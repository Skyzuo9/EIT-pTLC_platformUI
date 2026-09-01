"""4 角标板矫正帧 — 点序校验矩阵 + warp 黄金值 (spec §6.1, 契约 C-2)。"""

from __future__ import annotations

import numpy as np
import pytest

from eit_ptlc.controller import sketch_path as sp

_GOOD = [[30, 20], [170, 25], [165, 140], [28, 135]]  # 左上,右上,右下,左下


def test_validate_accepts_good_corners():
    pts = sp.validate_manual_corners(_GOOD)
    assert len(pts) == 4 and pts[0] == (30.0, 20.0)


@pytest.mark.parametrize("corners,frag", [
    ([[0, 0], [1, 1], [2, 2]], "4 个角点"),                       # 数量
    ([[0, 0], [10], [2, 2], [3, 3]], "数对"),                     # 形状
    ([[170, 20], [30, 25], [165, 140], [28, 135]], "左右颠倒"),    # 左右换
    ([[30, 140], [170, 135], [165, 20], [28, 25]], "上下颠倒"),    # 上下换
    ([[30, 20], [170, 25], [165, 140], [100, 80]], "凸四边形"),    # BL 内凹(方位检查可通过, 凸性不行)
    ([[10, 10], [50, 20], [90, 30], [50, 20]], "共线"),            # 同一斜线上退化(方位检查可通过)
])
def test_validate_rejects_bad_corners(corners, frag):
    with pytest.raises(ValueError, match=frag):
        sp.validate_manual_corners(corners)


def test_rectify_manual_frame_warps_to_square(tmp_path):
    cv2 = pytest.importorskip("cv2")
    img = np.zeros((160, 200, 3), dtype=np.uint8)
    cv2.fillPoly(img, [np.array(_GOOD, dtype=np.int32)], (255, 255, 255))  # 板内白
    backdrop = tmp_path / "after_normalized.jpg"
    cv2.imwrite(str(backdrop), img)
    res = sp.rectify_manual_frame(backdrop, _GOOD, 20.0, tmp_path, px_per_cm=10)
    out = cv2.imread(res["image_path"])
    assert [out.shape[1], out.shape[0]] == [200, 200]              # 20cm × 10px/cm
    assert float(out.mean()) > 180                                 # 板区充满画幅(近全白)
    assert res["plate_bbox_px"] == {"x": 0, "y": 0, "w": 200, "h": 200}
    assert res["manual_rectify"] == {
        "plate_corners_px": [[30.0, 20.0], [170.0, 25.0], [165.0, 140.0], [28.0, 135.0]],
        "px_per_cm": 10, "frame_size": [200, 200],
    }


def test_rectify_unreadable_backdrop_raises(tmp_path):
    pytest.importorskip("cv2")
    with pytest.raises(ValueError, match="底图"):
        sp.rectify_manual_frame(tmp_path / "nope.jpg", _GOOD, 20.0, tmp_path)


def _client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from eit_ptlc.api.photoscrape_routes import register_photoscrape_routes

    class _CfgStub:
        def read_section(self, name):
            return {"output_dir": str(tmp_path)}

    app = FastAPI()
    app.state.config_svc = _CfgStub()
    register_photoscrape_routes(app)
    return TestClient(app)


def _case_dir(tmp_path):
    cv2 = pytest.importorskip("cv2")
    case = tmp_path / "T1"
    case.mkdir()
    img = np.zeros((160, 200, 3), dtype=np.uint8)
    cv2.fillPoly(img, [np.array(_GOOD, dtype=np.int32)], (255, 255, 255))
    cv2.imwrite(str(case / "after_normalized.jpg"), img)
    (case / "summary.json").write_text('{"ok": false, "plate_size_cm": 20.0}', encoding="utf-8")
    return case


def test_rectify_endpoint_happy_path(tmp_path):
    client = _client(tmp_path)
    case = _case_dir(tmp_path)
    r = client.post("/api/photoscrape/sketch_rectify", json={
        "summary_path": str(case / "summary.json"), "corners_px": _GOOD, "plate_size_cm": 20.0,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["image_url"].startswith("/api/vision/image/")
    assert body["plate_bbox_px"]["w"] == body["plate_bbox_px"]["h"] == 800   # 默认 40px/cm
    assert body["manual_rectify"]["frame_size"] == [800, 800]
    assert (case / "manual_normalized.jpg").is_file()


def test_rectify_endpoint_rejects_bad_order(tmp_path):
    client = _client(tmp_path)
    case = _case_dir(tmp_path)
    bad = [_GOOD[1], _GOOD[0], _GOOD[2], _GOOD[3]]                           # 左右颠倒
    r = client.post("/api/photoscrape/sketch_rectify", json={
        "summary_path": str(case / "summary.json"), "corners_px": bad,
    })
    assert r.status_code == 422 and "左右颠倒" in r.json()["detail"]


def test_rectify_endpoint_404_when_no_backdrop(tmp_path):
    client = _client(tmp_path)
    case = tmp_path / "T2"
    case.mkdir()
    (case / "summary.json").write_text("{}", encoding="utf-8")
    r = client.post("/api/photoscrape/sketch_rectify", json={
        "summary_path": str(case / "summary.json"), "corners_px": _GOOD,
    })
    assert r.status_code == 404


def test_commit_sketch_persists_manual_rectify(tmp_path):
    import json as _json
    from eit_ptlc.config.models import GCodeCfg
    manual = {"plate_corners_px": [[30.0, 20.0], [170.0, 25.0], [165.0, 140.0], [28.0, 135.0]],
              "px_per_cm": 40, "frame_size": [800, 800]}
    res = sp.commit_sketch(
        [(100, 700), (700, 700), (700, 600)], GCodeCfg(), tmp_path,
        plate_size_cm=20.0, plate_bbox_px={"x": 0, "y": 0, "w": 800, "h": 800},
        sample_id="T", manual_rectify=manual,
    )
    doc = _json.loads((tmp_path / "T_manual" / "summary.json").read_text(encoding="utf-8"))
    assert doc["manual_rectify"] == manual


def test_rectify_endpoint_rejects_summary_outside_output_dir(tmp_path):
    # 越界防护: summary_path 在 output_dir 之外 → 422, 且写盘前拦截(旁路目录零落盘)。
    cv2 = pytest.importorskip("cv2")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    client = _client(out_dir)                                # output_dir = tmp/out
    rogue = tmp_path / "rogue"                               # 旁路目录, 不在 output_dir 下
    rogue.mkdir()
    img = np.zeros((160, 200, 3), dtype=np.uint8)
    cv2.fillPoly(img, [np.array(_GOOD, dtype=np.int32)], (255, 255, 255))
    cv2.imwrite(str(rogue / "after_normalized.jpg"), img)
    (rogue / "summary.json").write_text('{"ok": false, "plate_size_cm": 20.0}', encoding="utf-8")
    r = client.post("/api/photoscrape/sketch_rectify", json={
        "summary_path": str(rogue / "summary.json"), "corners_px": _GOOD,
    })
    assert r.status_code == 422 and "不在视觉输出目录" in r.json()["detail"]
    assert not (rogue / "manual_normalized.jpg").exists()    # 越界写已被写盘前拦截


def test_rectify_endpoint_returns_plate_axes(tmp_path):
    case = _case_dir(tmp_path)
    client = _client(tmp_path)
    r = client.post("/api/photoscrape/sketch_rectify", json={
        "summary_path": str(case / "summary.json"), "corners_px": _GOOD, "plate_size_cm": 20.0,
    })
    assert r.status_code == 200
    axes = r.json()["plate_axes"]
    # 矫正帧全幅 bbox: 20cm × 40px/cm 默认 → side=800; 原点=左下 [0,800]
    assert axes["origin_px"] == [0.0, 800.0]
    assert axes["corners"][3]["label"] == "cm(20,20)"


def test_context_endpoint_returns_plate_axes(tmp_path):
    case = tmp_path / "C1"
    case.mkdir()
    (case / "summary.json").write_text(
        '{"plate_bbox_px": {"x": 10, "y": 10, "w": 80, "h": 80}, "plate_size_cm": 5.0}',
        encoding="utf-8")
    client = _client(tmp_path)
    r = client.get("/api/photoscrape/sketch_context",
                   params={"summary_path": str(case / "summary.json")})
    assert r.status_code == 200
    body = r.json()
    assert body["plate_axes"]["origin_px"] == [10.0, 90.0]


def test_context_without_plate_ref_has_no_axes(tmp_path):
    case = tmp_path / "C2"
    case.mkdir()
    (case / "summary.json").write_text('{"ok": false}', encoding="utf-8")
    client = _client(tmp_path)
    r = client.get("/api/photoscrape/sketch_context",
                   params={"summary_path": str(case / "summary.json")})
    assert r.status_code == 200
    assert r.json()["plate_axes"] is None


def test_context_degenerate_bbox_swallows_axes(tmp_path):
    # 退化 bbox(w=0/h=0) 让 plate_axes_annotation 抛 ValueError → 200 且 plate_axes=None,
    # has_plate_ref 仍为 True(有 plate_bbox_px), 前端只是不画轴(不再 500)。
    case = tmp_path / "C3"
    case.mkdir()
    (case / "summary.json").write_text(
        '{"plate_bbox_px": {"x": 0, "y": 0, "w": 0, "h": 80}, "plate_size_cm": 5.0}',
        encoding="utf-8")
    client = _client(tmp_path)
    r = client.get("/api/photoscrape/sketch_context",
                   params={"summary_path": str(case / "summary.json")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plate_axes"] is None
    assert body["has_plate_ref"] is True
