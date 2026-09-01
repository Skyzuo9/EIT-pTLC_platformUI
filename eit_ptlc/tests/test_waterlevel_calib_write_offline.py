"""液位标定/参数写入上位机离线测试 (P3.2)
============================================
功能:
    验证 WaterLevelDetectService 的标定/参数写入 (取代香橙派 set_roi/set_calibration MQTT):
      - update_roi/update_calibration/update_params → 内存生效 + 持久化到 calib_path
      - get_params 返回含 flow_direction
      - ROI/标定变更 → 参考图失效 (清 _refs, 强制重抓)
      - clear_roi → roi_bbox=None

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_write_offline
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
        save_channel_configs(cfg_path, {
            1: ChannelConfig(
                ChannelCalibration(0.0, (50, 50, 200, 100), "left_to_right"),
                WaterLevelDetectParams()),
        })
        svc = WaterLevelDetectService("127.0.0.1", 0, cfg_path)

        # ---- update_roi → 内存 + 持久化 ----
        svc.update_roi(1, 60, 60, 100, 80)
        check("roi_in_memory", svc.get_config(1).calib.roi_bbox == (60, 60, 100, 80),
              str(svc.get_config(1).calib.roi_bbox))
        reloaded = load_channel_configs(cfg_path)
        check("roi_persisted", reloaded[1].calib.roi_bbox == (60, 60, 100, 80),
              str(reloaded[1].calib.roi_bbox))

        # ---- update_params (含 flow_direction → calib) ----
        svc.update_params(1, {"wet_pixel_threshold": 9.0, "blur_ksize": 7,
                              "flow_direction": "right_to_left"})
        c1 = svc.get_config(1)
        check("param_diff", abs(c1.params.wet_pixel_threshold - 9.0) < 1e-6, str(c1.params.wet_pixel_threshold))
        check("param_blur_int", c1.params.blur_ksize == 7 and isinstance(c1.params.blur_ksize, int),
              str(type(c1.params.blur_ksize)))
        check("param_flow_to_calib", c1.calib.flow_direction == "right_to_left", c1.calib.flow_direction)

        # ---- get_params 返回含 flow_direction ----
        p = svc.get_params(1)
        check("get_params", p.get("wet_pixel_threshold") == 9.0 and p.get("flow_direction") == "right_to_left",
              str(p))

        # ---- 参考图失效: ROI 变更清 _refs ----
        svc._refs[1] = "fake_ref"
        svc.update_roi(1, 0, 0, 40, 40)
        check("roi_invalidates_ref", 1 not in svc._refs, str(list(svc._refs.keys())))

        # ---- update_calibration (旋转+ROI+流向) ----
        svc.update_calibration(2, rotation_angle_deg=3.5, roi_bbox=[10, 10, 50, 50],
                               flow_direction="bottom_to_top")
        c2 = svc.get_config(2)
        check("calib_rotation", abs(c2.calib.rotation_angle_deg - 3.5) < 1e-6,
              str(c2.calib.rotation_angle_deg))
        check("calib_roi", c2.calib.roi_bbox == (10, 10, 50, 50), str(c2.calib.roi_bbox))
        check("calib_flow", c2.calib.flow_direction == "bottom_to_top", c2.calib.flow_direction)
        check("calib_now_calibrated", c2.calib.calibrated, "")

        # ---- dry_ref_frac 三态: 设置 / 缺省保持 / None 清除 (哨兵语义) ----
        svc.update_calibration(2, dry_ref_frac=[0.02, 0.1, 0.13, 0.8])
        c2 = svc.get_config(2)
        check("dry_set", c2.calib.dry_ref_frac == (0.02, 0.1, 0.13, 0.8),
              str(c2.calib.dry_ref_frac))
        check("get_calib_exposes_dry",
              svc.get_calibration(2).get("dry_ref_frac") == [0.02, 0.1, 0.13, 0.8],
              str(svc.get_calibration(2)))
        reloaded = load_channel_configs(cfg_path)
        check("dry_persisted", reloaded[2].calib.dry_ref_frac == (0.02, 0.1, 0.13, 0.8),
              str(reloaded[2].calib.dry_ref_frac))
        svc.update_calibration(2, rotation_angle_deg=1.0)   # 不带 dry 参 → 现值保持
        check("dry_kept_when_absent",
              svc.get_config(2).calib.dry_ref_frac == (0.02, 0.1, 0.13, 0.8),
              str(svc.get_config(2).calib.dry_ref_frac))
        svc._refs[2] = "fake_ref2"
        svc.update_calibration(2, dry_ref_frac=None)        # 显式 None → 清除 + 参考失效
        check("dry_cleared", svc.get_config(2).calib.dry_ref_frac is None,
              str(svc.get_config(2).calib.dry_ref_frac))
        check("dry_change_invalidates_ref", 2 not in svc._refs, str(list(svc._refs.keys())))
        reloaded = load_channel_configs(cfg_path)
        check("dry_clear_persisted", reloaded[2].calib.dry_ref_frac is None,
              str(reloaded[2].calib.dry_ref_frac))

        # ---- clear_roi → None ----
        svc.clear_roi(1)
        check("clear_roi", svc.get_config(1).calib.roi_bbox is None,
              str(svc.get_config(1).calib.roi_bbox))

    total = 19
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
