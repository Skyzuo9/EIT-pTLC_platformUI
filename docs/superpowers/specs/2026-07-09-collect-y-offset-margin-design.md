# 收集路径 Y 向偏移 + 绝对余量重构 — 设计

**日期**: 2026-07-09
**分支**: codex/ui-upper-next
**状态**: 设计已定，待 writing-plans

## 背景与动机

拍照刮板收集路径（无 Z 粉桶，`_build_collect_points`）当前用一个乘性对称参数
`collect_expand_ratio`（app.yaml 现值 1.2）在 Y 方向放大收集范围，本意是"往外扩一些，
把所有硅胶收干净"。真机（`origin_corner=top-right` → `flip_x=flip_y=True`）暴露了两个
**正交的物理问题**，现有单一膨胀参数在原理上无法同时解决：

1. **覆盖余量应是绝对量纲，不是比例。** 粉末外溅、桶口口径都是绝对长度（mm），与谱带高度
   无关。乘性 ratio 随带高忽大忽小：1cm 带 ×1.2 每侧加 1mm，3cm 带每侧加 3mm（过扫、空跑
   收集空板），0.4cm 带每侧仅 0.4mm（不足）。而 `bottle_diameter_mm`（5mm，桶口）当前在
   路径生成里**完全没被用到**，覆盖公式里"桶口半径覆盖板边"只是注释里的空话。

2. **铣刀↔收集器存在 Y 向装配偏移（真机实测 ≈ 1mm，收集器偏 −Y）**，导致 +Y 侧谱带边缘
   硅胶残留。这是**单向常量 bias**，对称的膨胀/margin 永远治不了它——一侧残留在数学上只可能
   来自非对称偏移。真机 +Y 单侧残留即此设计的交叉验证。

同时真机发现的第三点（X 端拖尾堆积）**已确认是既有 `bottle_x_offset_mm` 标定问题**
（真实间距 ≈90mm，配置 85mm，收集器够不到板 x_max 边）：因 `flip_x=True`，板 x_max 映射
到机床 −X，拖尾区正是 `bottle_x_offset_mm` 直接管辖的段。**该问题纯配置修正（85→90），
不属于本 spec 代码范围**，仅在配置落点里记录。

## 目标

把收集路径的两个正交物理量各自第一性化，均为绝对 mm、可标定、默认安全：

- 新增 `tool.bottle_y_offset_mm`：收集器 Y 向装配偏移补偿，**只作用收集路径**（g_cy），
  scrape 路径（铣刀是基准）与 g_cx 一律不动。
- 用 `collect_margin_mm`（绝对余量，并真正扣除桶口半径）取代乘性 `collect_expand_ratio`。

## 非目标

- 不改 X 向拖尾/回走逻辑、`bottle_x_offset_mm`、`return_sweep`、scrape 路径。
- 不改 PLC 契约（仍块写 g_sx/g_sy/g_cx/g_cy 各 400 点 + g_scrape_feed）。
- 不动前端/API（`collect_expand_ratio` 未被任何 route/UI 引用，`generate_cnc_path`/
  `generate_scrape_arrays` 的 override 形参在生产中从不带值调用——见下"blast radius"）。
- X 端拖尾堆积的配置修正（85→90）不在代码范围。

## 核心公式（收集路径 Y，板 cm）

`generate_scrape_arrays` 的收集分支（cnc_path.py:831-832 现址）改为：

```python
band_center = (bbox_cm[1] + bbox_cm[3]) / 2.0
band_half   = (bbox_cm[3] - bbox_cm[1]) / 2.0
mouth_radius_cm = gcode_cfg.tool.bottle_diameter_mm / 2.0 / 10.0

y_center = band_center + gcode_cfg.tool.bottle_y_offset_mm / 10.0        # ① 标定 bias, 只作用 collect
y_half   = max(0.0, band_half + effective_collect_margin_mm / 10.0 - mouth_radius_cm)  # ② 绝对余量 − 桶口半径
```

**推导（第一性）**：桶口半径 r 每条扫掠线覆盖 ±r。要罩住"谱带 ± 外溅余量 margin"，
所需扫掠半 span = `带半高 + margin − r`。偏移只平移中心，不改半 span → 两个量正交、
可独立标定、天然组合。

`y_center`/`y_half` 仍如现址喂给 `_build_collect_points`（tail 段与 return 段自动一致继承，
无需分别处理）。`max(0.0, …)` 下钳：margin < 桶口半径时扫掠半 span 收敛到 0（单中心线，
桶口自身覆盖谱带），不产生负值。

## 配置改动（blast radius = 4 文件 + 测试，全在 eit_ptlc/）

`collect_expand_ratio` 全仓引用仅这 4 文件（grep 确认无前端/API/其他 controller 引用）：

| 文件 | 改动 |
|---|---|
| `config/models.py` | `ToolCfg` 新增 `bottle_y_offset_mm: float = 0.0`；`GCodeCfg` 删 `collect_expand_ratio: float = 1.0`，加 `collect_margin_mm: float = 4.0` |
| `config/loader.py` | 解析 `tool.bottle_y_offset_mm`（默认 `ToolCfg.bottle_y_offset_mm`）；解析 `collect_margin_mm` 替换 `collect_expand_ratio`；删旧 `[1.0, 2.0]` 校验；加新校验：`collect_margin_mm >= 0`、`abs(bottle_y_offset_mm) <= 20`（防手滑，单位 mm） |
| `config/app.yaml` | `tool.bottle_y_offset_mm: 1.0`（真机实测起步值）；删 `collect_expand_ratio: 1.2`，加 `collect_margin_mm: 4.0`；`tool.bottle_x_offset_mm: 85 → 90`（配置修正，随本次一并落） |
| `controller/cnc_path.py` | `generate_scrape_arrays` + `CncPathController.generate_cnc_path` 形参 `collect_expand_ratio → collect_margin_mm`；换 Y 公式（上节）；换校验（`>=0` 取代 `[1.0,2.0]`）；更新 docstring 与 log 行（第 822、824-830、874、880 附近） |

### 默认值取舍

- `collect_margin_mm = 4.0`：net 每侧 = 4.0 − 2.5(桶口半径) = 板边外 +1.5mm 实扫覆盖。
  比"刚好压带边"（margin=半径 → net=0）宽出一档，因真机 1mm 偏移即把边缘 margin 吃穿
  致残留、且桶口边缘吸力弱，不宜全赌桶口。真机可再调。
- `bottle_y_offset_mm = 1.0`：真机实测收集器偏 −Y 约 1mm。符号按与 `bottle_x_offset_mm`
  同约定（板空间加、flip 后统一变换）；真机拨到 +Y 残留消失，若拨反残留加重则翻符号。

## 正交性铁证（测试重点）

扩 `tests/test_cnc_path_offline.py`：

- **偏移正交**：`bottle_y_offset_mm` 非零使 g_cy 整体平移常量，g_sx/g_sy/g_cx **逐点不变**。
- **余量绝对**：同 `collect_margin_mm`、不同带高 → 相同绝对外扩（net 半 span 之差 = 带半高之差，
  与 margin 无关）；对照旧乘性行为（外扩随带高变）已被移除。
- **扣桶口半径**：`collect_margin_mm == bottle_diameter_mm/2` → y_half == band_half（净外扩 0）。
- **默认回归安全**：`bottle_y_offset_mm == 0.0` → y_center 恒等于 band_center（纯几何不变）。
- **下钳**：`collect_margin_mm < bottle_diameter_mm/2` → y_half 钳到 0，不出负值、不抛异常。
- **校验**：`collect_margin_mm < 0` 抛 ValueError；`abs(bottle_y_offset_mm) > 20` 抛 ValueError。
- 既有 collect Y-span 相关断言按新公式更新（不再是 ratio 语义）。

同步检查 `tests/test_config_service_offline.py` 是否有 `collect_expand_ratio` 键断言需迁移
（grep：当前无该键引用，预计仅需确认加载新键不报错）。

## 风险与回归

- 语义变更（ratio→绝对量）无法逐位保持旧输出，但旧 `collect_expand_ratio` 未被生产流程
  以外任何处消费，且默认 `bottle_y_offset_mm=0` 保证偏移维度零行为变化。
- `keep_ratio`/`strategy`/`collect_margin_mm` 三个 override 形参在生产 VM 中均不带值调用
  （默认 None → 取 cfg），改名安全。
- 桶口半径扣除后若真机 +Y 仍有散粉残留 → 调大 `collect_margin_mm`（不动代码）。

## 真机配置落点汇总

- `tool.bottle_x_offset_mm: 85 → 90`（拖尾够到 x_max）
- `tool.bottle_y_offset_mm: 1.0`（+Y 残留补偿，拨符号）
- `collect_expand_ratio: 1.2` 删 → `collect_margin_mm: 4.0`
