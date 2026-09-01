from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller.cnc_path import CncPathController
from eit_ptlc.controller.cnc_preview import preview_payload_from_arrays


def _case(root: Path) -> Path:
    case = root / "S1"
    case.mkdir(parents=True)
    contour = [
        {"x_cm": 2.0, "y_cm": 6.0},
        {"x_cm": 18.0, "y_cm": 6.0},
        {"x_cm": 18.0, "y_cm": 8.0},
        {"x_cm": 2.0, "y_cm": 8.0},
    ]
    (case / "band_01_path.json").write_text(json.dumps({
        "scrape_path": {"bbox_cm": {
            "x_min": 2.0, "y_min": 6.0, "x_max": 18.0, "y_max": 8.0,
        }},
        "contour_cm": contour,
    }), encoding="utf-8")
    summary = case / "summary.json"
    summary.write_text(json.dumps({
        "plate_bbox_px": {"x": 10, "y": 10, "w": 200, "h": 200},
        "plate_size_cm": 20.0,
        "bands": [{"band_id": "band_01", "path_json": "band_01_path.json"}],
    }), encoding="utf-8")
    Image.new("RGB", (220, 220), (20, 90, 30)).save(case / "after_normalized.jpg")
    return summary


def test_controller_preview_uses_returned_execution_arrays(tmp_path):
    root = tmp_path / "vision"
    summary = _case(root)
    cfg = GCodeCfg(path_strategy="contour")
    controller = CncPathController(lambda: cfg, image_root_provider=lambda: root)

    result = asyncio.run(controller.generate_cnc_path(str(summary), "band_01"))

    assert result["preview_available"] is True
    assert result["preview_url"] == "/api/vision/image/S1/band_01_cnc_preview.png"
    assert (root / "S1" / "band_01_cnc_preview.png").is_file()
    assert result["point_count"] == 400
    assert len(result["g_sx"]) == len(result["g_sy"]) == 400
    assert len(result["g_cx"]) == len(result["g_cy"]) == 400

    arrays = SimpleNamespace(
        g_sx=result["g_sx"], g_sy=result["g_sy"],
        g_cx=result["g_cx"], g_cy=result["g_cy"],
        g_scrape_feed=result["g_scrape_feed"], pass_count=result["pass_count"],
        pass_z_list=result["pass_z_list"],
    )
    preview = preview_payload_from_arrays(summary, "band_01", arrays, cfg)
    assert len(preview["scrape_px"]) == 400
    assert len(preview["collect_px"]) == 400
    assert preview["point_count"] == result["point_count"]


def test_preview_payload_includes_cutter_width(tmp_path):
    """payload 带 cutter_width_px = 刀径(cm)/板尺(cm)×板宽(px): 2mm/20cm×200px = 2.0px。"""
    root = tmp_path / "vision"
    summary = _case(root)
    cfg = GCodeCfg(path_strategy="contour")
    controller = CncPathController(lambda: cfg, image_root_provider=lambda: root)
    result = asyncio.run(controller.generate_cnc_path(str(summary), "band_01"))
    arrays = SimpleNamespace(
        g_sx=result["g_sx"], g_sy=result["g_sy"],
        g_cx=result["g_cx"], g_cy=result["g_cy"],
        g_scrape_feed=result["g_scrape_feed"], pass_count=result["pass_count"],
        pass_z_list=result["pass_z_list"],
    )
    preview = preview_payload_from_arrays(summary, "band_01", arrays, cfg)
    assert abs(preview["cutter_width_px"] - 2.0) < 1e-6
    # 渲染路径(controller 内部已带 swath 分支)不炸且出图: 上面 result 已断言过 preview_available
    assert result["preview_available"] is True


def test_payload_carries_plate_ref_fields(tmp_path):
    from eit_ptlc.controller.sketch_path import write_manual_summary
    from eit_ptlc.controller.cnc_path import generate_scrape_arrays
    from eit_ptlc.config.models import GCodeCfg
    cfg = GCodeCfg()
    summary = write_manual_summary(
        [(2.0, 4.0), (18.0, 4.0), (18.0, 6.0), (2.0, 6.0)], tmp_path,
        plate_bbox_px={"x": 0, "y": 0, "w": 400, "h": 400},
    )
    arrays = generate_scrape_arrays(summary, "manual_01", cfg)
    payload = preview_payload_from_arrays(summary, "manual_01", arrays, cfg)
    assert payload["plate_bbox_px"] == {"x": 0, "y": 0, "w": 400, "h": 400}
    assert payload["plate_size_cm"] == 20.0


def test_render_overlay_draws_plate_frame_annotation(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    from eit_ptlc.controller.cnc_preview import render_cnc_overlay
    backdrop = tmp_path / "after_normalized.jpg"
    cv2.imwrite(str(backdrop), np.zeros((400, 400, 3), dtype=np.uint8))
    payload = {"scrape_px": [[50, 50], [350, 50]], "collect_px": [], "contour_px": [],
               "cutter_width_px": 0.0,
               "plate_bbox_px": {"x": 20, "y": 20, "w": 360, "h": 360},
               "plate_size_cm": 20.0}
    out = tmp_path / "overlay.png"
    assert render_cnc_overlay(backdrop, payload, out)
    img = cv2.imread(str(out))
    # 原点角 cm(0,0) = bbox 左下 (20, 380) 附近应出现黄色标注像素 (B,G,R)=(0,255,255)
    patch = img[340:400, 0:80]
    yellow = (patch[:, :, 1] > 200) & (patch[:, :, 2] > 200) & (patch[:, :, 0] < 80)
    assert int(yellow.sum()) > 20


def test_cnc_path_action_persists_payload(tmp_path):
    import asyncio, json as _json
    from eit_ptlc.controller.sketch_path import write_manual_summary
    from eit_ptlc.controller.cnc_path import CncPathController
    from eit_ptlc.config.models import GCodeCfg
    summary = write_manual_summary(
        [(2.0, 4.0), (18.0, 4.0), (18.0, 6.0), (2.0, 6.0)], tmp_path,
        plate_bbox_px={"x": 0, "y": 0, "w": 400, "h": 400},
    )
    ctrl = CncPathController(lambda: GCodeCfg())
    result = asyncio.run(ctrl.generate_cnc_path(str(summary), "manual_01"))
    payload_path = tmp_path / "preview_payload.json"
    assert payload_path.is_file()                      # 无 backdrop 也要落 payload
    doc = _json.loads(payload_path.read_text(encoding="utf-8"))
    assert doc["band_id"] == "manual_01" and "plate_bbox_px" in doc
    assert result["preview_payload_path"] == str(payload_path)


def test_cnc_path_stale_payload_invalidated_on_failed_preview(tmp_path):
    """C-5 同代性: 前任成功落 payload → 本轮 summary 无 plate_bbox_px(矫正回落老路手绘) →
    preview_payload_from_arrays 抛 KeyError 被外层 except 吞, 但陈旧 payload 已在数组生成前
    被先行 unlink 且未被重写 → 文件不存在。对账宁可无图, 绝不用旧 payload 配新 summary 错帧。"""
    import asyncio
    from eit_ptlc.controller.sketch_path import write_manual_summary
    from eit_ptlc.controller.cnc_path import CncPathController
    from eit_ptlc.config.models import GCodeCfg

    contour = [(2.0, 4.0), (18.0, 4.0), (18.0, 6.0), (2.0, 6.0)]
    ctrl = CncPathController(lambda: GCodeCfg())

    # 第一版: 带 plate_bbox_px → payload 成功落盘(前任候选)
    summary = write_manual_summary(
        contour, tmp_path,
        plate_bbox_px={"x": 0, "y": 0, "w": 400, "h": 400},
    )
    asyncio.run(ctrl.generate_cnc_path(str(summary), "manual_01"))
    payload_path = tmp_path / "preview_payload.json"
    assert payload_path.is_file()                      # 前任 payload 已落盘

    # 第二版: 无 plate_bbox_px(矫正回落老路手绘 summary), 覆写同一 summary.json
    write_manual_summary(contour, tmp_path)            # 不带 plate_bbox_px
    result = asyncio.run(ctrl.generate_cnc_path(str(summary), "manual_01"))

    # 动作本身成功(返回真机数组), 但 payload 写入内部失败(无 plate_bbox_px)被吞
    assert result["point_count"] == 400
    assert result["preview_available"] is False
    # 陈旧 payload 已先行失效且未被重写 → 不存在(宁可无图不可错帧)
    assert not payload_path.exists()

