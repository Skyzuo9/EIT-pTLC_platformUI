"""PLC L2 等待期连接瞬断容忍 (真机复现: client is disconnected 杀死在飞泵动作)
================================================================================
背景 (真机 TID 418ded72e68d 复现):
    泵动作 (rinse_fill/fill) 整个行程 L2 字段静默, 等待期唯一持续打网络的调用是 ~1Hz
    软复核直读。OPC UA 传输层瞬断时 (asyncua 即时判死 vs 驱动心跳 3x100ms 判定之间的
    竞态窗口), 断连异常从软复核泄漏, 被 executor 兜底判成 ERROR 非重试 → 运行 FAILED,
    而 PLC 泵物理上仍在正常推进。

修复 (两层):
    - 驱动 _guarded: 调用侧先于心跳发现死连接时立即触发重连迁移并重试一次, 不向上
      泄漏原始断连异常 (见 test_opcua_driver_offline 的断连注入用例);
    - 控制器软复核: 遇 ConnectionError 仅放弃本拍, 动作生死交由镜像恢复与 stall/ceiling
      预算裁决 —— 瞬断存活; 持续断连按停滞判 "结果不明确", 不误分类为普通执行异常。

本测试用伪驱动验证控制器侧语义:
    用例 1: Start 后链路瞬断, 软复核连续失败 2 次后链路恢复且 PLC 已完成 → 动作存活 DONE。
    用例 2: Start 后链路持续断开 → 按停滞抛 PLCActionOutcomeUnknown, 绝不泄漏 ConnectionError。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_plc_l2_link_blip_offline
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


class BlipLinkDriver:
    """伪 OPC UA 驱动: Start 后链路断开, 直读抛 ConnectionError; 订阅镜像定格在 RUNNING。

    参数:
        prefix: L2 前缀;
        recover_after_fails: 第 N 次直读失败后恢复链路并让 PLC 完成 (模拟瞬断+泵已跑完);
                             None = 链路永不恢复 (模拟持续断连)。
    """

    def __init__(self, prefix: str, *, recover_after_fails: int | None) -> None:
        self.prefix = prefix
        self._recover_after = recover_after_fails
        self.link_down = False
        self.read_fail_count = 0
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

    # ---- 读 (直读; 断链时模拟 asyncua 泄漏的原始异常) ----
    async def read_many(self, names: list[str]) -> list:
        """批量读 (替身实现: 逐点转 read_variable, 完整保留本替身模拟的断链/静默语义)."""
        return [await self.read_variable(n) for n in names]

    async def read_variable(self, name: str):
        if self.link_down:
            self.read_fail_count += 1
            if self._recover_after is not None and self.read_fail_count >= self._recover_after:
                # 链路恢复, 且断链期间 PLC 已自行跑完动作 (真机: 泵不依赖 OPC UA 会话)
                self.link_down = False
                seq = int(self._real[f"{self.prefix}_L2_RequestSeq"])
                self._real[f"{self.prefix}_L2_State"] = int(PLCActionState.DONE)
                self._real[f"{self.prefix}_L2_CompletedSeq"] = seq
                self._real[f"{self.prefix}_L2_Step"] = 9
            raise ConnectionError("client is disconnected")
        return self._real.get(name)

    def cached_many(self, names):
        return {n: self._mirror.get(n) for n in names}

    # ---- 写 ----
    async def write_variable(self, name: str, value) -> None:
        if self.link_down:
            raise ConnectionError("client is disconnected")
        self._real[name] = value
        if name == f"{self.prefix}_L2_Start" and value is True:
            seq = int(self._real[f"{self.prefix}_L2_RequestSeq"])
            # PLC 接受并进入 RUNNING; 订阅把这次变化推给镜像, 随后链路断开 —— 镜像自此
            # 定格 (泵行程静默, 断链期间也不会再有推送)。
            self._real[f"{self.prefix}_L2_AcceptedSeq"] = seq
            self._real[f"{self.prefix}_L2_State"] = int(PLCActionState.RUNNING)
            self._mirror[f"{self.prefix}_L2_AcceptedSeq"] = seq
            self._mirror[f"{self.prefix}_L2_State"] = int(PLCActionState.RUNNING)
            self.link_down = True
            self._bump()
        elif name == f"{self.prefix}_L2_Start" and value is False:
            self._real[f"{self.prefix}_L2_State"] = int(PLCActionState.IDLE)

    async def write_many(self, params: dict) -> None:
        if self.link_down:
            raise ConnectionError("client is disconnected")
        self._real.update(params)

    # ---- 订阅镜像 ----
    async def add_subscription(self, names) -> None:
        for n in names:
            self._mirror.setdefault(n, self._real.get(n))

    async def refresh_mirror(self, names) -> None:
        # 真驱动逐节点吞读异常且连接中断短路 → 断链时镜像保持原值
        if self.link_down:
            return
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

    # 用例 1: 瞬断 (软复核失败 2 次后链路恢复, PLC 已完成) → 动作存活返回 DONE
    drv = BlipLinkDriver("Develop", recover_after_fails=2)
    ctrl = PlcController(drv, poll_interval=0.02, action_timeout=5.0,
                         stall_timeout=2.0, soft_recheck=0.05)
    try:
        r = await ctrl.execute("develop", 21)
        check("blip_survives_as_done",
              r.ok and r.state is PLCActionState.DONE and drv.read_fail_count >= 2,
              f"result={r} fails={drv.read_fail_count}")
    except ConnectionError as exc:
        check("blip_survives_as_done", False, f"断连异常泄漏 (修复失效): {exc}")
    except PLCActionOutcomeUnknown as exc:
        check("blip_survives_as_done", False, f"瞬断不应判超时: {exc}")

    # 用例 2: 持续断连 → 按停滞判 "结果不明确" (诚实结局), 绝不泄漏 ConnectionError
    drv2 = BlipLinkDriver("Develop", recover_after_fails=None)
    ctrl2 = PlcController(drv2, poll_interval=0.02, action_timeout=5.0,
                          stall_timeout=0.3, soft_recheck=0.05)
    t0 = asyncio.get_running_loop().time()
    try:
        await ctrl2.execute("develop", 21)
        check("outage_ends_as_outcome_unknown", False, "持续断连应抛 PLCActionOutcomeUnknown")
    except ConnectionError as exc:
        check("outage_ends_as_outcome_unknown", False, f"断连异常泄漏 (修复失效): {exc}")
    except PLCActionOutcomeUnknown as exc:
        elapsed = asyncio.get_running_loop().time() - t0
        check("outage_ends_as_outcome_unknown",
              0.25 <= elapsed < 3.0 and "停滞" in str(exc) and drv2.read_fail_count >= 2,
              f"elapsed={elapsed:.2f}s fails={drv2.read_fail_count} {exc}")

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
