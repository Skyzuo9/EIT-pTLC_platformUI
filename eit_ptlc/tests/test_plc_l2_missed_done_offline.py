"""PLC L2 漏推 DONE 通知 → 超时前直读复核救回 (结构性修复回归)
==============================================================
背景 (真机复现):
    等待循环只读订阅镜像 (cached_many)。OPC UA 订阅按周期采样, 若 "State→DONE" 这一次数据变化
    通知被漏推 / 合并, 镜像会永久停在 RUNNING, 而 PLC 其实已按下降沿契约保持 DONE。旧逻辑在
    stall_timeout 后判 "停滞 Xs 无进度 (已接受)" → PLCActionOutcomeUnknown → 上层 ERROR, 把一个
    已经完成的动作误判成卡死 (现场表现: 徽标卡住、动作不同步、间歇复现、跨不同工位)。

修复:
    判超时 (停滞 / 绝对上限) 之前先 refresh_mirror 直读一次 L2 字段再复核终态; 直读看到真 DONE
    即救回, 只有直读仍非本 seq 终态才是真卡, 照常判超时。

本测试用伪驱动精确复现 "镜像与直读发散":
    - cached_many (订阅镜像) 永久停在 RUNNING;
    - read_variable / refresh_mirror (直读) 反映 PLC 真实值 (已 DONE)。
  用例 1: 漏推 DONE → execute 返回 DONE (救回), 不再抛 OutcomeUnknown。
  用例 2: 真卡死 (直读也停在 RUNNING) → 仍抛 PLCActionOutcomeUnknown (修复不吞真故障)。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_plc_l2_missed_done_offline
"""

from __future__ import annotations

import asyncio
import sys

from eit_ptlc.controller.plc_controller import (
    PLCActionOutcomeUnknown,
    PLCActionState,
    PlcController,
)

_FIELDS = ("State", "ActiveCode", "AcceptedSeq", "CompletedSeq",
           "Step", "ErrorCode", "SafeState", "Retryable")


class MirrorStaleDriver:
    """伪 OPC UA 驱动: 直读反映真实 PLC 值, 订阅镜像故意漏掉 "→DONE" 那次更新。

    参数:
        prefix: L2 前缀 (如 PhotoScrape);
        salvageable: True=PLC 真的完成了 (直读 DONE, 只是镜像漏推) → 应被救回;
                     False=PLC 真卡死 (直读也停 RUNNING) → 应照常判超时。
    """

    def __init__(self, prefix: str, *, salvageable: bool) -> None:
        self.prefix = prefix
        self._salvageable = salvageable
        self._real: dict[str, object] = {}
        self._real[f"{prefix}_L2_ActionCode"] = 0
        self._real[f"{prefix}_L2_RequestSeq"] = 0
        self._real[f"{prefix}_L2_Start"] = False
        self._real[f"{prefix}_L2_Reset"] = False
        for f in _FIELDS:
            self._real[f"{prefix}_L2_{f}"] = 0
        self._real[f"{prefix}_L2_SafeState"] = 10   # READY
        self._real[f"{prefix}_L2_Retryable"] = False
        self._mirror: dict[str, object] = dict(self._real)
        self._count = 0
        self._waiters: list[asyncio.Future] = []
        self._pending_done = False   # Start=True 后, 首次读镜像时把真实值推进到 DONE

    # ---- 读 (直读, 反映真实 PLC) ----
    async def read_many(self, names: list[str]) -> list:
        """批量读 (替身实现: 逐点转 read_variable, 完整保留本替身模拟的断链/静默语义)."""
        return [await self.read_variable(n) for n in names]

    async def read_variable(self, name: str):
        return self._real.get(name)

    def cached_many(self, names):
        # 首次读镜像时让真实 PLC 完成 (只更新 real, 不更新 mirror = 漏推 DONE 那次通知)
        if self._pending_done:
            self._pending_done = False
            if self._salvageable:
                seq = int(self._real[f"{self.prefix}_L2_RequestSeq"])
                self._real[f"{self.prefix}_L2_State"] = int(PLCActionState.DONE)
                self._real[f"{self.prefix}_L2_CompletedSeq"] = seq
                self._real[f"{self.prefix}_L2_Step"] = 1
        return {n: self._mirror.get(n) for n in names}

    # ---- 写 ----
    async def write_variable(self, name: str, value) -> None:
        self._real[name] = value
        if name == f"{self.prefix}_L2_Start" and value is True:
            seq = int(self._real[f"{self.prefix}_L2_RequestSeq"])
            # PLC 接受并进入 RUNNING; 订阅把 "已接受 + RUNNING" 推给镜像 (故 accepted=True),
            # 但之后 "→DONE" 那次通知漏推 —— 镜像就此定格在 RUNNING。
            self._real[f"{self.prefix}_L2_AcceptedSeq"] = seq
            self._real[f"{self.prefix}_L2_State"] = int(PLCActionState.RUNNING)
            self._mirror[f"{self.prefix}_L2_AcceptedSeq"] = seq
            self._mirror[f"{self.prefix}_L2_State"] = int(PLCActionState.RUNNING)
            self._pending_done = True
            self._bump()
        elif name == f"{self.prefix}_L2_Start" and value is False:
            self._real[f"{self.prefix}_L2_State"] = int(PLCActionState.IDLE)

    async def write_many(self, params: dict) -> None:
        self._real.update(params)

    # ---- 订阅镜像 ----
    async def add_subscription(self, names) -> None:
        for n in names:
            self._mirror.setdefault(n, self._real.get(n))

    async def refresh_mirror(self, names) -> None:
        # 直读基线 / 超时前复核: 把真实值写进镜像 (救回的关键路径)
        for n in names:
            self._mirror[n] = self._real.get(n)
        self._bump()

    # ---- 变化唤醒 ----
    def change_token(self) -> int:
        return self._count

    async def wait_change(self, token: int) -> int:
        if token != self._count:
            return self._count
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        try:
            await fut
        finally:
            if fut in self._waiters:
                self._waiters.remove(fut)
        return self._count

    def _bump(self) -> None:
        self._count += 1
        waiters, self._waiters = self._waiters, []
        for fut in waiters:
            if not fut.done():
                fut.set_result(None)


async def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # 用例 1: 漏推 DONE 但 PLC 真完成 → 超时前直读复核救回为 DONE
    drv = MirrorStaleDriver("PhotoScrape", salvageable=True)
    ctrl = PlcController(drv, poll_interval=0.02, action_timeout=5.0, stall_timeout=0.3)
    try:
        r = await ctrl.execute("photoscrape", 40)
        check("missed_done_salvaged",
              r.ok and r.state is PLCActionState.DONE and r.request_seq == 1,
              str(r))
    except PLCActionOutcomeUnknown as exc:
        check("missed_done_salvaged", False, f"不应超时, 应直读救回: {exc}")

    # 用例 2: 真卡死 (直读也停 RUNNING) → 修复不吞真故障, 仍判 OutcomeUnknown
    drv2 = MirrorStaleDriver("PhotoScrape", salvageable=False)
    ctrl2 = PlcController(drv2, poll_interval=0.02, action_timeout=5.0, stall_timeout=0.3)
    t0 = asyncio.get_running_loop().time()
    try:
        await ctrl2.execute("photoscrape", 40)
        check("genuine_stall_still_detected", False, "真卡死应抛 PLCActionOutcomeUnknown")
    except PLCActionOutcomeUnknown as exc:
        elapsed = asyncio.get_running_loop().time() - t0
        check("genuine_stall_still_detected",
              0.25 <= elapsed < 3.0 and "停滞" in str(exc),
              f"elapsed={elapsed:.2f}s {exc}")

    print(f"\n共 2 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
