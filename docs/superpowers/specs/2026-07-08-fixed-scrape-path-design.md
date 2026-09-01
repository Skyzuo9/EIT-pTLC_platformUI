# 固定刮取路径（回收率实验） — 设计稿

日期: 2026-07-08
分支: codex/ui-upper-next
相关记忆: `photoscrape-vision-frame-consistency`, `cnc-collect-path-tail-return`, `ptlc-photoscrape-path-source`

## 1. 背景与目标

做刮板硅胶**回收率**实验: 需要 CNC 在板上一个**已知起点、固定尺寸**（默认 10×5 cm）的矩形区域内跑一条**可重复**的刮取+收集路径, 收集到的粉末离线称重后估算回收率。

`photoscrape_process` 已经实现了完整的执行链（下压 → 拍照 → 视觉分析 → 人工门 → `cnc_path` → `write_cnc_path` → 逐 pass 刮取+收集 → 收尾）。本实验唯一需要改变的是**路径来源**: 用一个固定矩形**覆盖**人工绘制 / 视觉识别得到的路径, 其余一律不动。

**非目标**: 回收率的称重与计算由人工线下完成（区域面积恰为 `w×h`, 已知）。脚本不涉及称重/回收率。

## 2. 关键领域事实（决定设计）

路径来源统一模型（见 `sketch_path.py` 顶注 + `photoscrape_process.yaml` §14-23）:

> 拍照刮板消费的是一个"刮取路径产物"——一个 `summary.json`（形状: `bands[].path_json` 指向 `<band>_path.json`, 内含 `scrape_path.bbox_cm` + `contour_cm`）。**视觉**是产生它的一种来源, **手绘**是**同契约**的另一种来源。下游 `cnc_path.generate_scrape_arrays`（400 点扫描线填充 + 收集拖尾 + per-pass Z + 6 变量）对二者完全同形。

坐标链: `板 cm → cnc_path._to_machine → 机床 mm`。`_to_machine` 按 `gcode.origin_corner`（当前 `top-right`）翻转 + `plate_origin_x/y` 平移。**板 cm 坐标系**: 原点在 `origin_corner`, `+x/+y` 指向板内, 与视觉/手绘同框。

推论: **一个固定矩形就是一个 4 点 `contour_cm`**。因为直接用 cm 指定, 完全**跳过**像素↔cm 映射（那套仿射/单应只为把*画布像素*转成 cm）。写 `summary.json` 只需现成的 `sketch_path.write_manual_summary(contour_cm, out_dir)`——零新几何代码。

`generate_scrape_arrays` 的扫描线对任意 ≥3 点多边形鲁棒, 会把矩形 bbox 整片填满, 与 `path_strategy`（zigzag/contour）无关地覆盖 `w×h` 区域。

## 3. 架构（两部分）

### Part A — 脚本 `eit_ptlc/tools/fixed_scrape_path.py`

命令行工具（与既有 `eit_ptlc/tools/*` 同层, 满足文件放置规范）:

```
python -m eit_ptlc.tools.fixed_scrape_path \
    --x0 3 --y0 4 --w 10 --h 5 \
    [--band-id fixed_01] [--out <dir>] [--preview]
```

职责（单一）: 把 (x0, y0, w, h)[板 cm] → `contour_cm` 4 角矩形 → 落 `summary.json` + `<band>_path.json` → 打印 `summary_path` 与 `band_id`。

- 矩形: `(x0,y0) → (x0+w,y0) → (x0+w,y0+h) → (x0,y0+h)`（板 cm, +x/+y 入板）。
- 落盘: 直接调用**现成** `sketch_path.write_manual_summary(contour_cm, out_dir, band_id=...)`。产物与视觉/手绘 summary **同契约**, `cnc_path` 一行不改即可消费。
- `--out` 默认 `<vision.output_dir>/fixed_scrape`（解析为绝对路径）; 只要服务进程可读即可。
- `--preview`（可选）: 加载 `gcode` 配置段（经 `config.loader._parse_gcode`）, 跑**未改动**的 `generate_scrape_arrays`, 打印 `pass_count / point_count / feed`, 让你在下发前看清真机将跑什么。核心落盘路径不依赖任何配置（`write_manual_summary` 不吃 `gcode_cfg`）。
- 输出（stdout, 便于复制回填 / 脚本化）:
  ```
  summary_path=<abs>/summary.json
  band_id=fixed_01
  # 若 --preview:
  preview pass_count=1 point_count=400 feed=800
  ```

**依赖**: `contour_cm` 生成 + `write_manual_summary`（无配置）; `--preview` 时另需 `gcode` 配置。**不依赖** PLC / 相机 / 运行时。

### Part B — `photoscrape_process.yaml` 注入点（方案 B1: 输入变量预种）

新增一个 input var, 在人工门**之前**判定; 非空即用它算路径并**自动下发**（跳过门）; 空（默认）则**行为一字不变**。

新增 vars:
```yaml
- {name: fixed_summary_path, scope: local, type: STRING, io: in, default: "", comment: "固定路径实验: 非空则用此 summary 覆盖视觉/手绘, 直接下发跳过门"}
- {name: fixed_band_id,      scope: local, type: STRING, io: in, default: fixed_01, comment: 固定路径 band_id}
```

在步骤 (3) 初始候选之后、(4)/(5) 门之前插入一个块（约 8 行）:
```yaml
- {op: comment, text: "(3b) 固定路径实验: fixed_summary_path 非空 → 覆盖候选, 自动下发跳过门"}
- op: if
  cond: {binop: "!=", left: {var: fixed_summary_path}, right: {lit: ""}}
  then:
    - {op: call, action: photoscrape.cnc_path, mode: RUN,
       args: {summary_path: {var: fixed_summary_path}, band_id: {var: fixed_band_id}},
       assign: {var: cnc}}
    - {op: assign, target: {var: cand_summary_path}, value: {var: fixed_summary_path}}
    - {op: assign, target: {var: cand_band_id},      value: {var: fixed_band_id}}
    - {op: assign, target: {var: cand_valid},        value: {lit: true}}
    - {op: assign, target: {var: dispatched},        value: {lit: true}}
```

设计要点:
- `dispatched=true` → (5) 的 `while (not dispatched)` 门环**不进入**, 无人工交互, 一键可重复。
- **不放 try/catch**: 固定路径几何非法（如 cnc_path 抛错）应当**显式 fault** 交 run-control, 而非静默落回门——实验要么按预期跑, 要么明确报错, 不含糊。
- 默认 `fixed_summary_path=""` → `if` 不进入, `dispatched` 保持 false, 走原视觉/手绘/门全流程, **生产行为逐字节不变**。
- 收尾 (6)~ 复用: `cnc` 已被本块算好, `write_cnc_path` + per-pass 刮取照常, 无需改动。

## 4. 使用流程（实验一次）

1. `python -m eit_ptlc.tools.fixed_scrape_path --x0 3 --y0 4 --w 10 --h 5 --preview` → 记下 `summary_path`。
2. 启动 `photoscrape_process`, 传入 `fixed_summary_path=<上一步>`（`sample_id`/`save_dir`/`before_path` 照常）。
3. 无门, 直接跑固定路径刮取+收集 → 收粉 → 线下称重 → 回收率 = 实测质量 /（面积 `w×h` × 涂层面密度）。

生产照常时不传 `fixed_summary_path`（默认 `""`）, 一切如旧。

## 5. 边界 / 健壮

- **区域越板**: `x0+w` / `y0+h` 超出板尺寸不在脚本内硬拦（板真实尺寸各实验不同）; `--preview` 的机床 mm 输出 + 真机第一次 dry-run 是护栏。可选加一条"超出 `plate_size_cm` 警告"。
- **band_id 一致性**: 脚本写的 `<band>_path.json` 名与 summary 内 `band_id` 必须一致; 脚本单点产出保证一致, 操作侧 `fixed_band_id` 默认与脚本默认对齐（`fixed_01`）。
- **坐标语义**: `x0,y0` 是板 cm（原点在 `origin_corner`）。真机第一次用小尺寸/低进给 dry-run 核对方向（与 `photoscrape-vision-frame-consistency` 的所见即所跑一致性护栏同调）。

## 6. 测试（离线, TDD）

沿用 `test_photoscrape_gate_flow_offline.py` / `test_sketch_path_offline.py` 模式:

1. **脚本契约**: 给定 (x0,y0,w,h) → `write_manual_summary` 产物: `summary.json` 有 1 band 指向 `<band>_path.json`; `path.json` 的 `contour_cm` 为预期 4 角、`bbox_cm` = (x0,y0,x0+w,y0+h)。
2. **脚本→数组**: 对产物跑 `generate_scrape_arrays`, 断言 `pass_count>=1`、点数 = 400（满点契约）、`bbox` 覆盖 `w×h`。
3. **B1 分支（注入）**: `fixed_summary_path` 非空 → VM 走 (3b), `dispatched` 变 true、门**未执行**（无 human 事件）、`cnc` 来自固定 summary。
4. **B1 默认（零改动）**: `fixed_summary_path=""` → (3b) 跳过, 原门流程（视觉/手绘）逐字保持, 现有门测试全绿不回归。

全部 SDD 离线可跑（无 PLC/相机/真机）。

## 7. 待真机

- 首次小尺寸 + 低进给 dry-run 核对起点方向与刮取覆盖（板 cm ↔ 机床 mm 翻转)。
- 收集拖尾/残粉回走对回收率的影响（见 `cnc-collect-path-tail-return`）: 回收率实验期间建议 `gcode.collection.return_sweep=true` 全面收集。
