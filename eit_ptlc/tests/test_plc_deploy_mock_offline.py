"""PLC 完整下载安全握手的配置与 Mock 同构测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from eit_ptlc.config.loader import load_plc_nodes
from eit_ptlc.controller.plc_controller import (
    PLCActionError,
    PLCActionState,
    PLCDeployRejected,
    PlcController,
)
from eit_ptlc.driver.opcua_driver import OpcUaDriver
from eit_ptlc.mock.plc_server import (
    build_mock_server,
    mock_read,
    mock_write,
    run_deploy_fsm,
    run_l2_fsm,
)


_NODES = Path(__file__).resolve().parent.parent / "config" / "plc_nodes.yaml"
_URL = "opc.tcp://127.0.0.1:48507/eit_ptlc/mock-deploy/"


def test_plc_deploy_and_startup_node_contract() -> None:
    node_map = load_plc_nodes(_NODES)
    expected = {
        "PLC_Deploy_RequestSeq": ("Int32", 0),
        "PLC_Deploy_Start": ("Boolean", 0),
        "PLC_Deploy_Reset": ("Boolean", 0),
        "PLC_Deploy_CommitSeq": ("Int32", 0),
        "PLC_Deploy_State": ("Int16", 0),
        "PLC_Deploy_AcceptedSeq": ("Int32", 0),
        "PLC_Deploy_ErrorCode": ("Int16", 0),
        "PLC_Startup_State": ("Int16", 0),
        "PLC_Startup_ErrorCode": ("Int16", 0),
        "PLC_Ready": ("Boolean", 0),
        "PLC_Startup_AlarmInhibit": ("Boolean", 0),
        "PLC_HandWheel_Active": ("Boolean", 0),
        "PLC_Axis_CommOperational": ("Boolean", 11),
        "PLC_Axis_FaultSource": ("Int16", 11),
        "PLC_Axis_FaultCode": ("Int32", 11),
    }
    actual = {
        name: (node_map.nodes[name].var_type, node_map.nodes[name].array_len)
        for name in expected
    }
    assert actual == expected


async def _wait_value(server, name: str, expected, timeout: float = 1.0) -> None:
    async def _poll() -> None:
        while await mock_read(server, name) != expected:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=timeout)


async def _exercise_mock_deploy() -> None:
    node_map = load_plc_nodes(_NODES)
    server = await build_mock_server(_URL, node_map)
    async with server:
        assert int(await mock_read(server, "PLC_Startup_State")) == 60
        assert await mock_read(server, "PLC_Ready") is True
        assert list(await mock_read(server, "PLC_Axis_CommOperational")) == [True] * 11
        assert list(await mock_read(server, "PLC_Axis_FaultSource")) == [0] * 11
        assert list(await mock_read(server, "PLC_Axis_FaultCode")) == [0] * 11

        stop = asyncio.Event()
        task = asyncio.create_task(run_deploy_fsm(server, stop, tick=0.005))
        driver = OpcUaDriver(_URL, node_map, reconnect_wait_timeout=1.0)
        await driver.connect()
        controller = PlcController(driver, poll_interval=0.005, action_timeout=1.0)
        try:
            assert await controller.sampling_free_move_active() is False
            await mock_write(server, "Sampling_Servo_FreeMove", True)
            assert await controller.sampling_free_move_active() is True
            await mock_write(server, "Sampling_Servo_FreeMove", False)

            prepared = await controller.prepare_for_deploy(timeout=1.0)
            assert prepared["state"] == 20
            assert prepared["accepted_seq"] == prepared["request_seq"]
            assert int(await mock_read(server, "PLC_Deploy_ErrorCode")) == 0

            await controller.reset_deploy(pulse_s=0.02, timeout=1.0)
            await _wait_value(server, "PLC_Deploy_State", 0)
            # AcceptedSeq is an acknowledgement watermark, not transient state.
            assert int(await mock_read(server, "PLC_Deploy_AcceptedSeq")) == prepared["request_seq"]
        finally:
            await driver.disconnect()
            stop.set()
            await task


def test_mock_defaults_ready_and_prepare_handshake() -> None:
    asyncio.run(_exercise_mock_deploy())


async def _exercise_mock_deploy_failures() -> None:
    node_map = load_plc_nodes(_NODES)
    url = "opc.tcp://127.0.0.1:48508/eit_ptlc/mock-deploy-failures/"
    server = await build_mock_server(url, node_map)
    async with server:
        stop = asyncio.Event()
        task = asyncio.create_task(run_deploy_fsm(server, stop, tick=0.005, prepare_ticks=40))
        driver = OpcUaDriver(url, node_map, reconnect_wait_timeout=1.0)
        await driver.connect()
        controller = PlcController(driver, poll_interval=0.005, action_timeout=1.0)
        try:
            # 正在执行的 L2 动作必须明确拒绝下载准备，不能由握手隐式中止。
            await mock_write(server, "Sampling_L2_State", 10)
            try:
                await controller.prepare_for_deploy(timeout=1.0)
            except PLCDeployRejected as exc:
                assert int(exc.state) == 30
                assert exc.error_code == 1
            else:  # pragma: no cover - 失败时给出比裸超时更明确的断言
                raise AssertionError("busy L2 must reject deploy preparation")
            await controller.reset_deploy(pulse_s=0.02, timeout=1.0)
            await mock_write(server, "Sampling_L2_State", 0)

            # PREPARING 是可观察阶段；该阶段通信丢失只产生准备失败，不会伪装成可下载。
            await mock_write(server, "PLC_Deploy_RequestSeq", 77)
            await mock_write(server, "PLC_Deploy_Start", True)
            await _wait_value(server, "PLC_Deploy_State", 10)
            comm = [True] * 11
            comm[4] = False
            await mock_write(server, "PLC_Axis_CommOperational", comm)
            await _wait_value(server, "PLC_Deploy_State", 40)
            assert int(await mock_read(server, "PLC_Deploy_ErrorCode")) == 5

            # Start=TRUE 表示请求方持有准备许可，此时 Reset 不能被另一写者抢占。
            await mock_write(server, "PLC_Deploy_Reset", True)
            await asyncio.sleep(0.03)
            assert int(await mock_read(server, "PLC_Deploy_State")) == 40
            await mock_write(server, "PLC_Deploy_Start", False)
            await _wait_value(server, "PLC_Deploy_State", 0)
            await mock_write(server, "PLC_Deploy_Reset", False)
            await mock_write(server, "PLC_Axis_CommOperational", [True] * 11)

            # 合法取消顺序：先撤销 Start，再脉冲 Reset；AcceptedSeq 保留作确认水位线。
            await asyncio.sleep(0.02)  # 让 FSM 观察 Start 下降沿
            await mock_write(server, "PLC_Deploy_RequestSeq", 78)
            await mock_write(server, "PLC_Deploy_Start", True)
            await _wait_value(server, "PLC_Deploy_State", 10)
            await mock_write(server, "PLC_Deploy_Start", False)
            await mock_write(server, "PLC_Deploy_Reset", True)
            await _wait_value(server, "PLC_Deploy_State", 0)
            assert int(await mock_read(server, "PLC_Deploy_AcceptedSeq")) == 78
            await mock_write(server, "PLC_Deploy_Reset", False)

            # SAFE 经同序号 Commit 后进入不可由普通 HMI Reset 撤销的 COMMITTED。
            await asyncio.sleep(0.02)
            await mock_write(server, "PLC_Deploy_RequestSeq", 79)
            await mock_write(server, "PLC_Deploy_Start", True)
            await _wait_value(server, "PLC_Deploy_State", 20)
            await mock_write(server, "PLC_Deploy_CommitSeq", 79)
            await _wait_value(server, "PLC_Deploy_State", 25)
            comm = [True] * 11
            comm[0] = False
            await mock_write(server, "PLC_Axis_CommOperational", comm)
            await _wait_value(server, "PLC_Deploy_ErrorCode", 5)
            assert int(await mock_read(server, "PLC_Deploy_State")) == 25
            await mock_write(server, "PLC_Axis_CommOperational", [True] * 11)
            await mock_write(server, "PLC_Deploy_Start", False)
            await mock_write(server, "PLC_Deploy_Reset", True)
            await asyncio.sleep(0.03)
            assert int(await mock_read(server, "PLC_Deploy_State")) == 25

            # 仅明确确认 worker 尚未下载的恢复路径可先清 CommitSeq，再退出占位。
            await mock_write(server, "PLC_Deploy_CommitSeq", 0)
            await _wait_value(server, "PLC_Deploy_State", 0)
        finally:
            await driver.disconnect()
            stop.set()
            await task


def test_mock_deploy_busy_comm_loss_and_cancel() -> None:
    asyncio.run(_exercise_mock_deploy_failures())


async def _exercise_mock_l2_global_gate() -> None:
    node_map = load_plc_nodes(_NODES)
    url = "opc.tcp://127.0.0.1:48509/eit_ptlc/mock-l2-deploy-gate/"
    server = await build_mock_server(url, node_map)
    async with server:
        stop = asyncio.Event()
        task = asyncio.create_task(run_l2_fsm(server, "Sampling", stop, tick=0.005))
        driver = OpcUaDriver(url, node_map, reconnect_wait_timeout=1.0)
        await driver.connect()
        controller = PlcController(
            driver,
            poll_interval=0.005,
            action_timeout=1.0,
            stall_timeout=0.5,
            soft_recheck=0.05,
        )
        try:
            # 启动未就绪时，L2 请求应以明确、可重试的 190 拒绝，不得进入 RUNNING。
            await mock_write(server, "PLC_Ready", False)
            try:
                await controller.execute("sampling", 20, {})
            except PLCActionError as exc:
                assert exc.result.state is PLCActionState.REJECTED
                assert exc.result.error_code == 190
                assert exc.result.retryable is True
            else:
                raise AssertionError("L2 action must be rejected while PLC is not ready")

            # PLC 已就绪但下载维护态占位时同样拒绝。
            await mock_write(server, "PLC_Ready", True)
            await mock_write(server, "PLC_Deploy_State", 25)
            try:
                await controller.execute("sampling", 20, {})
            except PLCActionError as exc:
                assert exc.result.state is PLCActionState.REJECTED
                assert exc.result.error_code == 190
            else:
                raise AssertionError("L2 action must be rejected during deploy maintenance")

            # 门控释放后原有 L2 正常路径保持不变。
            await mock_write(server, "PLC_Deploy_State", 0)
            result = await controller.execute("sampling", 20, {})
            assert result.state is PLCActionState.DONE
        finally:
            await driver.disconnect()
            stop.set()
            await task


def test_mock_l2_rejects_not_ready_and_deploy_maintenance() -> None:
    asyncio.run(_exercise_mock_l2_global_gate())
