"""展缸资源管理器离线测试 (vs Mock + plc_controller 展缸辅助)
=============================================================
功能:
    验证 ResourceManager 迁移后: 展缸分配/绑定/释放/偏好/空闲查询, 及 plc_controller
    展缸数组辅助 (read_all_tank_states/read_tank_state/release_tank) 对 Mock 读写正确.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_resource_manager_offline
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from eit_ptlc.config.loader import load_plc_nodes
from eit_ptlc.controller.plc_controller import PlcController
from eit_ptlc.driver.opcua_driver import OpcUaDriver
from eit_ptlc.mock.plc_server import build_mock_server
from eit_ptlc.operation.resource_manager import ResourceManager

_URL = "opc.tcp://127.0.0.1:48481/eit_ptlc/mock/"
_NODES = Path(__file__).resolve().parent.parent / "config" / "plc_nodes.yaml"


async def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    node_map = load_plc_nodes(_NODES)
    server = await build_mock_server(_URL, node_map)
    async with server:
        driver = OpcUaDriver(_URL, node_map, reconnect_wait_timeout=5.0)
        await driver.connect()
        plc = PlcController(driver)
        try:
            states = await plc.read_all_tank_states()
            check("tank_states_len", len(states) == 8 and all(v == 0 for v in states), str(states))

            rm = ResourceManager(plc)
            t1 = await rm.allocate("S1")
            t2 = await rm.allocate("S2")
            check("allocate_first_two", t1 == 1 and t2 == 2, f"t1={t1} t2={t2}")
            check("binding", rm.get_tank_for_sample("S1") == 1 and rm.get_tank_for_sample("S2") == 2)

            t3 = await rm.allocate("S3", preferred_tank=5)
            check("preferred_alloc", t3 == 5, f"t3={t3}")

            await rm.release(1)
            check("release", rm.get_tank_for_sample("S1") is None and 1 in rm.idle_tanks(), str(rm.idle_tanks()))
            check("plc_tank_reset", (await plc.read_tank_state(1)) == 0)

            # 写入一个缸态再 sync, 验证 PLC->本地镜像
            await driver.write_array_element("Tank_State", 2, 40)  # DEVELOPING
            await rm.sync_states()
            check("sync_mirror", rm.get_tank_state(2).value == 40, str(rm.get_tank_state(2)))
        finally:
            await driver.disconnect()

    print(f"\n共 7 用例, 失败 {len(failures)}")
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
