"""沙盒合成值登记簿
==================
功能:
    沙盒里有几个答案给不出真值 —— 没有对位相机, 没有液位相机。此前的处置是**直接抛
    异常拒绝**(原注释的理由: "零偏桩会骗人")。但那条拒绝把 `robot_suction_put` 整条
    堵死了, 而它被 7 条操作引用 (sampling_load / sampling_place_plate /
    photoscrape_load / photoscrape_place / photoscrape_plate_load /
    feedlift_unload_cycle / ptlc_full_v2) —— 于是沙盒里**任何放板都必定中途硬失败**,
    一条完整流程都跑不完。`develop.wait_level` 同样挡死 develop 链。

    本模块是"改成合成值"的配套约束。原顾虑要正面回答: **骗人的从来不是零偏本身** ——
    沙盒里板的位姿是沙盒自己写的, 板就在名义位, 零偏是这个世界里的真值; 骗人的是把
    它当成对**真机**的结论。所以规矩不是"不许编", 而是"编了必须自报":

      ① 结果体自带 `synthetic: True` 与中文 `synthetic_reason`;
      ② 每次调用登记一笔, 按 host 计数;
      ③ 经 `sim_synthetic` 事件与 `GET /api/sim/diagnostics` 在界面上留痕。

    没有第 ③ 条, 这就退回成一个更隐蔽的零偏桩 —— 界面上看不出来的合成值, 与拒绝相比
    只是把"跑不通"换成了"跑通了但不知道有几处是编的"。

单写者: 只有 sim_stack 的沙盒 host 方法表往里写, 诊断面板只读。
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

log = logging.getLogger("eit_ptlc.mock.synthetic")

__all__ = ["SyntheticLedger"]


class SyntheticLedger:
    """沙盒合成值的登记簿 (计数 + 事件广播 + 自述字段生成).

    参数:
        publish: 沙盒事件总线的 publish (同步); None 则只计数不广播
    """

    def __init__(self, publish: Optional[Callable[[dict], None]] = None) -> None:
        self._publish = publish
        self._items: dict[str, dict] = {}
        self._total = 0
        self._seq = 0

    def record(self, host: str, reason: str) -> dict:
        """登记一次合成, 返回可并进动作结果体的**自述字段**.

        参数:
            host: 合成发生在哪个 host 方法上, 如 "vision.capture_plate_offset"
            reason: 为什么只能合成 (中文, 直接给人看)
        返回:
            Dict {"synthetic": True, "synthetic_reason": reason}

        返回值刻意是"补丁"形状而不是完整结果体 —— 合成值的**主体**必须来自真机侧
        同一个构造器 (如 pallas_vision_client.neutral_offset), 本模块只负责给它盖章。
        两份形状各自演化才是真的会骗人。
        """
        entry = self._items.get(host)
        if entry is None:
            entry = {"host": host, "reason": reason, "count": 0, "last_ts": 0.0}
            self._items[host] = entry
        entry["reason"] = reason              # 同一 host 换了理由以最新一次为准
        entry["count"] += 1
        entry["last_ts"] = time.time()
        self._total += 1
        self._seq += 1
        if self._publish is not None:
            try:
                self._publish({"type": "sim_synthetic", "host": host, "reason": reason,
                               "count": entry["count"], "total": self._total,
                               "ts": entry["last_ts"], "seq": self._seq})
            except Exception:                 # 广播失败不许影响动作本身
                log.debug("[沙盒·合成值] 事件广播失败", exc_info=True)
        return {"synthetic": True, "synthetic_reason": reason}

    def snapshot(self) -> dict:
        """只读快照, 供 GET /api/sim/diagnostics.

        参数:
            无
        返回:
            Dict {total, items: [{host, reason, count, last_ts}]}, items 按次数降序
        """
        items = sorted(self._items.values(), key=lambda row: -row["count"])
        return {"total": self._total, "items": [dict(row) for row in items]}
