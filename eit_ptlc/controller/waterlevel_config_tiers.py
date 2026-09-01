"""液位配置分层网关 (参数分三层 + 所有权 + frac 派生 + 一致性判据)
================================================================
第一性原理 (见 docs/superpowers/specs/2026-07-10-waterlevel-config-tiers-design.md):
    液位标定真源 water_level_calib.json 的每个参数按"定它需要什么信息"天然分三层, 层即所有权:
      - 全局·判据 (WaterLevelDetectParams 全字段): 一段时序录制才能定 → CLI 回放整定拥有;
      - 全局·尺寸  (ROI 像素 w,h, 在参考分辨率下): 同上 → CLI 拥有;
      - 逐通道·位姿 (rotation / flow / ROI 位置 x,y): 实时画面即可定 → 网页标定 UI 拥有。
    本模块是唯一懂"谁属哪层 / frac 如何由 px 派生 / 什么算漂"的网关。两个薄面 (网页/CLI)
    各自只提交自己拥有的层; apply_commit 是唯一的按层过滤写入点 (越权字段被丢弃)。

刻意约束:
    - 运行时检测真源是 roi_frac (分辨率无关); 像素 w,h 只在声明的参考分辨率 REFERENCE_CAPTURE
      下有意义, 是"人看的权威统一值"。frac 是派生值, 按每通道自己的 rotation 换算 (正反严格互逆,
      圆整误差 ≤1px)。运行时检测代码零改。
    - 真源文件格式不动; 防漂靠约束写者, 非重构存储。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Optional

from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    WaterLevelDetectParams,
    box_to_roi_frac,
    rotation_matrix,
)
from eit_ptlc.controller.waterlevel_store import ChannelConfig

# 像素尺寸的声明参考分辨率 (由现有真源反推: CH1 rot=0.8666° 时画布 1290x739, 133/1290=0.103101)。
REFERENCE_CAPTURE = (1280, 720)

# 全局·判据层字段 = WaterLevelDetectParams 判据字段 (不含每通道触发阈值 T1/T2)。
GLOBAL_JUDGMENT_FIELDS = (
    "roi_crop_x",
    "roi_crop_y",
    "blur_ksize",
    "separation_mode",
    "wet_pixel_threshold",
    "wet_rel_threshold",
    "front_ratio_level",
    "front_gap_frac",
)


@dataclass(frozen=True)
class Pose:
    """逐通道·位姿层。xy_px 为旋转后画布 (参考分辨率) 的 ROI 左上角像素; 未标定通道为 None。

    dry_frac: 干参考区比例框, 逐通道位姿层, 随 with_pose 提交。
    """
    rotation_deg: float
    flow: str
    xy_px: Optional[tuple[int, int]]
    dry_frac: Optional[tuple[float, float, float, float]] = None


@dataclass(frozen=True)
class TierView:
    """一个通道拆成三层的视图。size_px=None 表示未标定 (无 ROI); pose 恒在 (承载 rotation+flow)。"""
    judgment: WaterLevelDetectParams
    size_px: Optional[tuple[int, int]]
    pose: Pose


def _rotated_canvas(rotation_deg: float, capture: tuple[int, int]) -> tuple[int, int]:
    """参考分辨率下, 该 rotation 的旋转后画布尺寸 (rw, rh)。"""
    _M, (rw, rh) = rotation_matrix(rotation_deg, capture[0], capture[1])
    return rw, rh


def split_tiers(cfg: ChannelConfig, capture: tuple[int, int] = REFERENCE_CAPTURE) -> TierView:
    """把一个通道配置拆成 判据 / 尺寸px / 位姿 三层 (读方向)。

    尺寸/位置像素在 capture 参考分辨率的旋转后画布下由 roi_frac 还原 (round)。
    未标定 (roi_frac 与 roi_bbox 皆空) → size_px=None, pose.xy_px=None (但保留 rotation+flow)。
    """
    calib = cfg.calib
    pose_xy: Optional[tuple[int, int]] = None
    size_px: Optional[tuple[int, int]] = None
    if calib.calibrated:
        rw, rh = _rotated_canvas(calib.rotation_angle_deg, capture)
        px = calib.roi_pixels(rw, rh)
        if px is not None:
            x, y, w, h = px
            pose_xy = (x, y)
            size_px = (w, h)
    pose = Pose(rotation_deg=calib.rotation_angle_deg, flow=calib.flow_direction,
                xy_px=pose_xy, dry_frac=calib.dry_ref_frac)
    return TierView(judgment=cfg.params, size_px=size_px, pose=pose)


def derive_roi_frac(rotation_deg: float, xy_px: tuple[int, int], size_px: tuple[int, int],
                    capture: tuple[int, int] = REFERENCE_CAPTURE) -> tuple[float, float, float, float]:
    """位姿 rotation + ROI 像素 (x,y,w,h, 参考分辨率) → 分辨率无关 roi_frac。

    按该 rotation 自己的旋转后画布尺寸换算 (复用 box_to_roi_frac), 与 split_tiers 严格互逆。
    """
    rw, rh = _rotated_canvas(rotation_deg, capture)
    x, y = xy_px
    w, h = size_px
    return box_to_roi_frac(x, y, w, h, rw, rh)


def merge_tiers(judgment: WaterLevelDetectParams, size_px: Optional[tuple[int, int]],
                pose: Pose, capture: tuple[int, int] = REFERENCE_CAPTURE) -> ChannelConfig:
    """三层 → 通道配置 (写方向), 含 frac 派生 + roi_bbox materialize。

    标定成立当且仅当 size_px 与 pose.xy_px 皆非空 (有位置可锚 + 有尺寸)。此时:
      roi_frac = derive_roi_frac(rotation, xy, size); roi_bbox = 参考分辨率下 frac 还原的像素框。
    退化 ROI (w<=0 / h<=0 / 越出参考画布) → ValueError (不写)。
    否则 (无位置或无尺寸) → 未标定 calib (仅保留 rotation + flow + 判据)。
    """
    if size_px is not None and pose.xy_px is not None:
        w, h = size_px
        x, y = pose.xy_px
        rw, rh = _rotated_canvas(pose.rotation_deg, capture)
        if w <= 0 or h <= 0:
            raise ValueError(f"退化 ROI 尺寸 (w={w}, h={h})")
        if not (0 <= x and 0 <= y and x + w <= rw and y + h <= rh):
            raise ValueError(f"ROI 越出参考画布: box=({x},{y},{w},{h}) 画布=({rw},{rh})")
        roi_frac = derive_roi_frac(pose.rotation_deg, (x, y), (w, h), capture)
        roi_bbox = ChannelCalibration(
            rotation_angle_deg=pose.rotation_deg, roi_frac=roi_frac).roi_pixels(rw, rh)
        calib = ChannelCalibration(
            rotation_angle_deg=pose.rotation_deg,
            roi_bbox=tuple(roi_bbox),
            flow_direction=pose.flow,
            roi_frac=roi_frac,
            dry_ref_frac=pose.dry_frac,
        )
    else:
        calib = ChannelCalibration(
            rotation_angle_deg=pose.rotation_deg,
            roi_bbox=None,
            flow_direction=pose.flow,
            roi_frac=None,
            dry_ref_frac=pose.dry_frac,
        )
    return ChannelConfig(calib=calib, params=judgment)


@dataclass(frozen=True)
class FieldAudit:
    """单个全局层字段的一致性判据。

    consistent: 已标定各路是否全等。
    expected:   一致值 / 严格多数 (>半数) 值; 无共识时为 None。
    deviants:   偏离 expected 的通道 → 值 (一致 / 无共识时为空)。
    values:     已标定各路取值 (无共识时的主展示; 恒填)。
    """
    field: str
    consistent: bool
    expected: Optional[Any]
    deviants: dict[int, Any]
    values: dict[int, Any]


@dataclass(frozen=True)
class AuditReport:
    fields: list[FieldAudit]            # 6 判据字段 + 'w' + 'h'
    uncalibrated: list[int]             # 无 ROI 的通道号 (升序)


def _consensus(values: dict[int, Any]) -> tuple[bool, Optional[Any]]:
    """(consistent, expected)。consistent=全等; expected=一致值 / 严格多数(>半数)值; 无共识时 None。

    展示概念: 多数值只用于提示"谁偏离了大伙", 不用于广播 (广播源是确定的 tuned 那一路)。
    """
    if not values:
        return True, None
    uniq = set(values.values())
    if len(uniq) == 1:
        return True, next(iter(uniq))
    n = len(values)
    val, cnt = Counter(values.values()).most_common(1)[0]
    if cnt > n / 2:
        return False, val         # 严格多数
    return False, None            # 无共识 (平票 / 无过半) → 不猜


def _field_audit(field: str, values: dict[int, Any]) -> FieldAudit:
    consistent, expected = _consensus(values)
    deviants = {ch: v for ch, v in values.items() if expected is not None and v != expected}
    return FieldAudit(field=field, consistent=consistent, expected=expected,
                      deviants=deviants, values=values)


def audit(configs: dict[int, ChannelConfig],
          capture: tuple[int, int] = REFERENCE_CAPTURE) -> AuditReport:
    """8 路全局层一致性判据 (只读)。未标定通道 (无 ROI) 单列, 不参与字段一致性。"""
    views = {ch: split_tiers(cfg, capture) for ch, cfg in configs.items()}
    calibrated = {ch: v for ch, v in views.items() if v.size_px is not None}
    uncalibrated = sorted(ch for ch in views if ch not in calibrated)

    fields: list[FieldAudit] = []
    for name in GLOBAL_JUDGMENT_FIELDS:
        vals = {ch: getattr(configs[ch].params, name) for ch in calibrated}
        fields.append(_field_audit(name, vals))
    for i, name in enumerate(("w", "h")):
        vals = {ch: v.size_px[i] for ch, v in calibrated.items()}
        fields.append(_field_audit(name, vals))
    return AuditReport(fields=fields, uncalibrated=uncalibrated)


def apply_commit(configs: dict[int, ChannelConfig], ch: int, tuned: ChannelConfig, *,
                 broadcast_global: bool, with_pose: bool,
                 capture: tuple[int, int] = REFERENCE_CAPTURE) -> dict[int, ChannelConfig]:
    """唯一的按层过滤写入点 (所有权从"文档约定"升格为"代码强制")。

    - 判据层 + 尺寸层 (全局): 落 ch (默认) 或 broadcast_global 时落全部通道;
      每通道尺寸按自身 rotation + 现位置重新派生 frac (故各路 frac 各异是有意的)。
    - 位姿层 (逐通道): 仅当 with_pose 且是 tuned 自己的通道 ch 才写入 (显式越权逃生口)。
    - 尺寸层需要一个位置来锚定 (pose.xy_px); 无位置的通道 (未标定且不给位姿) 只落判据层。
    """
    if ch not in configs:
        raise ValueError(f"CH{ch} 不在真源通道中: {sorted(configs)}")
    tv = split_tiers(tuned, capture)
    if tv.size_px is None or tv.pose.xy_px is None:
        raise ValueError(f"tuned CH{ch} 无 ROI, 不能作全局层来源")

    targets = set(configs) if broadcast_global else {ch}
    result: dict[int, ChannelConfig] = {}
    for c, cfg in configs.items():
        cur = split_tiers(cfg, capture)
        pose = tv.pose if (c == ch and with_pose) else cur.pose
        if c in targets:
            judgment = tv.judgment
            size_px = tv.size_px if pose.xy_px is not None else None   # 无位置可锚 → 尺寸跳过
        else:
            judgment = cur.judgment
            size_px = cur.size_px
        result[c] = merge_tiers(judgment, size_px, pose, capture)
    return result
