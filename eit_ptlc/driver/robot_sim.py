"""机器人仿真传输
================
功能:
    实现 RobotTransport 接口的内存仿真, 不连真机/网络. 供离线开发 / API 联调 / 演示.
    move/step 更新内部位姿与关节, jog 记录起停, query 返回当前状态.
    与 mock/plc_server (PLC 仿真) 对称, 是常驻仿真件而非测试桩.

插值模式 (仿真沙盒专用, 2026-08-09):
    构造传 interpolate=True 时, move_j/move_l/step **阻塞**地按名义速度匀速积分,
    每 50ms 经姿态观察者播一帧 (20Hz, 前端 RobotPoseBuffer 的插值窗口因此可用),
    真实等待按 clock.rate 缩放。缺省 False = 历史即时完成语义, 主 sim 栈/既有测试
    行为零变化。

    关节缺失的坑 (用户实测抓到): RobotController 对派生点 (架位/趋近位) 恒传
    joint=None, 旧实现只更新 pose 不动 joint —— robot_pose 帧的关节数组逐帧恒等,
    前端机械臂被钉死。插值模式下这类目标经注入的 ik_solver 现解 (种子=当前关节);
    IK 不可用则关节保持并一次性告警 (宁缺毋假, 不编姿态)。
"""

from __future__ import annotations

import logging
import math
import time

from eit_ptlc.driver.robot_transport import (
    STEP_CARTESIAN_AXES,
    STEP_JOINT_AXES,
    MotionOptions,
    RobotFeedback,
    RobotTransport,
    ToolAction,
    ToolState,
)

log = logging.getLogger(__name__)

# Dobot RobotMode.ENABLED_IDLE
_ENABLED_IDLE = 5

# 插值模式的名义速度 (演示节拍, 非动力学): 时长 = 跨度 / (名义速度 × speed_factor/100)
_NOMINAL_JOINT_DEG_S = 90.0     # 关节空间 (CR5 量级)
_NOMINAL_LINEAR_MM_S = 350.0    # 笛卡尔直线
_MOTION_TICK_S = 0.05           # 帧节奏 (20Hz)


class SimRobotTransport(RobotTransport):
    """内存机器人仿真; 维护位姿/关节, 动作即时完成."""

    def __init__(self, *, pose: tuple[float, ...] | None = None,
                 joint: tuple[float, ...] | None = None,
                 interpolate: bool = False, clock=None, ik_solver=None) -> None:
        """参数:
            pose/joint: 起始位姿与关节
            interpolate: True = 阻塞插值运动 (仿真沙盒); False = 历史即时完成语义
            clock: 时间倍率源 (直读 .rate 属性, 传 SimClock 实例; None = 1×)
            ik_solver: (pose6, seed_joint6, tool:int) -> joint6 | None; 关节缺失的
                目标用它现解, 失败/缺席则关节保持
        """
        self._pose = list(pose or (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        self._joint = list(joint or (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        self._connected = False
        self._jogging: str | None = None
        self.speed_factor = 20
        # 内存 DO 输出位图 (通道号 1..16 -> bit), 供裸 DO 直控的离线回显
        self._do_bits = 0
        # 姿态观察者: 契约对齐 DobotTcpRobotTransport.set_feedback_observer —— bootstrap 的
        # hasattr 分支据此在 sim/沙盒里点亮 robot_pose 事件 (此前 sim 下机器人只有 1Hz telemetry)。
        self._observer = None
        self._interpolate = bool(interpolate)
        self._clock = clock
        self._ik_solver = ik_solver
        self._motion_break = False      # stop()/急停置位, 插值循环检查后停在当前位
        self._ik_warned = False
        self.calls: list[tuple] = []

    def set_feedback_observer(self, observer, *, replay_latest: bool = False) -> None:
        """注册姿态帧观察者 ((RobotFeedback) -> None); replay_latest 立即补发当前帧."""
        self._observer = observer
        if observer is not None and replay_latest:
            self._notify()

    def _notify(self) -> None:
        if self._observer is None:
            return
        try:
            self._observer(self._fb(0))
        except Exception:                      # 观察者异常不反噬运动路径
            log.debug("[SimRobot] 姿态观察者回调异常", exc_info=True)

    def set_state(self, *, pose=None, joint=None) -> None:
        """仿真专用: 直写当前位姿/关节 (仿真沙盒"设定设备状态"入口), 并播一帧."""
        if pose is not None:
            self._pose = [float(v) for v in pose]
        if joint is not None:
            self._joint = [float(v) for v in joint]
        self.calls.append(("set_state", tuple(self._pose), tuple(self._joint)))
        self._notify()

    def _resolve_target_joint(self, target_pose, joint):
        """目标关节: 显式传入优先; 缺失时经注入的 IK 现解 (种子=当前关节); 都没有 → None."""
        if joint is not None:
            return [float(v) for v in joint]
        if self._ik_solver is None:
            if not self._ik_warned:
                self._ik_warned = True
                log.warning("[SimRobot] 目标点无关节角且未注入 IK, 该类段臂姿保持 (宁缺毋假)")
            return None
        try:
            solved = self._ik_solver(tuple(target_pose), tuple(self._joint),
                                     int(self.mounted_tool))
        except Exception:
            solved = None
        if solved is None and not self._ik_warned:
            self._ik_warned = True
            log.warning("[SimRobot] IK 求解失败, 无关节角的段臂姿保持 (宁缺毋假)")
        return [float(v) for v in solved] if solved is not None else None

    def _run_motion(self, pose, joint) -> None:
        """插值模式的运动核: 阻塞地匀速走到目标, 20Hz 播帧, 中断即停在当前位.

        时长 = max(关节跨度/关节名义速度, 直线距离/直线名义速度) / (speed_factor/100),
        真实等待再按 clock.rate 缩 —— 名义速度是演示节拍, 不是动力学声明。
        """
        target_pose = [float(v) for v in pose]
        if not self._interpolate:
            # 即时模式 = 历史语义逐字保持: 不做 IK、不告警, joint 缺失就不动关节
            self._pose = target_pose
            if joint is not None:
                self._joint = [float(v) for v in joint]
            self._notify()
            return
        target_joint = self._resolve_target_joint(target_pose, joint)
        start_pose = list(self._pose)
        start_joint = list(self._joint)
        factor = max(float(self.speed_factor) or 20.0, 1.0) / 100.0
        joint_span = (max(abs(t - s) for t, s in zip(target_joint, start_joint))
                      if target_joint is not None else 0.0)
        linear_span = math.dist(target_pose[:3], start_pose[:3])
        duration = max(joint_span / (_NOMINAL_JOINT_DEG_S * factor),
                       linear_span / (_NOMINAL_LINEAR_MM_S * factor))
        if duration <= _MOTION_TICK_S:
            self._pose = target_pose
            if target_joint is not None:
                self._joint = target_joint
            self._notify()
            return
        self._motion_break = False
        steps = max(int(math.ceil(duration / _MOTION_TICK_S)), 1)
        for i in range(1, steps + 1):
            if self._motion_break:
                return                        # 软停: 冻结在当前插值位 (与真机 stop 同义)
            rate = float(getattr(self._clock, "rate", 1.0) or 1.0)
            time.sleep(_MOTION_TICK_S / max(rate, 1e-6))
            fraction = i / steps
            self._pose = [s + (t - s) * fraction for s, t in zip(start_pose, target_pose)]
            if target_joint is not None:
                self._joint = [s + (t - s) * fraction
                               for s, t in zip(start_joint, target_joint)]
            self._notify()

    def connect(self) -> None:
        self._connected = True
        self.calls.append(("connect",))

    def close(self) -> None:
        self._connected = False
        self.calls.append(("close",))

    def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        self.calls.append(("query",))
        return self._fb(24)

    def move_j(self, pose, options: MotionOptions = MotionOptions(), *, joint=None) -> RobotFeedback:
        self.calls.append(("move_j", tuple(float(v) for v in pose)))
        self._run_motion(pose, joint)
        return self._fb(25)

    def move_l(self, pose, options: MotionOptions = MotionOptions(), *, joint=None) -> RobotFeedback:
        # 直线运动按位姿执行; 控制器对示教点传标定关节角, 对派生点传 None —— None 时
        # 插值模式经 ik_solver 现解, 即时模式保持关节 (历史语义)
        self.calls.append(("move_l", tuple(float(v) for v in pose)))
        self._run_motion(pose, joint)
        return self._fb(27)

    def tool_action(self, action: ToolAction, timeout_ms: int = 3000) -> RobotFeedback:
        self.calls.append(("tool_action", int(action)))
        return self._fb(28)

    def set_do(self, channel: int, enabled: bool) -> RobotFeedback:
        # 仿真: 维护内存 DO 位图 (与真机一致只接受白名单 {1,2,3,6}), 即时回显
        channel = int(channel)
        if channel not in {1, 2, 3, 6}:
            raise PermissionError(f"DO{channel} 不在白名单")
        mask = 1 << (channel - 1)
        if enabled:
            self._do_bits |= mask
        else:
            self._do_bits &= ~mask
        self.calls.append(("set_do", channel, bool(enabled)))
        return self._fb(28)

    def set_output(self, channel: int, enabled: bool) -> None:
        # 裸 DO 直控 (如 PALLAS 补光触发口): 仿真仅记录, 不受工具白名单约束
        self.calls.append(("set_output", int(channel), bool(enabled)))

    def jog_start(self, axis_id: str, options: MotionOptions = MotionOptions()) -> None:
        self._jogging = axis_id
        self.calls.append(("jog_start", axis_id))

    def jog_stop(self) -> None:
        self._jogging = None
        self.calls.append(("jog_stop",))

    def set_speed_factor(self, ratio: int | None = None) -> None:
        if ratio is not None:
            self.speed_factor = int(ratio)
        self.calls.append(("set_speed_factor", self.speed_factor))

    def step(self, axis, distance, options: MotionOptions = MotionOptions(), *, motion: str = "l") -> RobotFeedback:
        # 仿真: 笛卡尔轴更新对应位姿分量, 关节轴更新对应关节角
        self.calls.append(("step", axis, float(distance), motion))
        target_pose = list(self._pose)
        target_joint = None
        if axis in STEP_CARTESIAN_AXES:
            target_pose[STEP_CARTESIAN_AXES.index(axis)] += float(distance)
        elif axis in STEP_JOINT_AXES:
            target_joint = list(self._joint)
            target_joint[STEP_JOINT_AXES.index(axis)] += float(distance)
        self._run_motion(target_pose, target_joint)
        return self._fb(29)

    def stop(self) -> None:
        # 即时模式无在飞运动; 插值模式置中断位, 运动线程停在当前插值位
        self._jogging = None
        self._motion_break = True
        self.calls.append(("stop",))

    def pause(self) -> None:
        self.calls.append(("pause",))

    def resume(self) -> None:
        self.calls.append(("resume",))

    def emergency_stop(self, pressed: bool = True) -> None:
        self._jogging = None
        if pressed:
            self._motion_break = True
        self.calls.append(("emergency_stop", pressed))

    def clear_error(self, *, confirm: bool = False) -> RobotFeedback:
        self.calls.append(("clear_error", confirm))
        return self._fb(0)

    def enable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        self.calls.append(("enable_robot", confirm))
        return self._fb(0)

    def disable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        self.calls.append(("disable_robot", confirm))
        return self._fb(0)

    def _fb(self, last_action: int) -> RobotFeedback:
        return RobotFeedback(
            pose=tuple(self._pose),
            joint=tuple(self._joint),
            check_result=0,
            last_action=last_action,
            tool_state=ToolState(commanded_bits=0, actual_bits=0, di_bits=0, di_available=False,
                                 di_confirmed=False, do_bits=self._do_bits & 0xFFFF,
                                 mounted_tool=int(self.mounted_tool)),
            robot_mode=_ENABLED_IDLE,
            connected=True,
        )
