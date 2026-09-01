"""PLC 控制器离线测试 (统一 L2 通道 vs Mock FSM)
=================================================
功能:
    启动 Mock OPC UA + Sampling L2 FSM, 验证 PlcController.execute 的下降沿启动 /
    终态返回 (DONE) / 拒绝 (REJECTED, retryable) / 故障 (ERROR, RECOVERY_REQUIRED) /
    序号单调 / snapshot / reset.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_plc_controller_offline
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from eit_ptlc.config.loader import load_plc_nodes
from eit_ptlc.controller.plc_controller import (
    PLCActionError,
    PLCActionOutcomeUnknown,
    PLCActionSafeState,
    PLCActionState,
    PlcController,
)
from eit_ptlc.driver.opcua_driver import OpcUaDriver
from eit_ptlc.mock.plc_server import build_mock_server, mock_read, mock_write, run_l2_fsm

_URL = "opc.tcp://127.0.0.1:48478/eit_ptlc/mock/"
_NODES = Path(__file__).resolve().parent.parent / "config" / "plc_nodes.yaml"


async def _run() -> int:
    node_map = load_plc_nodes(_NODES)
    server = await build_mock_server(_URL, node_map)
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    async with server:
        stop = asyncio.Event()
        # Sampling: 99->拒绝 98->故障 其余->完成; Collect: 50->卡死(RUNNING 永不推进); Develop: 慢动作(逐拍推进 Step)
        fsm = asyncio.create_task(run_l2_fsm(server, "Sampling", stop, reject_codes=(99,), error_codes=(98,)))
        fsm_collect = asyncio.create_task(run_l2_fsm(server, "Collect", stop, hang_codes=(50,)))
        fsm_develop = asyncio.create_task(run_l2_fsm(server, "Develop", stop, slow_ticks=15))
        # 独立卡死站: 供 per-action stall 覆盖用例 (与 Collect 的全局 stall 用例互不污染 IDLE)
        fsm_photo = asyncio.create_task(run_l2_fsm(server, "PhotoScrape", stop, hang_codes=(40,)))
        driver = OpcUaDriver(_URL, node_map, reconnect_wait_timeout=5.0, subscription_period_ms=20)
        await driver.connect()
        ctrl = PlcController(driver, poll_interval=0.02, action_timeout=5.0)
        # 看门狗专用: 小 stall_timeout 便于快速验证停滞判停; 绝对上限留足
        ctrl_wd = PlcController(driver, poll_interval=0.02, action_timeout=3.0, stall_timeout=0.5)
        try:
            # 正常完成 (action 10 = Sampling_Init)
            r = await ctrl.execute("sampling", 10)
            check("execute_done", r.ok and r.state is PLCActionState.DONE and r.request_seq == 1, str(r))

            # 拒绝路径 (retryable)
            try:
                await ctrl.execute("sampling", 99)
                check("execute_reject", False, "应抛 PLCActionError")
            except PLCActionError as exc:
                check("execute_reject", exc.result.state is PLCActionState.REJECTED and exc.result.retryable, str(exc.result))

            # 故障路径 (safe_state=RECOVERY_REQUIRED)
            try:
                await ctrl.execute("sampling", 98)
                check("execute_error", False, "应抛 PLCActionError")
            except PLCActionError as exc:
                check("execute_error",
                      exc.result.state is PLCActionState.ERROR
                      and exc.result.safe_state is PLCActionSafeState.RECOVERY_REQUIRED,
                      str(exc.result))

            # 序号单调: 第四次应为 seq=4
            r = await ctrl.execute("sampling", 10)
            check("seq_monotonic", r.request_seq == 4, f"seq={r.request_seq}")

            # snapshot
            snap = await ctrl.snapshot("sampling")
            check("snapshot", "State" in snap and "CompletedSeq" in snap, str(snap.keys()))

            # reset (脉冲不报错)
            await ctrl.reset("sampling")
            check("reset", True)

            # ── 看门狗核心修复: 慢动作(逐拍推进 Step, 远超 stall_timeout=0.5 的总时长)仍走到 DONE ──
            r = await ctrl_wd.execute("develop", 22)
            check("watchdog_slow_done", r.ok and r.state is PLCActionState.DONE, str(r))

            # ── 看门狗: 真卡死(接受后 RUNNING 永不推进)在 ~stall_timeout 后判结果不明确 ──
            t0 = asyncio.get_running_loop().time()
            try:
                await ctrl_wd.execute("collect", 50)
                check("watchdog_stall_detect", False, "应抛 PLCActionOutcomeUnknown")
            except PLCActionOutcomeUnknown as exc:
                elapsed = asyncio.get_running_loop().time() - t0
                check("watchdog_stall_detect", 0.4 <= elapsed < 3.0, f"elapsed={elapsed:.2f}s {exc}")

            # ── per-action stall 覆盖: 全局 stall 宽松(默认 60s)的控制器, 用 execute(stall_timeout=)
            #    收紧到 0.5s, 卡死动作应按 per-action 值在 ~0.5s 判停, 而非全局 60s / 5s 绝对上限。
            #    用独立卡死站 PhotoScrape(40), 不与上面 Collect 用例争 IDLE。 ──
            t0 = asyncio.get_running_loop().time()
            try:
                await ctrl.execute("photoscrape", 40, stall_timeout=0.5)
                check("watchdog_stall_override", False, "应抛 PLCActionOutcomeUnknown")
            except PLCActionOutcomeUnknown as exc:
                elapsed = asyncio.get_running_loop().time() - t0
                check("watchdog_stall_override", 0.4 <= elapsed < 3.0, f"elapsed={elapsed:.2f}s {exc}")

            # ── 卡死 RUNNING 后再派发: _prepare_idle 超时的报错必须引导操作员去设备页工位复位 ──
            #    PLC FSM 的 RUNNING 态只认 L2_Reset、不认 Start 落沿; 上面 PhotoScrape(40) 已把工位卡在
            #    RUNNING (Mock 忠实模拟), 此处再派发即触发 _prepare_idle 2s 超时, 断言报错带"复位/设备页"引导,
            #    使操作员知道调试坞 VM 复位无用、须去设备页脉冲 L2_Reset (清 L2 故障)。
            try:
                await ctrl.execute("photoscrape", 10)
                check("prepare_idle_reset_guidance", False, "应抛 TimeoutError (工位卡 RUNNING 回不了 IDLE)")
            except TimeoutError as exc:
                msg = str(exc)
                check("prepare_idle_reset_guidance",
                      "未回到 IDLE" in msg and "复位" in msg and "设备页" in msg, msg)

            # ── 驱动订阅->镜像: 外部写入经订阅推送更新镜像 (Rail 无 FSM, 隔离验证) ──
            await driver.add_subscription(["Rail_L2_State"])
            check("sub_seed", int(driver.cached("Rail_L2_State")) == 0, str(driver.cached("Rail_L2_State")))
            token = driver.change_token()
            await mock_write(server, "Rail_L2_State", 10)
            try:
                await asyncio.wait_for(driver.wait_change(token), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            check("sub_mirror", int(driver.cached("Rail_L2_State")) == 10, str(driver.cached("Rail_L2_State")))

            # ── 重连重订阅: _resubscribe_all 后镜像仍随变化更新 ──
            await driver._resubscribe_all()
            token = driver.change_token()
            await mock_write(server, "Rail_L2_State", 20)
            try:
                await asyncio.wait_for(driver.wait_change(token), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            check("resubscribe", int(driver.cached("Rail_L2_State")) == 20, str(driver.cached("Rail_L2_State")))
        finally:
            stop.set()
            await asyncio.gather(fsm, fsm_collect, fsm_develop, fsm_photo, return_exceptions=True)
            await driver.disconnect()

    print(f"\n共 12 用例, 失败 {len(failures)}")
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
