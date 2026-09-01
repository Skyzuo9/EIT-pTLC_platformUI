"""沙盒合成值 host 方法的离线测试
================================
功能:
    钉住"给不出真值的 host 方法改成**自述合成**"这条契约, 以及它换来的东西 ——
    `robot_suction_put` 在沙盒里能跑到 DONE。

    改之前 `vision.capture_plate_offset` 直接抛异常拒绝 (注释理由: "零偏桩会骗人"),
    而 `robot_suction_put` 无条件调它四次, 那个脚本被 7 条操作引用
    (sampling_load / sampling_place_plate / photoscrape_load / photoscrape_place /
    photoscrape_plate_load / feedlift_unload_cycle / ptlc_full_v2) ——
    于是沙盒里**任何放板都必定中途硬失败**, 一条完整流程都跑不完。

    改之后的三条约束由本文件钉住:
      ① 结果体与真机侧 neutral_offset() **同形**(不许在沙盒里另写一份键集);
      ② 结果体自带 synthetic 标记, 且经 GET /api/sim/diagnostics 可数可看;
      ③ 故障注入能把被合成抹掉的 err=111 分支演练回来。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest \
        eit_ptlc/tests/test_sim_synthetic_hosts_offline.py -q
"""

from __future__ import annotations

import asyncio
import socket
import tempfile
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from httpx import ASGITransport, AsyncClient

import eit_ptlc.runtime.bootstrap as bootstrap
from eit_ptlc.controller.pallas_vision_client import neutral_offset
from eit_ptlc.runtime.sim_stack import build_sim_stack
from eit_ptlc.tools.pump.profiles import set_pump_defaults_provider

_VISION_HOST = "vision.capture_plate_offset"
_TERMINAL = {"DONE", "ERROR", "KILLED"}


def _free_port() -> int:
    """借一个空闲端口 (照 test_sim_stack_offline 同款)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestSyntheticVisionOffset(unittest.IsolatedAsyncioTestCase):
    """合成纠偏结果的形状 / 留痕 / 故障注入 / 放板脚本能跑通.

    ⚠ 与其它沙盒用例同款: **不走 POST /api/sim/session** (SANDBOX_URL 端口 48491 是
    模块常量, 现场开着 /3d/sim 就抢不到), 改用随机端口直建栈再挂进 app.state.sim。
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="ptlc-sim-synthetic-")
        cls._orig_data_dir = bootstrap._DATA_DIR
        bootstrap._DATA_DIR = Path(cls._tmp.name)
        cls._app = bootstrap.create_sim_app(
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/sim/")

    @classmethod
    def tearDownClass(cls):
        bootstrap._DATA_DIR = cls._orig_data_dir
        cls._tmp.cleanup()
        set_pump_defaults_provider(None)

    @asynccontextmanager
    async def _sandbox(self):
        app = self._app
        repo = app.state.script_repo
        stack = await build_sim_stack(
            app.state.app_config,
            registry=app.state.registry,
            resolve_script=lambda name: repo.get("default", name),
            mode_provider=lambda: app.state.control_mode,
            opcua_url=f"opc.tcp://127.0.0.1:{_free_port()}/eit_ptlc/synthetic-test/",
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
        async with self._app.router.lifespan_context(self._app):
            transport = ASGITransport(app=self._app)
            async with AsyncClient(transport=transport,
                                   base_url="http://sim.test") as client:
                yield client

    async def _capture(self, client, apply_rz: bool = True) -> dict:
        """经真实动作路由发一次纠偏, 返回 result 段."""
        resp = await client.post(f"/api/sim/actions/{_VISION_HOST}/run",
                                 json={"params": {"apply_rz": apply_rz}})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "DONE",
                         f"合成纠偏应 DONE 而不是被拒: {body}")
        return body["result"]

    async def _run_script(self, client, name: str, inputs: dict | None = None,
                          timeout_s: float = 180.0) -> dict:
        """跑一条脚本到终态, 返回最后一帧调试状态."""
        resp = await client.post(f"/api/sim/scripts/{name}/debug/run",
                                 json={"inputs": inputs or {}, "mode_run": "run"})
        self.assertEqual(resp.status_code, 200, resp.text)
        run_id = resp.json()["run_id"]
        deadline = time.monotonic() + timeout_s
        state: dict = {}
        while time.monotonic() < deadline:
            state = (await client.get(f"/api/sim/debug/{run_id}/state")).json()
            if str(state.get("status") or "") in _TERMINAL:
                return state
            await asyncio.sleep(0.2)
        self.fail(f"脚本 {name} 在 {timeout_s}s 内未收敛, 末状态: {state}")

    async def test_offset_is_neutral_and_self_declared(self):
        """合成纠偏: 与真机 neutral_offset 同形, 且自报 synthetic."""
        async with self._client() as client:
            async with self._sandbox():
                result = await self._capture(client)

                # ① 同形: 真机侧那份的每一个键都在 (不许沙盒另写一份键集)
                for key in neutral_offset("x"):
                    self.assertIn(key, result, f"缺真机侧的键 {key}: {result}")
                self.assertEqual(result["dx_mm"], 0.0)
                self.assertEqual(result["dy_mm"], 0.0)
                self.assertEqual(result["drz_deg"], 0.0)
                self.assertEqual(int(result["err"]), 0)
                self.assertTrue(result["valid"])

                # ② 自报: 界面与调用方都能看出这是编的
                self.assertIs(result.get("synthetic"), True,
                              f"合成值必须自报: {result}")
                self.assertTrue(str(result.get("synthetic_reason") or "").strip(),
                                f"自报必须带中文理由: {result}")
                self.assertEqual(result["source"], "sim_synthetic",
                                 f"来源应写明是沙盒合成: {result}")

    async def test_diagnostics_counts_the_synthetic_uses(self):
        """留痕: 每次合成都登记, 诊断面板可数可看.

        没有这一条, 合成就退回成一个更隐蔽的零偏桩 —— 与直接拒绝相比只是把
        "跑不通"换成了"跑通了但不知道有几处是编的"。
        """
        async with self._client() as client:
            async with self._sandbox():
                before = (await client.get("/api/sim/diagnostics")).json()["synthetic"]
                self.assertEqual(before["total"], 0, "新建栈不该有合成记录")

                await self._capture(client)
                await self._capture(client)

                after = (await client.get("/api/sim/diagnostics")).json()["synthetic"]
                self.assertEqual(after["total"], 2, f"两次调用应记两笔: {after}")
                hosts = {item["host"]: item for item in after["items"]}
                self.assertIn(_VISION_HOST, hosts, f"台账里应有该 host: {after}")
                self.assertEqual(hosts[_VISION_HOST]["count"], 2)
                self.assertTrue(hosts[_VISION_HOST]["reason"].strip())

    async def test_fault_injection_restores_the_failure_branch(self):
        """故障注入: 把合成抹掉的 err=111 识别失败分支演练回来.

        合成零偏让 robot_suction_put 里那两段"确认=重拍一次"的人工处置永不可达。
        注入钩子是把它还回来的手段 (形制照 cylinders 的 _eit_cylinder_stuck:
        server 属性, 缺省不生效, 不开 API)。
        """
        async with self._client() as client:
            async with self._sandbox() as stack:
                stack.server._eit_vision_reject = (_VISION_HOST,)
                result = await self._capture(client)
                fail_code = int(self._app.state.app_config.pallas_vision.err_fail_code)
                self.assertEqual(int(result["err"]), fail_code,
                                 f"注入后应报识别失败码 {fail_code}: {result}")
                self.assertFalse(result["valid"])
                self.assertIs(result.get("synthetic"), True,
                              "注入出来的失败同样是编的, 同样要自报")

                stack.server._eit_vision_reject = ()
                self.assertEqual(int((await self._capture(client))["err"]), 0,
                                 "撤掉注入后应恢复零偏")

    async def test_suction_put_script_reaches_done(self):
        """★ 本轮解锁的可执行判据: 放板脚本在沙盒里能跑到 DONE.

        改之前这条脚本必定在第一次 capture_plate_offset 处硬失败, 连带 7 条操作
        (含 ptlc_full_v2) 在沙盒里全跑不完。
        """
        async with self._client() as client:
            async with self._sandbox():
                state = await self._run_script(
                    client, "robot_suction_put", {"station_id": "spotting"})
                self.assertEqual(state.get("status"), "DONE",
                                 f"放板脚本应跑到 DONE: {state}")

                report = (await client.get("/api/sim/diagnostics")).json()
                self.assertGreaterEqual(report["synthetic"]["total"], 2,
                                        f"该脚本调两次纠偏, 台账应有两笔以上: "
                                        f"{report['synthetic']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
