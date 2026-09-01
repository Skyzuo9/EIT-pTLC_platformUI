"""液位检测路由 (控制台专用 + MJPEG 代理)
==========================================
功能:
    注册液位外设 (香橙派) 控制台所需的 HTTP 端点到 FastAPI 应用。混合模式中的"控制台"一半:
    离散动作 (query_status/stream_start/stop) 走 /api/actions, 此处承载交互性命令透传与视频流。

    从 app.state 读取 (由 lifespan 注入):
        water_level_client - WaterLevelClient (MQTT 下发 + CMD_TOPICS 白名单)
        water_level_ctrl   - WaterLevelController (只读快照: online/channels/alarm_count)
        water_level_cfg    - WaterLevelCfg (orangepi_ip / stream_port, 构造上游 MJPEG URL)
    三者为 None 时 (SIM / 未启用 / paho 缺失): snapshot 返回离线, 命令/代理 503, 不阻断应用。

端点 (统一 /api 前缀, 经前端 vite 代理直达后端):
    GET  /api/water_level/snapshot          液位只读快照 (在线 + 各通道最新数据 + 报警计数)
    POST /api/water_level/cmd/{cmd}          命令分发: 标定/参数落上位机检测服务, record_* 落上位机录制器,
                                             其余经 CMD_TOPICS 白名单透传香橙派; body=payload
        record_start {channel, sample_id?}   → {ok, path, recording:true}   单通道原始录制开 (Phase 0)
        record_stop  {channel}               → {ok, summary}                录制停 + 汇总 (帧数/起止/标定快照)
        record_status {}                     → {ok, recordings:[...]}       当前活跃录制列表
    GET  /api/water_level/debug_frame/ch{N}  上位机渲染的检测叠加图 (ROI 框 + 湿区掩膜 + 前沿线 + 数值)
                                             ?overlay=0 关掉就地涂色与前沿线 (只留标定框与 HUD)
    GET  /api/water_level/history/{channel}  该通道 front% 走势历史 (~30min 环形缓冲)
    GET  /api/water_level/stream/{path}      同源代理香橙派 MJPEG 流 (path=ch1/grid; 透传 ?raw=1/?debug=1)
    POST /api/water_level/opi/start          SSH 香橙派启动液位脚本 (run.sh); ?wait=1 则等 MQTT online
    POST /api/water_level/opi/stop           SSH 香橙派停止液位脚本
    GET  /api/water_level/opi/status         SSH 查香橙派液位脚本进程是否存活
    POST /api/water_level/opi/deploy         scp 推送本机 payload_dir 载荷脚本到香橙派 work_dir
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

log = logging.getLogger(__name__)

# MJPEG multipart 边界 (与香橙派 mjpeg_streamer.py 一致)
_MJPEG_MEDIA_TYPE = "multipart/x-mixed-replace; boundary=MJPEGBOUNDARY"

# 标定/参数/参考图: 检测真源在上位机, 由 detect service 处理, 不透传香橙派
_UPPER_CMDS = {
    "capture_reference", "set_roi", "clear_roi", "set_calibration",
    "set_detect_param", "get_detect_param", "get_calibration", "save_detect_param", "load_detect_param",
    "reload_config",
}


def _dispatch_upper_cmd(detect, cmd: str, body: dict) -> dict:
    """把标定/参数/参考图命令落到上位机检测服务 (取代香橙派 MQTT 下发)。"""
    ch = body.get("channel")
    if cmd == "capture_reference":
        if ch is None:
            raise HTTPException(400, "capture_reference 需要 channel")
        detect.request_reference(int(ch))
        return {"ok": True, "cmd": cmd, "channel": int(ch)}
    if cmd == "set_roi":
        for k in ("channel", "x", "y", "w", "h"):
            if k not in body:
                raise HTTPException(400, f"set_roi 缺少 {k}")
        detect.update_roi(int(ch), body["x"], body["y"], body["w"], body["h"],
                          save=bool(body.get("save", True)))
        return {"ok": True, "cmd": cmd, "channel": int(ch)}
    if cmd == "clear_roi":
        if ch is None:
            raise HTTPException(400, "clear_roi 需要 channel")
        detect.clear_roi(int(ch))
        return {"ok": True, "cmd": cmd, "channel": int(ch)}
    if cmd == "set_calibration":
        if ch is None:
            raise HTTPException(400, "set_calibration 需要 channel")
        extra = {}
        if "dry_ref_frac" in body:   # 键存在才透传: 缺席=保持现值 (兼容不带此键的旧调用方)
            extra["dry_ref_frac"] = body["dry_ref_frac"]
        detect.update_calibration(
            int(ch), rotation_angle_deg=body.get("rotation_angle_deg"),
            roi_bbox=body.get("roi_bbox"), roi_frac=body.get("roi_frac"),
            flow_direction=body.get("flow_direction"),
            save=bool(body.get("save", True)), **extra)
        return {"ok": True, "cmd": cmd, "channel": int(ch)}
    if cmd == "get_calibration":
        if ch is None:
            raise HTTPException(400, "get_calibration 需要 channel")
        return {"ok": True, "cmd": cmd, "channel": int(ch),
                "calib": detect.get_calibration(int(ch))}
    if cmd == "set_detect_param":
        if ch is None:
            raise HTTPException(400, "set_detect_param 需要 channel")
        detect.update_params(int(ch), body.get("params", {}))
        return {"ok": True, "cmd": cmd, "channel": int(ch)}
    if cmd == "get_detect_param":
        if ch is None:
            raise HTTPException(400, "get_detect_param 需要 channel")
        return {"ok": True, "cmd": cmd, "channel": int(ch),
                "params": detect.get_params(int(ch))}
    if cmd == "save_detect_param":
        detect.save_all()
        return {"ok": True, "cmd": cmd,
                "params": detect.get_params(int(ch)) if ch is not None else {}}
    if cmd == "load_detect_param":
        # 从盘重载 (单写者兜底: 外部离线整定写盘后同步进运行态), 返回该通道刷新后的参数
        detect.reload()
        return {"ok": True, "cmd": cmd,
                "params": detect.get_params(int(ch)) if ch is not None else {}}
    if cmd == "reload_config":
        # 从标定文件重读全部通道 (安全阀); 返回全通道当前参数供前端整体刷新
        detect.reload()
        return {"ok": True, "cmd": cmd,
                "channels": {ch2: detect.get_params(ch2) for ch2 in range(1, 9)}}
    raise HTTPException(404, f"未知上位机命令: {cmd}")


# 单通道原始录制 (Phase 0): host 拥有, 落到 water_level_recorder (与拉帧检测同源 /frame/chN)
_RECORD_CMDS = {"record_start", "record_stop", "record_status"}


def _dispatch_record_cmd(recorder, cmd: str, body: dict) -> dict:
    """把录制命令落到上位机单通道录制器 (start/stop 幂等; status 只读)。"""
    if cmd == "record_status":
        return {"ok": True, "cmd": cmd, **recorder.status()}
    ch = body.get("channel")
    if ch is None:
        raise HTTPException(400, f"{cmd} 需要 channel")
    if cmd == "record_start":
        sample_id = body.get("sample_id")
        if sample_id is not None:
            sample_id = str(sample_id).strip() or None
        try:
            path = recorder.start(int(ch), sample_id)
        except Exception as exc:
            raise HTTPException(500, f"录制启动失败: {exc}")
        return {"ok": True, "cmd": cmd, "channel": int(ch), "path": path, "recording": True}
    if cmd == "record_stop":
        return {"ok": True, "cmd": cmd, "channel": int(ch), "summary": recorder.stop(int(ch))}
    raise HTTPException(404, f"未知录制命令: {cmd}")


def register_water_level_routes(app: FastAPI) -> None:
    """把液位控制台路由注册到应用。"""

    @app.get("/api/water_level/snapshot")
    async def water_level_snapshot(request: Request):
        # 通道 front% 来自上位机拉帧检测 (water_level_detect); 设备在线来自香橙派 MQTT LWT (ctrl)
        ctrl = getattr(request.app.state, "water_level_ctrl", None)
        detect = getattr(request.app.state, "water_level_detect", None)
        if ctrl is None and detect is None:
            # SIM / 未启用 / 未连接: 返回离线快照, 前端据此显示"设备离线", 不报错
            return {"online": False, "channels": {}, "alarm_count": 0, "enabled": False}
        ctrl_snap = ctrl.snapshot() if ctrl is not None else {}
        det = detect.snapshot() if detect is not None else {}
        return {
            "online": bool(ctrl_snap.get("online", False)),
            "channels": det.get("channels", {}),
            "active": det.get("active", []),
            "reachable_any": det.get("reachable_any", False),
            "alarm_count": ctrl_snap.get("alarm_count", 0),
            "enabled": True,
        }

    @app.post("/api/water_level/cmd/{cmd}")
    async def water_level_cmd(request: Request, cmd: str, body: dict | None = None):
        body = body or {}
        # 标定/参数/参考图: 检测真源在上位机, 由 detect service 处理, 不再透传香橙派
        if cmd in _UPPER_CMDS:
            detect = getattr(request.app.state, "water_level_detect", None)
            if detect is None:
                raise HTTPException(503, "拉帧检测服务未就绪 (SIM 或未启用)")
            return _dispatch_upper_cmd(detect, cmd, body)

        # 单通道原始录制 (Phase 0): host 拥有, 落到 water_level_recorder (不透传香橙派)
        if cmd in _RECORD_CMDS:
            recorder = getattr(request.app.state, "water_level_recorder", None)
            if recorder is None:
                raise HTTPException(503, "单通道录制器未就绪 (SIM 或未启用)")
            detect = getattr(request.app.state, "water_level_detect", None)
            ch = body.get("channel")
            # 录制帧源前提: 被录通道必须在香橙派激活采集; 用硬 pin(record=True), 上限下优先级最高 →
            # 录制途中误点别的 ch 页面也挤不掉正在录的相机。
            if cmd == "record_start" and detect is not None and ch is not None:
                await detect.ensure_active(int(ch), record=True)   # 先确保帧源在采集再起录
            result = _dispatch_record_cmd(recorder, cmd, body)
            if cmd == "record_stop" and detect is not None and ch is not None:
                await detect.release_pin(int(ch), record=True)     # 停录 → 解硬 pin
            return result

        # 单路视频流开/关: 同步 pin/解 pin 该通道 (max_active_channels 上限下"查看哪路才激活哪路";
        # 上限=0 时 ensure_active 幂等无副作用). 之后仍透传香橙派设 STREAM 态。
        if cmd in ("stream_start", "stream_stop"):
            detect = getattr(request.app.state, "water_level_detect", None)
            ch = body.get("channel")
            if detect is not None and ch is not None:
                if cmd == "stream_start":
                    await detect.ensure_active(int(ch))
                else:
                    await detect.release_pin(int(ch))

        # 其余 (硬件/视频流: restart_camera/stream_start/stop/query_status/...) 透传香橙派
        client = getattr(request.app.state, "water_level_client", None)
        if client is None:
            raise HTTPException(503, "液位客户端未就绪 (SIM 或未启用)")
        if cmd not in client.CMD_TOPICS:
            raise HTTPException(404, f"未知液位命令: {cmd} (合法 {sorted(client.CMD_TOPICS)})")
        ok = await client.send_command(cmd, body)
        if not ok:
            raise HTTPException(502, f"命令下发失败 (未连接或发布失败): {cmd}")
        return {"ok": True, "cmd": cmd}

    @app.post("/api/water_level/opi/start")
    async def water_level_opi_start(request: Request, wait: int = 0):
        """SSH 香橙派启动液位脚本。wait=1 时启动后再等 MQTT online 确认 (start_and_wait)。"""
        opi = getattr(request.app.state, "orangepi", None)
        if opi is None:
            raise HTTPException(503, "香橙派 SSH 管理未就绪 (未启用 water_level)")
        if not opi.ssh_target:
            raise HTTPException(503, "香橙派 SSH 目标未配置 (water_level.orangepi_ip/ssh_ip 为空)")
        ok = await (opi.start_and_wait() if wait else opi.start_remote())
        if not ok:
            raise HTTPException(502, "香橙派远程启动失败 (检查 SSH 免密/网络/脚本日志)")
        return {"ok": True, "target": opi.ssh_target}

    @app.post("/api/water_level/opi/stop")
    async def water_level_opi_stop(request: Request):
        """SSH 香橙派停止液位脚本 (按 PID 文件 kill)。"""
        opi = getattr(request.app.state, "orangepi", None)
        if opi is None:
            raise HTTPException(503, "香橙派 SSH 管理未就绪 (未启用 water_level)")
        if not opi.ssh_target:
            raise HTTPException(503, "香橙派 SSH 目标未配置 (water_level.orangepi_ip/ssh_ip 为空)")
        ok = await opi.stop_remote()
        if not ok:
            raise HTTPException(502, "香橙派远程停止失败 (检查 SSH 免密/网络)")
        return {"ok": True, "target": opi.ssh_target}

    @app.post("/api/water_level/opi/deploy")
    async def water_level_opi_deploy(request: Request):
        """scp 推送本机 payload_dir 载荷脚本到香橙派 work_dir (含 run.sh CRLF 修正)。"""
        opi = getattr(request.app.state, "orangepi", None)
        if opi is None:
            raise HTTPException(503, "香橙派 SSH 管理未就绪 (未启用 water_level)")
        if not opi.ssh_target:
            raise HTTPException(503, "香橙派 SSH 目标未配置 (water_level.orangepi_ip/ssh_ip 为空)")
        result = await opi.deploy_payload()
        if not result.get("ok"):
            raise HTTPException(502, result.get("error") or "载荷部署失败")
        return {"ok": True, "files": result["files"], "target": opi.ssh_target}

    @app.get("/api/water_level/opi/status")
    async def water_level_opi_status(request: Request):
        """SSH 查香橙派液位脚本进程是否存活。未就绪返回 running=false 而非报错。"""
        opi = getattr(request.app.state, "orangepi", None)
        if opi is None or not opi.ssh_target:
            return {"enabled": False, "running": False, "target": ""}
        running = await opi.check_remote_running()
        return {"enabled": True, "running": running, "target": opi.ssh_target}

    @app.get("/api/water_level/frame/{path:path}")
    async def water_level_frame_proxy(request: Request, path: str):
        """同源代理香橙派单帧 JPEG (GET /frame/chN): 网格总览低频拉帧用。

        相比 8 路持久 MJPEG 流, 单帧瞬时连接不占满浏览器单主机连接上限(~6)/香橙派带宽,
        故网格画面能持续刷新 (总览 1s 一帧足够; 实时连续流留给单路视图)。path 形如 ch1。
        """
        cfg = getattr(request.app.state, "water_level_cfg", None)
        if cfg is None:
            raise HTTPException(503, "液位配置未就绪 (SIM 或未启用)")
        sub = path
        if sub.startswith("ch/") and len(sub) > 3:
            sub = "ch" + sub[3:]
        upstream = f"http://{cfg.orangepi_ip}:{cfg.stream_port}/frame/{sub}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0), trust_env=False) as client:
                resp = await client.get(upstream)
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"拉帧失败: {exc}")
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, "上游无帧 (通道未激活/无信号)")
        return Response(content=resp.content, media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/api/water_level/debug_frame/ch{channel}")
    async def water_level_debug_frame(request: Request, channel: int, overlay: int = 1):
        """上位机渲染的检测叠加图 (「识别」页图源): 与 snapshot 数字同出一帧。

        不是代理 —— 检测在上位机, 香橙派只给原始帧, 叠加图由 detect service 用它缓存的
        那一帧现渲。通道未激活/尚未出结果时 503, 文案区分两种情形便于现场排查。

        overlay=0: 板面不着色也不画前沿线 (只留三个标定框与 HUD), 供与 overlay=1 对照 ——
        关掉看真实干湿边界, 开启看算法判成什么样, 一比就知道判得准不准。
        """
        detect = getattr(request.app.state, "water_level_detect", None)
        if detect is None:
            raise HTTPException(503, "拉帧检测服务未就绪 (SIM 或未启用)")
        jpeg = detect.debug_frame_jpeg(channel, inplace_overlay=bool(overlay))
        if jpeg is None:
            snap = detect.snapshot() or {}
            if channel not in (snap.get("active") or []):
                raise HTTPException(503, f"CH{channel} 未激活 (打开该通道页面或开流后重试)")
            raise HTTPException(503, f"CH{channel} 尚未产出检测帧 (等待下一轮拉帧)")
        return Response(content=jpeg, media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/api/water_level/history/{channel}")
    async def water_level_history(request: Request, channel: int, limit: int = 900):
        """该通道 front% 走势历史 (最旧在前)。

        独立端点而非并进 /snapshot: snapshot 被前端以 1s 轮询全通道, 塞进历史点会把它撑爆。
        """
        detect = getattr(request.app.state, "water_level_detect", None)
        if detect is None:
            raise HTTPException(503, "拉帧检测服务未就绪 (SIM 或未启用)")
        return {"channel": channel, "points": detect.history(channel, limit)}

    @app.get("/api/water_level/stream/{path:path}")
    async def water_level_mjpeg_proxy(request: Request, path: str):
        """同源代理香橙派 MJPEG 流: 避开 CORS/混合内容, 并规避浏览器单主机 6 连接上限。

        path 形如 "ch1" / "grid"; 兼容前端误传的 "ch/1" (归一为 "ch1")。透传查询串 (?raw=1/?debug=1)。
        """
        cfg = getattr(request.app.state, "water_level_cfg", None)
        if cfg is None:
            raise HTTPException(503, "液位配置未就绪 (SIM 或未启用)")
        sub = path
        if sub.startswith("ch/") and len(sub) > 3:
            sub = "ch" + sub[3:]
        upstream = f"http://{cfg.orangepi_ip}:{cfg.stream_port}/stream/{sub}"
        if request.url.query:
            upstream += f"?{request.url.query}"

        # 先建连并读上游状态码, 再决定响应形态。★关键: 上游非-200 (如通道刚 stream_start、
        # cs 尚未 READY 时的 503) 必须原样透传。否则 StreamingResponse 默认已发 200, 上游错误
        # 只是让生成器提前 return → 浏览器收到"空的 200": <img> 既不 error 也不 load → 永久
        # 静默黑屏, 还废掉前端 onStreamError 限频重连。透传真实状态后, 开流瞬间的短暂 503 会被
        # 前端重连接住, stream_start 落地即连上 (对照: /frame 代理已正确透传 resp.status_code)。
        timeout = httpx.Timeout(600.0, connect=5.0)
        client = httpx.AsyncClient(timeout=timeout, trust_env=False)
        try:
            req = client.build_request("GET", upstream)
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            log.warning("[WL] MJPEG 代理连接失败 %s: %s", upstream, exc)
            raise HTTPException(502, f"MJPEG 上游连接失败: {exc}")
        if resp.status_code != 200:
            status = resp.status_code
            await resp.aclose()
            await client.aclose()
            log.warning("[WL] MJPEG 上游 %s 返回 %s (透传)", upstream, status)
            raise HTTPException(status, "上游无帧 (通道未激活/未就绪)")

        async def _stream():
            try:
                async for chunk in resp.aiter_bytes(65536):
                    yield chunk
            except httpx.HTTPError as exc:
                log.warning("[WL] MJPEG 代理流中断 %s: %s", upstream, exc)
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(_stream(), media_type=_MJPEG_MEDIA_TYPE)
