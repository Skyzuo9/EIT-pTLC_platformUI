"""
功能: 管线各步骤共用的小工具 —— 配置加载/路径处理/日志/耗时统计.
参数: 见各函数签名
返回值: 见各函数说明
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from typing import Any

import yaml

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(PIPELINE_DIR, "pipeline.yaml")


def load_config(path: str | None = None) -> dict[str, Any]:
    """
    功能: 读取 pipeline.yaml 配置, 并把所有路径规范化为绝对路径.
    参数:
        path: 配置文件路径; None 表示使用管线目录下的 pipeline.yaml
    返回值: dict, 配置字典
    """
    config_path = os.path.abspath(path or DEFAULT_CONFIG)
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    config_dir = os.path.dirname(config_path)

    def resolve_path(value: str) -> str:
        """
        功能:
            将管线配置路径相对 pipeline.yaml 所在目录解析, 绝对路径保持原义.

        参数:
            value: YAML 中的路径文本.

        返回:
            规范化后的绝对路径.
        """
        raw = os.path.expandvars(str(value))
        if os.path.isabs(raw) is True:
            return os.path.normpath(raw)
        return os.path.normpath(os.path.abspath(os.path.join(config_dir, raw)))

    for key, value in config.get("paths", {}).items():
        config["paths"][key] = resolve_path(value)
    for key, value in config.get("sources", {}).items():
        config["sources"][key] = resolve_path(value)

    config["_config_path"] = config_path
    return config


def ensure_dir(path: str) -> str:
    """
    功能: 确保目录存在(若传入的是文件路径, 则创建其父目录).
    参数:
        path: 目录或文件路径
    返回值: str, 传入的原路径
    """
    directory = path if os.path.splitext(path)[1] == "" else os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return path


def human_size(num_bytes: float) -> str:
    """
    功能: 把字节数格式化成便于阅读的字符串.
    参数:
        num_bytes: 字节数
    返回值: str, 如 "289.3 MB"
    """
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} GB"


def log(message: str) -> None:
    """
    功能: 打印带时间戳的日志并立刻刷新, 便于在后台长任务里实时观察进度.
    参数:
        message: 日志内容
    返回值: None
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


@contextmanager
def timed(label: str):
    """
    功能: 上下文管理器, 统计并打印一段操作的耗时.
    参数:
        label: 操作名称
    返回值: 生成器, 无产出值
    """
    log(f"开始: {label}")
    started = time.time()
    try:
        yield
    finally:
        log(f"完成: {label} (耗时 {time.time() - started:.1f}s)")


def write_report(path: str, payload: dict[str, Any]) -> str:
    """
    功能: 把步骤产出的结构化报告写成 JSON, 供后续步骤与人工审查使用.
    参数:
        path: 输出 JSON 路径
        payload: 报告内容
    返回值: str, 输出路径
    """
    ensure_dir(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    log(f"报告已写入: {path}")
    return path


def die(message: str, code: int = 1) -> None:
    """
    功能: 打印错误并以非零码退出, 让后台任务的失败可被立即察觉.
    参数:
        message: 错误说明
        code: 退出码
    返回值: None(不返回)
    """
    print(f"错误: {message}", file=sys.stderr, flush=True)
    raise SystemExit(code)
