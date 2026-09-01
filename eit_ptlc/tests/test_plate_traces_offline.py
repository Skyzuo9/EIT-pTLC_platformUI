"""板面痕迹取数(/api/3d/plate-traces)的离线测试.

盯两件事:
  1. `_collect_plate_traces` 把视觉 case 目录的既有产物(preview_payload / summary /
     band_XX_path)汇总成板 cm 帧的痕迹事实 —— px→cm 走 plate_coords 单一真源;
  2. 样品号白名单(直接拼路径, 目录穿越必须在入口拦死)。
"""

from __future__ import annotations

import json

from eit_ptlc.api.three_d_routes import _SAMPLE_ID_RE, _collect_plate_traces


def _write_case(tmp_path, *, with_payload=True, with_summary=True):
    case = tmp_path / "TEST-XX-001"
    contours = case / "task1_task2_contours_paths"
    contours.mkdir(parents=True)
    if with_payload:
        # 板框 1000px 铺 20cm ⇒ 1px = 0.02cm; 刀宽 10px = 0.2cm
        (case / "preview_payload.json").write_text(json.dumps({
            "plate_size_cm": 20.0,
            "plate_bbox_px": {"x": 100, "y": 50, "w": 1000, "h": 1000},
            "scrape_px": [[100, 1050], [1100, 1050], [1100, 50]],
            "cutter_width_px": 10.0,
            "pass_count": 2,
        }), encoding="utf-8")
    if with_summary:
        (case / "summary.json").write_text(json.dumps({
            "bands": [
                {"band_id": "band_00_origin", "is_origin": True,
                 "path_json": "vision_output\\TEST-XX-001\\task1_task2_contours_paths\\band_00_origin_path.json"},
                {"band_id": "band_01", "is_origin": False,
                 "path_json": "vision_output\\TEST-XX-001\\task1_task2_contours_paths\\band_01_path.json"},
            ],
            "solvent_front": {"y_cm": 14.72},
        }), encoding="utf-8")
        (contours / "band_00_origin_path.json").write_text(json.dumps({
            "scrape_path": {"bbox_cm": {"x_min": 1.0, "y_min": 2.3, "x_max": 19.0, "y_max": 3.2}},
        }), encoding="utf-8")
        (contours / "band_01_path.json").write_text(json.dumps({
            "scrape_path": {"bbox_cm": {"x_min": 1.0, "y_min": 5.4, "x_max": 19.2, "y_max": 7.5}},
        }), encoding="utf-8")
    return case


def test_collect_traces_full_case(tmp_path):
    facts = _collect_plate_traces(_write_case(tmp_path))
    assert facts["found"] is True
    assert facts["plateSizeCm"] == [20.0, 20.0]
    # px→cm: 板框左下角(100, 1050) → (0, 0); 右下(1100, 1050) → (20, 0); 右上 → (20, 20)
    assert facts["scrapePolylineCm"] == [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0]]
    assert facts["cutterWidthCm"] == 0.2
    assert facts["passCount"] == 2
    # 谱带 bbox 从逐带 path_json 的 scrape_path.bbox_cm 取, 顺序保持
    assert facts["bandsCm"] == [[1.0, 2.3, 19.0, 3.2], [1.0, 5.4, 19.2, 7.5]]
    assert facts["solventFrontYCm"] == 14.72


def test_collect_traces_partial_and_empty(tmp_path):
    # 只有 summary(还没算刀路): 谱带可用, found 仍为真
    only_summary = _collect_plate_traces(_write_case(tmp_path, with_payload=False))
    assert only_summary["found"] is True
    assert "scrapePolylineCm" not in only_summary
    assert len(only_summary["bandsCm"]) == 2

    # 空目录: found=false(痕迹缺失不是错误)
    empty = tmp_path / "EMPTY-001"
    empty.mkdir()
    assert _collect_plate_traces(empty) == {"found": False}


def test_band_path_anchored_to_case_dir(tmp_path):
    """path_json 里的历史相对路径只取文件名锚回 case 目录 —— 旧记录里的路径不许把读取带出去。"""
    case = _write_case(tmp_path)
    summary = json.loads((case / "summary.json").read_text(encoding="utf-8"))
    summary["bands"][0]["path_json"] = "..\\..\\..\\etc\\evil.json"
    (case / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    facts = _collect_plate_traces(case)
    # 越界条目按文件不存在跳过, 其余照常
    assert facts["bandsCm"] == [[1.0, 5.4, 19.2, 7.5]]


def test_sample_id_whitelist():
    assert _SAMPLE_ID_RE.match("TEST-PS-001")
    assert _SAMPLE_ID_RE.match("S_01.a")
    assert not _SAMPLE_ID_RE.match("../evil")
    assert not _SAMPLE_ID_RE.match("a/b")
    assert not _SAMPLE_ID_RE.match("")
    assert not _SAMPLE_ID_RE.match("x" * 129)
