"""沙盒气缸类工序离线测试 (阶段③ D 步)
========================================
功能:
    验证 Collect / StagingA / Pump 三工位的工序复刻。重点是**此前不可达的错误分支**:
      ① A23 缩回到位那一刻缺瓶 -> ErrorCode 201 (真机同码; 此前沙盒无条件 DONE);
      ② 有瓶时 A23 走完升降与下压置位;
      ③ A21/A43 夹持一开一合各自等到位反馈;
      ④ StagingA 24/25 写定位气缸并推段号 1/24|25/99;
      ⑤ Pump 10/20 经引用计数槽驱动真空泵机构;
      ⑥ 未登记码回 REJECTED。

    瓶的有无由 sensors 合成层从**物料账本的座位账**推导 —— 于是"往收集工位放一只瓶"
    在沙盒里就是一次 payload_seat 记账, 与真机的传感器语义闭环。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_sim_cylinders_offline.py -q
"""

from __future__ import annotations

import asyncio
import socket
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.mock.behavior.cylinders import read_feedback  # noqa: E402
from eit_ptlc.mock.plc_server import mock_read, mock_write  # noqa: E402
from eit_ptlc.runtime.material_store import STATE_FRESH  # noqa: E402
from eit_ptlc.runtime.sim_stack import build_sim_stack  # noqa: E402

_CONFIG_DIR = _PKG / "config"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestCylinderStations(unittest.TestCase):
    """三工位的工序 (起真沙盒, 走真实执行链)."""

    def test_end_to_end(self):
        asyncio.run(self._exercise())

    async def _exercise(self) -> None:
        config = load_config(_CONFIG_DIR / "app.yaml")
        registry = ActionRegistry.load(_CONFIG_DIR / "actions")
        stack = await build_sim_stack(
            config, registry=registry,
            resolve_script=lambda name: (_ for _ in ()).throw(KeyError(name)),
            mode_provider=lambda: "DEBUG",
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/cyl-test/",
            time_scale=20.0,
        )
        try:
            await self._check_clamp_cycle(stack)
            await self._check_lift_press_without_bottle(stack)
            await self._check_lift_press_with_bottle(stack)
            await self._check_staging_a_locators(stack)
            await self._check_vacuum_pump(stack)
            await self._check_unknown_code_rejected(stack)
        finally:
            await stack.stop()

    async def _fb(self, stack, mech_id: str, which: str):
        return await read_feedback(stack.server, stack.manual_map,
                                   stack._manual_paths, mech_id, which)

    async def _set_bottle(self, stack, present: bool) -> None:
        """经物料账本让收集工位"有瓶/无瓶", 再等传感器合成层刷一拍."""
        if present:
            stack.material_store.mark_plate("bottle", 1, STATE_FRESH)
            stack.material_store.seat_payload_manually("collect-bottle", "bottle", 1, 1)
        else:
            stack.material_store.clear_payload_seat("collect-bottle")
        for _ in range(20):
            await asyncio.sleep(0.05)
            ix8 = int(await mock_read(stack.server, "IX8") or 0)
            if bool(ix8 >> 1 & 1) == present:
                return
        self.fail(f"传感器合成层未反映瓶位变化 (期望 present={present})")

    async def _check_clamp_cycle(self, stack) -> None:
        """A21 夹紧 / A43 松开: 各自写自动位并等到位反馈."""
        result = await stack.executor.execute("collect.clamp", {}, current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE")
        self.assertTrue(await self._fb(stack, "col_clamp", "fb_on"),
                        "夹紧后动点反馈应成立 (manual FSM 复刻 FB_cylinder)")

        result = await stack.executor.execute("collect.release_clamp", {},
                                              current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE")
        self.assertTrue(await self._fb(stack, "col_clamp", "fb_off"))

    async def _check_lift_press_without_bottle(self, stack) -> None:
        """A23 缺瓶 -> 201: 此前沙盒对任何动作码都无条件 DONE, 这条分支从不可达."""
        await self._set_bottle(stack, False)
        result = await stack.executor.execute("collect.lift_press", {},
                                              current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.ERROR")
        self.assertEqual(int(result.error_code), 201,
                         f"缺瓶应报 201, 实际 {result.error_code} {result.message}")

    async def _check_lift_press_with_bottle(self, stack) -> None:
        """有瓶时走完: 升降到动点 + 下压置位 (下压不等到位, 该气缸无动点传感器)."""
        await self._set_bottle(stack, True)
        result = await stack.executor.execute("collect.lift_press", {},
                                              current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE",
                         f"有瓶时应 DONE: {result.message}")
        self.assertTrue(await self._fb(stack, "col_lift", "fb_on"), "升降应到动点")

        # 复位伸出: 下压回原点 -> 升降回原点 -> 伸缩伸出 (三段有序)
        result = await stack.executor.execute("collect.transport_extend", {},
                                              current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE")
        self.assertTrue(await self._fb(stack, "col_extend", "fb_on"))

    async def _check_staging_a_locators(self, stack) -> None:
        """StagingA 24/25: 写定位气缸目标态并推段号 (写完即 DONE 不读反馈)."""
        result = await stack.executor.execute("staging_a.locator_a", {"target": True},
                                              current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE")
        self.assertEqual(int(await mock_read(stack.server, "StagingA_L2_Step")), 99,
                         "完成时段号应停在 99 (与 ST 一致)")

    async def _check_vacuum_pump(self, stack) -> None:
        """Pump 10/20: 经引用计数槽驱动真空泵机构 (聚合语义与 PLC_Pump_泵管理 同)."""
        result = await stack.executor.execute("pump.vacuum_on", {}, current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE")
        self.assertTrue(await self._fb(stack, "pump_vacuum", "fb_on") is not False,
                        "开泵后真空泵机构应被驱动")

        result = await stack.executor.execute("pump.vacuum_off", {}, current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.DONE")

    async def _check_unknown_code_rejected(self, stack) -> None:
        """未登记码回 REJECTED (Collect 的未知码是 101)."""
        await mock_write(stack.server, "Collect_L2_ActionCode", 88)
        await mock_write(stack.server, "Collect_L2_RequestSeq", 7001)
        await mock_write(stack.server, "Collect_L2_Start", True)
        state = 0
        for _ in range(100):
            await asyncio.sleep(0.05)
            state = int(await mock_read(stack.server, "Collect_L2_State"))
            if state in (20, 30, 40):
                break
        await mock_write(stack.server, "Collect_L2_Start", False)
        self.assertEqual(state, 30, "未登记码必须 REJECTED")
        self.assertEqual(int(await mock_read(stack.server, "Collect_L2_ErrorCode")), 101)


if __name__ == "__main__":
    unittest.main(verbosity=2)
