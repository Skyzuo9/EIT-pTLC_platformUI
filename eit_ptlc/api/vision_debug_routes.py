"""独立视觉调试台 API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eit_ptlc.controller.vision_debug_service import VisionDebugError


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaptureRequest(_StrictRequest):
    role: Literal["before", "after"]
    exposure_time_us: int = Field(gt=0, le=2_000_000)
    gain: float = Field(ge=0)
    uv_on_time_ms: int = Field(gt=0, le=1800)

    @model_validator(mode="after")
    def validate_timing(self):
        if self.exposure_time_us / 1000 > self.uv_on_time_ms:
            raise ValueError("曝光时间不能大于 UV 总点亮时间")
        return self


class AnalyzeRequest(_StrictRequest):
    image_plate_orientation: Literal["rot0", "rot90cw", "rot180", "rot270cw"]
    auto_rectify_tilt: bool
    rectify_min_angle_deg: float = Field(ge=0, le=45)
    min_row_score: float = Field(ge=0)
    image_plate_rotation_deg: float | None = Field(default=None, ge=-180, le=180)


class LoadCaseRequest(_StrictRequest):
    summary_dir: str


class CncPreviewRequest(_StrictRequest):
    band_id: str = Field(min_length=1, max_length=120)


def _service(request: Request):
    service = request.app.state.vision_debug
    if service is None:
        raise HTTPException(503, "视觉调试服务未就绪")
    return service


def _raise_debug_error(exc: VisionDebugError) -> None:
    raise HTTPException(exc.status_code, str(exc)) from exc


def register_vision_debug_routes(app: FastAPI) -> None:
    @app.get("/api/vision/debug/state")
    async def get_state(request: Request):
        return _service(request).state

    @app.post("/api/vision/debug/capture")
    async def capture(request: Request, body: CaptureRequest):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "拍照仅在 DEBUG 模式下可用")
        try:
            return await _service(request).capture(
                body.role,
                body.model_dump(exclude={"role"}),
            )
        except VisionDebugError as exc:
            _raise_debug_error(exc)

    @app.post("/api/vision/debug/upload/{role}")
    async def upload(
        request: Request,
        role: Literal["before", "after"],
        file: UploadFile = File(...),
    ):
        content = await file.read()
        if not content:
            raise HTTPException(422, "上传文件为空")
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(413, "图片不能超过 50 MB")
        try:
            return await _service(request).upload(
                role,
                content,
                file.filename or f"{role}.jpg",
            )
        except VisionDebugError as exc:
            _raise_debug_error(exc)

    @app.post("/api/vision/debug/analyze")
    async def analyze(request: Request, body: AnalyzeRequest):
        try:
            return await _service(request).analyze(body.model_dump())
        except VisionDebugError as exc:
            _raise_debug_error(exc)

    @app.post("/api/vision/debug/cnc_preview")
    async def cnc_preview(request: Request, body: CncPreviewRequest):
        cfg_svc = getattr(request.app.state, "config_svc", None)
        if cfg_svc is None:
            raise HTTPException(503, "配置服务未就绪")
        try:
            from eit_ptlc.config.loader import _parse_gcode

            gcode_cfg = _parse_gcode(cfg_svc.read_section("gcode"))
            return await _service(request).generate_cnc_preview(
                body.band_id, gcode_cfg,
            )
        except VisionDebugError as exc:
            _raise_debug_error(exc)

    @app.post("/api/vision/debug/apply_to_production")
    async def apply_to_production(request: Request):
        """把调试台当前识别参数写回 config.vision 单一真源 ("应用到生产", 打通调参↔生产)。

        生产 analyze 运行期实时读 config.vision (见 bootstrap._analyze_live), 故写盘后**下一次
        analyze 即生效, 无需重启**。写盘经 ConfigService.save_section (复用 _parse_vision 全量
        校验 + ruamel 保留注释); 只写 5 个识别参数(含 image_plate_rotation_deg, None=每帧自动估), 不动 vision 段其余项 (mock/output_dir)。
        """
        cfg_svc = getattr(request.app.state, "config_svc", None)
        if cfg_svc is None:
            raise HTTPException(503, "配置服务未就绪")
        recog = _service(request).state.get("recognition_params") or {}
        values = {
            key: recog[key]
            for key in (
                "image_plate_orientation",
                "auto_rectify_tilt",
                "rectify_min_angle_deg",
                "min_row_score",
                "image_plate_rotation_deg",
            )
            if key in recog
        }
        if not values:
            raise HTTPException(422, "调试台无可应用的识别参数")
        try:
            cfg_svc.save_section("vision", values)
        except (ValueError, PermissionError) as exc:
            raise HTTPException(422, str(exc))
        return {"section": "vision", "applied": values}

    def _vision_output_root(request: Request) -> Path:
        cfg_svc = getattr(request.app.state, "config_svc", None)
        if cfg_svc is None:
            raise HTTPException(503, "配置服务未就绪")
        section = cfg_svc.read_section("vision") or {}
        return Path(section.get("output_dir", "vision_output"))

    @app.get("/api/vision/debug/cases")
    async def list_cases(request: Request):
        """列出可载入调试台复盘的生产分析 case (config.vision.output_dir 下含 inputs.json 的子目录)。"""
        root = _vision_output_root(request)
        cases = []
        if root.is_dir():
            for entry in root.iterdir():
                if not entry.is_dir() or not (entry / "inputs.json").is_file():
                    continue
                cases.append({
                    "id": entry.name,
                    "summary_dir": str(entry),
                    "mtime_iso": datetime.fromtimestamp(
                        entry.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
        cases.sort(key=lambda c: c["mtime_iso"], reverse=True)
        return {"cases": cases[:50], "truncated": len(cases) > 50}

    @app.post("/api/vision/debug/load_case")
    async def load_case(request: Request, body: LoadCaseRequest):
        """把生产 case 的 before/after 载入调试台工作区复盘调参 (走与上传同一归一化路径)。"""
        root = _vision_output_root(request)
        case_dir = Path(body.summary_dir)
        try:
            case_dir.resolve().relative_to(root.resolve())
        except ValueError:
            raise HTTPException(404, "case 不在视觉输出目录下")
        inputs_file = case_dir / "inputs.json"
        if not inputs_file.is_file():
            raise HTTPException(404, "该 case 缺少 inputs.json, 无法载入")
        try:
            inputs = json.loads(inputs_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(500, f"读取 inputs.json 失败: {exc}") from exc
        service = _service(request)
        # 两遍循环: 先只校验两个 image_path 全部存在 (不动工作区), 全过再依次 upload。
        # 消除"逐 role 查文件→upload"半途失败(after 缺失 404)时 before 已写入的混对态。
        image_paths: dict[str, Path] = {}
        for role, key in (("before", "before_path"), ("after", "after_path")):
            image_path = Path(str(inputs.get(key) or ""))
            if not image_path.is_file():
                raise HTTPException(404, f"该 case 的 {role} 原始图片已被清理: {image_path}")
            image_paths[role] = image_path
        state = None
        for role, image_path in image_paths.items():
            try:
                state = await service.upload(
                    role,
                    image_path.read_bytes(),
                    image_path.name,
                    source=f"case:{case_dir.name}",
                )
            except VisionDebugError as exc:
                _raise_debug_error(exc)
        observation = None
        observation_file = case_dir / "liquid_observation.json"
        if observation_file.is_file():
            try:
                observation = json.loads(observation_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise HTTPException(500, f"读取液位观测旁挂失败: {exc}") from exc
        return await service.set_source_context({
            "sample_id": str(inputs.get("sample_id") or case_dir.name),
            "case_dir": str(case_dir),
            "liquid_observation": observation,
        })

    @app.get("/api/vision/debug/file/{filename:path}")
    async def serve_file(request: Request, filename: str):
        path = _service(request).get_file_path(filename)
        if path is None or not path.is_file():
            raise HTTPException(404, "文件不存在")
        return FileResponse(path, headers={"Cache-Control": "no-store"})
