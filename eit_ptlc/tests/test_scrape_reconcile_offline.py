"""刮后对账叠加 — 帧回放 + payload 同源渲染 + 全链 fail-safe。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from eit_ptlc.controller.scrape_reconcile import render_scraped_overlay


def _case(tmp_path: Path, *, with_applied=True, with_payload=True) -> tuple[Path, Path]:
    """最小 case 目录: summary(+normalize_applied) + preview_payload.json + 原始 scraped.jpg。"""
    summary = {"ok": True, "bands": []}
    if with_applied:
        summary["normalize_applied"] = {"orientation": "rot0", "tilt_deg": 0.0,
                                        "rotation_center": "image_center",
                                        "frame_size": [200, 160]}
    sp = tmp_path / "summary.json"
    sp.write_text(json.dumps(summary), encoding="utf-8")
    if with_payload:
        payload = {"scrape_px": [[20, 80], [180, 80]], "collect_px": [], "contour_px": [],
                   "cutter_width_px": 0.0,
                   "plate_bbox_px": {"x": 10, "y": 10, "w": 180, "h": 140},
                   "plate_size_cm": 20.0}
        (tmp_path / "preview_payload.json").write_text(json.dumps(payload), encoding="utf-8")
    scraped = tmp_path / "scraped.jpg"
    cv2.imwrite(str(scraped), np.zeros((160, 200, 3), dtype=np.uint8))
    return sp, scraped


def test_happy_path_writes_normalized_and_annotated(tmp_path):
    sp, scraped = _case(tmp_path)
    res = render_scraped_overlay(sp, scraped, image_root=tmp_path)
    assert res["ok"] is True
    assert (tmp_path / "scraped_normalized.jpg").is_file()
    assert (tmp_path / "scraped_annotated.png").is_file()
    assert res["annotated_url"].startswith("/api/vision/image/")


def test_missing_normalize_applied_failsafe(tmp_path):
    sp, scraped = _case(tmp_path, with_applied=False)
    res = render_scraped_overlay(sp, scraped, image_root=tmp_path)
    assert res["ok"] is False and "normalize_applied" in res["message"]
    assert not (tmp_path / "scraped_annotated.png").exists()   # 宁可无图不可错帧


def test_missing_payload_failsafe(tmp_path):
    sp, scraped = _case(tmp_path, with_payload=False)
    res = render_scraped_overlay(sp, scraped, image_root=tmp_path)
    assert res["ok"] is False and "preview_payload" in res["message"]


def test_action_wrapper_never_raises(tmp_path):
    import asyncio
    from eit_ptlc.controller.scrape_reconcile import ScrapeReconcileController
    ctrl = ScrapeReconcileController(lambda: tmp_path)
    res = asyncio.run(ctrl.scraped_overlay(summary_path="", scraped_path=""))
    assert res["ok"] is False
