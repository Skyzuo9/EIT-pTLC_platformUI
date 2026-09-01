"""Tests for TLC vision debug artifacts and VisionService overrides."""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from pathlib import Path

import pytest

from eit_ptlc.controller.vision_controller import VisionService


VIEW_DIR = Path("View/pTLC_Viewing").resolve()
if str(VIEW_DIR) not in sys.path:
    sys.path.insert(0, str(VIEW_DIR))

from tlc_analyze import process_pair, _detect_plate_tilt_deg  # type: ignore  # noqa: E402


CASE1_BEFORE = Path("data/samples/case1/before.jpg")
CASE1_AFTER = Path("data/samples/case1/after.jpg")


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    """Repo-local tmp dir for restricted Windows sandboxes."""
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
    root = Path("eit_ptlc/var/test_vision_algorithm_tmp") / safe_name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _require_case1() -> None:
    if not CASE1_BEFORE.is_file() or not CASE1_AFTER.is_file():
        pytest.skip("data/samples/case1 before/after images are not present")


def _fresh_workspace(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_process_pair_case1_writes_debug_evidence(tmp_path: Path) -> None:
    _require_case1()
    output_dir = _fresh_workspace(tmp_path, "debug_case1")
    summary = process_pair(
        case_name="case1",
        before_path=CASE1_BEFORE,
        after_path=CASE1_AFTER,
        output_dir=output_dir,
        plate_size_cm=20.0,
        path_step_cm=0.25,
        min_row_score=7.5,
        render_scale=1.0,
        export_pdf=False,
    )

    case_dir = output_dir / "case1"
    assert summary["ok"] is True
    assert summary["analysis_status"]["valid_band_count"] >= 1
    assert summary["recognition_params"]["min_row_score"] == pytest.approx(7.5)
    assert summary["solvent_front"]["source"]
    assert summary["solvent_front"]["is_fallback"] is False
    assert summary["row_scores"]["threshold"] == pytest.approx(7.5)
    assert summary["row_scores"]["max_value"] > 0
    assert summary["row_scores"]["all_peak_segments"]
    assert (case_dir / "score.png").is_file()
    assert (case_dir / "summary.json").is_file()

    non_origin = [b for b in summary["bands"] if not b.get("is_origin", False)]
    assert non_origin
    band_metrics = non_origin[0]["metrics"]
    assert "normalized_develop_height" in band_metrics
    assert "confidence" not in band_metrics


def test_process_pair_origin_only_is_not_success(tmp_path: Path) -> None:
    _require_case1()
    output_dir = _fresh_workspace(tmp_path, "origin_only")
    summary = process_pair(
        case_name="origin_only",
        before_path=CASE1_BEFORE,
        after_path=CASE1_AFTER,
        output_dir=output_dir,
        plate_size_cm=20.0,
        path_step_cm=0.25,
        min_row_score=9999.0,
        render_scale=1.0,
        export_pdf=False,
    )

    assert summary["ok"] is False
    assert summary["analysis_status"]["origin_only"] is True
    assert summary["analysis_status"]["valid_band_count"] == 0
    assert summary["solvent_front"]["source"] == "plate_top_fallback"
    assert summary["solvent_front"]["is_fallback"] is True
    assert summary["solvent_front"]["warning"]
    assert (output_dir / "origin_only" / "score.png").is_file()


def test_vision_service_analyze_full_accepts_debug_overrides(tmp_path: Path) -> None:
    _require_case1()
    output_dir = _fresh_workspace(tmp_path, "service_debug_overrides")
    service = VisionService(
        output_dir=tmp_path / "unused_vision_service_output",
        min_row_score=5.0,
        render_scale=1.0,
    )

    result = asyncio.run(
        service.analyze_full(
            sample_id="debug_case",
            before_path=CASE1_BEFORE,
            after_path=CASE1_AFTER,
            output_dir=output_dir,
            overrides={
                "min_row_score": 7.5,
                "image_plate_orientation": "rot0",
                "auto_rectify_tilt": False,
                "rectify_min_angle_deg": 0.5,
            },
        )
    )

    assert result.ok is True
    assert result.case_dir == output_dir / "debug_case"
    assert result.summary["recognition_params"]["min_row_score"] == pytest.approx(7.5)
    assert (result.case_dir / "score.png").is_file()


def test_vision_service_with_overrides_rejects_unknown_keys() -> None:
    service = VisionService(output_dir=Path("eit_ptlc/var/unused_vision_service_output"))
    with pytest.raises(ValueError, match="不支持的参数"):
        service.with_overrides(overrides={"rf_threshold": 0.2})


def test_process_pair_fixed_rotation_writes_normalized_and_squares_plate(tmp_path: Path) -> None:
    """固定角 deskew 主路径: 存 after_normalized.jpg (显示/手绘唯一背景, 与 plate_bbox_px 同帧)
    且按实测倾角把板摆正 (残差≈0) —— 帧内一致 + 帧间可重复的核心保证。"""
    _require_case1()
    import cv2  # type: ignore  # noqa: PLC0415

    raw_tilt = _detect_plate_tilt_deg(cv2.imread(str(CASE1_AFTER)))
    assert raw_tilt is not None

    output_dir = _fresh_workspace(tmp_path, "fixed_rotation")
    process_pair(
        case_name="fixrot",
        before_path=CASE1_BEFORE,
        after_path=CASE1_AFTER,
        output_dir=output_dir,
        plate_size_cm=20.0,
        path_step_cm=0.25,
        min_row_score=7.5,
        render_scale=1.0,
        export_pdf=False,
        image_plate_orientation="rot0",
        auto_rectify_tilt=True,               # 交叉校验分支也被执行 (仅告警, 不改旋转量)
        rectify_min_angle_deg=0.5,
        image_plate_rotation_deg=raw_tilt,    # 按实测倾角固定 deskew
    )

    normalized = output_dir / "fixrot" / "after_normalized.jpg"
    assert normalized.is_file()                         # 归一化图上盘
    residual = _detect_plate_tilt_deg(cv2.imread(str(normalized)))
    assert residual is not None
    assert abs(residual) < 0.6                          # 按实测角 deskew 后板已摆正 (残差≈0)
