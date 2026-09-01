#!/usr/bin/env python3
"""机器人点位 operation 离线端到端测试
=====================================
功能:
    校验"完全原子化分解"的正确性: 生成的机器人点位 operation (robot_*) 经 mini-VM + 仿真机械臂
    执行后, 其逐点序列与可信解析器 RobotPlanCatalog.resolve 完全一致; 进/出 require_anchor 通过;
    工具动作在 RUN 模式下可执行 (tool_action 已放开门控); 无效 selector 触发 raise 失败。
    仅机器人原子动作 (不接 PLC), 用 ScriptRepo 临时工作区从 config/operation 播种。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
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
from eit_ptlc.operation.robot_routes.robot_flow import MoveStep  # noqa: E402
from eit_ptlc.operation.robot_routes.robot_plan import RobotPlanCatalog  # noqa: E402
from eit_ptlc.operation.vm.repo import ScriptRepo  # noqa: E402
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402
from eit_ptlc.operation.vm.state import VmStatus  # noqa: E402
from eit_ptlc.operation.vm.thread import VmThread  # noqa: E402


class _RecordingExecutor:
    """包裹 ActionExecutor, 记录 (动作名, 入参, 终态) 供断言执行轨迹."""

    def __init__(self, inner: ActionExecutor) -> None:
        self.inner = inner
        self.calls: list[tuple[str, dict, ActionStatus]] = []

    async def execute(self, name, params=None, **kwargs):
        result = await self.inner.execute(name, params, **kwargs)
        self.calls.append((name, dict(params or {}), result.status))
        return result


def _walk_nodes(nodes):
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node
        for key in ("then", "else", "body", "finally"):
            yield from _walk_nodes(node.get(key))
        for branch in node.get("branches") or []:
            yield from _walk_nodes(branch)
        for handler in node.get("catch") or []:
            yield from _walk_nodes(handler.get("body"))
        for elif_branch in node.get("elifs") or []:
            yield from _walk_nodes(elif_branch.get("body"))


def _tool_action_name(node: dict) -> str | None:
    if node.get("op") != "call" or node.get("action") != "robot.tool_action":
        return None
    return (node.get("args") or {}).get("action", {}).get("lit")


_RAIL_MM = {1: 168.0, 2: 168.0, 3: 350.0, 4: 500.0, 5: 600.0, 6: 600.0}


class _RailPlc:
    """PLC 桩: 换刀路径 rail_move_safe(4) 的 rail.move 派发 + read_rail_pose。"""

    def __init__(self, actual_mm=500.0, homed=True):
        self._actual = actual_mm
        self._homed = homed
        self.rail_moves: list[tuple] = []

    async def read_rail_pose(self):
        return (self._actual, self._homed)

    async def execute(self, station, code, channels, *, timeout=None, stall_timeout=None):
        self.rail_moves.append((station, code, dict(channels)))
        return SimpleNamespace(request_seq=1, action_code=code, step=0,
                               safe_state=SimpleNamespace(name="IDLE"))


class _RailPoints:
    """点位服务桩: sync_group=None (跳过单写者回读), rail_slot_mm 查槽→mm。"""

    def sync_group(self, station):
        return None

    def rail_slot_mm(self, slot):
        return _RAIL_MM.get(int(slot))


class RobotPointOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_PKG / "config" / "app.yaml")
        cls.cfg_dir = cfg.plc.nodes_file.parent
        cls.registry = ActionRegistry.load(cls.cfg_dir / "actions")
        valid = {a.name for a in cls.registry.list()}
        pts = PointRegistry.load(cfg.robot.points_file,
                                 source_version=cfg.robot.point_source_version,
                                 meta_path=cfg.robot.points_meta_file)
        cls.catalog = RobotPlanCatalog.load(cls.cfg_dir / "backup" / "robot_flows_v2.yaml", pts)
        cls.points = cls.catalog.registry
        cls.home_point = cfg.robot.home_point
        # 临时工作区: 从 config/operation 全量播种 (递归), 校验器引用动作目录
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = ScriptRepo(Path(cls._tmp.name) / "scripts",
                              validator=lambda d: validate_script(d, valid_actions=valid))
        for path in sorted((cls.cfg_dir / "operation").glob("**/*.yaml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            cls.repo.create("default", doc["name"], doc)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _run(self, script: str, inputs: dict, transport=None, mounted_tool: int = 0,
             plc=None, auto_rail: bool = False):
        """以 RUN 模式在仿真机械臂上执行一个 operation, 返回 (终态, 记录执行器).

        参数:
            script: 待执行 operation 名
            inputs: 根脚本入参
            transport: 可选注入的仿真传输 (默认 home 位 SimRobotTransport);
                       供真空守卫测试注入"吸盘挂载 + 真空在"的 query 回报
            mounted_tool: 预置权威工具态 (0=裸腕/1=吸盘/2=大夹爪/3=小夹爪); 入口 prologue 的
                       robot_tool_ensure 据此判定, 传入本流程固定工具即令其 current==needed 跳过换刀
                       (本执行器无 PLC, 触发换刀会因 rail.move 无 PLC 而失败)
            plc: 可选注入的 PLC 桩; 换刀路径的 rail_move_safe(4) 需 rail.move 可派发时传入
        """
        home = self.points.get(self.home_point)
        if transport is None:
            transport = SimRobotTransport(pose=home.pose, joint=home.joint)
        transport.connect()
        transport.set_mounted_tool(mounted_tool)
        robot = RobotController(transport, self.points, home_point=self.home_point,
                                jog_speed_percent=20, step_distance_mm=1.0, step_angle_deg=1.0)
        ex_kwargs = {"robot": robot}
        if plc is not None:
            ex_kwargs["plc"] = plc
            ex_kwargs["points"] = _RailPoints()
            ex_kwargs["auto_rail"] = auto_rail
        rec = _RecordingExecutor(ActionExecutor(self.registry, **ex_kwargs))
        thread = VmThread(self.repo.get("default", script), executor=rec, res_gate=ResourceGate(),
                          resolve_script=lambda n: self.repo.get("default", n),
                          emit=lambda e: None, mode_provider=lambda: "RUN")
        status = asyncio.run(thread.run(inputs))
        return status, rec

    def test_tank_pick_3_point_sequence_matches_resolver(self) -> None:
        status, rec = self._run("robot_tank_pick", {"tank_id": 3}, mounted_tool=1)
        self.assertEqual(status, VmStatus.DONE)
        moves = [p["point_id_or_robot_name"] for n, p, _ in rec.calls if n == "robot.move_to_point"]
        expected = [s.point for s in self.catalog.resolve("tank.pick", {"tank_id": "3"}).flow.steps
                    if isinstance(s, MoveStep)]
        self.assertEqual(moves, expected)

    def test_run_mode_tool_action_and_anchors_pass(self) -> None:
        status, rec = self._run("robot_tank_pick", {"tank_id": 3}, mounted_tool=1)
        self.assertEqual(status, VmStatus.DONE)
        # 工具动作在 RUN 下执行成功 (吸盘吸取)
        tools = [(p.get("action"), st) for n, p, st in rec.calls if n == "robot.tool_action"]
        self.assertTrue(any(act == "suction-on" and st is ActionStatus.DONE for act, st in tools))
        # 分支进/出锚点校验 (branch require_anchor, 入口 prologue 换确保式后分支锚仍保留) 均执行且通过
        anchors = [st for n, _, st in rec.calls if n == "robot.require_anchor"]
        self.assertTrue(anchors)
        self.assertTrue(all(st is ActionStatus.DONE for st in anchors))
        # 入口 prologue 的确保式回零执行且通过 (sim 起于 home, 平凡通过零运动)
        home_ensures = [st for n, _, st in rec.calls if n == "robot.home_ensure"]
        self.assertTrue(home_ensures)
        self.assertTrue(all(st is ActionStatus.DONE for st in home_ensures))

    def test_two_param_group_rack_matches_resolver(self) -> None:
        status, rec = self._run("robot_group_rack_pick", {"rack_id": "collector", "slot_id": 4},
                                mounted_tool=2)
        self.assertEqual(status, VmStatus.DONE)
        moves = [p["point_id_or_robot_name"] for n, p, _ in rec.calls if n == "robot.move_to_point"]
        expected = [s.point for s in
                    self.catalog.resolve("group-rack.pick", {"rack_id": "collector", "slot_id": "4"}).flow.steps
                    if isinstance(s, MoveStep)]
        self.assertEqual(moves, expected)

    def test_invalid_selector_raises(self) -> None:
        status, _ = self._run("robot_tank_pick", {"tank_id": 9}, mounted_tool=1)
        self.assertEqual(status, VmStatus.ERROR)

    # ------------------------------------------------------------------
    # 智能换夹爪优化: 卸刀按工具差异安全收起 + 去掉卸->装之间的 home 往返
    # ------------------------------------------------------------------

    def test_suction_on_derived_from_commanded_bits(self) -> None:
        """改动A: _feedback_to_dict 由 commanded_bits 的 DO3 语义位(值2)派生 suction_on 布尔."""
        from eit_ptlc.action.executor import _feedback_to_dict
        from eit_ptlc.driver.robot_transport import RobotFeedback, ToolState

        def suction_on(bits: int) -> bool:
            ts = ToolState(commanded_bits=bits, actual_bits=0, di_bits=0,
                           di_available=False, di_confirmed=False)
            fb = RobotFeedback(pose=(0.0,) * 6, joint=(0.0,) * 6, check_result=0,
                               last_action=24, tool_state=ts)
            return _feedback_to_dict(fb)["tool_state"]["suction_on"]

        self.assertTrue(suction_on(2))     # 吸盘真空在 (DO3 语义位)
        self.assertTrue(suction_on(3))     # 含快换位(1) 但吸盘位仍置
        self.assertFalse(suction_on(0))    # 无真空
        self.assertFalse(suction_on(4))    # 夹爪位(DO2) 非吸盘

    def test_pick_gripper_opens_before_every_close(self) -> None:
        """取耗材/耗材板/夹具件前先张开夹爪, 防止闭合态进料撞机。"""
        scripts = [
            "robot_group_rack_pick",
            "robot_group_staging_pick",
            "robot_individual_pick",
            "robot_scrape_holder_pick_enter",
            "robot_collect_holder_pick_enter",
            "robot_collect_bottle_pick",
        ]
        for script in scripts:
            with self.subTest(script=script):
                path = self.cfg_dir / "operation" / "06_robot" / f"{script}.yaml"
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                previous_tool_action = None
                close_count = 0
                for node in _walk_nodes(doc.get("body")):
                    action = _tool_action_name(node)
                    if action == "gripper-close":
                        close_count += 1
                        self.assertEqual(previous_tool_action, "gripper-open")
                    if action:
                        previous_tool_action = action
                self.assertGreater(close_count, 0)

    def test_gripper_open_precedes_near_approach_descent(self) -> None:
        """夹取分支中 gripper-open 再前移: 已提到"下探到 near approach"之前。

        取 robot_group_rack_pick 首分支 (collector/slot 1): 逼近序列 mid=group-rack.p25.mid →
        near=group-rack.p25.near → P25(目标)。near 位常已贴近仓库位耗材板, 闭合态在此插入会蹭板,
        故张开须早于 near 下探。
        期望顺序: mid → gripper-open(确认张开) → near 下探 → move_l 下降到 P25 → gripper-close。
        """
        path = self.cfg_dir / "operation" / "06_robot" / "robot_group_rack_pick.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # 入口 prologue (comment + home_ensure + tool_ensure) 后, 首个业务 if 不再是 body[0]; 按 op 定位
        first_if = next(n for n in doc["body"] if n.get("op") == "if")
        then_body = first_if["then"]
        events: list[tuple[str, str]] = []
        for node in then_body:
            if node.get("op") != "call":
                continue
            if node.get("action") == "robot.move_to_point":
                events.append(("move", node["args"]["point_id_or_robot_name"]["lit"]))
            elif node.get("action") == "robot.tool_action":
                events.append(("tool", node["args"]["action"]["lit"]))
        near_idx = events.index(("move", "group-rack.p25.near"))   # 首次出现 = 下探 near
        open_idx = events.index(("tool", "gripper-open"))
        target_idx = events.index(("move", "P25"))
        close_idx = events.index(("tool", "gripper-close"))
        self.assertLess(open_idx, near_idx, "gripper-open 应在下探 near 之前 (闭合态勿在 near 位蹭板)")
        self.assertLess(near_idx, target_idx, "near 到位应在下降到目标 move_l 之前")
        self.assertLess(target_idx, close_idx, "闭合应在下降到目标之后")
        self.assertEqual(events[open_idx + 1], ("move", "group-rack.p25.near"),
                         "张开后紧接下探 near (中间无其它动作)")

    def test_put_suction_lowers_then_no_home_tail(self) -> None:
        """需求1+3: 卸吸盘前 rotary-down 到下降态; 卸刀收于抬升位(approach-high), 途中不回 home."""
        status, rec = self._run("robot_tool_put", {"tool_id": 1})
        self.assertEqual(status, VmStatus.DONE)
        tool_acts = [p.get("action") for n, p, _ in rec.calls if n == "robot.tool_action"]
        self.assertIn("rotary-down", tool_acts)
        moves = [p["point_id_or_robot_name"] for n, p, _ in rec.calls if n == "robot.move_to_point"]
        self.assertEqual(moves[-1], "robot-main.tool-change.slot-1.approach-high")   # 收于抬升位
        self.assertNotIn("robot-main.home", moves)                                   # 卸刀途中不回 home

    def test_put_gripper_closes_before_release(self) -> None:
        """需求2: 卸大/小夹爪前 gripper-close (闭合态), 且在 quick-change-release 之前; 不回 home."""
        for tool_id in (2, 3):
            status, rec = self._run("robot_tool_put", {"tool_id": tool_id})
            self.assertEqual(status, VmStatus.DONE)
            seq = [p.get("action") for n, p, _ in rec.calls if n == "robot.tool_action"]
            self.assertIn("gripper-close", seq)
            self.assertLess(seq.index("gripper-close"), seq.index("quick-change-release"))
            moves = [p["point_id_or_robot_name"] for n, p, _ in rec.calls if n == "robot.move_to_point"]
            self.assertNotIn("robot-main.home", moves)

    def test_pick_starts_without_home_anchor_and_returns_home(self) -> None:
        """需求3: 装刀首步非 require_anchor; 工具槽 high 间直线安全, 可直接进入目标槽; 末尾回 home + 校验."""
        for tool_id in (1, 2, 3):
            with self.subTest(tool_id=tool_id):
                status, rec = self._run("robot_tool_pick", {"tool_id": tool_id})
                self.assertEqual(status, VmStatus.DONE)
                self.assertEqual(rec.calls[0][0], "robot.move_to_point")             # 首动作不是 require_anchor
                self.assertEqual(
                    rec.calls[0][1]["point_id_or_robot_name"],
                    f"robot-main.tool-change.slot-{tool_id}.approach-high",
                )
                self.assertEqual(rec.calls[-1][0], "robot.require_anchor")           # 末步 home 校验
                moves = [p["point_id_or_robot_name"] for n, p, _ in rec.calls if n == "robot.move_to_point"]
                self.assertEqual(moves[-1], "robot-main.home")                      # 末个 move 回 home

    def test_ensure_aborts_when_suction_holds_board(self) -> None:
        """需求1: 当前是吸盘(1)且仍有真空 -> 守卫在任何移动前 raise (默认吸着板子)."""
        from eit_ptlc.driver.robot_transport import MotionOptions, RobotFeedback, ToolState

        class _VacuumHeldTransport(SimRobotTransport):
            """query 回报: 吸盘挂载 (mounted_tool=1) 且真空在 (commanded_bits=2)."""

            def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
                ts = ToolState(commanded_bits=2, actual_bits=0, di_bits=0, di_available=False,
                               di_confirmed=False, mounted_tool=1)
                return RobotFeedback(pose=tuple(self._pose), joint=tuple(self._joint),
                                     check_result=0, last_action=24, tool_state=ts,
                                     robot_mode=5, connected=True)

        home = self.points.get(self.home_point)
        transport = _VacuumHeldTransport(pose=home.pose, joint=home.joint)
        status, rec = self._run("robot_tool_ensure", {"needed": 2}, transport=transport)
        self.assertEqual(status, VmStatus.ERROR)                                     # 守卫 raise
        # 守卫在任何运动前中止: 只发生 robot.query, 无任何 move_to_point
        self.assertNotIn("robot.move_to_point", [n for n, _, _ in rec.calls])

    def test_pick_emits_no_aux_on(self) -> None:
        """问题1: 装刀 quick-change-lock 后不得发 tool-change-aux-on (=DO6=1 会让吸盘在工具站原位翻下)."""
        for tool_id in (1, 2, 3):
            status, rec = self._run("robot_tool_pick", {"tool_id": tool_id})
            self.assertEqual(status, VmStatus.DONE)
            acts = [p.get("action") for n, p, _ in rec.calls if n == "robot.tool_action"]
            self.assertNotIn("tool-change-aux-on", acts)

    def test_collect_unload_seam_hands_off_at_p70_without_home(self) -> None:
        """收集下料链取放接缝优化: 取件动作停在收集枢纽 P70 (不回 P1), 放件动作可从 P70 入
        (enter_anchor=P70); 接缝两侧各锚 P70, 整链仍 Home 进 Home 出。仿真臂上校验 P70/P1 锚点均通过。
        """
        # --- 取件动作: 末锚=P70, 末个 move=P70, 全程无 move 到 P1 (不再回家) ---
        # robot_collect_bottle_pick 起于 home (默认 transport); 入口 prologue needed=3, 预置小夹爪令换刀跳过
        status, rec = self._run("robot_collect_bottle_pick", {"station_id": "default"}, mounted_tool=3)
        self.assertEqual(status, VmStatus.DONE)
        self.assertEqual(rec.calls[-1][0], "robot.require_anchor")
        self.assertEqual(rec.calls[-1][1]["point_id"], "P70")            # 出锚点=收集枢纽
        moves = [p["point_id_or_robot_name"] for n, p, _ in rec.calls if n == "robot.move_to_point"]
        self.assertEqual(moves[-1], "P70")                              # 末个 move 停枢纽
        self.assertNotIn("P1", moves)                                   # 取件不再回家

        # robot_collect_holder_pick_exit 起于抓取锚 P74 (注入 P74 位仿真臂)
        p74 = self.points.get("P74")
        status, rec = self._run("robot_collect_holder_pick_exit", {"station_id": "default"},
                                transport=SimRobotTransport(pose=p74.pose, joint=p74.joint))
        self.assertEqual(status, VmStatus.DONE)
        self.assertEqual(rec.calls[-1][1]["point_id"], "P70")
        moves = [p["point_id_or_robot_name"] for n, p, _ in rec.calls if n == "robot.move_to_point"]
        self.assertEqual(moves[-1], "P70")
        self.assertNotIn("P1", moves)

        # --- 放件动作: 从 P70 入 (enter_anchor=P70), 入锚=P70 出锚仍=P1(回家) ---
        p70 = self.points.get("P70")
        for script, inputs in (
            ("robot_individual_put", {"rack_id": "bottle", "slot_id": 1, "enter_anchor": "P70"}),
            ("robot_collector_return_put", {"slot_id": 1, "enter_anchor": "P70"}),
        ):
            with self.subTest(put=script):
                status, rec = self._run(script, inputs,
                                        transport=SimRobotTransport(pose=p70.pose, joint=p70.joint))
                self.assertEqual(status, VmStatus.DONE)
                anchors = [p["point_id"] for n, p, _ in rec.calls if n == "robot.require_anchor"]
                self.assertEqual(anchors[0], "P70")                     # 入锚点=枢纽 (免回家交接)
                self.assertEqual(anchors[-1], "P1")                     # 出锚点仍=home

        # --- 回归: 不传 enter_anchor 时放件默认锚 P1, 既有调用者零影响 (默认 P1 入口触发条件式 prologue, 预置小夹爪跳过换刀) ---
        home = self.points.get(self.home_point)
        status, rec = self._run("robot_individual_put", {"rack_id": "bottle", "slot_id": 1},
                                transport=SimRobotTransport(pose=home.pose, joint=home.joint),
                                mounted_tool=3)
        self.assertEqual(status, VmStatus.DONE)
        anchors = [p["point_id"] for n, p, _ in rec.calls if n == "robot.require_anchor"]
        self.assertEqual(anchors[0], "P1")                             # 默认入锚点=home

    # ------------------------------------------------------------------
    # 入口保证 prologue: 换刀保证 (home_ensure + tool_ensure) 下沉子流程
    # ------------------------------------------------------------------

    def test_entry_tool_match_skips_change(self) -> None:
        """入口工具匹配: current==needed 时 prologue 换刀跳过 —— 无 rail.move、无换刀点位 move。"""
        status, rec = self._run("robot_group_rack_pick", {"rack_id": "collector", "slot_id": 1},
                                mounted_tool=2)
        self.assertEqual(status, VmStatus.DONE)
        self.assertNotIn("rail.move", [n for n, _, _ in rec.calls])          # 未换刀故未移轨到工具站
        moves = [p["point_id_or_robot_name"] for n, p, _ in rec.calls if n == "robot.move_to_point"]
        self.assertFalse(any("tool-change" in m for m in moves))             # 无工具站进近/槽位 move
        self.assertTrue([st for n, _, st in rec.calls if n == "robot.home_ensure"])  # home_ensure 已执行

    def test_entry_tool_mismatch_auto_changes(self) -> None:
        """入口工具不匹配: current!=needed 时 prologue 自动换刀 —— rail_move_safe(4) 移轨 + 卸旧装新。"""
        plc = _RailPlc()
        status, rec = self._run("robot_group_rack_pick", {"rack_id": "collector", "slot_id": 1},
                                mounted_tool=1, plc=plc)                     # 挂吸盘(1), 需大夹爪(2)
        self.assertEqual(status, VmStatus.DONE)
        # 换刀经 rail_move_safe(4) 移地轨到工具站
        self.assertIn((("rail", 10, {"Rail_Target_Position": 4})), plc.rail_moves)
        # 权威工具态更新: 卸吸盘(set 0) 再装大夹爪(set 2)
        set_tools = [p.get("tool_id") for n, p, _ in rec.calls if n == "robot.set_mounted_tool"]
        self.assertEqual(set_tools, [0, 2])
        # 卸/装经过工具槽 1 (吸盘) 与槽 2 (大夹爪) 的进近点
        moves = [p["point_id_or_robot_name"] for n, p, _ in rec.calls if n == "robot.move_to_point"]
        self.assertTrue(any("slot-1" in m for m in moves))                   # 卸吸盘途经槽1
        self.assertTrue(any("slot-2" in m for m in moves))                   # 装大夹爪途经槽2

    def test_entry_vacuum_held_blocks_change(self) -> None:
        """入口持真空拒换: 挂吸盘且真空在 (疑似吸板) 且需不同工具 -> tool_ensure 守卫 raise, 无任何 move。"""
        from eit_ptlc.driver.robot_transport import MotionOptions, RobotFeedback, ToolState

        class _VacuumHeldTransport(SimRobotTransport):
            def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
                ts = ToolState(commanded_bits=2, actual_bits=0, di_bits=0, di_available=False,
                               di_confirmed=False, mounted_tool=1)
                return RobotFeedback(pose=tuple(self._pose), joint=tuple(self._joint),
                                     check_result=0, last_action=24, tool_state=ts,
                                     robot_mode=5, connected=True)

        home = self.points.get(self.home_point)
        transport = _VacuumHeldTransport(pose=home.pose, joint=home.joint)
        # robot_group_rack_pick 需大夹爪(2); 挂吸盘(1)且真空在 -> 守卫拦截
        status, rec = self._run("robot_group_rack_pick", {"rack_id": "collector", "slot_id": 1},
                                transport=transport)
        self.assertEqual(status, VmStatus.ERROR)
        self.assertNotIn("robot.move_to_point", [n for n, _, _ in rec.calls])

    def test_entry_home_ensure_auto_return_from_safe_point(self) -> None:
        """入口不在 home 但在安全点 (P2) 邻域: prologue home_ensure 自动 move_j 回 home 并续跑。"""
        home = self.points.get(self.home_point)
        p2 = self.points.get("P2")
        transport = SimRobotTransport(pose=p2.pose, joint=p2.joint)
        status, rec = self._run("robot_group_rack_pick", {"rack_id": "collector", "slot_id": 1},
                                transport=transport, mounted_tool=2)
        self.assertEqual(status, VmStatus.DONE)
        self.assertTrue([st for n, _, st in rec.calls if n == "robot.home_ensure"
                         and st is ActionStatus.DONE])
        # 自动回零发生: 确保式内部经 transport.move_j 回 home (直调 transport, 不经 move_to_point 动作),
        # 且首个 move_j 即回 home (prologue 先于任何分支运动)
        move_js = [c[1] for c in transport.calls if c[0] == "move_j"]
        self.assertEqual(move_js[0], tuple(home.pose))

    def test_entry_outside_neighborhood_blocks(self) -> None:
        """入口不在 home 且不在任何安全点邻域: prologue home_ensure raise -> 流程 ERROR, 无业务 move。"""
        transport = SimRobotTransport(pose=(0.0,) * 6, joint=(0.0,) * 6)     # 全零, 非任何安全点
        status, rec = self._run("robot_group_rack_pick", {"rack_id": "collector", "slot_id": 1},
                                transport=transport, mounted_tool=2)
        self.assertEqual(status, VmStatus.ERROR)
        self.assertNotIn("robot.move_to_point", [n for n, _, _ in rec.calls])

    def test_exit_flow_has_no_prologue(self) -> None:
        """exit 流程 (工位内入口 P77) 不加 prologue: 无 home_ensure, 首个锚点=P77。"""
        p77 = self.points.get("P77")
        transport = SimRobotTransport(pose=p77.pose, joint=p77.joint)
        status, rec = self._run("robot_scrape_holder_pick_exit", {"station_id": "default"},
                                transport=transport)
        self.assertEqual(status, VmStatus.DONE)
        self.assertNotIn("robot.home_ensure", [n for n, _, _ in rec.calls])   # 无入口确保式
        anchors = [p["point_id"] for n, p, _ in rec.calls if n == "robot.require_anchor"]
        self.assertEqual(anchors[0], "P77")                                   # 入口锚=工位内 P77

    def test_startup_check_auto_return_from_safe_point(self) -> None:
        """起手自检: 臂在安全点 P2 时 home_ensure 自动回零 -> DONE (不再断言式硬停)。"""
        p2 = self.points.get("P2")
        transport = SimRobotTransport(pose=p2.pose, joint=p2.joint)
        status, rec = self._run("robot_startup_check", {}, transport=transport)
        self.assertEqual(status, VmStatus.DONE)
        home_ensures = [st for n, _, st in rec.calls if n == "robot.home_ensure"]
        self.assertTrue(home_ensures and all(st is ActionStatus.DONE for st in home_ensures))


if __name__ == "__main__":
    unittest.main(verbosity=2)
