"""离线单测: 液位阈值等待核心 (waterlevel_trigger.wait_level) + host 动作派发.

全部假时钟/假检测服务, 无相机无 PLC 无真实 sleep.
运行:
    & "E:/Anaconda/python.exe" -m eit_ptlc.tests.test_waterlevel_trigger_offline
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.waterlevel_trigger import capture_reference, resolve_threshold, wait_level  # noqa: E402


class FakeClock:
    """假单调钟: sleep 即推进, 测试零等待."""

    def __init__(self) -> None:
        self.t = 0.0

    def time(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += float(seconds)


_SEQ = [0]   # 保证每次构造的帧 observed_at 互不相同 (真实服务每拍时刻必不同)


def _chan(front_percent, *, valid=True, reachable=True, reason="", age_s=0.0,
          has_ref=True) -> dict:
    # observed_at 是 wait_level 的去重键: 同一 dict 被驻留重复读到 = 同一检测拍, 不计入 streak;
    # 故这里每次构造都错开微秒级, 让"不同的帧"必然是"不同的拍" (µs 量级不影响 age_s 陈旧判定)
    _SEQ[0] += 1
    observed = (datetime.now(timezone.utc) - timedelta(seconds=age_s)
                - timedelta(microseconds=_SEQ[0]))
    return {"front_percent": front_percent, "valid": valid, "reachable": reachable,
            "reason": reason, "observed_at": observed.isoformat(), "has_ref": has_ref}


class FakeDetect:
    """假检测服务: 依次吐 frames (最后一帧驻留), get_params 返回固定阈值."""

    def __init__(self, frames, params=None) -> None:
        self._frames = list(frames)
        self._params = dict(params or {"trigger_percent_t2": 80.0, "t1_offset": 15.0})

    def get_params(self, channel: int) -> dict:
        return dict(self._params)

    def snapshot(self) -> dict:
        frame = self._frames.pop(0) if len(self._frames) > 1 else self._frames[0]
        channels = {} if frame is None else {1: frame}
        return {"channels": channels, "active": [1], "reachable_any": True}


def _run(coro):
    return asyncio.run(coro)


class ResolveThresholdTests(unittest.TestCase):
    def test_t2_and_t1(self) -> None:
        params = {"trigger_percent_t2": 80.0, "t1_offset": 15.0}
        self.assertEqual(resolve_threshold(params, "t2"), 80.0)
        self.assertEqual(resolve_threshold(params, "t1"), 65.0)

    def test_unconfigured_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_threshold({"trigger_percent_t2": 0.0, "t1_offset": 0.0}, "t2")
        with self.assertRaises(ValueError):
            resolve_threshold({"trigger_percent_t2": 10.0, "t1_offset": 20.0}, "t1")


class WaitLevelTests(unittest.TestCase):
    def _wait(self, detect, clock, **kw):
        kw.setdefault("target_tank", 1)
        kw.setdefault("stage", "t2")
        kw.setdefault("staleness_s", 6.0)
        kw.setdefault("hard_cap_s", 100.0)
        kw.setdefault("poll_s", 2.0)
        return _run(wait_level(detect, time_fn=clock.time, sleep=clock.sleep, **kw))

    def test_reached_t2(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(60.0), _chan(75.0), _chan(82.0), _chan(82.0)])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "reached")
        self.assertEqual(res["front_percent"], 82.0)
        self.assertEqual(res["threshold"], 80.0)
        self.assertEqual(res["elapsed_s"], 6.0)   # confirm_n=2: 第3/4帧是两个不同的拍

    def test_reached_t1_uses_offset(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(70.0), _chan(70.0)])
        res = self._wait(detect, clock, stage="t1")
        self.assertEqual(res["status"], "reached")
        self.assertEqual(res["threshold"], 65.0)
        self.assertEqual(res["elapsed_s"], 2.0)   # 两个不同拍即确认, 不靠 hard_cap 兜

    def test_degraded_unreachable(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(50.0, reachable=False)])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "unreachable")
        self.assertGreaterEqual(res["elapsed_s"], 6.0)

    def test_front_none_waits_to_hard_cap(self) -> None:
        # 前沿线未成形 = 正常等待, 不再 30s 降级; 由 hard_cap 兜底
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None)]), clock, hard_cap_s=20.0)
        self.assertEqual(res["status"], "hard_cap")
        self.assertEqual(res["reason"], "waiting:front_none")

    def test_no_front_waits_to_hard_cap(self) -> None:
        # 前沿未进 ROI (invalid:no_front) = 物理正常等待态, 不降级 (0715 ch6 回放根因)
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None, valid=False, reason="no_front")]),
                         clock, hard_cap_s=20.0)
        self.assertEqual(res["status"], "hard_cap")
        self.assertEqual(res["reason"], "waiting:no_front")

    def test_no_front_then_ramp_reaches(self) -> None:
        # 0715 时间线缩样: 长等待 (前沿未进 ROI) 后前沿爬坡 → reached, 全程不降级
        clock = FakeClock()
        frames = [_chan(None, valid=False, reason="no_front")] * 30 + [
            _chan(40.0), _chan(70.0), _chan(85.0), _chan(85.0)]
        res = self._wait(FakeDetect(frames), clock, hard_cap_s=500.0)
        self.assertEqual(res["status"], "reached")

    def test_no_reference_config_degraded_immediately(self) -> None:
        # 无参考 → Otsu 回退值不可信: 立即配置错误降级, 不等 staleness_s
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(85.0, has_ref=False)]), clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "config:no_reference")
        self.assertEqual(res["elapsed_s"], 0.0)

    def test_no_roi_config_degraded_immediately(self) -> None:
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None, valid=False, reason="no_roi")]), clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "config:no_roi")

    def test_frame_dark_transport_degraded(self) -> None:
        # 暗帧按传输类累计: 持续 >= staleness_s 才降级 (曝光爬坡数秒不触发)
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None, valid=False, reason="frame_dark")]), clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "invalid:frame_dark")
        self.assertGreaterEqual(res["elapsed_s"], 6.0)

    def test_confirm_n_blocks_single_spike(self) -> None:
        # 单拍尖峰 (85) 不触发; 回落后到 hard_cap
        clock = FakeClock()
        frames = [_chan(85.0), _chan(50.0), _chan(50.0)]
        res = self._wait(FakeDetect(frames), clock, hard_cap_s=10.0)
        self.assertEqual(res["status"], "hard_cap")

    def test_same_frame_polled_twice_does_not_confirm(self) -> None:
        """同一检测拍被重复读到不得凑满 confirm_n (2026-07-26 T2 误触发的直接机理)。

        真机 poll_s=2.0 而检测周期 = interval + 处理耗时 > 2.0s, 轮询必然快过检测 ——
        当时 T2 段只有一拍新数据 (front=100), 却在 2.0s 内被数了两次判 reached 并排液。
        这里只给一帧驻留: 去重后 streak 永远停在 1, 确认路径走不通, 一直等到 hard_cap
        才由既有的"检测 > 硬上限"直通契约判 reached。故判据钉在 elapsed_s ——
        旧口径 2.0s (第二次轮询同一拍即确认), 新口径 = hard_cap_s。
        """
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(100.0)]), clock, hard_cap_s=10.0)
        self.assertEqual(res["elapsed_s"], 10.0)   # 不是 2.0: 同一拍没被数第二次
        self.assertEqual(res["status"], "reached")  # hard_cap 到点时在阈上 → 直通契约

    def test_replay_20260726_spike_no_longer_triggers(self) -> None:
        """真实回放钉子: 2026-07-26 07:33:27~36 CH1 那 5 拍不得再触发。

        现场序列 (取自 /api/water_level/history/1 环形缓冲, 板全程是干的):
            :27 percent=0 front=None → :29/:31/:33 percent=100 front=100 → :36 percent=0
        整块 ROI 6 秒内 0%→100%→0% 是整帧亮度跳变, 不是前沿。检测侧的结构门
        (waterlevel_detector.analyze_front 的干拖尾判据) 会把这三拍判成 roi_saturated
        无效 —— 整条 profile 被抬平、下游拖尾一并过判湿线, 单帧即可认出, 到本层
        表现为 invalid:roi_saturated (传输类, 6s < staleness_s 不降级), 前沿继续等。
        """
        clock = FakeClock()
        frames = (
            [_chan(None, valid=False, reason="no_front")] * 3
            + [_chan(None, valid=False, reason="roi_saturated")] * 3   # 被结构门拒的三拍
            + [_chan(None, valid=False, reason="no_front")] * 3
        )
        res = self._wait(FakeDetect(frames), clock, staleness_s=30.0, hard_cap_s=20.0)
        self.assertEqual(res["status"], "hard_cap")     # 等到硬上限, 而不是 reached
        self.assertNotEqual(res["status"], "reached")

    def test_roi_saturated_persisting_degrades(self) -> None:
        # 持续性整区判湿 (照明一直在抖/曝光锁死) 按传输类累计 → staleness_s 后升 HITL 交人决定
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None, valid=False, reason="roi_saturated")]), clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "invalid:roi_saturated")
        self.assertGreaterEqual(res["elapsed_s"], 6.0)

    def test_no_front_is_waiting_not_degraded(self) -> None:
        """前沿未进 ROI 是物理正常等待态, 不得升 HITL —— 只由 hard_cap 兜底。

        no_front = analyze_front 的锚定判据不过 (流入侧湿平台幅值未起来)。
        若漏进 _WAITING_REASONS 白名单, 展开前段每一拍都会被当成传输故障, 30s 即误弹人工门。
        """
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None, valid=False, reason="no_front")]),
                         clock, staleness_s=30.0, hard_cap_s=20.0)
        self.assertEqual(res["status"], "hard_cap")

    def test_confirm_n_one_keeps_single_hit(self) -> None:
        # confirm_n=1 = 旧行为单拍即触
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(85.0)]), clock, confirm_n=1)
        self.assertEqual(res["status"], "reached")
        self.assertEqual(res["elapsed_s"], 0.0)

    def test_degraded_stale_observed_at(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(50.0, age_s=999.0)])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "degraded")
        self.assertTrue(res["reason"].startswith("stale:"))

    def test_degraded_channel_missing(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([None])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "channel_missing")

    def test_bad_streak_resets_on_recovery(self) -> None:
        # 4s 坏 + 恢复 + 再坏: 不累计跨段, 恢复后从零重计 → 先命中阈值
        clock = FakeClock()
        detect = FakeDetect([_chan(50.0, reachable=False), _chan(50.0, reachable=False),
                             _chan(60.0), _chan(85.0), _chan(85.0)])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "reached")

    def test_hard_cap(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(50.0)])
        res = self._wait(detect, clock, hard_cap_s=10.0)
        self.assertEqual(res["status"], "hard_cap")
        self.assertEqual(res["front_percent"], 50.0)
        self.assertGreaterEqual(res["elapsed_s"], 10.0)

    def test_hard_cap_zero_immediate(self) -> None:
        # T2 段剩余预算被扣到 0: 首轮即 hard_cap (兜底直排), 但已到阈值优先 reached
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(50.0)]), clock, hard_cap_s=0.0)
        self.assertEqual(res["status"], "hard_cap")
        clock2 = FakeClock()
        res2 = self._wait(FakeDetect([_chan(85.0)]), clock2, hard_cap_s=0.0)
        self.assertEqual(res2["status"], "reached")   # 检测 > 硬上限


class HostActionDispatchTests(unittest.TestCase):
    """develop.wait_level 经 ActionRegistry + ActionExecutor (kind=host) 的派发契约."""

    @classmethod
    def setUpClass(cls) -> None:
        from eit_ptlc.action.registry import ActionRegistry
        cls.registry = ActionRegistry.load(_PKG / "config" / "actions")

    def test_action_definition(self) -> None:
        adef = self.registry.get("develop.wait_level")
        self.assertEqual(adef.kind, "host")
        self.assertEqual(adef.method, "wait_level")
        stage = adef.param("stage")
        self.assertEqual(stage.type, "enum")
        self.assertEqual([o.value for o in stage.options], ["t1", "t2"])
        tank = adef.param("target_tank")
        self.assertTrue(tank.required)
        self.assertEqual((tank.minimum, tank.maximum), (1, 8))
        self.assertEqual(adef.param("staleness_s").default, 30.0)
        self.assertEqual(adef.param("hard_cap_s").default, 3600.0)
        self.assertEqual(adef.param("confirm_n").default, 2)

    def test_capture_action_definition(self) -> None:
        adef = self.registry.get("develop.capture_reference")
        self.assertEqual(adef.kind, "host")
        self.assertEqual(adef.method, "capture_reference")
        tank = adef.param("target_tank")
        self.assertTrue(tank.required)
        self.assertEqual((tank.minimum, tank.maximum), (1, 8))
        self.assertEqual(adef.param("timeout_s").default, 90.0)

    def test_capture_dispatch(self) -> None:
        from eit_ptlc.action.executor import ActionExecutor
        from eit_ptlc.action.models import ActionStatus
        seen = {}

        async def fake_capture(**kwargs):
            seen.update(kwargs)
            return {"ok": True, "has_ref": True, "elapsed_s": 31.0}

        executor = ActionExecutor(self.registry, vision_methods={"capture_reference": fake_capture})
        res = asyncio.run(executor.execute("develop.capture_reference", {"target_tank": 6}))
        self.assertIs(res.status, ActionStatus.DONE)
        self.assertTrue(res.result["ok"])
        self.assertEqual(seen, {"target_tank": 6, "timeout_s": 90.0})

    def test_executor_dispatches_to_injected_method(self) -> None:
        from eit_ptlc.action.executor import ActionExecutor
        from eit_ptlc.action.models import ActionStatus
        seen = {}

        async def fake_wait_level(**kwargs):
            seen.update(kwargs)
            return {"status": "reached", "front_percent": 91.0,
                    "threshold": 90.0, "stage": kwargs["stage"],
                    "elapsed_s": 1.0, "reason": ""}

        executor = ActionExecutor(self.registry, vision_methods={"wait_level": fake_wait_level})
        res = asyncio.run(executor.execute(
            "develop.wait_level", {"target_tank": 2, "stage": "t2"}))
        self.assertIs(res.status, ActionStatus.DONE)
        self.assertEqual(res.result["status"], "reached")
        # 默认参数应随校验强转一并进 kwargs
        self.assertEqual(seen, {"target_tank": 2, "stage": "t2",
                                "staleness_s": 30.0, "hard_cap_s": 3600.0,
                                "confirm_n": 2})

    def test_executor_rejects_bad_stage(self) -> None:
        from eit_ptlc.action.executor import ActionExecutor
        from eit_ptlc.action.models import ActionStatus

        async def fake_wait_level(**kwargs):  # pragma: no cover - 不应被调到
            raise AssertionError("不应派发")

        executor = ActionExecutor(self.registry, vision_methods={"wait_level": fake_wait_level})
        res = asyncio.run(executor.execute(
            "develop.wait_level", {"target_tank": 2, "stage": "t9"}))
        self.assertIs(res.status, ActionStatus.REJECTED)


class FakeRefDetect:
    """假检测服务: 镜像 has_reference 语义 (in refs and not pending); 可预置旧参考."""

    def __init__(self, ready_after=2, preseeded=False) -> None:
        self.requests: list[int] = []
        self.cancels: list[int] = []
        self.ensured: list[int] = []
        self._polls = 0
        self._ready_after = ready_after
        self._refs: set[int] = set()
        self._pending: set[int] = set()
        self._preseed = preseeded

    async def ensure_active(self, ch: int) -> None:
        self.ensured.append(int(ch))

    def request_reference(self, ch: int) -> None:
        ch = int(ch)
        if self._preseed:
            self._refs.add(ch)          # 旧 run 留下的参考仍在
        self.requests.append(ch)
        self._pending.add(ch)

    def cancel_reference(self, ch: int) -> None:
        ch = int(ch)
        self.cancels.append(ch)
        self._pending.discard(ch)

    def has_reference(self, ch: int) -> bool:
        ch = int(ch)
        self._polls += 1
        if (self._ready_after is not None and self._polls > self._ready_after
                and ch in self._pending):
            self._refs.add(ch)          # 窗口完成: 新基线落位
            self._pending.discard(ch)
        return ch in self._refs and ch not in self._pending


class _NoEnsureRefDetect:
    """无 ensure_active 方法的最小假检测服务: 验证 capture_reference 的缺席容错分支."""

    def __init__(self) -> None:
        self._polls = 0
        self.requests: list[int] = []

    def request_reference(self, ch: int) -> None:
        self.requests.append(int(ch))

    def has_reference(self, ch: int) -> bool:
        self._polls += 1
        return self._polls > 1

    def cancel_reference(self, ch: int) -> None:  # pragma: no cover - 不应被调到
        raise AssertionError("不应超时")


class CaptureReferenceTests(unittest.TestCase):
    def test_ok_after_window(self) -> None:
        clock = FakeClock()
        det = FakeRefDetect(ready_after=2)
        res = _run(capture_reference(det, target_tank=6, timeout_s=90.0, poll_s=1.0,
                                     time_fn=clock.time, sleep=clock.sleep))
        self.assertEqual(res, {"ok": True, "has_ref": True, "elapsed_s": 2.0})
        self.assertEqual(det.ensured, [6])     # 采集前确保通道在采
        self.assertEqual(det.requests, [6])    # 每 run 无条件重拍
        self.assertEqual(det.cancels, [])

    def test_timeout_cancels_pending(self) -> None:
        # 超时必须撤销挂起窗口: 防帧源迟到后在湿板上补采毒参考
        clock = FakeClock()
        det = FakeRefDetect(ready_after=None)
        res = _run(capture_reference(det, target_tank=3, timeout_s=5.0, poll_s=1.0,
                                     time_fn=clock.time, sleep=clock.sleep))
        self.assertFalse(res["ok"])
        self.assertFalse(res["has_ref"])
        self.assertGreaterEqual(res["elapsed_s"], 5.0)
        self.assertEqual(det.cancels, [3])

    def test_stale_ref_does_not_short_circuit(self) -> None:
        # 第二个 run: 旧板参考仍在 _refs — 不得首拍短路, 必须等新窗口完成 (Critical 回归锁)
        clock = FakeClock()
        det = FakeRefDetect(ready_after=2, preseeded=True)
        res = _run(capture_reference(det, target_tank=6, timeout_s=90.0, poll_s=1.0,
                                     time_fn=clock.time, sleep=clock.sleep))
        self.assertEqual(res["ok"], True)
        self.assertEqual(res["elapsed_s"], 2.0)   # 等了窗口, 不是 0.0

    def test_timeout_with_stale_ref_reports_has_ref_true(self) -> None:
        # 超时 + 盘上有旧参考: ok=False 但 has_ref=True (诚实汇报旧基线仍在)
        clock = FakeClock()
        det = FakeRefDetect(ready_after=None, preseeded=True)
        res = _run(capture_reference(det, target_tank=3, timeout_s=5.0, poll_s=1.0,
                                     time_fn=clock.time, sleep=clock.sleep))
        self.assertFalse(res["ok"])
        self.assertTrue(res["has_ref"])
        self.assertEqual(det.cancels, [3])

    def test_ensure_active_absent_ok(self) -> None:
        # 无 ensure_active 方法的检测服务 (getattr 容错分支): 正常完成不抛
        clock = FakeClock()
        det = _NoEnsureRefDetect()
        res = _run(capture_reference(det, target_tank=2, timeout_s=10.0, poll_s=1.0,
                                     time_fn=clock.time, sleep=clock.sleep))
        self.assertEqual(res["ok"], True)
        self.assertEqual(det.requests, [2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
