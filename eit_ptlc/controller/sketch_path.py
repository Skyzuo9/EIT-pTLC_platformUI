"""手绘刮取路径 — 视觉失败兜底/显式手绘的路径来源层。

设计立场（见 memory[ptlc-photoscrape-path-source]）：
  拍照刮板这一步消费的是一个"刮取路径产物"(summary 形状: bbox_cm + contour_cm)。
  视觉是产生它的一种来源; 手绘是另一种**同契约**来源。因此本模块只做一件事:
  把用户在板照片上画的**闭合区域轮廓**(像素) 变成 contour_cm, 落成一个最小 summary.json
  + <band>_path.json, 交给**未改动的** cnc_path.generate_scrape_arrays 生成真机 6 变量。

  下游(400 点刮取 / 收集拖尾 / per-pass Z / write_cnc_path / scrape 循环) 一行不改 ——
  手绘与视觉产出的 band 对 cnc_path 完全同形。

坐标链(与 vision_controller 的 cm_to_px 严格对齐, 保证手绘叠加与视觉 band 同一像素系):
  像素(px) ──仿射/透视逆── 板坐标(cm) ──cnc_path._to_machine── 机床(mm)
  - 有 plate_bbox_px(视觉找到板, 如 no_bands 分支): 轴对齐仿射 + Y 翻转, 与 vision 同式。
  - 无 plate_bbox_px(视觉连板都没框住): 用户点 4 个板角 → 透视单应(DLT, 纯 numpy)。
  预览叠加走反向 machine(mm)→px, 展示的即真机将跑的路径(含 origin_corner 翻转), 所见即所跑。

退化/健壮:
  - 轮廓退化(点少 / 自相接): cnc_path 的扫描线对任意多边形(≥3 点)鲁棒; 这里只保证闭合 + 去重相邻点。
  - plate_size_cm 单标量(方板假设, 与 vision 同), 双轴同尺度以贴合视觉映射, 不擅自各向异性。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Sequence

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller.cnc_path import _flip_from_corner  # noqa: F401 — 复用 origin_corner→(flip_x,flip_y); 供测试 sp._flip_from_corner
from eit_ptlc.controller.plate_coords import (  # noqa: F401 — 公共 API 兼容再导出(单一真源见 plate_coords)
    cm_to_px,
    cm_to_px_affine,
    cm_to_px_corners,
    machine_mm_to_cm,
    machine_mm_to_px,
    plate_bbox_xywh as _plate_bbox_xywh,
    px_to_cm_affine,
    px_to_cm_corners,
)

log = logging.getLogger(__name__)

# 手绘 band 固定 id(单区域); 与 cnc_path 的 band 选择契约对齐。
MANUAL_BAND_ID = "manual_01"
Point = tuple[float, float]


# ---------------------------------------------------------------------------
# 多边形清理 + contour_cm
# ---------------------------------------------------------------------------

def _clean_closed(pts: Sequence[Point], *, eps: float = 1e-6) -> list[Point]:
    """去相邻重复点; 不强制显式闭合(扫描线按 (i,(i+1)%n) 环绕自然闭合)。"""
    cleaned: list[Point] = []
    for p in pts:
        if not cleaned or abs(p[0] - cleaned[-1][0]) > eps or abs(p[1] - cleaned[-1][1]) > eps:
            cleaned.append((float(p[0]), float(p[1])))
    # 若首尾显式重合(用户闭合了曲线), 去掉冗余尾点
    if len(cleaned) >= 2 and abs(cleaned[0][0] - cleaned[-1][0]) <= eps and abs(cleaned[0][1] - cleaned[-1][1]) <= eps:
        cleaned.pop()
    return cleaned


def polygon_to_contour_cm(
    polygon_px: Sequence[Point],
    *,
    plate_size_cm: float,
    plate_bbox_px: Any = None,
    plate_corners_px: Sequence[Point] | None = None,
) -> list[Point]:
    """用户手绘闭合区域(像素) → contour_cm。

    plate_bbox_px 优先(轴对齐, 视觉找到板); 否则用 plate_corners_px(透视, 手动标板)。
    两者皆无 → ValueError(无法建立像素→cm 映射)。
    """
    poly = _clean_closed(polygon_px)
    if len(poly) < 3:
        raise ValueError(f"手绘轮廓至少需 3 个不同点(三角形), 得到 {len(poly)}")
    if plate_bbox_px is not None:
        return px_to_cm_affine(poly, plate_bbox_px, plate_size_cm)
    if plate_corners_px is not None:
        return px_to_cm_corners(poly, plate_corners_px, plate_size_cm)
    raise ValueError("缺少 plate_bbox_px 与 plate_corners_px, 无法把手绘像素映射到板 cm")


# ---------------------------------------------------------------------------
# 最小 summary.json + <band>_path.json(cnc_path 契约)
# ---------------------------------------------------------------------------

def _bbox_of(contour_cm: Sequence[Point]) -> dict[str, float]:
    xs = [p[0] for p in contour_cm]
    ys = [p[1] for p in contour_cm]
    return {"x_min": min(xs), "y_min": min(ys), "x_max": max(xs), "y_max": max(ys)}


def write_manual_summary(
    contour_cm: Sequence[Point],
    workspace_dir: Path,
    *,
    band_id: str = MANUAL_BAND_ID,
    plate_bbox_px: Any = None,
    normalize_applied: dict | None = None,
    manual_rectify: dict | None = None,
) -> Path:
    """落一个最小 summary.json + <band>_path.json, 返回 summary_path。

    path_json 写成同目录裸文件名 → cnc_path._patch_summary_paths 会把它解析回本目录绝对路径,
    再由 _load_band_geometry 读 scrape_path.bbox_cm + contour_cm(与视觉 path_json 同字段)。
    """
    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    path_json_name = f"{band_id}_path.json"

    path_doc = {
        "scrape_path": {"bbox_cm": _bbox_of(contour_cm)},
        "contour_cm": [{"x_cm": round(x, 4), "y_cm": round(y, 4)} for x, y in contour_cm],
    }
    (workspace_dir / path_json_name).write_text(
        json.dumps(path_doc, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    summary_doc: dict[str, Any] = {
        "ok": True,
        "source": "manual_sketch",
        "bands": [{"band_id": band_id, "is_origin": False, "path_json": path_json_name}],
    }
    if plate_bbox_px is not None:
        summary_doc["plate_bbox_px"] = plate_bbox_px
    # C-1: 手绘 summary 继承源(视觉)summary 的实际归一化参数; 刮后照片据此确定性回放同帧。
    if normalize_applied is not None:
        summary_doc["normalize_applied"] = normalize_applied
    # C-2: 4 角标板矫正记录(plate_corners_px/px_per_cm/frame_size); 给了才写, 供刮后二级回放。
    if manual_rectify is not None:
        summary_doc["manual_rectify"] = manual_rectify
    summary_path = workspace_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary_doc, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return summary_path


def read_plate_bbox(summary_path: Path | str) -> tuple[Any | None, float]:
    """从(视觉)summary.json 读 plate_bbox_px 与 plate_size_cm。

    plate_bbox_px 缺失(视觉连板都没框住) → (None, size): 调用方据此走 4 角手动标板。
    """
    try:
        data = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None, 20.0
    plate_bbox = data.get("plate_bbox_px")
    plate_size = float(data.get("plate_size_cm", 20.0) or 20.0)
    return plate_bbox, plate_size


# ---------------------------------------------------------------------------
# 4 角标板矫正帧 (spec §6, 契约 C-2): 点序校验 + warpPerspective 出正方形主路径帧。
# 端点失败时前端回落上面的 4 角单应老路 — 老路不删。
# ---------------------------------------------------------------------------

def validate_manual_corners(corners_px: Any) -> list[Point]:
    """校验 4 角点序 [左上,右上,右下,左下]: 数量/数对/方位/凸性; 不符 ValueError(中文原因)。

    后端准绳: 前端有同规则即时提示, 但以这里为最终校验(双重校验, 不信任客户端)。
    """
    if not isinstance(corners_px, (list, tuple)) or len(corners_px) != 4:
        raise ValueError("需恰好 4 个角点 [左上,右上,右下,左下]")
    pts: list[Point] = []
    for p in corners_px:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise ValueError(f"角点须为 [x,y] 数对, 得到 {p!r}")
        pts.append((float(p[0]), float(p[1])))
    (tlx, tly), (trx, tr_y), (brx, bry), (blx, bly) = pts
    if not (tlx < trx and blx < brx):
        raise ValueError("左右颠倒: 请按 左上→右上→右下→左下 顺序点四角")
    if not (tly < bly and tr_y < bry):
        raise ValueError("上下颠倒: 请按 左上→右上→右下→左下 顺序点四角")
    sign = 0.0
    for i in range(4):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % 4]
        cx, cy = pts[(i + 2) % 4]
        z = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if z == 0:
            raise ValueError("角点共线/重合, 无法构成板框")
        if sign == 0.0:
            sign = z
        elif (z > 0) != (sign > 0):
            raise ValueError("四点不构成凸四边形, 请检查点位或顺序")
    return pts


def rectify_manual_frame(
    backdrop_path: Path | str,
    corners_px: Any,
    plate_size_cm: float,
    case_dir: Path | str,
    *,
    px_per_cm: int = 40,
) -> dict[str, Any]:
    """4 角单应 → 正方形矫正帧 manual_normalized.jpg(用户看到"程序认为的板")。

    返回含 C-2 形状的 manual_rectify 记录 — 提交时随 manual summary 落盘,
    供刮后 replay_normalization 二级回放。cv2 缺失 → RuntimeError(路由 503, 前端回落老路)。
    """
    try:
        import cv2  # type: ignore
        import numpy as _np  # type: ignore
    except ImportError as exc:
        raise RuntimeError(f"cv2 缺失, 无法生成矫正帧: {exc}") from exc
    pts = validate_manual_corners(corners_px)
    img = cv2.imread(str(backdrop_path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"底图不可读: {backdrop_path}")
    side = int(round(float(plate_size_cm) * px_per_cm))
    if side <= 0:
        raise ValueError(f"plate_size_cm/px_per_cm 无效: {plate_size_cm}/{px_per_cm}")
    src = _np.float32(pts)
    dst = _np.float32([[0, 0], [side, 0], [side, side], [0, side]])
    warped = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (side, side))
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    out = case_dir / "manual_normalized.jpg"
    if not cv2.imwrite(str(out), warped):
        raise ValueError(f"矫正帧写盘失败: {out}")
    return {
        "image_path": str(out),
        "plate_bbox_px": {"x": 0, "y": 0, "w": side, "h": side},
        "px_per_cm": px_per_cm,
        "manual_rectify": {
            "plate_corners_px": [[x, y] for x, y in pts],
            "px_per_cm": px_per_cm,
            "frame_size": [side, side],
        },
    }


# ---------------------------------------------------------------------------
# 高层: 预览(不落盘) / 提交(落盘 + 叠加图), 供 photoscrape_routes 调用
# ---------------------------------------------------------------------------

def _arrays_from_contour_cm(contour_cm, gcode_cfg, *, plate_bbox_px=None, strategy=None):
    """把 contour_cm 走一遍**未改动的** generate_scrape_arrays(临时 summary, 用后即删)。"""
    import tempfile

    from eit_ptlc.controller.cnc_path import generate_scrape_arrays
    with tempfile.TemporaryDirectory() as td:
        sp_path = write_manual_summary(contour_cm, Path(td), plate_bbox_px=plate_bbox_px)
        return generate_scrape_arrays(sp_path, MANUAL_BAND_ID, gcode_cfg, strategy=strategy)


def preview_from_polygon(
    polygon_px: Sequence[Point],
    gcode_cfg: GCodeCfg,
    *,
    plate_size_cm: float,
    plate_bbox_px: Any = None,
    plate_corners_px: Sequence[Point] | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """手绘多边形 → 真机路径预览(像素)。所见即所跑: 走同一 generate_scrape_arrays 再逆回 px。"""
    contour_cm = polygon_to_contour_cm(
        polygon_px, plate_size_cm=plate_size_cm,
        plate_bbox_px=plate_bbox_px, plate_corners_px=plate_corners_px,
    )
    arrays = _arrays_from_contour_cm(contour_cm, gcode_cfg, plate_bbox_px=plate_bbox_px, strategy=strategy)
    scrape_px = machine_mm_to_px(
        list(zip(arrays.g_sx, arrays.g_sy)), gcode_cfg,
        plate_bbox_px, plate_size_cm, plate_corners_px=plate_corners_px,
    )
    collect_px = machine_mm_to_px(
        list(zip(arrays.g_cx, arrays.g_cy)), gcode_cfg,
        plate_bbox_px, plate_size_cm, plate_corners_px=plate_corners_px,
    )
    contour_px = cm_to_px(
        contour_cm, plate_size_cm=plate_size_cm,
        plate_bbox_px=plate_bbox_px, plate_corners_px=plate_corners_px,
    )
    return {
        "scrape_px": [[round(x, 1), round(y, 1)] for x, y in scrape_px],
        "collect_px": [[round(x, 1), round(y, 1)] for x, y in collect_px],
        "contour_px": [[round(x, 1), round(y, 1)] for x, y in contour_px],
        "pass_count": int(arrays.pass_count),
        "point_count": len(arrays.g_sx),
        "feed": int(arrays.g_scrape_feed),
    }


def render_sketch_overlay(
    after_path: Path | str,
    contour_px: Sequence[Point],
    scrape_px: Sequence[Point],
    out_path: Path,
) -> bool:
    """在板照片上叠加手绘区域轮廓(品红)+ 生成刮取路径(青), 存 out_path。cv2 缺失/图缺失 → False。"""
    try:
        import cv2  # type: ignore
        import numpy as _np  # type: ignore
    except ImportError:
        return False
    img = cv2.imread(str(after_path), cv2.IMREAD_COLOR)
    if img is None:
        return False
    CONTOUR_MAGENTA = (54, 132, 255)
    PATH_CYAN = (236, 216, 0)
    SHADOW = (7, 7, 10)
    if scrape_px:
        pp = _np.rint(_np.array(scrape_px, dtype=_np.float32)).astype(_np.int32)
        cv2.polylines(img, [pp], False, SHADOW, 4, cv2.LINE_AA)
        cv2.polylines(img, [pp], False, PATH_CYAN, 2, cv2.LINE_AA)
    if contour_px and len(contour_px) >= 3:
        cp = _np.rint(_np.array(contour_px, dtype=_np.float32)).astype(_np.int32)
        cv2.polylines(img, [cp], True, SHADOW, 4, cv2.LINE_AA)
        cv2.polylines(img, [cp], True, CONTOUR_MAGENTA, 2, cv2.LINE_AA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), img, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    return True


def commit_sketch(
    polygon_px: Sequence[Point],
    gcode_cfg: GCodeCfg,
    output_dir: Path,
    *,
    plate_size_cm: float,
    plate_bbox_px: Any = None,
    plate_corners_px: Sequence[Point] | None = None,
    after_path: Path | str | None = None,
    sample_id: str = "manual",
    strategy: str | None = None,
    source_summary_path: str | None = None,
    manual_rectify: dict | None = None,
) -> dict[str, Any]:
    """提交手绘: 落最小 summary(供 cnc_path) + 叠加图(供门预览), 返回 analyze_action 同形 result。

    返回的 summary_path 由人工回复带回 VM, 交给**未改动的** cnc_path 动作; 与视觉候选完全同形。
    """
    output_dir = Path(output_dir)
    contour_cm = polygon_to_contour_cm(
        polygon_px, plate_size_cm=plate_size_cm,
        plate_bbox_px=plate_bbox_px, plate_corners_px=plate_corners_px,
    )
    # C-1: 手绘 summary 继承源(视觉)summary 的 normalize_applied, 刮后回放两级链路第一级。
    normalize_applied = None
    if source_summary_path:
        try:
            normalize_applied = json.loads(
                Path(source_summary_path).read_text(encoding="utf-8")
            ).get("normalize_applied")
        except (OSError, ValueError, TypeError):
            normalize_applied = None  # 旧 summary 无此字段: 对账叠加将 fail-safe 跳过
    workspace = output_dir / f"{sample_id}_manual"
    summary_path = write_manual_summary(
        contour_cm, workspace, plate_bbox_px=plate_bbox_px,
        normalize_applied=normalize_applied,
        manual_rectify=manual_rectify,
    )

    annotated_url = ""
    if after_path:
        try:
            source_backdrop = Path(after_path)
            normalized_backdrop = workspace / "after_normalized.jpg"
            if source_backdrop.is_file() and source_backdrop.resolve() != normalized_backdrop.resolve():
                normalized_backdrop.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_backdrop, normalized_backdrop)
            arrays = _arrays_from_contour_cm(contour_cm, gcode_cfg, plate_bbox_px=plate_bbox_px, strategy=strategy)
            scrape_px = machine_mm_to_px(
                list(zip(arrays.g_sx, arrays.g_sy)), gcode_cfg,
                plate_bbox_px, plate_size_cm, plate_corners_px=plate_corners_px,
            )
            contour_px = cm_to_px(
                contour_cm, plate_size_cm=plate_size_cm,
                plate_bbox_px=plate_bbox_px, plate_corners_px=plate_corners_px,
            )
            overlay = workspace / "manual_annotated.png"
            if render_sketch_overlay(after_path, contour_px, scrape_px, overlay):
                try:
                    rel = overlay.resolve().relative_to(output_dir.resolve()).as_posix()
                    annotated_url = f"/api/vision/image/{rel}"
                except ValueError:
                    annotated_url = ""
        except Exception as exc:  # noqa: BLE001 叠加图失败不阻断提交(路径已可下发)
            log.warning("[sketch] 叠加图渲染失败(不阻断提交): %s", exc)

    return {
        "ok": True,
        "reason": "ok",
        "message": "",
        "source": "manual_sketch",
        "summary_path": str(summary_path),
        "case_dir": str(workspace),
        "band_ids": [MANUAL_BAND_ID],
        "band_id": MANUAL_BAND_ID,
        "annotated_url": annotated_url,
    }
