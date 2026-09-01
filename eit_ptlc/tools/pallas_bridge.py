"""PALLASVision companion bridge.

The bridge keeps the PALLAS callback port open while EIT is running, then
exposes a small localhost HTTP API for the backend. It does not control the
robot or PLC; it only triggers PALLAS and returns parsed correction data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from eit_ptlc.config.loader import load_config
from eit_ptlc.config.models import PallasVisionCfg
from eit_ptlc.controller.pallas_vision_client import (
    PallasVisionError,
    PallasVisionResultError,
    parse_plate_offset_payload,
)

log = logging.getLogger("pallas_bridge")

_TERMINATORS = {
    "none": b"",
    "cr": b"\r",
    "lf": b"\n",
    "crlf": b"\r\n",
    "nul": b"\0",
}


class BridgeBusy(RuntimeError):
    """A capture is already in flight."""


class LocalVisionUnavailable(RuntimeError):
    """本地视觉未启用/不可用, 无法示教零点 (前置条件不满足, 非硬件故障)。"""


class PallasBridge:
    """Long-lived callback listener plus single-capture trigger gate."""

    def __init__(self, cfg: PallasVisionCfg) -> None:
        self.cfg = cfg
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._capture_lock = asyncio.Lock()
        self._pending: asyncio.Future[dict[str, Any]] | None = None
        self._capture_started_at: float | None = None
        self._started_at = time.time()
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_raw: str | None = None
        self._last_packet_at: float | None = None
        self._ignored_packets = 0
        self._accepted_connections = 0
        # 本地视觉临时替代路径缓存 (None=未探测, False=不可用/未启用, LocalVisionCfg=已启用)
        self._lpv_cfg: Any = None
        self._lpv_mod: Any = None

    async def start(self) -> None:
        if not self.cfg.enabled or self.cfg.mock:
            log.info("[PALLAS] bridge idle: enabled=%s mock=%s", self.cfg.enabled, self.cfg.mock)
            return
        self._server = await asyncio.start_server(
            self._handle_callback,
            self.cfg.listen_host,
            self.cfg.listen_port,
        )
        addrs = ", ".join(str(sock.getsockname()) for sock in (self._server.sockets or []))
        log.info("[PALLAS] callback listener ready: %s", addrs)

    async def stop(self) -> None:
        await self._close_clients()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._pending is not None and not self._pending.done():
            self._pending.cancel()

    async def reconnect(self) -> dict[str, Any]:
        """Force callback clients to reconnect without triggering capture."""
        await self._close_clients()
        self._last_error = None
        if self._server is None and self.cfg.enabled and not self.cfg.mock:
            await self.start()
        return self.status()

    async def capture(self) -> dict[str, Any]:
        if not self.cfg.enabled:
            return _neutral_offset("disabled")
        if self.cfg.mock:
            return _neutral_offset("mock")
        if self._capture_lock.locked():
            raise BridgeBusy("PALLASVision capture already running")

        async with self._capture_lock:
            lpv_cfg = self._local_vision_cfg()
            if lpv_cfg is not None:
                # 本地视觉临时替代路径 (加密狗丢失后启用); 未启用时下面回落原 PALLAS TCP
                try:
                    result = await self._capture_via_local_vision(lpv_cfg)
                    self._last_result = dict(result)
                    return result
                except Exception as exc:
                    self._last_error = str(exc)
                    raise
            loop = asyncio.get_running_loop()
            self._clear_capture_window()
            self._pending = loop.create_future()
            self._capture_started_at = None
            try:
                await self._send_trigger()
                result = await asyncio.wait_for(self._pending, timeout=self.cfg.result_timeout)
                self._last_result = dict(result)
                return result
            except asyncio.TimeoutError as exc:
                self._last_error = f"PALLASVision result timeout after {self.cfg.result_timeout:.1f}s"
                raise
            except Exception as exc:
                self._last_error = str(exc)
                raise
            finally:
                self._pending = None
                self._capture_started_at = None

    def _local_vision_cfg(self):
        """返回启用的本地视觉配置 (LocalVisionCfg); 未启用/不可用/未配置返回 None (回落 PALLAS TCP)。惰性加载并缓存。

        总开关是 pallas_vision.local_vision_enabled (app.yaml 经 PallasVisionCfg 流入);
        关闭时直接回落 PALLAS TCP, 现有离线测试 (该字段默认 False) 不受影响。
        """
        if self._lpv_cfg is False:
            return None
        if self._lpv_cfg is not None:
            return self._lpv_cfg
        if not getattr(self.cfg, "local_vision_enabled", False):
            self._lpv_cfg = False
            return None
        try:
            from eit_ptlc.controller import local_plate_vision as lpv
            cfg = lpv.load_cfg()
        except Exception:
            log.warning("[PALLAS] 本地视觉模块加载失败, 回落 PALLAS TCP", exc_info=True)
            self._lpv_cfg = False
            return None
        if cfg is None:
            log.warning("[PALLAS] local_vision_enabled=True 但未找到 local_plate_vision.yaml, 回落 PALLAS TCP")
            self._lpv_cfg = False
            return None
        self._lpv_mod = lpv
        self._lpv_cfg = cfg
        log.info("[PALLAS] 本地视觉纠偏路径已启用 (相机 %s), 替代 PALLAS TCP", cfg.ip)
        return cfg

    async def _capture_via_local_vision(self, lpv_cfg) -> dict[str, Any]:
        """本地视觉路径: 在线程池里触发 .163 拍照 + 检测 + 换算, 返回契约 dict。"""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._lpv_mod.measure_offset, lpv_cfg)
        log.info("[PALLAS] 本地视觉纠偏结果: %s", result)
        return result

    async def measure_pose(self) -> dict[str, Any]:
        """示教用: 触发本地视觉测一次板原始位姿 (u,v,theta), 不做纠偏换算。

        功能:
            与 capture() 共用同一 capture_lock (串行取图), 但只返回 detect 出的原始像素位姿,
            供板位对位控制台重新示教零点。仅本地视觉启用时可用 (否则示教无意义)。
        返回:
            dict{u, v, theta, valid}; 识别不到板 valid=False
        异常:
            LocalVisionUnavailable: 本地视觉未启用/配置缺失; RuntimeError: 相机取图失败
        """
        if self._capture_lock.locked():
            raise BridgeBusy("PALLASVision capture already running")
        async with self._capture_lock:
            lpv_cfg = self._local_vision_cfg()
            if lpv_cfg is None:
                raise LocalVisionUnavailable(
                    "本地视觉未启用, 无法示教零点 "
                    "(需 pallas_vision.local_vision_enabled=true 且 local_plate_vision.yaml 存在)")
            loop = asyncio.get_running_loop()
            pose = await loop.run_in_executor(None, self._lpv_mod.measure_pose, lpv_cfg)
            log.info("[PALLAS] 本地视觉示教测姿: %s", pose)
            return pose

    def reload_local_vision(self) -> dict[str, Any]:
        """清本地视觉配置缓存, 使下次 capture/measure_pose 重读 local_plate_vision.yaml。

        写零点 (reference.u0/v0/theta0) 后调用: Bridge 惰性缓存了 LocalVisionCfg, 不清则新零点
        不生效。清缓存后下次取图经 _local_vision_cfg 重新 load_cfg。
        """
        self._lpv_cfg = None
        self._lpv_mod = None
        log.info("[PALLAS] 本地视觉配置缓存已清, 下次取图将重读 local_plate_vision.yaml")
        return {"reloaded": True}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.cfg.enabled,
            "mock": self.cfg.mock,
            "trigger": {
                "host": self.cfg.host,
                "port": self.cfg.port,
                "terminator": self.cfg.terminator,
            },
            "callback": {
                "host": self.cfg.listen_host,
                "port": self.cfg.listen_port,
                "server_ready": self._server is not None or not self.cfg.enabled or self.cfg.mock,
                "clients": len(self._clients),
                "accepted_connections": self._accepted_connections,
            },
            "capturing": self._capture_lock.locked(),
            "last_result": self._last_result,
            "last_error": self._last_error,
            "last_raw": self._last_raw,
            "last_packet_at": self._last_packet_at,
            "ignored_packets": self._ignored_packets,
            "uptime_s": round(time.time() - self._started_at, 3),
        }

    async def _handle_callback(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._clients.add(writer)
        self._accepted_connections += 1
        peer = writer.get_extra_info("peername")
        log.info("[PALLAS] callback connected: %s", peer)
        try:
            while True:
                data = await reader.read(self.cfg.read_bytes)
                if not data:
                    break
                self._handle_payload(data)
        except Exception:
            log.exception("[PALLAS] callback read failed")
        finally:
            self._clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            log.info("[PALLAS] callback disconnected: %s", peer)

    def _handle_payload(self, payload: bytes) -> None:
        now = time.time()
        text = payload.decode(self.cfg.encoding, errors="replace").replace("\x00", "").strip()
        self._last_raw = text
        self._last_packet_at = now

        pending = self._pending
        if pending is None or pending.done():
            self._ignored_packets += 1
            log.info("[PALLAS] ignored callback outside capture window: %r", text)
            return
        if self._capture_started_at is None or now < self._capture_started_at:
            self._ignored_packets += 1
            log.info("[PALLAS] ignored callback before trigger window: %r", text)
            return

        try:
            result = parse_plate_offset_payload(
                payload,
                encoding=self.cfg.encoding,
                err_fail_code=self.cfg.err_fail_code,
                max_abs_xy_mm=self.cfg.max_abs_xy_mm,
                max_abs_rz_deg=self.cfg.max_abs_rz_deg,
            )
        except PallasVisionResultError as exc:
            self._last_error = str(exc)
            log.warning("[PALLAS] rejected callback result: %s", exc)
            pending.set_exception(exc)
            return

        result["source"] = "pallas_bridge"
        pending.set_result(result)

    async def _send_trigger(self) -> None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.cfg.host, self.cfg.port),
                timeout=self.cfg.connect_timeout,
            )
        except Exception as exc:
            raise PallasVisionError(f"连接 PALLASVision {self.cfg.host}:{self.cfg.port} 失败: {exc}") from exc
        try:
            self._capture_started_at = time.time()
            writer.write(self.cfg.trigger.encode(self.cfg.encoding) + _TERMINATORS[self.cfg.terminator])
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            del reader

    async def _close_clients(self) -> None:
        clients = list(self._clients)
        self._clients.clear()
        for writer in clients:
            writer.close()
        for writer in clients:
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def _clear_capture_window(self) -> None:
        self._last_result = None
        self._last_error = None
        self._last_raw = None
        self._ignored_packets = 0


def _neutral_offset(source: str) -> dict[str, Any]:
    return {"dx_mm": 0.0, "dy_mm": 0.0, "drz_deg": 0.0, "err": 0, "valid": True, "source": source}


def create_app(bridge: PallasBridge) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await bridge.start()
        try:
            yield
        finally:
            await bridge.stop()

    app = FastAPI(title="PALLASVision Bridge", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok", **bridge.status()}

    @app.get("/status")
    async def status():
        return bridge.status()

    @app.post("/capture")
    async def capture():
        try:
            return await bridge.capture()
        except BridgeBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, bridge.status()["last_error"]) from exc
        except PallasVisionResultError as exc:
            raise HTTPException(422, str(exc)) from exc
        except PallasVisionError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/reconnect")
    async def reconnect():
        return await bridge.reconnect()

    @app.post("/measure_pose")
    async def measure_pose():
        try:
            return await bridge.measure_pose()
        except BridgeBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except LocalVisionUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, f"measure_pose 失败: {exc}") from exc

    @app.post("/reload")
    async def reload():
        return bridge.reload_local_vision()

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PALLASVision companion bridge")
    parser.add_argument("--config", default=str(Path("eit_ptlc") / "config" / "app.yaml"))
    parser.add_argument("--host", default=None, help="HTTP bind host; defaults to pallas_vision.bridge_host")
    parser.add_argument("--port", type=int, default=None, help="HTTP port; defaults to pallas_vision.bridge_port")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    args = parse_args()
    cfg = load_config(Path(args.config)).pallas_vision
    app = create_app(PallasBridge(cfg))
    uvicorn.run(
        app,
        host=args.host or cfg.bridge_host,
        port=args.port or cfg.bridge_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
