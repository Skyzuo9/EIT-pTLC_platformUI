"""接粉桶翻料缸到位判定 — photoscrape.wait_rot 的 host 计算/轮询函数。

背景: 「刮板拍照旋转气缸」是两位气缸(原点/动点), 只有两个动作驱动它 ——
A41 scrape_finish 置 TRUE(翻转倒料), A52 retr_stoprot 置 FALSE(复位)。
两者的 desc 都写着「在同一扫描周期返回 DONE」「不等待旋转气缸到位反馈」, 即**纯开环**。

⚠️ 2026-07-27 真机复盘: 标定流程里 A41 与 A52 之间只隔一行注释, 毫秒级一开一关,
   翻料缸根本走不完行程 —— 粉没倒进桶, 后续会掉出去。生产侧因为 A52 落在 collect_load
   (机器人取走粉桶之后)才有几十秒行程时间, 所以翻得成 —— 但同样**从不确认到位**,
   气压不足/卡滞导致压根没翻是一类完全看不见的哑故障。

到位信号本来就读得到, 不必猜驻留时长:
    刮板拍照旋转气缸动点  %IX9.7   → IX9 bit 7
    刮板拍照旋转气缸原点  %IX9.6   → IX9 bit 6
IX9 已是 plc_nodes.yaml 暴露的字节节点。同型先例见 feedlift_count.preflight_gate(读 IX8 取位)。

⚠️ IX9 是**共享**输入字节(bit0/1 = 上样料架检测), 必须按位取, 不能整字节比较。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

# 位号见模块头。⚠️ 气缸动作.xml 里 cylinder_14 的 xPosExtend/xPosRetract 接线看着与同文件
# 其它气缸相反(xPosExtend:=原点, xPosRetract:=动点), 故这两个常量必须经真机核对:
# 手动翻一次缸, 前后各读一次 IX9, 看哪一位在翻倒态变 1。改这里即可, 不必动别处。
_IX9_ROT_EXTEND_BIT = 7   # 动点 = 已翻倒(倒料位)
_IX9_ROT_HOME_BIT = 6     # 原点 = 未翻(刮取位)

# 默认超时对齐 PLC 自己那个气缸 FB 的 tTimeout := T#5S, 加一点余量。
# 超过它 PLC 会置 cyinderAlarm.13 —— 但那个字没暴露给上位机, 所以这里超时是我们唯一的知情渠道。
_DEFAULT_TIMEOUT_S = 6.0
_DEFAULT_POLL_S = 0.2

TARGETS = ("extend", "home")


def rot_state(ix9: int) -> dict[str, Any]:
    """输入字节 IX9 → 翻料缸两个到位位 (纯函数)。

    参数:
        ix9: PLC 输入字节 IX9 的当前值
    返回:
        Dict[str, Any], {at_extend, at_home, raw}

    两位同时为真或同时为假都是**合法的中间/故障态**(行程中 / 传感器失效), 本函数不做判断,
    如实返回两位 —— 判定留给 wait_rot, 免得把"读到什么"和"该怎么办"糊在一起。
    """
    raw = int(ix9) & 0xFF
    return {
        "at_extend": bool(raw >> _IX9_ROT_EXTEND_BIT & 1),
        "at_home": bool(raw >> _IX9_ROT_HOME_BIT & 1),
        "raw": raw,
    }


async def wait_rot(
    read_ix9: Callable[[], Awaitable[Any]],
    *,
    target: str = "extend",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    poll_s: float = _DEFAULT_POLL_S,
    time_fn: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> dict[str, Any]:
    """轮询 IX9 等翻料缸到位, 返回是否到位 + 实际耗时。

    参数:
        read_ix9:  读 IX9 的协程(注入以便离线测); 返回 None 视为读不到
        target:    'extend'(动点/翻倒) 或 'home'(原点/刮取位)
        timeout_s: 等到位的上限秒数
        poll_s:    轮询间隔秒
    返回:
        Dict[str, Any], {ok, at_extend, at_home, raw, target, elapsed_s, message}

    **永不抛。** 与 scrape_reconcile 的对账叠加同姿势: 这是哨兵不是工艺步。翻料没翻成
    既不影响板子也不影响标定数学, 而在收尾这一步抛错会把一次已完成的标定判成 ABORTED,
    生产侧则会让板卡在压头下 —— 代价远大于收益。超时/读不到一律 ok=false + WARN,
    由动作记录与日志留痕。

    读回 None 不当 0 用: 那是"读不到"而非"全 0", 当 0 会得到一张骗人的快照
    (bit6/bit7 全 0 恰好是"两个到位位都没到"的故障态, 会指错方向)。
    """
    if target not in TARGETS:
        # 参数写错属于编排 bug, 不是现场故障 —— 但仍不抛, 免得一个笔误炸掉收尾链
        log.warning("[翻料缸] target 应为 %s 之一, 收到 %r; 按 extend 处理", TARGETS, target)
        target = "extend"
    key = "at_extend" if target == "extend" else "at_home"
    label = "动点(翻倒)" if target == "extend" else "原点(刮取位)"

    start = time_fn()
    state: dict[str, Any] = {"at_extend": False, "at_home": False, "raw": None}
    while True:
        raw = await read_ix9()
        if raw is None:
            elapsed = round(time_fn() - start, 3)
            log.warning("[翻料缸] IX9 读回空值(节点存在但无值, 通常是 PLC 未运行或输入映像未刷新); "
                        "无法确认翻料缸是否到%s", label)
            return {"ok": False, "at_extend": False, "at_home": False, "raw": None,
                    "target": target, "elapsed_s": elapsed,
                    "message": "IX9 读回空值, 翻料缸到位无法确认"}
        state = rot_state(raw)
        if state[key]:
            elapsed = round(time_fn() - start, 3)
            log.info("[翻料缸] 已到%s (%.2fs, IX9=%d)", label, elapsed, state["raw"])
            return {"ok": True, **state, "target": target, "elapsed_s": elapsed,
                    "message": f"翻料缸已到{label}"}
        if time_fn() - start >= timeout_s:
            elapsed = round(time_fn() - start, 3)
            log.warning("[翻料缸] 等%s超时 (%.1fs, IX9=%d, 动点=%s 原点=%s) —— "
                        "气压不足/机构卡滞? PLC 侧应已置 cyinderAlarm.13",
                        label, elapsed, state["raw"], state["at_extend"], state["at_home"])
            return {"ok": False, **state, "target": target, "elapsed_s": elapsed,
                    "message": f"等翻料缸到{label}超时 {timeout_s:g}s; 气压不足或机构卡滞"}
        await sleep(poll_s)
