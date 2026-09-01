"""沙盒状态读写面的离线测试
============================
功能:
    钉住三条不变式:
      ① **读写面同构** —— state_snapshot 的 mechanisms 键集里每个 id 都写得动
         (PLC 气缸走 mechanisms, 机器人末端走 robot.effectors)。此前 rob_* 在
         mechanism_state 事件面里有、REST 面按"未知执行器 id"拒、前端面板还会过滤掉,
         三处不一致;
      ② **单写者在 API 表面自己说话** —— 板仓张数的写入被显式拒绝, 且 reason 里
         写出正确入口, 而不是靠文档约定;
      ③ **传感器位不重算** —— 观测面反解出来的位与合成写进 OPC 的字节逐位相等,
         于是"我看到的"和"动作看到的"是同一个东西。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest \
        eit_ptlc/tests/test_sim_state_surface_offline.py -q
"""

from __future__ import annotations

import asyncio
import socket
import unittest
from pathlib import Path

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.config.loader import load_config
from eit_ptlc.mock.behavior.sensors import SENSOR_BYTES, decode_bytes
from eit_ptlc.mock.plc_server import mock_read
from eit_ptlc.runtime import material_audit
from eit_ptlc.runtime.sim_stack import build_sim_stack

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _free_port() -> int:
    """借一个空闲端口 (沙盒的 SANDBOX_URL 端口是单例常量, 现场会被 /3d/sim 占住)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestSimStateSurface(unittest.TestCase):
    """状态读写面 (一次建栈跑完全部断言, 建栈成本高)."""

    def test_end_to_end(self):
        asyncio.run(self._exercise())

    async def _exercise(self) -> None:
        config = load_config(_CONFIG_DIR / "app.yaml")
        registry = ActionRegistry.load(_CONFIG_DIR / "actions")
        stack = await build_sim_stack(
            config, registry=registry,
            resolve_script=lambda name: (_ for _ in ()).throw(KeyError(name)),
            mode_provider=lambda: "DEBUG",
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/state-test/",
            time_scale=20.0,
        )
        try:
            await self._check_mechanisms_are_writable(stack)
            await self._check_magazine_count_is_rejected(stack)
            await self._check_feedlift_homed_is_settable(stack)
            await self._check_feed_rack_is_settable(stack)
            await self._check_pump_phase_is_settable(stack)
            await self._check_sensor_bits_match_the_bytes(stack)
            await self._check_tool_bits_agree_with_the_audit(stack)
            await self._check_ledger_and_model_never_diverge(stack)
        finally:
            await stack.stop()

    async def _check_mechanisms_are_writable(self, stack) -> None:
        """读面 mechanisms 里的每个 id 都写得动 —— 读写面同构是本段的全部意义.

        方向只有这一个: **发布了就必须写得动**。反过来不成立且不该成立 ——
        rob_suction 在被命令过之前不发布 (它没有 CAD 基准位, 发一个推定态就是撒谎;
        对比 rob_flip_suction 有基准位, 故未命令时也发布), 但它一直是可写的。
        """
        from eit_ptlc.driver.robot_transport import MountedTool
        stack.robot_transport.set_mounted_tool(MountedTool(1))

        snapshot = await stack.state_snapshot()
        ids = sorted(snapshot["mechanisms"])
        self.assertTrue(ids, "mechanisms 段不该为空")
        self.assertIn("rob_flip_suction", ids, "挂 1 号刀后翻转应出现在 mechanisms 里")

        for mech_id in ids:
            if mech_id.startswith("rob_"):
                patch = {"robot": {"effectors": {mech_id: True}}}
                path = f"robot.effectors.{mech_id}"
            else:
                patch = {"mechanisms": {mech_id: False}}
                path = f"mechanisms.{mech_id}"
            result = await stack.apply_state(patch)
            self.assertEqual(result["rejected"], [],
                             f"读面发布了 {mech_id} 却写不动: {result['rejected']}")
            self.assertIn(path, result["applied"])

        # 吸盘: 写得动, 且写完就进读面 (从此可跨刷新恢复"还带着电")
        result = await stack.apply_state({"robot": {"effectors": {"rob_suction": True}}})
        self.assertEqual(result["rejected"], [], f"吸盘应可写: {result['rejected']}")
        snapshot = await stack.state_snapshot()
        self.assertIn("rob_suction", snapshot["mechanisms"],
                      "命令过之后吸盘必须出现在读面里")
        await stack.apply_state({"robot": {"effectors": {"rob_suction": False}}})

        bogus = await stack.apply_state({"mechanisms": {"nope": True}})
        self.assertTrue(bogus["rejected"], "未知机构 id 必须落 rejected")

        # 裸腕时末端不可写, 且 reason 要给出可执行的下一步
        stack.robot_transport.set_mounted_tool(MountedTool(0))
        bare = await stack.apply_state({"robot": {"effectors": {"rob_suction": True}}})
        self.assertEqual(bare["applied"], [])
        self.assertIn("robot.tool", bare["rejected"][0]["reason"])
        stack.robot_transport.set_mounted_tool(MountedTool(1))

        # 同一 patch 里"先换刀再动末端"必须成立 (次序不变式)
        combo = await stack.apply_state(
            {"robot": {"tool": 2, "effectors": {"rob_grip_plate96": True}}})
        self.assertEqual(combo["rejected"], [],
                         f"同一 patch 内换刀应先于末端生效: {combo['rejected']}")

    async def _check_magazine_count_is_rejected(self, stack) -> None:
        """板仓张数在状态面被拒, 且 reason 指出唯一写者 (账本)."""
        result = await stack.apply_state({"feedlift": {"feed": {"count": 5}}})
        self.assertEqual(result["applied"], [])
        self.assertEqual(len(result["rejected"]), 1)
        reason = result["rejected"][0]["reason"]
        self.assertIn("/api/sim/materials/magazine", reason,
                      f"拒绝理由应写出正确入口, 实际: {reason}")

    async def _check_feedlift_homed_is_settable(self, stack) -> None:
        """bHomed 是模型独有量, 也是沙盒里唯一能走到 A10 错误码 308 的开关."""
        result = await stack.apply_state({"feedlift": {"feed": {"homed": False}}})
        self.assertIn("feedlift.feed.homed", result["applied"])
        self.assertFalse(stack.feedlift_model.homed["feed"])

        init = await stack.executor.execute("feedlift.init", {}, current_mode="DEBUG")
        self.assertEqual(str(init.status), "ActionStatus.ERROR")
        self.assertEqual(int(init.error_code), 308,
                         f"未回零时 A10 应报 308, 实际 {init.error_code}")

        await stack.apply_state({"feedlift": {"feed": {"homed": True}}})
        self.assertTrue(stack.feedlift_model.homed["feed"])

    async def _check_feed_rack_is_settable(self, stack) -> None:
        """上样料架两处是没有软件账的现场事实, 从写死 True 改为可设."""
        result = await stack.apply_state({"site": {"feed_rack": {"1": False}}})
        self.assertIn("site.feed_rack.1", result["applied"])
        await asyncio.sleep(0.3)
        ix9 = int(await mock_read(stack.server, "IX9"))
        self.assertFalse(ix9 >> 0 & 1, "置 False 后 IX9.0 应落位")

        await stack.apply_state({"site": {"feed_rack": {"1": True}}})
        await asyncio.sleep(0.3)
        ix9 = int(await mock_read(stack.server, "IX9"))
        self.assertTrue(ix9 >> 0 & 1)

        bad = await stack.apply_state({"site": {"feed_rack": {"9": True}}})
        self.assertTrue(bad["rejected"], "料架只有 1/2 两处")

    async def _check_pump_phase_is_settable(self, stack) -> None:
        """泵相位可设 —— "吸了一半停电重开"是个真实初态, 沙盒要能表达它.

        此前 pumps 只在 state_snapshot 出现, apply_state 里一行都没有 (只读不可写),
        这是"S 缺项"的一例: 状态向量里没有的量, 就无法从它出发推演。
        """
        pump_id = sorted(stack.pumps)[0]
        result = await stack.apply_state(
            {"pumps": {pump_id: {"plunger_ml": 12.5, "valve_port": 3}}})
        self.assertEqual(result["rejected"], [], f"泵相位应可写: {result['rejected']}")
        self.assertIn(f"pumps.{pump_id}", result["applied"])

        snapshot = await stack.state_snapshot()
        self.assertAlmostEqual(snapshot["pumps"][pump_id]["plunger_ml"], 12.5, places=3)
        self.assertEqual(snapshot["pumps"][pump_id]["valve_port"], 3)

        # 夹逼到满程 (与 mock/behavior/pump 的 6000 步同源)
        await stack.apply_state({"pumps": {pump_id: {"plunger_ml": 999.0}}})
        snapshot = await stack.state_snapshot()
        self.assertAlmostEqual(snapshot["pumps"][pump_id]["plunger_ml"], 25.0, places=3)

        bogus = await stack.apply_state({"pumps": {"NOPE": {"plunger_ml": 1.0}}})
        self.assertTrue(bogus["rejected"], "未知泵 id 必须落 rejected")
        self.assertIn("未知泵 id", bogus["rejected"][0]["reason"])

        bad_port = await stack.apply_state({"pumps": {pump_id: {"valve_port": 0}}})
        self.assertTrue(bad_port["rejected"], "阀口号 0 应被拒")

        # 忙时拒写: 直写会与积分器打架, 且下一拍就被覆盖 —— 是个假装生效的写
        stack.pumps[pump_id].busy = True
        try:
            busy = await stack.apply_state({"pumps": {pump_id: {"plunger_ml": 1.0}}})
            self.assertTrue(busy["rejected"], "泵忙时必须拒绝直写")
        finally:
            stack.pumps[pump_id].busy = False
        await stack.apply_state({"pumps": {pump_id: {"plunger_ml": 0.0}}})

    async def _check_sensor_bits_match_the_bytes(self, stack) -> None:
        """观测面反解 == 合成写进 OPC 的字节 (共读一张 BIT_SPECS 表的护栏)."""
        await asyncio.sleep(0.3)
        values = {name: int(await mock_read(stack.server, name)) for name in SENSOR_BYTES}
        for entry in decode_bytes(values):
            raw = values[entry["byte"]]
            self.assertEqual(entry["on"], bool(raw >> entry["bit"] & 1),
                             f"位 {entry['name']} 反解与字节不符")
        self.assertEqual(values["IX11"], 0, "料库 12 路应恒 0 (真机未供电)")
        self.assertEqual(values["IX12"] & 0x0F, 0, "IX12 低 4 位属料库, 应恒 0")

    async def _check_tool_bits_agree_with_the_audit(self, stack) -> None:
        """IX12.4-6 随挂刀变化, 且与 material_audit 的同一条推定不打架."""
        from eit_ptlc.driver.robot_transport import MountedTool
        for tool in (0, 1, 2):
            stack.robot_transport.set_mounted_tool(MountedTool(tool))
            await asyncio.sleep(0.3)
            ix12 = int(await mock_read(stack.server, "IX12"))
            bits = [bool(ix12 >> b & 1) for b in (4, 5, 6)]
            self.assertEqual(bits, [slot != tool for slot in (1, 2, 3)],
                             f"挂 {tool} 号刀时刀架检测位应是"
                             f"{[slot != tool for slot in (1, 2, 3)]}")
            row = material_audit.tool_state_row(ix12, tool)
            self.assertEqual(row["severity"], material_audit.SEV_OK,
                             f"沙盒合成与审查层用同一条推定, 不该互判不符: {row}")

    async def _check_ledger_and_model_never_diverge(self, stack) -> None:
        """账面写完即回灌; 审查层的仓底核对应恒 ok —— 本次 P0 缺陷的常驻探测器."""
        stack.material_store.set_magazine("feed", 11)
        stack.material_store.set_magazine("waste", 4)
        await asyncio.sleep(0.3)
        self.assertEqual(stack.feedlift_model.counts, {"feed": 11, "waste": 4})

        ix8 = int(await mock_read(stack.server, "IX8"))
        magazines = (await asyncio.to_thread(stack.material_store.grid))["magazines"]
        rows = material_audit.magazine_bottom_rows(ix8, magazines)
        bad = [row for row in rows if row["severity"] != material_audit.SEV_OK]
        self.assertEqual(bad, [], f"账面与仓底接近开关应一致, 不一致行: {bad}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
