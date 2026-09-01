"""液位整定台纯函数离线测试
============================
功能:
    验证 tools/wl_replay_tune 的无 GUI 纯逻辑:
      - PARAM_SPECS 标度往返 (from_pos(to_pos(v)) ≈ v) + 与旧内联公式等价
      - parse_edit_command 解析 (编号/短名/空行/非法/越界)
      - commit_to_source load-merge-save (Task 4 追加)

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline
"""

from __future__ import annotations

import sys

from eit_ptlc.tools.wl_replay_tune import (
    PARAM_SPECS,
    SPECS,
    ROTATION_KEY,
    edit_menu,
    parse_edit_command,
)


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # ---- PARAM_SPECS 标度往返 ----
    samples = {
        "diff_thr": 7.5, "wet_thr": 12.0, "front_lvl": 0.5,
        "roi_fx": 0.30, "roi_fy": 0.05, "roi_fw": 0.20, "roi_fh": 0.80,
        "crop_x": 0.12, "crop_y": 0.10, "blur_ksize": 5, "flow": 1,
    }
    for key, v in samples.items():
        s = SPECS[key]
        back = s.from_pos(s.to_pos(v))
        tol = 1.0 if s.is_int else 1.0 / 100.0 + 1e-9
        check(f"roundtrip_{key}", abs(back - v) <= tol, f"{v} -> {s.to_pos(v)} -> {back}")

    # ---- 与旧内联公式等价 (钉死 dedup 不改行为) ----
    check("eq_diff_thr", SPECS["diff_thr"].to_pos(7.5) == 75, str(SPECS["diff_thr"].to_pos(7.5)))
    check("eq_wet_thr", SPECS["wet_thr"].to_pos(12.0) == 120, str(SPECS["wet_thr"].to_pos(12.0)))
    check("eq_front_lvl", SPECS["front_lvl"].to_pos(0.5) == 50, str(SPECS["front_lvl"].to_pos(0.5)))
    check("eq_roi_fx", SPECS["roi_fx"].to_pos(0.30) == 300, str(SPECS["roi_fx"].to_pos(0.30)))
    check("eq_roi_fw_floor", SPECS["roi_fw"].from_pos(0) == 1 / 1000.0, str(SPECS["roi_fw"].from_pos(0)))
    check("eq_crop_x", SPECS["crop_x"].to_pos(0.12) == 12, str(SPECS["crop_x"].to_pos(0.12)))
    check("eq_blur", SPECS["blur_ksize"].to_pos(5) == 2 and SPECS["blur_ksize"].from_pos(2) == 5,
          f"{SPECS['blur_ksize'].to_pos(5)}/{SPECS['blur_ksize'].from_pos(2)}")

    # ---- 越界 clamp 到滑块范围 ----
    check("clamp_diff_hi", SPECS["diff_thr"].to_pos(999.0) == 500, str(SPECS["diff_thr"].to_pos(999.0)))
    check("clamp_crop_hi", SPECS["crop_x"].to_pos(9.0) == 40, str(SPECS["crop_x"].to_pos(9.0)))

    # ---- front_gap 滑块规格: 自然值 <-> 轨位互逆 ----
    sp = SPECS["front_gap"]
    check("front_gap_spec_roundtrip", abs(sp.from_pos(sp.to_pos(0.15)) - 0.15) < 1e-9,
          f"got={sp.from_pos(sp.to_pos(0.15))}")
    check("front_gap_spec_clamp", sp.to_pos(9.9) == 40, f"got={sp.to_pos(9.9)}")

    # ---- log 域三新滑块规格 (sep_mode / wet_rel / diff_log) ----
    sp = SPECS["sep_mode"]
    check("sep_mode_spec", sp.from_pos(sp.to_pos(1)) == 1 and sp.from_pos(0) == 0
          and sp.to_pos(9) == 1, f"{sp.to_pos(1)}/{sp.from_pos(1)}")
    sp = SPECS["wet_rel"]
    check("wet_rel_spec_roundtrip", abs(sp.from_pos(sp.to_pos(0.05)) - 0.05) < 1e-9,
          f"got={sp.from_pos(sp.to_pos(0.05))}")
    check("wet_rel_spec_clamp", sp.to_pos(9.9) == 200, f"got={sp.to_pos(9.9)}")
    sp = SPECS["diff_log"]
    check("diff_log_spec_roundtrip", abs(sp.from_pos(sp.to_pos(0.013)) - 0.013) < 1e-9,
          f"got={sp.from_pos(sp.to_pos(0.013))}")

    # ---- edit_menu: 0=rotation ----
    menu = edit_menu()
    check("menu_head_rotation", menu[0][0] == ROTATION_KEY, str(menu[0]))
    check("menu_len", len(menu) == 1 + len(PARAM_SPECS), str(len(menu)))

    # ---- parse_edit_command ----
    check("parse_by_index", parse_edit_command("10 7.5") == (PARAM_SPECS[9].key, 7.5),
          str(parse_edit_command("10 7.5")))
    check("parse_by_name", parse_edit_command("diff_thr 7.5") == ("diff_thr", 7.5),
          str(parse_edit_command("diff_thr 7.5")))
    check("parse_rotation", parse_edit_command("0 -3.2") == (ROTATION_KEY, -3.2),
          str(parse_edit_command("0 -3.2")))
    check("parse_empty_exit", parse_edit_command("") == (None, None), str(parse_edit_command("")))
    check("parse_q_exit", parse_edit_command("q") == (None, None), str(parse_edit_command("q")))
    k, m = parse_edit_command("foo 1")
    check("parse_unknown", k == "__error__", f"{k}/{m}")
    k, m = parse_edit_command("diff_thr abc")
    check("parse_nan", k == "__error__", f"{k}/{m}")
    k, m = parse_edit_command("diff_thr")
    check("parse_arity", k == "__error__", f"{k}/{m}")

    # ---- commit_to_source load-merge-save ----
    import tempfile
    from pathlib import Path
    from eit_ptlc.controller.waterlevel_detector import ChannelCalibration, WaterLevelDetectParams
    from eit_ptlc.controller.waterlevel_store import (
        ChannelConfig, load_channel_configs, save_channel_configs,
    )
    from eit_ptlc.tools.wl_replay_tune import commit_to_source

    def _cal(rot):
        # ROI 高 0.5 (非 0.8): commit 走离线路径时 apply_commit 会把本路像素尺寸广播到
        # 各路, 而各路 rotation 不同→旋转后画布高度不同; 0.8 高框在 rot=9.9 下派生的像素高
        # (~743px) 会溢出 rot=2 通道画布 (764px) 触发 merge_tiers 的越界守卫。0.5 使广播恒在界内,
        # 令本用例只考核 commit_to_source 的 load-merge-save, 不被跨旋转尺寸广播的边界行为干扰。
        return ChannelCalibration(rotation_angle_deg=rot, flow_direction="left_to_right",
                                  roi_frac=(0.3, 0.05, 0.2, 0.5))

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "water_level_calib.json"
        save_channel_configs(path, {
            1: ChannelConfig(calib=_cal(1.0), params=WaterLevelDetectParams()),
            2: ChannelConfig(calib=_cal(2.0), params=WaterLevelDetectParams()),
        })

        ok = commit_to_source(path, 5, _cal(5.0), WaterLevelDetectParams(), confirm=lambda: True,
                              alive=lambda: False)
        after = load_channel_configs(path)
        check("commit_add_ch5", ok and set(after.keys()) == {1, 2, 5}, str(sorted(after.keys())))
        check("commit_keep_ch2", after.get(2) is not None
              and abs(after[2].calib.rotation_angle_deg - 2.0) < 1e-6, "")

        ok2 = commit_to_source(path, 1, _cal(9.9), WaterLevelDetectParams(), confirm=lambda: True,
                               alive=lambda: False)
        after2 = load_channel_configs(path)
        check("commit_replace_ch1", ok2 and abs(after2[1].calib.rotation_angle_deg - 9.9) < 1e-6,
              str(after2[1].calib.rotation_angle_deg))
        check("commit_replace_keep_ch2", abs(after2[2].calib.rotation_angle_deg - 2.0) < 1e-6, "")

        # 取消 → 不改
        ok3 = commit_to_source(path, 7, _cal(7.0), WaterLevelDetectParams(), confirm=lambda: False,
                               alive=lambda: False)
        after3 = load_channel_configs(path)
        check("commit_cancel_noop", (ok3 is False) and (7 not in after3), str(sorted(after3.keys())))

        # 未标定 → 拒写
        ok4 = commit_to_source(path, 8, ChannelCalibration(), WaterLevelDetectParams(),
                               confirm=lambda: True, alive=lambda: False)
        after4 = load_channel_configs(path)
        check("commit_uncalibrated_refused", (ok4 is False) and (8 not in after4),
              str(sorted(after4.keys())))

    # ---- _load_initial 读回 meta 快照的 front_gap_frac + dry_ref_frac ----
    import json
    from eit_ptlc.tools.wl_replay_tune import _load_initial

    with tempfile.TemporaryDirectory() as td:
        avi = Path(td) / "clip.avi"          # 无需真存在, _load_initial 只读 meta
        meta = Path(td) / "clip.meta.json"
        meta.write_text(json.dumps({
            "calibration_snapshot": {
                "rotation_angle_deg": 0.0,
                "roi_frac": [0.30, 0.05, 0.20, 0.80],
                "dry_ref_frac": [0.02, 0.1, 0.13, 0.8],
                "flow_direction": "left_to_right",
                "calibrated": True,
                "params": {"front_gap_frac": 0.22, "wet_pixel_threshold": 8.0,
                           "separation_mode": "abs", "wet_rel_threshold": 0.07,
                           "wet_rel_threshold": 0.07},
            },
        }), encoding="utf-8")
        calib_i, params_i, _ = _load_initial(avi)
        check("load_initial_front_gap", params_i.front_gap_frac == 0.22,
              str(params_i.front_gap_frac))
        check("load_initial_dry_ref_frac", calib_i.dry_ref_frac == (0.02, 0.1, 0.13, 0.8),
              str(calib_i.dry_ref_frac))
        check("load_initial_log_fields",
              params_i.separation_mode == "abs"
              and abs(params_i.wet_rel_threshold - 0.07) < 1e-9
              and abs(params_i.wet_rel_threshold - 0.07) < 1e-9,
              f"mode={params_i.separation_mode} k={params_i.wet_rel_threshold} "
              f"k={params_i.wet_rel_threshold}")

    print(f"\n失败 {len(failures)}")
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
