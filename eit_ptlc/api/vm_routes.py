"""VM 编排路由
============
功能:
    注册脚本仓库 CRUD 与 VM 运行/调试/HITL 端点到 FastAPI 应用. 全部从 app.state 读取
    script_repo (ScriptRepo) 与 vm (VmController). 运行历史/回放复用既有 /api/runs.

端点 (前缀 /api):
    GET    /scripts/workspaces                 工作区列表
    GET    /scripts?ws=&kind=                  脚本摘要列表
    GET    /scripts/{name}?ws=                 单脚本节点树
    POST   /scripts {name,kind,label} ?ws=     新建空脚本
    PUT    /scripts/{name} {doc} ?ws=          保存脚本 (校验 + 快照)
    DELETE /scripts/{name}?ws=                 删除脚本
    POST   /scripts/{name}/clone {dst} ?ws=    克隆
    POST   /scripts/{name}/rename {dst} ?ws=   重命名 (英文ID + 文件名)
    POST   /scripts/{name}/label {label} ?ws=  改显示名 (仅 label, 不动英文ID/文件名)
    GET    /scripts/{name}/versions?ws=        版本历史
    GET    /scripts/{name}/versions/{rev}?ws=  某版本节点树
    GET    /scripts/{name}/debug/knobs?ws=        运行前旋钮 (带 ui 的 in var, 树内递归收集)
    POST   /scripts/{name}/debug/run {inputs,mode,mode_run,start_aid?,overrides?} ?ws=   启动运行/调试
    POST   /debug/{run_id}/{step|step_over|run|pause|resume}       调试动词 (step=步入/step_over=步过; pause=冻结/resume=续跑)
    POST   /debug/{run_id}/{stop_after|terminate|estop|stop}       停止动词 (边界停/终止/急停; stop=terminate 别名)
    POST   /debug/{run_id}/reset {aid?}                            复位 (含到节点)
    GET    /debug/{run_id}/{state|vars}                            查询
    GET    /debug/active                                           非终态运行列表 (rehydrate: 含挂起 human 请求)
    POST   /debug/{run_id}/breakpoints {aids}                      设断点
    POST   /debug/{run_id}/human/{req_id} {choice?,values?}        人工回复
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.operation.vm.inputs import validate_inputs
from eit_ptlc.operation.vm.knobs import collect_knobs, validate_overrides
from eit_ptlc.runtime.maintenance_gate import MaintenanceActiveError
from eit_ptlc.api.vm_dto import (
    BreakpointsBody,
    HumanReplyBody,
    LabelBody,
    NameBody,
    ResetBody,
    ScriptCreateBody,
    ScriptWriteBody,
    VmStartBody,
    new_script_doc,
)

log = logging.getLogger(__name__)


def register_vm_routes(app: FastAPI) -> None:
    """把 VM 编排路由注册到应用."""

    def _repo(request: Request):
        repo = request.app.state.script_repo
        if repo is None:
            raise HTTPException(503, "脚本仓库未就绪")
        return repo

    def _vm(request: Request):
        vm = request.app.state.vm
        if vm is None:
            raise HTTPException(503, "VM 控制器未就绪")
        return vm

    # ------------------------------------------------------------------
    # 脚本仓库
    # ------------------------------------------------------------------

    @app.get("/api/scripts/workspaces")
    async def list_workspaces(request: Request):
        return _repo(request).list_workspaces()

    @app.get("/api/scripts")
    async def list_scripts(request: Request, ws: str = "default", kind: str | None = None):
        return _repo(request).list_scripts(ws, kind=kind)

    @app.get("/api/scripts/{name}")
    async def get_script(request: Request, name: str, ws: str = "default"):
        try:
            return _repo(request).get(ws, name)
        except KeyError:
            raise HTTPException(404, f"脚本不存在: {ws}/{name}")

    @app.post("/api/scripts")
    async def create_script(request: Request, body: ScriptCreateBody, ws: str = "default"):
        try:
            return _repo(request).create(ws, body.name, new_script_doc(body.name, body.kind, body.label),
                                         group=body.group or "")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.put("/api/scripts/{name}")
    async def save_script(request: Request, name: str, body: ScriptWriteBody, ws: str = "default"):
        try:
            return _repo(request).update(ws, name, body.doc)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.delete("/api/scripts/{name}")
    async def delete_script(request: Request, name: str, ws: str = "default"):
        _repo(request).delete(ws, name)
        return {"deleted": name}

    @app.post("/api/scripts/{name}/clone")
    async def clone_script(request: Request, name: str, body: NameBody, ws: str = "default"):
        try:
            return _repo(request).clone(ws, name, body.dst)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/scripts/{name}/rename")
    async def rename_script(request: Request, name: str, body: NameBody, ws: str = "default"):
        try:
            return _repo(request).rename(ws, name, body.dst)
        except KeyError:
            raise HTTPException(404, f"脚本不存在: {ws}/{name}")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/scripts/{name}/label")
    async def set_script_label(request: Request, name: str, body: LabelBody, ws: str = "default"):
        try:
            return _repo(request).set_label(ws, name, body.label)
        except KeyError:
            raise HTTPException(404, f"脚本不存在: {ws}/{name}")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/scripts/{name}/versions")
    async def list_versions(request: Request, name: str, ws: str = "default"):
        return _repo(request).history(ws, name)

    @app.get("/api/scripts/{name}/versions/{rev}")
    async def get_version(request: Request, name: str, rev: str, ws: str = "default"):
        try:
            return _repo(request).get_version(ws, name, rev)
        except KeyError:
            raise HTTPException(404, f"版本不存在: {ws}/{name}@{rev}")

    # ------------------------------------------------------------------
    # 运行 / 调试
    # ------------------------------------------------------------------

    @app.get("/api/scripts/{name}/debug/knobs")
    async def debug_knobs(request: Request, name: str, ws: str = "default"):
        """运行前旋钮: 静态遍历该 operation 的 run_script 树, 收集带 ui 的 in var (可覆盖白名单)。

        附带下钻树所需的两项: actions (消费该旋钮的动作 + 其 schema label) 与 live (live_from 解析出的
        当前示教基准, 供几何旋钮面板预填)。points/registry 缺省即降级 (live=None / label=动作名)。
        """
        repo = _repo(request)
        try:
            doc = repo.get(ws, name)
        except KeyError:
            raise HTTPException(404, f"脚本不存在: {ws}/{name}")
        points = getattr(request.app.state, "points", None)
        registry = getattr(request.app.state, "registry", None)

        def _action_label(action_name: str) -> str:
            try:
                return registry.get(action_name).label if registry is not None else action_name
            except Exception:
                return action_name  # 未知动作: 降级用动作名 (收集阶段容错, 不阻断面板)

        return {"knobs": collect_knobs(doc, lambda n: repo.get(ws, n),
                                       resolve_action_label=_action_label, points=points)}

    @app.post("/api/scripts/{name}/debug/run")
    async def debug_run(request: Request, name: str, body: VmStartBody, ws: str = "default"):
        repo, vm = _repo(request), _vm(request)
        try:
            doc = repo.get(ws, name)
        except KeyError:
            raise HTTPException(404, f"脚本不存在: {ws}/{name}")
        # 运行前提交校验: 取值域外的入参未跑先拒。不拦的话要一路跑到脚本末尾
        # `else: raise ROBOT_FLOW_SELECTOR` 才炸, 那时机器人已 home 完并换过刀。
        # 只校声明了 enum 的 in 变量, 其余入参 (samples / ctx 键等) 一律放行。
        if body.inputs:
            errors = validate_inputs(doc, body.inputs)
            if errors:
                raise HTTPException(400, "入参非法: " + "; ".join(errors))
        # 运行前提交校验: 越界/未知旋钮未跑先拒 (免机器人空跑几步才在动作处失败); 安全兜底仍在动作层
        if body.overrides:
            errors = validate_overrides(collect_knobs(doc, lambda n: repo.get(ws, n)), body.overrides)
            if errors:
                raise HTTPException(400, "旋钮覆盖非法: " + "; ".join(errors))
        mode_run = "step" if body.mode_run == "step" else "run"
        if body.command_id:
            try:
                return vm.state(body.command_id)
            except KeyError:
                pass
        try:
            return await vm.start(doc, body.inputs, mode_run=mode_run, start_aid=body.start_aid,
                                  overrides=body.overrides, run_id=body.command_id)
        except MaintenanceActiveError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/debug/{run_id}/step")
    async def debug_step(request: Request, run_id: str):
        """单步步入: 放行一个叶子, 在下一个叶子 (任意层级, 含子脚本内部) 停驻."""
        return await _vm_call(request, run_id, "step")

    @app.post("/api/debug/{run_id}/step_over")
    async def debug_step_over(request: Request, run_id: str):
        """单步步过: 子脚本 (run_script) 一次执行完, 停在父流程下一叶子."""
        return await _vm_call(request, run_id, "step_over")

    @app.post("/api/debug/{run_id}/run")
    async def debug_continue(request: Request, run_id: str):
        return await _vm_call(request, run_id, "run")

    @app.post("/api/debug/{run_id}/pause")
    async def debug_pause(request: Request, run_id: str):
        return await _vm_call(request, run_id, "pause")

    @app.post("/api/debug/{run_id}/resume")
    async def debug_resume(request: Request, run_id: str):
        return await _vm_call(request, run_id, "resume")

    @app.post("/api/debug/{run_id}/stop_after")
    async def debug_stop_after(request: Request, run_id: str):
        """运行后停止: 跑完当前动作停在边界 (可 resume 放行下一动作)."""
        return await _vm_call(request, run_id, "stop_after")

    @app.post("/api/debug/{run_id}/terminate")
    async def debug_terminate(request: Request, run_id: str):
        """终止运行: 软停机器人 (不报警) + 干净结束本次运行 (不可继续)."""
        return await _vm_call(request, run_id, "terminate")

    @app.post("/api/debug/{run_id}/estop")
    async def debug_estop(request: Request, run_id: str):
        """急停: 失能臂并报警 + 结束运行; 释放/清警走机器人维护端点."""
        return await _vm_call(request, run_id, "estop")

    @app.post("/api/debug/{run_id}/stop")
    async def debug_stop(request: Request, run_id: str):
        """兼容旧端点: 等价于 terminate."""
        return await _vm_call(request, run_id, "stop")

    @app.post("/api/debug/{run_id}/reset")
    async def debug_reset(request: Request, run_id: str, body: ResetBody | None = None):
        vm = _vm(request)
        try:
            return await vm.reset(run_id, (body.aid if body else None))
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    @app.get("/api/debug/active")
    async def debug_active(request: Request):
        """非终态运行列表 (含挂起的 human 请求全文): 前端刷新/WS 断线重连后重建弹窗与调试状态."""
        return _vm(request).active()

    @app.get("/api/debug/{run_id}/state")
    async def debug_state(request: Request, run_id: str):
        try:
            return _vm(request).state(run_id)
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    @app.get("/api/debug/{run_id}/vars")
    async def debug_vars(request: Request, run_id: str):
        try:
            return _vm(request).vars(run_id)
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    @app.post("/api/debug/{run_id}/breakpoints")
    async def debug_breakpoints(request: Request, run_id: str, body: BreakpointsBody):
        try:
            return _vm(request).set_breakpoints(run_id, body.aids)
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    @app.post("/api/debug/{run_id}/human/{req_id}")
    async def debug_human(request: Request, run_id: str, req_id: str, body: HumanReplyBody):
        vm = _vm(request)
        try:
            return await vm.human_reply(run_id, req_id, {"choice": body.choice, "values": body.values})
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")

    async def _vm_call(request: Request, run_id: str, verb: str):
        vm = _vm(request)
        fn = getattr(vm, verb)
        try:
            return await fn(run_id)
        except KeyError:
            raise HTTPException(404, f"无此运行: {run_id}")
