"""刮痕位置测量离线用例 — 合成「已知位移」的刮前/刮后帧, 验算出的 Δ 与建议 plate_origin。

关键钉子:
    1. 已知位移 → 测出的 dx/dy 数值与**方向**正确 (px→cm 的 Y 轴翻转最易搞反)
    2. suggested_plate_origin 的符号随 origin_corner 的 flip 翻转 (唯一真源 _flip_from_corner)
    3. 前置缺失(无刮后帧 / 无 preview_payload) 一律拒绝测量, 不猜
    4. 未真刮(两图相同) 不得因 Otsu 把噪声放大成"检出"
    5. 连通块按**面积**过滤: 毫米级碎屑剔除放行, 与刮痕同量级的第二块照样判不可信
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from eit_ptlc.config.models import GCodeCfg  # noqa: E402
from eit_ptlc.controller.scrape_offset import (  # noqa: E402
    measure_scrape_offset,
    suggest_plate_origin,
)

# 合成帧: 800x800 板占满 (0,0)-(800,800), 20cm 板 → 40 px/cm
_SIZE = 800
_PLATE_BBOX = {"x": 0, "y": 0, "w": _SIZE, "h": _SIZE}
_PLATE_CM = 20.0
_PX_PER_CM = _SIZE / _PLATE_CM


def _cfg(**over) -> GCodeCfg:
    defaults = {"origin_corner": "lower-left", "plate_origin_x": 91.24, "plate_origin_y": -75.2}
    return replace(GCodeCfg(), **{**defaults, **over})


def _write_case(tmp_path: Path, shift_px: tuple[int, int], *, band_y_px: int = 400,
                scraped: bool = True, blobs: tuple[tuple[int, int, int, int], ...] = (),
                extra_left_px: int = 0) -> Path:
    """造一个 case: 指令是一条水平带, 实刮带按 shift_px 平移。返回 summary_path。

    刮前 = 均匀"荧光"底; 刮后 = 在实刮位置挖掉一条(变暗) → 差分即得刮槽。

    参数:
        blobs: 额外的独立变化块 (x0, y0, 宽, 高 px), 用于模拟板面污点/残粉或第二条刮痕。
               ⚠️ 摆位须与刮痕、彼此都留 >13px 间隙 —— 差分掩膜的闭运算核就是 13px,
               贴太近会被桥接成一块, 那测的就不是"多块"了
        extra_left_px: 实刮带的左端额外向左延伸的量(右端不动) —— 模拟"拉伸"而非平移,
               即板框比例失真/刮取中途跳变在测量端的表观(2026-07-27 CALIB-...165445)
    """
    case = tmp_path / "case"
    case.mkdir(parents=True, exist_ok=True)

    band_h = 40                                   # 1 cm 高
    path_x0, path_x1 = 80, 716                    # 指令中心线两端 (range(80, 720, 4) 的首末)
    before = np.full((_SIZE, _SIZE, 3), 180, dtype=np.uint8)
    after = before.copy()
    if scraped:
        y0 = band_y_px + shift_px[1] - band_h // 2
        # 基线实刮带与指令掩膜同跨度: polyline 厚线两端各有半刀宽圆帽 (60..736), 不对齐
        # 的话逐边分解会把"画法差"误读成拉伸
        x0 = path_x0 - band_h // 2 + shift_px[0] - extra_left_px
        x1 = path_x1 + band_h // 2 + shift_px[0]
        after[y0:y0 + band_h, x0:x1] = 40         # 刮掉 → 明显变暗
    for bx, by, bw, bh in blobs:
        after[by:by + bh, bx:bx + bw] = 40
    cv2.imwrite(str(case / "after_normalized.jpg"), before)
    cv2.imwrite(str(case / "scraped_normalized.jpg"), after)

    # 指令路径: 同一条带的中心线, 刀宽 = band_h
    scrape_px = [[float(x), float(band_y_px)] for x in range(path_x0, path_x1 + 4, 4)]
    payload = {
        "band_id": "test_01", "scrape_px": scrape_px, "collect_px": [], "contour_px": [],
        "cutter_width_px": float(band_h),
        "plate_bbox_px": _PLATE_BBOX, "plate_size_cm": _PLATE_CM,
    }
    (case / "preview_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    summary = case / "summary.json"
    summary.write_text(json.dumps({"ok": True}, ensure_ascii=False), encoding="utf-8")
    return summary


# --------------------------------------------------------------------------
# 1) 已知位移 → Δ 数值与方向
# --------------------------------------------------------------------------

def test_pure_y_shift_sign_and_magnitude(tmp_path):
    """实刮比指令偏图像下方 40px = 板 cm 的 −1.0 (图像 y 向下 = cm 变小)。"""
    summary = _write_case(tmp_path, shift_px=(0, 40))
    res = measure_scrape_offset(summary, _cfg())

    assert res["ok"] is True
    assert res["trustworthy"] is True, res["checks"]
    assert res["dx_cm"] == pytest.approx(0.0, abs=0.05)
    assert res["dy_cm"] == pytest.approx(-1.0, abs=0.05)   # ← Y 翻转钉子


def test_pure_x_shift_sign_and_magnitude(tmp_path):
    """实刮比指令偏图像右侧 40px = 板 cm 的 +1.0 (x 同向)。"""
    summary = _write_case(tmp_path, shift_px=(40, 0))
    res = measure_scrape_offset(summary, _cfg())

    assert res["dx_cm"] == pytest.approx(1.0, abs=0.05)
    assert res["dy_cm"] == pytest.approx(0.0, abs=0.05)


def test_zero_shift_gives_zero_delta(tmp_path):
    """指令与实刮重合 → Δ≈0, 且建议值 = 原值 (不引入漂移)。"""
    summary = _write_case(tmp_path, shift_px=(0, 0))
    cfg = _cfg()
    res = measure_scrape_offset(summary, cfg)

    assert abs(res["dx_cm"]) < 0.05
    assert abs(res["dy_cm"]) < 0.05
    assert res["suggested_plate_origin_x"] == pytest.approx(cfg.plate_origin_x, abs=0.5)
    assert res["suggested_plate_origin_y"] == pytest.approx(cfg.plate_origin_y, abs=0.5)


# --------------------------------------------------------------------------
# 2) 建议 plate_origin 的符号 (随 flip 翻转)
# --------------------------------------------------------------------------

def test_suggest_origin_lower_left_subtracts():
    """lower-left: flip=(False,False) → m = o + c*10, 故 o_new = o − Δ*10。"""
    cfg = _cfg()
    ox, oy = suggest_plate_origin(0.3, -0.5, cfg)

    assert ox == pytest.approx(cfg.plate_origin_x - 3.0)
    assert oy == pytest.approx(cfg.plate_origin_y + 5.0)


def test_suggest_origin_top_right_adds():
    """top-right: flip=(True,True) → m = o − c*10, 故 o_new = o + Δ*10 (符号相反)。"""
    cfg = _cfg(origin_corner="top-right")
    ox, oy = suggest_plate_origin(0.3, -0.5, cfg)

    assert ox == pytest.approx(cfg.plate_origin_x + 3.0)
    assert oy == pytest.approx(cfg.plate_origin_y - 5.0)


def test_measured_delta_feeds_suggestion(tmp_path):
    """端到端: 测出的 Δ 与建议值满足 o_new = o − Δ*10 (lower-left)。"""
    summary = _write_case(tmp_path, shift_px=(0, 40))
    cfg = _cfg()
    res = measure_scrape_offset(summary, cfg)

    expect_y = cfg.plate_origin_y - res["dy_cm"] * 10.0
    assert res["suggested_plate_origin_y"] == pytest.approx(expect_y, abs=1e-6)


# --------------------------------------------------------------------------
# 3) 前置缺失一律拒绝 (帧契约未成立时不给数)
# --------------------------------------------------------------------------

def test_missing_scraped_frame_refuses(tmp_path):
    summary = _write_case(tmp_path, shift_px=(0, 0))
    (summary.parent / "scraped_normalized.jpg").unlink()

    with pytest.raises(FileNotFoundError, match="帧契约未成立"):
        measure_scrape_offset(summary, _cfg())


def test_missing_payload_refuses(tmp_path):
    summary = _write_case(tmp_path, shift_px=(0, 0))
    (summary.parent / "preview_payload.json").unlink()

    with pytest.raises(FileNotFoundError, match="preview_payload"):
        measure_scrape_offset(summary, _cfg())


def test_frame_size_mismatch_refuses(tmp_path):
    """刮前/刮后尺寸不一致 = 回放链已破, 必须拒绝而不是缩放凑合。"""
    summary = _write_case(tmp_path, shift_px=(0, 0))
    small = np.full((400, 400, 3), 180, dtype=np.uint8)
    cv2.imwrite(str(summary.parent / "scraped_normalized.jpg"), small)

    with pytest.raises(ValueError, match="尺寸不一致"):
        measure_scrape_offset(summary, _cfg())


# --------------------------------------------------------------------------
# 4) 未真刮 → 不得虚报检出
# --------------------------------------------------------------------------

def test_no_scrape_reports_not_detected(tmp_path):
    """两图相同(未真刮): Otsu 会把噪声切一刀, 阈值下限必须挡住, 报未检出而非给假 Δ。"""
    summary = _write_case(tmp_path, shift_px=(0, 0), scraped=False)
    res = measure_scrape_offset(summary, _cfg())

    assert res["ok"] is False
    assert res["trustworthy"] is False
    assert "未检出刮痕" in res["message"]
    assert "dx_cm" not in res


def test_not_detected_still_renders_overlay(tmp_path):
    """未检出也必须出图 —— 恰恰这一档最需要看现场("为什么没测出来")。

    2026-07-27 CALIB-...101716 的回归钉子: 出图原先排在成功分支末尾, 于是"存疑"有图、
    "未检出"没图, 界面上刮后那栏整个消失, 操作员只能对着一行文字猜。
    """
    summary = _write_case(tmp_path, shift_px=(0, 0), scraped=False)
    res = measure_scrape_offset(summary, _cfg())

    assert res["ok"] is False
    assert res["annotated_name"] == "scrape_offset.png"
    assert (summary.parent / "scrape_offset.png").is_file()


def test_offset_beyond_search_window_not_silently_taken(tmp_path):
    """实刮偏出搜索窗: 不得静默给一个被窗裁过的 Δ; 要么未检出, 要么判据不通过。"""
    summary = _write_case(tmp_path, shift_px=(0, 200), band_y_px=300)   # 偏 5cm >> 窗 1cm
    res = measure_scrape_offset(summary, _cfg(), search_margin_cm=1.0)

    assert res["trustworthy"] is False


# --------------------------------------------------------------------------
# 5) 连通块按面积过滤 (2026-07-26 真机 CALIB-...141119 第2轮误判的回归钉子)
# --------------------------------------------------------------------------
# 现场: 一个 196px(2.1×1.6mm) 的污点绊掉"连通块数==1"硬闸, 整轮作废、放弃写盘;
# 而它对质心的影响只有 0.055mm —— 判据只数块数、对面积不敏感, 是错的代理量。
# 下面同时钉住"该放的放行"与"该拦的照拦", 防修复被做成一味放宽。

# 摆在刮痕**上方**, 使其与 shift=(0,0) 和 (0,40) 两种实刮位置都留足间隙, 且仍在 2cm 搜索窗内
_SPECK = (300, 320, 20, 20)             # 400px, 远小于指令面积的 5%(≈1272px) → 应剔除
_SECOND_GROOVE = (250, 320, 200, 24)    # 4800px, 远大于阈值, 形状也像刮痕 → 必须拦下


def test_tiny_speck_is_filtered_and_round_still_passes(tmp_path):
    """毫米级碎屑不该让整轮作废 —— 剔除后连通块数仍为 1, 判据全过。"""
    summary = _write_case(tmp_path, shift_px=(0, 0), blobs=(_SPECK,))
    res = measure_scrape_offset(summary, _cfg())

    assert res["checks"]["component_count"]["value"] == 1
    assert res["checks"]["component_count"]["pass"] is True
    assert res["trustworthy"] is True, res["checks"]
    assert res["minor_count"] == 1
    assert 0 < res["minor_area_px"] < res["min_component_px"]


def test_speck_does_not_shift_the_measured_delta(tmp_path):
    """碎屑被剔除后不进质心 —— 有无碎屑测出的 Δ 必须一致(否则等于让噪声参与闭环)。"""
    clean = measure_scrape_offset(_write_case(tmp_path / "a", shift_px=(0, 40)), _cfg())
    dirty = measure_scrape_offset(
        _write_case(tmp_path / "b", shift_px=(0, 40), blobs=(_SPECK,)), _cfg())

    assert dirty["dx_cm"] == pytest.approx(clean["dx_cm"], abs=1e-6)
    assert dirty["dy_cm"] == pytest.approx(clean["dy_cm"], abs=1e-6)


def test_real_second_groove_is_not_filtered(tmp_path):
    """与刮痕同量级的第二块**不得**被剔除 —— 原判据意图(拦杂痕/拦刮痕断开)必须保住。"""
    summary = _write_case(tmp_path, shift_px=(0, 0), blobs=(_SECOND_GROOVE,))
    res = measure_scrape_offset(summary, _cfg())

    assert res["checks"]["component_count"]["value"] == 2
    assert res["checks"]["component_count"]["pass"] is False
    assert res["trustworthy"] is False
    assert res["minor_count"] == 0


def test_filtered_specks_count_into_unaccepted_area(tmp_path):
    """剔除不等于不记账: 碎屑面积必须计入 stray_area_px, 否则满板碎屑会静默通过。"""
    summary = _write_case(tmp_path, shift_px=(0, 0), blobs=(_SPECK,))
    res = measure_scrape_offset(summary, _cfg())

    assert res["stray_area_px"] == res["outside_area_px"] + res["minor_area_px"]
    assert res["minor_area_px"] > 0


def test_many_specks_trip_stray_ratio(tmp_path):
    """板面全是碎屑(每块都不足阈值)时, 仍须由 stray_ratio 一条兜住, 不放行。

    搜索窗放到 3cm 才摆得下两排互不桥接的碎屑(窗内净空要够 碎屑+间隙+离刮痕间隙)。
    """
    dirt = tuple((x, y, 20, 20) for x in range(120, 660, 50) for y in (450, 500))
    summary = _write_case(tmp_path, shift_px=(0, 0), blobs=dirt)
    res = measure_scrape_offset(summary, _cfg(), search_margin_cm=3.0)

    assert res["minor_count"] >= 20
    assert res["checks"]["stray_ratio"]["pass"] is False
    assert res["trustworthy"] is False


def test_axis_agreements_decompose_the_combined_check(tmp_path):
    """逐轴分歧与合量判据自洽 —— 面板拿逐轴数提示"哪个轴不能信", 不能与判据对不上。"""
    summary = _write_case(tmp_path, shift_px=(20, 40))
    res = measure_scrape_offset(summary, _cfg())

    combined = res["checks"]["centroid_agreement_cm"]["value"]
    assert float(np.hypot(res["dx_agree_cm"], res["dy_agree_cm"])) == pytest.approx(
        combined, abs=5e-4)
    assert res["dx_agree_cm"] == pytest.approx(abs(res["dx_cm"] - res["bbox_dx_cm"]), abs=1e-6)
    assert res["dy_agree_cm"] == pytest.approx(abs(res["dy_cm"] - res["bbox_dy_cm"]), abs=1e-6)


# --------------------------------------------------------------------------
# 6) 拉伸指纹 (2026-07-27 真机 CALIB-...165445 的回归钉子)
# --------------------------------------------------------------------------
# 现场: 板框左边被照明削 ~11mm → x 比例低估 6%, 卡尺实测 80.0mm 的图案被"测成" ~86mm。
# 关键盲区: 对称图形整体拉伸时, 质心Δ 与 bbox中心Δ 一致地各偏一半, centroid_agreement
# 拦不住 —— 只有逐边分解(左右端偏移不等)能显影。当时靠人工比对两端才定位, 此处自动化。


def test_pure_shift_has_zero_stretch(tmp_path):
    """纯平移: 四边同偏, 宽/高差必须为零 —— 拉伸指纹不得把正常平移误报成失真。"""
    summary = _write_case(tmp_path, shift_px=(40, 40))
    res = measure_scrape_offset(summary, _cfg())

    assert res["stretch_x_cm"] == pytest.approx(0.0, abs=0.05)
    assert res["stretch_y_cm"] == pytest.approx(0.0, abs=0.05)
    assert res["dx_left_cm"] == pytest.approx(res["dx_right_cm"], abs=0.05)
    assert "拉伸" not in res["message"]


def test_left_stretch_reports_fingerprint_with_edge_decomposition(tmp_path):
    """左端多出 1cm(右端不动) → stretch_x=+1.0, 逐边偏移分解正确, 消息给出指纹。"""
    summary = _write_case(tmp_path, shift_px=(0, 0), extra_left_px=40)
    res = measure_scrape_offset(summary, _cfg())

    assert res["stretch_x_cm"] == pytest.approx(1.0, abs=0.08)
    assert res["dx_left_cm"] == pytest.approx(-1.0, abs=0.08)
    assert res["dx_right_cm"] == pytest.approx(0.0, abs=0.08)
    assert res["stretch_y_cm"] == pytest.approx(0.0, abs=0.05)
    assert "拉伸" in res["message"]
    assert "不宜采纳" in res["message"]


def test_symmetric_band_stretch_evades_centroid_agreement(tmp_path):
    """钉住盲区本身: 对称带纯拉伸时 centroid_agreement 照常通过 —— 这正是拉伸指纹存在的
    理由; 若未来该判据变得能拦拉伸, 此用例提醒重新评估指纹是否还需要。"""
    summary = _write_case(tmp_path, shift_px=(0, 0), extra_left_px=40)
    res = measure_scrape_offset(summary, _cfg())

    assert res["checks"]["centroid_agreement_cm"]["pass"] is True
    # 质心与 bbox 中心各偏拉伸量的一半, 两个估计器"一致地错" —— 合量判据看不见
    assert res["dx_cm"] == pytest.approx(-0.5, abs=0.08)
    assert res["bbox_dx_cm"] == pytest.approx(-0.5, abs=0.08)
