"""液位标定持久化离线测试
==========================
功能:
    验证 controller/waterlevel_store:
      - 香橙派格式加载 (嵌套 calibration/roi_manual/detect_params → ChannelCalibration)
      - auto 模式通道 (无 roi_manual) → roi_bbox=None
      - 原生格式 save → reload round-trip 一致
      - 文件不存在 → 空 dict; default_configs 8 通道 + 流向约定

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_store_offline
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from eit_ptlc.controller.waterlevel_detector import ChannelCalibration, WaterLevelDetectParams
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    default_configs,
    load_channel_configs,
    save_channel_configs,
)

# 香橙派 water_level_config.json 样例 (CH1 手动 ROI, CH5 auto 无 roi_manual)
_ORANGEPI = {
    "1": {
        "detect_params": {
            "flow_direction": "right_to_left",
            "roi_crop_x": 0.12, "roi_crop_y": 0.08,
            "water_blur_ksize": 7, "water_diff_threshold": 6.0,
        },
        "calibration": {"rotation_angle_deg": 2.5, "scale_factor": 0.01, "qr_id": "tank1"},
        "roi_manual": {"x": 100, "y": 50, "w": 200, "h": 150, "reference_y": 50},
    },
    "5": {
        "detect_params": {"flow_direction": "left_to_right"},
        "calibration": {"rotation_angle_deg": -1.0},
    },
}


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # ---- 香橙派格式加载 ----
        opi_path = td / "water_level_config.json"
        opi_path.write_text(json.dumps(_ORANGEPI), encoding="utf-8")
        cfgs = load_channel_configs(opi_path)
        check("opi_loaded_2ch", set(cfgs.keys()) == {1, 5}, str(sorted(cfgs.keys())))

        c1 = cfgs.get(1)
        check("opi_ch1_rotation", c1 is not None and abs(c1.calib.rotation_angle_deg - 2.5) < 1e-6,
              None if c1 is None else str(c1.calib.rotation_angle_deg))
        check("opi_ch1_roi", c1 is not None and c1.calib.roi_bbox == (100, 50, 200, 150),
              None if c1 is None else str(c1.calib.roi_bbox))
        check("opi_ch1_flow", c1 is not None and c1.calib.flow_direction == "right_to_left",
              None if c1 is None else c1.calib.flow_direction)
        check("opi_ch1_params_mapped",
              c1 is not None and abs(c1.params.roi_crop_x - 0.12) < 1e-6
              and c1.params.blur_ksize == 7,
              None if c1 is None else str(c1.params))
        check("opi_ch1_calibrated", c1 is not None and c1.calib.calibrated, "")

        # ---- auto 模式 (无 roi_manual) → roi_bbox=None ----
        c5 = cfgs.get(5)
        check("opi_ch5_no_roi", c5 is not None and c5.calib.roi_bbox is None,
              None if c5 is None else str(c5.calib.roi_bbox))
        check("opi_ch5_uncalibrated", c5 is not None and not c5.calib.calibrated, "")

        # ---- 原生格式 round-trip ----
        native_path = td / "upper_calib.json"
        save_channel_configs(native_path, cfgs)
        reloaded = load_channel_configs(native_path)
        r1 = reloaded.get(1)
        check("roundtrip_ch1_roi", r1 is not None and r1.calib.roi_bbox == (100, 50, 200, 150),
              None if r1 is None else str(r1.calib.roi_bbox))
        check("roundtrip_ch1_rotation",
              r1 is not None and abs(r1.calib.rotation_angle_deg - 2.5) < 1e-6, "")
        check("roundtrip_ch1_params",
              r1 is not None and r1.params.blur_ksize == 7, "")
        r5 = reloaded.get(5)
        check("roundtrip_ch5_no_roi", r5 is not None and r5.calib.roi_bbox is None, "")

        # ---- 文件不存在 → 空 ----
        check("missing_file_empty", load_channel_configs(td / "nope.json") == {}, "")

    # ---- dry_ref_frac / front_gap_frac / log 域三字段 往返保真 ----
    cfg_rt = ChannelConfig(
        calib=ChannelCalibration(rotation_angle_deg=1.0, roi_frac=(0.1, 0.0, 0.2, 1.0),
                                 flow_direction="right_to_left",
                                 dry_ref_frac=(0.02, 0.10, 0.13, 0.80)),
        params=WaterLevelDetectParams(front_gap_frac=0.22, separation_mode="abs",
                                      wet_rel_threshold=0.07, front_ratio_level=0.42))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "rt.json"
        save_channel_configs(p, {3: cfg_rt})
        back = load_channel_configs(p)[3]
    check("dry_ref_frac_roundtrip", back.calib.dry_ref_frac == (0.02, 0.10, 0.13, 0.80),
          f"got={back.calib.dry_ref_frac}")
    check("front_gap_frac_roundtrip", abs(back.params.front_gap_frac - 0.22) < 1e-9,
          f"got={back.params.front_gap_frac}")
    check("log_fields_roundtrip",
          back.params.separation_mode == "abs"
          and abs(back.params.wet_rel_threshold - 0.07) < 1e-9
          and abs(back.params.front_ratio_level - 0.42) < 1e-9,
          f"mode={back.params.separation_mode} k={back.params.wet_rel_threshold} "
          f"front_lvl={back.params.front_ratio_level}")
    # 旧盘文件缺三新字段 → 默认 log 口径 (r1 来自香橙派格式往返, 无新字段)
    check("legacy_file_defaults_log",
          r1 is not None and r1.params.separation_mode == "log"
          and abs(r1.params.wet_rel_threshold - 0.05) < 1e-9,
          None if r1 is None else f"mode={r1.params.separation_mode}")
    # 非法 separation_mode → 回退默认 (防手改盘文件打进未知分支)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bad_mode.json"
        save_channel_configs(p, {2: cfg_rt})
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["2"]["params"]["separation_mode"] = "banana"
        p.write_text(json.dumps(doc), encoding="utf-8")
        back_bad = load_channel_configs(p)[2]
    check("invalid_mode_falls_back", back_bad.params.separation_mode == "log",
          f"got={back_bad.params.separation_mode}")

    # ---- default_configs ----
    d = default_configs()
    check("default_8ch", len(d) == 8 and set(d.keys()) == set(range(1, 9)), str(sorted(d.keys())))
    check("default_flow_group1", all(d[c].calib.flow_direction == "right_to_left" for c in (1, 2, 3, 4)), "")
    check("default_flow_group2", all(d[c].calib.flow_direction == "left_to_right" for c in (5, 6, 7, 8)), "")
    check("default_uncalibrated", all(not d[c].calib.calibrated for c in range(1, 9)), "")

    # ---- 默认配置按侧预置干区 ----
    check("default_dry_left", d[3].calib.dry_ref_frac == (0.02, 0.10, 0.13, 0.80),
          f"ch3={d[3].calib.dry_ref_frac}")
    check("default_dry_right", d[8].calib.dry_ref_frac == (0.78, 0.15, 0.10, 0.70),
          f"ch8={d[8].calib.dry_ref_frac}")

    total = 23
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
