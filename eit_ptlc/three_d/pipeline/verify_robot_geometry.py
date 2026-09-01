"""Verify the exported CR5, rail carriage, flange and quick-change geometry.

Run after ``03_clean_model.py`` and before optimization. The optimized GLB uses
meshopt, which older trimesh readers cannot decode; the unoptimized work asset is
the geometry acceptance source.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
import yaml
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation


ROOT = Path(__file__).resolve().parents[1]
CALIBRATION = ROOT / "pipeline" / "calibration" / "cr5_ptlc_v1.yaml"
RIG_MAP = ROOT / "pipeline" / "rig_map.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="验收 CR5、地轨托盘和末端快换的刚体连续性")
    parser.add_argument(
        "model",
        nargs="?",
        # 上位机 authoring 服务与手动管线共用的 03 产物.
        default=str(ROOT / "work" / "machine.full.glb"),
    )
    args = parser.parse_args()

    scene = trimesh.load(Path(args.model), force="scene")
    edges = scene.graph.to_edgelist()
    children: dict[str, list[str]] = {}
    for parent, child, *_rest in edges:
        children.setdefault(str(parent), []).append(str(child))

    def exact(name: str) -> str:
        hits = [str(node) for node in scene.graph.nodes if str(node) == name]
        if len(hits) != 1:
            raise SystemExit(f"节点 {name!r} 必须唯一，实际找到 {len(hits)} 个")
        return hits[0]

    def contains(text: str) -> str:
        hits = [str(node) for node in scene.graph.nodes if text.lower() in str(node).lower()]
        if len(hits) != 1:
            raise SystemExit(f"包含 {text!r} 的节点必须唯一，实际找到 {len(hits)} 个")
        return hits[0]

    def descendants(root: str) -> list[str]:
        result, stack = [], [root]
        while stack:
            node = stack.pop()
            result.append(node)
            stack.extend(children.get(node, ()))
        return result

    def world_vertices(nodes: list[str]) -> np.ndarray:
        chunks = []
        for node in nodes:
            transform, geometry = scene.graph.get(node)
            if geometry is None:
                continue
            vertices = scene.geometry[geometry].vertices
            homogeneous = np.column_stack((vertices, np.ones(len(vertices))))
            chunks.append((transform @ homogeneous.T).T[:, :3])
        if not chunks:
            raise SystemExit(f"节点没有可验收的网格: {nodes}")
        return np.vstack(chunks)

    with CALIBRATION.open(encoding="utf-8") as handle:
        calibration = yaml.safe_load(handle)
    registration = calibration["scene_registration"]
    support_spec = registration.get("rail_support") or {}

    base_frame = exact("CR5_BASE_FRAME")
    base_node = exact("CR5_BASE")
    link6_node = exact("CR5_LINK6")
    carriage = exact("CARRIAGE")
    support_node = exact(str(support_spec.get("reference_node") or ""))
    socket_node = exact(str(support_spec.get("socket_node") or ""))
    valve_group = exact("4V21008B-1")
    regulator_group = exact("WEF50-N-KL-1")
    pressure_plate = exact("PTLC-07-027 压力表安装板-1")

    carriage_nodes = set(descendants(carriage))
    required_carriage_nodes = {
        base_frame,
        support_node,
        socket_node,
        valve_group,
        regulator_group,
        pressure_plate,
    }
    missing_from_carriage = sorted(required_carriage_nodes - carriage_nodes)
    if missing_from_carriage:
        raise SystemExit(
            "CR5、物理支撑板、安装插槽或托盘气动附件没有归入同一个地轨 CARRIAGE 刚体链: "
            + ", ".join(missing_from_carriage)
        )

    base = world_vertices(descendants(base_node))
    support = world_vertices(descendants(support_node))
    link6 = world_vertices(descendants(link6_node))
    adapter = world_vertices(descendants(contains("PTLC-07-028")))
    quick_change = world_vertices(descendants(contains("QT2191876")))

    base_origin = scene.graph.get(base_frame)[0][:3, 3]
    socket_origin = scene.graph.get(socket_node)[0][:3, 3]
    base_bottom_y = float(np.min(base[:, 1]))
    support_min = np.min(support, axis=0)
    support_max = np.max(support, axis=0)
    support_top_y = float(support_max[1])
    support_mount = np.asarray(
        [
            (support_min[0] + support_max[0]) / 2.0,
            support_top_y,
            (support_min[2] + support_max[2]) / 2.0,
        ]
    )
    expected_mount = np.asarray(support_spec.get("reference_mount_frame_m"), dtype=float)
    if expected_mount.shape != (3,):
        raise SystemExit("版本化标定缺少 rail_support.reference_mount_frame_m")
    contact_y = float(registration["base_contact_height_m"])

    def nearest_mm(first: np.ndarray, second: np.ndarray) -> float:
        return float(np.min(cKDTree(second).query(first, k=1)[0]) * 1000.0)

    report = {
        "base_origin_m": [round(float(value), 9) for value in base_origin],
        "base_bottom_y_m": round(base_bottom_y, 9),
        "rail_contact_y_m": round(contact_y, 9),
        "base_contact_error_mm": round(abs(base_bottom_y - contact_y) * 1000.0, 4),
        "rail_carriage_node": carriage,
        "rail_support_node": support_node,
        "rail_companion_nodes": [valve_group, regulator_group, pressure_plate],
        "rail_support_top_y_m": round(support_top_y, 9),
        "base_to_support_gap_mm": round((base_bottom_y - support_top_y) * 1000.0, 4),
        "base_to_support_centre_mm": round(
            float(np.linalg.norm(base_origin[[0, 2]] - support_mount[[0, 2]])) * 1000.0,
            4,
        ),
        "base_to_socket_mm": round(float(np.linalg.norm(base_origin - socket_origin)) * 1000.0, 4),
        "support_to_socket_mm": round(float(np.linalg.norm(support_mount - socket_origin)) * 1000.0, 4),
        "support_to_calibrated_mount_mm": round(
            float(np.linalg.norm(support_mount - expected_mount)) * 1000.0,
            4,
        ),
        "link6_to_adapter_nearest_vertex_mm": round(nearest_mm(link6, adapter), 4),
        "adapter_to_quick_change_nearest_vertex_mm": round(nearest_mm(adapter, quick_change), 4),
    }

    # ---- 快换同轴复核(独立于 03 内部门禁的第二本账) --------------------------
    # 机器人侧快换(QT2191876, ICP 链)与工具侧母盘(QT2091392, TOOL_MOUNT 示教点链)
    # 在锁紧位必须同轴; 03 的 quick_change_correction 在 Blender 系里保证过一次,
    # 这里用 trimesh 在导出后的 glTF 系再量一次, 防导出/换基回归. 耦合轴向 =
    # mount 局部 Z(实测金色母盘沿它仅 15mm 厚), 侧向 = X/Y 平面; 两处实现刻意
    # 不共享代码.
    with RIG_MAP.open(encoding="utf-8") as handle:
        rig_map = yaml.safe_load(handle)
    tools = rig_map.get("tools") or []
    source_tool = next(
        (
            tool for tool in tools
            if (tool.get("mount_transform") or {}).get("position_m")
            and not (tool.get("mount_transform") or {}).get("shared_coupling")
        ),
        None,
    ) or next((tool for tool in tools if (tool.get("mount_transform") or {}).get("position_m")), None)
    if source_tool is None:
        raise SystemExit("rig_map 无 mount_transform, 无法复核快换同轴")
    lock_spec = source_tool["mount_transform"]
    lock = np.eye(4)
    lock[:3, :3] = Rotation.from_quat(np.asarray(lock_spec["quaternion_xyzw"], dtype=float)).as_matrix()
    lock[:3, 3] = np.asarray(lock_spec["position_m"], dtype=float)

    tool_root = exact(str(source_tool["id"]))
    gold_roots = [node for node in descendants(tool_root) if "qt2091392" in str(node).lower()]
    if not gold_roots:
        raise SystemExit(f"{source_tool['id']} 子树内找不到工具侧快换 QT2091392")
    gold_nodes = sorted({node for gold_root in gold_roots for node in descendants(gold_root)})
    gold = world_vertices(gold_nodes)

    mount_transform = np.asarray(scene.graph.get(exact("TOOL_MOUNT"))[0], dtype=float)
    tool_transform = np.asarray(scene.graph.get(tool_root)[0], dtype=float)
    gold_h = np.column_stack((gold, np.ones(len(gold))))
    gold_local = ((lock @ np.linalg.inv(tool_transform)) @ gold_h.T).T[:, :3]
    black_h = np.column_stack((quick_change, np.ones(len(quick_change))))
    black_local = (np.linalg.inv(mount_transform) @ black_h.T).T[:, :3]

    # ---- 实体端面贴合(第二本账, 独立于 03 的 Blender 面检测) --------------------
    # 框架距离(TOOL_MOUNT-DOCK)只证坐标系重合; 2026-08-02 用户实锤过"框架 0.44mm 而
    # 端面差 4.3mm 插销没插到底"的验收漏洞. 这里按三角形法线找黑盘朝工具侧(-z)接触
    # 环面与母盘(锁紧位)朝臂侧(+z)顶面, 面积加权聚类后互比; 端面也定位本体段.
    def face_plane_z(node_list: list[str], to_local: np.ndarray, direction: int):
        """返回 (面积加权 z, 归属节点名) —— 归属 = 获胜簇里贡献接触面积最大的那个网格,
        横向轮廓配准复用它, 保证轴向与横向锁定同一个实体特征."""
        bins: dict[float, float] = {}
        weighted: dict[float, float] = {}
        owners: dict[tuple[float, str], float] = {}
        for node in node_list:
            transform, geometry = scene.graph.get(node)
            if geometry is None:
                continue
            mesh = scene.geometry[geometry]
            matrix = to_local @ np.asarray(transform, dtype=float)
            homogeneous = np.column_stack((mesh.vertices, np.ones(len(mesh.vertices))))
            local = (matrix @ homogeneous.T).T[:, :3]
            triangle = local[np.asarray(mesh.faces)]
            normal = np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0])
            double_area = np.linalg.norm(normal, axis=1)
            valid = double_area > 1e-12
            unit_z = np.zeros(len(normal))
            unit_z[valid] = normal[valid, 2] / double_area[valid]
            mask = (unit_z * direction) > 0.95
            centers = triangle[:, :, 2].mean(axis=1)[mask]
            areas = double_area[mask] / 2.0
            for z_value, area in zip(np.round(centers * 5000.0) / 5000.0, areas):
                bins[z_value] = bins.get(z_value, 0.0) + float(area)
                weighted[z_value] = weighted.get(z_value, 0.0) + float(area) * float(z_value)
                owners[(z_value, node)] = owners.get((z_value, node), 0.0) + float(area)
        if not bins:
            raise SystemExit("快换端面检测: 没有找到朝向耦合轴向的平面")
        best_z, best_area, best_key = 0.0, -1.0, 0.0
        for center_key in bins:
            area = sum(a for k, a in bins.items() if abs(k - center_key) <= 0.0005)
            value = sum(w for k, w in weighted.items() if abs(k - center_key) <= 0.0005)
            if area > best_area:
                best_area, best_z, best_key = area, value / area, center_key
        owner_area: dict[str, float] = {}
        for (key, name), area in owners.items():
            if abs(key - best_key) <= 0.0005:
                owner_area[name] = owner_area.get(name, 0.0) + area
        return best_z, (max(owner_area, key=owner_area.get) if owner_area else None)

    black_node_list = descendants(contains("QT2191876"))
    gold_face_z, gold_owner = face_plane_z(gold_nodes, lock @ np.linalg.inv(tool_transform), +1)
    black_face_z, black_owner = face_plane_z(black_node_list, np.linalg.inv(mount_transform), -1)
    report["quick_change_face_gap_mm"] = round((gold_face_z - black_face_z) * 1000.0, 3)

    # ---- 横向同轴: 两半**本体外轮廓**支撑函数配准 -------------------------------
    # 不用质心: 两半挂的模块不一样(金盘多 2 路气模块)会把质心系统性拉偏, 且配合面处
    # 截面不可比 —— 质心版曾只纠掉真实偏差的一半, 用户目视一眼看穿. 本体段取离各自
    # 配合面 2~12mm 的一圈(黑侧朝臂, 金侧朝工具), 只认两半共有的 42x48 本体轮廓.
    # 两侧都只取接触面归属网格(排除同子树里的零碎件, 与 03 同一特征定义)
    body_near, body_far = 0.002, 0.012
    black_owner_pts = world_vertices([black_owner] if black_owner else black_node_list)
    gold_owner_pts = world_vertices([gold_owner] if gold_owner else gold_nodes)
    black_owner_local = (
        np.linalg.inv(mount_transform)
        @ np.column_stack((black_owner_pts, np.ones(len(black_owner_pts)))).T
    ).T[:, :3]
    gold_owner_local = (
        (lock @ np.linalg.inv(tool_transform))
        @ np.column_stack((gold_owner_pts, np.ones(len(gold_owner_pts)))).T
    ).T[:, :3]
    black_body = black_owner_local[
        (black_owner_local[:, 2] >= black_face_z + body_near)
        & (black_owner_local[:, 2] <= black_face_z + body_far)
    ][:, :2]
    gold_body = gold_owner_local[
        (gold_owner_local[:, 2] >= gold_face_z - body_far)
        & (gold_owner_local[:, 2] <= gold_face_z - body_near)
    ][:, :2]
    if len(black_body) < 50 or len(gold_body) < 50:
        raise SystemExit(f"快换本体段点太少(黑 {len(black_body)} / 金 {len(gold_body)}), 无法复核轮廓")
    angles = np.linspace(0.0, 2.0 * np.pi, 180, endpoint=False)
    unit = np.column_stack((np.cos(angles), np.sin(angles)))
    difference = (gold_body @ unit.T).max(axis=0) - (black_body @ unit.T).max(axis=0)
    keep = np.ones(len(angles), dtype=bool)
    offset = np.zeros(2)
    for _ in range(4):
        offset = np.linalg.lstsq(unit[keep], difference[keep], rcond=None)[0]
        residual = np.abs(difference - unit @ offset)
        median = float(np.median(residual))
        limit = max(median + 3.0 * float(np.median(np.abs(residual - median))), 0.0003)
        trimmed = residual <= limit
        if int(trimmed.sum()) < len(angles) // 3:
            break
        keep = trimmed
    report["quick_change_lateral_offset_mm"] = {
        "x": round(float(offset[0]) * 1000.0, 3),
        "y": round(float(offset[1]) * 1000.0, 3),
        "norm": round(float(np.linalg.norm(offset)) * 1000.0, 3),
        "inlier_ratio": round(float(keep.mean()), 3),
        "residual_median_mm": round(float(np.median(np.abs(difference - unit @ offset)[keep])) * 1000.0, 4),
        "reference_tool": source_tool["id"],
    }

    # 注: 不做"Link6-法兰切片质心同心度"指标 —— 实测(2026-08-02)该数字被零件自身
    # 形状不对称主导(J6 法兰盘 / 异形连接板 / 带侧挂模块的黑盘互比切片心, 量出的是
    # 形状差 5~8mm 而非轴心差), 有误导性. 机器人侧回归 CAD 原位的判据是上面的
    # link6_to_adapter_nearest_vertex_mm 精确回到 ICP 标定验收值(0.0393mm, 见
    # calibration/cr5_ptlc_v1.yaml validation) —— 曾经的"平移机器人侧"旧方案会把
    # 它推到 ~0.24mm.

    print(json.dumps(report, ensure_ascii=False, indent=2))

    centre_tolerance_mm = float(support_spec.get("centre_tolerance_mm", 0.1))
    if report["base_contact_error_mm"] > 0.1:
        raise SystemExit("CR5 基座未落在版本化地轨接触高度")
    if abs(report["base_to_support_gap_mm"]) > 0.1:
        raise SystemExit("CR5 基座与 PTLC-07-025 支撑板之间仍存在间隙或穿透")
    if report["base_to_support_centre_mm"] > centre_tolerance_mm:
        raise SystemExit("CR5 基座中心没有对准 PTLC-07-025 地轨移动托盘中心")
    if report["base_to_socket_mm"] > centre_tolerance_mm:
        raise SystemExit("CR5 基座与显式机器人安装插槽不重合")
    if report["support_to_socket_mm"] > centre_tolerance_mm:
        raise SystemExit("PTLC-07-025 支撑板与机器人安装插槽不重合")
    if report["support_to_calibrated_mount_mm"] > centre_tolerance_mm:
        raise SystemExit("地轨移动托盘没有落在版本化的 slot 4 安装基准")
    if report["link6_to_adapter_nearest_vertex_mm"] > 1.0:
        raise SystemExit("官方 Link6 与 PTLC 自制末端法兰存在可见间隙")
    if report["adapter_to_quick_change_nearest_vertex_mm"] > 1.0:
        raise SystemExit("PTLC 自制末端法兰与 QT219 快换存在可见间隙")
    if report["quick_change_lateral_offset_mm"]["norm"] > 0.5:
        raise SystemExit(
            "机器人侧快换与工具侧母盘在锁紧位不同轴 "
            f"({report['quick_change_lateral_offset_mm']['norm']} mm, >0.5mm) — "
            "03 的 quick_change_correction 未生效或导出链回归"
        )
    if report["quick_change_lateral_offset_mm"]["inlier_ratio"] < 0.5:
        raise SystemExit(
            "快换两半本体外轮廓吻合方向不足 50% — 不像同规格配对件, 轮廓配准结论不可信"
        )
    if abs(report["quick_change_face_gap_mm"]) > 0.5:
        raise SystemExit(
            f"快换锁紧位端面不贴合 ({report['quick_change_face_gap_mm']} mm, >0.5mm), "
            "插销未插到底 — 03 的轴向校正未生效或配合面检测抓错平面"
        )


if __name__ == "__main__":
    main()
