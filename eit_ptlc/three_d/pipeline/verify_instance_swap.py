# 功能: 两条静态门禁, 只读 clips + 运行期 GLB + manifest, 不起三维、不碰浏览器。
#
#   门禁一「实例交换保姿态」: 每一处"载荷落位 → 显示目的实例", 按两份 CAD 拷贝**共享的
#       唯一 mesh** 逐子件量包围盒角点位移。源实例刚落到的地方与目的实例即将出现的地方
#       必须重合, 否则交换那一帧就是肉眼可见的瞬移。
#       修前基线(2026-08-13, flow.collect_cycle): 收集工位桶→中转A 125.3mm、刮板桶→
#       收集工位桶 35.7mm、瓶两向 36.1/39.3mm; 修后应全部归零级。
#
#   门禁二「落位父级必须先在场」: detach 事件的时刻取步骤的 at 而不是 at+dur, 所以换父
#       那一刻目的父托盘若还是 visible=false, 件连同托盘一起消失整个落位补间(0.45s),
#       补间结束才三条 state 一起闪出来 —— 用户报障"最后放粉桶时粉桶支架没有, 是后续
#       闪现出来的"就是这条。
#
# ⚠ 本脚本判的是**片段产物**, 所以必须在重编片段之后跑; 拿它去判陈旧的 clips/ 会红,
#   那是产物陈旧不是回归。
#
# 用法: python verify_instance_swap.py [clips 目录]     (省略即 ../clips)
#       退出码 0 = 两条门禁都过; 1 = 有违例(逐条打印)
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import yaml
from scipy.spatial.transform import Rotation

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from scene_kinematics import GlbScene  # noqa: E402

CLIPS = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "clips"
MODEL = ROOT / "models" / "machine.official-cr5.glb"
MANIFEST = ROOT / "models" / "device-manifest.official-cr5.json"

#: 交换跳变上限(毫米)。同一份几何摆到同一处, 差的只该是 dock 的 8 位小数量化噪声(1e-5mm
#: 量级), 0.5 给了五个数量级余量 —— 它不是"允许的误差", 是"确实算过了"的证据线。
SWAP_TOLERANCE_MM = 0.5

#: glTF 归一化整型分量的除数(KHR_mesh_quantization 的顶点是量化坐标, accessor 的
#: min/max 也是, 要按 componentType 折回单位区间再乘节点 scale)。
NORMALIZED_DIVISOR = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}


def load_scene() -> tuple[GlbScene, dict, dict]:
    glb = GlbScene(MODEL)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    node_of = {entry["id"]: entry["node"] for entry in manifest.get("attachments") or []}
    kind_of = {entry["id"]: (entry.get("payload") or {}).get("kind", "tray")
               for entry in manifest.get("attachments") or []}
    for entry in manifest.get("states") or []:
        node_of.setdefault(entry["id"], entry["node"])
    return glb, node_of, kind_of


def mesh_corners(glb: GlbScene, mesh_index: int) -> np.ndarray:
    """网格局部包围盒的 8 个角点(已折回米)。"""
    low = high = None
    for primitive in glb.gltf["meshes"][mesh_index]["primitives"]:
        accessor = glb.gltf["accessors"][primitive["attributes"]["POSITION"]]
        divisor = (NORMALIZED_DIVISOR[accessor["componentType"]]
                   if accessor.get("normalized") else 1.0)
        minimum = np.asarray(accessor["min"], dtype=float) / divisor
        maximum = np.asarray(accessor["max"], dtype=float) / divisor
        low = minimum if low is None else np.minimum(low, minimum)
        high = maximum if high is None else np.maximum(high, maximum)
    return np.asarray(list(itertools.product(*zip(low, high))), dtype=float)


def unique_mesh_frames(glb: GlbScene, path: str) -> dict[int, np.ndarray]:
    """子树内**唯一出现**的 mesh -> 该网格节点相对子树根的局部矩阵。

    与 clip_compiler.ClipBuilder._instance_mesh_frames 同式(那边烤 dock, 这边验收)。
    """
    root = glb.index_of(path)
    found: dict[int, list[np.ndarray]] = {}
    stack: list[tuple[int, np.ndarray]] = [(root, np.eye(4))]
    while stack:
        index, upstream = stack.pop()
        local = upstream if index == root else upstream @ glb.local_matrix(index)
        mesh = glb.nodes[index].get("mesh")
        if mesh is not None:
            found.setdefault(int(mesh), []).append(local)
        for child in glb.nodes[index].get("children") or []:
            stack.append((int(child), local))
    return {mesh: mats[0] for mesh, mats in found.items() if len(mats) == 1}


def node_scale(glb: GlbScene, path: str) -> np.ndarray:
    return np.asarray(glb.nodes[glb.index_of(path)].get("scale") or [1.0, 1.0, 1.0],
                      dtype=float)


def placed_world(glb: GlbScene, parent_path: str, dock: dict, scale: np.ndarray) -> np.ndarray:
    """按**前端**的复原式还原一个 dock 落位后的世界矩阵: R(q)·diag(node.scale)。"""
    local = np.eye(4)
    local[:3, :3] = Rotation.from_quat(
        np.asarray(dock["quaternion"], dtype=float)).as_matrix() @ np.diag(scale)
    local[:3, 3] = np.asarray(dock["position"], dtype=float)
    return glb.world_matrix(parent_path) @ local


def check_swap_poses(glb, node_of, kind_of) -> tuple[list[str], list[str]]:
    """返回 (单件违例, 整板观察值)。

    只判 kind=item: 整板的目的地有可复核的 CAD 座位(编译期 dockResiduals ≤0.5mm 门禁 +
    孔序看门狗), 它的落位真源就是 CAD, 交换到 CAD 实例是**对的**; 剩下的跳变是两份托盘
    CAD 拷贝之间的摆放差, 属另一条线(实测: 收集器板 2.6mm; 样品瓶板 154mm 但那是绕板心
    的 180° 偏航, 板与 2×3 孔阵二重对称, 形心只差 0.6mm, 观感等同)。所以整板只报数不判红。
    """
    problems: list[str] = []
    observations: list[str] = []
    for path in sorted(CLIPS.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        steps = document.get("steps") or []
        for index, step in enumerate(steps):
            detach = (step.get("do") or {}).get("detach")
            if not detach or "dock" not in detach or step.get("label") != "载荷落位":
                continue
            window = steps[index + 1:index + 8]
            destination = next((s["do"]["state"]["id"] for s in window
                                if s.get("label") == "显示目的实例"), None)
            swap = next((s["do"]["detach"] for s in window
                         if s.get("label") == "目的实例就位"), None)
            source = detach["id"]
            if destination is None or source not in node_of or destination not in node_of:
                continue
            source_world = placed_world(glb, detach["parent"], detach["dock"],
                                        node_scale(glb, node_of[source]))
            if swap is not None:
                destination_world = placed_world(glb, swap["parent"], swap["dock"],
                                                 node_scale(glb, node_of[destination]))
            else:
                destination_world = glb.world_matrix(node_of[destination])
            source_frames = unique_mesh_frames(glb, node_of[source])
            destination_frames = unique_mesh_frames(glb, node_of[destination])
            shared = sorted(set(source_frames) & set(destination_frames))
            if not shared:
                problems.append(f"{path.name}: {source} -> {destination} 没有共享的唯一网格")
                continue
            worst = 0.0
            for mesh in shared:
                before = source_world @ source_frames[mesh]
                after = destination_world @ destination_frames[mesh]
                corners = mesh_corners(glb, mesh)
                moved = (before[:3, :3] @ corners.T).T + before[:3, 3]
                landed = (after[:3, :3] @ corners.T).T + after[:3, 3]
                worst = max(worst, float(np.max(np.linalg.norm(moved - landed, axis=1))) * 1000.0)
            line = f"{path.name}: {source} -> {destination} 交换跳变 {worst:.2f}mm"
            if kind_of.get(source) != "item":
                if worst > SWAP_TOLERANCE_MM:
                    observations.append(line + "  (整板, 只报数)")
            elif worst > SWAP_TOLERANCE_MM:
                problems.append(line + f" > {SWAP_TOLERANCE_MM}mm")
    return problems, observations


def check_parent_visible_before_landing(glb, node_of) -> list[str]:
    """任何 detach.parent 若本身是一条 state 节点, 该 state 必须在事件时刻之前已置 true。"""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    state_ids = {entry["id"] for entry in manifest.get("states") or []}
    problems: list[str] = []
    for path in sorted(CLIPS.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        shown: dict[str, float] = {}
        cursor = 0.0
        for step in document.get("steps") or []:
            at = float(step["at"]) if step.get("at") is not None else cursor
            body = step.get("do") or {}
            state = body.get("state")
            if state and state.get("value") is True:
                shown.setdefault(str(state["id"]), at)
            detach = body.get("detach")
            if detach:
                parent_id = str(detach.get("parent") or "").rsplit("/", 1)[-1]
                if parent_id in state_ids and shown.get(parent_id, float("inf")) > at:
                    problems.append(
                        f"{path.name}: t={at:.2f}s 把 {detach['id']} 挂进 {parent_id}, "
                        f"而它到 t={shown.get(parent_id, float('inf')):.2f}s 才点亮 —— "
                        "落位补间期间连件带盘不可见")
            cursor = at + max(0.0, float(step.get("dur") or 0))
    return problems


def main() -> None:
    glb, node_of, kind_of = load_scene()
    print(f"片段目录: {CLIPS}")
    swap_problems, tray_observations = check_swap_poses(glb, node_of, kind_of)
    parent_problems = check_parent_visible_before_landing(glb, node_of)
    if tray_observations:
        unique = sorted({line.split(": ", 1)[1] for line in tray_observations})
        print(f"\n整板交换跳变(不判红, 见 check_swap_poses 头注释): {len(unique)} 种")
        for line in unique:
            print(f"  {line}")
    for title, problems in (("门禁一 实例交换保姿态(单件)", swap_problems),
                            ("门禁二 落位父级必须先在场", parent_problems)):
        if problems:
            print(f"\n{title}: {len(problems)} 条违例")
            for line in problems[:40]:
                print(f"  {line}")
            if len(problems) > 40:
                print(f"  … 另有 {len(problems) - 40} 条")
        else:
            print(f"{title}: 通过")
    if swap_problems or parent_problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
