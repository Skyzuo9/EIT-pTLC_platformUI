"""结构化表达式求值与变量类型系统
================================
功能:
    对 "结构化表达式 dict" 求值 (条件 / 赋值 / 参数绑定), 以及 VM 变量类型的强转与默认值.
    刻意不使用文本 DSL / eval(); 表达式由编辑器直接构造为 dict, 此处递归求值.

表达式形态 (节点为 dict):
    {lit: 值}                              字面量
    {var: 名}                              变量读 (经 read 回调按作用域解析)
    {binop: 运算符, left: 表达式, right: 表达式}   二元运算
    {unop: 运算符, operand: 表达式}         一元运算 (not / neg)
    {call: 名, args: [表达式, ...]}         白名单纯函数
    {index: 表达式, key: 表达式}            下标取值 (list/dict)
    {field: 表达式, name: 字段名}           字典字段取值
"""

from __future__ import annotations

import operator
from typing import Any, Callable

from eit_ptlc.operation.vm.errors import VmError

# VM 变量类型 (闭集)
VAR_TYPES = ("INT", "FLOAT", "STRING", "BOOL", "POSE", "LIST", "DICT")

# 二元运算符表 (and/or 单独短路处理)
_BINOPS: dict[str, Callable[[Any, Any], Any]] = {
    "+": operator.add, "-": operator.sub, "*": operator.mul,
    "/": operator.truediv, "//": operator.floordiv, "%": operator.mod,
    "==": operator.eq, "!=": operator.ne,
    ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le,
}

# 白名单纯函数 (脚本可调用的唯一函数集合)
_CALLS: dict[str, Callable[..., Any]] = {
    "len": len, "min": min, "max": max, "abs": abs, "round": round,
    "int": int, "float": float, "str": str, "bool": bool,
    "contains": lambda c, x: x in c,
    "get": lambda c, k: c.get(k) if isinstance(c, dict) else None,
}


def default_value(vtype: str) -> Any:
    """返回某 VM 类型的零值默认.

    参数:
        vtype: VAR_TYPES 之一
    返回:
        该类型的默认值
    """
    return {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOL": False,
            "POSE": [0.0] * 6, "LIST": [], "DICT": {}}.get(vtype, None)


def coerce_value(vtype: str, value: Any) -> Any:
    """把任意值强转为声明的 VM 类型; 失败抛 VmError.

    参数:
        vtype: 目标类型 (VAR_TYPES 之一)
        value: 原始值 (None 视为取默认零值)
    返回:
        强转后的值
    """
    if value is None:
        return default_value(vtype)
    try:
        if vtype == "INT":
            return int(value)
        if vtype == "FLOAT":
            return float(value)
        if vtype == "STRING":
            return str(value)
        if vtype == "BOOL":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "yes", "on")
            return bool(value)
        if vtype == "POSE":
            seq = list(value)
            if len(seq) != 6:
                raise ValueError(f"POSE 需 6 个分量, 得到 {len(seq)}")
            return [float(x) for x in seq]
        if vtype == "LIST":
            return list(value)
        if vtype == "DICT":
            return dict(value)
    except (ValueError, TypeError) as exc:
        raise VmError(f"类型强转失败: 值 {value!r} 无法转为 {vtype} ({exc})") from exc
    raise VmError(f"未知变量类型: {vtype}")


def eval_expr(node: Any, read: Callable[[str], Any]) -> Any:
    """递归求值一个结构化表达式.

    参数:
        node: 表达式 dict
        read: 变量读回调 (名 -> 值), 由 VM 按作用域提供
    返回:
        求值结果
    """
    if not isinstance(node, dict):
        raise VmError(f"表达式必须为 dict, 得到 {node!r}")

    if "lit" in node:
        return node["lit"]
    if "var" in node:
        return read(node["var"])
    if "binop" in node:
        op = node["binop"]
        if op == "and":
            left = eval_expr(node["left"], read)
            return eval_expr(node["right"], read) if left else left
        if op == "or":
            left = eval_expr(node["left"], read)
            return left if left else eval_expr(node["right"], read)
        fn = _BINOPS.get(op)
        if fn is None:
            raise VmError(f"未知二元运算符: {op}")
        return fn(eval_expr(node["left"], read), eval_expr(node["right"], read))
    if "unop" in node:
        op = node["unop"]
        val = eval_expr(node["operand"], read)
        if op == "not":
            return not val
        if op == "neg":
            return -val
        raise VmError(f"未知一元运算符: {op}")
    if "call" in node:
        name = node["call"]
        fn = _CALLS.get(name)
        if fn is None:
            raise VmError(f"不允许的函数调用: {name} (仅限 {sorted(_CALLS)})")
        args = [eval_expr(a, read) for a in node.get("args", [])]
        return fn(*args)
    if "index" in node:
        container = eval_expr(node["index"], read)
        key = eval_expr(node["key"], read)
        return container[key]
    if "field" in node:
        container = eval_expr(node["field"], read)
        return container[node["name"]]

    raise VmError(f"无法识别的表达式: {node!r}")
