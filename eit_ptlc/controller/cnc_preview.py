"""CNC execution-path preview helpers.

The preview is derived from the exact ``ScrapeArrays`` instance that is returned
to the operation VM.  It never regenerates or approximates the cutter path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller.plate_coords import (  # noqa: F401 — 单一真源; machine_mm_to_cm 兼容再导出
    cm_to_px_affine,
    machine_mm_to_cm,
    machine_mm_to_px,
    plate_bbox_xywh as _plate_bbox_xywh,
)

Point = tuple[float, float]


def _load_preview_geometry(
    summary_path: Path, band_id: str,
) -> tuple[Any, float, list[Point]]:
    """Read plate reference and selected contour without generating a path."""
    from eit_ptlc.controller.cnc_path import _load_band_geometry, _patch_summary_paths

    summary_path = Path(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    plate_bbox_px = summary.get("plate_bbox_px")
    if plate_bbox_px is None:
        raise KeyError("summary 缺少 plate_bbox_px，无法叠加 CNC 预览")
    plate_size_cm = float(summary.get("plate_size_cm", 20.0) or 20.0)

    patched = _patch_summary_paths(summary_path, summary_path.parent)
    try:
        _bbox, contour = _load_band_geometry(patched, band_id)
    finally:
        patched.unlink(missing_ok=True)
    contour_cm = [] if contour is None else [tuple(map(float, point)) for point in contour]
    return plate_bbox_px, plate_size_cm, contour_cm


def preview_payload_from_arrays(
    summary_path: Path | str,
    band_id: str,
    arrays: Any,
    cfg: GCodeCfg,
) -> dict[str, Any]:
    """Map the exact execution arrays back to the normalized plate image frame."""
    plate_bbox_px, plate_size_cm, contour_cm = _load_preview_geometry(
        Path(summary_path), band_id,
    )
    scrape_px = machine_mm_to_px(
        list(zip(arrays.g_sx, arrays.g_sy)), cfg, plate_bbox_px, plate_size_cm,
    )
    collect_px = machine_mm_to_px(
        list(zip(arrays.g_cx, arrays.g_cy)), cfg, plate_bbox_px, plate_size_cm,
    )
    contour_px = cm_to_px_affine(contour_cm, plate_bbox_px, plate_size_cm)
    _px, _py, plate_w_px, _ph = _plate_bbox_xywh(plate_bbox_px)
    cutter_width_px = cfg.tool.cutter_diameter_mm / 10.0 / plate_size_cm * plate_w_px
    return {
        "band_id": band_id,
        "strategy": str(cfg.path_strategy),
        "scrape_px": [[round(x, 1), round(y, 1)] for x, y in scrape_px],
        "collect_px": [[round(x, 1), round(y, 1)] for x, y in collect_px],
        "contour_px": [[round(x, 1), round(y, 1)] for x, y in contour_px],
        "pass_count": int(arrays.pass_count),
        "pass_z_list": [float(value) for value in arrays.pass_z_list],
        "point_count": len(arrays.g_sx),
        "feed": int(arrays.g_scrape_feed),
        "cutter_width_px": round(cutter_width_px, 1),  # 刀宽扫掠带(物理事实, 与补偿开关无关)
        # 板参照随 payload 落盘: 对账叠加/坐标系标注层同源消费 (契约 C-5)
        "plate_bbox_px": plate_bbox_px,
        "plate_size_cm": float(plate_size_cm),
    }


def draw_plate_frame_annotation(image, plate_bbox_px, plate_size_cm) -> None:
    """板坐标系标注层: 四角 X + cm 语义标签, 原点 cm(0,0) 双圈, +x/+y 短箭头。

    标注全部经同一 cm_to_px_affine 画出 — 标注即同源探针: 映射有错, 箭头/角标立错。
    操作员核对口诀: cm 原点角应贴点样边。门 preview 与刮后对账图共用 (spec §5.3)。
    """
    import cv2  # type: ignore
    s = float(plate_size_cm)
    yellow, shadow = (0, 255, 255), (7, 7, 10)
    scale = max(0.5, image.shape[1] / 1600.0)
    r = max(4, int(round(10 * scale)))

    def _pt(cx: float, cy: float) -> tuple[int, int]:
        x, y = cm_to_px_affine([(cx, cy)], plate_bbox_px, s)[0]
        return int(round(x)), int(round(y))

    def _text(label: str, org: tuple[int, int]) -> None:
        for color, thick in ((shadow, 3), (yellow, 1)):
            cv2.putText(image, label, org, cv2.FONT_HERSHEY_SIMPLEX,
                        0.6 * scale + 0.2, color, thick, cv2.LINE_AA)

    for cx, cy in ((0.0, 0.0), (s, 0.0), (0.0, s), (s, s)):
        p = _pt(cx, cy)
        for color, thick in ((shadow, 4), (yellow, 2)):
            cv2.line(image, (p[0] - r, p[1] - r), (p[0] + r, p[1] + r), color, thick, cv2.LINE_AA)
            cv2.line(image, (p[0] - r, p[1] + r), (p[0] + r, p[1] - r), color, thick, cv2.LINE_AA)
        _text(f"cm({int(cx)},{int(cy)})", (p[0] + r + 3, p[1] - r - 3))

    origin = _pt(0.0, 0.0)
    for mul in (1.6, 2.4):  # 双圈: 原点角醒目于其余三角
        cv2.circle(image, origin, int(round(r * mul)), yellow, 2, cv2.LINE_AA)
    for tx, ty, label in ((3.0, 0.0, "+x"), (0.0, 3.0, "+y")):
        tip = _pt(tx, ty)
        cv2.arrowedLine(image, origin, tip, shadow, 4, cv2.LINE_AA, tipLength=0.25)
        cv2.arrowedLine(image, origin, tip, yellow, 2, cv2.LINE_AA, tipLength=0.25)
        _text(label, (tip[0] + 4, tip[1] - 4))


def render_cnc_overlay(
    backdrop_path: Path | str,
    preview: dict[str, Any],
    output_path: Path | str,
) -> bool:
    """Render band contour, exact cutter path and exact collector path."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return False

    image = cv2.imread(str(backdrop_path), cv2.IMREAD_COLOR)
    if image is None:
        return False

    shadow = (7, 7, 10)
    contour_orange = (54, 132, 255)
    cutter_cyan = (236, 216, 0)
    collector_purple = (196, 72, 180)

    def _polyline(points, color, *, closed=False, core=2, halo=4):
        if not points or len(points) < (3 if closed else 2):
            return
        arr = np.rint(np.asarray(points, dtype=np.float32)).astype(np.int32)
        cv2.polylines(image, [arr], closed, shadow, halo, cv2.LINE_AA)
        cv2.polylines(image, [arr], closed, color, core, cv2.LINE_AA)

    # 刀宽扫掠带: 以刀径像素宽半透明铺底, 中心线照旧 —— 补偿后刀刃贴轮廓内侧可直接目视核对
    swath_px = float(preview.get("cutter_width_px") or 0.0)
    scrape_pts = preview.get("scrape_px")
    if swath_px >= 1.0 and scrape_pts and len(scrape_pts) >= 2:
        arr = np.rint(np.asarray(scrape_pts, dtype=np.float32)).astype(np.int32)
        overlay = image.copy()
        cv2.polylines(overlay, [arr], False, cutter_cyan, max(1, int(round(swath_px))), cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.35, image, 0.65, 0.0, image)

    _polyline(preview.get("contour_px"), contour_orange, closed=True)
    _polyline(preview.get("scrape_px"), cutter_cyan)
    _polyline(preview.get("collect_px"), collector_purple)

    bbox = preview.get("plate_bbox_px")
    size = preview.get("plate_size_cm")
    if bbox is not None and size:
        try:
            draw_plate_frame_annotation(image, bbox, float(size))
        except Exception:  # noqa: BLE001 标注失败不挡叠加主体(旧 payload 无板参照即静默跳过)
            pass

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(output_path), image, [cv2.IMWRITE_PNG_COMPRESSION, 2]))


def default_backdrop(summary_path: Path | str) -> Path | None:
    case_dir = Path(summary_path).parent
    for name in ("after_normalized.jpg", "after.jpg"):
        candidate = case_dir / name
        if candidate.is_file():
            return candidate
    return None

