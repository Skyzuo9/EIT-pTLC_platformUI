"""mini-VM 异常类型
==================
功能:
    定义 VM 解释执行期间的异常体系. 借 Python 异常机制实现脚本 raise/try-catch 的传播与匹配.
"""

from __future__ import annotations


class VmError(Exception):
    """VM 内部错误 (脚本结构非法 / 变量未声明 / 迭代超限等). 不可被脚本 catch 捕获以外的常规处理."""


class VmRaise(VmError):
    """脚本显式 raise 抛出的业务异常.

    参数:
        error: 错误名 (字符串标签, 供 try/catch 按名匹配, 如 VISION_EMPTY)
        message: 中文错误消息
    """

    def __init__(self, error: str, message: str = "") -> None:
        self.error = str(error)
        self.message = str(message)
        super().__init__(f"{self.error}: {self.message}")


class VmActionError(VmError):
    """叶子设备调用 (call) 返回非 DONE 结果时抛出, 作为 fail-fast 与 try/catch 的挂钩.

    参数:
        result: 失败的 ActionResult
    属性:
        error: 供 try/catch 匹配的错误名 = reject_code 或状态值 (如 BUSY / ERROR / TIMEOUT)
    """

    def __init__(self, result) -> None:
        self.result = result
        self.error = result.reject_code or result.status.value
        super().__init__(
            f"动作失败: {result.action} status={result.status.value} msg={result.message}"
        )
