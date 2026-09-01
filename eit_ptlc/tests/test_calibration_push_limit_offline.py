#!/usr/bin/env python3
"""push_well 软限位离线测试 (#1 越程拒发)
======================================
功能:
    CalibrationService.push_well 写 *_Target 前对算得的 X/Y 做软限位校验:
      - 边角孔越程 → 抛 ValueError 且**零写入** (不写 X 也不写 Y, 不静默 clamp);
      - 孔在限位内 → 正常写两轴;
      - 未注入限位 (None) → 退化为不校验 (保留旧行为, 仅告警)。
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.calibration_service import CalibrationService  # noqa: E402
from eit_ptlc.controller.plate_affine import Well  # noqa: E402
from eit_ptlc.controller.plate_catalog import PlateCatalog  # noqa: E402

_CFG = _PKG / "config"

# 轴对齐 24孔标定: X 跨度约 139.3..235.8, Y 约 74.3..132.2
_CALIBRATED_YAML = """\
version: 1
instances:
  - id: sampling_plate_1
    label: "上样板1"
    plate_type: "24-well"
    points:
      - {well: [1, 1], x_mm: 139.3, y_mm: 74.3}
      - {well: [1, 6], x_mm: 235.8, y_mm: 74.3}
      - {well: [4, 1], x_mm: 139.3, y_mm: 132.2}
"""


class _RecordingDriver:
    """记录所有 write_variable 调用 (校验零写入)。"""

    def __init__(self) -> None:
        self.writes: list[tuple[str, float]] = []

    async def write_variable(self, name: str, value) -> None:
        self.writes.append((name, float(value)))


def _catalog(tmp: Path) -> PlateCatalog:
    (tmp / "calibration.yaml").write_text(_CALIBRATED_YAML, encoding="utf-8")
    return PlateCatalog.load(_CFG / "plates.yaml", tmp / "calibration.yaml")


class PushLimitTests(unittest.TestCase):
    def test_off_range_rejected_zero_write(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cat = _catalog(Path(d))
            drv = _RecordingDriver()
            # X 限位收到 150 → Well(1,6) 的 X=235.8 越程
            svc = CalibrationService(cat, drv, Path(d) / "calibration.yaml",
                                     x_limits=(0.0, 150.0), y_limits=(0.0, 500.0))
            with self.assertRaises(ValueError):
                asyncio.run(svc.push_well("sampling_plate_1", Well(1, 6)))  # A6: row1,col6 → X≈235.8
            self.assertEqual(drv.writes, [])  # 零写入: 未写 X 也未写 Y

    def test_in_range_writes_both(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cat = _catalog(Path(d))
            drv = _RecordingDriver()
            svc = CalibrationService(cat, drv, Path(d) / "calibration.yaml",
                                     x_limits=(0.0, 500.0), y_limits=(0.0, 500.0))
            x, y = asyncio.run(svc.push_well("sampling_plate_1", Well(1, 1)))  # A1
            self.assertAlmostEqual(x, 139.3, places=3)
            self.assertEqual([n for n, _ in drv.writes],
                             ["Sampling_4X_Target", "Sampling_3Y_Target"])

    def test_no_limits_falls_back_no_check(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cat = _catalog(Path(d))
            drv = _RecordingDriver()
            svc = CalibrationService(cat, drv, Path(d) / "calibration.yaml")  # 不注入限位
            asyncio.run(svc.push_well("sampling_plate_1", Well(1, 6)))  # 越程也照写 (旧行为)
            self.assertEqual(len(drv.writes), 2)


if __name__ == "__main__":
    unittest.main()
