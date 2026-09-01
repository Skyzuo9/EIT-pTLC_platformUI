#!/usr/bin/env python3
"""仿真沙盒栈 (runtime/sim_stack) 离线测试
==========================================
覆盖 (仿真模块阶段②的验收面):
    1. 建栈/收栈: 随机端口起第二台 Mock OPC UA + 全套执行链, stop() 干净收口;
    2. 状态面: apply_state 写轴/机器人 → state_snapshot 读回一致;
    3. 事件面: 状态写入经 flat→struct 链 + 20Hz realtime_feedback 变成 axis_pose 事件;
    4. 真实协议: PlcController.execute 走完整 L2 握手, DONE 后瞬移镜像
       (*_ActPos := *_Target) 生效 —— 目标值是上位机真实下推的, 瞬移落在真实位置;
    5. 泵归真链: executor.execute(sampling.flush) 经 PUMP_PROFILES → translator
       生成真实 DT 指令串写进沙盒 PLC 节点 (与金测试同一产地);
    6. VM 面: 沙盒 VmController 跑最小脚本, operation_done 事件到沙盒 bus;
    7. 隔离: RunStore/MaterialStore 均为 :memory:, executor 无 manual_guard/维护门。

运行:
    python -m pytest eit_ptlc/tests/test_sim_stack_offline.py -q
"""

from __future__ import annotations

import asyncio
import socket
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.mock.plc_server import mock_read, mock_write  # noqa: E402
from eit_ptlc.runtime.sim_stack import build_sim_stack  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_SMOKE_DOC = {
    "schema": "ptlc.script/v1",
    "kind": "operation",
    "name": "sim_smoke",
    "label": "沙盒冒烟",
    "vars": [],
    "body": [{"op": "comment", "text": "沙盒 VM 布线冒烟"}],
}


async def _wait_event(queue, want_type: str, predicate=None, timeout: float = 5.0) -> dict:
    """从订阅队列里等一条指定类型 (且过谓词) 的事件。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remain = deadline - loop.time()
        if remain <= 0:
            raise AssertionError(f"等不到事件 {want_type}")
        event = await asyncio.wait_for(queue.get(), timeout=remain)
        if event.get("type") == want_type and (predicate is None or predicate(event)):
            return event


class SimStackOfflineTests(unittest.TestCase):
    """整栈一次性起停 (Mock Server 启动有秒级成本, 用例串在一个事件循环里)。"""

    def test_sandbox_end_to_end(self) -> None:
        asyncio.run(self._exercise())

    async def _exercise(self) -> None:
        config = load_config(_PKG / "config" / "app.yaml")
        registry = ActionRegistry.load(_PKG / "config" / "actions")
        port = _free_port()
        stack = await build_sim_stack(
            config, registry=registry,
            resolve_script=lambda n: (_ for _ in ()).throw(KeyError(n)),
            mode_provider=lambda: "DEBUG",
            opcua_url=f"opc.tcp://127.0.0.1:{port}/eit_ptlc/sandbox-test/",
            time_scale=8.0,      # 行为层快进: 轴按 vel_max 连续运动, 全速会拖慢测试
        )
        try:
            # ---- 7. 隔离不变量 (先断言, 建栈即错就别跑后面) ----
            self.assertEqual(stack.run_store._path, ":memory:")
            self.assertEqual(stack.material_store._path, ":memory:")
            self.assertIsNone(stack.executor._manual_guard)
            self.assertIn(str(port), stack.opcua_url)
            self.assertEqual(stack.time_scale, 8.0)     # 倍率经 SimClock 生效

            # ---- 2. 状态写读 ----
            result = await stack.apply_state({
                "axes": {"axis_4x": 55.5, "axis_11y": 300.0},
                "robot": {"joint": [1, 2, 3, 4, 5, 6], "tool": 1},
                "mechanisms": {},
            })
            self.assertFalse(result["rejected"], result)
            snap = await stack.state_snapshot()
            self.assertAlmostEqual(snap["axes"]["axis_4x"]["mm"], 55.5, places=3)
            self.assertAlmostEqual(snap["axes"]["axis_11y"]["mm"], 300.0, places=3)
            self.assertEqual(snap["robot"]["joint"][0], 1.0)
            self.assertEqual(snap["robot"]["tool"], 1)
            unknown = await stack.apply_state({"axes": {"axis_nope": 1.0}})
            self.assertEqual(len(unknown["rejected"]), 1)

            async with stack.bus.subscribe() as queue:
                # ---- 3. axis_pose 事件链 (flat→struct→20Hz 采样) ----
                await stack.apply_state({"axes": {"axis_7y": 42.0}})
                await _wait_event(
                    queue, "axis_pose",
                    lambda e: abs(float((e.get("positions") or {}).get("axis_7y", 0)) - 42.0) < 0.01)

                # ---- 4. 真实 L2 协议 + 瞬移镜像 ----
                await mock_write(stack.server, "Sampling_4X_Target", 123.4)
                l2 = await stack.plc.execute("Sampling", 10, {})
                self.assertEqual(int(l2.state), 20, l2)     # DONE
                self.assertAlmostEqual(
                    float(await mock_read(stack.server, "Sampling_4X_ActPos")), 123.4, places=3)
                await _wait_event(
                    queue, "axis_pose",
                    lambda e: abs(float((e.get("positions") or {}).get("axis_4x", 0)) - 123.4) < 0.01)

                # ---- 5. 泵归真链: 执行器→profiles→translator→DT 串落沙盒节点,
                #         虚拟泵按动作码消费并广播 pump_state; 单动作路径发合成事件 ----
                small = {"flush_volume_ml": 2.0, "outer_wash_volume_ml": 1.0,
                         "spot_head_volume_ml": 0.5, "asp_speed": 250,
                         "flush_disp_speed": 300, "spot_head_disp_speed": 100,
                         "step_delay": 1500}
                first = await stack.run_action_with_events(
                    "sampling.flush", dict(small), mode="DEBUG")
                self.assertEqual(first["status"], "DONE", first)
                instructions = await mock_read(stack.server, "Sampling_clean_instructions")
                self.assertTrue(instructions and str(instructions[0]).startswith("/4V"),
                                f"DT 指令未落节点: {instructions!r}")
                # 合成事件次序 (镜像 app.py 单发路径): step_start(带 params) →
                # 执行期 pump_state → step_done(DONE) → operation_done
                start_ev = await _wait_event(
                    queue, "step_start", lambda e: e.get("action") == "sampling.flush")
                self.assertAlmostEqual(
                    float(start_ev["params"]["flush_volume_ml"]), 2.0, places=3)
                await _wait_event(queue, "pump_state", lambda e: e.get("id") == "SMP")
                await _wait_event(queue, "step_done",
                                  lambda e: e.get("action") == "sampling.flush"
                                  and e.get("status") == "DONE")
                await _wait_event(queue, "operation_done",
                                  lambda e: e.get("operation") == "sampling.flush")
                # 同参数重跑: 指令串逐字节相同, 泵仍须动 —— 旧"节点值变更"触发在此漏触发
                second = await stack.run_action_with_events(
                    "sampling.flush", dict(small), mode="DEBUG")
                self.assertEqual(second["status"], "DONE", second)
                await _wait_event(queue, "pump_state",
                                  lambda e: e.get("id") == "SMP" and e.get("busy") is True)
                await _wait_event(queue, "operation_done",
                                  lambda e: e.get("operation") == "sampling.flush")
                # 泵状态进栈级快照 (柱塞终态回 0, translator 不变量)
                snap_after = await stack.state_snapshot()
                self.assertAlmostEqual(
                    snap_after["pumps"]["SMP"]["plunger_ml"], 0.0, places=2)

                # ---- 5b. 机械臂插值: 运动期连续 robot_pose 帧且关节逐帧变化 ----
                base = stack.robot_transport.query()
                target_joint = [j + d for j, d in
                                zip(base.joint, (12.0, -8.0, 10.0, 6.0, -5.0, 9.0))]
                mover = asyncio.create_task(asyncio.to_thread(
                    stack.robot_transport.move_j, list(base.pose), joint=target_joint))
                frames = []
                while True:
                    event = await _wait_event(queue, "robot_pose", timeout=10.0)
                    frames.append(list(event["joint"]))
                    if max(abs(a - b) for a, b in zip(event["joint"], target_joint)) < 1e-6:
                        break
                await mover
                self.assertGreaterEqual(len(frames), 3, "插值应产生连续帧而不是单帧瞬移")
                self.assertNotEqual(frames[0], frames[-1], "关节应逐帧变化")
                # 无关节角的派生点 (move_l joint=None): IK 可用时应解出新关节
                if stack.robot_transport._ik_solver is not None:
                    before_joint = list(stack.robot_transport.query().joint)
                    lifted = list(stack.robot_transport.query().pose)
                    lifted[2] += 30.0
                    await asyncio.to_thread(stack.robot_transport.move_l, lifted)
                    after_joint = list(stack.robot_transport.query().joint)
                    self.assertNotEqual(before_joint, after_joint,
                                        "IK 应为无关节角目标解出新关节 (机械臂不再钉死)")

                # ---- 6. VM 布线冒烟 ----
                started = await stack.vm.start(_SMOKE_DOC, {}, mode_run="run")
                await stack.vm.wait_final(started["run_id"], timeout=10.0)
                await _wait_event(queue, "operation_done",
                                  lambda e: e.get("run_id") == started["run_id"], timeout=5.0)
        finally:
            await stack.stop()


if __name__ == "__main__":
    unittest.main()
