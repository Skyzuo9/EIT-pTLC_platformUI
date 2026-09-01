#!/usr/bin/env python3
"""地轨双源同步 (push/pull/diff) 离线测试
==========================================
覆盖地轨 11Y 收编的 PC 侧链路 (不依赖真机 / OPC; fake driver 模拟 Rail_Sync POU):
  1. 解析: rail.yaml sync 块 + plc_servo 点的 PC 真源 value; DTO 暴露 value/sync;
  2. set_servo_value: 限位校验 + ruamel round-trip 保留注释 + reload;
  3. diff_sync: PC 真源 ↔ HMI flat 镜像逐点偏差 + 阈值 over 判定 (只读);
  4. push_sync: 按 slot 写 target 数组 + 触发邮箱 → POU 拷进镜像, Ack/Req 握手;
  5. pull_sync: confirm=False 仅预览不落盘; confirm=True 持久化 + 重算 target; 越限拒绝置 Ack=REJECT。

契约见 docs/PLC交付_地轨双源同步_Rail_Sync_可复制粘贴_20260623.md。
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
    SYNC_ACK_DONE,
    SYNC_ACK_REJECT,
    SYNC_REQ_IDLE,
    SYNC_REQ_PUSH,
    PointsCatalogError,
    PointsService,
)

_CFG = _PKG / "config"


class _SyncFakeDriver:
    """模拟 Rail_Sync POU: 持有 flat 节点状态; write_many 时若 Req=PUSH 即执行 POU 拷贝 (Target->镜像)。"""

    def __init__(self, state: dict | None = None) -> None:
        self.state: dict = dict(state or {})
        self.write_log: list[tuple[str, object]] = []

    async def read_many(self, names):
        """批量读 (替身实现: 逐点转 read_variable, 完整保留本替身模拟的语义)."""
        return [await self.read_variable(n) for n in names]

    async def read_variable(self, node):
        v = self.state.get(node)
        return list(v) if isinstance(v, list) else v

    async def write_variable(self, node, value):
        self.state[node] = value
        self.write_log.append((node, value))
        self._run_pou()

    async def write_many(self, params: dict):
        for k, v in params.items():
            self.state[k] = list(v) if isinstance(v, (list, tuple)) else v
            self.write_log.append((k, self.state[k]))
        self._run_pou()

    async def write_block_confirmed(self, fields: dict, *, atol: float = 1e-6, attempts: int = 2):
        # 模拟 driver 写-回读确认原语: fake 无丢包, 存值即等于回读, 平凡确认通过。
        await self.write_many(fields)
        return {k: {"ok": True, "attempts": 1} for k in fields}

    def _run_pou(self) -> None:
        # PUSH: Target -> position[] (镜像随之); Ack=完成, Req=空闲 (PLC 独立完成)
        if self.state.get("Rail_Sync_Req") == SYNC_REQ_PUSH:
            tgt = self.state.get("Rail_Pos_Target")
            if isinstance(tgt, list):
                self.state["Rail_Pos_HMI"] = list(tgt)
            self.state["Rail_Sync_Ack"] = SYNC_ACK_DONE
            self.state["Rail_Sync_Req"] = SYNC_REQ_IDLE


def _svc(points_dir, driver=None) -> PointsService:
    cfg = load_config(_CFG / "app.yaml")
    reg = PointRegistry.load(cfg.robot.points_file, source_version=cfg.robot.point_source_version,
                             meta_path=cfg.robot.points_meta_file)
    return PointsService(points_dir, reg, driver=driver)


class RailSyncTests(unittest.TestCase):
    # rail.yaml 真源现携带真机站点坐标; 各用例以 0.0 为已知起点, 故复制后在副本里归零 (与磁盘真值解耦)。
    _RAIL_KEYS = ("rail_p1_sampling", "rail_p2_photo", "rail_p3_collect",
                  "rail_p4_tool", "rail_p5_expand", "rail_p6_store")

    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp()) / "points"
        shutil.copytree(_CFG / "points", self._dir)
        self._rail = self._dir / "plc" / "rail.yaml"
        svc = _svc(self._dir)
        for k in self._RAIL_KEYS:
            svc.set_servo_value(k, 0.0)

    def test_parse_sync_group_and_dto(self) -> None:
        svc = _svc(self._dir)
        g = svc.sync_group("rail")
        self.assertIsNotNone(g)
        self.assertEqual(g.target_node, "Rail_Pos_Target")
        self.assertEqual(g.hmi_mirror_node, "Rail_Pos_HMI")
        self.assertEqual(g.array_len, 6)
        # 非收编工位无 sync
        self.assertIsNone(svc.sync_group("spotting"))
        # DTO 暴露 value + sync 标志
        dto = svc.get("plc_servo", "rail_p2_photo")
        self.assertEqual(dto["value"], 0.0)
        self.assertTrue(dto["sync"])
        self.assertEqual(dto["slot"], 2)

    def test_set_servo_value_roundtrip_and_limits(self) -> None:
        svc = _svc(self._dir)
        out = svc.set_servo_value("rail_p3_collect", 1234.5)
        self.assertEqual(out["value"], 1234.5)
        self.assertEqual(svc.servo_entry("rail_p3_collect").value, 1234.5)
        text = self._rail.read_text(encoding="utf-8")
        self.assertIn("value: 1234.5", text)
        self.assertIn("离散召回位", text)   # 注释保留
        with self.assertRaises(ValueError):
            svc.set_servo_value("rail_p3_collect", 9999.0)   # 越限
        with self.assertRaises(PointsCatalogError):
            svc.set_servo_value("不存在", 1.0)

    def test_diff_sync(self) -> None:
        # PC 真源: p1=100, p2=200; HMI 镜像: p1=100.2(在阈内), p2=205(超阈)
        svc = _svc(self._dir)
        svc.set_servo_value("rail_p1_sampling", 100.0)
        svc.set_servo_value("rail_p2_photo", 200.0)
        drv = _SyncFakeDriver({"Rail_Pos_HMI": [100.2, 205.0, 0.0, 0.0, 0.0, 0.0]})
        svc = _svc(self._dir, driver=drv)
        out = asyncio.run(svc.diff_sync("rail", threshold=0.5))
        self.assertTrue(out["any_over"])
        rows = {r["key"]: r for r in out["points"]}
        self.assertAlmostEqual(rows["rail_p1_sampling"]["delta"], 0.2)
        self.assertFalse(rows["rail_p1_sampling"]["over"])
        self.assertAlmostEqual(rows["rail_p2_photo"]["delta"], 5.0)
        self.assertTrue(rows["rail_p2_photo"]["over"])

    def test_push_sync_writes_target_array_by_slot(self) -> None:
        svc = _svc(self._dir)
        svc.set_servo_value("rail_p1_sampling", 10.0)
        svc.set_servo_value("rail_p6_store", 60.0)
        drv = _SyncFakeDriver()
        svc = _svc(self._dir, driver=drv)
        out = asyncio.run(svc.push_sync("rail"))
        self.assertEqual(drv.state["Rail_Pos_Target"], [10.0, 0.0, 0.0, 0.0, 0.0, 60.0])
        self.assertTrue(out["mirror_synced"])
        self.assertEqual(out["ack"], SYNC_ACK_DONE)
        # POU 已把 target 拷进 HMI 镜像 → 随后 diff 应为 0
        diff = asyncio.run(svc.diff_sync("rail"))
        self.assertFalse(diff["any_over"])

    def test_ensure_target_confirmed_writes_only_target(self) -> None:
        # 即时重建原语 (地轨 L2 移动前调用): 写真源数组 + 回读确认, 不碰邮箱 (Req/Ack 不动)。
        svc = _svc(self._dir)
        svc.set_servo_value("rail_p3_collect", 350.0)
        drv = _SyncFakeDriver()
        svc = _svc(self._dir, driver=drv)
        out = asyncio.run(svc.ensure_target_confirmed("rail"))
        self.assertEqual(out["target_node"], "Rail_Pos_Target")
        self.assertEqual(drv.state["Rail_Pos_Target"], [0.0, 0.0, 350.0, 0.0, 0.0, 0.0])
        # 未触发握手: 无 Req=PUSH 写入, POU 未跑 → 无 Ack/镜像
        self.assertNotIn("Rail_Sync_Req", drv.state)
        self.assertNotIn("Rail_Sync_Ack", drv.state)
        self.assertNotIn("Rail_Pos_HMI", drv.state)

    def test_pull_sync_preview_then_commit(self) -> None:
        drv = _SyncFakeDriver({"Rail_Pos_HMI": [11.0, 22.0, 33.0, 44.0, 55.0, 66.0]})
        svc = _svc(self._dir, driver=drv)
        # confirm=False: 仅预览, 不落盘
        prev = asyncio.run(svc.pull_sync("rail", confirm=False))
        self.assertFalse(prev["committed"])
        self.assertEqual(prev["preview"]["rail_p1_sampling"], 11.0)
        self.assertEqual(svc.servo_entry("rail_p1_sampling").value, 0.0)  # 未改
        # confirm=True: 落盘 + 重算 target
        out = asyncio.run(svc.pull_sync("rail", confirm=True))
        self.assertTrue(out["committed"])
        svc2 = _svc(self._dir)
        self.assertEqual(svc2.servo_entry("rail_p4_tool").value, 44.0)   # 已持久化
        self.assertEqual(drv.state["Rail_Pos_Target"], [11.0, 22.0, 33.0, 44.0, 55.0, 66.0])

    def test_pull_sync_rejects_out_of_limit(self) -> None:
        # 教出值越限 (>3000) → 拒绝并置 Ack=REJECT, 不落盘
        drv = _SyncFakeDriver({"Rail_Pos_HMI": [9999.0, 0.0, 0.0, 0.0, 0.0, 0.0]})
        svc = _svc(self._dir, driver=drv)
        with self.assertRaises(ValueError):
            asyncio.run(svc.pull_sync("rail", confirm=True))
        self.assertEqual(drv.state["Rail_Sync_Ack"], SYNC_ACK_REJECT)
        self.assertEqual(svc.servo_entry("rail_p1_sampling").value, 0.0)  # 未落盘

    def test_sync_requires_driver_and_group(self) -> None:
        svc = _svc(self._dir)   # driver=None
        with self.assertRaises(PointsCatalogError):
            asyncio.run(svc.diff_sync("rail"))           # 无 driver
        drv = _SyncFakeDriver({"Rail_Pos_HMI": [0.0] * 6})
        svc = _svc(self._dir, driver=drv)
        with self.assertRaises(PointsCatalogError):
            asyncio.run(svc.diff_sync("spotting"))       # 无 sync 契约


if __name__ == "__main__":
    unittest.main()
