"""液位配置分层网关 + CLI 看板离线测试
========================================
覆盖: split_tiers/derive_roi_frac (frac↔px 金标准) / merge_tiers (往返+退化守卫) /
      audit (严格多数/无共识, 真源 h 漂移金标准) / apply_commit (按层过滤/广播) /
      wl_config_board (只读渲染/dry-run/备份失败中止/广播写) / wl_replay_tune 存盘提示。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline
    或 (随套件)  & "E:/Anaconda/envs/platformupper/python.exe" -m pytest eit_ptlc/tests/test_waterlevel_config_tiers_offline.py -q
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    WaterLevelDetectParams,
)
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    load_channel_configs,
    save_channel_configs,
)


def _real_snapshot() -> dict[int, ChannelConfig]:
    """water_level_calib.json 快照 (2026-07-10); 参数均为检测器默认。
    用作金标准且与可变真源文件解耦 (frac 是真源, split_tiers 只读 frac, 故 roi_bbox 略)。"""
    rows = {
        1: (0.8665927624189634, "right_to_left", (0.10155, 0.006766, 0.103101, 0.537212)),
        2: (-0.6962686000719428, "right_to_left", (0.072981, 0.014966, 0.103261, 0.522449)),
        3: (-0.0, "right_to_left", (0.078125, 0.0, 0.103906, 0.55)),
        4: (0.5926938186167044, "right_to_left", (0.0777, 0.0, 0.103341, 0.527967)),
        5: (1.6560493162756562, "left_to_right", (0.205385, 0.0, 0.102308, 0.518519)),
        6: (0.5856264148077176, "left_to_right", (0.207459, 0.0, 0.103341, 0.534789)),
        7: (1.1632062452411367, "left_to_right", (0.206337, 0.0, 0.102782, 0.526174)),
        8: (-0.1932396703826922, "left_to_right", (0.208268, 0.001381, 0.103744, 0.541436)),
    }
    out: dict[int, ChannelConfig] = {}
    for ch, (rot, flow, frac) in rows.items():
        out[ch] = ChannelConfig(
            ChannelCalibration(rot, None, flow, frac), WaterLevelDetectParams())
    return out


def _run() -> int:
    results = {"pass": 0}
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            results["pass"] += 1
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # ============================ Task 1: split_tiers / derive_roi_frac ============================
    from eit_ptlc.controller.waterlevel_config_tiers import (
        REFERENCE_CAPTURE, split_tiers, derive_roi_frac,
    )
    ch1 = ChannelConfig(
        ChannelCalibration(0.8665927624189634, None, "right_to_left",
                           (0.10155, 0.006766, 0.103101, 0.537212)),
        WaterLevelDetectParams())
    ch5 = ChannelConfig(
        ChannelCalibration(1.6560493162756562, None, "left_to_right",
                           (0.205385, 0.0, 0.102308, 0.518519)),
        WaterLevelDetectParams())

    t1 = split_tiers(ch1)
    check("split_ch1_size", t1.size_px == (133, 397), str(t1.size_px))
    check("split_ch1_xy", t1.pose.xy_px == (131, 5), str(t1.pose.xy_px))
    check("split_ch1_flow", t1.pose.flow == "right_to_left", t1.pose.flow)
    check("split_ch1_rot", abs(t1.pose.rotation_deg - 0.8665927624189634) < 1e-9, str(t1.pose.rotation_deg))
    check("split_ch1_judgment", t1.judgment.wet_pixel_threshold == 5.0, str(t1.judgment.wet_pixel_threshold))

    t5 = split_tiers(ch5)
    check("split_ch5_size", t5.size_px == (133, 392), str(t5.size_px))
    check("split_ch5_xy", t5.pose.xy_px == (267, 0), str(t5.pose.xy_px))

    f1 = derive_roi_frac(0.8665927624189634, (131, 5), (133, 397))
    exp1 = (0.10155, 0.006766, 0.103101, 0.537212)
    check("derive_ch1_frac", max(abs(a - b) for a, b in zip(f1, exp1)) < 1e-4, f"{f1} vs {exp1}")

    unc = ChannelConfig(ChannelCalibration(0.0, None, "bottom_to_top", None), WaterLevelDetectParams())
    tu = split_tiers(unc)
    check("split_uncalib_size_none", tu.size_px is None, str(tu.size_px))
    check("split_uncalib_xy_none", tu.pose.xy_px is None, str(tu.pose.xy_px))
    check("split_uncalib_flow_kept", tu.pose.flow == "bottom_to_top", tu.pose.flow)

    # ============================ Task 2: merge_tiers 往返 + 守卫 ============================
    from eit_ptlc.controller.waterlevel_config_tiers import merge_tiers, Pose
    for ch, cfg in _real_snapshot().items():
        a = split_tiers(cfg)
        merged = merge_tiers(a.judgment, a.size_px, a.pose)
        b = split_tiers(merged)
        check(f"roundtrip_ch{ch}_size", a.size_px == b.size_px, f"{a.size_px} != {b.size_px}")
        check(f"roundtrip_ch{ch}_xy", a.pose.xy_px == b.pose.xy_px, f"{a.pose.xy_px} != {b.pose.xy_px}")
    m1 = merge_tiers(WaterLevelDetectParams(), (133, 397),
                     Pose(0.8665927624189634, "right_to_left", (131, 5)))
    check("merge_bbox_materialized", m1.calib.roi_bbox == (131, 5, 133, 397), str(m1.calib.roi_bbox))
    check("merge_frac_set", m1.calib.roi_frac is not None, "")

    def _raises_value(fn) -> bool:
        try:
            fn()
            return False
        except ValueError:
            return True

    check("merge_degenerate_w0",
          _raises_value(lambda: merge_tiers(WaterLevelDetectParams(), (0, 50),
                                            Pose(0.0, "left_to_right", (10, 10)))), "")
    check("merge_out_of_bounds",
          _raises_value(lambda: merge_tiers(WaterLevelDetectParams(), (100, 50),
                                            Pose(0.0, "left_to_right", (1270, 10)))), "")
    mu = merge_tiers(WaterLevelDetectParams(), None, Pose(2.0, "bottom_to_top", None))
    check("merge_uncalib_frac_none", mu.calib.roi_frac is None, str(mu.calib.roi_frac))
    check("merge_uncalib_flow", mu.calib.flow_direction == "bottom_to_top", mu.calib.flow_direction)

    # ============================ Task 3: audit 一致性判据 ============================
    from eit_ptlc.controller.waterlevel_config_tiers import audit
    rep = audit(_real_snapshot())
    fa = {f.field: f for f in rep.fields}
    check("audit_w_consistent", fa["w"].consistent and fa["w"].expected == 133, str(fa["w"]))
    check("audit_h_inconsistent", not fa["h"].consistent, str(fa["h"]))
    check("audit_h_no_consensus", fa["h"].expected is None, str(fa["h"].expected))
    check("audit_h_values_8", len(fa["h"].values) == 8, str(fa["h"].values))
    check("audit_judgment_consistent",
          fa["wet_pixel_threshold"].consistent and fa["wet_pixel_threshold"].expected == 5.0, str(fa["wet_pixel_threshold"]))
    check("audit_no_uncalibrated", rep.uncalibrated == [], str(rep.uncalibrated))

    synth: dict[int, ChannelConfig] = {}
    hs = {1: 392, 2: 392, 3: 392, 4: 392, 5: 392, 6: 380, 7: 381, 8: 382}
    for ch, cfg in _real_snapshot().items():
        tv = split_tiers(cfg)
        synth[ch] = merge_tiers(tv.judgment, (tv.size_px[0], hs[ch]), tv.pose)
    fh = {f.field: f for f in audit(synth).fields}["h"]
    check("audit_majority_expected", fh.expected == 392, str(fh.expected))
    check("audit_majority_deviants", sorted(fh.deviants) == [6, 7, 8], str(fh.deviants))

    snap2 = _real_snapshot()
    snap2[3] = ChannelConfig(ChannelCalibration(0.0, None, "right_to_left", None), WaterLevelDetectParams())
    rep3 = audit(snap2)
    check("audit_uncalib_listed", rep3.uncalibrated == [3], str(rep3.uncalibrated))
    fh3 = {f.field: f for f in rep3.fields}["h"]
    check("audit_uncalib_excluded", 3 not in fh3.values, str(fh3.values))

    # ============================ Task 4: apply_commit 按层过滤 + 广播 ============================
    from eit_ptlc.controller.waterlevel_config_tiers import apply_commit
    base = _real_snapshot()
    tv5 = split_tiers(base[5])
    tuned5 = merge_tiers(tv5.judgment, tv5.size_px, Pose(9.9, "left_to_right", (300, 40)))

    r_nopose = apply_commit(base, 5, tuned5, broadcast_global=False, with_pose=False)
    o5 = split_tiers(base[5]); n5 = split_tiers(r_nopose[5])
    check("commit_pose_filtered_xy", n5.pose.xy_px == o5.pose.xy_px, f"{n5.pose.xy_px} vs {o5.pose.xy_px}")
    check("commit_pose_filtered_rot", abs(n5.pose.rotation_deg - o5.pose.rotation_deg) < 1e-9, str(n5.pose.rotation_deg))

    r_pose = apply_commit(base, 5, tuned5, broadcast_global=False, with_pose=True)
    n5p = split_tiers(r_pose[5])
    check("commit_with_pose_xy", n5p.pose.xy_px == (300, 40), str(n5p.pose.xy_px))
    check("commit_with_pose_rot", abs(n5p.pose.rotation_deg - 9.9) < 1e-9, str(n5p.pose.rotation_deg))

    r_bc = apply_commit(base, 5, base[5], broadcast_global=True, with_pose=False)
    sizes = {ch: split_tiers(cfg).size_px for ch, cfg in r_bc.items()}
    check("broadcast_all_size", all(s == (133, 392) for s in sizes.values()), str(sizes))
    pos_kept = all(split_tiers(r_bc[ch]).pose.xy_px == split_tiers(base[ch]).pose.xy_px for ch in r_bc)
    check("broadcast_pos_kept", pos_kept, "")
    fh_bc = {f.field: f for f in audit(r_bc).fields}["h"]
    check("broadcast_h_consistent", fh_bc.consistent and fh_bc.expected == 392, str(fh_bc))
    fh_fracs = {ch: cfg.calib.roi_frac[3] for ch, cfg in r_bc.items()}
    check("broadcast_fracs_differ", len({round(f, 6) for f in fh_fracs.values()}) > 1, str(fh_fracs))

    base_u = _real_snapshot()
    base_u[3] = ChannelConfig(ChannelCalibration(0.0, None, "right_to_left", None),
                              WaterLevelDetectParams(wet_pixel_threshold=1.0))
    r_u = apply_commit(base_u, 5, base_u[5], broadcast_global=True, with_pose=False)
    check("broadcast_uncalib_still_uncalib", r_u[3].calib.roi_frac is None, str(r_u[3].calib.roi_frac))
    check("broadcast_uncalib_judgment_updated",
          r_u[3].params.wet_pixel_threshold == base_u[5].params.wet_pixel_threshold, str(r_u[3].params.wet_pixel_threshold))

    tuned_noroi = ChannelConfig(ChannelCalibration(0.0, None, "left_to_right", None), WaterLevelDetectParams())
    check("commit_tuned_no_roi_raises",
          _raises_value(lambda: apply_commit(base, 5, tuned_noroi, broadcast_global=False, with_pose=False)), "")

    # ============================ Task 5: 看板只读渲染 ============================
    from eit_ptlc.tools import wl_config_board as board
    lines = board.render_report(_real_snapshot())
    text = "\n".join(lines)
    check("board_h_flagged", any("✗" in l and "无共识" in l for l in lines), text)
    check("board_w_ok", any(l.lstrip().startswith("w ") and "一致" in l for l in lines), text)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "calib.json"
        save_channel_configs(p, _real_snapshot())
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = board.cmd_show(p)
        check("board_show_rc0", rc == 0, str(rc))
        check("board_show_prints", "液位配置看板" in buf.getvalue(), "")
        missing = Path(td) / "nope.json"

    def _show_missing_exits() -> bool:
        try:
            board.load_true_source(missing)   # td 已删, 文件必不存在
            return False
        except SystemExit:
            return True
    check("board_missing_source_exits", _show_missing_exits(), "")

    # ============================ Task 6: 看板提交/广播 (备份前置/dry-run) ============================
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "calib.json"
        save_channel_configs(src, _real_snapshot())
        tuned_p = Path(td) / "ch5.tuned.json"
        save_channel_configs(tuned_p, {5: _real_snapshot()[5]})
        before = src.read_bytes()

        with contextlib.redirect_stdout(io.StringIO()):
            rc = board.cmd_commit(src, tuned_p, broadcast=True, with_pose=False,
                                  dry_run=True, yes=True, now="T")
        check("commit_dryrun_rc0", rc == 0, str(rc))
        check("commit_dryrun_no_write", src.read_bytes() == before, "src changed on dry-run")
        check("commit_dryrun_no_backup", not (Path(td) / "calib.T.bak.json").exists(), "backup on dry-run")

        orig_copy = board.shutil.copy2
        board.shutil.copy2 = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = board.cmd_commit(src, tuned_p, broadcast=True, with_pose=False,
                                      dry_run=False, yes=True, now="BK")
        finally:
            board.shutil.copy2 = orig_copy
        check("commit_backup_fail_rc3", rc == 3, str(rc))
        check("commit_backup_fail_no_write", src.read_bytes() == before, "src changed despite backup fail")

        with contextlib.redirect_stdout(io.StringIO()):
            rc = board.cmd_commit(src, tuned_p, broadcast=True, with_pose=False,
                                  dry_run=False, yes=False, now="NO", confirm=lambda _p: "n")
        check("commit_cancelled_rc1", rc == 1, str(rc))
        check("commit_cancelled_no_write", src.read_bytes() == before, "src changed on cancel")

        with contextlib.redirect_stdout(io.StringIO()):
            rc = board.cmd_commit(src, tuned_p, broadcast=True, with_pose=False,
                                  dry_run=False, yes=True, now="OK")
        check("commit_ok_rc0", rc == 0, str(rc))
        check("commit_ok_backup", (Path(td) / "calib.OK.bak.json").exists(), "no backup")
        fh_after = {f.field: f for f in audit(load_channel_configs(src)).fields}["h"]
        check("commit_ok_h_consistent", fh_after.consistent and fh_after.expected == 392, str(fh_after))

        bad = Path(td) / "bad.tuned.json"
        save_channel_configs(bad, {0: _real_snapshot()[5]})
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = board.cmd_commit(src, bad, broadcast=False, with_pose=False,
                                  dry_run=False, yes=True, now="X")
        check("commit_bad_channel_rc2", rc == 2, str(rc))

    # ============================ Task 4-brief: dry_frac 穿层 + front_gap_frac 收编 ============================
    from eit_ptlc.controller.waterlevel_config_tiers import GLOBAL_JUDGMENT_FIELDS
    # ---- dry_frac 穿 split/merge 往返 + apply_commit 不串台 ----
    cfg_d = ChannelConfig(
        calib=ChannelCalibration(rotation_angle_deg=0.0, roi_frac=(0.2, 0.0, 0.1, 0.5),
                                 flow_direction="right_to_left",
                                 dry_ref_frac=(0.02, 0.1, 0.13, 0.8)),
        params=WaterLevelDetectParams())
    tv_d = split_tiers(cfg_d)
    check("pose_carries_dry", tv_d.pose.dry_frac == (0.02, 0.1, 0.13, 0.8),
          f"got={tv_d.pose.dry_frac}")
    back_d = merge_tiers(tv_d.judgment, tv_d.size_px, tv_d.pose)
    check("merge_keeps_dry", back_d.calib.dry_ref_frac == (0.02, 0.1, 0.13, 0.8),
          f"got={back_d.calib.dry_ref_frac}")
    # 广播判据层不得覆盖他通道自己的 dry_frac
    other = ChannelConfig(
        calib=ChannelCalibration(rotation_angle_deg=0.0, roi_frac=(0.3, 0.0, 0.1, 0.5),
                                 flow_direction="left_to_right",
                                 dry_ref_frac=(0.78, 0.15, 0.10, 0.70)),
        params=WaterLevelDetectParams())
    merged_d = apply_commit({1: cfg_d, 2: other}, 1, cfg_d,
                            broadcast_global=True, with_pose=True)
    check("broadcast_keeps_other_dry",
          merged_d[2].calib.dry_ref_frac == (0.78, 0.15, 0.10, 0.70),
          f"got={merged_d[2].calib.dry_ref_frac}")
    check("judgment_has_front_gap", "front_gap_frac" in GLOBAL_JUDGMENT_FIELDS, "")
    # log 域字段属全局·判据层 (随 'W' 广播, audit 有一致性判据)
    check("judgment_has_log_fields",
          all(k in GLOBAL_JUDGMENT_FIELDS
              for k in ("separation_mode", "wet_rel_threshold")),
          str(GLOBAL_JUDGMENT_FIELDS))
    # 广播判据层携带 separation_mode (str 字段随整个 judgment 对象落他通道)
    cfg_abs = ChannelConfig(
        calib=ChannelCalibration(rotation_angle_deg=0.0, roi_frac=(0.2, 0.0, 0.1, 0.5),
                                 flow_direction="right_to_left"),
        params=WaterLevelDetectParams(separation_mode="abs", wet_rel_threshold=0.07))
    merged_m = apply_commit({1: cfg_abs, 2: other}, 1, cfg_abs,
                            broadcast_global=True, with_pose=True)
    check("broadcast_carries_mode",
          merged_m[2].params.separation_mode == "abs"
          and abs(merged_m[2].params.wet_rel_threshold - 0.07) < 1e-9,
          f"mode={merged_m[2].params.separation_mode} k={merged_m[2].params.wet_rel_threshold}")

    total = results["pass"] + len(failures)
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def test_waterlevel_config_tiers():
    """pytest 桥: 让 `pytest eit_ptlc/tests -q` 也覆盖本文件。"""
    assert _run() == 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return _run()


if __name__ == "__main__":
    sys.exit(main())
