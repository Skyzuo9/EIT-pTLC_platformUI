"""吸盘真空的数字孪生机构态 — 离线测试。

背景: 末端四个语义动作里, 夹爪开合与吸盘上下翻转早就进了 `mechanism_state`(供三维
显示), 唯独**吸盘真空 (DO3) 没有**。缺了它, 三维在页面刷新后就无从得知"吸盘还带着
电、手上还吸着一块薄层板" —— 流程事件包络刷新即丢, 只有这一位能跨刷新恢复。

本文件锁住四件事:
  1. SUCTION_ON/OFF 落到 `rob_suction`, 且布尔语义与 DO3 电平一致 (on=True);
  2. 非 1 号刀 (吸盘) 挂载时, 吸盘动作不污染任何机构缓存;
  3. `mechanism_snapshot()` 在 1 号刀下同时给出翻转气缸与真空两条;
  4. **吸盘没有真空 DI, 必须如实报 `confirmed=None` / `source="commanded"`** ——
     绝不能因为"命令发下去了"就伪造成 confirmed, 那会让三维把估计态显示成确认态。
     (`driver/robot_transport.py::_TOOL_DI_TARGET` 里没有 SUCTION 条目即此。)

运行: & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_twin_suction_state_offline.py -q
"""

from __future__ import annotations

from pathlib import Path

from eit_ptlc.controller.point_registry import PointRegistry
from eit_ptlc.controller.robot_controller import RobotController
from eit_ptlc.driver.robot_sim import SimRobotTransport
from eit_ptlc.driver.robot_transport import MountedTool, ToolAction

_CFG = Path(__file__).resolve().parents[1] / "config"


def _make(tool: MountedTool) -> tuple[RobotController, SimRobotTransport]:
    """真实点表 + 仿真传输的控制器; 仿真传输不做工具门控, 正好用来验控制器自己那道语义关。"""
    registry = PointRegistry.load(
        _CFG / "points" / "robot" / "robot_points.json",
        source_version="v0.11",
        meta_path=_CFG / "points" / "robot" / "robot_points_meta.json",
    )
    transport = SimRobotTransport()
    transport.set_mounted_tool(tool)
    ctrl = RobotController(transport, registry, home_point="robot-main.home",
                           jog_speed_percent=20, step_distance_mm=1.0, step_angle_deg=1.0)
    return ctrl, transport


def test_suction_on_off_落到_rob_suction_且布尔语义与_do3_一致():
    ctrl, _ = _make(MountedTool.SLOT1)

    ctrl.tool_action(ToolAction.SUCTION_ON)
    snap = ctrl.mechanism_snapshot()
    assert snap["rob_suction"]["commanded"] is True

    ctrl.tool_action(ToolAction.SUCTION_OFF)
    snap = ctrl.mechanism_snapshot()
    assert snap["rob_suction"]["commanded"] is False


def test_无真空di_必须报_commanded_而不是伪造_confirmed():
    ctrl, _ = _make(MountedTool.SLOT1)
    ctrl.tool_action(ToolAction.SUCTION_ON)
    entry = ctrl.mechanism_snapshot()["rob_suction"]

    assert entry["confirmed"] is None, "吸盘没有真空 DI, 不得声称已确认到位"
    assert entry["source"] == "commanded"
    assert entry["available"] is True


def test_一号刀下同时给出翻转气缸与真空两条():
    ctrl, _ = _make(MountedTool.SLOT1)
    ctrl.tool_action(ToolAction.ROTARY_UP)
    ctrl.tool_action(ToolAction.SUCTION_ON)

    snap = ctrl.mechanism_snapshot()
    assert set(snap) == {"rob_flip_suction", "rob_suction"}
    assert snap["rob_flip_suction"]["commanded"] is True


def test_非一号刀时吸盘动作不落到任何机构():
    for tool in (MountedTool.NONE, MountedTool.SLOT2, MountedTool.SLOT3):
        ctrl, _ = _make(tool)
        ctrl.tool_action(ToolAction.SUCTION_ON)
        snap = ctrl.mechanism_snapshot()
        assert "rob_suction" not in snap, f"{tool!r} 挂载下不该产出吸盘机构态"


def test_夹爪动作不会被吸盘分支截走():
    """SUCTION 分支插在 ROTARY 与 GRIPPER 之间, 别把夹爪路由坏了。"""
    ctrl, _ = _make(MountedTool.SLOT2)
    ctrl.tool_action(ToolAction.GRIPPER_CLOSE)
    snap = ctrl.mechanism_snapshot()
    assert snap["rob_grip_plate96"]["commanded"] is True
    assert "rob_suction" not in snap


def test_机构id与rig_map目录逐字一致():
    """id 是四份契约(控制器 / rig_map / manifest / 前端)逐字对齐的, 错一个字前端静默不动。"""
    import yaml

    rig_map = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "three_d" / "pipeline" / "rig_map.yaml").read_text(encoding="utf-8")
    )
    catalog_ids = {item["id"] for item in (rig_map.get("mechanisms_catalog") or [])}
    assert RobotController._TWIN_SUCTION_ID in catalog_ids

    actuator_ids = {item["id"] for item in (rig_map.get("actuators") or [])}
    assert RobotController._TWIN_FLIP_ID in actuator_ids
    # 纯状态机构绝不能进 actuators: 那会被 gen_twin_manifest 标成 rigged:true,
    # 变成一个前端永远绑不到几何、每帧告警的幽灵条目。
    assert RobotController._TWIN_SUCTION_ID not in actuator_ids
