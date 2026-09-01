"""UV 相机安全契约离线测试。

这些测试只验证驱动层阶段 A：参数硬校验、Software Trigger、异常关灯、
取消等待和并发互斥。无需真实大恒相机。
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from eit_ptlc.driver import daheng_capture as dc


_WORK_DIR = Path("eit_ptlc/var/test_camera_safety")


def _work_path(filename: str) -> Path:
    _WORK_DIR.mkdir(parents=True, exist_ok=True)
    return _WORK_DIR / f"{time.time_ns()}_{filename}"


def _work_dir(name: str) -> Path:
    path = _WORK_DIR / f"{time.time_ns()}_{name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_params(**overrides):
    params = dict(dc.DEFAULT_PARAMS)
    params.update({
        "exposure_time": 19_000.0,
        "uv_on_time_ms": 20,
        "uv_hard_cutoff_ms": 120,
        "timeout_ms": 100,
    })
    params.update(overrides)
    return params


class _EnumFeature:
    def __init__(self, remote, name: str):
        self.remote = remote
        self.name = name
        self.value = {
            "PixelFormat": "RGB8",
            "TriggerMode": "Off",
            "TriggerSource": "",
        }.get(name, "")

    def set(self, value):
        self.value = value
        self.remote.events.append((self.name, value))

    def get(self):
        if self.name == "PixelFormat":
            return dc.GxPixelFormatEntry.RGB8, "RGB8"
        return 0, self.value


class _FloatFeature:
    def __init__(self, remote, name: str):
        self.remote = remote
        self.name = name

    def set(self, value):
        self.remote.events.append((self.name, float(value)))

    def get_range(self):
        return {"min": 1.0, "max": 2_000_000.0}


class _IntFeature:
    def __init__(self, remote, name: str, value: int):
        self.remote = remote
        self.name = name
        self.value = value

    def set(self, value):
        self.value = int(value)
        self.remote.events.append((self.name, int(value)))

    def get(self):
        return self.value


class _StringFeature:
    def __init__(self, value: str):
        self.value = value

    def get(self):
        return self.value


class _BoolFeature:
    def __init__(self, remote):
        self.remote = remote

    def set(self, value: bool):
        value = bool(value)
        if value and self.remote.fail_light_on:
            raise RuntimeError("light on failed")
        if (not value) and self.remote.fail_off_after_on and self.remote.ever_on:
            raise RuntimeError("light off failed")
        if value:
            self.remote.ever_on = True
        self.remote.light_values.append(value)
        self.remote.events.append(("UserOutputValue", value, time.monotonic()))


class _CommandFeature:
    def __init__(self, remote):
        self.remote = remote

    def send_command(self):
        self.remote.software_trigger_count += 1
        self.remote.events.append(("TriggerSoftware", "send"))


class _Remote:
    def __init__(
        self,
        *,
        unsupported_trigger: bool = False,
        fail_light_on: bool = False,
        fail_off_after_on: bool = False,
    ):
        self.unsupported_trigger = unsupported_trigger
        self.fail_light_on = fail_light_on
        self.fail_off_after_on = fail_off_after_on
        self.ever_on = False
        self.light_values: list[bool] = []
        self.events: list[tuple] = []
        self.software_trigger_count = 0

    def is_implemented(self, name: str) -> bool:
        if name == "TriggerSoftware" and self.unsupported_trigger:
            return False
        return name in {
            "LineSelector",
            "LineSource",
            "UserOutputSelector",
            "UserOutputValue",
            "TriggerMode",
            "TriggerSource",
            "TriggerSoftware",
            "ExposureTime",
            "Gain",
            "PixelFormat",
            "Width",
            "Height",
            "OffsetX",
            "OffsetY",
        }

    def get_enum_feature(self, name: str):
        return _EnumFeature(self, name)

    def get_float_feature(self, name: str):
        return _FloatFeature(self, name)

    def get_int_feature(self, name: str):
        defaults = {"Width": 8, "Height": 6, "OffsetX": 0, "OffsetY": 0}
        return _IntFeature(self, name, defaults.get(name, 0))

    def get_string_feature(self, name: str):
        values = {
            "DeviceModelName": "Fake-Daheng",
            "DeviceSerialNumber": "FAKE-SN",
        }
        return _StringFeature(values[name])

    def get_bool_feature(self, name: str):
        assert name == "UserOutputValue"
        return _BoolFeature(self)

    def get_command_feature(self, name: str):
        assert name == "TriggerSoftware"
        return _CommandFeature(self)


class _RawImage:
    frame_data = type("FrameData", (), {"height": 2, "width": 2})()

    def get_status(self):
        return dc.GxFrameStatusList.SUCCESS

    def get_frame_id(self):
        return 1

    def get_width(self):
        return 2

    def get_height(self):
        return 2

    def get_pixel_format(self):
        return dc.GxPixelFormatEntry.RGB8

    def get_numpy_array(self):
        return np.zeros((2, 2, 3), dtype=np.uint8)


class _DataStream:
    def __init__(self, *, return_none: bool = False, raise_error: bool = False):
        self.return_none = return_none
        self.raise_error = raise_error
        self.timeouts: list[int] = []

    def get_image(self, timeout_ms: int):
        self.timeouts.append(timeout_ms)
        if self.raise_error:
            raise RuntimeError("sdk get_image failed")
        if self.return_none:
            return None
        return _RawImage()


class _Camera:
    def __init__(self, remote: _Remote, data_stream: _DataStream | None = None):
        self.remote = remote
        self.data_stream = [data_stream or _DataStream()]
        self.stream_on_count = 0
        self.stream_off_count = 0
        self.closed = False

    def get_remote_device_feature_control(self):
        return self.remote

    def stream_on(self):
        self.stream_on_count += 1
        self.remote.events.append(("stream_on", None))

    def stream_off(self):
        self.stream_off_count += 1
        self.remote.events.append(("stream_off", None))

    def close_device(self):
        self.closed = True
        self.remote.events.append(("close_device", None))


class _DeviceManager:
    def __init__(self, camera: _Camera):
        self.camera = camera

    def update_all_device_list(self):
        return 1, [{
            "index": 1,
            "model_name": "Fake-Daheng",
            "vendor_name": "Daheng",
            "ip": "192.168.0.169",
            "sn": "FAKE-SN",
        }]

    def open_device_by_ip(self, _ip):
        return self.camera

    def create_image_format_convert(self):
        return object()


def _install_fake_camera(monkeypatch, *, remote=None, data_stream=None):
    remote = remote or _Remote()
    camera = _Camera(remote, data_stream=data_stream)
    monkeypatch.setattr(dc.gx, "DeviceManager", lambda: _DeviceManager(camera))
    return camera


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"exposure_time": 21_000.0, "uv_on_time_ms": 20}, "曝光时间"),
        ({"uv_on_time_ms": dc.UV_WORKING_LIMIT_MS + 1}, "工作上限"),
        ({"uv_hard_cutoff_ms": dc.UV_HARD_CUTOFF_LIMIT_MS + 1}, "硬上限"),
        ({"uv_on_time_ms": 20, "uv_hard_cutoff_ms": 20}, "必须大于"),
    ],
)
def test_uv_params_rejected_before_open(monkeypatch, overrides, message):
    def _should_not_open():
        raise AssertionError("非法 UV 参数不应进入 SDK")

    monkeypatch.setattr(dc.gx, "DeviceManager", _should_not_open)

    with pytest.raises(ValueError, match=message):
        dc.capture(_work_path("bad.jpg"), _safe_params(**overrides))


def test_default_uv_limits_are_hard_safe():
    assert dc.DEFAULT_PARAMS["uv_on_time_ms"] <= dc.UV_WORKING_LIMIT_MS
    assert dc.DEFAULT_PARAMS["uv_hard_cutoff_ms"] <= dc.UV_HARD_CUTOFF_LIMIT_MS
    assert dc.DEFAULT_PARAMS["trigger_mode"] == "On"
    assert dc.DEFAULT_PARAMS["trigger_source"] == "Software"


def test_capture_sends_software_trigger_and_returns_timing(monkeypatch):
    camera = _install_fake_camera(monkeypatch)

    path, timing = dc.capture(_work_path("ok.jpg"), _safe_params())

    assert path.exists()
    assert camera.remote.software_trigger_count == 1
    assert True in camera.remote.light_values
    assert camera.remote.light_values[-1] is False
    assert camera.stream_off_count == 1
    assert camera.closed is True
    assert timing["requested_uv_on_ms"] == 20
    assert timing["uv_hard_cutoff_ms"] == 120
    assert timing["software_trigger_sent"] is True
    assert timing["line1_close_ok"] is True
    assert timing["off_ok"] is True
    assert isinstance(timing["actual_uv_on_ms"], (int, float))


def test_unsupported_software_trigger_fails_before_light_on(monkeypatch):
    remote = _Remote(unsupported_trigger=True)
    _install_fake_camera(monkeypatch, remote=remote)

    with pytest.raises(RuntimeError, match="Software Trigger"):
        dc.capture(_work_path("unsupported.jpg"), _safe_params())

    assert True not in remote.light_values


@pytest.mark.parametrize(
    "data_stream",
    [
        _DataStream(return_none=True),
        _DataStream(raise_error=True),
    ],
)
def test_get_image_failure_closes_light(monkeypatch, data_stream):
    camera = _install_fake_camera(monkeypatch, data_stream=data_stream)

    with pytest.raises(RuntimeError):
        dc.capture(_work_path("fail.jpg"), _safe_params())

    assert camera.remote.light_values[-1] is False
    assert camera.stream_off_count == 1
    assert camera.closed is True


def test_save_failure_still_closes_light(monkeypatch):
    camera = _install_fake_camera(monkeypatch)

    class _BrokenImage:
        width = 2
        height = 2

        def save(self, *_args, **_kwargs):
            raise OSError("save failed")

    monkeypatch.setattr(dc.Image, "fromarray", lambda *_args, **_kwargs: _BrokenImage())

    with pytest.raises(OSError, match="save failed"):
        dc.capture(_work_path("save-fail.jpg"), _safe_params())

    assert camera.remote.light_values[-1] is False
    assert camera.stream_off_count == 1
    assert camera.closed is True


def test_unconfirmed_light_off_raises_and_does_not_report_ok(monkeypatch):
    remote = _Remote(fail_off_after_on=True)
    _install_fake_camera(monkeypatch, remote=remote)

    with pytest.raises(RuntimeError, match="未能确认 Line1"):
        dc.capture(_work_path("off-fail.jpg"), _safe_params(uv_hard_cutoff_ms=50))

    assert True in remote.light_values
    assert remote.light_values[-1] is True


def test_capture_with_timing_keeps_lock_until_cancelled_worker_finishes():
    from eit_ptlc.driver.camera_driver import DahengCameraService

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def _blocking_capture(save_path, params=None):
        started.set()
        release.wait(timeout=2.0)
        Path(save_path).write_bytes(b"jpeg")
        finished.set()
        return Path(save_path), {
            "actual_uv_on_ms": 10.0,
            "requested_uv_on_ms": 20,
            "line1_close_ok": True,
            "off_ok": True,
            "over_limit": False,
            "trigger_mode_used": "On",
        }

    async def _scenario():
        svc = DahengCameraService(params={})
        save_dir = _work_dir("cancel")
        with patch("eit_ptlc.driver.daheng_capture.capture", side_effect=_blocking_capture):
            task = asyncio.create_task(svc.capture_with_timing("s", save_dir))
            assert await asyncio.to_thread(started.wait, 1.0)
            assert svc._lock.locked()

            task.cancel()
            await asyncio.sleep(0.05)
            assert svc._lock.locked(), "后台 SDK 未清理完成前不能释放锁"
            assert not finished.is_set()

            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set()
            assert not svc._lock.locked()

    asyncio.run(_scenario())


def test_concurrent_capture_never_enters_two_sdk_threads():
    from eit_ptlc.driver.camera_driver import DahengCameraService

    active = 0
    max_active = 0
    calls = 0
    guard = threading.Lock()

    def _slow_capture(save_path, params=None):
        nonlocal active, max_active, calls
        with guard:
            active += 1
            calls += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        Path(save_path).write_bytes(b"jpeg")
        with guard:
            active -= 1
        return Path(save_path), {
            "actual_uv_on_ms": 10.0,
            "requested_uv_on_ms": 20,
            "line1_close_ok": True,
            "off_ok": True,
            "over_limit": False,
            "trigger_mode_used": "On",
        }

    async def _scenario():
        svc = DahengCameraService(params={})
        save_dir = _work_dir("concurrent")
        with patch("eit_ptlc.driver.daheng_capture.capture", side_effect=_slow_capture):
            await asyncio.gather(
                svc.capture_with_timing("a", save_dir, filename="a.jpg"),
                svc.capture_with_timing("b", save_dir, filename="b.jpg"),
            )

    asyncio.run(_scenario())
    assert calls == 2
    assert max_active == 1


def test_trigger_mode_reset_off_on_success(monkeypatch):
    camera = _install_fake_camera(monkeypatch)

    dc.capture(_work_path("reset-ok.jpg"), _safe_params())

    trigger_vals = [v for (n, v, *_) in camera.remote.events if n == "TriggerMode"]
    assert trigger_vals, "应至少配置过一次 TriggerMode"
    assert trigger_vals[-1] == "Off", "拍完必须把相机留在连续采集态 (TriggerMode=Off)"


@pytest.mark.parametrize(
    "data_stream",
    [
        _DataStream(return_none=True),
        _DataStream(raise_error=True),
    ],
)
def test_trigger_mode_reset_off_even_on_get_image_failure(monkeypatch, data_stream):
    camera = _install_fake_camera(monkeypatch, data_stream=data_stream)

    with pytest.raises(RuntimeError):
        dc.capture(_work_path("reset-fail.jpg"), _safe_params())

    trigger_vals = [v for (n, v, *_) in camera.remote.events if n == "TriggerMode"]
    assert trigger_vals[-1] == "Off", "拍照失败路径也必须复位 TriggerMode=Off"
