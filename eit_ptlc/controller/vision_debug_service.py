"""独立视觉调试台服务.

该服务只维护一组 Before/After 与当前分析结果，供拍照质量和双帧算法调试。
它复用正式 CameraController / VisionService，不接入生产 operation。
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import shutil
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _image_size(path: Path) -> tuple[int, int] | None:
    """读图像像素尺寸 (width, height); 任何失败返回 None, 不阻断主流程.

    用途: capture/upload 返回体附带 image_width/height (纯增量可选字段),
    前端据此在 analyze 之前就能给图位设 aspect-ratio 消布局位移
    (拍照相机整幅传感器无固定比例契约, 尺寸只能按实图取)。
    """
    try:
        from PIL import Image  # 延迟导入: 视觉栈已依赖 Pillow, 但缺失时静默降级

        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return None


_CAMERA_KEYS = ("exposure_time_us", "gain", "uv_on_time_ms")
_RECOGNITION_KEYS = (
    "image_plate_orientation",
    "auto_rectify_tilt",
    "rectify_min_angle_deg",
    "min_row_score",
    "image_plate_rotation_deg",
)
_FILE_WHITELIST = frozenset({
    "before.jpg",
    "after.jpg",
    "state.json",
    "before_quality.png",
    "after_quality.png",
    "result/summary.json",
    "result/score.png",
    "result/annotated.png",
    "result/cnc_preview.png",
})


class VisionDebugError(RuntimeError):
    """已写入 state.json 的调试操作错误."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _initial_state(
    camera_defaults: dict[str, Any] | None = None,
    recognition_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    camera = {
        "exposure_time_us": 1_000_000,
        "gain": 1.0,
        "uv_on_time_ms": 1000,
    }
    recognition = {
        "image_plate_orientation": "rot180",
        "auto_rectify_tilt": True,
        "rectify_min_angle_deg": 0.5,
        "min_row_score": 5.0,
        "image_plate_rotation_deg": None,
    }
    camera.update(camera_defaults or {})
    recognition.update(recognition_defaults or {})
    empty_slot = {"source": "none", "url": "", "quality_url": "", "filename": ""}
    return {
        "revision": 0,
        "updated_at": "",
        "before": dict(empty_slot),
        "after": dict(empty_slot),
        "camera_params": camera,
        "recognition_params": recognition,
        "capture_quality": {"before": None, "after": None},
        "uv_timing": None,
        "analysis": None,
        "source_context": None,
        "error": None,
    }


class VisionDebugService:
    """固定工作区视觉调试服务，所有写操作由单一 asyncio.Lock 串行化."""

    def __init__(
        self,
        workspace_dir: Path,
        camera_service: Any,
        vision_service: Any,
        *,
        camera_defaults: dict[str, Any] | None = None,
        recognition_defaults: dict[str, Any] | None = None,
    ) -> None:
        self._workspace = Path(workspace_dir)
        self._camera = camera_service
        self._vision = vision_service
        self._camera_defaults = dict(camera_defaults or {})
        self._recognition_defaults = dict(recognition_defaults or {})
        self._lock = asyncio.Lock()
        self._state: dict[str, Any] | None = None

    @property
    def state(self) -> dict[str, Any]:
        """返回不可影响内部状态的快照."""
        return copy.deepcopy(self._state_ref())

    def _state_ref(self) -> dict[str, Any]:
        if self._state is None:
            self._state = self._load_state()
        return self._state

    def _load_state(self) -> dict[str, Any]:
        initial = _initial_state(self._camera_defaults, self._recognition_defaults)
        path = self._workspace / "state.json"
        if not path.is_file():
            return initial
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            log.warning("[VisionDebug] state.json 无法读取，使用初始状态: %s", exc)
            return initial
        if not isinstance(data, dict):
            return initial
        merged = {**initial, **data}
        for key in ("before", "after", "camera_params", "recognition_params", "capture_quality"):
            if isinstance(data.get(key), dict):
                merged[key] = {**initial[key], **data[key]}
        return merged

    def _save_state(self, state: dict[str, Any]) -> None:
        state["revision"] = int(state.get("revision", 0)) + 1
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._workspace.mkdir(parents=True, exist_ok=True)
        path = self._workspace / "state.json"
        temp = self._workspace / "state.json.tmp"
        temp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(temp, path)

    def _persist_error(
        self,
        state: dict[str, Any],
        message: str,
        *,
        status_code: int,
    ) -> None:
        state["error"] = message
        self._save_state(state)
        raise VisionDebugError(message, status_code=status_code)

    def _clear_result_files(self) -> None:
        for name in (
            "result/summary.json", "result/score.png", "result/annotated.png",
            "result/cnc_preview.png",
        ):
            path = self._workspace / name
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("[VisionDebug] 清理旧结果失败 %s: %s", path, exc)

    def _invalidate_analysis(self, state: dict[str, Any]) -> None:
        state["analysis"] = None
        self._clear_result_files()

    def _update_quality(self, state: dict[str, Any], role: str, image_path: Path) -> None:
        from eit_ptlc.controller.vision_quality import analyze_quality, generate_quality_overlay

        metrics = analyze_quality(image_path)
        overlay = self._workspace / f"{role}_quality.png"
        generate_quality_overlay(image_path, metrics, overlay)
        state["capture_quality"][role] = _jsonable(metrics)
        state[role]["quality_url"] = f"/api/vision/debug/file/{role}_quality.png"

    async def capture(self, role: str, params: dict[str, Any]) -> dict[str, Any]:
        if role not in ("before", "after"):
            raise VisionDebugError("role 必须为 before 或 after", status_code=422)
        async with self._lock:
            state = self._state_ref()
            state["error"] = None
            state["source_context"] = None
            camera_params = dict(state["camera_params"])
            camera_params.update({k: params[k] for k in _CAMERA_KEYS if k in params})

            exposure_us = int(camera_params["exposure_time_us"])
            gain = float(camera_params["gain"])
            uv_on_ms = int(camera_params["uv_on_time_ms"])
            if exposure_us <= 0 or uv_on_ms <= 0 or gain < 0:
                self._persist_error(state, "相机参数必须为正数，增益不得为负", status_code=422)
            if exposure_us / 1000 > uv_on_ms:
                self._persist_error(state, "曝光时间不能大于 UV 总点亮时间", status_code=422)

            filename = f"{role}.jpg"
            try:
                image_path, timing = await self._camera.capture_with_timing(
                    sample_id="vision-debug",
                    save_dir=self._workspace,
                    filename=filename,
                    overrides={
                        "exposure_time": exposure_us,
                        "gain": gain,
                        "uv_on_time_ms": uv_on_ms,
                    },
                )
            except asyncio.CancelledError:
                state["error"] = f"拍照已取消 ({role})"
                self._save_state(state)
                raise
            except Exception as exc:
                log.error("[VisionDebug] 拍照失败 (%s): %s", role, exc)
                self._persist_error(state, f"拍照失败 ({role}): {exc}", status_code=502)

            image_path = Path(image_path)
            if not image_path.is_file():
                self._persist_error(state, f"拍照失败 ({role}): 未生成图像", status_code=502)
            destination = self._workspace / filename
            if image_path.resolve() != destination.resolve():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(image_path, destination)

            self._invalidate_analysis(state)
            state["camera_params"] = camera_params
            state[role] = {
                "source": "capture",
                "url": f"/api/vision/debug/file/{filename}",
                "quality_url": "",
                "filename": filename,
            }
            size = _image_size(destination)
            if size:
                state[role]["image_width"], state[role]["image_height"] = size
            normalized_timing = dict(timing or {})
            normalized_timing.setdefault("requested_uv_on_ms", uv_on_ms)
            normalized_timing.setdefault("actual_uv_on_ms", 0.0)
            normalized_timing.setdefault("line1_close_ok", True)
            normalized_timing.setdefault("over_limit", False)
            normalized_timing["role"] = role
            if not timing:
                normalized_timing["simulated"] = True
            state["uv_timing"] = normalized_timing
            try:
                self._update_quality(state, role, destination)
            except Exception as exc:
                log.warning("[VisionDebug] 拍照质量分析失败 (%s): %s", role, exc)
                state["capture_quality"][role] = None
            self._save_state(state)
            return copy.deepcopy(state)

    async def upload(
        self,
        role: str,
        file_bytes: bytes,
        filename: str,
        *,
        source: str = "upload",
    ) -> dict[str, Any]:
        if role not in ("before", "after"):
            raise VisionDebugError("role 必须为 before 或 after", status_code=422)
        async with self._lock:
            state = self._state_ref()
            state["error"] = None
            if not str(source).startswith("case:"):
                state["source_context"] = None
            try:
                import io

                from PIL import Image, ImageOps

                with Image.open(io.BytesIO(file_bytes)) as opened:
                    image = ImageOps.exif_transpose(opened)
                    image.load()
                    if image.width <= 0 or image.height <= 0:
                        raise ValueError("图片尺寸无效")
                    if image.width * image.height > 100_000_000:
                        raise ValueError("图片像素数过大")
                    rgb = image.convert("RGB")
                    destination = self._workspace / f"{role}.jpg"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    rgb.save(destination, "JPEG", quality=95)
            except Exception as exc:
                self._persist_error(state, f"无效图片 ({role}): {exc}", status_code=422)

            self._invalidate_analysis(state)
            state[role] = {
                "source": source,
                "url": f"/api/vision/debug/file/{role}.jpg",
                "quality_url": "",
                "filename": filename,
            }
            size = _image_size(destination)
            if size:
                state[role]["image_width"], state[role]["image_height"] = size
            try:
                self._update_quality(state, role, destination)
            except Exception as exc:
                log.warning("[VisionDebug] 上传图片质量分析失败 (%s): %s", role, exc)
                state["capture_quality"][role] = None
            self._save_state(state)
            return copy.deepcopy(state)

    async def analyze(self, params: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            state = self._state_ref()
            state["error"] = None
            before_path = self._workspace / "before.jpg"
            after_path = self._workspace / "after.jpg"
            if not before_path.is_file() or not after_path.is_file():
                self._persist_error(
                    state,
                    "缺少 before.jpg 或 after.jpg，请先拍照或上传",
                    status_code=409,
                )

            recognition = dict(state["recognition_params"])
            recognition.update({k: params[k] for k in _RECOGNITION_KEYS if k in params})
            state["recognition_params"] = recognition
            self._clear_result_files()

            try:
                if hasattr(self._vision, "with_overrides"):
                    analyzer = self._vision.with_overrides(
                        output_dir=self._workspace,
                        overrides=recognition,
                    )
                else:
                    analyzer = self._vision
                result = await analyzer.analyze_full(
                    sample_id="debug",
                    before_path=before_path,
                    after_path=after_path,
                )
            except Exception as exc:
                log.error("[VisionDebug] 分析失败: %s", exc, exc_info=True)
                state["analysis"] = None
                self._persist_error(state, f"视觉分析失败: {exc}", status_code=422)

            non_origin_bands = [band for band in result.bands if not band.is_origin]
            if not result.ok or not non_origin_bands:
                state["analysis"] = {
                    "ok": False,
                    "summary": _jsonable(result.summary),
                    "bands": [],
                    "urls": {},
                }
                self._persist_error(state, "视觉分析未检测到有效非原点条带", status_code=422)

            result_dir = self._workspace / "result"
            result_dir.mkdir(parents=True, exist_ok=True)
            analysis: dict[str, Any] = {
                "ok": True,
                "summary": _jsonable(result.summary),
                "bands": [_band_to_dict(band) for band in result.bands],
                "urls": {},
            }
            if result.annotated_image_path and Path(result.annotated_image_path).is_file():
                shutil.copy2(result.annotated_image_path, result_dir / "annotated.png")
                analysis["urls"]["annotated"] = (
                    "/api/vision/debug/file/result/annotated.png"
                )

            case_dir = Path(result.case_dir)
            score_candidates = (
                case_dir / "score.png",
                case_dir / "debug" / "score.png",
                case_dir / "debug_score.png",
            )
            score_source = next((path for path in score_candidates if path.is_file()), None)
            if score_source is not None:
                shutil.copy2(score_source, result_dir / "score.png")
                analysis["urls"]["score"] = "/api/vision/debug/file/result/score.png"
            summary_source = case_dir / "summary.json"
            if summary_source.is_file():
                shutil.copy2(summary_source, result_dir / "summary.json")
                analysis["urls"]["summary"] = "/api/vision/debug/file/result/summary.json"
                analysis["summary_path"] = str(summary_source)

            try:
                from eit_ptlc.controller.vision_quality import (
                    analyze_quality,
                    generate_quality_report,
                )

                before_metrics = analyze_quality(before_path)
                after_metrics = analyze_quality(after_path)
                state["capture_quality"]["before"] = _jsonable(before_metrics)
                state["capture_quality"]["after"] = _jsonable(after_metrics)
                self._update_quality(state, "before", before_path)
                self._update_quality(state, "after", after_path)
                analysis["urls"]["before_quality"] = state["before"]["quality_url"]
                analysis["urls"]["after_quality"] = state["after"]["quality_url"]
                analysis["quality_report"] = generate_quality_report(
                    before_metrics, after_metrics,
                )
            except Exception as exc:
                log.warning("[VisionDebug] 分析后质量诊断失败: %s", exc)

            state["analysis"] = analysis
            self._save_state(state)
            return copy.deepcopy(state)

    async def set_source_context(self, context: dict[str, Any] | None) -> dict[str, Any]:
        """Bind production-case provenance after both images were loaded successfully."""
        async with self._lock:
            state = self._state_ref()
            state["source_context"] = copy.deepcopy(context) if context else None
            self._save_state(state)
            return copy.deepcopy(state)

    async def generate_cnc_preview(
        self, band_id: str, gcode_cfg: Any,
    ) -> dict[str, Any]:
        """Render a debug-only CNC preview with the production path generator."""
        async with self._lock:
            state = self._state_ref()
            analysis = state.get("analysis") or {}
            summary_path = Path(str(analysis.get("summary_path") or ""))
            if not summary_path.is_file():
                self._persist_error(state, "当前分析没有可用 summary.json", status_code=409)

            loop = asyncio.get_running_loop()

            def _build() -> dict[str, Any]:
                from eit_ptlc.controller.cnc_path import generate_scrape_arrays
                from eit_ptlc.controller.cnc_preview import (
                    default_backdrop,
                    preview_payload_from_arrays,
                    render_cnc_overlay,
                )

                arrays = generate_scrape_arrays(summary_path, band_id, gcode_cfg)
                preview = preview_payload_from_arrays(summary_path, band_id, arrays, gcode_cfg)
                backdrop = default_backdrop(summary_path)
                if backdrop is None:
                    raise FileNotFoundError("分析 case 缺少 after_normalized.jpg/after.jpg")
                output = self._workspace / "result" / "cnc_preview.png"
                if not render_cnc_overlay(backdrop, preview, output):
                    raise RuntimeError("CNC 预览图渲染失败")
                return {
                    key: value for key, value in preview.items()
                    if key not in ("scrape_px", "collect_px", "contour_px")
                }

            try:
                metadata = await loop.run_in_executor(None, _build)
            except (FileNotFoundError, KeyError, ValueError) as exc:
                self._persist_error(state, f"CNC 预览失败: {exc}", status_code=422)
            except Exception as exc:
                log.error("[VisionDebug] CNC 预览失败: %s", exc, exc_info=True)
                self._persist_error(state, f"CNC 预览失败: {exc}", status_code=500)

            analysis.setdefault("urls", {})["cnc_preview"] = (
                "/api/vision/debug/file/result/cnc_preview.png"
            )
            analysis["cnc_preview"] = metadata
            state["analysis"] = analysis
            state["error"] = None
            self._save_state(state)
            return copy.deepcopy(state)

    def get_file_path(self, filename: str) -> Path | None:
        if filename not in _FILE_WHITELIST:
            return None
        resolved = (self._workspace / filename).resolve()
        workspace = self._workspace.resolve()
        try:
            resolved.relative_to(workspace)
        except ValueError:
            return None
        return resolved


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _band_to_dict(band: Any) -> dict[str, Any]:
    names = (
        "band_id",
        "is_origin",
        "centroid_cm",
        "bbox_cm",
        "vertical_width_cm",
        "horizontal_span_cm",
        "distance_to_origin_cm",
        "normalized_develop_height",
        "area_cm2",
    )
    return {
        name: _jsonable(getattr(band, name))
        for name in names
        if hasattr(band, name)
    }
