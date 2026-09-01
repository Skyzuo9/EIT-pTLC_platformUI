"""CNC 路径生成离线测试
=====================
功能:
    验证 controller/cnc_path 迁移后可用: 安全占位数组 + 由合成 band 几何生成刮扫/收集数组
    (boustrophedon 策略), 输出 400 点 + PLC 变量字典 + 非退化.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_cnc_path_offline
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest
from eit_ptlc.config.models import GCodeCfg, ScrapeCfg, ToolCfg
from eit_ptlc.controller.cnc_path import (
    SCRAPE_POINT_COUNT,
    CncPathController,
    generate_scrape_arrays,
    safe_placeholder_arrays,
)

# 块写字段（真机 6 变量契约中一次写入的 5 个；g_pass_z 每 pass 单独写不在此）
_PLC_KEYS = {"g_sx", "g_sy", "g_cx", "g_cy", "g_scrape_feed"}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []
    total = [0]

    def check(name: str, cond: bool, detail: str = "") -> None:
        total[0] += 1
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    cfg = GCodeCfg()

    # 安全占位: pass_count=0, 全 0 数组, 块写键齐全
    ph = safe_placeholder_arrays(cfg)
    d = ph.as_plc_dict()
    check("placeholder_pass0", ph.pass_count == 0 and len(d["g_sx"]) == SCRAPE_POINT_COUNT, str(ph.pass_count))
    check("placeholder_keys", _PLC_KEYS <= set(d), str(sorted(_PLC_KEYS - set(d))))
    check("placeholder_zeros", all(v == 0 for v in d["g_sx"]), "占位应全 0")
    check("placeholder_passz_empty", ph.pass_z_list == [], str(ph.pass_z_list))
    check("placeholder_start_zero", ph.start_x_mm == 0.0 and ph.start_y_mm == 0.0,
          f"({ph.start_x_mm},{ph.start_y_mm})")

    # 真几何: 合成 band (bbox 0.5..2.5cm x 0.5..1.5cm) -> boustrophedon 刮扫数组
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "band_01_path.json").write_text(json.dumps(
            {"scrape_path": {"bbox_cm": {"x_min": 0.5, "y_min": 0.5, "x_max": 2.5, "y_max": 1.5}}}
        ), encoding="utf-8")
        (td / "summary.json").write_text(json.dumps(
            {"bands": [{"band_id": "band_01", "path_json": "band_01_path.json"}]}
        ), encoding="utf-8")

        arr = generate_scrape_arrays(td / "summary.json", "band_01", cfg, strategy="boustrophedon")
        check("scrape_len", len(arr.g_sx) == SCRAPE_POINT_COUNT and len(arr.g_cx) == SCRAPE_POINT_COUNT,
              f"sx={len(arr.g_sx)} cx={len(arr.g_cx)}")
        check("pass_count", arr.pass_count == cfg.scrape.num_passes, str(arr.pass_count))
        check("plc_dict_keys", _PLC_KEYS <= set(arr.as_plc_dict()), str(sorted(_PLC_KEYS - set(arr.as_plc_dict()))))
        check("non_degenerate", any(v != 0 for v in arr.g_sx) and any(v != 0 for v in arr.g_sy), "刮扫数组不应全 0")
        # 每 pass Z 递增: 长度=pass_count, 末 pass = plate_surface + total_depth
        rs = arr.as_action_result()
        expect_last = round(cfg.plate_surface_z_mm + cfg.scrape.total_depth_mm, 3)
        check("pass_z_list", len(rs["pass_z_list"]) == arr.pass_count and abs(rs["pass_z_list"][-1] - expect_last) < 1e-6,
              f"{rs['pass_z_list']} vs last={expect_last}")
        # 路径首点标量: 供对位检查内环走起点(VM 无数组下标) —— 与 g_ 数组同帧机床 mm
        check("start_xy_field", arr.start_x_mm == arr.g_sx[0] and arr.start_y_mm == arr.g_sy[0],
              f"start=({arr.start_x_mm},{arr.start_y_mm}) head=({arr.g_sx[0]},{arr.g_sy[0]})")
        check("start_xy_dict", rs["start_x_mm"] == arr.g_sx[0] and rs["start_y_mm"] == arr.g_sy[0],
              f"dict start=({rs.get('start_x_mm')},{rs.get('start_y_mm')})")

    # 收集路径不变量（拖尾正向 + 残粉 −X 回走）: 宽 band (X 跨度 15cm > 拖尾 8.5cm)
    # 守卫"带粉出界"回归: ① g_cx[0] 接 g_sx[-1](首步零窜) ② 中心封顶 x_max 不越界
    #                    ③ return_sweep 切换拖尾-only / 拖尾+回走
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        x_min_cm, x_max_cm = 1.0, 16.0
        (td / "band_01_path.json").write_text(json.dumps(
            {"scrape_path": {"bbox_cm": {"x_min": x_min_cm, "y_min": 0.5, "x_max": x_max_cm, "y_max": 1.5}}}
        ), encoding="utf-8")
        (td / "summary.json").write_text(json.dumps(
            {"bands": [{"band_id": "band_01", "path_json": "band_01_path.json"}]}
        ), encoding="utf-8")

        off_cm = cfg.tool.bottle_x_offset_mm / 10.0      # 拖尾长度 = 偏置 (8.5cm)
        # lower-left 原点、无翻转: 机床 X = (plate_x + off) * 10; 中心封顶 plate x_max
        cap_mm = (x_max_cm + off_cm) * 10.0              # x_max 中心对应机床上界
        xmin_mm = (x_min_cm + off_cm) * 10.0             # x_min 对应机床下界
        tail_start_mm = (max(x_min_cm, x_max_cm - off_cm) + off_cm) * 10.0  # 拖尾起点

        cfg.collection.return_sweep = True
        a_ret = generate_scrape_arrays(td / "summary.json", "band_01", cfg, strategy="boustrophedon")
        check("collect_continuity", abs(a_ret.g_sx[-1] - a_ret.g_cx[0]) < 1e-6,
              f"g_sx[-1]={a_ret.g_sx[-1]} g_cx[0]={a_ret.g_cx[0]} (首步窜动应为 0)")
        check("collect_cap_xmax", max(a_ret.g_cx) <= cap_mm + 1e-6,
              f"max(g_cx)={max(a_ret.g_cx)} > 封顶 {cap_mm} (中心越界=带粉出界根源)")
        check("collect_return_to_xmin", abs(min(a_ret.g_cx) - xmin_mm) < 1.0,
              f"min(g_cx)={min(a_ret.g_cx)} 应回走到 x_min≈{xmin_mm}")

        cfg.collection.return_sweep = False
        a_tail = generate_scrape_arrays(td / "summary.json", "band_01", cfg, strategy="boustrophedon")
        check("collect_len_tailonly", len(a_tail.g_cx) == SCRAPE_POINT_COUNT, str(len(a_tail.g_cx)))
        check("collect_tailonly_no_return", min(a_tail.g_cx) >= tail_start_mm - 1.0,
              f"min(g_cx)={min(a_tail.g_cx)} 仅拖尾不应低于拖尾起点≈{tail_start_mm}")
        cfg.collection.return_sweep = True  # 复位

    print(f"\n共 {total[0]} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def test_cnc_path_offline():
    """pytest 入口: 安全占位 + 真几何路径 + 收集不变量。"""
    assert main() == 0


def test_generate_cnc_path_placeholder_reachable():
    """容错化: cnc_path(placeholder=true) 无需 summary/band 即产出 0-pass 安全占位数组,
    这是"无谱带/跳过刮板"路径在生产 VM 里可达的实现 (旧 UI-Upper 有定义但从不调用)。"""
    cfg = GCodeCfg()
    ctrl = CncPathController(lambda: cfg)

    # 占位路径: 传空 summary_path/band_id + placeholder=True, 不触碰文件系统
    res = asyncio.run(ctrl.generate_cnc_path(summary_path="", band_id="", placeholder=True))
    assert res["pass_count"] == 0, res["pass_count"]
    assert res["pass_z_list"] == [], res["pass_z_list"]
    assert res["start_x_mm"] == 0.0, res["start_x_mm"]   # placeholder 首点标量 = 0.0
    assert res["start_y_mm"] == 0.0, res["start_y_mm"]
    for key in ("g_sx", "g_sy", "g_cx", "g_cy"):
        assert len(res[key]) == SCRAPE_POINT_COUNT, (key, len(res[key]))
        assert all(v == 0 for v in res[key]), f"{key} 应全 0 (空跑不撞板)"
    assert res["g_scrape_feed"] == cfg.scrape.feed_rate

    # 非占位路径 (placeholder 缺省 False) 仍要求真 summary → FileNotFoundError, 契约未被削弱
    raised = False
    try:
        asyncio.run(ctrl.generate_cnc_path(summary_path="/no/such/summary.json", band_id="band_01"))
    except FileNotFoundError:
        raised = True
    assert raised, "常规路径应仍要求有效 summary.json"


def _write_band_summary(dirpath: Path, bbox: dict) -> Path:
    """写一个最小 summary.json + band path_json, 返回 summary 路径。"""
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "band_01_path.json").write_text(
        json.dumps({"scrape_path": {"bbox_cm": bbox}}), encoding="utf-8"
    )
    (dirpath / "summary.json").write_text(
        json.dumps({"bands": [{"band_id": "band_01", "path_json": "band_01_path.json"}]}),
        encoding="utf-8",
    )
    return dirpath / "summary.json"


def test_bottle_y_offset_shifts_only_collect_y(tmp_path):
    """bottle_y_offset_mm 使 g_cy 整体平移常量, 而 g_sx/g_sy/g_cx 逐点不变（正交性铁证）。"""
    summary = _write_band_summary(
        tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5}
    )
    base = GCodeCfg()  # bottle_y_offset_mm 默认 0.0
    shifted = GCodeCfg(tool=ToolCfg(bottle_y_offset_mm=3.0))
    a0 = generate_scrape_arrays(summary, "band_01", base, strategy="boustrophedon")
    a1 = generate_scrape_arrays(summary, "band_01", shifted, strategy="boustrophedon")

    assert a0.g_sx == a1.g_sx
    assert a0.g_sy == a1.g_sy
    assert a0.g_cx == a1.g_cx  # X 维完全不受 Y 偏移影响

    deltas = [c1 - c0 for c0, c1 in zip(a0.g_cy, a1.g_cy)]
    assert max(deltas) - min(deltas) < 1e-6      # 常量平移(非缩放/非局部)
    assert abs(deltas[0] - 3.0) < 1e-6           # 默认 lower-left(flip_y=False): 板+Y→机床+Y, 平移=+offset_mm


def test_loader_rejects_out_of_range_bottle_y_offset():
    from eit_ptlc.config.loader import _parse_gcode
    with pytest.raises(ValueError):
        _parse_gcode({"tool": {"bottle_y_offset_mm": 30.0}})
    # 边界内合法, 正常返回
    cfg = _parse_gcode({"tool": {"bottle_y_offset_mm": 1.0}})
    assert abs(cfg.tool.bottle_y_offset_mm - 1.0) < 1e-9


def test_collect_margin_absolute_independent_of_band_height(tmp_path):
    """同 margin、不同带高 → 收集 Y span 之差 == 2×带半高之差（绝对膨胀, 与 margin 无关）。"""
    cfg = GCodeCfg()  # collect_margin_mm 默认 4.0
    s1 = _write_band_summary(tmp_path / "b1", {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})  # 带高1cm
    s2 = _write_band_summary(tmp_path / "b2", {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 3.5})  # 带高3cm
    a1 = generate_scrape_arrays(s1, "band_01", cfg, strategy="boustrophedon")
    a2 = generate_scrape_arrays(s2, "band_01", cfg, strategy="boustrophedon")
    span1 = max(a1.g_cy) - min(a1.g_cy)
    span2 = max(a2.g_cy) - min(a2.g_cy)
    assert abs((span2 - span1) - 20.0) < 1e-6   # 带半高差1cm → span 差 2×10mm=20mm


def test_collect_margin_equals_radius_gives_band_edge(tmp_path):
    """collect_margin_mm == 桶口半径 → y_half == 带半高 → 收集 Y span == 带高（真扣桶口半径）。"""
    cfg = GCodeCfg(collect_margin_mm=2.5)  # == bottle_diameter_mm(5)/2
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})  # 带高1cm=10mm
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="boustrophedon")
    assert abs((max(a.g_cy) - min(a.g_cy)) - 10.0) < 1e-6


def test_collect_margin_below_radius_clamps_to_zero(tmp_path):
    """margin < 桶口半径 → y_half 下钳到 0（单中心线, span 0）, 不出负值。"""
    cfg = GCodeCfg(collect_margin_mm=0.0)  # 0 < 半径2.5
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 0.7})  # 带半高0.1cm
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="boustrophedon")
    assert abs(max(a.g_cy) - min(a.g_cy)) < 1e-6


def test_collect_margin_negative_rejected(tmp_path):
    """collect_margin_mm < 0 抛 ValueError。"""
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    with pytest.raises(ValueError):
        generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="boustrophedon", collect_margin_mm=-1.0)


def test_loader_parses_collect_expand_ratio():
    """collect_expand_ratio 恢复为可调乘性包络(治硅胶崩飞): 合法值解析, 越界 [1.0,2.0] 抛错。"""
    from eit_ptlc.config.loader import _parse_gcode
    cfg = _parse_gcode({"collect_expand_ratio": 1.5})
    assert abs(cfg.collect_expand_ratio - 1.5) < 1e-9
    with pytest.raises(ValueError):
        _parse_gcode({"collect_expand_ratio": 2.5})   # > 2.0
    with pytest.raises(ValueError):
        _parse_gcode({"collect_expand_ratio": 0.5})   # < 1.0


def test_bottle_y_offset_sign_under_flip_y(tmp_path):
    """真机 origin_corner=top-right(flip_y=True): 板+Y偏移 → 机床−Y, delta=−offset_mm。守卫翻转下符号契约。"""
    summary = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    base = GCodeCfg(origin_corner="top-right")
    shifted = GCodeCfg(origin_corner="top-right", tool=ToolCfg(bottle_y_offset_mm=3.0))
    a0 = generate_scrape_arrays(summary, "band_01", base, strategy="boustrophedon")
    a1 = generate_scrape_arrays(summary, "band_01", shifted, strategy="boustrophedon")
    assert a0.g_sx == a1.g_sx and a0.g_sy == a1.g_sy and a0.g_cx == a1.g_cx
    deltas = [c1 - c0 for c0, c1 in zip(a0.g_cy, a1.g_cy)]
    assert max(deltas) - min(deltas) < 1e-6      # 常量平移
    assert abs(deltas[0] - (-3.0)) < 1e-6        # flip_y: +板Y → −机床Y


def test_collect_margin_does_not_affect_gcx(tmp_path):
    """collect_margin_mm 只影响收集 Y, g_cx(X 维)不变（第二正交轴）。"""
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    a1 = generate_scrape_arrays(s, "band_01", GCodeCfg(collect_margin_mm=4.0), strategy="boustrophedon")
    a2 = generate_scrape_arrays(s, "band_01", GCodeCfg(collect_margin_mm=8.0), strategy="boustrophedon")
    assert a1.g_cx == a2.g_cx
    assert a1.g_cy != a2.g_cy   # Y 确实随 margin 变化(sanity)


# ---------------------------------------------------------------------------
# 分刀分层 (num_passes > 1)
# ---------------------------------------------------------------------------
# ⚠️ 现役 app.yaml 的 num_passes 恒为 1, 分层算式在 N=1 下退化成 [surface+total],
#    "均分成 N 层" 这件事此前无任何用例覆盖。分刀是治粉末崩飞的唯一工艺手段
#    (每刀切削力 ∝ 切深), 算式错了会直接把某一刀切到玻璃基板或整层刮不透。

def test_pass_z_splits_total_depth_into_equal_layers(tmp_path):
    """num_passes=N → N 层等距递进下刀, 末层恰为总深(不多不少)。

    契约 pass_z[k] = plate_surface + k*total_depth/N, k=1..N (Z 正方向向下)。
    三条一起断言才有意义: 只查末层会漏掉层距不均, 只查层距会漏掉整体偏置。
    """
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    cfg = GCodeCfg(plate_surface_z_mm=20.5, scrape=ScrapeCfg(total_depth_mm=1.2, num_passes=3))
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="boustrophedon")

    assert a.pass_count == 3
    assert len(a.pass_z_list) == 3
    assert a.pass_z_list == [20.9, 21.3, 21.7]                      # 逐层 +0.4mm
    deltas = [b - a2 for a2, b in zip(a.pass_z_list, a.pass_z_list[1:])]
    assert max(deltas) - min(deltas) < 1e-9, f"层距不均: {deltas}"    # 等距
    assert abs(a.pass_z_list[-1] - (20.5 + 1.2)) < 1e-9              # 末层恰好切透总深
    assert a.pass_z_list[0] > 20.5, "首层必须已下刀(不能停在板面)"


def test_pass_count_does_not_change_the_path_itself(tmp_path):
    """分刀只改 Z 分层, 不得动 XY 路径 —— 路径随刀次变化会让分刀前后刮的不是同一块区域。"""
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    one = generate_scrape_arrays(s, "band_01", GCodeCfg(scrape=ScrapeCfg(num_passes=1)),
                                 strategy="boustrophedon")
    three = generate_scrape_arrays(s, "band_01", GCodeCfg(scrape=ScrapeCfg(num_passes=3)),
                                   strategy="boustrophedon")

    assert one.g_sx == three.g_sx and one.g_sy == three.g_sy
    assert one.g_cx == three.g_cx and one.g_cy == three.g_cy
    assert one.g_scrape_feed == three.g_scrape_feed
    assert one.pass_count == 1 and three.pass_count == 3


def _write_band_summary_contour(dirpath: Path, bbox: dict) -> Path:
    """写带 contour_cm 的最小 summary（矩形轮廓 = bbox 四角）, 使 contour 策略真正采样轮廓。

    _write_band_summary 只写 bbox → contour 策略退回 boustrophedon; 本 helper 补上
    contour_cm, 覆盖生产默认策略 contour 下的收集 Y 行为（bottle_y_offset / collect_margin）。
    """
    dirpath.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = bbox["x_min"], bbox["y_min"], bbox["x_max"], bbox["y_max"]
    contour = [
        {"x_cm": x0, "y_cm": y0}, {"x_cm": x1, "y_cm": y0},
        {"x_cm": x1, "y_cm": y1}, {"x_cm": x0, "y_cm": y1},
    ]
    (dirpath / "band_01_path.json").write_text(
        json.dumps({"scrape_path": {"bbox_cm": bbox}, "contour_cm": contour}), encoding="utf-8"
    )
    (dirpath / "summary.json").write_text(
        json.dumps({"bands": [{"band_id": "band_01", "path_json": "band_01_path.json"}]}),
        encoding="utf-8",
    )
    return dirpath / "summary.json"


def test_bottle_y_offset_shifts_collect_y_under_contour(tmp_path):
    """生产 contour 策略下: bottle_y_offset_mm 必须平移 g_cy, 且不动 g_sx/g_sy/g_cx。

    回归护栏: 曾经 _path_contour 每列从轮廓扫描线重算 Y 中心, 丢弃 offset → 真机无效。
    """
    summary = _write_band_summary_contour(
        tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5}
    )
    base = GCodeCfg()  # bottle_y_offset_mm 默认 0.0
    shifted = GCodeCfg(tool=ToolCfg(bottle_y_offset_mm=3.0))
    a0 = generate_scrape_arrays(summary, "band_01", base, strategy="contour")
    a1 = generate_scrape_arrays(summary, "band_01", shifted, strategy="contour")

    assert a0.g_sx == a1.g_sx and a0.g_sy == a1.g_sy  # 刮取路径不受收集偏移影响
    assert a0.g_cx == a1.g_cx                         # 收集 X 维不变

    deltas = [c1 - c0 for c0, c1 in zip(a0.g_cy, a1.g_cy)]
    assert max(deltas) - min(deltas) < 1e-6           # 常量平移(非缩放/非局部)
    assert abs(deltas[0] - 3.0) < 1e-6                # lower-left(flip_y=False): 板+Y→机床+Y=+offset_mm


def test_collect_margin_expands_collect_y_under_contour(tmp_path):
    """生产 contour 策略下: collect_margin_mm 每 +1mm → 收集 Y 每侧 +1mm(span +2mm), g_cx 不变。"""
    summary = _write_band_summary_contour(
        tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5}
    )
    a1 = generate_scrape_arrays(summary, "band_01", GCodeCfg(collect_margin_mm=4.0), strategy="contour")
    a2 = generate_scrape_arrays(summary, "band_01", GCodeCfg(collect_margin_mm=8.0), strategy="contour")
    assert a1.g_cx == a2.g_cx
    span1 = max(a1.g_cy) - min(a1.g_cy)
    span2 = max(a2.g_cy) - min(a2.g_cy)
    assert abs((span2 - span1) - 8.0) < 1e-6          # margin 差 4mm → span 差 2×4=8mm


def test_collect_expand_ratio_scales_local_half_under_contour(tmp_path):
    """生产 contour 策略下 collect_expand_ratio 按比例缩放每列轮廓局部半高(乘性包络, 治崩飞), g_cx 不变。

    带高1cm; margin==桶口半径(2.5) → 绝对净加量 y_extra=0, 隔离出纯乘性效果:
    span = ratio × 带高。ratio1.0→10mm, ratio2.0→20mm。
    回归护栏: 曾经 _path_contour 每列重算半高, 会丢弃乘性包络。
    """
    summary = _write_band_summary_contour(
        tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5}
    )
    a1 = generate_scrape_arrays(
        summary, "band_01",
        GCodeCfg(collect_margin_mm=2.5, collect_expand_ratio=1.0), strategy="contour",
    )
    a2 = generate_scrape_arrays(
        summary, "band_01",
        GCodeCfg(collect_margin_mm=2.5, collect_expand_ratio=2.0), strategy="contour",
    )
    assert a1.g_cx == a2.g_cx
    assert abs((max(a1.g_cy) - min(a1.g_cy)) - 10.0) < 1e-6   # ratio1.0, extra0 → 带高
    assert abs((max(a2.g_cy) - min(a2.g_cy)) - 20.0) < 1e-6   # ratio2.0, extra0 → 2×带高


def test_collect_expand_ratio_and_margin_compose_affine(tmp_path):
    """y_half = ratio×带半高 + (collect_margin − 桶口半径): 乘性包络与绝对余量线性叠加(affine)。

    带高1cm(半高5mm); ratio1.5 → 7.5mm; margin4.0−半径2.5=1.5mm; y_half=9.0mm → span 18mm。
    """
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    a = generate_scrape_arrays(
        s, "band_01",
        GCodeCfg(collect_expand_ratio=1.5, collect_margin_mm=4.0), strategy="boustrophedon",
    )
    assert abs((max(a.g_cy) - min(a.g_cy)) - 18.0) < 1e-6


def test_machine_y_min_clamps_scrape_and_collect(tmp_path):
    """machine_y_min_mm 设定后, 刮取/收集 Y 均不低于下限(防撞机); g_sx/g_cx 不受影响。"""
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    # lower-left + plate_origin_y=-75.7: band 底部机床 Y ≈ -75.7 + 0.5*10 = -70.7; 收集更低
    kw = dict(origin_corner="lower-left", plate_origin_x=91.24, plate_origin_y=-75.7)
    unclamped = generate_scrape_arrays(s, "band_01", GCodeCfg(**kw), strategy="contour")
    floor = -68.0
    clamped = generate_scrape_arrays(s, "band_01", GCodeCfg(**kw, machine_y_min_mm=floor), strategy="contour")

    assert min(unclamped.g_sy) < floor or min(unclamped.g_cy) < floor   # sanity: 未钳确有点低于 floor
    assert min(clamped.g_sy) >= floor - 1e-9
    assert min(clamped.g_cy) >= floor - 1e-9
    assert unclamped.g_sx == clamped.g_sx and unclamped.g_cx == clamped.g_cx  # X 维不受 Y 钳影响


def test_machine_y_min_none_is_zero_regression(tmp_path):
    """machine_y_min_mm 默认 None → 数组与不设时逐点一致(零回归)。"""
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    a0 = generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="contour")
    a1 = generate_scrape_arrays(s, "band_01", GCodeCfg(machine_y_min_mm=None), strategy="contour")
    assert a0.g_sy == a1.g_sy and a0.g_cy == a1.g_cy


def test_loader_parses_machine_y_min_mm():
    """gcode.machine_y_min_mm: 数值解析为 float, 缺省=None(关)。"""
    from eit_ptlc.config.loader import _parse_gcode
    assert _parse_gcode({}).machine_y_min_mm is None
    assert abs(_parse_gcode({"machine_y_min_mm": -73.0}).machine_y_min_mm - (-73.0)) < 1e-9


def test_loader_parses_cutter_compensation():
    """刀具半径补偿配置: 开关+安全边解析; margin 越界 [0,10] 拒绝; 默认关(零回归)。"""
    from eit_ptlc.config.loader import _parse_gcode
    cfg = _parse_gcode({"tool": {"cutter_compensation": True, "compensation_margin_mm": 1.5}})
    assert cfg.tool.cutter_compensation is True
    assert abs(cfg.tool.compensation_margin_mm - 1.5) < 1e-9
    # 缺省 = dataclass 默认: 关 + 0
    cfg0 = _parse_gcode({})
    assert cfg0.tool.cutter_compensation is False
    assert abs(cfg0.tool.compensation_margin_mm) < 1e-9
    with pytest.raises(ValueError):
        _parse_gcode({"tool": {"compensation_margin_mm": -0.1}})
    with pytest.raises(ValueError):
        _parse_gcode({"tool": {"compensation_margin_mm": 10.5}})


def test_inset_interval():
    from eit_ptlc.controller.cnc_path import _inset_interval
    assert _inset_interval(0.0, 10.0, 1.0) == (1.0, 9.0)
    lo, hi = _inset_interval(0.0, 1.0, 0.6)   # 宽 1 < 2×0.6 → 收拢中点
    assert abs(lo - 0.5) < 1e-12 and abs(hi - 0.5) < 1e-12


def test_erode_column_interval_rectangle_and_zero_radius():
    import numpy as np
    from eit_ptlc.controller.cnc_path import _erode_column_interval, _sample_contour_y_scanline
    rect = np.asarray([[1.0, 0.5], [16.0, 0.5], [16.0, 1.5], [1.0, 1.5]])
    top, bot = _erode_column_interval(rect, 8.0, 0.2, (1.0, 16.0))
    assert abs(top - 1.3) < 1e-6 and abs(bot - 0.7) < 1e-6      # 矩形腐蚀 = 恒减 R
    # radius=0 → 直通扫描线(逐字节零回归)
    assert _erode_column_interval(rect, 8.0, 0.0, (1.0, 16.0)) == _sample_contour_y_scanline(rect, 8.0)


def test_erode_column_interval_sloped_edge_tighter_than_naive():
    """斜边(slope=1)处真腐蚀 top' ≈ y_top − R·√2, 朴素恒减 R 会欠补偿 —— 弦高项守卫。"""
    import numpy as np
    from eit_ptlc.controller.cnc_path import _erode_column_interval
    tri = np.asarray([[1.0, 0.5], [6.0, 0.5], [6.0, 5.5]])      # 斜边 (1,0.5)→(6,5.5)
    top, bot = _erode_column_interval(tri, 3.0, 0.25, (1.0, 6.0))
    # y_top(3.0)=2.5; 朴素=2.25; 真值≈2.5−0.25√2≈2.1464(17 采样误差 <0.01)
    assert 2.14 <= top <= 2.16
    assert abs(bot - 0.75) < 1e-6                                # 底边平直 → 恒加 R


def test_erode_column_interval_collapse_signal():
    """带高 0.3 < 2R=0.5 → 返回倒置区间(top'<bot'), 调用方据此收拢中线。"""
    import numpy as np
    from eit_ptlc.controller.cnc_path import _erode_column_interval
    thin = np.asarray([[1.0, 0.5], [16.0, 0.5], [16.0, 0.8], [1.0, 0.8]])
    top, bot = _erode_column_interval(thin, 8.0, 0.25, (1.0, 16.0))
    assert top < bot
    assert abs((top + bot) / 2.0 - 0.65) < 1e-6                  # 倒置区间中点 = 带中线


def test_path_contour_tool_radius_erodes_y(tmp_path):
    """tool_radius_cm>0: 每列 Y 上下限收进腐蚀区间(矩形轮廓 → 恒减 R); 默认 0 不动。"""
    import numpy as np
    from eit_ptlc.controller.cnc_path import _path_contour
    rect = np.asarray([[1.0, 0.5], [16.0, 0.5], [16.0, 1.5], [1.0, 1.5]])
    kw = dict(
        x_offset_mm=0.0, plate_origin_x=0.0, plate_origin_y=0.0,
        flip_x=False, flip_y=False, n_points=400, columns=20, contour=rect,
    )
    pts_on = _path_contour((1.2, 0.7, 15.8, 1.3), tool_radius_cm=0.2, **kw)   # bbox 已由调用方内缩
    ys = [p[1] for p in pts_on]
    assert max(ys) <= 13.0 + 1e-6 and min(ys) >= 7.0 - 1e-6                    # [0.7,1.3]cm → [7,13]mm
    pts_off = _path_contour((1.0, 0.5, 16.0, 1.5), **kw)                       # 未传 → 老行为
    ys0 = [p[1] for p in pts_off]
    assert abs(max(ys0) - 15.0) < 1e-6 and abs(min(ys0) - 5.0) < 1e-6


def test_path_contour_collapsed_columns_center_line(caplog):
    """带高 0.3 < 2R: 所有列收拢中线 6.5mm, 且 WARN 汇总一条。"""
    import logging
    import numpy as np
    from eit_ptlc.controller.cnc_path import _path_contour
    thin = np.asarray([[1.0, 0.5], [16.0, 0.5], [16.0, 0.8], [1.0, 0.8]])
    with caplog.at_level(logging.WARNING, logger="eit_ptlc.controller.cnc_path"):
        pts = _path_contour(
            (1.25, 0.65, 15.75, 0.65), x_offset_mm=0.0,
            plate_origin_x=0.0, plate_origin_y=0.0, flip_x=False, flip_y=False,
            n_points=400, columns=20, contour=thin, tool_radius_cm=0.25,
        )
    assert all(abs(p[1] - 6.5) < 1e-6 for p in pts)
    assert any("收拢中线" in rec.message for rec in caplog.records)


def test_compensation_insets_scrape_not_collect(tmp_path):
    """comp on: 刮扫 X/Y 各内缩 R(矩形轮廓); 收集数组逐点不变; margin 叠加内缩。"""
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    a_off = generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="contour")
    cfg_on = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=4.0, cutter_compensation=True))
    a_on = generate_scrape_arrays(s, "band_01", cfg_on, strategy="contour")
    # X: [10,160]mm → [12,158]mm; Y: [5,15]mm → [7,13]mm (R=2mm)
    assert abs(min(a_off.g_sx) - 10.0) < 1e-6 and abs(max(a_off.g_sx) - 160.0) < 1e-6
    assert abs(min(a_on.g_sx) - 12.0) < 1e-6 and abs(max(a_on.g_sx) - 158.0) < 1e-6
    assert abs(min(a_on.g_sy) - 7.0) < 1e-6 and abs(max(a_on.g_sy) - 13.0) < 1e-6
    # 收集路径不补偿: 逐点不变
    assert a_on.g_cx == a_off.g_cx and a_on.g_cy == a_off.g_cy
    # margin 每 +1mm → 每侧再 +1mm
    cfg_m = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=4.0, cutter_compensation=True,
                                  compensation_margin_mm=1.0))
    a_m = generate_scrape_arrays(s, "band_01", cfg_m, strategy="contour")
    assert abs(min(a_m.g_sx) - 13.0) < 1e-6 and abs(max(a_m.g_sx) - 157.0) < 1e-6


def test_compensation_off_zero_regression(tmp_path):
    """开关关(含 margin>0 但开关关)→ 数组与默认逐点相等。"""
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    a0 = generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="contour")
    cfg = GCodeCfg(tool=ToolCfg(cutter_compensation=False, compensation_margin_mm=5.0))
    a1 = generate_scrape_arrays(s, "band_01", cfg, strategy="contour")
    assert a0.g_sx == a1.g_sx and a0.g_sy == a1.g_sy and a0.g_cx == a1.g_cx and a0.g_cy == a1.g_cy


def test_compensation_narrow_band_single_center_column(tmp_path, caplog):
    """整带 X 跨 0.3cm ≤ 2R=0.4cm → 收拢中心单列(11.5mm), 仍正常刮(绝非占位)。"""
    import logging
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 1.3, "y_max": 1.5})
    cfg = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=4.0, cutter_compensation=True))
    with caplog.at_level(logging.WARNING, logger="eit_ptlc.controller.cnc_path"):
        a = generate_scrape_arrays(s, "band_01", cfg, strategy="contour")
    assert all(abs(v - 11.5) < 0.01 for v in a.g_sx)          # 中心 1.15cm, round(3) 后同一机床点
    assert a.pass_count == cfg.scrape.num_passes               # 不是占位不刮
    assert any(v != 0 for v in a.g_sy)
    assert any("中心单列" in rec.message for rec in caplog.records)


def test_compensation_keep_ratio_applies_after_erosion(tmp_path):
    """keep_ratio 作用在腐蚀后区间: 腐蚀 [7,13]mm × keep 0.5 → [8.5,11.5]mm。"""
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    cfg = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=4.0, cutter_compensation=True))
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="contour", keep_ratio=0.5)
    assert abs(max(a.g_sy) - 11.5) < 1e-6 and abs(min(a.g_sy) - 8.5) < 1e-6


def _write_summary_free_contour(dirpath, bbox, contour_xy):
    """任意多边形轮廓 summary(三角/梯形用, _write_band_summary_contour 只会写矩形)。"""
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "band_01_path.json").write_text(json.dumps({
        "scrape_path": {"bbox_cm": bbox},
        "contour_cm": [{"x_cm": x, "y_cm": y} for x, y in contour_xy],
    }), encoding="utf-8")
    s = dirpath / "summary.json"
    s.write_text(json.dumps(
        {"bands": [{"band_id": "band_01", "path_json": "band_01_path.json"}]}
    ), encoding="utf-8")
    return s


def _point_in_poly(poly, x, y):
    """射线法点在多边形内(独立 oracle, 不复用生产扫描线)。"""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xt = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < xt:
                inside = not inside
    return inside


def test_compensation_disk_inside_polygon_oracle(tmp_path):
    """独立 oracle: 每个刮扫点为圆心、0.92R 圆盘(16 方向)须整体落在轮廓内 —— 刀刃不越界的直接判据。
    尖角处腐蚀区间为空的列(收拢中线, 物理不可避免的过切)按生产同款判据跳过。"""
    import math as _m
    from eit_ptlc.controller.cnc_path import _erode_column_interval
    import numpy as np
    tri = [(1.0, 0.5), (6.0, 0.5), (6.0, 5.5)]                 # 斜边 slope=1
    s = _write_summary_free_contour(
        tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 6.0, "y_max": 5.5}, tri)
    cfg = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=5.0, cutter_compensation=True))  # R=0.25cm
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="contour")
    contour = np.asarray(tri)
    r_test = 0.25 * 0.92                                        # 采样近似 + round(3) 容差
    checked = 0
    for mx, my in zip(a.g_sx, a.g_sy):
        x_cm, y_cm = mx / 10.0, my / 10.0                       # 默认 lower-left 原点(0,0)无翻转
        ero = _erode_column_interval(contour, x_cm, 0.25, (1.0, 6.0), n_samples=201)
        if ero is None or ero[0] - ero[1] < 1e-9:
            continue                                            # 收拢列: 过切物理不可避免, 跳过
        for i in range(16):
            ang = 2.0 * _m.pi * i / 16.0
            px, py = x_cm + r_test * _m.cos(ang), y_cm + r_test * _m.sin(ang)
            assert _point_in_poly(tri, px, py), f"刀刃越界: 中心({x_cm},{y_cm}) 边缘({px},{py})"
        checked += 1
    assert checked > 300                                        # 绝大多数点被实际校验


def test_compensation_sloped_edge_beats_naive(tmp_path):
    """斜边列 top ≤ y_top−1.3R < 朴素恒减 R 的 y_top−R —— 弦高项在整链生效。"""
    tri = [(1.0, 0.5), (6.0, 0.5), (6.0, 5.5)]
    s = _write_summary_free_contour(
        tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 6.0, "y_max": 5.5}, tri)
    cfg = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=5.0, cutter_compensation=True))
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="contour")
    hit = [(mx / 10.0, my / 10.0) for mx, my in zip(a.g_sx, a.g_sy) if 2.85 < mx / 10.0 < 3.15]
    assert hit                                                  # 该窗口至少一列
    for x_cm, y_cm in hit:
        naive_top = (0.5 + (x_cm - 1.0)) - 0.25                 # 斜边 y_top(x) − R
        assert y_cm <= naive_top - 0.25 * 0.3                   # 至少再紧 0.3R


def test_compensation_shrinks_coverage_columns(tmp_path):
    """spec 测试清单#6: 覆盖列数按内缩后 X 跨度推导 — 大刀径下 comp on 列数应少于 off。

    band X 跨 13.9cm、20mm 刀(step=20×0.6=12mm): off 跨 139mm→ideal 12→取因子 16 列;
    on 内缩 2R=20mm→跨 119mm→ideal 10→恰为因子 10 列。boustrophedon_columns=1 关掉
    用户列数下限(默认 20 会盖住差异)。列数以 g_sx 去重计数观测。
    """
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 14.9, "y_max": 1.5})
    kw = dict(boustrophedon_columns=1)
    a_off = generate_scrape_arrays(
        s, "band_01", GCodeCfg(**kw, tool=ToolCfg(cutter_diameter_mm=20.0)), strategy="contour")
    a_on = generate_scrape_arrays(
        s, "band_01",
        GCodeCfg(**kw, tool=ToolCfg(cutter_diameter_mm=20.0, cutter_compensation=True)),
        strategy="contour")
    cols_off = len({round(v, 3) for v in a_off.g_sx})
    cols_on = len({round(v, 3) for v in a_on.g_sx})
    assert cols_off == 16 and cols_on == 10


# ---------------------------------------------------------------------------
# 刮取粉量 (面积 × 切深 × 松散系数) —— 只给物料账本与三维, 不下发 PLC
# ---------------------------------------------------------------------------

def test_scrape_area_from_contour_shoelace(tmp_path):
    """真实轮廓面积走鞋带公式, 而不是 bbox —— L 形轮廓的两者差得开。

    L 形: 外接 bbox 4×4=16cm², 真实面积 16−(2×2)=12cm²。若哪天有人把面积换回 bbox,
    这条会立刻红 —— 挑 L 形正是因为矩形/正方形下两者恰好相等, 测不出区别。
    """
    ell = [(1.0, 1.0), (5.0, 1.0), (5.0, 3.0), (3.0, 3.0), (3.0, 5.0), (1.0, 5.0)]
    s = _write_summary_free_contour(
        tmp_path, {"x_min": 1.0, "y_min": 1.0, "x_max": 5.0, "y_max": 5.0}, ell)
    a = generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="contour")

    assert a.scrape_area_source == "contour", a.scrape_area_source
    assert abs(a.scrape_area_mm2 - 1200.0) < 1e-6, a.scrape_area_mm2   # 12cm² = 1200mm²
    # bbox 面积会是 1600mm², 与真值差 33%
    assert a.scrape_area_mm2 < 1600.0


def test_scrape_area_falls_back_to_bbox_without_contour(tmp_path):
    """老 summary 没有 contour_cm 时退回 bbox 面积, 并把来源标成 bbox(而不是静默假装量过)。"""
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 3.0, "y_max": 1.5})
    a = generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="boustrophedon")

    assert a.scrape_area_source == "bbox", a.scrape_area_source
    assert abs(a.scrape_area_mm2 - 200.0) < 1e-6, a.scrape_area_mm2   # 2cm×1cm = 2cm² = 200mm²


def test_scrape_volume_uses_total_depth_not_per_pass(tmp_path):
    """体积 = 面积 × **总**切深 × 松散系数 —— 既不乘 pass 数, 也不用每刀深度。

    用 num_passes=2 跑: 若误写成 depth_per_pass 体积会减半, 若误乘 pass 数会翻倍,
    两种错都被这条挡住 (cnc_path 里 depth_per_pass = total_depth_mm / g_pass_count
    就是"total_depth_mm 是总深"的证据)。
    """
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 3.0, "y_max": 1.5})
    cfg = GCodeCfg(scrape=ScrapeCfg(total_depth_mm=1.0, num_passes=2, bulk_factor=1.6))
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="boustrophedon")

    assert a.pass_count == 2                                  # 确实分了两刀
    assert abs(a.scrape_volume_mm3 - 200.0 * 1.0 * 1.6) < 1e-6, a.scrape_volume_mm3

    # 松散系数只缩放体积, 不碰面积; 默认 1.0 时体积恒等于面积×深度(零回归)
    a_plain = generate_scrape_arrays(
        s, "band_01", GCodeCfg(scrape=ScrapeCfg(total_depth_mm=1.0, num_passes=2)),
        strategy="boustrophedon")
    assert abs(a_plain.scrape_area_mm2 - a.scrape_area_mm2) < 1e-9
    assert abs(a_plain.scrape_volume_mm3 - 200.0) < 1e-6, a_plain.scrape_volume_mm3


def test_placeholder_carries_zero_powder_keys():
    """安全占位也必须带齐三个键(值为 0/空) —— 物料侧的 scrape_arm 靠 result 取键,
    键缺了会静默不记账而不是报错。"""
    res = safe_placeholder_arrays(GCodeCfg()).as_action_result()
    assert res["scrape_area_mm2"] == 0.0
    assert res["scrape_area_source"] == ""
    assert res["scrape_volume_mm3"] == 0.0


def test_action_result_exposes_powder_keys(tmp_path):
    """三个键必须出现在 as_action_result() 里 —— 那是 VM 与物料账本唯一的取数口。"""
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 3.0, "y_max": 1.5})
    a = generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="boustrophedon")
    res = a.as_action_result()

    assert res["scrape_area_mm2"] == a.scrape_area_mm2
    assert res["scrape_area_source"] == a.scrape_area_source
    assert res["scrape_volume_mm3"] == a.scrape_volume_mm3
    # 但**不许**混进 PLC 块写字典: 真机 6 变量契约不容多字段
    assert not (set(a.as_plc_dict()) - _PLC_KEYS)


def test_loader_rejects_out_of_range_bulk_factor():
    from eit_ptlc.config.loader import _parse_gcode
    with pytest.raises(ValueError):
        _parse_gcode({"scrape": {"bulk_factor": 0.1}})
    with pytest.raises(ValueError):
        _parse_gcode({"scrape": {"bulk_factor": 9.0}})
    cfg = _parse_gcode({"scrape": {"bulk_factor": 1.6}})
    assert abs(cfg.scrape.bulk_factor - 1.6) < 1e-9
    # 不写就是 1.0(零回归)
    assert abs(_parse_gcode({}).scrape.bulk_factor - 1.0) < 1e-9


if __name__ == "__main__":
    sys.exit(main())
