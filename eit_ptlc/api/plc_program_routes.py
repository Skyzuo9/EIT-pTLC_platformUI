"""PLC 程序编辑路由
==================
功能:
    注册 PLC 程序(CODESYS POU)编辑/编译端点到 FastAPI 应用. 从 app.state.plc_program
    (PlcProgramService) 读取; 未就绪(codesys.enabled=false 或非 real 模式)返回 503.
    底层经 CodesysIpcClient 驱动 InoProShop, 首次调用会冷启动 IDE(较慢).

端点 (前缀 /api/plc):
    GET  /plc/status               worker/工程状态(并懒启动 InoProShop)
    GET/POST /plc/session*         只读会话状态 / 用户接管 / 释放接管(不启动 worker)
    GET  /plc/pous                 列出 Application 下可编辑 POU 路径
    GET  /plc/tree                 列出工程完整设备树(含硬件节点, 供「设备」标签)
    GET  /plc/pou?path=<path>      读某 POU 的声明(VAR)+实现(ST)
    PUT  /plc/pou {path,declaration?,implementation?,save?}  整体替换并可选落盘
    POST /plc/compile              编译 Application, 返回 errors/warnings
    POST /plc/generate_code        离线生成 Symbol Configuration XML（不登录/不下载）
    GET  /plc/symbols?path=<path>  列出某 POU(GVL)变量及 OPC 符号导出态
    POST /plc/symbols {path,name,enabled}  增删某变量的符号导出 pragma 并落盘
    GET  /plc/online_status        探测真机在线可达性(供 web 门控下发按钮)
    GET  /plc/deploy/status        读取当前/最近一次部署的内存阶段（不访问 worker）
    POST /plc/deploy/reconcile     人工核版后只读核对 PLC READY，并解除持久维护锁
    POST /plc/deploy               安全卸载伺服后全下载，并等待启动/自动回零 READY
    GET  /plc/versions             列出 .project 全量快照历史
    GET  /plc/versions/{rev}/download  下载某版 .project 二进制
    POST /plc/versions/snapshot {message?}  手动给当前工程打一版快照
    POST /plc/versions/{rev}/restore   还原某版到活动工程(先停 worker 释放文件锁)
    POST /plc/stations/{station}/reset  脉冲 L2_Reset 清工位故障 (DEBUG 门控; 由「设备」页工位节点调用)
    POST /plc/stations/{station}/init   跑该工位 *.init 原子 (RUN/DEBUG 均可; 走执行器)
    POST /plc/stations/init_all         全工站一键初始化 (走 system_init_all 编排, 留痕可回放)

错误码:
    503 服务未就绪; 502 InoProShop 操作失败(含 POU 未找到/工程被占用); 504 操作超时;
    400 请求体非法; 403 部署未启用; 404 版本不存在/工位无初始化动作;
    409 下载前置条件不满足 / 初始化时仍有流程或 L2 动作在跑; 422 编排未跑成 DONE
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request, Response

from eit_ptlc.action.models import ActionStatus
from eit_ptlc.api.dto import action_result_to_dto
from eit_ptlc.controller.plc_program_service import (
    PLCDeployOutcomeUnknown,
    PLCDeployPreparationTimeout,
    PLCDeployPreconditionError,
)
from eit_ptlc.runtime.maintenance_gate import MaintenanceActiveError

log = logging.getLogger(__name__)

_WORKSPACE = "default"
_INIT_ALL_SCRIPT = "system_init_all"

# 工位初始化的参数集: 一个工位跑几条 init、各带什么参数。缺省 ({},) = 无参跑一条。
# 展缸的 init 是**按缸**的 (每次只清所选缸的阀路/气缸 + 该组泵), 所以"初始化展开工位"
# 必须逐缸跑一遍 —— 只跑 1 号缸会留下 7 个缸没清, 那不叫工位初始化。
# 缸数固定 8: plc_nodes.yaml 的 Tank_* 数组与 resources.yaml 的 tank_action:1..8 同为 8。
_INIT_PARAM_SETS: dict[str, tuple[dict, ...]] = {
    "develop": tuple({"target_tank": n} for n in range(1, 9)),
    "expand": tuple({"target_tank": n} for n in range(1, 9)),   # STATION_PREFIX 的同义工位名
}
# 全工站初始化的等待上限(秒): 编排跑两条并行支 (无泵支 photoscrape+feedlift ‖ 泵总线支
# sampling+展缸逐缸+collect, 切分依据见 system_init_all.yaml 文件头), 总时长取两支中的长者,
# 正常一两分钟内结束。取 600 是给 PhotoScrape 三轴慢速归位与各泵 /nQ 轮询留足余量。
# 超时只是不再等, **不终止运行** —— 轴可能正在动。
_INIT_ALL_TIMEOUT_S = 600.0


def register_plc_program_routes(app: FastAPI) -> None:
    """把 PLC 程序编辑路由注册到应用。"""

    def _svc(request: Request):
        svc = request.app.state.plc_program
        if svc is None:
            raise HTTPException(503, "PLC 程序服务未就绪 (codesys.enabled=false 或非 real 模式)")
        return svc

    async def _call(coro):
        """统一把 IPC 层异常映射为 HTTP 错误码。"""
        try:
            return await coro
        except PLCDeployPreconditionError as exc:
            raise HTTPException(409, detail=exc.payload())
        except PLCDeployOutcomeUnknown as exc:
            raise HTTPException(502, detail=exc.payload())
        except PLCDeployPreparationTimeout as exc:
            raise HTTPException(504, detail=exc.payload())
        except TimeoutError as exc:
            raise HTTPException(504, str(exc))
        except RuntimeError as exc:
            raise HTTPException(502, str(exc))

    @app.get("/api/plc/status")
    async def plc_status(request: Request):
        return await _call(_svc(request).status())

    @app.get("/api/plc/session")
    async def plc_session(request: Request):
        return _svc(request).session()

    @app.post("/api/plc/session/takeover")
    async def plc_session_takeover(request: Request, body: dict | None = None):
        body = body or {}
        by = body.get("by", "operator") if isinstance(body, dict) else "operator"
        reason = body.get("reason", "") if isinstance(body, dict) else ""
        return _svc(request).takeover(str(by or "operator"), str(reason or ""))

    @app.post("/api/plc/session/release")
    async def plc_session_release(request: Request, body: dict | None = None):
        body = body or {}
        by = body.get("by", "operator") if isinstance(body, dict) else "operator"
        return _svc(request).release_takeover(str(by or "operator"))

    @app.get("/api/plc/pous")
    async def plc_list_pous(request: Request):
        return await _call(_svc(request).list_pous())

    @app.get("/api/plc/tree")
    async def plc_tree(request: Request):
        return await _call(_svc(request).tree())

    @app.get("/api/plc/pou")
    async def plc_read_pou(request: Request, path: str):
        return await _call(_svc(request).read_pou(path))

    @app.put("/api/plc/pou")
    async def plc_save_pou(request: Request, body: dict):
        path = body.get("path")
        if not isinstance(path, str) or not path:
            raise HTTPException(400, "请求体缺少 path 字段")
        return await _call(_svc(request).save_pou(
            path, body.get("declaration"), body.get("implementation"),
            bool(body.get("save", False))))

    @app.post("/api/plc/compile")
    async def plc_compile(request: Request):
        return await _call(_svc(request).compile())

    @app.post("/api/plc/generate_code")
    async def plc_generate_code(request: Request):
        return await _call(_svc(request).generate_code())

    # ---- OPC 符号导出: 列出/切换某变量的 symbol pragma (改动后需编译+下载才生效) ----
    @app.get("/api/plc/symbols")
    async def plc_list_symbols(request: Request, path: str):
        return await _call(_svc(request).list_symbols(path))

    @app.post("/api/plc/symbols")
    async def plc_set_symbol(request: Request, body: dict):
        path = body.get("path")
        name = body.get("name")
        if not isinstance(path, str) or not path or not isinstance(name, str) or not name:
            raise HTTPException(400, "请求体需含 path 与 name")
        try:
            return await _call(_svc(request).set_symbol_export(path, name, bool(body.get("enabled", False))))
        except ValueError as exc:                       # 变量名不存在
            raise HTTPException(400, str(exc))

    # ---- 部署: 空闲/安全握手后全下载，自动启动并等待 PLC_READY ----
    @app.get("/api/plc/online_status")
    async def plc_online_status(request: Request):
        return await _call(_svc(request).online_status())

    @app.get("/api/plc/deploy/status")
    async def plc_deploy_status(request: Request):
        # 纯内存快照：部署进行中也不能排队访问 CODESYS worker 或 OPC UA。
        return _svc(request).deploy_status()

    @app.post("/api/plc/deploy/reconcile")
    async def plc_deploy_reconcile(request: Request):
        body = await request.json()
        confirmed = body.get("operator_confirmed_online_version") is True
        return await _call(_svc(request).reconcile_maintenance_latch(
            operator_confirmed_online_version=confirmed,
        ))

    @app.post("/api/plc/deploy")
    async def plc_deploy(request: Request):
        svc = _svc(request)
        if not getattr(svc, "allow_deploy", False):
            raise HTTPException(403, "部署未启用 (codesys.allow_deploy=false)")
        return await _call(svc.deploy())

    # ---- 版本管理: 整份 .project 全量快照 (详见 controller/plc_version_repo.py) ----
    @app.get("/api/plc/versions")
    async def plc_versions(request: Request):
        return _svc(request).versions()

    @app.get("/api/plc/versions/{rev}/download")
    async def plc_version_download(request: Request, rev: str):
        svc = _svc(request)
        try:
            data = svc.version_bytes(rev)
        except KeyError:
            raise HTTPException(404, "版本不存在: %s" % rev)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return Response(content=data, media_type="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="%s.project"' % rev})

    @app.post("/api/plc/versions/snapshot")
    async def plc_version_snapshot(request: Request, body: dict | None = None):
        svc = _svc(request)
        message = (body or {}).get("message", "") if isinstance(body, dict) else ""
        try:
            entry = svc.snapshot(message)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return {"snapshotted": entry is not None, "version": entry}

    @app.post("/api/plc/versions/{rev}/restore")
    async def plc_version_restore(request: Request, rev: str):
        svc = _svc(request)
        try:
            return await svc.restore_version(rev)
        except KeyError:
            raise HTTPException(404, "版本不存在: %s" % rev)
        except PLCDeployPreconditionError as exc:
            raise HTTPException(409, detail=exc.payload())
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))

    # ---- 工位 L2 复位 (清故障): 由「设备」页工位节点调用 (执行→动作页, 状态→设备页遥测, 不在此重复) ----
    @app.post("/api/plc/stations/{station}/reset")
    async def plc_station_reset(request: Request, station: str):
        """脉冲 L2_Reset 清工位故障 (DEBUG 模式门控; 不产生回零运动)."""
        plc = request.app.state.plc
        if plc is None:
            raise HTTPException(503, "PLC 控制器未就绪")
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(403, "工位复位仅在 DEBUG 模式可用")
        try:
            await plc.reset(station)
            return {"station": station, "reset": True}
        except (RuntimeError, TimeoutError) as exc:
            raise HTTPException(502, str(exc))

    # ---- 工位初始化 ----------------------------------------------------------
    # 与上面的复位是两件事: 复位只脉冲 L2_Reset 清故障位、不动机构; 初始化是真的跑一遍
    # 工位的 *.init 原子 (清气缸/阀、轴归位、泵初始化)。两者都放在这里, 因为「设备」页
    # 的工位节点是它们共同的入口。
    #
    # 不做 DEBUG 门控 (与复位不同): 初始化是每天开机的正常操作而非调试手段, RUN 下也要能用。
    # 危险性由二次确认 (前端) + 工位锁 + 空闲守卫 (init_all) 兜住。
    def _init_action(request: Request, station: str) -> str:
        """工位名 -> 初始化动作名; 该工位没有 init 动作则 404 (不是错误, 是设计如此)."""
        name = f"{station.strip().lower()}.init"
        registry = request.app.state.registry
        try:
            registry.get(name)
        except KeyError:
            raise HTTPException(
                404, f"工位 {station} 没有初始化动作 ({name} 未定义)。"
                     f"泵站/地轨/中转A 是无状态的目标态动作, 本就不需要初始化") from None
        return name

    @app.post("/api/plc/stations/{station}/init")
    async def plc_station_init(request: Request, station: str):
        """跑单个工位的 *.init 原子 (RUN/DEBUG 均可)。

        走执行器而不是直写 PLC: 由它统一拿工位锁、施加超时与停滞看门狗, 并发
        operation_* 事件让前端「当前运行」面板实时点亮 —— 直写这些全都没有。
        动作被拒/报错同样回 200 (results 里 status 非 DONE), 与 /api/actions/{name}/run
        及 robot 便捷端点一致; 调用方据 ok/status 判成败, 不靠 HTTP 码。

        展缸会跑出 8 条 result (逐缸), 其余工位 1 条; 故返回体统一是列表而不是单个 DTO。
        """
        if request.app.state.plc is None:
            raise HTTPException(503, "PLC 控制器未就绪")
        executor = request.app.state.executor
        if executor is None:
            raise HTTPException(503, "动作执行器未就绪")
        key = station.strip().lower()
        name = _init_action(request, station)
        mode = request.app.state.control_mode
        results = []
        for params in _INIT_PARAM_SETS.get(key, ({},)):
            # 一缸失败不中断其余缸: 与全工站初始化同一口径 (跑完再汇总, 免得反复重跑才发现第二个故障)
            result = await executor.execute(name, dict(params), current_mode=mode)
            results.append(action_result_to_dto(result))
        return {"station": station, "action": name,
                "ok": all(r.status == ActionStatus.DONE.value for r in results),
                "results": results}

    @app.post("/api/plc/stations/init_all")
    async def plc_stations_init_all(request: Request):
        """全工站一键初始化: 走 system_init_all 编排 (RUN/DEBUG 均可)。

        走 VM 而不是在这里循环调执行器, 是为了留痕: 只有经 VM 才发 vm_*/operation_*
        事件、进 RunStore, 现场才看得出卡在第几站, 事后也才能回放。
        遇错策略在编排脚本里 (每站独立 try, 跑完再收口点名), 此处只负责起跑与转错误码。
        """
        if request.app.state.plc is None:
            raise HTTPException(503, "PLC 控制器未就绪")
        vm = getattr(request.app.state, "vm", None)
        if vm is None:
            raise HTTPException(503, "VM 控制器未就绪")
        repo = getattr(request.app.state, "script_repo", None)
        if repo is None:
            raise HTTPException(503, "脚本仓库未就绪")
        try:
            doc = repo.get(_WORKSPACE, _INIT_ALL_SCRIPT)
        except KeyError:
            raise HTTPException(503, f"编排脚本缺失: {_INIT_ALL_SCRIPT}") from None

        # 空闲守卫: 脚本根声明的 station:* 是 exclusive 资源, 被占时资源门是**等待**而非
        # 报错 —— 不先拦一道, 页面就会静静挂到超时才说话。只读检查, 不中止任何在跑动作。
        active = vm.active().get("runs", [])
        if active:
            raise HTTPException(409, "仍有流程在运行, 拒绝全工站初始化: " + ", ".join(
                str(item.get("operation") or item.get("run_id", "?")) for item in active[:5]))
        if request.app.state.plc.has_active_actions():
            raise HTTPException(409, "仍有 PLC L2 动作占用工位, 拒绝全工站初始化")

        try:
            started = await vm.start(doc, {})
        except MaintenanceActiveError as exc:
            raise HTTPException(409, str(exc)) from exc
        run_id = started["run_id"]
        try:
            state = await vm.wait_final(run_id, timeout=_INIT_ALL_TIMEOUT_S)
        except asyncio.TimeoutError:
            # 不掐运行: 轴可能正在动, 掐掉只会留下一个说不清的中间态。交由前端按 run_id 跟。
            raise HTTPException(
                504, f"全工站初始化超过 {_INIT_ALL_TIMEOUT_S:.0f} 秒仍未结束 (run_id={run_id}); "
                     f"运行未被终止, 请在运行历史或实时监视器里跟进") from None
        if state["status"] != "DONE":
            store = getattr(request.app.state, "run_store", None)
            detail = ((store.get_run(run_id) or {}).get("message") if store else "") or "全工站初始化未完成"
            raise HTTPException(422, f"{detail} (run_id={run_id})")
        return {"run_id": run_id, "status": state["status"], "ok": True}
