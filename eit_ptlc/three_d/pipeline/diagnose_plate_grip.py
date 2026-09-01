"""持板常量判别: 把"板该在哪"与"plateGrip 说板在哪"的差, 摊到**吸盘自己的坐标系**里。

为什么要有它(与 verify_plate_seats 的分工):
    verify_plate_seats 是**相对**判据 —— 各站与同翻转态的中位数比。它抓得住"某一站
    的板托座骑在没被驱动的工位轴上"这类**站间不一致**, 但结构上抓不到各站**均匀**的
    刀具常量误差: 那种误差把所有站一起平移, 中位数跟着走, 偏离恒为 0。
    2026-08-05 实测到的 ~17.9mm 持板偏差就是这么全绿走过去的。

    本模块做的是**绝对**核对, 且刻意把结果表达在**翻转节点局部系**里 —— 那里
    plateGrip 的三个常量(contactLocalM / axisLocal / spanAxisLocal)就是坐标本身,
    误差落在哪根轴上一眼可读:
        · 沿 axisLocal(吸盘轴)偏 → 唇口位置不对(杯长/杯建模态/示教时的实际刀具)
        · 沿 spanAxisLocal(两杯连线)偏 → 对中心不对
        · 转角不为 0        → 翻转支点或 180° 行程不对, 与平移是两回事

判别口径(2026-08-05 踩过的坑, 记下来免得再踩):
    · **必须用 pose 反解关节角**, 不能用实测 joint。点表里 P11-P18/P22/P65 十个点是
      "pose 已迁移、joint 未刷新"的半新态(差整整一个基准 ~22mm, 见 clip_compiler
      ._consistent_joint)。动画走的是 move_l → 从 pose 反解, 所以判别也必须跟着 pose,
      否则量到的是"旧基准 vs CAD", 与画面上看到的穿模不是同一回事。
    · **板托座骑在工位轴上, 必须把那些轴一起摆到位**(SEAT_AXES), 只摆机器人不摆托座,
      量出来的是"CAD 建模位 vs 机器人真实位"那个假差(此前 7Y 99mm / 1Z 530mm 的由来)。
    · 橡胶杯节点的原点在**杯身中点**而不是安装端 —— 拿 `原点 − freeLen` 当唇口会得到
      −89.07 这个不存在的位置, 与真唇口 −71.57 正好差半个自由长(17.5mm), 而 17.5 又
      与本模块要查的 ~17.9mm 撞车, 极易误判成"CAD 杯建模偏短"。已在 M1 里显式复核。

用法:
    PTLC_CONTROL_ROOT=<上位机根> python diagnose_plate_grip.py
    PTLC_CONTROL_ROOT=<上位机根> python diagnose_plate_grip.py --cups   # 加做逐顶点杯几何
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

import clip_compiler
import verify_plate_seats as V
from robot_kinematics import load_calibration, forward_kinematics, pose_matrix, solve_ik
from scene_kinematics import GlbScene, RobotPosture
from sync_ptlc_robot import ROOT, _control_root, _load_registry

#: 翻转气缸节点(板挂它下面), 以及从工具根到它的中间层
FLIP_NODE = ("ST_TOOLING/夹具总装-1/TOOL_SUCTION/TOOL_SUCTION_GEOMETRY/"
             "ACTUATOR_FLIP_SUCTION")
TOOL_GEOMETRY_NODE = "ST_TOOLING/夹具总装-1/TOOL_SUCTION/TOOL_SUCTION_GEOMETRY"
TOOL_ID = "TOOL_SUCTION"

#: 标准板总厚(玻璃 2.0 + 硅胶 1.0), 与前端 plateGeometry 的 GLASS_MM/SILICA_MM 默认一致
PLATE_THICK_MM = 3.0

#: 硅胶朝上的落点(真源是前端 PlateSlots.SILICA_UP_SLOTS; 这里镜像一份, 改了要同步)
SILICA_UP_SLOTS = {"spot_seat", "scrape_table"}

#: 翻转态 -> 该态下 rob_flip_suction 的输出角(度)。inputRange[0,1]->outputRange[0,180]
FLIP_DEG = {"down": 0.0, "up": 180.0}


def rigid(translation, quaternion_xyzw) -> np.ndarray:
    """由平移 + 四元数(xyzw)组成 4x4。"""
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_quat(np.asarray(quaternion_xyzw, dtype=float)).as_matrix()
    matrix[:3, 3] = np.asarray(translation, dtype=float)
    return matrix


def plate_local_pose(grip: dict, silica_up: bool,
                     thick_mm: float = PLATE_THICK_MM) -> tuple[np.ndarray, np.ndarray]:
    """plateGrip 说的"板在翻转节点局部系里的位姿" —— 与前端 suctionMountLocal 同一套代数。

    位置那一步在前端是 `contact − faceY * plateY`, 其中 faceY 恒等于 ∓半板厚
    (吸盘永远贴玻璃面, 板体总在接触面的 +axis 一侧), 于是无论 silicaUp 取何值都化简成
    **contact + 半板厚 · axis**。方向则确实随 silicaUp 翻面, 故仍照抄前端的基底构造。

    ⚠ 接触面取的是**压缩后**的唇口(contact − carryCompressionM · axis), 与前端逐字一致。
      本函数是"前端会把板摆在哪"的复算 —— 与 suctionMountLocal 漂开一丝, 判据量到的就
      不再是画面上那块板, 而是一个纸面上的板。改那边必须同步改这里。

    Returns:
        (位置 3 向量(米), 旋转矩阵 3x3)
    """
    axis = np.asarray(grip["axisLocal"], dtype=float)
    axis = axis / np.linalg.norm(axis)
    carry = float(grip.get("carryCompressionM") or 0.0)
    contact = np.asarray(grip["contactLocalM"], dtype=float) - axis * carry
    span = np.asarray(grip["spanAxisLocal"], dtype=float)

    plate_y = axis * (1.0 if silica_up else -1.0)
    span_x = span - plate_y * float(np.dot(span, plate_y))
    span_x = span_x / np.linalg.norm(span_x)
    plate_z = np.cross(span_x, plate_y)

    position = contact + axis * (thick_mm / 2.0 / 1000.0)
    rotation = np.column_stack((span_x, plate_y, plate_z))
    return position, rotation


def flip_world(posture: RobotPosture, scene: GlbScene, manifest: dict,
               flip: str, **pose_kwargs) -> np.ndarray:
    """给定机器人姿态下, 翻转节点的世界矩阵。

    吸盘在 GLB 里停在 ST_TOOLING(工具架)下而**不是**挂在 TOOL_MOUNT 上 —— 上机是运行期
    换父 + 按标定的 mountPosition/mountQuaternion 就位(见 MachineStateDriver.lockTool)。
    所以这里必须显式复算这条链, 不能拿 GLB 静止层级里的世界矩阵当数。
    """
    tool = next(item for item in manifest.get("tools") or [] if item["id"] == TOOL_ID)
    mount = posture.mount_world(**pose_kwargs)
    dock = rigid(tool["mountPosition"], tool["mountQuaternion"])
    geometry = scene.local_matrix(scene.index_of(TOOL_GEOMETRY_NODE))

    local = scene.local_matrix(scene.index_of(FLIP_NODE))
    spec = next(item for item in manifest["actuators"] if item["id"] == "rob_flip_suction")
    axis = np.asarray(spec.get("axis") or [0, 0, 1], dtype=float)
    axis = axis / np.linalg.norm(axis)
    delta = Rotation.from_rotvec(axis * np.deg2rad(FLIP_DEG[flip])).as_matrix()
    turned = local.copy()
    # 后乘: 加载态旋转 @ 局部轴转角(与 RobotJointDriver / scene_kinematics 同一约定)
    turned[:3, :3] = local[:3, :3] @ delta
    return mount @ dock @ geometry @ turned


def seat_errors(scene, posture, manifest, registry, rail_slots, axes_mm,
                source: str = "pose") -> dict[str, dict]:
    """各落点"板该在哪 − plateGrip 说板在哪", 表达在翻转节点局部系(mm)。

    Args:
        source: 'pose' 走反解(动画口径, 默认), 'joint' 走实测关节角(旧基准, 仅供对照)

    Returns:
        {落点: {"point","flip","delta"(3, mm),"normalDeg","spanDeg"}}
    """
    calibration = load_calibration()
    anchors = clip_compiler.resolve_plate_anchors(scene)
    grip = next(item for item in manifest["actuators"]
                if item["id"] == "rob_flip_suction")["plateGrip"]
    by_name = {point.robot_name: point for point in registry.points}

    result: dict[str, dict] = {}
    for point_name, slot, rail_slot, flip in V.SEATS:
        point, anchor = by_name.get(point_name), anchors.get(slot)
        if point is None or anchor is None or not point.joint:
            continue
        if source == "joint":
            joints = list(point.joint)
        else:
            try:
                joints = list(solve_ik(pose_matrix(point.pose), list(point.joint),
                                       calibration, tool=point.tool))
            except Exception as exc:  # pylint: disable=broad-except
                print(f"  [跳过] {point_name} 从 pose 反解失败: {exc}")
                continue

        kwargs = dict(joints_deg=joints, rail_mm=rail_slots[rail_slot], axes_mm=axes_mm)
        tool_world = flip_world(posture, scene, manifest, flip, **kwargs)
        anchor_world = posture.node_world(anchor, **kwargs)

        # 锚点位姿转进翻转节点局部系 —— 在这里 plateGrip 的常量就是坐标本身
        anchor_local = np.linalg.inv(tool_world) @ anchor_world
        expect_position, expect_rotation = plate_local_pose(grip, slot in SILICA_UP_SLOTS)
        delta = (anchor_local[:3, 3] - expect_position) * 1000.0

        # 转角: 板面法线(期望基底的第 2 列)与锚点最接近它的那根轴之间的夹角。
        # 锚点是个近似立方的薄板盒, 面内两轴对方板而言简并(转 90° 同构), 故只判法线。
        #
        # ⚠ 必须**逐列归一化**再点乘: 锚点节点带缩放(玻璃盒是被压扁的单位立方, 薄轴
        #   缩放 ~0.003 而面内 ~0.2), 直接拿矩阵列去点乘等于把长度当余弦, 薄轴那一列
        #   会被缩到几乎为零 —— 首版就是这么读出 84.26° 这种**几何上不可能**的值
        #   (三根正交轴里最接近的一根, 夹角上限是 54.7°)。
        normal = expect_rotation[:, 1]
        cosines = []
        for axis_index in range(3):
            column = anchor_local[:3, axis_index]
            length = float(np.linalg.norm(column))
            cosines.append(abs(float(np.dot(column / length, normal))) if length > 1e-12 else 0.0)
        best = int(np.argmax(cosines))
        normal_deg = float(np.degrees(np.arccos(min(1.0, cosines[best]))))

        # 面内偏航: 锚点的**面内**轴与 expect 面内基底(spanX = 第0列, plateZ = 第2列)的夹角。
        # 方板转 90° 与自身同构(200×200), 所以只有折进 ±45° 的那一份有物理意义 ——
        # 不折就会报出 90° 这种"其实完全贴合"的假大数。
        # 归一化同上: 锚点带缩放, 拿原始列去点乘等于把长度当余弦。
        in_plane = [index for index in range(3) if index != best]
        column = anchor_local[:3, in_plane[0]]
        column = column / max(float(np.linalg.norm(column)), 1e-12)
        yaw = np.degrees(np.arctan2(float(np.dot(column, expect_rotation[:, 2])),
                                    float(np.dot(column, expect_rotation[:, 0]))))
        yaw_deg = float((yaw + 45.0) % 90.0 - 45.0)

        # 世界系下"板该在的位置 − plateGrip 说的位置"。归属工位/塔位要用它:
        # 刀具系已经把各站偏航除掉了, 反而看不出"某个塔整体摆位偏了一个常向量"。
        expect_world = (tool_world @ np.append(expect_position, 1.0))[:3]
        world_delta = (anchor_world[:3, 3] - expect_world) * 1000.0

        result[slot] = {
            "point": point_name, "flip": flip, "delta": delta,
            "worldDelta": world_delta,
            # 两端各自的世界位置也留着: 判"模块内间距对不对"要拿它们相减(同 tank_towers
            # 的节距对照)。只留差值的话, 间距这一类错查不出来 —— 差值把它抵消掉了。
            "anchorWorldMm": anchor_world[:3, 3] * 1000.0,
            "expectWorldMm": expect_world * 1000.0,
            # 归属判别要按地轨槽位分组看(见 attribute_stations 的"地轨相关性"一段),
            # 而槽位号本身不够 —— 六个槽位里有重复值(168/168/…), 要的是毫米数。
            "railMm": float(rail_slots[rail_slot]),
            "normalDeg": normal_deg, "normalAxis": best, "yawDeg": yaw_deg,
        }
    return result


def grip_basis(grip: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """plateGrip 的三根正交轴: (吸盘轴, 两杯连线, 第三轴)。

    单独成函数是因为 verify_plate_seats 的面内判据要用同一组基 —— 两处各写一遍基的构造,
    迟早有一处把 cross 的次序写反, 而那种错在数字上看着完全合理。
    """
    axis = np.asarray(grip["axisLocal"], dtype=float)
    axis = axis / np.linalg.norm(axis)
    span = np.asarray(grip["spanAxisLocal"], dtype=float)
    span = span / np.linalg.norm(span)
    return axis, span, np.cross(axis, span)


def in_plane_mm(grip: dict, delta: np.ndarray) -> float:
    """一笔残差里**面内**(垂直于吸盘轴)那一份的模长, mm。

    面内是软轴: 光板上两只杯落在哪没有几何特征定位(见 INPLANE_IS_SOFT_AXIS)。
    它不该被拿去平移工位, 但必须有人看着 —— 前端 PlateStage._seatHold 的落点捕获窗口
    是有限的, 这个量涨过窗口, 取放板的跳变就会回来。
    """
    axis, _span, _third = grip_basis(grip)
    return float(np.linalg.norm(np.asarray(delta, dtype=float) - axis * np.dot(delta, axis)))


def report_axes(grip: dict, seats: dict) -> dict:
    """把误差投到 plateGrip 的三根轴上并按翻转态汇总 —— 本模块的结论段。"""
    axis, span, third = grip_basis(grip)

    print()
    print("各落点误差在**吸盘局部系**的分解(mm) —— 正号 = 板该比 plateGrip 说的更靠该轴正向")
    print(f"{'点':6}{'落点':14}{'翻转':6}{'沿吸盘轴':>10}{'沿两杯连线':>12}"
          f"{'第三轴':>9}{'合计':>8}{'法线转角':>10}")
    summary: dict[str, dict] = {}
    for flip in ("up", "down"):
        group = {slot: item for slot, item in seats.items() if item["flip"] == flip}
        if not group:
            continue
        rows = []
        for slot, item in group.items():
            delta = item["delta"]
            projected = np.array([float(np.dot(delta, axis)), float(np.dot(delta, span)),
                                  float(np.dot(delta, third))])
            rows.append(projected)
            print(f"{item['point']:6}{slot:14}{flip:6}{projected[0]:+10.2f}{projected[1]:+12.2f}"
                  f"{projected[2]:+9.2f}{np.linalg.norm(delta):8.2f}{item['normalDeg']:9.2f}°")
        stack = np.stack(rows)
        median = np.median(stack, axis=0)
        spread = float(max(np.linalg.norm(row - median) for row in stack))
        summary[flip] = {
            "medianAlongAxisMm": round(float(median[0]), 3),
            "medianAlongSpanMm": round(float(median[1]), 3),
            "medianThirdMm": round(float(median[2]), 3),
            "spreadMm": round(spread, 3),
            "maxNormalDeg": round(max(item["normalDeg"] for item in group.values()), 3),
        }
        print(f"  -> rotary-{flip:5} 中位数 沿轴 {median[0]:+7.2f} / 连线 {median[1]:+7.2f}"
              f" / 第三 {median[2]:+7.2f}   组内散布 {spread:5.2f}mm"
              f"   最大法线转角 {summary[flip]['maxNormalDeg']:.2f}°")
    return summary


def decompose(summary: dict) -> dict:
    """把两翻转态拆成"刀具项"与"其余项" —— 归因的关键一步。

    为什么用两态的**均值**当刀具项: 本模块的读数都表达在翻转节点**自己的**局部系里,
    而该局部系是随节点一起转的 —— 板挂在它下面, plateGrip 的常量在这个系里与转角无关。
    所以一个真的刀具几何误差在两个翻转态下应当读出**同一个值**; 两态的均值就是它。

    反过来, 工具停靠变换 / 工位摆位 / 锚点建模位这些**节点上游或场景侧**的误差, 在这个
    随动局部系里会被 180° 旋转翻个号(且 up/down 两组本来就是不同的站), 于是落在两态的
    **差**里。故: 刀具项 = (up+down)/2, 其余项 = (up−down)/2。

    ⚠ 别拿"法兰系下变不变号"来读本函数的输出 —— 那是另一个系。同一笔误差在法兰系下
      确实变号(实测 −20.1 / +15.6), 在本地系下则同号(−20.10 / −15.53), 两种说法等价。
    """
    if "up" not in summary or "down" not in summary:
        return {}
    up, down = summary["up"], summary["down"]
    out = {}
    for key, label in (("medianAlongAxisMm", "沿吸盘轴"), ("medianAlongSpanMm", "沿两杯连线")):
        # 局部系里"上"态已被 180° 转过, 故同一个刀具误差在两态读数应当**同号等值**;
        # 真正的刀具项 = 两者均值, 站/停靠项 = 两者之差的一半。
        tool = (up[key] + down[key]) / 2.0
        other = (up[key] - down[key]) / 2.0
        out[key] = {"轴": label, "刀具项mm": round(tool, 3), "非刀具项mm": round(other, 3)}
    return out


#: 落点 -> 所属机械模块。归属判别要按**模块**分组而不是按翻转态: 同一模块上的两个落点
#: 若共用一个世界系常向量, 那是模块摆位; 各走各的, 那是逐点示教散。
#: FEEDLIFT 那一对尤其决定性 —— 玻璃上料机构与玻璃下料机构是同图纸孪生, 并排装在
#: 同一块底板上, 它们**不可能**各自偏一个不同的量。
SEAT_STATION = {
    "feedlift": "FEEDLIFT", "waste": "FEEDLIFT",
    "spot_seat": "SAMPLING", "scrape_table": "PHOTOSCRAPE",
    **{f"tank:{n}": "DEVELOP" for n in range(1, 9)},
}

#: 判"一组落点共用同一个常向量"的组内散布上限(mm)。依据是既有实测: 展缸塔内散布
#: 2.20 / 2.05mm(见 tank_towers), 那已被判定为"同属一个刚体"的一组。留一点余量取 3.0,
#: 再大就不该再叫常向量了。
STATION_COHERENT_MM = 3.0

#: 模块内落点间距的 CAD/示教允许差(mm)。超了才是**建模节距**错; 不超就说明模块本身建对了,
#: 那么剩下的残差只可能是"模块整体摆位"或"示教落点", 二者要靠下面那条纪律区分。
PITCH_TOL_MM = 2.0

#: ⚠ 吸盘这条链上, **面内两根轴都是软轴** —— 判归属时必须先读这一条。
#:
#: 依据是 docs/工位摆位偏差溯源_20260805.md §三.4 那条已经付过学费的纪律: 只拟合**有物理
#: 约束**的轴。夹爪那条链上, 榫槽卡合(单边 0.13mm)与槽高(余量 0.81mm)是硬约束, 而"夹爪
#: 沿托盘长边咬在哪"是软的 —— 当年把那根软轴一起拟合, 工位被挪了 23~41mm 去补一个根本
#: 不属于工位的量, 门禁全绿而模型离真机越来越远。
#:
#: 吸盘这条链的软硬之分更极端: 板是 200×200 的**光板**, 两只杯落在板面上, 面内**没有任何
#: 几何特征**定位 —— 落在哪纯由示教时人手停在哪决定。硬约束只剩"杯必须贴住板面"这一根
#: 法向。实测正好印证: 法向残差全场 ≤3mm(见世界系 dY 列), 而面内 4~21mm 且散得开。
#:
#: ⇒ 面内残差**再怎么"共用常向量"也不构成平移工位的许可**。共用常向量只能证明"这一组
#:   落点是一起被教偏的", 证不了"工位摆错了"。真要动几何, 判据必须来自几何本身
#:   (现场卷尺 / 模块间距 / 装配基准), 不能来自落点残差。
INPLANE_IS_SOFT_AXIS = True


def attribute_stations(seats: dict) -> dict:
    """世界系残差按模块分组 —— 判"整站摆位差"还是"逐点示教散"的那一步。

    为什么必须在**世界系**里判(而不是 report_axes 那个吸盘局部系): 局部系随机械臂偏航
    一起转, 同一笔工位摆位误差在偏航差 90°/180° 的两个落点上会读出方向完全不同的分量,
    看起来就像"各站各的" —— 正是 tank_towers 那段注释记下的坑(首版读出 −450.86mm)。

    判据: 一组落点的世界系残差**中位向量**幅值不小、而**组内散布**小于
    STATION_COHERENT_MM ⇒ 该组整体偏了一个常向量 ⇒ 归"模块摆位";
    散布与中位数同量级 ⇒ 归"逐点示教散", 按本文档正题的教训**不得据此平移工位**。

    水平/竖直分开报: 场景是 glTF 轴系(Y 向上), 板是水平的, 所以"面内"= 世界 XZ、
    "沿板法线"= 世界 Y。画面上看到的横向穿模是前者, 2026-08-05 修掉的持板压缩是后者。

    Returns:
        {模块: {"seats", "medianMm", "spreadMm", "horizMm", "coherent"}}
    """
    print()
    print("世界系残差(板该在的位置 − plateGrip 说的位置, mm; glTF 轴系 Y 向上)")
    print(f"{'点':6}{'落点':14}{'模块':12}{'地轨mm':>8}"
          f"{'dX':>9}{'dY(竖直)':>11}{'dZ':>9}{'水平合计':>10}")
    groups: dict[str, list[str]] = {}
    for slot, item in seats.items():
        station = SEAT_STATION.get(slot, "?")
        groups.setdefault(station, []).append(slot)
        delta = item["worldDelta"]
        horiz = float(np.hypot(delta[0], delta[2]))
        print(f"{item['point']:6}{slot:14}{station:12}{item['railMm']:8.1f}"
              f"{delta[0]:+9.2f}{delta[1]:+11.2f}{delta[2]:+9.2f}{horiz:10.2f}")

    print()
    print("按模块归属:")
    out: dict[str, dict] = {}
    for station, slots in groups.items():
        stack = np.stack([seats[slot]["worldDelta"] for slot in slots])
        median = np.median(stack, axis=0)
        spread = float(max(np.linalg.norm(row - median) for row in stack))
        horiz = float(np.hypot(median[0], median[2]))
        coherent = len(slots) > 1 and spread <= STATION_COHERENT_MM
        if len(slots) == 1:
            verdict = "单落点, 组内散布无从谈起"
        elif coherent:
            verdict = f"组内散布 {spread:.2f} ≤ {STATION_COHERENT_MM} ⇒ 这组落点是**一起**被教偏的"
        else:
            verdict = f"组内散布 {spread:.2f} > {STATION_COHERENT_MM} ⇒ 各落点各偏各的"
        print(f"  {station:12}({len(slots)}个落点) 中位 "
              f"({median[0]:+8.2f}, {median[1]:+8.2f}, {median[2]:+8.2f})  水平 {horiz:6.2f}mm")
        print(f"  {'':12} {verdict}")
        out[station] = {
            "seats": sorted(slots),
            "medianMm": [round(float(v), 3) for v in median],
            "spreadMm": round(spread, 3),
            "horizMm": round(horiz, 3),
            "coherent": bool(coherent),
        }

    # 模块内间距对照: 差值判归属, 间距判建模。两者查的不是一回事 —— 一组落点整体偏一个
    # 常向量(差值)是摆位, 而落点**彼此之间**的距离对不上(间距)是建模节距错, 后者在差值
    # 里会互相抵消掉。tank_towers 对八缸做的就是这一步, 这里推广到任意多落点模块。
    print()
    print("模块内落点间距 CAD vs 示教(间距对不上 = 建模节距错, 与整体摆位是两笔账):")
    for station, slots in sorted(groups.items()):
        if len(slots) < 2:
            continue
        for i, a in enumerate(slots):
            for b in slots[i + 1:]:
                cad = float(np.linalg.norm(seats[b]["anchorWorldMm"] - seats[a]["anchorWorldMm"]))
                taught = float(np.linalg.norm(seats[b]["expectWorldMm"] - seats[a]["expectWorldMm"]))
                out.setdefault("_pitch", []).append({
                    "station": station, "from": a, "to": b,
                    "cadMm": round(cad, 3), "taughtMm": round(taught, 3),
                    "diffMm": round(cad - taught, 3),
                })
                # 八缸有 28 对, 全打会把结论淹掉(而且相邻节距 tank_towers 已经打过);
                # 小组全打, 大组只打超差的那些。JSON 里始终是全量。
                if len(slots) > 3 and abs(cad - taught) <= PITCH_TOL_MM:
                    continue
                flag = "" if abs(cad - taught) <= PITCH_TOL_MM else "   <= 超 2mm, 查建模节距"
                print(f"  {station:12}{a:12}-> {b:12} CAD {cad:8.2f}   "
                      f"示教 {taught:8.2f}   差 {cad - taught:+7.2f}{flag}")

    # 地轨相关性: 排除"其实是 axis_11y 的零点/标度错, 被误读成工位摆位"。
    # 地轨沿世界 X 展开, 所以这类错**只**能落在 dX 上, 且应随 |railMm − 零点 500| 单调。
    print()
    print("地轨相关性(排除 axis_11y 零点/标度错; 该类错只落在 dX 且应随离零点距离单调):")
    by_rail: dict[float, list[float]] = {}
    for item in seats.values():
        by_rail.setdefault(round(item["railMm"], 1), []).append(float(item["worldDelta"][0]))
    rail_rows = []
    for rail_mm in sorted(by_rail):
        values = by_rail[rail_mm]
        rail_rows.append({"railMm": rail_mm, "n": len(values),
                          "medianDxMm": round(float(np.median(values)), 3),
                          "spanDxMm": round(float(max(values) - min(values)), 3)})
        print(f"  地轨 {rail_mm:7.1f}mm ({len(values)}个落点) dX 中位 "
              f"{np.median(values):+8.2f}   同槽位内跨度 {max(values) - min(values):6.2f}mm")
    out["_railCorrelation"] = rail_rows

    print()
    print("⚠ 读法(别把上面的'共用常向量'当成平移工位的许可):")
    print("  吸盘链的面内两轴是**软轴** —— 200×200 光板上两只杯落在哪, 纯由示教时人手停在哪")
    print("  决定, 面内没有任何几何特征定位它。硬约束只有'杯贴住板面'那一根法向, 而法向残差")
    print("  实测全场 ≤3mm(dY 列)。所以面内残差证不了工位摆错, 只证明落点是那么教的 ——")
    print("  与 §三.4 那条'只拟合有物理约束的轴'是同一条纪律(当年拟合软轴挪了工位 23~41mm)。")
    print("  要动几何, 判据必须来自几何本身: 现场卷尺 / 模块间距 / 装配基准。")
    return out


#: 落点 -> 中文名, 只用于打印对照表。
SEAT_LABEL = {
    "spot_seat": "点样座", "scrape_table": "刮板台", "feedlift": "上料仓", "waste": "废板仓",
    **{f"tank:{n}": f"展缸{n}" for n in range(1, 9)},
}

#: 200×200 薄层板的半对角(mm)。偏航差折算到**角点**位移用它 —— 板中心不动而转 θ,
#: 最远的角走 θ(rad)·141.4mm。判"放不放得进兜"看的是角点, 不是中心。
PLATE_HALF_DIAGONAL_MM = float(np.hypot(200.0, 200.0) / 2.0)


def transfer_matrix(grip: dict, seats: dict) -> dict:
    """从 A 取、到 B 放的错配 —— 回答"这块板放得进那个座吗"。

    代数(本节的全部依据, 写死在这免得下次再推一遍):
        `plate_local_pose` 的**位置项** `contact + axis·半板厚` **与 silicaUp 无关**
        ⇒ "板该在刀具上的哪个位置"是同一个常量 `expect`。
        板从 A 取走后, 它在翻转节点局部系里的位姿就是 `expect + δ_A`; 机械臂走到 B,
        座在同一个系里是 `expect + δ_B` ⇒ **错配 = δ_A − δ_B**(常量项相消)。

    两条好性质, 正是它比绝对残差有用的原因:
        · **与地轨零点、机器人基座注册的全局偏移无关** —— 全局平移对两站等量作用, 相减即消。
          于是它单独度量"站与站之间的**相对**摆位分歧", 不被那笔说不清的公共偏差污染;
        · 它就是"不做任何再对中时, 板落到 B 会偏多少"的物理量, 可以直接拿去比座的净空。

    ⚠ 跨翻转态(up↔down)同样成立: 局部系是**跟着翻转节点转**的, 板挂在它下面,
      翻转不改变板在这个系里的位姿。

    ⚠ 读法: 用户已确认**实机取放没问题**。所以这批错配度量的是**三维模型的摆位误差**,
      不是机器的问题 —— 反过来用(拿它去改示教点)是错的。
    """
    axis, span, third = grip_basis(grip)
    slots = [slot for slot in SEAT_LABEL if slot in seats]

    rows = []
    for a in slots:
        for b in slots:
            if a == b:
                continue
            vector = np.asarray(seats[a]["delta"], dtype=float) - np.asarray(
                seats[b]["delta"], dtype=float)
            in_plane = float(np.hypot(np.dot(vector, span), np.dot(vector, third)))
            along = float(np.dot(vector, axis))
            d_yaw = float((seats[a]["yawDeg"] - seats[b]["yawDeg"] + 45.0) % 90.0 - 45.0)
            worst = in_plane + abs(np.radians(d_yaw)) * PLATE_HALF_DIAGONAL_MM
            rows.append({"from": a, "to": b, "inPlaneMm": round(in_plane, 3),
                         "alongAxisMm": round(along, 3), "yawDeg": round(d_yaw, 3),
                         "worstCornerMm": round(worst, 3)})

    print()
    print("从 A 取、到 B 放的**面内**错配 (mm) —— 与地轨零点/基座注册的全局偏移无关")
    print("        " + "".join(f"{SEAT_LABEL[b][:4]:>7}" for b in slots))
    by_pair = {(row["from"], row["to"]): row for row in rows}
    for a in slots:
        line = "".join("      -" if a == b else f"{by_pair[(a, b)]['inPlaneMm']:7.1f}"
                       for b in slots)
        print(f"{SEAT_LABEL[a]:8}{line}")

    worst_along = max(rows, key=lambda row: abs(row["alongAxisMm"]))
    worst_yaw = max(rows, key=lambda row: abs(row["yawDeg"]))
    print(f"  沿吸盘轴(高度)最大 {worst_along['alongAxisMm']:+.2f}mm "
          f"({SEAT_LABEL[worst_along['from']]}->{SEAT_LABEL[worst_along['to']]}); "
          f"偏航差最大 {worst_yaw['yawDeg']:+.2f}° "
          f"({SEAT_LABEL[worst_yaw['from']]}->{SEAT_LABEL[worst_yaw['to']]})"
          " ⇒ 卡人的是面内平移")
    return {"pairs": rows, "halfDiagonalMm": round(PLATE_HALF_DIAGONAL_MM, 3)}


def pair_distances(seats: dict) -> list[dict]:
    """两落点**中心距**: CAD 说多少 vs 示教反推多少。

    为什么单独有它: 上面所有的量都活在"翻转节点局部系"里, 要跟人解释、要拿去现场核对,
    都得先讲清楚那个系。**标量距离没有这个问题** —— 它与姿态、与偏航、与全局注册
    全都无关, 是这批诊断里**唯一能拿卷尺直接证伪**的量:
        量出来 ≈ CAD  ⇒ 是示教点偏了;
        量出来 ≈ 示教 ⇒ 是 CAD 摆位错了。
    现场复核清单(docs/现场复核清单_工位间距_20260806.md)就是从这张表生成的。
    """
    slots = [slot for slot in SEAT_LABEL if slot in seats]
    rows = []
    for index, a in enumerate(slots):
        for b in slots[index + 1:]:
            cad = float(np.linalg.norm(
                np.asarray(seats[a]["anchorWorldMm"]) - np.asarray(seats[b]["anchorWorldMm"])))
            taught = float(np.linalg.norm(
                np.asarray(seats[a]["expectWorldMm"]) - np.asarray(seats[b]["expectWorldMm"])))
            rows.append({"a": a, "b": b, "cadMm": round(cad, 3),
                         "taughtMm": round(taught, 3), "diffMm": round(cad - taught, 3)})
    rows.sort(key=lambda row: -abs(row["diffMm"]))

    print()
    print("两落点中心距 CAD vs 示教反推 (mm) —— 标量, 与姿态/偏航/全局注册无关, 卷尺可直接验")
    print(f"{'A':10}{'B':10}{'CAD':>10}{'示教':>10}{'CAD−示教':>10}")
    for row in rows[:10]:
        print(f"{SEAT_LABEL[row['a']]:10}{SEAT_LABEL[row['b']]:10}"
              f"{row['cadMm']:10.2f}{row['taughtMm']:10.2f}{row['diffMm']:+10.2f}")
    spread = [abs(row["diffMm"]) for row in rows]
    print(f"  (共 {len(rows)} 对, 只打最大的 10 对) 全部 |CAD−示教| 中位 "
          f"{np.median(spread):.2f}mm / 最大 {max(spread):.2f}mm")
    return rows


def refit_rail_zero(manifest: dict, seats: dict) -> dict:
    """只解地轨零点这一个自由度, 并**同时给出该结论的证伪判据**。

    地轨沿世界 X 展开(rig_map `axis: [1,0,0]`), 所以零点误差**只**能落在 dX 上, 且对
    所有落点是**同一个常数**(与 railMm 无关); 标度误差才随 (railMm − 零点) 线性变化。

    ⚠ 证伪判据(比解本身更重要): 真是地轨零点错, **同一个 railMm 的那几个点应当整齐同向
      偏移**。若同槽位内的散布反而比槽位之间的差大一个量级, 那 dX 里的主项就不是地轨的账,
      解出来的那个数只是"别处的常量偏差被地轨这个自由度吸收掉了"。
      本模块顶部 INPLANE_IS_SOFT_AXIS 那条纪律同样适用: 别拿落点残差反向驱动标定。
    """
    spec = next((item for item in manifest.get("axes") or []
                 if item.get("id") == "axis_11y"), {})
    zero = float(spec.get("zeroOffsetMm", 500.0))
    sign = float(spec.get("sign", -1))

    rows = [(slot, float(item["railMm"]), float(item["worldDeltaMm"][0]))
            if "worldDeltaMm" in item else
            (slot, float(item["railMm"]), float(item["worldDelta"][0]))
            for slot, item in seats.items()]
    rail = np.array([row[1] for row in rows])
    dx = np.array([row[2] for row in rows])

    # 机器人沿 +X 平移 Δ ⇒ expect 加 Δ ⇒ dX 减 Δ。要 dX 归零取 Δ = 中位数。
    # 零点与位移的关系: offset = (mm − zero)·sign ⇒ 零点加 δ 使机器人平移 −sign·δ。
    shift = float(np.median(dx))
    new_zero = zero + shift / (-sign)
    slope, intercept = np.polyfit(rail - zero, dx, 1)

    print()
    print("地轨零点重解(只解这一个自由度):")
    print(f"  现行 zero_offset_mm = {zero:.2f} (sign={sign:+.0f}); 12 点 dX 中位 {shift:+.2f}mm"
          f" / 均值 {dx.mean():+.2f} / σ {dx.std():.2f}")
    print(f"  ⇒ 若照取板点重解: zero_offset_mm ≈ {new_zero:.2f}, 差 {abs(new_zero - zero):.2f}mm")
    print(f"  标度检验: dX 对 (railMm−{zero:.0f}) 线性斜率 {slope * 1000:+.3f}mm/m "
          f"(= {slope * 100:+.4f}% 标度), 截距 {intercept:+.2f}mm ⇒ 接近 0 即不是标度错")

    groups = {}
    for _slot, rail_mm, value in rows:
        groups.setdefault(round(rail_mm, 1), []).append(value)
    medians = {k: float(np.median(v)) for k, v in groups.items()}
    within = max(float(max(v) - min(v)) for v in groups.values())
    between = (max(medians.values()) - min(medians.values())) if len(medians) > 1 else 0.0
    verdict = ("同槽位内散布 > 组间差 ⇒ **dX 的主项不是地轨的账**, 这个解不可信"
               if within > between else "同槽位内整齐, 地轨假说站得住")
    for rail_mm in sorted(groups):
        print(f"    地轨 {rail_mm:7.1f}mm ({len(groups[rail_mm])}点) dX 中位 "
              f"{medians[rail_mm]:+7.2f}  同槽位内跨度 {max(groups[rail_mm]) - min(groups[rail_mm]):6.2f}")
    print(f"  证伪判据: 同槽位内最大跨度 {within:.2f}mm vs 组间中位数之差 {between:.2f}mm")
    print(f"    ⇒ {verdict}")
    return {
        "currentZeroMm": zero, "refitZeroMm": round(new_zero, 3),
        "shiftMm": round(new_zero - zero, 3),
        "scalePercent": round(float(slope) * 100.0, 5),
        "withinSlotSpreadMm": round(within, 3), "betweenSlotSpreadMm": round(between, 3),
        "trustworthy": bool(within <= between),
    }


def measure_cups(manifest: dict) -> dict:
    """M1: 逐顶点实测橡胶杯, 复核 contactLocalM 取的是不是真唇口。

    为什么不能只看 structure.json 的包围盒: 那是**吸盘总成**(杯 + KQ2E06 气路接头)的
    AABB, resolve_plate_grip 正是取它的远端当接触面。要判"取的对不对"就必须绕开它,
    直接量橡胶杯网格自己。

    ⚠ 用 work/machine.full.glb 而不是 models/*.glb —— 后者是 meshopt 压缩的, trimesh
      读不出顶点(两者节点层级与世界位姿逐位一致, 见 fit_station_alignment.Geometry)。
    """
    from fit_station_alignment import Geometry  # pylint: disable=import-outside-toplevel

    full = ROOT / "work" / "machine.full.glb"
    if not full.is_file():
        print(f"  [跳过] 找不到 {full} —— 先跑 03_clean_model.py --stage full")
        return {}

    grip = next(item for item in manifest["actuators"]
                if item["id"] == "rob_flip_suction")["plateGrip"]
    geometry = Geometry(full)
    scene = GlbScene(ROOT / "models" / "machine.official-cr5.glb")
    inverse = np.linalg.inv(scene.world_matrix(FLIP_NODE))
    axis = np.asarray(grip["axisLocal"], dtype=float)
    axis = axis / np.linalg.norm(axis)

    out = {}
    for rubber in grip.get("rubbers") or []:
        node = rubber["node"]
        leaf = node.split("/")[-1]
        try:
            points = geometry.vertices(leaf)
        except SystemExit:
            print(f"  [跳过] full.glb 里找不到网格节点 {leaf}")
            continue
        local = (inverse @ np.column_stack((points, np.ones(len(points)))).T).T[:, :3]
        along = local @ axis * 1000.0
        out[leaf] = {
            "沿轴跨度mm": [round(float(along.min()), 2), round(float(along.max()), 2)],
            "唇口(最大沿轴)mm": round(float(along.max()), 2),
            "顶点数": int(len(points)),
        }
        print(f"  {leaf[:52]:52} 沿吸盘轴 {along.min():+8.2f} .. {along.max():+8.2f}mm"
              f"  ({len(points)} 顶点)")
    contact_along = float(np.dot(np.asarray(grip["contactLocalM"], dtype=float), axis)) * 1000.0
    print(f"  contactLocalM 沿吸盘轴 = {contact_along:+.2f}mm  <- manifest 实际下发的接触面")
    for leaf, item in out.items():
        gap = item["唇口(最大沿轴)mm"] - contact_along
        verdict = "一致" if abs(gap) < 0.5 else f"**差 {gap:+.2f}mm**"
        print(f"    vs {leaf[:40]:40} 唇口: {verdict}")
    out["contactAlongAxisMm"] = round(contact_along, 3)
    return out


def tank_towers(scene, posture, manifest, registry, rail_slots, axes_mm, seats) -> dict:
    """M4: 展缸两塔的横向劈裂归属 —— 比 CAD 锚点与示教点各自的**塔内节距 / 塔间关系**。

    只出归属结论, 不动几何: 拿落点残差反向驱动工位平移是 2026-08-05 已记录的坑
    (见 docs/工位摆位偏差溯源_20260805)。
    """
    calibration = load_calibration()
    anchors = clip_compiler.resolve_plate_anchors(scene)
    by_name = {point.robot_name: point for point in registry.points}

    taught, cad = {}, {}
    for tank in range(1, 9):
        point, anchor = by_name.get(f"P{10 + tank}"), anchors.get(f"tank:{tank}")
        if point is None or anchor is None or not point.joint:
            continue
        try:
            joints = list(solve_ik(pose_matrix(point.pose), list(point.joint),
                                   calibration, tool=point.tool))
        except Exception:  # pylint: disable=broad-except
            continue
        kwargs = dict(joints_deg=joints, rail_mm=rail_slots[5], axes_mm=axes_mm)
        taught[tank] = posture.mount_world(**kwargs)[:3, 3] * 1000.0
        cad[tank] = posture.node_world(anchor, **kwargs)[:3, 3] * 1000.0

    print()
    print("展缸两塔(缸 1-4 = 塔A, 缸 5-8 = 塔B): 塔内节距对照(mm)")
    out: dict = {"towers": {}}
    for tower, tanks in (("A", (1, 2, 3, 4)), ("B", (5, 6, 7, 8))):
        rows = []
        for a, b in zip(tanks, tanks[1:]):
            if a in cad and b in cad:
                rows.append({
                    "相邻缸": f"{a}->{b}",
                    "CAD节距": float(np.linalg.norm(cad[b] - cad[a])),
                    "示教节距": float(np.linalg.norm(taught[b] - taught[a])),
                })
        for row in rows:
            print(f"  塔{tower} {row['相邻缸']:8} CAD {row['CAD节距']:8.2f}   "
                  f"示教 {row['示教节距']:8.2f}   差 {row['CAD节距'] - row['示教节距']:+7.2f}")
        out["towers"][tower] = [
            {k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}
            for row in rows
        ]

    # 塔位归属只能在**世界系**里判, 且必须拿"板该在的位置 vs plateGrip 说的位置"这个
    # 世界残差 —— 不能拿法兰世界位置相减。两塔的机械臂偏航差着约 180°(pose[5] 一个
    # +158°、一个 −22°), 同一个刀具偏置在世界系下指向相反, 直接减法兰会凭空造出几百
    # 毫米的假差(首版就读出 −450.86mm 这种数, 全是这个成因)。
    print()
    print("展缸两塔的世界系残差(板该在的位置 − plateGrip 说的位置, mm):")
    towers: dict[str, list] = {}
    for tower, tanks in (("A", (1, 2, 3, 4)), ("B", (5, 6, 7, 8))):
        rows = [seats[f"tank:{n}"]["worldDelta"] for n in tanks if f"tank:{n}" in seats]
        if not rows:
            continue
        stack = np.stack(rows)
        median = np.median(stack, axis=0)
        spread = float(max(np.linalg.norm(row - median) for row in stack))
        towers[tower] = [round(float(v), 3) for v in median]
        print(f"  塔{tower} 中位数 ({median[0]:+8.2f}, {median[1]:+8.2f}, {median[2]:+8.2f})"
              f"   塔内散布 {spread:5.2f}mm")
        out.setdefault("towerWorldMedianMm", {})[tower] = towers[tower]
        out.setdefault("towerWorldSpreadMm", {})[tower] = round(spread, 3)
    if len(towers) == 2:
        gap = np.asarray(towers["B"]) - np.asarray(towers["A"])
        print(f"  塔B − 塔A = ({gap[0]:+8.2f}, {gap[1]:+8.2f}, {gap[2]:+8.2f})mm"
              f"  |{float(np.linalg.norm(gap)):.2f}|mm")
        print("    两塔各自塔内散布都小、而塔间差一个常向量 => 塔位(CAD 摆位)差, 不是示教散")
        out["towerGapWorldMm"] = [round(float(v), 3) for v in gap]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="持板常量判别(只读, 不改任何生产文件)")
    parser.add_argument("--cups", action="store_true",
                        help="加做逐顶点橡胶杯实测(要 work/machine.full.glb, 慢)")
    parser.add_argument("--source", default="pose", choices=("pose", "joint"),
                        help="用哪套姿态: pose(动画口径, 默认) 或 joint(旧基准, 对照用)")
    args = parser.parse_args()

    control_root = _control_root(None)
    registry = _load_registry(control_root)
    manifest = json.loads(
        (ROOT / "models" / "device-manifest.official-cr5.json").read_text(encoding="utf-8"))
    scene = GlbScene(ROOT / "models" / "machine.official-cr5.glb")
    posture = RobotPosture(scene, manifest)
    rail_slots = clip_compiler.load_rail_slots(control_root)
    axes_mm = V.seat_axes_mm(control_root)
    grip = next(item for item in manifest["actuators"]
                if item["id"] == "rob_flip_suction")["plateGrip"]

    print(f"姿态口径: {args.source}"
          f"{' (动画走的就是它)' if args.source == 'pose' else ' (旧基准, 仅对照)'}")
    print(f"工位轴已摆到位: {', '.join(f'{k}={v:.1f}' for k, v in sorted(axes_mm.items()))}")

    seats = seat_errors(scene, posture, manifest, registry, rail_slots, axes_mm, args.source)
    if not seats:
        print("[!] 一个落点都没算出来 —— 点表/锚点/工位轴至少缺一样")
        return 1
    summary = report_axes(grip, seats)

    split = decompose(summary)
    if split:
        print()
        print("归因分解(在吸盘局部系里, 两翻转态同号等值的部分才是刀具项):")
        for item in split.values():
            print(f"  {item['轴']:10} 刀具项 {item['刀具项mm']:+8.2f}mm   "
                  f"非刀具项(停靠/工位/锚点) {item['非刀具项mm']:+8.2f}mm")

    stations = attribute_stations(seats)
    transfers = transfer_matrix(grip, seats)
    distances = pair_distances(seats)
    rail_zero = refit_rail_zero(manifest, seats)

    cups = {}
    if args.cups:
        print()
        print("M1 逐顶点橡胶杯实测(复核 contactLocalM 取的是不是真唇口):")
        cups = measure_cups(manifest)

    towers = tank_towers(scene, posture, manifest, registry, rail_slots, axes_mm, seats)

    out_path = ROOT / "work" / "plate_grip_diagnosis.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "source": args.source,
        "seatAxesMm": {k: round(v, 3) for k, v in sorted(axes_mm.items())},
        "seats": {slot: {"point": item["point"], "flip": item["flip"],
                         "deltaLocalMm": [round(float(v), 3) for v in item["delta"]],
                         # 世界系那份是**归属判别**的唯一可用口径(局部系随偏航转, 跨站不可比),
                         # 首版只写了局部系, 于是每次追根都要重跑一遍脚本才拿得到。
                         "worldDeltaMm": [round(float(v), 3) for v in item["worldDelta"]],
                         "railMm": round(item["railMm"], 3),
                         "normalDeg": round(item["normalDeg"], 3),
                         "yawDeg": round(item["yawDeg"], 3)}
                  for slot, item in seats.items()},
        "summary": summary,
        "decomposition": split,
        "stationAttribution": stations,
        "transfer": transfers,
        "pairDistances": distances,
        "railZero": rail_zero,
        "cups": cups,
        "tankTowers": towers,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"[ok] 判别产物已写 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
