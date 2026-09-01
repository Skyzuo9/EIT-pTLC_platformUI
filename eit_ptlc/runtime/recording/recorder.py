"""状态录制器: 事件总线的一路 sink + 后台写盘线程。

接入点
    挂在 bootstrap 的 make_event_sink 扇出上, 生产者一行都不用改。且 sink 扇出发生
    在 EventBus._SubQueue 的丢帧策略**之前** (那是按订阅者队列丢的), 所以录到的比
    任何前端客户端看到的都全。

丢帧策略与总线同构
    队列满时只挤掉"最新快照即全部语义"的类型 (轴/机构/遥测等), 增量类事件一条不丢。
    scrape_state 与 vm_node_enter 尤其不可丢:
      - scrape_state 丢一条就永远画不出刮痕 (后端也刻意没把它列进可丢类型);
      - vm_node_done 不带 args, 配对表是 args 的唯一来源, 丢了 enter 会静默杀死
        夹爪持握 / 板转移 / 托盘挂载的推断, 且不报任何错。

关键帧只装"直接录到的"状态, 派生态靠快进重建
    每块块首写入合并后的连续量与机构态 —— 这些后端直接看得到。而前端派生的锁存态
    (板归属与 l2Trail、夹爪持握、托盘 owned 等) 是浏览器里算出来的, 后端无从知晓,
    也不能指望"有人开着三维页面"才录得全。
    因此 seek 的语义是两段:
        块关键帧      -> 连续量瞬间到位
        自运行起点快进低频事件流 -> 重建派生态
    低频事件流本就完整且不丢, 快进一整个运行的代价可以忽略。这个分工决定了上面
    "增量事件一条不丢"是硬要求而不是保守。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable

from eit_ptlc.runtime.recording.activity import chunk_activity
from eit_ptlc.runtime.recording.codec import ChunkBuilder
from eit_ptlc.runtime.recording.store import (
    MIN_PLAUSIBLE_TS, RecordingStore, SessionInfo,
)

log = logging.getLogger(__name__)

# 与 runtime/events.py 的 _DROPPABLE_TYPES 同构: 只有"最新快照即全部语义"的才可丢
_DROPPABLE = frozenset({
    "telemetry", "robot_pose", "axis_pose", "mechanism_state",
    "material_state", "vm_vars", "signal_light", "pump_state",
    # tank_liquid: 仿真沙盒专属的展缸液量快照, 最新一帧即全部语义 —— 与
    # runtime/events.py 的 _DROPPABLE_TYPES 保持同步。两处不一致的话, 录像的丢帧
    # 取舍会与实时推送不同, 排查"为什么录像里有而画面上没有"会非常难受。
    "tank_liquid",
})

# 时间戳合理性区间。一条坏 ts 就能永久毁掉整条时间轴: chunks.t0 会被写进索引,
# coverage() 取 MIN(t0), 于是前端的可拖动区间从 1970 一直铺到今天, seek 落进虚空、
# 预取请求变成 frames?t0=1&t1=21。所以宁可用墙钟顶上, 也不能让它进库。
# 下界与 store.MIN_PLAUSIBLE_TS 同源: 录制侧拦截、整理侧清理, 判据必须是同一个数
_FUTURE_SLACK_S = 3600.0              # 容忍一点点时钟偏差, 不容忍"未来一小时以上"

# 走列式帧编码的高频流 (其余事件原样入块)
_FRAME_STREAMS = frozenset({"axis_pose", "robot_pose", "mechanism_state", "signal_light"})

# 需要在时间轴上打点的事件 -> 标记类型。事故追溯靠它一键跳转。
_MARKER_KINDS = {
    "operation_start": "operation",
    "operation_done": "operation",
    "operation_failed": "alarm",
    "vm_hold": "hold",
    "vm_human_request": "human",
    "vm_human_reply": "human",
    "step_start": "step",
    "step_done": "step",
    "transport": "transport",
    "alarm": "alarm",
    "estop": "alarm",
    "vision_capture": "camera",
    # VM 跑脚本发的是 vm_node_*, 而不是 step_*。不收它们的话, 真跑流程时动作列表几乎
    # 是空的 —— runs.db 里 vm_node_enter 有 6344 条, step_start 只有 45 条。
    "vm_node_enter": "action",
    "vm_node_done": "action",
}

# 只有这两种 op 算"一步"。与 stores/runs.js 同一条纪律: 控制流 if/for/parallel 不成步,
# 否则一个 100 次的 for 循环就往标记表里写 200 行。
_STEP_OPS = frozenset({"call", "run_script"})


def _flatten(event: dict) -> tuple[str, float, dict] | None:
    """把高频事件摊平成 (流名, 时间戳, {通道: 值}); 非帧类事件返回 None。"""
    etype = event.get("type")
    ts = event.get("ts")
    if etype not in _FRAME_STREAMS or not isinstance(ts, (int, float)):
        return None
    ts = float(ts)

    if etype == "axis_pose":
        values: dict = {}
        for axis, value in (event.get("positions") or {}).items():
            values[f"{axis}.position"] = value
        for axis, value in (event.get("velocities") or {}).items():
            values[f"{axis}.velocity"] = value
        return ("axis_pose", ts, values) if values else None

    if etype == "robot_pose":
        values = {}
        joint = event.get("joint") or []
        for i, value in enumerate(joint[:6]):
            values[f"joint{i}"] = value
        pose = event.get("pose") or []
        for i, value in enumerate(pose[:3]):
            values[f"pose_xyz{i}"] = value
        for i, value in enumerate(pose[3:6]):
            values[f"pose_rpy{i}"] = value
        if event.get("tool") is not None:
            values["tool"] = event["tool"]
        if event.get("mode") is not None:
            values["mode"] = event["mode"]
        return ("robot_pose", ts, values) if values else None

    if etype == "mechanism_state":
        values = {}
        for mech, state in (event.get("states") or {}).items():
            if not isinstance(state, dict):
                continue
            for field, value in state.items():
                values[f"{mech}.{field}"] = value
        return ("mechanism_state", ts, values) if values else None

    # signal_light: 顶层就是各灯位
    values = {k: v for k, v in event.items()
              if k in ("red", "yellow", "green", "buzzer", "flash", "mode")}
    return ("signal_light", ts, values) if values else None


def _markers_for(event: dict, ts: float) -> list[dict]:
    """从一条事件里抽出时间轴标记 (可能 0~2 条)。

    相机抓图不需要另建一条录制链路: 拍照动作的结果里本就带着 image_path, 而它随
    vm_node_done 原样入库。这里只是把它认出来打成 camera 标记, 回放时即可与三维并排
    显示当时那张真实照片 —— 图片本身由既有的视觉产物端点提供, 一个字节都不必重存。
    """
    out: list[dict] = []
    etype = str(event.get("type") or "")
    kind = _MARKER_KINDS.get(etype)
    if kind == "action" and str(event.get("op") or "") not in _STEP_OPS:
        kind = None                       # 控制流节点不成步
    if kind:
        # phase 是首尾配对的**唯一**可靠依据: operation_start 与 operation_done 都映射
        # 成 kind="operation", 光看 kind 分不出哪头是哪头。
        phase = "done" if etype.endswith("_done") or etype.endswith("_failed") else "start"
        payload = {k: v for k, v in event.items()
                   if k in ("status", "message", "op", "action", "script", "node", "id")}
        # aid 归一: vm_node_* 用 aid, step_* 用 step
        aid = event.get("aid") or event.get("step")
        if aid is not None:
            payload["aid"] = str(aid)
        payload["phase"] = phase
        out.append({
            "ts": ts,
            "kind": kind,
            "run_id": event.get("run_id"),
            "label": str(event.get("operation") or event.get("action")
                         or event.get("label") or etype),
            "payload": payload,
        })

    result = event.get("result")
    if etype == "vm_node_done" and isinstance(result, dict):
        image = result.get("image_path")
        if image:
            out.append({
                "ts": ts,
                "kind": "camera",
                "run_id": event.get("run_id"),
                "label": str(event.get("action") or "拍照"),
                "payload": {"image_path": str(image), "script": event.get("script")},
            })
    return out


class _KeyframeState:
    """连续量与机构态的滚动合并快照, 每块块首写出。

    机构字段是**刻意粘滞**的 (commanded / confirmed / expectedS 只在出现时才写),
    所以关键帧必须是逐字段合并的结果, 而不是"最后一条 mechanism_state 事件" ——
    最后那条可能只带了一部分键。
    """

    def __init__(self) -> None:
        self.axes: dict[str, dict] = {}
        self.robot: dict = {}
        self.mechanisms: dict[str, dict] = {}
        self.signal_light: dict = {}
        self.material_state: dict | None = None
        self.telemetry: dict[str, dict] = {}
        self.scalars: dict = {}

    def apply(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "axis_pose":
            for axis, value in (event.get("positions") or {}).items():
                self.axes.setdefault(axis, {})["position"] = value
            for axis, value in (event.get("velocities") or {}).items():
                self.axes.setdefault(axis, {})["velocity"] = value
        elif etype == "robot_pose":
            self.robot = {k: event.get(k) for k in ("joint", "pose", "tool", "mode")}
        elif etype == "mechanism_state":
            for mech, state in (event.get("states") or {}).items():
                if isinstance(state, dict):
                    self.mechanisms.setdefault(mech, {}).update(state)
        elif etype == "signal_light":
            self.signal_light = {k: v for k, v in event.items() if k != "type"}
        elif etype == "material_state":
            self.material_state = dict(event)
        elif etype == "telemetry":
            node = event.get("node")
            if node:
                self.telemetry[str(node)] = dict(event)
        elif etype == "process_light":
            lights = self.scalars.setdefault("processLights", {})
            if event.get("id") is not None:
                lights[str(event["id"])] = bool(event.get("on"))
        elif etype == "pump_speeds":
            # 泵速是前端构造函数里 fire-and-forget 拉的实时配置, 不录进来回放会不确定
            self.scalars["pumpSpeeds"] = event.get("speeds")

    def snapshot(self) -> dict:
        out: dict = {
            "axes": self.axes,
            "robot": self.robot,
            "mechanisms": self.mechanisms,
            "signalLight": self.signal_light,
            "telemetry": self.telemetry,
            **self.scalars,
        }
        if self.material_state is not None:
            # initial:true 让前端 MaterialStateStore 绕过它的时间戳倒退闸门
            out["materialState"] = {**self.material_state, "initial": True}
        return out


class StateRecorder:
    """事件 sink + 后台写盘线程。on_event 永不阻塞调用方。"""

    def __init__(self, store: RecordingStore, *,
                 kind: str = "real",
                 chunk_seconds: float = 10.0,
                 queue_max: int = 20000,
                 manifest_hash: str | None = None,
                 retention_interval_s: float = 3600.0,
                 station_map: dict[str, str] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.kind = kind
        # {机构或轴 id: 工位 key}, 供活动度按工位聚合。缺省是空表 —— 那样每一块都会
        # 把全部实体计进 unmapped 并由 status() 上墙, 而不是悄悄画一条恒为 0 的条。
        self.station_map = dict(station_map or {})
        self.unmapped_ids: set[str] = set()
        self.chunk_seconds = float(chunk_seconds)
        self.queue_max = int(queue_max)
        self.manifest_hash = manifest_hash
        self.retention_interval_s = float(retention_interval_s)
        self._clock = clock

        self._queue: deque[dict] = deque()
        # 本轮批处理里攒下的增量事件, 收尾时一次 executemany 写进 lowfreq 索引。
        # 逐条写会把库级写锁攥得很碎 —— 与 store 头注释同一条纪律。
        self._lowfreq_batch: list[dict] = []
        self._cv = threading.Condition()
        self._thread: threading.Thread | None = None
        # 收事件的开关与写盘线程的存活分开表达: on_event 跑在控制回路线程上, 判据
        # 应当是"录制器是否在收", 而不是去窥探线程对象的状态。
        self._active = False
        self._stop = threading.Event()
        self._session: SessionInfo | None = None
        self._seq = 0
        self._keyframe = _KeyframeState()
        self._builder: ChunkBuilder | None = None
        self._chunk_end = 0.0
        self._frames = 0
        self._last_sweep = 0.0

        self.dropped = 0
        self.recorded = 0
        self.bytes_written = 0
        self.lowfreq_written = 0
        # 时间戳不合理、被墙钟顶替的事件数。与 dropped 同一条纪律: 有问题必须看得见
        self.bad_ts = 0

    # -- 生命周期 -----------------------------------------------------

    def start(self, *, note: str = "") -> SessionInfo:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("录制器已在运行")
        self._session = self.store.start_session(
            kind=self.kind, note=note, manifest_hash=self.manifest_hash)
        self._stop.clear()
        self._active = True
        self._seq = 0
        self._frames = 0
        self._builder = None
        self._last_sweep = self._clock()
        self._thread = threading.Thread(target=self._run, name="ptlc-dvr-writer", daemon=True)
        self._thread.start()
        log.info("[dvr] 录制开始 session=%s root=%s", self._session.id, self.store.root)
        return self._session

    def stop(self, timeout: float = 5.0) -> None:
        self._active = False
        if self._thread is None:
            return
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        self._thread.join(timeout=timeout)
        self._thread = None
        if self._session is not None:
            self.store.end_session(self._session.id)
            log.info("[dvr] 录制结束 session=%s 帧=%d 丢弃=%d 字节=%d",
                     self._session.id, self.recorded, self.dropped, self.bytes_written)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- sink ---------------------------------------------------------

    def on_event(self, event: dict) -> None:
        """总线 sink 入口。只入队, 绝不做 IO —— 它跑在控制回路的线程上。"""
        if not self._active or self._stop.is_set():
            return
        if not isinstance(event, dict) or not event.get("type"):
            return
        with self._cv:
            if len(self._queue) >= self.queue_max:
                if not self._make_room():
                    # 挤不出可丢事件说明积压的全是增量事件。丢它们会让回放静默出错,
                    # 宁可短暂超限 —— 增量事件是低频的, 不构成内存风险。
                    log.warning("[dvr] 队列积压 %d 且无可丢事件, 暂时超限", len(self._queue))
            self._queue.append(event)
            self._cv.notify()

    def _make_room(self) -> bool:
        for i, old in enumerate(self._queue):
            if old.get("type") in _DROPPABLE:
                del self._queue[i]
                self.dropped += 1
                return True
        return False

    # -- 写盘线程 -----------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                if not self._queue:
                    self._cv.wait(timeout=0.5)
                batch = list(self._queue)
                self._queue.clear()
            for event in batch:
                try:
                    self._consume(event)
                except Exception:
                    log.exception("[dvr] 事件写入失败 type=%s", event.get("type"))
            self._flush_lowfreq()
            self._maybe_sweep()
        try:
            self._flush_chunk(force=True)
            self._flush_lowfreq()
            self.store.flush()
        except Exception:
            log.exception("[dvr] 收尾落盘失败")

    def _flush_lowfreq(self) -> None:
        """把本批增量事件一次写进 lowfreq 索引 (seek 重建派生态的唯一数据源)。"""
        batch = self._lowfreq_batch
        self._lowfreq_batch = []
        if not batch or self._session is None:
            return
        try:
            self.lowfreq_written += self.store.add_lowfreq(self._session.id, batch)
        except Exception:
            # 索引写失败不该杀掉写盘线程: 块本身已经落了, 少的只是重建派生态的便捷检索
            log.exception("[dvr] 增量事件索引写入失败 %d 条", len(batch))

    def _plausible_ts(self, raw) -> float:
        """把事件时间戳收敛到合理的纪元秒; 不合理就用墙钟顶上并计数。

        显式排除 bool: `isinstance(True, int)` 在 Python 里为真, 一条 `ts=True`
        会被当成 1.0 —— 即 1970-01-01, 足以把整条时间轴的下界拖到 56 年前。
        """
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            self.bad_ts += 1
            return self._clock()
        value = float(raw)
        now = self._clock()
        if not (MIN_PLAUSIBLE_TS <= value <= now + _FUTURE_SLACK_S):
            self.bad_ts += 1
            return now
        return value

    def _consume(self, event: dict) -> None:
        ts = self._plausible_ts(event.get("ts"))
        self._keyframe.apply(event)

        if self._builder is None or ts >= self._chunk_end:
            self._flush_chunk()
            self._open_chunk(ts)

        flat = _flatten(event)
        if flat is not None:
            # 用收敛过的 ts 而不是 _flatten 直接从事件里取的那个: 帧时间戳会被差分成
            # int32 毫秒, 一条 1970 的坏值与邻帧的差值是 -1.8e12 ms, 直接整数溢出,
            # 把这一列的全部时间戳搅烂。
            _stream, _raw_ts, values = flat
            self._builder.add_frame(_stream, ts, values)
            self._frames += 1
        else:
            self._builder.add_event(event)
            # 增量事件另存一份进索引: 它们是 seek 时重建派生态(板在谁手里/托盘挂载/
            # 夹爪持握)的唯一来源, 而关键帧里没有这些。判据直接复用 _DROPPABLE ——
            # "最新快照即全部语义"的那些本来就由关键帧表达, 不必再存。
            if event.get("type") not in _DROPPABLE:
                self._lowfreq_batch.append({**event, "ts": ts})
        self.recorded += 1

        if self._session is not None:
            for marker in _markers_for(event, ts):
                self.store.add_markers(self._session.id, [marker])

    def _open_chunk(self, ts: float) -> None:
        self._builder = ChunkBuilder(ts, keyframe=self._keyframe.snapshot())
        self._chunk_end = ts + self.chunk_seconds
        self._frames = 0

    def _flush_chunk(self, *, force: bool = False) -> None:
        builder = self._builder
        if builder is None or self._session is None:
            return
        if builder.is_empty() and not force:
            self._builder = None
            return
        if builder.is_empty():
            self._builder = None
            return
        # 活动度必须在 encode 之前从原值算 —— 编码后只剩量化差分, 再解回来是多余功
        stations, unmapped = chunk_activity(builder.columns(), self.station_map)
        self.unmapped_ids.update(unmapped)
        blob = builder.encode()
        self.store.append_chunk(self._session, self._seq, builder.t0, builder.t1,
                                blob, self._frames)
        self.store.set_chunk_activity(self._session.id, self._seq, stations)
        self.bytes_written += len(blob)
        self._seq += 1
        self._builder = None

    def _maybe_sweep(self) -> None:
        now = self._clock()
        if now - self._last_sweep < self.retention_interval_s:
            return
        self._last_sweep = now
        try:
            result = self.store.sweep_retention(now=now)
            if result["removed"]:
                log.info("[dvr] 保留策略清理 %d 个会话", len(result["removed"]))
        except Exception:
            log.exception("[dvr] 保留策略清理失败")

    # -- 状态 ---------------------------------------------------------

    def status(self) -> dict:
        with self._cv:
            queued = len(self._queue)
        return {
            "running": self.running,
            "session": self._session.as_dict() if self._session else None,
            "kind": self.kind,
            "root": str(self.store.root),
            "queued": queued,
            "queue_max": self.queue_max,
            "recorded": self.recorded,
            # 录像有洞比不知道有洞好: 这个数要如实上到 HUD
            "dropped": self.dropped,
            "bad_ts": self.bad_ts,
            "bytes_written": self.bytes_written,
            # 增量事件索引行数: seek 重建派生态全靠它, 长期是 0 就说明这条路是死的
            "lowfreq_written": self.lowfreq_written,
            # 认不出工位的实体: 工程演进新增机构时必须看得见, 不能让它悄悄漏出利用率
            "unmapped_ids": sorted(self.unmapped_ids),
            "modules_total": len(set(self.station_map.values()) | {"robot"}),
            # 前端据此把"尚未落盘的那一小段"画成独立区域: coverage 取的是已落盘块的
            # MAX(t1), 所以"实时"边缘最多比真实晚一个块; 拖进那段 state_at 会 404。
            "chunk_seconds": self.chunk_seconds,
            "retention_days": self.store.retention_days,
            "coverage": self.store.coverage(),
        }
