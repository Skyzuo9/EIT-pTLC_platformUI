"""FastAPI 应用 (动作 HTTP 接口)
================================
功能:
    暴露动作目录与统一动作执行为 REST 接口, 供 Vue3 前端 (运维页/流程页) 调用.
    路由从 app.state 读取 executor/registry/control_mode, 以便由 runtime 在 lifespan 中注入
    (区分 sim/real 装配). 机器人 jog/step 提供低延迟便捷端点 (维护页按住起停).

主要端点:
    GET  /api/health              健康与模式
    GET  /api/mode  POST /api/mode 读取/切换控制模式
    GET  /api/actions[?kind=]     动作目录 (UI 左栏)
    GET  /api/actions/{name}      单动作定义 (UI 右栏参数)
    PUT  /api/actions/{name}/description  定点更新动作详细说明
    PUT  /api/actions/{name}/label        定点更新动作显示名
    DELETE /api/actions/{name}            删除动作定义 (被流程引用时 400 拒绝)
    POST /api/actions/{name}/run  执行动作 -> ActionResult
    POST /api/robot/jog/start|stop, /step, /stop, /emergency_stop  机器人便捷端点
    POST /api/robot/enable, /disable, /clear_error  机器人使能 / 下使能 / 清警 (维护页; DEBUG + 配置门控)
    POST /api/robot/connect  机器人断联重连 (维护页; 不限模式, 仅重建通信)
    POST /api/robot/speed_factor  设置全局速度比 (维护页; 当前值经机器人节点遥测回显)
    GET  /api/nodes[/{id}]        设备节点清单与快照 (健康)
    GET  /api/runs[/{run_id}]     执行历史列表与单次运行事件 (回放)
    WS   /api/ws/events           VM 编排事件 (vm_*/operation_*) + 节点遥测 实时流
    GET  /api/planner/*           排程只读统计 (见 api/planner_routes.py)
    GET/POST /api/materials/*     物料账本查询 + 人工盘点 (见 api/material_routes.py)
    脚本仓库与 VM 运行/调试/HITL 端点见 api/vm_routes.py (register_vm_routes).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from eit_ptlc.action.executor import ActionExecutor
from eit_ptlc.action.models import ActionStatus
from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.dto import (
    ActionDefDTO,
    ActionDescriptionUpdate,
    ActionLabelUpdate,
    ActionResultDTO,
    RunRequest,
    action_def_to_dto,
    action_result_to_dto,
)
from eit_ptlc.api.calibration_routes import register_calibration_routes
from eit_ptlc.api.config_routes import register_config_routes
from eit_ptlc.api.feedlift_routes import register_feedlift_routes
from eit_ptlc.api.material_audit_routes import register_material_audit_routes
from eit_ptlc.api.material_routes import register_material_routes
from eit_ptlc.api.planner_routes import register_planner_routes
from eit_ptlc.api.recording_routes import register_recording_routes
from eit_ptlc.api.scheduler_routes import register_scheduler_routes
from eit_ptlc.api.sim_routes import register_sim_routes
from eit_ptlc.api.three_d_routes import register_three_d_routes
from eit_ptlc.api.plate_align_routes import register_plate_align_routes
from eit_ptlc.api.plc_program_routes import register_plc_program_routes
from eit_ptlc.api.points_routes import register_points_routes
from eit_ptlc.api.vision_debug_routes import register_vision_debug_routes
from eit_ptlc.api.vision_routes import register_vision_routes
from eit_ptlc.runtime.material_feedback import material_state_event
from eit_ptlc.api.manual_routes import register_manual_routes
from eit_ptlc.api.photoscrape_routes import register_photoscrape_routes
from eit_ptlc.api.vm_routes import register_vm_routes
from eit_ptlc.api.water_level_routes import register_water_level_routes
from eit_ptlc.config.models import ALLOWED_CONTROL_MODES

log = logging.getLogger(__name__)

# 前端构建产物: 同源托管它即可免掉 vite dev 独立窗口 (npm run build 生成)
_DIST_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"


def _mount_spa(app: FastAPI) -> None:
    """把 web/dist 挂成同源静态站点 (免 vite dev 窗口); 缺失则跳过并告警.

    功能:
        前端 api.js 用 baseURL '/' 与 location.host 组 WS, 天然同源, 故前端零改动。
    约束:
        必须在全部 register_*_routes 之后调用 —— catch-all 路由后注册才不会遮蔽
        /api/* 与 WS /api/ws/events。
    """
    index = _DIST_DIR / "index.html"
    if not index.is_file():
        log.warning("[API] 未找到 %s, 跳过前端静态托管 (先跑 npm run build, 或用 main.py --dev-frontend)",
                    index)
        return

    assets = _DIST_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    dist_root = _DIST_DIR.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str):
        """命中真实文件就发文件, 否则回 index.html 交给 vue-router 处理前端路由."""
        # 走到这里的 /api/* 说明没有任何真实路由匹配 => 必须 404。
        # 否则打错的端点会拿到 200 + HTML, axios 按 JSON 解析失败, 把"路由不存在"伪装成解析错误。
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="未知 API 路由")
        # full_path 直接来自 URL, 必须限定在 dist 内, 否则是路径穿越
        candidate = (dist_root / full_path).resolve()
        if full_path and candidate.is_relative_to(dist_root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    log.info("[API] 前端静态托管已挂载: %s", _DIST_DIR)


def create_app(
    registry: ActionRegistry,
    *,
    executor: Optional[ActionExecutor] = None,
    script_repo=None,
    vm=None,
    bus=None,
    node_registry=None,
    run_store=None,
    three_d_authoring=None,
    control_mode: str = "DEBUG",
    cors_origins: Optional[list] = None,
    lifespan=None,
) -> FastAPI:
    """构建 FastAPI 应用.

    参数:
        registry: 动作目录; executor: 动作执行器; script_repo: 脚本仓库 (ScriptRepo);
        vm: VM 控制器 (VmController); bus: 事件总线 (WebSocket 订阅源);
        control_mode: 初始控制模式; cors_origins: 跨域来源; lifespan: 异步生命周期.
        executor/script_repo/vm/bus 可为 None, 由 lifespan 注入 app.state.
        three_d_authoring: 三维工程 authoring 服务.
    返回:
        FastAPI 实例
    """
    app = FastAPI(title="eit_ptlc 上位机 API", version="0.1.0", lifespan=lifespan)
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins,
                           allow_methods=["*"], allow_headers=["*"])
    app.state.registry = registry
    app.state.executor = executor
    app.state.script_repo = script_repo
    app.state.vm = vm
    app.state.bus = bus
    app.state.node_registry = node_registry
    app.state.run_store = run_store
    app.state.three_d_authoring = three_d_authoring
    app.state.points = None  # 统一点位目录服务 (PointsService), 由 lifespan 注入
    app.state.actions = None  # 动作源文件服务 (ActionsService), 由 lifespan 注入
    app.state.config_svc = None  # 设备参数服务 (ConfigService), 由 lifespan 注入
    app.state.calibration = None  # 孔板标定/下发服务 (CalibrationService), 由 lifespan 注入
    app.state.water_level_client = None  # 液位 MQTT 客户端 (WaterLevelClient), 由 lifespan 注入
    app.state.water_level_ctrl = None    # 液位只读快照 (WaterLevelController), 由 lifespan 注入
    app.state.water_level_cfg = None     # 液位配置 (WaterLevelCfg: orangepi_ip/stream_port), 由 lifespan 注入
    app.state.water_level_observations = None  # VM run 级液位观测旁挂收集器
    app.state.plc_program = None  # PLC 程序编辑服务 (PlcProgramService), 仅 real + codesys.enabled 注入
    app.state.plc = None  # PLC L2 控制器 (PlcController), 由 lifespan 注入 (运行时工位控制)
    app.state.manual = None  # 单点控制服务 (ManualService), 由 lifespan 注入 (点表缺失时保持 None → 503)
    app.state.control_mode = control_mode
    app.state.app_config = None  # AppConfig 快照, 由 lifespan 注入 (仿真沙盒建栈读点表路径用)
    app.state.sim = None  # 仿真沙盒 (SimStack), 由 /api/sim/session 懒建 (见 api/sim_routes.py)
    app.state.recorder = None  # 状态录像机 (StateRecorder), 由 lifespan 注入; 关闭录制时保持 None → 503
    app.state.planner_stats = None  # 排程统计服务 (TimingStats), 首次请求懒建
    app.state.vision_debug = None  # 视觉调试台 (VisionDebugService), 由 lifespan 注入
    app.state.pallas_vision = None  # PALLASVision TCP/Bridge 客户端, 由 lifespan 注入

    def _executor(request: Request) -> ActionExecutor:
        ex = request.app.state.executor
        if ex is None:
            raise HTTPException(503, "执行器未就绪")
        return ex

    @app.get("/api/health")
    async def health(request: Request):
        return {"status": "ok", "control_mode": request.app.state.control_mode,
                "actions": len(request.app.state.registry), "executor_ready": request.app.state.executor is not None}

    @app.get("/api/diag/opc_read_timing")
    async def opc_read_timing(request: Request):
        """OPC UA 批量读耗时分位数, 按节点数分档。只读, 不触网。

        判定实时反馈跑不满配置频率的病因: 若 p50 远小于 (实测周期 − 配置周期),
        说明瓶颈不在读取而在调度或下游。分档是因为成本主要是固定往返开销而非节点数。
        """
        plc = getattr(request.app.state, "plc", None)
        driver = getattr(plc, "_driver", None) if plc is not None else None
        stats = getattr(driver, "read_timing_stats", None)
        if stats is None:
            return {"available": False, "reason": "PLC 驱动未就绪 (仿真模式或尚未连接)", "buckets": {}}
        return {"available": True, "buckets": stats()}

    @app.get("/api/mode")
    async def get_mode(request: Request):
        return {"control_mode": request.app.state.control_mode}

    @app.post("/api/mode")
    async def set_mode(request: Request, body: dict):
        mode = str(body.get("control_mode", "")).strip().upper()
        if mode not in ALLOWED_CONTROL_MODES:
            raise HTTPException(400, f"非法控制模式: {mode} (合法 {list(ALLOWED_CONTROL_MODES)})")
        request.app.state.control_mode = mode
        log.info("[API] 控制模式切换为 %s", mode)
        return {"control_mode": mode}

    def _target_keys(request: Request):
        """可下发点位 key 列表 (供 point_ref 参数下拉"选用哪个点位"); 含普通目标点 (滤掉限位源/未建节点)
        与组合点位 (多轴聚合, 如点样位置)。points 服务未就绪时返回 None (前端 point_ref 回退为文本输入)。"""
        points = getattr(request.app.state, "points", None)
        if points is None:
            return None
        targets = [t["id"] for t in points.list_plc_servo_target()
                   if not t["limit_source"] and not t["pending"]]
        composites = [c["id"] for c in points.list_plc_servo_composite()]
        return targets + composites

    @app.get("/api/actions", response_model=list[ActionDefDTO])
    async def list_actions(request: Request, kind: Optional[str] = None):
        reg = request.app.state.registry
        defs = reg.by_kind(kind) if kind else reg.list()
        keys = _target_keys(request)
        return [action_def_to_dto(d, keys) for d in defs]

    @app.get("/api/actions/{name}", response_model=ActionDefDTO)
    async def get_action(request: Request, name: str):
        try:
            return action_def_to_dto(request.app.state.registry.get(name), _target_keys(request))
        except KeyError:
            raise HTTPException(404, f"未知动作: {name}")

    async def _execute_with_live_events(
        request: Request, name: str, params, mode: str, *, command_id: str | None = None
    ):
        """执行原子动作并向事件总线发实时 run 事件, 使「当前运行」面板/态势条在执行期间实时点亮.

        功能:
            把单次原子执行包进 operation_start/step_start (执行前) 与 step_done/operation_done|failed
            (执行后) 一组合成事件, 镜像 VM 流程的事件形状, 复用前端事件溯源管线 (runs.ingest)。
            仅推 app.state.bus (实时显示), 不入 run_store, 故执行记录历史不被手动点测污染。
            bus 未就绪 (无 lifespan 的纯离线测试) 则不发事件, 动作照常执行。
        参数:
            request: 当前请求 (取 bus/registry/executor); name: 动作名; params: 动作参数;
            mode: 当前控制模式 (模式门控用)
        返回:
            ActionResult, 与直发 execute 等价 (事件仅为旁路实时通知)
        """
        bus = getattr(request.app.state, "bus", None)
        emit = bus.publish if bus is not None else (lambda event: None)
        rid = command_id or uuid.uuid4().hex[:12]
        try:
            label = request.app.state.registry.get(name).label
        except KeyError:
            label = name                      # 未知动作: execute 会优雅拒绝, label 回退动作名
        t0 = time.time()
        # atomic: 标记这是单原子动作运行 (operation=动作 id, 如 robot.home), 与 VM 流程
        # (operation=脚本名) 区分; 前端据此不把动作 id 当流程名去跳死路由 (审阅 #6)。
        # params 随事件带出: VM 路径的 vm_node_enter 一直带 args, 而这条合成路径此前不带,
        # 于是任何按入参做的旁路显示 (三维展缸液面要的 target_tank/体积) 在手点动作时全瞎。
        # 【2026-08-05】物料记账现在也吃这份 params: material_store.on_event 多了一条
        # step_done 分支查动作级绑定 (当前只有 liquid_draw), 于是单发上液也扣溶剂余量,
        # 流水标 "[面板单发]"。与 VM 路径**互斥不重复** —— VM 只发 vm_node_*, 本路径只发
        # step_*, 二者不同时出现 (test_material_store_offline 的 TestPanelSingleFireAccounting
        # 有回归钉住)。判据是 effect 能不能自愈而非触发路径, 理由见 config/material_bindings.yaml。
        emit({"type": "operation_start", "operation": name, "atomic": True,
              "run_id": rid, "label": label, "ts": t0})
        emit({"type": "step_start", "run_id": rid, "step": "a1", "action": name,
              "params": dict(params or {}), "index": 0, "status": "RUNNING", "ts": t0})
        result = await _executor(request).execute(name, params, request_id=rid, current_mode=mode)
        t1 = time.time()
        status = result.status.value
        emit({"type": "step_done", "run_id": rid, "step": "a1", "action": name, "index": 0,
              "params": dict(params or {}),
              "status": status, "message": result.message, "result": result.result, "ts": t1})
        done_type = "operation_done" if result.status is ActionStatus.DONE else "operation_failed"
        emit({"type": done_type, "operation": name, "run_id": rid,
              "status": status, "message": result.message, "ts": t1})
        return result

    @app.post("/api/actions/{name}/run", response_model=ActionResultDTO)
    async def run_action(request: Request, name: str, body: RunRequest):
        # 资源钩子动作 (如 pump.vacuum_on/off) 由资源门按引用计数驱动: 本路由绕过 VM 与资源门,
        # 手点一次就会把在跑流程仍在使用的共享设备关掉, 故直接拒绝。
        gate = getattr(request.app.state, "res_gate", None)
        if gate is not None and name in gate.hook_actions():
            raise HTTPException(
                409, f"{name} 是共享资源的开关动作, 由资源门按引用计数驱动, 不能单独运行; "
                     f"请在流程中用 with_resources 区间声明该资源")
        mode = body.mode or request.app.state.control_mode
        result = await _execute_with_live_events(
            request, name, body.params, mode, command_id=body.command_id
        )
        return action_result_to_dto(result)

    @app.get("/api/resources")
    async def list_resources(request: Request):
        """设备资源表 + 实时占用快照 (供流程编辑器选资源与占用诊断).

        返回:
            {"resources": [{id, label, mode, locked?|holders?}, ...]}
            mode=exclusive 带 locked (是否被占用), mode=shared 带 holders (当前持有者数)
        """
        gate = getattr(request.app.state, "res_gate", None)
        if gate is None:
            raise HTTPException(503, "资源门未就绪")
        return {"resources": [{"id": rid, **item} for rid, item in gate.snapshot().items()]}

    # ---- 动作 YAML 源文件视图 (整文件读写; 写前全量校验, 通过即热重载; 不限模式) ----
    def _actions_svc(request: Request):
        svc = request.app.state.actions
        if svc is None:
            raise HTTPException(503, "动作源文件服务未就绪")
        return svc

    @app.get("/api/actions/{name}/raw")
    async def get_action_raw(request: Request, name: str):
        try:
            return _actions_svc(request).read_action_raw(name)
        except KeyError:
            raise HTTPException(404, f"未知动作: {name}")

    @app.put("/api/actions/{name}/raw")
    async def save_action_raw(request: Request, name: str, body: dict):
        svc = _actions_svc(request)
        text = body.get("text")
        if not isinstance(text, str):
            raise HTTPException(400, "请求体缺少 text 字段")
        try:
            return svc.save_action_raw(name, text)
        except KeyError:
            raise HTTPException(404, f"未知动作: {name}")
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"YAML 解析失败: {exc}")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc))

    @app.put("/api/actions/{name}/description", response_model=ActionDefDTO)
    async def save_action_description(
        request: Request, name: str, body: ActionDescriptionUpdate,
    ):
        """只更新目标动作的 desc，保留同文件其它源码并热重载。"""
        try:
            _actions_svc(request).save_action_description(name, body.desc)
            return action_def_to_dto(
                request.app.state.registry.get(name), _target_keys(request))
        except KeyError:
            raise HTTPException(404, f"未知动作: {name}")
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"YAML 解析失败: {exc}")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc))

    @app.put("/api/actions/{name}/label", response_model=ActionDefDTO)
    async def save_action_label(
        request: Request, name: str, body: ActionLabelUpdate,
    ):
        """只更新目标动作的显示名 label, 保留同文件其它源码并热重载。"""
        try:
            _actions_svc(request).save_action_label(name, body.label)
            return action_def_to_dto(
                request.app.state.registry.get(name), _target_keys(request))
        except KeyError:
            raise HTTPException(404, f"未知动作: {name}")
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"YAML 解析失败: {exc}")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc))

    @app.delete("/api/actions/{name}")
    async def delete_action(request: Request, name: str):
        """从源文件删除该动作定义并热重载; 被流程引用时拒绝 (400, 详情含引用清单)。"""
        try:
            return _actions_svc(request).delete_action(name)
        except KeyError:
            raise HTTPException(404, f"未知动作: {name}")
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"YAML 解析失败: {exc}")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/actions/reload")
    async def reload_actions(request: Request):
        """从磁盘重扫动作目录并热重载 (直接改了动作 YAML 后手动同步, 无需重启后端)。"""
        svc = _actions_svc(request)
        try:
            return svc.reload()
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"YAML 解析失败: {exc}")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/robot/jog/start", response_model=ActionResultDTO)
    async def robot_jog_start(request: Request, body: dict):
        mode = body.get("mode") or request.app.state.control_mode
        result = await _executor(request).execute("robot.jog_start", {"axis_id": body.get("axis_id")}, current_mode=mode)
        return action_result_to_dto(result)

    @app.post("/api/robot/jog/stop", response_model=ActionResultDTO)
    async def robot_jog_stop(request: Request, body: Optional[dict] = None):
        mode = (body or {}).get("mode") or request.app.state.control_mode
        result = await _executor(request).execute("robot.jog_stop", {}, current_mode=mode)
        return action_result_to_dto(result)

    @app.post("/api/robot/step", response_model=ActionResultDTO)
    async def robot_step(request: Request, body: dict):
        mode = body.get("mode") or request.app.state.control_mode
        params = {k: body[k] for k in ("axis", "distance", "motion") if k in body}
        result = await _executor(request).execute("robot.step", params, current_mode=mode)
        return action_result_to_dto(result)

    @app.post("/api/robot/stop", response_model=ActionResultDTO)
    async def robot_stop(request: Request, body: Optional[dict] = None):
        # 安全便捷端点: 不限模式, 运动中可中止 (controller.stop 不占动作锁)
        mode = (body or {}).get("mode") or request.app.state.control_mode
        result = await _executor(request).execute("robot.stop", {}, current_mode=mode)
        return action_result_to_dto(result)

    @app.post("/api/robot/emergency_stop", response_model=ActionResultDTO)
    async def robot_emergency_stop(request: Request, body: Optional[dict] = None):
        body = body or {}
        mode = body.get("mode") or request.app.state.control_mode
        params = {"pressed": body["pressed"]} if "pressed" in body else {}
        result = await _executor(request).execute("robot.emergency_stop", params, current_mode=mode)
        return action_result_to_dto(result)

    @app.post("/api/robot/enable", response_model=ActionResultDTO)
    async def robot_enable(request: Request, body: Optional[dict] = None):
        # 维护页使能按钮: 调用本端点即视为显式 confirm (动作仍受 DEBUG 模式 + 配置 allow_enable_command 门控)
        mode = (body or {}).get("mode") or request.app.state.control_mode
        result = await _executor(request).execute("robot.enable", {"confirm": True}, current_mode=mode)
        return action_result_to_dto(result)

    @app.post("/api/robot/disable", response_model=ActionResultDTO)
    async def robot_disable(request: Request, body: Optional[dict] = None):
        # 维护页下使能按钮: 调用本端点即视为显式 confirm (门控同使能: DEBUG 模式 + 配置 allow_enable_command)
        mode = (body or {}).get("mode") or request.app.state.control_mode
        result = await _executor(request).execute("robot.disable", {"confirm": True}, current_mode=mode)
        return action_result_to_dto(result)

    @app.post("/api/robot/connect", response_model=ActionResultDTO)
    async def robot_connect(request: Request, body: Optional[dict] = None):
        # 维护页重连按钮: 断联恢复, 不限模式 (仅重建通信, 安全由传输层重连校验兜底)。
        # confirm=true = 操作员已人工确认无其他控制者, 先清接管守卫再重连 (强制接管)
        mode = (body or {}).get("mode") or request.app.state.control_mode
        params = {"confirm": True} if (body or {}).get("confirm") else {}
        result = await _executor(request).execute("robot.connect", params, current_mode=mode)
        return action_result_to_dto(result)

    @app.post("/api/robot/clear_error", response_model=ActionResultDTO)
    async def robot_clear_error(request: Request, body: Optional[dict] = None):
        # 维护页清警按钮: 调用本端点即视为显式 confirm (门控同上, 由 allow_clear_error_command 控制)
        mode = (body or {}).get("mode") or request.app.state.control_mode
        result = await _executor(request).execute("robot.clear_error", {"confirm": True}, current_mode=mode)
        return action_result_to_dto(result)

    @app.post("/api/robot/speed_factor", response_model=ActionResultDTO)
    async def robot_set_speed_factor(request: Request, body: dict):
        # 维护页全局速度比: 1-100, 影响点动与所有运动; 当前值经机器人节点遥测 (data.speed_factor) 回显
        mode = body.get("mode") or request.app.state.control_mode
        # 必填 ratio 前置校验: 缺失/非数值 → 422, 使 HTTP 码与 result.status 一致 (范围 1-100 仍由 action 内部校验)
        raw = body.get("ratio")
        if raw is None or isinstance(raw, bool):
            raise HTTPException(422, "speed_factor 需要数值参数 ratio")
        try:
            ratio = float(raw)
        except (TypeError, ValueError):
            raise HTTPException(422, "ratio 必须是数值")
        result = await _executor(request).execute(
            "robot.set_speed_factor", {"ratio": ratio}, current_mode=mode)
        return action_result_to_dto(result)

    def _pallas(request: Request):
        svc = getattr(request.app.state, "pallas_vision", None)
        if svc is None:
            raise HTTPException(503, "PALLASVision 服务未就绪")
        return svc

    @app.get("/api/pallas/status")
    async def pallas_status(request: Request):
        try:
            return await _pallas(request).bridge_status()
        except Exception as exc:
            raise HTTPException(503, str(exc))

    @app.post("/api/pallas/reconnect")
    async def pallas_reconnect(request: Request):
        try:
            return await _pallas(request).bridge_reconnect()
        except Exception as exc:
            raise HTTPException(503, str(exc))

    # ---- 设备节点 (健康 + 快照) ----
    @app.get("/api/nodes")
    async def list_nodes(request: Request):
        reg = request.app.state.node_registry
        if reg is None:
            raise HTTPException(503, "节点注册表未就绪")
        return await reg.snapshot_all()

    @app.get("/api/nodes/{node_id}")
    async def get_node(request: Request, node_id: str):
        reg = request.app.state.node_registry
        if reg is None:
            raise HTTPException(503, "节点注册表未就绪")
        snap = await reg.snapshot(node_id)
        if snap is None:
            raise HTTPException(404, f"未知节点: {node_id}")
        return snap

    # ---- 执行历史 (运行记录 + 回放) ----
    @app.get("/api/runs")
    async def list_runs(request: Request, limit: int = 50, status: Optional[str] = None,
                        since: Optional[float] = None, until: Optional[float] = None):
        store = request.app.state.run_store
        if store is None:
            raise HTTPException(503, "运行记录未就绪")
        return store.list_runs(limit=limit, status=status, since=since, until=until)

    @app.get("/api/runs/{run_id}")
    async def get_run(request: Request, run_id: str):
        store = request.app.state.run_store
        if store is None:
            raise HTTPException(503, "运行记录未就绪")
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, f"未知运行: {run_id}")
        return run

    # ---- WebSocket 事件流 (流程实时状态 + 节点遥测) ----
    @app.websocket("/api/ws/events")
    async def ws_events(websocket: WebSocket):
        await websocket.accept()
        bus = websocket.app.state.bus
        if bus is None:
            await websocket.close(code=1011)
            return
        async with bus.subscribe() as queue:
            await websocket.send_json({"type": "ready"})  # 订阅就绪确认
            # 物料是持久化快照而不是纯增量事件。连接后立即补种，避免客户端必须等到
            # 下一次盘点/流程扣账才看到现有托盘、耗材与板仓数量。
            material_store = getattr(websocket.app.state, "material_store", None)
            if material_store is not None:
                snapshot = await asyncio.to_thread(material_store.grid)
                await websocket.send_json(material_state_event(snapshot, seq=0, initial=True))
            try:
                while True:
                    event = await queue.get()
                    await websocket.send_json(event)
            except WebSocketDisconnect:
                pass
            except Exception as exc:  # 连接异常时安静退出
                log.debug("[API] WS 事件流结束: %s", exc)

    register_vm_routes(app)  # 脚本仓库 + VM 运行/调试/HITL 端点
    register_planner_routes(app)  # 排程只读统计 (甘特图数据, 不控制执行)
    register_scheduler_routes(app)  # 并行实验调度 (配方/批次提交/段作业恢复/快照)
    register_points_routes(app)  # 统一点位目录 (机器人/PLC伺服/CNC) 浏览端点
    register_material_routes(app)  # 物料账本 (板x孔 二态余量) 查询 + 人工盘点端点
    register_material_audit_routes(app)  # 一键审查 (账实体检, 只报不改)
    register_feedlift_routes(app)  # 升降板仓行程标定 (空仓基准位 + 堆叠节距两步标定)
    register_config_routes(app)  # 设备参数 (camera/gcode/vision) 读写端点
    register_plc_program_routes(app)  # PLC 程序 (CODESYS POU) 编辑/编译端点
    register_calibration_routes(app)  # 孔板标定采点 + 按孔下发端点
    register_plate_align_routes(app)  # 板位对位: 点样视觉零点一键示教 (.163 对位相机)
    register_water_level_routes(app)  # 液位控制台命令透传 + MJPEG 代理
    register_vision_routes(app)  # 视觉产物图片服务 (标注图 → HITL 弹窗 <img>)
    register_vision_debug_routes(app)  # 视觉调试台 (固定工作区拍照/识别参数调优)
    register_photoscrape_routes(app)  # 手绘路径来源 (视觉失败兜底: 画区域→预览→提交 summary)
    register_manual_routes(app)  # 单点控制: 复刻 HMI 手动屏的气缸电平二态 + 轴点动 (设备页面板)
    register_three_d_routes(app)  # 三维模型资产 + DEBUG authoring 写回与重建
    register_recording_routes(app)  # 状态录像 (3D DVR): 会话/时间轴/任意时刻快照/帧流
    register_sim_routes(app)  # 仿真沙盒: 独立虚拟 PLC 执行链 + /api/sim/ws/events (三维仿真页)
    _mount_spa(app)  # 必须最后: catch-all 不能遮蔽上面的 /api/* 与 WS 路由
    return app
