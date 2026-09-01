"""门内"重新识别(调参)" REST 端点 (T7 backend) 的离线测试。

契约: POST /api/photoscrape/reanalyze {summary_path, [识别覆盖]} →
  从 summary 同目录 inputs.json 取本 run 的 before/after → 经 executor 跑 photoscrape.analyze
  (与 VM 同一 live-read+覆盖路径) → 返回同形结果 (含 bands 供面板)。
只透传非 None 覆盖; 缺 inputs.json → 404; 缺 summary_path → 422。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from eit_ptlc.action.executor import ActionExecutor
from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.app import create_app

ACTIONS_DIR = Path(__file__).resolve().parents[1] / "config" / "actions"


def _client(captured: dict) -> TestClient:
    """真 registry (含 photoscrape.analyze 契约) + 假 analyze 方法, 截获 executor 透传的参数。"""

    async def fake_analyze(sample_id, before_path, after_path, **overrides):
        captured.update(
            sample_id=sample_id, before=before_path, after=after_path, overrides=overrides
        )
        return {
            "ok": True, "reason": "ok", "message": "",
            "summary_path": "x/summary.json", "case_dir": "x",
            "band_ids": ["band_01"], "annotated_url": "/api/vision/image/x/annotated.png",
            "bands": [{"band_id": "band_01", "is_origin": False}],
        }

    registry = ActionRegistry.load(ACTIONS_DIR)
    executor = ActionExecutor(registry, vision_methods={"analyze": fake_analyze})
    app = create_app(registry, executor=executor, control_mode="RUN")
    return TestClient(app)


def _write_inputs(tmp_path: Path, **kw) -> str:
    case_dir = tmp_path / "S1"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "inputs.json").write_text(json.dumps(kw), encoding="utf-8")
    return str(case_dir / "summary.json")


def test_reanalyze_reads_inputs_and_forwards_override(tmp_path):
    captured: dict = {}
    client = _client(captured)
    summary_path = _write_inputs(tmp_path, sample_id="S1", before_path="b.jpg", after_path="a.jpg")
    r = client.post(
        "/api/photoscrape/reanalyze",
        json={"summary_path": summary_path, "min_row_score": 3.0},
    )
    assert r.status_code == 200, r.text
    assert captured["before"] == "b.jpg"
    assert captured["after"] == "a.jpg"
    # #3: reanalyze 写独立 _re 目录 (case_dir=output_dir/sample_id), 不覆写原候选磁盘产物。
    assert captured["sample_id"] == "S1_re"
    assert captured["overrides"] == {"min_row_score": 3.0}
    body = r.json()
    assert body["band_ids"] == ["band_01"]
    assert body["bands"][0]["band_id"] == "band_01"


def test_reanalyze_baseline_when_no_overrides(tmp_path):
    captured: dict = {}
    client = _client(captured)
    summary_path = _write_inputs(tmp_path, sample_id="S1", before_path="b.jpg", after_path="a.jpg")
    r = client.post("/api/photoscrape/reanalyze", json={"summary_path": summary_path})
    assert r.status_code == 200, r.text
    assert captured["overrides"] == {}


def test_reanalyze_404_without_inputs(tmp_path):
    client = _client({})
    r = client.post(
        "/api/photoscrape/reanalyze",
        json={"summary_path": str(tmp_path / "nope" / "summary.json")},
    )
    assert r.status_code == 404


def test_reanalyze_422_without_summary_path(tmp_path):
    client = _client({})
    r = client.post("/api/photoscrape/reanalyze", json={})
    assert r.status_code == 422


def test_reanalyze_rejects_illegal_orientation(tmp_path):
    # #6: image_plate_orientation 现为 enum, 非法值经 executor 校验被拒(REJECTED) → 422; 不触及 analyze 方法。
    captured: dict = {}
    client = _client(captured)
    summary_path = _write_inputs(tmp_path, sample_id="S1", before_path="b.jpg", after_path="a.jpg")
    r = client.post(
        "/api/photoscrape/reanalyze",
        json={"summary_path": summary_path, "image_plate_orientation": "sideways"},
    )
    assert r.status_code == 422, r.text
    assert not captured, "非法参数应在 analyze 执行前被拒"


def test_reanalyze_rejects_out_of_range_angle(tmp_path):
    # #6: rectify_min_angle_deg 现有 max=45, 超限被拒 → 422。
    captured: dict = {}
    client = _client(captured)
    summary_path = _write_inputs(tmp_path, sample_id="S1", before_path="b.jpg", after_path="a.jpg")
    r = client.post(
        "/api/photoscrape/reanalyze",
        json={"summary_path": summary_path, "rectify_min_angle_deg": 90.0},
    )
    assert r.status_code == 422, r.text
    assert not captured


def test_reanalyze_accepts_valid_orientation(tmp_path):
    # #6: 合法 orientation 正常透传 (校验放行)。
    captured: dict = {}
    client = _client(captured)
    summary_path = _write_inputs(tmp_path, sample_id="S1", before_path="b.jpg", after_path="a.jpg")
    r = client.post(
        "/api/photoscrape/reanalyze",
        json={"summary_path": summary_path, "image_plate_orientation": "rot90cw"},
    )
    assert r.status_code == 200, r.text
    assert captured["overrides"]["image_plate_orientation"] == "rot90cw"


def test_reanalyze_forwards_rotation_deg_including_zero(tmp_path):
    # rotation=0.0 是合法覆盖值(整数零), 必须透传, 不得被判空丢弃 (None-sentinel 零值坑)。
    captured: dict = {}
    client = _client(captured)
    summary_path = _write_inputs(tmp_path, sample_id="S1", before_path="b.jpg", after_path="a.jpg")
    r = client.post(
        "/api/photoscrape/reanalyze",
        json={"summary_path": summary_path, "image_plate_rotation_deg": 0.0},
    )
    assert r.status_code == 200, r.text
    assert captured["overrides"] == {"image_plate_rotation_deg": 0.0}


def test_reanalyze_rejects_out_of_range_rotation(tmp_path):
    # 超出 [-180,180] 经 executor 契约校验被拒 → 422, 不触及 analyze。
    captured: dict = {}
    client = _client(captured)
    summary_path = _write_inputs(tmp_path, sample_id="S1", before_path="b.jpg", after_path="a.jpg")
    r = client.post(
        "/api/photoscrape/reanalyze",
        json={"summary_path": summary_path, "image_plate_rotation_deg": 200.0},
    )
    assert r.status_code == 422, r.text
    assert not captured
