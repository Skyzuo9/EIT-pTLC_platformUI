"""离线: ExperimentStore (experiments.db) 实体库.

覆盖:
    1. 建批事务 (批+样品+段作业) 与查询形状 (detail 嵌套 / 列表聚合)
    2. 状态迁移合法性 (非法值拒绝) 与字段白名单
    3. 样品上下文合并; 按 run_id 反查段作业
    4. mark_interrupted_on_boot: 在飞段 INTERRUPTED + 批 PAUSED + QUEUED 批不动
    5. 结果摄取: summary + band metrics -> results 行, Rf 计算, 幂等重摄取

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_experiment_store_offline.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.runtime.experiment_store import ExperimentStore  # noqa: E402


def _store_with_batch(batch_id="B1", samples=2) -> ExperimentStore:
    s = ExperimentStore(":memory:")
    s.create_batch(
        batch_id, name="测试批", recipe="parallel_v1", priority=1,
        tank_pool=[1, 2], params={"auto_drain": True},
        config_snapshot={"pump": {"x": 1}},
        samples=[{"sample_id": f"S-{i:02d}", "seq": i, "position": "feedlift"}
                 for i in range(1, samples + 1)],
        jobs=[{"job_id": f"{batch_id}-af0", "sample_id": None, "flow_id": "af0",
               "af_index": 0, "script": "pf_af0_batch_startup", "depends": []}] + [
            {"job_id": f"S-{i:02d}-s1", "sample_id": f"S-{i:02d}", "flow_id": "s1",
             "af_index": 1, "script": "pf_s1_load", "depends": ["af0"]}
            for i in range(1, samples + 1)])
    return s


class EntityTest(unittest.TestCase):
    def test_create_and_detail(self) -> None:
        s = _store_with_batch()
        batch = s.get_batch("B1")
        self.assertEqual(batch["status"], "QUEUED")
        self.assertEqual(batch["tank_pool"], [1, 2])
        self.assertEqual(batch["config_snapshot"]["pump"], {"x": 1})
        detail = s.get_batch_detail("B1")
        self.assertEqual(len(detail["samples"]), 2)
        self.assertEqual(len(detail["batch_jobs"]), 1)
        self.assertEqual(len(detail["samples"][0]["jobs"]), 1)
        rows = s.list_batches()
        self.assertEqual((rows[0]["sample_total"], rows[0]["sample_done"]), (2, 0))
        self.assertEqual(s.sample_ids_exist(["S-01", "S-99"]), ["S-01"])

    def test_update_guards(self) -> None:
        s = _store_with_batch()
        with self.assertRaises(ValueError):
            s.update_batch("B1", status="不存在的态")
        with self.assertRaises(ValueError):
            s.update_job("S-01-s1", nonsense_field=1)
        s.update_job("S-01-s1", status="RUNNING", run_id="r1", started_at=1.0)
        self.assertEqual(s.job_by_run_id("r1")["job_id"], "S-01-s1")
        ctx = s.merge_sample_context("S-01", {"before_path": "b.jpg"})
        ctx = s.merge_sample_context("S-01", {"tank": 2})
        self.assertEqual(ctx, {"before_path": "b.jpg", "tank": 2})

    def test_mark_interrupted_spares_queued_batches(self) -> None:
        s = _store_with_batch("B1")
        s.create_batch("B2", name="排队批", recipe="parallel_v1",
                       samples=[{"sample_id": "Q-01", "seq": 1, "position": "feedlift"}],
                       jobs=[{"job_id": "Q-01-s1", "sample_id": "Q-01", "flow_id": "s1",
                              "af_index": 1, "script": "pf_s1_load", "depends": []}])
        s.update_batch("B1", status="RUNNING")
        s.update_job("S-01-s1", status="RUNNING", run_id="r1")
        s.update_job("S-02-s1", status="WAITING_HUMAN", run_id="r2")
        report = s.mark_interrupted_on_boot()
        self.assertEqual(report["jobs"], 2)
        self.assertEqual(report["batches"], ["B1"])
        self.assertEqual(s.get_batch("B1")["status"], "PAUSED")
        self.assertTrue(s.get_batch("B1")["needs_reconcile"])
        self.assertEqual(s.get_job("S-01-s1")["status"], "INTERRUPTED")
        # QUEUED 批 (无在飞) 不动: 调度器就绪后可正常起跑
        self.assertEqual(s.get_batch("B2")["status"], "QUEUED")
        self.assertFalse(s.get_batch("B2")["needs_reconcile"])


class ResultsIngestTest(unittest.TestCase):
    def _case_dir(self, root: Path) -> Path:
        case = root / "S-01"
        (case / "task3_metrics").mkdir(parents=True)
        (case / "summary.json").write_text(json.dumps({
            "bands": [{"band_id": 1}, {"band_id": 2}],
            "solvent_front": {"distance_from_origin_cm": 5.0},
            "origin_band": {"center_cm": [1.0, 2.0]},
            "plate_bbox_px": [0, 0, 100, 200],
        }), encoding="utf-8")
        (case / "task3_metrics" / "band_01_metrics.json").write_text(json.dumps({
            "band": {"band_id": 1, "distance_to_origin_cm": 2.5},
            "solvent_front": {"distance_from_origin_cm": 5.0},
        }), encoding="utf-8")
        (case / "task3_metrics" / "band_02_metrics.json").write_text(json.dumps({
            "band": {"band_id": 2, "distance_to_origin_cm": 4.0},
        }), encoding="utf-8")
        return case

    def test_ingest_and_rf(self) -> None:
        s = _store_with_batch()
        with tempfile.TemporaryDirectory() as tmp:
            case = self._case_dir(Path(tmp))
            n = s.ingest_vision_results("S-01", case)
            self.assertEqual(n, 3, "summary + 2 条带")
            rows = s.list_results(sample_id="S-01")
            summary = [r for r in rows if r["kind"] == "vision_summary"][0]
            self.assertEqual(summary["band_count"], 2)
            self.assertEqual(summary["batch_id"], "B1")
            bands = {r["band_id"]: r for r in rows if r["kind"] == "band"}
            self.assertAlmostEqual(bands[1]["rf"], 0.5, places=3)
            # band_02 自身无 solvent_front -> 用 summary 级前沿兜底
            self.assertAlmostEqual(bands[2]["rf"], 0.8, places=3)
            # 幂等重摄取: 行数不翻倍
            s.ingest_vision_results("S-01", case)
            self.assertEqual(len(s.list_results(sample_id="S-01")), 3)

    def test_ingest_missing_summary(self) -> None:
        s = _store_with_batch()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(s.ingest_vision_results("S-01", Path(tmp) / "nope"), 0)


if __name__ == "__main__":
    unittest.main()
