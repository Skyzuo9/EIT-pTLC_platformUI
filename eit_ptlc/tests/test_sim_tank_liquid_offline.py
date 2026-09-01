"""展缸液量模型的离线测试
========================
功能:
    钉住 M4-4 的三条:
      ① **容量与排液时长取自三维 manifest**, 不在后端硬编码 (硬编码就会与三维分叉);
      ② 积分**读物理状态不读动作码** —— 进液看"泵排出量 × 进液阀", 排液看排液阀,
         于是 A26 抽吸 / A50 排液桥 / 人手开阀三条路天然都覆盖;
      ③ 浸泡计时走**名义秒**而不是挂钟 —— 否则 time_scale=20 下 wait_level 仍要等
         真实几分钟。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest \
        eit_ptlc/tests/test_sim_tank_liquid_offline.py -q
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from eit_ptlc.mock.behavior.tank_liquid import (
    TANK_COUNT, TankLiquidModel, build_model, tank_group, tank_number)

_MANIFEST = (Path(__file__).resolve().parents[1] / "three_d" / "models"
             / "device-manifest.official-cr5.json")


class TestTankLiquidModel(unittest.TestCase):
    """液量积分 / 前沿推导 / 真源取值."""

    def _model(self) -> TankLiquidModel:
        return build_model(json.loads(_MANIFEST.read_text(encoding="utf-8")))

    def test_capacity_comes_from_the_twin_manifest(self):
        """容量与排液时长必须来自 manifest, 且与三维读的是同一份数."""
        raw = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        block = raw["tankLiquid"]
        model = build_model(raw)
        self.assertEqual(model.capacity_ml, float(block["cavity"]["capacityMl"]))
        self.assertEqual(model.drain_ramp_s,
                         float(block["actions"]["develop.drain"]["rampS"]))
        self.assertGreater(model.capacity_ml, 0, "实测溶液槽容量应为正")

        # manifest 缺席时容量为 0 —— 液量恒 0 而不是编一个默认容量
        blind = build_model(None)
        self.assertEqual(blind.capacity_ml, 0.0)
        blind.fill(1, 50.0)
        self.assertEqual(blind.volume_ml[1], 0.0, "没有容量真源就不该凭空生出液体")

    def test_fill_and_drain_are_clamped(self):
        """注排都夹逼在 [0, 容量]; 满了溢不进去, 空了排不出来."""
        model = self._model()
        taken = model.fill(3, 1e6)
        self.assertAlmostEqual(taken, model.capacity_ml, places=3)
        self.assertAlmostEqual(model.volume_ml[3], model.capacity_ml, places=3)
        self.assertEqual(model.fill(3, 10.0), 0.0, "满缸再灌应一滴进不去")

        # 排液速率 = 容量 / rampS; 排满一整程正好清空
        drained = model.drain(3, model.drain_ramp_s)
        self.assertAlmostEqual(drained, model.capacity_ml, places=3)
        self.assertAlmostEqual(model.volume_ml[3], 0.0, places=6)
        self.assertEqual(model.drain(3, 5.0), 0.0, "空缸排不出东西")

    def test_soak_is_nominal_seconds_not_wall_clock(self):
        """浸泡计时按名义秒累加 —— 这是 time_scale 能加速 wait_level 的前提.

        用挂钟记起算时刻的话, 20 倍速下前沿仍要等真实几分钟, 沙盒就没法演练展开。
        """
        model = self._model()
        model.fill(2, model.capacity_ml)
        self.assertEqual(model.soak_s[2], 0.0)
        model.tick(60.0)
        self.assertEqual(model.soak_s[2], 60.0, "一拍 60 名义秒就该记 60")
        self.assertEqual(model.soak_s[1], 0.0, "空缸不该累计浸泡")

        # 满缸泡了一半 climb_s -> 前沿约 50%
        self.assertAlmostEqual(model.front_percent(2, climb_s=120.0), 50.0, places=3)
        # 液面越浅爬得越慢
        model.drain(2, model.drain_ramp_s / 2.0)
        self.assertLess(model.front_percent(2, climb_s=120.0), 50.0)

    def test_empty_tank_front_is_always_zero(self):
        """空缸前沿恒 0 —— 与真机一致 (没液就永远等不到), 也是"先设液量"这条因果的判据."""
        model = self._model()
        model.tick(9999.0)
        for tank in range(1, TANK_COUNT + 1):
            self.assertEqual(model.front_percent(tank, climb_s=1.0), 0.0)

        # 排空后浸泡计时清零, 前沿从头算
        model.fill(5, model.capacity_ml)
        model.tick(300.0)
        self.assertGreater(model.front_percent(5, climb_s=300.0), 90.0)
        model.drain(5, model.drain_ramp_s)
        self.assertEqual(model.soak_s[5], 0.0, "缸空了浸泡计时要清零")
        model.fill(5, model.capacity_ml)
        self.assertEqual(model.front_percent(5, climb_s=300.0), 0.0, "重新注液从头爬")

    def test_set_volume_rejects_bad_tank(self):
        """写面: 缸号越界如实报错, 不静默吞掉."""
        model = self._model()
        model.set_volume(8, 20.0)
        self.assertAlmostEqual(model.volume_ml[8], 20.0, places=6)
        with self.assertRaises(ValueError):
            model.set_volume(9, 1.0)
        with self.assertRaises(ValueError):
            model.set_volume(0, 1.0)

    def test_group_mapping_matches_develop(self):
        """组号/缸内序号与 develop._tank_context 同式 (1..4 属 1 组, 5..8 属 2 组)."""
        self.assertEqual([tank_group(t) for t in range(1, 9)],
                         [1, 1, 1, 1, 2, 2, 2, 2])
        self.assertEqual([tank_number(t) for t in range(1, 9)],
                         [1, 2, 3, 4, 1, 2, 3, 4])

    def test_snapshot_keys_do_not_collide_with_the_write_face(self):
        """读面逐缸量在 volumes 下而不是 tanks —— 与写面 {"tanks": {...}} 不同名."""
        model = self._model()
        snap = model.snapshot()
        self.assertIn("volumes", snap)
        self.assertNotIn("tanks", snap,
                         "读面若也叫 tanks, 会诱出'读面整个回灌写面'的错觉")
        self.assertEqual(set(snap["volumes"]), {str(t) for t in range(1, TANK_COUNT + 1)})
        self.assertEqual(set(snap["volumes"]["1"]), {"volume_ml", "level", "soak_s"})


class TestSimClockElapsed(unittest.TestCase):
    """名义耗时必须量出来, 不许把请求的 sleep 时长累加起来.

    2026-08-13 段 B 浏览器验收抓到的实缺陷: 累加法在 rate=16 下把 600 名义秒记成了
    实际的 242 秒, 展缸 wait_level 的硬上限提前 2.5 倍触发, 有液的缸也等不到前沿。
    同一个错在展缸液量积分循环里也犯过一次, 故把判据收进时钟本身。
    """

    def test_elapsed_scales_with_rate(self):
        from eit_ptlc.mock.behavior.clock import SimClock
        import time as _time

        clock = SimClock(rate=8.0)
        started = clock.mark()
        _time.sleep(0.05)
        nominal = clock.elapsed(started)
        # 真实 0.05s × 8 = 0.4 名义秒 (给足调度抖动余量, 只钉数量级与方向)
        self.assertGreater(nominal, 0.3, f"名义耗时应随倍率放大: {nominal}")
        self.assertLess(nominal, 1.2, f"不该离谱地放大: {nominal}")

        clock.rate = 1.0
        started = clock.mark()
        _time.sleep(0.05)
        self.assertLess(clock.elapsed(started), 0.3, "倍率 1 时名义秒约等于真实秒")


if __name__ == "__main__":
    unittest.main(verbosity=2)
