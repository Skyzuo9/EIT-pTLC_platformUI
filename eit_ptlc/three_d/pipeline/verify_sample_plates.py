"""上样孔板验收: 板放得进巢吗、针够得着孔底吗、抬起时过得了板顶吗、与控制侧标定对得上吗。

为什么要有它: 这四件事全都**不会自己报错**. 板画歪一毫米、针抬不过板沿、标定与几何差一倍
—— 模型照样导出、轴照样走、没有任何既有指标会说一句话(与 verify_plate_clearance /
verify_plate_seats 同一条理由). 尤其第四条: 控制侧 config/calibration.yaml 那两块 4×6 板
的标定是**真机下发孔位的依据**, 三维这边一量就能看出它跟几何对不上, 这个信息不报出来
就永远没人知道.

测量在 03 步(blender_clean.build_sample_plates)一次做完并写进
work/03_clean_model.report.json; 本脚本只读报告做算术, 所以**不起 Blender, 秒级返回**,
改判据也不用重跑管线.

三档结论:
    · 硬失败(退出 1) —— 板与巢的几何对不上(装不进去/没坐在台肩上/孔距不对);
    · 告警(退出 0)   —— 净空偏小、控制侧标定与几何不一致; 这类要现场量, 不是三维能定的;
    · 通过(退出 0).

⚠ 与 CLAUDE.md 第 37 条一致: 失败提示里写"先查什么", 不写死"已知病因" ——
   上一次把病因写死在提示里, 错误结论被抄进两份文档反过来当了依据.

用法:
    python verify_sample_plates.py
    python verify_sample_plates.py --no-fail      # 只报不判红(重建链里想放行时用)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from common import load_config, log, write_report

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_twin_manifest import read_yaml  # noqa: E402  (同目录模块, 复用其 YAML 读取)

#: 孔距允许偏差(mm). 生成器是解析式的, 这里只防"规格表被改坏"这类低级错.
PITCH_TOL_MM = 0.05

#: 板底与台肩的允许缝隙(mm). 板是**坐**在台肩上的, 理论值恒为 0.
SEAT_GAP_TOL_MM = 0.01

#: 板顶与上方固定件的净空低于它就告警(mm). 不是硬判据 —— 真机换个板厂、垫张纸都能吃掉几毫米.
CLEARANCE_WARN_MM = 15.0

#: 标定与几何差 2 倍那件事的溯源文档. 告警里带上它, 免得下次又从头查一遍
#: (2026-08-05 已排除 PLC 代码层与工程文件层, 落点在轴标度或驱动器电子齿轮比).
CALIB_DOC = "docs/上样4X标度溯源_孔位标定与几何差2倍_20260805.md"

#: 5Z 的"抬针位"控制侧 mm. 不是猜的: `Sampling_L2/A50_absorb_吸收液体` 的 step 0 与 step 40
#: 都写死 `上样轴5Z轴DATE.fAbsTarget:=0`, 且 4X 的移动门禁是 `上样轴5Z轴DATE.fActPos<3`(抬起).
RAISE_MM = 0.0

#: 4X 那个 2.0 增益的临时措施档案(换伺服后作废)。判据失败时指过去, 省得再查一遍。
TEMP_GAIN_DOC = "docs/上样4X_5Z临时标度增益_换伺服后作废_20260806.md"

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))


def _overlap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """功能: 一维区间重叠长度. 参数: 两个区间. 返回值: float, 不重叠为 0"""
    return max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))


def check_geometry(sp: dict, problems: list, warnings: list) -> None:
    """
    功能: 板与巢的几何自洽 —— 装得进、坐得住、孔距对.
    参数: sp 报告里的 sample_plates 段; problems/warnings 结果收集器
    返回值: None
    """
    foot = sp["footprint_mm"]
    for slot in sp["slots"]:
        tag = f'盘位{slot["slot"]}({slot["node"]})'
        for axis, name in ((0, "长"), (1, "宽")):
            gap = slot["nest_size_mm"][axis] - foot[axis]
            if gap < 0:
                problems.append(
                    f"{tag} {name}边放不进巢: 巢 {slot['nest_size_mm'][axis]:.2f} < "
                    f"板 {foot[axis]:.2f}mm. 先查 sample_plates.installed 选的规格对不对, "
                    f"再查这个巢是不是根本不是孔板位")
        # 板底 = 落板面: 由 build_sample_plates 直接按台肩高度落位, 差值恒 0; 一旦不为 0
        # 说明落位代数被动过.
        gap = abs(slot["top_z_mm"] - slot["seat_z_mm"] - sp["height_mm"])
        if gap > SEAT_GAP_TOL_MM:
            problems.append(
                f"{tag} 板高对不上: 顶面 {slot['top_z_mm']:.3f} − 落板 {slot['seat_z_mm']:.3f} "
                f"≠ 规格高 {sp['height_mm']:.3f}mm. 先查 labware_geom 的规格表, "
                f"再查 build_sample_plates 的落位代数")

    # 孔距: 从实际写进模型的孔心反推, 而不是复述规格表 —— 复述等于什么都没验
    for slot in sp["slots"]:
        wells = slot["wells"]
        by_row = {}
        by_col = {}
        for w in wells:
            by_row.setdefault(w["row"], []).append(w)
            by_col.setdefault(w["col"], []).append(w)
        cols = sorted(by_col)
        xs = [sorted(by_col[c], key=lambda w: w["col"])[0]["center"][0] for c in cols]
        steps = [(xs[i + 1] - xs[i]) * 1000 for i in range(len(xs) - 1)]
        for step in steps:
            if abs(step - sp["pitch_mm"]) > PITCH_TOL_MM:
                problems.append(
                    f'盘位{slot["slot"]} 列距实测 {step:.4f} ≠ {sp["pitch_mm"]}mm. '
                    f"先查 labware_geom.well_centers, 再查规格表的 pitch_mm")
                break
        if len(wells) != 24:
            problems.append(f'盘位{slot["slot"]} 孔数 {len(wells)} ≠ 24')


def check_needle(sp: dict, problems: list, warnings: list) -> None:
    """
    功能: 针的可达性与净空 —— 够得着孔底、抬起时过得了板顶、板顶与扶针器不打架.
    参数: sp; problems/warnings
    返回值: None
    """
    refs = sp.get("clearance_refs") or {}
    needle = refs.get("needle")
    if not needle:
        warnings.append("没量到上样针, 跳过可达性判据(检查 sample_plates.clearance_refs.needle)")
        return
    tip_z = needle["min_mm"][2]
    slot = sp["slots"][0]
    well_bottom = slot["seat_z_mm"] + (sp["height_mm"] - sp["well_depth_mm"])
    top_z = slot["top_z_mm"]
    log(f"针尖 CAD 静位 z={tip_z:.2f}mm; 孔底 z={well_bottom:.2f}mm; 板顶 z={top_z:.2f}mm")
    log(f"  → 要够到孔底, 5Z 需从 CAD 位抬 {well_bottom - tip_z:+.2f}mm; "
        f"要越过板顶需抬 {top_z - tip_z:+.2f}mm")

    guide = refs.get("guide")
    if guide:
        # 只有在 XY 上真重叠才谈净空 —— 两者分属 3Y 与 4X 两根轴, 不重叠就永远碰不到
        ov_x = _overlap(guide["min_mm"][0], guide["max_mm"][0],
                        slot["nest_center_mm"][0] - sp["footprint_mm"][0] / 2,
                        slot["nest_center_mm"][0] + sp["footprint_mm"][0] / 2)
        ov_y = 0.0
        for s in sp["slots"]:
            ov_y = max(ov_y, _overlap(
                guide["min_mm"][1], guide["max_mm"][1],
                s["nest_center_mm"][1] - sp["footprint_mm"][1] / 2,
                s["nest_center_mm"][1] + sp["footprint_mm"][1] / 2))
        clear = guide["min_mm"][2] - top_z
        if ov_x > 0 and ov_y > 0:
            msg = (f'板顶与扶针器({guide["part"]})净空 {clear:.2f}mm '
                   f'(XY 重叠 {ov_x:.1f}×{ov_y:.1f}mm)')
            if clear < 0:
                problems.append(
                    msg + " —— 已经是负的, 板直接顶在扶针器上. 先查 installed 选的规格, "
                          "再查巢的落板面是不是量错了")
            elif clear < CLEARANCE_WARN_MM:
                warnings.append(msg + f" —— 低于 {CLEARANCE_WARN_MM}mm 提醒线, 换更高的板前先现场量")
            else:
                log("  → " + msg)


def check_needle_travel(sp: dict, eit_root: str, problems: list, warnings: list) -> dict:
    """
    功能: 拿 5Z 的标定三元组, 把 HMI 示教的"升降/下探"两档换算成针尖高度并断言落点.

    为什么非要有它: 2026-08-06 查出 `axis_5z` 的 `sign` 与 `zero_offset_mm` **一起反了**
    (sign 来自已被 CLAUDE.md 第 35 条判死的"动作页实拖判定"), 而两个错误在 mm=0 处**恰好抵消**
    —— 于是静止画面看不出任何异常, 只有真机走到非零位时才暴露。这类"互相掩盖的成对错误"
    靠目检永远抓不到, 必须有一条把**三件事同时锁住**的判据: sign、zero_offset、所装板规格。

    判据(两条, 都可失败):
      1. 下探位(HMI slot 2)针尖必须落在**孔内** —— 高于孔底、低于板顶;
      2. 抬起位(A50 里写死的 `fAbsTarget:=0`)针尖必须**高于板顶**, 否则横移必撞板。
    第 2 条正是"15mL 板会撞"的来源: 抬起位针尖只到 125.01, 而 15mL 板顶在 137.70。

    换算与前端 `MachineStateDriver.setAxisMm` 同式: `δ = (mm − zeroOffsetMm) × sign`,
    沿轴向量施加。轴向量取自 rig_map(glTF 系), 本轴是 [0,1,0] 即 glTF +Y = **Blender +Z**,
    与报告里的 min_mm/seat_z_mm 同系, 故 δ 可直接加在 Blender Z 上; 不是这个轴向就拒绝判断,
    免得在别的朝向上悄悄算错(硬约束 10: Blender Z 上 / glTF Y 上)。

    参数: sp 报告的 sample_plates 段; eit_root 上位机根; problems/warnings 收集器
    返回值: dict, 换算明细(写进报告)
    """
    needle = (sp.get("clearance_refs") or {}).get("needle")
    if not needle:
        warnings.append("没量到上样针, 跳过 5Z 行程判据")
        return {}

    rig = read_yaml(os.path.join(PIPELINE_DIR, "rig_map.yaml")) or {}
    axis = next((a for a in (rig.get("axes") or []) if a.get("id") == "axis_5z"), None)
    if not axis:
        warnings.append("rig_map 里找不到 axis_5z, 跳过 5Z 行程判据")
        return {}
    if [int(v) for v in (axis.get("axis") or [])] != [0, 1, 0]:
        warnings.append(
            f'axis_5z 的轴向量是 {axis.get("axis")} 而非 [0,1,0](glTF +Y=上), '
            "本判据只在竖直轴上成立, 已跳过 —— 轴向真变了要先改这里的换算")
        return {}
    sign = float(axis.get("sign", 1))
    zero = float(axis.get("zero_offset_mm", 0.0))

    teach = read_yaml(os.path.join(eit_root, "config", "points", "plc", "sampling.yaml")) or {}
    by_key = {str(t.get("key")): t for t in (teach.get("plc_servo_target") or [])}
    dip = by_key.get("sample_5z_dip")
    if dip is None or dip.get("value") is None:
        warnings.append("points/plc/sampling.yaml 里没有 sample_5z_dip 的值, 跳过下探判据")
        return {}

    tip = float(needle["min_mm"][2])
    slot = sp["slots"][0]
    floor = slot["seat_z_mm"] + (sp["height_mm"] - sp["well_depth_mm"])   # 孔底
    top = slot["top_z_mm"]

    def tip_at(mm: float) -> float:
        """功能: 控制侧 mm → 针尖 Blender Z. 参数: mm. 返回值: float"""
        return tip + (mm - zero) * sign

    z_dip = tip_at(float(dip["value"]))
    z_up = tip_at(RAISE_MM)
    detail = {
        "sign": sign, "zero_offset_mm": zero,
        "tip_cad_z_mm": round(tip, 3), "well_bottom_z_mm": round(floor, 3),
        "plate_top_z_mm": round(top, 3),
        "dip_mm": float(dip["value"]), "dip_tip_z_mm": round(z_dip, 3),
        "raise_mm": RAISE_MM, "raise_tip_z_mm": round(z_up, 3),
    }
    log(f'5Z 行程(sign={sign:+.0f} zero={zero:+.2f}): '
        f'下探 {dip["value"]}mm → 针尖 {z_dip:.2f}(孔底 {floor:.2f}); '
        f'抬起 {RAISE_MM}mm → 针尖 {z_up:.2f}(板顶 {top:.2f})')

    if not (floor <= z_dip <= top):
        where = "低于孔底(会扎穿板)" if z_dip < floor else "高于板顶(根本没进孔)"
        problems.append(
            f"5Z 下探位针尖 z={z_dip:.2f} 不在孔内 [{floor:.2f}, {top:.2f}] —— {where}. "
            f"先查 axis_5z 的 sign/zero_offset_mm 是不是成对反了(见 CLAUDE.md 第 35/37 条), "
            f"再查 sample_plates.installed 选的规格与示教值是不是同一批")
    if z_up <= top:
        problems.append(
            f"5Z 抬起位针尖 z={z_up:.2f} 没高过板顶 {top:.2f}(差 {top - z_up:.2f}mm) —— "
            f"针抬到头仍在板里, 横移必撞. 先查 installed 选的板高不高了, "
            f"再查 axis_5z 的 zero_offset_mm 够不够抬")
    else:
        log(f"  → 抬起位高出板顶 {z_up - top:.2f}mm(可横移)")
    return detail


def check_well_reachable(sp: dict, eit_root: str, problems: list, warnings: list) -> dict:
    """
    功能: 把控制侧标定的孔位目标按 manifest 轴模型驱动到针上, 断言它落在**对应盘位的那个孔**里.

    这条判据是本文件里最值钱的一条, 因为它**同时锁住四件互相独立的东西**:
      · `axis_4x.scale_mm`(2026-08-06 卡尺定案的 2.0 增益)
      · `axis_4x.zero_offset_mm`(77.68)
      · `axis_3y.zero_offset_mm`(20.70)
      · **盘位编号与控制侧 plate_no 的对齐**(编反过一次, 见 rig_map 的 slot_order)
    这四个里任意一个错, 针就落不进孔 —— 而它们**单看每一个都像是对的**
    (2026-08-06 之前就是四个错了三个, 画面照常渲染、无任何报错)。

    换算与前端 `MachineStateDriver.setAxisMm` 同式: `δ = (mm − zeroOffsetMm) × sign × scaleMm`,
    沿 manifest 的 `axis`(glTF)施加。glTF (x,y,z) → Blender (x, −z, y) 换到报告的坐标系。

    参数: sp 报告的 sample_plates 段; eit_root; problems/warnings
    返回值: dict, 逐孔明细(写进报告)
    """
    manifest_path = os.path.join(PIPELINE_DIR, "..", "models", "device-manifest.json")
    if not os.path.isfile(manifest_path):
        warnings.append("还没有 device-manifest.json(首次构建), 跳过孔位可达判据")
        return {}
    with open(manifest_path, "r", encoding="utf-8") as handle:
        axes = {a["id"]: a for a in (json.load(handle) or {}).get("axes") or []}
    needle = (sp.get("clearance_refs") or {}).get("needle")
    if not needle or not {"axis_4x", "axis_3y"} <= set(axes):
        warnings.append("缺针或缺 4X/3Y 轴条目, 跳过孔位可达判据")
        return {}

    # eit_root 是 <仓根>/eit_ptlc, 它的父目录才是包的可导入位置
    repo_root = os.path.abspath(os.path.join(eit_root, ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        from eit_ptlc.controller.plate_affine import Well
        from eit_ptlc.controller.plate_catalog import PlateCatalog
    except Exception as exc:                       # 上位机包不可导入时降级为告警, 不挡构建
        warnings.append(f"导入 controller.plate_* 失败({exc}), 跳过孔位可达判据")
        return {}
    catalog = PlateCatalog.load(
        _existing(os.path.join(eit_root, "config", "plates.yaml")),
        _existing(os.path.join(eit_root, "config", "calibration.yaml")))

    tip = [(needle["min_mm"][0] + needle["max_mm"][0]) / 2,
           (needle["min_mm"][1] + needle["max_mm"][1]) / 2]

    def blender_dir(axis_vec: list) -> tuple:
        """功能: glTF 轴向量 → Blender 的 (x, y) 分量. 参数: axis_vec. 返回值: tuple"""
        return (float(axis_vec[0]), -float(axis_vec[2]))

    def delta(axis_id: str, mm: float) -> tuple:
        """功能: 该轴走到 mm 时在 Blender XY 上的位移. 参数: axis_id/mm. 返回值: (dx, dy)"""
        a = axes[axis_id]
        d = (mm - float(a.get("zeroOffsetMm", 0.0))) \
            * float(a.get("sign", 1)) * float(a.get("scaleMm", 1.0))
        bx, by = blender_dir(a.get("axis", [1, 0, 0]))
        return (d * bx, d * by)

    slots = {s["slot"]: s for s in sp["slots"]}
    half = sp["well_top_mm"] / 2.0                 # 方孔开口半边长, 判"落没落进孔"
    out: dict = {"checked": [], "well_half_mm": round(half, 3)}
    # 报告里的 grid 就是 "4×6", 与 calibration.yaml 的 plate_type / 动作参数 plate_spec 同值
    spec_name = str(sp.get("grid") or "4×6")

    for slot_no, slot in sorted(slots.items()):
        try:
            inst = catalog.instance_for(spec_name, int(slot_no))
        except Exception as exc:
            warnings.append(f"盘位{slot_no} 在 calibration.yaml 里没有对应实例({exc}), 跳过")
            continue
        if not inst.is_calibrated:
            warnings.append(f"盘位{slot_no}({inst.id}) 未标定, 跳过孔位可达判据")
            continue
        wells = {w["well"]: w for w in slot["wells"]}
        worst = None
        for label in ("A1", "A6", "D1", "D6"):     # 四个角孔就够钉死仿射的四个自由度
            if label not in wells:
                continue
            row = ord(label[0]) - ord("A") + 1
            x_mm, y_mm = catalog.well_target(inst.id, Well(row, int(label[1:])))
            dx3, dy3 = delta("axis_3y", y_mm)      # 列沿 3Y
            dx4, dy4 = delta("axis_4x", x_mm)      # 行沿 4X
            nx, ny = tip[0] + dx3 + dx4, tip[1] + dy3 + dy4
            # ⚠ 键名: 03 报告里叫 `center`(米), manifest 里才叫 `centerM` —— 别拿混了
            cx, cy = wells[label]["center"][0] * 1000, wells[label]["center"][1] * 1000
            ex, ey = nx - cx, ny - cy
            out["checked"].append({
                "slot": slot_no, "well": label,
                "target_4x_mm": x_mm, "target_3y_mm": y_mm,
                "needle_mm": [round(nx, 3), round(ny, 3)],
                "well_mm": [round(cx, 3), round(cy, 3)],
                "err_mm": [round(ex, 3), round(ey, 3)],
            })
            if worst is None or max(abs(ex), abs(ey)) > worst[1]:
                worst = (label, max(abs(ex), abs(ey)), ex, ey)
        if worst is None:
            continue
        label, err, ex, ey = worst
        log(f"  盘位{slot_no}({inst.id}) 最差角孔 {label}: 针偏 ΔX(沿3Y)={ex:+.2f} "
            f"ΔY(沿4X)={ey:+.2f} mm (孔半边 {half:.2f})")
        if err > half:
            problems.append(
                f"盘位{slot_no} 的 {label} 针没落进孔: 偏 ΔX={ex:+.2f} ΔY={ey:+.2f}mm, "
                f"超出孔半边 {half:.2f}mm。按可能性排查: "
                f"① 盘位编号与控制侧 plate_no 是否对齐(rig_map.sample_plates.slot_order); "
                f"② axis_4x.scale_mm 是否仍是实测的 2.0(见 {TEMP_GAIN_DOC}); "
                f"③ axis_3y / axis_4x 的 zero_offset_mm; ④ 装的板规格与标定是否同一批")
    return out


def _existing(path: str):
    """功能: 存在则回 Path, 否则回 None(交给 PlateCatalog 走缺省). 参数: path. 返回值: Path|None"""
    from pathlib import Path
    return Path(path) if os.path.isfile(path) else None


def check_calibration(sp: dict, eit_root: str, warnings: list) -> dict:
    """
    功能: 拿控制侧 config/calibration.yaml 的 3 点仿射与三维实测的巢几何对一对.

    这不是三维的判据, 而是**三维顺手能发现的控制侧问题**: 标定是真机下发孔位的唯一依据,
    它跟几何差多少, 只有把两边摆在一起才看得见. 一律只告警不判红 —— 谁对谁错要现场
    jog 复核, 不是三维能定的.

    参数: sp; eit_root 上位机根(= PTLC_CONTROL_ROOT, 即 .../eit_ptlc, 内含 config/); warnings
    返回值: dict, 对比明细(写进报告)
    """
    path = os.path.join(eit_root, "config", "calibration.yaml")
    if not os.path.isfile(path):
        warnings.append(f"没找到 {path}, 跳过标定交叉核对")
        return {}
    doc = read_yaml(path) or {}
    out = {"file": path, "instances": []}
    # 巢间距(沿 4X = 世界 Y)由三维实测; 列距(沿 3Y = 世界 X)是板规格
    centers_y = sorted(s["nest_center_mm"][1] for s in sp["slots"])
    geom_slot_gap = abs(centers_y[1] - centers_y[0]) if len(centers_y) > 1 else None

    for inst in doc.get("instances") or []:
        pts = inst.get("points") or []
        if len(pts) < 3:
            continue
        by_well = {(p["well"][0], p["well"][1]): p for p in pts}
        row_pitch = col_pitch = None
        # 列沿 3Y(y_mm), 行沿 4X(x_mm) —— 见 controller/plate_affine.Well 的定义
        if (1, 1) in by_well and (1, 6) in by_well:
            col_pitch = (by_well[(1, 6)]["y_mm"] - by_well[(1, 1)]["y_mm"]) / 5.0
        if (1, 1) in by_well and (4, 1) in by_well:
            row_pitch = (by_well[(4, 1)]["x_mm"] - by_well[(1, 1)]["x_mm"]) / 3.0
        out["instances"].append({
            "id": inst.get("id"), "plate_type": inst.get("plate_type"), "slot": inst.get("slot"),
            "col_pitch_mm": None if col_pitch is None else round(col_pitch, 4),
            "row_pitch_mm": None if row_pitch is None else round(row_pitch, 4),
            "a1_x_mm": by_well.get((1, 1), {}).get("x_mm"),
        })
        for label, got in (("列距", col_pitch), ("行距", row_pitch)):
            if got is None or abs(got - sp["pitch_mm"]) <= 0.2:
                continue
            ratio = sp["pitch_mm"] / got if got else 0.0
            # 2026-08-06 定案: 沿 4X 的"行距"差恰是 2 倍, 病根是**那根轴的标度**
            # (控制侧 1mm = 物理 2mm, 卡尺实测 11.28→22.6), **不是标定表填错**。
            # 所以这条不再让人去查 calibration.yaml —— 那会把人引到已经排除过的方向上。
            if abs(ratio - 2.0) < 0.05:
                warnings.append(
                    f'标定 {inst.get("id")} 的{label} {got:.2f}mm ≈ 孔板规格 '
                    f'{sp["pitch_mm"]}mm 的 1/2 —— 这是**已定案**的 4X 标度问题'
                    f'(控制侧 1mm = 物理 2mm), 标定表本身是对的, **别去改它**。'
                    f'三维已用 axis_4x.scale_mm=2.0 补偿; 该增益是临时的, 换伺服后作废: {TEMP_GAIN_DOC}')
            else:
                warnings.append(
                    f'标定 {inst.get("id")} 的{label} {got:.2f}mm 与孔板规格 '
                    f'{sp["pitch_mm"]}mm 不一致(差 {got - sp["pitch_mm"]:+.2f}, 比值 {ratio:.3f})'
                    f' —— **不是**已知的 2× 那一档, 属新情况。先查装的板规格与标定是否同一批, '
                    f'再查 4X/3Y 的标度。背景见 {CALIB_DOC}')

    xs = [i["a1_x_mm"] for i in out["instances"]
          if i["plate_type"] == "4×6" and i["a1_x_mm"] is not None]
    if len(xs) > 1 and geom_slot_gap:
        calib_gap = abs(max(xs) - min(xs))
        out["slot_gap_mm"] = {"calibration": round(calib_gap, 3), "geometry": round(geom_slot_gap, 3)}
        if abs(calib_gap - geom_slot_gap) > 1.0:
            ratio = geom_slot_gap / calib_gap if calib_gap else 0.0
            if abs(ratio - 2.0) < 0.05:
                # 同上: 这是 4X 标度的 2×, 不是标定错。顺带把"标定表自身那 0.5mm"点出来 ——
                # 按精确 2× 盘距应是 56.0 而非 55.5, 那 1mm 正是孔位判据里 ±0.5 残差的来源。
                warnings.append(
                    f"两个盘位间距: 标定 {calib_gap:.1f}mm × 2 = {calib_gap * 2:.1f}mm vs "
                    f"三维实测巢心距 {geom_slot_gap:.1f}mm —— **已定案**的 4X 2× 标度, "
                    f"标定表是对的。(顺带: 按精确 2× 该填 {geom_slot_gap / 2:.1f} 而非 "
                    f"{calib_gap:.1f}, 那 {abs(geom_slot_gap - calib_gap * 2):.1f}mm 就是孔位判据里 "
                    f"±0.5mm 残差的来源。) 增益是临时的: {TEMP_GAIN_DOC}")
            else:
                warnings.append(
                    f"两个盘位的间距: 标定说 {calib_gap:.1f}mm, 三维实测巢心距 {geom_slot_gap:.1f}mm "
                    f"(比值 {ratio:.3f}) —— **不是**已知的 2× 那一档, 属新情况。"
                    f"先查盘位编号是否与 plate_no 对齐, 再查 4X 标度。背景见 {CALIB_DOC}")
    return out


def main() -> int:
    """功能: 主流程. 参数: 无. 返回值: int, 退出码"""
    parser = argparse.ArgumentParser(description="上样孔板验收")
    parser.add_argument("--report", default="", help="03 步报告路径; 缺省取 work/03_clean_model.report.json")
    parser.add_argument("--no-fail", action="store_true", help="只报不判红")
    args = parser.parse_args()

    config = load_config()
    report_path = args.report or os.path.join(config["paths"]["work"], "03_clean_model.report.json")
    if not os.path.isfile(report_path):
        raise SystemExit(f"错误: 未找到 {report_path}\n请先运行 03_clean_model.py --stage full")
    with open(report_path, "r", encoding="utf-8") as handle:
        sp = (json.load(handle) or {}).get("sample_plates") or {}
    if not sp or sp.get("skipped"):
        log(f"上样孔板未生成({sp.get('skipped', '报告里没有 sample_plates 段')}), 跳过验收")
        return 0

    problems: list = []
    warnings: list = []
    log(f'规格 {sp["label"]} ({sp["installed"]}): {sp["grid"]}, 孔距 {sp["pitch_mm"]}mm, '
        f'单孔 {sp["well_volume_ml"]}mL (标称 {sp["nominal_ml"]}), 每块 {sp["tris_each"]} 三角')
    for slot in sp["slots"]:
        log(f'  盘位{slot["slot"]}: 巢 {slot["nest_size_mm"][0]:.2f}×{slot["nest_size_mm"][1]:.2f} '
            f'@({slot["nest_center_mm"][0]:.2f},{slot["nest_center_mm"][1]:.2f}), '
            f'落板 z={slot["seat_z_mm"]:.2f} 顶面 z={slot["top_z_mm"]:.2f}, '
            f'间隙 {slot["nest_size_mm"][0] - sp["footprint_mm"][0]:.2f}/'
            f'{slot["nest_size_mm"][1] - sp["footprint_mm"][1]:.2f}mm')

    check_geometry(sp, problems, warnings)
    check_needle(sp, problems, warnings)
    # 与 gen_twin_manifest.DEFAULT_EIT_ROOT 同一约定: PTLC_CONTROL_ROOT 指的是**内含
    # config/ 的那一层**(即 <仓根>/eit_ptlc), 不是仓根. 兜底按 three_d 的父目录推。
    eit_root = os.environ.get("PTLC_CONTROL_ROOT") or os.path.abspath(
        os.path.join(config["paths"]["root"], ".."))
    travel = check_needle_travel(sp, eit_root, problems, warnings)
    reach = check_well_reachable(sp, eit_root, problems, warnings)
    calib = check_calibration(sp, eit_root, warnings)

    write_report(os.path.join(config["paths"]["work"], "sample_plates.verify.json"), {
        "installed": sp["installed"], "slots": [
            {k: v for k, v in s.items() if k != "wells"} for s in sp["slots"]],
        "needle_travel": travel,
        "well_reachable": reach,
        "calibration_crosscheck": calib,
        "problems": problems, "warnings": warnings,
    })

    for text in warnings:
        log(f"⚠ 告警: {text}")
    if problems:
        for text in problems:
            log(f"✗ 失败: {text}")
        if args.no_fail:
            log(f"上样孔板验收: {len(problems)} 项失败(--no-fail, 不判红)")
            return 0
        return 1
    log(f"上样孔板验收: 通过 ({len(warnings)} 项告警)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
