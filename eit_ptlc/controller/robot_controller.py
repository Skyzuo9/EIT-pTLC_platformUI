"""机器人控制器
==============
功能:
    机械臂设备语义层. 把点位许可 / 安全门控与底层 Dobot TCP 传输隔离, 对上层提供
    点动 (jog) / 步进 (step) / 到点 (move_to_point) / 工具 / 查询 / 回原点.
    迁移自 UI-Upper/core/robot_service.py 的 RobotActionService (仅 Dobot 直连),
    新增 jog/step 三模式的控制器封装.

线程模型:
    底层 Dobot 传输为同步阻塞; 本控制器方法同步, 由 API 层经 run_in_executor 调用.
    动作锁为可重入 RLock, 允许一个流程在整段路线内独占机器人.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Callable, Iterator

from eit_ptlc.config.models import RobotCfg
from eit_ptlc.controller.point_registry import PointRegistry, RobotPoint
from eit_ptlc.driver.dobot_tcp_driver import DobotTcpRobotTransport
from eit_ptlc.driver.robot_transport import (
    MotionOptions,
    MotionProfile,
    MountedTool,
    RobotFeedback,
    RobotTransport,
    ToolAction,
)

log = logging.getLogger(__name__)


def _serialized(method):
    """方法装饰器: 进入前获取动作锁, 保证单命令串行."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._registered_activity(method.__name__):
            with self._action_lock:
                return method(self, *args, **kwargs)
    return wrapper


class RobotController:
    """机械臂控制器: 点位运动 + 点动/步进 + 工具动作的唯一业务入口."""

    # ── 末端执行器数字孪生状态映射 ────────────────────────────────────────
    # 机构 id 与 three_d 的 rig_map.yaml / device-manifest 逐字一致(错一个字前端
    # 静默不动): rob_grip_plate96 / rob_grip_vial / rob_flip_suction / rob_suction.
    # 布尔语义与 DO 接线对齐: true = DO2 侧激活 = 偏离模型基准位
    # (夹爪闭合 GRIPPER_CLOSE / 吸盘上翻 ROTARY_UP); false = 张开 / 下翻.
    _TWIN_GRIPPER_BY_TOOL = {
        MountedTool.SLOT2: "rob_grip_plate96",
        MountedTool.SLOT3: "rob_grip_vial",
    }
    _TWIN_FLIP_ID = "rob_flip_suction"
    # 吸盘真空(DO3). 与翻转气缸同属 1 号刀, 但它没有几何(rigged:false 的纯状态机构):
    # 它存在的意义是让三维在**页面刷新后**仍然知道"吸盘还带着电"——
    # 板是否跟着机械臂走, 靠的就是这一位; 流程事件包络刷新即丢, 只有它能跨刷新恢复.
    _TWIN_SUCTION_ID = "rob_suction"
    _TWIN_ACTION_STATE = {
        ToolAction.GRIPPER_CLOSE: True,
        ToolAction.GRIPPER_OPEN: False,
        ToolAction.ROTARY_UP: True,
        ToolAction.ROTARY_DOWN: False,
        ToolAction.SUCTION_ON: True,
        ToolAction.SUCTION_OFF: False,
    }
    # "发令即公告"名单: 这些动作在**行程中**就先把 commanded 推给三维(带 moving: True),
    # 动作返回时再补 confirmed 并清 moving. 其余动作维持"到位才公告".
    #
    # 只有翻转在列, 因为只有它同时满足两条: ① 180° 大幅动作, 静止一整段再瞬间转完极显眼;
    # ② 行程时长不可预知 —— app.yaml 的 rotary_up/down 是 di_or_dwell, 等 DI 上限
    # tool_di_timeout=10s, 等不到才回退 600ms. 于是三维那边任何"按固定时长播一段"的做法
    # 都对不齐, 只能靠这条在途标记让动画与实物同起同止.
    # 夹爪(0.4s)与真空(无几何)没有这个观感问题, 不进名单就少一条会失败的路径.
    _TWIN_INFLIGHT_ACTIONS = (ToolAction.ROTARY_UP, ToolAction.ROTARY_DOWN)
    # 翻转气缸尚未被命令过时对外发布的**推定**姿态: CAD 基准位 = 下翻(False).
    # 作用是让三维一挂刀就建好插值通道, 免得开机后的第一程撞上"首见直跳"被整段吃掉.
    # confirmed=None + source='commanded' 是如实表达"这是推定不是 DI 确认",
    # 前端按既有 estimated 语义显示; 绝不能为了"看起来确定"而伪造 confirmed.
    _TWIN_BASELINE_STATE = {
        "commanded": False,
        "confirmed": None,
        "available": True,
        "source": "commanded",
    }

    def __init__(
        self,
        transport: RobotTransport,
        registry: PointRegistry,
        *,
        home_point: str,
        jog_speed_percent: int = 20,
        step_distance_mm: float = 1.0,
        step_angle_deg: float = 1.0,
        default_user: int = 0,
        default_tool: int = 1,
        maintenance_gate=None,
    ) -> None:
        self.transport = transport
        self.registry = registry
        self.home_point = home_point
        self.jog_speed_percent = jog_speed_percent
        self.step_distance_mm = step_distance_mm
        self.step_angle_deg = step_angle_deg
        self.default_user = default_user
        self.default_tool = default_tool
        self._maintenance_gate = maintenance_gate
        # 传输锁覆盖单条命令; 本可重入租约让一个流程独占整段已审计路线
        self._action_lock = threading.RLock()
        # 连续点动跨越 jog_start 返回边界，activity 租约必须一直保留到成功 stop。
        self._jog_state_lock = threading.Lock()
        self._jog_activity_lease = None
        # 末端执行器最近命令态缓存 (机构 id -> mechanism_state 条目), 供数字孪生只读
        # 发布. 按 id 永久保留: 重挂同一把刀恢复上次姿态; 进程重启缓存为空 -> 前端
        # 保持模型基准态(张开/下翻). 独立小锁, 绝不碰 _action_lock(10Hz 采样不得被
        # 长运动阻塞).
        self._twin_mech_lock = threading.Lock()
        self._twin_mech_cache: dict[str, dict] = {}

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """独占机器人 (可重入), 供一个流程在整段路线内持有."""
        with self._registered_activity("exclusive"):
            with self._action_lock:
                yield

    def is_busy(self) -> bool:
        """机器人动作锁是否正被其它执行线程占用（非阻塞只读探测）。"""
        acquired = self._action_lock.acquire(blocking=False)
        if not acquired:
            return True
        self._action_lock.release()
        return False

    # ------------------------------------------------------------------
    # 查询 / 到点
    # ------------------------------------------------------------------

    def query(self, *, user: int | None = None, tool: int | None = None) -> RobotFeedback:
        """读取机器人当前状态 (不运动)."""
        with self._action_lock:
            if user is None and tool is None:
                return self.transport.query()
            options = MotionOptions(
                user=self.default_user if user is None else int(user),
                tool=self.default_tool if tool is None else int(tool),
            )
            return self.transport.query(options)

    @_serialized
    def home(self) -> RobotFeedback:
        """回原点: 走已标定 home 点的 move_j (TCP 无内建 P1)."""
        point = self.registry.require_motion(self.home_point, "move_j")
        if point.role != "home":
            raise PermissionError(f"配置的 home 点角色不是 home: {point.point_id}")
        options = MotionOptions(user=point.user, tool=point.tool, acc=point.acc, vel=point.vel, cp=point.cp)
        return self.transport.move_j(point.pose, options, joint=point.joint)

    @_serialized
    def move_j(self, point_id_or_robot_name: str) -> RobotFeedback:
        """关节运动到命名点位."""
        return self._move_point(self.registry.require_motion(point_id_or_robot_name, "move_j"), "move_j")

    @_serialized
    def move_l(self, point_id_or_robot_name: str) -> RobotFeedback:
        """直线运动到命名点位."""
        return self._move_point(self.registry.require_motion(point_id_or_robot_name, "move_l"), "move_l")

    @_serialized
    def move_to_point(
        self,
        point_id_or_robot_name: str,
        motion: str | None = None,
        *,
        profile: MotionProfile | None = None,
        offset: tuple[float, float, float] | None = None,
    ) -> RobotFeedback:
        """到命名点位; motion 为 None 时要求点位唯一允许动作.

        offset=(dx_mm, dy_mm, drz_deg) 为视觉纠偏偏移, 在该点 user 系下叠加到目标位姿
        (复刻旧 RelPointUser); 仅本次运动生效, 不改点表. 偏移仅支持直线运动 move_l
        (move_j 按关节角运动, 笛卡尔偏移无意义)。
        """
        point = self.registry.get(point_id_or_robot_name)
        if motion is None:
            if len(point.allowed_motion) != 1:
                raise PermissionError(f"点 {point.point_id} 允许动作不唯一, 必须显式指定 move_j/move_l")
            motion = point.allowed_motion[0]
        if motion not in {"move_j", "move_l"}:
            raise ValueError(f"不支持的运动类型: {motion}")
        if offset is not None and motion != "move_l":
            raise ValueError("视觉纠偏偏移仅支持直线运动 move_l (move_j 按关节角运动, 笛卡尔偏移无意义)")
        return self._move_point(self.registry.require_motion(point_id_or_robot_name, motion),
                                motion, profile=profile, offset=offset)

    @_serialized
    def move_to_pose(
        self,
        pose,
        motion: str = "move_l",
        *,
        user: int | None = None,
        tool: int | None = None,
        profile: MotionProfile | None = None,
        joint=None,
    ) -> RobotFeedback:
        """运动到给定 6DOF 笛卡尔位姿 (非命名点位), 默认 move_l、限速。

        仅供示教复核: 上位机据「捕获位姿 + 进近偏移」算出临时进近点 (点表无对应条目),
        逐点 move_l 走退出/二次进入序列, 让人复核落位。合理性/DEBUG 门控由调用方
        (points_service.teach_move / 路由) 负责; 本方法只做纯运动。缺省 acc=20 vel=10
        (与长按运行同限速)。move_j 需给 joint (笛卡尔位姿无法反解), 一般用 move_l。
        """
        pose = tuple(float(v) for v in pose)
        if len(pose) != 6:
            raise ValueError("pose 必须是 6 元 (X,Y,Z,Rx,Ry,Rz)")
        if motion not in {"move_j", "move_l"}:
            raise ValueError(f"不支持的运动类型: {motion}")
        options = MotionOptions(
            user=self.default_user if user is None else int(user),
            tool=self.default_tool if tool is None else int(tool),
            acc=20 if profile is None else profile.acc,
            vel=10 if profile is None else profile.vel,
            cp=0 if profile is None else profile.cp,
        )
        if motion == "move_j":
            if joint is None:
                raise ValueError("move_j 到笛卡尔位姿需显式提供 joint")
            return self.transport.move_j(pose, options, joint=tuple(float(v) for v in joint))
        return self.transport.move_l(pose, options, joint=None)

    @_serialized
    def tool_action(self, action: ToolAction, timeout_ms: int = 3000) -> RobotFeedback:
        """末端工具语义动作 (白名单).

        transport.tool_action **阻塞整段物理行程**(翻转要等 DI 到位, 最坏 tool_di_timeout=10s),
        所以孪生状态分两拍写: 发令前先公告在途, 动作返回后再补到位. 只在缓存里写完就完事,
        真正发出去的是 10 Hz 的 mechanism_snapshot(), 控制路径不因此多一次 I/O.
        """
        action = ToolAction(action)
        rollback = self._announce_twin_motion(action)
        try:
            feedback = self.transport.tool_action(action, timeout_ms)
        except BaseException:
            # 动作没跑成 -> 撤回公告, 不给三维留一个"没发生过的姿态".
            # 门控 _assert_tool_allows 在任何 DO 之前抛, 撤回是准确的; 部署配置 di_or_dwell
            # 的 DI 超时**不抛错**(回退 dwell), 所以到这里的基本只剩门控拒绝与通讯断,
            # 两者都拿不到 confirmed, 退回最后一个已知姿态是两个错法里更诚实的那个.
            # ⚠ 若将来把 tool_confirm 的 mode 改成纯 di(超时会抛), 这条策略要重新评估:
            # 那时气缸其实已经在动, 撤回会让画面倒回去.
            rollback()
            raise
        self._record_twin_mechanism(action, feedback)
        return feedback

    def _twin_mech_id_for(self, action: ToolAction) -> "str | None":
        """动作 × 当前挂载工具 -> 孪生机构 id; 对不上号返回 None.

        真机与仿真都汇聚到 tool_action, 所以两种传输免费共享这条显示链. 仿真传输不做
        工具门控(真机由 driver._assert_tool_allows 挡), 这里按语义再挡一道, 免得污染缓存.
        公告与到位两个写入方共用这一份判据 —— 分成两套迟早会一边发一边不发.
        """
        if action not in self._TWIN_ACTION_STATE:
            return None
        mounted = MountedTool(int(self.transport.mounted_tool))
        if action in (ToolAction.ROTARY_UP, ToolAction.ROTARY_DOWN):
            return self._TWIN_FLIP_ID if mounted == MountedTool.SLOT1 else None
        if action in (ToolAction.SUCTION_ON, ToolAction.SUCTION_OFF):
            return self._TWIN_SUCTION_ID if mounted == MountedTool.SLOT1 else None
        return self._TWIN_GRIPPER_BY_TOOL.get(mounted)

    def twin_mechanism_ids(self) -> tuple:
        """当前挂刀提供的全部孪生机构 id (排序; 裸腕为空).

        参数:
            无
        返回:
            tuple[str, ...]

        判据仍是 _twin_mech_id_for, 所以这张表与"写得动哪些机构"逐字同源 ——
        供仿真沙盒的状态面发布"这把刀能点哪几个末端", 前端因此不必复抄刀↔机构映射。
        与 mechanism_snapshot 的区别: 那边只发布**已被命令过**(或有 CAD 基准位)的机构,
        是显示面; 这边是能力面, 未命令过的也在列。
        """
        ids = set()
        for action in self._TWIN_ACTION_STATE:
            mech_id = self._twin_mech_id_for(action)
            if mech_id is not None:
                ids.add(mech_id)
        return tuple(sorted(ids))

    def commanded_mechanism_states(self) -> dict[str, dict]:
        """**已被命令过**的末端执行器状态 (不含 mechanism_snapshot 补的 CAD 推定基准态).

        参数:
            无
        返回:
            Dict[str, dict], 机构 id -> 状态条目 (commanded/confirmed/available/source);
            从未被命令过的机构**不出现**

        与 mechanism_snapshot 的唯一差别是**不补 _TWIN_BASELINE_STATE**。那条推定是为
        三维一挂刀就建好插值通道用的, 只该走渲染路径; 仿真沙盒采纳状态时若把它一并搬走,
        就等于把一条推定写进了**另一台机器**的"命令过什么"账本 —— 正是
        _TWIN_BASELINE_STATE 注释里第二条红线禁止的事, 只是跨了一台机器。

        机构范围取 twin_mechanism_ids (同一条 _twin_mech_id_for 判据), 不建第二张表。
        同样不取 _action_lock —— 采纳发生在长运动期间也不得阻塞。
        """
        with self._twin_mech_lock:
            return {
                mech_id: dict(self._twin_mech_cache[mech_id])
                for mech_id in self.twin_mechanism_ids()
                if mech_id in self._twin_mech_cache
            }

    def tool_action_for_mechanism(self, mech_id: str, state: bool) -> "ToolAction | None":
        """孪生机构 id + 目标布尔态 -> 该发的 ToolAction; 当前挂刀不提供该机构则 None.

        参数:
            mech_id: 机构 id (rob_suction / rob_flip_suction / rob_grip_*)
            state: 目标态; True = DO2 侧激活 (夹爪闭合 / 吸盘上翻 / 真空开)
        返回:
            ToolAction | None

        实现是把 _TWIN_ACTION_STATE × _twin_mech_id_for 反查一遍, **不建第二张表** ——
        工具门控 (哪把刀提供哪个机构) 因此自动沿用同一判据, 不会出现"面板能点但
        动作发不出去"或反过来的偏差。供仿真沙盒的状态写面用 (真机侧不调它)。
        """
        for action, value in self._TWIN_ACTION_STATE.items():
            if value != bool(state):
                continue
            if self._twin_mech_id_for(action) == mech_id:
                return action
        return None

    def _twin_expected_stroke_s(self, action: ToolAction) -> "float | None":
        """本方向上一程的实测行程耗时(秒), 供三维按真速配速; 没有样本则 None.

        为什么不写死一个时长: 这只缸挂在机器人工具 I/O 上(DO2/DO6 + DI1/DI2), **不是 PLC
        设备**, PLC 点表里没有它, 更没有速度寄存器 —— 唯一能拿到真速的途径就是量"写完 DO
        到限位 DI 置位"的时间, 而驱动已经在等 DI 时顺手量了(_wait_di_timed).
        自校准的好处: 现场调气压、换缸、季节温差导致的速度变化, 三维全自动跟上, 不用改配置.

        仿真传输没有这个方法(鸭子类型探测), 返回 None -> 前端回退 rig_map 的标称值.
        """
        getter = getattr(self.transport, "last_tool_stroke_s", None)
        if not callable(getter):
            return None
        try:
            value = getter(action)
        except Exception:
            return None
        if not isinstance(value, (int, float)):
            return None
        value = float(value)
        # 离谱值不下发, 让前端走标称值(标称值只会偏慢, 偏慢不会跑到实物前面):
        #   · 下限 0.2s —— 双气缸物理上不可能比这更快, 比它小的必是"没真走"量出来的假样本
        #     (驱动侧已挡掉"DI 一开始就到位"那一类, 这里是第二道: 计时器抖动、反馈周期
        #     被当成行程等都会落进这个区间). 2026-08-05 就是一个 ~0.01s 的假样本让上翻瞬移的.
        #   · 上限 60s —— 过大多半是那一程卡过 DI 轮询.
        if not 0.2 <= value <= 60.0:
            return None
        return value

    def _twin_already_confirmed_at(self, mech_id: str, target: bool) -> bool:
        """该机构此刻是否**已由真 DI 确认**停在 target 位(用于识别防御性复令).

        流程里 rotary 常被当作状态确认重下(robot_suction_pick 同一次运行发两次 rotary-up),
        这种复令实物一动不动, 三维却照播一整段翻转 —— 用户看到的"没动却翻了"就是它.

        判据只认**真 DI 确认过**的位置, 刻意排除 source='commanded' 的推断态:
        页面刷新/换刀/急停/进程重启后, 缓存里可能只有命令态甚至什么都没有, 此刻缸在哪
        其实**并不知道**. 把"假设在该位"误判成"已在该位", 会把一段真实运动从画面上吃掉 ——
        那比多播一段动画危险得多. 所以拿不准一律照常公告.
        """
        with self._twin_mech_lock:
            entry = self._twin_mech_cache.get(mech_id)
        if not entry:
            return False
        return (
            entry.get("source") == "feedback"
            and isinstance(entry.get("confirmed"), bool)
            and entry["confirmed"] is target
        )

    def _announce_twin_motion(self, action: ToolAction) -> "Callable[[], None]":
        """发令即公告: 把"命令已下发、行程未结束"写进缓存, 让三维与实物同时起步.

        只公告 commanded, confirmed 一律 None —— 此刻确实还没到位, 不得伪造.
        返回一个撤回闭包(捕获改写前的条目), 供动作抛错时还原.

        已知误差: 公告发生在 transport.tool_action **之前**, 而翻转的 DO 是在驱动里
        清完反向位、过完 _ROTARY_INTERLOCK_S(200ms)互锁才写的, 所以画面比实际给气早约
        200ms(= 2 个 10Hz 采样周期). 要做到零偏差得把回调穿过 RobotTransport 抽象基类
        (4 个实现 + 测试桩), 不值得为两个采样周期付这个代价 —— 与现状"晚整段行程"相比
        小两个数量级.
        """
        def _noop() -> None:
            return None

        try:
            if action not in self._TWIN_INFLIGHT_ACTIONS:
                return _noop
            mech_id = self._twin_mech_id_for(action)
            if mech_id is None:
                return _noop
            target = self._TWIN_ACTION_STATE[action]
            # 防御性复令(缸已由 DI 确认在该位): 整条在途公告都跳过, 连 moving 都不写 ——
            # 缓存原样保留(仍是 confirmed/feedback), 三维目标值不变, 于是一帧都不动.
            # 动作本身照发: DO 照写、200ms 互锁照等, 安全语义一个字不动;
            # 这里只是不再向三维公告一段**并不存在**的运动.
            if self._twin_already_confirmed_at(mech_id, target):
                return _noop
            entry = {
                "commanded": target,
                "confirmed": None,
                "available": True,
                "source": "commanded",
                "moving": True,
            }
            # 本方向上一程的实测耗时, 让三维按真速匀速铺开这一段; 无样本则省略该键,
            # 前端自然回退 rig_map 的标称 transitionS(与 moving 一样是新增可选键,
            # 老前端读不到就走原路).
            expected_s = self._twin_expected_stroke_s(action)
            if expected_s is not None:
                entry["expectedS"] = expected_s
            with self._twin_mech_lock:
                previous = self._twin_mech_cache.get(mech_id)
                self._twin_mech_cache[mech_id] = entry

            def _rollback() -> None:
                try:
                    with self._twin_mech_lock:
                        # 只在没有别人覆盖过时才还原(动作期间理论上独占, 但缓存是共享的)
                        if self._twin_mech_cache.get(mech_id) is not entry:
                            return
                        if previous is None:
                            self._twin_mech_cache.pop(mech_id, None)
                        else:
                            self._twin_mech_cache[mech_id] = previous
                except Exception:
                    log.exception("末端执行器孪生在途公告撤回失败(不影响动作)")

            return _rollback
        except Exception:
            log.exception("末端执行器孪生在途公告失败(不影响动作)")
            return _noop

    def _record_twin_mechanism(self, action: ToolAction, feedback: RobotFeedback) -> None:
        """缓存末端执行器语义状态(数字孪生显示用); 任何失败只记日志, 不影响控制路径.

        判据由 _twin_mech_id_for 统一给出(与在途公告共用一份).
        """
        try:
            mech_id = self._twin_mech_id_for(action)
            if mech_id is None:
                return
            state = self._TWIN_ACTION_STATE[action]
            # gripper_open 走 DI2 可靠确认 -> feedback; 夹料时 close 是 dwell -> 只有
            # 命令位, 如实标 commanded(前端 HUD 按既有 estimated 语义呈现).
            # 吸盘真空**没有任何 DI**(_TOOL_DI_TARGET 无 SUCTION 条目), di_confirmed
            # 恒 False -> confirmed=None/source=commanded. 这是如实表达, 不得伪造 confirmed.
            confirmed = bool(getattr(feedback.tool_state, "di_confirmed", False))
            entry = {
                "commanded": state,
                "confirmed": state if confirmed else None,
                "available": True,
                "source": "feedback" if confirmed else "commanded",
            }
            # moving 只出现在公告过在途的机构上(当前只有翻转): 其余条目逐字节维持原样,
            # 免得给 PLC/夹爪那些本就没有这个阶段的机构凭空加一个恒 False 的字段.
            # 这里必须写 False 而不是删键 —— 前端靠它把保持在终点前的动画放行.
            if action in self._TWIN_INFLIGHT_ACTIONS:
                entry["moving"] = False
            with self._twin_mech_lock:
                self._twin_mech_cache[mech_id] = entry
        except Exception:
            log.exception("末端执行器孪生状态缓存失败(不影响动作)")

    def mechanism_snapshot(self) -> dict[str, dict]:
        """当前挂载工具的末端执行器状态快照, 供 realtime_feedback_loop 并入
        mechanism_state 事件(10 Hz 只读采样).

        只发布挂载中工具的机构: 卸刀/裸腕后不再发布, 前端 store 保末态即冻结;
        重挂同一把刀恢复上次缓存姿态. 不取 _action_lock —— 长运动期间采样不得阻塞.

        翻转气缸**没有命令过也照发一条基准态**(见 _TWIN_BASELINE_STATE): 它在三维里
        是有几何的执行器, 若等到第一条命令才首次出现, 前端那一帧才建插值通道 ——
        而通道首见是直跳的, 于是**开机后的第一程被整段吃掉**, 表现为"上翻瞬移".
        """
        try:
            mounted = MountedTool(int(self.transport.mounted_tool))
        except Exception:
            return {}
        if mounted == MountedTool.SLOT1:
            wanted = (self._TWIN_FLIP_ID, self._TWIN_SUCTION_ID)
        else:
            gripper = self._TWIN_GRIPPER_BY_TOOL.get(mounted)
            wanted = (gripper,) if gripper else ()
        if not wanted:
            return {}
        with self._twin_mech_lock:
            snapshot = {
                mech_id: dict(self._twin_mech_cache[mech_id])
                for mech_id in wanted
                if mech_id in self._twin_mech_cache
            }
        # 缸还没被命令过 -> 补一条"按 CAD 基准态推定"的条目, 让前端开机就建好通道.
        # 三条红线:
        #   · confirmed 恒 None / source='commanded' —— 没有 DI 证据就绝不声称到位;
        #   · 只补进**返回值**, 不回填 _twin_mech_cache —— 那份缓存是"命令过什么"的账本,
        #     一旦被推定值污染, 空翻抑制(_twin_already_confirmed_at)的判据就会被带偏;
        #   · 不带 moving —— 它不在行程中, 缺省即已就位.
        if self._TWIN_FLIP_ID in wanted and self._TWIN_FLIP_ID not in snapshot:
            snapshot[self._TWIN_FLIP_ID] = dict(self._TWIN_BASELINE_STATE)
        return snapshot

    @_serialized
    def set_mounted_tool(self, tool_id: int) -> None:
        """声明当前挂载工具 (权威工具态注入; 0=无/裸腕, 1/2/3=slot1/2/3).

        机器人无"挂了哪个工具"的 DI, 工具态由知道意图者显式注入:
        robot_tool_pick 锁定后通知 slot, robot_tool_put 卸刀后通知 0,
        启动对账由操作员按实物声明. 驱动据此对 DO2/DO6 双义工具动作门控.
        """
        self.transport.set_mounted_tool(MountedTool(int(tool_id)))

    @property
    def mounted_tool(self) -> MountedTool:
        """当前挂载工具 (权威工具态), 供启动对账 UI / 状态回显."""
        return self.transport.mounted_tool

    @_serialized
    def set_do(self, channel: int, enabled: bool) -> RobotFeedback:
        """裸 DO 直控 (维护页纯 DO 栏): 直接置位单个数字输出口, 不走语义白名单.

        通道白名单 ({1,2,3,6}) 与安全由传输层执行; 模式门控 (仅 DEBUG) 由 action 层负责.
        """
        return self.transport.set_do(int(channel), bool(enabled))

    @staticmethod
    def _check_anchor(
        point: RobotPoint,
        feedback: RobotFeedback,
        joint_tol_deg: float,
        pos_tol_mm: float,
        rot_tol_deg: float,
    ) -> str | None:
        """位姿谓词: feedback 在 point 容差内返回 None, 否则返回中文偏差描述 (不抛异常).

        功能:
            关节优先 (点位有 joint 且反馈 6 轴齐全), 否则退化笛卡尔位姿比较; 反馈不可校验也返回描述.
            require_anchor 与 ensure_home 共用此单一谓词 (在不在某点容差内).
        参数:
            point: 命名锚点; feedback: 当前反馈;
            joint_tol_deg: 关节容差 (deg); pos_tol_mm: 位置容差 (mm); rot_tol_deg: 姿态容差 (deg)
        返回:
            str | None, None 表示在容差内, 否则为偏差描述 (供上层决定抛错或续跑)
        """
        if point.joint is not None and len(feedback.joint) == 6:
            delta = max(abs(_angle_delta_deg(actual, expected))
                        for actual, expected in zip(feedback.joint, point.joint))
            if delta > joint_tol_deg:
                return f"机器人不在锚点 {point.point_id}: 关节偏差={delta:.3f} deg"
            return None
        if len(feedback.pose) != 6:
            return f"反馈无法校验锚点 {point.point_id}"
        position_delta = max(abs(feedback.pose[i] - point.pose[i]) for i in range(3))
        rotation_delta = max(abs(_angle_delta_deg(feedback.pose[i], point.pose[i])) for i in range(3, 6))
        if position_delta > pos_tol_mm or rotation_delta > rot_tol_deg:
            return (f"机器人不在锚点 {point.point_id}: 位置偏差={position_delta:.3f} mm, "
                    f"姿态偏差={rotation_delta:.3f} deg")
        return None

    @_serialized
    def require_anchor(
        self,
        point_id: str,
        *,
        joint_tol_deg: float = 2.0,
        pos_tol_mm: float = 5.0,
        rot_tol_deg: float = 5.0,
    ) -> RobotFeedback:
        """校验机器人当前位姿处于命名锚点容差内 (点位 operation 的进/出锚点安全门).

        功能:
            读取当前反馈, 与命名点的关节/位姿逐分量比较; 命名点须为 validated.
            优先用关节比较 (点位有 joint 且反馈 6 轴齐全), 否则退化到笛卡尔位姿比较.
            超出任一容差抛 PermissionError (拒绝后续运动).
        参数:
            point_id: 命名锚点 id;
            joint_tol_deg: 关节容差 (deg); pos_tol_mm: 位置容差 (mm); rot_tol_deg: 姿态容差 (deg)
        返回:
            RobotFeedback, 当前反馈 (供链路记录)
        """
        point = self.registry.get(point_id)
        if point.status != "validated":
            raise PermissionError(f"锚点 {point.point_id} 未校验 (status={point.status})")
        feedback = self.transport.query()
        detail = self._check_anchor(point, feedback, joint_tol_deg, pos_tol_mm, rot_tol_deg)
        if detail is not None:
            raise PermissionError(detail)
        return feedback

    @_serialized
    def ensure_home(
        self,
        point_id: str | None = None,
        *,
        joint_tol_deg: float = 2.0,
        pos_tol_mm: float = 5.0,
        rot_tol_deg: float = 5.0,
    ) -> RobotFeedback:
        """确保机器人在 home 锚点 (确保式回零, 取代断言式 require_anchor 卡点).

        功能:
            在 P1 容差内直接过; 否则吸盘真空守卫 -> 仅当当前位姿在某个 safe_anchor 安全点
            邻域内才 move_j 回 home 并复验; 邻域外/持真空维持硬停 PermissionError.
        参数:
            point_id: 仅接受解析到 home 点的锚点 (供 executor safety_anchor 透传), 其它点显式拒绝;
                None 即用配置 home_point;
            joint_tol_deg: 关节容差 (deg); pos_tol_mm: 位置容差 (mm); rot_tol_deg: 姿态容差 (deg)
        返回:
            RobotFeedback, 已在 home 的当前反馈
        """
        # 0) 锚点归一与门槛校验: point_id 非 None 时只认 home 锚点
        home = self.registry.get(self.home_point)
        if point_id is not None and self.registry.get(point_id).point_id != home.point_id:
            raise PermissionError(f"确保式回零仅支持 home 锚点, 收到: {point_id}")
        if home.role != "home":
            raise PermissionError(f"配置的 home 点角色不是 home: {home.point_id}")
        if home.status != "validated":
            raise PermissionError(f"锚点 {home.point_id} 未校验 (status={home.status})")

        # 1) P1 容差内直接过 (无运动, 不做真空判定 —— 持料停在 P1 是取放链正常态)
        feedback = self.transport.query()
        if self._check_anchor(home, feedback, joint_tol_deg, pos_tol_mm, rot_tol_deg) is None:
            return feedback

        # 2) 吸盘真空守卫 (仅需运动时): 工具态=吸盘 且 DO3 语义位在 -> 默认吸着板子, 禁止拖动。
        #    工具态与真空位都读自同一 query 快照 (feedback.tool_state), 与 robot_tool_ensure 同源。
        if feedback.tool_state.mounted_tool == MountedTool.SLOT1 and (feedback.tool_state.commanded_bits & 2):
            raise PermissionError(
                "机器人不在 home 且吸盘仍有真空(疑似吸持板件), 拒绝自动回零; 请先人工处理板件")

        # 3) 安全邻域判定: 当前位姿须落在某个 safe_anchor 点容差邻域内
        safe_points = self.registry.safe_anchor_points()
        matched = next(
            (candidate for candidate in safe_points
             if self._check_anchor(candidate, feedback, joint_tol_deg, pos_tol_mm, rot_tol_deg) is None),
            None)
        if matched is None:
            raise PermissionError(
                f"机器人不在 home 且不在任何安全点邻域内 (已检 {len(safe_points)} 个 safe_anchor 点), "
                f"拒绝自动回零; 请维护模式手动回 {home.point_id}")

        # 4) 自动回零: 从已知自由空间安全点 move_j 回 home (点位标定 acc/vel; 复用内部运动, 不嵌套动作锁)
        log.info("[robot] 确保式回零: 从安全点 %s 邻域自动 move_j 回 %s", matched.point_id, home.point_id)
        point = self.registry.require_motion(self.home_point, "move_j")
        self._move_point(point, "move_j")

        # 5) require_anchor 语义复验 (同谓词): 回零后仍不在位则暴露, 不吞
        feedback = self.transport.query()
        detail = self._check_anchor(home, feedback, joint_tol_deg, pos_tol_mm, rot_tol_deg)
        if detail is not None:
            raise PermissionError(f"自动回零后复验失败: {detail}")
        return feedback

    @_serialized
    def dwell(self, duration_ms: int) -> None:
        """驻留等待: 点位序列中的固定延时 (取代旧流程引擎的 WaitStep).

        参数:
            duration_ms: 时长 ms (1-60000)
        返回:
            None
        """
        time.sleep(max(0, int(duration_ms)) / 1000.0)

    # ------------------------------------------------------------------
    # 点动 jog / 步进 step (维护页手动控制)
    # ------------------------------------------------------------------

    def jog_start(self, axis_id: str, *, user: int | None = None, tool: int | None = None) -> None:
        """开始连续点动 (按住起). axis_id 取自 JOG_AXES (J1±..J6± / X±..Rz±).

        点动速度由机器人全局速度因子 (SpeedFactor) 控制, 本系统不设定;
        jog_speed_percent 不影响点动 (仅作为 step 的 acc/vel 默认).
        模式门控 (仅维护/手动) 由上层 action/api 层执行.
        """
        gate = self._maintenance_gate
        lease = gate.try_enter_activity("机器人操作 jog_start") if gate is not None else None
        if gate is not None and lease is None:
            gate.require_available("机器人操作 jog_start")
        options = MotionOptions(user=self.default_user if user is None else user,
                                tool=self.default_tool if tool is None else tool)
        try:
            with self._action_lock:
                with self._jog_state_lock:
                    if self._jog_activity_lease is not None:
                        raise RuntimeError("机器人连续点动已处于活动状态，请先 jog_stop")
                self.transport.jog_start(axis_id, options)
                with self._jog_state_lock:
                    self._jog_activity_lease = lease
        except BaseException:
            if gate is not None and lease is not None:
                gate.leave_activity(lease)
            raise

    def jog_stop(self) -> None:
        """停止点动 (松开停). 任何时刻可调用."""
        with self._action_lock:
            self.transport.jog_stop()
            self._release_jog_activity()

    def set_speed_factor(self, ratio: int) -> None:
        """设置全局速度比 SpeedFactor (1-100); 影响点动与所有运动 (维护页速度入口).

        实际速度 = SpeedFactor% × 各命令 v%; 点动无独立速度参数, 故点动快慢由此决定.
        不取动作锁: 须能在流程运动 (持锁) 进行中抢发以即时调速; 传输层命令口自有锁守护
        (同 stop/pause/resume 的运动中抢发语义)。
        """
        with self._registered_activity("set_speed_factor"):
            value = int(ratio)
            if not 1 <= value <= 100:
                raise ValueError("速度比 ratio 必须在 1..100")
            self.transport.set_speed_factor(value)

    @property
    def speed_factor(self) -> int | None:
        """当前(主控已设)全局速度比; 传输无此概念时为 None."""
        value = getattr(self.transport, "speed_factor", None)
        return int(value) if value is not None else None

    @_serialized
    def step(
        self,
        axis: str,
        distance: float | None = None,
        *,
        motion: str = "l",
        speed: int | None = None,
        user: int | None = None,
        tool: int | None = None,
    ) -> RobotFeedback:
        """单轴步进 (增量移动). distance 为 None 时按配置默认 (笛卡尔 mm / 关节 deg)."""
        if distance is None:
            distance = self.step_angle_deg if axis.startswith("J") else self.step_distance_mm
        options = MotionOptions(
            user=self.default_user if user is None else user,
            tool=self.default_tool if tool is None else tool,
            acc=self.jog_speed_percent,
            vel=self.jog_speed_percent if speed is None else speed,
        )
        return self.transport.step(axis, distance, options, motion=motion)

    # ------------------------------------------------------------------
    # 运动中止 / 暂停 / 急停 (绕过动作锁, 运动中可触发)
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """中止当前运动 (软停, 臂保持使能). 不取动作锁, 故运动中可触发."""
        self.transport.stop()
        self._release_jog_activity()

    def pause(self) -> None:
        """暂停当前运动. 不取动作锁; 配合 resume 恢复."""
        self.transport.pause()

    def resume(self) -> None:
        """恢复被暂停的运动. 不取动作锁."""
        with self._registered_activity("resume"):
            self.transport.resume()

    def emergency_stop(self, pressed: bool = True) -> None:
        """急停; pressed=True 按下 (失能臂并报警), False 释放. 不取动作锁."""
        self.transport.emergency_stop(pressed)
        if pressed:
            self._release_jog_activity()

    # ------------------------------------------------------------------
    # 报警清除 / 使能 (维护; 配置 + confirm 双重门控由传输层执行)
    # ------------------------------------------------------------------

    def clear_error(self, *, confirm: bool = False) -> RobotFeedback:
        """清除机器人报警 (需配置允许且 confirm). 传输层内部串行化, 不取本层动作锁."""
        return self.transport.clear_error(confirm=confirm)

    def enable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        """使能机器人 (需配置允许且 confirm). 传输层内部串行化, 不取本层动作锁."""
        with self._registered_activity("enable_robot"):
            return self.transport.enable_robot(confirm=confirm)

    def disable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        """下使能机器人 (需配置允许且 confirm). 传输层内部串行化, 不取本层动作锁."""
        feedback = self.transport.disable_robot(confirm=confirm)
        self._release_jog_activity()
        return feedback

    @_serialized
    def reconnect(self, confirm: bool = False) -> RobotFeedback:
        """重建机器人传输连接 (断联恢复). 先 close 再 connect (幂等), 返回一次查询反馈.

        功能:
            运行期机器人 IO 断链后传输通道被关闭, 节点转 offline; 本方法重新建链以恢复.
            close 兜底清理可能残留的半开通道, 使从 offline 状态也能可靠重连;
            传输层 connect 内部的 _reconcile_after_connect 会在他人正在运动/CommandId
            变化时拒绝夺权, 故重连本身不产生运动且安全.
        参数:
            confirm: 操作员已人工确认"机械臂已物理停止、无其他控制者"时置真 ——
                先清接管守卫的比对基准再重连 (transport.reset_takeover_guard),
                这是守卫报错文案里那句"需人工确认"的唯一落点; 缺省 False 时
                守卫照常拦截, 不许静默夺权。"仍在运行/暂停"的拒绝不受 confirm 影响。
        """
        if confirm:
            self.transport.reset_takeover_guard()
        self.transport.close()
        self.transport.connect()
        return self.transport.query()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    _MAINTENANCE_ALLOWED = {
        # 只读/恢复连接不产生运动；停止、急停、去使能必须在任何状态下可用。
        "query", "require_anchor", "reconnect",
        "stop", "pause", "emergency_stop", "jog_stop", "disable_robot", "clear_error",
    }

    @contextmanager
    def _registered_activity(self, operation: str) -> Iterator[None]:
        """Atomically hold an activity token for the complete direct robot call."""
        gate = self._maintenance_gate
        if gate is None or operation in self._MAINTENANCE_ALLOWED:
            yield
            return
        lease = gate.try_enter_activity(f"机器人操作 {operation}")
        if lease is None:
            gate.require_available(f"机器人操作 {operation}")
        try:
            yield
        finally:
            gate.leave_activity(lease)

    def _release_jog_activity(self) -> None:
        with self._jog_state_lock:
            lease = self._jog_activity_lease
            self._jog_activity_lease = None
        if lease is None:
            return
        if self._maintenance_gate is not None:
            self._maintenance_gate.leave_activity(lease)

    def _move_point(self, point: RobotPoint, motion: str, *, profile: MotionProfile | None = None,
                    offset: tuple[float, float, float] | None = None) -> RobotFeedback:
        options = MotionOptions(
            user=point.user,
            tool=point.tool,
            acc=point.acc if profile is None else profile.acc,
            vel=point.vel if profile is None else profile.vel,
            cp=point.cp if profile is None else profile.cp,
        )
        pose = point.pose
        if offset is not None:
            # 视觉纠偏: 在该点 user 系下叠加平移(X/Y)与旋转(Rz), 复刻旧 RelPointUser(target,{dx,dy,0,0,0,drz})
            dx, dy, drz = offset
            pose = (pose[0] + dx, pose[1] + dy, pose[2], pose[3], pose[4], pose[5] + drz)
        if motion == "move_j":
            return self.transport.move_j(pose, options, joint=point.joint)
        return self.transport.move_l(pose, options, joint=point.joint)


def build_robot_controller(robot_cfg: RobotCfg, *, base_dir: str | Path = ".") -> RobotController:
    """由 RobotCfg 构建 Dobot 直连传输 + 点表 + 控制器.

    参数:
        robot_cfg: 机器人配置 (端口/点表/安全门控/jog-step 默认)
        base_dir: 解析相对路径的基准 (points_file 已由 loader 解析为绝对路径时不影响)
    返回:
        RobotController
    """
    if robot_cfg.transport != "dobot_tcp":
        raise ValueError(f"controller 仅支持 dobot_tcp 直连, 配置为: {robot_cfg.transport}")
    base = Path(base_dir).resolve()
    points_file = _resolve(base, robot_cfg.points_file)
    meta_file = _resolve(base, robot_cfg.points_meta_file)
    registry = PointRegistry.load(points_file, source_version=robot_cfg.point_source_version, meta_path=meta_file)
    transport = DobotTcpRobotTransport(
        robot_cfg.host,
        command_port=robot_cfg.command_port,
        feedback_port=robot_cfg.feedback_port,
        error_http_port=robot_cfg.error_http_port,
        connect_timeout=robot_cfg.connect_timeout,
        command_timeout=robot_cfg.command_timeout,
        action_timeout=robot_cfg.action_timeout,
        poll_interval=robot_cfg.poll_interval,
        allow_enable_command=robot_cfg.allow_enable_command,
        allow_clear_error_command=robot_cfg.allow_clear_error_command,
        tool_di_feedback_enabled=robot_cfg.tool_di_feedback_enabled,
        tool_di_timeout=robot_cfg.tool_di_timeout,
        tool_confirm=DobotTcpRobotTransport.tool_confirm_from_cfg(robot_cfg.tool_confirm),
        speed_factor=robot_cfg.speed_factor,
    )
    return RobotController(
        transport, registry,
        home_point=robot_cfg.home_point,
        jog_speed_percent=robot_cfg.jog_speed_percent,
        step_distance_mm=robot_cfg.step_distance_mm,
        step_angle_deg=robot_cfg.step_angle_deg,
    )


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _angle_delta_deg(actual: float, expected: float) -> float:
    """角度差归一化到 (-180, 180] (deg), 供锚点姿态/关节比较."""
    return math.fmod(actual - expected + 540.0, 360.0) - 180.0
