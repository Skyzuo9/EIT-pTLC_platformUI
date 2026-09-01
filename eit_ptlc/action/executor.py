"""动作执行器
============
功能:
    统一动作执行入口. 校验参数与模式门控, 调度到 RobotController (机器人原子) 或
    PlcController (PLC L2 工位动作), 把异构结果归一为 ActionResult.
    机器人控制器为同步, 经 run_in_executor 调用; PLC 控制器为异步直接 await.

返回:
    始终返回 ActionResult (不抛); 拒绝/错误/超时均以 status + reject_code/error_code 表达.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Callable, Optional

from eit_ptlc.action.models import ActionResult, ActionStatus, RejectCode
from eit_ptlc.action.plc_error_hints import describe as describe_plc_error
from eit_ptlc.action.registry import ActionDef, ActionRegistry
from eit_ptlc.driver.robot_transport import RobotActionError, RobotTransportError
from eit_ptlc.tools.pump.profiles import PUMP_PROFILES
from eit_ptlc.value_domain import check_enum

log = logging.getLogger(__name__)

# 孔板孔位寻址参数 (sampling.aspirate / sampling.rinse_mix): 三者一起由执行器在 PLC L2 触发前消费
# (取标定 → 仿射算 xy → 写 Sampling_4X/3Y_Target), 非泵 builder 消费; 泵契约测试据此
# 从 builder 消费集排除 (单一真源, 见 tests/test_pump_contract_offline.py)。
PLATE_WELL_PARAMS = ("plate_spec", "plate_no", "well")

# 与 PC 单点控制会话互斥的动作类型: 这些都会写 PLC 的执行器/伺服命令位, 与单点通道同源。
# robot / camera / vision 走各自设备, 单点会话期间照常可用。
_MANUAL_EXCLUSIVE_KINDS = frozenset({"plc_l2", "plc_write", "servo_target", "rail_ensure"})


class ActionExecutor:
    """统一动作执行器.

    参数:
        registry: 动作目录; robot: RobotController (可选); plc: PlcController (可选);
        mode_provider: 返回当前控制模式的回调 (可选); time_fn: 时间源 (可注入测试)
    """

    def __init__(
        self,
        registry: ActionRegistry,
        *,
        robot=None,
        plc=None,
        points=None,
        driver=None,
        calibration=None,
        camera=None,
        vision_methods=None,
        mode_provider: Optional[Callable[[], str]] = None,
        time_fn: Callable[[], float] = time.time,
        auto_rail: bool = False,
        maintenance_gate=None,
        manual_guard: Optional[Callable[[], Optional[str]]] = None,
        error_hint_context: str = "real",
    ) -> None:
        self._registry = registry
        self._robot = robot
        self._plc = plc
        # 运行期地轨随点自动到位 (Win B): move_to_point 走臂前据目标点 rail 槽把地轨先移到位。
        # 默认关 = 零行为变化 (地轨仍由编排层 rail_move_safe 字面量驱动)。见 _ensure_rail_for_point。
        self._auto_rail = bool(auto_rail)
        self._points = points          # PointsService: servo_target 下发 (push_target)
        self._driver = driver          # OpcUaDriver: plc_write 块写回读确认
        self._calibration = calibration  # CalibrationService: 孔位寻址下发 (push_well 写 *_Target)
        self._camera = camera          # CameraController: camera 拍照动作
        # vision 动作 method 名 -> async 计算函数 (视觉分析 / cnc 路径生成); 返回 result dict
        self._vision_methods = dict(vision_methods or {})
        self._mode_provider = mode_provider
        self._time = time_fn
        self._maintenance_gate = maintenance_gate
        # 单点控制互斥回调: 会话激活时返回原因串, 否则 None (见 ManualService.exclusion_reason)。
        # 单点会话期间 PLC 的 <设备>手动/自动 位由上位机直接持有, 此时再放 L2 动作下去就是双写者。
        self._manual_guard = manual_guard
        # 错误码释义的语境: "real"=真机现场处置话术, "sim"=沙盒状态面指引。
        # 同一个 301, 真机该去查仓里有没有板与回没回零, 沙盒该去设板仓张数 ——
        # 给沙盒用户看标定话术会把人引到一条根本不存在的歧路上。
        self._error_hint_context = str(error_hint_context)

    def set_registry(self, registry: ActionRegistry) -> None:
        """热替换动作目录 (raw 编辑保存后): 后续 execute 即用新定义, 与 app.state.registry 保持一致."""
        self._registry = registry

    @property
    def robot(self):
        """机器人控制器只读访问 (可为 None)。

        供仿真沙盒"采纳实时状态"读取真实位姿 —— app.state 没有发布 robot,
        这里给一个公开口, 免得调用方去摸 `_robot` 私有属性。
        """
        return self._robot

    async def execute(
        self,
        name: str,
        params: Optional[dict] = None,
        *,
        request_id: Optional[str] = None,
        current_mode: Optional[str] = None,
    ) -> ActionResult:
        """Atomically register the whole action against PLC deployment maintenance."""
        rid = request_id or uuid.uuid4().hex[:12]
        try:
            adef = self._registry.get(name)
        except KeyError:
            return await self._execute_impl(
                name, params, request_id=rid, current_mode=current_mode,
            )

        maintenance_allowed = (
            adef.kind == "robot"
            and adef.method in {"stop", "emergency_stop", "jog_stop", "disable_robot"}
        )
        gate = self._maintenance_gate
        if gate is None or maintenance_allowed:
            return await self._execute_impl(
                name, params, request_id=rid, current_mode=current_mode,
            )

        lease = gate.try_enter_activity(f"原子动作 {name}")
        if lease is None:
            reason = gate.reason or "等待 PLC 重新启动并就绪"
            return self._reject(
                name, rid, RejectCode.RESOURCE_CONFLICT,
                f"PLC 下载维护态已锁定，拒绝新动作: {reason}", self._time(),
            )
        try:
            return await self._execute_impl(
                name, params, request_id=rid, current_mode=current_mode,
            )
        finally:
            gate.leave_activity(lease)

    async def _execute_impl(
        self,
        name: str,
        params: Optional[dict] = None,
        *,
        request_id: Optional[str] = None,
        current_mode: Optional[str] = None,
    ) -> ActionResult:
        """执行一个声明式动作, 返回统一 ActionResult."""
        rid = request_id or uuid.uuid4().hex[:12]
        params = dict(params or {})
        try:
            adef = self._registry.get(name)
        except KeyError:
            return self._reject(name, rid, RejectCode.INVALID_PARAM, f"未知动作: {name}")

        started = self._time()

        # 完整下载维护门：所有新动作统一在参数校验/设备 IO 前拒绝。仅保留随时可用的
        # 停止、急停、点动停止和机器人去使能，确保维护态不会挡住风险收敛动作。
        maintenance_allowed = (
            adef.kind == "robot"
            and adef.method in {"stop", "emergency_stop", "jog_stop", "disable_robot"}
        )
        if (self._maintenance_gate is not None
                and self._maintenance_gate.active
                and not maintenance_allowed):
            reason = self._maintenance_gate.reason or "等待 PLC 重新启动并就绪"
            return self._reject(
                name, rid, RejectCode.RESOURCE_CONFLICT,
                f"PLC 下载维护态已锁定，拒绝新动作: {reason}", started,
            )

        # 模式门控
        mode = current_mode if current_mode is not None else (self._mode_provider() if self._mode_provider else None)
        if (adef.modes and mode is not None and mode not in adef.modes
                and not (self._maintenance_gate is not None
                         and self._maintenance_gate.active
                         and maintenance_allowed)):
            return self._reject(name, rid, RejectCode.MODE_NOT_ALLOWED,
                                f"当前模式 {mode} 不允许动作 {name} (需 {list(adef.modes)})", started)

        # 单点控制互斥: 会话激活时 PLC 的执行器命令位归上位机直接持有, 放 L2/写类动作
        # 下去会变成双写者。robot/camera/vision 不碰这批位, 照常放行。
        if self._manual_guard is not None and adef.kind in _MANUAL_EXCLUSIVE_KINDS:
            manual_reason = self._manual_guard()
            if manual_reason:
                return self._reject(name, rid, RejectCode.RESOURCE_CONFLICT,
                                    manual_reason, started)

        # 参数校验与强转 (plc_write 用 fields 自带类型, 不走标量 params 校验, 见 _exec_plc_write)
        if adef.kind == "plc_write":
            coerced = params
        else:
            ok, coerced, msg = self._validate(adef, params)
            if not ok:
                return self._reject(name, rid, RejectCode.INVALID_PARAM, msg, started)

        # 调度
        try:
            if adef.kind == "robot":
                return await self._exec_robot(adef, coerced, rid, started)
            if adef.kind == "plc_l2":
                return await self._exec_plc_l2(adef, coerced, rid, started)
            if adef.kind == "rail_ensure":
                return await self._exec_rail_ensure(adef, coerced, rid, started)
            if adef.kind == "servo_target":
                return await self._exec_servo_target(adef, rid, started)
            if adef.kind == "plc_write":
                return await self._exec_plc_write(adef, coerced, rid, started)
            if adef.kind == "camera":
                return await self._exec_camera(adef, coerced, rid, started)
            if adef.kind in ("vision", "host"):
                # host = 同 vision 的注入函数 method 派发, 语义上非视觉 (如液位等待); 共用管线
                return await self._exec_vision(adef, coerced, rid, started)
            return self._reject(name, rid, RejectCode.INVALID_PARAM,
                                f"动作类别 {adef.kind} 暂未实现执行", started)
        except Exception as exc:  # 调度层兜底, 不抛出
            log.exception("[Action] %s 执行异常", name)
            return ActionResult(action=name, request_id=rid, status=ActionStatus.ERROR,
                                accepted=True, message=f"执行异常: {exc}", started_at=started,
                                finished_at=self._time())

    # ------------------------------------------------------------------
    # 机器人调度
    # ------------------------------------------------------------------

    async def _exec_robot(self, adef: ActionDef, coerced: dict, rid: str, started: float) -> ActionResult:
        if self._robot is None:
            return self._reject(adef.name, rid, RejectCode.PLC_NOT_READY, "机器人控制器未就绪", started)
        method = getattr(self._robot, adef.method, None)
        if method is None or not callable(method):
            return self._reject(adef.name, rid, RejectCode.INVALID_PARAM, f"机器人无方法 {adef.method}", started)
        # tool_action 需把字符串动作名转为 ToolAction 枚举
        if adef.method == "tool_action" and "action" in coerced:
            from eit_ptlc.driver.robot_transport import TOOL_ACTION_NAMES
            key = str(coerced["action"]).strip().lower()
            if key not in TOOL_ACTION_NAMES:
                return self._reject(adef.name, rid, RejectCode.INVALID_PARAM, f"未知工具动作: {key}", started)
            coerced["action"] = TOOL_ACTION_NAMES[key]
        # move_to_point 的 acc/vel/cp 合成为运动速度档 MotionProfile (二者齐备才覆盖, 否则用点位默认)
        if adef.method == "move_to_point":
            acc = coerced.pop("acc", None)
            vel = coerced.pop("vel", None)
            cp = coerced.pop("cp", None)
            if acc is not None and vel is not None:
                from eit_ptlc.driver.robot_transport import MotionProfile
                coerced["profile"] = MotionProfile(acc=acc, vel=vel, cp=cp or 0)
            # 视觉纠偏偏移 (dx_mm/dy_mm/drz_deg): 任一给定即合成 offset 元组下传 (缺省补 0); 全缺则不偏移
            dx = coerced.pop("dx_mm", None)
            dy = coerced.pop("dy_mm", None)
            drz = coerced.pop("drz_deg", None)
            if dx is not None or dy is not None or drz is not None:
                coerced["offset"] = (float(dx or 0.0), float(dy or 0.0), float(drz or 0.0))
            # auto_rail (Win B): 走臂前据目标点 rail 槽把地轨先移到位 (开关默认关 → 直接放行, 零行为变化)。
            # 前置失败 (安全门不在位 / 未回零 / 移轨被拒) 即拦截, 不走臂。
            gate = await self._ensure_rail_for_point(
                coerced.get("point_id_or_robot_name"), adef.name, rid, started)
            if gate is not None:
                return gate

        loop = asyncio.get_running_loop()
        from eit_ptlc.driver.robot_transport import RobotMotionInterrupted
        try:
            feedback = await loop.run_in_executor(None, lambda: method(**coerced))
        except RobotMotionInterrupted as exc:
            # 运动被显式中止 (Stop/EmergencyStop): 归一为 CANCELLED, 非故障
            return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.CANCELLED, accepted=True,
                                message=str(exc), started_at=started, finished_at=self._time())
        except PermissionError as exc:
            return self._reject(adef.name, rid, RejectCode.UNSAFE, str(exc), started)
        except (ValueError, KeyError) as exc:
            return self._reject(adef.name, rid, RejectCode.INVALID_PARAM, str(exc), started)
        except Exception as exc:
            error_id = int(getattr(exc, "error_id", 0))
            return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR, accepted=True,
                                error_code=error_id, message=str(exc), started_at=started, finished_at=self._time())
        # capture_plate_offset 等返回 dict 的机器人方法直接透传 result; 其余返回 RobotFeedback 则序列化
        result = feedback if isinstance(feedback, dict) else _feedback_to_dict(feedback)
        return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.DONE, accepted=True,
                            message="完成", progress=1.0, result=result,
                            started_at=started, finished_at=self._time())

    # ------------------------------------------------------------------
    # auto_rail: 运行期地轨随点自动到位 (地轨作为机器人点第7维 Win B)
    #   见 docs 地轨点位合并管理_地轨作为机器人点第7维_设计
    # ------------------------------------------------------------------

    _RAIL_MOVE_ACTION = "rail.move"
    _RAIL_MM_TOL = 5.0           # mm: 实际位与目标槽 mm 之差在此内即视为已在位 (同 mm 异槽不无谓移轨)

    async def _ensure_rail_for_point(self, point_id, action_name: str, rid: str, started: float):
        """move_to_point 走臂前把地轨移到目标点 rail 槽对应工位 (auto_rail 关 → None 放行, 零行为变化)。

        由目标点派生 rail 槽后委托 _ensure_rail 按 mm 判据确认/补移。返回 None=放行走臂;
        返回 ActionResult=前置拦截 (不走臂)。

        退化/豁免 (均放行, 依赖编排残留 rail_move_safe 字面量, 决策 #10 sentinel):
          auto_rail 关 / robot 缺失 / 点位未知 / 点无 rail (未收编)。
        """
        if not self._auto_rail:
            return None
        if self._robot is None or not point_id:
            return None
        try:
            point = self._robot.registry.get(str(point_id))
        except Exception:
            return None                      # 未知点位: 交由臂运动自身报错, auto_rail 不越权
        slot = getattr(point, "rail", None)
        if slot is None:
            return None                      # 未收编: 退化为编排残留 rail_move_safe
        return await self._ensure_rail(slot, action_name, rid, started, point_hint=str(point_id))

    async def _ensure_rail(self, slot, action_name: str, rid: str, started: float, *, point_hint=None):
        """按槽确认/补移地轨到位 (幂等); auto_rail 主开关由各调用方在委托前判定。

        判据用 mm 不用槽码 (位1=位2=168、位5=位6=600, 槽码→mm 不可逆): 目标槽 mm 与实际 mm 之差
        <= 容差即幂等不动 (含同 mm 异槽); 超差则要求臂已在 P1 后复用 rail.move 动作管线移轨
        (单写者回读确认 + L2 派发)。

        参数:
            slot: 目标地轨槽码 1-6; action_name/rid/started: 结果归属的动作身份与起始时刻;
            point_hint: 触发本次确认的目标点名 (auto_rail 路径传入, 仅用于报错定位), None 表示显式 rail.ensure
        返回:
            None=已在位/移轨成功 (放行); ActionResult=前置失败 (读位失败/未回零/臂不在 P1/移轨被拒)。
        豁免 (返回 None): plc|points 缺失 / slot 为空 / 目标槽无 mm 映射。
        """
        if self._plc is None or self._points is None or slot is None:
            return None
        target_mm = self._points.rail_slot_mm(int(slot))
        if target_mm is None:
            return None                      # 无 mm 真源: 不臆断移轨
        try:
            actual_mm, homed = await self._plc.read_rail_pose()
        except Exception as exc:             # Rail_ActPos/Homed 节点未下载真机等 → 不可判位, 拒绝
            return ActionResult(action=action_name, request_id=rid, status=ActionStatus.ERROR,
                                accepted=True, retryable=True, started_at=started, finished_at=self._time(),
                                message=f"auto_rail: 地轨实际位读取失败, 未移轨/未走臂: {exc}")
        if not homed:
            return ActionResult(action=action_name, request_id=rid, status=ActionStatus.ERROR,
                                accepted=True, retryable=False, started_at=started, finished_at=self._time(),
                                message="auto_rail: 地轨未回零, 拒绝自动移轨 (先手动回零再运行)")
        if abs(float(actual_mm) - float(target_mm)) <= self._RAIL_MM_TOL:
            return None                      # 已在位 (含同 mm 异槽): 幂等不动
        # 需补移: 断言式要求臂已在 P1, 不在则拒 —— 地轨到位是原子的前置条件, 不是序列中的一步。
        # 走到这里还不在 P1, 只可能是该原子入口漏了 rail.ensure(槽), 臂已伸出才发现要移轨; 此时
        # 交给 rail.move 的确保式安全门是错的: 臂持料则被真空守卫拒 (报错误指"不在安全位", 掩盖真因),
        # 臂恰停在某 safe_anchor 且无真空则会被静默 move_j 拉回 P1 再移轨, 悄悄改掉序列轨迹。
        # 注: rail_move_safe / 裸 rail.move 不经本函数, 其确保式自动回零语义不受影响。
        if self._robot is not None:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None, lambda: self._robot.require_anchor(self._robot.home_point))
            except PermissionError as exc:
                where = f"目标点 {point_hint} " if point_hint else ""
                return self._reject(
                    action_name, rid, RejectCode.UNSAFE,
                    f"{where}需地轨在位{int(slot)}({target_mm:.1f}mm), 实际{float(actual_mm):.1f}mm 需补移, "
                    f"但机械臂已离开安全位 —— 该原子入口缺 rail.ensure({int(slot)}), 未移轨/未走臂: {exc}",
                    started)
        # 臂已在 P1: 复用 rail.move 动作管线 (其 safety_anchor=P1 硬门在此仅复核放行,
        # 仍为 rail_move_safe / 裸 rail.move 等其它调用方的最后一道防线), 及 sync_group 单写者回读确认 + L2 派发器等 DONE。
        res = await self.execute(self._RAIL_MOVE_ACTION, {"Rail_Target_Position": int(slot)})
        if res.status is not ActionStatus.DONE:
            return res                       # 移轨失败/被拒(含安全门)/超时: 直接回传
        return None

    async def _exec_rail_ensure(self, adef: ActionDef, coerced: dict, rid: str, started: float) -> ActionResult:
        """rail.ensure: 原子 enter 处 (臂在 P1) 按槽确认/补移地轨到位, 幂等 (已在位则跳过)。

        auto_rail 关 → 直接 DONE 空操作 (地轨仍由编排层 rail_move_safe 字面量驱动, 零行为变化)。
        复用 _ensure_rail: 读位→未回零/读失败拒→在容差内跳过→超差断言臂在 P1 后走 rail.move 管线。
        本动作恒在原子 enter 的 require_anchor(P1) 之后调用, 故断言必过; 不过即为编排放错了位置。
        """
        if not self._auto_rail:
            return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.DONE,
                                accepted=True, message="auto_rail 关闭, rail.ensure 空操作", progress=1.0,
                                started_at=started, finished_at=self._time())
        res = await self._ensure_rail(coerced.get("Rail_Target_Position"), adef.name, rid, started)
        if res is not None:
            return res                       # 读失败/未回零/移轨被拒: 直接回传
        return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.DONE,
                            accepted=True, message="地轨已在位/已到位", progress=1.0,
                            started_at=started, finished_at=self._time())

    # ------------------------------------------------------------------
    # 机器人运动中止原语 (供 VmController 在流程运动中抢发; 均不占 action 锁)
    # ------------------------------------------------------------------

    async def robot_pause(self) -> None:
        """暂停在飞运动 (Pause): 机械臂在轨迹中途冻结, 配合 robot_resume 续跑。

        best-effort: 无在飞运动时机器人会拒 Pause (Dobot ErrorID=-1), 视作"已无可暂停"良性空操作,
        不打断流程 —— 暂停的目的就是让臂停下, 臂本就不在动即已达成。故 strict=False。
        """
        await self._robot_preempt("pause", strict=False)

    async def robot_resume(self) -> None:
        """恢复被冻结的运动 (Continue): 从冻结点无缝续跑。

        best-effort: 无被冻结运动时机器人会拒 Continue, 同 pause 视作良性空操作, 不打断流程。
        """
        await self._robot_preempt("resume", strict=False)

    async def robot_stop(self) -> None:
        """软停在飞运动 (Stop): 半路停下、臂保持使能、不报警; 在飞 move 以中止收尾。"""
        await self._robot_preempt("stop")

    async def robot_estop(self, pressed: bool = True) -> None:
        """急停 (EmergencyStop): 立即停 + 失能臂报警, 释放后需清警重新使能。"""
        await self._robot_preempt("emergency_stop", pressed)

    async def _robot_preempt(self, method_name: str, *args, strict: bool = True) -> None:
        """把机器人中止类命令 (stop/pause/resume/estop) 经线程池异步抢发 (命令口自有锁, 可与在飞 move 并发)。

        机器人离线/断链时安全跳过 (best-effort): 中止类命令的目的就是让臂停下, 臂够不着即已停;
        连接级失败 (RobotTransportError 未连接 / OSError 断链) 不得反噬调用方 —— 否则机器人 offline 时
        VmController 的 terminate/reset/estop/pause/resume 会被抛错整体阻断, 运行永远无法收尾/复位
        (真机现场"点复位无效、报错反复"即此)。机器人在线但拒绝命令 (RobotActionError, 是
        RobotTransportError 的子类) 默认是真错, 照常上抛, 不掩盖。与 transport._mark_uncertain_on_io_error
        同一"链路级才封锁、动作级拒绝不算断链"约定。

        strict=False (仅 pause/resume): 动作级拒绝 (RobotActionError) 也视作良性空操作 —— 无在飞运动时
        Pause/Continue 必被拒 (ErrorID=-1), 但"让臂冻结/续跑"的意图对空闲臂本就已满足, 不应把它当真错
        令 pause/resume 端点回 500 打断 demo 流程。
        """
        if self._robot is None:
            return
        method = getattr(self._robot, method_name, None)
        if not callable(method):
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, lambda: method(*args))
        except RobotActionError as exc:
            if strict:
                raise                               # 机器人在线且应答但拒绝: 真错, 不吞
            log.info("[executor] 机器人 %s 被拒 (无可暂停/续跑, 视作空操作): %s", method_name, exc)
        except (RobotTransportError, OSError) as exc:
            log.warning("[executor] 机器人 %s 因离线/断链跳过 (臂不可达即已停): %s", method_name, exc)

    async def plc_abort_scrape(self) -> None:
        """抢发刮取中止: 脉冲 PhotoScrape_L2_Reset, 令 PLC 熄火在跑的 CNC 插补。

        存在理由 (2026-07-26 真机复盘): A40 在 step0 锁存 CNC启动:=TRUE, 而 PLC_CNC 是独立
        PROGRAM 持续插补 —— 上位机 terminate 只停机器人和 VM 协程, 8Y 会一直跑完剩余 G-code。
        PLC 侧 PLC_MainPRG 的闸门块据本 Reset 置 CNC_AbortLatch → CNC停止(bSlow_Stop) + 撤 CNC启动。

        必须绕开工位锁直接走 PlcController.reset (它自己写 driver), 否则会排在正在跑的 A40 后面
        —— PlcController.execute 的 asyncio.shield 会等在飞动作跑完, 那样抢占就失去意义。

        best-effort: 与 _robot_preempt 同立场 —— 中止类命令的连接级失败不得反噬调用方, 否则
        PLC 离线时 terminate/estop 会被整体阻断, 运行永远无法收尾。
        """
        if self._plc is None:
            return
        try:
            await self._plc.reset("photoscrape")
        except Exception as exc:  # noqa: BLE001 中止类命令: 任何失败都降级跳过, 不阻断 terminate
            log.warning("[executor] 刮取中止抢发失败 (已降级跳过, 不阻断终止): %s", exc)

    # ------------------------------------------------------------------
    # PLC L2 调度
    # ------------------------------------------------------------------

    async def _exec_plc_l2(self, adef: ActionDef, coerced: dict, rid: str, started: float) -> ActionResult:
        if self._plc is None:
            return self._reject(adef.name, rid, RejectCode.PLC_NOT_READY, "PLC 控制器未就绪", started)
        # 移轨类硬安全门: L2 Start 前臂须在 safety_anchor —— 地轨平移拖拽伸展臂有碰撞风险。
        # 确保式: 不在位时按安全邻域策略自动回零 (ensure_home), 邻域外/持真空仍硬停拒发。
        # auto_rail / rail_move_safe / 裸 rail.move 任何调用方均经此门。robot 缺失(离线)则跳过。
        if adef.safety_anchor and self._robot is not None:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, lambda: self._robot.ensure_home(adef.safety_anchor))
            except PermissionError as exc:
                return self._reject(adef.name, rid, RejectCode.UNSAFE,
                                    f"移轨前机械臂不在安全位 {adef.safety_anchor} 且无法自动回零, 拒绝下发: {exc}", started)
            except Exception as exc:
                return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR, accepted=True,
                                    message=f"移轨安全位校验异常: {exc}", started_at=started, finished_at=self._time())
        from eit_ptlc.controller.points_service import PointsCatalogError
        preload_report = None
        # 单写者兜底: 收编工位 (如地轨) 的 L2 派发器消费 *_Pos_Target 前, 先把 PC 真源写入并回读确认。
        # 防 PLC 重启后该数组归 0 → 派发器读 0 移到底端 (即时重建, 免 retain / 启动 push / 重连钩子)。
        if self._points is not None and self._points.sync_group(adef.station) is not None:
            try:
                await self._points.ensure_target_confirmed(adef.station)
            except ValueError as exc:                       # 真源越限/配置非法: 重发无益
                return self._reject(adef.name, rid, RejectCode.INVALID_PARAM,
                                    f"工位 {adef.station} 真源回读确认前校验失败, 拒绝下发: {exc}", started)
            except Exception as exc:                         # 回读不符/写失败/PLC 未就绪: 不可移动
                return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR,
                                    accepted=True, retryable=True, started_at=started,
                                    finished_at=self._time(),
                                    message=f"工位 {adef.station} 真源回读确认失败, 未下发: {exc}")
        # 固定前置目标点: 如 FeedLift 光电搜索窗口边界, 在 L2 Start 前块写并回读确认。
        if adef.preload_targets:
            if self._points is None:
                return self._reject(adef.name, rid, RejectCode.PLC_NOT_READY, "点位服务未就绪", started)
            try:
                preload_report = await self._points.push_targets_confirmed(adef.preload_targets)
            except (PointsCatalogError, ValueError) as exc:
                return self._reject(adef.name, rid, RejectCode.INVALID_PARAM,
                                    f"前置目标点位下发被拒: {exc}", started)
            except Exception as exc:                 # OPC 写失败 / 回读不符等
                return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR,
                                    accepted=True, retryable=True, started_at=started,
                                    finished_at=self._time(),
                                    message=f"前置目标点位回读确认失败, 未触发 L2: {exc}")
        # 点位引用参数 (type=point_ref) → L2 触发前据其取点表值写入 PLC *_Target flat 节点 (合并自
        # servo_target; 用哪个点位由调用方显式给定)。push_point_ref 派发普通目标点/组合点位 (后者展开为
        # 多成员整体下发), 单写者+限位校验。任一失败即不触发。
        target_ref_names = [p.name for p in adef.params if p.type == "point_ref"]
        if target_ref_names:
            if self._points is None:
                return self._reject(adef.name, rid, RejectCode.PLC_NOT_READY, "点位服务未就绪", started)
            for name in target_ref_names:
                key = coerced.pop(name, None)            # 弹出: 引用键是"用哪个点位", 非 PLC 通道值
                if key is None:
                    continue                             # required 缺失已在 _validate 拦截
                # 组合点位成员的运行前覆盖 (如点样几何 x_start/x_end/y_height): 声明为可选动作参数,
                # 名与组合成员 key 对齐; 命中即从 coerced 弹出 (不下传 PLC 通道), 作 member_overrides 透传
                # push_composite。未给的成员 (None 已被 _validate 挡在 coerced 外) → push 用点表示教基准。
                member_overrides: dict = {}
                comp = self._points.composite_entry(str(key))
                if comp is not None:
                    for m in comp.members:
                        if m.key in coerced:
                            member_overrides[m.key] = coerced.pop(m.key)
                try:
                    await self._points.push_point_ref(str(key), member_overrides=member_overrides or None)
                except (PointsCatalogError, ValueError) as exc:
                    return self._reject(adef.name, rid, RejectCode.INVALID_PARAM,
                                        f"点位引用 {name}={key} 下发被拒: {exc}", started)
                except Exception as exc:                 # OPC 写失败等
                    return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR,
                                        accepted=True, started_at=started, finished_at=self._time(),
                                        message=f"点位 {key} 下发失败: {exc}")
        # 孔板孔位寻址 (上样吸液/润洗混匀): (规格+盘位号) → 标定实例, 孔号 → 仿射 xy, 触发前写 Sampling_4X/3Y_Target
        # (单写者 + 软限位, 结构对齐上面 point_ref→push)。三参数 (PLATE_WELL_PARAMS) 由本块消费, 不下传 PLC 通道。
        if all(n in {p.name for p in adef.params} for n in PLATE_WELL_PARAMS):
            if self._calibration is None:
                return self._reject(adef.name, rid, RejectCode.PLC_NOT_READY, "标定服务未就绪", started)
            from eit_ptlc.controller.plate_affine import parse_well
            from eit_ptlc.controller.plate_catalog import PlateCatalogError
            spec = coerced.pop("plate_spec")
            no = coerced.pop("plate_no")
            well_str = coerced.pop("well")
            try:
                inst = self._calibration.catalog.instance_for(str(spec), int(no))
                plate = self._calibration.catalog.plate_types()[inst.plate_type]
                well = parse_well(plate, str(well_str))           # 字母+数字 → Well, 越界即抛
                await self._calibration.push_well(inst.id, well)   # 仿射算 xy + 软限位 + 写 *_Target
            except (PlateCatalogError, ValueError) as exc:        # 无实例/未标定/越界/格式错: 重发无益
                return self._reject(adef.name, rid, RejectCode.INVALID_PARAM,
                                    f"孔位寻址被拒 (规格={spec} 盘位={no} 孔={well_str}): {exc}", started)
            except Exception as exc:                              # OPC 写失败等
                return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR,
                                    accepted=True, started_at=started, finished_at=self._time(),
                                    message=f"孔位 {spec}/{no}/{well_str} 下发失败: {exc}")
        from eit_ptlc.controller.plc_controller import (
            PLCActionError,
            PLCActionOutcomeUnknown,
            PLCActionState,
        )
        # 泵动作: 语义参数 (体积/配比/次数/速度延时) 经 PUMP_PROFILES builder 翻译为注射泵 DT 指令通道;
        # 非泵动作无 profile, channels 即原始已校验参数, 但按 param.channel 声明式别名重映射键 (A4),
        # 让用户面语义参数名 (如 target_tank) 在下发时还原为 PLC 通道名 (Expand_Target_Tank).
        channels = coerced
        profile = PUMP_PROFILES.get(adef.name)
        if profile is not None:
            try:
                channels = profile.build(coerced)
            except (KeyError, ValueError, TypeError) as exc:
                return self._reject(adef.name, rid, RejectCode.INVALID_PARAM,
                                    f"泵参数翻译失败: {exc}", started)
        else:
            alias = {p.name: p.channel for p in adef.params if p.channel}
            if alias:
                channels = {alias.get(k, k): v for k, v in coerced.items()}
        try:
            r = await self._plc.execute(adef.station, adef.action_code, channels,
                                        timeout=adef.action_timeout,
                                        stall_timeout=adef.stall_timeout)
        except PLCActionError as exc:
            res = exc.result
            status = ActionStatus.CANCELLED if res.state is PLCActionState.INTERRUPTED else (
                ActionStatus.REJECTED if res.state is PLCActionState.REJECTED else ActionStatus.ERROR)
            # 错误码释义并进 message 而不是留给调用方: 事件流/运行历史/回放与 HTTP 响应
            # 是同一条 message 的四个消费者, 加在源头才四处一致 (见 action/plc_error_hints.py)
            message = str(exc)
            hint = describe_plc_error(adef.station, adef.action_code, res.error_code,
                                      res.step, context=self._error_hint_context)
            if hint:
                message = f"{message} —— {hint}"
            return ActionResult(action=adef.name, request_id=rid, status=status,
                                accepted=res.state is not PLCActionState.REJECTED,
                                reject_code=RejectCode.BUSY.value if res.state is PLCActionState.REJECTED else None,
                                error_code=res.error_code, message=message, step=res.step,
                                retryable=res.retryable, safe_state=res.safe_state.name,
                                started_at=started, finished_at=self._time())
        except PLCActionOutcomeUnknown as exc:
            return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.TIMEOUT, accepted=True,
                                message=f"结果不明确, 禁止自动重发: {exc}", retryable=False,
                                started_at=started, finished_at=self._time())
        result = {"request_seq": r.request_seq, "action_code": r.action_code}
        if preload_report is not None:
            result["preload_targets"] = preload_report
        return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.DONE, accepted=True,
                            message="完成", progress=1.0, step=r.step, safe_state=r.safe_state.name,
                            result=result, started_at=started, finished_at=self._time())

    # ------------------------------------------------------------------
    # servo_target 调度 (PC 侧 flat 目标点位下发; B 方案单写者, 不进 L2 FSM)
    # ------------------------------------------------------------------

    async def _exec_servo_target(self, adef: ActionDef, rid: str, started: float) -> ActionResult:
        """按 adef.targets 顺序把各 plc_servo_target 的存储 value 写入 PLC *_Target flat 节点。

        排在消费它的 L2 动作 (吸液/点样/拍照) 触发之前, 保证 _Target 在 Start 前稳定
        (见 PLC 交付文档「写/读时序契约」)。任一点位下发失败即整体 ERROR。
        """
        if self._points is None:
            return self._reject(adef.name, rid, RejectCode.PLC_NOT_READY, "点位服务未就绪", started)
        from eit_ptlc.controller.points_service import PointsCatalogError
        written = []
        for key in adef.targets:
            try:
                r = await self._points.push_target(key)
                written.append(r)
            except (PointsCatalogError, ValueError) as exc:
                return self._reject(adef.name, rid, RejectCode.INVALID_PARAM,
                                    f"目标点位 {key} 下发被拒: {exc}", started)
            except Exception as exc:  # OPC-UA 写失败等
                return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR, accepted=True,
                                    message=f"目标点位 {key} 下发失败: {exc}", started_at=started,
                                    finished_at=self._time())
        return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.DONE, accepted=True,
                            message="完成", progress=1.0, result={"written": written},
                            started_at=started, finished_at=self._time())

    # ------------------------------------------------------------------
    # plc_write 调度 (flat 节点块写 + 回读确认; 单写者, 不进 L2 FSM)
    # ------------------------------------------------------------------

    async def _exec_plc_write(self, adef, coerced: dict, rid: str, started: float) -> ActionResult:
        """按 adef.fields 把动作 args 映射到 PLC 节点, 块写并逐字段回读确认。

        fields[].key 缺失即拒绝; 数组/标量类型由 PLC 节点表决定 (driver 内部强转)。
        回读不符 (PLCWriteConfirmError) → ERROR(retryable, 同值幂等可重发)。
        """
        if self._driver is None:
            return self._reject(adef.name, rid, RejectCode.PLC_NOT_READY, "PLC 驱动未就绪", started)
        from eit_ptlc.driver.opcua_driver import PLCWriteConfirmError

        # fields[].key → fields[].node 映射; 校验所有声明字段都有 arg
        node_values: dict = {}
        for fld in adef.fields:
            if fld.key not in coerced:
                return self._reject(adef.name, rid, RejectCode.INVALID_PARAM,
                                    f"plc_write 缺少字段 {fld.key} (节点 {fld.node})", started)
            node_values[fld.node] = coerced[fld.key]
        unknown = set(coerced) - {f.key for f in adef.fields}
        if unknown:
            return self._reject(adef.name, rid, RejectCode.INVALID_PARAM,
                                f"plc_write 未知字段: {sorted(unknown)}", started)

        kwargs = {} if adef.atol is None else {"atol": adef.atol}
        try:
            report = await self._driver.write_block_confirmed(node_values, **kwargs)
        except PLCWriteConfirmError as exc:
            return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR, accepted=True,
                                message=f"回读确认失败: {exc}", retryable=True,
                                started_at=started, finished_at=self._time())
        return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.DONE, accepted=True,
                            message="完成", progress=1.0,
                            result={"written": list(node_values), "confirm": report},
                            started_at=started, finished_at=self._time())

    # ------------------------------------------------------------------
    # 相机调度 (拍照到样品目录; profile 预填 + 逐项覆写)
    # ------------------------------------------------------------------

    # 拍照"控制"参数 (定位拍照目标), 其余声明参数皆视为相机参数覆盖 (profile 基线之上)
    _CAMERA_CONTROL_KEYS = {"sample_id", "save_dir", "filename", "profile"}

    async def _exec_camera(self, adef, coerced: dict, rid: str, started: float) -> ActionResult:
        """拍照动作: sample_id/save_dir/filename/profile 为控制参数, 余者为相机参数覆盖。"""
        if self._camera is None:
            return self._reject(adef.name, rid, RejectCode.PLC_NOT_READY, "相机控制器未就绪", started)
        save_dir = coerced.get("save_dir")
        if not save_dir:
            return self._reject(adef.name, rid, RejectCode.INVALID_PARAM, "camera 动作缺少 save_dir", started)
        from pathlib import Path
        sample_id = str(coerced.get("sample_id", ""))
        filename = str(coerced.get("filename", "after.jpg"))
        profile = coerced.get("profile") or None
        overrides = {k: v for k, v in coerced.items() if k not in self._CAMERA_CONTROL_KEYS}
        try:
            path = await self._camera.capture(sample_id, Path(str(save_dir)),
                                              filename=filename, profile=profile, overrides=overrides)
        except KeyError as exc:  # 未知 profile
            return self._reject(adef.name, rid, RejectCode.INVALID_PARAM, str(exc), started)
        except Exception as exc:
            return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR, accepted=True,
                                message=f"拍照失败: {exc}", started_at=started, finished_at=self._time())
        return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.DONE, accepted=True,
                            message="完成", progress=1.0, result={"image_path": str(path)},
                            started_at=started, finished_at=self._time())

    # ------------------------------------------------------------------
    # vision 调度 (视觉分析 / cnc 路径生成等纯计算; method 派发, result 回 VM)
    # ------------------------------------------------------------------

    async def _exec_vision(self, adef, coerced: dict, rid: str, started: float) -> ActionResult:
        """vision 动作: 按 adef.method 派发到注入的计算函数, 校验后的 params 作 kwargs。

        计算函数为 async, 返回 result dict (经 assign 回 VM)。无副作用/不进 FSM。
        """
        fn = self._vision_methods.get(adef.method)
        if fn is None:
            return self._reject(adef.name, rid, RejectCode.INVALID_PARAM,
                                f"vision 动作无方法 {adef.method!r} (已注册 {sorted(self._vision_methods)})", started)
        try:
            result = await fn(**coerced)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            return self._reject(adef.name, rid, RejectCode.INVALID_PARAM, str(exc), started)
        except Exception as exc:
            log.exception("[Action] vision %s 执行异常", adef.name)
            return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.ERROR, accepted=True,
                                message=f"vision 执行异常: {exc}", started_at=started, finished_at=self._time())
        return ActionResult(action=adef.name, request_id=rid, status=ActionStatus.DONE, accepted=True,
                            message="完成", progress=1.0,
                            result=result if isinstance(result, dict) else {"value": result},
                            started_at=started, finished_at=self._time())

    # ------------------------------------------------------------------
    # 校验与工具
    # ------------------------------------------------------------------

    def _validate(self, adef: ActionDef, params: dict) -> tuple[bool, dict, str]:
        """按动作参数 schema 校验并强转; 返回 (是否通过, 强转后参数, 错误消息)."""
        coerced: dict = {}
        declared = {p.name for p in adef.params}
        unknown = set(params) - declared
        if unknown:
            return False, {}, f"未知参数: {sorted(unknown)}"
        for p in adef.params:
            # None ≡ 未提供: 可选参数走 default/跳过 (使能"未覆盖→走点表基准"的 base-by-read, 见
            # sampling.spot_band_layer 的 x_start/x_end/y_height); 必填给 None 仍落 elif p.required 报缺失。
            if p.name in params and params[p.name] is not None:
                raw = params[p.name]
            elif p.default is not None:
                raw = p.default
            elif p.required:
                return False, {}, f"缺少必填参数: {p.name}"
            else:
                continue
            try:
                value = _coerce_param(p.type, raw)
            except (ValueError, TypeError):
                return False, {}, f"参数 {p.name} 类型应为 {p.type}, 得到 {raw!r}"
            if p.type in ("int", "float"):
                if p.minimum is not None and value < p.minimum:
                    return False, {}, f"参数 {p.name}={value} 小于下限 {p.minimum}"
                if p.maximum is not None and value > p.maximum:
                    return False, {}, f"参数 {p.name}={value} 超过上限 {p.maximum}"
            # 取值域与 type 正交: 只看 options 有没有, 不要求 type=="enum"。
            # 这样 type: int 的参数 (如 rail.move 的 Rail_Target_Position, 必须保持 int 才能
            # 喂 PLC) 也能声明取值域并在此拦下。
            err = check_enum(p.options, value, coerce=lambda v, t=p.type: _coerce_param(t, v))
            if err:
                return False, {}, f"参数 {p.name}: {err}"
            coerced[p.name] = value
        return True, coerced, ""

    def _reject(self, name: str, rid: str, code: RejectCode, msg: str, started: Optional[float] = None) -> ActionResult:
        return ActionResult(action=name, request_id=rid, status=ActionStatus.REJECTED, accepted=False,
                            reject_code=code.value, message=msg,
                            started_at=started, finished_at=self._time())


def _coerce_param(ptype: str, raw):
    if ptype == "int":
        return int(raw)
    if ptype == "float":
        return float(raw)
    if ptype == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in ("true", "1", "yes", "on")
        return bool(raw)
    return str(raw) if ptype in ("string", "enum", "point_ref") else raw


def _feedback_to_dict(feedback) -> dict:
    """把 RobotFeedback (或 None) 序列化为结构化结果 dict."""
    if feedback is None:
        return {}
    out: dict = {}
    for attr in ("pose", "joint", "robot_mode", "command_id", "last_action"):
        if hasattr(feedback, attr):
            value = getattr(feedback, attr)
            out[attr] = list(value) if isinstance(value, tuple) else value
    ts = getattr(feedback, "tool_state", None)
    if ts is not None:
        out["tool_state"] = {"commanded_bits": ts.commanded_bits, "actual_bits": ts.actual_bits,
                             "di_confirmed": ts.di_confirmed,
                             "do_bits": getattr(ts, "do_bits", 0),
                             "mounted_tool": getattr(ts, "mounted_tool", 0),
                             # 吸盘真空状态: commanded_bits 的 DO3 语义位 (值 2); 真空在 = 疑似吸着板子
                             # VM 表达式无位运算, 故在此派生为布尔供换刀守卫读取
                             "suction_on": bool(ts.commanded_bits & 2)}
    return out
