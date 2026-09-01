"""沙盒"采纳真机账本后 FeedLift 能不能跑"的端到端离线测试
==========================================================
功能:
    钉死 账本 -> 板堆物理模型 的回灌链。这条链 2026-08-12 之前是断的:
    FeedLiftModel 的张数只在 build_sim_stack 那一刻从**还是空的** :memory: 账本取过
    一次初值, 而 adopt (以及 /api/sim/materials/magazine 人工盘点) 只改 SQLite,
    从不回写模型。于是仓底接近开关恒 FALSE, FeedLift 的四个 jog_search 动作
    全部 10 秒前置门超时报 301/302 —— 用户在 /3d/sim 上跑"上样-上料"看到的就是它。

    当时既有测试全绿, 因为 test_sim_feedlift_offline 的夹具**同时**直写了模型计数,
    恰好补上了产品代码缺的那一步。本文件不碰模型内部, 一律走真实 HTTP 路径。

为什么必须走 HTTP 而不是直调 import_rows:
    缺陷恰恰长在 adopt 路由与模型之间的接线上, 绕开路由就测不到。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest \
        eit_ptlc/tests/test_sim_adopt_feedlift_offline.py -q
"""

from __future__ import annotations

import asyncio
import socket
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from httpx import ASGITransport, AsyncClient

import eit_ptlc.runtime.bootstrap as bootstrap
from eit_ptlc.controller.feedlift_count import _IX8_PROX_BIT, preflight_gate
from eit_ptlc.driver.robot_transport import MountedTool, ToolAction
from eit_ptlc.mock.plc_server import mock_read, mock_write
from eit_ptlc.runtime.sim_stack import build_sim_stack
from eit_ptlc.tools.pump.profiles import set_pump_defaults_provider


def _free_port() -> int:
    """借一个空闲端口 (照 test_sim_stack_offline 同款)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _SandboxAdoptFixture:
    """两个用例类共用的夹具: sim app / 随机端口沙盒 / ASGI 客户端 / 单动作直跑.

    ⚠ 与 test_sim_materials_offline 同款: **不走 POST /api/sim/session**, 因为
    SANDBOX_URL 的端口 48491 是模块常量, 现场只要开着 /3d/sim 就被占住。改用随机
    端口直建栈再挂进 app.state.sim, 测的仍是真实路由。

    刻意**不是 TestCase 子类**: 靠类继承共享夹具会让父类的用例在每个子类里再跑一遍,
    而本文件每条用例都要起一台沙盒 —— 白跑一轮就是三分半钟。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory(prefix="ptlc-sim-adopt-")
        cls._orig_data_dir = bootstrap._DATA_DIR
        bootstrap._DATA_DIR = Path(cls._tmp.name)
        cls._app = bootstrap.create_sim_app(
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/sim/")

    @classmethod
    def tearDownClass(cls):
        bootstrap._DATA_DIR = cls._orig_data_dir
        cls._tmp.cleanup()
        set_pump_defaults_provider(None)
        super().tearDownClass()

    @asynccontextmanager
    async def _sandbox(self):
        """起一台随机端口沙盒并挂进 app.state.sim; 退出时停栈与摘挂."""
        app = self._app
        repo = app.state.script_repo
        stack = await build_sim_stack(
            app.state.app_config,
            registry=app.state.registry,
            resolve_script=lambda name: repo.get("default", name),
            mode_provider=lambda: app.state.control_mode,
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/adopt-test/",
            time_scale=20.0,
        )
        app.state.sim = stack
        try:
            yield stack
        finally:
            app.state.sim = None
            await stack.stop()

    @asynccontextmanager
    async def _client(self):
        """ASGI 传输客户端 (与沙盒同一事件循环); 必须显式跑 lifespan 装配 app.state."""
        async with self._app.router.lifespan_context(self._app):
            transport = ASGITransport(app=self._app)
            async with AsyncClient(transport=transport,
                                   base_url="http://sim.test") as client:
                yield client

    async def _preload_search_window(self, stack) -> None:
        """给 1Z 合法搜索窗 (真机由上位机 preload_targets 写入)."""
        await mock_write(stack.server, "FeedLift_1Z_SearchLowTarget", 400.0)
        await mock_write(stack.server, "FeedLift_1Z_SearchHighTarget", 520.0)

    async def _run(self, client, action: str, params: dict | None = None) -> dict:
        """经 /api/sim/actions/{name}/run 发一个单动作, 返回响应体."""
        resp = await client.post(f"/api/sim/actions/{action}/run",
                                 json={"params": params or {}})
        self.assertEqual(resp.status_code, 200, f"{action} 路由应 200: {resp.text}")
        return resp.json()


class TestAdoptFeedsTheStackModel(_SandboxAdoptFixture, unittest.IsolatedAsyncioTestCase):
    """采纳/人工盘点 -> 板堆模型 -> 传感器 -> L2 前置门 的整条链."""

    async def test_adopt_then_feed_raise_runs(self):
        """主库置 3/9 -> adopt -> 模型跟上 -> 传感器翻位 -> clear/raise DONE -> probe 得 3."""
        async with self._client() as client:
            await client.post("/api/materials/magazine",
                              json={"magazine": "feed", "count": 3})
            await client.post("/api/materials/magazine",
                              json={"magazine": "waste", "count": 9})

            async with self._sandbox() as stack:
                # 建栈时账本还是空的, 模型必然是 0 —— 这是缺陷的起点, 先钉住它
                self.assertEqual(stack.feedlift_model.counts,
                                 {"feed": 0, "waste": 0},
                                 "建栈初值应来自当时还空着的 :memory: 账本")

                adopt = (await client.post("/api/sim/adopt")).json()
                self.assertGreater(adopt["materials"]["rows"], 0, "adopt 应搬来账本行")

                # ① 回灌: 模型跟着账面走
                self.assertEqual(stack.feedlift_model.counts, {"feed": 3, "waste": 9},
                                 "adopt 之后板堆模型必须跟上账面 —— 断了就是 P0 复发")

                # ② 传感器合成随之翻位 (仓底接近开关不再恒 0)
                await asyncio.sleep(0.3)
                ix8 = int(await mock_read(stack.server, "IX8"))
                self.assertTrue(ix8 >> _IX8_PROX_BIT["feed"] & 1,
                                "有板时仓底接近开关必须为 1")
                self.assertTrue(preflight_gate("feed", ix8)["ok"],
                                "有板时可见前置自检应通过")

                # ③ 前置门放行, 动作真跑起来 (用户截图那条报错的正面判据)
                await self._preload_search_window(stack)
                for action in ("feedlift.feed_clear", "feedlift.feed_raise"):
                    body = await self._run(client, action)
                    self.assertEqual(body["status"], "DONE",
                                     f"{action} 应 DONE, 实际 {body}")
                    self.assertFalse(body.get("error_code"),
                                     f"{action} 不该带错误码: {body}")
                step = int(await mock_read(stack.server, "FeedLift_L2_Step"))
                self.assertNotIn(step, (14, 44), f"段号 {step} 是失败收敛段")

                # ④ 光电盘点量回同一个数
                probe = await self._run(client, "feedlift.probe_stack",
                                        {"magazine": "feed", "reconcile": True})
                self.assertEqual(probe["status"], "DONE", f"probe 应 DONE: {probe}")
                self.assertEqual(int(probe["result"]["count"]), 3,
                                 f"光电行程应量回 3 张: {probe['result']}")

    async def test_manual_magazine_write_also_reaches_the_model(self):
        """第二条入口: POST /api/sim/materials/magazine 同样回灌 (不是只修了 adopt)."""
        async with self._client() as client:
            async with self._sandbox() as stack:
                resp = await client.post("/api/sim/materials/magazine",
                                         json={"magazine": "feed", "count": 7})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(stack.feedlift_model.counts["feed"], 7,
                                 "人工盘点也必须回灌板堆模型")

                await self._preload_search_window(stack)
                for action in ("feedlift.feed_clear", "feedlift.feed_raise"):
                    body = await self._run(client, action)
                    self.assertEqual(body["status"], "DONE", f"{action} 应 DONE: {body}")

                probe = await self._run(client, "feedlift.probe_stack",
                                        {"magazine": "feed", "reconcile": True})
                self.assertEqual(int(probe["result"]["count"]), 7)

    async def test_without_the_observer_the_gate_times_out(self):
        """负面判据: 摘掉观察者后同一序列必报 301.

        只断言"现在能跑"的测试, 在有人删掉回灌却顺手在别处补了初值时仍会绿。
        显式摘掉观察者再验证它**必然失败**, 才真正锁住"这条链是靠回灌成立的"。
        """
        async with self._client() as client:
            async with self._sandbox() as stack:
                stack.material_store.set_magazine_observer(None)
                resp = await client.post("/api/sim/materials/magazine",
                                         json={"magazine": "feed", "count": 30})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(stack.feedlift_model.counts["feed"], 0,
                                 "摘掉观察者后模型就该停在 0 —— 否则还有第二条回灌路")

                await self._preload_search_window(stack)
                body = await self._run(client, "feedlift.feed_raise")
                self.assertEqual(body["status"], "ERROR")
                self.assertEqual(int(body["error_code"]), 301,
                                 f"无回灌时应报前置门超时 301: {body}")

                # 沙盒语境的释义: 指向状态面, 不是真机标定话术
                message = str(body.get("message") or "")
                self.assertIn("/api/sim/materials/magazine", message,
                              f"沙盒里的 301 应指向板仓设置入口, 实际: {message}")
                self.assertNotIn("标定不要采空仓那一组", message,
                                 f"沙盒里不该出现真机标定话术: {message}")


class TestAdoptCarriesEndEffectors(_SandboxAdoptFixture, unittest.IsolatedAsyncioTestCase):
    """采纳末端执行器 (吸盘/夹爪/翻转).

    此前 `patch["robot"]` 只有 joint/pose/tool 三个键, 末端整条没接。后果不止面板上
    那几个按钮显示"未命令" —— 沙盒板堆的"板是否离堆"判据 `_suction_on()`
    (sim_stack.py) 读的正是这份机构缓存, 且它的注释自称"与 adopt 采纳机构态同一准则",
    而 adopt 根本没采纳它。于是真机吸着一块板时采纳, 沙盒认为手上是空的, 取放板的
    因果从错的初态起算。
    """

    @asynccontextmanager
    async def _robot_busy(self, robot):
        """把真机侧机器人置成"动作锁被别的线程占着".

        直接占 `_action_lock` 而不是发一条长运动: 主栈的 SimRobotTransport 是
        interpolate=False 的瞬移实现, 发什么动作都不会真的占住锁。而 is_busy() 的
        判据就是对这把锁做非阻塞探测, 所以按它的判据造现场最直接。
        """
        held = threading.Event()
        release = threading.Event()

        def _hold() -> None:
            with robot._action_lock:          # 测试要造的就是"这把锁被别人占着"
                held.set()
                release.wait(10)

        worker = threading.Thread(target=_hold, daemon=True, name="test-hold-robot-lock")
        worker.start()
        self.assertTrue(held.wait(5), "占锁线程没起来")
        try:
            yield
        finally:
            release.set()
            worker.join(timeout=5)

    @staticmethod
    def _arm_suction(robot) -> None:
        """真机侧挂 1 号刀并开吸盘 (末端态的来源)."""
        robot.set_mounted_tool(int(MountedTool.SLOT1))
        robot.tool_action(ToolAction.SUCTION_ON)

    async def test_suction_state_reaches_the_sandbox(self):
        """真机吸盘吸着 -> adopt -> 沙盒的 rob_suction 跟着为真, 且仍标"推定"."""
        async with self._client() as client:
            robot = self._app.state.executor.robot
            self._arm_suction(robot)

            async with self._sandbox() as stack:
                sim_robot = stack.executor.robot
                self.assertNotIn("rob_suction", sim_robot.mechanism_snapshot(),
                                 "新建栈的沙盒机器人不该有被命令过的吸盘")

                result = (await client.post("/api/sim/adopt")).json()
                self.assertIn("robot.effectors.rob_suction", result["applied"],
                              f"吸盘态没随采纳搬进沙盒: {result}")

                entry = sim_robot.mechanism_snapshot().get("rob_suction") or {}
                self.assertTrue(entry.get("commanded"), f"吸盘应为吸住: {entry}")
                # 真机吸盘没有任何 DI (_TOOL_DI_TARGET 无 SUCTION 条目), 搬过来也不许
                # 变成"已确认" —— 把推定画成确认是本仓的老坑
                self.assertIsNone(entry.get("confirmed"),
                                  f"吸盘不该有到位反馈: {entry}")
                self.assertEqual(entry.get("source"), "commanded",
                                 f"来源应仍是命令态, 前端据此标'推定': {entry}")

    async def test_cad_baseline_is_not_adopted(self):
        """红线: mechanism_snapshot 为三维补的 CAD 推定基准态**不许**被采纳.

        翻转气缸从没被命令过时, mechanism_snapshot 会补一条 _TWIN_BASELINE_STATE ——
        那是为"一挂刀就建好插值通道"服务的渲染用推定。把它一并采纳, 就等于把一条推定
        写进**另一台机器**的"命令过什么"账本, 正是 _TWIN_BASELINE_STATE 注释里第二条
        红线禁止的事。adopt 因此走 commanded_mechanism_states 而不是 mechanism_snapshot。
        """
        async with self._client() as client:
            robot = self._app.state.executor.robot
            self._arm_suction(robot)                 # 只命令吸盘, 刻意不碰翻转
            self.assertIn("rob_flip_suction", robot.mechanism_snapshot(),
                          "前提: 显示面确实补了翻转的基准态, 否则本用例失去意义")
            self.assertNotIn("rob_flip_suction", robot.commanded_mechanism_states(),
                             "采纳面不该出现从没被命令过的机构")

            async with self._sandbox():
                result = (await client.post("/api/sim/adopt")).json()
                self.assertNotIn("robot.effectors.rob_flip_suction", result["applied"],
                                 f"CAD 推定基准态不该被采纳: {result}")

    async def test_effectors_adopted_even_while_robot_is_busy(self):
        """机器人忙: 位姿记 skipped, 挂刀与末端照采.

        分路判据是"读它要不要打 TCP" —— mounted_tool 是落盘的软件权威态, 机构态是
        内存缓存, 两者都不碰动作锁。吸盘吸着一块板、臂还在走的时候采纳, 沙盒必须
        知道手上有板。
        """
        async with self._client() as client:
            robot = self._app.state.executor.robot
            self._arm_suction(robot)

            async with self._sandbox() as stack:
                async with self._robot_busy(robot):
                    result = (await client.post("/api/sim/adopt")).json()

                parts = {str(item.get("part")) for item in result.get("skipped") or []}
                self.assertIn("robot.pose", parts, f"忙时位姿应记 skipped: {result}")
                self.assertIn("robot.effectors.rob_suction", result["applied"],
                              f"忙时末端仍应采到: {result}")
                self.assertIn("robot", result["applied"],
                              f"挂刀是纯内存读, 忙时也应采到: {result}")
                entry = stack.executor.robot.mechanism_snapshot().get("rob_suction") or {}
                self.assertTrue(entry.get("commanded"), f"忙时吸盘态仍应落地: {entry}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
