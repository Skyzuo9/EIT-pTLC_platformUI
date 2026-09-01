"""三维模型资产与 authoring API 路由."""

from __future__ import annotations

import json
import logging
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from eit_ptlc.api.vision_routes import _vision_output_dir
from eit_ptlc.controller.plate_coords import px_to_cm_affine
from eit_ptlc.runtime.three_d_authoring import (
    ThreeDAuthoringService,
    ThreeDRebuildBusy,
    ThreeDWorkspaceUnavailable,
)

log = logging.getLogger(__name__)

#: 样品号的安全字符集(直接拼进文件路径, 必须白名单式过滤 —— 防目录穿越)。
_SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


def _collect_plate_traces(case_dir) -> dict:
    """汇总一个视觉 case 目录的板面痕迹(板 cm 帧)。

    数据源(全是既有产物, 见 controller/cnc_preview.py 的落盘契约):
      · preview_payload.json —— 真机将跑/已跑的 400 点刀路(px 帧)+ 板参照
        (plate_bbox_px/plate_size_cm), 经 plate_coords.px_to_cm_affine 反算 cm;
      · summary.json —— 检出谱带索引(bands[].path_json 指向逐带几何)与溶剂前沿;
      · band_XX_path.json —— 各谱带的 scrape_path.bbox_cm(板 cm 帧, 直接可用)。
    """
    payload_path = case_dir / "preview_payload.json"
    summary_path = case_dir / "summary.json"
    out: dict = {"found": False}

    plate_size_cm = 20.0
    if payload_path.is_file():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        plate_size_cm = float(payload.get("plate_size_cm") or 20.0)
        bbox = payload.get("plate_bbox_px")
        scrape_px = payload.get("scrape_px") or []
        if bbox and len(scrape_px) >= 2:
            points_cm = px_to_cm_affine(
                [(float(p[0]), float(p[1])) for p in scrape_px], bbox, plate_size_cm)
            out["scrapePolylineCm"] = [[round(x, 4), round(y, 4)] for x, y in points_cm]
            width_px = float(payload.get("cutter_width_px") or 0.0)
            bbox_w = float(bbox["w"] if isinstance(bbox, dict) else bbox[2])
            if width_px > 0 and bbox_w > 0:
                out["cutterWidthCm"] = round(width_px / bbox_w * plate_size_cm, 4)
            out["passCount"] = int(payload.get("pass_count") or 0)
            out["found"] = True

    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        bands_cm: list[list[float]] = []
        for band in summary.get("bands") or []:
            rel = str(band.get("path_json") or "")
            if not rel:
                continue
            # path_json 是相对仓根的历史格式(vision_output\<sid>\...), 只取文件名部分,
            # 锚回本 case 目录 —— 防止旧记录里的绝对/相对路径把读取带出目录。
            path = case_dir / "task1_task2_contours_paths" / rel.replace("\\", "/").split("/")[-1]
            if not path.is_file():
                continue
            geometry = json.loads(path.read_text(encoding="utf-8"))
            box = (geometry.get("scrape_path") or {}).get("bbox_cm") or {}
            keys = ("x_min", "y_min", "x_max", "y_max")
            if all(isinstance(box.get(key), (int, float)) for key in keys):
                bands_cm.append([round(float(box[key]), 4) for key in keys])
        if bands_cm:
            out["bandsCm"] = bands_cm
            out["found"] = True
        front = (summary.get("solvent_front") or {}).get("y_cm")
        if isinstance(front, (int, float)):
            out["solventFrontYCm"] = round(float(front), 4)

    if out["found"]:
        out["plateSizeCm"] = [plate_size_cm, plate_size_cm]
    return out


def register_three_d_routes(app: FastAPI) -> None:
    """
    功能:
        注册三维资产读取, 受管文件读写和模型重建端点.

    参数:
        app: FastAPI 应用实例.

    返回:
        无.
    """

    def _service(request: Request) -> ThreeDAuthoringService:
        service = getattr(request.app.state, "three_d_authoring", None)
        if service is None:
            raise HTTPException(503, "三维工程服务未就绪")
        return service

    def _require_debug(request: Request) -> None:
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(403, "三维工程写回与重建仅允许在 DEBUG 模式执行")

    @app.get("/api/3d/assets/{asset_path:path}", include_in_schema=False)
    async def get_three_d_asset(request: Request, asset_path: str):
        try:
            target = _service(request).resolve_asset(asset_path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ThreeDWorkspaceUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        # no-store 堵一个真实发生过的缓存投毒窗口: 管线先写 manifest 后写 GLB, 前端拿
        # manifest.generatedAt 当 ?v= 戳 —— 落在两次写之间的页面加载会把**旧 GLB 字节**
        # 缓存到**新戳**之下, 而本路由此前不带 Cache-Control, 浏览器按启发式新鲜度
        # (文件年龄的 ~10%)能把它留存几分钟到几小时。资产都在本机/内网, no-store 的
        # 重复传输代价可忽略。(照抄 vision_debug_routes 的同款处置)
        return FileResponse(target, headers={"Cache-Control": "no-store"})

    # ── 板面痕迹取数(实时页四态板的只读数据面) ──────────────────────────────
    # 注册顺序要紧: "config" 必须先于 "{sample_id}", 否则会被后者当样品号吞掉。

    @app.get("/api/3d/plate-traces/config")
    async def get_plate_trace_config(request: Request):
        """点样扫线的示教毫米(spot_pose 组合点位配置值) —— 前端与 motion-map 的
        spotBandCalib 过同一条仿射即得标称色带。只读, 不碰 OPC。"""
        points = getattr(request.app.state, "points", None)
        if points is None:
            raise HTTPException(503, "点位服务未就绪")
        comp = points.composite_entry("spot_pose")
        if comp is None:
            raise HTTPException(404, "点表缺 spot_pose 组合点位")
        values = {m.key: m.value for m in comp.members}
        missing = [key for key in ("x_start", "x_end", "y_height") if values.get(key) is None]
        if missing:
            raise HTTPException(404, f"spot_pose 缺成员: {missing}")
        return {"spotPose": {key: float(values[key]) for key in ("x_start", "x_end", "y_height")}}

    @app.get("/api/3d/plate-traces/{sample_id}")
    async def get_plate_traces(request: Request, sample_id: str):
        """某样品的板面痕迹真源(视觉 case 目录, 板 cm 帧): 实际刮取刀路 + 检出谱带.

        全部数据都是**磁盘上已有的运行产物**(vision_output/{sample_id}/), 本路由只做
        px→cm 换算(controller/plate_coords 单一真源)与汇总, 不触发任何计算或设备动作。
        没有产物(未拍照/跳过/历史清理)返回 {found: false} —— 痕迹是装饰性数据,
        缺失不该是错误。
        """
        if not _SAMPLE_ID_RE.match(sample_id):
            raise HTTPException(400, "非法样品号")
        base = _vision_output_dir(request)
        case_dir = (base / sample_id).resolve()
        if not case_dir.is_relative_to(base) or not case_dir.is_dir():
            return {"found": False}
        try:
            return _collect_plate_traces(case_dir)
        except Exception:  # noqa: BLE001 痕迹缺失/损坏不该 500 —— 如实说没有, 细节进日志
            log.warning("[3d] 汇总板面痕迹失败: %s", case_dir, exc_info=True)
            return {"found": False}

    @app.get("/api/3d/authoring/status")
    async def get_three_d_authoring_status(request: Request):
        service = _service(request)
        return {
            "ok": True,
            **service.workspace_status(),
            "authoring_allowed": request.app.state.control_mode == "DEBUG",
            "rebuild": service.status(),
        }

    @app.post("/api/3d/authoring/read")
    async def read_three_d_file(request: Request, body: dict):
        try:
            return _service(request).read_file(key=body.get("key"), clip=body.get("clip"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ThreeDWorkspaceUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/3d/authoring/write")
    async def write_three_d_file(request: Request, body: dict):
        _require_debug(request)
        try:
            return _service(request).write_file(
                key=body.get("key"),
                clip=body.get("clip"),
                content=body.get("content"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ThreeDWorkspaceUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"写入三维工程文件失败: {exc}") from exc

    @app.get("/api/3d/authoring/clips")
    async def list_three_d_clips(request: Request):
        try:
            return {"ok": True, "clips": _service(request).list_clips()}
        except ThreeDWorkspaceUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/3d/authoring/rebuild", status_code=202)
    async def start_three_d_rebuild(request: Request, body: dict):
        _require_debug(request)
        only = body.get("only", [])
        if isinstance(only, list) is False:
            raise HTTPException(400, "only 必须是步骤名列表")
        # flow 是可选的"定向编一条流程": {"operation": 名, "inputs": {入参: 值}}。
        # 语义与 only 正交 —— only 说跑哪几个**管线步骤**, flow 说 flows 那一步只编哪条
        # 流程、用什么入参。演示页"按这组入参编这一条"走它, 约 20 秒而不是 10 分钟。
        flow = body.get("flow")
        if flow is not None and isinstance(flow, dict) is False:
            raise HTTPException(400, "flow 必须是 {operation, inputs} 映射")
        try:
            status = await _service(request).start_rebuild(only, flow=flow)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ThreeDRebuildBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except ThreeDWorkspaceUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"ok": True, **status}

    @app.get("/api/3d/authoring/rebuild/status")
    async def get_three_d_rebuild_status(request: Request):
        return {"ok": True, **_service(request).status()}
