"""OPC UA 驱动离线测试 (对 Mock 服务器)
========================================
功能:
    启动 Mock OPC UA 服务器, 用 OpcUaDriver 验证连接 / 标量读写 / 数组整体与单元素读写 /
    心跳 / 急停上升沿回调. 不依赖真机.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_opcua_driver_offline
期望:
    全部用例打印 PASS, 退出码 0.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from eit_ptlc.config.loader import load_plc_nodes
from eit_ptlc.driver import opcua_driver as od_mod
from eit_ptlc.driver.opcua_driver import OpcUaDriver, PLCState
from eit_ptlc.mock.plc_server import build_mock_server

_URL = "opc.tcp://127.0.0.1:48477/eit_ptlc/mock/"
_NODES = Path(__file__).resolve().parent.parent / "config" / "plc_nodes.yaml"


async def _run() -> int:
    node_map = load_plc_nodes(_NODES)
    server = await build_mock_server(_URL, node_map)
    failures: list[str] = []
    ncases = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ncases
        ncases += 1
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(f"{name}: {detail}")
            print(f"FAIL {name}: {detail}")

    estop_fired = asyncio.Event()

    async def on_estop() -> None:
        estop_fired.set()

    driver = OpcUaDriver(_URL, node_map, on_estop=on_estop, reconnect_wait_timeout=15.0)
    # 状态迁移轨迹 (断连注入用例断言经 RECONNECTING 回到 CONNECTED)
    states: list[PLCState] = []

    async def _on_state(state: PLCState) -> None:
        states.append(state)

    try:
        async with server:
            await driver.connect()
            driver.add_state_listener(_on_state)
            check("connect", driver.state == PLCState.CONNECTED, str(driver.state))

            # 标量布尔读写
            await driver.write_variable("collect_Enable", True)
            v = await driver.read_variable("collect_Enable")
            check("scalar_bool_rw", v is True, f"got {v!r}")

            # 标量整型读写 (Int16)
            await driver.write_variable("collect_Step", 30)
            v = int(await driver.read_variable("collect_Step"))
            check("scalar_int_rw", v == 30, f"got {v}")

            # 标量浮点读写 (Float)
            await driver.write_variable("g_pass_z", 5.5)
            v = float(await driver.read_variable("g_pass_z"))
            check("scalar_float_rw", abs(v - 5.5) < 1e-3, f"got {v}")

            # 字符串数组整体写 (补齐到声明长度 2)
            await driver.write_array("Sampling_clean_instructions", ["/1I1P480R;"])
            arr = await driver.read_array("Sampling_clean_instructions")
            check("string_array_pad", list(arr) == ["/1I1P480R;", ""], f"got {arr}")

            # Int16 数组整体写 (Tank_State, 8)
            await driver.write_array("Tank_State", [10, 20, 30, 40, 50, 60, 70, 80])
            arr = [int(x) for x in await driver.read_array("Tank_State")]
            check("int_array_rw", arr == [10, 20, 30, 40, 50, 60, 70, 80], f"got {arr}")

            # 数组单元素读改写 (1-based)
            await driver.write_array_element("Tank_State", 3, 99)
            el = int(await driver.read_array_element("Tank_State", 3))
            check("array_element_rw", el == 99, f"got {el}")
            arr = [int(x) for x in await driver.read_array("Tank_State")]
            check("array_element_isolation", arr == [10, 20, 99, 40, 50, 60, 70, 80], f"got {arr}")

            # 批量写
            await driver.write_many({"collect_count": 3, "Expand_Target_Tank": 5})
            check("write_many", int(await driver.read_variable("collect_count")) == 3
                  and int(await driver.read_variable("Expand_Target_Tank")) == 5)

            # 急停上升沿: 经服务器节点写 PLC_EStop=True, 心跳应在 ~0.3s 内触发回调
            estop_node = await _server_node(server, node_map, "PLC_EStop")
            from asyncua import ua
            await estop_node.write_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
            try:
                await asyncio.wait_for(estop_fired.wait(), timeout=2.0)
                check("estop_edge_callback", True)
            except asyncio.TimeoutError:
                check("estop_edge_callback", False, "on_estop 未在 2s 内触发")

        # ── 断连注入 (真机复现 "client is disconnected"): server 上下文退出 = PLC 掉线 ──
        # 在心跳 (3x100ms) 未必察觉的窗口内立即发起调用: 期望不向调用方泄漏 asyncua 原始
        # 断连异常, 而是触发重连迁移并阻塞; 替身 server 就位后守卫内重试成功。
        pending = asyncio.create_task(driver.read_variable("collect_Step"))
        await asyncio.sleep(0.5)   # 心跳判死 + 首轮退避 (1s) 期间起替身 server
        check("blip_state_reconnecting", PLCState.RECONNECTING in states,
              f"states={[s.value for s in states]}")
        server2 = await build_mock_server(_URL, node_map)
        async with server2:
            v = await asyncio.wait_for(pending, timeout=30.0)
            check("blip_read_survives", v is not None, f"got {v!r}")
            check("blip_reconnected_once",
                  driver.state == PLCState.CONNECTED and driver.reconnect_count == 1,
                  f"state={driver.state.value} count={driver.reconnect_count}")
            await driver.write_variable("collect_Step", 77)
            check("blip_post_reconnect_rw",
                  int(await driver.read_variable("collect_Step")) == 77)
    finally:
        await driver.disconnect()

    # ── 竞态窗口定向复现 (真机 "client is disconnected" 的确切路径) ──
    # 把心跳间隔拉长使其无法先行判死: server 停止后驱动状态仍 CONNECTED, 调用必踩
    # "asyncua 已死 / 状态机未察觉" 窗口 → 应由 _note_link_lost 迁移重连并在守卫内重试成功。
    hb_interval = od_mod.HEARTBEAT_INTERVAL
    od_mod.HEARTBEAT_INTERVAL = 3600.0
    driver3 = OpcUaDriver(_URL, node_map, reconnect_wait_timeout=15.0)
    try:
        server3 = await build_mock_server(_URL, node_map)
        async with server3:
            await driver3.connect()
            await driver3.read_variable("collect_Step")   # 连接可用基线
        check("race_state_still_connected", driver3.state == PLCState.CONNECTED,
              driver3.state.value)
        pending3 = asyncio.create_task(driver3.read_variable("collect_Step"))
        await asyncio.sleep(0.5)
        check("race_flipped_by_caller", driver3.state == PLCState.RECONNECTING,
              driver3.state.value)
        server4 = await build_mock_server(_URL, node_map)
        async with server4:
            v3 = await asyncio.wait_for(pending3, timeout=30.0)
            check("race_read_survives",
                  v3 is not None and driver3.reconnect_count == 1,
                  f"got {v3!r} count={driver3.reconnect_count}")
    finally:
        od_mod.HEARTBEAT_INTERVAL = hb_interval
        await driver3.disconnect()

    print(f"\n共 {ncases} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


async def _server_node(server, node_map, name: str):
    """从服务器侧按 gvl_path + name 取节点对象 (用于直接写值模拟 PLC)."""
    node = server.nodes.objects
    for part in node_map.gvl_path:
        node = await node.get_child(f"{await _ns(server)}:{part}")
    return await node.get_child(f"{await _ns(server)}:{name}")


async def _ns(server) -> int:
    return await server.get_namespace_index("eit_ptlc_mock")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
