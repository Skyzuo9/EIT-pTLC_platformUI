# 液位检测差分图调试可视化 + 参数面板重组 — 设计文档

**日期**: 2026-06-05 | **状态**: 已确认 | **分支**: parallel

## 背景

香橙派液位检测模块使用差分图（当前帧 - 干板参考图）+ Sobel 梯度 + 两区对比验证的方式检测溶剂前沿。当前上位机 TankVisionDialog 只能看到最终渲染帧（液位线 + ROI 框），调试时需要理解算法中间步骤的行为，以便高效调参。

此外，检测算法有 14 个可调参数，当前 UI 只暴露了 8 个，6 个前沿检测相关参数无法调整。需要在调试视图中同时暴露全部参数，实现"看 debug 视图 → 调参数 → 看效果"的闭环。

## 目标

1. 在 TankVisionDialog 中增加「调试视图」模式，实时展示差分检测管线的中间结果
2. 重组参数面板：新增 6 个前沿检测参数，低频参数移入可折叠"高级设置"区域
3. 删除废弃的独立"保存校准"按钮

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 可视化内容 | 差分图 + 两区对比 + 1D投影曲线(原始+平滑双线)，合为一张灰度图 | 足以定位绝大多数参数问题；双投影线可区分梯度丢失 vs 平滑丢失 |
| 传递方式 | MJPEG 流，新 URL 参数 `?debug=1` | 复用现有基础设施，实时性好 |
| 生成位置 | Orange Pi (OpenCV compositing) | 无需传输中间数组，CPU 开销可控 |
| 交互方式 | TankVisionDialog 加三态切换按钮（annotated/raw/debug），互斥 | 右侧调参 + 左侧看效果，单点调试最优体验 |
| 布局 | 纵向堆叠 (3-panel) | 信息密度适中，每个 panel 保持与 ROI 等宽 |
| 参数面板 | 5 分组，高级设置默认折叠 | 高频参数触手可及，低频参数不占空间 |
| 中间结果缓存 | `_debug_enabled` 开关控制，仅 debug 客户端连接时写入 | 无 debug 客户端时 process_frame() 零额外开销 |

## 架构

```
采集线程 ──frame──▶ 主循环 process_frame()
                        │
                        ├──▶ 检测管线 (detect_water_level / directional)
                        │      ├─ _prepare_gray_roi() → gray_roi_original
                        │      ├─ ref subtraction → gray_roi (diff)
                        │      ├─ Sobel → G_proj → profile → smoothed
                        │      ├─ peak detection → idx, contrast
                        │      └─ ★ 新增: 若 _debug_enabled，写入 _debug_* 缓存
                        │
                        ├──▶ _draw_overlay() → latest_rendered
                        │      → /stream/chN (现有)
                        │
                        └──▶ [无额外组合开销]

MJPEG HTTP 线程: 根据 URL 参数选择帧源
  ?raw=1   → detector.get_frame()
  ?debug=1 → detector.get_debug()   ★ 新增 (锁内引用快照→锁外构建→返回)
  (默认)   → detector.get_rendered()
```

## 调试帧布局 (build_debug_frame 输出)

单张 BGR numpy array，纵向排列 3 个 panel + 顶部参数栏：

```
┌──────────────────────────────────────────┐
│ CH3|mode=dir|→|thr=10.0 blur=5 sob=-1|TRACKING │ ← 参数栏 (绿字黑底, ~24px)
├──────────────────────────────────────────┤
│ Panel 1: 原始ROI + 两区对比               │ ← gray_roi_original
│  [wet_zone cyan框] |gap| |检测边红线|     │     叠加 wet/dry zone 矩形
│  |gap| [dry_zone yellow框]              │     标注 median + contrast 数值
│  wet=128.5  dry=145.2  contrast=16.7 ✓   │
├──────────────────────────────────────────┤  ← 1px 白色分隔线
│ Panel 2: 差分图 (当前 - 参考)             │ ← gray_roi (after diff)
│  clamp(I_curr - I_ref, 0, 255)           │     亮=有液体, 暗=无变化
│  无参考图时显示 "No Reference" 占位       │
├──────────────────────────────────────────┤  ← 1px 白色分隔线
│ Panel 3: 1D 投影曲线                     │ ← OpenCV 绘图 (白底)
│  原始梯度投影 (灰虚线)                    │     smoothed profile (蓝实线)
│  threshold 水平虚线 (橙)                  │     检测 peak 垂直线 (红) + 标记
│  P2 约束范围 [lo..hi]                    │     idx/val/flow 底部标注
└──────────────────────────────────────────┘
```

各 panel 宽度 = ROI 裁剪后宽度。
Panel 1/2 高度 = ROI 高度（保持原始比例）。
Panel 3 高度 = ROI 宽度的 65%（自适应宽高比）。

## 中间结果缓存

新增 `ChannelDetector` 实例属性：

```python
self._debug_enabled = False          # 开关：有 debug 客户端时为 True

self._debug_gray_original = None     # np.ndarray: 差分前 ROI 灰度 (Panel 1)
self._debug_gray_diff = None         # np.ndarray: 差分后 ROI 灰度 (Panel 2)
self._debug_profile = None           # np.ndarray: 原始梯度投影 (Panel 3 灰虚线)
self._debug_smoothed = None          # np.ndarray: 平滑后 profile (Panel 3 蓝实线)
self._debug_edge_idx = None          # int: 检测到的峰值索引
self._debug_edge_val = None          # float: 峰值梯度幅值
self._debug_wet_val = None           # float: wet_zone median
self._debug_dry_val = None           # float: dry_zone median
self._debug_contrast = None          # float: contrast 值
self._debug_contrast_ok = False      # bool: contrast >= threshold
self._debug_lo = None                # int: P2 约束下界
self._debug_hi = None                # int: P2 约束上界
self._debug_detect_ok = False        # bool: 检测成功 (h_cm 非 None)
self._debug_front_state = "WAITING"  # str: 前沿状态机状态

self._debug_lock = threading.Lock()
```

## 线程安全

- **写入方**：主循环 `process_frame()`，仅当 `_debug_enabled` 时持有 `_debug_lock` 写入 `_debug_*`
- **读取方**：MJPEG HTTP 线程 `get_debug()`，持有 `_debug_lock` 组装引用快照 dict (O(1))，释放锁后在外部调用 `_build_debug_frame(snapshots)` 生成组合图
- **生命周期**：`_debug_enabled` 由 MJPEG streamer 的 `_stream_channel(debug=True)` 管理，客户端连入时设为 True，断开时设为 False
- **内存安全**：numpy 数组引用计数保证快照在 MJPEG 线程使用期间不被回收

## MJPEG 流改动

`mjpeg_streamer.py`：

- 修正 URL 解析：从 `"raw=1" in query` 改为 `urllib.parse.parse_qs` 标准解析
- `_stream_channel()` 新增 `debug` 参数，帧源选择：debug > raw > rendered
- 管理 `detector._debug_enabled` 生命周期

```python
# 帧源选择
if debug:
    detector._debug_enabled = True
    frame_getter = lambda: detector.get_debug()
elif raw:
    frame_getter = lambda: detector.get_frame()
else:
    frame_getter = lambda: detector.get_rendered()
```

异常处理：`get_debug()` 返回错误信息图片而非 None。

## 上位机改动

`tank_vision_dialog.py`：

### 视图模式三态切换

`_raw_mode: bool` → `_view_mode: str` = `"annotated"` | `"raw"` | `"debug"`

- "原始/标注切换" → 在 annotated/raw 间切换
- "🔬 调试视图" → 在 annotated/debug 间切换（新增）
- 两按钮互斥高亮
- 标定进入 drawing 模式时临时切换到 raw，退出标定后恢复

### 参数面板重组

14 个参数，5 个分组：

```
液位边缘检测
  water_edge_threshold  [10.0] ──●──
  water_blur_ksize      [5 ▼]
  water_sobely_ksize    [-1 ▼]

前沿对比验证                          ← 新增
  front_contrast_threshold [15.0] ──●──
  front_zone_width         [20]   ──●──
  front_zone_gap           [3]    ──●──

流动方向                              ← 新增
  flow_direction    [left_to_right ▼]

▶ 高级设置                           ← 可折叠，默认折叠
  roi_crop_x           [0.10] ──●──
  roi_crop_y           [0.10] ──●──
  roi_sobel_ksize      [5 ▼]
  height_offset_cm     [0.0] ──●──
  height_gain          [1.0] ──●──
  front_arrival_frames   [30]  ──●──
  front_departure_frames [60]  ──●──
```

底部操作栏：`[重置] [应用全部] [保存到配置文件] [关闭]`

### 删除项

- 独立的 "💾 保存校准" 按钮

## 新参数控件定义

| 参数 | 控件 | 范围 | 步长 | 默认值 |
|------|------|------|------|--------|
| `front_contrast_threshold` | slider | 5.0 – 80.0 | 0.5 | 15.0 |
| `front_zone_width` | slider | 10 – 60 | 1 | 20 |
| `front_zone_gap` | slider | 1 – 10 | 1 | 3 |
| `front_arrival_frames` | slider | 10 – 300 | 5 | 30 |
| `front_departure_frames` | slider | 10 – 600 | 5 | 60 |
| `flow_direction` | select | bottom_to_top / left_to_right / right_to_left | — | 取决于通道 |

## 边界情况

| 情况 | 处理 |
|------|------|
| 无参考图 (ref_gray=None) | Panel 2 显示 "No Reference" 占位，Panel 1/3 正常 |
| 未标定 / 无 ROI | `get_debug()` 返回 480×360 空白帧 + "Not calibrated / No ROI" |
| 检测失败 (h_cm=None) | 中间结果正常显示，Panel 1 不画液位线，参数栏标注 "FAIL" |
| `get_debug()` 返回 None | MJPEG 回退到错误信息图片，不崩溃 |
| `_build_debug_frame` 异常 | try/except 包裹，异常时返回错误信息图片 |
| 标定流程与 debug 模式冲突 | 进入标定 drawing 时临时切换到 raw，退出标定后恢复 |
| 无 debug 客户端 | `_debug_enabled=False`，process_frame() 零额外开销 |

## 不在此次范围

- 定格/保存调试帧（后续按需）
- Sobel 梯度幅值图面板（用 1D profile 中的原始+平滑双投影线替代）
- 网格预览的调试模式（仅单通道）
- MQTT 协议新命令（完全复用现有基础设施）

## 实现步骤

1. **ChannelDetector 中间结果缓存** — 新增 `_debug_*` 属性 + `_debug_lock` + `_debug_enabled`
2. **`_build_debug_frame()` 方法** — 3-panel 组合图生成 (OpenCV 绘图)，原始+平滑双投影线
3. **`get_debug()` 方法** — 线程安全读取 + 按需调用 `_build_debug_frame()`
4. **`process_frame()` 改动** — 检测流程中（仅在 `_debug_enabled` 时）保存中间结果
5. **`mjpeg_streamer.py` 改动** — 修正 URL 解析 + 支持 `?debug=1` 参数 + `_debug_enabled` 管理
6. **`tank_vision_dialog.py` 改动** — 三态视图切换 + 参数面板重组（新增 6 参数 + 折叠分组 + 删除保存校准按钮）
