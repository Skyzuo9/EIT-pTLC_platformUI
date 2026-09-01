"""离线单测: 前沿解析结构门 (waterlevel_detector.analyze_front)
================================================================
被测对象是把"补偿后差分场 → 前沿位置 + 形状合理性"的连续域纯函数。它取代了两样旧东西:

  1. 服务层的时序步长门 (_gate_front_jump / MAX_PERCENT_STEP) —— 那个门有跨帧基线, 而基线
     只在"被接受"时前进, 一旦第一个可见拍就超限, 基线永远停在 0, 后续每一拍都被拒 = 死锁。
     2026-07-26 真机 CH1 实测连续 199 拍 front_jump (442s) 不恢复。本模块无任何跨帧状态,
     故该失效模式在结构上不可能再现 (见 test_stateless_*)。
  2. 前沿位置的单列判据 (`if seq[0] < ratio_level: return None`) —— 一列边缘伪迹判死全盘。
     同一台机 435 列中最流入侧 1 列恒 0, 其余 434 列一致报前沿 44%, 却整体判 None
     (见 test_inflow_dead_column_*)。

判湿线由绝对阈值改为 f×A (A = 湿平台幅值), 消除 A 在 0.07~0.10 浮动带来的 run-to-run
位置漂移 (见 test_front_position_invariant_to_amplitude —— 本次改动的核心断言)。
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from eit_ptlc.controller.waterlevel_detector import (
    PLATEAU_SAMPLE_FRAC,
    PROFILE_EDGE_BAND_FRAC,
    WaterLevelDetectParams,
    analyze_front,
)

# 真机 CH1 有效检测区尺寸 (435 × 63), 让合成用例与现场同量级
_N = 435
_H = 63
# 真机实测湿平台幅值 (log 域); 随板/展开剂/照明在 0.07~0.10 浮动
_A_REAL = 0.085


def _params(**kw) -> WaterLevelDetectParams:
    p = WaterLevelDetectParams()
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def _field(seq_screen) -> np.ndarray:
    """把一维 profile (画面坐标序) 铺成 _H 行的二维差分场。"""
    return np.tile(np.asarray(seq_screen, np.float32), (_H, 1))


def _front_seq(amplitude: float, front_frac: float, ramp_frac: float = 0.08):
    """构造一条"流入侧高台 + 线性锐降 + 干拖尾"的 profile, 返回**流入侧序** (索引 0 = 流入侧)。

    front_frac 是高台末端位置; 斜坡跨 ramp_frac, 故半幅穿越点应落在
    front_frac + ramp_frac/2 处 —— 这是各用例的解析真值。
    """
    seq = np.zeros(_N, np.float32)
    k = int(front_frac * _N)
    ramp = max(1, int(ramp_frac * _N))
    seq[:k] = amplitude
    tail = min(ramp, _N - k)
    if tail > 0:
        seq[k:k + tail] = np.linspace(amplitude, 0.0, tail, dtype=np.float32)
    return seq


def _to_screen(seq_inflow, flow_direction: str):
    """流入侧序 → 画面坐标序 (right_to_left / bottom_to_top 的流入侧在高索引端)。"""
    if flow_direction in ("right_to_left", "bottom_to_top"):
        return seq_inflow[::-1]
    return seq_inflow


class TestAmplitudeRelativeThreshold(unittest.TestCase):
    """判湿线相对幅值 —— 本次改动要消掉的那项 run-to-run 方差。"""

    def test_front_position_invariant_to_amplitude(self) -> None:
        """同一形状、不同对比度 A, 前沿位置必须一致。

        这是整改的核心断言。旧口径判湿线是绝对的 log(1/(1-0.05))=0.0513, 它在幅值中的
        相对位置随 A 在 51%~73% 漂 (A=0.07 时占 73%, A=0.10 时占 51%), 前沿位置跟着漂;
        取 f×A 后与 A 无关。
        """
        p = _params()
        seen = []
        for amplitude in (0.070, 0.085, 0.100):
            seq = _front_seq(amplitude, 0.44)
            fa = analyze_front(_field(_to_screen(seq, "right_to_left")),
                               "right_to_left", p)
            self.assertEqual(fa.verdict, "ok")
            self.assertAlmostEqual(fa.amplitude, amplitude, places=4)
            seen.append(fa.front_percent)
        self.assertEqual(len(set(seen)), 1,
                         f"前沿位置随幅值漂了: {seen} (相对幅值化未生效)")

    def test_level_tracks_amplitude(self) -> None:
        # level 必须是 f×A 而非常数
        for amplitude in (0.07, 0.10):
            fa = analyze_front(_field(_to_screen(_front_seq(amplitude, 0.44), "left_to_right")),
                               "left_to_right", _params(front_ratio_level=0.5))
            self.assertAlmostEqual(fa.level, 0.5 * amplitude, places=4)

    def test_half_amplitude_crossing_lands_mid_ramp(self) -> None:
        # f=0.5 应落在斜坡中点: 高台末端 0.44 + 斜坡 0.08/2 = 0.48
        fa = analyze_front(_field(_to_screen(_front_seq(_A_REAL, 0.44, 0.08), "right_to_left")),
                           "right_to_left", _params(front_ratio_level=0.5))
        self.assertEqual(fa.verdict, "ok")
        self.assertAlmostEqual(fa.front_percent, 48.0, delta=0.6)

    def test_lower_f_reaches_further_into_fringe(self) -> None:
        # f 越小越贴近渐变带前缘 —— 语义单调性, 防日后把比较方向写反
        base = _to_screen(_front_seq(_A_REAL, 0.44, 0.20), "right_to_left")
        near = analyze_front(_field(base), "right_to_left", _params(front_ratio_level=0.8))
        far = analyze_front(_field(base), "right_to_left", _params(front_ratio_level=0.2))
        self.assertLess(near.front_percent, far.front_percent)


class TestInflowAnchor(unittest.TestCase):
    """锚定判据: 边带/平台 median, 不再是单列。"""

    def test_inflow_dead_column_does_not_kill_front(self) -> None:
        """流入侧首列坏点不得判死整个前沿 (缺陷二回归锁)。

        真机 CH1: 435 列中最流入侧 1 列恒 0 (缸壁反光 + 模糊核边界), 其余 434 列一致
        报前沿 44%, 旧的 seq[0] 单列门却返回 None, 使 wait_level 的 T2 永远打不响。
        """
        seq = _front_seq(_A_REAL, 0.44)
        seq[0] = 0.0                       # 流入侧首列坏点
        fa = analyze_front(_field(_to_screen(seq, "right_to_left")), "right_to_left", _params())
        self.assertEqual(fa.verdict, "ok", "一列边缘伪迹不得判死前沿")
        self.assertAlmostEqual(fa.front_percent, 48.0, delta=0.6)

    def test_all_dry_is_no_front(self) -> None:
        fa = analyze_front(_field(np.zeros(_N, np.float32)), "right_to_left", _params())
        self.assertEqual(fa.verdict, "no_front")
        self.assertIsNone(fa.front_percent)

    def test_no_front_level_falls_back_to_absolute_floor(self) -> None:
        """平台未湿时 level 必须退回绝对判湿线。

        否则 f×A 会是个 ~0 甚至负的数, detect_level 拿它做掩膜会把噪声整片判成浸润,
        干板瞬间显示 ~50% 浸润。
        """
        p = _params(wet_rel_threshold=0.05)
        fa = analyze_front(_field(np.zeros(_N, np.float32)), "right_to_left", p)
        self.assertAlmostEqual(fa.level, math.log(1.0 / 0.95), places=6)

    def test_barely_wet_plateau_still_no_front(self) -> None:
        # 平台幅值刚好在绝对地板之下 → 仍算前沿未进入
        floor = math.log(1.0 / 0.95)
        seq = _front_seq(floor * 0.9, 0.44)
        fa = analyze_front(_field(_to_screen(seq, "right_to_left")), "right_to_left", _params())
        self.assertEqual(fa.verdict, "no_front")


class TestSaturationGuard(unittest.TestCase):
    """干拖尾判据: 取代时序步长门, 单帧认出整帧照度突变。"""

    def test_uniform_lift_is_roi_saturated(self) -> None:
        """整条 profile 被抬平 = 曝光/照度突变, 不是前沿。

        这正是 2026-07-26 那次 0%→100%→0% 误触发自动排液的形状。
        """
        fa = analyze_front(_field(np.full(_N, _A_REAL, np.float32)), "right_to_left", _params())
        self.assertEqual(fa.verdict, "roi_saturated")
        self.assertIsNone(fa.front_percent)

    def test_genuine_front_near_t2_still_ok(self) -> None:
        """前沿推到 T2 附近 (90%) 时下游边带仍干, 不得被误判成整区判湿。

        这道边界决定了守卫能不能与 trigger_percent_t2=90 共存。
        """
        seq = _front_seq(_A_REAL, 0.90, 0.04)
        fa = analyze_front(_field(_to_screen(seq, "right_to_left")), "right_to_left", _params())
        self.assertEqual(fa.verdict, "ok")
        self.assertGreater(fa.front_percent, 88.0)


class TestStatelessness(unittest.TestCase):
    """无跨帧状态 —— 死锁在结构上不可能再现 (缺陷一回归锁)。"""

    def test_same_input_same_output(self) -> None:
        p = _params()
        field = _field(_to_screen(_front_seq(_A_REAL, 0.44), "right_to_left"))
        a = analyze_front(field, "right_to_left", p)
        b = analyze_front(field, "right_to_left", p)
        self.assertEqual((a.verdict, a.front_percent, a.amplitude),
                         (b.verdict, b.front_percent, b.amplitude))

    def test_recovers_immediately_after_artifact(self) -> None:
        """伪迹拍之后紧跟的正常拍必须立刻恢复 ok。

        旧的时序步长门在这里会把基线卡住并永久拒后续每一拍 (真机实测 199 拍不恢复)。
        """
        p = _params()
        good = _field(_to_screen(_front_seq(_A_REAL, 0.44), "right_to_left"))
        bad = _field(np.full(_N, _A_REAL, np.float32))
        self.assertEqual(analyze_front(good, "right_to_left", p).verdict, "ok")
        self.assertEqual(analyze_front(bad, "right_to_left", p).verdict, "roi_saturated")
        after = analyze_front(good, "right_to_left", p)
        self.assertEqual(after.verdict, "ok", "伪迹后必须立即恢复, 不得残留状态")
        self.assertAlmostEqual(after.front_percent, 48.0, delta=0.6)

    def test_big_jump_between_frames_is_accepted(self) -> None:
        """一步从干板跳到 44% 也必须被采信 —— 判据是形状不是速度。

        旧门用"物理速度上限"作采信判据, 而当年那道整帧差分均值下限造成的盲区,
        恰好让第一个可见拍就超限。
        """
        p = _params()
        self.assertEqual(
            analyze_front(_field(np.zeros(_N, np.float32)), "right_to_left", p).verdict,
            "no_front")
        jumped = analyze_front(
            _field(_to_screen(_front_seq(_A_REAL, 0.44), "right_to_left")), "right_to_left", p)
        self.assertEqual(jumped.verdict, "ok")


class TestAnchorFloorUnits(unittest.TestCase):
    """锚定地板必须与 corrected 同单位 —— log 域 ~0.05, abs 域是灰度 ~5~30。

    早先地板写死用 log 域的 log(1/(1-k))≈0.0513, abs 模式下任何 >0.0513 灰度的噪声都能
    "锚定成功" ⇒ 干板也判 ok, no_front 在 abs 模式下永不触发。
    """

    def test_abs_mode_dry_plate_is_no_front(self) -> None:
        p = _params(separation_mode="abs", wet_pixel_threshold=5.0)
        # 干板在 abs 域的残差量级是零点几到几个灰度, 远低于判湿线 5.0
        noise = np.full(_N, 1.0, np.float32)
        fa = analyze_front(_field(noise), "right_to_left", p)
        self.assertEqual(fa.verdict, "no_front",
                         f"abs 模式干板被误锚定 (amplitude={fa.amplitude}), 地板单位错了")

    def test_abs_mode_real_front_anchors(self) -> None:
        p = _params(separation_mode="abs", wet_pixel_threshold=5.0)
        seq = _front_seq(12.0, 0.44)          # 12 灰度的浸润变暗
        fa = analyze_front(_field(_to_screen(seq, "right_to_left")), "right_to_left", p)
        self.assertEqual(fa.verdict, "ok")
        self.assertAlmostEqual(fa.amplitude, 12.0, places=3)
        self.assertAlmostEqual(fa.level, 6.0, places=3)     # f=0.5 × A
        self.assertAlmostEqual(fa.front_percent, 48.0, delta=0.6)

    def test_log_mode_floor_unchanged(self) -> None:
        # log 模式地板仍是 −log(1−k); 幅值刚好压线之下须判 no_front
        p = _params(separation_mode="log", wet_rel_threshold=0.05)
        floor = math.log(1.0 / 0.95)
        below = analyze_front(_field(_front_seq(floor * 0.9, 0.44)[::-1]), "right_to_left", p)
        self.assertEqual(below.verdict, "no_front")


class TestFlowDirections(unittest.TestCase):
    """三个流向的流入侧取向 —— 边带若取反, 锚定与拖尾判据会整体镜像。"""

    def test_all_directions_agree_on_same_shape(self) -> None:
        p = _params()
        for direction in ("left_to_right", "right_to_left", "bottom_to_top"):
            seq = _front_seq(_A_REAL, 0.44)
            screen = _to_screen(seq, direction)
            # bottom_to_top 沿 y 推进 → profile 是行方向, 差分场须转置
            field = _field(screen)
            if direction == "bottom_to_top":
                field = field.T
            fa = analyze_front(field, direction, p)
            self.assertEqual(fa.verdict, "ok", f"{direction} 判定失败")
            self.assertAlmostEqual(fa.front_percent, 48.0, delta=0.6,
                                   msg=f"{direction} 前沿位置偏了 (流入侧取向可能反了)")

    def test_direction_mismatch_is_detected(self) -> None:
        # 用错流向 → 流入侧变成干端 → 锚定失败, 不会悄悄给出一个镜像的错位置
        seq = _front_seq(_A_REAL, 0.44)
        fa = analyze_front(_field(_to_screen(seq, "right_to_left")), "left_to_right", _params())
        self.assertEqual(fa.verdict, "no_front")


class TestSubPixel(unittest.TestCase):
    """亚像素插值。"""

    def test_subpixel_interpolation_beats_integer_grid(self) -> None:
        """已知穿越位置的斜坡, 定位误差应远小于 1 列。"""
        p = _params(front_ratio_level=0.5, front_gap_frac=0.15)
        # 高台到 0.400, 斜坡跨 10 列 → 半幅穿越真值 = (0.400*_N + 5) / _N
        seq = np.zeros(_N, np.float32)
        k = int(0.400 * _N)
        seq[:k] = _A_REAL
        seq[k:k + 10] = np.linspace(_A_REAL, 0.0, 10, dtype=np.float32)
        truth = (k + 5) / _N * 100.0
        fa = analyze_front(_field(_to_screen(seq, "right_to_left")), "right_to_left", p)
        self.assertEqual(fa.verdict, "ok")
        err_cols = abs(fa.front_percent - truth) / 100.0 * _N
        self.assertLess(err_cols, 1.0, f"亚像素误差 {err_cols:.2f} 列 (真值 {truth:.2f}%)")


class TestConstants(unittest.TestCase):
    """常量语义钉子 —— 这两个是安全轨, 改动须是有意识的。"""

    def test_band_widths_are_small_but_multi_column(self) -> None:
        # 必须 >1 列 (否则退回被一列坏点打死的旧行为), 又必须够小 (不吃掉真实前沿)
        self.assertGreater(round(_N * PROFILE_EDGE_BAND_FRAC), 1)
        self.assertLess(PROFILE_EDGE_BAND_FRAC, 0.05)
        self.assertGreater(round(_N * PLATEAU_SAMPLE_FRAC), 1)
        self.assertLess(PLATEAU_SAMPLE_FRAC, 0.15)


if __name__ == "__main__":
    unittest.main()
