"""点位目录路由
============
功能:
    注册统一点位目录 (机器人 / PLC 伺服 / CNC) 的浏览与原始 yaml 读写端点到 FastAPI 应用。
    全部从 app.state.points (PointsService) 读取; 未就绪返回 503。
    伺服实时读写见 Phase 4 (register 同处扩展)。

端点 (前缀 /api):
    GET /points                    完整点位树 (按 category -> workstation 分组)
    GET /points/raw/files          可浏览/编辑的原始文件列表 (stations.yaml / plc/*.yaml / robot 真源)
    GET /points/raw?kind=          底层原始文件内容 (kind = 文件列表里的相对路径)
    PUT /points/raw?kind= {text}   校验后保存 (失败 400, 绝不写坏文件; robot/* 门禁 DEBUG)
    GET /points/{category}/{id}    单点详情 (category: robot|plc_servo)
"""

from __future__ import annotations

import asyncio
import logging

import yaml
from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.controller.points_service import (
    CATEGORIES,
    ROBOT_META_KIND,
    ROBOT_POINTS_KIND,
    STATIONS_FILE,
    PointsCatalogError,
)

log = logging.getLogger(__name__)

_ROBOT_RAW_KINDS = (ROBOT_POINTS_KIND, ROBOT_META_KIND)


def register_points_routes(app: FastAPI) -> None:
    """把点位目录路由注册到应用。"""

    def _points(request: Request):
        svc = request.app.state.points
        if svc is None:
            raise HTTPException(503, "点位服务未就绪")
        return svc

    @app.get("/api/points")
    async def get_points_tree(request: Request):
        return _points(request).tree()

    # 仿射网格库位布局 (货架示意图); 注册在单点 {category}/{id} 之前 (1 段路径, 不冲突)
    @app.get("/api/points/grids")
    async def list_point_grids(request: Request):
        return {"grids": _points(request).list_grids()}

    # 原始 yaml/json 读写 (注册在单点路由之前, 避免 /points/raw 被 {category}/{id} 误匹配)
    @app.get("/api/points/raw/files")
    async def list_points_raw_files(request: Request):
        return {"files": _points(request).list_raw_files()}

    @app.get("/api/points/raw")
    async def get_points_raw(request: Request, kind: str = STATIONS_FILE):
        try:
            return _points(request).read_raw(kind)
        except (PointsCatalogError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc))

    @app.put("/api/points/raw")
    async def save_points_raw(request: Request, body: dict, kind: str = "catalog"):
        svc = _points(request)
        text = body.get("text")
        if not isinstance(text, str):
            raise HTTPException(400, "请求体缺少 text 字段")
        # robot_* 改机器人点位 (影响实机运动): 仅 DEBUG 模式允许
        if kind in _ROBOT_RAW_KINDS and request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "机器人点位编辑仅允许在 DEBUG 模式")
        try:
            return svc.save_raw(kind, text)
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"YAML 解析失败: {exc}")
        except (PointsCatalogError, ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc))

    # 注: plc_servo (HMI struct 点) 不提供 OPC 实时读写路由 —— B 方案下 HMI position[] 不经 OPC,
    #   上位机对 PLC 位置的示教统一走下方 plc_servo_target 的 flat 流程 (见 points_service 说明)。

    # PC 侧 flat 目标点位 (B 方案单写者): 读 actpos 镜像 / 存 value 回 points.yaml / 下发 *_Target
    @app.get("/api/points/plc_servo_target/{key}/actpos")
    async def get_target_actpos(request: Request, key: str):
        try:
            return {"key": key, "actpos": await _points(request).read_target_actpos(key)}
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))
        except Exception as exc:  # OPC-UA 读失败 (含 sim 无镜像)
            raise HTTPException(502, f"读取目标点位实际位失败: {exc}")

    @app.put("/api/points/plc_servo_target/{key}/value")
    async def set_target_value(request: Request, key: str, body: dict):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "目标点位值编辑仅允许在 DEBUG 模式")
        if "value" not in body:
            raise HTTPException(400, "请求体缺少 value 字段")
        try:
            return _points(request).set_target_value(key, body["value"])
        except ValueError as exc:  # 限位/类型
            raise HTTPException(400, str(exc))
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))

    @app.post("/api/points/plc_servo_target/{key}/push")
    async def push_target(request: Request, key: str):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "目标点位下发仅允许在 DEBUG 模式")
        try:
            return await _points(request).push_target(key)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))
        except Exception as exc:  # OPC-UA 写失败
            raise HTTPException(502, f"下发目标点位失败: {exc}")

    # 组合点位 (多根 flat 目标轴位聚为一个语义点位, 如点样位置): 逐成员读 actpos / 存 value / 整体下发
    @app.get("/api/points/plc_servo_composite/{key}/member/{member}/actpos")
    async def get_composite_member_actpos(request: Request, key: str, member: str):
        try:
            actpos = await _points(request).read_composite_member_actpos(key, member)
            return {"key": key, "member": member, "actpos": actpos}
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))
        except Exception as exc:  # OPC-UA 读失败 (含 sim 无镜像)
            raise HTTPException(502, f"读取组合点位成员实际位失败: {exc}")

    @app.put("/api/points/plc_servo_composite/{key}/member/{member}/value")
    async def set_composite_member_value(request: Request, key: str, member: str, body: dict):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "组合点位值编辑仅允许在 DEBUG 模式")
        if "value" not in body:
            raise HTTPException(400, "请求体缺少 value 字段")
        try:
            return _points(request).set_composite_member_value(key, member, body["value"])
        except ValueError as exc:  # 限位/类型
            raise HTTPException(400, str(exc))
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))

    @app.post("/api/points/plc_servo_composite/{key}/push")
    async def push_composite(request: Request, key: str):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "组合点位下发仅允许在 DEBUG 模式")
        try:
            return await _points(request).push_composite(key)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))
        except Exception as exc:  # OPC-UA 写失败
            raise HTTPException(502, f"下发组合点位失败: {exc}")

    # plc_servo 离散召回位 PC 真源 value 编辑 (收编工位; 与 plc_servo_target/value 同范式)
    @app.put("/api/points/plc_servo/{key}/value")
    async def set_servo_value(request: Request, key: str, body: dict):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "点位值编辑仅允许在 DEBUG 模式")
        if "value" not in body:
            raise HTTPException(400, "请求体缺少 value 字段")
        try:
            return _points(request).set_servo_value(key, body["value"])
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))

    # 双源同步 push/pull/diff (收编工位, 如地轨 rail): PC↔HMI 经 PLC flat 数组+邮箱对账。
    #   diff 只读安全; push 只覆盖工作副本; pull 改写真源 → DEBUG + confirm 二次确认。
    @app.get("/api/points/sync/{workstation}/diff")
    async def sync_diff(request: Request, workstation: str, threshold: float | None = None):
        try:
            kwargs = {} if threshold is None else {"threshold": threshold}
            return await _points(request).diff_sync(workstation, **kwargs)
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))
        except Exception as exc:  # OPC 读失败 (含 sim 无镜像)
            raise HTTPException(502, f"读取同步偏差失败: {exc}")

    @app.post("/api/points/sync/{workstation}/push")
    async def sync_push(request: Request, workstation: str):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "同步下发仅允许在 DEBUG 模式")
        try:
            return await _points(request).push_sync(workstation)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))
        except Exception as exc:  # OPC 写失败
            raise HTTPException(502, f"同步下发失败: {exc}")

    @app.post("/api/points/sync/{workstation}/pull")
    async def sync_pull(request: Request, workstation: str, body: dict | None = None):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "回收示教仅允许在 DEBUG 模式")
        confirm = bool((body or {}).get("confirm", False))
        try:
            return await _points(request).pull_sync(workstation, confirm=confirm)
        except ValueError as exc:  # 限位拒绝
            raise HTTPException(400, str(exc))
        except PointsCatalogError as exc:
            raise HTTPException(404, str(exc))
        except Exception as exc:  # OPC 读/写失败
            raise HTTPException(502, f"回收示教失败: {exc}")

    # 单点原始片段读写 (机器人): 仅展示/编辑当前点对应的源条目, 避免整文件冗长
    # (注册在 {category}/{point_id} 之前; 3 段路径不与 2 段单点详情冲突)
    @app.post("/api/points/robot/{point_id}/capture")
    async def capture_robot_point(request: Request, point_id: str):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "机器人点位示教仅允许在 DEBUG 模式")
        try:
            return _points(request).capture_robot_point(point_id)
        except (PointsCatalogError, PermissionError, ValueError) as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(502, f"读取机器人当前位置失败: {exc}")

    @app.post("/api/points/robot/{point_id}/commit")
    async def commit_robot_point(request: Request, point_id: str, body: dict):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "机器人点位覆盖保存仅允许在 DEBUG 模式")
        try:
            return _points(request).commit_robot_point_capture(
                point_id,
                pose=body.get("pose"),
                joint=body.get("joint"),
                confirm=bool(body.get("confirm", False)),
                note=body.get("note"),
            )
        except (PointsCatalogError, PermissionError, ValueError) as exc:
            raise HTTPException(400, str(exc))

    # 示教复核 (teach-verify): 用"新"捕获位算进近航点 → 按住二次进入逐点走位 → 回位漂移检查
    @app.post("/api/points/robot/{point_id}/teach/plan")
    async def teach_plan(request: Request, point_id: str, body: dict | None = None):
        try:
            return _points(request).teach_plan(point_id, (body or {}).get("captured_pose"))
        except (PointsCatalogError, PermissionError, ValueError) as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/points/robot/{point_id}/teach/move")
    async def teach_move(request: Request, point_id: str, body: dict):
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "示教复核运动仅允许在 DEBUG 模式")
        svc = _points(request)
        try:
            # 阻塞式机器人运动经线程池执行, 不阻塞事件循环 (deadman: 前端松手即 robotStop)
            return await asyncio.get_running_loop().run_in_executor(
                None, lambda: svc.teach_move(point_id, body.get("pose"), body.get("motion", "move_l")))
        except (PointsCatalogError, PermissionError, ValueError) as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(502, f"示教复核运动失败: {exc}")

    @app.post("/api/points/robot/{point_id}/teach/drift")
    async def teach_drift(request: Request, point_id: str, body: dict | None = None):
        try:
            return _points(request).teach_drift(point_id, (body or {}).get("captured_pose"))
        except (PointsCatalogError, PermissionError, ValueError) as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(502, f"读取回位漂移失败: {exc}")

    @app.get("/api/points/{category}/{point_id}/raw")
    async def get_point_raw(request: Request, category: str, point_id: str):
        try:
            return _points(request).read_point_raw(category, point_id)
        except (PointsCatalogError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc))

    @app.put("/api/points/{category}/{point_id}/raw")
    async def save_point_raw(request: Request, category: str, point_id: str, body: dict):
        svc = _points(request)
        text = body.get("text")
        if not isinstance(text, str):
            raise HTTPException(400, "请求体缺少 text 字段")
        # 机器人点位编辑 (影响实机运动): 仅 DEBUG 模式允许
        if request.app.state.control_mode != "DEBUG":
            raise HTTPException(409, "机器人点位编辑仅允许在 DEBUG 模式")
        try:
            return svc.save_point_raw(category, point_id, text)
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"解析失败: {exc}")
        except (PointsCatalogError, ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/points/{category}/{point_id}")
    async def get_point(request: Request, category: str, point_id: str):
        if category not in CATEGORIES:
            raise HTTPException(404, f"未知点位类别: {category}")
        dto = _points(request).get(category, point_id)
        if dto is None:
            raise HTTPException(404, f"未知点位: {category}/{point_id}")
        return dto
