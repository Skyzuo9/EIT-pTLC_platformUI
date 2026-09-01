"""实验调度路由 (调度方案 / 批次提交 / 段作业恢复 / 调度快照)
==============================================================
功能:
    实验系统的完整 API 面: 调度方案枚举/校验/编辑、批量样品提交 (完整工艺参数快照)、
    批次/样品/段作业三级控制动词、调度器快照 (看板权威投影)、结果数据查询。
    全部经 app.state.scheduler (FlowScheduler) 与 app.state.experiment_store; 未就绪 503。

端点 (前缀 /api):
    GET  /recipes                         方案清单 (含段序/停放位/依赖/hitl/retry)
    GET  /recipes/{name}/validate         方案全链静态校验 (R1-R3 + 位置连续 + 接线)
    GET  /recipes/{name}/doc              结构化源 doc (图形化编排器加载; depends 已显式化)
    PUT  /recipes/{name}/doc              结构化落盘 {doc} (规范化 YAML; 原文注释被取代)
    GET  /recipes/{name}/raw              YAML 原文 (文本页签加载; # 注释保留)
    PUT  /recipes/{name}/raw              原文落盘 {text} (逐字保留)
    POST /recipes/validate                干跑校验 {doc} 或 {text} -> {ok, errors, recipe?} (不落盘)
                                          落盘两路同守卫: name 不符/校验失败 400,
                                          被未完结批次引用 409; PUT 新名字 = 新建 (另存为)
    POST /experiments                     提交批次 -> {batch_id, sample_ids}; 重名 409
    GET  /experiments?limit&status        批次列表 (含 sample_total/sample_done)
    GET  /experiments/{bid}               批次详情 (批+样品+段+参数快照)
    POST /experiments/{bid}/{verb}        批级动词 start|pause|resume|abort
    POST /experiments/{bid}/samples/{sid}/{verb}          样品动词 abort|hold|resume
    POST /experiments/{bid}/samples/{sid}/jobs/{flow}/{verb}  段动词 retry|resume|skip|mark_done
                                          (flow 可为段 id 如 s2, 也可为拓扑序号; retry 铸新
                                           run_id, 响应带回; body 可带 confirm/position/context)
    POST /experiments/{bid}/reconcile     重启/中止后的人工对账 (逐段处置+缸/占位释放)
    GET  /experiments/{bid}/results       批次结果 (视觉指标, 含 Rf)
    GET  /experiments/{bid}/timeline      段起止时间证据 (双样品重叠验收即查此)
    GET  /experiments/{bid}/events        调度决策审计流水
    GET  /scheduler/snapshot              看板权威投影 (队列/资源持有者/缸池/等待原因/服务端钟)

动词语义 (前端确认门文案照此):
    批 pause  = 停止派发新段; 在飞段跑完当前段自然停在段边界。
    批 abort  = 不再派发 + 待派段取消 + 释放物料预留; 在飞段跑完记账; 物理残留走对账。
    样品 hold = 跑完当前段后该样品不再推进 (段边界软停); resume 恢复。
    段 retry  = 整段重跑 (restart 段直接重派; 其余需 confirm=true 人工确认物理态)。
    段 resume = 断点续跑 (仅 retry:resume 段; 从失败 AID 顶层语句边界续 + 变量回注)。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.operation.recipe import RecipeError
from eit_ptlc.operation.scheduler import SubmitError

log = logging.getLogger(__name__)

_BATCH_VERBS = {"start", "pause", "resume", "abort"}
_SAMPLE_VERBS = {"abort", "hold", "resume"}
_JOB_VERBS = {"retry", "resume", "skip", "mark_done"}


def register_scheduler_routes(app: FastAPI) -> None:
    """把并行实验调度路由注册到应用 (必须在 _mount_spa 之前)。"""

    def _sched(request: Request):
        sched = getattr(request.app.state, "scheduler", None)
        if sched is None:
            raise HTTPException(503, "并行调度器未就绪")
        return sched

    def _exp(request: Request):
        store = getattr(request.app.state, "experiment_store", None)
        if store is None:
            raise HTTPException(503, "实验数据库未就绪")
        return store

    # ------------------------------------------------------------------
    # 调度方案 (UI 的"调度"层; 代码内标识符沿用 recipe)
    # ------------------------------------------------------------------

    @app.get("/api/recipes")
    async def list_recipes(request: Request):
        return {"recipes": _sched(request).list_recipes()}

    @app.get("/api/recipes/{name}/validate")
    async def validate_recipe(request: Request, name: str):
        try:
            errors = _sched(request).validate_recipe_by_name(name)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except RecipeError as exc:
            return {"name": name, "ok": False, "errors": [str(exc)]}
        return {"name": name, "ok": not errors, "errors": errors}

    @app.get("/api/recipes/{name}/raw")
    async def get_recipe_raw(request: Request, name: str):
        try:
            return {"name": name, "text": _sched(request).read_recipe_text(name)}
        except KeyError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/recipes/{name}/doc")
    async def get_recipe_doc(request: Request, name: str):
        try:
            return {"name": name, "doc": _sched(request).read_recipe_doc(name)}
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except RecipeError as exc:      # 磁盘上的方案本身坏了: 结构化路无法加载, 走文本页签修
            raise HTTPException(400, str(exc))

    @app.post("/api/recipes/validate")
    async def validate_recipe_payload(request: Request):
        """干跑校验: body 带 doc 走结构化路 (画布), 带 text 走文本路; doc 优先。"""
        body = await request.json() or {}
        sched = _sched(request)
        if body.get("doc") is not None:
            errors, dto = sched.validate_recipe_doc(body.get("doc"))
        else:
            errors, dto = sched.validate_recipe_text(str(body.get("text") or ""))
        return {"ok": not errors, "errors": errors, "recipe": dto}

    @app.put("/api/recipes/{name}/raw")
    async def save_recipe_raw(request: Request, name: str):
        body = await request.json()
        try:
            return _sched(request).save_recipe_text(name, str((body or {}).get("text") or ""))
        except SubmitError as exc:
            raise HTTPException(409 if exc.conflict else 400, str(exc))

    @app.put("/api/recipes/{name}/doc")
    async def save_recipe_doc(request: Request, name: str):
        body = await request.json()
        try:
            return _sched(request).save_recipe_doc(name, (body or {}).get("doc"))
        except SubmitError as exc:
            raise HTTPException(409 if exc.conflict else 400, str(exc))

    # ------------------------------------------------------------------
    # 批次
    # ------------------------------------------------------------------

    @app.post("/api/experiments")
    async def submit_experiment(request: Request):
        body = await request.json()
        try:
            return await _sched(request).submit_batch(dict(body or {}))
        except SubmitError as exc:
            raise HTTPException(409 if exc.conflict else 400, str(exc))
        except (RecipeError, KeyError) as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/experiments")
    async def list_experiments(request: Request, limit: int = 50, status: str = ""):
        return {"batches": _exp(request).list_batches(limit=limit, status=status or None)}

    @app.get("/api/experiments/{batch_id}")
    async def get_experiment(request: Request, batch_id: str):
        detail = _exp(request).get_batch_detail(batch_id)
        if detail is None:
            raise HTTPException(404, f"批次不存在: {batch_id}")
        return detail

    @app.post("/api/experiments/{batch_id}/{verb}")
    async def batch_verb(request: Request, batch_id: str, verb: str):
        if verb == "reconcile":
            return await _reconcile(request, batch_id)
        if verb not in _BATCH_VERBS:
            raise HTTPException(404, f"未知批级动词: {verb}")
        sched = _sched(request)
        try:
            return await getattr(sched, f"batch_{verb}")(batch_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    async def _reconcile(request: Request, batch_id: str):
        body = await request.json() if await request.body() else {}
        try:
            return await _sched(request).reconcile(
                batch_id, list(body.get("decisions") or []),
                release_tanks=body.get("release_tanks"),
                clear_occupancy=body.get("clear_occupancy"))
        except KeyError as exc:
            raise HTTPException(404, str(exc))

    # ------------------------------------------------------------------
    # 样品与段作业
    # ------------------------------------------------------------------

    @app.post("/api/experiments/{batch_id}/samples/{sample_id}/{verb}")
    async def sample_verb(request: Request, batch_id: str, sample_id: str, verb: str):
        if verb not in _SAMPLE_VERBS:
            raise HTTPException(404, f"未知样品动词: {verb}")
        sched = _sched(request)
        try:
            return await getattr(sched, f"sample_{verb}")(batch_id, sample_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/experiments/{batch_id}/samples/{sample_id}/jobs/{flow}/{verb}")
    async def job_verb(request: Request, batch_id: str, sample_id: str, flow: str, verb: str):
        if verb not in _JOB_VERBS:
            raise HTTPException(404, f"未知段动词: {verb}")
        body = {}
        raw = await request.body()
        if raw:
            body = await request.json()
        sched = _sched(request)
        try:
            if verb == "retry":
                return await sched.job_retry(batch_id, sample_id, flow,
                                             confirm=bool(body.get("confirm")))
            if verb == "resume":
                return await sched.job_resume(batch_id, sample_id, flow)
            return await sched.job_skip(batch_id, sample_id, flow,
                                        position=body.get("position"),
                                        context=body.get("context"),
                                        mark_done=verb == "mark_done")
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    # ------------------------------------------------------------------
    # 结果与审计
    # ------------------------------------------------------------------

    @app.get("/api/experiments/{batch_id}/results")
    async def batch_results(request: Request, batch_id: str, sample_id: str = ""):
        store = _exp(request)
        if store.get_batch(batch_id) is None:
            raise HTTPException(404, f"批次不存在: {batch_id}")
        return {"results": store.list_results(batch_id=batch_id,
                                              sample_id=sample_id or None)}

    @app.get("/api/experiments/{batch_id}/timeline")
    async def batch_timeline(request: Request, batch_id: str):
        """段起止时间证据 (并行验收: 双样品展开区间相交即真重叠)."""
        store = _exp(request)
        if store.get_batch(batch_id) is None:
            raise HTTPException(404, f"批次不存在: {batch_id}")
        rows = [{
            "job_id": j["job_id"], "sample_id": j.get("sample_id"),
            "flow_id": j["flow_id"], "seq": j["af_index"], "status": j["status"],
            "run_id": j.get("run_id") or "", "started_at": j.get("started_at"),
            "finished_at": j.get("finished_at"),
        } for j in store.list_jobs(batch_id=batch_id)]
        return {"batch_id": batch_id, "jobs": rows}

    @app.get("/api/experiments/{batch_id}/events")
    async def batch_events(request: Request, batch_id: str, limit: int = 500):
        return {"events": _exp(request).list_events(batch_id, limit=limit)}

    # ------------------------------------------------------------------
    # 快照
    # ------------------------------------------------------------------

    @app.get("/api/scheduler/snapshot")
    async def scheduler_snapshot(request: Request):
        return _sched(request).snapshot()
