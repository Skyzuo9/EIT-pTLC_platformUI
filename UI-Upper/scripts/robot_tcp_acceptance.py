#!/usr/bin/env python3
"""机器人 transport 独立验收 CLI；不接入 pTLC 主业务流程。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from core.config import load_config  # noqa: E402
from core.dobot_tcp_transport import DobotTcpRobotTransport  # noqa: E402
from core.robot_service import build_robot_runtime  # noqa: E402
from core.robot_transport import RobotActionError, RobotTransportError, ToolAction  # noqa: E402


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
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "机器人 transport 验收工具。只读：connect/status/query/points-check；"
            "运动或输出：home/move-j/move-l/move-to-point/tool-action/enable/clear-error。"
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=UI_ROOT / "config.example.yaml",
        help="含 robot: 段的 YAML 配置",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("connect", help="[只读] 建立连接并读取状态后立即关闭")
    sub.add_parser("status", help="[只读] 查询 RobotMode/CommandId/位姿/IO")
    sub.add_parser("query", help="[只读] 查询 pose、joint、RobotMode 和 IO")
    sub.add_parser("points-check", help="[只读/离线] 检查点表状态、重复位姿和 home")

    for name, help_text in (
        ("move-j", "[机器人运动] 以 MovJ 到已验收命名点"),
        ("move-l", "[机器人运动] 以 MovL 到已验收命名点"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("point", help="已验收 point_id 或机器人点名（如 P1）")
        cmd.add_argument("--confirm-motion", action="store_true", help="确认现场已清场并允许运动")

    home = sub.add_parser("home", help="[机器人运动] 低速回配置的已验收 home 点")
    home.add_argument("--confirm-motion", action="store_true")

    move = sub.add_parser("move-to-point", help="[机器人运动] 按点位许可执行 MovJ/MovL")
    move.add_argument("point")
    move.add_argument("--motion", choices=("auto", "move_j", "move_l"), default="auto")
    move.add_argument("--confirm-motion", action="store_true")

    tool = sub.add_parser("tool-action", help="[可能驱动末端工具] 执行语义白名单动作")
    tool.add_argument("action", choices=tuple(TOOL_ACTIONS))
    tool.add_argument("--timeout-ms", type=int, default=3000)
    tool.add_argument("--confirm-tool", action="store_true")

    enable = sub.add_parser("enable", help="[改变机器人状态] 显式 EnableRobot（仅 TCP）")
    enable.add_argument("--confirm", action="store_true")
    clear = sub.add_parser("clear-error", help="[改变机器人状态] 显式 ClearError（仅 TCP）")
    clear.add_argument("--confirm", action="store_true")
    return parser


def _points_report(runtime: object) -> dict[str, object]:
    registry = runtime.registry
    home = registry.get(runtime.service.home_point)
    statuses = {
        status: sum(point.status == status for point in registry.points)
        for status in ("validated", "unreviewed", "placeholder", "deprecated")
    }
    return {
        "count": len(registry.points),
        "source_sha256": registry.source_sha256,
        "statuses": statuses,
        "duplicate_pose_groups": registry.duplicate_pose_groups(),
        "home": {
            "point_id": home.point_id,
            "robot_name": home.robot_name,
            "role": home.role,
            "status": home.status,
            "allowed_motion": home.allowed_motion,
        },
    }


def _require(value: bool, message: str) -> None:
    if not value:
        raise PermissionError(message)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = args.config.resolve()
    app_config = load_config(config_path)
    runtime = build_robot_runtime(app_config.robot, base_dir=config_path.parent)

    if args.command == "points-check":
        print(json.dumps(_points_report(runtime), ensure_ascii=False, indent=2))
        return 0

    transport = runtime.transport
    try:
        transport.connect()
        if args.command in {"connect", "status", "query"}:
            feedback = runtime.service.query()
        elif args.command == "home":
            _require(args.confirm_motion, "home 会引发机器人运动，必须传 --confirm-motion")
            feedback = runtime.service.home()
        elif args.command == "move-j":
            _require(args.confirm_motion, "move-j 会引发机器人运动，必须传 --confirm-motion")
            feedback = runtime.service.move_j(args.point)
        elif args.command == "move-l":
            _require(args.confirm_motion, "move-l 会引发机器人运动，必须传 --confirm-motion")
            feedback = runtime.service.move_l(args.point)
        elif args.command == "move-to-point":
            _require(args.confirm_motion, "move-to-point 会引发机器人运动，必须传 --confirm-motion")
            motion = None if args.motion == "auto" else args.motion
            feedback = runtime.service.move_to_point(args.point, motion)
        elif args.command == "tool-action":
            action = TOOL_ACTIONS[args.action]
            if action != ToolAction.GET_STATE:
                _require(args.confirm_tool, "该工具动作会改变 DO，必须传 --confirm-tool")
            feedback = runtime.service.tool_action(action, args.timeout_ms)
        elif args.command == "enable":
            _require(isinstance(transport, DobotTcpRobotTransport), "enable 仅适用于 dobot_tcp")
            feedback = transport.enable_robot(confirm=args.confirm)
        elif args.command == "clear-error":
            _require(isinstance(transport, DobotTcpRobotTransport), "clear-error 仅适用于 dobot_tcp")
            feedback = transport.clear_error(confirm=args.confirm)
        else:
            raise AssertionError(args.command)
        print(json.dumps(asdict(feedback), ensure_ascii=False, indent=2))
        return 0
    except RobotActionError as exc:
        print(
            f"机器人动作失败：error_id={exc.error_id}, check={exc.check_result}, {exc}",
            file=sys.stderr,
        )
        return 3
    except (OSError, TimeoutError, RobotTransportError, ValueError, PermissionError, KeyError) as exc:
        print(f"机器人验收命令失败：{exc}", file=sys.stderr)
        return 2
    finally:
        transport.close()


if __name__ == "__main__":
    raise SystemExit(main())

