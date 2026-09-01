"""流程耗时统计 (排程读侧聚合)
==============================
功能:
    从 RunStore 历史事件按需聚合流程/动作/步骤耗时, 供 /api/planner/* 只读端点.
    纯读侧: 不动事件写入路径; 每流程按 (window, 窗口内 run 集合) 记忆缓存,
    集合不变即复用, 不重复读事件.

配对规则:
    只有 op 为 call/run_script 的节点发 vm_node_enter/vm_node_done; AID 仅帧内唯一,
    循环/parallel/递归会让同一 (script, aid) 重复或并发出现, 故用栈式配对
    (done 匹配最近一个未配对的同键 enter). terminate/estop/join:any 取消路径
    不发在飞叶子的 done, 未配对 enter 一律丢弃.

剔除规则:
    命中 vm_hold.hold 为 frozen/at_boundary, 或 vm_state.status 为 PAUSED/STOPPED
    的运行视为被人工/调试干预, 整次剔除出统计; WAITING_HUMAN (人工门) 保留,
    人工确认等待属于真实工艺耗时.

统计基线:
    RunStore.stat_baselines 记录"从哪一刻起的运行才算", 供流程改动后作废旧耗时;
    每流程有效基线 = max(该流程基线, 全局 '*' 基线), 早于它的运行不入统计.
    基线只影响统计, 不删任何运行记录 (执行记录与回放始终完整).

子流程耗时回填 (样本模型):
    子流程是 VM 栈帧不是运行 —— run_script 把子脚本压进同一个 VmThread, 同一个
    run_id, 只有根脚本发 operation_start. 所以嵌套调用不产生自己的 runs 行,
    runs.operation 永远是根流程名, 只按它取窗口会让子流程恒为"无历史".
    但每次嵌套执行在父运行事件流里就是一条 op=run_script 的完整区间, 且 action
    字段带的正是子脚本名 (见 vm/thread.py 的 _node_ref), 所以按名字归集即可回填.

    统一成"样本"概念 —— 一次该流程从头跑到尾的记录, 两个来源:
        顶层样本: runs 表里 operation == 本流程的一行, 时长 = finished_at - started_at
        嵌套样本: 任意父运行里 op=run_script 且 action == 本流程的一条区间
    两者合并后按时刻降序取窗口前 N 条再求平均, 单独跑与被调用一视同仁.

    嵌套收割 (_nested_index) 刻意不过滤父流程基线: 基线语义是"这个流程改了, 它的
    旧耗时作废", 改父流程不代表子流程也变了; 子流程自己的基线在合并期生效, 两者正交.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# 成步的两种节点 op (与 vm/thread.py 的 enter/done 发射范围一致)
_PAIRED_OPS = ("call", "run_script")
# 干预判据: 冻结/边界停 (pause/stop_after 动词), 与 暂停/单步断点停驻 状态
_INTERVENED_HOLDS = frozenset({"frozen", "at_boundary"})
_INTERVENED_STATES = frozenset({"PAUSED", "STOPPED"})
# 全局统计基线的表键 (流程名取自 YAML 文件名, 不会是 '*')
GLOBAL_BASELINE_KEY = "*"
# 嵌套收割的扫描深度: 覆盖最近多少次干净 DONE 运行. 子流程按每次父运行调用一次算,
# 200 次父运行足够填满窗口上限 (_WINDOW_MAX); 更早的嵌套执行不进统计.
_NESTED_SCAN_RUNS = 200
# 逐运行配对结果的 LRU 上限: 新运行入库只让一条失效, 其余免于重解析事件
_PAIRED_CACHE_MAX = 256


def effective_baseline(baselines: dict, operation: str) -> float | None:
    """某流程的有效统计基线.

    功能:
        取该流程自己的基线与全局基线中较晚的一个; 两者都没有则无基线.
    参数:
        baselines: RunStore.get_stat_baselines() 的返回值
        operation: 流程名
    返回:
        float 基线时刻 (epoch 秒), 无基线返回 None
    """
    candidates = [ts for ts in (baselines.get(operation), baselines.get(GLOBAL_BASELINE_KEY))
                  if ts is not None]
    if not candidates:
        return None
    return max(candidates)


def pair_intervals(events: list[dict]) -> dict:
    """把一次运行的有序事件配对成步骤区间.

    功能:
        栈式配对 vm_node_enter/vm_node_done 得到每步执行区间; 同趟扫描判定该次
        运行是否被暂停/调试干预; run_script 嵌套深度仅供显示缩进 (并行分支交错
        时深度为近似值).
    参数:
        events: RunStore.get_run()["events"], 按落库顺序 (id 升序即时间序)
    返回:
        Dict, 含:
            intervals: List[Dict], 每项 {script, aid, op, action, start_ts, end_ts,
                       duration_s, status, depth}, 按 start_ts 升序
            intervened: bool, 是否命中干预剔除判据
            unpaired: int, 丢弃的未配对 enter 数
            start_ts/end_ts: 运行起止事件时间 (缺失为 None)
    """
    open_stacks: dict[tuple[str, str], list[dict]] = {}
    intervals: list[dict] = []
    depth = 0
    intervened = False
    start_ts = None
    end_ts = None
    for ev in events:
        etype = ev.get("type", "")
        if etype == "operation_start":
            # 防御: reset 复用 run_id 时 RunStore 已清旧事件, 此处再兜底一次
            open_stacks.clear()
            intervals.clear()
            depth = 0
            start_ts = ev.get("ts")
        elif etype in ("operation_done", "operation_failed"):
            end_ts = ev.get("ts")
        elif etype == "vm_hold":
            if ev.get("hold") in _INTERVENED_HOLDS:
                intervened = True
        elif etype == "vm_state":
            if ev.get("status") in _INTERVENED_STATES:
                intervened = True
        elif etype == "vm_node_enter" and ev.get("op") in _PAIRED_OPS:
            key = (ev.get("script") or "", ev.get("aid") or "")
            open_stacks.setdefault(key, []).append(
                {"ts": ev.get("ts"), "op": ev.get("op"),
                 "action": ev.get("action"), "depth": depth})
            if ev.get("op") == "run_script":
                depth += 1
        elif etype == "vm_node_done" and ev.get("op") in _PAIRED_OPS:
            if ev.get("op") == "run_script" and depth > 0:
                depth -= 1
            key = (ev.get("script") or "", ev.get("aid") or "")
            stack = open_stacks.get(key)
            if not stack:
                continue  # 无匹配 enter 的孤儿 done: 忽略 (事件缺损)
            entered = stack.pop()
            ts_enter = entered.get("ts")
            ts_done = ev.get("ts")
            if ts_enter is None or ts_done is None:
                continue
            intervals.append({
                "script": key[0],
                "aid": key[1],
                "op": ev.get("op"),
                "action": entered.get("action") or ev.get("action"),
                "start_ts": ts_enter,
                "end_ts": ts_done,
                "duration_s": max(0.0, ts_done - ts_enter),  # 时钟回拨钳 0
                "status": ev.get("status") or "DONE",
                "depth": entered.get("depth", 0),
            })
    unpaired = sum(len(stack) for stack in open_stacks.values())
    intervals.sort(key=lambda item: item["start_ts"])
    return {"intervals": intervals, "intervened": intervened, "unpaired": unpaired,
            "start_ts": start_ts, "end_ts": end_ts}


def _agg_of(values: list[float]) -> tuple[float | None, float | None, float | None]:
    """求 (平均, 最小, 最大), 空列表返回三个 None; 保留 3 位小数."""
    if not values:
        return None, None, None
    return (round(sum(values) / len(values), 3),
            round(min(values), 3), round(max(values), 3))


def _merge_samples(agg, nested, window: int, baseline_ts: float | None) -> list[dict]:
    """把顶层样本与嵌套样本并成一条时间轴, 取最近 window 次.

    功能:
        单独跑与被父流程调用一视同仁, 合并后按执行时刻降序截窗口; 嵌套样本在此
        按本流程自己的基线过滤 (收割时刻意没滤, 避免父流程基线牵连子流程).
    参数:
        agg: _OpAgg, 本流程顶层运行聚合
        nested: _NestedAgg 或 None, 本流程被嵌套调用的聚合
        window: 窗口大小; baseline_ts: 本流程有效基线, None 表示不限
    返回:
        List[Dict], 样本按时刻新→旧, 长度不超过 window; 嵌套样本带 nested=True
    """
    items = list(agg.samples)
    if nested is not None:
        items.extend(item for item in nested.samples
                     if baseline_ts is None or item["start_ts"] >= baseline_ts)
    items.sort(key=lambda item: item["start_ts"], reverse=True)
    return items[:window]


def _build_steps(intervals: list[dict], base_ts: float | None,
                 order_index: dict[tuple[str, str], int]) -> list[dict]:
    """把区间列表折成时间线步骤, 顺带记下各步首次出现的位置.

    功能:
        偏移相对 base_ts, depth 减去本组最小值归一化到 0 起 —— 顶层运行本就从 0 起,
        子流程的内部区间则要扣掉它在父运行里的基准深度, 否则弹窗整体多缩进一层.
    参数:
        intervals: pair_intervals 产出的区间, 按 start_ts 升序
        base_ts: 偏移基准时刻, None 则 start_offset_s 给 None
        order_index: 输出参数, 记录 (script, aid) → 首次出现下标, 供步骤统计排序
    返回:
        List[Dict], 每项 {script, aid, op, action, start_offset_s, duration_s, status, depth}
    """
    base_depth = min((itv["depth"] for itv in intervals), default=0)
    steps = []
    for pos, itv in enumerate(intervals):
        order_index.setdefault((itv["script"], itv["aid"]), pos)
        steps.append({
            "script": itv["script"], "aid": itv["aid"], "op": itv["op"],
            "action": itv["action"],
            "start_offset_s": (round(max(0.0, itv["start_ts"] - base_ts), 3)
                               if base_ts is not None else None),
            "duration_s": round(itv["duration_s"], 3),
            "status": itv["status"], "depth": itv["depth"] - base_depth,
        })
    return steps


@dataclass
class _OpAgg:
    """单流程窗口聚合结果 (缓存值), 只含该流程自己的顶层运行."""
    count: int = 0                                     # 干净 DONE 运行数
    excluded: int = 0                                  # 被干预剔除数
    # 各次顶层样本 {start_ts, end_ts, duration_s, run_id}, 新→旧;
    # 带时刻是为了能与嵌套样本按时间轴合并 (光有时长排不了序)
    samples: list[dict] = field(default_factory=list)
    last_run: dict | None = None                       # 最近一次干净运行的 runs 行
    last_intervals: list[dict] = field(default_factory=list)
    last_unpaired: int = 0
    action_durs: dict[str, list[float]] = field(default_factory=dict)   # 仅 op=call
    step_durs: dict[tuple[str, str], dict] = field(default_factory=dict)


@dataclass
class _NestedAgg:
    """单子流程的嵌套执行聚合 (从各父运行事件流收割)."""
    # 各次嵌套样本 {start_ts, end_ts, duration_s, run_id, nested: True}, 扫描序
    samples: list[dict] = field(default_factory=list)
    excluded: int = 0                                  # 出现在被干预父运行里的次数
    # 该子流程内部步骤的跨运行统计, 键同 _OpAgg.step_durs; 只收它作为子流程被调用
    # 时的区间 (跳过 runs.operation == 本流程的运行), 与 _OpAgg.step_durs 严格不相交
    step_durs: dict[tuple[str, str], dict] = field(default_factory=dict)
    last_sample: dict | None = None                    # 最新一次嵌套执行
    last_steps: list[dict] = field(default_factory=list)   # 该次执行的内部区间


class TimingStats:
    """排程统计服务 (读侧聚合 + 进程内 memo 缓存)."""

    def __init__(self, run_store, script_repo) -> None:
        """构建统计服务.

        参数:
            run_store: RunStore, 运行历史库 (list_runs / list_runs_by_operation / get_run)
            script_repo: ScriptRepo, 流程摘要来源 (label/group/ui/resources)
        """
        self._run_store = run_store
        self._repo = script_repo
        self._cache: dict[str, tuple[tuple, _OpAgg]] = {}
        self._nested_cache: tuple[tuple, dict[str, _NestedAgg]] | None = None
        self._paired_cache: OrderedDict[tuple, dict] = OrderedDict()
        self._lock = threading.Lock()  # 端点走线程池, 缓存字典需要并发保护

    # ------------------------------------------------------------------
    # 对外查询
    # ------------------------------------------------------------------

    def stats(self, window: int = 50, *, resources_meta: list[dict] | None = None) -> dict:
        """全部流程的窗口统计 + 全局动作统计.

        功能:
            组装 /api/planner/stats 响应体: 每个流程最近 window 次执行 (顶层运行 +
            作为子流程被嵌套调用, 合并计) 的总时长统计与资源声明, 外加按动作名跨流程
            合并的 call 区间统计.
        参数:
            window: 每流程取最近 N 次执行
            resources_meta: [{id, label, mode}] 资源元数据, 由路由层注入 (可为 None)
        返回:
            Dict {window, generated_at, operations, actions, resources}
        """
        operations = []
        action_acc: dict[str, list[float]] = {}
        baselines = self._run_store.get_stat_baselines()   # 整表一次读出, 逐流程取有效值
        nested = self._nested_index(_NESTED_SCAN_RUNS)     # 跨流程收割一次, 逐流程取用
        for meta in self._repo.list_scripts("default", kind="operation"):
            name = meta["name"]
            baseline_ts = effective_baseline(baselines, name)
            agg = self._windowed(name, window, baseline_ts)
            ext = nested.get(name)
            merged = _merge_samples(agg, ext, window, baseline_ts)
            avg_s, min_s, max_s = _agg_of([item["duration_s"] for item in merged])
            head = merged[0] if merged else None           # 最近一次执行, 不论来源
            ui = meta.get("ui") or {}
            operations.append({
                "name": name,
                "label": meta.get("label") or name,
                "group": meta.get("group"),
                "role": ui.get("role"),
                "hidden": bool(ui.get("hidden")),
                "resources": meta.get("resources") or [],
                "count": len(merged),
                "excluded": agg.excluded + (ext.excluded if ext is not None else 0),
                "avg_s": avg_s,
                "min_s": min_s,
                "max_s": max_s,
                "last_s": round(head["duration_s"], 3) if head else None,
                # 嵌套样本给出父运行 id: 点进去查得到这次执行落在哪次运行里
                "last_run_id": head["run_id"] if head else None,
                "last_finished_at": head["end_ts"] if head else None,
                # 供前端说明"这 n 次里有几次来自父流程内的嵌套执行"
                "nested_count": sum(1 for item in merged if item.get("nested")),
                "baseline_ts": baseline_ts,
            })
            for action, durs in agg.action_durs.items():
                action_acc.setdefault(action, []).extend(durs)
        actions = []
        for action, durs in action_acc.items():
            avg_s, min_s, max_s = _agg_of(durs)
            actions.append({"action": action, "count": len(durs),
                            "avg_s": avg_s, "min_s": min_s, "max_s": max_s})
        actions.sort(key=lambda item: (-item["count"], item["action"]))
        return {"window": window, "generated_at": time.time(),
                # 全局基线单独给出: 前端据此把「清除全部」切成「撤销全部」
                "global_baseline_ts": baselines.get(GLOBAL_BASELINE_KEY),
                "operations": operations, "actions": actions,
                "resources": resources_meta or []}

    def timeline(self, name: str, window: int = 50) -> dict:
        """单流程的步骤时间线明细.

        功能:
            返回该流程最近一次干净执行的步骤区间 (相对该次执行开始的偏移), 以及按
            (script, aid) 聚合的跨执行步骤统计. 最近一次执行是顶层运行还是嵌套调用,
            决定步骤来自哪一侧 —— 两侧窗口口径不同, 混着算会双计, 故二选一不合并.
        参数:
            name: 流程名; window: 平均窗口
        返回:
            Dict {operation, label, window, count, excluded, baseline_ts,
                  last_run, step_stats}; 无干净执行时 last_run 为 None, step_stats 为空
        异常:
            KeyError: 流程不存在 (路由层转 404)
        """
        meta = None
        for item in self._repo.list_scripts("default", kind="operation"):
            if item["name"] == name:
                meta = item
                break
        if meta is None:
            raise KeyError(f"流程不存在: {name}")
        # 与 stats 同一套基线与同一套合并结果, 否则弹窗明细与列表统计自相矛盾
        baseline_ts = effective_baseline(self._run_store.get_stat_baselines(), name)
        agg = self._windowed(name, window, baseline_ts)
        ext = self._nested_index(_NESTED_SCAN_RUNS).get(name)
        merged = _merge_samples(agg, ext, window, baseline_ts)
        head = merged[0] if merged else None
        last_run = None
        order_index: dict[tuple[str, str], int] = {}
        step_durs = agg.step_durs
        if head is not None and head.get("nested"):
            # 最新一次是嵌套执行: 用父运行里该子流程的内部区间. 基线只砍更早的样本,
            # 最新那条必然留存, 故 head 恒等于 ext.last_sample, 可直接用配套 last_steps.
            last_run = {"run_id": head["run_id"],
                        "started_at": head["start_ts"], "finished_at": head["end_ts"],
                        "duration_s": round(head["duration_s"], 3),
                        "unpaired": 0,   # 嵌套区间成对才被收割, 不存在半截的
                        "steps": _build_steps(ext.last_steps, head["start_ts"], order_index)}
            step_durs = ext.step_durs
        elif head is not None:
            # 最新一次是顶层运行: head 即 agg.samples[0], 对应 agg.last_run
            started = agg.last_run.get("started_at")
            finished = agg.last_run.get("finished_at")
            duration_s = None
            if started is not None and finished is not None:
                duration_s = round(max(0.0, finished - started), 3)
            last_run = {"run_id": agg.last_run.get("run_id"),
                        "started_at": started, "finished_at": finished,
                        "duration_s": duration_s, "unpaired": agg.last_unpaired,
                        "steps": _build_steps(agg.last_intervals, started, order_index)}
        step_stats = []
        for (script, aid), rec in step_durs.items():
            avg_s, min_s, max_s = _agg_of(rec["durations"])
            step_stats.append({"script": script, "aid": aid, "op": rec["op"],
                               "action": rec["action"], "count": len(rec["durations"]),
                               "avg_s": avg_s, "min_s": min_s, "max_s": max_s})
        # 排序: 按最近一次执行中首次出现的位置; 未出现的排最后按键名兜底
        step_stats.sort(key=lambda item: (
            order_index.get((item["script"], item["aid"]), 1 << 30),
            item["script"], item["aid"]))
        return {"operation": name, "label": meta.get("label") or name,
                "window": window, "count": len(merged),
                "excluded": agg.excluded + (ext.excluded if ext is not None else 0),
                "baseline_ts": baseline_ts,
                "last_run": last_run, "step_stats": step_stats}

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _windowed(self, operation: str, window: int,
                  baseline_ts: float | None = None) -> _OpAgg:
        """取该流程的窗口聚合; 窗口内 run 集合不变时直接复用缓存.

        参数:
            operation: 流程名; window: 窗口大小
            baseline_ts: 统计基线, 早于它的运行不计入; None 表示不限
        返回:
            _OpAgg 聚合结果
        """
        rows = self._run_store.list_runs_by_operation(
            operation, status="DONE", limit=window, since=baseline_ts)
        # 缓存键含 run 集合、最新 finished_at 与基线: 新运行入库/reset 复写头记录/
        # 改基线都会失效 (基线必须在键里 — 撤销基线时 run 集合会变大, 但设基线到
        # 未来时刻可能让集合为空又与"本来就没有运行"撞键, 故显式并入)
        key = (int(window), baseline_ts, tuple(row.get("run_id") for row in rows),
               rows[0].get("finished_at") if rows else None)
        with self._lock:
            cached = self._cache.get(operation)
            if cached is not None and cached[0] == key:
                return cached[1]
        agg = _OpAgg()
        for row in rows:  # 新→旧
            run = self._run_store.get_run(row.get("run_id"))
            if run is None:
                continue
            paired = pair_intervals(run.get("events") or [])
            if paired["intervened"]:
                agg.excluded += 1
                continue
            started = row.get("started_at")
            finished = row.get("finished_at")
            if started is None or finished is None or finished < started:
                continue  # 记录缺损 (断电等) 不入统计
            agg.samples.append({"start_ts": started, "end_ts": finished,
                                "duration_s": finished - started,
                                "run_id": row.get("run_id")})
            agg.count += 1
            if agg.last_run is None:
                agg.last_run = row
                agg.last_intervals = paired["intervals"]
                agg.last_unpaired = paired["unpaired"]
            for itv in paired["intervals"]:
                if itv["op"] == "call" and itv["action"]:
                    agg.action_durs.setdefault(itv["action"], []).append(itv["duration_s"])
                skey = (itv["script"], itv["aid"])
                rec = agg.step_durs.setdefault(
                    skey, {"op": itv["op"], "action": itv["action"], "durations": []})
                rec["durations"].append(itv["duration_s"])
        with self._lock:
            self._cache[operation] = (key, agg)
        return agg

    def _paired_of(self, run_id: str, finished_at: float | None) -> dict | None:
        """取某次运行的配对结果, 带进程内 LRU memo.

        功能:
            嵌套收割每次都要重扫最近 N 次运行, 而 get_run 加逐事件 json 解析是这里
            唯一的重活; 新运行入库只让收割缓存失效, 其余运行走 memo 不再解析事件.
        参数:
            run_id: 运行 id
            finished_at: 该运行的结束时刻, 并入键以便 reset 复用 run_id 时自然失效
        返回:
            pair_intervals 的返回值; 运行记录已被 LRU 剪掉时返回 None
        """
        key = (run_id, finished_at)
        with self._lock:
            cached = self._paired_cache.get(key)
            if cached is not None:
                self._paired_cache.move_to_end(key)
                return cached
        run = self._run_store.get_run(run_id)
        if run is None:
            return None
        paired = pair_intervals(run.get("events") or [])
        with self._lock:
            self._paired_cache[key] = paired
            self._paired_cache.move_to_end(key)
            while len(self._paired_cache) > _PAIRED_CACHE_MAX:
                self._paired_cache.popitem(last=False)
        return paired

    def _nested_index(self, scan: int) -> dict[str, _NestedAgg]:
        """扫描最近 scan 次 DONE 运行, 按子流程名收割其中的 run_script 区间.

        功能:
            嵌套调用不产生自己的 runs 行, 但在父运行事件流里是一条完整区间, 且
            action 即子脚本名 —— 这里按名字归集, 供 stats/timeline 与顶层样本合并.
            刻意不按基线过滤: 父流程的基线不该牵连子流程, 子流程自己的基线在
            _merge_samples 里生效.
        参数:
            scan: 扫描深度, 覆盖最近多少次 DONE 运行
        返回:
            Dict[脚本名, _NestedAgg]; 无嵌套调用时为空字典
        """
        rows = self._run_store.list_runs(status="DONE", limit=scan)
        # 缓存键与 _windowed 同一失效模型: 新运行入库 / reset 复写头记录都会变
        key = (int(scan), tuple(row.get("run_id") for row in rows),
               rows[0].get("finished_at") if rows else None)
        with self._lock:
            if self._nested_cache is not None and self._nested_cache[0] == key:
                return self._nested_cache[1]
        index: dict[str, _NestedAgg] = {}
        for row in rows:  # 新→旧
            run_id = row.get("run_id")
            paired = self._paired_of(run_id, row.get("finished_at"))
            if paired is None:
                continue
            intervals = paired["intervals"]
            if paired["intervened"]:
                # 被干预运行的时长不可信, 但"这次执行被剔除了"要如实计数
                for name in {itv["action"] for itv in intervals
                             if itv["op"] == "run_script" and itv["action"]}:
                    index.setdefault(name, _NestedAgg()).excluded += 1
                continue
            root = row.get("operation")
            fresh: dict[str, list[dict]] = {}   # 本次运行里各子流程的新样本
            for itv in intervals:
                if itv["op"] == "run_script" and itv["action"] and itv["status"] == "DONE":
                    fresh.setdefault(itv["action"], []).append(
                        {"start_ts": itv["start_ts"], "end_ts": itv["end_ts"],
                         "duration_s": itv["duration_s"], "run_id": run_id,
                         "nested": True})
                # 步骤统计只收"作为子流程被调用"时的内部区间: 跳过本次运行根脚本自己
                # 的步骤, 那些归 _windowed 的 step_durs, 否则两边双计
                script = itv["script"]
                if script and script != root:
                    rec = index.setdefault(script, _NestedAgg()).step_durs.setdefault(
                        (script, itv["aid"]),
                        {"op": itv["op"], "action": itv["action"], "durations": []})
                    rec["durations"].append(itv["duration_s"])
            for name, items in fresh.items():
                agg = index.setdefault(name, _NestedAgg())
                agg.samples.extend(items)
                if agg.last_sample is None:
                    # 运行按新→旧扫, 首个含该名字的运行即最新; 取它在本次运行里最后
                    # 一次调用, 再截出落在该次调用时间窗内的内部区间
                    newest = max(items, key=lambda item: item["start_ts"])
                    agg.last_sample = newest
                    agg.last_steps = [
                        itv for itv in intervals
                        if itv["script"] == name
                        and newest["start_ts"] <= itv["start_ts"] <= newest["end_ts"]]
        with self._lock:
            self._nested_cache = (key, index)
        return index
