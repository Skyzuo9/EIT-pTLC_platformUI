"""解算单件耗材(瓶/粉桶)的在手锚点 —— 小夹爪四销笼中心在 TOOL_MOUNT 系的坐标。

为什么需要它: 片段里单件的 attach 是"保世界变换换父", 在手位姿 = CAD 座位与实机示教点
之间的失配, 原样可见 —— 用户实拍里瓶子整支嵌进夹爪本体, 而不是悬在两指之间。
整板托盘有实测 mountLocal(fit_station_alignment --emit-grips, 取料示教位姿反解)兜住
这一层; 单件此前一直没有。

但单件**不能**照抄托盘的"示教反解"法: inv(示教法兰位姿) @ CAD座位位姿 恰好等于今天
attach 保世界换父得到的那个错误在手位姿 —— 反解出来的锚点只会把失配原样固化。真正能
修正视觉的锚点必须来自**夹爪自身的几何**, 与"抓取基准要瞄卡合特征而不是包围盒中心"
(fit_station_alignment.py 头注释, 2026-08-05 定案)同一条方法论。

小夹爪的卡合特征有**两处**(2026-08-06/07 逐网格+FK 实测, machine.full.glb / TOOL_VIAL 局部系):
    ① 四销笼: 每指两根竖直短柱(短柱1-*, Ø8×20), 笼心在长度轴 x≈29.8 —— **夹瓶颈**用;
      开爪态内侧半间隙 15.0mm ≈ 瓶体半径 13.4 + 单指开→合行程 1.26(差 0.34mm, 自洽)。
    ② 指臂弧口袋: 臂体上的凹弧, 轴心 x≈72.67 —— **抱粉桶桶身**用。中转A示教桶轴
      x=72.62 与之吻合 0.06mm、口袋同心闭合值 0.104≈holdValue 0.101, 双重证明示教
      与标定都是按口袋来的。2026-08-06 曾把桶也锚在销笼心, 弧臂闭合后离桶 1.2~6.6mm
      贴不上(用户报障"闭合离外径差很多"), 2026-08-07 订正。

锚点语义(与托盘的 mountLocal 刻意不同, 消费端按 payload.kind 区分):
    tray —— mountLocal 是**节点完整局部位姿**(position+quaternion), 挂载时整体钉上去;
    item —— mountLocal.position 是**四销笼中心点**(TOOL_MOUNT 系), quaternion 恒单位
            (占位, 满足 schema)。挂载时只做**位置吸附**且姿态保留(单件都是回转体,
            竖直朝向在座位上本来就对)。吸附基准/锚点/自由度**逐族**声明(2026-08-07 版):
              锚点 position —— 瓶=四销笼心(销笼夹瓶颈); 粉桶=**指臂弧口袋心**
                  (solve_arm_pocket 实测, 见头注②)。
              grabLocal —— 抓取特征点(件节点局部系): 瓶=**瓶颈**中点(Ø23.6, 用户按
                  实机指认"四指夹瓶口"), 收集器=注射器桶身。此前用几何中心, 瓶被抬
                  55.9mm 销子跨在瓶身中段 —— "包围盒中心不是抓取基准"的老教训
                  (fit_station_alignment 托盘凹槽定案)在单件上重演了一遍。
              freeAxes —— 磁吸放手的方向(TOOL_MOUNT 系): 瓶=**空**(销笼是双水平轴
                  定心特征, 2026-08-06 曾放开长度轴让 ~18mm 示教偏差全程保留, 用户
                  报障"夹起瓶子没有在中心"; "长度不约束"的 2026-08-05 定案只适用于
                  托盘榫槽); 粉桶=[销轴](均匀圆柱沿轴无几何基准, 轴向咬哪段是示教
                  事实)。
            消费端两处必须**逐字同式**: MachineStateDriver.attach(播放期磁吸)与
            clip_compiler._grab_corrected(编译期烤 dock) —— 不同式的表现是放件瞬间
            硬弹回 + "dock 与实际取料位姿不同源"误告警。
    GRIP_DEPTH_OFFSET_MM 仍可整体平移销笼锚点(演示观感微调), 但特征选择不归它管。

⚠ 两个坐标帧, 别混: 拟合在 work/machine.full.glb 上做(trimesh 能解码几何), 而消费端
  读的是 models/machine.official-cr5.glb(04_optimize 量化过)。量化会把几何缩进 int16
  码值、补偿塞进节点 TRS —— 瓶那六个件在拟合帧是 scale=1/原点在瓶底, 在运行期帧是
  scale≈0.0475/原点在几何中心, **节点局部平移量不可搬运**。2026-08-07 实测: 拟合出的
  瓶颈 y=0.089 被运行期读成 4.2mm(真值是中心上方 41.5mm), 世界点差 37.3mm, 就是用户报
  的"夹起瓶子没有在中心"; 粉桶 scale 恰为 1 才一直没露。所以 grabLocal 出厂前必须过
  rebase_grab_local 搬进运行期帧, 并由 assert_same_world_geometry 挡住"运行期 GLB 陈旧"。
  (同一条坑在 gen_twin_manifest 的 mountOffsetParent 上记过一次。)

产物: 合并写回 generated/payload-grips.json(保留既有整板条目)。gen_twin_manifest 原样
透传为 manifest attachments[].payload.mountLocal。

可证伪自检: 开爪态四销内侧半间隙 ≈ 瓶体半径 + 单指开→合行程, 差超容差即硬失败 ——
夹爪换版/认错网格时在这里报, 而不是上线后瓶悬在半空。
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from scene_kinematics import GlbScene

ROOT = Path(__file__).resolve().parents[1]

#: 夹持深度微调(mm, 沿销轴方向, +为把物件相对销带往销尖方向挪)。默认 0 = 物件几何中心
#: 对准销带中心(中段夹持)。这是**演示观感值**, 截图定案后要改就只改这一个数。
GRIP_DEPTH_OFFSET_MM = 0.0

#: 自检容差(mm): |开爪半间隙 − (瓶体半径 + 开→合行程)| 的上限。实测差 0.34mm。
CAGE_CHECK_TOL_MM = 2.0


#: 世界包围盒一致性容差(mm): 拟合帧(work/machine.full.glb)与运行期帧
#: (models/machine.official-cr5.glb)的同名子树世界 AABB 允许的最大偏差。实测 0.001mm
#: (量化只动 TRS 的分配, 不动世界几何)。超限 = 运行期 GLB 陈旧或几何被换过, 硬失败。
RUNTIME_FRAME_BOX_TOL_MM = 1.0

#: glTF 归一化整型分量的满量程(componentType → 除数)。normalized 访问器的 min/max 是
#: 整型码值, 除以满量程才是节点局部单位。
_ACCESSOR_NORMALIZE = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}


def _accessor_world_box(scene: GlbScene, path: str) -> tuple[np.ndarray, np.ndarray]:
    """子树世界 AABB —— 只读 glTF 访问器的 min/max, **不解码几何**。

    为什么不用 trimesh: 运行期那份 GLB 是 meshopt 量化 + Draco 压缩的, trimesh 装不上
    对应解码器; 而 POSITION 访问器的 min/max 就在 JSON 块里, 拿它的八个角点过一遍
    父级链就够判"两份 GLB 的同名子树是不是同一块世界几何"。
    """
    corners: list[np.ndarray] = []

    def walk(index: int, world: np.ndarray) -> None:
        world = world @ scene.local_matrix(index)
        node = scene.nodes[index]
        if "mesh" in node:
            for primitive in scene.gltf["meshes"][node["mesh"]].get("primitives") or []:
                accessor = scene.gltf["accessors"][primitive["attributes"]["POSITION"]]
                low, high = accessor.get("min"), accessor.get("max")
                if not low or not high:
                    continue
                divisor = (_ACCESSOR_NORMALIZE[accessor["componentType"]]
                           if accessor.get("normalized") else 1.0)
                low = np.asarray(low, dtype=float) / divisor
                high = np.asarray(high, dtype=float) / divisor
                for x in (low[0], high[0]):
                    for y in (low[1], high[1]):
                        for z in (low[2], high[2]):
                            corners.append((world @ np.array([x, y, z, 1.0]))[:3])
        for child in node.get("children") or []:
            walk(int(child), world)

    walk(scene.index_of(path), np.eye(4))
    if not corners:
        raise SystemExit(f"{path} 子树在 {Path(scene_path_of(scene)).name} 里没有带 min/max 的 "
                         "POSITION 访问器 —— 无法核对运行期帧")
    stacked = np.asarray(corners, dtype=float)
    return stacked.min(axis=0), stacked.max(axis=0)


def scene_path_of(scene: GlbScene) -> str:
    """GlbScene 没有记来源路径, 报错文案要用 —— 由 load_runtime_scene 挂上。"""
    return getattr(scene, "_ptlc_source", "(未知 GLB)")


def load_runtime_scene(path: Path) -> GlbScene:
    """载入运行期 GLB(前端与 clip_compiler 实际消费的那份)。

    它由 04_optimize 产出、在重建链里排在本步**之后**, 所以这里读到的是上一轮的产物 ——
    与本脚本读上一轮 manifest 结构段是同一条约定(见 three_d_authoring 的 item-grips 注释)。
    上一轮陈旧到几何都变了的情形由 assert_same_world_geometry 抓。
    """
    if not path.is_file():
        raise SystemExit(
            f"缺运行期 GLB: {path} —— grabLocal 必须落在运行期帧里(量化会改节点局部系), "
            "全新环境请先跑一次 04_optimize.mjs --output ../models/machine.official-cr5.glb")
    scene = GlbScene(path)
    scene._ptlc_source = str(path)
    return scene


def assert_same_world_geometry(fit: GlbScene, runtime: GlbScene, node_path: str) -> float:
    """硬断言: 同名子树在两份 GLB 里是同一块世界几何(否则搬运 grabLocal 无意义)。

    这是防"运行期 GLB 陈旧"的唯一闸门 —— 量化只重新分配 TRS 与顶点码值, 世界盒实测只
    差 0.001mm; 一旦有人改了几何却没重跑 04, 这里立刻点名, 而不是让一个错了几十毫米的
    抓取点静静发到前端。
    """
    fit_low, fit_high = _accessor_world_box(fit, node_path)
    run_low, run_high = _accessor_world_box(runtime, node_path)
    delta = float(max(np.abs(fit_low - run_low).max(), np.abs(fit_high - run_high).max()) * 1000.0)
    if delta > RUNTIME_FRAME_BOX_TOL_MM:
        raise SystemExit(
            f"{node_path} 在拟合帧与运行期帧的世界包围盒差 {delta:.3f}mm > "
            f"{RUNTIME_FRAME_BOX_TOL_MM} —— 运行期 GLB({Path(scene_path_of(runtime)).name}) "
            f"陈旧或几何被换过, 先重跑 04_optimize.mjs 再跑本脚本。\n"
            f"  拟合帧 盒(mm) min={np.round(fit_low * 1000, 2)} max={np.round(fit_high * 1000, 2)}\n"
            f"  运行期 盒(mm) min={np.round(run_low * 1000, 2)} max={np.round(run_high * 1000, 2)}")
    return delta


def rebase_grab_local(grab_local: list[float], node_path: str,
                      fit: GlbScene, runtime: GlbScene) -> list[float]:
    """把 grabLocal 从拟合帧的节点局部系搬到**运行期帧**的节点局部系。

    ⚠ 这一步不是可选的美化。节点局部平移量在两份 GLB 之间**不可搬运**:
    04_optimize 的 meshopt 量化会把件的几何缩进 int16 码值、再把补偿塞进节点 TRS ——
    瓶子那六个件在 work/machine.full.glb 里是 scale=1、原点在瓶底, 在
    models/machine.official-cr5.glb 里是 scale≈0.0475、原点在几何中心。于是拟合期算出的
    瓶颈 y=0.089(米)被运行期读成 0.089×0.0475=4.2mm, 而瓶颈其实在中心上方 41.5mm ——
    实测世界点差 37.3mm, 正是用户报的"夹起瓶子没有在中心"。粉桶那几族 scale 恰好是 1,
    躲过了这个坑, 所以它一直是对的。
    (同一条坑在 gen_twin_manifest 的 mountOffsetParent 上记过一次。)

    做法: 拟合帧算世界点 → 运行期帧反解回局部。两帧的世界几何必须一致, 由调用方的
    世界盒断言把关。
    """
    grab_world = fit.world_matrix(node_path) @ np.append(np.asarray(grab_local, dtype=float), 1.0)
    local = (np.linalg.inv(runtime.world_matrix(node_path)) @ grab_world)[:3]
    return [round(float(v), 6) for v in local]


def _subtree(children: dict[str, list[str]], root: str,
             exclude_prefixes: tuple[str, ...] = ()) -> list[str]:
    names, stack = [], [root]
    while stack:
        node = stack.pop()
        # 整支剪掉被排除的分支(如 LIQUID_*): 液柱几何会把径向轮廓拉歪
        if node != root and any(node.startswith(prefix) for prefix in exclude_prefixes):
            continue
        names.append(node)
        stack.extend(children.get(node, ()))
    return names


def _world_vertices(scene: trimesh.Scene, children: dict[str, list[str]], root: str,
                    exclude_prefixes: tuple[str, ...] = ()) -> np.ndarray:
    """一个子树的全部顶点(世界系)。与 export_payload_poses.subtree_center 同口径。"""
    chunks: list[np.ndarray] = []
    for node in _subtree(children, root, exclude_prefixes):
        transform, geometry = scene.graph.get(node)
        if geometry is None:
            continue
        vertices = scene.geometry[geometry].vertices
        homogeneous = np.column_stack((vertices, np.ones(len(vertices))))
        chunks.append((transform @ homogeneous.T).T[:, :3])
    if not chunks:
        raise SystemExit(f"子树 {root!r} 没有任何网格顶点")
    return np.vstack(chunks)


def solve_pin_cage(glb: GlbScene, scene: trimesh.Scene,
                   children: dict[str, list[str]], manifest: dict) -> dict:
    """解 rob_grip_vial 四销笼中心, 折算到 TOOL_MOUNT 系。

    Returns:
        {"positionMount": [3], "pinAxisTool": [3], "halfGapOpenMm": float,
         "fingerTravelToHoldMm": float, "cageCenterTool": [3]}
    """
    linkage = next((item for item in manifest.get("linkages") or []
                    if item.get("id") == "rob_grip_vial"), None)
    if linkage is None:
        raise SystemExit("manifest 里没有 rob_grip_vial 联动组")
    members = linkage.get("members") or []
    if len(members) != 2:
        raise SystemExit(f"rob_grip_vial 期望恰好两指, 实得 {len(members)}")
    tool = next((item for item in manifest.get("tools") or []
                 if item.get("id") == "TOOL_VIAL"), None)
    if tool is None or not tool.get("mountPosition") or not tool.get("mountQuaternion"):
        raise SystemExit("manifest.tools 里没有 TOOL_VIAL 或缺锁紧位姿(mountPosition/mountQuaternion)")

    inv_tool = np.linalg.inv(glb.world_matrix("TOOL_VIAL"))

    def tool_local(points: np.ndarray) -> np.ndarray:
        homogeneous = np.column_stack((points, np.ones(len(points))))
        return (inv_tool @ homogeneous.T).T[:, :3]

    finger_pins: list[list[np.ndarray]] = []
    finger_centroids: list[np.ndarray] = []
    for member in members:
        leaf = str(member["node"]).rsplit("/", 1)[-1]
        pins = [node for node in _subtree(children, leaf) if node.startswith("短柱")]
        if len(pins) != 2:
            raise SystemExit(
                f"指组 {leaf} 下的短柱(销钉)有 {len(pins)} 根, 期望恰好 2 ——"
                " 夹爪换版或 rig_map 指组成员变了, 卡合特征失效")
        finger_pins.append([tool_local(_world_vertices(scene, children, pin)) for pin in pins])
        finger_centroids.append(tool_local(_world_vertices(scene, children, leaf)).mean(axis=0))

    # 开合方向: 两指几何质心连线(声明轴在各自局部系, 方向号不统一, 用几何差更稳)
    closing = finger_centroids[1] - finger_centroids[0]
    closing /= np.linalg.norm(closing)

    all_pins = [pin for pins in finger_pins for pin in pins]
    # 销轴 = 各销最大延展方向; 断言四根一致且 ⊥ 开合方向
    axes = []
    for pin in all_pins:
        centered = pin - pin.mean(axis=0)
        _u, _s, vh = np.linalg.svd(centered, full_matrices=False)
        axis = vh[0] / np.linalg.norm(vh[0])
        if axes and float(np.dot(axis, axes[0])) < 0:
            axis = -axis
        axes.append(axis)
    pin_axis = np.mean(axes, axis=0)
    pin_axis /= np.linalg.norm(pin_axis)
    if min(abs(float(np.dot(axis, pin_axis))) for axis in axes) < 0.98:
        raise SystemExit("四根销钉的轴向不一致(<cos 11°) —— 认错了网格")
    if abs(float(np.dot(pin_axis, closing))) > 0.2:
        raise SystemExit("销轴与开合方向不垂直 —— 卡合特征假设不成立, 需人工核对夹爪几何")

    cage_center = np.mean([pin.mean(axis=0) for pin in all_pins], axis=0)
    cage_center = cage_center + pin_axis * (GRIP_DEPTH_OFFSET_MM / 1000.0)

    # 开爪半间隙: 每指取两销顶点在"朝向对指"方向上的最内坐标(负值 = 未过两指中线),
    # 两指内侧面间距 = −(inner_L + inner_R)。
    inner = []
    for index, pins in enumerate(finger_pins):
        direction = closing if index == 0 else -closing
        inner.append(max(float((pin @ direction).max()) for pin in pins))
    gap_m = -(inner[0] + inner[1])
    if gap_m <= 0:
        raise SystemExit("四销内侧面已过两指中线(开爪态间隙非正) —— 认错网格或开合方向反了")
    half_gap_m = gap_m / 2.0

    mount_rot = Rotation.from_quat([float(v) for v in tool["mountQuaternion"]]).as_matrix()
    mount_pos = np.asarray([float(v) for v in tool["mountPosition"]], dtype=float)
    center_mount = mount_rot @ cage_center + mount_pos

    stroke_mm = float((members[0].get("outputRange") or [0, 0])[1])
    hold = float(linkage.get("holdValue") or 0.0)
    # 长度轴 = 销轴 × 闭合轴(右手系补全)。这根轴上"咬在物件哪一段"由**示教点**决定
    # (docs/工位摆位偏差溯源_20260805.md §5 定案: 夹爪本就偏一头咬, CAD 摆位是对的;
    # fit_station_alignment 的长度轴同理无约束) —— 磁吸对它必须放手, 否则就是把被
    # 废除的"必须咬中心"假设又引回来, 观感即"到位后自动往后对齐"(2026-08-06 用户报障)。
    length_axis = np.cross(pin_axis, closing)
    length_axis /= np.linalg.norm(length_axis)
    pin_proj = np.concatenate([pin @ pin_axis for pin in all_pins])
    return {
        "positionMount": [round(float(v), 8) for v in center_mount],
        "cageCenterTool": [round(float(v) * 1000.0, 3) for v in cage_center],
        # 以下未圆整字段供 solve_arm_pocket 复用同一套基/坐标, 不再各解一遍以免两处分叉
        "cageCenterToolRaw": cage_center,
        "closingTool": closing,
        "pinAxisTool": [round(float(v), 6) for v in pin_axis],
        "pinAxisToolRaw": pin_axis,
        "lengthAxisToolRaw": length_axis,
        "pinSpanTool": [float(pin_proj.min()), float(pin_proj.max())],
        "mountRot": mount_rot,
        "mountPos": mount_pos,
        "pinAxisMount": [round(float(v), 6) for v in (mount_rot @ pin_axis)],
        "lengthAxisMount": [round(float(v), 6) for v in (mount_rot @ length_axis)],
        "halfGapOpenMm": round(half_gap_m * 1000.0, 3),
        "fingerTravelToHoldMm": round(stroke_mm * hold, 3),
        "strokeMm": stroke_mm,
        "holdValue": hold,
    }


#: 逐族抓取特征声明。半径出处: 2026-08-06 machine.full.glb 逐网格实测(瓶颈 Ø23.6 —— 用户
#: 按实机指认四指夹瓶口; 注射器桶身 Ø28)。**选点靠声明半径, 位置靠网格实测**: CAD 光滑
#: 圆柱面只有端环顶点(中段无顶点), 逐毫米带扫在稀疏镶嵌上全是空带 —— 首版带扫法就死在
#: 这里; 而"半径 ≈ 声明值"的顶点环无论镶嵌疏密都存在。网格对不上声明就硬死, 不许猜。
GRAB_FEATURES = {
    "vial": {"feature": "neck", "radiusMm": 11.8, "tolMm": 0.6},
    "collector": {"feature": "barrel", "radiusMm": 14.0, "tolMm": 0.6},
}


def _fit_circle(points_xy: np.ndarray) -> tuple[np.ndarray, float, float]:
    """代数最小二乘圆拟合(Kasa)。points_xy: (N,2) 毫米。返回 (圆心, 半径, 平均残差毫米)。"""
    a = np.column_stack((points_xy[:, 0], points_xy[:, 1], np.ones(len(points_xy))))
    b = (points_xy ** 2).sum(axis=1)
    solution, *_rest = np.linalg.lstsq(a, b, rcond=None)
    center = solution[:2] / 2.0
    radius = float(np.sqrt(max(float(solution[2]) + float(center @ center), 0.0)))
    residual = np.abs(np.linalg.norm(points_xy - center, axis=1) - radius)
    return center, radius, float(residual.mean())


def solve_arm_pocket(glb: GlbScene, scene: trimesh.Scene,
                     children: dict[str, list[str]], manifest: dict, cage: dict) -> dict:
    """解指臂弧口袋中心(粉桶的真实卡合特征), 折算到 TOOL_MOUNT 系。

    为什么销笼不是粉桶的锚点(2026-08-07 实测定案): 示教点把桶轴放在工具长度轴 x≈72.6
    处(中转A 桶轴 72.62 vs 口袋轴心 72.67, 吻合 0.06mm), 而销笼在 x≈29.8 —— 硬件设计是
    **销笼夹瓶颈、指臂弧口袋抱桶身**。把桶锚在销笼心, 弧臂闭合后离桶 1.2~6.6mm 贴不上,
    即用户报障的"夹爪闭合离粉桶外径还差很多"。

    做法(全程 TOOL_VIAL 局部系): 指臂体顶点 = 指子树剔 短柱 前缀 → 限臂带(销顶之上,
    界线取自实测销跨度, 不写死常量)→ 沿长度轴 1mm 分箱取每指内侧面 → half_gap(x) 轮廓
    → 口袋 = 高出侧翼平台 ≥2mm 的连续段 → 每指口袋内表面点圆拟合得 (x, y) 心。
    锚点: x = 两指拟合心均值, y = 两心中点(对称闭合下的不变量, 任何开度都成立),
    z = 笼心 z(粉桶销轴在 freeAxes 里放开, 该分量不驱动画面)。

    可证伪自检(夹爪/耗材换版在这里大声死, 不在屏幕上静默歪):
      ① 两指口袋弧**半径**必须 ≈ 桶身半径(实测双指均 13.95 vs 桶 13.95 —— 口袋就是
         按桶身半径铣的摇篮);
      ② 摇篮同心闭合值 = 两弧心开爪 y 距/(2×行程), 实测 20.43/(2×12.5)=**0.817**,
         须落 [0.5,0.95] —— 这才是粉桶的真实闭合深度, rig_map holdValue 0.101 是
         "瓶身贴销"的旧标定, 弧臂只动 1.26mm 离桶还差 ~9mm。
    """
    linkage = next((item for item in manifest.get("linkages") or []
                    if item.get("id") == "rob_grip_vial"), None)
    if linkage is None:
        raise SystemExit("solve_arm_pocket: manifest 缺 rob_grip_vial")
    inv_tool = np.linalg.inv(glb.world_matrix("TOOL_VIAL"))

    def tool_local(points: np.ndarray) -> np.ndarray:
        homogeneous = np.column_stack((points, np.ones(len(points))))
        return (inv_tool @ homogeneous.T).T[:, :3]

    closing = np.asarray(cage["closingTool"], dtype=float)
    pin_axis = np.asarray(cage["pinAxisToolRaw"], dtype=float)
    length_axis = np.asarray(cage["lengthAxisToolRaw"], dtype=float)
    cage_center = np.asarray(cage["cageCenterToolRaw"], dtype=float)
    pin_top = float(max(cage["pinSpanTool"]))

    arms: list[np.ndarray] = []
    for index, member in enumerate(linkage.get("members") or []):
        leaf = str(member["node"]).rsplit("/", 1)[-1]
        verts = tool_local(_world_vertices(scene, children, leaf, exclude_prefixes=("短柱",)))
        band = verts[(verts @ pin_axis) >= pin_top - 0.002]  # 臂带 = 销顶之上(2mm 余量)
        if len(band) < 50:
            raise SystemExit(f"solve_arm_pocket: 指 {leaf} 臂带只剩 {len(band)} 点, 几何异常")
        arms.append(band)

    def profile(bin_mm: float) -> tuple[np.ndarray, list[float], list[list[float]]]:
        x_lo = max(float((arm @ length_axis).min()) for arm in arms) * 1000.0
        x_hi = min(float((arm @ length_axis).max()) for arm in arms) * 1000.0
        xs = np.arange(math.floor(x_lo), math.ceil(x_hi), bin_mm)
        gaps: list[float] = []
        inners: list[list[float]] = []
        for x in xs:
            vals = []
            for index, arm in enumerate(arms):
                direction = closing if index == 0 else -closing
                x_mm = (arm @ length_axis) * 1000.0
                mask = (x_mm >= x) & (x_mm < x + bin_mm)
                vals.append(float((arm[mask] @ direction).max() * 1000.0)
                            if mask.any() else float("nan"))
            inners.append(vals)
            gaps.append(float("nan") if any(math.isnan(v) for v in vals)
                        else -(vals[0] + vals[1]) / 2.0)
        return xs, gaps, inners

    xs, gaps, _inners = profile(1.0)
    window = [(x, g) for x, g in zip(xs, gaps) if 55.0 <= x <= 90.0 and not math.isnan(g)]
    if sum(1 for x, g in zip(xs, gaps) if 55.0 <= x <= 90.0 and math.isnan(g)) > 0.4 * max(
            1, sum(1 for x in xs if 55.0 <= x <= 90.0)):
        xs, gaps, _inners = profile(2.0)  # 稀疏镶嵌兜底: 分箱放宽到 2mm, 再不行就死
        window = [(x, g) for x, g in zip(xs, gaps) if 55.0 <= x <= 90.0 and not math.isnan(g)]
    if not window or max(g for _x, g in window) < 20.0:
        raise SystemExit(
            f"solve_arm_pocket: x∈[55,90] 内最大半间隙 "
            f"{max((g for _x, g in window), default=float('nan')):.2f}mm < 20 —— 口袋不存在?"
            f" 轮廓: {[(round(x, 1), round(g, 2)) for x, g in zip(xs, gaps)][:60]}")
    flank = [g for x, g in zip(xs, gaps) if 45.0 <= x <= 55.0 and not math.isnan(g)]
    plateau = float(np.median(flank)) if flank else 13.5
    pocket_bins = [x for x, g in window if g >= plateau + 2.0]
    span_lo, span_hi = min(pocket_bins), max(pocket_bins) + 1.0

    centers: list[np.ndarray] = []
    residuals: list[float] = []
    radii: list[float] = []
    for index, arm in enumerate(arms):
        direction = closing if index == 0 else -closing
        x_mm = (arm @ length_axis) * 1000.0
        inner_mm = (arm @ direction) * 1000.0
        y_mm = (arm @ closing) * 1000.0
        # 口袋内表面皮: 逐箱取内侧最大值 −1.5mm 以内的点(剔外表面/加强筋), 并记每箱深度
        skin = np.zeros(len(arm), dtype=bool)
        bin_depth: dict[int, float] = {}
        for x in np.arange(span_lo, span_hi):
            mask = (x_mm >= x) & (x_mm < x + 1.0)
            if not mask.any():
                continue
            top = float(inner_mm[mask].max())
            bin_depth[int(x)] = top
            skin |= mask & (inner_mm >= top - 1.5)
        if int(skin.sum()) < 12:
            raise SystemExit(f"solve_arm_pocket: 指{index} 口袋内表面点仅 {int(skin.sum())}")
        # "深核先拟、全皮吸附": 口袋两端的肩部弯折不在弧上, 从含肩初拟出发迭代修剪收敛
        # 不动(实测半径卡在 15.2-15.6)。先用离最大深度 ≤4mm 的箱(纯弧段)拟出干净圆,
        # 再吸附全体皮点中距该圆 ≤1mm 的内点重拟两轮 —— 实测收敛到 r13.95/残差 0.25。
        points = np.column_stack((x_mm[skin], y_mm[skin]))
        # inner 是"朝对指方向的投影", 恒为负且**越负越深**(离中线越远=口袋越凹);
        # 深核 = 最负端 4mm 内的箱(纯弧段), 肩台在浅端(−17..−19)天然出局
        depth_floor = min(bin_depth.values())
        core_bins = {b for b, d in bin_depth.items() if d <= depth_floor + 4.0}
        core_mask = np.array([int(x) in core_bins for x in points[:, 0]])
        if int(core_mask.sum()) < 12:
            raise SystemExit(
                f"solve_arm_pocket: 指{index} 深核点仅 {int(core_mask.sum())}, "
                f"箱深: {sorted(bin_depth.items())}")
        center, radius_fit, residual = _fit_circle(points[core_mask])
        for _round in range(2):
            keep = np.abs(np.linalg.norm(points - center, axis=1) - radius_fit) <= 1.0
            if int(keep.sum()) < 12:
                break
            center, radius_fit, residual = _fit_circle(points[keep])
        if residual > 0.5:
            raise SystemExit(
                f"solve_arm_pocket: 指{index} 口袋弧拟合残差 {residual:.2f}mm > 0.5 "
                f"(半径 {radius_fit:.1f}, 心 {np.round(center, 2)}) —— 口袋面被污染或几何换版")
        if os.environ.get("PTLC_GRIP_DEBUG"):
            print(f"[debug] 指{index}: span [{span_lo},{span_hi}) 深核箱 {sorted(core_bins)} "
                  f"核点 {int(core_mask.sum())}/{len(points)} -> 心 {np.round(center, 2)} "
                  f"r {radius_fit:.2f} 残差 {residual:.3f}")
        centers.append(np.asarray(center, dtype=float))
        residuals.append(residual)
        radii.append(radius_fit)

    if abs(float(centers[0][0] - centers[1][0])) > 2.0:
        raise SystemExit(
            f"solve_arm_pocket: 两指口袋 x 心不一致 {centers[0][0]:.2f} vs {centers[1][0]:.2f}")
    pocket_x = float((centers[0][0] + centers[1][0]) / 2.0)
    y_mid = float((centers[0][1] + centers[1][1]) / 2.0)
    y_sep = abs(float(centers[0][1] - centers[1][1]))
    if not 60.0 <= pocket_x <= 85.0:
        raise SystemExit(f"solve_arm_pocket: 口袋 x={pocket_x:.2f}mm 超出 [60,85](实测 72.8)")
    # 口袋弧半径必须 ≈ 桶身半径(2026-08-07 实测两指均 13.95 vs 桶 13.95 —— 口袋就是按
    # 桶身半径铣的摇篮): 差超 1mm 说明认错面或夹爪/耗材换版。
    barrel_radius = GRAB_FEATURES["collector"]["radiusMm"]
    for index, radius_fit in enumerate(radii):
        if abs(radius_fit - barrel_radius) > 1.0:
            raise SystemExit(
                f"solve_arm_pocket: 指{index} 弧半径 {radius_fit:.2f}mm 与桶身半径 "
                f"{barrel_radius}mm 差超 1 —— 口袋面认错或几何换版")
    if not 12.0 <= y_sep <= 26.0:
        raise SystemExit(
            f"solve_arm_pocket: 两弧心开爪 y 距 {y_sep:.2f}mm 超出 [12,26](实测 20.43)")
    # 摇篮同心闭合值: 两弧心合拢到重合(=桶轴)所需行程 / 单指行程。实测 20.43/(2×12.5)
    # =0.817 —— 这才是粉桶的真实闭合深度; rig_map holdValue 0.101 是"瓶身贴销"的旧标定,
    # 用在粉桶上弧臂只动 1.26mm, 离桶还差 ~9mm(用户报障"闭合离外径差很多"的另一半病根)。
    concentric = y_sep / (2.0 * float(cage["strokeMm"]))
    if not 0.5 <= concentric <= 0.95:
        raise SystemExit(
            f"solve_arm_pocket: 摇篮同心闭合值 {concentric:.4f} 超出 [0.5,0.95] —— 几何异常")

    anchor_tool = (length_axis * (pocket_x / 1000.0)
                   + closing * (y_mid / 1000.0)
                   + pin_axis * float(cage_center @ pin_axis))
    mount_rot = np.asarray(cage["mountRot"], dtype=float)
    mount_pos = np.asarray(cage["mountPos"], dtype=float)
    anchor_mount = mount_rot @ anchor_tool + mount_pos
    return {
        "positionMount": [round(float(v), 8) for v in anchor_mount],
        "pocketCenterTool": [round(pocket_x, 3), round(y_mid, 3)],
        "pocketConcentricValue": round(concentric, 6),
        "pocketArcRadiusMm": round(float(np.mean(radii)), 3),
        "pocketFitResidualMm": round(max(residuals), 3),
        "pocketSpanMm": [round(span_lo, 1), round(span_hi, 1)],
    }


def item_family(item_id: str, node_leaf: str) -> str:
    """载荷 id/节点名 → 抓取族。认不出就硬死 —— 新种类耗材必须显式归族。"""
    if "BOTTLE" in item_id or "STAGING_B" in item_id or node_leaf.startswith("样品瓶"):
        return "vial"
    if ("COLLECTOR" in item_id or "STAGING_A" in item_id or "HOLDER" in item_id
            or node_leaf.startswith("硅胶收集")):
        return "collector"
    raise SystemExit(f"载荷 {item_id}({node_leaf}) 无法归入抓取族 —— 在 item_family 里显式声明")


def solve_grab_feature(scene: trimesh.Scene, children: dict[str, list[str]],
                       node_leaf: str, family: str, half_gap_open_mm: float) -> dict:
    """单件的抓取特征点 —— 瓶颈(neck)或注射器桶身(barrel)。

    "抓取基准要瞄卡合特征而不是包围盒中心"(fit_station_alignment 头注, 托盘凹槽
    2026-08-05 定案)的单件版: 此前把物件**几何中心**平移到销笼中心, 瓶被抬 55.9mm、
    销子跨在瓶身中段; 真机四指夹的是**瓶颈**。

    做法: 子树顶点(剔 LIQUID_* 分支)→ SVD 主轴 → 取 |半径−声明值|≤容差 的顶点
    → 沿轴向 ε=3mm 单链聚段:
      neck   —— 取**触及轴向端点(±2mm)**的段(圆顶上同半径的伪环离端 ~15mm, 不会
                误中), 并向内并入 ≤20mm 处的最近邻段(颈壁只有上下两个端环, 上环在
                瓶口、下环在颈根, 并起来才是整个颈)→ 段中点 = 颈中;
      barrel —— 全部匹配点的轴向全跨(桶身端环散布在多个子网格上), 跨度必须 ≥20mm;
                桶身类的销轴随后在 freeAxes 里放开, 轴向取哪点本就不驱动画面。
    匹配点不足/段不唯一/跨度异常一律 SystemExit 并倾倒半径直方图 —— 换版件在这里
    大声死, 不许猜。

    返回: {"grabLocal": 件节点局部系米, "feature": "neck"|"barrel",
           "diameterMm": 实测直径, "spanMm": [lo, hi] 沿主轴毫米}
    """
    spec = GRAB_FEATURES[family]
    verts = _world_vertices(scene, children, node_leaf, exclude_prefixes=("LIQUID_",))
    centroid = verts.mean(axis=0)
    centered = verts - centroid
    _u, _s, vh = np.linalg.svd(centered, full_matrices=False)
    axis = vh[0] / np.linalg.norm(vh[0])
    t_mm = (centered @ axis) * 1000.0
    radial_mm = np.linalg.norm(centered - np.outer(centered @ axis, axis), axis=1) * 1000.0

    match = np.abs(radial_mm - spec["radiusMm"]) <= spec["tolMm"]
    if int(match.sum()) < 12:
        hist = np.bincount(np.clip(radial_mm.astype(int), 0, 40))
        raise SystemExit(
            f"{node_leaf}({family}) 半径 {spec['radiusMm']}±{spec['tolMm']}mm 的顶点只有 "
            f"{int(match.sum())} 个(<12) —— CAD 换件或归族错误。半径直方图(mm:个): "
            f"{[(r, int(c)) for r, c in enumerate(hist) if c]}")
    t_match = np.sort(t_mm[match])
    segments: list[tuple[float, float]] = []
    seg_lo = t_match[0]
    prev = t_match[0]
    for value in t_match[1:]:
        if value - prev > 3.0:
            segments.append((seg_lo, prev))
            seg_lo = value
        prev = value
    segments.append((seg_lo, prev))

    if spec["feature"] == "neck":
        t_lo, t_hi = float(t_mm.min()), float(t_mm.max())
        touching = [seg for seg in segments if seg[1] >= t_hi - 2.0 or seg[0] <= t_lo + 2.0]
        if len(touching) != 1:
            raise SystemExit(
                f"{node_leaf}({family}) 触及轴向端点的颈段有 {len(touching)} 个, 期望恰 1 "
                f"—— 段表: {[(round(a, 1), round(b, 1)) for a, b in segments]}")
        chosen = touching[0]
        # 颈壁只有两个端环: 向内并入最近邻段(≤20mm)才覆盖整个颈; 圆顶伪环离得远(>70mm)
        inward = [seg for seg in segments if seg != chosen
                  and min(abs(chosen[0] - seg[1]), abs(seg[0] - chosen[1])) <= 20.0]
        for seg in inward:
            chosen = (min(chosen[0], seg[0]), max(chosen[1], seg[1]))
        span = chosen[1] - chosen[0]
        if not 6.0 <= span <= 30.0:
            raise SystemExit(
                f"{node_leaf}({family}) 颈段跨度 {span:.1f}mm 不在 [6,30] —— 段表: "
                f"{[(round(a, 1), round(b, 1)) for a, b in segments]}")
    else:  # barrel
        chosen = (float(t_match[0]), float(t_match[-1]))
        if chosen[1] - chosen[0] < 20.0:
            raise SystemExit(
                f"{node_leaf}({family}) 桶身匹配跨度 {chosen[1] - chosen[0]:.1f}mm < 20 "
                f"—— 段表: {[(round(a, 1), round(b, 1)) for a, b in segments]}")

    in_span = match & (t_mm >= chosen[0] - 1e-6) & (t_mm <= chosen[1] + 1e-6)
    measured_radius = float(radial_mm[in_span].mean())
    if measured_radius >= half_gap_open_mm:
        raise SystemExit(
            f"{node_leaf} 特征半径 {measured_radius:.2f}mm ≥ 开爪半间隙 {half_gap_open_mm}mm")

    mid_m = (chosen[0] + chosen[1]) / 2.0 / 1000.0
    grab_world = centroid + axis * mid_m
    transform, _geometry = scene.graph.get(node_leaf)
    grab_local = (np.linalg.inv(np.asarray(transform, dtype=float))
                  @ np.append(grab_world, 1.0))[:3]
    return {
        "grabLocal": [round(float(v), 6) for v in grab_local],
        "feature": spec["feature"],
        "diameterMm": round(measured_radius * 2.0, 2),
        "spanMm": [round(chosen[0], 1), round(chosen[1], 1)],
    }


def item_radius_mm(scene: trimesh.Scene, children: dict[str, list[str]], leaf: str) -> float:
    """单件的圆柱体半径(80 分位, 排回转体口沿/倒角噪声)。"""
    verts = _world_vertices(scene, children, leaf)
    centered = verts - verts.mean(axis=0)
    _u, _s, vh = np.linalg.svd(centered, full_matrices=False)
    axis = vh[0]
    radial = centered - np.outer(centered @ axis, axis)
    return float(np.quantile(np.linalg.norm(radial, axis=1), 0.8) * 1000.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="解算单件耗材的在手锚点(四销笼中心)")
    parser.add_argument("--model", default=str(ROOT / "work" / "machine.full.glb"))
    # 运行期帧: grabLocal 最终要落在**这一份**的节点局部系里(前端 loadModel 与
    # clip_compiler 都读它)。量化让两份 GLB 的节点局部系不同, 见 rebase_grab_local。
    parser.add_argument("--runtime-model",
                        default=str(ROOT / "models" / "machine.official-cr5.glb"))
    parser.add_argument("--manifest",
                        default=str(ROOT / "models" / "device-manifest.official-cr5.json"))
    parser.add_argument("--output", default=str(ROOT / "generated" / "payload-grips.json"))
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    glb = GlbScene(args.model)
    runtime = load_runtime_scene(Path(args.runtime_model))
    scene = trimesh.load(Path(args.model), force="scene")
    children: dict[str, list[str]] = {}
    for parent, child, *_rest in scene.graph.to_edgelist():
        children.setdefault(str(parent), []).append(str(child))

    cage = solve_pin_cage(glb, scene, children, manifest)

    # 可证伪自检: 开爪半间隙 ≈ 瓶体半径 + 开→合行程
    radius = item_radius_mm(scene, children, "INV_STAGING_B_ITEM_1")
    expect = radius + cage["fingerTravelToHoldMm"]
    gap = abs(cage["halfGapOpenMm"] - expect)
    if gap > CAGE_CHECK_TOL_MM:
        raise SystemExit(
            f"四销笼自检失败: 开爪半间隙 {cage['halfGapOpenMm']}mm vs 瓶体 {radius:.1f}mm"
            f" + 行程 {cage['fingerTravelToHoldMm']}mm = {expect:.1f}mm, 差 {gap:.1f}mm"
            f" > {CAGE_CHECK_TOL_MM} —— 夹爪换版或认错网格")

    # 单件清单**从 manifest 反查**(kind=item 且 grip=rob_grip_vial), 不在这里另写一份。
    # 逐件解抓取特征: STA_* 的 id 与节点叶名不同, 站侧 CAD 实例朝向也各异 —— 特征点存
    # **件节点局部系**, 朝向差异自然消解。
    items = [(att["id"], str(att["node"]).rsplit("/", 1)[-1])
             for att in manifest.get("attachments") or []
             if (att.get("payload") or {}).get("kind") == "item"
             and (att.get("payload") or {}).get("grip") == "rob_grip_vial"]
    if not items:
        raise SystemExit("manifest 里没有任何 kind=item / grip=rob_grip_vial 的载荷")

    output = Path(args.output)
    doc = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {
        "schema": "ptlc.payload-grips/v1", "generatedFrom": Path(args.model).name, "grips": {}}
    grips = doc.setdefault("grips", {})
    pocket = solve_arm_pocket(glb, scene, children, manifest, cage)

    features_seen: dict[str, list[str]] = {}
    rebased: list[str] = []
    for item_id, leaf in items:
        family = item_family(item_id, leaf)
        feature = solve_grab_feature(scene, children, leaf, family, cage["halfGapOpenMm"])
        # 抓取点搬进运行期帧 —— 拟合在 machine.full.glb 上做(能解码几何), 消费在
        # machine.official-cr5.glb 上做(量化后节点局部系不同)。先断言两帧世界几何一致。
        box_delta = assert_same_world_geometry(glb, runtime, leaf)
        fit_local = feature["grabLocal"]
        feature["grabLocal"] = rebase_grab_local(fit_local, leaf, glb, runtime)
        if not np.allclose(fit_local, feature["grabLocal"], atol=1e-6):
            rebased.append(f"{item_id}: {fit_local} → {feature['grabLocal']} (盒差 {box_delta:.3f}mm)")
        if feature["feature"] == "neck":
            # 瓶: 销笼夹瓶颈。销笼对回转体是**双水平轴定心**特征, 三轴全锚定
            # (freeAxes=[]) —— 2026-08-07 定案: 此前放开长度轴让 ~18mm 示教偏差全程
            # 保留, 用户报障"夹起瓶子没有在中心"。"长度不约束"的 2026-08-05 定案只
            # 适用于托盘榫槽那种沿长开放的特征。
            anchor = cage["positionMount"]
            free_axes: list = []
            # 闭合到瓶颈: 销面贴颈 = (开爪半间隙 − 颈半径)/单指行程 = 0.2543
            close_value = round(
                (cage["halfGapOpenMm"] - feature["diameterMm"] / 2.0) / cage["strokeMm"], 6)
        else:
            # 粉桶: 指臂弧口袋抱桶身(锚点=口袋心, 见 solve_arm_pocket 头注)。销轴仍
            # 放开 —— 均匀圆柱沿轴无几何基准, 轴向咬哪段是示教事实, 磁吸只修水平两向。
            anchor = pocket["positionMount"]
            free_axes = [cage["pinAxisMount"]]
            # 闭合到摇篮同心: 两弧心并到桶轴 = 0.817(见 solve_arm_pocket 自检②)
            close_value = pocket["pocketConcentricValue"]
        if not 0.0 < close_value <= 1.0:
            raise SystemExit(
                f"{item_id} 闭合值 {close_value} 越界 (0,1] —— 特征/行程数据异常")
        entry = {
            "position": anchor,
            "quaternion": [0.0, 0.0, 0.0, 1.0],
            "method": "pin-cage-grab-feature",
            "gripper": "rob_grip_vial",
            "halfGapOpenMm": cage["halfGapOpenMm"],
            "freeAxes": free_axes,
            "grabLocal": feature["grabLocal"],
            "grabFeature": feature["feature"],
            "grabDiameterMm": feature["diameterMm"],
            # 闭合深度**逐件下发**(公式只活在本文件): 瓶颈=销面贴颈 0.2543, 粉桶=摇篮
            # 同心 0.817。消费端 clip_compiler._close_value_for(编译片段链); 实时/近似链
            # 仍走 manifest holdValue 兜底(布尔持料语义拿不到载荷身份)。
            "closeValue": close_value,
        }
        if feature["feature"] == "barrel":
            # 纯出处字段(manifest 白名单有意不透传): 口袋几何的可追溯记录
            entry["pocketCenterTool"] = pocket["pocketCenterTool"]
            entry["pocketConcentricValue"] = pocket["pocketConcentricValue"]
            entry["pocketFitResidualMm"] = pocket["pocketFitResidualMm"]
        grips[item_id] = entry
        features_seen.setdefault(feature["feature"], []).append(item_id)
    doc["itemGripNote"] = (
        "kind=item 的条目是**位置吸附**语义, quaternion 恒单位、仅占位。position 逐族: "
        "瓶=四销笼心(销笼夹瓶颈), 粉桶=指臂弧口袋心(弧口袋抱桶身, 2026-08-07 实测定案)。"
        "挂载时把物件的 grabLocal 特征点平移到该点、姿态保留当刻朝向, freeAxes 上的分量"
        "放手不修(瓶=空: 销笼双水平轴定心; 桶=[销轴]: 轴向咬哪段由示教定)。"
        "消费端: MachineStateDriver.attach(磁吸) 与 clip_compiler._grab_corrected(烤 dock)"
        "必须逐字同式; 闭合深度见 clip_compiler._close_value_for(瓶颈逐件, 桶身走 holdValue)。"
        f"自检: 开爪半间隙 {cage['halfGapOpenMm']}mm ≈ 瓶体 {radius:.1f}mm"
        f" + 行程 {cage['fingerTravelToHoldMm']}mm; 口袋同心值 {pocket['pocketConcentricValue']}"
        f" ≈ holdValue {cage['holdValue']}。"
        f"grabLocal 存的是**运行期帧**({Path(args.runtime_model).name})的节点局部系坐标, "
        "量化件与拟合帧不同值(见 rebase_grab_local)。")
    doc["runtimeFrame"] = Path(args.runtime_model).name
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if rebased:
        print(f"grabLocal 搬入运行期帧({Path(args.runtime_model).name})的量化件 {len(rebased)} 个:")
        for line in rebased:
            print(f"  {line}")
    print(f"四销笼中心(TOOL_MOUNT 系) {cage['positionMount']} "
          f"(工具系 {cage['cageCenterTool']}mm, 半间隙 {cage['halfGapOpenMm']}mm); "
          f"弧口袋心(工具系 x,y) {pocket['pocketCenterTool']}mm, "
          f"同心值 {pocket['pocketConcentricValue']}, 残差 {pocket['pocketFitResidualMm']}mm; "
          "逐件特征: " + ", ".join(
              f"{name}×{len(ids)}" for name, ids in sorted(features_seen.items()))
          + f"; 写入 {len(items)} 个单件锚点 -> {output.name}")


if __name__ == "__main__":
    main()
