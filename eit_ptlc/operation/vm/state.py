"""mini-VM 运行期内存对象
========================
功能:
    定义 VM 执行状态机与内存结构 (变量 / 作用域 / 调用帧 / 全局环境). 全部在进程内存, 不引 Redis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VmStatus(str, Enum):
    """VM 线程状态机 (镜像土星5 OsThread)."""
    NEW = "NEW"                       # 已构建未运行
    RUNNING = "RUNNING"              # 执行中
    PAUSED = "PAUSED"               # 暂停 (等待 resume)
    WAITING_HUMAN = "WAITING_HUMAN"  # 等待人工回复
    STOPPED = "STOPPED"             # 单步/断点停驻
    DONE = "DONE"                   # 正常结束
    ERROR = "ERROR"                 # 异常结束
    KILLED = "KILLED"               # 被显式停止


@dataclass
class Variable:
    """一个变量绑定.

    字段:
        name: 变量名; scope: local|global; type: VM 类型; io: in|out|var|const;
        value: 当前值; comment: 注释
    """
    name: str
    scope: str
    type: str
    io: str
    value: Any
    comment: str = ""


class Scope:
    """一个作用域的变量表 (局部帧或全局环境)."""

    def __init__(self, variables: dict[str, Variable] | None = None) -> None:
        self.vars: dict[str, Variable] = dict(variables or {})

    def has(self, name: str) -> bool:
        return name in self.vars

    def get(self, name: str) -> Variable | None:
        return self.vars.get(name)


@dataclass
class Frame:
    """一次脚本调用的执行帧 (run_script 压栈一帧).

    字段:
        script_name: 该帧脚本名; locals: 局部 + 局部常量变量表
    """
    script_name: str
    locals: Scope = field(default_factory=Scope)


class GlobalEnv(Scope):
    """全局 + 全局常量变量表 (单 VM 线程内跨帧共享)."""
