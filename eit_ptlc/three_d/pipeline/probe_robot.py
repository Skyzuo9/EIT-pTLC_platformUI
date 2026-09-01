"""
功能: 探查 GLB 里机械臂装配的连杆构成 —— 各子件的世界位置、尺寸与朝向,
      用于推断 6 个关节的顺序与旋转轴, 从而自动铰接.

为什么需要: CAD 导出的装配里, 各连杆是**平级兄弟**, 由绝对变换摆位, 并不体现运动链的
父子关系. 要让它动起来, 必须先判断"谁是 J1、谁是 J2", 而判断依据只能是空间位置 ——
沿运动链从基座往外, 关节模组的位置是单调外推的.

用法:
    python probe_robot.py ../work/xxx.raw.glb --root "DOBOT CR5Model"

参数: 见 argparse
返回值: 无(打印报告 + 可选写 JSON)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(
    0,
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp_servers", "blender_mcp")),
)

import blender_core as core  # noqa: E402

SCRIPT = '''
from mathutils import Vector

load_model(r"{model}")

root = None
for obj in bpy.data.objects:
    if obj.name.startswith({root!r}):
        root = obj
        break
if root is None:
    emit({{"ok": False, "error": "找不到根节点 " + {root!r}}})
    raise SystemExit(0)

def world_bounds(o):
    """功能: 求对象及后代的世界包围盒. 参数: o 对象. 返回值: (lo, hi) 或 None"""
    import math
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    found = False
    def visit(n):
        nonlocal lo, hi, found
        if n.type == "MESH" and len(n.data.vertices):
            for c in n.bound_box:
                w = n.matrix_world @ Vector(c)
                lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
                hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
                found = True
        for ch in n.children:
            visit(ch)
    visit(o)
    return (lo, hi) if found else None

items = []
for child in root.children:
    b = world_bounds(child)
    if b is None:
        continue
    lo, hi = b
    center = (lo + hi) / 2
    size = hi - lo
    tris = 0
    def count(n):
        global tris
        if n.type == "MESH":
            tris += sum(max(len(p.vertices) - 2, 0) for p in n.data.polygons)
        for ch in n.children:
            count(ch)
    count(child)
    items.append({{
        "name": child.name,
        "center": [round(v, 4) for v in center],
        "size": [round(v, 4) for v in size],
        "triangles": tris,
        "children": [c.name for c in child.children],
    }})

rb = world_bounds(root)
emit({{
    "ok": True,
    "root": root.name,
    "root_center": [round(v, 4) for v in ((rb[0] + rb[1]) / 2)] if rb else None,
    "root_size": [round(v, 4) for v in (rb[1] - rb[0])] if rb else None,
    "links": items,
}})
'''


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="探查机械臂连杆构成")
    parser.add_argument("path")
    parser.add_argument("--root", default="DOBOT CR5Model", help="机械臂装配根节点名前缀")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    if not os.path.isfile(args.path):
        raise SystemExit(f"错误: 文件不存在: {args.path}")

    code = core.PRELUDE + SCRIPT.format(
        model=os.path.abspath(args.path).replace("\\", "/"), root=args.root
    )
    result = core.run_script(code, timeout=1800)
    payload = core.extract_json_result(result["stdout"])
    if payload is None:
        print("\n".join(result["stdout"].splitlines()[-30:]))
        raise SystemExit("Blender 未回传结果")
    if not payload.get("ok"):
        raise SystemExit(payload.get("error", "未知错误"))

    print(f"机械臂根节点: {payload['root']}")
    print(f"整体中心: {payload['root_center']}   尺寸: {payload['root_size']}")
    print(f"\n连杆 {len(payload['links'])} 个（Blender 为 Z 轴向上）:")
    print(f"{'中心 (x, y, z)':<30} {'尺寸 (x, y, z)':<28} {'三角形':>8}  名称")
    print("-" * 110)
    # 按高度排序: 运动链从基座往外通常是自下而上, 这个顺序最接近 J1→J6
    for link in sorted(payload["links"], key=lambda x: x["center"][2]):
        center = ", ".join(f"{v:6.3f}" for v in link["center"])
        size = ", ".join(f"{v:6.3f}" for v in link["size"])
        print(f"{center:<30} {size:<28} {link['triangles']:>8}  {link['name']}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"\nJSON 已写入: {args.json}")


if __name__ == "__main__":
    main()
