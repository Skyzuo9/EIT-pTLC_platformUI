"""板落点验收: 机器人取放示教点 ↔ 三维板锚点 的残差, 按翻转态分组核对。

为什么要有它: 2026-08-03 之前这条误差没有任何人看着 —— 板被画成一条线, 谁也看不出它
同时还错位了几十到几百毫米。等板画对了才发现取放处肉眼穿模。**这类错不会自己冒出来**,
只能靠一个每次生成前都跑的判据。

判据: 把"法兰 → 板锚点"这个向量转到**法兰自己的坐标系**里, 它就是"板面相对吸盘"的
纯刀具几何常量 —— 同一把刀、同一翻转态下, **与站无关、与机械臂朝向无关**, 各站必须一致。

为什么必须转到法兰系而不是直接比世界向量: 各站在机器上位置不同、机械臂到各站的偏航
也不同, 世界系下的水平分量本来就该不一样, 没法跨站比。转进法兰系后偏航被除掉,
剩下的差异只可能来自"板锚点不在它该在的地方"。

这一条同时抓得住两类错(世界系竖直比对只抓得住第一类):
  竖直向的 —— 上料仓/废板仓的板堆锚点没随 1Z/2Z 顶升(实测差 534mm);
  水平向的 —— 点样座 7Y(99mm)、刮板台 8Y(35mm)的板托座骑在没被驱动的工位轴上。
              (2026-08-04 订正: 刮板台那根此前误记为 9X, 实为 8Y —— 9X 载的是刀不是板)

任一项不一致, 都指向同一个成因: 该站的板托座骑在某根**没被装配/没被驱动**的工位轴上,
CAD 停在建模位而机器人去了另一处。

用法:
    PTLC_CONTROL_ROOT=<上位机根> python verify_plate_seats.py
    PTLC_CONTROL_ROOT=<上位机根> python verify_plate_seats.py --solve   # 重解点样座 7Y
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

import clip_compiler
from scene_kinematics import GlbScene, RobotPosture
from sync_ptlc_robot import ROOT, _control_root, _load_registry


#: 取放基准点 -> (落点, 地轨站位, 翻转态)。地轨槽位取控制侧 rail.yaml 的真源值。
SEATS = (
    ("P19", "spot_seat", 1, "up"),
    ("P65", "scrape_table", 2, "up"),
    ("P21", "feedlift", 1, "down"),
    ("P22", "waste", 1, "down"),
    *((f"P{10 + n}", f"tank:{n}", 5, "down") for n in range(1, 9)),
)

#: 落点 -> (板托座所骑的工位轴, 该轴的毫米值, 出处)。真源在 clip_compiler ——
#: 那边的片段要照它摆 `home.axis_mm`, 这边只是拿同一份来复核, 不另立一份。
#: ⚠ 表里的值可能是"point:<key>"(实读点表), 故一律经 seat_axes_resolved 解开后再用,
#:   不要直接读 clip_compiler.SEAT_AXES 的第二元素。
SEAT_AXES = clip_compiler.SEAT_AXES

#: 持板常量(plateGrip)与各站落点之间允许的**绝对**偏差(mm), 沿吸盘轴。
#: 3mm 取自实测残差量级: 2026-08-05 扣掉 17.82mm 持板压缩后, 各站沿轴残差 ≤2.3mm。
#: 再紧就是在比工位摆位底噪, 再松就盖不住"整块板扎进座面"那一级的错。
GRIP_TOOL_TOLERANCE_MM = 3.0

#: 逐站**面内**残差(垂直于吸盘轴那两根)的上限(mm)。
#:
#: 这一档 2026-08-06 才补上 —— 在那之前面内这一类**没有任何判据看着**:
#:   · 上面的相对判据容差 40mm, 吞得下它(上料位 15.1mm 只报 7.0mm);
#:   · 下面的绝对判据只判 decompose() 出来的**刀具项**, 逐站那一份根本不进那一节;
#:   · 前端 plateContact 只沿吸盘轴打射线, 面内位移压根不产生轴向穿透, 探针恒为 0。
#: 于是用户在演示里看到上料位取板横着穿模 15mm, 而三道门全绿。
#:
#: 阈值**不是拍的**: 它绑在前端 PlateStage 的落点捕获窗口 SEAT_HOLD_LATERAL_M(45mm)上。
#: 面内残差是软轴量(见 diagnose_plate_grip.INPLANE_IS_SOFT_AXIS), 不该拿去平移工位, 但
#: 前端靠"板还坐在落点里时面内归落点"把它吸收掉, 而那个吸收有窗口 —— 残差涨过窗口,
#: 落点就认不出来, 取放板的跳变原样回来。30mm 留了 15mm 余量(现役最大 tank:8 20.7mm)。
#: _check_capture_window() 会核对这两个数没有漂开。
IN_PLANE_TOLERANCE_MM = 30.0

#: 前端落点捕获窗口(mm), 必须与 PlateStage.SEAT_HOLD_LATERAL_M 一致。
FRONTEND_CAPTURE_MM = 45.0

#: 已归属、待现场结清的面内超差 —— 具名基线, **不是**把阈值放宽到看不见它。
#: 写成名字的好处: 数一变就红, 而放宽阈值会把将来真出现的同量级错一起盖掉
#: (与 verify_plate_clearance.LEDGE_HANDOFF 同一写法)。
IN_PLANE_ATTRIBUTED = {
    f"tank:{n}": "展缸两塔 CAD 摆位差一个常向量(塔间 10.11mm), 已归属塔位, 待现场卷尺"
    for n in (5, 6, 7, 8)
}

#: 同翻转态内, 各站"法兰系下的板偏置"允许偏离中位数多远(mm)。
#: 给到 40mm 是为了容下各站 13~19mm 的整站摆位底噪 —— 那是 fit_station_alignment 没覆盖
#: SAMPLING/PHOTOSCRAPE/FEEDLIFT/DEVELOP 四个工位造成的, 与"轴没装配"是两件事,
#: 不该由本门禁来拦。同时 40mm 仍稳稳拦得住 35mm 以上的真错位(刮板台 8Y 正好在边缘,
#: 它是本判据能抓到的最小一例)。
SEAT_TOLERANCE_MM = 40.0


def seat_axes_mm(control_root, overrides: dict[str, float] | None = None) -> dict[str, float]:
    """把 SEAT_AXES 摊成 {轴 id: 毫米}, 值未知的轴由 overrides 补。

    control_root 是必须的: 表里的点位引用要实读点表才解得开(见 seat_axes_resolved)。
    """
    result: dict[str, float] = {}
    for axis_id, value, _why in clip_compiler.seat_axes_resolved(control_root).values():
        resolved = (overrides or {}).get(axis_id, value)
        if resolved is not None:
            result[axis_id] = float(resolved)
    return result


def solve_seat_axis(scene, posture, registry, rail_slots, slot: str,
                    search_mm: tuple[float, float], step_mm: float = 0.05,
                    control_root=None) -> float | None:
    """一维搜索: 让某个落点的法兰系板偏置对齐同翻转态基准的那个轴值。

    只在"同翻转态里另有轴值已知的站"时成立 —— 那一站单独定出基准, 本站只剩一个未知量。
    现役唯一用例是点样座 7Y: 同组的刮板台 8Y 放板位有 PLC 出处(=0), 于是 7Y 可解。

    这是**反解**, 不是读数。它的价值在于比"照抄一个手记的修正量"多了一层可复核:
    解完两站残差应当 <1mm, 解不出来(残差仍很大)就说明这一组里还有别的没被驱动的自由度。
    """
    known = {slot_id: item for slot_id, item in SEAT_AXES.items()
             if slot_id != slot and item[1] is not None}
    if not known:
        return None
    flip = next((f for name, s, _r, f in SEATS if s == slot), None)
    peers = [s for _n, s, _r, f in SEATS if f == flip and s != slot and s in known]
    if not peers:
        return None

    base = seat_axes_mm(control_root)
    reference = seat_deviations(scene, posture, registry, rail_slots, base)
    targets = [reference[peer]["local"] for peer in peers if peer in reference]
    if not targets:
        return None
    target = np.median(np.stack(targets), axis=0)

    axis_id = SEAT_AXES[slot][0]

    def error_at(value: float) -> float:
        seats = seat_deviations(scene, posture, registry, rail_slots, {**base, axis_id: value})
        item = seats.get(slot)
        return float(np.linalg.norm(item["local"] - target)) if item else float("inf")

    # 两遍: 先 1mm 粗扫定区间, 再在邻域细扫。误差沿轴值是凸的(纯平移), 粗扫不会漏掉谷底,
    # 而一遍 0.05mm 扫完整个行程要跑两千次全场世界矩阵, 慢得没必要。
    low, high = search_mm
    coarse = min((low + i for i in range(int((high - low)) + 1)), key=error_at)
    fine_low, fine_high = max(low, coarse - 1.0), min(high, coarse + 1.0)
    steps = int(round((fine_high - fine_low) / step_mm))
    return min((fine_low + i * step_mm for i in range(steps + 1)), key=error_at)


def seat_deviations(scene, posture, registry, rail_slots: dict[int, float],
                    axes_mm: dict[str, float] | None = None) -> dict[str, dict]:
    """算每个落点"法兰系下的板偏置"及其相对同翻转态基准的偏离(mm)。

    这是本模块的唯一判据实现 —— main() 与 sync_ptlc_robot 的一行摘要都调它,
    免得两处各写一份比较逻辑然后慢慢漂开。

    Returns:
        {落点: {"flip", "local"(np 3 向量, mm), "deviation"(mm)}}
    """
    anchors = clip_compiler.resolve_plate_anchors(scene)
    by_name = {point.robot_name: point for point in registry.points}

    seats: dict[str, dict] = {}
    for point_name, slot, rail_slot, flip in SEATS:
        point, anchor = by_name.get(point_name), anchors.get(slot)
        if point is None or anchor is None or not point.joint:
            continue
        mount = posture.mount_world(joints_deg=list(point.joint), rail_mm=rail_slots[rail_slot],
                                    axes_mm=axes_mm)
        # 板锚点骑在工位轴上, 必须跟着 axes_mm 一起摆 —— 只摆机器人不摆托座, 量出来的
        # 就是"CAD 建模位 vs 机器人真实位"那个假差(此前 7Y 99mm / 8Y 35mm 的由来)。
        anchor_world = posture.node_world(anchor, joints_deg=list(point.joint),
                                          rail_mm=rail_slots[rail_slot], axes_mm=axes_mm)
        # 转进法兰系: 除掉各站不同的机械臂偏航, 剩下的才是可跨站比较的刀具几何常量
        local = mount[:3, :3].T @ (anchor_world[:3, 3] - mount[:3, 3]) * 1000.0
        seats[slot] = {"point": point_name, "flip": flip, "local": local, "deviation": 0.0}

    for flip in ("up", "down"):
        group = {slot: item for slot, item in seats.items() if item["flip"] == flip}
        if len(group) < 2:
            continue
        # 中位数当基准而不是均值: 一两个离群站不该把基准拖走
        median = np.median(np.stack([item["local"] for item in group.values()]), axis=0)
        for item in group.values():
            item["deviation"] = float(np.linalg.norm(item["local"] - median))
            item["median"] = median
    return seats


def grip_problems(scene, posture, manifest, registry, rail_slots, axes_mm) -> list[str]:
    """**绝对**判据: plateGrip 说的持板位姿, 与各站落点对不对得上。

    为什么本文件非有这一节不可: 上面 seat_deviations 是**相对**判据 —— 各站与同翻转态的
    中位数比。一个各站**均匀**的持板常量误差会把所有站一起平移, 中位数跟着走, 偏离恒为 0,
    于是它结构上就看不见。2026-08-05 的 17.82mm 持板压缩误差正是这么全绿走过去的:
    相对判据说"各站一致", 而每块板都整整扎进座面 17.8mm。

    判据实现复用 diagnose_plate_grip —— 那边把误差摊在**吸盘局部系**里, 沿吸盘轴/两杯连线/
    第三轴分得清清楚楚, 且两翻转态的均值正好隔离出"刀具项"。这里只做阈值, 不另写一份代数
    (两处各写一份比较逻辑然后慢慢漂开, 是本文件 seat_deviations 头注释就点过的名)。

    Returns:
        问题描述; 空表示持板常量与各站落点自洽
    """
    # 延迟导入: diagnose_plate_grip 在模块级 import 本模块(要 SEATS / seat_axes_mm),
    # 放在文件顶会绕成循环。
    import diagnose_plate_grip as D  # pylint: disable=import-outside-toplevel

    grip = next((item for item in manifest.get("actuators") or []
                 if item.get("id") == "rob_flip_suction"), {}).get("plateGrip")
    if not grip:
        print("[--] manifest 里没有 plateGrip, 跳过绝对判据(前端会退回'保世界位姿'老路径)")
        return []

    seats = D.seat_errors(scene, posture, manifest, registry, rail_slots, axes_mm, "pose")
    if not seats:
        return ["绝对判据一个落点都没算出来 —— 点表/锚点/工位轴至少缺一样"]
    summary = D.report_axes(grip, seats)
    split = D.decompose(summary)
    if not split:
        print("[--] 只有一个翻转态有数据, 分不出刀具项, 跳过绝对判据")
        return []

    print()
    print("持板常量核对(吸盘局部系; 两翻转态的均值 = 刀具项, 差值 = 停靠/工位/锚点):")
    problems = []
    for item in split.values():
        tool = item["刀具项mm"]
        ok = abs(tool) <= GRIP_TOOL_TOLERANCE_MM
        print(f"  [{'ok' if ok else '!!'}] {item['轴']:10} 刀具项 {tool:+8.2f}mm "
              f"(限 {GRIP_TOOL_TOLERANCE_MM:.1f}) / 非刀具项 {item['非刀具项mm']:+8.2f}mm")
        if not ok:
            problems.append(f"持板常量在「{item['轴']}」上偏 {tool:+.2f}mm")

    problems.extend(_check_capture_window())
    problems.extend(_report_in_plane(grip, seats, D))
    return problems


def _check_capture_window() -> list[str]:
    """核对 IN_PLANE_TOLERANCE_MM 绑的那个前端窗口没被改掉。

    面内阈值的全部合理性来自"必须稳稳落在前端捕获窗口以内"。窗口在 JS 里、阈值在 Python 里,
    两处各写一份就会慢慢漂开 —— 而漂开之后本判据仍然全绿, 只是不再有意义。
    读不到源码(部署态只有 dist)时不判红, 只提示: 判据不该因为环境缺文件而拦住重建链。
    """
    source = ROOT.parent / "web" / "src" / "three-d" / "twin" / "scene" / "plates" / "PlateStage.js"
    if not source.is_file():
        print(f"  [--] 读不到 {source.name}, 跳过捕获窗口一致性核对")
        return []
    import re  # pylint: disable=import-outside-toplevel
    match = re.search(r"SEAT_HOLD_LATERAL_M\s*=\s*([0-9.]+)", source.read_text(encoding="utf-8"))
    if not match:
        return [f"{source.name} 里找不到 SEAT_HOLD_LATERAL_M —— 面内阈值失去依据, 先去看那边"]
    actual = float(match.group(1)) * 1000.0
    if abs(actual - FRONTEND_CAPTURE_MM) > 1e-6:
        return [f"前端落点捕获窗口已改成 {actual:.1f}mm, 而本判据仍按 {FRONTEND_CAPTURE_MM:.1f}mm "
                f"定阈值 —— 同步 FRONTEND_CAPTURE_MM 与 IN_PLANE_TOLERANCE_MM 再跑"]
    return []


def _report_in_plane(grip: dict, seats: dict, module) -> list[str]:
    """逐站面内残差 —— 软轴那一类, 只判"别涨过前端能吸收的量", 不据此动几何。"""
    print()
    print(f"逐站面内残差(垂直于吸盘轴; 限 {IN_PLANE_TOLERANCE_MM:.0f}mm = 前端捕获窗口 "
          f"{FRONTEND_CAPTURE_MM:.0f}mm 留余量):")
    problems = []
    for slot, item in seats.items():
        value = module.in_plane_mm(grip, item["delta"])
        attributed = IN_PLANE_ATTRIBUTED.get(slot)
        ok = value <= IN_PLANE_TOLERANCE_MM
        # 具名基线超差要与真超差**看着就不一样**: 都打 !! 的话, 读日志的人会以为门禁
        # 该红没红。-- = 超了但已归属、已立项。
        mark = "ok" if ok else ("--" if attributed else "!!")
        note = f"   (已归属: {attributed})" if attributed else ""
        print(f"  [{mark}] {item['point']:5}{slot:14}{value:7.2f}mm{note}")
        if not ok and not attributed:
            problems.append(
                f"落点「{slot}」面内残差 {value:.2f}mm 超过 {IN_PLANE_TOLERANCE_MM:.0f}mm —— "
                "先查: (1) diagnose_plate_grip 的世界系残差按模块是否共用一个常向量; "
                "(2) 该模块内落点间距 CAD vs 示教是否对得上(对不上是建模节距错); "
                "(3) 地轨相关性那一节有没有指向 axis_11y。"
                "⚠ 面内是软轴, 查清楚之前不要拿这个数去平移工位(见溯源文档 §三.4)"
            )
    return problems


def main() -> int:
    control_root = _control_root(None)
    registry = _load_registry(control_root)
    manifest = json.loads(
        (ROOT / "models" / "device-manifest.official-cr5.json").read_text(encoding="utf-8"))
    scene = GlbScene(ROOT / "models" / "machine.official-cr5.glb")
    posture = RobotPosture(scene, manifest)
    rail_slots = clip_compiler.load_rail_slots(control_root)
    solve = "--solve" in sys.argv

    axes = seat_axes_mm(control_root)
    if solve:
        # 重解点样座 7Y: "7Y 停在哪个毫米值, 板才落在 P19 示教点的吸盘下"。
        # 搜索区间取该轴**现行 range_mm**, 不写死 —— 2026-08-05 就吃过亏: 区间写死成
        # 旧量程, 改完标定后窗口盖不住新量程, 解会静默落在边界上。
        axis_id = SEAT_AXES["spot_seat"][0]
        axis_range = next((tuple(float(v) for v in spec["rangeMm"])
                           for spec in manifest.get("axes", [])
                           if spec.get("id") == axis_id and spec.get("rangeMm")), None)
        solved = (solve_seat_axis(scene, posture, registry, rail_slots, "spot_seat",
                                  search_mm=axis_range, control_root=control_root)
                  if axis_range else None)
        if solved is not None:
            # ⚠ spot_seat 的现役值是**实机 OPC 实读**(点表 spot_7y_place=56.0), 不是本反解的
            #   产物 —— **不要把解出来的数抄回 SEAT_AXES**, 那等于拿反解覆盖读数。
            #   反解的正当用处在别处: 它给出"板该落在 δ=多少", 与实读毫米值联立就定出
            #   rig_map 的 sign 与 zero_offset_mm(2026-08-05 的 sign +1→−1 就是这么定的)。
            #   标定对了之后两者应当**重合**(差 ≈0); 再次拉开就是零点漂了或几何动了。
            declared = clip_compiler.seat_axes_resolved(control_root)['spot_seat'][1]
            print(f"[solve] spot_seat axis_7y 反解 = {solved:.2f}mm; "
                  f"实机实读 = {declared:.2f}mm; 差 {abs(solved - declared):.2f}mm "
                  "—— 标定对齐后这个差应当 ≈0, 差得多说明 rig_map 的 sign/zero_offset 不对")
            axes["axis_7y"] = solved
    seats = seat_deviations(scene, posture, registry, rail_slots, axes)

    print("板托座所骑的工位轴(不摆到位就量不出真差):")
    for slot, (axis_id, value, why) in clip_compiler.seat_axes_resolved(control_root).items():
        shown = axes.get(axis_id)
        print(f"  {slot:13} {axis_id:9} {('%.2f' % shown) if shown is not None else '未知':>9}mm "
              f"{why}")
    print()
    print("取放点  落点          翻转   法兰系下的板偏置 dX      dY      dZ    偏离基准")
    for slot, item in seats.items():
        local = item["local"]
        print(f"  {item['point']:5} {slot:13} {item['flip']:5}  "
              f"{local[0]:+8.1f} {local[1]:+8.1f} {local[2]:+8.1f}   {item['deviation']:7.1f}mm")

    problems: list[str] = grip_problems(scene, posture, manifest, registry, rail_slots, axes)
    print()
    for flip in ("up", "down"):
        group = {slot: item for slot, item in seats.items() if item["flip"] == flip}
        if len(group) < 2:
            continue
        worst = max(group, key=lambda slot: group[slot]["deviation"])
        worst_mm = group[worst]["deviation"]
        median = group[worst]["median"]
        ok = worst_mm <= SEAT_TOLERANCE_MM
        print(f"[{'ok' if ok else '!!'}] rotary-{flip} 基准 "
              f"({median[0]:+.1f}, {median[1]:+.1f}, {median[2]:+.1f})mm; "
              f"最大偏离 {worst} {worst_mm:.1f}mm")
        for slot, item in sorted(group.items(), key=lambda kv: -kv[1]["deviation"]):
            if item["deviation"] > SEAT_TOLERANCE_MM:
                print(f"       {slot:13} 偏离 {item['deviation']:7.1f}mm")
        if not ok:
            problems.append(
                f"rotary-{flip} 有站偏离刀具几何基准超过 {SEAT_TOLERANCE_MM:.0f}mm"
                f"(最大 {worst} {worst_mm:.0f}mm)"
            )

    print()
    if problems:
        print(f"[!] 板落点验收未通过({len(problems)} 项):")
        for item in problems:
            print(f"    {item}")
        if any("持板常量" in item for item in problems):
            print("    「持板常量」那几条是**绝对**判据, 与下面的站间一致性是两回事:")
            print("      它说的是'板整体贴错位置', 各站可以完全一致地一起错(相对判据看不见)。")
            print("      修 rig_map 的 actuators[rob_flip_suction].plate_grip:")
            print("        · 沿吸盘轴偏  -> carry_compression_mm(被吸住时波纹已压掉多少)")
            print("        · 沿两杯连线偏 -> 对中心/cups 匹配器选错了子件")
            print("      先跑 diagnose_plate_grip.py 看逐站分解与法线转角: 转角不为 0 就不是")
            print("      平移的事, 而是翻转支点或 180° 行程, 改 carry_compression_mm 是治不好的。")
        print("    下面的站间一致性有两种成因, 修法完全不同 —— 先看上面那张表里该轴有没有值:")
        print("      (a) 轴值是'未知' → 板托座骑在**没被装配或没被驱动**的工位轴上,")
        print("          CAD 停在建模位而机器人去了另一处。补装配(rig_map 各轴条目)或")
        print("          补驱动(clip_compiler 的 SEQUENCE_ACTIONS / SEARCH_AXIS_ACTIONS)。")
        print("      (b) 轴值有出处却仍偏 → 先怀疑**那根轴的 sign/zero_offset 标错了**,")
        print("          再怀疑 CAD 落点与实机示教值对不上。跑 --solve: 反解值与实读值")
        print("          差得多, 就是标定不对(反解给 δ, 实读给 mm, 两者联立即定 zero_offset)。")
        print("          2026-08-05 实例: 点样座 7Y 偏 40.8mm, 病因是 sign 写成了 +1 ——")
        print("          sign=+1 下没有任何 zero_offset 能同时装下 −20 与 56 两个示教点,")
        print("          改 −1 / zero_offset=−24.85 后转绿(见 docs/工位摆位偏差溯源_20260805)。")
        print("          排除标定后剩下的才是几何账, 与货架/中转那 23~41mm 同类, 留给现场卷尺。")
        return 1
    print("[ok] 各站板落点残差一致, 未见'工位轴没被驱动'的特征")
    return 0


if __name__ == "__main__":
    sys.exit(main())
