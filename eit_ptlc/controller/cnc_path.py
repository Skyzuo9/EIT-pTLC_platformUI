"""CNC 点位数组生成器 — 上位机几字形/轮廓路径规划层。

职责：
  解析 TLC 视觉分析输出的 summary.json + band_id，按 GCodeCfg 标定参数
  生成真机 GVL（Now.xml）契约的 6 个 PC→PLC 变量。

真机契约（PLC 仅执行单 pass，不再内部循环；pass 循环 / per_pass-final / Z 逐层下压
全部编排归上位机 operation VM）：
  块写一次（plc_write 回读确认）: g_sx/g_sy/g_cx/g_cy (REAL[400]) + g_scrape_feed (INT)
  每 pass 写（VM 循环, plc_write 标量回读）: g_pass_z = pass_z_list[k]
  不下发 g_pass_count；safe_z/approach_z/plunge_feed 真机已删除，不再产出。

设计要点：
  - 坐标变换（to_machine 算术）直接内联，消除对 View/pTLC_Viewing/tlc_gcode.py
    的动态 sys.path 导入依赖（避免 __pycache__ 陈旧字节码风险）
  - 三种路径策略可选（gcode_cfg.path_strategy 或显式 strategy 形参覆盖）：
      * zigzag        — 锯齿（X 均分 n-1 段，Y 在 y_max/y_min 交替；保留作回归对照）
      * boustrophedon — 光栅式/牛犁式（columns × per_col；列内 Y 单向匀分，列间方向交替；
                        180° U 形回头降为 90° 转角，对 SMC 速度过渡友好）
      * contour       — 轮廓驱动按列扫描（扫描线算法 + keep_ratio，生产唯一推荐）
  - 列数由 cutter_diameter × (1 - overlap_ratio) 自动推导，保证铣刀覆盖无遗漏
  - 收集路径（无 Z 粉桶专用，见 _build_collect_points）：拖尾正向补收
    (x_max-bottle_x_offset → x_max) + 残粉 −X 回走 (x_max → x_min)，连续接刮取终点；
    中心封顶 [x_min,x_max] 不外扩越界，桶壁永不朝 x_max 开口边推粉（带粉出界根治）
  - 退化处理：
      bbox 过窄 → 仍输出 400 点（重复点不影响 SMC 插补，仅日志 WARN）
      bottle_x_cm ≤ x_min → 全部 400 点填 (x_max + offset, alt y) 占位
      summary.json / band 缺失 → 抛 FileNotFoundError / KeyError，由调用方走安全占位

数据流（operation VM 编排 photoscrape 流程）：
  cnc_path 动作(vision kind)
    → generate_scrape_arrays(summary_path, band_id, gcode_cfg).as_action_result()
    → VM assign 到变量 cnc
  plc_write 块(回读确认): 写 g_sx/g_sy/g_cx/g_cy/g_scrape_feed
  for k in range(cnc.pass_count):
    plc_write 标量(回读确认): g_pass_z = cnc.pass_z_list[k]
    scrape(40)  + per_pass/final 收集触发
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from eit_ptlc.config.models import GCodeCfg

log = logging.getLogger(__name__)


def _patch_summary_paths(summary_path: Path, work_dir: Path) -> Path:
    """修复 summary.json 中的相对路径为绝对路径, 使条带几何能正确定位.

    功能:
        视觉 summary.json 中 path_json 等为相对 analysis 运行目录的路径;
        目录迁移后失效, 本函数取末两级拼 analysis 目录得绝对路径, 写一份临时修正文件.
        迁移自 UI-Upper/core/gcode_generator._patch_summary_paths.
    参数:
        summary_path: 原 summary.json; work_dir: 临时文件写入目录
    返回:
        修正后的临时 summary.json 路径
    """
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    analysis_dir = summary_path.parent

    def _fix_path(rel_str: str) -> str:
        if not rel_str:
            return rel_str
        parts = Path(rel_str).parts
        resolved = analysis_dir / (Path(*parts[-2:]) if len(parts) >= 2 else Path(rel_str))
        return str(resolved.resolve()) if resolved.exists() else rel_str

    for band in summary.get("bands", []):
        for key in ("path_json", "contour_path_image", "metrics_image", "metrics_pdf", "contour_path_pdf"):
            if key in band:
                band[key] = _fix_path(band[key])
    for key in ("path_json_files", "metric_json_files"):
        if key in summary:
            summary[key] = [_fix_path(p) for p in summary[key]]

    patched_path = work_dir / f"_patched_{summary_path.name}"
    patched_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return patched_path

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
    """CNC 路径生成结果。对齐真机 GVL 契约（Now.xml）：仅 6 个 PC→PLC 变量。

    真机契约（PLC 不再内部循环 pass，全部编排归上位机 operation VM）：
      块写一次（plc_write 回读确认）: g_sx/g_sy/g_cx/g_cy (REAL[400]) + g_scrape_feed (INT)
      每 pass 写（VM 循环, plc_write 标量回读确认）: g_pass_z = pass_z_list[k]
      g_pass_count 不下发（PLC 不内部循环）；safe_z/approach_z/plunge_feed 真机已删除，不再产出。
    """
    g_sx: list[float]
    g_sy: list[float]
    g_cx: list[float]
    g_cy: list[float]
    g_scrape_feed: int
    pass_count: int               # pass 数（供 VM 循环次数；不写 PLC）
    pass_z_list: list[float]      # 每 pass 的 Z = plate_surface + k*total_depth/passes, k=1..passes
    start_x_mm: float = 0.0       # 路径首点机床 X (= g_sx[0])；供对位检查内环走起点（VM 无数组下标）。placeholder 时 0.0
    start_y_mm: float = 0.0       # 路径首点机床 Y (= g_sy[0])；同帧机床 mm，与 g_ 数组同源
    # 谱带 bbox（板 cm 帧: x0,y0,x1,y1，原点=板左下角，与 controller/plate_coords.py 同帧）。
    # 只给**三维孪生**用：数字孪生要在板面上画出被刮的那一块，而这是全链唯一知道它在哪的地方
    # （PLC 只收机床 mm 数组，反算不回板帧）。不下发 PLC，也不参与任何路径计算。
    band_cm: list[float] = field(default_factory=list)
    # 被刮掉的硅胶粉体积与它的两个来源量。与 band_cm 同一性质：只给**物料账本与三维**用，
    # 不下发 PLC，也不参与任何路径计算。
    #
    # ⚠ scrape_volume_mm3 = 面积 × gcode.scrape.total_depth_mm × gcode.scrape.bulk_factor。
    #   乘的是 **total_depth_mm（总切深）**，不是 depth_per_pass，也**不再乘 pass 数** ——
    #   下面 depth_per_pass = total_depth_mm / g_pass_count 那一行就是"总深"的证据。
    #   两刀分切只是治粉末崩飞的工艺手段，挖走的还是同一层 1mm。
    #
    # 已知二阶偏差（按用户口径不作修正）：scrape_keep_ratio < 1.0 时实际刮掉的面积小于轮廓
    # 面积（现役配置是 1，无影响）；刀具补偿内缩只改刀心路径、不改被刮走的带。
    scrape_area_mm2: float = 0.0
    scrape_area_source: str = ""      # contour=鞋带面积 | bbox=老 summary 无轮廓时的退化估计
    scrape_volume_mm3: float = 0.0

    def as_plc_dict(self) -> dict[str, Any]:
        """块写字段（一次写入，回读确认）：4 数组 + 进给。

        不含 g_pass_z（每 pass 由上位机 VM 循环单独写）与 g_pass_count（PLC 不再内部循环，不下发）。
        """
        return {
            "g_sx":          list(self.g_sx),
            "g_sy":          list(self.g_sy),
            "g_cx":          list(self.g_cx),
            "g_cy":          list(self.g_cy),
            "g_scrape_feed": int(self.g_scrape_feed),
        }

    def as_action_result(self) -> dict[str, Any]:
        """cnc_path 动作返回给 operation VM 的完整 result。

        VM 用法：
          - 块写：plc_write(args = {sx: result.g_sx, ..., feed: result.g_scrape_feed})
          - pass 循环：for k in range(result.pass_count): 写 g_pass_z = result.pass_z_list[k]
        """
        d = self.as_plc_dict()
        d["pass_count"] = int(self.pass_count)
        d["pass_z_list"] = [float(z) for z in self.pass_z_list]
        d["start_x_mm"] = float(self.start_x_mm)   # 路径首点标量, 供对位检查内环(VM 无数组下标)
        d["start_y_mm"] = float(self.start_y_mm)
        d["band_cm"] = [float(v) for v in self.band_cm]   # 三维孪生画刮痕用, 不下发 PLC
        # 物料账本记粉量用(material_bindings 的 photoscrape.cnc_path -> scrape_arm 取这三个键)。
        # VM 按 field 名取键, 多的键没人取, 向后兼容。
        d["scrape_area_mm2"] = float(self.scrape_area_mm2)
        d["scrape_area_source"] = str(self.scrape_area_source)
        d["scrape_volume_mm3"] = float(self.scrape_volume_mm3)
        return d


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
    y_shift_cm: float = 0.0,
    y_extra_cm: float = 0.0,
    y_ratio: float = 1.0,
    tool_radius_cm: float = 0.0,
    **_: Any,
) -> list[tuple[float, float]]:
    """轮廓驱动的按列扫描：沿 X 等分 columns 列，每列取轮廓上下边缘交点，
    并应用 keep_ratio 以重心为中心两侧各扩 列长×k/2。

    contour=None 或不可用 → fallback _path_boustrophedon（保证老 summary / fixture 仍可用）。

    y_shift_cm / y_extra_cm / y_ratio（收集路径专用，刮取传默认 0/0/1 → 逐点不变）：
      每列在轮廓采样得到的局部半高上做 affine 变换 half = y_ratio×局部半高 + y_extra_cm，
      中心上叠加 y_shift_cm，半高下钳到 0：
        - y_ratio（collect_expand_ratio）: 乘性包络，按比例放大局部带半高（治硅胶崩飞，随带体量正比）
        - y_extra_cm（collect_margin−桶口半径）: 绝对余量（恒定散粉晕 + 桶口口径）
        - y_shift_cm（bottle_y_offset）: 装配偏移平移中心
      既"追随带形状"又真正响应三个参数（真机可调）。仅在真正用到轮廓采样的列生效；超出轮廓
      X 范围 / 退化截面的列退回 bbox 截面（该 bbox 已含 ratio/margin/offset，不再重复叠加，避免双计）。

    tool_radius_cm(刀具半径补偿, 刮取专用, 收集传 0):
      每列采样改走 _erode_column_interval(圆盘腐蚀列向投影), 刀刃外缘不越轮廓;
      腐蚀区间倒置(带窄于刀)的列收拢到区间中点(对称过切 ≤ 刀半径), 汇总 WARN 一条。
      0 = 直通老采样, 逐字节零回归。
    """
    if not (0.0 < keep_ratio <= 1.0):
        raise ValueError(f"contour: keep_ratio 必须在 (0, 1]，得到 {keep_ratio}")

    if contour is None or contour.shape[0] < 3:
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
    contour_x_lo = float(contour[:, 0].min())
    contour_x_hi = float(contour[:, 0].max())
    n_collapsed = 0
    points: list[tuple[float, float]] = []
    for col in range(columns):
        col_idx = (columns - 1 - col) if reverse_x else col
        x_query = start_x + col_idx * x_step_cm
        # 圆盘腐蚀采样(radius=0 时等价原扫描线); 上下交点 → 刀具中心可行区间
        sample = _erode_column_interval(
            contour, x_query, tool_radius_cm, (contour_x_lo, contour_x_hi),
        )
        collapsed = (
            tool_radius_cm > 1e-12
            and sample is not None
            and (sample[0] - sample[1]) < 1e-9
        )
        # 真正用到轮廓采样（非 None 且非退化截面）才叠加收集偏移/余量
        used_contour = sample is not None and (sample[0] - sample[1]) >= 1e-9
        if collapsed:
            # 带窄于刀: 收拢腐蚀区间中点(对称过切 ≤ 刀半径; Z 全程下压无法跳列)
            y_top, y_bot = sample
            center_y = (y_top + y_bot) / 2.0 + y_shift_cm
            half_len = 0.0
            n_collapsed += 1
        elif used_contour:
            y_top, y_bot = sample
            center_y = (y_top + y_bot) / 2.0 + y_shift_cm
            half_len = max(0.0, y_ratio * (y_top - y_bot) * keep_ratio / 2.0 + y_extra_cm)
        else:
            # 超出轮廓 X 范围 / 上下边缘重合 → 退回 bbox 截面（已含偏移余量，不再叠 delta）
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
    if n_collapsed:
        log.warning(
            "_path_contour: %d/%d 列腐蚀后窄于刀径, 已收拢中线(对称过切 ≤ 刀半径)",
            n_collapsed, columns,
        )
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
            if contour_arr.shape[0] < 3:
                contour_arr = None  # 少于 3 点无法围成闭合面积 (扫描线 _sample_contour_y_scanline 需 ≥3 顶点)
        except (KeyError, TypeError, ValueError):
            contour_arr = None

    return bbox, contour_arr


def _polygon_area_cm2(contour: np.ndarray | None) -> float:
    """闭合多边形面积（鞋带公式），单位 cm²；点数不足或退化时返回 0.0。

    contour 是 path_json 的 contour_cm —— 视觉分割出的**真实谱带轮廓**，首尾不必闭合
    （np.roll 天然循环）。取绝对值：顶点绕向（CW/CCW）由视觉侧决定，本函数不作约定。

    这是全链唯一能拿到"被刮走多少硅胶"的地方：PLC 只收机床 mm 数组反算不回来，而
    vision_controller 的 area_cm2 是 vertical_width × horizontal_span 的 **bbox 面积**，
    对弯曲谱带明显高估。真实分割面积 cv2.contourArea 在视觉侧算过但从不写进 summary，
    所以这里从 contour_cm 顶点重算。
    """
    if contour is None or len(contour) < 3:
        return 0.0
    x, y = contour[:, 0], contour[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) / 2.0)


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


def _erode_column_interval(
    contour: np.ndarray,
    x: float,
    radius_cm: float,
    x_clamp: tuple[float, float],
    n_samples: int = 17,
) -> tuple[float, float] | None:
    """列向圆盘腐蚀: 列 x 处刀具中心可行 Y 区间(刀刃不越轮廓)。

    圆盘腐蚀的精确列向投影(dx 均匀采样近似):
      y_top'(x) = min over dx∈[−R,R] of ( y_top(x+dx) − √(R²−dx²) )
      y_bot'(x) = max over dx∈[−R,R] of ( y_bot(x+dx) + √(R²−dx²) )
    斜边处弦高项收得比"朴素恒减 R"更紧(大刀径动机场景)。

    radius_cm ≤ 0 → 直通 _sample_contour_y_scanline(零回归)。
    采样 x+dx 钳到 x_clamp 内(留 1e-6 防扫描线在垂直端边失效); 单点采样 None 则跳过。
    返回可能 y_top' < y_bot'(带窄于刀的收拢信号), 由调用方判定; 全部采样失败返回 None。
    """
    if radius_cm <= 1e-12:
        return _sample_contour_y_scanline(contour, x)
    lo, hi = x_clamp
    eps = 1e-6
    y_top = math.inf
    y_bot = -math.inf
    found = False
    for i in range(n_samples):
        dx = -radius_cm + (2.0 * radius_cm) * i / (n_samples - 1)
        xq = min(max(x + dx, lo + eps), hi - eps)
        sample = _sample_contour_y_scanline(contour, xq)
        if sample is None:
            continue
        chord = math.sqrt(max(radius_cm * radius_cm - dx * dx, 0.0))
        y_top = min(y_top, sample[0] - chord)
        y_bot = max(y_bot, sample[1] + chord)
        found = True
    if not found:
        return None
    return y_top, y_bot


def _inset_interval(lo: float, hi: float, r: float) -> tuple[float, float]:
    """区间双侧内缩 r; 宽度 ≤ 2r 时收拢为中点(带窄于刀, 对称过切最小)。"""
    if hi - lo <= 2.0 * r:
        mid = (lo + hi) / 2.0
        return mid, mid
    return lo + r, hi - r


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


def _mirror_contour_x(contour: "np.ndarray | None", pivot_cm: float) -> "np.ndarray | None":
    """把 contour 的 X 绕 pivot_cm 反射(收集器侧解耦: 整条路径镜像回规范帧用), Y 不变。"""
    if contour is None:
        return None
    mirrored = np.array(contour, dtype=float, copy=True)
    if mirrored.ndim == 2 and mirrored.shape[1] >= 1:
        mirrored[:, 0] = 2.0 * pivot_cm - mirrored[:, 0]
    return mirrored


def _build_collect_points(
    bbox_cm: tuple[float, float, float, float],
    path_fn: Callable[..., list[tuple[float, float]]],
    *,
    bottle_x_offset_mm: float,
    plate_origin_x: float,
    plate_origin_y: float,
    flip_x: bool,
    flip_y: bool,
    contour: np.ndarray | None,
    y_center: float,
    y_half: float,
    y_shift_cm: float,
    y_extra_cm: float,
    y_ratio: float,
    tail_cm: float,
    return_sweep: bool,
    n_points: int = COLLECT_POINT_COUNT,
) -> list[tuple[float, float]]:
    """收集路径点序：拖尾正向补收 [+ 残粉 −X 回走]，连续接刮取终点。

    真机几何：铣刀与收集器(粉桶)刚性同体、X 向相距 bottle_x_offset(≈8.5cm)、收集器拖在
    铣刀后；刮取时真空全程开，band 主体边刮边吸，铣刀到 x_max 时收集器才到 x_max−tail，
    最后 tail 段铣了未吸。粉桶无 Z（永远贴面）→ 每步移动都在推粉，只能靠 XY 路径规划。

    设计（拷问收敛，见 docs / memory[cnc-collect-path-tail-return]）：
      ① 拖尾段（+X）：从 x_max−tail（=收集器刮取真实落点，g_cx[1] 与 g_sx[400] 连续，首步小）
         轻扫到 x_max，补铣刀-收集器偏置漏收的 tail 段。薄粉，真空压倒桶壁推力
         （= 旧版已验证可接受的"只走拖尾"行为，绝非一次性大跨步怼边）。
      ② 回走段（−X，仅 return_sweep=True）：从 x_max 一路扫回 x_min 收残粉，全程 −X，
         桶壁只朝板内推。x_min 也是开口边但残粉已被吸得极薄，不留安全边。

    取代旧实现"凭空把桶怼到 x_max+margin 板外缘再反扫"——那一怼 +X 把右边缘粉推出界，
    是带粉出界的代码根源。中心点封顶 [x_min, x_max] 不外扩越界，板边覆盖交给桶口半径
    （bottle_diameter/2 > 旧 cutter 半径 margin，覆盖反而更全）。

    实现：per_col=2（平面收集足够，与 _compute_coverage_columns 同哲学）；总列数按 X 跨度
    在拖尾/回走两段间分配，每段各自满足 n_points % columns == 0，拼接后恰好 n_points 点。
    """
    x_min, _, x_max, _ = bbox_cm
    y_lo, y_hi = y_center - y_half, y_center + y_half
    per_col = 2
    total_cols = max(1, n_points // per_col)
    tail_start = max(x_min, x_max - tail_cm)

    def _seg(bx0: float, bx1: float, cols: int, n_pts: int, reverse: bool) -> list[tuple[float, float]]:
        if cols < 1 or n_pts < per_col:
            return []
        return path_fn(
            (bx0, y_lo, bx1, y_hi),
            x_offset_mm=bottle_x_offset_mm,  # 补偿铣刀-收集器安装偏移
            plate_origin_x=plate_origin_x,
            plate_origin_y=plate_origin_y,
            flip_x=flip_x, flip_y=flip_y,
            x_start_cm=None,
            n_points=n_pts,
            columns=cols,
            keep_ratio=1.0,        # collect 始终用全列长
            contour=contour,
            reverse_x=reverse,
            y_shift_cm=y_shift_cm,  # 轮廓策略下叠加装配偏移(bottle_y_offset)
            y_extra_cm=y_extra_cm,  # 轮廓策略下叠加绝对余量净扣桶口半径(collect_margin)
            y_ratio=y_ratio,        # 轮廓策略下乘性包络缩放局部半高(collect_expand_ratio)
        )

    if not return_sweep:
        # 仅拖尾：全部点铺在 [tail_start, x_max] 正向（退回旧"只走拖尾"行为）
        return _seg(tail_start, x_max, total_cols, n_points, reverse=False)

    # 拖尾 + 回走：按 X 跨度分配列（拖尾占小头、回走占大头），各自整除
    tail_x = max(x_max - tail_start, 0.0)
    full_x = tail_x + (x_max - x_min)
    tail_cols = max(1, round(total_cols * tail_x / full_x)) if full_x > 1e-9 else 1
    tail_cols = min(tail_cols, total_cols - 1)  # 至少给回走留 1 列
    return_cols = total_cols - tail_cols
    seg_tail = _seg(tail_start, x_max, tail_cols, tail_cols * per_col, reverse=False)    # ① +X 补尾
    seg_return = _seg(x_min, x_max, return_cols, return_cols * per_col, reverse=True)    # ② −X 回走
    return seg_tail + seg_return


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
    collect_margin_mm: float | None = None,
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
        collect_margin_mm: 收集路径 Y 方向绝对余量(mm)覆盖(None 时取 gcode_cfg.collect_margin_mm)。
        collect_expand_ratio: 收集路径 Y 乘性包络覆盖(None 时取 gcode_cfg.collect_expand_ratio, [1.0,2.0])。
            收集 Y 半span(affine) = collect_expand_ratio × 带半高 + (collect_margin_mm − 桶口半径)/10;
            桶口半径 = bottle_diameter_mm/2。乘性治硅胶崩飞(随带体量正比), 绝对治恒定散粉晕+桶口口径。

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

    # ── 被刮掉的硅胶体积(只给物料账本与三维; 不进任何路径计算) ──────────────────
    # 面积用 contour_cm 的鞋带面积而不是 bbox: 谱带是弯的, bbox 会高估相当多。
    # 用**未镜像**的原件算 —— 下面 collector_x_positive 那段镜像不改面积, 但用原件更诚实。
    # contour_cm 是 path_json 的可选字段(老 summary 没有), 缺了退回 bbox 并把来源标出来:
    # 三维据此决定粉柱高度要不要打问号, 物料流水里也看得见这一笔是量的还是估的。
    scrape_area_cm2 = _polygon_area_cm2(contour_cm)
    scrape_area_source = "contour"
    if scrape_area_cm2 <= 0.0:
        scrape_area_cm2 = max(0.0, (bbox_cm[2] - bbox_cm[0]) * (bbox_cm[3] - bbox_cm[1]))
        scrape_area_source = "bbox"
    scrape_area_mm2 = scrape_area_cm2 * 100.0
    scrape_volume_mm3 = (
        scrape_area_mm2 * gcode_cfg.scrape.total_depth_mm * gcode_cfg.scrape.bulk_factor
    )

    flip_x, flip_y = _flip_from_corner(gcode_cfg.origin_corner)

    # ── 收集器物理侧解耦(见 memory[photoscrape-vision-frame-consistency] 0709) ──
    # 收集拖尾/回走几何在 flip_x=True 的规范帧调参; 收集器在机床 +X 侧 → 该帧下 cutter 落 band −X,
    # 收集器正好压 band。当实际 origin_corner 的 flip_x 与收集器侧不符(如 rot0/lower-left+收集器+X),
    # 把整条路径(刮取+收集)的 X **绕 bbox 右端反射 + origin_x 补偿 + flip_x→True** 镜像回规范帧:
    #   机床位置不变(o_c − x_mir = plate_origin_x + x)，只镜像遍历序; 收集 offset 因而正确朝 band 反侧,
    #   并逐点复现真机 top-right 调参下的收集几何(含连续性)。默认 collector_x_positive=False → 不镜像(零回归)。
    if gcode_cfg.collector_x_positive != flip_x:
        _pivot = bbox_cm[2]  # 绕 bbox x_max 反射(保正坐标)
        eff_bbox = (2.0 * _pivot - bbox_cm[2], bbox_cm[1], 2.0 * _pivot - bbox_cm[0], bbox_cm[3])
        eff_contour = _mirror_contour_x(contour_cm, _pivot)
        eff_flip_x = True
        eff_origin_x = gcode_cfg.plate_origin_x + 2.0 * _pivot * 10.0
    else:
        eff_bbox, eff_contour, eff_flip_x, eff_origin_x = (
            bbox_cm, contour_cm, flip_x, gcode_cfg.plate_origin_x,
        )

    # ── 刀具半径补偿(纯度优先, spec: docs/superpowers/specs/2026-07-13-cutter-compensation-design.md):
    #   刮扫中心路径内缩 R = 刀半径 + 纯度安全边 → 刀刃外缘不越谱带轮廓, 不刮进相邻杂带;
    #   收集路径不补偿(粉末落在切削区内, 桶口覆盖只多不少)。默认关 = 零回归, 真机 app.yaml 显式开。
    comp_r_cm = (
        (gcode_cfg.tool.cutter_diameter_mm / 2.0 + gcode_cfg.tool.compensation_margin_mm) / 10.0
        if gcode_cfg.tool.cutter_compensation else 0.0
    )
    scrape_bbox = eff_bbox
    if comp_r_cm > 0.0:
        sx_lo, sx_hi = _inset_interval(eff_bbox[0], eff_bbox[2], comp_r_cm)
        sy_lo, sy_hi = _inset_interval(eff_bbox[1], eff_bbox[3], comp_r_cm)
        if sx_hi - sx_lo <= 1e-9:  # 与 _check_degenerate 的 x_max-1e-9 阈值对齐, 消 (1e-12,1e-9] 击穿缝
            # 整带 X 跨 ≤ 刀径+边: 收拢中心单列一刀过(对称过切物理不可避免)。名义半宽 1e-6cm
            # 避开 _check_degenerate 的占位分支(那会整段不刮丢材料), round(3) 后为同一机床点。
            sx_lo, sx_hi = sx_lo - 1e-6, sx_hi + 1e-6
            log.warning(
                "[cnc_path_generator] 刀具补偿: band X 跨 %.3fcm ≤ 2R=%.3fcm, 收拢为中心单列",
                eff_bbox[2] - eff_bbox[0], 2.0 * comp_r_cm,
            )
        scrape_bbox = (sx_lo, sy_lo, sx_hi, sy_hi)

    # ── 铣刀覆盖率：自动推导列数 ──
    scrape_step_mm = _effective_step_mm(
        gcode_cfg.tool.cutter_diameter_mm, gcode_cfg.scrape.overlap_ratio,
    )
    x_min, _, x_max, _ = bbox_cm
    x_span_scrape_mm = (scrape_bbox[2] - scrape_bbox[0]) * 10.0

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
        "columns":        effective_columns,
        "keep_ratio":     effective_keep_ratio,
        "contour":        eff_contour,
        "tool_radius_cm": comp_r_cm,   # 刀具半径补偿(zigzag/boustrophedon 靠 bbox 内缩, 由 **_ 吞掉)
    }

    # 刮扫 400 点：覆盖整个 bbox X 跨度（收集器解耦: 用 eff_* 镜像帧, 机床位置不变）
    g_sxy = path_fn(
        scrape_bbox,
        x_offset_mm=0.0,
        plate_origin_x=eff_origin_x,
        plate_origin_y=gcode_cfg.plate_origin_y,
        flip_x=eff_flip_x, flip_y=flip_y,
        x_start_cm=None,
        n_points=SCRAPE_POINT_COUNT,
        **strategy_kwargs,
    )
    g_sx = [pt[0] for pt in g_sxy]
    g_sy = [pt[1] for pt in g_sxy]

    # ── 收集 400 点：拖尾正向补收 + 残粉 −X 回走（连续接刮取终点，见 _build_collect_points）──
    # 无 Z 粉桶：路径保证桶壁永不朝 x_max 开口边推粉。收集 Y 半span 为 affine:
    #   y_half = collect_expand_ratio × 带半高 + (collect_margin − 桶口半径)  (中心加装配偏移)
    #   乘性包络(治崩飞, 随带体量正比) 与 绝对余量(恒定散粉晕 + 桶口口径) 各管各的, 线性叠加。
    effective_collect_margin_mm = (
        float(collect_margin_mm) if collect_margin_mm is not None
        else float(gcode_cfg.collect_margin_mm)
    )
    if effective_collect_margin_mm < 0.0:
        raise ValueError(
            f"collect_margin_mm 必须 ≥ 0, 得到: {effective_collect_margin_mm}"
        )
    effective_collect_expand = (
        float(collect_expand_ratio) if collect_expand_ratio is not None
        else float(gcode_cfg.collect_expand_ratio)
    )
    if not (1.0 <= effective_collect_expand <= 2.0):
        raise ValueError(
            f"collect_expand_ratio 必须在 [1.0, 2.0], 得到: {effective_collect_expand}"
        )
    mouth_radius_cm = gcode_cfg.tool.bottle_diameter_mm / 2.0 / 10.0
    # 三个参数的两种等价表示（同一真源，不会双计——见 _path_contour / _build_collect_points）：
    #   y_center/y_half：整带均匀矩形（boustrophedon 策略与轮廓退化列的 bbox 截面用）
    #   y_shift_cm/y_extra_cm/y_ratio：增量（contour 策略下叠加到逐列轮廓中心/半高，实现"追随带形状 + 三参数"）
    y_shift_cm = gcode_cfg.tool.bottle_y_offset_mm / 10.0
    y_extra_cm = effective_collect_margin_mm / 10.0 - mouth_radius_cm
    y_center = (bbox_cm[1] + bbox_cm[3]) / 2.0 + y_shift_cm
    y_half = max(0.0, effective_collect_expand * (bbox_cm[3] - bbox_cm[1]) / 2.0 + y_extra_cm)
    tail_cm = gcode_cfg.tool.bottle_x_offset_mm / 10.0  # 铣刀-收集器偏置 = 拖尾长度
    g_cxy = _build_collect_points(
        eff_bbox, path_fn,
        bottle_x_offset_mm=gcode_cfg.tool.bottle_x_offset_mm,
        plate_origin_x=eff_origin_x,
        plate_origin_y=gcode_cfg.plate_origin_y,
        flip_x=eff_flip_x, flip_y=flip_y,
        contour=eff_contour,
        y_center=y_center, y_half=y_half,
        y_shift_cm=y_shift_cm, y_extra_cm=y_extra_cm, y_ratio=effective_collect_expand,
        tail_cm=tail_cm,
        return_sweep=gcode_cfg.collection.return_sweep,
    )
    g_cx = [pt[0] for pt in g_cxy]
    g_cy = [pt[1] for pt in g_cxy]

    # ── 机床 Y 软下限保护(防撞机): 非 None 时刮取/收集 Y 钳到下限, 有钳制即告警 ──
    #   底边(点样线, machine Y≈plate_origin_y)离撞机 <5mm; band 贴底/收集拖尾/y_shift 误差
    #   可能把 Y 压到危险边界。钳制会截平路径底部(牺牲覆盖保设备), 故必须告警让人复核。
    #   默认 None=关 → 零回归(不改现有数组)。
    y_floor = gcode_cfg.machine_y_min_mm
    if y_floor is not None:
        n_clamped = sum(1 for v in g_sy if v < y_floor) + sum(1 for v in g_cy if v < y_floor)
        if n_clamped:
            worst = min(min(g_sy), min(g_cy))
            log.warning(
                "[cnc_path_generator] band=%s 机床 Y 触软下限 %.1fmm: %d/%d 点被钳(最低 %.1fmm), "
                "路径底部被截平以防撞机——复核 plate_origin_y / band 是否贴撞机边",
                band_id, y_floor, n_clamped, len(g_sy) + len(g_cy), worst,
            )
            g_sy = [max(v, y_floor) for v in g_sy]
            g_cy = [max(v, y_floor) for v in g_cy]

    # Z / 进给参数
    g_pass_count = max(1, int(gcode_cfg.scrape.num_passes))
    # 每 pass 的 Z（k=1..passes），上位机 VM 循环逐 pass 写入 g_pass_z（PLC 不再内部计算）：
    #   pass_z[k] = plate_surface + k * total_depth / num_passes
    depth_per_pass = gcode_cfg.scrape.total_depth_mm / g_pass_count
    pass_z_list = [
        round(gcode_cfg.plate_surface_z_mm + k * depth_per_pass, 3)
        for k in range(1, g_pass_count + 1)
    ]

    arrays = ScrapeArrays(
        g_sx=g_sx,
        g_sy=g_sy,
        g_cx=g_cx,
        g_cy=g_cy,
        g_scrape_feed=int(gcode_cfg.scrape.feed_rate),
        pass_count=g_pass_count,
        pass_z_list=pass_z_list,
        start_x_mm=g_sx[0] if g_sx else 0.0,   # 路径首点(机床 mm), 供对位检查内环走起点
        start_y_mm=g_sy[0] if g_sy else 0.0,
        # 未内缩的原始带 bbox(刀补只影响刀心路径, 被刮掉的仍是整条带) —— 三维孪生画刮痕用
        band_cm=[float(bbox_cm[0]), float(bbox_cm[1]), float(bbox_cm[2]), float(bbox_cm[3])],
        # 粉量三兄弟 —— 物料账本按 scrape_arm/powder_fill 两段式落进那只桶所属的托盘格
        scrape_area_mm2=round(scrape_area_mm2, 2),
        scrape_area_source=scrape_area_source,
        scrape_volume_mm3=round(scrape_volume_mm3, 2),
    )

    # 健全性诊断
    span_scrape_mm = (scrape_bbox[2] - scrape_bbox[0]) * 10.0  # 内缩后跨度, 与 columns 推导同源(勿用未内缩 x_max-x_min)
    avg_step_mm = span_scrape_mm / (SCRAPE_POINT_COUNT - 1) if SCRAPE_POINT_COUNT > 1 else 0.0
    log.info(
        "[cnc_path_generator] band=%s strategy=%s keep_ratio=%.2f contour=%s "
        "bbox=[%.2f,%.2f]-[%.2f,%.2f]cm columns=%d scrape_step≈%.2fmm pass_count=%d "
        "collect=%s(tail=%.1fcm) collect_margin=%.1fmm expand=%.2f y_off=%.1fmm comp=%s "
        "powder=%.1fmm³(面积 %.1fmm²/%s × 深 %.2fmm × 松散 %.2f)",
        band_id, strategy_name, effective_keep_ratio,
        "yes" if contour_cm is not None else "no",
        x_min, bbox_cm[1], x_max, bbox_cm[3],
        effective_columns, avg_step_mm, g_pass_count,
        "拖尾+回走" if gcode_cfg.collection.return_sweep else "仅拖尾",
        gcode_cfg.tool.bottle_x_offset_mm / 10.0, effective_collect_margin_mm,
        effective_collect_expand, gcode_cfg.tool.bottle_y_offset_mm,
        "on(R=%.2fmm)" % (comp_r_cm * 10.0) if comp_r_cm > 0 else "off",
        scrape_volume_mm3, scrape_area_mm2, scrape_area_source,
        gcode_cfg.scrape.total_depth_mm, gcode_cfg.scrape.bulk_factor,
    )
    return arrays


def safe_placeholder_arrays(gcode_cfg: GCodeCfg) -> ScrapeArrays:
    """安全占位数组：pass_count=0 → VM 刮取循环执行 0 次（不触发任何 scrape）。

    用于：
      - 视觉失败用户选择继续
      - band 选择超时（manual 模式）
      - 重刮模式路径生成失败
      - 未配 VisionService

    所有数组全 0、pass_z_list 空，即便误下发也无刮取动作，不会撞板。
    """
    zeros = [0.0] * SCRAPE_POINT_COUNT
    return ScrapeArrays(
        g_sx=zeros, g_sy=zeros, g_cx=zeros, g_cy=zeros,
        g_scrape_feed=int(gcode_cfg.scrape.feed_rate),
        pass_count=0,
        pass_z_list=[],
    )


class CncPathController:
    """cnc_path 计算动作后端: 按运行期实时 GCodeCfg 生成 ScrapeCNC 路径结果。

    供 ActionExecutor 的 vision 动作 (method=generate_cnc_path) 注入调用。
    gcode_cfg_provider 每次执行时调用 → 实时读 app.yaml gcode 段, config 页改动即时生效。
    """

    def __init__(
        self,
        gcode_cfg_provider: Callable[[], GCodeCfg],
        image_root_provider: Callable[[], Path] | None = None,
        event_sink: Callable[[dict], None] | None = None,
    ) -> None:
        self._gcode_cfg = gcode_cfg_provider
        self._image_root = image_root_provider
        # 三维孪生的刮取条带来源(可选注入; 离线单测不给就不发事件)
        self._event_sink = event_sink

    def _emit_scrape_armed(self, arrays: Any, cfg: GCodeCfg) -> None:
        """发一条 `scrape_state`, 把**本次视觉解出的真实谱带**告诉三维孪生。

        为什么必须由后端发, 而不是前端从既有事件里凑:
          · 谱带 bbox 只在这里存在 —— 下发 PLC 的是机床 mm 数组, 反算不回板帧;
          · 层号可以由 write_pass_z 的 args 反推, 但那要前端自己拿 gcode 配置做除法,
            两处各推一遍迟早漂。这条事件把"条带 + 总刀数"一次给全, 层进度仍交给
            前端按 write_pass_z 的 z 值定位(见 web 侧 ScrapeStateStore)。

        事件类型**不进** runtime/events.py 的 _DROPPABLE_TYPES: 它是增量语义(丢了
        条带就永远画不出刮痕), 与 axis_pose 那种"最新快照即全部语义"的流不同。

        Args:
            arrays: ScrapeArrays
            cfg: 本次生效的 GCodeCfg
        """
        if self._event_sink is None:
            return
        try:
            self._event_sink({
                "type": "scrape_state",
                "phase": "armed",
                "band_cm": [float(v) for v in (arrays.band_cm or [])],
                "pass_count": int(arrays.pass_count),
                "pass_z_list": [float(z) for z in arrays.pass_z_list],
                "plate_surface_z_mm": float(cfg.plate_surface_z_mm),
                "total_depth_mm": float(cfg.scrape.total_depth_mm),
            })
        except Exception:  # 三维显示不得影响真机路径生成
            log.warning("[cnc_path] scrape_state 事件发送失败(已忽略)", exc_info=True)

    async def generate_cnc_path(
        self,
        summary_path: str = "",
        band_id: str = "",
        *,
        strategy: str | None = None,
        keep_ratio: float | None = None,
        collect_margin_mm: float | None = None,
        collect_expand_ratio: float | None = None,
        placeholder: bool = False,
    ) -> dict[str, Any]:
        """生成刮取/收集路径数组 + per-pass Z, 返回 VM 可消费的 result dict。

        路径生成为 CPU 密集, 经 run_in_executor 异步化, 不阻塞事件循环。
        summary.json / band 缺失 → FileNotFoundError / KeyError (executor 归一为 INVALID_PARAM)。

        placeholder=True（"无谱带/跳过刮板"路径）：不读 summary/band, 直接返回
        safe_placeholder_arrays（pass_count=0、全 0 数组、pass_z_list 空）。VM 的 pass
        循环因此执行 0 次, scrape 一次也不触发, write_cnc_path/scrape_finish 照常干净收尾,
        即便误下发也绝不撞板。故障（analyze 无谱带 / 路径生成失败）后人工选择跳过时选此路。
        """
        import asyncio

        cfg = self._gcode_cfg()
        if placeholder:
            log.info("[cnc_path] placeholder 请求: 返回 pass_count=0 安全占位数组（跳过刮板）")
            placeholder_arrays = safe_placeholder_arrays(cfg)
            # 跳过刮板也要发: 三维那边要据此把上一轮的刮痕状态清掉(pass_count=0 = 不刮)
            self._emit_scrape_armed(placeholder_arrays, cfg)
            result = placeholder_arrays.as_action_result()
            result.update({
                "preview_available": False,
                "preview_url": "",
                "preview_message": "跳过刮板，无执行路径",
                "path_strategy": str(cfg.path_strategy),
                "point_count": 0,
            })
            return result
        loop = asyncio.get_running_loop()
        summary = Path(summary_path)

        def _generate_and_preview() -> dict[str, Any]:
            # C-5 生命周期: payload 必须与本次 cnc_path 同代 — 先失效前任, 本次失败绝不留陈旧坐标给对账(宁可无图不可错帧)
            (summary.parent / "preview_payload.json").unlink(missing_ok=True)
            arrays = generate_scrape_arrays(
                Path(summary_path), band_id, cfg,
                strategy=strategy, keep_ratio=keep_ratio,
                collect_margin_mm=collect_margin_mm,
                collect_expand_ratio=collect_expand_ratio,
            )
            self._emit_scrape_armed(arrays, cfg)
            result = arrays.as_action_result()
            result.update({
                "preview_available": False,
                "preview_url": "",
                "preview_path": "",
                "preview_payload_path": "",
                "preview_message": "",
                "path_strategy": str(strategy or cfg.path_strategy),
                "point_count": len(arrays.g_sx),
            })
            try:
                from eit_ptlc.controller.cnc_preview import (
                    default_backdrop,
                    preview_payload_from_arrays,
                    render_cnc_overlay,
                )

                preview = preview_payload_from_arrays(summary, band_id, arrays, cfg)
                # C-5: payload 先落盘 — 对账叠加只读此文件, 与门 preview 逐字节同源
                payload_path = summary.parent / "preview_payload.json"
                payload_path.write_text(
                    json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
                result["preview_payload_path"] = str(payload_path)
                backdrop = default_backdrop(summary)
                if backdrop is None:
                    result["preview_message"] = "未找到 after_normalized.jpg/after.jpg，未生成 CNC 预览"
                    return result
                safe_band = "".join(
                    char if (char.isalnum() or char in "-_.") else "_"
                    for char in Path(str(band_id)).name
                )[:100] or "band"
                preview_path = summary.parent / f"{safe_band}_cnc_preview.png"
                if not render_cnc_overlay(backdrop, preview, preview_path):
                    result["preview_message"] = "CNC 预览渲染失败"
                    return result
                result["preview_available"] = True
                result["preview_path"] = str(preview_path)
                if self._image_root is not None:
                    try:
                        root = Path(self._image_root()).resolve()
                        rel = preview_path.resolve().relative_to(root).as_posix()
                        result["preview_url"] = f"/api/vision/image/{rel}"
                    except (OSError, ValueError):
                        result["preview_message"] = "预览已生成，但不在视觉服务目录内"
                return result
            except Exception as exc:  # 预览失败不得污染已经生成的真机数组
                log.warning("[cnc_path] 真机数组已生成，但 CNC 预览失败: %s", exc, exc_info=True)
                result["preview_message"] = f"CNC 预览失败: {exc}"
                return result

        return await loop.run_in_executor(None, _generate_and_preview)
