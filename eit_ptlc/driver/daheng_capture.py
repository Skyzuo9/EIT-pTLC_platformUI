#!/usr/bin/env python3
"""大恒相机拍照脚本（独立可运行 + 可导入模块）

基于大恒 PALLAS SDK (gxipy v2.0.2512) 的 GigE 彩色相机单帧拍照。

使用方式：
    # CLI 模式（调试/手动拍照）
    python scripts/daheng_capture.py --ip 192.168.0.169 --output E:/test.jpg

    # 导入模式（供 DahengCameraService 调用）
    from scripts.daheng_capture import capture, DEFAULT_PARAMS
    params = {**DEFAULT_PARAMS, "exposure_time": 200000.0}
    path, timing = capture(Path("output/after.jpg"), params)
    # CLI backward compat: path, _ = capture(...)

参数设计（params dict 对应 config.example.yaml 的 camera.daheng 段）：
    ip                : str   = "192.168.0.169"  相机 IP 地址
    exposure_time     : float = 1000000.0         曝光时间 (µs)，默认 1000ms
    gain              : float = 1.0              模拟增益
    pixel_format      : str   = "RGB8"            目标像素格式
    trigger_mode      : str   = "On"              触发模式 (On=软触发, Off=连续采集)
    trigger_source    : str   = "Software"        触发源 (仅 trigger_mode=On 时有效)
    timeout_ms        : int   = 5000              采图超时 (ms)
    width             : int   = 0                 图像宽度 (0=不修改)
    height            : int   = 0                 图像高度 (0=不修改)
    offset_x          : int   = 0                 ROI X 偏移
    offset_y          : int   = 0                 ROI Y 偏移
    uv_on_time_ms     : int   = 1000              UV 光源允许开启时长 (ms)
    uv_hard_cutoff_ms : int   = 2000              UV 光源硬截止时限 (ms), 独立安全线程强制关灯

UV 安全契约 (vision debug station):
    原子 UV 拍照序列: 强制关灯(初态) → 开灯 → 采图 → 关灯
    双重保护: (1) 主路径 finally 关灯 (2) 独立 threading.Timer 硬截止
    关灯失败 → logging.CRITICAL (升级自 warning)
    返回 timing_info dict 记录实际 UV 开启时长/超限/关灯状态
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Monkey-patch: numpy >= 1.24 移除了 numpy.compat，但大恒 SDK (DeviceManager.py
# line 7) 需要 from numpy.compat import long。在此注入兼容模块。
# ---------------------------------------------------------------------------
import types as _types  # noqa: E402

if not hasattr(np, "compat"):
    _compat = _types.ModuleType("numpy.compat")
    _compat.long = int
    sys.modules["numpy.compat"] = _compat
    np.compat = _compat

# ---------------------------------------------------------------------------
# 使用随 eit_ptlc 迁移的本地大恒 Python SDK。
# ---------------------------------------------------------------------------
_DRIVER_DIR = Path(__file__).resolve().parent
if str(_DRIVER_DIR) not in sys.path:
    sys.path.insert(0, str(_DRIVER_DIR))

import gxipy as gx  # noqa: E402
from gxipy.gxidef import *  # noqa: E402 F403

log = logging.getLogger(__name__)

# UV 安全硬约束：普通工作窗口给系统/SDK 抖动留 200ms 余量，硬截止不可超过 2 秒。
UV_WORKING_LIMIT_MS = 1800
UV_HARD_CUTOFF_LIMIT_MS = 2000

# ---------------------------------------------------------------------------
# 默认参数（与 config.example.yaml camera.daheng 段同步）
# ---------------------------------------------------------------------------
DEFAULT_PARAMS: dict = {
    "ip": "192.168.0.169",
    "exposure_time": 1_000_000.0,  # µs，默认 1000ms
    "gain": 1.0,
    "pixel_format": "RGB8",
    "trigger_mode": "On",           # 默认尝试软触发 (软件触发)
    "trigger_source": "Software",   # 触发源 (仅 trigger_mode=On 时有效)
    "timeout_ms": 2000,
    "width": 0,
    "height": 0,
    "offset_x": 0,
    "offset_y": 0,
    "auto_light_control": True,     # 拍照前开光源，拍照后关（保护光源）
    "light_line": "Line1",          # 光源连接的物理 I/O 线（默认 Line1=Pin7/8 光耦输出）
    # UV 安全契约 (vision debug station)
    "uv_on_time_ms": 1000,          # UV 光源允许开启时长 (ms), 超出即 over_limit
    "uv_hard_cutoff_ms": 2000,      # UV 光源硬截止时限 (ms), 独立安全线程强制关灯
}


def _validate_uv_safety_params(p: dict) -> tuple[float, int, int]:
    """在任何开灯/连相机动作之前校验 UV 安全参数。"""
    exposure_time_us = float(p["exposure_time"])
    exposure_time_ms = exposure_time_us / 1000.0
    uv_on_time_ms = int(p["uv_on_time_ms"])
    uv_hard_cutoff_ms = int(p["uv_hard_cutoff_ms"])

    if exposure_time_us <= 0:
        raise ValueError("exposure_time 必须 > 0")
    if uv_on_time_ms <= 0:
        raise ValueError("uv_on_time_ms 必须 > 0")
    if uv_hard_cutoff_ms <= 0:
        raise ValueError("uv_hard_cutoff_ms 必须 > 0")
    if exposure_time_ms > uv_on_time_ms:
        raise ValueError(
            "UV 安全参数非法: 曝光时间 "
            f"{exposure_time_ms:.1f}ms 不能超过 UV 总点亮时间 {uv_on_time_ms}ms",
        )
    if uv_on_time_ms > UV_WORKING_LIMIT_MS:
        raise ValueError(
            "UV 安全参数非法: uv_on_time_ms="
            f"{uv_on_time_ms}ms 超过工作上限 {UV_WORKING_LIMIT_MS}ms",
        )
    if uv_hard_cutoff_ms <= uv_on_time_ms:
        raise ValueError(
            "UV 安全参数非法: uv_hard_cutoff_ms 必须大于 uv_on_time_ms, "
            "为 SDK 抖动和关灯重试保留余量",
        )
    if uv_hard_cutoff_ms > UV_HARD_CUTOFF_LIMIT_MS:
        raise ValueError(
            "UV 安全参数非法: uv_hard_cutoff_ms="
            f"{uv_hard_cutoff_ms}ms 超过硬上限 {UV_HARD_CUTOFF_LIMIT_MS}ms",
        )
    return exposure_time_ms, uv_on_time_ms, uv_hard_cutoff_ms


# ---------------------------------------------------------------------------
# 像素格式 → 有效位映射（参考 GxSingleCamColor.py get_best_valid_bits）
# ---------------------------------------------------------------------------
def _get_best_valid_bits(pixel_format: int) -> int:
    """根据像素格式返回最佳有效位."""
    if pixel_format in (
        GxPixelFormatEntry.MONO8, GxPixelFormatEntry.BAYER_GR8, GxPixelFormatEntry.BAYER_RG8,
        GxPixelFormatEntry.BAYER_GB8, GxPixelFormatEntry.BAYER_BG8,
        GxPixelFormatEntry.RGB8, GxPixelFormatEntry.BGR8,
        GxPixelFormatEntry.R8, GxPixelFormatEntry.B8, GxPixelFormatEntry.G8,
    ):
        return DxValidBit.BIT0_7
    elif pixel_format in (
        GxPixelFormatEntry.MONO10, GxPixelFormatEntry.MONO10_PACKED, GxPixelFormatEntry.MONO10_P,
        GxPixelFormatEntry.BAYER_GR10, GxPixelFormatEntry.BAYER_RG10,
        GxPixelFormatEntry.BAYER_GB10, GxPixelFormatEntry.BAYER_BG10,
        GxPixelFormatEntry.BAYER_GR10_P, GxPixelFormatEntry.BAYER_RG10_P,
        GxPixelFormatEntry.BAYER_GB10_P, GxPixelFormatEntry.BAYER_BG10_P,
        GxPixelFormatEntry.BAYER_GR10_PACKED, GxPixelFormatEntry.BAYER_RG10_PACKED,
        GxPixelFormatEntry.BAYER_GB10_PACKED, GxPixelFormatEntry.BAYER_BG10_PACKED,
    ):
        return DxValidBit.BIT2_9
    elif pixel_format in (
        GxPixelFormatEntry.MONO12, GxPixelFormatEntry.MONO12_PACKED, GxPixelFormatEntry.MONO12_P,
        GxPixelFormatEntry.BAYER_GR12, GxPixelFormatEntry.BAYER_RG12,
        GxPixelFormatEntry.BAYER_GB12, GxPixelFormatEntry.BAYER_BG12,
        GxPixelFormatEntry.BAYER_GR12_P, GxPixelFormatEntry.BAYER_RG12_P,
        GxPixelFormatEntry.BAYER_GB12_P, GxPixelFormatEntry.BAYER_BG12_P,
        GxPixelFormatEntry.BAYER_GR12_PACKED, GxPixelFormatEntry.BAYER_RG12_PACKED,
        GxPixelFormatEntry.BAYER_GB12_PACKED, GxPixelFormatEntry.BAYER_BG12_PACKED,
    ):
        return DxValidBit.BIT4_11
    elif pixel_format in (
        GxPixelFormatEntry.MONO14, GxPixelFormatEntry.MONO14_P,
        GxPixelFormatEntry.BAYER_GR14, GxPixelFormatEntry.BAYER_RG14,
        GxPixelFormatEntry.BAYER_GB14, GxPixelFormatEntry.BAYER_BG14,
        GxPixelFormatEntry.BAYER_GR14_P, GxPixelFormatEntry.BAYER_RG14_P,
        GxPixelFormatEntry.BAYER_GB14_P, GxPixelFormatEntry.BAYER_BG14_P,
    ):
        return DxValidBit.BIT6_13
    elif pixel_format in (
        GxPixelFormatEntry.MONO16, GxPixelFormatEntry.BAYER_GR16, GxPixelFormatEntry.BAYER_RG16,
        GxPixelFormatEntry.BAYER_GB16, GxPixelFormatEntry.BAYER_BG16,
    ):
        return DxValidBit.BIT8_15
    return DxValidBit.BIT0_7


# ---------------------------------------------------------------------------
# RGB 转换（参考 GxSingleCamColor.py convert_to_RGB）
# ---------------------------------------------------------------------------
def _convert_to_rgb(raw_image, image_convert) -> Optional[np.ndarray]:
    """将 raw_image 转为 RGB8 numpy 数组（H, W, 3）。"""
    from ctypes import c_ubyte, addressof

    image_convert.set_dest_format(GxPixelFormatEntry.RGB8)
    valid_bits = _get_best_valid_bits(raw_image.get_pixel_format())
    image_convert.set_valid_bits(valid_bits)

    buffer_out_size = image_convert.get_buffer_size_for_conversion(raw_image)
    output_image_array = (c_ubyte * buffer_out_size)()
    output_image = addressof(output_image_array)

    image_convert.convert(raw_image, output_image, buffer_out_size, False)
    if output_image is None:
        log.error("RGB 转换失败")
        return None

    return np.frombuffer(output_image_array, dtype=np.ubyte, count=buffer_out_size).reshape(
        raw_image.frame_data.height, raw_image.frame_data.width, 3,
    )


# ---------------------------------------------------------------------------
# 光源控制辅助函数（适配不同相机 GPIO 命名方式）
# ---------------------------------------------------------------------------
def _control_light(remote, on: bool, line: str = "Line1") -> bool:
    """打开/关闭相机光源。

    MEX-G/MER2 系列相机通过 Line1 光耦输出控制光源（手册 §8.1.2）。
    Line1 是单向光耦输出，上电默认输出源为 UserOutput0。

    控制链：LineSelector→Line1 → LineSource→UserOutput0
           → UserOutputSelector→UserOutput0 → UserOutputValue→True/False

    Args:
        line: 物理输出线，默认 "Line1"（Pin 7/8 光耦输出）

    Returns:
        True 若成功，False 若相机不支持 GPIO 控制
    """
    action = "开" if on else "关"

    # 严格按照官方手册 §8.1.2 配置输出引脚
    try:
        if (remote.is_implemented("LineSelector")
                and remote.is_implemented("UserOutputSelector")
                and remote.is_implemented("UserOutputValue")):
            # 1. 选择物理引脚
            remote.get_enum_feature("LineSelector").set(line)
            # 2. 将 UserOutput0 信号路由到此引脚（上电默认，显式设置确保无误）
            if remote.is_implemented("LineSource"):
                remote.get_enum_feature("LineSource").set("UserOutput0")
            # 3. 选择要控制的 UserOutput 信号
            remote.get_enum_feature("UserOutputSelector").set("UserOutput0")
            # 4. 设置输出电平
            remote.get_bool_feature("UserOutputValue").set(on)
            log.info("光源%s (LineSelector→%s, LineSource→UserOutput0, UserOutputValue→%s)",
                     action, line, on)
            return True
    except Exception:
        log.debug("LineSelector 方式失败", exc_info=True)

    # 备用：UserOutputSelector + UserOutputValue（依赖默认 LineSource 映射）
    try:
        if (remote.is_implemented("UserOutputSelector")
                and remote.is_implemented("UserOutputValue")):
            remote.get_enum_feature("UserOutputSelector").set("UserOutput0")
            remote.get_bool_feature("UserOutputValue").set(on)
            log.info("光源%s (UserOutputSelector→UserOutput0, UserOutputValue→%s)", action, on)
            return True
    except Exception:
        log.debug("UserOutputSelector 方式失败", exc_info=True)

    return False


# ---------------------------------------------------------------------------
# UV 安全: 独立紧急关灯回调 (由 threading.Timer 在单独线程中执行)
# ---------------------------------------------------------------------------
def _emergency_light_off(
    remote,
    light_line: str,
    reason: str = "hard_cutoff",
    light_state: Optional[dict] = None,
    state_lock: Optional[threading.Lock] = None,
) -> None:
    """紧急关灯回调 -- 由独立安全线程调用, 不依赖主路径状态.

    此函数在单独的线程中运行, 即使主线程卡死在 SDK 调用中也会触发.
    关灯失败时记录 CRITICAL 级别日志, 需要人工干预.
    """
    try:
        ok = _control_light(remote, False, light_line)
        now = time.monotonic()
        if light_state is not None:
            lock = state_lock or threading.Lock()
            with lock:
                light_state[f"{reason}_fired"] = True
                light_state[f"{reason}_off_ok"] = ok
                if ok and light_state.get("on") and not light_state.get("off_confirmed"):
                    light_state["off_confirmed"] = True
                    light_state["off_ok"] = True
                    light_state["off_time"] = now
                    light_state["closed_by"] = reason
        if ok:
            log.critical("UV SAFETY: %s 关灯成功 (独立安全线程) -- 主路径可能已卡死!", reason)
        else:
            log.critical("UV SAFETY: %s 关灯失败 (GPIO 不可用) -- 需人工检查光源状态!", reason)
    except Exception:
        if light_state is not None:
            lock = state_lock or threading.Lock()
            with lock:
                light_state[f"{reason}_fired"] = True
                light_state[f"{reason}_off_ok"] = False
        log.critical("UV SAFETY: %s 关灯异常 -- 需人工干预关闭 UV 光源!", reason, exc_info=True)


def _send_software_trigger(remote) -> None:
    """发送大恒 Software Trigger；不支持则失败关闭，不回退连续采集。"""
    if not remote.is_implemented("TriggerSoftware"):
        raise RuntimeError("相机不支持 TriggerSoftware，UV 安全拍照拒绝回退到连续采集")
    try:
        remote.get_command_feature("TriggerSoftware").send_command()
    except AttributeError as exc:
        raise RuntimeError("当前 gxipy FeatureControl 不支持 get_command_feature") from exc
    log.info("触发命令: TriggerSoftware.send_command() 已发送")


# ---------------------------------------------------------------------------
# 核心拍照函数
# ---------------------------------------------------------------------------
def capture(save_path: Path, params: dict | None = None) -> Tuple[Path, dict]:
    """从大恒相机拍照并保存为 JPEG, 带 UV 安全契约.

    原子 UV 拍照序列:
        强制关灯(初态) → 开灯 → 采图 → 关灯
    双重保护:
        1. 主路径 finally 关灯
        2. 独立 threading.Timer 硬截止 (uv_hard_cutoff_ms 后强制关灯)

    Args:
        save_path: 图像保存路径（含文件名，如 output/after.jpg）
        params:   相机参数字典，缺失字段回落到 DEFAULT_PARAMS

    Returns:
        (保存后的图像路径, timing_info dict)
        timing_info keys:
            actual_uv_on_ms:     实际 UV 开启时长 (ms)
            requested_uv_on_ms:  请求的 UV 允许开启时长 (ms)
            exposure_time_us:    曝光时间 (µs)
            over_limit:          是否超出 uv_on_time_ms 限制
            line1_close_ok:      主路径关灯是否成功
            trigger_mode_used:   实际使用的触发模式

    Raises:
        RuntimeError: 相机未找到 / 拍照失败
    """
    p: dict = {**DEFAULT_PARAMS, **(params or {})}

    ip = str(p["ip"])
    exposure_time = float(p["exposure_time"])
    gain = float(p["gain"])
    pixel_format_str = str(p["pixel_format"])
    trigger_mode_str = str(p["trigger_mode"])
    trigger_source_str = str(p["trigger_source"])
    timeout_ms = int(p["timeout_ms"])
    width = int(p["width"])
    height = int(p["height"])
    offset_x = int(p["offset_x"])
    offset_y = int(p["offset_y"])
    auto_light_control = bool(p["auto_light_control"])
    light_line = str(p["light_line"])
    exposure_time_ms, uv_on_time_ms, uv_hard_cutoff_ms = _validate_uv_safety_params(p)

    if auto_light_control and (
        trigger_mode_str != "On" or trigger_source_str != "Software"
    ):
        raise RuntimeError(
            "UV 安全拍照要求 trigger_mode=On 且 trigger_source=Software, "
            "拒绝使用连续采集或外部触发以避免旧帧/暗帧",
        )

    # 初始化 timing_info (默认值 -- 即使早期失败也能返回有意义的结果)
    timing_info: dict = {
        "actual_uv_on_ms": 0,
        "requested_uv_on_ms": uv_on_time_ms,
        "exposure_time_us": exposure_time,
        "uv_hard_cutoff_ms": uv_hard_cutoff_ms,
        "uv_working_limit_ms": UV_WORKING_LIMIT_MS,
        "over_limit": False,
        "line1_close_ok": False,
        "off_ok": False,
        "closed_by": None,
        "line1_initial_off_ok": False,
        "line1_open_ok": False,
        "software_trigger_sent": False,
        "trigger_mode_used": "Off",
    }
    if not auto_light_control:
        timing_info.update({
            "line1_close_ok": True,
            "off_ok": True,
            "closed_by": "auto_light_disabled",
        })

    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("初始化大恒 SDK...")
    device_manager = gx.DeviceManager()
    dev_num, dev_info_list = device_manager.update_all_device_list()
    if dev_num == 0:
        raise RuntimeError("未枚举到任何大恒相机设备")

    log.info("发现 %d 台设备:", dev_num)
    for info in dev_info_list:
        log.info("  [%d] %s | %s | IP=%s | SN=%s",
                 info["index"], info["model_name"], info["vendor_name"],
                 info.get("ip", "N/A"), info.get("sn", "N/A"))

    # 按 IP 打开设备
    log.info("正在连接相机 IP=%s ...", ip)
    cam = device_manager.open_device_by_ip(ip)
    if cam is None:
        raise RuntimeError(f"无法通过 IP={ip} 连接相机，请检查网络和 IP 配置")

    # 安全定时器句柄 (在 remote 可用后创建)
    requested_timer: Optional[threading.Timer] = None
    safety_timer: Optional[threading.Timer] = None
    uv_start_time: float = 0.0
    stream_started = False
    light_state: dict = {
        "on": False,
        "off_confirmed": False,
        "off_ok": False,
        "off_time": None,
        "closed_by": None,
        "requested_cutoff_fired": False,
        "hard_cutoff_fired": False,
    }
    state_lock = threading.Lock()

    def _mark_light_on(start_time: float) -> None:
        with state_lock:
            light_state["on"] = True
            light_state["on_time"] = start_time
            light_state["off_confirmed"] = False
            light_state["off_ok"] = False
            light_state["off_time"] = None
            light_state["closed_by"] = None

    def _close_light(reason: str) -> bool:
        """主线程关灯并记录第一次确认 OFF 的时间。"""
        ok = _control_light(remote, False, light_line)
        now = time.monotonic()
        with state_lock:
            if ok and light_state.get("on") and not light_state.get("off_confirmed"):
                light_state["off_confirmed"] = True
                light_state["off_ok"] = True
                light_state["off_time"] = now
                light_state["closed_by"] = reason
            elif not ok and not light_state.get("off_confirmed"):
                light_state["off_ok"] = False
        return ok

    def _refresh_timing() -> None:
        with state_lock:
            off_time = light_state.get("off_time")
            off_ok = bool(light_state.get("off_confirmed"))
            closed_by = light_state.get("closed_by")
            requested_fired = bool(light_state.get("requested_cutoff_fired"))
            hard_fired = bool(light_state.get("hard_cutoff_fired"))
        if uv_start_time and off_time:
            actual_uv_on_ms = max(0.0, (float(off_time) - uv_start_time) * 1000.0)
        elif uv_start_time:
            actual_uv_on_ms = max(0.0, (time.monotonic() - uv_start_time) * 1000.0)
        else:
            actual_uv_on_ms = 0.0
        timing_info.update({
            "actual_uv_on_ms": round(actual_uv_on_ms, 1),
            "over_limit": actual_uv_on_ms > uv_on_time_ms,
            "line1_close_ok": off_ok,
            "off_ok": off_ok,
            "closed_by": closed_by,
            "requested_cutoff_fired": requested_fired,
            "hard_cutoff_fired": hard_fired,
        })

    remote = None
    try:
        remote = cam.get_remote_device_feature_control()

        # 打印相机信息
        model = remote.get_string_feature("DeviceModelName").get()
        sn = remote.get_string_feature("DeviceSerialNumber").get()
        log.info("已连接: %s (SN=%s)", model, sn)

        # ---- 创建图像格式转换器 (彩色相机 Bayer→RGB) ----
        image_convert = device_manager.create_image_format_convert()

        # ---- 配置触发模式 (UV 安全路径只允许软触发，失败即拒绝拍照) ----
        trigger_mode_used = "Off"
        try:
            trigger_feature = remote.get_enum_feature("TriggerMode")
            trigger_feature.set(trigger_mode_str)
            if trigger_mode_str == "On":
                if not remote.is_implemented("TriggerSource"):
                    raise RuntimeError("相机不支持 TriggerSource，无法保证 Software Trigger")
                remote.get_enum_feature("TriggerSource").set(trigger_source_str)
                if trigger_source_str == "Software" and not remote.is_implemented("TriggerSoftware"):
                    raise RuntimeError("相机不支持 TriggerSoftware，拒绝开灯")
                log.info("触发模式: %s (TriggerSource=%s)", trigger_mode_str, trigger_source_str)
            else:
                log.info("触发模式: %s", trigger_mode_str)
            trigger_mode_used = trigger_mode_str
        except Exception as exc:
            raise RuntimeError("配置 Software Trigger 失败，UV 安全拍照已拒绝") from exc
        timing_info["trigger_mode_used"] = trigger_mode_used

        # ---- 配置曝光 ----
        if remote.is_implemented("ExposureTime"):
            exp_feature = remote.get_float_feature("ExposureTime")
            exp_range = (exp_feature.get_range()["min"], exp_feature.get_range()["max"])
            log.info("曝光范围: %.1f ~ %.1f µs", exp_range[0], exp_range[1])
            exp_feature.set(exposure_time)
            log.info("曝光时间: %.1f µs", exposure_time)

        # ---- 配置增益 ----
        if remote.is_implemented("Gain"):
            gain_feature = remote.get_float_feature("Gain")
            gain_feature.set(gain)
            log.info("增益: %.2f", gain)

        # ---- 配置像素格式 ----
        pf_feature = remote.get_enum_feature("PixelFormat")
        current_pf_value, current_pf_str = pf_feature.get()
        log.info("当前像素格式: %s", current_pf_str)

        # 若指定了不同格式且相机支持，则切换
        if pixel_format_str and pixel_format_str != current_pf_str:
            try:
                pf_feature.set(pixel_format_str)
                log.info("像素格式切换: %s → %s", current_pf_str, pixel_format_str)
            except Exception:
                log.warning("像素格式 %s 不支持，保持 %s", pixel_format_str, current_pf_str)

        # ---- 配置 ROI ----
        if width > 0:
            remote.get_int_feature("Width").set(width)
        if height > 0:
            remote.get_int_feature("Height").set(height)
        if offset_x > 0:
            remote.get_int_feature("OffsetX").set(offset_x)
        if offset_y > 0:
            remote.get_int_feature("OffsetY").set(offset_y)

        actual_width = remote.get_int_feature("Width").get()
        actual_height = remote.get_int_feature("Height").get()
        log.info("分辨率: %d × %d", actual_width, actual_height)

        # ================================================================
        # UV 安全契约: 原子 UV 拍照序列
        # ================================================================
        # Step 0: 强制关灯 (确保初态安全)
        if auto_light_control:
            log.info("UV SAFETY: 强制关灯 (初态)")
            initial_off_ok = _control_light(remote, False, light_line)
            timing_info["line1_initial_off_ok"] = initial_off_ok
            if not initial_off_ok:
                raise RuntimeError("UV SAFETY: 初始强制关灯失败，拒绝继续拍照")

        # ---- 开始采集 ----
        cam.stream_on()
        stream_started = True

        # Step 2: 开灯 + 采图 + 关灯 (原子序列)
        try:
            if auto_light_control:
                # Step 2a: 记录开始时间 + 开灯
                uv_start_time = time.monotonic()
                light_ok = _control_light(remote, True, light_line)
                if not light_ok:
                    raise RuntimeError("UV SAFETY: Line1 开灯失败，拒绝继续拍照")
                timing_info["line1_open_ok"] = True
                _mark_light_on(uv_start_time)

                requested_timer = threading.Timer(
                    uv_on_time_ms / 1000.0,
                    _emergency_light_off,
                    args=(remote, light_line, "requested_cutoff", light_state, state_lock),
                )
                requested_timer.daemon = True
                requested_timer.start()
                safety_timer = threading.Timer(
                    uv_hard_cutoff_ms / 1000.0,
                    _emergency_light_off,
                    args=(remote, light_line, "hard_cutoff", light_state, state_lock),
                )
                safety_timer.daemon = True
                safety_timer.start()
                log.info("UV SAFETY: 光源已开启 (Line1=ON) at t=%.3fs", uv_start_time)
                log.info("UV SAFETY: 请求截止=%dms, 硬截止=%dms", uv_on_time_ms, uv_hard_cutoff_ms)

            if trigger_mode_used == "On" and trigger_source_str == "Software":
                # 让 UV 总窗口覆盖“预照 + 曝光”: 先等待剩余预照时间，再触发曝光。
                pre_trigger_delay_ms = max(0.0, uv_on_time_ms - exposure_time_ms)
                if pre_trigger_delay_ms > 0:
                    time.sleep(pre_trigger_delay_ms / 1000.0)
                _send_software_trigger(remote)
                timing_info["software_trigger_sent"] = True

            # Step 2b: 抓取一帧
            if uv_start_time:
                elapsed_ms = (time.monotonic() - uv_start_time) * 1000.0
                bounded_timeout_ms = max(1, int(min(timeout_ms, uv_hard_cutoff_ms - elapsed_ms)))
            else:
                bounded_timeout_ms = timeout_ms
            log.info("等待图像 (timeout=%dms)...", bounded_timeout_ms)
            raw_image = cam.data_stream[0].get_image(bounded_timeout_ms)
            if raw_image is None:
                raise RuntimeError("获取图像超时（相机未返回数据）")

            if raw_image.get_status() != GxFrameStatusList.SUCCESS:
                raise RuntimeError(f"图像状态异常: {raw_image.get_status()}")

        finally:
            # Step 3: 双重保护 -- finally 中无条件尝试关灯，成功前不取消后备截止。
            if auto_light_control:
                main_off_ok = _close_light("main_finally")
                if main_off_ok:
                    log.info("UV SAFETY: 主路径/finally 关灯确认")
                else:
                    log.critical("UV SAFETY: 主路径/finally 关灯失败，保留后备截止并重试")
                    retry_ok = _close_light("main_retry")
                    if not retry_ok:
                        log.critical("UV SAFETY: 关灯重试失败 -- 需人工干预关闭 UV 光源!")

                _refresh_timing()
                if timing_info["line1_close_ok"]:
                    if requested_timer is not None:
                        requested_timer.cancel()
                    if safety_timer is not None:
                        safety_timer.cancel()
                elif safety_timer is not None:
                    safety_timer.join(timeout=max(0.0, uv_hard_cutoff_ms / 1000.0 + 0.1))
                    _refresh_timing()

                if timing_info["over_limit"]:
                    log.warning(
                        "UV SAFETY: UV 开启时长 %.1fms 超出请求上限 %dms",
                        timing_info["actual_uv_on_ms"],
                        uv_on_time_ms,
                    )

        # ================================================================
        # 图像转换与保存
        # ================================================================
        log.info("获取到图像: FrameID=%d  %d×%d  PixelFormat=0x%X",
                 raw_image.get_frame_id(), raw_image.get_width(), raw_image.get_height(),
                 raw_image.get_pixel_format())

        # ---- 转换并保存 ----
        pixel_format_value = raw_image.get_pixel_format()
        if pixel_format_value == GxPixelFormatEntry.RGB8:
            numpy_image = raw_image.get_numpy_array()
        else:
            log.info("正在转换像素格式 → RGB8 ...")
            numpy_image = _convert_to_rgb(raw_image, image_convert)

        if numpy_image is None:
            raise RuntimeError("图像数据为空")

        img = Image.fromarray(numpy_image, "RGB")
        img.save(str(save_path), "JPEG", quality=95)
        log.info("图像已保存: %s (%d×%d)", save_path, img.width, img.height)

        if auto_light_control and not timing_info["line1_close_ok"]:
            raise RuntimeError("UV SAFETY: 未能确认 Line1 已关闭，拍照结果不可信")

    finally:
        # 最外层 finally: 确保采集停止、安全定时器按关灯状态处理、相机断开。
        if stream_started:
            try:
                cam.stream_off()
            except Exception:
                log.warning("停止采集失败", exc_info=True)
        if requested_timer is not None and timing_info.get("line1_close_ok"):
            requested_timer.cancel()
        if safety_timer is not None and timing_info.get("line1_close_ok"):
            safety_timer.cancel()
        # 复位触发模式: 把相机留成连续采集态, 供下一个消费者(GxViewer/下次拍照)直接取流。
        # 否则相机停在软触发 On 态, 别的软件"开始采集"会 0 帧/0 带宽(等一个永不到来的触发)。
        if remote is not None:
            try:
                remote.get_enum_feature("TriggerMode").set("Off")
                log.info("触发模式已复位: Off（连续采集）")
            except Exception:
                log.warning("复位 TriggerMode=Off 失败", exc_info=True)
        cam.close_device()
        log.info("相机已断开")

    return save_path, timing_info


# ---------------------------------------------------------------------------
# CLI（调试/手动拍照用）
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="大恒相机拍照脚本（GigE 彩色相机，PALLAS SDK）",
    )
    parser.add_argument("--ip", default=DEFAULT_PARAMS["ip"],
                        help=f"相机 IP 地址（默认: {DEFAULT_PARAMS['ip']})")
    parser.add_argument("--output", "-o", required=True,
                        help="输出图像路径（如 E:/test.jpg）")
    parser.add_argument("--exposure", type=float, default=DEFAULT_PARAMS["exposure_time"],
                        help=f"曝光时间 µs（默认: {DEFAULT_PARAMS['exposure_time']:.0f}）")
    parser.add_argument("--gain", type=float, default=DEFAULT_PARAMS["gain"],
                        help=f"模拟增益（默认: {DEFAULT_PARAMS['gain']}）")
    parser.add_argument("--pixel-format", default=DEFAULT_PARAMS["pixel_format"],
                        help=f"目标像素格式（默认: {DEFAULT_PARAMS['pixel_format']}）")
    parser.add_argument("--trigger", default=DEFAULT_PARAMS["trigger_mode"],
                        choices=["Off", "On"],
                        help=f"触发模式（默认: {DEFAULT_PARAMS['trigger_mode']}）")
    parser.add_argument("--trigger-source", default=DEFAULT_PARAMS["trigger_source"],
                        help=f"触发源（默认: {DEFAULT_PARAMS['trigger_source']}，"
                             "仅 trigger_mode=On 时有效）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_PARAMS["timeout_ms"],
                        help=f"采图超时 ms（默认: {DEFAULT_PARAMS['timeout_ms']}）")
    parser.add_argument("--width", type=int, default=DEFAULT_PARAMS["width"],
                        help="图像宽度（0=不修改）")
    parser.add_argument("--height", type=int, default=DEFAULT_PARAMS["height"],
                        help="图像高度（0=不修改）")
    parser.add_argument("--offset-x", type=int, default=DEFAULT_PARAMS["offset_x"],
                        help="ROI X 偏移")
    parser.add_argument("--offset-y", type=int, default=DEFAULT_PARAMS["offset_y"],
                        help="ROI Y 偏移")
    parser.add_argument("--light-line", default=DEFAULT_PARAMS["light_line"],
                        choices=["Line1", "Line2", "Line3"],
                        help=f"光源连接的物理 I/O 线（默认: {DEFAULT_PARAMS['light_line']}，"
                             "Line1=Pin7/8 光耦输出）")
    parser.add_argument("--no-light-control", action="store_true",
                        help="禁用自动光源控制（默认拍照前开/后关光源）")
    parser.add_argument("--uv-on-time-ms", type=int, default=DEFAULT_PARAMS["uv_on_time_ms"],
                        help=f"UV 光源允许开启时长 ms（默认: {DEFAULT_PARAMS['uv_on_time_ms']}）")
    parser.add_argument("--uv-hard-cutoff-ms", type=int, default=DEFAULT_PARAMS["uv_hard_cutoff_ms"],
                        help=f"UV 光源硬截止时限 ms（默认: {DEFAULT_PARAMS['uv_hard_cutoff_ms']}）")

    args = parser.parse_args()

    params = {
        "ip": args.ip,
        "exposure_time": args.exposure,
        "gain": args.gain,
        "pixel_format": args.pixel_format,
        "trigger_mode": args.trigger,
        "trigger_source": args.trigger_source,
        "timeout_ms": args.timeout,
        "width": args.width,
        "height": args.height,
        "offset_x": args.offset_x,
        "offset_y": args.offset_y,
        "light_line": args.light_line,
        "auto_light_control": not args.no_light_control,
        "uv_on_time_ms": args.uv_on_time_ms,
        "uv_hard_cutoff_ms": args.uv_hard_cutoff_ms,
    }

    try:
        path, timing = capture(Path(args.output), params)
        print(f"OK: {path}")
        print(f"Timing: actual_uv_on_ms={timing['actual_uv_on_ms']:.0f}, "
              f"over_limit={timing['over_limit']}, "
              f"line1_close_ok={timing['line1_close_ok']}, "
              f"trigger_mode={timing['trigger_mode_used']}")
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
