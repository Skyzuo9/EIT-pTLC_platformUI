"""Async application entry for one resolved robot business route."""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .robot_business_resources import RobotBusinessResourceLedger
from .robot_host_adapter import ThreadsafePlcCameraHost
from .robot_route import ResolvedRoutePlan
from .robot_route_executor import RouteExecutionResult, RouteExecutor
from .robot_service import RobotRuntime

if TYPE_CHECKING:
    from .camera_service import CameraService
    from .plc_client import PLCClient


async def execute_route(
    *,
    runtime: RobotRuntime,
    plan: ResolvedRoutePlan,
    plc: "PLCClient",
    plc_action_client,
    camera: "CameraService",
    sample_id: str,
    save_dir: str | Path,
    resources: RobotBusinessResourceLedger,
    event_sink: Callable[[dict[str, object]], None] | None = None,
    host_call_timeout_s: float = 30.0,
) -> RouteExecutionResult:
    """Execute on one worker thread while PLC/camera stay on the app loop.

    The worker-thread boundary keeps the synchronous Modbus robot transaction
    and its RLock on one thread. ThreadsafePlcCameraHost submits only PLC and
    camera coroutines back to the owning asyncio loop.
    """

    loop = asyncio.get_running_loop()
    host = ThreadsafePlcCameraHost(
        loop=loop,
        plc=plc,
        camera=camera,
        catalog=runtime.host_action_catalog,
        plc_action_client=plc_action_client,
        sample_id=sample_id,
        save_dir=save_dir,
        call_timeout_s=host_call_timeout_s,
    )
    stop_requested = threading.Event()
    executor = RouteExecutor(
        action_service=runtime.service,
        flow_service=runtime.flow_service,
        host=host,
        resources=resources,
        event_sink=event_sink,
        stop_requested=stop_requested.is_set,
    )
    runtime.transport.connect()
    worker = asyncio.create_task(
        asyncio.to_thread(executor.execute, plan)
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Never close the Modbus connection while its worker is still using it.
        # The current robot/host step finishes naturally; the stop flag blocks
        # every subsequent route step and disables further PLC polling.
        stop_requested.set()
        with suppress(Exception):
            await asyncio.shield(worker)
        raise
    finally:
        runtime.transport.close()
