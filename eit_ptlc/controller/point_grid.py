"""货架/仓库库位仿射网格 — 由 3+ 角点标定, 算出规则点阵每个库位的 6DOF 机器人位姿。

与 `plate_affine` 同源思想 (逻辑 (col,row) 网格 → 物理量的 2D 仿射), 但这里对 6 个
位姿分量 (X, Y, Z, Rx, Ry, Rz) 各拟合一个平面 `v = a·col + b·row + c`, 再叠加每个
库位的静态偏置 (offset, 吸收机械/示教散差)。3 个角点为精确解, >3 个取最小二乘。

设计要点:
  - 逻辑坐标 (col, row) 1-based; 角点须逻辑不共线 (否则退化, 抛 ValueError)。
  - 姿态分量与平移一样按平面拟合 (货架姿态近乎常量, 拟合即近似 held-constant)。
  - 偏置 offset 为 6 元 (dx,dy,dz,drx,dry,drz): 小量修正下逐元素相加即可; 迁移时把
    offset 播种为 `示教值 − 网格值`, 则算出的位姿精确复现原示教点 (零位移迁移)。
  - 重标 = 只改 3 个角点位姿 (整架随之平移/微旋), 偏置随动; 单库位微调 = 只改其 offset,
    不牵连其它库位。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_POSE_LEN = 6
_MIN_ANCHORS = 3


@dataclass(frozen=True)
class GridAnchor:
    """一个标定角点: 逻辑 (row, col) + 实测 6DOF 位姿 (示教值)。"""

    row: int
    col: int
    pose: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.pose) != _POSE_LEN:
            raise ValueError(f"anchor pose 必须是 {_POSE_LEN} 元, 实际 {len(self.pose)}")


def solve_grid_planes(anchors: list[GridAnchor]) -> list[tuple[float, float, float]]:
    """由角点解出 6 个位姿分量各自的平面系数 (a, b, c): v = a·col + b·row + c。

    3 个角点精确解, >3 个最小二乘 (numpy.linalg.lstsq)。逻辑共线立即抛 ValueError。
    """
    if len(anchors) < _MIN_ANCHORS:
        raise ValueError(f"网格标定需至少 {_MIN_ANCHORS} 个角点, 实际 {len(anchors)}")
    design = np.array([[a.col, a.row, 1.0] for a in anchors], dtype=float)
    if np.linalg.matrix_rank(design) < 3:
        raise ValueError("网格角点在逻辑网格上共线(退化), 无法确定仿射; 请取不共线的 3 角")
    planes: list[tuple[float, float, float]] = []
    for k in range(_POSE_LEN):
        b = np.array([a.pose[k] for a in anchors], dtype=float)
        coef, *_ = np.linalg.lstsq(design, b, rcond=None)
        planes.append((float(coef[0]), float(coef[1]), float(coef[2])))
    return planes


def grid_pose(
    planes: list[tuple[float, float, float]],
    row: int,
    col: int,
    offset: tuple[float, ...] | None = None,
    *,
    ndigits: int | None = 6,
) -> tuple[float, ...]:
    """逻辑 (row, col) + 偏置 → 6DOF 物理位姿。ndigits=None 时不取整 (供播种偏置用)。"""
    off = tuple(offset) if offset is not None else (0.0,) * _POSE_LEN
    if len(off) != _POSE_LEN:
        raise ValueError(f"offset 必须是 {_POSE_LEN} 元, 实际 {len(off)}")
    pose = []
    for k, (a, b, c) in enumerate(planes):
        v = a * col + b * row + c + float(off[k])
        pose.append(round(v, ndigits) if ndigits is not None else v)
    return tuple(pose)


def seed_offset(
    planes: list[tuple[float, float, float]],
    row: int,
    col: int,
    taught_pose: tuple[float, ...],
    *,
    ndigits: int = 6,
) -> list[float]:
    """播种偏置 = 示教值 − 网格标称值 (未取整标称), 使 grid_pose 精确复现示教点。"""
    if len(taught_pose) != _POSE_LEN:
        raise ValueError(f"taught_pose 必须是 {_POSE_LEN} 元, 实际 {len(taught_pose)}")
    nominal = grid_pose(planes, row, col, ndigits=None)
    return [round(taught_pose[k] - nominal[k], ndigits) for k in range(_POSE_LEN)]
