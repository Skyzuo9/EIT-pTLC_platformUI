"""
功能: 导出 GLB 顶层装配树及每个装配的世界包围盒, 作为编写 rig_map.yaml(装配归属表)的依据.

为什么需要: 要把整机拆成"工位"级别的语义结构, 先得知道有哪些顶层装配、各自在机器的
哪个位置、多大、含多少几何. 名称给出语义线索, 空间位置给出分区线索, 两者结合才能
可靠地把装配归到对应工位.

用法:
    python dump_hierarchy.py ../work/xxx.raw.glb
    python dump_hierarchy.py ../work/xxx.raw.glb --depth 2 --json out.json

参数: 见 argparse
返回值: 无(打印表格, 可选写 JSON)
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pygltflib


def node_local_matrix(node: pygltflib.Node) -> np.ndarray:
    """
    功能: 求节点的局部变换矩阵(优先用 matrix, 否则由 TRS 合成).
    参数:
        node: glTF 节点
    返回值: np.ndarray, 4x4 行主序矩阵
    """
    if node.matrix:
        # glTF 的 matrix 是列主序, 转成行主序便于用 @ 连乘
        return np.array(node.matrix, dtype=float).reshape(4, 4).T

    matrix = np.eye(4)
    if node.scale:
        matrix = np.diag([*node.scale, 1.0]) @ matrix
    if node.rotation:
        x, y, z, w = node.rotation
        rotation = np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
                [0, 0, 0, 1],
            ]
        )
        matrix = rotation @ matrix
    if node.translation:
        translation = np.eye(4)
        translation[:3, 3] = node.translation
        matrix = translation @ matrix
    return matrix


def mesh_positions_bounds(gltf: pygltflib.GLTF2, mesh_index: int) -> tuple[np.ndarray, np.ndarray] | None:
    """
    功能: 取一个网格的局部包围盒(直接读访问器的 min/max, 无需解码顶点数据).
    参数:
        gltf: glTF 文档
        mesh_index: 网格索引
    返回值: tuple[np.ndarray, np.ndarray] | None, (最小点, 最大点)
    """
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    found = False
    for primitive in gltf.meshes[mesh_index].primitives:
        position_index = primitive.attributes.POSITION
        if position_index is None:
            continue
        accessor = gltf.accessors[position_index]
        if accessor.min and accessor.max:
            lo = np.minimum(lo, np.array(accessor.min, dtype=float))
            hi = np.maximum(hi, np.array(accessor.max, dtype=float))
            found = True
    return (lo, hi) if found else None


def collect(gltf: pygltflib.GLTF2, index: int, matrix: np.ndarray, accumulator: dict) -> None:
    """
    功能: 递归累计一棵子树的世界包围盒、网格数与三角形数.
    参数:
        gltf: glTF 文档
        index: 节点索引
        matrix: 父级累计变换
        accumulator: 输出累加器
    返回值: None
    """
    node = gltf.nodes[index]
    world = matrix @ node_local_matrix(node)

    if node.mesh is not None:
        bounds = mesh_positions_bounds(gltf, node.mesh)
        if bounds is not None:
            lo, hi = bounds
            # 变换包围盒的八个角点, 再重新拟合
            corners = np.array(
                [[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
            )
            transformed = (world @ corners.T).T[:, :3]
            accumulator["lo"] = np.minimum(accumulator["lo"], transformed.min(axis=0))
            accumulator["hi"] = np.maximum(accumulator["hi"], transformed.max(axis=0))
        accumulator["meshes"] += 1
        for primitive in gltf.meshes[node.mesh].primitives:
            if primitive.indices is not None:
                accumulator["triangles"] += gltf.accessors[primitive.indices].count // 3

    for child in node.children or []:
        collect(gltf, child, world, accumulator)


def find_roots(gltf: pygltflib.GLTF2) -> list[int]:
    """
    功能: 找出所有根节点.
    参数:
        gltf: glTF 文档
    返回值: list[int]
    """
    children = set()
    for node in gltf.nodes or []:
        children.update(node.children or [])
    return [i for i in range(len(gltf.nodes or [])) if i not in children]


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="导出 GLB 顶层装配树与包围盒")
    parser.add_argument("path")
    parser.add_argument("--depth", type=int, default=1, help="展开到第几层(1=顶层装配)")
    parser.add_argument("--json", default=None, help="同时写出 JSON")
    args = parser.parse_args()

    if not os.path.isfile(args.path):
        raise SystemExit(f"错误: 文件不存在: {args.path}")

    gltf = pygltflib.GLTF2().load(args.path)
    roots = find_roots(gltf)

    rows: list[dict] = []

    def walk(index: int, matrix: np.ndarray, depth: int) -> None:
        """功能: 逐层展开并记录每个装配的统计. 参数: 索引/父变换/深度. 返回值: None"""
        node = gltf.nodes[index]
        world = matrix @ node_local_matrix(node)
        if depth >= 1:
            accumulator = {
                "lo": np.full(3, np.inf),
                "hi": np.full(3, -np.inf),
                "meshes": 0,
                "triangles": 0,
            }
            collect(gltf, index, matrix, accumulator)
            if accumulator["meshes"] > 0:
                lo, hi = accumulator["lo"], accumulator["hi"]
                rows.append(
                    {
                        "depth": depth,
                        "name": node.name or f"node_{index}",
                        "center": [round(float(v), 3) for v in (lo + hi) / 2],
                        "size": [round(float(v), 3) for v in (hi - lo)],
                        "meshes": accumulator["meshes"],
                        "triangles": accumulator["triangles"],
                    }
                )
        if depth < args.depth:
            for child in node.children or []:
                walk(child, world, depth + 1)

    for root in roots:
        walk(root, np.eye(4), 0)

    rows.sort(key=lambda r: -r["triangles"])

    print(f"文件: {args.path}")
    print(f"顶层装配数: {len(rows)}\n")
    header = f"{'三角形':>9} {'网格':>5}  {'中心 (x,y,z)':<26} {'尺寸 (w,h,d)':<24} 名称"
    print(header)
    print("-" * len(header))
    for row in rows:
        center = ",".join(f"{v:6.2f}" for v in row["center"])
        size = ",".join(f"{v:6.2f}" for v in row["size"])
        print(f"{row['triangles']:>9,} {row['meshes']:>5}  {center:<26} {size:<24} {row['name']}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
        print(f"\nJSON 已写入: {args.json}")


if __name__ == "__main__":
    main()
