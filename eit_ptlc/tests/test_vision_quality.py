"""Vision quality diagnostics offline test
==========================================
验证 controller/vision_quality 在合成图像上的指标计算:
  - 所有指标字段均被填充, 无异常
  - plate_bbox_px 提供时 plate 相关指标已计算
  - 无 plate 时 plate 相关字段为 None
  - overlay 生成有效 PNG
  - before/after report 包含预期键
  - 不存在的路径抛出 FileNotFoundError
  - 临时文件测试后自动清理

运行:
    python -m pytest eit_ptlc/tests/test_vision_quality.py -v

依赖: cv2 / numpy (合成图生成) + PIL/Pillow
"""

from __future__ import annotations

import sys
import re
import shutil
from pathlib import Path

import pytest

from eit_ptlc.controller.vision_quality import (
    QualityMetrics,
    analyze_quality,
    generate_quality_overlay,
    generate_quality_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_synthetic_plate_image(
    path: Path,
    width: int = 640,
    height: int = 480,
    *,
    plate_x: int = 120,
    plate_y: int = 80,
    plate_w: int = 400,
    plate_h: int = 320,
    plate_intensity: int = 80,
    bg_intensity: int = 210,
    add_noise: bool = True,
) -> tuple[int, int, int, int]:
    """Create a synthetic JPEG with a dark 'plate' rectangle on a light background.

    Returns the plate bbox as ``(x, y, w, h)``.
    """
    import numpy as np
    from PIL import Image

    # Light background
    img = np.full((height, width, 3), bg_intensity, dtype=np.uint8)
    # Dark plate rectangle
    img[plate_y : plate_y + plate_h, plate_x : plate_x + plate_w] = plate_intensity

    if add_noise:
        rng = np.random.default_rng(42)
        noise = rng.integers(-8, 9, img.shape, dtype=np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    Image.fromarray(img).save(str(path), "JPEG", quality=95)
    return plate_x, plate_y, plate_w, plate_h


def _make_synthetic_green_plate_image(
    path: Path,
    width: int = 640,
    height: int = 480,
    *,
    plate_x: int = 120,
    plate_y: int = 80,
    plate_w: int = 400,
    plate_h: int = 320,
) -> tuple[int, int, int, int]:
    """Create a fluorescent-green TLC-like image on a dark background."""
    import numpy as np
    from PIL import Image

    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = (12, 18, 16)
    img[plate_y : plate_y + plate_h, plate_x : plate_x + plate_w] = (18, 125, 24)
    rng = np.random.default_rng(123)
    noise = rng.integers(-4, 5, img.shape, dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    Image.fromarray(img).save(str(path), "JPEG", quality=95)
    return plate_x, plate_y, plate_w, plate_h


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    """Repo-local tmp dir for restricted Windows sandboxes."""
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
    root = Path("eit_ptlc/var/test_vision_quality_tmp") / safe_name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def tmp_img(tmp_path: Path) -> Path:
    """Synthetic plate image in a temporary directory."""
    p = tmp_path / "test_plate.jpg"
    _make_synthetic_plate_image(p)
    return p


@pytest.fixture
def no_plate_img(tmp_path: Path) -> Path:
    """Uniform grey image (no detectable plate)."""
    import numpy as np
    from PIL import Image

    p = tmp_path / "no_plate.jpg"
    img = np.full((480, 640, 3), 150, dtype=np.uint8)
    # Very slight gradient so it's not perfectly uniform
    rng = np.random.default_rng(99)
    img = np.clip(img.astype(np.int16) + rng.integers(-2, 3, img.shape, dtype=np.int16),
                  0, 255).astype(np.uint8)
    Image.fromarray(img).save(str(p), "JPEG", quality=95)
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyzeQuality:
    """Unit tests for analyze_quality()."""

    def test_all_metrics_populated(self, tmp_img: Path) -> None:
        """All metric fields should be populated without error."""
        m = analyze_quality(tmp_img)

        assert m.mean_brightness > 0
        assert m.sharpness > 0
        assert m.overexposed_ratio >= 0.0
        assert m.underexposed_ratio >= 0.0
        assert m.image_width == 640
        assert m.image_height == 480
        assert isinstance(m.plate_center_offset_mm, tuple | None)
        # Plate should be detectable in the synthetic image
        assert m.plate_bbox_px is not None, "Plate should be detected in synthetic image"

    def test_with_provided_bbox(self, tmp_img: Path) -> None:
        """When plate_bbox_px is provided, plate-specific metrics use it."""
        bbox = {"x": 120, "y": 80, "w": 400, "h": 320}
        m = analyze_quality(tmp_img, plate_bbox_px=bbox)

        assert m.plate_bbox_px == bbox
        assert m.plate_center_offset_mm is not None
        assert m.margin_px is not None
        assert m.margin_px["top"] == 80
        assert m.margin_px["left"] == 120

    def test_no_plate_detected(self, no_plate_img: Path) -> None:
        """When no plate is present nor provided, plate fields are None."""
        m = analyze_quality(no_plate_img)

        assert m.plate_center_offset_mm is None
        assert m.plate_rotation_deg is None
        assert m.perspective_skew_deg is None
        assert m.margin_px is None
        # Global metrics still work
        assert m.mean_brightness > 0
        assert m.sharpness > 0

    def test_green_fluorescent_plate_detected(self, tmp_path: Path) -> None:
        """Fluorescent green TLC plates use the production green-mask detector."""
        img = tmp_path / "green_plate.jpg"
        _make_synthetic_green_plate_image(img)

        m = analyze_quality(img)

        assert m.plate_bbox_px is not None
        assert m.plate_center_px is not None
        assert m.plate_corners_px is not None
        assert len(m.plate_corners_px) == 4
        assert m.margin_px is not None
        assert m.quality_region == "plate_roi"
        assert m.global_mean_brightness != m.mean_brightness

    def test_real_case1_green_plate_detected(self) -> None:
        """The current real sample image should expose geometry diagnostics."""
        case1 = Path("data/samples/case1/after.jpg")
        if not case1.is_file():
            pytest.skip("case1 sample image is not present")

        m = analyze_quality(case1)

        assert m.plate_bbox_px is not None
        assert m.plate_center_px is not None
        assert m.plate_corners_px is not None
        assert len(m.plate_corners_px) == 4
        assert m.plate_rotation_deg is not None
        assert m.perspective_skew_deg is not None
        assert m.margin_px is not None
        assert m.quality_region == "plate_roi"
        assert m.global_mean_brightness > 0

    def test_nonexistent_path_raises(self, tmp_path: Path) -> None:
        """Non-existent image path should raise FileNotFoundError."""
        bad = tmp_path / "does_not_exist.jpg"
        with pytest.raises(FileNotFoundError):
            analyze_quality(bad)

    def test_brightness_range(self, tmp_img: Path) -> None:
        """Mean brightness should be in [0, 255]."""
        m = analyze_quality(tmp_img)
        assert 0.0 <= m.mean_brightness <= 255.0

    def test_ratio_bounds(self, tmp_img: Path) -> None:
        """Over/underexposed ratios should be in [0, 1]."""
        m = analyze_quality(tmp_img)
        assert 0.0 <= m.overexposed_ratio <= 1.0
        assert 0.0 <= m.underexposed_ratio <= 1.0


class TestGenerateQualityOverlay:
    """Unit tests for generate_quality_overlay()."""

    def test_produces_valid_png(self, tmp_img: Path, tmp_path: Path) -> None:
        """Overlay should write a valid PNG file."""
        m = analyze_quality(tmp_img)
        out = tmp_path / "overlay.png"
        result = generate_quality_overlay(tmp_img, m, out)

        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

        # Verify it's a real PNG (magic bytes)
        header = out.read_bytes()[:8]
        assert header[:4] == b"\x89PNG"

    def test_overlay_with_explicit_bbox(self, tmp_img: Path, tmp_path: Path) -> None:
        """Overlay should work with an externally-provided bbox."""
        bbox = {"x": 100, "y": 60, "w": 440, "h": 360}
        m = analyze_quality(tmp_img)
        out = tmp_path / "overlay_bbox.png"
        result = generate_quality_overlay(tmp_img, m, out, plate_bbox_px=bbox)

        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_nonexistent_path_raises(self, tmp_path: Path) -> None:
        """Non-existent source image should raise FileNotFoundError."""
        m = QualityMetrics(mean_brightness=100, image_width=640, image_height=480)
        bad = tmp_path / "does_not_exist.jpg"
        out = tmp_path / "overlay.png"
        with pytest.raises(FileNotFoundError):
            generate_quality_overlay(bad, m, out)


class TestGenerateQualityReport:
    """Unit tests for generate_quality_report()."""

    def test_expected_keys(self) -> None:
        """Report dict should contain all expected keys."""
        before = QualityMetrics(mean_brightness=120.0, sharpness=500.0)
        after = QualityMetrics(mean_brightness=125.0, sharpness=520.0)
        report = generate_quality_report(before, after)

        assert "brightness_diff" in report
        assert "sharpness_diff" in report
        assert "rotation_diff_deg" in report
        assert "center_shift_mm" in report

    def test_brightness_diff(self) -> None:
        """Brightness diff should be after - before."""
        before = QualityMetrics(mean_brightness=100.0)
        after = QualityMetrics(mean_brightness=110.0)
        report = generate_quality_report(before, after)
        assert report["brightness_diff"] == 10.0

    def test_sharpness_diff(self) -> None:
        """Sharpness diff should be after - before."""
        before = QualityMetrics(sharpness=400.0)
        after = QualityMetrics(sharpness=450.0)
        report = generate_quality_report(before, after)
        assert report["sharpness_diff"] == 50.0

    def test_rotation_diff_none_when_missing(self) -> None:
        """Rotation diff is None when either side lacks plate detection."""
        before = QualityMetrics(plate_rotation_deg=2.5)
        after = QualityMetrics(plate_rotation_deg=None)
        report = generate_quality_report(before, after)
        assert report["rotation_diff_deg"] is None

    def test_rotation_diff_computed(self) -> None:
        """Rotation diff computed when both have plate detection."""
        before = QualityMetrics(plate_rotation_deg=1.0)
        after = QualityMetrics(plate_rotation_deg=3.0)
        report = generate_quality_report(before, after)
        assert report["rotation_diff_deg"] == pytest.approx(2.0)

    def test_center_shift_none_when_missing(self) -> None:
        """Center shift is None when either side lacks plate detection."""
        before = QualityMetrics(plate_center_offset_mm=(1.0, 2.0))
        after = QualityMetrics(plate_center_offset_mm=None)
        report = generate_quality_report(before, after)
        assert report["center_shift_mm"] is None

    def test_center_shift_computed(self) -> None:
        """Center shift should be Euclidean distance between offsets."""
        before = QualityMetrics(plate_center_offset_mm=(0.0, 0.0))
        after = QualityMetrics(plate_center_offset_mm=(3.0, 4.0))
        report = generate_quality_report(before, after)
        assert report["center_shift_mm"] == pytest.approx(5.0)

    def test_values_rounded_to_3_decimals(self) -> None:
        """All numeric report values should be rounded to 3 decimal places."""
        before = QualityMetrics(mean_brightness=100.123456)
        after = QualityMetrics(mean_brightness=200.654321)
        report = generate_quality_report(before, after)
        diff_str = str(report["brightness_diff"])
        # After rounding to 3 dp: 100.531 (200.654321 - 100.123456 = 100.530865)
        decimal_part = diff_str.split(".")[-1] if "." in diff_str else ""
        assert len(decimal_part) <= 3


class TestIntegration:
    """End-to-end pipeline test."""

    def test_full_pipeline(self, tmp_path: Path) -> None:
        """Analyze -> overlay -> report with before/after images."""
        # Create before/after synthetic images
        before_path = tmp_path / "before.jpg"
        after_path = tmp_path / "after.jpg"
        bbox_before = _make_synthetic_plate_image(before_path)
        bbox_after = _make_synthetic_plate_image(after_path)

        # Analyze both
        before_m = analyze_quality(before_path)
        after_m = analyze_quality(after_path)

        # Both should have detected plates
        assert before_m.plate_bbox_px is not None
        assert after_m.plate_bbox_px is not None

        # Generate overlays
        overlay_before = tmp_path / "before_overlay.png"
        overlay_after = tmp_path / "after_overlay.png"
        assert generate_quality_overlay(before_path, before_m, overlay_before).exists()
        assert generate_quality_overlay(after_path, after_m, overlay_after).exists()

        # Generate report
        report = generate_quality_report(before_m, after_m)
        assert isinstance(report["brightness_diff"], float)
        assert isinstance(report["sharpness_diff"], float)
        # Since both images are identical synthetic copies, diffs should be near zero
        assert abs(report["brightness_diff"]) < 5.0
        assert abs(report["sharpness_diff"]) < 10.0

    def test_pipeline_with_provided_bbox(self, tmp_path: Path) -> None:
        """Full pipeline with externally-provided bbox (e.g. from recognition)."""
        before_path = tmp_path / "before.jpg"
        _make_synthetic_plate_image(before_path)

        bbox = {"x": 120, "y": 80, "w": 400, "h": 320}
        m = analyze_quality(before_path, plate_bbox_px=bbox)

        overlay = tmp_path / "overlay.png"
        generate_quality_overlay(before_path, m, overlay, plate_bbox_px=bbox)

        assert overlay.exists()
        # Verify plate center offset uses the provided bbox
        assert m.plate_center_offset_mm is not None


# ---------------------------------------------------------------------------
# Manual runner (for parity with other eit_ptlc tests)
# ---------------------------------------------------------------------------


def main() -> int:
    """Run tests manually (also callable with -m)."""
    # Enable pytest-style reporting when run directly
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        capture_output=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
