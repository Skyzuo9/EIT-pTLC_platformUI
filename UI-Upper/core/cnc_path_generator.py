"""CNC 点位数组生成器 — SMC_CNC_REF 主方案上位机适配层。

职责：
  解析 TLC 视觉分析输出的 summary.json + band_id，按 GCodeCfg 标定参数
  生成 PLC Host_Computer/ScrapeCNC 所需的 4 个 ARRAY[400] OF REAL 点位数组 +
  N 个 REAL/INT 标量参数；返回 dict 与 Host_Computer 变量名严格对齐。

设计要点：
  - 坐标变换（to_machine 算术）直接内联，消除对 View/pTLC_Viewing/tlc_gcode.py
    的动态 sys.path 导入依赖（避免 __pycache__ 陈旧字节码风险）
  - 三种路径策略可选（gcode_cfg.path_strategy 或显式 strategy 形参覆盖）：
      * zigzag        — 锯齿（X 均分 n-1 段，Y 在 y_max/y_min 交替；保留作回归对照）
      * boustrophedon — 光栅式/牛犁式（columns × per_col；列内 Y 单向匀分，列间方向交替；
                        180° U 形回头降为 90° 转角，对 SMC 速度过渡友好）
      * contour       — 轮廓驱动按列扫描（扫描线算法 + keep_ratio，生产唯一推荐）
  - 列数由 cutter_diameter × (1 - overlap_ratio) 自动推导，保证铣刀覆盖无遗漏
  - 收集路径同策略，X 起点为 bottle_x_cm = x_max - bottle_x_offset_mm/10
  - 退化处理：
      bbox 过窄 → 仍输出 400 点（重复点不影响 SMC 插补，仅日志 WARN）
      bottle_x_cm ≤ x_min → 全部 400 点填 (x_max + offset, alt y) 占位
      summary.json / band 缺失 → 抛 FileNotFoundError / KeyError，由调用方走安全占位

数据流：
  ScrapeStage._run_scrape_body
    → cnc_path_generator.generate_scrape_arrays(summary_path, band_id, gcode_cfg)
    → plc.send_recipe_params(arrays)  # 一次 batch 写 12 个 Host_Computer 变量
    → plc.confirm_stage("scrape")

ScrapeCNC 契约见 docs/PLC_ScrapeCNC_Interface.md。
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from core.config import GCodeCfg
from core.gcode_generator import _patch_summary_paths

log = logging.getLogger(__name__)

# 模板硬约束：刮扫 400 点 + 收集 400 点（与 scrape_template_v2.cnc 中 g_sx[1..400] 等数组对齐）
SCRAPE_POINT_COUNT = 400
COLLECT_POINT_COUNT = 400

# origin_corner → (flip_x, flip_y) 查表（与 tlc_gcode._flip_from_corner 对齐，
# 内联于此避免 sys.path 动态导入 + __pycache__ 陈旧字节码风险）
_CORNER_FLIP: dict[str, tuple[bool, bool]] = {
    "lower-left":   (False, False),
    "top-right":    (True,  True),
    "top-left":     (False, True),
    "bottom-right": (True,  False),
}


def _flip_from_corner(origin_corner: str) -> tuple[bool, bool]:
    """Return (flip_x, flip_y) for the given origin corner（内联版本）。"""
    try:
        return _CORNER_FLIP[origin_corner]
    except KeyError:
        raise ValueError(
            f"origin_corner 必须是 {list(_CORNER_FLIP)} 之一，得到 {origin_corner!r}"
        ) from None


@dataclass
class ScrapeArrays:
    """生成器内部结果对象（仅用于类型提示与单元测试，对外仍返回 dict）。"""
    g_sx: list[float]
    g_sy: list[float]
    g_cx: list[float]
    g_cy: list[float]
    g_safe_z: float
    g_approach_z: float
    g_pass_z: float
    g_pass_count: int
    g_total_depth: float
    g_plate_surface_z: float
    g_scrape_feed: int
    g_plunge_feed: int

    def as_plc_dict(self) -> dict[str, Any]:
        """转为 plc.send_recipe_params 直接消费的 dict（key=Host_Computer 变量名）。

        注意：g_pass_z 不包含在内——该变量由 PLC Step 30 内部计算
        （g_plate_surface_z + k * g_total_depth / g_pass_count），
        上位机只读不写，避免覆盖 PLC 运行时值导致竞争条件。
        """
        return {
            "g_sx":              list(self.g_sx),
            "g_sy":              list(self.g_sy),
            "g_cx":              list(self.g_cx),
            "g_cy":              list(self.g_cy),
            "g_safe_z":          float(self.g_safe_z),
            "g_approach_z":      float(self.g_approach_z),
            "g_pass_count":      int(self.g_pass_count),
            "g_total_depth":     float(self.g_total_depth),
            "g_plate_surface_z": float(self.g_plate_surface_z),
            "g_scrape_feed":     int(self.g_scrape_feed),
            "g_plunge_feed":     int(self.g_plunge_feed),
        }


# ---------------------------------------------------------------------------
# 路径生成：三种策略 + 退化分支共享 helper
# ---------------------------------------------------------------------------

def _to_machine(
    x_cm: float, y_cm: float,
    ox: float, oy: float,
    flip_x: bool, flip_y: bool,
) -> tuple[float, float]:
    """板坐标(cm) → 机床坐标(mm)（内联版本，与 tlc_gcode.to_machine 对齐）。

    (ox, oy) 是板左下角对应的机床坐标 (mm)。
    flip_x=True: 机床 X 随板 x_cm 增加而减小（原点在右侧）。
    flip_y=True: 机床 Y 随板 y_cm 增加而减小（原点在上侧）。
    """
    mx = (ox - x_cm * 10.0) if flip_x else (ox + x_cm * 10.0)
    my = (oy - y_cm * 10.0) if flip_y else (oy + y_cm * 10.0)
    return round(mx, 3), round(my, 3)


def _degenerate_points(
    n_points: int,
    bbox_cm: tuple[float, float, float, float],
    x_offset_mm: float,
    plate_origin_x: float,
    plate_origin_y: float,
    flip_x: bool,
    flip_y: bool,
) -> list[tuple[float, float]]:
    """退化分支：所有点 collapse 到 (x_max + offset, alt y)。

    三种策略共用同一退化表现（避免分支剧本不一致）。
    """
    _, y_min, x_max, y_max = bbox_cm
    offset_cm = x_offset_mm / 10.0
    points: list[tuple[float, float]] = []
    for i in range(n_points):
        y = y_max if (i % 2 == 0) else y_min
        mx, my = _to_machine(x_max + offset_cm, y, plate_origin_x, plate_origin_y, flip_x, flip_y)
        points.append((mx, my))
    return points


def _check_degenerate(
    bbox_cm: tuple[float, float, float, float],
    x_start_cm: float | None,
    n_points: int,
) -> tuple[float, bool]:
    """退化判定。返回 (start_x, is_degenerate)。

    退化场景：
      1. start_x 越过右端 → 原地占位于 (x_max + offset)
      2. 显式传入的 x_start_cm 小于/等于 x_min → 表示 outer offset 已超 bbox 宽，
         路径会跨到 bbox 外侧，不安全 → 同样原地占位
    """
    x_min, _, x_max, _ = bbox_cm
    start_x = x_min if x_start_cm is None else x_start_cm
    is_explicit_start = x_start_cm is not None
    over_right = start_x >= x_max - 1e-9
    over_left = is_explicit_start and start_x <= x_min + 1e-9
    if over_right or over_left:
        log.warning(
            "_path 退化: x_start=%.4f 不在 (%.4f, %.4f) 内，输出 %d 个原地占位点",
            start_x, x_min, x_max, n_points,
        )
        return start_x, True
    if n_points < 2:
        raise ValueError(f"n_points 必须 ≥ 2, 得到 {n_points}")
    return start_x, False


def _path_zigzag(
    bbox_cm: tuple[float, float, float, float],
    x_offset_mm: float,
    plate_origin_x: float,
    plate_origin_y: float,
    flip_x: bool,
    flip_y: bool,
    x_start_cm: float | None = None,
    n_points: int = SCRAPE_POINT_COUNT,
    reverse_x: bool = False,
    **_: Any,  # 吞其他策略专属参数（columns / keep_ratio / contour）
) -> list[tuple[float, float]]:
    """锯齿（保留作回归对照与兜底）：X 均分 n-1 段，Y 在 y_max/y_min 间交替。

    每个点均是一个 180° U 形回头，机械冲击大；仅用于回归/调试对比。
    """
    start_x, degen = _check_degenerate(bbox_cm, x_start_cm, n_points)
    if degen:
        return _degenerate_points(
            n_points, bbox_cm, x_offset_mm,
            plate_origin_x, plate_origin_y, flip_x, flip_y,
        )

    _, y_min, x_max, y_max = bbox_cm
    offset_cm = x_offset_mm / 10.0
    span_cm = x_max - start_x
    step_cm = span_cm / (n_points - 1)
    points: list[tuple[float, float]] = []
    for i in range(n_points):
        x = start_x + ((n_points - 1 - i) if reverse_x else i) * step_cm
        y = y_max if (i % 2 == 0) else y_min
        mx, my = _to_machine(x + offset_cm, y, plate_origin_x, plate_origin_y, flip_x, flip_y)
        points.append((mx, my))
    return points


def _path_boustrophedon(
    bbox_cm: tuple[float, float, float, float],
    x_offset_mm: float,
    plate_origin_x: float,
    plate_origin_y: float,
    flip_x: bool,
    flip_y: bool,
    x_start_cm: float | None = None,
    n_points: int = SCRAPE_POINT_COUNT,
    columns: int = 20,
    reverse_x: bool = False,
    **_: Any,
) -> list[tuple[float, float]]:
    """光栅式/牛犁式：n_points 划分为 columns 列 × per_col 点。

    每列内 Y 从 y_max(偶列)/y_min(奇列) 单向匀分走到另一端；列间通过一段
    水平连接过渡（首尾点 Y 同，自然形成 90° 转角）。
    """
    if columns < 1:
        raise ValueError(f"boustrophedon: columns 必须 ≥ 1, 得到 {columns}")
    if n_points % columns != 0:
        raise ValueError(
            f"boustrophedon: n_points({n_points}) 必须能被 columns({columns}) 整除"
        )
    per_col = n_points // columns
    if per_col < 2:
        raise ValueError(
            f"boustrophedon: per_col={per_col} 必须 ≥ 2（每列至少 2 个点）"
        )

    start_x, degen = _check_degenerate(bbox_cm, x_start_cm, n_points)
    if degen:
        return _degenerate_points(
            n_points, bbox_cm, x_offset_mm,
            plate_origin_x, plate_origin_y, flip_x, flip_y,
        )

    _, y_min, x_max, y_max = bbox_cm
    offset_cm = x_offset_mm / 10.0
    span_cm = x_max - start_x
    x_step_cm = span_cm / (columns - 1) if columns > 1 else 0.0
    y_step_cm = (y_max - y_min) / (per_col - 1)

    points: list[tuple[float, float]] = []
    for col in range(columns):
        col_idx = (columns - 1 - col) if reverse_x else col
        x = start_x + col_idx * x_step_cm
        downward = (col % 2 == 0)  # 偶列从 y_max 走到 y_min；奇列反向
        for k in range(per_col):
            if downward:
                y = y_max - k * y_step_cm
            else:
                y = y_min + k * y_step_cm
            mx, my = _to_machine(x + offset_cm, y, plate_origin_x, plate_origin_y, flip_x, flip_y)
            points.append((mx, my))
    return points


def _path_contour(
    bbox_cm: tuple[float, float, float, float],
    x_offset_mm: float,
    plate_origin_x: float,
    plate_origin_y: float,
    flip_x: bool,
    flip_y: bool,
    x_start_cm: float | None = None,
    n_points: int = SCRAPE_POINT_COUNT,
    columns: int = 20,
    keep_ratio: float = 1.0,
    contour: np.ndarray | None = None,
    reverse_x: bool = False,
    **_: Any,
) -> list[tuple[float, float]]:
    """轮廓驱动的按列扫描：沿 X 等分 columns 列，每列取轮廓上下边缘交点，
    并应用 keep_ratio 以重心为中心两侧各扩 列长×k/2。

    contour=None 或不可用 → fallback _path_boustrophedon（保证老 summary / fixture 仍可用）。
    """
    if not (0.0 < keep_ratio <= 1.0):
        raise ValueError(f"contour: keep_ratio 必须在 (0, 1]，得到 {keep_ratio}")

    if contour is None or contour.shape[0] < 4:
        log.warning("_path_contour: contour 不可用，fallback 到 boustrophedon")
        return _path_boustrophedon(
            bbox_cm, x_offset_mm, plate_origin_x, plate_origin_y,
            flip_x, flip_y, x_start_cm=x_start_cm,
            n_points=n_points, columns=columns,
            reverse_x=reverse_x,
        )

    if columns < 1:
        raise ValueError(f"contour: columns 必须 ≥ 1, 得到 {columns}")
    if n_points % columns != 0:
        raise ValueError(
            f"contour: n_points({n_points}) 必须能被 columns({columns}) 整除"
        )
    per_col = n_points // columns
    if per_col < 2:
        raise ValueError(
            f"contour: per_col={per_col} 必须 ≥ 2（每列至少 2 个点）"
        )

    start_x, degen = _check_degenerate(bbox_cm, x_start_cm, n_points)
    if degen:
        return _degenerate_points(
            n_points, bbox_cm, x_offset_mm,
            plate_origin_x, plate_origin_y, flip_x, flip_y,
        )

    x_min, y_min, x_max, y_max = bbox_cm
    offset_cm = x_offset_mm / 10.0
    span_cm = x_max - start_x
    x_step_cm = span_cm / (columns - 1) if columns > 1 else 0.0

    # _split_contour_to_top_bot 仅供调试/可视化外部调用，采样走扫描线。
    points: list[tuple[float, float]] = []
    for col in range(columns):
        col_idx = (columns - 1 - col) if reverse_x else col
        x_query = start_x + col_idx * x_step_cm
        # 使用扫描线算法求上下交点（对任意多边形鲁棒）
        sample = _sample_contour_y_scanline(contour, x_query)
        if sample is None:
            y_top, y_bot = y_max, y_min
        else:
            y_top, y_bot = sample

        # 退化保护：上下边缘重合或超出 bbox → 用 bbox 截面
        if y_top - y_bot < 1e-9:
            y_top, y_bot = y_max, y_min

        center_y = (y_top + y_bot) / 2.0
        half_len = (y_top - y_bot) * keep_ratio / 2.0
        y_hi = center_y + half_len
        y_lo = center_y - half_len
        y_step_cm = (y_hi - y_lo) / (per_col - 1)

        downward = (col % 2 == 0)  # 偶列 y_hi → y_lo；奇列反向
        for k in range(per_col):
            if downward:
                y = y_hi - k * y_step_cm
            else:
                y = y_lo + k * y_step_cm
            mx, my = _to_machine(
                x_query + offset_cm, y,
                plate_origin_x, plate_origin_y, flip_x, flip_y,
            )
            points.append((mx, my))
    return points


# ---------------------------------------------------------------------------
# summary.json 解析
# ---------------------------------------------------------------------------

def _load_band_geometry(
    summary_path: Path, band_id: str,
) -> tuple[tuple[float, float, float, float], np.ndarray | None]:
    """从 summary.json + 对应 path_json 提取 band 的 bbox_cm 与 contour_cm。

    返回:
        (bbox_cm, contour_cm | None)
        - bbox_cm: (x_min, y_min, x_max, y_max)
        - contour_cm: shape (N, 2) ndarray，列 0 = x_cm，列 1 = y_cm；
          path_json 缺少 contour_cm 字段时返回 None（老 summary 向后兼容）

    解析顺序（bbox）：
        1. summary.json -> bands[band_id == X] -> path_json
        2. path_json -> scrape_path.bbox_cm（若有）→ 直接返回
        3. 否则从 path_json -> scrape_path.points_cm 计算 min/max

    Raises:
        FileNotFoundError: summary 或 path_json 文件不存在
        KeyError: band_id 不存在或字段缺失
    """
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    bands = summary.get("bands", [])

    band_info = None
    for b in bands:
        if b.get("band_id") == band_id:
            band_info = b
            break
    if band_info is None:
        available = [b.get("band_id") for b in bands]
        raise KeyError(f"band_id={band_id!r} 不在 summary.bands 中（可用: {available}）")

    path_json_rel = band_info.get("path_json")
    if not path_json_rel:
        raise KeyError(f"band {band_id} 缺少 path_json 字段")

    # path_json 在 _patch_summary_paths 后已是绝对路径
    path_json_path = Path(path_json_rel)
    if not path_json_path.is_file():
        # 退一步：若 patched_summary 仍未生效，尝试把相对路径解释为 summary 的兄弟目录
        candidate = summary_path.parent / Path(path_json_rel).name
        if candidate.is_file():
            path_json_path = candidate
        else:
            raise FileNotFoundError(
                f"band {band_id} 的 path_json 不存在: {path_json_rel}（也尝试了 {candidate}）"
            )

    path_data = json.loads(path_json_path.read_text(encoding="utf-8"))
    scrape_path = path_data.get("scrape_path") or {}

    bbox_cm = scrape_path.get("bbox_cm")
    if bbox_cm:
        bbox = (
            float(bbox_cm["x_min"]), float(bbox_cm["y_min"]),
            float(bbox_cm["x_max"]), float(bbox_cm["y_max"]),
        )
    else:
        points_cm = scrape_path.get("points_cm") or []
        if not points_cm:
            raise KeyError(f"band {band_id} 的 scrape_path 缺少 bbox_cm 与 points_cm")
        xs = [p["x_cm"] for p in points_cm]
        ys = [p["y_cm"] for p in points_cm]
        bbox = (min(xs), min(ys), max(xs), max(ys))

    # contour_cm 是可选字段，仅 contour 策略使用；缺少时返回 None 让上层 fallback
    contour_raw = path_data.get("contour_cm") or []
    contour_arr: np.ndarray | None = None
    if contour_raw:
        try:
            contour_arr = np.asarray(
                [[float(p["x_cm"]), float(p["y_cm"])] for p in contour_raw],
                dtype=float,
            )
            if contour_arr.shape[0] < 4:
                contour_arr = None  # 点太少，无法构造上/下边缘
        except (KeyError, TypeError, ValueError):
            contour_arr = None

    return bbox, contour_arr


def _split_contour_to_top_bot(
    contour: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """保留函数名作为接口占位（原需求），但现有实现已走扫描线算法。

    该函数仅供可视化脚本 / 调试用：以 i_min / i_max 切两段并按 X 升序。
    生产路径采样走 _sample_contour_y_scanline，不依赖本函数。
    """
    xs = contour[:, 0]
    ys = contour[:, 1]
    n = len(xs)
    i_min = int(np.argmin(xs))
    i_max = int(np.argmax(xs))

    if i_min <= i_max:
        seg_a_idx = np.arange(i_min, i_max + 1)
        seg_b_idx = np.concatenate([np.arange(i_max, n), np.arange(0, i_min + 1)])
    else:
        seg_a_idx = np.concatenate([np.arange(i_min, n), np.arange(0, i_max + 1)])
        seg_b_idx = np.arange(i_max, i_min + 1)

    a_xs, a_ys = xs[seg_a_idx], ys[seg_a_idx]
    b_xs, b_ys = xs[seg_b_idx], ys[seg_b_idx]

    a_order = np.argsort(a_xs)
    b_order = np.argsort(b_xs)
    return a_xs[a_order], a_ys[a_order], b_xs[b_order], b_ys[b_order]


def _sample_contour_y_scanline(
    contour: np.ndarray, x: float,
) -> tuple[float, float] | None:
    """多边形扫描线算法：求闭合 contour 在查询 X 处的上下交点。

    逐边 (p_i, p_{i+1}) 如果跨越 x_query 则线性插 y。对凸/凹/任意形状都成立，
    是扫描线填充的标准算法。

    返回 (y_top, y_bot)；不足 2 个交点时返回 None，调用方退化到 bbox 截面。
    重合采样（多个交点重叠）取 max/min 包括。
    """
    n = contour.shape[0]
    ys: list[float] = []
    for i in range(n):
        x1, y1 = contour[i]
        x2, y2 = contour[(i + 1) % n]
        if abs(x1 - x2) < 1e-12:
            continue  # 垂直边跳过（不参与扫描线交会）
        # 是否跨越 x（含端点）
        if (x1 - x) * (x2 - x) <= 0:
            t = (x - x1) / (x2 - x1)
            ys.append(y1 + t * (y2 - y1))
    if len(ys) < 2:
        return None
    return max(ys), min(ys)


def _sample_contour_y(
    seg_a_xs: np.ndarray, seg_a_ys: np.ndarray,
    seg_b_xs: np.ndarray, seg_b_ys: np.ndarray,
    x: float,
) -> tuple[float, float]:
    """保留原接口供外部调用（现生产路径不再使用）：在两段轮廓上各插值。"""
    y_a = float(np.interp(x, seg_a_xs, seg_a_ys))
    y_b = float(np.interp(x, seg_b_xs, seg_b_ys))
    return max(y_a, y_b), min(y_a, y_b)


# ---------------------------------------------------------------------------
# 铣刀覆盖率：自动推导列数
# ---------------------------------------------------------------------------

def _compute_coverage_columns(
    x_span_mm: float,
    effective_step_mm: float,
    n_points: int,
) -> int:
    """根据铣刀直径 × 重叠率推导最优列数。

    选取满足以下约束的最小列数（宁可过覆盖，不欠覆盖）：
      - columns 能整除 n_points
      - columns ≥ ideal_columns（覆盖率保证）
      - per_col = n_points / columns ≥ 2（每列至少 2 点）

    设计决策（2026-06-03）：搜索方向由"≤ ideal 最大因子"改为"≥ ideal 最小因子"，
    解决 n_points=400 时因子 100↔200 断层（理想列数 101~199 全部降级为 100 列
    导致覆盖不足告警）的结构性问题。per_col=2 对平面刮取物理上完全够用。

    Returns:
        最优列数。若 x_span_mm ≈ 0 返回 1。
        若 ideal 超出 n_points//2 极限，返回 n_points//2（物理上限，per_col=2）。
    """
    if x_span_mm < 1e-6 or effective_step_mm < 1e-6:
        return 1
    ideal_columns = int(x_span_mm / effective_step_mm) + 1
    max_columns = n_points // 2  # per_col ≥ 2 硬约束
    if ideal_columns > max_columns:
        return max_columns
    # 找 ≥ ideal_columns 的最小 n_points 因子
    for d in range(ideal_columns, max_columns + 1):
        if n_points % d == 0:
            return d
    # 极端情况（无因子满足 ≥ ideal 且 ≤ max）→ 用物理上限
    return max_columns


def _effective_step_mm(tool_diameter_mm: float, overlap_ratio: float) -> float:
    """有效步距 = 刀具直径 × (1 - 重叠率)。"""
    return tool_diameter_mm * (1.0 - overlap_ratio)


# 策略分发表。新增策略只需在此补一行 + 补对应 _path_xxx 函数。
_PATH_DISPATCH: dict[str, Callable[..., list[tuple[float, float]]]] = {
    "zigzag":        _path_zigzag,
    "boustrophedon": _path_boustrophedon,
    "contour":       _path_contour,
}


def _resolve_strategy(strategy: str | None, gcode_cfg: GCodeCfg) -> str:
    """显式 strategy 优先；None 时取 gcode_cfg.path_strategy。"""
    name = (strategy or gcode_cfg.path_strategy).strip().lower()
    if name not in _PATH_DISPATCH:
        raise ValueError(
            f"path_strategy 必须是 {list(_PATH_DISPATCH)} 之一，得到: {name!r}"
        )
    return name


# ---------------------------------------------------------------------------
# 主接口
# ---------------------------------------------------------------------------

def generate_scrape_arrays(
    summary_path: Path,
    band_id: str,
    gcode_cfg: GCodeCfg,
    *,
    strategy: str | None = None,
    keep_ratio: float | None = None,
    collect_expand_ratio: float | None = None,
) -> ScrapeArrays:
    """生成 ScrapeCNC 所需的所有变量。

    Args:
        summary_path: TLC 视觉分析的 summary.json 路径
        band_id: 选中的 band（如 "band_01"）
        gcode_cfg: AppConfig.gcode 注入的标定/工艺参数
        strategy: 路径策略覆盖（None 时取 gcode_cfg.path_strategy）。
        keep_ratio: contour 策略下的刮取每列保留比例覆盖（None 时取 gcode_cfg.scrape_keep_ratio）。
            其他策略对该参数无感。
        collect_expand_ratio: 收集路径 Y 方向全局膨胀比覆盖（None 时取 gcode_cfg.collect_expand_ratio）。
            1.0=与刮取 bbox 一致，>1.0=扩大收集范围。

    Returns:
        ScrapeArrays，调用方常用 .as_plc_dict() 直接传给 plc.send_recipe_params()。

    Raises:
        FileNotFoundError: summary 或 path_json 不存在
        KeyError: band_id 不存在或字段缺失
        ValueError: strategy 非法 / boustrophedon 或 contour 参数不合法 / keep_ratio 越界
    """
    summary_path = Path(summary_path)
    if not summary_path.is_file():
        raise FileNotFoundError(f"summary.json 不存在: {summary_path}")

    # 复用 gcode_generator 的 path_json 路径修正（同样的目录迁移问题）
    work_dir = summary_path.parent
    patched_path = _patch_summary_paths(summary_path, work_dir)
    try:
        bbox_cm, contour_cm = _load_band_geometry(patched_path, band_id)
    finally:
        try:
            patched_path.unlink()
        except OSError:
            pass

    flip_x, flip_y = _flip_from_corner(gcode_cfg.origin_corner)

    # ── 铣刀覆盖率：自动推导列数 ──
    scrape_step_mm = _effective_step_mm(
        gcode_cfg.tool.cutter_diameter_mm, gcode_cfg.scrape.overlap_ratio,
    )
    collect_step_mm = _effective_step_mm(
        gcode_cfg.tool.bottle_diameter_mm, gcode_cfg.collection.overlap_ratio,
    )
    x_min, _, x_max, _ = bbox_cm
    x_span_scrape_mm = (x_max - x_min) * 10.0

    # 刮扫列数：基于 bbox 全 X 跨度（向上取因子，保证覆盖）
    auto_scrape_columns = _compute_coverage_columns(
        x_span_scrape_mm, scrape_step_mm, SCRAPE_POINT_COUNT,
    )
    # 用户 boustrophedon_columns：仅在超过 auto 时生效（需要更高列数的极端场景）
    effective_columns = max(auto_scrape_columns, gcode_cfg.boustrophedon_columns)
    # 若用户偏好不是 n_points 因子，向上修正到最近因子
    if SCRAPE_POINT_COUNT % effective_columns != 0:
        max_cols = SCRAPE_POINT_COUNT // 2
        for d in range(effective_columns, max_cols + 1):
            if SCRAPE_POINT_COUNT % d == 0:
                effective_columns = d
                break
        else:
            effective_columns = max_cols

    # 覆盖不足警告（向上取因子后正常路径不应触发，作为安全兜底保留）
    actual_x_step_mm = x_span_scrape_mm / (effective_columns - 1) if effective_columns > 1 else x_span_scrape_mm
    if actual_x_step_mm > scrape_step_mm * 1.01:
        log.warning(
            "[cnc_path_generator] ⚠ 覆盖不足: X步距 %.2fmm > 有效步距 %.2fmm "
            "(cutter=%.1fmm overlap=%.0f%% columns=%d)，建议换更大刀径或减小重叠率",
            actual_x_step_mm, scrape_step_mm,
            gcode_cfg.tool.cutter_diameter_mm,
            gcode_cfg.scrape.overlap_ratio * 100,
            effective_columns,
        )

    # 策略分发：显式 strategy 优先，否则走 gcode_cfg.path_strategy
    strategy_name = _resolve_strategy(strategy, gcode_cfg)
    path_fn = _PATH_DISPATCH[strategy_name]

    # keep_ratio 覆写优先于 gcode_cfg，用于 Debug Tab / 可视化脚本 运行时调参
    effective_keep_ratio = (
        float(keep_ratio) if keep_ratio is not None else float(gcode_cfg.scrape_keep_ratio)
    )
    if not (0.0 < effective_keep_ratio <= 1.0):
        raise ValueError(
            f"keep_ratio 必须在 (0, 1] 区间内，得到: {effective_keep_ratio}"
        )

    # 策略专属参数（多余参数被 _path_xxx 的 **_ 吞掉）
    strategy_kwargs: dict[str, Any] = {
        "columns":     effective_columns,
        "keep_ratio":  effective_keep_ratio,
        "contour":     contour_cm,
    }

    # 刮扫 400 点：覆盖整个 bbox X 跨度
    g_sxy = path_fn(
        bbox_cm,
        x_offset_mm=0.0,
        plate_origin_x=gcode_cfg.plate_origin_x,
        plate_origin_y=gcode_cfg.plate_origin_y,
        flip_x=flip_x, flip_y=flip_y,
        x_start_cm=None,
        n_points=SCRAPE_POINT_COUNT,
        **strategy_kwargs,
    )
    g_sx = [pt[0] for pt in g_sxy]
    g_sy = [pt[1] for pt in g_sxy]

    # 收集 400 点：覆盖刮取全路径 + 铣刀半径余量，从右到左反向
    # ── X 方向：铣刀半径固定余量；x_offset_mm 补偿铣刀-收集瓶 85mm 安装偏移 ──
    margin_cm = gcode_cfg.tool.cutter_diameter_mm / 2.0 / 10.0  # 铣刀半径 (cm)
    # ── Y 方向：按 collect_expand_ratio 全局放大 ──
    effective_collect_expand = (
        float(collect_expand_ratio) if collect_expand_ratio is not None
        else float(gcode_cfg.collect_expand_ratio)
    )
    if not (1.0 <= effective_collect_expand <= 2.0):
        raise ValueError(
            f"collect_expand_ratio 必须在 [1.0, 2.0] 区间内，得到: {effective_collect_expand}"
        )
    y_center = (bbox_cm[1] + bbox_cm[3]) / 2.0
    y_half = (bbox_cm[3] - bbox_cm[1]) / 2.0 * effective_collect_expand
    collect_bbox = (x_min - margin_cm, y_center - y_half, x_max + margin_cm, y_center + y_half)

    # 收集路径列数：基于扩展后全 X 跨度
    collect_x_span_mm = (collect_bbox[2] - collect_bbox[0]) * 10.0
    auto_collect_columns = _compute_coverage_columns(
        collect_x_span_mm, collect_step_mm, COLLECT_POINT_COUNT,
    )
    effective_collect_columns = max(auto_collect_columns, 1)
    # auto 已保证是因子；若 max 后不再是因子则向上修正
    if COLLECT_POINT_COUNT % effective_collect_columns != 0:
        max_cols = COLLECT_POINT_COUNT // 2
        for d in range(effective_collect_columns, max_cols + 1):
            if COLLECT_POINT_COUNT % d == 0:
                effective_collect_columns = d
                break
        else:
            effective_collect_columns = max_cols
    collect_kwargs = dict(strategy_kwargs)
    collect_kwargs["columns"] = effective_collect_columns
    collect_kwargs["reverse_x"] = True        # 反向遍历（右→左）
    collect_kwargs["keep_ratio"] = 1.0          # collect 不动 keep_ratio，始终用全列长
    g_cxy = path_fn(
        collect_bbox,                          # 扩展后的 bbox
        x_offset_mm=gcode_cfg.tool.bottle_x_offset_mm,  # 补偿铣刀-收集瓶安装偏移
        plate_origin_x=gcode_cfg.plate_origin_x,
        plate_origin_y=gcode_cfg.plate_origin_y,
        flip_x=flip_x, flip_y=flip_y,
        x_start_cm=None,                       # 使用 collect_bbox 全范围
        n_points=COLLECT_POINT_COUNT,
        **collect_kwargs,
    )
    g_cx = [pt[0] for pt in g_cxy]
    g_cy = [pt[1] for pt in g_cxy]

    # Z / 进给参数
    g_pass_count = max(1, int(gcode_cfg.scrape.num_passes))
    # g_pass_z 给一个首 pass 的合理初值（PLC ST 会在循环中按 k 覆盖）：
    #   首 pass 深度 = plate_surface + total_depth / num_passes
    g_pass_z = gcode_cfg.plate_surface_z_mm + gcode_cfg.scrape.total_depth_mm / g_pass_count

    arrays = ScrapeArrays(
        g_sx=g_sx,
        g_sy=g_sy,
        g_cx=g_cx,
        g_cy=g_cy,
        g_safe_z=float(gcode_cfg.safe_z_mm),
        g_approach_z=float(gcode_cfg.approach_z_mm),
        g_pass_z=float(g_pass_z),
        g_pass_count=g_pass_count,
        g_total_depth=float(gcode_cfg.scrape.total_depth_mm),
        g_plate_surface_z=float(gcode_cfg.plate_surface_z_mm),
        g_scrape_feed=int(gcode_cfg.scrape.feed_rate),
        g_plunge_feed=int(gcode_cfg.scrape.plunge_rate),
    )

    # 健全性诊断
    span_scrape_mm = (x_max - x_min) * 10.0
    avg_step_mm = span_scrape_mm / (SCRAPE_POINT_COUNT - 1) if SCRAPE_POINT_COUNT > 1 else 0.0
    log.info(
        "[cnc_path_generator] band=%s strategy=%s keep_ratio=%.2f contour=%s "
        "bbox=[%.2f,%.2f]-[%.2f,%.2f]cm columns=%d scrape_step≈%.2fmm pass_count=%d "
        "collect_columns=%d collect_expand=%.2f collect_reverse=True",
        band_id, strategy_name, effective_keep_ratio,
        "yes" if contour_cm is not None else "no",
        x_min, bbox_cm[1], x_max, bbox_cm[3],
        effective_columns, avg_step_mm, g_pass_count,
        effective_collect_columns, effective_collect_expand,
    )
    return arrays


def safe_placeholder_arrays(gcode_cfg: GCodeCfg) -> ScrapeArrays:
    """安全占位数组：g_pass_count=0，PLC ST 应识别并跳过 SMC_CNC_REF 启动。

    替代旧的 SAFE_PLACEHOLDER_GCODE 字符串占位，用于：
      - 视觉失败用户选择继续
      - band 选择超时（manual 模式）
      - 重刮模式 G-code 生成失败
      - 未配 VisionService

    所有数组全 0、g_pass_z=g_safe_z（即不向下），即便 PLC 误启动也不会撞板。
    """
    zeros = [0.0] * SCRAPE_POINT_COUNT
    return ScrapeArrays(
        g_sx=zeros, g_sy=zeros, g_cx=zeros, g_cy=zeros,
        g_safe_z=float(gcode_cfg.safe_z_mm),
        g_approach_z=float(gcode_cfg.approach_z_mm),
        g_pass_z=float(gcode_cfg.safe_z_mm),
        g_pass_count=0,
        g_total_depth=float(gcode_cfg.scrape.total_depth_mm),
        g_plate_surface_z=float(gcode_cfg.plate_surface_z_mm),
        g_scrape_feed=int(gcode_cfg.scrape.feed_rate),
        g_plunge_feed=int(gcode_cfg.scrape.plunge_rate),
    )
