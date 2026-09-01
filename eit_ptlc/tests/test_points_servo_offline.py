#!/usr/bin/env python3
"""PLC 伺服点位 (plc_servo) 只读配置展示 离线测试
==================================================
B 方案 / 路径 T: 连续伺服轴已迁 plc_servo_target flat 逐点示教; plc_servo 仅余地轨「离散召回位」
(真值在 PLC position[1..6], HMI 面板维护, 上位机经 rail.move 召回)。故 plc_servo 在点位页仅作
只读配置展示 (槽位/限位/角色语义), 不提供 OPC 实时读写。本测试校验:
  1. plc_servo 解析: 仅地轨 6 工位 (连续轴已不在 struct 分支); 槽位/限位/角色/工位字段透传;
  2. dto 形状: 不含 live 字段 (无实时值来源);
  3. within_limits 限位语义仍可用 (供配置展示/写前钳制复用);
  4. 已无 read_servo_live / set_servo_position OPC 读写方法 (B 方案移除)。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402
from eit_ptlc.controller.points_service import PointsService  # noqa: E402

_CFG = _PKG / "config"


class ServoConfigTests(unittest.TestCase):
    def setUp(self):
        cfg = load_config(_CFG / "app.yaml")
        reg = PointRegistry.load(
            cfg.robot.points_file, source_version=cfg.robot.point_source_version,
            meta_path=cfg.robot.points_meta_file)
        self.svc = PointsService(_CFG / "points", reg)

    def test_parse_plc_servo_points(self):
        servo = self.svc.list_plc_servo()
        by_id = {s["id"]: s for s in servo}
        # 路径 T: plc_servo = 地轨 6 召回位 + 点样7Y 放板位 (上样/点样/拍照的**连续轴**已迁
        # plc_servo_target; 但放板位的值仍在 HMI_点样轴7Y.position[1], PLC 侧没有对应的 flat
        # 节点, 故仍以 struct 槽位点表达 —— 2026-08-05 经 OPC 实读收进点表, 只读不下发)
        self.assertEqual(len(servo), 7)
        rail = [s for s in servo if s["workstation"] == "rail"]
        self.assertEqual(len(rail), 6)  # 地轨 6 工位定位
        self.assertEqual({s["workstation"] for s in servo}, {"rail", "spotting"})
        self.assertEqual(by_id["spot_7y_place"]["node"], "HMI_点样轴7Y")
        self.assertEqual(by_id["spot_7y_place"]["slot"], 1)
        p1 = by_id["rail_p1_sampling"]
        self.assertEqual(p1["node"], "HMI_地轨轴11Y")
        self.assertEqual(p1["slot"], 1)
        self.assertEqual((p1["limits"]["min"], p1["limits"]["max"]), (0.0, 3000.0))

    def test_servo_dto_has_no_live_field(self):
        # B 方案无 OPC 实时值来源, dto 不再承载 live (只读配置展示)
        for s in self.svc.list_plc_servo():
            self.assertNotIn("live", s)

    def test_within_limits_semantics(self):
        entry = self.svc.servo_entry("rail_p1_sampling")
        self.assertTrue(entry.within_limits(100.0))
        self.assertFalse(entry.within_limits(99999.0))

    def test_opc_read_write_methods_removed(self):
        # B 方案下 plc_servo 不再有 OPC 实时读写方法 (示教走 plc_servo_target flat 流程)
        self.assertFalse(hasattr(self.svc, "read_servo_live"))
        self.assertFalse(hasattr(self.svc, "set_servo_position"))


if __name__ == "__main__":
    unittest.main()
