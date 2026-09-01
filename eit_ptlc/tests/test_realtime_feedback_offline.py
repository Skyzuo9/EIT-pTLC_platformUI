"""数字孪生高频只读生产端离线测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from eit_ptlc.config.loader import load_manual_points
from eit_ptlc.controller.manual_service import ManualService
from eit_ptlc.runtime.events import EventBus
from eit_ptlc.runtime.realtime_feedback import realtime_feedback_loop


ROOT = Path(__file__).resolve().parents[1]


class _BatchDriver:
    def __init__(self, manual_map) -> None:
        self.values: dict[str, object] = {}
        for cyl in manual_map.cylinders.values():
            self.values[cyl.manual.name] = False
            self.values[cyl.auto_ro.name] = False
            if cyl.fb_on is not None:
                self.values[cyl.fb_on.name] = False
            if cyl.fb_off is not None:
                self.values[cyl.fb_off.name] = False

    async def resolve_ext_node(self, path):
        return tuple(path)

    async def read_ext_batch(self, paths):
        result = []
        for path in paths:
            member = path[-1]
            if member == "fActPos":
                result.append(123.5)
            elif member == "fActVel":
                result.append(-4.25)
            else:
                result.append(self.values.get(member, False))
        return result


def test_manual_realtime_snapshot_is_complete_and_does_not_touch_session() -> None:
    manual_map = load_manual_points(ROOT / "config" / "manual_points.yaml")
    driver = _BatchDriver(manual_map)
    feedback_cylinder = next(c for c in manual_map.cylinders.values() if c.fb_on is not None)
    driver.values[feedback_cylinder.manual.name] = True
    driver.values[feedback_cylinder.fb_on.name] = True
    service = ManualService(driver=driver, manual_map=manual_map)
    service._touch = lambda: (_ for _ in ()).throw(AssertionError("不得续期手动会话"))

    snapshot = asyncio.run(service.realtime_snapshot())
    assert len(snapshot["axes"]) == 11
    assert len(snapshot["mechanisms"]) == 51
    assert snapshot["axes"]["axis_11y"] == {"position": 123.5, "velocity": -4.25}
    state = snapshot["mechanisms"][feedback_cylinder.id]
    assert state["commanded"] is True
    assert state["confirmed"] is True
    assert state["source"] == "feedback"


class _LoopManual:
    def __init__(self, stop: asyncio.Event) -> None:
        self.stop = stop
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def realtime_snapshot(self, *, include_axes: bool, include_mechanisms: bool):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.005)
        self.active -= 1
        if self.calls >= 2:
            self.stop.set()
        return {
            "axes": {"axis_11y": {"position": 500, "velocity": 20}} if include_axes else {},
            "mechanisms": {"ps_shade": {"commanded": True, "confirmed": None,
                                                   "source": "feedback"}}
            if include_mechanisms else {},
        }


async def _exercise_loop() -> None:
    stop = asyncio.Event()
    manual = _LoopManual(stop)
    bus = EventBus(max_queue=20)
    async with bus.subscribe() as q:
        await realtime_feedback_loop(
            manual,
            bus,
            stop,
            axis_interval=0.001,
            mechanism_interval=0.002,
        )
        events = []
        while q._buf:
            events.append(await q.get())
    assert manual.max_active == 1, "慢周期不得堆积并发读取任务"
    assert any(event["type"] == "axis_pose" for event in events)
    assert any(event["type"] == "mechanism_state" for event in events)
    assert all(event["seq"] >= 1 for event in events)


def test_realtime_loop_publishes_without_backlog() -> None:
    asyncio.run(_exercise_loop())


# -- 三色灯状态推导与 signal_light 发布 --------------------------------------
# 颜色由 MODE_State 推导, 不再信任原始色位(与实体灯脱钩, 见 manual_service 注释).

def test_manual_realtime_snapshot_derives_signals_from_mode() -> None:
    """运行态推绿; 既有 11 轴/51 机构契约原样不动; 轴专用快照不多读。"""
    manual_map = load_manual_points(ROOT / "config" / "manual_points.yaml")
    driver = _BatchDriver(manual_map)
    driver.values["MODE_State"] = 1
    service = ManualService(driver=driver, manual_map=manual_map)

    snapshot = asyncio.run(service.realtime_snapshot())
    assert len(snapshot["axes"]) == 11
    assert len(snapshot["mechanisms"]) == 51
    assert snapshot["signals"] == {
        "red": False, "yellow": False, "green": True,
        "flash": False, "buzzer": False, "mode": 1,
    }

    axis_only = asyncio.run(service.realtime_snapshot(include_mechanisms=False))
    assert "signals" not in axis_only, "轴专用快照(20Hz)不得多读灯位"


def test_signal_colors_ignore_polluted_raw_bits() -> None:
    """回归锁: 运行版 PLC 的 三色灯红 恒 TRUE, 推导结果必须对其免疫。"""
    manual_map = load_manual_points(ROOT / "config" / "manual_points.yaml")
    driver = _BatchDriver(manual_map)
    driver.values["MODE_State"] = 1
    driver.values["三色灯红"] = True      # 实机取证: 运行态红位常 TRUE 而实体红灯不亮
    driver.values["三色灯黄"] = True
    service = ManualService(driver=driver, manual_map=manual_map)
    signals = asyncio.run(service.realtime_snapshot())["signals"]
    assert signals["red"] is False and signals["yellow"] is False and signals["green"] is True


def test_signal_mode_table_covers_all_states() -> None:
    """0停止=黄 / 2故障=红闪 / 3急停=红 / 4初始化=黄闪 / 未知码=全灭; 蜂鸣器透传。"""
    manual_map = load_manual_points(ROOT / "config" / "manual_points.yaml")
    expected = {
        0: {"red": False, "yellow": True, "green": False, "flash": False},
        2: {"red": True, "yellow": False, "green": False, "flash": True},
        3: {"red": True, "yellow": False, "green": False, "flash": False},
        4: {"red": False, "yellow": True, "green": False, "flash": True},
        99: {"red": False, "yellow": False, "green": False, "flash": False},
    }
    for mode, colors in expected.items():
        driver = _BatchDriver(manual_map)
        driver.values["MODE_State"] = mode
        driver.values["蜂鸣器"] = mode == 2
        service = ManualService(driver=driver, manual_map=manual_map)
        signals = asyncio.run(service.realtime_snapshot())["signals"]
        assert signals == {**colors, "buzzer": mode == 2, "mode": mode}, f"mode={mode}"


class _NoModeDriver(_BatchDriver):
    """模拟 MODE_State 路径解析失败: read_ext_batch 该槽为 None。"""

    async def read_ext_batch(self, paths):
        values = await super().read_ext_batch(paths)
        return [None if path[-1] == "MODE_State" else value
                for path, value in zip(paths, values)]


def test_manual_realtime_snapshot_omits_signals_when_mode_unresolved() -> None:
    """mode 读不到时省略 signals 键 —— 下游不发事件, 前端保持烘焙静态灯。"""
    manual_map = load_manual_points(ROOT / "config" / "manual_points.yaml")
    service = ManualService(driver=_NoModeDriver(manual_map), manual_map=manual_map)
    snapshot = asyncio.run(service.realtime_snapshot())
    assert "signals" not in snapshot
    assert len(snapshot["axes"]) == 11, "灯位解析失败不得拖垮轴流"
    assert len(snapshot["mechanisms"]) == 51


class _SignalLoopManual:
    """按脚本逐次吐灯态的假快照源; 攒够 max_calls 次机构快照后停 loop。"""

    def __init__(self, stop: asyncio.Event, plan: list[dict | None], *, max_calls: int) -> None:
        self.stop = stop
        self.plan = plan
        self.mech_calls = 0
        self.max_calls = max_calls

    async def realtime_snapshot(self, *, include_axes: bool, include_mechanisms: bool):
        snapshot: dict[str, object] = {"axes": {}, "mechanisms": {}}
        if include_mechanisms:
            self.mech_calls += 1
            signals = self.plan[min(self.mech_calls - 1, len(self.plan) - 1)]
            if signals is not None:
                snapshot["signals"] = dict(signals)
            if self.mech_calls >= self.max_calls:
                self.stop.set()
        return snapshot


_GREEN = {"red": False, "yellow": False, "green": True, "flash": False, "buzzer": False, "mode": 1}
_RED = {"red": True, "yellow": False, "green": False, "flash": True, "buzzer": True, "mode": 2}


async def _collect_signal_events(plan, *, signal_heartbeat: float, max_calls: int):
    stop = asyncio.Event()
    manual = _SignalLoopManual(stop, plan, max_calls=max_calls)
    bus = EventBus(max_queue=50)
    async with bus.subscribe() as q:
        await realtime_feedback_loop(
            manual,
            bus,
            stop,
            axis_interval=0.001,
            mechanism_interval=0.001,
            signal_heartbeat=signal_heartbeat,
        )
        events = []
        while q._buf:
            events.append(await q.get())
    return [event for event in events if event["type"] == "signal_light"]


def test_signal_light_published_on_change_only_within_heartbeat_window() -> None:
    """变化即发: 心跳窗口内同态帧去重, 灯态一变立即发布。"""
    events = asyncio.run(_collect_signal_events(
        [_GREEN, _GREEN, _GREEN, _RED, _RED],
        signal_heartbeat=999.0,
        max_calls=5,
    ))
    assert len(events) == 2, "5 次同源采样只应发出 首帧 + 变化帧 两条"
    assert events[0]["green"] is True and events[0]["red"] is False
    assert events[1]["red"] is True and events[1]["green"] is False
    assert events[1]["flash"] is True and events[1]["mode"] == 2, "故障帧必须携带闪烁与模式码"
    assert [event["seq"] for event in events] == [1, 2]
    assert all("ts" in event and "yellow" in event and "buzzer" in event for event in events)


def test_signal_light_heartbeat_repeats_unchanged_state() -> None:
    """心跳路径: 窗口归零时每轮机构采样都重发, 供断流检测与新连接播种。"""
    events = asyncio.run(_collect_signal_events(
        [_GREEN, _GREEN, _GREEN],
        signal_heartbeat=0.0,
        max_calls=3,
    ))
    assert len(events) == 3
    assert [event["seq"] for event in events] == [1, 2, 3]


def test_signal_light_absent_snapshot_publishes_nothing() -> None:
    """快照没有 signals 键(采集降级)时一条 signal_light 都不发。"""
    events = asyncio.run(_collect_signal_events(
        [None, None],
        signal_heartbeat=0.0,
        max_calls=2,
    ))
    assert events == []


# -- 机器人末端执行器状态并入 mechanism_state --------------------------------

async def _collect_mechanism_events(robot_states) -> list[dict]:
    """跑一轮短 loop, 收回全部 mechanism_state 事件。"""
    stop = asyncio.Event()
    manual = _LoopManual(stop)
    bus = EventBus(max_queue=20)
    async with bus.subscribe() as q:
        await realtime_feedback_loop(
            manual,
            bus,
            stop,
            axis_interval=0.001,
            mechanism_interval=0.002,
            robot_states=robot_states,
        )
        events = []
        while q._buf:
            events.append(await q.get())
    return [event for event in events if event["type"] == "mechanism_state"]


def test_realtime_loop_merges_robot_end_effector_states() -> None:
    """rob_* 末端执行器与 PLC 机构必须并入同一个 mechanism_state 事件(单源)。"""
    calls = {"count": 0}

    def robot_states():
        calls["count"] += 1
        return {"rob_grip_plate96": {"commanded": True, "confirmed": None,
                                     "available": True, "source": "commanded"}}

    events = asyncio.run(_collect_mechanism_events(robot_states))
    assert events, "应发布 mechanism_state"
    assert calls["count"] >= 1, "快照函数应被采样"
    for event in events:
        assert "rob_grip_plate96" in event["states"], "末端执行器必须并入同一事件"
        assert "ps_shade" in event["states"], "PLC 机构不得被机器人快照顶掉"


def test_realtime_loop_survives_robot_snapshot_failure() -> None:
    """末端执行器快照抛错只影响该合并, PLC 机构照常发布, 循环不退出。"""

    def broken():
        raise RuntimeError("末端执行器快照坏了")

    events = asyncio.run(_collect_mechanism_events(broken))
    assert events, "快照函数抛错不得杀掉反馈循环"
    assert all("ps_shade" in event["states"] for event in events)
    assert all(not any(key.startswith("rob_") for key in event["states"]) for event in events)
