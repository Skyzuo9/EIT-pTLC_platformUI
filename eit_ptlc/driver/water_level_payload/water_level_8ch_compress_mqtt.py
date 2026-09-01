#!/usr/bin/env python3
"""
TCL板液位高度检测程序 — 8路版本 + MQTT + 检测参数命令化
每路摄像头独立标定、独立检测，统一在一个窗口以 2×4 网格显示。
通过 MQTT 上报液位数据，并接收上位机下发的配置/控制/算法参数指令。

MQTT 主题设计:
  上行(设备→上位机):
    water_level/data              — 所有通道液位数据(JSON), 周期上报
    water_level/status            — 设备状态(上线/离线/告警)
    water_level/ch/{id}/data      — 单通道液位数据(JSON)
    water_level/alarm             — 液位报警
    water_level/param/detect      — 检测参数返回
    water_level/ack               — 命令执行确认/错误

  下行(上位机→设备):
    water_level/cmd/reset          — 重载配置 (保留校准, 从文件恢复 ROI+参数)
    water_level/cmd/set_interval   — 设置上报周期
    water_level/cmd/set_threshold  — 设置报警阈值
    water_level/cmd/query_status   — 查询状态
    water_level/cmd/restart_camera — 重启摄像头
    water_level/cmd/set_detect_param  — 设置检测算法参数
    water_level/cmd/get_detect_param  — 查询检测算法参数
    water_level/cmd/save_detect_param — 保存参数到配置文件
    water_level/cmd/load_detect_param — 从配置文件加载参数
    water_level/cmd/stream_start   — 激活 MJPEG HTTP 流
    water_level/cmd/stream_stop    — 停用 MJPEG HTTP 流
    water_level/cmd/set_roi        — 人工设定 ROI (新增)
    water_level/cmd/clear_roi      — 清除人工 ROI (新增)
    water_level/cmd/save_calibration — 持久化校准+ROI (新增)
    water_level/cmd/reload_config  — 从文件重载配置 (新增)
    water_level/cmd/factory_reset  — 全部清除回出厂状态 (新增)
    water_level/cmd/capture_reference — 拍摄干板参考图用于差分检测 (新增)
"""

import cv2
import numpy as np
import time
import argparse
import subprocess
import sys
import threading
import json
import os
from collections import deque

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("[WARN] paho-mqtt 未安装, MQTT功能不可用. pip install paho-mqtt")


# ====================================================================
# 检测参数默认值 & 校验规则
# ====================================================================
DEFAULT_DETECT_PARAMS = {
    "height_offset_cm":     0.0,
    "height_gain":          1.0,
    "roi_sobel_ksize":      5,
    "roi_crop_x":           0.10,
    "roi_crop_y":           0.10,
    "water_sobely_ksize":   -1,
    "water_edge_threshold": 10.0,
    "water_blur_ksize":     5,
    "flow_direction":       "left_to_right",
    # ★ 两区对比验证 + 前沿状态机 参数
    "front_contrast_threshold": 0.12,
    "front_zone_width":         20,
    "front_zone_gap":           3,
    "front_arrival_frames":     30,
    "front_departure_frames":   60,
    # ★ 信号显著性检验 (防止无信号时的噪声误检)
    "water_snr_threshold":      3.5,   # 梯度峰值/中位数 最小倍数
    "water_diff_threshold":     5.0,   # 差分图均值下限 (有参考图时)
    # ★ 逐行边缘检测 (解决U形/倾斜前沿的均值投影抹平问题)
    "front_valid_row_ratio":    0.20,  # 有效行/总行 最小比例, 低于此值视为无信号
}

PARAM_VALIDATORS = {
    "height_offset_cm":     lambda v: isinstance(v, (int, float)) and -50.0 <= v <= 50.0,
    "height_gain":          lambda v: isinstance(v, (int, float)) and 0.5 <= v <= 2.0,
    "roi_sobel_ksize":      lambda v: v in (-1, 1, 3, 5, 7),
    "roi_crop_x":           lambda v: isinstance(v, (int, float)) and 0.0 <= v < 0.5,
    "roi_crop_y":           lambda v: isinstance(v, (int, float)) and 0.0 <= v < 0.5,
    "water_sobely_ksize":   lambda v: v in (-1, 1, 3, 5, 7),
    "water_edge_threshold": lambda v: isinstance(v, (int, float)) and 0.0 <= v <= 100.0,
    "water_blur_ksize":     lambda v: v in (1, 3, 5, 7, 9),
    "flow_direction":       lambda v: v in ("bottom_to_top", "left_to_right", "right_to_left"),
    # ★ 两区对比验证 + 前沿状态机
    "front_contrast_threshold": lambda v: isinstance(v, (int, float)) and 0.02 <= v <= 0.80,
    "front_zone_width":         lambda v: isinstance(v, (int, float)) and 10 <= v <= 60,
    "front_zone_gap":           lambda v: isinstance(v, (int, float)) and 1 <= v <= 10,
    "front_arrival_frames":     lambda v: isinstance(v, (int, float)) and 10 <= v <= 300,
    "front_departure_frames":   lambda v: isinstance(v, (int, float)) and 10 <= v <= 600,
    # ★ 信号显著性检验
    "water_snr_threshold":      lambda v: isinstance(v, (int, float)) and 1.2 <= v <= 15.0,
    "water_diff_threshold":     lambda v: isinstance(v, (int, float)) and 0.0 <= v <= 50.0,
    # ★ 逐行边缘检测
    "front_valid_row_ratio":    lambda v: isinstance(v, (int, float)) and 0.10 <= v <= 0.80,
}

PARAM_HINTS = {
    "height_offset_cm":     "-50.0 ~ 50.0",
    "height_gain":          "0.5 ~ 2.0",
    "roi_sobel_ksize":      "-1, 1, 3, 5, 7",
    "roi_crop_x":           "0.0 ~ 0.4",
    "roi_crop_y":           "0.0 ~ 0.4",
    "water_sobely_ksize":   "-1, 1, 3, 5, 7",
    "water_edge_threshold": "0.0 ~ 100.0",
    "water_blur_ksize":     "1, 3, 5, 7, 9",
    "flow_direction":       "bottom_to_top, left_to_right, right_to_left",
    # ★ 两区对比验证 + 前沿状态机
    "front_contrast_threshold": "0.02 ~ 0.80 (归一化, 越大越严格)",
    "front_zone_width":         "10 ~ 60",
    "front_zone_gap":           "1 ~ 10",
    "front_arrival_frames":     "10 ~ 300",
    "front_departure_frames":   "10 ~ 600",
    # ★ 信号显著性检验
    "water_snr_threshold":      "1.2 ~ 15.0 (峰值/背景中位数, 越大越严格)",
    "water_diff_threshold":     "0.0 ~ 50.0 (差分图均值下限, 0=不检查)",
    # ★ 逐行边缘检测
    "front_valid_row_ratio":    "0.10 ~ 0.80 (有效行/总行最小比例, 低于此值→无信号)",
}

CONFIG_FILE = "water_level_config.json"


class NumpyEncoder(json.JSONEncoder):
    """自定义 JSON 编码器，将 numpy 标量转为 Python 原生类型。
    用于防御所有 numpy 类型泄漏到 json.dump 的路径。"""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


# ====================================================================
# MQTT 通信管理器
# ====================================================================
class MQTTManager:

    TOPIC_DATA_ALL    = "water_level/data"
    TOPIC_STATUS      = "water_level/status"
    TOPIC_CH_DATA     = "water_level/ch/{}/data"
    TOPIC_ALARM       = "water_level/alarm"
    TOPIC_PARAM       = "water_level/param/detect"
    TOPIC_ACK         = "water_level/ack"

    TOPIC_CMD_PREFIX            = "water_level/cmd/"
    TOPIC_CMD_RESET             = "water_level/cmd/reset"
    TOPIC_CMD_SET_INTERVAL      = "water_level/cmd/set_interval"
    TOPIC_CMD_SET_THRESHOLD     = "water_level/cmd/set_threshold"
    TOPIC_CMD_QUERY_STATUS      = "water_level/cmd/query_status"
    TOPIC_CMD_RESTART_CAM       = "water_level/cmd/restart_camera"
    TOPIC_CMD_SET_DETECT_PARAM  = "water_level/cmd/set_detect_param"
    TOPIC_CMD_GET_DETECT_PARAM  = "water_level/cmd/get_detect_param"
    TOPIC_CMD_SAVE_DETECT_PARAM = "water_level/cmd/save_detect_param"
    TOPIC_CMD_LOAD_DETECT_PARAM = "water_level/cmd/load_detect_param"
    TOPIC_CMD_STREAM_START      = "water_level/cmd/stream_start"
    TOPIC_CMD_STREAM_STOP       = "water_level/cmd/stream_stop"
    TOPIC_CMD_DIAG_CAMERA       = "water_level/cmd/diag_camera"
    TOPIC_CMD_SET_ACTIVE_CHANNELS = "water_level/cmd/set_active_channels"
    TOPIC_CMD_SET_ROI          = "water_level/cmd/set_roi"
    TOPIC_CMD_CLEAR_ROI        = "water_level/cmd/clear_roi"
    TOPIC_CMD_SAVE_CALIBRATION = "water_level/cmd/save_calibration"
    TOPIC_CMD_RELOAD_CONFIG    = "water_level/cmd/reload_config"
    TOPIC_CMD_FACTORY_RESET    = "water_level/cmd/factory_reset"
    TOPIC_CMD_CAPTURE_REFERENCE = "water_level/cmd/capture_reference"
    TOPIC_CMD_START_CALIBRATE  = "water_level/cmd/start_calibrate"
    TOPIC_CMD_STOP_CALIBRATE   = "water_level/cmd/stop_calibrate"
    TOPIC_CMD_SET_CALIBRATION  = "water_level/cmd/set_calibration"
    TOPIC_CMD_GET_CALIBRATION  = "water_level/cmd/get_calibration"

    def __init__(self, broker_ip, broker_port=1883, client_id=None, keepalive=60):
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.keepalive = keepalive
        self.connected = False

        if client_id is None:
            client_id = f"orangepi_wl_{os.getpid()}"
        self._client_id_str = client_id

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        self.client.on_connect    = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message    = self._on_message

        will_payload = json.dumps({
            "status": "offline",
            "client_id": client_id,
            "timestamp": time.time(),
        })
        self.client.will_set(self.TOPIC_STATUS, will_payload, qos=1, retain=True)

        self._cmd_handlers = {}
        self.report_interval = 1.0
        self.alarm_min = None
        self.alarm_max = None

    def connect(self):
        try:
            self.client.connect(self.broker_ip, self.broker_port, self.keepalive)
            self.client.loop_start()
            print(f"[MQTT] 正在连接 {self.broker_ip}:{self.broker_port} ...")
            return True
        except Exception as e:
            print(f"[MQTT] 连接失败: {e}")
            return False

    def disconnect(self):
        self.publish_status("offline")
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] 已断开")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.connected = True
            print(f"[MQTT] 已连接到 {self.broker_ip}:{self.broker_port}")
            self.client.subscribe(self.TOPIC_CMD_PREFIX + "#", qos=1)
            print(f"[MQTT] 已订阅 {self.TOPIC_CMD_PREFIX}#")
            self.publish_status("online")
        else:
            print(f"[MQTT] 连接失败 rc={rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self.connected = False
        if rc != 0:
            print(f"[MQTT] 意外断开 rc={rc}, 将自动重连...")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = msg.payload.decode("utf-8", errors="replace")

        print(f"[MQTT RX] {topic}: {payload}")

        handler = self._cmd_handlers.get(topic)
        if handler:
            try:
                handler(payload)
            except Exception as e:
                print(f"[MQTT] 处理指令异常 {topic}: {e}")
        else:
            print(f"[MQTT] 未注册的指令主题: {topic}")

    def register_handler(self, topic, callback):
        self._cmd_handlers[topic] = callback

    def publish_all_channels(self, channel_data_list):
        if not self.connected:
            return
        payload = {
            "device_id": self._client_id_str,
            "timestamp": time.time(),
            "channels": channel_data_list,
        }
        self.client.publish(self.TOPIC_DATA_ALL,
                            json.dumps(payload, ensure_ascii=False), qos=0)
        for ch_data in channel_data_list:
            ch_id = ch_data.get("channel", 0)
            self.client.publish(self.TOPIC_CH_DATA.format(ch_id),
                                json.dumps(ch_data, ensure_ascii=False), qos=0)

    def publish_alarm(self, channel_id, height_cm, alarm_type):
        if not self.connected:
            return
        payload = {"channel": channel_id, "height_cm": height_cm,
                   "alarm_type": alarm_type, "timestamp": time.time()}
        self.client.publish(self.TOPIC_ALARM,
                            json.dumps(payload, ensure_ascii=False), qos=1)
        print(f"[MQTT] 报警 CH{channel_id}: {alarm_type} {height_cm:.2f}cm")

    def publish_status(self, status, extra=None):
        payload = {"status": status, "client_id": self._client_id_str,
                   "timestamp": time.time()}
        if extra:
            payload.update(extra)
        try:
            self.client.publish(self.TOPIC_STATUS,
                                json.dumps(payload, ensure_ascii=False),
                                qos=1, retain=True)
        except Exception:
            pass

    def publish_ack(self, cmd, result, channel=None, extra=None):
        payload = {"cmd": cmd, "result": result, "timestamp": time.time()}
        if channel is not None:
            payload["channel"] = channel
        if extra:
            payload.update(extra)
        try:
            self.client.publish(self.TOPIC_ACK,
                                json.dumps(payload, ensure_ascii=False), qos=1)
        except Exception:
            pass

    def publish_detect_params(self, device_id, channels_params):
        payload = {"device_id": device_id, "timestamp": time.time(),
                   "channels": channels_params}
        try:
            self.client.publish(self.TOPIC_PARAM,
                                json.dumps(payload, ensure_ascii=False), qos=1)
        except Exception:
            pass


# ====================================================================
# 单通道检测器
# ====================================================================
class ChannelDetector:
    # 通道状态机 (上位机指令驱动)
    STATE_IDLE = "idle"         # 摄像头关闭, 标定参数保留
    STATE_CAPTURE = "capture"   # 采集运行中, 液位检测+MQTT上报
    STATE_STREAM = "stream"     # CAPTURE + MJPEG HTTP 流
    STATE_ERROR = "error"       # 启动失败/运行时异常

    def __init__(self, channel_id, camera_device, tl_bl_real_cm,
                 cap_width=1920, cap_height=1080, calibrate_mode=False,
                 cap_fps=30, exposure_time=312, awb_temp=4600):
        self.channel_id = channel_id + 1
        self.camera_device = camera_device
        self.tl_bl_real_cm = tl_bl_real_cm
        self.cap_width = cap_width
        self.cap_height = cap_height
        self.cap_fps = cap_fps
        # 手动曝光/白平衡定值 (见 _lock_camera_controls): 上位机差分检测要求"参考图与检测帧同曝光",
        # 自动曝光一动, 参考基线立即作废
        self.exposure_time = int(exposure_time)
        self.awb_temp = int(awb_temp)
        self._calibrate_mode = calibrate_mode

        self.calibrated = False
        self.rotation_angle_deg = 0.0
        self.tl_bl_pixel_length = 0.0
        self.scale_factor = 0.0
        self.qr_id = "Unknown"

        self.rotation_matrix = None
        self.rotated_size = None
        self.frame_center = None
        self.qr_corners_original = None

        self.roi_bbox = None
        self.reference_y = 0
        self.reference_x = 0.0
        self.roi_mode = "auto"  # "auto" | "manual"

        self.height_buffer = deque(maxlen=300)
        self.latest_height_cm = None
        self.latest_waterline_y = None

        self.cap = None
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.latest_rendered = None       # 主循环 process_frame() 后缓存
        self.rendered_lock = threading.Lock()
        self.running = False

        self.qr_detector = cv2.QRCodeDetector()

        self._fps_frame_count = 0
        self._fps_last_time = time.time()
        self.current_fps = 0.0

        self._qr_interval = 5.0
        self._last_qr_time = 0.0
        self._just_calibrated = False  # 标定模式自动保存触发标志

        # ★ 检测算法参数 (每通道独立)
        self.detect_params = dict(DEFAULT_DETECT_PARAMS)
        # 根据通道号自动设定液流方向 (展开组1: CH1-4 右→左, 展开组2: CH5-8 左→右)
        if self.channel_id <= 4:
            self.detect_params["flow_direction"] = "right_to_left"
        else:
            self.detect_params["flow_direction"] = "left_to_right"

        # ★ 前沿状态机: WAITING | TRACKING | GONE
        self._front_state = "WAITING"
        self._front_ok_counter = 0    # 连续满足 contrast 条件的帧数
        self._front_fail_counter = 0  # 连续不满足 contrast 条件的帧数

        # ★ P0: 参考图差分检测
        self.ref_gray = None           # 干板参考图 (灰度ROI)
        self._capture_ref_pending = False  # MQTT 触发后下一帧捕获

        # ★ P2: 历史位置软约束
        self._last_edge_idx = None     # 上一帧候选边像素索引

        # ★ 调试可视化中间结果缓存 (仅当 _debug_enabled 时写入)
        self._debug_enabled = False
        self._debug_gray_original = None   # 差分前 ROI 灰度 (Panel 1)
        self._debug_gray_diff = None       # 差分后 ROI 灰度 (Panel 2)
        self._debug_profile = None         # 原始梯度投影 (Panel 3 灰虚线)
        self._debug_smoothed = None        # 平滑后 profile (Panel 3 蓝实线)
        self._debug_edge_idx = None        # 检测到的峰值索引
        self._debug_edge_val = None        # 峰值梯度幅值
        self._debug_wet_val = None         # wet zone 中位数
        self._debug_dry_val = None         # dry zone 中位数
        self._debug_contrast = None        # 对比度值
        self._debug_contrast_ok = False    # 对比度是否通过
        self._debug_lo = None              # P2 约束下界
        self._debug_hi = None              # P2 约束上界
        self._debug_detect_ok = False      # 检测成功 (h_cm 非 None)
        self._debug_front_state = "WAITING"  # 前沿状态机状态
        self._debug_row_positions = None   # ★ 逐行边缘位置 (NaN=无效, 供U形曲线绘制)
        self._debug_lock = threading.Lock()

        # 通道状态机 (上位机指令驱动)
        self.state = self.STATE_IDLE
        self._state_lock = threading.Lock()

    # ---------- 摄像头 ----------
    def _lock_camera_controls(self) -> bool:
        """锁死本路相机的自动曝光与自动白平衡为定值 (返回是否成功)。

        功能:
            经 v4l2-ctl 把 auto_exposure 切手动并写入 exposure_time_absolute,
            关掉 white_balance_automatic 并写入 white_balance_temperature, 写后回读校验。

        为何必须锁 (2026-07-26 真机事故根因):
            上位机差分检测拿"干板参考图"与当前帧比亮度, 判湿阈值只有 5%。UVC 默认
            auto_exposure=3 (Aperture Priority) 会自行改曝光, 整帧亮度一动就超过 5%,
            于是整块 ROI 同时翻成"已浸润" —— 实测 CH1 出现 6 秒内 0%→100%→0% 的整体
            翻转, 骗过 wait_level 触发了自动排液。锁定后实测帧间均亮相对标准差 0.036%。

        参数取值 (实测自 orangepi 现役相机 v4l2-ctl --list-ctrls-menus):
            auto_exposure           menu, 1=Manual / 3=Aperture Priority(默认)
            exposure_time_absolute  int, 1~10000 (单位 100us), 设备默认 312
            white_balance_automatic bool, 默认 1
            white_balance_temperature int, 2800~6500, 设备默认 4600
        顺序不可颠倒: exposure_time_absolute 在自动曝光下 flags=inactive 写不进去,
        white_balance_temperature 同理依赖先关自动白平衡。
        """
        pairs = [
            ("auto_exposure", 1),                              # 先切手动, 下一条才可写
            ("exposure_time_absolute", self.exposure_time),
            ("white_balance_automatic", 0),                    # 先关自动, 下一条才可写
            ("white_balance_temperature", self.awb_temp),
        ]
        try:
            for name, value in pairs:
                subprocess.run(
                    ["v4l2-ctl", "-d", self.camera_device, f"--set-ctrl={name}={value}"],
                    check=True, capture_output=True, timeout=5)
            # 回读校验: 写成功不代表驱动接受 (控件 inactive 时 v4l2-ctl 仍返回 0)
            out = subprocess.run(
                ["v4l2-ctl", "-d", self.camera_device,
                 "--get-ctrl=auto_exposure,exposure_time_absolute,white_balance_automatic"],
                check=True, capture_output=True, timeout=5, text=True).stdout
            readback = {}
            for line in out.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    readback[key.strip()] = val.strip().split()[0] if val.strip() else ""
            expect = {"auto_exposure": "1",
                      "exposure_time_absolute": str(self.exposure_time),
                      "white_balance_automatic": "0"}
            bad = {k: (readback.get(k), v) for k, v in expect.items() if readback.get(k) != v}
            if bad:
                print(f"[CH{self.channel_id}] ✗ 曝光锁定回读不符: {bad}")
                return False
        except Exception as e:
            print(f"[CH{self.channel_id}] ✗ 曝光锁定失败: {e}")
            return False
        print(f"[CH{self.channel_id}] ✓ 曝光已锁定 exposure={self.exposure_time} "
              f"awb=off wb_temp={self.awb_temp}")
        return True

    def start_capture(self):
        self.cap = cv2.VideoCapture(self.camera_device)
        if not self.cap.isOpened():
            print(f"[CH{self.channel_id}] 无法打开摄像头 {self.camera_device}")
            with self._state_lock:
                self.state = self.STATE_ERROR
            return False

        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cap_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cap_height)
        self.cap.set(cv2.CAP_PROP_FPS, self.cap_fps)

        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc_int = int(self.cap.get(cv2.CAP_PROP_FOURCC))
        fourcc_str = "".join([chr((fourcc_int >> 8*i) & 0xFF) for i in range(4)])

        # MJPG 格式协商警告: 若驱动未接受 MJPG 请求而退化为 YUYV,
        # 带宽需求将大幅增加, 可能触发 USB 等时传输丢帧
        if fourcc_str != "MJPG":
            print(f"[CH{self.channel_id}] ⚠ 格式={fourcc_str} 而非 MJPG, "
                  f"带宽需求偏高, 建议检查摄像头固件")

        # 锁曝光失败即拒绝供帧: 未锁曝光的帧会让上位机差分检测整块误判 (见 _lock_camera_controls),
        # 宁可这一路进 ERROR 让上位机拉帧失败升人工门, 也不供不可信的帧去驱动自动排液
        if not self._lock_camera_controls():
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
            with self._state_lock:
                self.state = self.STATE_ERROR
            return False

        self.running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()
        self._capture_start_time = time.time()
        self._actual_fourcc = fourcc_str  # 保存格式协商结果供诊断用
        self._actual_resolution = (actual_w, actual_h)
        with self._state_lock:
            self.state = self.STATE_CAPTURE
        print(f"[CH{self.channel_id}] 摄像头 {self.camera_device} 已启动 "
              f"({actual_w}x{actual_h} {fourcc_str})")
        return True

    def restart_capture(self):
        """外部冷重启 (MQTT restart_camera / ERROR 态激活): 停线程→释放→重开。
        注意: 仅用于通道非运行/正在(重)激活的场景; 运行中相机的读失败/定格自愈已改由
        _capture_loop 在本线程内 _reopen_capture_inloop 处理 (避免跨线程 release↔read 竞态)。"""
        print(f"[CH{self.channel_id}] 正在重启摄像头 {self.camera_device} ...")
        self.running = False
        time.sleep(0.5)
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
        time.sleep(0.5)
        return self.start_capture()

    def _reopen_capture_inloop(self) -> bool:
        """★ 在采集线程内重开相机 (单写者, 无跨线程 release↔read 竞态)。

        供 _capture_loop 自身在"读失败超阈值"或"画面定格"时调用: 释放旧 cap → 新开 →
        重设 MJPG/分辨率/fps。失败返回 False (self.cap 置 None), 交由外层退避重试。
        不新起线程、不改 self.running —— 全程本线程独占 self.cap 生命周期。"""
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        self.cap = None
        try:
            cap = cv2.VideoCapture(self.camera_device)
        except Exception as e:
            print(f"[CH{self.channel_id}] 重开相机构造异常: {e}")
            return False
        if not cap.isOpened():
            try:
                cap.release()
            except Exception:
                pass
            return False
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cap_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cap_height)
        cap.set(cv2.CAP_PROP_FPS, self.cap_fps)
        self.cap = cap
        # 重开必须重锁: USB 重枚举会把 v4l2 控件复位成出厂自动曝光, 不重锁则自愈后的帧
        # 与本次 run 的参考图不同曝光 (同 start_capture, 失败即拒绝供帧)
        if not self._lock_camera_controls():
            try:
                cap.release()
            except Exception:
                pass
            self.cap = None
            return False
        self._capture_start_time = time.time()
        try:
            fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
            self._actual_fourcc = "".join(chr((fourcc_int >> 8*i) & 0xFF) for i in range(4))
            self._actual_resolution = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                       int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        except Exception:
            pass
        print(f"[CH{self.channel_id}] ✓ 相机已在采集线程内重开 {self.camera_device}")
        return True

    # 读失败自愈参数
    _FAILS_BEFORE_BLANK = 15      # 连续失败达此值 → 清 latest_frame (/frame 返 503, 暴露无信号, 不再骗定格图)
    _FAILS_BEFORE_REOPEN = 30     # 连续失败达此值 → 判定该路挂了, 开始带退避重开 (~0.3-0.5s)
    _REOPEN_BACKOFF = (1.0, 2.0, 5.0, 10.0, 30.0)  # 重开退避(s), 封顶 30s: 防死机相机疯狂重开霸占 USB 连累幸存路

    def _capture_loop(self):
        fail_count = 0
        stale_count = 0
        prev_fingerprint = None
        reopen_attempts = 0
        next_reopen_at = 0.0      # time.monotonic() 门: 到点才允许下一次重开 (退避)
        blanked = False           # 是否已因持续失败清空 latest_frame
        while self.running:
            try:
                ret, frame = self.cap.read() if self.cap is not None else (False, None)
            except cv2.error as e:
                ret, frame = False, None
                if fail_count == 0:
                    print(f"[CH{self.channel_id}] ⚠ cv2.error on cap.read(): {e} "
                          f"device={self.camera_device} "
                          f"negotiated={getattr(self, '_actual_fourcc', '?')}")
            if not ret:
                fail_count += 1
                stale_count = 0
                if fail_count == 1:
                    # ★ 详细诊断: 记录失败时刻的摄像头状态，帮助定位根因
                    try:
                        fourcc = int(self.cap.get(cv2.CAP_PROP_FOURCC))
                        fourcc_s = "".join(chr((fourcc >> 8*i) & 0xFF) for i in range(4))
                    except Exception:
                        fourcc_s = "N/A"
                    try:
                        pos_msec = self.cap.get(cv2.CAP_PROP_POS_MSEC)
                    except Exception:
                        pos_msec = -1
                    try:
                        cur_fps = self.cap.get(cv2.CAP_PROP_FPS)
                    except Exception:
                        cur_fps = -1
                    uptime = time.time() - getattr(self, '_capture_start_time', 0)
                    negotiated = getattr(self, '_actual_fourcc', '?')
                    res = getattr(self, '_actual_resolution', (0, 0))

                    print(f"[CH{self.channel_id}] ⚠ cap.read() 开始失败! "
                          f"device={self.camera_device} "
                          f"negotiated={negotiated} "
                          f"current_fourcc={fourcc_s} "
                          f"resolution={res[0]}x{res[1]} "
                          f"fps={cur_fps:.1f} "
                          f"pos_msec={pos_msec:.0f} "
                          f"uptime={uptime:.0f}s "
                          f"fail_count_before={fail_count - 1}")
                elif fail_count % 300 == 0:
                    print(f"[CH{self.channel_id}] ⚠ 已连续 {fail_count} 次读取失败")

                # ★ 持续失败 → 清最新帧: /frame 返 503, 录制器/实时画面显示"无信号"而非静默定格
                if fail_count == self._FAILS_BEFORE_BLANK and not blanked:
                    with self.frame_lock:
                        self.latest_frame = None
                    blanked = True
                    print(f"[CH{self.channel_id}] ⚠ 连续{fail_count}次失败, 已清空最新帧 (/frame 将返 503 无信号)")

                # ★ 失败超阈值 → 在本线程内带退避重开相机 (无跨线程竞态)
                if fail_count >= self._FAILS_BEFORE_REOPEN:
                    now = time.monotonic()
                    if now >= next_reopen_at:
                        delay = self._REOPEN_BACKOFF[min(reopen_attempts, len(self._REOPEN_BACKOFF) - 1)]
                        reopen_attempts += 1
                        print(f"[CH{self.channel_id}] ⚠ 连续{fail_count}次读取失败 → 第{reopen_attempts}次重开相机 "
                              f"(失败则退避{delay:.0f}s后再试)")
                        self._reopen_capture_inloop()
                        next_reopen_at = time.monotonic() + delay
                time.sleep(0.01)
                continue

            # 读取成功
            if fail_count >= self._FAILS_BEFORE_REOPEN or reopen_attempts > 0:
                print(f"[CH{self.channel_id}] ✓ 采集已恢复 "
                      f"(之前 {fail_count} 次失败, {reopen_attempts} 次重开)")
            fail_count = 0
            reopen_attempts = 0
            next_reopen_at = 0.0
            blanked = False

            # ★ 画面停滞检测: 连续完全相同的帧 → UVC 驱动可能在返回陈旧缓冲区
            fp = int(frame.sum())
            if prev_fingerprint is not None and fp == prev_fingerprint:
                stale_count += 1
                if stale_count == 60:
                    print(f"[CH{self.channel_id}] ⚠ 画面疑似定格! "
                          f"连续{stale_count}帧像素完全相同, "
                          f"可能是UVC驱动软状态异常, 在采集线程内重开相机...")
                    # ★ 本线程内重开 (旧版异步 restart_capture 会与本线程 cap.read() 抢 cap + 起双采集线程)
                    self._reopen_capture_inloop()
                    stale_count = 0
                    prev_fingerprint = None
                    continue
            else:
                if stale_count >= 60:
                    print(f"[CH{self.channel_id}] ✓ 画面已恢复")
                stale_count = 0
            prev_fingerprint = fp

            with self.frame_lock:
                self.latest_frame = frame

    def get_frame(self):
        with self.frame_lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def get_rendered(self):
        """MJPEG HTTP 线程安全读取：返回最近一次 process_frame() 的渲染结果"""
        with self.rendered_lock:
            return (self.latest_rendered.copy()
                    if self.latest_rendered is not None else None)

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
        with self._state_lock:
            self.state = self.STATE_IDLE

    # ---------- 状态机转换 (上位机指令驱动) ----------
    def activate_capture(self):
        """IDLE → CAPTURE: 启动采集, 保留已有标定参数"""
        with self._state_lock:
            if self.state != self.STATE_IDLE:
                return False
        success = self.start_capture()
        if success:
            print(f"[CH{self.channel_id}] 摄像头激活 "
                  f"(标定保留: {self.calibrated})")
        else:
            with self._state_lock:
                self.state = self.STATE_ERROR
            print(f"[CH{self.channel_id}] 摄像头激活失败!")
        return success

    def deactivate(self):
        """CAPTURE/STREAM → IDLE: 停止采集, 保留标定参数和 ROI"""
        with self._state_lock:
            if self.state not in (self.STATE_CAPTURE, self.STATE_STREAM):
                return
            self.running = False
            if self.cap:
                self.cap.release()
                self.cap = None
            # 清除最新帧, 避免主循环处理过期数据
            with self.frame_lock:
                self.latest_frame = None
            with self.rendered_lock:
                self.latest_rendered = None
            self.state = self.STATE_IDLE
            # 清除运行时检测状态
            self.ref_gray = None
            self._capture_ref_pending = False
            self._last_edge_idx = None
            self._debug_row_positions = None
            self._front_state = "WAITING"
            self._front_ok_counter = 0
            self._front_fail_counter = 0
            self.height_buffer.clear()
            # calibrated / roi_bbox / rotation_* / scale_factor 全部保留
            print(f"[CH{self.channel_id}] 摄像头已停用 (标定保留: {self.calibrated})")

    def activate_stream(self):
        """CAPTURE → STREAM"""
        with self._state_lock:
            if self.state == self.STATE_CAPTURE:
                self.state = self.STATE_STREAM
                return True
            return False

    def deactivate_stream(self):
        """STREAM → CAPTURE"""
        with self._state_lock:
            if self.state == self.STATE_STREAM:
                self.state = self.STATE_CAPTURE
                return True
            return False

    def get_report_str(self):
        if self.state == self.STATE_IDLE:
            tag = " (标定)" if self.calibrated else ""
            return f"[CH{self.channel_id}]  IDLE{tag}"
        if self.state == self.STATE_ERROR:
            return f"[CH{self.channel_id}]  ERROR"
        if not self.calibrated:
            return f"[CH{self.channel_id}] ---.-- cm"
        if self.latest_height_cm is not None:
            return f"[CH{self.channel_id}] {self.latest_height_cm:6.2f} cm"
        else:
            return f"[CH{self.channel_id}]   N/A  "

    def get_status_dict(self):
        return {
            "channel": self.channel_id,
            "device": self.camera_device,
            "qr_id": self.qr_id,
            "height_cm": float(round(self.latest_height_cm, 3))
                         if self.latest_height_cm is not None else None,
            "calibrated": self.calibrated,
            "has_roi": self.roi_bbox is not None,
            "roi_mode": self.roi_mode,
            "reference_y": float(self.reference_y),
            "reference_x": float(self.reference_x),
            "flow_direction": self.detect_params.get("flow_direction", "left_to_right"),
            "rotation_deg": float(self.rotation_angle_deg),
            "scale_cm_per_px": float(self.scale_factor),
            "state": self.state,
            "front_state": self._front_state,
            "timestamp": time.time(),
        }

    def get_detect_params_dict(self):
        """返回当前检测参数, 供 MQTT 上报"""
        d = dict(self.detect_params)
        d["channel"] = self.channel_id
        return d

    def get_diagnostic_info(self):
        """返回摄像头诊断信息, 供 MQTT diag_camera 命令查询"""
        info = {
            "channel": self.channel_id,
            "device": self.camera_device,
            "running": self.running,
            "calibrated": self.calibrated,
            "negotiated_fourcc": getattr(self, '_actual_fourcc', 'N/A'),
            "resolution": "{}x{}".format(*getattr(self, '_actual_resolution', (0, 0))),
            "uptime_sec": time.time() - getattr(self, '_capture_start_time', 0),
            "current_fps": self.current_fps,
            "height_cm": float(round(self.latest_height_cm, 3))
                         if self.latest_height_cm is not None else None,
            "has_roi": self.roi_bbox is not None,
            "timestamp": time.time(),
        }
        # 尝试读取当前摄像头实时状态
        if self.cap and self.cap.isOpened():
            try:
                info["cap_fourcc_now"] = "".join(
                    chr((int(self.cap.get(cv2.CAP_PROP_FOURCC)) >> 8*i) & 0xFF)
                    for i in range(4))
            except Exception:
                info["cap_fourcc_now"] = "error"
            try:
                info["cap_fps_now"] = self.cap.get(cv2.CAP_PROP_FPS)
            except Exception:
                info["cap_fps_now"] = -1
            try:
                info["cap_pos_msec"] = self.cap.get(cv2.CAP_PROP_POS_MSEC)
            except Exception:
                info["cap_pos_msec"] = -1
        else:
            info["cap_status"] = "closed"
        return info

    # ---------- 二维码标定 ----------
    def calibrate_with_qr(self, frame):
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            data_text, points, _ = self.qr_detector.detectAndDecode(gray)

            if points is None or len(points) == 0:
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                data_text, points, _ = self.qr_detector.detectAndDecode(clahe.apply(gray))
        except cv2.error:
            return False

        if points is None or len(points) == 0:
            return False

        if data_text:
            self.qr_id = data_text.strip()

        if points.ndim == 3:
            corners = points[0].astype(np.float32) if points.shape[0] == 1 \
                else points[:, 0, :].astype(np.float32)
        else:
            corners = points.astype(np.float32)
        if len(corners) != 4:
            return False

        ordered = self._reorder_corners(corners)
        oriented = self._determine_orientation(frame, ordered)
        if oriented is not None:
            ordered = oriented

        self.qr_corners_original = ordered.copy()
        tl, tr, br, bl = ordered

        dx, dy = tr[0] - tl[0], tr[1] - tl[1]
        self.rotation_angle_deg = np.degrees(np.arctan2(dy, dx))

        h, w = frame.shape[:2]
        self.frame_center = (w / 2.0, h / 2.0)
        M = cv2.getRotationMatrix2D(self.frame_center, self.rotation_angle_deg, 1.0)
        cos_a, sin_a = np.abs(M[0, 0]), np.abs(M[0, 1])
        new_w = int(h * sin_a + w * cos_a)
        new_h = int(h * cos_a + w * sin_a)
        M[0, 2] += (new_w / 2) - self.frame_center[0]
        M[1, 2] += (new_h / 2) - self.frame_center[1]

        self.rotation_matrix = M.copy()
        self.rotated_size = (new_w, new_h)

        rc = self._transform_points(ordered, M)
        self.tl_bl_pixel_length = np.linalg.norm(rc[3] - rc[0])

        if self.tl_bl_real_cm > 0 and self.tl_bl_pixel_length > 0:
            self.scale_factor = self.tl_bl_real_cm / self.tl_bl_pixel_length

        self.calibrated = True
        self._just_calibrated = True  # 触发自动保存
        print(f"[CH{self.channel_id}] 标定完成 ID={self.qr_id} "
              f"angle={self.rotation_angle_deg:.2f}° scale={self.scale_factor:.6f} cm/px")
        return True

    # ---------- 校准持久化 ----------
    def _rebuild_rotation_matrix(self):
        """从 rotation_angle_deg + 帧尺寸重建旋转矩阵（无需 QR 码）"""
        h, w = self.cap_height, self.cap_width
        self.frame_center = (w / 2.0, h / 2.0)
        M = cv2.getRotationMatrix2D(self.frame_center, self.rotation_angle_deg, 1.0)
        cos_a, sin_a = np.abs(M[0, 0]), np.abs(M[0, 1])
        new_w = int(h * sin_a + w * cos_a)
        new_h = int(h * cos_a + w * sin_a)
        M[0, 2] += (new_w / 2) - self.frame_center[0]
        M[1, 2] += (new_h / 2) - self.frame_center[1]
        self.rotation_matrix = M.copy()
        self.rotated_size = (new_w, new_h)

    def _apply_manual_calibration(self, rotation_angle_deg, roi_bbox=None,
                                   reference_y=None, reference_x=None,
                                   scale_factor=None):
        """应用人工标定参数（来自上位机 Canvas 画线标定）。

        Args:
            rotation_angle_deg: 旋转角度（度），使硅胶板边沿竖直
            roi_bbox: (x, y, w, h) 在旋转后坐标系中的 ROI 矩形
            reference_y: 垂直流参考 Y 坐标
            reference_x: 水平流参考 X 坐标
            scale_factor: cm/pixel 比例尺（可选）
        """
        self.rotation_angle_deg = float(rotation_angle_deg)
        self._rebuild_rotation_matrix()

        if roi_bbox is not None:
            x, y, w, h = roi_bbox
            self.roi_bbox = (int(x), int(y), int(w), int(h))
            self.roi_mode = "manual"
            if reference_y is not None:
                self.reference_y = float(reference_y)
            else:
                self.reference_y = float(y)
            if reference_x is not None:
                self.reference_x = float(reference_x)

        if scale_factor is not None:
            self.scale_factor = float(scale_factor)

        self.calibrated = True
        self.qr_id = "manual"
        print(f"[CH{self.channel_id}] 人工标定已应用 "
              f"angle={self.rotation_angle_deg:.2f}° "
              f"roi={self.roi_bbox} "
              f"scale={self.scale_factor:.6f} cm/px")

    def get_calibration_dict(self):
        """返回校准参数的序列化字典，未标定时返回 None。
        所有数值显式转为 Python 原生类型，避免 numpy scalar 导致 JSON 序列化失败。"""
        if not self.calibrated:
            return None
        d = {
            "rotation_angle_deg": float(self.rotation_angle_deg),
            "scale_factor": float(self.scale_factor),
            "capture_width": int(self.cap_width),
            "capture_height": int(self.cap_height),
        }
        # QR 标定特有字段（人工标定时 qr_id="manual" 不写入这些）
        if self.qr_id and self.qr_id != "manual":
            d["qr_id"] = str(self.qr_id)
        if self.tl_bl_real_cm > 0:
            d["tl_bl_real_cm"] = float(self.tl_bl_real_cm)
        return d

    def load_calibration_dict(self, d: dict):
        """从配置字典加载校准参数，分辨率不匹配时拒绝加载。返回 (success: bool, message: str)

        支持两种来源:
          - QR 标定: 需要 qr_id, tl_bl_real_cm 字段
          - 人工标定: 只需 rotation_angle_deg (其余字段可选)
        """
        if "rotation_angle_deg" not in d:
            return False, "校准数据缺少 rotation_angle_deg"

        if "capture_width" in d and "capture_height" in d:
            if (int(d["capture_width"]) != self.cap_width or
                    int(d["capture_height"]) != self.cap_height):
                msg = (f"⚠ 校准分辨率({d['capture_width']}x{d['capture_height']}) "
                       f"与当前采集分辨率({self.cap_width}x{self.cap_height})不匹配，"
                       f"拒绝加载。请重新标定")
                print(f"[CH{self.channel_id}] {msg}")
                return False, msg

        self.rotation_angle_deg = float(d["rotation_angle_deg"])
        self.scale_factor = float(d.get("scale_factor", self.scale_factor))
        self.qr_id = str(d.get("qr_id", "manual"))
        self.tl_bl_real_cm = float(d.get("tl_bl_real_cm", self.tl_bl_real_cm))

        self._rebuild_rotation_matrix()
        self.calibrated = True

        print(f"[CH{self.channel_id}] 校准已从配置文件加载 "
              f"ID={self.qr_id} angle={self.rotation_angle_deg:.2f}° "
              f"scale={self.scale_factor:.6f} cm/px")
        return True, "ok"

    # ---------- ROI 持久化 ----------
    def get_roi_dict(self):
        """返回手动 ROI 的序列化字典，auto 模式或无效时返回 None"""
        if self.roi_mode != "manual" or self.roi_bbox is None:
            return None
        x, y, w, h = self.roi_bbox
        d = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        if int(self.reference_y) != int(y):
            d["reference_y"] = int(self.reference_y)
        return d

    def load_roi_dict(self, d: dict):
        """从配置字典加载手动 ROI。返回 (success: bool, message: str)"""
        required = ["x", "y", "w", "h"]
        if not all(k in d for k in required):
            return False, "ROI 数据不完整"
        x, y, w, h = int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"])
        if w < 20 or h < 20:
            return False, f"ROI 尺寸过小 ({w}x{h})"
        self.roi_bbox = (x, y, w, h)
        self.roi_mode = "manual"
        self.reference_y = float(d.get("reference_y", y))
        print(f"[CH{self.channel_id}] ROI 已加载 (手动) "
              f"bbox=({x},{y},{w},{h}) reference_y={self.reference_y:.0f}")
        return True, "ok"

    # ---------- ROI ----------
    @staticmethod
    def _find_first_significant_edge(profile, threshold_ratio=0.3, min_distance=10):
        peak = np.max(profile)
        if peak < 10:
            return len(profile) - 1
        thresh = peak * threshold_ratio
        candidates = np.where(profile > thresh)[0]
        candidates = candidates[candidates >= min_distance]
        return candidates[0] if len(candidates) > 0 else np.argmax(profile)

    def detect_roi(self, frame, margin=5):
        rotated = cv2.warpAffine(frame, self.rotation_matrix, self.rotated_size)
        h, w = rotated.shape[:2]
        cx, cy = w // 2, h // 2

        blurred = cv2.GaussianBlur(rotated, (7, 7), 0)
        gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)

        # ★ 使用参数化 roi_sobel_ksize
        ks = self.detect_params["roi_sobel_ksize"]
        sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=ks)
        sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=ks)
        band = min(60, h // 6, w // 6)

        le = cx - 1 - self._find_first_significant_edge(
            np.abs(sobelx[cy-band:cy+band, :cx]).mean(axis=0)[::-1], 0.3, 15)
        re = cx + self._find_first_significant_edge(
            np.abs(sobelx[cy-band:cy+band, cx:]).mean(axis=0), 0.3, 15)
        te = cy - 1 - self._find_first_significant_edge(
            np.abs(sobely[:cy, cx-band:cx+band]).mean(axis=1)[::-1], 0.3, 15)
        be = cy + self._find_first_significant_edge(
            np.abs(sobely[cy:, cx-band:cx+band]).mean(axis=1), 0.3, 15)

        edges = cv2.Canny(gray, 40, 120)

        def refine_h(y, xs, xe):
            yl, yh = max(0, y-15), min(h-1, y+15)
            s = edges[yl:yh+1, max(0,xs):min(w,xe)]
            r = s.sum(axis=1)
            return yl + np.argmax(r) if r.max() > 0 else y

        def refine_v(x, ys, ye):
            xl, xh = max(0, x-15), min(w-1, x+15)
            s = edges[max(0,ys):min(h,ye), xl:xh+1]
            c = s.sum(axis=0)
            return xl + np.argmax(c) if c.max() > 0 else x

        lr = refine_v(le, te, be)
        rr = refine_v(re, te, be)
        tr = refine_h(te, le, re)
        br = refine_h(be, le, re)

        x1, y1 = max(0, lr-margin), max(0, tr-margin)
        x2, y2 = min(w, rr+margin), min(h, br+margin)
        rw, rh = x2-x1, y2-y1
        if rw < 20 or rh < 20:
            return False

        self.roi_bbox = (x1, y1, rw, rh)
        self.reference_y = float(y1)
        print(f"[CH{self.channel_id}] ROI=({x1},{y1},{rw},{rh}) reference_y={self.reference_y:.0f}")
        return True

    # ---------- ROI 灰度预处理 (P0: 参考图差分用) ----------
    def _prepare_gray_roi(self, frame):
        """从原始帧提取 ROI 灰度图，含 crop + blur，供检测和参考图捕获共用。
        使用 warpAffine 旋转后提取 ROI，并将裁剪后的 ROI 左上角坐标存入
        self._roi_x0 / self._roi_y0 供高度换算使用。

        Returns:
            np.ndarray | None: 灰度 ROI 图，或 None (标定/ROI 未就绪)
        """
        roi_box = self.roi_bbox
        if not self.calibrated or roi_box is None:
            return None

        crop_x = self.detect_params["roi_crop_x"]
        crop_y = self.detect_params["roi_crop_y"]

        rotated = cv2.warpAffine(frame, self.rotation_matrix, self.rotated_size)
        rx, ry, rw, rh = roi_box
        mx, my = int(rw * crop_x), int(rh * crop_y)
        rx_s, ry_s = rx + mx, ry + my
        rw_s, rh_s = rw - 2 * mx, rh - 2 * my

        h_img, w_img = rotated.shape[:2]
        rx_s = max(0, min(rx_s, w_img - 1))
        ry_s = max(0, min(ry_s, h_img - 1))
        rw_s = min(rw_s, w_img - rx_s)
        rh_s = min(rh_s, h_img - ry_s)
        if rw_s <= 0 or rh_s <= 0:
            return None

        roi = rotated[ry_s:ry_s + rh_s, rx_s:rx_s + rw_s]
        if roi.size == 0:
            return None
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        self._roi_x0 = rx_s
        self._roi_y0 = ry_s

        blur_ks = self.detect_params["water_blur_ksize"]
        if blur_ks > 1:
            gray_roi = cv2.GaussianBlur(gray_roi, (blur_ks, blur_ks), 0)

        return gray_roi

    # ---------- 液位检测 ----------
    def detect_water_level(self, frame):
        if not self.calibrated or self.roi_bbox is None:
            return None

        gray_roi = self._prepare_gray_roi(frame)
        if gray_roi is None:
            return None

        # ★ P0: 参考图差分 — 保留原始灰度用于对比度验证
        gray_roi_original = gray_roi  # P1 对比度验证需要原始图
        _dbg_diff_mean = 0.0
        snr = 0.0

        # ★ debug 缓存字典: 统一收集中间结果, finally 管保写入
        dbg = {
            'gray_orig': gray_roi_original,
            'gray_diff': None,
            'profile': None,
            'smoothed': None,
            'edge_idx': None,
            'edge_val': 0.0,
            'contrast': 0.0,
            'wet_val': 0.0,
            'dry_val': 0.0,
            'contrast_ok': False,
            'lo': None,
            'hi': None,
            'row_positions': None,  # ★ 逐行边缘位置
            'valid_count': 0,       # ★ G2 有效行数
            'snr': 0.0,             # ★ G3 信噪比
        }

        try:
            if self.ref_gray is not None:
                gray_f = np.abs(gray_roi.astype(np.float32) - self.ref_gray.astype(np.float32))
                gray_roi = gray_f.astype(np.uint8)
                dbg['gray_diff'] = gray_roi  # Panel 2: 差分图
                # ★ P0a: 差分图有效性检验 — 差分均值为零说明画面无变化，直接退出
                diff_threshold = self.detect_params.get("water_diff_threshold", 5.0)
                if diff_threshold > 0:
                    _dbg_diff_mean = float(np.mean(gray_roi))
                    if _dbg_diff_mean < diff_threshold:
                        return None

            # ★ 使用参数化 water_sobely_ksize
            water_ks = self.detect_params["water_sobely_ksize"]
            direction = self.detect_params.get("flow_direction", "left_to_right")

            if direction == "bottom_to_top":
                grad = np.abs(cv2.Sobel(gray_roi, cv2.CV_64F, 0, 1, ksize=water_ks))
                profile = np.mean(grad, axis=1)
            else:
                grad = np.abs(cv2.Sobel(gray_roi, cv2.CV_64F, 1, 0, ksize=water_ks))
                profile = np.mean(grad, axis=0)
            dbg['profile'] = profile

            # ★ P1 debug: 保留 mean 投影用于 P3 面板可视化 (检测本身不依赖此值)
            k = max(3, len(profile)//30)
            if k % 2 == 0: k += 1
            smoothed = np.convolve(profile, np.ones(k)/k, mode='same')
            dbg['smoothed'] = smoothed

            # ★ 逐行/列边缘检测 — 替代 mean→argmax, 解决U形/倾斜前沿问题
            threshold = self.detect_params["water_edge_threshold"]
            row_result = self._detect_edge_rowwise(grad, direction)
            if row_result is None:
                return None
            idx, edge_val, valid_positions, valid_count = row_result
            dbg['row_positions'] = valid_positions
            dbg['edge_idx'] = idx
            dbg['edge_val'] = edge_val
            dbg['valid_count'] = valid_count

            # ★ P2: 历史位置软约束 — 限制中位数位置避免跳变
            _dbg_lo, _dbg_hi = None, None
            if self._last_edge_idx is not None:
                max_advance = 20   # px, 单帧最大推进距离
                backtrack = 5       # px, 允许微小回退
                max_dim = grad.shape[1] if direction != "bottom_to_top" else grad.shape[0]
                lo = max(0, self._last_edge_idx - backtrack)
                hi = min(max_dim - 1, self._last_edge_idx + max_advance)
                _dbg_lo, _dbg_hi = lo, hi
                if lo <= hi:
                    if idx < lo:
                        idx = lo
                    elif idx > hi:
                        idx = hi
                    dbg['edge_idx'] = idx
            self._last_edge_idx = idx
            dbg['lo'] = _dbg_lo
            dbg['hi'] = _dbg_hi

            # ★ 始终计算两区对比 (无论检测成功与否, debug 视图需要展示 wet/dry 区域)
            contrast, wet_val, dry_val = self._compute_front_contrast(
                gray_roi_original, idx, direction)
            dbg['contrast'] = contrast
            dbg['wet_val'] = wet_val
            dbg['dry_val'] = dry_val
            contrast_ok = contrast >= self.detect_params["front_contrast_threshold"]
            dbg['contrast_ok'] = contrast_ok

            # ★ P0b: 信噪比检验 — 峰值 vs 背景区(干侧远端20%)梯度中位数
            if direction == "left_to_right":
                bg_w = max(1, grad.shape[1] // 5)
                bg = grad[:, -bg_w:]          # 最右列 = 干侧远端
            elif direction == "right_to_left":
                bg_w = max(1, grad.shape[1] // 5)
                bg = grad[:, :bg_w]            # 最左列 = 干侧远端
            else:  # bottom_to_top
                bg_h = max(1, grad.shape[0] // 5)
                bg = grad[:bg_h, :]            # 最上行 = 干侧远端

            noise_floor = float(np.median(bg))
            snr = edge_val / max(noise_floor, 1e-6)
            dbg['snr'] = snr

            snr_threshold = self.detect_params.get("water_snr_threshold", 3.5)
            if snr < snr_threshold:
                return None

            if direction == "bottom_to_top":
                wl_pos = self._roi_y0 + idx
                h_cm = (wl_pos - self.reference_y) * self.scale_factor
            elif direction == "left_to_right":
                wl_pos = self._roi_x0 + idx
                h_cm = (wl_pos - self.reference_x) * self.scale_factor
            else:  # right_to_left
                wl_pos = self._roi_x0 + idx
                h_cm = (self.reference_x - wl_pos) * self.scale_factor

            # ★ 使用参数化 height_gain / height_offset_cm
            gain = self.detect_params["height_gain"]
            offset = self.detect_params["height_offset_cm"]
            h_cm = h_cm * gain + offset

            if not contrast_ok:
                return None

            return wl_pos, h_cm

        finally:
            self._save_debug_cache(
                dbg['gray_orig'], dbg['gray_diff'], dbg['profile'], dbg['smoothed'],
                dbg['edge_idx'], dbg['edge_val'], dbg['contrast'], dbg['wet_val'], dbg['dry_val'],
                dbg['contrast_ok'], dbg['lo'], dbg['hi'],
                dbg.get('row_positions'),
                dbg.get('valid_count'),
                dbg.get('snr', 0.0),
            )

    # ---------- 调试缓存 ----------
    def _save_debug_cache(self, gray_orig, gray_diff, profile, smoothed,
                           edge_idx, edge_val, contrast, wet_val, dry_val,
                           contrast_ok, lo, hi, row_positions=None,
                           valid_count=None, snr=0.0):
        """线程安全写入中间结果缓存 (仅当 _debug_enabled 时调用)。"""
        if not self._debug_enabled:
            return
        if not hasattr(self, '_debug_write_count'):
            self._debug_write_count = 0
        self._debug_write_count += 1
        if self._debug_write_count == 1 or self._debug_write_count % 30 == 0:
            _ev = edge_val if edge_val is not None else 0.0
            _ct = contrast if contrast is not None else 0.0
            _vc = np.sum(~np.isnan(row_positions)) if row_positions is not None else 0
            print(f"[DETECT-DBG] CH{self.channel_id} _save_debug_cache "
                  f"#{self._debug_write_count}: edge_idx={edge_idx} "
                  f"edge_val={_ev:.1f} contrast={_ct:.1f} "
                  f"contrast_ok={contrast_ok} lo={lo} hi={hi} "
                  f"valid_rows={_vc}")
        with self._debug_lock:
            self._debug_gray_original = gray_orig.copy() if gray_orig is not None else None
            self._debug_gray_diff = gray_diff.copy() if gray_diff is not None else None
            self._debug_profile = profile.copy() if profile is not None else None
            self._debug_smoothed = smoothed.copy() if smoothed is not None else None
            self._debug_edge_idx = edge_idx
            self._debug_edge_val = edge_val
            self._debug_contrast = contrast
            self._debug_wet_val = wet_val
            self._debug_dry_val = dry_val
            self._debug_contrast_ok = contrast_ok
            self._debug_lo = lo
            self._debug_hi = hi
            self._debug_row_positions = row_positions.copy() if row_positions is not None else None
            self._debug_valid_count = valid_count
            self._debug_snr = snr

    # ---------- 两区对比验证 ----------
    def _compute_front_contrast(self, roi_gray, edge_idx, direction):
        """计算湿-干两区对比度: median(dry_zone) - median(wet_zone)。

        在候选边位置两侧等宽提取 zone_wet (靠近流动原点) 和 zone_dry (远离流动原点),
        跳过 gap 像素避免包含过渡区。返回有符号对比度 (干-湿, 正常应为正)。

        Args:
            roi_gray: 裁剪后 ROI 灰度图 (已做 blur 处理)
            edge_idx: 候选边在流动方向上的像素索引
            direction: 流动方向
        Returns:
            float: 对比度值, zone 超出边界时返回 0.0
        """
        zone_width = int(self.detect_params["front_zone_width"])
        zone_gap = int(self.detect_params["front_zone_gap"])
        h, w = roi_gray.shape[:2]

        try:
            if direction == "bottom_to_top":
                # profile 沿行 (axis=1), 湿区在下 (大 y), 干区在上 (小 y)
                wet_start = edge_idx + zone_gap
                dry_end = edge_idx - zone_gap
                if wet_start + zone_width > h or dry_end - zone_width < 0:
                    return (0.0, 0.0, 0.0)
                wet_zone = roi_gray[wet_start:wet_start + zone_width, :]
                dry_zone = roi_gray[dry_end - zone_width:dry_end, :]
            elif direction == "left_to_right":
                # profile 沿列 (axis=0), 湿区在左 (小 x), 干区在右 (大 x)
                dry_start = edge_idx + zone_gap
                wet_end = edge_idx - zone_gap
                if dry_start + zone_width > w or wet_end - zone_width < 0:
                    return (0.0, 0.0, 0.0)
                wet_zone = roi_gray[:, wet_end - zone_width:wet_end]
                dry_zone = roi_gray[:, dry_start:dry_start + zone_width]
            else:  # right_to_left
                # profile 沿列 (axis=0), 湿区在右 (大 x), 干区在左 (小 x)
                wet_start = edge_idx + zone_gap
                dry_end = edge_idx - zone_gap
                if wet_start + zone_width > w or dry_end - zone_width < 0:
                    return (0.0, 0.0, 0.0)
                wet_zone = roi_gray[:, wet_start:wet_start + zone_width]
                dry_zone = roi_gray[:, dry_end - zone_width:dry_end]

            wet_val = float(np.median(wet_zone))
            dry_val = float(np.median(dry_zone))
            # 归一化对比度: (干-湿)/干区亮度, 落在 0-1 区间
            contrast = (dry_val - wet_val) / max(dry_val, 1.0)
            return (contrast, wet_val, dry_val)
        except (IndexError, ValueError):
            return (0.0, 0.0, 0.0)

    # ---------- 逐行边缘检测 (解决U形/倾斜前沿的均值投影抹平问题) ----------
    def _detect_edge_rowwise(self, grad_2d, direction):
        """逐行/列独立检测梯度峰值，取中位数作为液面位置。

        对水平流 (left_to_right / right_to_left):
          每行独立 argmax → 各行峰值位置中位数
        对垂直流 (bottom_to_top):
          每列独立 argmax → 各列峰值位置中位数

        Args:
            grad_2d: 2D Sobel 梯度幅值 (roi_h, roi_w)
            direction: 流动方向
        Returns:
            (edge_idx, edge_val, valid_positions, valid_count) | None
            valid_positions: 1D array, NaN=无效, float=峰值位置(像素索引)
        """
        threshold = self.detect_params["water_edge_threshold"]
        roi_h, roi_w = grad_2d.shape[:2]
        valid_ratio = self.detect_params.get("front_valid_row_ratio", 0.20)

        if direction == "bottom_to_top":
            # 垂直流: 每列独立找峰值 (沿行方向, axis=0)
            k = max(3, roi_h // 30)
            if k % 2 == 0:
                k += 1
            # box filter 沿垂直方向 → 等价于逐列 np.convolve
            smoothed_2d = cv2.blur(grad_2d, (1, k))

            peak_indices = np.argmax(smoothed_2d, axis=0)  # (roi_w,)
            peak_vals = smoothed_2d[peak_indices, np.arange(roi_w)]  # (roi_w,)

            valid_mask = peak_vals >= threshold
            valid_count = int(np.sum(valid_mask))

            if valid_count < roi_w * valid_ratio:
                return None

            valid_positions = np.where(valid_mask, peak_indices.astype(np.float64), np.nan)
            edge_idx = int(np.median(peak_indices[valid_mask]))
            edge_val = float(np.median(peak_vals[valid_mask]))
        else:
            # 水平流: 每行独立找峰值 (沿列方向, axis=1)
            k = max(3, roi_w // 30)
            if k % 2 == 0:
                k += 1
            # box filter 沿水平方向 → 等价于逐行 np.convolve
            smoothed_2d = cv2.blur(grad_2d, (k, 1))

            peak_indices = np.argmax(smoothed_2d, axis=1)  # (roi_h,)
            peak_vals = smoothed_2d[np.arange(roi_h), peak_indices]  # (roi_h,)

            valid_mask = peak_vals >= threshold
            valid_count = int(np.sum(valid_mask))

            if valid_count < roi_h * valid_ratio:
                return None

            valid_positions = np.where(valid_mask, peak_indices.astype(np.float64), np.nan)
            edge_idx = int(np.median(peak_indices[valid_mask]))
            edge_val = float(np.median(peak_vals[valid_mask]))

        return (edge_idx, edge_val, valid_positions, valid_count)

    # ---------- 单帧处理 ----------
    def process_frame(self, frame):
        self._fps_frame_count += 1
        now = time.time()
        elapsed = now - self._fps_last_time
        if elapsed >= 1.0:
            self.current_fps = self._fps_frame_count / elapsed
            self._fps_frame_count = 0
            self._fps_last_time = now

        if not self.calibrated or self._calibrate_mode:
            # 标定模式：周期性尝试 QR 检测
            if self._calibrate_mode:
                if now - self._last_qr_time >= self._qr_interval:
                    self._last_qr_time = now
                    self.calibrate_with_qr(frame)
            # 正常模式：不尝试 QR 检测（QR 不在画面中）
            if not self.calibrated:
                return self._draw_uncalibrated(frame)

        if self.roi_bbox is None:
            # 仅 auto 模式下自动检测 ROI；manual 模式由 MQTT/配置文件注入
            if self.roi_mode == "auto":
                self.detect_roi(frame)
        if self.roi_bbox is None:
            return self._draw_uncalibrated(frame, "No ROI")

        # 根据 flow_direction 自动派生 reference_x (水平流用)
        direction = self.detect_params.get("flow_direction", "left_to_right")
        if direction != "bottom_to_top":
            rx, ry, rw, rh = self.roi_bbox
            if direction == "left_to_right":
                self.reference_x = float(rx)
            else:  # right_to_left
                self.reference_x = float(rx + rw)

        # ★ P0: 参考图捕获 — MQTT capture_reference 触发, 下一帧自动抓取
        if self._capture_ref_pending:
            gray_ref = self._prepare_gray_roi(frame)
            if gray_ref is not None:
                self.ref_gray = gray_ref
                self._capture_ref_pending = False
                self._last_edge_idx = None  # 重置软约束起点
                self._front_state = "WAITING"  # 重置前沿状态机
                self._front_ok_counter = 0
                self._front_fail_counter = 0
                self.height_buffer.clear()
                print(f"[CH{self.channel_id}] 参考图已捕获 "
                      f"({gray_ref.shape[1]}x{gray_ref.shape[0]})")

        result = self.detect_water_level(frame)
        wl_pos, h_cm = result if result else (None, None)

        # ★ 调试缓存: 检测成功标记 + 前沿状态
        if self._debug_enabled:
            with self._debug_lock:
                self._debug_detect_ok = (h_cm is not None)
            # 首次进入 debug 模式时打印检测管线状态
            if not hasattr(self, '_debug_notified_process'):
                self._debug_notified_process = True
                print(f"[DETECT-DBG] CH{self.channel_id} process_frame "
                      f"首次以 _debug_enabled=True 运行: "
                      f"calibrated={self.calibrated} "
                      f"has_roi={self.roi_bbox is not None} "
                      f"has_ref={self.ref_gray is not None} "
                      f"result={'OK' if h_cm is not None else 'FAIL'} "
                      f"h_cm={h_cm}")

        # ★ 前沿状态机: 两区对比验证已在 detect 方法内部完成,
        #   此处根据检测结果 (有/无 valid h_cm) 驱动状态转移
        contrast_ok = (h_cm is not None)
        arrival_frames = int(self.detect_params["front_arrival_frames"])
        departure_frames = int(self.detect_params["front_departure_frames"])

        if contrast_ok:
            self._front_ok_counter += 1
            self._front_fail_counter = 0
        else:
            self._front_fail_counter += 1
            self._front_ok_counter = 0

        if self._front_state == "WAITING":
            if self._front_ok_counter >= arrival_frames:
                self._front_state = "TRACKING"
                self.height_buffer.clear()
                print(f"[CH{self.channel_id}] 溶剂前沿已到达 → TRACKING")
        elif self._front_state == "TRACKING":
            if self._front_fail_counter >= departure_frames:
                self._front_state = "GONE"
                print(f"[CH{self.channel_id}] 溶剂前沿已穿过ROI → GONE")

        if self._debug_enabled:
            with self._debug_lock:
                self._debug_front_state = self._front_state

        # Gate: 仅在 TRACKING 状态下接受高度测量
        if self._front_state == "TRACKING":
            if h_cm is not None and h_cm >= 0:
                self.height_buffer.append(h_cm)
            self.latest_waterline_y = wl_pos
            display_h = (np.median(list(self.height_buffer)[-30:])
                         if self.height_buffer else h_cm)
            self.latest_height_cm = display_h
        elif self._front_state == "GONE":
            # 保持最后有效高度冻结, 不更新 height_buffer
            display_h = self.latest_height_cm
            wl_pos = self.latest_waterline_y
        else:  # WAITING
            self.latest_height_cm = None
            display_h = None
            wl_pos = None

        return self._draw_overlay(frame, wl_pos, display_h)

    # ---------- 绘制 ----------
    def _draw_uncalibrated(self, frame, msg=None):
        display = cv2.warpAffine(frame, self.rotation_matrix, self.rotated_size,
                                borderMode=cv2.BORDER_CONSTANT,
                                borderValue=(64, 64, 64)) \
            if self.rotation_matrix is not None else frame.copy()
        if msg is None:
            if not self.calibrated:
                if self._calibrate_mode:
                    msg = "Waiting for QR..."
                else:
                    msg = "Not calibrated - run --calibrate first"
            else:
                msg = "No ROI"
        cv2.putText(display, f"CH{self.channel_id}: {msg}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        cv2.putText(display, f"Mode: {self.roi_mode}",
                    (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.putText(display, f"{self.current_fps:.1f} FPS",
                    (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        return display

    def _draw_overlay(self, frame, waterline_pos, display_height_cm):
        if self.rotation_matrix is None:
            return frame.copy()

        display = cv2.warpAffine(frame, self.rotation_matrix, self.rotated_size,
                                borderMode=cv2.BORDER_CONSTANT,
                                borderValue=(64, 64, 64))
        direction = self.detect_params.get("flow_direction", "left_to_right")

        if self.roi_bbox is not None:
            rx, ry, rw, rh = self.roi_bbox
            cv2.rectangle(display, (rx, ry), (rx+rw, ry+rh), (255, 255, 0), 2)

            crop_x = self.detect_params["roi_crop_x"]
            crop_y = self.detect_params["roi_crop_y"]
            mx, my = int(rw * crop_x), int(rh * crop_y)
            cv2.rectangle(display, (rx+mx, ry+my), (rx+rw-mx, ry+rh-my), (255, 255, 0), 1)

            if direction == "bottom_to_top":
                # 参考线 (蓝色): 水平线 reference_y = 板顶部/点样线
                ry_line = int(self.reference_y)
                cv2.line(display, (rx, ry_line), (rx+rw, ry_line), (255, 0, 0), 2)

                if waterline_pos is not None:
                    wp = int(waterline_pos)
                    cv2.line(display, (rx, wp), (rx+rw, wp), (0, 0, 255), 3)
            else:
                # 参考线 (蓝色): 垂直线 reference_x = 液面起始边
                rx_line = int(self.reference_x)
                cv2.line(display, (rx_line, ry), (rx_line, ry+rh), (255, 0, 0), 2)

                if waterline_pos is not None:
                    wp = int(waterline_pos)
                    cv2.line(display, (wp, ry), (wp, ry+rh), (0, 0, 255), 3)

        if self.qr_corners_original is not None:
            qr_rot = self._transform_points(self.qr_corners_original,
                                            self.rotation_matrix).astype(np.int32)
            cv2.polylines(display, [qr_rot], True, (0, 255, 0), 2)

        py = 22
        font, fs, th = cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2
        def text(msg, color=(255,255,255)):
            nonlocal py
            tw, th_s = cv2.getTextSize(msg, font, fs, th)[0]
            cv2.rectangle(display, (3, py-th_s-3), (8+tw, py+3), (0,0,0), -1)
            cv2.putText(display, msg, (5, py), font, fs, color, th)
            py += 22

        text(f"CH{self.channel_id} | {self.qr_id}", (0, 255, 255))
        dir_label = {"bottom_to_top": "↑", "left_to_right": "→", "right_to_left": "←"}
        text(f"Flow: {dir_label.get(direction, '?')} | ROI: {self.roi_mode}", (200, 200, 200))
        text(f"Rot: {self.rotation_angle_deg:.1f} deg", (0, 255, 0))
        text(f"Scale: {self.scale_factor:.5f} cm/px", (200, 200, 200))

        if self._front_state == "WAITING":
            text("Front: WAITING", (0, 165, 255))
        elif self._front_state == "GONE":
            text("Front: GONE", (255, 165, 0))

        if display_height_cm is not None:
            text(f"Level: {display_height_cm:.2f} cm", (0, 255, 255))
        else:
            text("Level: N/A", (128, 128, 128))

        text(f"FPS: {self.current_fps:.1f}", (0, 255, 0))

        return display

    # ---------- 调试可视化 ----------
    _get_debug_call_count = 0

    def get_debug(self):
        """MJPEG HTTP 线程安全读取：返回 3-panel 调试组合图。

        锁内仅做引用快照 (O(1))，OpenCV 绘图在锁外执行。
        未标定/无ROI 或数据缺失时返回带提示的占位帧。
        """
        self._get_debug_call_count += 1
        is_first = (self._get_debug_call_count == 1)
        is_periodic = (self._get_debug_call_count % 30 == 0)

        if is_first or is_periodic:
            print(f"[DETECT-DBG] CH{self.channel_id} get_debug() "
                  f"#{self._get_debug_call_count}: "
                  f"calibrated={self.calibrated} "
                  f"has_roi={self.roi_bbox is not None} "
                  f"debug_enabled={self._debug_enabled} "
                  f"has_gray_orig={self._debug_gray_original is not None} "
                  f"state={self.state}")

        if not self.calibrated or self.roi_bbox is None:
            if is_first:
                print(f"[DETECT-DBG] CH{self.channel_id} get_debug→placeholder: "
                      f"calibrated={self.calibrated} roi={self.roi_bbox}")
            return self._build_debug_placeholder("Not calibrated / No ROI")

        with self._debug_lock:
            if self._debug_gray_original is None:
                if is_first:
                    print(f"[DETECT-DBG] CH{self.channel_id} get_debug→placeholder: "
                          f"no debug data yet (_debug_gray_original=None)")
                return self._build_debug_placeholder("No debug data yet")
            snap = {
                'gray_original': self._debug_gray_original,
                'gray_diff': self._debug_gray_diff,
                'profile': self._debug_profile,
                'smoothed': self._debug_smoothed,
                'edge_idx': self._debug_edge_idx,
                'edge_val': self._debug_edge_val,
                'wet_val': self._debug_wet_val,
                'dry_val': self._debug_dry_val,
                'contrast': self._debug_contrast,
                'contrast_ok': self._debug_contrast_ok,
                'lo': self._debug_lo,
                'hi': self._debug_hi,
                'detect_ok': self._debug_detect_ok,
                'front_state': self._debug_front_state,
                'row_positions': self._debug_row_positions,  # ★ 逐行边缘位置 (U形曲线)
                'valid_count': self._debug_valid_count,      # ★ G2
                'snr': self._debug_snr,                      # ★ G3
            }

        try:
            result = self._build_debug_frame(snap)
            if is_first:
                print(f"[DETECT-DBG] CH{self.channel_id} get_debug→SUCCESS "
                      f"frame_shape={result.shape} "
                      f"edge_idx={snap['edge_idx']} "
                      f"contrast={snap['contrast']:.1f} "
                      f"contrast_ok={snap['contrast_ok']} "
                      f"detect_ok={snap['detect_ok']} "
                      f"front_state={snap['front_state']}")
            return result
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[DETECT-DBG] CH{self.channel_id} get_debug→ERROR: {e}")
            return self._build_debug_placeholder(f"Error: {e}")

    def _build_debug_placeholder(self, msg):
        """生成带错误/状态信息的占位帧。"""
        w, h = 480, 360
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.putText(canvas, msg, (20, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
        cv2.putText(canvas, f"CH{self.channel_id}", (20, h // 2 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1)
        return canvas

    def _build_debug_frame(self, snap):
        """构建调试组合图。

        垂直流向 (bottom_to_top): 2×2 网格, P1|P2 并排, P3 全宽 (现有布局)
        水平流向 (left_to_right / right_to_left): 源图旋转 90° 归一化为 bottom→top,
           P1/P2/P3 纵向堆叠, 输出始终 portrait

        Returns:
            np.ndarray: BGR 组合图
        """
        gray_orig = snap['gray_original']
        gray_diff = snap['gray_diff']
        profile = snap['profile']
        smoothed = snap['smoothed']

        roi_h, roi_w = gray_orig.shape[:2]
        direction = self.detect_params.get("flow_direction", "left_to_right")
        is_horizontal = direction in ("left_to_right", "right_to_left")

        edge_idx = snap['edge_idx']
        lo = snap['lo']
        hi = snap['hi']
        rot_label = ""

        # === 水平流向: 旋转源图像归一化到 bottom→top ===
        if is_horizontal:
            if direction == "left_to_right":
                rot = cv2.ROTATE_90_COUNTERCLOCKWISE
                rot_symbol = "↺"   # ↺
            else:
                rot = cv2.ROTATE_90_CLOCKWISE
                rot_symbol = "↻"   # ↻

            gray_orig = cv2.rotate(gray_orig, rot)
            if gray_diff is not None:
                gray_diff = cv2.rotate(gray_diff, rot)

            # 旋转后尺寸交换: 原 roi_w×roi_h → roi_h×roi_w
            roi_h, roi_w = roi_w, roi_h

            # 重映射 edge_idx 到旋转后坐标系
            if edge_idx is not None:
                if direction == "left_to_right":
                    # CCW: 原 x 列 → 新行 row = roi_h - 1 - x
                    edge_idx = roi_h - 1 - edge_idx
                # CW: 原 x 列 → 新行 row = x (不变)

            # 重映射 P2 约束范围 [lo..hi] 到旋转后坐标系
            if lo is not None and hi is not None:
                if direction == "left_to_right":
                    # CCW: 坐标范围方向反转
                    lo, hi = roi_h - 1 - hi, roi_h - 1 - lo
                # CW: 范围不变

            rot_label = f" (rot'd {rot_symbol}90°)"
            viz_direction = "bottom_to_top"
        else:
            viz_direction = direction

        # === 布局计算 ===
        bar_h = 28
        gate_h = 14
        sep_h = 1

        if is_horizontal:
            # 纵向堆叠: P1 → P2 → P3, 输出 portrait
            panel3_h = max(80, int(roi_h * 0.65))
            total_w = roi_w
            total_h = bar_h + gate_h + roi_h + roi_h + sep_h + panel3_h
        else:
            # 2×2 网格: P1|P2 并排, P3 全宽 (现有布局)
            panel3_h = max(80, int(roi_w * 0.65))
            total_w = roi_w * 2
            total_h = bar_h + gate_h + roi_h + sep_h + panel3_h

        # 方向箭头 (用于参数栏标注, 始终显示原始方向)
        dir_label = {"bottom_to_top": "↑", "left_to_right": "→", "right_to_left": "←"}

        # 阈值
        threshold = self.detect_params["water_edge_threshold"]
        contrast_th = self.detect_params["front_contrast_threshold"]
        blur_ks = self.detect_params["water_blur_ksize"]
        sobel_ks = self.detect_params["water_sobely_ksize"]

        # 对比度信息
        wet_val = snap['wet_val']
        dry_val = snap['dry_val']
        contrast = snap['contrast']
        contrast_ok = snap['contrast_ok']
        if wet_val is not None and dry_val is not None and contrast is not None:
            contrast_str = (f"wet={wet_val:.1f} dry={dry_val:.1f} "
                            f"c={contrast:.1f}/{contrast_th:.1f}"
                            f"{'✓' if contrast_ok else '✗'}")
        else:
            contrast_str = "contrast: N/A"

        # 构建组合画布 (白色背景)
        canvas = np.full((total_h, total_w, 3), 255, dtype=np.uint8)

        # ---- 参数栏 (黑底绿字, 全宽) ----
        canvas[:bar_h, :] = (0, 0, 0)
        bar_text = (f"CH{self.channel_id}|"
                    f"{dir_label.get(direction, '?')}{rot_label}|"
                    f"thr={threshold:.0f} blur={blur_ks} sob={sobel_ks}|"
                    f"{snap['front_state']}"
                    f"{' FAIL' if not snap['detect_ok'] else ''}")
        cv2.putText(canvas, bar_text, (4, bar_h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

        # ---- 门控状态摘要栏 (深灰底, gate_h px) ----
        canvas[bar_h:bar_h + gate_h, :] = (50, 50, 50)
        gate_parts = []
        valid_count = snap.get('valid_count')
        row_positions_gate = snap.get('row_positions')
        if valid_count is not None and row_positions_gate is not None:
            total = len(row_positions_gate)
            gate_parts.append(f"G2 valid:{valid_count}/{total}")
        snr_val = snap.get('snr', 0.0)
        if snr_val > 0:
            snr_th = self.detect_params.get("water_snr_threshold", 3.5)
            gate_parts.append(f"G3 SNR:{snr_val:.1f}/{snr_th:.1f}")
        contrast_val = snap.get('contrast', 0.0)
        contrast_ok_gate = snap.get('contrast_ok', False)
        contrast_th = self.detect_params["front_contrast_threshold"]
        gate_parts.append(f"G4 c:{contrast_val:.3f}/{contrast_th:.3f}{'v' if contrast_ok_gate else 'x'}")
        gate_summary = " | ".join(gate_parts)
        cv2.putText(canvas, gate_summary, (4, bar_h + gate_h - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.32, (180, 180, 180), 1)

        # ---- Panel 1: 原始 ROI + 两区对比 + U形曲线 ----
        # 水平流向旋转后 viz_direction 强制为 bottom_to_top,
        # zone 绘制逻辑 (湿区在下/干区在上) 完美映射到旋转后图像, 零分支增量
        zone_width = int(self.detect_params["front_zone_width"])
        zone_gap = int(self.detect_params["front_zone_gap"])
        detect_ok = snap.get('detect_ok', False)

        if is_horizontal:
            # 纵向堆叠: P1 占据顶部
            p1_y0 = bar_h + gate_h
            p1_y1 = p1_y0 + roi_h
            p1_x0 = 0
        else:
            # 并排: P1 占据左半
            p1_y0 = bar_h + gate_h
            p1_y1 = p1_y0 + roi_h
            p1_x0 = 0

        p1_bgr = cv2.cvtColor(gray_orig, cv2.COLOR_GRAY2BGR)
        canvas[p1_y0:p1_y1, p1_x0:p1_x0 + roi_w] = p1_bgr

        # ★ U形曲线: 逐行边缘位置 (绿色折线, 全程显示)
        row_positions = snap.get('row_positions')
        if row_positions is not None and len(row_positions) > 0:
            curve_pts = []
            for idx_line in range(len(row_positions)):
                p = row_positions[idx_line]
                if not np.isnan(p):
                    if is_horizontal:
                        # 水平流已旋转: idx_line=原行号, p=原x坐标
                        if direction == "left_to_right":
                            y_mapped = roi_h - 1 - int(p)  # CCW 映射
                        else:
                            y_mapped = int(p)               # CW 不变
                        curve_pts.append((p1_x0 + idx_line, p1_y0 + y_mapped))
                    else:
                        # 垂直流未旋转: idx_line=列号, p=该列的y峰值
                        curve_pts.append((p1_x0 + idx_line, p1_y0 + int(p)))
            if len(curve_pts) >= 2:
                curve_arr = np.array(curve_pts, dtype=np.int32)
                cv2.polylines(canvas, [curve_arr], False, (0, 255, 0), 1, cv2.LINE_AA)

        # ★ 液面线 + wet/dry 区域: 仅在检测成功 (TRACKING) 时绘制
        if detect_ok and edge_idx is not None and contrast is not None:
            # 湿区在下(大y), 干区在上(小y) — 旋转归一化后统一为 bottom→top
            wet_y0 = edge_idx + zone_gap
            wet_y1 = edge_idx + zone_gap + zone_width
            dry_y0 = edge_idx - zone_gap - zone_width
            dry_y1 = edge_idx - zone_gap
            wet_rect = (0, wet_y0, roi_w, wet_y1 - wet_y0)
            dry_rect = (0, dry_y0, roi_w, dry_y1 - dry_y0)
            cv2.line(canvas, (p1_x0, p1_y0 + edge_idx),
                     (p1_x0 + roi_w, p1_y0 + edge_idx), (0, 0, 255), 2)

            overlay = canvas[p1_y0:p1_y1, p1_x0:p1_x0 + roi_w].copy()
            cv2.rectangle(overlay, (wet_rect[0], wet_rect[1]),
                          (wet_rect[0] + wet_rect[2], wet_rect[1] + wet_rect[3]),
                          (255, 255, 0), -1)  # cyan for wet
            cv2.rectangle(overlay, (dry_rect[0], dry_rect[1]),
                          (dry_rect[0] + dry_rect[2], dry_rect[1] + dry_rect[3]),
                          (0, 255, 255), -1)  # yellow for dry
            canvas[p1_y0:p1_y1, p1_x0:p1_x0 + roi_w] = cv2.addWeighted(
                canvas[p1_y0:p1_y1, p1_x0:p1_x0 + roi_w], 0.55, overlay, 0.45, 0)

        # P1 标签
        p1_label_y = p1_y1 - 6
        p1_title = "P1: Original ROI + Contrast"
        if row_positions is not None:
            valid_n = int(np.sum(~np.isnan(row_positions)))
            p1_title += f" [{valid_n} valid]"
        cv2.putText(canvas, p1_title,
                    (p1_x0 + 2, p1_y0 + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                    (255, 255, 255), 1)
        cv2.putText(canvas, contrast_str,
                    (p1_x0 + 2, p1_label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                    (0, 255, 0) if contrast_ok else (0, 0, 255), 1)

        # ---- Panel 2: 差分图 ----
        if is_horizontal:
            p2_x0 = 0
            p2_y0 = bar_h + gate_h + roi_h
        else:
            p2_x0 = roi_w
            p2_y0 = bar_h + gate_h
        p2_y1 = p2_y0 + roi_h

        if gray_diff is not None:
            p2_bgr = cv2.cvtColor(gray_diff, cv2.COLOR_GRAY2BGR)
            canvas[p2_y0:p2_y1, p2_x0:p2_x0 + roi_w] = p2_bgr
        else:
            canvas[p2_y0:p2_y1, p2_x0:p2_x0 + roi_w] = (40, 40, 40)
            nr_x = max(2, p2_x0 + roi_w // 2 - 50)  # 防窄面板溢出
            cv2.putText(canvas, "No Reference",
                        (nr_x, p2_y0 + roi_h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

        # P2 标签
        cv2.putText(canvas, "P2: Diff (curr - ref)",
                    (p2_x0 + 2, p2_y0 + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)

        # ---- 分隔线 ----
        if is_horizontal:
            sep_y = p2_y1  # P1+P2 下方
        else:
            sep_y = p1_y1  # P1/P2 行下方
        canvas[sep_y:sep_y + sep_h, :] = (200, 200, 200)
        cv2.putText(canvas, "P3: 1D Projection (-- raw, - smoothed, - thr, | peak)",
                    (2, sep_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (200, 200, 200), 1)

        # ---- Panel 3: 1D 投影曲线 ----
        p3_y0 = sep_y + sep_h

        # L→R (CCW 旋转): profile[0] (湿/左) → 旋转后底部, 需翻转 Y 轴
        flip_y = is_horizontal and direction == "left_to_right"

        self._draw_projection_panel(canvas, p3_y0, panel3_h, total_w,
                                    profile, smoothed, threshold,
                                    edge_idx, lo, hi,
                                    viz_direction, snap['edge_val'],
                                    vertical=is_horizontal,
                                    flip_y=flip_y)

        return canvas

    def _draw_projection_panel(self, canvas, y0, panel_h, panel_w,
                                profile, smoothed, threshold,
                                edge_idx, lo, hi, direction, edge_val,
                                vertical=False, flip_y=False):
        """在画布指定区域绘制 1D 投影曲线 panel (白底)。

        horizontal 模式 (vertical=False):
          X 轴 = 像素索引, Y 轴 = 梯度幅值
        vertical 模式 (vertical=True):
          X 轴 = 梯度幅值, Y 轴 = 像素索引 (与旋转后 P1/P2 纵向对齐)

        包含：原始投影 (灰虚线) + 平滑投影 (蓝实线) +
              threshold (橙虚线) + peak 标记 (红虚线) +
              P2 约束范围 [lo..hi]
        """
        # 白色背景
        canvas[y0:y0 + panel_h, :panel_w] = (255, 255, 255)

        if profile is None or smoothed is None or len(profile) == 0:
            cv2.putText(canvas, "No profile data", (panel_w // 2 - 50, y0 + panel_h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1)
            return

        n = len(profile)
        if n < 2:
            return

        if vertical:
            self._draw_projection_vertical(canvas, y0, panel_h, panel_w,
                                           profile, smoothed, threshold,
                                           edge_idx, lo, hi, edge_val,
                                           flip_y)
        else:
            self._draw_projection_horizontal(canvas, y0, panel_h, panel_w,
                                             profile, smoothed, threshold,
                                             edge_idx, lo, hi, direction, edge_val)

    def _draw_projection_horizontal(self, canvas, y0, panel_h, panel_w,
                                     profile, smoothed, threshold,
                                     edge_idx, lo, hi, direction, edge_val):
        """水平投影: X=像素索引, Y=梯度幅值 (现有逻辑)"""
        n = len(profile)
        # Y 轴映射：值 → 像素 (上方为 0)
        margin_top, margin_bot = 12, 22
        plot_h = panel_h - margin_top - margin_bot
        if plot_h <= 0:
            return

        max_val = max(np.max(profile), np.max(smoothed), threshold) * 1.15
        if max_val <= 0:
            max_val = 1.0

        def to_x(i):
            return int(i * panel_w / (n - 1)) if n > 1 else panel_w // 2

        def to_y(v):
            return y0 + margin_top + int((1.0 - v / max_val) * plot_h)

        # 阈值水平虚线 (橙色)
        thr_y = to_y(threshold)
        for px in range(0, panel_w, 6):
            cv2.line(canvas, (px, thr_y), (min(px + 3, panel_w - 1), thr_y),
                     (0, 140, 255), 1)

        # P2 约束范围 [lo..hi] 半透明灰色区
        if lo is not None and hi is not None and lo <= hi:
            lo_x = to_x(lo)
            hi_x = to_x(hi)
            overlay = canvas[y0:y0 + panel_h, :panel_w].copy()
            cv2.rectangle(overlay, (lo_x, y0), (hi_x, y0 + panel_h), (200, 200, 200), -1)
            cv2.rectangle(overlay, (lo_x, y0), (hi_x, y0 + panel_h), (180, 180, 180), 1)
            canvas[y0:y0 + panel_h, :panel_w] = cv2.addWeighted(
                canvas[y0:y0 + panel_h, :panel_w], 0.85, overlay, 0.15, 0)
            # 标注 lo/hi
            cv2.putText(canvas, f"lo={lo}", (lo_x + 1, y0 + panel_h - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
            cv2.putText(canvas, f"hi={hi}", (hi_x - 28, y0 + panel_h - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)

        # 原始投影 (灰虚线)
        prev_pt = None
        for i in range(n):
            pt = (to_x(i), to_y(profile[i]))
            if prev_pt is not None and i % 2 == 0:  # 每隔一点画虚线
                cv2.line(canvas, prev_pt, pt, (160, 160, 160), 1)
            prev_pt = pt

        # 平滑后投影 (蓝实线)
        pts = np.array([[to_x(i), to_y(smoothed[i])] for i in range(n)], dtype=np.int32)
        cv2.polylines(canvas, [pts], False, (255, 80, 0), 2)

        # 检测峰值 (红色虚线)
        if edge_idx is not None and 0 <= edge_idx < n:
            peak_x = to_x(edge_idx)
            peak_y = to_y(smoothed[edge_idx])
            # 竖直线
            cv2.line(canvas, (peak_x, y0 + margin_top), (peak_x, y0 + margin_top + plot_h),
                     (0, 0, 255), 1, cv2.LINE_AA)
            # 峰值标记圆点
            cv2.circle(canvas, (peak_x, peak_y), 4, (0, 0, 255), -1)
            # 峰值标注
            val_str = f"idx={edge_idx}"
            if edge_val is not None:
                val_str += f" v={edge_val:.1f}"
            cv2.putText(canvas, val_str, (peak_x + 5, peak_y - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 255), 1)

        # ★ per-row 中位数峰值参考线 (绿色点划线, 与阈值同单位可比)
        if edge_val is not None and edge_val > 0:
            ev_y = to_y(edge_val)
            for px in range(0, panel_w, 8):
                cv2.line(canvas, (px, ev_y), (min(px + 4, panel_w - 1), ev_y),
                         (0, 180, 0), 1)
            cv2.putText(canvas, f"row_peak={edge_val:.1f}", (2, ev_y - 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 180, 0), 1)

        # 阈值标注
        cv2.putText(canvas, f"row_thr={threshold:.0f}", (2, thr_y - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 140, 255), 1)

        # 底部流动方向标注
        dir_label = {"bottom_to_top": "↑", "left_to_right": "→", "right_to_left": "←"}
        cv2.putText(canvas, f"flow: {dir_label.get(direction, '?')}",
                    (2, y0 + panel_h - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (100, 100, 100), 1)

    def _draw_projection_vertical(self, canvas, y0, panel_h, panel_w,
                                   profile, smoothed, threshold,
                                   edge_idx, lo, hi, edge_val,
                                   flip_y=False):
        """垂直投影 (水平流向旋转后): X=梯度幅值, Y=像素索引。

        纵轴 Y 与旋转后 P1/P2 图像对齐:
          Y=0 (顶部) 对应 profile[0] (流动起点), Y=panel_h (底部) 对应 profile[n-1] (终点)
        横轴 X: 梯度幅值 (0 → max_val, 左→右)
        """
        n = len(profile)
        margin_left, margin_right = 30, 8
        margin_top, margin_bot = 8, 14
        plot_w = panel_w - margin_left - margin_right
        plot_h = panel_h - margin_top - margin_bot
        if plot_w <= 0 or plot_h <= 0:
            return

        max_val = max(np.max(profile), np.max(smoothed), threshold) * 1.15
        if max_val <= 0:
            max_val = 1.0

        def to_x(v):
            return margin_left + int(v / max_val * plot_w)

        def to_y(i):
            # L→R (flip_y=True): profile[0] (湿/旋转后底部) → 绘于底部; profile[n-1] (干/顶部) → 绘于顶部
            # R→L (flip_y=False): profile[0] (干/旋转后顶部) → 绘于顶部; profile[n-1] (湿/底部) → 绘于底部
            if flip_y:
                return y0 + margin_top + int((n - 1 - i) * plot_h / (n - 1))
            else:
                return y0 + margin_top + int(i * plot_h / (n - 1))

        # 阈值垂直虚线 (橙色), 沿 X=threshold 从上到下
        thr_x = to_x(threshold)
        for py in range(y0 + margin_top, y0 + margin_top + plot_h, 6):
            cv2.line(canvas, (thr_x, py), (thr_x, min(py + 3, y0 + margin_top + plot_h - 1)),
                     (0, 140, 255), 1)

        # P2 约束范围 [lo..hi]: 水平半透明灰色带
        if lo is not None and hi is not None and lo <= hi:
            lo_y = to_y(lo)
            hi_y = to_y(hi)
            overlay = canvas[y0:y0 + panel_h, :panel_w].copy()
            cv2.rectangle(overlay, (0, lo_y), (panel_w, hi_y), (200, 200, 200), -1)
            cv2.rectangle(overlay, (0, lo_y), (panel_w, hi_y), (180, 180, 180), 1)
            canvas[y0:y0 + panel_h, :panel_w] = cv2.addWeighted(
                canvas[y0:y0 + panel_h, :panel_w], 0.85, overlay, 0.15, 0)
            # 标注 lo/hi (右侧)
            cv2.putText(canvas, f"lo={lo}", (panel_w - 48, lo_y + 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
            cv2.putText(canvas, f"hi={hi}", (panel_w - 48, hi_y - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)

        # 原始投影 (灰虚线): 每 2 点画一线段, X=profile[i] 处向右偏移
        prev_pt = None
        for i in range(n):
            pt = (to_x(profile[i]), to_y(i))
            if prev_pt is not None and i % 2 == 0:
                cv2.line(canvas, prev_pt, pt, (160, 160, 160), 1)
            prev_pt = pt

        # 平滑后投影 (蓝实线)
        pts = np.array([[to_x(smoothed[i]), to_y(i)] for i in range(n)], dtype=np.int32)
        cv2.polylines(canvas, [pts], False, (255, 80, 0), 2)

        # 检测峰值 (红点 + 水平标线)
        if edge_idx is not None and 0 <= edge_idx < n:
            peak_x = to_x(smoothed[edge_idx])
            peak_y = to_y(edge_idx)
            # 水平虚线穿过峰值
            cv2.line(canvas, (margin_left, peak_y),
                     (margin_left + plot_w, peak_y), (0, 0, 255), 1, cv2.LINE_AA)
            # 峰值标记圆点
            cv2.circle(canvas, (peak_x, peak_y), 4, (0, 0, 255), -1)
            # 峰值标注
            val_str = f"idx={edge_idx}"
            if edge_val is not None:
                val_str += f" v={edge_val:.1f}"
            cv2.putText(canvas, val_str, (peak_x + 5, peak_y - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 255), 1)

        # ★ per-row 中位数峰值参考线 (绿色点划线, 与阈值同单位可比)
        if edge_val is not None and edge_val > 0:
            ev_x = to_x(edge_val)
            for py in range(y0 + margin_top, y0 + margin_top + plot_h, 8):
                cv2.line(canvas, (ev_x, py), (ev_x, min(py + 4, y0 + margin_top + plot_h - 1)),
                         (0, 180, 0), 1)
            cv2.putText(canvas, f"row_peak={edge_val:.1f}", (ev_x + 2, y0 + margin_top + 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 180, 0), 1)

        # 阈值标注 (顶部)
        cv2.putText(canvas, f"row_thr={threshold:.0f}", (thr_x + 2, y0 + margin_top - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 140, 255), 1)

    # ---------- 辅助 ----------
    def _transform_points(self, pts, M):
        pts = np.array(pts, dtype=np.float64).reshape(-1, 2)
        return (M @ np.hstack([pts, np.ones((len(pts),1))]).T).T.astype(np.float32)

    def _reorder_corners(self, c):
        s, d = c[:,0]+c[:,1], c[:,0]-c[:,1]
        return np.array([c[np.argmin(s)], c[np.argmax(d)],
                         c[np.argmax(s)], c[np.argmin(d)]], dtype=np.float32)

    def _determine_orientation(self, frame, corners):
        for i in range(4):
            c = np.roll(corners, -i, axis=0)
            tl, tr, br, bl = c
            if (self._is_finder(frame, tl, tr, bl) and
                self._is_finder(frame, tr, tl, br) and
                self._is_finder(frame, bl, tl, br) and
                not self._is_finder(frame, br, tr, bl)):
                return np.array([tl, tr, br, bl], dtype=np.float32)
        return None

    def _is_finder(self, frame, corner, adj1, adj2):
        d1, d2 = np.linalg.norm(adj1-corner), np.linalg.norm(adj2-corner)
        ps = int(max(20, min(d1,d2)*0.4))
        x, y = int(corner[0]), int(corner[1])
        h, w = frame.shape[:2]
        x0, y0 = max(0,x-ps//2), max(0,y-ps//2)
        x1, y1 = min(w,x+ps//2), min(h,y+ps//2)
        if x1<=x0 or y1<=y0: return False
        roi = frame[y0:y1, x0:x1]
        if roi.size == 0: return False
        g = cv2.resize(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (64,64))
        _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        return (np.mean(bw==0) > 0.45 and
                np.mean(bw[10:54,10:54]==0) < 0.70 and
                np.mean(bw[20:44,20:44]==0) > 0.45)


# ====================================================================
# 8路管理器 + MQTT + 检测参数命令
# ====================================================================
class MultiChannelManager:

    GRID_ROWS = 2
    GRID_COLS = 4
    CELL_W = 480
    CELL_H = 360

    def __init__(self, camera_devices, tl_bl_real_cm,
                 cap_width=1920, cap_height=1080, cap_fps=30,
                 broker_ip=None, broker_port=1883, enable_mqtt=True,
                 mjpeg_port=7070,
                 mjpeg_max_active=None,
                 calibrate_mode=False, detect_enabled=True, headless=False,
                 exposure_time=312, awb_temp=4600):
        self.calibrate_mode = calibrate_mode
        # detect_enabled=False: 检测已搬到上位机, 本机 CAPTURE 只抓帧 (供 /frame 端点), 不跑 CV 检测
        self.detect_enabled = detect_enabled
        # headless=True: 无显示环境 (SSH/nohup 启动), 跳过 cv2.imshow/waitKey 否则抛 cv2.error 崩溃。
        # _gui_failed: 运行时首帧 imshow 抛错则自动转 headless (防御 DISPLAY 探测不准)。
        self.headless = headless
        self._gui_failed = False
        self.channels = []
        for i, cam_dev in enumerate(camera_devices):
            ch = ChannelDetector(
                channel_id=i, camera_device=cam_dev,
                tl_bl_real_cm=tl_bl_real_cm,
                cap_width=cap_width, cap_height=cap_height,
                calibrate_mode=calibrate_mode,
                cap_fps=cap_fps,
                exposure_time=exposure_time, awb_temp=awb_temp,
            )
            self.channels.append(ch)

        self.num_channels = len(self.channels)
        if self.num_channels <= 1:
            self.GRID_ROWS, self.GRID_COLS = 1, 1
            self.CELL_W, self.CELL_H = 960, 720
        elif self.num_channels <= 2:
            self.GRID_ROWS, self.GRID_COLS = 1, 2
            self.CELL_W, self.CELL_H = 640, 480
        elif self.num_channels <= 4:
            self.GRID_ROWS, self.GRID_COLS = 2, 2
            self.CELL_W, self.CELL_H = 640, 480
        else:
            self.GRID_ROWS, self.GRID_COLS = 2, 4
            self.CELL_W, self.CELL_H = 480, 360

        self.mqtt = None
        self.mqtt_enabled = enable_mqtt and MQTT_AVAILABLE and broker_ip is not None
        self.last_mqtt_report_time = 0.0

        # MJPEG HTTP 流式传输 (按需启动)
        self.mjpeg_streamer = None
        self.mjpeg_port = mjpeg_port
        self.mjpeg_max_active = (mjpeg_max_active
                                 if mjpeg_max_active is not None
                                 else self.num_channels)

        if self.mqtt_enabled:
            self.mqtt = MQTTManager(broker_ip, broker_port)
            self._register_mqtt_handlers()

        # 启动时尝试加载配置文件
        # 标定模式下跳过 calibration 和 roi_manual 加载
        self._load_config_from_file(load_calibration=not calibrate_mode)

    # ---------- 配置文件 ----------
    def _save_config_to_file(self, channels="all"):
        """保存检测参数+校准+ROI 到 JSON 配置文件（嵌套结构）"""
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
            except Exception:
                config = {}

        if channels == "all":
            targets = self.channels
        else:
            targets = [self.channels[channels]] if 0 <= channels < self.num_channels else []

        for ch in targets:
            key = str(ch.channel_id)
            entry = config.get(key, {})
            if not isinstance(entry, dict):
                entry = {}
            # detect_params
            entry["detect_params"] = dict(ch.detect_params)
            # calibration (仅当已标定时写入)
            cal = ch.get_calibration_dict()
            if cal is not None:
                entry["calibration"] = cal
            elif "calibration" in entry:
                del entry["calibration"]
            # roi_manual (仅当手动模式时写入)
            roi = ch.get_roi_dict()
            if roi is not None:
                entry["roi_manual"] = roi
            elif "roi_manual" in entry:
                del entry["roi_manual"]
            config[key] = entry

        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        print(f"[CONFIG] 配置已保存到 {CONFIG_FILE}")

    def _load_config_from_file(self, channels="all", load_calibration=True):
        """从 JSON 配置文件加载 detect_params + calibration + roi_manual。
        若 load_calibration=False（标定模式下），跳过 calibration 和 roi_manual 加载。"""
        if not os.path.exists(CONFIG_FILE):
            print(f"[CONFIG] 配置文件 {CONFIG_FILE} 不存在, 使用默认参数")
            return False

        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
        except Exception as e:
            print(f"[CONFIG] 读取配置文件失败: {e}")
            return False

        if channels == "all":
            targets = self.channels
        else:
            targets = [self.channels[channels]] if 0 <= channels < self.num_channels else []

        for ch in targets:
            key = str(ch.channel_id)
            if key not in config:
                continue
            entry = config[key]
            if not isinstance(entry, dict):
                continue

            # detect_params: 支持嵌套新格式 {"detect_params": {...}} 也兼容扁平旧格式
            if "detect_params" in entry and isinstance(entry["detect_params"], dict):
                params_src = entry["detect_params"]
            else:
                # 旧格式兼容：扁平 key 即为 detect_params
                params_src = entry

            for k, v in params_src.items():
                if k in PARAM_VALIDATORS and PARAM_VALIDATORS[k](v):
                    ch.detect_params[k] = v
            # ★ 向后兼容: 旧格式 front_contrast_threshold > 1.0 自动迁移为归一化值
            _ct = ch.detect_params.get("front_contrast_threshold")
            if _ct is not None and _ct > 1.0:
                _new_ct = _ct / 255.0
                ch.detect_params["front_contrast_threshold"] = _new_ct
                print(f"[CONFIG] CH{ch.channel_id} front_contrast_threshold "
                      f"已从旧格式 {_ct:.1f} 迁移为归一化值 {_new_ct:.3f}")
            print(f"[CONFIG] CH{ch.channel_id} detect_params 已从文件加载")

            # calibration（标定模式下跳过）
            if load_calibration and "calibration" in entry:
                ok, msg = ch.load_calibration_dict(entry["calibration"])
                if ok:
                    print(f"[CONFIG] CH{ch.channel_id} 校准已从配置文件加载")
                else:
                    print(f"[CONFIG] CH{ch.channel_id} 校准加载失败: {msg}")

            # roi_manual（标定模式下跳过）
            if load_calibration and "roi_manual" in entry:
                ok, msg = ch.load_roi_dict(entry["roi_manual"])
                if ok:
                    print(f"[CONFIG] CH{ch.channel_id} ROI 已从配置文件加载 (手动)")
                else:
                    print(f"[CONFIG] CH{ch.channel_id} ROI 加载失败: {msg}")

        return True

    def _reload_channel_config(self, ch_idx):
        """重载单个通道配置：从文件恢复 detect_params + roi_manual，保留校准"""
        if 0 <= ch_idx < self.num_channels:
            ok = self._load_config_from_file(channels=ch_idx, load_calibration=True)
            ch = self.channels[ch_idx]
            ch.height_buffer.clear()
            ch.latest_height_cm = None
            ch.latest_waterline_y = None
            ch._front_state = "WAITING"
            ch._front_ok_counter = 0
            ch._front_fail_counter = 0
            ch.ref_gray = None
            ch._capture_ref_pending = False
            ch._last_edge_idx = None
            print(f"[CONFIG] CH{ch.channel_id} 配置已重载 (校准保留: {ch.calibrated})")
            return ok
        return False

    def _factory_reset_channel(self, ch_idx):
        """工厂重置单个通道：清除校准+ROI+detect_params，回到出厂状态"""
        if 0 <= ch_idx < self.num_channels:
            ch = self.channels[ch_idx]
            ch.calibrated = False
            ch.rotation_angle_deg = 0.0
            ch.scale_factor = 0.0
            ch.qr_id = "Unknown"
            ch.rotation_matrix = None
            ch.rotated_size = None
            ch.frame_center = None
            ch.qr_corners_original = None
            ch.roi_bbox = None
            ch.roi_mode = "auto"
            ch.reference_y = 0
            ch.reference_x = 0.0
            ch.detect_params = dict(DEFAULT_DETECT_PARAMS)
            # 恢复通道自动方向设定
            if ch.channel_id <= 4:
                ch.detect_params["flow_direction"] = "right_to_left"
            else:
                ch.detect_params["flow_direction"] = "left_to_right"
            ch.height_buffer.clear()
            ch.latest_height_cm = None
            ch.latest_waterline_y = None
            ch._last_qr_time = 0.0
            ch._just_calibrated = False
            ch._front_state = "WAITING"
            ch._front_ok_counter = 0
            ch._front_fail_counter = 0
            ch.ref_gray = None
            ch._capture_ref_pending = False
            ch._last_edge_idx = None
            # 停采并回到 IDLE
            if ch.state in (ch.STATE_CAPTURE, ch.STATE_STREAM):
                ch.deactivate()
            print(f"[FACTORY_RESET] CH{ch.channel_id} 已恢复出厂状态")
            return True
        return False

    # ---------- 参数校验 ----------
    @staticmethod
    def _validate_params(params):
        """校验参数, 返回 (valid_params, errors)"""
        valid = {}
        errors = []
        for k, v in params.items():
            if k not in PARAM_VALIDATORS:
                errors.append(f"未知参数: {k}")
                continue
            if PARAM_VALIDATORS[k](v):
                valid[k] = v
            else:
                errors.append(f"{k} 值 {v} 非法, 允许范围: {PARAM_HINTS[k]}")
        return valid, errors

    # ---------- MQTT handlers ----------
    def _register_mqtt_handlers(self):
        m = self.mqtt

        # ---- reset (改为 reload_config 语义) ----
        def handle_reset(payload):
            ch = payload.get("channel", "all") if isinstance(payload, dict) else "all"
            if str(ch) == "all":
                for i in range(self.num_channels):
                    self._reload_channel_config(i)
                print("[CMD] 全部通道重载配置")
                m.publish_ack("reset", "ok", channel="all",
                              extra={"message": "reload_config"})
            else:
                idx = int(ch) - 1
                if 0 <= idx < self.num_channels:
                    self._reload_channel_config(idx)
                    print(f"[CMD] 通道 {idx+1} 重载配置")
                    m.publish_ack("reset", "ok", channel=idx+1,
                                  extra={"message": "reload_config"})
        m.register_handler(m.TOPIC_CMD_RESET, handle_reset)

        # ---- set_interval ----
        def handle_set_interval(payload):
            interval = float(payload.get("interval", 1.0))
            m.report_interval = max(0.1, interval)
            print(f"[CMD] 上报周期 → {m.report_interval:.1f}s")
        m.register_handler(m.TOPIC_CMD_SET_INTERVAL, handle_set_interval)

        # ---- set_threshold ----
        def handle_set_threshold(payload):
            m.alarm_min = payload.get("min")
            m.alarm_max = payload.get("max")
            if m.alarm_min is not None: m.alarm_min = float(m.alarm_min)
            if m.alarm_max is not None: m.alarm_max = float(m.alarm_max)
            print(f"[CMD] 报警阈值 → min={m.alarm_min} max={m.alarm_max}")
        m.register_handler(m.TOPIC_CMD_SET_THRESHOLD, handle_set_threshold)

        # ---- query_status ----
        def handle_query_status(payload):
            extra = {
                "num_channels": self.num_channels,
                "channels": [ch.get_status_dict() for ch in self.channels],
                "report_interval": m.report_interval,
                "alarm_min": m.alarm_min, "alarm_max": m.alarm_max,
            }
            m.publish_status("online", extra)
            print("[CMD] 状态已上报")
        m.register_handler(m.TOPIC_CMD_QUERY_STATUS, handle_query_status)

        # ---- restart_camera ----
        def handle_restart_camera(payload):
            ch = payload.get("channel", 1) if isinstance(payload, dict) else 1
            idx = int(ch) - 1
            if 0 <= idx < self.num_channels:
                threading.Thread(target=self.channels[idx].restart_capture,
                                 daemon=True).start()
                print(f"[CMD] 通道 {idx+1} 摄像头重启中...")
        m.register_handler(m.TOPIC_CMD_RESTART_CAM, handle_restart_camera)

        # ---- set_detect_param ----
        def handle_set_detect_param(payload):
            if not isinstance(payload, dict):
                return
            ch_spec = payload.get("channel", "all")
            params = payload.get("params", {})
            save = payload.get("save", False)

            valid, errors = self._validate_params(params)

            if errors:
                m.publish_ack("set_detect_param", "error", channel=ch_spec,
                              extra={"message": "; ".join(errors)})
                print(f"[CMD] set_detect_param 参数错误: {errors}")
                return

            if not valid:
                m.publish_ack("set_detect_param", "error", channel=ch_spec,
                              extra={"message": "没有有效参数"})
                return

            # 确定目标通道
            if str(ch_spec) == "all":
                targets = self.channels
            else:
                idx = int(ch_spec) - 1
                targets = [self.channels[idx]] if 0 <= idx < self.num_channels else []

            for ch in targets:
                ch.detect_params.update(valid)
                print(f"[CMD] CH{ch.channel_id} 参数更新: {valid}")

            if save:
                if str(ch_spec) == "all":
                    self._save_config_to_file("all")
                else:
                    self._save_config_to_file(int(ch_spec) - 1)

            m.publish_ack("set_detect_param", "ok", channel=ch_spec,
                          extra={"updated": valid})

        m.register_handler(m.TOPIC_CMD_SET_DETECT_PARAM, handle_set_detect_param)

        # ---- get_detect_param ----
        def handle_get_detect_param(payload):
            ch_spec = payload.get("channel", "all") if isinstance(payload, dict) else "all"
            if str(ch_spec) == "all":
                targets = self.channels
            else:
                idx = int(ch_spec) - 1
                targets = [self.channels[idx]] if 0 <= idx < self.num_channels else []

            params_list = [ch.get_detect_params_dict() for ch in targets]
            m.publish_detect_params(m._client_id_str, params_list)
            print(f"[CMD] 检测参数已上报 ({len(params_list)} 通道)")

        m.register_handler(m.TOPIC_CMD_GET_DETECT_PARAM, handle_get_detect_param)

        # ---- save_detect_param ----
        def handle_save_detect_param(payload):
            ch_spec = payload.get("channel", "all") if isinstance(payload, dict) else "all"
            if str(ch_spec) == "all":
                self._save_config_to_file("all")
            else:
                self._save_config_to_file(int(ch_spec) - 1)
            m.publish_ack("save_detect_param", "ok", channel=ch_spec)

        m.register_handler(m.TOPIC_CMD_SAVE_DETECT_PARAM, handle_save_detect_param)

        # ---- load_detect_param ----
        def handle_load_detect_param(payload):
            ch_spec = payload.get("channel", "all") if isinstance(payload, dict) else "all"
            if str(ch_spec) == "all":
                ok = self._load_config_from_file("all")
            else:
                ok = self._load_config_from_file(int(ch_spec) - 1)
            result = "ok" if ok else "error"
            extra = {} if ok else {"message": f"配置文件 {CONFIG_FILE} 不存在或读取失败"}
            m.publish_ack("load_detect_param", result, channel=ch_spec, extra=extra)

        m.register_handler(m.TOPIC_CMD_LOAD_DETECT_PARAM, handle_load_detect_param)

        # ---- stream_start ----
        def handle_stream_start(payload):
            if not isinstance(payload, dict):
                return
            ch_id = int(payload.get("channel", 1))

            # 延迟初始化 MJPEG streamer (首次 stream_start 时)
            if self.mjpeg_streamer is None:
                from mjpeg_streamer import MJPEGStreamer
                self.mjpeg_streamer = MJPEGStreamer(
                    port=self.mjpeg_port, max_active=self.mjpeg_max_active,
                    multi_channel_manager=self)
                self.mjpeg_streamer.start()

            result = self.mjpeg_streamer.stream_start(ch_id)
            m.publish_ack("stream_start", result["result"],
                          channel=ch_id,
                          extra={"port": result.get("port", 7070)})
            if result.get("result") == "error":
                print(f"[CMD] stream_start CH{ch_id} → ⚠ 拒绝: {result.get('message', 'limit reached')} "
                      f"(active={self.mjpeg_streamer._active_count()}/{self.mjpeg_max_active})")
            else:
                print(f"[CMD] stream_start CH{ch_id} → {result}")

        m.register_handler(m.TOPIC_CMD_STREAM_START, handle_stream_start)

        # ---- stream_stop ----
        def handle_stream_stop(payload):
            if not isinstance(payload, dict):
                return
            ch_spec = payload.get("channel", "all")
            if str(ch_spec) == "all":
                if self.mjpeg_streamer:
                    self.mjpeg_streamer.stream_stop_all()
                m.publish_ack("stream_stop", "ok", channel="all")
                print("[CMD] stream_stop all")
            else:
                ch_id = int(ch_spec)
                if self.mjpeg_streamer:
                    result = self.mjpeg_streamer.stream_stop(ch_id)
                else:
                    result = {"result": "error", "message": "Streamer not running"}
                m.publish_ack("stream_stop", result["result"], channel=ch_id)
                print(f"[CMD] stream_stop CH{ch_id} → {result}")

        m.register_handler(m.TOPIC_CMD_STREAM_STOP, handle_stream_stop)

        # ---- diag_camera ----
        def handle_diag_camera(payload):
            if not isinstance(payload, dict):
                return
            ch_spec = payload.get("channel", "all")
            if str(ch_spec) == "all":
                targets = self.channels
            else:
                idx = int(ch_spec) - 1
                targets = [self.channels[idx]] if 0 <= idx < self.num_channels else []

            diag_list = [ch.get_diagnostic_info() for ch in targets]
            extra = {
                "num_channels": len(diag_list),
                "channels": diag_list,
            }
            m.publish_ack("diag_camera", "ok", channel=ch_spec, extra=extra)
            print(f"[CMD] diag_camera → {len(diag_list)} 通道诊断已上报")

        m.register_handler(m.TOPIC_CMD_DIAG_CAMERA, handle_diag_camera)

        # ---- set_active_channels ----
        def handle_set_active_channels(payload):
            """上位机下发的活跃通道集合, 香橙派按指令启停摄像头。

            Payload:
                channels:       需要 CAPTURE 的通道列表 [1, 3, 5]
                stream_channels: 额外需要 MJPEG 流的通道列表 [3]  (⊆ channels)
                action:         "set"(默认, 全量替换) | "add"(增量激活) | "remove"(增量停用)
            """
            if not isinstance(payload, dict):
                return
            action = payload.get("action", "set")
            target_capture = set(payload.get("channels", []))
            target_stream = set(payload.get("stream_channels", []))

            for ch in self.channels:
                ch_id = ch.channel_id

                with ch._state_lock:
                    is_capturing = ch.state in (ch.STATE_CAPTURE, ch.STATE_STREAM)
                    is_streaming = ch.state == ch.STATE_STREAM

                if action == "set":
                    # 全量替换：不在目标集合的通道全部停用
                    want_capture = ch_id in target_capture
                    want_stream = ch_id in target_stream

                    # 采集启停
                    if want_capture and not is_capturing:
                        ch.activate_capture()
                    elif not want_capture and is_capturing:
                        if is_streaming and self.mjpeg_streamer:
                            self.mjpeg_streamer.stream_stop(ch_id)
                        ch.deactivate()
                elif action == "add":
                    # 增量激活：只激活指定通道，不影响已活跃的通道
                    want_capture = ch_id in target_capture
                    want_stream = ch_id in target_stream

                    if want_capture and not is_capturing:
                        ch.activate_capture()
                    # 不在此集合的通道保持现状
                elif action == "remove":
                    # 增量停用：只停用指定通道，不影响其他活跃通道
                    want_remove = ch_id in target_capture

                    if want_remove and is_capturing:
                        if is_streaming and self.mjpeg_streamer:
                            self.mjpeg_streamer.stream_stop(ch_id)
                        ch.deactivate()
                    # 不在此集合的通道保持现状
                    continue  # 跳过 stream 处理（remove 只需停用）
                else:
                    print(f"[CMD] set_active_channels: 未知 action={action}, 忽略")
                    return

                # 重新读取状态 (activate/deactivate 可能改变了状态)
                with ch._state_lock:
                    is_capturing = ch.state in (ch.STATE_CAPTURE, ch.STATE_STREAM)
                    is_streaming = ch.state == ch.STATE_STREAM

                # MJPEG 流处理
                if action == "add":
                    # 增量模式：只启动新流，不关闭已有流
                    if want_stream and is_capturing and not is_streaming:
                        ch.activate_stream()
                        if self.mjpeg_streamer is None:
                            from mjpeg_streamer import MJPEGStreamer
                            self.mjpeg_streamer = MJPEGStreamer(
                                port=self.mjpeg_port,
                                max_active=self.mjpeg_max_active,
                                multi_channel_manager=self)
                            self.mjpeg_streamer.start()
                        self.mjpeg_streamer.stream_start(ch_id)
                else:
                    # set 模式：全量控制 MJPEG 启停
                    if want_stream and is_capturing and not is_streaming:
                        ch.activate_stream()
                        if self.mjpeg_streamer is None:
                            from mjpeg_streamer import MJPEGStreamer
                            self.mjpeg_streamer = MJPEGStreamer(
                                port=self.mjpeg_port,
                                max_active=self.mjpeg_max_active,
                                multi_channel_manager=self)
                            self.mjpeg_streamer.start()
                        self.mjpeg_streamer.stream_start(ch_id)
                    elif not want_stream and is_streaming:
                        ch.deactivate_stream()
                        if self.mjpeg_streamer:
                            self.mjpeg_streamer.stream_stop(ch_id)

            active = [ch.channel_id for ch in self.channels
                      if ch.state in (ch.STATE_CAPTURE, ch.STATE_STREAM)]
            streaming = [ch.channel_id for ch in self.channels
                         if ch.state == ch.STATE_STREAM]
            print(f"[CMD] set_active_channels → "
                  f"capture={sorted(active)} stream={sorted(streaming)}")

            m.publish_ack("set_active_channels", "ok",
                          extra={"active": sorted(active),
                                 "streaming": sorted(streaming)})
        m.register_handler(m.TOPIC_CMD_SET_ACTIVE_CHANNELS,
                          handle_set_active_channels)

        # ---- set_roi (新增) ----
        def handle_set_roi(payload):
            if not isinstance(payload, dict):
                return
            ch_spec = payload.get("channel", "all")
            save = payload.get("save", False)

            def _apply_roi(ch, p):
                required = ["x", "y", "w", "h"]
                if not all(k in p for k in required):
                    return False, "缺少必填字段 x/y/w/h"
                x, y, w, h = int(p["x"]), int(p["y"]), int(p["w"]), int(p["h"])
                if w < 20 or h < 20:
                    return False, f"ROI 尺寸过小 ({w}x{h}), 最小 20x20"
                ch.roi_bbox = (x, y, w, h)
                ch.roi_mode = "manual"
                ch.reference_y = float(p.get("reference_y", y))
                print(f"[CMD] CH{ch.channel_id} set_roi "
                      f"bbox=({x},{y},{w},{h}) reference_y={ch.reference_y:.0f}")
                return True, "ok"

            if str(ch_spec) == "all":
                results = []
                for c in self.channels:
                    ok, msg = _apply_roi(c, payload)
                    results.append((c.channel_id, ok, msg))
                m.publish_ack("set_roi", "ok", channel="all",
                              extra={"results": [{"ch": r[0], "result": r[1], "msg": r[2]}
                                                 for r in results]})
            else:
                idx = int(ch_spec) - 1
                if 0 <= idx < self.num_channels:
                    ok, msg = _apply_roi(self.channels[idx], payload)
                    m.publish_ack("set_roi", "ok" if ok else "error",
                                  channel=idx+1, extra={"message": msg})
                else:
                    m.publish_ack("set_roi", "error", channel=ch_spec,
                                  extra={"message": "无效通道"})

            if save:
                if str(ch_spec) == "all":
                    self._save_config_to_file("all")
                else:
                    self._save_config_to_file(int(ch_spec) - 1)

        m.register_handler(m.TOPIC_CMD_SET_ROI, handle_set_roi)

        # ---- clear_roi (新增) ----
        def handle_clear_roi(payload):
            if not isinstance(payload, dict):
                ch_spec = "all"
            else:
                ch_spec = payload.get("channel", "all")

            if str(ch_spec) == "all":
                for c in self.channels:
                    c.roi_bbox = None
                    c.roi_mode = "auto"
                    c.reference_y = 0
                    c.reference_x = 0.0
                self._save_config_to_file("all")
                print("[CMD] 全部通道清除 ROI")
                m.publish_ack("clear_roi", "ok", channel="all")
            else:
                idx = int(ch_spec) - 1
                if 0 <= idx < self.num_channels:
                    ch = self.channels[idx]
                    ch.roi_bbox = None
                    ch.roi_mode = "auto"
                    ch.reference_y = 0
                    ch.reference_x = 0.0
                    self._save_config_to_file(idx)
                    print(f"[CMD] CH{ch.channel_id} 清除 ROI")
                    m.publish_ack("clear_roi", "ok", channel=idx+1)
                else:
                    m.publish_ack("clear_roi", "error", channel=ch_spec,
                                  extra={"message": "无效通道"})

        m.register_handler(m.TOPIC_CMD_CLEAR_ROI, handle_clear_roi)

        # ---- save_calibration (新增) ----
        def handle_save_calibration(payload):
            if not isinstance(payload, dict):
                ch_spec = "all"
            else:
                ch_spec = payload.get("channel", "all")
            if str(ch_spec) == "all":
                self._save_config_to_file("all")
            else:
                self._save_config_to_file(int(ch_spec) - 1)
            m.publish_ack("save_calibration", "ok", channel=ch_spec)
            print(f"[CMD] save_calibration channel={ch_spec}")

        m.register_handler(m.TOPIC_CMD_SAVE_CALIBRATION, handle_save_calibration)

        # ---- reload_config (新增) ----
        def handle_reload_config(payload):
            if not isinstance(payload, dict):
                ch_spec = "all"
            else:
                ch_spec = payload.get("channel", "all")
            if str(ch_spec) == "all":
                for i in range(self.num_channels):
                    self._reload_channel_config(i)
                m.publish_ack("reload_config", "ok", channel="all")
            else:
                idx = int(ch_spec) - 1
                if 0 <= idx < self.num_channels:
                    self._reload_channel_config(idx)
                    m.publish_ack("reload_config", "ok", channel=idx+1)
                else:
                    m.publish_ack("reload_config", "error", channel=ch_spec,
                                  extra={"message": "无效通道"})
            print(f"[CMD] reload_config channel={ch_spec}")

        m.register_handler(m.TOPIC_CMD_RELOAD_CONFIG, handle_reload_config)

        # ---- factory_reset (新增) ----
        def handle_factory_reset(payload):
            if not isinstance(payload, dict):
                ch_spec = "all"
            else:
                ch_spec = payload.get("channel", "all")
            if str(ch_spec) == "all":
                for i in range(self.num_channels):
                    self._factory_reset_channel(i)
                self._save_config_to_file("all")
                m.publish_ack("factory_reset", "ok", channel="all")
            else:
                idx = int(ch_spec) - 1
                if 0 <= idx < self.num_channels:
                    self._factory_reset_channel(idx)
                    self._save_config_to_file(idx)
                    m.publish_ack("factory_reset", "ok", channel=idx+1)
                else:
                    m.publish_ack("factory_reset", "error", channel=ch_spec,
                                  extra={"message": "无效通道"})
            print(f"[CMD] factory_reset channel={ch_spec}")

        m.register_handler(m.TOPIC_CMD_FACTORY_RESET, handle_factory_reset)

        # ---- capture_reference (P0: 参考图差分) ----
        def handle_capture_reference(payload):
            """拍摄当前帧作为干板参考图 I0，用于后续帧差分检测。

            Payload:
                channel: 通道号 (1-8) 或 "all"
            前置条件: 通道必须已标定且处于 CAPTURE/STREAM 状态
            """
            if not isinstance(payload, dict):
                ch_spec = "all"
            else:
                ch_spec = payload.get("channel", "all")

            def _request_one(ch):
                with ch._state_lock:
                    cur_state = ch.state
                if cur_state not in (ch.STATE_CAPTURE, ch.STATE_STREAM):
                    return False, f"通道未在采集状态 (当前: {cur_state})"
                if not ch.calibrated:
                    return False, "通道未标定"
                if ch.roi_bbox is None:
                    return False, "通道无有效 ROI"
                ch._capture_ref_pending = True
                return True, "pending"

            if str(ch_spec) == "all":
                results = []
                for c in self.channels:
                    ok, msg = _request_one(c)
                    results.append({"ch": c.channel_id, "ok": ok, "msg": msg})
                ok_count = sum(1 for r in results if r["ok"])
                m.publish_ack("capture_reference",
                              "ok" if ok_count > 0 else "error",
                              channel="all",
                              extra={"results": results,
                                     "message": f"{ok_count}/{len(results)} 通道已请求"})
                print(f"[CMD] capture_reference all → {ok_count} 通道已请求参考图捕获")
            else:
                idx = int(ch_spec) - 1
                if 0 <= idx < self.num_channels:
                    ok, msg = _request_one(self.channels[idx])
                    m.publish_ack("capture_reference",
                                  "ok" if ok else "error",
                                  channel=idx + 1,
                                  extra={"message": msg})
                    print(f"[CMD] capture_reference CH{idx + 1} → {msg}")
                else:
                    m.publish_ack("capture_reference", "error", channel=ch_spec,
                                  extra={"message": "无效通道"})

        m.register_handler(m.TOPIC_CMD_CAPTURE_REFERENCE, handle_capture_reference)

        # ---- start_calibrate ----
        def handle_start_calibrate(payload):
            """启用 QR 检测模式：激活摄像头（如需要）→ 开始周期性 QR 检测。
            标定成功后自动保存并退出校准模式。"""
            if not isinstance(payload, dict):
                ch_spec = "all"
            else:
                ch_spec = payload.get("channel", "all")

            def _start_one(ch):
                # 确定当前状态，必要时激活摄像头
                with ch._state_lock:
                    cur_state = ch.state
                if cur_state == ch.STATE_IDLE:
                    if not ch.activate_capture():
                        return False, "摄像头激活失败"
                elif cur_state == ch.STATE_ERROR:
                    if not ch.restart_capture():
                        return False, "摄像头重启失败"
                # CAPTURE/STREAM 状态：直接启用校准模式
                ch._calibrate_mode = True
                ch._last_qr_time = 0.0  # 立即触发首次 QR 检测
                return True, ch.state

            if str(ch_spec) == "all":
                results = []
                for c in self.channels:
                    ok, msg = _start_one(c)
                    results.append({"ch": c.channel_id, "ok": ok, "state": msg if ok else msg})
                m.publish_ack("start_calibrate", "ok", channel="all",
                              extra={"results": results})
                print(f"[CMD] start_calibrate all → {results}")
            else:
                idx = int(ch_spec) - 1
                if 0 <= idx < self.num_channels:
                    ok, msg = _start_one(self.channels[idx])
                    ch = self.channels[idx]
                    m.publish_ack("start_calibrate",
                                  "ok" if ok else "error",
                                  channel=idx + 1,
                                  extra={"state": ch.state,
                                         "calibrated": ch.calibrated,
                                         "message": msg if not ok else "ok"})
                    print(f"[CMD] start_calibrate CH{idx + 1} → ok={ok} state={ch.state}")
                else:
                    m.publish_ack("start_calibrate", "error", channel=ch_spec,
                                  extra={"message": "无效通道"})

        m.register_handler(m.TOPIC_CMD_START_CALIBRATE, handle_start_calibrate)

        # ---- stop_calibrate ----
        def handle_stop_calibrate(payload):
            """停用 QR 检测模式，保留已有标定结果。"""
            if not isinstance(payload, dict):
                ch_spec = "all"
            else:
                ch_spec = payload.get("channel", "all")

            if str(ch_spec) == "all":
                for c in self.channels:
                    c._calibrate_mode = False
                m.publish_ack("stop_calibrate", "ok", channel="all")
                print("[CMD] stop_calibrate all")
            else:
                idx = int(ch_spec) - 1
                if 0 <= idx < self.num_channels:
                    self.channels[idx]._calibrate_mode = False
                    m.publish_ack("stop_calibrate", "ok", channel=idx + 1)
                    print(f"[CMD] stop_calibrate CH{idx + 1}")
                else:
                    m.publish_ack("stop_calibrate", "error", channel=ch_spec,
                                  extra={"message": "无效通道"})

        m.register_handler(m.TOPIC_CMD_STOP_CALIBRATE, handle_stop_calibrate)

        # ---- set_calibration (人工标定) ----
        def handle_set_calibration(payload):
            """接收上位机下发的人工标定参数 (rotation_angle_deg + roi + scale_factor)。
            替代 QR 码自动标定流程，由用户在 TankVisionDialog 中画线标定后下发。
            """
            if not isinstance(payload, dict):
                m.publish_ack("set_calibration", "error",
                              extra={"message": "payload 必须为 JSON 对象"})
                return

            ch_spec = payload.get("channel", "all")
            rotation_angle_deg = payload.get("rotation_angle_deg")
            roi_data = payload.get("roi")
            scale_factor = payload.get("scale_factor")
            save = payload.get("save", False)

            if rotation_angle_deg is None:
                m.publish_ack("set_calibration", "error", channel=ch_spec,
                              extra={"message": "缺少 rotation_angle_deg"})
                return

            def _apply_one(ch, p):
                roi_bbox = None
                ref_y = None
                ref_x = None
                if "roi" in p and p["roi"] is not None:
                    r = p["roi"]
                    if all(k in r for k in ("x", "y", "w", "h")):
                        w, h = int(r["w"]), int(r["h"])
                        if w < 20 or h < 20:
                            return False, f"ROI 尺寸过小 ({w}x{h}), 最小 20x20"
                        roi_bbox = (int(r["x"]), int(r["y"]), w, h)
                        ref_y = r.get("reference_y")
                        ref_x = r.get("reference_x")
                ch._apply_manual_calibration(
                    rotation_angle_deg=p["rotation_angle_deg"],
                    roi_bbox=roi_bbox,
                    reference_y=ref_y,
                    reference_x=ref_x,
                    scale_factor=p.get("scale_factor"),
                )
                return True, "ok"

            if str(ch_spec) == "all":
                results = []
                for c in self.channels:
                    ok, msg = _apply_one(c, payload)
                    results.append({"ch": c.channel_id, "ok": ok, "msg": msg})
                m.publish_ack("set_calibration", "ok", channel="all",
                              extra={"results": results})
            else:
                idx = int(ch_spec) - 1
                if 0 <= idx < self.num_channels:
                    ok, msg = _apply_one(self.channels[idx], payload)
                    ch = self.channels[idx]
                    m.publish_ack("set_calibration", "ok" if ok else "error",
                                  channel=idx + 1,
                                  extra={"message": msg,
                                         "calibrated": ch.calibrated})
                    print(f"[CMD] set_calibration CH{idx + 1} "
                          f"angle={rotation_angle_deg:.2f}° "
                          f"roi={ch.roi_bbox} calibrated={ch.calibrated}")
                else:
                    m.publish_ack("set_calibration", "error", channel=ch_spec,
                                  extra={"message": "无效通道"})

            if save:
                if str(ch_spec) == "all":
                    self._save_config_to_file("all")
                else:
                    self._save_config_to_file(int(ch_spec) - 1)

        m.register_handler(m.TOPIC_CMD_SET_CALIBRATION, handle_set_calibration)

        # ---- get_calibration (查询标定状态) ----
        def handle_get_calibration(payload):
            """返回指定通道的当前标定状态，供上位机 TankVisionDialog 打开时查询。"""
            if not isinstance(payload, dict):
                ch_spec = "all"
            else:
                ch_spec = payload.get("channel", "all")

            def _build_calib_info(ch):
                info = {
                    "channel": ch.channel_id,
                    "calibrated": ch.calibrated,
                    "rotation_angle_deg": float(ch.rotation_angle_deg),
                    "scale_factor": float(ch.scale_factor),
                    "roi_mode": ch.roi_mode,
                    "roi": None,
                    "flow_direction": ch.detect_params.get("flow_direction",
                                                           "left_to_right"),
                }
                if ch.roi_bbox is not None:
                    x, y, w, h = ch.roi_bbox
                    info["roi"] = {"x": int(x), "y": int(y),
                                   "w": int(w), "h": int(h),
                                   "reference_y": float(ch.reference_y),
                                   "reference_x": float(ch.reference_x)}
                return info

            if str(ch_spec) == "all":
                calib_list = [_build_calib_info(c) for c in self.channels]
                m.publish_ack("get_calibration", "ok", channel="all",
                              extra={"channels": calib_list})
            else:
                idx = int(ch_spec) - 1
                if 0 <= idx < self.num_channels:
                    info = _build_calib_info(self.channels[idx])
                    m.publish_ack("get_calibration", "ok", channel=idx + 1,
                                  extra=info)
                else:
                    m.publish_ack("get_calibration", "error", channel=ch_spec,
                                  extra={"message": "无效通道"})

        m.register_handler(m.TOPIC_CMD_GET_CALIBRATION, handle_get_calibration)

    # ---------- MQTT 上报 ----------
    def _mqtt_report(self):
        if not self.mqtt or not self.mqtt.connected:
            return
        now = time.time()
        if now - self.last_mqtt_report_time < self.mqtt.report_interval:
            return
        self.last_mqtt_report_time = now

        data_list = []
        for ch in self.channels:
            d = ch.get_status_dict()
            data_list.append(d)
            h = d["height_cm"]
            if h is not None:
                if self.mqtt.alarm_min is not None and h < self.mqtt.alarm_min:
                    self.mqtt.publish_alarm(ch.channel_id, h, "low")
                if self.mqtt.alarm_max is not None and h > self.mqtt.alarm_max:
                    self.mqtt.publish_alarm(ch.channel_id, h, "high")
        self.mqtt.publish_all_channels(data_list)

        # 周期性发布通道状态摘要 (每30s一次, 供上位机监控)
        if not getattr(self, '_last_status_summary_time', 0):
            self._last_status_summary_time = 0.0
        if now - self._last_status_summary_time >= 30.0:
            self._last_status_summary_time = now
            summary = {}
            for ch in self.channels:
                summary[str(ch.channel_id)] = ch.state
            self.mqtt.publish_status("online", extra={
                "channels_summary": summary,
                "num_active": sum(1 for ch in self.channels
                                  if ch.state in (ch.STATE_CAPTURE, ch.STATE_STREAM)),
            })

    # ---------- 启停 ----------
    def _ensure_mjpeg_server(self):
        """确保 MJPEG HTTP 服务已启动 (同时承载 /frame 单帧 与 /stream 连续流)。幂等。

        --no-detect 下上位机靠 GET /frame/ch{N} 拉帧检测, 故服务必须开机即起 —
        不能沿用"首次 stream_start 才懒启动", 否则上位机仅发 set_active_channels(不含
        streaming) 时 7070 无监听, /frame 与 /stream 全部连不上。
        """
        if self.mjpeg_streamer is None:
            from mjpeg_streamer import MJPEGStreamer
            self.mjpeg_streamer = MJPEGStreamer(
                port=self.mjpeg_port, max_active=self.mjpeg_max_active,
                multi_channel_manager=self)
            self.mjpeg_streamer.start()

    def start(self):
        if self.calibrate_mode:
            # 标定模式：全部通道启动，用于 QR 标定
            ok_count = 0
            for i, ch in enumerate(self.channels):
                if i > 0:
                    if i == 4:
                        time.sleep(0.5)
                    else:
                        time.sleep(0.15)
                if ch.start_capture():
                    ok_count += 1
            print(f"[CALIBRATE] 标定模式：已启动 {ok_count}/{self.num_channels} 路摄像头")
            print("  放置 QR 码于画面中，标定成功后自动保存。Ctrl+C 退出。")
            if ok_count == 0:
                print("错误: 没有可用的摄像头")
                return False
        else:
            # 正常模式：静默启动，全部 IDLE，等待上位机指令
            uncalibrated_count = sum(1 for ch in self.channels if not ch.calibrated)
            print(f"静默启动：{self.num_channels} 路通道就绪 (IDLE)")
            if uncalibrated_count > 0:
                print(f"  {uncalibrated_count} 路未标定（液位=N/A，可从上位机 UI 远程标定）")
            print("  等待上位机 set_active_channels 指令...")
            # 不启动任何摄像头

        if self.mqtt_enabled:
            self.mqtt.connect()
        return True

    def run(self):
        if not self.start():
            return

        # /frame 与 /stream 同由 MJPEG HTTP 服务承载; 上位机拉帧检测依赖 /frame,
        # 故开机即起 (不等 stream_start 懒启动), 否则 7070 无监听、上位机拉帧全失败。
        self._ensure_mjpeg_server()

        mqtt_tag = f"MQTT→{self.mqtt.broker_ip}:{self.mqtt.broker_port}" \
                   if self.mqtt_enabled else "MQTT未启用"
        print("=" * 60)
        print(f"TCL液位检测 — {self.num_channels}路 | {mqtt_tag}")
        print(f"网格: {self.GRID_ROWS}×{self.GRID_COLS}, "
              f"每格: {self.CELL_W}×{self.CELL_H}")
        print("按 q 退出, 1-8 重载对应通道配置")
        print("=" * 60)

        blank = np.zeros((self.CELL_H, self.CELL_W, 3), dtype=np.uint8)
        cv2.putText(blank, "No Signal", (self.CELL_W//2-80, self.CELL_H//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (80, 80, 80), 2)

        last_print_time = time.time()

        while True:
            cells = []
            for i in range(self.GRID_ROWS * self.GRID_COLS):
                if i < self.num_channels:
                    ch = self.channels[i]
                    # 跳过 IDLE/ERROR 通道, 显示状态标签
                    if ch.state in (ch.STATE_IDLE, ch.STATE_ERROR):
                        cell = blank.copy()
                        label = f"CH{ch.channel_id}: {ch.state.upper()}"
                        color = (0, 165, 255) if ch.state == ch.STATE_IDLE else (0, 0, 255)
                        cv2.putText(cell, label, (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                        if ch.state == ch.STATE_IDLE and ch.calibrated:
                            cv2.putText(cell, "(标定已保留)", (10, 55),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                    else:
                        frame = ch.get_frame()
                        if frame is not None:
                            # detect_enabled=False: 只抓帧不检测 (检测在上位机), 渲染=原始帧
                            rendered = ch.process_frame(frame) if self.detect_enabled else frame
                            # 缓存渲染帧供 MJPEG HTTP 线程读取
                            with ch.rendered_lock:
                                ch.latest_rendered = rendered
                            cell = cv2.resize(rendered, (self.CELL_W, self.CELL_H))
                        else:
                            cell = blank.copy()
                            cv2.putText(cell, f"CH{ch.channel_id}: No Frame",
                                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                                        0.7, (0, 0, 255), 2)
                else:
                    cell = blank.copy()
                cells.append(cell)

            rows = []
            for r in range(self.GRID_ROWS):
                row_cells = cells[r * self.GRID_COLS : (r+1) * self.GRID_COLS]
                rows.append(np.hstack(row_cells))
            grid = np.vstack(rows)

            # 无显示环境 (SSH/nohup) 下 imshow 抛 cv2.error 会崩溃整个采集进程,
            # 致香橙派从不上线、7070 不出帧。headless 时跳过; 误判时首帧抛错自动转 headless。
            if not self.headless and not self._gui_failed:
                try:
                    cv2.imshow("Water Level Detector - Multi Channel", grid)
                except cv2.error as e:
                    self._gui_failed = True
                    print(f"[GUI] cv2.imshow 失败 (无显示环境?), 转 headless 模式: {e}")

            self._mqtt_report()

            # MJPEG streamer 超时回收
            if self.mjpeg_streamer:
                self.mjpeg_streamer.cleanup_timeouts()

            # 标定自动保存（CLI --calibrate 或 MQTT start_calibrate 均生效）
            for ch in self.channels:
                if ch._just_calibrated:
                    ch._just_calibrated = False
                    ch._calibrate_mode = False  # 自动退出校准模式
                    self._save_config_to_file(ch.channel_id - 1)
                    print(f"[CALIBRATE] CH{ch.channel_id} 标定已自动保存到 {CONFIG_FILE}")

            now = time.time()
            if now - last_print_time >= 1.0:
                parts = [ch.get_report_str() for ch in self.channels]
                print("  ".join(parts))
                for ch in self.channels:
                    if ch.height_buffer:
                        ch.height_buffer.clear()
                last_print_time = now

            if self.headless or self._gui_failed:
                # waitKey 兼做帧节流 + GUI 事件泵; headless 下用 sleep 替代, 防空转占满 CPU
                time.sleep(0.03)
            else:
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif ord('1') <= key <= ord('8'):
                    ch_idx = key - ord('1')
                    if ch_idx < self.num_channels:
                        self._reload_channel_config(ch_idx)

        # 安全清理
        if self.mjpeg_streamer:
            self.mjpeg_streamer.shutdown()
        if self.mqtt:
            self.mqtt.disconnect()
        for ch in self.channels:
            ch.running = False
        time.sleep(0.5)
        for ch in self.channels:
            if ch.cap:
                try:
                    ch.cap.release()
                except Exception:
                    pass
                time.sleep(0.1)
        cv2.destroyAllWindows()
        cv2.waitKey(1)
        print("程序结束")


# ====================================================================
# 入口
# ====================================================================
def main():
    parser = argparse.ArgumentParser(
        description="TCL液位检测 — 多路版本 + MQTT + 检测参数命令化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
用法示例:
  python water_level_8ch_mqtt.py --tl_bl_cm 15.0 --cameras /dev/camera1,/dev/camera2 --broker 192.168.10.226
  python water_level_8ch_mqtt.py --tl_bl_cm 15.0 --cameras /dev/camera1 --width 640 --height 480 --broker 192.168.10.226
  python water_level_8ch_mqtt.py --tl_bl_cm 15.0 --cameras /dev/camera1 --no-mqtt

检测参数命令 (mosquitto_pub 示例):
  # 降低液位边缘阈值
  mosquitto_pub -h IP -t water_level/cmd/set_detect_param \\
    -m '{"channel":1,"params":{"water_edge_threshold":5.0}}'

  # 查询CH1参数
  mosquitto_pub -h IP -t water_level/cmd/get_detect_param -m '{"channel":1}'

  # 保存全部通道参数
  mosquitto_pub -h IP -t water_level/cmd/save_detect_param -m '{"channel":"all"}'
        """
    )
    parser.add_argument("--tl_bl_cm", type=float, required=True,
                        help="二维码TL到BL的实际距离(cm)")
    parser.add_argument("--cameras", type=str, required=True,
                        help="摄像头设备路径, 逗号分隔")
    parser.add_argument("--width", type=int, default=1280,
                        help="摄像头采集宽度 (默认 1280; 720p 保证 4 路/USB2.0总线 不撞 400M 等时带宽)")
    parser.add_argument("--height", type=int, default=720,
                        help="摄像头采集高度 (默认 720)")
    parser.add_argument("--fps", type=int, default=30,
                        help="采集帧率 (默认 30; 液位慢过程可降 10/5 以减 USB 等时预留带宽)")
    parser.add_argument("--broker", type=str, default=None,
                        help="MQTT Broker IP")
    parser.add_argument("--port", type=int, default=1883,
                        help="MQTT Broker 端口 (默认 1883)")
    parser.add_argument("--mjpeg_port", type=int, default=7070,
                        help="MJPEG HTTP 服务端口 (默认 7070)")
    parser.add_argument("--mjpeg_max_active", type=int, default=None,
                        help="MJPEG 最大并发流数 (默认=通道数)")
    parser.add_argument("--calibrate", action="store_true",
                        help="标定模式：QR检测并自动保存校准到配置文件。"
                             "正常模式无需此参数（QR不在画面中）。")
    parser.add_argument("--no-mqtt", action="store_true",
                        help="禁用MQTT")
    parser.add_argument("--no-detect", action="store_true",
                        help="禁用本机液位检测, CAPTURE 通道只抓帧供上位机拉帧检测 "
                             "(检测已搬到上位机; 省香橙派算力, 8 路不再卡)")
    parser.add_argument("--headless", action="store_true",
                        help="无显示环境 (SSH/nohup 启动): 跳过 cv2.imshow 本地预览窗口, "
                             "否则无 DISPLAY 时 imshow 抛错崩溃。默认按 DISPLAY 自动探测。")
    parser.add_argument("--exposure", type=int, default=312,
                        help="手动曝光值 v4l2 exposure_time_absolute (1~10000, 单位100us; "
                             "默认312=设备出厂值, 柜内正常照明下实测均亮约165)。"
                             "自动曝光会让上位机差分检测整块误判, 故一律锁死。")
    parser.add_argument("--awb_temp", type=int, default=4600,
                        help="手动白平衡色温 v4l2 white_balance_temperature (2800~6500; "
                             "默认4600=设备出厂值)。自动白平衡同样会改灰度, 一并锁死。")

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    cam_list = [x.strip() for x in args.cameras.split(",")]
    if len(cam_list) > 8:
        print("最多支持8路，多余的将被忽略")
        cam_list = cam_list[:8]

    enable_mqtt = not args.no_mqtt
    if enable_mqtt and not args.broker:
        print("[WARN] 未指定 --broker, MQTT不启用. 加 --broker IP 启用.")
        enable_mqtt = False

    # headless: 显式 --headless, 或 Linux 下无 DISPLAY (典型 SSH/nohup 启动场景)
    headless = args.headless or (sys.platform.startswith("linux") and not os.environ.get("DISPLAY"))
    if headless:
        print("[GUI] headless 模式: 跳过本地预览窗口 (cv2.imshow)")

    mgr = MultiChannelManager(
        cam_list, args.tl_bl_cm,
        cap_width=args.width, cap_height=args.height, cap_fps=args.fps,
        broker_ip=args.broker, broker_port=args.port,
        enable_mqtt=enable_mqtt,
        mjpeg_port=args.mjpeg_port,
        mjpeg_max_active=args.mjpeg_max_active,
        calibrate_mode=args.calibrate,
        detect_enabled=not args.no_detect,
        headless=headless,
        exposure_time=args.exposure, awb_temp=args.awb_temp,
    )
    mgr.run()


if __name__ == "__main__":
    main()