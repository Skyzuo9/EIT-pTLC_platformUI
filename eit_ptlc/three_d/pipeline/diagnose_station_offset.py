"""定位"工位摆位偏差"到底长在链条的哪一段 —— 只读诊断, 不写任何文件。

# 为什么需要它

`fit_station_alignment.py --fit` 解的是**逐站平移**(每站 3 个自由度, 三站共 9 个)。
这个自由度足够高, 足以把**任何来源**的误差都吸收掉并让门禁全绿 —— 包括根本不属于工位的
误差(机器人基座注册、地轨零点、工具 TCP)。所以"门禁绿"只证明"托盘被挪到了机器人以为的
地方", 不证明工位摆对了。

用户现场观察: 实机的中转 A/B 位置**与 SolidWorks 总装图差得不多, 反而与三维数模差得很远**。
若属实, 现役的三站平移就是在替别人背锅。本脚本把同一批观测量喂给若干**自由度更低、
物理含义更明确**的假设, 比谁的残差更小:

    无修正(0) < 地轨零点(1) < 工具 TCP(3) ≈ 整机平移(3) < 基座刚体(6) < 逐站平移(9)

自由度越低而残差相当, 解释力越强。若某个低自由度假设的残差与逐站平移相当, 那它才是
真成因, 正确的修法是改那一段, **把工位放回 CAD 原位**。

# 观测量

与 `fit_station_alignment` 完全同源: 48 个整板转移取放位姿(24 条片段 × attach/detach),
每个位姿的 `need = 夹爪凹槽基准(世界) − 托盘孔板几何中心(世界)`。即"要把托盘挪多少才能
落进凹槽"。几何、运动学、抓取基准全部复用 `Aligner`, 本脚本一行几何都不重写。

用法(先把 rig_map 的 station_alignment/shelf_alignment 归零并重建, 否则量到的是残差而非偏差):

    python diagnose_station_offset.py
"""

from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path

import numpy as np
import yaml

from fit_station_alignment import (
    ROOT,
    Aligner,
    station_of,
    teach_poses,
    transform_points,
)


def collect(aligner: Aligner, clip_dir: Path) -> list[dict]:
    """逐位姿取 need 向量, 并保留复算所需的上下文(关节/地轨/法兰矩阵)。

    与 `Aligner.samples()` 同一套取样逻辑(含"放料侧要跟目的地托盘比"那条), 但额外留下
    `mount` 与 `rail` —— 后面几个假设要靠它们把 need 换到法兰系/地轨轴上去。
    """
    rows: list[dict] = []
    for path in sorted(glob.glob(str(clip_dir / "transfer.tray.*.yaml"))):
        clip = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        label = os.path.basename(path).replace("transfer.tray.", "").replace(".yaml", "")
        residuals = clip.get("compiled", {}).get("dockResiduals") or []
        if not residuals:
            raise SystemExit(f"{label} 缺 compiled.dockResiduals")
        destination = str(residuals[0]["payload"])
        for phase, (joints, rail, carried_id) in teach_poses(clip, aligner.catalog).items():
            payload_id = carried_id if phase == "attach" else destination
            station, _node = station_of(payload_id)
            mount = aligner.posture.mount_world(joints_deg=joints, rail_mm=rail)
            grasp = transform_points(mount, aligner.grasp_center_mounted[None, :])[0]
            plate_world = aligner.plate_vertices(payload_id)
            plate = (plate_world.min(0) + plate_world.max(0)) / 2
            rows.append({
                "label": f"{label}/{phase}", "station": station, "rail": rail,
                "mount": mount, "grasp": grasp, "plate": plate, "need": grasp - plate,
            })
    return rows


def kabsch(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """求最小二乘刚体变换 R,t 使 R·src + t ≈ dst(含反射抑制)。"""
    sc, dc = src.mean(0), dst.mean(0)
    u, _s, vt = np.linalg.svd((src - sc).T @ (dst - dc))
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return r, dc - r @ sc


def summarize(name: str, dof: int, residual: np.ndarray, extra: str = "") -> dict:
    norms = np.linalg.norm(residual, axis=1) * 1000
    return {"name": name, "dof": dof, "max": norms.max(), "rms": float(np.sqrt((norms**2).mean())),
            "mean": norms.mean(), "extra": extra}


def main() -> None:
    parser = argparse.ArgumentParser(description="定位工位摆位偏差的成因段")
    parser.add_argument("--model", default=str(ROOT / "work" / "machine.full.glb"))
    parser.add_argument("--manifest", default=str(ROOT / "models" / "device-manifest.official-cr5.json"))
    parser.add_argument("--catalog", default=str(ROOT / "generated" / "robot-points.json"))
    parser.add_argument("--rig-map", default=str(Path(__file__).resolve().parent / "rig_map.yaml"))
    parser.add_argument("--clips", default=str(ROOT / "clips"))
    parser.add_argument("--calibration",
                        default=str(Path(__file__).resolve().parent / "calibration" / "cr5_ptlc_v1.yaml"))
    args = parser.parse_args()

    aligner = Aligner(Path(args.model), Path(args.manifest), Path(args.catalog), Path(args.rig_map))
    rows = collect(aligner, Path(args.clips))
    if not rows:
        raise SystemExit("没有找到 transfer.tray.*.yaml 片段")

    need = np.array([r["need"] for r in rows])
    grasp = np.array([r["grasp"] for r in rows])
    plate = np.array([r["plate"] for r in rows])
    stations = np.array([r["station"] for r in rows])

    declared = {str(e["node"]): np.array(e["translate_mm"], float)
                for e in (aligner.rig_map.get("station_alignment") or [])}
    if any(np.abs(v).max() > 1e-9 for v in declared.values()):
        print("⚠ rig_map 的 station_alignment 非零 —— 下面量到的是**残差**, 不是原始偏差。")
        print("  要看原始偏差, 先把 station_alignment/shelf_alignment 归零并重跑 03。\n")

    # ---- 观测量本身 -------------------------------------------------------
    print(f"观测量: {len(rows)} 个取放位姿的 need = 夹爪凹槽基准 − 托盘孔板中心(世界系, mm)\n")
    closing, length, height = aligner._axes
    axis_name = {closing: "闭合轴(硬)", length: "长度轴(无约束)", height: "高度轴(硬)"}
    print(f"  {'工位':10s} {'n':>3s} {'均值向量 (x, y, z)':>28s} {'模长':>7s} "
          f"{'逐点残差max':>10s} | 法兰系分解 " + " / ".join(axis_name[a] for a in (closing, length, height)))
    for station in sorted(set(stations)):
        sel = stations == station
        vec = need[sel].mean(0) * 1000
        resid = np.linalg.norm((need[sel] - need[sel].mean(0)), axis=1) * 1000
        # 把每个 need 转进它自己那一刻的法兰系, 再取均值 —— 三轴的物理含义各不相同:
        # 长度轴只是软判(用户: 夹持"大概中心, 也不是 100%"), 在那根轴上追平是没有物理依据的。
        local = np.array([r["mount"][:3, :3].T @ r["need"] for r in rows if r["station"] == station]) * 1000
        parts = " / ".join(f"{local[:, a].mean():+7.2f}" for a in (closing, length, height))
        print(f"  {station:10s} {sel.sum():3d} "
              f"[{vec[0]:+8.2f},{vec[1]:+7.2f},{vec[2]:+8.2f}] {np.linalg.norm(vec):7.2f} "
              f"{resid.max():10.2f} | {parts}")

    # ---- 假设对照 ---------------------------------------------------------
    results = [summarize("无修正(工位停在 CAD 原位)", 0, need)]

    # (1) 地轨零点: 只沿地轨方向平移。方向由场景实测, 不写死。
    probe = rows[0]
    step = 100.0
    m0 = aligner.posture.mount_world(joints_deg=[0.0] * 6, rail_mm=probe["rail"])
    m1 = aligner.posture.mount_world(joints_deg=[0.0] * 6, rail_mm=probe["rail"] + step)
    rail_dir = (m1[:3, 3] - m0[:3, 3]) / step
    rail_unit = rail_dir / np.linalg.norm(rail_dir)
    delta = float((need @ rail_unit).mean())
    results.append(summarize("地轨零点(沿轨单一平移)", 1, need - delta * rail_unit,
                             f"需 {delta * 1000:+.1f} mm 沿 [{rail_unit[0]:+.2f},{rail_unit[1]:+.2f},{rail_unit[2]:+.2f}]"))

    # (2) 工具 TCP: 法兰系里的一个常量偏置。这正是 verify_plate_seats 用的口径 ——
    #     "板相对吸盘/夹爪"是纯刀具几何常量, 各站必须一致。
    stack_a = np.vstack([r["mount"][:3, :3] for r in rows])
    stack_b = -need.reshape(-1)
    tcp, *_ = np.linalg.lstsq(stack_a, stack_b, rcond=None)
    tcp_resid = np.array([r["mount"][:3, :3] @ tcp + r["need"] for r in rows])
    named = ", ".join(f"{axis_name[a].split('(')[0]} {tcp[a]*1000:+.1f}"
                      for a in (closing, length, height))
    results.append(summarize("工具 TCP(法兰系常量偏置)", 3, tcp_resid, f"需 {named} mm"))

    # (2b) 只动长度轴 —— 若 1 个自由度就吃掉大半, 那"抓取基准的长度位置取错了"就是主因,
    #      而不是三个工位各自装歪了。
    only = np.zeros(3)
    only[length] = float(np.mean([-(r["mount"][:3, :3].T @ r["need"])[length] for r in rows]))
    len_resid = np.array([r["mount"][:3, :3] @ only + r["need"] for r in rows])
    results.append(summarize("仅法兰系长度轴常量", 1, len_resid, f"需 {only[length]*1000:+.1f} mm"))

    # (3) 整机统一平移(等价于"所有工位一起挪"或"机器人整体挪", 3 自由度)
    results.append(summarize("整机统一平移", 3, need - need.mean(0),
                             f"需 [{need.mean(0)[0]*1000:+.1f},{need.mean(0)[1]*1000:+.1f},"
                             f"{need.mean(0)[2]*1000:+.1f}] mm"))

    # (4) 机器人基座刚体变换(6 自由度): 让夹爪基准整体刚体地对上托盘
    rot, trans = kabsch(grasp, plate)
    base_resid = (rot @ grasp.T).T + trans - plate
    angle = np.degrees(np.arccos(np.clip((np.trace(rot) - 1) / 2, -1, 1)))
    # 副作用: 同一个刚体变换会把已经标定好的换刀位一起带走。
    calib = yaml.safe_load(Path(args.calibration).read_text(encoding="utf-8"))
    docks = np.array([c["scene_point_m"]
                      for c in calib["scene_registration"]["correspondences"]], float)
    dock_shift = np.linalg.norm((rot @ docks.T).T + trans - docks, axis=1) * 1000
    results.append(summarize("机器人基座刚体变换", 6, base_resid,
                             f"转 {angle:.3f}°; 会让 P8/P9/P10 换刀位移 "
                             f"{dock_shift.min():.1f}~{dock_shift.max():.1f} mm"))

    # (5) 逐站平移(现役做法, 9 自由度) —— 基线
    per_station = need.copy()
    for station in set(stations):
        sel = stations == station
        per_station[sel] = need[sel] - need[sel].mean(0)
    results.append(summarize("逐站平移(现役做法)", 9, per_station))

    # (6) 逐站平移, 但**只拟合硬约束轴**(闭合轴 + 高度轴), 长度轴放开。
    #     长度轴是"夹爪沿托盘长边插进去多深", 判据里本来就是软判(容差 20 mm, 用户原话
    #     "大概中心, 也不是 100%") —— 它由示教时人手停在哪决定, 不是工位摆位能定的量。
    #     把它一起拟合, 等于用整站平移去追一个没有物理约束的自由度。
    hard = [closing, height]
    hard_fit: dict[str, np.ndarray] = {}
    hard_resid = np.zeros((len(rows), 2))
    for station in sorted(set(stations)):
        idx = np.nonzero(stations == station)[0]
        a = np.vstack([rows[i]["mount"][:3, hard].T for i in idx])          # (2n, 3)
        b = np.concatenate([rows[i]["mount"][:3, hard].T @ rows[i]["need"] for i in idx])
        # ⚠ 必须取**最小范数解**: 每个位姿只约束 2 个方向, 长度轴落在零空间里。
        # rcond=None 会把零空间那个近零奇异值当有效值, 解出 10^5 mm 量级的伪平移
        # (实测 STAGING_A 报 +153614 mm) —— 数字"残差 0.00"却毫无物理意义。
        v, *_ = np.linalg.lstsq(a, b, rcond=1e-3)
        hard_fit[station] = v
        for k, i in enumerate(idx):
            hard_resid[i] = rows[i]["mount"][:3, hard].T @ (rows[i]["need"] - v)
    norms = np.linalg.norm(hard_resid, axis=1) * 1000
    print("\n若只拟合硬约束轴(闭合+高度), 长度轴放开 —— 各站还需要多少平移:\n")
    print(f"  {'工位':10s} {'translate_mm (glTF x,y,z)':>32s} {'水平模长':>9s} "
          f"{'现役水平模长':>12s} {'硬轴残差max':>11s}")
    for station in sorted(hard_fit):
        v = hard_fit[station] * 1000
        cur = need[stations == station].mean(0) * 1000
        sel = stations == station
        print(f"  {station:10s} [{v[0]:+8.2f},{v[1]:+7.2f},{v[2]:+8.2f}] "
              f"{np.hypot(v[0], v[2]):9.1f} {np.hypot(cur[0], cur[2]):12.1f} "
              f"{norms[sel].max():11.2f}")
    print(f"\n  硬轴残差合计: max {norms.max():.2f} / rms {np.sqrt((norms**2).mean()):.2f} mm"
          f"  (现役 9 自由度全轴拟合的残差是 max {summarize('', 9, per_station)['max']:.2f} mm)")

    print("\n成因假设对照(残差越小解释力越强; 自由度越低越可信):\n")
    print(f"  {'假设':26s} {'自由度':>4s} {'残差max':>9s} {'rms':>8s} {'均值':>8s}   备注")
    for r in sorted(results, key=lambda x: x["dof"]):
        print(f"  {r['name']:26s} {r['dof']:4d} {r['max']:9.2f} {r['rms']:8.2f} "
              f"{r['mean']:8.2f}   {r['extra']}")

    print("\n判读: 若某个低自由度假设的残差与「逐站平移」相当, 它才是真成因 —— "
          "正确的修法是改那一段, 并把工位放回 CAD 原位。")
    print("      若全部显著劣于「逐站平移」, 则三个工位确实各装各的, 需现场卷尺定案。")

    # ---- 几何背景: 把上面的法兰系数字翻译成"夹具板上的哪个位置" ----------
    jaw = np.vstack(aligner.jaws) * 1000
    grasp = aligner.grasp_center_mounted * 1000
    print("\n几何背景(TOOL_MOUNT 局部系, mm) —— 用来判上面的修正量落在夹具板的什么位置:")
    for a, tag in ((closing, "闭合轴"), (length, "长度轴"), (height, "高度轴")):
        print(f"  {tag}(局部第{a}轴): 夹具板跨度 [{jaw[:, a].min():+8.2f}, {jaw[:, a].max():+8.2f}]"
              f"  当前抓取基准 {grasp[a]:+8.2f}"
              f"  建议移到 {grasp[a] + tcp[a]*1000:+8.2f}")
    band = aligner.bands[0]
    print(f"  凹槽(第一块板): 长度带 [{band['slot_len_lo']*1000:+.2f}, {band['slot_len_hi']*1000:+.2f}], "
          f"高度带 [{band['slot_lo']*1000:+.2f}, {band['slot_hi']*1000:+.2f}]")

    # ---- 现场可核对量 ----------------------------------------------------
    # 上面全是内部坐标, 拿到机器跟前没法比。这里换算成一个**用尺子就能量**的量:
    # 夹具板最前端到托盘中心还差多远。它是本轮唯一能判"CAD 摆位对不对"的现场证据 ——
    # 几何只能定住闭合轴与高度轴, 长度轴上托盘咬在哪, 只有真机说了算。
    tip = float(np.vstack(aligner.jaws)[:, length].max()) * 1000
    print("\n现场可核对量(按本模型的工位摆位; 真机拿尺子量同一处):")
    print(f"  {'工位':10s} {'夹具板最前端':>12s} {'托盘中心':>10s} {'最前端离托盘中心':>16s}  夹爪覆盖")
    for station in sorted(set(stations)):
        idx = np.nonzero(stations == station)[0]
        # 托盘中心在长度轴的位置 = 抓取基准 − need 的长度分量(need = 基准 − 托盘中心)
        centers = [aligner.grasp_center_mounted[length]
                   - (rows[i]["mount"][:3, :3].T @ rows[i]["need"])[length] for i in idx]
        centre = float(np.mean(centers)) * 1000
        gap = centre - tip
        print(f"  {station:10s} {tip:12.1f} {centre:10.1f} {abs(gap):15.1f}mm  "
              f"{'够不到中心' if gap > 0 else '越过中心'}")
    print("  (正 = 夹具板最前端还没够到托盘中心, 即只咬住靠机械臂那一半)")


if __name__ == "__main__":
    main()
