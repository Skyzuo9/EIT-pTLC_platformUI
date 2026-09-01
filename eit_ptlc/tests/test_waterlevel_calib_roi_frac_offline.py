"""液位标定 roi_frac 写入/持久化离线测试
============================================
验证 update_calibration(roi_frac=...) → 设 calib.roi_frac + 清 roi_bbox + 持久化往返一致。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_roi_frac_offline
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from eit_ptlc.controller.waterlevel_detector import ChannelCalibration, WaterLevelDetectParams
from eit_ptlc.controller.waterlevel_service import WaterLevelDetectService
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    load_channel_configs,
    save_channel_configs,
)


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "calib.json"
        # 起始: 通道 3 只有旧像素 bbox
        save_channel_configs(cfg_path, {
            3: ChannelConfig(
                ChannelCalibration(0.0, (50, 50, 200, 100), "left_to_right"),
                WaterLevelDetectParams()),
        })
        svc = WaterLevelDetectService("127.0.0.1", 0, cfg_path)

        # roi_frac 写入: 设 frac + 清 bbox + 存旋转/流向
        ok = svc.update_calibration(
            3, rotation_angle_deg=1.7,
            roi_frac=[0.53, 0.0, 0.20, 1.0], flow_direction="left_to_right")
        c = svc.get_config(3)
        check("returns_true", ok is True, str(ok))
        check("frac_set", c.calib.roi_frac == (0.53, 0.0, 0.20, 1.0), str(c.calib.roi_frac))
        check("bbox_cleared", c.calib.roi_bbox is None, str(c.calib.roi_bbox))
        check("rotation_set", abs(c.calib.rotation_angle_deg - 1.7) < 1e-6, str(c.calib.rotation_angle_deg))
        check("calibrated", c.calib.calibrated, "")

        # 持久化往返一致
        reloaded = load_channel_configs(cfg_path)
        check("frac_persisted", reloaded[3].calib.roi_frac == (0.53, 0.0, 0.20, 1.0),
              str(reloaded[3].calib.roi_frac))
        check("bbox_persisted_none", reloaded[3].calib.roi_bbox is None,
              str(reloaded[3].calib.roi_bbox))

        # 改标定使参考图失效
        svc._refs[3] = "fake_ref"
        svc.update_calibration(3, roi_frac=[0.1, 0.1, 0.2, 0.2])
        check("frac_invalidates_ref", 3 not in svc._refs, str(list(svc._refs.keys())))

        # ---- get_calibration 回读当前标定 (供前端标定面板 seed) ----
        svc.update_calibration(3, rotation_angle_deg=2.5,
                               roi_frac=[0.5, 0.1, 0.2, 0.8], flow_direction="right_to_left")
        gc = svc.get_calibration(3)
        check("getcalib_rotation", abs(gc.get("rotation_angle_deg") - 2.5) < 1e-6, str(gc))
        check("getcalib_frac", gc.get("roi_frac") == [0.5, 0.1, 0.2, 0.8], str(gc.get("roi_frac")))
        check("getcalib_flow", gc.get("flow_direction") == "right_to_left", str(gc.get("flow_direction")))
        check("getcalib_calibrated", gc.get("calibrated") is True, str(gc.get("calibrated")))
        check("getcalib_missing_empty", svc.get_calibration(999) == {}, str(svc.get_calibration(999)))

    total = 13
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return _run()


if __name__ == "__main__":
    sys.exit(main())
