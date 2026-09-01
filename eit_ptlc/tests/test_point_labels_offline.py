#!/usr/bin/env python3
"""机器人点位中文名与工位分组离线测试
====================================
功能:
    1. labels.yaml -> RobotPoint.label 的三条取名路径 (基点显式 / 派生点显式 / 派生点自动生成)
       与回退链 (未登记 -> 空串 -> 前端回退 alias); labels.yaml 缺失时不得报错。
    2. 点位树按语义工位分组: 历史几何区号 area-2..area-11 与 unknown 不得再出现,
       且分组顺序遵循 stations.yaml group_order 声明的流程走向。

背景: 树里原先"基点按 area-N 区号 + 派生点按工位"两套分类并存, 与设备/流程对不上;
      叶子直接显示英文 alias (Area_1_tool1_high)。见 config/points/robot/labels.yaml 头注释。
"""

from __future__ import annotations

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
from eit_ptlc.controller.points_service import PointsService  # noqa: E402

_CFG = _PKG / "config"

# 重新分组后机器人树应有的全部分组 (area-1 工具更换区 / area-5 待定区 保留原 key: 无对应流程工位)
_EXPECTED_GROUPS = {
    "feed-lift", "waste", "spotting", "tank", "scrape", "collect",
    "staging-a", "staging-b", "group-staging", "group-rack",
    "area-1", "area-5", "global", "vision", "calibration",
}


class RobotPointLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = load_config(_CFG / "app.yaml")
        self.reg = PointRegistry.load(
            self.cfg.robot.points_file, source_version=self.cfg.robot.point_source_version,
            meta_path=self.cfg.robot.points_meta_file)

    # ---- 取名: 三条路径 ----

    def test_base_point_label_from_yaml(self) -> None:
        self.assertEqual(self.reg.get("P8").label, "1号工具位·吸盘")
        self.assertEqual(self.reg.get("P21").label, "升降上料取料位")

    def test_grid_slot_label_from_yaml(self) -> None:
        """网格库位 (P25-P36 仿射解算) 也按 robot_name 取名。"""
        self.assertEqual(self.reg.get("P25").label, "收集器组1号位")
        self.assertEqual(self.reg.get("P31").label, "收集瓶组1号位")

    def test_derived_label_auto_from_base_plus_suffix(self) -> None:
        """未显式登记的派生点 = 基点中文名 + point_id 末段后缀。"""
        self.assertEqual(self.reg.get("tank.3.approach_far").label, "3号展开缸·远接近")
        self.assertEqual(self.reg.get("tank.3.approach_mid").label, "3号展开缸·中接近")
        self.assertEqual(self.reg.get("staging-a.p46.high").label, "中转A收集器1号位·高位接近")
        self.assertEqual(self.reg.get("scrape-holder-put.x-plus").label, "刮板收集器放置位·+X靠拢")
        self.assertEqual(self.reg.get("scrape-holder-pick.retreat-1").label, "刮板收集器取出过渡点·退离2")

    def test_derived_label_explicit_beats_auto(self) -> None:
        """put/pick 共用同一基点 (P19/P65) 时自动生成会撞名, 由 derived 显式条目区分。"""
        self.assertEqual(self.reg.get("spotting.put.approach_far").label, "点样放板·远接近")
        self.assertEqual(self.reg.get("spotting.pick.approach_far").label, "点样取板·远接近")
        self.assertEqual(self.reg.get("scrape.plate-put.retreat_near").label, "刮板台放板·近退离")
        self.assertEqual(self.reg.get("scrape.plate-pick.retreat_near").label, "刮板台取板·近退离")

    def test_every_point_named_and_unique(self) -> None:
        """全部 239 点都有中文名, 且互不撞名 (撞名会让树里出现两个同名条目)。"""
        labels = [p.label for p in self.reg.points]
        self.assertEqual([p.robot_name for p in self.reg.points if not p.label], [])
        self.assertEqual(len(labels), len(set(labels)))

    # ---- 回退链 ----

    def test_missing_labels_file_degrades_to_empty(self) -> None:
        """labels.yaml 不存在时不得报错, 全部 label 为空 (前端回退英文 alias)。"""
        tmp = Path(tempfile.mkdtemp(prefix="ptlabels_"))
        try:
            points = tmp / "robot_points.json"
            meta = tmp / "robot_points_meta.json"
            shutil.copy(self.cfg.robot.points_file, points)
            shutil.copy(self.cfg.robot.points_meta_file, meta)   # 刻意不复制 labels.yaml
            reg = PointRegistry.load(
                points, source_version=self.cfg.robot.point_source_version, meta_path=meta)
            self.assertEqual(len(reg.points), len(self.reg.points))
            self.assertEqual({p.label for p in reg.points}, {""})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_derive_label_fallback_chain(self) -> None:
        derive = PointRegistry._derive_label
        self.assertEqual(derive("", "tank.1.approach_far", "approach_far"), "")      # 基点无名 -> 空
        self.assertEqual(derive("基点", "x.y.approach_far", "approach_far"), "基点·远接近")  # 末段命中
        self.assertEqual(derive("基点", "x.y.zzz", "settle"), "基点·靠拢")           # 末段未命中 -> role 兜底
        self.assertEqual(derive("基点", "x.y.zzz", "target"), "")                    # 两者都未命中 -> 空
        self.assertEqual(derive("基点", "x.y.zzz", "target", {"zzz": "·自定义"}), "基点·自定义")  # suffixes 覆盖


class RobotPointGroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        cfg = load_config(_CFG / "app.yaml")
        reg = PointRegistry.load(
            cfg.robot.points_file, source_version=cfg.robot.point_source_version,
            meta_path=cfg.robot.points_meta_file)
        self.svc = PointsService(_CFG / "points", reg)

    def test_groups_are_semantic_workstations(self) -> None:
        groups = {g["key"] for g in self.svc.tree()["robot"]["groups"]}
        self.assertEqual(groups, _EXPECTED_GROUPS)
        self.assertFalse([k for k in groups if k.startswith("area-") and k not in ("area-1", "area-5")],
                         "历史几何区号分组不应再出现在树里")
        self.assertNotIn("unknown", groups)

    def test_every_group_has_chinese_label(self) -> None:
        for g in self.svc.tree()["robot"]["groups"]:
            self.assertNotEqual(g["label"], g["key"], f"工位 {g['key']} 缺 stations.yaml labels 条目")

    def test_group_order_follows_stations_yaml(self) -> None:
        """分组顺序 = group_order 声明的流程走向 (原实现按 key 字符串序: area-1, area-10, area-11, area-2…)。"""
        order = self.svc._catalog.station_order
        self.assertTrue(order, "stations.yaml 应声明 group_order")
        for category in ("robot", "plc_servo"):
            keys = [g["key"] for g in self.svc.tree()[category]["groups"]]
            listed = [k for k in keys if k in order]
            self.assertEqual(listed, [k for k in order if k in keys], f"{category} 分组顺序未按 group_order")

    def test_dto_carries_label(self) -> None:
        self.assertEqual(self.svc.get("robot", "P8")["label"], "1号工具位·吸盘")
        self.assertEqual(self.svc.get("robot", "tank.1.approach_far")["label"], "1号展开缸·远接近")


if __name__ == "__main__":
    unittest.main()
