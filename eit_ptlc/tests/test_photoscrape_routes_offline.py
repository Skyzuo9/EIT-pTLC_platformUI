"""手绘路径来源 REST 端点离线测试 (TestClient)。

验证 preview/commit/context 三端点契约, 且提交产出的 summary 能被**真** cnc_path 消费。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.app import create_app
from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller.cnc_path import generate_scrape_arrays

PLATE_BBOX = {"x": 100, "y": 50, "w": 400, "h": 400}
REGION = [[150, 100], [450, 100], [450, 400], [150, 400]]
CORNERS = [[100, 50], [500, 50], [500, 450], [100, 450]]  # TL,TR,BR,BL


class _FakeConfigSvc:
    def __init__(self, output_dir):
        self._out = str(output_dir)

    def read_section(self, name):
        if name == "vision":
            return {"output_dir": self._out}
        return {}  # gcode → _parse_gcode({}) 走全默认


def _client(tmp_path) -> TestClient:
    app = create_app(ActionRegistry({}), control_mode="DEBUG")
    app.state.config_svc = _FakeConfigSvc(tmp_path)
    return TestClient(app)


def test_preview_returns_wysiwyg_px_path(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/photoscrape/preview_path",
                    json={"polygon_px": REGION, "plate_bbox_px": PLATE_BBOX, "plate_size_cm": 20})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["scrape_px"]) == 400 and d["pass_count"] >= 1 and d["point_count"] == 400
    for x, y in d["scrape_px"]:            # 预览落回板像素框内
        assert 95 <= x <= 505 and 45 <= y <= 455


def test_preview_rejects_missing_plate_reference(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/photoscrape/preview_path", json={"polygon_px": REGION, "plate_size_cm": 20})
    assert r.status_code == 422


def test_commit_writes_summary_consumable_by_cnc_path(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/photoscrape/sketch_commit",
                    json={"polygon_px": REGION, "plate_bbox_px": PLATE_BBOX, "plate_size_cm": 20, "sample_id": "T"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["band_id"] == "manual_01" and d["ok"] is True
    summary = Path(d["summary_path"])
    assert summary.is_file()
    # 真 cnc_path 直接消费手绘 summary → 非退化 400 点
    arrays = generate_scrape_arrays(summary, "manual_01", GCodeCfg())
    assert len(arrays.g_sx) == 400
    assert max(arrays.g_sx) - min(arrays.g_sx) > 50.0


def test_commit_with_corners_when_no_plate_bbox(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/photoscrape/sketch_commit",
                    json={"polygon_px": REGION, "plate_corners_px": CORNERS, "plate_size_cm": 20, "sample_id": "C"})
    assert r.status_code == 200, r.text
    assert Path(r.json()["summary_path"]).is_file()


def test_sketch_context_reports_plate_reference_presence(tmp_path):
    client = _client(tmp_path)
    with_bbox = tmp_path / "summary.json"
    with_bbox.write_text(json.dumps({"plate_bbox_px": PLATE_BBOX, "plate_size_cm": 20}), encoding="utf-8")
    r = client.get("/api/photoscrape/sketch_context", params={"summary_path": str(with_bbox)})
    assert r.status_code == 200 and r.json()["has_plate_ref"] is True

    no_bbox = tmp_path / "s2.json"
    no_bbox.write_text(json.dumps({"ok": False}), encoding="utf-8")
    r2 = client.get("/api/photoscrape/sketch_context", params={"summary_path": str(no_bbox)})
    assert r2.status_code == 200 and r2.json()["has_plate_ref"] is False


def test_commit_sanitizes_traversal_sample_id(tmp_path):
    # #7: sample_id 含 ../ 不得越 output_dir 写文件; .name 去分隔符后产物落在 output_dir 内。
    client = _client(tmp_path)
    r = client.post("/api/photoscrape/sketch_commit",
                    json={"polygon_px": REGION, "plate_bbox_px": PLATE_BBOX, "plate_size_cm": 20,
                          "sample_id": "../../evil"})
    assert r.status_code == 200, r.text
    summary = Path(r.json()["summary_path"]).resolve()
    assert summary.is_file()
    assert summary.is_relative_to(tmp_path.resolve()), "提交产物必须落在 output_dir 内, 不得目录穿越"
    assert summary.parts[-2] == "evil_manual", "目录名取自净化后的 .name, 不含穿越段"


def test_preview_rejects_malformed_points(tmp_path):
    # #12: 畸形点(非二元数对)应 422, 而非 _clean_closed 取 p[1] 抛 TypeError → HTTP 500。
    client = _client(tmp_path)
    r = client.post("/api/photoscrape/preview_path",
                    json={"polygon_px": [[1, 2], [3], [5, 6]], "plate_bbox_px": PLATE_BBOX, "plate_size_cm": 20})
    assert r.status_code == 422, r.text
