"""子进程 tee 运行器 (控制台窗 + 日志文件双写, 供 launcher 包裹各子进程)
================================================================
功能:
    起一个真正的命令, 把它的 stdout+stderr 逐行同时写到本进程 stdout (即所在的控制台窗)
    与指定日志文件, 两边都即时 flush. 起之前把已存在的同名日志轮转成 <name>.prev.log
    (只留一级). 子命令退出后原样透传其退出码.

为何:
    launcher 用 CREATE_NEW_CONSOLE 给每个子进程开独立控制台窗, 窗口能滚能搜能复制, 好用;
    但进程一崩窗口立刻关掉, traceback 一闪而过 —— 2026-07-28 后端因 PLC 网口链路断而
    起服失败, 现场只剩 launcher 一行"退出码=3", 驱动打出的排查结论 (裸 TCP 探测/查网线)
    全丢了. 包这一层后窗口观感不变, 崩溃现场则留在 eit_ptlc/var/logs/ 里, launcher 可
    在子进程就绪前退出时把末尾若干行带回主终端.

运行:
    python -m eit_ptlc.tools.run_logged --log <日志路径> -- <真正的命令...>
    例: python -m eit_ptlc.tools.run_logged --log var/logs/backend.log -- \
            python -m uvicorn eit_ptlc.runtime.bootstrap:app --port 18080

关键约束 (改动前先读):
    - 编码: 给子命令设 PYTHONIOENCODING=utf-8 + PYTHONUNBUFFERED=1, 本进程按 UTF-8 解码,
      日志落 UTF-8, 控制台按其代码页 (通常 cp936) 重编码写出. 中文日志过管道时两头不设
      就会花屏, 这是本文件最容易踩的坑.
    - 信号: 本进程忽略 CTRL_C / CTRL_BREAK. launcher 优雅关停后端时是往整个控制台广播
      CTRL_BREAK (见 main.py _graceful_stop_backend), 广播同时打到本 shim 与 uvicorn;
      shim 必须装死才能把 uvicorn lifespan 收尾那几行 (撤 Enable / 关 UV / 复位相机)
      完整落盘, 随后靠子进程 EOF 自然退出.
    - 不在子命令非零退出时留住窗口: 那样本进程不退, launcher 的 poll() 永远拿不到退出码,
      精准的"退出码=3"会退化成"未在 40s 内就绪".

限制:
    - 只合并 stdout/stderr 一路 (stderr 重定向到 stdout), 不区分两者;
    - 子命令若自己开新控制台则输出不经本管道, 拦不住 (launcher 的子进程均不这么做).
"""

from __future__ import annotations

import argparse
import io
import os
import signal
import subprocess
import sys
from pathlib import Path


def _rotate(log_path: Path) -> None:
    """功能: 把已存在的日志轮转成 <stem>.prev<suffix>, 只留一级.

    参数:
        log_path: 本次要写的日志路径
    说明:
        崩完再手动重启一次也不会把上一次的崩溃现场覆盖掉; 轮转失败 (文件被占用等)
        不阻断启动, 大不了这次追加不到干净文件.
    """
    if not log_path.is_file():
        return
    prev = log_path.with_name(f"{log_path.stem}.prev{log_path.suffix}")
    try:
        prev.unlink(missing_ok=True)
        log_path.rename(prev)
    except OSError:
        pass


def _ignore_console_signals() -> None:
    """功能: 忽略 CTRL_C / CTRL_BREAK, 让本 shim 活到子进程收尾结束 (见模块头 '信号')."""
    for name in ("SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, signal.SIG_IGN)
            except (OSError, ValueError):
                pass


def _console_writer():
    """功能: 取按控制台代码页编码的文本写出口 (中文不花屏, 无法编码的字符降级为 ?).

    返回:
        TextIO, 行缓冲; 拿不到 buffer (被重定向到非二进制流) 时退回 sys.stdout
    """
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        return sys.stdout
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return io.TextIOWrapper(buffer, encoding=encoding, errors="replace", line_buffering=True)


def main() -> None:
    """功能: 解析参数 → 起子命令 → 逐行双写 → 透传退出码."""
    parser = argparse.ArgumentParser(
        description="起子命令并把其输出同时写到控制台与日志文件 (tee)")
    parser.add_argument("--log", required=True, help="日志文件路径 (父目录自动创建)")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="-- 之后为真正要执行的命令")
    args = parser.parse_args()

    cmd = list(args.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        parser.error("缺少要执行的命令 (用 -- 分隔, 如: --log a.log -- python -m x)")

    log_path = Path(args.log).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate(log_path)

    _ignore_console_signals()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"   # 子进程输出定为 UTF-8, 与下面的 encoding 对齐
    env["PYTHONUNBUFFERED"] = "1"       # 管道下 stdout 默认块缓冲, 不设则日志一卡一大截

    console = _console_writer()
    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,          # 行缓冲
        )
    except OSError as exc:
        message = f"[run_logged] 无法启动子命令 {cmd}: {exc}\n"
        console.write(message)
        console.flush()
        with log_path.open("w", encoding="utf-8", errors="replace") as fh:
            fh.write(message)
        sys.exit(127)

    with log_path.open("w", encoding="utf-8", errors="replace") as fh:
        assert proc.stdout is not None
        for line in proc.stdout:
            console.write(line)
            console.flush()
            fh.write(line)
            fh.flush()
        proc.stdout.close()
        code = proc.wait()
        tail = f"[run_logged] 子命令退出, 退出码={code}\n"
        fh.write(tail)
        fh.flush()
    console.write(tail)
    console.flush()
    sys.exit(code)


if __name__ == "__main__":
    main()
