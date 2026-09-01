"""物料一键审查离线测试
========================
功能:
    两层验证 runtime/material_audit + api/material_audit_routes:
    1. 纯函数层: 各核对函数的判定四象限 / fix 载荷 / severity 映射, 不起 app;
    2. 端点层: 经 create_sim_app 起完整 sim 装配, POST /api/materials/audit
       走真实取数链 (mock PLC 字节 / 调度器快照 / robot 工具态), 并断言
       **只报不改** (连打两次审查, 账本稳定面逐键相等) 与"造矛盾-修复-复审"闭环。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m unittest eit_ptlc.tests.test_material_audit_offline -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import eit_ptlc.runtime.bootstrap as bootstrap
from eit_ptlc.runtime import material_audit as audit


def _grid_min(**overrides) -> dict:
    """拼一份最小 grid 形状 (纯函数测试用), overrides 覆盖单键."""
    grid = {"seats": [], "transit": {}, "magazines": [], "bottles": [], "cells": [],
            "payload_seats": [], "topology": {"categories": []}}
    grid.update(overrides)
    return grid


class TestMagazineBottomRows(unittest.TestCase):
    """板仓账面 vs 仓底接近开关 (IX8.5=feed, IX8.6=waste) 的四象限."""

    def _rows(self, ix8: int, feed_count: int) -> dict:
        magazines = [{"magazine": "feed", "label": "上料仓", "count": feed_count,
                      "capacity": 30},
                     {"magazine": "waste", "label": "下料仓", "count": 0, "capacity": 30}]
        rows = audit.magazine_bottom_rows(ix8, magazines)
        return {row["id"]: row for row in rows}

    def test_count_zero_and_empty_is_ok(self):
        row = self._rows(0, 0)["derived.magazine.feed"]
        self.assertEqual(row["severity"], "ok")

    def test_count_positive_but_bottom_empty_is_mismatch_with_fix(self):
        """账面 >0 而仓底说空: 一键置 0 (以实为准)."""
        row = self._rows(0, 5)["derived.magazine.feed"]
        self.assertEqual(row["severity"], "mismatch")
        self.assertEqual(row["fix"]["action"], "magazine")
        self.assertEqual(row["fix"]["payload"], {"magazine": "feed", "count": 0})

    def test_count_zero_but_bottom_has_plate_is_mismatch_without_fix(self):
        """账面 =0 而仓底说有: 真实张数未知, 不许猜, 只指向实测."""
        row = self._rows(1 << 5, 0)["derived.magazine.feed"]
        self.assertEqual(row["severity"], "mismatch")
        self.assertIsNone(row["fix"])
        self.assertEqual(row["goto"], {"cat": "glass"})
        self.assertIn("会动轴", row["note"])

    def test_count_positive_and_bottom_has_plate_is_ok(self):
        row = self._rows(1 << 5, 5)["derived.magazine.feed"]
        self.assertEqual(row["severity"], "ok")


class TestCollectBottleRow(unittest.TestCase):
    """收集工位瓶位: IX8.1 vs payload_seat['collect-bottle']."""

    _SEATED = [{"seat": "collect-bottle", "kind": "bottle", "plate": 2, "hole": 4}]

    def test_no_declaration_yields_no_row(self):
        self.assertIsNone(audit.collect_bottle_row(None, self._SEATED))

    def test_unverified_never_judges(self):
        """极性未实证: 双方数值照显, 恒 unverifiable —— 纪律③."""
        for present, seats in ((True, []), (False, self._SEATED)):
            row = audit.collect_bottle_row(
                {"verified": False, "present": present}, seats)
            self.assertEqual(row["severity"], "unverifiable")
            self.assertIsNone(row["fix"])

    def test_verified_sensor_empty_but_account_has_item(self):
        """传感器空而账面有件: 一键清座位账."""
        row = audit.collect_bottle_row(
            {"verified": True, "present": False}, self._SEATED)
        self.assertEqual(row["severity"], "mismatch")
        self.assertEqual(row["fix"]["action"], "payload_seat")
        self.assertEqual(row["fix"]["payload"], {"seat": "collect-bottle"})

    def test_verified_sensor_has_bottle_but_account_empty(self):
        """传感器有而账面空: 瓶身份未知, 无 fix, 指向件位页人工放件."""
        row = audit.collect_bottle_row({"verified": True, "present": True}, [])
        self.assertEqual(row["severity"], "mismatch")
        self.assertIsNone(row["fix"])
        self.assertEqual(row["goto"], {"cat": "holder"})

    def test_verified_match_is_ok(self):
        row = audit.collect_bottle_row(
            {"verified": True, "present": True}, self._SEATED)
        self.assertEqual(row["severity"], "ok")


class TestToolStateRow(unittest.TestCase):
    """机器人工具检测位 vs 权威工具态 (推定判据, 不符只 warn)."""

    def test_skip_reason_wins(self):
        row = audit.tool_state_row(0x70, 2, skip_reason="机器人运动中")
        self.assertEqual(row["severity"], "skip")

    def test_matching_bits_ok(self):
        """挂 2 号工具: 期望 1/3 号在刀架 (bit4=1, bit5=0, bit6=1)."""
        row = audit.tool_state_row((1 << 4) | (1 << 6), 2)
        self.assertEqual(row["severity"], "ok")

    def test_mismatch_is_warn_only(self):
        """全 1 与挂 2 号矛盾, 但该族极性未实证 -> warn 不给 mismatch."""
        row = audit.tool_state_row((1 << 4) | (1 << 5) | (1 << 6), 2)
        self.assertEqual(row["severity"], "warn")
        self.assertIsNone(row["fix"], "工具态修正不在物料写端点集内")


class TestTankRows(unittest.TestCase):
    """展缸状态 vs 调度器占用: 只判错误态与无主残留."""

    def test_idle_and_owned_transient_are_ok(self):
        rows = audit.tank_rows([0] * 8, {"6": "s1"})
        self.assertTrue(all(row["severity"] == "ok" for row in rows))

    def test_error_state_warns(self):
        rows = {row["id"]: row for row in audit.tank_rows([0, 0, 90] + [0] * 5, {})}
        self.assertEqual(rows["derived.tank.3"]["severity"], "warn")

    def test_unowned_residual_state_warns_without_fix(self):
        rows = {row["id"]: row for row in audit.tank_rows([0] * 4 + [98] + [0] * 3, {})}
        row = rows["derived.tank.5"]
        self.assertEqual(row["severity"], "warn")
        self.assertIsNone(row["fix"], "释放缸会驱动硬件, 违反只报不改")

    def test_owned_residual_state_is_ok(self):
        rows = {row["id"]: row for row in
                audit.tank_rows([50] + [0] * 7, {"1": "s2"})}
        self.assertEqual(rows["derived.tank.1"]["severity"], "ok")


class TestLedgerRows(unittest.TestCase):
    """软件双账: 座位 vs 调度 / 陈旧在途 / 孤儿预留 / 越界."""

    def test_scheduler_down_yields_skip_rows(self):
        rows = audit.ledger_rows(_grid_min(), None, {"bottle": {"count_level": ["s1"],
                                                                "holes": []}},
                                 sched_error="调度器未装配")
        severities = {row["id"]: row["severity"] for row in rows}
        self.assertEqual(severities["ledger.seat"], "skip")
        self.assertEqual(severities["ledger.reservations"], "skip")

    def test_seat_vs_scheduler_mismatch_fix_follows_scheduler(self):
        grid = _grid_min(seats=[{"seat": "spot_seat", "label": "点样座", "present": True}])
        rows = audit.ledger_rows(grid, [], {})
        row = next(r for r in rows if r["id"] == "ledger.seat.spot_seat")
        self.assertEqual(row["severity"], "warn")
        self.assertEqual(row["fix"]["action"], "seat")
        self.assertEqual(row["fix"]["payload"], {"seat": "spot_seat", "present": False})

    def test_seat_matching_scheduler_is_ok(self):
        grid = _grid_min(seats=[{"seat": "spot_seat", "label": "点样座", "present": True}])
        samples = [{"sample_id": "s1", "status": "RUNNING", "position": "spot_seat"}]
        rows = audit.ledger_rows(grid, samples, {})
        row = next(r for r in rows if r["id"] == "ledger.seat.spot_seat")
        self.assertEqual(row["severity"], "ok")

    def test_stale_transit_warns_and_fresh_does_not(self):
        grid = _grid_min(transit={
            "gripper_vial": {"stale": True, "payload": "item", "kind": "bottle",
                             "plate": 1, "hole": 2},
            "gripper_plate96": {"stale": False, "payload": "tray", "kind": "collector",
                                "plate": 3, "hole": None}})
        rows = audit.ledger_rows(grid, [], {})
        ids = [row["id"] for row in rows]
        self.assertIn("ledger.transit.gripper_vial", ids)
        self.assertNotIn("ledger.transit.gripper_plate96", ids,
                         "本进程在途行可信, 不该报")

    def test_orphan_reservation_offers_release(self):
        """样品不在任何批次 / 已终止 -> 孤儿; 活跃样品的预留不报."""
        reserved = {"bottle": {"count_level": ["gone", "done1", "alive"], "holes": []}}
        samples = [{"sample_id": "done1", "status": "DONE", "position": "none"},
                   {"sample_id": "alive", "status": "RUNNING", "position": "feedlift"}]
        rows = audit.ledger_rows(_grid_min(), samples, reserved)
        by_id = {row["id"]: row for row in rows}
        self.assertIn("ledger.reservation.bottle.gone", by_id)
        self.assertIn("ledger.reservation.bottle.done1", by_id)
        self.assertNotIn("ledger.reservation.bottle.alive", by_id)
        fix = by_id["ledger.reservation.bottle.gone"]["fix"]
        self.assertEqual(fix["action"], "reservation_release")
        self.assertEqual(fix["payload"], {"sample_id": "gone", "kind": "bottle"})

    def test_out_of_range_rows(self):
        """越界必错但真值未知: mismatch 且一律无 fix."""
        grid = _grid_min(
            magazines=[{"magazine": "feed", "label": "上料仓", "count": 35,
                        "capacity": 30}],
            bottles=[{"bottle": "eluent", "label": "洗脱液", "volume_ml": 120.0,
                      "capacity_ml": 100.0}],
            cells=[{"kind": "bottle", "plate": 1, "hole": 1, "liquid_ml": 40.0}],
            topology={"categories": [{"contents": [
                {"kind": "bottle", "capacity": 29.65}]}]})
        rows = audit.ledger_rows(grid, [], {})
        by_id = {row["id"]: row for row in rows}
        for row_id in ("ledger.range.magazine.feed", "ledger.range.bottle.eluent",
                       "ledger.range.cell.bottle.1.1"):
            self.assertEqual(by_id[row_id]["severity"], "mismatch")
            self.assertIsNone(by_id[row_id]["fix"])


class TestCapacityDriftRows(unittest.TestCase):
    """库内容量/名称 vs 拓扑声明 (种子漂移)."""

    def test_drift_warns_and_match_is_silent(self):
        grid = _grid_min(
            magazines=[{"magazine": "feed", "label": "上料仓", "capacity": 25}],
            bottles=[{"bottle": "eluent", "label": "洗脱液", "capacity_ml": 100.0}],
            topology={"categories": [{
                "magazines": [{"id": "feed", "capacity": 30}],
                "bottles": [{"id": "eluent", "label": "洗脱液", "capacity_ml": 100.0}],
            }]})
        rows = audit.capacity_drift_rows(grid)
        self.assertEqual([row["id"] for row in rows], ["ledger.capacity.magazine.feed"])
        self.assertEqual(rows[0]["severity"], "warn")


class TestPresenceRows(unittest.TestCase):
    """reconcile 行 -> 审查行的映射."""

    def test_no_account_rows_are_dropped(self):
        rows = audit.presence_rows([
            {"location_id": "feed-1", "label": "上样料架1", "expected": None,
             "ok": None, "verified": True, "present": True}])
        self.assertEqual(rows, [])

    def test_unverified_with_account_is_unverifiable(self):
        rows = audit.presence_rows([
            {"location_id": "rack.collector.1", "label": "货架 collector板1",
             "expected": True, "ok": None, "verified": False, "present": False}])
        self.assertEqual(rows[0]["severity"], "unverifiable")

    def test_staging_empty_sensor_offers_clear_fix(self):
        rows = audit.presence_rows([
            {"location_id": "staging-a", "label": "中转托盘位A", "expected": True,
             "ok": False, "verified": True, "present": False, "note": "x"}])
        row = rows[0]
        self.assertEqual(row["severity"], "mismatch")
        self.assertEqual(row["fix"]["action"], "staging")
        self.assertEqual(row["fix"]["payload"], {"area": "staging-a", "plate": None})

    def test_reverse_direction_has_no_fix(self):
        """传感器报有料但账空: 板号无从知道, 只给跳转."""
        rows = audit.presence_rows([
            {"location_id": "staging-a", "label": "中转托盘位A", "expected": False,
             "ok": False, "verified": True, "present": True, "note": "x"}])
        self.assertIsNone(rows[0]["fix"])
        self.assertEqual(rows[0]["goto"], {"cat": "tray"})


class TestCounts(unittest.TestCase):
    def test_count_rows_aggregates_all_groups(self):
        groups = [{"rows": [{"severity": "mismatch"}, {"severity": "ok"}]},
                  {"rows": [{"severity": "warn"}, {"severity": "unverifiable"},
                            {"severity": "skip"}]}]
        self.assertEqual(audit.count_rows(groups),
                         {"mismatch": 1, "warn": 1, "unverifiable": 1, "ok": 1,
                          "skipped": 1})


class TestAuditEndpoint(unittest.TestCase):
    """端点层: 走完整 sim 装配的真实取数链."""

    @classmethod
    def setUpClass(cls):
        # 隔离数据根: 不写 eit_ptlc/var/, 不干扰常驻真机后端的库文件
        cls._tmp = tempfile.TemporaryDirectory(prefix="ptlc-mat-audit-")
        cls._orig_data_dir = bootstrap._DATA_DIR
        bootstrap._DATA_DIR = Path(cls._tmp.name)
        cls._app = bootstrap.create_sim_app(
            opcua_url="opc.tcp://127.0.0.1:48498/eit_ptlc/sim/")

    @classmethod
    def tearDownClass(cls):
        bootstrap._DATA_DIR = cls._orig_data_dir
        cls._tmp.cleanup()

    def test_audit_shape_and_report_only_discipline(self):
        """四组齐全 + 计数五键 + 连打两次账本稳定面逐键相等 (只报不改)."""
        with TestClient(self._app) as client:
            first = client.post("/api/materials/audit")
            self.assertEqual(first.status_code, 200)
            body = first.json()
            self.assertEqual([g["key"] for g in body["groups"]],
                             ["presence", "derived", "ledger", "manual"])
            self.assertEqual(set(body["counts"]),
                             {"mismatch", "warn", "unverifiable", "ok", "skipped"})
            by_key = {g["key"]: g for g in body["groups"]}
            # mock PLC 可读: 在位组要么有行要么有 error 横幅, 不允许空表无解释
            self.assertTrue(by_key["presence"]["rows"]
                            or by_key["presence"]["error"])
            self.assertTrue(by_key["manual"]["rows"])
            second = client.post("/api/materials/audit").json()
            for key in ("cells", "staging", "rack", "magazines", "bottles",
                        "seats", "summary", "transit"):
                self.assertEqual(body["grid"][key], second["grid"][key],
                                 f"审查改动了账本的 {key} —— 违反只报不改")

    def test_mismatch_fix_roundtrip(self):
        """造矛盾 (账面 5 张而仓底空) -> 审查报 mismatch 带 fix -> 执行 fix -> 复审转绿."""
        with TestClient(self._app) as client:
            client.post("/api/materials/magazine", json={"magazine": "feed", "count": 5})
            body = client.post("/api/materials/audit").json()
            derived = next(g for g in body["groups"] if g["key"] == "derived")
            row = next(r for r in derived["rows"] if r["id"] == "derived.magazine.feed")
            self.assertEqual(row["severity"], "mismatch")
            self.assertEqual(row["fix"]["payload"], {"magazine": "feed", "count": 0})

            # 前端点"以实为准"= 把 fix.payload 原样交给既有写端点
            client.post("/api/materials/magazine", json=row["fix"]["payload"])
            body = client.post("/api/materials/audit").json()
            derived = next(g for g in body["groups"] if g["key"] == "derived")
            row = next(r for r in derived["rows"] if r["id"] == "derived.magazine.feed")
            self.assertEqual(row["severity"], "ok")

    def test_payload_seat_place_and_clear_endpoint(self):
        """payload_seat 端点双语义: 三元组=放件, 只给 seat=清账, 半截=400."""
        with TestClient(self._app) as client:
            resp = client.post("/api/materials/payload_seat",
                               json={"seat": "scrape-holder", "kind": "collector",
                                     "plate": 2, "hole": 3})
            self.assertEqual(resp.status_code, 200)
            seats = {row["seat"]: row for row in resp.json()["payload_seats"]}
            self.assertEqual((seats["scrape-holder"]["plate"],
                              seats["scrape-holder"]["hole"]), (2, 3))
            self.assertEqual(
                client.post("/api/materials/payload_seat",
                            json={"seat": "scrape-holder", "kind": "collector",
                                  "plate": 2}).status_code, 400,
                "三元组只给一部分必须按写错拒")
            resp = client.post("/api/materials/payload_seat",
                               json={"seat": "scrape-holder"})
            self.assertEqual(resp.json()["payload_seats"], [])

    def test_reservation_release_endpoint_is_idempotent(self):
        with TestClient(self._app) as client:
            resp = client.post("/api/materials/reservations/release",
                               json={"sample_id": "ghost"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                client.post("/api/materials/reservations/release",
                            json={}).status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
