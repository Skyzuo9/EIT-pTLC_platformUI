"""
功能: 把从 SolidWorks 提取的真实材质, 经语义映射表转成管线用的 materials.yaml.

数据流:
    SolidWorks 装配体
      └─ extract_materials.py ──> work/materials_from_cad.json   (零件 -> 材质名/外观)
           └─ 本脚本 + material_semantics.yaml ──> pipeline/materials.yaml
                └─ 03_clean_model.py ──> 模型上真实的 PBR 材质

设计取舍(与用户确认过): **材质名决定物性, 颜色不直推**.
SolidWorks 里的 RGB 多半是设计过程中为了区分零件随手指的, 直接搬进演示画面会花花绿绿;
而材质名(6061 合金/304 不锈钢/亚克力)是真实物性, 用它决定金属度、粗糙度、透射率,
颜色则统一走本项目的深色控制台配色. 这样既忠实又好看.

产出的 materials.yaml 分三段, 优先级由高到低:
    functional_overrides —— 功能压过材料(状态灯是塑料做的, 但必须自发光)
    cad_materials        —— 按 SolidWorks 材质名分组的零件清单(权威)
    rules                —— 按零件名猜的旧规则, 只给没指定材质的零件兜底

用法:
    python build_materials.py
    python build_materials.py --dry-run          # 只打印, 不写文件
    python build_materials.py --report           # 打印材质分布报告

参数: 见 main() 中的 argparse 定义
返回值: 无(产出 materials.yaml)
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter

import yaml

from common import ensure_dir, load_config, log

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))

# GLB 节点名的实测截断长度. 超过这个长度的零件名进模型时会被截掉尾巴,
# 匹配材质时必须额外准备一份截断写法.
GLB_NAME_LIMIT = 47


def read_yaml(path: str) -> dict:
    """
    功能: 读取 YAML.
    参数:
        path: 文件路径
    返回值: dict; 文件不存在返回空字典
    """
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def apply_overrides(materials: dict, overrides: dict) -> dict:
    """
    功能: 把人工覆盖(材质名 -> 观感参数)盖到已生成的各材质段上.

    覆盖优先级最高: 它代表人对着实物照片调出来的结果, 应当压过任何按名字猜的规则.
    按**最终材质名**匹配, 与该材质由哪条规则产生无关, 这样不论它来自 rules /
    native_materials / 颜色直采, 调法都一样.

    参数:
        materials: 已组装好的 materials 配置(就地修改)
        overrides: {材质名: {字段: 值}}
    返回值: dict, {"section_hits": 改写段内规则条数, "passthrough": 按实例名透传条数}
    """
    if not overrides:
        return {"section_hits": 0, "passthrough": 0}

    sections = (
        "functional_overrides", "cad_transparent", "cad_materials",
        "native_materials", "rules",
    )
    hits = 0
    matched: set[str] = set()
    for section in sections:
        for entry in materials.get(section) or []:
            patch = overrides.get(entry.get("name"))
            if patch:
                entry.update(patch)
                hits += 1
                matched.add(entry.get("name"))

    default_name = (materials.get("default") or {}).get("name")
    default_patch = overrides.get(default_name)
    if default_patch:
        materials["default"].update(default_patch)
        hits += 1
        matched.add(default_name)

    # 其余键是 Blender 侧现造的**材质实例名**(现行命名 MAT_<类>_<HEX>[_Axx], 材质台
    # 写回的就是它), 不在上面任何段里, 原样透传给 blender_clean.material_for 在造
    # 材质前查一次. 不能按前缀过滤: 旧版只认已废弃的 MAT_NAT_ 命名, 结果罩板类覆盖
    # 全被静默丢弃 —— 材质台(运行时叠加)看着已生效, 重跑管线后 GLB 里却没有.
    # 键名拼错/色号已不存在的条目由 blender_clean 在烘焙收尾时统一告警.
    passthrough_patches = {
        name: patch for name, patch in overrides.items() if name not in matched
    }
    if passthrough_patches:
        materials.setdefault("native_color_passthrough", {})["overrides"] = passthrough_patches

    return {"section_hits": hits, "passthrough": len(passthrough_patches)}


"""观感字段的数值范围(与前端 overrideModel.FIELDS 同口径), 零件级覆盖与材质组共用"""
_FIELD_RANGES = {
    "roughness": (0.0, 1.0), "metalness": (0.0, 1.0), "alpha": (0.0, 1.0),
    "transmission": (0.0, 1.0), "ior": (1.0, 2.5), "emission_strength": (0.0, 12.0),
}


def _clean_patch(patch: dict) -> dict:
    """
    功能: 清洗一份观感补丁 —— 丢未知字段、校验色号、夹取值范围.

    与前端 sanitizePatch 同口径: YAML 允许手改, 一个越界的 roughness 会让零件
    "莫名其妙不对"且极难排查, 读入时统一防脏.

    参数:
        patch: {字段: 值}
    返回值: dict, 清洗后的补丁(可能为空)
    """
    entry: dict = {}
    for key, value in (patch or {}).items():
        if key in ("base_color", "emission"):
            text = str(value or "").strip()
            if re.fullmatch(r"#?[0-9a-fA-F]{6}", text):
                entry[key] = f"#{text.lstrip('#').upper()}"
            continue
        if key in _FIELD_RANGES:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            low, high = _FIELD_RANGES[key]
            entry[key] = min(high, max(low, number))
    return entry


def _clean_part_overrides(section: dict) -> dict:
    """
    功能: 清洗零件级覆盖段(part_overrides).

    参数:
        section: material_semantics.yaml 的 part_overrides 段 {零件名: {字段: 值}}
    返回值: dict, 清洗后的段(空补丁的键被丢弃)
    """
    clean: dict = {}
    for part, patch in (section or {}).items():
        if not isinstance(patch, dict):
            continue
        entry = _clean_patch(patch)
        if entry:
            clean[str(part)] = entry
    return clean


def _clean_part_isolate(section, part_overrides: dict) -> list:
    """
    功能: 清洗孤立清单段(part_isolate) —— "只脱离静态合并、不改观感"的零件名单.

    校验: 接受列表(正写法)或映射(手改成 map 时取键); 名字剥 Blender 重名后缀
    .00N(跨次运行后缀会漂移, base 名才稳定)、去空去重排序; 与 part_overrides
    重叠的键丢弃并告警 —— 单件覆盖本身就会生成专属材质而脱离合并, 两者叠加只会
    让材质名在 MAT_PART_/MAT_SOLO_ 之间摇摆, 前端寻址随之断裂.

    参数:
        section: material_semantics.yaml 的 part_isolate 段(list 或 map)
        part_overrides: 已清洗的零件级覆盖段(用于互斥裁决)
    返回值: list[str], 清洗后的名单(排序)
    """
    raw = section or []
    if isinstance(raw, dict):
        raw = list(raw.keys())
    covered = {re.sub(r"\.\d{3}$", "", str(key)) for key in (part_overrides or {})}
    clean: list = []
    for item in raw:
        text = re.sub(r"\.\d{3}$", "", str(item).strip())
        if not text or text in clean:
            continue
        if text in covered:
            log(f"警告: part_isolate 零件「{text}」已有单件覆盖(天然独立), 忽略孤立标记")
            continue
        clean.append(text)
    return sorted(clean)


def _clean_part_groups(section: dict, isolated: set | None = None) -> dict:
    """
    功能: 清洗材质组段(part_groups) —— 工程师定义的"哪些零件合并成同一种材质".

    校验: parts 必须是非空字符串列表(去重保序); 观感字段走 _clean_patch;
    跨组重复零件保留先出现的组并告警(与前端 GroupModel 单一隶属规则一致, 隶属
    按剥 .00N 的 base 名判定); 命中孤立清单的成员从组里剔除并告警(孤立优先,
    与前端"拆出自动移出组"同一裁决); 空 parts 的组丢弃.

    参数:
        section: {组名: {parts: [...], 字段...}}
        isolated: part_isolate 清洗后的 base 名集合
    返回值: dict, 清洗后的段
    """
    clean: dict = {}
    claimed: dict = {}
    isolated = isolated or set()
    for name, entry in (section or {}).items():
        if not isinstance(entry, dict):
            continue
        parts: list = []
        for part in entry.get("parts") or []:
            text = str(part).strip()
            if not text or text in parts:
                continue
            base = re.sub(r"\.\d{3}$", "", text)
            if base in isolated:
                log(f"警告: part_groups 零件「{text}」已被标记孤立, 从组「{name}」剔除(孤立优先)")
                continue
            owner = claimed.get(base)
            if owner:
                log(f"警告: part_groups 零件「{text}」同时在组「{owner}」与「{name}」, 保留前者")
                continue
            parts.append(text)
        if not parts:
            continue
        for text in parts:
            claimed[re.sub(r"\.\d{3}$", "", text)] = str(name)
        group = {"parts": parts}
        group.update(_clean_patch(entry))
        clean[str(name)] = group
    return clean


def _as_named(spec: dict) -> dict:
    """
    功能: 把语义表里用 `id` 标识的一条规格, 转成下游要的 `name` 写法.

    语义表(material_semantics.yaml)对人友好, 用 id + label; 而 blender_clean 读的是
    spec["name"]. 两边键名不一致会直接 KeyError 或把材质命名成 MAT_UNNAMED.

    参数:
        spec: 语义表里的一条规格
    返回值: dict, 以 name 开头、去掉 id/label 的规格
    """
    if not spec:
        return {}
    named = {"name": spec.get("name") or spec.get("id") or "MAT_DEFAULT"}
    named.update({k: v for k, v in spec.items() if k not in ("id", "label", "name")})
    return named


def compile_rules(rules: list[dict]) -> list[tuple[list[re.Pattern], dict]]:
    """
    功能: 把语义映射表的模式编译成正则.
    参数:
        rules: 规则列表
    返回值: list[tuple], (已编译模式列表, 规则本体)
    """
    compiled = []
    for rule in rules or []:
        patterns = []
        for pattern in rule.get("patterns", []):
            try:
                patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                log(f"警告: 忽略非法正则 {pattern!r} ({exc})")
        compiled.append((patterns, rule))
    return compiled


def match_rule(text: str, compiled: list) -> dict | None:
    """
    功能: 找出第一条命中的规则.
    参数:
        text: 待匹配文本
        compiled: compile_rules 的产出
    返回值: dict | None
    """
    if not text:
        return None
    for patterns, rule in compiled:
        if any(p.search(text) for p in patterns):
            return rule
    return None


def slugify_name(name: str) -> str:
    """
    功能: 把零件文件名转成管线里使用的 slug(与 01 步的转换保持一致).

    01 步把中文名转成了拼音, 因此这里也要转, 否则 CAD 侧的零件名与模型里的节点名对不上.

    参数:
        name: 原始名称
    返回值: str, slug
    """
    # 复用 01 步的实现, 保证两边规则完全一致 —— 各写一份迟早会漂移
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_fix_names", os.path.join(PIPELINE_DIR, "01_fix_step_names.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.slugify(name)


def build(cad_data: dict, semantics: dict, legacy: dict) -> tuple[dict, dict]:
    """
    功能: 生成 materials.yaml 的内容.
    参数:
        cad_data: extract_materials 的产出
        semantics: material_semantics.yaml
        legacy: 现有 materials.yaml(取其 rules 段作为兜底)
    返回值: tuple[dict, dict], (materials 配置, 统计报告)
    """
    material_rules = compile_rules(semantics.get("rules", []))
    override_rules = compile_rules(semantics.get("functional_overrides", []))

    # 新格式(extract_part_colors.py, 按零件文件去重)优先; 兼容旧的按组件遍历格式
    components = cad_data.get("parts") or cad_data.get("components", [])
    # SolidWorks 材质名 -> 该材质下的零件 slug 集合
    by_material: dict[str, set[str]] = {}
    # 语义材质 id -> 命中的 SolidWorks 材质名
    semantic_hits: dict[str, set[str]] = {}
    # 透明件: CAD 里 transparency > 0 的零件, 连同它们各自的实测 α.
    # 键含"原名"与"slug"两种写法, 所以条目数会多于零件数, 零件数另行计.
    transparent: dict[str, float] = {}
    transparent_files: set[str] = set()
    unmapped: Counter = Counter()
    no_material = 0

    for item in components:
        cad_material = (item.get("material") or "").strip()
        file_name = os.path.splitext(item.get("file") or "")[0]
        if not file_name:
            continue
        # 01 步只改**中文**名, 纯 ASCII 名原样透传进 GLB(连 `^` `(2)` 都保留).
        # 所以两种写法都要发出去, 否则 `_HFD12X10(CL)_b` 这类零件永远匹配不上.
        keys = {file_name, slugify_name(file_name)}
        # GLB 里的节点名被截断到 47 字符(实测: gua_ban_mo_zu_an_zhuang_xing_cai_mo_ren_an_jia_g),
        # 长名零件只能靠截断写法命中. 截断后可能与别的长名相撞, 但那两个零件在 GLB 里
        # 本来就同名, 不是本步引入的新问题.
        keys |= {key[:GLB_NAME_LIMIT] for key in list(keys) if len(key) > GLB_NAME_LIMIT}

        # 透明度是 CAD 里最可信也最影响观感的一项: 设计者特意调过才会非零.
        # 它与材质名彼此独立(门板是钣金件却是透明的), 所以单独收集、单独成段.
        appearance = item.get("appearance") or {}
        alpha = float(appearance.get("transparency") or 0.0)
        if alpha > 0.01:
            transparent_files.add(file_name)
            for key in keys:
                transparent[key] = max(transparent.get(key, 0.0), round(alpha, 3))

        if not cad_material:
            no_material += 1
            continue

        rule = match_rule(cad_material, material_rules)
        if rule is None:
            unmapped[cad_material] += 1
            continue

        by_material.setdefault(rule["id"], set()).update(keys)
        semantic_hits.setdefault(rule["id"], set()).add(cad_material)

    # -- 组装 materials.yaml -------------------------------------------------
    materials: dict = {
        "schema": "ptlc.materials/v2",
        "_generated": (
            "本文件由 build_materials.py 生成: SolidWorks 真实材质 + material_semantics.yaml.\n"
            "手工改动会在下次生成时被覆盖; 要调材质请改 material_semantics.yaml."
        ),
        "functional_overrides": [],
        "cad_transparent": [],
        "cad_materials": [],
        "rules": legacy.get("rules", []),
        # 原生外观段按**材质名**匹配(不是零件名), 所以原样带过去即可, 不需要零件清单
        "native_materials": [_as_named(rule) for rule in semantics.get("native_materials", [])],
        # 通用外观(`color-N`)的颜色直采参数
        "native_color_passthrough": semantics.get("native_color_passthrough", {}),
        # 原生 alpha<1 零件的玻璃物性模板(blender_clean 两轴算法的 glass_template)
        "glass_template": dict(semantics.get("glass_from_transparency") or {}),
        "default": _as_named(semantics.get("fallback") or legacy.get("default") or {}),
    }

    # 功能覆盖原样带过去(它按零件名匹配, 与 CAD 材质无关).
    # 键名要从 id 改成 name —— 下游 blender_clean.assign_materials 读的是 spec["name"],
    # 直接把 id 传过去会 KeyError.
    for _patterns, rule in override_rules:
        materials["functional_overrides"].append(_as_named(rule))

    # 透明段: 按 α 分档, 同档的零件合成一条, 免得每个零件一条材质把文件撑爆.
    # 档位取 0.05 宽度 —— CAD 里的 α 本来就是设计者手调的几个整数值.
    glass = semantics.get("glass_from_transparency", {})
    buckets: dict[float, list[str]] = {}
    for slug, alpha in transparent.items():
        buckets.setdefault(round(round(alpha / 0.05) * 0.05, 2), []).append(slug)
    for alpha in sorted(buckets, reverse=True):
        materials["cad_transparent"].append(
            {
                "name": f"MAT_CAD_GLASS_{int(alpha * 100):03d}",
                "base_color": glass.get("base_color", "#a8d8f0"),
                "roughness": glass.get("roughness", 0.08),
                "metalness": 0.0,
                "transmission": round(min(0.95, alpha + 0.3), 3),
                "ior": glass.get("ior", 1.46),
                # CAD 的 transparency 是"透明度", three 里的 alpha 是"不透明度", 要取反
                "alpha": round(1.0 - alpha, 3),
                "parts": sorted(buckets[alpha]),
            }
        )

    # CAD 材质段: 每种语义材质一条, 附上它覆盖的零件 slug 清单
    for _patterns, rule in material_rules:
        parts = sorted(by_material.get(rule["id"], []))
        if not parts:
            continue
        entry = {k: v for k, v in rule.items() if k not in ("patterns", "label")}
        entry["name"] = rule["id"]
        entry.pop("id", None)
        entry["cad_materials"] = sorted(semantic_hits.get(rule["id"], []))
        entry["parts"] = parts
        materials["cad_materials"].append(entry)

    # 人工覆盖最后盖上去 —— 它是人对着实物调出来的, 压过任何按名字猜的规则
    override_hits = apply_overrides(materials, semantics.get("appearance_overrides") or {})

    # 零件级覆盖原样透传给 blender_clean.apply_part_overrides: 命中零件强制生成
    # 专属材质实例 MAT_PART_<slug>, 使其脱离共享材质、在合并模型里单独成块
    part_overrides = _clean_part_overrides(semantics.get("part_overrides") or {})
    if part_overrides:
        materials["part_overrides"] = part_overrides

    # 孤立清单透传给 blender_clean.apply_part_isolate: 命中零件观感不变, 换专属
    # 实例 MAT_SOLO_<slug> 以脱离静态合并 —— 材质台「拆出为独立零件」的落点
    part_isolate = _clean_part_isolate(semantics.get("part_isolate"), part_overrides)
    if part_isolate:
        materials["part_isolate"] = part_isolate

    # 材质组透传给 blender_clean.apply_part_groups: 组内零件共享 MAT_GROUP_<slug>,
    # 按工位合并成同一 STATIC 块 —— "哪些零件合并在一起"由工程师在材质台定义
    part_groups = _clean_part_groups(semantics.get("part_groups") or {}, set(part_isolate))
    if part_groups:
        materials["part_groups"] = part_groups

    report = {
        "override_hits": override_hits,
        "part_overrides": len(part_overrides),
        "part_isolate": len(part_isolate),
        "part_groups": len(part_groups),
        "components_scanned": len(components),
        "with_material": len(components) - no_material,
        "without_material": no_material,
        "transparent_parts": len(transparent_files),
        "transparent_buckets": [
            {"alpha": entry["alpha"], "parts": len(entry["parts"])}
            for entry in materials["cad_transparent"]
        ],
        "semantic_materials": [
            {
                "id": entry["name"],
                "cad_materials": entry["cad_materials"],
                "parts": len(entry["parts"]),
            }
            for entry in materials["cad_materials"]
        ],
        "unmapped_cad_materials": [
            {"name": name, "count": count} for name, count in unmapped.most_common()
        ],
    }
    return materials, report


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    config = load_config()

    parser = argparse.ArgumentParser(description="由 SolidWorks 材质生成 materials.yaml")
    # 优先用按零件文件去重的新格式; 没有则退回早期按组件遍历的产物
    work_dir = config["paths"]["work"]
    default_input = os.path.join(work_dir, "part_colors.json")
    if not os.path.isfile(default_input):
        default_input = os.path.join(work_dir, "materials_from_cad.json")
    parser.add_argument("--input", default=default_input)
    parser.add_argument("--output", default=os.path.join(PIPELINE_DIR, "materials.yaml"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", action="store_true", help="打印详细分布")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        raise SystemExit(
            f"错误: 未找到 {args.input}\n请先运行 mcp_servers/sw_mcp/extract_part_colors.py"
        )

    with open(args.input, "r", encoding="utf-8") as handle:
        cad_data = json.load(handle)

    semantics = read_yaml(os.path.join(PIPELINE_DIR, "material_semantics.yaml"))
    if not semantics:
        raise SystemExit("错误: 未找到 material_semantics.yaml")
    legacy = read_yaml(args.output)

    materials, report = build(cad_data, semantics, legacy)

    summary = cad_data.get("summary", {})
    log(
        f"CAD 扫描: 组件 {report['components_scanned']} 个, "
        f"其中 {report['with_material']} 个有材质, {report['without_material']} 个没有"
    )
    log(f"CAD 里共有 {summary.get('distinct_materials', '?')} 种不同材质")

    if report["override_hits"]["section_hits"] or report["override_hits"]["passthrough"]:
        log(
            f"人工覆盖: {report['override_hits']['section_hits']} 条改写规则段, "
            f"{report['override_hits']['passthrough']} 条按实例名透传给 blender_clean"
        )
    if report["part_overrides"]:
        log(f"零件级覆盖: {report['part_overrides']} 条透传给 blender_clean(生成 MAT_PART_*)")
    if report["part_groups"]:
        log(f"材质组: {report['part_groups']} 组透传给 blender_clean(生成 MAT_GROUP_*, 按组合并)")

    if report["transparent_buckets"]:
        print(f"\n=== CAD 透明件 {report['transparent_parts']} 个 ===")
        for bucket in report["transparent_buckets"]:
            print(f"  不透明度 α={bucket['alpha']:<6} {bucket['parts']:>4} 个零件")

    print("\n=== 映射结果 ===")
    for item in report["semantic_materials"]:
        cad_names = ", ".join(item["cad_materials"][:4])
        more = f" 等{len(item['cad_materials'])}种" if len(item["cad_materials"]) > 4 else ""
        print(f"  {item['id']:<18} {item['parts']:>5} 个零件   ← {cad_names}{more}")

    if report["unmapped_cad_materials"]:
        print(f"\n=== 未映射的 CAD 材质({len(report['unmapped_cad_materials'])} 种) ===")
        print("(它们会退回按零件名猜; 想精确控制请补进 material_semantics.yaml)")
        for item in report["unmapped_cad_materials"][:20]:
            print(f"  {item['count']:>5}  {item['name']}")

    if args.report:
        print("\n=== CAD 原始材质分布 ===")
        for item in summary.get("materials", [])[:40]:
            print(f"  {item['count']:>5}  {item['name']}")

    if args.dry_run:
        log("--dry-run: 未写入文件")
        return

    ensure_dir(args.output)
    if os.path.isfile(args.output):
        # 生成器会整体重写, 先留一份旧的 —— 里面可能有手工调过的兜底规则
        import shutil

        shutil.copyfile(args.output, args.output + ".bak")

    with open(args.output, "w", encoding="utf-8") as handle:
        yaml.safe_dump(
            materials, handle, allow_unicode=True, sort_keys=False, width=120, default_flow_style=False
        )
    log(f"已写入: {args.output}（旧版本备份为 .bak）")


if __name__ == "__main__":
    main()
