#!/usr/bin/env python3
"""地轨 rail.ensure 流程级接管 sim 预演 (地轨第 7 维 Win B · B2)
================================================================
功能:
    在仿真机械臂 + 有状态地轨 PLC 上, 以 auto_rail=True 端到端执行一条真实转运流程, 验证
    "删除编排层 rail_move_safe 字面量后, 原子 enter 注入的 rail.ensure 能接管移轨、地轨仍落到
    正确工位槽、全程无 UNSAFE/ERROR"。这是 B2 逐工位删字面量前的 sim 预演载体 (物理仍需真机 dry-run):
      - 字面量还在时: literal 移轨, ensure 幂等跳过 -> 本测试绿 (基线, 证测试本身对)。
      - 字面量删除后: 无 literal, ensure 独力把地轨移到位 -> 本测试仍绿 (证接管)。
    两态测试代码不变, 仅磁盘 YAML 变 (repo 从 config/operation 播种)。

判据: 有状态 PLC 桩的 rail.move 更新实际 mm (模拟 sim FSM 到位), read_rail_pose 回读; 地轨起于
    错位, 跑完落在流程最后一段的目标槽即证接管。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.executor import ActionExecutor  # noqa: E402
from eit_ptlc.action.models import ActionStatus  # noqa: E402
from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402
from eit_ptlc.controller.robot_controller import RobotController  # noqa: E402
from eit_ptlc.driver.robot_sim import SimRobotTransport  # noqa: E402
from eit_ptlc.operation.resources import ResourceGate  # noqa: E402
from eit_ptlc.operation.vm.repo import ScriptRepo  # noqa: E402
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402
from eit_ptlc.operation.vm.state import VmStatus  # noqa: E402
from eit_ptlc.operation.vm.thread import VmThread  # noqa: E402

_RAIL_MM = {1: 168.0, 2: 168.0, 3: 350.0, 4: 500.0, 5: 600.0, 6: 600.0}


class _StatefulRailPlc:
    """有状态地轨 PLC 桩: rail.move 更新实际 mm (模拟 sim FSM 到位), read_rail_pose 回读。"""

    def __init__(self, start_slot: int, homed: bool = True) -> None:
        self.mm = _RAIL_MM[start_slot]
        self.homed = homed
        self.moves: list[int] = []

    async def read_rail_pose(self):
        return (self.mm, self.homed)

    async def execute(self, station, code, channels, *, timeout=None, stall_timeout=None):
        # 只对地轨动作建模位置; 流程里途经的其它 L2 动作 (如 staging_a.locator_* 中转定位气缸)
        # 一律直接 ack —— 本桩只关心"地轨落在哪个槽", 不该因无关工位缺通道而 KeyError。
        if "Rail_Target_Position" in channels:
            tgt = int(channels["Rail_Target_Position"])
            self.mm = _RAIL_MM[tgt]                   # 模拟到位
            self.moves.append(tgt)
        return SimpleNamespace(request_seq=1, action_code=code, step=0,
                               safe_state=SimpleNamespace(name="IDLE"))


class _RailPoints:
    def sync_group(self, station):
        return None

    def rail_slot_mm(self, slot):
        return _RAIL_MM.get(int(slot))


class _RecordingExecutor:
    def __init__(self, inner: ActionExecutor) -> None:
        self.inner = inner
        self.calls: list[tuple[str, dict, ActionStatus]] = []

    async def execute(self, name, params=None, **kwargs):
        result = await self.inner.execute(name, params, **kwargs)
        self.calls.append((name, dict(params or {}), result.status))
        return result


class RailEnsureFlowTakeoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_PKG / "config" / "app.yaml")
        cls.cfg_dir = cfg.plc.nodes_file.parent
        cls.registry = ActionRegistry.load(cls.cfg_dir / "actions")
        valid = {a.name for a in cls.registry.list()}
        cls.points = PointRegistry.load(cfg.robot.points_file,
                                        source_version=cfg.robot.point_source_version,
                                        meta_path=cfg.robot.points_meta_file)
        cls.home_point = cfg.robot.home_point
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = ScriptRepo(Path(cls._tmp.name) / "scripts",
                              validator=lambda d: validate_script(d, valid_actions=valid))
        for path in sorted((cls.cfg_dir / "operation").glob("**/*.yaml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if doc.get("name"):
                cls.repo.create("default", doc["name"], doc)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _run_flow(self, script: str, inputs: dict, start_slot: int, mounted_tool: int = 2):
        home = self.points.get(self.home_point)
        transport = SimRobotTransport(pose=home.pose, joint=home.joint)
        transport.connect()
        transport.set_mounted_tool(mounted_tool)      # 预置工具, 免入口换刀触发
        robot = RobotController(transport, self.points, home_point=self.home_point,
                                jog_speed_percent=20, step_distance_mm=1.0, step_angle_deg=1.0)
        plc = _StatefulRailPlc(start_slot)
        rec = _RecordingExecutor(ActionExecutor(self.registry, robot=robot, plc=plc,
                                                points=_RailPoints(), auto_rail=True))
        thread = VmThread(self.repo.get("default", script), executor=rec, res_gate=ResourceGate(),
                          resolve_script=lambda n: self.repo.get("default", n),
                          emit=lambda e: None, mode_provider=lambda: "RUN")
        status = asyncio.run(thread.run(inputs))
        return status, rec, plc

    def test_bottle_staging_b_to_rack_rail_ends_at_slot6(self) -> None:
        """跨槽转运 (中转B位3取 → 货架位6放): 地轨起于错位, 跑完须落位6, 途经位3; 地轨调用全 DONE。"""
        status, rec, plc = self._run_flow("transfer_bottle_staging_b_to_rack",
                                          {"slot_id": 1}, start_slot=1)
        rail_calls = [(n, s) for n, _, s in rec.calls if n in ("rail.move", "rail.ensure")]
        self.assertEqual(status, VmStatus.DONE,
                         f"流程未 DONE; 地轨调用={rail_calls}")
        self.assertTrue(all(s is ActionStatus.DONE for _, s in rail_calls),
                        f"地轨调用有非 DONE (UNSAFE/ERROR): {rail_calls}")
        self.assertEqual(plc.mm, _RAIL_MM[6], f"地轨终位应为货架位6, 实为 {plc.mm}; moves={plc.moves}")
        self.assertIn(3, plc.moves, f"应途经中转B位3; moves={plc.moves}")
        self.assertIn(6, plc.moves, f"应到货架位6; moves={plc.moves}")

    def test_tank_atomics_move_rail_at_entry_seam_not_mid_sequence(self) -> None:
        """tank 取放: 地轨起于位1, 须在臂离开 P1 之前移到展开位5, 全程一次移轨。

        回归载体 —— 修复前这两个原子入口没有任何移轨步骤, 中途点 P75/P84/P59 为 rail=None 放行,
        直到 tank.N.approach_far (rail=5) 才由 auto_rail 触发移轨, 此时臂已伸出持板,
        撞 rail.move 的 P1 硬门 (真空守卫) 而 UNSAFE 拒发, 板件卡在缸口上方。
        """
        for script in ("robot_tank_put", "robot_tank_pick"):
            with self.subTest(script=script):
                # mounted_tool=1 (吸盘) 与两原子 needed=1 一致, 免入口换刀把地轨拉到工具位4
                status, rec, plc = self._run_flow(script, {"tank_id": 1}, start_slot=1, mounted_tool=1)
                rail_calls = [(n, s) for n, _, s in rec.calls if n in ("rail.move", "rail.ensure")]
                self.assertEqual(status, VmStatus.DONE, f"{script} 未 DONE; 地轨调用={rail_calls}")
                self.assertTrue(all(s is ActionStatus.DONE for _, s in rail_calls),
                                f"{script} 地轨调用有非 DONE (UNSAFE/ERROR): {rail_calls}")
                self.assertEqual(plc.moves, [5],
                                 f"{script} 应恰好移轨一次到展开位5; moves={plc.moves}")
                self.assertEqual(plc.mm, _RAIL_MM[5],
                                 f"{script} 地轨终位应为展开位5, 实为 {plc.mm}")
                # 接缝性质: 移轨必须发生在任何一次走臂之前 (臂仍缩在 P1 时)
                names = [n for n, _, _ in rec.calls]
                self.assertIn("rail.ensure", names, f"{script} 入口缺 rail.ensure")
                self.assertLess(names.index("rail.ensure"), names.index("robot.move_to_point"),
                                f"{script} 移轨发生在走臂之后 (中途移轨); 调用序={names}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
