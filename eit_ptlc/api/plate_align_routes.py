"""板位对位控制台 API (点样视觉零点一键示教)
================================================
功能:
    暴露 `.163` 对位相机的板位零点示教端点, 供独立"板位对位"控制台调用。示教是标定写操作,
    teach/apply 均要求 control_mode==DEBUG; apply 另需 confirm=true (防误触污染零点)。

端点:
    GET  /api/plate_align/status  当前零点参考 (u0/v0/theta0) + Bridge 状态
    POST /api/plate_align/teach   取板→P86 拍姿→放回, 返回测得零点与当前零点比对 (不写盘)
    POST /api/plate_align/apply   {u,v,theta,confirm} 写回 reference + 令 Bridge 热更
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from eit_ptlc.controller.pallas_vision_client import PallasVisionError
from eit_ptlc.controller.plate_align_service import PlateAlignError

log = logging.getLogger(__name__)


class ApplyRequest(BaseModel):
    """写零点请求: 取自一次合理 teach 的测得位姿, confirm 二次确认。"""

    model_config = ConfigDict(extra="forbid")

    u: float
    v: float
    theta: float
    confirm: bool = Field(default=False)


def register_plate_align_routes(app: FastAPI) -> None:
    """注册板位对位示教端点。"""

    def _service(request: Request):
        service = getattr(request.app.state, "plate_align", None)
        if service is None:
            raise HTTPException(503, "板位对位服务未就绪")
        return service

    def _require_debug(request: Request, what: str) -> None:
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, f"{what}仅在 DEBUG 模式下可用")

    @app.get("/api/plate_align/status")
    async def plate_align_status(request: Request):
        try:
            return await _service(request).status()
        except PlateAlignError as exc:
            raise HTTPException(422, str(exc)) from exc
        except PallasVisionError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/plate_align/teach")
    async def plate_align_teach(request: Request):
        _require_debug(request, "示教零点")
        try:
            return await _service(request).teach(current_mode="DEBUG")
        except PlateAlignError as exc:
            raise HTTPException(422, str(exc)) from exc
        except PallasVisionError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/plate_align/apply")
    async def plate_align_apply(request: Request, body: ApplyRequest):
        _require_debug(request, "写零点")
        if not body.confirm:
            raise HTTPException(409, "写零点需 confirm=true 二次确认")
        try:
            return await _service(request).apply(body.u, body.v, body.theta)
        except PlateAlignError as exc:
            raise HTTPException(422, str(exc)) from exc
        except PallasVisionError as exc:
            raise HTTPException(503, str(exc)) from exc
