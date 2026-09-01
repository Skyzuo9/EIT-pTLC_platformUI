# CNC 刀具半径补偿 — 设计 spec (2026-07-13)

## 背景与问题

`eit_ptlc/controller/cnc_path.py` 的路径生成中,`gcode.tool.cutter_diameter_mm` **只用于推导扫描列数**
(`_effective_step_mm` → `_compute_coverage_columns`,保证列距 ≤ 直径×(1−重叠率) 的覆盖率),
**完全不参与路径边界计算**:

- 刮扫路径 X 跨度 = 谱带 bbox `[x_min, x_max]`(刀具中心落点);
- contour 策略每列 Y 上下限 = 轮廓在该列 X 处的扫描线交点 × keep_ratio(仍是刀具中心);
- 因此刀刃实际切削区域比谱带轮廓**四周各外扩一个刀具半径 r**。

刀径 2mm 时外扩仅 1mm,可接受;换大刀径后会把相邻杂带刮进收集瓶,pTLC 实验因收到杂色带而失败。

## 目标

刀具中心路径整体**内缩 r = cutter_diameter_mm/2**(可叠加纯度安全边 margin),
使刀刃外缘不越出谱带轮廓——纯度优先,代价是轮廓边缘一圈(≤ r)目标带材料不刮、损失少量收率。

> 决策记录:方向语义(内缩 vs 外扩 vs 双模式)曾向用户提问未及回复,按最贴合
> "杂色带导致实验失败"痛点的**内缩 + 可配置 margin(默认 0)** 方案推进;后续如需
> yield 模式再议(YAGNI)。

## 非目标

- **收集路径不补偿**:粉末落在(内缩后的)切削区内,收集覆盖 = 原 bbox + 桶口/margin 包络,
  只会更全;桶口半径已在 collect_margin 语义中净扣,不再动。
- **视觉层不动**:summary.json / contour_cm 保持视觉真值,补偿是加工层关切,在 cnc_path 内做。
- 不做运行前 knob 透传(gcode cfg 已是 provider 实时读 app.yaml,config 页改动即时生效)。

## 方案选型

| 方案 | 说明 | 结论 |
|---|---|---|
| **A. 逐列解析腐蚀(选定)** | X 跨度内缩 + 每列在 dx∈[−R,R] 采样取圆盘弦高紧界(见算法),无新依赖,path 函数架构不动 | ✅ 精确到圆盘腐蚀的列向投影,实现小 |
| B. cv2 栅格腐蚀轮廓预处理 | rasterize→erode→findContours 后走原逻辑 | ❌ 引入分辨率选择;带中部窄于刀径时裂成多连通域,取最大域丢材料 |
| C. 朴素每轴内缩(Y 恒减 R) | 实现最简 | ❌ 轮廓斜边处欠补偿,恰是大刀径动机场景 |

## 配置

```yaml
gcode:
  tool:
    cutter_diameter_mm: 2
    cutter_compensation: true       # 刀径半径补偿开关(dataclass 默认 false = 零回归)
    compensation_margin_mm: 0.0     # 额外纯度安全边(mm, 单侧), 补视觉分割边界误差
```

- `ToolCfg` 新增 `cutter_compensation: bool = False`、`compensation_margin_mm: float = 0.0`
  (dataclass 默认关,遵循 collector_x_positive / machine_y_min_mm 的零回归惯例;真机 app.yaml 显式开)。
- loader 校验:`compensation_margin_mm ∈ [0, 10]`,越界 raise ValueError。
- 有效补偿半径 `R_cm = (cutter_diameter_mm/2 + compensation_margin_mm) / 10`,开关关闭时 R=0。

## 几何算法

统一在 `generate_scrape_arrays` 内、**镜像帧变换之后**应用(X 反射与腐蚀可交换,作用于 eff_* 几何最简):

### 1. X 跨度内缩(所有策略)

刮扫 bbox 传给 path_fn 前内缩:`scrape_bbox = (x_min+R, y_min+R, x_max−R, y_max−R)`
(bbox 四边各内缩 R;contour 策略的 bbox 仅作退化列 fallback,同样内缩后语义自洽)。
覆盖列数 `_compute_coverage_columns` 的 `x_span_scrape_mm` 与覆盖不足告警同步改用内缩后跨度。
collect 路径继续用原 eff_bbox,不受影响。

### 2. 每列 Y 圆盘腐蚀(contour 策略)

`_path_contour` 新增参数 `tool_radius_cm: float = 0.0`(R=0 时逐字节零回归)。
每列 x 的腐蚀区间为圆盘腐蚀的精确列向投影:

```
y_top'(x) = min over dx∈[−R,R] of ( y_top(x+dx) − √(R²−dx²) )
y_bot'(x) = max over dx∈[−R,R] of ( y_bot(x+dx) + √(R²−dx²) )
```

实现:dx 取 9 个均匀采样(含 0、±R),`x+dx` 钳到 `[x_min+ε, x_max−ε]` 防扫描线在
垂直端边失效;某采样点 `_sample_contour_y_scanline` 返回 None 则跳过该 dx
(端部钳制后一般不会发生)。keep_ratio 作用在**腐蚀后**区间(先几何、后工艺)。

### 3. 退化规则(带窄于刀)

- **X 向**:内缩后 `x_max' − x_min' ≤ 0` → 整带窄于刀径,collapse 为原跨度中点单列
  (columns=1,一刀过中心,过切对称且物理不可避免),WARN 一条。
  注意不得复用 `_check_degenerate` 的占位路径(那会整段不刮,丢材料)。
- **列向**:某列腐蚀区间为空(`y_top' < y_bot'`)→ 该列点收拢到 `(y_top'+y_bot')/2`
  中点(最小化对称过切;Z 全程下压无法跳列),计数,循环后汇总 WARN 一条
  (`n/columns 列窄于刀径, 已收拢中线`)。

### 4. zigzag / boustrophedon

纯 bbox 矩形策略,靠第 1 步 bbox 四边内缩即完成补偿,函数体零改动。

## 预览增强

`cnc_preview.py` 刮扫路径渲染增加**刀宽扫掠带**:以 `cutter_diameter_mm` 换算像素
(`px = diameter_mm/10 × plate_px_per_cm`)为线宽画半透明底带,中心线照旧。
让"补偿后刀刃是否越出谱带"在预览图上直接可核。预览失败不污染真机数组(既有保护不变)。

## 日志

`generate_scrape_arrays` 收尾 INFO 行追加:`comp=on/off R=x.xmm collapsed_cols=n`。

## 测试(test_cnc_path_offline.py 追加)

1. **零回归**:`cutter_compensation=False`(默认)→ 数组与现状逐点相等(拿一组现有场景对拍)。
2. 矩形轮廓 + comp on:所有刮扫点距 bbox 四边 ≥ R(机床坐标换算后)。
3. 斜边轮廓(三角/梯形)+ comp on:与暴力腐蚀 oracle(密集 dx 采样)对拍,
   验证弦高项 √(R²−dx²) 生效(朴素恒减 R 会挂)。
4. `compensation_margin_mm` 每 +1mm → 内缩每侧再 +1mm;越界 loader 拒绝。
5. 窄带(band 高 < 2R)→ 列收拢中线 + WARN;整带 X 跨 < 2R → 单列中心 + WARN,
   且 pass_count 正常(不得变成占位不刮)。
6. 覆盖列数按内缩后跨度推导(构造边界场景断言 columns 变化)。
7. collect 数组(g_cx/g_cy)在 comp on/off 下逐点不变。
8. loader 解析 `cutter_compensation` / `compensation_margin_mm` 往返。

## 兼容性与上机

- dataclass 默认关 → 全离线套件零回归;app.yaml 提交时置 `cutter_compensation: true`
  (当前 2mm 刀内缩 1mm,行为变化小且方向正确)。
- 上机验证项:开补偿跑一次 photoscrape,预览图核对扫掠带贴轮廓内侧;真机刮完看
  相邻杂带是否残留完好。
