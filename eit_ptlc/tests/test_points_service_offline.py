#!/usr/bin/env python3
"""统一点位目录服务离线测试
==========================
功能:
    校验 PointsService 从 config/points/ 目录加载 (stations.yaml + plc/<工位>.yaml) +
    聚合机器人点表(含派生点), 产出按 category -> workstation 分组的可读树, 并按 id/robot_name 查单点。
"""

from __future__ import annotations

import asyncio
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

_CFG = _PKG / "config"


class PointsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        cfg = load_config(_CFG / "app.yaml")
        reg = PointRegistry.load(
            cfg.robot.points_file, source_version=cfg.robot.point_source_version,
            meta_path=cfg.robot.points_meta_file)
        self.svc = PointsService(_CFG / "points", reg)

    def _flatten(self, category: str) -> list[dict]:
        return [p for g in self.svc.tree()[category]["groups"] for p in g["points"]]

    def test_tree_has_all_categories(self) -> None:
        # 顶层 2 个设备类: 目标点 (plc_servo_target) 并入 plc_servo 枝; CNC 已移出 (归设备参数页)
        tree = self.svc.tree()
        self.assertEqual(set(tree), {"robot", "plc_servo"})

    def test_robot_aggregates_all_points_with_derived(self) -> None:
        robot = self._flatten("robot")
        self.assertEqual(len(robot), 239)
        ids = {p["id"] for p in robot}
        self.assertIn("collect-bottle-pick.far", ids)   # 派生点
        self.assertTrue(any(p["is_derived"] for p in robot))

    def test_plc_servo_grouped_by_workstation(self) -> None:
        # 路径 T: plc_servo 枝 = 7 个 struct 召回位 (plc_servo) + 10 个 flat 目标点 + 1 个组合点位
        #   7 召回 = 地轨 6 + 点样7Y 放板位 (spot_7y_place, 值在 HMI 槽、PLC 无 flat 节点, 只读)
        #   10 目标 = photo_8y + sampling 5 (含 5Z 两档) + feedlift 搜索边界 4
        #   1 组合 = 点样位置 (spot_pose, 含 6X起/止/7Y)
        servo = self._flatten("plc_servo")
        self.assertEqual(len(servo), 18)
        rail = [p for p in servo if p["workstation"] == "rail"]
        self.assertEqual(len(rail), 6)  # 地轨 6 工位定位
        # 目标点 / 组合点位经各自 category 携带, 与召回 struct 点区分
        self.assertEqual(len([p for p in servo if p["category"] == "plc_servo_target"]), 10)
        self.assertEqual(len([p for p in servo if p["category"] == "plc_servo_composite"]), 1)

    def test_get_robot_by_id_and_robot_name(self) -> None:
        self.assertIsNotNone(self.svc.get("robot", "P70"))                    # by robot_name
        self.assertIsNotNone(self.svc.get("robot", "collect-bottle-pick.far"))  # by point_id
        self.assertIsNone(self.svc.get("robot", "不存在的点"))

    def test_get_servo(self) -> None:
        s = self.svc.get("plc_servo", "rail_p1_sampling")
        self.assertEqual(s["slot"], 1)
        self.assertEqual(s["limits"]["min"], 0.0)

    def test_catalog_rejects_bad_slot(self) -> None:
        # 临时点位目录: 合法 stations.yaml + 含越界 slot 的 plc 文件 -> 装配校验拒绝
        tmp = Path(tempfile.mkdtemp()) / "points"
        (tmp / "plc").mkdir(parents=True)
        (tmp / "stations.yaml").write_text(
            "version: 1\nplc_servo_container: {gvl_path: [A, B]}\nlabels: {}\n", encoding="utf-8")
        (tmp / "plc" / "bad.yaml").write_text(
            "plc_servo:\n  - {key: x, label: X, node: HMI_X, slot: 99, limits: {min: 0, max: 1}}\n",
            encoding="utf-8")
        try:
            with self.assertRaises(PointsCatalogError):
                PointsService.load_catalog(tmp)
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)


class _FakeDriver:
    """假 OPC 驱动: 只记录 write_variable (组合点位下发唯一用到的 driver 方法)。"""

    def __init__(self) -> None:
        self.writes: list[tuple[str, float]] = []

    async def write_variable(self, node: str, value) -> None:
        self.writes.append((node, float(value)))


class PushCompositeOverrideTests(unittest.TestCase):
    """点样组合点位 push 的运行前成员覆盖: 生效值下发、点表基准不被改、限位/未知键把关。"""

    def setUp(self) -> None:
        cfg = load_config(_CFG / "app.yaml")
        reg = PointRegistry.load(
            cfg.robot.points_file, source_version=cfg.robot.point_source_version,
            meta_path=cfg.robot.points_meta_file)
        self.drv = _FakeDriver()
        self.svc = PointsService(_CFG / "points", reg, driver=self.drv)

    def test_baseline_when_no_override(self) -> None:
        # 未覆盖 → 各成员写点表示教基准 (spot_pose: 70 / 240 / -20); overridden 全 False
        r = asyncio.run(self.svc.push_composite("spot_pose"))
        w = dict(self.drv.writes)
        self.assertAlmostEqual(w["Spot_6X_StartTarget"], 70.0)
        self.assertAlmostEqual(w["Spot_6X_EndTarget"], 240.0)
        self.assertAlmostEqual(w["Spot_7Y_Target"], -20.0)
        self.assertTrue(all(not x["overridden"] for x in r["written"]))

    def test_override_writes_effective_and_keeps_catalog(self) -> None:
        r = asyncio.run(self.svc.push_composite("spot_pose", {"x_start": 123.0}))
        w = dict(self.drv.writes)
        self.assertAlmostEqual(w["Spot_6X_StartTarget"], 123.0)      # 覆盖值下发
        self.assertAlmostEqual(w["Spot_6X_EndTarget"], 240.0)        # 未覆盖成员仍走基准
        # 点表 m.value 纹丝不动 (临时覆盖永不回写; teach 仍是唯一写者)
        m = next(x for x in self.svc.composite_entry("spot_pose").members if x.key == "x_start")
        self.assertAlmostEqual(m.value, 70.0)
        self.assertTrue(next(x for x in r["written"] if x["member"] == "x_start")["overridden"])

    def test_unknown_member_rejected(self) -> None:
        with self.assertRaises(PointsCatalogError):
            asyncio.run(self.svc.push_composite("spot_pose", {"nope": 1.0}))

    def test_overlimit_override_rejected_no_partial_write(self) -> None:
        # 生效值越限 (9999 > max 500) → 整体不下发 (校验在写之前, 无部分写)
        with self.assertRaises(ValueError):
            asyncio.run(self.svc.push_composite("spot_pose", {"x_start": 9999.0}))
        self.assertEqual(self.drv.writes, [])

    def test_push_point_ref_plain_target_rejects_overrides(self) -> None:
        # 普通目标点无成员, 误带成员覆盖即报错 (只有组合点位/点样才有可覆盖几何成员)
        with self.assertRaises(PointsCatalogError):
            asyncio.run(self.svc.push_point_ref("photo_8y", {"x_start": 1.0}))

    def test_push_point_ref_composite_forwards_overrides(self) -> None:
        asyncio.run(self.svc.push_point_ref("spot_pose", {"y_height": -15.0}))
        w = dict(self.drv.writes)
        self.assertAlmostEqual(w["Spot_7Y_Target"], -15.0)
        self.assertAlmostEqual(w["Spot_6X_StartTarget"], 70.0)


if __name__ == "__main__":
    unittest.main()
