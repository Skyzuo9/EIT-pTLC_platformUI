"""
功能: 检查 GLB 的节点层级与命名情况, 用于确认资产管线各步骤是否保住了语义名称.

命名是否可用是整条管线的生死线: device-manifest 靠节点名/层级路径绑定实时数据,
删减规则与材质规则也全靠名称匹配. 因此每一步产出后都应当用本工具核对一次.

用法:
    python inspect_glb.py work/xxx.raw.glb
    python inspect_glb.py work/xxx.raw.glb --tree --depth 3
    python inspect_glb.py work/xxx.raw.glb --grep zhan_gang

参数: 见 main() 中的 argparse 定义
返回值: 无(打印报告)
"""

from __future__ import annotations

import argparse
import os
import re
from collections import Counter

import pygltflib

# OCCT 为装配实例(NEXT_ASSEMBLY_USAGE_OCCURRENCE)生成的无语义名
NAUO_PATTERN = re.compile(r"^NAUO\d+$", re.IGNORECASE)
# OCCT 导入供应商 STEP 时给未命名实体起的自动名
VENDOR_AUTO = re.compile(r"Open[_ ]CASCADE[_ ]STEP[_ ]translator", re.IGNORECASE)


def load(path: str) -> pygltflib.GLTF2:
    """
    功能: 加载 GLB 文件.
    参数:
        path: GLB 路径
    返回值: pygltflib.GLTF2
    """
    if not os.path.isfile(path):
        raise SystemExit(f"错误: 文件不存在: {path}")
    return pygltflib.GLTF2().load(path)


def classify(name: str) -> str:
    """
    功能: 把节点名归类, 便于统计命名质量.
    参数:
        name: 节点名
    返回值: str, 类别标识
    """
    if not name:
        return "空名"
    if NAUO_PATTERN.match(name):
        return "NAUO 装配实例名(无语义)"
    if VENDOR_AUTO.search(name):
        return "供应商自动名(无语义)"
    return "有语义名"


def build_children_map(gltf: pygltflib.GLTF2) -> dict[int, list[int]]:
    """
    功能: 建立节点索引到子节点索引列表的映射.
    参数:
        gltf: glTF 文档
    返回值: dict[int, list[int]]
    """
    return {i: list(node.children or []) for i, node in enumerate(gltf.nodes or [])}


def find_roots(gltf: pygltflib.GLTF2) -> list[int]:
    """
    功能: 找出所有根节点(未被任何节点引用为子节点的节点).
    参数:
        gltf: glTF 文档
    返回值: list[int], 根节点索引
    """
    child_ids = set()
    for node in gltf.nodes or []:
        child_ids.update(node.children or [])
    return [i for i in range(len(gltf.nodes or [])) if i not in child_ids]


def print_tree(
    gltf: pygltflib.GLTF2,
    children_map: dict[int, list[int]],
    index: int,
    depth: int,
    max_depth: int,
    max_siblings: int,
    prefix: str = "",
) -> None:
    """
    功能: 递归打印节点树.
    参数:
        gltf: glTF 文档
        children_map: 子节点映射
        index: 当前节点索引
        depth: 当前深度
        max_depth: 最大打印深度
        max_siblings: 每层最多打印的兄弟数
        prefix: 缩进前缀
    返回值: None
    """
    node = gltf.nodes[index]
    has_mesh = node.mesh is not None
    marker = "◆" if has_mesh else "○"
    print(f"{prefix}{marker} {node.name or '(无名)'}")

    if depth >= max_depth:
        children = children_map.get(index, [])
        if children:
            print(f"{prefix}   … 还有 {len(children)} 个子节点(已达深度上限)")
        return

    children = children_map.get(index, [])
    shown = children[:max_siblings]
    for child in shown:
        print_tree(gltf, children_map, child, depth + 1, max_depth, max_siblings, prefix + "   ")
    if len(children) > len(shown):
        print(f"{prefix}   … 另有 {len(children) - len(shown)} 个同级节点未显示")


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="检查 GLB 节点命名与层级")
    parser.add_argument("path")
    parser.add_argument("--tree", action="store_true", help="打印节点树")
    parser.add_argument("--depth", type=int, default=3, help="节点树最大深度")
    parser.add_argument("--siblings", type=int, default=8, help="每层最多显示的兄弟节点数")
    parser.add_argument("--grep", default=None, help="按子串筛选节点名(不区分大小写)")
    parser.add_argument("--samples", type=int, default=25, help="每类打印的样例数量")
    args = parser.parse_args()

    gltf = load(args.path)
    nodes = gltf.nodes or []
    size_mb = os.path.getsize(args.path) / 1024 / 1024

    print(f"文件: {args.path} ({size_mb:.2f} MB)")
    print(f"节点 {len(nodes)} / 网格 {len(gltf.meshes or [])} / 材质 {len(gltf.materials or [])}")

    counter = Counter(classify(node.name or "") for node in nodes)
    print("\n=== 命名质量 ===")
    for category, count in counter.most_common():
        print(f"  {category}: {count} ({count / max(len(nodes), 1) * 100:.1f}%)")

    meaningful = [node.name for node in nodes if classify(node.name or "") == "有语义名"]
    if meaningful:
        print(f"\n=== 有语义名样例(共 {len(meaningful)}) ===")
        for name in meaningful[: args.samples]:
            print(f"  {name}")

    if args.grep:
        keyword = args.grep.lower()
        hits = [
            (i, node.name)
            for i, node in enumerate(nodes)
            if node.name and keyword in node.name.lower()
        ]
        print(f"\n=== 匹配 '{args.grep}' 的节点(共 {len(hits)}) ===")
        for index, name in hits[: args.samples]:
            print(f"  [{index}] {name}")

    if args.tree:
        children_map = build_children_map(gltf)
        roots = find_roots(gltf)
        print(f"\n=== 节点树(根节点 {len(roots)} 个, 深度上限 {args.depth}) ===")
        for root in roots[:3]:
            print_tree(gltf, children_map, root, 0, args.depth, args.siblings)


if __name__ == "__main__":
    main()
