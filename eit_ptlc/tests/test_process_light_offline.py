"""视觉纠偏补光 (机器人 DO7) 的孪生公告 —— 离线用例, 不碰真机也不起后端。

为什么值得单独锁: 三维孪生实时页要知道"补光此刻亮着没有", 而机器人 DO 没有回读通道,
唯一诚实的取数点就是 `make_pallas_light_setter` 这一次调用本身。这条链 2026-08-05
之前根本不存在(现象: 实时页跑上样-上料时闪光灯不闪), 而它坏掉时**画面完全正常**、
没有任何指标会报警 —— 正是最该有回归测的形状。

三条判据:
    1. 写 DO 成功才公告, 且公告内容与真机通道一致;
    2. 写 DO 失败**不公告** —— 关灯失败会被上游升级成 PallasVisionError, 那种情况下
       画面里的灯不该跟着灭掉, 否则人以为灯关了、实际还亮着;
    3. bus 缺席(纯离线/无 lifespan 的测试)时照常控灯, 不炸。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from eit_ptlc.runtime.bootstrap import PALLAS_LIGHT_TWIN_ID, make_pallas_light_setter


class _RecordingBus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, event: dict) -> None:
        self.events.append(event)


class _Transport:
    """记录 set_output 调用; fail_on 里的开关值会抛错, 模拟写 DO 失败。"""

    def __init__(self, fail_on: set[bool] | None = None) -> None:
        self.calls: list[tuple[int, bool]] = []
        self.fail_on = fail_on or set()

    def set_output(self, channel: int, enabled: bool) -> None:
        if enabled in self.fail_on:
            raise RuntimeError(f"DO{channel} 写失败(模拟)")
        self.calls.append((channel, enabled))


def _make(channel: int = 7, fail_on: set[bool] | None = None):
    config = SimpleNamespace(
        pallas_vision=SimpleNamespace(light_do_channel=channel, light_control_enabled=True)
    )
    transport = _Transport(fail_on=fail_on)
    robot = SimpleNamespace(transport=transport)
    bus = _RecordingBus()
    app = SimpleNamespace(state=SimpleNamespace(bus=bus))
    return make_pallas_light_setter(config, robot, app), transport, bus, app


def test_开关灯都公告_且与真机通道一致():
    setter, transport, bus, _ = _make(channel=7)

    asyncio.run(setter(True))
    asyncio.run(setter(False))

    assert transport.calls == [(7, True), (7, False)]
    assert [e["type"] for e in bus.events] == ["process_light", "process_light"]
    assert [e["on"] for e in bus.events] == [True, False]
    # id 必须与 rig_map.lights[].id 逐字一致, 前端按它查 manifest.lights
    assert {e["id"] for e in bus.events} == {PALLAS_LIGHT_TWIN_ID}
    assert {e["channel"] for e in bus.events} == {7}
    assert all(isinstance(e["ts"], float) for e in bus.events)


def test_通道号跟随配置_不写死7():
    setter, transport, bus, _ = _make(channel=5)
    asyncio.run(setter(True))
    assert transport.calls == [(5, True)]
    assert bus.events[0]["channel"] == 5


def test_写DO失败时不公告_否则人会以为灯关了而它还亮着():
    setter, transport, bus, _ = _make(fail_on={False})

    asyncio.run(setter(True))
    assert bus.events[-1]["on"] is True

    with pytest.raises(RuntimeError):
        asyncio.run(setter(False))

    # 关灯那一次没写成功 → 不该有第二条事件
    assert len(bus.events) == 1, "写 DO 失败必须不公告, 只报已经写成功的状态"
    assert transport.calls == [(7, True)]


def test_bus缺席时照常控灯_不炸():
    setter, transport, _, app = _make()
    app.state.bus = None
    asyncio.run(setter(True))
    assert transport.calls == [(7, True)]

    # 连 state.bus 这个属性都不存在时(更早的启动阶段)也要走 getattr 兜住
    delattr(app.state, "bus")
    asyncio.run(setter(False))
    assert transport.calls == [(7, True), (7, False)]


def test_process_light_不在可丢事件集里():
    """无心跳的事件一旦被背压挤掉就是永久错态, 必须与生命周期事件同级不可丢。"""
    from eit_ptlc.runtime.events import _DROPPABLE_TYPES

    assert "process_light" not in _DROPPABLE_TYPES
    # signal_light 能丢是因为有 1s 心跳会重新播种, 两者的差别就在这里
    assert "signal_light" in _DROPPABLE_TYPES
