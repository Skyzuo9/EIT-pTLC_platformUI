"""离线管线的泵档 provider 安装器
================================
功能:
    把 config/app.yaml 的 pump 段接进 profiles 的持久档回退链
    (set_pump_defaults_provider), 让**离线**消费方(三维片段编译器等)与运行链
    走同一条 `动作传值 > config.pump > translator 常量` 回退 —— 仿真模块阶段①
    "泵链路归真"的收口件: 此前编译器只认构建期拍的 manifest 速度快照, 快照陈旧
    时演示时长与实机脱钩。

语义差异 (刻意, 写明):
    运行链 provider 是 ConfigService live-read(每次取值重读); 本安装器是
    **安装时一次性快照** —— 离线编译是批处理, 批内 app.yaml 不会变, 换文件重装
    即可。安装失败(缺文件/格式坏)静默回退 translator 常量并返回 False, 与
    profiles._config_default "读失败绝不阻断" 同一条纪律。
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# 已安装的 app.yaml 路径 (幂等: 同路径重复调用不重读文件)
_installed_for: Path | None = None


def install_pump_defaults_from_app_yaml(app_yaml: str | Path) -> bool:
    """解析 app.yaml 的 pump 段并注入 profiles provider (幂等)。

    参数:
        app_yaml: config/app.yaml 路径
    返回:
        是否安装成功 (失败已回退常量, 不抛)
    """
    global _installed_for
    path = Path(app_yaml)
    if _installed_for == path:
        return True
    try:
        import yaml

        from eit_ptlc.config.loader import _parse_pump
        from eit_ptlc.tools.pump.profiles import set_pump_defaults_provider

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        parsed = _parse_pump(raw.get("pump"))
        set_pump_defaults_provider(lambda: parsed)
        _installed_for = path
        return True
    except Exception as exc:                      # noqa: BLE001  (回退常量, 不阻断编译)
        log.warning("泵档持久值安装失败(回退 translator 常量): %s: %s", path, exc)
        return False
