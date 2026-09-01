"""导出载荷节点的几何参考帧, 供片段编译器算落位。

为什么需要单独一份: `INV_*` 是 blender_clean 造的空节点, **原点位置是任意的** ——
实测 `INV_STAGING_A` 的原点落在世界原点 (0,0,0), 离它自己的几何中心 655 mm;
`INV_RACK_COLLECTOR_3` 的原点离几何 769 mm。所以"两个节点原点之间的距离"完全不是
"两块托盘看起来差多远", 拿它做落位门禁会得到 840 mm 这种毫无意义的数。

真正有意义的量是**几何**: 把托盘搬过去之后, 它的网格是否落在 CAD 里那块托盘的位置上。
本脚本因此逐顶点(见 docs/CLAUDE.md 第 11 条: 旋转过的局部 AABB 重新拟合会明显膨胀)
算出每个载荷子树的世界 AABB 中心, 再折算回该节点的局部坐标存下来。

输入用 `work/machine.full.glb`(04 压缩之前的产物): `models/*.glb` 是 meshopt 压缩的,
trimesh 读不了顶点; 而节点层级两者一致。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
import yaml

from scene_kinematics import GlbScene


ROOT = Path(__file__).resolve().parents[1]


def subtree_center(scene: trimesh.Scene, children: dict[str, list[str]], root: str) -> np.ndarray | None:
    """逐顶点求一个子树的世界 AABB 中心。"""
    chunks: list[np.ndarray] = []
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(children.get(node, ()))
        transform, geometry = scene.graph.get(node)
        if geometry is None:
            continue
        vertices = scene.geometry[geometry].vertices
        homogeneous = np.column_stack((vertices, np.ones(len(vertices))))
        chunks.append((transform @ homogeneous.T).T[:, :3])
    if not chunks:
        return None
    points = np.vstack(chunks)
    return (points.min(axis=0) + points.max(axis=0)) / 2.0


#: 同种耗材的货架托盘与中转托盘, 是同一套物理托盘 —— 零件构成必须一致。
TRAY_PARITY = {
    "collector": ("INV_RACK_COLLECTOR_{}", "INV_STAGING_A"),
    "bottle": ("INV_RACK_BOTTLE_{}", "INV_STAGING_B"),
}


def check_tray_parity(glb: GlbScene) -> None:
    """货架托盘与中转托盘的零件数必须一致, 否则说明有非托盘件混进了可搬运载荷。

    这是一条可证伪的结构断言, 用来挡住"把货架的金属件当成托盘的一部分"这类回归 ——
    该问题实锤过一次: `rack` 条目是"把整棵 CAD 装配改名成 INV_*", 装配里混着的
    `PTLC-01-005 样品放置板`(库位搁板, 12 个实例对应 12 个库位)因此被一并搬走,
    表现是机械臂抬起托盘时带走货架的一块搁板。中转侧是"只把 members 搬进新空节点",
    天然没有这个问题 —— 所以两边零件数一致正是"货架侧没有混入"的充分体现。

    Raises:
        SystemExit: 数量不一致
    """
    def size(name: str) -> int:
        total, stack = 0, [glb.index_of(name)]
        while stack:
            index = stack.pop()
            total += 1
            stack.extend(glb.nodes[index].get("children") or [])
        return total

    problems: list[str] = []
    for kind, (rack_pattern, staging_name) in TRAY_PARITY.items():
        expected = size(staging_name)
        for plate in range(1, 7):
            name = rack_pattern.format(plate)
            actual = size(name)
            if actual != expected:
                problems.append(
                    f"{name} 有 {actual} 个节点, 中转 {staging_name} 有 {expected} 个 "
                    f"(差 {actual - expected:+d}) —— 疑似货架件混进了托盘"
                )
    if problems:
        for line in problems:
            print(f"  {line}")
        raise SystemExit(
            f"托盘零件数一致性门禁失败: {len(problems)} 条。"
            "若确有正当差异, 在 rig_map 的 inventory.rackExclude 里排除货架侧零件。"
        )
    print("托盘零件数一致性: 12 个货架托盘与 2 个中转托盘逐一相符")


def station_seat_poses(glb: GlbScene, scene: trimesh.Scene,
                       children: dict[str, list[str]]) -> dict[str, dict]:
    """站侧座位(rig_map.station_seats, STA_*)的几何参考帧。

    为什么必须有它们: 片段编译器 `_align_to_cad` 把示教点推算的落位平移校正到 CAD 目的地,
    查帧时一边按**载荷 id**(目的座, 如 STA_COLLECT_BOTTLE)、一边按**被携节点叶名**
    (源实例, 如 硅胶收集-1.008)。此前本文件只导 INV_*, 收集三座位一条帧都没有 ——
    _align_to_cad 原样返回不校正, 隐/显实例交换两头位置不同源, 用户看到的就是
    "放瓶进收集治具瞬移"。所以每个座位按 **id 与叶名双键**各写一份(同值), 两边都查得到。

    解析纪律与 gen_twin_manifest.build_payloads 同款: 叶名唯一命中; 不唯一或子树无网格
    即硬失败(后者常见于收集粉桶还没收进 col_lift 组的旧模型 —— 先重跑 03 再导出)。
    """
    rig_map = yaml.safe_load(
        (Path(__file__).resolve().parent / "rig_map.yaml").read_text(encoding="utf-8")) or {}
    poses: dict[str, dict] = {}
    for raw in rig_map.get("station_seats") or []:
        seat = str(raw.get("seat") or "")
        payload_id = str(raw.get("id") or "")
        leaf = str(raw.get("node") or "")
        if not (seat and payload_id and leaf):
            raise SystemExit(f"station_seats 条目缺 seat/id/node: {raw!r}")
        hits = [str(node.get("name") or "") for node in glb.nodes
                if str(node.get("name") or "") == leaf]
        if len(hits) != 1:
            raise SystemExit(
                f"站侧座位 {seat} 的节点 {leaf!r} 在模型里命中 {len(hits)} 次(要求恰好 1)"
                " —— 与 gen_twin_manifest.build_payloads 同一条解析纪律,"
                " 见 rig_map station_seats 头注释的四条对策")
        center = subtree_center(scene, children, leaf)
        if center is None:
            raise SystemExit(
                f"站侧座位 {seat} 的节点 {leaf!r} 子树没有任何网格, 给不出几何参考帧 ——"
                " 多半是目的实例还没收进执行器组(known_debt empty-node-no-geometry 的旧模型):"
                " 先按 rig_map actuators[col_lift/col_extend].build.groups 收编并重跑 03,"
                " 再来导出")
        world = glb.world_matrix(leaf)
        local = np.linalg.inv(world) @ np.append(center, 1.0)
        entry = {
            "localCenter": [round(float(value), 8) for value in local[:3]],
            "worldCenter": [round(float(value), 8) for value in center],
        }
        for key in {payload_id, leaf}:
            if key in poses:
                raise SystemExit(f"站侧座位参考帧键冲突: {key}(station_seats 条目重复?)")
            poses[key] = entry
    return poses


def main() -> None:
    parser = argparse.ArgumentParser(description="导出载荷几何参考帧")
    # ⚠ 已知帧不匹配(2026-08-07 实测, 未修): 本文件默认从 **machine.full.glb**(节点 scale=1,
    #   顶点即米)取 localCenter, 而消费方 clip_compiler 的场景是 **models/machine.official-cr5.glb**
    #   (04 meshopt 量化, 同名节点 scale≈0.0475, 顶点是量化坐标)。`world @ [localCenter,1]` 里
    #   world 带着那个 0.0475, 于是全量帧的中心偏移被缩到 4.75% —— _align_to_cad 相当于只校正了
    #   真值的二十分之一。105 个载荷里 44 个偏差 >1mm: 瓶/桶 2.26mm(其原点本就贴近几何心, 影响小),
    #   INV_SAMPLE_PLATE_1/2 达 ~69.8mm。predicted 与 target 两侧同缩, 源与目的中心相近时会自相
    #   抵消, 这也是它长期没暴露的原因。
    #   要修就是把 --model 换成量化模型后**全链重编 + 逐座位复验 alignment_mm**(会动整板链,
    #   属另一轮的活), 不能只改这一行了事。
    parser.add_argument("--model", default=str(ROOT / "work" / "machine.full.glb"))
    parser.add_argument("--output", default=str(ROOT / "generated" / "payload-poses.json"))
    args = parser.parse_args()

    glb = GlbScene(args.model)
    scene = trimesh.load(Path(args.model), force="scene")
    children: dict[str, list[str]] = {}
    for parent, child, *_rest in scene.graph.to_edgelist():
        children.setdefault(str(parent), []).append(str(child))

    poses: dict[str, dict] = {}
    skipped: list[str] = []
    for index, node in enumerate(glb.nodes):
        name = str(node.get("name") or "")
        if not name.startswith("INV_"):
            continue
        center = subtree_center(scene, children, name)
        if center is None:
            skipped.append(name)
            continue
        world = glb.world_matrix(name)
        # 折算回局部: 节点位姿变了, 几何跟着走, 所以存局部偏移才是刚体不变量。
        local = np.linalg.inv(world) @ np.append(center, 1.0)
        poses[name] = {
            "localCenter": [round(float(value), 8) for value in local[:3]],
            "worldCenter": [round(float(value), 8) for value in center],
        }

    seat_poses = station_seat_poses(glb, scene, children)
    overlap = set(seat_poses) & set(poses)
    if overlap:
        raise SystemExit(f"站侧座位参考帧键与 INV_* 键冲突: {sorted(overlap)}")
    poses.update(seat_poses)

    check_tray_parity(glb)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema": "ptlc.payload-poses/v1",
        "generatedFrom": Path(args.model).name,
        "note": "localCenter 是该载荷子树逐顶点世界 AABB 中心折算回节点局部坐标的结果; "
                "INV_* 空节点的原点是任意的, 落位门禁必须用几何而不是原点。"
                "站侧座位(STA_*)按 id 与 CAD 叶名双键各存一份(同值): 编译器 _align_to_cad "
                "源端按被携节点叶名查、目的端按载荷 id 查, 两边都要命中。",
        "poses": poses,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"导出 {len(poses)} 个载荷几何参考帧(含 {len(seat_poses)} 个站侧座位键) -> {output.name}")
    if skipped:
        print(f"跳过 {len(skipped)} 个无网格载荷: {', '.join(skipped[:6])}")


if __name__ == "__main__":
    main()
