"""Dobot 驱动离线测试
====================
功能:
    用 fake dashboard / feedback 通道验证 jog / step / move 生成的 29999 命令线格式,
    不依赖真机或网络. 注入 fake 通道绕过 connect() 的 socket.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_dobot_driver_offline
期望:
    全部用例打印 PASS, 退出码 0.
"""

from __future__ import annotations

import logging
import sys
import queue
import threading
import time

from eit_ptlc.driver.dobot_tcp_driver import (
    DashboardReply,
    DobotFeedbackFrame,
    DobotTcpRobotTransport,
    RobotMode,
)
from eit_ptlc.driver.robot_transport import (
    MotionOptions,
    MountedTool,
    RobotActionError,
    RobotTransportError,
    ToolAction,
)


class _FakeDash:
    """fake 29999 通道: 记录发送命令, 按命令类型返回 ErrorID/CommandId."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def close(self) -> None:
        pass

    def command(self, cmd: str) -> DashboardReply:
        self.sent.append(cmd)
        if cmd.startswith("MoveJog"):
            return DashboardReply(0, (), cmd)            # 点动无 CommandId
        if cmd.startswith(("RelMovLUser", "RelMovJUser", "RelJointMovJ", "MovJ", "MovL", "DO(")):
            return DashboardReply(0, (123.0,), cmd)       # 运动返回 CommandId=123
        if cmd.startswith("RobotMode"):
            return DashboardReply(0, (5.0,), cmd)
        return DashboardReply(0, (), cmd)


def _frame(mode: int, cid: int) -> DobotFeedbackFrame:
    return DobotFeedbackFrame(
        robot_mode=mode, current_command_id=cid, digital_inputs=0, digital_outputs=0,
        pose=(0.0,) * 6, joint=(0.0,) * 6, error_status=False, collision_state=False,
        enable_status=True, auto_manual_mode=0, safety_state=0,
    )


class _FakeFb:
    """fake 30004 通道: 始终返回使能空闲 + CommandId=123 的反馈帧."""

    def __init__(self) -> None:
        self.frame = _frame(RobotMode.ENABLED_IDLE, 123)

    def close(self) -> None:
        pass

    def read_frame(self) -> DobotFeedbackFrame:
        return self.frame


class _QueuedFb:
    """阻塞 fake：记录真正执行 read_frame 的线程，用于证明只有后台泵读 30004。"""

    def __init__(self) -> None:
        self.frames: queue.Queue[DobotFeedbackFrame | None] = queue.Queue()
        self.reader_threads: list[int] = []

    def close(self) -> None:
        self.frames.put(None)

    def read_frame(self) -> DobotFeedbackFrame:
        self.reader_threads.append(threading.get_ident())
        frame = self.frames.get(timeout=1.0)
        if frame is None:
            raise OSError("closed")
        return frame


def _make() -> DobotTcpRobotTransport:
    t = DobotTcpRobotTransport("127.0.0.1")
    t._dashboard = _FakeDash()
    t._feedback = _FakeFb()
    return t


def test_feedback_observer_reuses_read_frame_and_is_isolated() -> None:
    seen: list[DobotFeedbackFrame] = []
    t = _make()
    t.set_feedback_observer(seen.append)
    frame = t._read_frame()
    assert seen == [frame]

    # 孪生旁路失败不得改变机器人控制读帧结果。
    t.set_feedback_observer(lambda _frame: (_ for _ in ()).throw(RuntimeError("observer")))
    assert t._read_frame() == frame
    t.set_feedback_observer(seen.append, replay_latest=True)
    assert seen[-1] == frame


def test_行程标定_di本来就到位时不得记成一程() -> None:
    """防御性复令不得污染行程标定 —— 2026-08-05 "上翻瞬移" 的真病根.

    流程会把 rotary 当状态确认重下 (robot_suction_pick 同一次运行发两次 rotary-up).
    缸本来就停在上位, DI1 早已置位, _wait_di 第一帧就满足 -> 量到的是**一个反馈周期**
    (约 10ms) 而不是行程. 那个假值被当标定下发, 前端 speed=span/0.01 一帧走完全程.
    下翻从不被复发, 标定一直干净 —— 于是表现成 "上翻瞬移、下翻正常" 的方向性错觉.
    """
    t = _make()
    # DI1 已经是高电平 = 缸已在上位
    t._feedback.frame = DobotFeedbackFrame(
        robot_mode=RobotMode.ENABLED_IDLE, current_command_id=123,
        digital_inputs=0b1, digital_outputs=0,
        pose=(0.0,) * 6, joint=(0.0,) * 6, error_status=False, collision_state=False,
        enable_status=True, auto_manual_mode=0, safety_state=0,
    )
    t._wait_di_timed(ToolAction.ROTARY_UP, 1, True)
    assert t.last_tool_stroke_s(ToolAction.ROTARY_UP) is None, "没真走的一程不得写进标定"


def test_行程标定_真走过一程才记录() -> None:
    """对照组: DI 起初为低、随后置位 —— 这才是有效样本, 必须记下来."""
    t = _make()
    low = DobotFeedbackFrame(
        robot_mode=RobotMode.ENABLED_IDLE, current_command_id=123,
        digital_inputs=0, digital_outputs=0,
        pose=(0.0,) * 6, joint=(0.0,) * 6, error_status=False, collision_state=False,
        enable_status=True, auto_manual_mode=0, safety_state=0,
    )
    high = DobotFeedbackFrame(
        robot_mode=RobotMode.ENABLED_IDLE, current_command_id=123,
        digital_inputs=0b1, digital_outputs=0,
        pose=(0.0,) * 6, joint=(0.0,) * 6, error_status=False, collision_state=False,
        enable_status=True, auto_manual_mode=0, safety_state=0,
    )

    class _Ramp:
        """前两帧 DI 低, 之后置位 —— 模拟一段真实行程."""

        def __init__(self) -> None:
            self.n = 0

        def close(self) -> None:
            pass

        def read_frame(self) -> DobotFeedbackFrame:
            self.n += 1
            if self.n <= 2:
                # 行程要占真实时间才量得出来。睡满 60ms 是为了越过 Windows 上
                # time.monotonic() 约 15.6ms 的时钟粒度 —— 睡 10ms 时两次采样
                # 可能落在同一个 tick 里, 量到的恒为 0.0, 测试会假失败。
                time.sleep(0.06)
                return low
            return high

    ramp = _Ramp()
    t._feedback = ramp
    t._wait_di_timed(ToolAction.ROTARY_UP, 1, True)
    stroke = t.last_tool_stroke_s(ToolAction.ROTARY_UP)
    assert ramp.n == 3, f"应当是 探针1帧 + 等到位2帧: {ramp.n}"
    assert stroke is not None and stroke > 0, f"真走过的一程必须记录: {stroke}"


def test_feedback_pump_is_the_only_30004_reader() -> None:
    t = _make()
    feedback = _QueuedFb()
    t._feedback = feedback
    t.command_timeout = 0.5
    seen: list[DobotFeedbackFrame] = []
    t.set_feedback_observer(seen.append, replay_latest=False)
    t._start_feedback_pump()
    first = _frame(RobotMode.ENABLED_IDLE, 1)
    feedback.frames.put(first)
    deadline = time.monotonic() + 0.5
    while t._feedback_generation < 1 and time.monotonic() < deadline:
        time.sleep(0.001)
    second = _frame(RobotMode.RUNNING, 2)
    timer = threading.Timer(0.02, feedback.frames.put, args=(second,))
    timer.start()
    try:
        assert t._read_frame() == second
        assert seen[-2:] == [first, second]
        assert set(feedback.reader_threads) == {t._feedback_thread.ident}
        assert threading.get_ident() not in feedback.reader_threads
    finally:
        timer.join()
        t._close_channels()


def test_jog_start_stop() -> None:
    t = _make()
    t.jog_start("X+", MotionOptions(user=0, tool=1))
    assert t._dashboard.sent[-1] == "MoveJog(X+,coordtype=1,user=0,tool=1)", t._dashboard.sent[-1]
    t.jog_stop()
    assert t._dashboard.sent[-1] == "MoveJog()", t._dashboard.sent[-1]


def test_speed_factor_applied() -> None:
    t = _make()
    t._apply_speed_factor()
    assert t._dashboard.sent[-1] == "SpeedFactor(20)", t._dashboard.sent[-1]
    t.set_speed_factor(35)
    assert t._dashboard.sent[-1] == "SpeedFactor(35)", t._dashboard.sent[-1]
    assert t.speed_factor == 35


def test_apply_speed_factor_propagates_link_close() -> None:
    # 链路级失败 (机器人关闭 29999) 不可被吞: connect 须如实失败置空通道, 不可伪装成功后再于遥测掉线
    class _LinkClosedDash:
        def close(self) -> None:
            pass

        def command(self, cmd: str):
            raise RobotTransportError("机器人关闭 29999 连接")

    t = DobotTcpRobotTransport("127.0.0.1")
    t._dashboard = _LinkClosedDash()
    t._feedback = _FakeFb()
    try:
        t._apply_speed_factor()
    except RobotTransportError:
        return
    raise AssertionError("SpeedFactor 链路级失败应上抛, 不应被吞")


def test_apply_speed_factor_swallows_action_error() -> None:
    # 机器人有应答但按 ErrorID 拒绝 (报警/未就绪/不在 TCP 模式): 仅告警跳过, 不阻断连接建立
    class _RejectDash:
        def close(self) -> None:
            pass

        def command(self, cmd: str) -> DashboardReply:
            return DashboardReply(-1, (), cmd)  # ErrorID!=0 -> RobotActionError

    t = DobotTcpRobotTransport("127.0.0.1")
    t._dashboard = _RejectDash()
    t._feedback = _FakeFb()
    try:
        t._apply_speed_factor()  # 不应抛
    except RobotActionError:
        raise AssertionError("机器人按 ErrorID 拒绝 SpeedFactor 应被吞跳过, 不应阻断连接")


def test_speed_factor_out_of_range() -> None:
    t = _make()
    try:
        t.set_speed_factor(0)
    except ValueError:
        return
    raise AssertionError("speed_factor 越界应抛 ValueError")


def test_set_output_waits_for_do_completion() -> None:
    # PALLAS 补光 DO7 也必须等待机器人回到 idle; 否则紧随其后的 move_to_point 会撞上 RobotMode=RUNNING。
    t = _make()
    t.set_output(7, True)
    assert t._dashboard.sent[-1] == "DO(7,1)", t._dashboard.sent[-1]
    assert t._last_dispatched_command_id == 123, "set_output 应等待 DO 命令完成"


def test_jog_invalid_axis() -> None:
    t = _make()
    try:
        t.jog_start("Q+")
    except ValueError:
        return
    raise AssertionError("非法点动轴应抛 ValueError")


def test_step_cartesian_linear() -> None:
    t = _make()
    fb = t.step("Z", -2.0, MotionOptions(user=0, tool=1, acc=20, vel=20, cp=0), motion="l")
    expected = "RelMovLUser(0.000000,0.000000,-2.000000,0.000000,0.000000,0.000000,user=0,tool=1,a=20,v=20,cp=0)"
    assert t._dashboard.sent[-1] == expected, t._dashboard.sent[-1]
    assert fb.robot_mode == RobotMode.ENABLED_IDLE


def test_step_cartesian_joint_interp() -> None:
    t = _make()
    t.step("X", 5.0, MotionOptions(user=0, tool=1, acc=20, vel=20, cp=0), motion="j")
    expected = "RelMovJUser(5.000000,0.000000,0.000000,0.000000,0.000000,0.000000,user=0,tool=1,a=20,v=20,cp=0)"
    assert t._dashboard.sent[-1] == expected, t._dashboard.sent[-1]


def test_step_joint() -> None:
    t = _make()
    t.step("J1", 1.5, MotionOptions(acc=20, vel=20, cp=0))
    expected = "RelJointMovJ(1.500000,0.000000,0.000000,0.000000,0.000000,0.000000,a=20,v=20,cp=0)"
    assert t._dashboard.sent[-1] == expected, t._dashboard.sent[-1]


def test_step_invalid_axis() -> None:
    t = _make()
    try:
        t.step("W", 1.0)
    except ValueError:
        return
    raise AssertionError("非法步进轴应抛 ValueError")


def test_move_l_and_j() -> None:
    t = _make()
    t.move_l((1, 2, 3, 4, 5, 6), MotionOptions(user=0, tool=1, acc=20, vel=20, cp=0))
    assert t._dashboard.sent[-1].startswith("MovL(pose={1.000000,2.000000,3.000000,"), t._dashboard.sent[-1]
    t.move_j((0,) * 6, MotionOptions(user=0, tool=1, acc=20, vel=20, cp=0), joint=(10, 20, 30, 40, 50, 60))
    assert t._dashboard.sent[-1].startswith("MovJ(joint={10.000000,20.000000,"), t._dashboard.sent[-1]


def test_stop_pause_resume() -> None:
    t = _make()
    t.stop()
    assert t._dashboard.sent[-1] == "Stop()", t._dashboard.sent[-1]
    assert t._stop_event.is_set(), "stop() 应置中止信号"
    t.pause()
    assert t._dashboard.sent[-1] == "Pause()", t._dashboard.sent[-1]
    t.resume()
    assert t._dashboard.sent[-1] == "Continue()", t._dashboard.sent[-1]


def test_emergency_stop() -> None:
    t = _make()
    t.emergency_stop()
    assert t._dashboard.sent[-1] == "EmergencyStop(1)", t._dashboard.sent[-1]
    assert t._stop_event.is_set(), "急停按下应置中止信号"
    t.emergency_stop(pressed=False)
    assert t._dashboard.sent[-1] == "EmergencyStop(0)", t._dashboard.sent[-1]


def test_disable_robot_gating_and_command() -> None:
    # 未配置 allow_enable_command -> 即便 confirm 也拒绝
    t = _make()
    try:
        t.disable_robot(confirm=True)
    except PermissionError:
        pass
    else:
        raise AssertionError("未配置 allow_enable_command 应拒绝 DisableRobot")
    # 配置允许但缺 confirm -> 拒绝
    t2 = DobotTcpRobotTransport("127.0.0.1", allow_enable_command=True)
    t2._dashboard = _FakeDash()
    t2._feedback = _FakeFb()
    try:
        t2.disable_robot(confirm=False)
    except PermissionError:
        pass
    else:
        raise AssertionError("缺少 confirm 应拒绝 DisableRobot")
    # 配置允许 + confirm -> 发 DisableRobot() 并等 DISABLED
    t2._feedback.frame = _frame(RobotMode.DISABLED, 123)
    fb = t2.disable_robot(confirm=True)
    assert t2._dashboard.sent[-1] == "DisableRobot()", t2._dashboard.sent[-1]
    assert fb.robot_mode == RobotMode.DISABLED, fb.robot_mode


def test_wait_command_interrupt() -> None:
    # 置中止信号后 _wait_command 应抛 RobotMotionInterrupted (区分"被中止"与"完成")
    from eit_ptlc.driver.robot_transport import RobotMotionInterrupted
    t = _make()
    t._stop_event.set()
    try:
        t._wait_command(123, timeout=1.0)
    except RobotMotionInterrupted:
        return
    raise AssertionError("置中止信号后 _wait_command 应抛 RobotMotionInterrupted")


def test_tool_gate_none_rejects_semantic_but_allows_change() -> None:
    # 默认 = NONE(裸腕): 语义工具动作 (吸/夹/翻) 拒发, 换刀联轴/辅助永远放行
    t = _make()
    assert t.mounted_tool == MountedTool.NONE
    for action in (ToolAction.SUCTION_ON, ToolAction.GRIPPER_CLOSE, ToolAction.ROTARY_UP):
        try:
            t.tool_action(action)
        except PermissionError:
            pass
        else:
            raise AssertionError(f"NONE 下 {action.name} 应被拒")
    # 换刀联轴 + 辅助 (写 DO1/DO6) 必须放行, 否则裸腕时连挂刀都做不了
    before = len(t._dashboard.sent)
    t.tool_action(ToolAction.QUICK_CHANGE_LOCK)
    t.tool_action(ToolAction.TOOL_CHANGE_AUX_ON)
    assert len(t._dashboard.sent) > before, "quick-change/aux 应放行并下发命令"


def test_tool_gate_by_slot() -> None:
    # slot1(吸盘): 允许吸/翻, 拒夹爪; slot2(夹爪): 允许夹, 拒翻
    t = _make()
    t.set_mounted_tool(MountedTool.SLOT1)
    t.tool_action(ToolAction.SUCTION_ON)
    t.tool_action(ToolAction.ROTARY_UP)
    try:
        t.tool_action(ToolAction.GRIPPER_CLOSE)
    except PermissionError:
        pass
    else:
        raise AssertionError("slot1 挂吸盘时 gripper-close 应被拒")
    t.set_mounted_tool(MountedTool.SLOT2)
    t.tool_action(ToolAction.GRIPPER_OPEN)
    try:
        t.tool_action(ToolAction.ROTARY_DOWN)
    except PermissionError:
        pass
    else:
        raise AssertionError("slot2 挂夹爪时 rotary-down 应被拒")


def test_tool_change_aux_off_vents_both_wrist_ports() -> None:
    # 卸刀 release 后 aux-off 须排空两个手腕作动口 (DO2 夹爪合气/翻上 + DO6 配合线),
    # 否则卸夹爪后裸腕 DO2 口持续喷气 (现场故障); 单测钉死 aux-off 同时清 DO2 与 DO6
    t = _make()
    t.set_mounted_tool(MountedTool.SLOT2)
    t.tool_action(ToolAction.GRIPPER_CLOSE)        # 合气置 DO2=1
    before = len(t._dashboard.sent)
    t.tool_action(ToolAction.TOOL_CHANGE_AUX_OFF)  # 卸刀辅助关: 须清 DO2 与 DO6
    sent = t._dashboard.sent[before:]
    assert "DO(2,0)" in sent, sent
    assert "DO(6,0)" in sent, sent
    assert (t._tool_commanded_bits & 4) == 0, "aux-off 后夹爪合气语义位(DO2)应清零"


def test_rotary_di_mapping_and_interlock() -> None:
    # rotary-up: 清 DO6 -> 200ms 互锁 -> 给 DO2 -> 等 DI1; rotary-down 对称等 DI2
    slept: list[float] = []
    t = DobotTcpRobotTransport("127.0.0.1", tool_di_feedback_enabled=True, sleep_fn=slept.append)
    t._dashboard = _FakeDash()
    t._feedback = _FakeFb()
    t._feedback.frame = _frame(RobotMode.ENABLED_IDLE, 123)
    t._feedback.frame = DobotFeedbackFrame(
        robot_mode=RobotMode.ENABLED_IDLE, current_command_id=123, digital_inputs=0b11,
        digital_outputs=0, pose=(0.0,) * 6, joint=(0.0,) * 6, error_status=False,
        collision_state=False, enable_status=True, auto_manual_mode=0, safety_state=0,
    )
    t.set_mounted_tool(MountedTool.SLOT1)
    fb = t.tool_action(ToolAction.ROTARY_UP)
    assert t._dashboard.sent[-2:] == ["DO(6,0)", "DO(2,1)"], t._dashboard.sent[-2:]
    assert 0.2 in slept, "rotary 切位间应有 200ms 互锁停顿"
    assert fb.tool_state.di_confirmed, "启用 DI 时 rotary 应确认到位"
    fb = t.tool_action(ToolAction.ROTARY_DOWN)
    assert t._dashboard.sent[-2:] == ["DO(2,0)", "DO(6,1)"], t._dashboard.sent[-2:]


def test_gripper_di_mapping() -> None:
    # 夹爪到位判据: 张开等 DI2, 闭合等 DI1 (现场接线确认); 用单 bit 区分通道, 防 DI 反向回归
    # tool_di_timeout 设小值: 万一映射被改回反向, 会等错 bit 在 0.1s 内 TimeoutError 而非死等 10s
    t = DobotTcpRobotTransport("127.0.0.1", tool_di_feedback_enabled=True, tool_di_timeout=0.1)
    t._dashboard = _FakeDash()
    t._feedback = _FakeFb()
    t.set_mounted_tool(MountedTool.SLOT2)  # SLOT2 放行夹爪 (吸盘/翻面归 SLOT1)
    # 张开: 仅置 DI2(0b10) 应确认到位
    t._feedback.frame = DobotFeedbackFrame(
        robot_mode=RobotMode.ENABLED_IDLE, current_command_id=123, digital_inputs=0b10,
        digital_outputs=0, pose=(0.0,) * 6, joint=(0.0,) * 6, error_status=False,
        collision_state=False, enable_status=True, auto_manual_mode=0, safety_state=0,
    )
    fb = t.tool_action(ToolAction.GRIPPER_OPEN)
    assert fb.tool_state.di_confirmed, "张开应在 DI2 置位时确认到位"
    # 闭合: 仅置 DI1(0b01) 应确认到位
    t._feedback.frame = DobotFeedbackFrame(
        robot_mode=RobotMode.ENABLED_IDLE, current_command_id=123, digital_inputs=0b01,
        digital_outputs=0, pose=(0.0,) * 6, joint=(0.0,) * 6, error_status=False,
        collision_state=False, enable_status=True, auto_manual_mode=0, safety_state=0,
    )
    fb = t.tool_action(ToolAction.GRIPPER_CLOSE)
    assert fb.tool_state.di_confirmed, "闭合应在 DI1 置位时确认到位"


def test_tool_state_persistence_roundtrip(tmp_path=None) -> None:
    # set_mounted_tool 落盘即权威真源; 新实例启动直接读盘恢复 (权威自动应用)
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "robot_tool_state.json"
        t = DobotTcpRobotTransport("127.0.0.1", tool_state_path=path)
        t._dashboard = _FakeDash()
        t._feedback = _FakeFb()
        t.set_mounted_tool(MountedTool.SLOT2)
        assert path.exists(), "声明工具应落盘"
        t2 = DobotTcpRobotTransport("127.0.0.1", tool_state_path=path)
        assert t2.mounted_tool == MountedTool.SLOT2, "启动应读盘权威恢复持久值"


# ── 2026-08-16 奇异点断连事故的回归用例 ──────────────────────────────────

class _AlarmDash(_FakeDash):
    """报警态 fake: GetPose/GetAngle 按 ErrorID 显式拒绝, GetErrorID 回报警码."""

    def command(self, cmd: str) -> DashboardReply:
        self.sent.append(cmd)
        if cmd.startswith(("GetPose", "GetAngle")):
            return DashboardReply(-1, (), cmd)
        if cmd.startswith("GetErrorID"):
            return DashboardReply(0, (114.0,), cmd)
        if cmd.startswith("RobotMode"):
            return DashboardReply(0, (9.0,), cmd)
        return DashboardReply(0, (), cmd)


def test_报警态query回退帧值_不抛不断连() -> None:
    """奇异点报警时 GetPose 被拒 -> query 回退 30004 帧值, 遥测继续流动, 通道不关."""
    t = _make()
    t._dashboard = _AlarmDash()
    t._feedback.frame = _frame(RobotMode.ERROR, 123)
    feedback = t.query()
    assert feedback.robot_mode == RobotMode.ERROR
    assert feedback.pose == (0.0,) * 6, "查询被拒时位姿应回退帧值"
    assert feedback.error_ids == (114,), feedback.error_ids
    assert "dashboard_query_refused" in feedback.details, feedback.details
    assert t._dashboard is not None and t._feedback is not None, "显式拒绝不许关通道"


def test_jog后守卫缓存失效() -> None:
    """MoveJog 绕开队列记账 (旧固件下还会推进机器人侧 id), 发出后期望值必须作废."""
    t = _make()
    t._last_dispatched_command_id = 777
    t.jog_start("Y+", MotionOptions(user=0, tool=1))
    assert t._last_dispatched_command_id is None, "jog_start 后守卫缓存应清空"
    t._last_dispatched_command_id = 777
    t.jog_stop()
    assert t._last_dispatched_command_id is None, "jog_stop 后守卫缓存应清空"


def test_强制接管重连_清守卫后放行() -> None:
    """CurrentCommandId 守卫: 未确认拦截如旧, reset_takeover_guard 是唯一放行通道."""
    t = _make()
    t._last_frame = _frame(RobotMode.ENABLED_IDLE, 5)
    t._last_dispatched_command_id = 5
    drifted = _frame(RobotMode.ENABLED_IDLE, 123)
    try:
        t._reconcile_after_connect(drifted)
        assert False, "id 漂移且未确认时必须拒绝接管"
    except RobotTransportError as exc:
        assert "CurrentCommandId 已变化" in str(exc), exc
    t.reset_takeover_guard()
    t._reconcile_after_connect(drifted)          # 人工确认后放行, 不抛
    assert t._last_frame is drifted


def test_链路级异常关通道时留痕() -> None:
    """断连的唯一触发点必须打 warning —— 此前全静默, 现场只看到断联查不到原因."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    driver_log = logging.getLogger("eit_ptlc.driver.dobot_tcp_driver")
    driver_log.addHandler(handler)
    try:
        class _DeadDash(_FakeDash):
            def command(self, cmd: str) -> DashboardReply:
                raise OSError("broken pipe")

        t = _make()
        t._dashboard = _DeadDash()
        try:
            t.jog_stop()
            assert False, "链路级异常应上抛"
        except OSError:
            pass
        assert t._dashboard is None and t._feedback is None, "链路级异常必须关闭两条通道"
        assert any("链路级异常" in record.getMessage() for record in records), \
            [record.getMessage() for record in records]
    finally:
        driver_log.removeHandler(handler)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n共 {len(tests)} 用例, 失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
