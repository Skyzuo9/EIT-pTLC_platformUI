"""料仓板净空验收: 薄层板随 1Z/2Z 升降时会不会扎进固定结构。

为什么要有它: 2026-08-05 之前这条误差没有任何人看着 —— 演示页流程末尾 `axis_2z → 0`
把刚放进废板仓的那块板一路带下去, 与固定仓壳交叠 131 个三角形, 肉眼就是穿模; 而
`range_mm` 的下限 −50 比几何允许的下限还低 18mm, 到底更是扎穿仓底中央那个黑色件
(feed 966 面 / waste 1305 面)。**这类错不会自己冒出来** —— 轴照走、板照画、没有任何
既有指标会说一句话, 只能靠一个每次生成前都跑的判据(与 verify_plate_seats 同一条理由)。

产出同时被两处消费:
    · 本脚本自己判红(穿透档位数 > 允许值);
    · gen_twin_manifest 读 work/plate_clearance.json 的 floorOffsetM, 折成 manifest 的
      axes[].geometryMinMm —— 前端 MachineStateDriver.setAxisMm 拿它做第二道下界,
      于是把滑杆拖到行程下限、或实时页收到越界遥测时都不会再扎下去。夹的是**轴**不是板,
      所以滑车、玻璃放置板、板堆一起停, 不会出现"板停了而托板还在往下走"的脱节。

用法:
    python verify_plate_clearance.py                 # 实测 + 判红
    python verify_plate_clearance.py --measure-only  # 只产出 JSON, 不判红(重建链里用这个)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

from common import ensure_dir, load_config, log

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_twin_manifest import read_yaml  # noqa: E402  (同目录模块, 复用其 YAML 读取)

BLENDER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "blender_plate_clearance.py")

#: 扫掠步长(mm)。5mm 足以抓住任何肉眼可见的穿模, 又让 600mm 行程只有 121 个采样点。
SWEEP_STEP_MM = 5.0

#: 允许的最大穿透深度(mm)。
#:
#: 为什么判深度而不判"交叠了几个三角形": 板从料仓口进出时必然与仓壁擦肩, 擦边同样能
#: 数出几十个面 —— 按个数判会把"贴着走"和"扎进去"混为一谈, 于是要么全程误报、要么
#: 只好把阈值放到看不见真错为止。深度分得开: 实测擦边只有零点几毫米, 而扎穿仓底是
#: 整个板厚(3mm)。1.0mm 落在两者中间, 且比 02 步的网格化公差(0.4mm)留了余量。
MAX_PENETRATION_MM = 1.0

#: 已知且允许的交叠带 —— 料仓口的**固定托边**。
#:
#: 实测(2026-08-05; 平面高度 2026-08-07 由托边探针复测订正): `STATIC_MAT_STEEL_PLATE_F0F0F0.002`
#: 上有一圈平板, 开口比 200mm 的板四周各内收 **25.0mm**, 全部命中落在单一水平面上
#: (feed z=-410.7 / waste z=-413.7; 旧记录的 feed=-423.7 与今几何对不上, 以探针为准)。
#: 那就是板堆不被滑车顶着时坐的那圈托边。滑车要把板从托边下方送到上方, 几何上**必然**
#: 扫过托边所在平面 —— 这一档的 25mm 交叠是"交接瞬间"本身, 不是位姿错, 挪谁都消不掉。
#:
#: 对策在画面侧: 轴低于交接值(ledgeAxisMm, blender_plate_clearance.ledge_probe 实测,
#: 经 manifest 的 inventory.magazines[] 交给前端)时 MachineStateDriver 把板托在托边高度
#: —— 板停、滑车继续走; clip_compiler 的埋料 hide 是它落地前的旧缓解, 与之兼容。
#: 这里记成**具名基线**而不是把阈值放宽到 26mm: 放宽会把真出现的 25mm 错位一起盖住;
#: 记下来则是深度或档位一变就红。
LEDGE_HANDOFF = {
    "feed": {"axisMm": (-2.5, 7.5), "depthMm": 25.0},
    "waste": {"axisMm": (-7.5, 2.5), "depthMm": 25.0},
}
LEDGE_DEPTH_TOL_MM = 1.0


def is_ledge_handoff(magazine_id: str, item: dict) -> bool:
    """这一档的交叠是不是"扫过料仓托边"那一下(见 LEDGE_HANDOFF)。"""
    known = LEDGE_HANDOFF.get(magazine_id)
    if not known:
        return False
    low, high = known["axisMm"]
    return (low <= item["axisMm"] <= high
            and item.get("depthMm", 0.0) <= known["depthMm"] + LEDGE_DEPTH_TOL_MM)


def build_job(config: dict, output: str) -> dict:
    """由 rig_map 的 inventory.magazines + axes 段拼出作业单。"""
    pipeline_dir = os.path.dirname(os.path.abspath(__file__))
    rig_map = read_yaml(os.path.join(pipeline_dir, "rig_map.yaml"))
    axes = {item["id"]: item for item in rig_map.get("axes", []) or []}

    magazines = []
    for raw in ((rig_map.get("inventory") or {}).get("magazines") or []):
        # 驱动轴按**板堆模板的 CAD 源名**反查是哪根轴把它收进了 carriage_members ——
        # 不在 inventory 里再抄一遍轴 id: 那样"锚点进了滑车"与"料仓声明的轴"会各说各话,
        # 而这两者不一致正是 2026-08-03 "板堆升、板不动"那一案的形态。
        source = str(raw.get("source") or "")
        axis_id = next(
            (aid for aid, spec in axes.items()
             if any(str(member.get("equals", "")) == source
                    for member in (spec.get("carriage_members") or []))),
            None,
        )
        if axis_id is None:
            raise SystemExit(
                f"料仓 {raw.get('id')}(source={source!r}) 的板堆模板不在任何一根轴的 "
                "carriage_members 里 —— 那意味着板堆根本不随轴升降, 先修 rig_map"
            )
        axis = axes[axis_id]
        magazines.append({
            "id": raw["id"],
            "axisId": axis_id,
            "template": raw["node"],
            "axisVec": axis.get("axis", [0, 1, 0]),
            "sign": axis.get("sign", 1),
            "rangeMm": axis["range_mm"],
            "zeroOffsetMm": axis.get("zero_offset_mm", 0.0),
        })
    if not magazines:
        raise SystemExit("rig_map.inventory.magazines 为空 —— 没有可验收的料仓")

    return {
        "model": os.path.join(config["paths"]["work"], "machine.full.glb"),
        "output": output,
        "magazines": magazines,
        "sweepStepMm": SWEEP_STEP_MM,
        "floorGrid": 11,
    }


def main() -> int:
    config = load_config()
    parser = argparse.ArgumentParser(description="料仓板净空验收")
    parser.add_argument("--measure-only", action="store_true",
                        help="只产出 JSON 不判红(重建链里用: 门禁另由本脚本无参运行时施加)")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    output = args.output or os.path.join(config["paths"]["work"], "plate_clearance.json")
    ensure_dir(output)
    job = build_job(config, output)
    if not os.path.isfile(job["model"]):
        raise SystemExit(f"错误: 未找到 {job['model']}\n请先运行 03_clean_model.py --stage full")

    job_path = os.path.join(config["paths"]["work"], "plate_clearance.job.json")
    ensure_dir(job_path)
    with open(job_path, "w", encoding="utf-8") as handle:
        json.dump(job, handle, ensure_ascii=False, indent=2)

    # 复用 03 的 Blender 调用器: 它已经处理了"脚本抛异常但进程退出码仍是 0"这个坑
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    clean_model = __import__("03_clean_model")
    clean_model.BLENDER_SCRIPT = BLENDER_SCRIPT
    clean_model.run_blender(
        config["paths"]["blender"],
        job_path,
        console_log=os.path.join(config["paths"]["work"], "plate_clearance.console.log"),
    )

    with open(output, "r", encoding="utf-8") as handle:
        report = json.load(handle)

    problems, notes = [], []
    print()
    print("料仓   板厚   CAD停靠净空   几何下限    声明下限   可绘区最深穿透   超限档位   托边交接")
    for entry in report["magazines"]:
        spec = next(m for m in job["magazines"] if m["id"] == entry["id"])
        declared_min = float(spec["rangeMm"][0])
        geometric_min = entry.get("minAxisMm")
        ledge_axis = entry.get("ledgeAxisMm")
        # 前端按 geometryMinMm 把轴夹在几何下界上, 所以**实际画得出来**的区间从这里起步。
        # 判红只判这一段: 判到夹紧线以下等于判一段永远画不出来的画面, 那种门禁只会一直红着。
        drawable_min = declared_min if geometric_min is None else max(declared_min, geometric_min)
        overlaps = [item for item in (entry.get("overlaps") or [])
                    if item["axisMm"] >= drawable_min - 1e-6]
        ledge = [item for item in overlaps if is_ledge_handoff(entry["id"], item)]
        judged = [item for item in overlaps if item not in ledge]
        deep = [item for item in judged if item.get("depthMm", 0.0) > MAX_PENETRATION_MM]
        worst = max(judged, key=lambda item: item.get("depthMm", 0.0)) if judged else None
        if ledge:
            notes.append(
                f"{entry['id']}: {len(ledge)} 个档位(axis {ledge[0]['axisMm']}~{ledge[-1]['axisMm']}mm)"
                f"扫过料仓固定托边, 最深 {max(i['depthMm'] for i in ledge):.1f}mm —— "
                "已知交接带, 见 LEDGE_HANDOFF"
            )
        thickness = min(entry["plateSizeMm"])
        print(
            f"  {entry['id']:6} {thickness:5.1f}mm "
            f"{entry.get('clearanceMm', float('nan')):9.2f}mm "
            f"{(geometric_min if geometric_min is not None else float('nan')):9.1f}mm "
            f"{declared_min:9.1f}mm "
            f"{(worst['depthMm'] if worst else 0.0):12.2f}mm   {len(deep):3d} 个 "
            f"{(float(ledge_axis) if ledge_axis is not None else float('nan')):8.1f}mm"
        )
        # 托边交接值门禁: LEDGE_HANDOFF 声明了托边的料仓必须测得 ledgeAxisMm, 且它应落在
        # 交接窗口上沿附近 —— 窗口是 5mm 粗档的盒交叠带, 真交接值(板底=托边顶面)按几何
        # 就在带上沿 ± 一个扫掠步长内; 偏得更远说明托边射线打错了平面。
        expected_ledge = LEDGE_HANDOFF.get(entry["id"])
        if expected_ledge:
            window_top = float(expected_ledge["axisMm"][1])
            if ledge_axis is None or not math.isfinite(float(ledge_axis)):
                problems.append(
                    f"{entry['id']}: 未测到托边交接值 ledgeAxisMm —— 托边探针"
                    "(blender_plate_clearance.ledge_probe)没有命中, 查环带采样是否落空"
                )
            elif abs(float(ledge_axis) - window_top) > SWEEP_STEP_MM:
                problems.append(
                    f"{entry['id']}: 托边交接值 {float(ledge_axis):.1f}mm 偏离 LEDGE_HANDOFF "
                    f"窗口上沿 {window_top:.1f}mm 超过 {SWEEP_STEP_MM:.0f}mm —— "
                    "多半是托边射线打错了平面(或托边几何真的变了, 那就先更新 LEDGE_HANDOFF)"
                )
        if deep:
            problems.append(
                f"{entry['id']}: 可绘区内 {len(deep)} 个档位穿透超过 {MAX_PENETRATION_MM}mm"
                f"(最深 axis={worst['axisMm']}mm, {worst['depthMm']}mm, {worst['tris']} 个三角形)"
            )
        if geometric_min is not None and declared_min < geometric_min - 0.5:
            notes.append(
                f"{entry['id']}: range_mm 下限 {declared_min:.1f}mm 比几何下限 "
                f"{geometric_min:.1f}mm 低 {geometric_min - declared_min:.1f}mm —— "
                f"这段由 manifest 的 axes[].geometryMinMm 夹住不画。**没有改 range_mm**: 它镜像控制侧 "
                "feedlift.yaml 的 limits, 是真源; 差额来自简化板盒(实机放置板在光电处有让位孔, "
                "200×200 的实心盒没有)。"
            )

    print()
    for line in notes:
        log(f"提示: {line}")
    if args.measure_only:
        log(f"--measure-only: 已产出 {output}(未判红)")
        return 0
    if problems:
        print(f"[!] 料仓板净空验收未通过({len(problems)} 项):")
        for item in problems:
            print(f"    {item}")
        print("    两类成因: 板托座位姿错(查 rig_map 该轴的 carriage_members 与 zero_offset_mm),")
        print("    或片段把轴驱到了几何走不通的档位(查 clip_compiler.STATION_AXIS_ACTIONS)。")
        print("    注意: geometryMinMm 只是画面兜底, 它不该被当成'反正会夹紧'的借口。")
        return 1
    print(f"[ok] 可绘区内无超过 {MAX_PENETRATION_MM}mm 的穿透(已知交接带见上方提示)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
