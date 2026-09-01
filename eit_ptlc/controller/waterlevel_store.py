"""液位通道配置持久化 (上位机侧标定真源)
==========================================
功能:
    管理 8 通道的标定 (ChannelCalibration) + 检测参数 (WaterLevelDetectParams) 的
    JSON 持久化。检测从香橙派搬到上位机后, 这里是标定真源, 取代香橙派本地
    water_level_config.json。

兼容迁移 (奥卡姆: 零重标):
    load_channel_configs 同时认两种格式:
      - **香橙派格式** (嵌套 calibration / roi_manual / detect_params) —— 把现场那份
        water_level_config.json 直接拷过来即可用;
      - **上位机原生格式** (calib / params) —— save_channel_configs 写出的格式。
    香橙派 auto ROI 模式 (无 roi_manual) 的通道 → roi_bbox=None (标记未标定, 待上位机补标)。

字段映射 (香橙派 → 上位机, 仅迁几何相关, 算法阈值用新默认):
    calibration.rotation_angle_deg → calib.rotation_angle_deg
    roi_manual.{x,y,w,h}           → calib.roi_bbox
    detect_params.flow_direction   → calib.flow_direction
    detect_params.roi_crop_x/y     → params.roi_crop_x/y
    detect_params.water_blur_ksize → params.blur_ksize
    (香橙派的 water_diff_threshold 不再迁: 上位机侧已无"整帧差分均值下限"这道门,
     判前沿到没到改由 analyze_front 的流入侧锚定判据回答)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    WaterLevelDetectParams,
)

log = logging.getLogger(__name__)

NUM_CHANNELS = 8

# 干参考区按流向的预置默认 (旋转后画布比例; 板外金属面板, 2026-07-14 逐通道首帧核实):
# right_to_left (CH1-4) 面板在左; left_to_right (CH5-8) 镜像在右; 垂直流无预置。
DRY_REF_DEFAULT_BY_FLOW: dict[str, Optional[tuple[float, float, float, float]]] = {
    "right_to_left": (0.02, 0.10, 0.13, 0.80),
    "left_to_right": (0.78, 0.15, 0.10, 0.70),
    "bottom_to_top": None,
}


@dataclass
class ChannelConfig:
    """单通道完整配置: 标定 + 检测参数。"""
    calib: ChannelCalibration
    params: WaterLevelDetectParams


# ====================================================================
# dataclass ↔ dict
# ====================================================================
def _calib_to_dict(c: ChannelCalibration) -> dict:
    d = {
        "rotation_angle_deg": float(c.rotation_angle_deg),
        "roi_bbox": list(c.roi_bbox) if c.roi_bbox is not None else None,
        "flow_direction": c.flow_direction,
    }
    # 分辨率无关 ROI 比例 (优先真源); 仅在存在时写出, 兼容旧文件
    if c.roi_frac is not None:
        d["roi_frac"] = [float(v) for v in c.roi_frac]
    if c.dry_ref_frac is not None:
        d["dry_ref_frac"] = [float(v) for v in c.dry_ref_frac]
    return d


def _params_to_dict(p: WaterLevelDetectParams) -> dict:
    return {
        "roi_crop_x": p.roi_crop_x,
        "roi_crop_y": p.roi_crop_y,
        "blur_ksize": p.blur_ksize,
        "separation_mode": p.separation_mode,
        "wet_pixel_threshold": p.wet_pixel_threshold,
        "wet_rel_threshold": p.wet_rel_threshold,
        "front_ratio_level": p.front_ratio_level,
        "front_gap_frac": p.front_gap_frac,
        "trigger_percent_t2": p.trigger_percent_t2,
        "t1_offset": p.t1_offset,
    }


def _params_from_native(d: dict) -> WaterLevelDetectParams:
    base = WaterLevelDetectParams()
    mode = d.get("separation_mode", base.separation_mode)
    if mode not in ("abs", "log"):      # 手改盘文件的未知口径 → 回退默认
        mode = base.separation_mode
    return WaterLevelDetectParams(
        roi_crop_x=float(d.get("roi_crop_x", base.roi_crop_x)),
        roi_crop_y=float(d.get("roi_crop_y", base.roi_crop_y)),
        blur_ksize=int(d.get("blur_ksize", base.blur_ksize)),
        separation_mode=mode,
        wet_pixel_threshold=float(d.get("wet_pixel_threshold", base.wet_pixel_threshold)),
        wet_rel_threshold=float(d.get("wet_rel_threshold", base.wet_rel_threshold)),
        front_ratio_level=float(d.get("front_ratio_level", base.front_ratio_level)),
        front_gap_frac=float(d.get("front_gap_frac", base.front_gap_frac)),
        trigger_percent_t2=float(d.get("trigger_percent_t2", base.trigger_percent_t2)),
        t1_offset=float(d.get("t1_offset", base.t1_offset)),
    )


# ====================================================================
# 香橙派嵌套格式 → ChannelConfig
# ====================================================================
def _from_orangepi_entry(entry: dict) -> ChannelConfig:
    """解析香橙派 water_level_config.json 的单通道条目 (calibration/roi_manual/detect_params)。"""
    dp = entry.get("detect_params", {}) if isinstance(entry.get("detect_params"), dict) else {}
    cal = entry.get("calibration", {}) if isinstance(entry.get("calibration"), dict) else {}
    roi_m = entry.get("roi_manual", {}) if isinstance(entry.get("roi_manual"), dict) else {}

    rotation = float(cal.get("rotation_angle_deg", 0.0))
    flow = dp.get("flow_direction", "left_to_right")

    roi_bbox: Optional[tuple[int, int, int, int]] = None
    if all(k in roi_m for k in ("x", "y", "w", "h")):
        roi_bbox = (int(roi_m["x"]), int(roi_m["y"]), int(roi_m["w"]), int(roi_m["h"]))

    calib = ChannelCalibration(rotation_angle_deg=rotation, roi_bbox=roi_bbox,
                               flow_direction=flow)

    base = WaterLevelDetectParams()
    params = WaterLevelDetectParams(
        roi_crop_x=float(dp.get("roi_crop_x", base.roi_crop_x)),
        roi_crop_y=float(dp.get("roi_crop_y", base.roi_crop_y)),
        blur_ksize=int(dp.get("water_blur_ksize", base.blur_ksize)),
        # 香橙派的 water_diff_threshold 不再迁 (上位机已无整帧差分均值门);
        # wet_pixel_threshold / front_ratio_level 香橙派无对应 (算法不同), 用上位机默认
    )
    return ChannelConfig(calib=calib, params=params)


def _from_native_entry(entry: dict) -> ChannelConfig:
    """解析上位机原生格式单通道条目 (calib/params)。"""
    cd = entry.get("calib", {}) if isinstance(entry.get("calib"), dict) else {}
    rb = cd.get("roi_bbox")
    roi_bbox = tuple(int(v) for v in rb) if isinstance(rb, (list, tuple)) and len(rb) == 4 else None
    rf = cd.get("roi_frac")
    roi_frac = tuple(float(v) for v in rf) if isinstance(rf, (list, tuple)) and len(rf) == 4 else None
    df = cd.get("dry_ref_frac")
    dry_frac = tuple(float(v) for v in df) if isinstance(df, (list, tuple)) and len(df) == 4 else None
    calib = ChannelCalibration(
        rotation_angle_deg=float(cd.get("rotation_angle_deg", 0.0)),
        roi_bbox=roi_bbox,
        flow_direction=cd.get("flow_direction", "left_to_right"),
        roi_frac=roi_frac,
        dry_ref_frac=dry_frac,
    )
    pd = entry.get("params", {}) if isinstance(entry.get("params"), dict) else {}
    return ChannelConfig(calib=calib, params=_params_from_native(pd))


def _detect_format(entry: dict) -> str:
    """判断单通道条目是 'native' / 'orangepi' / 'unknown'。"""
    if "calib" in entry or "params" in entry:
        return "native"
    if "calibration" in entry or "roi_manual" in entry or "detect_params" in entry:
        return "orangepi"
    return "unknown"


# ====================================================================
# 公共 API
# ====================================================================
def load_channel_configs(path: Union[str, Path]) -> dict[int, ChannelConfig]:
    """从 JSON 加载各通道配置, 自动识别香橙派/原生格式。

    文件不存在/解析失败/空 → 返回空 dict (调用方对缺失通道用默认 + 标记未标定)。
    通道键为 1-based int。
    """
    path = Path(path)
    if not path.is_file():
        log.info("[WL] 标定文件不存在, 使用空配置: %s", path)
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("[WL] 标定文件解析失败 (%s): %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        log.warning("[WL] 标定文件顶层非 dict, 忽略: %s", path)
        return {}

    out: dict[int, ChannelConfig] = {}
    for key, entry in raw.items():
        try:
            ch_id = int(key)
        except (ValueError, TypeError):
            continue
        if not isinstance(entry, dict):
            continue
        fmt = _detect_format(entry)
        if fmt == "native":
            out[ch_id] = _from_native_entry(entry)
        elif fmt == "orangepi":
            out[ch_id] = _from_orangepi_entry(entry)
        else:
            log.warning("[WL] CH%s 配置格式无法识别, 跳过", ch_id)
    log.info("[WL] 已加载 %d 通道标定 (来源 %s)", len(out), path)
    return out


def save_channel_configs(path: Union[str, Path],
                         configs: dict[int, ChannelConfig]) -> None:
    """以上位机原生格式写出各通道配置 (覆盖写, 原子: 先写临时再替换)。"""
    path = Path(path)
    payload = {
        str(ch_id): {"calib": _calib_to_dict(cfg.calib),
                     "params": _params_to_dict(cfg.params)}
        for ch_id, cfg in sorted(configs.items())
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    log.info("[WL] 已保存 %d 通道标定 → %s", len(configs), path)


def default_configs() -> dict[int, ChannelConfig]:
    """全 8 通道默认配置 (未标定; 展开组 1 CH1-4 右→左, 组 2 CH5-8 左→右, 沿用香橙派约定)。"""
    out: dict[int, ChannelConfig] = {}
    for ch in range(1, NUM_CHANNELS + 1):
        flow = "right_to_left" if ch <= 4 else "left_to_right"
        out[ch] = ChannelConfig(
            calib=ChannelCalibration(flow_direction=flow,
                                     dry_ref_frac=DRY_REF_DEFAULT_BY_FLOW.get(flow)),
            params=WaterLevelDetectParams(),
        )
    return out
