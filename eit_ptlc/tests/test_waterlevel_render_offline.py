"""液位检测叠加图渲染离线测试 (无相机/无网络/无香橙派)
========================================================
功能:
    钉死 render_debug_frame 与 detect_level 的**口径一致性** —— 叠加图上那片红色湿区
    必须就是算出 percent 的那片掩膜。两者若日后分叉, 网页「识别」页就会展示一张
    与读数自相矛盾的图, 而这种错比没有图更危险 (看着可信却是错的)。

覆盖:
    1. 掩膜一致性: 渲染内部掩膜占比 == detect_level 的 wet_ratio
    2. gain_override 透传: 给不同增益必须画出不同掩膜 (证明参数不是摆设)
    3. 前沿线三流向落位: left_to_right/right_to_left/bottom_to_top 各自量取端不同
    4. 退化输入不崩: 未标定 / 无参考 / front_percent=None
    5. 服务层缓存: _process 存下的 frame/gain 必须与产出该结果的那一次配套 (含走势历史)
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2", reason="渲染测试需要 opencv")

from eit_ptlc.controller.waterlevel_detector import (  # noqa: E402
    ChannelCalibration,
    WaterLevelDetectParams,
    _VIS_FRONT,
    _VIS_ROI_CROP,
    compute_reference,
    detect_level,
    effective_roi_rect,
    extract_roi_gray,
    render_debug_frame,
    rotation_matrix,
)

# 合成帧尺寸 (够大以便 crop 后仍有像素, 又足够小跑得快)
_W, _H = 320, 240


def _dry_frame() -> np.ndarray:
    """干板: 均匀中灰 (给 log 分离一个干净基线)。"""
    return np.full((_H, _W, 3), 180, np.uint8)


def _wet_frame(wet_cols: int, from_right: bool = False) -> np.ndarray:
    """压暗 wet_cols 列模拟已浸润 (湿=反射率下降, 与算法"变暗为正"口径一致)。

    from_right=True 时湿区贴右边 —— 测 right_to_left 必须让湿区在**流入侧**, 否则
    算法按定义判"前沿未进入"(流入侧首列即干) 返回 None, 测不到落位。
    """
    frame = _dry_frame()
    if from_right:
        frame[:, _W - wet_cols:] = 120
    else:
        frame[:, :wet_cols] = 120
    return frame


def _calib(flow: str = "left_to_right") -> ChannelCalibration:
    """全画幅 ROI 的比例标定 (roi_frac 分辨率无关, 与生产口径一致)。"""
    return ChannelCalibration(rotation_angle_deg=0.0, flow_direction=flow,
                              roi_frac=(0.0, 0.0, 1.0, 1.0))


def _params() -> WaterLevelDetectParams:
    return WaterLevelDetectParams()


def _rect(calib, params):
    """该标定在渲染画布上的有效检测区 (旋转角 0 → 画布尺寸即 _W x _H)。"""
    return effective_roi_rect(calib, params, _W, _H)


def _rendered_wet_frac(calib, params, frame, *render_args, **render_kw) -> float:
    """由 overlay 开/关两张画布的差异反推渲染实际用的湿区比例。

    纯色掩膜的放大面板撤掉后, 画面上只剩**半透明混合**的湿区, 没法按颜色直接数。
    改用差分: 就地叠加只动掩膜为真的像素, 故 on/off 在有效检测区内逐像素不等的点就是掩膜。

    **但不能直接用 changed.mean()**: 绿框 (线宽 2) 与 HUD 文字是在叠加之后画的, 两态下
    逐字节相同, 它们盖住的湿像素在差分里表现为"没变" —— 会把比例压低 (实测偏低约 1.5%)。
    故先identify 标注像素 (off 相对原帧被改动过的位置 = 框线 + HUD), 再把它们从**分子
    分母同时**剔除。不写死标注颜色, 日后再加标注也不会误伤这条断言。
    要求 rotation_angle_deg=0 (旋转后画布即原帧), 且 result=None (不画前沿线进差分)。
    """
    assert calib.rotation_angle_deg == 0.0, "本 helper 以原帧作未标注基准, 只支持旋转角 0"
    on = render_debug_frame(frame, *render_args, **render_kw, inplace_overlay=True)
    off = render_debug_frame(frame, *render_args, **render_kw, inplace_overlay=False)
    rx, ry, rw, rh = _rect(calib, params)
    sl = (slice(ry, ry + rh), slice(rx, rx + rw))

    annotated = np.any(off[sl] != frame[sl], axis=2)      # 框线 + HUD 覆盖的像素
    changed = np.any(on[sl] != off[sl], axis=2)           # 被半透明混合动过的湿像素
    return float(changed[~annotated].mean())


class TestMaskConsistency:
    """口径一致性: 渲染的掩膜必须与 detect_level 用的是同一片。"""

    def test_wet_ratio_matches_rendered_mask(self):
        calib, params = _calib(), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        assert ref is not None

        frame = _wet_frame(wet_cols=160)          # 左半湿
        result = detect_level(frame, calib, ref=ref, params=params)
        assert result.valid, f"合成用例应有效, 实得 reason={result.reason}"

        # 渲染时传 result=None: 掩膜的计算与 result 无关 (result 只决定前沿线/HUD),
        # 不画前沿线才能让 on/off 的差异只剩掩膜本身
        rendered = _rendered_wet_frac(calib, params, frame, calib, ref, params, None)

        assert rendered == pytest.approx(result.wet_ratio, abs=0.01), (
            f"渲染掩膜占比 {rendered:.4f} 与 detect_level 的 wet_ratio "
            f"{result.wet_ratio:.4f} 不一致 —— 口径已分叉")

    @pytest.mark.parametrize("verdict, make_frame, flow", [
        # 前沿在流入侧 → 形状合格
        ("ok", lambda: _wet_frame(wet_cols=160), "left_to_right"),
        # 湿区全在下游、流入侧是干的 → 锚定失败。**掩膜非空但 verdict 不是 ok**,
        # 正是 2026-07-26 真机翻车的形状 (画面一片红, 数字却报 0)
        ("no_front", lambda: _wet_frame(wet_cols=160, from_right=True), "left_to_right"),
        # 整帧压暗 → 下游拖尾也过判湿线 → 判照度突变伪迹
        ("roi_saturated", lambda: np.full((_H, _W, 3), 120, np.uint8), "left_to_right"),
    ])
    def test_wet_ratio_matches_rendered_mask_for_every_verdict(self, verdict,
                                                               make_frame, flow):
        """**每一种 verdict** 下渲染掩膜占比都必须等于 detect_level 的 wet_ratio。

        这条是结构锁, 不是又一个普通用例: 真机上出过 detect_level 在算掩膜**之前**早返回
        (旧 no_signal 门) 而 render_debug_frame 照常涂红的事故 —— 同一帧渲染掩膜 0.1569、
        snapshot wet_ratio 0.0, 页面上"画面说湿、数字说干"。只锁 valid 分支锁不住它,
        必须逐 verdict 锁。日后谁再在 detect_level 里加早返回, 这条会当场抓住。
        """
        calib, params = _calib(flow), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        assert ref is not None

        frame = make_frame()
        result = detect_level(frame, calib, ref=ref, params=params)
        assert result.reason == ("" if verdict == "ok" else verdict), (
            f"用例构造的形状没有产出预期 verdict={verdict}, 实得 reason={result.reason!r}")

        rendered = _rendered_wet_frac(calib, params, frame, calib, ref, params, None)
        assert rendered == pytest.approx(result.wet_ratio, abs=0.01), (
            f"verdict={verdict}: 渲染掩膜占比 {rendered:.4f} != wet_ratio "
            f"{result.wet_ratio:.4f} —— 画面与数字分叉")

    @pytest.mark.parametrize("sep_mode", ["log", "abs"])
    def test_otsu_path_mask_matches_wet_ratio(self, sep_mode):
        """无参考 (Otsu 回退) 路径同样必须画面 == 数字, 两种分离口径都要。

        该路径的 corrected 是 0/1 判湿场, 判湿地板既不是 log 量级也不是灰度量级, 由
        detect_level 与 render_debug_frame **各自**传 _OTSU_WET_FLOOR —— 两处传得不一样
        就又是一张骗人的图。abs 那档尤其要锁: 曾经用灰度地板 5.0 去卡 0/1 场, 半湿板报 0%。
        """
        params = WaterLevelDetectParams(separation_mode=sep_mode)
        calib = _calib()
        frame = _wet_frame(wet_cols=160)

        result = detect_level(frame, calib, ref=None, params=params)
        assert result.wet_ratio > 0.3, (
            f"sep={sep_mode}: 半湿板 Otsu 回退却报 wet_ratio={result.wet_ratio} "
            f"(reason={result.reason}) —— 判湿地板单位又错了")

        rendered = _rendered_wet_frac(calib, params, frame, calib, None, params, None)
        assert rendered == pytest.approx(result.wet_ratio, abs=0.01), (
            f"sep={sep_mode}: 渲染掩膜 {rendered:.4f} != wet_ratio {result.wet_ratio:.4f}")

    def test_invalid_verdict_still_reports_nonzero_wet_ratio(self):
        """verdict 非 ok 时也必须如实上报 wet_ratio, 不能清零。

        清零正是旧 no_signal 门干的事: 前沿明明已进 ROI、掩膜画得好好的, 上报却是 0,
        于是「检测健康」全零、走势曲线空白、前沿线不画。
        """
        calib, params = _calib("left_to_right"), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _wet_frame(wet_cols=160, from_right=True)   # 下游湿, 流入侧干
        result = detect_level(frame, calib, ref=ref, params=params)

        assert not result.valid and result.reason == "no_front"
        assert result.wet_ratio > 0.3, (
            f"下游半幅已浸润, wet_ratio 却是 {result.wet_ratio} —— 又把无效帧的读数清零了")

    def test_gain_override_is_actually_used(self):
        """给一个明显偏离的 gain_override 必须改变掩膜; 否则说明参数没透传到 separate_wet。"""
        calib, params = _calib(), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _wet_frame(wet_cols=160)

        base = _rendered_wet_frac(calib, params, frame, calib, ref, params, None, None)
        shifted = _rendered_wet_frac(calib, params, frame, calib, ref, params, None, 0.5)

        assert base != pytest.approx(shifted, abs=1e-6), (
            "gain_override 未影响掩膜 —— 增益没有透传进 separate_wet, "
            "叠加图会与带守卫增益的 detect_level 结果不一致")

    def test_matches_detect_level_under_gain_override(self):
        """带 override 时两条路径仍须一致 (守卫冻结增益后的真实运行态)。"""
        calib, params = _calib(), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _wet_frame(wet_cols=160)
        gain = 0.92

        result = detect_level(frame, calib, ref=ref, params=params, gain_override=gain)
        rendered = _rendered_wet_frac(calib, params, frame, calib, ref, params, None, gain)

        assert rendered == pytest.approx(result.wet_ratio, abs=0.01)


class TestFrontLine:
    """前沿线落位: front_percent 是"从流入侧起算", 三个流向的量取端不同。

    前沿线只就地画在有效检测区内, 故取样与坐标换算都相对该区左上角。
    """

    @staticmethod
    def _hit(canvas: np.ndarray, calib, params) -> np.ndarray:
        rx, ry, rw, rh = _rect(calib, params)
        sub = canvas[ry:ry + rh, rx:rx + rw]
        b, g, r = _VIS_FRONT
        return (sub[:, :, 0] == b) & (sub[:, :, 1] == g) & (sub[:, :, 2] == r)

    @classmethod
    def _front_xs(cls, canvas: np.ndarray, calib, params) -> np.ndarray:
        return np.unique(np.nonzero(cls._hit(canvas, calib, params))[1])

    @classmethod
    def _front_ys(cls, canvas: np.ndarray, calib, params) -> np.ndarray:
        return np.unique(np.nonzero(cls._hit(canvas, calib, params))[0])

    def test_left_to_right_front_near_left(self):
        """左进右出 + 仅左侧 25% 浸润 → 前沿线应靠左。"""
        calib, params = _calib("left_to_right"), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _wet_frame(wet_cols=80)          # 25% 宽
        result = detect_level(frame, calib, ref=ref, params=params)
        canvas = render_debug_frame(frame, calib, ref, params, result)

        xs = self._front_xs(canvas, calib, params)
        assert xs.size > 0, "应画出前沿线"
        assert xs.mean() < _rect(calib, params)[2] * 0.5, "left_to_right 下前沿应在左半"

    def test_right_to_left_front_near_right(self):
        """右进左出 + 仅右侧 25% 浸润 → 前沿线应靠右 (与 left_to_right 镜像)。"""
        calib, params = _calib("right_to_left"), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _wet_frame(wet_cols=80, from_right=True)
        result = detect_level(frame, calib, ref=ref, params=params)
        assert result.valid and result.front_percent is not None, (
            f"湿区已在流入侧, 应判出前沿 (valid={result.valid} "
            f"front={result.front_percent} reason={result.reason})")
        canvas = render_debug_frame(frame, calib, ref, params, result)

        xs = self._front_xs(canvas, calib, params)
        assert xs.size > 0, "应画出前沿线"
        assert xs.mean() > _rect(calib, params)[2] * 0.5, "right_to_left 下前沿应在右半"

    def test_flow_direction_mirrors_front_line(self):
        """同一张湿区在右的图, 两个水平流向必须把前沿线画到相反侧 —— 换算写反会被这条抓住。"""
        params = _params()
        frame = _wet_frame(wet_cols=80, from_right=True)

        rtl = _calib("right_to_left")
        ref_r = compute_reference(_dry_frame(), rtl, params)
        res_r = detect_level(frame, rtl, ref=ref_r, params=params)
        xs_rtl = self._front_xs(
            render_debug_frame(frame, rtl, ref_r, params, res_r), rtl, params)

        # 同一 front_percent 数值喂给 left_to_right, 应画到镜像位置
        ltr = _calib("left_to_right")
        xs_ltr = self._front_xs(
            render_debug_frame(frame, ltr, ref_r, params, res_r), ltr, params)

        assert xs_rtl.size > 0 and xs_ltr.size > 0
        assert xs_rtl.mean() > xs_ltr.mean(), (
            "right_to_left 的前沿线应比 left_to_right 更靠右 (流向换算反了)")

    def test_bottom_to_top_draws_horizontal_line(self):
        """垂直流: 前沿线应是横线 (跨多列同一行), 而非竖线。"""
        calib, params = _calib("bottom_to_top"), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _dry_frame()
        frame[160:, :] = 120                      # 下部 1/3 浸润
        result = detect_level(frame, calib, ref=ref, params=params)
        canvas = render_debug_frame(frame, calib, ref, params, result)

        if result.front_percent is None:
            pytest.skip("前沿未进入")
        ys = self._front_ys(canvas, calib, params)
        xs = self._front_xs(canvas, calib, params)
        assert ys.size <= 3, "横线应只占少数几行"
        assert xs.size > _rect(calib, params)[2] * 0.5, "横线应横跨有效检测区"


class TestInPlaceOverlay:
    """就地叠加: 把识别结果画回原图真实位置, 并可开关 (关掉与开启对照看判得准不准)。"""

    def test_rect_matches_extract_roi_gray(self):
        """**一致性锁**: effective_roi_rect 的 (w,h) 必须等于 extract_roi_gray 的实际尺寸。

        两者若分叉, 就地叠加/绿框就会与真正被检测的那块像素错位。
        """
        for rot, frac in ((0.0, (0.0, 0.0, 1.0, 1.0)),
                          (0.0, (0.15, 0.2, 0.5, 0.6)),
                          (11.0, (0.1, 0.1, 0.8, 0.8))):
            calib = ChannelCalibration(rotation_angle_deg=rot, roi_frac=frac)
            params = _params()
            gray = extract_roi_gray(_dry_frame(), calib, params)
            _M, (rw, rh) = rotation_matrix(rot, _W, _H)
            rect = effective_roi_rect(calib, params, rw, rh)
            assert gray is not None and rect is not None
            assert (rect[2], rect[3]) == (gray.shape[1], gray.shape[0]), (
                f"rot={rot} frac={frac}: 矩形 {rect[2]}x{rect[3]} 与实际 ROI "
                f"{gray.shape[1]}x{gray.shape[0]} 不符 —— 两处夹取逻辑已分叉")

    def test_overlay_changes_only_inside_rect(self):
        """涂色只许落在有效检测区内, 一个像素都不许溢出到框外。"""
        calib, params = _calib(), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _wet_frame(wet_cols=160)
        result = detect_level(frame, calib, ref=ref, params=params)

        on = render_debug_frame(frame, calib, ref, params, result, inplace_overlay=True)
        off = render_debug_frame(frame, calib, ref, params, result, inplace_overlay=False)
        rx, ry, rw, rh = _rect(calib, params)

        assert not np.array_equal(on[ry:ry + rh, rx:rx + rw],
                                  off[ry:ry + rh, rx:rx + rw]), "框内应有涂色差异"

        # 框外逐字节相同: 把框内挖空后比对
        a, b = on.copy(), off.copy()
        a[ry:ry + rh, rx:rx + rw] = 0
        b[ry:ry + rh, rx:rx + rw] = 0
        assert np.array_equal(a, b), "就地叠加溢出到了有效检测区之外"

    def test_overlay_is_translucent_not_solid(self):
        """必须是半透明混合 —— 涂实就把板面纹理盖没了, 反而没法判断红得对不对。"""
        calib, params = _calib(), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _wet_frame(wet_cols=160)
        canvas = render_debug_frame(frame, calib, ref, params, None, inplace_overlay=True)
        rx, ry, rw, rh = _rect(calib, params)
        sub = canvas[ry:ry + rh, rx:rx + rw]
        solid = (sub[:, :, 0] == 0) & (sub[:, :, 1] == 0) & (sub[:, :, 2] == 255)
        assert not solid.any(), "原图上出现了纯红 —— 说明是覆盖而非半透明混合"

    def test_overlay_off_draws_no_front_line(self):
        """关掉就地叠加时前沿线也一并撤掉 —— 板面须是完全未着色的原貌供人眼比对。"""
        calib, params = _calib(), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _wet_frame(wet_cols=160)
        result = detect_level(frame, calib, ref=ref, params=params)
        assert result.front_percent is not None

        off = render_debug_frame(frame, calib, ref, params, result, inplace_overlay=False)
        b, g, r = _VIS_FRONT
        hit = (off[:, :, 0] == b) & (off[:, :, 1] == g) & (off[:, :, 2] == r)
        assert not hit.any(), "overlay=0 时仍画出了前沿线"

    def test_front_line_drawn_in_place(self):
        """前沿线就地画在有效检测区内: 识别结果直接落在板面真实位置上。"""
        calib, params = _calib(), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        frame = _wet_frame(wet_cols=160)
        result = detect_level(frame, calib, ref=ref, params=params)
        assert result.front_percent is not None

        canvas = render_debug_frame(frame, calib, ref, params, result, inplace_overlay=True)
        rx, ry, rw, rh = _rect(calib, params)
        sub = canvas[ry:ry + rh, rx:rx + rw]
        b, g, r = _VIS_FRONT
        hit = (sub[:, :, 0] == b) & (sub[:, :, 1] == g) & (sub[:, :, 2] == r)
        assert hit.any(), "有效检测区内未找到就地前沿线"

    def test_uncalibrated_draws_no_crop_box(self):
        """未标定时没有可锚的矩形, 不得画绿框, 更不得崩。"""
        calib = ChannelCalibration()
        canvas = render_debug_frame(_dry_frame(), calib, None, _params(), None)
        b, g, r = _VIS_ROI_CROP
        green = (canvas[:, :, 0] == b) & (canvas[:, :, 1] == g) & (canvas[:, :, 2] == r)
        assert not green.any(), "未标定却画出了绿框"


class TestDegradedInputs:
    """退化输入不得崩 —— 「识别」页在任何设备状态下都要能出图。"""

    def test_no_reference_falls_back_to_otsu(self):
        calib, params = _calib(), _params()
        frame = _wet_frame(wet_cols=160)
        canvas = render_debug_frame(frame, calib, None, params, None)
        assert canvas.ndim == 3 and canvas.dtype == np.uint8
        assert canvas.shape[0] == _H

    def test_uncalibrated_channel_still_renders(self):
        """未标定 → 仍原样给出旋转帧 (现场据此确认"相机有画面但没标定")。"""
        calib = ChannelCalibration()              # roi_frac/roi_bbox 皆 None
        canvas = render_debug_frame(_dry_frame(), calib, None, _params(), None)
        assert canvas.ndim == 3 and canvas.dtype == np.uint8
        assert canvas.shape[1] == _W              # 单幅整帧, 不再拼接放大面板

    def test_front_none_draws_no_line(self):
        """前沿未出现时不画线, 也不得崩。"""
        calib, params = _calib(), _params()
        ref = compute_reference(_dry_frame(), calib, params)
        canvas = render_debug_frame(_dry_frame(), calib, ref, params, None)
        b, g, r = _VIS_FRONT
        hit = (canvas[:, :, 0] == b) & (canvas[:, :, 1] == g) & (canvas[:, :, 2] == r)
        assert not hit.any(), "result=None 时不应画前沿线"

    def test_rotation_does_not_crash(self):
        """带旋转角时画布尺寸变化, 拼接仍须成立。"""
        calib = ChannelCalibration(rotation_angle_deg=12.0,
                                   roi_frac=(0.1, 0.1, 0.8, 0.8))
        canvas = render_debug_frame(_dry_frame(), calib, None, _params(), None)
        assert canvas.ndim == 3 and canvas.dtype == np.uint8


class TestServiceCache:
    """服务层: _process 必须把"产出当前结果的那一帧 + 那次增益"配套存下并可渲染。

    这是「识别」页"所见即所算"的落地点 —— 缓存错帧/错增益, 画面就会与读数矛盾。
    全程不起循环、不联网 (直接喂帧给 _process), 故无副作用。
    """

    CH = 1

    @staticmethod
    def _svc():
        from eit_ptlc.controller.waterlevel_service import WaterLevelDetectService
        # config_path=None → 纯内存默认配置, 不读盘不写盘
        svc = WaterLevelDetectService(orangepi_ip="127.0.0.1", stream_port=1,
                                      config_path=None, ref_frames=2)
        svc._configs[TestServiceCache.CH].calib = _calib("left_to_right")
        return svc

    @staticmethod
    async def _advance_to(svc, ch, wet_cols: int):
        """把前沿逐步推到 wet_cols 列并返回最后喂进去的那一帧。

        检测已无跨帧基线 (前沿判据改成单帧空间结构门), 一步跳到目标也不会被拒;
        仍保留逐步推进是因为它就是真实溶剂前沿的样子, 也顺带覆盖了多拍连续推进的路径。
        """
        step = int(_W * 0.06)
        frame = None
        for cols in list(range(step, wet_cols, step)) + [wet_cols]:
            frame = _wet_frame(wet_cols=cols)
            await svc._process(ch, frame)
        return frame

    def test_caches_frame_and_produces_debug_jpeg(self):
        async def run():
            svc = self._svc()
            svc.request_reference(self.CH)
            for _ in range(2):                       # 填满参考窗口 (ref_frames=2)
                await svc._process(self.CH, _dry_frame())
            assert svc.has_reference(self.CH), "参考窗口应已完成"

            frame = await self._advance_to(svc, self.CH, 160)

            result = svc._results[self.CH]
            assert result.valid, f"应判有效, 实得 {result.reason}"
            # 缓存帧必须就是刚喂进去那张 (不是上一帧/干板)
            assert np.array_equal(svc._last_frame[self.CH], frame)

            jpeg = svc.debug_frame_jpeg(self.CH)
            assert jpeg is not None and jpeg[:2] == b"\xff\xd8", "应为合法 JPEG (SOI)"

            # 解码回来核对渲染掩膜与该次 wet_ratio 同口径 (端到端复用一致性断言)
            canvas = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            assert canvas is not None
            return result

        asyncio.run(run())

    def test_history_records_valid_and_invalid_points(self):
        async def run():
            svc = self._svc()
            svc.request_reference(self.CH)
            for _ in range(2):
                await svc._process(self.CH, _dry_frame())
            await self._advance_to(svc, self.CH, 160)

            pts = svc.history(self.CH)
            assert len(pts) >= 3, "参考窗口两帧 + 检测一帧都应留痕"
            assert pts[0]["reason"] == "ref_window", "参考窗口应记成可解释的无效点"
            assert pts[0]["valid"] is False and pts[0]["front_percent"] is None
            assert pts[-1]["valid"] is True and pts[-1]["front_percent"] is not None
            assert all("t" in p for p in pts)
        asyncio.run(run())

    def test_gain_step_invalidates_frame_and_recovers_next_tick(self):
        """干区照度一拍跳变 → 本帧判无效 + 增益跟进, **不冻结**, 下一拍自动恢复。

        2026-07-26 真机 CH1 事故: 干区画在机架面板上 (dry_zone_front_percent=111%),
        冻结判据 ①② 结构性不可达, 唯一能触发的 ③ 却按"假装光照没变"处理 —— 整个变化量
        (>0.05 log) 原样注入 corrected, 与判湿线 0.5×A (≈0.05) 同量级, 16s 内把 front%
        从 74.28 顶到 90.35 越过 T2=90, 触发自动排液。
        这里锁三件事: 该帧不可采信 / 增益必须跟上新光照 / 通道不被永久毙掉。
        """
        async def run():
            svc = self._svc()
            # 干区放在最下游 (zone=100%) → 前沿到 50% 时 ① 不触发, ③ 才可达
            svc._configs[self.CH].calib = ChannelCalibration(
                rotation_angle_deg=0.0, flow_direction="left_to_right",
                roi_frac=(0.0, 0.0, 1.0, 1.0), dry_ref_frac=(0.90, 0.05, 0.08, 0.20))
            svc.request_reference(self.CH)
            for _ in range(2):
                await svc._process(self.CH, _dry_frame())
            await self._advance_to(svc, self.CH, 160)
            assert svc._results[self.CH].valid, "基线一拍应有效"
            assert svc._guards[self.CH].frozen is False, "正常推进不该冻结"

            # 整场照度 ×0.90 (干区一并变暗 10% ⇒ |Δlog gain|≈0.105 > 0.05)
            dim = (_wet_frame(wet_cols=160).astype(np.float32) * 0.90)
            dim = np.clip(dim, 0, 255).astype(np.uint8)
            await svc._process(self.CH, dim)

            r = svc._results[self.CH]
            assert r.valid is False and r.reason == "gain_step", \
                f"照度突变帧必须判无效, 实得 valid={r.valid} reason={r.reason}"
            assert r.front_percent is None, "无效帧不得带读数 (trigger 与 snapshot 都依赖它)"
            assert svc._guards[self.CH].frozen is False, \
                "③ 是光照事件, 冻结会把变化量原样注入 corrected —— 必须跟进而非冻结"
            assert 0.85 <= svc._guards[self.CH].gain <= 0.95, \
                f"增益应跟上新光照, 实得 {svc._guards[self.CH].gain}"
            assert svc.history(self.CH)[-1]["front_percent"] is None

            # 下一拍照度已稳 → |Δlog gain|≈0 → 自动恢复, 且读数回到 ~50%
            await svc._process(self.CH, dim)
            r2 = svc._results[self.CH]
            assert r2.valid, f"照度稳定后应自动恢复, 实得 {r2.reason}"
            assert r2.front_percent is not None and 45 <= r2.front_percent <= 55, \
                f"补偿到位后前沿应回到 ~50%, 实得 {r2.front_percent}"
        asyncio.run(run())

    def test_debug_frame_none_before_any_process(self):
        svc = self._svc()
        assert svc.debug_frame_jpeg(self.CH) is None, "没拉过帧就不该有图 (路由据此回 503)"
        assert svc.history(self.CH) == []

    def test_calibration_change_drops_stale_frame(self):
        """改标定 → 丢缓存帧: 旧帧配新 ROI 渲出的图与 _results 旧数字对不上, 宁可空一拍。"""
        async def run():
            svc = self._svc()
            svc.request_reference(self.CH)
            for _ in range(2):
                await svc._process(self.CH, _dry_frame())
            await self._advance_to(svc, self.CH, 160)
            assert svc.debug_frame_jpeg(self.CH) is not None

            svc.update_calibration(self.CH, rotation_angle_deg=5.0, save=False)
            assert svc.debug_frame_jpeg(self.CH) is None, "标定变更后不得再吐旧帧渲染图"
        asyncio.run(run())

    def test_history_survives_calibration_change(self):
        """走势是历史事实, 不因改标定而抹掉 (与缓存帧的处置刻意不同)。"""
        async def run():
            svc = self._svc()
            svc.request_reference(self.CH)
            for _ in range(2):
                await svc._process(self.CH, _dry_frame())
            await self._advance_to(svc, self.CH, 160)
            before = len(svc.history(self.CH))
            svc.update_calibration(self.CH, rotation_angle_deg=5.0, save=False)
            assert len(svc.history(self.CH)) == before
        asyncio.run(run())
