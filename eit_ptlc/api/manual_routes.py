"""单点控制路由 (PC Manual Mode)
================================
功能:
    注册单点控制端点到 FastAPI. 从 app.state.manual (ManualService) 读取;
    未就绪 (点表缺失 / PLC 未连接) 返回 503。

端点 (前缀 /api/manual):
    POST /manual/session/enter        进入单点模式 (DEBUG 门控; 前置不满足 409)
    POST /manual/session/exit         退出并清扫 (不限模式 —— 安全方向永远放行)
    POST /manual/session/keepalive    前端心跳, 刷新会话 TTL
    GET  /manual/points[?station=]    点表回显 (纯内存, 不限模式)
    GET  /manual/state[?station=]     会话态 + 全局状态 + 气缸/轴实时值 (不限模式)
    POST /manual/cylinder/{id}        {on: bool} 置执行器电平二态
    POST /manual/axis/{id}/jog/start  {direction: pos|neg} 按住点动开始
    POST /manual/axis/{id}/jog/keep   续订点动窗口 (前端按住期间 ~300ms 一次)
    POST /manual/axis/{id}/jog/stop   松开点动 (不限模式)
    POST /manual/axis/{id}/stop       停止该轴 (不限模式)
    POST /manual/axis/{id}/reset      轴清错 (不限模式)
    POST /manual/axis/{id}/home       单轴回零
    POST /manual/axis/{id}/move       {mode: abs|rel, target, vel?} 定位
    POST /manual/home_all             {confirm: true} 一键回原点 (全轴)
    POST /manual/machine/stop         {confirm: true} 停机 (脉冲 PLCStop, 等效柜面「停止」)
    POST /manual/machine/resume       {confirm: true} 恢复运行 (脉冲 PLCStart, 等效柜面「启动」)

设计偏离说明:
    docs/pTLC下一阶段_生产调度与设备节点_完整落地计划.md 约定"设备节点页不增加第二套
    直接驱动按钮, 必须走统一 Action API"。本功能是用户明确要求的例外: HMI 手动位是
    **电平**、点动是**按住持续**, 与"一发一终态"的 Action 模型不适配。补偿措施:
    (1) 每次下发都发 operation_* 审计事件进事件总线, 监视器/态势条可见;
    (2) 与 L2 动作 / VM 流程 / PLC 部署三重互斥 (见 ManualService.exclusion_reason
        与 executor 的 manual_guard);
    (3) 写类端点 DEBUG 门控, 且必须先建立会话 (PLC 侧 PC_Manual_Active 为唯一权威)。

错误码:
    503 服务未就绪; 403 非 DEBUG 模式; 409 前置条件不满足 / 会话未激活;
    404 未知执行器或轴; 422 请求体非法
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.controller.manual_service import ManualSessionError

log = logging.getLogger(__name__)


def register_manual_routes(app: FastAPI) -> None:
    """把单点控制端点注册到 app (须在 _mount_spa 之前调用)."""

    def _svc(request: Request):
        svc = getattr(request.app.state, "manual", None)
        if svc is None:
            raise HTTPException(503, "单点控制未就绪 (点表未加载或 PLC 未连接)")
        return svc

    def _require_debug(request: Request) -> None:
        if getattr(request.app.state, "control_mode", None) != "DEBUG":
            raise HTTPException(403, "单点控制仅在 DEBUG 模式可用")

    async def _guarded(coro):
        """把服务层异常翻译成 HTTP 状态码."""
        try:
            return await coro
        except ManualSessionError as exc:
            raise HTTPException(409, str(exc))
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except (RuntimeError, TimeoutError, OSError) as exc:
            raise HTTPException(502, f"PLC 通讯失败: {exc}")

    # ---- 会话 ----

    @app.post("/api/manual/session/enter")
    async def manual_enter(request: Request):
        """进入单点模式: 只读空闲检查 -> 置 Enable -> 等 PLC 回 Active."""
        _require_debug(request)
        return await _guarded(_svc(request).enter())

    @app.post("/api/manual/session/exit")
    async def manual_exit(request: Request):
        """退出单点模式并清扫全部命令位 (不限模式: 收敛动作永远放行)."""
        return await _guarded(_svc(request).exit(reason="用户主动退出"))

    @app.post("/api/manual/session/keepalive")
    async def manual_keepalive(request: Request):
        """前端心跳; 停发 3.5s 后端优雅退出, 停发 3s PLC 侧看门狗兜底清扫."""
        return await _guarded(_svc(request).keepalive())

    # ---- 只读 ----

    @app.get("/api/manual/points")
    async def manual_points(request: Request, station: str | None = None):
        """点表回显 (纯内存): 前端据此渲染面板结构."""
        return _svc(request).points(station)

    @app.get("/api/manual/state")
    async def manual_state(request: Request, station: str | None = None):
        """会话态 + 全局状态 + 该工位气缸/轴实时值 (一次批量读)."""
        return await _guarded(_svc(request).state(station))

    # ---- 执行器 ----

    @app.post("/api/manual/cylinder/{cyl_id}")
    async def manual_cylinder(request: Request, cyl_id: str, body: dict):
        """置执行器电平二态: {on: bool}. 同时写手动位与自动位 (两档都能操作)."""
        _require_debug(request)
        if "on" not in body:
            raise HTTPException(422, "缺少字段 on")
        return await _guarded(_svc(request).cylinder_set(cyl_id, bool(body["on"])))

    # ---- 伺服轴 ----

    @app.post("/api/manual/axis/{axis_id}/jog/start")
    async def manual_jog_start(request: Request, axis_id: str, body: dict):
        """按住点动开始: {direction: pos|neg}. 需 ~300ms 续订, 否则 0.8s 自动松开."""
        _require_debug(request)
        direction = str(body.get("direction") or "")
        return await _guarded(_svc(request).jog_start(axis_id, direction))

    @app.post("/api/manual/axis/{axis_id}/jog/keep")
    async def manual_jog_keep(request: Request, axis_id: str):
        """续订点动窗口 (按住期间周期调用)."""
        _require_debug(request)
        return await _guarded(_svc(request).jog_keep(axis_id))

    @app.post("/api/manual/axis/{axis_id}/jog/stop")
    async def manual_jog_stop(request: Request, axis_id: str):
        """松开点动 (不限模式: 停止是安全方向)."""
        return await _guarded(_svc(request).jog_stop(axis_id))

    @app.post("/api/manual/axis/{axis_id}/stop")
    async def manual_axis_stop(request: Request, axis_id: str):
        """停止该轴并撤全部运动命令位 (不限模式)."""
        return await _guarded(_svc(request).axis_stop(axis_id))

    @app.post("/api/manual/axis/{axis_id}/reset")
    async def manual_axis_reset(request: Request, axis_id: str):
        """轴清错 (不限模式: 清错是收敛方向)."""
        return await _guarded(_svc(request).axis_reset(axis_id))

    @app.post("/api/manual/axis/{axis_id}/home")
    async def manual_axis_home(request: Request, axis_id: str):
        """单轴回零 (PLC 回零完成时自清命令位)."""
        _require_debug(request)
        return await _guarded(_svc(request).axis_home(axis_id))

    @app.post("/api/manual/axis/{axis_id}/move")
    async def manual_axis_move(request: Request, axis_id: str, body: dict):
        """定位: {mode: abs|rel, target: float, vel?: float}; vel 按点表 vel_max 限幅."""
        _require_debug(request)
        if "target" not in body:
            raise HTTPException(422, "缺少字段 target")
        try:
            target = float(body["target"])
            vel = float(body["vel"]) if body.get("vel") is not None else None
        except (TypeError, ValueError):
            raise HTTPException(422, "target / vel 必须是数字")
        return await _guarded(
            _svc(request).axis_move(axis_id, str(body.get("mode") or "abs"), target, vel))

    # ---- 设备状态机启停 (与柜面按钮并联; 会真的停/开产线, 故双重确认) ----

    @app.post("/api/manual/machine/stop")
    async def manual_machine_stop(request: Request, body: dict):
        """从界面停机 (脉冲 PLCStop, 等效柜面「停止」), 好让单点模式能进; 须 confirm=true.

        单点模式要求 MODE_State<>运行 —— 没有这个端点, 操作工每次调试都得跑去柜子按停止。
        有流程/L2 动作在跑时拒绝 (409), 免得把它冻在半路。
        """
        _require_debug(request)
        if not body.get("confirm"):
            raise HTTPException(422, "停机会中断生产, 须显式 confirm=true")
        return await _guarded(_svc(request).request_stop())

    @app.post("/api/manual/machine/resume")
    async def manual_machine_resume(request: Request, body: dict):
        """恢复运行 (脉冲 PLCStart, 等效柜面「启动」); 须先退出单点会话且在自动档; confirm=true."""
        _require_debug(request)
        if not body.get("confirm"):
            raise HTTPException(422, "恢复运行会让设备重新接受流程派发, 须显式 confirm=true")
        return await _guarded(_svc(request).resume_run())

    # ---- 一键回原点 ----

    @app.post("/api/manual/home_all")
    async def manual_home_all(request: Request, body: dict):
        """一键回原点 (全轴按 PLC 内既定次序); 须显式 {confirm: true}."""
        _require_debug(request)
        if not body.get("confirm"):
            raise HTTPException(422, "一键回原点须显式 confirm=true")
        return await _guarded(_svc(request).home_all())
