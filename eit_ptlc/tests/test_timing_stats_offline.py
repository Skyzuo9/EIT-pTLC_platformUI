"""排程统计离线测试
====================
功能:
    验证 timing_stats 的事件配对 (栈式/循环/并行/未配对丢弃/干预判定)、窗口聚合
    (window 截断/剔除/动作合并/空历史)、时间线明细、memo 缓存复用与失效、
    统计基线 (单流程/全局取 max/改基线令缓存失效)、子流程耗时回填 (从父运行事件流
    收割 run_script 区间/与顶层样本合并/父子基线正交/多层嵌套/步骤不双计), 以及
    run_store.list_runs_by_operation 与 /api/planner/* 路由的形状与错误分支.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_timing_stats_offline.py -q
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eit_ptlc.api.planner_routes import register_planner_routes
from eit_ptlc.runtime.run_store import RunStore
from eit_ptlc.runtime.timing_stats import (
    GLOBAL_BASELINE_KEY,
    TimingStats,
    effective_baseline,
    pair_intervals,
)


# ----------------------------------------------------------------------
# 事件构造器
# ----------------------------------------------------------------------

def _start(run_id: str, ts: float, operation: str = "op_a") -> dict:
    return {"type": "operation_start", "operation": operation, "run_id": run_id,
            "label": f"流程{operation}", "ts": ts}


def _finish(run_id: str, ts: float, status: str = "DONE") -> dict:
    etype = "operation_failed" if status == "FAILED" else "operation_done"
    return {"type": etype, "run_id": run_id, "status": status, "message": "", "ts": ts}


def _enter(run_id: str, ts: float, aid: str, *, script: str = "op_a",
           op: str = "call", action: str = "dev.x") -> dict:
    return {"type": "vm_node_enter", "run_id": run_id, "script": script,
            "aid": aid, "op": op, "action": action, "ts": ts}


def _done(run_id: str, ts: float, aid: str, *, script: str = "op_a",
          op: str = "call", action: str = "dev.x", status: str = "DONE") -> dict:
    return {"type": "vm_node_done", "run_id": run_id, "script": script, "aid": aid,
            "op": op, "action": action, "status": status, "message": "",
            "result": None, "ts": ts}


class _FakeRepo:
    """ScriptRepo 替身: 只实现 TimingStats 用到的 list_scripts."""

    def __init__(self, metas: list[dict]) -> None:
        self._metas = metas

    def list_scripts(self, ws: str, kind: str | None = None) -> list[dict]:
        return list(self._metas)


def _meta(name: str, *, resources: list[str] | None = None, ui: dict | None = None) -> dict:
    return {"name": name, "kind": "operation", "label": f"流程{name}",
            "group": "01_test", "ui": ui or {}, "resources": resources or []}


def _feed_simple_run(store: RunStore, run_id: str, operation: str, t0: float,
                     steps: list[tuple[str, str, float]], *, status: str = "DONE",
                     extra_events: list[dict] | None = None) -> None:
    """灌一次串行运行: steps 为 [(aid, action, 时长秒)], 依次首尾相接."""
    store.on_event(_start(run_id, t0, operation))
    ts = t0
    for aid, action, dur in steps:
        store.on_event(_enter(run_id, ts, aid, script=operation, action=action))
        ts += dur
        store.on_event(_done(run_id, ts, aid, script=operation, action=action))
    for ev in (extra_events or []):
        store.on_event(ev)
    store.on_event(_finish(run_id, ts, status))


def _feed_nested_run(store: RunStore, run_id: str, operation: str, t0: float,
                     subs: list[tuple[str, str, list[tuple[str, str, float]]]],
                     *, status: str = "DONE", sub_status: str = "DONE",
                     extra_events: list[dict] | None = None) -> None:
    """灌一次含子流程的运行 (父帧 run_script 包住子帧的 call 步骤).

    参数:
        subs: [(父帧 aid, 子流程名, [(子帧 aid, action, 时长秒)])], 依次首尾相接
        sub_status: run_script 完成事件的状态, 用 FAILED 模拟被 try 兜住的失败子流程
    """
    store.on_event(_start(run_id, t0, operation))
    ts = t0
    for aid, sub_name, steps in subs:
        store.on_event(_enter(run_id, ts, aid, script=operation,
                              op="run_script", action=sub_name))
        for sub_aid, action, dur in steps:
            store.on_event(_enter(run_id, ts, sub_aid, script=sub_name, action=action))
            ts += dur
            store.on_event(_done(run_id, ts, sub_aid, script=sub_name, action=action))
        store.on_event(_done(run_id, ts, aid, script=operation, op="run_script",
                             action=sub_name, status=sub_status))
    for ev in (extra_events or []):
        store.on_event(ev)
    store.on_event(_finish(run_id, ts, status))


# ----------------------------------------------------------------------
# pair_intervals: 配对
# ----------------------------------------------------------------------

def test_pair_basic_interval():
    events = [_start("r", 100.0), _enter("r", 110.0, "b/0"),
              _done("r", 113.5, "b/0"), _finish("r", 115.0)]
    out = pair_intervals(events)
    assert out["intervened"] is False
    assert out["unpaired"] == 0
    assert out["start_ts"] == 100.0 and out["end_ts"] == 115.0
    assert len(out["intervals"]) == 1
    itv = out["intervals"][0]
    assert itv["aid"] == "b/0" and itv["duration_s"] == 3.5
    assert itv["start_ts"] == 110.0 and itv["end_ts"] == 113.5


def test_pair_loop_same_aid_multiple_intervals():
    # 循环体内同一 aid 出现两次: 各自成区间
    events = [_start("r", 0.0),
              _enter("r", 10.0, "b/1/body/0"), _done("r", 12.0, "b/1/body/0"),
              _enter("r", 20.0, "b/1/body/0"), _done("r", 23.0, "b/1/body/0"),
              _finish("r", 25.0)]
    out = pair_intervals(events)
    assert [itv["duration_s"] for itv in out["intervals"]] == [2.0, 3.0]


def test_pair_run_script_nesting_and_depth():
    # 父帧 run_script 包住子帧同名 aid: 键含 script 不互撞, 子步 depth+1
    events = [_start("r", 0.0),
              _enter("r", 10.0, "b/1", op="run_script", action="sub"),
              _enter("r", 11.0, "b/0", script="sub", action="dev.y"),
              _done("r", 12.0, "b/0", script="sub", action="dev.y"),
              _done("r", 13.0, "b/1", op="run_script", action="sub"),
              _finish("r", 14.0)]
    out = pair_intervals(events)
    by_aid = {(itv["script"], itv["aid"]): itv for itv in out["intervals"]}
    parent = by_aid[("op_a", "b/1")]
    child = by_aid[("sub", "b/0")]
    assert parent["op"] == "run_script" and parent["duration_s"] == 3.0
    assert parent["depth"] == 0 and child["depth"] == 1


def test_pair_parallel_interleaved_same_key():
    # parallel 分支让同键并发: LIFO 配对, 总时长守恒且均非负
    events = [_start("r", 0.0),
              _enter("r", 10.0, "b/2"), _enter("r", 11.0, "b/2"),
              _done("r", 12.0, "b/2"), _done("r", 14.0, "b/2"),
              _finish("r", 15.0)]
    out = pair_intervals(events)
    durs = sorted(itv["duration_s"] for itv in out["intervals"])
    assert durs == [1.0, 4.0]
    assert all(d >= 0 for d in durs) and out["unpaired"] == 0


def test_pair_unpaired_enter_dropped():
    # terminate/estop 不发在飞叶子的 done: 未配对 enter 丢弃并计数
    events = [_start("r", 0.0), _enter("r", 10.0, "b/0"), _finish("r", 12.0, "CANCELLED")]
    out = pair_intervals(events)
    assert out["intervals"] == [] and out["unpaired"] == 1


def test_pair_orphan_done_ignored():
    events = [_start("r", 0.0), _done("r", 10.0, "b/0"), _finish("r", 12.0)]
    out = pair_intervals(events)
    assert out["intervals"] == [] and out["unpaired"] == 0


def test_pair_intervened_by_hold():
    base = [_start("r", 0.0), _finish("r", 5.0)]
    hold = {"type": "vm_hold", "run_id": "r", "hold": "frozen", "ts": 1.0}
    assert pair_intervals(base[:1] + [hold] + base[1:])["intervened"] is True
    hold_b = {"type": "vm_hold", "run_id": "r", "hold": "at_boundary", "ts": 1.0}
    assert pair_intervals(base[:1] + [hold_b] + base[1:])["intervened"] is True
    none_hold = {"type": "vm_hold", "run_id": "r", "hold": "none", "ts": 1.0}
    assert pair_intervals(base[:1] + [none_hold] + base[1:])["intervened"] is False


def test_pair_intervened_by_state():
    base = [_start("r", 0.0), _finish("r", 5.0)]
    for status, expect in (("PAUSED", True), ("STOPPED", True),
                           ("WAITING_HUMAN", False), ("RUNNING", False)):
        state = {"type": "vm_state", "run_id": "r", "status": status, "ts": 1.0}
        assert pair_intervals(base[:1] + [state] + base[1:])["intervened"] is expect, status


# ----------------------------------------------------------------------
# TimingStats: 窗口聚合
# ----------------------------------------------------------------------

def _stats_of(payload: dict, name: str) -> dict:
    return next(item for item in payload["operations"] if item["name"] == name)


def test_stats_window_truncation_and_values():
    store = RunStore(":memory:")
    # 三次 DONE: 时长 30 / 10 / 20 (按开始时间从旧到新)
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 30.0)])
    _feed_simple_run(store, "r2", "op_a", 200.0, [("b/0", "dev.x", 10.0)])
    _feed_simple_run(store, "r3", "op_a", 300.0, [("b/0", "dev.x", 20.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_a", resources=["robot"])]))
    payload = svc.stats(window=2)
    entry = _stats_of(payload, "op_a")
    # 窗口 2 只取最近两次 (r3=20, r2=10)
    assert entry["count"] == 2 and entry["excluded"] == 0
    assert entry["avg_s"] == 15.0 and entry["min_s"] == 10.0 and entry["max_s"] == 20.0
    assert entry["last_s"] == 20.0 and entry["last_run_id"] == "r3"
    assert entry["resources"] == ["robot"]


def test_stats_failed_runs_not_in_window():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    _feed_simple_run(store, "r2", "op_a", 200.0, [("b/0", "dev.x", 99.0)], status="FAILED")
    svc = TimingStats(store, _FakeRepo([_meta("op_a")]))
    entry = _stats_of(svc.stats(window=10), "op_a")
    assert entry["count"] == 1 and entry["avg_s"] == 10.0


def test_stats_intervened_run_excluded():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    hold = {"type": "vm_hold", "run_id": "r2", "hold": "frozen", "ts": 201.0}
    _feed_simple_run(store, "r2", "op_a", 200.0, [("b/0", "dev.x", 50.0)],
                     extra_events=[hold])
    svc = TimingStats(store, _FakeRepo([_meta("op_a")]))
    entry = _stats_of(svc.stats(window=10), "op_a")
    # r2 被干预剔除: 只有 r1 入统计, excluded 记 1
    assert entry["count"] == 1 and entry["excluded"] == 1
    assert entry["avg_s"] == 10.0


def test_stats_action_merge_across_operations():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    _feed_simple_run(store, "r2", "op_b", 200.0, [("b/0", "dev.x", 20.0), ("b/1", "dev.y", 5.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_a"), _meta("op_b")]))
    payload = svc.stats(window=10)
    actions = {item["action"]: item for item in payload["actions"]}
    assert actions["dev.x"]["count"] == 2 and actions["dev.x"]["avg_s"] == 15.0
    assert actions["dev.y"]["count"] == 1


def test_stats_no_history_gives_nulls():
    store = RunStore(":memory:")
    svc = TimingStats(store, _FakeRepo([_meta("op_never")]))
    entry = _stats_of(svc.stats(window=10), "op_never")
    assert entry["count"] == 0 and entry["avg_s"] is None
    assert entry["min_s"] is None and entry["max_s"] is None and entry["last_run_id"] is None


def test_timeline_offsets_and_step_stats():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 4.0), ("b/1", "dev.y", 6.0)])
    _feed_simple_run(store, "r2", "op_a", 200.0, [("b/0", "dev.x", 2.0), ("b/1", "dev.y", 8.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_a")]))
    payload = svc.timeline("op_a", window=10)
    assert payload["count"] == 2
    last = payload["last_run"]
    assert last["run_id"] == "r2" and last["duration_s"] == 10.0
    # 最近一次运行: b/0 从 0 偏移执行 2s, b/1 从 2s 偏移执行 8s
    assert [(s["aid"], s["start_offset_s"], s["duration_s"]) for s in last["steps"]] == [
        ("b/0", 0.0, 2.0), ("b/1", 2.0, 8.0)]
    steps = {(s["script"], s["aid"]): s for s in payload["step_stats"]}
    assert steps[("op_a", "b/0")]["count"] == 2 and steps[("op_a", "b/0")]["avg_s"] == 3.0
    assert steps[("op_a", "b/1")]["avg_s"] == 7.0


def test_timeline_unknown_operation_raises():
    svc = TimingStats(RunStore(":memory:"), _FakeRepo([_meta("op_a")]))
    try:
        svc.timeline("no_such_op", window=10)
    except KeyError:
        pass
    else:
        raise AssertionError("未知流程应抛 KeyError")


class _CountingStore(RunStore):
    """统计 get_run 调用次数的 RunStore, 用于缓存复用断言."""

    def __init__(self) -> None:
        super().__init__(":memory:")
        self.get_run_calls = 0

    def get_run(self, run_id: str):
        self.get_run_calls += 1
        return super().get_run(run_id)


def test_stats_cache_reuse_and_invalidation():
    store = _CountingStore()
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_a")]))
    svc.stats(window=10)
    first_calls = store.get_run_calls
    assert first_calls >= 1
    # 运行集合未变: 第二次不再读事件
    svc.stats(window=10)
    assert store.get_run_calls == first_calls
    # 新运行入库: 缓存键变化, 重新聚合
    _feed_simple_run(store, "r2", "op_a", 200.0, [("b/0", "dev.x", 20.0)])
    entry = _stats_of(svc.stats(window=10), "op_a")
    assert store.get_run_calls > first_calls
    assert entry["count"] == 2 and entry["avg_s"] == 15.0


# ----------------------------------------------------------------------
# RunStore.list_runs_by_operation
# ----------------------------------------------------------------------

def test_effective_baseline_takes_max():
    # 单流程与全局都存在时取较晚者; 缺失则取存在的那个; 全无则 None
    assert effective_baseline({"op_a": 100.0, GLOBAL_BASELINE_KEY: 200.0}, "op_a") == 200.0
    assert effective_baseline({"op_a": 300.0, GLOBAL_BASELINE_KEY: 200.0}, "op_a") == 300.0
    assert effective_baseline({"op_a": 100.0}, "op_a") == 100.0
    assert effective_baseline({GLOBAL_BASELINE_KEY: 200.0}, "op_a") == 200.0
    assert effective_baseline({}, "op_a") is None


def test_stats_baseline_excludes_older_runs():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    _feed_simple_run(store, "r2", "op_a", 200.0, [("b/0", "dev.x", 30.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_a")]))
    entry = _stats_of(svc.stats(window=10), "op_a")
    assert entry["count"] == 2 and entry["avg_s"] == 20.0 and entry["baseline_ts"] is None
    # 基线设在 r1 与 r2 之间: 只剩 r2
    store.set_stat_baseline("op_a", 150.0)
    entry = _stats_of(svc.stats(window=10), "op_a")
    assert entry["count"] == 1 and entry["avg_s"] == 30.0 and entry["baseline_ts"] == 150.0
    # 基线设在全部运行之后: 归零, 各统计为 null (前端据此显示"无历史")
    store.set_stat_baseline("op_a", 500.0)
    entry = _stats_of(svc.stats(window=10), "op_a")
    assert entry["count"] == 0 and entry["avg_s"] is None and entry["last_run_id"] is None
    # 撤销后恢复
    store.clear_stat_baseline("op_a")
    entry = _stats_of(svc.stats(window=10), "op_a")
    assert entry["count"] == 2 and entry["avg_s"] == 20.0 and entry["baseline_ts"] is None


def test_stats_global_baseline_applies_to_all_and_takes_max():
    store = RunStore(":memory:")
    _feed_simple_run(store, "a1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    _feed_simple_run(store, "a2", "op_a", 300.0, [("b/0", "dev.x", 20.0)])
    _feed_simple_run(store, "b1", "op_b", 100.0, [("b/0", "dev.x", 40.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_a"), _meta("op_b")]))
    store.set_stat_baseline(GLOBAL_BASELINE_KEY, 200.0)
    payload = svc.stats(window=10)
    # 全局基线对两个流程都生效
    assert _stats_of(payload, "op_a")["count"] == 1
    assert _stats_of(payload, "op_b")["count"] == 0
    # 单流程基线更晚时以它为准 (max)
    store.set_stat_baseline("op_a", 400.0)
    payload = svc.stats(window=10)
    assert _stats_of(payload, "op_a")["count"] == 0
    assert _stats_of(payload, "op_a")["baseline_ts"] == 400.0
    # 清空全部基线 → 两个流程都恢复
    store.clear_all_stat_baselines()
    payload = svc.stats(window=10)
    assert _stats_of(payload, "op_a")["count"] == 2 and _stats_of(payload, "op_b")["count"] == 1


def test_timeline_honors_baseline():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_a")]))
    assert svc.timeline("op_a", window=10)["last_run"]["run_id"] == "r1"
    store.set_stat_baseline("op_a", 500.0)
    payload = svc.timeline("op_a", window=10)
    # 基线之后无运行: 明细与列表统计一致地归零, 不残留旧步骤
    assert payload["count"] == 0 and payload["last_run"] is None and payload["step_stats"] == []
    assert payload["baseline_ts"] == 500.0


def test_baseline_change_invalidates_cache():
    store = _CountingStore()
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    _feed_simple_run(store, "r2", "op_a", 200.0, [("b/0", "dev.x", 30.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_a")]))
    svc.stats(window=10)
    calls_after_first = store.get_run_calls
    svc.stats(window=10)
    assert store.get_run_calls == calls_after_first        # 缓存命中
    store.set_stat_baseline("op_a", 150.0)
    entry = _stats_of(svc.stats(window=10), "op_a")
    # 基线在缓存键里: 必须重新读事件并给出新结果 (漏了这条则清除功能形同无效)
    assert store.get_run_calls > calls_after_first
    assert entry["count"] == 1 and entry["avg_s"] == 30.0


def test_list_runs_by_operation_since_filters():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 1.0)])
    _feed_simple_run(store, "r2", "op_a", 200.0, [("b/0", "dev.x", 1.0)])
    rows = store.list_runs_by_operation("op_a", since=150.0)
    assert [row["run_id"] for row in rows] == ["r2"]
    # 边界: since 恰等于 started_at 时该运行保留 (>=)
    rows = store.list_runs_by_operation("op_a", since=200.0)
    assert [row["run_id"] for row in rows] == ["r2"]
    assert store.list_runs_by_operation("op_a", since=None) == store.list_runs_by_operation("op_a")


def test_stat_baseline_store_roundtrip():
    store = RunStore(":memory:")
    assert store.get_stat_baselines() == {}
    store.set_stat_baseline("op_a", 111.0)
    store.set_stat_baseline(GLOBAL_BASELINE_KEY, 222.0)
    assert store.get_stat_baselines() == {"op_a": 111.0, GLOBAL_BASELINE_KEY: 222.0}
    store.set_stat_baseline("op_a", 333.0)                # 覆盖而非新增
    assert store.get_stat_baselines()["op_a"] == 333.0
    store.clear_stat_baseline("op_a")
    assert store.get_stat_baselines() == {GLOBAL_BASELINE_KEY: 222.0}
    store.clear_stat_baseline("不存在的流程")               # 幂等
    store.clear_all_stat_baselines()
    assert store.get_stat_baselines() == {}


def test_list_runs_by_operation_filter_order_limit():
    store = RunStore(":memory:")
    _feed_simple_run(store, "a1", "op_a", 100.0, [("b/0", "dev.x", 1.0)])
    _feed_simple_run(store, "b1", "op_b", 150.0, [("b/0", "dev.x", 1.0)])
    _feed_simple_run(store, "a2", "op_a", 200.0, [("b/0", "dev.x", 1.0)])
    _feed_simple_run(store, "a3", "op_a", 300.0, [("b/0", "dev.x", 1.0)], status="FAILED")
    rows = store.list_runs_by_operation("op_a")
    # 默认 status=DONE: 排除 FAILED 与其它流程, 按开始时间倒序
    assert [row["run_id"] for row in rows] == ["a2", "a1"]
    rows_all = store.list_runs_by_operation("op_a", status=None)
    assert [row["run_id"] for row in rows_all] == ["a3", "a2", "a1"]
    rows_lim = store.list_runs_by_operation("op_a", limit=1)
    assert [row["run_id"] for row in rows_lim] == ["a2"]


# ----------------------------------------------------------------------
# /api/planner/* 路由
# ----------------------------------------------------------------------

def _make_client(*, run_store=None, repo=None) -> TestClient:
    app = FastAPI()
    app.state.run_store = run_store
    app.state.script_repo = repo
    app.state.planner_stats = None
    register_planner_routes(app)
    return TestClient(app)


def test_routes_stats_shape_and_window_clamp():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    client = _make_client(run_store=store, repo=_FakeRepo([_meta("op_a")]))
    resp = client.get("/api/planner/stats", params={"window": 9999})
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"] == 200  # 夹紧到上限
    assert body["resources"] == []  # res_gate 未挂: 空列表而非报错
    assert _stats_of(body, "op_a")["count"] == 1


def test_routes_timeline_404():
    client = _make_client(run_store=RunStore(":memory:"), repo=_FakeRepo([_meta("op_a")]))
    resp = client.get("/api/planner/operations/no_such/timeline")
    assert resp.status_code == 404
    assert "流程不存在" in resp.json()["detail"]


def test_routes_503_when_store_missing():
    client = _make_client(run_store=None, repo=_FakeRepo([_meta("op_a")]))
    assert client.get("/api/planner/stats").status_code == 503


def test_routes_baseline_set_and_clear_single_operation():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    _feed_simple_run(store, "b1", "op_b", 100.0, [("b/0", "dev.x", 20.0)])
    client = _make_client(run_store=store, repo=_FakeRepo([_meta("op_a"), _meta("op_b")]))
    resp = client.post("/api/planner/baseline", json={"operation": "op_a"})
    assert resp.status_code == 200 and resp.json()["operation"] == "op_a"
    assert resp.json()["since_ts"] > 100.0
    body = client.get("/api/planner/stats").json()
    # 只 op_a 归零, op_b 不受影响
    assert _stats_of(body, "op_a")["count"] == 0
    assert _stats_of(body, "op_a")["baseline_ts"] is not None
    assert _stats_of(body, "op_b")["count"] == 1
    resp = client.request("DELETE", "/api/planner/baseline", params={"operation": "op_a"})
    assert resp.status_code == 200 and resp.json()["cleared"] is True
    body = client.get("/api/planner/stats").json()
    assert _stats_of(body, "op_a")["count"] == 1 and _stats_of(body, "op_a")["baseline_ts"] is None


def test_routes_baseline_global_set_and_clear_all():
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    _feed_simple_run(store, "b1", "op_b", 100.0, [("b/0", "dev.x", 20.0)])
    client = _make_client(run_store=store, repo=_FakeRepo([_meta("op_a"), _meta("op_b")]))
    # 不带 operation = 全局基线, 所有流程归零
    assert client.post("/api/planner/baseline", json={}).json()["operation"] is None
    body = client.get("/api/planner/stats").json()
    assert _stats_of(body, "op_a")["count"] == 0 and _stats_of(body, "op_b")["count"] == 0
    # 全局基线单独回报 (前端据此切「撤销全部」)
    assert body["global_baseline_ts"] is not None
    # 不带 operation 的 DELETE = 清空全部基线
    assert client.request("DELETE", "/api/planner/baseline").status_code == 200
    body = client.get("/api/planner/stats").json()
    assert _stats_of(body, "op_a")["count"] == 1 and _stats_of(body, "op_b")["count"] == 1
    assert body["global_baseline_ts"] is None


def test_routes_baseline_accepts_empty_body():
    # 无请求体 (fetch 不带 body) 也视为全局基线, 不应 422
    store = RunStore(":memory:")
    _feed_simple_run(store, "r1", "op_a", 100.0, [("b/0", "dev.x", 10.0)])
    client = _make_client(run_store=store, repo=_FakeRepo([_meta("op_a")]))
    resp = client.post("/api/planner/baseline")
    assert resp.status_code == 200 and resp.json()["operation"] is None


# ----------------------------------------------------------------------
# 子流程耗时回填 (嵌套样本)
# ----------------------------------------------------------------------

def test_stats_backfills_pure_subflow_from_parent_runs():
    store = RunStore(":memory:")
    # sub_a 从没单独跑过, 只在 op_parent 里被 run_script 调用
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 5.0), ("b/1", "dev.y", 7.0)])])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    payload = svc.stats(window=10)
    sub = _stats_of(payload, "sub_a")
    # 改前 count 恒为 0 (前端显示"无历史"), 改后从父运行事件流回填出真实耗时
    assert sub["count"] == 1 and sub["nested_count"] == 1
    assert sub["avg_s"] == 12.0 and sub["last_s"] == 12.0
    assert sub["last_run_id"] == "p1"          # 嵌套样本给父运行 id, 点进去查得到
    assert sub["last_finished_at"] == 112.0
    # 父流程自身统计不受影响
    parent = _stats_of(payload, "op_parent")
    assert parent["count"] == 1 and parent["nested_count"] == 0 and parent["avg_s"] == 12.0


def test_stats_merges_top_level_and_nested_samples():
    store = RunStore(":memory:")
    _feed_simple_run(store, "s1", "sub_a", 100.0, [("b/0", "dev.x", 20.0)])   # 单独跑
    _feed_nested_run(store, "p1", "op_parent", 300.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 12.0)])])            # 被调用
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    sub = _stats_of(svc.stats(window=10), "sub_a")
    # 单独跑与被调用一视同仁, 合并算一个平均
    assert sub["count"] == 2 and sub["nested_count"] == 1
    assert sub["avg_s"] == 16.0 and sub["min_s"] == 12.0 and sub["max_s"] == 20.0
    assert sub["last_s"] == 12.0 and sub["last_run_id"] == "p1"


def test_stats_merged_last_follows_time_not_source():
    store = RunStore(":memory:")
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 12.0)])])
    _feed_simple_run(store, "s1", "sub_a", 300.0, [("b/0", "dev.x", 20.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    sub = _stats_of(svc.stats(window=10), "sub_a")
    # "最新一次"按时刻取, 不偏向任何一侧来源
    assert sub["count"] == 2 and sub["last_s"] == 20.0 and sub["last_run_id"] == "s1"


def test_stats_window_truncates_merged_samples():
    store = RunStore(":memory:")
    _feed_simple_run(store, "s1", "sub_a", 100.0, [("b/0", "dev.x", 50.0)])
    _feed_nested_run(store, "p1", "op_parent", 300.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 10.0)])])
    _feed_nested_run(store, "p2", "op_parent", 500.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 20.0)])])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    sub = _stats_of(svc.stats(window=2), "sub_a")
    # 窗口截断作用在合并后的时间轴上: 只剩最近两条嵌套, 早先单独跑的 50s 被截掉
    assert sub["count"] == 2 and sub["avg_s"] == 15.0 and sub["nested_count"] == 2


def test_stats_nested_excluded_when_parent_intervened():
    store = RunStore(":memory:")
    hold = {"type": "vm_hold", "run_id": "p1", "hold": "frozen", "ts": 101.0}
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 12.0)])],
                     extra_events=[hold])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    sub = _stats_of(svc.stats(window=10), "sub_a")
    # 父运行被暂停/调试过, 里面的子流程时长不可信: 不入统计, 但如实计入剔除数
    assert sub["count"] == 0 and sub["excluded"] == 1 and sub["avg_s"] is None


def test_stats_nested_ignores_non_done_subflow():
    store = RunStore(":memory:")
    # 子流程失败但被父流程 try 兜住, 父运行仍 DONE: 该次时长残缺, 不能进平均
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 3.0)])], sub_status="FAILED")
    _feed_nested_run(store, "p2", "op_parent", 300.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 20.0)])])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    sub = _stats_of(svc.stats(window=10), "sub_a")
    assert sub["count"] == 1 and sub["avg_s"] == 20.0


def test_baseline_orthogonal_between_parent_and_subflow():
    store = RunStore(":memory:")
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 10.0)])])
    _feed_nested_run(store, "p2", "op_parent", 300.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 30.0)])])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    assert _stats_of(svc.stats(window=10), "sub_a")["count"] == 2
    # 清父流程的记录: 子流程不受牵连 —— 父流程改了不代表子流程也改了
    store.set_stat_baseline("op_parent", 200.0)
    payload = svc.stats(window=10)
    assert _stats_of(payload, "op_parent")["count"] == 1
    assert _stats_of(payload, "sub_a")["count"] == 2
    # 清子流程的记录: 只砍它自己早于基线的嵌套样本, 父流程统计不动
    store.set_stat_baseline("sub_a", 200.0)
    payload = svc.stats(window=10)
    assert _stats_of(payload, "sub_a")["count"] == 1
    assert _stats_of(payload, "sub_a")["avg_s"] == 30.0
    assert _stats_of(payload, "op_parent")["count"] == 1
    # 撤销子流程基线后恢复
    store.clear_stat_baseline("sub_a")
    assert _stats_of(svc.stats(window=10), "sub_a")["count"] == 2


def test_stats_backfills_multi_level_nesting():
    store = RunStore(":memory:")
    # 祖父 op_root → 父 sub_mid → 子 sub_leaf: 三层各自拿到自己的样本
    for ev in [_start("r1", 0.0, "op_root"),
               _enter("r1", 1.0, "b/0", script="op_root", op="run_script", action="sub_mid"),
               _enter("r1", 2.0, "b/0", script="sub_mid", op="run_script", action="sub_leaf"),
               _enter("r1", 3.0, "b/0", script="sub_leaf", action="dev.x"),
               _done("r1", 8.0, "b/0", script="sub_leaf", action="dev.x"),
               _done("r1", 9.0, "b/0", script="sub_mid", op="run_script", action="sub_leaf"),
               _done("r1", 10.0, "b/0", script="op_root", op="run_script", action="sub_mid"),
               _finish("r1", 11.0)]:
        store.on_event(ev)
    svc = TimingStats(store, _FakeRepo(
        [_meta("op_root"), _meta("sub_mid"), _meta("sub_leaf")]))
    payload = svc.stats(window=10)
    assert _stats_of(payload, "op_root")["avg_s"] == 11.0    # 顶层运行整段
    assert _stats_of(payload, "sub_mid")["avg_s"] == 9.0     # 1.0 → 10.0
    assert _stats_of(payload, "sub_leaf")["avg_s"] == 7.0    # 2.0 → 9.0
    assert _stats_of(payload, "sub_leaf")["nested_count"] == 1


def test_timeline_of_pure_nested_subflow():
    store = RunStore(":memory:")
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 4.0), ("b/1", "dev.y", 6.0)])])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    payload = svc.timeline("sub_a", window=10)
    # 明细与列表统计自洽: 不再出现"列表有耗时, 点开说暂无记录"
    assert payload["count"] == _stats_of(svc.stats(window=10), "sub_a")["count"] == 1
    last = payload["last_run"]
    assert last is not None and last["run_id"] == "p1" and last["duration_s"] == 10.0
    assert last["started_at"] == 100.0 and last["finished_at"] == 110.0
    # 偏移相对子流程自身起点; depth 扣掉父帧那一层, 归一化到 0 起
    assert [(s["aid"], s["start_offset_s"], s["duration_s"], s["depth"])
            for s in last["steps"]] == [("b/0", 0.0, 4.0, 0), ("b/1", 4.0, 6.0, 0)]
    steps = {(s["script"], s["aid"]): s for s in payload["step_stats"]}
    assert steps[("sub_a", "b/0")]["avg_s"] == 4.0
    assert steps[("sub_a", "b/1")]["avg_s"] == 6.0


def test_timeline_nested_step_stats_exclude_own_top_level_runs():
    store = RunStore(":memory:")
    # sub_a 单独跑一次 (t=100) + 被父流程调用一次 (t=300, 更新)
    _feed_simple_run(store, "s1", "sub_a", 100.0, [("b/0", "dev.x", 20.0)])
    _feed_nested_run(store, "p1", "op_parent", 300.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 12.0)])])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    payload = svc.timeline("sub_a", window=10)
    # 最新一次是嵌套 → 步骤取嵌套侧; 两侧窗口口径不同, 混着算会把同一步双计
    assert payload["count"] == 2 and payload["last_run"]["run_id"] == "p1"
    steps = {(s["script"], s["aid"]): s for s in payload["step_stats"]}
    assert steps[("sub_a", "b/0")]["count"] == 1 and steps[("sub_a", "b/0")]["avg_s"] == 12.0


def test_timeline_uses_top_level_branch_when_newest_is_own_run():
    store = RunStore(":memory:")
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 12.0)])])
    _feed_simple_run(store, "s1", "sub_a", 300.0, [("b/0", "dev.x", 20.0)])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    payload = svc.timeline("sub_a", window=10)
    assert payload["count"] == 2
    assert payload["last_run"]["run_id"] == "s1" and payload["last_run"]["duration_s"] == 20.0
    steps = {(s["script"], s["aid"]): s for s in payload["step_stats"]}
    assert steps[("sub_a", "b/0")]["count"] == 1 and steps[("sub_a", "b/0")]["avg_s"] == 20.0


def test_nested_index_refreshes_on_new_run():
    store = _CountingStore()
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 10.0)])])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    assert _stats_of(svc.stats(window=10), "sub_a")["count"] == 1
    calls = store.get_run_calls
    svc.stats(window=10)
    assert store.get_run_calls == calls          # 运行集合未变: 收割缓存命中
    _feed_nested_run(store, "p2", "op_parent", 300.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 30.0)])])
    sub = _stats_of(svc.stats(window=10), "sub_a")
    # 新运行入库必须让收割结果刷新, 漏了这条则子流程耗时永远停在旧值
    assert sub["count"] == 2 and sub["avg_s"] == 20.0


def test_nested_run_script_not_merged_into_action_stats():
    store = RunStore(":memory:")
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 10.0)])])
    svc = TimingStats(store, _FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    actions = {item["action"] for item in svc.stats(window=10)["actions"]}
    # 全局动作统计只合并原子动作 (op=call), 子流程名不混进去
    assert actions == {"dev.x"}


def test_routes_stats_exposes_nested_count():
    store = RunStore(":memory:")
    _feed_nested_run(store, "p1", "op_parent", 100.0,
                     [("b/0", "sub_a", [("b/0", "dev.x", 10.0)])])
    client = _make_client(run_store=store,
                          repo=_FakeRepo([_meta("op_parent"), _meta("sub_a")]))
    body = client.get("/api/planner/stats").json()
    assert _stats_of(body, "sub_a")["nested_count"] == 1
    assert _stats_of(body, "op_parent")["nested_count"] == 0
