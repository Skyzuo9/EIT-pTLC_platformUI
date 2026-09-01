"""调度方案 (ptlc.recipe/v1) — 原子流程的有序编排
==================================================
调度方案 (UI 里的"调度"层; 代码内标识符沿用 recipe) = 原子流程引用的 DAG: 每段声明脚本、
作用域 (batch|sample)、依赖 (depends_on, 缺省依赖上一段)、变量接线 (inputs 来源: ctx
样品上下文 / batch 批参数 / lit 字面量; outputs: 脚本 out 变量 -> ctx 键)。调度器按方案
为每个样品生成段作业链。**段间串/并行结构的唯一定义处**: 链式依赖=串行, 分叉=并行。

三条加载路 (同一套结构判据):
    load_recipe(path)      磁盘文件 (运行期/契约测试)
    load_recipe_text(text) YAML 文本 (文本编辑页签)
    load_recipe_doc(doc)   已解析 doc (图形化编排器直传, 前端零 YAML 依赖)
回写路: recipe_source_doc(recipe) -> 规范化源 doc (depends 显式化, 供画布画边);
       dump_recipe_yaml(doc) -> 落盘文本。

静态校验 (validate_recipe, 于批次提交 / 契约测试 / GET /api/recipes/{name}/validate 执行):
    - 每段脚本存在、validate_script 干净、flowspec.validate_flow (R1-R3) 干净;
    - scope 与 flow.sample 一致 (batch 段须 sample:none, sample 段须 sample:required);
    - DAG 无环; 依赖引用存在;
    - 位置连续性: 位移段 (from != to) 必须被依赖关系全序化, 且链上 to(k)==from(k+1);
      位置具体的非位移段, 其位置须等于它所依赖的最后一个位移段的 to;
    - 接线: inputs 键是脚本 in 变量; ctx 来源须由种子键或传递依赖的上游段 outputs 提供;
      outputs 键是脚本 out 变量。

配方是数据: 并行粒度调整 = 改配方 + 薄包装脚本, 零引擎改动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

from eit_ptlc.operation.flowspec import validate_flow
from eit_ptlc.operation.vm.schema import validate_script

RECIPE_SCHEMA = "ptlc.recipe/v1"
FLOW_SCOPES = {"batch", "sample"}
# 调度器注入的样品上下文种子键 (接线校验时视为恒可用)
SEED_CTX = frozenset({"sample_id", "save_dir", "tank"})
# 非停放位记号 (位置连续性校验中不参与链)
_NEUTRAL = {"same", "none"}


class RecipeError(ValueError):
    """配方文件结构错误 (加载期即拒)."""


@dataclass(frozen=True)
class FlowRef:
    """配方中的一段原子流程引用."""
    id: str
    script: str
    scope: str = "sample"                       # batch | sample
    depends_on: tuple[str, ...] = ()
    inputs: dict = field(default_factory=dict)   # {in变量: {ctx|batch|lit: ...}}
    outputs: dict = field(default_factory=dict)  # {out变量: ctx键}
    # 跨段物理占位账 (资源门覆盖不到的部分): occupy 声明本段 DONE 后开始占用的占位名
    # (如 scrape-holder —— 收集器带粉压在夹具里直到收集段取走), release 声明本段 DONE
    # 后清除的占位。调度器据此保证"占位未清时不派下一个 occupy 同名的段"。
    occupy: tuple[str, ...] = ()
    release: tuple[str, ...] = ()
    # 本段 DONE 后自动摄取视觉结果 (vision_output/<sample_id>/ -> experiments.db results)
    ingest_results: bool = False


@dataclass(frozen=True)
class Recipe:
    """一份并行配方."""
    name: str
    label: str
    flows: tuple[FlowRef, ...]
    # 本配方每样品消耗的耗材种类 (批次准入时逐样品 reserve_count 的依据)
    consumables: tuple[str, ...] = ()

    def flow(self, fid: str) -> FlowRef:
        for f in self.flows:
            if f.id == fid:
                return f
        raise KeyError(f"调度方案 {self.name} 无段 {fid}")

    def sample_flows(self) -> list[FlowRef]:
        return [f for f in self.flows if f.scope == "sample"]

    def batch_flows(self) -> list[FlowRef]:
        return [f for f in self.flows if f.scope == "batch"]


def load_recipe(path: str | Path) -> Recipe:
    """读取并结构校验一份配方文件 (依赖缺省补齐: 未写 depends_on 即依赖上一段)."""
    p = Path(path)
    return load_recipe_text(p.read_text(encoding="utf-8"), fallback_name=p.stem, source=str(p))


def load_recipe_text(text: str, *, fallback_name: str = "", source: str = "") -> Recipe:
    """从 YAML 文本解析并结构校验一份调度方案 (文件加载与编辑器干跑校验共用).

    fallback_name: 文本缺 name 字段时的兜底名 (文件加载传文件名; 编辑器不传 —— 文本必须自带 name)。
    source: 错误信息里的出处标注 (文件路径或空)。
    """
    where = source or fallback_name or "<text>"
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise RecipeError(f"调度方案 {where} YAML 解析失败: {exc}") from exc
    return load_recipe_doc(doc, fallback_name=fallback_name, source=source)


def load_recipe_doc(doc, *, fallback_name: str = "", source: str = "") -> Recipe:
    """从已解析的源 doc (mapping) 结构校验一份调度方案.

    图形化编排器直传 doc (前端零 YAML 依赖); 文本路径经 load_recipe_text 转调此处,
    两条路共用同一套结构判据 —— 画布存的与手写 YAML 存的必然同规矩。
    """
    where = source or fallback_name or "<doc>"
    if not isinstance(doc, dict):
        raise RecipeError(f"调度方案 {where} 根必须为 mapping")
    if doc.get("schema") != RECIPE_SCHEMA:
        raise RecipeError(f"调度方案 {where} schema 必须为 {RECIPE_SCHEMA}: {doc.get('schema')!r}")
    name = str(doc.get("name") or fallback_name)
    if not name:
        raise RecipeError(f"调度方案 {where} 缺 name 字段")
    raw_flows = doc.get("flows")
    if not isinstance(raw_flows, list) or not raw_flows:
        raise RecipeError(f"调度方案 {name} 缺 flows 列表")
    flows: list[FlowRef] = []
    seen: set[str] = set()
    prev_id: Optional[str] = None
    for i, item in enumerate(raw_flows):
        if not isinstance(item, dict):
            raise RecipeError(f"调度方案 {name} flows[{i}] 必须为 mapping")
        fid = str(item.get("id") or "")
        script = str(item.get("script") or "")
        if not fid or not script:
            raise RecipeError(f"调度方案 {name} flows[{i}] 缺 id 或 script")
        if fid in seen:
            raise RecipeError(f"调度方案 {name} 段 id 重复: {fid}")
        seen.add(fid)
        scope = str(item.get("scope", "sample"))
        if scope not in FLOW_SCOPES:
            raise RecipeError(f"调度方案 {name} 段 {fid} scope 非法: {scope}")
        if "depends_on" in item:
            deps_raw = item.get("depends_on") or []
            if not isinstance(deps_raw, list):
                raise RecipeError(f"调度方案 {name} 段 {fid} depends_on 必须为 list")
            deps = tuple(str(d) for d in deps_raw)
        else:
            deps = (prev_id,) if prev_id is not None else ()
        inputs = item.get("inputs") or {}
        outputs = item.get("outputs") or {}
        if not isinstance(inputs, dict) or not isinstance(outputs, dict):
            raise RecipeError(f"调度方案 {name} 段 {fid} inputs/outputs 必须为 mapping")
        for var, src in inputs.items():
            if not isinstance(src, dict) or len(set(src) & {"ctx", "batch", "lit"}) != 1:
                raise RecipeError(
                    f"调度方案 {name} 段 {fid} 输入 {var} 来源必须为 {{ctx|batch|lit: ...}} 之一")
        occupy = item.get("occupy") or []
        release = item.get("release") or []
        if not isinstance(occupy, list) or not isinstance(release, list):
            raise RecipeError(f"调度方案 {name} 段 {fid} occupy/release 必须为 list")
        flows.append(FlowRef(id=fid, script=script, scope=scope, depends_on=deps,
                             inputs=dict(inputs), outputs=dict(outputs),
                             occupy=tuple(str(x) for x in occupy),
                             release=tuple(str(x) for x in release),
                             ingest_results=bool(item.get("ingest_results", False))))
        prev_id = fid
    for f in flows:
        for d in f.depends_on:
            if d not in seen:
                raise RecipeError(f"调度方案 {name} 段 {f.id} 依赖不存在的段: {d}")
    # occupy/release 配平: 每个占位名的 occupy 段与 release 段必须成对且 release 传递依赖 occupy
    occupiers = {n: f.id for f in flows for n in f.occupy}
    releasers = {n: f.id for f in flows for n in f.release}
    if set(occupiers) != set(releasers):
        raise RecipeError(
            f"调度方案 {name} 占位账不配平: occupy={sorted(occupiers)} release={sorted(releasers)}")
    consumables = doc.get("consumables") or []
    if not isinstance(consumables, list):
        raise RecipeError(f"调度方案 {name} consumables 必须为 list")
    return Recipe(name=name, label=str(doc.get("label") or name), flows=tuple(flows),
                  consumables=tuple(str(c) for c in consumables))


def recipe_source_doc(recipe: Recipe) -> dict:
    """Recipe -> 规范化源 doc (图形化编排器的读侧真源).

    与磁盘文件的差别只有一处: depends_on **一律显式**。文件里省略 depends_on 表示
    "依赖上一段"(链式糖), 画布要画边就必须拿到显式上游, 故此处把糖展开。
    其余可选键 (inputs/outputs/occupy/release/ingest_results) 为空时省略, 让
    回写的 YAML 不长出一堆空壳键。
    """
    flows = []
    for f in recipe.flows:
        item: dict = {"id": f.id, "script": f.script, "scope": f.scope,
                      "depends_on": list(f.depends_on)}
        if f.inputs:
            item["inputs"] = dict(f.inputs)
        if f.outputs:
            item["outputs"] = dict(f.outputs)
        if f.occupy:
            item["occupy"] = list(f.occupy)
        if f.release:
            item["release"] = list(f.release)
        if f.ingest_results:
            item["ingest_results"] = True
        flows.append(item)
    return {"schema": RECIPE_SCHEMA, "name": recipe.name, "label": recipe.label,
            "consumables": list(recipe.consumables), "flows": flows}


def dump_recipe_yaml(doc: dict) -> str:
    """源 doc -> YAML 文本 (结构化保存的落盘形态).

    sort_keys=False 保 doc 里的键序 (schema/name/label/consumables/flows 与手写文件同序);
    allow_unicode 让中文 label 不被转义成 \\uXXXX。
    注意: 结构化回写必然丢失原文 `#` 注释 —— 编排器在首次结构化保存前会明确告知。
    """
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def topo_order(recipe: Recipe) -> list[FlowRef]:
    """Kahn 拓扑序 (稳定: 同层按声明序); 有环抛 RecipeError."""
    indeg = {f.id: 0 for f in recipe.flows}
    for f in recipe.flows:
        for d in f.depends_on:
            indeg[f.id] += 1
    order: list[FlowRef] = []
    ready = [f for f in recipe.flows if indeg[f.id] == 0]
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for f in recipe.flows:
            if cur.id in f.depends_on:
                indeg[f.id] -= 1
                if indeg[f.id] == 0:
                    ready.append(f)
    if len(order) != len(recipe.flows):
        cyclic = sorted(set(indeg) - {f.id for f in order})
        raise RecipeError(f"调度方案 {recipe.name} 依赖成环: {cyclic}")
    return order


def transitive_deps(recipe: Recipe) -> dict[str, frozenset[str]]:
    """每段的传递依赖闭包 {段id: frozenset(所有上游段id)}."""
    closure: dict[str, frozenset[str]] = {}
    for f in topo_order(recipe):
        acc: set[str] = set()
        for d in f.depends_on:
            acc.add(d)
            acc |= closure.get(d, frozenset())
        closure[f.id] = frozenset(acc)
    return closure


def _norm_loc(loc: str) -> str:
    """位置归一: tank:{var} 模板 -> 符号 tank (连续性只关心停放点类别)."""
    if isinstance(loc, str) and loc.startswith("tank:"):
        return "tank"
    return loc


def validate_recipe(recipe: Recipe, *, resolve: Callable[[str], dict], registry,
                    resource_modes: dict[str, str]) -> list[str]:
    """全量静态校验; 返回错误列表 (空=可用于批次提交)."""
    errors: list[str] = []
    docs: dict[str, dict] = {}
    for f in recipe.flows:
        try:
            docs[f.id] = resolve(f.script)
        except KeyError:
            errors.append(f"段 {f.id}: 脚本 {f.script} 不存在")
    if errors:
        return errors

    try:
        closure = transitive_deps(recipe)
        order = topo_order(recipe)
    except RecipeError as exc:
        return [str(exc)]

    # 逐段: schema + flow 树级 + scope 一致性
    for f in recipe.flows:
        doc = docs[f.id]
        for e in validate_script(doc, resource_modes=resource_modes):
            errors.append(f"段 {f.id} ({f.script}): {e}")
        for e in validate_flow(doc, resolve=resolve, registry=registry,
                               resource_modes=resource_modes):
            errors.append(f"段 {f.id}: {e}")
        flow = doc.get("flow") or {}
        sample_decl = flow.get("sample", "required")
        if f.scope == "batch" and sample_decl != "none":
            errors.append(f"段 {f.id}: scope=batch 要求 flow.sample=none, 实际 {sample_decl}")
        if f.scope == "sample" and sample_decl != "required":
            errors.append(f"段 {f.id}: scope=sample 要求 flow.sample=required, 实际 {sample_decl}")

    # 位置连续性 (仅 sample 段): 位移段全序 + 链续接 + 非位移段位置符合
    sample_order = [f for f in order if f.scope == "sample"]
    movers: list[tuple[FlowRef, str, str]] = []
    for f in sample_order:
        flow = docs[f.id].get("flow") or {}
        frm, to = _norm_loc(flow.get("from", "none")), _norm_loc(flow.get("to", "none"))
        if frm in _NEUTRAL or to in _NEUTRAL:
            continue
        if frm != to:
            movers.append((f, frm, to))
    for k in range(1, len(movers)):
        prev_f, _, prev_to = movers[k - 1]
        cur_f, cur_frm, _ = movers[k]
        if prev_f.id not in closure[cur_f.id]:
            errors.append(
                f"位移段 {prev_f.id} 与 {cur_f.id} 无依赖全序 (可能并发执行, 样品会同时"
                f"出现在两处); 请给 {cur_f.id} 加 depends_on 传递依赖 {prev_f.id}")
        if prev_to != cur_frm:
            errors.append(
                f"位置断链: 段 {prev_f.id} 终点 {prev_to} != 段 {cur_f.id} 起点 {cur_frm}")
    # 非位移但位置具体的段: 位置须等于其依赖的最后一个位移段的 to
    mover_ids = [m[0].id for m in movers]
    for f in sample_order:
        flow = docs[f.id].get("flow") or {}
        frm, to = _norm_loc(flow.get("from", "none")), _norm_loc(flow.get("to", "none"))
        if frm in _NEUTRAL or frm != to:
            continue
        upstream = [m for m in movers if m[0].id in closure[f.id]]
        expected = upstream[-1][2] if upstream else None
        if expected is not None and expected != frm:
            errors.append(
                f"段 {f.id} 声明驻留位置 {frm}, 但按依赖推演样品此时在 {expected}")
        if not upstream and mover_ids:
            errors.append(
                f"段 {f.id} 声明具体位置 {frm} 却不依赖任何位移段, 位置无法保证; "
                f"请依赖把样品送到 {frm} 的段")

    # 占位账配对: release 段必须传递依赖 occupy 段 (否则占位可能先清后占, 账目失义)
    for f in recipe.flows:
        for name_ in f.release:
            occupier = next((g for g in recipe.flows if name_ in g.occupy), None)
            if occupier is not None and occupier.id not in closure[f.id]:
                errors.append(
                    f"段 {f.id} release {name_} 但不传递依赖其 occupy 段 {occupier.id}")

    # 接线校验
    available_ctx: dict[str, set[str]] = {}
    produced: dict[str, set[str]] = {
        f.id: set((f.outputs or {}).values()) for f in recipe.flows}
    for f in order:
        avail = set(SEED_CTX)
        for up in closure[f.id]:
            avail |= produced.get(up, set())
        available_ctx[f.id] = avail
        doc = docs[f.id]
        in_vars = {v.get("name"): v for v in (doc.get("vars") or []) if v.get("io") == "in"}
        out_vars = {v.get("name") for v in (doc.get("vars") or []) if v.get("io") == "out"}
        for var, src in (f.inputs or {}).items():
            if var not in in_vars:
                errors.append(f"段 {f.id}: 接线目标 {var} 不是脚本 {f.script} 的 in 变量")
            if "ctx" in src and src["ctx"] not in avail:
                errors.append(
                    f"段 {f.id}: 输入 {var} 引用上下文键 {src['ctx']}, 但其不在种子键"
                    f"且没有任何传递依赖的上游段输出它")
        for out_var in (f.outputs or {}):
            if out_var not in out_vars:
                errors.append(f"段 {f.id}: 输出 {out_var} 不是脚本 {f.script} 的 out 变量")
    return errors
