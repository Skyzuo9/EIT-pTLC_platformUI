"""落位 dock 的姿态保真锁 —— 两条各自独立的缺陷, 都能静默烤进片段。

一、`_dock_of` 必须先除掉节点自身的 scale 再取四元数。
    scipy(1.11.4)的 `Rotation.from_matrix` 对**带缩放**的矩阵不做归一化, 会安静地解出
    一个完全无关的旋转: scale=1 时误差 2.2e-16, 而 04_optimize 的 meshopt 量化把中转B
    那六只样品瓶压成的 scale=0.0475 下, 角误差中位 68.1°、最大 106.1°(2026-08-13 实测,
    3000 次随机姿态)。此前 dock 就是直接喂 `local[:3,:3]` 烤的 —— 那六只瓶的落位姿态整个
    是错的, 且全程零报错(前端只会拿到一个合法的单位四元数)。
    反解式必须与前端逐字互逆: MachineStateDriver.dockPayload 只写 position/quaternion、
    原样保留 node.scale, 前端复原的是 R(q)·diag(node_scale)。

二、`_instance_frame_map` 是"实例交换保姿态"的地基。
    同一零件在 CAD 里有两份拷贝(刮板夹具那只粉桶 与 收集工位那只), 两份的**子件局部帧
    并不一致** —— 实测差到 180°。于是"把源实例摆在 X 处"与"把目的实例摆在 X 处"根本不是
    同一个画面, 隐源/显目的那一帧就是一次肉眼可见的瞬移(实测 35.7 ~ 125.3mm)。
    对应关系只能按 mesh 索引认(两份拷贝叶名不同), 且只能用**在各自子树内唯一出现**的
    mesh —— 一只托盘下 6 只同款瓶共用一个 mesh, 拿它们乱配会把孔距(154mm)当成姿态差。
"""

import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "three_d" / "pipeline"))

#: 中转B 六只样品瓶被 meshopt 量化压成的 scale(GLB 实测值, 各向异性比 1.000000083)。
QUANTIZED_SCALE = [0.047500003348764745, 0.04749999940395355, 0.047500003348764745]


def _dock_of(local, node_scale):
    from clip_compiler import _dock_of as impl

    return impl(local, node_scale)


def _local_of(quaternion_xyzw, position, node_scale):
    """按**前端**的复原式造一个局部矩阵: R(q)·diag(scale), 平移直接写。"""
    local = np.eye(4)
    local[:3, :3] = Rotation.from_quat(quaternion_xyzw).as_matrix() @ np.diag(node_scale)
    local[:3, 3] = position
    return local


def test_dock_of_round_trips_through_quantized_scale():
    """量化件: dock 反解出来的四元数, 经前端复原式必须还原出原矩阵。

    这条就是"别把 local[:3,:3] 直接喂 from_matrix"的锁 —— 直接喂在 scale=0.0475 下
    差几十度, 本用例立刻红。
    """
    rotation = Rotation.from_euler("xyz", [37.0, -128.0, 64.0], degrees=True).as_quat()
    position = [0.123456, -0.654321, 0.098765]
    local = _local_of(rotation, position, QUANTIZED_SCALE)

    dock = _dock_of(local, QUANTIZED_SCALE)
    restored = _local_of(dock["quaternion"], dock["position"], QUANTIZED_SCALE)

    # dock 只保留 8 位小数, 1e-7 是量化位数本身的下界, 不是容差放水
    assert np.allclose(restored, local, atol=1e-7), "反解式与前端复原式必须互逆"


def test_naive_from_matrix_is_actually_wrong_at_this_scale():
    """把"scipy 会自己归一化"这个错误前提钉死成可证伪的数字。

    若某天 scipy 改成对带缩放矩阵也返回极分解的旋转, 本用例会红 —— 那时 _dock_of 里
    那一步除法就可以删, 但必须由这条断言的失败来触发, 而不是凭印象。
    """
    rotation = Rotation.from_euler("xyz", [37.0, -128.0, 64.0], degrees=True)
    scaled = rotation.as_matrix() @ np.diag(QUANTIZED_SCALE)
    naive = Rotation.from_matrix(scaled)
    error_deg = (naive.inv() * rotation).magnitude() * 180.0 / np.pi
    assert error_deg > 1.0, (
        "scipy.from_matrix 在 scale=0.0475 下仍会解错(实测中位 68.1°); "
        f"本次 {error_deg:.1f}° —— 若它已被修好, 请连同 _dock_of 的除法一起复核")


def test_dock_of_rejects_wrong_scale():
    """传错 scale 必须硬失败, 不许烤出一个"看着合法"的四元数。"""
    from clip_compiler import CompileError

    local = _local_of([0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0], QUANTIZED_SCALE)
    with pytest.raises(CompileError, match="不正交"):
        _dock_of(local, [1.0, 1.0, 1.0])


# --- 实例帧映射 --------------------------------------------------------------- #


class _FakeScene:
    """最小 GlbScene 替身: 只需要 nodes / index_of / local_matrix 三样。"""

    def __init__(self, nodes: list[dict]) -> None:
        self.nodes = nodes
        self._by_name = {str(node.get("name")): i for i, node in enumerate(nodes)}

    def index_of(self, path: str) -> int:
        return self._by_name[path.rsplit("/", 1)[-1]]

    def local_matrix(self, index: int) -> np.ndarray:
        matrix = np.eye(4)
        matrix[:3, 3] = self.nodes[index].get("t", [0.0, 0.0, 0.0])
        return matrix


def _frame_map(scene, carried_node: str, destination_node: str) -> np.ndarray:
    from clip_compiler import ClipBuilder

    builder = object.__new__(ClipBuilder)
    builder.scene = scene
    return ClipBuilder._instance_frame_map(
        builder, {"id": "SRC", "node": carried_node}, {"id": "DST", "node": destination_node})


def _two_instances(source_offset, dest_offset, *, mesh=7):
    """两份同零件拷贝: 各自一个子节点挂同一个 mesh, 子节点相对父节点的偏移不同。"""
    return _FakeScene([
        {"name": "SRC", "children": [1]},
        {"name": "SRC_PART", "mesh": mesh, "t": source_offset},
        {"name": "DST", "children": [3]},
        {"name": "DST_PART", "mesh": mesh, "t": dest_offset},
    ])


def test_instance_frame_map_recovers_the_offset_between_two_copies():
    scene = _two_instances([0.10, 0.0, 0.0], [0.0, 0.04, 0.0])
    mapping = _frame_map(scene, "SRC", "DST")
    # Ms·Md⁻¹: 源子件在 +0.10x, 目的子件在 +0.04y ⇒ 映射平移 = (0.10, −0.04, 0)
    assert np.allclose(mapping[:3, 3], [0.10, -0.04, 0.0], atol=1e-12)
    assert np.allclose(mapping[:3, :3], np.eye(3), atol=1e-12)


def test_instance_frame_map_ignores_meshes_that_repeat_in_a_subtree():
    """同一子树里出现两次的 mesh 无法唯一配对, 必须被排除。

    真实对应物: 一只托盘下 6 只同款瓶共用同一个 mesh。不排除就会拿"第 1 只对第 4 只",
    把 154mm 的孔距当成姿态差。
    """
    from clip_compiler import CompileError

    scene = _FakeScene([
        {"name": "SRC", "children": [1, 2]},
        {"name": "SRC_A", "mesh": 7, "t": [0.0, 0.0, 0.0]},
        {"name": "SRC_B", "mesh": 7, "t": [0.15, 0.0, 0.0]},   # 同 mesh 出现两次
        {"name": "DST", "children": [4]},
        {"name": "DST_A", "mesh": 7, "t": [0.0, 0.0, 0.0]},
    ])
    with pytest.raises(CompileError, match="没有共享的唯一网格"):
        _frame_map(scene, "SRC", "DST")


def test_instance_frame_map_rejects_non_congruent_copies():
    """各网格解出的映射必须一致 —— 不一致说明两份拷贝不全等, 不许挑一个用。"""
    from clip_compiler import CompileError

    scene = _FakeScene([
        {"name": "SRC", "children": [1, 2]},
        {"name": "SRC_A", "mesh": 7, "t": [0.0, 0.0, 0.0]},
        {"name": "SRC_B", "mesh": 8, "t": [0.10, 0.0, 0.0]},
        {"name": "DST", "children": [4, 5]},
        {"name": "DST_A", "mesh": 7, "t": [0.0, 0.0, 0.0]},
        {"name": "DST_B", "mesh": 8, "t": [0.20, 0.0, 0.0]},   # 相对布局与源侧不同
    ])
    with pytest.raises(CompileError, match="实例帧映射不自洽"):
        _frame_map(scene, "SRC", "DST")
