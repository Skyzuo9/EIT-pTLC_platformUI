"""单点控制服务 (PC Manual Mode)
================================
功能:
    把 HMI 手动屏的"每模块单点操作"搬到上位机: 会话握手 + 气缸电平二态 + 伺服轴
    点动/回零/定位 + 一键回原点 + 状态批量回显。

与统一 Action 通道的关系:
    动作目录 (config/actions/) 走的是"一发一终态"的 L2 原子动作, 语义上是脉冲;
    而 HMI 手动位是**电平** (阀通电即保持), 点动是**按住持续**, 两者不适配同一模型,
    故单点控制独立成一条通道。补偿措施: 每次下发都发 operation_* 审计事件进事件总线
    (监视器可见), 且与 L2 动作 / VM 流程 / PLC 部署三重互斥。

三层防卡死 (OPC UA 写进去的是电平, 断链后 PLC 侧不会自己松开):
    1. 前端 pointerup/blur 立即发 jog_stop
    2. 后端 jog deadline (0.8s 不续订即清位) + 会话 TTL (前端停发心跳即优雅退出)
    3. PLC 侧 PLC_PCManual 的 3s 心跳看门狗 + Active 下降沿清扫全部命令位

PLC 真源: Application/40_Man/PLC_PCManual (握手/判定/清扫)
点表真源: config/manual_points.yaml
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from eit_ptlc.config.models import ManualAxis, ManualCylinder, ManualPointMap, ManualRef

log = logging.getLogger(__name__)

# PLC_PCManual.PC_Manual_Reject 的取值释义 (与 POU 内 CASE 一一对应)
REJECT_TEXT = {
    0: "",
    1: "上位机心跳超时",
    2: "有工位 L2 动作正在运行",
    3: "PLC 未就绪 (PLC_Ready=FALSE)",
    4: "PLC 处于下载握手窗口",
}

# 轴的运动命令位; 清扫时统一置 FALSE (不含 xStop/XReset —— 安全与清错方向)
_AXIS_CMD_BITS = ("xJogPos", "xJogNeg", "xMoveAbs", "xMoveRel", "xHome")

_JOG_TTL = 0.8          # jog 续订窗口: 前端每 300ms 续一次, 超时即松开
_SESSION_TTL = 3.5      # 前端心跳 TTL: 每秒一次, 停发即优雅退出
_PLC_BEAT_PERIOD = 1.0  # 往 PLC 写心跳的周期 (PLC 侧 3s 判死)
_WATCHDOG_TICK = 0.2
_ACTIVE_WAIT = 2.0      # enter 后等 PC_Manual_Active 起来的上限
_MOVE_TIMEOUT = 60.0
_HOME_TIMEOUT = 120.0
# 设备状态机 (GVL.MODE_State): 0=停止 1=运行 2=故障 3=急停 4=初始化
_MODE_RUNNING = 1
# signal_light 事件的采集源. 原始色位(三色灯红/黄/绿, %QX0.0-0.2)已证实与实体灯
# 脱钩(2026-08-02 取证: 运行版 FB_Mode 在运行态误置红位恒 TRUE 而实体红灯不亮),
# 故颜色改由 MODE_State 状态机推导; 蜂鸣器位未见污染, 仍读原始输出位.
_SIGNAL_REFS = ("mode_state", "signal_buzzer")
# MODE_State -> 塔灯表现. 依据 PLC FB_Mode 源码与活值取证:
#   故障 = `bRed := bFlashFlag`(tFlashTimer T#500MS 翻转 = 1Hz 闪烁);
#   停止态黄灯块(自动常亮/手动闪烁, 此处简化为常亮); 运行=绿为活值验证.
# 急停常亮 / 初始化黄闪按惯例暂定 —— 真机验收若与实体灯不符, 只改这张表.
_SIGNAL_BY_MODE = {
    0: {"red": False, "yellow": True, "green": False, "flash": False},   # 停止 = 黄
    1: {"red": False, "yellow": False, "green": True, "flash": False},   # 运行 = 绿
    2: {"red": True, "yellow": False, "green": False, "flash": True},    # 故障 = 红闪
    3: {"red": True, "yellow": False, "green": False, "flash": False},   # 急停 = 红
    4: {"red": False, "yellow": True, "green": False, "flash": True},    # 初始化 = 黄闪
}
# 未知模式码的兜底: 全灭(熄灯), 不猜色
_SIGNAL_UNKNOWN_MODE = {"red": False, "yellow": False, "green": False, "flash": False}
_STOP_WAIT = 5.0     # 脉冲 PLCStop 后等 MODE_State 落出运行态
_START_WAIT = 15.0   # 脉冲 PLCStart 后等进运行态 (FB_Mode 的初始化态要占 3s)
_PULSE_HOLD = 0.3
# 判运动终态前的沉降: 至少覆盖几个 PLC 扫描周期, 让 MC_* 的 Done 从上一次运动的
# 残留电平翻下去; 短于这个值会把刚发出的命令当场撤掉。
_CMD_SETTLE = 0.4


class ManualSessionError(RuntimeError):
    """会话前置条件不满足 (路由据此回 409)."""


class ManualService:
    """单点控制会话与下发通道 (单例, 挂 app.state.manual)."""

    def __init__(
        self,
        *,
        driver,
        plc=None,
        manual_map: ManualPointMap,
        bus=None,
        maintenance_gate=None,
        vm_provider: Optional[Callable[[], object]] = None,
        stations: tuple[str, ...] = (),
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self._driver = driver
        self._plc = plc
        self._map = manual_map
        self._bus = bus
        self._gate = maintenance_gate
        self._vm_provider = vm_provider
        self._l2_stations = tuple(stations)
        self._time = time_fn

        self._container_paths: dict[str, tuple[str, ...]] = {}
        self._enabled = False                     # 会话已请求 (不等于 PLC 已生效)
        self._lease = None                        # MaintenanceGate 活动租约
        self._ttl_deadline = 0.0
        self._last_beat = 0.0
        self._beat_value = 0
        self._watchdog: Optional[asyncio.Task] = None
        self._jog_deadline: dict[str, float] = {}
        self._bg: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()               # 串行化 enter/exit, 防重入

    # ------------------------------------------------------------------
    # 路径解析
    # ------------------------------------------------------------------

    async def _container(self, key: str) -> tuple[str, ...]:
        """解析容器完整路径, 按 containers.search 候选前缀依次探测并缓存.

        存在理由: 符号表里 GVL 与 PROGRAM 实例都平铺在 Application 下, 但 OPC UA
        browse 树给 GVL 插了一层 GlobalVars, PROGRAM 实例是否同插无法离线判定。
        """
        cached = self._container_paths.get(key)
        if cached is not None:
            return cached
        name = self._map.containers.get(key)
        if name is None:
            raise KeyError(f"manual_points.containers.names 缺少容器 {key!r}")
        errors = []
        for prefix in self._map.search:
            path = self._map.root + prefix + (name,)
            try:
                await self._driver.resolve_ext_node(path)
            except KeyError as exc:
                errors.append(f"{'/'.join(path)}: {exc}")
                continue
            self._container_paths[key] = path
            return path
        raise KeyError(f"容器 {key}={name} 未找到; 已试: {'; '.join(errors)}")

    async def _ref_path(self, ref: ManualRef) -> tuple[str, ...]:
        return (await self._container(ref.container)) + (ref.name,)

    async def _axis_path(self, axis: ManualAxis, member: str) -> tuple[str, ...]:
        return (await self._container("servo")) + (axis.struct, member)

    async def _host_path(self, key: str) -> tuple[str, ...]:
        host = self._map.host
        return (await self._container(host["container"])) + (host[key],)

    # ------------------------------------------------------------------
    # 审计事件 (形状对齐 api/app.py 的 _execute_with_live_events)
    # ------------------------------------------------------------------

    def _emit(self, event: dict) -> None:
        if self._bus is not None:
            try:
                self._bus.publish(event)
            except Exception as exc:
                log.debug("[Manual] 事件发布失败 (忽略): %s", exc)

    def _audit(self, operation: str, label: str, result: Optional[dict] = None,
               *, ok: bool = True, message: str = "") -> None:
        """把一次单点下发合成一组 operation_* 事件, 让监视器/态势条能看到."""
        rid = f"manual-{int(self._time() * 1000) % 10**9:09d}"
        ts = self._time()
        self._emit({"type": "operation_start", "operation": operation, "atomic": True,
                    "run_id": rid, "label": label, "ts": ts})
        self._emit({"type": "step_done", "run_id": rid, "step": "m1", "action": operation,
                    "index": 0, "status": "DONE" if ok else "FAILED",
                    "message": message, "result": result or {}, "ts": ts})
        self._emit({"type": "operation_done" if ok else "operation_failed",
                    "operation": operation, "run_id": rid,
                    "status": "DONE" if ok else "FAILED", "message": message, "ts": ts})

    # ------------------------------------------------------------------
    # 会话
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """会话是否已请求 (供 executor 互斥判定; 不等于 PLC 侧已生效)."""
        return self._enabled

    def exclusion_reason(self) -> Optional[str]:
        """executor 的互斥回调: 会话激活时返回原因串, 否则 None."""
        if not self._enabled:
            return None
        return "PC 单点控制会话激活中 (请先退出单点模式再执行动作/流程)"

    async def _preconditions(self) -> list[str]:
        """进入前的只读空闲检查 (与 bootstrap._deploy_idle_guard 同一套判据)."""
        reasons: list[str] = []
        vm = self._vm_provider() if self._vm_provider else None
        if vm is not None:
            try:
                runs = vm.active().get("runs", [])
                if runs:
                    reasons.append("流程仍在运行: " + ", ".join(
                        str(r.get("run_id", "?")) for r in runs[:5]))
            except Exception as exc:
                reasons.append(f"无法确认流程空闲: {exc}")
        if self._plc is not None and self._plc.has_active_actions():
            reasons.append("上位机仍有 PLC L2 动作占用工位")
        for station in self._l2_stations:
            try:
                state = int(await self._driver.read_variable(f"{station}_L2_State"))
            except Exception as exc:
                reasons.append(f"无法读取 {station}_L2_State: {exc}")
                continue
            if state == 10:
                reasons.append(f"PLC 工位仍在 RUNNING: {station}")
        return reasons

    async def enter(self) -> dict:
        """请求进入单点模式; 成功返回状态快照, 前置不满足抛 ManualSessionError."""
        async with self._lock:
            if self._enabled:
                return await self.state()
            if self._gate is not None and self._gate.active:
                raise ManualSessionError(
                    f"PLC 下载维护态已锁定: {self._gate.reason or '等待 PLC 就绪'}")
            reasons = await self._preconditions()
            if reasons:
                raise ManualSessionError("；".join(reasons))

            lease = None
            if self._gate is not None:
                lease = self._gate.try_enter_activity("PC 单点控制会话")
                if lease is None:
                    raise ManualSessionError(
                        f"PLC 下载维护态已锁定: {self._gate.reason or '等待 PLC 就绪'}")

            self._lease = lease
            self._enabled = True
            self._ttl_deadline = time.monotonic() + _SESSION_TTL
            try:
                await self._beat(force=True)
                await self._driver.write_ext(await self._host_path("enable"), True, "Boolean")
                active = await self._await_active()
            except Exception:
                await self._teardown()
                raise

            if not active:
                reject = await self._read_reject()
                await self._teardown()
                raise ManualSessionError(
                    f"PLC 拒绝进入单点模式: {reject or '未知原因'}")

            self._watchdog = asyncio.create_task(self._watchdog_loop())
            self._audit("manual.session", "进入单点控制模式")
            log.info("[Manual] 已进入单点控制模式")
            return await self.state()

    async def _await_active(self) -> bool:
        deadline = time.monotonic() + _ACTIVE_WAIT
        path = await self._host_path("active")
        while time.monotonic() < deadline:
            try:
                if bool(await self._driver.read_ext(path)):
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.05)
        return False

    async def _read_reject(self) -> str:
        if not self._map.host.get("reject"):
            return ""
        try:
            code = int(await self._driver.read_ext(await self._host_path("reject")))
        except Exception:
            return ""
        return REJECT_TEXT.get(code, f"拒绝码 {code}")

    def _touch(self) -> None:
        """任一前端交互都算"人还在": 刷新会话 TTL.

        存在理由: 只认专门的 /keepalive 心跳的话, 前端在按住点动、连拨气缸这类
        密集交互期间反而可能因为心跳被排在后面而超时掉线。面板可见时的 state 轮询
        (500ms) 本身就是最可靠的存活证据, 故所有单点端点统一刷新。
        """
        if self._enabled:
            self._ttl_deadline = time.monotonic() + _SESSION_TTL

    async def keepalive(self) -> dict:
        """前端心跳: 刷新会话 TTL. 会话未激活时抛 ManualSessionError."""
        if not self._enabled:
            raise ManualSessionError("单点控制会话未激活")
        self._touch()
        return {"ok": True, "ttl_s": _SESSION_TTL}

    async def _beat(self, *, force: bool = False) -> None:
        """向 PLC 递增心跳计数 (PLC 侧只看变没变, 回绕安全)."""
        now = time.monotonic()
        if not force and (now - self._last_beat) < _PLC_BEAT_PERIOD:
            return
        self._last_beat = now
        self._beat_value = (self._beat_value + 1) % 1_000_000
        await self._driver.write_ext(
            await self._host_path("keepalive"), self._beat_value, "Int32")

    async def exit(self, reason: str = "") -> dict:
        """退出单点模式 (幂等): 清扫全部命令位 -> 撤 Enable -> 释放租约."""
        async with self._lock:
            if not self._enabled and self._lease is None:
                return {"active": False, "enabled": False}
            await self._teardown(reason=reason)
            return {"active": False, "enabled": False}

    async def _teardown(self, reason: str = "") -> None:
        """内部收口: 调用方须持 self._lock (或在 enter 的异常路径上)."""
        self._enabled = False
        task, self._watchdog = self._watchdog, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._jog_deadline.clear()
        # 取消在途的运动收口任务: 它们最长会再轮询 60s, 会话都结束了没必要还挂着
        # (它们写的是命令位置 FALSE, 方向安全, 但下面的 _sweep 已经把这些位清了)
        for task in list(self._bg):
            if not task.done():
                task.cancel()
        self._bg.clear()
        await self._sweep()
        try:
            await self._driver.write_ext(await self._host_path("enable"), False, "Boolean")
        except Exception as exc:
            log.warning("[Manual] 撤 PC_Manual_Enable 失败 (PLC 看门狗会兜底): %s", exc)
        lease, self._lease = self._lease, None
        if lease is not None and self._gate is not None:
            try:
                self._gate.leave_activity(lease)
            except Exception as exc:
                log.warning("[Manual] 释放活动租约失败: %s", exc)
        self._audit("manual.session", "退出单点控制模式", message=reason)
        log.info("[Manual] 已退出单点控制模式%s", f" ({reason})" if reason else "")

    async def _sweep(self) -> None:
        """把全部气缸手动位与轴运动位写 FALSE (逐点失败不中断).

        只清手动位: 自动位从头到尾没被我们碰过, 档位一还原, 各执行器自然接着听流程的 ——
        这也是退出单点不会打断在途生产状态的原因。
        """
        for cyl in self._map.cylinders.values():
            try:
                await self._driver.write_ext(
                    await self._ref_path(cyl.manual), False, "Boolean")
            except Exception as exc:
                log.warning("[Manual] 清扫 %s 失败: %s", cyl.manual.name, exc)
        for axis in self._map.axes.values():
            for member in _AXIS_CMD_BITS:
                try:
                    await self._driver.write_ext(
                        await self._axis_path(axis, member), False, "Boolean")
                except Exception as exc:
                    log.warning("[Manual] 清扫 %s.%s 失败: %s", axis.struct, member, exc)

    async def _watchdog_loop(self) -> None:
        """200ms 巡检: 续 PLC 心跳 / jog 超时松开 / 前端心跳超时优雅退出."""
        try:
            while True:
                await asyncio.sleep(_WATCHDOG_TICK)
                now = time.monotonic()

                expired = [aid for aid, dl in self._jog_deadline.items() if now >= dl]
                for aid in expired:
                    self._jog_deadline.pop(aid, None)
                    axis = self._map.axes.get(aid)
                    if axis is None:
                        continue
                    log.warning("[Manual] jog 续订超时, 强制松开: %s", axis.label)
                    for member in ("xJogPos", "xJogNeg"):
                        try:
                            await self._driver.write_ext(
                                await self._axis_path(axis, member), False, "Boolean")
                        except Exception as exc:
                            log.error("[Manual] jog 超时松开失败 %s.%s: %s",
                                      axis.struct, member, exc)

                if now >= self._ttl_deadline:
                    log.warning("[Manual] 前端心跳超时, 自动退出单点模式")
                    asyncio.create_task(self.exit(reason="前端心跳超时"))
                    return

                try:
                    await self._beat()
                except Exception as exc:
                    log.warning("[Manual] 写 PLC 心跳失败: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[Manual] 看门狗异常退出; 交由 PLC 侧 3s 看门狗兜底")

    def _require_active(self) -> None:
        if not self._enabled:
            raise ManualSessionError("单点控制会话未激活 (请先进入单点模式)")
        self._touch()

    # ------------------------------------------------------------------
    # 设备状态机启停 (与柜面按钮并联)
    #
    # A00_设备状态显示及控制 里 FB_Mode 的接线:
    #     xStart := 启动 OR PLCStart;   xStop := NOT 停止 OR PLCStop
    # 所以上位机写 PLCStop/PLCStart 与操作工按柜面按钮完全等效。二者都必须**脉冲**:
    # 一直压着 PLCStop 的话, 机器一进运行态就会被立刻打回停止。
    # 之所以要这对接口: 单点模式要求 MODE_State<>运行 (见 PLC_PCManual 的门条件),
    # 没有它操作工每次调试都得跑去柜子按一下停止。
    # ------------------------------------------------------------------

    async def _mode_state(self) -> Optional[int]:
        ref = self._map.globals_.get("mode_state")
        if ref is None:
            return None
        try:
            return int(await self._driver.read_ext(await self._ref_path(ref)))
        except Exception as exc:
            log.warning("[Manual] 读 MODE_State 失败: %s", exc)
            return None

    async def _pulse(self, node: str, wait: float, want_running: bool) -> Optional[int]:
        """脉冲一个启停位并等 MODE_State 转到目标态; 返回转态后的 MODE_State."""
        deadline = time.monotonic() + wait
        await self._driver.write_variable(node, True)
        try:
            await asyncio.sleep(_PULSE_HOLD)
            while time.monotonic() < deadline:
                mode = await self._mode_state()
                if mode is not None and (mode == _MODE_RUNNING) == want_running:
                    return mode
                await asyncio.sleep(0.2)
        finally:
            # 必须撤: PLCStop 一直为真会把机器焊死在停止态, PLCStart 同理会反复重启
            try:
                await self._driver.write_variable(node, False)
            except Exception as exc:
                log.error("[Manual] 撤 %s 失败 (机器可能被压在该状态): %s", node, exc)
        return await self._mode_state()

    async def request_stop(self) -> dict:
        """从界面停机 (等效柜面「停止」), 好让单点模式能进.

        先跑与 enter 同一套空闲检查 —— 有流程/L2 动作在跑时停机会把它冻在半路。
        """
        if self._enabled:
            raise ManualSessionError("单点会话激活中, 无需也不应再停机")
        mode = await self._mode_state()
        if mode is not None and mode != _MODE_RUNNING:
            return {"mode_state": mode, "changed": False, "message": "设备本就不在运行态"}
        reasons = await self._preconditions()
        if reasons:
            raise ManualSessionError("；".join(reasons))

        mode = await self._pulse("PLCStop", _STOP_WAIT, want_running=False)
        ok = mode is not None and mode != _MODE_RUNNING
        self._audit("manual.machine_stop", "上位机停机 (等效柜面停止)",
                    {"mode_state": mode}, ok=ok,
                    message="" if ok else f"停机后 MODE_State 仍为 {mode}")
        if not ok:
            raise ManualSessionError(f"停机未生效, MODE_State={mode}")
        log.info("[Manual] 已从上位机停机, MODE_State=%s", mode)
        return {"mode_state": mode, "changed": True}

    async def resume_run(self) -> dict:
        """恢复运行 (等效柜面「启动」); 需先退出单点会话, 且必须在自动档."""
        if self._enabled:
            raise ManualSessionError("请先退出单点模式再恢复运行")
        mode = await self._mode_state()
        if mode == _MODE_RUNNING:
            return {"mode_state": mode, "changed": False, "message": "设备已在运行态"}
        # 档位要等一小会儿再判: 刚退出单点时电子手动档 (xAutoMode := 手自动 AND NOT
        # PC_Manual_Active) 要过一个扫描周期才交还回自动, 立刻判会误报"当前是手动档"。
        auto_ref = self._map.globals_.get("manual_auto")
        if auto_ref is not None:
            path = await self._ref_path(auto_ref)
            deadline = time.monotonic() + 1.5
            is_auto = False
            while True:
                try:
                    is_auto = bool(await self._driver.read_ext(path))
                except Exception as exc:
                    log.warning("[Manual] 读档位失败, 仍尝试启动: %s", exc)
                    is_auto = True
                if is_auto or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(0.1)
            if not is_auto:
                raise ManualSessionError(
                    "当前是手动档, FB_Mode 只在自动档接受启动 —— 请先把柜面旋钮打到自动")

        mode = await self._pulse("PLCStart", _START_WAIT, want_running=True)
        ok = mode == _MODE_RUNNING
        self._audit("manual.machine_resume", "上位机恢复运行 (等效柜面启动)",
                    {"mode_state": mode}, ok=ok,
                    message="" if ok else f"启动后 MODE_State 为 {mode}")
        if not ok:
            raise ManualSessionError(
                f"恢复运行未生效, MODE_State={mode} (有故障/急停未复位时启动会被 FB_Mode 挡下)")
        log.info("[Manual] 已从上位机恢复运行")
        return {"mode_state": mode, "changed": True}

    # ------------------------------------------------------------------
    # 气缸 / 电磁阀
    # ------------------------------------------------------------------

    def cylinder(self, cyl_id: str) -> ManualCylinder:
        cyl = self._map.cylinders.get(cyl_id)
        if cyl is None:
            raise KeyError(f"未知执行器: {cyl_id}")
        return cyl

    def axis(self, axis_id: str) -> ManualAxis:
        axis = self._map.axes.get(axis_id)
        if axis is None:
            raise KeyError(f"未知轴: {axis_id}")
        return axis

    async def cylinder_set(self, cyl_id: str, on: bool) -> dict:
        """置一个执行器的电平二态.

        只写 <设备>手动 —— 单点会话生效时 PLC 已被切到电子手动档
        (A00_设备状态显示及控制 里 xAutoMode := 手自动 AND NOT PC_Manual_Active),
        FB_cylinder 走手动位分支。<设备>自动 是 L2 流程与 PLC_Pump_泵管理 的地盘,
        我们一根手指都不碰 —— 碰了就会跟它们抢, 而且 HMI 上的自动位显示会跟着乱。
        """
        self._require_active()
        cyl = self.cylinder(cyl_id)
        on = bool(on)
        await self._driver.write_ext(await self._ref_path(cyl.manual), on, "Boolean")
        self._audit(f"manual.cylinder.{cyl_id}",
                    f"{cyl.label} {'开' if on else '关'}", {"id": cyl_id, "on": on})
        return {"id": cyl_id, "on": on}

    # ------------------------------------------------------------------
    # 伺服轴
    # ------------------------------------------------------------------

    async def jog_start(self, axis_id: str, direction: str) -> dict:
        """按住点动开始; 需前端每 ~300ms 调 jog_keep 续订, 否则 0.8s 后自动松开.

        说明:
            速度不可调 —— PLC `伺服调用` 把 fJogVel 硬编码成常量, <轴>DATE.fJogVel
            并未接线, 写进去无效。点表的 jog_vel_fixed 只作只读显示。
        """
        self._require_active()
        axis = self.axis(axis_id)
        if direction not in ("pos", "neg"):
            raise ValueError(f"jog 方向非法: {direction!r} (pos|neg)")
        on_bit = "xJogPos" if direction == "pos" else "xJogNeg"
        off_bit = "xJogNeg" if direction == "pos" else "xJogPos"
        # 先撤反向位再置正向位, 避免同扫描两向同时为真
        await self._driver.write_ext(await self._axis_path(axis, off_bit), False, "Boolean")
        await self._driver.write_ext(await self._axis_path(axis, on_bit), True, "Boolean")
        self._jog_deadline[axis_id] = time.monotonic() + _JOG_TTL
        self._audit(f"manual.jog.{axis_id}", f"{axis.label} 点动{'+' if direction == 'pos' else '-'}",
                    {"id": axis_id, "direction": direction, "vel": axis.jog_vel_fixed})
        return {"id": axis_id, "direction": direction, "vel_fixed": axis.jog_vel_fixed}

    async def jog_keep(self, axis_id: str) -> dict:
        """续订点动窗口 (前端按住期间周期调用; 不发审计事件避免刷屏)."""
        self._require_active()
        self.axis(axis_id)
        if axis_id not in self._jog_deadline:
            raise ManualSessionError("该轴当前没有进行中的点动")
        self._jog_deadline[axis_id] = time.monotonic() + _JOG_TTL
        return {"id": axis_id, "ttl_s": _JOG_TTL}

    async def jog_stop(self, axis_id: str) -> dict:
        """松开点动 (安全方向: 不要求会话激活, 任何时候都放行)."""
        axis = self.axis(axis_id)
        self._jog_deadline.pop(axis_id, None)
        for member in ("xJogPos", "xJogNeg"):
            await self._driver.write_ext(await self._axis_path(axis, member), False, "Boolean")
        self._audit(f"manual.jog_stop.{axis_id}", f"{axis.label} 点动停", {"id": axis_id})
        return {"id": axis_id}

    async def axis_stop(self, axis_id: str) -> dict:
        """停止轴 (MC_Halt 脉冲) 并顺手撤掉本轴全部运动命令位; 安全方向, 不要求会话."""
        axis = self.axis(axis_id)
        self._jog_deadline.pop(axis_id, None)
        for member in _AXIS_CMD_BITS:
            await self._driver.write_ext(await self._axis_path(axis, member), False, "Boolean")
        stop_path = await self._axis_path(axis, "xStop")
        await self._driver.write_ext(stop_path, True, "Boolean")
        await asyncio.sleep(0.3)
        await self._driver.write_ext(stop_path, False, "Boolean")
        self._audit(f"manual.axis_stop.{axis_id}", f"{axis.label} 停止", {"id": axis_id})
        return {"id": axis_id}

    async def axis_reset(self, axis_id: str) -> dict:
        """轴清错 (MC_Reset 脉冲); 安全方向, 不要求会话."""
        axis = self.axis(axis_id)
        path = await self._axis_path(axis, "XReset")
        await self._driver.write_ext(path, True, "Boolean")
        await asyncio.sleep(0.3)
        await self._driver.write_ext(path, False, "Boolean")
        self._audit(f"manual.axis_reset.{axis_id}", f"{axis.label} 清错", {"id": axis_id})
        return {"id": axis_id}

    async def axis_home(self, axis_id: str) -> dict:
        """单轴回零. PLC `伺服调用` 在回零完成时自清 xHome, 这里只兜底超时清位.

        **不预清 bHomed** —— 它是 `伺服未回原点报警` 的唯一输入 (A00_设备状态显示及控制 里
        `IF NOT 任一 bHomed THEN 伺服未回原点报警 := TRUE`, 且那是**置位锁存**, 只有柜面
        `复位`/`bSysReset`/`bAutoHomeResetPulse` 能清)。预清一次就等于每回一次零都在 HMI
        留一条要人工复位的报警, 还会把整机推进 FB_Mode 的故障态。

        不清它也照样能回零: MC_Home.Execute 是 `xHome AND bNormalMotionAllowed` 的沿触发,
        Done 只反映本次执行; PLC 侧 `IF 回零完成nX THEN xHome := FALSE; bHomed := TRUE`
        会在完成时自清命令位, 正是 _clear_after 的主终态判据。所以 done_members 必须换掉
        bHomed —— 留着它, 轴本来就已回零时会在 _CMD_SETTLE 沉降后当场判"已完成"把命令撤掉。
        换成 bError 与 axis_move 同构: 故障即撤命令位, 其余交给 _HOME_TIMEOUT 兜底。
        """
        self._require_active()
        axis = self.axis(axis_id)
        await self._driver.write_ext(await self._axis_path(axis, "xHome"), True, "Boolean")
        self._spawn(self._clear_after(axis, "xHome", _HOME_TIMEOUT, ("bError",)))
        self._audit(f"manual.home.{axis_id}", f"{axis.label} 回零", {"id": axis_id})
        return {"id": axis_id}

    async def axis_move(self, axis_id: str, mode: str, target: float,
                        vel: Optional[float] = None) -> dict:
        """绝对/相对定位. vel 按点表 vel_max 限幅 (fVelocity 已接线, 可写)."""
        self._require_active()
        axis = self.axis(axis_id)
        if mode not in ("abs", "rel"):
            raise ValueError(f"定位模式非法: {mode!r} (abs|rel)")
        speed = float(vel) if vel is not None else axis.vel_max
        if speed <= 0:
            raise ValueError("定位速度必须为正")
        speed = min(speed, axis.vel_max)
        target = float(target)

        await self._driver.write_ext(await self._axis_path(axis, "fVelocity"), speed, "Double")
        target_member = "fAbsTarget" if mode == "abs" else "fRelTarget"
        await self._driver.write_ext(await self._axis_path(axis, target_member), target, "Double")
        cmd = "xMoveAbs" if mode == "abs" else "xMoveRel"
        done = "bAbMoveDone" if mode == "abs" else "bReMoveDone"
        await self._driver.write_ext(await self._axis_path(axis, cmd), True, "Boolean")
        self._spawn(self._clear_after(axis, cmd, _MOVE_TIMEOUT, (done, "bError")))
        self._audit(f"manual.move.{axis_id}", f"{axis.label} {'绝对' if mode == 'abs' else '相对'}定位",
                    {"id": axis_id, "mode": mode, "target": target, "vel": speed})
        return {"id": axis_id, "mode": mode, "target": target, "vel": speed}

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _clear_after(self, axis: ManualAxis, cmd_member: str,
                           timeout: float, done_members: tuple[str, ...]) -> None:
        """等运动终态 (或超时) 后撤命令位.

        PLCopen 的 Execute 是沿触发, 命令位不撤下次同目标就发不出去 —— 这个收口
        任务就是替 HMI 上那只"按完松手"的手。

        判终态前先沉降一段: MC_MoveAbsolute.Done 是**上一次**运动留下的电平, 命令刚
        发出去的头几个扫描周期里它还是 TRUE, 不等就会把刚下的命令当场撤掉 (实机表现
        为"点了没反应")。另外 xHome 由 PLC 的 `伺服调用` 在回零完成时自清, 故命令位
        自己变 FALSE 也算终态。
        """
        cmd_path = await self._axis_path(axis, cmd_member)
        try:
            await asyncio.sleep(_CMD_SETTLE)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    if not bool(await self._driver.read_ext(cmd_path)):
                        return          # PLC 自清 (回零) —— 已终态, 无需再写
                except Exception:
                    pass
                for member in done_members:
                    try:
                        if bool(await self._driver.read_ext(await self._axis_path(axis, member))):
                            await self._driver.write_ext(cmd_path, False, "Boolean")
                            return
                    except Exception:
                        pass
                await asyncio.sleep(0.1)
            log.warning("[Manual] %s.%s 等待终态超时 %.0fs, 强制撤命令位",
                        axis.struct, cmd_member, timeout)
            await self._driver.write_ext(cmd_path, False, "Boolean")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("[Manual] %s.%s 收口失败: %s", axis.struct, cmd_member, exc)

    # ------------------------------------------------------------------
    # 一键回原点
    # ------------------------------------------------------------------

    async def home_all(self) -> dict:
        """触发 PLC 的一键回原点 (全轴按 PLC 内既定次序); PLC 完成后自清该位.

        先撤掉本会话下发过的全部点动/定位命令位: 一键回原点在 PLC 里是给每根轴置
        xHome, 若我们还挂着 xMoveAbs, 同一个 FB 上就成了两条运动命令抢同一根轴
        (实测表现为回零刚归零又被定位拉回去)。
        """
        self._require_active()
        ref = self._map.globals_.get("one_key_home")
        if ref is None:
            raise KeyError("manual_points.globals 未声明 one_key_home")
        self._jog_deadline.clear()
        for axis in self._map.axes.values():
            for member in ("xJogPos", "xJogNeg", "xMoveAbs", "xMoveRel"):
                await self._driver.write_ext(
                    await self._axis_path(axis, member), False, "Boolean")
        await self._driver.write_ext(await self._ref_path(ref), True, "Boolean")
        self._audit("manual.home_all", "一键回原点 (全轴)")
        return {"ok": True}

    # ------------------------------------------------------------------
    # 状态回显
    # ------------------------------------------------------------------

    def points(self, station: Optional[str] = None) -> dict:
        """点表回显 (纯内存, 不碰 PLC): 前端据此渲染面板."""
        stations = [station] if station else list(self._map.stations)
        out: dict[str, dict] = {}
        for st in stations:
            cyls = self._map.station_cylinders(st)
            axes = self._map.station_axes(st)
            if not cyls and not axes:
                continue
            out[st] = {
                "cylinders": [
                    {"id": c.id, "label": c.label, "note": c.note,
                     "has_fb_on": c.fb_on is not None, "has_fb_off": c.fb_off is not None,
                     "alarm_bit": c.alarm_bit}
                    for c in cyls
                ],
                "axes": [
                    {"id": a.id, "label": a.label, "struct": a.struct,
                     "jog_vel_fixed": a.jog_vel_fixed, "vel_max": a.vel_max, "note": a.note}
                    for a in axes
                ],
            }
        return {"stations": out, "all_stations": list(self._map.stations)}

    async def realtime_snapshot(
        self,
        *,
        include_axes: bool = True,
        include_mechanisms: bool = True,
    ) -> dict:
        """批量读取孪生只读快照；不调用 ``_touch``，绝不续期手动会话。

        轴只取实际位置/速度；机构同时保留命令态与到位反馈。单次调用合并为一次
        ``read_ext_batch``，供 10–20 Hz 后台采样使用，避免逐节点网络往返。
        """
        cyls = list(self._map.cylinders.values()) if include_mechanisms else []
        axes = list(self._map.axes.values()) if include_axes else []
        paths: list[tuple[str, ...]] = []
        slots: list[tuple[str, str, str]] = []

        for axis in axes:
            for field in ("fActPos", "fActVel"):
                paths.append(await self._axis_path(axis, field))
                slots.append(("axis", axis.id, field))
        for cyl in cyls:
            for field, ref in (
                ("manual", cyl.manual),
                ("auto", cyl.auto_ro),
                ("fb_on", cyl.fb_on),
                ("fb_off", cyl.fb_off),
            ):
                if ref is None:
                    continue
                paths.append(await self._ref_path(ref))
                slots.append(("mechanism", cyl.id, field))
        # 塔灯推导源(MODE_State)与蜂鸣器位搭机构采样的顺风车(同为 10Hz 语义)
        for key in (_SIGNAL_REFS if include_mechanisms else ()):
            ref = self._map.globals_.get(key)
            if ref is None:
                continue
            paths.append(await self._ref_path(ref))
            slots.append(("signal", key, ""))

        values = await self._driver.read_ext_batch(paths) if paths else []
        raw_axes: dict[str, dict] = {axis.id: {} for axis in axes}
        raw_mechanisms: dict[str, dict] = {cyl.id: {} for cyl in cyls}
        raw_signals: dict[str, object] = {}
        for (kind, key, field), value in zip(slots, values):
            if kind == "axis":
                raw_axes[key][field] = value
            elif kind == "mechanism":
                raw_mechanisms[key][field] = value
            else:
                raw_signals[key] = value

        axis_out = {
            axis.id: {
                "position": float(raw_axes[axis.id]["fActPos"]),
                "velocity": float(raw_axes[axis.id]["fActVel"]),
            }
            for axis in axes
        }
        mechanism_out: dict[str, dict] = {}
        for cyl in cyls:
            raw = raw_mechanisms[cyl.id]
            state: dict[str, object] = {
                "commanded": bool(raw.get("manual")) or bool(raw.get("auto")),
            }
            has_on = cyl.fb_on is not None
            has_off = cyl.fb_off is not None
            on = has_on and bool(raw.get("fb_on"))
            off = has_off and bool(raw.get("fb_off"))
            if on and not off:
                state.update({"confirmed": True, "available": True, "source": "feedback"})
            elif off and not on:
                state.update({"confirmed": False, "available": True, "source": "feedback"})
            elif has_on or has_off:
                # 气缸切换途中两个到位信号都可能为 FALSE；双 TRUE 则是接线/机构冲突。
                # null 明确清掉上一到位态, 让三维视图立即回退 commanded+estimated.
                state.update({
                    "confirmed": None,
                    "available": not (on and off),
                    "source": "feedback" if not (on and off) else "feedback_conflict",
                })
            else:
                state.update({"available": True, "source": "commanded"})
            mechanism_out[cyl.id] = state

        result: dict[str, object] = {"axes": axis_out, "mechanisms": mechanism_out}
        # 颜色由 MODE_State 推导(见 _SIGNAL_BY_MODE 注释); mode 读不到(None/点表缺失)
        # 时省略 signals 键让下游不发 signal_light, 前端保持烘焙静态灯 —— 静默降级.
        mode_raw = raw_signals.get("mode_state")
        try:
            mode = int(mode_raw) if mode_raw is not None else None
        except (TypeError, ValueError):
            mode = None
        if mode is not None:
            signals: dict[str, object] = dict(_SIGNAL_BY_MODE.get(mode, _SIGNAL_UNKNOWN_MODE))
            signals["buzzer"] = bool(raw_signals.get("signal_buzzer"))
            signals["mode"] = mode
            result["signals"] = signals
        return result

    async def state(self, station: Optional[str] = None) -> dict:
        """会话态 + 全局状态 + 该工位气缸/轴的实时回显 (一次批量读)."""
        self._touch()   # 面板在轮询 = 人还在看着, 这是最可靠的存活证据
        cyls = (self._map.station_cylinders(station) if station
                else list(self._map.cylinders.values()))
        axes = (self._map.station_axes(station) if station
                else list(self._map.axes.values()))

        paths: list[tuple[str, ...]] = []
        slots: list[tuple[str, str, str]] = []   # (kind, id, field)

        for key in ("active", "reject") if self._map.host.get("reject") else ("active",):
            paths.append(await self._host_path(key))
            slots.append(("host", key, ""))
        for name, ref in self._map.globals_.items():
            paths.append(await self._ref_path(ref))
            slots.append(("global", name, ""))
        for cyl in cyls:
            for field, ref in (("manual", cyl.manual), ("auto", cyl.auto_ro),
                               ("fb_on", cyl.fb_on), ("fb_off", cyl.fb_off)):
                if ref is None:
                    continue
                paths.append(await self._ref_path(ref))
                slots.append(("cylinder", cyl.id, field))
        axis_fields = ("fActPos", "fActVel", "bEnabled", "bHomed", "bBusy",
                       "bError", "iErrorCode", "xJogPos", "xJogNeg")
        for axis in axes:
            for field in axis_fields:
                paths.append(await self._axis_path(axis, field))
                slots.append(("axis", axis.id, field))

        values = await self._driver.read_ext_batch(paths)

        host: dict[str, object] = {}
        globals_: dict[str, object] = {}
        cyl_out: dict[str, dict] = {c.id: {} for c in cyls}
        axis_out: dict[str, dict] = {a.id: {} for a in axes}
        for (kind, key, field), value in zip(slots, values):
            if kind == "host":
                host[key] = value
            elif kind == "global":
                globals_[key] = value
            elif kind == "cylinder":
                cyl_out[key][field] = value
            else:
                axis_out[key][field] = value

        # 每个执行器的报警位从 cyinderAlarm 整数按位取出
        alarm_word = globals_.get("cylinder_alarm")
        for cyl in cyls:
            if cyl.alarm_bit >= 0 and isinstance(alarm_word, int):
                cyl_out[cyl.id]["alarm"] = bool(alarm_word >> cyl.alarm_bit & 1)

        # 首次调用要解析上百个节点, 可能比一个 TTL 周期还长; 请求跑完本身就是存活证据,
        # 故收尾再刷一次, 否则会出现"面板刚拉完状态就被看门狗判死"。
        self._touch()
        reject_code = host.get("reject")
        return {
            "enabled": self._enabled,
            "active": bool(host.get("active")),
            "reject_code": reject_code,
            "reject_text": REJECT_TEXT.get(reject_code, "") if isinstance(reject_code, int) else "",
            "ttl_s": max(0.0, self._ttl_deadline - time.monotonic()) if self._enabled else 0.0,
            "globals": globals_,
            "cylinders": cyl_out,
            "axes": axis_out,
            "jogging": sorted(self._jog_deadline),
        }
