"""香橙派液位检测 MQTT 驱动
===========================
功能:
    液位检测模块 (运行在香橙派) 的 MQTT 通信驱动. 单连接 / 自动重连 / 回调机制,
    运行在 asyncio 事件循环, 经 paho-mqtt 后台线程 + call_soon_threadsafe 桥接.
    迁移自 UI-Upper/core/water_level_client.py (纯传输, 业务聚合在 controller 层).

职责:
    - 订阅上行主题: water_level/data, /status, /alarm, /param/detect, /ack
    - 暴露 async send_command(cmd, payload) 统一下发接口
    - 提供 on_data/on_status/on_alarm/on_param/on_ack 回调注册
    - 感知香橙派 LWT (online/offline)
"""

import asyncio
import atexit
import json
import logging
import threading
import time
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

log = logging.getLogger(__name__)

# 全局列表: 供 atexit 回调做最后清理 (进程退出前 force_cleanup)
_instances: list = []

# MQTT 主题常量 (与下位机 water_level_8ch_compress_mqtt.py 一致)
TOPIC_DATA_ALL = "water_level/data"
TOPIC_STATUS = "water_level/status"
TOPIC_ALARM = "water_level/alarm"
TOPIC_PARAM = "water_level/param/detect"
TOPIC_ACK = "water_level/ack"
TOPIC_CH_DATA = "water_level/ch/+/data"

CMD_PREFIX = "water_level/cmd/"

Callback = Callable[..., Any]


class WaterLevelClient:
    """液位检测 MQTT 客户端 (asyncio 集成)."""

    # 下行命令 -> topic 映射
    CMD_TOPICS = {
        "reset": "water_level/cmd/reset",
        "set_interval": "water_level/cmd/set_interval",
        "set_threshold": "water_level/cmd/set_threshold",
        "query_status": "water_level/cmd/query_status",
        "restart_camera": "water_level/cmd/restart_camera",
        "set_detect_param": "water_level/cmd/set_detect_param",
        "get_detect_param": "water_level/cmd/get_detect_param",
        "save_detect_param": "water_level/cmd/save_detect_param",
        "load_detect_param": "water_level/cmd/load_detect_param",
        "stream_start": "water_level/cmd/stream_start",
        "stream_stop": "water_level/cmd/stream_stop",
        "diag_camera": "water_level/cmd/diag_camera",
        "set_active_channels": "water_level/cmd/set_active_channels",
        "set_roi": "water_level/cmd/set_roi",
        "clear_roi": "water_level/cmd/clear_roi",
        "save_calibration": "water_level/cmd/save_calibration",
        "reload_config": "water_level/cmd/reload_config",
        "factory_reset": "water_level/cmd/factory_reset",
        "start_calibrate": "water_level/cmd/start_calibrate",
        "stop_calibrate": "water_level/cmd/stop_calibrate",
        "set_calibration": "water_level/cmd/set_calibration",
        "get_calibration": "water_level/cmd/get_calibration",
        "capture_reference": "water_level/cmd/capture_reference",
    }

    def __init__(self, broker_ip: str, broker_port: int = 1883, client_id: str | None = None):
        if not MQTT_AVAILABLE:
            raise ImportError("paho-mqtt 未安装, 无法使用 WaterLevelClient")
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.client_id = client_id or f"upper_wl_{id(self):x}"
        self.connected = False
        self.device_online = False     # 香橙派 LWT 状态
        self._force_cleaned = False
        # 回调注册表
        self._on_data: list[Callback] = []
        self._on_status: list[Callback] = []
        self._on_alarm: list[Callback] = []
        self._on_param: list[Callback] = []
        self._on_ack: list[Callback] = []
        self._on_device_state_change: list[Callback] = []
        self._client: "mqtt.Client | None" = None
        self._loop = None
        _instances.append(self)
        atexit.register(self._atexit_cleanup)

    # ---- 回调注册 ----
    def on_data(self, cb: Callback):
        """注册全通道数据回调: cb(channel_data_list)."""
        self._on_data.append(cb)

    def on_status(self, cb: Callback):
        """注册设备状态回调: cb(status_dict)."""
        self._on_status.append(cb)

    def on_alarm(self, cb: Callback):
        """注册报警回调: cb(alarm_dict)."""
        self._on_alarm.append(cb)

    def on_param(self, cb: Callback):
        """注册检测参数回调: cb(param_dict)."""
        self._on_param.append(cb)

    def on_ack(self, cb: Callback):
        """注册命令确认回调: cb(ack_dict)."""
        self._on_ack.append(cb)

    def on_device_state_change(self, cb: Callback):
        """注册设备上下线回调: cb(online: bool)."""
        self._on_device_state_change.append(cb)

    def remove_on_data(self, cb: Callback):
        if cb in self._on_data:
            self._on_data.remove(cb)

    def remove_on_ack(self, cb: Callback):
        if cb in self._on_ack:
            self._on_ack.remove(cb)

    # ---- 事件分发 (paho 线程 -> asyncio) ----
    def _dispatch(self, callbacks: list[Callback], *args):
        """安全分发回调 (在 paho 线程中调用, 转发到 asyncio 事件循环)."""
        if not callbacks:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            for cb in callbacks:
                try:
                    cb(*args)
                except Exception:
                    log.exception("回调异常: %s", cb)
            return
        for cb in callbacks:
            loop.call_soon_threadsafe(lambda c=cb, a=args: self._safe_call(c, *a))

    @staticmethod
    def _safe_call(cb, *args):
        try:
            cb(*args)
        except Exception:
            log.exception("回调异常: %s", cb)

    # ---- paho 回调 ----
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.connected = True
            log.info("[WL] MQTT 已连接 %s:%s", self.broker_ip, self.broker_port)
            topics = [
                (TOPIC_DATA_ALL, 0), (TOPIC_STATUS, 0), (TOPIC_ALARM, 1),
                (TOPIC_PARAM, 0), (TOPIC_ACK, 1), (TOPIC_CH_DATA, 0),
            ]
            client.subscribe(topics)
            log.info("[WL] 已订阅 %d 个上行主题", len(topics))
        else:
            log.warning("[WL] MQTT 连接失败 rc=%s", rc)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self.connected = False
        if rc != 0:
            log.warning("[WL] MQTT 意外断开 rc=%s", rc)
        # 香橙派 LWT: 断开后如 device_online 仍 True, 标记 offline
        if self.device_online:
            self.device_online = False
            self._dispatch(self._on_device_state_change, False)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        topic = msg.topic
        if topic == TOPIC_DATA_ALL:
            self._dispatch(self._on_data, payload.get("channels", []))
        elif topic == TOPIC_STATUS:
            status = payload.get("status", "")
            was_online = self.device_online
            self.device_online = (status == "online")
            if was_online != self.device_online:
                self._dispatch(self._on_device_state_change, self.device_online)
            self._dispatch(self._on_status, payload)
        elif topic == TOPIC_ALARM:
            self._dispatch(self._on_alarm, payload)
        elif topic == TOPIC_PARAM:
            self._dispatch(self._on_param, payload)
        elif topic == TOPIC_ACK:
            self._dispatch(self._on_ack, payload)
        elif topic.startswith("water_level/ch/") and topic.endswith("/data"):
            self._dispatch(self._on_data, [payload])

    # ---- 连接管理 ----
    async def connect(self) -> bool:
        """异步连接 MQTT Broker; 返回是否发起成功."""
        self._loop = asyncio.get_running_loop()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        # LWT: 上位机离线时发布
        self._client.will_set(
            "water_level/upper/status",
            json.dumps({"status": "offline", "client_id": self.client_id, "timestamp": time.time()}),
            qos=1, retain=True,
        )
        try:
            self._client.connect(self.broker_ip, self.broker_port, keepalive=60)
        except Exception as exc:
            log.error("[WL] MQTT 连接失败: %s", exc)
            return False
        self._client.loop_start()
        self._client.publish(
            "water_level/upper/status",
            json.dumps({"status": "online", "client_id": self.client_id, "timestamp": time.time()}),
            qos=1, retain=True,
        )
        log.info("[WL] WaterLevelClient 已启动")
        return True

    async def disconnect(self) -> None:
        """断开 MQTT 连接 (带超时保护, 防止 paho loop_stop 阻塞)."""
        if self._client:
            try:
                self._client.publish(
                    "water_level/upper/status",
                    json.dumps({"status": "offline", "client_id": self.client_id, "timestamp": time.time()}),
                    qos=1, retain=True,
                )
            except Exception:
                pass
            loop_stop_done = await asyncio.get_running_loop().run_in_executor(None, self._timed_loop_stop, 2.0)
            if not loop_stop_done:
                log.warning("[WL] loop_stop 超时(2s), 强制跳过")
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self.connected = False
        log.info("[WL] WaterLevelClient 已断开")

    def _timed_loop_stop(self, timeout: float) -> bool:
        """在独立线程中调用 loop_stop, 超时返回 False."""
        if not self._client:
            return True
        done_event = threading.Event()

        def _stop():
            try:
                self._client.loop_stop()
            except Exception:
                pass
            finally:
                done_event.set()

        threading.Thread(target=_stop, daemon=True).start()
        return done_event.wait(timeout)

    def force_cleanup(self) -> None:
        """同步强制清理 (在 os._exit 前调用), 幂等可重复."""
        if self._force_cleaned:
            return
        self._force_cleaned = True
        client = self._client
        if client is None:
            return
        log.info("[WL] force_cleanup: 强制关闭 paho 客户端")
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass
        try:
            if hasattr(client, "_sock") and client._sock:
                client._sock.close()
        except Exception:
            pass
        self._client = None
        self.connected = False

    def _atexit_cleanup(self) -> None:
        self.force_cleanup()

    # ---- 命令发送 ----
    async def send_command(self, cmd: str, payload: dict | None = None) -> bool:
        """发送下行控制指令.

        参数:
            cmd: 命令名 (如 stream_start, set_detect_param); payload: 命令参数 dict
        返回:
            True 发送成功, False 未连接或发送失败
        """
        # 发命令的真实前提是 *broker 连接* (connected), 与香橙派是否在线 (device_online) 无关:
        # 历史上这里用 is_connected = connected AND device_online 作门, 香橙派离线时打出误导性的
        # "未连接", 把排查带向 broker。现仅按 broker 连接门控; 设备离线时仍发布 (QoS1 + 周期重发兜底)。
        if not self.connected or not self._client:
            log.warning("[WL] broker 未连接(connected=%s), 无法发送命令: %s", self.connected, cmd)
            return False
        if not self.device_online:
            log.debug("[WL] 香橙派当前离线, 仍发布 %s (待设备上线由周期重发生效)", cmd)
        topic = self.CMD_TOPICS.get(cmd)
        if topic is None:
            log.error("[WL] 未知命令: %s", cmd)
            return False
        data = json.dumps(payload or {}, ensure_ascii=False)
        try:
            result = self._client.publish(topic, data, qos=1)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                log.debug("[WL TX] %s -> %s", cmd, data)
                return True
            log.warning("[WL TX] %s 发送失败 rc=%s", cmd, result.rc)
            return False
        except Exception as exc:
            log.error("[WL TX] %s 异常: %s", cmd, exc)
            return False

    @property
    def is_connected(self) -> bool:
        """上位机到 broker 的 MQTT 连接是否建立 (与香橙派是否在线无关)。"""
        return self.connected

    @property
    def is_broker_connected(self) -> bool:
        """is_connected 的语义别名: broker 连接已建立。"""
        return self.connected

    @property
    def is_device_online(self) -> bool:
        """香橙派设备是否在线 (经其 MQTT LWT water_level/status 判定)。"""
        return self.device_online
