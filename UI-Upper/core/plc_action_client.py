"""PLC L2 atomic-action client.

After a connection loss, query the original sequence only. Never automatically
resend a physical action whose outcome is uncertain.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Mapping

from core.plc_client import PLCClient

log = logging.getLogger(__name__)


class PLCActionState(IntEnum):
    IDLE = 0
    RUNNING = 10
    DONE = 20
    REJECTED = 30
    ERROR = 40
    INTERRUPTED = 50


class PLCActionSafeState(IntEnum):
    UNKNOWN = 0
    READY = 10
    PLATE_HELD_UNVERIFIED = 20
    RELEASE_READY_UNVERIFIED = 30
    RECOVERY_REQUIRED = 90


class SamplingAction(IntEnum):
    INIT = 10
    CLEAN = 20
    PREPARE_FLUID = 30
    PREPARE_PLATE_RECEIVE = 40
    CLAMP_PLATE = 50
    ASPIRATE_SAMPLE = 60
    DISPENSE_SAMPLE = 70
    PREPARE_PLATE_RELEASE = 80
    FINISH_PLATE_RELEASE = 90


SAMPLING_ACTION_NAMES = {
    "init": SamplingAction.INIT,
    "clean": SamplingAction.CLEAN,
    "prepare-fluid": SamplingAction.PREPARE_FLUID,
    "prepare-plate-receive": SamplingAction.PREPARE_PLATE_RECEIVE,
    "clamp-plate": SamplingAction.CLAMP_PLATE,
    "aspirate-sample": SamplingAction.ASPIRATE_SAMPLE,
    "dispense-sample": SamplingAction.DISPENSE_SAMPLE,
    "prepare-plate-release": SamplingAction.PREPARE_PLATE_RELEASE,
    "finish-plate-release": SamplingAction.FINISH_PLATE_RELEASE,
}


class RailAction(IntEnum):
    """地轨 (地轨轴11Y) 工位位置原子动作码, 对齐 legacy HMI_地轨轴11Y.position[1..6]。"""

    SPOTTING = 1     # 上样点样位
    SCRAPE = 2       # 刮板拍照位
    COLLECT = 3      # 收集工位
    TOOL_CHANGE = 4  # 取工具位
    TANK = 5         # 展开缸位
    GROUP = 6        # 取放收集组位


@dataclass(frozen=True)
class PLCActionResult:
    station: str
    action_code: int
    request_seq: int
    state: PLCActionState
    error_code: int
    safe_state: PLCActionSafeState
    retryable: bool
    step: int

    @property
    def ok(self) -> bool:
        return self.state is PLCActionState.DONE


class PLCActionError(RuntimeError):
    def __init__(self, result: PLCActionResult) -> None:
        self.result = result
        super().__init__(
            f"PLC L2 action failed: station={result.station} "
            f"action={result.action_code} seq={result.request_seq} "
            f"state={result.state.name} error={result.error_code}"
        )


class PLCActionOutcomeUnknown(RuntimeError):
    """The caller must not automatically resend this action."""


class PLCActionClient:
    _TERMINAL = {
        PLCActionState.DONE,
        PLCActionState.REJECTED,
        PLCActionState.ERROR,
        PLCActionState.INTERRUPTED,
    }

    def __init__(
        self,
        plc: PLCClient,
        *,
        poll_interval: float = 0.05,
        action_timeout: float = 300.0,
    ) -> None:
        self._plc = plc
        self._poll_interval = float(poll_interval)
        self._action_timeout = float(action_timeout)
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_seq: dict[str, int] = {}

    async def execute(
        self,
        station: str,
        action: int | str | IntEnum,
        params: Mapping[str, object] | None = None,
        *,
        timeout: float | None = None,
    ) -> PLCActionResult:
        prefix = self._prefix(station)
        action_code = self._action_code(prefix, action)
        async with self._locks.setdefault(prefix, asyncio.Lock()):
            seq = await self._allocate_seq(prefix)
            worker = asyncio.create_task(
                self._execute_one(
                    prefix, action_code, seq, dict(params or {}), timeout
                ),
                name=f"plc-action-{prefix}-{seq}",
            )
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Let an accepted physical action finish before propagating cancel.
                try:
                    await asyncio.shield(worker)
                except Exception:
                    log.exception(
                        "[%s L2] action cleanup after cancellation failed seq=%d",
                        prefix,
                        seq,
                    )
                raise

    async def reset(self, station: str, *, pulse_s: float = 0.1) -> None:
        prefix = self._prefix(station)
        await self._plc.write_variable(f"{prefix}_L2_Reset", True)
        await asyncio.sleep(pulse_s)
        await self._plc.write_variable(f"{prefix}_L2_Reset", False)

    async def snapshot(self, station: str) -> dict[str, object]:
        prefix = self._prefix(station)
        fields = (
            "State",
            "ActiveCode",
            "AcceptedSeq",
            "CompletedSeq",
            "Step",
            "ErrorCode",
            "SafeState",
            "Retryable",
        )
        return {
            field: await self._plc.read_variable(f"{prefix}_L2_{field}")
            for field in fields
        }

    async def _execute_one(
        self,
        prefix: str,
        action_code: int,
        seq: int,
        params: dict[str, object],
        timeout: float | None,
    ) -> PLCActionResult:
        await self._prepare_idle(prefix)
        if params:
            await self._plc.send_recipe_params(params)
        await self._plc.write_variable(f"{prefix}_L2_ActionCode", action_code)
        await self._plc.write_variable(f"{prefix}_L2_RequestSeq", seq)
        read_action = int(
            await self._plc.read_variable(f"{prefix}_L2_ActionCode")
        )
        read_seq = int(
            await self._plc.read_variable(f"{prefix}_L2_RequestSeq")
        )
        if (read_action, read_seq) != (action_code, seq):
            raise RuntimeError(
                f"{prefix} L2 write-verify failed: "
                f"action={read_action}/{action_code}, seq={read_seq}/{seq}"
            )

        start_write_uncertain = False
        try:
            await self._plc.write_variable(f"{prefix}_L2_Start", True)
        except Exception:
            # The request may have reached the PLC. Query the same sequence.
            start_write_uncertain = True
            log.warning(
                "[%s L2] Start result uncertain; query original seq=%d",
                prefix,
                seq,
            )

        deadline = asyncio.get_running_loop().time() + (
            self._action_timeout if timeout is None else float(timeout)
        )
        accepted = False
        try:
            while True:
                snap = await self.snapshot(prefix)
                state = PLCActionState(int(snap["State"]))
                accepted_seq = int(snap["AcceptedSeq"])
                completed_seq = int(snap["CompletedSeq"])
                accepted = accepted or accepted_seq == seq

                if completed_seq == seq and state in self._TERMINAL:
                    result = self._result(
                        prefix, action_code, seq, state, snap
                    )
                    if result.ok:
                        return result
                    raise PLCActionError(result)
                if state in self._TERMINAL and completed_seq != seq:
                    raise PLCActionOutcomeUnknown(
                        f"{prefix} L2 terminal result belongs to old seq "
                        f"{completed_seq}, expected {seq}; not resent"
                    )
                if (
                    start_write_uncertain
                    and not accepted
                    and state is PLCActionState.IDLE
                ):
                    raise PLCActionOutcomeUnknown(
                        f"{prefix} L2 cannot prove seq {seq} was accepted; "
                        "not resent"
                    )
                if asyncio.get_running_loop().time() >= deadline:
                    qualifier = "accepted" if accepted else "acceptance unknown"
                    raise PLCActionOutcomeUnknown(
                        f"{prefix} L2 timeout for seq {seq} "
                        f"({qualifier}); not resent"
                    )
                await asyncio.sleep(self._poll_interval)
        finally:
            # Preserve evidence when the result is uncertain.
            try:
                snap = await self.snapshot(prefix)
                terminal = PLCActionState(int(snap["State"])) in self._TERMINAL
                if int(snap["CompletedSeq"]) == seq and terminal:
                    await self._plc.write_variable(f"{prefix}_L2_Start", False)
                    await self._wait_idle(prefix, timeout=2.0)
            except Exception:
                log.warning(
                    "[%s L2] terminal falling-edge cleanup unconfirmed seq=%d",
                    prefix,
                    seq,
                    exc_info=True,
                )

    async def _prepare_idle(self, prefix: str) -> None:
        await self._plc.write_variable(f"{prefix}_L2_Start", False)
        await self._wait_idle(prefix, timeout=2.0)
        if prefix == "Sampling":
            mode = int(
                await self._plc.read_variable("Sampling_ControlMode")
            )
            if mode != 1:
                raise RuntimeError(
                    "Sampling_ControlMode is not L2 (expected 1)"
                )

    async def _wait_idle(self, prefix: str, *, timeout: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            state = PLCActionState(
                int(await self._plc.read_variable(f"{prefix}_L2_State"))
            )
            if state is PLCActionState.IDLE:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"{prefix} L2 did not return to IDLE")
            await asyncio.sleep(self._poll_interval)

    async def _allocate_seq(self, prefix: str) -> int:
        if prefix not in self._next_seq:
            values = await asyncio.gather(
                self._plc.read_variable(f"{prefix}_L2_RequestSeq"),
                self._plc.read_variable(f"{prefix}_L2_AcceptedSeq"),
                self._plc.read_variable(f"{prefix}_L2_CompletedSeq"),
            )
            self._next_seq[prefix] = max(int(v) for v in values) + 1
        seq = self._next_seq[prefix]
        if seq > 2_147_483_647:
            raise OverflowError(f"{prefix} L2 request sequence exhausted")
        self._next_seq[prefix] = seq + 1
        return seq

    @staticmethod
    def _prefix(station: str) -> str:
        normalized = station.strip().lower()
        if normalized in {"sampling", "spotting"}:
            return "Sampling"
        if normalized == "rail":
            return "Rail"
        raise KeyError(f"unsupported PLC L2 station: {station}")

    @staticmethod
    def _action_code(prefix: str, action: int | str | IntEnum) -> int:
        if isinstance(action, str):
            if prefix == "Sampling":
                try:
                    return int(SAMPLING_ACTION_NAMES[action.strip().lower()])
                except KeyError as exc:
                    raise KeyError(
                        f"unknown {prefix} L2 action: {action}"
                    ) from exc
            raise KeyError(f"unknown {prefix} L2 action: {action}")
        code = int(action)
        if (
            prefix == "Sampling"
            and code not in {int(x) for x in SamplingAction}
        ):
            raise ValueError(f"invalid Sampling L2 action code: {code}")
        if (
            prefix == "Rail"
            and code not in {int(x) for x in RailAction}
        ):
            raise ValueError(f"invalid Rail L2 action code: {code}")
        return code

    @staticmethod
    def _result(
        prefix: str,
        action_code: int,
        seq: int,
        state: PLCActionState,
        snap: Mapping[str, object],
    ) -> PLCActionResult:
        return PLCActionResult(
            station=prefix,
            action_code=action_code,
            request_seq=seq,
            state=state,
            error_code=int(snap["ErrorCode"]),
            safe_state=PLCActionSafeState(int(snap["SafeState"])),
            retryable=bool(snap["Retryable"]),
            step=int(snap["Step"]),
        )
