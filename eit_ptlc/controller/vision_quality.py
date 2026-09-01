"""Vision quality diagnostics module
===================================
Analyzes photo quality independently of the recognition algorithm.

Computes exposure, positioning, sharpness, and image clarity metrics
from raw images (before/after) to help debug photo station issues.

Pure computation: no file I/O beyond reading/writing images passed as
Path arguments. All image-processing imports are lazy/guarded so the
module is importable even without OpenCV installed.

Usage::

    from pathlib import Path
    from eit_ptlc.controller.vision_quality import (
        analyze_quality, generate_quality_overlay, generate_quality_report,
    )
    metrics = analyze_quality(Path("before.jpg"))
    overlay_path = generate_quality_overlay(
        Path("before.jpg"), metrics, Path("debug_overlay.png"),
    )
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from math import atan2, degrees, hypot
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class QualityMetrics:
    """Photo quality metrics for a single image.

    Plate-specific fields (plate_center_offset_mm, plate_rotation_deg,
    perspective_skew_deg, margin_px) are ``None`` when no plate is detected.
    """

    plate_center_offset_mm: tuple[float, float] | None = None
    plate_rotation_deg: float | None = None
    perspective_skew_deg: float | None = None
    margin_px: dict[str, int] | None = None
    plate_center_px: tuple[float, float] | None = None
    plate_corners_px: list[dict[str, float]] | None = None
    mean_brightness: float = 0.0
    overexposed_ratio: float = 0.0
    underexposed_ratio: float = 0.0
    sharpness: float = 0.0
    image_width: int = 0
    image_height: int = 0

    # ------------------------------------------------------------------
    # reserved for future use (populated when plate_bbox_px is available)
    # ------------------------------------------------------------------
    plate_bbox_px: dict[str, int] | None = field(default=None, repr=False)
    quality_region: str = "full_image"
    global_mean_brightness: float = 0.0
    global_overexposed_ratio: float = 0.0
    global_underexposed_ratio: float = 0.0
    global_sharpness: float = 0.0
    global_mean_saturation: float = 0.0
    global_mean_hue: float = 0.0
    mean_saturation: float = 0.0
    mean_hue: float = 0.0


# ---------------------------------------------------------------------------
# Lazy / guarded imports
# ---------------------------------------------------------------------------

_CV2_AVAILABLE: bool | None = None
_NP_AVAILABLE: bool | None = None
_PIL_AVAILABLE: bool | None = None


def _has_cv2() -> bool:
    global _CV2_AVAILABLE
    if _CV2_AVAILABLE is None:
        try:
            import cv2  # noqa: F401
            _CV2_AVAILABLE = True
        except ImportError:
            log.warning("cv2 (OpenCV) not available – falling back to PIL")
            _CV2_AVAILABLE = False
    return _CV2_AVAILABLE


def _has_np() -> bool:
    global _NP_AVAILABLE
    if _NP_AVAILABLE is None:
        try:
            import numpy  # noqa: F401
            _NP_AVAILABLE = True
        except ImportError:
            _NP_AVAILABLE = False
    return _NP_AVAILABLE


def _has_pil() -> bool:
    global _PIL_AVAILABLE
    if _PIL_AVAILABLE is None:
        try:
            from PIL import Image  # noqa: F401
            _PIL_AVAILABLE = True
        except ImportError:
            _PIL_AVAILABLE = False
    return _PIL_AVAILABLE


# ---------------------------------------------------------------------------
# Shared plate detection helpers
# ---------------------------------------------------------------------------


def _ensure_tlc_analyze() -> Any:
    """Load the production TLC analysis module for shared plate detection."""
    view_dir = Path(__file__).resolve().parents[2] / "View" / "pTLC_Viewing"
    view_dir_str = str(view_dir)
    if view_dir_str not in sys.path:
        sys.path.insert(0, view_dir_str)
    try:
        import tlc_analyze  # type: ignore  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(f"Unable to import tlc_analyze from {view_dir}: {exc}") from exc
    return tlc_analyze


def _order_corners(points: Any) -> Any:
    """Return corners ordered TL, TR, BR, BL."""
    import numpy as np

    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    ordered[0] = pts[int(np.argmin(s))]
    ordered[2] = pts[int(np.argmax(s))]
    ordered[1] = pts[int(np.argmin(diff))]
    ordered[3] = pts[int(np.argmax(diff))]
    return ordered


def _corners_to_payload(corners: Any) -> list[dict[str, float]]:
    return [
        {"x": round(float(x), 3), "y": round(float(y), 3)}
        for x, y in corners
    ]


def _rotation_from_corners(corners: Any) -> float:
    tl, tr = corners[0], corners[1]
    angle = degrees(atan2(float(tr[1] - tl[1]), float(tr[0] - tl[0])))
    while angle <= -90.0:
        angle += 180.0
    while angle > 90.0:
        angle -= 180.0
    return float(angle)


def _perspective_skew_from_corners(corners: Any) -> float:
    import numpy as np

    max_deviation = 0.0
    for i in range(4):
        prev_pt = corners[(i - 1) % 4]
        pt = corners[i]
        next_pt = corners[(i + 1) % 4]
        v1 = prev_pt - pt
        v2 = next_pt - pt
        norm = np.linalg.norm(v1) * np.linalg.norm(v2)
        if norm < 1e-9:
            continue
        cos_angle = np.clip(float(np.dot(v1, v2) / norm), -1.0, 1.0)
        angle_deg = float(degrees(np.arccos(cos_angle)))
        max_deviation = max(max_deviation, abs(angle_deg - 90.0))
    return max_deviation if max_deviation > 1.0 else 0.0


def _bbox_from_corners(corners: Any, image_w: int, image_h: int) -> dict[str, int]:
    import numpy as np

    xs = corners[:, 0]
    ys = corners[:, 1]
    x0 = max(0, int(np.floor(xs.min())))
    y0 = max(0, int(np.floor(ys.min())))
    x1 = min(image_w, int(np.ceil(xs.max())))
    y1 = min(image_h, int(np.ceil(ys.max())))
    return {"x": x0, "y": y0, "w": max(0, x1 - x0), "h": max(0, y1 - y0)}


def _geometry_from_bbox(bbox: dict[str, int]) -> dict[str, Any]:
    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    corners = [
        {"x": float(x), "y": float(y)},
        {"x": float(x + w), "y": float(y)},
        {"x": float(x + w), "y": float(y + h)},
        {"x": float(x), "y": float(y + h)},
    ]
    return {
        "bbox": bbox,
        "corners": corners,
        "rotation_deg": 0.0,
        "perspective_skew_deg": 0.0,
    }


def _detect_green_plate_geometry_cv(
    bgr: Any,
    image_w: int,
    image_h: int,
    plate_size_cm: float,
) -> dict[str, Any] | None:
    """Detect the TLC plate using the same green-mask basis as tlc_analyze."""
    import cv2
    import numpy as np

    try:
        tlc_analyze = _ensure_tlc_analyze()
        plate = tlc_analyze.detect_plate(bgr, plate_size_cm)
        bbox = {"x": int(plate.x), "y": int(plate.y), "w": int(plate.w), "h": int(plate.h)}
        _, green_mask = tlc_analyze.green_plate_mask(bgr)
    except Exception as exc:
        log.debug("Production green plate detection failed: %s", exc)
        return None

    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return _geometry_from_bbox(bbox)
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.05 * image_w * image_h:
        return _geometry_from_bbox(bbox)

    rect = cv2.minAreaRect(largest)
    corners = _order_corners(cv2.boxPoints(rect))
    # Keep the production axis-aligned bbox, but expose corners from the same
    # green contour so operators can see rotation/perspective evidence.
    corner_bbox = _bbox_from_corners(corners, image_w, image_h)
    if corner_bbox["w"] >= 20 and corner_bbox["h"] >= 20:
        bbox = {
            "x": max(0, bbox["x"]),
            "y": max(0, bbox["y"]),
            "w": min(image_w - max(0, bbox["x"]), bbox["w"]),
            "h": min(image_h - max(0, bbox["y"]), bbox["h"]),
        }

    return {
        "bbox": bbox,
        "corners": _corners_to_payload(corners),
        "rotation_deg": _rotation_from_corners(corners),
        "perspective_skew_deg": _perspective_skew_from_corners(corners),
    }


def _detect_plate_bbox_cv(
    gray: Any,  # numpy ndarray (uint8, H x W)
    image_w: int,
    image_h: int,
) -> dict[str, int] | None:
    """Detect the largest dark quadrilateral on a light background.

    Returns ``{x, y, w, h}`` in pixels, or ``None`` if no plausible plate
    is found.  Designed for TLC plates photographed on a white/light stage.
    """
    import cv2
    import numpy as np

    # Binary threshold: assume plate is darker than background.
    # Otsu picks a split point automatically.
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Morphological close to merge nearby dark regions
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Pick the largest contour by area
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    img_area = image_w * image_h

    # Reject contours that are too small (< 5 % of image) or too large (> 95 %)
    if area < 0.05 * img_area or area > 0.95 * img_area:
        log.debug("Plate detection: contour area %.0f px outside plausible range", area)
        return None

    x, y, w, h = cv2.boundingRect(largest)
    # Reject degenerate boxes
    if w < 20 or h < 20:
        return None

    return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}


# ---------------------------------------------------------------------------
# Metrics computation helpers
# ---------------------------------------------------------------------------


def _compute_sharpness_cv(gray: Any) -> float:
    """Laplacian variance – higher means sharper."""
    import cv2

    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


def _compute_brightness_stats(
    gray: Any,
) -> tuple[float, float, float]:
    """Return (mean_brightness, overexposed_ratio, underexposed_ratio)."""
    import numpy as np

    total = gray.size
    mean = float(np.mean(gray))
    over = float(np.count_nonzero(gray >= 254)) / total
    under = float(np.count_nonzero(gray <= 1)) / total
    return mean, over, under


def _clip_bbox(bbox: dict[str, int], image_w: int, image_h: int) -> dict[str, int] | None:
    x = max(0, int(bbox["x"]))
    y = max(0, int(bbox["y"]))
    right = min(image_w, int(bbox["x"]) + int(bbox["w"]))
    bottom = min(image_h, int(bbox["y"]) + int(bbox["h"]))
    if right <= x or bottom <= y:
        return None
    return {"x": x, "y": y, "w": right - x, "h": bottom - y}


def _compute_saturation_hue(bgr: Any) -> tuple[float, float]:
    """Return (mean_saturation, mean_hue) from BGR image."""
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = float(np.mean(hsv[:, :, 1]))
    hue = float(np.mean(hsv[:, :, 0]))
    return sat, hue


def _compute_plate_rotation_cv(gray: Any, bbox: dict[str, int]) -> float | None:
    """Fit a rotated rectangle to the plate contour and return its angle in degrees."""
    import cv2
    import numpy as np

    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    roi = gray[y : y + h, x : x + w]

    _, thresh = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    if len(largest) < 5:
        return None

    rect = cv2.minAreaRect(largest)
    angle = rect[2]
    # Normalize: minAreaRect returns angle in [-90, 0); we want degrees
    # away from horizontal, so take the smaller absolute value.
    if angle < -45:
        angle = 90 + angle  # e.g. -88 -> 2
    return float(abs(angle))


def _compute_perspective_skew_cv(bbox: dict[str, int], gray: Any) -> float | None:
    """Estimate perspective skew by measuring corner angles of the plate outline.

    Returns the maximum deviation of any interior corner from 90 degrees.
    """
    import cv2
    import numpy as np

    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    roi = gray[y : y + h, x : x + w]

    _, thresh = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    # Approximate contour to a quadrilateral
    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * peri, True)

    if len(approx) != 4:
        # Not a clean quadrilateral – try convex hull
        hull = cv2.convexHull(largest)
        if len(hull) < 4:
            return None
        # Simplify hull to 4 points
        peri = cv2.arcLength(hull, True)
        approx = cv2.approxPolyDP(hull, 0.02 * peri, True)
        if len(approx) != 4:
            return None

    pts = approx.reshape(4, 2).astype(np.float32)

    # Compute interior angles from the four vertices
    max_deviation = 0.0
    for i in range(4):
        p0 = pts[i]
        p1 = pts[(i + 1) % 4]
        p2 = pts[(i + 2) % 4]
        v1 = p0 - p1
        v2 = p2 - p1
        dot = np.dot(v1, v2)
        norm = np.linalg.norm(v1) * np.linalg.norm(v2)
        if norm < 1e-9:
            continue
        cos_angle = np.clip(dot / norm, -1.0, 1.0)
        angle_rad = np.arccos(cos_angle)
        angle_deg = float(degrees(angle_rad))
        deviation = abs(angle_deg - 90.0)
        if deviation > max_deviation:
            max_deviation = deviation

    return max_deviation if max_deviation > 1.0 else 0.0


def _compute_margins(bbox: dict[str, int], image_w: int, image_h: int) -> dict[str, int]:
    """Distance from plate edges to image edges (pixels)."""
    return {
        "top": bbox["y"],
        "bottom": image_h - (bbox["y"] + bbox["h"]),
        "left": bbox["x"],
        "right": image_w - (bbox["x"] + bbox["w"]),
    }


def _compute_center_offset_mm(
    bbox: dict[str, int],
    image_w: int,
    image_h: int,
    plate_size_cm: float = 20.0,
) -> tuple[float, float]:
    """Compute plate center offset from image center, in mm.

    Assumes the plate is *plate_size_cm* wide.  Uses the bounding-box width
    as the pixel reference for the plate dimension to convert px -> mm.
    """
    plate_cx_px = bbox["x"] + bbox["w"] / 2.0
    plate_cy_px = bbox["y"] + bbox["h"] / 2.0
    img_cx = image_w / 2.0
    img_cy = image_h / 2.0

    # Scale: plate_size_cm (cm) per bbox width (px) -> mm per px
    if bbox["w"] <= 0:
        return (0.0, 0.0)
    mm_per_px = (plate_size_cm * 10.0) / bbox["w"]
    dx_mm = (plate_cx_px - img_cx) * mm_per_px
    dy_mm = (plate_cy_px - img_cy) * mm_per_px
    return (round(dx_mm, 3), round(dy_mm, 3))


# ---------------------------------------------------------------------------
# PIL fallback for basic metrics
# ---------------------------------------------------------------------------


def _compute_brightness_stats_pil(img: Any) -> tuple[float, float, float]:
    """PIL fallback: compute brightness stats from a PIL Image."""
    import numpy as np

    gray = np.array(img.convert("L"))
    return _compute_brightness_stats(gray)


def _compute_sharpness_pil(img: Any) -> float:
    """PIL fallback: approximate sharpness via gradient magnitude."""
    import numpy as np
    from PIL import ImageFilter

    gray = np.array(img.convert("L"), dtype=np.float64)
    # Simple gradient-based sharpness: variance of edge-detected image
    edges = np.array(img.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float64)
    return float(edges.var())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_quality(
    image_path: Path,
    plate_bbox_px: dict[str, int] | None = None,
    *,
    plate_size_cm: float = 20.0,
) -> QualityMetrics:
    """Analyze photo quality for a single image.

    Parameters
    ----------
    image_path:
        Path to the image file (JPEG / PNG).  Must exist and be readable.
    plate_bbox_px:
        Optional pre-computed bounding box of the plate in pixels
        (``{"x", "y", "w", "h"}``).  When provided (e.g. from a recognition
        summary.json), plate-specific metrics use this box directly.
        When ``None``, the function attempts to auto-detect the plate via
        contour finding (largest dark rectangle on light background).
    plate_size_cm:
        Nominal plate width in cm, used to convert pixel offsets to mm.
        Default 20.0 (standard TLC plate).

    Returns
    -------
    QualityMetrics
        All fields populated; plate-specific fields are ``None`` when no
        plate can be detected.
    """
    image_path = Path(image_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    metrics = QualityMetrics()

    # --- Try OpenCV path first ---
    if _has_cv2() and _has_np():
        try:
            return _analyze_quality_cv(image_path, plate_bbox_px, plate_size_cm)
        except Exception as exc:
            log.warning("OpenCV analysis failed (%s), falling back to PIL", exc)

    # --- PIL fallback (basic metrics only) ---
    if _has_pil() and _has_np():
        try:
            return _analyze_quality_pil(image_path, plate_bbox_px, plate_size_cm)
        except Exception as exc:
            log.error("PIL analysis also failed: %s", exc)
            raise

    # --- No imaging library available ---
    log.error("No imaging library available (cv2/PIL); returning empty metrics")
    return metrics


def _analyze_quality_cv(
    image_path: Path,
    plate_bbox_px: dict[str, int] | None,
    plate_size_cm: float,
) -> QualityMetrics:
    """OpenCV-backed quality analysis."""
    import cv2

    bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Unable to read image: {image_path}")

    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # --- Full-image metrics are always retained for comparison ---
    global_mean_brightness, global_overexposed, global_underexposed = _compute_brightness_stats(gray)
    global_sharpness = _compute_sharpness_cv(gray)
    global_mean_sat, global_mean_hue = _compute_saturation_hue(bgr)

    metrics = QualityMetrics(
        mean_brightness=round(global_mean_brightness, 3),
        overexposed_ratio=round(global_overexposed, 6),
        underexposed_ratio=round(global_underexposed, 6),
        sharpness=round(global_sharpness, 3),
        image_width=w,
        image_height=h,
        mean_saturation=round(global_mean_sat, 3),
        mean_hue=round(global_mean_hue, 3),
        global_mean_brightness=round(global_mean_brightness, 3),
        global_overexposed_ratio=round(global_overexposed, 6),
        global_underexposed_ratio=round(global_underexposed, 6),
        global_sharpness=round(global_sharpness, 3),
        global_mean_saturation=round(global_mean_sat, 3),
        global_mean_hue=round(global_mean_hue, 3),
    )

    # --- Plate detection ---
    geometry = None
    bbox = _clip_bbox(plate_bbox_px, w, h) if plate_bbox_px is not None else None
    if bbox is None:
        geometry = _detect_green_plate_geometry_cv(bgr, w, h, plate_size_cm)
        if geometry is not None:
            bbox = _clip_bbox(geometry["bbox"], w, h)
    else:
        geometry = _geometry_from_bbox(bbox)
    if bbox is None:
        bbox = _detect_plate_bbox_cv(gray, w, h)
        if bbox is not None:
            geometry = _geometry_from_bbox(bbox)

    if bbox is not None:
        metrics.plate_bbox_px = bbox
        metrics.plate_center_px = (
            round(bbox["x"] + bbox["w"] / 2.0, 3),
            round(bbox["y"] + bbox["h"] / 2.0, 3),
        )
        if geometry is not None:
            metrics.plate_corners_px = geometry.get("corners")
            metrics.plate_rotation_deg = round(float(geometry.get("rotation_deg", 0.0)), 3)
            metrics.perspective_skew_deg = round(float(geometry.get("perspective_skew_deg", 0.0)), 3)
        else:
            metrics.plate_rotation_deg = _compute_plate_rotation_cv(gray, bbox)
            if metrics.plate_rotation_deg is not None:
                metrics.plate_rotation_deg = round(metrics.plate_rotation_deg, 3)
            metrics.perspective_skew_deg = _compute_perspective_skew_cv(bbox, gray)
            if metrics.perspective_skew_deg is not None:
                metrics.perspective_skew_deg = round(metrics.perspective_skew_deg, 3)
        metrics.margin_px = _compute_margins(bbox, w, h)
        metrics.plate_center_offset_mm = _compute_center_offset_mm(
            bbox, w, h, plate_size_cm,
        )
        roi_gray = gray[bbox["y"] : bbox["y"] + bbox["h"], bbox["x"] : bbox["x"] + bbox["w"]]
        roi_bgr = bgr[bbox["y"] : bbox["y"] + bbox["h"], bbox["x"] : bbox["x"] + bbox["w"]]
        if roi_gray.size and roi_bgr.size:
            mean_brightness, overexposed, underexposed = _compute_brightness_stats(roi_gray)
            sharpness = _compute_sharpness_cv(roi_gray)
            mean_sat, mean_hue = _compute_saturation_hue(roi_bgr)
            metrics.quality_region = "plate_roi"
            metrics.mean_brightness = round(mean_brightness, 3)
            metrics.overexposed_ratio = round(overexposed, 6)
            metrics.underexposed_ratio = round(underexposed, 6)
            metrics.sharpness = round(sharpness, 3)
            metrics.mean_saturation = round(mean_sat, 3)
            metrics.mean_hue = round(mean_hue, 3)

    return metrics


def _analyze_quality_pil(
    image_path: Path,
    plate_bbox_px: dict[str, int] | None,
    plate_size_cm: float,
) -> QualityMetrics:
    """PIL fallback for basic quality analysis (no plate detection)."""
    from PIL import Image

    img = Image.open(image_path)
    w, h = img.size

    mean_brightness, overexposed, underexposed = _compute_brightness_stats_pil(img)
    sharpness = _compute_sharpness_pil(img)

    metrics = QualityMetrics(
        mean_brightness=round(mean_brightness, 3),
        overexposed_ratio=round(overexposed, 6),
        underexposed_ratio=round(underexposed, 6),
        sharpness=round(sharpness, 3),
        image_width=w,
        image_height=h,
        global_mean_brightness=round(mean_brightness, 3),
        global_overexposed_ratio=round(overexposed, 6),
        global_underexposed_ratio=round(underexposed, 6),
        global_sharpness=round(sharpness, 3),
    )

    # Plate-specific: if bbox was provided we can still compute some metrics
    if plate_bbox_px is not None:
        bbox = _clip_bbox(plate_bbox_px, w, h)
        if bbox is None:
            return metrics
        metrics.plate_bbox_px = bbox
        metrics.plate_center_px = (
            round(bbox["x"] + bbox["w"] / 2.0, 3),
            round(bbox["y"] + bbox["h"] / 2.0, 3),
        )
        metrics.plate_corners_px = _geometry_from_bbox(bbox)["corners"]
        metrics.margin_px = _compute_margins(bbox, w, h)
        metrics.plate_center_offset_mm = _compute_center_offset_mm(
            bbox, w, h, plate_size_cm,
        )
        # Rotation / skew are cv2-only
        metrics.plate_rotation_deg = None
        metrics.perspective_skew_deg = None

    return metrics


# ---------------------------------------------------------------------------
# Quality overlay
# ---------------------------------------------------------------------------


def generate_quality_overlay(
    image_path: Path,
    metrics: QualityMetrics,
    output_path: Path,
    plate_bbox_px: dict[str, int] | None = None,
) -> Path:
    """Generate a diagnostic overlay PNG saved to *output_path*.

    The overlay includes:
    - Plate bounding box (green)
    - Center crosshair (red)
    - Rotation angle annotation
    - Margin lines
    - Brightness histogram inset
    - Sharpness value annotation

    Parameters
    ----------
    image_path:
        Source image to annotate.
    metrics:
        Pre-computed QualityMetrics (from :func:`analyze_quality`).
    output_path:
        Destination path for the overlay PNG.
    plate_bbox_px:
        Optional override for the plate bounding box.  Falls back to
        ``metrics.plate_bbox_px``.

    Returns
    -------
    Path
        *output_path* (for chaining).
    """
    image_path = Path(image_path)
    output_path = Path(output_path)

    if not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    bbox = plate_bbox_px or (metrics.plate_bbox_px if metrics.plate_bbox_px else None)

    # --- OpenCV path ---
    if _has_cv2() and _has_np():
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _generate_overlay_cv(image_path, metrics, output_path, bbox)
            return output_path
        except Exception as exc:
            log.warning("OpenCV overlay failed (%s), falling back to PIL", exc)

    # --- PIL fallback ---
    if _has_pil():
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _generate_overlay_pil(image_path, metrics, output_path, bbox)
            return output_path
        except Exception as exc:
            log.error("PIL overlay also failed: %s", exc)
            raise

    raise RuntimeError("No imaging library available for overlay generation")


def _generate_overlay_cv(
    image_path: Path,
    metrics: QualityMetrics,
    output_path: Path,
    bbox: dict[str, int] | None,
) -> None:
    """OpenCV-based overlay rendering."""
    import cv2
    import numpy as np

    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Unable to read image: {image_path}")

    h, w = img.shape[:2]

    # Colors (BGR)
    GREEN = (0, 220, 0)
    RED = (0, 0, 220)
    CYAN = (220, 220, 0)
    YELLOW = (0, 220, 220)
    WHITE = (240, 240, 240)
    BLACK = (10, 10, 10)

    # --- Plate bounding box (green) ---
    # Image center crosshair (white) helps judge mechanical centering.
    img_cx = w // 2
    img_cy = h // 2
    cv2.line(img, (img_cx - 18, img_cy), (img_cx + 18, img_cy), WHITE, 1, cv2.LINE_AA)
    cv2.line(img, (img_cx, img_cy - 18), (img_cx, img_cy + 18), WHITE, 1, cv2.LINE_AA)

    if bbox:
        x, y, bw, bh = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
        cv2.rectangle(img, (x, y), (x + bw, y + bh), GREEN, 2, cv2.LINE_AA)

        if metrics.plate_corners_px:
            corners = np.array(
                [[p["x"], p["y"]] for p in metrics.plate_corners_px],
                dtype=np.int32,
            )
            cv2.polylines(img, [corners], isClosed=True, color=YELLOW, thickness=2, lineType=cv2.LINE_AA)
            for idx, (px, py) in enumerate(corners):
                cv2.circle(img, (int(px), int(py)), 4, YELLOW, -1, cv2.LINE_AA)
                cv2.putText(img, str(idx + 1), (int(px) + 5, int(py) - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, YELLOW, 1, cv2.LINE_AA)

        # Plate center crosshair (red)
        cx = x + bw // 2
        cy = y + bh // 2
        ch_len = 20
        cv2.line(img, (cx - ch_len, cy), (cx + ch_len, cy), RED, 2, cv2.LINE_AA)
        cv2.line(img, (cx, cy - ch_len), (cx, cy + ch_len), RED, 2, cv2.LINE_AA)

        # Margin lines (cyan)
        # Top margin
        cv2.line(img, (0, y), (w, y), CYAN, 1, cv2.LINE_AA)
        # Bottom margin
        cv2.line(img, (0, y + bh), (w, y + bh), CYAN, 1, cv2.LINE_AA)
        # Left margin
        cv2.line(img, (x, 0), (x, h), CYAN, 1, cv2.LINE_AA)
        # Right margin
        cv2.line(img, (x + bw, 0), (x + bw, h), CYAN, 1, cv2.LINE_AA)

        # Rotation annotation
        if metrics.plate_rotation_deg is not None:
            text = f"rot={metrics.plate_rotation_deg:.2f}deg"
            cv2.putText(img, text, (x + 6, y + 20), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, YELLOW, 2, cv2.LINE_AA)

        # Skew annotation
        if metrics.perspective_skew_deg is not None:
            text = f"skew={metrics.perspective_skew_deg:.2f}deg"
            cv2.putText(img, text, (x + 6, y + 42), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, YELLOW, 2, cv2.LINE_AA)

    # --- Sharpness text (top-left) ---
    sharp_text = f"sharpness={metrics.sharpness:.1f}"
    cv2.putText(img, sharp_text, (10, 22), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, WHITE, 2, cv2.LINE_AA)

    # --- Brightness text ---
    bright_text = (
        f"{metrics.quality_region} b={metrics.mean_brightness:.1f} "
        f"ov={metrics.overexposed_ratio:.3f} un={metrics.underexposed_ratio:.3f}"
    )
    cv2.putText(img, bright_text, (10, 44), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, WHITE, 1, cv2.LINE_AA)
    if metrics.quality_region == "plate_roi":
        global_text = f"global b={metrics.global_mean_brightness:.1f} sharp={metrics.global_sharpness:.1f}"
        cv2.putText(img, global_text, (10, 64), cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, WHITE, 1, cv2.LINE_AA)

    # --- Brightness histogram inset (bottom-right corner) ---
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    hist_h = 80
    hist_w = 128
    hist_origin_x = w - hist_w - 10
    hist_origin_y = h - hist_h - 10

    # Normalize histogram to fit the inset
    hist_norm = cv2.normalize(hist, None, 0, hist_h, cv2.NORM_MINMAX)
    # Draw semi-transparent background
    overlay = img.copy()
    cv2.rectangle(overlay, (hist_origin_x - 4, hist_origin_y - 4),
                  (hist_origin_x + hist_w + 4, hist_origin_y + hist_h + 4),
                  BLACK, -1)
    alpha = 0.55
    img[:] = cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0)

    for i in range(256):
        bar_h = int(hist_norm[i][0])
        px_x = hist_origin_x + int(i * hist_w / 256)
        cv2.line(img, (px_x, hist_origin_y + hist_h),
                 (px_x, hist_origin_y + hist_h - bar_h),
                 WHITE, 1, cv2.LINE_AA)

    # Histogram label
    cv2.putText(img, "hist", (hist_origin_x, hist_origin_y - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, WHITE, 1, cv2.LINE_AA)

    cv2.imwrite(str(output_path), img, [cv2.IMWRITE_PNG_COMPRESSION, 2])


def _generate_overlay_pil(
    image_path: Path,
    metrics: QualityMetrics,
    output_path: Path,
    bbox: dict[str, int] | None,
) -> None:
    """PIL fallback overlay rendering."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    GREEN = (0, 220, 0)
    RED = (220, 0, 0)

    if bbox:
        x, y, bw, bh = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
        draw.rectangle([x, y, x + bw, y + bh], outline=GREEN, width=2)
        if metrics.plate_corners_px:
            pts = [(p["x"], p["y"]) for p in metrics.plate_corners_px]
            draw.line(pts + [pts[0]], fill=(220, 180, 0), width=2)

        # Center crosshair
        cx, cy = x + bw // 2, y + bh // 2
        ch = 20
        draw.line([(cx - ch, cy), (cx + ch, cy)], fill=RED, width=2)
        draw.line([(cx, cy - ch), (cx, cy + ch)], fill=RED, width=2)

        if metrics.plate_rotation_deg is not None:
            draw.text((x + 6, y + 6), f"rot={metrics.plate_rotation_deg:.2f}deg",
                      fill=RED, font=font)

    # Sharpness
    draw.text((10, 10), f"sharpness={metrics.sharpness:.1f}", fill=RED, font=font)
    # Brightness
    draw.text((10, 28), f"{metrics.quality_region} b={metrics.mean_brightness:.1f}", fill=RED, font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)


# ---------------------------------------------------------------------------
# Before/after comparison
# ---------------------------------------------------------------------------


def generate_quality_report(
    before_metrics: QualityMetrics,
    after_metrics: QualityMetrics,
) -> dict[str, Any]:
    """Compare before vs. after quality metrics.

    Returns a dict with:
    - ``brightness_diff``: difference in mean brightness (after - before)
    - ``sharpness_diff``: difference in sharpness (after - before)
    - ``rotation_diff_deg``: difference in plate rotation (after - before)
    - ``center_shift_mm``: Euclidean distance between plate centers

    All values are rounded to 3 decimal places.  Rotation and center-shift
    are ``None`` when either image has no plate detected.
    """
    def _r(v: float) -> float:
        return round(v, 3)

    report: dict[str, Any] = {
        "brightness_diff": _r(after_metrics.mean_brightness - before_metrics.mean_brightness),
        "sharpness_diff": _r(after_metrics.sharpness - before_metrics.sharpness),
        "rotation_diff_deg": None,
        "center_shift_mm": None,
    }

    # Rotation diff (only when both have plate detection)
    if before_metrics.plate_rotation_deg is not None and after_metrics.plate_rotation_deg is not None:
        report["rotation_diff_deg"] = _r(
            after_metrics.plate_rotation_deg - before_metrics.plate_rotation_deg,
        )

    # Center shift (only when both have plate center offsets)
    if (
        before_metrics.plate_center_offset_mm is not None
        and after_metrics.plate_center_offset_mm is not None
    ):
        dx = after_metrics.plate_center_offset_mm[0] - before_metrics.plate_center_offset_mm[0]
        dy = after_metrics.plate_center_offset_mm[1] - before_metrics.plate_center_offset_mm[1]
        report["center_shift_mm"] = _r(hypot(dx, dy))

    return report
