# 液位检测算法参数化修复 — 设计文档

Date: 2026-06-10
Status: Draft — awaiting review
Scope: `液位检测模块/work/water_level_8ch_compress_mqtt.py` 单文件

## 背景

上位机侧液位检测的多数可调参数（边缘阈值、模糊核、Sobel 核、SNR 阈值、对比度阈值、对比区宽度、区隙间距）在实际调节中几乎不产生可观测的检测结果变化。唯一有效的参数是 `water_diff_threshold`（差分均值下限），在 12.5→13.0 处产生毛刺状的切断效应。

根因分析发现 5 个独立问题：1 个死代码重言式、1 个可视化计量错位、1 个 SNR 分母接近零、1 个中位数湮没效应、1 个对比度动态范围不匹配。

## 设计目标

1. 每个参数控制一个正交的检测门控维度
2. 参数可调范围覆盖实际信号的动态范围（在决策边界附近有区分力）
3. Debug 可视化展示检测实际使用的量，与门控逻辑一致

## 架构约束

- **不改动**：管线调用顺序、参数名和 MQTT 协议、`_save_debug_cache` 接口签名、状态机逻辑
- **改动集中在** `water_level_8ch_compress_mqtt.py` 单文件
- **上位机 UI 无需修改**

## 检测管线（5 门控级联）

```
帧输入
  → [G1: 差分存在性] water_diff_threshold
  → [G2: 边缘一致性] water_edge_threshold + front_valid_row_ratio
  → [G3: 信噪显著性] water_snr_threshold（受 water_blur_ksize/water_sobely_ksize 间接影响）
  → [G4: 湿干对比] front_contrast_threshold（front_zone_width/gap 控制采样区域）
  → [G5: 时序稳定] front_arrival_frames / front_departure_frames（状态机，无 bug）
  → 输出
```

---

## Fix 1: 删除 L1089 死代码 [G2]

### 问题

`detect_water_level()` L1089-1090:
```python
if edge_val < threshold:
    return None
```

`edge_val` 在 `_detect_edge_rowwise()` 中由 `valid_mask = peak_vals >= threshold` 过滤后的值计算中位数，因此 `edge_val >= threshold` 恒成立。此检查是永真重言式。

### 修改

删除 L1089–1090。G2 的门控完全由 `_detect_edge_rowwise()` 内部完成（`valid_mask` 过滤 + `valid_count >= total * valid_ratio` 检查）。

### 影响

消除死代码。`water_edge_threshold` 的效果仅通过 per-row 有效行过滤体现——提高阈值 → 更少的行被认为"有效" → 更易触发 valid_ratio 检查失败。

---

## Fix 2: 修复 SNR 计算 [G3]

### 问题

`detect_water_level()` L1094-1098:
```python
profile_median = float(np.median(grad))   # 全局 2D 梯度中位数 → 趋近于 0
snr = edge_val / profile_median          # → 100+
```

ROI 中绝大部分像素是平坦区（梯度≈0），全局中位数接近零。SNR 永远 30~200+，远超参数范围 1.2~15.0。

### 修改

将分母从全局中位数改为**背景区（干侧远端）梯度中位数**：

```python
# 取 ROI 远端 20% 作为噪声参考区
if direction == "left_to_right":
    bg_w = max(1, grad.shape[1] // 5)
    bg = grad[:, -bg_w:]          # 最右列（干侧远端）
elif direction == "right_to_left":
    bg_w = max(1, grad.shape[1] // 5)
    bg = grad[:, :bg_w]            # 最左列（干侧远端）
else:  # bottom_to_top
    bg_h = max(1, grad.shape[0] // 5)
    bg = grad[:bg_h, :]            # 最上行（干侧远端）

noise_floor = float(np.median(bg))
snr = edge_val / max(noise_floor, 1e-6)
```

### 为什么这会让 blur/sobel 参数起作用

- 小 blur（ksize=1,3）→ 背景噪声未被平滑 → noise_floor 高 → SNR 低
- 适中的 blur（ksize=5,7）→ 噪声平滑但边缘保留 → SNR 最优
- 过大 blur（ksize=9）→ 边缘也被抹平 → edge_val 降低 → SNR 下降
- 用户调 blur/sobel 会观察到 SNR 值变化，从而影响 G3 门是否通过

### 参数范围

`water_snr_threshold` 默认 3.5，校验范围 1.2–15.0 不变。修复后实际 SNR 落在 2~30 区间，参数调节有区分力。

---

## Fix 3: 对比度归一化 [G4]

### 问题

`_compute_front_contrast()` 返回 `dry_median - wet_median`（绝对灰度差，0–255）。真实溶剂前沿湿干差 30–80，远超默认阈值 15。即使拉满到 80，多数信号仍通过。

### 修改

将对比度改为归一化比值，落在可预测的 0–1 区间：

```python
# 归一化对比度: (干-湿) / 干区亮度
contrast = (dry_median - wet_median) / max(dry_median, 1.0)
# 真实溶剂前沿: ~0.10–0.50
```

参数调整：

| 项目 | 旧值 | 新值 |
|------|------|------|
| `front_contrast_threshold` 默认 | 15.0 | 0.12 |
| 校验范围 (PARAM_VALIDATORS) | 5.0–80.0 | 0.02–0.80 |
| UI slider min/max/step | 5/80/0.5 | 0.02/0.80/0.01 |
| PARAM_HINTS 描述 | "5.0 ~ 80.0" | "0.02 ~ 0.80（归一化，越大越严格）" |

### 向后兼容

`_load_config_from_file()` 加载时检测旧格式（`front_contrast_threshold > 1.0`），自动除以 255 迁移，打印 warning。新格式直接使用。

`front_zone_width` / `front_zone_gap` 保持原样——median 对区域宽度不敏感是正常的。

---

## Fix 4: P3 1D 投影面板可视化对齐

### 问题

P3 面板画的是 mean 投影曲线 + 阈值线，但检测实际比较的是 per-row 中位数峰值 (`edge_val`)。两者单位相同（Sobel 梯度幅值）但数值差 3–5 倍。用户看到蓝线峰值低于橙色阈值线 → 困惑。

### 修改

在 P3 面板新增一条"per-row 中位数峰值"参考线，与阈值线同单位可比：

```
P3 新增元素:
  ── 绿点划线: edge_val（per-row 中位数峰值），标注 "row_peak=X.X"  ← 新增
  ── 橙虚线:   water_edge_threshold，标注改为 "row_thr=X"            ← 标签修改

P3 底部信息栏新增（替代原有零散标注）:
  valid:N/M(P%) | SNR:X.X | contrast:X.XX ✓/✗
```

### 涉及方法

- `_build_debug_frame()`：底部信息栏拼接逻辑
- `_draw_projection_horizontal()`：画绿线 + 阈值标注修改
- `_draw_projection_vertical()`：同上

绿线画法（以 horizontal 为例，插入在红色 peak 标记之前）：

```python
# per-row 中位数峰值参考线（绿色点划线，与阈值同单位可比）
if edge_val is not None and edge_val > 0:
    ev_y = to_y(edge_val)
    for px in range(0, panel_w, 8):
        cv2.line(canvas, (px, ev_y), (min(px + 4, panel_w - 1), ev_y),
                 (0, 180, 0), 1)  # green dashed
    cv2.putText(canvas, f"row_peak={edge_val:.1f}", (2, ev_y - 3),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 180, 0), 1)
```

底部信息栏（追加在方向标注之前）：

```python
# 门控状态摘要
parts = []
if valid_count is not None:
    total = len(row_positions) if row_positions is not None else 0
    parts.append(f"valid:{valid_count}/{total}")
parts.append(f"SNR:{snr:.1f}")
parts.append(f"contrast:{contrast:.2f}{'✓' if contrast_ok else '✗'}")
summary = " | ".join(parts)
cv2.putText(canvas, summary, (2, y0 + panel_h - 18),
            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (80, 80, 80), 1)
```

这需要将 `valid_count`、`snr`、`contrast` 传递到 debug 绘制路径——在 `_save_debug_cache` 和 `_build_debug_frame` 之间增加这些字段。

---

## 改动汇总

| Fix | 方法/区域 | 类型 | 约行数 |
|-----|----------|------|--------|
| ① 死代码 | `detect_water_level()` L1089–1090 | 删除 | -2 |
| ② SNR | `detect_water_level()` 背景区计算 | 新增 | +12 |
| ③ 对比度 | `_compute_front_contrast()` 归一化 | 修改 | +3 |
| ③ 参数默认值 | `DEFAULT_DETECT_PARAMS`、`PARAM_VALIDATORS`、`PARAM_HINTS` | 修改 | +5 |
| ③ 向后兼容 | `_load_config_from_file()` | 新增 | +8 |
| ④ P3 可视化 | `_draw_projection_horizontal()`、`_draw_projection_vertical()`、`_build_debug_frame()` | 新增/修改 | +30 |
| ④ debug 传递 | `detect_water_level()` dbg dict + `_save_debug_cache()` 签名 + snap | 修改 | +15 |

总计约 **+70 行 / -2 行**，全部在 `water_level_8ch_compress_mqtt.py`。

---

## 不变更项

- MQTT topic 和 payload 格式不变
- 上位机 `tank_vision_dialog.py` 参数面板无需修改（参数名、范围通过 MQTT `get_detect_param` 动态加载）
- 状态机（WAITING/TRACKING/GONE）逻辑不变
- `front_zone_width` / `front_zone_gap` / `front_valid_row_ratio` / `front_arrival_frames` / `front_departure_frames` 不变
- `water_diff_threshold`（G1）已验证有效，不变
- `height_gain` / `height_offset_cm` / `roi_crop_*` / `roi_sobel_ksize` 不变

## 风险与回滚

- **对比度归一化向后兼容**：旧配置文件中 `front_contrast_threshold > 1.0` 时自动 `/255` 并 warning，不静默丢失用户设置
- **SNR 背景区假设**：背景区取 ROI 远端 20%——若溶剂已覆盖整个 ROI 则该假设不成立，但前沿状态机会在 GONE 时冻结输出，不影响已完成的跟踪
- **回滚**：改动单文件，git revert 即可恢复
