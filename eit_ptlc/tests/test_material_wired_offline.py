"""物料账本装配接线离线测试
============================
功能:
    验证 sim 装配确实把物料账本接进了 VM 事件 sink 与 app.state, 并且 REST 端点可用.

    为什么单列一个文件: 这是本方案最危险的漏洞形态 —— 账本只作为 make_event_sink 的一路
    接收器存在, 若漏接线则纯 store 单测会全绿而真机零记账. 故必须有一条测试断言
    "app.state.vm 交给每个 VmThread 的那个 sink 里确实有账本".

    这里经 app.state.vm._emit 直接投递合成事件, 不跑真实转运流程: 转运链需地轨已回零
    (sim 默认 Rail_Homed=FALSE, auto_rail 前置拦截), 那是流程前置条件, 与记账接线无关.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m unittest eit_ptlc.tests.test_material_wired_offline -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import eit_ptlc.runtime.bootstrap as bootstrap


class TestMaterialWiring(unittest.TestCase):
    """sim 装配的物料账本接线."""

    @classmethod
    def setUpClass(cls):
        # 隔离数据根: 不写 eit_ptlc/var/, 不干扰常驻真机后端的库文件
        cls._tmp = tempfile.TemporaryDirectory(prefix="ptlc-mat-wire-")
        cls._orig_data_dir = bootstrap._DATA_DIR
        bootstrap._DATA_DIR = Path(cls._tmp.name)
        cls._app = bootstrap.create_sim_app(
            opcua_url="opc.tcp://127.0.0.1:48497/eit_ptlc/sim/")

    @classmethod
    def tearDownClass(cls):
        bootstrap._DATA_DIR = cls._orig_data_dir
        cls._tmp.cleanup()

    def test_store_on_app_state_and_endpoint_serves_seeded_grid(self):
        """app.state.material_store 就位, REST 直出播种好的 72 格与两个中转区.

        本类共用一个 app 与库文件, 故只断结构不断具体状态 (初值全空由
        test_material_store_offline.TestSeeding 覆盖).
        """
        with TestClient(self._app) as client:
            self.assertIsNotNone(getattr(client.app.state, "material_store", None))
            grid = client.get("/api/materials").json()
            self.assertEqual(len(grid["cells"]), 72)
            self.assertEqual({cell["kind"] for cell in grid["cells"]}, {"collector", "bottle"})
            self.assertEqual(set(grid["staging"]), {"staging-a", "staging-b"})
            for kind in ("collector", "bottle"):
                counts = grid["summary"][kind]
                self.assertEqual(counts["fresh"] + counts["used"], 36)

    def test_vm_event_sink_reaches_the_ledger(self):
        """VM 交给每个 VmThread 的 sink 里确实有账本 —— 漏接线则真机零记账."""
        with TestClient(self._app) as client:
            emit = client.app.state.vm._emit      # VmThread 收到的正是这个 sink
            client.post("/api/materials/mark",
                        json={"kind": "collector", "plate": 5, "state": "FRESH"})

            # 合成一次"面板直跑 transfer_collector_rack_to_staging_a(slot_id=5)"
            emit({"type": "operation_start", "run_id": "wire-1",
                  "operation": "transfer_collector_rack_to_staging_a",
                  "inputs": {"slot_id": 5}, "ts": 1.0})
            emit({"type": "operation_done", "run_id": "wire-1",
                  "operation": "transfer_collector_rack_to_staging_a", "ts": 2.0})

            grid = client.get("/api/materials").json()
            self.assertEqual(grid["staging"]["staging-a"]["plate"], 5,
                             "账本未收到 VM 事件: material_store.on_event 未接入 make_event_sink")

            # 再合成一次子脚本调用的单件消耗, 验证 (板, 孔) 定位链完整
            emit({"type": "vm_node_enter", "run_id": "wire-1", "script": "demo", "aid": "b1",
                  "op": "run_script", "action": "transfer_collector_staging_a_to_scrape",
                  "args": {"slot_id": 3}, "ts": 3.0})
            emit({"type": "vm_node_done", "run_id": "wire-1", "script": "demo", "aid": "b1",
                  "op": "run_script", "action": "transfer_collector_staging_a_to_scrape",
                  "status": "DONE", "ts": 4.0})

            cells = client.get("/api/materials").json()["cells"]
            cell = next(c for c in cells
                        if c["kind"] == "collector" and c["plate"] == 5 and c["hole"] == 3)
            self.assertEqual(cell["state"], "USED")

    def test_transit_reaches_ledger_and_rest(self):
        """叶子层取放经同一条 sink 落成在途行, 并从 /api/materials 透出.

        这条是"实时页托盘不动"的收口: 三维画在途靠的就是 material_state.transit,
        而那份快照就是本端点的内容 —— 接线断了这里立刻红。
        """
        with TestClient(self._app) as client:
            emit = client.app.state.vm._emit
            client.post("/api/materials/mark",
                        json={"kind": "bottle", "plate": 4, "state": "FRESH"})

            # 合成一次 robot_group_rack_pick(bottle, slot_id=4) 的子脚本调用
            emit({"type": "vm_node_enter", "run_id": "wire-t", "script": "demo", "aid": "t1",
                  "op": "run_script", "action": "robot_group_rack_pick",
                  "args": {"rack_id": "bottle", "slot_id": 4}, "ts": 10.0})
            emit({"type": "vm_node_done", "run_id": "wire-t", "script": "demo", "aid": "t1",
                  "op": "run_script", "action": "robot_group_rack_pick",
                  "status": "DONE", "ts": 11.0})

            grid = client.get("/api/materials").json()
            row = grid["transit"].get("gripper_plate96")
            self.assertIsNotNone(row, "在途未落账: 叶子层绑定或 sink 接线断了")
            self.assertEqual((row["payload"], row["kind"], row["plate"]), ("tray", "bottle", 4))
            rack = next(r for r in grid["rack"]
                        if r["kind"] == "bottle" and r["plate"] == 4)
            self.assertEqual(rack["present"], 0, "板在爪上时库位必须已标空, 否则三维画两块板")

            # 人工清账端点: 崩溃后板滞留在爪上时的唯一出路
            grid = client.post("/api/materials/transit",
                               json={"carrier": "gripper_plate96", "land_at": "rack"}).json()
            self.assertEqual(grid["transit"], {})
            rack = next(r for r in grid["rack"]
                        if r["kind"] == "bottle" and r["plate"] == 4)
            self.assertEqual(rack["present"], 1)
            self.assertEqual(client.post("/api/materials/transit",
                                         json={"carrier": "nope"}).status_code, 400)

    def test_panel_single_fire_draws_solvent(self):
        """面板单发动作经 step_done 扣溶剂; 流水标 [面板单发] 供人辨认与撤销."""
        with TestClient(self._app) as client:
            emit = client.app.state.vm._emit
            client.post("/api/materials/bottle", json={"bottle": "eluent", "volume_ml": 400.0})
            emit({"type": "step_done", "run_id": "panel-1", "step": "a1",
                  "action": "collect.collect", "index": 0,
                  "params": {"solvent_volume_ml": 25.0}, "status": "DONE", "ts": 20.0})

            grid = client.get("/api/materials").json()
            eluent = next(b for b in grid["bottles"] if b["bottle"] == "eluent")
            self.assertAlmostEqual(eluent["volume_ml"], 375.0, places=3)
            events = client.get("/api/materials/events?limit=5").json()["events"]
            draw = next(e for e in events if e["effect"] == "liquid_draw")
            self.assertIn("[面板单发]", draw["detail"])

    def test_plate_and_bottle_endpoints(self):
        """玻璃板仓与溶剂瓶的盘点端点; 非法入参 400."""
        with TestClient(self._app) as client:
            grid = client.post("/api/materials/magazine",
                               json={"magazine": "feed", "count": 12}).json()
            feed = next(m for m in grid["magazines"] if m["magazine"] == "feed")
            self.assertEqual(feed["count"], 12)
            self.assertEqual(feed["label"], "上料仓 (1Z)")

            grid = client.post("/api/materials/bottle",
                               json={"bottle": "solvent_2", "volume_ml": 250.0}).json()
            s2 = next(b for b in grid["bottles"] if b["bottle"] == "solvent_2")
            self.assertAlmostEqual(s2["volume_ml"], 250.0, places=3)
            self.assertAlmostEqual(s2["percent"], 25.0, places=1)

            self.assertEqual(client.post("/api/materials/magazine",
                                         json={"magazine": "attic", "count": 1}).status_code, 400)
            self.assertEqual(client.post("/api/materials/bottle",
                                         json={"bottle": "beaker",
                                               "volume_ml": 1.0}).status_code, 400)

    def test_rack_presence_endpoint(self):
        """货架在架端点: 无板参与统计剔除; 板在中转时 400; present 非布尔 400.

        本类共用一个库, 用例末尾把状态全部还原 (标回有板 / 中转置空), 不污染其他用例。
        """
        with TestClient(self._app) as client:
            grid = client.post("/api/materials/rack",
                               json={"kind": "collector", "plate": 6,
                                     "present": False}).json()
            row = next(r for r in grid["rack"]
                       if r["kind"] == "collector" and r["plate"] == 6)
            self.assertEqual(row["present"], 0)
            counts = grid["summary"]["collector"]
            self.assertEqual(counts["absent_plates"], 1)
            self.assertEqual(counts["fresh"] + counts["used"], 30)   # 缺板 6 孔退出统计

            grid = client.post("/api/materials/rack",
                               json={"kind": "collector", "plate": 6,
                                     "present": True}).json()
            self.assertEqual(grid["summary"]["collector"]["absent_plates"], 0)

            # 板在中转位时拒改, 在架态由中转占用维护
            client.post("/api/materials/staging", json={"area": "staging-b", "plate": 6})
            resp = client.post("/api/materials/rack",
                               json={"kind": "bottle", "plate": 6, "present": False})
            self.assertEqual(resp.status_code, 400)
            self.assertIn("中转", resp.json()["detail"])
            client.post("/api/materials/staging", json={"area": "staging-b", "plate": None})

            self.assertEqual(client.post("/api/materials/rack",
                                         json={"kind": "collector", "plate": 1,
                                               "present": "yes"}).status_code, 400)
            self.assertEqual(client.post("/api/materials/rack",
                                         json={"kind": "widget", "plate": 1,
                                               "present": False}).status_code, 400)

    def test_seat_presence_endpoint(self):
        """板位端点: 翻转回带 grid; 未知座名与非布尔 present 均 400.

        本类共用一个库, 用例末尾还原为无板, 不污染其他用例。
        """
        with TestClient(self._app) as client:
            grid = client.post("/api/materials/seat",
                               json={"seat": "spot_seat", "present": True}).json()
            row = next(r for r in grid["seats"] if r["seat"] == "spot_seat")
            self.assertTrue(row["present"])
            self.assertIn("点样座", row["label"])
            # 只供展示: 不得渗进统计口径 (薄层板不是孔位耗材)
            self.assertEqual(grid["summary"]["collector"]["absent_plates"], 0)

            self.assertEqual(client.post("/api/materials/seat",
                                         json={"seat": "nope",
                                               "present": True}).status_code, 400)
            self.assertEqual(client.post("/api/materials/seat",
                                         json={"seat": "spot_seat",
                                               "present": "yes"}).status_code, 400)

            grid = client.post("/api/materials/seat",
                               json={"seat": "spot_seat", "present": False}).json()
            self.assertFalse(next(r for r in grid["seats"]
                                  if r["seat"] == "spot_seat")["present"])

    def test_liquid_draw_reaches_ledger_through_vm_sink(self):
        """动作级绑定 (op: call) 也经 VM sink 落账 —— 液体扣减挂在动作上."""
        with TestClient(self._app) as client:
            emit = client.app.state.vm._emit
            client.post("/api/materials/bottle",
                        json={"bottle": "solvent_1", "volume_ml": 100.0})
            emit({"type": "vm_node_enter", "run_id": "wire-liq", "script": "demo", "aid": "b1",
                  "op": "call", "action": "develop.fill",
                  "args": {"target_tank": 1, "solvent_volume_ml": 5.0,
                           "up_liquid_repeat_count": 2, "solvent_ratio_1": 1.0,
                           "solvent_ratio_2": 0.0, "solvent_ratio_3": 0.0,
                           "solvent_ratio_4": 0.0}, "ts": 1.0})
            emit({"type": "vm_node_done", "run_id": "wire-liq", "script": "demo", "aid": "b1",
                  "op": "call", "action": "develop.fill", "status": "DONE", "ts": 2.0})

            bottles = {b["bottle"]: b["volume_ml"]
                       for b in client.get("/api/materials").json()["bottles"]}
            self.assertAlmostEqual(bottles["solvent_1"], 90.0, places=3,
                                   msg="动作级绑定未落账: sink 未处理 op=call")

    def test_topology_endpoint_serves_six_categories(self):
        """/materials/topology 直出六类树 —— 前端左侧导航与分区据此渲染, 不再硬编码."""
        with TestClient(self._app) as client:
            cats = client.get("/api/materials/topology").json()["categories"]
            self.assertEqual([c["key"] for c in cats],
                             ["tray", "holder", "feed", "glass", "solvent", "seat"])
            by_key = {c["key"]: c for c in cats}
            # 板位无位置无传感器 (故不进对账读字节的清单)。2026-08-13 补 8 个展缸位:
            # 此前"哪块板在哪个缸"只存在于调度器缸池, 没批次跑着时无处表达。
            self.assertEqual(by_key["seat"]["locations"], [])
            self.assertEqual([s["id"] for s in by_key["seat"]["seats"]],
                             ["spot_seat", "scrape_table"]
                             + [f"tank_{index}" for index in range(1, 9)])
            # 件位由流程事件自动记账 (seat 是纯人工账), 两者不可合并; 收集瓶位是三座里
            # 唯一有传感器的 (IX8.1, PLC 拿它做 A22/A23 硬互锁), 极性未实证前只显读数
            holder_locs = by_key["holder"]["locations"]
            self.assertEqual([loc["id"] for loc in holder_locs], ["collect-bottle"])
            self.assertEqual((holder_locs[0]["byte"], holder_locs[0]["bit"]), ("IX8", 1))
            self.assertFalse(holder_locs[0]["verified"])
            self.assertEqual([(p["id"], p["accepts"]) for p in by_key["holder"]["payload_seats"]],
                             [("scrape-holder", "collector"), ("collect-holder", "collector"),
                              ("collect-bottle", "bottle")])
            self.assertEqual([loc["id"] for loc in by_key["tray"]["locations"]],
                             ["rack", "staging-a", "staging-b"])
            self.assertEqual([loc["id"] for loc in by_key["feed"]["locations"]],
                             ["feed-1", "feed-2"])
            self.assertEqual([m["id"] for m in by_key["glass"]["magazines"]], ["feed", "waste"])
            self.assertEqual(len(by_key["solvent"]["bottles"]), 5)
            # 极性与是否已实证随位置透出, 供页面标注"极性未核实"
            feed1 = by_key["feed"]["locations"][0]
            self.assertEqual(feed1["polarity"], "no")
            self.assertTrue(feed1["verified"])
            rack = by_key["tray"]["locations"][0]
            self.assertEqual(rack["slots"], 12)
            self.assertFalse(rack["verified"])

    def test_reconcile_endpoint_covers_all_sensored_locations(self):
        """对账覆盖全部有传感器的位置 (12 货架 + 2 中转 + 2 上料 + 1 收集瓶位); 读不到则 503."""
        with TestClient(self._app) as client:
            resp = client.post("/api/materials/reconcile")
            self.assertIn(resp.status_code, (200, 503))
            if resp.status_code == 503:
                self.assertIn("输入字节", resp.json()["detail"])
            else:
                body = resp.json()
                self.assertEqual(len(body["rows"]), 17)
                self.assertIn("grid", body)
                # 原始字节按名列全, 供现场分清"传感器说空"与"没信号"
                self.assertEqual(set(body["raw"]),
                                 {"IX8", "IX9", "IX10", "IX11", "IX12"})
                self.assertIn("tool_detect_bits", body["raw"]["IX12"])
                # 上料两处不判定, 故不进 mismatches
                feed = [r for r in body["rows"] if r["category"] == "feed"]
                self.assertEqual(len(feed), 2)
                self.assertTrue(all(r["ok"] is None for r in feed))

    def test_next_endpoint_contract(self):
        """next 端点: 无余量时 available=false (前端据此退回 default); 非法 kind 400."""
        with TestClient(self._app) as client:
            self.assertEqual(
                client.get("/api/materials/next", params={"kind": "widget"}).status_code, 400)
            body = client.get("/api/materials/next", params={"kind": "bottle"}).json()
            self.assertFalse(body["available"])

            client.post("/api/materials/mark",
                        json={"kind": "bottle", "plate": 2, "state": "FRESH"})
            body = client.get("/api/materials/next", params={"kind": "bottle"}).json()
            self.assertTrue(body["available"])
            self.assertEqual((body["rack_slot"], body["hole"]), (2, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
