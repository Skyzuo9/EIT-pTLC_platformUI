"""调试台"载入生产 case"(cases 列表 + load_case)离线测试。

契约: GET /api/vision/debug/cases 扫 config.vision.output_dir 单根, case = 含 inputs.json
的子目录, mtime 倒序截 50 (truncated 标志); POST /api/vision/debug/load_case {summary_dir}
把该 case 的 before/after 经上传同一归一化路径拷入工作区, state[role].source = "case:<id>"。
防穿越: summary_dir 解析后必须在 output_dir 根内; inputs.json/图片缺失 → 404 明确文案。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from eit_ptlc.api.vision_debug_routes import register_vision_debug_routes
from eit_ptlc.controller.config_service import ConfigService
from eit_ptlc.controller.vision_debug_service import VisionDebugService


def _jpg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (60, 40), (40, 220, 80)).save(buffer, "JPEG")
    return buffer.getvalue()


def _make_case(root: Path, name: str, *, with_images: bool = True) -> Path:
    case_dir = root / name
    case_dir.mkdir(parents=True)
    before = case_dir / "before_src.jpg"
    after = case_dir / "after_src.jpg"
    if with_images:
        before.write_bytes(_jpg_bytes())
        after.write_bytes(_jpg_bytes())
    (case_dir / "inputs.json").write_text(
        json.dumps({"sample_id": name, "before_path": str(before), "after_path": str(after)}),
        encoding="utf-8",
    )
    return case_dir


def _client(tmp_path: Path) -> TestClient:
    output_root = tmp_path / "vision_output"
    output_root.mkdir()
    cfg_path = tmp_path / "app.yaml"
    cfg_path.write_text(
        f"vision:\n  mock: true\n  output_dir: {json.dumps(str(output_root))}\n",
        encoding="utf-8",
    )
    app = FastAPI()
    app.state.config_svc = ConfigService(cfg_path)
    # camera/vision 服务在 upload/load_case 路径上不被触达 → None 桩即可
    app.state.vision_debug = VisionDebugService(tmp_path / "workspace", None, None)
    app.state.control_mode = "DEBUG"
    register_vision_debug_routes(app)
    return TestClient(app)


def test_list_and_load_case(tmp_path):
    client = _client(tmp_path)
    output_root = tmp_path / "vision_output"
    case_dir = _make_case(output_root, "S1")
    observation = {
        "schema": "ptlc.water-level-observation/v1",
        "run_id": "run-S1",
        "sample_id": "S1",
        "measurement": {"percent": 61.0, "front_percent": 59.5, "valid": True},
    }
    (case_dir / "liquid_observation.json").write_text(
        json.dumps(observation), encoding="utf-8",
    )
    (output_root / "not_a_case").mkdir()  # 无 inputs.json → 不列出

    r = client.get("/api/vision/debug/cases")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["id"] for c in body["cases"]] == ["S1"]
    assert body["truncated"] is False

    r2 = client.post(
        "/api/vision/debug/load_case",
        json={"summary_dir": body["cases"][0]["summary_dir"]},
    )
    assert r2.status_code == 200, r2.text
    state = r2.json()
    assert state["before"]["source"] == "case:S1"
    assert state["after"]["source"] == "case:S1"
    assert state["source_context"]["sample_id"] == "S1"
    assert state["source_context"]["liquid_observation"] == observation
    assert (tmp_path / "workspace" / "before.jpg").is_file()
    assert (tmp_path / "workspace" / "after.jpg").is_file()


def test_load_case_404_when_images_cleaned(tmp_path):
    client = _client(tmp_path)
    case_dir = _make_case(tmp_path / "vision_output", "S2", with_images=False)
    r = client.post("/api/vision/debug/load_case", json={"summary_dir": str(case_dir)})
    assert r.status_code == 404
    assert "已被清理" in r.json()["detail"]


def test_load_case_404_when_inputs_missing(tmp_path):
    client = _client(tmp_path)
    case_dir = tmp_path / "vision_output" / "S3"
    case_dir.mkdir(parents=True)
    r = client.post("/api/vision/debug/load_case", json={"summary_dir": str(case_dir)})
    assert r.status_code == 404
    assert "inputs.json" in r.json()["detail"]


def test_load_case_rejects_outside_root(tmp_path):
    # 防穿越: 不在 output_dir 根内的目录一律拒 (即使真实存在且含 inputs.json)。
    client = _client(tmp_path)
    outside = _make_case(tmp_path / "elsewhere", "EVIL")
    r = client.post("/api/vision/debug/load_case", json={"summary_dir": str(outside)})
    assert r.status_code == 404
    assert "不在视觉输出目录" in r.json()["detail"]


def test_load_case_missing_after_leaves_workspace_untouched(tmp_path):
    # 半途失败不得留混对态: after 缺失时 before 也不得已被载入 (终审 Important #2)
    client = _client(tmp_path)
    case_dir = _make_case(tmp_path / "vision_output", "S4")
    (case_dir / "after_src.jpg").unlink()
    r = client.post("/api/vision/debug/load_case", json={"summary_dir": str(case_dir)})
    assert r.status_code == 404
    assert not (tmp_path / "workspace" / "before.jpg").exists()
