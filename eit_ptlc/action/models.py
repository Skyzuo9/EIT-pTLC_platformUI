"""动作层数据模型
================
功能:
    定义统一动作生命周期 / 结构化拒绝原因 / 统一动作结果 ActionResult.
    机器人原子动作与 PLC L2 工位动作经 executor 都归一为 ActionResult, 供 API 与 operation 层消费.
依据:
    central_action_draft.work.md 第 7-8 节 (生命周期与拒绝原因).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ActionStatus(str, Enum):
    """统一动作生命周期."""
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class RejectCode(str, Enum):
    """动作接受前的结构化拒绝原因."""
    BUSY = "BUSY"
    ESTOP_ACTIVE = "ESTOP_ACTIVE"
    UNSAFE = "UNSAFE"
    INVALID_PARAM = "INVALID_PARAM"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    WORKSTATION_OCCUPIED = "WORKSTATION_OCCUPIED"
    MODE_NOT_ALLOWED = "MODE_NOT_ALLOWED"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    PLC_NOT_READY = "PLC_NOT_READY"


# 终态集合 (生命周期结束)
TERMINAL_STATUSES = {
    ActionStatus.REJECTED, ActionStatus.DONE, ActionStatus.ERROR,
    ActionStatus.CANCELLED, ActionStatus.TIMEOUT,
}


@dataclass
class ActionResult:
    """统一动作执行结果.

    功能:
        承载一次动作 (机器人原子 / PLC L2 / 设备原子 / 相机视觉) 的统一反馈.
    字段:
        action: 动作名; request_id: 请求标识; status: 生命周期终态;
        accepted: 是否被接受执行; reject_code: 拒绝原因 (REJECTED 时);
        error_code: 错误码 (ERROR 时); message: 中文消息;
        step: PLC 内部子步; progress: 进度 0-1; retryable: 是否可重试;
        safe_state: 动作后稳定安全状态; result: 结构化结果 (位姿/快照等);
        started_at/finished_at: 时间戳 (epoch 秒, 由调用方注入)
    """
    action: str
    request_id: str
    status: ActionStatus
    accepted: bool = False
    reject_code: Optional[str] = None
    error_code: int = 0
    message: str = ""
    step: int = 0
    progress: float = 0.0
    retryable: bool = False
    safe_state: str = ""
    result: dict = field(default_factory=dict)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.status is ActionStatus.DONE


class ActionRejected(RuntimeError):
    """动作被拒绝 (接受前门控失败)."""

    def __init__(self, result: ActionResult) -> None:
        self.result = result
        super().__init__(f"动作被拒绝: {result.action} reject={result.reject_code} msg={result.message}")
