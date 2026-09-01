"""视觉调试台服务与 HTTP 契约离线测试."""

from __future__ import annotations

import asyncio
import io
import json
import socket
from pathlib import Path

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.app import create_app
from eit_ptlc.controller.vision_controller import AnalysisResult, BandInfo
from eit_ptlc.controller.vision_debug_service import (
    VisionDebugError,
    VisionDebugService,
)
from eit_ptlc.runtime.bootstrap import create_sim_app


def _image_bytes(fmt: str = "JPEG") -> bytes:
    image = np.zeros((120, 180, 3), dtype=np.uint8)
    image[20:100, 35:145] = (40, 220, 80)
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, fmt)
    return buffer.getvalue()


class FakeCameraController:
    def __init__(self, *, fail: bool = False, delay: float = 0) -> None:
        self.fail = fail
        self.delay = delay
        self.calls: list[dict] = []
        self.active = 0
        self.max_active = 0

    async def capture_with_timing(
        self,
        sample_id: str,
        save_dir: Path,
        *,
        filename: str,
        overrides: dict,
    ):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("模拟相机故障")
            self.calls.append({
                "sample_id": sample_id,
                "filename": filename,
                "overrides": dict(overrides),
            })
            path = Path(save_dir) / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_image_bytes())
            return path, {
                "requested_uv_on_ms": overrides["uv_on_time_ms"],
                "actual_uv_on_ms": overrides["uv_on_time_ms"] - 10,
                "line1_close_ok": True,
                "over_limit": False,
            }
        finally:
            self.active -= 1


class FakeVisionService:
    def __init__(
        self,
        *,
        output_dir: Path | None = None,
        ok: bool = True,
        origin_only: bool = False,
    ) -> None:
        self.output_dir = output_dir
        self.ok = ok
        self.origin_only = origin_only
        self.last_overrides: dict | None = None

    def with_overrides(self, *, output_dir: Path, overrides: dict):
        clone = FakeVisionService(
            output_dir=Path(output_dir),
            ok=self.ok,
            origin_only=self.origin_only,
        )
        clone.last_overrides = dict(overrides)
        self.last_overrides = dict(overrides)
        return clone

    async def analyze_full(
        self,
        sample_id: str,
        before_path: Path | None,
        after_path: Path,
    ) -> AnalysisResult:
        assert before_path is not None
        case_dir = Path(self.output_dir or after_path.parent) / sample_id
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "score.png").write_bytes(_image_bytes("PNG"))
        (case_dir / "summary.json").write_text(
            json.dumps({"solvent_front": {"source": "detected"}}),
            encoding="utf-8",
        )
        annotated = case_dir / "annotated.png"
        annotated.write_bytes(_image_bytes("PNG"))
        origin = BandInfo(
            band_id="origin",
            is_origin=True,
            centroid_cm=(10.0, 2.0),
            bbox_cm=(1.0, 1.5, 19.0, 2.5),
            vertical_width_cm=1.0,
            horizontal_span_cm=18.0,
            distance_to_origin_cm=0.0,
            normalized_develop_height=0.0,
            area_cm2=18.0,
        )
        band = BandInfo(
            band_id="band_01",
            is_origin=False,
            centroid_cm=(10.0, 8.0),
            bbox_cm=(1.0, 7.0, 19.0, 9.0),
            vertical_width_cm=2.0,
            horizontal_span_cm=18.0,
            distance_to_origin_cm=6.0,
            normalized_develop_height=0.5,
            area_cm2=36.0,
        )
        bands = [origin] if self.origin_only else [origin, band]
        return AnalysisResult(
            ok=self.ok,
            case_name=sample_id,
            case_dir=case_dir,
            summary={"solvent_front": {"source": "detected"}},
            bands=bands,
            annotated_image_path=annotated,
            before_image_path=before_path,
            after_image_path=after_path,
        )


def _service(
    workspace: Path,
    *,
    camera: FakeCameraController | None = None,
    vision: FakeVisionService | None = None,
) -> VisionDebugService:
    return VisionDebugService(
        workspace,
        camera or FakeCameraController(),
        vision or FakeVisionService(),
    )


@pytest.mark.asyncio
async def test_capture_uses_formal_controller_contract_and_records_timing(tmp_path: Path):
    camera = FakeCameraController()
    service = _service(tmp_path, camera=camera)

    state = await service.capture(
        "before",
        {"exposure_time_us": 500_000, "gain": 2.0, "uv_on_time_ms": 700},
    )

    assert camera.calls[0]["filename"] == "before.jpg"
    assert camera.calls[0]["overrides"]["exposure_time"] == 500_000
    assert state["before"]["source"] == "capture"
    assert state["uv_timing"]["actual_uv_on_ms"] == 690
    assert state["before"]["quality_url"].endswith("before_quality.png")


@pytest.mark.asyncio
async def test_capture_failure_is_non_success_and_persisted(tmp_path: Path):
    service = _service(tmp_path, camera=FakeCameraController(fail=True))

    with pytest.raises(VisionDebugError, match="模拟相机故障"):
        await service.capture("before", {})

    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "模拟相机故障" in saved["error"]


@pytest.mark.asyncio
async def test_service_serializes_capture_calls(tmp_path: Path):
    camera = FakeCameraController(delay=0.02)
    service = _service(tmp_path, camera=camera)

    await asyncio.gather(
        service.capture("before", {}),
        service.capture("after", {}),
    )

    assert camera.max_active == 1


@pytest.mark.asyncio
async def test_upload_normalizes_png_and_invalidates_analysis(tmp_path: Path):
    service = _service(tmp_path)
    await service.upload("before", _image_bytes(), "before.jpg")
    await service.upload("after", _image_bytes(), "after.jpg")
    state = await service.analyze({})
    assert state["analysis"]["ok"] is True

    state = await service.upload("before", _image_bytes("PNG"), "replacement.png")

    assert state["analysis"] is None
    assert Image.open(tmp_path / "before.jpg").format == "JPEG"
    assert not (tmp_path / "result" / "annotated.png").exists()


@pytest.mark.asyncio
async def test_analyze_uses_overrides_and_copies_debug_artifacts(tmp_path: Path):
    vision = FakeVisionService()
    service = _service(tmp_path, vision=vision)
    await service.upload("before", _image_bytes(), "before.jpg")
    await service.upload("after", _image_bytes(), "after.jpg")

    state = await service.analyze({
        "image_plate_orientation": "rot0",
        "auto_rectify_tilt": False,
        "rectify_min_angle_deg": 1.0,
        "min_row_score": 3.5,
    })

    assert vision.last_overrides["min_row_score"] == 3.5
    assert state["analysis"]["bands"][1]["normalized_develop_height"] == 0.5
    assert (tmp_path / "result" / "score.png").is_file()
    assert (tmp_path / "result" / "annotated.png").is_file()


@pytest.mark.asyncio
async def test_origin_only_is_not_a_success(tmp_path: Path):
    service = _service(tmp_path, vision=FakeVisionService(origin_only=True))
    await service.upload("before", _image_bytes(), "before.jpg")
    await service.upload("after", _image_bytes(), "after.jpg")

    with pytest.raises(VisionDebugError, match="非原点条带"):
        await service.analyze({})

    assert service.state["analysis"]["ok"] is False


def test_state_is_snapshot_and_file_access_is_whitelisted(tmp_path: Path):
    service = _service(tmp_path)
    snapshot = service.state
    snapshot["camera_params"]["gain"] = 99

    assert service.state["camera_params"]["gain"] == 1.0
    assert service.get_file_path("before.jpg") == (tmp_path / "before.jpg").resolve()
    assert service.get_file_path("../before.jpg") is None
    assert service.get_file_path("secret.txt") is None


def test_http_contract_rejects_unknown_fields_and_reports_failures(tmp_path: Path):
    app = create_app(ActionRegistry({}), control_mode="DEBUG")
    app.state.vision_debug = _service(tmp_path)
    client = TestClient(app)

    bad = client.post("/api/vision/debug/capture", json={
        "role": "before",
        "exposure_time_us": 100_000,
        "gain": 1,
        "uv_on_time_ms": 300,
        "exposure": 100_000,
    })
    assert bad.status_code == 422

    missing = client.post("/api/vision/debug/analyze", json={
        "image_plate_orientation": "rot180",
        "auto_rectify_tilt": True,
        "rectify_min_angle_deg": 0.5,
        "min_row_score": 5.0,
    })
    assert missing.status_code == 409
    assert client.get("/api/vision/debug/state").json()["error"]


def test_http_upload_and_analyze_round_trip(tmp_path: Path):
    app = create_app(ActionRegistry({}), control_mode="DEBUG")
    app.state.vision_debug = _service(tmp_path)
    client = TestClient(app)

    for role in ("before", "after"):
        response = client.post(
            f"/api/vision/debug/upload/{role}",
            files={"file": (f"{role}.png", _image_bytes("PNG"), "image/png")},
        )
        assert response.status_code == 200

    analyzed = client.post("/api/vision/debug/analyze", json={
        "image_plate_orientation": "rot180",
        "auto_rectify_tilt": True,
        "rectify_min_angle_deg": 0.5,
        "min_row_score": 5.0,
    })
    assert analyzed.status_code == 200
    assert analyzed.json()["analysis"]["ok"] is True


def test_sim_bootstrap_injects_vision_debug_service(tmp_path: Path):
    repo = Path(__file__).resolve().parents[2]
    config_dir = repo / "eit_ptlc" / "config"
    raw = yaml.safe_load((config_dir / "app.yaml").read_text(encoding="utf-8"))
    raw["plc"]["nodes_file"] = str(config_dir / "plc_nodes.yaml")
    raw["robot"]["points_file"] = str(
        config_dir / "points" / "robot" / "robot_points.json"
    )
    raw["robot"]["points_meta_file"] = str(
        config_dir / "points" / "robot" / "robot_points_meta.json"
    )
    raw["robot"]["tool_state_file"] = str(config_dir / "robot_tool_state.json")
    raw["camera"]["mock"] = True
    raw["camera"]["test_image"] = str(repo / "data" / "samples" / "case1" / "after.jpg")
    raw["camera"]["test_before_image"] = str(
        repo / "data" / "samples" / "case1" / "before.jpg"
    )
    raw["vision"]["output_dir"] = str(tmp_path / "vision_output")
    raw["vision_debug"]["workspace_dir"] = str(tmp_path / "vision_debug")
    raw["water_level"]["enabled"] = False
    raw["codesys"]["enabled"] = False
    raw["recipes_dir"] = str(config_dir / "operation")
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_sim_app(
        config_path,
        opcua_url=f"opc.tcp://127.0.0.1:{port}/eit_ptlc/vision-test/",
    )
    with TestClient(app) as client:
        response = client.get("/api/vision/debug/state")
        assert response.status_code == 200
        assert response.json()["camera_params"]["uv_on_time_ms"] == 1000

        captured = client.post("/api/vision/debug/capture", json={
            "role": "before",
            "exposure_time_us": 500_000,
            "gain": 1.0,
            "uv_on_time_ms": 700,
        })
        assert captured.status_code == 200
        assert captured.json()["before"]["source"] == "capture"


def test_analyze_forwards_rotation_deg_and_persists_in_state(tmp_path):
    # rotation 入 _RECOGNITION_KEYS 后: analyze 参数经 with_overrides 透传给 VisionService,
    # 并持久化进 state.recognition_params (与其余 4 识别参数同轨)。
    fake_vision = FakeVisionService()
    service = VisionDebugService(
        tmp_path,
        FakeCameraController(),
        fake_vision,
        recognition_defaults={"image_plate_rotation_deg": None},
    )
    (tmp_path / "before.jpg").write_bytes(_image_bytes())
    (tmp_path / "after.jpg").write_bytes(_image_bytes())
    state = asyncio.run(service.analyze({
        "image_plate_orientation": "rot0",
        "auto_rectify_tilt": False,
        "rectify_min_angle_deg": 0.5,
        "min_row_score": 5.0,
        "image_plate_rotation_deg": -2.43,
    }))
    assert fake_vision.last_overrides["image_plate_rotation_deg"] == -2.43
    assert state["recognition_params"]["image_plate_rotation_deg"] == -2.43
