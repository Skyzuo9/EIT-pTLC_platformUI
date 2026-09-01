"""Compile the active PTLC PointRegistry/operations into offline 3D robot assets.

Inputs are discovered only through PTLC_CONTROL_ROOT.  Generated browser assets contain
relative source labels, the point-table SHA and the pinned CR5 commit, never a workstation path.
"""

from __future__ import annotations

import argparse
import collections
import fnmatch
import json
import math
import os
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

import clip_compiler
import flow_discovery
from robot_kinematics import forward_kinematics, load_calibration, sample_move_l


ROOT = Path(__file__).resolve().parents[1]
# 产物落在 three_d 根: 前端经 /api/3d/assets/clips/*.yaml 直接读这里(见 api/three_d_routes.py)。
# ⚠ 曾经默认指向 app/public —— 那是**已废弃的独立三维应用**目录(docs/CLAUDE.md 明确
# "不存在独立三维应用")。默认值留在那里的后果是: 生成一路绿灯, 而页面读到的还是旧片段。
DEFAULT_OUTPUT = ROOT
# Controller tool number -> GLB node.  All three tools exist in the model (slot 1 is
# assembled from loose parts via rig_map's `members`, see docs/CR5_DIGITAL_TWIN.md).
TOOL_ASSET = {1: "TOOL_SUCTION", 2: "TOOL_PLATE96", 3: "TOOL_VIAL"}


def _control_root(value: str | None) -> Path:
    raw = value or os.environ.get("PTLC_CONTROL_ROOT")
    if not raw:
        raise SystemExit("PTLC_CONTROL_ROOT 未设置；同步器拒绝使用绝对开发机路径")
    root = Path(raw).resolve()
    if not (root / "controller" / "point_registry.py").is_file():
        raise SystemExit(f"PTLC_CONTROL_ROOT 不是有效上位机目录: {root}")
    return root


def _load_registry(root: Path):
    sys.path.insert(0, str(root.parent))
    from eit_ptlc.controller.point_registry import PointRegistry  # pylint: disable=import-outside-toplevel

    point_dir = root / "config" / "points" / "robot"
    meta_path = point_dir / "robot_points_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    registry = PointRegistry.load(
        point_dir / "robot_points.json",
        source_version=str(meta.get("source_version", "unknown")),
        meta_path=meta_path,
        labels_path=point_dir / "labels.yaml",
    )
    return registry


def _literal(value, default=None):
    if isinstance(value, dict) and "lit" in value:
        return value["lit"]
    return default


def _condition_value(condition) -> int | None:
    if not isinstance(condition, dict) or condition.get("binop") != "==":
        return None
    for side in (condition.get("left"), condition.get("right")):
        value = _literal(side)
        if isinstance(value, int):
            return value
    return None


def _select_tool_branch(document: dict, tool_id: int) -> list[dict]:
    body = document.get("body") or []
    if len(body) != 1 or body[0].get("op") != "if":
        raise ValueError(f"{document.get('name')} 不是受支持的单层工具分支 operation")
    branch = body[0]
    if _condition_value(branch.get("cond")) == tool_id:
        return branch.get("then") or []
    for alternative in branch.get("elifs") or []:
        if _condition_value(alternative.get("cond")) == tool_id:
            return alternative.get("body") or []
    raise ValueError(f"{document.get('name')} 没有 tool_id={tool_id} 分支")


def _move_duration(current: list[float], target: list[float], velocity: float, motion: str) -> float:
    delta = max(abs(a - b) for a, b in zip(current, target))
    divisor = max(8.0, float(velocity)) * (0.75 if motion == "move_j" else 0.5)
    return round(min(4.0, max(0.35, delta / divisor)), 3)


#: 反解一个派生点时最多试几个种子(父示教点用完之后按位姿由近到远试)。
#: 种子决定解到哪个位形分支, 所以"由近到远"不是凑数: 相邻点位的手肘/腕部翻转本就该一致。
IK_SEED_FALLBACKS = 5


def _has_joint(item: dict) -> bool:
    """点位是否带**实测**关节角。全零视为占位, 不是实测值(与 clipSchema 同一条判据)。"""
    joint = item.get("joint")
    return bool(joint) and any(abs(float(value)) > 1e-9 for value in joint)


def _solve_derived_joints(points: dict, calibration: dict) -> dict:
    """给没有实测关节角的点位离线反解一份, 写进 `jointSolved`。

    为什么要做: 239 个点位里 169 个是派生点(接近位/退离位/货架各库位), 只有 pose、
    allowedMotion 只允许 move_l —— 前端的即时近似展开拿不到关节角就只能跳过它们, 机械臂
    于是在少数几个示教点之间瞬移, 接近/退离整段丢失, 看着就是穿模乱窜。

    为什么在这里解而不是在浏览器里解: 反解(robot_kinematics.solve_ik)是官方 xacro 链 +
    cr5_ptlc_v1 标定 + 关节限位 + 失败即拒的那一份, 已经存在。往前端再塞一份数值反解, 就是
    本仓吃过亏的"两边各留一份公式"(linkageKinematics.js vs solve_lid_kinematics), 而且一条
    流程上百次反解也谈不上"秒级可见"。派生点是**静态**的, 解一次落盘即可。

    为什么写新字段而不是覆盖 `joint`: `joint` 的语义是"现场示教出来的实测值", 精编译片段的
    move_j 门禁(clipSchema.js)与 pose/joint 半新态检查(clip_compiler._consistent_joint)都
    建立在这个语义上。灌进去会让那些门禁从此形同虚设, 且没有任何指标会报警 —— 本仓已经为
    pose/joint 漂移付过一次代价(P11-P18 差整整一个吸附基准)。

    Args:
        points: _catalog 已经填好的点位表(原地补字段)
        calibration: 运动学标定

    Returns:
        {"solved": 解出数, "failed": [(point_id, 原因), ...]}
    """
    from robot_kinematics import pose_matrix, solve_ik  # pylint: disable=import-outside-toplevel

    by_robot_name = {item.get("robotName"): key for key, item in points.items()}
    known = [
        (key, item["pose"][:3]) for key, item in points.items()
        if _has_joint(item) and item.get("pose")
    ]
    solved_count = 0
    failures: list[tuple[str, str]] = []

    for point_id, item in points.items():
        if _has_joint(item) or not item.get("pose"):
            continue
        target = pose_matrix(item["pose"])
        tool = int(item.get("tool") or 1)
        position = item["pose"][:3]

        seeds: list[tuple[str, list]] = []
        parent_key = by_robot_name.get(str(item.get("derivedFrom") or ""))
        if parent_key and _has_joint(points[parent_key]):
            seeds.append((parent_key, points[parent_key]["joint"]))
        nearest = sorted(
            known,
            key=lambda entry: math.dist(entry[1], position),
        )[:IK_SEED_FALLBACKS]
        seeds.extend((key, points[key]["joint"]) for key, _ in nearest)

        reason = "没有可用种子"
        for seed_key, seed in seeds:
            try:
                joints = solve_ik(target, seed, calibration, tool=tool)
            except ValueError as exc:
                reason = str(exc)
                continue
            item["jointSolved"] = [round(float(value), 6) for value in joints]
            item["jointSolvedFrom"] = seed_key
            solved_count += 1
            break
        else:
            failures.append((point_id, reason))

    return {"solved": solved_count, "failed": failures}


def _catalog(registry, calibration: dict) -> dict:
    points = {}
    for point in registry.points:
        item = {
            "robotName": point.robot_name,
            "alias": point.alias,
            "label": point.label,
            "pose": list(point.pose),
            "joint": list(point.joint) if point.joint is not None else None,
            # 离线反解出来的关节角(派生点专用); 与实测 joint 严格分开, 见 _solve_derived_joints
            "jointSolved": None,
            "jointSolvedFrom": None,
            "tool": point.tool,
            "user": point.user,
            "rail": point.rail,
            "status": point.status,
            "allowedMotion": list(point.allowed_motion),
            "derivedFrom": point.derived_from,
        }
        points[point.point_id] = item

    report = _solve_derived_joints(points, calibration)
    missing = sum(1 for item in points.values() if not _has_joint(item))
    print(f"点位目录: {len(points)} 个点位, 其中 {missing} 个无实测关节角 —— "
          f"离线反解出 {report['solved']} 个, 仍缺 {len(report['failed'])} 个")
    for point_id, reason in report["failed"]:
        print(f"    [反解失败] {point_id}: {reason}")

    return {
        "schema": "ptlc.robot-points/v1",
        "referencePointHash": registry.source_sha256,
        "kinematicsCommit": calibration["kinematics_source"]["commit"],
        "calibrationVersion": calibration["version"],
        "points": points,
    }


def _compile_operation(
    control_root: Path,
    registry,
    calibration: dict,
    operation_name: str,
    *,
    tool_id: int,
    manifest: dict | None = None,
) -> dict:
    if tool_id not in TOOL_ASSET:
        known = "、".join(f"{key}={value}" for key, value in sorted(TOOL_ASSET.items()))
        raise ValueError(f"tool_id={tool_id} 没有对应 CAD 工具；当前模型包含 {known}")
    operation_path = control_root / "config" / "operation" / "06_robot" / f"{operation_name}.yaml"
    document = yaml.safe_load(operation_path.read_text(encoding="utf-8"))
    instructions = _select_tool_branch(document, tool_id)
    home_point = registry.get("robot-main.home")
    if home_point.joint is None:
        raise ValueError("robot-main.home 没有实测 joint")
    current = list(home_point.joint)
    steps: list[dict] = []
    trajectories: dict[str, list[list[float]]] = {}
    rail_home_mm = 500.0  # rail.yaml slot 4; emitted in metres by the manifest's 0.001 factor.

    for instruction in instructions:
        if instruction.get("op") != "call":
            continue
        action = instruction.get("action")
        args = instruction.get("args") or {}

        if action == "rail.ensure":
            slot = int(_literal(args.get("Rail_Target_Position"), 0))
            if slot != 4:
                raise ValueError(f"工具 operation 期望 rail slot 4，实际 {slot}")
            steps.append({
                "label": "地轨到工具工位 4",
                "dur": 1.5,
                "ease": "inout",
                "do": {"axis": {"id": "axis_11y", "to_mm": rail_home_mm}},
            })
            continue

        if action == "robot.move_to_point":
            point_id = str(_literal(args.get("point_id_or_robot_name"), ""))
            motion = str(_literal(args.get("motion"), ""))
            point = registry.require_motion(point_id, motion)
            velocity = float(_literal(args.get("vel"), point.vel))
            step_index = len(steps)

            if motion == "move_j":
                if point.joint is None or max(abs(value) for value in point.joint) < 1e-9:
                    raise ValueError(f"{point_id} 的 move_j 没有有效实测 joint")
                target = list(point.joint)
            elif motion == "move_l":
                target_path = sample_move_l(current, point.pose, calibration, tool=point.tool)
                target = target_path[-1]
                trajectories[str(step_index)] = target_path
                # Compile-time independent FK check; do not publish a guessed endpoint.
                actual = forward_kinematics(target, calibration, tool=point.tool)
                expected = point.pose
                error_mm = math.sqrt(sum((actual[i, 3] * 1000.0 - expected[i]) ** 2 for i in range(3)))
                if error_mm > 1.0:
                    raise ValueError(f"{point_id} move_l 终点 FK 误差 {error_mm:.3f}mm")
            else:
                raise ValueError(f"不支持的机器人运动: {motion}")

            steps.append({
                "label": point.label or point.alias or point.point_id,
                "dur": _move_duration(current, target, velocity, motion),
                "ease": "inout" if motion == "move_j" else "linear",
                "do": {"robot_point": {"id": point.point_id, "motion": motion}},
            })
            current = target
            continue

        if action == "robot.tool_action":
            actuator = str(_literal(args.get("action"), ""))
            if actuator in {"quick-change-lock", "quick-change-release"}:
                steps.append({
                    "label": "快换锁紧" if actuator.endswith("lock") else "快换释放",
                    "dur": 0.45,
                    "do": {
                        "tool": {
                            "action": "lock" if actuator.endswith("lock") else "release",
                            "id": TOOL_ASSET[tool_id],
                        }
                    },
                })
            else:
                steps.append({"label": actuator, "dur": 0.3, "do": {"wait": {}}})
            continue

        if action == "robot.dwell":
            duration_ms = float(_literal(args.get("duration_ms"), 0.0))
            steps.append({"label": "等待", "dur": duration_ms / 1000.0, "do": {"wait": {}}})

    if not steps:
        raise ValueError(f"{operation_name} 未生成任何动画步骤")
    return {
        "schema": "ptlc.clip/v2",
        "name": operation_name.replace("robot_tool_pick", "robot.tool_pickup").replace("robot_tool_put", "robot.tool_return"),
        "label": f"{document.get('label', operation_name)}（实机点位）",
        "description": "由 PointRegistry 与上位机 operation 编译；禁止手工填写生产关节角。",
        "operation": {"name": operation_name, "inputs": {"tool_id": tool_id}},
        "source": {
            "operation": f"config/operation/06_robot/{operation_name}.yaml",
            "referencePointHash": registry.source_sha256,
            "kinematicsCommit": calibration["kinematics_source"]["commit"],
            "calibrationVersion": calibration["version"],
            # 显式 null: 本条通路不建 RobotPosture, moveL 轨迹是机器人基座系里的关节
            # 采样, 不含任何按地轨标定折算的落位 —— 改地轨零点不会让它陈旧.
            # 写 null 而不是省略键, 是为了与"旧编译器产物(未标记)"区分开.
            "railCalib": None,
        },
        "home": {
            # 轴起手态: 地轨在 4 号工具位 + STATION_AXIS_HOME 的静态停放位(与
            # ClipBuilder.__init__ 同一张表 —— 缺了它换刀片段里刮板 9X 会停在未让位端)。
            "axis_mm": {"axis_11y": rail_home_mm,
                        **{axis_id: park_mm for axis_id, (park_mm, _why)
                           in clip_compiler.STATION_AXIS_HOME.items()}},
            "joints_deg": list(home_point.joint),
            # 机构起手态: 与 compile_plate_route/compile_transfer 同一张 MECHANISM_HOME。
            # 这两个换刀片段一样在演示页播, 缺了它 col_lift/col_clamp/8 个缸盖会停在
            # CAD 基位(那对 outputRange 递减的十条是反的)。
            **_mechanism_home_block(manifest),
        },
        "steps": steps,
        "compiled": {"moveLTrajectories": trajectories},
    }


def _mechanism_home_block(manifest: dict | None) -> dict:
    """给迷你编译器产出 home 的机构两段; manifest 缺失时退回空(此路径本就可无 manifest)。"""
    if not manifest:
        return {}
    actuators, linkages = clip_compiler.mechanism_home_of(manifest)
    return {"actuators": actuators, "linkages": linkages}


def _report_dock_residuals(written) -> None:
    """打印并门禁"示教点推算落位 vs CAD 目的地实测"的残差。

    整板路线的目的地在 CAD 里有真实节点, 这条比对因此是可证伪的: 两套坐标同源, 残差就该
    很小; 差得多说明示教点与 CAD 不同源, 那么单件那几条"没有 CAD 可比"的路线也不能信。
    """
    rows = [
        (spec.clip_name, item)
        for spec, clip, _path in written
        for item in (clip.get("compiled", {}).get("dockResiduals") or [])
    ]
    if not rows:
        print("dock 残差: 无(未提供 GLB 场景, 片段按纯换父落位)")
        return
    worst_pos = max(rows, key=lambda row: row[1]["position_mm"])
    worst_align = max(rows, key=lambda row: row[1]["alignment_mm"])
    print(f"dock 残差 {len(rows)} 条: "
          f"校正后位置最大 {worst_pos[1]['position_mm']:.4f} mm; "
          f"示教↔CAD 平移残差最大 {worst_align[1]['alignment_mm']:.2f} mm ({worst_align[0]})")
    limit = 0.5
    bad = [row for row in rows if not row[1]["position_mm"] <= limit]
    if bad:
        for name, item in bad[:8]:
            print(f"  超差 {item['position_mm']:.3f} mm  {item['payload']:<22} {name}")
        raise SystemExit(f"落位几何门禁失败: {len(bad)} 条超过 {limit} mm")
    for name, item in sorted(rows, key=lambda row: -row[1]["alignment_mm"])[:4]:
        print(f"  示教↔CAD {item['alignment_mm']:7.2f} mm  {item['payload']:<22} {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 PTLC 机器人点表和 operation 到三维模块")
    parser.add_argument("--control-root", help="覆盖 PTLC_CONTROL_ROOT")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--tool-id",
        type=int,
        default=2,
        choices=(1, 2, 3),
        help="样板工具；当前 CAD 可生成 2=大夹爪或 3=小夹爪，1=吸盘缺少模型会拒绝生成",
    )
    parser.add_argument(
        "--transfers",
        action="store_true",
        help="同时生成整板转移片段矩阵(4 条路线 × 6 个库位)并刷新 clips/index.json",
    )
    parser.add_argument(
        "--plates",
        action="store_true",
        help="同时生成薄层板搬运片段(料仓/点样座/刮板台/废板仓 7 条 + 8 缸进出 16 条)",
    )
    parser.add_argument(
        "--flows",
        action="store_true",
        help="自动发现 config/operation 里的全部流程并逐条编译, 产出 clips/flow-index.json",
    )
    parser.add_argument(
        "--only",
        default="",
        metavar="GLOB",
        help="只编片段名匹配该 glob 的流程(如 'flow.transfer_*'), 且不重写 flow-index.json。"
             "全量 --flows 约 20 分钟而单条 5~9 秒, 迭代期用它; 收工前必须再跑一次全量",
    )
    parser.add_argument(
        "--inputs",
        default="",
        metavar="JSON",
        help='点名覆盖某条流程的入参, 形如 \'{"collect_execute": {"solvent_volume_ml": 5}}\'。'
             "被点名的入参退出变体扇出, 但仍进片段名后缀 —— 于是产出的是货架上多出来的一条, "
             "不会顶掉正式片段。演示页的\"按这组入参编这一条\"走它",
    )
    args = parser.parse_args()
    if args.only and not args.flows:
        raise SystemExit("--only 只对 --flows 生效(--transfers/--plates 是硬编码路线, 本就只有几十条)")
    # 带 override 跑全量 = 两百条片段里混进一条参数不同的, 而 flow-index 不会记录这件事。
    # 与上面那条同一个理由: 宁可拒绝, 也不产出一个没人说得清来历的产物。
    if args.inputs and not args.only:
        raise SystemExit("--inputs 必须与 --only 配套(不然全量产物里会混进一条来历不明的片段)")
    try:
        flow_overrides = json.loads(args.inputs) if args.inputs else {}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--inputs 不是合法 JSON: {exc}") from exc
    if not isinstance(flow_overrides, dict) or not all(
            isinstance(value, dict) for value in flow_overrides.values()):
        raise SystemExit('--inputs 应形如 {"<流程名>": {"<入参名>": <值>}}')

    root = _control_root(args.control_root)
    output = Path(args.output).resolve()
    calibration = load_calibration()
    registry = _load_registry(root)
    if registry.source_sha256 != calibration["reference_points"]["sha256"]:
        raise SystemExit(
            "点表 SHA 与标定文件不一致；请先运行 calibrate_cr5.py --write，拒绝生成过期动画"
        )

    generated_dir = output / "generated"
    clip_dir = output / "clips"
    generated_dir.mkdir(parents=True, exist_ok=True)
    clip_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "robot-points.json").write_text(
        json.dumps(_catalog(registry, calibration), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    targets = {
        "robot_tool_pick": clip_dir / "robot.tool_pickup.yaml",
        "robot_tool_put": clip_dir / "robot.tool_return.yaml",
    }
    # 机构起手态要读 manifest(见 _mechanism_home_block)。缺 manifest 时退化为不写 home
    # 机构段 —— 这两条片段本来就能在没有 manifest 的机器上生成。
    tool_manifest_path = ROOT / "models" / "device-manifest.official-cr5.json"
    tool_manifest = (json.loads(tool_manifest_path.read_text(encoding="utf-8"))
                     if tool_manifest_path.is_file() else None)
    for operation, path in targets.items():
        clip = _compile_operation(root, registry, calibration, operation,
                                  tool_id=args.tool_id, manifest=tool_manifest)
        path.write_text(yaml.safe_dump(clip, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"generated {path.relative_to(output)} ({len(clip['steps'])} steps)")

    if args.transfers:
        _write_transfer_clips(root, registry, calibration, output, clip_dir)
    if args.plates:
        _write_plate_clips(root, registry, calibration, output, clip_dir)
    if args.flows:
        _write_flow_clips(root, registry, calibration, output, clip_dir, only=args.only,
                          overrides=flow_overrides)

    # 映射表随每次同步刷新: 它是前端即时近似展开的唯一真源, 落后于 Python 侧就会让
    # 演示栏播出与实机对不上的运动。
    _write_motion_map(generated_dir, output)

    print(f"referencePointHash={registry.source_sha256}")


def _plate_seat_summary(scene, manifest: dict, registry, rail_slots: dict[int, float],
                        root: Path) -> str:
    """一行话概括各站板落点残差(不拦生成)。判据实现在 verify_plate_seats, 这里只取结果。

    延迟 import 是因为 verify_plate_seats 反过来要用本模块的 ROOT/_load_registry ——
    放在函数里, 调用时本模块已加载完毕, 不成环。
    """
    import verify_plate_seats  # pylint: disable=import-outside-toplevel
    from scene_kinematics import RobotPosture  # pylint: disable=import-outside-toplevel

    # 必须把板托座所骑的工位轴一起摆到位: 不摆的话量出来的是"CAD 建模位 vs 机器人真实位"
    # 那个假差(此前 7Y 99mm / 8Y 35mm 就是它), 与本摘要要报的"落点残差"完全是两回事。
    seats = verify_plate_seats.seat_deviations(
        scene, RobotPosture(scene, manifest), registry, rail_slots,
        verify_plate_seats.seat_axes_mm(root))
    if not seats:
        return ""
    worst = max(seats, key=lambda slot: seats[slot]["deviation"])
    worst_mm = seats[worst]["deviation"]
    if worst_mm <= verify_plate_seats.SEAT_TOLERANCE_MM:
        return ""
    # 措辞不要写死成"轴没被驱动": 2026-08-05 起点样座 7Y 用的是实机 OPC 实读值(56.0),
    # 轴是被驱动的, 剩下的 41mm 是 **CAD 落点 vs 实机示教值** 的账 —— 两种成因的修法完全
    # 不同(一个补驱动, 一个要现场卷尺), 混为一谈会把人引到错的方向。
    return (f"板落点残差: 最大 {worst} 偏离刀具几何基准 {worst_mm:.0f}mm "
            f"—— 或是该站工位轴没被驱动, 或是 CAD 落点与实机示教值本就对不上"
            f"(详情跑 verify_plate_seats.py)")


def _gate_staging_numbering(scene, manifest, registry, rail_slots) -> None:
    """中转/货架孔位编号自洽性硬门禁: 不过就拒绝生成任何片段。

    这错画出来看着完全正常(爪合在正确的孔位上, 只是耗材画在别的孔) —— 与展缸编号
    同一类"没有指标会报警"的缺陷, 只能在源头拦。与展缸门禁(只跳过缸片段)不同, 这里
    **硬停**: 孔件贯穿 flows/plates/transfers 三族, 跳过集靠不住。几何链没动时它恒绿,
    平时零成本; 触发即说明 blender_clean 的孔序(rig_map consumables.holeOrder)与
    机器人点表又对不上了。判据与实测定案过程见 verify_staging_numbering.py 头注。
    """
    from verify_staging_numbering import verify_staging_pairing  # 局部导入: 该模块反向 import 本模块

    problems = verify_staging_pairing(
        scene, clip_compiler.RobotPosture(scene, manifest), registry, rail_slots)
    if problems:
        print("[!] 中转/货架孔位编号自洽性检查未通过, 拒绝生成片段:")
        for problem in problems:
            print(f"    {problem}")
        raise SystemExit(
            "孔位编号错位时生成的片段会把耗材画进错的孔(观感=夹空气) —— "
            "跑 verify_staging_numbering.py --report 对照置换表, 修 rig_map 的 "
            "consumables.holeOrder 或几何后重跑")


def _write_plate_clips(root: Path, registry, calibration: dict, output: Path, clip_dir: Path) -> None:
    """生成薄层板搬运片段并把它们登记进 clips/index.json。

    与整板转移一样是**离线预生成**: move_l 要跑 least_squares IK, 放到运行期按需编译
    会让首播等上数十秒。
    """
    manifest_path = ROOT / "models" / "device-manifest.official-cr5.json"
    if not manifest_path.is_file():
        raise SystemExit(f"缺少 device-manifest: {manifest_path}(先跑 gen_twin_manifest.py)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rail_slots = clip_compiler.load_rail_slots(root)
    scene = clip_compiler.GlbScene(ROOT / "models" / "machine.official-cr5.glb")
    _gate_staging_numbering(scene, manifest, registry, rail_slots)

    # 轴起手声明覆盖面: 只报不拦(机构侧的 mechanism_home_of 是硬门禁模板, 轴侧大多数
    # 隐式 0 恰是 PLC 回零目标, 硬拦会逼着为 4X/3Y/5Z/6X 编造出处)。停放位非 0 的轴
    # 一旦新增而没进 STATION_AXIS_HOME, 症状与 2026-08-06 的刮板 9X 一样: 片段里停在
    # CAD 基位/0, 画面看着正常, 没有指标报警 —— 靠这行提示进人审。
    covered_axes = {"axis_11y", *clip_compiler.STATION_AXIS_HOME,
                    *(spec[0] for spec in clip_compiler.SEAT_AXES.values())}
    uncovered_axes = [axis.get("id") for axis in manifest.get("axes") or []
                      if axis.get("rigged") and axis.get("id") not in covered_axes]
    if uncovered_axes:
        print(f"[i] 无起手声明的 rigged 轴(隐式 0): {sorted(uncovered_axes)} "
              f"—— 若其 PLC 停放位非 0, 要补进 clip_compiler.STATION_AXIS_HOME")

    # 展缸编号自洽性: 不过就**不生成任何缸片段**。板落进错的缸画出来看着完全正常
    # (板稳稳落座、缸盖照开), 没有任何自动指标会报警 —— 这种错只能在源头拦。
    tank_problems = clip_compiler.verify_tank_pairing(
        scene, clip_compiler.RobotPosture(scene, manifest), registry, rail_slots[5])
    if tank_problems:
        print("[!] 展缸编号自洽性检查未通过, 已跳过全部展缸片段:")
        for problem in tank_problems:
            print(f"    {problem}")
        print("    机器人点表 P11..P18 = 1..8 号展开缸(现场示教); 三维 TANK_1..8 由 "
              "rig_map.tanks.order_by=[rack, z_desc] 架内自上而下编号。")
        print("    实测改按架内颠倒配对后, 8 个缸的偏置齐平在 +135.8~136.4mm(法兰在板上方, "
              "与展缸取放 rotary-down 持板朝下吻合)。")
        print("    现场核对实物后改 rig_map 的 z_desc↔z_asc 并全链重跑; "
              "该改动同时影响缸盖 dev_t*_cyl*、Tank_State 显示与液面, 故不自动改。")

    # 板落点残差: 只报不拦。与展缸编号那条的区别在于**这种错是看得见的**(板明显飘在
    # 吸盘外面), 不属于"画出来看着很真却是错的"那一类, 所以不该为它拒发片段。
    # 等工位轴标定+驱动补齐、verify_plate_seats 转绿之后, 可以把它提升成硬门禁。
    seat_note = _plate_seat_summary(scene, manifest, registry, rail_slots, root)
    if seat_note:
        print(f"[i] {seat_note}(详情跑 verify_plate_seats.py)")

    # 载荷几何参考帧: 与 _write_transfer_clips / _write_flow_clips 读同一份(见那两处的说明)
    frames_path = ROOT / "generated" / "payload-poses.json"
    if not frames_path.is_file():
        raise SystemExit(f"缺少载荷几何参考帧: {frames_path}(先跑 export_payload_poses.py)")
    payload_frames = json.loads(frames_path.read_text(encoding="utf-8"))["poses"]

    written = []
    failed = []
    for spec in clip_compiler.plate_route_specs():
        if tank_problems and ("tank" in spec.clip_name or "develop" in spec.clip_name):
            continue
        try:
            clip = clip_compiler.compile_plate_route(
                spec, control_root=root, registry=registry, calibration=calibration,
                manifest=manifest, rail_slots=rail_slots, scene=scene,
                payload_frames=payload_frames,
            )
        except (clip_compiler.CompileError, ValueError) as exc:
            # 编译期的每一处不确定性都要浮出来, 不静默跳过 —— 但一条路线编不出来
            # 不该拖垮其它 22 条, 所以收集起来最后统一报。
            # ValueError 主要来自 robot_kinematics.solve_ik 的残差门禁: 那是"这个示教点
            # 用当前标定反解不出足够精确的关节角", 属于真实的标定/点位问题, 只能如实报,
            # 绝不能放宽门禁把不准的关节角混进片段。
            failed.append((spec.clip_name, str(exc)))
            continue
        path = clip_dir / f"{spec.clip_name}.yaml"
        path.write_text(yaml.safe_dump(clip, allow_unicode=True, sort_keys=False), encoding="utf-8")
        written.append((spec, clip, path))

    for spec, clip, path in written:
        print(f"generated {path.relative_to(output)} ({len(clip['steps'])} steps)")
    print(f"generated {len(written)} 个薄层板片段")
    if failed:
        # 不用 ⚠ 之类的符号: Windows 控制台默认 GBK, 非 GBK 字符会让整个脚本在
        # "只是想打印一条警告"的地方崩掉(实测 UnicodeEncodeError)。
        print(f"[!] {len(failed)} 条路线未能编译:")
        for name, reason in failed:
            print(f"    {name}: {reason}")

    index_path = clip_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
    keep = [item for item in index.get("clips", []) if not item["name"].startswith("plate.")]
    keep.extend({
        "name": spec.clip_name,
        "label": spec.label,
        "url": f"/clips/{spec.clip_name}.yaml",
    } for spec, _clip, _path in written)
    # 族按**实际产出**过滤: 展缸族在编号自洽性检查没过时整批不生成, 这时候还把下拉框
    # 摆出来, 用户点一下只会得到"装载失败"。
    families = _clip_families({path.stem for path in clip_dir.glob("*.yaml")})
    index_path.write_text(json.dumps({
        "schema": "ptlc.clip-index/v2",
        "clips": keep,
        "families": families,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"refreshed {index_path.relative_to(output)} (clips={len(keep)}, families={len(families)})")


def _write_motion_map(generated_dir: Path, output: Path) -> None:
    """导出"动作 -> 三维机构"映射表, 供前端即时近似展开读取。"""
    path = generated_dir / "action-motion-map.json"
    path.write_text(
        json.dumps(clip_compiler.motion_map_document(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"generated {path.relative_to(output)}")


def _merge_flow_index(clip_dir: Path, entries: dict[str, dict], written: set[str], *,
                      adhoc: bool) -> None:
    """把 --only 这一轮**真正写盘的**片段 merge 进现有 flow-index.json, 其余条目原样落回。

    ⚠ 必须按 `written` 过滤, 不能拿 `entry["clips"]` 当"本轮编到的": 那张表是从 presets
    (12 条硬编码路线覆盖的流程)播种的, 它们**一进来就带着 44 条 clips**。不过滤的后果是
    --only 一条流程却 merge 了 44 条, 还给那 44 条统统打上 adhoc 标 —— 演示栏会把一批
    正式片段显示成"临时, 下次全量重编会消失"。

    ⚠ **绝不碰索引级的 railCalib 与 referencePointHash。** 它们的语义是"这一批片段共用的
    标定指纹", 而 --only 只重编了 1/200 —— 顺手刷新就等于替另外 199 条声明"我们也是新标定
    编的"。而 DemoView 的 clipStale 正读它, 那会把唯一的陈旧提示变成一个说谎的绿灯。
    代价如实: 新编的临时片段自身是新标定编的, 但索引级指纹仍是旧的, 徽章可能仍显示待重编译
    —— 那是**保守方向**的偏差, 可接受。

    参数:
        clip_dir: clips 目录; entries: 本轮的 {operation: 条目};
        adhoc: 本轮是不是点名覆盖入参编出来的临时片段(是则给 clip 打 adhoc 标, 供前端标注
            "下次全量重编会消失")
    返回: None
    """
    index_path = clip_dir / "flow-index.json"
    if not index_path.is_file():
        print("    (没有现成的 flow-index.json, 跳过 merge —— 先跑一次全量 --flows)")
        return
    doc = json.loads(index_path.read_text(encoding="utf-8"))
    by_name = {item["name"]: item for item in (doc.get("flows") or [])}

    merged = 0
    for name, entry in entries.items():
        fresh = [clip for clip in (entry.get("clips") or [])
                 if clip.get("clipName") in written]
        if not fresh:
            continue                       # 本轮没编出片段的条目不动(失败留痕靠控制台)
        target = by_name.get(name)
        if target is None:
            # 索引里没有这条流程(它此前是 hidden/failed/从没编过): 整条插进去, 但 clips
            # 只放本轮真编出来的那几条, 状态也只由本轮的事实决定
            target = {k: v for k, v in entry.items() if k not in ("failures", "clips")}
            target["clips"] = []
            target["status"] = "ok"
            doc.setdefault("flows", []).append(target)
            by_name[name] = target
        clips = target.setdefault("clips", [])
        for clip in fresh:
            if adhoc:
                clip = {**clip, "adhoc": True}
            hit = next((i for i, old in enumerate(clips)
                        if old.get("clipName") == clip["clipName"]), -1)
            if hit >= 0:
                clips[hit] = clip
            else:
                clips.append(clip)
            merged += 1
        target["status"] = "ok"
        target.pop("reason", None)

    doc["flows"] = sorted(doc.get("flows") or [],
                          key=lambda item: (item.get("group", ""), item["name"]))
    index_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"    flow-index.json: merge 了 {merged} 条片段"
          f"{'(标 adhoc)' if adhoc else ''}, railCalib 未动")


def _write_flow_clips(root: Path, registry, calibration: dict, output: Path, clip_dir: Path,
                      only: str = "", overrides: dict | None = None) -> None:
    """自动发现全部流程并逐条编译, 产出片段与 flow-index.json。

    Args:
        only: 片段名 glob(如 `flow.transfer_*`); 非空时只编匹配的那些, 且**不整体重写
            flow-index.json**(只把编到的那几条 merge 回去) —— 那份索引是全量视图, 用一次
            筛过的结果覆盖它会把没编的流程抹成缺失, 演示栏立刻少掉大半。全量约 20 分钟
            而单条 5~9 秒, 迭代期靠它把一轮验证从"泡一杯茶"压到"眨个眼"。
        overrides: 点名覆盖入参 {流程名: {入参名: 值}}, 透传给 discover_flow_specs。
            必须与 only 配套(main 里已拦), 产出的是带后缀的临时片段。

    ⚠ 与本管线其它入口不同, 这里**单条失败不中断全局**。

    编译器的第二条纪律是"运行期看到的每一处近似都要在编译期就失败", 而那条纪律约束的是
    **单个片段的内容** —— 它仍然成立: compile_plate_route 该 raise 照旧 raise, 一条编不出来
    的流程绝不会被降格成一个内容可疑的片段落盘。

    这里放宽的是**驱动层的整体退出行为**。理由是可证伪的: 101 个流程里大多含
    assign/human/while/for/try, 编译器对这些直接 CompileError; 若整体退出, 产出为零,
    连本来能编出来的那几条也拿不到。逐条记录失败原因比"全体退出并只报第一条"更可行动 ——
    flow-index.json 里每条都带 status 与 reason, 演示栏据此逐条显示为何播不了。
    """
    manifest_path = ROOT / "models" / "device-manifest.official-cr5.json"
    if not manifest_path.is_file():
        raise SystemExit(f"缺少 device-manifest: {manifest_path}(先跑 gen_twin_manifest.py)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rail_slots = clip_compiler.load_rail_slots(root)
    scene = clip_compiler.GlbScene(ROOT / "models" / "machine.official-cr5.glb")
    _gate_staging_numbering(scene, manifest, registry, rail_slots)
    # 载荷几何参考帧: 与 _write_transfer_clips 读同一份。缺了它 _align_to_cad 会原样返回,
    # 落位与 CAD 差 6~23mm, 落位后的实例交换肉眼可见地跳一下。
    frames_path = ROOT / "generated" / "payload-poses.json"
    if not frames_path.is_file():
        raise SystemExit(f"缺少载荷几何参考帧: {frames_path}(先跑 export_payload_poses.py)")
    payload_frames = json.loads(frames_path.read_text(encoding="utf-8"))["poses"]

    specs, presets = flow_discovery.discover_flow_specs(
        root, Path(__file__).resolve().parent, overrides=overrides)

    # 索引按 **operation** 组织, 一条流程一个条目 —— 演示栏的左栏就是按流程列的,
    # 一个流程展开成 8 个缸号变体时, 那是条目内部的下拉框, 不是 8 行。
    entries: dict[str, dict] = {item["name"]: item for item in presets}
    clips_written = 0
    # 本轮真正写盘的片段名 —— merge 索引时靠它区分"本轮编的"与"presets 一进来就带的"
    written_names: set[str] = set()
    if only:
        kept = [spec for spec in specs if fnmatch.fnmatch(spec.clip_name, only)]
        if not kept:
            raise SystemExit(
                f"--only {only!r} 一条流程都没匹配上 —— 片段名形如 flow.<operation>[.<变体>]; "
                f"现有 {len(specs)} 条, 例: {', '.join(s.clip_name for s in specs[:3])}")
        print(f"--only {only}: {len(kept)}/{len(specs)} 条流程, 且**不重写 flow-index.json**")
        specs = kept
    for spec in specs:
        entry = entries.setdefault(spec.operation, {
            "name": spec.operation,
            "label": spec.label.split(" · ")[0],
            "group": spec.group,
            "role": spec.role,
            "clips": [],
            "failures": [],
        })
        try:
            clip = clip_compiler.compile_plate_route(
                flow_discovery.to_transfer_spec(spec),
                control_root=root, registry=registry, calibration=calibration,
                manifest=manifest, rail_slots=rail_slots, scene=scene,
                payload_frames=payload_frames,
            )
        except Exception as exc:  # noqa: BLE001 —— 逐条留痕正是本函数存在的理由
            entry["failures"].append({
                "clipName": spec.clip_name,
                "variant": spec.variant,
                "reason": f"{type(exc).__name__}: {exc}",
            })
            continue

        moving = flow_discovery.motion_step_count(clip)
        if moving == 0:
            # 编出来了但一步机构都不动: 这是"该流程无机械动作"的**编译期证据**,
            # 不是前端猜的。片段本身不落盘 —— 播一个零运动的片段只会让人以为坏了。
            entry["motionStepCount"] = 0
            continue

        path = clip_dir / f"{spec.clip_name}.yaml"
        path.write_text(yaml.safe_dump(clip, allow_unicode=True, sort_keys=False), encoding="utf-8")
        entry["clips"].append({
            "clipName": spec.clip_name,
            "label": spec.label,
            "variant": spec.variant,
            "url": f"/clips/{spec.clip_name}.yaml",
            "stepCount": len(clip.get("steps") or []),
            "motionStepCount": moving,
        })
        written_names.add(spec.clip_name)
        clips_written += 1

    if only:
        # 索引是全量视图, 用筛过的结果**整体覆盖**它等于把没编的流程抹成缺失。但"全有或
        # 全无"之外还有第三条: 读回现有索引, 只把这一轮编到的那几条 merge 回去。
        # 不 merge 的后果很具体: 演示页靠 flow-index 列变体下拉, 新编的临时片段落了盘却
        # 没人看得见, 用户点完"按这组入参编这一条"等了二十秒, 画面纹丝不动。
        _merge_flow_index(clip_dir, entries, written_names, adhoc=bool(overrides))
        print(f"--only 模式: 已写 {clips_written} 个片段, flow-index.json 只 merge 了这几条")
        return

    # 定状态: 有片段=ok; 无片段但编出来过零运动=no-motion; 否则 failed 并带首条原因
    for entry in entries.values():
        if entry.get("status") == "ok":
            continue                      # 硬编码路线覆盖的, 状态已定
        if entry.get("clips"):
            entry["status"] = "ok"
            entry.setdefault("reason", "")
        elif entry.get("motionStepCount") == 0:
            entry["status"] = "no-motion"
            entry["reason"] = "全部步骤都不驱动机构(只读/账本/等待)"
        elif entry.get("failures"):
            entry["status"] = "failed"
            entry["reason"] = entry["failures"][0]["reason"]

    ordered = sorted(entries.values(), key=lambda item: (item.get("group", ""), item["name"]))
    index_path = clip_dir / "flow-index.json"
    # 地轨标定指纹随索引一起出: 演示栏据此逐条判陈旧, 不必为了判一个徽章去拉一百个片段.
    # 一次运行里全部片段共用同一份 manifest, 所以是索引级的单值而非逐条.
    try:
        rail_calib = clip_compiler.RobotPosture(scene, manifest).rail_fingerprint()
    except Exception as exc:  # noqa: BLE001 —— 指纹取不到不该拖垮整条编译
        rail_calib = None
        print(f"警告: 地轨标定指纹取不到({exc}), flow-index 将不带 railCalib")
    index_path.write_text(json.dumps({
        "schema": "ptlc.flow-index/v1",
        "referencePointHash": registry.source_sha256,
        "railCalib": rail_calib,
        "flows": ordered,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tally = collections.Counter(item.get("status", "?") for item in ordered)
    print(f"generated {index_path.relative_to(output)}: {len(ordered)} 条流程, "
          f"{clips_written} 个片段落盘 —— "
          + " / ".join(f"{status} {count}" for status, count in sorted(tally.items())))
    failed = [item for item in ordered if item.get("status") == "failed"]
    for item in failed[:8]:
        print(f"    [failed] {item['name']}: {item['reason']}")
    if len(failed) > 8:
        print(f"    ... 另有 {len(failed) - 8} 条, 详见 {index_path.name}")


def _write_transfer_clips(root: Path, registry, calibration: dict, output: Path, clip_dir: Path) -> None:
    """生成整板转移片段矩阵(4 条路线 × 6 个库位)并刷新片段索引。

    片段是**离线预生成**的: move_l 要跑 least_squares IK, 放到运行期按需编译会让首播
    等上数十秒。预生成后浏览器只做插值, 零运行时依赖。
    """
    manifest_path = ROOT / "models" / "device-manifest.official-cr5.json"
    if not manifest_path.is_file():
        raise SystemExit(f"缺少 device-manifest: {manifest_path}(先跑 gen_twin_manifest.py)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rail_slots = clip_compiler.load_rail_slots(root)
    scene = clip_compiler.GlbScene(ROOT / "models" / "machine.official-cr5.glb")
    _gate_staging_numbering(scene, manifest, registry, rail_slots)
    frames_path = ROOT / "generated" / "payload-poses.json"
    if not frames_path.is_file():
        raise SystemExit(f"缺少载荷几何参考帧: {frames_path}(先跑 export_payload_poses.py)")
    payload_frames = json.loads(frames_path.read_text(encoding="utf-8"))["poses"]

    specs = clip_compiler.tray_transfer_specs(manifest)
    written = []
    for spec in specs:
        clip = clip_compiler.compile_transfer(
            spec, control_root=root, registry=registry, calibration=calibration,
            manifest=manifest, rail_slots=rail_slots, scene=scene,
            payload_frames=payload_frames,
        )
        path = clip_dir / f"{spec.clip_name}.yaml"
        path.write_text(yaml.safe_dump(clip, allow_unicode=True, sort_keys=False), encoding="utf-8")
        written.append((spec, clip, path))
    for spec, clip, path in written[:2]:
        print(f"generated {path.relative_to(output)} ({len(clip['steps'])} steps)")
    print(f"generated {len(written)} 个转移片段(整板 4 路线 × 6 库位)")
    _report_dock_residuals(written)

    index_path = clip_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
    singles = [item for item in index.get("clips", []) if not item["name"].startswith("transfer.")]
    families = _clip_families({path.stem for path in clip_dir.glob("*.yaml")})
    index_path.write_text(json.dumps({
        "schema": "ptlc.clip-index/v2",
        "clips": singles,
        "families": families,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"refreshed {index_path.relative_to(output)} (families={len(families)})")


def _clip_families(available: set[str] | None = None) -> list[dict]:
    """片段族描述: 动画界面据此渲染下拉框, 再按 nameTemplate 拼出片段名。

    这样"转移目标可选"就不需要前端硬编码任何路线知识 —— 加一条路线只改生成器。

    ``available`` 给了就只保留**片段真的生成出来了**的族: 展缸族在编号自洽性检查没过时
    整批不生成, 这时候还把下拉框摆出来, 用户点一下只会得到"装载失败"。

    Args:
        available: 已生成的片段名集合; None 表示不过滤

    Returns:
        族描述列表
    """
    families = [{
        "id": "transfer.tray",
        "label": "托盘转移(整板)",
        "hint": "大夹爪整板搬运; 货架 12 库位 ↔ 中转托盘位 A/B",
        "nameTemplate": "transfer.tray.{kind}.{direction}.slot{slot}",
        "params": [
            {"key": "kind", "label": "托盘种类", "options": [
                {"value": "collector", "label": "粉末收集器组"},
                {"value": "bottle", "label": "样品瓶组"},
            ]},
            {"key": "direction", "label": "转移方向", "options": [
                {"value": "to_staging", "label": "货架 → 中转位"},
                {"value": "to_rack", "label": "中转位 → 货架"},
            ]},
            {"key": "slot", "label": "货架库位", "range": [1, 6]},
        ],
    }, {
        "id": "plate.develop",
        "label": "展开工位(选缸)",
        "hint": "机器人持板进出 8 个展缸; 含缸盖开合与地轨就位",
        "nameTemplate": "plate.flow.develop_{phase}.tank{tank}",
        "params": [
            {"key": "phase", "label": "阶段", "options": [
                {"value": "load", "label": "上料(板入缸)"},
                {"value": "unload", "label": "下料(板出缸)"},
            ]},
            {"key": "tank", "label": "展缸号", "range": [1, 8]},
        ],
    }, {
        "id": "plate.tank",
        "label": "展缸取放(单动作)",
        "hint": "只有机械臂进出缸这一段, 不含缸盖与地轨",
        "nameTemplate": "plate.tank{tank}_{direction}",
        "params": [
            {"key": "direction", "label": "方向", "options": [
                {"value": "put", "label": "放板入缸"},
                {"value": "pick", "label": "取板出缸"},
            ]},
            {"key": "tank", "label": "展缸号", "range": [1, 8]},
        ],
    }]
    if available is None:
        return families
    kept = []
    for family in families:
        head = str(family["nameTemplate"]).split("{", 1)[0]
        if any(name.startswith(head) for name in available):
            kept.append(family)
    return kept


if __name__ == "__main__":
    main()
