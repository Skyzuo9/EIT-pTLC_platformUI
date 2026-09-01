"""拍照刮板 — 手绘路径来源 REST 端点
====================================
功能:
    视觉失败/显式手绘的兜底路径来源。前端在板照片上画闭合区域, 经这些端点:
      - preview_path  实时把手绘区域 → 真机将跑的刮取路径(像素), 供画布叠加预览(所见即所跑)
      - sketch_commit 提交手绘 → 落最小 summary.json(供**未改动的** cnc_path 动作) + 叠加图,
                      返回 summary_path 字符串由人工回复带回 VM, 与视觉候选完全同形
      - sketch_context 读(视觉)summary 的 plate_bbox_px/plate_size_cm; 缺板参照 → 前端走 4 角手动标板

    坐标标定与工艺参数运行期实时读 config(gcode 段), 与 cnc_path 动作同源。

端点:
    POST /api/photoscrape/preview_path   {polygon_px, plate_bbox_px?|plate_corners_px?, plate_size_cm?, strategy?}
    POST /api/photoscrape/sketch_commit  {polygon_px, summary_path?|plate_bbox_px?|plate_corners_px?, backdrop_ref?, plate_size_cm?, sample_id?, strategy?}
    GET  /api/photoscrape/sketch_context ?summary_path=...
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.api.vision_routes import _vision_output_dir
from eit_ptlc.controller import plate_coords
from eit_ptlc.controller import sketch_path as sp
from eit_ptlc.controller.align_check import build_align_readout

log = logging.getLogger(__name__)


def _gcode_cfg(request: Request):
    """运行期实时解析 gcode 段为 GCodeCfg(与 cnc_path 动作 / bootstrap 同源)。"""
    from eit_ptlc.config.loader import _parse_gcode
    cfg_svc = getattr(request.app.state, "config_svc", None)
    if cfg_svc is None:
        raise HTTPException(503, "配置服务未就绪")
    try:
        return _parse_gcode(cfg_svc.read_section("gcode"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"解析 gcode 配置失败: {exc}") from exc


def _plate_ref(body: dict) -> tuple[object | None, list | None]:
    """从请求体取板参照: plate_bbox_px(轴对齐) 或 plate_corners_px(4 角透视)。"""
    return body.get("plate_bbox_px"), body.get("plate_corners_px")


def _require_polygon(body: dict) -> list:
    poly = body.get("polygon_px")
    if not isinstance(poly, list) or len(poly) < 3:
        raise HTTPException(422, "polygon_px 需为至少 3 个 [x,y] 点的列表")
    # #12: 每点须是二元数对; 否则 _clean_closed 取 p[0]/p[1] 抛 TypeError → 逃过 except ValueError → HTTP 500。
    for p in poly:
        if not (isinstance(p, (list, tuple)) and len(p) == 2
                and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in p)):
            raise HTTPException(422, f"polygon_px 每点须为 [x,y] 二元数对, 得到 {p!r}")
    return poly


def register_photoscrape_routes(app: FastAPI) -> None:
    """注册手绘路径来源端点。"""

    @app.post("/api/photoscrape/preview_path")
    async def preview_path(request: Request):
        body = await request.json()
        polygon = _require_polygon(body)
        plate_bbox_px, plate_corners_px = _plate_ref(body)
        if plate_bbox_px is None and plate_corners_px is None:
            raise HTTPException(422, "缺少 plate_bbox_px 或 plate_corners_px(4 角)")
        try:
            return sp.preview_from_polygon(
                polygon, _gcode_cfg(request),
                plate_size_cm=float(body.get("plate_size_cm", 20.0) or 20.0),
                plate_bbox_px=plate_bbox_px, plate_corners_px=plate_corners_px,
                strategy=body.get("strategy"),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/photoscrape/sketch_commit")
    async def sketch_commit(request: Request):
        body = await request.json()
        polygon = _require_polygon(body)
        plate_bbox_px, plate_corners_px = _plate_ref(body)
        plate_size_cm = float(body.get("plate_size_cm", 20.0) or 20.0)

        # 板参照缺省时, 从源(视觉)summary 读 plate_bbox_px/plate_size_cm
        source_summary = body.get("summary_path")
        if plate_bbox_px is None and plate_corners_px is None and source_summary:
            plate_bbox_px, plate_size_cm = sp.read_plate_bbox(source_summary)
        if plate_bbox_px is None and plate_corners_px is None:
            raise HTTPException(422, "无 plate_bbox_px / plate_corners_px, 也无法从 summary 读到板参照")

        output_dir = _vision_output_dir(request)
        after_path = _resolve_backdrop(body, source_summary, output_dir)
        try:
            return sp.commit_sketch(
                polygon, _gcode_cfg(request), output_dir,
                plate_size_cm=plate_size_cm,
                plate_bbox_px=plate_bbox_px, plate_corners_px=plate_corners_px,
                after_path=after_path,
                # #7: 去路径分隔符 (.name), 防 sample_id 构造 ../../.. 越 output_dir 任意写文件 (写侧收口, 与读侧防穿越一致)。
                sample_id=Path(str(body.get("sample_id") or "manual")).name or "manual",
                strategy=body.get("strategy"),
                # C-1: 透传源(视觉)summary, 让手绘 summary 继承 normalize_applied 归一化参数。
                source_summary_path=source_summary,
                # C-2: 透传 4 角矫正记录, 随手绘 summary 落盘供刮后二级回放到手动矫正帧。
                manual_rectify=body.get("manual_rectify"),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/photoscrape/sketch_context")
    async def sketch_context(request: Request, summary_path: str = ""):
        if not summary_path:
            raise HTTPException(422, "缺少 summary_path")
        plate_bbox_px, plate_size_cm = sp.read_plate_bbox(summary_path)
        # 板坐标系标注几何(原点/轴/角标签, 只核标角): 无板参照时 None, 前端不画。
        # 退化 bbox(w/h≤0)或非正 plate_size → plate_axes_annotation 抛 ValueError;
        # 吞成 None(标注建不出来不是服务错误), has_plate_ref 等其余键语义不变, 前端只是不画轴。
        plate_axes = None
        if plate_bbox_px is not None:
            try:
                plate_axes = plate_coords.plate_axes_annotation(plate_bbox_px, plate_size_cm)
            except ValueError:
                plate_axes = None
        return {
            "plate_bbox_px": plate_bbox_px,
            "plate_size_cm": plate_size_cm,
            "has_plate_ref": plate_bbox_px is not None,
            "plate_axes": plate_axes,
        }

    @app.get("/api/photoscrape/axes")
    async def read_axes(request: Request):
        """刮板三轴 ActPos 只读回显 (UI 轮询; 读不算写者, 单写者纪律不破)。"""
        plc = getattr(request.app.state, "plc", None)
        if plc is None:
            raise HTTPException(503, "PLC 控制器未就绪")
        try:
            x, y, z = await plc.read_scrape_axes()
        except Exception as exc:  # noqa: BLE001 — 节点未下装(KeyError)/通讯异常统一 503
            raise HTTPException(503, f"读取刮板轴位置失败: {exc}") from exc
        return {"x_mm": x, "y_mm": y, "z_mm": z}

    @app.get("/api/photoscrape/align_readout")
    async def align_readout(request: Request):
        """对位回显: 三轴实读 + gcode 标定 → Δ/检查高度/建议值 (结构化, 供对刀面板轮询)。

        与 photoscrape.align_readout 动作同一产地 (build_align_readout), 面板不得自行
        重算 Δ/建议值 — 公式单点留在 controller/align_check.py。
        """
        plc = getattr(request.app.state, "plc", None)
        if plc is None:
            raise HTTPException(503, "PLC 控制器未就绪")
        try:
            axes = await plc.read_scrape_axes()
        except Exception as exc:  # noqa: BLE001 — 节点未下装(KeyError)/通讯异常统一 503
            raise HTTPException(503, f"读取刮板轴位置失败: {exc}") from exc
        return build_align_readout(axes, _gcode_cfg(request))

    @app.post("/api/photoscrape/calib_pattern")
    async def calib_pattern(request: Request):
        """构造第 N 轮标定工作区, 返回可直接交给 cnc_path 的 summary_path。

        图案几何/工作区命名/差分基准帧的选择全在 controller.scrape_calib 单点决定,
        调用方只给 sample_id + round。
        失败语义: 404 前置帧缺失 | 422 轮次越界或视觉 case 不满足建帧条件。
        """
        body = await request.json()
        sample_id = str(body.get("sample_id") or "").strip()
        if not sample_id:
            raise HTTPException(422, "缺少 sample_id")
        # 与其余端点同一立场: sample_id 客户端可控, 去路径分隔符防越出视觉输出目录
        sample_id = Path(sample_id).name
        try:
            round_no = int(body.get("round") or 1)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "round 须为整数") from exc

        from eit_ptlc.controller.scrape_calib import build_round_workspace
        try:
            res = build_round_workspace(_vision_output_dir(request), sample_id, round_no)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # 刮前基准帧 URL: 面板展示"这一轮是拿哪张底图做差分的", 让拍照过程可见
        rel = res.pop("base_frame_rel", "")
        res["base_frame_url"] = f"/api/vision/image/{rel}" if rel else ""
        return res

    @app.post("/api/photoscrape/scrape_offset")
    async def scrape_offset(request: Request):
        """测「指令 vs 实刮」位置误差 → Δ + 建议 plate_origin + 可信度判据。

        只读磁盘上已落的归一化帧与 preview_payload, 不触发任何运动/拍照。
        失败语义: 404 前置缺失(帧契约未成立) | 422 几何不可比 | 503 cv2 缺失。
        """
        body = await request.json()
        summary_path = body.get("summary_path")
        if not summary_path:
            raise HTTPException(422, "缺少 summary_path")
        output_dir = _vision_output_dir(request)
        # 与 sketch_rectify 同一立场: summary_path 客户端可控, 读盘前先收口到视觉输出目录内
        if not Path(summary_path).resolve().is_relative_to(output_dir.resolve()):
            raise HTTPException(422, "summary_path 不在视觉输出目录内")
        try:
            from eit_ptlc.controller.scrape_offset import measure_scrape_offset
        except ImportError as exc:
            raise HTTPException(503, f"测量模块不可用: {exc}") from exc

        margin = float(body.get("search_margin_cm") or 2.0)
        try:
            result = measure_scrape_offset(summary_path, _gcode_cfg(request),
                                           search_margin_cm=margin)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ImportError as exc:   # cv2 缺失
            raise HTTPException(503, f"缺少 opencv, 无法做刮痕测量: {exc}") from exc

        name = result.pop("annotated_name", "")
        result["annotated_url"] = ""
        if name:
            try:
                rel = (Path(result["case_dir"]) / name).resolve().relative_to(
                    output_dir.resolve()).as_posix()
                result["annotated_url"] = f"/api/vision/image/{rel}"
            except ValueError:
                result["annotated_url"] = ""
        return result

    @app.post("/api/photoscrape/sketch_rectify")
    async def sketch_rectify(request: Request):
        """4 角标板 → 透视矫正帧(主路径): 落 case_dir/manual_normalized.jpg, 返回全幅
        plate_bbox_px + manual_rectify(C-2, 提交时随 manual summary 落盘供刮后回放)。
        失败语义: 422 点序/参数 | 404 底图缺失 | 503 cv2 缺失 → 前端回落 4 角单应老路。"""
        body = await request.json()
        summary_path = body.get("summary_path")
        if not summary_path:
            raise HTTPException(422, "缺少 summary_path")
        # 防越界写盘(与 _resolve_backdrop / sample_id .name 消毒同一立场): summary_path 客户端可控,
        # 矫正帧落其 case 目录 — **写盘前**校验在 output_dir 之内, 拦住越界写而不只拦 URL。
        output_dir = _vision_output_dir(request)
        if not Path(summary_path).resolve().is_relative_to(output_dir.resolve()):
            raise HTTPException(422, "summary_path 不在视觉输出目录内")
        plate_size_cm = float(body.get("plate_size_cm") or sp.read_plate_bbox(summary_path)[1] or 20.0)
        case_dir = Path(summary_path).parent
        backdrop = None
        for name in ("after_normalized.jpg", "after.jpg"):   # 干净底图, 不用带叠加的门图
            cand = case_dir / name
            if cand.is_file():
                backdrop = cand
                break
        if backdrop is None:
            raise HTTPException(404, "case 目录缺少 after_normalized.jpg/after.jpg, 无法生成矫正帧")
        try:
            res = sp.rectify_manual_frame(backdrop, body.get("corners_px"), plate_size_cm, case_dir)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            # 写前已校验包含性, 此兜底理论上不再触发(双保险)。
            rel = Path(res["image_path"]).resolve().relative_to(output_dir.resolve()).as_posix()
        except ValueError as exc:
            raise HTTPException(500, "矫正图不在视觉服务目录内, 无法提供 URL") from exc
        res["image_url"] = f"/api/vision/image/{rel}"
        res["plate_axes"] = plate_coords.plate_axes_annotation(res["plate_bbox_px"], plate_size_cm)
        return res

    @app.post("/api/photoscrape/reanalyze")
    async def reanalyze(request: Request):
        """门内"重新识别(调参)": 用调整后的识别参数在**本 run 的 before/after** 上重跑分析,
        返回与 photoscrape.analyze 同形的结果 (含 bands 供面板)。VM 停在门, 前端可反复调用迭代;
        满意后人工回复带回 summary_path/band_id (交未改动的 cnc_path), 与手绘门完全同形。

        before/after 从 summary 同目录的 inputs.json 取 (analyze 落), 故前端只需带 summary_path。
        重跑走 photoscrape.analyze **动作** (经 executor), 与 VM 同一条 live-read+覆盖路径, 结果一致。
        """
        body = await request.json()
        summary_path = body.get("summary_path")
        if not summary_path:
            raise HTTPException(422, "缺少 summary_path")
        inputs_file = Path(summary_path).parent / "inputs.json"
        if not inputs_file.is_file():
            raise HTTPException(404, "找不到本次分析的输入清单 (inputs.json); 无法重识别")
        try:
            inputs = json.loads(inputs_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(500, f"读取 inputs.json 失败: {exc}") from exc

        executor = getattr(request.app.state, "executor", None)
        if executor is None:
            raise HTTPException(503, "执行器未就绪")

        params = {
            # #3: reanalyze 写独立 _re 目录 (case_dir=output_dir/sample_id), 不就地覆写原候选磁盘产物;
            # 取消/no_bands 后"所见=所跑"; 采纳(用此结果)后 cand_* 指向 _re, 语义不变。
            "sample_id": str(inputs.get("sample_id") or "reanalyze") + "_re",
            "before_path": str(inputs.get("before_path") or ""),
            "after_path": str(inputs.get("after_path") or ""),
        }
        # 识别覆盖 (可选): 只透传非 None 项; 缺省即用 config.vision 实时基线。
        for key in ("image_plate_orientation", "auto_rectify_tilt",
                    "rectify_min_angle_deg", "min_row_score",
                    "image_plate_rotation_deg"):
            if body.get(key) is not None:
                params[key] = body[key]

        result = await executor.execute(
            "photoscrape.analyze", params, current_mode=request.app.state.control_mode
        )
        if result.status.value != "DONE":
            raise HTTPException(422, f"重识别失败: {result.message}")
        return result.result


def _resolve_backdrop(body: dict, source_summary: str | None, output_dir: Path) -> Path | None:
    """定位叠加图的底图(板照片): backdrop_ref(前端所绘底图, /api/vision/image/<rel>) 优先,
    否则源 summary 同目录的 after.jpg。防目录穿越: 解析后必须仍在 output_dir 下。"""
    ref = body.get("backdrop_ref")
    if ref:
        rel = str(ref).split("/api/vision/image/", 1)[-1]
        cand = (output_dir / rel).resolve()
        if cand.is_relative_to(output_dir.resolve()) and cand.is_file():
            return cand
    if source_summary:
        # 归一化图优先（与 plate_bbox_px 同帧，所见即所跑）；缺失回落原始 after.jpg。
        case_dir = Path(source_summary).parent
        for name in ("after_normalized.jpg", "after.jpg"):
            cand = case_dir / name
            if cand.is_file():
                return cand
    return None
