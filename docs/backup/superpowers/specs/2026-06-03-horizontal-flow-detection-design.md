# Horizontal Flow Water Level Detection — Design Spec

**Date**: 2026-06-03
**Status**: draft
**Scope**: `液位检测模块/work/water_level_8ch_compress_mqtt.py`

## 1. Problem Statement

当前液位检测算法假设液面从下往上（垂直方向）推进，使用 Sobel Y 检测水平边缘 + 逐行投影 + `reference_y` 作为基准。

实际物理布置：摄像头俯拍水平放置的展缸，TLC 板平放，毛细作用驱动液面沿**水平方向**推进。展开组 1（通道 1-4）液流从右向左，展开组 2（通道 5-8）液流从左向右。

旧假设导致检测到的"液面"实际上是噪声或错误特征，测量结果不可靠。

## 2. Design Decision

采用**方案 B：参数化检测方向**。新增 `flow_direction` 检测参数，三种取值：

| flow_direction | 液面方向 | 梯度检测 | 投影轴 | 参考边 |
|---|---|---|---|---|
| `"bottom_to_top"` (旧) | 水平线 | Sobel Y | axis=1 (逐行) | `reference_y` (ROI 顶部) |
| `"left_to_right"` (新) | 垂直线 | Sobel X | axis=0 (逐列) | `reference_x` = ROI 左边缘 |
| `"right_to_left"` (新) | 垂直线 | Sobel X | axis=0 (逐列) | `reference_x` = ROI 右边缘 |

通道初始化时根据 `channel_id` 自动设定：
- `channel_id` ∈ {1,2,3,4} → `"right_to_left"`
- `channel_id` ∈ {5,6,7,8} → `"left_to_right"`

可通过 MQTT `set_detect_param` 动态修改，通过 `save_detect_param` 持久化到 `water_level_config.json`。

## 3. Core Algorithm Changes

### 3.1 `detect_water_level()` — default mode

在 rotated ROI 上，根据 `flow_direction` 选择 Sobel 轴和投影方向：

```
if direction == "bottom_to_top":
    grad = |Sobel(gray, 0, 1)|     # Sobel Y → horizontal edges
    profile = mean(grad, axis=1)    # row-wise
    idx → wl_y
    h_cm = (wl_y - reference_y) × scale
else:
    grad = |Sobel(gray, 1, 0)|     # Sobel X → vertical edges
    profile = mean(grad, axis=0)    # column-wise
    idx → wl_x
    if direction == "left_to_right":
        h_cm = (wl_x - reference_x) × scale    # reference_x = ROI left
    else:  # right_to_left
        h_cm = (reference_x - wl_x) × scale    # reference_x = ROI right
```

平滑 (`np.convolve`) 和 `argmax` + `water_edge_threshold` 阈值逻辑不变。

### 3.2 `detect_water_level_directional()` — directional mode

方向梯度法同理切换。当前计算梯度沿 QR 上边法向（适用于垂直流液面），水平流需改为沿 QR 上边切向：

```
垂直流 (bottom_to_top):
    G_perp = |-Gx·sin(θ) + Gy·cos(θ)|    # QR 上边法向 = 液面前沿法向
    row_int = mean(G_perp, axis=1)        # 逐行 → argmax → wl_y

水平流 (left_to_right / right_to_left):
    G_parallel = |Gx·cos(θ) + Gy·sin(θ)|  # QR 上边切向 = 液面前沿法向
    row_int = mean(G_parallel, axis=0)     # 逐列 → argmax → wl_x
```

角度滑动平均 (`_angle_history`) 和大角度微小旋转校正逻辑同样从 G_perp 切换到 G_parallel。

### 3.3 `reference_x` automatic derivation

在 `process_frame()` 中，ROI 确定后自动计算：

```python
if self.roi_bbox is not None:
    rx, ry, rw, rh = self.roi_bbox
    direction = self.detect_params["flow_direction"]
    if direction == "left_to_right":
        self.reference_x = float(rx)
    elif direction == "right_to_left":
        self.reference_x = float(rx + rw)
    # bottom_to_top: reference_x not used (keeps reference_y semantics)
```

## 4. Visualization Changes (`_draw_overlay()`)

根据 `flow_direction` 选择绘制水平线还是垂直线：

| flow_direction | 参考线 (蓝) | 液面线 (红) |
|---|---|---|
| `bottom_to_top` | 水平线 `y = reference_y` | 水平线 `y = wl_y` |
| 其他 | 垂直线 `x = reference_x` | 垂直线 `x = wl_x` |

叠加文字增加方向指示箭头（↑/→/←）。

## 5. Configuration

### 5.1 New parameter

```python
DEFAULT_DETECT_PARAMS["flow_direction"] = "left_to_right"

PARAM_VALIDATORS["flow_direction"] = lambda v: v in (
    "bottom_to_top", "left_to_right", "right_to_left"
)

PARAM_HINTS["flow_direction"] = "bottom_to_top, left_to_right, right_to_left"
```

### 5.2 Auto-initialization per channel

```python
# In ChannelDetector.__init__(), after detect_params = dict(DEFAULT_DETECT_PARAMS):
if self.channel_id <= 4:
    self.detect_params["flow_direction"] = "right_to_left"
else:
    self.detect_params["flow_direction"] = "left_to_right"
```

### 5.3 Persistence

现有 `_save_config_to_file()` / `_load_config_from_file()` 无需改动——`detect_params` 字典整体序列化/反序列化，`flow_direction` 自动跟随。

## 6. MQTT Protocol

- **字段名不变**：`height_cm` 保持，物理含义从"垂直高度"变为"液面行进距离"
- **set_detect_param 支持 flow_direction**：上位机可通过 MQTT 下发修改
  ```json
  {"channel": 1, "params": {"flow_direction": "right_to_left"}}
  ```
- 上位机 `water_level_client.py` **无需任何改动**

## 7. Backward Compatibility

- 旧 `water_level_config.json` 文件不含 `flow_direction` 字段时，`_load_config_from_file()` 从 `DEFAULT_DETECT_PARAMS` 取值，然后被 `ChannelDetector.__init__()` 中的自动设定覆盖——确保旧配置文件迁移后通道 1-4 仍然正确设为右→左
- 手动通过 MQTT `set_detect_param` 覆盖的 `flow_direction` 会被 `save_detect_param` 持久化，后续启动时从配置文件加载，**不会被** `__init__` 中的自动设定覆盖

## 8. Files Changed

| File | Scope |
|------|-------|
| `液位检测模块/work/water_level_8ch_compress_mqtt.py` | 唯一改动文件，约 +70/−15 行 |

上位机所有文件不变。

## 9. Test Plan

### 9.1 离线单元验证

- 使用已采集的展缸图片（包含可见液面），分别以 `left_to_right` 和 `right_to_left` 模式运行 `detect_water_level()`
- 验证液面位置（垂直线 x 坐标）在连续帧中沿正确方向推进
- 验证 `h_cm` 单调递增

### 9.2 实机联调

1. 部署到香橙派，启动 8 路摄像头
2. 发起一次展开实验，通过 MJPEG 流观察每路的红色液面线是否正确跟踪
3. 通过 `mosquitto_sub -t water_level/data` 观察上报的 `height_cm` 是否随展开推进而增大
4. 验证通道 1-4 和 5-8 的方向正确（液面线从正确的一侧开始推进）

### 9.3 回归

- `bottom_to_top` 模式保持可用（通过 MQTT 切换验证）
- MQTT 指令 `set_detect_param` / `get_detect_param` / `save_detect_param` 对 `flow_direction` 生效
- 配置文件读写不丢字段
