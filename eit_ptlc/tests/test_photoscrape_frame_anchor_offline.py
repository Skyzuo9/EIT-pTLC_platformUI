"""手绘/视觉帧 ↔ 机床帧锚定离线判据
=====================================
背景（见 memory[photoscrape-vision-frame-consistency]）:
    手绘刮取"画的位置 ≠ 刮的位置、呈中心对称(180°)"根因: cm→机床的锚定
    (origin_corner + plate_origin) 是按 **rot180 归一化图** 设计的, 而手绘画布显示的是
    **rot0** 原图。rot0 vs rot180 = 正好一个 180°。

判据用真机实测四角作 ground truth（用户 0709 现场量, 20cm 方板）:
    图像左下 cm(0,0)   → 机床 (91.24, -75.7)   ← 作 plate_origin(lower-left 锚点)
    图像右下 cm(20,0)  → 机床 (291.44, -75.7)
    图像右上 cm(20,20) → 机床 (291.02, 122.13) ← CNC 示教原点(点样线远端角)

结论(本测试锁定): rot0 帧下正确配置 =
    image_plate_orientation: rot0 + origin_corner: lower-left + plate_origin: (91.24, -75.7)
且该配置与旧 rot180+top-right+(291.02,122.13) 对同一物理点产生**相同机床坐标**(证明不改机床运动)。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_photoscrape_frame_anchor_offline
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import pytest

from eit_ptlc.config.models import GCodeCfg, ToolCfg
from eit_ptlc.controller.cnc_path import _flip_from_corner, _to_machine, generate_scrape_arrays
from eit_ptlc.controller.sketch_path import polygon_to_contour_cm

# --- 真机实测(20cm 方板), (cm) -> (机床 mm) -----------------------------------
PLATE_CM = 20.0
MEASURED = {
    # 图像角 : (cm_pt,        machine_mm)
    "bottom_left":  ((0.0, 0.0),   (91.24, -75.7)),
    "bottom_right": ((PLATE_CM, 0.0), (291.44, -75.7)),
    "top_right":    ((PLATE_CM, PLATE_CM), (291.02, 122.13)),
}
# 板微倾 + 手测 → 顶边残差约 2mm; 给 3mm 容差
TOL_MM = 3.0

# rot0 画布: 板铺满 2000x2000 px 图像(x 右增, y 下增)。px_to_cm_affine 下:
#   图像左下 px(0,2000) → cm(0,0); 图像右上 px(2000,0) → cm(20,20)。
_BBOX = {"x": 0.0, "y": 0.0, "w": 2000.0, "h": 2000.0}


def _cfg_fix_a() -> GCodeCfg:
    """Fix-A(rot0 标准帧): lower-left 锚在图像左下=实测原点。"""
    return GCodeCfg(origin_corner="lower-left", plate_origin_x=91.24, plate_origin_y=-75.7)


def _cfg_old() -> GCodeCfg:
    """旧配置: top-right + 示教右上角值 (为 rot180 帧设计)。"""
    return GCodeCfg(origin_corner="top-right", plate_origin_x=291.02, plate_origin_y=122.13)


def _cm_to_machine(cm_pt, cfg: GCodeCfg):
    fx, fy = _flip_from_corner(cfg.origin_corner)
    return _to_machine(cm_pt[0], cm_pt[1], cfg.plate_origin_x, cfg.plate_origin_y, fx, fy)


def _px_corner_to_cm(px_pt):
    """走真手绘链路 sketch_path.polygon_to_contour_cm(px_to_cm_affine) 把一个像素点 → cm。"""
    # polygon 需 ≥3 点; 用一个绕 px_pt 的微三角形, 取首点。
    x, y = px_pt
    tri = [[x, y], [x + 1.0, y], [x, y + 1.0]]
    return polygon_to_contour_cm(tri, plate_size_cm=PLATE_CM, plate_bbox_px=_BBOX)[0]


# ---------------------------------------------------------------------------
# 1) Fix-A 配置让"画布角 → 机床"落到实测机床角(误差 < 3mm)
# ---------------------------------------------------------------------------

def test_fix_a_maps_drawn_corners_to_measured_machine():
    cfg = _cfg_fix_a()
    for name, (cm_pt, machine_mm) in MEASURED.items():
        mx, my = _cm_to_machine(cm_pt, cfg)
        d = math.hypot(mx - machine_mm[0], my - machine_mm[1])
        assert d < TOL_MM, f"{name}: cm{cm_pt} → 机床({mx:.2f},{my:.2f}) 偏离实测{machine_mm} {d:.2f}mm"


def test_fix_a_full_sketch_chain_top_right_corner():
    """整条手绘链路(px→cm→机床): 在 rot0 画布右上角点一下, 必须落到示教原点(291.02,122.13)。"""
    cfg = _cfg_fix_a()
    cm_pt = _px_corner_to_cm((2000.0, 0.0))          # 图像右上 px → 应得 cm(20,20)
    assert math.hypot(cm_pt[0] - PLATE_CM, cm_pt[1] - PLATE_CM) < 1e-6, cm_pt
    mx, my = _cm_to_machine(cm_pt, cfg)
    assert math.hypot(mx - 291.02, my - 122.13) < TOL_MM, (mx, my)


# ---------------------------------------------------------------------------
# 2) 红判据: 旧配置对 rot0 画布产生中心对称(180°)错位 —— 这就是用户看到的 bug
# ---------------------------------------------------------------------------

def test_old_config_is_centrally_symmetric_bug():
    """在 rot0 画布右上角(cm 20,20)画点, 旧配置把它送到 ~对角(左下), 距离示教原点约 283mm。

    这是"画的≠刮的、中心对称"的可复现红判据: 旧配置对 rot0 输入必然偏一个板对角线。
    """
    cfg = _cfg_old()
    intended = (291.02, 122.13)                      # 用户想刮的位置(右上原点角)
    mx, my = _cm_to_machine((PLATE_CM, PLATE_CM), cfg)  # 旧配置实际送达
    d = math.hypot(mx - intended[0], my - intended[1])
    assert d > 250.0, f"旧配置应把右上角误送到对角(≈283mm 外), 实测偏 {d:.2f}mm"
    # 且落点接近实测左下角 —— 印证"中心对称"
    bl = MEASURED["bottom_left"][1]
    assert math.hypot(mx - bl[0], my - bl[1]) < TOL_MM, (mx, my)


# ---------------------------------------------------------------------------
# 3) Fix-A 不改机床运动: 同一物理点在 rot0(Fix-A) 与 rot180(旧) 下机床坐标相同
# ---------------------------------------------------------------------------

def test_fix_a_preserves_machine_motion_vs_rot180():
    """任取物理点, rot0-cm 与 rot180-cm 差一个 180°(cx→20-cx, cy→20-cy);
    Fix-A(rot0) 与旧(rot180) 映射到的机床坐标必须一致(<3mm)。收集路径真机调参因此不受影响。"""
    fix_a, old = _cfg_fix_a(), _cfg_old()
    for cx0 in (0.0, 5.0, 12.5, 20.0):
        for cy0 in (0.0, 3.0, 20.0):
            m_new = _cm_to_machine((cx0, cy0), fix_a)                  # rot0 帧
            m_old = _cm_to_machine((PLATE_CM - cx0, PLATE_CM - cy0), old)  # 同物理点的 rot180 帧
            d = math.hypot(m_new[0] - m_old[0], m_new[1] - m_old[1])
            assert d < TOL_MM, f"物理点 rot0-cm({cx0},{cy0}): Fix-A{m_new} vs 旧{m_old} 差 {d:.2f}mm"


# ---------------------------------------------------------------------------
# 4) Fix-A 保刮取区域(报告 bug), 但翻转收集拖尾方向(需真机复核, 见下)
# ---------------------------------------------------------------------------

def _write_phys_band(dirp: Path, bbox, contour):
    dirp.mkdir(parents=True, exist_ok=True)
    (dirp / "band_01_path.json").write_text(json.dumps(
        {"scrape_path": {"bbox_cm": bbox},
         "contour_cm": [{"x_cm": x, "y_cm": y} for x, y in contour]}), encoding="utf-8")
    (dirp / "summary.json").write_text(json.dumps(
        {"bands": [{"band_id": "band_01", "path_json": "band_01_path.json"}]}), encoding="utf-8")
    return dirp / "summary.json"


def _cfg_fix_a_collector():
    """Fix-A 生产配置: rot0/lower-left + 收集器 +X(app.yaml 真机)。触发收集镜像回规范帧。"""
    return GCodeCfg(origin_corner="lower-left", plate_origin_x=91.24, plate_origin_y=-75.7,
                    collector_x_positive=True, tool=ToolCfg(bottle_x_offset_mm=93.0))


def _cfg_old_collector():
    """旧真机配置: top-right + 收集器 +X(不镜像, 收集在规范帧)。作 collect 几何 ground truth。"""
    return GCodeCfg(origin_corner="top-right", plate_origin_x=291.02, plate_origin_y=122.13,
                    collector_x_positive=True, tool=ToolCfg(bottle_x_offset_mm=93.0))


def test_collector_decoupling_reproduces_old_collect_geometry():
    """核心判据: 同一物理band, Fix-A(rot0/lower-left, 收集器+X) 的刮取+收集机床点 **逐点复现**
    旧(top-right, 收集器+X) —— 收集器解耦把整条路径镜像回真机调参的规范帧, 完整保住收集调参,
    只是现在跟对了正确的刮取位置。含连续性(g_cx[0] 接 g_sx[-1])。"""
    a, b, c, d = 3.0, 16.0, 2.0, 4.0
    fix, old = _cfg_fix_a_collector(), _cfg_old_collector()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cont0 = [(a, c), (b, c), (b, d), (a, d)]
        s0 = _write_phys_band(td / "r0", {"x_min": a, "y_min": c, "x_max": b, "y_max": d}, cont0)
        cont180 = [(PLATE_CM - x, PLATE_CM - y) for x, y in cont0]
        s180 = _write_phys_band(td / "r180",
                                {"x_min": PLATE_CM - b, "y_min": PLATE_CM - d,
                                 "x_max": PLATE_CM - a, "y_max": PLATE_CM - c}, cont180)
        for strat in ("contour", "boustrophedon"):
            Af = generate_scrape_arrays(s0, "band_01", fix, strategy=strat)
            Ao = generate_scrape_arrays(s180, "band_01", old, strategy=strat)
            # X 是收集器解耦的作用轴: 刮取+收集 X **逐点复现**旧几何(镜像回规范帧)。
            for nm, u, v in (("g_sx", Af.g_sx, Ao.g_sx), ("g_cx", Af.g_cx, Ao.g_cx)):
                md = max(abs(p - q) for p, q in zip(u, v))
                assert md < TOL_MM, f"[{strat}] {nm} 逐点最大差 {md:.2f}mm (X 应复现旧几何)"
            # Y 与收集无关(rot0 vs rot180 Y 遍历序天生不同, 但覆盖同一机床区域): 按区间 min/max 校验。
            for nm, u, v in (("g_sy", Af.g_sy, Ao.g_sy), ("g_cy", Af.g_cy, Ao.g_cy)):
                assert abs(min(u) - min(v)) < TOL_MM and abs(max(u) - max(v)) < TOL_MM, \
                    f"[{strat}] {nm} 机床 Y 区间应与旧一致"
            # 连续性: 收集首点接刮取末点(收集器解耦保住了 X 连续)
            assert abs(Af.g_cx[0] - Af.g_sx[-1]) < 5.0


def test_collector_decoupling_off_is_zero_regression():
    """collector_x_positive=False(默认, legacy) → lower-left 不镜像, 与不设时逐点一致(零回归)。"""
    a, b, c, d = 3.0, 16.0, 2.0, 4.0
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cont0 = [(a, c), (b, c), (b, d), (a, d)]
        s0 = _write_phys_band(td / "r0", {"x_min": a, "y_min": c, "x_max": b, "y_max": d}, cont0)
        base = GCodeCfg(origin_corner="lower-left", plate_origin_x=91.24, plate_origin_y=-75.7)
        explicit = GCodeCfg(origin_corner="lower-left", plate_origin_x=91.24, plate_origin_y=-75.7,
                            collector_x_positive=False)
        A0 = generate_scrape_arrays(s0, "band_01", base, strategy="contour")
        A1 = generate_scrape_arrays(s0, "band_01", explicit, strategy="contour")
        assert A0.g_sx == A1.g_sx and A0.g_cx == A1.g_cx and A0.g_cy == A1.g_cy


# ---------------------------------------------------------------------------
# 5) Task③: rot0 是 tlc_analyze 点样线检测的正确朝向(detect_origin_band 只在下半找)
# ---------------------------------------------------------------------------

def test_rot0_is_correct_orientation_for_origin_detection():
    """真样品 before 图: rot0 下点样线(origin) 落图像下半且置信度显著高于 rot180。
    锁定 image_plate_orientation=rot0 与 detect_origin_band(profile 清零上半45%) 同帧。"""
    cv2 = pytest.importorskip("cv2")
    img_path = Path("data/samples/case1/before.jpg")
    if not img_path.is_file():
        pytest.skip("缺 data/samples/case1/before.jpg")
    view_dir = Path("View/pTLC_Viewing")
    if str(view_dir) not in sys.path:
        sys.path.insert(0, str(view_dir))
    from tlc_analyze import detect_origin_band, detect_plate  # type: ignore

    img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    assert img is not None

    def origin_ratio_conf(im):
        plate = detect_plate(im, PLATE_CM)
        ob = detect_origin_band(im, plate)
        return ob.center_y / plate.h, ob.confidence

    r0_ratio, r0_conf = origin_ratio_conf(img)
    r180_ratio, r180_conf = origin_ratio_conf(cv2.rotate(img, cv2.ROTATE_180))

    assert 0.45 <= r0_ratio <= 0.96, f"rot0 点样线应在图像下半(45~96%), 实为 {r0_ratio:.3f}"
    assert r0_conf > r180_conf * 3.0, f"rot0 置信度({r0_conf:.1f}) 应远高于 rot180({r180_conf:.1f})"


# ---------------------------------------------------------------------------
# main() 便于 `python -m ...` 直接跑(与 test_cnc_path_offline 同风格)
# ---------------------------------------------------------------------------

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    cases = [
        ("fix_a_maps_measured", test_fix_a_maps_drawn_corners_to_measured_machine),
        ("fix_a_full_chain_TR", test_fix_a_full_sketch_chain_top_right_corner),
        ("old_config_180_bug", test_old_config_is_centrally_symmetric_bug),
        ("fix_a_preserves_motion", test_fix_a_preserves_machine_motion_vs_rot180),
        ("collector_decoupling_reproduces_old", test_collector_decoupling_reproduces_old_collect_geometry),
        ("collector_decoupling_zero_regression", test_collector_decoupling_off_is_zero_regression),
    ]
    fails = []
    for name, fn in cases:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            fails.append(name)
            print(f"FAIL {name}: {exc}")
    print(f"\n共 {len(cases)} 用例, 失败 {len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
