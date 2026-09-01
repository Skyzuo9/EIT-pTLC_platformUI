"""
功能: 找出远离设备主体的游离几何体.

为什么需要: 少数残留零件(例如未删净的线槽、误建的参考体、导入产生的空壳)可能落在
离设备很远的位置. 它们在画面上几乎看不见, 却会把整机包围盒撑大, 进而让相机自动
取景时被迫拉远, 白白浪费大半个屏幕. 本工具按"到主体中位数中心的距离"排序, 把嫌疑
对象列出来, 便于补进 prune_list 或单独处理.

用法:
    python find_outliers.py ../work/xxx.raw.glb
    python find_outliers.py ../work/xxx.raw.glb --top 30

参数: 见 argparse
返回值: 无(打印报告)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp", "blender_mcp")))

import blender_core as core  # noqa: E402

SCRIPT = '''
from mathutils import Vector
import statistics

load_model(r"{model}")

objs = mesh_objects()
if not objs:
    emit({{"ok": False, "error": "没有网格对象"}})
    raise SystemExit(0)

def world_center(o):
    """功能: 求对象包围盒的世界坐标中心. 参数: o 对象. 返回值: Vector"""
    corners = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return (lo + hi) / 2, lo, hi

info = []
for o in objs:
    center, lo, hi = world_center(o)
    info.append((o, center, lo, hi))

# 用中位数而不是平均值定位主体中心: 中位数不受少数极端离群值影响
mx = statistics.median([i[1].x for i in info])
my = statistics.median([i[1].y for i in info])
mz = statistics.median([i[1].z for i in info])
median_center = Vector((mx, my, mz))

rows = []
for o, center, lo, hi in info:
    rows.append({{
        "name": o.name,
        "distance": round((center - median_center).length, 3),
        "center": [round(v, 3) for v in center],
        "size": [round(v, 3) for v in (hi - lo)],
        "polygons": len(o.data.polygons),
    }})
rows.sort(key=lambda r: -r["distance"])

# 整体包围盒, 以及剔除最远的 N 个之后的包围盒, 用于评估"删掉它们能收窄多少"
def bounds(subset):
    """功能: 求一批对象的整体包围盒尺寸. 参数: subset 行列表. 返回值: list[float]"""
    if not subset:
        return [0, 0, 0]
    lo = [min(r["center"][i] - r["size"][i] / 2 for r in subset) for i in range(3)]
    hi = [max(r["center"][i] + r["size"][i] / 2 for r in subset) for i in range(3)]
    return [round(hi[i] - lo[i], 3) for i in range(3)]

emit({{
    "ok": True,
    "objects": len(rows),
    "median_center": [round(v, 3) for v in median_center],
    "bounds_all": bounds(rows),
    "bounds_drop_5": bounds(rows[5:]),
    "bounds_drop_20": bounds(rows[20:]),
    "bounds_drop_50": bounds(rows[50:]),
    "farthest": rows[:{top}],
}})
'''


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="查找远离主体的游离几何体")
    parser.add_argument("path")
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()

    if not os.path.isfile(args.path):
        raise SystemExit(f"错误: 文件不存在: {args.path}")

    code = core.PRELUDE + SCRIPT.format(
        model=os.path.abspath(args.path).replace("\\", "/"), top=args.top
    )
    result = core.run_script(code, timeout=1800)
    payload = core.extract_json_result(result["stdout"])
    if payload is None:
        print("\n".join(result["stdout"].splitlines()[-30:]))
        raise SystemExit("Blender 未回传结果")

    print(f"对象数: {payload['objects']}")
    print(f"主体中心(中位数): {payload['median_center']}")
    print(f"整体包围盒        : {payload['bounds_all']}")
    print(f"剔除最远 5 个后   : {payload['bounds_drop_5']}")
    print(f"剔除最远 20 个后  : {payload['bounds_drop_20']}")
    print(f"剔除最远 50 个后  : {payload['bounds_drop_50']}")
    print(f"\n最远的 {len(payload['farthest'])} 个对象:")
    print(f"{'距离(m)':>9}  {'面数':>7}  {'尺寸(m)':<26} 名称")
    for row in payload["farthest"]:
        size = "×".join(f"{v:g}" for v in row["size"])
        print(f"{row['distance']:>9.3f}  {row['polygons']:>7}  {size:<26} {row['name']}")


if __name__ == "__main__":
    main()
