"""Offline tests for the Sampling PLC L2 action client."""

from __future__ import annotations

import asyncio
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from core.plc_action_client import (
    PLCActionClient,
    PLCActionOutcomeUnknown,
    PLCActionState,
)


class FakePLC:
    def __init__(self, *, delay: float = 0.001) -> None:
        self.delay = delay
        self.values = {
            "Sampling_ControlMode": 1,
            "Sampling_L2_ActionCode": 0,
            "Sampling_L2_RequestSeq": 0,
            "Sampling_L2_Start": False,
            "Sampling_L2_Reset": False,
            "Sampling_L2_State": 0,
            "Sampling_L2_ActiveCode": 0,
            "Sampling_L2_AcceptedSeq": 0,
            "Sampling_L2_CompletedSeq": 0,
            "Sampling_L2_Step": 0,
            "Sampling_L2_ErrorCode": 0,
            "Sampling_L2_SafeState": 10,
            "Sampling_L2_Retryable": False,
        }
        self.params = {}
        self.started_sequences = []
        self.fail_start_after_accept = False
        self.return_old_terminal = False

    async def read_variable(self, name: str):
        return self.values[name]

    async def write_variable(self, name: str, value) -> None:
        previous = self.values.get(name)
        self.values[name] = value
        if name == "Sampling_L2_Start" and value and not previous:
            seq = int(self.values["Sampling_L2_RequestSeq"])
            code = int(self.values["Sampling_L2_ActionCode"])
            self.started_sequences.append(seq)
            if self.return_old_terminal:
                self.values["Sampling_L2_State"] = 20
                return
            self.values["Sampling_L2_State"] = 10
            self.values["Sampling_L2_ActiveCode"] = code
            self.values["Sampling_L2_AcceptedSeq"] = seq
            self.values["Sampling_L2_Step"] = code
            asyncio.create_task(self._complete(seq))
            if self.fail_start_after_accept:
                self.fail_start_after_accept = False
                raise ConnectionError("simulated ambiguous Start write")
        if name == "Sampling_L2_Start" and not value:
            if self.values["Sampling_L2_State"] in {20, 30, 40, 50}:
                self.values["Sampling_L2_State"] = 0
                self.values["Sampling_L2_ActiveCode"] = 0
                self.values["Sampling_L2_Step"] = 0

    async def send_recipe_params(self, params: dict) -> None:
        self.params.update(params)

    async def _complete(self, seq: int) -> None:
        await asyncio.sleep(self.delay)
        self.values["Sampling_L2_CompletedSeq"] = seq
        self.values["Sampling_L2_State"] = 20


class RailFakePLC:
    """地轨 L2 通道仿真: 无 ControlMode/SafeState 门控的伺服绝对移动。"""

    def __init__(self, *, delay: float = 0.001) -> None:
        self.delay = delay
        self.values = {
            "Rail_L2_ActionCode": 0,
            "Rail_L2_RequestSeq": 0,
            "Rail_L2_Start": False,
            "Rail_L2_Reset": False,
            "Rail_L2_State": 0,
            "Rail_L2_ActiveCode": 0,
            "Rail_L2_AcceptedSeq": 0,
            "Rail_L2_CompletedSeq": 0,
            "Rail_L2_Step": 0,
            "Rail_L2_ErrorCode": 0,
            "Rail_L2_SafeState": 0,
            "Rail_L2_Retryable": False,
        }
        self.started: list[tuple[int, int]] = []

    async def read_variable(self, name: str):
        return self.values[name]

    async def write_variable(self, name: str, value) -> None:
        previous = self.values.get(name)
        self.values[name] = value
        if name == "Rail_L2_Start" and value and not previous:
            seq = int(self.values["Rail_L2_RequestSeq"])
            code = int(self.values["Rail_L2_ActionCode"])
            self.started.append((seq, code))
            self.values["Rail_L2_State"] = 10
            self.values["Rail_L2_ActiveCode"] = code
            self.values["Rail_L2_AcceptedSeq"] = seq
            self.values["Rail_L2_Step"] = code
            asyncio.create_task(self._complete(seq))
        if name == "Rail_L2_Start" and not value:
            if self.values["Rail_L2_State"] in {20, 30, 40, 50}:
                self.values["Rail_L2_State"] = 0
                self.values["Rail_L2_ActiveCode"] = 0
                self.values["Rail_L2_Step"] = 0

    async def send_recipe_params(self, params: dict) -> None:
        pass

    async def _complete(self, seq: int) -> None:
        await asyncio.sleep(self.delay)
        self.values["Rail_L2_CompletedSeq"] = seq
        self.values["Rail_L2_State"] = 20


class RailL2ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_rail_move_executes_by_position_code(self) -> None:
        plc = RailFakePLC()
        client = PLCActionClient(plc, poll_interval=0.001)
        result = await client.execute("rail", 5)  # 5 = 展开缸位
        self.assertEqual(result.state, PLCActionState.DONE)
        self.assertEqual(result.station, "Rail")
        self.assertEqual(result.action_code, 5)
        self.assertEqual(plc.started, [(1, 5)])

    async def test_rail_rejects_invalid_position_code(self) -> None:
        plc = RailFakePLC()
        client = PLCActionClient(plc, poll_interval=0.001)
        with self.assertRaises(ValueError):
            await client.execute("rail", 9)
        self.assertEqual(plc.started, [])


class SamplingL2ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_monotonic_sequences_and_params(self) -> None:
        plc = FakePLC()
        client = PLCActionClient(plc, poll_interval=0.001)
        first = await client.execute(
            "sampling", "init", {"Sampling_clean_count": 3}
        )
        second = await client.execute("spotting", "clean")
        self.assertEqual(first.state, PLCActionState.DONE)
        self.assertEqual((first.request_seq, second.request_seq), (1, 2))
        self.assertEqual(plc.started_sequences, [1, 2])
        self.assertEqual(plc.params["Sampling_clean_count"], 3)

    async def test_ambiguous_start_queries_same_sequence(self) -> None:
        plc = FakePLC()
        plc.fail_start_after_accept = True
        client = PLCActionClient(plc, poll_interval=0.001)
        result = await client.execute("sampling", "init")
        self.assertTrue(result.ok)
        self.assertEqual(plc.started_sequences, [1])

    async def test_old_terminal_result_is_not_accepted(self) -> None:
        plc = FakePLC()
        plc.values["Sampling_L2_CompletedSeq"] = 7
        plc.return_old_terminal = True
        client = PLCActionClient(plc, poll_interval=0.001)
        with self.assertRaises(PLCActionOutcomeUnknown):
            await client.execute("sampling", "init", timeout=0.02)
        self.assertEqual(plc.started_sequences, [8])

    async def test_cancel_waits_for_action_cleanup(self) -> None:
        plc = FakePLC(delay=0.03)
        client = PLCActionClient(plc, poll_interval=0.001)
        task = asyncio.create_task(client.execute("sampling", "init"))
        deadline = asyncio.get_running_loop().time() + 1.0
        while not plc.started_sequences:
            if asyncio.get_running_loop().time() >= deadline:
                self.fail("Sampling L2 action did not start")
            await asyncio.sleep(0.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(plc.values["Sampling_L2_State"], 0)
        self.assertFalse(plc.values["Sampling_L2_Start"])
        self.assertEqual(plc.started_sequences, [1])

    async def test_control_mode_must_be_l2(self) -> None:
        plc = FakePLC()
        plc.values["Sampling_ControlMode"] = 0
        client = PLCActionClient(plc, poll_interval=0.001)
        with self.assertRaisesRegex(RuntimeError, "ControlMode"):
            await client.execute("sampling", "init")
        self.assertEqual(plc.started_sequences, [])


if __name__ == "__main__":
    unittest.main()
