"""薄层板位置沙盒投影的离线测试
================================
功能:
    钉住投影的**诚实边界** —— 它能说什么、不能说什么, 以及"不能说"是怎么表达的。

    最重要的一条是反向护栏: 输出里**永远不出现**调度器那些字段。给一个空的
    `tanks: {}` 等于宣称"八个缸都没人占", 是假数据; 而这条断言就是"本投影不是
    第二套调度器"这句话的可执行版本 —— 哪天有人顺手往里加, 它立刻红。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest \
        eit_ptlc/tests/test_sim_plate_projection_offline.py -q
"""

from __future__ import annotations

import unittest
from pathlib import Path

from eit_ptlc.controller.feedlift_count import load_calib
from eit_ptlc.mock.behavior.feedlift import FeedLiftModel
from eit_ptlc.runtime.sim_plate_projection import (
    COVERED_SLOTS, SEAT_SLOTS, project_plate_positions)

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

#: 调度器专属字段: 本投影一个都不许产出
_SCHEDULER_ONLY = ("tanks", "resources", "reservations", "wip_limit",
                   "occupancy", "boot_report")


def _model(feed: int = 12, waste: int = 3) -> FeedLiftModel:
    calib = {name: load_calib(_CONFIG_DIR / "feedlift_calib.json", name, 30)
             for name in ("feed", "waste")}
    return FeedLiftModel(calib=calib, counts={"feed": feed, "waste": waste},
                         capacity={"feed": 30, "waste": 30})


def _project(seats=(), magazines=(), *, feed: int = 12, waste: int = 3, revision: int = 1):
    return project_plate_positions(seats=list(seats), magazines=list(magazines),
                                   feedlift_model=_model(feed, waste), revision=revision)


class TestNotASecondScheduler(unittest.TestCase):
    """反向护栏: 投影不产出任何调度器状态."""

    def test_scheduler_only_fields_never_appear(self):
        for seats in ([], [{"seat": "spot_seat", "label": "点样座", "present": True}]):
            out = _project(seats, [{"magazine": "feed", "count": 12, "capacity": 30}])
            for field in _SCHEDULER_ONLY:
                self.assertNotIn(field, out,
                                 f"投影产出了调度器字段 {field} —— 它就成了第二套调度器")

    def test_samples_never_carry_jobs(self):
        """恒空 jobs: 编一个 run_id 会让 L2 迁移错误归属, 比不归属更坏."""
        out = _project([{"seat": "spot_seat", "label": "点样座", "present": True},
                        {"seat": "scrape_table", "label": "刮板台", "present": True}])
        samples = out["batches"][0]["samples"]
        self.assertEqual(len(samples), 2)
        for sample in samples:
            self.assertEqual(sample["jobs"], [])
            self.assertIsNone(sample["tank"], "缸里有哪块板给不出, 不许猜")
            self.assertTrue(sample["synthetic"])

    def test_identity_declares_itself_synthetic(self):
        out = _project()
        self.assertEqual(out["identity"], "synthetic")
        self.assertEqual(out["coverage"]["run_index"], "unavailable")


class TestCoverage(unittest.TestCase):
    """"缺"与"空"的分界."""

    def test_tanks_became_covered_and_only_carried_is_left(self):
        """2026-08-13: 8 个缸位进了拓扑 seats, 于是从"覆盖外"转成了说得清的落点.

        此前缸位是 uncovered 的, 理由是"那在真机上是调度器缸池的状态, 沙盒不装调度器
        故不知道"。补了 tank_1..tank_8 座 + material_bindings 的 plate_seat 之后,
        "哪块板在哪个缸"第一次成了现场账 —— 覆盖外只剩 carried 一项。
        """
        out = _project()
        uncovered = out["coverage"]["uncovered"]
        for tank in range(1, 9):
            self.assertIn(f"tank:{tank}", COVERED_SLOTS)
            self.assertNotIn(f"tank:{tank}", uncovered)
        self.assertEqual(uncovered, ["carried"],
                         "板被吸盘带着走时后端从不报, 必须仍声明为覆盖外, "
                         "否则前端会把半空中的板回收掉")

    def test_covered_slots_match_the_seat_vocabulary(self):
        out = _project()
        self.assertEqual(out["coverage"]["slots"], list(COVERED_SLOTS))
        self.assertIn("spot_seat", COVERED_SLOTS)
        self.assertIn("scrape_table", COVERED_SLOTS)

    def test_covered_is_wider_than_sample_producing(self):
        """覆盖面 ⊋ 产 sample 的座: 板仓沙盒也说得清, 只是不建独立板实例."""
        self.assertTrue(set(SEAT_SLOTS) < set(COVERED_SLOTS))
        for magazine in ("feedlift", "waste"):
            self.assertIn(magazine, COVERED_SLOTS)
            self.assertNotIn(magazine, SEAT_SLOTS)

    def test_every_uncovered_slot_has_a_reason(self):
        """给不出的落点都要说明为什么 —— 否则前端只知道缺, 不知道该不该等."""
        notes = _project()["coverage"]["notes"]
        self.assertIn("carried", notes)
        self.assertNotIn("tank", notes, "缸位已转为覆盖内, 就不该再留一条'为什么给不出'")
        for slot in _project()["coverage"]["uncovered"]:
            self.assertIn(slot.split(":")[0], notes, f"{slot} 缺一条说明")


class TestSamples(unittest.TestCase):
    """样品行的取数."""

    def test_absent_seat_produces_no_sample(self):
        out = _project([{"seat": "spot_seat", "label": "点样座", "present": False}])
        self.assertEqual(out["batches"][0]["samples"], [])

    def test_magazines_produce_no_samples(self):
        """仓态由料仓堆叠画; 为它造 sample 只会污染板层计数."""
        out = _project([{"seat": "feedlift", "label": "上料仓", "present": True}],
                       [{"magazine": "feed", "count": 12, "capacity": 30}])
        positions = [s["position"] for s in out["batches"][0]["samples"]]
        self.assertNotIn("feedlift", positions,
                         "板仓不该产 sample (前端 onPlate=false 本就会滤掉)")

    def test_sample_id_is_position_derived(self):
        out = _project([{"seat": "spot_seat", "label": "点样座", "present": True}])
        sample = out["batches"][0]["samples"][0]
        self.assertEqual(sample["sample_id"], "sim:seat:spot_seat")
        self.assertEqual(sample["position"], "spot_seat")
        self.assertNotIn(sample["status"], ("HOLD", "ABORTED"),
                         "状态不该落进前端的待处理词表")


class TestMagazineRows(unittest.TestCase):
    """板仓行: 账面与模型并排, 背离可见."""

    def test_divergence_is_reported_not_hidden(self):
        out = _project(magazines=[{"magazine": "feed", "count": 12, "capacity": 30},
                                  {"magazine": "waste", "count": 9, "capacity": 30}],
                       feed=12, waste=3)
        rows = {row["magazine"]: row for row in out["magazines"]}
        self.assertFalse(rows["feed"]["diverged"], "账面与模型相等时不该报背离")
        self.assertTrue(rows["waste"]["diverged"],
                        "账面 9 而模型 3: 背离必须报出来, 不许抹平")
        self.assertEqual(rows["waste"]["ledger_count"], 9)
        self.assertEqual(rows["waste"]["model_count"], 3)

    def test_pitch_comes_from_the_same_calib_as_the_model(self):
        """节距给前端画板堆用: 与沙盒板堆模型同一份标定, 不是第二个数."""
        out = _project(magazines=[{"magazine": "feed", "count": 12, "capacity": 30}])
        row = out["magazines"][0]
        model = _model()
        self.assertAlmostEqual(row["pitch_mm"], model.calib["feed"].pitch_mm)
        self.assertAlmostEqual(row["z_trigger_mm"], model.z_trigger("feed"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
