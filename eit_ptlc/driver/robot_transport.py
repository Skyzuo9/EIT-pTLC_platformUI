"""机器人传输接口与共享协议类型
================================
功能:
    定义机器人原子动作传输的抽象接口 (RobotTransport) 与共享数据类型
    (运动参数 / 反馈 / 工具动作 / 错误). 仅含机器人语义, 不含具体协议寄存器.
    迁移自 UI-Upper/core/robot_transport.py 的共享部分; Modbus 实现归历史不迁移.
    在原接口基础上新增 jog (点动) / step (步进) 以及中止/暂停/急停/清警/使能抽象方法.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Sequence


class RobotStatus(IntEnum):
    FREE = 0
    BUSY = 1
    DONE = 2
    ERROR = 3


class ToolAction(IntEnum):
    """末端工具语义动作 (白名单; 裸 IO 不直接开放)."""
    QUICK_CHANGE_LOCK = 1
    QUICK_CHANGE_RELEASE = 2
    SUCTION_ON = 3
    SUCTION_OFF = 4
    GRIPPER_OPEN = 5
    GRIPPER_CLOSE = 6
    GET_STATE = 7
    TOOL_CHANGE_AUX_ON = 8
    TOOL_CHANGE_AUX_OFF = 9
    ROTARY_UP = 10
    ROTARY_DOWN = 11


TOOL_ACTION_NAMES = {
    "quick-change-lock": ToolAction.QUICK_CHANGE_LOCK,
    "quick-change-release": ToolAction.QUICK_CHANGE_RELEASE,
    "suction-on": ToolAction.SUCTION_ON,
    "suction-off": ToolAction.SUCTION_OFF,
    "gripper-open": ToolAction.GRIPPER_OPEN,
    "gripper-close": ToolAction.GRIPPER_CLOSE,
    "get-state": ToolAction.GET_STATE,
    "tool-change-aux-on": ToolAction.TOOL_CHANGE_AUX_ON,
    "tool-change-aux-off": ToolAction.TOOL_CHANGE_AUX_OFF,
    "rotary-up": ToolAction.ROTARY_UP,
    "rotary-down": ToolAction.ROTARY_DOWN,
}


class MountedTool(IntEnum):
    """当前挂载的快换工具 (权威工具态; 机器人无 DI 自证, 由权威状态文件持久化恢复).

    四态真源, 启动从 tool_state_file 读盘恢复 (见 dobot_tcp_driver._load_tool):
    NONE: 裸腕 (无工具); 拒发所有语义工具动作 (吸/夹/翻).
    SLOT1/2/3: 旋转吸附(吸盘) / 大夹持 / 小夹持.
    """
    NONE = 0
    SLOT1 = 1
    SLOT2 = 2
    SLOT3 = 3


# 各挂载工具允许的语义工具动作; DO2/DO6 双义在此按工具切开, 不符即拒发.
# (与工具无关的换刀联轴/辅助/查询动作永远放行, 见 TOOL_AGNOSTIC_ACTIONS, 不入此表)
TOOL_ALLOWED_ACTIONS: dict[MountedTool, frozenset[ToolAction]] = {
    MountedTool.SLOT1: frozenset(
        {ToolAction.SUCTION_ON, ToolAction.SUCTION_OFF, ToolAction.ROTARY_UP, ToolAction.ROTARY_DOWN}
    ),
    MountedTool.SLOT2: frozenset({ToolAction.GRIPPER_OPEN, ToolAction.GRIPPER_CLOSE}),
    MountedTool.SLOT3: frozenset({ToolAction.GRIPPER_OPEN, ToolAction.GRIPPER_CLOSE}),
}

# 与当前工具无关、永远放行的动作: 快换联轴/换刀辅助 (发生在工具未声明窗口) 与只读查询.
# 注意 tool-change-aux-on/off 物理上也写 DO6/DO2, 但属换刀联轴语义, 必须放行才能完成挂/卸.
TOOL_AGNOSTIC_ACTIONS: frozenset[ToolAction] = frozenset(
    {
        ToolAction.QUICK_CHANGE_LOCK,
        ToolAction.QUICK_CHANGE_RELEASE,
        ToolAction.TOOL_CHANGE_AUX_ON,
        ToolAction.TOOL_CHANGE_AUX_OFF,
        ToolAction.GET_STATE,
    }
)

# 点动合法轴 (MoveJog axis_id): 关节 J1..J6 + 笛卡尔 X/Y/Z/Rx/Ry/Rz, 带 +/- 方向
JOG_AXES = frozenset(
    [f"J{i}{s}" for i in range(1, 7) for s in ("+", "-")]
    + [f"{a}{s}" for a in ("X", "Y", "Z", "Rx", "Ry", "Rz") for s in ("+", "-")]
)
# 步进笛卡尔轴 (索引 0..5 对应 offset 向量)
STEP_CARTESIAN_AXES = ("X", "Y", "Z", "Rx", "Ry", "Rz")
# 步进关节轴
STEP_JOINT_AXES = ("J1", "J2", "J3", "J4", "J5", "J6")


@dataclass(frozen=True)
class MotionProfile:
    """运动参数档位 (加速度 / 速度 / 平滑过渡), 不含 user/tool."""
    acc: int
    vel: int
    cp: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.acc <= 100 or not 1 <= self.vel <= 100 or not 0 <= self.cp <= 100:
            raise ValueError("运动档位 acc/vel 必须在 1..100, cp 必须在 0..100")


@dataclass(frozen=True)
class MotionOptions:
    """单次运动的坐标系与运动参数."""
    user: int = 0
    tool: int = 1
    acc: int = 20
    vel: int = 20
    cp: int = 0


@dataclass(frozen=True)
class ToolState:
    commanded_bits: int
    actual_bits: int | None
    di_bits: int
    di_available: bool
    di_confirmed: bool
    # 原始 DO 输出位 (低 16 位), 供维护页裸 DO 直控栏实时回显; 不折叠语义
    do_bits: int = 0
    # 权威工具态 (MountedTool 值): 当前挂载夹爪 (0=无/1=吸盘/2=大夹爪/3=小夹爪), 从状态文件读盘恢复
    mounted_tool: int = int(MountedTool.NONE)


@dataclass(frozen=True)
class RobotFeedback:
    pose: tuple[float, ...]
    joint: tuple[float, ...]
    check_result: int
    last_action: int
    tool_state: ToolState
    robot_mode: int | None = None
    command_id: int | None = None
    error_ids: tuple[int, ...] = ()
    connected: bool = True
    details: dict[str, object] = field(default_factory=dict)


class RobotTransportError(RuntimeError):
    """通信或协议失败."""


class RobotActionError(RobotTransportError):
    def __init__(self, error_id: int, check_result: int, message: str | None = None) -> None:
        super().__init__(message or f"机器人动作失败: error_id={error_id}, check={check_result}")
        self.error_id = error_id
        self.check_result = check_result


class RobotMotionInterrupted(RobotActionError):
    """运动被显式中止 (Stop / EmergencyStop), 非故障.

    功能:
        标记一次到点/步进运动因外部中止而提前结束. 作为 RobotActionError 子类,
        使传输层的 IO 错误判定 (_mark_uncertain_on_io_error) 不会因它关闭连接.
    """


class RobotTransport(ABC):
    """单控制者机器人原子动作边界."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def reset_takeover_guard(self) -> None:
        """清除"其他控制者"接管守卫的比对基准 (人工确认后的显式解锁).

        功能:
            真机 transport 用缓存的队列 CommandId 在重连时比对机器人现值, 对不上即
            拒绝接管 ("可能存在其他控制者; 需人工确认")。本方法就是那个"人工确认"的
            落点: 操作员确认机械臂已物理停止、无其他控制者后, 经 reconnect(confirm=True)
            调到这里清掉比对基准, 让下一次 connect 放行。仿真等无守卫实现保持 no-op。
        参数:
            无
        返回:
            None
        """

    @abstractmethod
    def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback: ...

    @abstractmethod
    def move_j(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
        *,
        joint: Sequence[float] | None = None,
    ) -> RobotFeedback: ...

    @abstractmethod
    def move_l(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
        *,
        joint: Sequence[float] | None = None,
    ) -> RobotFeedback: ...

    @abstractmethod
    def tool_action(self, action: ToolAction, timeout_ms: int = 3000) -> RobotFeedback: ...

    @abstractmethod
    def jog_start(self, axis_id: str, options: MotionOptions = MotionOptions()) -> None:
        """开始连续点动 (按住起); axis_id 取自 JOG_AXES."""

    @abstractmethod
    def jog_stop(self) -> None:
        """停止点动 (松开停)."""

    @abstractmethod
    def step(
        self,
        axis: str,
        distance: float,
        options: MotionOptions = MotionOptions(),
        *,
        motion: str = "l",
    ) -> RobotFeedback:
        """单轴步进 (增量移动); axis 取自 STEP_CARTESIAN_AXES 或 STEP_JOINT_AXES."""

    @abstractmethod
    def stop(self) -> None:
        """中止当前运动 (软停, 臂保持使能); 运动中可调用, 使在飞运动以中止结束."""

    @abstractmethod
    def pause(self) -> None:
        """暂停当前运动; 运动中可调用, 配合 resume 恢复."""

    @abstractmethod
    def resume(self) -> None:
        """恢复被 pause 暂停的运动."""

    @abstractmethod
    def emergency_stop(self, pressed: bool = True) -> None:
        """急停; pressed=True 按下 (失能臂并报警), pressed=False 释放. 运动中可调用."""

    @abstractmethod
    def clear_error(self, *, confirm: bool = False) -> RobotFeedback:
        """清除机器人报警; 需配置允许且显式 confirm (双重门控)."""

    @abstractmethod
    def enable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        """使能机器人; 需配置允许且显式 confirm (双重门控)."""

    @abstractmethod
    def disable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        """下使能 (去使能化, 干净失能臂); 需配置允许且显式 confirm (双重门控)."""

    def set_do(self, channel: int, enabled: bool) -> RobotFeedback:
        """裸 DO 直控: 直接置位单个数字输出口 (维护页纯 DO 栏, 不走语义白名单).

        非抽象: 默认抛 NotImplementedError, 供不支持裸 IO 的实现 (测试桩) 继承时显式拒绝.
        Dobot 直连 / 仿真应覆盖本方法; 通道白名单与安全门控由实现与上层模式门控负责.
        """
        raise NotImplementedError("该传输实现不支持裸 DO 直控")

    # ------------------------------------------------------------------
    # 裸 DO 直控 (触发口 DO 不受工具白名单约束, 如 PALLAS 补光 DO7)
    # 非抽象: 默认抛 NotImplementedError, 供不支持的实现 (测试桩) 显式拒绝; Dobot 直连 / 仿真覆盖。
    # ------------------------------------------------------------------

    def set_output(self, channel: int, enabled: bool) -> None:
        """裸 DO 直控任意通道 (供补光触发口如 DO7; 不受工具 DO 白名单 {1,2,3,6} 约束).

        与 set_do 区别: set_do 受工具语义白名单约束 (维护页裸 DO 栏), 本法不约束,
        专供补光触发等非工具 IO; 安全由上层模式门控负责.
        """
        raise NotImplementedError("该传输实现不支持裸 DO 触发输出")

    @property
    def mounted_tool(self) -> MountedTool:
        """当前挂载工具 (权威工具态); 默认 NONE (裸腕), 由 set_mounted_tool 注入."""
        return getattr(self, "_mounted_tool", MountedTool.NONE)

    def set_mounted_tool(self, tool: MountedTool) -> None:
        """显式声明当前挂载工具 (robot_tool_pick·put 编排通知 / 操作员 UI 覆盖).

        机器人无"挂了哪个工具"的 DI, 工具态由知道意图者注入:
        快换锁定后通知 slot, 卸刀后通知 NONE, 操作员可经 UI 覆盖任意值.
        """
        self._mounted_tool = MountedTool(tool)

    def set_speed_factor(self, ratio: int | None = None) -> None:
        """设置全局速度比 SpeedFactor (1-100), 影响点动与所有运动.

        非抽象: 默认无操作, 供无全局速度概念的实现 (部分仿真/测试桩) 直接继承.
        Dobot 直连等真实实现应覆盖本方法并下发 SpeedFactor.
        """
