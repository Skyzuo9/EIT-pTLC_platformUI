#!/usr/bin/env python3
"""PALLASVision TCP correction action offline tests."""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.executor import ActionExecutor  # noqa: E402
from eit_ptlc.action.models import ActionStatus  # noqa: E402
from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.controller.pallas_vision_client import (  # noqa: E402
    PallasVisionCfg,
    PallasVisionClient,
    PallasVisionError,
    PallasVisionResultError,
    parse_plate_offset_payload,
)
from eit_ptlc.tools.pallas_bridge import PallasBridge, create_app  # noqa: E402


class PallasVisionActionTests(unittest.TestCase):
    def test_parse_json_payload(self) -> None:
        result = parse_plate_offset_payload(b'{"HXTX":1.25,"HXTY":-0.5,"errnum":0}')
        self.assertEqual((result["dx_mm"], result["dy_mm"], result["drz_deg"], result["err"], result["valid"]),
                         (1.25, -0.5, 0.0, 0, True))

    def test_parse_key_value_and_fail_code(self) -> None:
        result = parse_plate_offset_payload('HXTX=2.0;HXTY=3.0;Angle=1.2;errnum=111')
        self.assertEqual((result["dx_mm"], result["dy_mm"], result["drz_deg"], result["err"], result["valid"]),
                         (2.0, 3.0, 1.2, 111, False))

    def test_parse_bare_fail_code_sentinel(self) -> None:
        # 现场识别失败回传裸 "111" (无分隔符): 应优雅降级为 valid=False, 交人工分支处理,
        # 而不是抛 PallasVisionResultError 让整条流程 FAILED。
        result = parse_plate_offset_payload("111")
        self.assertEqual((result["dx_mm"], result["dy_mm"], result["drz_deg"], result["err"], result["valid"]),
                         (0.0, 0.0, 0.0, 111, False))

    def test_bare_fail_code_is_config_driven(self) -> None:
        result = parse_plate_offset_payload("222", err_fail_code=222)
        self.assertEqual((result["err"], result["valid"]), (222, False))

    def test_bare_non_fail_code_still_rejected(self) -> None:
        # 不等于失败码的裸数字仍是无法解析的意外输入, 照旧抛错 (不放松错误判定)。
        with self.assertRaises(PallasVisionResultError):
            parse_plate_offset_payload("222")

    def test_parse_decimal_fail_code_sentinel(self) -> None:
        # 现场可能以小数渲染失败码 (如 "111.0"): 数值等于失败码即判识别失败哨兵, 优雅降级
        # valid=False 交人工分支, 而非 int("111.0") 抛 ValueError → 升级为 run FAILED (审阅 #4)。
        # (" 111 " 今日已能过 int strip; 一并断言锁定契约。)
        for payload in ("111.0", "111.00", " 111 "):
            with self.subTest(payload=payload):
                result = parse_plate_offset_payload(payload)
                self.assertEqual((result["err"], result["valid"]), (111, False))

    def test_near_fail_code_decimal_still_rejected(self) -> None:
        # 不放松错误判定: 数值不等于失败码 (111.9 ≠ 111) 仍是意外输入, 照旧抛错。
        with self.assertRaises(PallasVisionResultError):
            parse_plate_offset_payload("111.9")

    def test_parse_numeric_payload(self) -> None:
        result = parse_plate_offset_payload('4.5,-6.0,0.7,0')
        self.assertEqual((result["dx_mm"], result["dy_mm"], result["drz_deg"], result["valid"]),
                         (4.5, -6.0, 0.7, True))

    def test_parse_pallas_comma_payload(self) -> None:
        result = parse_plate_offset_payload('0.241873,0.991215,0.012353')
        self.assertEqual((result["dx_mm"], result["dy_mm"], result["drz_deg"], result["err"], result["valid"]),
                         (0.242, 0.991, 0.012, 0, True))

    def test_rejects_undelimited_compact_payload(self) -> None:
        with self.assertRaises(PallasVisionError):
            parse_plate_offset_payload('0.2418730.9912150.012353')

    def test_rejects_unreasonable_valid_offset(self) -> None:
        with self.assertRaises(PallasVisionError):
            parse_plate_offset_payload('0.242,9912150.012,0.0')

    def test_client_mock_returns_neutral_offset(self) -> None:
        client = PallasVisionClient(PallasVisionCfg(enabled=True, mock=True))
        result = asyncio.run(client.capture_plate_offset(apply_rz=True))
        self.assertEqual(result, {"dx_mm": 0.0, "dy_mm": 0.0, "drz_deg": 0.0,
                                  "err": 0, "valid": True, "source": "mock"})

    def test_client_wraps_pallas_trigger_with_light(self) -> None:
        calls: list[object] = []

        async def light_setter(enabled: bool) -> None:
            calls.append(enabled)

        client = PallasVisionClient(
            PallasVisionCfg(enabled=True, mock=False, result_mode="reply"),
            light_setter=light_setter,
        )

        async def fake_capture_reply() -> bytes:
            calls.append("capture")
            return b"1.0,2.0,0.3,0"

        client._capture_reply = fake_capture_reply  # type: ignore[method-assign]
        result = asyncio.run(client.capture_plate_offset(apply_rz=True))
        self.assertEqual(calls, [True, "capture", False])
        self.assertEqual((result["dx_mm"], result["dy_mm"], result["drz_deg"]), (1.0, 2.0, 0.3))

    def test_client_turns_light_off_when_pallas_trigger_fails(self) -> None:
        calls: list[object] = []

        async def light_setter(enabled: bool) -> None:
            calls.append(enabled)

        client = PallasVisionClient(
            PallasVisionCfg(enabled=True, mock=False, result_mode="reply"),
            light_setter=light_setter,
        )

        async def fake_capture_reply() -> bytes:
            calls.append("capture")
            raise RuntimeError("pallas failed")

        client._capture_reply = fake_capture_reply  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            asyncio.run(client.capture_plate_offset(apply_rz=True))
        self.assertEqual(calls, [True, "capture", False])

    def test_client_bridge_preserves_vision_failure_result(self) -> None:
        client = PallasVisionClient(
            PallasVisionCfg(enabled=True, mock=False, bridge_enabled=True, light_control_enabled=False),
        )

        async def fake_bridge_result() -> dict:
            return {"dx_mm": 2.0, "dy_mm": 3.0, "drz_deg": 1.2, "err": 111,
                    "valid": False, "raw": "HXTX=2.0;HXTY=3.0;Angle=1.2;errnum=111",
                    "source": "pallas_bridge"}

        client._capture_bridge_result = fake_bridge_result  # type: ignore[method-assign]
        result = asyncio.run(client.capture_plate_offset(apply_rz=True))
        self.assertEqual((result["valid"], result["err"], result["source"]), (False, 111, "pallas_bridge"))
        self.assertEqual((result["dx_mm"], result["dy_mm"], result["drz_deg"]), (2.0, 3.0, 1.2))

    def test_client_bridge_turns_light_off_when_bridge_fails(self) -> None:
        calls: list[object] = []

        async def light_setter(enabled: bool) -> None:
            calls.append(enabled)

        client = PallasVisionClient(
            PallasVisionCfg(enabled=True, mock=False, bridge_enabled=True),
            light_setter=light_setter,
        )

        async def fake_bridge_result() -> dict:
            calls.append("bridge")
            raise PallasVisionError("bridge offline")

        client._capture_bridge_result = fake_bridge_result  # type: ignore[method-assign]
        with self.assertRaises(PallasVisionError):
            asyncio.run(client.capture_plate_offset(apply_rz=True))
        self.assertEqual(calls, [True, "bridge", False])

    def test_client_uses_configured_offset_limits(self) -> None:
        client = PallasVisionClient(
            PallasVisionCfg(
                enabled=True,
                mock=False,
                result_mode="reply",
                light_control_enabled=False,
                max_abs_rz_deg=8.0,
            ),
        )

        async def fake_capture_reply() -> bytes:
            return b"0.1,0.2,7.0,0"

        client._capture_reply = fake_capture_reply  # type: ignore[method-assign]
        result = asyncio.run(client.capture_plate_offset(apply_rz=True))
        self.assertEqual((result["dx_mm"], result["dy_mm"], result["drz_deg"]), (0.1, 0.2, 7.0))

    def test_bridge_rejects_out_of_range_callback_without_timeout(self) -> None:
        async def run() -> tuple[dict, str]:
            bridge = PallasBridge(
                PallasVisionCfg(
                    enabled=True,
                    mock=False,
                    result_timeout=30.0,
                    max_abs_rz_deg=5.0,
                )
            )

            async def fake_send_trigger() -> None:
                bridge._capture_started_at = time.time() - 0.001
                bridge._handle_payload(b"0.1,0.2,7.0,0")

            bridge._send_trigger = fake_send_trigger  # type: ignore[method-assign]
            with self.assertRaises(PallasVisionResultError) as ctx:
                await bridge.capture()
            return bridge.status(), str(ctx.exception)

        status, message = asyncio.run(run())
        self.assertIn("角度偏移超限", message)
        self.assertEqual(status["last_error"], message)
        self.assertIsNone(status["last_result"])
        self.assertEqual(status["ignored_packets"], 0)

    def test_bridge_capture_returns_valid_false_on_bare_fail_code(self) -> None:
        # 识别失败 (裸 "111") 经桥应回 200 + valid=False, 不再走 set_exception → HTTP 422,
        # 否则客户端会把它当硬故障, VM 判 FAILED, 到不了流程内 human 分支。
        async def run() -> tuple[dict, dict]:
            bridge = PallasBridge(PallasVisionCfg(enabled=True, mock=False, result_timeout=30.0))

            async def fake_send_trigger() -> None:
                bridge._capture_started_at = time.time() - 0.001
                bridge._handle_payload(b"111")

            bridge._send_trigger = fake_send_trigger  # type: ignore[method-assign]
            result = await bridge.capture()
            return result, bridge.status()

        result, status = asyncio.run(run())
        self.assertEqual((result["valid"], result["err"], result["source"]), (False, 111, "pallas_bridge"))
        self.assertIsNone(status["last_error"])

    def test_bridge_capture_route_reports_result_error_as_422(self) -> None:
        class FakeBridge:
            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            def status(self) -> dict:
                return {"last_error": "bad result"}

            async def capture(self) -> dict:
                raise PallasVisionResultError("PALLASVision 角度偏移超限")

            async def reconnect(self) -> dict:
                return {}

        app = create_app(FakeBridge())  # type: ignore[arg-type]
        with TestClient(app) as client:
            response = client.post("/capture")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "PALLASVision 角度偏移超限")

    def test_action_executor_dispatches_formal_vision_action(self) -> None:
        registry = ActionRegistry.load(_PKG / "config" / "actions")

        async def fake_capture_plate_offset(*, apply_rz: bool = False):
            return {"dx_mm": 1.0, "dy_mm": 2.0, "drz_deg": 0.3 if apply_rz else 0.0,
                    "err": 0, "valid": True, "source": "test"}

        executor = ActionExecutor(
            registry,
            vision_methods={"capture_plate_offset": fake_capture_plate_offset},
        )
        result = asyncio.run(executor.execute("vision.capture_plate_offset", {"apply_rz": False}, current_mode="RUN"))
        self.assertEqual(result.status, ActionStatus.DONE)
        self.assertEqual(result.result["source"], "test")
        self.assertEqual(result.result["drz_deg"], 0.0)
        with self.assertRaises(KeyError):
            registry.get("robot.capture_plate_offset")


if __name__ == "__main__":
    unittest.main(verbosity=2)
