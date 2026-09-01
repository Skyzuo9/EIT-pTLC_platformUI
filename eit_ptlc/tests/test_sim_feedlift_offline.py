"""沙盒 FeedLift 行为离线测试 (阶段③ C 步)
============================================
功能:
    验证虚拟 PLC 的 FeedLift 工序复刻:
      ① 板堆物理模型与 controller/feedlift_count 的换算互为逆运算 (纯函数级);
      ② 传感器合成层把"现场事实"变成 IX 位 (此前恒 0);
      ③ 空仓时前置门超时报 301 (真机同款), 有板时 clear→raise→probe 得到准确张数;
      ④ **取板全程**: 吸住后降轴让位扣一张, 二次 probe 的行程差恰好一个节距
         (expect_taken=1 通过) —— 这正是用户 2026-08-09 截图里跑不通的那条链;
      ⑤ 未登记动作码回 REJECTED。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_sim_feedlift_offline.py -q
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
from eit_ptlc.controller.feedlift_count import count_from_pos, load_calib  # noqa: E402
from eit_ptlc.mock.behavior.feedlift import (  # noqa: E402
    PHOTO_HYSTERESIS_MM, build_model)
from eit_ptlc.mock.plc_server import mock_read, mock_write  # noqa: E402
from eit_ptlc.runtime.sim_stack import build_sim_stack  # noqa: E402

_CONFIG_DIR = _PKG / "config"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestFeedLiftModel(unittest.TestCase):
    """板堆模型 (纯函数级, 不起沙盒)."""

    def setUp(self):
        self.model = build_model(_CONFIG_DIR, {"feed": ("上料仓", 30), "waste": ("下料仓", 30)},
                                 {"feed": 30, "waste": 0})

    def test_trigger_position_is_the_inverse_of_count_from_pos(self):
        """模型的触发位与上位机的张数换算互为逆运算 —— 两者用同一份标定, 不许各算各的."""
        calib = self.model.calib["feed"]
        self.assertTrue(calib.calibrated)
        self.assertEqual(self.model.calibration_source["feed"], "simulation_fixture")
        for count in (0, 1, 15, 29, 30):
            self.model.counts["feed"] = count
            z = self.model.z_trigger("feed")
            back, residual = count_from_pos(z, calib)
            self.assertEqual(back, count, f"{count} 张的触发位反算成了 {back} 张")
            self.assertLess(residual, 1e-6)

    def test_photo_and_proximity_semantics(self):
        """光电=顶板到位 (空仓恒假), 接近开关=仓内有板."""
        trigger = self.model.z_trigger("feed")
        self.assertTrue(self.model.photo("feed", trigger))
        self.assertTrue(self.model.photo("feed", trigger + 1.0))
        self.assertFalse(self.model.photo("feed", trigger - PHOTO_HYSTERESIS_MM))
        self.assertTrue(self.model.proximity("feed"))

        self.model.counts["feed"] = 0
        self.assertFalse(self.model.proximity("feed"), "空仓仓底开关必须为假")
        self.assertFalse(self.model.photo("feed", 999.0), "空仓没板可挡光, 光电恒假")

    def test_hysteresis_exceeds_stale_reading_guard(self):
        """回差必须大于陈旧读数守卫阈值, 否则正常逼近会被真机链判成陈旧读数."""
        from eit_ptlc.controller.feedlift_count import MIN_APPROACH_MM
        self.assertGreater(PHOTO_HYSTERESIS_MM, MIN_APPROACH_MM)


class TestFeedLiftBehavior(unittest.TestCase):
    """沙盒内的 FeedLift 工序 (起真沙盒, 走真实执行链)."""

    def test_end_to_end(self):
        asyncio.run(self._exercise())

    async def _exercise(self) -> None:
        config = load_config(_CONFIG_DIR / "app.yaml")
        registry = ActionRegistry.load(_CONFIG_DIR / "actions")
        stack = await build_sim_stack(
            config, registry=registry,
            resolve_script=lambda name: (_ for _ in ()).throw(KeyError(name)),
            mode_provider=lambda: "DEBUG",
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/feedlift-test/",
            time_scale=20.0,
        )
        try:
            await self._check_sensors_reflect_the_stack(stack)
            await self._check_empty_magazine_gate(stack)
            await self._check_probe_counts_thirty(stack)
            await self._check_take_one_plate(stack)
            await self._check_put_one_plate(stack)
            await self._check_full_waste_magazine_rejects(stack)
            await self._check_unknown_code_rejected(stack)
        finally:
            await stack.stop()

    async def _prepare(self, stack, count: int) -> None:
        """置张数并给合法搜索窗 (真机由上位机 preload 写入).

        **只写账本**: 模型由 set_magazine 的观察者回灌 (make_ledger_reflow)。此处曾经
        额外直写一行 stack.feedlift_model.counts["feed"] = count —— 那行夹具恰好补上了
        产品代码缺的回灌, 于是本文件全绿而现场 100% 报 301。删掉它, 本文件的每一条断言
        就都在替回灌链作证。
        """
        stack.material_store.set_magazine("feed", count)
        await mock_write(stack.server, "FeedLift_1Z_SearchLowTarget", 400.0)
        await mock_write(stack.server, "FeedLift_1Z_SearchHighTarget", 520.0)
        # 复位到规范 home (全轴 0) 再开跑, 与用户现场的起点一致
        await stack.reset_home()

    async def _check_sensors_reflect_the_stack(self, stack) -> None:
        """传感器合成: 仓底位随张数翻, 不再恒 0 (此前 preflight 必报空仓)."""
        from eit_ptlc.controller.feedlift_count import _IX8_PROX_BIT, preflight_gate
        await self._prepare(stack, 30)
        await asyncio.sleep(0.3)
        ix8 = int(await mock_read(stack.server, "IX8"))
        self.assertTrue(ix8 >> _IX8_PROX_BIT["feed"] & 1, "有板时仓底接近开关必须为 1")
        self.assertTrue(preflight_gate("feed", ix8)["ok"], "有板时 preflight 应通过")

        # 经账本清零 (而不是直改模型): 顺带钉住 账本 -> 回灌 -> 模型 -> 传感器 整条链
        stack.material_store.set_magazine("feed", 0)
        await asyncio.sleep(0.3)
        ix8 = int(await mock_read(stack.server, "IX8"))
        self.assertFalse(ix8 >> _IX8_PROX_BIT["feed"] & 1, "空仓时仓底开关必须为 0")
        self.assertFalse(preflight_gate("feed", ix8)["ok"], "空仓时 preflight 应拦下")

    async def _check_empty_magazine_gate(self, stack) -> None:
        """空仓跑 feed_raise: 前置门 10 秒超时报 301 (与真机同码)."""
        await self._prepare(stack, 0)
        result = await stack.executor.execute("feedlift.feed_raise", {},
                                              current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.ERROR")
        self.assertEqual(int(result.error_code), 301,
                         f"空仓应报 301 (前置门未满足), 实际 {result.error_code} {result.message}")

    async def _check_probe_counts_thirty(self, stack) -> None:
        """满仓 clear→raise→probe 得 30 张; 轴停在该张数的触发位上."""
        await self._prepare(stack, 30)
        for action in ("feedlift.feed_clear", "feedlift.feed_raise"):
            result = await stack.executor.execute(action, {}, current_mode="DEBUG")
            self.assertEqual(str(result.status), "ActionStatus.DONE", f"{action} 应 DONE")
        z = float(await mock_read(stack.server, "FeedLift_1Z_ActPos"))
        self.assertAlmostEqual(z, stack.feedlift_model.z_trigger("feed"), places=3)

        probe = await stack.executor.execute(
            "feedlift.probe_stack", {"magazine": "feed", "reconcile": True},
            current_mode="DEBUG")
        self.assertEqual(str(probe.status), "ActionStatus.DONE",
                         f"probe 失败: {probe.message}")
        self.assertEqual(int(probe.result["count"]), 30)
        self.assertLess(float(probe.result["residual"]), 0.05, "残差应接近 0")

    async def _check_take_one_plate(self, stack) -> None:
        """取板全程: 吸住→降轴让位 (扣一张) →再升→二次 probe 行程差恰好一个节距.

        这是用户 2026-08-09 截图里跑不通的那条链的核心判据 (expect_taken=1)。
        """
        await self._prepare(stack, 30)
        await stack.executor.execute("feedlift.feed_clear", {}, current_mode="DEBUG")
        await stack.executor.execute("feedlift.feed_raise", {}, current_mode="DEBUG")
        first = await stack.executor.execute(
            "feedlift.probe_stack", {"magazine": "feed", "reconcile": True},
            current_mode="DEBUG")
        z_prev = float(first.result["z_mm"])

        # 机器人吸住玻璃 (沙盒里直接置吸盘态: 本测试验的是 FeedLift 工序, 不是机器人链)
        from eit_ptlc.driver.robot_transport import ToolAction
        stack.robot.set_mounted_tool(1)
        await asyncio.to_thread(stack.robot.tool_action, ToolAction.SUCTION_ON)
        lower = await stack.executor.execute("feedlift.feed_lower", {}, current_mode="DEBUG")
        self.assertEqual(str(lower.status), "ActionStatus.DONE")
        self.assertEqual(stack.feedlift_model.counts["feed"], 29,
                         "吸住后降轴让位 = 板离堆, 模型应扣一张")

        await stack.executor.execute("feedlift.feed_raise", {}, current_mode="DEBUG")
        second = await stack.executor.execute(
            "feedlift.probe_stack",
            {"magazine": "feed", "z_prev": z_prev, "expect_taken": 1},
            current_mode="DEBUG")
        self.assertEqual(str(second.status), "ActionStatus.DONE",
                         f"二次 probe 失败 (expect_taken=1 不成立): {second.message}")
        self.assertEqual(int(second.result["count"]), 29)
        self.assertEqual(int(second.result["taken"]), 1)

    async def _check_put_one_plate(self, stack) -> None:
        """放板全程: A21 置 armed → 吸盘松开时下料仓 +1 → A22 埋料走一个节距.

        判据出自 specs/feedlift.yaml 的 A21 notes ("真正 +1 在放板(吸盘 ON->OFF 沿)时")。
        钉住"+1 必须发生在 A22 之前": 若改绑 A22 DONE, 埋料行程会从"一个节距 + 回差"
        缩成"只有回差", 随后 waste 侧 probe 的差分会量到错误节距。
        """
        from eit_ptlc.driver.robot_transport import ToolAction
        stack.material_store.set_magazine("waste", 3)
        await mock_write(stack.server, "FeedLift_2Z_SearchLowTarget", 400.0)
        await mock_write(stack.server, "FeedLift_2Z_SearchHighTarget", 520.0)
        await stack.reset_home()
        self.assertEqual(stack.feedlift_model.counts["waste"], 3, "账面应已回灌进模型")

        ready = await stack.executor.execute("feedlift.unload_ready", {},
                                             current_mode="DEBUG")
        self.assertEqual(str(ready.status), "ActionStatus.DONE",
                         f"A21 应 DONE (门刻意不查接近开关2): {ready.message}")
        self.assertTrue(stack.feedlift_model.waste_armed, "A21 DONE 应置 armed")
        z_before = float(await mock_read(stack.server, "FeedLift_2Z_ActPos"))

        stack.robot.set_mounted_tool(1)
        await asyncio.to_thread(stack.robot.tool_action, ToolAction.SUCTION_ON)
        await asyncio.sleep(0.2)
        await asyncio.to_thread(stack.robot.tool_action, ToolAction.SUCTION_OFF)
        await asyncio.sleep(0.3)
        self.assertEqual(stack.feedlift_model.counts["waste"], 4,
                         "吸盘松开 (armed 窗口内) 应让下料仓 +1")
        self.assertFalse(stack.feedlift_model.waste_armed, "+1 后应清 armed")

        bury = await stack.executor.execute("feedlift.unload_bury", {},
                                            current_mode="DEBUG")
        self.assertEqual(str(bury.status), "ActionStatus.DONE", f"A22 应 DONE: {bury.message}")
        z_after = float(await mock_read(stack.server, "FeedLift_2Z_ActPos"))
        pitch = stack.feedlift_model.calib["waste"].pitch_mm
        self.assertAlmostEqual(z_before - z_after, pitch + PHOTO_HYSTERESIS_MM, places=2,
                               msg="埋料行程应是一个节距 + 光电回差 —— 对不上说明 +1 "
                                   "发生在了 A22 之后")

    async def _check_full_waste_magazine_rejects(self, stack) -> None:
        """满仓 A21 报 302: Alarm.1 (下料机构已满料) 的沙盒推导生效."""
        stack.material_store.set_magazine("waste", 30)      # 容量上限, 拓扑真源
        await stack.reset_home()
        result = await stack.executor.execute("feedlift.unload_ready", {},
                                              current_mode="DEBUG")
        self.assertEqual(str(result.status), "ActionStatus.ERROR")
        self.assertEqual(int(result.error_code), 302,
                         f"满仓应报 302 (前置门未满足), 实际 {result.error_code}")

    async def _check_unknown_code_rejected(self, stack) -> None:
        """未登记动作码回 REJECTED —— 沙盒不替 PLC 圆谎 (此前任何码都 DONE)."""
        await mock_write(stack.server, "FeedLift_L2_ActionCode", 77)
        await mock_write(stack.server, "FeedLift_L2_RequestSeq", 9001)
        await mock_write(stack.server, "FeedLift_L2_Start", True)
        for _ in range(100):
            await asyncio.sleep(0.05)
            state = int(await mock_read(stack.server, "FeedLift_L2_State"))
            if state in (20, 30, 40):
                break
        await mock_write(stack.server, "FeedLift_L2_Start", False)
        self.assertEqual(state, 30, "未登记码必须 REJECTED")
        self.assertEqual(int(await mock_read(stack.server, "FeedLift_L2_ErrorCode")), 101)


if __name__ == "__main__":
    unittest.main(verbosity=2)
