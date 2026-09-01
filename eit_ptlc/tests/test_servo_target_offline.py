#!/usr/bin/env python3
"""PC 侧 flat 目标点位 (B 方案单写者) 离线测试
================================================
覆盖议题② 落地链路 (不依赖真机 / OPC):
  1. points.yaml plc_servo_target 解析 + 树分类 + 单点查询;
  2. set_target_value: 限位校验 + ruamel round-trip 保留注释 + reload;
  3. push_target: 把存储 value 写到 PLC *_Target flat 节点 (fake driver 记录);
  4. servo_target 动作经 ActionExecutor 调度 → 顺序下发各 target → DONE。
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

from eit_ptlc.action.executor import ActionExecutor  # noqa: E402
from eit_ptlc.action.models import ActionStatus  # noqa: E402
from eit_ptlc.action.registry import ActionDef, ActionParam, ActionRegistry  # noqa: E402
from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402
from eit_ptlc.controller.points_service import PointsCatalogError, PointsService  # noqa: E402
from eit_ptlc.config.loader import load_config  # noqa: E402

_CFG = _PKG / "config"


class _FakeDriver:
    """记录 flat 节点写入 (write_variable) 与读出 (read_variable)。"""

    def __init__(self, reads=None) -> None:
        self.writes: list[tuple[str, float]] = []
        self._reads = reads or {}

    async def write_variable(self, node, value):
        self.writes.append((node, float(value)))

    async def read_many(self, names):
        """批量读 (替身实现: 逐点转 read_variable, 完整保留本替身模拟的语义)."""
        return [await self.read_variable(n) for n in names]

    async def read_variable(self, node):
        return self._reads.get(node, 0.0)

    async def write_block_confirmed(self, fields: dict, *, atol: float = 1e-3, attempts: int = 2):
        for node, value in fields.items():
            await self.write_variable(node, value)
        return {node: {"ok": True, "attempts": 1} for node in fields}


class _FakePlc:
    """记录 L2 execute 调用 (station, action_code, params), 恒返回 DONE 终态。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(self, station, action_code, params, *, timeout=None, stall_timeout=None):
        from eit_ptlc.controller.plc_controller import (
            PLCActionResult, PLCActionSafeState, PLCActionState,
        )
        self.calls.append((station, int(action_code), dict(params)))
        return PLCActionResult(station=station, action_code=int(action_code), request_seq=1,
                               state=PLCActionState.DONE, error_code=0,
                               safe_state=PLCActionSafeState.READY, retryable=False, step=0)


def _svc(points_dir, driver=None) -> PointsService:
    cfg = load_config(_CFG / "app.yaml")
    reg = PointRegistry.load(cfg.robot.points_file, source_version=cfg.robot.point_source_version,
                             meta_path=cfg.robot.points_meta_file)
    return PointsService(points_dir, reg, driver=driver)


class ServoTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        # 用工程真实 config/points/ 目录的副本, 避免污染源文件
        self._dir = Path(tempfile.mkdtemp()) / "points"
        shutil.copytree(_CFG / "points", self._dir)
        self._spotting = self._dir / "plc" / "spotting.yaml"  # spot_7y 等点样目标所在文件

    def test_parse_tree_and_get(self) -> None:
        svc = _svc(self._dir)
        # 目标点已并入 plc_servo 枝展示, 按各点自身 category 过滤取出
        targets = {t["id"]: t for g in svc.tree()["plc_servo"]["groups"] for t in g["points"]
                   if t["category"] == "plc_servo_target"}
        # 点样 6X(起/止)/7Y 已合并为组合点位 spot_pose, 不再是独立 target
        # sample_5z / sample_5z_dip = 5Z 的两档 (HMI slot 1/2); 两者的 PLC flat 节点都待建,
        # 故都仍标 pending, 但 value 是 2026-08-05 从在线 PLC 实读的 45.0 / 46.5
        self.assertEqual(set(targets), {"photo_8y", "sampling_4x", "sampling_3y",
                                        "sample_5z", "sample_5z_dip", "sampling_4x_wash",
                                        "feedlift_1z_search_low", "feedlift_1z_search_high",
                                        "feedlift_2z_search_low", "feedlift_2z_search_high"})
        # 4X 清洗位: 4X 轴上的固定离散工位 → 独立离散示教点 (非 limit_source; 节点已下载 0624, pending 已清)
        self.assertEqual(targets["sampling_4x_wash"]["node"], "Sampling_4X_WashTarget")
        self.assertEqual(targets["sampling_4x_wash"]["actpos"], "Sampling_4X_ActPos")
        self.assertEqual(targets["sampling_4x_wash"]["hmi_slot"], 9)
        self.assertFalse(targets["sampling_4x_wash"]["limit_source"])
        self.assertFalse(targets["sampling_4x_wash"]["pending"])
        self.assertEqual(targets["photo_8y"]["node"], "Photo_8Y_Target")
        self.assertEqual(targets["photo_8y"]["actpos"], "Photo_8Y_ActPos")
        self.assertEqual(targets["photo_8y"]["value"], 420.0)
        # 组合点位 spot_pose: 树中以单条出现 (category=plc_servo_composite), 含三个子坐标成员
        comps = {c["id"]: c for g in svc.tree()["plc_servo"]["groups"] for c in g["points"]
                 if c["category"] == "plc_servo_composite"}
        self.assertEqual(set(comps), {"spot_pose"})
        cd = svc.get("plc_servo_composite", "spot_pose")
        self.assertEqual(cd["category"], "plc_servo_composite")
        self.assertEqual([m["key"] for m in cd["members"]], ["x_start", "x_end", "y_height"])
        self.assertEqual([m["node"] for m in cd["members"]],
                         ["Spot_6X_StartTarget", "Spot_6X_EndTarget", "Spot_7Y_Target"])
        self.assertEqual([m["actpos"] for m in cd["members"]],
                         ["Spot_6X_ActPos", "Spot_6X_ActPos", "Spot_7Y_ActPos"])
        # 路径 T: 连续轴 struct 已退役; 召回位 (rail) 为 plc_servo, 各按 category 路由
        self.assertEqual(svc.get("plc_servo", "rail_p1_sampling")["category"], "plc_servo")
        self.assertIsNone(svc.get("plc_servo", "spot_7y"))            # 连续轴已无 struct 条目
        self.assertIsNone(svc.get("plc_servo_target", "spot_7y"))     # 已并入组合点位, 非独立 target

    def test_set_composite_member_value_roundtrip_preserves_comments(self) -> None:
        svc = _svc(self._dir)
        out = svc.set_composite_member_value("spot_pose", "y_height", 12.5)
        self.assertEqual(out["value"], 12.5)
        self.assertEqual(out["node"], "Spot_7Y_Target")
        # reload 后内存值已更新
        ym = next(m for m in svc.composite_entry("spot_pose").members if m.key == "y_height")
        self.assertEqual(ym.value, 12.5)
        # 重新加载该工位文件确认已持久化, 且注释未被 dump 抹掉
        text = self._spotting.read_text(encoding="utf-8")
        self.assertIn("value: 12.5", text)
        self.assertIn("flat 节点不 retain", text)   # 注释保留 (ruamel round-trip)
        comps = {c.key: c for c in PointsService.load_catalog(self._dir).composites}
        ym2 = next(m for m in comps["spot_pose"].members if m.key == "y_height")
        self.assertEqual(ym2.value, 12.5)

    def test_set_value_rejects_out_of_limit_and_unknown(self) -> None:
        svc = _svc(self._dir)
        # 普通目标点 (photo_8y): 越限拒绝
        with self.assertRaises(ValueError):
            svc.set_target_value("photo_8y", 9999.0)
        with self.assertRaises(PointsCatalogError):
            svc.set_target_value("不存在", 1.0)
        # 组合点位成员: 越限拒绝; 未知组合/成员抛 PointsCatalogError
        with self.assertRaises(ValueError):
            svc.set_composite_member_value("spot_pose", "y_height", 9999.0)
        with self.assertRaises(PointsCatalogError):
            svc.set_composite_member_value("spot_pose", "不存在", 1.0)
        with self.assertRaises(PointsCatalogError):
            svc.set_composite_member_value("不存在", "y_height", 1.0)

    def test_limit_source_is_read_only(self) -> None:
        # 限位源点位 (上样仿射轴): value 仅作软限位, 禁止手动存值/下发
        drv = _FakeDriver()
        svc = _svc(self._dir, driver=drv)
        self.assertTrue(svc.target_entry("sampling_4x").limit_source)
        self.assertFalse(svc.target_entry("photo_8y").limit_source)
        with self.assertRaises(ValueError):
            svc.set_target_value("sampling_4x", 10.0)
        with self.assertRaises(ValueError):
            asyncio.run(svc.push_target("sampling_3y"))
        self.assertEqual(drv.writes, [])  # 护栏拦在写 PLC 之前

    def test_push_target_writes_flat_node(self) -> None:
        drv = _FakeDriver()
        svc = _svc(self._dir, driver=drv)
        out = asyncio.run(svc.push_target("photo_8y"))
        self.assertEqual(out, {"key": "photo_8y", "node": "Photo_8Y_Target", "written": 420.0})
        self.assertEqual(drv.writes, [("Photo_8Y_Target", 420.0)])

    def test_push_targets_confirmed_writes_block(self) -> None:
        drv = _FakeDriver()
        svc = _svc(self._dir, driver=drv)
        svc.set_target_value("feedlift_1z_search_low", -10.0)
        svc.set_target_value("feedlift_1z_search_high", 20.0)
        out = asyncio.run(svc.push_targets_confirmed(
            ("feedlift_1z_search_low", "feedlift_1z_search_high")
        ))
        self.assertEqual(drv.writes, [
            ("FeedLift_1Z_SearchLowTarget", -10.0),
            ("FeedLift_1Z_SearchHighTarget", 20.0),
        ])
        self.assertEqual([row["key"] for row in out["written"]],
                         ["feedlift_1z_search_low", "feedlift_1z_search_high"])
        self.assertTrue(out["confirm"]["FeedLift_1Z_SearchLowTarget"]["ok"])

    def test_read_actpos(self) -> None:
        drv = _FakeDriver(reads={"Spot_7Y_ActPos": 33.3, "Photo_8Y_ActPos": 7.7})
        svc = _svc(self._dir, driver=drv)
        # 普通目标点
        self.assertAlmostEqual(asyncio.run(svc.read_target_actpos("photo_8y")), 7.7)
        # 组合点位成员 (y_height 读 Spot_7Y_ActPos)
        self.assertAlmostEqual(
            asyncio.run(svc.read_composite_member_actpos("spot_pose", "y_height")), 33.3)

    def test_pending_target_store_ok_but_read_push_blocked(self) -> None:
        # 路径 T / 5Z: PLC flat 节点待建 (pending) → 可离线存值 (PC 真源), 但读实际位/下发被拦
        drv = _FakeDriver(reads={"Sampling_5Z_ActPos": 12.0})
        svc = _svc(self._dir, driver=drv)
        self.assertTrue(svc.target_entry("sample_5z").pending)
        # 存值可行 (限位内) — 离线预示教
        out = svc.set_target_value("sample_5z", 33.0)
        self.assertEqual(out["value"], 33.0)
        self.assertEqual(svc.target_entry("sample_5z").value, 33.0)
        # 读实际位被拦 (PointsCatalogError), 不触 driver
        with self.assertRaises(PointsCatalogError):
            asyncio.run(svc.read_target_actpos("sample_5z"))
        # 下发被拦 (ValueError), 不写 PLC
        with self.assertRaises(ValueError):
            asyncio.run(svc.push_target("sample_5z"))
        self.assertEqual(drv.writes, [])

    def test_executor_servo_target_dispatch(self) -> None:
        drv = _FakeDriver()
        svc = _svc(self._dir, driver=drv)
        # servo_target 原子按 targets 顺序把各点位存储值下发, 校验顺序与节点
        svc.set_target_value("photo_8y", 1.0)
        svc.set_target_value("sampling_4x_wash", 2.0)
        adef = ActionDef(name="x.push_targets", kind="servo_target",
                         targets=("photo_8y", "sampling_4x_wash"))
        ex = ActionExecutor(ActionRegistry({adef.name: adef}), points=svc)
        r = asyncio.run(ex.execute("x.push_targets"))
        self.assertEqual(r.status, ActionStatus.DONE)
        self.assertEqual(drv.writes,
                         [("Photo_8Y_Target", 1.0), ("Sampling_4X_WashTarget", 2.0)])

    def test_executor_servo_target_without_points_service(self) -> None:
        adef = ActionDef(name="x.push", kind="servo_target", targets=("photo_8y",))
        ex = ActionExecutor(ActionRegistry({adef.name: adef}))  # points=None
        r = asyncio.run(ex.execute("x.push"))
        self.assertEqual(r.status, ActionStatus.REJECTED)

    def test_plc_l2_preload_targets_confirmed_before_trigger(self) -> None:
        drv = _FakeDriver()
        svc = _svc(self._dir, driver=drv)
        svc.set_target_value("feedlift_1z_search_low", -10.0)
        svc.set_target_value("feedlift_1z_search_high", 20.0)
        plc = _FakePlc()
        adef = ActionDef(name="feedlift.feed_raise", kind="plc_l2", station="feedlift",
                         action_code=11,
                         preload_targets=("feedlift_1z_search_low", "feedlift_1z_search_high"))
        ex = ActionExecutor(ActionRegistry({adef.name: adef}), plc=plc, points=svc)
        r = asyncio.run(ex.execute("feedlift.feed_raise"))
        self.assertEqual(r.status, ActionStatus.DONE)
        self.assertEqual(drv.writes, [
            ("FeedLift_1Z_SearchLowTarget", -10.0),
            ("FeedLift_1Z_SearchHighTarget", 20.0),
        ])
        self.assertEqual(plc.calls, [("feedlift", 11, {})])
        self.assertEqual([row["key"] for row in r.result["preload_targets"]["written"]],
                         ["feedlift_1z_search_low", "feedlift_1z_search_high"])

    def test_plc_l2_preload_targets_without_points_rejects_before_trigger(self) -> None:
        plc = _FakePlc()
        adef = ActionDef(name="feedlift.feed_raise", kind="plc_l2", station="feedlift",
                         action_code=11,
                         preload_targets=("feedlift_1z_search_low", "feedlift_1z_search_high"))
        ex = ActionExecutor(ActionRegistry({adef.name: adef}), plc=plc)  # points=None
        r = asyncio.run(ex.execute("feedlift.feed_raise"))
        self.assertEqual(r.status, ActionStatus.REJECTED)
        self.assertEqual(plc.calls, [])

    def test_plc_l2_point_ref_pushes_then_triggers(self) -> None:
        # plc_l2 动作的 point_ref 参数 (组合点位) 在触发前展开为各成员下发 *_Target, 再触发 L2
        drv = _FakeDriver()
        svc = _svc(self._dir, driver=drv)
        svc.set_composite_member_value("spot_pose", "x_start", 1.0)
        svc.set_composite_member_value("spot_pose", "x_end", 2.0)
        svc.set_composite_member_value("spot_pose", "y_height", 3.0)
        plc = _FakePlc()
        # 用中性名 (非 PUMP_PROFILES 注册名) 隔离点位引用机制, 不掺泵参数翻译
        adef = ActionDef(name="t.spot_l2", kind="plc_l2", station="sampling", action_code=60,
                         params=(ActionParam(name="ref_spot", type="point_ref", required=True),))
        ex = ActionExecutor(ActionRegistry({adef.name: adef}), plc=plc, points=svc)
        r = asyncio.run(ex.execute("t.spot_l2", {"ref_spot": "spot_pose"}))
        self.assertEqual(r.status, ActionStatus.DONE)
        # 触发前已按成员序把 3 个子坐标值写到各自 *_Target 节点
        self.assertEqual(drv.writes, [("Spot_6X_StartTarget", 1.0), ("Spot_6X_EndTarget", 2.0),
                                      ("Spot_7Y_Target", 3.0)])
        # L2 被触发一次, 且引用键未作为 PLC 通道下发 (已从 channels 弹出)
        self.assertEqual(len(plc.calls), 1)
        station, code, params = plc.calls[0]
        self.assertEqual((station, code), ("sampling", 60))
        self.assertNotIn("ref_spot", params)

    def test_plc_l2_point_ref_without_points_rejects_before_trigger(self) -> None:
        plc = _FakePlc()
        adef = ActionDef(name="t.spot_l2", kind="plc_l2", station="sampling", action_code=60,
                         params=(ActionParam(name="ref_spot", type="point_ref", required=True),))
        ex = ActionExecutor(ActionRegistry({adef.name: adef}), plc=plc)  # points=None
        r = asyncio.run(ex.execute("t.spot_l2", {"ref_spot": "spot_pose"}))
        self.assertEqual(r.status, ActionStatus.REJECTED)
        self.assertEqual(plc.calls, [])      # 点位服务未就绪 → 不触发

    def test_plc_l2_point_ref_rejects_limit_source_before_trigger(self) -> None:
        drv = _FakeDriver()
        svc = _svc(self._dir, driver=drv)
        plc = _FakePlc()
        adef = ActionDef(name="t.spot_l2", kind="plc_l2", station="sampling", action_code=60,
                         params=(ActionParam(name="ref_x", type="point_ref", required=True),))
        ex = ActionExecutor(ActionRegistry({adef.name: adef}), plc=plc, points=svc)
        r = asyncio.run(ex.execute("t.spot_l2", {"ref_x": "sampling_4x"}))  # 限位源点位不可下发
        self.assertEqual(r.status, ActionStatus.REJECTED)
        self.assertEqual(plc.calls, [])      # 下发被拒 → 不触发
        self.assertEqual(drv.writes, [])


if __name__ == "__main__":
    unittest.main()
