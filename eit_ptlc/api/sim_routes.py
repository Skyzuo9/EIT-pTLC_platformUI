"""仿真沙盒端点 (/api/sim/*)
============================
功能:
    三维仿真页 (/3d/sim) 的后端面: 管理单例仿真沙盒 (runtime/sim_stack.SimStack),
    读写沙盒设备状态、一键采纳真机实时状态、经沙盒 VM 执行动作/流程 (与
    /api/scripts/{name}/debug/run 同语义), 并提供独立事件 WS。

端点:
    POST   /api/sim/session {time_scale?, adopt?}   创建沙盒 (懒建; 已存在→409)
    GET    /api/sim/session                          状态 {active, time_scale, runs}
    DELETE /api/sim/session                          销毁
    GET    /api/sim/state                            全量状态快照
    PUT    /api/sim/state {axes/robot/rail/mechanisms}  局部写 (运行中→409)
    POST   /api/sim/adopt                            采纳真机/主栈实时状态
    POST   /api/sim/reset                            复位规范 home
    POST   /api/sim/time_scale {rate}                时间倍率 (阶段③生效, 先行落值)
    POST   /api/sim/scripts/{name}/debug/run         沙盒运行 (body 同 vm_routes)
    POST   /api/sim/debug/{run_id}/{verb}            调试动词 (薄委托沙盒 VmController)
    GET    /api/sim/debug/active|{run_id}/state|vars
    POST   /api/sim/debug/{run_id}/human/{req_id}    HITL 透传
    WS     /api/sim/ws/events                        沙盒事件流 (连接即发 ready+物料快照)
    *      /api/sim/materials/*                      沙盒物料账本 (镜像 /api/materials 全部 16 个端点)

隔离:
    全部动词落 app.state.sim (SimStack) —— 与真实 executor/vm/调度器零交集;
    路由为薄委托, 不复用 vm_routes 的路由函数 (那些直读 app.state.vm)。
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

from eit_ptlc.api.material_routes import register_material_routes
from eit_ptlc.api.vm_dto import BreakpointsBody, HumanReplyBody, ResetBody, VmStartBody
from eit_ptlc.operation.vm.inputs import validate_inputs
from eit_ptlc.operation.vm.knobs import collect_knobs, validate_overrides
from eit_ptlc.runtime.material_feedback import material_state_event
from eit_ptlc.runtime.sim_stack import build_sim_stack

log = logging.getLogger(__name__)

_VERBS = ("step", "step_over", "run", "pause", "resume",
          "stop_after", "terminate", "estop", "stop")
_REQUIRED_SIM_MAGAZINE_SEEDS = {"waste": 1}


def _seed_required_sim_materials(stack) -> dict[str, int]:
    """给全新沙盒补齐生产流程要求的固定工位物料，不覆盖已有人工盘点。

    FeedLift A22 的真实前置门要求下料仓接近开关为 TRUE，因此物理零张仓不是
    合法生产起点。沙盒会话是全新世界，默认补一张承托板；手工预置为更多张时
    保留原值。采纳实时状态的会话不调用本函数，避免伪造真机现场事实。
    """

    seeded: dict[str, int] = {}
    store = stack.material_store
    for magazine, minimum in _REQUIRED_SIM_MAGAZINE_SEEDS.items():
        if store.magazine_count(magazine) >= minimum:
            continue
        store.set_magazine(magazine, minimum, detail="仿真默认工位承托板")
        seeded[magazine] = minimum
    return seeded


def register_sim_routes(app: FastAPI) -> None:
    """注册仿真沙盒端点. app.state.sim 由本模块独占管理 (单例, 懒建)."""
    # 创建/销毁互斥: 并发 POST session 不该起两台 Mock Server 抢同一端口
    lifecycle_lock = asyncio.Lock()

    def _stack(request_or_ws):
        stack = getattr(request_or_ws.app.state, "sim", None)
        if stack is None:
            raise HTTPException(503, "仿真沙盒未创建 (先 POST /api/sim/session)")
        return stack

    def _repo(request: Request):
        repo = request.app.state.script_repo
        if repo is None:
            raise HTTPException(503, "脚本仓库未就绪")
        return repo

    # 沙盒物料端点: 复用 material_routes 的同一批 handler, 只换前缀与取数口 ——
    # 15 个 handler 的校验与话术是同一份契约, 抄一份必漂。
    # 沙盒 reconcile 读的是沙盒自己那台 Mock OPC 的 IX 字节, 与传感器合成层天然同源。
    register_material_routes(
        app, prefix="/api/sim/materials",
        store_getter=lambda request: _stack(request).material_store,
        plc_getter=lambda request: _stack(request).plc,
    )

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------

    @app.post("/api/sim/session")
    async def sim_create(request: Request, body: dict | None = None):
        body = body or {}
        config = getattr(request.app.state, "app_config", None)
        if config is None:
            raise HTTPException(503, "应用配置未就绪 (app_config 缺席)")
        async with lifecycle_lock:
            if getattr(request.app.state, "sim", None) is not None:
                raise HTTPException(409, "仿真沙盒已存在 (先 DELETE /api/sim/session)")
            repo = _repo(request)
            try:
                stack = await build_sim_stack(
                    config,
                    registry=request.app.state.registry,
                    resolve_script=lambda n: repo.get("default", n),
                    mode_provider=lambda: request.app.state.control_mode,
                    read_config_section=(
                        request.app.state.config_svc.read_section
                        if getattr(request.app.state, "config_svc", None) is not None else None),
                    time_scale=float(body.get("time_scale") or 1.0),
                )
            except OSError as exc:
                raise HTTPException(503, f"沙盒启动失败 (端口被占?): {exc}") from exc
            seeded_materials = (
                {} if body.get("adopt") else _seed_required_sim_materials(stack)
            )
            request.app.state.sim = stack
        result: dict = {
            "ok": True,
            "time_scale": stack.time_scale,
            "seeded_materials": seeded_materials,
        }
        if body.get("adopt"):
            result["adopt"] = await _adopt_into(request.app, stack)
        return result

    @app.get("/api/sim/session")
    async def sim_status(request: Request):
        stack = getattr(request.app.state, "sim", None)
        if stack is None:
            return {"active": False}
        return {"active": True, "time_scale": stack.time_scale,
                "runs": stack.vm.active()}

    @app.delete("/api/sim/session")
    async def sim_destroy(request: Request):
        async with lifecycle_lock:
            stack = getattr(request.app.state, "sim", None)
            if stack is None:
                return {"ok": True, "active": False}
            request.app.state.sim = None
            await stack.stop()
        return {"ok": True, "active": False}

    # ------------------------------------------------------------------
    # 状态面
    # ------------------------------------------------------------------

    @app.get("/api/sim/state")
    async def sim_state(request: Request):
        return await _stack(request).state_snapshot()

    @app.get("/api/sim/plate_positions")
    async def sim_plate_positions(request: Request):
        """薄层板位置的只读投影 (三维板层的 L1 源).

        参数:
            无
        返回:
            Dict; 形状与消费者 PlateLedgerStore.push 逐字段对齐, 另带 coverage/identity

        沙盒未创建时 **503 而不是 200-空体**: 前端 pullLedger 只在 res.ok 时 push,
        非 ok 即"保持末态, 板绝不回零" —— 与断流冻结同义。给一个空 batches 反而会让
        板层把画面上的板全回收掉。
        名字里刻意没有 scheduler / snapshot / batch 任何一个词: 沙盒不装调度器,
        端点名是第一道语义防线 (它是什么、不是什么, 见 runtime/sim_plate_projection 头注)。
        """
        return await _stack(request).plate_positions()

    @app.get("/api/sim/diagnostics")
    async def sim_diagnostics(request: Request):
        """只读诊断: 门为什么不满足 / 段号走到哪 / 传感器位由什么推导.

        参数:
            无
        返回:
            Dict {stations, sensors, feedlift}

        与 GET /api/sim/state 分家: 那边是可设面的回读, 这边是只读诊断。
        """
        return await _stack(request).diagnostics()

    @app.put("/api/sim/state")
    async def sim_state_put(request: Request, body: dict):
        stack = _stack(request)
        if stack.vm.active().get("runs"):
            raise HTTPException(409, "沙盒有流程在跑, 不接受直写状态 (先停运行)")
        return await stack.apply_state(body or {})

    @app.post("/api/sim/reset")
    async def sim_reset(request: Request):
        stack = _stack(request)
        if stack.vm.active().get("runs"):
            raise HTTPException(409, "沙盒有流程在跑, 不接受复位 (先停运行)")
        return await stack.reset_home()

    @app.post("/api/sim/adopt")
    async def sim_adopt(request: Request):
        stack = _stack(request)
        if stack.vm.active().get("runs"):
            raise HTTPException(409, "沙盒有流程在跑, 不接受采纳 (先停运行)")
        return await _adopt_into(request.app, stack)

    @app.post("/api/sim/time_scale")
    async def sim_time_scale(request: Request, body: dict):
        stack = _stack(request)
        rate = float((body or {}).get("rate") or 1.0)
        if not 0.1 <= rate <= 20.0:
            raise HTTPException(400, f"时间倍率须在 0.1~20, 收到 {rate}")
        stack.time_scale = rate
        return {"ok": True, "time_scale": rate}

    # ------------------------------------------------------------------
    # 运行面 (与 vm_routes 的 debug 语义逐字同构, 落沙盒 vm)
    # ------------------------------------------------------------------

    @app.post("/api/sim/actions/{name}/run")
    async def sim_action_run(request: Request, name: str, body: dict | None = None):
        """单个原子动作直跑 (经沙盒执行器, 全参数校验/泵翻译/孔位仿射照走)。

        合成事件包裹在 SimStack.run_action_with_events (镜像主栈
        app.py::_execute_with_live_events) —— 泵/液面包络链吃 step_* 事件的 params。
        """
        stack = _stack(request)
        try:
            label = request.app.state.registry.get(name).label
        except KeyError:
            label = name
        return await stack.run_action_with_events(
            name, dict((body or {}).get("params") or {}),
            mode=request.app.state.control_mode, label=label)

    @app.post("/api/sim/scripts/{name}/debug/run")
    async def sim_debug_run(request: Request, name: str, body: VmStartBody, ws: str = "default"):
        repo, stack = _repo(request), _stack(request)
        try:
            doc = repo.get(ws, name)
        except KeyError:
            raise HTTPException(404, f"脚本不存在: {ws}/{name}")
        if body.inputs:
            errors = validate_inputs(doc, body.inputs)
            if errors:
                raise HTTPException(400, "入参非法: " + "; ".join(errors))
        if body.overrides:
            errors = validate_overrides(collect_knobs(doc, lambda n: repo.get(ws, n)), body.overrides)
            if errors:
                raise HTTPException(400, "旋钮覆盖非法: " + "; ".join(errors))
        mode_run = "step" if body.mode_run == "step" else "run"
        return await stack.vm.start(doc, body.inputs, mode_run=mode_run,
                                    start_aid=body.start_aid, overrides=body.overrides,
                                    meta={"origin": "sim"})

    @app.post("/api/sim/debug/{run_id}/{verb}")
    async def sim_debug_verb(request: Request, run_id: str, verb: str):
        if verb not in _VERBS:
            raise HTTPException(404, f"未知动词: {verb}")
        stack = _stack(request)
        method = "terminate" if verb == "stop" else verb
        try:
            return await getattr(stack.vm, method)(run_id)
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    @app.post("/api/sim/debug/{run_id}/reset")
    async def sim_debug_reset(request: Request, run_id: str, body: ResetBody | None = None):
        try:
            return await _stack(request).vm.reset(run_id, (body.aid if body else None))
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    @app.get("/api/sim/debug/active")
    async def sim_debug_active(request: Request):
        return _stack(request).vm.active()

    @app.get("/api/sim/debug/{run_id}/state")
    async def sim_debug_state(request: Request, run_id: str):
        try:
            return _stack(request).vm.state(run_id)
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    @app.get("/api/sim/debug/{run_id}/vars")
    async def sim_debug_vars(request: Request, run_id: str):
        try:
            return _stack(request).vm.vars(run_id)
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    @app.post("/api/sim/debug/{run_id}/breakpoints")
    async def sim_debug_breakpoints(request: Request, run_id: str, body: BreakpointsBody):
        try:
            return _stack(request).vm.set_breakpoints(run_id, body.aids)
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    @app.post("/api/sim/debug/{run_id}/human/{req_id}")
    async def sim_debug_human(request: Request, run_id: str, req_id: str, body: HumanReplyBody):
        try:
            return await _stack(request).vm.human_reply(
                run_id, req_id, {"choice": body.choice, "values": body.values})
        except KeyError:
            raise HTTPException(404, f"无此运行/请求: {run_id}/{req_id}")

    # ------------------------------------------------------------------
    # 事件流 (独立通道; 契约对齐 /api/ws/events: ready + 物料快照播种)
    # ------------------------------------------------------------------

    @app.websocket("/api/sim/ws/events")
    async def sim_ws_events(websocket: WebSocket):
        await websocket.accept()
        stack = getattr(websocket.app.state, "sim", None)
        if stack is None:
            await websocket.close(code=1011)
            return
        async with stack.bus.subscribe() as queue:
            await websocket.send_json({"type": "ready"})
            snapshot = await asyncio.to_thread(stack.material_store.grid)
            await websocket.send_json(material_state_event(snapshot, seq=0, initial=True))
            try:
                while True:
                    await websocket.send_json(await queue.get())
            except WebSocketDisconnect:
                pass
            except Exception as exc:
                log.debug("[SimAPI] WS 事件流结束: %s", exc)


async def _adopt_into(app, stack) -> dict:
    """一键采纳: 把真实侧 (real 的真机 / sim 主栈的 Mock) 的当前状态灌进沙盒。

    逐类 best-effort: 某一类读不到 (设备离线/服务未装配) 记进 skipped 并继续,
    绝不因一类失败整体报错 —— 采纳的意义是"从现在的机器出发推演", 缺哪类用户
    在返回体里看得见。
    """
    patch: dict = {"axes": {}, "mechanisms": {}}
    skipped: list[dict] = []

    manual = getattr(app.state, "manual", None)
    if manual is None:
        skipped.append({"part": "axes+mechanisms", "reason": "主栈单点服务未装配"})
    else:
        try:
            # 形状对齐 ManualService.realtime_snapshot:
            #   axes: {id: {position, velocity}}; mechanisms: {id: {commanded, confirmed, ...}}
            # 机构采纳取 confirmed(到位反馈) 优先, 缺反馈退 commanded(命令态)。
            snap = await manual.realtime_snapshot()
            for axis_id, entry in (snap.get("axes") or {}).items():
                value = entry.get("position") if isinstance(entry, dict) else None
                if value is not None:
                    patch["axes"][axis_id] = float(value)
            for mech_id, entry in (snap.get("mechanisms") or {}).items():
                if not isinstance(entry, dict):
                    continue
                state = entry.get("confirmed")
                if state is None:
                    state = entry.get("commanded")
                if state is not None:
                    patch["mechanisms"][mech_id] = bool(state)
        except Exception as exc:
            skipped.append({"part": "axes+mechanisms", "reason": f"实时快照失败: {exc}"})

    executor = getattr(app.state, "executor", None)
    robot = executor.robot if executor is not None else None
    if robot is None:
        skipped.append({"part": "robot", "reason": "主栈机器人不可达"})
    else:
        # 机器人分两路采, 判据是"读它要不要打 TCP":
        #   挂刀与末端执行器 = 纯内存读 (mounted_tool 是落盘的软件权威态, 机构态是最近
        #     命令缓存), 不打 TCP 也不碰 _action_lock ⇒ **机器人忙也照采**;
        #   关节角与 TCP 位姿 = robot.query() 要实发 GetAngle()/GetPose() 且持动作锁
        #     ⇒ 忙时不等, 记 skipped。
        # 分两路的实际意义: 吸盘正吸着一块板时采纳, 哪怕臂还在走, 沙盒也知道手上有板 ——
        # 板堆扣减判据 _suction_on() 读的就是这份机构态。
        robot_patch: dict = {}
        try:
            robot_patch["tool"] = int(robot.mounted_tool)
            # 只采**已被命令过**的机构 (commanded_mechanism_states 不搬 CAD 推定基准态)。
            # 取值口径与上面的 PLC 气缸段逐字相同: confirmed 优先, 缺则 commanded;
            # 两者皆无则不进 patch —— 不写 = "这机构从没被命令过", 与沙盒新栈初态同义。
            #
            # ⚠ 吸盘 rob_suction 在真机上没有任何 DI (_TOOL_DI_TARGET 无 SUCTION 条目),
            # confirmed 恒 None、source 恒 commanded ⇒ 这里采到的必然是推定值。沙盒侧经
            # tool_action 落地后 source 同样是 commanded, 前端照既有约定标"推定", 语义
            # 逐字一致。**真机自己也只知道最后发过什么命令**, 采不到更强的东西。
            effectors: dict = {}
            for mech_id, entry in (robot.commanded_mechanism_states() or {}).items():
                if not isinstance(entry, dict):
                    continue
                state = entry.get("confirmed")
                if state is None:
                    state = entry.get("commanded")
                if state is not None:
                    effectors[str(mech_id)] = bool(state)
            if effectors:
                robot_patch["effectors"] = effectors
        except Exception as exc:
            skipped.append({"part": "robot.effectors", "reason": f"末端机构读取失败: {exc}"})
        try:
            # 公开 API robot.query() 持控制器动作锁 (不绕过运动序列); 忙时不等 ——
            # 采纳是 best-effort, 挂在一段长运动后面不如快速回报 skipped。
            if robot.is_busy():
                skipped.append({"part": "robot.pose", "reason": "机器人运动中, 本次未采纳位姿"})
            else:
                fb = await asyncio.to_thread(robot.query)
                robot_patch["joint"] = list(fb.joint)
                robot_patch["pose"] = list(fb.pose)
        except Exception as exc:
            skipped.append({"part": "robot.pose", "reason": f"位姿读取失败: {exc}"})
        if robot_patch:
            patch["robot"] = robot_patch

    # 物料账本: 整表快照搬进沙盒的 :memory: 副本。
    # epoch 原样保留 —— 沙盒进程的 epoch 与快照里的不同, 于是在途行自动判 stale,
    # 语义恰好诚实 ("上一个世界留下的在途, 沙盒无法确认爪上真有东西")。
    main_store = getattr(app.state, "material_store", None)
    sim_store = getattr(stack, "material_store", None)
    if main_store is None or sim_store is None:
        skipped.append({"part": "materials", "reason": "主栈或沙盒物料账本未装配"})
    else:
        try:
            snapshot = await asyncio.to_thread(main_store.export_rows)
            counts = await asyncio.to_thread(sim_store.import_rows, snapshot)
            result_materials = {"tables": counts, "rows": sum(counts.values())}
        except Exception as exc:
            skipped.append({"part": "materials", "reason": f"账本采纳失败: {exc}"})
            result_materials = None
    result = await stack.apply_state(patch)
    result["skipped"] = skipped
    if main_store is not None and sim_store is not None and result_materials is not None:
        result["materials"] = result_materials
    return result
