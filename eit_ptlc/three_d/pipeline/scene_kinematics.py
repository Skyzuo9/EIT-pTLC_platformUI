"""在编译期复算浏览器场景里任意节点的世界位姿。

为什么需要它: 载荷落位要算"放料示教点上, 夹爪把托盘带到了哪儿"。这个位姿不是运动学
求解器的输出(那只给法兰位姿), 而是**GLB 层级 + 关节旋转 + 地轨平移**共同决定的
TOOL_MOUNT 世界矩阵。前端由 three.js 的场景图天然算出来, 编译期必须逐位复算。

因此本模块刻意**逐字镜像**两处前端实现, 改动必须同步:
  - `web/src/three-d/anim/RobotJointDriver.js`: modelDeg = controllerDeg*sign + zeroOffsetDeg,
    四元数 = 加载态 **后乘** 局部轴转角(前乘会把 local-Z 当父/世界轴, 是旧模型扭曲的病根)
  - `web/src/three-d/anim/MachineStateDriver.setAxisMm`:
    offset = (mm - zeroOffsetMm) * sign * mmToUnit, 位置 = 加载态 + 方向*offset

数据源是 **GLB 本体**而不是 work/structure.json —— 前者就是浏览器加载的那份产物,
后者只有世界 AABB 中心没有旋转(且是 Blender 侧的中间产物)。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def _trs_matrix(translation, rotation_xyzw, scale) -> np.ndarray:
    """由 glTF 的 TRS 组成 4x4 齐次矩阵(列向量约定, 与 three.js 一致)。"""
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_quat(np.asarray(rotation_xyzw, dtype=float)).as_matrix()
    matrix[:3, :3] = matrix[:3, :3] @ np.diag(np.asarray(scale, dtype=float))
    matrix[:3, 3] = np.asarray(translation, dtype=float)
    return matrix


class GlbScene:
    """只读 glTF 层级(不解码几何) —— 节点 TRS 全在 JSON 块里, 无需 meshopt/Draco 解码器。"""

    def __init__(self, path: str | Path) -> None:
        raw = Path(path).read_bytes()
        magic, _version, _length = struct.unpack_from("<III", raw, 0)
        if magic != 0x46546C67:
            raise ValueError(f"不是 GLB 文件: {path}")
        chunk_length, chunk_type = struct.unpack_from("<II", raw, 12)
        if chunk_type != 0x4E4F534A:
            raise ValueError("GLB 第一个块不是 JSON")
        self.gltf = json.loads(raw[20:20 + chunk_length].decode("utf-8"))

        self.nodes = self.gltf.get("nodes") or []
        self.parent: dict[int, int] = {}
        for index, node in enumerate(self.nodes):
            for child in node.get("children") or []:
                self.parent[int(child)] = index
        self.roots = [
            index for index in range(len(self.nodes)) if index not in self.parent
        ]
        self._by_name: dict[str, list[int]] = {}
        for index, node in enumerate(self.nodes):
            name = node.get("name")
            if name:
                self._by_name.setdefault(str(name), []).append(index)

    # -- 查找 ------------------------------------------------------------- #

    def index_of(self, path: str) -> int:
        """按 manifest 的 "A/B/C" 路径或裸叶名找唯一节点。

        与前端 loadModel.buildNodeIndex 的两级解析同构: 全路径优先, 裸叶名回退。

        Raises:
            KeyError: 找不到, 或裸叶名不唯一
        """
        leaf = path.rsplit("/", 1)[-1]
        candidates = self._by_name.get(leaf) or []
        if not candidates:
            raise KeyError(f"GLB 里没有节点: {path}")
        if len(candidates) == 1:
            return candidates[0]
        # 叶名重名时按祖先链消歧
        wanted = path.split("/")
        for index in candidates:
            chain = []
            cursor: int | None = index
            while cursor is not None:
                chain.append(str(self.nodes[cursor].get("name") or ""))
                cursor = self.parent.get(cursor)
            chain.reverse()
            if all(part in chain for part in wanted):
                return index
        raise KeyError(f"节点路径不唯一且无法消歧: {path}(候选 {len(candidates)} 个)")

    def name_of(self, index: int) -> str:
        return str(self.nodes[index].get("name") or "")

    def parent_path(self, path: str) -> str:
        """取一个节点父级的裸名(载荷落位要挂到它下面)。"""
        index = self.index_of(path)
        parent = self.parent.get(index)
        return "" if parent is None else self.name_of(parent)

    # -- 位姿 ------------------------------------------------------------- #

    def local_matrix(self, index: int, overrides: dict[int, np.ndarray] | None = None) -> np.ndarray:
        if overrides is not None and index in overrides:
            return overrides[index]
        node = self.nodes[index]
        if "matrix" in node:
            # glTF 的 matrix 是列主序 16 元组
            return np.asarray(node["matrix"], dtype=float).reshape(4, 4, order="F")
        return _trs_matrix(
            node.get("translation", [0.0, 0.0, 0.0]),
            node.get("rotation", [0.0, 0.0, 0.0, 1.0]),
            node.get("scale", [1.0, 1.0, 1.0]),
        )

    def world_matrix(self, path: str, overrides: dict[int, np.ndarray] | None = None) -> np.ndarray:
        """从根到该节点逐级相乘得到世界矩阵。"""
        index = self.index_of(path)
        chain: list[int] = []
        cursor: int | None = index
        while cursor is not None:
            chain.append(cursor)
            cursor = self.parent.get(cursor)
        matrix = np.eye(4)
        for node_index in reversed(chain):
            matrix = matrix @ self.local_matrix(node_index, overrides)
        return matrix


class RobotPosture:
    """按 manifest 的轴/关节声明, 把"地轨毫米 + 六轴控制器角"折算成节点局部矩阵覆盖。"""

    def __init__(self, scene: GlbScene, manifest: dict) -> None:
        self.scene = scene
        self.manifest = manifest
        robot = manifest.get("robot") or {}
        self.joints = list(robot.get("joints") or [])
        self.mount_path = str(robot.get("toolMount") or "TOOL_MOUNT")
        self.rail_spec = next(
            (axis for axis in manifest.get("axes") or []
             if axis.get("id") == "axis_11y" and axis.get("rigged")),
            None,
        )
        if self.rail_spec is None:
            raise ValueError("manifest 里没有已装配的 axis_11y —— 载荷落位算不了")

    def rail_fingerprint(self) -> dict:
        """产出地轨标定指纹, 供片段自述"我是按哪套标定烘的"。

        下面 overrides() 把地轨毫米折成节点位移用的就是这三个数, 而结果会一路烘进
        片段的 dock 位姿与 moveL 轨迹。标完零点若不重编译片段, 那些烘死的落点就与
        新标定对不上了 —— 而且不会报任何错。把三个数随片段一起存下来, 前端才有得比。
        """
        spec = self.rail_spec
        low, high = (spec.get("rangeMm") or [0.0, 0.0])
        return {
            "axis": "axis_11y",
            "zeroOffsetMm": float(spec.get("zeroOffsetMm", 0.0)),
            "sign": int(spec.get("sign", 1)),
            "rangeMm": [float(low), float(high)],
        }

    def axis_override(self, axis_id: str, value_mm: float) -> dict[int, np.ndarray]:
        """任意已装配直线轴的节点覆盖 —— 与 MachineStateDriver.setAxisMm 同式。

        地轨只是它的一个特例。工位轴(点样 7Y / 刮板 8Y / 上下料 1Z·2Z)也要能覆盖:
        板托座就骑在这些轴上, 轴不摆到位, CAD 锚点停在建模位而机器人去了另一处 ——
        2026-08-05 实测的 7Y 99mm / 8Y 35mm / 料仓 530mm 三处错位都是这么来的。
        """
        spec = next((axis for axis in self.manifest.get("axes") or []
                     if axis.get("id") == axis_id and axis.get("rigged")), None)
        if spec is None:
            raise ValueError(f"manifest 里没有已装配的 {axis_id}")
        index = self.scene.index_of(str(spec["glbNode"]))
        base = self.scene.local_matrix(index)
        direction = np.asarray(spec.get("axis") or [1, 0, 0], dtype=float)
        direction = direction / np.linalg.norm(direction)
        low, high = (spec.get("rangeMm") or [0.0, 0.0])
        clamped = min(max(float(value_mm), float(low)), float(high))
        offset = ((clamped - float(spec.get("zeroOffsetMm", 0.0)))
                  * float(spec.get("sign", 1)) * float(spec.get("mmToUnit", 0.001)))
        moved = base.copy()
        moved[:3, 3] = base[:3, 3] + direction * offset
        return {index: moved}

    def actuator_override(self, spec: dict, value: float) -> dict[int, np.ndarray]:
        """任意已装配执行器的节点覆盖 —— 与 MachineStateDriver.applyMotion **逐字同式**。

        为什么需要: 载荷可能骑在机构上(刮板接粉座在翻料缸 ps_rotate 上、收集工位瓶/桶
        在 col_extend/col_lift 上)。机构不摆到位, 编译器取到的源/目的姿态是建模位 ——
        STA_SCRAPE_HOLDER 曾因此(叠加 9X 滑车)烤出与前端差 383.67mm 的夹持变换而全程
        零报错(2026-08-07 实测)。

        同式细节(applyMotion): output = 线性 clamp 映射(inputRange→outputRange);
        rotate 分支 = 基四元数**右乘**局部轴角(度, 乘 sign); translate 分支 = 基位移 +
        axis·output·unitScale·sign。rotate 要求基旋转正交(带缩放的基在 three.js 走
        四元数分解, 与矩阵右乘不同式) —— 非正交硬失败, 不许悄悄不同式。
        """
        node = spec.get("node") or spec.get("glbNode")
        index = self.scene.index_of(str(node))
        base = self.scene.local_matrix(index)
        in_lo, in_hi = [float(v) for v in (spec.get("inputRange") or [0, 1])]
        out_lo, out_hi = [float(v) for v in (spec.get("outputRange") or [0, 1])]
        lo, hi = min(in_lo, in_hi), max(in_lo, in_hi)
        span = in_hi - in_lo
        normalized = 0.0 if abs(span) < 1e-12 else (
            (min(max(float(value), lo), hi) - in_lo) / span)
        output = out_lo + (out_hi - out_lo) * normalized
        axis = np.asarray(spec.get("axis") or [1, 0, 0], dtype=float)
        axis = axis / np.linalg.norm(axis)
        sign = float(spec.get("sign", 1))
        moved = base.copy()
        motion = str(spec.get("motion") or spec.get("kind") or "translate")
        if motion in ("rotate", "rotary"):
            rotation = base[:3, :3]
            if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3):
                raise ValueError(
                    f"执行器节点 {node} 基旋转非正交(带缩放) —— 机构覆盖无法与前端同式")
            delta = Rotation.from_rotvec(axis * np.deg2rad(output * sign)).as_matrix()
            moved[:3, :3] = rotation @ delta
        else:
            unit = float(spec.get("unitScale") or spec.get("mmToUnit") or 1.0)
            moved[:3, 3] = base[:3, 3] + axis * (output * unit * sign)
        return {index: moved}

    def overrides(self, *, joints_deg, rail_mm: float,
                  axes_mm: dict[str, float] | None = None) -> dict[int, np.ndarray]:
        """产出 {节点下标: 局部矩阵} 覆盖表。

        Args:
            joints_deg: 六轴控制器角
            rail_mm: 地轨毫米
            axes_mm: 额外的工位轴毫米(轴 id -> 值), 用于把板托座摆到位
        """
        result: dict[int, np.ndarray] = {}

        # -- 地轨与工位轴: 与 MachineStateDriver.setAxisMm 同式 --------------- #
        result.update(self.axis_override("axis_11y", rail_mm))
        for axis_id, value in (axes_mm or {}).items():
            result.update(self.axis_override(axis_id, value))

        # -- 六轴: 与 RobotJointDriver.setJointsDeg 同式(局部轴后乘) --------- #
        for order, joint in enumerate(self.joints):
            raw = joints_deg[order] if order < len(joints_deg) else None
            if raw is None or not np.isfinite(raw):
                continue
            node_index = self.scene.index_of(str(joint["node"]))
            local = self.scene.local_matrix(node_index)
            axis = np.asarray(joint.get("axis") or [0, 1, 0], dtype=float)
            axis = axis / np.linalg.norm(axis)
            model_deg = float(raw) * float(joint.get("sign", 1)) + float(joint.get("zeroOffsetDeg", 0.0))
            delta = Rotation.from_rotvec(axis * np.deg2rad(model_deg)).as_matrix()
            rotated = local.copy()
            # 后乘: 加载态旋转 @ 局部轴转角(前乘会绕父/世界轴, 见 RobotJointDriver 头注释)
            rotated[:3, :3] = local[:3, :3] @ delta
            result[node_index] = rotated
        return result

    def mount_world(self, *, joints_deg, rail_mm: float,
                    axes_mm: dict[str, float] | None = None) -> np.ndarray:
        """给定姿态下 TOOL_MOUNT 的世界矩阵。"""
        return self.scene.world_matrix(
            self.mount_path,
            self.overrides(joints_deg=joints_deg, rail_mm=rail_mm, axes_mm=axes_mm),
        )

    def node_world(self, path: str, *, joints_deg, rail_mm: float,
                   axes_mm: dict[str, float] | None = None) -> np.ndarray:
        """给定姿态下任意节点的世界矩阵(板锚点骑在工位轴上, 要跟着 axes_mm 走)。"""
        return self.scene.world_matrix(
            path, self.overrides(joints_deg=joints_deg, rail_mm=rail_mm, axes_mm=axes_mm)
        )
