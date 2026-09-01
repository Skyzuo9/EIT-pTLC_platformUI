"""PLC L2 错误码 → 现场可执行释义
================================
功能:
    把 PLC 回的整数 ErrorCode 翻成"该去查什么"的中文, 供执行器在构造失败 ActionResult
    时并进 message。

为什么并在执行器而不是某个路由里: 一次失败有四个消费者 —— HTTP 响应、WS 事件流
(vm_node_done)、运行历史 (RunStore) 与回放。释义只加在路由上, 其余三处看到的仍是裸
"error=301"; 而从格式化好的字符串里再解析回错误码来补释义则是自找的脆弱。并在源头,
四处自然一致。

释义的真源是编排说明书 (mock/behavior/specs/*.yaml):
    八个工位的 spec 里都已有机器可读的 `errors:` (动作级) 与 `dispatcher.gate_errors`
    (派发器级), 全部带 CODESYS POU 锚点与 ST 哈希, 由两层漂移看门狗守着。此前本模块
    只认 feedlift 一个工位, 其余七个在现场只显示裸数字; 而 feedlift 那份释义又是
    controller/feedlift_count.py 里手抄的第二份真源 —— 抄一份必漂。现在一律读 spec。

刻意不做的两件事:
    * **不把处置话术写回 spec**: spec 是 CODESYS 的逐字提取记录, 往里塞上位机话术会
      污染提取物, 在线哈希比对会开始报假阳。释义取 spec 的原文, 话术留在本模块。
    * **不把 spec 的 notes 拼进 message**: notes 是多行 ST 转录 (A11 的有 6 行),
      塞进一条动作 message 会把真正的信息淹掉。
"""

from __future__ import annotations

import logging
from functools import lru_cache

log = logging.getLogger(__name__)

#: 语境闭集。真机现场关心"该去查什么设备", 沙盒关心"该去设哪个状态" —— 同一个错误码,
#: 两种处置。混在一起就会出现用户 2026-08-12 撞到的那种事: 沙盒里报 301, 界面却建议
#: 去查标定采样。
CONTEXT_REAL = "real"
CONTEXT_SIM = "sim"

#: 沙盒语境下 FeedLift 前置门超时的处置指引 (对应真机侧的 EMPTY_MAGAZINE_HINT)。
#: 它讲的是**沙盒状态面**怎么用, 属主是沙盒 API 而不是标定链, 故常量放这里。
_SIM_FEEDLIFT_GATE_HINT = (
    "沙盒里仓内张数由板堆模型决定, 而模型跟着账面走: "
    "POST /api/sim/materials/magazine {magazine, count} 置张数 (自动回灌模型), "
    "或 PUT /api/sim/state {feedlift: {<仓>: {homed: true}}} 置回零位。"
    "标定文件是真机的, 沙盒不涉及'标定失准'。")


@lru_cache(maxsize=None)
def _spec(prefix: str):
    """按 L2 前缀取编排说明书; 取不到返回 None (释义随之为空串).

    参数:
        prefix: L2 变量前缀 (FeedLift / Sampling / ...)
    返回:
        StationSpec | None

    spec 是随包发布的只读文件, 进程级缓存即可。
    """
    try:
        from eit_ptlc.mock.behavior.spec_loader import load_station_spec
        return load_station_spec(prefix)
    except Exception:
        log.debug("[释义] 工位 %s 无编排说明书", prefix, exc_info=True)
        return None


def _prefix_of(station: str) -> str:
    """工位名归一到 L2 变量前缀 (复用 plc_controller 那份唯一的映射表)."""
    from eit_ptlc.controller.plc_controller import STATION_PREFIX
    key = str(station or "").strip()
    return STATION_PREFIX.get(key.lower(), key)


def _gate_text(action_spec) -> str:
    """把动作的前置门各项串成一句 (timeout_error 不是门条件, 排除)."""
    items = [str(value) for key, value in (action_spec.gate or {}).items()
             if key != "timeout_error"]
    return " + ".join(items)


def _step_text(spec, action_spec, step: int) -> str:
    """把段号翻成"属哪个动作的哪一段"; 认不出返回空串.

    段号命中**别的动作**时明确点出来 —— 那通常是上一个动作留下的残留段号,
    手抄表给不了这条诊断。
    """
    for item in (action_spec.steps if action_spec is not None else ()):
        if int(item["step"]) == step:
            return f"段号 {step} 属 {item['phase']} 段"
    for other in (spec.actions.values() if spec is not None else ()):
        for item in other.steps:
            if int(item["step"]) == step:
                return (f"段号 {step} 属 {other.name} 的 {item['phase']} 段 "
                        f"(与本动作不符, 疑为上一动作的残留段号)")
    return ""


def describe(station: str, action_code: int, error_code: int, step: int = 0,
             *, context: str = CONTEXT_REAL) -> str:
    """把 (工位, 动作码, 错误码, 段号) 翻成现场能照着做的一句话。

    参数:
        station: 动作声明里的工位名 (如 feedlift), 经 STATION_PREFIX 归一到 L2 前缀
        action_code: 动作码 (spec 按码索引动作); 0 表示不参与
        error_code: PLC 回的 {prefix}_L2_ErrorCode
        step: PLC 回的 {prefix}_L2_Step; 0 表示不参与
        context: 语境闭集 —— "real"=真机现场处置, "sim"=仿真沙盒状态面指引

    返回:
        str; 认不出的码返回空串 —— 宁可不说, 也不编一个似是而非的解释。
    """
    code = int(error_code or 0)
    if code <= 0:
        return ""
    prefix = _prefix_of(station)
    spec = _spec(prefix)
    if spec is None:
        return ""
    action_spec = spec.action(int(action_code or 0))

    parts: list[str] = []
    text = ""
    if action_spec is not None:
        text = str((action_spec.errors or {}).get(code) or "")
    if not text:
        text = str((spec.gate_errors or {}).get(code) or "")
    if not text and code == int(spec.unknown_code_error):
        text = f"{prefix} 派发器未登记该动作码"
    if text:
        parts.append(text)

    # 前置门超时: 把门的各项原文附上 (这是手抄门表的自动版, 立刻覆盖八个工位)
    is_gate_timeout = (action_spec is not None
                       and int((action_spec.gate or {}).get("timeout_error") or 0) == code)
    if is_gate_timeout:
        gate = _gate_text(action_spec)
        if gate:
            parts.append(f"该动作要求: {gate}")
        parts.append(_gate_hint(prefix, context))

    step_text = _step_text(spec, action_spec, int(step or 0))
    if step_text:
        parts.append(step_text)
    return "; ".join(part for part in parts if part)


def _gate_hint(prefix: str, context: str) -> str:
    """前置门超时的处置指引 (分语境).

    参数:
        prefix: L2 前缀; context: CONTEXT_REAL | CONTEXT_SIM
    返回:
        str

    真机侧沿用标定链既有的两条 hint (它们还被 feedlift_count.preflight_gate 用着,
    属主在那边); 沙盒侧换成状态面指引 —— 沙盒里没有"标定失准"这回事。
    """
    if prefix != "FeedLift":
        return ""
    if context == CONTEXT_SIM:
        return _SIM_FEEDLIFT_GATE_HINT
    from eit_ptlc.controller.feedlift_count import EMPTY_MAGAZINE_HINT, HOMING_HINT
    return f"{EMPTY_MAGAZINE_HINT} {HOMING_HINT}"
