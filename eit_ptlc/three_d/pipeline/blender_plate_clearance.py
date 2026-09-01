"""
功能: 在 Blender 内部运行的"料仓板净空"实测脚本(不可直接用系统 Python 运行).

由 verify_plate_clearance.py 通过以下方式调用:
    blender --background --python blender_plate_clearance.py -- --job <job.json>

拆两层的理由与 blender_clean 相同: Blender 自带 Python 没有 PyYAML, YAML 解析留在外层.

为什么必须进 Blender: 判据要的是**三角形级**的相交与净空, 而 work/structure.json 只有
世界包围盒 —— 04 步按材质合并之后, 一个 STATIC_MAT_* 块的包围盒能横跨半台机器, 拿它
做遮挡判断等于没判(与 rig_map「灯被合并块连坐」是同一类坑). 逐三角形是唯一说得清的量法.

产出三组数(都随作业单里的每个料仓给一份):
    floorZ      —— 板正下方**最高的静止面**(沿轴向反方向打射线网格取最近命中).
                   前端拿 floorM 夹紧板底, 于是拖轴到行程下限也不会扎穿仓底.
    sweep       —— 沿 range_mm 全程扫板盒 vs 静止几何的最大穿透深度, 供门禁判红.
    ledge       —— 料仓口固定托边顶面的轴向位置(板不被滑车顶着时坐的那圈平板).
                   折成 ledgeAxisMm 后由 manifest 交给前端: 轴低于它时板停在托边、
                   滑车继续走 —— 这是"板堆随滑车穿托边"穿模的对症数据.

"静止"的定义: 不在该料仓滑车(CARRIAGE)子树里的几何. 滑车里的件(玻璃放置板/顶升加强筋
等)与板同步升降, 它们之间的相对关系恒定, 判它们相交没有意义.

参数: 见 parse_args()
返回值: 无(产出 JSON)
"""

from __future__ import annotations

import json
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def log(message: str) -> None:
    """打印带时间戳前缀的日志并立即刷新(Blender 后台模式下 stdout 有缓冲)。"""
    print(f"[blender-clearance] {message}", flush=True)


def parse_args() -> dict:
    """从 `--` 之后的参数里取作业单并载入。"""
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    job_path = None
    for index, value in enumerate(args):
        if value == "--job" and index + 1 < len(args):
            job_path = args[index + 1]
    if not job_path:
        raise SystemExit("缺少 --job <job.json> 参数")
    with open(job_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_model(path: str) -> None:
    """清空场景并导入 GLB。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)


def mesh_objects():
    return [obj for obj in bpy.data.objects if obj.type == "MESH" and obj.data]


def subtree_names(root) -> set[str]:
    """节点及其全部后代的名字集合。"""
    names, stack = set(), [root]
    while stack:
        node = stack.pop()
        names.add(node.name)
        stack.extend(node.children)
    return names


def find_object(name: str):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise SystemExit(f"GLB 里没有节点: {name}")
    return obj


def ancestor_matching(obj, prefix: str):
    """向上找第一个名字以 prefix 开头的祖先(滑车 CARRIAGE / CARRIAGE.001 …)。"""
    cursor = obj.parent
    while cursor is not None:
        if cursor.name.startswith(prefix):
            return cursor
        cursor = cursor.parent
    return None


def world_vertices(obj) -> list[Vector]:
    """obj 及其后代的全部顶点(世界系)。"""
    out, stack = [], [obj]
    while stack:
        node = stack.pop()
        if node.type == "MESH" and node.data and len(node.data.vertices):
            matrix = node.matrix_world
            out.extend([matrix @ vertex.co for vertex in node.data.vertices])
        stack.extend(node.children)
    return out


def bounds(points: list[Vector]) -> tuple[Vector, Vector]:
    low = Vector((min(p[i] for p in points) for i in range(3)))
    high = Vector((max(p[i] for p in points) for i in range(3)))
    return low, high


#: 板中面取样点数(把交线离散成若干点后逐点判"离板沿多远")。
_SLICE_SAMPLES = 9


def slice_intrusion(tri, center: Vector, half: Vector, axis: int) -> float:
    """静止三角形与**板中面**的交线, 伸进板轮廓内最深多少(米)。

    为什么量"离板沿多远"而不是"交叠了多少": 要判红的分界是**看不看得见**。
      · 板进出仓口时必然与仓壁擦肩 —— 交线贴着板沿, 离沿零点几毫米, 眼睛看不出来;
      · 仓底那个黑色件捅穿板面 —— 交线落在板正中, 离沿几十毫米, 一眼就是穿模。
    单看三角形个数分不开这两者(擦边同样能数出几十个面)。

    也不能用"三角形包围盒 × 板盒的最小轴向交叠": 平面三角形沿自身法向的包围盒厚度是 0,
    于是任何轴对齐的壁面都会被算成 0 深度 —— 首版就是这么把 527 个面的真穿模量成
    0.21mm 的(2026-08-05)。交线取样没有这种退化。
    """
    plane_axes = [k for k in range(3) if k != axis]
    signed = [point[axis] - center[axis] for point in tri]
    crossings = []
    for i in range(3):
        j = (i + 1) % 3
        if abs(signed[i]) < 1e-9:
            crossings.append(tri[i])
        if (signed[i] > 0.0) != (signed[j] > 0.0) and abs(signed[i] - signed[j]) > 1e-12:
            crossings.append(tri[i].lerp(tri[j], signed[i] / (signed[i] - signed[j])))
    if len(crossings) < 2:
        return 0.0

    start, end = crossings[0], crossings[-1]
    best = 0.0
    for step in range(_SLICE_SAMPLES):
        point = start.lerp(end, step / (_SLICE_SAMPLES - 1))
        # 到最近那条板沿的距离; 落在板外时为负
        inside = min(half[k] - abs(point[k] - center[k]) for k in plane_axes)
        best = max(best, inside)
    return max(best, 0.0)


#: 托边探针的射线起点抬升量(米, 相对 CAD 停靠位板底)。托边顶面在板底上方 ~19~29mm
#: (feed/waste 不同), 60mm 有裕量又足够局部 —— 不会打到料仓上方行程走廊里的结构
#: (那段走廊已被 sweep 证明只有亚毫米擦边)。
_LEDGE_PROBE_LIFT_M = 0.060

#: 托边环带三圈采样的边内缩量(米)。外缘缩 4mm 避开与板沿零点几毫米擦肩的仓壁,
#: 内缘 21mm 不超过托边实测深度 25mm —— 三圈覆盖托边环的外/中/内。
_LEDGE_RING_INSETS_M = (0.004, 0.0125, 0.021)
_LEDGE_RING_SIDE_SAMPLES = 6

#: 命中点离最高命中 ≤ 此值(米)算"同一托边平面"; 更低的命中是从螺孔漏下去打到深处的,
#: 不参与 spread 统计。
_LEDGE_PLANE_TOL_M = 1.5e-3


def ledge_probe(bvh, center: Vector, low: Vector, high: Vector,
                direction: Vector, thickness: float):
    """沿板足迹外圈环带从上往下打射线, 量料仓口固定托边顶面的轴向位置(相对板心, 米)。

    环带 = 板 200mm 足迹的外圈 25mm(开口比板四周各内收 25mm, 见 verify 的 LEDGE_HANDOFF),
    环带正下方只有托边平板, 板上行走廊在其上方是空的 —— 因此"起点抬 60mm、向下打、
    取最高命中"就是托边顶面。取 max 而不是均值: 个别射线会从托边螺孔漏下去命中更低的面,
    max + 平面聚类把它们滤掉; 偏差方向是保守的(板停得高, 不穿模)。

    返回 (托边轴向偏移, 平面内命中数, 平面内 spread, 总命中数); 一条都没命中返回 None
    (= 该料仓没有托边, 调用方跳过相关字段)。
    """
    if bvh is None:
        return None
    plane_axes = [k for k in range(3) if abs(direction[k]) < 0.5][:2]
    origin_lift = direction * (-thickness / 2.0 + _LEDGE_PROBE_LIFT_M)
    ray_length = _LEDGE_PROBE_LIFT_M + 0.14
    hits: list[float] = []
    for inset in _LEDGE_RING_INSETS_M:
        rect_low = [low[k] + inset for k in plane_axes]
        rect_high = [high[k] - inset for k in plane_axes]
        if rect_low[0] >= rect_high[0] or rect_low[1] >= rect_high[1]:
            continue
        corners = [
            (rect_low[0], rect_low[1]), (rect_high[0], rect_low[1]),
            (rect_high[0], rect_high[1]), (rect_low[0], rect_high[1]),
        ]
        for side in range(4):
            begin, end = corners[side], corners[(side + 1) % 4]
            for step in range(_LEDGE_RING_SIDE_SAMPLES):
                fraction = step / _LEDGE_RING_SIDE_SAMPLES
                point = Vector(center)
                point[plane_axes[0]] = begin[0] + (end[0] - begin[0]) * fraction
                point[plane_axes[1]] = begin[1] + (end[1] - begin[1]) * fraction
                hit = bvh.ray_cast(point + origin_lift, -direction, ray_length)
                if hit and hit[0] is not None:
                    hits.append(float((hit[0] - center).dot(direction)))
    if not hits:
        return None
    top = max(hits)
    plane = [value for value in hits if top - value <= _LEDGE_PLANE_TOL_M]
    return top, len(plane), top - min(plane), len(hits)


def region_bvh(exclude: set[str], low: Vector, high: Vector):
    """把区域内的静止三角形收成一棵 BVH。

    两级筛: 先用对象整体包围盒粗筛(便宜), 再逐三角形精筛 —— 合并块的包围盒很大,
    只有精筛这一步才把"块里真正落在这一小片的那几十个面"挑出来。
    """
    verts: list[Vector] = []
    faces: list[tuple[int, int, int]] = []
    for obj in mesh_objects():
        if obj.name in exclude:
            continue
        mesh = obj.data
        mesh.calc_loop_triangles()
        world = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
        if not world:
            continue
        obj_low, obj_high = bounds(world)
        if any(obj_high[i] < low[i] or obj_low[i] > high[i] for i in range(3)):
            continue
        keep: dict[int, int] = {}
        for triangle in mesh.loop_triangles:
            indices = triangle.vertices
            if all(any(world[i][k] < low[k] or world[i][k] > high[k] for k in range(3))
                   for i in indices):
                continue
            face = []
            for index in indices:
                if index not in keep:
                    keep[index] = len(verts)
                    verts.append(world[index])
                face.append(keep[index])
            faces.append(tuple(face))
    if not faces:
        return None, [], []
    return BVHTree.FromPolygons(verts, faces), verts, faces


def box_bvh(center: Vector, size: Vector) -> BVHTree:
    """一个轴对齐长方体的 BVH(12 个三角形)。"""
    half = size / 2.0
    corners = [
        Vector((center.x + sx * half.x, center.y + sy * half.y, center.z + sz * half.z))
        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
    ]
    faces = [
        (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5),
        (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),
    ]
    return BVHTree.FromPolygons(corners, faces)


def gltf_to_blender(vec: Vector) -> Vector:
    """glTF(Y 朝上) 的方向 -> Blender(Z 朝上) 的方向。

    ⚠ 漏了这一步会静默把"竖直轴"当成水平轴: rig_map 的 axis: [0,1,0] 在 Blender 里
    读成 +Y(往机器后方), 于是地板射线横着打、扫掠沿着错的方向走, 全程数字都是假的
    (2026-08-05 首版就栽在这里 —— 净空量出 56mm、废板仓 121 条射线一条都没命中)。

    导入器把整场从 Y-up 转成 Z-up, 相当于对每个节点做相似变换 M_b = C·M_g·C⁻¹。
    于是 glTF 父空间里的方向 d 在 Blender 父空间里就是 C·d, 再乘父级世界旋转即得世界向。
    """
    return Vector((vec.x, -vec.z, vec.y))


def axis_world_direction(axis_node, axis_vec: list[float], sign: float) -> Vector:
    """镜像 MachineStateDriver.setAxisMm 的方向语义。

    前端写的是 `node.position = base + direction * offset`, 而 position 是**父空间**量,
    所以世界方向 = 父级世界旋转 ∘ axis。sign 与 offset 同号折进这里。
    """
    local = gltf_to_blender(Vector(axis_vec).normalized()) * sign
    parent = axis_node.parent
    if parent is None:
        return local.normalized()
    return (parent.matrix_world.to_3x3() @ local).normalized()


def measure(job: dict) -> dict:
    load_model(job["model"])
    step_mm = float(job.get("sweepStepMm", 5.0))
    results = []

    for spec in job["magazines"]:
        template = find_object(spec["template"])
        carriage = ancestor_matching(template, spec.get("carriagePrefix", "CARRIAGE"))
        if carriage is None:
            raise SystemExit(f"{spec['id']}: {spec['template']} 之上找不到 CARRIAGE 滑车祖先")
        axis_node = ancestor_matching(template, spec.get("axisPrefix", "AXIS_"))
        if axis_node is None:
            raise SystemExit(f"{spec['id']}: {spec['template']} 之上找不到 AXIS_ 轴节点")

        points = world_vertices(template)
        if not points:
            raise SystemExit(f"{spec['id']}: {spec['template']} 没有几何")
        low, high = bounds(points)
        center = (low + high) / 2.0
        size = high - low
        direction = axis_world_direction(axis_node, spec["axisVec"], float(spec.get("sign", 1)))

        exclude = subtree_names(carriage)
        # 区域取板足迹外扩一圈 + 轴向上下各留出整段行程, 免得扫到一半出界
        margin = Vector((0.03, 0.03, 0.03))
        travel = [
            (float(spec["rangeMm"][0]) - float(spec["zeroOffsetMm"])) / 1000.0,
            (float(spec["rangeMm"][1]) - float(spec["zeroOffsetMm"])) / 1000.0,
        ]
        span = [direction * travel[0], direction * travel[1]]
        region_low = Vector((
            min(low[i] + span[0][i], low[i] + span[1][i], low[i]) - margin[i] for i in range(3)))
        region_high = Vector((
            max(high[i] + span[0][i], high[i] + span[1][i], high[i]) + margin[i] for i in range(3)))
        bvh, region_verts, region_faces = region_bvh(exclude, region_low, region_high)
        triangle_count = len(region_faces)

        # -- 地板: 沿 −direction 打射线网格, 取最近命中里"最高"(最靠近板)的那一个 ------
        floor_hits = []
        grid = int(job.get("floorGrid", 11))
        # 轴向上的板厚(direction 轴对齐时 = size 在该轴的分量)
        thickness = size.dot(Vector((abs(direction.x), abs(direction.y), abs(direction.z))))
        # 射线起点压到板底面再往下让 0.5mm, 免得起点正好落在自己的底面上打不出去
        origin_offset = direction * (-thickness / 2.0 - 5e-4)
        for i in range(grid):
            for j in range(grid):
                # 在板面内两个方向上撒点(直接用世界 AABB 的两条非轴向边)
                fraction = [i / (grid - 1), j / (grid - 1)]
                point = Vector(center)
                axes = [k for k in range(3) if abs(direction[k]) < 0.5]
                for slot, k in enumerate(axes[:2]):
                    point[k] = low[k] + (high[k] - low[k]) * fraction[slot]
                hit = bvh.ray_cast(point + origin_offset, -direction,
                                   abs(travel[0]) + abs(travel[1]) + 0.5) if bvh else None
                if hit and hit[0] is not None:
                    floor_hits.append(float((hit[0] - center).dot(direction)))

        # 板心到地板的**有符号轴向距离**(负值 = 地板在板下方)
        floor_offset = max(floor_hits) if floor_hits else None

        # -- 托边: 板不被滑车顶着时坐的那圈固定平板(见 verify 的 LEDGE_HANDOFF) ------
        ledge = ledge_probe(bvh, center, low, high, direction, thickness)

        # -- 行程扫掠: 逐三角形量交线伸进板轮廓的深度 ---------------------------
        # box_bvh 造的是**世界轴对齐**长方体, 只有轴向也轴对齐时才成立; 不成立就明说,
        # 别默默算一个偏大的盒子(与 measurePlateAnchor 头注释第 2 条同款教训)。
        axis_index = max(range(3), key=lambda k: abs(direction[k]))
        if any(abs(direction[k]) > 1e-6 for k in range(3) if k != axis_index):
            raise SystemExit(
                f"{spec['id']}: 轴向 {tuple(round(v, 6) for v in direction)} 不是世界轴对齐的, "
                "板盒不能再用轴对齐长方体近似 —— 需要改走 OBB"
            )

        sweep = []
        half = size / 2.0
        value = float(spec["rangeMm"][0])
        stop = float(spec["rangeMm"][1])
        while value <= stop + 1e-9:
            offset = (value - float(spec["zeroOffsetMm"])) / 1000.0
            probe_center = center + direction * offset
            overlaps = bvh.overlap(box_bvh(probe_center, size)) if bvh else []
            if overlaps:
                depth = 0.0
                for static_index, _probe_index in overlaps:
                    triangle = tuple(region_verts[i] for i in region_faces[static_index])
                    depth = max(depth, slice_intrusion(triangle, probe_center, half, axis_index))
                sweep.append({
                    "axisMm": round(value, 3),
                    "tris": len(overlaps),
                    "depthMm": round(depth * 1000.0, 4),
                })
            value += step_mm

        entry = {
            "id": spec["id"],
            "axisId": spec.get("axisId"),
            "template": spec["template"],
            "carriage": carriage.name,
            "axisNode": axis_node.name,
            "staticTrisInRegion": triangle_count,
            "plateSizeMm": [round(v * 1000, 3) for v in size],
            "plateCenterWorld": [round(v, 8) for v in center],
            "axisWorldDir": [round(v, 8) for v in direction],
            "floorRayHits": len(floor_hits),
            "overlaps": sweep,
        }
        if floor_offset is not None:
            # 板底面允许到达的最低轴向位置(相对 CAD 停靠态板心, 米)
            entry["floorOffsetM"] = round(floor_offset, 8)
            entry["clearanceMm"] = round((-floor_offset - thickness / 2.0) * 1000.0, 3)
            entry["minAxisMm"] = round(
                (floor_offset + thickness / 2.0) * 1000.0 + float(spec["zeroOffsetMm"]), 3)
        if ledge is not None:
            ledge_offset, ledge_hits, ledge_spread, ledge_total = ledge
            # 板底面正好落在托边顶面时的轴向位置(与 minAxisMm 同一代数)
            entry["ledgeOffsetM"] = round(ledge_offset, 8)
            entry["ledgeAxisMm"] = round(
                (ledge_offset + thickness / 2.0) * 1000.0 + float(spec["zeroOffsetMm"]), 3)
            entry["ledgeRayHits"] = ledge_hits
            entry["ledgeSpreadMm"] = round(ledge_spread * 1000.0, 4)
            if ledge_spread > 1e-3 or ledge_hits < 8:
                log(f"{spec['id']}: 托边命中异常(平面内 {ledge_hits}/{ledge_total} 条, "
                    f"spread {ledge_spread * 1000.0:.2f}mm) —— 仍取最高命中为托边顶面")
        results.append(entry)
        log(f"{spec['id']}: 静止面 {triangle_count} 三角形 · 地板命中 {len(floor_hits)}/{grid * grid}"
            f" · 净空 {entry.get('clearanceMm', 'n/a')}mm · 托边交接 {entry.get('ledgeAxisMm', 'n/a')}mm"
            f" · 越界档位 {len(sweep)} 个")

    return {"model": job["model"], "sweepStepMm": step_mm, "magazines": results}


def main() -> None:
    job = parse_args()
    report = measure(job)
    with open(job["output"], "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    log(f"已写入: {job['output']}")


if __name__ == "__main__":
    main()
