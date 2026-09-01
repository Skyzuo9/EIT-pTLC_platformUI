"""沙盒诊断面的离线测试
========================
功能:
    钉住诊断的三条纪律:
      ① `because` 由**已有合成规则原地求值** —— 板堆张数变了, 门的真值与说明跟着变;
      ② `value=None` 与 `value=False` 分开 —— "读不到"不能画成"不满足";
      ③ 传感器位表与实际写进 OPC 的字节**逐位一致** (共读 BIT_SPECS 的护栏)。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest \
        eit_ptlc/tests/test_sim_diagnostics_offline.py -q
"""

from __future__ import annotations

import asyncio
import socket
import unittest
from pathlib import Path

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.config.loader import load_config
from eit_ptlc.mock.plc_server import mock_read
from eit_ptlc.runtime.sim_stack import build_sim_stack

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _station(report: dict, name: str) -> dict:
    for row in report["stations"]:
        if row["station"] == name:
            return row
    raise AssertionError(f"诊断里缺工位 {name}")


class TestSimDiagnostics(unittest.TestCase):

    def test_end_to_end(self):
        asyncio.run(self._exercise())

    async def _exercise(self) -> None:
        config = load_config(_CONFIG_DIR / "app.yaml")
        registry = ActionRegistry.load(_CONFIG_DIR / "actions")
        stack = await build_sim_stack(
            config, registry=registry,
            resolve_script=lambda name: (_ for _ in ()).throw(KeyError(name)),
            mode_provider=lambda: "DEBUG",
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/diag-test/",
            time_scale=20.0,
        )
        try:
            await self._check_all_stations_present(stack)
            await self._check_gate_because_follows_the_model(stack)
            await self._check_unreadable_is_not_false(stack)
            await self._check_sensor_bits_match_bytes(stack)
            await self._check_feedlift_block(stack)
        finally:
            await stack.stop()

    async def _check_all_stations_present(self, stack) -> None:
        report = await stack.diagnostics()
        names = {row["station"] for row in report["stations"]}
        self.assertGreaterEqual(len(names), 8, f"应覆盖八个 L2 工位, 实际 {names}")
        for row in report["stations"]:
            self.assertIn("l2", row)
            self.assertIn("gate", row)

    async def _check_gate_because_follows_the_model(self, stack) -> None:
        """真因跟着板堆模型走: 张数变了, 门的真值与说明同时变."""
        stack.material_store.set_magazine("feed", 0)
        await stack.executor.execute("feedlift.feed_raise", {}, current_mode="DEBUG")
        report = await stack.diagnostics()
        row = _station(report, "FeedLift")
        self.assertEqual(int(row["l2"]["ErrorCode"]), 301)
        gate = {item["key"]: item for item in row["gate"]}
        self.assertFalse(gate["proximity"]["value"], "空仓时接近开关必须为假")
        self.assertIn("0 张", gate["proximity"]["because"])
        self.assertIn("仓是空的", gate["proximity"]["because"])
        self.assertTrue(row["error_text"], "错误码释义不该为空")
        self.assertIn("/api/sim/materials/magazine", row["error_text"],
                      "沙盒语境要指向状态入口, 不是真机标定话术")

        stack.material_store.set_magazine("feed", 8)
        report = await stack.diagnostics()
        gate = {item["key"]: item for item in _station(report, "FeedLift")["gate"]}
        self.assertTrue(gate["proximity"]["value"])
        self.assertIn("8 张", gate["proximity"]["because"])

    async def _check_unreadable_is_not_false(self, stack) -> None:
        """读不到的量给 None 而不是 False —— 画成"不满足"会把人引到错地方查."""
        stack.material_store.set_magazine("waste", 5)
        await stack.executor.execute("feedlift.unload_ready", {}, current_mode="DEBUG")
        report = await stack.diagnostics()
        gate = {item["key"]: item for item in _station(report, "FeedLift")["gate"]}
        self.assertIsNone(gate["out_sensor"]["value"],
                          "下料出料传感器是 PLC 内部量, 必须给 None 不是 False")
        self.assertIn("PLC 内部量", gate["out_sensor"]["because"])
        self.assertIsNotNone(gate["alarm"]["value"], "Alarm 有推定值, 不该是 None")
        self.assertIn("推定", gate["alarm"]["because"], "推定必须自报是推定")

    async def _check_sensor_bits_match_bytes(self, stack) -> None:
        await asyncio.sleep(0.3)
        report = await stack.diagnostics()
        sensors = report["sensors"]
        for entry in sensors["bits"]:
            raw = int(await mock_read(stack.server, entry["byte"]))
            self.assertEqual(entry["on"], bool(raw >> entry["bit"] & 1),
                             f"位 {entry['name']} 与字节不符 —— 观测面自己解了一套")
            self.assertTrue(entry["source"], "每一位都要说清由什么推导")
        self.assertEqual(sensors["bytes"]["IX11"]["value"], 0)
        self.assertTrue(sensors["constant_zero"], "恒 0 的位段要如实点名与给依据")

    async def _check_feedlift_block(self, stack) -> None:
        stack.material_store.set_magazine("feed", 11)
        await asyncio.sleep(0.2)
        report = await stack.diagnostics()
        feed = report["feedlift"]["feed"]
        self.assertEqual(feed["count"], 11)
        self.assertEqual(feed["capacity"], 30)
        self.assertTrue(feed["proximity"])
        self.assertIsNotNone(feed["z_trigger_mm"])
        self.assertEqual(feed["calibration_source"], "simulation_fixture")
        self.assertIsNotNone(feed["z_mm"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
