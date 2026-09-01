"""视觉产物图片服务
==================
功能:
    把视觉分析产物 (标注图 *_annotated.png 等) 以同源 HTTP 暴露给浏览器, 供 HITL 弹窗
    <img> 直接加载。前端经 vite 代理 /api → FastAPI, 故 analyze_action 返回的相对 URL
    "/api/vision/image/<相对 output_dir 的路径>" 可直接作为 <img src>。

    output_dir 取自 config_svc 的 vision 段 (缺省 vision_output), 与 VisionService 写盘一致。

端点:
    GET /api/vision/image/{path}   返回 output_dir/{path} 下的图片 (限图片后缀 + 防目录穿越)
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

log = logging.getLogger(__name__)

_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg"}


def _vision_output_dir(request: Request) -> Path:
    """解析 vision.output_dir (随 config 实时; 缺省 vision_output), 返回绝对路径。"""
    out = "vision_output"
    cfg_svc = getattr(request.app.state, "config_svc", None)
    if cfg_svc is not None:
        try:
            out = cfg_svc.read_section("vision").get("output_dir") or out
        except Exception:  # noqa: BLE001 配置读取失败回落默认, 不阻断取图
            pass
    return Path(out).resolve()


def register_vision_routes(app: FastAPI) -> None:
    """注册视觉产物图片端点。"""

    @app.get("/api/vision/image/{path:path}")
    async def serve_vision_image(request: Request, path: str):
        base = _vision_output_dir(request)
        target = (base / path).resolve()
        # 防目录穿越: 解析后必须仍在 output_dir 之下
        if not target.is_relative_to(base):
            raise HTTPException(403, "非法路径")
        if target.suffix.lower() not in _ALLOWED_SUFFIXES or not target.is_file():
            raise HTTPException(404, "图片不存在")
        return FileResponse(target)
