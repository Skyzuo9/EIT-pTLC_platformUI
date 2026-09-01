"""离线单测: 液位自动排液阈值字段 (trigger_percent_t2 / t1_offset) 的参数面.

覆盖: dataclass 默认值 / store JSON 往返 / 旧文件缺字段回退默认 / service get/update_params 暴露.
运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_autodrain_params_offline
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.waterlevel_detector import WaterLevelDetectParams  # noqa: E402
from eit_ptlc.controller.waterlevel_store import (  # noqa: E402
    ChannelConfig,
    default_configs,
    load_channel_configs,
    save_channel_configs,
)


class ThresholdParamsTests(unittest.TestCase):
    def test_dataclass_defaults(self) -> None:
        p = WaterLevelDetectParams()
        self.assertEqual(p.trigger_percent_t2, 90.0)
        self.assertEqual(p.t1_offset, 15.0)

    def test_store_round_trip(self) -> None:
        cfgs = default_configs()
        cfgs[3].params.trigger_percent_t2 = 82.5
        cfgs[3].params.t1_offset = 12.0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calib.json"
            save_channel_configs(path, cfgs)
            loaded = load_channel_configs(path)
        self.assertEqual(loaded[3].params.trigger_percent_t2, 82.5)
        self.assertEqual(loaded[3].params.t1_offset, 12.0)
        # 未改的通道保持默认
        self.assertEqual(loaded[1].params.trigger_percent_t2, 90.0)

    def test_old_file_without_fields_falls_back_to_defaults(self) -> None:
        # 旧格式文件 (无新字段) 加载后回退 dataclass 默认, 不炸
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calib.json"
            path.write_text(
                '{"2": {"calib": {"rotation_angle_deg": 0.0, "roi_bbox": null, '
                '"flow_direction": "left_to_right"}, "params": {"roi_crop_x": 0.1, '
                '"roi_crop_y": 0.1, "blur_ksize": 5, '
                '"wet_pixel_threshold": 10.0, "front_ratio_level": 0.5}}}',
                encoding="utf-8")
            loaded = load_channel_configs(path)
        self.assertEqual(loaded[2].params.trigger_percent_t2, 90.0)
        self.assertEqual(loaded[2].params.t1_offset, 15.0)


class ServiceParamsSurfaceTests(unittest.TestCase):
    def _make_service(self):
        from eit_ptlc.controller.waterlevel_service import WaterLevelDetectService
        return WaterLevelDetectService("127.0.0.1", 8080, config_path=None)

    def test_get_params_exposes_thresholds(self) -> None:
        svc = self._make_service()
        params = svc.get_params(1)
        self.assertEqual(params["trigger_percent_t2"], 90.0)
        self.assertEqual(params["t1_offset"], 15.0)

    def test_update_params_sets_thresholds(self) -> None:
        svc = self._make_service()
        ok = svc.update_params(1, {"trigger_percent_t2": 75.0, "t1_offset": 10.0}, save=False)
        self.assertTrue(ok)
        params = svc.get_params(1)
        self.assertEqual(params["trigger_percent_t2"], 75.0)
        self.assertEqual(params["t1_offset"], 10.0)


class SnapshotContractTests(unittest.TestCase):
    """快照生产端契约: snapshot() 必须暴露 wait_level 消费的全部键 (终审 Important#2)。

    wait_level (waterlevel_trigger) 逐轮读 channels[ch] 的 front_percent/valid/
    reachable/observed_at; 任何一键改名/缺失都会让 auto 模式静默降级为 HITL。
    """

    def test_snapshot_exposes_keys_wait_level_consumes(self) -> None:
        from datetime import datetime, timezone

        from eit_ptlc.controller.waterlevel_detector import LevelResult
        from eit_ptlc.controller.waterlevel_service import WaterLevelDetectService

        svc = WaterLevelDetectService("127.0.0.1", 8080, config_path=None)
        svc._results[1] = LevelResult(valid=True, front_percent=37.5,
                                      wet_ratio=0.42, diff_mean=9.9, roi_size=(100, 50))
        svc._observed_at[1] = datetime.now(timezone.utc).isoformat()
        svc._reachable[1] = True
        ch = svc.snapshot()["channels"][1]
        self.assertEqual(ch["front_percent"], 37.5)
        self.assertTrue(ch["valid"])
        self.assertTrue(ch["reachable"])
        self.assertIsNotNone(ch["observed_at"])
        # observed_at 须为可解析 UTC ISO (wait_level._observed_age_s 消费)
        datetime.fromisoformat(str(ch["observed_at"]).replace("Z", "+00:00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
