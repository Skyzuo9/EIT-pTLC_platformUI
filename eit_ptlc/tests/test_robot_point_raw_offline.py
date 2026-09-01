#!/usr/bin/env python3
"""单点原始片段读写离线测试
==========================
功能:
    校验 PointsService.read_point_raw / save_point_raw —— 只抽取/编辑当前机器人点
    对应的源条目 (基础点: robot_points.json 条目 + overrides; 派生点: supplement 条目),
    保存走 PointRegistry.load 全量校验, 不通过不写盘。

    使用真源文件的临时副本, 避免测试污染 config/ 真源。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402
from eit_ptlc.controller.points_service import (  # noqa: E402
    PointsCatalogError,
    PointsService,
)
from eit_ptlc.driver.robot_transport import RobotFeedback, ToolState  # noqa: E402

_CFG = _PKG / "config"


class _FakeRobot:
    def __init__(self, *, pose: tuple[float, ...], joint: tuple[float, ...]) -> None:
        self.registry = None
        self.pose = pose
        self.joint = joint
        self.calls: list[tuple[int | None, int | None]] = []

    def query(self, *, user: int | None = None, tool: int | None = None) -> RobotFeedback:
        self.calls.append((user, tool))
        return RobotFeedback(
            pose=self.pose,
            joint=self.joint,
            check_result=0,
            last_action=24,
            tool_state=ToolState(
                commanded_bits=0,
                actual_bits=0,
                di_bits=0,
                di_available=False,
                di_confirmed=False,
            ),
        )


class RobotPointRawTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = load_config(_CFG / "app.yaml")
        self.tmp = Path(tempfile.mkdtemp(prefix="ptraw_"))
        self.points_file = self.tmp / "robot_points.json"
        self.meta_file = self.tmp / "robot_points_meta.json"
        shutil.copy(self.cfg.robot.points_file, self.points_file)
        shutil.copy(self.cfg.robot.points_meta_file, self.meta_file)
        # 中文名真源随点表一起复制: 单点保存走临时配对文件重建 registry, 若 labels 路径未显式
        # 传给 PointRegistry.load, 重建后中文名会整体丢失 (下方 test_save_keeps_labels 守护)
        shutil.copy(Path(self.cfg.robot.points_meta_file).parent / "labels.yaml", self.tmp / "labels.yaml")
        self.svc = self._build()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self, robot=None) -> PointsService:
        reg = PointRegistry.load(
            self.points_file, source_version=self.cfg.robot.point_source_version,
            meta_path=self.meta_file)
        if robot is not None:
            robot.registry = reg
        return PointsService(
            _CFG / "points", reg,
            robot=robot,
            robot_points_file=self.points_file, robot_meta_file=self.meta_file,
            point_source_version=self.cfg.robot.point_source_version)

    # ---- 读: 片段只含本点对应的源条目 ----

    def test_read_base_point_fragment(self) -> None:
        raw = self.svc.read_point_raw("robot", "P45")
        self.assertFalse(raw["is_derived"])
        frag = json.loads(raw["text"])
        self.assertEqual(set(frag), {"point", "meta"})
        self.assertEqual(frag["point"]["name"], "P45")
        self.assertIn("allowed_motion", frag["meta"])  # P45 有 overrides

    def test_read_derived_point_fragment(self) -> None:
        raw = self.svc.read_point_raw("robot", "collect-bottle-pick.far")
        self.assertTrue(raw["is_derived"])
        frag = json.loads(raw["text"])
        self.assertEqual(set(frag), {"supplement"})
        self.assertEqual(frag["supplement"]["point_id"], "collect-bottle-pick.far")
        self.assertEqual(frag["supplement"]["base_point"], "P72")

    def test_non_robot_rejected(self) -> None:
        with self.assertRaises(PointsCatalogError):
            self.svc.read_point_raw("plc_servo", "rail_p1_sampling")

    # ---- 写: 拼回 + 全量校验 + 热替换 ----

    def test_save_base_point_meta_roundtrip(self) -> None:
        raw = self.svc.read_point_raw("robot", "P45")
        frag = json.loads(raw["text"])
        frag["meta"]["notes"] = "edited-by-test"
        res = self.svc.save_point_raw("robot", "P45", json.dumps(frag))
        self.assertTrue(res["saved"])
        # 磁盘 overrides 已更新
        meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        self.assertEqual(meta["overrides"]["P45"]["notes"], "edited-by-test")
        # 运行期 registry 热替换生效
        self.assertEqual(self._build().get("robot", "P45")["notes"], "edited-by-test")

    def test_save_keeps_labels(self) -> None:
        """单点保存后中文名不得丢失 (热替换路径用临时 meta, 须显式传 labels 真源)。"""
        before = self.svc.get("robot", "P45")["label"]
        self.assertTrue(before, "前置条件: P45 应有中文名")
        raw = self.svc.read_point_raw("robot", "P45")
        frag = json.loads(raw["text"])
        frag["meta"]["notes"] = "label-guard"
        self.svc.save_point_raw("robot", "P45", json.dumps(frag))
        self.assertEqual(self.svc.get("robot", "P45")["label"], before)          # 热替换后的运行期点表
        self.assertEqual(self.svc.get("robot", "tank.1.approach_far")["label"],  # 派生点自动生成名同样保留
                         "1号展开缸·远接近")

    def test_save_derived_offset_roundtrip(self) -> None:
        raw = self.svc.read_point_raw("robot", "collect-bottle-pick.far")
        frag = json.loads(raw["text"])
        frag["supplement"]["offset"] = [0, 0, 120, 0, 0, 0]
        res = self.svc.save_point_raw("robot", "collect-bottle-pick.far", json.dumps(frag))
        self.assertTrue(res["saved"])
        meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        sup = next(r for r in meta["supplement"] if r["point_id"] == "collect-bottle-pick.far")
        self.assertEqual(sup["offset"], [0, 0, 120, 0, 0, 0])

    def test_reject_rename_name(self) -> None:
        raw = self.svc.read_point_raw("robot", "P45")
        frag = json.loads(raw["text"])
        frag["point"]["name"] = "P999"
        before = self.points_file.read_text(encoding="utf-8")
        with self.assertRaises(PointsCatalogError):
            self.svc.save_point_raw("robot", "P45", json.dumps(frag))
        self.assertEqual(self.points_file.read_text(encoding="utf-8"), before)  # 未写盘

    def test_reject_invalid_does_not_write(self) -> None:
        # validated 点移除 allowed_motion -> PointRegistry 校验失败
        raw = self.svc.read_point_raw("robot", "P45")
        frag = json.loads(raw["text"])
        frag["meta"]["allowed_motion"] = []
        before = self.meta_file.read_text(encoding="utf-8")
        with self.assertRaises((PointsCatalogError, ValueError)):
            self.svc.save_point_raw("robot", "P45", json.dumps(frag))
        self.assertEqual(self.meta_file.read_text(encoding="utf-8"), before)  # 未写盘

    # ---- 机器人示教: 读当前位置 -> 预览 -> 确认覆盖基础点 pose/joint ----

    def test_capture_robot_point_preview_uses_point_user_tool(self) -> None:
        robot = _FakeRobot(
            pose=(1.1, 2.2, 3.3, 4.4, 5.5, 6.6),
            joint=(10.0, 20.0, 30.0, 40.0, 50.0, 60.0),
        )
        self.svc = self._build(robot=robot)
        detail = self.svc.get("robot", "P45")

        preview = self.svc.capture_robot_point("P45")

        self.assertEqual(robot.calls[-1], (detail["user"], detail["tool"]))
        self.assertEqual(preview["captured"]["pose"], [1.1, 2.2, 3.3, 4.4, 5.5, 6.6])
        self.assertEqual(preview["captured"]["joint"], [10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
        self.assertEqual([round(v, 4) for v in preview["current"]["pose"]], detail["pose"])

    def test_commit_robot_point_capture_preserves_original_fields(self) -> None:
        robot = _FakeRobot(
            pose=(101.0, 102.0, 103.0, 104.0, 105.0, 106.0),
            joint=(11.0, 12.0, 13.0, 14.0, 15.0, 16.0),
        )
        self.svc = self._build(robot=robot)
        before_points = json.loads(self.points_file.read_text(encoding="utf-8-sig"))
        before_meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        before_record = next(r for r in before_points if r["name"] == "P45")
        before_override = dict(before_meta.get("overrides", {}).get("P45", {}))

        preview = self.svc.capture_robot_point("P45")
        res = self.svc.commit_robot_point_capture(
            "P45",
            pose=preview["captured"]["pose"],
            joint=preview["captured"]["joint"],
            confirm=True,
            note="manual-teach",
        )

        self.assertTrue(res["saved"])
        after_points = json.loads(self.points_file.read_text(encoding="utf-8"))
        after_meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        after_record = next(r for r in after_points if r["name"] == "P45")
        for key, value in before_record.items():
            if key not in {"pose", "joint"}:
                self.assertEqual(after_record[key], value)
        self.assertEqual(after_record["pose"], preview["captured"]["pose"])
        self.assertEqual(after_record["joint"], preview["captured"]["joint"])

        after_override = after_meta["overrides"]["P45"]
        for key, value in before_override.items():
            if key not in {"calibrated_at", "notes"}:
                self.assertEqual(after_override[key], value)
        self.assertEqual(after_override["notes"], "manual-teach")
        self.assertIn("calibrated_at", after_override)
        self.assertEqual(tuple(robot.registry.get("P45").pose), tuple(preview["captured"]["pose"]))

    def test_commit_requires_confirm_and_valid_vectors_without_writing(self) -> None:
        before_points = self.points_file.read_text(encoding="utf-8")
        before_meta = self.meta_file.read_text(encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.svc.commit_robot_point_capture(
                "P45", pose=[1, 2, 3, 4, 5, 6], joint=[1, 2, 3, 4, 5, 6], confirm=False)
        with self.assertRaises(ValueError):
            self.svc.commit_robot_point_capture(
                "P45", pose=[1, 2], joint=[1, 2, 3, 4, 5, 6], confirm=True)
        self.assertEqual(self.points_file.read_text(encoding="utf-8"), before_points)
        self.assertEqual(self.meta_file.read_text(encoding="utf-8"), before_meta)

    def test_derived_robot_point_cannot_be_directly_overwritten(self) -> None:
        before_points = self.points_file.read_text(encoding="utf-8")
        before_meta = self.meta_file.read_text(encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.svc.capture_robot_point("collect-bottle-pick.far")
        with self.assertRaises(PermissionError):
            self.svc.commit_robot_point_capture(
                "collect-bottle-pick.far",
                pose=[1, 2, 3, 4, 5, 6],
                joint=[1, 2, 3, 4, 5, 6],
                confirm=True,
            )
        self.assertEqual(self.points_file.read_text(encoding="utf-8"), before_points)
        self.assertEqual(self.meta_file.read_text(encoding="utf-8"), before_meta)


if __name__ == "__main__":
    unittest.main()
