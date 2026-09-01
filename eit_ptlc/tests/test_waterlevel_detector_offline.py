"""液位检测核心离线测试 (合成图, 纯函数)
=========================================
功能:
    验证 controller/waterlevel_detector 的前沿线检测 (读数真源 = front_percent):
      - 半湿 → front≈50; 全湿 → 掩膜比≈1 但判 roi_saturated (整区判湿与真·满展开
        单帧内不可分, 刻意不采信 —— T2=90 远在此之前触发, 见 analyze_front 干拖尾判据)
      - **不平整(斜)前沿 → front 仍≈平均**: profile 先沿垂直流向求均值再判定, 线性斜前沿
        的半幅穿越点就落在等效推进位置 (面积法给均值, profile 法给中位数, 线性斜时相等)
      - wet_ratio 只作掩膜诊断量断言, **不当读数** (见 LevelResult.wet_ratio)
      - 全干(=参考图) → valid=False/no_front (流入侧平台未起来)
      - 未标定 → valid=False/no_roi
      - right_to_left 方向对称; 无参考图 Otsu 回退
      - abs 旧口径回归 (有符号差分 + 加性 drift 补偿, deprecated 留 A/B)
      - **log 域乘性模型**: 阴影带相对变暗检出 (abs 漏检) / 乘性漂移 gain 补偿 /
        measure_dry_gain / dry_zone_front_percent 几何 / DryGainGuard 冻结守卫

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_detector_offline
"""

from __future__ import annotations

import math
import sys

import numpy as np

from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    DryGainGuard,
    WaterLevelDetectParams,
    compute_reference,
    detect_level,
    dry_zone_front_percent,
    measure_dry_gain,
)

# 公共标定: rotation=0 → 旋转后坐标==原图坐标; ROI=(50,50,200,100)
# crop 0.1 → 实际检测 ROI = 原图 [60:140, 70:230] (宽160 高80)
_ROI = (50, 50, 200, 100)
_DRY = 200   # 干板灰度 (亮)
_WET = 100   # 浸润灰度 (暗)
# 检测 ROI 在原图中的范围 (crop 后)
_X0, _X1, _Y0, _Y1 = 70, 230, 60, 140
_W = _X1 - _X0   # 160


def _dry_frame() -> np.ndarray:
    """全亮干板帧 (BGR)。"""
    return np.full((200, 300, 3), _DRY, np.uint8)


def _calib(direction: str = "left_to_right") -> ChannelCalibration:
    return ChannelCalibration(rotation_angle_deg=0.0, roi_bbox=_ROI,
                              flow_direction=direction)


def _run() -> int:
    failures: list[str] = []
    passed = [0]

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            passed[0] += 1
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # ================= abs 旧口径回归 (deprecated, 整定台 A/B 用) =================
    params = WaterLevelDetectParams(separation_mode="abs")
    calib = _calib("left_to_right")
    ref = compute_reference(_dry_frame(), calib, params)
    check("compute_reference", ref is not None and ref.plate_gray.shape == (_Y1 - _Y0, _W),
          f"shape={None if ref is None else ref.plate_gray.shape}")

    # ---- 半湿 (左半浸润) → percent≈50 ----
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X0 + _W // 2] = _WET     # ROI 左半涂暗
    r = detect_level(f, calib, ref=ref, params=params)
    check("half_valid", r.valid, r.reason)
    check("half_front_50", r.front_percent is not None and 45 <= r.front_percent <= 55,
          f"front={r.front_percent}")

    # ---- 不平整(斜)前沿: 顶行湿25%→底行湿75%, 面积平均仍≈50% (核心鲁棒性) ----
    f = _dry_frame()
    for i, y in enumerate(range(_Y0, _Y1)):
        frac = 0.25 + 0.5 * i / (_Y1 - _Y0 - 1)   # 0.25 → 0.75
        f[y, _X0:_X0 + int(_W * frac)] = _WET
    r = detect_level(f, calib, ref=ref, params=params)
    check("slanted_valid", r.valid, r.reason)
    check("slanted_front_50", r.front_percent is not None and 45 <= r.front_percent <= 55,
          f"front={r.front_percent} (线性斜前沿的半幅穿越点应落在~50)")

    # ---- 全湿 → ≈100 ----
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X1] = _WET
    r = detect_level(f, calib, ref=ref, params=params)
    # 掩膜仍如实算到 ~1.0, 但整区判湿 = 与"整帧照度突变"单帧内不可分 → 刻意不采信。
    # 这是 analyze_front 干拖尾判据的设计边界 (T2=90 早已触发, 生产上到不了这里)。
    check("full_mask_saturated", r.wet_ratio >= 0.95 and r.reason == "roi_saturated",
          f"wet_ratio={r.wet_ratio} reason={r.reason}")

    # ---- 全干 (=参考图) → 前沿未进 ROI ----
    r = detect_level(_dry_frame(), calib, ref=ref, params=params)
    check("dry_no_front", (not r.valid) and r.reason == "no_front",
          f"valid={r.valid} reason={r.reason} diff_mean={r.diff_mean}")

    # ---- 未标定 → no_roi ----
    r = detect_level(_dry_frame(), ChannelCalibration(), ref=None, params=params)
    check("uncalibrated_no_roi", (not r.valid) and r.reason == "no_roi", r.reason)

    # ---- right_to_left: 右半浸润 → percent≈50, front≈50 ----
    f = _dry_frame()
    f[_Y0:_Y1, _X1 - _W // 2:_X1] = _WET     # ROI 右半涂暗 (流入侧=右)
    r = detect_level(f, _calib("right_to_left"), ref=ref, params=params)
    check("r2l_front_50", r.valid and r.front_percent is not None and 45 <= r.front_percent <= 55,
          f"front={r.front_percent}")

    # ---- 无参考图 Otsu 回退: 半湿仍≈50 ----
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X0 + _W // 2] = _WET
    r = detect_level(f, calib, ref=None, params=params)
    check("otsu_front_50", r.valid and r.front_percent is not None
          and 45 <= r.front_percent <= 55, f"front={r.front_percent} (Otsu 回退)")

    # ---- 有符号差分: 变亮不算湿 ----
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X0 + _W // 2] = 250          # ROI 左半变亮 30
    r = detect_level(f, calib, ref=ref, params=params)
    # 变亮不得被算成湿; 板面实际是干的 → 前沿未进 ROI (valid=False/no_front 是正常等待态)
    check("brighten_not_wet", r.wet_ratio <= 0.05 and r.reason == "no_front",
          f"wet_ratio={r.wet_ratio} reason={r.reason}")

    # ---- 干区漂移补偿: 全局 +5 变亮 + 微弱湿润变暗 8 (净差 3 < 阈值 5) ----
    _DRYFRAC = (0.85, 0.05, 0.10, 0.30)
    calib_dry = ChannelCalibration(rotation_angle_deg=0.0, roi_bbox=_ROI,
                                   flow_direction="left_to_right", dry_ref_frac=_DRYFRAC)
    ref_dry = compute_reference(_dry_frame(), calib_dry, params)
    check("ref_has_dry", ref_dry is not None and ref_dry.dry_gray is not None, "")
    f = _dry_frame().astype(np.int16) + 5                    # 全局变亮 +5 (含干区)
    f[_Y0:_Y1, _X0:_X0 + _W // 2] -= 8                       # 左半湿润变暗 8 → 净 |diff|=3
    f = np.clip(f, 0, 255).astype(np.uint8)
    r_no = detect_level(f, calib, ref=ref, params=params)            # 无干区: 净差 3 < 5 漏检
    check("drift_uncompensated_misses", r_no.valid is False or r_no.wet_ratio <= 0.05,
          f"valid={r_no.valid} wet_ratio={r_no.wet_ratio}")
    r_yes = detect_level(f, calib_dry, ref=ref_dry, params=params)   # 有干区: 3+5=8 > 5 检出
    check("drift_compensated_detects", r_yes.valid and r_yes.front_percent is not None
          and 45 <= r_yes.front_percent <= 55, f"front={r_yes.front_percent}")
    check("drift_reported", 4.0 <= r_yes.drift <= 6.0, f"drift={r_yes.drift}")

    # ---- 归一化 ROI (roi_frac): 同一场景两种分辨率 → percent 一致 (分辨率无关核心) ----
    def _scene(W: int, H: int) -> np.ndarray:
        f = np.full((H, W, 3), _DRY, np.uint8)
        x0, x1 = int(0.2 * W), int(0.8 * W)          # ROI 横跨 [0.2, 0.8]
        y0, y1 = int(0.25 * H), int(0.75 * H)        # ROI 纵跨 [0.25, 0.75]
        f[y0:y1, x0:(x0 + x1) // 2] = _WET           # ROI 左半浸润 → 应 ≈50%
        return f
    calib_frac = ChannelCalibration(rotation_angle_deg=0.0,
                                    roi_frac=(0.2, 0.25, 0.6, 0.5),
                                    flow_direction="left_to_right")
    ra = detect_level(_scene(320, 240), calib_frac, ref=None, params=params)
    rb = detect_level(_scene(1280, 720), calib_frac, ref=None, params=params)
    check("frac_valid_both", ra.valid and rb.valid, f"{ra.reason}/{rb.reason}")
    check("frac_resolution_invariant",
          ra.valid and rb.valid and ra.front_percent is not None
          and rb.front_percent is not None
          and abs(ra.front_percent - rb.front_percent) <= 5,
          f"320x240={ra.front_percent} 1280x720={rb.front_percent}")

    # ---- 限宽跨洞: 10% 缺口 (≤15%) 桥接, 30% 缺口截停 ----
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X0 + int(_W * 0.45)] = _WET              # [0, 45%) 湿
    f[_Y0:_Y1, _X0 + int(_W * 0.55):_X0 + int(_W * 0.70)] = _WET  # [55%, 70%) 湿, 缺口 10%
    r = detect_level(f, calib, ref=ref, params=params)
    check("front_gap_bridged", r.front_percent is not None and 65 <= r.front_percent <= 75,
          f"front={r.front_percent} (10%缺口应桥接到70)")
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X0 + int(_W * 0.30)] = _WET              # [0, 30%) 湿
    f[_Y0:_Y1, _X0 + int(_W * 0.60):_X0 + int(_W * 0.70)] = _WET  # 缺口 30% > 15%
    r = detect_level(f, calib, ref=ref, params=params)
    check("front_gap_truncates", r.front_percent is not None and 25 <= r.front_percent <= 35,
          f"front={r.front_percent} (30%缺口应截停在30)")

    def _paint(spans) -> np.ndarray:
        """按流向比例区间涂湿 (整列涂满)。"""
        f = _dry_frame()
        for a, b in spans:
            f[_Y0:_Y1, _X0 + int(_W * a):_X0 + int(_W * b)] = _WET
        return f

    # 真前沿被阴影带切开时, 洞后是很长的续段 → 必须照常桥接到远端
    r = detect_level(_paint([(0.0, 0.74), (0.85, 0.975)]), calib, ref=ref, params=params)
    check("front_still_bridges_real_shadow_band",
          r.front_percent is not None and 93 <= r.front_percent <= 100,
          f"front={r.front_percent} (11%缺口应桥接到 ~97)")

    # ---- 指进带: 前沿不是干净台阶, 扫描必须穿过去够到指尖 (本函数最易被改坏的地方) ----
    # 真机前沿是一段毛细指进带: 带内逐列的**湿行占比**在 0~1 反复起伏 ⇒ 列均值 c(x) 多次穿越
    # 判湿线, 且沟与坎宽度相当。任何"桥接后续段须长过缺口"之类的收紧判据都会在这里把 last
    # 钉死在满湿平台边缘 (32%), 造成随指进带变宽而增大的系统性滞后 —— 即 commit 1082219
    # 之前的老 bug。此用例就是那次修复的护栏。
    # 注意构造: 必须逐列改**湿行占比**。平滑的波浪形前沿不行 —— 任意单值前沿形状的列均值都
    # 等于"前沿越过该列的行数占比", 天然单调, 不会产生穿越震荡。
    f = _dry_frame()
    f[_Y0:_Y1, _X0:_X0 + int(_W * 0.32)] = _WET              # 满湿平台 [0, 32%)
    band_lo, band_hi = int(_W * 0.32), int(_W * 0.48)        # 指进带 [32%, 48%)
    rows, span = _Y1 - _Y0, max(1, band_hi - band_lo)
    for k, x in enumerate(range(band_lo, band_hi)):
        decay = k / span                                     # 指尖越远越细
        # 每 8 列一个周期: 3 列"指" (湿行占比稳在 0.5 以上) + 5 列"指缝" (稳在 0.5 以下)
        ratio = (0.90 - 0.28 * decay) if k % 8 < 3 else (0.28 - 0.22 * decay)
        wet_rows = int(round(rows * ratio))
        if wet_rows > 0:
            f[_Y0:_Y0 + wet_rows, _X0 + x] = _WET
    r = detect_level(f, calib, ref=ref, params=params)
    check("front_reaches_through_fingering_band",
          r.front_percent is not None and r.front_percent >= 40,
          f"front={r.front_percent} (须穿过指进带够到 ~45, 不得停在平台边缘 ~33)")

    # ================= log 域乘性模型 (默认口径) =================
    params_log = WaterLevelDetectParams()
    check("default_mode_log", params_log.separation_mode == "log",
          str(params_log.separation_mode))

    # ---- 阴影带: 参考帧同含阴影, 湿润 8% 相对变暗 (绝对仅 4 灰度) ----
    # abs (thr 5.0) 结构性漏检; log (k=0.05) 照度约掉 → 检出 ≈50 且 front 可用
    shadow_ref = _dry_frame()
    shadow_ref[_Y0:_Y1, _X0:_X0 + _W // 2] = 50              # 左半为盖阴影带 (照度低)
    f = shadow_ref.copy()
    f[_Y0:_Y1, _X0:_X0 + _W // 2] = 46                       # 阴影带内湿润: 50→46
    ref_shadow = compute_reference(shadow_ref, calib, params)
    r_abs = detect_level(f, calib, ref=ref_shadow, params=params)
    check("shadow_abs_misses", (not r_abs.valid) or r_abs.wet_ratio <= 0.05,
          f"valid={r_abs.valid} wet_ratio={r_abs.wet_ratio}")
    r_log = detect_level(f, calib, ref=ref_shadow, params=params_log)
    check("shadow_log_front", r_log.valid and r_log.front_percent is not None
          and 45 <= r_log.front_percent <= 55,
          f"valid={r_log.valid} reason={r_log.reason} front={r_log.front_percent}")

    # ---- 乘性全局变亮 ×1.1 (无干区): 不判湿 ----
    ref_log = compute_reference(_dry_frame(), calib, params_log)
    f = np.clip(_dry_frame().astype(np.float32) * 1.10, 0, 255).astype(np.uint8)
    r = detect_level(f, calib, ref=ref_log, params=params_log)
    check("log_brighten_not_wet", r.wet_ratio <= 0.05 and r.reason == "no_front",
          f"valid={r.valid} wet_ratio={r.wet_ratio}")

    # ---- 乘性漂移 + 干区 gain 补偿: ×1.1 变亮叠加左半湿润 ×0.9 ----
    base = np.full((200, 300, 3), 180, np.uint8)
    ref_plain = compute_reference(base, calib, params_log)               # 无干区
    ref_gain = compute_reference(base, calib_dry, params_log)            # 有干区
    f = base.astype(np.float32) * 1.10
    f[_Y0:_Y1, _X0:_X0 + _W // 2] *= 0.90                    # 净变暗仅 ~1% (0.99×)
    f = np.clip(f, 0, 255).astype(np.uint8)
    r_no = detect_level(f, calib, ref=ref_plain, params=params_log)      # gain=1 → 漏检
    check("gain_uncompensated_misses", (not r_no.valid) or r_no.wet_ratio <= 0.05,
          f"valid={r_no.valid} wet_ratio={r_no.wet_ratio}")
    r_yes = detect_level(f, calib_dry, ref=ref_gain, params=params_log)  # gain≈1.1 → 检出
    check("gain_compensated_detects", r_yes.valid and r_yes.front_percent is not None
          and 45 <= r_yes.front_percent <= 55,
          f"valid={r_yes.valid} reason={r_yes.reason} front={r_yes.front_percent}")
    check("gain_reported", 1.05 <= r_yes.gain <= 1.15, f"gain={r_yes.gain}")

    # ---- measure_dry_gain: 增益测量 + 干区自卫统计 ----
    m = measure_dry_gain(f, calib_dry, ref_gain, params_log)
    check("measure_gain_value", m is not None and 1.05 <= m[0] <= 1.15 and m[1] <= 0.05,
          str(m))
    f2 = base.copy()
    f2[40:70, 255:285] = 90                                  # 干区下半被淹 (变暗) → wet_frac≈0.5
    m2 = measure_dry_gain(f2, calib_dry, ref_gain, params_log)
    check("measure_gain_selfguard", m2 is not None and m2[1] >= 0.3, str(m2))
    check("measure_gain_none_without_dry",
          measure_dry_gain(f, calib, ref_plain, params_log) is None, "")

    # ---- dry_zone_front_percent: crop 修正后的流向坐标 ----
    calib_geo = ChannelCalibration(roi_frac=(0.2, 0.25, 0.6, 0.5),
                                   flow_direction="left_to_right",
                                   dry_ref_frac=(0.5, 0.3, 0.06, 0.4))
    p_l2r = dry_zone_front_percent(calib_geo, params_log)
    # span=[0.26,0.74] (crop 0.1); 干区上游沿 0.5 → (0.5−0.26)/0.48 = 50%
    check("zone_pct_l2r", p_l2r is not None and 48 <= p_l2r <= 52, str(p_l2r))
    calib_geo_r = ChannelCalibration(roi_frac=(0.2, 0.25, 0.6, 0.5),
                                     flow_direction="right_to_left",
                                     dry_ref_frac=(0.26, 0.3, 0.06, 0.4))
    p_r2l = dry_zone_front_percent(calib_geo_r, params_log)
    # 流入侧=右 0.74; 干区上游沿 0.32 → (0.74−0.32)/0.48 = 87.5%
    check("zone_pct_r2l", p_r2l is not None and 85 <= p_r2l <= 90, str(p_r2l))
    check("zone_pct_none_without_frac",
          dry_zone_front_percent(ChannelCalibration(roi_bbox=_ROI,
                                                    dry_ref_frac=_DRYFRAC),
                                 params_log) is None, "")

    # ---- DryGainGuard: 更新 / front 逼近冻结 / 干区自卫回滚 / 步限跟进(不冻结) ----
    g = DryGainGuard()
    v, ok = g.filter((1.02, 0.0), None, None)
    check("guard_updates", abs(v - 1.02) < 1e-9 and ok and not g.frozen,
          f"v={v} ok={ok} frozen={g.frozen}")
    v, ok = g.filter((1.03, 0.0), 75.0, 80.0)                # 75 ≥ 80−10 → 冻结, 弃本次测量
    check("guard_front_freeze", abs(v - 1.02) < 1e-9 and ok and g.frozen
          and g.reason == "front_near_dry_zone", f"v={v} ok={ok} r={g.reason}")
    g2 = DryGainGuard()
    v, ok = g2.filter((0.98, 0.30), None, None)              # 干区 30% 判湿 → 回滚上一可信值
    check("guard_selfguard_rollback", abs(v - 1.0) < 1e-9 and ok and g2.frozen
          and g2.reason == "dry_zone_wet", f"v={v} ok={ok} r={g2.reason}")
    # ③ 步限: 光照真变了 ⇒ 跟上新增益 + 判本帧不可信, **不冻结**。冻结会把整个变化量原样
    # 注入 corrected, 而它与判湿线 0.5×A 同量级, 足以把整个干区抬过线 (2026-07-26 真机 CH1)。
    g3 = DryGainGuard()
    v, ok = g3.filter((0.5, 0.0), None, None)                # |Δlog| 0.69 > 0.05
    check("guard_step_follows_not_freeze", abs(v - 0.5) < 1e-9 and (not ok)
          and (not g3.frozen), f"v={v} ok={ok} frozen={g3.frozen}")
    v, ok = g3.filter((0.5, 0.0), None, None)                # 下一拍已稳 → 自动恢复可信
    check("guard_step_recovers", abs(v - 0.5) < 1e-9 and ok and (not g3.frozen),
          f"v={v} ok={ok} frozen={g3.frozen}")
    g4 = DryGainGuard()
    v, ok = g4.filter(None, None, None)                      # 无测量 → 保持, 不冻结
    check("guard_none_measure_keeps", abs(v - 1.0) < 1e-9 and ok and not g4.frozen,
          f"v={v} ok={ok} frozen={g4.frozen}")

    total = passed[0] + len(failures)
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
