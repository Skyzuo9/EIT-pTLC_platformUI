"""标定图案几何 + 逐轮工作区离线用例。

关键钉子:
    1. 三轮图案互不重叠且间距够 —— 重叠会让第二轮差分只剩细月牙, 测不出来
    2. 均偏离板中心 —— 居中图案对 origin_corner 镜像错误不变, 检不出来
    3. 均远离 y=0 点样边 —— 那里有 machine_y_min_mm 截平钳制, 会被误读成偏移
    4. 基准帧按轮次正确切换 (r1=视觉空白帧, r2=r1 的刮后帧)
    5. 视觉 case 缺 normalize_applied/plate_bbox_px → 当场拒绝, 不留哑弹工作区
    6. L 形三要素: 单 pass 行程不超停滞预算 / 扫掠实心且列距达标 / x 向可观测性不退化
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from eit_ptlc.controller.scrape_calib import (
    CALIB_BAND_ID,
    MAX_ROUND,
    base_frame_path,
    build_round_workspace,
    pattern_contour_cm,
    workspace_dir,
)

_PLATE_CM = 20.0
_NORMALIZE = {"orientation": "rot0", "tilt_deg": -2.43,
              "rotation_center": "image_center", "frame_size": [800, 800]}


def _bbox(contour):
    xs = [p[0] for p in contour]
    ys = [p[1] for p in contour]
    return min(xs), min(ys), max(xs), max(ys)


def _seed_vision_case(root: Path, sample_id: str, *, normalize=True, bbox=True,
                      bbox_wh: tuple[int, int] = (800, 800)) -> Path:
    """造一个视觉 case: summary.json + after_normalized.jpg(空白板归一化帧)。"""
    case = root / sample_id
    case.mkdir(parents=True, exist_ok=True)
    doc = {"ok": True, "plate_size_cm": _PLATE_CM}
    if bbox:
        doc["plate_bbox_px"] = {"x": 0, "y": 0, "w": bbox_wh[0], "h": bbox_wh[1]}
    if normalize:
        doc["normalize_applied"] = _NORMALIZE
    (case / "summary.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (case / "after_normalized.jpg").write_bytes(b"BLANK-PLATE-FRAME")
    return case


# --------------------------------------------------------------------------
# 1) 图案几何
# --------------------------------------------------------------------------

def test_all_patterns_inside_plate_and_away_from_sampling_edge():
    """全部落在板内, 且下沿离 y=0 点样边 ≥3cm (避开 machine_y_min_mm 截平钳制区)。"""
    for r in range(1, MAX_ROUND + 1):
        x0, y0, x1, y1 = _bbox(pattern_contour_cm(r))
        assert 0 < x0 < x1 < _PLATE_CM, f"轮{r} X 越板: {x0}..{x1}"
        assert 0 < y0 < y1 < _PLATE_CM, f"轮{r} Y 越板: {y0}..{y1}"
        assert y0 >= 3.0, f"轮{r} 下沿 {y0}cm 离点样边过近, 会撞上 Y 软下限钳制"


def test_patterns_are_off_center():
    """图案质心不得落在板中心 —— 居中图案对 origin_corner 镜像错误不变, 检不出来。"""
    center = _PLATE_CM / 2.0
    for r in range(1, MAX_ROUND + 1):
        x0, y0, x1, y1 = _bbox(pattern_contour_cm(r))
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        assert abs(cx - center) > 1.0 or abs(cy - center) > 1.0, f"轮{r} 质心过于居中"


def test_consecutive_rounds_do_not_overlap():
    """相邻轮次图案必须完全不重叠 —— 重叠则第二轮差分只剩细月牙, 检出垃圾。"""
    for r in range(1, MAX_ROUND):
        ax0, ay0, ax1, ay1 = _bbox(pattern_contour_cm(r))
        bx0, by0, bx1, by1 = _bbox(pattern_contour_cm(r + 1))
        separated = ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0
        assert separated, f"轮{r} 与轮{r + 1} 图案重叠"


def test_consecutive_rounds_gap_clears_search_window():
    """相邻轮次间距必须大于测量的默认搜索窗 (2cm), 否则旧痕会落进新轮的窗内被算进质心。

    这是第二道保险 —— 第一道是"第 N 轮用第 N−1 轮的刮后帧当差分基准", 旧痕在前后两帧
    都存在会被差分抵消。两道都要, 因为基准帧一旦缺失(上轮对账失败)就只剩位置隔离兜底。
    """
    search_margin_cm = 2.0
    for r in range(1, MAX_ROUND):
        ax0, ay0, ax1, ay1 = _bbox(pattern_contour_cm(r))
        bx0, by0, bx1, by1 = _bbox(pattern_contour_cm(r + 1))
        gap = max(bx0 - ax1, ax0 - bx1, by0 - ay1, ay0 - by1)
        assert gap > search_margin_cm, (
            f"轮{r}→{r + 1} 间距 {gap}cm 未超搜索窗 {search_margin_cm}cm, 旧痕会被吃进新轮质心")


def test_round_out_of_range_rejected():
    with pytest.raises(ValueError, match="轮次"):
        pattern_contour_cm(0)
    with pytest.raises(ValueError, match="轮次"):
        pattern_contour_cm(MAX_ROUND + 1)


# --------------------------------------------------------------------------
# 1b) 单 pass 行程上限 —— 2026-07-26 真机教训的回归钉子
# --------------------------------------------------------------------------

def test_pattern_path_fits_within_stall_timeout():
    """每轮图案的单 pass 总行程必须能在 photoscrape.scrape 的 stall_timeout 内跑完。

    背景: 首次真机标定用 4×4cm 方块, 收集路径 13480mm / 全程 18.8min, 远超当时的 300s 预算,
    动作会被误判"结果不明确"而 fail-fast。**收集路径 ∝ y 高度**(拖尾沿 x, 每 y 层拖一次),
    缩宽度几乎无效 —— 所以图案必须"宽而扁"。本用例把这条钉死, 改图案/进给后自动复核。
    """
    import math
    import tempfile

    from eit_ptlc.config.loader import load_config
    from eit_ptlc.controller.cnc_path import generate_scrape_arrays
    from eit_ptlc.controller.sketch_path import write_manual_summary

    cfg = load_config(Path("eit_ptlc/config/app.yaml")).gcode
    actions = yaml.safe_load(
        Path("eit_ptlc/config/actions/04_photoscrape/plc_photoscrape.yaml").read_text(
            encoding="utf-8"))
    stall_s = float(actions["photoscrape.scrape"]["stall_timeout"])
    feed_mm_min = float(cfg.scrape.feed_rate)
    budget_mm = feed_mm_min * stall_s / 60.0

    def _plen(xs, ys):
        return sum(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(len(xs) - 1))

    for r in range(1, MAX_ROUND + 1):
        with tempfile.TemporaryDirectory() as td:
            summary = write_manual_summary(pattern_contour_cm(r), Path(td), band_id="t")
            arr = generate_scrape_arrays(summary, "t", cfg)
        total = _plen(arr.g_sx, arr.g_sy) + _plen(arr.g_cx, arr.g_cy)
        # 留 25% 余量: feed 是指令值, 真机含加减速与拐角降速, 实测会比理论慢
        assert total <= budget_mm * 0.75, (
            f"轮{r} 单 pass 行程 {total:.0f}mm 超预算 {budget_mm * 0.75:.0f}mm "
            f"(stall_timeout={stall_s}s @feed {feed_mm_min}) — 把图案改扁(降 y 高度)或调大 stall_timeout")


# --------------------------------------------------------------------------
# 1c) L 形几何 —— 2026-07-26 第二轮复盘的回归钉子
# --------------------------------------------------------------------------
# 扁带在 x 方向几何欠定(沿带长挪 2.8mm 只掉 2.5% 重叠), 换估计器救不了, 只能靠形状。
# 下面三条把 L 形的三个前提钉死: 是 L / 刮得实 / x 真能观测。

_PPM = 8.485        # px/mm, 取真机 CALIB-...141119 实测的 px_per_cm=84.85
_SHIFT_MM = 2.8     # 与真机取证同口径的位移量


def _swept_mask(round_no: int):
    """把某轮图案的刮取路径按刀宽渲成扫掠掩膜, 并返回 (掩膜, 各列 x 的最大间距 mm)。

    画法与 scrape_offset._commanded_mask 一致(polylines + cutter_width), 故这里量到的
    实心度/连通性就是测量端将看到的。
    """
    import tempfile

    import cv2
    import numpy as np

    from eit_ptlc.config.loader import load_config
    from eit_ptlc.controller.cnc_path import generate_scrape_arrays
    from eit_ptlc.controller.sketch_path import write_manual_summary

    cfg = load_config(Path("eit_ptlc/config/app.yaml")).gcode
    with tempfile.TemporaryDirectory() as td:
        summary = write_manual_summary(pattern_contour_cm(round_no), Path(td), band_id="t")
        arr = generate_scrape_arrays(summary, "t", cfg)

    xs, ys = np.asarray(arr.g_sx), np.asarray(arr.g_sy)
    ox, oy = xs.min() - 8, ys.min() - 8
    pts = np.stack([(xs - ox) * _PPM, (ys - oy) * _PPM], 1).round().astype(np.int32)
    # np.ptp(arr) 而非 arr.ptp() —— ndarray.ptp 方法在 NumPy 2.0 已移除
    mask = np.zeros((int((np.ptp(ys) + 16) * _PPM), int((np.ptp(xs) + 16) * _PPM)), np.uint8)
    cv2.polylines(mask, [pts], False, 255,
                  max(1, int(round(cfg.tool.cutter_diameter_mm * _PPM))), cv2.LINE_8)
    col_gap = float(np.diff(np.unique(np.round(xs, 2))).max())
    return mask, col_gap, cfg


def test_pattern_is_L_shaped_not_a_bar():
    """图案必须是 L(6 点), 不是矩形 —— 竖笔是 x 向可观测性的唯一来源, 丢了就退回欠定。"""
    for r in range(1, MAX_ROUND + 1):
        contour = pattern_contour_cm(r)
        assert len(contour) == 6, f"轮{r} 不是 L 形(应 6 个角), 得到 {len(contour)} 点"
        x0, y0, x1, y1 = _bbox(contour)
        # 矩形的四角会填满 bbox; L 缺一角, 故必有某个 bbox 角不在轮廓上
        corners = {(x0, y0), (x1, y0), (x1, y1), (x0, y1)}
        assert corners - set(contour), f"轮{r} 轮廓填满了 bbox 四角, 实为矩形"


def test_swept_area_is_solid_and_column_pitch_covers():
    """扫掠必须实心单连通, 且列距 ≤ 刀宽×(1−重叠) —— 否则刮成断续梳齿, 连通块判据必挂。

    覆盖的唯一约束是**列距**: 路径沿 X 分列、列内在 Y 上连续往返, 列内点距只是直线上的
    路点密度。这条在 2026-07-26 定 L 形时实测确认过, 此处钉成回归。
    """
    import cv2

    for r in range(1, MAX_ROUND + 1):
        mask, col_gap, cfg = _swept_mask(r)
        limit = cfg.tool.cutter_diameter_mm * (1.0 - cfg.scrape.overlap_ratio)
        n_comp = int(cv2.connectedComponents(mask)[0]) - 1
        assert n_comp == 1, f"轮{r} 扫掠区裂成 {n_comp} 块, 刮出来会是断续的"
        assert col_gap <= limit * 1.01, (
            f"轮{r} 最大列距 {col_gap:.3f}mm 超过刀宽有效步距 {limit:.2f}mm, 相邻列之间会漏刮")


def test_x_observability_floor():
    """x 向的定位能力不得再退回扁带水平 —— 位移 2.8mm 时 x 的重叠损失须 ≥ y 损失的 1/4。

    ⚠️ 这条是防"为省时间把图案改回宽扁带"的钉子。扁带 8×0.6 的实测比值只有 0.11
    (x 损 5.1% / y 损 46.2%), 现役 L 形是 0.30 —— 阈值 0.25 恰好把两者分开。
    x 欠定的后果是 dx 的估计歧义大于 dx 本身, 等于在噪声上闭环。
    """
    import cv2
    import numpy as np

    d = int(round(_SHIFT_MM * _PPM))
    for r in range(1, MAX_ROUND + 1):
        mask, _gap, _cfg = _swept_mask(r)
        area = cv2.countNonZero(mask)

        def keep(dx, dy, m=mask, a=area):
            moved = cv2.warpAffine(m, np.float32([[1, 0, dx], [0, 1, dy]]),
                                   (m.shape[1], m.shape[0]))
            return cv2.countNonZero(cv2.bitwise_and(moved, m)) / a

        loss_x = 1.0 - keep(d, 0)
        loss_y = 1.0 - keep(0, d)
        assert loss_x >= loss_y * 0.25, (
            f"轮{r} x 向可观测性不足: 位移 {_SHIFT_MM}mm 时 x 只损失 {loss_x:.1%} 而 y 损失 "
            f"{loss_y:.1%} (比值 {loss_x / loss_y:.2f} < 0.25) — 图案太扁, dx 测不准")


# --------------------------------------------------------------------------
# 2) 基准帧按轮次切换 (本模块存在的理由)
# --------------------------------------------------------------------------

def test_base_frame_round1_is_vision_blank_frame(tmp_path):
    p = base_frame_path(tmp_path, "S1", 1)
    assert p == tmp_path / "S1" / "after_normalized.jpg"


def test_base_frame_round2_is_previous_scraped_frame(tmp_path):
    """轮2 基准 = 轮1 刮后帧 —— 旧痕在前后两帧都在, 差分抵消, 只留本轮新痕。"""
    p = base_frame_path(tmp_path, "S1", 2)
    assert p == workspace_dir(tmp_path, "S1", 1) / "scraped_normalized.jpg"


# --------------------------------------------------------------------------
# 3) 工作区构造
# --------------------------------------------------------------------------

def test_round1_workspace_inherits_frame_contract(tmp_path):
    """工作区 summary 必须带 plate_bbox_px + normalize_applied, 否则刮后测不了。"""
    _seed_vision_case(tmp_path, "S1")
    res = build_round_workspace(tmp_path, "S1", 1)

    doc = json.loads(Path(res["summary_path"]).read_text(encoding="utf-8"))
    assert doc["plate_bbox_px"] == {"x": 0, "y": 0, "w": 800, "h": 800}
    assert doc["normalize_applied"] == _NORMALIZE
    assert res["band_id"] == CALIB_BAND_ID
    assert doc["bands"][0]["band_id"] == CALIB_BAND_ID


def test_round1_copies_blank_frame_as_diff_base(tmp_path):
    _seed_vision_case(tmp_path, "S1")
    res = build_round_workspace(tmp_path, "S1", 1)

    base = Path(res["workspace"]) / "after_normalized.jpg"
    assert base.read_bytes() == b"BLANK-PLATE-FRAME"


def test_round2_copies_round1_scraped_frame_as_diff_base(tmp_path):
    """轮2 的刮前基准应逐字节等于轮1 的刮后帧。"""
    _seed_vision_case(tmp_path, "S1")
    build_round_workspace(tmp_path, "S1", 1)
    r1_scraped = workspace_dir(tmp_path, "S1", 1) / "scraped_normalized.jpg"
    r1_scraped.write_bytes(b"R1-SCRAPED-FRAME")

    res = build_round_workspace(tmp_path, "S1", 2)
    assert (Path(res["workspace"]) / "after_normalized.jpg").read_bytes() == b"R1-SCRAPED-FRAME"


def test_round2_without_previous_scraped_frame_refuses(tmp_path):
    """上一轮没产出刮后帧 = 对账链在上一轮就断了; 必须当场失败而非拿空白帧凑合。"""
    _seed_vision_case(tmp_path, "S1")
    build_round_workspace(tmp_path, "S1", 1)

    with pytest.raises(FileNotFoundError, match="基准帧"):
        build_round_workspace(tmp_path, "S1", 2)


def test_missing_normalize_applied_refuses(tmp_path):
    """老 case 无 normalize_applied → 刮后无法确定性回放, 拒绝构造 (不留哑弹工作区)。"""
    _seed_vision_case(tmp_path, "S1", normalize=False)

    with pytest.raises(ValueError, match="normalize_applied"):
        build_round_workspace(tmp_path, "S1", 1)
    assert not workspace_dir(tmp_path, "S1", 1).exists()


def test_missing_plate_bbox_refuses(tmp_path):
    _seed_vision_case(tmp_path, "S1", bbox=False)

    with pytest.raises(ValueError, match="plate_bbox_px"):
        build_round_workspace(tmp_path, "S1", 1)


def test_workspace_paths_are_round_scoped(tmp_path):
    """每轮独立目录 —— 共用目录会让 preview_payload / scraped 帧互相覆盖。"""
    _seed_vision_case(tmp_path, "S1")
    r1 = build_round_workspace(tmp_path, "S1", 1)
    workspace_dir(tmp_path, "S1", 1).joinpath("scraped_normalized.jpg").write_bytes(b"X")
    r2 = build_round_workspace(tmp_path, "S1", 2)

    assert r1["workspace"] != r2["workspace"]
    assert Path(r1["summary_path"]).parent != Path(r2["summary_path"]).parent


# --------------------------------------------------------------------------
# 3b) 板框方形校验 (2026-07-27 真机 CALIB-...165445 的回归钉子)
# --------------------------------------------------------------------------
# 现场: 左侧补光衰减, 板框检出 1634×1712(纵横比 0.954, 左边被削 ~11mm), x 比例低估 6%,
# 卡尺实测 80.0mm 的图案被"测成" ~86mm → 判据挂掉白刮一轮。板是正方形, 比例失衡在建
# 工作区时就能看出来 —— 与空白预检同一立场: 拒绝要发生在任何刀具动作之前。


def test_non_square_bbox_is_rejected_before_workspace(tmp_path):
    """板框纵横比失衡 → 当场拒绝且不留工作区。用真机故障轮的实测比例 0.954 复刻。"""
    _seed_vision_case(tmp_path, "S1", bbox_wh=(764, 800))   # 0.955, 复刻 1634×1712 量级

    with pytest.raises(ValueError, match="正方形"):
        build_round_workspace(tmp_path, "S1", 1)
    assert not workspace_dir(tmp_path, "S1", 1).exists()


def test_slightly_off_square_bbox_passes(tmp_path):
    """正常光照的实测纵横比在 0.994~1.006 —— 容差不得误伤真实好板框。"""
    pytest.importorskip("cv2")
    case = _seed_vision_case(tmp_path, "S1", bbox_wh=(792, 800))   # 0.990, 容差内
    _write_frame(case / "after_normalized.jpg")

    res = build_round_workspace(tmp_path, "S1", 1)
    assert Path(res["summary_path"]).is_file()


def test_degenerate_bbox_is_rejected(tmp_path):
    """检测彻底崩溃(如真机 06:37 的 69×1133)也必须拦住, 不得除零或放行。"""
    _seed_vision_case(tmp_path, "S1", bbox_wh=(69, 1133))

    with pytest.raises(ValueError, match="正方形"):
        build_round_workspace(tmp_path, "S1", 1)


# --------------------------------------------------------------------------
# 4) 开刮前的空白预检 (2026-07-27 真机 CALIB-...101716 第1轮的回归钉子)
# --------------------------------------------------------------------------
# 现场: 操作员拿了一块用过的板, 第1轮图案 y4.0-6.1cm 正压在一条全宽旧痕上。
# 刮秃处再刮 → 前后帧同样黑 → 只能报"未检出", 而那时刀已跑完、粉已出。
# 下面同时钉住"脏板拦得住"与"空白板别误伤", 防修复被做成一味放宽或一味收严。

_FRAME_PX = 800   # 与 _seed_vision_case 的 plate_bbox_px 同尺寸: 整帧即板, 20cm → 40px/cm


def _write_frame(path: Path, dark_band_cm: tuple[float, float] | None = None) -> None:
    """写一张真实可解码的基准帧: 均匀亮"荧光"底, 可选在给定 y_cm 区间画一条全宽暗带。"""
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    frame = np.full((_FRAME_PX, _FRAME_PX, 3), 180, dtype=np.uint8)
    if dark_band_cm is not None:
        ppc = _FRAME_PX / _PLATE_CM
        y_lo, y_hi = dark_band_cm
        # 图像 y 向下 = cm 变小, 故上下沿在像素域互换
        top = int(round(_FRAME_PX - y_hi * ppc))
        bot = int(round(_FRAME_PX - y_lo * ppc))
        frame[top:bot, :] = 30
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)


def test_old_groove_in_pattern_region_is_rejected(tmp_path):
    """图案区压在旧痕上 → 建工作区时当场拒, 不留工作区(此时还没有任何刀具动作)。"""
    pytest.importorskip("cv2")
    case = _seed_vision_case(tmp_path, "S1")
    _, y_lo, _, y_hi = _bbox(pattern_contour_cm(1))
    _write_frame(case / "after_normalized.jpg", dark_band_cm=(y_lo, y_hi))

    with pytest.raises(ValueError, match="空白牺牲板"):
        build_round_workspace(tmp_path, "S1", 1)
    assert not workspace_dir(tmp_path, "S1", 1).exists()


def test_blank_plate_passes_precheck(tmp_path):
    """空白板必须放行 —— 预检误伤等于把整条标定链堵死。"""
    pytest.importorskip("cv2")
    case = _seed_vision_case(tmp_path, "S1")
    _write_frame(case / "after_normalized.jpg")

    res = build_round_workspace(tmp_path, "S1", 1)
    assert Path(res["summary_path"]).is_file()


def test_old_groove_outside_pattern_region_is_not_rejected(tmp_path):
    """旧痕在别处(轮3 位置) → 不影响轮1; 预检只看本轮真要刮的那块。"""
    pytest.importorskip("cv2")
    case = _seed_vision_case(tmp_path, "S1")
    _, y_lo, _, y_hi = _bbox(pattern_contour_cm(3))
    _write_frame(case / "after_normalized.jpg", dark_band_cm=(y_lo, y_hi))

    res = build_round_workspace(tmp_path, "S1", 1)
    assert Path(res["summary_path"]).is_file()


def test_undecodable_base_frame_skips_precheck(tmp_path):
    """基准帧不可解码 → 放行并留 warning。护栏不是工艺步, 看不了图不该堵死流程。"""
    _seed_vision_case(tmp_path, "S1")   # 夹具写的是假字节, 不是图像

    res = build_round_workspace(tmp_path, "S1", 1)
    assert Path(res["summary_path"]).is_file()
