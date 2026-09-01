"""孔板标定/下发路由
==================
功能:
    注册孔板标定 (jog 采点 → solve → 持久化) 与按孔下发 (写 *_Target) 端点。
    全部从 app.state.calibration (CalibrationService) 读取; 未就绪返回 503。

端点 (前缀 /api/calibration):
    GET  /instances              标定实例列表 (id/label/类型/是否已标定/点数)
    GET  /plate_types            孔板类型列表 (内置 + plates.yaml)
    GET  /actpos                 当前轴对实际位置镜像 (*_ActPos, 实时显示/采点参考)
    GET  /{id}                   实例详情 (含推荐标定孔 + 已存标定点)
    GET  /{id}/targets           该实例全孔目标预览 (需已标定)
    POST /{id}/capture {row,col} 读当前 ActPos 作为该孔标定点 (不持久化, UI 累计 3 点)
    POST /{id}/commit {points}   提交标定 (solve 校验 + 写 calibration.yaml; DEBUG)
    POST /{id}/push {row,col}    算该孔目标并写 *_Target (DEBUG)

采点前把轴挪到孔位, 走的是单点控制 (`/api/manual/axis/{id}/*`, 见 api/manual_routes.py),
本模块不碰伺服。原先那对 `POST /manual/enter|exit`(写 `Sampling_Servo_FreeMove` 去使能
4X/3Y 供手推) 已于 2026-07 删除, 原因见 controller/calibration_service.py 模块 docstring;
它承担的"标定期间挡住 PLC 全下载"由单点会话自己的 ActivityLease 接管
(ManualService.enter → gate.try_enter_activity), 覆盖面更严。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.controller.plate_affine import CalibrationPoint, Well
from eit_ptlc.controller.plate_catalog import PlateCatalogError

log = logging.getLogger(__name__)


def _instance_dto(c) -> dict:
    return {"id": c.id, "label": c.label, "plate_type": c.plate_type,
            "is_calibrated": c.is_calibrated, "point_count": len(c.points)}


def _plate_type_dto(pt) -> dict:
    return {"name": pt.name, "rows": pt.rows, "cols": pt.cols, "row_major": pt.row_major,
            "calib_wells": [[w.row, w.col] for w in pt.calib_wells],
            "nominal_pitch_x_mm": pt.nominal_pitch_x_mm,
            "nominal_pitch_y_mm": pt.nominal_pitch_y_mm}


def _point_dto(p) -> dict:
    return {"well": [p.well.row, p.well.col], "x_mm": p.x_mm, "y_mm": p.y_mm}


def _well_from_body(body: dict) -> Well:
    try:
        return Well(int(body["row"]), int(body["col"]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "请求体需含 row, col (整数)")


def _points_from_body(body: dict) -> list[CalibrationPoint]:
    raw = body.get("points")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "请求体需含非空 points 数组")
    out: list[CalibrationPoint] = []
    for p in raw:
        try:
            w = p["well"]
            out.append(CalibrationPoint(Well(int(w[0]), int(w[1])), float(p["x_mm"]), float(p["y_mm"])))
        except (KeyError, TypeError, ValueError, IndexError):
            raise HTTPException(400, f"标定点格式错误: {p!r} (需 well:[row,col], x_mm, y_mm)")
    return out


def register_calibration_routes(app: FastAPI) -> None:
    """把孔板标定/下发路由注册到应用。"""

    def _calib(request: Request):
        svc = request.app.state.calibration
        if svc is None:
            raise HTTPException(503, "标定服务未就绪")
        return svc

    def _require_instance(svc, instance_id: str):
        try:
            return svc.catalog.instance(instance_id)
        except PlateCatalogError as exc:
            raise HTTPException(404, str(exc))

    # —— 字面量路由 (声明在 /{instance_id} 之前, 避免被参数路由误匹配) ——
    @app.get("/api/calibration/instances")
    async def list_instances(request: Request):
        return [_instance_dto(c) for c in _calib(request).list_instances()]

    @app.get("/api/calibration/plate_types")
    async def list_plate_types(request: Request):
        return [_plate_type_dto(pt) for pt in _calib(request).catalog.plate_types().values()]

    @app.get("/api/calibration/actpos")
    async def read_actpos(request: Request):
        try:
            return await _calib(request).read_actpos()
        except Exception as exc:  # OPC-UA 读失败 (含 sim 无镜像)
            raise HTTPException(502, f"读取 ActPos 失败: {exc}")

    @app.post("/api/calibration/{instance_id}/capture")
    async def capture(request: Request, instance_id: str, body: dict):
        svc = _calib(request)
        _require_instance(svc, instance_id)
        well = _well_from_body(body)
        try:
            return _point_dto(await svc.capture_well(well))
        except Exception as exc:
            raise HTTPException(502, f"采点失败 (读 ActPos): {exc}")

    @app.post("/api/calibration/{instance_id}/commit")
    async def commit(request: Request, instance_id: str, body: dict):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "标定提交仅允许在 DEBUG 模式")
        svc = _calib(request)
        _require_instance(svc, instance_id)
        points = _points_from_body(body)
        try:
            return _instance_dto(svc.commit(instance_id, points))
        except ValueError as exc:  # 含 PlateCatalogError: 不足3点/共线退化/越界
            raise HTTPException(400, str(exc))

    @app.post("/api/calibration/{instance_id}/push")
    async def push(request: Request, instance_id: str, body: dict):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "下发仅允许在 DEBUG 模式")
        svc = _calib(request)
        _require_instance(svc, instance_id)
        well = _well_from_body(body)
        try:
            x, y = await svc.push_well(instance_id, well)
        except ValueError as exc:  # 含 PlateCatalogError: 未标定/越界/退化
            raise HTTPException(400, str(exc))
        except Exception as exc:  # OPC-UA 写失败
            raise HTTPException(502, f"下发失败 (写 Target): {exc}")
        return {"well": [well.row, well.col], "x_mm": x, "y_mm": y}

    @app.get("/api/calibration/{instance_id}/targets")
    async def targets(request: Request, instance_id: str):
        svc = _calib(request)
        _require_instance(svc, instance_id)
        try:
            ts = svc.targets(instance_id)
        except ValueError as exc:  # 含 PlateCatalogError: 未标定/退化
            raise HTTPException(400, str(exc))
        return [{"well": [t.well.row, t.well.col], "label": t.label, "x_mm": t.x_mm, "y_mm": t.y_mm}
                for t in ts]

    @app.get("/api/calibration/{instance_id}")
    async def get_instance(request: Request, instance_id: str):
        svc = _calib(request)
        c = _require_instance(svc, instance_id)
        pt = svc.catalog.plate_types().get(c.plate_type)
        return {**_instance_dto(c),
                "plate": _plate_type_dto(pt) if pt else None,
                "points": [_point_dto(p) for p in c.points]}
