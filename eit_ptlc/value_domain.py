"""有限取值域 (enum) 的规范化与成员校验
=====================================
功能:
    把 YAML 里声明的"这个参数只能取这几个值"统一成一种形状, 供三处消费方共用:
    脚本裸入参 (operation/vm/inputs.py)、脚本旋钮 (operation/vm/knobs.py)、
    动作参数 (action/registry.py)。

为什么放在包顶层:
    action/ 与 operation/ 目前互不 import (两套并行的参数 schema)。共用件塞进任一方
    都会凭空引入一条方向性依赖, 故独立成顶层模块, 只依赖 stdlib。

声明形状 (两种写法可在同一列表里混用):
    enum: [collector, bottle]                     标量项, 值即标签
    enum:                                          带标签项, 给操作员看的中文说明
      - {value: 1, label: 1 上样}
      - {value: 2, label: 2 拍照}

    刻意不支持 `enum: {1: 上样}` 映射形 —— YAML 映射键恒为字符串, 会把 INT 域悄悄
    变成 STRING 域, 正是本模块要防的那类漂移。

与类型的关系:
    enum 与 type 正交。type 只管强转 (地轨 target 必须仍是 INT 才能喂 rail.move),
    enum 非空即"渲染下拉 + 强制成员校验"。不新增 ENUM 类型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence


@dataclass(frozen=True)
class EnumOption:
    """一个可选值: 下发的 value 与给人看的 label (缺省即 str(value))."""
    value: Any
    label: str


def normalize_enum(raw: Any, *, where: str = "") -> tuple[EnumOption, ...]:
    """把声明的 enum (标量/带标签项混合列表) 规范化为 EnumOption 元组.

    参数:
        raw: YAML 里读到的原始声明; None/空列表表示"无有限取值域"
        where: 出错消息里的定位串 (如 "变量 rack_id")
    返回:
        EnumOption 元组; raw 为 None/空时返回空元组
    异常:
        ValueError: 形状非法 (非列表 / 项既不是标量也不是带 value 的映射)
    """
    if raw is None:
        return ()
    prefix = f"{where} " if where else ""
    if isinstance(raw, dict):
        raise ValueError(f"{prefix}enum 不支持映射形 (YAML 映射键恒为字符串, 会改变取值类型); 请用列表")
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{prefix}enum 必须为列表, 实为 {type(raw).__name__}")

    out: list[EnumOption] = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            if "value" not in item:
                raise ValueError(f"{prefix}enum[{i}] 缺少 value 键")
            extra = set(item) - {"value", "label"}
            if extra:
                raise ValueError(f"{prefix}enum[{i}] 含未知键: {sorted(extra)} (只认 value/label)")
            value = item["value"]
            label = item.get("label")
            label = str(value) if label is None else str(label)
        elif isinstance(item, (list, tuple)):
            raise ValueError(f"{prefix}enum[{i}] 不能是列表; 带标签请写 {{value: …, label: …}}")
        else:
            value, label = item, str(item)
        out.append(EnumOption(value=value, label=label))
    return tuple(out)


def enum_values(opts: Sequence[EnumOption]) -> tuple:
    """取取值域元组 (供成员判定与守卫测试比对)."""
    return tuple(o.value for o in opts)


def _coerced(opts: Sequence[EnumOption], coerce: Callable[[Any], Any] | None) -> list:
    """把声明值过一遍强转; 强转失败的项原样保留 (形状校验会单独报, 此处不吞不炸)."""
    if coerce is None:
        return [o.value for o in opts]
    out = []
    for o in opts:
        try:
            out.append(coerce(o.value))
        except Exception:
            out.append(o.value)
    return out


def check_enum(opts: Sequence[EnumOption], value: Any, *,
               coerce: Callable[[Any], Any] | None = None) -> str:
    """成员判定; 合法返回空串, 否则返回中文错误消息 (含允许集).

    待校验值与声明值过**同一个** coerce 再比 —— 消灭"声明 1 传 '1'"这一整类假不匹配。
    coerce 抛异常 (值根本转不成该类型) 时不在此处报, 交由调用方的类型校验负责,
    本函数只回退成原值比较, 避免同一个错误被报两遍。

    参数:
        opts: 规范化后的可选值
        value: 待校验值
        coerce: 类型强转 (VM 侧传 coerce_value 的偏函数, 动作侧传 _coerce_param 的)
    返回:
        错误消息; 合法返回空串
    """
    if not opts:
        return ""
    declared = _coerced(opts, coerce)
    try:
        cval = coerce(value) if coerce is not None else value
    except Exception:
        cval = value
    if cval in declared:
        return ""
    return f"{value!r} 不在可选值内 (允许: {', '.join(describe_enum(opts))})"


def describe_enum(opts: Iterable[EnumOption]) -> list[str]:
    """人读的可选值描述: 有标签且与值不同时写成 "值(标签)", 否则只写值."""
    out = []
    for o in opts:
        sval = str(o.value)
        out.append(sval if o.label == sval else f"{sval}({o.label})")
    return out


def enum_payload(opts: Iterable[EnumOption]) -> list[dict]:
    """转成可 JSON 下发给前端的 plain dict 列表 (前端 enumOf 直接消费此形状)."""
    return [{"value": o.value, "label": o.label} for o in opts]
