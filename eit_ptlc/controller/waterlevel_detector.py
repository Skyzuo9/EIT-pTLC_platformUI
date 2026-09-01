"""液位检测核心 (上位机侧, 纯函数无状态)
==========================================
功能:
    把"溶剂前沿到达 ROI 的百分比位置"从一帧图像 + 标定参数算出来。
    取代香橙派 water_level_8ch_compress_mqtt.py 里 ChannelDetector.detect_water_level
    那套"算绝对高度 cm"的重管线 —— 检测从香橙派搬到上位机后, 这里是纯算法核心。

设计 (第一性原理 + 奥卡姆):
    - 目标量从"绝对高度 cm"改为"前沿到达 ROI 的百分比 (0~100)"。8 缸机械结构相同、
      相机等高, 百分比本就是无量纲相对量, 无需 QR 绝对标定 / scale_factor / cm 换算。
    - **唯一输出 = 前沿线位置** (front_percent): 沿垂直流向求均值得到一维 profile, 再在
      连续域上找半幅穿越点。"先平均后判定"把逐像素噪声压约 sqrt(行数) 倍, 且对"前沿线
      不纯平"天然鲁棒 —— 半幅穿越点就是前沿位置的中位数, U 形/倾斜前沿自动落到等效推进位置。
      曾并存的"面积占比"(浸润像素/ROI 总像素) 已删: 它是逐像素硬判定再平均, 噪声在阈值处
      被固化, 同一段真机数据上残差 RMS 是前沿线法的 3~5 倍 (2026-07-26 CH1)。浸润掩膜比
      wet_ratio 仍照常上报, 但只作诊断与渲染一致性锚点, 见 LevelResult.wet_ratio。
    - 干/湿分离 = **log 域乘性模型** (默认): 相机灰度 I = 照度L × 反射率R, 湿润是 R 的乘性
      下降, 加性差分信号正比局部照度 → 盖阴影带内被压到绝对阈值下 (结构性漏检)。log 域
      逐像素比值把 L 约掉, 阴影带湿信号与亮区等强; 全局照度漂移退化为乘性 gain, 由干参考区
      median 比值补偿。旧加性口径保留为 separation_mode="abs" (deprecated, 整定台 A/B 用)。
      无参考图退化到 Otsu, 置信下降。
    - 干参考区语义 = "运行窗口内不湿" (可画在板上, 同材质同受光; 避开阴影带尽量靠下游),
      不再要求"永不湿" —— 前沿逼近/打湿干区由 DryGainGuard 冻结兜底 (见下)。

无状态约定:
    本模块只回答"这一帧的前沿在哪", 不做时序滤波 / 前沿状态机 (WAITING/TRACKING/GONE) /
    中位数缓冲 —— 那些是上层拉帧检测服务 (P2) 的职责, 不污染纯函数。
    唯一显式例外: DryGainGuard —— 干区增益的微型时序守卫 (冻结/回滚需跨帧记忆),
    服务与整定台共用同一口径, 放本模块避免口径分叉。

坐标系兼容:
    rotation_angle_deg + roi_bbox 的语义与香橙派 _apply_manual_calibration 完全一致
    (roi_bbox 在"旋转后坐标系"), 便于 P3 把香橙派标定数据 1:1 迁移过来。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


# ====================================================================
# 数据模型
# ====================================================================
@dataclass
class WaterLevelDetectParams:
    """液位检测算法参数 (精简自香橙派 DEFAULT_DETECT_PARAMS, 砍掉 cm/scale/状态机相关)。

    字段:
        roi_crop_x/y:        ROI 内边缩进比例, 避开板框/反光边沿 (0~0.4)。
        blur_ksize:          高斯模糊核 (奇数, 抑噪)。
        separation_mode:     干湿分离口径: "log"(乘性模型, 默认) / "abs"(加性旧口径,
                             deprecated, 仅整定台 A/B 保留)。
        wet_pixel_threshold: [abs] 补偿后有符号差分 (变暗为正) > 此值判为"已浸润";
                             同时充当 analyze_front 的锚定地板 (灰度量级)。
        wet_rel_threshold:   [log] 相对变暗比例 k; 补偿后 log 差 > −log(1−k) 判湿。
                             默认 0.05 (真机整定 wet_thr 8.6 @ 亮区 ~180 灰度 ≈ 4.8% 自洽)。
                             同时充当 analyze_front 的锚定地板 (log 量级)。
        front_ratio_level:   前沿判定的**幅值比例** f (0~1): 沿流向的补偿差分列均值 c(x)
                             跌破 f×A 处判为前沿线 (A = 湿平台幅值, 见 analyze_front)。
                             0.5 = 半幅穿越。**旧口径是"二值列湿像素比跌破此值"** —— 绝对判湿线
                             在幅值中的相对位置会随 A (0.07~0.10) 漂到 51%~73%, 前沿位置跟着
                             run-to-run 漂; 改成相对幅值即消掉这项方差。同一个判湿线也用于
                             浸润掩膜, 使红色掩膜边界与前沿线同口径。
        front_gap_frac:      前沿扫描允许桥接的最大缺口宽度占 ROI 比例; 防边界伪迹用小值截停。
    """
    roi_crop_x: float = 0.10
    roi_crop_y: float = 0.10
    blur_ksize: int = 5
    separation_mode: str = "log"
    wet_pixel_threshold: float = 5.0
    wet_rel_threshold: float = 0.05
    front_ratio_level: float = 0.5
    front_gap_frac: float = 0.15
    # 自动排液触发阈值 (front_percent, 0~100; 每通道标定层真源 — D_f 常量前提, 见
    # docs/superpowers/specs/2026-07-13-waterlevel-auto-drain-design.md)
    trigger_percent_t2: float = 90.0   # T2: 命中即自动 develop.drain
    t1_offset: float = 15.0           # T1 = T2 - offset: 预告 (物理就位)


_LOG_EPS = 1.0   # log 域黑电平兜底 (log(0) 防护, 1~2 灰度量级)

# DryGainGuard 冻结常量 —— 安全轨而非整定目标, 硬编码不设旋钮 (现场经验要求再升 knob)
DRY_GUARD_FRONT_MARGIN_PCT = 10.0   # front 逼近干区的冻结边距 (percent)
DRY_GUARD_WET_FRAC = 0.15           # 干区自卫: 自补偿后仍判湿的像素占比上限 (部分打湿)
DRY_GUARD_GAIN_STEP = 0.05          # 单次 |Δlog gain| 上限 (整区突变/全淹, ≈5%/样本)

# ---- 前沿结构门常量 (安全轨而非整定目标, 硬编码不设旋钮; 同 DRY_GUARD_* 口径) ----
# 干拖尾判据的取样带宽 (占流向长度比例)。**不可退回单列判据**: 单列会被一列边缘伪迹打死 ——
# 2026-07-26 真机 CH1 实测 435 列中最流入侧 1 列恒 0 (缸壁反光 + 模糊核边界效应),
# 其余 434 列一致报前沿 44%, 却被旧的 seq[0] 单列门整体判成 front_percent=None。
PROFILE_EDGE_BAND_FRAC = 0.02

# 湿平台幅值 A 的取样带宽 (占流向长度比例, 自流入侧起算): 流入侧最先浸润、饱和最久,
# 其 median 是 A 的稳健估计。真机实测 A ≈ 0.085 (log 域), 随板/展开剂/照明在 0.07~0.10 浮动。
PLATEAU_SAMPLE_FRAC = 0.05


@dataclass
class ChannelCalibration:
    """单通道标定 (上位机侧真源, 取代香橙派 water_level_config.json 的 calibration+roi_manual)。

    字段:
        rotation_angle_deg: 使硅胶板边沿竖直的旋转角 (度); 与香橙派语义一致。
        roi_bbox:           (x, y, w, h), 在"旋转后坐标系"中的 ROI 像素矩形; None=未标定。
                            **遗留字段, 分辨率相关**: 仅当 roi_frac 缺失时回退使用。
        flow_direction:     left_to_right | right_to_left | bottom_to_top, 决定前沿从哪侧推进。
        roi_frac:           (fx, fy, fw, fh), 旋转后画面的**比例**(0~1); **分辨率无关**, 优先于
                            roi_bbox。监控档(如 360p)与活跃档(如 1080p)共用同一份 roi_frac,
                            检测时按当前帧尺寸还原像素框 → 换分辨率无需重标。
        dry_ref_frac:       (fx, fy, fw, fh) 旋转后画布比例; 板外永不湿的干参考区 (如金属面板),
                            用于每帧全局光照漂移补偿; None=不补偿。
    """
    rotation_angle_deg: float = 0.0
    roi_bbox: Optional[tuple[int, int, int, int]] = None
    flow_direction: str = "left_to_right"
    roi_frac: Optional[tuple[float, float, float, float]] = None
    dry_ref_frac: Optional[tuple[float, float, float, float]] = None

    @property
    def calibrated(self) -> bool:
        return self.roi_frac is not None or self.roi_bbox is not None

    def roi_pixels(self, rot_w: int, rot_h: int) -> Optional[tuple[int, int, int, int]]:
        """给定当前旋转后画面尺寸, 返回 ROI 像素框 (x, y, w, h)。

        优先用分辨率无关的 roi_frac 按 (rot_w, rot_h) 还原; 缺失时回退遗留像素 roi_bbox
        (此时随分辨率漂移, 仅在采集分辨率==标定分辨率时正确)。未标定返回 None。
        """
        if self.roi_frac is not None:
            fx, fy, fw, fh = self.roi_frac
            return (round(fx * rot_w), round(fy * rot_h),
                    round(fw * rot_w), round(fh * rot_h))
        return self.roi_bbox


@dataclass
class LevelResult:
    """单帧检测结果。

    字段:
        valid:         是否可信 (有信号且 ROI 有效); False 时 front_percent 不应被采纳。
        front_percent: **唯一测量输出** — 前沿线位置百分比 (0~100, 亚像素);
                       无有效过渡点时为 None。T1/T2 比的就是它 (见 waterlevel_trigger)。
        wet_ratio:     浸润掩膜像素比 (0~1) —— **诊断量, 不是测量值**。
                       它是网页上那片半透明红掩膜的数值化身: 用来看"湿区有没有洞"
                       (前沿参差/局部伪迹), 并作 render_debug_frame 与 detect_level
                       的口径一致性锚点 (test_waterlevel_render_offline 锁的就是它)。
                       **不要拿它当前沿读数**: 逐像素硬判定再平均会把噪声固化在阈值处,
                       同一段真机数据上它的残差 RMS 是 front_percent 的 3~5 倍
                       (2026-07-26 CH1: 50~70% 区间 1.33 vs 0.32), 且越接近满展开越抖 ——
                       湿区中段会塌向判湿线, 贴线像素被同一个 A 拴住整片翻转。
        diff_mean:     差分图均值 (信号强度指标; abs=灰度 / log=log单位; 无参考图时为 0)。
        drift:         [abs] 干参考区加性光照漂移 (灰度; 当前 − 参考, 变亮为正; log 模式恒 0)。
        gain:          [log] 干参考区乘性照度增益 (变亮 >1; abs 模式/无干区恒 1)。
        amplitude:     湿平台幅值 A (log 单位, 见 analyze_front)。判湿线是 A 的比例而非绝对值,
                       故 A 是本口径的核心可观测量: 它随板/展开剂/照明在 0.07~0.10 浮动,
                       前沿位置若跟着漂就说明相对化没生效。abs 模式/无参考时为 0。
        roi_size:      (w, h) 裁剪后 ROI 像素尺寸。
        reason:        valid=False 时的原因 (no_roi / empty_roi /
                       no_front 前沿未进 ROI / roi_saturated 整区判湿被判伪迹)。
    """
    valid: bool
    front_percent: Optional[float] = None
    wet_ratio: float = 0.0
    diff_mean: float = 0.0
    drift: float = 0.0
    gain: float = 1.0
    amplitude: float = 0.0
    roi_size: tuple[int, int] = (0, 0)
    reason: str = ""


# ====================================================================
# 几何: 旋转矩阵 (与香橙派 _rebuild_rotation_matrix 逐字一致, 保证标定可迁移)
# ====================================================================
def rotation_matrix(angle_deg: float, width: int, height: int):
    """由旋转角 + 原图尺寸重建 warpAffine 矩阵与旋转后画布尺寸。

    返回 (M, (new_w, new_h))。angle_deg=0 时 new_w/new_h == width/height。
    """
    center = (width / 2.0, height / 2.0)
    M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
    new_w = int(height * sin_a + width * cos_a)
    new_h = int(height * cos_a + width * sin_a)
    M[0, 2] += (new_w / 2.0) - center[0]
    M[1, 2] += (new_h / 2.0) - center[1]
    return M, (new_w, new_h)


def angle_to_make_line_vertical(dx: float, dy: float) -> float:
    """给定线段方向向量 (dx, dy)(旋转后显示坐标系, y 向下), 返回把该线转到竖直所需的
    增量旋转角 (度, 正角=逆时针, 与 cv2.getRotationMatrix2D 一致), 归一到 (-90, 90]。

    用途: 网页/整定台"画竖直参考边定角" —— 用户沿硅胶板竖直边点两点, 本函数给出让该边
    竖直的增量角, 累加到当前总角后从原始帧重渲 (角度可迭代逼近)。
    JS 端 (WaterLevelCalibrate.vue) 镜像本实现, 改此处须同步 JS。
    """
    theta = math.degrees(math.atan2(dy, dx))   # 线与 +x 轴夹角
    delta = theta - 90.0                        # 转到竖直 (θ=90°) 所需增量 (cv2 旋转方向核验后的符号)
    while delta <= -90.0:
        delta += 180.0
    while delta > 90.0:
        delta -= 180.0
    return delta


def box_to_roi_frac(x, y, w, h, rot_w: int, rot_h: int):
    """旋转后画布像素框 (x, y, w, h) → 分辨率无关 roi_frac (fx, fy, fw, fh)。
    是 ChannelCalibration.roi_pixels 的逆; rot_w/rot_h 为旋转后画布尺寸 (rotation_matrix 第二返回值)。
    """
    rot_w = max(1, int(rot_w))
    rot_h = max(1, int(rot_h))
    return (x / rot_w, y / rot_h, w / rot_w, h / rot_h)


# ====================================================================
# ROI 灰度预处理 (检测与参考图捕获共用, 保证两者像素对齐)
# ====================================================================
def effective_roi_rect(calib: ChannelCalibration, params: WaterLevelDetectParams,
                       rot_w: int, rot_h: int) -> Optional[tuple[int, int, int, int]]:
    """crop 内缩并夹到画布内后的**有效检测区**, 在旋转后坐标系中的 (x, y, w, h)。

    未标定 / roi 缺失 / 内缩后退化为空 → None。

    单一真源: extract_roi_gray 取的就是这块, 调试渲染的就地叠加/前沿线/绿框也全用它。
    渲染侧若自己重算这段夹取逻辑, 两处日后必然分叉 → 框与掩膜错位, 画出一张
    "看着可信但是错的"图, 故此处独此一份。
    """
    if not calib.calibrated:
        return None
    # 分辨率无关: 按当前旋转后画布尺寸还原 ROI 像素框 (roi_frac 优先, 回退 roi_bbox)
    roi_px = calib.roi_pixels(rot_w, rot_h)
    if roi_px is None:
        return None
    rx, ry, rw, rh = roi_px
    mx, my = int(rw * params.roi_crop_x), int(rh * params.roi_crop_y)
    rx_s, ry_s = rx + mx, ry + my
    rw_s, rh_s = rw - 2 * mx, rh - 2 * my

    rx_s = max(0, min(rx_s, rot_w - 1))
    ry_s = max(0, min(ry_s, rot_h - 1))
    rw_s = min(rw_s, rot_w - rx_s)
    rh_s = min(rh_s, rot_h - ry_s)
    if rw_s <= 0 or rh_s <= 0:
        return None
    return (rx_s, ry_s, rw_s, rh_s)


def extract_roi_gray(frame_bgr, calib: ChannelCalibration,
                     params: WaterLevelDetectParams):
    """旋转 → 按 roi_bbox+crop 提取 ROI → 灰度 → 模糊。

    返回裁剪后灰度 ROI (np.ndarray, uint8); 标定缺失或 ROI 退化为空时返回 None。
    与香橙派 _prepare_gray_roi 同算法, 使上位机检测与香橙派历史标定结果像素对齐。
    """
    if not calib.calibrated:
        return None
    h, w = frame_bgr.shape[:2]
    M, rotated_size = rotation_matrix(calib.rotation_angle_deg, w, h)
    rotated = cv2.warpAffine(frame_bgr, M, rotated_size)

    rect = effective_roi_rect(calib, params, rotated_size[0], rotated_size[1])
    if rect is None:
        return None
    rx_s, ry_s, rw_s, rh_s = rect

    roi = rotated[ry_s:ry_s + rh_s, rx_s:rx_s + rw_s]
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    ks = params.blur_ksize
    if ks > 1:
        gray = cv2.GaussianBlur(gray, (ks, ks), 0)
    return gray


@dataclass
class ReferenceBundle:
    """参考捕获产物: 干板 ROI 灰度 + 干参考区灰度 (漂移补偿基准; 无 dry_ref_frac 时 None)。"""
    plate_gray: np.ndarray
    dry_gray: Optional[np.ndarray] = None


def extract_dry_gray(frame_bgr, calib: ChannelCalibration,
                     params: WaterLevelDetectParams):
    """按 calib.dry_ref_frac 抽取干参考区灰度 (与板 ROI 同一套旋转/crop/模糊管线,
    保证参考帧与检测帧像素对齐)。未配置干区返回 None。"""
    if calib.dry_ref_frac is None:
        return None
    dry_calib = replace(calib, roi_frac=calib.dry_ref_frac, roi_bbox=None)
    return extract_roi_gray(frame_bgr, dry_calib, params)


def compute_reference(frame_bgr, calib: ChannelCalibration,
                      params: Optional[WaterLevelDetectParams] = None):
    """从一帧"干板"图抽取参考 (板 ROI 灰度 + 干参考区灰度); 板 ROI 失败返回 None。"""
    params = params or WaterLevelDetectParams()
    plate = extract_roi_gray(frame_bgr, calib, params)
    if plate is None:
        return None
    return ReferenceBundle(plate_gray=plate,
                           dry_gray=extract_dry_gray(frame_bgr, calib, params))


# Otsu 回退路径的判湿地板。该路径的 corrected 是"逐像素 0/1 判湿"伪造场, 列均值即"列湿像素比",
# 单位既不是 log 也不是灰度, 故**不能**用 _wet_floor(params): abs 模式下 5.0 灰度的地板会把
# 一整块 0/1 场判成"没湿", 半湿板悄无声息地报 0%。取 0.5 = "该列半数以上像素判湿", 与旧口径
# front_ratio_level 作用在列湿比上完全一致。
_OTSU_WET_FLOOR = 0.5


def _wet_floor(params: WaterLevelDetectParams) -> float:
    """判"这个像素/这段平台算不算湿"的**绝对**阈值, 与 corrected 同单位。

    唯一真源: separate_wet 的逐像素判湿与 analyze_front 的流入侧锚定必须用同一条线, 否则会
    出现"掩膜说湿、锚定说没到"之类的自相矛盾。
    log 模式 corrected 是 log 量级 (−log(1−k), ~0.05); abs 模式是灰度量级 (~5~30)。
    """
    if params.separation_mode == "abs":
        return float(params.wet_pixel_threshold)
    k = min(max(params.wet_rel_threshold, 1e-4), 0.9)
    return math.log(1.0 / (1.0 - k))


def separate_wet(gray, ref: ReferenceBundle, dry_now,
                 params: WaterLevelDetectParams,
                 gain_override: Optional[float] = None):
    """干/湿分离 (detect_level 与整定台共用口径)。返回 (wet_mask, drift, corrected, gain)。

    log 模式 (默认): 乘性模型 I = L·R —— 湿润是反射率乘性下降, 加性差分正比局部照度
    (阴影带信号被压缩), 故在 log 域逐像素比值把照度约掉:
        gain      = median((干区当前+ε)/(干区参考+ε))          # 全局照度增益, 变亮 >1
        corrected = log(板参考+ε) − log(板当前+ε) + log(gain)   # 湿润变暗为正
        wet       ⇔ corrected > −log(1−k),  k = wet_rel_threshold
    gain_override 非 None 时跳过干区自测 (由 DryGainGuard 过滤后注入); drift 恒 0。

    abs 模式 (旧口径, deprecated 留整定台 A/B): 有符号差分 + 加性漂移:
        drift     = median(干区当前 − 干区参考)   # 全局变亮为正
        corrected = (板参考 − 板当前) + drift      # 湿润变暗为正, 漂移被抵消
        wet       ⇔ corrected > wet_pixel_threshold;  gain 恒 1。
    两种模式下干区缺失/shape 不符均不补偿 (drift=0 / gain=1)。
    """
    if params.separation_mode == "abs":
        diff = ref.plate_gray.astype(np.float32) - gray.astype(np.float32)
        drift = 0.0
        if (ref.dry_gray is not None and dry_now is not None
                and dry_now.shape == ref.dry_gray.shape):
            drift = float(np.median(dry_now.astype(np.float32)
                                    - ref.dry_gray.astype(np.float32)))
        corrected = diff + drift
        return corrected > _wet_floor(params), drift, corrected, 1.0

    log_ref = np.log(ref.plate_gray.astype(np.float32) + _LOG_EPS)
    log_now = np.log(gray.astype(np.float32) + _LOG_EPS)
    if gain_override is not None:
        gain = float(gain_override)
    elif (ref.dry_gray is not None and dry_now is not None
            and dry_now.shape == ref.dry_gray.shape):
        ratio = ((dry_now.astype(np.float32) + _LOG_EPS)
                 / (ref.dry_gray.astype(np.float32) + _LOG_EPS))
        gain = float(np.clip(np.median(ratio), 0.1, 10.0))
    else:
        gain = 1.0
    corrected = log_ref - log_now + math.log(max(gain, 1e-6))
    return corrected > _wet_floor(params), 0.0, corrected, gain


def measure_dry_gain(frame_bgr, calib: ChannelCalibration, ref: ReferenceBundle,
                     params: WaterLevelDetectParams) -> Optional[tuple[float, float]]:
    """量一帧的干区乘性增益 (log 模式漂移补偿输入) + 干区自卫统计。

    返回 (gain, dry_wet_frac):
        gain         = median((干区当前+ε)/(干区参考+ε)), clip 0.1~10;
        dry_wet_frac = 以自测 gain 补偿后干区内仍判湿的像素占比 —— >0 说明干区被
                       **部分**打湿 (median 对 <50% 污染鲁棒, 供守卫自卫判据);
                       整区同步突变 (全淹) 会被 median 吸收, 由守卫步限兜。
    干区不可用 (无 dry_ref_frac / 参考无干区 / shape 不符) → None。
    """
    if ref is None or ref.dry_gray is None:
        return None
    dry_now = extract_dry_gray(frame_bgr, calib, params)
    if dry_now is None or dry_now.shape != ref.dry_gray.shape:
        return None
    dry_ref = ref.dry_gray.astype(np.float32) + _LOG_EPS
    now = dry_now.astype(np.float32) + _LOG_EPS
    gain = float(np.clip(np.median(now / dry_ref), 0.1, 10.0))
    corrected = np.log(dry_ref) - np.log(now) + math.log(gain)
    k = min(max(params.wet_rel_threshold, 1e-4), 0.9)
    wet_frac = float((corrected > math.log(1.0 / (1.0 - k))).mean())
    return gain, wet_frac


def dry_zone_front_percent(calib: ChannelCalibration,
                           params: Optional[WaterLevelDetectParams] = None,
                           ) -> Optional[float]:
    """干区上游沿在检测 ROI (crop 后) 流向坐标中的位置 (%, 与 front_percent 同量纲)。

    守卫用: front_max ≥ 本值 − DRY_GUARD_FRONT_MARGIN_PCT 时冻结 gain。仅当 roi_frac 与
    dry_ref_frac 皆有时可算 (遗留 roi_bbox-only 通道 → None, 守卫退化为自卫+步限)。
    允许 <0 / >100: 干区在 ROI 外 (如板外面板) → 恒不触发 front 冻结, 语义正确。
    """
    if calib.roi_frac is None or calib.dry_ref_frac is None:
        return None
    params = params or WaterLevelDetectParams()
    fx, fy, fw, fh = calib.roi_frac
    dx, dy, dw, dh = calib.dry_ref_frac
    if calib.flow_direction == "bottom_to_top":
        span = fh * (1.0 - 2.0 * params.roi_crop_y)
        if span <= 0:
            return None
        inflow = fy + fh - fh * params.roi_crop_y      # 流入侧 = 底
        return round((inflow - (dy + dh)) / span * 100.0, 2)
    span = fw * (1.0 - 2.0 * params.roi_crop_x)
    if span <= 0:
        return None
    if calib.flow_direction == "right_to_left":
        inflow = fx + fw - fw * params.roi_crop_x      # 流入侧 = 右
        return round((inflow - (dx + dw)) / span * 100.0, 2)
    inflow = fx + fw * params.roi_crop_x               # 流入侧 = 左
    return round((dx - inflow) / span * 100.0, 2)


@dataclass
class DryGainGuard:
    """干区增益的微型时序守卫: 冻结/回滚 (模块"无状态约定"的唯一显式例外)。

    干区语义放宽为"运行窗口内不湿"后, 前沿终会打湿干区 —— 若继续采信 gain,
    median(湿区比值) ≪ 1 会把已湿像素"补"回干判定, 读数崩塌。守卫按帧过滤:
      ① front 逼近: front_max ≥ 干区上游沿 − MARGIN → 冻结 (单调, 不解冻);
      ② 干区自卫: dry_wet_frac 超限 (部分打湿) → 冻结并回滚上一可信值;
      ③ 步限: 单次 |Δlog gain| 超限 → **不冻结**, 跟上新 gain 并判本帧不可信。
    ①② 是"gain 测量被信号污染", 冻结(保持旧值)才对; ③ 语义相反, 见下。
    用法 (服务与整定台同口径): 每帧 measure_dry_gain → guard.filter → 作
    gain_override 传给 detect_level。重抓参考/改标定后应重建守卫。

    ③ 为什么必须跟上而不是冻结 (本类正确性的核心依据):
        ③ 的物理含义是"干区整体亮度一拍内跳变超过 DRY_GUARD_GAIN_STEP", 即**光照真变了**。
        此时冻结 = 假装没变, corrected = log(ref) − log(now) + log(旧gain) 会把整个变化量
        原样注入全场; 而变化量 (>5% ⇒ >0.05 log) 与判湿线 0.5×A (≈0.05) 同量级, 一次冻结
        就足以把整个干区抬过线 (2026-07-26 真机 CH1: 16s 内 front% 由 74.28 跳到 90.35,
        diff_mean 由 0.0517 翻到 0.1122, 直接顶穿 T2=90 触发自动排液)。
        安全性由控制流保证, 不需要额外参数: ① 在本方法开头先判并提前 return, 所以能走到
        ③ 就说明前沿尚未逼近干区 ⇒ 干区不可能被淹 ⇒ ③ 只可能是光照事件, 绝不会是
        "整区全淹被 median 吸收"。后者永远先被 ① 拦下。
        亦不会永久毙掉通道: 新 gain 成为基线后下一拍 |Δlog gain| 归小, 检测自动恢复;
        光照持续闪烁则每拍不可信, 曲线上表现为断口 —— 那正是应该被看到的真实信号。

    返回约定:
        filter() 返回 (gain, trusted)。trusted=False 仅表示**本帧**补偿不可信 (参考图是
        旧光照下拍的, 新 gain 只能纠乘性分量), 调用方应把该帧记为无效而非采纳其读数。
    """
    gain: float = 1.0
    frozen: bool = False
    reason: str = ""

    def filter(self, measure: Optional[tuple[float, float]],
               front_percent: Optional[float],
               zone_percent: Optional[float]) -> tuple[float, bool]:
        if (not self.frozen and front_percent is not None and zone_percent is not None
                and front_percent >= zone_percent - DRY_GUARD_FRONT_MARGIN_PCT):
            self.frozen = True
            self.reason = "front_near_dry_zone"
        if self.frozen or measure is None:
            return self.gain, True
        gain, wet_frac = measure
        if wet_frac > DRY_GUARD_WET_FRAC:
            self.frozen = True
            self.reason = "dry_zone_wet"
            return self.gain, True
        if abs(math.log(max(float(gain), 1e-6))
               - math.log(max(self.gain, 1e-6))) > DRY_GUARD_GAIN_STEP:
            # 光照真变了: 跟上新 gain 作为后续基线, 但本帧的参考图仍属旧光照, 不可采信。
            # 不动 self.reason —— 该字段是**冻结**原因, 本分支不冻结; 这一拍的可见信号是
            # 调用方据 trusted=False 记下的 reason="gain_step" 无效点。
            self.gain = float(gain)
            return self.gain, False
        self.gain = float(gain)
        return self.gain, True


# ====================================================================
# 前沿解析 (连续域, 单帧无状态; detect_level 与调试渲染共用同一口径)
# ====================================================================
@dataclass
class FrontAnalysis:
    """一帧的前沿解析产物 (analyze_front 输出)。

    字段:
        verdict:       ok / no_front (前沿未进 ROI, 物理正常等待) /
                       roi_saturated (整区判湿, 判为照度突变伪迹)
        front_percent: 前沿线位置 (0~100, 亚像素); verdict != "ok" 时为 None。
        amplitude:     湿平台幅值 A (log 单位), 由流入侧平台 median 估出。
        level:         判湿线 = front_ratio_level × A (log 单位); 浸润掩膜与前沿线共用它。
        profile:       沿流向的补偿差分均值 c, **已按流向反转** (索引 0 恒为流入侧)。
    """
    verdict: str
    front_percent: Optional[float] = None
    amplitude: float = 0.0
    level: float = 0.0
    profile: Optional[np.ndarray] = None


def analyze_front(corrected, flow_direction: str,
                  params: WaterLevelDetectParams,
                  wet_floor: Optional[float] = None) -> FrontAnalysis:
    """由补偿后差分场解析溶剂前沿位置与形状合理性 (连续域, 单帧无状态)。

    功能:
        先沿垂直于流向的轴取均值得到一维 c(x), 再在连续域上定位前沿并判断形状是否讲得通。
        三处与旧口径的实质差别:

        1) **先平均后判定**。旧口径逐像素二值化再取列比例, 噪声在阈值处被固化成横向锯齿
           (真机实测掩膜边界逐行 std 6.6px, 跨度 9.2% ROI); 先对 ROI 高度方向求均值可把
           逐像素噪声压约 sqrt(行数) 倍, 再判定就没有逐行决策可抖。
        2) **判湿线相对幅值而非绝对值**。相机灰度差分幅值 A 随板/展开剂/照明在 0.07~0.10
           浮动, 死阈值在幅值中的相对位置随之在 51%~73% 漂, 前沿位置跟着 run-to-run 漂;
           取 f×A 即把这项方差消掉 (常数偏差无害, 会被 T2 标定吸收, 方差才伤 Rf 复现)。
        3) **形状本身即伪迹判据**。真前沿 = 流入侧高台 + 一次锐降 + 下游干拖尾; 整帧照度/
           曝光突变把整条 c(x) 抬平, 下游拖尾一并过线。单帧即可分 ⇒ 不需要跨帧基线 ⇒
           不可能像旧的时序步长门那样, 因基线停在旧值而把后续每一拍都永久拒掉。

    参数:
        corrected:      separate_wet 产出的补偿后差分场 (log 域, 湿润为正), 形状同 ROI
        flow_direction: left_to_right | right_to_left | bottom_to_top, 决定流入侧在哪端
        params:         检测参数, 取 wet_pixel_threshold / wet_rel_threshold /
                        front_ratio_level / front_gap_frac
        wet_floor:      锚定地板, 须与 corrected **同单位**; None = 按 separation_mode 取
                        (_wet_floor)。Otsu 回退路径的 corrected 是 0/1 判湿场, 两种模式的
                        地板都不适用, 由调用方显式传 _OTSU_WET_FLOOR。

    返回:
        FrontAnalysis; verdict != "ok" 时 front_percent 为 None, 但 amplitude/level/profile
        仍照常带回供排查。
    """
    # 水平流沿 x 推进 → 对行取均值; 垂直流沿 y 推进 → 对列取均值
    axis = 1 if flow_direction == "bottom_to_top" else 0
    c = np.asarray(corrected, dtype=np.float32).mean(axis=axis)
    n = int(c.size)
    if n == 0:
        return FrontAnalysis(verdict="no_front")
    # 流入侧统一摆到索引 0: left_to_right 自小端进, 另两个自大端进
    inflow_from_high = flow_direction in ("right_to_left", "bottom_to_top")
    seq = c[::-1] if inflow_from_high else c

    # 幅值: 流入侧最先浸润、饱和最久, 取其 median 作 A 的稳健估计
    head = max(1, int(round(n * PLATEAU_SAMPLE_FRAC)))
    amplitude = float(np.median(seq[:head]))

    # 锚定: 流入侧平台自己得真湿。用既有判湿线作绝对地板, 不依赖 A 本身 —— 若拿 f×A 去判 A
    # 则恒真, 是循环判据。
    # 地板必须与 corrected **同单位**: log 模式是 log 量级 (~0.05), abs 模式是灰度量级
    # (~5~30), Otsu 回退是 0/1 湿比。早先一律用 log 地板, abs 模式下 0.0513 恒被超过 ⇒
    # 干板也"锚定成功", no_front 永不触发。
    if wet_floor is None:
        wet_floor = _wet_floor(params)
    if amplitude < wet_floor:
        # 平台未湿 ⇒ f×A 无意义 (可能 ≤0, 会把噪声整片判湿), 掩膜退回绝对判湿线
        return FrontAnalysis(verdict="no_front", amplitude=amplitude,
                             level=wet_floor, profile=seq)

    level = float(params.front_ratio_level) * amplitude

    # 干拖尾: 真前沿的下游必然还干; 下游边带也过线 = 整条 c(x) 被抬平 = 照度突变伪迹。
    # 取边带 median 而非单列: 单列会被一列边缘伪迹打死 (见 PROFILE_EDGE_BAND_FRAC)。
    band = max(1, int(round(n * PROFILE_EDGE_BAND_FRAC)))
    if float(np.median(seq[-band:])) >= level:
        return FrontAnalysis(verdict="roi_saturated", amplitude=amplitude,
                             level=level, profile=seq)

    # 限宽跨洞扫描: 取**最远**过线索引, 连续缺口超过 gap_limit 才截停。
    # 物理依据: 湿区从流入侧连续推进, 中段掉线是光度问题而非干燥; 但远端孤立伪迹不应把前沿
    # 骗到 100%, 故缺口限宽。
    #
    # ⚠ 不要往这个循环里加"收紧采信"的判据。已经踩过一次的坑:
    #   曾加过"桥接后的续段长度须 > 被跨过的缺口长度才采信 last", 想借此挡下游孤立伪迹。
    #   但真实前沿是一段**毛细指进带** —— 带内逐列湿行占比在 0~1 反复起伏, c(x) 多次穿越
    #   level 且沟与坎宽度相当, 该判据几乎必然不成立, last 被钉死在满湿平台边缘, 于是前沿
    #   读数系统性滞后, 且指进带随展开推进变宽 ⇒ 滞后越走越大 (2026-07-26 真机 CH1 合成复算:
    #   指进带 8%/13%/16% 时分别滞后 3.7/3.9/6.0 pp)。这正是本函数在 commit 1082219 之前
    #   "停在第一个跌破 level 的列"的老 bug, 加收紧判据等于把那次修复撤销。
    #   下游孤立伪迹**不在本函数处理**: 改由 ROI 下游端收缩 (标定层) 把伪迹排除在检测区外。
    #   护栏见 test_waterlevel_detector_offline 的 front_reaches_through_fingering_band。
    gap_limit = max(1, int(round(n * params.front_gap_frac)))
    last = 0
    gap = 0
    for i in range(1, n):
        if seq[i] >= level:
            last = i
            gap = 0
        else:
            gap += 1
            if gap > gap_limit:
                break

    # 亚像素: 在 last 与 last+1 之间对 c 线性插值, 求 c = level 的真实穿越点
    frac = 0.0
    if last + 1 < n:
        drop = float(seq[last]) - float(seq[last + 1])
        if drop > 0.0:
            frac = min(max((float(seq[last]) - level) / drop, 0.0), 1.0)
    return FrontAnalysis(verdict="ok",
                         front_percent=round((last + 1 + frac) / n * 100.0, 2),
                         amplitude=amplitude, level=level, profile=seq)


# ====================================================================
# 核心检测: 一帧 → 占比
# ====================================================================
def detect_level(frame_bgr, calib: ChannelCalibration,
                 ref: Optional[ReferenceBundle] = None,
                 params: Optional[WaterLevelDetectParams] = None,
                 gain_override: Optional[float] = None) -> LevelResult:
    """检测溶剂前沿到达 ROI 的百分比位置 (前沿线法; 掩膜仅作诊断)。

    Args:
        frame_bgr: 原始 BGR 帧 (香橙派抓取, 未旋转未裁剪)。
        calib:     通道标定 (旋转角 + ROI + 流向)。
        ref:       参考 bundle (compute_reference 产出); None 则走 Otsu 回退。
        params:    检测参数; None 用默认。
        gain_override: [log] 外部注入的干区增益 (DryGainGuard 过滤产物); 给定则
                       跳过帧内干区自测。abs 模式忽略。

    Returns:
        LevelResult。valid=False 时 front_percent 不应被采纳 (reason 给出原因)。
    """
    params = params or WaterLevelDetectParams()

    gray = extract_roi_gray(frame_bgr, calib, params)
    if gray is None:
        return LevelResult(valid=False, reason="no_roi" if calib.calibrated else "no_roi")

    roi_h, roi_w = gray.shape[:2]

    # --- 干/湿分离: log 域乘性 (默认) / abs 加性 (deprecated), 无参考退化 Otsu ---
    if ref is not None and ref.plate_gray.shape == gray.shape:
        dry_now = None if gain_override is not None else \
            extract_dry_gray(frame_bgr, calib, params)
        _abs_mask, drift, corrected, gain = separate_wet(
            gray, ref, dry_now, params, gain_override)
        # diff_mean 只作信号强度指标上报, **不当门**: 它是整个 ROI 的均值, 量的是"变了多大
        # 面积"而非"有没有变" —— 一条真实前沿占 16% 面积 × 幅值 0.085 ≈ 0.013, 会被一个
        # 0.013 的下限整帧毙掉 (2026-07-26 真机 CH1: 掩膜明明 wet_ratio=0.157 且头湿尾干,
        # 数字却全 0、曲线空白、前沿线不画)。"前沿到没到"是局部判据, 由 analyze_front 的
        # 锚定测试回答并发 no_front。
        diff_mean = float(np.abs(corrected).mean())
        wet_floor = None                     # 按 separation_mode 取
    else:
        # 无参考图: Otsu 双峰分割 (湿区通常更暗 → 取暗侧为湿)。把二值掩膜当成退化的差分场
        # 喂给 analyze_front, 其列均值就是"该列湿像素比" —— 无参考也不另开一条前沿代码路径
        # (两条路径日后必然分叉)。地板须显式给 _OTSU_WET_FLOOR, 见该常量说明。
        # 注意此路径下 A = 流入侧列湿比的 median, 只有流入段接近全湿时才 ≈1; 流入段本身半湿时
        # A 会明显小于 1, 判湿线随之压低、前沿外推。这不影响控制: 无参考的读数本就被 wait_level
        # 判 config:no_reference 拒收 (页面也挂红条警告), 此处只求不崩且有个能看的画面。
        drift = 0.0
        gain = 1.0
        diff_mean = 0.0
        _t, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        corrected = (otsu > 0).astype(np.float32)
        wet_floor = _OTSU_WET_FLOOR

    # --- 前沿解析 (连续域): 判湿线 = f × 湿平台幅值, 掩膜与前沿线同出这一条线 ---
    # 读数只由 analyze_front 出 (先沿垂直流向求均值再判定, 噪声压 √行数)。掩膜比 wet_ratio
    # 仍照常算, 但只作诊断/渲染一致性锚点 —— 见 LevelResult.wet_ratio 的说明。
    fa = analyze_front(corrected, calib.flow_direction, params, wet_floor)
    wet_mask = corrected > fa.level
    wet_ratio = float(wet_mask.mean())

    if fa.verdict != "ok":
        # 形状讲不通 (前沿未进 / 整区被抬平): 掩膜比与幅值照常带回供排查, 但不可采信
        return LevelResult(valid=False, wet_ratio=wet_ratio,
                           diff_mean=diff_mean, drift=drift, gain=gain,
                           amplitude=fa.amplitude, roi_size=(roi_w, roi_h),
                           reason=fa.verdict)

    return LevelResult(
        valid=True,
        front_percent=fa.front_percent,
        wet_ratio=wet_ratio,
        diff_mean=diff_mean,
        drift=drift,
        gain=gain,
        amplitude=fa.amplitude,
        roi_size=(roi_w, roi_h),
        reason="",
    )


# ====================================================================
# 调试可视化: 一帧 → 叠加画面 (网页「识别」页签的图源)
# ====================================================================
# 叠加色 (BGR), 与前端中文图例一一对应, 改此处须同步 WaterLevelDetect.vue 的图例
_VIS_ROI_FULL = (0, 255, 255)     # 黄: ROI 全框
_VIS_ROI_CROP = (0, 255, 0)       # 绿: crop 后有效检测区
_VIS_DRY_REF = (0, 128, 255)      # 橙: 干参考区 (BGR, 勿写成 (255,128,0) — 那是天蓝, 会与前沿线撞色)
_VIS_WET = (0, 0, 255)            # 红: 判为浸润的像素
_VIS_FRONT = (255, 160, 0)        # 天蓝: 前沿线

# 就地叠加的红色混合权重: 太高盖住板面纹理 (等于把那块涂没, 反而没法判断红得对不对),
# 太低看不见。0.45 在真机灰板 (~150-180 灰度) 上实测既显眼又透得出纹理。
_VIS_INPLACE_ALPHA = 0.45


def render_debug_frame(frame_bgr, calib: ChannelCalibration,
                       ref: Optional[ReferenceBundle] = None,
                       params: Optional[WaterLevelDetectParams] = None,
                       result: Optional[LevelResult] = None,
                       gain_override: Optional[float] = None,
                       inplace_overlay: bool = True):
    """把一帧检测渲染成可视化叠加图。

    版面: 单幅整帧 (旋转后) + 标定框; inplace_overlay 时湿区半透明红 + 前沿线**就地**
    画在有效检测区内 —— 识别结果直接落在板面真实位置上, 一眼看出判到哪了。

    与 detect_level **严格同口径**: 掩膜经同一个 separate_wet 复算, 且 gain_override 必须
    传入产出 result 的那一次守卫过滤值 —— 否则渲染会自测干区增益, 掩膜与 result.wet_ratio
    不是同一口径, 画面就会骗人 (回归锁见 test_waterlevel_render_offline)。

    参数:
        frame_bgr:      原始 BGR 帧 (须与产出 result 的那一帧同一张)
        calib:          通道标定
        ref:            参考 bundle; None 则与 detect_level 一样退化 Otsu
        params:         检测参数; None 用默认
        result:         该帧的 detect_level 结果; 供画前沿线与 HUD, None 则只画标定框
        gain_override:  产出 result 时用的守卫增益; 语义同 detect_level
        inplace_overlay: 是否在原图上就地涂湿区/画前沿线。False 时板面完全不着色也不画
                        前沿线, 只剩三个标定框与 HUD —— 供与开启态对照, 看算法判的边界
                        与真实干湿边界差多少。

    返回:
        BGR ndarray (与旋转后帧同尺寸); 标定缺失时只给旋转原图 + HUD, 不画框。
    """
    params = params or WaterLevelDetectParams()

    h, w = frame_bgr.shape[:2]
    M, (rot_w, rot_h) = rotation_matrix(calib.rotation_angle_deg, w, h)
    rotated = cv2.warpAffine(frame_bgr, M, (rot_w, rot_h))
    rect = effective_roi_rect(calib, params, rot_w, rot_h)

    # --- 掩膜先算 (就地叠加用; sep_label 也在此分支定, HUD 要报口径) ---
    gray = extract_roi_gray(frame_bgr, calib, params)
    wet_mask = None
    sep_label = "no_roi"
    if gray is not None:
        if ref is not None and ref.plate_gray.shape == gray.shape:
            # 逐字镜像 detect_level: 有 override 就不再自测干区 (否则口径分叉)
            dry_now = None if gain_override is not None else \
                extract_dry_gray(frame_bgr, calib, params)
            _abs_mask, _drift, corrected, _gain = separate_wet(
                gray, ref, dry_now, params, gain_override)
            sep_label = params.separation_mode
            wet_floor = None
        else:
            _t, otsu = cv2.threshold(gray, 0, 255,
                                     cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            corrected = (otsu > 0).astype(np.float32)
            sep_label = "otsu"
            wet_floor = _OTSU_WET_FLOOR      # 必须与 detect_level 的 Otsu 分支逐字一致
        # 判湿线同样过 analyze_front 取 f×A —— 与 detect_level 同为
        # (gray, ref, dry_now, params, gain_override) 的纯函数, 同输入必同输出,
        # 故掩膜与 result 里的数字严格同口径 (回归锁见 test_waterlevel_render_offline)
        wet_mask = corrected > analyze_front(
            corrected, calib.flow_direction, params, wet_floor).level

    # --- 画布: 旋转帧 + (可选) 就地叠加 + 标定框 ---
    canvas = rotated.copy()
    # 就地叠加须在画框之前: 框压在涂色之上才清晰, 且不会被半透明混合冲淡
    if inplace_overlay and rect is not None and wet_mask is not None:
        rx_s, ry_s, rw_s, rh_s = rect
        sub = canvas[ry_s:ry_s + rh_s, rx_s:rx_s + rw_s]   # 视图, 写它即写 canvas
        # 半透明混合而非直接涂实: 保留板面纹理, 才看得出"红的地方是不是真的湿"
        sub[wet_mask] = (sub[wet_mask] * (1.0 - _VIS_INPLACE_ALPHA)
                         + np.array(_VIS_WET, np.float32) * _VIS_INPLACE_ALPHA
                         ).astype(np.uint8)
        _draw_front_line(canvas, rect, result, calib.flow_direction)

    roi_px = calib.roi_pixels(rot_w, rot_h) if calib.calibrated else None
    if roi_px is not None:
        rx, ry, rw_, rh_ = roi_px
        cv2.rectangle(canvas, (rx, ry), (rx + rw_, ry + rh_), _VIS_ROI_FULL, 1)
    if rect is not None:
        # 绿框用有效矩形 (夹取后) 而非 rx+mx: 必须与就地叠加锚在同一块, 否则 ROI 越界时
        # 框会与真正的检测区错开
        rx_s, ry_s, rw_s, rh_s = rect
        cv2.rectangle(canvas, (rx_s, ry_s), (rx_s + rw_s, ry_s + rh_s), _VIS_ROI_CROP, 2)
    if calib.dry_ref_frac is not None:
        dfx, dfy, dfw, dfh = calib.dry_ref_frac
        cv2.rectangle(canvas, (round(dfx * rot_w), round(dfy * rot_h)),
                      (round((dfx + dfw) * rot_w), round((dfy + dfh) * rot_h)),
                      _VIS_DRY_REF, 1)

    _draw_hud(canvas, result, sep_label)
    return canvas


def _draw_front_line(img, rect, result: Optional[LevelResult],
                     flow_direction: str) -> None:
    """在 img 的 rect=(x, y, w, h) 区域内画前沿线 (原地改 img)。

    收绝对矩形而非子视图: cv2 在非连续切片上绘图行为不可靠 (线可能画不上或越界),
    故传绝对坐标让 cv2 直接写整幅画布。

    front_percent 是"从流入侧起算"的百分比, 故各流向的起算边不同:
        left_to_right → 从左量, right_to_left → 从右量, bottom_to_top → 从下量。
    result 缺失或前沿尚未出现 (front_percent=None) 则不画。
    """
    if result is None or result.front_percent is None:
        return
    rx, ry, rw, rh = rect
    frac = min(max(float(result.front_percent) / 100.0, 0.0), 1.0)
    if flow_direction == "bottom_to_top":
        y = ry + int(round((1.0 - frac) * (rh - 1)))      # 从下往上推进
        cv2.line(img, (rx, y), (rx + rw - 1, y), _VIS_FRONT, 2)
        return
    if flow_direction == "right_to_left":
        x = rx + int(round((1.0 - frac) * (rw - 1)))      # 从右往左推进
    else:
        x = rx + int(round(frac * (rw - 1)))              # 默认 left_to_right
    cv2.line(img, (x, ry), (x, ry + rh - 1), _VIS_FRONT, 2)


def _draw_hud(canvas, result: Optional[LevelResult], sep_label: str) -> None:
    """左上角叠 ASCII 数值 HUD (原地改 canvas)。

    只放数字不放文案: cv2.putText 渲染不了中文, 中文标签/图例一律由前端 Vue 层画。
    黑色粗描边 + 彩色细字, 保证在亮/暗画面上都读得清。
    """
    if result is None:
        lines = [f"sep={sep_label}"]
        color = (60, 220, 255)
    else:
        front = "-" if result.front_percent is None else f"{result.front_percent:.1f}"
        lines = [
            f"valid={result.valid} reason={result.reason or '-'} sep={sep_label}",
            f"front={front}%  wet={result.wet_ratio:.3f}",
            f"diff={result.diff_mean:.4g}  gain={result.gain:.4f}  roi={result.roi_size}",
            f"A={result.amplitude:.4f}",
        ]
        color = (0, 255, 0) if result.valid else (0, 165, 255)
    y = 18
    for i, txt in enumerate(lines):
        c = color if i == 0 else (60, 220, 255)
        cv2.putText(canvas, txt, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(canvas, txt, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    c, 1, cv2.LINE_AA)
        y += 20


