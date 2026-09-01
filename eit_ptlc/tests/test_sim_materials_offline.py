"""仿真沙盒物料链离线测试
==========================
功能:
    验证阶段③ B 步的三件事:
      ① MaterialStore.export_rows / import_rows 的往返保真与白名单纪律;
      ② 导入后在途行自动判 stale (epoch 不同世界 -> "上一个世界留下的在途");
      ③ /api/sim/materials/* 镜像端点可写可读, 且**与真机账本完全隔离**
         (写沙盒不动主库, 这是沙盒隔离铁律里最容易被破的一条)。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_sim_materials_offline.py -q
"""

from __future__ import annotations

import socket
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from httpx import ASGITransport, AsyncClient

import eit_ptlc.runtime.bootstrap as bootstrap
from eit_ptlc.api.sim_routes import _seed_required_sim_materials
from eit_ptlc.tools.pump.profiles import set_pump_defaults_provider
from eit_ptlc.runtime.material_store import STATE_FRESH, MaterialStore
from eit_ptlc.runtime.sim_stack import build_sim_stack

from eit_ptlc.tests.test_material_store_offline import _store as _make_store


class TestSnapshotRoundTrip(unittest.TestCase):
    """export_rows / import_rows 的往返."""

    def test_round_trip_preserves_ledger_face(self):
        """搬过去的账面与源账本逐键相等 (板仓/溶剂/孔位/中转)."""
        source = _make_store()
        source.mark_plate("collector", 3, STATE_FRESH)
        source.set_magazine("feed", 17)
        source.set_bottle("solvent_1", 88.5)
        source.set_staging("staging-a", 3)
        source.set_cell_amount("collector", 3, 2, powder_mm3=1234.0)

        target = _make_store()
        counts = target.import_rows(source.export_rows())
        self.assertEqual(set(counts), set(MaterialStore.SNAPSHOT_TABLES))

        src_grid, dst_grid = source.grid(), target.grid()
        for key in ("cells", "staging", "rack", "magazines", "bottles", "seats", "summary"):
            self.assertEqual(src_grid[key], dst_grid[key], f"{key} 未逐键搬过去")

    def test_events_and_presence_are_not_transferable(self):
        """流水与传感器快照刻意不进快照: 真机历史不属于沙盒时间线."""
        self.assertNotIn("material_events", MaterialStore.SNAPSHOT_TABLES)
        self.assertNotIn("location_presence", MaterialStore.SNAPSHOT_TABLES)
        target = _make_store()
        with self.assertRaises(ValueError):
            target.import_rows({"material_events": []})

    def test_import_leaves_a_trace(self):
        """导入本身要留流水 —— 否则"账本怎么突然满了"无从追溯."""
        target = _make_store()
        target.import_rows(_make_store().export_rows(), detail="沙盒采纳")
        adopts = [e for e in target.list_events() if e["effect"] == "adopt"]
        self.assertTrue(adopts, "导入未留流水")
        self.assertIn("沙盒采纳", adopts[0]["detail"])

    def test_transit_rows_become_stale_in_the_new_world(self):
        """在途行搬过去自动判陈旧 (epoch 是本进程实例标识, 不同 store 必不同)."""
        source = _make_store()
        source.mark_plate("bottle", 4, STATE_FRESH)
        # 合成一次整板取料 -> 落在途行
        from eit_ptlc.tests.test_material_store_offline import _run_script
        _run_script(source, "robot_group_rack_pick", {"rack_id": "bottle", "slot_id": 4})
        self.assertFalse(source.grid()["transit"]["gripper_plate96"]["stale"])

        target = _make_store()
        target.import_rows(source.export_rows())
        row = target.grid()["transit"]["gripper_plate96"]
        self.assertEqual((row["kind"], row["plate"]), ("bottle", 4), "身份要原样搬过去")
        self.assertTrue(row["stale"],
                        "上一个世界留下的在途, 沙盒无法确认爪上真有东西 -> 必须判陈旧")
        self.assertEqual(target.grid()["transit_stale"], 1)

    def test_partial_snapshot_only_replaces_given_tables(self):
        """部分快照只替换给到的表 (调用方可只搬板仓)."""
        target = _make_store()
        target.set_bottle("solvent_2", 42.0)
        source = _make_store()
        source.set_magazine("waste", 9)
        target.import_rows({"plate_magazines": source.export_rows()["plate_magazines"]})
        self.assertEqual(target.magazine_count("waste"), 9)
        bottles = {b["bottle"]: b["volume_ml"] for b in target.grid()["bottles"]}
        self.assertEqual(bottles["solvent_2"], 42.0, "未给的表不该被清空")

    def test_new_sim_session_seeds_waste_support_plate_without_overwriting_inventory(self):
        """普通新沙盒默认有一张下料承托板；已有盘点绝不能被降回一张。"""
        store = _make_store()
        stack = type("Stack", (), {"material_store": store})()

        self.assertEqual(_seed_required_sim_materials(stack), {"waste": 1})
        self.assertEqual(store.magazine_count("waste"), 1)

        store.set_magazine("waste", 4)
        self.assertEqual(_seed_required_sim_materials(stack), {})
        self.assertEqual(store.magazine_count("waste"), 4)


def _free_port() -> int:
    """借一个空闲端口 (照 test_sim_stack_offline 同款)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestSimMaterialEndpoints(unittest.IsolatedAsyncioTestCase):
    """/api/sim/materials/* 镜像端点.

    ⚠ 沙盒的 Mock OPC 端口 (SANDBOX_URL, 48491) 是单例常量, 现场只要有人开着
    /3d/sim 就被占住 —— 故本类**不走 POST /api/sim/session**, 而是照
    test_sim_stack_offline 的做法用随机端口直建栈再挂进 app.state.sim,
    再经 ASGI 传输打真实路由。测的仍是路由本身, 只是绕开端口争用。
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="ptlc-sim-mat-")
        cls._orig_data_dir = bootstrap._DATA_DIR
        bootstrap._DATA_DIR = Path(cls._tmp.name)
        cls._app = bootstrap.create_sim_app(
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/sim/")

    @classmethod
    def tearDownClass(cls):
        bootstrap._DATA_DIR = cls._orig_data_dir
        cls._tmp.cleanup()
        # bootstrap 的 lifespan 会注入进程级泵档 provider; 不撤销会把 config.pump
        # 的持久档漏给后续测试 (见 test_spot_end_position_offline 的类注释)
        set_pump_defaults_provider(None)

    @asynccontextmanager
    async def _sandbox(self):
        """起一台随机端口沙盒并挂进 app.state.sim; 退出时停栈与摘挂."""
        app = self._app
        config = app.state.app_config
        repo = app.state.script_repo
        stack = await build_sim_stack(
            config,
            registry=app.state.registry,
            resolve_script=lambda name: repo.get("default", name),
            mode_provider=lambda: app.state.control_mode,
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/sandbox-test/",
            time_scale=8.0,
        )
        app.state.sim = stack
        try:
            yield stack
        finally:
            app.state.sim = None
            await stack.stop()

    @asynccontextmanager
    async def _client(self):
        """ASGI 传输客户端 (与沙盒同一事件循环, 不另起线程).

        必须显式跑 lifespan: 裸 ASGITransport 不会触发它, 而 app.state 的
        app_config/registry/material_store 全在 lifespan 里装配。
        """
        async with self._app.router.lifespan_context(self._app):
            transport = ASGITransport(app=self._app)
            async with AsyncClient(transport=transport,
                                   base_url="http://sim.test") as client:
                yield client

    async def test_endpoints_require_sandbox(self):
        """未建沙盒时 503 —— 不许静默落到主库."""
        self._app.state.sim = None
        async with self._client() as client:
            resp = await client.get("/api/sim/materials")
            self.assertEqual(resp.status_code, 503)

    async def test_sim_writes_never_touch_the_real_ledger(self):
        """同一批 handler 挂两处; 写沙盒绝不污染真机账本 (隔离铁律)."""
        async with self._client() as client:
            await client.post("/api/materials/magazine",
                              json={"magazine": "feed", "count": 3})
            async with self._sandbox():
                resp = await client.post("/api/sim/materials/magazine",
                                         json={"magazine": "feed", "count": 30})
                self.assertEqual(resp.status_code, 200)
                sim_counts = {m["magazine"]: m["count"] for m in resp.json()["magazines"]}
                self.assertEqual(sim_counts["feed"], 30)

                sim_grid = (await client.get("/api/sim/materials")).json()
                self.assertEqual(len(sim_grid["cells"]), 72)
                self.assertIn("topology", sim_grid)

            main_grid = (await client.get("/api/materials")).json()
            main_counts = {m["magazine"]: m["count"] for m in main_grid["magazines"]}
            self.assertEqual(main_counts["feed"], 3,
                             "写沙盒账本污染了真机账本 —— 隔离铁律被破")

    async def test_adopt_transfers_the_ledger(self):
        """POST /api/sim/adopt 把主库账本搬进沙盒, 且不再有"未实现"假文案."""
        async with self._client() as client:
            await client.post("/api/materials/magazine",
                              json={"magazine": "feed", "count": 12})
            await client.post("/api/materials/mark",
                              json={"kind": "collector", "plate": 2, "state": "FRESH"})
            async with self._sandbox():
                adopt = (await client.post("/api/sim/adopt")).json()
                reasons = " ".join(str(item) for item in adopt.get("skipped") or [])
                self.assertNotIn("暂未实现", reasons)
                self.assertNotIn("满配", reasons, "旧文案说的满配从来就不是事实")
                self.assertIn("materials", adopt, "采纳结果里应有物料段")
                self.assertGreater(adopt["materials"]["rows"], 0)

                sim_grid = (await client.get("/api/sim/materials")).json()
                sim_counts = {m["magazine"]: m["count"] for m in sim_grid["magazines"]}
                self.assertEqual(sim_counts["feed"], 12, "板仓张数未随采纳搬进沙盒")
                fresh = [c for c in sim_grid["cells"]
                         if c["kind"] == "collector" and c["plate"] == 2
                         and c["state"] == "FRESH"]
                self.assertEqual(len(fresh), 6, "孔位状态未随采纳搬进沙盒")


if __name__ == "__main__":
    unittest.main(verbosity=2)
