"""GCodeGenerator - 封装 tlc_gcode.py 的 G-code 生成逻辑。

直接 import View/pTLC_Viewing/tlc_gcode.py 的 generate_gcode() + GCodeConfig，
不复制代码，通过 sys.path 注入实现跨目录调用。

外部公共签名（GCodeGenerator.generate 的 17 个 kwargs）保持不变，调用点零感知；
内部一次性打包为 tlc_gcode.GCodeConfig 后调用 tlc_gcode.generate_gcode。
"""

import logging
import json
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# tlc_gcode 所在目录（相对本文件：../../View/pTLC_Viewing）
_VIEW_DIR = Path(__file__).parent.parent.parent / "View" / "pTLC_Viewing"


def _patch_summary_paths(summary_path: Path, work_dir: Path) -> Path:
    """修复 summary.json 中的相对路径，使 tlc_gcode 能正确定位文件。

    原始 summary.json 中的 path_json / contour_path_image 等路径是
    相对于 tlc_analyze.py 运行目录的。当 analysis 目录被移动到
    data/samples/<id>/analysis/ 后，这些路径不再有效。

    本函数将相对路径替换为绝对路径（基于 analysis 目录推算），
    生成一份修正后的临时 summary.json 供 tlc_gcode 使用。
    """
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    analysis_dir = summary_path.parent

    def _fix_path(rel_str: str) -> str:
        """将原始相对路径转换为绝对路径。

        原始路径形如 analysis_output/case1/task1_task2_contours_paths/band_01_path.json。
        取最后两级（子目录名 + 文件名）拼接 analysis_dir 得到绝对路径。
        """
        if not rel_str:
            return rel_str
        p = Path(rel_str)
        # 取最后两级：task1_task2_contours_paths/band_01_path.json
        parts = p.parts
        if len(parts) >= 2:
            resolved = analysis_dir / Path(*parts[-2:])
        else:
            resolved = analysis_dir / p
        # 返回绝对路径字符串（resolve_path_json 会先尝试 Path(rel).exists()）
        return str(resolved.resolve()) if resolved.exists() else rel_str

    for band in summary.get("bands", []):
        if "path_json" in band:
            band["path_json"] = _fix_path(band["path_json"])
        if "contour_path_image" in band:
            band["contour_path_image"] = _fix_path(band["contour_path_image"])
        if "metrics_image" in band:
            band["metrics_image"] = _fix_path(band["metrics_image"])
        if "metrics_pdf" in band:
            band["metrics_pdf"] = _fix_path(band["metrics_pdf"])
        if "contour_path_pdf" in band:
            band["contour_path_pdf"] = _fix_path(band["contour_path_pdf"])

    for key in ("path_json_files", "metric_json_files"):
        if key in summary:
            summary[key] = [_fix_path(p) for p in summary[key]]

    patched_path = work_dir / f"_patched_{summary_path.name}"
    patched_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return patched_path


class GCodeGenerator:
    """封装 tlc_gcode.py 的 G-code 生成逻辑。"""

    @staticmethod
    def _ensure_tlc_gcode():
        """动态注入 tlc_gcode 所在目录并导入 generate_gcode + GCodeConfig。"""
        view_dir_str = str(_VIEW_DIR)
        if view_dir_str not in sys.path:
            sys.path.insert(0, view_dir_str)
        try:
            from tlc_gcode import GCodeConfig, generate_gcode  # type: ignore  # noqa: PLC0415
            return generate_gcode, GCodeConfig
        except ImportError as e:
            raise RuntimeError(f"无法导入 tlc_gcode，请检查路径 {_VIEW_DIR}: {e}") from e

    @staticmethod
    def generate(
        summary_path: Path,
        selected_band_ids: list[str],
        plate_origin_x: float = 0.0,
        plate_origin_y: float = 0.0,
        origin_corner: str = "lower-left",
        # New Z params (replace old scrape_z, safe_z, approach_z)
        plate_surface_z_mm: float = 7.0,
        safe_z_mm: float = 5.0,
        approach_z_mm: float = 6.5,
        # New tool params
        cutter_diameter_mm: float = 2.0,
        bottle_diameter_mm: float = 5.0,
        bottle_x_offset_mm: float = 85.0,
        # New scrape params
        total_depth_mm: float = 1.0,
        num_passes: int = 3,
        scrape_overlap_ratio: float = 0.3,
        scrape_feed_rate: int = 800,
        plunge_rate: int = 200,
        # New collection params
        collection_overlap_ratio: float = 0.5,
        collection_feed_rate: int = 800,
        collection_mode: str = "per_pass",
        include_origin: bool = False,
        output_path: Path | None = None,
    ) -> tuple[str, Path]:
        """生成 G-code 并写入文件。

        Args:
            summary_path: summary.json 文件路径。
            selected_band_ids: 选中的 band ID 列表（如 ["band_01", "band_03"]）。
            origin_corner: 机床原点角（lower-left / top-right / top-left / bottom-right），
                默认 lower-left；真机标定后通过上层从 config.yaml 注入。
            plate_surface_z_mm: 板面 Z 高度 (mm)。
            safe_z_mm: 安全高度 (mm)。
            approach_z_mm: 接近高度 (mm)。
            cutter_diameter_mm: 刮刀直径 (mm)。
            bottle_diameter_mm: 收集瓶直径 (mm)。
            bottle_x_offset_mm: 收集瓶 X 偏移 (mm)。
            total_depth_mm: 总刮取深度 (mm)。
            num_passes: 刮取次数。
            scrape_overlap_ratio: 刮取路径重叠比例。
            scrape_feed_rate: 刮取进给速率。
            plunge_rate: 下刀速率。
            collection_overlap_ratio: 收集路径重叠比例。
            collection_feed_rate: 收集进给速率。
            collection_mode: 收集模式 ("per_pass" 或 "after_all")。
            output_path: 输出 .gcode 文件路径，默认为 summary.json 同目录下的 <case>.gcode。

        Returns:
            (gcode_text, gcode_file_path) 元组。
        """
        generate_gcode, GCodeConfig = GCodeGenerator._ensure_tlc_gcode()

        # 修正 summary.json 中的路径（处理目录迁移情况）
        work_dir = summary_path.parent
        patched_path = _patch_summary_paths(summary_path, work_dir)

        # 预先确定输出路径（tlc_gcode 会直接写出）
        if output_path is None:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            case_name = summary.get("case", summary_path.parent.name)
            output_path = summary_path.parent / f"{case_name}.gcode"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        config = GCodeConfig(
            plate_origin_x=plate_origin_x,
            plate_origin_y=plate_origin_y,
            origin_corner=origin_corner,
            plate_surface_z_mm=plate_surface_z_mm,
            safe_z_mm=safe_z_mm,
            approach_z_mm=approach_z_mm,
            cutter_diameter_mm=cutter_diameter_mm,
            bottle_diameter_mm=bottle_diameter_mm,
            bottle_x_offset_mm=bottle_x_offset_mm,
            total_depth_mm=total_depth_mm,
            num_passes=num_passes,
            scrape_overlap_ratio=scrape_overlap_ratio,
            scrape_feed_rate=scrape_feed_rate,
            plunge_rate=plunge_rate,
            collection_overlap_ratio=collection_overlap_ratio,
            collection_feed_rate=collection_feed_rate,
            collection_mode=collection_mode,
            band_ids=selected_band_ids if selected_band_ids else None,
            include_origin=include_origin,
            output=output_path,
        )

        try:
            # tlc_gcode.generate_gcode 返回 (gcode_text, out_path) 并内部写出 .gcode
            gcode_text, written_path = generate_gcode(patched_path, config)
        finally:
            # 清理临时文件
            try:
                patched_path.unlink()
            except OSError:
                pass

        log.info(
            "[GCodeGenerator] 生成 G-code: %s (%d 字节, %d 条 band)",
            written_path, len(gcode_text), len(selected_band_ids),
        )
        return gcode_text, written_path
