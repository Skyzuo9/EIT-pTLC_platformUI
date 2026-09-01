"""辅助控制器离线测试 (相机 + 液位)
===================================
功能:
    验证 camera_controller (mock 拍照复制预置图) 与 waterlevel_controller (订阅回调聚合快照).

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_aux_controllers_offline
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from eit_ptlc.config.models import CameraCfg
from eit_ptlc.controller.camera_controller import CameraController, build_camera_service
from eit_ptlc.controller.waterlevel_controller import WaterLevelController
from eit_ptlc.driver.camera_driver import MockCameraService


class _FakeWLClient:
    """fake 液位客户端: 记录回调供测试直接触发."""

    def __init__(self) -> None:
        self.cbs: dict = {}

    def on_data(self, cb):
        self.cbs["data"] = cb

    def on_device_state_change(self, cb):
        self.cbs["state"] = cb

    def on_alarm(self, cb):
        self.cbs["alarm"] = cb


async def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # ---- 相机 (mock) ----
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        preset = td / "preset.jpg"
        preset.write_bytes(b"img")
        cfg = CameraCfg(mock=True, test_image=preset)
        check("build_mock_camera", isinstance(build_camera_service(cfg), MockCameraService))
        ctrl = CameraController.from_config(cfg)
        out = await ctrl.capture("S1", td / "out", filename="after.jpg")
        check("camera_capture", out.is_file() and out.name == "after.jpg", str(out))

    # ---- 液位 (聚合) ----
    fake = _FakeWLClient()
    wl = WaterLevelController(fake)
    fake.cbs["state"](True)
    fake.cbs["data"]([{"channel": 1, "level": 42.0}, {"channel": 2, "level": 10.5}])
    snap = wl.snapshot()
    check("wl_online", snap["online"] is True, str(snap))
    check("wl_channels", snap["channels"][1]["level"] == 42.0 and len(snap["channels"]) == 2, str(snap["channels"]))
    check("wl_level_of", wl.level_of(2) == 10.5 and wl.level_of(9) is None, str(wl.level_of(2)))

    print(f"\n共 5 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
