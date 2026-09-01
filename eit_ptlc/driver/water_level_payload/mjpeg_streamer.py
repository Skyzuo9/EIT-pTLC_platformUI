#!/usr/bin/env python3
"""
MJPEG HTTP 按需流式传输服务

与 MultiChannelManager 松耦合集成: HTTP 线程只读取已采集/已渲染的帧缓存，
不调用任何有副作用的 detector 方法。

纯标准库实现 (http.server + cv2.imencode)，零额外依赖。

架构:
  MJPEGStreamer 在独立 daemon 线程运行 HTTP 服务
  └─ ChannelStream: 每条活跃通道一个, 管理状态与客户端引用计数
      └─ 从 ChannelDetector.get_frame() / get_rendered() 读取 → JPEG → HTTP multipart

并发安全:
  - 采集线程写入 latest_frame (frame_lock)
  - 主循环读取 latest_frame、调用 process_frame()、写入 latest_rendered (rendered_lock)
  - HTTP 线程只读取 latest_frame / latest_rendered (各自的锁)，不调用 process_frame()
"""

import cv2
import time
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器: 每个请求独立线程, 支持并发 MJPEG 流"""
    daemon_threads = True
import numpy as np


# --- MJPEG multipart 常量 ---
_BOUNDARY = b"--MJPEGBOUNDARY\r\n"
_HEADER_JPG = b"Content-Type: image/jpeg\r\n\r\n"
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
}


class ChannelStream:
    """单通道 MJPEG 流状态机"""

    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        self.ref_count = 0
        self.state = "IDLE"          # IDLE | READY | ACTIVE
        self.last_client_time = 0.0  # grace period 计时起点
        self.last_ready_time = 0.0   # READY timeout 计时起点
        self.last_active_beat = 0.0  # ACTIVE 心跳: 用于检测 ref_count 泄漏


class MJPEGStreamer:
    """
    MJPEG HTTP 流式传输服务.

    用法:
        streamer = MJPEGStreamer(port=8080, max_active=8, manager=mgr)
        streamer.start()
        streamer.stream_start(3)   # 激活通道 3 的 HTTP 端点
        streamer.stream_stop(3)    # 停用
        streamer.shutdown()        # 退出时调用
    """

    GRACE_PERIOD = 30.0
    READY_TIMEOUT = 60.0
    MAX_ACTIVE = 8
    JPEG_QUALITY = 70

    def __init__(self, port=8080, max_active=8, jpeg_quality=70,
                 multi_channel_manager=None):
        self.port = port
        self.max_active = max_active
        self.jpeg_quality = jpeg_quality
        self._mgr = multi_channel_manager

        self._server = None
        self._thread = None
        self._running = False
        self._streams: dict[int, ChannelStream] = {}

    # ---- detector 访问 ----
    def _get_detector(self, channel_id: int):
        """1-based channel_id → ChannelDetector | None"""
        if self._mgr is None:
            return None
        idx = channel_id - 1
        if 0 <= idx < self._mgr.num_channels:
            return self._mgr.channels[idx]
        return None

    def _active_count(self) -> int:
        return sum(1 for s in self._streams.values() if s.state == "ACTIVE")

    # ================================================================
    # HTTP RequestHandler (闭包绑定 streamer)
    # ================================================================
    def _build_handler(self):
        streamer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                pass  # 静默, 避免刷屏

            def _cors(self):
                for k, v in _CORS_HEADERS.items():
                    self.send_header(k, v)

            def _error(self, code, msg):
                # HTTP/1.1 下必须带 Content-Length + Connection: close, 否则客户端
                # (http.client / httpx) 无从判断 body 结束 → 一直 read 到超时挂起。
                body = msg.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self._cors()
                self.end_headers()
                self.wfile.write(body)

            def _stream_channel(self, ch_id: int, raw: bool = False, debug: bool = False):
                cs = streamer._streams.get(ch_id)
                print(f"[MJPEG-DBG] _stream_channel ch{ch_id} raw={raw} debug={debug} "
                      f"cs_state={cs.state if cs else 'None'} "
                      f"cs_ref={cs.ref_count if cs else 'N/A'}")

                # 优雅等待: MQTT stream_start 命令可能正在传输中,
                # 轮询最多 3 秒等待状态从 IDLE → READY
                if cs is None or cs.state == "IDLE":
                    print(f"[MJPEG-DBG] ch{ch_id} 状态={cs.state if cs else 'None'}, "
                          f"等待 READY (最多3s)...")
                    waited = 0.0
                    while waited < 3.0:
                        time.sleep(0.1)
                        waited += 0.1
                        cs = streamer._streams.get(ch_id)
                        if cs is not None and cs.state != "IDLE":
                            break
                    if cs is None or cs.state == "IDLE":
                        print(f"[MJPEG-DBG] ch{ch_id} 超时: 仍为 IDLE → 503")
                        self._error(503, "Channel not active")
                        return
                    print(f"[MJPEG-DBG] ch{ch_id} 状态已变为 {cs.state} (等待{waited:.1f}s)")

                detector = streamer._get_detector(ch_id)
                if detector is None:
                    print(f"[MJPEG-DBG] ch{ch_id} detector=None → 404")
                    self._error(404, "Channel not found")
                    return

                cs.ref_count += 1
                cs.state = "ACTIVE"
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, streamer.jpeg_quality]

                # ★ 启用 debug 缓存 (如有)
                if debug:
                    detector._debug_enabled = True
                    detector._debug_notified_process = False  # 允许下次 process_frame 打印状态
                    detector._debug_write_count = 0  # 重置写入计数器
                    detector._get_debug_call_count = 0  # 重置读取计数器
                    print(f"[MJPEG-DBG] ch{ch_id} _debug_enabled=True "
                          f"calibrated={detector.calibrated} "
                          f"has_roi={detector.roi_bbox is not None} "
                          f"has_ref={detector.ref_gray is not None} "
                          f"state={detector.state}")

                try:
                    self.send_response(200)
                    self.send_header("Content-Type",
                                     "multipart/x-mixed-replace; boundary=MJPEGBOUNDARY")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self._cors()
                    self.end_headers()

                    frame_count = 0
                    none_count = 0
                    while cs.ref_count > 0:
                        if debug:
                            frame = detector.get_debug()
                        elif raw:
                            frame = detector.get_frame()
                        else:
                            frame = detector.get_rendered()

                        if frame is None:
                            none_count += 1
                            if none_count == 1 or none_count % 50 == 0:
                                print(f"[MJPEG-DBG] ch{ch_id} frame=None "
                                      f"(累计{none_count}次) mode={'debug' if debug else 'raw' if raw else 'annotated'}")
                            time.sleep(0.05)
                            continue
                        elif none_count > 0:
                            print(f"[MJPEG-DBG] ch{ch_id} frame恢复 (之前{none_count}次None)")

                        frame_count += 1
                        if frame_count == 1:
                            print(f"[MJPEG-DBG] ch{ch_id} 首帧: shape={frame.shape} "
                                  f"dtype={frame.dtype} mode={'debug' if debug else 'raw' if raw else 'annotated'}")

                        ok, jpg = cv2.imencode(".jpg", frame, encode_params)
                        if not ok:
                            continue

                        cs.last_active_beat = time.time()  # 心跳: 用于泄漏检测
                        try:
                            self.wfile.write(_BOUNDARY)
                            self.wfile.write(_HEADER_JPG)
                            self.wfile.write(jpg.tobytes())
                            self.wfile.write(b"\r\n")
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            print(f"[MJPEG-DBG] ch{ch_id} 客户端断开 "
                                  f"(已发送{frame_count}帧)")
                            break
                finally:
                    if debug:
                        detector._debug_enabled = False
                        print(f"[MJPEG-DBG] ch{ch_id} _debug_enabled=False "
                              f"(共发送{frame_count}帧, None={none_count}次)")
                    cs.ref_count = max(0, cs.ref_count - 1)
                    if cs.ref_count == 0:
                        cs.last_client_time = time.time()

            def _stream_grid(self):
                """8 路 2×4 网格概览"""
                cell_w, cell_h = 480, 360
                blank = None
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, streamer.jpeg_quality]

                self.send_response(200)
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=MJPEGBOUNDARY")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self._cors()
                self.end_headers()

                while True:
                    cells = []
                    for i in range(8):
                        if streamer._mgr and i < streamer._mgr.num_channels:
                            ch = streamer._mgr.channels[i]
                            rendered = ch.get_rendered()
                            if rendered is not None:
                                cell = cv2.resize(rendered, (cell_w, cell_h))
                            else:
                                # fallback: raw frame
                                raw_frame = ch.get_frame()
                                if raw_frame is not None:
                                    cell = cv2.resize(raw_frame, (cell_w, cell_h))
                                else:
                                    if blank is None:
                                        blank = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
                                    cell = blank.copy()
                                    cv2.putText(cell, f"CH{ch.channel_id}: No Signal",
                                                (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                                                0.7, (0, 0, 255), 2)
                        else:
                            if blank is None:
                                blank = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
                            cell = blank.copy()
                        cells.append(cell)

                    rows = [np.hstack(cells[:4]), np.hstack(cells[4:8])]
                    grid = np.vstack(rows)

                    ok, jpg = cv2.imencode(".jpg", grid, encode_params)
                    if not ok:
                        continue

                    try:
                        self.wfile.write(_BOUNDARY)
                        self.wfile.write(_HEADER_JPG)
                        self.wfile.write(jpg.tobytes())
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break

            def _serve_single_frame(self, ch_id: int):
                """单帧 JPEG 拉取 (上位机定时拉帧检测用; 无 multipart / 无 stream_start 生命周期)。

                只读 detector.get_frame() 的最近原始帧 → JPEG, 一次性返回。检测已搬到上位机,
                故只给原始帧 (不渲染/不标注)。前提: 通道已 set_active_channels 激活 (CAPTURE 态
                才有 latest_frame); 未激活/无帧返回 503, 上位机据此跳过该轮。
                """
                detector = streamer._get_detector(ch_id)
                if detector is None:
                    self._error(404, "Channel not found")
                    return
                frame = detector.get_frame()
                if frame is None:
                    self._error(503, "No frame (channel idle or not capturing)")
                    return
                ok, jpg = cv2.imencode(
                    ".jpg", frame,
                    [cv2.IMWRITE_JPEG_QUALITY, streamer.jpeg_quality])
                if not ok:
                    self._error(500, "JPEG encode failed")
                    return
                body = jpg.tobytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self._cors()
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            # ---- 路由 ----
            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path
                params = parse_qs(parsed.query)

                # /frame/ch{N}  — 单帧 JPEG (上位机定时拉帧检测; 区别于 /stream 的连续流)
                if path.startswith("/frame/ch"):
                    try:
                        ch_id = int(path[len("/frame/ch"):])
                    except ValueError:
                        self._error(400, "Invalid channel number")
                        return
                    self._serve_single_frame(ch_id)
                    return

                # /stream/ch{N}  or  /stream/ch{N}?raw=1  or  /stream/ch{N}?debug=1
                if path.startswith("/stream/ch"):
                    try:
                        ch_id = int(path[len("/stream/ch"):])
                    except ValueError:
                        self._error(400, "Invalid channel number")
                        return
                    raw = params.get('raw', ['0'])[0] == '1'
                    debug = params.get('debug', ['0'])[0] == '1'
                    print(f"[MJPEG-DBG] HTTP GET ch{ch_id} raw={raw} debug={debug} "
                          f"query={parsed.query!r} path={path!r}")
                    self._stream_channel(ch_id, raw=raw, debug=debug)

                # /stream/grid
                elif path == "/stream/grid":
                    self._stream_grid()

                # /stream/status (调试)
                elif path == "/stream/status":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    info = {
                        "active": streamer._active_count(),
                        "max": streamer.max_active,
                        "streams": {
                            str(k): v.state for k, v in streamer._streams.items()
                        },
                    }
                    self.wfile.write(json.dumps(info, ensure_ascii=False).encode())

                else:
                    self._error(404, "Not Found. Try /stream/ch1 or /stream/grid")

            def do_OPTIONS(self):
                self.send_response(200)
                self._cors()
                self.end_headers()

        return Handler

    # ================================================================
    # 控制接口 (由 MQTT handler 调用)
    # ================================================================
    def stream_start(self, channel_id: int) -> dict:
        if self._active_count() >= self.max_active:
            return {"result": "error",
                    "message": f"active streams limit ({self.max_active}) reached"}

        if channel_id not in self._streams:
            self._streams[channel_id] = ChannelStream(channel_id)

        cs = self._streams[channel_id]
        cs.ref_count = 0          # 防御: 清理上次非正常退出残留的 ref_count
        cs.state = "READY"
        cs.last_ready_time = time.time()
        print(f"[MJPEG] CH{channel_id} → READY")
        return {"result": "ok", "channel": channel_id, "port": self.port}

    def stream_stop(self, channel_id: int) -> dict:
        cs = self._streams.get(channel_id)
        if cs:
            cs.state = "IDLE"
            cs.ref_count = 0
            print(f"[MJPEG] CH{channel_id} → IDLE")
            return {"result": "ok", "channel": channel_id}
        return {"result": "error", "message": "Channel not found"}

    def stream_stop_all(self):
        for cs in self._streams.values():
            cs.state = "IDLE"
            cs.ref_count = 0
        print("[MJPEG] 全部通道 → IDLE")

    # ================================================================
    # 生命周期
    # ================================================================
    def start(self):
        handler = self._build_handler()
        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        self._running = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="mjpeg-http")
        self._thread.start()
        print(f"[MJPEG] HTTP 服务已启动 → http://0.0.0.0:{self.port}")

    def shutdown(self):
        self._running = False
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
        print("[MJPEG] HTTP 服务已关闭")

    def cleanup_timeouts(self):
        """主循环周期性调用: 回收超时通道"""
        now = time.time()
        for cid, cs in list(self._streams.items()):
            if cs.state == "ACTIVE" and cs.ref_count == 0:
                # 客户端正常断开，检查 grace period
                if now - cs.last_client_time > self.GRACE_PERIOD:
                    cs.state = "READY"
                    cs.last_ready_time = now
                    print(f"[MJPEG] CH{cid} grace period 到期 → READY")
            elif cs.state == "ACTIVE" and cs.ref_count > 0:
                # 防御: ref_count 泄漏 (上位机非正常退出)
                # 心跳超时 3×READY_TIMEOUT (180s) → 强制回收
                if (cs.last_active_beat > 0 and
                        now - cs.last_active_beat > self.READY_TIMEOUT * 3):
                    print(f"[MJPEG] CH{cid} ACTIVE 心跳丢失 (rc={cs.ref_count}) → 强制 IDLE")
                    cs.ref_count = 0
                    cs.state = "IDLE"
            elif cs.state == "READY":
                # 无客户端连接，检查 READY 超时
                if now - cs.last_ready_time > self.READY_TIMEOUT:
                    cs.state = "IDLE"
                    print(f"[MJPEG] CH{cid} READY 超时 → IDLE")
