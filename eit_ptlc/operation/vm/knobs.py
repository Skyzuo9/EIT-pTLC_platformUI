"""运行前旋钮 (knob) 静态收集与校验
==================================
功能:
    从一个入口 operation 文档出发, 静态遍历其 run_script 调用树, 收集所有"旋钮"
    (带 ui: 的 in var, 见 schema.is_knob_var) 供运行前预检面板展示; 以及在运行前按旋钮的
    ui 范围/枚举校验一张覆盖 map。

设计要点:
    - 旋钮判定 (is_knob_var) 与 VM 建帧注入 (thread._make_frame) 同源, 保证"面板可调集"与
      "实际可覆盖集"永远一致。
    - 覆盖按 var 名寻址 (语义具名): 同名即同一旋钮; 树中多处声明按名去重 (首现为准), 记录
      全部出现路径供展示。冲突升级 (name -> path::name) 是后续事, v1 不做。
    - 范围校验只是运行前 UX 兜底 (未跑先拒, 免机器人空跑几步才在动作处失败); 真正安全闸在
      动作层 executor._validate (调用时强制 min/max/enum/required), 故此处不追求穷尽, 覆盖
      标量 (INT/FLOAT/enum) 足矣, LIST/DICT 仅校验可强转。
"""

from __future__ import annotations

from typing import Callable

from eit_ptlc.operation.vm.errors import VmError
from eit_ptlc.operation.vm.expr import coerce_value
from eit_ptlc.operation.vm.schema import child_blocks, is_knob_var, var_enum
from eit_ptlc.value_domain import check_enum, enum_payload, normalize_enum

MAX_KNOB_DEPTH = 64  # run_script 静态下钻深度上限 (环由 visited 集拦截, 此为二次兜底)


def _iter_child_scripts(nodes: list) -> list[str]:
    """递归收集一段 body 中所有 run_script 的子脚本名 (含控制流子块内)."""
    out: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("op") == "run_script" and node.get("script"):
            out.append(node["script"])
        for _, block in child_blocks(node):
            out.extend(_iter_child_scripts(block))
    return out


def _iter_calls(nodes: list) -> list[dict]:
    """递归收集一段 body 中所有 call 节点 (含控制流子块内; 用于把旋钮关联到消费它的 action)."""
    out: list[dict] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("op") == "call" and node.get("action"):
            out.append(node)
        for _, block in child_blocks(node):
            out.extend(_iter_calls(block))
    return out


def collect_knobs(entry_doc: dict, resolve_script: Callable[[str], dict],
                  *, max_depth: int = MAX_KNOB_DEPTH,
                  resolve_action_label: Callable[[str], str] | None = None,
                  points=None) -> list[dict]:
    """静态遍历入口文档的 run_script 树, 收集全部旋钮.

    参数:
        entry_doc: 入口 operation 节点树
        resolve_script: 子脚本名 -> 节点树 (无法解析者静默跳过, 交脚本校验器另行报错)
        max_depth: 下钻深度上限
        resolve_action_label: 动作名 -> 显示 label (可选; 缺省用动作名本身)。供下钻树在
            operation → action 两级里挂动作显示名。
        points: PointsService (可选, 鸭子类型只用 .composite_entry)。给了则解析 ui.live_from
            (形如 "spot_pose.x_start") → 当前示教值, 供面板预填实时基准。缺省不解析 (离线可测)。
    返回:
        旋钮列表 [{name, type, default, ui, script, script_label, paths, actions, live}]; 按发现序、按名去重。
        actions: [{name, label}, ...] 消费该旋钮的动作 (按 call.args 里直接 {var: 旋钮名} 判定; 可空)。
        live: live_from 解析出的当前示教值 (无 live_from / 无 points / 解析失败 → None)。
    """
    knobs: dict[str, dict] = {}
    visited: set[str] = set()

    def _resolve_live(vd: dict):
        lf = (vd.get("ui") or {}).get("live_from")
        if not lf or points is None:
            return None
        try:
            comp_key, _, member_key = str(lf).partition(".")
            comp = points.composite_entry(comp_key)
            if comp is None:
                return None
            m = next((x for x in comp.members if x.key == member_key), None)
            return None if m is None else m.value
        except Exception:
            return None  # live 仅面板预填, 解析失败静默降级 (旋钮仍可用, 未覆盖走基准)

    def _attach_actions(doc: dict) -> None:
        # 关联"消费该旋钮的 action": call.args 里直接 {var: 旋钮名} 即算该 action 用到该旋钮。
        # 一个旋钮被多 action 引 → 记多个 (下钻树各挂一份, 身份仍是名)。深层表达式绑定 (罕见) 不追。
        for call in _iter_calls(doc.get("body", []) or []):
            action = call["action"]
            label = action
            if resolve_action_label is not None:
                try:
                    label = resolve_action_label(action) or action
                except Exception:
                    label = action
            for expr in (call.get("args") or {}).values():
                if isinstance(expr, dict) and "var" in expr:
                    k = knobs.get(expr["var"])
                    if k is not None:
                        entry = {"name": action, "label": label}
                        if entry not in k["actions"]:
                            k["actions"].append(entry)

    def walk(doc: dict, depth: int, path: str) -> None:
        if not isinstance(doc, dict) or depth > max_depth:
            return
        name = doc.get("name", "")
        if name in visited:
            return
        visited.add(name)
        here = f"{path} → {name}" if path else name
        for vd in doc.get("vars", []) or []:
            if not is_knob_var(vd):
                continue
            key = vd["name"]
            if key in knobs:
                knobs[key]["paths"].append(here)  # 同名旋钮多处声明: 记录出现路径, 元数据首现为准
                continue
            knobs[key] = {
                "name": key,
                "type": vd["type"],
                "default": vd.get("default"),
                "ui": dict(vd["ui"]),
                # 有限取值域 (顶层 enum, 兼容期回落 ui.enum) 规范化后随面板下发,
                # 前端 enumOf 直接消费, 免它自己再认两种写法
                "enum": enum_payload(var_enum(vd)),
                "script": name,
                "script_label": doc.get("label", name),
                "paths": [here],
                "actions": [],
                "live": _resolve_live(vd),
            }
        _attach_actions(doc)  # 本脚本的 call 已可关联到本脚本刚登记的旋钮 (in var 仅在本帧可见)
        for child_name in _iter_child_scripts(doc.get("body", []) or []):
            try:
                child = resolve_script(child_name)
            except Exception:
                continue  # 子脚本缺失/解析失败: 收集阶段容错, 不阻断面板 (真正跑到会另行报错)
            walk(child, depth + 1, here)

    walk(entry_doc, 0, "")
    return list(knobs.values())


def validate_overrides(knobs: list[dict], overrides: dict) -> list[str]:
    """运行前校验一张覆盖 map; 返回错误消息列表 (空=通过).

    校验项: 键须为已知旋钮; 值可强转为旋钮类型; 标量在 ui.min/max 内; enum 在 ui.enum 内。
    LIST/DICT 旋钮仅做类型强转校验 (逐行/结构校验交批次表 UI 与动作层)。

    参数:
        knobs: collect_knobs 的输出
        overrides: 覆盖 map (名 -> 值)
    返回:
        错误消息列表
    """
    errors: list[str] = []
    by_name = {k["name"]: k for k in knobs}
    for name, val in (overrides or {}).items():
        knob = by_name.get(name)
        if knob is None:
            errors.append(f"未知旋钮: {name}")
            continue
        try:
            cval = coerce_value(knob["type"], val)
        except VmError as exc:
            errors.append(f"旋钮 {name}: {exc}")
            continue
        ui = knob.get("ui") or {}
        if knob["type"] in ("INT", "FLOAT"):
            lo, hi = ui.get("min"), ui.get("max")
            if lo is not None and cval < lo:
                errors.append(f"旋钮 {name}={cval} 小于下限 {lo}")
            if hi is not None and cval > hi:
                errors.append(f"旋钮 {name}={cval} 超过上限 {hi}")
        # 取值域: 与裸入参走同一个成员判定 (value_domain.check_enum), 不再各写一套。
        # knob dict 里已带规范化的 enum (collect_knobs 写入); 直接传进来的 raw 旋钮
        # (测试/旧调用方) 回落到 var_enum 现算一遍。
        opts = normalize_enum(knob.get("enum")) if knob.get("enum") is not None else var_enum(knob)
        err = check_enum(opts, val, coerce=lambda v, t=knob["type"]: coerce_value(t, v))
        if err:
            errors.append(f"旋钮 {name}: {err}")
    return errors
