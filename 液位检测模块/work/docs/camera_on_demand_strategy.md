# 摄像头按需启停策略

## 1. 设计原则

- **决策权在上位机**：上位机掌握展缸资源状态（IDLE / PREPPING / DEVELOPING / DRAINING / ERROR），香橙派只做执行器
- **香橙派不做自主决策**：不自行判断"空闲 N 分钟自动关"等逻辑，一切启停由上位机指令驱动
- **硬暂停（cap.release()）**：要省 USB 带宽必须释放设备，但仅在上位机明确指令时执行
- **标定参数与采集状态解耦**：暂停后保留 calibrated / roi_bbox / rotation_* / scale_factor，恢复时无需重新标定（前提是相机物理位置未变）

## 2. 通道与展缸映射

**channel_id ≡ tank_id**，严格 1:1。

```
/dev/camera1  ←→  CH1  ←→  Tank 1
/dev/camera2  ←→  CH2  ←→  Tank 2
...
/dev/camera8  ←→  CH8  ←→  Tank 8
```

映射由 `run.bash` 中 `--cameras` 参数顺序保证。启动时打印映射表确认：

```
[MAPPING] CH1(/dev/camera11) → Tank 1
[MAPPING] CH2(/dev/camera12) → Tank 2
...
```

## 3. 通道状态机

```
                    ┌─────────┐
           ┌───────│  IDLE   │◄──────────────────┐
           │       └────┬────┘                    │
           │            │ activate_capture()      │ deactivate()
           │            ▼                         │
           │       ┌─────────┐                    │
           │       │ CAPTURE │──────────────────►│
           │       └────┬────┘                    │
           │            │ activate_stream()       │
           │            ▼                         │
           │       ┌──────────────┐               │
           │       │ CAPTURE+     │──────────────►│
           │       │ STREAM       │deactivate_stream()
           │       └──────────────┘               │
           │                                      │
           └── 启动失败 / 运行时异常 → ERROR ────►│（保留标定，等待恢复指令）
```

| 状态 | cv2.VideoCapture | 液位检测 | MQTT 上报 | MJPEG HTTP |
|------|:---:|:---:|:---:|:---:|
| IDLE | 关闭 | ❌ | ❌ | ❌ |
| CAPTURE | 运行中 | ✅ | ✅ | ❌ |
| CAPTURE+STREAM | 运行中 | ✅ | ✅ | ✅ |
| ERROR | 关闭 | ❌ | 告警上报 | ❌ |

关键行为：
- **IDLE → CAPTURE**：`cv2.VideoCapture.open()` + `_capture_loop` 启动，**保留已有标定参数**
- **CAPTURE → IDLE**：`cap.release()`，保留标定参数
- **CAPTURE → CAPTURE+STREAM**：MJPEG 端点激活（已有实现）
- **任意状态 → ERROR**：记录错误原因，通过 `water_level/status` 上报，等待上位机 `restart_camera` 恢复

## 4. MQTT 协议

### 4.1 新增下行命令

```
Topic: water_level/cmd/set_active_channels
QoS: 1
Payload: {
    "channels": [1, 3, 5],        // 需要 CAPTURE 的通道列表
    "stream_channels": [3]        // 额外需要 MJPEG 流的通道（⊆ channels）
}
```

香橙派处理逻辑：

```python
def handle_set_active_channels(payload):
    target_capture = set(payload.get("channels", []))
    target_stream = set(payload.get("stream_channels", []))

    for ch_id in range(1, 9):
        ch = get_channel(ch_id)
        want_capture = ch_id in target_capture
        want_stream = ch_id in target_stream
        is_capturing = ch.state in (STATE_CAPTURE, STATE_STREAM)
        is_streaming = ch.state == STATE_STREAM

        if want_capture and not is_capturing:
            ch.activate_capture()       # IDLE → CAPTURE
        elif not want_capture and is_capturing:
            ch.deactivate()             # CAPTURE → IDLE

        if want_stream and is_capturing and not is_streaming:
            ch.activate_stream()        # CAPTURE → CAPTURE+STREAM
        elif not want_stream and is_streaming:
            ch.deactivate_stream()      # CAPTURE+STREAM → CAPTURE

    # 发布确认
    mqtt.publish_ack("set_active_channels", "ok", extra={
        "active": list(target_capture),
        "streaming": list(target_stream),
    })
```

### 4.2 上行反馈

`water_level/status` 的 extra 字段增加通道状态摘要：

```json
{
    "status": "online",
    "channels_summary": {
        "1": "capture",
        "2": "idle",
        "3": "stream",
        ...
    }
}
```

### 4.3 周期性同步（防丢包）

上位机每 30s 重发一次 `set_active_channels`，payload 与上次一致。幂等操作，无副作用。

## 5. 各场景触发逻辑

### 场景 A：调试预览（眼图标）

- **触发**：用户在 Debug Tab 点击某通道的眼图标 → 打开 TankVisionDialog
- **上位机动作**：
  1. 发 `stream_start`（已有）
  2. 如果该通道当前不在活跃列表中，将 `stream_channels` 加入该通道，重发 `set_active_channels`
- **关闭 dialog 时**：发 `stream_stop`（已有），如果该通道不是展缸占用状态，从活跃列表中移除

### 场景 B：展缸占用（核心场景）

- **触发**：`ResourceManager.allocate()` 分配展缸 → 缸状态 IDLE→PREPPING
- **上位机动作**：重新计算活跃通道集合并下发
- **释放**：`ResourceManager.release()` 释放展缸 → 缸状态 DONE→IDLE
- **释放延迟**：release 后延迟 30s 再移除通道（给可能的后续操作留窗口）

```python
# ResourceManager 中新增
async def _sync_active_channels(self):
    """计算当前需要监控的通道集合并下发到香橙派"""
    active = []
    for tank_id, info in self._tanks.items():
        if info.state not in (TankStatus.IDLE, TankStatus.DONE):
            active.append(tank_id)
        # ERROR 状态的缸也需要监控（诊断用途）
        if info.state == TankStatus.ERROR:
            active.append(tank_id)

    # 通过 WaterLevelClient 下发
    await self._wl_client.send_command("set_active_channels", {
        "channels": list(set(active)),
        "stream_channels": self._get_stream_channels(),  # 来自 UI 的 stream 请求
    })
```

在 `allocate()` 和 `release()` 末尾调用 `_sync_active_channels()`。

### 场景 C：异常诊断

- **触发**：`_sync_states_locked()` 检测到 PLC 侧 Tank_State=90（ERROR）
- **动作**：保持该通道在活跃列表中（即使不在正常占用列表）
- **恢复**：ERROR 清除后（手动释放或 PLC 复位），按正常逻辑处理

### 场景 D：系统启动

1. 香橙派启动：**静默启动，全通道 IDLE**，不打开任何摄像头
2. 香橙派连接 MQTT → 发布 `water_level/status`（全通道 IDLE）
3. 上位机收到 status → 根据 RM 状态计算活跃通道 → 下发 `set_active_channels`
4. 香橙派收到后：激活指定通道 (IDLE → CAPTURE)，开始液位检测

> **设计变更 (2026-06-04)**：原方案为"全通道 CAPTURE 后上位机关闭"，已改为"静默启动全 IDLE 等待上位机激活"。
> 详见 `docs/superpowers/specs/2026-06-04-silent-start-design.md`。
> 标定模式 (`--calibrate`) 保持全部启动行为不变。

### 场景 E：全局空闲

- 上位机检测到所有缸 IDLE > N 分钟（通过 `idle_tanks()` == [1..8]）
- 下发 `"channels": []` → 香橙派全部 deactivate
- 下一个 `allocate()` 触发时重新激活对应通道

## 6. ChannelDetector 改动

```python
class ChannelDetector:
    STATE_IDLE = "idle"
    STATE_CAPTURE = "capture"
    STATE_STREAM = "stream"
    STATE_ERROR = "error"

    def __init__(self, ...):
        ...
        self.state = self.STATE_IDLE
        self._state_lock = threading.Lock()

    def activate_capture(self):
        """IDLE → CAPTURE: 启动采集，保留标定"""
        with self._state_lock:
            if self.state != self.STATE_IDLE:
                return
            success = self.start_capture()
            if success:
                self.state = self.STATE_CAPTURE
                print(f"[CH{self.channel_id}] 摄像头激活 (标定保留: {self.calibrated})")
            else:
                self.state = self.STATE_ERROR
                print(f"[CH{self.channel_id}] 摄像头激活失败!")

    def deactivate(self):
        """CAPTURE/STREAM → IDLE: 停止采集，保留标定参数"""
        with self._state_lock:
            self.running = False
            if self.cap:
                self.cap.release()
                self.cap = None
            self.state = self.STATE_IDLE
            # calibrated / roi_bbox / rotation_* / scale_factor 全部保留

    def activate_stream(self):
        """CAPTURE → STREAM"""
        with self._state_lock:
            if self.state == self.STATE_CAPTURE:
                self.state = self.STATE_STREAM

    def deactivate_stream(self):
        """STREAM → CAPTURE"""
        with self._state_lock:
            if self.state == self.STATE_STREAM:
                self.state = self.STATE_CAPTURE

    def resume_with_verify(self):
        """恢复采集后验证标定是否仍然有效"""
        self.activate_capture()
        if self.state != self.STATE_CAPTURE:
            return
        # 等待几帧后验证 QR
        time.sleep(0.5)
        frame = self.get_frame()
        if frame is not None:
            # 用当前标定参数验证 QR 是否仍在原位
            recheck = self._recheck_calibration(frame)
            if not recheck:
                print(f"[CH{self.channel_id}] 标定失效, 自动重置")
                self.reset()
```

## 7. 上位机 WaterLevelClient 扩展

```python
# core/water_level_client.py CMD_TOPICS 新增
"set_active_channels":  "water_level/cmd/set_active_channels",
```

## 8. 上位机 AppState 新增字段

```python
# ui/state.py
water_level_active_channels: set = field(default_factory=set)   # 当前活跃的通道集合
water_level_stream_channels: set = field(default_factory=set)   # 当前 MJPEG 流通道
water_level_max_active: int = 4                                 # 最大并发 CAPTURE 通道数
```

## 9. 边界条件处理

| 情况 | 处理 |
|------|------|
| MQTT 命令丢失 | 上位机每 30s 重发，幂等 |
| 摄像头启动延迟（~300ms） | CAPTURE 启动期间液位数据缺失，上位机已容忍 `height_cm: None` |
| 摄像头启动失败 | `water_level/ack` 返回 error + reason；Debug Tab 显示告警 |
| 标定失效（resume 后相机被移动） | `resume_with_verify()` 中做 QR 重检测，偏差超阈值自动 reset |
| 多样品并发 > USB 带宽 | `water_level_max_active` 限制最大并发；超限时排队或降分辨率 |
| 上位机未连接（香橙派孤立） | 香橙派静默启动全 IDLE，持续等待上位机连接后下发指令 |

## 10. 实施分期

| 期数 | 内容 | 依赖 |
|------|------|------|
| **Phase 1** | MQTT `set_active_channels` 协议 + ChannelDetector 状态机 + 上位机 RM 集成（场景 B） | — |
| **Phase 2** | 调试预览集成（场景 A）+ 系统启动流程（场景 D）+ 周期性同步 | Phase 1 |
| **Phase 3** | 全局空闲节能（场景 E）+ 标定失效检测 + 启动失败告警 UI | Phase 2 |
