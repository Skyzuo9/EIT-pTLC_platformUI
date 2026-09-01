"""脚本节点树 schema 与 AID 寻址
=============================
功能:
    定义脚本节点树的 schema 常量、控制流子块结构、AID (按树位置的指令指针) 推导与反解,
    以及 validate_script (校验节点合法 / 变量引用可解析 / 动作名存在).

AID 形态 (由树位置推导, 断点/复位按位置):
    根块名为 "b"; 形如 b/3 / b/3/then/0 / b/4/body/2 / b/5/catch1/0 / b/6/br0/2.
    内部以 ((block, idx), ...) 元组表示, aid_of 序列化为字符串, resolve_aid 反解为节点.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eit_ptlc.operation.resources import MODE_EXCLUSIVE, MODE_SHARED
from eit_ptlc.operation.vm.expr import VAR_TYPES, coerce_value
from eit_ptlc.value_domain import normalize_enum

# 脚本只有 operation 一类 (动作=config/actions 原子指令, 非脚本; 见方案修订 R1)
SCRIPT_KINDS = {"operation"}
VAR_SCOPES = {"local", "global"}
VAR_IO = {"in", "out", "var", "const"}
# 变量定义的合法字段 (闭集; 未知键即报错, 见 validate_script)
#   ui   = 旋钮元数据 (label/group/min/max/scale/unit/hint/live_from); 它的"存在"即旋钮 opt-in
#   enum = 有限取值域; 与 ui 平级且与 io 正交 —— 声明它不会把变量变成旋钮
VAR_KEYS = {"name", "scope", "type", "io", "default", "comment", "ui", "enum"}
# 允许声明 enum 的 io: 运行期产物 (out/var) 声明取值域无意义且会误导 UI
ENUM_IO = {"in", "const"}
# 全部语句指令集
OPS = {
    "call", "run_script", "assign", "if", "for", "while", "repeat",
    "raise", "try", "parallel", "with_resources", "human", "comment",
}
# 叶子指令 (执行前过调试门; 控制流节点透明穿过)
LEAF_OPS = {"call", "run_script", "assign", "human"}

# 原子流程 flow: 块 (并行调度最小单元的规范化声明; 本文件只做单文件形状校验,
# 资源闭合/HITL 一致性等树级校验在 operation/flowspec.py, 于配方校验与契约测试时执行)
FLOW_KEYS = {"atomic", "sample", "from", "to", "hitl", "retry"}
FLOW_SAMPLE = {"required", "none"}
FLOW_HITL = {"none", "confirm"}
FLOW_RETRY = {"restart", "resume", "manual"}
# 停放位词表: 段边界样品必须处于的稳定位置; same=位置中立段 (整段不移动样品);
# 另支持 "tank:{var}" 模板 —— 花括号内须为本脚本声明的 INT 型 in 变量 (调度器注入缸号)
FLOW_LOCATIONS = {"feedlift", "spot_seat", "scrape_table", "waste", "none", "same"}


@dataclass(frozen=True)
class _ResRules:
    """资源声明的校验规则 (由资源表导出, 使 schema 不直接依赖 ResourceGate 实例).

    字段:
        modes: 资源名 -> 模式 (exclusive | shared)
        hooks: 被登记为 activate/deactivate 的动作名, 编排层禁止直调
    """
    modes: dict[str, str]
    hooks: frozenset


def is_knob_var(vd: dict) -> bool:
    """判定一个变量定义是否为"旋钮" (运行前可覆盖的白名单参数).

    旋钮 = io 为 in 且带 ui: 元数据块的变量。ui 的存在即 opt-in 白名单: 只有作者显式加
    ui 的 in 变量才进运行前面板、才被 overrides 注入命中, 天然排除 const/scratch(var)/out
    与未暴露的 in 变量。此单一判定同时供 VM 建帧注入 (thread._make_frame) 与静态收集
    (knobs.collect_knobs), 确保"什么是旋钮"只有一处定义。

    参数:
        vd: 变量定义 dict (来自 doc["vars"] 的一项)
    返回:
        是否为旋钮
    """
    return (
        vd.get("io") == "in" and isinstance(vd.get("ui"), dict)
        and isinstance(vd.get("name"), str) and bool(vd.get("name"))
        and isinstance(vd.get("type"), str)
    )


def var_enum(vd: dict) -> tuple:
    """读取一个变量定义的有限取值域; 无声明返回空元组.

    与 is_knob_var 并列的单一读取口: "取值域在哪读"只有这一处定义, 供入参校验
    (vm/inputs.validate_inputs)、旋钮校验 (vm/knobs.validate_overrides)、前端下发
    (collect_knobs) 与守卫测试共用。

    取值域与旋钮身份**正交**: enum 是与 ui 平级的顶层键, 声明它不会把变量变成旋钮
    (往 ui 里塞任何键都会 —— 见 is_knob_var)。这一点是刻意的: 像 rack_id / slot_id
    这类 per-call-site 的路由选择子必须留在 inputs 通道, 若变成旋钮, 线程级按名覆盖
    会把 collect_unload 里那两处取值不同的 slot_id 碾成同一个孔号。

    兼容期同时认旧的 ui.enum (仅 6 处, 迁移完成后删掉回落分支)。

    参数:
        vd: 变量定义 dict
    返回:
        EnumOption 元组; 无声明或形状非法时返回空元组 (形状问题由 validate_script 报)
    """
    if not isinstance(vd, dict):
        return ()
    raw = vd.get("enum")
    if raw is None:
        ui = vd.get("ui")
        raw = ui.get("enum") if isinstance(ui, dict) else None
    try:
        return normalize_enum(raw)
    except ValueError:
        return ()


def _validate_var_enum(vd: dict, name: str, errors: list[str]) -> None:
    """校验变量的 enum 声明: 形状 / 与 type 自洽 / 无重复 / default 落在域内 / io 合法.

    存盘即拒 —— 把"取值域写错"的暴露时机从运行期 (机器人已 home 完换完刀才抛
    ROBOT_FLOW_SELECTOR) 提前到保存脚本的那一刻。

    参数:
        vd: 变量定义 dict
        name: 变量名 (出错消息用)
        errors: 错误累积列表 (原地追加)
    """
    if "enum" not in vd:
        return
    try:
        opts = normalize_enum(vd["enum"], where=f"变量 {name}")
    except ValueError as exc:
        errors.append(str(exc))
        return
    if not opts:
        errors.append(f"变量 {name} enum 为空; 无取值域限制请删掉该字段")
        return
    io = vd.get("io", "var")
    if io not in ENUM_IO:
        errors.append(f"变量 {name} io={io} 不允许声明 enum (只允许 {sorted(ENUM_IO)})")
    vtype = vd.get("type")
    if vtype not in VAR_TYPES:
        return                       # type 本身非法已单独报过, 不再连坐
    # 每项须能强转为声明类型, 且强转后互不重复 (拦 [1, '1'] 这种看着两项实为一项)
    seen: dict = {}
    for opt in opts:
        try:
            cval = coerce_value(vtype, opt.value)
        except Exception:
            errors.append(f"变量 {name} enum 项 {opt.value!r} 无法转为 {vtype}")
            continue
        key = (type(cval).__name__, cval) if not isinstance(cval, (list, dict)) else repr(cval)
        if key in seen:
            errors.append(f"变量 {name} enum 项 {opt.value!r} 与 {seen[key]!r} 强转后重复")
        else:
            seen[key] = opt.value
    if vd.get("default") is not None:
        try:
            cdef = coerce_value(vtype, vd["default"])
        except Exception:
            return               # default 类型问题由别处负责, 不在此连坐
        if cdef not in [coerce_value(vtype, o.value) for o in opts if _coercible(vtype, o.value)]:
            errors.append(f"变量 {name} default={vd['default']!r} 不在 enum 内")


def _coercible(vtype: str, value) -> bool:
    """该值能否强转为 vtype (供 default 比对时跳过已单独报错的畸形项)."""
    try:
        coerce_value(vtype, value)
        return True
    except Exception:
        return False


def child_blocks(node: dict) -> list[tuple[str, list]]:
    """返回控制流节点的全部子块 [(块名, 节点列表), ...]; 非控制流返回空.

    参数:
        node: 语句节点
    返回:
        子块列表 (块名唯一: then/elif{n}/else/body/catch{n}/finally/br{n})
    """
    op = node.get("op")
    blocks: list[tuple[str, list]] = []
    if op == "if":
        blocks.append(("then", node.get("then", [])))
        for i, br in enumerate(node.get("elifs", [])):
            blocks.append((f"elif{i}", br.get("body", [])))
        blocks.append(("else", node.get("else", [])))
    elif op in ("for", "while", "repeat"):
        blocks.append(("body", node.get("body", [])))
    elif op == "try":
        blocks.append(("body", node.get("body", [])))
        for i, h in enumerate(node.get("catch", [])):
            blocks.append((f"catch{i}", h.get("body", [])))
        blocks.append(("finally", node.get("finally", [])))
    elif op == "parallel":
        for i, br in enumerate(node.get("branches", [])):
            blocks.append((f"br{i}", br))
    elif op == "with_resources":
        blocks.append(("body", node.get("body", [])))
    return blocks


def aid_of(path: tuple) -> str:
    """把路径元组序列化为 AID 字符串.

    参数:
        path: ((block, idx), ...) 元组, 首段 block 恒为 "b"
    返回:
        AID 字符串 (如 b/3/then/0)
    """
    return "/".join(f"{block}/{idx}" for block, idx in path)


def parse_aid(aid: str) -> tuple:
    """把 AID 字符串反解为路径元组.

    参数:
        aid: AID 字符串
    返回:
        ((block, idx), ...) 元组
    """
    segs = aid.split("/")
    if len(segs) % 2 != 0:
        raise ValueError(f"AID 段数非法: {aid}")
    return tuple((segs[i], int(segs[i + 1])) for i in range(0, len(segs), 2))


def resolve_aid(script: dict, aid: str) -> dict:
    """按 AID 在脚本树中定位节点.

    参数:
        script: 脚本文档 (含 body)
        aid: AID 字符串
    返回:
        定位到的语句节点
    """
    pairs = parse_aid(aid)
    block, idx = pairs[0]
    if block != "b":
        raise ValueError(f"AID 根段必须为 b: {aid}")
    node = script["body"][idx]
    for block, idx in pairs[1:]:
        blocks = dict(child_blocks(node))
        if block not in blocks:
            raise ValueError(f"AID 块名 {block} 不属于 op={node.get('op')}: {aid}")
        node = blocks[block][idx]
    return node


# ----------------------------------------------------------------------
# 校验
# ----------------------------------------------------------------------

def validate_script(doc: dict, *, valid_actions: set[str] | None = None,
                    resource_modes: dict[str, str] | None = None,
                    hook_actions: set[str] | None = None) -> list[str]:
    """校验脚本文档; 返回错误消息列表 (空=合法).

    校验项: 顶层字段与 kind; 变量定义合法; 节点 op 合法且必填子块为 list;
            call 的动作名存在 (若给定 valid_actions); 表达式中变量引用可解析;
            resources 声明的资源名已登记且模式合法 (若给定 resource_modes);
            call 未直调资源钩子动作 (若给定 hook_actions).

    参数:
        doc: 脚本文档 dict
        valid_actions: 合法原子动作名集合 (来自 ActionRegistry), None 则跳过动作名检查
        resource_modes: 资源名 -> 模式 (exclusive|shared), None 则跳过资源名与模式检查
        hook_actions: 被资源表登记为 activate/deactivate 的动作名, 编排层禁止直调
    返回:
        错误消息列表
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["脚本根必须为 mapping"]

    rules = None if resource_modes is None else _ResRules(
        modes=dict(resource_modes), hooks=frozenset(hook_actions or ()))
    # 脚本根 resources: 允许独占, 整条运行只获取一次
    _validate_resources(doc.get("resources"), rules, errors, "脚本根", allow_exclusive=True)

    for key in ("schema", "kind", "name", "body"):
        if key not in doc:
            errors.append(f"缺少顶层字段: {key}")
    kind = doc.get("kind")
    if kind is not None and kind not in SCRIPT_KINDS:
        errors.append(f"kind 非法: {kind!r} (合法 {sorted(SCRIPT_KINDS)})")

    # 变量定义
    declared: set[str] = set()
    int_in_vars: set[str] = set()
    for vd in doc.get("vars", []) or []:
        name = vd.get("name")
        if not name:
            errors.append("变量定义缺少 name")
            continue
        declared.add(name)
        # 键白名单: 拦未加引号的 flow 标量含逗号被劈成野键这类静默畸形
        # (如 `{comment: 步进X(mm, 可负)}` 会解析出一个名为 "可负)" 的 null 键)
        extra_keys = set(vd) - VAR_KEYS
        if extra_keys:
            errors.append(f"变量 {name} 含未知字段: {sorted(extra_keys)} "
                          f"(合法 {sorted(VAR_KEYS)}; 注释含逗号需加引号)")
        if vd.get("scope", "local") not in VAR_SCOPES:
            errors.append(f"变量 {name} scope 非法: {vd.get('scope')}")
        if vd.get("io", "var") not in VAR_IO:
            errors.append(f"变量 {name} io 非法: {vd.get('io')}")
        if vd.get("type") not in VAR_TYPES:
            errors.append(f"变量 {name} type 非法: {vd.get('type')}")
        if vd.get("io") == "in" and vd.get("type") == "INT":
            int_in_vars.add(name)
        _validate_var_enum(vd, name, errors)

    _validate_flow_block(doc.get("flow"), int_in_vars, errors)

    body = doc.get("body")
    if not isinstance(body, list):
        errors.append("body 必须为 list")
        body = []

    # 根已持独占集: 供 W1/W2 防死锁校验 (with_resources 独占区间只允许出现在根无独占的脚本)
    held = _exclusive_names(doc.get("resources"), rules)
    _validate_block(body, declared, valid_actions, errors, "b", rules, held)
    return errors


def _validate_flow_block(flow, int_in_vars: set[str], errors: list[str]) -> None:
    """校验原子流程 flow: 块的单文件形状 (键/枚举/停放位词表/组合律).

    参数:
        flow: doc["flow"] (None 表示非原子流程, 直接放行)
        int_in_vars: 本脚本声明的 INT 型 in 变量名 (tank:{var} 模板解析用)
        errors: 错误累积列表
    """
    if flow is None:
        return
    if not isinstance(flow, dict):
        errors.append("flow 必须为 mapping")
        return
    unknown = set(flow) - FLOW_KEYS
    if unknown:
        errors.append(f"flow 含未知键: {sorted(unknown)} (合法 {sorted(FLOW_KEYS)})")
    if not isinstance(flow.get("atomic", False), bool):
        errors.append(f"flow.atomic 必须为 bool: {flow.get('atomic')!r}")
    sample = flow.get("sample", "required")
    if sample not in FLOW_SAMPLE:
        errors.append(f"flow.sample 非法: {sample!r} (合法 {sorted(FLOW_SAMPLE)})")
    if flow.get("hitl", "none") not in FLOW_HITL:
        errors.append(f"flow.hitl 非法: {flow.get('hitl')!r} (合法 {sorted(FLOW_HITL)})")
    if flow.get("retry", "manual") not in FLOW_RETRY:
        errors.append(f"flow.retry 非法: {flow.get('retry')!r} (合法 {sorted(FLOW_RETRY)})")
    frm, to = flow.get("from", "none"), flow.get("to", "none")
    for key, loc in (("from", frm), ("to", to)):
        if not _flow_location_ok(loc, int_in_vars):
            errors.append(
                f"flow.{key} 非法: {loc!r} (合法 {sorted(FLOW_LOCATIONS)} 或 tank:{{INT型in变量}})")
    # 组合律: 维护型段 (sample:none) 不涉及样品位置; same 表示整段位置中立, 必须成对出现
    if sample == "none" and not (frm == "none" and to == "none"):
        errors.append("flow.sample=none 时 from/to 必须均为 none (维护型段不涉及样品位置)")
    if sample == "required" and ("none" in (frm, to)):
        errors.append("flow.sample=required 时 from/to 不得为 none")
    if ("same" in (frm, to)) and frm != to:
        errors.append("flow.from/to 使用 same 时必须成对 (same 表示整段不移动样品)")


def _flow_location_ok(loc, int_in_vars: set[str]) -> bool:
    """停放位合法性: 词表内, 或 tank:{var} 模板且 var 为本脚本 INT 型 in 变量."""
    if not isinstance(loc, str):
        return False
    if loc in FLOW_LOCATIONS:
        return True
    if loc.startswith("tank:{") and loc.endswith("}"):
        return loc[len("tank:{"):-1] in int_in_vars
    return False


def _exclusive_names(names, rules) -> frozenset:
    """从一处 resources 声明提取已登记的独占资源名集 (rules 缺失或名字未登记时不计入).

    未登记名不计入: 其本身已由 _validate_resources 报错, 再参与 W1/W2 只会产生连带噪音。
    """
    if rules is None or not isinstance(names, list):
        return frozenset()
    return frozenset(n for n in names
                     if isinstance(n, str) and rules.modes.get(n) == MODE_EXCLUSIVE)


def _validate_resources(names, rules, errors, where, *, allow_exclusive):
    """校验一处 resources 声明: 名字已登记, 且 call/parallel 节点级只允许共享资源.

    参数:
        names: resources 列表 (None 表示未声明)
        rules: _ResRules 或 None (None 则跳过资源表相关检查)
        errors: 错误累积列表
        where: 出错位置描述
        allow_exclusive: 是否允许声明独占资源 (脚本根与 with_resources 区间为 True;
                         with_resources 的独占另受 W1/W2 防死锁律约束, 见 _validate_node)
    """
    if names is None:
        return
    if not isinstance(names, list):
        errors.append(f"{where} 的 resources 必须为 list")
        return
    if rules is None:
        return
    for name in names:
        if not isinstance(name, str):
            errors.append(f"{where} 的 resources 项必须为字符串: {name!r}")
            continue
        mode = rules.modes.get(name)
        if mode is None:
            errors.append(f"{where} 引用未登记资源: {name} (须先在 config/resources.yaml 声明)")
        elif not allow_exclusive and mode != MODE_SHARED:
            errors.append(
                f"{where} 只能声明共享资源, 但 {name} 为独占资源 "
                f"(独占资源只能声明在脚本根 resources 或满足 W1/W2 的 with_resources 区间)")


def _validate_block(nodes, declared, valid_actions, errors, where, rules=None,
                    held=frozenset()):
    if not isinstance(nodes, list):
        errors.append(f"{where} 块必须为 list")
        return
    for node in nodes:
        _validate_node(node, declared, valid_actions, errors, rules, held)


def _validate_node(node, declared, valid_actions, errors, rules=None, held=frozenset()):
    if not isinstance(node, dict) or "op" not in node:
        errors.append(f"节点必须为含 op 的 mapping: {node!r}")
        return
    op = node["op"]
    if op not in OPS:
        errors.append(f"未知 op: {op}")
        return

    if op == "call":
        action = node.get("action")
        if not action:
            errors.append("call 缺少 action")
        elif valid_actions is not None and action not in valid_actions:
            errors.append(f"call 引用未知动作: {action}")
        if rules is not None and action in rules.hooks:
            errors.append(
                f"call 不能直调资源钩子动作 {action}: 该动作由资源门按引用计数驱动, "
                f"编排层请改用 with_resources 区间声明")
        _validate_resources(node.get("resources"), rules, errors, f"call({action})",
                            allow_exclusive=False)
        for expr in (node.get("args") or {}).values():
            _validate_expr(expr, declared, errors)
        _check_var_ref(node.get("assign"), declared, errors, "call.assign")
    elif op == "run_script":
        if not node.get("script"):
            errors.append("run_script 缺少 script")
        for expr in (node.get("inputs") or {}).values():
            _validate_expr(expr, declared, errors)
        for target in (node.get("outputs") or {}).values():
            _check_var_ref(target, declared, errors, "run_script.outputs")
    elif op == "assign":
        _check_var_ref(node.get("target"), declared, errors, "assign.target")
        _validate_expr(node.get("value"), declared, errors)
    elif op == "if":
        _validate_expr(node.get("cond"), declared, errors)
        _validate_block(node.get("then", []), declared, valid_actions, errors, "then", rules, held)
        for br in node.get("elifs", []):
            _validate_expr(br.get("cond"), declared, errors)
            _validate_block(br.get("body", []), declared, valid_actions, errors, "elif", rules, held)
        _validate_block(node.get("else", []), declared, valid_actions, errors, "else", rules, held)
    elif op == "for":
        if node.get("var") not in declared:
            errors.append(f"for 循环变量未声明: {node.get('var')}")
        if "in" in node:
            _validate_expr(node.get("in"), declared, errors)
        else:
            for k in ("start", "stop"):
                _validate_expr(node.get(k), declared, errors)
            if "step" in node:
                _validate_expr(node.get("step"), declared, errors)
        _validate_block(node.get("body", []), declared, valid_actions, errors, "for.body", rules, held)
    elif op == "while":
        _validate_expr(node.get("cond"), declared, errors)
        _validate_block(node.get("body", []), declared, valid_actions, errors, "while.body", rules, held)
    elif op == "repeat":
        _validate_expr(node.get("until"), declared, errors)
        _validate_block(node.get("body", []), declared, valid_actions, errors, "repeat.body", rules, held)
    elif op == "raise":
        if not node.get("error"):
            errors.append("raise 缺少 error")
        if node.get("message") is not None:
            _validate_expr(node.get("message"), declared, errors)
    elif op == "try":
        _validate_block(node.get("body", []), declared, valid_actions, errors, "try.body", rules, held)
        for h in node.get("catch", []):
            if not h.get("error"):
                errors.append("catch 缺少 error")
            _validate_block(h.get("body", []), declared, valid_actions, errors, "catch", rules, held)
        if node.get("finally"):
            _validate_block(node.get("finally"), declared, valid_actions, errors, "finally", rules, held)
    elif op == "parallel":
        _validate_resources(node.get("resources"), rules, errors, "parallel", allow_exclusive=False)
        for br in node.get("branches", []):
            _validate_block(br, declared, valid_actions, errors, "parallel.branch", rules, held)
    elif op == "with_resources":
        names = node.get("resources")
        if not names:
            errors.append("with_resources 缺少 resources")
        _validate_resources(names, rules, errors, "with_resources", allow_exclusive=True)
        # W1/W2 防死锁律: 独占区间只允许出现在"当前未持有任何独占"的上下文 (根 resources 无独占
        # 且不在独占区间内)。W1 拦自死锁 (asyncio.Lock 非重入, 重取已持名即挂死); W2 拦
        # hold-and-wait (已持独占再等独占, 两条运行互持互等即经典死锁)。共享资源不受限 (引用计数)。
        region_excl = _exclusive_names(names, rules)
        if region_excl:
            overlap = region_excl & held
            if overlap:
                errors.append(
                    f"with_resources 重复获取已持有的独占资源 {sorted(overlap)} "
                    f"(W1: asyncio.Lock 非重入, 会自死锁)")
            elif held:
                errors.append(
                    f"with_resources 在已持有独占资源 {sorted(held)} 时申请独占资源 "
                    f"{sorted(region_excl)} (W2: 禁止 hold-and-wait; 独占区间只允许出现在"
                    f"根 resources 无独占的脚本, 如展开等待段)")
        _validate_block(node.get("body", []), declared, valid_actions, errors,
                        "with_resources.body", rules, held | region_excl)
    elif op == "human":
        # choose: 多按钮门(assign_choice 取值); sketch: 手绘门(画布, values 带回 summary_path 等)
        # reanalyze: 门内重识别面板(调参重跑, values 带回 summary_path/band_id/annotated_url, 同手绘形)
        if node.get("kind") not in ("confirm", "input", "show_pic", "choose", "sketch", "reanalyze"):
            errors.append(f"human kind 非法: {node.get('kind')}")
        if node.get("prompt") is not None:
            _validate_expr(node.get("prompt"), declared, errors)
        if node.get("image") is not None:
            _validate_expr(node.get("image"), declared, errors)
        if node.get("context") is not None:
            _validate_expr(node.get("context"), declared, errors)
        _check_var_ref(node.get("assign_choice"), declared, errors, "human.assign_choice")
        for f in node.get("fields", []) or []:
            if f.get("var") not in declared:
                errors.append(f"human 字段变量未声明: {f.get('var')}")
    # comment: 无需校验


def _validate_expr(expr, declared, errors):
    """递归校验表达式结构合法且 {var} 引用已声明."""
    if not isinstance(expr, dict):
        errors.append(f"表达式必须为 dict: {expr!r}")
        return
    if "lit" in expr:
        return
    if "var" in expr:
        if expr["var"] not in declared:
            errors.append(f"表达式引用未声明变量: {expr['var']}")
        return
    if "binop" in expr:
        _validate_expr(expr.get("left"), declared, errors)
        _validate_expr(expr.get("right"), declared, errors)
        return
    if "unop" in expr:
        _validate_expr(expr.get("operand"), declared, errors)
        return
    if "call" in expr:
        for a in expr.get("args", []):
            _validate_expr(a, declared, errors)
        return
    if "index" in expr:
        _validate_expr(expr.get("index"), declared, errors)
        _validate_expr(expr.get("key"), declared, errors)
        return
    if "field" in expr:
        _validate_expr(expr.get("field"), declared, errors)
        return
    errors.append(f"无法识别的表达式: {expr!r}")


def _check_var_ref(ref, declared, errors, where):
    """校验一个 {var: 名} 引用 (用于赋值目标 / 输出绑定 / assign_choice)."""
    if ref is None:
        return
    if not isinstance(ref, dict) or "var" not in ref:
        errors.append(f"{where} 必须为 {{var: 名}}: {ref!r}")
        return
    if ref["var"] not in declared:
        errors.append(f"{where} 引用未声明变量: {ref['var']}")
