"""
功能: 在 Blender 内部运行的模型清理/重组/赋材质脚本(不可直接用系统 Python 运行).

由 03_clean_model.py 通过以下方式调用:
    blender --background --python blender_clean.py -- --job <job.json>

之所以拆成两层: Blender 自带的 Python 没有 PyYAML, 因此把 YAML 配置的解析留在外层,
本脚本只吃一份合并好的 JSON 作业单, 保持 Blender 环境零依赖.

处理流程:
    导入 GLB -> 单位归一 -> 按规则删减 -> 可选减面 -> 赋 PBR 材质
    -> (full 阶段)按 rig_map 重组语义层级并设置轴枢轴 -> 按材质合并 -> 导出 GLB

参数: 见 parse_args()
返回值: 无(产出 GLB + 统计 JSON)
"""

from __future__ import annotations

import functools
import json
import math
import os
import re
import sys
import time
import zlib

import bmesh
import bpy
import numpy as np  # Blender 自带 numpy; 孔阵实测的顶点批处理与圆拟合用
from mathutils import Euler, Matrix, Quaternion, Vector


def log(message: str) -> None:
    """
    功能: 打印带时间戳的日志并立即刷新(Blender 后台模式下 stdout 有缓冲).
    参数:
        message: 日志内容
    返回值: None
    """
    print(f"[blender {time.strftime('%H:%M:%S')}] {message}", flush=True)


def fail(message: str) -> None:
    """
    功能: 硬失败退出(非零码), 供显式名单/断言类校验用.

    此前模块级并没有这个函数 —— _translate_world 的失败路径实际是 NameError
    (照样崩, 但报错文案丢了), 2026-08-06 随座位过继一起补正.

    参数:
        message: 失败原因
    返回值: 无(必抛)
    """
    raise SystemExit(message)


def parse_args() -> dict:
    """
    功能: 解析 "--" 之后的命令行参数, 读取作业单 JSON.
    参数: 无(读 sys.argv)
    返回值: dict, 作业单内容
    """
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


# ---------------------------------------------------------------------------
# 场景准备
# ---------------------------------------------------------------------------


def reset_scene() -> None:
    """功能: 清空默认场景(去掉自带的立方体/相机/灯). 参数: 无. 返回值: None"""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path: str) -> None:
    """
    功能: 导入 GLB 文件.
    参数:
        path: GLB 绝对路径
    返回值: None
    """
    log(f"导入 GLB: {path} ({os.path.getsize(path) / 1024 / 1024:.1f} MB)")
    started = time.time()
    bpy.ops.import_scene.gltf(filepath=path)
    log(f"导入完成, 耗时 {time.time() - started:.1f}s; 对象数 {len(bpy.data.objects)}")


def mesh_objects() -> list:
    """
    功能: 取当前场景中所有网格对象.
    参数: 无
    返回值: list[bpy.types.Object]
    """
    return [obj for obj in bpy.data.objects if obj.type == "MESH"]


def scene_bounds() -> tuple[Vector, Vector]:
    """
    功能: 计算整个场景所有网格的世界坐标包围盒.
    参数: 无
    返回值: tuple[Vector, Vector], (最小点, 最大点)
    """
    lo = Vector((math.inf, math.inf, math.inf))
    hi = Vector((-math.inf, -math.inf, -math.inf))
    for obj in mesh_objects():
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            lo.x, lo.y, lo.z = min(lo.x, world.x), min(lo.y, world.y), min(lo.z, world.z)
            hi.x, hi.y, hi.z = max(hi.x, world.x), max(hi.y, world.y), max(hi.z, world.z)
    return lo, hi


def normalize_units() -> dict:
    """
    功能: 把模型单位归一到米.

    CAD 中性格式一律以毫米建模, 转出的 GLB 里 1 单位 = 1 毫米; 而 Blender 与 glTF 的
    约定单位是米. 若不归一, 一台 3 米的设备在场景里会有 3000 单位大, 后续相机裁剪面、
    减面阈值、导出精度都会失真.

    参数: 无
    返回值: dict, 含 scale / diagonal_before / diagonal_after
    """
    lo, hi = scene_bounds()
    diagonal = (hi - lo).length
    scale = 0.001 if diagonal > 100 else 1.0

    if scale != 1.0:
        log(f"检测到毫米单位(对角线 {diagonal:.1f}), 统一缩放 ×{scale}")
        for obj in bpy.data.objects:
            if obj.parent is None:
                obj.scale *= scale
                obj.location *= scale
        bpy.context.view_layer.update()

    lo2, hi2 = scene_bounds()
    return {
        "scale": scale,
        "diagonal_before": round(diagonal, 3),
        "diagonal_after": round((hi2 - lo2).length, 3),
        "size_m": [round(v, 3) for v in (hi2 - lo2)],
    }


# ---------------------------------------------------------------------------
# 删减
# ---------------------------------------------------------------------------


def compile_patterns(patterns: list[str]) -> list:
    """
    功能: 把字符串模式编译为不区分大小写的正则.
    参数:
        patterns: 模式列表
    返回值: list[re.Pattern]
    """
    compiled = []
    for pattern in patterns or []:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            log(f"警告: 忽略非法正则 {pattern!r} ({exc})")
    return compiled


# 中文对象名 -> 拼音 slug 的别名表, 由 03 步经作业单传入(见 set_name_aliases).
# Blender 自带的 Python 没有 pypinyin, 转换只能在外面做.
_NAME_ALIASES: dict[str, str] = {}


def set_name_aliases(aliases: dict[str, str] | None) -> int:
    """
    功能: 装入"中文名 -> 拼音 slug"的别名表.
    参数:
        aliases: 03 步算好的映射; None 或空表示不用别名
    返回值: int, 装入的条目数
    """
    _NAME_ALIASES.clear()
    if aliases:
        _NAME_ALIASES.update(aliases)
    name_variants.cache_clear()
    return len(_NAME_ALIASES)


@functools.lru_cache(maxsize=8192)
def name_variants(name: str) -> tuple[str, ...]:
    """
    功能: 给一个对象名列出所有该参与匹配的写法.

    模型有两种来源, 命名风格不同:
        走 STEP  -> 01 步把中文转成了拼音 slug, 如 `zhan_gang_zhu_she_beng`
        原生 GLB -> SolidWorks 直接给出中文实例名, 如 `展缸注射泵总装-1`
    而 prune_list.yaml / rig_map.yaml 里积累的几十条规则全是按拼音写的.
    与其重写规则(或把刚保住的中文可读性再转回拼音), 不如匹配时两种写法都试一遍 ——
    旧规则继续生效, 新规则用中文或拼音都行, 而模型里的名字保持中文最便于人看.

    参数:
        name: 对象名
    返回值: tuple[str, ...], 去重后的候选写法
    """
    base = _base_name(name)
    variants = {name, base}
    for key in (name, base):
        alias = _NAME_ALIASES.get(key)
        if alias:
            variants.add(alias)
    return tuple(v for v in variants if v)


def matches_any(name: str, patterns: list) -> bool:
    """
    功能: 判断名称是否命中任一模式(原名与拼音写法都试).
    参数:
        name: 对象名
        patterns: 已编译的正则列表
    返回值: bool
    """
    candidates = name_variants(name)
    return any(pattern.search(c) for pattern in patterns for c in candidates)


def _base_name(name: str) -> str:
    """
    功能: 去掉 Blender 导入时为重名对象追加的 .001 后缀.

    工作台里点选的是 GLB 里的原始节点名, 而 Blender 导入同名对象时会自动改名,
    两边对不上就会漏删. 比对时统一剥掉后缀.

    参数:
        name: 对象名
    返回值: str, 去掉数字后缀的基础名
    """
    return re.sub(r"\.\d{3}$", "", name)


def _collect_subtree_names(obj: Any) -> set[str]:
    """
    功能: 收集一个对象及其全部后代的基础名.
    参数:
        obj: 对象
    返回值: set[str]
    """
    names = {_base_name(obj.name)}
    for child in obj.children:
        names |= _collect_subtree_names(child)
    return names


def _norm(name: str) -> str:
    """功能: 每个空白字符→一个下划线, 精确复刻 three.js 的节点名消毒. 参数: name. 返回值: str"""
    # 注意不能用 \s+ 折叠: 两个空格在 three 里是两个下划线, 折叠成一个就又对不上了(踩过)
    return re.sub(r"\s", "_", name)


def restore_missing_geometry(rules: list) -> dict:
    """
    功能: 用单件导出的 GLB 素材, 把"装配导出丢了几何的零件"补回空节点位置.

    为什么需要这一步(2026-08-02 上样两个同步带惰轮丢失一案):
        SolidWorks XR 导出器在**装配**上下文对个别零件只写出带变换的空节点、不给
        网格; 同一个零件**单件导出**却完全正常. EBF41-S3M150 实测如此(它是
        0 实体 + 3 曲面体, 试过 InsertSewRefSurface 的三组参数都缝不成实体).
        结果是那两个轮子在整机 GLB 里只剩空节点, 04 步再把无几何空节点剪掉,
        孪生里就彻底没有了 —— 用户看到的就是"上样模块少两个轴承".

    对位为什么天然成立: 素材几何在零件原点坐标系(单件 GLB 根变换是单位阵),
    而空节点保留着完整的装配变换; 因此把素材挂到空节点下、局部变换取单位阵,
    世界位姿就与零件正常导出时一致(已用前后渲染对比核对).

    补进来的对象**继承空节点的名字并取代它**(而不是做成子节点), 这样下游
    按名字工作的一切(materials 规则/part_overrides/rig_map 的滑车成员)
    与"零件本来就导出成功"时完全同构, 不需要为它开特例.

    参数:
        rules: 规则表, 每项 {node_prefix, part_glb, note}; part_glb 须为绝对路径
    返回值: dict, 含每条规则补了几个、总数与跳过原因
    """
    # 前缀冲突预检: 供应商件名极易互为前缀(如 `…133.1.1.1.1-1` 与 `…133.1.1.1.10-1`),
    # 串了规则就会给零件套上别人的几何, 且渲染出来不一定看得出来 —— 必须提前拦住.
    claims: dict[str, list[str]] = {}
    for rule in rules or []:
        prefix = rule.get("node_prefix") or ""
        if not prefix:
            continue
        for obj in bpy.data.objects:
            if obj.type == 'EMPTY' and _base_name(obj.name).startswith(prefix):
                claims.setdefault(obj.name, []).append(prefix)
    disputed = {k: v for k, v in claims.items() if len(v) > 1}
    if disputed:
        lines = [f"  {k} <- {v}" for k, v in sorted(disputed.items())[:10]]
        raise SystemExit(
            "补几何规则前缀冲突, 同一空节点被多条规则认领:\n" + "\n".join(lines)
            + "\n把 node_prefix 写得更长(带上实例号 -N)即可区分"
        )

    detail = []
    total = 0
    for rule in rules or []:
        prefix = rule.get("node_prefix") or ""
        asset = rule.get("part_glb") or ""
        rec = {"node_prefix": prefix, "part_glb": asset, "filled": 0}
        if not prefix or not asset:
            rec["skipped"] = "规则缺 node_prefix 或 part_glb"
            detail.append(rec)
            continue
        if not os.path.isfile(asset):
            # 素材缺失必须报错而不是静默跳过: 否则零件又会无声消失一次
            raise SystemExit(f"补几何素材不存在: {asset}(规则 {prefix})")

        slots = [o for o in bpy.data.objects
                 if o.type == 'EMPTY' and _base_name(o.name).startswith(prefix)]
        if not slots:
            rec["skipped"] = "没有匹配的空节点(零件可能已能正常导出)"
            detail.append(rec)
            continue

        known = {o.name for o in bpy.data.objects}
        bpy.ops.import_scene.gltf(filepath=asset)
        fresh = [o for o in bpy.data.objects if o.name not in known]
        donor = next((o for o in fresh if o.type == 'MESH'), None)
        for extra in fresh:                       # 素材自带的相机/空节点一律丢弃
            if extra is not donor:
                bpy.data.objects.remove(extra, do_unlink=True)
        if donor is None:
            raise SystemExit(f"补几何素材里没有网格: {asset}")

        for slot in slots:
            name = slot.name
            parent = slot.parent
            matrix = slot.matrix_world.copy()
            children = list(slot.children)

            copy = donor.copy()
            copy.data = donor.data                # 共享网格数据: 多实例不增内存
            bpy.context.scene.collection.objects.link(copy)
            copy.parent = parent
            for child in children:                # 空节点若挂着子件, 一并转到新对象下
                child.parent = copy
            copy.matrix_world = matrix

            bpy.data.objects.remove(slot, do_unlink=True)
            copy.name = name                      # 删掉占名的空节点后才改得成原名
            rec["filled"] += 1
            total += 1

        bpy.data.objects.remove(donor, do_unlink=True)
        detail.append(rec)

    # 依赖图不刷新的话, 后续步骤读到的 matrix_world 还是旧值(踩过: 读出全 0)
    bpy.context.view_layer.update()
    log(f"补几何: 共 {total} 个空节点被替换为真实网格")
    for rec in detail:
        note = rec.get("skipped") or f"补了 {rec['filled']} 个"
        log(f"  {rec['node_prefix']}: {note}")
    return {"total": total, "rules": detail}


def prune_verdict(config: dict) -> dict:
    """
    功能: 只裁决"哪些对象会被删减", 不动场景.

    从 prune() 里抽出来的原因: 装配工作台要在**未删减**的 raw.glb 上把"会被删掉的
    零件"标红, 早先那是浏览器里另写一份正则/尺寸判定(workbench/pruneEval.js), 与本
    函数漂移出四类错判 —— 拼音别名表覆盖不同(管线用 pypinyin 现算全模型, 浏览器只
    有 309 行 STEP 时代产品名表, `zhi_shi_deng` 这类 keep 规则永远命不中)、尺寸口径
    一个取零件局部包围盒一个取子树世界 AABB、管线在 prune **之后**才造的合成零件
    (注射泵指示灯等)被拿去判删、region_delete 的面级删除按节点粒度根本表达不了.
    现在两边共用这一份裁决: 正式删减走 prune() -> 本函数 -> 执行; raw 阶段只调本
    函数, 结果写成 work/prune_preview.json 交给工作台渲染.

    裁决与执行分开是安全的: 本函数唯一会被"边判边删"影响的输入是 obj.children
    (非网格那轮用它跳过装配节点), 而删除只发生在无子级的对象上, 不会让任何别的
    对象改变名字、包围盒或显式名单归属 —— 先全判再全删与原来逐个删等价.

    调用约定与 prune() 相同: 必须在 normalize_units() 之后调用, 归一后场景恒为米.

    参数:
        config: prune_list 配置
    返回值: dict, 形如
        {"delete": [{"name": 对象名, "reason": "explicit|pattern|size|nonmesh"}, ...],
         "kept_explicit": [对象名, ...], "explicit_missed": [...], "min_dimension_m": float}
        name 一律用 Blender 的**对象名原样**(含重名时的 .001 后缀): 它就是导出后的
        glTF 节点名, 工作台靠它与 PartIndex.origName 精确对齐.
    """
    delete_patterns = compile_patterns(config.get("delete_patterns", []))
    keep_patterns = compile_patterns(config.get("keep_patterns", []))
    min_dim = float(config.get("min_dimension_mm", 0.0)) / 1000.0

    # 显式名单: 工作台点选的是"零件"(可能是一棵子树的根), 因此要连同后代一并处理
    explicit_delete = set(config.get("explicit_delete") or [])
    explicit_keep = set(config.get("explicit_keep") or [])

    # 归一后比对: 浏览器里 three 会把节点名的空格换成下划线, 工作台早期保存的名单
    # 因此与 Blender 原名(带空格)对不上, 表现为"标了删除、重跑后还在"且日志只写
    # "显式 0 个"没人看见. 归一映射让两种写法都能命中, 并记录每条是否用上.
    delete_by_norm = {_norm(entry): entry for entry in explicit_delete}
    keep_by_norm = {_norm(entry): entry for entry in explicit_keep}
    matched_entries: set[str] = set()

    delete_names: set[str] = set()
    keep_names: set[str] = set()
    for obj in list(bpy.data.objects):
        norm = _norm(_base_name(obj.name))
        entry = delete_by_norm.get(norm)
        if entry is not None:
            delete_names |= _collect_subtree_names(obj)
            matched_entries.add(entry)
        entry = keep_by_norm.get(norm)
        if entry is not None:
            keep_names |= _collect_subtree_names(obj)
            matched_entries.add(entry)

    doomed: list[dict] = []
    kept_explicit: list[str] = []

    # 非网格节点(相机/灯/空物体)单独判一轮.
    # SolidWorks 原生 glTF 会附带一个名为 current 的相机节点, 它没有网格,
    # 只走 mesh_objects() 就永远删不掉; 而它一留下, 顶层就从"单一总装根"变成两个,
    # assembly_level_objects() 的下探逻辑失效, 工位归组会全部落空.
    for obj in list(bpy.data.objects):
        if obj.type == "MESH" or obj.children:
            continue
        if matches_any(obj.name, keep_patterns):
            continue
        if matches_any(obj.name, delete_patterns):
            doomed.append({"name": obj.name, "reason": "nonmesh"})

    for obj in list(mesh_objects()):
        base = _base_name(obj.name)

        if base in keep_names:
            kept_explicit.append(obj.name)
            continue
        if base in delete_names:
            doomed.append({"name": obj.name, "reason": "explicit"})
            continue

        if matches_any(obj.name, keep_patterns):
            continue
        if matches_any(obj.name, delete_patterns):
            doomed.append({"name": obj.name, "reason": "pattern"})
            continue

        if min_dim > 0:
            longest = max(obj.dimensions) if len(obj.dimensions) else 0.0
            if 0 < longest < min_dim:
                doomed.append({"name": obj.name, "reason": "size"})

    return {
        "delete": doomed,
        "kept_explicit": kept_explicit,
        "explicit_missed": sorted((explicit_delete | explicit_keep) - matched_entries),
        "min_dimension_m": min_dim,
    }


def prune(config: dict) -> dict:
    """
    功能: 按显式名单、名称模式与尺寸阈值删除对整机观感无贡献的零件.

    这是控制性能预算最有效的一步: 紧固件与拖链节数量占比极高, 但在整机视角下
    每个都不足一个像素, 删掉它们能同时降低三角形数、绘制调用数与文件体积.

    优先级(高到低): 显式保留 > 显式删除 > 正则保留 > 正则删除 > 尺寸阈值 ——
    判定全在 prune_verdict() 里, 本函数只负责执行它的裁决, 好让装配工作台的
    "会被删掉"预览与真实删减共用同一份实现(两份实现漂移过, 见 prune_verdict 说明).
    显式名单来自「装配工作台」的点选授权, 代表人做过判断, 因此压过所有通用规则.

    单位说明: 本函数必须在 normalize_units() 之后调用. 归一之后场景恒为米,
    因此配置里的毫米阈值一律除以 1000 换算, 不需要再看原始单位.

    参数:
        config: prune_list 配置
    返回值: dict, 删除统计
    """
    verdict = prune_verdict(config)
    min_dim = verdict["min_dimension_m"]
    missed_entries = verdict["explicit_missed"]

    counts = {"explicit": 0, "pattern": 0, "size": 0, "nonmesh": 0}
    vanished = 0
    for item in verdict["delete"]:
        obj = bpy.data.objects.get(item["name"])
        if obj is None:
            vanished += 1
            continue
        bpy.data.objects.remove(obj, do_unlink=True)
        counts[item["reason"]] += 1

    log(
        f"删减: 显式 {counts['explicit']} 个(显式保留 {len(verdict['kept_explicit'])} 个), "
        f"按名称 {counts['pattern']} 个, 按尺寸(<{min_dim * 1000:.1f}mm) {counts['size']} 个, "
        f"非网格节点 {counts['nonmesh']} 个; 剩余网格 {len(mesh_objects())}"
    )
    # 静默失败是这类问题的温床: 名单条目一个对象都没命中时必须喊出来,
    # 常见原因是浏览器侧自动名(mesh_N)或零件已被上游规则删掉.
    if missed_entries:
        log(f"警告: 显式名单未命中任何对象({len(missed_entries)} 条): " + ", ".join(missed_entries[:8]))
    # 裁决时在、执行时没了 = 删除意外产生了连带效应, 同属"必须喊出来"那一类
    if vanished:
        log(f"警告: 裁决为删的对象有 {vanished} 个在执行时已不存在")
    return {
        "removed_explicit": counts["explicit"],
        "kept_explicit": len(verdict["kept_explicit"]),
        "removed_by_name": counts["pattern"],
        "removed_by_size": counts["size"],
        "removed_non_mesh": counts["nonmesh"],
        "explicit_missed": missed_entries,
        "min_dimension_m": min_dim,
        "remaining_meshes": len(mesh_objects()),
    }


# 区域分离出来的对象名后缀. 刻意不含空格: three.js 会把节点名里的空白消毒成下划线,
# 带空格的后缀在浏览器侧就成了另一个写法, 平白多一层要对齐的东西.
REGION_SPLIT_SUFFIX = "__REGION_DELETE"

# 0.5mm 容差: 抵消 Draco 量化与浮点误差, 又不足以误伤相邻结构
_REGION_EPS_M = 0.0005


def _region_doomed_faces(mesh: Any, boxes: list) -> tuple[set[int], int]:
    """
    功能: 按"连通面岛整岛落进区域框"判定一个网格上哪些面注定被切除.

    region_delete(真删) 与 region_split(分离出来给工作台标红) 共用本函数 ——
    判定只此一份, 免得"预览标红的"和"实际删掉的"不是同一批面.

    参数:
        mesh: 网格数据块
        boxes: 区域框列表, 每项 {min:[x,y,z], max:[x,y,z]}, 毫米, 零件局部坐标
    返回值: tuple(注定被切的面索引集合, 命中的面岛数)
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    # 按面邻接划分连通岛, 逐岛判定是否整体落入某个区域框
    seen: set[int] = set()
    doomed: set[int] = set()
    islands = 0
    for face in bm.faces:
        if face.index in seen:
            continue
        stack = [face]
        seen.add(face.index)
        island = []
        while stack:
            current = stack.pop()
            island.append(current)
            for edge in current.edges:
                for neighbor in edge.link_faces:
                    if neighbor.index not in seen:
                        seen.add(neighbor.index)
                        stack.append(neighbor)
        centers = [f.calc_center_median() for f in island]
        for box in boxes:
            lo = [v / 1000.0 - _REGION_EPS_M for v in box["min"]]
            hi = [v / 1000.0 + _REGION_EPS_M for v in box["max"]]
            if all(lo[i] <= c[i] <= hi[i] for c in centers for i in range(3)):
                doomed.update(f.index for f in island)
                islands += 1
                break
    bm.free()
    return doomed, islands


def _delete_faces(mesh: Any, indices: set[int], invert: bool = False) -> None:
    """
    功能: 从网格数据块上删掉指定索引的面.

    面索引取自 _region_doomed_faces 的那一遍 from_mesh; 这里重新 from_mesh 仍然对得上,
    因为 bmesh 的面顺序恒等于网格的多边形顺序, 而两次之间没人动过这个网格.

    参数:
        mesh: 网格数据块
        indices: 面索引集合
        invert: True 表示反过来删"不在集合里"的面(用于抠出只含目标面的副本)
    返回值: None
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    victims = [f for f in bm.faces if (f.index in indices) != invert]
    if victims:
        bmesh.ops.delete(bm, geom=victims, context="FACES")
        bm.to_mesh(mesh)
    bm.free()


def region_delete(rules: list) -> dict:
    """
    功能: 从单体网格零件上切除指定局部区域的几何(整个连通面岛都落进区域框才删).

    针对的场景: 供应商 STEP 导入件把电机线缆/插头直接模在本体网格里(如刮板 Z 轴
    模组 CFG4-L5-50 的 `Open CASCADE STEP translator 7.6 18.2-1`), 按名删除的
    最小粒度是整个节点, 表达不了"只删线不删电机". 这里按几何删: 线缆/插头在这类
    未焊接的网格里是独立面岛, 区域框画宽松也只会整岛命中它们; 机身面岛延伸到框外,
    "整岛判定"天然豁免 —— 所以框不需要毫米级精确.

    坐标语义: 区域框是该零件**局部坐标系**下的毫米值(glTF 网格局部空间恒为米,
    此处 ÷1000 换算), 与实例摆放无关 —— 同名零件的全部实例一次生效.
    框坐标由 AI 在 Blender 里探测面岛分布、渲染前后对比核对后写定.

    参数:
        rules: prune_list.yaml 的 region_delete 段, 每条形如
               {node: 节点名, note: 说明, boxes_mm: [{min: [x,y,z], max: [x,y,z]}]}
               节点名语义与显式名单一致: 去 .001 后缀、空白归一后比对.
    返回值: dict, 各规则删除统计与未命中警告
    """
    results = []
    missed = []
    processed_meshes: set[str] = set()
    for rule in rules or []:
        node = str(rule.get("node") or "")
        boxes = rule.get("boxes_mm") or []
        want = _norm(node)
        stat = {"node": node, "matched_objects": 0, "islands_deleted": 0, "faces_deleted": 0}
        if rule.get("note"):
            stat["note"] = rule["note"]

        for obj in list(mesh_objects()):
            if _norm(_base_name(obj.name)) != want:
                continue
            stat["matched_objects"] += 1
            if obj.data.name in processed_meshes:
                continue  # 多实例共享网格数据块时只切一次, 效果覆盖全部实例
            processed_meshes.add(obj.data.name)

            doomed, islands = _region_doomed_faces(obj.data, boxes)
            if doomed:
                stat["islands_deleted"] += islands
                stat["faces_deleted"] += len(doomed)
                _delete_faces(obj.data, doomed)

            if len(obj.data.polygons) == 0:
                bpy.data.objects.remove(obj, do_unlink=True)

        if stat["matched_objects"] == 0 or stat["faces_deleted"] == 0:
            missed.append(node)
        results.append(stat)

    total = sum(r["faces_deleted"] for r in results)
    log(f"区域删除: {len(results)} 条规则, 共删 {total} 个面")
    # 静默失败是这类问题的温床(与显式名单同一约定): 规则一个面都没删到必须喊出来,
    # 常见原因是节点名对不上或几何已被上游规则删掉.
    if missed:
        log(f"警告: 区域删除未命中任何面({len(missed)} 条): " + ", ".join(missed[:8]))
    return {"rules": results, "faces_deleted": total, "missed": missed}


def region_split(rules: list) -> dict:
    """
    功能: 把 region_delete 注定切除的面岛**分离**成独立对象, 而不是删掉.

    只在 raw 阶段(装配工作台)用. 工作台加载的是未删减的 raw.glb, 白模下把"会被管线
    删掉的零件"标红; 而 region_delete 是**面级**删除, 按节点上色根本表达不了"只删线
    不删电机" —— 用户看到的就是电机上那截注定被删的模制线缆一直保持白色(2026-08-05
    点样水平模组 CFG4-L10-100 一案). 这里把那些面从本体网格搬到一个同父、同变换的
    兄弟对象上(名字加 REGION_SPLIT_SUFFIX): 几何总量与外观都不变, 但那截线缆成了
    独立节点, 工作台当普通零件标红/点选/在「减配后」隐藏即可, 前端不需要任何特例.

    面岛判定与 region_delete 共用 _region_doomed_faces —— 判定只此一份实现, 不会漂移.

    参数:
        rules: 同 region_delete, prune_list.yaml 的 region_delete 段
    返回值: dict, 各规则分离统计; nodes 为新建对象名(工作台按它标红)
    """
    results = []
    missed = []
    split_nodes: list[str] = []
    # 多实例共享网格数据块时面只能搬一次, 但每个实例都得有自己的线缆对象
    cable_meshes: dict[str, Any] = {}

    for rule in rules or []:
        node = str(rule.get("node") or "")
        boxes = rule.get("boxes_mm") or []
        want = _norm(node)
        stat = {"node": node, "matched_objects": 0, "islands_split": 0, "faces_split": 0}
        if rule.get("note"):
            stat["note"] = rule["note"]

        for obj in list(mesh_objects()):
            if _norm(_base_name(obj.name)) != want:
                continue
            stat["matched_objects"] += 1

            cable_mesh = cable_meshes.get(obj.data.name)
            if cable_mesh is None:
                doomed, islands = _region_doomed_faces(obj.data, boxes)
                if not doomed:
                    continue
                # 顺序要紧: 先复制出"只留被切面"的网格, 再从本体上删掉这些面
                cable_mesh = obj.data.copy()
                cable_mesh.name = f"{obj.data.name}_REGION"
                _delete_faces(cable_mesh, doomed, invert=True)
                _delete_faces(obj.data, doomed)
                cable_meshes[obj.data.name] = cable_mesh
                stat["islands_split"] += islands
                stat["faces_split"] += len(doomed)

            cable = bpy.data.objects.new(f"{obj.name}{REGION_SPLIT_SUFFIX}", cable_mesh)
            for collection in obj.users_collection:
                collection.objects.link(cable)
            if not cable.users_collection:
                bpy.context.scene.collection.objects.link(cable)
            cable.parent = obj.parent
            # 顶点在源零件局部坐标里, 所以世界变换必须与源对象逐位一致
            cable.matrix_world = obj.matrix_world.copy()
            split_nodes.append(cable.name)

        if stat["matched_objects"] == 0 or stat["faces_split"] == 0:
            missed.append(node)
        results.append(stat)

    # 依赖图不刷新的话, 后续步骤读到的 matrix_world 还是旧值(补几何那边踩过: 读出全 0)
    bpy.context.view_layer.update()

    total = sum(r["faces_split"] for r in results)
    log(f"区域分离: {len(results)} 条规则, 共分出 {len(split_nodes)} 个对象 / {total} 个面")
    # 与 region_delete 同一约定: 一个面都没分到必须喊出来, 否则工作台会安静地少标一处红
    if missed:
        log(f"警告: 区域分离未命中任何面({len(missed)} 条): " + ", ".join(missed[:8]))
    return {"rules": results, "faces_split": total, "nodes": split_nodes, "missed": missed}


def write_prune_preview(cfg: dict) -> dict:
    """
    功能: 产出装配工作台的"会被删掉"基线 —— 只裁决不执行, 顺带把 region_delete 的
          面岛分离成独立节点, 结果落成 JSON 供浏览器直接渲染.

    为什么要落盘而不是让浏览器自己算: 见 prune_verdict 的说明, 两份实现漂移过四类
    错判. 基线里带 prune_list.yaml 原文的戳(见 03_clean_model.source_stamp), 工作台
    拿它与当前 YAML 比对 —— 对不上就说明规则改了而 raw 模型没重跑, 页面要挂"预览为
    近似"的告警(缺戳同理, 与片段陈旧检测 railCalibStatus 同一约定: 缺戳不许判绿).

    参数:
        cfg: 作业单的 prune_preview 段, 形如
             {"config": prune_list 配置, "output": 输出 JSON 路径,
              "source_stamp": prune_list.yaml 原文的戳}
    返回值: dict, 摘要统计(进 03 报告)
    """
    config = cfg.get("config") or {}
    verdict = prune_verdict(config)
    split = region_split(config.get("region_delete") or [])

    reasons = {item["name"]: item["reason"] for item in verdict["delete"]}
    for name in split["nodes"]:
        reasons[name] = "region"

    counts: dict[str, int] = {}
    for reason in reasons.values():
        counts[reason] = counts.get(reason, 0) + 1

    payload = {
        "version": 1,
        # 刻意不写生成时间: 同样的输入要产出逐字节相同的文件, 否则没法 diff、也没法判"变没变"
        "source_stamp": cfg.get("source_stamp") or "",
        "min_dimension_mm": verdict["min_dimension_m"] * 1000.0,
        # 名字是 Blender 对象名原样(= 导出后的 glTF 节点名), 工作台按它对齐 PartIndex.origName
        "deleted": sorted(reasons),
        "reasons": reasons,
        "counts": counts,
        "kept_explicit": sorted(verdict["kept_explicit"]),
        "explicit_missed": verdict["explicit_missed"],
        "region_nodes": sorted(split["nodes"]),
        "region_missed": split["missed"],
    }

    output = cfg.get("output")
    if output:
        os.makedirs(os.path.dirname(output), exist_ok=True)
        with open(output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        log(f"标红基线已写入: {output}")

    detail = ", ".join(f"{reason} {count}" for reason, count in sorted(counts.items()))
    log(f"标红基线: 判删 {len(payload['deleted'])} 个({detail or '无'}); 显式保留 {len(payload['kept_explicit'])} 个")
    return {
        "output": output or "",
        "source_stamp": payload["source_stamp"],
        "deleted": len(payload["deleted"]),
        "counts": counts,
        "region": {"nodes": len(split["nodes"]), "faces_split": split["faces_split"], "missed": split["missed"]},
        "explicit_missed": verdict["explicit_missed"],
    }


def _apply_decimate(obj: Any, ratio: float) -> bool:
    """
    功能: 给一个对象加减面修改器并烘焙.
    参数:
        obj: 网格对象
        ratio: 保留比例(0~1)
    返回值: bool, 是否实际执行
    """
    # 面数太少的对象再减面只会破坏轮廓, 直接跳过
    if len(obj.data.polygons) < 200:
        return False
    modifier = obj.modifiers.new(name="TwinDecimate", type="DECIMATE")
    modifier.ratio = ratio
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    return True


def decimate(config: dict) -> dict:
    """
    功能: 对显式指定或规则匹配的重型零件应用减面修改器并烘焙.
    参数:
        config: prune_list 配置(读 explicit_decimate 与 decimate_rules)
    返回值: dict, 减面统计
    """
    applied_explicit = 0
    applied_rules = 0

    # 显式减面: 工作台点选授权, 精确到零件(含其后代)
    explicit = {e["name"]: float(e.get("ratio", 0.3)) for e in config.get("explicit_decimate") or [] if e.get("name")}
    if explicit:
        targets: dict[str, float] = {}
        for obj in list(bpy.data.objects):
            ratio = explicit.get(_base_name(obj.name))
            if ratio is not None:
                for name in _collect_subtree_names(obj):
                    targets[name] = ratio
        for obj in mesh_objects():
            ratio = targets.get(_base_name(obj.name))
            if ratio is not None and ratio < 1.0 and _apply_decimate(obj, ratio):
                applied_explicit += 1

    for rule in config.get("decimate_rules") or []:
        patterns = compile_patterns(rule.get("patterns", []))
        ratio = float(rule.get("ratio", 1.0))
        if ratio >= 1.0:
            continue
        for obj in mesh_objects():
            if matches_any(obj.name, patterns) and _apply_decimate(obj, ratio):
                applied_rules += 1

    if applied_explicit or applied_rules:
        log(f"减面: 显式 {applied_explicit} 个, 按规则 {applied_rules} 个")
    return {"decimated_explicit": applied_explicit, "decimated_by_rule": applied_rules}


# ---------------------------------------------------------------------------
# 材质
# ---------------------------------------------------------------------------


def hex_to_rgba(value: str, alpha: float = 1.0) -> tuple:
    """
    功能: 把 "#RRGGBB" 转成 Blender 使用的线性 RGBA 元组.
    参数:
        value: 十六进制颜色
        alpha: 透明度
    返回值: tuple[float, float, float, float]
    """
    value = (value or "#808080").lstrip("#")
    srgb = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def to_linear(channel: float) -> float:
        """功能: sRGB 分量转线性. 参数: channel 0~1. 返回值: float"""
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return (*[to_linear(c) for c in srgb], alpha)


def build_material(spec: dict):
    """
    功能: 按规格创建一个 Principled BSDF 材质.
    参数:
        spec: 材质规格(base_color/roughness/metalness/emission/transmission/alpha 等)
    返回值: bpy.types.Material
    """
    name = spec.get("name", "MAT_UNNAMED")
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    _write_principled(material, spec)
    return material


def _write_principled(material: Any, spec: dict) -> None:
    """
    功能: 把规格写进一个**已存在**的 Principled BSDF 材质(创建与补写共用的唯一写入面).

    单独成函数的理由: 外观覆盖收尾补写(apply_manual_override_postpass)要对既有实例
    打补丁 —— 写入侧只存在这一份, 补写与创建才不可能漂(输入名探测表与
    _principled_snapshot 的读回侧配对).

    参数:
        material: bpy 材质(须 use_nodes); 无 Principled 节点时静默返回
        spec: 材质规格(base_color/roughness/metalness/emission/transmission/alpha 等)
    返回值: None
    """
    bsdf = material.node_tree.nodes.get("Principled BSDF") if material.use_nodes else None
    if bsdf is None:
        return

    alpha = float(spec.get("alpha", 1.0))
    bsdf.inputs["Base Color"].default_value = hex_to_rgba(spec.get("base_color"), 1.0)
    bsdf.inputs["Roughness"].default_value = float(spec.get("roughness", 0.5))
    bsdf.inputs["Metallic"].default_value = float(spec.get("metalness", 0.0))

    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = alpha
    if alpha < 1.0:
        material.blend_method = "BLEND"
    elif material.blend_method == "BLEND":
        # 补写路径(apply_manual_override_postpass)把既有 BLEND 实例的 alpha 提回 1.0
        # 时要同步退出 BLEND, 否则导出的 GLB 仍是 alphaMode=BLEND, 前端一加载就拿到
        # depthWrite=false 的穿模三元组
        material.blend_method = "OPAQUE"

    # 不同 Blender 版本里透射与自发光的输入名有差异, 逐一探测避免版本耦合
    for key in ("Transmission Weight", "Transmission"):
        if key in bsdf.inputs and spec.get("transmission") is not None:
            bsdf.inputs[key].default_value = float(spec["transmission"])
            break
    if "IOR" in bsdf.inputs and spec.get("ior") is not None:
        bsdf.inputs["IOR"].default_value = float(spec["ior"])

    if spec.get("emission"):
        for key in ("Emission Color", "Emission"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = hex_to_rgba(spec["emission"], 1.0)
                break
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = float(
                spec.get("emission_strength", 1.0)
            )


def _principled_snapshot(material: Any) -> dict:
    """
    功能: 把一个 Principled BSDF 材质的可调输入读回成 build_material 规格.

    用于零件级覆盖: 以零件当前材质为"底", 叠加人工补丁后生成专属实例 ——
    未覆盖的字段必须保持原样, 所以要能无损读回. 输入名探测与 build_material
    的写入侧保持同一张表(防 Blender 版本改名漂移).

    参数:
        material: bpy 材质; None 或非节点材质按中性灰兜底
    返回值: dict, 规格(不含 name)
    """
    fallback = {"base_color": "#A9AFB8", "roughness": 0.5, "metalness": 0.0}
    if material is None or not getattr(material, "use_nodes", False):
        return dict(fallback)
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return dict(fallback)

    def to_hex(value: Any) -> str:
        """功能: 线性 RGBA -> '#RRGGBB'. 参数: value 颜色输入值. 返回值: str"""
        channels = [int(round(linear_to_srgb(float(value[i])) * 255)) for i in range(3)]
        return "#" + "".join(f"{max(0, min(255, c)):02X}" for c in channels)

    spec: dict = {
        "base_color": to_hex(bsdf.inputs["Base Color"].default_value),
        "roughness": round(float(bsdf.inputs["Roughness"].default_value), 4),
        "metalness": round(float(bsdf.inputs["Metallic"].default_value), 4),
    }
    if "Alpha" in bsdf.inputs:
        alpha = round(float(bsdf.inputs["Alpha"].default_value), 4)
        if alpha < 1.0:
            spec["alpha"] = alpha
    for key in ("Transmission Weight", "Transmission"):
        if key in bsdf.inputs:
            transmission = round(float(bsdf.inputs[key].default_value), 4)
            if transmission > 0:
                spec["transmission"] = transmission
            break
    if "IOR" in bsdf.inputs:
        spec["ior"] = round(float(bsdf.inputs["IOR"].default_value), 4)
    strength = 0.0
    if "Emission Strength" in bsdf.inputs:
        strength = float(bsdf.inputs["Emission Strength"].default_value)
    if strength > 0:
        for key in ("Emission Color", "Emission"):
            if key in bsdf.inputs:
                spec["emission"] = to_hex(bsdf.inputs[key].default_value)
                spec["emission_strength"] = round(strength, 4)
                break
    return spec


def apply_manual_override_postpass(materials_cfg: dict) -> dict:
    """
    功能: 把 appearance_overrides 的实例名覆盖补写到**全部已存在**的材质实例上(收尾一遍).

    为什么在收尾统一补而不是只靠 assign_materials: 覆盖(经 build_materials 落到
    native_color_passthrough.overrides)原本只有 material_for() 消费, 而 metal_material()
    (机器人连杆/金属饰件)、build_pump_visuals(泵饰件)等路径按配方直建实例、从不问覆盖 ——
    2026-08-06 实锤: MAT_NAT_GOLD_B08D57(注射泵鲁尔接头)在材质台(运行时按名回放)看着
    已生效, 烘进 GLB 却仍是金色, 只有一行容易被淹没的警告。build_materials.py 的
    apply_overrides 头注早记载过同类静默丢弃, 本函数把洞从消费侧补上。

    时序: 在 main() 阶段分支之后、stats_final/导出之前的唯一挂点调用 —— 晚于一切材质
    创建路径, 三阶段(raw/minimal/full)通吃; join 并的是网格不是材质数据块, 对合并前后
    都成立(STATIC_MAT_* 块名来自材质名, 材质实例仍在)。

    已知边界: part_overrides/part_groups 的独占材质(MAT_PART_*/MAT_GROUP_*)在建组时
    snapshot 过底材质 —— 材质级覆盖不回灌进它们, 与材质台的运行时行为一致。

    参数:
        materials_cfg: materials.yaml 全量配置
    返回值: dict {applied, unused} —— unused 从此只剩真死键(该色号已不再产出)
    """
    overrides = ((materials_cfg or {}).get("native_color_passthrough") or {}).get("overrides") or {}
    applied: list[str] = []
    unused: list[str] = []
    for name, patch in overrides.items():
        material = bpy.data.materials.get(str(name))
        if material is None:
            unused.append(str(name))
            continue
        spec = _principled_snapshot(material)
        spec.update({key: value for key, value in (patch or {}).items() if value is not None})
        _write_principled(material, spec)
        applied.append(str(name))
    if applied:
        log(f"外观覆盖收尾补写: {len(applied)} 条实例名覆盖已落到最终材质"
            f"({', '.join(sorted(applied))})")
    if unused:
        log(
            "警告: appearance_overrides 以下键在最终场景里没有同名材质实例"
            "(键名拼错或该色号已不存在): " + ", ".join(sorted(unused))
        )
    return {"applied": sorted(applied), "unused": sorted(unused)}


def _apply_exclusive_materials(patches: dict, prefix: str, section_label: str, cn_label: str) -> dict:
    """
    功能: 给命中零件换专属材质实例(<prefix>_<slug>), 以当前材质为底叠观感补丁.

    apply_part_overrides / apply_part_isolate 的共用内核: 专属材质名使零件在
    join_by_material / join_static_per_station 里自然脱离共享块(单件时保留原节点,
    多件成独立 STATIC 块), 重跑一次之后前端就能按材质名寻址.

    必须在 assign_materials 之后、join 之前调用: 底要取"两轴算法定稿后的材质",
    合并之前零件才仍可按名字命中.

    参数:
        patches: {零件名(中文/拼音/three 消毒写法均可): {字段: 值}}(孤立场景传空补丁)
        prefix: 材质名前缀(不含末尾下划线, 如 MAT_PART / MAT_SOLO)
        section_label: 告警里的段名(part_overrides / part_isolate)
        cn_label: 摘要日志里的中文名
    返回值: dict, {"applied": {键: 对象数}, "unused": [未命中的键]}
    """
    # 键的匹配集: 原写法 + three 消毒写法(空白→下划线); 对象侧同样双写法+别名展开
    key_forms = {key: {key, _norm(key)} for key in patches}
    applied: dict[str, int] = {}
    used_names: set[str] = set()
    cache: dict[str, Any] = {}

    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            continue
        variants: set[str] = set()
        for variant in name_variants(obj.name):
            variants.add(variant)
            variants.add(_norm(variant))
        hit_key = None
        for key, forms in key_forms.items():
            if forms & variants:
                hit_key = key
                break
        if hit_key is None:
            continue

        material = cache.get(hit_key)
        if material is None:
            base = obj.data.materials[0] if obj.data.materials else None
            spec = _principled_snapshot(base)
            spec.update(patches[hit_key])
            slug = _NAME_ALIASES.get(_base_name(hit_key)) or _NAME_ALIASES.get(hit_key)
            if not slug:
                slug = re.sub(r"[^0-9A-Za-z]+", "_", hit_key).strip("_")
            if len(slug or "") < 3:
                # 纯中文键消毒后所剩无几: 用 CRC 保证跨零件唯一且跨次运行稳定
                slug = f"h{zlib.crc32(hit_key.encode('utf-8')) & 0xFFFFFFFF:08x}"
            name = f"{prefix}_{slug}"
            serial = 2
            while name in used_names:
                name = f"{prefix}_{slug}_{serial}"
                serial += 1
            used_names.add(name)
            spec["name"] = name
            material = build_material(spec)
            cache[hit_key] = material

        obj.data.materials.clear()
        obj.data.materials.append(material)
        applied[hit_key] = applied.get(hit_key, 0) + 1

    unused = sorted(set(patches) - set(applied))
    if unused:
        # 与 unused_manual_overrides 同款: 告警冒泡到重跑面板, 不硬失败 ——
        # 键可能对应已被删减的零件, 不该让整条管线因此翻车
        log(f"警告: {section_label} 以下键未命中任何零件(改名/已删减?): {', '.join(unused)}")
    log(f"{cn_label}: {len(applied)}/{len(patches)} 键命中, 换材质 {sum(applied.values())} 个对象")
    return {"applied": applied, "unused": unused}


def apply_part_overrides(overrides: dict) -> dict:
    """
    功能: 零件级材质覆盖 —— 命中零件以当前材质为底叠补丁, 换成专属实例 MAT_PART_<slug>.

    这是材质台「单零件调材质」的管线落点(内核见 _apply_exclusive_materials):
    该零件脱离共享块, 重跑一次之后前端就能按材质名寻址、永久实时预览.

    参数:
        overrides: {零件名(中文/拼音/three 消毒写法均可): {字段: 值}}
    返回值: dict, {"applied": {键: 对象数}, "unused": [未命中的键]}
    """
    if not overrides:
        return {"applied": {}, "unused": []}
    return _apply_exclusive_materials(overrides, "MAT_PART", "part_overrides", "零件级覆盖")


def apply_part_isolate(names: list) -> dict:
    """
    功能: 孤立清单 —— 命中零件观感不变, 仅换成专属实例 MAT_SOLO_<slug> 以脱离静态合并.

    这是材质台「拆出为独立零件」的管线落点: 与 apply_part_overrides 同一内核, 区别
    只在不叠任何观感补丁, 表达"只独立、不改观感". 与 part_overrides 的互斥在
    build_materials 清洗期已裁决(重叠键被丢弃并告警), 这里按清单直做; 同 base 名的
    多个实例会一并命中并共享同一 MAT_SOLO 实例(同工位多实例合并成一个专属小块).

    参数:
        names: [零件 base 名(已剥 .00N 后缀)]
    返回值: dict, {"applied": {键: 对象数}, "unused": [未命中的键]}
    """
    if not names:
        return {"applied": {}, "unused": []}
    return _apply_exclusive_materials(
        {str(name): {} for name in names}, "MAT_SOLO", "part_isolate", "孤立拆出"
    )


# 柜门归属表: 门键 -> 门板零件名. 消费方是 fx-preview 沙盒的 fxConfig.doors ——
# 那边按门键写门体 nodes, 这边按门键给合页门叶起名, 两处的键必须逐字一致.
# 门板改名/增删会被 rename_door_hinge_leaves 的门禁直接顶红, 不会静默漂移.
DOOR_PANELS = {
    "feed": "上料门板-1",     # 前上料门(另带亚克力窗 门板-5)
    "back": "侧门板-1",       # 后面同位置那扇
    "sideL1": "侧门-1",       # 左端面对开门
    "sideL2": "侧门-2",
    "frontL1": "固定门板-5",  # 前面左半对开门
    "frontL2": "固定门板-6",
    "backL1": "固定门板-2",   # 后面左半对开门
    "backL2": "固定门板-3",
}

# 合页 AKQ41 每只拆三个子件, 只有 _002 那片压在门板上(_001 在框侧, _003 是销).
# 每扇门 2 只合页 = 2 片门叶, 全机 8 扇共 16 片, 且这 16 片**同名**(实例只靠 Blender
# 追加的 .00N 区分), 所以没法直接写进 part_isolate —— 那边会剥掉 .00N 再去重.
DOOR_HINGE_LEAF_BASE = "AKQ41-G-Z-6065_002-1"


def rename_door_hinge_leaves() -> dict:
    """
    功能: 把 16 片合页门叶按几何归属改名为 DOOR_HINGE_<门键>, 使其可随门转动.

    为什么需要这一步: 门叶要跟着门转, 就得脱离静态合并块单独成节点; 而脱离合并的
    唯一入口 part_isolate 是**按 base 名**匹配的(build_materials._clean_part_isolate
    会主动 `re.sub(r"\\.\\d{3}$", "")` 剥掉实例后缀再去重). 16 片门叶共用一个 base 名,
    直接写清单只会让它们共享同一个 MAT_SOLO 又并成一块 —— 等于没做.

    于是先按**几何**(门叶中心落在哪扇门的门板包围盒内)给它们起稳定名字, 再交给
    part_isolate 走常规流程. 归属每轮按几何重算, 与 .00N 后缀彻底解耦 —— 这一点很要紧,
    因为整机 GLB 来自 SolidWorks XR 导出, 重导会换序, 后缀根本不可依赖.

    同一扇门的两片**故意同名**: 它们同进同出, 让 join_static_per_station 把它们并成
    一个 ST_FRAME/STATIC_MAT_SOLO_DOOR_HINGE_<门键> 节点, 只吃 1 个绘制调用而不是 2 个.
    (DOOR_HINGE_ 不在 join 的 protected_prefixes 里, 会正常合并.)

    调用时序: 在全部 build_*/apply_station_alignment 之后(门板位置定稿)、
    apply_part_isolate 之前(名字还在, 且清单要按新名匹配).

    参数: 无
    返回值: dict, {"assigned": {门键: [门叶原名...]}, "leaves": 总片数}
    异常: 片数/归属对不上时 RuntimeError —— 宁可红, 不要静默把门叶留在原地.
    """
    panels: dict[str, tuple] = {}
    for key, part in DOOR_PANELS.items():
        hits = [obj for obj in mesh_objects() if _base_name(obj.name) == part]
        if len(hits) != 1:
            raise RuntimeError(
                f"合页门叶归属: 门板「{part}」(门键 {key})命中 {len(hits)} 个对象, 期望恰好 1 个"
            )
        lo, hi = _mesh_world_bounds(hits[0])
        panels[key] = (lo, hi)

    leaves = [obj for obj in mesh_objects() if _base_name(obj.name) == DOOR_HINGE_LEAF_BASE]
    if not leaves:
        raise RuntimeError(f"合页门叶归属: 没找到任何 {DOOR_HINGE_LEAF_BASE}, 装配或件号变了")

    assigned: dict[str, list] = {}
    renames: list = []
    for leaf in leaves:
        lo, hi = _mesh_world_bounds(leaf)
        center = (lo + hi) / 2
        owners = []
        for key, (plo, phi) in panels.items():
            # 门板是薄板: 只在最薄那根轴上放宽 40mm(合页骑在门面外侧), 另两轴严格落内
            span = phi - plo
            thin = min(range(3), key=lambda i: span[i])
            pad = [0.0, 0.0, 0.0]
            pad[thin] = 0.04
            if all(plo[i] - pad[i] <= center[i] <= phi[i] + pad[i] for i in range(3)):
                owners.append(key)
        if len(owners) != 1:
            raise RuntimeError(
                f"合页门叶归属: {leaf.name} 中心 {tuple(round(v, 4) for v in center)} "
                f"落在 {len(owners)} 扇门内({owners}), 期望恰好 1 扇"
            )
        renames.append((leaf, owners[0]))
        assigned.setdefault(owners[0], []).append(leaf.name)

    missing = [key for key in DOOR_PANELS if len(assigned.get(key, [])) != 2]
    if missing or len(leaves) != 2 * len(DOOR_PANELS):
        detail = {key: len(assigned.get(key, [])) for key in DOOR_PANELS}
        raise RuntimeError(
            f"合页门叶归属: 共 {len(leaves)} 片(期望 {2 * len(DOOR_PANELS)}), "
            f"每扇门应各 2 片, 实得 {detail}"
        )

    # 改名放在全部判定通过之后: 中途抛错就不会留下改了一半的场景
    for leaf, key in renames:
        leaf.name = f"DOOR_HINGE_{key}"

    log(f"合页门叶归属: {len(leaves)} 片按几何归到 {len(assigned)} 扇门, 改名 DOOR_HINGE_<门键>")
    return {"assigned": {key: sorted(names) for key, names in assigned.items()}, "leaves": len(leaves)}


def apply_part_groups(groups: dict) -> dict:
    """
    功能: 材质组 —— 工程师定义的"哪些零件合并成同一种材质", 组内成员共享
          一个专属实例 MAT_GROUP_<slug>.

    与 apply_part_overrides 同构("一键一材质多对象"), 匹配关系反转为成员→组:
    单遍扫场景, 每个对象按**组声明顺序、组内 parts 顺序**取首个命中(单一隶属).
    组底 = parts 列表首个可解析成员的当时材质快照 ⊕ 组参数(与前端预览同一规则).
    组材质名独立 → join_static_per_station 自然把组成员按工位合并成同一 STATIC 块 ——
    这正是"合并规则由工程师定"的管线落点.

    调用时序: 在 assign_materials 之后(底要取定稿材质)、apply_part_overrides 之前
    (单件覆盖压过组)、join 之前(合并后名字就没了).

    参数:
        groups: {组名: {parts: [零件原名...], 观感字段子集}}
    返回值: dict, {"applied": {组名: 对象数}, "unused": [未命中的 '组名/零件名']}
    """
    if not groups:
        return {"applied": {}, "unused": []}

    # 成员匹配表: 组声明顺序 + 组内 parts 顺序 = 认领优先级
    member_forms: list = []  # [(组名, part 序号, 零件名, 匹配集)]
    for name, spec in groups.items():
        for order, part in enumerate(spec.get("parts") or []):
            member_forms.append((name, order, part, {part, _norm(part)}))

    # 单遍认领: 对象 -> (组名, part 序号, 零件名)
    hits: dict = {}
    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            continue
        variants: set = set()
        for variant in name_variants(obj.name):
            variants.add(variant)
            variants.add(_norm(variant))
        for name, order, part, forms in member_forms:
            if forms & variants:
                hits[obj] = (name, order, part)
                break

    applied: dict = {}
    matched_parts: set = set()
    used_names: set = set()
    materials_by_group: dict = {}

    for name, spec in groups.items():
        members = sorted(
            ((order, obj) for obj, (group, order, _p) in hits.items() if group == name),
            key=lambda item: item[0],
        )
        if not members:
            continue
        # 底 = parts 序号最小的命中对象(= parts 列表首个可解析成员)
        base_obj = members[0][1]
        base = base_obj.data.materials[0] if base_obj.data.materials else None
        merged = _principled_snapshot(base)
        merged.update({k: v for k, v in spec.items() if k != "parts"})

        slug = _NAME_ALIASES.get(_base_name(name)) or _NAME_ALIASES.get(name)
        if not slug:
            slug = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_")
        if len(slug or "") < 3:
            slug = f"h{zlib.crc32(name.encode('utf-8')) & 0xFFFFFFFF:08x}"
        mat_name = f"MAT_GROUP_{slug}"
        serial = 2
        while mat_name in used_names:
            mat_name = f"MAT_GROUP_{slug}_{serial}"
            serial += 1
        used_names.add(mat_name)
        merged["name"] = mat_name
        material = build_material(merged)
        materials_by_group[name] = material

        for _order, obj in members:
            obj.data.materials.clear()
            obj.data.materials.append(material)
        applied[name] = len(members)
        matched_parts.update(part for obj, (group, _o, part) in hits.items() if group == name)

    unused = sorted(
        f"{name}/{part}"
        for name, spec in groups.items()
        for part in (spec.get("parts") or [])
        if part not in matched_parts
    )
    if unused:
        log(f"警告: part_groups 以下成员未命中任何零件(改名/已删减?): {', '.join(unused)}")
    log(f"材质组: {len(applied)}/{len(groups)} 组命中, 换材质 {sum(applied.values())} 个对象")
    return {"applied": applied, "unused": unused}


def dominant_material_name(obj: Any) -> str:
    """
    功能: 取一个对象占面最多的那个原生材质名.

    SolidWorks 原生 glTF 会把外观赋到面上, 一个零件可能带好几个材质槽
    (实测电磁阀同时有 polished steel / color / white medium gloss plastic).
    要判断"这零件整体算什么材质", 按面数投票比取第一个槽稳妥.

    参数:
        obj: 网格对象
    返回值: str, 材质名; 没有材质时返回空串
    """
    slots = obj.data.materials
    if not slots:
        return ""
    if len(slots) == 1:
        return slots[0].name if slots[0] else ""

    tally: dict[int, int] = {}
    for polygon in obj.data.polygons:
        index = polygon.material_index
        tally[index] = tally.get(index, 0) + 1
    if not tally:
        return slots[0].name if slots[0] else ""

    best = max(tally, key=lambda k: tally[k])
    material = slots[best] if best < len(slots) else None
    return material.name if material else ""


def dominant_base_color(obj: Any) -> tuple[float, float, float] | None:
    """
    功能: 读出一个对象主材质的基色(线性 RGB).

    用于"通用外观颜色直采": 原生 GLB 里大量材质叫 `color-N`, 名字没有语义,
    但基色是设计者特意指定的 —— 青色气管、米黄优力胶、红色件都藏在这里.

    参数:
        obj: 网格对象
    返回值: tuple | None, (r, g, b) 线性值; 读不到返回 None
    """
    name = dominant_material_name(obj)
    if not name:
        return None
    material = bpy.data.materials.get(name)
    if material is None or not material.use_nodes:
        return None
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is None or "Base Color" not in bsdf.inputs:
        return None
    value = bsdf.inputs["Base Color"].default_value
    return (float(value[0]), float(value[1]), float(value[2]))


def dominant_native_info(obj: Any) -> tuple[str, tuple[float, float, float] | None, float]:
    """
    功能: 一次读出对象主材质的 (原生材质名, 线性基色, alpha).

    颜色/物性两轴算法的输入: 原生名投物性(satin aluminum→金属), 基色直采为颜色,
    alpha<1 则整件按玻璃物性处理(SolidWorks 只给真透明件写 alpha, 如 门板 α=0.2).

    参数:
        obj: 网格对象
    返回值: tuple, (材质名, (r,g,b)|None, alpha)
    """
    name = dominant_material_name(obj)
    if not name:
        return "", None, 1.0
    material = bpy.data.materials.get(name)
    if material is None or not material.use_nodes:
        return name, None, 1.0
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is None or "Base Color" not in bsdf.inputs:
        return name, None, 1.0
    value = bsdf.inputs["Base Color"].default_value
    alpha = 1.0
    if "Alpha" in bsdf.inputs:
        alpha = float(bsdf.inputs["Alpha"].default_value)
    return name, (float(value[0]), float(value[1]), float(value[2])), alpha


def linear_to_srgb(value: float) -> float:
    """
    功能: 线性分量转 sRGB(与 hex_to_rgba 的 to_linear 互为逆运算).
    参数:
        value: 线性分量 0~1
    返回值: float, sRGB 分量 0~1
    """
    value = max(0.0, min(1.0, value))
    return value * 12.92 if value <= 0.0031308 else 1.055 * (value ** (1 / 2.4)) - 0.055


def colorful_enough(rgb: tuple[float, float, float], cfg: dict) -> str | None:
    """
    功能: 判断一个基色是否"有彩色到值得直采", 是则返回它的十六进制写法.

    近白与近黑一律不采: 整机 744 个材质里有 412 个是纯白, 全采会让画面一片惨白,
    压过深色控制台配色的重心.

    参数:
        rgb: 线性 RGB
        cfg: native_color_passthrough 配置
    返回值: str | None, 形如 "#00FFFF"; 不够彩色返回 None
    """
    import colorsys

    srgb = tuple(linear_to_srgb(c) for c in rgb)
    _hue, lightness, saturation = colorsys.rgb_to_hls(*srgb)
    if saturation < float(cfg.get("min_saturation", 0.25)):
        return None
    if not (float(cfg.get("min_lightness", 0.12)) <= lightness <= float(cfg.get("max_lightness", 0.88))):
        return None
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c * 255)))) for c in srgb)


def assign_materials(config: dict) -> dict:
    """
    功能: 给所有网格赋 PBR 材质 —— 「物性」与「颜色」两个独立颗粒度.

    2026-07-31 重构. 起因是用户对照实机照片的判定: "装配图(原生模型)比材质图还好看,
    材质管线在做减法". 旧算法每条规则一种共享材质, 角色规则(557 件)与兜底灰(1116 件)
    把原生 GLB 里 744 种真实外观**连颜色带物性一起碾平** —— 夹爪金色快换(#FFC400 的
    PEEK 接头)、门板的 α=0.2 全被单色规则盖掉. 新算法两轴分治:

    物性轴(粗, 按类), 依次:
      1. functional_overrides  功能压过一切(状态灯发光/展缸玻璃/紫外灯), 物性+颜色全定
      2. 原生透明              零件自带 alpha<1(SolidWorks 只给真透明件写它) → 玻璃物性
                               + CAD 实测 α. 必须压过名称规则: 门板 α=0.2 曾被 men_ban
                               规则盖成不透明白, 即"升降料前玻璃变实心块"
      3. cad_transparent       STEP 时代经 COM 读出的透明清单(按零件名, 走别名索引)
      4. rules                 角色规则只定物性模板; base_color 降级为无原生色时的回退.
                               带 force_color: true 的规则例外(黑色拖链、机械臂分层这类
                               "颜色即语义"的规则)
      5. native_materials      原生外观族(satin aluminum→金属 …)定物性
      6. default               中性半金属

    颜色轴(细, 按件), 依次:
      1. recolor 纠错表        CAD 标记色/错色 → 实物色(青→银灰, 线槽米黄→浅灰 …)
      2. 原生基色直采(含白灰)  这是"装配图好看"的全部秘密 —— 白也是信息, 不再丢兜底
      3. 物性类的回退色

    材质实例 = (物性类, 量化色, α档), 共享缓存, 命名 MAT_<类>_<HEX>[_Axx];
    颜色量化到每通道 quantize_step 级以约束绘制调用(预算门禁 500).

    单材质约定: 每个对象最终只留一个材质槽, 按"占面最多的槽"决定归属 ——
    这是下游按工位合并静态几何的前提.

    参数:
        config: materials 配置
    返回值: dict, 每种材质命中的对象数与来源统计
    """
    overrides = [
        (compile_patterns(spec.get("patterns", [])), build_material(spec), spec["name"])
        for spec in config.get("functional_overrides", [])
    ]
    natives = [
        (compile_patterns(spec.get("patterns", [])), spec)
        for spec in config.get("native_materials", [])
    ]

    def index_by_part(section: str) -> dict[str, dict]:
        """功能: 把一段按零件名列举的规格建成精确索引. 参数: section 段名. 返回值: {零件slug: 规格}"""
        index: dict[str, dict] = {}
        for spec in config.get(section, []):
            for part in spec.get("parts", []):
                index[part] = spec
        return index

    # 按零件名建精确索引; 查找时遍历中文/拼音全部写法 —— 此前只查原名, 名单是 STEP
    # 时代的拼音而零件是中文名, 结果 0 命中(日志 CAD透明=0 可证)
    transparent_by_part = index_by_part("cad_transparent")
    cad_by_part = index_by_part("cad_materials")

    def lookup_by_part(index: dict[str, dict], obj_name: str) -> dict | None:
        """功能: 在按零件名的索引里查对象(尝试全部名字写法). 参数: 索引, 对象名. 返回值: 规格|None"""
        for variant in name_variants(obj_name):
            hit = index.get(_base_name(variant))
            if hit is not None:
                return hit
        return None

    rules = [
        (compile_patterns(spec.get("patterns", [])), spec)
        for spec in config.get("rules", [])
    ]
    default_spec = dict(config.get("default") or {})
    default_spec.setdefault("name", "MAT_DEFAULT")

    passthrough = config.get("native_color_passthrough") or {}
    recolor_map = {
        str(k).lstrip("#").upper(): "#" + str(v).lstrip("#").upper()
        for k, v in (passthrough.get("recolor") or {}).items()
    }
    quant_step = max(1, int(passthrough.get("quantize_step", 8)))
    manual_overrides = passthrough.get("overrides") or {}
    # 记录哪些人工覆盖真的套上了 —— 键是材质台写回的实例名(MAT_<类>_<HEX>), 若拼错
    # 或该色号的实例本轮没造出来, 收尾必须告警, 不许再静默丢弃(同硬约束 27 的教训)
    consumed_overrides: set[str] = set()

    # 玻璃物性模板: 原生 alpha<1 的零件统一走它(SolidWorks 只给真透明件写 alpha)
    glass_spec = dict(config.get("glass_template") or {})
    glass_spec.setdefault("name", "MAT_CADGLASS")
    glass_spec.setdefault("roughness", 0.08)
    glass_spec.setdefault("metalness", 0.0)
    glass_spec.setdefault("transmission", 0.7)
    glass_spec.setdefault("ior", 1.46)

    material_cache: dict[str, Any] = {}

    def quantized_hex(rgb: tuple[float, float, float]) -> str:
        """功能: 线性基色 → 量化 sRGB 十六进制(约束材质实例数). 参数: rgb 线性. 返回值: #RRGGBB"""
        channels = []
        for channel in rgb:
            value = round(linear_to_srgb(channel) * 255)
            value = round(value / quant_step) * quant_step
            channels.append(max(0, min(255, int(value))))
        return "#%02X%02X%02X" % tuple(channels)

    def material_for(class_spec: dict, color_hex: str | None, alpha: float) -> Any:
        """功能: 取(物性类, 颜色, α档)对应的共享材质, 没有则现造. 参数见名. 返回值: 材质"""
        base_name = class_spec.get("name", "MAT_DEFAULT")
        spec = dict(class_spec)
        spec.pop("patterns", None)
        spec.pop("parts", None)
        name = base_name
        if color_hex:
            spec["base_color"] = color_hex
            name = f"{base_name}_{str(color_hex).lstrip('#').upper()}"
        if alpha < 0.999:
            bucket = max(5, int(round(alpha * 20) * 5))  # 5% 一档, 避免每个 α 各造一种
            spec["alpha"] = bucket / 100
            name = f"{name}_A{bucket:02d}"
        spec["name"] = name
        cached = material_cache.get(name)
        if cached is None:
            patch = manual_overrides.get(name)
            if patch:
                spec.update(patch)
                consumed_overrides.add(name)
            cached = build_material(spec)
            material_cache[name] = cached
        return cached

    counts: dict[str, int] = {}
    sources = {
        "override": 0, "native_alpha": 0, "glass": 0, "cad": 0,
        "rule": 0, "native": 0, "default": 0,
    }
    color_from = {"recolor": 0, "native": 0, "fallback": 0}
    native_families: dict[str, int] = {}
    native_colors: dict[str, int] = {}

    for obj in mesh_objects():
        # -- 功能覆盖: 物性+颜色一次定死("功能即观感"的零件) --------------------
        chosen = None
        for patterns, material, name in overrides:
            if matches_any(obj.name, patterns):
                chosen = material
                counts[name] = counts.get(name, 0) + 1
                sources["override"] += 1
                break
        if chosen is not None:
            obj.data.materials.clear()
            obj.data.materials.append(chosen)
            continue

        native_name, native_rgb, native_alpha = dominant_native_info(obj)

        # -- 物性轴(按类) ------------------------------------------------------
        class_spec = None
        source = "default"
        alpha = 1.0
        if native_alpha < 0.999:
            class_spec, source, alpha = glass_spec, "native_alpha", native_alpha
        if class_spec is None:
            hit = lookup_by_part(transparent_by_part, obj.name)
            if hit is not None:
                class_spec, source = hit, "glass"
                alpha = float(hit.get("alpha", 0.5))
        if class_spec is None:
            hit = lookup_by_part(cad_by_part, obj.name)
            if hit is not None:
                class_spec, source = hit, "cad"
        if class_spec is None:
            for patterns, spec in rules:
                if matches_any(obj.name, patterns):
                    class_spec, source = spec, "rule"
                    break
        if class_spec is None and native_name:
            for patterns, spec in natives:
                if any(p.search(native_name) for p in patterns):
                    class_spec, source = spec, "native"
                    native_families[native_name] = native_families.get(native_name, 0) + 1
                    break
        if class_spec is None:
            class_spec = default_spec

        # -- 颜色轴(按件): 纠错表 > 原生直采(含白灰) > 类回退色 -----------------
        if class_spec.get("force_color"):
            color_hex = class_spec.get("base_color")
            color_from["fallback"] += 1
        elif native_rgb is not None:
            exact = "#%02X%02X%02X" % tuple(
                max(0, min(255, round(linear_to_srgb(c) * 255))) for c in native_rgb
            )
            fixed = recolor_map.get(exact.lstrip("#"))
            if fixed is not None:
                rgba = hex_to_rgba(fixed, 1.0)
                color_hex = quantized_hex((rgba[0], rgba[1], rgba[2]))
                color_from["recolor"] += 1
            else:
                color_hex = quantized_hex(native_rgb)
                color_from["native"] += 1
            native_colors[color_hex] = native_colors.get(color_hex, 0) + 1
        else:
            color_hex = class_spec.get("base_color")
            color_from["fallback"] += 1

        chosen = material_for(class_spec, color_hex, alpha)
        obj.data.materials.clear()
        obj.data.materials.append(chosen)
        counts[chosen.name] = counts.get(chosen.name, 0) + 1
        sources[source] += 1

    log(
        f"材质: {len(counts)} 种实例; "
        f"物性来源 功能覆盖={sources['override']} 原生透明={sources['native_alpha']} "
        f"CAD透明={sources['glass']} CAD真实={sources['cad']} 物性规则={sources['rule']} "
        f"原生外观={sources['native']} 兜底={sources['default']}"
    )
    log(
        f"  颜色来源 原生直采={color_from['native']} 纠错={color_from['recolor']} "
        f"类回退={color_from['fallback']}"
    )
    if native_families:
        top = sorted(native_families.items(), key=lambda kv: -kv[1])[:8]
        log("  原生外观命中: " + ", ".join(f"{n}×{c}" for n, c in top))
    if native_colors:
        top = sorted(native_colors.items(), key=lambda kv: -kv[1])[:12]
        log("  直采色分布: " + ", ".join(f"{h}×{c}" for h, c in top))
    top_counts = sorted(counts.items(), key=lambda kv: -kv[1])[:20]
    log("  用量前 20: " + ", ".join(f"{k}={v}" for k, v in top_counts))
    unused_overrides = sorted(set(manual_overrides) - consumed_overrides)
    if manual_overrides:
        log(f"  人工覆盖(实例名透传): 套用 {len(consumed_overrides)}/{len(manual_overrides)} 条")
    # 这里**不再警告** unused: assign_materials 只是覆盖的消费方之一, metal_material/
    # 泵饰件等直建路径此刻还没跑 —— 在这里判"未命中"必然误报(MAT_NAT_* 全中枪)。
    # 权威判定移到收尾的 apply_manual_override_postpass: 那时全部实例已建齐, 报出来的
    # 才是真死键。本返回值里的 unused_manual_overrides 同理只是中间量, 报告落盘前会被
    # 收尾补写的结果覆盖(见 main() 挂点)。
    return {
        "counts": counts, "sources": sources, "colors": color_from,
        "manual_overrides_used": sorted(consumed_overrides),
        "unused_manual_overrides": unused_overrides,
    }


def _plain_match(name: str, spec: dict) -> bool:
    """
    功能: 朴素子串匹配(contains / endswith / equals 组合), 比对前剥掉 .001 后缀.

    机器人零件名里满是 ^ ( ) 等正则特殊字符(如 `25-JIONT_ASM_4_ASM^CR5-MODLE(2)_...`),
    用正则要处处转义, 一个漏了就静默失配 —— 关节装配这种"错一个就全错"的场合用朴素匹配.

    特例: equals 自带 `.NNN` 副本后缀 = 指名道姓要 Blender 去重命名后的那一个实例.
    孪生机构(玻璃上料/下料)内部零件连实例号都同名, 前端从 raw.glb 看到并保存的就是
    去重名(如 `…连接板-1.001`); 同一输入文件的导入去重是确定性的, 正式链里同名对象
    拿到同一个后缀, 按原样精确比对即可锁定实例(inventory 段引用 .006 等已是既有惯例).

    参数:
        name: 对象名
        spec: {contains?, endswith?, equals?}
    返回值: bool, 是否匹配(空规格视为不匹配)
    """
    if not spec:
        return False
    base = _base_name(name)
    if "equals" in spec:
        expected = str(spec["equals"])
        if re.search(r"\.\d{3}$", expected):
            if name != expected:
                return False
        elif base != expected:
            return False
    if "contains" in spec and spec["contains"] not in base:
        return False
    if "endswith" in spec and not base.endswith(spec["endswith"]):
        return False
    return True


def _find_one(spec: dict, prefer_empty: bool = True) -> Any:
    """
    功能: 按朴素规格找唯一对象; 多命中时优先空节点(装配组), 再取名字最短者.

    关节壳是"空节点 + 同名前缀的网格子件"的结构, 网格子件名往往包含父装配名,
    因此 contains 匹配天然多命中 —— 优先空节点恰好取到装配组本身.

    参数:
        spec: 匹配规格
        prefer_empty: 是否优先空节点
    返回值: 对象或 None
    """
    hits = [obj for obj in bpy.data.objects if _plain_match(obj.name, spec)]
    if not hits:
        return None
    if len(hits) > 1 and prefer_empty:
        empties = [obj for obj in hits if obj.type == "EMPTY"]
        if len(empties) == 1:
            return empties[0]
        if empties:
            hits = empties
    hits.sort(key=lambda obj: len(obj.name))
    return hits[0]


def _find_all(spec: dict, pool: Any = None) -> list:
    """
    功能: 按朴素规格找出**全部**命中对象, 按名字排序保证结果确定.

    _find_one 取唯一对象, 但同一零件常有多个实例(吸盘工具的 `加强筋` 有 4 件、
    `SAB22-KQ2E06` 有 2 件), 按 contains 聚合散件时必须全取.

    参数:
        spec: 匹配规格
        pool: 候选对象序列; 缺省时在全场景里找
    返回值: list, 命中对象(可能为空)
    """
    candidates = bpy.data.objects if pool is None else pool
    return sorted(
        (obj for obj in candidates if _plain_match(obj.name, spec)),
        key=lambda obj: obj.name,
    )


def _to_gl(vector: Vector) -> list[float]:
    """功能: Blender Z-up 向量 → glTF Y-up 写法 (x,y,z)->(x,z,-y). 参数: vector. 返回值: list"""
    return [round(vector.x, 4), round(vector.z, 4), round(-vector.y, 4)]


# rig_map 里凡是写 `axis: x|y|z` 的字段(gap_check.axis / pivot.axis)一律是 **Blender 轴系**
# (Z 向上), 与 translate 那套 glTF 轴向量(Y 向上)不是一回事 —— 见 rig_map.yaml 头注绊线.
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _gl_translation_to_blender(vector) -> Vector:
    """glTF Y-up translation (x,y,z) -> Blender Z-up translation (x,-z,y)."""
    return Vector((float(vector[0]), -float(vector[2]), float(vector[1])))


# 官方 base_link.STL: 主体是 Ø148 圆(局部 |y|≤74mm), y>74.5mm 的凸起全部属于电缆航插.
# 该网格由 rig_map 的固定提交锁定(37730d08), 阈值经 Blender 试删+渲染核对后写定.
BASE_CONNECTOR_Y_M = 0.0745


def strip_base_connector(obj) -> dict:
    """
    功能: 删除官方底座网格上的电缆航插(正式产物减配用), 并只补插头留下的开口.

    base_link.STL 是单一连通壳体, 插头不是独立面岛, 只能按区域删面. 判据用网格
    局部坐标(即 STL 坐标; colorize_link 的 separate/join 不改动顶点坐标).
    补洞只针对删除后**新出现**的边界边 —— 网格自带的开放边(底面口等 24 条)绝不能
    误封; 识别靠删除前记录的边中点坐标集合(量化 0.1mm), 顶点索引在删除后会重排
    所以不可用索引对比.

    参数: obj CR5_BASE 对象(在 colorize 之后调用, 网格只有一个 BODY 材质槽,
          holes_fill 的新面继承槽 0, 无需另行赋材质)
    返回值: dict, 删面/补洞统计(写入 03 报告)
    """
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    def edge_key(edge):
        mid = (edge.verts[0].co + edge.verts[1].co) / 2.0
        return (round(mid.x, 4), round(mid.y, 4), round(mid.z, 4))

    pre_boundary = {edge_key(e) for e in bm.edges if e.is_boundary}
    doomed = [v for v in bm.verts if v.co.y > BASE_CONNECTOR_Y_M]
    faces_before = len(bm.faces)
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    faces_deleted = faces_before - len(bm.faces)

    hole_edges = [e for e in bm.edges if e.is_boundary and edge_key(e) not in pre_boundary]
    filled = bmesh.ops.holes_fill(bm, edges=hole_edges, sides=0) if hole_edges else {"faces": []}
    still_open = sum(1 for e in bm.edges if e.is_boundary and edge_key(e) not in pre_boundary)

    bm.to_mesh(mesh)
    bm.free()
    result = {
        "faces_deleted": faces_deleted,
        "hole_edges": len(hole_edges),
        "faces_filled": len(filled.get("faces", [])),
        "still_open": still_open,
    }
    log(f"底座航插减配: 删 {faces_deleted} 面, 补 {result['faces_filled']} 面, 残留开边 {still_open}")
    return result


def build_robot_joints(
    rig_map: dict,
    materials_config: dict | None = None,
    *,
    place_at_cad: bool = False,
    bake_joints_deg: list | None = None,
    strip_connector: bool = False,
) -> dict:
    """
    功能: 用固定提交的官方 STL 与 xacro 数据重建 CR5 刚体链.

    每轴层级严格为 ORIGIN(官方 xyz/rpy) -> ROTOR(单位旋转, local-Z) -> Link 网格。
    不再读取包围盒中心、叉乘猜轴或让网格发生骨骼/缩放变形。

    参数:
        rig_map: rig_map.yaml 内容
        materials_config: materials.yaml 内容; 官方 STL 不带任何材质, 连杆的
            白/灰/蓝分层按 rules 段的 MAT_ROBOT_* 规则名取色(色值唯一来源不变)
        place_at_cad: True(raw 阶段/装配台)时臂放回 CAD 老臂的原摆放位而非标定
            参考轨位 —— raw 链不跑 build_axis_carriages, 安装座留在 CAD 原地,
            用注册位臂会悬在轨道中段
        bake_joints_deg: 非空(raw 阶段)时把这组**控制器**六轴角静态烘进 ROTOR,
            公式与前端 RobotJointDriver 完全一致; None 则保持零位(full 阶段,
            姿态由前端实时驱动)
        strip_connector: True(full 阶段/正式减配产物)时删除底座电缆航插;
            raw 阶段保持 False, 装配台展示全量原貌
    返回值: dict, 装配结果(含各关节枢轴与轴向, glTF Y-up 坐标)
    """
    spec = rig_map.get("robot") or {}
    kinematics = spec.get("kinematics") or {}
    calibration = spec.get("calibration_data") or {}
    joints = calibration.get("joints") or []
    mesh_dir = kinematics.get("mesh_dir")
    if not spec.get("joints_rigged") or len(joints) != 6 or not mesh_dir:
        return {"rigged": False, "reason": "缺少官方运动学/六轴标定"}
    if calibration.get("kinematics_source", {}).get("commit") != kinematics.get("commit"):
        return {"rigged": False, "reason": "官方模型提交与标定提交不一致"}
    mesh_files = [os.path.join(mesh_dir, "base_link.STL")] + [
        os.path.join(mesh_dir, f"J{index}.STL") for index in range(1, 7)
    ]
    missing_meshes = [path for path in mesh_files if not os.path.isfile(path)]
    if missing_meshes:
        return {"rigged": False, "reason": f"官方网格缺失: {missing_meshes}"}

    root_patterns = compile_patterns([spec.get("pattern", "^DOBOT")])
    old_root = next((obj for obj in bpy.data.objects if matches_any(obj.name, root_patterns)), None)
    if old_root is None:
        return {"rigged": False, "reason": "找不到旧 DOBOT 定位根节点"}
    # 在任何 reparent/删除之前记录 CAD 老臂原位(硬约束 9: 先 update 再读矩阵).
    # 已量测: 老臂装配原点的 x/y 即底座轴心(与基座网格 bbox 中心一致到 1mm).
    bpy.context.view_layer.update()
    old_translation = old_root.matrix_world.translation.copy()

    # 机器人基座不再沿用 CAD 中任意姿态，而使用 P8/P9/P10 与三个工具快换接口拟合的
    # 绝对场景注册。矩阵记录 robot XYZ -> glTF Y-up；Blender 根节点保持单位旋转，
    # 因为导出器本身完成 (x,y,z)->(x,z,-y) 的固定换基。
    scene_registration = calibration.get("scene_registration") or {}
    registration_matrix = (
        scene_registration.get("base_transform_at_reference_rail") or {}
    ).get("matrix")
    expected_axis_map = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)))
    if not registration_matrix or len(registration_matrix) != 4:
        raise RuntimeError("缺少 scene_registration.base_transform_at_reference_rail")
    actual_axis_map = Matrix([row[:3] for row in registration_matrix[:3]])
    if any(abs(actual_axis_map[row][col] - expected_axis_map[row][col]) > 1e-8 for row in range(3) for col in range(3)):
        raise RuntimeError("当前 Blender 管线仅接受版本化的 robot XYZ -> glTF Y-up 固定轴映射")
    base_location = _gl_translation_to_blender([row[3] for row in registration_matrix[:3]])
    if place_at_cad:
        # 装配台: 水平位对齐 CAD 原摆放(坐回黑色安装座); 高度仍用注册值 ——
        # 已量测两臂底面同高, 而 CAD root 原点不在底面, 其 z 不可直接用.
        base_location = Vector((old_translation.x, old_translation.y, base_location.z))

    custom_members = []
    for member_spec in spec.get("custom_mount_members") or []:
        member = _find_one(member_spec)
        if member is not None and member not in custom_members:
            if old_root.parent is not None:
                reparent(member, old_root.parent)
            else:
                bpy.context.view_layer.update()
                world = member.matrix_world.copy()
                member.parent = None
                member.matrix_world = world
            custom_members.append(member)

    # 删除旧 CR5 CAD 本体；自制法兰/快换已在上一步脱离并保留世界变换。
    def descendants(node):
        result = []
        for child in list(node.children):
            result.extend(descendants(child))
            result.append(child)
        return result

    old_parent = old_root.parent
    for child in descendants(old_root):
        if child.name in bpy.data.objects:
            bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.objects.remove(old_root, do_unlink=True)

    def parent_local(child, parent):
        child.parent = parent
        child.matrix_parent_inverse = Matrix.Identity(4)
        child.matrix_basis = Matrix.Identity(4)

    official_root = new_empty("CR5_BASE_FRAME")
    if old_parent is not None:
        official_root.parent = old_parent
    official_root.matrix_world = Matrix.Translation(base_location)
    base_transform = scene_registration
    official_root.scale = (1.0, 1.0, 1.0)

    # -- 官方连杆着色 --------------------------------------------------------
    # STL 不携带材质, 且 assign_materials 跑在换臂之前(旧 CAD 本体在那一步已被
    # 着色又随后删除), 所以这里必须自己实例化. 色值仍只认 materials.yaml rules
    # 段的 MAT_ROBOT_* 规则(按规则名索引), 材质名沿用 MAT_<类>_<HEX> 约定以便
    # 与 assign_materials 的实例去重.
    rule_specs = {
        spec.get("name"): spec
        for spec in (materials_config or {}).get("rules", [])
        if spec.get("name")
    }

    def robot_material(rule_name: str):
        """功能: 按 rules 规则名实例化机器人材质. 参数: rule_name. 返回值: Material"""
        spec = rule_specs.get(rule_name) or rule_specs.get("MAT_ROBOT_BODY") or {
            "name": "MAT_ROBOT_BODY",
            "base_color": "#F0F1F3",
            "roughness": 0.5,
            "metalness": 0.05,
        }
        named = dict(spec)
        hex_part = str(spec.get("base_color", "#F0F1F3")).lstrip("#").upper()
        named["name"] = f"{spec.get('name', rule_name)}_{hex_part}"
        return build_material(named)

    # J2 连杆是"肩关节+大臂+肘关节"一体网格, 实机大臂为灰; 底座为灰; 其余连杆白.
    link_body_rule = {"CR5_BASE": "MAT_ROBOT_BASE", "CR5_LINK2": "MAT_ROBOT_ARM"}

    def smooth_by_angle(obj, fallback_flat=False):
        """
        功能: 按 40° 阈值重算锐边与平滑着色.

        参数: obj 目标对象; fallback_flat 算子不可用时是否退化为"全平滑" ——
              仅首次导入(还没有任何着色信息)时才该退化; 拓扑变动后的**重算**
              若退化成全平滑, 反而会把已有锐边全抹平, 故默认 False(保持现状).
        返回值: None(就地改对象)
        """
        try:
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40.0))
        except Exception:
            if fallback_flat:
                for poly in obj.data.polygons:
                    poly.use_smooth = True

    def finalize_link_shading(obj):
        """
        功能: 连杆着色定稿 = 40° 重算平滑 + 面积加权法线.

        端盖缘圈与筒壁之间有一圈 25~40° 的小倒角面, 低于 40° 平滑阈值被一起
        平滑; 小面把缘圈顶点的法线往端盖方向拽, 沿筒壁长三角形插值出一条条
        从缘圈下垂渐隐的楔形明暗"牙齿"(用户两次报告的伪影). 同机位 A/B 实测:
        把阈值降到 30° 都除不净(倒角还有 25~30° 的边), 只有面积加权法线有效 ——
        FACE_AREA + weight 50 = 纯面积加权, 大筒壁面主导顶点法线, 小倒角面
        失去话语权; keep_sharp 保住 40° 锐边(端盖缘圈依旧锐利).

        参数: obj 目标对象(几何与选面已定稿). 返回值: None(就地改法线)
        """
        smooth_by_angle(obj)
        try:
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            mod = obj.modifiers.new("WN_FINALIZE", 'WEIGHTED_NORMAL')
            mod.mode = 'FACE_AREA'
            mod.weight = 50
            mod.keep_sharp = True
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except Exception:
            # 失败就保持 smooth_by_angle 的结果, 但绝不能把未应用的修改器留在
            # 对象上 —— glTF 导出会再应用一次或直接报错.
            for mod in [m for m in obj.modifiers if m.name == "WN_FINALIZE"]:
                obj.modifiers.remove(mod)

    def paint_seam_bands(body_obj, seam_anchors, link_name):
        """
        功能: 以官方环形薄壳为标尺, 直接在连杆表面改色(不生成新几何).

        官方 CR 系效果图的造型语言: 蓝环只出现在**连杆贴合缝**(网格上的可见
        接缝 = 锐边环/边界环, 不一定与薄壳锚点共面 —— 带心先平移到检测出的
        接缝棱线, 否则环会停在筒身半途被截断); 端盖面是深灰底 + 白色浮雕
        logo. 锚点按版本锁定网格(37730d08)分流:
          - 贴合缝环(各连杆最大径类; LINK2 需按轴向位置排除 Ø112 台阶环)
            → 平移到接缝后画 8mm 蓝带, 选面用环向 48 扇区找最近表面;
          - 端盖顶缘环(小径类)与 J4/J5/J6 的筒端 → 端盖区: 法线∥轴的面按
            轴向位置聚类(1mm 桶、面积加权), **面积最大的层=底面涂深灰, 其余
            凸起层(logo/缘圈)涂白** —— 各关节浮雕深度不同, 固定阈值会把浅
            浮雕端盖整片涂成同色(白底白标看不见).

        参数: body_obj 连杆主壳体, seam_anchors [(center, axis, r_out)](局部系),
              link_name 连杆名
        返回值: None
        """
        if not seam_anchors and link_name != "CR5_LINK6":
            return
        import bmesh

        seams = []
        cap_zones = []  # (center, axis, t_lo, t_hi, radial_max, min_norm)
        motor_anchor = None  # LINK4/5 的 Y 轴叉臂锚点, 供电机端盖区定轴(即使不画环)
        for center, axis, r_out in seam_anchors:
            if link_name == "CR5_LINK2" and r_out > 0.05 and abs(center.z - 0.0802) > 0.02:
                continue  # Ø112 端盖台阶装饰环: 效果图此处既无蓝环也无灰盖
            if link_name in ("CR5_LINK4", "CR5_LINK5"):
                motor_anchor = (center, axis)
            if link_name == "CR5_LINK5":
                continue  # LINK5 的 Y 轴叉臂环: 垂直于 J6 旋转缝、"穿缝而过", 用户判错
            small = (
                (link_name in ("CR5_LINK1", "CR5_LINK2") and r_out < 0.05)
                or (link_name == "CR5_LINK3" and r_out < 0.035)
            )
            if small:
                cap_zones.append((center, axis, -0.006, 0.006, r_out * 1.6, 0.5))
            else:
                seams.append((center, axis, r_out))

        # -- 旋转缝环(与关节旋转轴同心, 显式标定) ------------------------------
        # 用户定义的物理语义: 蓝环与关节旋转轴同心、与旋转缝平行 —— 关节转动时
        # 环绕自身轴同心转. 位置为版本锁定网格 37730d08 实测: J5 原点 z=0
        # 位于腕部开叉交叠区; 端盖接缝约 z=-0.049. J6 可见棱线 z≈-7mm.
        rotation_rings = {
        # 蓝带贴住 J5 端盖接缝; 内缘留在 J5 一侧,
            # 外缘由零件自身 z=-49mm 的接缝边界收口, 避免跨进开叉区产生锯齿.
        "CR5_LINK5": (-0.04790, 0.036),
            "CR5_LINK6": (-0.008, 0.036),  # 实证局部 z=0 为法兰侧, 棱线在 z≈-8
        }
        rotation_band_halves = {
            "CR5_LINK5": 0.0030,  # J5 可见蓝带加宽; J6 保持原 5mm 带宽
        }
        rotation_seams = []
        if link_name in rotation_rings:
            z_seam, r_ref = rotation_rings[link_name]
            rotation_seams.append((Vector((0.0, 0.0, z_seam)), Vector((0.0, 0.0, 1.0)), r_ref))

        # J4/J5 沿 Y 筒、J6 沿 Z 筒的两端(电机端盖/外端盖)也是端盖区; 两端全涂,
        # 藏在配合面里的那端涂了也看不见, 免去方向判断.
        cap_axis_center = None
        if link_name in ("CR5_LINK4", "CR5_LINK5") and motor_anchor is not None:
            cap_axis_center = motor_anchor
        elif link_name == "CR5_LINK6":
            cap_axis_center = (Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0)))
        if cap_axis_center is not None:
            center, axis = cap_axis_center
            spans = [(Vector(corner) - center).dot(axis) for corner in body_obj.bound_box]
            for end, inward in ((min(spans), 1.0), (max(spans), -1.0)):
                lo, hi = sorted((end, end + inward * 0.012))
                cap_zones.append((center, axis, lo, hi, 0.044, 0.4))

        half = 0.004
        mesh = body_obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)

        # -- 蓝带轴向偏移: 显式逐环标定表(版本锁定网格 37730d08) ---------------
        # 自动找接缝棱线(锐边直方图)在大关节上会抓到别的装饰棱线, 把原本位置
        # 正确的环拽偏, 已废弃. 未列出的环不平移(留在官方薄壳锚点平面).
        # 键 = (连杆名, 环外径 mm, 环心沿自身轴投影 cm); 值 = 沿轴偏移(米).
        ring_shift = {}
        ring_skip = {
            ("CR5_LINK3", 38, -6),  # 删除 J4 前方的粗环
            ("CR5_LINK4", 29, -3),  # 删除误画在 J4 壳体一侧的细环
        }
        shifted_seams = []
        for center, axis, r_ring in seams:
            key = (link_name, round(r_ring * 1000), round(center.dot(axis) * 100))
            if key in ring_skip:
                log(f"贴合缝环 {key} 已停用")
                continue
            offset = ring_shift.get(key, 0.0)
            log(f"贴合缝环 {key} 偏移 {offset * 1000:.0f}mm")
            shifted_seams.append((center + axis * offset, axis, r_ring, False))
        for center, axis, r_ring in rotation_seams:
            log(f"旋转缝环 {(link_name, round(r_ring * 1000), round(center.z * 1000))}")
            shifted_seams.append((center, axis, r_ring, True))

        cuts = []
        for center, axis, _r_out, is_rot in shifted_seams:
            band_half = rotation_band_halves.get(link_name, 0.0025) if is_rot else half
            cuts += [(center + axis * off, axis) for off in (-band_half, band_half)]
        for plane_co, plane_no in cuts:
            bmesh.ops.bisect_plane(
                bm,
                geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                plane_co=plane_co,
                plane_no=plane_no,
                clear_outer=False,
                clear_inner=False,
            )
        # 每刀都以整根连杆为 geom(旋转环带平面更是纵切全杆), 平面掠过既有顶点时
        # 会切出**零面积碎片**: 实测 J2 一根就 738 个. 碎片本身不可见, 却参与
        # shade_smooth 的顶点法线平均, 把上臂照出楔形黑白条带(法线偏差>30° 的面
        # 占比 2.3%→16.6%). 上色**之前**先清掉, 让后续选面也基于干净拓扑;
        # 1e-5 m = 0.01mm, 远小于 5~8mm 带宽, 不会动到蓝带.
        bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges)

        slots = {}
        for key, rule in (("COVER", "MAT_ROBOT_COVER"), ("LOGO", "MAT_ROBOT_BODY"), ("TRIM", "MAT_ROBOT_TRIM")):
            mesh.materials.append(robot_material(rule))
            slots[key] = len(mesh.materials) - 1

        # -- 端盖区: 两类配色 ---------------------------------------------------
        # 多平层端盖(J1/J2, 浮雕深 3-4mm): 层位法 —— 最大面积平层为灰底, 整面
        #   所有顶点沿外向高出 ≥1.2mm 的凸台面(商标/缘圈顶)涂白, 触底面排除防锯齿;
        # 单平层/穹面端盖(J4/J5 电机盖、J6 外端、J3 腕盖): 无可用层位, 按官方图
        #   "白缘圈-灰盘面-白商标"做**径向三区**: radial≥0.78R 白圈, ≤0.32R 白标.
        for center, axis, t_lo, t_hi, radial_max, min_norm in cap_zones:
            zone_faces = []
            flat_hist = {}
            beyond_hi = 0
            beyond_lo = 0
            max_radial = 0.0
            for face in bm.faces:
                p = face.calc_center_median()
                t = (p - center).dot(axis)
                rho = ((p - center) - t * axis).length
                if rho > radial_max:
                    continue
                if t > t_hi + 0.005:
                    beyond_hi += 1
                    continue
                if t < t_lo - 0.005:
                    beyond_lo += 1
                    continue
                nd = abs(face.normal.dot(axis))
                if nd < min_norm:
                    continue  # 筒壁面法线垂直于轴, 不属于端盖面
                if not (t_lo - 1e-4) <= t <= (t_hi + 1e-4):
                    continue
                if nd >= 0.92:
                    bucket = round(t * 1000.0)
                    flat_hist[bucket] = flat_hist.get(bucket, 0.0) + face.calc_area()
                zone_faces.append((face, rho))
                max_radial = max(max_radial, rho)
            if not zone_faces:
                continue
            major_levels = [b for b, area in flat_hist.items() if area >= 0.0002]
            multi_level = bool(major_levels) and (max(major_levels) - min(major_levels)) >= 2
            if multi_level:
                outward = 1.0 if beyond_hi <= beyond_lo else -1.0
                base_bucket = max(flat_hist, key=flat_hist.get)
                base_t = base_bucket / 1000.0
                for face, _rho in zone_faces:
                    depth = min(
                        ((vert.co - center).dot(axis) - base_t) * outward
                        for vert in face.verts
                    )
                    face.material_index = slots["LOGO"] if depth >= 0.0012 else slots["COVER"]
            else:
                for face, rho in zone_faces:
                    if rho >= max_radial * 0.78 or rho <= max_radial * 0.32:
                        face.material_index = slots["LOGO"]
                    else:
                        face.material_index = slots["COVER"]

        # -- 蓝带: 环向 48 扇区逐扇区找最近表面, 全周连续 ----------------------
        # 旋转缝环额外要求**面法线与环轴的径向对齐**(|n·radial|≥0.7)且径向窗口
        # 收紧到 [r-6, r+10]mm: 它的带平面会纵切整根连杆(电机筒壁/端盖面/法兰面
        # 都会被切到), 不加判据会画出闪电状蓝斑与法兰染蓝 —— 只有绕环轴的套环
        # 壁面才满足径向对齐.
        for center, axis, r_ring, is_rot in shifted_seams:
            u_ref = axis.orthogonal().normalized()
            v_ref = axis.cross(u_ref)
            band_half = rotation_band_halves.get(link_name, 0.0025) if is_rot else half
            r_lo = 0.005 if is_rot else 0.006
            r_hi = 0.010 if is_rot and link_name == "CR5_LINK5" else (0.006 if is_rot else 0.025)
            candidates = []
            for face in bm.faces:
                p = face.calc_center_median()
                t = (p - center).dot(axis)
                if abs(t) > band_half + 1e-5:
                    continue
                d = (p - center) - t * axis
                rho = d.length
                if not (r_ring - r_lo) <= rho <= (r_ring + r_hi):
                    continue
                if is_rot and rho > 1e-6:
                    radial_dir = d / rho
                    min_radial_alignment = 0.75 if link_name == "CR5_LINK5" else 0.8
                    if abs(face.normal.dot(radial_dir)) < min_radial_alignment:
                        continue
                theta = math.atan2(d.dot(v_ref), d.dot(u_ref))
                sector = int((theta + math.pi) / (2.0 * math.pi) * 48.0) % 48
                candidates.append((face, rho, sector))
            sector_min = {}
            for _face, rho, sector in candidates:
                if sector not in sector_min or rho < sector_min[sector]:
                    sector_min[sector] = rho
            if is_rot and link_name == "CR5_LINK5":
                # J5 已标定到端部唯一的圆柱套环; 这里不做逐扇区最近层裁剪, 否则
                # 三角面中心跨过带边界时会漏染, 在圆环上缘留下锯齿状白口.
                for face, _rho, _sector in candidates:
                    face.material_index = slots["TRIM"]
                continue
            for face, rho, sector in candidates:
                if rho <= sector_min[sector] + 0.012:
                    face.material_index = slots["TRIM"]
        bm.to_mesh(mesh)
        bm.free()
        # 40° 阈值是在切割**之前**算的(import_stl), 切口产生的新边不带锐边标记;
        # 最终拓扑上的重算+面积加权定稿由 colorize_link 在本函数返回后统一做
        # (finalize_link_shading), 那条路径对无锚点早退的 CR5_BASE 也生效.

    def colorize_link(obj, name):
        """
        功能: 按松散壳体给一根官方连杆重建实机三色分层, 蓝环直接画在连杆表面.

        官方网格把关节面装饰做成独立薄壳. 其中**环形**薄壳位于两连杆贴合面
        之间, 装配后完全不可见 —— 但其位置/薄轴/外径精确标注了接缝, 故只拿
        它当标尺(paint_seam_bands 在主壳体表面就地改色), 本体删除. **盘形**
        薄壳是外露的 logo 端盖(灰, 微加厚防共面闪烁); 最大边≤15mm 碎件是
        法兰螺钉(金属灰); Link6 的附件是裸金属法兰盘; 其余壳体跟随连杆整体
        色. 主壳体保留原名(gen_twin_manifest 按 CR5_LINK6 找法兰).

        参数: obj 导入的连杆对象, name 连杆名(CR5_BASE/CR5_LINK1..6)
        返回值: None(就地改场景)
        """
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.separate(type="LOOSE")
        bpy.ops.object.mode_set(mode="OBJECT")
        islands = [o for o in bpy.context.selected_objects if o.type == "MESH"]
        main = max(islands, key=lambda o: len(o.data.vertices))
        # 分离后原对象仍占用连杆名且不保证是主壳体; 先全部改临时名, 保证最终
        # 主壳体改回连杆名时不会因重名被 Blender 追加 .001 后缀.
        for index, island in enumerate(islands):
            island.name = f"{name}__tmp{index}"

        seam_anchors = []
        ring_shells = []
        buckets: dict[str, list] = {}
        for island in islands:
            dims = [island.dimensions.x, island.dimensions.y, island.dimensions.z]
            order = sorted(range(3), key=lambda i: dims[i])
            if island is main:
                buckets.setdefault("BODY", []).append(island)
                continue
            if dims[order[0]] <= 0.002 and dims[order[2]] >= 0.04:
                # 薄贴饰按环形度分流: 环(有大孔)是接缝标尺, 盘(实心)是 logo 端盖.
                axis = Vector((0.0, 0.0, 0.0))
                axis[order[0]] = 1.0
                center = Vector((0.0, 0.0, 0.0))
                for corner in island.bound_box:
                    center += Vector(corner)
                center /= 8.0
                r_out = dims[order[2]] / 2.0
                r_in = min(
                    ((v.co - center) - (v.co - center).dot(axis) * axis).length
                    for v in island.data.vertices
                )
                if r_in / max(r_out, 1e-6) >= 0.6:
                    seam_anchors.append((center.copy(), axis, r_out))
                    ring_shells.append(island)
                else:
                    buckets.setdefault("COVER", []).append(island)
                continue
            if dims[order[2]] <= 0.015 or name == "CR5_LINK6":
                buckets.setdefault("WRIST", []).append(island)
            else:
                buckets.setdefault("BODY", []).append(island)

        # 环形薄壳只当标尺, 本体删除 —— 它埋在贴合面之间, 永远不可见.
        for shell in ring_shells:
            bpy.data.objects.remove(shell, do_unlink=True)

        # logo 端盖只有 0.4~1.2mm 厚, 沿薄轴微加厚, 防与壳体面共面闪烁.
        def thicken(island, target_m):
            """功能: 把薄壳沿最薄轴对称加厚到 target_m. 参数: island, 目标厚度(米). 返回值: None"""
            extents = [island.dimensions.x, island.dimensions.y, island.dimensions.z]
            axis = extents.index(min(extents))
            current = max(extents[axis], 1e-5)
            if current >= target_m:
                return
            factor = target_m / current
            verts = island.data.vertices
            center = sum((v.co[axis] for v in verts), 0.0) / max(len(verts), 1)
            for vert in verts:
                vert.co[axis] = center + (vert.co[axis] - center) * factor
        for island in buckets.get("COVER", []):
            thicken(island, 0.002)

        bucket_rules = {
            "BODY": link_body_rule.get(name, "MAT_ROBOT_BODY"),
            "COVER": "MAT_ROBOT_COVER",
            "WRIST": "MAT_ROBOT_WRIST",
        }
        suffixes = {"BODY": "", "COVER": "_CAP", "WRIST": "_HW"}
        for key, members in buckets.items():
            target = main if main in members else members[0]
            bpy.ops.object.select_all(action="DESELECT")
            for member in members:
                member.select_set(True)
            bpy.context.view_layer.objects.active = target
            if len(members) > 1:
                bpy.ops.object.join()
            target.name = name if key == "BODY" else f"{name}{suffixes[key]}"
            material = robot_material(bucket_rules[key])
            target.data.materials.clear()
            target.data.materials.append(material)
            if key != "BODY":
                # _CAP/_HW 岛几何到此定稿(join/thicken 已完成); 主壳体还要过
                # paint_seam_bands 的切割, 在下面统一定稿.
                finalize_link_shading(target)

        paint_seam_bands(main, seam_anchors, name)
        # 无条件定稿: CR5_BASE 无接缝锚点, paint_seam_bands 会直接 return,
        # 只有这里能给它做面积加权.
        finalize_link_shading(main)

    def import_stl(path, name, parent):
        bpy.ops.object.select_all(action="DESELECT")
        before = set(bpy.data.objects)
        bpy.ops.wm.stl_import(filepath=path)
        imported = [obj for obj in bpy.data.objects if obj not in before]
        if len(imported) != 1:
            raise RuntimeError(f"STL 导入对象数异常: {path} -> {len(imported)}")
        obj = imported[0]
        obj.name = name
        parent_local(obj, parent)
        # 官方 STL 不带法线平滑信息, 导入默认逐面平直着色, 圆柱臂身呈多边形
        # 棱带(比装配台 raw.glb 里的 CAD 原生网格"粗糙"). 按 40° 阈值平滑:
        # 圆面光顺, 法兰/棱边保留锐利. 注意 colorize_link 之后拓扑还会变(蓝带切割),
        # paint_seam_bands 结尾会在最终拓扑上再算一次.
        smooth_by_angle(obj, fallback_flat=True)
        colorize_link(obj, name)
        return obj

    base_obj = import_stl(mesh_files[0], "CR5_BASE", official_root)
    strip_report = strip_base_connector(base_obj) if strip_connector else None
    if strip_report is not None:
        # 删航插+补洞改了几何, colorize 阶段的定稿已失效, 重出一次.
        finalize_link_shading(base_obj)
    parent = official_root
    joints_report = []
    baked_report = []
    last_rotor = None
    for index, joint_spec in enumerate(joints, start=1):
        origin = new_empty(joint_spec.get("origin_node", f"CR5_J{index}_ORIGIN"))
        parent_local(origin, parent)
        origin.location = Vector(joint_spec["origin_xyz_m"])
        origin.rotation_euler = Euler(joint_spec["origin_rpy_rad"], "XYZ")

        rotor = new_empty(joint_spec.get("node", f"CR5_J{index}_ROTOR"))
        parent_local(rotor, origin)
        link_node = import_stl(mesh_files[index], f"CR5_LINK{index}", rotor)
        axis = Vector(joint_spec.get("axis", (0, 0, 1)))
        joints_report.append({
            "id": joint_spec["id"],
            "origin_node": origin.name,
            "node": rotor.name,
            "link_node": link_node.name,
            "axis": _to_gl(axis),
            "sign": joint_spec.get("sign", 1),
            "zero_offset_deg": joint_spec.get("zero_offset_deg", 0.0),
            "limit_deg": joint_spec.get("limit_deg"),
            "origin_xyz_m": joint_spec["origin_xyz_m"],
            "origin_rpy_rad": joint_spec["origin_rpy_rad"],
        })
        parent = rotor
        last_rotor = rotor

    # 装配台静态姿态: 在全部连杆导入与涂色**之后**统一烘焙, 保证 colorize_link 的
    # 几何判断(缝环分类等)与 full 链在完全相同的零位上下文里执行, 两条链产出的
    # 连杆网格逐面一致. 公式与前端 RobotJointDriver 完全一致
    # (model = controller*sign + zero_offset, 绕 ROTOR local-Z), 越限冻结为零位.
    if bake_joints_deg:
        for index, joint_spec in enumerate(joints, start=1):
            rotor = bpy.data.objects.get(joint_spec.get("node", f"CR5_J{index}_ROTOR"))
            if rotor is None:
                baked_report.append(None)
                continue
            model_deg = float(bake_joints_deg[index - 1]) * float(joint_spec.get("sign", 1)) + float(
                joint_spec.get("zero_offset_deg", 0.0)
            )
            limit = joint_spec.get("limit_deg")
            if (
                isinstance(limit, (list, tuple))
                and len(limit) == 2
                and not (float(limit[0]) - 1e-6 <= model_deg <= float(limit[1]) + 1e-6)
            ):
                log(f"警告: J{index} 烘焙角 {model_deg:.2f}° 越限 {limit}, 该轴保持零位")
                baked_report.append(None)
            else:
                rotor.rotation_euler = Euler((0.0, 0.0, math.radians(model_deg)), "XYZ")
                baked_report.append(round(model_deg, 4))
        bpy.context.view_layer.update()

    mount = new_empty(calibration.get("tool_mount_node", "TOOL_MOUNT"))
    parent_local(mount, last_rotor)
    # TOOL_MOUNT 是实体快换接口，绝不能复用控制器 Tool 1 TCP。两者轴向距离相差
    # 约 60.8 mm，混用会同时造成机器人悬空和快换脱离 Link6。
    mount_transform = calibration.get("physical_tool_mount") or {}
    if not str(mount_transform.get("status", "")).startswith("fitted"):
        raise RuntimeError("实体 Link6 法兰到快换接口的变换尚未标定")
    mount.location = Vector(mount_transform.get("translation_m", (0.0, 0.0, 0.0)))
    mount.rotation_euler = Euler(
        [math.radians(float(value)) for value in mount_transform.get("rpy_deg", (0.0, 0.0, 0.0))],
        "XYZ",
    )
    bpy.context.view_layer.update()

    # 自制法兰/QT219 的几何安装以原始 CAD 中正确接触的 Link6 法兰为事实源。
    # QT219 与工具侧 QT2091392 的“零件原点”不是配合坐标系；把两者直接重合会在
    # 官方 Link6 与自制法兰之间留下约 60 mm 间隙。下面的刚体矩阵由两版法兰网格
    # 配准得到，整组复用同一矩阵，保留 CAD 内部装配关系。
    quick_change_correction = {"applied": False, "reason": "无 custom_mount_members"}
    if custom_members:
        alignment = calibration.get("custom_mount_alignment") or {}
        matrix_rows = alignment.get("matrix_cad_world_to_link6") or []
        if not str(alignment.get("status", "")).startswith("fitted") or len(matrix_rows) != 4:
            raise RuntimeError("原始 CAD 自制末端到官方 Link6 的几何安装偏置尚未标定")
        cad_world_to_link6 = Matrix(matrix_rows)
        for member in custom_members:
            cad_world = member.matrix_world.copy()
            member.matrix_world = last_rotor.matrix_world @ cad_world_to_link6 @ cad_world
            reparent(member, last_rotor)
        # ICP 链(上面)与示教点链(TOOL_MOUNT)互相独立, 横向互差会直接变成取放对接
        # 错位; 在这里做反向吸收式同轴校正 + 硬门禁(机器人侧保持 CAD 原位,
        # TOOL_MOUNT 与工具站随动; 度量姿态无关, full/raw 共用).
        bpy.context.view_layer.update()
        quick_change_correction = _quick_change_lateral_correction(
            mount, custom_members, rig_map, calibration
        )

    log(
        f"机器人关节链: 官方 CR5 {kinematics.get('commit')}，"
        f"6 x ORIGIN/ROTOR + TOOL_MOUNT，自制末端 {len(custom_members)} 件"
    )
    return {
        "rigged": True,
        "kinematics_source": {
            "repository": kinematics.get("repository"),
            "commit": kinematics.get("commit"),
            "xacro": "cra_description/urdf/cr5_robot.xacro",
        },
        "calibration_version": calibration.get("version"),
        "reference_point_hash": calibration.get("reference_points", {}).get("sha256"),
        "base_transform": base_transform,
        "joints": joints_report,
        "flange_node": calibration.get("flange_node", "CR5_LINK6"),
        "tool_mount": {"node": mount.name},
        "tool_mount_transform": mount_transform,
        "quick_change_correction": quick_change_correction,
        "custom_mount_alignment": calibration.get("custom_mount_alignment", {}),
        "tool_transforms": calibration.get("tool_transforms", {}),
        "placed_at": "cad_origin" if place_at_cad else "scene_registration",
        "baked_model_deg": baked_report if bake_joints_deg else None,
        "base_connector": strip_report if strip_connector else "kept",
    }


def build_tools(rig_map: dict) -> dict:
    """
    功能: 把可更换工具(夹爪)子树登记为独立可重挂节点 TOOL_*.

    重命名根节点，并从 CAD 的 QT2091392 工具侧快换原点建立显式 DOCK 节点；静态合并
    (join_static_per_station)会因 TOOL_ 前缀跳过整棵子树 —— 换夹爪动画的
    attach 语义(three 的 Object3D.attach, 夹爪保世界变换换父)依赖它保持独立.

    两种声明方式:
      root:    CAD 里已经包成子装配的工具(96孔板/样品瓶), 直接抓那棵子树;
      members: CAD 里**没有**包成子装配的工具(1 号玻璃吸盘 —— `吸盘夹具支架/` 只有
               一个把工具与料架混在一起的 `玻璃夹具支架装配.SLDASM`), 按零件规格
               把散件聚起来再包成 `{id}_GEOMETRY`. 曾因缺这条通路而把吸盘误判为
               "CAD 缺少完整工具几何", 实际零件一直都在, 只是被静态合并吃掉了.

    参数:
        rig_map: rig_map.yaml 内容
    返回值: dict, 各工具的登记结果
    """
    results = []
    dock_frames = []
    def descendants(root):
        found = []
        for child in root.children:
            found.append(child)
            found.extend(descendants(child))
        return found

    def under_tool_root(obj) -> bool:
        """功能: 判断对象是否已被前序工具认领(祖先里有 TOOL_ 节点). 参数: obj. 返回值: bool"""
        node = obj
        while node is not None:
            if node.name.startswith("TOOL_"):
                return True
            node = node.parent
        return False

    def collect_members(tool: dict) -> list:
        """
        功能: 按 members 规格聚合散件; 跳过已被前序工具认领的对象与已入选者的后代.

        跳过"已认领"是 QT2091392 这种三把刀共用同一零件号的关键: slot-2/3 的两个实例
        此刻已经在 TOOL_PLATE96_GEOMETRY / TOOL_VIAL_GEOMETRY 之下, 于是同一条
        `contains: QT2091392` 只会剩下 slot-1 那一个。靠 `.002` 后缀区分是行不通的 ——
        _base_name 会把它剥掉。

        参数: tool 工具声明
        返回值: list, 成员对象
        """
        members: list = []
        for spec in tool.get("members") or []:
            hits = [obj for obj in _find_all(spec) if not under_tool_root(obj)]
            if not hits:
                raise RuntimeError(f"工具 {tool['id']} 的成员规格 {spec} 未命中任何对象")
            for obj in hits:
                if obj in members:
                    continue
                # 已入选成员的后代由父级整棵带走, 不重复登记
                if any(ancestor in members for ancestor in _ancestors(obj)):
                    continue
                members.append(obj)
        return members

    def _ancestors(obj) -> list:
        """功能: 列出对象的全部祖先. 参数: obj. 返回值: list"""
        chain = []
        node = obj.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        return chain

    for tool in rig_map.get("tools") or []:
        members = collect_members(tool) if tool.get("members") else []
        if members:
            home_parents = {obj.parent for obj in members}
            if len(home_parents) != 1 or None in home_parents:
                names = sorted((p.name if p else "<scene root>") for p in home_parents)
                raise RuntimeError(
                    f"工具 {tool['id']} 的成员分散在多个父级 {names}, 无法确定停靠父级"
                )
            home_parent = home_parents.pop()
            node = new_empty(f"{tool['id']}_GEOMETRY")
            reparent(node, home_parent)
            for member in members:
                reparent(member, node)
            log(f"工具 {tool['id']}: 按 members 聚合 {len(members)} 件散件")
        else:
            node = _find_one(tool.get("root") or {})
            if node is None:
                # 静默跳过会让 manifest 少一把刀, 而前端只是"取刀后什么都没有"——
                # 这正是 2026-08-01 吸盘 bug 的形态, 不许再有.
                raise RuntimeError(
                    f"工具 {tool.get('id')} 未匹配到子树 {tool.get('root')}; "
                    "若该工具在 CAD 里没有独立子装配, 请改用 members 声明"
                )
        lo, hi = object_world_bounds(node)
        connector_spec = tool.get("connector") or {}
        pool = members if members else descendants(node)
        connector = next(
            (item for item in pool if _plain_match(item.name, connector_spec)),
            None,
        )
        if connector is None:
            raise RuntimeError(f"工具 {tool['id']} 缺少已声明的快换接口 {connector_spec}")
        bpy.context.view_layer.update()
        dock_world = connector.matrix_world.copy()
        dock_frames.append((tool["id"], dock_world))

        # CAD 装配根原点离快换口很远，而且上游层级含复杂变换；直接 attach 该根会在
        # Three.js 重挂后放大微小旋转误差。建立单位 TOOL_* 包装根，把根原点固定在
        # CAD 快换接口，几何作为孩子保世界变换，之后锁紧时局部偏移接近零。
        home_parent = node.parent
        node.name = f"{tool['id']}_GEOMETRY"
        tool_root = new_empty(tool["id"])
        tool_root.matrix_world = dock_world
        if home_parent is not None:
            reparent(tool_root, home_parent)
        reparent(node, tool_root)

        dock_node = new_empty(f"{tool['id']}_DOCK")
        dock_node.matrix_world = dock_world
        reparent(dock_node, tool_root)
        dock = dock_world.translation
        results.append({
            "id": tool["id"],
            "label": tool.get("label", ""),
            "found": True,
            "node": tool_root.name,
            "dock_node": dock_node.name,
            "dock": _to_gl(dock),
            "center": _to_gl((lo + hi) / 2),
        })
    found = sum(1 for item in results if item.get("found"))
    log(f"可更换工具: 登记 {found}/{len(results)} 个")
    alignment = _check_dock_frames(dock_frames, rig_map)
    return {"tools": results, "dock_alignment": alignment}


def _check_dock_frames(
    dock_frames: list,
    rig_map: dict,
    max_angle_deg: float = 0.5,
    max_offline_mm: float = 1.0,
) -> dict:
    """
    功能: 门禁 —— 各工具侧快换必须同朝向且共线, 否则拒绝共用同一份 mount_transform.

    manifest 里 1/3 号刀的 mount_transform 是复用 2 号刀在 robot.tool_pickup 锁紧
    瞬间标定出来的那一组值, 前提是"三个工具侧快换在 CAD 工具站中共用一个坐标朝向"
    (见 calibration/cr5_ptlc_v1.yaml 的 dock_frame_rotation). 那是个可证伪的几何假设,
    所以在这里把它变成会失败的断言, 而不是留在注释里.

    参数:
        dock_frames: [(工具 id, 快换世界矩阵)]
        rig_map: rig_map.yaml 内容, 用于回读各刀声明的 mount_transform
        max_angle_deg: 朝向偏差上限
        max_offline_mm: 偏离拟合直线的距离上限
    返回值: dict, 实测残差
    """
    if len(dock_frames) < 2:
        return {"tools": len(dock_frames), "checked": False}

    quaternions = [(tool_id, matrix.to_quaternion()) for tool_id, matrix in dock_frames]
    base_id, base_quaternion = quaternions[0]
    angles = {}
    for tool_id, quaternion in quaternions[1:]:
        dot = min(1.0, abs(quaternion.dot(base_quaternion)))
        angles[tool_id] = round(math.degrees(2 * math.acos(dot)), 4)
    worst_angle = max(angles.values(), default=0.0)

    points = [matrix.translation.copy() for _, matrix in dock_frames]
    direction = (points[-1] - points[0])
    offsets = {}
    if direction.length > 1e-9:
        direction.normalize()
        for (tool_id, _), point in zip(dock_frames[1:-1], points[1:-1]):
            delta = point - points[0]
            offsets[tool_id] = round((delta - direction * delta.dot(direction)).length * 1000, 4)
    worst_offset = max(offsets.values(), default=0.0)

    shared = [
        tool.get("id")
        for tool in rig_map.get("tools") or []
        if (tool.get("mount_transform") or {}).get("shared_coupling")
    ]
    if shared and (worst_angle > max_angle_deg or worst_offset > max_offline_mm):
        raise RuntimeError(
            f"工具侧快换未同朝向/未共线(相对 {base_id} 最大 {worst_angle}°, "
            f"最大偏线 {worst_offset} mm), {shared} 不能再复用同一份 mount_transform"
        )
    log(
        f"工具侧快换对齐: 相对 {base_id} 朝向最大偏差 {worst_angle}°, "
        f"最大偏线 {worst_offset} mm (共享耦合位姿: {shared or '无'})"
    )
    return {
        "reference": base_id,
        "orientation_deg": angles,
        "offline_mm": offsets,
        "max_orientation_deg": worst_angle,
        "max_offline_mm": worst_offset,
        "shared_coupling_tools": shared,
    }


# 快换同轴门禁: 校正后残差上限; 预偏差超过 PRECORR 视为链断裂而非侧向失配.
QUICK_CHANGE_MAX_LATERAL_MM = 0.5
QUICK_CHANGE_MAX_PRECORR_MM = 25.0
# 导出器的 Z-up -> Y-up 基变换((x,y,z)_bl -> (x,z,-y)_gl); 局部变换按共轭方式换基,
# 所以 app 侧(glTF 系)量出的 mount_transform 拿回 Blender 系要做逆共轭.
_GL_FROM_BL = Matrix((
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, -1.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
))
_BL_FROM_GL = _GL_FROM_BL.inverted()


def _subtree_world_verts(root) -> list:
    """功能: 收集 root 及其后代全部网格顶点的世界坐标. 参数: root. 返回值: list[Vector]"""
    stack = [root]
    verts: list = []
    while stack:
        node = stack.pop()
        stack.extend(node.children)
        if node.type == "MESH" and node.data is not None:
            matrix = node.matrix_world
            verts.extend(matrix @ vertex.co for vertex in node.data.vertices)
    return verts


def _support_offset_xy(black_points: list, gold_points: list, samples: int = 180):
    """
    功能: 支撑函数配准 —— 求快换两半**本体外轮廓**的横向平移差(gold − black).

    为什么不用质心: 两半挂的侧模块不一样(金盘多一个 2 路气模块), 质心被系统性拉偏;
    而且配合面附近两侧截面根本不可比(黑侧是插销+倒角, 金侧是孔口环) —— 2026-08-02
    的质心版实测只纠了真实偏差的一半(5.5mm 里纠了 2.96mm), 用户一眼看出仍错开.
    改用支撑函数: 对每个方向 θ 取轮廓最远点投影 h(θ); 两半本体是同规格(实测 42×48mm
    外廓在 82% 方向上吻合到 0.09mm), congruent 形状满足 h_gold(θ) − h_black(θ) = Δ·u(θ),
    最小二乘解出 Δ, 模块不一致的方向按残差剔除 —— 结论只由"共有的本体轮廓"决定.

    参数:
        black_points / gold_points: 各自本体段顶点(同一 glTF 约定 mount 局部系, 单位 m;
                                    耦合轴 = z, 侧向 = xy)
        samples: 方向采样数
    返回值: (Vector((dx, dy)), 内点比例, 内点残差中位数 m)
    """
    if len(black_points) < 50 or len(gold_points) < 50:
        raise RuntimeError(
            f"快换本体段点太少(黑 {len(black_points)} / 金 {len(gold_points)}), 无法配准轮廓"
        )
    directions = [
        (math.cos(2.0 * math.pi * index / samples), math.sin(2.0 * math.pi * index / samples))
        for index in range(samples)
    ]

    def support(points: list) -> list:
        return [
            max(point.x * ux + point.y * uy for point in points)
            for ux, uy in directions
        ]

    diff = [g - b for g, b in zip(support(gold_points), support(black_points))]
    keep = [True] * samples
    offset = Vector((0.0, 0.0))
    residuals = [0.0] * samples
    for _ in range(4):
        a11 = a12 = a22 = b1 = b2 = 0.0
        for (ux, uy), value, use in zip(directions, diff, keep):
            if not use:
                continue
            a11 += ux * ux
            a12 += ux * uy
            a22 += uy * uy
            b1 += ux * value
            b2 += uy * value
        det = a11 * a22 - a12 * a12
        if abs(det) < 1e-12:
            raise RuntimeError("快换本体轮廓配准退化: 保留方向不足以定出平移")
        offset = Vector(((b1 * a22 - b2 * a12) / det, (b2 * a11 - b1 * a12) / det))
        residuals = [
            abs(value - (ux * offset.x + uy * offset.y))
            for (ux, uy), value in zip(directions, diff)
        ]
        median = sorted(residuals)[samples // 2]
        spread = sorted(abs(value - median) for value in residuals)[samples // 2]
        limit = max(median + 3.0 * spread, 0.0003)
        trimmed = [value <= limit for value in residuals]
        if sum(trimmed) < samples // 3:
            break
        keep = trimmed
    inliers = sorted(value for value, use in zip(residuals, keep) if use)
    ratio = len(inliers) / float(samples)
    median_inlier = inliers[len(inliers) // 2] if inliers else float("inf")
    if ratio < 0.5:
        raise RuntimeError(
            f"快换两半本体外轮廓只有 {ratio:.0%} 方向吻合, 不像同规格配对件 — "
            "拒绝按轮廓配准(检查是否取到了正确的本体段/是否有旋向差)"
        )
    if median_inlier > 0.0005:
        raise RuntimeError(
            f"快换本体轮廓配准残差中位数 {median_inlier * 1000:.2f} mm (>0.5mm), "
            "两半轮廓不同规格或本体段取错"
        )
    return offset, ratio, median_inlier


def _contact_plane_z(roots: list, world_to_local: Matrix, direction: int):
    """
    功能: 找一组子树网格在目标局部系(glTF 约定, 耦合轴=Z)里朝向 direction 的主接触平面.

    快换的锁紧关系是"端面贴合": 黑盘朝工具侧(-z)的接触环面 vs 母盘朝臂侧(+z)的顶面.
    逐多边形取(局部中心 z, 面积), 只收法线与轴向夹角 <18° 的面(|n_z|>0.95), 0.2mm
    分箱 + ±0.5mm 窗口聚类, 面积加权取最大簇 —— 插销尖/销孔沉台等小面自然落选.
    坐标系距离(TOOL_MOUNT vs DOCK)只证明框架重合, 端面是否贴合必须直接量实体 ——
    2026-08-02 用户实锤过一次"框架 0.44mm 而端面差 4.3mm"的验收漏洞.

    参数:
        roots: 子树根对象列表(遍历后代取全部网格)
        world_to_local: 世界 -> 目标局部(Blender 系)的 4x4; 内部再换 glTF 约定
        direction: +1 取朝 +z(臂侧)面, -1 取朝 -z(工具侧)面
    返回值: (面积加权 z(glTF 局部, m), 簇总面积 m^2, 簇面数, 归属网格名)
    """
    rotation = world_to_local.to_3x3()
    bins: dict = {}
    owners: dict = {}
    stack = list(roots)
    while stack:
        node = stack.pop()
        stack.extend(node.children)
        if node.type != "MESH" or node.data is None:
            continue
        matrix = world_to_local @ node.matrix_world
        normal_matrix = rotation @ node.matrix_world.to_3x3()
        for polygon in node.data.polygons:
            local_normal = normal_matrix @ polygon.normal
            length = local_normal.length
            if length < 1e-9:
                continue
            # glTF z 分量 = -(Blender 局部 y), 见 to_gl_point
            if (-local_normal.y / length) * direction < 0.95:
                continue
            gl_z = -(matrix @ polygon.center).y
            key = round(gl_z * 5000.0) / 5000.0  # 0.2mm 分箱
            entry = bins.setdefault(key, [0.0, 0])
            entry[0] += polygon.area
            entry[1] += 1
            owners[(key, node.name)] = owners.get((key, node.name), 0.0) + polygon.area
    if not bins:
        raise RuntimeError("快换配合面检测: 没有找到朝向耦合轴向的平面")
    keys = sorted(bins)
    best = None
    best_key = None
    for center_key in keys:
        area = 0.0
        weighted = 0.0
        count = 0
        for key in keys:
            if abs(key - center_key) <= 0.0005:
                bin_area, bin_count = bins[key]
                area += bin_area
                weighted += key * bin_area
                count += bin_count
        if best is None or area > best[1]:
            best = (weighted / area, area, count)
            best_key = center_key
    # 归属网格: 在获胜簇里贡献接触面积最大的那个 mesh —— 它就是"真正贴合的那件".
    # 横向轮廓配准复用它, 于是轴向与横向锁定同一个实体特征; 也天然排除 raw 阶段
    # 未删减时混在同一子树里的零碎件(如 M6111, full 里被 prune 掉, 会毁掉轮廓一致性).
    owner_area: dict = {}
    for (key, name), area in owners.items():
        if abs(key - best_key) <= 0.0005:
            owner_area[name] = owner_area.get(name, 0.0) + area
    owner_name = max(owner_area, key=owner_area.get) if owner_area else None
    return (*best, owner_name)


def _quick_change_lateral_correction(mount, custom_members: list, rig_map: dict, calibration: dict) -> dict:
    """
    功能: 锁紧位三维校正(反向吸收) —— TOOL_MOUNT 落到黑盘轴线且端面贴合, 工具站随动.

    末端有两条互相独立、都刚挂在 J6 上的链: TOOL_MOUNT(physical_tool_mount, 由真实
    示教点拟合, 是取放/锁紧的事实源)与机器人侧快换组(custom_mount_alignment, 由 CAD
    法兰网格 ICP 配准). 两链互差是**三维**的(实测横向 ~5.5mm + 轴向端面 ~4.3mm), 表现为
    取放对接横向错位 + 端面留缝/插销悬空, 且此前无任何交叉校验. 本函数在 TOOL_MOUNT
    局部系模拟锁紧(工具侧母盘按 rig_map mount_transform 就位), 量:
      - 横向: 两半**本体外轮廓**支撑函数配准(_support_offset_xy, 本体段=离配合面
        2~12mm 的一圈); 曾用"配合面切片质心"只纠了一半(5.5 里纠 2.96), 因为两侧
        模块不对称且配合面处截面不可比 —— 用户一眼看出仍错开;
      - 轴向: 黑盘朝工具侧接触环面 vs 母盘顶面的实体平面差(_contact_plane_z);
    然后**机器人侧保持 CAD/ICP 原位不动**(臂/自制法兰/黑盘天生同轴):
      - TOOL_MOUNT 平移 -delta(三维), 落到黑盘轴线且锁紧位端面贴合、插销插到底;
      - 工具站(ST_* 祖先: 料架+三把刀)按示教位姿下的等价世界向量整体平移,
        示教点对接保持精确, 料架相对机架的几毫米无参照物不可见.
    曾先后废弃两版(2026-08-01/02): 平移机器人侧(法兰接缝留台阶, 用户要求三者同轴);
    只修横向(端面留 4.3mm 缝, 用户指出插销未入凹槽 —— 框架距离≠实体贴合).
    度量与关节姿态无关(full 零位 / raw 烘焙位应得到相同校正量). 注意: 报告与
    manifest 里的 tool_mount_transform 字段仍原样透传标定值(verify_robot_assets
    以 1e-8 容差断言其与标定一致), GLB 中 TOOL_MOUNT 节点的实际局部变换有意
    与该信息字段相差本函数的 -delta.

    参数:
        mount: TOOL_MOUNT 空物体(已就位)
        custom_members: 已按 ICP 矩阵放置并挂到 J6 ROTOR 的机器人侧成员
        rig_map: rig_map.yaml 内容(取 tools[*].mount_transform 锁紧位)
        calibration: cr5_ptlc_v1.yaml 内容(取 correspondences 选金色实例)
    返回值: dict, 校正量与残差(写入 03 报告 robot_joints.quick_change_correction)
    """
    tools = rig_map.get("tools") or []
    source_tool = next(
        (
            tool for tool in tools
            if (tool.get("mount_transform") or {}).get("position_m")
            and not (tool.get("mount_transform") or {}).get("shared_coupling")
        ),
        None,
    ) or next((tool for tool in tools if (tool.get("mount_transform") or {}).get("position_m")), None)
    if source_tool is None:
        return {"applied": False, "reason": "rig_map 无 mount_transform, 无法定义锁紧位"}

    lock = source_tool["mount_transform"]
    qx, qy, qz, qw = (float(value) for value in lock["quaternion_xyzw"])
    lock_gl = (
        Matrix.Translation(Vector([float(value) for value in lock["position_m"]]))
        @ Quaternion((qw, qx, qy, qz)).to_matrix().to_4x4()
    )
    lock_bl = _BL_FROM_GL @ lock_gl @ _GL_FROM_BL

    slot = int(source_tool.get("controller_tool") or 0)
    correspondences = (calibration.get("scene_registration") or {}).get("correspondences") or []
    entry = next(
        (item for item in correspondences if f"slot-{slot}." in str(item.get("point_id", ""))),
        None,
    )
    if entry is None:
        raise RuntimeError(f"标定缺少 slot-{slot} 对接点, 无法选定工具侧快换实例")
    slot_point = _gl_translation_to_blender(entry["scene_point_m"])

    hits = _find_all(source_tool.get("connector") or {"contains": "QT2091392"})
    if not hits:
        raise RuntimeError(f"工具侧快换 {source_tool.get('connector')} 未命中任何对象")
    bpy.context.view_layer.update()
    gold = min(hits, key=lambda obj: (obj.matrix_world.translation - slot_point).length)
    while gold.parent is not None and gold.parent in hits:
        gold = gold.parent
    slot_distance_mm = (gold.matrix_world.translation - slot_point).length * 1000.0
    if slot_distance_mm > 20.0:
        raise RuntimeError(
            f"slot-{slot} 工具侧快换 {gold.name} 离标定对接点 {slot_distance_mm:.1f} mm, "
            "场景注册可能已回退"
        )

    gold_world = _subtree_world_verts(gold)
    if not gold_world:
        raise RuntimeError(f"工具侧快换 {gold.name} 子树没有网格顶点")
    gold_inverse = gold.matrix_world.inverted()

    # mount 局部点统一换到 glTF 约定 (x,z,-y) 后再切片: 实测(见 03 报告 slice 字段与
    # 2026-08-01 仲裁)耦合轴是 glTF 局部 Z / Blender 局部 -Y —— 金色母盘沿它仅 15mm 厚.
    # 曾按"耦合轴 = Blender 局部 Z"实现过一版, 结果把轴向堆叠差(12mm)误当横向差搬走.
    def to_gl_point(point: Vector) -> Vector:
        return Vector((point.x, point.z, -point.y))

    gold_local = [to_gl_point(lock_bl @ (gold_inverse @ vertex)) for vertex in gold_world]

    def cloud_of(members) -> list:
        mount_inverse = mount.matrix_world.inverted()
        return [
            to_gl_point(mount_inverse @ vertex)
            for member in members
            for vertex in _subtree_world_verts(member)
        ]

    black_local = cloud_of(custom_members)
    if not black_local:
        raise RuntimeError("custom_mount_members 子树没有网格顶点")

    # ---- 轴向(端面)分量: 黑盘朝工具侧接触环面 vs 母盘(锁紧位)朝臂侧顶面 ----------
    # 必须量实体配合面: 框架距离(TOOL_MOUNT vs DOCK)只证坐标系重合, 2026-08-02 用户
    # 实锤"框架 0.44mm 而端面差 4.3mm 插销没插到底"的验收漏洞. 端面也定义了本体段位置.
    gold_lock_world_to_local = lock_bl @ gold.matrix_world.inverted()
    gold_face_z, gold_face_area, gold_face_count, gold_face_owner = _contact_plane_z(
        [gold], gold_lock_world_to_local, +1
    )
    # 黑侧只在"最靠工具侧的成员"(z 最低子树 = QT 快换本体)上找接触面: custom_members
    # 还含自制法兰, 其朝下大底面(16.6cm2)会盖过 QT 接触环面(7cm2)导致抓错平面.
    mount_world_to_local = mount.matrix_world.inverted()

    def member_min_z(member) -> float:
        return min(
            -(mount_world_to_local @ vertex).y for vertex in _subtree_world_verts(member)
        )

    contact_member = min(custom_members, key=member_min_z)
    black_face_z, black_face_area, black_face_count, black_face_owner = _contact_plane_z(
        [contact_member], mount_world_to_local, -1
    )
    face_gap_m = gold_face_z - black_face_z
    if abs(face_gap_m) > 0.012:
        raise RuntimeError(
            f"快换配合面检测疑似抓错平面: 端面差 {face_gap_m * 1000:.1f} mm (>12mm). "
            f"黑面 z={black_face_z * 1000:.1f}mm/{black_face_area * 1e4:.1f}cm2, "
            f"金面 z={gold_face_z * 1000:.1f}mm/{gold_face_area * 1e4:.1f}cm2"
        )

    # ---- 横向分量: 两半**本体外轮廓**支撑函数配准 -------------------------------
    # 本体段 = 离各自配合面 2~12mm 的一圈(黑侧朝臂向上、金侧朝工具向下), 刻意避开
    # 插销/孔口/倒角这些两侧不可比的特征; 配准只认两半共有的 42x48 本体轮廓.
    # 两侧都只取"贡献接触面积最大的那件本体网格"(_contact_plane_z 的归属), 于是横向与
    # 轴向锁定同一个实体特征; 也排除 raw 未删减时混在同一子树的零碎件(M6111 之类).
    def owner_object(name: str, fallback):
        return bpy.data.objects.get(name) if name else fallback

    body_near_m, body_far_m = 0.002, 0.012
    black_owner = owner_object(black_face_owner, contact_member)
    gold_owner = owner_object(gold_face_owner, gold)
    black_body = [
        point for point in cloud_of([black_owner])
        if black_face_z + body_near_m <= point.z <= black_face_z + body_far_m
    ]
    gold_owner_local = [
        to_gl_point(gold_lock_world_to_local @ vertex)
        for vertex in _subtree_world_verts(gold_owner)
    ]
    gold_body = [
        point for point in gold_owner_local
        if gold_face_z - body_far_m <= point.z <= gold_face_z - body_near_m
    ]
    lateral, inlier_ratio, registration_residual_m = _support_offset_xy(black_body, gold_body)

    delta_gl = Vector((lateral.x, lateral.y, face_gap_m))
    pre_mm = delta_gl.length * 1000.0
    if pre_mm > QUICK_CHANGE_MAX_PRECORR_MM:
        raise RuntimeError(
            f"机器人侧快换与工具侧母盘两条 J6 刚体链分歧 {pre_mm:.1f} mm, 远超失配量级 — "
            "检查 physical_tool_mount 与 custom_mount_alignment 是否出自同一标定版本"
        )

    # ---- 三维反向吸收(2026-08-02): 机器人侧保持 CAD/ICP 原位(臂/法兰/黑盘天生同轴),
    # 把 TOOL_MOUNT 平移 -delta(横向落到黑盘轴线 + 轴向使端面贴合、插销插到底);
    # 工具站(料架+三把刀)按示教位姿下的等价世界向量整体平移(横向 ~3mm + 竖直 ~4.3mm,
    # 相对机架无参照物不可见), 示教点对接保持精确. 曾先后废弃两版: 平移机器人侧
    # (法兰接缝留台阶)与只修横向(端面留 4.3mm 缝、插销悬空).
    # rig_map mount_transform 逐字节不变: mount 与工具在示教朝向下按同一世界向量
    # 平移, 锁紧相对变换严格保持(示教姿态残差 ≤0.44° -> 误差 ≤0.02mm).
    delta_bl = Vector((delta_gl.x, -delta_gl.z, delta_gl.y))
    v_bl = -delta_bl
    mount.matrix_world = (
        Matrix.Translation(mount.matrix_world.to_3x3() @ v_bl) @ mount.matrix_world
    )
    bpy.context.view_layer.update()

    # 门禁复测(同口径, 全部按平移后的实际几何重取): mount 带三维平移后黑盘在 mount
    # 局部系整体移了 +delta, 所以配合面与本体段都必须重新定位 —— 沿用旧带会切到
    # 另一截面, 量出假残差(12:14 曾因此误报 1.17mm).
    black_face_after, _area_after, _count_face_after, _owner_after = _contact_plane_z(
        [contact_member], mount.matrix_world.inverted(), -1
    )
    face_gap_after_mm = (gold_face_z - black_face_after) * 1000.0
    if abs(face_gap_after_mm) > 0.5:
        raise RuntimeError(
            f"快换端面校正后仍差 {face_gap_after_mm:.2f} mm (>0.5mm), 插销未贴合到底 — "
            "检查配合面检测簇与 mount 平移方向"
        )
    black_body_after = [
        point for point in cloud_of([black_owner])
        if black_face_after + body_near_m <= point.z <= black_face_after + body_far_m
    ]
    lateral_after, ratio_after, residual_after_m = _support_offset_xy(black_body_after, gold_body)
    residual_mm = lateral_after.length * 1000.0
    if residual_mm > QUICK_CHANGE_MAX_LATERAL_MM:
        raise RuntimeError(
            f"机器人侧快换与工具侧母盘在锁紧位不同轴: 校正后两半本体轮廓仍差 "
            f"{residual_mm:.2f} mm (> {QUICK_CHANGE_MAX_LATERAL_MM} mm). "
            "TOOL_MOUNT 链(physical_tool_mount)与 ICP 链(custom_mount_alignment)不自洽 — "
            "检查 calibration/cr5_ptlc_v1.yaml 两段是否同版本、rig_map mount_transform "
            "是否被改、QT2091392 实例是否被删减"
        )

    # 工具站世界平移: w = R_mount@示教 @ v, 而 R_mount@示教 = R_gold(dock) @ R_lock^-1.
    # gold 的世界朝向就是 dock 坐标系(build_tools 用同一矩阵建 DOCK; _check_dock_frames
    # 已证三工位朝向互差 0.04°); 全程 Blender 系, 不引入 dock_frame_rotation 常量.
    gold_rotation = gold.matrix_world.to_quaternion().to_matrix()
    lock_rotation_inv = lock_bl.to_quaternion().to_matrix().transposed()
    station_vec_bl = gold_rotation @ (lock_rotation_inv @ v_bl)

    station_root = None
    node = gold
    while node is not None:
        if node.name.startswith("ST_"):
            station_root = node
            break
        node = node.parent
    if station_root is not None:
        station_root.matrix_world = (
            Matrix.Translation(station_vec_bl) @ station_root.matrix_world
        )
        bpy.context.view_layer.update()
        station_state = "applied"
    else:
        # raw 阶段无 ST_ 站层级: 装配台不播取放, 料架保持 CAD 原位即可.
        station_state = "skipped-raw"

    log(
        f"快换同轴校正(tool_side_shift/3d): 预偏 {pre_mm:.2f} mm "
        f"(glTF x={delta_gl.x * 1000:.2f}, y={delta_gl.y * 1000:.2f}, 端面 z={delta_gl.z * 1000:.2f}) "
        f"-> 横向残差 {residual_mm:.3f} mm, 端面残差 {face_gap_after_mm:.3f} mm; "
        f"工具站平移 {station_state} "
        f"{[round(value * 1000, 3) for value in station_vec_bl]} mm(bl)"
    )
    return {
        "applied": True,
        "mode": "tool_side_shift",
        "reference_tool": source_tool.get("id"),
        "gold_instance_node": gold.name,
        "slot_point_distance_mm": round(slot_distance_mm, 3),
        "pre_offset_mm": {
            "x": round(delta_gl.x * 1000, 3),
            "y": round(delta_gl.y * 1000, 3),
            "z_face": round(delta_gl.z * 1000, 3),
            "norm": round(pre_mm, 3),
        },
        "post_residual_mm": round(residual_mm, 4),
        "face_gap_after_mm": round(face_gap_after_mm, 4),
        "contact_planes": {
            "black_face_z_mm": round(black_face_z * 1000, 3),
            "black_face_area_cm2": round(black_face_area * 1e4, 2),
            "black_face_polys": black_face_count,
            "black_face_owner": black_face_owner,
            "gold_face_z_mm": round(gold_face_z * 1000, 3),
            "gold_face_area_cm2": round(gold_face_area * 1e4, 2),
            "gold_face_polys": gold_face_count,
            "gold_face_owner": gold_face_owner,
        },
        "mount_local_shift_mm": {
            "x": round(-delta_gl.x * 1000, 3),
            "y": round(-delta_gl.y * 1000, 3),
            "z_face": round(-delta_gl.z * 1000, 3),
        },
        "station_shift": station_state,
        "station_node": station_root.name if station_root is not None else None,
        "station_shift_world_m": [
            round(station_vec_bl.x, 6),
            round(station_vec_bl.z, 6),
            round(-station_vec_bl.y, 6),
        ],
        "outline_registration": {
            "method": "support-function-trimmed-lstsq",
            "body_band_mm": [body_near_m * 1000, body_far_m * 1000],
            "black_body_points": len(black_body),
            "gold_body_points": len(gold_body),
            "inlier_ratio": round(inlier_ratio, 3),
            "residual_median_mm": round(registration_residual_m * 1000, 4),
            "inlier_ratio_after": round(ratio_after, 3),
            "residual_median_after_mm": round(residual_after_m * 1000, 4),
        },
        "gate_mm": QUICK_CHANGE_MAX_LATERAL_MM,
    }


# ---------------------------------------------------------------------------
# 合并与导出
# ---------------------------------------------------------------------------


def join_by_material(prefix: str = "MERGED") -> dict:
    """
    功能: 把使用同一材质的网格合并为一个对象, 大幅降低绘制调用数.

    注意: 合并会丢失原有的对象层级与名称, 因此只在 minimal 阶段(M0 只求"看得见")
    或 full 阶段的 STATIC 静态组内部使用; 需要独立驱动的运动件绝不参与合并.

    参数:
        prefix: 合并后对象的名称前缀
    返回值: dict, 合并统计
    """
    groups: dict[str, list] = {}
    for obj in mesh_objects():
        key = obj.data.materials[0].name if obj.data.materials else "NONE"
        groups.setdefault(key, []).append(obj)

    merged = 0
    adopted = 0
    for material_name, objects in groups.items():
        if len(objects) < 2:
            continue
        adopted += adopt_orphans_before_join(objects)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.join()
        bpy.context.view_layer.objects.active.name = f"{prefix}_{material_name}"
        merged += 1

    log(f"合并: {merged} 组; 合并后网格数 {len(mesh_objects())}; 过继子级 {adopted}")
    return {"groups_merged": merged, "meshes_after": len(mesh_objects()), "orphans_adopted": adopted}


def top_level_objects() -> list:
    """
    功能: 取所有顶层对象(无父级的对象).
    参数: 无
    返回值: list[bpy.types.Object]
    """
    return [obj for obj in bpy.data.objects if obj.parent is None]


def assembly_level_objects() -> list:
    """
    功能: 取"装配级"对象 —— 即需要按工位归组的那一层.

    不论走 STEP 还是原生 glTF, 导出的 GLB 通常只有一个总装根节点(如 `TLC设备总装`),
    真正的顶层装配是它的子节点. 若直接按"无父级"取, 只会拿到那一个根, 归组就全落空了.
    这里在只有单一根节点时自动下探一层.

    判定"单一根"时要忽略**没有子节点的非网格节点** —— 原生导出会附带相机之类的空节点,
    正常情况下它们已被 prune 删掉, 但万一漏网, 不该因为多了一个空节点就让整套归组失效.

    参数: 无
    返回值: list[bpy.types.Object]
    """
    roots = [obj for obj in top_level_objects() if not obj.name.startswith("ST_")]
    meaningful = [
        obj for obj in roots
        if obj.children or obj.type == "MESH"
    ]
    if len(meaningful) == 1 and meaningful[0].children:
        ignored = len(roots) - 1
        log(
            f"检测到单一总装根节点 '{meaningful[0].name}', "
            f"下探到其 {len(meaningful[0].children)} 个子装配"
            + (f"(忽略 {ignored} 个空节点)" if ignored else "")
        )
        return list(meaningful[0].children)
    return roots


def object_world_bounds(obj: Any) -> tuple[Vector, Vector]:
    """
    功能: 求一个对象及其全部后代的精确世界坐标包围盒(逐顶点).

    为什么不用 obj.bound_box: 那是对象的局部 AABB, 把它的八个角点变换到世界坐标再
    重新拟合, 一旦对象带旋转就会显著膨胀 —— 实测能把整机机架从 2.6×1.5×1.0 m
    报成 3.9×3.7×2.1 m, 进而让相机机位与工位包围盒全部失真. CAD 导入的零件普遍
    带任意旋转, 所以这里必须逐顶点算. 用 numpy 批量变换, 三百多万顶点也只需数秒.

    参数:
        obj: 目标对象
    返回值: tuple[Vector, Vector], (最小点, 最大点); 无几何时返回 (inf, -inf)
    """
    import numpy as np

    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)

    def visit(node: Any) -> None:
        """功能: 递归累计包围盒. 参数: node 对象. 返回值: None"""
        nonlocal lo, hi
        if node.type == "MESH" and len(node.data.vertices):
            count = len(node.data.vertices)
            flat = np.empty(count * 3, dtype=np.float64)
            node.data.vertices.foreach_get("co", flat)
            points = flat.reshape(count, 3)

            matrix = np.array(node.matrix_world, dtype=np.float64)
            # 齐次变换: 补一列 1 再乘, 取前三列
            homogeneous = np.hstack([points, np.ones((count, 1))])
            world = homogeneous @ matrix.T

            lo = np.minimum(lo, world[:, :3].min(axis=0))
            hi = np.maximum(hi, world[:, :3].max(axis=0))
        for child in node.children:
            visit(child)

    visit(obj)
    return Vector(lo.tolist()), Vector(hi.tolist())


def _mesh_world_bounds(obj: Any) -> tuple[Vector, Vector]:
    """
    功能: 求单个网格对象**自身几何**的世界坐标包围盒(逐顶点, 不含后代).

    与 object_world_bounds 的差别只在不递归: 静态合并的成员各自就是一个 MESH 对象,
    成员之间可能存在父子关系, 若把后代算进来, 支架类零件的包围盒会罩住整棵子树,
    材质台"命中点→成员候选"会因此全是误报.

    参数:
        obj: 目标对象
    返回值: tuple[Vector, Vector], (最小点, 最大点); 非网格或无顶点时返回 (inf, -inf)
    """
    import numpy as np

    if obj.type != "MESH" or not len(obj.data.vertices):
        return Vector((math.inf,) * 3), Vector((-math.inf,) * 3)
    count = len(obj.data.vertices)
    flat = np.empty(count * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", flat)
    points = flat.reshape(count, 3)
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    homogeneous = np.hstack([points, np.ones((count, 1))])
    world = homogeneous @ matrix.T
    return Vector(world[:, :3].min(axis=0).tolist()), Vector(world[:, :3].max(axis=0).tolist())


def _object_triangles(obj: Any) -> int:
    """功能: 单个网格对象自身的三角形数(n 边形按 n-2 计, 与 scene_stats 同口径). 参数: obj. 返回值: int"""
    if obj.type != "MESH":
        return 0
    return sum(max(len(polygon.vertices) - 2, 0) for polygon in obj.data.polygons)


def new_empty(name: str, location: Vector | None = None) -> Any:
    """
    功能: 创建一个空对象(作为层级分组节点).
    参数:
        name: 对象名
        location: 位置; None 表示原点
    返回值: bpy.types.Object
    """
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_size = 0.05
    if location is not None:
        empty.location = location
    bpy.context.scene.collection.objects.link(empty)
    return empty


def reparent(child: Any, parent: Any) -> None:
    """
    功能: 把对象挂到新父级下, 并保持其世界变换不变.

    注意首行的 view_layer.update(): Blender 的 matrix_world 是惰性求值的, 刚通过
    location/scale 赋值创建出来的对象, 其 matrix_world 仍是上一次求值的结果(通常是
    单位矩阵). 若不先刷新就读取并回写, 等于把刚设好的位置与缩放抹掉 —— 现象是所有
    新建的状态灯和液面盒都缩回原点、尺寸变成 1, 还会把所属工位的包围盒撑大.

    参数:
        child: 子对象
        parent: 父对象
    返回值: None
    """
    bpy.context.view_layer.update()
    world = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    child.matrix_world = world


def adopt_orphans_before_join(objects: list) -> int:
    """
    功能: join 前把"将被删对象"的子级过继给存活体, 防止孤儿塌回世界原点.

    bpy.ops.object.join() 只保留 objects[0], 其余全部从 bpy.data 删除. 被删对象的子级
    会失去父级、matrix_world 退回 matrix_basis —— 于是整件东西被传送到世界原点, 并且
    因为它仍带着材质, 还会被后续同材质组一起并进某个 STATIC 块, 把那个块的包围盒撑到
    半个场景那么大. 2026-08 实测: 注射泵视窗-3 / 注射泵针筒-3 就是这么没的
    (merge-members.json 里两者 bbox center = [0,0,*], 而它们的兄弟在 [-0.451,-0.581,*]).

    过继而不是删除: 子级本身可能是别的材质组的合并成员, 删了会静默少几何; reparent
    保持世界变换, 所以过继对最终画面零影响, 纯属兜底.

    参数:
        objects: 本次要合并的对象(objects[0] 存活, objects[1:] 会被删)
    返回值: int, 实际过继的子级数
    """
    if len(objects) < 2:
        return 0
    survivor = objects[0]
    doomed = set(objects[1:])
    adopted = 0
    for obj in objects[1:]:
        for child in list(obj.children):
            # 子级自己也在本次合并名单里的话, 它马上会被并进 survivor, 不必过继
            if child in doomed or child is survivor:
                continue
            reparent(child, survivor)
            adopted += 1
    return adopted


def regroup_by_rig_map(rig_map: dict) -> dict:
    """
    功能: 按装配归属表把顶层装配重组进 ST_<工位> 语义层级.

    重组之后场景根下只剩若干 ST_* 空对象, 这是 device-manifest 里 glbNode 路径的基础,
    也是前端做工位拾取、状态灯定位、相机机位的依据.

    参数:
        rig_map: rig_map.yaml 的内容
    返回值: dict, 每个工位分到的顶层装配数与未归属清单
    """
    stations = rig_map.get("stations", [])
    compiled = [
        (spec["id"], compile_patterns(spec.get("patterns", [])), spec)
        for spec in stations
    ]

    roots = {spec["id"]: new_empty(f"ST_{spec['id']}") for spec in stations}
    misc_root = new_empty("ST_MISC")

    counts: dict[str, int] = {spec["id"]: 0 for spec in stations}
    unassigned: list[str] = []

    for obj in list(assembly_level_objects()):
        if obj.name.startswith("ST_"):
            continue
        target = None
        for station_id, patterns, _spec in compiled:
            if matches_any(obj.name, patterns):
                target = station_id
                break
        if target is None:
            reparent(obj, misc_root)
            unassigned.append(obj.name)
        else:
            reparent(obj, roots[target])
            counts[target] += 1

    log(
        "工位归组: "
        + ", ".join(f"{k}={v}" for k, v in counts.items() if v)
        + f"; 未归属 {len(unassigned)} 个"
    )
    if unassigned:
        log(f"  未归属样例: {unassigned[:10]}")

    return {"counts": counts, "unassigned": unassigned, "roots": list(roots)}


def mesh_descendants(root: Any) -> list:
    """
    功能: 收集一个对象下(含自身)所有带几何的网格后代.
    参数:
        root: 根对象
    返回值: list[bpy.types.Object]
    """
    out = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "MESH" and len(node.data.vertices) > 0:
            out.append(node)
        stack.extend(node.children)
    return out


def _occupancy_probe(parts: list):
    """
    功能: 造一个"世界坐标点是否落在任一零件实体内"的判定函数.

    判据是 closest_point_on_mesh 的法线朝向: 最近点指向查询点的向量若与该点的外法线
    反向, 查询点就在网格内侧. 先用逐顶点世界 AABB 粗筛, 绝大多数体素只需比几次浮点数,
    真正进 BVH 的很少.

    参数:
        parts: 参与占位判定的网格对象
    返回值: callable(Vector) -> bool
    """
    boxes = []
    for part in parts:
        plo, phi = object_world_bounds(part)
        if plo.x == math.inf:
            continue
        boxes.append((part, part.matrix_world.inverted(), plo, phi))

    def occupied(point: Vector) -> bool:
        for part, inverse, plo, phi in boxes:
            if not (plo.x <= point.x <= phi.x
                    and plo.y <= point.y <= phi.y
                    and plo.z <= point.z <= phi.z):
                continue
            local = inverse @ point
            hit, closest, normal, _ = part.closest_point_on_mesh(local)
            if hit and (local - closest).dot(normal) < 0:
                return True
        return False

    return occupied


def measure_trough_cavity(trough: Any, parts: list,
                          samples: tuple[int, int, int] = (36, 72, 90)) -> dict | None:
    """
    功能: 在溶液槽的包围盒内做体素扫描, 量出液体真正能占据的自由空间.

    为什么必须实测而不是按壁厚推算: 槽里还塞着过滤芯(把溶剂引到 TLC 板下沿)、气管接头
    与硅胶垫, 各自占掉一块; 按"外形减壁厚"估出来的容积会偏大三成以上, 由它反算的液面
    高度自然全错. 这里逐体素判"是否在任一零件实体内", 剩下的就是液体进得去的地方.

    产出的 free_area_mm2 是**实测自由截面积**, 与液面盒自身的底面积并不相等(盒是把自由
    空间拟合成的矩形, 边角/接头处有出入). 前端一律用 free_area_mm2 反算液面高度, 盒只
    负责画 —— 这样体积是准的, 观感差异可以忽略.

    参数:
        trough: 溶液槽对象
        parts: 同一个缸下的全部网格(含槽自身), 作为占位判定的对象集
        samples: (NX, NY, NZ) 体素分辨率; 槽沿长轴近似棱柱, X 方向可以粗一些
    返回值:
        dict, 含自由空间 AABB(世界坐标)与腔底/槽口/截面积/容积; 扫不出腔时返回 None
    """
    lo, hi = object_world_bounds(trough)
    if lo.x == math.inf:
        return None

    nx, ny, nz = samples
    dx = (hi.x - lo.x) / nx
    dy = (hi.y - lo.y) / ny
    dz = (hi.z - lo.z) / nz
    cell_xy_mm2 = (dx * 1000.0) * (dy * 1000.0)
    cell_mm3 = cell_xy_mm2 * (dz * 1000.0)

    occupied = _occupancy_probe(parts)
    free = bytearray(nx * ny * nz)
    layer_free = [0] * nz
    for ix in range(nx):
        x = lo.x + (ix + 0.5) * dx
        for iy in range(ny):
            y = lo.y + (iy + 0.5) * dy
            base = (ix * ny + iy) * nz
            for iz in range(nz):
                z = lo.z + (iz + 0.5) * dz
                if occupied(Vector((x, y, z))):
                    continue
                free[base + iz] = 1
                layer_free[iz] += 1

    peak = max(layer_free)
    if peak == 0:
        return None

    # 腔底 = 自底向上第一层"自由面积过半峰值"的层. 低于它的零星缝隙(槽底圆角、
    # 接头周围的空隙)不是液体待的地方, 计进去会把腔底压低、液面整体偏矮.
    floor_iz = next(iz for iz, count in enumerate(layer_free) if count >= peak * 0.5)
    span = nz - floor_iz

    # 腔柱 = 从腔底一路通到槽口基本无阻挡的列. 过滤芯/气管接头占据的列会被这步筛掉,
    # 于是拟合出来的盒自然让开它们, 不会把液体画进实体里.
    cavity = [(ix, iy)
              for ix in range(nx) for iy in range(ny)
              if sum(free[(ix * ny + iy) * nz + floor_iz:(ix * ny + iy) * nz + nz]) >= span * 0.8]
    if not cavity:
        return None

    xs = [c[0] for c in cavity]
    ys = [c[1] for c in cavity]
    box_lo = Vector((lo.x + min(xs) * dx, lo.y + min(ys) * dy, lo.z + floor_iz * dz))
    box_hi = Vector((lo.x + (max(xs) + 1) * dx, lo.y + (max(ys) + 1) * dy, hi.z))

    # 截面积取腔身的中位数: 顶上两层会蹭到槽口外的倒角、底下若干层还在圆角里, 都不代表腔身
    body = sorted(layer_free[floor_iz:max(floor_iz + 1, nz - 2)])
    area_mm2 = body[len(body) // 2] * cell_xy_mm2
    capacity_ml = sum(layer_free[floor_iz:]) * cell_mm3 / 1000.0

    return {
        "box_lo": box_lo,
        "box_hi": box_hi,
        "floor_z_mm": round((lo.z + floor_iz * dz) * 1000.0, 3),
        "rim_z_mm": round(hi.z * 1000.0, 3),
        "usable_depth_mm": round((hi.z - lo.z - floor_iz * dz) * 1000.0, 3),
        "free_area_mm2": round(area_mm2, 1),
        "capacity_ml": round(capacity_ml, 2),
        "ml_per_mm": round(area_mm2 / 1000.0, 3),
        "voxel_mm": [round(dx * 1000, 3), round(dy * 1000, 3), round(dz * 1000, 3)],
    }


def build_tanks(rig_map: dict) -> dict:
    """
    功能: 识别 8 个展缸实例, 重命名为 TANK_1..TANK_8, 并在每个缸的溶液槽内生成液面盒.

    液体积在**溶液槽**(PTLC-02-014)里, 不在缸底摊开 —— TLC 板的下沿正泡在这个槽里.
    2026-08-03 之前液面盒是按整缸包围盒(388×250)建的、四周还内缩 12%, 于是液体成了
    一块四周悬空 15~23mm 的板, 观感崩坏被停用; 现在改建到实测出来的槽内腔里.

    液面盒建成"满到槽口"的尺寸, 原点放在**底面**, 前端按液位缩放 scale.y 就是"从底往
    上涨"而不是上下同时变化.

    坐标轴: 本函数运行在 Blender 里, **Z 轴向上**. glTF 导出时会把 Blender 的 Z
    转成 glTF 的 Y(scale 分量同样按 (sx,sy,sz) -> (sx,sz,sy) 换), 所以这里沿 Z 建高,
    前端那边 animate 的正是 scale.y —— 两边是对上的.
    早期版本整段按 Y 向上写, 结果高度取到了缸的平面尺寸上, 液面看着永远是满的.
    也因此盒必须**保持世界轴对齐**(不继承槽的旋转), 否则局部 Y 不再是世界上方向.

    参数:
        rig_map: rig_map.yaml 的内容
    返回值: dict, 识别与生成结果
    """
    spec = rig_map.get("tanks") or {}
    patterns = compile_patterns([spec.get("pattern", "")])
    if not patterns:
        return {"found": 0}

    found = []
    for obj in bpy.data.objects:
        if obj.name.startswith(("TANK_", "LIQUID")):
            continue
        if matches_any(obj.name, patterns):
            lo, hi = object_world_bounds(obj)
            if lo.x == math.inf:
                continue
            found.append((obj, (lo + hi) / 2, lo, hi))

    # 排序: **先分架, 架内按 order_by 指定的方向** —— 1~4 是一个架, 5~8 是另一个架,
    # 与上位机 Tank_State 的分组下标一致(见 rig_map.tanks 注释). 早前按"层优先"排,
    # 两架被编成 1/3/5/7 与 2/4/6/8 交错, 状态码显示到了错的缸上.
    # 哪个架排前由 first_rack 定(Blender 世界系的 Y 符号); 高度用 round 分档, 否则同
    # 一层的缸因零点几毫米的差异会被拆散.
    #
    # ⚠ 架内方向(z_asc/z_desc)必须与机器人点表 P11..P18 一致 —— 2026-08-03 实测发现两者
    # 首尾颠倒过一次: 判据是"同一架 4 个缸的法兰-锚点竖直偏置必须相同", 当时按 360mm
    # (=2×层距)一级级跳。这类错画出来看着完全正常(板稳稳落座、缸盖照开), 只是不是机器
    # 实际用的那个缸, 没有任何自动指标会报警。现由 clip_compiler.verify_tank_pairing 守。
    first_rack = str(spec.get("first_rack", "y_negative"))
    if first_rack not in ("y_positive", "y_negative"):
        raise RuntimeError(f"tanks.first_rack 只能是 y_positive/y_negative: {first_rack}")
    front_sign = 1.0 if first_rack == "y_positive" else -1.0

    order_by = [str(item) for item in (spec.get("order_by") or ["rack", "z_asc"])]
    if order_by[:1] != ["rack"] or len(order_by) != 2 or order_by[1] not in ("z_asc", "z_desc"):
        raise RuntimeError(f'tanks.order_by 只能是 ["rack", "z_asc"|"z_desc"]: {order_by}')
    height_sign = 1.0 if order_by[1] == "z_asc" else -1.0

    def tank_order(item):
        center = item[1]
        # 同侧记 0(先), 对侧记 1(后); 架内按 order_by 的高度方向.
        rack_index = 0 if center.y * front_sign > 0 else 1
        return (rack_index, height_sign * round(center.z, 3))

    found.sort(key=tank_order)

    liquid_cfg = spec.get("liquid", {})
    # 液面盒也是可选几何, 可单独停用; TANK_n 重命名不受影响(动画绑定还要按名字找缸)
    make_liquid = bool(liquid_cfg.get("enabled", True))
    trough_patterns = compile_patterns([(liquid_cfg.get("trough") or {}).get("contains", "")])
    clearance = float(liquid_cfg.get("clearance", 0.0003))

    liquid_material = None
    if make_liquid:
        # ⚠ MAT_LIQUID 的真源是 material_semantics.yaml(经 build_materials 编译进
        # materials.yaml), assign_materials 早于本函数执行, 这里 build_material 只会
        # **命名即返回**那份已建好的材质 —— 下面这份规格仅在材质表里没有 MAT_LIQUID 时
        # 才生效, 改观感请去改 material_semantics.yaml, 改这里不会有任何效果.
        # (2026-08-03 在这上面栽过一次: 改了本处颜色, 产物里纹丝不动.)
        # 两条硬约束与语义表保持一致: 淡蓝(展开剂是无色有机溶剂), 且必须不透明
        # ——否则会和玻璃缸壁一起进透明队列而被画到缸外面去, 详见 TwinBindings._bindTanks.
        liquid_material = build_material(
            {
                "name": "MAT_LIQUID",
                "base_color": "#6fb9d8",
                "roughness": 0.08,
                "metalness": 0.0,
                "alpha": 1.0,
            }
        )

    def find_trough(tank_obj):
        """在缸下找溶液槽零件"""
        for node in mesh_descendants(tank_obj):
            if matches_any(node.name, trough_patterns):
                return node
        return None

    results = []
    cavity_stats = None

    for index, (obj, center, lo, hi) in enumerate(found, start=1):
        obj.name = f"TANK_{index}"
        size = hi - lo

        liquid_name = None
        cavity = None
        if make_liquid and trough_patterns:
            trough = find_trough(obj)
            if trough is None:
                log(f"警告: TANK_{index} 未找到溶液槽零件, 跳过液面盒")
            else:
                # 逐缸实测. 8 个槽虽是同一零件的实例, 但按包围盒比例复用首缸结果并不可靠
                # (拟合出的矩形腔跨在过滤芯两侧, 抽样命中率只有七八成, 分不清"本该如此"
                # 与"该架镜像了"); 单缸约 1.8 秒, 全量实测既准又不值得省.
                cavity = measure_trough_cavity(trough, mesh_descendants(obj))
                if cavity is not None and cavity_stats is None:
                    cavity_stats = {k: cavity[k] for k in
                                    ("floor_z_mm", "rim_z_mm", "usable_depth_mm",
                                     "free_area_mm2", "capacity_ml", "ml_per_mm", "voxel_mm")}
                    log(f"展缸液面: 实测溶液槽内腔 深{cavity['usable_depth_mm']}mm "
                        f"截面{cavity['free_area_mm2']}mm² 容积{cavity['capacity_ml']}mL "
                        f"({cavity['ml_per_mm']}mL/mm)")

            if cavity is not None:
                box_lo, box_hi = cavity["box_lo"], cavity["box_hi"]
                width = max(box_hi.x - box_lo.x - 2 * clearance, 1e-4)
                depth = max(box_hi.y - box_lo.y - 2 * clearance, 1e-4)
                height = max(box_hi.z - box_lo.z, 1e-4)   # 满液位 = 到槽口

                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
                cube = bpy.context.active_object

                # 立方体默认以中心为原点; 把顶点整体上移半个单位(Blender 的上是 +Z),
                # 让原点落在底面, 这样缩放时液面是"从底往上涨"而不是上下同时变化.
                # 注意必须直接改这个立方体自带的网格数据 —— 早期版本给它换了一个新建的空网格,
                # 结果几何被丢弃, 导出后液面节点没有任何顶点.
                for vertex in cube.data.vertices:
                    vertex.co.z += 0.5

                cube.name = f"LIQUID_{index}"
                cube.data.name = f"LIQUID_{index}_mesh"
                cube.scale = (width, depth, height)
                cube.location = Vector((
                    (box_lo.x + box_hi.x) / 2,
                    (box_lo.y + box_hi.y) / 2,
                    box_lo.z,
                ))
                cube.data.materials.clear()
                cube.data.materials.append(liquid_material)
                # 挂到缸根而非槽下: 盒必须保持世界轴对齐, 槽带任意旋转时挂它下面会歪
                reparent(cube, obj)
                liquid_name = cube.name

        results.append(
            {
                "index": index,
                "tank": obj.name,
                "liquid": liquid_name,
                "center": [round(v, 4) for v in center],
                "size": [round(v, 4) for v in size],
            }
        )

    if not make_liquid:
        liquid_note = "液面盒已停用(enabled: false)"
    else:
        built = sum(1 for r in results if r["liquid"])
        liquid_note = f"液面盒 {built}/{len(results)} 个"
    log(
        f"展缸: 识别 {len(found)} 个(期望 {spec.get('expect_count', '?')}), "
        f"1~4 在 {first_rack} 架, 5~8 在对侧, {liquid_note}"
    )
    return {
        "found": len(found),
        "first_rack": first_rack,
        "tanks": results,
        # 腔体实测量: gen_twin_manifest 搬进 manifest, 前端据此把 mL 反算成液面高度
        "liquid_cavity": cavity_stats,
        "liquid_exaggeration": float(liquid_cfg.get("exaggeration", 1.0)),
        "liquid_pipe_holdup_ml": float(liquid_cfg.get("pipe_holdup_ml", 0.0)),
    }


def build_tank_lids(rig_map: dict) -> dict:
    """
    功能: 为 8 个展缸的盖子机构建立可驱动的四刚体联动组(曲柄滑块式竖直提盖).

    机构拓扑(2026-08-02 逐顶点实测, 修正过两版误判): 每缸缸口上方 ~113~139mm 处,
    两根倒装 LRM9 导轨(固定)下挂 4 滑块+拉板横梁(009)+4 连杆连接板(008)+4 转轴
    (016)构成整体滑车, MA16x90 气缸(缸体经脚座固定)推拉滑车沿 Y 平移; 4 根摆臂
    连杆(007)上端铰在滑车转轴, 下端经旋转环(015)铰在盖沿, 铰点相对枢轴实测
    (水平 60.9mm 朝机器中心, 竖直 109.2mm 向下), 模长 125.03mm == 摆臂 R.
    盖(011)+压板(010)+石英玻璃(019)+窗密封圈(硅胶垫)+两根气缸拉板端梁(006), 端梁四角
    各一个 Y-J-GVB72-d12 直线轴承套在**竖直**导向轴上 —— **盖被锁为纯竖直升降**.

    运动学(曲柄滑块): 滑车沿远离机器中心方向平移 s ⇒ 铰点水平偏距 d0→d0+s,
    摆臂竖直分量 √(R²−(d0+s)²) 变短 ⇒ 盖被提起 h = √(R²−d0²) − √(R²−(d0+s)²),
    摆角 θ = asin((d0+s)/R) − asin(d0/R). 几何上限 s < R−d0(摆臂转平的奇异位),
    因此 carriage_travel_mm 与气缸标称 90mm 无关, 是 rig_map 声明的观感值.

    刚体划分(每缸 4 个 LINKAGE_TANK<n>_* 空对象, 前缀受静态合并保护):
        CARRIAGE             滑车(滑块+拉板+活塞杆+连接板+转轴+枢轴垫片), 沿 Y 平移,
                             挂 ST_ 工位根下
        ROCKER_F / ROCKER_R  前/后排摆杆(各 2 臂+2 枢轴轴承), **嵌套在 CARRIAGE 下**
                             绕世界 X 旋转 θ(父级只平移不旋转, 轴向不受影响)
        LID                  盖+压板+石英玻璃+窗密封圈+旋转环+盖排轴承/垫片+端梁+直线轴承,
                             **独立挂 ST_ 工位根**(不嵌套进摆杆), 沿世界 Z 平移 h ——
                             嵌套进摆杆会让盖跟着水平走, 与四个直线轴承的约束矛盾

    运行时各成员对同一个值线性混合(setLinkage 的双重映射会抵消 member.inputRange,
    表达不了分段相位), 端点严格正确, 中程 θ(s)/h(s) 的非线性用平滑混合近似.

    数学前提(全部进硬门禁): 空对象以单位世界旋转、纯平移创建, 且父级(ST_ 工位根
    /只平移的 CARRIAGE)世界旋转为单位阵 ⇒ glTF 导出的局部 base 旋转=单位阵 ⇒
    manifest 里的 axis 就是世界轴(共轭后仍是纯平移方向, 见 rig_map 头部 sign 绊线).

    信号语义: PLC DO=1(动点)=关盖=GLB 建模态 → outputRange 反向 [θ, 0](与夹爪
    [行程, 0] 同一约定, 见 rig_map 头注), inputRange 恒为升序 [0, 1].

    盖类网格按 master plan"全部重建一致"以捐赠缸实例化(原生 GLB 里 TANK_1 的盖与
    石英玻璃是无网格空节点; 同架各缸相对缸体是纯平移, 进旋转残差门禁).

    参数:
        rig_map: rig_map.yaml 的内容(消费 tank_lids 段)
    返回值: dict, 实测与建组结果; gen_twin_manifest 据其 tanks[].linkage 展开
            8 条 manifest linkages(id=PLC 的 dev_t{架}_cyl{层})并翻 rigged.
    """
    spec = rig_map.get("tank_lids") or {}
    if not spec.get("enabled", False):
        log("展缸盖: tank_lids 未启用, 跳过")
        return {"enabled": False}

    def fail(message: str) -> None:
        raise RuntimeError(f"展缸盖: {message}")

    racks_cfg = spec.get("racks") or {}
    rack_patterns = compile_patterns([racks_cfg.get("pattern", "^展缸架总装")])
    pairing = spec.get("pairing") or {}
    # PLC 的 dev_t1_* 必须落在拿 1~4 号缸的那个架上 —— 缸号与机构分组是同一件事,
    # 真源统一在 tanks.first_rack(早前 tank_lids 自带 t1_rack, 与缸号规则两处配置,
    # 一改一漏就会出现"缸号对了机构对不上"的错位).
    t1_rack = str((rig_map.get("tanks") or {}).get("first_rack", "y_negative"))
    declared_t1 = pairing.get("t1_rack")
    if declared_t1 is not None and str(declared_t1) != t1_rack:
        raise RuntimeError(
            f"展缸盖: tank_lids.pairing.t1_rack={declared_t1} 与 tanks.first_rack={t1_rack} "
            "冲突 —— 缸号与 PLC 分组必须同源, 删掉前者或改成一致"
        )
    # cyl_order 已退役: 气缸号就是缸号(manual_points 的 dev_t{架}_cyl{层} 与 PLC 的
    # Expand_Group/Expand_Number 都从缸号派生), 再给它一个独立的层序旋钮, 就等于把
    # "缸号↔层"这一件事写成两处 —— 2026-08-03 正因为它与 tanks.order_by 各自为政,
    # 出现过"缸号对了、盖对不上"的隐患。现在直接按 TANK_n 的编号配对, 旋钮留着只会误导。
    if pairing.get("cyl_order") is not None:
        raise RuntimeError(
            "展缸盖: tank_lids.pairing.cyl_order 已退役 —— 气缸号直接取自 TANK_n 的编号, "
            "架内层序的唯一真源是 tanks.order_by。请删掉这一行。"
        )
    lift_cfg = spec.get("lift_mm")
    travel_cfg = float(spec.get("carriage_travel_mm", 40.0))
    singular_margin_mm = float(spec.get("singular_margin_mm", 3.0))
    open_cfg = spec.get("open_deg", "auto")
    open_tol_deg = float(spec.get("open_tol_deg", 8.0))
    open_band = [float(v) for v in (spec.get("open_band_deg") or [15.0, 60.0])]
    label_tpl = str(spec.get("label", "展缸{tank}盖({plc})"))
    transition_s = float(spec.get("transition_s", 1.0))
    donor_cfg = spec.get("donor") or {}
    inst_cfg = spec.get("instancing") or {}
    inst_mode = str(inst_cfg.get("mode", "all"))
    inst_tol_mm = float(inst_cfg.get("residual_tol_mm", 3.0))
    geo = spec.get("geometry") or {}
    row_tol_mm = float(geo.get("row_spacing_tol_mm", 2.0))
    par_tol_mm = float(geo.get("parallel_tol_mm", 1.0))
    gap_window_mm = [float(v) for v in (geo.get("closed_gap_mm") or [-0.5, 3.0])]
    min_lift_mm = float(geo.get("min_lift_mm", 5.0))
    coax_tol_mm = float(geo.get("bushing_coax_tol_mm", 2.0))
    arm_tol_mm = float(geo.get("arm_length_tol_mm", 1.5))
    guide_match = spec.get("guide_rod") or {"contains": "气缸导向轴"}
    row_gap_mm = float(geo.get("row_gap_min_mm", 40.0))
    body_match = spec.get("body") or {"contains": "PTLC-02-012 平面展缸"}
    classes = spec.get("classes") or {}
    if not classes:
        fail("tank_lids.classes 为空")

    def descendants(root):
        found = []
        for child in root.children:
            found.append(child)
            found.extend(descendants(child))
        return found

    def mesh_center(obj) -> Vector:
        lo, hi = _mesh_world_bounds(obj)
        if lo.x == math.inf:
            fail(f"{obj.name} 没有网格顶点, 无法定位")
        return (lo + hi) / 2.0

    def rotation_residual(matrix) -> float:
        delta = matrix.to_3x3() - Matrix.Identity(3)
        return max(abs(value) for row in delta for value in row)

    # ---- 1. 定位两架并按世界 Y 符号分侧 -----------------------------------
    bpy.context.view_layer.update()
    racks = [
        obj for obj in bpy.data.objects
        if obj.type == "EMPTY" and matches_any(obj.name, rack_patterns)
    ]
    expect_racks = int(racks_cfg.get("expect_count", 2))
    if len(racks) != expect_racks:
        fail(f"展缸架命中 {len(racks)} 个, 预期 {expect_racks}: {[o.name for o in racks]}")
    rack_info: dict[str, dict] = {}
    for rack in racks:
        lo, hi = object_world_bounds(rack)
        center_y = (lo.y + hi.y) / 2.0
        side = "y_positive" if center_y > 0 else "y_negative"
        if side in rack_info:
            fail(f"两个展缸架落在同一侧({side}), 无法按 Y 符号分架")
        # front = 朝机器中心(y=0)的单位方向: 开盖的水平移动方向, 也是铰点相对吊点的偏置侧
        rack_info[side] = {"obj": rack, "front": -1.0 if center_y > 0 else 1.0}

    def station_root_of(obj):
        node = obj
        while node is not None:
            if node.name.startswith("ST_"):
                return node
            node = node.parent
        fail(f"{obj.name} 不在任何 ST_ 工位根之下")

    st_root = station_root_of(next(iter(rack_info.values()))["obj"])
    if rotation_residual(st_root.matrix_world) > 1e-6:
        fail(f"工位根 {st_root.name} 世界旋转不是单位阵, 空对象'轴=世界轴'前提被破坏")

    # ---- 2. 归架、定缸口基准面、按层配 PLC id ------------------------------
    tank_re = re.compile(r"^TANK_(\d+)$")
    tanks_by_side: dict[str, list[dict]] = {side: [] for side in rack_info}
    for obj in bpy.data.objects:
        match = tank_re.match(obj.name)
        if not match:
            continue
        side = None
        node = obj.parent
        while node is not None:
            for key, info in rack_info.items():
                if node is info["obj"]:
                    side = key
            node = node.parent
        if side is None:
            fail(f"{obj.name} 不在任何展缸架之下")
        bodies = [
            child for child in descendants(obj)
            if child.type == "MESH" and _plain_match(child.name, body_match)
        ]
        if len(bodies) != 1:
            fail(f"{obj.name} 内缸体({body_match})命中 {len(bodies)} 个, 必须唯一")
        lo, hi = _mesh_world_bounds(bodies[0])
        tanks_by_side[side].append({
            "obj": obj,
            "number": int(match.group(1)),
            "body": bodies[0],
            "face_z": hi.z,
        })
    for side, entries in tanks_by_side.items():
        if len(entries) != 4:
            fail(f"{side} 架内 TANK 数 {len(entries)} ≠ 4: {[e['obj'].name for e in entries]}")
        entries.sort(key=lambda item: -item["face_z"])  # 层 1 = 最上(只用于诊断/报告)
        for layer, entry in enumerate(entries, start=1):
            entry["layer"] = layer
        # 气缸号 = 缸号在本架内的序号(缸 1~4 → cyl1~4, 缸 5~8 → 同样 cyl1~4)。
        # 直接取自 TANK_n 的编号, 于是"架内层序"这件事全仓只有 tanks.order_by 一个真源。
        for entry in entries:
            cyl = (entry["number"] - 1) % 4 + 1
            entry["plc_id"] = f"dev_t{1 if side == t1_rack else 2}_cyl{cyl}"

    # ---- 3. 按"名字 + 相对缸口 z 窗口"认领零件(防串层的关键) ---------------
    claims: dict[tuple[int, str], list] = {}
    claimed_ids: dict[int, tuple[str, str]] = {}
    for side, info in rack_info.items():
        rack_meshes = [
            obj for obj in descendants(info["obj"])
            if obj.type == "MESH" and len(obj.data.vertices)
        ]
        for cls_name, cls in classes.items():
            window = [float(v) for v in (cls.get("z_window") or [])]
            if len(window) != 2:
                fail(f"classes.{cls_name}.z_window 必须是 [lo, hi]")
            for obj in rack_meshes:
                if not _plain_match(obj.name, cls.get("match") or {}):
                    continue
                dz_by_tank = [
                    (tank, mesh_center(obj).z - tank["face_z"])
                    for tank in tanks_by_side[side]
                ]
                owners = [t for t, dz in dz_by_tank if window[0] <= dz <= window[1]]
                if len(owners) > 1:
                    fail(
                        f"{obj.name} 同时落进 {[t['obj'].name for t in owners]} 的 "
                        f"{cls_name} 窗口, z 窗口需要收紧"
                    )
                if not owners:
                    continue  # 名字命中但 z 不在本类窗口: 属于另一类(如 626 高/低排)
                owner = owners[0]
                previous = claimed_ids.get(id(obj))
                if previous:
                    fail(f"{obj.name} 被 {previous[0]} 与 {cls_name} 双重认领")
                claimed_ids[id(obj)] = (cls_name, owner["obj"].name)
                claims.setdefault((owner["number"], cls_name), []).append(obj)

    instanced_classes = [name for name, cls in classes.items() if cls.get("instanced")]
    for side, entries in tanks_by_side.items():
        for entry in entries:
            for cls_name, cls in classes.items():
                expected = int(cls.get("per_tank", 1))
                got = claims.get((entry["number"], cls_name), [])
                if cls.get("instanced"):
                    if len(got) > expected:
                        fail(f"{entry['obj'].name} 的 {cls_name} 命中 {len(got)} > {expected}")
                elif len(got) != expected:
                    fail(
                        f"{entry['obj'].name} 的 {cls_name} 命中 {len(got)} 个, 预期 {expected}: "
                        f"{[o.name for o in got]}"
                    )

    # ---- 4. 捐赠实例化: 全部盖类网格按 donor 重建(修缺网格 + 保证一致) ------
    def complete_for_donor(entry) -> bool:
        """该缸的盖类网格是否齐全(够格当捐赠源)."""
        return all(
            len(claims.get((entry["number"], cls_name), []))
            == int(classes[cls_name].get("per_tank", 1))
            for cls_name in instanced_classes
        )

    instanced_report: dict[str, list[str]] = {}
    donor_report: dict[str, str] = {}
    for side, entries in tanks_by_side.items():
        # 缺省自动挑该架内网格齐全的第一台. 写死缸号很脆: 缸号规则一变(2026-08-02
        # 从层优先改成按架分组), 原来的 donor 就可能落到那台原生 GLB 就缺网格的缸上.
        declared = str(donor_cfg.get(side) or "auto")
        if declared == "auto":
            donor = next((e for e in entries if complete_for_donor(e)), None)
            if donor is None:
                fail(f"{side} 架里没有盖类网格齐全的缸可作捐赠源")
        else:
            donor = next((e for e in entries if e["obj"].name == declared), None)
            if donor is None:
                fail(f"{side} 架的 donor {declared!r} 不是该架的 TANK: "
                     f"{[e['obj'].name for e in entries]}")
            if not complete_for_donor(donor):
                fail(f"donor {declared} 的盖类网格不完整, 无法作为捐赠源(可改成 auto)")
        donor_name = donor["obj"].name
        donor_report[side] = donor_name
        donor_body_matrix = donor["body"].matrix_world.copy()
        for entry in entries:
            if entry is donor:
                continue
            transform = entry["body"].matrix_world @ donor_body_matrix.inverted()
            rot_max = rotation_residual(transform)
            if rot_max > 1e-3:
                fail(
                    f"{entry['obj'].name} 相对 donor 的落位变换含旋转(残差 {rot_max:.2e}), "
                    "同架缸应纯平移; 可降级 instancing.mode: missing_only"
                )
            for cls_name in instanced_classes:
                originals = claims.get((entry["number"], cls_name), [])
                if originals and inst_mode != "all":
                    continue
                source = claims[(donor["number"], cls_name)][0]
                clone = source.copy()  # 共享 mesh data, 材质随 mesh
                bpy.context.scene.collection.objects.link(clone)
                clone.matrix_world = transform @ source.matrix_world
                bpy.context.view_layer.update()
                if originals:
                    delta_mm = (mesh_center(clone) - mesh_center(originals[0])).length * 1000.0
                    if delta_mm > inst_tol_mm:
                        fail(
                            f"{entry['obj'].name} 的 {cls_name} 捐赠落位偏离原件 "
                            f"{delta_mm:.2f}mm 超限 {inst_tol_mm}mm; "
                            "可降级 instancing.mode: missing_only"
                        )
                    for original in originals:
                        bpy.data.objects.remove(original, do_unlink=True)
                reparent(clone, entry["obj"])
                claims[(entry["number"], cls_name)] = [clone]
                instanced_report.setdefault(entry["obj"].name, []).append(
                    f"{cls_name}<-{donor_name}"
                )
        # 原生 GLB 里缺网格的盖/石英玻璃只剩空节点占位, 删掉防止结构清单里出现幽灵
        for entry in entries:
            for cls_name in instanced_classes:
                match = classes[cls_name].get("match") or {}
                ghosts = [
                    obj for obj in descendants(entry["obj"])
                    if obj.type == "EMPTY" and _plain_match(obj.name, match)
                ]
                for ghost in ghosts:
                    bpy.data.objects.remove(ghost, do_unlink=True)
            for cls_name in instanced_classes:
                expected = int(classes[cls_name].get("per_tank", 1))
                if len(claims.get((entry["number"], cls_name), [])) != expected:
                    fail(f"{entry['obj'].name} 实例化后 {cls_name} 仍不足 {expected}")

    # ---- 5. 逐缸实测枢轴/铰点两排、解算开角、建组 ---------------------------
    def two_rows(objs, expected_each, what, tank_name):
        """按世界 y 聚成前后两排; 排距不足/数量不对硬失败. 返回 (y 小排, y 大排)."""
        pairs = sorted(((mesh_center(o), o) for o in objs), key=lambda p: p[0].y)
        gaps = [pairs[i + 1][0].y - pairs[i][0].y for i in range(len(pairs) - 1)]
        split = max(range(len(gaps)), key=lambda i: gaps[i])
        if gaps[split] * 1000.0 < row_gap_mm:
            fail(f"{tank_name} 的 {what} 按 y 分排失败(最大间隙 {gaps[split] * 1000:.1f}mm)")
        low, high = pairs[:split + 1], pairs[split + 1:]
        if len(low) != expected_each or len(high) != expected_each:
            fail(f"{tank_name} 的 {what} 分排 {len(low)}/{len(high)} ≠ {expected_each} 对称")

        def row(items):
            centers = [c for c, _ in items]
            return {
                "x": sum(c.x for c in centers) / len(centers),
                "y": sum(c.y for c in centers) / len(centers),
                "z": sum(c.z for c in centers) / len(centers),
                "objs": [o for _, o in items],
            }

        return row(low), row(high)

    def make_lid_empty(name, world_pos):
        if not name.startswith("LINKAGE_"):
            fail(f"节点名 {name} 必须以 LINKAGE_ 开头(静态合并保护前缀)")
        if bpy.data.objects.get(name) is not None:
            fail(f"节点名 {name} 已被占用")
        empty = new_empty(name)
        empty.matrix_world = Matrix.Translation(world_pos)  # 单位世界旋转(数学前提)
        if empty.name != name:
            fail(f"空对象名被 Blender 改写为 {empty.name}")
        return empty

    results = []
    for side, entries in tanks_by_side.items():
        front = rack_info[side]["front"]
        for entry in entries:
            number = entry["number"]
            name = entry["obj"].name

            def claimed(cls_name):
                return claims.get((number, cls_name), [])

            shaft_low, shaft_high = two_rows(claimed("pivot_shaft"), 2, "转轴", name)
            bear_low, bear_high = two_rows(claimed("pivot_bearing"), 2, "高位轴承", name)
            ring_low, ring_high = two_rows(claimed("lid_ring"), 2, "旋转环", name)
            arm_low, arm_high = two_rows(claimed("rocker_arm"), 2, "连杆", name)
            shaft_f, shaft_r = (shaft_high, shaft_low) if front > 0 else (shaft_low, shaft_high)
            bear_f, bear_r = (bear_high, bear_low) if front > 0 else (bear_low, bear_high)
            ring_f, ring_r = (ring_high, ring_low) if front > 0 else (ring_low, ring_high)
            arm_f, arm_r = (arm_high, arm_low) if front > 0 else (arm_low, arm_high)

            # 门禁: 两排共面 / 轴承贴合转轴 / 平行四边形 / 铰点在吊点前侧
            if abs(shaft_f["z"] - shaft_r["z"]) * 1000.0 > 1.5:
                fail(f"{name} 前后转轴排 z 差 {(shaft_f['z'] - shaft_r['z']) * 1000:.2f}mm 超限 1.5mm")
            for row_bear, row_shaft, tag in ((bear_f, shaft_f, "前"), (bear_r, shaft_r, "后")):
                dev = math.hypot(row_bear["y"] - row_shaft["y"], row_bear["z"] - row_shaft["z"]) * 1000.0
                if dev > 1.5:
                    fail(f"{name} {tag}排高位轴承偏离转轴 {dev:.2f}mm 超限 1.5mm")
            shaft_span_mm = abs(shaft_f["y"] - shaft_r["y"]) * 1000.0
            ring_span_mm = abs(ring_f["y"] - ring_r["y"]) * 1000.0
            if abs(shaft_span_mm - ring_span_mm) > row_tol_mm:
                fail(
                    f"{name} 吊点排距 {shaft_span_mm:.1f}mm ≠ 铰点排距 {ring_span_mm:.1f}mm"
                    f"(±{row_tol_mm}mm), 平行四边形前提被打破"
                )
            offset_f = (ring_f["y"] - shaft_f["y"], ring_f["z"] - shaft_f["z"])
            offset_r = (ring_r["y"] - shaft_r["y"], ring_r["z"] - shaft_r["z"])
            parallel_dev_mm = max(
                abs(offset_f[0] - offset_r[0]), abs(offset_f[1] - offset_r[1])
            ) * 1000.0
            if parallel_dev_mm > par_tol_mm:
                fail(f"{name} 前/后偏移向量差 {parallel_dev_mm:.2f}mm 超限 {par_tol_mm}mm")
            if offset_f[0] * front <= 0:
                fail(f"{name} 铰点不在吊点的机器中心侧(dy={offset_f[0] * 1000:.1f}mm), 方向前提被打破")
            bearing_size = None
            b_lo, b_hi = _mesh_world_bounds(bear_f["objs"][0])
            bearing_size = b_hi - b_lo
            if not (bearing_size.x <= bearing_size.y and bearing_size.x <= bearing_size.z):
                fail(
                    f"{name} 高位轴承包围盒最短轴不是 X({[round(v * 1000, 1) for v in bearing_size]}), "
                    "转动轴≠世界 X, 拒绝继续"
                )

            # 门禁: GLB 建模态必须是关盖(盖底贴缸口)
            lid_lo, _lid_hi = _mesh_world_bounds(claimed("lid_plate")[0])
            closed_gap_mm = (lid_lo.z - entry["face_z"]) * 1000.0
            if not (gap_window_mm[0] <= closed_gap_mm <= gap_window_mm[1]):
                fail(
                    f"{name} 盖底-缸口间隙 {closed_gap_mm:.2f}mm 不在 {gap_window_mm}mm 内, "
                    "GLB 建模态不是关盖, rig 语义前提被破坏"
                )

            # 门禁: 盖侧四个直线轴承必须与竖直导向轴同轴 —— 这是"盖只能竖直升降"
            # 这条运动学前提的物理依据, 轴承挪位/换型时必须在这里翻车而不是上线后
            bushings = claimed("lid_bushing")
            guides = [
                obj for obj in descendants(rack_info[side]["obj"])
                if obj.type == "MESH" and len(obj.data.vertices) and _plain_match(obj.name, guide_match)
            ]
            if len(guides) < 4:
                fail(f"{name} 所在架的竖直导向轴只找到 {len(guides)} 根(需 ≥4)")
            guide_axes = []
            for rod in guides:
                g_lo, g_hi = _mesh_world_bounds(rod)
                g_size = g_hi - g_lo
                if not (g_size.z > g_size.x and g_size.z > g_size.y):
                    fail(f"{name} 导向轴 {rod.name} 长轴不是世界 Z, 竖直约束前提被打破")
                guide_axes.append(((g_lo.x + g_hi.x) / 2.0, (g_lo.y + g_hi.y) / 2.0))
            for bushing in bushings:
                b_center = mesh_center(bushing)
                dev_mm = min(
                    math.hypot(b_center.x - gx, b_center.y - gy) * 1000.0
                    for gx, gy in guide_axes
                )
                if dev_mm > coax_tol_mm:
                    fail(
                        f"{name} 盖侧直线轴承 {bushing.name} 偏离最近导向轴 {dev_mm:.2f}mm "
                        f"超限 {coax_tol_mm}mm, 盖的竖直约束不成立"
                    )

            # 运动学(曲柄滑块): 摆臂上端(枢轴)随滑车沿 ±Y 平移 s, 下端(铰点)在盖上而
            # 盖被导向轴锁为纯竖直 ⇒ 水平偏距 d0→d0+s, 竖直分量 √(R²-(d0+s)²) 变短,
            # 盖被提起 h = √(R²-d0²) − √(R²-(d0+s)²). 摆角 θ = 两个 asin 之差.
            d0_mm = abs(offset_f[0]) * 1000.0
            v0_mm = abs(offset_f[1]) * 1000.0
            radius_mm = math.hypot(offset_f[0], offset_f[1]) * 1000.0
            arm_lo, arm_hi = _mesh_world_bounds(arm_f["objs"][0])
            arm_span_mm = max((arm_hi - arm_lo).y, (arm_hi - arm_lo).z) * 1000.0
            if abs(arm_span_mm - radius_mm) > radius_mm * 0.35:
                fail(
                    f"{name} 摆臂包围盒跨度 {arm_span_mm:.1f}mm 与铰点-枢轴距 "
                    f"{radius_mm:.1f}mm 相差过大, 枢轴/铰点配对可疑"
                )
            # 主参数是 lift_mm(盖抬升): 由它反解滑车行程 s = √(R²−(v0−h)²) − d0;
            # 缺省时退回直接声明的 carriage_travel_mm. 两者只是同一条约束的两端,
            # 绝不能分别给 —— 它们和 θ 被 |铰点−枢轴|=R 这一条锁死.
            max_reach_mm = radius_mm - singular_margin_mm
            max_lift_mm = v0_mm - math.sqrt(max(radius_mm ** 2 - max_reach_mm ** 2, 0.0))
            if lift_cfg is not None:
                lift_mm = float(lift_cfg)
                if lift_mm > max_lift_mm:
                    fail(
                        f"{name} 声明抬升 {lift_mm:.1f}mm 超过几何上限 {max_lift_mm:.1f}mm"
                        f"(摆臂半径 {radius_mm:.1f}mm 扣 {singular_margin_mm}mm 奇异余量)"
                    )
                travel_mm = math.sqrt(
                    max(radius_mm ** 2 - (v0_mm - lift_mm) ** 2, 0.0)
                ) - d0_mm
            else:
                travel_mm = travel_cfg
                if travel_mm <= 0:
                    fail(f"carriage_travel_mm={travel_mm} 必须为正")
                if d0_mm + travel_mm > max_reach_mm:
                    fail(
                        f"{name} 开盖末态水平偏距 {d0_mm + travel_mm:.1f}mm 距摆臂半径 "
                        f"{radius_mm:.1f}mm 不足 {singular_margin_mm}mm(逼近转平奇异位)"
                    )
                lift_mm = v0_mm - math.sqrt(
                    max(radius_mm ** 2 - (d0_mm + travel_mm) ** 2, 0.0)
                )
            if travel_mm <= 0:
                fail(f"{name} 反解滑车行程 {travel_mm:.1f}mm 非正, 抬升声明有误")
            if lift_mm < min_lift_mm:
                fail(f"{name} 抬升 {lift_mm:.1f}mm < 下限 {min_lift_mm}mm")
            theta_solved = math.degrees(
                math.asin((d0_mm + travel_mm) / radius_mm) - math.asin(d0_mm / radius_mm)
            )
            if isinstance(open_cfg, (int, float)):
                if abs(theta_solved - float(open_cfg)) > open_tol_deg:
                    fail(
                        f"{name} 解算开角 {theta_solved:.2f}° 与声明 {open_cfg}° 差超 "
                        f"{open_tol_deg}°, 几何或声明有一方错了"
                    )
                theta_used = float(open_cfg)
            else:
                if not (open_band[0] <= theta_solved <= open_band[1]):
                    fail(f"{name} 解算开角 {theta_solved:.2f}° 越出合理带 {open_band}°")
                theta_used = theta_solved
            # 摆臂旋向: 开盖末态铰点相对枢轴 = (front*(d0+s), -√(R²-(d0+s)²)), 与初态
            # (front*d0, -v0) 的夹角(绕世界 X)即带号摆角 —— 直接由 atan2 差得出,
            # 不做候选搜索: 竖直约束已经把末态钉死, 旋向没有第二种可能.
            open_dy = front * (d0_mm + travel_mm) / 1000.0
            open_dz = -math.sqrt(max(radius_mm ** 2 - (d0_mm + travel_mm) ** 2, 0.0)) / 1000.0
            angle_open = math.atan2(open_dz, open_dy)
            angle_closed = math.atan2(offset_f[1], offset_f[0])
            delta = math.degrees(angle_open - angle_closed)
            while delta > 180.0:
                delta -= 360.0
            while delta < -180.0:
                delta += 360.0
            if abs(abs(delta) - theta_used) > 0.5:
                fail(
                    f"{name} 旋向解算 {abs(delta):.2f}° 与开角 {theta_used:.2f}° 不符, "
                    "枢轴/铰点配对或行程有误"
                )
            sign_bl = 1.0 if delta > 0 else -1.0

            # 建组: 4 个空对象(单位世界旋转); 盖只竖直升降, 所以 LID 不嵌套进摆杆
            x_ref = (shaft_f["x"] + shaft_r["x"]) / 2.0
            base_name = f"LINKAGE_TANK{number}"
            rocker_front = make_lid_empty(
                f"{base_name}_ROCKER_F", Vector((x_ref, shaft_f["y"], shaft_f["z"])))
            rocker_rear = make_lid_empty(
                f"{base_name}_ROCKER_R", Vector((x_ref, shaft_r["y"], shaft_r["z"])))
            lid_empty = make_lid_empty(
                f"{base_name}_LID", Vector((x_ref, ring_f["y"], ring_f["z"])))
            carriage_members = (
                claimed("pull_plate") + claimed("slider") + claimed("piston_rod")
                + claimed("pivot_shaft") + claimed("pivot_bracket") + claimed("pivot_washer")
            )
            car_bounds = [_mesh_world_bounds(o) for o in carriage_members]
            car_center = Vector((
                (min(b[0].x for b in car_bounds) + max(b[1].x for b in car_bounds)) / 2.0,
                (min(b[0].y for b in car_bounds) + max(b[1].y for b in car_bounds)) / 2.0,
                (min(b[0].z for b in car_bounds) + max(b[1].z for b in car_bounds)) / 2.0,
            ))
            carriage_empty = make_lid_empty(f"{base_name}_CARRIAGE", car_center)

            # 层级: 滑车挂工位根, 摆杆嵌套在滑车下(枢轴随滑车平移); 盖被导向轴锁为
            # 纯竖直升降, 独立挂工位根 —— 嵌套进摆杆会让它跟着水平走, 与轴承约束矛盾
            reparent(carriage_empty, st_root)
            reparent(rocker_front, carriage_empty)
            reparent(rocker_rear, carriage_empty)
            reparent(lid_empty, st_root)
            for obj in arm_f["objs"] + bear_f["objs"]:
                reparent(obj, rocker_front)
            for obj in arm_r["objs"] + bear_r["objs"]:
                reparent(obj, rocker_rear)
            # 注意: classes 里的 role 字段是纯文档, 这里的枚举才是真正的归属真源 ——
            # 新增一类却漏加到这个元组里, 认领与 per_tank 门禁全会通过、报告也看不出
            # 异常, 但零件根本不会被 reparent(2026-08-03 密封圈就是这么漏掉的).
            lid_members = (
                claimed("lid_plate") + claimed("lid_press") + claimed("lid_quartz")
                + claimed("lid_ring") + claimed("ring_bearing") + claimed("lid_washer")
                + claimed("lid_beam") + claimed("lid_bushing") + claimed("lid_seal")
            )
            for obj in lid_members:
                reparent(obj, lid_empty)
            for obj in carriage_members:
                reparent(obj, carriage_empty)

            # 门禁: 导出局部旋转必须是单位阵("axis=世界轴"与反转数学的前提)
            bpy.context.view_layer.update()
            for empty in (rocker_front, rocker_rear, lid_empty, carriage_empty):
                local = empty.parent.matrix_world.inverted() @ empty.matrix_world
                if rotation_residual(local) > 1e-6:
                    fail(f"{empty.name} 的导出局部旋转不是单位阵")

            theta_out = round(theta_used, 2)
            sign_out = int(sign_bl)
            # 开盖=滑车向远离机器中心侧退(活塞杆缩回); front 指向中心, 故取 -front.
            # 盖沿世界 +Z 抬起 → glTF 的 +Y.
            carriage_axis = [int(round(v)) for v in _to_gl(Vector((0.0, -front, 0.0)))]
            lid_axis = [int(round(v)) for v in _to_gl(Vector((0.0, 0.0, 1.0)))]
            # 几何量(实测, 不随调参变)与运动参数(可调)分开: gen_twin_manifest 会按
            # rig_map 的 lift_mm 现值重算 outputRange, 所以调抬升只需秒级重跑 manifest.
            kinematics = {
                "model": "crank-slider-lift",
                "d0Mm": round(d0_mm, 3),
                "v0Mm": round(v0_mm, 3),
                "radiusMm": round(radius_mm, 3),
                "singularMarginMm": singular_margin_mm,
                "maxLiftMm": round(max_lift_mm, 2),
                "minLiftMm": min_lift_mm,
                "signBl": sign_out if False else int(sign_bl),
                # 与 members 同序的角色, 前端据此把主参数摊给各成员
                "roles": ["rocker", "rocker", "lid", "carriage"],
                "liftMm": round(lift_mm, 2),
                "travelMm": round(travel_mm, 2),
                "thetaDeg": round(theta_used, 2),
            }
            linkage = {
                "id": entry["plc_id"],
                "label": label_tpl.format(tank=number, plc=entry["plc_id"]),
                "inputRange": [0, 1],
                "transitionS": transition_s,
                "kinematics": kinematics,
                # 值语义: 1=DO 动点=关盖=GLB 基准态(输出 0), 0=原点=开盖(输出 θ/行程)
                # —— 反相只准表达为 outputRange 反向, 见 rig_map 头注
                "members": [
                    {"node": rocker_front.name, "motion": "rotate", "axis": [1, 0, 0],
                     "sign": sign_out, "inputRange": [0, 1], "outputRange": [theta_out, 0]},
                    {"node": rocker_rear.name, "motion": "rotate", "axis": [1, 0, 0],
                     "sign": sign_out, "inputRange": [0, 1], "outputRange": [theta_out, 0]},
                    {"node": lid_empty.name, "motion": "translate", "axis": lid_axis,
                     "sign": 1, "inputRange": [0, 1],
                     "outputRange": [round(lift_mm, 2), 0], "unitScale": 0.001},
                    {"node": carriage_empty.name, "motion": "translate", "axis": carriage_axis,
                     "sign": 1, "inputRange": [0, 1],
                     "outputRange": [round(travel_mm, 2), 0], "unitScale": 0.001},
                ],
            }
            results.append({
                "id": entry["plc_id"],
                "tank": name,
                "rack": side,
                "layer": entry["layer"],
                "closed_gap_mm": round(closed_gap_mm, 2),
                "theta_solved_deg": round(theta_solved, 2),
                "theta_used_deg": theta_out,
                "d0_mm": round(d0_mm, 1),
                "v0_mm": round(v0_mm, 1),
                "radius_mm": round(radius_mm, 1),
                "carriage_travel_mm": round(travel_mm, 1),
                "lift_mm": round(lift_mm, 1),
                "max_lift_mm": round(max_lift_mm, 1),
                "sign_bl": sign_out,
                "pivot_front_gl": _to_gl(Vector((x_ref, shaft_f["y"], shaft_f["z"]))),
                "pivot_rear_gl": _to_gl(Vector((x_ref, shaft_r["y"], shaft_r["z"]))),
                "hinge_front_gl": _to_gl(Vector((x_ref, ring_f["y"], ring_f["z"]))),
                "gates": {
                    "shaft_span_mm": round(shaft_span_mm, 2),
                    "ring_span_mm": round(ring_span_mm, 2),
                    "parallel_dev_mm": round(parallel_dev_mm, 3),
                },
                "members": {
                    "rocker_f": [o.name for o in arm_f["objs"] + bear_f["objs"]],
                    "rocker_r": [o.name for o in arm_r["objs"] + bear_r["objs"]],
                    "lid": [o.name for o in lid_members],
                    "carriage": [o.name for o in carriage_members],
                },
                "linkage": linkage,
            })

    results.sort(key=lambda item: item["tank"])
    if len(results) != 8:
        fail(f"建组 {len(results)} 缸 ≠ 8")
    log(
        f"展缸盖: 建组 8 缸, 滑车行程 {travel_mm:.0f}mm → 摆角 "
        f"{results[0]['theta_used_deg']:.1f}° / 盖抬升 {results[0]['lift_mm']:.1f}mm, "
        f"关盖间隙 {results[0]['closed_gap_mm']}mm, 捐赠重建 {len(instanced_report)} 缸"
    )
    return {
        "enabled": True,
        "modeled_state": "closed",
        "carriage_travel_mm": travel_mm,
        "donor": donor_report,
        "instanced": instanced_report,
        "tanks": results,
    }


def build_status_lights(rig_map: dict, station_roots: list[str]) -> dict:
    """
    功能: 为每个工位生成一个自发光状态灯条, 悬在该工位包围盒顶部.

    状态灯是前端唯一参与辉光(bloom)的物体: 用颜色表达健康度(绿/琥珀/红/灰),
    在深色场景里一眼可辨, 且不会因为设备本体发光而糊掉信息.

    参数:
        rig_map: rig_map.yaml 的内容
        station_roots: 工位根节点名列表
    返回值: dict, 生成结果
    """
    spec = rig_map.get("status_lights") or {}
    # 灯条是纯示意几何, 观感差(用户: 太丑); 真实三色灯零件走 MAT_STATUS_LIGHT 自发光,
    # 状态视觉已经够用. N2 需要逐工位状态显示时再打开, 或改用别的表达.
    if not spec.get("enabled", True):
        log("状态灯: 已按 rig_map 停用(enabled: false), 不生成灯条")
        return {"created": [], "skipped": True}
    bar_size = spec.get("bar_size", [0.10, 0.012, 0.012])
    # lift 是新名; 兼容旧的 y_offset —— 那个名字误导过一次(Blender 里向上是 Z)
    lift = float(spec.get("lift", spec.get("y_offset", 0.06)))

    material = build_material(
        {
            "name": "MAT_STATUS_LIGHT",
            "base_color": "#39d98a",
            "roughness": 0.3,
            "metalness": 0.0,
            "emission": "#39d98a",
            "emission_strength": 4.0,
        }
    )

    created = []
    for root_name in station_roots:
        root = bpy.data.objects.get(f"ST_{root_name}") or bpy.data.objects.get(root_name)
        if root is None or not root.children:
            continue
        lo, hi = object_world_bounds(root)
        if lo.x == math.inf:
            continue

        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
        bar = bpy.context.active_object
        bar.name = f"LIGHT_STATUS_{root_name}"
        bar.scale = Vector(bar_size)
        # Blender 是 **Z 轴向上**(glTF 才是 Y 向上). 早期版本这里写成 hi.y, 把灯条塞到了
        # 工位包围盒的"后侧面、半腰高"处 —— 表现为机器上散落着一堆不明发光方块.
        bar.location = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z + lift))
        bar.data.materials.clear()
        bar.data.materials.append(material)
        reparent(bar, root)
        created.append(bar.name)

    log(f"状态灯: 生成 {len(created)} 个")
    return {"created": created}


def split_tower(config: dict, materials_cfg: dict) -> dict:
    """
    功能: 把三色灯厂商单网格按高度拆成 顶盖(金属) / 灯罩(保留自发光) / 外壳(金属) 三个对象.

    背景: ZHD24 整灯(顶盖+灯罩+外壳+底座)在厂商模型里是一个网格, MAT_STATUS_LIGHT
    功能覆盖一命中就整根点亮, 而实机**只有中间那段灯罩筒身发光**, 顶盖与底座外壳都是
    金属件. 该网格由两百多个独立壳体组成, 两处切面都落在天然接缝上:
      * height_ratio=0.5 → 灯罩/外壳 接缝(实测 166.3/332.5 mm, 双顶点环);
      * cap_ratio ≈ 0.93 → 灯罩/顶盖 接缝(顶盖组壳体重心全部 ≥ 世界 Z 0.9306,
        灯罩筒身壳体重心只有 ~0.856/0.859, 中间是很宽的空档, ratio 落在 0.74~0.95
        之间结果完全相同; 取中值是为了避开 0.9306 那圈顶点的浮点边界).
    按 loose parts 的重心分类即可干净拆开, 不需要 bisect, 零新增三角形.

    时机: 必须在 assign_materials 之后(整灯已拿到 MAT_STATUS_LIGHT)、工位重组与合并
    之前. 灯罩保留原名与原材质(manifest.signalLight 契约认这个名字); 顶盖与外壳的名字
    保留原名前缀(FRAME 工位归组的 ^ 锚定正则才能继续命中)再各加后缀, 并按
    materials.yaml 里的配方名赋金属材质 —— 两者同配方时共享材质实例, 合并阶段归一组.

    参数:
        config: rig_map.yaml 的 tower_split 段(pattern/height_ratio/lower_suffix/
            lower_material/cap_ratio/cap_suffix/cap_material); 不给 cap_ratio 就退回
            "灯罩 + 外壳"两段的旧行为
        materials_cfg: materials.yaml 内容(用于按名解析顶盖/外壳材质配方)
    返回值: dict, 拆分统计
    """
    patterns = compile_patterns([config.get("pattern", "")])
    targets = [obj for obj in mesh_objects() if matches_any(obj.name, patterns)]
    if not targets:
        log("三色灯拆分: 未找到目标网格, 跳过")
        return {"skipped": "no_match"}
    if len(targets) > 1:
        log(f"三色灯拆分: 命中 {len(targets)} 个, 只处理第一个: {targets[0].name}")
    obj = targets[0]
    orig_name = obj.name

    bpy.context.view_layer.update()
    lo, hi = object_world_bounds(obj)
    height = hi.z - lo.z
    ratio = float(config.get("height_ratio", 0.5))
    plane_z = lo.z + ratio * height
    # 顶盖切面可选: 不配 cap_ratio 就退回"灯罩 + 外壳"两段
    cap_ratio = config.get("cap_ratio")
    cap_z = lo.z + float(cap_ratio) * height if cap_ratio is not None else None
    if cap_z is not None and cap_z <= plane_z:
        log(f"三色灯拆分: cap_ratio={cap_ratio} 不高于 height_ratio={ratio}, 顶盖切分已忽略")
        cap_z = None

    # 分离全部独立壳体(separate 保持父级与世界变换, 材质随几何走)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    parts = list(bpy.context.selected_objects)

    cap: list = []
    upper: list = []
    lower: list = []
    straddle = 0
    eps = 0.002  # 2mm: 只用于统计"跨缝壳体"以便观察, 归属一律按重心
    planes = [z for z in (plane_z, cap_z) if z is not None]
    for part in parts:
        plo, phi = object_world_bounds(part)
        center_z = (plo.z + phi.z) / 2
        if cap_z is not None and center_z >= cap_z:
            cap.append(part)
        elif center_z >= plane_z:
            upper.append(part)
        else:
            lower.append(part)
        if any(plo.z < z - eps and phi.z > z + eps for z in planes):
            straddle += 1

    def join_group(group: list, name: str):
        """功能: 把一组对象合并为一个并命名. 参数: group 对象列表, name 目标名. 返回值: 合并后对象"""
        bpy.ops.object.select_all(action="DESELECT")
        for part in group:
            part.select_set(True)
        bpy.context.view_layer.objects.active = group[0]
        bpy.ops.object.join()
        joined = bpy.context.view_layer.objects.active
        joined.name = name
        return joined

    # 先全部改临时名, 避免 join 之后目标名位被 .001 副本占住
    for index, part in enumerate(parts):
        part.name = f"_TWRSPLIT_{index}"

    def metal_material(recipe_name: str):
        """
        功能: 按名从 materials.yaml 各段里解析配方并建材质实例.

        实例名遵循 assign_materials 的"类名_颜色"约定, 这样与同款原生外观件共享实例,
        也能被按材质合并归到一组 —— 顶盖与外壳配同一个配方时不会多出一次 draw call.
        参数: recipe_name 配方名
        返回值: 材质
        """
        recipe = None
        for section in materials_cfg.values():
            if isinstance(section, list):
                for item in section:
                    if isinstance(item, dict) and item.get("name") == recipe_name:
                        recipe = item
                        break
            if recipe is not None:
                break
        if recipe is None:
            log(f"三色灯拆分: materials.yaml 里找不到配方 {recipe_name}, 用内置抛光钢兜底")
            recipe = {"name": recipe_name, "base_color": "#d8dde4", "roughness": 0.15, "metalness": 0.96}
        spec = {key: value for key, value in recipe.items() if key not in ("patterns", "parts")}
        color = str(spec.get("base_color", "#d8dde4"))
        spec["name"] = f"{recipe_name}_{color.lstrip('#').upper()}"
        return build_material(spec)

    # 护栏: 任一段为空说明 ratio 配错了, 合回原样退出, 别把灯拆坏
    empty = [label for label, group in (("灯罩", upper), ("外壳", lower)) if not group]
    if cap_z is not None and not cap:
        empty.append("顶盖")
    if empty:
        join_group(parts, orig_name)
        log(
            f"三色灯拆分: ratio={ratio}/cap_ratio={cap_ratio} 下 {'+'.join(empty)} 为空, "
            f"已还原 {orig_name}, 请检查 tower_split 配置"
        )
        return {"skipped": "empty_side", "ratio": ratio, "cap_ratio": cap_ratio, "empty": empty}

    join_group(upper, orig_name)  # 灯罩: 保留原名与 MAT_STATUS_LIGHT
    lower_obj = join_group(lower, orig_name + str(config.get("lower_suffix", "_HOUSING")))
    lower_material = metal_material(str(config.get("lower_material", "MAT_NAT_POLISHED_STEEL")))
    lower_obj.data.materials.clear()
    lower_obj.data.materials.append(lower_material)

    report = {
        "target": orig_name,
        "upper_parts": len(upper),
        "lower_parts": len(lower),
        "straddle": straddle,
        "plane_z": round(float(plane_z), 5),
        "lower_object": lower_obj.name,
        "lower_material": lower_material.name,
    }
    cap_detail = ""
    if cap_z is not None:
        cap_obj = join_group(cap, orig_name + str(config.get("cap_suffix", "_CAP")))
        cap_material = metal_material(
            str(config.get("cap_material", config.get("lower_material", "MAT_NAT_POLISHED_STEEL")))
        )
        cap_obj.data.materials.clear()
        cap_obj.data.materials.append(cap_material)
        report.update({
            "cap_parts": len(cap),
            "cap_object": cap_obj.name,
            "cap_material": cap_material.name,
            "cap_plane_z": round(float(cap_z), 5),
        })
        cap_detail = (
            f" + 顶盖 {len(cap)} 壳体({cap_obj.name} <- {cap_material.name}, 切分面 Z={cap_z:.4f}m)"
        )

    log(
        f"三色灯拆分: {orig_name} -> 灯罩 {len(upper)} 壳体 + 外壳 {len(lower)} 壳体"
        f"({lower_obj.name} <- {lower_material.name}); 切分面 Z={plane_z:.4f}m, "
        f"跨缝 {straddle}{cap_detail}"
    )
    return report


# ---------------------------------------------------------------------------
# 注射泵风格化
# ---------------------------------------------------------------------------


# 注射泵(润泽 SY-03B)在 CAD 里只是 686 三角形的占位方壳, 真机是**黑色阳极氧化机身**:
# 正面上部一个朝前的圆阀头(带端口与螺钉), 其下竖置玻璃注射器, 再下一条长竖窗露出丝杆
# 与滑车. 本机三台均**倒装**, 所以装机后阀头在下、竖窗在上.
# 官方不公开任何三维数模(润泽只放说明书/协议 PDF/选型手册, GrabCAD 与 TraceParts 亦无),
# 故照官方"产品尺寸mm"图程序化重建外形.
#
# 2026-08-05 返工: 上一版被用户判为"完全没有办法接受". 事后审计的六条结构性错误与它们的
# 修法都写在下面各段的注释里 —— 简述: 阀头轴线建成了竖直的(于是没有正圆端面)、正面糊了
# 一块 55×245 的镜面铝板(真机是黑机身)、玻璃针筒因参数落在"会消失"那一档而整根不存在、
# 刻度做成了 6 块贯穿针筒的实心白圆盘、导轨与丝杆 100% 被埋、滑车与竖槽共面闪烁.
#
# 官方尺寸(2026-08-05 自润泽产品页的"产品尺寸mm"图读得, 单通道 SY-03B). 图是 JPG,
# 官网只放说明书/ASCII·CAN 协议/选型手册, 没有任何 CAD 文件, GrabCAD 与 TraceParts 亦无
# 此型号 —— 要复核尺寸只能回去看这两张图:
#   正面/背面/侧面 https://www.runzefluidsystem.com/static/upload/image/20250314/1741933236464683.jpg
#   阀头选型/底面   https://www.runzefluidsystem.com/static/upload/image/20250314/1741933240365869.jpg
#   总高 253.3 / 前面板宽 55 / 机体宽 65 / 主体进深 114.5 / 注射器前伸 32 / 侧面总深 151
#   正面 6-M4↧8 安装孔, 底面 4-M3↧6 孔距 40, 背面 M3↧5 接地孔 + DB15 接头
#   T-04 / T-06 阀头: Ø28 × 高 35, 自面板前伸 28.7
#   额定行程 60mm / 6000 步 / 梯形丝杆导程 6mm
# 这些数与 CAD 占位件逐位吻合 —— 实测占位件是个两级台阶体: 主体 Y∈[-114.5,0] 恰是官方
# 114.5, 前脸凸台 35(X)×230(Z)×30(Y深) 恰是官方 32 的注射器前伸区, 总高 253.3 完全相等.
# 即集成商当年就是照这张图建的占位件, 故 60/144.5/253.3 可直接当基准, 无需再核.
#
# 前脸判定: 凸台只长在局部 -Y 侧(+Y 背面仅 2 个纯平三角形, 是贴安装板的面), 是几何硬证据.
PUMP_FRONT_AXIS = "-Y"

# 竖向朝向: 2026-08-05 用户对实机确认 —— 本机三台泵**均倒装**, 阀头朝下.
# 于是局部 Z 由低到高 = 阀头 → 玻璃针筒 → 柱塞夹头 → 丝杆(正好是官方图从上往下),
# 且实测三台泵的 matrix_world 都满足"局部 +Z = 世界正上", 无一台被转过.
# 由此定死抽液方向: **吸液 = 柱塞上行 = 液柱自筒底向上涨**, 故液柱原点放在底面.
# 若日后有泵改成正装, 翻本常量并重跑 03 即可(整套布局按它镜像).
PUMP_VALVE_AT = "bottom"

# 占位件包围盒的标称毫米值. 下面 PUMP_LAYOUT_MM 里所有数都以它为基准折算成分数,
# 因此顶点空间是 mm 还是 m(normalize_units 之后恒为米)都免疫.
PUMP_NOMINAL_MM = {"w": 60.0, "d": 144.5, "h": 253.3}

# 局部布局, 单位 mm. 三个坐标的含义(见 build_pump_visuals 里的 P() ):
#   u = 沿宽偏移, 0 = 泵体中线, 范围 ±30
#   d = 自**最前面**(原凸台前脸)向机体内的距离, 0 = 最前; 负值 = 再往前伸
#   h = 沿高偏移, 0 = 泵体中心, 范围 ±126.65; 低 = 阀头端, 高 = 丝杆端(倒装)
#
# 深度分层(2026-08-05 返工定, 同日按实物照二次订正阀头):
#   d ∈ [ 2,  32]  阀头区: 指针盘 2.05→5.05 | 阀盘 5.2→20.2 | 阀座 19.7→32(扎进机体)
#   d ∈ [ 0,  30]  玻璃针筒区(原凸台占的体积, 现在放真东西); 针筒/阀轴心 d = 12.7
#   d ∈ [28, 30.5] 黑色前盖 —— 四条边框补上删凸台后留下的 35×230 洞, 中间留竖窗
#   d ∈ [34,  44]  竖窗内腔: 丝杆 + 滑车(前后各留 1mm 以上, 根治滑车共面闪烁)
#   d ∈ [45,  48]  窗底板 + 四面窗壁(不加就会从窗口看穿到机体背面的背面)
#   d ∈ [30,144.5] 机体本体(占位件, 已由规则赋 MAT_PUMP_BODY)
#
# 返工删掉的三组(上一版的病根, 别再加回来):
#   铝面板  —— 55×245 的镜面银板盖住整个正面, 真机是黑机身, 观感彻底反转
#   刻度环  —— 6 块 Ø28.5 实心白圆盘, 径向只凸 0.25mm(0.2 像素)却切进液柱与柱塞杆;
#              整机取景 0.8 px/mm, 真刻度线物理上画不出来, 且管线零 UV 零贴图
#   导轨条  —— 100% 埋在竖槽盒内部, 一个像素都看不到
PUMP_LAYOUT_MM = {
    "pattern": "^注射泵|^zhu_she_beng",
    # --- 阀头: **Ø40 × 15 厚的米白 PEEK 盘, 接针筒那一侧被一条弦切成平口** -------
    # 2026-08-05 用户对着实物纠正 + 重读官方**正面尺寸图**(dim_bm_1.jpg)佐证:
    # 正面图里阀头是个大圆, 拿 55mm 前板宽作标尺量直径 ≈ 40(明显比 Ø28 针筒粗一圈),
    # 且圆的底边(接针筒那一侧)是截平的, 平口上正好托住压紧针筒的滚花螺母.
    #
    # 上一版把细节图里的 "Ø28" 当成了阀头直径 —— 那是别的特征. 官方给 T-04/T-06/T-08 的
    # 另外两个数(自面板前伸 28.7、组件高 35)是**总成包络**, 与 Ø40×15 的 PEEK 盘 + 盘后
    # 到面板之间那截黑色阀座恰好凑得上:
    #     面板 d=30 → 阀座 → 盘后 d=20.2 → 盘前 d=5.2(前伸 24.8) → 螺钉头/指针盘 → 前伸 27.9
    #
    # 端口不是绕轴心 360° 均布, 而是**全挤在下半圈、径向朝外**甩出(用户实测 + 已确认朝向).
    # valve_h 由官方正面图量出: 拿三个安装孔(距面板端 4.2/126.7/249.2)标定出 0.4935 mm/px,
    # 阀心距面板端 38.0mm → 泵中心系 ±88.5(倒装取负). 上一次拍 -98 偏出去 9.5mm, 接头
    # 差点探出泵底.
    "valve_r": 20.0, "valve_len": 15.0, "valve_h": -88.5,
    "valve_face_d": 5.2,                 # 阀盘前端面(d), 盘后端面 = 5.2 + 15 = 20.2
    "valve_chord": 13.5,                 # 平口: 弦到盘心 13.5 → 平口宽 2√(20²−13.5²) = 29.5
    # 正面凸台: 官方正面图上阀头是**两个同心圆** —— 外圈 Ø38.5 的法兰 + 内圈一圈凸出的
    # 主体. 少了这一层就读成一块没细节的白饼. 取 Ø30 而不是图上量到的 Ø33, 是为了给
    # screw_ring_r 让出一圈干净的法兰面(见下条).
    "valve_hub_r": 15.0, "valve_hub_t": 2.0,
    "valve_boss_r": 12.0, "valve_boss_d1": 32.0,   # 阀座: 自盘后 20.2 穿过前盖扎进机体
    # 端口: 黄铜滚花**鲁尔接头**, 沿半径朝外, 全部落在 port_arc 这段下弧里.
    # 三段尺寸照 CAD 里现成的 `PTLC-03-031 鲁尔接头-1` 逐层量出来的回转轮廓折算
    # (实测总长 16.5 / 最大 Ø8.02, 形状是 "Ø4 杆 → Ø8 滚花箍 → Ø6 头"), 不是拍的.
    #
    # port_arc 首尾**降序**: 用户按实物指认 1 号口在右(335°)、末号口在左(205°).
    # 前脸朝 -Y 看进去时屏幕右 = +u(right = forward × up = Ŷ × Ẑ = X̂), 故 335° 在右.
    # 若现场编号起点相反, 把这一对首尾对调即可, 其余全链自动跟着走.
    "port_arc": (335.0, 205.0),
    "luer_stem_r": 1.6, "luer_stem_r0": 18.0, "luer_stem_r1": 21.0,
    # 滚花箍**自 r=21 才起**: 螺钉圈外缘 17.5+1.9 = 19.4, 再往里就会与螺钉同面且真重叠
    # (第二轮正是这种叠法一次报出 24 对共面)
    "luer_knurl_r": 4.0, "luer_knurl_r1": 28.0, "luer_knurl_seg": 20,
    "luer_nose_r": 3.0, "luer_nose_r1": 31.5,
    # 螺钉落在凸台之外的那圈法兰上: 内缘 17.5-1.9 = 15.6 > valve_hub_r, 外缘 19.4 < valve_r,
    # 两头都不许蹭 —— 蹭上就是"同一个平面上还真重叠"的 z-fighting.
    "screw_r": 1.9, "screw_len": 2.0, "screw_ring_r": 17.5,
    # 三颗成**正三角**且一颗在正下方(用户 2026-08-05 指出 250° 是"偏左下", 不对):
    # 30/150/270 两两相差 120°, 270° 正下.
    "screw_angles": (30.0, 150.0, 270.0),
    # 可转指示盘(定子带端口不动, 转的是面心指示盘 —— 真机转子在内部, 外面看不见).
    # pointer_r1 必须小于 screw_ring_r - screw_r(= 16.1): 250° 那颗螺钉正落在指针的
    # 扫掠弧里, 指针再长一点就会从螺钉头里穿过去.
    "rotor_r": 6.0, "rotor_t": 3.0, "pointer_w": 1.5, "pointer_r0": 3.0, "pointer_r1": 15.0,
    # --- 玻璃针筒(薄壁管: 外径对齐 ST_COLLECT/注射器-1 实测 Ø28×100.5; 内径 Ø23 = 25mL/60mm) ---
    # syringe_d 12.7 = 30 − 17.3, 官方底面尺寸图标的"进样器轴心(在前板前方)17.3".
    #
    # 针筒起点由平口**算出来**(barrel_h0 = flat_h + barrel_gap), 不再写死 —— 两者一旦
    # 各写各的就会错位: 针筒 Ø28 在**进深**上比只有 15 厚的阀盘还宽 13mm, 只要它往阀盘里
    # 塞一点, 前后各有 6.5mm 玻璃从阀盘表面穿出来(实测渲染: 阀盘正面糊着一条竖直的玻璃).
    # 所以针筒必须**停在平口上方**, 中间那 2mm 缝由滚花螺母骑过去盖住.
    #
    # 官方图上那根 Ø13 带 0.5~2.5 刻度的是**标配 2.5mL 针筒**; 本机用 25mL 适配器, 故取
    # Ø28 外 / Ø23 内(25mL ÷ 60mm 行程反推), 与 ST_COLLECT/注射器-1 实测一致.
    "syringe_d": 12.7,                   # 针筒/阀共用的轴线深度
    # barrel_len 不写死: 它必须 = 液柱起点余量 1 + 柱塞头 5 + 行程 60 + 筒口余量 2 = 68.
    # 写死 92 时满行程柱塞头顶距筒口还剩 31mm, 画面上就是"量程没拉满"(用户 2026-08-05 指出).
    # 由 _derive_pump_layout 按 stroke/plunger_len 算出来, 改行程时不会有人忘记跟着改筒长.
    "barrel_ro": 14.0, "barrel_ri": 11.5, "barrel_gap": 2.0,
    "barrel_head": 2.0,                  # 满行程时柱塞头顶到筒口(内)的余量
    # 下压环 = 照片里那颗银色滚花螺母, 坐在平口上并下沉 1mm(免底面与平口面共面)
    "collar_lo_r": 14.5, "collar_lo_len": 8.0,
    "collar_hi_r": 15.0, "collar_hi_len": 5.0,
    # --- 液柱与柱塞(行程 60mm; 半径取内径减留量, 免与筒内壁 z-fighting) ---
    # liquid_r 必须**小于** plunger_r: 柱塞头刻意下沉 0.2mm 进液柱(免顶面共面), 两者半径
    # 一旦逐位相同, 那 0.2mm 就成了一段共面的**圆柱侧面** —— 实测就是液面顶部那圈竖条纹
    # (用户 2026-08-05 截图). 缩到 11.0 后柱塞头(11.2)在径向罩住液柱, 条纹消失.
    "liquid_r": 11.0, "stroke": 60.0,
    "liquid_gap": 1.0,                   # 液柱底距筒内底的余量(免与筒底端盖共面)
    # plunger_len 5 而不是 12(用户 2026-08-05 指出"推杆头太厚"): 12 配 Ø22.4 的头长径比
    # 12:22.4, 在筒内读成一截粗短圆柱塞; 实物 Ø22 腔的 PTFE/丁基活塞密封件是 4~8mm 的**薄盘**.
    # ⚠ 改它会连带一串: barrel_len 是派生值(见上), 头薄 7mm ⇒ 筒长 -7、筒口下移 7、
    # 上压环/夹头/滑车整条链下移 7 ⇒ win_h0 与 lead_h0 必须跟着下移(见各自注释).
    "plunger_r": 11.2, "plunger_len": 5.0,
    "rod_r": 4.0, "clamp_w": 7.0, "clamp_len": 12.0, "clamp_d1": 40.0,
    "slider_w": 7.0, "slider_len": 18.0, "slider_d0": 34.0, "slider_d1": 44.0,
    # --- 前盖与竖窗 ---
    # 前盖只比机体前脸凸 0.4mm: 它的职责只是补上删凸台留下的 35×230 洞, 不是一块独立面板.
    # 凸 2mm 时它会自己接光, 在正视图上读成"机体上又盖了一块板"(三层嵌套矩形).
    "cover_w": 18.0, "cover_h": 116.0, "cover_d0": 29.6, "cover_d1": 30.5,
    # win_h0 −3 而不是 14: 筒长两次改动(92→75→68)后整条柱塞链累计下移 24mm, 滑车底
    # (= clamp_h0)在 level=0 落到 0 —— 窗下沿还留在原处就是"滑车从窗口下沿钻出去".
    # 取 −3 留 3mm 余量. 窗底板(h −4…−3)与筒顶(−5)只差 1mm, 但两者**进深不同**
    # (窗在 d≥30.5, 针筒轴心 d=12.7), 撞不上, 也不共面.
    "win_w": 9.0, "win_h0": -3.0, "win_h1": 108.0,
    "win_wall": 1.0, "win_floor_d0": 45.0, "win_floor_d1": 48.0,
    # 丝杆必须覆盖整个 60mm 行程 —— 上一版只有 22mm 且与滑车行程零重叠.
    # 梯形丝杆导程 6mm(官方 SY-03B 规格), 行程 60mm ⇒ **满行程正好 10 圈**.
    # lead_thread_*: 螺纹是一根沿螺旋线扫出来的管. 光面圆柱绕自身轴转在画面上是**完全
    # 看不出来的**, 要让"丝杆在转"读得出来就必须有螺纹这条可跟踪的线索.
    # lead_h0 −2: 柱塞头改薄后滑车下死点降到 0, 丝杆下端不跟着下移就会"滑块悬在丝杆下方".
    # 上端 112 不动 —— 已覆盖滑车上死点 78 且不顶穿泵顶(126.65).
    "lead_r": 2.2, "lead_d": 40.0, "lead_h0": -2.0, "lead_h1": 112.0,
    "lead_pitch": 6.0, "lead_thread_r": 2.9, "lead_thread_t": 0.75,
    "lead_thread_steps": 10,          # 每圈采几个点(10 × 19 圈 = 190 点)
    # --- 黑壳细节 ---
    # 侧面散热槽与正面 6-M4 沉孔刻意不建 —— 都是凹特征, 累积器减不出来, 贴个盒子上去
    # 就必然与机体表面共面(z-fighting); 而 0.8 px/mm 下它们本就在可读阈值以下. 详见
    # build_pump_visuals 里那段注释.
    "conn_w": 16.0, "conn_d0": 134.0, "conn_h0": 96.0, "conn_h1": 118.0,
    # --- 指示灯(绿/绿/红) ---
    # 2026-08-05 用户按实物纠正: 三颗灯在**侧面**、**横排**、**红灯在最右**.
    # 于是灯柱沿宽度轴(侧面的法向), 三颗沿进深轴排开、同一高度.
    # "最右"的解释: 站在该侧面外朝里看, 视线 -X、上 +Z 时右手边是 +Y —— 即**进深增大**
    # 的方向(朝机体后方), 所以红灯取最大的 d. 若实物是另一侧的面, 把 led_side 翻成 -1,
    # 那一侧看过去的"右"随之反向, 同时把 led_step 取负即可.
    "led_r": 2.0, "led_len": 1.6, "led_side": 1.0,
    "led_h": -65.0, "led_d0": 55.0, "led_step": 9.0,
    # --- 蓝色软管 ---
    "tube_r": 2.2,
    # --- 材质配方名(跨段按名检索 materials.yaml; 只覆写颜色的用 override) ---
    "rules": {
        # 前盖/窗壁**不覆写颜色**: 与机体命中同一个 MAT_PUMP_BODY_1A1B1E 实例, 正面才读成
        # 一整片机身而不是"机体上又贴了块板"; 顺带还能与机体并进同一个 STATIC 块.
        "shell": ("MAT_PUMP_BODY", None),
        # 丝杆压暗: 裸配方是 #dde2e8 + metalness 0.97(全泵最亮的抛光镀铬), 在深色窗口里
        # 会读成一条刺眼白条; 实物那根是发暗的丝杆.
        "rail": ("MAT_GUIDE_RAIL", "#6a7078"),
        "slider": ("MAT_GUIDE_BLOCK", None),
        # 针筒专用玻璃: 绝不复用 MAT_GLASS(它还罩着展缸等件, 改它会波及全机).
        # 那份配方 transmission 0.92 + alpha 0.28 正是 plateMaterials.js:47 记着的
        # "透射再高会让玻璃在深色背景里消失"的那一档.
        "glass": ("MAT_SYRINGE_GLASS", None),
        "ferrule": ("MAT_ALUMINUM", None),          # 只剩上下两个压环, 不再是整块面板
        "valve": ("MAT_PLASTIC", None),             # #ddd9ce 正是米白 PEEK
        "rotor": ("MAT_NAT_WHITE", None),
        # 黄铜鲁尔接头. MAT_NAT_GOLD 是 #b08d57 / roughness 0.38 / metalness 0.94,
        # materials.yaml 里现成, 但整机此前没有任何件命中它 —— 本段是它的第一个用户.
        "luer": ("MAT_NAT_GOLD", None),
        "plunger": ("MAT_POWDER_BUCKET", None),     # 裸名共享实例(functional_overrides 已 eager 建)
        "liquid": ("MAT_LIQUID", None),             # 裸名; alpha 1.0 无 transmission, 绝不可改
        # 指示灯自建类, 不蹭 MAT_STATUS_LIGHT(那是裸名共享实例, 被前端状态灯克隆驱动).
        "led_green": ("MAT_PUMP_LED_GREEN", "#35d17a"),
        "led_red": ("MAT_PUMP_LED_RED", "#e0503c"),
    },
    # 指示灯的自发光参数(find_recipe 找不到上面两个类名, 会走兜底, 这里补齐发光)
    "led_emission": {"emission_strength": 0.8, "roughness": 0.35, "metalness": 0.0},
}


def _derive_pump_layout(base: dict) -> dict:
    """
    功能: 把 PUMP_LAYOUT_MM 里可由别的尺寸推出来的项算出来, 回传新 dict(不改原表).

    只算 barrel_len 一项: 玻璃筒必须刚好装下"液柱起点余量 + 柱塞头 + 满行程 + 筒口余量".
    写死过一版 92, 结果满行程时柱塞头顶距筒口还剩 31mm —— 画面上读成"量程没拉满".
    派生之后改 stroke 或 plunger_len 都不必再记得回来改筒长.
    """
    out = dict(base)
    out["barrel_len"] = (base["liquid_gap"] + base["plunger_len"]
                         + base["stroke"] + base["barrel_head"])
    return out



class _PumpPart:
    """
    功能: 把若干轴对齐盒 / 圆柱 / 折线管累积进**一个**网格(from_pydata 手写顶点, 法线朝外).

    为什么要累积器而不是一物一网格: 上样泵那台挂在 CARRIAGE.006 下, 受 join_static_per_station
    的保护前缀庇护、不参与合并 —— 每个盒各自成对象的话, 光它一台就要独吞三十几个图元, 而
    05_report 的绘制调用门禁(500)当前只剩九十来个余量. 按材质各攒一个网格, 每台泵只出 8 个
    静态对象, 且三台泵顶点逐位相同, 04 的 dedup 还会把它们折成一份.

    纯手写顶点表, 不碰 bmesh 算子, 免疫 Blender 版本差异.
    """

    def __init__(self) -> None:
        self.verts: list[tuple] = []
        self.faces: list[tuple] = []
        # 与 faces 等长: 圆柱/管的侧面 True(平滑), 盒与端盖 False(平直)
        self.smooth: list[bool] = []

    @property
    def empty(self) -> bool:
        """功能: 是否一个面都没攒到. 参数: 无. 返回值: bool"""
        return not self.faces

    def _add(self, verts: list, faces: list, smooth: list) -> None:
        """功能: 追加一批顶点与面, 自动偏移面的顶点下标. 参数: verts/faces/smooth. 返回值: None"""
        base = len(self.verts)
        self.verts.extend(verts)
        self.faces.extend(tuple(base + i for i in face) for face in faces)
        self.smooth.extend(smooth)

    def box(self, bounds_min: Vector, bounds_max: Vector) -> "_PumpPart":
        """
        功能: 攒一个轴对齐盒.
        参数:
            bounds_min: 一角(不要求逐轴都比 bounds_max 小, 内部会排序)
            bounds_max: 对角
        返回值: self(便于链式调用)
        """
        x0, x1 = sorted((bounds_min[0], bounds_max[0]))
        y0, y1 = sorted((bounds_min[1], bounds_max[1]))
        z0, z1 = sorted((bounds_min[2], bounds_max[2]))
        verts = [
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
        ]
        # 面表与 _pump_box 一致(法线朝外)
        faces = [
            (0, 3, 2, 1), (4, 5, 6, 7),
            (0, 1, 5, 4), (2, 3, 7, 6),
            (0, 4, 7, 3), (1, 2, 6, 5),
        ]
        self._add(verts, faces, [False] * len(faces))
        return self

    @staticmethod
    def _unit_ring(segments: int) -> list:
        """功能: 单位圆上均布的 (cos, sin) 表. 参数: segments 分段数. 返回值: list[tuple]"""
        return [
            (math.cos(math.tau * i / segments), math.sin(math.tau * i / segments))
            for i in range(segments)
        ]

    @staticmethod
    def _span(length: float, anchor: str) -> tuple:
        """
        功能: 按 anchor 与正负号归一出 z0 < z1 的轴向区间.

        length 允许为负(调用方用 up*len 表达"朝下长"). 必须归一成 z0 < z1, 否则侧面绕序
        会整体翻转、法线朝内 —— 现象是模型从外面看变成透明/黑面. anchor="base" 时基准面
        恒在 0, 与正负无关.

        参数: length 轴向长度(可负); anchor "center" 或 "base"
        返回值: (z0, z1)
        """
        if anchor == "base":
            return (0.0, length) if length >= 0 else (length, 0.0)
        half = abs(length) / 2.0
        return -half, half

    @staticmethod
    def _axis_place(center: Vector, axis: str):
        """
        功能: 造一个把"回转体本地系(c 为轴向)"轮换到泵局部系的映射函数.

        用**坐标轮换**而不是旋转矩阵: 轮换是偶置换(行列式 +1), 既保住法线绕序, 又让顶点
        仍是精确的轴对齐值 —— 04 的 weld 才焊得上, 也才能让三台泵逐位相同而被 dedup.

        参数: center 轴线基准点; axis "X"/"Y"/"Z"
        返回值: callable(a, b, c) -> tuple
        """
        def place(a: float, b: float, c: float) -> tuple:
            """功能: 本地 (a,b,c) → 泵局部坐标. 参数: a/b 截面内; c 轴向. 返回值: tuple"""
            if axis == "X":
                return (center[0] + c, center[1] + a, center[2] + b)
            if axis == "Y":
                return (center[0] + b, center[1] + c, center[2] + a)
            return (center[0] + a, center[1] + b, center[2] + c)
        return place

    def pipe(self, center: Vector, r_outer: float, r_inner: float, length: float,
             axis: str = "Z", segments: int = 24, anchor: str = "center") -> "_PumpPart":
        """
        功能: 攒一根薄壁管 —— 外壁 + 内壁 + 两个环形端盖.

        玻璃针筒必须用它而不是 cyl: 实心圆柱**没有内表面**, 少了玻璃最重要的视觉线索
        (两层壁各自的高光边), 在整机远景里直接读成空气. 2026-08-05 返工前的针筒就是实心柱,
        用户看到的成品里它整根不存在, 只剩罩在里面的柱塞杆与刻度盘悬空.

        内壁绕序是外壁的镜像(法线朝轴心), 否则从筒口看进去内壁会被背面剔除掉.

        参数:
            center: 轴线基准点
            r_outer: 外半径
            r_inner: 内半径(必须小于 r_outer)
            length: 轴向长度(可负)
            axis: "X" / "Y" / "Z"
            segments: 圆周分段数
            anchor: "center" 或 "base"
        返回值: self
        """
        if not (r_outer > r_inner >= 0.0):
            raise SystemExit(f"_PumpPart.pipe: 内外半径非法 r_outer={r_outer} r_inner={r_inner}")
        z0, z1 = self._span(length, anchor)
        ring = self._unit_ring(segments)
        place = self._axis_place(center, axis)
        seg = segments

        verts = [place(r_outer * cx, r_outer * cy, z0) for cx, cy in ring]          # 0
        verts += [place(r_outer * cx, r_outer * cy, z1) for cx, cy in ring]         # seg
        verts += [place(r_inner * cx, r_inner * cy, z0) for cx, cy in ring]         # 2*seg
        verts += [place(r_inner * cx, r_inner * cy, z1) for cx, cy in ring]         # 3*seg

        faces, smooth = [], []
        for i in range(seg):
            j = (i + 1) % seg
            faces.append((i, j, seg + j, seg + i))                     # 外壁, 法线朝外
            smooth.append(True)
            faces.append((2 * seg + j, 2 * seg + i, 3 * seg + i, 3 * seg + j))  # 内壁, 法线朝轴
            smooth.append(True)
            # 两个环形端盖的绕序与内外壁**相反**: 手推 4 段特例时这两片曾朝里, 现象是
            # 有向体积只有理论值的 1/3(壁对了、盖反了), 而"总体积 > 0"这条粗筛看不出来.
            faces.append((j, i, 2 * seg + i, 2 * seg + j))             # z0 环形端盖, 法线 -轴
            smooth.append(False)
            faces.append((seg + i, seg + j, 3 * seg + j, 3 * seg + i))  # z1 环形端盖, 法线 +轴
            smooth.append(False)
        self._add(verts, faces, smooth)
        return self

    def disc_ring(self, center: Vector, r_outer: float, r_inner: float, thickness: float,
                  axis: str = "Z", segments: int = 24) -> "_PumpPart":
        """
        功能: 攒一片环形薄盘(压环 / 阀头面板台阶用). 就是极短的 pipe.
        参数: center 中心; r_outer 外半径; r_inner 内半径; thickness 厚度; axis; segments
        返回值: self
        """
        return self.pipe(center, r_outer, r_inner, thickness, axis=axis,
                         segments=segments, anchor="center")

    def dcyl(self, center: Vector, radius: float, length: float, chord: float,
             axis: str = "Z", segments: int = 24, anchor: str = "center",
             chord_dir: tuple = (0.0, 1.0)) -> "_PumpPart":
        """
        功能: 攒一根**截圆柱(D 形柱)** —— 圆被一条弦切掉一块, 截面 = 圆弧 + 一条平直的弦.

        阀头必须用它: 实物那块米白 PEEK 盘在接针筒的那一侧是**平口**(用户 2026-08-05 实测,
        官方正面尺寸图上也画得出来 —— 圆的底边是截平的, 平口上正好托住压紧针筒的滚花螺母).
        累积器没有布尔运算减不出这一刀, 只能直接把 D 形截面写出来.

        保留的是 `a*ca + b*cb <= chord` 的那一侧(ca, cb 来自 chord_dir).

        ⚠ chord_dir 必须由调用方按轴向给: _axis_place 是坐标轮换, axis="X" 时截面 (a,b)→(Y,Z),
        axis="Y" 时 (a,b)→(Z,X) —— "哪个分量是高度"随轴而变, 写死 (0,1) 会在另一个轴向上
        把刀切到侧面去.

        参数:
            center: 轴线基准点
            radius: 圆半径
            length: 轴向长度(可负)
            chord: 弦到圆心的**有符号**距离; >= radius 退化成整圆, <= -radius 什么都不剩
            axis: "X" / "Y" / "Z"
            segments: 整圆的名义分段数(实际弧上按保留比例取点)
            anchor: "center" 或 "base"
            chord_dir: 截面内指向"被切掉那一侧"的单位向量 (ca, cb)
        返回值: self
        """
        if radius <= 0.0:
            raise SystemExit(f"_PumpPart.dcyl: 半径非法 radius={radius}")
        if chord <= -radius:
            raise SystemExit(f"_PumpPart.dcyl: 弦切光了整个圆 chord={chord} radius={radius}")
        if chord >= radius:                                   # 没切到, 退化成整圆
            return self.cyl(center, radius, length, axis=axis,
                            segments=segments, anchor=anchor)

        ca, cb = chord_dir
        norm = math.hypot(ca, cb)
        if norm < 1e-9:
            raise SystemExit(f"_PumpPart.dcyl: chord_dir 是零向量 {chord_dir}")
        ca, cb = ca / norm, cb / norm
        base_ang = math.atan2(cb, ca)                         # 弦法向的方位角
        alpha = math.acos(chord / radius)                     # 保留弧的半角(自弦法向量起)
        # 保留弧: 自 base+alpha 逆时针走到 base+(tau-alpha). 两个端点恰好落在弦上, 弦本身
        # 不再另采点 —— 这样截面是一条封闭折线, 弦那一段就是最后一条边.
        sweep = math.tau - 2.0 * alpha
        count = max(3, int(round(segments * sweep / math.tau)) + 1)
        z0, z1 = self._span(length, anchor)
        place = self._axis_place(center, axis)

        ring = []
        for i in range(count):
            ang = base_ang + alpha + sweep * i / (count - 1)
            ring.append((math.cos(ang), math.sin(ang)))
        verts = [place(radius * a, radius * b, z0) for a, b in ring]
        verts += [place(radius * a, radius * b, z1) for a, b in ring]
        verts += [place(0.0, 0.0, z0), place(0.0, 0.0, z1)]
        lo_center, hi_center = 2 * count, 2 * count + 1

        faces, smooth = [], []
        for i in range(count):
            j = (i + 1) % count
            # i == count-1 那一片跨的是**弦** —— 单独 use_smooth=False, 平口要读成一个硬边;
            # 混进平滑组的话法线会被插值抹圆, 平口在渲染上就消失了.
            faces.append((i, j, count + j, count + i))
            smooth.append(i != count - 1)
        for i in range(count):
            j = (i + 1) % count
            # 端盖扇心取圆心: chord > -radius 保证圆心在多边形内, 扇形三角不会自交.
            # 绕序照 cyl —— 上一轮 pipe 的两个环形端盖全反了, "有向体积 > 0"那条粗筛还是绿的.
            faces.append((lo_center, j, i))
            smooth.append(False)
            faces.append((hi_center, count + i, count + j))
            smooth.append(False)
        self._add(verts, faces, smooth)
        return self

    def cyl(self, center: Vector, radius: float, length: float, axis: str = "Z",
            segments: int = 20, anchor: str = "center", smooth: bool = True) -> "_PumpPart":
        """
        功能: 攒一根实心圆柱(侧面默认平滑, 端盖恒平直).

        参数:
            center: 轴线基准点; anchor="center" 时是圆柱中心, "base" 时是底面圆心
            radius: 半径
            length: 轴向长度
            axis: "X" / "Y" / "Z"
            segments: 侧面分段数
            anchor: "center" 或 "base"(底面落在 center 上)
            smooth: 侧面是否平滑着色. 取 False 时每个分段各自平直 —— 这是**滚花**的做法:
                鲁尔接头的滚花箍用 20 边形 + 平直着色, Ø8 上 20 个棱 = 1.25mm 棱距, 与真
                滚花同量级, 代价只有 20 个四边形(真去建肋要几百个面)
        返回值: self
        """
        smooth_side = smooth          # 下面 faces/smooth 那个局部 list 会遮住同名形参
        z0, z1 = self._span(length, anchor)
        ring = self._unit_ring(segments)
        place = self._axis_place(center, axis)

        verts = [place(radius * cx, radius * cy, z0) for cx, cy in ring]
        verts += [place(radius * cx, radius * cy, z1) for cx, cy in ring]
        verts += [place(0.0, 0.0, z0), place(0.0, 0.0, z1)]
        lo_center, hi_center = 2 * segments, 2 * segments + 1
        faces, smooth = [], []
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((i, j, segments + j, segments + i))   # 侧面, 法线朝外
            smooth.append(smooth_side)
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((lo_center, j, i))                     # 底盖
            smooth.append(False)
            faces.append((hi_center, segments + i, segments + j))  # 顶盖
            smooth.append(False)
        self._add(verts, faces, smooth)
        return self

    def tube(self, points: list, radius: float, segments: int = 8,
             smooth: bool = True) -> "_PumpPart":
        """
        功能: 沿折线扫掠一根圆管(任意方向的回转体都靠它 —— 径向的轴不落在任何坐标轴上,
              cyl 的坐标轮换用不了).

        用平行输运帧而不是逐段独立取法线: 独立取法线时相邻段的环起始角对不上, 侧面会拧成
        麻花. 首帧拿与切向最不平行的世界轴叉乘起手, 之后逐段做最小旋转传递.

        参数:
            points: 折线点列(泵局部系), 至少两个
            radius: 管半径
            segments: 环分段数
            smooth: 侧面是否平滑着色. False = 每段各自平直, 用来做**滚花**(鲁尔接头的箍)
        返回值: self
        """
        smooth_side = smooth          # 下面 faces/smooth 那个局部 list 会遮住同名形参
        pts = [Vector(tuple(p)) for p in points]
        count = len(pts)
        if count < 2:
            return self
        tangents = []
        for i in range(count):
            if i == 0:
                vec = pts[1] - pts[0]
            elif i == count - 1:
                vec = pts[-1] - pts[-2]
            else:
                vec = pts[i + 1] - pts[i - 1]
            tangents.append(vec.normalized())

        def seed_for(tangent: Vector) -> Vector:
            """功能: 取一个与切向最不平行的世界轴. 参数: tangent. 返回值: Vector"""
            return Vector((0.0, 0.0, 1.0)) if abs(tangent.z) < 0.9 else Vector((1.0, 0.0, 0.0))

        normal = seed_for(tangents[0])
        verts: list = []
        for i in range(count):
            tangent = tangents[i]
            normal = normal - tangent * normal.dot(tangent)
            if normal.length < 1e-9:
                seed = seed_for(tangent)
                normal = seed - tangent * seed.dot(tangent)
            normal = normal.normalized()
            binormal = tangent.cross(normal)
            for k in range(segments):
                ang = math.tau * k / segments
                offset = (normal * math.cos(ang) + binormal * math.sin(ang)) * radius
                verts.append(tuple(pts[i] + offset))
        faces, smooth = [], []
        for i in range(count - 1):
            a, b = i * segments, (i + 1) * segments
            for k in range(segments):
                k2 = (k + 1) % segments
                faces.append((a + k, a + k2, b + k2, b + k))
                smooth.append(smooth_side)
        verts.append(tuple(pts[0]))
        verts.append(tuple(pts[-1]))
        lo_center, hi_center = len(verts) - 2, len(verts) - 1
        last = (count - 1) * segments
        for k in range(segments):
            k2 = (k + 1) % segments
            faces.append((lo_center, k2, k))
            smooth.append(False)
            faces.append((hi_center, last + k, last + k2))
            smooth.append(False)
        self._add(verts, faces, smooth)
        return self

    def build(self, name: str):
        """
        功能: 把攒好的顶点面表落成一个 Blender 对象并 link 进场景.
        参数:
            name: 对象名
        返回值: bpy.types.Object
        """
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.verts, [], self.faces)
        mesh.update()
        for poly, flag in zip(mesh.polygons, self.smooth):
            poly.use_smooth = flag
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj


def _strip_pump_boss(pump, depth_idx: int, sign: float, boss_limit: float) -> int:
    """
    功能: 删掉占位件的前脸凸台面, 只留主体.

    凸台(实测 35 × 230 × 30mm)是 CAD 对**注射器总成**的方块示意 —— 官方侧视图的
    "注射器前伸 32mm"画的就是它. 现在真的针筒/阀头/铝面板已经建出来了, 凸台就成了一块
    罩在它们外面的实心板: 它 35mm 宽正好盖住 Ø28 针筒与整条竖槽, 30mm 深正好把面板
    (d∈[27,30])埋在里面. 2026-08-05 正交前视图实测 —— 画面上只看得到一整块深灰板.

    只删"顶点全部落在凸台深度区间内"的面, 即凸台前脸与四周侧壁; 主体前脸(214 面)与
    前肩圆角(240 面, 在 d>30 一侧)原样保留. 删完主体前脸上会露出一个 35×230 的洞,
    但它整个被铝面板(55mm 宽)盖住, 面板中间的开口又被竖槽盒填实, 不会穿帮.

    参数:
        pump: 泵 mesh 对象
        depth_idx: 进深所在的局部轴下标
        sign: 前脸方向(-1 = 前脸在负半轴)
        boss_limit: 凸台与主体的分界面坐标(局部)
    返回值: int, 删掉的面数
    """
    mesh = pump.data
    if mesh.get("_pump_boss_stripped"):
        return 0
    coords = [vert.co.copy() for vert in mesh.vertices]
    kept = []
    removed = 0
    eps = 1e-6
    for poly in mesh.polygons:
        idx = tuple(poly.vertices)
        depths = [(coords[i][depth_idx] - boss_limit) * sign for i in idx]
        # 两个条件缺一不可:
        #   顶点全在凸台一侧(含分界面) —— 跨界的面属于主体;
        #   且**至少一个顶点严格越过分界面** —— 否则会把主体前脸(整片正好躺在分界面上,
        #   实测 214 面)一起删掉, 泵体正面就穿了个大洞.
        if all(d >= -eps for d in depths) and any(d > eps for d in depths):
            removed += 1
        else:
            kept.append(idx)
    if not removed:
        return 0
    mesh.clear_geometry()
    mesh.from_pydata([tuple(c) for c in coords], [], kept)
    mesh.update()
    mesh["_pump_boss_stripped"] = True
    return removed


def _attach_pump_visual(obj, pump, material, local_location: Vector | None = None) -> None:
    """
    功能: 把风格化几何挂到泵**所在装配**并赋材质(顶点已写在泵局部坐标).

    ⚠ 不挂泵网格本体. 泵网格在 join_static_per_station / join_by_material 里会被
    bpy.ops.object.join() 删除(同材质多台时只留 objects[0]), 被删对象的子级会失去父级、
    matrix_world 退回 matrix_basis —— 2026-08 实测: 注射泵视窗-3/针筒-3 因此被传送到
    世界原点(merge-members.json 里 bbox center = [0,0,*]), 又被后续同材质组一并吸收,
    把 ST_PUMP/STATIC_MAT_GLASS_EEF2F5 的包围盒从 12mm 撑成 0.71m.
    改挂 pump.parent 后饰件与泵是兄弟, 泵被删也带不走它.

    顶点仍写在泵局部系, 故要补上泵自身的 basis. 全程不读 matrix_world, 因此不触发
    "新建对象须先 view_layer.update()" 那条约束.

    参数:
        obj: 新建对象
        pump: 泵 mesh 对象(仅用于取变换与父级, 不作为父级)
        material: bpy 材质
        local_location: 在泵局部系内的附加平移(可动件用; 静态件顶点已含位置, 传 None)
    返回值: None
    """
    obj.parent = pump.parent
    obj.matrix_parent_inverse = pump.matrix_parent_inverse.copy()
    basis = pump.matrix_basis.copy()
    if local_location is not None:
        basis = basis @ Matrix.Translation(local_location)
    obj.matrix_basis = basis
    if obj.type == "MESH":
        obj.data.materials.clear()
        obj.data.materials.append(material)


def _pump_placement_items(rig_map: dict) -> dict:
    """功能: 取 rig_map.pumps.items 里带 placement 的条目. 参数: rig_map. 返回值: {泵id: placement}"""
    out: dict = {}
    for item in ((rig_map or {}).get("pumps") or {}).get("items") or []:
        pid = str(item.get("id") or "").strip()
        if pid and isinstance(item.get("placement"), dict):
            out[pid] = item["placement"]
    return out


def _gltf_point_to_blender(values) -> Vector:
    """
    功能: glTF/场景系坐标(毫米) -> Blender 世界坐标(米).

    与 apply_station_alignment 的 to_blender 同一条换算((x,y,z)_gltf -> (x,-z,y)_blender,
    CLAUDE.md 第 10 条); 线性映射对点与增量同式, 这里给摆位的绝对位/平移量共用.

    参数: values 长度 3 的毫米坐标
    返回值: Vector(米)
    """
    gx, gy, gz = (float(value) / 1000.0 for value in values)
    return Vector((gx, -gz, gy))


def _world_bbox_center(obj) -> Vector:
    """功能: 一个对象自身包围盒的世界中心(偏航枢轴用). 参数: obj mesh 对象. 返回值: Vector"""
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    lo = Vector((min(c[i] for c in corners) for i in range(3)))
    hi = Vector((max(c[i] for c in corners) for i in range(3)))
    return (lo + hi) / 2.0


def build_pump_visuals(materials_cfg: dict, movable: bool = False, rig_map: dict | None = None) -> dict:
    """
    功能: 把注射泵占位方壳重建成 SY-03B 外形(黑机身前盖 + 竖窗丝杆 + 朝前阀头 +
          薄壁玻璃针筒), full 阶段另拆出可动柱塞组、筒内液柱与阀头指针盘.

    时序不变量: 必须在 assign_materials 与各 build_* 之后、part_groups/part_overrides/
    join 之前调用 —— 分支期新建的几何拿不到 assign_materials 的材质(须在此自建), 且创建于
    prune/名字规则之后, 不会被删减规则误伤. 又必须排在 build_axis_carriages 之后, 才能
    靠 CARRIAGE 祖先认出骑在 6X 轴上的那台上样泵.

    静态饰件挂 pump.parent(与泵是兄弟), 不挂泵本体 —— 理由见 _attach_pump_visual.
    可动件命名落在 join_static_per_station 的保护前缀里(ACTUATOR_ / LIQUID), 因此
    **不需要**改那份清单; 但 minimal 阶段的 join_by_material 完全没有保护判定, 故
    可动件只在 full 阶段建(由 movable 控制).

    参数:
        materials_cfg: materials.yaml 全量配置(跨段按名检索各配方)
        movable: 是否生成可动柱塞组与液柱(仅 full 阶段为 True)
        rig_map: rig_map.yaml 内容; 只用来取每台泵的阀头通道数(T-04→4 / T-06→6),
                 决定正面画几个端口. 取不到就按 4 个画.
    返回值: dict, 生成统计与每台泵的最终节点名(供 gen_twin_manifest 读, 不靠猜)
    """
    layout = _derive_pump_layout(PUMP_LAYOUT_MM)
    # 阀头通道数: 从 valve 型号里取尾数(T-04→4, T-06→6). 只影响正面画几个端口,
    # 旋转角度由前端按 manifest 的 valvePorts 算, 两处同源于 rig_map.
    valve_ports: dict = {}
    for item in ((rig_map or {}).get("pumps") or {}).get("items") or []:
        match = re.search(r"(\d+)\s*$", str(item.get("valve") or ""))
        if item.get("id") and match:
            valve_ports[str(item["id"])] = max(2, int(match.group(1)))
    patterns = compile_patterns([layout["pattern"]])
    # 只认占位实体, 排除本函数自己造的饰件(名字同样以"注射泵"开头) —— 防二次调用叠加
    pumps = [
        obj for obj in mesh_objects()
        if matches_any(obj.name, patterns) and not obj.get("_pump_visual")
    ]
    if not pumps:
        log("注射泵风格化: 未找到目标, 跳过")
        return {"skipped": "no_match"}
    if movable and not any(obj.name.startswith("ST_") for obj in bpy.data.objects):
        raise SystemExit(
            "注射泵风格化: movable=True 但场景里没有 ST_* 工位根 —— 可动件只能在 full 阶段建, "
            "minimal 的 join_by_material 没有保护判定会把它们并掉"
        )

    axis = PUMP_FRONT_AXIS.strip().upper()
    if axis not in ("-Y", "+Y", "-X", "+X"):
        raise SystemExit(f"PUMP_FRONT_AXIS 非法: {PUMP_FRONT_AXIS}")
    valve_at = PUMP_VALVE_AT.strip().lower()
    if valve_at not in ("bottom", "top"):
        raise SystemExit(f"PUMP_VALVE_AT 非法: {PUMP_VALVE_AT}(只能是 bottom / top)")
    sign = -1.0 if axis[0] == "-" else 1.0
    depth_idx = 0 if axis[1] == "X" else 1
    width_idx = 1 - depth_idx
    axis_w = "X" if width_idx == 0 else "Y"
    axis_d = "X" if depth_idx == 0 else "Y"
    # up = +1: 阀头在下, 柱塞上行吸液, 液柱自底向上涨(本机实测). up = -1 则整套布局镜像.
    up = 1.0 if valve_at == "bottom" else -1.0
    # depth_dir: 局部进深轴上"由前脸朝机体内"的正负号. P() 里 d 增大即朝内, 但
    # _PumpPart.cyl(anchor="base") 恒沿局部轴正向长, 所以朝前/朝内的件要乘它.
    depth_dir = -sign

    # --- 材质: 跨段按名检索配方, 建"类名_颜色"实例 -------------------------------
    # 裸名共享实例: functional_overrides 段由 assign_materials eager 建过, 必须同名复用,
    # 否则会多出一份同色材质, 既多一个绘制批次, 前端按名找材质也会落空.
    bare_name_rules = {"MAT_POWDER_BUCKET", "MAT_LIQUID"}
    drop_keys = ("patterns", "parts", "cad_materials", "force_color", "native_materials")

    def find_recipe(rule_name: str) -> dict:
        """功能: 跨段按名检索材质配方. 参数: rule_name. 返回值: dict(已剔除非材质字段)"""
        for section in (materials_cfg or {}).values():
            if not isinstance(section, list):
                continue
            for item in section:
                if isinstance(item, dict) and item.get("name") == rule_name:
                    return {k: v for k, v in item.items() if k not in drop_keys}
        log(f"注射泵风格化: materials.yaml 里找不到配方 {rule_name}, 用兜底灰")
        return {"base_color": "#9aa0a6", "roughness": 0.5, "metalness": 0.0}

    materials: dict = {}
    for key, (rule_name, override_hex) in layout["rules"].items():
        if key.startswith("led_"):
            # 指示灯是本函数自建类, materials.yaml 里本来就没有, 不必去检索(也免得刷警告)
            spec = dict(layout["led_emission"])
            spec["base_color"] = override_hex
            spec["emission"] = override_hex
        else:
            spec = find_recipe(rule_name)
            if override_hex:
                spec["base_color"] = override_hex
        if rule_name in bare_name_rules:
            spec["name"] = rule_name
        else:
            hexcode = str(spec.get("base_color", "#9aa0a6")).lstrip("#").upper()
            spec["name"] = f"{rule_name}_{hexcode}"
        materials[key] = build_material(spec)

    # --- 稳定编号: 按几何键排序, 不用 Blender 的去重后缀 -------------------------
    # obj.name 是 注射泵-1 / .001 / .002, 顺序取决于导入次序, CAD 重导后可能翻 —— 而
    # 可动件名字是 manifest 绑定契约, 不能建在这上面. 改用世界包围盒中心这个几何键,
    # 并把最终名写进报告让 manifest 去读.
    bpy.context.view_layer.update()   # 下面要读 matrix_world(硬约束 9)

    def world_key(obj) -> tuple:
        """功能: 排序用的几何键. 参数: obj. 返回值: tuple"""
        loc = obj.matrix_world.translation
        return (round(loc.y, 4), round(loc.x, 4), round(loc.z, 4))

    def on_carriage(obj) -> bool:
        """功能: 是否骑在某根运动轴的滑车上(上样泵). 参数: obj. 返回值: bool"""
        node = obj.parent
        while node is not None:
            if node.name.startswith("CARRIAGE"):
                return True
            node = node.parent
        return False

    riding = sorted((p for p in pumps if on_carriage(p)), key=world_key)
    fixed = sorted((p for p in pumps if not on_carriage(p)), key=world_key)
    pump_ids = {}
    for i, obj in enumerate(riding, 1):
        pump_ids[obj.name] = "SMP" if len(riding) == 1 else f"SMP{i}"
    for i, obj in enumerate(fixed, 1):
        pump_ids[obj.name] = f"DEV{i}"
    ordered = fixed + riding

    # --- 无 CAD 泵体的泵(收集泵): 按名义尺寸合成占位, 走同一条风格化路径 -------
    # rig_map:pumps 注释里写明的翻开路径就是这条: "给它一个 build_pump_visuals 认得的
    # id". 合成体是与 CAD 占位方壳同构的名义尺寸盒(±5% 校验天然通过), 前脸凸台没有,
    # _strip_pump_boss 只会削掉它的前脸面(由黑色前盖补上), 与 CAD 占位的最终形态一致.
    # 只在 full(movable=True)合成: raw/minimal 没有 ST_* 工位根可挂, 也不喂孪生页.
    synthesized: list[dict] = []
    if movable:
        declared_items = {
            str(item.get("id") or "").strip(): item
            for item in ((rig_map or {}).get("pumps") or {}).get("items") or []
        }
        for pid, item in declared_items.items():
            if not pid or not item.get("rigged") or pid in pump_ids.values():
                continue
            placement = item.get("placement") if isinstance(item.get("placement"), dict) else {}
            world_mm = placement.get("world_mm")
            if not world_mm:
                # rigged 却既无 CAD 泵体又无落位声明 —— 造不出来, 必须喊出来而不是静默少一台
                raise SystemExit(
                    f"注射泵合成: {pid} 在 rig_map 标了 rigged 但场景里没有它的占位体, "
                    "且 placement.world_mm 未声明 —— 无 CAD 泵体的泵必须给绝对落位"
                )
            station = str(item.get("station") or "")
            st_root = bpy.data.objects.get(f"ST_{station}")
            if st_root is None:
                raise SystemExit(f"注射泵合成: {pid} 声明挂 ST_{station}, 场景里没有这个工位根")
            # 形状与 CAD 占位体**同构**: 主体盒(前脸在 cover_d1 分界面上) + 前凸台
            # (35×230×cover_d1, CAD 对注射器总成的方块示意)。这样 _strip_pump_boss 的
            # 行为与 CAD 件逐位一致 —— 凸台前脸/侧壁被削、凸台背面(躺在分界面上)与主体
            # 前脸保留, 风格化后不露内腔。单一整箱是踩过的坑: 整个前脸都在分界面之前,
            # 会被一并削掉, 从窗口直接看穿机体。
            d_half = PUMP_NOMINAL_MM["d"] / 2000.0
            boss_t = layout["cover_d1"] / 1000.0  # 凸台深度 = 到前盖背面的分界

            def co_at(t: float) -> float:
                """功能: 自前脸向内 t 米 -> 进深轴局部坐标(centered 盒). 参数: t. 返回值: float"""
                return sign * (d_half - t)

            def cuboid(verts: list, faces: list, u_half: float, t0: float, t1: float, h_half: float) -> None:
                """功能: 往顶点/面表里追加一个(宽半径, 进深区间, 高半径)长方体. 返回值: None"""
                base = len(verts)
                for su in (-1, 1):
                    for t in (t0, t1):
                        for sh in (-1, 1):
                            vec = [0.0, 0.0, sh * h_half]
                            vec[width_idx] = su * u_half
                            vec[depth_idx] = co_at(t)
                            verts.append(tuple(vec))
                faces.extend([
                    (base + 0, base + 1, base + 3, base + 2), (base + 4, base + 6, base + 7, base + 5),
                    (base + 0, base + 4, base + 5, base + 1), (base + 2, base + 3, base + 7, base + 6),
                    (base + 0, base + 2, base + 6, base + 4), (base + 1, base + 5, base + 7, base + 3),
                ])

            verts: list = []
            faces: list = []
            cuboid(verts, faces, PUMP_NOMINAL_MM["w"] / 2000.0, boss_t, 2.0 * d_half,
                   PUMP_NOMINAL_MM["h"] / 2000.0)   # 主体
            cuboid(verts, faces, 0.0175, 0.0, boss_t, 0.115)   # 凸台(35×230, 实测同 CAD)
            mesh = bpy.data.meshes.new(f"注射泵占位-{pid}")
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            asm = bpy.data.objects.new(f"注射泵总装-{pid}", None)
            body = bpy.data.objects.new(f"注射泵-{pid}", mesh)
            bpy.context.scene.collection.objects.link(asm)
            bpy.context.scene.collection.objects.link(body)
            bpy.context.view_layer.update()
            asm.parent = st_root
            asm.matrix_world = Matrix.Translation(_gltf_point_to_blender(world_mm))
            body.parent = asm
            body.matrix_parent_inverse = Matrix.Identity(4)
            # 机体用前盖同款配方: 官方外形就是一体的黑机身(正面即机体本色)
            body.data.materials.append(materials["shell"])
            pump_ids[body.name] = pid
            ordered.append(body)
            synthesized.append({"id": pid, "assembly": asm.name, "body": body.name,
                                "world_mm": [float(v) for v in world_mm]})
            log(f"注射泵合成: {pid} 无 CAD 泵体, 已按名义尺寸在 ST_{station} 下合成占位并入风格化")

    created: list[str] = []
    instances: list[dict] = []
    # 凸台要等**所有**泵都量完包围盒之后再删: 三台泵可能共用同一份 mesh 数据, 先删一台
    # 会把后面几台的包围盒缩掉 30mm, 整套 d 分数随之全错.
    strip_jobs: list[tuple] = []

    for pump in ordered:
        pid = pump_ids[pump.name]
        coords = [vert.co for vert in pump.data.vertices]
        if not coords:
            log(f"注射泵风格化: {pump.name} 无顶点, 跳过")
            continue
        lmin = Vector(tuple(min(co[i] for co in coords) for i in range(3)))
        lmax = Vector(tuple(max(co[i] for co in coords) for i in range(3)))
        size = lmax - lmin
        if min(size) <= 1e-6:
            log(f"注射泵风格化: {pump.name} 包围盒退化 {tuple(size)}, 跳过")
            continue
        center = (lmin + lmax) / 2.0
        front = lmin[depth_idx] if sign < 0 else lmax[depth_idx]

        # mm → 局部单位. 三轴必须同比例: 对不上说明 CAD 换了占位件, 此时宁可炸也不要
        # 画出一台被拉伸的泵(下面所有尺寸都是按 60/144.5/253.3 这套标称值折算的).
        scale = size.z / PUMP_NOMINAL_MM["h"]
        for label, actual, nominal in (
            ("宽", size[width_idx], PUMP_NOMINAL_MM["w"]),
            ("进深", size[depth_idx], PUMP_NOMINAL_MM["d"]),
        ):
            if abs(actual / (nominal * scale) - 1.0) > 0.05:
                raise SystemExit(
                    f"注射泵风格化: {pump.name} 的{label}实测 {actual / scale:.1f}mm, "
                    f"与官方标称 {nominal}mm 差超 5% —— CAD 占位件换过了, 请重新核对 "
                    f"PUMP_NOMINAL_MM 与 PUMP_LAYOUT_MM"
                )

        def P(u: float, d: float, h: float) -> Vector:
            """
            功能: 把 (沿宽偏移, 自前脸向内, 沿高偏移) 三个毫米量换成泵局部坐标.
            参数: u 沿宽(0=中线); d 自最前面向内(0=前脸, 负=伸到前脸之前); h 沿高(0=泵中心)
            返回值: Vector
            """
            vec = Vector((0.0, 0.0, 0.0))
            vec[width_idx] = center[width_idx] + u * scale
            vec[depth_idx] = front - sign * d * scale
            vec[2] = center.z + up * h * scale
            return vec

        strip_jobs.append((pump, front - sign * layout["cover_d1"] * scale))
        syr_d = layout["syringe_d"]
        vface = layout["valve_face_d"]
        # 平口高度: 阀盘被弦切平的那一面, 针筒停在它上方 barrel_gap 处(见 barrel_gap 注释),
        # 缝由滚花螺母骑过去盖住.
        flat_h = layout["valve_h"] + layout["valve_chord"]
        barrel_h0 = flat_h + layout["barrel_gap"]
        barrel_top = barrel_h0 + layout["barrel_len"]
        liquid_h0 = barrel_h0 + layout["liquid_gap"]
        rod_h0 = liquid_h0 + layout["plunger_len"]
        clamp_h0 = barrel_top + layout["collar_hi_len"]
        ports = int(valve_ports.get(pid, 4))
        # 端口角度: 全部落在下半圈的 port_arc 里均布(0° = +u, 90° = +h).
        # 首尾降序 ⇒ 1 号口在右(335°)、末号口在左(205°), 用户 2026-08-05 按实物指认.
        arc0, arc1 = layout["port_arc"]
        port_angles = ([(arc0 + arc1) / 2.0] if ports < 2 else
                       [arc0 + (arc1 - arc0) * k / (ports - 1) for k in range(ports)])

        def emit(key: str, name: str, part: _PumpPart) -> None:
            """功能: 把攒好的一组几何落成对象并挂到泵所在装配. 参数: key 材质键; name; part. 返回值: None"""
            if part.empty:
                return
            obj = part.build(name)
            obj["_pump_visual"] = True
            _attach_pump_visual(obj, pump, materials[key])
            created.append(obj.name)

        def face_at(radius: float, angle_deg: float) -> tuple:
            """功能: 阀头正面上绕轴心的径向阵列点. 参数: radius 分布半径; angle_deg. 返回值: (u, h)"""
            rad = math.radians(angle_deg)
            return (radius * math.cos(rad), layout["valve_h"] + radius * math.sin(rad))

        # --- 黑色前盖: 四条边框补上删凸台后留下的 35×230 洞, 中间留竖窗 ---
        # 上一版这里是一块 55×245、metalness 0.9 的镜面铝板, 把整台黑泵盖成了银板机 ——
        # 那是"完全不像真机"的最大单项来源. 现在正面就是机体本色, 唯一的银件是窗内丝杆.
        cw, ch = layout["cover_w"], layout["cover_h"]
        cd0, cd1 = layout["cover_d0"], layout["cover_d1"]
        ww, wh0, wh1 = layout["win_w"], layout["win_h0"], layout["win_h1"]
        wall = layout["win_wall"]
        fd0, fd1 = layout["win_floor_d0"], layout["win_floor_d1"]
        shell = _PumpPart()
        shell.box(P(-cw, cd0, -ch), P(-ww, cd1, ch))          # 左条
        shell.box(P(ww, cd0, -ch), P(cw, cd1, ch))            # 右条
        shell.box(P(-ww, cd0, -ch), P(ww, cd1, wh0))          # 下条
        shell.box(P(-ww, cd0, wh1), P(ww, cd1, ch))           # 上条
        # 窗腔四壁 + 窗底板: 机体是个闭合盒, 删掉凸台后从窗口直接看进去只会撞上背面的
        # **背面**(被背面剔除), 于是穿帮成一个洞. 加了这一圈内衬才读成"凹进去的窗".
        shell.box(P(-ww - wall, cd1, wh0), P(-ww, fd1, wh1))
        shell.box(P(ww, cd1, wh0), P(ww + wall, fd1, wh1))
        shell.box(P(-ww - wall, cd1, wh0 - wall), P(ww + wall, fd1, wh0))
        shell.box(P(-ww - wall, cd1, wh1), P(ww + wall, fd1, wh1 + wall))
        shell.box(P(-ww - wall, fd0, wh0 - wall), P(ww + wall, fd1, wh1 + wall))
        # 侧面散热槽与正面 6-M4 沉孔: **刻意不建**.
        #
        # 两者在真机上都是**凹**特征, 而累积器没有布尔运算, 减不出凹坑 —— 只能拿一个盒/盘
        # 去贴, 那样它的外表面必然与机体表面共面, 换来一片 z-fighting. 上一版绕开共面的办法
        # 是"凸出去一点": 散热槽凸 0.4mm(0.32 像素)、沉孔做成 4 颗凸起的钉(3.5 像素), 结果
        # 前者连同 4.7% 的色差一起读不出来(等于没建), 后者变成一圈噪点.
        #
        # 整机取景只有 0.8 px/mm, 这两类特征本来就在可读阈值(约 10mm)以下. 与其用共面换
        # 一个看不见的东西, 不如让正面保持干净的机体本色 —— 与产品图上的观感也一致.
        # 背面航插: 收进 0.5mm, 免与机体背面共面闪烁
        shell.box(P(-layout["conn_w"], layout["conn_d0"], layout["conn_h0"]),
                  P(layout["conn_w"], PUMP_NOMINAL_MM["d"] - 0.5, layout["conn_h1"]))
        emit("shell", f"注射泵壳饰-{pid}", shell)

        # --- 窗内丝杆: 必须覆盖整个 60mm 行程 ---
        # 上一版丝杆只有 22mm, 且区间 [98,120] 与滑车行程 [13.85, 91.85] **零重叠**,
        # 传动上滑车骑在空气上; 而且它整段埋在实心机体里, 一个像素都看不到.
        # 光杆芯是静态的(转起来也看不出), 只有带螺纹的那层才做成可转件 —— 见下面的
        # ACTUATOR_PUMP_LEAD_*. 芯子留在静态组里能跟机身并进同一个 STATIC 块, 省一个图元.
        rail = _PumpPart()
        rail.cyl(P(0.0, layout["lead_d"], layout["lead_h0"]), layout["lead_r"] * scale,
                 up * (layout["lead_h1"] - layout["lead_h0"]) * scale,
                 segments=12, anchor="base")
        emit("rail", f"注射泵丝杆芯-{pid}", rail)

        # --- 阀头: Ø40 × 15 的米白 PEEK 盘, 接针筒那一侧切成平口 ---
        # 上一版建成 Ø28 × 35 的整圆柱 —— 直径小了 12mm、厚了一倍多, 而且没有平口.
        # 官方正面尺寸图上阀头就是个 ≈Ø40 的大圆(比 Ø28 针筒粗一圈), 底边截平.
        #
        # chord_dir 必须按轴向给并乘 up(见 dcyl 的注释): _axis_place 是坐标轮换,
        # "截面里哪个分量是高度"随进深轴而变; 乘 up 才能保证平口恒在**朝针筒**那一侧.
        chord_dir = (0.0, up) if axis_d == "X" else (up, 0.0)
        valve = _PumpPart()
        valve.dcyl(P(0.0, vface, layout["valve_h"]), layout["valve_r"] * scale,
                   depth_dir * layout["valve_len"] * scale,
                   layout["valve_chord"] * scale, axis=axis_d, segments=32,
                   anchor="base", chord_dir=chord_dir)
        # 正面凸台(官方正面图上的内圈): 后端往盘里塞 0.5mm, 免与盘前脸共面
        valve.dcyl(P(0.0, vface + 0.5, layout["valve_h"]), layout["valve_hub_r"] * scale,
                   -depth_dir * (layout["valve_hub_t"] + 0.5) * scale,
                   layout["valve_chord"] * scale, axis=axis_d, segments=32,
                   anchor="base", chord_dir=chord_dir)
        emit("valve", f"注射泵阀头-{pid}", valve)

        # --- 阀座 + 端口接头(黑): 都走机体那份配方, 合并后不多占一个图元 ---
        # 阀座补上阀盘后端面(d=20.2)到机体前脸(d=30)之间那截空档; 一路扎到 d=32 埋进机体,
        # 后端盖就不会与机体前脸共面.
        # 起点再往盘里塞 0.5mm: 与盘的后端盖精确对齐的话两片完全共面(朝向相反, 剔除能救,
        # 但双面材质就救不了了), 塞进去就彻底没有这回事.
        boss_d0 = vface + layout["valve_len"] - 0.5
        fitting = _PumpPart()
        fitting.cyl(P(0.0, boss_d0, layout["valve_h"]), layout["valve_boss_r"] * scale,
                    depth_dir * (layout["valve_boss_d1"] - boss_d0) * scale,
                    axis=axis_d, segments=16, anchor="base")
        emit("shell", f"注射泵阀座-{pid}", fitting)

        # --- 黄铜滚花鲁尔接头 ×N: **径向朝外**沿下半圆周甩出 ---
        # 用户 2026-08-05 按实物指定: 不是深色短柱, 是图 2 真空阀上那种黄铜滚花鲁尔.
        # 三段(杆 / 滚花箍 / 头)的尺寸照 CAD 现成的 PTLC-03-031 折算, 见 PUMP_LAYOUT_MM.
        #
        # 全部用现成的 tube() 造: 它是平行输运帧扫掠、两端带封盖、天然支持任意方向 —— 径向
        # 的轴不落在任何坐标轴上, cyl 的坐标轮换用不了, 而 tube 正好不挑方向.
        # 滚花箍额外走 20 段并**关掉平滑**(smooth=False): Ø8 上 20 个棱 = 1.25mm 棱距,
        # 与真滚花同量级, 代价只有 20 个四边形.
        port_mid_d = vface + layout["valve_len"] / 2.0
        luer = _PumpPart()
        for angle in port_angles:
            def at(radius: float) -> Vector:
                """功能: 该端口方位上、给定半径处的阀面点. 参数: radius. 返回值: Vector"""
                u, h = face_at(radius, angle)
                return P(u, port_mid_d, h)
            luer.tube([at(layout["luer_stem_r0"]), at(layout["luer_stem_r1"])],
                      layout["luer_stem_r"] * scale, segments=8)
            luer.tube([at(layout["luer_stem_r1"]), at(layout["luer_knurl_r1"])],
                      layout["luer_knurl_r"] * scale, segments=layout["luer_knurl_seg"],
                      smooth=False)
            luer.tube([at(layout["luer_knurl_r1"] - 0.4), at(layout["luer_nose_r1"])],
                      layout["luer_nose_r"] * scale, segments=12)
        emit("luer", f"注射泵鲁尔接头-{pid}", luer)

        # --- 三颗内六角螺钉(钢): 照片是三角形排布 ---
        # 尾部埋进盘里 0.8mm、头部凸出 2.0: 两个端盖落在 d=6.0 / 3.4, 刻意避开阀盘前脸
        # (5.2)与凸台的前/后脸(3.2 / 5.7) —— 螺钉先前正好与凸台共用这两个平面, 检测器一次
        # 报出 24 对同向共面.
        screws = _PumpPart()
        for angle in layout["screw_angles"]:
            su, sh = face_at(layout["screw_ring_r"], angle)
            screws.cyl(P(su, vface + 0.8, sh), layout["screw_r"] * scale,
                       -depth_dir * (layout["screw_len"] + 0.6) * scale,
                       axis=axis_d, segments=8, anchor="base")
        emit("slider", f"注射泵阀螺钉-{pid}", screws)

        # --- 玻璃针筒: 薄壁管, 不是实心柱 ---
        # 实心柱没有内表面, 少了玻璃最重要的视觉线索(内外两层壁各自的高光边), 上一版
        # 整根针筒在画面里不存在, 只剩罩在里面的柱塞杆与刻度盘悬空.
        glass = _PumpPart()
        glass.pipe(P(0.0, syr_d, barrel_h0), layout["barrel_ro"] * scale,
                   layout["barrel_ri"] * scale, up * layout["barrel_len"] * scale,
                   segments=24, anchor="base")
        emit("glass", f"注射泵针筒-{pid}", glass)

        # --- 上下压环: 铝的合理去处(不再是一整块 245mm 的面板) ---
        # 两个环都**骑过筒口 1mm**而不是与筒端面对齐: 对齐的话环的端面与筒的环形端盖
        # 完全共面且朝向相同(实测两处), 是标准的 z-fighting 配方. 骑过去既避开共面,
        # 也更像真的卡箍.
        ferrule = _PumpPart()
        # 下压环 = 照片里那颗压紧针筒的银色滚花螺母, **坐在阀头平口上**(不是坐在筒底).
        # 往下沉 1mm 骑进平口: 底面与平口面对齐的话两片完全共面且朝向相同, 是标准的
        # z-fighting 配方.
        ferrule.disc_ring(P(0.0, syr_d, flat_h - 1.0 + layout["collar_lo_len"] / 2.0),
                          layout["collar_lo_r"] * scale, layout["barrel_ri"] * scale,
                          layout["collar_lo_len"] * scale, segments=24)
        ferrule.disc_ring(P(0.0, syr_d, barrel_top + 1.0 - layout["collar_hi_len"] / 2.0),
                          layout["collar_hi_r"] * scale, layout["rod_r"] * scale,
                          layout["collar_hi_len"] * scale, segments=24)
        emit("ferrule", f"注射泵压环-{pid}", ferrule)

        # --- 三颗指示灯(绿/绿/红): **侧面横排**, 红灯在最右 ---
        # 灯柱沿宽度轴戳出侧面; 尾部往机体里塞 0.2mm, 免得后端面与侧面正好共面.
        led_u = layout["led_side"] * (PUMP_NOMINAL_MM["w"] / 2.0
                                      + layout["led_len"] / 2.0 - 0.2)
        for slot, key in ((0, "led_green"), (1, "led_green"), (2, "led_red")):
            led = _PumpPart()
            led.cyl(P(led_u, layout["led_d0"] + slot * layout["led_step"], layout["led_h"]),
                    layout["led_r"] * scale, layout["led_len"] * scale,
                    axis=axis_w, segments=12)
            suffix = "绿" if key == "led_green" else "红"
            emit(key, f"注射泵指示灯{suffix}-{pid}-{slot + 1}", led)

        # 两根蓝色软管 2026-08-05 按用户指示删除 —— 现在每个口上都是真的黄铜鲁尔接头,
        # 挂两根到别处去的管子反而抢戏. 材质规则 "tube" 也一并摘了(留着会白建一份
        # MAT_SILICONE_4A7FD0 实例). MAT_SILICONE 裸名仍被 material_semantics 用着, 没动.

        record = {
            "id": pid,
            "pump": pump.name,
            "parent": pump.parent.name if pump.parent else None,
            "on_carriage": on_carriage(pump),
            "stroke_mm": layout["stroke"],
            "syringe_bore_mm": layout["barrel_ri"] * 2.0,
            "valve_at": valve_at,
            "valve_ports": ports,
            # 端口不是 360° 均布(全挤在下半圈), 前端不能再拿 (port-1)/N 算指针角, 否则
            # 会指向没有端口的方向. 把几何上真正建了接头的那些角一路带给 manifest.
            "valve_port_angles": [round(a, 3) for a in port_angles],
        }

        if movable:
            # --- 可动柱塞组: ACTUATOR_ 前缀已在 join_static_per_station 的保护清单里 ---
            plunger_origin = P(0.0, syr_d, liquid_h0)
            group = bpy.data.objects.new(f"ACTUATOR_PUMP_PLUNGER_{pid}", None)
            bpy.context.scene.collection.objects.link(group)
            group["_pump_visual"] = True
            group.empty_display_size = layout["plunger_r"] * scale
            _attach_pump_visual(group, pump, None, local_location=plunger_origin)

            def PR(u: float, d: float, h: float) -> Vector:
                """功能: 相对柱塞组原点的坐标(组内顶点写这个系, 组自身再被平移). 参数: 同 P. 返回值: Vector"""
                return P(u, d, h) - plunger_origin

            def attach_to_group(obj, parent_obj, key: str) -> None:
                """功能: 把网格挂进可动组(变换恒等). 参数: obj; parent_obj 组; key 材质键. 返回值: None"""
                obj["_pump_visual"] = True
                obj.parent = parent_obj
                obj.matrix_parent_inverse = Matrix.Identity(4)
                obj.matrix_basis = Matrix.Identity(4)
                obj.data.materials.clear()
                obj.data.materials.append(materials[key])
                created.append(obj.name)

            plunger = _PumpPart()
            # 柱塞头下沉 0.2mm 进液柱, 杆再多插 1mm 进夹头: 两处原本严丝合缝地端面对端面,
            # 虽然朝向相反不至于闪, 但掠射角下容易露缝. 微量互穿正是真活塞密封的样子.
            plunger.cyl(PR(0.0, syr_d, liquid_h0 - 0.2), layout["plunger_r"] * scale,
                        up * (layout["plunger_len"] + 0.2) * scale, segments=16, anchor="base")
            plunger.cyl(PR(0.0, syr_d, rod_h0), layout["rod_r"] * scale,
                        up * (clamp_h0 - rod_h0 + 1.0) * scale, segments=12, anchor="base")
            attach_to_group(plunger.build(f"注射泵柱塞-{pid}"), group, "plunger")

            # 滑车前后各留 1mm 以上: 上一版它与竖槽盒的 d 区间**逐位相同**, 于是一块
            # 13×18mm 的矩形在整个行程里持续 z-fighting 抖动, 是画面上最刺眼的一处.
            slider = _PumpPart()
            slider.box(PR(-layout["clamp_w"], syr_d - 4.0, clamp_h0),
                       PR(layout["clamp_w"], layout["clamp_d1"], clamp_h0 + layout["clamp_len"]))
            slider.box(PR(-layout["slider_w"], layout["slider_d0"], clamp_h0),
                       PR(layout["slider_w"], layout["slider_d1"],
                          clamp_h0 + layout["slider_len"]))
            attach_to_group(slider.build(f"注射泵滑车-{pid}"), group, "slider")

            # --- 可转指示盘: 定子带端口不动, 转的是面心这块盘 ---
            # 真机 Runze 阀是定子带端口、转子在内部, 外面看不到整头旋转; 管线又零 UV
            # 画不了 1/2/3/4 编号. 所以转一个指针盘 —— 既表达"它在切液路", 又不伪造一个
            # 实际不存在的运动.
            # 基准是**凸台**前脸(不是阀盘前脸): 凸台已经往前顶了 2mm, 拿阀盘前脸起手的话
            # 指针盘整个埋在凸台里. 再往前挪 0.15mm, 免得后端面正好落在凸台前脸上(共面).
            hub_face = vface - layout["valve_hub_t"]
            rotor_origin = P(0.0, hub_face - layout["rotor_t"] - 0.15, layout["valve_h"])
            rotor_group = bpy.data.objects.new(f"ACTUATOR_PUMP_VALVE_{pid}", None)
            bpy.context.scene.collection.objects.link(rotor_group)
            rotor_group["_pump_visual"] = True
            rotor_group.empty_display_size = layout["rotor_r"] * scale
            _attach_pump_visual(rotor_group, pump, None, local_location=rotor_origin)

            # --- 可转丝杆螺纹: 沿螺旋线扫一根管 ---
            # 梯形丝杆导程 6mm、行程 60mm ⇒ 满行程 10 圈. 光杆芯已在静态组里, 这里只建
            # 螺纹那一层: 光面圆柱绕自身轴转在画面上完全看不出来, 螺旋线才是"它在转"的
            # 唯一可跟踪线索.
            # 原点放在丝杆轴线上(不是 P(0,·,·) 的泵中线), 这样绕局部 Z 转就是绕自身轴转.
            lead_origin = P(0.0, layout["lead_d"], layout["lead_h0"])
            lead_group = bpy.data.objects.new(f"ACTUATOR_PUMP_LEAD_{pid}", None)
            bpy.context.scene.collection.objects.link(lead_group)
            lead_group["_pump_visual"] = True
            lead_group.empty_display_size = layout["lead_r"] * scale
            _attach_pump_visual(lead_group, pump, None, local_location=lead_origin)

            lead_len = layout["lead_h1"] - layout["lead_h0"]
            turns = lead_len / layout["lead_pitch"]
            steps = max(8, int(round(turns * layout["lead_thread_steps"])))
            helix = []
            for k in range(steps + 1):
                ang = math.tau * turns * k / steps
                pt = Vector((0.0, 0.0, 0.0))
                pt[width_idx] = math.cos(ang) * layout["lead_thread_r"] * scale
                pt[depth_idx] = math.sin(ang) * layout["lead_thread_r"] * scale
                pt[2] = up * lead_len * k / steps * scale
                helix.append(pt)
            thread = _PumpPart()
            thread.tube(helix, layout["lead_thread_t"] * scale, segments=6)
            attach_to_group(thread.build(f"注射泵丝杆螺纹-{pid}"), lead_group, "rail")

            rotor = _PumpPart()
            rotor.cyl(Vector((0.0, 0.0, 0.0)), layout["rotor_r"] * scale,
                      depth_dir * layout["rotor_t"] * scale, axis=axis_d, segments=16,
                      anchor="base")
            # 指针: 自盘心朝 0° 方向伸出的一条窄凸台, 转到哪一口一目了然
            pin_lo = Vector((0.0, 0.0, 0.0))
            pin_hi = Vector((0.0, 0.0, 0.0))
            pin_lo[width_idx] = layout["pointer_r0"] * scale
            pin_hi[width_idx] = layout["pointer_r1"] * scale
            pin_lo[2] = -layout["pointer_w"] / 2.0 * scale
            pin_hi[2] = layout["pointer_w"] / 2.0 * scale
            pin_lo[depth_idx] = -depth_dir * 0.6 * scale
            pin_hi[depth_idx] = depth_dir * layout["rotor_t"] * scale
            rotor.box(pin_lo, pin_hi)
            attach_to_group(rotor.build(f"注射泵阀指针-{pid}"), rotor_group, "rotor")

            # --- 液柱: 原点在筒底, 前端只缩一个分量就是"从底往上涨" ---
            # ⚠ 材质必须不透明(MAT_LIQUID 锁死 alpha 1.0 且无 transmission). 玻璃针筒是
            # BLEND 队列、经 GLTFLoader 拿到 depthWrite=false; 液柱一旦也进透明队列, 两者
            # 只能按物体中心排序, 柱塞一走就翻面 —— 那正是 2026-08-03 "液体糊在缸外面"
            # 那条 bug 的同款拓扑, 只不过这次会糊在筒外面.
            liquid_origin = P(0.0, syr_d, liquid_h0)
            liquid_part = _PumpPart()
            liquid_part.cyl(Vector((0.0, 0.0, 0.0)), layout["liquid_r"] * scale,
                            up * layout["stroke"] * scale, segments=20, anchor="base")
            liquid = liquid_part.build(f"LIQUID_PUMP_{pid}")
            liquid["_pump_visual"] = True
            _attach_pump_visual(liquid, pump, materials["liquid"], local_location=liquid_origin)
            created.append(liquid.name)

            record.update({
                "plunger_node": group.name,
                "liquid_node": liquid.name,
                "valve_node": rotor_group.name,
                # 导出 GLB 走 export_yup: 局部 (x,y,z) → (x, z, -y), 故局部 +Z = glTF +Y
                "travel_axis_gltf": "+y" if up > 0 else "-y",
                "travel_m": round(layout["stroke"] * scale, 6),
                # 阀指针绕**进深轴**转. 轴的正负由"指针静止时朝 +宽、端口角 θ 的方向是
                # (宽: cosθ, 局部Z: up·sinθ)"倒推 —— 要让绕该轴转 θ 正好把指针送到 θ 号
                # 方向, 解出局部轴 = (up,0,0)(进深沿X) 或 (0,-up,0)(进深沿Y), 与前脸朝
                # 哪一侧(sign/depth_dir)无关. 再按 export_yup 的 (x,y,z)→(x,z,-y) 换算.
                #
                # ⚠ 2026-08-05 订正: 旧式子挂的是 depth_dir, 解出来正好差一个镜像 ——
                # 端口原本 360° 均布时看不出来(转到哪都压着一个口), 现在端口全挤在下半圈,
                # 转反了指针就会跑到上面的平口那侧去.
                "valve_axis_gltf": ("+x" if up > 0 else "-x") if depth_idx == 0
                                   else ("+z" if up > 0 else "-z"),
                # 丝杆绕**自身竖轴**转. 局部 +Z → glTF +Y(与柱塞行程轴同源的换算).
                # 转向由 up 定: 倒装时柱塞上行吸液, 丝杆随之正转.
                "lead_node": lead_group.name,
                "lead_axis_gltf": "+y" if up > 0 else "-y",
                # 导程 6mm、行程 60mm ⇒ 满行程 10 圈. 前端按 level × 该值 × 2π 写转角.
                "lead_turns_per_stroke": round(layout["stroke"] / layout["lead_pitch"], 6),
            })
        instances.append(record)

    stripped = sum(_strip_pump_boss(pump, depth_idx, sign, limit) for pump, limit in strip_jobs)

    # --- 摆位订正: 平移 + 竖轴偏航, 作用在泵所在**装配**上(占位体/CAD 玻璃件/全部
    # 饰件与可动组都是它的子级或共享其 basis 的兄弟, 天然随动) -----------------
    # 声明在 rig_map:pumps.items[].placement, 数值按实物照片目视对齐(2026-08-06 用户
    # 指认: 左二右一, 针筒朝外, 背朝墙)。轴系与 station_alignment 同约定(glTF 系)。
    # 偏航是唯一的旋转自由度: 泵是立式模块, 俯仰/横滚在物理上不成立。
    placement_report: list[dict] = []
    placements = _pump_placement_items(rig_map or {})
    # 只在 full(movable=True)摆位, 与合成同一道闸: raw/minimal 没有 CARRIAGE 层级,
    # 骑轴判定失效会把三台 CAD 泵全编成 DEVn —— DEV2 的摆位会误套到上样泵头上
    # (2026-08-06 raw 链实测, 由下面的编号不变量门禁拦下)。raw 的本职就是保留 CAD
    # 原貌(与 strip_connector 只在正式链做同理), 位置真源在 full 派生的 GLB 里。
    if placements and not movable:
        log(f"注射泵摆位: 本阶段保留 CAD 原貌, {len(placements)} 条 placement 跳过(只在 full 应用)")
        placements = {}
    if placements:
        bpy.context.view_layer.update()
        by_id = {pump_ids[obj.name]: obj for obj in ordered if obj.name in pump_ids}
        for pid, placement in placements.items():
            obj = by_id.get(pid)
            if obj is None:
                if not movable and placement.get("world_mm"):
                    # 合成泵只在 full 造(见上), raw/minimal 轮到摆位时它本来就不在场
                    log(f"注射泵摆位: {pid} 是合成泵, 本阶段未生成, 跳过")
                    continue
                raise SystemExit(f"注射泵摆位: rig_map 给 {pid} 声明了 placement, 但本轮没有这台泵")
            target = obj.parent
            if target is None or target.name.startswith("CARRIAGE"):
                raise SystemExit(
                    f"注射泵摆位: {pid} 的父级是 {getattr(target, 'name', None)} —— "
                    "骑轴的泵(上样泵)不允许摆位, 它的位置由滑车与轴标定定"
                )
            yaw_deg = float(placement.get("yaw_deg") or 0.0)
            if abs(yaw_deg) > 1e-9:
                center = _world_bbox_center(obj)
                pivot = (Matrix.Translation(center)
                         @ Matrix.Rotation(math.radians(yaw_deg), 4, "Z")
                         @ Matrix.Translation(-center))
                target.matrix_world = pivot @ target.matrix_world
            delta_mm = placement.get("translate_mm")
            if delta_mm:
                target.matrix_world = (Matrix.Translation(_gltf_point_to_blender(delta_mm))
                                       @ target.matrix_world)
            bpy.context.view_layer.update()
            placement_report.append({
                "id": pid,
                "assembly": target.name,
                "yaw_deg": yaw_deg,
                "translate_mm": [float(v) for v in (delta_mm or [0, 0, 0])],
                "center_world_m": [round(v, 4) for v in _world_bbox_center(obj)],
            })
            log(f"注射泵摆位: {pid} 经 {target.name} 偏航 {yaw_deg:+.0f}° 平移 "
                f"{[round(float(v)) for v in (delta_mm or [0, 0, 0])]} mm(glTF)")

        # DEV 编号不变量: DEV1 = 世界 Y 更小的那台 = 缸 1-4 侧(与 tanks.first_rack 的
        # y_negative 约定绑死, 见 rig_map:pumps 头注)。摆位把 Y 序挪反的话, 缸组归属
        # 显示会静默错 —— 宁可在这里炸。
        devs = {pid: obj for pid, obj in by_id.items() if pid.startswith("DEV")}
        if len(devs) >= 2:
            bpy.context.view_layer.update()
            by_y = sorted(devs, key=lambda p: _world_bbox_center(devs[p]).y)
            by_no = sorted(devs, key=lambda p: int(p[3:] or "0"))
            if by_y != by_no:
                raise SystemExit(
                    f"注射泵摆位后 DEV 编号不变量被破坏: 世界 Y 升序是 {by_y}, 编号序是 {by_no} —— "
                    "要么调 placement 让 DEV1 留在 Y 小侧, 要么按 rig_map 头注改显式指认(别挪约定)"
                )

    # --- 合成泵的安装支架: 收集泵与展缸泵是同款模块, 实机同样立在 PTLC-02-022
    # 安装板上(用户 2026-08-07 指认: 与左边两台一模一样, 只差那 4 个电磁阀 —— 电磁阀
    # 本就不进合成清单)。CAD 没画这块板, 故从 DEV1 装配快照克隆一份, 按"前脸对转
    # 180°"(DEV 前脸 +X, COL 前脸 -X, 对映安装)绕 DEV1 泵体中心转半圈再平移到合成泵
    # 身侧 —— 支架相对泵身的偏距/贴地高度原样继承, 不引入任何手调数字。
    if movable and synthesized:
        bpy.context.view_layer.update()
        id_to_obj = {pump_ids[obj.name]: obj for obj in ordered if obj.name in pump_ids}
        ref_body = id_to_obj.get("DEV1")
        ref_bracket = None
        if ref_body is not None and ref_body.parent is not None:
            ref_bracket = next((child for child in ref_body.parent.children
                                if "安装板" in child.name and child.type == "MESH"), None)
        if ref_bracket is None:
            raise SystemExit(
                "注射泵支架克隆: DEV1 装配里找不到名字含'安装板'的 MESH —— CAD 重导后"
                "件名变了就把这里的匹配词一并改掉, 别让收集泵悄悄丢支架"
            )
        ref_center = _world_bbox_center(ref_body)
        flip = (Matrix.Translation(ref_center)
                @ Matrix.Rotation(math.pi, 4, "Z")
                @ Matrix.Translation(-ref_center))
        for entry in synthesized:
            asm = bpy.data.objects.get(entry["assembly"])
            body = bpy.data.objects.get(entry["body"])
            if asm is None or body is None:
                continue
            clone = ref_bracket.copy()
            clone.data = ref_bracket.data.copy()
            base = re.sub(r"-\d+(?:\.\d+)*$", "", ref_bracket.name)
            clone.name = f"{base}-{entry['id']}"
            clone.data.name = clone.name
            bpy.context.scene.collection.objects.link(clone)
            clone.parent = asm
            clone.matrix_parent_inverse = Matrix.Identity(4)
            clone.matrix_world = (Matrix.Translation(_world_bbox_center(body) - ref_center)
                                  @ flip @ ref_bracket.matrix_world)
            bpy.context.view_layer.update()
            # 贴地校验: 支架底面必须与克隆源同高(柜底), 否则就是 world_mm 的高度没按
            # "泵身骑板离地 90mm"(y=-581, 与 DEV 同高)配 —— 宁可在这里炸
            lo_ref = min((ref_bracket.matrix_world @ Vector(v)).z for v in ref_bracket.bound_box)
            lo_new = min((clone.matrix_world @ Vector(v)).z for v in clone.bound_box)
            if abs(lo_new - lo_ref) > 0.003:
                raise SystemExit(
                    f"注射泵支架克隆: {clone.name} 底面 z={lo_new:.4f} 与克隆源 {lo_ref:.4f} 不齐 —— "
                    f"检查 {entry['id']} 的 placement.world_mm 高度是否取 -581(泵身骑板, 与 DEV 同高)"
                )
            entry["bracket"] = clone.name
            created.append(clone.name)
            log(f"注射泵支架克隆: {entry['id']} ← {ref_bracket.name} 对转180°, 底面 z={lo_new:.4f}m 贴柜底")

    log(
        f"注射泵风格化: {len(instances)} 台({'含可动件' if movable else '仅静态'}), "
        f"前脸 {axis}, 阀头在{valve_at}, 新增 {len(created)} 件, 删占位凸台 {stripped} 面"
    )
    return {
        "pumps": len(instances),
        "boss_faces_removed": stripped,
        "front_axis": axis,
        "valve_at": valve_at,
        "movable": movable,
        "stroke_mm": layout["stroke"],
        "syringe_bore_mm": layout["liquid_r"] * 2.0,
        "instances": instances,
        "objects": created,
        "synthesized": synthesized,
        "placements": placement_report,
    }


def build_axis_carriages(rig_map: dict) -> dict:
    """
    功能: 为已确认装配归属的运动轴建立 AXIS_<id>/CARRIAGE 层级.

    CARRIAGE 是一个空对象, 其原点即该轴的零位; 前端按遥测把它沿声明的轴向平移.
    未确认归属的轴(rigged: false)只登记不建组, device-manifest 会据此跳过绑定.

    参数:
        rig_map: rig_map.yaml 的内容
    返回值: dict, 各轴的装配结果
    """
    results = []
    built_carriages: dict[str, Any] = {}  # 轴 id -> CARRIAGE 空对象, 供叠轴(parent_axis)挂接
    for axis in rig_map.get("axes", []):
        axis_id = axis["id"]
        if not axis.get("rigged"):
            results.append({"id": axis_id, "rigged": False, "reason": "rig_map 中未确认装配归属"})
            continue

        station_root = bpy.data.objects.get(f"ST_{axis['station']}")
        if station_root is None:
            results.append({"id": axis_id, "rigged": False, "reason": "找不到工位根节点"})
            continue

        # 叠轴: 子轴整个模组骑在父轴滑车上(如上样 5Z 骑 3Y). 声明 parent_axis 后,
        # 本轴的 AXIS 节点挂进父轴 CARRIAGE 而不是工位根, 父轴平移自然带动整个子轴.
        # 父轴必须 rigged 且在 axes 列表里排在子轴之前 —— 顺序错了宁可硬失败.
        parent_id = axis.get("parent_axis")
        parent_carriage = None
        if parent_id:
            parent_carriage = built_carriages.get(parent_id)
            if parent_carriage is None:
                raise RuntimeError(
                    f"轴 {axis_id} 声明 parent_axis: {parent_id}, 但该父轴尚未装配 —— "
                    "父轴必须 rigged 且在 rig_map 的 axes 列表中排在子轴之前"
                )

        groups = [bpy.data.objects.get(f"ST_{g}") for g in axis.get("carriage_groups", [])]
        groups = [g for g in groups if g is not None]
        member_specs = axis.get("carriage_members") or []
        if not groups and not member_specs:
            results.append(
                {"id": axis_id, "rigged": False, "reason": "carriage_groups/carriage_members 为空或不存在"}
            )
            continue

        def descendants(root):
            """Return every descendant once, preserving the imported CAD hierarchy order."""
            found = []
            for child in root.children:
                found.append(child)
                found.extend(descendants(child))
            return found

        candidates = descendants(station_root)

        def within_subassembly(obj, needle):
            """祖先(工位根以下, 剥 .001)名字包含 needle 即视为在该子装配内."""
            node = obj.parent
            while node is not None and node != station_root:
                if needle in _base_name(node.name):
                    return True
                node = node.parent
            return False

        members = []
        for member_spec in member_specs:
            hits = [obj for obj in candidates if _plain_match(obj.name, member_spec)]
            # within: 祖先子装配限定. 同图纸孪生机构(如玻璃上料/下料机构)的内部零件
            # 连实例号都一样, equals 也会命中两份 —— 只能按祖先子装配名区分.
            needle = member_spec.get("within")
            if needle:
                hits = [obj for obj in hits if within_subassembly(obj, needle)]
            expected = int(member_spec.get("expect_count", 1))
            if len(hits) != expected:
                raise RuntimeError(
                    f"轴 {axis_id} 的刚体成员 {member_spec} 命中 {len(hits)} 个，"
                    f"预期 {expected} 个；拒绝用近似几何继续构建"
                    "(同名多实例可给该成员加 within: <祖先子装配名> 限定)"
                )
            for hit in hits:
                if hit not in members:
                    members.append(hit)

        axis_node = new_empty(f"AXIS_{axis_id.upper()}")
        reparent(axis_node, parent_carriage if parent_carriage is not None else station_root)
        # Blender 对象名全局唯一: 第二根轴起这个空对象会被自动改名成 CARRIAGE.001 等.
        # 真名必须记进报告(carriage_node), gen_twin_manifest 按报告名解析路径 ——
        # 按字面 "CARRIAGE" 找会抓到别的轴的滑车, 绑错对象且不报错.
        carriage = new_empty("CARRIAGE")
        reparent(carriage, axis_node)
        built_carriages[axis_id] = carriage
        for group in groups:
            reparent(group, carriage)
        for member in members:
            reparent(member, carriage)

        alignment_report = None
        alignment = axis.get("mount_alignment") or {}
        if alignment:
            if alignment.get("role") != "robot-base-support":
                raise RuntimeError(f"轴 {axis_id} 使用了未知的 mount_alignment: {alignment}")
            support_hits = [
                member
                for member in members
                if _plain_match(member.name, alignment.get("support_member") or {})
            ]
            if len(support_hits) != 1:
                raise RuntimeError(
                    f"轴 {axis_id} 的机器人支撑板必须唯一，实际命中 {len(support_hits)} 个"
                )
            support = support_hits[0]
            calibration = (rig_map.get("robot") or {}).get("calibration_data") or {}
            registration = calibration.get("scene_registration") or {}
            support_calibration = registration.get("rail_support") or {}
            matrix_rows = (
                registration.get("base_transform_at_reference_rail") or {}
            ).get("matrix") or []
            if len(matrix_rows) != 4:
                raise RuntimeError("缺少机器人基座参考地轨位置，无法对齐物理托盘")

            target = _gl_translation_to_blender([row[3] for row in matrix_rows[:3]])
            bpy.context.view_layer.update()
            low, high = object_world_bounds(support)
            source = Vector(((low.x + high.x) / 2.0, (low.y + high.y) / 2.0, high.z))
            delta = target - source
            shift = Matrix.Translation(delta)
            for member in members:
                member.matrix_world = shift @ member.matrix_world
            bpy.context.view_layer.update()

            support.name = alignment.get("support_node", "ROBOT_CARRIAGE_SUPPORT")
            socket = new_empty(alignment.get("socket_node", "SOCKET_ROBOT_BASE"))
            socket.matrix_world = Matrix.Translation(target)
            reparent(socket, carriage)

            expected_source = support_calibration.get("source_mount_frame_m") or []
            expected_target = support_calibration.get("reference_mount_frame_m") or []
            if len(expected_source) != 3 or len(expected_target) != 3:
                raise RuntimeError("地轨托盘源/目标安装基准未写入版本化标定")
            actual_source_gl = _to_gl(source)
            actual_target_gl = _to_gl(target)
            tolerance = 0.0001
            if any(
                abs(float(actual) - float(expected)) > tolerance
                for actual, expected in zip(actual_source_gl, expected_source)
            ):
                raise RuntimeError(
                    f"CAD 机器人支撑板基准已变化: {actual_source_gl} != {expected_source}"
                )
            if any(
                abs(float(actual) - float(expected)) > tolerance
                for actual, expected in zip(actual_target_gl, expected_target)
            ):
                raise RuntimeError(
                    f"机器人基座参考基准已变化: {actual_target_gl} != {expected_target}"
                )
            alignment_report = {
                "support_node": support.name,
                "socket_node": socket.name,
                "source_mount_frame_m": actual_source_gl,
                "reference_mount_frame_m": actual_target_gl,
                "translation_mm": [round(value * 1000.0, 4) for value in _to_gl(delta)],
            }

        # 真实路径按父链回溯到工位根拼出(叠轴/CARRIAGE 改名后与字面拼法不再一致)
        chain = []
        cursor = carriage
        while cursor is not None:
            chain.append(cursor.name)
            if cursor is station_root:
                break
            cursor = cursor.parent
        results.append(
            {
                "id": axis_id,
                "rigged": True,
                "path": "/".join(reversed(chain)),
                "axis_node": axis_node.name,
                "carriage_node": carriage.name,
                "parent_axis": parent_id,
                "carriage_groups": [g.name for g in groups],
                "carriage_members": [member.name for member in members],
                "mount_alignment": alignment_report,
            }
        )

    rigged = sum(1 for r in results if r["rigged"])
    log(f"运动轴: 已装配 {rigged} / {len(results)} 条")
    return {"axes": results}


def build_spindle_cutters(rig_map: dict) -> dict:
    """
    功能: 按 rig_map.spindles 给主轴补出**缺失的刀刃几何**, 并建成独立可自转节点.

    为什么要新造而不是拉长原件(2026-08-06):
      · 数模里 `钻头-3` 末端是 Ø10 平口截断在 z=286(逐顶点实测只有 4 个 z 层:
        456/336 R=26.0 → 316 R=17.5 → 286 R=5.0), 真机那里还伸出一段 Ø2 铣刀 ——
        用户目检定性为"下半部分画断了";
      · 但"只许平移不许改尺寸"是本仓硬原则(尺寸是唯一独立于示教点的校验手段),
        拉长原件会毁掉落座关系的可反查性;
      · 且刀刃**必须是独立节点**才能单独自转 —— 拉长 `钻头-3` 会让整只主轴壳体跟着转。
      新造节点在本仓有先例: 官方 CR5 连杆同样是本步注入、raw 阶段没有对应件。

    伸出长度与轴标定的硬关系(别随手改一个不改另一个):
      MachineStateDriver 的位移公式 offset = (mm − zeroOffsetMm) × sign × 0.001,
      axis_10z sign=−1 / zeroOffsetMm=−4.0 ⇒ 10Z = gcode.plate_surface_z_mm(20.5) 时
      刀具下探 24.5mm。要让**刀尖**恰好落在玻璃面(实测 Blender z=251.5),
      刀尖 CAD 位必须在 z=276 = 鼻端 286 − 10 ⇒ protrusion_mm = 10.0。
      换言之现役 zeroOffsetMm 本就是按"刀伸出 10mm"反解的, 本函数只是把那段几何补上。
      通式: zeroOffsetMm = protrusion_mm − 14。改伸出长度必须同步改 rig_map 的
      axis_10z.zero_offset_mm 并重编 photoscrape 全部片段(clipSchema 有零点漂移告警)。

    鼻端位置**实测取得**而非写死: 取 source_mesh 最低 z 层的顶点质心作轴线、
    最大半径作鼻端半径, 并与声明的 nose_radius_mm 对表 —— 换 CAD 版本若把主轴改了,
    这里立刻硬失败, 而不是让刀刃悬空/埋进壳体上线。

    参数:
        rig_map: rig_map.yaml 的内容
    返回值: dict, {"items": [...]}
    """
    specs = rig_map.get("spindles") or []
    if not specs:
        return {"items": []}

    items = []
    for spec in specs:
        spindle_id = str(spec.get("id") or "")
        node_name = str(spec.get("node") or "")
        if not spindle_id or not node_name:
            fail(f"主轴刀刃: 条目缺 id 或 node: {spec!r}")
        if not node_name.startswith("TOOL_"):
            fail(f"主轴刀刃: 节点名 {node_name!r} 必须以 TOOL_ 开头"
                 "(join_static_per_station 的保护前缀, 否则会被并进静态块而无法自转)")
        if bpy.data.objects.get(node_name) is not None:
            fail(f"主轴刀刃: 节点名 {node_name!r} 已被占用")

        source = bpy.data.objects.get(str(spec.get("source_mesh") or ""))
        if source is None or source.type != "MESH":
            fail(f"主轴刀刃 {spindle_id}: 找不到主轴网格 {spec.get('source_mesh')!r}")
        parent = bpy.data.objects.get(str(spec.get("parent") or ""))
        if parent is None:
            fail(f"主轴刀刃 {spindle_id}: 找不到父节点 {spec.get('parent')!r}")

        bpy.context.view_layer.update()
        world = [source.matrix_world @ vertex.co for vertex in source.data.vertices]
        nose_z = min(point.z for point in world)
        face = [point for point in world if abs(point.z - nose_z) < 5e-5]
        if len(face) < 8:
            fail(f"主轴刀刃 {spindle_id}: 鼻端平面只取到 {len(face)} 个顶点, 主轴可能已不是平口截断")
        axis_x = sum(point.x for point in face) / len(face)
        axis_y = sum(point.y for point in face) / len(face)
        nose_r_mm = max(
            math.hypot(point.x - axis_x, point.y - axis_y) for point in face
        ) * 1000.0

        expect_r = float(spec.get("nose_radius_mm", 0.0))
        tol_r = float(spec.get("nose_radius_tol_mm", 0.5))
        if expect_r > 0 and abs(nose_r_mm - expect_r) > tol_r:
            fail(f"主轴刀刃 {spindle_id}: 鼻端实测半径 {nose_r_mm:.2f}mm 与声明 "
                 f"{expect_r}mm 差超 {tol_r}mm —— CAD 主轴换过了, 先复核伸出长度再改这里")

        diameter_m = float(spec["diameter_mm"]) / 1000.0
        length_m = float(spec["protrusion_mm"]) / 1000.0
        if diameter_m <= 0 or length_m <= 0:
            fail(f"主轴刀刃 {spindle_id}: diameter_mm / protrusion_mm 必须为正")

        # 原点放在**刀尖**: 自转绕本地 Z 与绕轴线等价, 且前端拿 origin 即刀尖便于验收
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=int(spec.get("segments", 24)), radius=0.5, depth=1.0, location=(0, 0, 0))
        bit = bpy.context.active_object
        for vertex in bit.data.vertices:
            vertex.co.z += 0.5
        bit.name = node_name
        bit.data.name = f"{node_name}_mesh"
        bit.scale = (diameter_m, diameter_m, length_m)
        bit.location = Vector((axis_x, axis_y, nose_z - length_m))

        material = build_material({
            "name": f"MAT_{node_name}",
            **{
                "base_color": "#6E6E73",   # 硬质合金铣刀: 比主轴壳体暗、略哑
                "roughness": 0.35,
                "metalness": 0.9,
                **(spec.get("material") or {}),
            },
        })
        bit.data.materials.clear()
        bit.data.materials.append(material)
        reparent(bit, parent)
        if bit.name != node_name:
            fail(f"主轴刀刃: 期望节点名 {node_name!r}, Blender 实得 {bit.name!r}(重名?)")

        tip_z_mm = round((nose_z - length_m) * 1000.0, 3)
        items.append({
            "id": spindle_id,
            "node": bit.name,
            "parent": parent.name,
            "source_mesh": source.name,
            "axis_xy_mm": [round(axis_x * 1000.0, 3), round(axis_y * 1000.0, 3)],
            "nose_z_mm": round(nose_z * 1000.0, 3),
            "nose_radius_mm": round(nose_r_mm, 3),
            "diameter_mm": float(spec["diameter_mm"]),
            "protrusion_mm": float(spec["protrusion_mm"]),
            "tip_z_mm": tip_z_mm,
        })
        log(f"主轴刀刃: {bit.name} Ø{spec['diameter_mm']}×{spec['protrusion_mm']}mm "
            f"接在 {source.name} 鼻端(实测 z={nose_z * 1000:.1f}, R={nose_r_mm:.2f}mm), "
            f"刀尖 z={tip_z_mm}")
    return {"items": items}


def export_structure(path: str) -> dict:
    """
    功能: 导出最终场景的节点层级清单(路径 -> 类型/尺寸), 供 manifest 生成器使用.
    参数:
        path: 输出 JSON 路径
    返回值: dict, 层级清单
    """
    bpy.context.view_layer.update()
    entries = []

    def to_gltf(vector: Vector) -> list[float]:
        """
        功能: Blender 的 Z 轴向上坐标转成 glTF 的 Y 轴向上坐标.

        导出 GLB 时用了 export_yup=True, 因此模型在前端里是 Y 轴向上; 若结构清单
        仍按 Blender 的 Z 轴向上记录, 下游算出来的相机机位高度会用错分量.
        转换关系: (x, y, z)_blender -> (x, z, -y)_gltf

        实现委托模块级 _to_gl —— join_static_per_station 的成员包围盒也用它,
        结构清单与成员元数据两处口径必须同源, 前端才能免换算直用.

        参数: vector 三维向量
        返回值: list[float], 转换后的坐标
        """
        return _to_gl(vector)

    def walk(obj: Any, prefix: str) -> None:
        """功能: 递归记录节点. 参数: 对象/父路径. 返回值: None"""
        node_path = f"{prefix}/{obj.name}" if prefix else obj.name
        lo, hi = object_world_bounds(obj)
        entry = {"path": node_path, "name": obj.name, "type": obj.type}
        if lo.x != math.inf:
            center = to_gltf((lo + hi) / 2)
            # 尺寸是标量长度, 只换轴序不取负
            size_raw = hi - lo
            entry["center"] = center
            entry["size"] = [round(size_raw.x, 4), round(size_raw.z, 4), round(size_raw.y, 4)]
        entries.append(entry)
        for child in obj.children:
            walk(child, node_path)

    for obj in top_level_objects():
        walk(obj, "")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"nodes": entries, "coordinateSystem": "gltf-y-up"}, handle,
                  ensure_ascii=False, indent=2)
    log(f"结构清单已写入: {path} ({len(entries)} 个节点, 坐标已转为 Y 轴向上)")
    return {"nodes": len(entries), "path": path}


def build_end_effector_actuators(rig_map: dict) -> dict:
    """
    功能: 为末端执行器(工具上的可动机构)建立 ACTUATOR_* 可驱动刚体组.

    消费 rig_map 的 actuators[].build / linkages[].build 块. 必须排在 build_tools
    之后 —— 成员此刻已被认领进 TOOL_*_GEOMETRY 子树, 建出的空对象也留在该子树内,
    换刀 attach 时随整把刀走; ACTUATOR_ 前缀天然受静态合并保护.

    两类建组:
      linkage.build.groups —— 平移组(夹爪双指). 空对象位置取组内成员逐顶点世界包围盒
          中心(平移运动与枢轴位置无关, 取中心仅为可读性), 姿态保持世界轴对齐.
          ⚠ 但"局部 axis = 世界轴"不成立: 前端位移加在导出后的父空间, glTF 导出器
          共轭全层级旋转后父空间 x 与 Blender 世界 x 可能反向 —— sign 一律以导出
          GLB JSON 的节点平移排布为准(2026-08-02 夹爪"闭合反而张开"实翻过车,
          见 rig_map.yaml 头注绊线).
      actuator.build.pivot —— 旋转组(HRQ 摆动气缸). 枢轴必须实测: 在摆台端面(自动取
          缸体网格朝向转接板一侧的 1.5mm 顶点薄层)上, 以"转接板包围盒中心"为先验做
          半径直方图门控, 取模态 1mm 环带 ±2mm 做 Kasa 圆拟合 + 一轮 3σ 离群剔除.
          残差超限 / 偏离先验超限 / 转动侧成员越过摆台面, 全部 RuntimeError 硬失败,
          不允许包围盒近似(rig_map v2 门禁).

    linkage.build.gap_check 锁死"GLB 建模态 = 张开态"的前提: 沿轴实测两爪片的
    outer(外缘跨距)或 inner(净间隙), 与期望值不符即硬失败 —— CAD 换版导出闭合态时
    在这里报错, 而不是上线后夹爪动反.

    参数:
        rig_map: rig_map.yaml 的内容
    返回值: dict, 各机构建组结果(实测枢轴/间隙全部写入报告)
    """
    import numpy as np

    entries = []
    for kind, key in (("actuator", "actuators"), ("linkage", "linkages")):
        for item in rig_map.get(key) or []:
            if item.get("build"):
                entries.append((kind, item))
    if not entries:
        return {"entries": []}

    def descendants(root):
        found = []
        for child in root.children:
            found.append(child)
            found.extend(descendants(child))
        return found

    def claim(entry_id, candidates, specs):
        members = []
        for spec in specs:
            hits = [obj for obj in candidates if _plain_match(obj.name, spec)]
            expected = int(spec.get("expect_count", 1))
            if len(hits) != expected:
                raise RuntimeError(
                    f"末端执行器 {entry_id} 的成员 {spec} 命中 {len(hits)} 个, "
                    f"预期 {expected} 个; 拒绝用近似几何继续构建"
                )
            for hit in hits:
                if hit not in members:
                    members.append(hit)
        return members

    def make_actuator_empty(entry_id, name, world_pos):
        if not name.startswith("ACTUATOR_"):
            raise RuntimeError(
                f"末端执行器 {entry_id}: 节点名 {name} 必须以 ACTUATOR_ 开头(静态合并保护前缀)"
            )
        if bpy.data.objects.get(name) is not None:
            raise RuntimeError(f"末端执行器 {entry_id}: 节点名 {name} 已被占用")
        empty = new_empty(name)
        empty.matrix_world = Matrix.Translation(world_pos)
        if empty.name != name:
            raise RuntimeError(f"末端执行器 {entry_id}: 空对象名被 Blender 改写为 {empty.name}")
        return empty

    def resolve_parent(entry_id, build, scope_root):
        """解析 ACTUATOR_* 空对象该挂在谁下面.

        默认挂 scope_root(刀具子树或工位根) —— 但骑在运动轴上的工位机构必须挂进那根轴的
        CARRIAGE, 否则本步会把已被 build_axis_carriages 收进滑车的成员**重新挂出去**,
        轴一动气缸就掉队(2026-08-04 刮板下压缸实翻过这个车).

        build.parent_axis: 轴 id, 解析成 AXIS_<ID>/CARRIAGE(该轴须 rigged, 建组早于本步).
        build.parent_node: 另一个已建成的 ACTUATOR_* 名(如下压缸骑在翻料缸转子上),
                           被引用者必须在 actuators/linkages 里排在本条目之前.
        """
        axis_id = str(build.get("parent_axis") or "")
        node_name = str(build.get("parent_node") or "")
        if axis_id and node_name:
            raise RuntimeError(
                f"末端执行器 {entry_id}: parent_axis 与 parent_node 只能给一个"
                f"(实际 {axis_id!r} / {node_name!r})"
            )
        if axis_id:
            axis_node = bpy.data.objects.get(f"AXIS_{axis_id.upper()}")
            if axis_node is None:
                raise RuntimeError(
                    f"末端执行器 {entry_id}: 声明 parent_axis: {axis_id}, 但场景里没有 "
                    f"AXIS_{axis_id.upper()} —— 该轴必须 rigged(build_axis_carriages 早于本步)"
                )
            carriages = [c for c in axis_node.children if _base_name(c.name) == "CARRIAGE"]
            if len(carriages) != 1:
                raise RuntimeError(
                    f"末端执行器 {entry_id}: {axis_node.name} 下的 CARRIAGE 不唯一"
                    f"({len(carriages)} 个)"
                )
            return carriages[0]
        if node_name:
            parent = bpy.data.objects.get(node_name)
            if parent is None:
                raise RuntimeError(
                    f"末端执行器 {entry_id}: 声明 parent_node: {node_name}, 但它尚未建成 —— "
                    "被引用的执行器必须在 rig_map 的 actuators/linkages 里排在本条目之前"
                )
            return parent
        return scope_root

    def members_bounds_center(members):
        bpy.context.view_layer.update()
        bounds = [object_world_bounds(member) for member in members]
        low = Vector((min(b[0].x for b in bounds), min(b[0].y for b in bounds), min(b[0].z for b in bounds)))
        high = Vector((max(b[1].x for b in bounds), max(b[1].y for b in bounds), max(b[1].z for b in bounds)))
        return (low + high) / 2.0

    def fit_ring_pivot(entry_id, mesh_obj, prior_obj, cfg):
        """摆台轴心环带拟合. 返回 (枢轴 Vector, 拟合报告 dict); 门禁失败抛 RuntimeError.

        `cfg.axis`(Blender 轴系 x|y|z, 缺省 y)= 摆台端面法向, 也就是转轴方向:
        rob_flip_suction 的 HRQ10A 在 y, ps_rotate 的 HRQ7 摆台从缸体 −X 端伸出、在 x.
        端面沿该轴取极值薄层, 圆拟合在另外两轴张成的平面里做.
        """
        bpy.context.view_layer.update()
        axis_key = str(cfg.get("axis", "y")).lower()
        if axis_key not in _AXIS_INDEX:
            raise RuntimeError(f"末端执行器 {entry_id}: pivot.axis 只能是 x/y/z, 实际 {axis_key!r}")
        n = _AXIS_INDEX[axis_key]
        u, v = [i for i in (0, 1, 2) if i != n]

        count = len(mesh_obj.data.vertices)
        flat = np.empty(count * 3, dtype=np.float64)
        mesh_obj.data.vertices.foreach_get("co", flat)
        matrix = np.array(mesh_obj.matrix_world, dtype=np.float64)
        verts = (np.hstack([flat.reshape(count, 3), np.ones((count, 1))]) @ matrix.T)[:, :3]

        low, high = object_world_bounds(prior_obj)
        prior = ((low[u] + high[u]) / 2.0, (low[v] + high[v]) / 2.0)
        lo_n, hi_n = float(verts[:, n].min()), float(verts[:, n].max())
        mesh_center_n = (lo_n + hi_n) / 2.0
        prior_n = float((low[n] + high[n]) / 2.0)
        # 端面自动取向: 摆台面在缸体朝向转接板的那一端
        payload_side = 1 if prior_n >= mesh_center_n else -1
        face_coord = hi_n if payload_side > 0 else lo_n

        # surface: face(缺省, HRQ10A 那种圆摆台 —— 端面本身就是个圆, 取 1.5mm 顶点薄层)
        #        / bore(HRQ7 那种**方**摆台 38.9×39 —— 端面是填满的方形, 半径直方图一片
        #          平坦无环带可言; 但中心导向孔是干净圆柱面, 取两端面之间的孔壁顶点拟合,
        #          实测 R=11.82mm 残差 0.089mm, 圆心与摆台包围盒中心偏差 0.000mm)。
        surface = str(cfg.get("surface", "face")).lower()
        if surface == "bore":
            band = verts[(verts[:, n] > lo_n + 0.0006) & (verts[:, n] < hi_n - 0.0006)]
            # 分箱基准取网格自身中心: 导向孔与摆台同心, 而转接板包围盒中心可能偏出几毫米
            bin_center = ((verts[:, u].min() + verts[:, u].max()) / 2.0,
                          (verts[:, v].min() + verts[:, v].max()) / 2.0)
            shortfall = "摆台孔壁"
        elif surface == "face":
            if payload_side > 0:
                band = verts[verts[:, n] >= face_coord - 0.0015]
            else:
                band = verts[verts[:, n] <= face_coord + 0.0015]
            bin_center = prior
            shortfall = "摆台端面"
        else:
            raise RuntimeError(f"末端执行器 {entry_id}: pivot.surface 只能是 face/bore, 实际 {surface!r}")
        if len(band) < 40:
            raise RuntimeError(f"末端执行器 {entry_id}: {shortfall}顶点不足({len(band)}), 无法拟合枢轴")

        radii_mm = np.hypot(band[:, u] - bin_center[0], band[:, v] - bin_center[1]) * 1000.0
        lo_r, hi_r = [float(val) for val in (cfg.get("ring_radius_mm") or [8, 25])]
        hist, edges = np.histogram(radii_mm, bins=np.arange(0.0, hi_r + 6.0, 1.0))
        valid = [(i, int(h)) for i, h in enumerate(hist) if h > 0 and lo_r <= edges[i] <= hi_r]
        if not valid:
            raise RuntimeError(
                f"末端执行器 {entry_id}: 端面在半径 {lo_r}~{hi_r}mm 内没有环带顶点, 摆台圆面缺失"
            )
        modal = max(valid, key=lambda pair: pair[1])[0]
        # 模态 1mm 分箱两侧各扩 ring_band_mm。缺省 2.0(rob_flip_suction 沿用);
        # 特征密集处必须收窄, 否则邻近圆特征被一起拟合: HRQ7 导向孔(R=11.82)旁边
        # 9mm/13mm 还各有一圈, ±2 时残差 1.25mm, 收到 ±0.6 立刻落到 0.089mm
        # (0.4/0.6/0.8 实测同一解, 是个平台不是碰巧调出来的)。
        ring_band = float(cfg.get("ring_band_mm", 2.0))
        ring = band[(radii_mm >= edges[modal] - ring_band) & (radii_mm <= edges[modal + 1] + ring_band)]

        def kasa(points):
            a, b = points[:, u], points[:, v]
            design = np.column_stack([a, b, np.ones(len(a))])
            rhs = a * a + b * b
            sol, *_ = np.linalg.lstsq(design, rhs, rcond=None)
            ca, cb = float(sol[0]) / 2.0, float(sol[1]) / 2.0
            radius = math.sqrt(max(float(sol[2]) + ca * ca + cb * cb, 0.0))
            residual = np.abs(np.hypot(a - ca, b - cb) - radius)
            return ca, cb, radius, residual

        cu, cv, radius, residual = kasa(ring)
        keep = residual < 3.0 * max(float(residual.mean()), 1e-6)
        if int(keep.sum()) >= 12:
            cu, cv, radius, residual = kasa(ring[keep])
        resid_mm = float(residual.mean()) * 1000.0
        off_prior_mm = float(np.hypot(cu - prior[0], cv - prior[1])) * 1000.0
        residual_tol = float(cfg.get("residual_tol_mm", 0.5))
        prior_tol = float(cfg.get("prior_tol_mm", 2.0))
        if resid_mm > residual_tol:
            raise RuntimeError(
                f"末端执行器 {entry_id}: 摆台圆拟合残差 {resid_mm:.3f}mm 超限 {residual_tol}mm"
            )
        if off_prior_mm > prior_tol:
            raise RuntimeError(
                f"末端执行器 {entry_id}: 实测轴心偏离转接板中心先验 {off_prior_mm:.2f}mm 超限 {prior_tol}mm"
            )
        coords = [0.0, 0.0, 0.0]
        coords[n] = face_coord
        coords[u] = float(cu)
        coords[v] = float(cv)
        pivot = Vector(coords)
        return pivot, {
            "face_axis": axis_key,
            "face_coord": face_coord,
            "surface": surface,
            "ring_band_mm": ring_band,
            "payload_side": payload_side,
            "ring_verts": int(len(ring)),
            "ring_radius_mm": round(radius * 1000.0, 2),
            "mean_resid_mm": round(resid_mm, 3),
            "off_prior_mm": round(off_prior_mm, 2),
        }

    def run_gap_check(entry_id, candidates, cfg):
        axis_index = {"x": 0, "y": 1, "z": 2}[str(cfg.get("axis", "x")).lower()]
        pair = []
        for spec in cfg.get("between") or []:
            hits = [obj for obj in candidates if _plain_match(obj.name, spec)]
            if len(hits) != 1:
                raise RuntimeError(
                    f"末端执行器 {entry_id}: gap_check 的 {spec} 命中 {len(hits)} 个, 必须唯一"
                )
            pair.append(hits[0])
        if len(pair) != 2:
            raise RuntimeError(f"末端执行器 {entry_id}: gap_check.between 必须恰为两件")
        bpy.context.view_layer.update()
        bounds = [object_world_bounds(obj) for obj in pair]
        lows = [b[0][axis_index] for b in bounds]
        highs = [b[1][axis_index] for b in bounds]
        measure = str(cfg.get("measure", "inner"))
        if measure == "outer":
            value_mm = (max(highs) - min(lows)) * 1000.0
        else:
            left, right = (0, 1) if lows[0] <= lows[1] else (1, 0)
            value_mm = (lows[right] - highs[left]) * 1000.0
        expect = float(cfg.get("expect_mm"))
        tol = float(cfg.get("tol_mm", 2.0))
        if abs(value_mm - expect) > tol:
            raise RuntimeError(
                f"末端执行器 {entry_id}: 张开态 {measure} 实测 {value_mm:.1f}mm ≠ 期望 "
                f"{expect}±{tol}mm; 'GLB=张开态'前提被打破, 拒绝继续(检查 CAD 是否换版)"
            )
        return {"measure": measure, "value_mm": round(value_mm, 2), "expect_mm": expect, "tol_mm": tol}

    results = []
    for kind, item in entries:
        entry_id = str(item.get("id"))
        build = item.get("build") or {}
        # 作用域二选一: 刀具侧(build.tool, 成员已被 build_tools 认领进 TOOL_*_GEOMETRY)
        # 或工位侧(build.station -> ST_<id>, 工位根在 regroup 阶段就已建好)。
        # 工位侧是 2026-08-03 为 col_clamp/ps_press 加的 —— 此前只支持刀具侧, 工位机构
        # 一律走不通。
        tool_id = str(build.get("tool") or "")
        station_id = str(build.get("station") or "")
        if bool(tool_id) == bool(station_id):
            raise RuntimeError(
                f"末端执行器 {entry_id}: build 必须且只能给 tool 或 station 之一"
                f"(实际 tool={tool_id!r} station={station_id!r})"
            )
        scope_name = f"{tool_id}_GEOMETRY" if tool_id else f"ST_{station_id}"
        scope_root = bpy.data.objects.get(scope_name)
        if scope_root is None:
            raise RuntimeError(
                f"末端执行器 {entry_id}: 找不到 {scope_name}"
                "(刀具侧须排在 build_tools 之后; 工位侧须排在工位重组之后)"
            )
        candidates = descendants(scope_root)
        parent_root = resolve_parent(entry_id, build, scope_root)
        entry_report: dict = {
            "id": entry_id, "kind": kind, "scope": scope_name, "parent": parent_root.name,
        }

        # 直线缸(actuator + build.groups)与双指夹爪(linkage)走同一条建组路径: 空对象origin
        # 取成员包围盒中心, 不做环带圆拟合 —— 圆拟合是旋转缸(rob_flip_suction)专用的。
        if build.get("groups"):
            declared = ({str(m.get("node")) for m in item.get("members") or []}
                        if kind == "linkage" else {str(item.get("node"))})
            groups_report = []
            for group in build.get("groups") or []:
                name = str(group.get("empty"))
                if name not in declared:
                    raise RuntimeError(
                        f"末端执行器 {entry_id}: build.groups 的 {name} 未在 members 里声明"
                    )
                members = claim(entry_id, candidates, group.get("members") or [])
                center = members_bounds_center(members)
                empty = make_actuator_empty(entry_id, name, center)
                reparent(empty, parent_root)
                for member in members:
                    reparent(member, empty)
                groups_report.append({
                    "node": name,
                    "members": [m.name for m in members],
                    "origin_gl": _to_gl(center),
                })
            built = {g["node"] for g in groups_report}
            missing = sorted(declared - built)
            if missing:
                raise RuntimeError(f"末端执行器 {entry_id}: members 声明的 {missing} 没有对应 build.groups")
            entry_report["groups"] = groups_report
            if build.get("gap_check"):
                entry_report["gap_check"] = run_gap_check(entry_id, candidates, build["gap_check"])
        else:
            members = claim(entry_id, candidates, build.get("members") or [])
            pivot_cfg = build.get("pivot") or {}
            mesh_hits = [
                obj for obj in candidates
                if obj.type == "MESH" and _plain_match(obj.name, pivot_cfg.get("mesh") or {})
            ]
            if len(mesh_hits) != 1:
                raise RuntimeError(
                    f"末端执行器 {entry_id}: pivot.mesh 命中 {len(mesh_hits)} 个网格, 必须唯一"
                )
            prior_hits = [
                obj for obj in candidates if _plain_match(obj.name, pivot_cfg.get("prior_member") or {})
            ]
            if len(prior_hits) != 1:
                raise RuntimeError(
                    f"末端执行器 {entry_id}: pivot.prior_member 命中 {len(prior_hits)} 个, 必须唯一"
                )
            pivot, fit_report = fit_ring_pivot(entry_id, mesh_hits[0], prior_hits[0], pivot_cfg)
            face_axis = fit_report["face_axis"]
            axis_index = _AXIS_INDEX[face_axis]
            face_coord = fit_report["face_coord"]
            for member in members:
                low, high = object_world_bounds(member)
                if fit_report["payload_side"] > 0 and low[axis_index] < face_coord - 0.002:
                    raise RuntimeError(
                        f"末端执行器 {entry_id}: 成员 {member.name} 越过摆台面({face_axis}_min="
                        f"{low[axis_index]:.4f} < {face_coord:.4f}), 不属于转动侧"
                    )
                if fit_report["payload_side"] < 0 and high[axis_index] > face_coord + 0.002:
                    raise RuntimeError(
                        f"末端执行器 {entry_id}: 成员 {member.name} 越过摆台面({face_axis}_max="
                        f"{high[axis_index]:.4f} > {face_coord:.4f}), 不属于转动侧"
                    )
            node_name = str(item.get("node"))
            empty = make_actuator_empty(entry_id, node_name, pivot)
            reparent(empty, parent_root)
            for member in members:
                reparent(member, empty)
            entry_report.update({
                "node": node_name,
                "members": [m.name for m in members],
                "pivot_gl": _to_gl(pivot),
                "fit": fit_report,
            })
        results.append(entry_report)

    log(
        "末端执行器: 建组 "
        + ", ".join(f"{r['id']}({r['kind']})" for r in results)
    )
    return {"entries": results}


#: 逐盘实测孔阵登记(build_inventory_nodes 填, export_consumable_lattice 导出)。
#: 孔心存**盘根局部系** —— apply_station_alignment 会平移工位装配, 局部坐标不变,
#: 导出时再乘回 matrix_world 得到与成品 GLB 一致的世界系。
_CONSUMABLE_LATTICE: list[dict] = []


def _kasa_circle(points_xy: "np.ndarray") -> tuple["np.ndarray", float, float]:
    """代数最小二乘圆拟合(Kasa)。points_xy: (N,2) 米。返回 (圆心, 半径, 平均残差米)。"""
    a = np.column_stack((points_xy[:, 0], points_xy[:, 1], np.ones(len(points_xy))))
    b = (points_xy ** 2).sum(axis=1)
    solution, *_rest = np.linalg.lstsq(a, b, rcond=None)
    center = solution[:2] / 2.0
    radius = math.sqrt(max(float(solution[2]) + float(center @ center), 0.0))
    residual = np.abs(np.linalg.norm(points_xy - center, axis=1) - radius)
    return center, radius, float(residual.mean())


def measure_plate_hole_lattice(plate_obj) -> dict:
    """从孔板**自己的网格**实测 6 孔中心与两向节距。

    为什么必须逐盘量: 瓶板(PTLC-01-007)实测孔距 42.5×40.0mm 而收集板(PTLC-01-009)
    是 47.5×45.0 —— 此前单一 gridReference 把收集盘节距套给全部 14 盘, 7 个瓶托盘的
    件阵按格阶梯偏 0/5/10mm(staging-b 1 号位偏 11.2mm, 悬出板沿 6.9mm 插进角柱,
    观感"瓶子没放在托盘里", 2026-08-06 用户报障)。与 measure_plate_nests /
    fit_station_alignment 同一条纪律: 实测, 不写死。

    做法: 板厚内部带(去上下大面)→ 去外沿 5mm(外侧壁/倒角)→ 水平面单链聚类 ε=6mm
    (孔缘镶嵌 ~2.6mm 连成环; 孔间最窄壁 = 瓶板列向 40−29.5=10.5mm, 不会被桥接)→
    簇门[8,20]mm(滤角柱孔/沉头螺孔)→ 每簇取模态半径环做 Kasa 拟合(防同心多径偏置)。

    返回: {"centers": [Vector×6 世界系], "row_pitch": 长边节距m, "column_pitch": 短边节距m,
           "long_axis": Vector(水平单位向量), "residual_mm": 最大孔拟合残差}
    任何一步对不上都 RuntimeError —— 板改版/认错网格要在这里大声死, 不许猜。
    """
    from mathutils import kdtree

    mesh = plate_obj.data
    count = len(mesh.vertices)
    if count < 100:
        raise RuntimeError(f"{plate_obj.name} 顶点过少({count}), 不像孔板网格")
    raw = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", raw)
    matrix = np.array(plate_obj.matrix_world, dtype=np.float64)
    world = raw.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]

    z_low, z_high = float(world[:, 2].min()), float(world[:, 2].max())
    band = world[(world[:, 2] > z_low + 0.0003) & (world[:, 2] < z_high - 0.0003)]
    if len(band) < 50:
        raise RuntimeError(f"{plate_obj.name} 板厚内部带只剩 {len(band)} 点, 板厚/网格异常")
    x_low, x_high = float(band[:, 0].min()), float(band[:, 0].max())
    y_low, y_high = float(band[:, 1].min()), float(band[:, 1].max())
    # 外沿只裁 1mm: 外侧壁顶点恰在面内 bbox 周界上, 1mm 足够裁掉它与贴边倒角。
    # 不许再宽 —— 收集板(127.9mm 宽)的四个角孔环外缘距板边只有 1.7mm(实测,
    # 2026-08-06 首跑用 5mm 裁掉外弧, 残弧质心内移 4.2mm、延展 20.7 超门, 6 孔只剩 2)。
    margin = 0.001
    inner = band[(band[:, 0] > x_low + margin) & (band[:, 0] < x_high - margin)
                 & (band[:, 1] > y_low + margin) & (band[:, 1] < y_high - margin)]
    if len(inner) < 50:
        raise RuntimeError(f"{plate_obj.name} 内部特征点只剩 {len(inner)}, 孔阵检测失败")

    def link_clusters(points_xy: "np.ndarray", eps: float) -> list["np.ndarray"]:
        """平面单链聚类(kd 树 BFS), 返回索引数组列表。"""
        tree = kdtree.KDTree(len(points_xy))
        for index, point in enumerate(points_xy):
            tree.insert(Vector((float(point[0]), float(point[1]), 0.0)), index)
        tree.balance()
        labels = [-1] * len(points_xy)
        result: list[list[int]] = []
        for seed in range(len(points_xy)):
            if labels[seed] != -1:
                continue
            labels[seed] = len(result)
            queue, members = [seed], []
            while queue:
                node = queue.pop()
                members.append(node)
                for _co, other, _dist in tree.find_range(
                        Vector((float(points_xy[node][0]), float(points_xy[node][1]), 0.0)),
                        eps):
                    if labels[other] == -1:
                        labels[other] = labels[seed]
                        queue.append(other)
            result.append(members)
        return [np.asarray(members, dtype=int) for members in result]

    inner_xy = inner[:, :2]
    inner_z = inner[:, 2]
    candidates: list["np.ndarray"] = []
    for members in link_clusters(inner_xy, 0.006):
        points = inner_xy[members]
        mean = points.mean(axis=0)
        extent = float(np.linalg.norm(points - mean, axis=1).max())
        if extent > 0.020:
            # 桥接簇: 收集板的角孔环与近旁角落小特征(螺孔/圆角弧)间隙仅 ~4.6mm,
            # ε=6 会连通成 22.6mm 大簇(2026-08-06 实测, 首跑因此 6 孔只剩 2)。簇内用
            # ε=2.5mm 重聚拆桥 —— 孔环自身镶嵌间距 ≤1.7mm 拆不散, 小特征簇随后被
            # 下限门(8mm)拦掉。
            for sub in link_clusters(points, 0.0025):
                candidates.append(members[sub])
            continue
        candidates.append(members)

    holes_found: list[tuple] = []
    rejected: list[tuple] = []
    worst_residual = 0.0
    for members in candidates:
        points = inner_xy[members]
        mean = points.mean(axis=0)
        extent = float(np.linalg.norm(points - mean, axis=1).max())
        if not 0.008 <= extent <= 0.020:
            rejected.append((len(points), round(extent * 1000, 1),
                             [round(float(v), 4) for v in mean]))
            continue
        radial = np.linalg.norm(points - mean, axis=1)
        bins = np.floor(radial / 0.001).astype(int)
        modal = int(np.bincount(bins).argmax())
        ring = points[(bins >= modal - 1) & (bins <= modal + 1)]
        center, _radius, residual = _kasa_circle(ring)
        if residual > 0.0006:
            raise RuntimeError(
                f"{plate_obj.name} 孔拟合残差 {residual * 1000:.2f}mm > 0.6 —— 网格异常, "
                f"簇心 {[round(float(v), 4) for v in mean]}")
        worst_residual = max(worst_residual, residual)
        z_mid = float(inner_z[members].mean())
        holes_found.append((center, z_mid))
    if len(holes_found) != 6:
        raise RuntimeError(
            f"{plate_obj.name} 检出 {len(holes_found)} 个孔, 期望恰 6 —— 板改版/簇门失配。"
            f"被拒簇(点数, 延展mm, 位置): {rejected}")

    centers_xy = np.array([hole[0] for hole in holes_found])
    spread = centers_xy - centers_xy.mean(axis=0)
    _eig, eigvec = np.linalg.eigh(spread.T @ spread)
    long_axis = eigvec[:, -1]
    short_axis = np.array([-long_axis[1], long_axis[0]])
    short_coord = spread @ short_axis
    order = np.argsort(short_coord)
    row_a, row_b = order[:3], order[3:]
    row_gap = float(short_coord[row_b].mean() - short_coord[row_a].mean())
    if row_gap < 0.020:
        raise RuntimeError(f"{plate_obj.name} 两排孔分不开(排距 {row_gap * 1000:.1f}mm)")
    long_deltas: list[float] = []
    aligned: list[np.ndarray] = []
    for row in (row_a, row_b):
        t = np.sort(centers_xy[row] @ long_axis)
        aligned.append(t)
        long_deltas.extend([float(t[1] - t[0]), float(t[2] - t[1])])
    if max(long_deltas) - min(long_deltas) > 0.0002:
        raise RuntimeError(
            f"{plate_obj.name} 沿长边四段节距不一致: "
            f"{[round(v * 1000, 3) for v in long_deltas]}")
    if float(np.abs(aligned[0] - aligned[1]).max()) > 0.0003:
        raise RuntimeError(f"{plate_obj.name} 两排孔沿长边未对齐(>0.3mm), 不是矩形格")
    row_pitch = float(np.mean(long_deltas))
    column_pitch = abs(row_gap)
    for label, pitch in (("行距", row_pitch), ("列距", column_pitch)):
        if not 0.035 <= pitch <= 0.055:
            raise RuntimeError(f"{plate_obj.name} {label} {pitch * 1000:.1f}mm 超出 35..55 合理域")
    return {
        "centers": [Vector((float(c[0]), float(c[1]), float(z))) for c, z in holes_found],
        "row_pitch": row_pitch,
        "column_pitch": column_pitch,
        "long_axis": Vector((float(long_axis[0]), float(long_axis[1]), 0.0)),
        "residual_mm": round(worst_residual * 1000.0, 3),
    }


def export_consumable_lattice(work_dir: str) -> int:
    """把逐盘实测孔阵落盘 work/consumable_lattice.json, 供 verify_staging_numbering 复核。

    必须在 apply_station_alignment **之后**调用: 登记表存盘根局部系, 此刻乘回
    matrix_world 得到的世界系才与成品 GLB 一致(经 _to_gl 转 glTF Y-up)。
    """
    if len(_CONSUMABLE_LATTICE) != 14:
        raise RuntimeError(f"耗材孔阵登记 {len(_CONSUMABLE_LATTICE)} 盘, full 阶段应恰 14")
    trays = []
    for entry in _CONSUMABLE_LATTICE:
        owner = bpy.data.objects.get(entry["node"])
        if owner is None:
            raise RuntimeError(f"孔阵导出: 场景里找不到 {entry['node']}")
        row = {key: entry[key] for key in
               ("node", "kind", "plate", "rowPitchMm", "colPitchMm", "fitResidualMm")}
        row["trayWorldTranslation"] = _to_gl(owner.matrix_world.translation)
        row["holeCentersWorld"] = [
            _to_gl(owner.matrix_world @ Vector(local)) for local in entry["holeCentersLocal"]]
        trays.append(row)
    path = os.path.join(work_dir, "consumable_lattice.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"schema": "ptlc.consumable-lattice/v1", "trays": trays},
                  handle, ensure_ascii=False, indent=2)
    log(f"耗材孔阵实测已写入: {path}(14 盘 × 6 孔)")
    return len(trays)


def build_inventory_nodes(rig_map: dict) -> dict:
    """把物料 CAD 实体改成稳定 ``INV_*`` 节点并从静态合并中保护出来。"""
    config = rig_map.get("inventory") or {}
    if not config:
        return {"rack": 0, "staging": 0, "magazines": 0}

    del _CONSUMABLE_LATTICE[:]  # 同进程重跑不叠加旧登记
    missing: list[str] = []

    def under(obj: Any, ancestor_name: str | None) -> bool:
        if not ancestor_name:
            return True
        node = obj.parent
        while node is not None:
            if node.name == ancestor_name:
                return True
            node = node.parent
        return False

    def find_exact(source: str, ancestor_name: str | None = None):
        hits = [obj for obj in bpy.data.objects if obj.name == source and under(obj, ancestor_name)]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            missing.append(f"{ancestor_name + '/' if ancestor_name else ''}{source}")
        else:
            missing.append(f"{source}(命中 {len(hits)} 个，拒绝猜选)")
        return None

    rack_roots: dict[tuple[str, int], Any] = {}
    rack_count = 0
    rack_exclude = [str(item) for item in (config.get("rackExclude") or [])]
    excluded_total = 0
    for kind, entries in (config.get("rack") or {}).items():
        for entry in entries or []:
            obj = find_exact(str(entry.get("source") or ""))
            if obj is None:
                continue
            shelf = obj.parent  # 改名前先记住货架侧父级, 排除件要挪回它下面
            obj.name = str(entry["node"])
            obj["ptlc_inventory_kind"] = kind
            obj["ptlc_inventory_plate"] = int(entry["plate"])
            # rack 是"整棵 CAD 装配改名", 装配里混着的货架件必须挪出去, 否则会被当成
            # 托盘的一部分搬走(实证: PTLC-01-005 样品放置板 是库位搁板, 12 个实例对应
            # 12 个库位, 两个中转托盘装配里都没有它)。
            for child in list(obj.children):
                if not any(token in child.name for token in rack_exclude):
                    continue
                if shelf is None:
                    fail(f"{obj.name} 没有货架侧父级, 无处安放排除件 {child.name}")
                reparent(child, shelf)
                excluded_total += 1
            rack_roots[(str(kind), int(entry["plate"]))] = obj
            rack_count += 1
    if rack_exclude:
        expected = len(rack_exclude) * rack_count
        # 声明了却一个都没命中 = 静默失效, 与"显式名单未命中必须告警"(CLAUDE.md 第 27 条)同理。
        if excluded_total != expected:
            fail(
                f"货架排除件命中 {excluded_total} 个, 预期 {expected} 个"
                f"({len(rack_exclude)} 条规则 × {rack_count} 个托盘): {rack_exclude}"
            )
        log(f"货架排除件: 从 {rack_count} 个托盘各挪出 {len(rack_exclude)} 件, 共 {excluded_total} 件")

    staging_roots: dict[str, Any] = {}
    staging_count = 0
    for entry in config.get("staging") or []:
        target_name = str(entry["node"])
        source = entry.get("source")
        if source:
            obj = find_exact(str(source))
            if obj is None:
                continue
            obj.name = target_name
            obj["ptlc_inventory_area"] = str(entry["area"])
            staging_roots[str(entry["area"])] = obj
            staging_count += 1
            continue

        ancestor_name = str(entry.get("ancestor") or "")
        ancestor = find_exact(ancestor_name)
        if ancestor is None:
            continue
        group = new_empty(target_name)
        reparent(group, ancestor)
        group["ptlc_inventory_area"] = str(entry["area"])
        member_count = 0
        for member_name in entry.get("members") or []:
            member = find_exact(str(member_name), ancestor_name)
            if member is None:
                continue
            reparent(member, group)
            member_count += 1
        if member_count:
            staging_roots[str(entry["area"])] = group
            staging_count += 1
        else:
            missing.append(f"{target_name}(没有托盘成员)")

    magazine_count = 0
    for entry in config.get("magazines") or []:
        obj = find_exact(str(entry.get("source") or ""))
        if obj is None:
            continue
        obj.name = str(entry["node"])
        obj["ptlc_inventory_magazine"] = str(entry["id"])
        magazine_count += 1

    if missing:
        raise RuntimeError("物料 CAD 映射缺失，拒绝生成近似库存几何: " + ", ".join(missing))

    consumable_cfg = config.get("consumables") or {}
    consumable_slots = 0
    if consumable_cfg:
        holes = int(consumable_cfg.get("holesPerTray", 6))
        # 孔号行进方向, 声明在 rig_map(与 tanks.order_by 同一条纪律): 缺省 pair_first 是
        # 2026-08-06 之前的旧行为, 与机器人点表转置 —— 现役配置必须显式写 long_asc_ccw。
        hole_order = str(consumable_cfg.get("holeOrder") or "pair_first")
        if hole_order not in ("long_asc_ccw", "pair_first"):
            raise RuntimeError(
                f"consumables.holeOrder 只认 long_asc_ccw|pair_first, 实际: {hole_order!r}")
        collector_prefix = str(consumable_cfg.get("collectorPrefix") or "")
        bottle_prefix = str(consumable_cfg.get("bottlePrefix") or "")
        collector_plate_prefix = str(consumable_cfg.get("collectorPlatePrefix") or "")
        bottle_plate_prefix = str(consumable_cfg.get("bottlePlatePrefix") or "")
        reference_name = str(consumable_cfg.get("gridReference") or "")

        def descendants(root: Any) -> list[Any]:
            result: list[Any] = []
            stack = list(root.children)
            while stack:
                node = stack.pop()
                result.append(node)
                stack.extend(node.children)
            return result

        def hole_plate(root: Any, kind: str) -> Any:
            prefix = collector_plate_prefix if kind == "collector" else bottle_plate_prefix
            hits = [node for node in descendants(root) if node.type == "MESH" and node.name.startswith(prefix)]
            if len(hits) != 1:
                raise RuntimeError(f"{root.name} 的 {kind} 孔板命中 {len(hits)} 个，拒绝猜选")
            return hits[0]

        def plate_geometry(root: Any, kind: str) -> tuple[Any, Vector, Vector]:
            plate = hole_plate(root, kind)
            low, high = object_world_bounds(plate)
            return plate, (low + high) * 0.5, high - low

        rack_layout = config.get("rackLayout") or {}
        if rack_layout:
            tiers = int(rack_layout.get("tiers", 4))
            slots_per_tier = int(rack_layout.get("slotsPerTier", 3))
            if tiers * slots_per_tier != len(rack_roots):
                raise RuntimeError("货架层列配置与 12 个托盘槽不一致")
            current = []
            for (kind, plate), root in rack_roots.items():
                _mesh, center, _size = plate_geometry(root, kind)
                current.append({"kind": kind, "plate": plate, "root": root, "center": center})
            # Blender Z-up: z 是高度(层), y 是进深(层内 3 槽); 同层两种托盘的孔板
            # 中心高度在 CAD 中逐层相等, 毫米级圆整保证同层聚为同键.
            # 层内 1..3 号位沿 y 降序(2026-08-02 对照实机核定; 前端正视图左->右).
            slots = sorted(
                [item["center"].copy() for item in current],
                key=lambda point: (-round(point.z, 3), -round(point.y, 3)),
            )
            upper_kind = str(rack_layout.get("upperKind") or "collector")
            lower_kind = str(rack_layout.get("lowerKind") or "bottle")
            ordered_owners = (
                sorted([item for item in current if item["kind"] == upper_kind], key=lambda item: item["plate"])
                + sorted([item for item in current if item["kind"] == lower_kind], key=lambda item: item["plate"])
            )
            if len(ordered_owners) != len(slots):
                raise RuntimeError("货架上下层物料种类没有完整覆盖全部托盘")
            for owner, target in zip(ordered_owners, slots):
                delta = target - owner["center"]
                owner["root"].matrix_world.translation += delta
            bpy.context.view_layer.update()
            # 再次从孔板实测做真校验: 12 张托盘必须铺满 "tiers 层(z) x slotsPerTier
            # 进深(y)" 网格, 且几何最高的一半层全为 upperKind、其余层全为 lowerKind.
            final_rows = []
            for owner in ordered_owners:
                _mesh, center, _size = plate_geometry(owner["root"], owner["kind"])
                final_rows.append({"kind": owner["kind"], "plate": owner["plate"], "center": center})

            def cluster(values: list[float], expected: int, label: str) -> list[float]:
                ordered = sorted(values)
                groups: list[list[float]] = [[ordered[0]]]
                for value in ordered[1:]:
                    if value - groups[-1][-1] > 0.02:
                        groups.append([])
                    groups[-1].append(value)
                if len(groups) != expected:
                    raise RuntimeError(
                        f"货架{label}应聚成 {expected} 组, 实得 {len(groups)} 组: "
                        f"{[round(group[0], 4) for group in groups]}"
                    )
                return [sum(group) / len(group) for group in groups]

            tier_heights = cluster([row["center"].z for row in final_rows], tiers, "层高(z)")
            tier_heights.sort(reverse=True)  # 下标 0 = 最上层
            depth_slots = cluster([row["center"].y for row in final_rows], slots_per_tier, "进深(y)")
            occupied: dict[tuple[int, int], int] = {}
            for row in final_rows:
                tier_index = min(range(tiers), key=lambda i: abs(row["center"].z - tier_heights[i]))
                depth_index = min(
                    range(slots_per_tier), key=lambda i: abs(row["center"].y - depth_slots[i])
                )
                cell = (tier_index, depth_index)
                if cell in occupied:
                    raise RuntimeError(f"货架槽位 层{tier_index + 1}/位{depth_index + 1} 被重复占用")
                occupied[cell] = row["plate"]
                expected_kind = upper_kind if tier_index < tiers // 2 else lower_kind
                if row["kind"] != expected_kind:
                    raise RuntimeError(
                        f"货架分层校验失败: 层{tier_index + 1} 出现 {row['kind']}#{row['plate']}, "
                        f"该层只允许 {expected_kind}"
                    )
            log(
                f"货架分层: 上两层 {upper_kind} 1..6, 下两层 {lower_kind} 1..6; "
                f"层高(z) {[round(v, 4) for v in tier_heights]}; "
                f"进深(y) {[round(v, 4) for v in depth_slots]}"
            )

        def direct_payloads(root: Any, prefix: str) -> list[Any]:
            return [child for child in root.children if child.name.startswith(prefix)]

        def numbered(items: list[Any], prefix: str) -> dict[int, Any]:
            result: dict[int, Any] = {}
            pattern = re.compile(rf"^{re.escape(prefix)}(\d+)")
            for item in items:
                match = pattern.match(item.name)
                if match:
                    result[int(match.group(1))] = item
            return result

        def duplicate_subtree(source: Any) -> Any:
            clone = source.copy()
            if source.data is not None:
                clone.data = source.data
            bpy.context.scene.collection.objects.link(clone)
            clone.matrix_world = source.matrix_world.copy()
            for child in source.children:
                child_clone = duplicate_subtree(child)
                reparent(child_clone, clone)
            return clone

        reference = bpy.data.objects.get(reference_name)
        if reference is None:
            raise RuntimeError(f"耗材孔距参考节点不存在: {reference_name}")
        reference_items = numbered(direct_payloads(reference, collector_prefix), collector_prefix)
        if not all(hole in reference_items for hole in (1, 2, 3)):
            raise RuntimeError("中转 A CAD 缺少 1/2/3 号收集器，无法由真实几何求六孔间距")
        bpy.context.view_layer.update()
        origin = reference_items[1].matrix_world.translation.copy()
        column_step = reference_items[2].matrix_world.translation.copy() - origin
        row_step = reference_items[3].matrix_world.translation.copy() - origin
        if min(column_step.length, row_step.length) < 0.001:
            raise RuntimeError("中转 A CAD 六孔间距退化，拒绝复制耗材")
        # Blender z 是高度: 孔距向量必须水平, 否则说明参考件被倒装/挪动过.
        for step_label, step in (("1->2", column_step), ("1->3", row_step)):
            if abs(step.z) > 0.002:
                raise RuntimeError(
                    f"中转 A 孔距向量 {step_label} 不水平(dz={step.z * 1000:.1f} mm), 参考几何被污染"
                )

        # 2026-08-06 降级: 参考实例推导的节距**不再驱动摆放**(瓶板孔距 42.5×40 与收集板
        # 47.5×45 不同, 单一参考曾让 7 个瓶托盘的件阵梯次偏 0/5/10mm), 只留作中转A上
        # 与板孔实测互证的第二来源 —— 见 materialize 里的交叉核对。
        reference_row_pitch = row_step.length
        reference_column_pitch = column_step.length

        def materialize(owner: Any, kind: str) -> int:
            prefix = collector_prefix if kind == "collector" else bottle_prefix
            existing = direct_payloads(owner, prefix)
            if kind == "collector":
                by_hole = numbered(existing, prefix)
            elif len(existing) > 1:
                raise RuntimeError(
                    f"{owner.name} 有 {len(existing)} 个未编号的 {kind} 实例, 无法确定模板孔位"
                )
            else:
                by_hole = {1: existing[0]} if existing else {}
            if 1 not in by_hole:
                raise RuntimeError(f"{owner.name} 缺少 {kind} 耗材模板")
            template = by_hole[1]
            template_world = template.matrix_world.copy()
            _plate, plate_center, plate_size = plate_geometry(owner, kind)
            # 行列都在水平面内(x 横向, y 进深); z 是板厚方向, 不能当排布轴.
            # 行向(3 孔 x 47.5mm)沿孔板长边, 列向(2 孔 x 45mm)沿短边 --
            # 中转 B 整盘旋转 90 度, 长边在 y 上, 按各孔板自身实测尺寸判长短边.
            if abs(plate_size.x - plate_size.y) < 0.02:
                raise RuntimeError(
                    f"{owner.name} 孔板近似方形({plate_size.x:.4f}x{plate_size.y:.4f} m), 拒绝猜行列朝向"
                )
            if plate_size.x >= plate_size.y:
                row_axis = Vector((1.0, 0.0, 0.0))
                column_axis = Vector((0.0, 1.0, 0.0))
            else:
                row_axis = Vector((0.0, 1.0, 0.0))
                column_axis = Vector((1.0, 0.0, 0.0))
            template_position = template_world.translation.copy()
            # 节距与孔位**逐盘实测自本盘孔板**(见 measure_plate_hole_lattice 头注);
            # gridReference 的实例推导节距只在中转A上作第二来源互证。
            lattice = measure_plate_hole_lattice(_plate)
            if owner.name == "INV_STAGING_A":
                for check_label, measured, expected in (
                        ("行距", lattice["row_pitch"], reference_row_pitch),
                        ("列距", lattice["column_pitch"], reference_column_pitch)):
                    if abs(measured - expected) > 0.001:
                        raise RuntimeError(
                            f"中转A {check_label} 板孔实测 {measured * 1000:.2f}mm 与实例推导 "
                            f"{expected * 1000:.2f}mm 差超 1mm —— 两条独立来源必须互证")
            axis_dot = abs(lattice["long_axis"].normalized().dot(row_axis))
            if axis_dot < 0.9994:  # cos 2°: 孔阵长轴必须与孔板 bbox 长边一致
                raise RuntimeError(f"{owner.name} 孔阵长轴与孔板长边不一致(cos={axis_dot:.4f})")
            if hole_order == "long_asc_ccw":
                if holes != 6:
                    raise RuntimeError(
                        f"holeOrder=long_asc_ccw 按 3x2 网格写死, holesPerTray={holes} 需重推规则")
                # 位置**直接取实测孔心**(高度沿用模板 Z): 比"模板角+节距重建"更强 ——
                # 连模板件自身在孔内的毫米级偏摆也一并消掉。模板必须坐在某个孔里(锚定
                # 检查): 差 >1.5mm 说明模板被挪动或孔检错位 —— 旧质心门在 5.6mm 节距
                # 误差下仍是绿的(2026-08-06 实测), 这道门不许再犯。
                template_xy = Vector((template_position.x, template_position.y, 0.0))
                anchor_miss = min(
                    (Vector((c.x, c.y, 0.0)) - template_xy).length for c in lattice["centers"])
                if anchor_miss > 0.0015:
                    raise RuntimeError(
                        f"{owner.name} 模板件不在任何实测孔位上(差 {anchor_miss * 1000:.1f}mm)")
                grid_positions = [Vector((c.x, c.y, template_position.z))
                                  for c in lattice["centers"]]
                # 机器人点表的孔号行进方向(2026-08-06 由 P46..P58 正解拟合定案, 见 rig_map
                # 注释与 verify_staging_numbering.py): 沿长边世界坐标**升序**编 1..3,
                # 第二排 4..6 在长边正方向**逆时针(+Z 俯视)**一侧(row_dir = Z x d_long)。
                # 世界系规则对 14 个托盘一体适用, 不锚在各盘 CAD 模板落角上。
                d_long = lattice["long_axis"].normalized()
                principal = d_long.x if abs(d_long.x) >= abs(d_long.y) else d_long.y
                if principal < 0:
                    d_long = -d_long
                row_dir = Vector((0.0, 0.0, 1.0)).cross(d_long)
                ordered = sorted(grid_positions, key=lambda p: round(p.dot(row_dir), 6))
                positions = (sorted(ordered[:3], key=lambda p: p.dot(d_long))
                             + sorted(ordered[3:], key=lambda p: p.dot(d_long)))
            else:  # pair_first: 旧行为(短边两孔一对先走, 锚在模板角), 一键回退保留
                candidates = []
                for row_sign in (-1.0, 1.0):
                    for column_sign in (-1.0, 1.0):
                        row_vector = row_axis * lattice["row_pitch"] * row_sign
                        column_vector = column_axis * lattice["column_pitch"] * column_sign
                        centroid = template_position + row_vector + column_vector * 0.5
                        error = ((centroid.x - plate_center.x) ** 2
                                 + (centroid.y - plate_center.y) ** 2)
                        candidates.append((error, row_vector, column_vector))
                chosen_error, owner_row_step, owner_column_step = min(
                    candidates, key=lambda item: item[0])
                if chosen_error > 0.02 ** 2:
                    raise RuntimeError(
                        f"{owner.name} 六孔网格质心偏离孔板中心 "
                        f"{chosen_error ** 0.5 * 1000:.1f} mm, 行列轴或模板孔位异常")
                positions = [
                    template_position + owner_row_step * ((hole - 1) // 2)
                    + owner_column_step * ((hole - 1) % 2)
                    for hole in range(1, holes + 1)
                ]
            owner_inverse = owner.matrix_world.inverted()
            _CONSUMABLE_LATTICE.append({
                "node": owner.name, "kind": kind, "plate": _plate.name,
                "rowPitchMm": round(lattice["row_pitch"] * 1000.0, 3),
                "colPitchMm": round(lattice["column_pitch"] * 1000.0, 3),
                "fitResidualMm": lattice["residual_mm"],
                "holeCentersLocal": [list(owner_inverse @ c) for c in lattice["centers"]],
            })
            for hole in range(1, holes + 1):
                item = by_hole.get(hole)
                if item is None:
                    item = duplicate_subtree(template)
                target_position = positions[hole - 1]
                # 基(旋转+缩放)一律取模板: CAD 里 6 个货架 硅胶收集-2 实例是 180 度
                # 倒装的, 只改平移会让吹气头/注射器朝下穿板; 模板自身代入为恒等.
                world = template_world.copy()
                world.translation = target_position
                item.matrix_world = world
                item.name = f"{owner.name}_ITEM_{hole}"
                item["ptlc_inventory_hole"] = hole
                item["ptlc_inventory_kind"] = kind
            return holes

        for (kind, _plate), root in sorted(rack_roots.items()):
            consumable_slots += materialize(root, kind)
        consumable_slots += materialize(staging_roots["staging-a"], "collector")
        consumable_slots += materialize(staging_roots["staging-b"], "bottle")
        pitch_by_kind: dict[str, set] = {}
        for entry in _CONSUMABLE_LATTICE:
            pitch_by_kind.setdefault(entry["kind"], set()).add(
                (entry["rowPitchMm"], entry["colPitchMm"]))
        log(
            "耗材刚体: "
            f"{len(rack_roots) + len(staging_roots)} 个托盘 × {holes} 孔 = {consumable_slots}; "
            "实测孔距 " + "; ".join(
                f"{kind} {sorted(values)}" for kind, values in sorted(pitch_by_kind.items()))
        )

    log(f"物料刚体: 货架托盘 {rack_count}, 中转托盘 {staging_count}, 板仓模板 {magazine_count}")
    return {
        "rack": rack_count,
        "staging": staging_count,
        "magazines": magazine_count,
        "consumable_slots": consumable_slots,
    }


def measure_plate_nests(tray: Any, plate_mm: tuple, cfg: dict) -> list:
    """
    功能: 从物料盘上实测出若干"孔板巢" —— 开口矩形 + 落板面高度, 一个数都不写死.

    为什么落点必须实测: 与 build_inventory_nodes 从 INV_STAGING_A 反推孔距同一原则 ——
    CAD 一改, 这里跟着改; 而写死的坐标改了 CAD 也不会报错, 只会静静地摆错位置.

    算法(先找**台肩**, 再由台肩定巢):
      1. 从上方打射线做高度图, 台面 = 最高面.
      2. 逐个候选高度层由高到低试: 取该层的格子聚类, 总面积够大的第一层就是**落板台肩**
         —— 这是个真实的物理判据(板裙边得有像样的接触面积才坐得住), 不是拍脑袋的阈值.
         本机实测: 台面 79.0 之下依次是 78.0(1mm 窄沿, 面积不够)、74.5(四条 32×90 台肩,
         合计 115cm², 命中)、70.99(深槽, 给孔底让位).
      3. 台肩聚类两两合并成巢: 两块台肩属于同一个巢, 当且仅当它们在某个轴上有重叠, 且合
         并后的外框在两个轴上都还塞得进"板尺寸 + 最大间隙". 这条判据自带收敛性, 不需要
         预先声明巢沿哪根轴排列 —— 本机四条台肩因此正确并成两个巢(左右两条并, 上下两条不并).

    ⚠ 不能用面岛或包围盒: 巢里既有台肩又有深槽还有中间通孔, 面岛拆出来是七八块互不相连
    的碎片; 而"顶面低于台面"的格子会顺着台面那圈窄沿连成一整块(实测把两个巢连成 230×204
    的一大块), 单纯的连通聚类在这块托盘上是失效的.

    参数:
        tray: 物料盘 mesh 对象
        plate_mm: (长, 宽) 板 footprint 毫米, 用于合并判据与间隙校验
        cfg: rig_map 的 sample_plates 段(读 nests / clearance_mm / min_seat_area_cm2 / probe_step_mm)
    返回值: list[dict], 每项含 center/size/seat_z(米, 世界系), 按巢中心排序
    """
    import bmesh as _bmesh
    from mathutils.bvhtree import BVHTree

    bpy.context.view_layer.update()          # 下面要读 matrix_world(硬约束 9)
    world = tray.matrix_world
    # 高度图天然假定"托盘在世界系里是轴对齐的". 这是可证伪的, 所以在这里断言而不是默认.
    basis = world.to_3x3().normalized()
    for row in basis:
        if sum(1 for v in row if abs(abs(v) - 1.0) < 1e-3) != 1:
            raise SystemExit(
                f"孔板巢实测: {tray.name} 在世界系里不是轴对齐的(旋转矩阵 {basis}) —— "
                "高度图法不成立; 需改用局部系实测后再变换")

    verts = [world @ v.co for v in tray.data.vertices]
    x0, x1 = min(v.x for v in verts), max(v.x for v in verts)
    y0, y1 = min(v.y for v in verts), max(v.y for v in verts)
    deck = max(v.z for v in verts)

    mesh = _bmesh.new()
    mesh.from_mesh(tray.data)
    mesh.transform(world)
    bvh = BVHTree.FromBMesh(mesh)
    down = Vector((0.0, 0.0, -1.0))
    step = float(cfg.get("probe_step_mm", 2.0)) / 1000.0
    eps = 0.0005

    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    surface: dict = {}
    for i in range(nx):
        for j in range(ny):
            hit = bvh.ray_cast(Vector((x0 + i * step, y0 + j * step, deck + 0.1)), down)
            if hit[0] is not None and hit[0].z < deck - eps:
                surface[(i, j)] = hit[0].z

    def clusters_at(level: float) -> list:
        """功能: 取某高度层的格子做四连通聚类. 参数: level 高度(米). 返回值: list[list[cell]]"""
        cells = {c for c, z in surface.items() if abs(z - level) < eps}
        seen, out = set(), []
        for cell in cells:
            if cell in seen:
                continue
            stack, comp = [cell], []
            seen.add(cell)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nb = (cur[0] + dx, cur[1] + dy)
                    if nb in cells and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            out.append(comp)
        return out

    cell_area_cm2 = (step * 100.0) ** 2
    min_area = float(cfg.get("min_seat_area_cm2", 40.0))
    seat_z, seat_groups = None, []
    for level in sorted({round(z, 5) for z in surface.values()}, reverse=True):
        comps = [c for c in clusters_at(level) if len(c) * cell_area_cm2 >= 4.0]
        if comps and sum(len(c) for c in comps) * cell_area_cm2 >= min_area:
            seat_z, seat_groups = level, comps
            break
    if seat_z is None:
        raise SystemExit(
            f"孔板巢实测: {tray.name} 上找不到面积 ≥{min_area}cm² 的落板台肩 —— "
            "先确认这块托盘是不是孔板载具, 再看 min_seat_area_cm2 是否过严")

    def bbox(comp: list) -> tuple:
        """功能: 聚类的世界包围盒. 参数: comp 格子列表. 返回值: (xlo, xhi, ylo, yhi)"""
        xs = [c[0] for c in comp]
        ys = [c[1] for c in comp]
        return (x0 + min(xs) * step, x0 + max(xs) * step,
                y0 + min(ys) * step, y0 + max(ys) * step)

    # --- 台肩两两并成巢 -------------------------------------------------------
    max_clear = float(cfg.get("clearance_mm", {}).get("max", 8.0)) / 1000.0
    limit = (plate_mm[0] / 1000.0 + max_clear, plate_mm[1] / 1000.0 + max_clear)
    boxes = [bbox(c) for c in seat_groups]
    changed = True
    while changed:
        changed = False
        for a in range(len(boxes)):
            for b in range(a + 1, len(boxes)):
                pa, pb = boxes[a], boxes[b]
                overlap = (pa[0] <= pb[1] and pb[0] <= pa[1]) or (pa[2] <= pb[3] and pb[2] <= pa[3])
                merged = (min(pa[0], pb[0]), max(pa[1], pb[1]),
                          min(pa[2], pb[2]), max(pa[3], pb[3]))
                fits = (merged[1] - merged[0] <= limit[0] and merged[3] - merged[2] <= limit[1])
                if overlap and fits:
                    boxes[a] = merged
                    boxes.pop(b)
                    changed = True
                    break
            if changed:
                break

    # --- 四条边细化到 0.01mm ---------------------------------------------------
    # 栅格采样出来的台肩包围盒取的是**格心**, 天然比真实边界窄最多一格(2mm) —— 实测
    # 因此把 129.0mm 的开口量成 128.0, 对 127.76 的板只剩 0.24mm 间隙而误判为"放不进去".
    # 真边界一定落在"最外那个台肩格"与"再外一格"之间, 在这个区间里二分即可.
    # 判据用"是否还在台肩平面上"而不是"是否低于台面": 巢口是 45° 导入倒角(实测 79.0 →
    # 78.0 走 1mm), 倒角面也低于台面, 拿它当边界会把开口量大 1mm; 而板裙边是坐在台肩上的,
    # 台肩的外沿才是真正卡住板的那道墙.
    def on_seat(px: float, py: float) -> bool:
        """功能: 该 XY 处的顶面是否就是落板台肩. 参数: px/py 世界坐标(米). 返回值: bool"""
        hit = bvh.ray_cast(Vector((px, py, deck + 0.1)), down)
        return hit[0] is not None and abs(hit[0].z - seat_z) < eps

    seat_cells = [c for c, z in surface.items() if abs(z - seat_z) < eps]
    refined = []
    for bx in boxes:
        members = [c for c in seat_cells
                   if bx[0] - eps <= x0 + c[0] * step <= bx[1] + eps
                   and bx[2] - eps <= y0 + c[1] * step <= bx[3] + eps]
        if not members:
            raise SystemExit("孔板巢实测: 合并后的巢里没有台肩格 —— 合并判据与聚类不自洽")
        edges = list(bx)
        for axis in (0, 1):
            for sign in (-1, 1):
                # 沿**多条**扫描线各细化一次再取中位数: 只用最外那一格会踩到圆角/让位槽,
                # 把边量偏近 1mm(实测长边因此从 129.0 报成 129.9). 中位数对这类局部特征免疫,
                # 又不会像取最内那样被圆角拽紧.
                other = 1 - axis
                lanes = sorted({c[other] for c in members})
                picks = []
                for lane in lanes[len(lanes) // 6: len(lanes) - len(lanes) // 6 or None]:
                    on_lane = [c for c in members if c[other] == lane]
                    cell = max(on_lane, key=(lambda c: c[axis] * sign))
                    fixed = (y0 if axis == 0 else x0) + lane * step
                    inside = (x0 if axis == 0 else y0) + cell[axis] * step
                    outside = inside + sign * step
                    probe0 = (inside, fixed) if axis == 0 else (fixed, inside)
                    if not on_seat(*probe0):
                        continue
                    for _ in range(20):                  # 2mm / 2^20 ≪ 0.01mm
                        mid = (inside + outside) / 2.0
                        probe = (mid, fixed) if axis == 0 else (fixed, mid)
                        if on_seat(*probe):
                            inside = mid
                        else:
                            outside = mid
                    picks.append(inside)
                if not picks:
                    raise SystemExit(
                        f"孔板巢实测: 第 {axis} 轴 {'+' if sign > 0 else '-'} 向细化取不到扫描线")
                picks.sort()
                edges[axis * 2 + (1 if sign > 0 else 0)] = picks[len(picks) // 2]
        refined.append(tuple(edges))
    boxes = refined

    nests = [{
        "center": ((bx[0] + bx[1]) / 2.0, (bx[2] + bx[3]) / 2.0),
        "size": (bx[1] - bx[0], bx[3] - bx[2]),
        "seat_z": seat_z,
    } for bx in boxes]
    # --- 盘位编号: 必须由 rig_map **显式声明**, 不许按坐标随手排 --------------------
    # 2026-08-06 事故: 这里原本是 `sort by (y, x)` 升序编号, 与控制侧 `plate_no` 毫无关联,
    # 结果编反了 —— 演示台命令 plate_no=1 却驱动到另一个巢(48 孔拟合残差 0.27 → 60.9mm)。
    # 同 [[tank-numbering-conflict]] 记的展缸编号事故: 三维自成一套编号迟早与点表对不上。
    order = cfg.get("slot_order") or {}
    key_axis = str(order.get("axis", "")).lower()
    if key_axis not in ("x", "y"):
        raise SystemExit(
            "孔板巢实测: rig_map 的 sample_plates 缺 slot_order.axis(取 x 或 y)。"
            "盘位编号必须显式声明并与控制侧 plate_no 对齐 —— 按坐标默认排序编反过一次, "
            "不再提供隐式缺省")
    idx = 0 if key_axis == "x" else 1
    desc = bool(order.get("descending", False))
    nests.sort(key=lambda n: round(n["center"][idx], 4), reverse=desc)

    want = int(cfg.get("nests", 2))
    if len(nests) != want:
        detail = "; ".join(
            f"中心({n['center'][0] * 1000:.1f},{n['center'][1] * 1000:.1f}) "
            f"开口{n['size'][0] * 1000:.1f}×{n['size'][1] * 1000:.1f}" for n in nests)
        raise SystemExit(
            f"孔板巢实测: 在 {tray.name} 上量到 {len(nests)} 个巢, 声明是 {want} 个. "
            f"实测清单: [{detail}]. 先查 CAD 里的托盘是不是换了, 再查 sample_plates.nests / "
            "clearance_mm.max 是否与实物不符")

    # 间隙校验: 板必须放得进去, 又不能旷得离谱(旷了说明认错了巢或者规格选错了)
    min_clear = float(cfg.get("clearance_mm", {}).get("min", 0.5)) / 1000.0
    for index, nest in enumerate(nests, start=1):
        for axis, plate_size in enumerate((plate_mm[0] / 1000.0, plate_mm[1] / 1000.0)):
            gap = nest["size"][axis] - plate_size
            if not (min_clear <= gap <= max_clear):
                raise SystemExit(
                    f"孔板巢 {index} 第 {axis} 轴间隙 {gap * 1000:.2f}mm 不在 "
                    f"[{min_clear * 1000:.1f}, {max_clear * 1000:.1f}] 内 "
                    f"(开口 {nest['size'][axis] * 1000:.2f}, 板 {plate_size * 1000:.2f}). "
                    "先查选的规格对不对, 再查这个巢是不是根本不是孔板位")
    log(f"孔板巢实测: {len(nests)} 个, 落板面 z={seat_z * 1000:.2f}mm, "
        + "; ".join(f"#{i} 开口 {n['size'][0] * 1000:.1f}×{n['size'][1] * 1000:.1f}"
                    f" @({n['center'][0] * 1000:.1f},{n['center'][1] * 1000:.1f})"
                    for i, n in enumerate(nests, start=1)))
    return nests


def build_sample_plates(rig_map: dict, materials_cfg: dict) -> dict:
    """
    功能: 在上样物料盘的两个巢里各摆一块 24 孔深孔板(样品液体的储存容器).

    这是"三维补上控制侧早就有的东西": sampling.aspirate 的参数是 plate_spec(默认 4×6
    = 24 孔) + plate_no(1/2 两个盘位) + well, config/calibration.yaml 也给两块板各存了
    3 点仿射标定 —— 唯独三维里盘位是空的, 针扎进一块空托盘.

    几何由 labware_geom 现算(与 gen_labware.py 出的独立数模资产同一份代数, 不读那两个
    GLB —— 免得"改了代数忘了重出资产"变成双真源). 板骑在 3Y 滑车上, 所以挂
    tray.parent 而不是挂 tray: 理由同 _attach_pump_visual —— 万一托盘将来被并掉,
    挂在它下面的板会跟着丢父级、塌回世界原点.

    时序不变量: 必须在 build_inventory_nodes 与 apply_station_alignment **之后**
    (工位平移完才量得到最终落点), 在 join_static_per_station **之前**(INV_ 前缀受保护,
    但新几何要赶在合并之前挂好自建材质). 只在 full 阶段建 —— minimal 的
    join_by_material 没有保护判定会把它并掉; raw 是装配台的 CAD 全量点选语义,
    掺进一个非 CAD 的耗材只会给删留裁决添噪声.

    参数:
        rig_map: rig_map.yaml 内容(读 sample_plates 段)
        materials_cfg: materials.yaml 全量配置(检索 MAT_LABWARE_PP 配方)
    返回值: dict, 生成统计 + 每个盘位的最终节点名与孔栅格(供 gen_twin_manifest 读, 不靠猜)
    """
    cfg = (rig_map or {}).get("sample_plates") or {}
    if not cfg or not cfg.get("enabled", True):
        log("上样孔板: rig_map 未启用, 跳过")
        return {"skipped": "disabled"}

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import labware_geom as lg

    installed = str(cfg.get("installed") or "")
    if installed not in lg.PLATE_SPECS:
        raise SystemExit(
            f"上样孔板: sample_plates.installed={installed!r} 不是已知规格 "
            f"(可选 {sorted(lg.PLATE_SPECS)})")
    spec = lg.PLATE_SPECS[installed]

    tray_name = str(cfg.get("tray") or "")
    tray = next((o for o in mesh_objects() if _base_name(o.name) == tray_name), None)
    if tray is None:
        raise SystemExit(
            f"上样孔板: 找不到物料盘 {tray_name!r}. 声明了却匹配不到一律硬失败(见 CLAUDE.md 第 31 条) —— "
            "先在 GLB 里按零件号扫一遍散落节点, 确认它是不是被删减规则误伤或改了名")

    nests = measure_plate_nests(tray, (spec["length_mm"], spec["width_mm"]), cfg)

    # --- 材质: 复用 assign_materials eager 建好的裸名实例 ------------------------
    rule = str(cfg.get("material") or "MAT_LABWARE_PP")
    recipe = None
    for section in (materials_cfg or {}).values():
        if isinstance(section, list):
            for item in section:
                if isinstance(item, dict) and item.get("name") == rule:
                    recipe = {k: v for k, v in item.items()
                              if k not in ("patterns", "parts", "cad_materials",
                                           "force_color", "native_materials")}
    if recipe is None:
        log(f"上样孔板: materials.yaml 里找不到配方 {rule}, 用兜底本色 PP")
        recipe = {"base_color": "#e0e2de", "roughness": 0.42, "metalness": 0.0}
    recipe["name"] = rule                    # 裸名共享, 别再加 _HEX 后缀(否则多一个绘制批次)
    material = build_material(recipe)

    # --- 逐巢造板 ------------------------------------------------------------
    acc = lg.build_plate(spec)
    scale = 0.001                            # labware_geom 出毫米, 场景是米
    # 板长轴对齐世界 X(= 3Y 轴向), 短轴对齐世界 Y(= 4X 轴向). 与 calibration.yaml 的
    # "列沿 3Y / 行沿 4X"同构, 也与 measure_plate_nests 量到的开口长短边一致 —— 下面断言它.
    long_axis = 0 if nests[0]["size"][0] >= nests[0]["size"][1] else 1
    if long_axis != 0:
        raise SystemExit(
            "上样孔板: 实测巢的长边不在世界 X 上, 与 labware_geom 的板长轴约定相反. "
            "别在这里悄悄转 90° —— 先核对 CAD 里托盘的摆向与 axis_3y 的 axis 向量")

    built = []
    for index, nest in enumerate(nests, start=1):
        name = f"INV_SAMPLE_PLATE_{index}"
        old = bpy.data.objects.get(name)
        if old is not None:                  # 幂等: 二次调用不叠加
            bpy.data.objects.remove(old, do_unlink=True)
        cx, cy = nest["center"]
        cz = nest["seat_z"]
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(
            [(cx + vx * scale, cy + vy * scale, cz + vz * scale) for vx, vy, vz in acc.verts],
            [], acc.faces)
        mesh.update()
        for poly, flag in zip(mesh.polygons, acc.smooth):
            poly.use_smooth = flag
        obj = bpy.data.objects.new(name, mesh)
        obj.data.materials.append(material)
        bpy.context.scene.collection.objects.link(obj)
        # 挂托盘的父级(与托盘是兄弟), 顶点已写在世界系, 故用 reparent 保世界变换
        reparent(obj, tray.parent)
        # 孔位下发给 manifest: 世界系孔心 + 逻辑地址, 前端要做孔高亮就靠它, 不必自己再算一遍
        wells = [{
            "well": label, "row": row, "col": col,
            "center": [round(cx + wx * scale, 6), round(cy + wy * scale, 6),
                       round(cz + spec["height_mm"] * scale, 6)],
        } for label, row, col, wx, wy in lg.well_centers(spec)]
        built.append({
            "slot": index, "node": name, "spec": installed,
            "nest_center_mm": [round(cx * 1000, 3), round(cy * 1000, 3)],
            "nest_size_mm": [round(nest["size"][0] * 1000, 3), round(nest["size"][1] * 1000, 3)],
            "seat_z_mm": round(cz * 1000, 3),
            "top_z_mm": round(cz * 1000 + spec["height_mm"], 3),
            "wells": wells,
        })
        log(f"上样孔板: {name} ← {spec['label']}, 落板 z={cz * 1000:.2f}mm, "
            f"顶面 z={cz * 1000 + spec['height_mm']:.2f}mm")

    # --- 净空参考件: 在这里顺手量掉, 验收脚本就不必再起一次 Blender ------------------
    # 量的是**世界包围盒**, 判据(能不能扎到孔底 / 抬起时过不过得了板顶)留给
    # verify_sample_plates.py 做纯 Python 算术 —— 测量与判断分开, 判据改了不用重跑管线.
    refs = {}
    for key, part in (cfg.get("clearance_refs") or {}).items():
        obj = next((o for o in mesh_objects() if _base_name(o.name) == str(part)), None)
        if obj is None:
            log(f"上样孔板: 净空参考件 {part!r} 未找到, 该项净空判据将被跳过")
            continue
        pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
        refs[key] = {
            "part": part,
            "min_mm": [round(min(p[i] for p in pts) * 1000, 3) for i in range(3)],
            "max_mm": [round(max(p[i] for p in pts) * 1000, 3) for i in range(3)],
        }

    return {
        "installed": installed,
        "label": spec["label"],
        "plates": len(built),
        "grid": f'{spec["rows"]}×{spec["cols"]}',
        "pitch_mm": spec["pitch_mm"],
        "well_top_mm": spec["well_top_mm"],
        "well_depth_mm": spec["well_depth_mm"],
        "height_mm": spec["height_mm"],
        "footprint_mm": [spec["length_mm"], spec["width_mm"]],
        "well_volume_ml": round(lg.well_volume_ml(spec), 3),
        "nominal_ml": spec["nominal_ml"],
        "tris_each": acc.tri_count,
        "clearance_refs": refs,
        "slots": built,
    }


def join_tank_lid_rigids() -> dict:
    """
    功能: 把每个展缸盖刚体(LINKAGE_TANK<n>_*)内部的网格按材质合并, 压低绘制调用.

    必须排在 part_groups/part_overrides 之后(合并后零件名就没了)、join_static_per_station
    之前(与静态合并同一时机语义). 只合并空对象的**直接** MESH 子级 —— LID 空对象嵌套在
    ROCKER_F 下, 递归收集会把盖并进摆杆刚体, 反转水平保持就毁了.

    参数: 无(按 LINKAGE_TANK 前缀自发现, tank_lids 未启用时自然空跑)
    返回值: dict, 合并统计与成员元数据(与 join_static_per_station 的 members 同口径)
    """
    empties = [
        obj for obj in bpy.data.objects
        if obj.type == "EMPTY" and re.match(r"^LINKAGE_TANK\d+_", obj.name)
    ]
    if not empties:
        return {"groups_merged": 0}

    merged = 0
    members: dict[str, list] = {}
    for empty in empties:
        groups: dict[str, list] = {}
        for child in list(empty.children):
            if child.type != "MESH":
                continue  # 跳过嵌套的 LID 空对象
            key = child.data.materials[0].name if child.data.materials else "NONE"
            groups.setdefault(key, []).append(child)
        for material_name, objects in groups.items():
            if len(objects) < 2:
                continue  # 单件保持原名(仍受 LINKAGE_ 祖先保护)
            member_meta = []
            for obj in objects:
                lo, hi = _mesh_world_bounds(obj)
                entry = {"name": obj.name, "tris": _object_triangles(obj)}
                if lo.x != math.inf:
                    size = hi - lo
                    entry["bbox"] = {
                        "c": _to_gl((lo + hi) / 2),
                        "s": [round(size.x, 4), round(size.z, 4), round(size.y, 4)],
                    }
                member_meta.append(entry)
            bpy.ops.object.select_all(action="DESELECT")
            for obj in objects:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = objects[0]
            bpy.ops.object.join()
            joined = bpy.context.view_layer.objects.active
            joined.name = f"{empty.name}_GEO_{material_name}"
            if joined.parent is not empty:
                reparent(joined, empty)
            members[f"{empty.name}/{joined.name}"] = member_meta
            merged += 1

    log(f"展缸盖刚体合并: {merged} 组(按材质, 只并直接子级)")
    return {"groups_merged": merged, "members": members}


def _translate_world(name: str, delta, section: str) -> float:
    """把一个对象沿**世界**向量平移 delta(Blender 轴系), 返回实际位移 mm。

    两个坑, 都踩过:

      1. `object.location` 是**父级局部系**的量, 而 delta 是世界向量。`上料架-1` 自带
         180° 绕 Y 的旋转, 它的子级(逐层搁板与 INV_* 托盘)若直接把世界向量加进 location,
         X/Z 会整个反号。所以必须先用父级世界矩阵的逆把 delta 转到局部系。
      2. 自校要校**向量**不是模长。旋转不改变模长 —— 老版本只比 `moved` 与 `expected`
         的长度, 方向反了照样"通过"。
    """
    hits = [obj for obj in bpy.data.objects if obj.name == name]
    if len(hits) != 1:
        # 显式名单未命中必须硬失败, 不能静默跳过(CLAUDE.md 第 27 条)
        fail(f"{section} 的节点 {name!r} 应唯一命中, 实际 {len(hits)} 个")
    target = hits[0]

    bpy.context.view_layer.update()
    before = target.matrix_world.translation.copy()
    scale_before = target.matrix_world.to_scale()
    local = delta if target.parent is None else (
        target.parent.matrix_world.to_3x3().inverted() @ delta)
    target.location = target.location + local
    bpy.context.view_layer.update()

    actual = target.matrix_world.translation - before
    error = (actual - delta).length * 1000.0
    if error > 0.01:
        fail(f"{name} 实际位移 {tuple(round(v * 1000, 3) for v in actual)} mm 与声明 "
             f"{tuple(round(v * 1000, 3) for v in delta)} mm 不符(偏差 {error:.3f} mm; "
             "父级有缩放或换算写错?)")
    # 只改位置, 不改尺寸(用户定的原则)。尺寸是本项目唯一独立于示教点的校验手段 ——
    # "底板底面 Y=10.00 / 沉台间隙 0.00 / 搁板 1.99" 这些结论全靠它们没被动过。
    drift = max(abs(a - b) for a, b in zip(target.matrix_world.to_scale(), scale_before))
    if drift > 1e-9:
        fail(f"{name} 的缩放被改动了({tuple(scale_before)} -> "
             f"{tuple(target.matrix_world.to_scale())}) —— 对齐只允许平移")
    return actual.length * 1000.0


def apply_station_alignment(rig_map: dict) -> dict:
    """把货架/中转工位对齐到机器人示教系, 分两段执行。

    背景与数值来源见 rig_map 里两段的注释; 数值由 `fit_station_alignment.py --fit` 从实机
    示教点解出(输出的已是可直接回填的绝对值), 本函数只负责执行。

    * `station_alignment` —— 整站**水平**平移。平移装配根即可, 子件(含 INV_* 托盘与逐孔
      耗材)按层级天然随动, 内部相对关系一点不动。竖直分量恒为 0: 三个工位的安装底板底面
      在 CAD 里全部 Y=10.00, 正好坐在 `PTLC-08-009 大面板` 上, 整体升高物理上不成立。
    * `shelf_alignment` —— **竖直**逐层平移。每条是一组节点(搁板/台面 + 该层的托盘)一起动,
      工位本体不动。中转那两条必须含 `样品架支撑轴`, 否则台面会浮在轴顶上。

    ⚠ 轴系换算: 声明值是 glTF/场景轴系(与 manifest、前端一致), Blender 是 Z 轴向上, 故按
      (x,y,z)_gltf -> (x,-z,y)_blender 换算(CLAUDE.md 第 10 条)。换错的现象是"挪了但没对齐",
      由 `fit_station_alignment.py --check` 的落位判定与**支承面门禁**在重跑后兜住。

    Args:
        rig_map: rig_map.yaml 全文

    Returns:
        执行报告(每段的平移量与命中情况)

    Raises:
        SystemExit: 声明节点未唯一命中, 或实际位移与声明不符(经 fail)
    """
    def to_blender(translate_mm) -> Vector:
        gx, gy, gz = (float(value) / 1000.0 for value in translate_mm)
        return Vector((gx, -gz, gy))

    stations = []
    for entry in (rig_map.get("station_alignment") or []):
        name = str(entry.get("node") or "")
        if abs(float(entry["translate_mm"][1])) > 1e-9:
            fail(f"station_alignment 的 {name!r} 带了竖直分量 {entry['translate_mm'][1]} mm —— "
                 "工位是拧在大面板上的, 竖直量应放进 shelf_alignment")
        delta = to_blender(entry["translate_mm"])
        moved = _translate_world(name, delta, "station_alignment")
        stations.append({"node": name, "translate_mm": list(entry["translate_mm"]),
                         "moved_mm": round(moved, 3)})
        log(f"工位摆位校正(水平): {name} 平移 {moved:.1f} mm(glTF {entry['translate_mm']})")

    shelves = []
    for entry in (rig_map.get("shelf_alignment") or []):
        label = str(entry.get("label") or "")
        delta = to_blender(entry["translate_mm"])
        nodes = [str(n) for n in (entry.get("nodes") or [])]
        if not nodes:
            fail(f"shelf_alignment 的 {label!r} 没有 nodes")
        for name in nodes:
            _translate_world(name, delta, "shelf_alignment")
        shelves.append({"label": label, "translate_mm": list(entry["translate_mm"]),
                        "nodes": len(nodes)})
        log(f"搁板高度校正: {label} 抬高 {entry['translate_mm'][1]:+.2f} mm({len(nodes)} 个节点)")

    log(f"工位摆位校正: {len(stations)} 个工位(水平) + {len(shelves)} 层(竖直)已对齐到示教系")
    return {"applied": len(stations), "stations": stations, "shelves": shelves}


def adopt_station_seats(rig_map: dict) -> dict:
    """
    功能: 按 station_seats[].adopt_into 声明, 把工位座位实例保世界变换过继进机构组.

    为什么不用 actuators[*].build.groups: `equals` 匹配会剥 .NNN 副本后缀(_plain_match),
    耗材类名字(样品瓶-*/硅胶收集-*)在货架与两个中转上都有同基名实例, 一写就多命中硬失败;
    这里按 Blender **精确名**取对象(全局唯一), 没有那个问题. 过继后:
      * 缸动件随(收集伸缩缸推瓶进出 / 升降缸带收集器落到瓶口), 与 scrape-holder 天生
        挂在 ACTUATOR_PS_ROTATE 下同款;
      * join_static_per_station 的 ACTUATOR_ 祖先前缀保护顺带覆盖其子件, 不再被静态合并;
      * 机器人取放教点(伸出态取瓶/抬起态取收集器)与三维位姿自然一致, 不需要编译期折算 ——
        座位落点(detach.dock)是父级局部位姿, 父级随机构走后对任意行程都成立.

    时序: 必须晚于全部 build_*/apply_station_alignment(位置定稿后过继才不会脱钩)、
    早于 join_static_per_station(保护要在合并前生效).

    参数:
        rig_map: rig_map.yaml 全文
    返回值: dict, 过继清单
    Raises:
        SystemExit: 声明节点/机构组不存在, 或过继后父级与 parent 断言不符(经 fail)
    """
    bpy.context.view_layer.update()
    adopted = []
    for seat in (rig_map.get("station_seats") or []):
        group_name = str(seat.get("adopt_into") or "")
        if not group_name:
            continue
        node_name = str(seat.get("node") or "")
        obj = bpy.data.objects.get(node_name)
        if obj is None:
            fail(f"station_seats 过继: 找不到节点 {node_name!r}(精确名)")
        group = bpy.data.objects.get(group_name)
        if group is None:
            fail(f"station_seats 过继: 找不到机构组 {group_name!r} —— "
                 "过继必须晚于该机构的建组步骤")
        before = obj.matrix_world.copy()
        reparent(obj, group)
        bpy.context.view_layer.update()
        drift = max(abs(a - b) for a, b in
                    zip(obj.matrix_world.translation, before.translation))
        if drift > 1e-6:
            fail(f"station_seats 过继: {node_name!r} 世界位置漂了 {drift * 1000:.3f} mm —— "
                 "reparent 应当保世界变换")
        declared = str(seat.get("parent") or "")
        if declared and (obj.parent is None or obj.parent.name != declared):
            actual = obj.parent.name if obj.parent else None
            fail(f"station_seats 过继: {node_name!r} 过继后父级是 {actual!r}, "
                 f"与 rig_map 的 parent 断言 {declared!r} 不符 —— 两处要一起改")
        adopted.append({"node": node_name, "into": group_name})
        log(f"座位过继: {node_name} -> {group_name}(保世界变换)")
    return {"adopted": adopted}


def build_station_bottle_liquid(rig_map: dict) -> dict:
    """
    功能: 按 station_seats[].liquid 声明, 在座位实例(样品瓶)腔内生成液柱几何.

    与展缸溶液槽的体素实测**刻意不同**(与 pumps 段针筒同理): 光壁玻璃瓶内腔无可测
    特征, 尺寸按 rig_map 声明(inner_diameter_mm/floor_mm/usable_depth_mm), 本函数只
    负责用瓶外形 bbox 做"声明装得进外形"的漂移守卫. 液柱是原点在底面的竖直圆柱,
    名字必须 LIQUID_ 开头(materials.yaml ^LIQUID 规则 + join 保护前缀双重要求);
    材质与展缸液面同一份 MAT_LIQUID(不透明 —— 瓶壁是 transmission 玻璃, 液柱透明
    会一起进透明队列被画到瓶外, 见 TwinBindings._bindTanks 的注释).

    挂在瓶节点下(而非工位根): 随瓶显隐(state 直写 visible 父隐子隐)、随爪
    (attach/dock 换父带着走)、随缸(瓶已过继进机构组), 三种跟随全部免费.

    参数:
        rig_map: rig_map.yaml 全文
    返回值: dict, 每个液柱的 cavity 声明与节点名(gen_twin_manifest 搬进 manifest.liquids)
    Raises:
        SystemExit: 声明尺寸装不进瓶外形, 或液柱名被占用(经 fail)
    """
    items = []
    for seat in (rig_map.get("station_seats") or []):
        liquid_cfg = seat.get("liquid") or {}
        if not bool(liquid_cfg.get("enabled", False)):
            continue
        node_name = str(seat.get("node") or "")
        bottle = bpy.data.objects.get(node_name)
        if bottle is None:
            fail(f"座位液柱: 找不到瓶节点 {node_name!r}")
        lo, hi = _mesh_world_bounds(bottle)
        if lo.x == math.inf:
            fail(f"座位液柱: {node_name!r} 没有网格几何, 量不到外形")
        size = hi - lo
        inner_d = float(liquid_cfg["inner_diameter_mm"]) / 1000.0
        floor_m = float(liquid_cfg["floor_mm"]) / 1000.0
        depth_m = float(liquid_cfg["usable_depth_mm"]) / 1000.0
        # 声明漂移守卫: 内径要小于水平外形, 底厚+可用深不得超过瓶高
        if inner_d >= min(size.x, size.y) - 1e-4:
            fail(f"座位液柱: {node_name!r} 声明内径 {inner_d * 1000:.1f}mm 不小于外径 "
                 f"{min(size.x, size.y) * 1000:.1f}mm —— rig_map 声明漂了")
        if floor_m + depth_m > size.z + 1e-6:
            fail(f"座位液柱: {node_name!r} 底厚+可用深 {(floor_m + depth_m) * 1000:.1f}mm "
                 f"超过瓶高 {size.z * 1000:.1f}mm —— rig_map 声明漂了")

        liquid_name = str(liquid_cfg.get("node") or f"LIQUID_{seat.get('seat')}")
        if not liquid_name.startswith("LIQUID"):
            fail(f"座位液柱: 节点名 {liquid_name!r} 必须以 LIQUID 开头"
                 "(材质 ^LIQUID 规则与 join 保护前缀双重要求)")
        if bpy.data.objects.get(liquid_name) is not None:
            fail(f"座位液柱: 节点名 {liquid_name!r} 已被占用")

        # 与展缸液面盒同款: 原点挪到底面, 缩放时液面"从底往上涨"; 圆柱贴瓶形
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=32, radius=0.5, depth=1.0, location=(0, 0, 0))
        cyl = bpy.context.active_object
        for vertex in cyl.data.vertices:
            vertex.co.z += 0.5
        cyl.name = liquid_name
        cyl.data.name = f"{liquid_name}_mesh"
        cyl.scale = (inner_d, inner_d, depth_m)
        cyl.location = Vector((
            (lo.x + hi.x) / 2,
            (lo.y + hi.y) / 2,
            lo.z + floor_m,
        ))
        # 与 build_tanks 同一份 MAT_LIQUID: 命名即返回已建好的那份, 规格仅兜底
        material = build_material(
            {
                "name": "MAT_LIQUID",
                "base_color": "#6fb9d8",
                "roughness": 0.08,
                "metalness": 0.0,
                "alpha": 1.0,
            }
        )
        cyl.data.materials.clear()
        cyl.data.materials.append(material)
        reparent(cyl, bottle)
        if cyl.name != liquid_name:
            fail(f"座位液柱: 期望节点名 {liquid_name!r}, Blender 实得 {cyl.name!r}(重名?)")

        area_mm2 = math.pi * (float(liquid_cfg["inner_diameter_mm"]) / 2.0) ** 2
        cavity = {
            "usable_depth_mm": round(float(liquid_cfg["usable_depth_mm"]), 3),
            "free_area_mm2": round(area_mm2, 1),
            "capacity_ml": round(area_mm2 * float(liquid_cfg["usable_depth_mm"]) / 1000.0, 2),
            "ml_per_mm": round(area_mm2 / 1000.0, 4),
        }
        items.append({
            "seat": str(seat.get("seat")),
            "attachment_id": str(seat.get("id")),
            "bottle": node_name,
            "node": cyl.name,
            "cavity": cavity,
            "exaggeration": float(liquid_cfg.get("exaggeration", 1.0)),
        })
        log(f"座位液柱: {cyl.name} 在 {node_name} 腔内 "
            f"Ø{liquid_cfg['inner_diameter_mm']}×{liquid_cfg['usable_depth_mm']}mm "
            f"容积 {cavity['capacity_ml']}mL(声明值, 非实测)")
    return {"items": items}


def build_station_powder(rig_map: dict) -> dict:
    """
    功能: 按 station_seats[].powder 声明, 在粉桶(接粉收集器)自由腔内生成粉柱几何.

    与 build_station_bottle_liquid 是同一套做法(原点挪到底面的竖直圆柱、挂在座位实例
    节点下随之显隐/换父/随机构、名字前缀受材质规则与 join 保护双重约束), 三处不同:

      1. **腔段是区间不是深度.** 粉被滤纸内衬拦在吹气头那一端(腔的 c1), 刮板工位那只
         挂 ps_rotate 翻 180° 倒粉时粉也不动 —— 故声明的是 chamber_m 两端而不是
         floor+depth. 几何按腔段**满长**建, 运行时靠 scale 表达粉量、靠 position 把
         占位区间钉在 [c1-h, c1](powderPivot.applyPowderColumn, 两条链共用同一份实现).
      2. **单位是 mm³.** cavity 键叫 capacity_mm3 / mm3_per_mm 而不是 capacity_ml /
         ml_per_mm —— 把 mm³ 喂进 levelFromMl 会立刻 NaN 而不是悄悄画错高度.
      3. **不夹瓶外形做守卫.** 粉腔是针筒里那圈滤纸**内衬的孔**(实测 Ø18.88, 而针筒
         OD 28.0), 守卫改成"内径要小于件的水平外形、腔段要落在件的轴向外形内".

    粉柱轴向按 item 局部 **+Y**: 建的是 Blender 竖直圆柱(局部 +Z), 挂到座位节点下后
    父级那一层的旋转会把它带到位 —— 与液柱同款, 这里不做任何朝向猜测.

    参数:
        rig_map: rig_map.yaml 全文
    返回值: dict, 每根粉柱的 cavity 声明与节点名(gen_twin_manifest 搬进内容物契约表)
    Raises:
        SystemExit: 声明尺寸装不进件外形, 或粉柱名被占用(经 fail)
    """
    items = []
    for seat in (rig_map.get("station_seats") or []):
        powder_cfg = seat.get("powder") or {}
        if not bool(powder_cfg.get("enabled", False)):
            continue
        node_name = str(seat.get("node") or "")
        holder = bpy.data.objects.get(node_name)
        if holder is None:
            fail(f"座位粉柱: 找不到粉桶节点 {node_name!r}")
        # 用 object_world_bounds(**含后代**)而不是 _mesh_world_bounds: 粉桶座位节点本身
        # 是个空对象, 几何全在 4 个子件(吹气头/注射器/注射器1/滤芯)上 —— 只量自身会拿到
        # 空包围盒, 守卫随即误判"没有网格几何".
        lo, hi = object_world_bounds(holder)
        if lo.x == math.inf:
            fail(f"座位粉柱: {node_name!r} 没有网格几何, 量不到外形")
        size = hi - lo
        inner_d = float(powder_cfg["inner_diameter_mm"]) / 1000.0
        chamber = powder_cfg.get("chamber_m") or []
        if len(chamber) != 2:
            fail(f"座位粉柱: {node_name!r} 的 chamber_m 必须是 [c0, c1] 两个数(米)")
        c0, c1 = float(chamber[0]), float(chamber[1])
        if c1 <= c0:
            fail(f"座位粉柱: {node_name!r} 的 chamber_m 必须 c0 < c1, 实得 [{c0}, {c1}]")
        span = c1 - c0
        # 声明漂移守卫: 内径小于件的水平外形; 腔长不超过件的轴向外形
        if inner_d >= min(size.x, size.y) - 1e-4:
            fail(f"座位粉柱: {node_name!r} 声明内径 {inner_d * 1000:.1f}mm 不小于外形 "
                 f"{min(size.x, size.y) * 1000:.1f}mm —— rig_map 声明漂了")
        if span > size.z + 1e-6:
            fail(f"座位粉柱: {node_name!r} 腔长 {span * 1000:.1f}mm 超过件高 "
                 f"{size.z * 1000:.1f}mm —— rig_map 声明漂了")

        powder_name = str(powder_cfg.get("node") or f"POWDER_{seat.get('seat')}")
        if not powder_name.startswith("POWDER"):
            fail(f"座位粉柱: 节点名 {powder_name!r} 必须以 POWDER 开头"
                 "(材质规则与 join 保护前缀双重要求)")
        if bpy.data.objects.get(powder_name) is not None:
            fail(f"座位粉柱: 节点名 {powder_name!r} 已被占用")

        # 与液柱同款: 原点挪到底面, 缩放时粉柱沿 +Z 长(运行时 scale.z 表达粉量, 位置由
        # powderPivot 把柱顶钉在 c1 —— 即从吹气头那一端往回长)
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=24, radius=0.5, depth=1.0, location=(0, 0, 0))
        cyl = bpy.context.active_object
        for vertex in cyl.data.vertices:
            vertex.co.z += 0.5
        cyl.name = powder_name
        cyl.data.name = f"{powder_name}_mesh"
        material = build_material(
            {
                "name": "MAT_POWDER",
                "base_color": "#e8e4dc",
                "roughness": 0.92,
                "metalness": 0.0,
                "alpha": 1.0,
            }
        )
        cyl.data.materials.clear()
        cyl.data.materials.append(material)
        # 先挂上再摆位, 与液柱**刻意相反**: 液柱的声明口径是世界量(瓶外形 bbox), 粉腔的
        # 声明口径是 **item 局部量**(chamber_m 就是按座位节点局部系实测的)。挂上之后直接
        # 写 location/scale 就是写局部系, 不必反算世界位 —— 也避免了 reparent 保世界变换
        # 时把父级那一层的旋转折进来。
        cyl.parent = holder
        cyl.matrix_parent_inverse.identity()
        cyl.location = Vector((0.0, 0.0, c0))
        cyl.rotation_euler = (0.0, 0.0, 0.0)
        cyl.scale = (inner_d, inner_d, span)
        bpy.context.view_layer.update()
        if cyl.name != powder_name:
            fail(f"座位粉柱: 期望节点名 {powder_name!r}, Blender 实得 {cyl.name!r}(重名?)")

        area_mm2 = math.pi * (float(powder_cfg["inner_diameter_mm"]) / 2.0) ** 2
        depth_mm = span * 1000.0
        cavity = {
            "usable_depth_mm": round(depth_mm, 3),
            "free_area_mm2": round(area_mm2, 1),
            "capacity_mm3": round(area_mm2 * depth_mm, 1),
            "mm3_per_mm": round(area_mm2, 4),
        }
        items.append({
            "seat": str(seat.get("seat")),
            "attachment_id": str(seat.get("id")),
            "holder": node_name,
            "node": cyl.name,
            "cavity": cavity,
            "chamber": {"c0": round(c0, 6), "c1": round(c1, 6)},
        })
        log(f"座位粉柱: {cyl.name} 在 {node_name} 自由腔内 "
            f"Ø{powder_cfg['inner_diameter_mm']}×{depth_mm:.1f}mm "
            f"容积 {cavity['capacity_mm3']}mm³(腔段与内径均按内衬孔实测)")
    return {"items": items}


def join_static_per_station(protect_names: set | None = None) -> dict:
    """
    功能: 在每个工位内部, 把静态几何按材质合并为 ST_<x>/STATIC_<材质> 若干对象.

    与 minimal 阶段的全场景合并不同, 这里严格按工位边界合并, 并跳过所有需要独立
    驱动的物体(展缸/液面/状态灯/运动组), 从而在压低绘制调用数的同时保住绑定能力.

    参数:
        protect_names: 额外的**精确名**保护集(自身或祖先命中即跳过合并)。来源是
            rig_map.station_seats —— 座位实例必须可独立显隐, 2026-08-06 前
            硅胶收集-1 的 4 个子件曾被并进 STATIC_MAT_POWDER_BUCKET, 显隐失效.
    返回值: dict, 合并统计
    """
    protect_names = protect_names or set()
    # TOOL_ = 可更换夹爪(attach 重挂需要独立节点); JOINT_ = 机器人关节链
    protected_prefixes = (
        "TANK_", "LIQUID", "LIGHT_STATUS", "AXIS_", "CARRIAGE", "TOOL_", "JOINT_", "CR5_",
        "ACTUATOR_", "LINKAGE_", "PAYLOAD_", "SOCKET_", "INV_",
        # POWDER 与 LIQUID 同理: 粉柱要按粉量独立缩放/按重力独立移位, 并进静态块就废了
        "POWDER",
    )

    def is_protected(obj: Any) -> bool:
        """功能: 判断对象是否需要保持独立. 参数: obj. 返回值: bool"""
        node = obj
        while node is not None:
            if node.name.startswith(protected_prefixes) or node.name in protect_names:
                return True
            node = node.parent
        return False

    station_roots = [obj for obj in bpy.data.objects if obj.name.startswith("ST_")]
    merged = 0
    adopted = 0
    # 合并块 -> 成员元数据清单 [{name, tris, bbox:{c,s}}]: 落进 report(work/
    # 03_clean_model.report.json), 材质台借此反查"这个 STATIC 块里都有谁"、按
    # 命中点×bbox 给出成员候选、按 tris 排序 —— join 之后成员身份就永远没了,
    # 只能在合并前顺手留下. bbox 坐标为 gltf-y-up(与 export_structure 同 _to_gl 口径)
    members: dict[str, list] = {}

    for root in station_roots:
        groups: dict[str, list] = {}

        def visit(node: Any) -> None:
            """功能: 收集该工位下可合并的网格. 参数: node. 返回值: None"""
            if node.type == "MESH" and not is_protected(node):
                key = node.data.materials[0].name if node.data.materials else "NONE"
                groups.setdefault(key, []).append(node)
            for child in node.children:
                visit(child)

        visit(root)

        for material_name, objects in groups.items():
            if len(objects) < 2:
                continue
            member_meta = []
            for obj in objects:
                lo, hi = _mesh_world_bounds(obj)
                entry = {"name": obj.name, "tris": _object_triangles(obj)}
                if lo.x != math.inf:
                    size = hi - lo
                    entry["bbox"] = {
                        "c": _to_gl((lo + hi) / 2),
                        # 尺寸是标量长度, 只换轴序不取负(与 export_structure 同口径)
                        "s": [round(size.x, 4), round(size.z, 4), round(size.y, 4)],
                    }
                member_meta.append(entry)
            adopted += adopt_orphans_before_join(objects)
            bpy.ops.object.select_all(action="DESELECT")
            for obj in objects:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = objects[0]
            bpy.ops.object.join()
            joined = bpy.context.view_layer.objects.active
            joined.name = f"STATIC_{material_name}"
            reparent(joined, root)
            # 键用改名后的最终名(Blender 全局重名会追加 .001, 与导出 GLB 一致)
            members[f"{root.name}/{joined.name}"] = member_meta
            merged += 1

    log(f"按工位合并静态几何: {merged} 组; 剩余网格 {len(mesh_objects())}; 过继子级 {adopted}")
    return {
        "groups_merged": merged,
        "meshes_after": len(mesh_objects()),
        "members": members,
        "orphans_adopted": adopted,
    }


def scene_stats() -> dict:
    """
    功能: 统计当前场景的网格/三角形/材质数量.
    参数: 无
    返回值: dict
    """
    triangles = 0
    for obj in mesh_objects():
        mesh = obj.data
        # 多边形可能是四边形或 n 边形, 三角化后的数量为 顶点数-2
        triangles += sum(max(len(polygon.vertices) - 2, 0) for polygon in mesh.polygons)
    return {
        "meshes": len(mesh_objects()),
        "triangles": triangles,
        "materials": len(bpy.data.materials),
        "objects": len(bpy.data.objects),
    }


def export_glb(path: str) -> None:
    """
    功能: 导出 GLB. 会按当前 Blender 版本过滤掉不支持的导出参数.
    参数:
        path: 输出 GLB 绝对路径
    返回值: None
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    desired = {
        "filepath": path,
        "export_format": "GLB",
        "export_apply": True,          # 烘焙修改器
        "export_materials": "EXPORT",
        "export_yup": True,            # glTF 约定 Y 轴向上
        "export_cameras": False,
        "export_lights": False,
        "export_animations": False,
        "export_skins": False,
        "export_morph": False,
        "export_extras": True,         # 保留自定义属性, 供后续绑定层使用
    }

    # 不同 Blender 版本导出器的参数名有增删, 这里只传当前版本认识的键
    supported = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs = {k: v for k, v in desired.items() if k in supported}
    dropped = sorted(set(desired) - set(kwargs))
    if dropped:
        log(f"提示: 当前 Blender 不支持这些导出参数, 已忽略: {dropped}")

    started = time.time()
    bpy.ops.export_scene.gltf(**kwargs)
    log(f"导出完成: {path} ({os.path.getsize(path) / 1024 / 1024:.1f} MB, {time.time() - started:.1f}s)")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> None:
    """功能: 作业主流程. 参数: 无. 返回值: None"""
    job = parse_args()
    stage = job.get("stage", "minimal")
    log(f"作业阶段: {stage}")

    # 原生 GLB 的节点名是中文, 而规则是按拼音写的; 别名表由 03 步算好传进来
    aliases = set_name_aliases(job.get("name_aliases"))
    if aliases:
        log(f"命名别名: {aliases} 条(中文名 → 拼音, 供旧规则继续匹配)")

    reset_scene()
    import_glb(job["input"])

    report: dict = {"stage": stage, "input": job["input"], "output": job["output"]}
    report["stats_imported"] = scene_stats()

    unit = normalize_units()
    report["unit"] = unit

    # 补几何要排在 prune/材质/合并之前: 补进来的对象继承原节点名, 之后与其他零件
    # 一视同仁地走完删减、赋材质、重组的全流程(否则它拿不到管线材质, 也进不了滑车)
    if job.get("restore_geometry"):
        report["restore_geometry"] = restore_missing_geometry(job["restore_geometry"])

    prune_cfg = job.get("prune") or {}
    if prune_cfg:
        report["prune"] = prune(prune_cfg)

    # 区域局部删除跟在整件删减之后: 目标零件先经历"删/留"裁决, 幸存下来再做局部切除
    if prune_cfg.get("region_delete"):
        report["region_delete"] = region_delete(prune_cfg["region_delete"])

    # raw 阶段(装配工作台)在**同一时点**只裁决不执行, 产出标红基线.
    # 时点必须与上面两行严丝合缝: 再往后 assign_materials / split_tower / 注射泵风格化
    # 都会新造对象, 那些零件在正式管线里生在 prune 之后、从不经过删减 —— 早先浏览器
    # 拿它们去套尺寸阈值, 才把注射泵的三颗指示灯误标成红的.
    if job.get("prune_preview"):
        report["prune_preview"] = write_prune_preview(job["prune_preview"])

    # 显式减面来自工作台授权, 无条件执行; 正则减面规则仍受 --decimate 开关控制
    if prune_cfg.get("explicit_decimate") or (job.get("decimate") and prune_cfg.get("decimate_rules")):
        report["decimate"] = decimate(
            prune_cfg if job.get("decimate") else {"explicit_decimate": prune_cfg.get("explicit_decimate")}
        )

    # 全阶段整机赋材质(2026-08-02 起含 raw): raw.glb 原生 735 种材质里 68.6% 是
    # 白/灰(SolidWorks 导出大多不写 baseColorFactor, glTF 默认纯白), 动作台指认/
    # 装配台原色档看着像白模. assign_materials 只 clear+append 材质槽, 不动层级
    # 与名字; 除下面的塔灯拆分外 raw 不跑 join, 点选粒度不变.
    if job.get("materials"):
        report["materials"] = assign_materials(job["materials"])

    # 三色灯拆分: 要在赋材质之后、重组/合并之前. 2026-08-02 起 raw 也跑(用户选定):
    # 实机只有中段灯罩发光, 装配台若还是整灯一个自发光节点就与正式模型对不上;
    # 代价是塔灯在装配台从 1 个可点选零件变 3 个(顶盖/灯罩/外壳).
    tower_cfg = (job.get("rig_map") or {}).get("tower_split") or {}
    if tower_cfg.get("enabled"):
        report["tower_split"] = split_tower(tower_cfg, job.get("materials") or {})

    if stage == "raw":
        # raw 阶段(装配工作台): 把 CAD 机械臂换成官方 STL, 其余零件保持全量与
        # 点选粒度(不删减/不合并/不重组, 塔灯三段拆分除外; 2026-08 起与其他阶段一样赋管线材质).
        # 臂放回 CAD 原摆放位并烘焙 home 工作姿态 —— raw 链不跑
        # build_axis_carriages/前端驱动, 用注册位+零位会导致臂悬在轨道中段且
        # 笔直朝天, 与正式视图对不上. 航插保留(装配台=全量零件).
        rig_map = job.get("rig_map") or {}
        if not rig_map:
            raise SystemExit("raw 阶段需要 rig_map.yaml, 但配置为空")
        report["robot_joints"] = build_robot_joints(
            rig_map,
            job.get("materials"),
            place_at_cad=True,
            bake_joints_deg=job.get("bake_joints_deg"),
        )
        # 注射泵外形重建: 黑壳规则已在赋材质阶段生效, 这里补铝面板/针筒/阀头等外观件.
        # raw 是装配工作台(全量点选、不合并), 可动件在这儿没人驱动, 只会给点选添噪声
        report["pump_visuals"] = build_pump_visuals(job.get("materials") or {}, movable=False, rig_map=rig_map)
        # 合页门叶改名与 full 同序(孤立清单之前): raw 不合并, 两片各自留名 DOOR_HINGE_x
        # 与 DOOR_HINGE_x.001; 与 full 用同一套键, 指认视图里也就是同一批名字.
        report["door_hinge_leaves"] = rename_door_hinge_leaves()
        # 组与零件级覆盖与 full 同序(build_* 之后), 让指认视图与正式产物观感
        # 一致; raw 无 join, 名字恒可命中. 先组后件 —— 单件覆盖压过组.
        groups_cfg = (job.get("materials") or {}).get("part_groups") or {}
        if groups_cfg:
            report["part_groups"] = apply_part_groups(groups_cfg)
        # 孤立清单夹在组与单件覆盖之间: 万一清洗漏网重叠键, 单件覆盖仍压过孤立
        iso_cfg = (job.get("materials") or {}).get("part_isolate") or []
        if iso_cfg:
            report["part_isolate"] = apply_part_isolate(iso_cfg)
        part_cfg = (job.get("materials") or {}).get("part_overrides") or {}
        if part_cfg:
            report["part_overrides"] = apply_part_overrides(part_cfg)
    elif stage == "minimal":
        # 注射泵外形重建要赶在按材质合并之前: 新几何要在 join 前挂好自建材质.
        # 不建可动件 —— 紧随其后的 join_by_material 完全没有保护判定, 建了必被并掉
        report["pump_visuals"] = build_pump_visuals(job.get("materials") or {}, movable=False, rig_map=rig_map)
        # 组与零件级覆盖要赶在按材质合并之前: 合并后名字就没了.
        # 先组后件 —— 单件覆盖压过组(后赋值覆盖材质槽)
        groups_cfg = (job.get("materials") or {}).get("part_groups") or {}
        if groups_cfg:
            report["part_groups"] = apply_part_groups(groups_cfg)
        # 孤立清单夹在组与单件覆盖之间: 万一清洗漏网重叠键, 单件覆盖仍压过孤立
        iso_cfg = (job.get("materials") or {}).get("part_isolate") or []
        if iso_cfg:
            report["part_isolate"] = apply_part_isolate(iso_cfg)
        part_cfg = (job.get("materials") or {}).get("part_overrides") or {}
        if part_cfg:
            report["part_overrides"] = apply_part_overrides(part_cfg)
        if job.get("join_by_material", True):
            # M0 只求快速看到整机: 全场景按材质合并, 把绘制调用压到材质种类数
            report["join"] = join_by_material()
    else:
        # full 阶段: 建立语义层级与可驱动结构, 这是实时绑定的前提
        rig_map = job.get("rig_map") or {}
        if not rig_map:
            raise SystemExit("full 阶段需要 rig_map.yaml, 但配置为空")

        regroup = regroup_by_rig_map(rig_map)
        report["regroup"] = {k: v for k, v in regroup.items() if k != "roots"}
        report["tanks"] = build_tanks(rig_map)
        # 展缸盖四刚体组: 必须在 build_tanks 之后(按 TANK_n 归架定层)、静态合并之前
        report["tank_lids"] = build_tank_lids(rig_map)
        report["status_lights"] = build_status_lights(rig_map, regroup["roots"])
        report["axes"] = build_axis_carriages(rig_map)
        # 主轴刀刃: 必须在 build_axis_carriages 之后 —— 父节点(钻头夹具支架装配)此时
        # 已挂进 CARRIAGE.010, reparent 保世界变换, 刀刃自然随 10Z 升降;
        # 也必须在 join_static_per_station 之前(TOOL_ 前缀受保护, 但要先建出来)。
        report["spindles"] = build_spindle_cutters(rig_map)
        # 正式减配产物: 底座电缆航插删除(装配台 raw 链保留原貌, 见 strip_base_connector)
        report["robot_joints"] = build_robot_joints(rig_map, job.get("materials"), strip_connector=True)
        report["tools"] = build_tools(rig_map)
        # 末端执行器建组必须在 build_tools 之后(成员已被认领进 TOOL_*_GEOMETRY)、
        # join_static_per_station 之前(ACTUATOR_ 前缀受保护, 但成员重挂要先完成)
        report["end_effectors"] = build_end_effector_actuators(rig_map)
        report["inventory"] = build_inventory_nodes(rig_map)
        # 工位摆位校正必须在 build_inventory_nodes 之后(此时 INV_* 已经是这些装配的子级,
        # 平移父级会带着托盘与耗材一起走)、静态合并之前(合并后就没有装配根可挪了)
        report["station_alignment"] = apply_station_alignment(rig_map)
        # 耗材孔阵导出必须在摆位校正之后: 孔心以盘根局部系登记, 此刻乘回世界系才与成品
        # GLB 一致 —— verify_staging_numbering 拿它做"件必须坐在板孔里"的双射断言。
        if job.get("report"):
            report["consumable_lattice"] = export_consumable_lattice(
                os.path.dirname(job["report"]))
        # 上样孔板必须排在 apply_station_alignment 之后: 巢的落点是实测的, 工位挪完才是终值.
        # (只在 full 建 —— 理由见函数 docstring 的时序不变量一段)
        report["sample_plates"] = build_sample_plates(rig_map, job.get("materials") or {})
        # 注射泵外形重建: 在全部 build_*(尤其 build_axis_carriages, 要靠 CARRIAGE 祖先认出
        # 上样泵)之后、静态合并之前. full 是唯一有 ST_*/CARRIAGE 层级、join 认保护前缀、
        # 且前端会绑定的阶段, 故可动柱塞组与液柱只在这里建
        report["pump_visuals"] = build_pump_visuals(job.get("materials") or {}, movable=True, rig_map=rig_map)
        # 合页门叶改名要赶在孤立清单之前(清单按新名匹配), 也要晚于 apply_station_alignment
        # —— 归属是按门板包围盒判的, 工位挪完才是终值.
        report["door_hinge_leaves"] = rename_door_hinge_leaves()
        # 组与零件级覆盖在全部 build_*(可能重命名/新造节点)之后、静态合并之前:
        # 此时底材质已定稿, 且零件仍能按名字命中. 先组后件(单件压过组).
        groups_cfg = (job.get("materials") or {}).get("part_groups") or {}
        if groups_cfg:
            report["part_groups"] = apply_part_groups(groups_cfg)
        # 孤立清单夹在组与单件覆盖之间: 万一清洗漏网重叠键, 单件覆盖仍压过孤立
        iso_cfg = (job.get("materials") or {}).get("part_isolate") or []
        if iso_cfg:
            report["part_isolate"] = apply_part_isolate(iso_cfg)
        part_cfg = (job.get("materials") or {}).get("part_overrides") or {}
        if part_cfg:
            report["part_overrides"] = apply_part_overrides(part_cfg)
        # 座位过继与瓶液柱: 晚于全部 build_*/摆位校正(位置定稿), 早于静态合并
        # (过继后 ACTUATOR_ 祖先前缀保护即生效; 液柱挂瓶下随之覆盖)
        report["station_seats_adopt"] = adopt_station_seats(rig_map)
        report["bottle_liquid"] = build_station_bottle_liquid(rig_map)
        report["station_powder"] = build_station_powder(rig_map)
        # 展缸盖刚体内部按材质合并: 在名字类覆盖之后、静态合并之前(同一时机语义)
        report["tank_lids_join"] = join_tank_lid_rigids()
        report["join"] = join_static_per_station(
            {str(seat.get("node") or "") for seat in (rig_map.get("station_seats") or [])})

        structure_path = job.get("structure")
        if structure_path:
            report["structure"] = export_structure(structure_path)

    # 外观覆盖收尾补写: 晚于一切材质创建路径(assign_materials/metal_material/泵饰件/
    # 机器人连杆/程序化孔板), 三阶段通吃; 报告里的 unused_manual_overrides 从此只剩真死键
    if job.get("materials"):
        override_post = apply_manual_override_postpass(job.get("materials") or {})
        report["manual_override_postpass"] = override_post
        report.setdefault("materials", {})["unused_manual_overrides"] = override_post["unused"]

    report["stats_final"] = scene_stats()
    export_glb(job["output"])
    report["output_mb"] = round(os.path.getsize(job["output"]) / 1024 / 1024, 2)

    report_path = job.get("report")
    if report_path:
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        log(f"报告已写入: {report_path}")

    log(
        f"完成: 网格 {report['stats_imported']['meshes']} -> {report['stats_final']['meshes']}, "
        f"三角形 {report['stats_imported']['triangles']:,} -> {report['stats_final']['triangles']:,}, "
        f"体积 {report['output_mb']} MB"
    )


if __name__ == "__main__":
    main()
