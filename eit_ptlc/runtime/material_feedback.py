"""PTLC 物料账本到数字孪生的只读快照发布器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

log = logging.getLogger(__name__)


def material_state_event(snapshot: dict, *, ts: float | None = None,
                         seq: int = 0, initial: bool = False) -> dict:
    """把 ``MaterialStore.grid`` 快照包装成 WebSocket 事件，不改动原快照。"""
    return {
        "type": "material_state",
        **snapshot,
        "ts": time.time() if ts is None else float(ts),
        "seq": int(seq),
        "initial": bool(initial),
    }


def _fingerprint(snapshot: dict) -> str:
    payload = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def material_feedback_loop(
    material_store,
    bus,
    stop: asyncio.Event,
    *,
    interval: float = 0.5,
    heartbeat: float = 5.0,
) -> None:
    """按变更发布完整物料快照；周期轮询本地 SQLite，不产生并发读取积压。"""
    if interval <= 0 or heartbeat <= 0:
        raise ValueError("物料反馈周期与心跳必须为正数")

    loop = asyncio.get_running_loop()
    last_digest = ""
    last_publish = 0.0
    seq = 0
    log.info("[material-realtime] 启动: 检查 %.1fHz, 心跳 %.1fs", 1.0 / interval, heartbeat)

    while not stop.is_set():
        started = loop.time()
        try:
            snapshot = await asyncio.to_thread(material_store.grid)
            digest = _fingerprint(snapshot)
            now = time.time()
            if digest != last_digest or now - last_publish >= heartbeat:
                seq += 1
                bus.publish(material_state_event(snapshot, ts=now, seq=seq))
                last_digest = digest
                last_publish = now
        except Exception:
            # 账本短暂被占用或关闭只影响本轮，不能拖垮机器人/PLC 的实时反馈任务。
            log.exception("[material-realtime] 只读快照失败")

        elapsed = loop.time() - started
        timeout = max(0.0, interval - elapsed)
        try:
            await asyncio.wait_for(stop.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    log.info("[material-realtime] 退出")
