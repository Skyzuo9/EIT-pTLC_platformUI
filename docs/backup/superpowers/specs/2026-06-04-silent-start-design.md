# 液位检测模块：静默启动设计方案

Date: 2026-06-04 | Status: Approved

## 1. 背景

液位检测模块已实现以下能力：

- **上位机控制相机启停**：通过 `water_level/cmd/set_active_channels` 按需激活/停用通道
- **参考图差分检测 (P0)**：通过 `water_level/cmd/capture_reference` 拍摄干板参考图 I0，后续帧做 I - I0 差分增强鲁棒性
- **通道状态机**：`IDLE → CAPTURE → STREAM`，状态转换由上位机指令驱动

但 `MultiChannelManager.start()` 在正常模式下仍**无条件启动全部 8 路摄像头**，与"按需启停"的设计原则不一致。

## 2. 设计目标

将启动行为从"全部启动，等待上位机关闭"改为"静默启动，等待上位机激活"，实现**香橙派不做自主采集决策**的原则。

## 3. 核心原则

1. **决策权在上位机**：上位机的 `ResourceManager` 掌握展缸状态（IDLE/PREPPING/DEVELOPING/DRAINING/ERROR），香橙派只做执行器
2. **启动即就绪，不启动采集**：加载配置（标定/ROI/detect_params）、连接 MQTT、发布状态、等待指令
3. **参考图是运行时概念**：只在 CAPTURE 状态下按 `capture_reference` 指令捕获，不与启动耦合
4. **故障安全**：上位机离线时保持现有采集状态不变（不主动关闭相机），上位机重连后通过周期性同步恢复

## 4. 改动范围

**唯一改动**：`MultiChannelManager.start()` 正常模式分支。

| 文件 | 改动 |
|------|------|
| `water_level_8ch_compress_mqtt.py` | `start()` 正常模式：移除全部 `start_capture()` 调用 |
| `run.bash` | **不变** |
| MQTT 协议 | **不变** |
| `ChannelDetector` 状态机 | **不变** |
| 所有 MQTT command handler | **不变** |

## 5. 启动时序

```
上位机启动 (先)
  ├─ WaterLevelClient.connect()
  ├─ 订阅上行主题
  └─ 发布 water_level/upper/status: online

香橙派启动 (后)
  ├─ 解析 CLI 参数
  ├─ MultiChannelManager.__init__()
  │   ├─ 创建 8 个 ChannelDetector (全部 STATE_IDLE)
  │   ├─ 加载 water_level_config.json (标定/ROI/detect_params)
  │   └─ 注册 MQTT handlers
  ├─ start()
  │   ├─ --calibrate 模式: 全部 start_capture() (不变)
  │   └─ 正常模式: 不启动任何摄像头, 打印就绪信息
  ├─ MQTT 连接 → 发布 water_level/status (全通道 IDLE)
  └─ 主循环: IDLE 通道显示状态标签, 等待指令

上位机收到 status (channels_summary 全 IDLE)
  ├─ 根据 ResourceManager 当前状态计算活跃通道
  └─ 下发 set_active_channels {"channels": [...], "stream_channels": [...]}

香橙派收到 set_active_channels
  ├─ 激活指定通道: IDLE → CAPTURE (~1-2s)
  └─ 开始液位检测 + MQTT 上报

实验需要参考图
  ├─ 上位机确认干板状态
  ├─ 下发 capture_reference {"channel": N}
  └─ 香橙派下一帧捕获 ref_gray, 后续帧自动差分
```

## 6. 具体改动

`MultiChannelManager.start()` 中正常模式分支：

```python
def start(self):
    if self.calibrate_mode:
        # 标定模式：全部启动（需要 QR 检测）— 不变
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
```

## 7. 主循环对 IDLE 通道的处理

已实现，无需改动。当前 `run()` 中 IDLE/ERROR 通道显示状态标签：

```python
if ch.state in (ch.STATE_IDLE, ch.STATE_ERROR):
    cell = blank.copy()
    label = f"CH{ch.channel_id}: {ch.state.upper()}"
    ...
```

## 8. 边界条件

| 情况 | 行为 |
|------|------|
| 香橙派启动时上位机已在线 | 上位机收到 status → 立即下发 set_active_channels |
| 通道未标定但被激活 | `activate_capture()` 成功，`process_frame()` 显示 "Not calibrated"，液位=N/A |
| capture_reference 时通道 IDLE | `handle_capture_reference` 返回 error: "通道未在采集状态" |
| 上位机异常重启 | 香橙派保持现有采集状态不变，等待上位机重连后周期性同步 |
| 上位机重连 | 周期性 `set_active_channels` (30s 幂等) 恢复一致状态 |
| 上位机下发指令时相机启动失败 | 通道进入 ERROR 状态，通过 `water_level/status` 上报 |

## 9. 不变的部分

- **`run.bash`**：CLI 参数完全不变
- **MQTT 协议**：所有 topic 和 payload 格式不变
- **`--calibrate` 模式**：仍全部启动（QR 标定需要相机出图）
- **`capture_reference`**：前置条件不变（CAPTURE/STREAM + calibrated + ROI）
- **上位机 `WaterLevelClient`**：无需任何修改
- **`camera_on_demand_strategy.md`**：Scenario D 中"香橙派启动：全通道 CAPTURE"的描述被本设计取代，其余场景（A/B/C/E）不变

## 10. 与已有设计文档的关系

本设计取代 `液位检测模块/work/docs/camera_on_demand_strategy.md` 中 Scenario D 的启动行为描述，其余内容（场景 A/B/C/E、状态机、MQTT 协议、ResourceManager 集成）保持不变。
