#!/usr/bin/env python3
"""gen_twin_manifest.merge_preserving 的人工字段保活门禁
=======================================================
背景 (2026-08-15 视角丢失 bug 的第二病根):
    实时页「保存视角」在 stations[].camera **内部**写 manual: true, 而
    merge_preserving 过去只认条目上的 _manual_camera sidecar 标记 —— 全仓没有
    任何写入方产生它, 于是人工机位一重跑管线就被静默冲掉。本门禁钉住两件事:
      ① camera 带内 manual: true 的工位, 重跑后保留人工机位(含 auto 备份);
      ② 没有人工标记的工位, 重跑后采用新生成值(保留逻辑不许扩大化);
      ③ 标量字段的 sidecar 形制(_manual_sign)仍然生效(轴三项的既有契约)。

运行:
    python -m pytest eit_ptlc/tests/test_manifest_merge_preserving_offline.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))
sys.path.insert(0, str(_PKG / "three_d" / "pipeline"))

from gen_twin_manifest import merge_preserving  # noqa: E402


def _station(station_id: str, camera: dict) -> dict:
    return {"id": station_id, "label": station_id, "camera": camera}


class TestMergePreserving(unittest.TestCase):
    def test_inband_manual_camera_survives(self) -> None:
        """camera.manual=true 的人工机位必须在重跑后原样存活."""
        manual_camera = {
            "pos": [1.0, 2.0, 3.0],
            "target": [0.0, 0.0, 0.0],
            "manual": True,
            "auto": {"pos": [9.0, 9.0, 9.0], "target": [0.0, 1.0, 0.0]},
        }
        generated = {"stations": [_station("RACK", {"pos": [5.0, 5.0, 5.0], "target": [0.0, 0.0, 0.0]})]}
        existing = {"stations": [_station("RACK", manual_camera)]}
        merged = merge_preserving(generated, existing)
        self.assertEqual(merged["stations"][0]["camera"], manual_camera)
        # 带内标记不需要 sidecar, 不许顺手塞一个进去污染产物
        self.assertNotIn("_manual_camera", merged["stations"][0])

    def test_unmarked_camera_takes_generated(self) -> None:
        """没有人工标记的工位必须采用新生成机位 —— 保留逻辑不许扩大化."""
        generated_camera = {"pos": [5.0, 5.0, 5.0], "target": [0.0, 0.0, 0.0]}
        generated = {"stations": [_station("PUMP", dict(generated_camera))]}
        existing = {"stations": [_station("PUMP", {"pos": [1.0, 1.0, 1.0], "target": [2.0, 2.0, 2.0]})]}
        merged = merge_preserving(generated, existing)
        self.assertEqual(merged["stations"][0]["camera"], generated_camera)

    def test_sidecar_marker_still_works_for_scalars(self) -> None:
        """轴标量字段的 _manual_<字段> sidecar 形制是既有契约, 不许被带内改法弄坏."""
        generated = {"axes": [{"id": "axis_7y", "sign": 1}]}
        existing = {"axes": [{"id": "axis_7y", "sign": -1, "_manual_sign": True}]}
        merged = merge_preserving(generated, existing)
        self.assertEqual(merged["axes"][0]["sign"], -1)
        self.assertTrue(merged["axes"][0]["_manual_sign"])


if __name__ == "__main__":
    unittest.main()
