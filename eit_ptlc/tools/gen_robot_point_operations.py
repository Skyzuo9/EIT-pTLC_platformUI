#!/usr/bin/env python3
"""机器人点位 operation 生成器 (一次性迁移)
=============================================

╔══════════════════════════════════════════════════════════════════════════╗
║  【冻结·勿运行】(G-1, 2026-06-24 裁定)                                        ║
║  生成的 config/operation/06_robot/*.yaml 现为【手改真源】。                    ║
║  重运行本生成器会【静默抹掉】手插的 tool_action (rotary 等,                    ║
║  自校验 _branch_body 只比对 move 点序列、不校验 tool_action)。                 ║
║  如确需重生成: 须先把全部手改并回模板 (robot_flows_v2.yaml)、                  ║
║  并扩展生成器支持 tool_action 插入, 再运行。                                   ║
╚══════════════════════════════════════════════════════════════════════════╝

功能:
    把 robot_flows_v2.yaml 的每条生产模板 (经可信解析器 RobotPlanCatalog 展开为具体取放路线),
    转写为"点位驱动、可编辑"的 operation 脚本写入 config/operation/06_robot/。
    每条 flow 产出一个参数化 operation: 以 selector(及次选择) 为入参, body 用 if/elif 按取值分支,
    每分支是该取值解析出的显式点位序列 (require_anchor 进锚点 -> move_to_point/tool_action/dwell
    逐步 -> require_anchor 出锚点)。取代运行期 run_flow 模板引擎, 使机械臂动作由点位控制。

设计:
    - 点位序列直接取自 catalog.resolve(template, business).flow.steps, 与旧引擎逐点一致 (生成时自校验)。
    - 运动速度档 (acc/vel/cp) 随 move 步写入 move_to_point 参数, 保留逐步控速。
    - 进/出锚点与容差取自 flow.entry_point/exit_point 与模板 anchor_tolerance。
    - selector 取值类型: 映射键全为数字 -> INT, 否则 STRING; 分支按该类型比较。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tools.gen_robot_point_operations
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402
from eit_ptlc.driver.robot_transport import TOOL_ACTION_NAMES  # noqa: E402
from eit_ptlc.operation.robot_routes.robot_flow import (  # noqa: E402
    MoveStep,
    SetMountedToolStep,
    ToolStep,
    WaitStep,
)
from eit_ptlc.operation.robot_routes.robot_plan import RobotPlanCatalog  # noqa: E402

_PKG_DIR = Path(__file__).resolve().parents[1]               # eit_ptlc/
_OUT_DIR = _PKG_DIR / "config" / "operation" / "06_robot"
# ToolAction 枚举 -> 规范动作名 (供 tool_action 参数; TOOL_ACTION_NAMES 为 名->枚举)
_TOOL_ACTION_REV = {action: name for name, action in TOOL_ACTION_NAMES.items()}


def _op_name(flow_id: str) -> str:
    """flow id (含 . 和 -) 规范化为 operation 名 (下划线)."""
    return "robot_" + flow_id.replace(".", "_").replace("-", "_")


def _var_type(keys: list[str]) -> str:
    """selector 映射键全为数字串 -> INT, 否则 STRING."""
    return "INT" if all(str(k).isdigit() for k in keys) else "STRING"


def _typed_literal(vtype: str, key: str):
    """把映射键字面量转为分支比较用的 VM 字面值 (INT 转 int)."""
    return int(key) if vtype == "INT" else str(key)


def _eq(var_name: str, vtype: str, key: str) -> dict:
    """构造 {var}=={lit} 比较表达式."""
    return {"binop": "==", "left": {"var": var_name}, "right": {"lit": _typed_literal(vtype, key)}}


def _anchor_call(point_id: str, flow) -> dict:
    """构造 require_anchor 调用 (容差取自 flow)."""
    return {"op": "call", "action": "robot.require_anchor",
            "args": {"point_id": {"lit": point_id},
                     "joint_tol_deg": {"lit": flow.anchor_joint_tolerance_deg},
                     "pos_tol_mm": {"lit": flow.anchor_position_tolerance_mm},
                     "rot_tol_deg": {"lit": flow.anchor_rotation_tolerance_deg}},
            "mode": "RUN"}


def _step_call(step) -> dict:
    """把一个具体 flow 步骤转为一个 VM call 节点."""
    if isinstance(step, MoveStep):
        return {"op": "call", "action": "robot.move_to_point",
                "args": {"point_id_or_robot_name": {"lit": step.point},
                         "motion": {"lit": step.motion},
                         "acc": {"lit": step.profile.acc},
                         "vel": {"lit": step.profile.vel},
                         "cp": {"lit": step.profile.cp}},
                "mode": "RUN"}
    if isinstance(step, ToolStep):
        return {"op": "call", "action": "robot.tool_action",
                "args": {"action": {"lit": _TOOL_ACTION_REV[step.action]},
                         "timeout_ms": {"lit": step.timeout_ms}},
                "mode": "RUN"}
    if isinstance(step, WaitStep):
        return {"op": "call", "action": "robot.dwell",
                "args": {"duration_ms": {"lit": step.duration_ms}}, "mode": "RUN"}
    if isinstance(step, SetMountedToolStep):
        return {"op": "call", "action": "robot.set_mounted_tool",
                "args": {"tool_id": {"lit": step.tool_id}}, "mode": "RUN"}
    raise TypeError(f"未知步骤类型: {step!r}")


def _branch_body(flow) -> list[dict]:
    """一个具体路线 -> [进锚点, 逐步, 出锚点] 的 VM 节点序列; 并自校验 move 点序列一致."""
    body = [_anchor_call(flow.entry_point, flow)]
    body.extend(_step_call(s) for s in flow.steps)
    body.append(_anchor_call(flow.exit_point, flow))
    # 自校验: 写出的 move 点序列必须与解析器逐点一致
    emitted_pts = [n["args"]["point_id_or_robot_name"]["lit"]
                   for n in body if n["action"] == "robot.move_to_point"]
    resolved_pts = [s.point for s in flow.steps if isinstance(s, MoveStep)]
    if emitted_pts != resolved_pts:
        raise AssertionError(f"保真校验失败: {flow.flow_id} move 点序列不一致")
    return body


def _enumerate_combos(mapping: dict, has_secondary: bool) -> list[tuple[str, str | None]]:
    """枚举 (主键, 次键|None) 组合 (与 catalog.preflight 同序)."""
    combos: list[tuple[str, str | None]] = []
    for primary, target in mapping.items():
        if has_secondary:
            if not isinstance(target, dict):
                raise ValueError(f"次选择映射缺失: {primary}")
            for secondary in target:
                combos.append((str(primary), str(secondary)))
        else:
            combos.append((str(primary), None))
    return combos


def build_operation(catalog: RobotPlanCatalog, raw: dict, flow_id: str) -> dict:
    """为一条 flow 模板构建参数化点位 operation 文档."""
    tdef = raw["templates"][flow_id]
    selector_param, secondary_param = catalog.selector_params(flow_id)
    mapping = raw["selectors"][tdef["selector"]]
    combos = _enumerate_combos(mapping, secondary_param is not None)

    primary_keys = [c[0] for c in combos]
    primary_type = _var_type(primary_keys)
    secondary_type = _var_type([c[1] for c in combos]) if secondary_param is not None else None

    # 变量声明 (selector 入参)
    variables = [{"name": selector_param, "scope": "local", "type": primary_type, "io": "in",
                  "default": _typed_literal(primary_type, primary_keys[0]),
                  "comment": f"{flow_id} 主选择值"}]
    if secondary_param is not None:
        variables.append({"name": secondary_param, "scope": "local", "type": secondary_type, "io": "in",
                          "default": _typed_literal(secondary_type, combos[0][1]),
                          "comment": f"{flow_id} 次选择值"})

    # 每个组合 -> 一个分支 (cond + 点位序列)
    branches = []
    for primary, secondary in combos:
        business = {selector_param: primary}
        cond = _eq(selector_param, primary_type, primary)
        if secondary_param is not None:
            business[secondary_param] = secondary
            cond = {"binop": "and", "left": cond,
                    "right": _eq(secondary_param, secondary_type, secondary)}
        plan = catalog.resolve(flow_id, business)
        branches.append((cond, _branch_body(plan.flow)))

    if_node = {"op": "if", "cond": branches[0][0], "then": branches[0][1],
               "elifs": [{"cond": c, "body": b} for c, b in branches[1:]],
               "else": [{"op": "raise", "error": "ROBOT_FLOW_SELECTOR",
                         "message": {"lit": f"{flow_id}: 无效选择值"}}]}

    return {"schema": "ptlc.script/v1", "kind": "operation", "name": _op_name(flow_id),
            "label": f"机器人-{flow_id} (点位序列)", "vars": variables,
            "resources": ["robot"], "body": [if_node]}


def main() -> int:
    config = load_config(_PKG_DIR / "config" / "app.yaml")
    registry = PointRegistry.load(config.robot.points_file,
                                  source_version=config.robot.point_source_version,
                                  meta_path=config.robot.points_meta_file)
    flow_source = config.plc.nodes_file.parent / "backup" / "robot_flows_v2.yaml"
    catalog = RobotPlanCatalog.load(flow_source, registry)
    raw = yaml.safe_load(flow_source.read_text(encoding="utf-8"))

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    total_branches = 0
    written = []
    for flow_id in catalog.template_ids:                      # 仅生产模板 (测试模板不导出)
        doc = build_operation(catalog, raw, flow_id)
        n_branches = 1 + len(doc["body"][0]["elifs"])
        total_branches += n_branches
        out_path = _OUT_DIR / f"{doc['name']}.yaml"
        with out_path.open("w", encoding="utf-8") as f:
            f.write(f"# 由 tools/gen_robot_point_operations.py 从 {flow_source.name} 模板 {flow_id} 生成\n")
            f.write("# 点位驱动: 可直接编辑各步点位/速度档; 进/出 require_anchor 为安全门\n")
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False, default_flow_style=None, width=200)
        written.append((doc["name"], n_branches))

    print(f"生成 {len(written)} 个机器人点位 operation, 共 {total_branches} 个 selector 分支, 保真校验通过:")
    for name, n in written:
        print(f"  {name:34} 分支={n}")
    print(f"输出目录: {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
