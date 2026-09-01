"""固定刮取路径脚本离线测试 — 证明 (x0,y0,w,h) → 与视觉/手绘同契约的 summary,
且被**未改动的** cnc_path.generate_scrape_arrays 消费得到非退化 400 点路径。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller.cnc_path import SCRAPE_POINT_COUNT, generate_scrape_arrays
from eit_ptlc.tools import fixed_scrape_path as fsp


def test_build_fixed_contour_cm_is_rectangle():
    c = fsp.build_fixed_contour_cm(3.0, 4.0, 10.0, 5.0)
    assert c == [(3.0, 4.0), (13.0, 4.0), (13.0, 9.0), (3.0, 9.0)]


def test_write_fixed_summary_contract(tmp_path):
    summary_path = fsp.write_fixed_summary(3.0, 4.0, 10.0, 5.0, tmp_path, band_id="fixed_01")
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert [b["band_id"] for b in summary["bands"]] == ["fixed_01"]
    path_json = summary_path.parent / "fixed_01_path.json"
    assert path_json.is_file()
    doc = json.loads(path_json.read_text(encoding="utf-8"))
    bbox = doc["scrape_path"]["bbox_cm"]
    assert (bbox["x_min"], bbox["y_min"], bbox["x_max"], bbox["y_max"]) == (3.0, 4.0, 13.0, 9.0)
    assert len(doc["contour_cm"]) == 4


def test_summary_feeds_cnc_path_400_points(tmp_path):
    summary_path = fsp.write_fixed_summary(3.0, 4.0, 10.0, 5.0, tmp_path, band_id="fixed_01")
    arr = generate_scrape_arrays(summary_path, "fixed_01", GCodeCfg())
    assert len(arr.g_sx) == SCRAPE_POINT_COUNT == 400
    assert arr.pass_count >= 1
    # 非退化: 刮取点在 X 上有真实展开(不是全 collapse 到一点)
    assert max(arr.g_sx) - min(arr.g_sx) > 1.0


def test_main_prints_summary_path_and_preview(tmp_path, capsys):
    rc = fsp.main(["--x0", "3", "--y0", "4", "--w", "10", "--h", "5",
                   "--out", str(tmp_path), "--band-id", "fixed_01", "--preview"])
    assert rc == 0
    out = capsys.readouterr().out
    # write_fixed_summary 返回 .resolve() 后的绝对路径, 断言也用 resolve 防 Windows 路径规范化差异
    assert f"summary_path={(tmp_path / 'summary.json').resolve()}" in out
    assert "band_id=fixed_01" in out
    assert "preview pass_count=" in out
    assert "point_count=400" in out


@pytest.mark.parametrize("w,h", [(0.0, 5.0), (10.0, -1.0), (-3.0, -2.0)])
def test_main_rejects_non_positive_dimensions(tmp_path, w, h):
    # 非正尺寸 = 退化矩形, 应快速失败(argparse error → SystemExit), 不落盘。
    with pytest.raises(SystemExit):
        fsp.main(["--x0", "3", "--y0", "4", "--w", str(w), "--h", str(h), "--out", str(tmp_path)])
    assert not (tmp_path / "summary.json").exists()
