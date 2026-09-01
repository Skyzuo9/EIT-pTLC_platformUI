"""解算并校验"工位摆位 ↔ 机器人示教点"的对齐。

# 为什么需要它

托盘转移动画里, 机械臂按实机示教点走到取料位, 而托盘按 CAD 摆位待着。两者不一致时,
托盘就不会落进夹爪的凹槽。示教点是真机的位置真源(机器人链本身已由 `scene_kinematics`
对已标定的快换变换自校到 0.0001 mm), 所以要动的是货架/中转的 CAD 摆位。

本脚本两个用法:

    python fit_station_alignment.py --fit     # 解出平移量(整站水平 + 逐层竖直), 回填 rig_map
    python fit_station_alignment.py --check   # 门禁: 逐位姿判定板沿是不是真的卡进凹槽

# 抓取基准 = 凹槽, 不是钳口板包围盒

夹具板不是实心板: 内面远端 50 mm 有一道 **内凹 1.02 / 槽高 10.11 mm** 的凹槽, 上下各有
齐平唇口。闭合态(每指内移 `holdValue × 5.2` = 1.498 mm)的尺寸链是:

    齐平内隙 85.46  vs 孔板宽 87.23  ->  唇口过盈 0.88 mm/侧(勾住板沿, 锁竖直)
    凹槽内隙 87.50  vs 孔板宽 87.23  ->  间隙 0.13 mm/侧(精密滑配)

也就是说这是**榫槽卡合**而不是摩擦夹持, 抓取基准的高度必须取**槽心**。

2026-08-03 之前这里取的是两块夹具板**包围盒中心**(mount 系 Z=−135.05), 而槽心在
−142.13 —— 系统性差 7.09 mm, 表现为托盘整体悬在槽口上方压着上唇。三个独立工位实测
需下降 7.04 / 7.10 / 7.06 mm, 与 7.09 吻合到 0.05 mm。

这是本项目第三次栽在"基准取法错 → 数字对但结论错": 前两次是拿 `INV_*` 空节点的任意
原点当几何中心(量出 840 mm 伪误差), 和把 TOOL_MOUNT 系的 X 当成钳口闭合轴。所以凹槽
一律从几何**自动判出**(见 `_jaw_slot`), 不写死位置。

# 门禁为什么用"包含判定"而不是"距离阈值"

距离数字在基准取错时照样全绿 —— 上一版门禁判的是"孔板落在钳口包围盒内", 48/48 通过
却整体错了 7 mm。现在改判**闭合态下板沿是否落在凹槽的高度带与内隙内**, 并附一条与
摆位无关的设计校核(见 `report_check`), CAD 一改就报。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

import numpy as np
import trimesh
import yaml
from scipy.spatial.transform import Rotation

from scene_kinematics import GlbScene, RobotPosture


ROOT = Path(__file__).resolve().parents[1]

#: 真正接触托盘的两块夹具板(各 10×29×135 mm, 内隙 88.49 mm —— 与 rig_map 记录吻合)。
#: 用它们而不是 ACTUATOR_GRIP_* 空节点: 后者原点是任意的(实测间距 59.3 mm, 与任何真实
#: 尺寸都对不上), 拿它当基准会得到偏差 100 mm 量级的伪结论。
JAW_NODES = ("PTLC-07-021 96孔板夹具1-1", "PTLC-07-020 96孔板夹具-1")

#: 托盘上被夹的那块孔板(按耗材种类不同零件号不同)。
PLATE_TOKEN = {"collector": "PTLC-01-009", "bottle": "PTLC-01-007"}

#: 载荷节点 -> 它所属的、需要整体平移的 CAD 工位装配根。
STATION_OF_PAYLOAD = {
    "INV_STAGING_A": ("STAGING_A", "收集瓶支架总装-1"),
    "INV_STAGING_B": ("STAGING_B", "样品瓶支架总装-1"),
}
RACK_STATION = ("RACK", "上料架-1")

#: 竖直向的"搁板层"分组。
#:
#: 为什么竖直不放在整站平移里: 三个工位的安装底板底面在 CAD 里**全部 Y=10.00**, 正好坐在
#: `PTLC-08-009 大面板`(顶面 10.00)上, 间隙 0.00 —— 它们是拧在台面上的, 不可能整体升高。
#: 而托盘/搁板的叠层公差完全可能差几毫米。所以整站只吃水平, 竖直交给这一层。
#:
#: 中转必须带上 `样品架支撑轴`: 层级是 安装板(10~20) -> 支撑轴(18~158) -> 台面(156~166)
#: -> 托盘, 只抬台面会让它浮在轴顶上。(托盘自己的 `瓶子料架支撑柱` 已在 INV_STAGING_* 组里。)
#: 货架每层的 `样品放置板` 实例按**实测高度**归的层, 不是按名字尾号猜的 —— 尾号与层号
#: 完全不对应(第1层是 .002/.003/.001, 第4层是 .011/.009/无后缀)。它夹在搁板与托盘之间,
#: 且被 inventory.rackExclude 排除在 INV_* 之外(它是货架的搁板件, 不随托盘搬走), 所以必须
#: 在这里显式跟着层一起动, 否则搁板抬起来它会留在原地, 托盘与搁板之间开一条 4~5 mm 的缝。
SHELF_GROUPS = [
    {"label": "货架第1层(搁板顶 Y560)",
     "shelf": ["PTLC-01-004 料盘放置板-1", "PTLC-01-005 样品放置板-1.001",
               "PTLC-01-005 样品放置板-1.002", "PTLC-01-005 样品放置板-1.003"],
     "payloads": ["INV_RACK_COLLECTOR_1", "INV_RACK_COLLECTOR_2", "INV_RACK_COLLECTOR_3"]},
    {"label": "货架第2层(搁板顶 Y400)",
     "shelf": ["PTLC-01-004 料盘放置板-2", "PTLC-01-005 样品放置板-1.005",
               "PTLC-01-005 样品放置板-1.007", "PTLC-01-005 样品放置板-1.010"],
     "payloads": ["INV_RACK_COLLECTOR_4", "INV_RACK_COLLECTOR_5", "INV_RACK_COLLECTOR_6"]},
    {"label": "货架第3层(搁板顶 Y240)",
     "shelf": ["PTLC-01-004 料盘放置板-3", "PTLC-01-005 样品放置板-1.004",
               "PTLC-01-005 样品放置板-1.006", "PTLC-01-005 样品放置板-1.008"],
     "payloads": ["INV_RACK_BOTTLE_1", "INV_RACK_BOTTLE_2", "INV_RACK_BOTTLE_3"]},
    {"label": "货架第4层(搁板顶 Y80)",
     "shelf": ["PTLC-01-004 料盘放置板-4", "PTLC-01-005 样品放置板-1",
               "PTLC-01-005 样品放置板-1.009", "PTLC-01-005 样品放置板-1.011"],
     "payloads": ["INV_RACK_BOTTLE_4", "INV_RACK_BOTTLE_5", "INV_RACK_BOTTLE_6"]},
    {"label": "中转A台面", "payloads": ["INV_STAGING_A"],
     "shelf": ["PTLC-07-030 孔板缓存工位-1", "样品架支撑轴-1", "样品架支撑轴-2",
               "样品架支撑轴-3", "样品架支撑轴-4"]},
    {"label": "中转B台面", "payloads": ["INV_STAGING_B"],
     "shelf": ["PTLC-07-030 孔板缓存工位-1.001", "样品架支撑轴-1.001", "样品架支撑轴-2.001",
               "样品架支撑轴-3.001", "样品架支撑轴-4.001"]},
]

#: 【纯观测】夹持偏心 —— **不是判据**(2026-08-05 订正)。
#:
#: 夹爪沿托盘长边咬在哪, 几何上不受任何约束: 榫槽只在闭合轴与高度轴上卡住托盘, 长度方向
#: 是自由的, 咬在哪由示教时人手停在哪决定。用户明确说过从没要求夹在中间。
#:
#: 曾经拿 20 mm 当阈值, 后果是它**反向驱动**了工位摆位: 为了让偏心达标, 三个工位被各挪了
#: 23~41 mm(其中 19~28 mm 纯粹是长度轴的账)。现场复核: 真机夹爪只咬住托盘靠机械臂那一半,
#: 最前端离托盘中心还差约 2 cm —— 而当时模型把它画到越过中心 25.4 mm, 方向都反了。
#: 也就是说这条阈值从来没被真正满足过, 只是被工位平移"做"到满足的。
#: 现改为如实报出数值, 不参与判定。
MAX_SLOT_UNCOVERED_MM_NOTE = "槽必须真的压在孔板边沿上, 这条才是硬的物理有效性"
#: 槽的 50.7 mm 必须全部压在孔板边沿上, 留 2 mm 容差给端部倒角。
MAX_SLOT_UNCOVERED_MM = 2.0

MAX_SLOT_RESIDUAL_MM = 8.0

#: 同一个载荷在不同片段里解出的夹持位姿, 允许的样本散布(mm)。
#: 夹持关系是纯刀具几何, 同一块托盘无论从哪个工位被夹起来都该一样; 散布大说明示教点或
#: 工位摆位有一处不自洽。取 6.0 是因为长度轴本就有 ~4mm 的示教偏心散布(见
#: MAX_GRIP_OFFCENTER_MM 的注释), 留一点余量给三角化误差。
MAX_GRIP_SPREAD_MM = 6.0

#: 内面剖面的判带阈值(mm)。回退 < FLUSH 记作齐平唇口, > RELIEF 记作让位槽; 中间那一档
#: 是两者之间的倒角, 两边都不算。实测: 唇口 0.00, 倒角 0.3~1.0, 让位槽 3.00。
#: ⚠ 这两个数曾把倒角误判成槽 —— 早先取 [0.5,2.5) 抓到的是 1.02 mm 的倒角面, 于是把
#: "让位槽"当成了榫槽, 结论整个反了。判带一律走剖面聚类, 不靠单一区间去捞顶点。
FLUSH_RECESS_MM = 0.30
RELIEF_RECESS_MM = 1.50

#: 剖面只取夹具板远端(让位槽只存在于远端 87~137 mm)。0.6 = 过了钳口板中点的保守取法。
PROFILE_FAR_END_FRACTION = 0.70
PROFILE_STEP_MM = 0.25

#: 【硬判】允许的负余量(mm)。槽高 9.62 / 孔板厚 8.00, 名义两侧各 0.81 mm; 但托盘与钳口
#: 之间还有约 0.5° 的姿态差, 把孔板在 mount 系的跨度撑到 9.06, 两侧只剩 ~0.28 mm。所以
#: 留 0.15 mm 吸收姿态差与三角化误差 —— 比最早那条 1.0 mm 紧一个量级, 且理由是实测的。
CLEARANCE_TOLERANCE_MM = 0.15


def station_of(payload_id: str) -> tuple[str, str]:
    if payload_id.startswith("INV_RACK_"):
        return RACK_STATION
    if payload_id in STATION_OF_PAYLOAD:
        return STATION_OF_PAYLOAD[payload_id]
    raise SystemExit(f"未知载荷所属工位: {payload_id}")


def kind_of(payload_id: str) -> str:
    return "bottle" if "BOTTLE" in payload_id or payload_id == "INV_STAGING_B" else "collector"


class Geometry:
    """逐顶点几何取用(带缓存)。用 04 压缩之前的 work/machine.full.glb —— models/*.glb
    是 meshopt 压缩的, trimesh 读不出顶点; 两者节点层级与世界位姿逐位一致(已实测 0.00 mm)。
    """

    def __init__(self, model: Path) -> None:
        self.scene = trimesh.load(model, force="scene")
        self.children: dict[str, list[str]] = {}
        for parent, child, *_rest in self.scene.graph.to_edgelist():
            self.children.setdefault(str(parent), []).append(str(child))
        self._cache: dict[str, np.ndarray] = {}

    def vertices(self, node: str) -> np.ndarray:
        if node in self._cache:
            return self._cache[node]
        chunks, stack = [], [node]
        while stack:
            current = stack.pop()
            stack.extend(self.children.get(current, ()))
            transform, geometry = self.scene.graph.get(current)
            if geometry is None:
                continue
            points = self.scene.geometry[geometry].vertices
            homogeneous = np.column_stack((points, np.ones(len(points))))
            chunks.append((transform @ homogeneous.T).T[:, :3])
        if not chunks:
            raise SystemExit(f"节点没有网格: {node}")
        self._cache[node] = np.vstack(chunks)
        return self._cache[node]

    def mesh(self, node: str) -> trimesh.Trimesh:
        """节点(含子树)合并后的三角网格, 世界系。判夹具板内面剖面要用面, 不能只用顶点。"""
        parts, stack = [], [node]
        while stack:
            current = stack.pop()
            stack.extend(self.children.get(current, ()))
            transform, geometry = self.scene.graph.get(current)
            if geometry is None:
                continue
            piece = self.scene.geometry[geometry].copy()
            piece.apply_transform(transform)
            parts.append(piece)
        if not parts:
            raise SystemExit(f"节点没有网格: {node}")
        return trimesh.util.concatenate(parts)

    def child_matching(self, parent: str, token: str) -> str:
        hits = [name for name in self.children.get(parent, []) if token in name]
        if len(hits) != 1:
            raise SystemExit(f"{parent} 下匹配 {token} 的子件应恰为 1 个, 实际 {len(hits)}")
        return hits[0]


def transform_points(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    return (matrix @ np.column_stack((points, np.ones(len(points)))).T).T[:, :3]


def teach_poses(clip: dict, catalog: dict) -> dict[str, tuple[list[float], float, str]]:
    """按片段自带的编译产物复算 attach/detach 时刻的关节与地轨。

    片段里 move_j 的关节来自点表, move_l 来自 `compiled.moveLTrajectories[步号]` 的末帧 ——
    与前端 compileClip 消费的是同一份数据, 因此这里算出的姿态与播放器逐位一致。
    """
    joints = list(clip["home"]["joints_deg"])
    rail = float(clip["home"]["axis_mm"]["axis_11y"])
    result: dict[str, tuple[list[float], float, str]] = {}
    for index, step in enumerate(clip["steps"]):
        kind = next(iter(step["do"]))
        body = step["do"][kind]
        if kind == "axis":
            rail = float(body["to_mm"])
        elif kind == "robot_point":
            if body["motion"] == "move_j":
                joints = list(catalog[body["id"]]["joint"])
            else:
                joints = list(clip["compiled"]["moveLTrajectories"][str(index)][-1])
        elif kind in ("attach", "detach"):
            result[kind] = (list(joints), rail, str(body["id"]))
    return result


def grip_close_mm(rig_map: dict) -> float:
    """从 rig_map 读 96 孔板夹爪夹持态每指的内移量(mm)。

    不写死 1.498: 它是 `holdValue × outputRange[1]` 的乘积, rig_map 里任一项改了这里
    必须跟着变, 否则门禁会拿张开态的内隙去判闭合态的配合 —— 而张开态唇口内隙比孔板宽
    3 mm, 那样算什么都"过得去"。
    """
    entry = next(x for x in rig_map["linkages"] if x["id"] == "rob_grip_plate96")
    travels = {float(m["outputRange"][1]) for m in entry["members"]}
    if len(travels) != 1:
        raise SystemExit(f"rob_grip_plate96 两指行程不一致: {travels}")
    return float(entry["holdValue"]) * travels.pop()


class Aligner:
    def __init__(self, model: Path, manifest_path: Path, catalog_path: Path,
                 rig_map_path: Path) -> None:
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.glb_path = Path(model)
        self.glb = GlbScene(model)
        self.posture = RobotPosture(self.glb, self.manifest)
        self.geometry = Geometry(model)
        self.catalog = json.loads(catalog_path.read_text(encoding="utf-8"))["points"]
        self.rig_map = yaml.safe_load(rig_map_path.read_text(encoding="utf-8"))
        self.close_m = grip_close_mm(self.rig_map) / 1000.0

        tool = next(t for t in self.manifest["tools"] if t["id"] == "TOOL_PLATE96")
        mounted = np.eye(4)
        mounted[:3, :3] = Rotation.from_quat(tool["mountQuaternion"]).as_matrix()
        mounted[:3, 3] = tool["mountPosition"]
        # 加载态(工具停在刀库) -> 挂载态(工具在法兰上)
        self.to_mounted = mounted @ np.linalg.inv(self.glb.world_matrix(tool["glbNode"]))
        self.jaws = [
            transform_points(self.to_mounted, self.geometry.vertices(name)) for name in JAW_NODES
        ]
        self._jaw_meshes = []
        for name in JAW_NODES:
            mesh = self.geometry.mesh(name).copy()
            mesh.apply_transform(self.to_mounted)
            self._jaw_meshes.append(mesh)
        self._axes = self._jaw_axes()
        self.bands = [self._bands(index) for index in range(2)]
        self.grasp_center_mounted = self._grasp_reference()

    def _jaw_axes(self) -> tuple[int, int, int]:
        """判出钳口闭合轴 / 夹具板长度轴 / 高度轴(全在 TOOL_MOUNT 局部系, 且近似轴对齐)。

        闭合轴 = 左右两块板中心相距最远的那根轴; 剩下两根里跨度大的是长度轴。
        这样就不必写死"X 是闭合轴"这种会翻车的假设。
        """
        centers = [(jaw.min(0) + jaw.max(0)) / 2 for jaw in self.jaws]
        separation = np.abs(centers[0] - centers[1])
        closing = int(np.argmax(separation))
        rest = [axis for axis in range(3) if axis != closing]
        merged = np.vstack(self.jaws)
        extent = merged.max(0) - merged.min(0)
        length = rest[0] if extent[rest[0]] >= extent[rest[1]] else rest[1]
        height = rest[1] if length == rest[0] else rest[0]
        return closing, length, height

    def _inner_sign(self, index: int) -> int:
        """+1 表示这块板的内面是它在闭合轴上的 min, −1 表示是 max。"""
        closing = self._axes[0]
        other = self.jaws[1 - index][:, closing].mean()
        return 1 if self.jaws[index][:, closing].mean() > other else -1

    def _inner_profile(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        """夹具板远端内面沿高度的"回退量"剖面(逐三角面投影, 步长 PROFILE_STEP_MM)。

        为什么必须走面而不是顶点: 平面只在角上有顶点, 单看顶点会把倒角的角点当成整条槽面
        (这正是本轮 1.02 vs 3.00 mm 的翻车点)。
        """
        closing, length, height = self._axes
        sign = self._inner_sign(index)
        tri = self._jaw_meshes[index].triangles
        a, b, c = (tri[:, i][:, [length, height]] for i in range(3))
        e0, e1 = b - a, c - a
        det = e0[:, 0] * e1[:, 1] - e1[:, 0] * e0[:, 1]

        jaw = self.jaws[index]
        far = jaw[:, length].min() + PROFILE_FAR_END_FRACTION * np.ptp(jaw[:, length])
        lengths = np.linspace(far, jaw[:, length].max() - 1e-3, 24)
        heights = np.arange(jaw[:, height].min() + 1e-4, jaw[:, height].max(),
                            PROFILE_STEP_MM / 1000.0)
        grid_l, grid_h = np.meshgrid(lengths, heights)
        points = np.stack([grid_l.ravel(), grid_h.ravel()], 1)

        inner = np.full(len(points), np.nan)
        for t in np.nonzero(np.abs(det) > 1e-14)[0]:
            rel = points - a[t]
            u = (rel[:, 0] * e1[t, 1] - e1[t, 0] * rel[:, 1]) / det[t]
            v = (e0[t, 0] * rel[:, 1] - rel[:, 0] * e0[t, 1]) / det[t]
            hit = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
            if not hit.any():
                continue
            value = (tri[t, 0, closing]
                     + u[hit] * (tri[t, 1, closing] - tri[t, 0, closing])
                     + v[hit] * (tri[t, 2, closing] - tri[t, 0, closing])) * sign
            where = np.nonzero(hit)[0]
            inner[where] = np.where(np.isnan(inner[where]), value,
                                    np.minimum(inner[where], value))
        inner = inner.reshape(len(heights), len(lengths))

        # 只保留"整条远端都有料"的高度行, 免得端部缺料的行拉低均值(也免得对空行求均值)
        solid = np.count_nonzero(~np.isnan(inner), axis=1) >= 0.8 * len(lengths)
        if not solid.any():
            raise SystemExit(f"{JAW_NODES[index]} 远端没有连续的内面, 无法取剖面")
        recess = np.nanmean(inner[solid], axis=1)
        return heights[solid], (recess - recess.min()) * 1000

    def _bands(self, index: int) -> dict:
        """把剖面切成 齐平唇口带 / 凹槽带 —— 这副夹爪是**榫槽卡合**, 不是摩擦夹持。

        尺寸链(闭合态, 每指内移 holdValue×5.2 = 1.498 mm):

            齐平唇口内隙 85.46  <  孔板宽 85.50   -> 上下唇口勾住板沿, 板出不来
            凹槽内隙     91.52  >  孔板宽 85.50   -> 槽内每侧 3 mm 是插入余量
            槽高          9.62  >  孔板厚  8.00   -> 竖直余量 ±0.81 mm

        所以孔板边沿是"榫", 槽是"卯"。判据一律对着**槽**算, 不是对着唇口算。
        """
        closing, length, height = self._axes
        heights, recess = self._inner_profile(index)
        sign = self._inner_sign(index)
        jaw = self.jaws[index]
        face = jaw[:, closing].min() if sign > 0 else jaw[:, closing].max()

        def runs(mask):
            out, start = [], None
            for i, flag in enumerate(mask):
                if flag and start is None:
                    start = i
                elif not flag and start is not None:
                    out.append((heights[start], heights[i - 1])); start = None
            if start is not None:
                out.append((heights[start], heights[-1]))
            return out

        flush = runs(recess < FLUSH_RECESS_MM)
        slot = runs(recess > RELIEF_RECESS_MM)
        if not flush or not slot:
            raise SystemExit(
                f"{JAW_NODES[index]} 内面剖面没切出齐平带/凹槽(齐平 {len(flush)} 段, "
                f"凹槽 {len(slot)} 段) —— 夹具板 CAD 换版了? 先核对 FLUSH/RELIEF_RECESS_MM")
        groove = max(slot, key=lambda band: band[1] - band[0])
        depth = float(np.nanmax(recess)) / 1000.0

        # 槽在**长度**方向的范围: 槽只存在于夹具板远端(实测 50.7 mm), 它的中心才是
        # "夹在托盘中段"的基准 —— 用钳口板中心会差 42 mm(见文件头注释)。
        #
        # 按"回退量 ≈ 槽深"选槽底面, **不要**按高度带筛: 平面只在边界上有顶点, 而槽底面的
        # 顶点恰好落在剖面带的边界之外(实测 Z −147.25 vs 带下沿 −147.02), 用高度筛会把它们
        # 全滤掉、只剩零星几个, 算出 0.16 mm 的假槽长。
        back = (jaw[:, closing] - face) * sign * 1000
        in_slot = jaw[np.abs(back - depth * 1000) < 0.6]
        if len(in_slot) < 4:
            raise SystemExit(
                f"{JAW_NODES[index]} 取不到槽底顶点(回退量 ≈{depth*1000:.2f} mm 的只有 {len(in_slot)} 个)")
        return {
            "sign": sign,
            "lip_face": float(face),
            "slot_face": float(face + sign * depth),
            "slot_lo": float(groove[0]), "slot_hi": float(groove[1]),
            "slot_len_lo": float(in_slot[:, length].min()),
            "slot_len_hi": float(in_slot[:, length].max()),
        }

    def _grasp_reference(self) -> np.ndarray:
        """标称抓取基准(mount 局部系) —— 孔板中心应该落在这里。

            高度 = 槽心          (硬约束: 槽高 9.62 vs 板厚 8.00, 余量只有 ±0.81 mm)
            闭合 = 两侧唇面中点  (硬约束: 唇口内隙 85.46 vs 板宽 85.50)
            长度 = 槽的长度中心    (**无约束**: 咬在托盘长边哪个位置由示教点决定)

        长度分量此前取的是钳口板包围盒中心(69.52), 而槽只存在于远端 50.7 mm、中心在
        111.67 —— 差 42.15 mm。改过来之后三个工位需要的水平量直接砍半。

        ⚠ 长度分量只是**报告偏心时的参考点**, 不参与整站平移解算(见 `report_fit`)。
          拿它去拟合等于假定夹爪必须咬在托盘中心, 而真机并不是那样咬的。
        """
        closing, length, height = self._axes
        ref = np.zeros(3)
        ref[closing] = float(np.mean([b["lip_face"] for b in self.bands]))
        ref[height] = float(np.mean([(b["slot_lo"] + b["slot_hi"]) / 2 for b in self.bands]))
        ref[length] = float(np.mean(
            [(b["slot_len_lo"] + b["slot_len_hi"]) / 2 for b in self.bands]))
        return ref

    def plate_vertices(self, payload_id: str) -> np.ndarray:
        token = PLATE_TOKEN[kind_of(payload_id)]
        return self.geometry.vertices(self.geometry.child_matching(payload_id, token))

    def plate_size_mm(self, payload_id: str) -> tuple[float, float]:
        """孔板的**本征**宽度与厚度(mm)。

        必须取本征值而不是它在 mount 系的跨度: 托盘与钳口之间有约 0.5~0.8° 的姿态差,
        会把 85.5 的板在 mount 系撑到 87.2 —— 拿撑过的值去比内隙会得出"槽是精密滑配"
        这种反了的结论。托盘在世界系是轴对齐的(主轴与世界轴夹角 < 0.05°), 故世界包围盒即本征值。
        """
        extent = np.sort(np.ptp(self.plate_vertices(payload_id), axis=0)) * 1000
        return float(extent[1]), float(extent[0])

    def design_check(self) -> dict:
        """与工位摆位无关的尺寸链校核: 证明"孔板边沿插进凹槽、被上下唇口勾住"确实是
        这副夹爪的设计接口。CAD 一换版、或 rig_map 的 holdValue 一改, 必有一条报出来。
        """
        width, thickness = self.plate_size_mm("INV_STAGING_A")
        close_mm = self.close_m * 1000
        lips = [b["lip_face"] for b in self.bands]
        slots = [b["slot_face"] for b in self.bands]
        assert {b["sign"] for b in self.bands} == {1, -1}, "两块夹具板的内面朝向应相反"
        return {
            "plate_width_mm": width,
            "plate_thickness_mm": thickness,
            "lip_gap_closed_mm": abs(lips[0] - lips[1]) * 1000 - 2 * close_mm,
            "slot_gap_closed_mm": abs(slots[0] - slots[1]) * 1000 - 2 * close_mm,
            "slot_height_mm": float(np.mean(
                [b["slot_hi"] - b["slot_lo"] for b in self.bands])) * 1000,
            "slot_length_mm": float(np.mean(
                [b["slot_len_hi"] - b["slot_len_lo"] for b in self.bands])) * 1000,
        }

    def evaluate(self, joints, rail, payload_id: str) -> dict:
        """在某个示教位姿上, 量**闭合态**的夹具板与孔板的相对关系。

        闭合态才是判据: 张开态(GLB 基准)唇口内隙比孔板宽 3 mm, 拿它算什么都"过得去"。
        """
        closing, length, height = self._axes
        mount = self.posture.mount_world(joints_deg=joints, rail_mm=rail)
        plate_world = self.plate_vertices(payload_id)
        plate = transform_points(np.linalg.inv(mount), plate_world)

        slot_lo = max(b["slot_lo"] for b in self.bands)
        slot_hi = min(b["slot_hi"] for b in self.bands)
        # 闭合态: 每块板朝对面移动 close_m
        lips = sorted(b["lip_face"] - b["sign"] * self.close_m for b in self.bands)
        walls = sorted(b["slot_face"] - b["sign"] * self.close_m for b in self.bands)
        slot_len_lo = max(b["slot_len_lo"] for b in self.bands)
        slot_len_hi = min(b["slot_len_hi"] for b in self.bands)
        plate_center_len = (plate[:, length].min() + plate[:, length].max()) / 2
        # 竖直判据用**板心对槽心**, 预算按真板厚算, 不按 mount 系的跨度算:
        # 托盘与钳口之间有约 0.5° 姿态差, 把 8.00 mm 的板在 mount 系撑到 9.06 —— 拿撑过的
        # 跨度去比槽高, 等于要求把姿态差也对齐掉, 而纯平移做不到。姿态差单独当观测量报出去。
        _width, thickness = self.plate_size_mm(payload_id)
        need_world = (transform_points(mount, self.grasp_center_mounted[None, :])[0]
                      - (plate_world.min(0) + plate_world.max(0)) / 2)
        extent = (plate[:, height].max() - plate[:, height].min()) * 1000
        center_offset = ((plate[:, height].min() + plate[:, height].max()) / 2
                         - (slot_lo + slot_hi) / 2) * 1000
        budget = ((slot_hi - slot_lo) * 1000 - thickness) / 2
        return {
            "slot_center_offset_mm": center_offset,
            "slot_center_budget_mm": budget,
            "tilt_extra_mm": extent - thickness,
            # 解算要按**夹爪自己的轴**分开处理(见 report_fit), 所以把当时的法兰位姿带出去
            "mount": mount,
            # 需要把托盘挪多少(世界系), 才能让孔板中心落到标称抓取基准上
            "need_world": need_world,
            # 【硬】板沿在槽的高度带内的上下余量(名义总余量 = 槽高 − 板厚 = 1.62 mm)
            "slot_lo_mm": (plate[:, height].min() - slot_lo) * 1000,
            "slot_hi_mm": (slot_hi - plate[:, height].max()) * 1000,
            # 【硬】唇口是否勾住板沿(正 = 勾住; 板宽必须大于闭合态唇口内隙)
            "hook_lo_mm": (lips[0] - plate[:, closing].min()) * 1000,
            "hook_hi_mm": (plate[:, closing].max() - lips[1]) * 1000,
            # 【硬】板沿不能顶到槽底
            "wall_lo_mm": (plate[:, closing].min() - walls[0]) * 1000,
            "wall_hi_mm": (walls[1] - plate[:, closing].max()) * 1000,
            # 【软】槽的 50.7 mm 有多少落在孔板边沿上(缺一段就是有槽悬空)
            "slot_covered_mm": max(0.0, min(slot_len_hi, plate[:, length].max())
                                   - max(slot_len_lo, plate[:, length].min())) * 1000,
            "slot_length_mm": (slot_len_hi - slot_len_lo) * 1000,
            # 【软】夹持位置离孔板中心多远(用户: "大概中心, 也不是 100%")
            "offcenter_mm": abs((slot_len_lo + slot_len_hi) / 2 - plate_center_len) * 1000,
        }

    def samples(self, clip_dir: Path) -> list[tuple[str, str, str, dict]]:
        """遍历全部整板转移片段, 取每条的取料点与放料点。"""
        rows = []
        for path in sorted(glob.glob(str(clip_dir / "transfer.tray.*.yaml"))):
            clip = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
            label = os.path.basename(path).replace("transfer.tray.", "").replace(".yaml", "")
            residuals = clip.get("compiled", {}).get("dockResiduals") or []
            if not residuals:
                raise SystemExit(f"{label} 缺 compiled.dockResiduals, 无法判定放料侧的目的托盘")
            # 放料侧要跟**目的地**托盘比, 不能跟被搬着的那块比 —— 片段里 detach 的 id 是
            # 正在被搬运的源实例(它此刻在爪里, 不在 CAD 原位), 拿它比会算出米级的伪值。
            destination = str(residuals[0]["payload"])
            for phase, (joints, rail, carried_id) in teach_poses(clip, self.catalog).items():
                payload_id = carried_id if phase == "attach" else destination
                station, _node = station_of(payload_id)
                rows.append((label, phase, station, {
                    "payload": payload_id, **self.evaluate(joints, rail, payload_id)}))
        return rows


#: 每个工位"拧在台面上"的那块安装底板。支承面门禁靠它判工位有没有离开台面。
STATION_MOUNT_PLATE = {
    "上料架-1": "PTLC-01-001 料架底板-1",
    "收集瓶支架总装-1": "PTLC-07-029 孔板缓存安装板-1",
    "样品瓶支架总装-1": "PTLC-07-029 孔板缓存安装板-1.001",
}
SUPPORT_FLUSH_TOL_MM = 0.05
OVERLAP_TOL_MM = 0.10


def report_support(rig_map: dict, raw_model: Path) -> int:
    """支承面门禁 —— 工位挪完之后, 它还坐在台面上吗? 有没有捅进别的零件里?

    为什么必须有这一条: 上一轮 `station_alignment` 把中转B 沿 Z 推了 −76.9 mm, 结果它从
    大面板上滑到了 `PTLC-07-022 机器人模组固定板` 上并压进去 1.5 mm —— 一处物理上不可能
    的摆位, 而当时的门禁(只判夹爪与孔板)48/48 全绿。夹爪对得上不等于工位放得下。

    跑在 **machine.raw.glb** 上而不是 full: full 已经按工位做过静态合并, 零件级节点没了,
    "脚下是哪块板"这种问题在合并后的模型上问不出来。这里把声明的平移量解析地施加到未合并
    的 CAD 上, 判的正是 rig_map 里那几行数值本身。
    """
    scene = trimesh.load(raw_model, force="scene")
    children: dict[str, list[str]] = {}
    for parent, child, *_rest in scene.graph.to_edgelist():
        children.setdefault(str(parent), []).append(str(child))

    known = set(scene.graph.nodes)
    missing: set[str] = set()

    def leaves(node: str) -> list[str]:
        # raw 里没有 INV_* —— 那是 blender_clean 后来造的节点。它们在 raw 里的本体
        # (收集瓶料架-N 等)本来就在工位子树内, 所以跳过不影响本门禁的两条判据;
        # 但要记下来报出去, 不能静默。
        if node not in known:
            missing.add(node)
            return []
        out, stack = [], [node]
        while stack:
            current = stack.pop()
            stack.extend(children.get(current, ()))
            if scene.graph.get(current)[1] is not None:
                out.append(current)
        return out

    boxes: dict[str, np.ndarray] = {}
    for name in {n for v in children.values() for n in v} | set(children):
        transform, geometry = scene.graph.get(name)
        if geometry is None:
            continue
        points = scene.geometry[geometry].vertices
        world = (transform @ np.column_stack((points, np.ones(len(points)))).T).T[:, :3] * 1000
        boxes[name] = np.array([world.min(0), world.max(0)])

    # 声明的平移: 整站 + 逐层(逐层节点是工位的子级, 两者叠加)
    shift: dict[str, np.ndarray] = {}
    for entry in (rig_map.get("station_alignment") or []):
        delta = np.array(entry["translate_mm"], dtype=float)
        for leaf in leaves(str(entry["node"])):
            shift[leaf] = shift.get(leaf, np.zeros(3)) + delta
    for entry in (rig_map.get("shelf_alignment") or []):
        delta = np.array(entry["translate_mm"], dtype=float)
        for node in entry["nodes"]:
            for leaf in leaves(str(node)):
                shift[leaf] = shift.get(leaf, np.zeros(3)) + delta

    print("支承面门禁(在未合并的 CAD 上施加声明的平移):")
    if missing:
        print(f"  (raw 里不存在、已跳过的节点 {len(missing)} 个: "
              f"{', '.join(sorted(missing)[:3])}{' ...' if len(missing) > 3 else ''})")
    failures: list[str] = []
    for station, plate in STATION_MOUNT_PLATE.items():
        inside = set(leaves(station))
        if plate not in boxes:
            raise SystemExit(f"支承面门禁: 找不到 {station} 的安装底板 {plate!r}")
        box = boxes[plate] + shift.get(plate, np.zeros(3))
        others = [(n, boxes[n] + shift.get(n, np.zeros(3))) for n in boxes if n not in inside]

        # 1) 底板底面必须贴在某块水平支承面上
        support = [(b[1][1], n) for n, b in others
                   if b[1][0] > box[0][0] and b[0][0] < box[1][0]
                   and b[1][2] > box[0][2] and b[0][2] < box[1][2]
                   and b[1][1] <= box[0][1] + SUPPORT_FLUSH_TOL_MM
                   and (b[1][1] - b[0][1]) < 600]
        if not support:
            failures.append(f"{station}: 底板下方没有任何支承面")
            print(f"  ✗ {station}: 底面 Y={box[0][1]:.2f}, **脚下悬空**")
            continue
        top, holder = max(support)
        gap = box[0][1] - top
        ok_gap = abs(gap) <= SUPPORT_FLUSH_TOL_MM

        # 2) 整个工位不得与工位外的零件产生**新增**体积交叠
        def overlaps(use_shift: bool) -> set[tuple[str, str]]:
            hits = set()
            for mine in inside:
                if mine not in boxes:
                    continue
                a = boxes[mine] + (shift.get(mine, np.zeros(3)) if use_shift else 0)
                for name, b in others:
                    if (b[1][1] - b[0][1]) > 600:      # 跳过整机级外壳
                        continue
                    inter = np.minimum(a[1], b[1]) - np.maximum(a[0], b[0])
                    if (inter > OVERLAP_TOL_MM).all():
                        hits.add((mine, name))
            return hits
        new = overlaps(True) - overlaps(False)

        mark = "  " if (ok_gap and not new) else "✗ "
        print(f"{mark}{station}: 底面 Y={box[0][1]:.2f} 坐在 {holder}(顶 {top:.2f}) 上, "
              f"间隙 {gap:+.2f} mm; 新增交叠 {len(new)} 处")
        if not ok_gap:
            failures.append(f"{station}: 底板离支承面 {gap:+.2f} mm (容差 ±{SUPPORT_FLUSH_TOL_MM})")
        for mine, other in sorted(new)[:3]:
            failures.append(f"{station}: {mine} 捅进了 {other}")

    print()
    if failures:
        print(f"支承面门禁失败 {len(failures)} 条:")
        for line in failures[:8]:
            print(f"  {line}")
        return 1
    print(f"支承面门禁通过: {len(STATION_MOUNT_PLATE)} 个工位仍贴在各自的支承面上, 无新增交叠")
    return 0


def report_grips(rows, aligner: "Aligner", out_path: Path) -> int:
    """产出"载荷↔夹爪"的相对位姿(TOOL_MOUNT 局部系), 供三维实时页挂托盘时钉局部位姿。

    为什么需要它: 实时页的在途行是在 `robot_group_rack_pick` **DONE** 时才落账, 而那个
    脚本以 `P7 -> P1 -> require_anchor(P1)` 收尾 —— 换父那一刻机械臂早已退回 home,
    离取料点一米开外。此时"保世界位姿换父"会把托盘冻在货架的世界位置却挂在 home 的法兰下,
    表现是托盘在虚空里跟着机械臂转。片段(/3d/demo)看着对, 是因为它的 attach 紧跟在合爪之后,
    那一刻臂正停在示教点 —— **演示靠时刻, 实时页没有那个时刻**, 所以必须把位姿显式给出。

    这与 gen_twin_manifest.resolve_plate_grip 为薄层板做的是同一件事(那边量吸盘几何,
    这边量取料示教位姿), 理由逐字相同: 载荷对刀具的关系本该与工位无关。

    只取**取料相**(attach): 放料相的 payload 是目的地托盘, 那时它还没被夹起来。

    ⚠ 必须按 `INV_*` 节点逐个产出, 不能"每种耗材一个常量" —— 14 个载荷节点里 13 个的
      局部系一致, 唯独 INV_STAGING_B 的多转 90°(合成空节点的作者约定, 见
      export_payload_poses.py)。按节点算天然吃掉这个差异。
    """
    samples: dict[str, list[np.ndarray]] = {}
    for _label, phase, _station, data in rows:
        if phase != "attach":
            continue
        payload = str(data["payload"])
        local = np.linalg.inv(data["mount"]) @ aligner.glb.world_matrix(payload)
        samples.setdefault(payload, []).append(local)

    if not samples:
        raise SystemExit("一个取料相都没采到 —— 片段是不是没编译?")

    grips: dict[str, dict] = {}
    worst_spread = 0.0
    print("载荷在 TOOL_MOUNT 局部系下的位姿(取料示教位姿实测):\n")
    print(f"  {'载荷':<24} {'x':>8} {'y':>8} {'z':>8}  {'样本':>4} {'散布mm':>7}")
    for payload, mats in sorted(samples.items()):
        translations = np.array([m[:3, 3] for m in mats])
        rotation = Rotation.from_matrix(np.array([m[:3, :3] for m in mats])).mean()
        position = np.median(translations, axis=0)
        spread = float(np.linalg.norm(translations - position, axis=1).max()) * 1000
        worst_spread = max(worst_spread, spread)
        quaternion = rotation.as_quat()          # scipy 与 three.js 同为 [x,y,z,w]
        grips[payload] = {
            "position": [round(float(v), 9) for v in position],
            "quaternion": [round(float(v), 9) for v in quaternion],
            "samples": len(mats),
            "spreadMm": round(spread, 3),
        }
        mm = position * 1000
        print(f"  {payload:<24}{mm[0]:>8.1f}{mm[1]:>8.1f}{mm[2]:>8.1f}"
              f"  {len(mats):>4} {spread:>7.2f}")

    out_path.write_text(json.dumps({
        "schema": "ptlc.payload-grips/v1",
        "generatedFrom": os.path.basename(str(aligner.glb_path)),
        "note": ("载荷相对 TOOL_MOUNT 的刚体位姿, 由取料示教位姿实测 "
                 "(inv(mount_world) @ node_world)。运行期挂载时直接钉这个局部位姿, "
                 "不要用保世界位姿换父 —— 换父时刻机械臂通常已不在取料点。"),
        "grips": grips,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已写出 {out_path}({len(grips)} 个载荷, 最大样本散布 {worst_spread:.2f} mm)")
    if worst_spread > MAX_GRIP_SPREAD_MM:
        print(f"⚠ 散布超过 {MAX_GRIP_SPREAD_MM} mm —— 同一载荷在不同片段里的夹持关系应当一致, "
              "散布大说明示教点或工位摆位有一处不自洽")
        return 1
    return 0


def report_fit(rows, aligner: "Aligner") -> int:
    """解算并打印**可直接回填的绝对值**。

    输出的是绝对值而不是增量: `need_world` 是相对**当前构建**的残差, 而当前构建里已经
    施加过一轮平移。让人去做这道加法迟早会错(而且错了没人发现), 所以这里直接读 rig_map
    现值加上去。

    水平与竖直分给两段(理由见 SHELF_GROUPS 注释): 整站只吃水平, 竖直逐层。

    # ⚠ 整站水平只按**硬约束轴**解算, 长度轴一律放开(2026-08-05 订正)

    托盘只在两根轴上被真正卡住: 钳口**闭合轴**(榫槽卡合, 单边间隙 0.13 mm)与**高度轴**
    (槽高余量 0.81 mm)。而**长度轴** —— 夹爪沿托盘长边咬在哪 —— 几何上根本不约束, 它由
    示教时人手停在哪决定。

    此前这里把 `need_world` 三个分量**一视同仁**地取均值, 等于用整站平移去追那个自由量。
    后果(实测): 三站被多挪了 19~28 mm, 而门禁照样 48/48 全绿 —— 逐站 3 个自由度足以
    吸收任何来源的误差, 绿只证明"托盘被挪到了机器人以为的地方", 不证明工位摆对了。
    现场复核确认真机夹爪只咬住托盘靠机械臂那一半、最前端够不到托盘中心, 而当时的模型把
    夹爪画到了越过中心 25.4 mm 处 —— **方向都反了**。

    改为只拟合硬轴后: 三站需要的平移从 40.5/23.1/35.7 降到 12.7/4.1/8.1 mm, 硬轴残差
    反而更紧(max 1.36 vs 5.41 mm)。竖直分量几乎不受影响(长度轴基本是水平的), 所以
    `shelf_alignment` 那一段照旧。

    ⚠ 最小二乘会**秩亏**: 每个位姿只约束 2 个方向, 长度方向落在零空间里。必须取最小
    范数解(`rcond` 给一个有限值), 否则会解出 10^5 mm 量级的伪平移却报"残差 0.00"。
    """
    current_station = {str(e.get("node")): np.array(e["translate_mm"], dtype=float)
                       for e in (aligner.rig_map.get("station_alignment") or [])}
    current_shelf = {str(e.get("label")): np.array(e["translate_mm"], dtype=float)
                     for e in (aligner.rig_map.get("shelf_alignment") or [])}

    # 每个载荷此刻已被施加的总平移(整站 + 该层), 用来把 need 还原成"相对 CAD 原位"的
    # 总偏差 —— 硬轴约束必须加在**总量**上, 加在增量上等于默认现值的长度轴分量是对的。
    applied: dict[str, np.ndarray] = {}
    for payload in {d["payload"] for *_x, d in rows}:
        _station, node = station_of(payload)
        total = current_station.get(node, np.zeros(3)).copy()
        for entry in (aligner.rig_map.get("shelf_alignment") or []):
            if payload in [str(n) for n in (entry.get("nodes") or [])]:
                total = total + np.array(entry["translate_mm"], dtype=float)
        applied[payload] = total / 1000.0

    by_station: dict[str, list] = {}
    by_payload: dict[str, list] = {}
    for _label, _phase, station, data in rows:
        # need 是相对当前构建的; 加回已施加的平移就得到相对 CAD 原位的总偏差
        total_need = data["need_world"] + applied[data["payload"]]
        by_station.setdefault(station, []).append((total_need, data["mount"]))
        by_payload.setdefault(data["payload"], []).append(data["need_world"])

    closing, _length, height = aligner._axes
    hard = [closing, height]
    print("station_alignment —— 整站只吃**水平**, 且只按**硬约束轴**解算"
          "(长度轴=夹爪咬在托盘长边哪个位置, 几何不约束, 放开):\n")
    worst = 0.0
    for station, samples in sorted(by_station.items()):
        needs = np.array([n for n, _m in samples])
        # 只让闭合轴与高度轴参与; 秩亏(长度方向在零空间)故取最小范数解
        matrix = np.vstack([m[:3, hard].T for _n, m in samples])
        target = np.concatenate([m[:3, hard].T @ n for n, m in samples])
        solved, *_ = np.linalg.lstsq(matrix, target, rcond=1e-3)
        residual = np.linalg.norm(
            np.array([m[:3, hard].T @ (n - solved) for n, m in samples]), axis=1) * 1000
        worst = max(worst, residual.max())
        absolute = solved * 1000
        node = RACK_STATION[1] if station == "RACK" else next(
            n for s, n in STATION_OF_PAYLOAD.values() if s == station)
        slack = np.linalg.norm(needs.mean(0) * 1000) - np.linalg.norm(absolute)
        print(f"  - node: \"{node}\"        # {station}, {len(samples)} 个取放点")
        print(f"      translate_mm: [{absolute[0]:.1f}, 0, {absolute[2]:.1f}]"
              f"   水平模长 {np.hypot(absolute[0], absolute[2]):.1f} mm"
              f"   (竖直 {absolute[1]:+.2f} 转入 shelf_alignment)")
        print(f"      # 硬轴残差 最大 {residual.max():.1f} / 均值 {residual.mean():.1f} mm;"
              f" 全轴拟合会多挪 {slack:.1f} mm(全是长度轴, 不该记在工位账上)")

    print("\nshelf_alignment —— 竖直逐层(搁板/台面这一层动, 工位仍坐在大面板上):\n")
    for group in SHELF_GROUPS:
        picked = [v for pid in group["payloads"] for v in by_payload.get(pid, [])]
        if not picked:
            raise SystemExit(f"shelf_alignment 分组 {group['label']} 一个取放点都没命中: "
                             f"{group['payloads']} —— 载荷名单过期了?")
        vertical = np.array(picked).mean(0)[1] * 1000
        per_payload = [np.mean(by_payload[p], 0)[1] * 1000
                       for p in group["payloads"] if p in by_payload]
        # 这一层的载荷此刻正被整站竖直量托着, 而整站竖直即将归 0 —— 那份量要接过来,
        # 否则回填出来的会是"相对当前构建的增量"而不是绝对值(实测符号都是反的)。
        station_node = station_of(group["payloads"][0])[1]
        inherited = current_station.get(station_node, np.zeros(3))[1]
        absolute = inherited + current_shelf.get(group["label"], np.zeros(3))[1] + vertical
        nodes = ", ".join(f'"{n}"' for n in group["shelf"] + group["payloads"])
        print(f"  - label: \"{group['label']}\"")
        print(f"      nodes: [{nodes}]")
        print(f"      translate_mm: [0, {absolute:.2f}, 0]"
              f"     # 层内散布 {max(per_payload) - min(per_payload):.2f} mm")

    print("\n把上面两段原样回填到 rig_map.yaml(已是绝对值, 不要再加)。")
    if worst > MAX_SLOT_RESIDUAL_MM:
        print(f"⚠ 最大残差 {worst:.1f} mm 超过 {MAX_SLOT_RESIDUAL_MM} mm —— "
              "纯平移可能不足以描述该误差, 回填前先查是否有转动或逐库位偏差")
    return 0


def report_design(aligner: "Aligner") -> tuple[int, list[str]]:
    """与工位摆位无关的尺寸链校核。摆位可以慢慢调, 但这几条一旦不成立, 说明"齐平唇口
    夹住孔板"这个前提本身就没了 —— 后面所有逐位姿判定都失去意义, 必须先停下来看 CAD。
    """
    d = aligner.design_check()
    checks = [
        ("唇口内隙 < 板宽(上下唇口勾住板沿, 板出不来)",
         d["lip_gap_closed_mm"] < d["plate_width_mm"],
         f"{d['lip_gap_closed_mm']:.2f} < {d['plate_width_mm']:.2f}"),
        ("槽内隙 > 板宽(板沿插得进去)",
         d["slot_gap_closed_mm"] > d["plate_width_mm"],
         f"{d['slot_gap_closed_mm']:.2f} > {d['plate_width_mm']:.2f}"),
        ("槽高 ≥ 板厚",
         d["slot_height_mm"] >= d["plate_thickness_mm"],
         f"{d['slot_height_mm']:.2f} ≥ {d['plate_thickness_mm']:.2f}"),
    ]
    print("设计校核 —— 榫槽卡合(与工位摆位无关; CAD 或 holdValue 一改就报):")
    failures = []
    for name, ok, detail in checks:
        print(f"  {'  ' if ok else '✗ '}{name}: {detail}")
        if not ok:
            failures.append(name)
    print(f"  槽 {d['slot_height_mm']:.2f}(高) × {d['slot_length_mm']:.2f}(长) mm; "
          f"竖直名义余量 {d['slot_height_mm'] - d['plate_thickness_mm']:.2f} mm\n")
    return (1 if failures else 0), failures


def report_check(rows, aligner: "Aligner") -> int:
    status, design_failures = report_design(aligner)

    print("逐位姿判定(闭合态; 张开态唇口内隙比板宽 3 mm, 拿它算什么都过得去):")
    print("  硬判 = 板沿在槽内 + 唇口勾住; 软判 = 槽真的压在孔板边沿上(偏心只报不判)\n")
    print(f"  {'位姿':32s} {'板心离槽心/预算':>18s} {'离槽底(下/上)':>18s} "
          f"{'槽被覆盖':>8s} {'偏心':>7s} {'姿态差':>7s}")
    failures: list[str] = []
    for label, phase, _station, d in rows:
        tol = -CLEARANCE_TOLERANCE_MM
        uncovered = d["slot_length_mm"] - d["slot_covered_mm"]
        over = abs(d["slot_center_offset_mm"]) - d["slot_center_budget_mm"]
        hard = (over <= CLEARANCE_TOLERANCE_MM
                and d["wall_lo_mm"] >= tol and d["wall_hi_mm"] >= tol)
        soft = uncovered <= MAX_SLOT_UNCOVERED_MM
        print(f"{'  ' if hard and soft else ('~ ' if hard else '✗ ')}{label + '/' + phase:32s} "
              f"{d['slot_center_offset_mm']:+8.2f}/{d['slot_center_budget_mm']:8.2f} "
              f"{d['wall_lo_mm']:8.2f}/{d['wall_hi_mm']:8.2f} "
              f"{d['slot_covered_mm']:8.1f} {d['offcenter_mm']:7.1f} {d['tilt_extra_mm']:7.2f}")
        if hard and soft:
            continue
        reasons = []
        if over > CLEARANCE_TOLERANCE_MM:
            reasons.append(f"板心偏离槽心 {abs(d['slot_center_offset_mm']):.2f} mm"
                           f"(预算 {d['slot_center_budget_mm']:.2f})")
        if d["wall_lo_mm"] < tol or d["wall_hi_mm"] < tol:
            reasons.append(f"板沿顶到槽底 {abs(min(d['wall_lo_mm'], d['wall_hi_mm'])):.2f} mm")
        if uncovered > MAX_SLOT_UNCOVERED_MM:
            reasons.append(f"槽有 {uncovered:.1f} mm 悬空在孔板外")
        failures.append(f"{'  ' if hard else '硬'}{label}/{phase}: " + "; ".join(reasons))

    print()
    if design_failures:
        print(f"设计校核未通过 {len(design_failures)} 条 —— 先看 CAD, 别急着调摆位")
    if failures:
        print(f"落位对齐门禁失败: {len(failures)}/{len(rows)} 个位姿不合格")
        for line in failures[:8]:
            print(f"  {line}")
        return 1
    worst_center = max(abs(d["slot_center_offset_mm"]) for *_x, d in rows)
    budget = rows[0][3]["slot_center_budget_mm"]
    worst_off = max(d["offcenter_mm"] for *_x, d in rows)
    worst_tilt = max(d["tilt_extra_mm"] for *_x, d in rows)
    print(f"落位对齐门禁通过: {len(rows)} 个取放点; "
          f"板心最大偏离槽心 {worst_center:.2f} mm(预算 {budget:.2f} + 容差 {CLEARANCE_TOLERANCE_MM:.2f}); "
          f"托盘与钳口姿态差把板厚在 mount 系撑大 ≤{worst_tilt:.2f} mm(观测量, 纯平移消不掉)")
    print(f"  观测量·夹持偏心 最大 {worst_off:.1f} mm —— **不判**: 夹爪沿托盘长边咬在哪由示教点决定, "
          f"几何不约束(见 MAX_SLOT_UNCOVERED_MM_NOTE 上方注释)")
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="解算/校验工位摆位与机器人示教点的对齐")
    parser.add_argument("--model", default=str(ROOT / "work" / "machine.full.glb"))
    parser.add_argument("--manifest", default=str(ROOT / "models" / "device-manifest.official-cr5.json"))
    parser.add_argument("--catalog", default=str(ROOT / "generated" / "robot-points.json"))
    parser.add_argument("--rig-map", default=str(Path(__file__).resolve().parent / "rig_map.yaml"))
    parser.add_argument("--clips", default=str(ROOT / "clips"))
    parser.add_argument("--raw", default=str(ROOT / "work" / "machine.raw.glb"),
                        help="支承面门禁用的未合并 CAD")
    parser.add_argument("--fit", action="store_true", help="解算模式(默认): 打印各工位需要的平移量")
    parser.add_argument("--check", action="store_true", help="门禁模式: 不合格以非零退出")
    parser.add_argument("--emit-grips", action="store_true",
                        help="产出 generated/payload-grips.json(载荷相对 TOOL_MOUNT 的位姿, 供实时页挂托盘)")
    parser.add_argument("--grips-out", default=str(ROOT / "generated" / "payload-grips.json"))
    args = parser.parse_args()

    # 防呆: 模型比 rig_map 旧, 说明改了对齐量却没重跑 03(或 03 写到了别的文件名 ——
    # `--stage full` 的 --output 默认是 machine.clean.glb, 不加就不会覆盖 machine.full.glb)。
    # 这种情况下门禁照跑照报数, 数字却是上一版模型的, 极易误判成"改了没生效"。
    model_path, rig_path = Path(args.model), Path(args.rig_map)
    if model_path.stat().st_mtime < rig_path.stat().st_mtime:
        raise SystemExit(
            f"{model_path.name} 比 {rig_path.name} 旧 —— 对齐量改过但模型没重建。\n"
            f"  先跑: python 03_clean_model.py --stage full --output ../work/machine.full.glb")

    aligner = Aligner(model_path, Path(args.manifest), Path(args.catalog), rig_path)
    rows = aligner.samples(Path(args.clips))
    if not rows:
        raise SystemExit("没有找到 transfer.tray.*.yaml 片段, 先跑 sync_ptlc_robot.py --transfers")
    if args.emit_grips:
        raise SystemExit(report_grips(rows, aligner, Path(args.grips_out)))
    if not args.check:
        raise SystemExit(report_fit(rows, aligner))
    support = report_support(aligner.rig_map, Path(args.raw))
    raise SystemExit(report_check(rows, aligner) | support)


if __name__ == "__main__":
    main()
