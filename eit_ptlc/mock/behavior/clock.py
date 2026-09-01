"""仿真时钟: 全沙盒统一的时间倍率。

行为层的一切耗时 (轴运动/泵积分/换阀/段间延时) 都经 clock.sleep(名义秒) 等待,
rate 可在运行中改 (POST /api/sim/time_scale), 下一次 sleep 即生效 —— 不追求
在途段的精确重标定, 演示语义足够。
"""

from __future__ import annotations

import asyncio
import time


class SimClock:
    """rate 倍速时钟; rate=4 表示名义 4 秒只等真实 1 秒。"""

    def __init__(self, rate: float = 1.0) -> None:
        self.rate = float(rate)

    async def sleep(self, nominal_seconds: float) -> None:
        await asyncio.sleep(max(0.0, float(nominal_seconds)) / max(self.rate, 1e-6))

    @staticmethod
    def mark() -> float:
        """取一个计时起点 (单调秒), 交给 elapsed 用。"""
        return time.monotonic()

    def elapsed(self, since: float) -> float:
        """从 since 到现在过了多少**名义**秒 = 真实经过 × 当前倍率.

        参数:
            since: mark() 取回的起点
        返回:
            float, 名义秒

        **为什么不许用"把请求的 sleep 时长累加起来"代替它**: 那个做法假设
        `await clock.sleep(x)` 恰好耗真实 x/rate 秒, 而事件循环并不保证 —— 2026-08-13
        实测在 rate=16 下 `clock.sleep(0.2)` 平均只用 5ms 就返回 (请求 12.5ms), 累加法
        把 600 名义秒记成了实际的 242 秒, 于是展缸 wait_level 的硬上限提前 2.5 倍触发,
        有液的缸也等不到前沿。同一个错在展缸液量积分循环里也犯过一次。
        倍率中途被改时本式按新倍率折算已过时间, 与 sleep 的"下一次调用即生效"同口径。
        """
        return (time.monotonic() - float(since)) * max(self.rate, 1e-6)
