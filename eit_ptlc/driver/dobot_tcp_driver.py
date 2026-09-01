"""Dobot TCP-IP-V4 驱动 (机械臂直连)
=====================================
功能:
    Dobot 越疆机器人 29999 指令口 + 30004 反馈口的安全适配传输层.
    复用官方 1440 字节反馈布局与指令格式, 用有界 socket / 流式组帧 / 显式重连确认
    规避官方示例的无限重连与单次 recv 假设.
    迁移自 UI-Upper/core/dobot_tcp_transport.py, 新增点动 (MoveJog) / 步进
    (RelMovLUser / RelMovJUser / RelJointMovJ) 三种运动模式.

模式:
    点动 jog: jog_start(axis_id) 起 / jog_stop() 停 (连续, 不等完成)
    步进 step: 单轴增量, 笛卡尔走 RelMovLUser/RelMovJUser, 关节走 RelJointMovJ
    到点 move: move_j (MovJ, 关节) / move_l (MovL, 直线)
    中止: stop (Stop) / pause (Pause) / resume (Continue) / emergency_stop (EmergencyStop),
          绕过 action 锁, 运动中可调用; 在飞运动以 RobotMotionInterrupted 结束
"""

from __future__ import annotations

import json
import logging
import re
import select
import socket
import struct
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from eit_ptlc.driver.robot_transport import (
    JOG_AXES,
    STEP_CARTESIAN_AXES,
    STEP_JOINT_AXES,
    TOOL_AGNOSTIC_ACTIONS,
    TOOL_ALLOWED_ACTIONS,
    MotionOptions,
    MountedTool,
    RobotActionError,
    RobotFeedback,
    RobotMotionInterrupted,
    RobotTransport,
    RobotTransportError,
    ToolAction,
    ToolState,
)

log = logging.getLogger(__name__)

FEEDBACK_SIZE = 1440
FEEDBACK_MAGIC = 0x0123456789ABCDEF
# 翻面气缸切位互锁: 清反向 DO 与给正向 DO 之间的停顿, 避免双向同时给气 (沿用旧 lua Wait(200))
_ROTARY_INTERLOCK_S = 0.2


@dataclass(frozen=True)
class ToolConfirm:
    """单个双气工具动作 (gripper/rotary) 作动后的到位确认策略 (driver 侧消费结构).

    由配置层 (RobotCfg.tool_confirm) 经装配转换注入; driver 不反向依赖 config, 故在此另立最小结构.
        mode: "di" 等 DI 到位 (旧行为) | "dwell" 不等 DI 改固定停顿 settle | "di_or_dwell" 先等 DI 超时回退 dwell.
        dwell_ms: dwell / di_or_dwell 回退时的固定到位停顿 (毫秒); <=0 不停顿.
    """
    mode: str
    dwell_ms: int = 0


class RobotMode:
    INIT = 1
    BRAKE_OPEN = 2
    POWEROFF = 3
    DISABLED = 4
    ENABLED_IDLE = 5
    BACKDRIVE = 6
    RUNNING = 7
    SINGLE_MOVE = 8
    ERROR = 9
    PAUSE = 10
    COLLISION = 11


@dataclass(frozen=True)
class DashboardReply:
    error_id: int
    values: tuple[float, ...]
    raw: str


@dataclass(frozen=True)
class DobotFeedbackFrame:
    robot_mode: int
    current_command_id: int
    digital_inputs: int
    digital_outputs: int
    pose: tuple[float, ...]
    joint: tuple[float, ...]
    error_status: bool
    collision_state: bool
    enable_status: bool
    auto_manual_mode: int
    safety_state: int


def parse_dashboard_reply(raw: str) -> DashboardReply:
    """解析 ErrorID,{values},Command(...); 不从回显命令误抓数字."""
    match = re.match(r"^\s*(-?\d+)\s*,\s*\{([^}]*)\}", raw.strip())
    if not match:
        # 机器人对异常状况回的是纯文本提示 (无标准 ErrorID,{...} 结构), 给出面向现场的清晰原因
        if "Not Tcp" in raw:
            raise RobotTransportError("机器人不在 TCP 控制模式 (请在 DobotStudio 切回在线/TCP 模式)")
        if "occupied" in raw or "refused" in raw:
            raise RobotTransportError("机器人 29999 已被其它客户端占用 (Dobot 单客户端; 请关闭 DobotStudio 或清理残留后端进程)")
        raise RobotTransportError(f"无法解析 29999 响应: {raw!r}")
    values = tuple(float(item.strip()) for item in match.group(2).split(",") if item.strip())
    return DashboardReply(int(match.group(1)), values, raw.strip())


def parse_feedback_packet(data: bytes) -> DobotFeedbackFrame:
    """按官方 V4 MyType 小端布局解析一个完整反馈包."""
    if len(data) != FEEDBACK_SIZE:
        raise RobotTransportError(f"30004 反馈长度错误: {len(data)} != {FEEDBACK_SIZE}")
    length = struct.unpack_from("<H", data, 0)[0]
    magic = struct.unpack_from("<Q", data, 48)[0]
    if length != FEEDBACK_SIZE or magic != FEEDBACK_MAGIC:
        raise RobotTransportError(f"30004 反馈包头错误: len={length}, test=0x{magic:x}")
    return DobotFeedbackFrame(
        robot_mode=int(struct.unpack_from("<Q", data, 24)[0]),
        current_command_id=int(struct.unpack_from("<Q", data, 1112)[0]),
        digital_inputs=int(struct.unpack_from("<Q", data, 8)[0]),
        digital_outputs=int(struct.unpack_from("<Q", data, 16)[0]),
        pose=tuple(float(x) for x in struct.unpack_from("<6d", data, 624)),
        joint=tuple(float(x) for x in struct.unpack_from("<6d", data, 432)),
        error_status=bool(data[1029]),
        collision_state=bool(data[1038]),
        enable_status=bool(data[1026]),
        auto_manual_mode=int(struct.unpack_from("<H", data, 1416)[0]),
        safety_state=int(data[1420]),
    )


class _DashboardChannel:
    def __init__(self, sock: socket.socket) -> None:
        self._socket = sock
        self._buffer = bytearray()

    def close(self) -> None:
        self._socket.close()

    def command(self, command: str) -> DashboardReply:
        self._socket.sendall(command.encode("utf-8"))
        while b";" not in self._buffer:
            # 机器人对"非 TCP 模式 / 端口被占"等异常状况回的是无 ';' 终止符的纯文本提示
            # (如 "Control Mode Is Not Tcp\t" / "Connection refused, IP:Port has been occupied").
            # 正常应答必以数字 ErrorID 开头; 一旦收到非数字开头且无 ';' 的数据, 立即交解析器
            # 抛出清晰错误, 不再死等到 command_timeout (否则每条这类响应都白白卡满超时窗口).
            head = self._buffer.lstrip()
            if head and head[:1] not in b"-0123456789":
                raw = bytes(self._buffer).decode("utf-8", errors="replace")
                self._buffer.clear()
                return parse_dashboard_reply(raw)
            chunk = self._socket.recv(4096)
            if not chunk:
                raise RobotTransportError("机器人关闭 29999 连接")
            self._buffer.extend(chunk)
        marker = self._buffer.index(ord(";")) + 1
        raw = bytes(self._buffer[:marker]).decode("utf-8", errors="replace")
        del self._buffer[:marker]
        return parse_dashboard_reply(raw)


class _FeedbackChannel:
    def __init__(self, sock: socket.socket) -> None:
        self._socket = sock
        self._buffer = bytearray()

    def close(self) -> None:
        self._socket.close()

    def read_frame(self) -> DobotFeedbackFrame:
        # TCP 是字节流; 允许粘包/半包, 通过官方 len/TestValue 重新对齐.
        # 安全门必须基于"当前"状态: 30004 ~125Hz, 一次 recv 可含数十帧, 若返回最旧帧,
        # 状态机会拿到陈旧快照 (历史碰撞/报警被反复重放, 表现为清警后仍立即复现). 故每次
        # 排空 socket 里已到达的全部数据, 仅返回缓冲区中最新的一个对齐帧, 丢弃更早历史帧.
        # 持续噪声时用 while 循环 (而非递归) 重试, 避免 Python 无尾调用优化导致栈无限增长.
        while True:
            # 1) 阻塞读到至少一帧 (本轮 forward progress 由此保证: 至少消费 FEEDBACK_SIZE 新字节)
            while len(self._buffer) < FEEDBACK_SIZE:
                chunk = self._socket.recv(65536)
                if not chunk:
                    raise RobotTransportError("机器人关闭 30004 连接")
                self._buffer.extend(chunk)
            # 2) 非阻塞排空: 把 socket 里已到达的后续帧全部追进缓冲 (select 0 超时探测可读)
            while select.select((self._socket,), (), (), 0)[0]:
                chunk = self._socket.recv(65536)
                if not chunk:
                    raise RobotTransportError("机器人关闭 30004 连接")
                self._buffer.extend(chunk)
            # 3) 逐帧解析并丢弃, 只保留最后一个对齐帧; 错位字节逐字节重同步, 半包留待下次
            frame: DobotFeedbackFrame | None = None
            while len(self._buffer) >= FEEDBACK_SIZE:
                candidate = bytes(self._buffer[:FEEDBACK_SIZE])
                try:
                    frame = parse_feedback_packet(candidate)
                except RobotTransportError:
                    del self._buffer[0]
                    continue
                del self._buffer[:FEEDBACK_SIZE]
            if frame is None:
                # 排空所得全是错位字节 (已逐字节丢弃), 回到顶部再阻塞取一帧
                continue
            return frame


class DobotTcpRobotTransport(RobotTransport):
    """串行单控制者的 Dobot 29999 + 30004 传输."""

    _TOOL_BITS = {
        ToolAction.QUICK_CHANGE_LOCK: (1, False),    # DO1=0=锁紧快换
        ToolAction.QUICK_CHANGE_RELEASE: (1, True),  # DO1=1=松开快换
        ToolAction.SUCTION_ON: (3, True),
        ToolAction.SUCTION_OFF: (3, False),
    }
    _QUICK_CHANGE_ACTIONS = {ToolAction.QUICK_CHANGE_LOCK, ToolAction.QUICK_CHANGE_RELEASE}
    # 四个双气工具动作的"到位 DI"判据 (现场接线确认): gripper 张开=DI2/闭合=DI1; rotary 上翻=DI1/下翻=DI2
    # (rotary 与 gripper 的 DI 映射相反 = 两套语义). 是否真等该 DI 由按动作确认策略 tool_confirm 决定.
    _TOOL_DI_TARGET = {
        ToolAction.GRIPPER_OPEN: (2, True),
        ToolAction.GRIPPER_CLOSE: (1, True),
        ToolAction.ROTARY_UP: (1, True),
        ToolAction.ROTARY_DOWN: (2, True),
    }

    def __init__(
        self,
        host: str,
        *,
        command_port: int = 29999,
        feedback_port: int = 30004,
        error_http_port: int = 22000,
        connect_timeout: float = 3.0,
        command_timeout: float = 5.0,
        action_timeout: float = 300.0,
        poll_interval: float = 0.05,
        allow_enable_command: bool = False,
        allow_clear_error_command: bool = False,
        tool_di_feedback_enabled: bool = False,
        tool_di_timeout: float = 10.0,
        tool_confirm: Mapping[ToolAction, ToolConfirm] | None = None,
        speed_factor: int = 20,
        tool_state_path: str | Path | None = None,
        socket_factory: Callable[..., socket.socket] = socket.create_connection,
        sleep_fn: Callable[[float], None] = time.sleep,
        feedback_observer: Callable[[DobotFeedbackFrame], None] | None = None,
    ) -> None:
        if not 1 <= int(speed_factor) <= 100:
            raise ValueError("speed_factor 必须在 1..100")
        self.host = host
        self.command_port = command_port
        self.feedback_port = feedback_port
        self.error_http_port = error_http_port
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.action_timeout = action_timeout
        self.poll_interval = poll_interval
        self.allow_enable_command = allow_enable_command
        self.allow_clear_error_command = allow_clear_error_command
        self.tool_di_feedback_enabled = tool_di_feedback_enabled
        # DI 到位确认等待上限(秒): 翻面/夹爪等物理到位由 DI1/DI2 判定, 与每流程 timeout_ms 解耦
        self.tool_di_timeout = float(tool_di_timeout)
        # 按动作到位确认 (gripper/rotary 四个双气动作各自 di/dwell/di_or_dwell + dwell_ms);
        # None (段缺失/未注入) 回退全局 tool_di_feedback_enabled 旧行为 (向后兼容, 见 _confirm_tool_action)
        self._tool_confirm: dict[ToolAction, ToolConfirm] | None = (
            dict(tool_confirm) if tool_confirm else None
        )
        # 双气动作的**实测行程耗时**(秒), 按动作分向缓存: 写完 DO 到 DI 置位之间的墙上时间。
        # 用途只有一个 —— 供数字孪生按真实速度配速(见 robot_controller._announce_twin_motion)。
        # 只在 DI 真到位时记录: dwell 兜底那一路没有到位证据, 记下来就是把超时当行程。
        # 上翻/下翻各存一份: 重力方向不同, 两程本来就不等速。
        self._tool_stroke_s: dict[ToolAction, float] = {}
        self.speed_factor = int(speed_factor)
        self._socket_factory = socket_factory
        self._sleep = sleep_fn
        # 只读旁路：把本来就由 30004 读到的帧交给数字孪生事件层；不创建第二读者，
        # 不新增查询/运动命令，也不允许观察者异常影响机器人控制。
        self._feedback_observer = feedback_observer
        self._dashboard: _DashboardChannel | None = None
        self._feedback: _FeedbackChannel | None = None
        self._action_lock = threading.Lock()
        # 命令口 (29999) 收发锁: 与 _action_lock 解耦, 让中止类命令在运动中也能抢发命令口
        self._dashboard_lock = threading.Lock()
        # 30004 唯一读者：后台泵持续收帧，所有命令等待/DI/查询只等条件变量里的新帧。
        # 这既保证连续 jog 期间仍有姿态，也从结构上禁止多个线程并发 recv 同一 socket。
        self._feedback_condition = threading.Condition()
        self._feedback_stop = threading.Event()
        self._feedback_thread: threading.Thread | None = None
        self._feedback_generation = 0
        self._feedback_error: BaseException | None = None
        # 中止信号: stop/emergency_stop 置位, 在飞的 _wait_command 检测到即以中止结束
        self._stop_event = threading.Event()
        self._last_frame: DobotFeedbackFrame | None = None
        self._last_dispatched_command_id: int | None = None
        self._clean_close = True
        self._tool_commanded_bits = 0
        # 权威工具态四态真源 (无/吸盘/大夹爪/小夹爪): 持久化到 tool_state_path,
        # 启动直接读盘恢复当前挂载 (文件缺失/损坏 -> NONE 裸腕); 不再人工重新声明.
        self._tool_state_path = Path(tool_state_path) if tool_state_path else None
        self._mounted_tool = self._load_tool()

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------

    def connect(self) -> None:
        with self._action_lock:
            if self._dashboard is not None or self._feedback is not None:
                raise RobotTransportError("机器人 transport 已连接")
            try:
                command_socket = self._socket_factory((self.host, self.command_port), self.connect_timeout)
                feedback_socket = self._socket_factory((self.host, self.feedback_port), self.connect_timeout)
                command_socket.settimeout(self.command_timeout)
                feedback_socket.settimeout(self.command_timeout)
                self._dashboard = _DashboardChannel(command_socket)
                self._feedback = _FeedbackChannel(feedback_socket)
                self._start_feedback_pump()
                frame = self._read_frame()
                self._reconcile_after_connect(frame)
                self._apply_speed_factor()
                self._clean_close = False
            except BaseException:
                self._close_channels()
                raise

    def close(self) -> None:
        with self._action_lock:
            self._clean_close = True
            self._close_channels()

    def reset_takeover_guard(self) -> None:
        """人工确认后清除 CurrentCommandId 接管守卫的比对基准 (见基类 docstring).

        只清 _last_dispatched_command_id: _reconcile_after_connect 的守卫条件是
        "缓存非 None 且与机器人现值不等", 清掉即放行下一次 connect。_last_frame
        保留 —— 它只是"连过"的证据, 不参与误报。
        """
        with self._action_lock:
            self._last_dispatched_command_id = None

    def __enter__(self) -> "DobotTcpRobotTransport":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 全局速度比 (SpeedFactor)
    # ------------------------------------------------------------------

    def set_speed_factor(self, ratio: int | None = None) -> None:
        """下发全局速度比 SpeedFactor (1-100); ratio 为 None 时用构造时的 speed_factor.

        功能:
            SpeedFactor 是全局比例, 同时影响点动 (MoveJog 无独立速度参数) 与到点/步进
            (实际速度 = SpeedFactor% × 各命令 v%). 现场速度比过低时点动肉眼难辨, 故连接后下发.
            不占 action 锁: SpeedFactor 是全局实时倍率, 须能在到点运动 (整段持 action 锁)
            进行中抢发以即时调速; 命令口收发自有 _dashboard_lock 守护, 故无锁安全
            (同 Stop/Pause 的抢发语义)。
        参数:
            ratio: 速度比 (1-100); None 用 self.speed_factor
        """
        value = self.speed_factor if ratio is None else int(ratio)
        if not 1 <= value <= 100:
            raise ValueError("speed_factor 必须在 1..100")
        self.speed_factor = value
        self._send_speed_factor(value)

    def _apply_speed_factor(self) -> None:
        """连接后下发 SpeedFactor; 仅当机器人"有应答但拒绝"时跳过, 链路级失败照常上抛.

        设计意图:
            SpeedFactor 是锦上添花的初始化项. 机器人可能暂时报警/未使能/不在 TCP 模式而按 ErrorID
            拒绝这条命令 (RobotActionError) —— 此时链路仍可用, 后端应照常起服, 仅告警跳过,
            让 UI 的"使能/清警"按钮能在后端在线后去处理机器人.
            但"机器人关闭 29999"/socket 超时等链路级失败 (RobotTransportError 非 RobotActionError
            子类, 及 OSError) 意味着命令通道已死: 此连接不可用, 绝不可伪装成功. 故不吞, 交
            connect() 的兜底关通道并上抛, 让 connect 当场失败、报出真因 (而非连上后才在遥测掉线).
        """
        try:
            self._send_speed_factor(self.speed_factor)
        except RobotActionError as exc:
            log.warning("连接后设置 SpeedFactor(%d) 被机器人拒绝 (报警/未就绪/不在 TCP 模式), 已跳过: %s",
                        self.speed_factor, exc)

    def _send_speed_factor(self, value: int) -> None:
        self._raise_dashboard_error(self._command(f"SpeedFactor({value})"), "SpeedFactor")

    # ------------------------------------------------------------------
    # 查询 / 到点运动
    # ------------------------------------------------------------------

    def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        """读一次完整状态快照 (1Hz 遥测的唯一入口).

        报警态容错 (2026-08-16, 奇异点事故定案): 机器人报警/未就绪时会对
        GetPose()/GetAngle() 按 ErrorID 显式拒绝 —— 链路是健在的, 此时**回退用
        30004 帧值**继续出快照, 让遥测携带 error_ids 流动(健康度=ERROR, 报警码
        上墙), 而不是把 RobotActionError 抛给遥测层被判成 offline"断联"。
        链路级异常(socket/超时/解析)行为不变: 关通道并上抛。
        """
        with self._action_lock:
            self._require_connected()
            try:
                # 先读 30004 帧: 它是活性判据, 也是 dashboard 查询被拒时的回退值来源
                frame = self._read_frame()
                pose: tuple[float, ...] | None = None
                joint: tuple[float, ...] | None = None
                details: dict[str, object] = {}
                try:
                    mode = self._command_scalar("RobotMode()")
                    pose = self._command_vector(f"GetPose(user={options.user},tool={options.tool})", 6)
                    joint = self._command_vector("GetAngle()", 6)
                    # 29999 与 30004 非原子采样; 以更新的反馈帧为最终状态并保留差异
                    if mode != frame.robot_mode:
                        details["dashboard_robot_mode"] = mode
                except RobotActionError as exc:
                    # 显式拒绝 = 链路健在; 记下原因供状态页排障, 值全部回退帧值
                    details["dashboard_query_refused"] = str(exc)
                return self._feedback_from(frame, pose=pose, joint=joint, last_action=24, details=details)
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def move_j(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
        *,
        joint: Sequence[float] | None = None,
    ) -> RobotFeedback:
        if joint is None:
            raise ValueError("DobotTCP move_j 需要 joint 关节角; 请传 joint= 指定已标定关节角")
        return self._move("MovJ", joint, "joint", options)

    def move_l(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
        *,
        joint: Sequence[float] | None = None,
    ) -> RobotFeedback:
        # joint 仅供仿真追踪关节态; 真机直线运动按位姿执行, 实际关节由反馈读取, 故此处忽略
        return self._move("MovL", pose, "pose", options)

    # ------------------------------------------------------------------
    # 点动 jog (连续, 按住起 / 松开停)
    # ------------------------------------------------------------------

    def jog_start(self, axis_id: str, options: MotionOptions = MotionOptions()) -> None:
        """开始连续点动: MoveJog(axis_id). axis_id 取自 JOG_AXES (J1±..J6± / X±..Rz±).

        功能:
            发 MoveJog 进入连续点动, 不等完成 (持续运动直到 jog_stop 或限位).
        参数:
            axis_id: 点动轴 + 方向; options: 坐标系 (user/tool, coordtype=1 用户系)
        """
        if axis_id not in JOG_AXES:
            raise ValueError(f"非法点动轴: {axis_id!r} (合法值见 JOG_AXES)")
        with self._action_lock:
            self._assert_action_ready()
            try:
                cmd = f"MoveJog({axis_id},coordtype=1,user={options.user},tool={options.tool})"
                self._raise_dashboard_error(self._command(cmd), "MoveJog")
                # 点动绕开队列记账 (MoveJog 不返回 CommandId; 固件 <V4.6.0 时它本身还是
                # 队列指令、会推进机器人侧 CurrentCommandId), "期望的队列 id"从此不可知 ——
                # 留着旧值就是重连守卫的必然误报源 (2026-08-16 奇异点事故的死锁一环)
                self._last_dispatched_command_id = None
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def jog_stop(self) -> None:
        """停止点动: MoveJog() 空轴. 任何时刻可调用 (含运动中)."""
        with self._action_lock:
            self._require_connected()
            try:
                self._raise_dashboard_error(self._command("MoveJog()"), "MoveJog stop")
                # 同 jog_start: 空轴停止在旧固件下同样过队列, 期望 id 已不可知
                self._last_dispatched_command_id = None
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    # ------------------------------------------------------------------
    # 运动中止 / 暂停 / 急停 (绕过 action 锁, 运动中可抢发命令口)
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """中止当前运动队列 (Stop, 臂保持使能).

        功能:
            置中止信号并发 Stop(); 在飞的到点/步进运动经 _wait_command 以
            RobotMotionInterrupted 结束. 不占 action 锁, 故运动中可调用.
        """
        self._stop_event.set()
        try:
            self._raise_dashboard_error(self._command("Stop()"), "Stop")
        except BaseException:
            self._mark_uncertain_on_io_error()
            raise

    def pause(self) -> None:
        """暂停当前运动 (Pause). 不占 action 锁; 配合 resume 恢复."""
        try:
            self._raise_dashboard_error(self._command("Pause()"), "Pause")
        except BaseException:
            self._mark_uncertain_on_io_error()
            raise

    def resume(self) -> None:
        """恢复被暂停的运动 (Continue). 不占 action 锁."""
        try:
            self._raise_dashboard_error(self._command("Continue()"), "Continue")
        except BaseException:
            self._mark_uncertain_on_io_error()
            raise

    def emergency_stop(self, pressed: bool = True) -> None:
        """急停: EmergencyStop(1) 按下 (失能臂并报警) / EmergencyStop(0) 释放.

        功能:
            pressed=True 时置中止信号并按下急停, 在飞运动以 RobotMotionInterrupted 结束;
            释放后需 ClearError + EnableRobot 方可再次使能. 不占 action 锁.
        参数:
            pressed: True 按下急停, False 释放急停
        """
        if pressed:
            self._stop_event.set()
        try:
            self._raise_dashboard_error(
                self._command(f"EmergencyStop({1 if pressed else 0})"), "EmergencyStop")
        except BaseException:
            self._mark_uncertain_on_io_error()
            raise

    # ------------------------------------------------------------------
    # 步进 step (单轴增量)
    # ------------------------------------------------------------------

    def step(
        self,
        axis: str,
        distance: float,
        options: MotionOptions = MotionOptions(),
        *,
        motion: str = "l",
    ) -> RobotFeedback:
        """单轴步进 (增量移动), 等待运动完成后返回反馈.

        功能:
            笛卡尔轴 (X/Y/Z/Rx/Ry/Rz) 经 RelMovLUser (直线) 或 RelMovJUser (关节插补);
            关节轴 (J1..J6) 经 RelJointMovJ. 仅目标轴非零, 其余偏移为 0.
        参数:
            axis: 轴名; distance: 增量 (mm 或 deg, 含正负方向);
            options: 运动参数; motion: 笛卡尔插补方式 "l" 直线 / "j" 关节
        返回:
            RobotFeedback
        """
        self._validate_options(options)
        if axis in STEP_JOINT_AXES:
            offsets = [0.0] * 6
            offsets[STEP_JOINT_AXES.index(axis)] = float(distance)
            cmd = (
                f"RelJointMovJ({','.join(self._fmt(o) for o in offsets)},"
                f"a={options.acc},v={options.vel},cp={options.cp})"
            )
            last_action = 29
        elif axis in STEP_CARTESIAN_AXES:
            offsets = [0.0] * 6
            offsets[STEP_CARTESIAN_AXES.index(axis)] = float(distance)
            name = "RelMovLUser" if motion == "l" else "RelMovJUser"
            cmd = (
                f"{name}({','.join(self._fmt(o) for o in offsets)},"
                f"user={options.user},tool={options.tool},a={options.acc},v={options.vel},cp={options.cp})"
            )
            last_action = 27 if motion == "l" else 25
        else:
            raise ValueError(f"未知步进轴: {axis!r} (笛卡尔 {STEP_CARTESIAN_AXES} 或关节 {STEP_JOINT_AXES})")
        with self._action_lock:
            self._assert_action_ready()
            try:
                reply = self._command(cmd)
                self._raise_dashboard_error(reply, "step")
                command_id = self._reply_command_id(reply, "step")
                frame = self._wait_command(command_id, self.action_timeout)
                return self._feedback_from(frame, last_action=last_action)
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    # ------------------------------------------------------------------
    # 工具动作
    # ------------------------------------------------------------------

    def tool_action(self, action: ToolAction, timeout_ms: int = 3000) -> RobotFeedback:
        action = ToolAction(action)
        if not 100 <= timeout_ms <= 60000:
            raise ValueError("工具动作 timeout_ms 必须在 100..60000")
        self._assert_tool_allows(action)
        with self._action_lock:
            self._assert_action_ready()
            try:
                final_command_id: int | None = None
                if action in self._TOOL_BITS:
                    if action in self._QUICK_CHANGE_ACTIONS:
                        self._sleep(1.0)
                    channel, enabled = self._TOOL_BITS[action]
                    final_command_id = self._queue_do(channel, enabled)
                    self._set_tool_bit(channel, enabled)
                elif action == ToolAction.GRIPPER_OPEN:
                    self._queue_do(6, True)
                    final_command_id = self._queue_do(2, False)
                    self._set_tool_bit(2, False)
                elif action == ToolAction.GRIPPER_CLOSE:
                    self._queue_do(6, False)
                    final_command_id = self._queue_do(2, True)
                    self._set_tool_bit(2, True)
                elif action == ToolAction.TOOL_CHANGE_AUX_ON:
                    final_command_id = self._queue_do(6, True)
                elif action == ToolAction.TOOL_CHANGE_AUX_OFF:
                    # 卸刀 release 后排空两个手腕作动口: DO2(夹爪合气/翻上) + DO6(配合线/夹爪开/翻下),
                    # 防止裸腕残留气压持续喷气 (尤其卸夹爪后 DO2 合气未清); 末口 DO6 作 final 等命令完成
                    self._queue_do(2, False)
                    self._set_tool_bit(2, False)
                    final_command_id = self._queue_do(6, False)
                elif action == ToolAction.ROTARY_UP:
                    # 翻面气缸上翻: 先清反向位 DO6, 200ms 互锁(避免双向同时给气), 再给 DO2; 等 DI1 到位
                    # (旧 lua: DO(6,0);Wait(200);DO(2,1) 等 DI(1); 注意与 gripper 的 DI 映射相反 = 两套语义)
                    self._queue_do(6, False)
                    self._sleep(_ROTARY_INTERLOCK_S)
                    final_command_id = self._queue_do(2, True)
                    self._set_tool_bit(2, True)
                elif action == ToolAction.ROTARY_DOWN:
                    # 翻面气缸下翻: 先清反向位 DO2, 200ms 互锁, 再给 DO6; 等 DI2 到位
                    # (旧 lua: DO(2,0);Wait(200);DO(6,1) 等 DI(2))
                    self._queue_do(2, False)
                    self._sleep(_ROTARY_INTERLOCK_S)
                    final_command_id = self._queue_do(6, True)
                    self._set_tool_bit(2, False)
                elif action != ToolAction.GET_STATE:
                    raise PermissionError(f"工具动作不在语义白名单: {action}")

                if final_command_id is not None:
                    frame = self._wait_command(final_command_id, self.action_timeout)
                    if action in self._QUICK_CHANGE_ACTIONS:
                        self._sleep(1.0)
                else:
                    frame = self._read_frame()
                confirmed = False
                if action in self._TOOL_DI_TARGET:
                    # 按动作到位确认 (di/dwell/di_or_dwell); _wait_command(DO 写完成) 已作为地板先行执行
                    frame, confirmed = self._confirm_tool_action(action, frame)
                return self._feedback_from(frame, last_action=28, tool_confirmed=confirmed)
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    @staticmethod
    def tool_confirm_from_cfg(cfg: "object | None") -> "dict[ToolAction, ToolConfirm] | None":
        """把 RobotCfg.tool_confirm (或 None) 转成 per-action 注入映射; None-safe.

        cfg 缺失 (None) → 返回 None → driver 回退全局 tool_di_feedback_enabled 旧行为 (向后兼容).
        鸭子类型读取 cfg.<动作>.mode/.dwell_ms, 不反向 import config.
        """
        if cfg is None:
            return None
        return {
            ToolAction.GRIPPER_OPEN: ToolConfirm(cfg.gripper_open.mode, cfg.gripper_open.dwell_ms),
            ToolAction.GRIPPER_CLOSE: ToolConfirm(cfg.gripper_close.mode, cfg.gripper_close.dwell_ms),
            ToolAction.ROTARY_UP: ToolConfirm(cfg.rotary_up.mode, cfg.rotary_up.dwell_ms),
            ToolAction.ROTARY_DOWN: ToolConfirm(cfg.rotary_down.mode, cfg.rotary_down.dwell_ms),
        }

    def _confirm_tool_action(self, action: ToolAction,
                             frame: DobotFeedbackFrame) -> tuple[DobotFeedbackFrame, bool]:
        """双气工具动作 (gripper/rotary) 作动后的按动作到位确认 (替代单一全局 DI 开关).

        策略取自 self._tool_confirm[action].mode:
            di          -- 等 DI 到位 (与旧行为一致); 超时抛 TimeoutError 安全停机.
            dwell       -- 不等 DI, 改固定停顿 settle(dwell_ms): 夹持物件闭合限位 DI1 不稳 / rotary DI 未校验.
            di_or_dwell -- 先等 DI, 超时回退 settle (不抛错).
        _wait_command (DO 写完成) 已由调用方作为地板先行; 本法只在其上叠加确认.
        self._tool_confirm 为 None (段缺失/未注入) 时回退全局 tool_di_feedback_enabled 旧行为:
        开→等 DI, 关→弱确认(仅 DO 完成). 返回 (frame, confirmed); confirmed 仅 DI 真到位为 True (dwell 恒 False).
        """
        channel, level = self._TOOL_DI_TARGET[action]
        confirm = self._tool_confirm.get(action) if self._tool_confirm is not None else None
        if confirm is None:
            if self.tool_di_feedback_enabled:
                return self._wait_di_timed(action, channel, level), True
            return frame, False
        if confirm.mode == "di":
            return self._wait_di_timed(action, channel, level), True
        if confirm.mode == "dwell":
            self._settle(confirm.dwell_ms)
            return frame, False
        if confirm.mode == "di_or_dwell":
            try:
                return self._wait_di_timed(action, channel, level), True
            except TimeoutError:
                self._settle(confirm.dwell_ms)
                return frame, False
        raise ValueError(f"未知 tool_confirm.mode: {confirm.mode!r}")

    def _wait_di_timed(self, action: ToolAction, channel: int, enabled: bool) -> DobotFeedbackFrame:
        """等 DI 到位, 顺带把这一程的实测耗时记进 _tool_stroke_s.

        为什么值得记: 气缸行程时间既不在 PLC 里(这只缸挂在机器人工具 I/O 上, 不是 PLC 设备),
        也没有任何速度寄存器可读 —— 但"写完 DO"到"限位 DI 置位"之间的时间就是行程本身,
        这里是全仓唯一同时握有这两个时刻的地方。三维据此按真速配速, 现场换气压/换缸自动跟上。

        **两种情况都不是有效样本, 一律不记**:
          · 超时(异常直接向上抛): 那一程压根没到位, 记下来等于把 tool_di_timeout 当行程;
          · **DI 一开始就已经在目标电平**: 缸本来就停在该位, 这一程根本没走 —— 流程会把
            rotary 当状态确认重下(robot_suction_pick 同一次运行发两次 rotary-up), 那一次
            _wait_di 在第一帧就满足条件, 量到的是**一个反馈周期**(约 10ms)而不是行程。
            2026-08-05 实测症状: 这个 ~0.01s 被当成标定值下发, 前端 speed=span/0.01 一帧
            就走完全程 —— 用户看到的"上翻瞬移、下翻正常"正是它(下翻从不被复发, 所以标定
            一直是干净的 5s 量级)。判据取"第一帧就已到位", 与空翻抑制同源但各自独立。

        计时含 _read_frame 的轮询粒度(poll_interval=0.05s), 对 5s 量级的行程可以忽略。
        """
        # 先看一帧: DI 已在目标电平 = 这一程没有发生, 直接返回且**不写标定**
        probe = self._read_frame()
        self._raise_for_mode(probe)
        if self._io_bit(probe.digital_inputs, channel) == enabled:
            return probe
        started = time.monotonic()
        last = self._wait_di(channel, enabled, self.tool_di_timeout)
        self._tool_stroke_s[action] = time.monotonic() - started
        return last

    def last_tool_stroke_s(self, action: ToolAction) -> float | None:
        """该动作上一程的实测行程耗时(秒); 还没有到位过则 None(调用方回退标称值)。"""
        return self._tool_stroke_s.get(action)

    def _settle(self, dwell_ms: int) -> None:
        """工具动作驱动 DO 之后的固定到位停顿 (settle): 等气缸物理作动到位.

        与 _ROTARY_INTERLOCK_S (0.2s 双气切位互锁, 在驱动 DO"之前"清反向气) 语义不同:
        本停顿发生在驱动 DO"之后", 是作动到位的沉降等待. dwell_ms<=0 时不停顿.
        """
        if dwell_ms > 0:
            self._sleep(dwell_ms / 1000.0)

    def set_do(self, channel: int, enabled: bool) -> RobotFeedback:
        """裸 DO 直控: 直接置位单个数字输出口 (维护页纯 DO 栏).

        不走语义白名单 (quick-change/gripper/...), 仅受 _queue_do 的通道白名单 {1,2,3,6}
        与上层模式门控约束. 同步更新 commanded_bits 让语义按钮状态与裸口保持一致.
        """
        with self._action_lock:
            self._assert_action_ready()
            try:
                command_id = self._queue_do(int(channel), bool(enabled))
                self._set_tool_bit(int(channel), bool(enabled))
                # 裸 DO 为 DEBUG 维护手段; 若维护中物理换了刀, 维护后由操作员经 UI 重设权威工具态.
                frame = self._wait_command(command_id, self.action_timeout)
                return self._feedback_from(frame, last_action=28)
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    # ------------------------------------------------------------------
    # 视觉纠偏 IO (相机触发 DO + 读机器人自身 Modbus 保持寄存器的板位姿偏移)
    # ------------------------------------------------------------------

    def set_output(self, channel: int, enabled: bool) -> None:
        """裸 DO 直控任意通道 (供智能相机触发口如 DO7; 不受工具 DO 白名单约束).

        与 set_do 区别: set_do 受工具语义白名单 {1,2,3,6} 约束并更新工具 commanded_bits;
        本法专供视觉相机触发等非工具 IO, 不动工具态. 仍需等待 DO 命令完成, 避免下一条运动
        在 RobotMode=RUNNING 的短暂窗口内被拒绝.
        """
        with self._action_lock:
            self._require_connected()
            try:
                reply = self._command(f"DO({int(channel)},{int(bool(enabled))})")
                self._raise_dashboard_error(reply, f"DO{channel}")
                command_id = self._reply_command_id(reply, f"DO{channel}")
                self._wait_command(command_id, self.action_timeout)
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    # ------------------------------------------------------------------
    # 安全门控命令 (维护用; 配置 + confirm 双重确认)
    # ------------------------------------------------------------------

    def enable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        """显式使能; 配置允许和调用确认缺一不可."""
        if not self.allow_enable_command or not confirm:
            raise PermissionError("EnableRobot 未经配置允许或缺少显式 confirm")
        with self._action_lock:
            try:
                self._raise_dashboard_error(self._command("EnableRobot()"), "EnableRobot")
                return self._feedback_from(self._wait_mode(RobotMode.ENABLED_IDLE, 15.0))
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def disable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        """显式下使能 (DisableRobot, 干净失能臂); 复用 allow_enable_command 门控 + 显式 confirm.

        功能:
            发 DisableRobot() 去使能臂 (伺服下电, 无报警, 与 EmergencyStop 不同),
            等机器人进入 DISABLED. 下使能本身是去使能化, 天然安全, 但仍要求双重门控对称使能.
        """
        if not self.allow_enable_command or not confirm:
            raise PermissionError("DisableRobot 未经配置允许或缺少显式 confirm")
        with self._action_lock:
            try:
                self._raise_dashboard_error(self._command("DisableRobot()"), "DisableRobot")
                return self._feedback_from(self._wait_mode(RobotMode.DISABLED, 15.0))
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def clear_error(self, *, confirm: bool = False) -> RobotFeedback:
        """显式清警; 绝不在 connect 或动作失败时自动调用."""
        if not self.allow_clear_error_command or not confirm:
            raise PermissionError("ClearError 未经配置允许或缺少显式 confirm")
        with self._action_lock:
            try:
                self._raise_dashboard_error(self._command("ClearError()"), "ClearError")
                frame = self._read_frame()
                if frame.robot_mode in (RobotMode.ERROR, RobotMode.COLLISION) or frame.collision_state:
                    raise RobotActionError(9000 + frame.robot_mode, frame.robot_mode,
                                           "报警原因仍存在, ClearError 后机器人未恢复")
                return self._feedback_from(frame)
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _move(self, command_name: str, target: Sequence[float], coordinate: str,
              options: MotionOptions) -> RobotFeedback:
        values = self._six(target, coordinate)
        self._validate_options(options)
        with self._action_lock:
            self._assert_action_ready()
            command = (
                f"{command_name}({coordinate}={{{','.join(self._fmt(v) for v in values)}}},"
                f"user={options.user},tool={options.tool},a={options.acc},v={options.vel},cp={options.cp})"
            )
            try:
                reply = self._command(command)
                self._raise_dashboard_error(reply, command_name)
                command_id = self._reply_command_id(reply, command_name)
                frame = self._wait_command(command_id, self.action_timeout)
                return self._feedback_from(frame, last_action=25 if command_name == "MovJ" else 27)
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def _wait_command(self, command_id: int, timeout: float) -> DobotFeedbackFrame:
        self._last_dispatched_command_id = command_id
        deadline = time.monotonic() + timeout
        accept_deadline = time.monotonic() + min(timeout, self.command_timeout)
        accepted = False
        while time.monotonic() < deadline:
            # 外部中止 (Stop/EmergencyStop) 优先于完成判定, 以区分"被中止"与"正常完成"
            if self._stop_event.is_set():
                mode = self._last_frame.robot_mode if self._last_frame is not None else 0
                raise RobotMotionInterrupted(0, mode, "运动已被中止 (Stop/EmergencyStop)")
            frame = self._read_frame()
            self._raise_for_mode(frame)
            # 暂停期间不计入超时, 持续等待 Continue 恢复或 Stop 中止
            if frame.robot_mode == RobotMode.PAUSE:
                now = time.monotonic()
                deadline = max(deadline, now + timeout)
                accept_deadline = max(accept_deadline, now + min(timeout, self.command_timeout))
                time.sleep(self.poll_interval)
                continue
            if frame.current_command_id == command_id or frame.robot_mode in (
                RobotMode.RUNNING, RobotMode.SINGLE_MOVE,
            ):
                accepted = True
            if frame.current_command_id == command_id and frame.robot_mode == RobotMode.ENABLED_IDLE:
                return frame
            if (frame.robot_mode == RobotMode.ENABLED_IDLE
                    and frame.current_command_id != command_id and accepted):
                raise RobotTransportError(
                    "机器人已空闲但 CurrentCommandId 不匹配, 可能存在其他控制者: "
                    f"expected={command_id}, actual={frame.current_command_id}"
                )
            if not accepted and time.monotonic() >= accept_deadline:
                raise TimeoutError(f"机器人未在 {self.command_timeout}s 内接收命令 {command_id}")
            time.sleep(self.poll_interval)
        raise TimeoutError(f"等待机器人命令 {command_id} 完成超时")

    def _wait_di(self, channel: int, enabled: bool, timeout: float) -> DobotFeedbackFrame:
        deadline = time.monotonic() + timeout
        last = self._last_frame
        while time.monotonic() < deadline:
            last = self._read_frame()
            self._raise_for_mode(last)
            if self._io_bit(last.digital_inputs, channel) == enabled:
                return last
        raise TimeoutError(f"等待 DI{channel}={int(enabled)} 超时")

    def _wait_mode(self, mode: int, timeout: float) -> DobotFeedbackFrame:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self._read_frame()
            if frame.robot_mode == mode:
                return frame
            self._raise_for_mode(frame)
        raise TimeoutError(f"等待 RobotMode={mode} 超时")

    def _assert_action_ready(self) -> None:
        # 新动作开始即清陈旧中止信号, 避免上一轮的 stop 误伤本轮
        self._stop_event.clear()
        self._require_connected()
        frame = self._read_frame()
        self._raise_for_mode(frame)
        if frame.robot_mode != RobotMode.ENABLED_IDLE:
            raise RobotActionError(9000 + frame.robot_mode, frame.robot_mode,
                                   f"机器人不是使能空闲状态, RobotMode={frame.robot_mode}")

    def _reconcile_after_connect(self, frame: DobotFeedbackFrame) -> None:
        # 报警/碰撞允许建立只读连接 (便于 status/GetError 和负责人显式清警); 运动入口仍严格拒绝
        if frame.robot_mode in (RobotMode.RUNNING, RobotMode.SINGLE_MOVE, RobotMode.PAUSE):
            raise RobotTransportError(f"重连时机器人仍在运行/暂停, 拒绝取得控制权: RobotMode={frame.robot_mode}")
        if (self._last_frame is not None and self._last_dispatched_command_id is not None
                and frame.current_command_id != self._last_dispatched_command_id):
            raise RobotTransportError("重连后 CurrentCommandId 已变化, 可能存在其他控制者; 需人工确认")
        self._last_frame = frame

    def _raise_for_mode(self, frame: DobotFeedbackFrame) -> None:
        active_fault = frame.robot_mode in (RobotMode.ERROR, RobotMode.COLLISION)
        latched = frame.error_status or frame.collision_state
        if not (active_fault or latched):
            return
        ids = self._get_error_ids()
        is_collision = frame.robot_mode == RobotMode.COLLISION or frame.collision_state
        error_id = ids[0] if ids else 9000 + (RobotMode.COLLISION if is_collision else frame.robot_mode)
        if active_fault:
            # RobotMode 本身处于 报警(9)/碰撞(11) 活动故障态
            label = "碰撞" if frame.robot_mode == RobotMode.COLLISION else "报警"
            raise RobotActionError(error_id, frame.robot_mode,
                                   f"机器人{label}(活动故障), 未自动 ClearError: "
                                   f"RobotMode={frame.robot_mode}, errors={ids}")
        # RobotMode 健康(如 5), 但反馈帧 collision/error 锁存位仍置位: 属未清除的历史事件,
        # 非当前碰撞; 需现场确认安全后显式 ClearError
        kind = "碰撞" if frame.collision_state else "报警"
        raise RobotActionError(error_id, frame.robot_mode,
                               f"机器人存在未清除的历史{kind}锁存(RobotMode={frame.robot_mode}, "
                               f"collision_state={frame.collision_state}, error_status={frame.error_status}, "
                               f"errors={ids}); 请确认现场安全后显式 ClearError")

    def _get_error_ids(self) -> tuple[int, ...]:
        # 官方 V4 GetError 实际用 22000 HTTP; 失败时回退 29999 GetErrorID
        try:
            url = f"http://{self.host}:{self.error_http_port}/protocol/getAlarm"
            with urllib.request.urlopen(url, timeout=min(self.command_timeout, 5.0)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return tuple(int(item["id"]) for item in payload.get("errMsg", []) if "id" in item)
        except Exception:
            try:
                reply = self._command("GetErrorID()")
                return tuple(int(value) for value in reply.values)
            except Exception:
                return ()

    def _feedback_from(self, frame: DobotFeedbackFrame, *, pose: Sequence[float] | None = None,
                       joint: Sequence[float] | None = None, last_action: int = 0,
                       tool_confirmed: bool = False, details: dict[str, object] | None = None) -> RobotFeedback:
        output_bits = frame.digital_outputs
        tool_actual = 0
        if self._io_bit(output_bits, 1):
            tool_actual |= 1
        if self._io_bit(output_bits, 3):
            tool_actual |= 2
        if self._io_bit(output_bits, 2):
            tool_actual |= 4
        return RobotFeedback(
            pose=tuple(pose or frame.pose),
            joint=tuple(joint or frame.joint),
            check_result=0,
            last_action=last_action,
            tool_state=ToolState(
                commanded_bits=self._tool_commanded_bits,
                actual_bits=tool_actual,
                di_bits=frame.digital_inputs & 0xFFFF,
                di_available=self.tool_di_feedback_enabled,
                di_confirmed=tool_confirmed,
                do_bits=output_bits & 0xFFFF,
                mounted_tool=int(self._mounted_tool),
            ),
            robot_mode=frame.robot_mode,
            command_id=frame.current_command_id,
            error_ids=self._get_error_ids()
            if frame.robot_mode in (RobotMode.ERROR, RobotMode.COLLISION) or frame.collision_state else (),
            connected=True,
            details={
                "auto_manual_mode": frame.auto_manual_mode,
                "safety_state": frame.safety_state,
                "collision_state": frame.collision_state,
                **(details or {}),
            },
        )

    def _queue_do(self, channel: int, enabled: bool) -> int:
        if channel not in {1, 2, 3, 6}:
            raise PermissionError(f"DO{channel} 不在白名单")
        reply = self._command(f"DO({channel},{int(enabled)})")
        self._raise_dashboard_error(reply, f"DO{channel}")
        return self._reply_command_id(reply, f"DO{channel}")

    def set_mounted_tool(self, tool: MountedTool) -> None:
        """更新权威工具态并落盘 (覆盖基类纯赋值实现).

        robot_tool_pick·put 编排经此注入工具身份, 操作员经 UI 覆盖; 落盘即权威真源,
        下次启动直接读盘恢复 (见 __init__: _mounted_tool = _load_tool()).
        """
        tool = MountedTool(tool)
        self._mounted_tool = tool
        self._persist_tool(tool)

    def _load_tool(self) -> MountedTool:
        """读取权威工具态文件恢复当前挂载夹爪; 文件缺失/损坏 -> NONE (裸腕, 最安全, 不阻断起服)."""
        if self._tool_state_path is None or not self._tool_state_path.exists():
            return MountedTool.NONE
        try:
            data = json.loads(self._tool_state_path.read_text(encoding="utf-8"))
            return MountedTool(int(data["mounted_tool"]))
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("[robot] 工具态文件读取失败, 退回 NONE: %s", self._tool_state_path)
            return MountedTool.NONE

    def _persist_tool(self, tool: MountedTool) -> None:
        """把声明的挂载工具落盘 (下次启动预填); IO 失败仅告警不抛 (不阻断动作)."""
        if self._tool_state_path is None:
            return
        try:
            self._tool_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._tool_state_path.write_text(
                json.dumps({"mounted_tool": int(tool), "name": tool.name}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            log.warning("[robot] 工具态持久化失败, 忽略: %s", self._tool_state_path)

    def _assert_tool_allows(self, action: ToolAction) -> None:
        """工具门控: DO2/DO6 物理含义随挂载工具而变, 不符当前工具的语义动作拒发.

        换刀联轴/辅助/查询动作 (TOOL_AGNOSTIC_ACTIONS) 与工具无关, 永远放行 ——
        否则未声明工具时连挂刀都做不了. 在唯一收口物理掐死双义隐患.
        """
        if action in TOOL_AGNOSTIC_ACTIONS:
            return
        tool = self.mounted_tool
        if action not in TOOL_ALLOWED_ACTIONS.get(tool, frozenset()):
            raise PermissionError(
                f"工具动作 {action.name} 与当前挂载工具 {tool.name} 不符, 拒发"
            )

    def _set_tool_bit(self, channel: int, enabled: bool) -> None:
        semantic_mask = {1: 1, 3: 2, 2: 4}.get(channel)
        if semantic_mask is None:
            return
        if enabled:
            self._tool_commanded_bits |= semantic_mask
        else:
            self._tool_commanded_bits &= ~semantic_mask

    def _command(self, command: str) -> DashboardReply:
        self._require_connected()
        assert self._dashboard is not None
        # 仅守护命令口收发本身; 到点运动等待期间只读 30004, 不占此锁, 故中止命令可抢发
        with self._dashboard_lock:
            return self._dashboard.command(command)

    def _command_scalar(self, command: str) -> int:
        reply = self._command(command)
        self._raise_dashboard_error(reply, command)
        if len(reply.values) != 1:
            raise RobotTransportError(f"{command} 返回值数量错误: {reply.raw}")
        return int(reply.values[0])

    def _command_vector(self, command: str, size: int) -> tuple[float, ...]:
        reply = self._command(command)
        self._raise_dashboard_error(reply, command)
        if len(reply.values) != size:
            raise RobotTransportError(f"{command} 返回值数量错误: {reply.raw}")
        return reply.values

    def _read_frame(self) -> DobotFeedbackFrame:
        self._require_connected()
        assert self._feedback is not None
        thread = self._feedback_thread
        if thread is not None and thread.is_alive():
            with self._feedback_condition:
                generation = self._feedback_generation
            return self._wait_feedback_after(generation, self.command_timeout)
        if self._feedback_error is not None:
            raise RobotTransportError(f"30004 后台反馈已停止: {self._feedback_error}")

        # 离线测试可直接注入 fake 通道而不启动线程；生产 connect() 永远先启动后台泵。
        frame = self._feedback.read_frame()
        self._accept_feedback_frame(frame)
        return frame

    def _accept_feedback_frame(self, frame: DobotFeedbackFrame) -> None:
        """记录后台新帧、唤醒全部等待者，并隔离只读观察者异常。"""
        with self._feedback_condition:
            self._last_frame = frame
            self._feedback_generation += 1
            self._feedback_condition.notify_all()
        observer = self._feedback_observer
        if observer is not None:
            try:
                observer(frame)
            except Exception:
                log.debug("[robot] 30004 反馈观察者异常（已隔离）", exc_info=True)

    def _start_feedback_pump(self) -> None:
        """启动唯一 30004 reader；重复启动直接拒绝，避免形成双读者。"""
        current = self._feedback_thread
        if current is not None and current.is_alive():
            raise RobotTransportError("30004 后台反馈线程已在运行")
        assert self._feedback is not None
        channel = self._feedback
        self._feedback_stop.clear()
        with self._feedback_condition:
            self._feedback_generation = 0
            self._feedback_error = None

        def pump() -> None:
            try:
                while not self._feedback_stop.is_set():
                    self._accept_feedback_frame(channel.read_frame())
            except Exception as exc:
                if not self._feedback_stop.is_set():
                    with self._feedback_condition:
                        self._feedback_error = exc
                        self._feedback_condition.notify_all()
                    log.warning("[robot] 30004 后台反馈停止: %s", exc)

        self._feedback_thread = threading.Thread(
            target=pump,
            name="dobot-30004-feedback",
            daemon=True,
        )
        self._feedback_thread.start()

    def _wait_feedback_after(self, generation: int, timeout: float) -> DobotFeedbackFrame:
        """等待 generation 之后的新反馈；后台异常/关闭/超时均显式失败。"""
        deadline = time.monotonic() + timeout
        with self._feedback_condition:
            while self._feedback_generation <= generation:
                if self._feedback_error is not None:
                    raise RobotTransportError(f"30004 后台反馈失败: {self._feedback_error}")
                if self._feedback_stop.is_set():
                    raise RobotTransportError("30004 后台反馈已关闭")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"等待 30004 新反馈超时 ({timeout:.2f}s)")
                self._feedback_condition.wait(remaining)
            assert self._last_frame is not None
            return self._last_frame

    def set_feedback_observer(
        self,
        observer: Callable[[DobotFeedbackFrame], None] | None,
        *,
        replay_latest: bool = True,
    ) -> None:
        """安装只读反馈观察者；复用 _read_frame，绝不主动读取或下发命令。"""
        self._feedback_observer = observer
        with self._feedback_condition:
            latest = self._last_frame
        if observer is not None and replay_latest and latest is not None:
            try:
                observer(latest)
            except Exception:
                log.debug("[robot] 回放最近反馈帧失败（已隔离）", exc_info=True)

    def _require_connected(self) -> None:
        if self._dashboard is None or self._feedback is None:
            raise RobotTransportError("机器人 TCP transport 未连接")

    def _mark_uncertain_on_io_error(self) -> None:
        # 参数/权限/机器人显式拒绝不等于链路未知; I/O / 断线 / 超时才封锁连接
        error = sys.exc_info()[1]
        if isinstance(error, (OSError, socket.timeout, TimeoutError, RobotTransportError)) and not isinstance(error, RobotActionError):
            # 这一行是事故现场的唯一留痕: 2026-08-16 之前此路径全静默, 现场只看到
            # "断联"却在 backend.log 里找不到任何原因 (uvicorn 只配了自己的 logger,
            # 本模块的 warning 走 lastResort 仍可见)。每次事故只触发一次。
            log.warning("[robot] 链路级异常, 关闭 29999/30004 连接: %r", error)
            self._clean_close = False
            self._close_channels()

    def _close_channels(self) -> None:
        self._feedback_stop.set()
        for channel in (self._dashboard, self._feedback):
            if channel is not None:
                try:
                    channel.close()
                except OSError:
                    pass
        with self._feedback_condition:
            self._feedback_condition.notify_all()
        thread = self._feedback_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=min(self.command_timeout + 0.5, 6.0))
            if thread.is_alive():
                log.warning("[robot] 30004 后台反馈线程在关闭后仍未退出")
        self._dashboard = None
        self._feedback = None

    @staticmethod
    def _raise_dashboard_error(reply: DashboardReply, action: str) -> None:
        if reply.error_id != 0:
            raise RobotActionError(reply.error_id, reply.error_id, f"机器人拒绝 {action}: {reply.raw}")

    @staticmethod
    def _reply_command_id(reply: DashboardReply, action: str) -> int:
        if len(reply.values) != 1 or not reply.values[0].is_integer():
            raise RobotTransportError(f"{action} 未返回唯一 CommandId: {reply.raw}")
        return int(reply.values[0])

    @staticmethod
    def _validate_options(options: MotionOptions) -> None:
        if not 1 <= options.acc <= 100 or not 1 <= options.vel <= 100:
            raise ValueError("acc/vel 必须在 1..100")
        if not 0 <= options.cp <= 100:
            raise ValueError("cp 必须在 0..100")
        if options.user < 0 or options.tool < 0:
            raise ValueError("user/tool 不能为负数")

    @staticmethod
    def _six(values: Sequence[float], label: str) -> tuple[float, ...]:
        if len(values) != 6:
            raise ValueError(f"{label} 必须包含 6 个数值")
        return tuple(float(value) for value in values)

    @staticmethod
    def _fmt(value: float) -> str:
        return f"{float(value):.6f}"

    @staticmethod
    def _io_bit(bits: int, one_based_channel: int) -> bool:
        return bool(bits & (1 << (one_based_channel - 1)))
