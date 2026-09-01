"""机器人原子动作协议的手工验收命令行工具。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parents[1]
# 支持从仓库根目录直接执行本脚本；静态分析路径由根目录 pyrightconfig.json 声明。
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from core.point_registry import PointRegistry  # noqa: E402
from core.robot_transport import (  # noqa: E402
    ModbusRobotTransport,
    MotionOptions,
    RobotActionError,
    RobotFeedback,
    RobotStatus,
    RobotTransportError,
    ToolAction,
)

TOOL_ACTIONS = {
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="机器人 MVP Modbus 验收工具", allow_abbrev=False)
    parser.add_argument("--host", default="192.168.0.15")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--unit-id", type=int, default=1)
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="动作完成硬超时（秒）；默认不限制，机器人到 DONE/ERROR 后才退出",
    )
    parser.add_argument("--byte-order", choices=("be", "word-swap"), default="word-swap")
    parser.add_argument("--point-source", type=Path)
    parser.add_argument("--point-meta", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    def motion_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--user", type=int, default=0)
        command.add_argument("--tool", type=int, default=1)
        command.add_argument("--acc", type=int, default=20)
        command.add_argument("--vel", type=int, default=20)
        command.add_argument("--cp", type=int, default=0)

    motion_options(sub.add_parser("query"))
    motion_options(sub.add_parser("home"))
    for name in ("move-j", "move-l"):
        command = sub.add_parser(name)
        motion_options(command)
        target = command.add_mutually_exclusive_group(required=True)
        target.add_argument("--pose", nargs=6, type=float, metavar=("X", "Y", "Z", "RX", "RY", "RZ"))
        target.add_argument("--point", help="已验收的 point_id 或 Pxx 点名")

    tool = sub.add_parser("tool-action")
    tool.add_argument("action", choices=tuple(TOOL_ACTIONS))
    tool.add_argument("--tool-timeout-ms", type=int, default=3000)

    points = sub.add_parser("points-check")
    points.add_argument("--source-version", default="v0.11")
    return parser


def load_registry(args: argparse.Namespace) -> PointRegistry:
    if args.point_source is None:
        raise ValueError("命名点运动或 points-check 必须提供 --point-source")
    meta = args.point_meta or (UI_ROOT / "config" / "robot_points_meta.json")
    return PointRegistry.load(
        args.point_source,
        source_version=getattr(args, "source_version", "v0.11"),
        meta_path=meta,
    )

def resolve_motion_target(
    args: argparse.Namespace, motion: str
) -> tuple[list[float], MotionOptions, list[float] | None]:
    """解析运动目标。

    --pose 返回原始位姿 + CLI 运动参数；joint 为 None。
    --point 返回注册点位 pose 与标定参数，含关节角（如可用）。
    """
    if args.pose is not None:
        return list(args.pose), MotionOptions(args.user, args.tool, args.acc, args.vel, args.cp), None
    point = load_registry(args).require_motion(args.point, motion)
    return (
        list(point.pose),
        MotionOptions(point.user, point.tool, point.acc, point.vel, point.cp),
        list(point.joint) if point.joint is not None else None,
    )


def print_feedback(feedback: RobotFeedback) -> None:
    print(json.dumps(asdict(feedback), ensure_ascii=False, indent=2))


def print_status(status: RobotStatus, elapsed: float) -> None:
    """运动较慢时持续给出存活信息，避免把正常 BUSY 误认为脚本卡死。"""
    print(f"[robot] status={status.name} elapsed={elapsed:.1f}s", file=sys.stderr, flush=True)


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "points-check":
        registry = load_registry(args)
        print(json.dumps({
            "count": len(registry.points),
            "source_sha256": registry.source_sha256,
            "statuses": {status: sum(p.status == status for p in registry.points) for status in ("validated", "unreviewed", "placeholder", "deprecated")},
            "duplicate_pose_groups": registry.duplicate_pose_groups(),
        }, ensure_ascii=False, indent=2))
        return 0

    options = MotionOptions(args.user, args.tool, args.acc, args.vel, args.cp) if args.command != "tool-action" else MotionOptions()
    transport = ModbusRobotTransport(
        args.host,
        port=args.port,
        unit_id=args.unit_id,
        timeout=args.timeout,
        byte_order=args.byte_order,
        status_callback=print_status,
    )
    try:
        with transport:
            if args.command == "query":
                feedback = transport.query(options)
            elif args.command == "home":
                feedback = transport.home(options)
            elif args.command == "move-j":
                pose, opts, joint = resolve_motion_target(args, "move_j")
                feedback = transport.move_j(pose, opts, joint=joint)
            elif args.command == "move-l":
                pose, opts, _ = resolve_motion_target(args, "move_l")
                feedback = transport.move_l(pose, opts)
            else:
                feedback = transport.tool_action(TOOL_ACTIONS[args.action], args.tool_timeout_ms)
        print_feedback(feedback)
        return 0
    except RobotActionError as exc:
        print(f"机器人拒绝动作：error_id={exc.error_id}, check={exc.check_result}", file=sys.stderr)
        return 3
    except (OSError, TimeoutError, RobotTransportError, ValueError, PermissionError, KeyError) as exc:
        print(f"机器人验收命令失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
