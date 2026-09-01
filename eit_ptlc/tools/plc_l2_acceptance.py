#!/usr/bin/env python3
"""PLC L2 原子动作真机验收 CLI (交互式)。

功能:
    交互式驱动 PLC 统一 L2 原子动作通道做真机验收。连接一次 PLC 后进入菜单, 可列出
    动作 / 读 L2 状态 (只读), 或执行动作 / 复位工位 (写 PLC)。注射泵动作 (上样清洗/
    点样 / 收集加液 / 展缸润洗上液) 录入体积/比例/次数等语义参数, 由内置翻译器转成
    SY-03B DT 协议指令写入 PLC 预留变量; 非泵动作录入其已声明参数后触发。

运行 (纯交互, 需 TTY):
    python -m eit_ptlc.tools.plc_l2_acceptance
    python -m eit_ptlc.tools.plc_l2_acceptance --url opc.tcp://127.0.0.1:48400/

安全:
    执行 / 复位会写真实 PLC 并可能驱动泵/轴/气缸/阀, 每次操作前需现场确认 (输入令牌)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

from eit_ptlc.action.registry import ActionDef, ActionRegistry
from eit_ptlc.config.loader import load_config, load_plc_nodes
from eit_ptlc.config.models import ALLOWED_CONTROL_MODES
from eit_ptlc.controller.plc_controller import (
    PlcController,
    PLCActionError,
    PLCActionOutcomeUnknown,
)
from eit_ptlc.driver.opcua_driver import OpcUaDriver
from eit_ptlc.tools.pump.profiles import PUMP_PROFILES, PumpProfile
from eit_ptlc.value_domain import check_enum, describe_enum


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "app.yaml"
STATION_PREFIX = {
    "sampling": "Sampling",
    "collect": "Collect",
    "develop": "Develop",
    "photoscrape": "PhotoScrape",
    "feedlift": "FeedLift",
    "pump": "Pump",
    "staging_a": "StagingA",
}
STATIONS = tuple(STATION_PREFIX)
L2_FIELDS = (
    "ActionCode",
    "RequestSeq",
    "Start",
    "Reset",
    "State",
    "ActiveCode",
    "AcceptedSeq",
    "CompletedSeq",
    "Step",
    "ErrorCode",
    "SafeState",
    "Retryable",
)

# 录入 "跳过" 哨兵 (非必填且未输入时返回, 表示不写该参数)
_SKIP = object()


# ----------------------------------------------------------------------
# 序列化与输出
# ----------------------------------------------------------------------
def _plain(value: Any) -> Any:
    """把 dataclass/Enum/Path 递归转换成 JSON 可序列化对象。"""
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _print_json(value: Any) -> None:
    print(json.dumps(_plain(value), ensure_ascii=False, indent=2))


# ----------------------------------------------------------------------
# 交互输入 (经线程池, 不阻塞 PLC 心跳事件循环)
# ----------------------------------------------------------------------
async def _ainput(prompt: str) -> str:
    """异步读取一行输入; 在执行器线程内调用 input, 保持事件循环 (心跳) 运转。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


def _coerce_scalar(ptype: str, raw: str):
    """按类型强转单个标量输入 (与执行器 _coerce_param 语义一致)。"""
    if ptype == "int":
        return int(raw)
    if ptype == "float":
        return float(raw)
    if ptype == "bool":
        return raw.strip().lower() in ("true", "1", "yes", "on", "y")
    return str(raw)


async def _prompt_scalar(
    label: str,
    ptype: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    default: object = None,
    options: tuple = (),
    required: bool = True,
    unit: str = "",
):
    """交互录入单个标量参数, 显示含义/类型/范围/默认, 非法重输。

    返回:
        强转后的值; 非必填且回车时返回 _SKIP (不写该参数)
    """
    unit_str = f"({unit})" if unit else ""
    range_str = ""
    if minimum is not None or maximum is not None:
        lo = "" if minimum is None else minimum
        hi = "" if maximum is None else maximum
        range_str = f" [{lo}..{hi}]"
    options_str = f" {{{'|'.join(describe_enum(options))}}}" if options else ""
    default_str = f" 默认={default}" if default is not None else ""
    prompt = f"  {label}{unit_str} <{ptype}>{range_str}{options_str}{default_str}: "

    while True:
        raw = (await _ainput(prompt)).strip()
        if raw == "":
            if default is not None:
                return default
            if not required:
                return _SKIP
            print("    必填参数, 请输入。")
            continue
        try:
            value = _coerce_scalar(ptype, raw)
        except (ValueError, TypeError):
            print(f"    类型应为 {ptype}, 无法解析 {raw!r}, 请重输。")
            continue
        # 取值域与 type 正交 (只看有没有 options), 与 executor._validate 同一条规则 ——
        # 否则 type: int 的地轨目标位这类参数会绕过取值域校验
        enum_err = check_enum(options, value, coerce=lambda v: _coerce_scalar(ptype, v))
        if enum_err:
            print(f"    {enum_err}, 请重输。")
            continue
        if ptype in ("int", "float"):
            if minimum is not None and value < minimum:
                print(f"    {value} 小于下限 {minimum}, 请重输。")
                continue
            if maximum is not None and value > maximum:
                print(f"    {value} 超过上限 {maximum}, 请重输。")
                continue
        return value


# ----------------------------------------------------------------------
# L2 状态快照
# ----------------------------------------------------------------------
async def _full_snapshot(driver: OpcUaDriver, station: str) -> dict[str, object]:
    """读取一个工位完整 L2 通道字段快照。"""
    prefix = STATION_PREFIX[station]
    values = await asyncio.gather(
        *(driver.read_variable(f"{prefix}_L2_{field}") for field in L2_FIELDS)
    )
    return {
        "station": station,
        "prefix": prefix,
        **dict(zip(L2_FIELDS, values)),
    }


# ----------------------------------------------------------------------
# 动作目录展示
# ----------------------------------------------------------------------
def _format_action_params(adef: ActionDef) -> str:
    """单行概述一个动作的参数 (参数声明真源 = registry; 泵动作加 [泵] 标记)。"""
    tag = "[泵] " if PUMP_PROFILES.get(adef.name) is not None else ""
    if not adef.params:
        return f"{tag}-" if tag else "-"
    parts: list[str] = []
    for param in adef.params:
        suffix = "*" if param.required else ""
        bounds = ""
        if param.minimum is not None or param.maximum is not None:
            lo = "" if param.minimum is None else param.minimum
            hi = "" if param.maximum is None else param.maximum
            bounds = f"[{lo}..{hi}]"
        parts.append(f"{param.name}{suffix}:{param.type}{bounds}")
    return tag + ", ".join(parts)


def _station_actions(registry: ActionRegistry, station: str) -> list[ActionDef]:
    """按动作码排序返回某工位的全部 plc_l2 动作。"""
    actions = [a for a in registry.by_kind("plc_l2") if a.station == station]
    return sorted(actions, key=lambda item: item.action_code)


def _list_actions(registry: ActionRegistry) -> None:
    """打印全部工位 L2 动作及参数概述。"""
    for station in STATIONS:
        actions = _station_actions(registry, station)
        if not actions:
            continue
        print(f"\n== {station} ({STATION_PREFIX[station]}) ==")
        for adef in actions:
            print(f"  {adef.action_code:>3}  {adef.name:28} {adef.label:28} {_format_action_params(adef)}")


# ----------------------------------------------------------------------
# 参数录入: 泵动作 (语义参数 + 翻译器) / 非泵动作 (已声明参数)
# ----------------------------------------------------------------------
async def _acquire_pump_channels(adef: ActionDef, profile: PumpProfile) -> Optional[dict[str, object]]:
    """录入泵动作语义参数 (声明真源 = registry adef.params) 并经 builder 转成 PLC 通道字典。

    有默认/必填的参数 (体积/比例/次数) 回车采用默认; 可选无默认的 V/M (速度/延时) 可跳过,
    跳过即不写入 semantic, 由 builder 回退 translator 泵档常量。取消或翻译失败返回 None。
    """
    print("  录入语义参数 (回车: 有默认者采用默认 / 可选 V/M 跳过):")
    semantic: dict[str, object] = {}
    for param in adef.params:
        value = await _prompt_scalar(
            param.label or param.name, param.type,
            minimum=param.minimum, maximum=param.maximum,
            default=param.default, options=param.options,
            required=param.required or param.default is not None,
        )
        if value is _SKIP:
            continue
        semantic[param.name] = value
    try:
        return profile.build(semantic)
    except (ValueError, TypeError, KeyError) as exc:
        print(f"  参数翻译失败: {exc}")
        return None


async def _acquire_declared_channels(adef: ActionDef) -> dict[str, object]:
    """录入非泵动作的已声明参数 (参数名即 PLC 变量名); 非必填回车跳过。"""
    if not adef.params:
        return {}
    print("  录入参数 (回车: 必填重输 / 非必填跳过):")
    channels: dict[str, object] = {}
    for param in adef.params:
        value = await _prompt_scalar(
            param.label or param.name, param.type,
            minimum=param.minimum, maximum=param.maximum,
            default=param.default, options=param.options,
            required=param.required,
        )
        if value is _SKIP:
            continue
        channels[param.name] = value
    return channels


def _preview_channels(channels: dict[str, object]) -> None:
    """预览将写入 PLC 的通道字典 (数组逐元素展开, 供操作员核对转化结果)。"""
    if not channels:
        print("  (无参数, 纯触发)")
        return
    for name, value in channels.items():
        if isinstance(value, (list, tuple)):
            print(f"  {name} (数组[{len(value)}]):")
            for index, item in enumerate(value, start=1):
                print(f"    [{index}] {str(item).strip()}")
        else:
            print(f"  {name} = {value}")


# ----------------------------------------------------------------------
# 现场安全确认
# ----------------------------------------------------------------------
async def _confirm_token(token: str, description: str) -> bool:
    """写 PLC 前现场确认; 输入指定令牌才放行。"""
    print("\n警告: 该操作会写入真实 PLC, 可能驱动泵/轴/气缸/阀。")
    print(description)
    answer = (await _ainput(f"确认现场已清场且急停可用, 输入 {token} 执行 (其它取消): ")).strip()
    if answer != token:
        print("已取消。")
        return False
    return True


# ----------------------------------------------------------------------
# 菜单动作
# ----------------------------------------------------------------------
async def _menu_status(driver: OpcUaDriver) -> None:
    """读 L2 状态 (只读): 全部工位或指定工位。"""
    target = (await _ainput(f"工位 (回车=all / {'/'.join(STATIONS)}): ")).strip().lower()
    if target in ("", "all"):
        stations = STATIONS
    elif target in STATIONS:
        stations = (target,)
    else:
        print(f"未知工位: {target}")
        return
    snapshots = [await _full_snapshot(driver, station) for station in stations]
    _print_json({"stations": snapshots})


async def _menu_run(
    driver: OpcUaDriver, plc: PlcController, registry: ActionRegistry, mode: Optional[str],
) -> None:
    """执行一个 L2 动作 (写 PLC): 选工位 -> 选动作 -> 录参 -> 预览 -> 确认 -> 执行。"""
    station = await _select_station()
    if station is None:
        return
    actions = _station_actions(registry, station)
    if not actions:
        print(f"工位 {station} 无 L2 动作。")
        return
    print(f"\n{station} 动作:")
    for index, adef in enumerate(actions, start=1):
        print(f"  [{index}] {adef.action_code:>3} {adef.name:28} {adef.label}  {_format_action_params(adef)}")
    choice = (await _ainput("选择动作序号 (回车取消): ")).strip()
    if not choice:
        return
    try:
        adef = actions[int(choice) - 1]
    except (ValueError, IndexError):
        print("无效序号。")
        return

    # 模式门控 (复刻执行器语义: 动作声明 modes 且当前模式不在其中则拒绝)
    if adef.modes and mode is not None and mode not in adef.modes:
        print(f"动作 {adef.name} 不允许在模式 {mode} 下执行 (需 {list(adef.modes)})。")
        return

    # photoscrape.scrape 的 CNC 点位数组由视觉/cnc_path 生成, 非本工具录入
    if adef.name == "photoscrape.scrape":
        print("注意: 刮取点位数组 g_sx/g_sy/g_cx/g_cy 由 cnc_path/视觉生成, 本工具不录入;"
              " 此处仅按 PLC 当前点位触发刮取。")

    # 录入参数 -> 通道字典
    profile = PUMP_PROFILES.get(adef.name)
    if profile is not None:
        channels = await _acquire_pump_channels(adef, profile)
        if channels is None:
            return
    else:
        channels = await _acquire_declared_channels(adef)

    print("\n将写入 PLC 的参数:")
    _preview_channels(channels)

    description = (
        f"工位={station}  动作={adef.name} (码 {adef.action_code})  参数项={list(channels)}"
    )
    if not await _confirm_token("RUN", description):
        return

    before = await _full_snapshot(driver, station)
    try:
        result = await plc.execute(adef.station, adef.action_code, channels)
        after = await _full_snapshot(driver, station)
        _print_json({
            "action": adef.name,
            "station": station,
            "channels": channels,
            "before": before,
            "result": result,
            "after": after,
        })
        print("结果: DONE")
    except PLCActionError as exc:
        after = await _full_snapshot(driver, station)
        _print_json({"action": adef.name, "result": exc.result, "after": after})
        print(f"结果: 失败 ({exc.result.state.name}) error={exc.result.error_code}")
    except PLCActionOutcomeUnknown as exc:
        after = await _full_snapshot(driver, station)
        _print_json({"action": adef.name, "after": after})
        print(f"结果: 不明确, 禁止自动重发 ({exc})")


async def _menu_reset(driver: OpcUaDriver, plc: PlcController) -> None:
    """脉冲指定工位 L2_Reset 清故障 (写 PLC)。"""
    station = await _select_station()
    if station is None:
        return
    pulse = await _prompt_scalar("Reset 脉冲", "float", minimum=0.0, default=0.1, unit="s")
    if not await _confirm_token("RESET", f"工位={station}  Reset 脉冲={pulse}s"):
        return
    before = await _full_snapshot(driver, station)
    await plc.reset(station, pulse_s=float(pulse))
    after = await _full_snapshot(driver, station)
    _print_json({"station": station, "before": before, "after": after})


async def _select_station() -> Optional[str]:
    """选择工位; 回车取消返回 None。"""
    print(f"\n工位: {', '.join(f'{i + 1}={s}' for i, s in enumerate(STATIONS))}")
    choice = (await _ainput("选择工位序号或名称 (回车取消): ")).strip().lower()
    if not choice:
        return None
    if choice in STATIONS:
        return choice
    try:
        return STATIONS[int(choice) - 1]
    except (ValueError, IndexError):
        print("无效工位。")
        return None


# ----------------------------------------------------------------------
# 主循环
# ----------------------------------------------------------------------
async def _repl(
    driver: OpcUaDriver, plc: PlcController, registry: ActionRegistry, url: str, mode: Optional[str],
) -> int:
    """交互主菜单循环。"""
    print(f"\nPLC L2 原子动作交互式验收  PLC={url}  模式={mode or '(不限)'}")
    while True:
        print(
            "\n[1] 列出动作   [2] 读 L2 状态(只读)   "
            "[3] 执行动作(写 PLC)   [4] 复位工位(写 PLC)   [5] 退出"
        )
        try:
            choice = (await _ainput("请选择: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0
        try:
            if choice == "1":
                _list_actions(registry)
            elif choice == "2":
                await _menu_status(driver)
            elif choice == "3":
                await _menu_run(driver, plc, registry, mode)
            elif choice == "4":
                await _menu_reset(driver, plc)
            elif choice in ("5", "q", "quit", "exit"):
                print("已退出。")
                return 0
            else:
                print("无效选择。")
        except KeyboardInterrupt:
            print("\n操作已中断, 返回主菜单。")
        except (OSError, ConnectionError, TimeoutError) as exc:
            print(f"PLC 通信异常: {exc}")


async def _async_main(args: argparse.Namespace) -> int:
    if args.poll_interval <= 0:
        raise ValueError("--poll-interval 必须大于 0")
    if args.timeout is not None and args.timeout <= 0:
        raise ValueError("--timeout 必须大于 0")

    config = load_config(args.config.resolve())
    registry = ActionRegistry.load(config.plc.nodes_file.parent / "actions")
    mode = args.mode or config.control_mode

    node_map = load_plc_nodes(config.plc.nodes_file)
    url = args.url or config.plc.url
    driver = OpcUaDriver(
        url,
        node_map,
        reconnect_wait_timeout=config.plc.reconnect_wait_timeout,
    )
    try:
        await driver.connect()
    except (OSError, ConnectionError, TimeoutError) as exc:
        # TimeoutError 等异常的 str() 可能为空, 回退到类型名并带上所连地址与排查提示
        detail = str(exc) or type(exc).__name__
        raise ConnectionError(
            f"无法连接 PLC OPC UA: {url} ({detail}); 请确认地址可达, 或用 --url 指定可达端点 (如 mock)"
        ) from exc
    try:
        plc = PlcController(
            driver,
            poll_interval=args.poll_interval,
            action_timeout=args.timeout or config.plc.action_timeout,
        )
        return await _repl(driver, plc, registry, url, mode)
    finally:
        await driver.disconnect()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PLC L2 原子动作交互式验收工具 (连接后进入菜单)。",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="eit_ptlc app.yaml")
    parser.add_argument("--url", help="覆盖配置中的 PLC OPC UA URL")
    parser.add_argument("--timeout", type=float, help="单动作终态等待上限 (秒)")
    parser.add_argument("--poll-interval", type=float, default=0.05, help="状态轮询间隔 (秒)")
    parser.add_argument("--mode", choices=ALLOWED_CONTROL_MODES, help="覆盖动作模式门控")
    parser.add_argument("--verbose", action="store_true", help="显示 INFO 通信日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    if not sys.stdin.isatty():
        print("本工具为纯交互式, 需在终端 (TTY) 运行。", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return 130
    except (OSError, ConnectionError, TimeoutError, PermissionError, ValueError, KeyError) as exc:
        detail = str(exc) or type(exc).__name__
        print(f"PLC L2 验收失败: {detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
