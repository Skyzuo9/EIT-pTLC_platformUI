"""auto_rail 原语离线测试 (地轨随点自动到位, Win B)
==================================================
功能:
    验证 ActionExecutor._ensure_rail_for_point: move_to_point 走臂前据目标点 rail 槽把地轨
    先移到位。用全 mock 三协作者 (robot/plc/points) + 真 ActionRegistry (供 rail.move 派发),
    确定性覆盖开关/退化/幂等/移轨/安全门/回零 七条 auto_rail 路径, 并断言「断言门→安全门→移轨→走臂」时序;
    另加两条裸 rail.move 用例, 验证 safety_anchor 硬门下沉到 rail.move 原语后, auto_rail 之外的
    任何调用方 (编排层 rail_move_safe / 全流程裸 rail.move) 移轨前也须臂在 P1 (确保式: 不在则安全邻域内
    自动回零, 邻域外/持真空拒发 UNSAFE)。再加六条 rail.ensure 用例 (B1 原子 enter 注入的显式按槽移轨原语):
    关→空操作 / 同 mm 异槽→幂等 / 异 mm→门+移 / 未回零→拒 / 臂已离开 P1→UNSAFE / 槽越界→参数拒。

判据 (与 executor 一致): 按 mm 判是否已在位 (位1=位2=168、位5=位6=600 槽码→mm 不可逆),
    同 mm 异槽不无谓移轨; 超差先断言式 require_anchor(P1), 过了再复用 rail.move 管线 (其确保式
    ensure_home 安全门在此仅复核放行)。

按槽补移用断言式而非确保式的理由 (用例 5b 锁死): 地轨到位是原子的前置条件, 只在臂仍缩在 P1 时成立。
    走到补移还不在 P1 即该原子入口缺 rail.ensure(槽) —— 此时交给确保式回零, 臂持料会被真空守卫拒
    (报错误指"不在安全位", 掩盖真因), 臂恰停在某 safe_anchor 且无真空则会被静默 move_j 拉回 P1
    再移轨, 悄悄改掉序列轨迹。确保式自动回零仍保留在 rail_move_safe / 裸 rail.move (不经本路径)。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_auto_rail_move_offline
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from eit_ptlc.action.executor import ActionExecutor
from eit_ptlc.action.models import ActionStatus, RejectCode
from eit_ptlc.action.registry import ActionRegistry

_CFG = Path(__file__).resolve().parent.parent / "config"

# rail.yaml plc_servo 槽→mm 真源镜像 (位1=位2=168、位5=位6=600 是同 mm 异槽的关键对)
_RAIL_MM = {1: 168.0, 2: 168.0, 3: 350.0, 4: 500.0, 5: 600.0, 6: 600.0}


class _Reg:
    """机器人点注册表桩: get(name) 返回带指定 rail 槽的点。"""

    def __init__(self, rail):
        self._rail = rail

    def get(self, name):
        return SimpleNamespace(rail=self._rail, robot_name=name, point_id=name)


class _Robot:
    """机器人桩: 记录 require_anchor / ensure_home / move_to_point 到共享事件序 (供时序断言)。

    两个位姿开关对应两道不同的门, 刻意分开以便构造"能自动回零但不该回"的危险组合:
      at_home=True/False   → 断言式 require_anchor(P1) 过/抛 (_ensure_rail 的按槽补移前置门);
      anchor_ok=True/False → 确保式 ensure_home 过/抛 (rail.move 的 safety_anchor 硬门);
        anchor_ok=True 表示已在 P1 或可从安全邻域自动回位 (执行器不可区分二者),
        anchor_ok=False 表示邻域外/持真空, 硬停拒发。
    """

    home_point = "P1"

    def __init__(self, rail, *, anchor_ok=True, at_home=True, events=None):
        self.registry = _Reg(rail)
        self._anchor_ok = anchor_ok
        self._at_home = at_home
        self.events = events if events is not None else []
        self.moved: list[dict] = []

    def require_anchor(self, point_id, **kw):
        self.events.append(("require_anchor", point_id))
        if not self._at_home:
            raise PermissionError(f"机器人不在锚点 {point_id}: 关节偏差=37.500 deg")
        return SimpleNamespace()

    def ensure_home(self, point_id=None, **kw):
        self.events.append(("ensure_home", point_id))
        if not self._anchor_ok:
            raise PermissionError(
                f"机器人不在 home 且不在任何安全点邻域内, 拒绝自动回零; 请维护模式手动回 {point_id}")
        return SimpleNamespace()

    def move_to_point(self, **kwargs):
        self.events.append(("arm", kwargs.get("point_id_or_robot_name")))
        self.moved.append(kwargs)
        return {}  # dict → executor 直接作 result 透传


class _Plc:
    """PLC 桩: read_rail_pose 返回 (实际mm, 已回零); execute 记录 rail.move 调用。"""

    def __init__(self, actual_mm, homed, *, events=None):
        self._actual = actual_mm
        self._homed = homed
        self.events = events if events is not None else []
        self.rail_moves: list[tuple] = []
        self.read_count = 0

    async def read_rail_pose(self):
        self.read_count += 1
        return (self._actual, self._homed)

    async def execute(self, station, code, channels, *, timeout=None, stall_timeout=None):
        self.events.append(("rail_move", station, code, dict(channels)))
        self.rail_moves.append((station, code, dict(channels)))
        return SimpleNamespace(request_seq=1, action_code=code, step=0,
                               safe_state=SimpleNamespace(name="IDLE"))


class _Points:
    """点位服务桩: sync_group=None (跳过单写者回读), rail_slot_mm 查槽→mm。"""

    def sync_group(self, station):
        return None

    def rail_slot_mm(self, slot):
        return _RAIL_MM.get(int(slot))


async def _run() -> int:
    failures: list[str] = []
    tally = {"n": 0}

    def check(name: str, cond: bool, detail: str = "") -> None:
        tally["n"] += 1
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    registry = ActionRegistry.load(_CFG / "actions")

    async def move(auto_rail, rail, actual, homed, anchor_ok=True, at_home=True):
        """构造一次 move_to_point 执行; 返回 (result, robot, plc, events)。"""
        events: list = []
        robot = _Robot(rail, anchor_ok=anchor_ok, at_home=at_home, events=events)
        plc = _Plc(actual, homed, events=events)
        ex = ActionExecutor(registry, robot=robot, plc=plc, points=_Points(), auto_rail=auto_rail)
        r = await ex.execute("robot.move_to_point",
                             {"point_id_or_robot_name": "P39", "motion": "move_l"},
                             current_mode="RUN")
        return r, robot, plc, events

    # 1) 开关关 → 零行为变化: 不读地轨位、不移轨, 直接走臂 (真机现行为冻结)
    r, robot, plc, events = await move(auto_rail=False, rail=3, actual=168.0, homed=True)
    check("off_zero_behavior",
          r.status is ActionStatus.DONE and plc.read_count == 0 and not plc.rail_moves
          and events == [("arm", "P39")],
          f"{r.status} read={plc.read_count} moves={plc.rail_moves} ev={events}")

    # 2) 点无 rail (未收编 sentinel) → 放行不移轨, 不读地轨位 (退化为编排残留 rail_move_safe)
    r, robot, plc, events = await move(auto_rail=True, rail=None, actual=168.0, homed=True)
    check("none_rail_passthrough",
          r.status is ActionStatus.DONE and plc.read_count == 0 and not plc.rail_moves
          and events == [("arm", "P39")],
          f"{r.status} read={plc.read_count} moves={plc.rail_moves} ev={events}")

    # 3) 同 mm 异槽 (槽2=168, 实际168) → 幂等不移轨 (§9-4 关键: 槽码不同但 mm 同即已在位)
    r, robot, plc, events = await move(auto_rail=True, rail=2, actual=168.0, homed=True)
    check("same_mm_idempotent",
          r.status is ActionStatus.DONE and plc.read_count == 1 and not plc.rail_moves
          and events == [("arm", "P39")],
          f"{r.status} read={plc.read_count} moves={plc.rail_moves} ev={events}")

    # 4) 异 mm (槽3=350, 实际168) 且臂在 P1 → 断言门过 → 确保式安全门过 → 移轨到3 → 再走臂
    #    (时序: require_anchor→ensure_home→rail_move→arm)
    r, robot, plc, events = await move(auto_rail=True, rail=3, actual=168.0, homed=True)
    check("diff_mm_move_then_arm",
          r.status is ActionStatus.DONE
          and events == [("require_anchor", "P1"),
                         ("ensure_home", "P1"),
                         ("rail_move", "rail", 10, {"Rail_Target_Position": 3}),
                         ("arm", "P39")]
          and len(robot.moved) == 1,
          f"{r.status} ev={events} moved={robot.moved}")

    # 5) 需移轨但机械臂已离开 P1 且邻域外 → 断言门先拒 → UNSAFE, 既不移轨也不走臂 (碰撞门保住)。
    #    收窄后连 ensure_home 都不再调用 —— 判定止于 require_anchor, 不给自动回零的机会。
    r, robot, plc, events = await move(auto_rail=True, rail=3, actual=168.0, homed=True,
                                       anchor_ok=False, at_home=False)
    check("unsafe_anchor_blocks",
          r.status is ActionStatus.REJECTED and r.reject_code == RejectCode.UNSAFE.value
          and not plc.rail_moves and not robot.moved
          and events == [("require_anchor", "P1")],
          f"{r.status} code={r.reject_code} moves={plc.rail_moves} ev={events}")

    # 5b) 回归锁 (本次 bug): 臂已离开 P1 但恰停在某 safe_anchor 且无真空 —— ensure_home 本会"成功"地
    #     把臂 move_j 悄悄拉回 P1 再移轨, 静默改掉序列轨迹。收窄后必须止于断言门: UNSAFE, 且事件序里
    #     没有 ensure_home / rail_move / arm, 即不回零、不移轨、不走臂。
    r, robot, plc, events = await move(auto_rail=True, rail=3, actual=168.0, homed=True,
                                       anchor_ok=True, at_home=False)
    check("mid_sequence_rail_change_blocks_without_autohome",
          r.status is ActionStatus.REJECTED and r.reject_code == RejectCode.UNSAFE.value
          and not plc.rail_moves and not robot.moved
          and events == [("require_anchor", "P1")]
          and "缺 rail.ensure(3)" in (r.message or "") and "P39" in (r.message or ""),
          f"{r.status} code={r.reject_code} moves={plc.rail_moves} ev={events} msg={r.message}")

    # 6) 地轨未回零 → 实际位不可信 → ERROR, 既不移轨也不走臂 (不拿脏位判定)
    r, robot, plc, events = await move(auto_rail=True, rail=3, actual=168.0, homed=False)
    check("not_homed_error",
          r.status is ActionStatus.ERROR and plc.read_count == 1
          and not plc.rail_moves and not robot.moved and events == [],
          f"{r.status} read={plc.read_count} moves={plc.rail_moves} ev={events}")

    # 7) 裸 rail.move (非 auto_rail 路径) 且臂不在安全位 → 原语级硬门拒发 (UNSAFE), 不下发 PLC。
    #    safety_anchor 声明在 rail.move 动作上, 与 auto_rail 开关无关 —— 覆盖编排层 rail_move_safe /
    #    全流程裸 rail.move 等所有调用方, 使"必须在 home 点才能移动地轨"不可绕过。
    events = []
    robot = _Robot(rail=5, anchor_ok=False, events=events)
    plc = _Plc(600.0, True, events=events)
    ex = ActionExecutor(registry, robot=robot, plc=plc, points=_Points(), auto_rail=False)
    r = await ex.execute("rail.move", {"Rail_Target_Position": 5}, current_mode="RUN")
    check("bare_rail_move_unsafe_blocks",
          r.status is ActionStatus.REJECTED and r.reject_code == RejectCode.UNSAFE.value
          and not plc.rail_moves and events == [("ensure_home", "P1")],
          f"{r.status} code={r.reject_code} moves={plc.rail_moves} ev={events}")

    # 8) 裸 rail.move 且臂在安全位 → 过门后正常下发 (时序 anchor→rail_move)
    events = []
    robot = _Robot(rail=5, anchor_ok=True, events=events)
    plc = _Plc(168.0, True, events=events)
    ex = ActionExecutor(registry, robot=robot, plc=plc, points=_Points(), auto_rail=False)
    r = await ex.execute("rail.move", {"Rail_Target_Position": 5}, current_mode="RUN")
    check("bare_rail_move_safe_dispatches",
          r.status is ActionStatus.DONE
          and events == [("ensure_home", "P1"), ("rail_move", "rail", 10, {"Rail_Target_Position": 5})],
          f"{r.status} ev={events}")

    # ---- rail.ensure 原语 (B1 原子 enter 注入; 显式按槽确认/补移地轨, 幂等) ----
    async def ensure(auto_rail, actual, homed, slot=3, anchor_ok=True, at_home=True):
        """构造一次 rail.ensure 执行; 返回 (result, plc, events)。slot 直接入参 (不查点)。"""
        events: list = []
        robot = _Robot(rail=slot, anchor_ok=anchor_ok, at_home=at_home, events=events)
        plc = _Plc(actual, homed, events=events)
        ex = ActionExecutor(registry, robot=robot, plc=plc, points=_Points(), auto_rail=auto_rail)
        r = await ex.execute("rail.ensure", {"Rail_Target_Position": slot}, current_mode="RUN")
        return r, plc, events

    # 9) auto_rail 关 → DONE 空操作, 不读地轨位、不移轨 (地轨仍由编排层字面量驱动)
    r, plc, events = await ensure(auto_rail=False, actual=168.0, homed=True, slot=3)
    check("ensure_off_noop",
          r.status is ActionStatus.DONE and plc.read_count == 0 and not plc.rail_moves and events == [],
          f"{r.status} read={plc.read_count} moves={plc.rail_moves} ev={events}")

    # 10) 同 mm 异槽 (槽2=168, 实际168) → 幂等 DONE, 读一次即跳过, 不移轨
    r, plc, events = await ensure(auto_rail=True, actual=168.0, homed=True, slot=2)
    check("ensure_same_mm_idempotent",
          r.status is ActionStatus.DONE and plc.read_count == 1 and not plc.rail_moves and events == [],
          f"{r.status} read={plc.read_count} moves={plc.rail_moves} ev={events}")

    # 11) 异 mm (槽3=350, 实际168) 且臂在 P1 → 断言门过 → 确保式安全门过 → 移轨到3 → DONE
    #     (时序 require_anchor→ensure_home→rail_move, 无走臂)
    r, plc, events = await ensure(auto_rail=True, actual=168.0, homed=True, slot=3)
    check("ensure_diff_mm_moves",
          r.status is ActionStatus.DONE
          and events == [("require_anchor", "P1"), ("ensure_home", "P1"),
                         ("rail_move", "rail", 10, {"Rail_Target_Position": 3})],
          f"{r.status} ev={events}")

    # 12) 未回零 → ERROR, 不移轨 (不拿脏位判定)
    r, plc, events = await ensure(auto_rail=True, actual=168.0, homed=False, slot=3)
    check("ensure_not_homed_error",
          r.status is ActionStatus.ERROR and plc.read_count == 1 and not plc.rail_moves and events == [],
          f"{r.status} read={plc.read_count} moves={plc.rail_moves} ev={events}")

    # 13) 需移轨但臂已离开 P1 → 断言门先拒 UNSAFE, 不移轨、不自动回零。
    #     rail.ensure 恒在原子 enter 的 require_anchor(P1) 之后调用, 走到这里即编排把它放错了位置。
    r, plc, events = await ensure(auto_rail=True, actual=168.0, homed=True, slot=3,
                                  anchor_ok=False, at_home=False)
    check("ensure_unsafe_anchor_blocks",
          r.status is ActionStatus.REJECTED and r.reject_code == RejectCode.UNSAFE.value
          and not plc.rail_moves and events == [("require_anchor", "P1")],
          f"{r.status} code={r.reject_code} moves={plc.rail_moves} ev={events}")

    # 14) 槽越界 (7 > 6) → 参数校验拒发 INVALID_PARAM, 不读位不移轨
    r, plc, events = await ensure(auto_rail=True, actual=168.0, homed=True, slot=7)
    check("ensure_out_of_range_rejected",
          r.status is ActionStatus.REJECTED and r.reject_code == RejectCode.INVALID_PARAM.value
          and plc.read_count == 0 and not plc.rail_moves,
          f"{r.status} code={r.reject_code} read={plc.read_count}")

    print(f"\n共 {tally['n']} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
