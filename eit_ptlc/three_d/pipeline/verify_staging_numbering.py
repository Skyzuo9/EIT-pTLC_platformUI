"""中转/货架耗材孔位编号验收: 机器人点表 P46..P51/P53..P58 ↔ 三维 INV_STAGING_*_ITEM_n。

为什么单独成一个可重复跑的脚本(与 verify_tank_numbering 同一条理由): 这条链错了
**画面看着完全正常** —— 爪子稳稳合在一个孔位上, 只是耗材画在另一个孔里, 观感就是
"机器人凭空夹起/夹空气", 没有任何自动指标会报警。2026-08-06 实测撞上过一次:
blender_clean.materialize 按"短边成对"(1,2 同列)编孔, 而点表 中转A收集器1..6号位
按"长边三连"(1,2,3 同排)编 —— 3x2 网格转置, 仅 1、6 号凑巧重合。

判据全部用**相对量**, 因为"示教关节角 -> GLB 世界位姿"这条链有几百毫米系统偏差
(见 clip_compiler.verify_tank_pairing 的注释), 绝对最近邻会认错。此外中转两排点位
Rz 相差约 180 度(同一夹爪从两侧探入), 法兰相对孔心的水平偏置在两排间**反号**:
  1. 排的配对不用绝对距离, 用"公共中线的同侧"(对称偏置在中线处抵消);
  2. 排内配对用沿长边的**次序**(常量平移不换序);
  3. 偏置一致性按**排组内**比较(同排同姿态, 法兰-孔心偏置必须是同一个向量)。

另有一条无点位可对的兜底: 12 个货架托盘 + 中转 B 的盘内 ITEM 格阵(距离签名+手性)
必须与中转 A 一致 —— materialize 的四角候选按质心拟合挑符号, 模板落在相邻角会挑出
**镜像**编号, 手性(row x col 叉积的竖直分量符号)专门拦这个。

用法:
  PTLC_CONTROL_ROOT=<上位机根> python verify_staging_numbering.py            # 门禁断言
  PTLC_CONTROL_ROOT=<上位机根> python verify_staging_numbering.py --report   # 诊断置换表
"""

from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np

import clip_compiler
from scene_kinematics import GlbScene, RobotPosture
from sync_ptlc_robot import ROOT, _control_root, _load_registry

#: (区域, 节点前缀, 点位 id 模板) —— 只有这两个区域有逐孔示教点。
AREAS = (
    ("staging-a", "INV_STAGING_A", "robot-main.area-7-{n}"),
    ("staging-b", "INV_STAGING_B", "robot-main.area-8-{n}"),
)

HOLES = 6
#: 排间距区分阈值: 孔排距 45mm、法兰排距 ~183mm, 20mm 之下就说明根本没分出两排。
ROW_GAP_MIN_MM = 20.0
#: 同排(同姿态)内"法兰-孔心"偏置向量的允许散布: 教点散布+Rz 差 2 度约几毫米,
#: 转置的信号是 >=45mm(一个孔距), 25mm 把噪声与信号分干净。
OFFSET_SPREAD_MAX_MM = 25.0
#: 盘内格阵一致性(纯几何复制, 理应亚毫米)。
LATTICE_TOL_MM = 2.0


def _hole_centers(scene: GlbScene, prefix: str) -> dict[int, np.ndarray] | None:
    centers: dict[int, np.ndarray] = {}
    for hole in range(1, HOLES + 1):
        try:
            centers[hole] = scene.world_matrix(f"{prefix}_ITEM_{hole}")[:3, 3].copy()
        except KeyError:
            return None
    return centers


def _row_split(projected: dict[int, tuple[float, float]]) -> tuple[list[int], list[int]] | str:
    """按短边坐标把 6 个键分成两排(各 3 个), 排序自小到大。分不出即返回原因。"""
    ordered = sorted(projected, key=lambda key: projected[key][1])
    low, high = ordered[:3], ordered[3:]
    low_max = max(projected[key][1] for key in low)
    high_min = min(projected[key][1] for key in high)
    if (high_min - low_max) * 1000.0 < ROW_GAP_MIN_MM:
        return f"排间隔仅 {(high_min - low_max) * 1000.0:.1f}mm, 分不出两排"
    return low, high


def _basis_from_holes(holes: dict[int, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """由孔位求水平面内(长边, 短边)正交基。竖直轴是 glTF 的 Y(下标 1)。

    用 PCA 主轴而不是"最远孔对连线": 最远孔对是对角线(105.1mm), 会把基拟歪;
    3x2 网格中心对称, 协方差主轴必落在长边(方差 1504 vs 506 mm^2)。
    """
    stacked = np.stack([np.array([value[0], value[2]]) for value in holes.values()])
    centered = stacked - stacked.mean(axis=0)
    _eigenvalues, eigenvectors = np.linalg.eigh(centered.T @ centered)
    long_dir = eigenvectors[:, -1]          # eigh 升序, 末列是主轴
    short_dir = np.array([-long_dir[1], long_dir[0]])
    return long_dir, short_dir


def _project(points: dict[int, np.ndarray], long_dir: np.ndarray,
             short_dir: np.ndarray) -> dict[int, tuple[float, float]]:
    result = {}
    for key, value in points.items():
        flat = np.array([value[0], value[2]])
        result[key] = (float(flat @ long_dir), float(flat @ short_dir))
    return result


def _area_permutation(scene: GlbScene, posture: RobotPosture, registry,
                      rail_slots: dict[int, float], area: str, prefix: str,
                      point_template: str, report: list[str]) -> dict[int, int] | None:
    """求"机器人槽号 -> 当前三维孔号"的实测置换; 缺数据回 None(不拿半份数据当证据)。"""
    holes = _hole_centers(scene, prefix)
    if holes is None:
        report.append(f"[{area}] GLB 里孔件不齐({prefix}_ITEM_1..6), 跳过")
        return None
    by_id = {point.point_id: point for point in registry.points}
    mounts: dict[int, np.ndarray] = {}
    for slot in range(1, HOLES + 1):
        point = by_id.get(point_template.format(n=slot))
        if point is None or not point.joint or point.rail is None:
            report.append(f"[{area}] 槽 {slot} 点位缺失/无实测关节角, 跳过整区")
            return None
        rail_mm = rail_slots.get(int(point.rail))
        if rail_mm is None:
            report.append(f"[{area}] 槽 {slot} 的地轨站位 {point.rail} 不在站位表, 跳过整区")
            return None
        mounts[slot] = posture.mount_world(
            joints_deg=list(point.joint), rail_mm=rail_mm)[:3, 3].copy()

    long_dir, short_dir = _basis_from_holes(holes)
    hole_flat = _project(holes, long_dir, short_dir)
    mount_flat = _project(mounts, long_dir, short_dir)

    hole_rows = _row_split(hole_flat)
    mount_rows = _row_split(mount_flat)
    for label, rows in (("孔位", hole_rows), ("法兰", mount_rows)):
        if isinstance(rows, str):
            report.append(f"[{area}] {label}{rows}, 跳过整区")
            return None

    permutation: dict[int, int] = {}
    # 排与排按公共中线同侧配对(短边坐标次序), 排内按长边坐标次序配对。
    for mount_row, hole_row in zip(mount_rows, hole_rows):
        mount_sorted = sorted(mount_row, key=lambda key: mount_flat[key][0])
        hole_sorted = sorted(hole_row, key=lambda key: hole_flat[key][0])
        for slot, hole in zip(mount_sorted, hole_sorted):
            permutation[slot] = hole

    report.append(f"[{area}] 实测置换(机器人槽 -> 当前三维孔): "
                  + ", ".join(f"{slot}->{permutation[slot]}" for slot in sorted(permutation)))
    for slot in sorted(permutation):
        hole = permutation[slot]
        offset = (mounts[slot] - holes[hole]) * 1000.0
        nearest = min(holes, key=lambda key: float(np.linalg.norm(mounts[slot] - holes[key])))
        report.append(
            f"    槽{slot} -> 孔{hole}  法兰-孔心偏置 [{offset[0]:+7.1f} {offset[1]:+7.1f} "
            f"{offset[2]:+7.1f}]mm  (绝对最近孔 {nearest}, 仅供参考)")
    return permutation


def _offset_spread(scene: GlbScene, posture: RobotPosture, registry,
                   rail_slots: dict[int, float], area: str, prefix: str,
                   point_template: str, permutation: dict[int, int]) -> list[str]:
    """排组内"法兰-孔心"偏置一致性(同排同姿态必须同一个向量)。"""
    holes = _hole_centers(scene, prefix)
    by_id = {point.point_id: point for point in registry.points}
    problems: list[str] = []
    for group in ((1, 2, 3), (4, 5, 6)):
        offsets = []
        for slot in group:
            point = by_id[point_template.format(n=slot)]
            mount = posture.mount_world(
                joints_deg=list(point.joint),
                rail_mm=rail_slots[int(point.rail)])[:3, 3]
            offsets.append((mount - holes[permutation[slot]]) * 1000.0)
        stacked = np.stack(offsets)
        spread = float(np.max(np.ptp(stacked, axis=0)))
        if spread > OFFSET_SPREAD_MAX_MM:
            problems.append(
                f"[{area}] 槽组 {group} 的法兰-孔心偏置不一致(极差 {spread:.1f}mm > "
                f"{OFFSET_SPREAD_MAX_MM:.0f}mm): 同排同姿态这个向量必须相同, 不同就是编号错位")
    return problems


def _lattice_signature(scene: GlbScene, prefix: str) -> tuple[np.ndarray, float] | None:
    """盘内格阵指纹: (ITEM_1 到 2..6 的距离序列, row x col 叉积竖直分量符号)。"""
    holes = _hole_centers(scene, prefix)
    if holes is None:
        return None
    distances = np.array([
        float(np.linalg.norm(holes[k] - holes[1])) for k in range(2, HOLES + 1)])
    chirality = float(np.cross(holes[2] - holes[1], holes[4] - holes[1])[1])
    return distances * 1000.0, chirality


def _items_on_plate_holes(scene: GlbScene) -> tuple[list[str], list[str]]:
    """件必须坐在**自己板**的实测孔位上(水平 ≤2mm 且双射)。

    数据来自 blender_clean 落盘的 work/consumable_lattice.json(与摆放同刻同码实测)——
    GlbScene 只读 JSON 层级、无顶点数据, 量不了网格, 故由 03 产出、这里复核。
    2026-08-06 的教训: 件阵 vs 板孔的系统性节距错(瓶盘梯次 5~11mm)对"件与点表"的
    相对判据完全免疫(整排一起偏, 组内散布仍为零), 必须有这条独立断言。
    """
    problems: list[str] = []
    notes: list[str] = []
    path = ROOT / "work" / "consumable_lattice.json"
    if not path.is_file():
        problems.append(
            "work/consumable_lattice.json 缺失 —— 03(full) 未跑或版本过旧, 孔阵断言无从谈起")
        return problems, notes
    trays = (json.loads(path.read_text(encoding="utf-8")).get("trays")) or []
    if len(trays) != 14:
        problems.append(f"consumable_lattice.json 有 {len(trays)} 盘, 应恰 14")
    for tray in trays:
        node = str(tray.get("node"))
        try:
            actual = scene.world_matrix(node)[:3, 3]
        except KeyError:
            notes.append(f"[孔阵] {node} 不在场景里, 跳过")
            continue
        stored = np.asarray(tray.get("trayWorldTranslation") or [], dtype=float)
        if stored.shape != (3,):
            problems.append(f"[孔阵] {node} 记录缺 trayWorldTranslation")
            continue
        drift = float(np.linalg.norm(np.asarray(actual) - stored)) * 1000.0
        if drift > 0.5:
            problems.append(
                f"[孔阵] {node} 盘位与 lattice 记录差 {drift:.2f}mm —— JSON 陈旧, 重跑 03")
            continue
        holes = [np.asarray(center, dtype=float)
                 for center in (tray.get("holeCentersWorld") or [])]
        if len(holes) != 6:
            problems.append(f"[孔阵] {node} 记录了 {len(holes)} 孔, 应恰 6")
            continue
        claimed: set[int] = set()
        for hole_index in range(1, HOLES + 1):
            try:
                item = scene.world_matrix(f"{node}_ITEM_{hole_index}")[:3, 3]
            except KeyError:
                problems.append(f"[孔阵] {node}_ITEM_{hole_index} 不在场景里")
                continue
            distances = [math.hypot(float(item[0]) - float(hole[0]),
                                    float(item[2]) - float(hole[2]))  # 水平 = glTF x,z
                         for hole in holes]
            best = min(range(6), key=lambda i: distances[i])
            if distances[best] * 1000.0 > 2.0:
                problems.append(
                    f"[孔阵] {node}_ITEM_{hole_index} 距最近板孔 "
                    f"{distances[best] * 1000.0:.2f}mm > 2 —— 件没坐在孔里")
            elif best in claimed:
                problems.append(f"[孔阵] {node} 两件挤进同一孔(孔下标 {best})")
            else:
                claimed.add(best)
    return problems, notes


def verify_staging_pairing(scene: GlbScene, posture: RobotPosture, registry,
                           rail_slots: dict[int, float]) -> list[str]:
    """门禁判据: 置换恒等 + 排组内偏置一致 + 格阵按 kind 同签名 + 全体同手性 + 件≈孔双射。

    与 verify_tank_pairing 同一条纪律: 缺数据的区域不下结论(返回时打印说明),
    但**查得到的必须全对** —— 这类错没有别的指标会报警。
    """
    problems: list[str] = []
    notes: list[str] = []
    for area, prefix, template in AREAS:
        permutation = _area_permutation(
            scene, posture, registry, rail_slots, area, prefix, template, notes)
        if permutation is None:
            continue
        wrong = {slot: hole for slot, hole in permutation.items() if slot != hole}
        if wrong:
            problems.append(
                f"[{area}] 机器人槽号与三维孔号不是恒等映射: "
                + ", ".join(f"槽{slot}->孔{hole}" for slot, hole in sorted(wrong.items()))
                + " —— 机器人会在正确的位置夹到画在别处的耗材(观感=夹空气)")
        problems.extend(_offset_spread(
            scene, posture, registry, rail_slots, area, prefix, template, permutation))

    # 格阵签名**按 kind 分参照**: 瓶板孔距 42.5×40 与收集板 47.5×45 本就不同
    # (2026-08-06 逐盘实测定案), 跨 kind 比签名必红。手性仍全体一比 —— 编号规则是
    # 世界系的, 与耗材种类无关。
    chirality_reference = None
    for kind_label, reference_prefix, trays in (
            ("collector", "INV_STAGING_A",
             tuple(f"INV_RACK_COLLECTOR_{index}" for index in range(1, 7))),
            ("bottle", "INV_STAGING_B",
             tuple(f"INV_RACK_BOTTLE_{index}" for index in range(1, 7)))):
        reference = _lattice_signature(scene, reference_prefix)
        if reference is None:
            problems.append(f"{reference_prefix} 孔件不齐, {kind_label} 格阵基准缺失")
            continue
        if chirality_reference is None:
            chirality_reference = (reference_prefix, reference[1])
        elif reference[1] * chirality_reference[1] < 0:
            problems.append(
                f"[格阵] {reference_prefix} 与 {chirality_reference[0]} 编号手性相反(镜像)")
        for prefix in trays:
            signature = _lattice_signature(scene, prefix)
            if signature is None:
                notes.append(f"[格阵] {prefix} 不在场景里, 跳过")
                continue
            delta = float(np.max(np.abs(signature[0] - reference[0])))
            if delta > LATTICE_TOL_MM:
                problems.append(
                    f"[格阵] {prefix} 的孔距签名与 {reference_prefix} 差 {delta:.2f}mm"
                    f"(> {LATTICE_TOL_MM}mm), 同 kind 两盘编号走法不一致")
            if signature[1] * reference[1] < 0:
                problems.append(
                    f"[格阵] {prefix} 的编号手性与 {reference_prefix} 相反(镜像)")

    hole_problems, hole_notes = _items_on_plate_holes(scene)
    problems.extend(hole_problems)
    notes.extend(hole_notes)
    for line in notes:
        print(line)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true",
                        help="只打诊断置换表, 不断言(改编号公式前先跑它定案)")
    args = parser.parse_args()

    control_root = _control_root(None)
    registry = _load_registry(control_root)
    manifest = json.loads(
        (ROOT / "models" / "device-manifest.official-cr5.json").read_text(encoding="utf-8"))
    scene = GlbScene(ROOT / "models" / "machine.official-cr5.glb")
    posture = RobotPosture(scene, manifest)
    rail_slots = clip_compiler.load_rail_slots(control_root)

    if args.report:
        report: list[str] = []
        for area, prefix, template in AREAS:
            _area_permutation(scene, posture, registry, rail_slots, area, prefix, template, report)
        reference = _lattice_signature(scene, "INV_STAGING_A")
        if reference is not None:
            report.append(f"[格阵] 中转A 孔距签名(1->2..6): "
                          + " ".join(f"{value:.1f}" for value in reference[0])
                          + f"  手性 {'+' if reference[1] > 0 else '-'}")
        for line in report:
            print(line)
        return 0

    problems = verify_staging_pairing(scene, posture, registry, rail_slots)
    print()
    if problems:
        print(f"[!] 中转/货架孔位编号验收未通过({len(problems)} 项):")
        for item in problems:
            print(f"    {item}")
        return 1
    print("[ok] 耗材孔位编号自洽: 点表 P46..P58 ↔ INV_STAGING_*_ITEM_n ↔ 货架格阵")
    return 0


if __name__ == "__main__":
    sys.exit(main())
