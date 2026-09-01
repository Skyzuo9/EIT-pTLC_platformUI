"""液位单通道原始录制器 (上位机侧, 为回放而生)
================================================
功能 (Phase 0):
    对单个展缸通道, 以 ~cap_fps 轮询香橙派单帧端点 GET /frame/ch{N} (一次性 JPEG,
    质量 70 —— 与拉帧检测器 waterlevel_service._grab 同一帧源), 把逐帧写入 MJPG-fourcc
    AVI, 并旁挂:
      - <stem>.jsonl     逐帧真实墙钟时间戳 {"i": idx, "t": epoch_seconds} (实际 fps 抖动)
      - <stem>.meta.json 通道/样品/分辨率/起止时刻/帧数/当时标定快照

    录的正是检测器所见 (同一 /frame 端点), 且不解 MJPEG multipart、不占香橙派持久流
    slot (MAX_ACTIVE) —— 单帧瞬时连接。产物必须能被 replay() 重开喂回检测器做离线整定。

职责边界:
    - 帧源/落盘/时间戳/标定快照 → 本模块
    - 检测算法 → waterlevel_detector (不碰)
    - 标定真源 → waterlevel_store / detect service (只读快照, 经注入的 calibration_snapshot)

风格 (照 waterlevel_service 的永不抛服务风格):
    后台线程循环丢坏帧、记日志、继续; start/stop 幂等; 一条录制一条线程。

内部接口 (P3 自动 per-run 录制可直接复用):
    start(channel, sample_id=None) -> str(avi_path)   幂等: 已在录该通道则返回既有路径
    stop(channel)                  -> dict(summary)    幂等: 未在录返回 {recording: False}
    status()                       -> dict             当前活跃录制列表
    stop_all()                     -> None             生命周期关停 (lifespan shutdown)

模块级回放:
    replay(avi_path, stride=1) -> Iterator[(frame_bgr, ts)]   重开 AVI + jsonl 逐帧 (帧, 时间戳);
                                                              stride>1 = 倍速抽帧 (跳过帧不解码)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Iterator, Optional, Union

import cv2
import httpx
import numpy as np

log = logging.getLogger(__name__)

_FOURCC = "MJPG"


def _default_recordings_dir() -> Path:
    """默认录制根目录 = <repo_root>/data/water_level_recordings (照 photoscrape case_dir 范式)。"""
    return Path(__file__).resolve().parents[2] / "data" / "water_level_recordings"


def _sidecar_paths(avi_path: Union[str, Path]) -> tuple[Path, Path]:
    """由 AVI 路径推出旁挂 (<stem>.jsonl, <stem>.meta.json)。"""
    avi_path = Path(avi_path)
    stem = avi_path.with_suffix("")            # 去掉 .avi
    jsonl_path = stem.with_suffix(".jsonl")
    meta_path = Path(str(stem) + ".meta.json")  # with_suffix 不接受双点后缀, 手拼
    return jsonl_path, meta_path


class _Recording:
    """单条录制的运行期句柄 (写盘资源 + 后台线程 + 计数)。"""

    __slots__ = ("channel", "sample_id", "avi_path", "jsonl_path", "meta_path",
                 "writer", "jsonl_fp", "thread", "stop_event", "started_at",
                 "frame_count", "calibration_snapshot")

    def __init__(self, channel: int, sample_id: Optional[str],
                 avi_path: Path, jsonl_path: Path, meta_path: Path,
                 writer, jsonl_fp, calibration_snapshot: Optional[dict]):
        self.channel = channel
        self.sample_id = sample_id
        self.avi_path = avi_path
        self.jsonl_path = jsonl_path
        self.meta_path = meta_path
        self.writer = writer
        self.jsonl_fp = jsonl_fp
        self.calibration_snapshot = calibration_snapshot
        self.stop_event = threading.Event()
        self.started_at = time.time()
        self.frame_count = 0
        self.thread: Optional[threading.Thread] = None


class WaterLevelRecorder:
    """上位机单通道原始录制器 (一通道一线程)。

    用法:
        rec = WaterLevelRecorder(orangepi_ip, stream_port, cap_fps=10,
                                 cap_width=640, cap_height=480)
        path = rec.start(1, sample_id="run_0706")
        ...
        summary = rec.stop(1)
        rec.stop_all()   # 生命周期关停
    """

    def __init__(self, orangepi_ip: str, stream_port: int, *,
                 cap_fps: Union[int, float] = 10, cap_width: int = 640,
                 cap_height: int = 480,
                 recordings_dir: Optional[Union[str, Path]] = None,
                 grab_timeout: float = 3.0,
                 calibration_snapshot: Optional[Callable[[int], Optional[dict]]] = None):
        self._ip = orangepi_ip
        self._port = stream_port
        self._cap_fps = float(cap_fps) if cap_fps and cap_fps > 0 else 10.0
        self._width = int(cap_width)
        self._height = int(cap_height)
        self._recordings_dir = (Path(recordings_dir) if recordings_dir
                                else _default_recordings_dir())
        self._grab_timeout = grab_timeout
        # 注入的 per-channel 标定只读快照函数 (通常读运行中的 detect service); 缺则 meta 里为 null
        self._calib_snapshot_fn = calibration_snapshot
        self._recordings: dict[int, _Recording] = {}
        self._lock = threading.Lock()

    # ---- 内部接口 ----
    def start(self, channel: int, sample_id: Optional[str] = None) -> str:
        """开始录制某通道, 返回 AVI 绝对路径 (str)。已在录该通道 → 幂等返回既有路径。

        VideoWriter 打不开 (缺编解码) → 抛 RuntimeError (安装期错误, 由路由映射 500);
        运行期坏帧不抛 (后台循环吞掉)。
        """
        channel = int(channel)
        with self._lock:
            existing = self._recordings.get(channel)
            if existing is not None:
                log.info("[WL-REC] CH%s 已在录制, 幂等返回既有路径 %s", channel, existing.avi_path)
                return str(existing.avi_path)
            rec = self._open_recording(channel, sample_id)
            self._recordings[channel] = rec
        rec.thread = threading.Thread(
            target=self._loop, args=(rec,), name=f"wl-record-ch{channel}", daemon=True)
        rec.thread.start()
        log.info("[WL-REC] CH%s 录制已启动 → %s (源 http://%s:%s/frame/ch%s, %sx%s@%.0ffps)",
                 channel, rec.avi_path, self._ip, self._port, channel,
                 self._width, self._height, self._cap_fps)
        return str(rec.avi_path)

    def stop(self, channel: int) -> dict:
        """停止录制某通道, 返回汇总 dict。未在录该通道 → 幂等返回 {recording: False, stopped: False}。"""
        channel = int(channel)
        with self._lock:
            rec = self._recordings.pop(channel, None)
        if rec is None:
            return {"channel": channel, "recording": False, "stopped": False}
        rec.stop_event.set()
        if rec.thread is not None:
            rec.thread.join(timeout=self._grab_timeout + 5.0)
            if rec.thread.is_alive():
                log.warning("[WL-REC] CH%s 录制线程未在超时内退出, 强制收尾", channel)
        return self._finalize(rec)

    def status(self) -> dict:
        """当前活跃录制的只读快照。"""
        now = time.time()
        with self._lock:
            recs = list(self._recordings.values())
        return {"recordings": [
            {
                "channel": r.channel,
                "sample_id": r.sample_id,
                "path": str(r.avi_path),
                "frame_count": r.frame_count,
                "started_at": r.started_at,
                "elapsed_s": round(now - r.started_at, 3),
                "recording": True,
            }
            for r in sorted(recs, key=lambda r: r.channel)
        ]}

    def stop_all(self) -> None:
        """关停全部活跃录制 (生命周期 shutdown 调用; 永不抛)。"""
        with self._lock:
            channels = sorted(self._recordings.keys())
        for ch in channels:
            try:
                self.stop(ch)
            except Exception:
                log.exception("[WL-REC] CH%s 关停失败", ch)

    # ---- 内部: 落盘资源 ----
    def _open_recording(self, channel: int, sample_id: Optional[str]) -> _Recording:
        ts = time.strftime("%Y%m%d_%H%M%S")
        sub = sample_id if sample_id else "adhoc"
        out_dir = self._recordings_dir / sub
        out_dir.mkdir(parents=True, exist_ok=True)
        avi_path = out_dir / f"ch{channel}_{ts}.avi"
        jsonl_path, meta_path = _sidecar_paths(avi_path)

        fourcc = cv2.VideoWriter_fourcc(*_FOURCC)
        writer = cv2.VideoWriter(str(avi_path), fourcc, self._cap_fps,
                                 (self._width, self._height))
        if not writer.isOpened():
            raise RuntimeError(
                f"CH{channel} VideoWriter 打不开 (fourcc={_FOURCC}, {avi_path})")
        jsonl_fp = open(jsonl_path, "w", encoding="utf-8")

        # 起始时刻的标定快照 (当时标定), 写进 meta; 取不到 → null
        calib = None
        if self._calib_snapshot_fn is not None:
            try:
                calib = self._calib_snapshot_fn(channel)
            except Exception:
                log.exception("[WL-REC] CH%s 取标定快照失败, 记 null", channel)
                calib = None
        return _Recording(channel, sample_id, avi_path, jsonl_path, meta_path,
                          writer, jsonl_fp, calib)

    def _finalize(self, rec: _Recording) -> dict:
        """线程已 join 后调用: 释放写盘资源 + 落 meta.json + 回汇总。"""
        try:
            rec.writer.release()
        except Exception:
            log.exception("[WL-REC] CH%s VideoWriter 释放失败", rec.channel)
        try:
            rec.jsonl_fp.close()
        except Exception:
            log.exception("[WL-REC] CH%s jsonl 关闭失败", rec.channel)
        stopped_at = time.time()
        meta = {
            "channel": rec.channel,
            "sample_id": rec.sample_id,
            "width": self._width,
            "height": self._height,
            "fps": self._cap_fps,
            "started_at": rec.started_at,
            "stopped_at": stopped_at,
            "frame_count": rec.frame_count,
            "calibration_snapshot": rec.calibration_snapshot,
        }
        try:
            rec.meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            log.exception("[WL-REC] CH%s meta.json 写入失败", rec.channel)
        summary = dict(meta)
        summary["path"] = str(rec.avi_path)
        summary["duration_s"] = round(stopped_at - rec.started_at, 3)
        summary["recording"] = False
        summary["stopped"] = True
        log.info("[WL-REC] CH%s 录制已停止: %d 帧, %.1fs → %s",
                 rec.channel, rec.frame_count, summary["duration_s"], rec.avi_path)
        return summary

    # ---- 内部: 后台循环 (永不抛) ----
    def _loop(self, rec: _Recording) -> None:
        interval = 1.0 / self._cap_fps
        try:
            with httpx.Client(timeout=self._grab_timeout, trust_env=False) as client:
                while not rec.stop_event.is_set():
                    t0 = time.time()
                    try:
                        frame = self._grab(client, rec.channel)
                        if frame is not None:
                            self._write_frame(rec, frame)
                    except Exception:
                        log.exception("[WL-REC] CH%s 录制帧异常, 丢帧继续", rec.channel)
                    wait = interval - (time.time() - t0)
                    if wait > 0:
                        rec.stop_event.wait(wait)   # 可被 stop 打断的节拍睡眠
        except Exception:
            log.exception("[WL-REC] CH%s 录制循环异常退出", rec.channel)

    def _grab(self, client: httpx.Client, ch: int):
        """GET /frame/ch{N} → 解码为 BGR; 失败/非 200/损坏返回 None (照 service._grab 同款幂等)。"""
        url = f"http://{self._ip}:{self._port}/frame/ch{ch}"
        try:
            resp = client.get(url)
        except httpx.HTTPError as exc:
            log.debug("[WL-REC] CH%s 拉帧失败: %s", ch, exc)
            return None
        if resp.status_code != 200:
            return None
        arr = np.frombuffer(resp.content, np.uint8)
        if arr.size == 0:
            return None
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def _write_frame(self, rec: _Recording, frame) -> None:
        """写一帧到 AVI + 追加一行墙钟时间戳。帧尺寸与采集档不一致 → resize 到采集档保 AVI 一致。"""
        if frame is None:
            return
        h, w = frame.shape[:2]
        if (w, h) != (self._width, self._height):
            frame = cv2.resize(frame, (self._width, self._height))
        rec.writer.write(frame)
        rec.jsonl_fp.write(json.dumps({"i": rec.frame_count, "t": time.time()}) + "\n")
        rec.jsonl_fp.flush()
        rec.frame_count += 1


# ====================================================================
# 模块级回放 (离线整定地基: 重开录像喂回检测器)
# ====================================================================
def replay(avi_path: Union[str, Path],
           stride: int = 1) -> Iterator[tuple[np.ndarray, Optional[float]]]:
    """重开录制产物, 逐帧 yield (frame_bgr, timestamp)。

    帧取自 AVI (cv2.VideoCapture), 时间戳按帧序取自旁挂 jsonl (缺行 → None)。
    stride>1 = 倍速抽帧: 每 stride 帧 yield 1 帧 (帧 0, stride, 2*stride, ...),
    跳过的帧只 grab() 不 retrieve, 省掉 MJPG 解码; 时间戳仍按真实帧序对齐。
    stride=1 时 yield 帧数 == AVI 可解码帧数。供离线用真实录像重跑 detect_level 整定判据。
    """
    stride = max(1, int(stride))
    avi_path = Path(avi_path)
    jsonl_path, _ = _sidecar_paths(avi_path)
    timestamps: list[Optional[float]] = []
    if jsonl_path.is_file():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                timestamps.append(float(json.loads(line).get("t")))
            except (json.JSONDecodeError, TypeError, ValueError):
                timestamps.append(None)
    cap = cv2.VideoCapture(str(avi_path))
    try:
        idx = 0
        while True:
            if idx % stride:
                if not cap.grab():
                    break
                idx += 1
                continue
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            ts = timestamps[idx] if idx < len(timestamps) else None
            yield frame, ts
            idx += 1
    finally:
        cap.release()
