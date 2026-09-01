"""液位控制器
============
功能:
    订阅香橙派液位 MQTT 驱动的回调, 维护各通道最新液位与设备在线状态的只读快照,
    供 SystemResourceView / UI / 展开完成判定使用.
    迁移自 UI-Upper/core/water_level_client 的业务聚合部分; MQTT 传输在 driver/orangepi_waterlevel.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class WaterLevelController:
    """液位状态聚合 (订阅驱动回调, 维护快照)."""

    def __init__(self, client: Any) -> None:
        """参数: client - 提供 on_data/on_device_state_change 回调注册的液位 MQTT 客户端."""
        self._client = client
        self._channels: dict[int, dict] = {}   # 通道号 -> 最新数据
        self._params: dict[int, dict] = {}      # 通道号 -> 最新检测参数 (get_detect_param 回报)
        self._online = False
        self._alarms: list[dict] = []
        client.on_data(self._on_data)
        client.on_device_state_change(self._on_state)
        if hasattr(client, "on_alarm"):
            client.on_alarm(self._on_alarm)
        if hasattr(client, "on_param"):
            client.on_param(self._on_param)

    def _on_data(self, channels: list) -> None:
        """消费全通道数据回调, 按通道号更新快照."""
        for ch in channels or []:
            key = ch.get("channel", ch.get("ch"))
            if key is not None:
                self._channels[int(key)] = ch

    def _on_state(self, online: bool) -> None:
        self._online = bool(online)
        log.info("[WL] 设备在线状态: %s", self._online)

    def _on_alarm(self, alarm: dict) -> None:
        self._alarms.append(alarm)

    def _on_param(self, payload: dict) -> None:
        """消费检测参数回报 (get_detect_param 触发), 按通道号缓存供控制台读取初值."""
        for ch in payload.get("channels", []) or []:
            key = ch.get("channel", ch.get("ch"))
            if key is not None:
                self._params[int(key)] = ch

    def snapshot(self) -> dict:
        """返回液位只读快照 (在线状态 + 各通道最新数据 + 最新检测参数)."""
        return {
            "online": self._online,
            "channels": {k: dict(v) for k, v in sorted(self._channels.items())},
            "params": {k: dict(v) for k, v in sorted(self._params.items())},
            "alarm_count": len(self._alarms),
        }

    def level_of(self, channel: int):
        """返回某通道最新液位值 (无数据返回 None)."""
        data = self._channels.get(channel)
        if data is None:
            return None
        return data.get("level", data.get("value"))
