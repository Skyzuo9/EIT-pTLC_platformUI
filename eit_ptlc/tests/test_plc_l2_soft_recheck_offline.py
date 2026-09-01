"""PLC L2 软复核 → 漏推 DONE 亚秒级救回 (直读对账回归)
==========================================================
背景 (真机复现, 承 test_plc_l2_missed_done_offline):
    等待终态只读订阅镜像。OPC UA 订阅是 report-on-change: 服务器只在采样值 != "上次已发水位线"
    时推 delta, 对保持不变的电平不重发。PLC 侧 StagingA 等目标态动作在单个扫描内 0→10→20 塌缩,
    对外只表现为一条 IDLE→DONE 的 delta; 这条一旦在发布/传输/队列环节丢失, 镜像永久停在动作前旧值,
    旧逻辑要等满 stall_timeout(几十秒) 才靠边界直读救回 —— 现场即 "定位气缸等几十秒才继续"。

修复 (soft_recheck):
    镜像静默超过 soft_recheck 即主动直读对账一次 (绕开水位线, 直接问 PLC), 把漏推恢复从 stall_timeout
    压到 ~soft_recheck。快路径 (通知正常到) last_progress 持续复位 → soft 永不触发 → 零额外网络。

本测试用伪驱动复现 "镜像与直读发散", 且 stall_timeout 放大到远超 soft_recheck, 证明:
  用例 1: 漏推 DONE → 在 ~soft_recheck 内经软复核直读救回为 DONE (远早于 stall_timeout)。
  用例 2: 软复核关闭 (soft_recheck=0) → 退回旧行为, 只能等 stall_timeout 边界直读才救回
          (对照证明用例 1 的救回确实来自软复核而非基线直读)。
  用例 3: 快路径 (通知正常到) → 镜像即时命中 DONE, 立即返回 (elapsed < soft_recheck, 软复核不可能触发)。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_plc_l2_soft_recheck_offline
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


class SoftRecheckDriver:
    """伪 OPC UA 驱动, 复现 StagingA "IDLE→DONE 单 delta 漏推"。

    参数:
        prefix: L2 前缀; push_done_to_mirror:
            True  = 通知正常到达 (镜像随真值一起到 DONE, 快路径);
            False = 漏推 (真值在首次读镜像后才落 DONE 且镜像永不更新 —— 复现基线直读拿到旧 IDLE、
                    随后 DONE 通知丢失; 只有软复核/边界直读能救回)。
    """

    def __init__(self, prefix: str, *, push_done_to_mirror: bool) -> None:
        self.prefix = prefix
        self._push = push_done_to_mirror
        self._real: dict[str, object] = {
            f"{prefix}_L2_ActionCode": 0,
            f"{prefix}_L2_RequestSeq": 0,
            f"{prefix}_L2_Start": False,
            f"{prefix}_L2_Reset": False,
        }
        for f in _FIELDS:
            self._real[f"{prefix}_L2_{f}"] = 0
        self._real[f"{prefix}_L2_SafeState"] = 10   # READY
        self._mirror: dict[str, object] = dict(self._real)
        self._count = 0
        self._waiters: list[asyncio.Future] = []
        self._pending_done = False   # 漏推路径: 首次读镜像后把真值推进到 DONE (镜像不动)

    def _land_done(self) -> None:
        seq = int(self._real[f"{self.prefix}_L2_RequestSeq"])
        self._real[f"{self.prefix}_L2_AcceptedSeq"] = seq
        self._real[f"{self.prefix}_L2_CompletedSeq"] = seq
        self._real[f"{self.prefix}_L2_State"] = int(PLCActionState.DONE)
        self._real[f"{self.prefix}_L2_Step"] = 99

    # ---- 读 (直读, 反映真实 PLC) ----
    async def read_many(self, names: list[str]) -> list:
        """批量读 (替身实现: 逐点转 read_variable, 完整保留本替身模拟的断链/静默语义)."""
        return [await self.read_variable(n) for n in names]

    async def read_variable(self, name: str):
        return self._real.get(name)

    def cached_many(self, names):
        # 漏推路径: 首次读镜像时让真值落 DONE (只更新 real, 镜像保持旧 IDLE = 漏掉那次通知)
        if self._pending_done:
            self._pending_done = False
            self._land_done()
        return {n: self._mirror.get(n) for n in names}

    # ---- 写 ----
    async def write_variable(self, name: str, value) -> None:
        self._real[name] = value
        if name == f"{self.prefix}_L2_Start" and value is True:
            if self._push:
                # 通知正常到: 真值 + 镜像一起到 DONE, 等待循环走快路径即时命中。
                self._land_done()
                for f in _FIELDS:
                    self._mirror[f"{self.prefix}_L2_{f}"] = self._real[f"{self.prefix}_L2_{f}"]
                self._bump()
            else:
                # 漏推: 真值延后到 DONE (首次 cached_many), 镜像永不更新。
                self._pending_done = True
        elif name == f"{self.prefix}_L2_Start" and value is False:
            self._real[f"{self.prefix}_L2_State"] = int(PLCActionState.IDLE)

    async def write_many(self, params: dict) -> None:
        self._real.update(params)

    # ---- 订阅镜像 ----
    async def add_subscription(self, names) -> None:
        for n in names:
            self._mirror.setdefault(n, self._real.get(n))

    async def refresh_mirror(self, names) -> None:
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

    loop = asyncio.get_running_loop()

    # 用例 1: 漏推 DONE, stall_timeout(10s) 远大于 soft_recheck(0.2s) → 软复核在 ~soft 内救回
    drv = SoftRecheckDriver("StagingA", push_done_to_mirror=False)
    ctrl = PlcController(drv, poll_interval=0.02, action_timeout=30.0,
                         stall_timeout=10.0, soft_recheck=0.2)
    t0 = loop.time()
    try:
        r = await ctrl.execute("staging_a", 25)
        elapsed = loop.time() - t0
        check("soft_recheck_salvages_fast",
              r.ok and r.state is PLCActionState.DONE and r.request_seq == 1 and elapsed < 2.0,
              f"state={r.state} seq={r.request_seq} elapsed={elapsed:.2f}s (应 < 2s, 远早于 stall=10s)")
    except PLCActionOutcomeUnknown as exc:
        check("soft_recheck_salvages_fast", False, f"不应超时, 应软复核救回: {exc}")

    # 用例 2: 关闭软复核 (soft_recheck=0) → 退回旧行为, 只能等 stall(0.5s) 边界直读才救回
    drv2 = SoftRecheckDriver("StagingA", push_done_to_mirror=False)
    ctrl2 = PlcController(drv2, poll_interval=0.02, action_timeout=30.0,
                          stall_timeout=0.5, soft_recheck=0.0)
    t0 = loop.time()
    r2 = await ctrl2.execute("staging_a", 25)
    elapsed2 = loop.time() - t0
    check("soft_off_falls_back_to_stall",
          r2.ok and elapsed2 >= 0.45,
          f"关闭软复核应等到 stall(0.5s) 才救回: ok={r2.ok} elapsed={elapsed2:.2f}s")

    # 用例 3: 快路径 (通知正常到) → 镜像即时命中 DONE, 立即返回; elapsed < soft(0.2s) 证明软复核未触发
    drv3 = SoftRecheckDriver("StagingA", push_done_to_mirror=True)
    ctrl3 = PlcController(drv3, poll_interval=0.02, action_timeout=30.0,
                          stall_timeout=10.0, soft_recheck=0.2)
    t0 = loop.time()
    r3 = await ctrl3.execute("staging_a", 25)
    elapsed3 = loop.time() - t0
    check("fast_path_no_soft_trigger",
          r3.ok and elapsed3 < 0.2,
          f"快路径应即时命中且早于软复核间隔: ok={r3.ok} elapsed={elapsed3:.3f}s")

    print(f"\n共 3 用例, 失败 {len(failures)}")
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
