"""调试台"应用到生产" (step 0e / 打通调参↔生产) 的离线端到端测试。

契约: POST /api/vision/debug/apply_to_production 把调试台当前 recognition_params 的 4 个
识别参数写回 config.vision 单一真源 (经 ConfigService.save_section 校验+保留其余项),
使随后生产 analyze 实时读取即生效。这里直接校验"写回 config.vision"这一环。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eit_ptlc.api.vision_debug_routes import register_vision_debug_routes
from eit_ptlc.controller.config_service import ConfigService


_APP_YAML = """\
vision:
  mock: true
  output_dir: vision_output
  image_plate_orientation: rot0
  auto_rectify_tilt: false
  rectify_min_angle_deg: 0.5
  min_row_score: 5.0
"""


class _StubBench:
    """只暴露 .state.recognition_params 的最小桩 (端点仅读这一项)。"""

    def __init__(self, recognition: dict) -> None:
        self._recognition = dict(recognition)

    @property
    def state(self) -> dict:
        return {"recognition_params": dict(self._recognition)}


def _client(tmp_path: Path, recognition: dict) -> tuple[TestClient, ConfigService]:
    cfg_path = tmp_path / "app.yaml"
    cfg_path.write_text(_APP_YAML, encoding="utf-8")
    cfg_svc = ConfigService(cfg_path)
    app = FastAPI()
    app.state.config_svc = cfg_svc
    app.state.vision_debug = _StubBench(recognition)
    app.state.control_mode = "DEBUG"
    register_vision_debug_routes(app)
    return TestClient(app), cfg_svc


def test_apply_writes_recognition_to_config_vision(tmp_path):
    tuned = {
        "image_plate_orientation": "rot180",
        "auto_rectify_tilt": True,
        "rectify_min_angle_deg": 1.0,
        "min_row_score": 3.5,
    }
    client, cfg_svc = _client(tmp_path, tuned)
    resp = client.post("/api/vision/debug/apply_to_production")
    assert resp.status_code == 200
    assert resp.json()["applied"] == tuned

    # 写回 config.vision 生效, 且不动 vision 段其余项 (mock/output_dir 保留)。
    after = cfg_svc.read_section("vision")
    assert after["min_row_score"] == 3.5
    assert after["image_plate_orientation"] == "rot180"
    assert after["auto_rectify_tilt"] is True
    assert after["rectify_min_angle_deg"] == 1.0
    assert after["mock"] is True
    assert after["output_dir"] == "vision_output"


def test_apply_rejects_invalid_recognition(tmp_path):
    # 负的 min_row_score 触发 _parse_vision 校验失败 → 422, 且不写盘。
    client, cfg_svc = _client(tmp_path, {"min_row_score": -1.0})
    resp = client.post("/api/vision/debug/apply_to_production")
    assert resp.status_code == 422
    assert cfg_svc.read_section("vision")["min_row_score"] == 5.0


def test_apply_without_config_service_is_503(tmp_path):
    client, _ = _client(tmp_path, {"min_row_score": 4.0})
    client.app.state.config_svc = None
    resp = client.post("/api/vision/debug/apply_to_production")
    assert resp.status_code == 503


def test_apply_includes_rotation_deg_value(tmp_path):
    tuned = {
        "image_plate_orientation": "rot180",
        "auto_rectify_tilt": True,
        "rectify_min_angle_deg": 1.0,
        "min_row_score": 3.5,
        "image_plate_rotation_deg": -2.0,
    }
    client, cfg_svc = _client(tmp_path, tuned)
    resp = client.post("/api/vision/debug/apply_to_production")
    assert resp.status_code == 200
    assert resp.json()["applied"] == tuned
    assert cfg_svc.read_section("vision")["image_plate_rotation_deg"] == -2.0


def test_apply_rotation_deg_null_roundtrip(tmp_path):
    # null = 每帧自动估计, 是合法可应用值 (VisionCfg 字段 Optional), 写回后读回仍为 None。
    tuned = {"min_row_score": 4.0, "image_plate_rotation_deg": None}
    client, cfg_svc = _client(tmp_path, tuned)
    resp = client.post("/api/vision/debug/apply_to_production")
    assert resp.status_code == 200
    after = cfg_svc.read_section("vision")
    assert after["min_row_score"] == 4.0
    assert after["image_plate_rotation_deg"] is None
