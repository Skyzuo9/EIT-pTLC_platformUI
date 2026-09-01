"""Process-wide maintenance interlock for non-idempotent PLC deployment.

The gate is intentionally synchronous and thread-safe: deployment owns it from
the first global-idle check until the replacement PLC application reports
``PLC_Ready``.  Async action entry points and the synchronous robot controller
therefore observe the same state without an event-loop hand-off window.
"""

from __future__ import annotations

import threading
import uuid
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


class MaintenanceActiveError(RuntimeError):
    """A new operation was rejected while maintenance owns the machine."""


@dataclass(frozen=True)
class MaintenanceLease:
    """Opaque ownership token; only its creator may release the gate."""

    token: str


@dataclass(frozen=True)
class ActivityLease:
    """Opaque token proving an operation registered before maintenance began."""

    token: str


class MaintenanceGate:
    """Small fail-safe ownership gate shared by deploy, actions, VM and robot."""

    def __init__(self, latch_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._lease: MaintenanceLease | None = None
        self._reason = ""
        self._activities: dict[str, str] = {}
        self._latch_path = Path(latch_path).resolve() if latch_path is not None else None
        if self._latch_path is not None and self._latch_path.exists():
            # Presence is authoritative even if a crash left truncated JSON.
            reason = "检测到上次进程遗留的 PLC 下载维护锁，等待只读安全对账"
            try:
                payload = json.loads(self._latch_path.read_text(encoding="utf-8"))
                reason = str(payload.get("reason") or reason)
            except Exception:
                pass
            self._lease = MaintenanceLease(uuid.uuid4().hex)
            self._reason = reason

    def try_acquire(self, reason: str) -> MaintenanceLease | None:
        """Atomically acquire the gate, returning ``None`` when already owned."""
        with self._lock:
            if self._lease is not None or self._activities:
                return None
            lease = MaintenanceLease(uuid.uuid4().hex)
            self._persist_latch(lease, str(reason))
            self._lease = lease
            self._reason = str(reason)
            return lease

    def release(self, lease: MaintenanceLease) -> None:
        """Release only when *lease* is the current owner."""
        with self._lock:
            if self._lease != lease:
                raise RuntimeError("维护门租约不匹配，拒绝释放")
            self._remove_latch()
            self._lease = None
            self._reason = ""

    def release_after_reconcile(self) -> None:
        """Release a persisted/restarted latch after an external read-only safety proof."""
        with self._lock:
            if self._lease is None:
                return
            if self._activities:
                raise RuntimeError("仍有活动操作，拒绝对账释放维护门")
            self._remove_latch()
            self._lease = None
            self._reason = ""

    def try_enter_activity(self, operation: str) -> ActivityLease | None:
        """Atomically register an operation iff maintenance has not started."""
        with self._lock:
            if self._lease is not None:
                return None
            lease = ActivityLease(uuid.uuid4().hex)
            self._activities[lease.token] = str(operation)
            return lease

    def leave_activity(self, lease: ActivityLease) -> None:
        """Release a previously registered operation token exactly once."""
        with self._lock:
            if lease.token not in self._activities:
                raise RuntimeError("活动租约不存在或已释放")
            self._activities.pop(lease.token)

    @property
    def active(self) -> bool:
        with self._lock:
            return self._lease is not None

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "active": self._lease is not None,
                "reason": self._reason,
                "activity_count": len(self._activities),
                "activities": list(self._activities.values()),
                "persistent": self._latch_path is not None,
                "latch_path": str(self._latch_path) if self._latch_path is not None else None,
            }

    def require_available(self, operation: str) -> None:
        """Reject a new operation while a deployment lease is active."""
        with self._lock:
            if self._lease is None:
                return
            reason = self._reason
        raise MaintenanceActiveError(
            f"PLC 下载维护态已锁定，拒绝{operation}: {reason or '等待 PLC 就绪'}"
        )

    def _persist_latch(self, lease: MaintenanceLease, reason: str) -> None:
        path = self._latch_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "token": lease.token,
            "reason": reason,
            "acquired_at": time.time(),
        }, ensure_ascii=False, sort_keys=True)
        # Exclusive creation prevents two backend processes from both owning deploy.
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise RuntimeError(f"PLC 下载维护锁已由其他进程持有: {path}") from exc

    def _remove_latch(self) -> None:
        path = self._latch_path
        if path is not None:
            path.unlink(missing_ok=True)
