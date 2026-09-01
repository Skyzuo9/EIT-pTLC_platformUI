#!/usr/bin/env python3
"""伺服标定/下发服务离线测试 (对 Mock 服务器)
============================================
功能:
    用 Mock OPC UA 服务器验证 CalibrationService 全链路:
    采点(读 *_ActPos) → 提交(solve+持久化) → 算点 → 下发(写 *_Target) 读回核对。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import load_plc_nodes  # noqa: E402
from eit_ptlc.controller.calibration_service import CalibrationService  # noqa: E402
from eit_ptlc.controller.plate_affine import Well  # noqa: E402
from eit_ptlc.controller.plate_catalog import PlateCatalog, PlateCatalogError  # noqa: E402
from eit_ptlc.driver.opcua_driver import OpcUaDriver  # noqa: E402
from eit_ptlc.mock.plc_server import build_mock_server  # noqa: E402

_CFG = _PKG / "config"
_NODES = _CFG / "plc_nodes.yaml"
_URL = "opc.tcp://127.0.0.1:48493/eit_ptlc/calib_test/"

# 轴对齐 24孔 (A1/A6/D1, pitch 19.3, tx=120/ty=55) → B2 应得 (158.6, 93.6)
_TRUTH = {Well(1, 1): (139.3, 74.3), Well(1, 6): (235.8, 74.3), Well(4, 1): (139.3, 132.2)}

_CAL_YAML = """\
version: 1
instances:
  - id: sampling_plate_1
    label: "上样板1"
    plate_type: "24-well"
    points: []
"""


class CalibrationServiceTests(unittest.TestCase):
    def test_capture_commit_push_flow(self) -> None:
        asyncio.run(self._flow())

    async def _flow(self) -> None:
        node_map = load_plc_nodes(_NODES)
        server = await build_mock_server(_URL, node_map)
        async with server:
            with tempfile.TemporaryDirectory() as d:
                cal_path = Path(d) / "calibration.yaml"
                cal_path.write_text(_CAL_YAML, encoding="utf-8")
                catalog = PlateCatalog.load(_CFG / "plates.yaml", cal_path)
                driver = OpcUaDriver(_URL, node_map, reconnect_wait_timeout=5.0)
                await driver.connect()
                try:
                    svc = CalibrationService(catalog, driver, cal_path)

                    # 提交前未标定 → 下发应被拒
                    with self.assertRaises(PlateCatalogError):
                        await svc.push_well("sampling_plate_1", Well(2, 2))

                    # 采 3 点: 每点先把 *_ActPos 置成"jog 到位"的值再读
                    points = []
                    for well, (x, y) in _TRUTH.items():
                        await driver.write_variable("Sampling_4X_ActPos", x)
                        await driver.write_variable("Sampling_3Y_ActPos", y)
                        p = await svc.capture_well(well)
                        self.assertAlmostEqual(p.x_mm, x, places=3)
                        self.assertAlmostEqual(p.y_mm, y, places=3)
                        points.append(p)

                    # 提交 → 持久化, 重载后仍已标定
                    svc.commit("sampling_plate_1", points)
                    reloaded = PlateCatalog.load(_CFG / "plates.yaml", cal_path)
                    self.assertTrue(reloaded.is_calibrated("sampling_plate_1"))

                    # 算点 B2=(2,2) → (158.6, 93.6)
                    tx, ty = svc.target("sampling_plate_1", Well(2, 2))
                    self.assertAlmostEqual(tx, 158.6, places=3)
                    self.assertAlmostEqual(ty, 93.6, places=3)

                    # 下发 → 写 *_Target, 读回核对
                    px, py = await svc.push_well("sampling_plate_1", Well(2, 2))
                    self.assertAlmostEqual(px, 158.6, places=3)
                    self.assertAlmostEqual(py, 93.6, places=3)
                    rx = float(await driver.read_variable("Sampling_4X_Target"))
                    ry = float(await driver.read_variable("Sampling_3Y_Target"))
                    self.assertAlmostEqual(rx, 158.6, places=3)
                    self.assertAlmostEqual(ry, 93.6, places=3)
                finally:
                    await driver.disconnect()


if __name__ == "__main__":
    unittest.main()
