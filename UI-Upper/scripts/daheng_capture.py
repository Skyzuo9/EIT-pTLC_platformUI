#!/usr/bin/env python3
"""大恒相机拍照脚本（独立可运行 + 可导入模块）

基于大恒 PALLAS SDK (gxipy v2.0.2512) 的 GigE 彩色相机单帧拍照。

使用方式：
    # CLI 模式（调试/手动拍照）
    python scripts/daheng_capture.py --ip 192.168.0.169 --output E:/test.jpg

    # 导入模式（供 DahengCameraService 调用）
    from scripts.daheng_capture import capture, DEFAULT_PARAMS
    params = {**DEFAULT_PARAMS, "exposure_time": 200000.0}
    path = capture(Path("output/after.jpg"), params)

参数设计（params dict 对应 config.example.yaml 的 camera.daheng 段）：
    ip              : str   = "192.168.0.169"  相机 IP 地址
    exposure_time   : float = 1000000.0         曝光时间 (µs)，默认 1000ms
    gain            : float = 1.0              模拟增益
    pixel_format    : str   = "RGB8"            目标像素格式
    trigger_mode    : str   = "Off"             触发模式 (Off=连续采集)
    timeout_ms      : int   = 5000              采图超时 (ms)
    width           : int   = 0                 图像宽度 (0=不修改)
    height          : int   = 0                 图像高度 (0=不修改)
    offset_x        : int   = 0                 ROI X 偏移
    offset_y        : int   = 0                 ROI Y 偏移
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

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
# 将大恒 SDK 加入 sys.path（SDK 位于仓库外 View/dahengCamera/PythonSDK/）
# ---------------------------------------------------------------------------
_SDK_DIR = Path(__file__).resolve().parent.parent.parent / "View" / "dahengCamera" / "PythonSDK"
if str(_SDK_DIR) not in sys.path:
    sys.path.insert(0, str(_SDK_DIR))

import gxipy as gx  # noqa: E402
from gxipy.gxidef import *  # noqa: E402 F403

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认参数（与 config.example.yaml camera.daheng 段同步）
# ---------------------------------------------------------------------------
DEFAULT_PARAMS: dict = {
    "ip": "192.168.0.169",
    "exposure_time": 1_000_000.0,  # µs，默认 500ms
    "gain": 1.0,
    "pixel_format": "RGB8",
    "trigger_mode": "Off",
    "timeout_ms": 2000,
    "width": 0,
    "height": 0,
    "offset_x": 0,
    "offset_y": 0,
    "auto_light_control": True,  # 拍照前开光源，拍照后关（保护光源）
    "light_line": "Line1",  # 光源连接的物理 I/O 线（默认 Line1=Pin7/8 光耦输出）
}


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
# 核心拍照函数
# ---------------------------------------------------------------------------
def capture(save_path: Path, params: dict | None = None) -> Path:
    """从大恒相机拍照并保存为 JPEG。

    Args:
        save_path: 图像保存路径（含文件名，如 output/after.jpg）
        params:   相机参数字典，缺失字段回落到 DEFAULT_PARAMS

    Returns:
        保存后的图像路径

    Raises:
        RuntimeError: 相机未找到 / 拍照失败
    """
    p: dict = {**DEFAULT_PARAMS, **(params or {})}

    ip = str(p["ip"])
    exposure_time = float(p["exposure_time"])
    gain = float(p["gain"])
    pixel_format_str = str(p["pixel_format"])
    trigger_mode_str = str(p["trigger_mode"])
    timeout_ms = int(p["timeout_ms"])
    width = int(p["width"])
    height = int(p["height"])
    offset_x = int(p["offset_x"])
    offset_y = int(p["offset_y"])
    auto_light_control = bool(p["auto_light_control"])
    light_line = str(p["light_line"])

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

    try:
        remote = cam.get_remote_device_feature_control()

        # 打印相机信息
        model = remote.get_string_feature("DeviceModelName").get()
        sn = remote.get_string_feature("DeviceSerialNumber").get()
        log.info("已连接: %s (SN=%s)", model, sn)

        # ---- 创建图像格式转换器 (彩色相机 Bayer→RGB) ----
        image_convert = device_manager.create_image_format_convert()

        # ---- 配置触发模式 ----
        trigger_feature = remote.get_enum_feature("TriggerMode")
        trigger_feature.set(trigger_mode_str)
        log.info("触发模式: %s", trigger_mode_str)

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

        # ---- 开始采集 ----
        cam.stream_on()

        # ---- 拍照前开启光源 ----
        light_ok = False
        if auto_light_control:
            light_ok = _control_light(remote, True, light_line)
            if not light_ok:
                log.warning("自动光源控制已启用但相机不支持任何已知 GPIO 方式，"
                            "请手动控制光源或使用 --no-light-control")

        try:
            # ---- 抓取一帧 ----
            log.info("等待图像 (timeout=%dms)...", timeout_ms)
            raw_image = cam.data_stream[0].get_image(timeout_ms)
            if raw_image is None:
                raise RuntimeError("获取图像超时（相机未返回数据）")

            if raw_image.get_status() != GxFrameStatusList.SUCCESS:
                raise RuntimeError(f"图像状态异常: {raw_image.get_status()}")
        finally:
            # ---- 拍照后关闭光源 ----
            if auto_light_control:
                _control_light(remote, False, light_line)
                # 注：即使开启光源失败也尝试关闭（可能上次成功开启、或相机状态不一致）

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

        # ---- 停止采集 ----
        cam.stream_off()

    finally:
        cam.close_device()
        log.info("相机已断开")

    return save_path


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

    args = parser.parse_args()

    params = {
        "ip": args.ip,
        "exposure_time": args.exposure,
        "gain": args.gain,
        "pixel_format": args.pixel_format,
        "trigger_mode": args.trigger,
        "timeout_ms": args.timeout,
        "width": args.width,
        "height": args.height,
        "offset_x": args.offset_x,
        "offset_y": args.offset_y,
        "light_line": args.light_line,
        "auto_light_control": not args.no_light_control,
    }

    try:
        result = capture(Path(args.output), params)
        print(f"OK: {result}")
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
