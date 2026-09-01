#!/usr/bin/env python3
"""Independent schema-v2 Modbus robot flow and route acceptance CLI."""
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
from core.robot_flow import RobotFlowError  # noqa: E402
from core.robot_service import build_robot_runtime  # noqa: E402
from core.robot_transport import RobotTransportError  # noqa: E402


def add_params(parser: argparse.ArgumentParser, station: bool = False) -> None:
    parser.add_argument("--tool-id", type=int, choices=range(1, 4))
    parser.add_argument("--tank-id", type=int, choices=range(1, 9))
    parser.add_argument("--rack-id", choices=("collector", "bottle"))
    parser.add_argument("--slot-id", type=int, choices=range(1, 7))
    if station:
        parser.add_argument(
            "--station-id",
            choices=("default", "spotting", "scrape", "waste"),
            help="engineering-only fixed-station selector",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=UI_ROOT / "config.example.yaml"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="[offline] list templates and routes")
    sub.add_parser("check", help="[offline] preflight all legal route cases")

    item = sub.add_parser("resolve-flow", help="[offline] resolve a robot template")
    item.add_argument("template")
    add_params(item, station=True)
    item = sub.add_parser("resolve-route", help="[offline] resolve a business route")
    item.add_argument("route")
    add_params(item)
    item = sub.add_parser("resolve-test", help="[offline] resolve a test template")
    item.add_argument("template")
    item.add_argument("--test-id", choices=("p2",), required=True)

    item = sub.add_parser("run-flow", help="[Modbus motion/IO] run a robot template")
    item.add_argument("template")
    add_params(item, station=True)
    item.add_argument("--confirm-flow", action="store_true")
    item = sub.add_parser("run-test", help="[Modbus motion/IO] run a test template")
    item.add_argument("template")
    item.add_argument("--test-id", choices=("p2",), required=True)
    item.add_argument("--confirm-flow", action="store_true")
    return parser


def params(args: argparse.Namespace) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in ("tool_id", "tank_id", "rack_id", "slot_id", "station_id"):
        value = getattr(args, name, None)
        if value is not None:
            result[name] = value
    return result


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = None
    connected = False
    try:
        config_path = args.config.resolve()
        app_config = load_config(config_path)
        runtime = build_robot_runtime(app_config.robot, base_dir=config_path.parent)

        if args.command == "list":
            emit({
                "production_templates": runtime.plan_catalog.template_ids,
                "test_templates": runtime.plan_catalog.test_template_ids,
                "business_routes": runtime.route_planner.route_ids,
            })
            return 0
        if args.command == "check":
            legal = runtime.route_planner.resolve_all_legal()
            emit({
                "status": "offline-resolve-passed",
                "config_version": runtime.plan_catalog.config_version,
                "config_sha256": runtime.plan_catalog.config_sha256,
                "host_config_sha256": runtime.host_action_catalog.source_sha256,
                "point_source_sha256": runtime.registry.source_sha256,
                "validated_points": sum(
                    p.status == "validated" for p in runtime.registry.points
                ),
                "production_template_count": len(runtime.plan_catalog.template_ids),
                "test_template_count": len(runtime.plan_catalog.test_template_ids),
                "business_route_count": len(runtime.route_planner.route_ids),
                "legal_route_case_count": len(legal),
                "field_status": "not-run",
            })
            return 0
        if args.command == "resolve-flow":
            emit(asdict(runtime.plan_catalog.resolve(args.template, params(args))))
            return 0
        if args.command == "resolve-route":
            emit(asdict(runtime.route_planner.resolve(args.route, params(args))))
            return 0
        if args.command == "resolve-test":
            emit(asdict(runtime.plan_catalog.resolve(
                args.template, {"test_id": args.test_id}, allow_test=True
            )))
            return 0

        if not args.confirm_flow:
            print("Motion and tool IO require --confirm-flow.", file=sys.stderr)
            return 2
        if app_config.robot.transport != "modbus":
            print("Field execution requires ModbusRobotTransport.", file=sys.stderr)
            return 2
        plan = runtime.plan_catalog.resolve(
            args.template,
            {"test_id": args.test_id} if args.command == "run-test" else params(args),
            allow_test=args.command == "run-test",
        )
        runtime.transport.connect()
        connected = True
        result = runtime.flow_service.run_resolved(
            plan.flow,
            on_step=lambda step, status: print(
                f"[robot-flow] {step}: {status}", file=sys.stderr, flush=True
            ),
        )
        emit({
            "config_version": plan.config_version,
            "config_sha256": plan.config_sha256,
            "business_params": dict(plan.business_params),
            "point_set_id": plan.point_set_id,
            "resolved_points": dict(plan.resolved_points),
            "result": asdict(result),
            "field_status": "executed",
        })
        return 0
    except RobotFlowError as exc:
        print(
            f"Robot flow failed: {exc.flow_id}/{exc.failed_step}: {exc.cause}",
            file=sys.stderr,
        )
        return 3
    except (
        OSError, TimeoutError, RobotTransportError,
        ValueError, PermissionError, KeyError,
    ) as exc:
        print(f"Robot acceptance failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if runtime is not None and connected:
            runtime.transport.close()


if __name__ == "__main__":
    raise SystemExit(main())
