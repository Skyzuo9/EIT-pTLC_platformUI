#!/usr/bin/env python3
"""仿真行为层 (mock/behavior) 离线测试
======================================
覆盖:
    1. SimClock: 倍率缩放真实等待;
    2. PumpModel: 对金测试冻结的真实 DT 指令串逐段积分 —— 柱塞轨迹与阀位序列
       必须与 translator plan 语义一致 (吸满 25 → 8 → 3 → 0, 阀 1→3→2→3);
    3. 非法串拒执行 (parse 抛 ValueError 的路径由 dt_codec 测试覆盖, 这里守
       watcher 侧不带病执行的语义在 e2e 里体现)。

运行:
    python -m pytest eit_ptlc/tests/test_sim_behavior_offline.py -q
"""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.mock.behavior.clock import SimClock  # noqa: E402
from eit_ptlc.mock.behavior.pump import PumpModel  # noqa: E402
from eit_ptlc.tools.pump import dt_codec  # noqa: E402

# 金测试 (test_pump_dt_golden_offline) 冻结的 sampling.flush 真实指令串
_FLUSH_CHAINED = "/4V250I1A6000M1500V300I3A1920M1500V300I2A720M1500R\r"
_FLUSH_SPOT_HEAD = "/4V100I3A0M1500R\r"


class PumpCodeTableTests(unittest.TestCase):
    """动作码消费表的关键语义钉住 (与 config/actions 勘察定稿逐条对照)。"""

    def test_code_table_semantics(self) -> None:
        from eit_ptlc.mock.behavior.pump import PUMP_BY_CODE
        # 上样 A50: PLC 消费序 [2]气隔断 → [1]样品
        self.assertEqual(PUMP_BY_CODE[("Sampling", 50)].order, (1, 0))
        # 润洗吹打: 只循环末条 (mix_count)
        self.assertEqual(PUMP_BY_CODE[("Sampling", 55)].repeat, "last")
        self.assertEqual(PUMP_BY_CODE[("Sampling", 55)].count_node,
                         "Sampling_rinse_mix_count")
        # Develop 轮数二义随码消解: 20/21 吃润洗轮数, 22 吃上液轮数
        self.assertEqual(PUMP_BY_CODE[("Develop", 21)].count_node, "Expand_rinse_count")
        self.assertEqual(PUMP_BY_CODE[("Develop", 22)].count_node,
                         "Expand_up_liquid_count")
        # clean/flush 共用 code 20 与 clean 通道
        self.assertEqual(PUMP_BY_CODE[("Sampling", 20)].node,
                         "Sampling_clean_instructions")
        self.assertEqual(PUMP_BY_CODE[("Collect", 30)].count_node, "collect_count")


class SimClockTests(unittest.TestCase):
    def test_rate_scales_real_wait(self) -> None:
        async def run() -> float:
            clock = SimClock(rate=50.0)
            start = time.monotonic()
            await clock.sleep(1.0)          # 名义 1s → 真实 ~0.02s
            return time.monotonic() - start
        elapsed = asyncio.run(run())
        self.assertLess(elapsed, 0.5)
        self.assertGreaterEqual(elapsed, 0.01)


class PumpModelTests(unittest.TestCase):
    def test_flush_program_trajectory_and_ports(self) -> None:
        """虚拟泵按真实 flush 串积分: 峰值 25mL, 逐级 8/3/0, 阀 1→3→2→3。"""
        async def run():
            clock = SimClock(rate=1000.0)   # 快进: 实测 <1s 跑完全程
            model = PumpModel("SMP")
            frames: list[dict] = []
            publish = lambda: frames.append(model.snapshot())  # noqa: E731
            await model.run_program(dt_codec.parse(_FLUSH_CHAINED), clock, publish)
            mid = model.snapshot()
            await model.run_program(dt_codec.parse(_FLUSH_SPOT_HEAD), clock, publish)
            return frames, mid, model.snapshot()

        frames, mid, final = asyncio.run(run())
        peak = max(frame["plunger_ml"] for frame in frames)
        self.assertAlmostEqual(peak, 25.0, delta=0.05, msg="吸满峰值应为 25mL")
        self.assertAlmostEqual(mid["plunger_ml"], 3.0, delta=0.01,
                               msg="链式段终点应停在 720 步 = 3mL")
        self.assertAlmostEqual(final["plunger_ml"], 0.0, delta=0.01,
                               msg="点样头段终点必回 0 (translator 不变量)")
        # 阀位序列 (去重后的先后次序)
        ports_seen: list = []
        for frame in frames:
            if frame["valve_port"] is not None and (
                    not ports_seen or ports_seen[-1] != frame["valve_port"]):
                ports_seen.append(frame["valve_port"])
        self.assertEqual(ports_seen, [1, 3, 2, 3], "阀位序列漂移")
        self.assertFalse(final["busy"])

    def test_duration_reflects_speed(self) -> None:
        """时长由 V 决定 (步数/V): V250 吸 6000 步名义 24s, 倍率 100 下 ≈0.24s 真实。"""
        async def run() -> float:
            clock = SimClock(rate=100.0)
            model = PumpModel("SMP")
            start = time.monotonic()
            await model.run_program(
                dt_codec.parse("/4V250I1A6000M0R\r"), clock, lambda: None)
            return time.monotonic() - start
        elapsed = asyncio.run(run())
        # 名义 24s / 100 = 0.24s; 放宽上下界容忍调度抖动
        self.assertGreater(elapsed, 0.1)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
