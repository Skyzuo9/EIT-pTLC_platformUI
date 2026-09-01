"""沙盒 Develop 工序离线测试 (阶段③ E 步)
==========================================
功能:
    验证展缸工位的复刻:
      ① 31/32 放板缸按 Expand_Target_Tank 推导的组号/缸号选缸并等到位反馈;
      ② 26 抽吸四相走通 (沉降 -> 等废液走空 -> 吹扫), 走空判据以排液阀开着为前提;
      ③ 组被注入"持续有液"时抽吸走硬上限报 402 (真机同码);
      ④ 缸号越界报 102 (与真派发器一致);
      ⑤ 50/51 排液仍走既有后台 FSM 与桥 —— 行为层返回 None 交回, 没被新链吞掉;
      ⑥ 排液 FSM 接了时间倍率 (此前是全沙盒唯一不吃倍率的环节)。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_sim_develop_offline.py -q
"""

from __future__ import annotations

import asyncio
import socket
import sys
import time
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.mock.behavior.cylinders import read_feedback  # noqa: E402
from eit_ptlc.mock.plc_server import mock_read, mock_write  # noqa: E402
from eit_ptlc.runtime.sim_stack import build_sim_stack  # noqa: E402

_CONFIG_DIR = _PKG / "config"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestDevelopBehavior(unittest.TestCase):
    """展缸工序 (起真沙盒, 走真实执行链)."""

    def test_end_to_end(self):
        asyncio.run(self._exercise())

    async def _exercise(self) -> None:
        config = load_config(_CONFIG_DIR / "app.yaml")
        registry = ActionRegistry.load(_CONFIG_DIR / "actions")
        stack = await build_sim_stack(
            config, registry=registry,
            resolve_script=lambda name: (_ for _ in ()).throw(KeyError(name)),
            mode_provider=lambda: "DEBUG",
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/develop-test/",
            time_scale=20.0,
        )
        try:
            await self._check_plate_cylinder(stack)
            await self._check_suction_four_phases(stack)
            await self._check_suction_cap_timeout(stack)
            await self._check_tank_out_of_range(stack)
            await self._check_drain_still_goes_through_the_bridge(stack)
        finally:
            await stack.stop()

    async def _fb(self, stack, mech_id: str, which: str):
        return await read_feedback(stack.server, stack.manual_map,
                                   stack._manual_paths, mech_id, which)

    async def _check_plate_cylinder(self, stack) -> None:
        """5 号缸 -> 组2 缸1: 32 到动点, 31 回原点 (选缸按 Target_Tank 推导)."""
        result = await stack.executor.execute(
            "develop.plate_extend", {"target_tank": 5}, current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE", result.message)
        self.assertTrue(await self._fb(stack, "dev_t2_cyl1", "fb_on"),
                        "5 号缸应落到组2缸1 的动点")

        result = await stack.executor.execute(
            "develop.plate_retract", {"target_tank": 5}, current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE", result.message)
        self.assertTrue(await self._fb(stack, "dev_t2_cyl1", "fb_off"))

    async def _check_suction_four_phases(self, stack) -> None:
        """抽吸走通: 沉降 -> 走空判据满足 -> 吹扫 -> 关阀 (时长用小值加速).

        必须先跑 A21 润洗注液 —— 它开进液+排液阀并**保持到退出**供抽吸承接 (ST 明写)。
        单发抽吸时排液阀是关的, 走空判据永远不满足而走硬上限 402: 那不是缺陷,
        正是"判据是物理后果而不是自由计时器"的证据。
        """
        for node, value in (("Tank_Suction_Settle_S", 0.2), ("Tank_Suction_Empty_S", 0.2),
                            ("Tank_Suction_Blow_S", 0.2), ("Tank_Suction_Cap_S", 5.0)):
            await mock_write(stack.server, node, value)
        stack.server._eit_drain_wet_groups = set()      # 无注入 = 排液正常走空
        fill = await stack.executor.execute(
            "develop.rinse_fill", {"target_tank": 1}, current_mode="DEBUG")
        self.assertEqual(str(fill.status), "ActionStatus.DONE", fill.message)
        result = await stack.executor.execute(
            "develop.rinse_suction", {"target_tank": 1}, current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE", result.message)
        self.assertFalse(bool(await mock_read(stack.server, "Expand_Waste_Empty_G1")),
                         "收尾应把走空镜像量清掉 (不留下骗人的电平)")

    async def _check_suction_cap_timeout(self, stack) -> None:
        """该组废液线持续有液 -> 走空判据永不满足 -> 硬上限报 402."""
        for node, value in (("Tank_Suction_Settle_S", 0.1), ("Tank_Suction_Empty_S", 0.2),
                            ("Tank_Suction_Blow_S", 0.1), ("Tank_Suction_Cap_S", 0.6)):
            await mock_write(stack.server, node, value)
        await stack.executor.execute("develop.rinse_fill", {"target_tank": 1},
                                     current_mode="DEBUG")
        stack.server._eit_drain_wet_groups = {1}
        try:
            result = await stack.executor.execute(
                "develop.rinse_suction", {"target_tank": 1}, current_mode="DEBUG")
            self.assertEqual(str(result.status), "ActionStatus.ERROR")
            self.assertEqual(int(result.error_code), 402,
                             f"持续有液应报 402, 实际 {result.error_code} {result.message}")
        finally:
            stack.server._eit_drain_wet_groups = set()

    async def _check_tank_out_of_range(self, stack) -> None:
        """缸号越界 -> REJECTED 102 (与真派发器一致)."""
        await mock_write(stack.server, "Expand_Target_Tank", 99)
        await mock_write(stack.server, "Develop_L2_ActionCode", 32)
        await mock_write(stack.server, "Develop_L2_RequestSeq", 6001)
        await mock_write(stack.server, "Develop_L2_Start", True)
        state = 0
        for _ in range(100):
            await asyncio.sleep(0.05)
            state = int(await mock_read(stack.server, "Develop_L2_State"))
            if state in (20, 30, 40):
                break
        await mock_write(stack.server, "Develop_L2_Start", False)
        self.assertEqual(state, 30, "缸号越界必须 REJECTED")
        self.assertEqual(int(await mock_read(stack.server, "Develop_L2_ErrorCode")), 102)

    async def _check_drain_still_goes_through_the_bridge(self, stack) -> None:
        """50 排液仍走既有后台 FSM 与桥 (行为层返回 None 交回), 且吃时间倍率.

        判据取"真实耗时远小于名义时长": 名义 drain 2s + blow 1s + dry 0s = 3 秒,
        20 倍率下真实应在 1 秒内走完。这一条正是修掉"沙盒排液比真机还慢"的验收。
        """
        for node, value in (("Tank_Drain_S", 2.0), ("Tank_Drain_Cap_S", 6.0),
                            ("Tank_Blow_S", 1.0), ("Tank_Dry_S", 0.0)):
            await mock_write(stack.server, node, value)
        await mock_write(stack.server, "Tank_State", [0] * 8)
        await mock_write(stack.server, "Tank_Drain_Done", [False] * 8)
        stack.server._eit_drain_wet_groups = set()

        started = time.monotonic()
        result = await stack.executor.execute(
            "develop.drain", {"target_tank": 2}, current_mode="DEBUG")
        elapsed = time.monotonic() - started
        self.assertEqual(str(result.status), "ActionStatus.DONE", result.message)
        states = list(await mock_read(stack.server, "Tank_State"))
        self.assertIn(int(states[1]), (98, 99), "排液终态应是已排空")
        self.assertLess(elapsed, 2.5,
                        f"名义 3 秒的排液在 20 倍率下应远快于此, 实际 {elapsed:.2f}s "
                        f"—— 排液 FSM 未吃时间倍率")


if __name__ == "__main__":
    unittest.main(verbosity=2)
