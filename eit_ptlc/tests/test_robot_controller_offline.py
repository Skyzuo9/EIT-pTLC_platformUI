"""机器人控制器离线测试
======================
功能:
    用记录型 fake 传输 + 真实点表, 验证 RobotController 的点位解析 / 门控 /
    jog / step / move 委派. 不依赖真机.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_robot_controller_offline
"""

from __future__ import annotations

import sys
from pathlib import Path

from eit_ptlc.controller.point_registry import PointRegistry
from eit_ptlc.controller.robot_controller import RobotController
from eit_ptlc.driver.robot_transport import (
    MotionOptions, RobotFeedback, RobotTransport, ToolAction, ToolState,
)

_CFG = Path(__file__).resolve().parent.parent / "config"


def _fb() -> RobotFeedback:
    return RobotFeedback(pose=(0.0,) * 6, joint=(0.0,) * 6, check_result=0, last_action=0,
                         tool_state=ToolState(0, 0, 0, False, False))


class _RecordingTransport(RobotTransport):
    """记录调用的 fake 传输."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        # tool_action 的两个测试钩子. 真机上这个调用会阻塞整段物理行程(翻转最坏等满
        # tool_di_timeout 10s), 而"发令即公告"的全部意义就在那段窗口里 —— 离线只能靠
        # 在返回前回调一次来观测它.
        self.during_tool_action = None   # 返回前调用, 用来窥视此刻的孪生快照
        self.tool_action_error = None    # 置成异常实例则抛出, 用来验证撤回

    def connect(self) -> None:
        self.calls.append(("connect",))

    def close(self) -> None:
        self.calls.append(("close",))

    def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        self.calls.append(("query",))
        return _fb()

    def move_j(self, pose, options=MotionOptions(), *, joint=None) -> RobotFeedback:
        self.calls.append(("move_j", tuple(pose), tuple(joint) if joint else None))
        return _fb()

    def move_l(self, pose, options=MotionOptions(), *, joint=None) -> RobotFeedback:
        self.calls.append(("move_l", tuple(pose)))
        return _fb()

    def tool_action(self, action, timeout_ms=3000) -> RobotFeedback:
        self.calls.append(("tool_action", int(action), timeout_ms))
        if self.during_tool_action is not None:
            self.during_tool_action()
        if self.tool_action_error is not None:
            raise self.tool_action_error
        return _fb()

    def jog_start(self, axis_id, options=MotionOptions()) -> None:
        self.calls.append(("jog_start", axis_id, options.user, options.tool))

    def jog_stop(self) -> None:
        self.calls.append(("jog_stop",))

    def step(self, axis, distance, options=MotionOptions(), *, motion="l") -> RobotFeedback:
        self.calls.append(("step", axis, distance, motion))
        return _fb()

    def stop(self) -> None:
        self.calls.append(("stop",))

    def pause(self) -> None:
        self.calls.append(("pause",))

    def resume(self) -> None:
        self.calls.append(("resume",))

    def emergency_stop(self, pressed: bool = True) -> None:
        self.calls.append(("emergency_stop", pressed))

    def clear_error(self, *, confirm: bool = False) -> RobotFeedback:
        self.calls.append(("clear_error", confirm))
        return _fb()

    def enable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        self.calls.append(("enable_robot", confirm))
        return _fb()

    def disable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        self.calls.append(("disable_robot", confirm))
        return _fb()


def _make() -> tuple[RobotController, _RecordingTransport]:
    reg = PointRegistry.load(_CFG / "points" / "robot" / "robot_points.json", source_version="v0.11",
                             meta_path=_CFG / "points" / "robot" / "robot_points_meta.json")
    t = _RecordingTransport()
    return RobotController(t, reg, home_point="robot-main.home", jog_speed_percent=20,
                           step_distance_mm=1.0, step_angle_deg=1.0), t


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ctrl, t = _make()
    failures: list[str] = []

    total = 0

    def check(name, cond, detail=""):
        nonlocal total
        total += 1
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    home = ctrl.registry.get("robot-main.home")

    # 回原点 -> move_j(home.pose, joint=home.joint)
    ctrl.home()
    check("home_move_j", t.calls[-1] == ("move_j", home.pose, home.joint), str(t.calls[-1]))

    # 关节到点
    ctrl.move_j("robot-main.home")
    check("move_j_point", t.calls[-1][0] == "move_j" and t.calls[-1][2] == home.joint, str(t.calls[-1]))

    # 直线到点
    ctrl.move_l("robot-main.home")
    check("move_l_point", t.calls[-1] == ("move_l", home.pose), str(t.calls[-1]))

    # 点动起停
    ctrl.jog_start("X+")
    check("jog_start", t.calls[-1] == ("jog_start", "X+", 0, 1), str(t.calls[-1]))
    ctrl.jog_stop()
    check("jog_stop", t.calls[-1] == ("jog_stop",), str(t.calls[-1]))

    # 步进 (笛卡尔显式)
    ctrl.step("Z", -2.0)
    check("step_cartesian", t.calls[-1] == ("step", "Z", -2.0, "l"), str(t.calls[-1]))

    # 步进 (关节默认增量 = step_angle_deg=1.0)
    ctrl.step("J1")
    check("step_joint_default", t.calls[-1] == ("step", "J1", 1.0, "l"), str(t.calls[-1]))

    # 中止 / 暂停 / 恢复 / 急停 委派 (绕过动作锁)
    ctrl.stop()
    check("stop", t.calls[-1] == ("stop",), str(t.calls[-1]))
    ctrl.pause()
    check("pause", t.calls[-1] == ("pause",), str(t.calls[-1]))
    ctrl.resume()
    check("resume", t.calls[-1] == ("resume",), str(t.calls[-1]))
    ctrl.emergency_stop()
    check("emergency_stop", t.calls[-1] == ("emergency_stop", True), str(t.calls[-1]))
    ctrl.emergency_stop(pressed=False)
    check("emergency_release", t.calls[-1] == ("emergency_stop", False), str(t.calls[-1]))

    # 清警 / 使能 委派 (confirm 透传)
    ctrl.clear_error(confirm=True)
    check("clear_error", t.calls[-1] == ("clear_error", True), str(t.calls[-1]))
    ctrl.enable_robot(confirm=True)
    check("enable_robot", t.calls[-1] == ("enable_robot", True), str(t.calls[-1]))
    ctrl.disable_robot(confirm=True)
    check("disable_robot", t.calls[-1] == ("disable_robot", True), str(t.calls[-1]))

    # 重连: 先 close 再 connect, 末尾 query 取一次反馈 (断联恢复幂等)
    del t.calls[:]
    ctrl.reconnect()
    check("reconnect", t.calls == [("close",), ("connect",), ("query",)], str(t.calls))

    # ── 末端执行器数字孪生快照 (tool_action 缓存 + 按挂载工具门控发布) ──
    # 挂 2 号大夹爪: close -> rob_grip_plate96 = true(闭合); fake 传输无 DI -> commanded
    ctrl.set_mounted_tool(2)
    ctrl.tool_action(ToolAction.GRIPPER_CLOSE)
    snap = ctrl.mechanism_snapshot()
    check("twin_plate96_close", snap == {"rob_grip_plate96": {
        "commanded": True, "confirmed": None, "available": True, "source": "commanded"}}, str(snap))

    # 换挂 3 号: plate96 停止发布(前端保末态即冻结), vial 尚无缓存 -> 空快照
    ctrl.set_mounted_tool(3)
    check("twin_switch_freezes", ctrl.mechanism_snapshot() == {}, str(ctrl.mechanism_snapshot()))
    ctrl.tool_action(ToolAction.GRIPPER_OPEN)
    snap = ctrl.mechanism_snapshot()
    check("twin_vial_open", snap.get("rob_grip_vial", {}).get("commanded") is False
          and "rob_grip_plate96" not in snap, str(snap))

    # 挂 1 号吸盘: 上翻=true / 下翻=false (true=DO2 侧=偏离模型基准位)
    ctrl.set_mounted_tool(1)
    ctrl.tool_action(ToolAction.ROTARY_UP)
    check("twin_flip_up", ctrl.mechanism_snapshot().get("rob_flip_suction", {}).get("commanded") is True,
          str(ctrl.mechanism_snapshot()))
    ctrl.tool_action(ToolAction.ROTARY_DOWN)
    check("twin_flip_down", ctrl.mechanism_snapshot()["rob_flip_suction"]["commanded"] is False,
          str(ctrl.mechanism_snapshot()))

    # ── 发令即公告: 翻转在**行程中**就必须可见 ──────────────────────────────
    # 病根曾是只在 transport.tool_action 返回之后写一次缓存, 而那一次调用阻塞整段物理
    # 行程(翻转是 di_or_dwell, 等 DI 上限 tool_di_timeout=10s), 于是 /3d/live 上表现为
    # "实物转完之后画面才一瞬间转过去". 这里是唯一能离线确定性验证它的地方 —— 仿真/fake
    # 传输瞬时返回, 生产端 10Hz 的机构采样根本采不到那个在途窗口.
    check("twin_flip_settled", ctrl.mechanism_snapshot()["rob_flip_suction"]["moving"] is False,
          str(ctrl.mechanism_snapshot()))
    seen: list[dict] = []
    t.during_tool_action = lambda: seen.append(ctrl.mechanism_snapshot())
    ctrl.tool_action(ToolAction.ROTARY_UP)
    t.during_tool_action = None
    check("twin_flip_inflight", bool(seen) and seen[0].get("rob_flip_suction") == {
        "commanded": True, "confirmed": None, "available": True,
        "source": "commanded", "moving": True}, str(seen))
    check("twin_flip_inflight_settles", ctrl.mechanism_snapshot()["rob_flip_suction"] == {
        "commanded": True, "confirmed": None, "available": True,
        "source": "commanded", "moving": False}, str(ctrl.mechanism_snapshot()))

    # 失败撤回: 动作没跑成(门控拒绝/通讯断)不得给三维留一个没发生过的姿态
    before_fail = ctrl.mechanism_snapshot()["rob_flip_suction"]
    t.tool_action_error = RuntimeError("传输拒绝")
    try:
        ctrl.tool_action(ToolAction.ROTARY_DOWN)
        raised = False
    except RuntimeError:
        raised = True
    t.tool_action_error = None
    check("twin_flip_rollback",
          raised and ctrl.mechanism_snapshot()["rob_flip_suction"] == before_fail,
          str(ctrl.mechanism_snapshot()))
    ctrl.tool_action(ToolAction.ROTARY_DOWN)   # 复位, 供后面的语义门用例接着走

    # 裸腕不发布; 重挂 2 号恢复上次 close 姿态(缓存按 id 保留)
    ctrl.set_mounted_tool(0)
    check("twin_bare_wrist_empty", ctrl.mechanism_snapshot() == {}, str(ctrl.mechanism_snapshot()))
    ctrl.set_mounted_tool(2)
    check("twin_remount_restores", ctrl.mechanism_snapshot()["rob_grip_plate96"]["commanded"] is True,
          str(ctrl.mechanism_snapshot()))

    # 语义门: fake/仿真传输不做工具门控, 控制器按"动作×工具"再挡一道 ——
    # 挂 2 号发 rotary 不得污染吸盘缓存(上一步 flip 仍为 false)
    ctrl.tool_action(ToolAction.ROTARY_UP)
    ctrl.set_mounted_tool(1)
    check("twin_semantic_gate", ctrl.mechanism_snapshot()["rob_flip_suction"]["commanded"] is False,
          str(ctrl.mechanism_snapshot()))

    # 未知点位 -> KeyError
    try:
        ctrl.move_j("不存在的点")
        check("unknown_point", False, "应抛 KeyError")
    except KeyError:
        check("unknown_point", True)

    # 非 validated 点位 -> PermissionError
    non_validated = next((p for p in ctrl.registry.points if p.status != "validated"), None)
    if non_validated is not None:
        try:
            ctrl.move_j(non_validated.point_id)
            check("non_validated_gate", False, "应抛 PermissionError")
        except PermissionError:
            check("non_validated_gate", True)
    else:
        check("non_validated_gate", True, "无非 validated 点, 跳过")

    # 用例数由 check 自己数. 原先这里写死 26, 加了用例也不涨 —— 一个"看着还是那么多"的
    # 汇总行会掩盖掉"新用例根本没跑到"这种失败方式.
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
