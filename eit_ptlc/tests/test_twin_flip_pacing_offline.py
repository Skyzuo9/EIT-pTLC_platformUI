"""吸盘翻转的数字孪生配速与空翻抑制 — 离线测试。

背景 (2026-08-05 用户反馈"翻转动画跟实物对不上"), 两个独立病根:

  1. **头段冲太快**: `rig_map` 的 `transitionS: 0.6` 在前端不是时长而是指数缓动的时间
     常数, 于是 0.6s 就扫掉 180° 中的绝大部分, 然后冻住干等 DI。实物一程约 5s。
     这只缸挂在**机器人工具 I/O** 上 (DO2/DO6 + DI1/DI2), 不是 PLC 设备, PLC 点表里
     没有它、更没有速度寄存器 —— 唯一能拿到真速的途径就是量"写完 DO 到限位 DI 置位"
     的时间, 由驱动 `_wait_di_timed` 记录、经 `expectedS` 下发给三维配速 (自校准)。
  2. **空翻**: 流程把 rotary 当状态确认重下 (`robot_suction_pick` 同一次运行发两次
     `rotary-up`), 实物一动不动, 画面却播一整段翻转。

本文件锁住:
  · 已由**真 DI** 确认停在目标位时, 不再公告在途 (画面一帧都不动);
  · 只认真 DI —— `source="commanded"` 的推断态、以及缓存为空 (刷新/换刀/重启) 时,
    一律照常公告。把"假设在该位"误判成"已在该位", 会把一段真实运动从画面上吃掉,
    那比多播一段动画危险得多;
  · 反向命令永远照常公告;
  · `expectedS` 取驱动实测值, 无样本 (如仿真传输) 时省略该键, 前端回退标称值。

运行: & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_twin_flip_pacing_offline.py -q
"""

from __future__ import annotations

from pathlib import Path

from eit_ptlc.controller.point_registry import PointRegistry
from eit_ptlc.controller.robot_controller import RobotController
from eit_ptlc.driver.robot_sim import SimRobotTransport
from eit_ptlc.driver.robot_transport import MountedTool, ToolAction

_CFG = Path(__file__).resolve().parents[1] / "config"
_FLIP = "rob_flip_suction"


def _make(tool: MountedTool = MountedTool.SLOT1) -> tuple[RobotController, SimRobotTransport]:
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


def _seed_confirmed(ctrl: RobotController, *, state: bool, source: str = "feedback") -> None:
    """直接种一条到位缓存, 模拟"上一程已由 DI 确认停在该位"。"""
    ctrl._twin_mech_cache[_FLIP] = {
        "commanded": state,
        "confirmed": state if source == "feedback" else None,
        "available": True,
        "source": source,
        "moving": False,
    }


def test_已由真di确认在该位时_同向复令不再公告在途():
    ctrl, _ = _make()
    _seed_confirmed(ctrl, state=True)          # 已确认停在"上翻"

    rollback = ctrl._announce_twin_motion(ToolAction.ROTARY_UP)

    entry = ctrl._twin_mech_cache[_FLIP]
    assert "moving" not in entry or entry["moving"] is False, "空翻不得公告在途"
    assert entry["confirmed"] is True, "缓存必须原样保留, 三维目标值才不会被挪走"
    assert entry["source"] == "feedback"
    rollback()  # 撤回闭包必须是安全的空操作
    assert ctrl._twin_mech_cache[_FLIP]["confirmed"] is True


def test_反向命令照常公告在途():
    ctrl, _ = _make()
    _seed_confirmed(ctrl, state=True)           # 停在上翻

    ctrl._announce_twin_motion(ToolAction.ROTARY_DOWN)   # 要求下翻 = 真的要动

    entry = ctrl._twin_mech_cache[_FLIP]
    assert entry["moving"] is True
    assert entry["commanded"] is False
    assert entry["confirmed"] is None, "在途不得伪造到位"


def test_只是命令态推断_不算已在该位_照常公告():
    # 页面刷新/换刀/急停后缓存里可能只有命令态, 此刻缸在哪其实并不知道。
    ctrl, _ = _make()
    _seed_confirmed(ctrl, state=True, source="commanded")

    ctrl._announce_twin_motion(ToolAction.ROTARY_UP)

    assert ctrl._twin_mech_cache[_FLIP]["moving"] is True, "推断态不得当作已到位而吞掉动画"


def test_缓存为空时照常公告():
    ctrl, _ = _make()
    ctrl._announce_twin_motion(ToolAction.ROTARY_UP)
    assert ctrl._twin_mech_cache[_FLIP]["moving"] is True


def test_无实测样本时不带expecteds_前端回退标称值():
    # 仿真传输没有 last_tool_stroke_s(鸭子类型探测), 必须省略该键而不是塞 0/None。
    ctrl, _ = _make()
    ctrl._announce_twin_motion(ToolAction.ROTARY_UP)
    assert "expectedS" not in ctrl._twin_mech_cache[_FLIP]


def test_有实测样本时按方向带上expecteds():
    ctrl, transport = _make()

    # 冒充驱动的实测缓存: 上翻 4.8s / 下翻 5.6s(重力方向不同, 两程本就不等速)
    strokes = {ToolAction.ROTARY_UP: 4.8, ToolAction.ROTARY_DOWN: 5.6}
    transport.last_tool_stroke_s = strokes.get      # type: ignore[attr-defined]

    ctrl._announce_twin_motion(ToolAction.ROTARY_UP)
    assert ctrl._twin_mech_cache[_FLIP]["expectedS"] == 4.8

    ctrl._twin_mech_cache.clear()
    ctrl._announce_twin_motion(ToolAction.ROTARY_DOWN)
    assert ctrl._twin_mech_cache[_FLIP]["expectedS"] == 5.6


def test_离谱的实测值不下发():
    # 0.01 是重点: 防御性复令量出来的假样本正是这个量级(一个反馈周期), 它"看起来合法"
    # 却会让前端 speed=span/0.01 一帧走完全程 —— 2026-08-05 上翻瞬移的直接成因。
    # 驱动侧已挡掉"DI 一开始就到位"那一类, 这里是第二道防线。
    ctrl, transport = _make()
    for bogus in (0.0, -1.0, 0.008, 0.05, 0.19, 999.0):
        ctrl._twin_mech_cache.clear()
        transport.last_tool_stroke_s = lambda _a, v=bogus: v   # type: ignore[attr-defined]
        ctrl._announce_twin_motion(ToolAction.ROTARY_UP)
        assert "expectedS" not in ctrl._twin_mech_cache[_FLIP], f"{bogus} 不该被当成行程"


def test_翻转机构开机即发布基准态_让三维先建好插值通道():
    # 若等到第一条命令才首次出现, 前端那一帧才建通道 —— 而通道首见是直跳的,
    # 开机后的第一程会被整段吃掉。基准态必须如实标注是推定而非 DI 确认。
    ctrl, _ = _make(MountedTool.SLOT1)
    assert ctrl._twin_mech_cache == {}, "前提: 还没命令过"

    entry = ctrl.mechanism_snapshot()[_FLIP]
    assert entry["commanded"] is False, "CAD 基准态 = 下翻位"
    assert entry["confirmed"] is None, "没有 DI 证据就不得声称到位"
    assert entry["source"] == "commanded"
    assert "moving" not in entry, "它不在行程中, 缺省即已就位"


def test_基准态不得回填缓存_否则空翻抑制会误判():
    # 缓存是"命令过什么"的账本。若推定值混进去, _twin_already_confirmed_at 会把
    # "假设在该位"当成"已在该位", 于是第一条上翻的动画被整段吃掉 —— 本缺陷的另一条复发路径。
    ctrl, _ = _make(MountedTool.SLOT1)
    ctrl.mechanism_snapshot()
    assert _FLIP not in ctrl._twin_mech_cache, "推定态只进返回值, 不进缓存"

    ctrl._announce_twin_motion(ToolAction.ROTARY_UP)
    assert ctrl._twin_mech_cache[_FLIP]["moving"] is True, "第一条上翻必须照常公告在途"


def test_非一号刀时不得凭空出现翻转条目():
    for tool in (MountedTool.SLOT2, MountedTool.NONE):
        ctrl, _ = _make(tool)
        assert _FLIP not in ctrl.mechanism_snapshot()


def test_夹爪不受空翻抑制影响():
    # 抑制只挂在 _TWIN_INFLIGHT_ACTIONS(只有翻转)上; 夹爪本来就走"到位才公告", 不进这条路。
    ctrl, _ = _make(MountedTool.SLOT2)
    rollback = ctrl._announce_twin_motion(ToolAction.GRIPPER_CLOSE)
    assert ctrl._twin_mech_cache == {}, "非在途名单的动作不得在发令阶段写缓存"
    rollback()
