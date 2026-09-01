"""设备参数路由
============
功能:
    注册 app.yaml 设备参数段 (camera / gcode / vision / pump) 的读写端点到 FastAPI 应用。
    从 app.state.config_svc (ConfigService) 读取; 未就绪返回 503。保存经 loader 校验,
    不通过 400 且不写盘 (见 ConfigService)。

端点 (前缀 /api):
    GET /config/{section}            读取段当前值 (camera|gcode|vision|pump)
    PUT /config/{section} {values}   校验后合并保存 (保留 yaml 注释)
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request

log = logging.getLogger(__name__)


def register_config_routes(app: FastAPI) -> None:
    """把设备参数路由注册到应用。"""

    def _cfg(request: Request):
        svc = request.app.state.config_svc
        if svc is None:
            raise HTTPException(503, "配置服务未就绪")
        return svc

    @app.get("/api/config/{section}")
    async def get_config_section(request: Request, section: str):
        try:
            return {"section": section, "values": _cfg(request).read_section(section)}
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @app.put("/api/config/{section}")
    async def save_config_section(request: Request, section: str, body: dict):
        values = body.get("values")
        if not isinstance(values, dict):
            raise HTTPException(400, "请求体缺少 values 对象")
        try:
            return _cfg(request).save_section(section, values)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
