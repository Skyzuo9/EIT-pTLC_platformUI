"""流程自动发现 —— 扫描上位机 config/operation, 列出所有可编译成动画的流程。

设计意图
--------
演示栏要"自动关联实机现有的所有流程": 新增一个流程, 演示栏自动多一条, 不改任何代码。
在此之前, 流程级片段的路线表(``PLATE_FLOW_ROUTES``/``PLATE_FLOW_TANK_ROUTES``)是硬编码
的四条 + 两组缸参数化, 加一个流程等于改一次 Python。

发现器只做三件事, 都不涉及"猜":
  1. 遍历 ``config/operation/**/*.yaml``, 跳过 ``ui.hidden``;
  2. 入参取脚本自己的 default(``clip_compiler.default_bindings``), 需要展开成多条的
     入参从 ``flow_params.yaml`` 读取值域 —— **值域不推断**, 理由见那个文件的头注释;
  3. 已被硬编码路线覆盖的 operation 让位给硬编码那条(它们的片段名是历史约定,
     被 clips/index.json 与深链引用着, 不能改名)。

编译成不成功不归发现器管: 它只产出"该编哪些", 编译与失败留痕在 sync_ptlc_robot。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

import clip_compiler


#: 发现器产出的片段名前缀。与既有的 ``plate.flow.*`` 区分开, 一眼能看出是自动发现的。
FLOW_CLIP_PREFIX = "flow"

#: 演示栏要与流程界面(/library/operation)**逐条对齐**, 那里只滤掉 ui.hidden, 所以这里
#: 也只滤 ui.hidden。helper/legacy 同样出条目 —— 它们在流程界面里看得见, 演示栏少了它们
#: 就会变成"两份清单对不上", 而对不上是没人会去核对的那种错。

#: 单个流程最多展开成多少条片段。参数域相乘会爆炸(8 缸 × 6 库位 × 3 落点 = 144),
#: 真出现这种流程时宁可少展开并如实报出来, 也不要生成上百个几乎一样的片段。
MAX_VARIANTS_PER_FLOW = 16


@dataclass(frozen=True)
class FlowSpec:
    """一个待编译的流程片段(流程 + 一组入参 = 一个片段)。"""

    clip_name: str
    label: str
    operation: str
    inputs: dict[str, Any]
    group: str = ""
    role: str = ""
    #: 起手挂的刀号(见 infer_initial_tool)。发现期推断一次, 编译期照单全收。
    tool: int = 1
    #: 展开维度, 供前端渲染下拉框: [{key, label, value}]
    variant: list[dict] = field(default_factory=list)


def load_flow_params(pipeline_dir: Path) -> dict:
    """读入参展开域声明; 文件缺失时返回空表(所有流程各编一条)。"""
    path = Path(pipeline_dir) / "flow_params.yaml"
    if not path.is_file():
        return {"params": {}, "overrides": {}}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {"params": doc.get("params") or {}, "overrides": doc.get("overrides") or {}}


def _domain_values(domain: dict) -> list[tuple[Any, str]]:
    """把一条域声明展开成 [(值, 显示名)]。"""
    if isinstance(domain.get("options"), list):
        return [(item.get("value"), str(item.get("label", item.get("value")))) for item in domain["options"]]
    span = domain.get("range")
    if isinstance(span, list) and len(span) == 2:
        low, high = int(span[0]), int(span[1])
        return [(value, str(value)) for value in range(low, high + 1)]
    return []


def _input_vars(document: dict) -> list[str]:
    """脚本声明的入参名(io: in)。"""
    return [
        str(item.get("name"))
        for item in (document.get("vars") or [])
        if item.get("io") == "in" and item.get("name")
    ]


def _coerce_override(document: dict, override: dict[str, Any]) -> dict[str, Any]:
    """按脚本声明的 type 把点名覆盖的取值转成真实类型。

    非做不可: 覆盖值一路是从**演示页面板**来的, 而 DemoView 把入参一律 String() 化了
    (为了让 <select> 的 option 匹配上)。而 clip_compiler 的 emit_station_liquid 里是
    `int(args.get(repeatFrom))` —— `int("3")` 过, **`int("3.0")` 抛 ValueError 被外层
    except 吞掉, 于是静默退回 1 轮**。用户改成 3 轮、等了二十秒、看到的还是一轮。

    与 clip_compiler._coerce_default 同款规则(FLOAT/INT/BOOL), 复用它的实现:
    把值塞成一条临时 var 声明喂进去, 两处的强转口径就不会各走各的。

    参数: document 脚本全文; override {入参名: 取值}
    返回: 强转后的新字典
    Raises:
        SystemExit: 声明为数值型却给了转不动的字符串(静默留字符串 = 后面某处静默失败)
    """
    types = {
        str(item.get("name")): str(item.get("type") or "")
        for item in (document.get("vars") or []) if item.get("name")
    }
    out: dict[str, Any] = {}
    for key, value in override.items():
        kind = types.get(key, "")
        coerced = clip_compiler._coerce_default({"default": value, "type": kind})
        if isinstance(coerced, str) and kind.upper() in ("FLOAT", "INT", "BOOL"):
            raise SystemExit(
                f"--inputs 的 {key}={value!r} 转不成声明类型 {kind}; "
                "留着字符串会让下游某处静默退回默认值")
        out[key] = coerced
    return out


def _iter_operation_files(control_root: Path):
    """遍历 config/operation 下的全部脚本文件(含未登记在 OPERATION_DIRS 的目录)。"""
    root = Path(control_root) / "config" / "operation"
    if not root.is_dir():
        return
    yield from sorted(root.glob("*.yaml"))
    for folder in sorted(item for item in root.iterdir() if item.is_dir() and not item.name.startswith(".")):
        yield from sorted(folder.glob("*.yaml"))


def covered_clips() -> dict[str, list[dict]]:
    """已被硬编码路线覆盖的 operation -> 它产出的片段列表。

    这些 operation 不走自动发现(片段名是历史约定, 被 clips/index.json 与深链引用着,
    改名会把既有链接全打断), 但演示栏仍要能播它们 —— 所以把它们的片段名与参数原样
    交出去, 让索引里带上 status:ok 而不是被当成"还没编译"。
    """
    grouped: dict[str, list[dict]] = {}
    for spec in clip_compiler.plate_route_specs():
        variant = [
            {"key": key, "label": key, "value": value, "valueLabel": str(value)}
            for key, value in sorted(spec.inputs.items())
            if isinstance(value, (int, float, str)) and not isinstance(value, bool)
        ]
        grouped.setdefault(spec.operation, []).append({
            "clipName": spec.clip_name,
            "label": spec.label,
            "variant": variant,
            "url": f"/clips/{spec.clip_name}.yaml",
        })
    return grouped


def infer_initial_tool(document: dict, control_root: Path, depth: int = 0) -> int | None:
    """流程起手挂的刀号 —— 按正文顺序找第一声 ``robot_tool_ensure(needed=字面量)``。

    为什么要有它: to_transfer_spec 此前硬编码 tool=1(起手挂玻璃吸盘), 而收集/刮板一族
    流程的第一个机器人脚本入口就是 robot_tool_ensure(needed=3, 小夹爪) —— 假设与事实不符
    时编译器会把换刀老老实实编出来(robot_tool_put 头一步 rail.ensure(4)), 于是片段开头凭空
    多出一次没人要求的换刀与一段 168→500→168 的地轨空跑。真机不会这样: 上一段收尾时刀
    本来就在腕上。"起手挂几号刀"应当从流程自己的第一声 robot_tool_ensure 读出来 —— 那正是
    脚本作者手写的显式声明(取放脚本的入口 prologue, 见 robot_scrape_holder_pick_enter)。

    只认 needed 为字面量(lit)的声明; 变量绑定的 needed 推断不动, 返回 None 让调用方回退
    1 —— 宁可保守多编一次换刀, 也不猜。只线性扫 body 顶层的 run_script(不进 if/循环分支):
    prologue 都在顶层, 而分支里的换刀本就依赖运行期状态, 不该拿来定起手态。

    Args:
        document: 已解析的 operation 文档
        control_root: 上位机仓库根(解析被引用脚本用)
        depth: 递归深度(流程 → 取放脚本 → prologue, 3 层封顶)

    Returns:
        推断的刀号; 整条链上没有任何 robot_tool_ensure 时返回 None
    """
    if depth > 3:
        return None
    for instruction in document.get("body") or []:
        if not isinstance(instruction, dict) or instruction.get("op") != "run_script":
            continue
        script = str(instruction.get("script") or "")
        if script == "robot_tool_ensure":
            needed = (instruction.get("inputs") or {}).get("needed")
            value = needed.get("lit") if isinstance(needed, dict) else None
            return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        try:
            child = clip_compiler.load_operation(control_root, script)
        except Exception:
            continue  # 引用的脚本缺失/读不了: 编译期自会硬报, 推断不替它兜底
        found = infer_initial_tool(child, control_root, depth + 1)
        if found is not None:
            return found
    return None


def _value_token(value: Any) -> str:
    """把一个入参取值变成片段名里的那一小段 —— **变体扇出与点名覆盖必须共用这一个函数**。

    两条路径各写一套的后果不是难看, 是**孤儿**: 演示页临时编出
    `flow.collect_execute.solvent_volume_ml0.30000000000000004`, 日后把 0.3 补进
    flow_params.yaml 跑全量又编出一条名字不同、内容相同的孪生片段, 而旧的那条谁也不会清理。

    规则:
      bool 先判(Python 里 bool 是 int 的子类, 顺序反了 True 会变成 "1");
      float 走 %g 归一化 —— 面板送来的 "5" 与片段里的 5.0 必须落到同一个 token,
        小数点换成 'p': '.' 虽然过得了 CLIP_NAME_RE, 但它同时是片段名的分隔符,
        `flow.x.var0.3` 读起来像多了一段;
      其余原样(取值域里的字符串如 station_id 的 spotting/scrape/waste)。

    参数: value 入参取值
    返回: 片段名片段(须满足 three_d_authoring.CLIP_NAME_RE 的 [A-Za-z0-9._-])
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}".replace(".", "p")
    return str(value)


def discover_flow_specs(
    control_root: Path,
    pipeline_dir: Path,
    overrides: Optional[dict[str, dict[str, Any]]] = None,
) -> tuple[list[FlowSpec], list[dict]]:
    """列出所有应当生成动画的流程片段。

    参数:
        control_root: 上位机仓库根(只读)
        pipeline_dir: 三维管线目录(读 flow_params.yaml)
        overrides: 点名覆盖入参 {流程名: {入参名: 值}} —— 演示页"按这组入参编这一条"走它。
            被点名的入参**退出变体扇出**(否则会被 :226 的扇出值静默覆盖掉), 但仍照常进
            片段名后缀与 variant, 于是它是货架上多出来的一条, 不会顶掉正式片段。

    返回:
        (待编译的片段规格列表, 被跳过的流程记录列表)
        跳过记录形如 {"name", "label", "group", "role", "status", "reason"} ——
        它们同样要进 flow-index.json, 否则演示栏会"少一条而没人知道为什么"。

    Raises:
        SystemExit: overrides 指到不存在的流程, 或该流程未声明的入参。
            **绝不静默忽略** —— 这个功能的全部失败模式都是沉默: 用户改了参数、等了二十秒、
            拿到一条逐位相同的片段, 然后判定"这功能是坏的"。
    """
    domains = load_flow_params(pipeline_dir)
    covered = covered_clips()
    overrides = dict(overrides or {})
    seen_names: set[str] = set()

    specs: list[FlowSpec] = []
    skipped: list[dict] = []

    for path in _iter_operation_files(control_root):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        name = str(document.get("name") or path.stem)
        seen_names.add(name)
        label = str(document.get("label") or name)
        group = path.parent.name if path.parent.name != "operation" else ""
        ui = document.get("ui") if isinstance(document.get("ui"), dict) else {}
        role = str(ui.get("role") or "")

        if ui.get("hidden") is True:
            skipped.append(_skip(name, label, group, role, "hidden", "脚本标了 ui.hidden, 流程界面也不显示"))
            continue
        if name in covered:
            entry = _skip(name, label, group, role, "ok",
                          "由既有硬编码路线生成的正式片段(片段名是历史约定, 不改名)")
            entry["clips"] = covered[name]
            skipped.append(entry)
            continue

        base = clip_compiler.default_bindings(document)
        declared = _input_vars(document)
        # 点名覆盖: 值直接进 base(与变体扇出走同一个 inputs 出口, 编译器那边
        # clip_compiler 的 bindings.update(spec.inputs) 一视同仁)
        override = dict(overrides.get(name) or {})
        unknown_vars = [key for key in override if key not in declared]
        if unknown_vars:
            raise SystemExit(
                f"--inputs 指到流程 {name!r} 未声明的入参 {sorted(unknown_vars)}; "
                f"该流程的 io:in 变量是 {declared}")
        override = _coerce_override(document, override)
        base.update(override)

        axes = []
        for var_name in declared:
            # 被点名的维度**退出扇出**: :226 的扇出值会覆盖 base, 不摘掉它 override 就被
            # 静默吃掉。语义 = "你点名的值我照办, 没点名的维度照常扇出"。
            if var_name in override:
                continue
            domain = (domains["overrides"].get(name) or {}).get(var_name) or domains["params"].get(var_name)
            if not isinstance(domain, dict):
                continue
            values = _domain_values(domain)
            if values:
                axes.append((var_name, str(domain.get("label") or var_name), values))

        combos = list(itertools.product(*[values for _key, _label, values in axes])) if axes else [()]
        if len(combos) > MAX_VARIANTS_PER_FLOW:
            skipped.append(_skip(name, label, group, role, "too-many-variants",
                                 f"参数域相乘得 {len(combos)} 个变体, 超过上限 {MAX_VARIANTS_PER_FLOW};"
                                 f" 请在 flow_params.yaml 的 overrides 里为该流程收窄取值域"))
            continue

        tool = infer_initial_tool(document, control_root) or 1
        for combo in combos:
            # 本轮每个入参的取值来源合到一张表, 再**按 declared 序**铺后缀 —— 顺序不能跟
            # "值是从扇出来的还是被点名的"走, 否则同一组取值经两条路会得到两个不同的片段名。
            chosen: dict[str, tuple[str, Any, str, bool]] = {}
            for (var_name, var_label, _values), (value, value_label) in zip(axes, combo):
                chosen[var_name] = (var_label, value, value_label, False)
            for var_name, value in override.items():
                chosen[var_name] = (var_name, value, _value_token(value), True)

            inputs = dict(base)
            variant = []
            suffix = []
            for var_name in declared:
                if var_name not in chosen:
                    continue
                var_label, value, value_label, adhoc = chosen[var_name]
                inputs[var_name] = value
                item = {"key": var_name, "label": var_label,
                        "value": value, "valueLabel": value_label}
                if adhoc:
                    # 临时片段: 下拉里标出来, 且下次全量重编会自然消失(它不在 flow_params.yaml 里)
                    item["adhoc"] = True
                variant.append(item)
                suffix.append(f"{var_name}{_value_token(value)}")
            clip_name = ".".join([FLOW_CLIP_PREFIX, name, *suffix]) if suffix else f"{FLOW_CLIP_PREFIX}.{name}"
            variant_label = " · ".join(f"{item['label']}{item['valueLabel']}" for item in variant)
            specs.append(FlowSpec(
                clip_name=clip_name,
                label=f"{label} · {variant_label}" if variant_label else label,
                operation=name,
                inputs=inputs,
                group=group,
                role=role,
                tool=tool,
                variant=variant,
            ))

    # 指到不存在的流程一律硬失败。被 covered/hidden 跳过的也算"存在"(seen_names 在过滤之前
    # 就收了), 那种情况留给调用方按"这条流程不参与编译"另行提示 —— 这里只拦拼错名字。
    missing_ops = sorted(set(overrides) - seen_names)
    if missing_ops:
        raise SystemExit(
            f"--inputs 指到不存在的流程 {missing_ops}; "
            f"流程名取脚本的 name 字段(不是文件名), 共发现 {len(seen_names)} 条")

    return specs, skipped


def _skip(name: str, label: str, group: str, role: str, status: str, reason: str) -> dict:
    return {"name": name, "label": label, "group": group, "role": role, "status": status, "reason": reason}


def to_transfer_spec(spec: FlowSpec) -> clip_compiler.TransferSpec:
    """把 FlowSpec 转成编译器吃的 TransferSpec。

    座位留空: 与 ``plate_route_specs`` 里的流程段同款 —— 板不是 GLB 里的库存节点,
    走不了 PayloadLedger 那套整板载荷交接, 板的行踪由 PLATE_POINT_SLOT 静态定出。

    tool 取发现期的推断值(见 infer_initial_tool): 此前硬编码 1, 于是收集/刮板一族
    (起手就要 3 号小夹爪)在片段开头被编出一段真机上不存在的换刀 + 地轨 168→500→168
    空跑 —— 用户看到的"收集-上料开头地轨无意义往返"正是它。
    """
    return clip_compiler.TransferSpec(
        clip_name=spec.clip_name,
        label=spec.label,
        operation=spec.operation,
        inputs=dict(spec.inputs),
        kind="plate-flow",
        source_seat="",
        dest_seat="",
        tool=spec.tool,
    )


def motion_step_count(clip: dict) -> int:
    """数一个片段里**真正驱动机构**的步数。

    ``wait`` 与 ``camera``/``highlight`` 这类不动几何的原语不算 —— 一个流程如果只剩这些,
    那它就是"无机械动作", 演示栏要如实说, 而不是让人对着一动不动的画面猜是不是坏了。
    """
    # liquid/scrape/spot/wet/pump 也是"真正驱动机构": 液面涨落、板面痕迹前沿、柱塞行程
    # 都是看得见的几何变化。曾经漏了 liquid —— 一条只画液面的流程会被 sync_ptlc_robot 按
    # motionStepCount==0 静默丢弃(当时恰好没有这种流程, 属预存隐患而非现症)。
    moving = {"axis", "joints", "robot_point", "node", "actuator", "linkage", "tool",
              "attach", "detach", "plate", "light", "liquid", "scrape", "spot", "wet",
              "pump", "pump_valve"}
    count = 0
    for step in clip.get("steps") or []:
        body = step.get("do") or {}
        if any(key in moving for key in body):
            count += 1
    return count
