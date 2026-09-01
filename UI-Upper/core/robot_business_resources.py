"""In-process business-resource leases for robot route transactions."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Mapping

from .robot_route import ResourceRef


class BusinessResourceBusy(RuntimeError):
    pass


class RobotBusinessResourceLedger:
    """Acquire route resources in a stable order and hold them to route exit.

    This ledger coordinates business transactions inside one upper-computer
    process. It is intentionally not a cross-process or multi-client robot lock.
    """

    def __init__(self, *, acquire_timeout_s: float | None = None) -> None:
        self.acquire_timeout_s = acquire_timeout_s
        self._guard = threading.Lock()
        self._locks: dict[tuple[str, str], threading.RLock] = {}
        self._owners: dict[tuple[str, str], int] = {}

    @contextmanager
    def lease(
        self,
        resources: tuple[ResourceRef, ...],
        business_params: Mapping[str, object],
    ) -> Iterator[None]:
        keys = tuple(sorted({
            (item.resource_type, repr(item.resource_id))
            for item in resources
        }))
        locks = [(key, self._lock_for(key)) for key in keys]
        acquired: list[tuple[tuple[str, str], threading.RLock]] = []
        owner = threading.get_ident()
        try:
            for key, lock in locks:
                if self.acquire_timeout_s is None:
                    ok = lock.acquire()
                else:
                    ok = lock.acquire(timeout=self.acquire_timeout_s)
                if not ok:
                    raise BusinessResourceBusy(
                        f"timed out acquiring business resource {key}"
                    )
                acquired.append((key, lock))
                with self._guard:
                    self._owners[key] = owner
            yield
        finally:
            for key, lock in reversed(acquired):
                with self._guard:
                    self._owners.pop(key, None)
                lock.release()

    def held_resources(self) -> tuple[tuple[str, str], ...]:
        with self._guard:
            return tuple(sorted(self._owners))

    def _lock_for(self, key: tuple[str, str]) -> threading.RLock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
            return lock
