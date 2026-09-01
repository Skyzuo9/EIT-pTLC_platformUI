#!/usr/bin/env python3
"""L2 等待循环 None 守卫离线测试 (#4)
===================================
功能:
    镜像 seeding/refresh 吞过瞬时首读失败时, 驱动镜像可能返回 None。验证 L2 等待循环
    对快照字段做 None 守卫: 不再 int(None) 抛 TypeError 逃逸看门狗, 而是落到停滞分支——
      - 首轮 None、次轮正常终态  → 正常完成, 不抛 TypeError;
      - 持续 None              → 停滞看门狗判 PLCActionOutcomeUnknown (非 TypeError)。

用 FakeDriver 直驱 _execute_one: read_variable 走 last-write-wins (State 恒 IDLE),
cached_many 按预设脚本逐轮给出 (None / 终态), 两路互不干扰。
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.plc_controller import (  # noqa: E402
    PLCActionOutcomeUnknown,
    PLCActionState,
    PlcController,
)

_L2_FIELDS = ("State", "ActiveCode", "AcceptedSeq", "CompletedSeq",
              "Step", "ErrorCode", "SafeState", "Retryable")


def _none_snap() -> dict:
    return {f: None for f in _L2_FIELDS}


def _done_snap(seq: int) -> dict:
    # CompletedSeq==seq + State=DONE → 终态命中
    return {
        "State": int(PLCActionState.DONE), "ActiveCode": 10,
        "AcceptedSeq": seq, "CompletedSeq": seq,
        "Step": 0, "ErrorCode": 0, "SafeState": 0, "Retryable": False,
    }


class FakeDriver:
    """最小驱动: 满足 _execute_one 的启动时序 + 看门狗等待循环。

    - read_variable: last-write-wins (未写过的字段读 0); State 恒 IDLE(0)。
    - cached_many: 按 snap_script 逐轮返回 (耗尽后恒返回最后一个)。
    """

    def __init__(self, snap_script: list[dict]) -> None:
        self._store: dict[str, object] = {}
        self._script = snap_script
        self._token = 0

    async def write_variable(self, name: str, value) -> None:
        self._store[name] = value

    async def read_many(self, names: list[str]) -> list:
        """批量读 (替身实现: 逐点转 read_variable, 完整保留本替身模拟的断链/静默语义)."""
        return [await self.read_variable(n) for n in names]

    async def read_variable(self, name: str):
        if name.endswith("_L2_State"):
            return 0  # 恒 IDLE: 满足 _prepare_idle / 收尾 snapshot
        return self._store.get(name, 0)

    async def write_many(self, params: dict) -> None:
        self._store.update(params)

    async def add_subscription(self, names) -> None:
        return None

    async def refresh_mirror(self, names) -> None:
        return None

    def cached_many(self, names) -> dict:
        snap = self._script[0] if len(self._script) == 1 else self._script.pop(0)
        prefix = names[0].rsplit("_L2_", 1)[0]
        return {f"{prefix}_L2_{f}": snap[f] for f in _L2_FIELDS}

    def change_token(self) -> int:
        return self._token

    async def wait_change(self, token) -> None:
        self._token += 1
        await asyncio.sleep(0.01)


async def _run_first_none_then_done() -> str:
    drv = FakeDriver([_none_snap(), _done_snap(1)])
    ctrl = PlcController(drv, poll_interval=0.02, action_timeout=3.0, stall_timeout=1.0)
    result = await ctrl.execute("sampling", 10)
    assert result.ok and result.state is PLCActionState.DONE, str(result)
    return "ok"


async def _run_persistent_none() -> str:
    drv = FakeDriver([_none_snap()])  # 单元素脚本 → 恒 None
    ctrl = PlcController(drv, poll_interval=0.02, action_timeout=3.0, stall_timeout=0.3)
    try:
        await ctrl.execute("sampling", 10)
    except PLCActionOutcomeUnknown:
        return "unknown"
    return "no-raise"


class L2NoneGuardTests(unittest.TestCase):
    def test_first_none_then_done_no_typeerror(self) -> None:
        self.assertEqual(asyncio.run(_run_first_none_then_done()), "ok")

    def test_persistent_none_raises_outcome_unknown(self) -> None:
        # 持续读不到镜像 → 停滞看门狗判 PLCActionOutcomeUnknown, 不是 TypeError
        self.assertEqual(asyncio.run(_run_persistent_none()), "unknown")


if __name__ == "__main__":
    unittest.main()
