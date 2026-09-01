# CNC 刀具半径补偿 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 刮扫路径按刀具半径 + 纯度安全边整体内缩,使刀刃外缘不越出谱带轮廓,大刀径下不再刮进相邻杂带(spec: `docs/superpowers/specs/2026-07-13-cutter-compensation-design.md`)。

**Architecture:** 补偿全部在 `eit_ptlc/controller/cnc_path.py` 加工层完成(视觉真值不动、收集路径不动):X 向 bbox 内缩 R + contour 策略每列做圆盘腐蚀的列向精确投影(dx 采样 + 弦高 √(R²−dx²));带窄于刀时收拢中线并 WARN。配置走 `ToolCfg` 两个新字段,dataclass 默认关(零回归),app.yaml 真机显式开。预览图给刮扫路径叠半透明刀宽扫掠带供人工核对。

**Tech Stack:** Python 3 dataclass 配置 + numpy(已有)+ cv2 预览(已有);测试 pytest,离线无硬件。

## Global Constraints

- 补偿方向 = **内缩**(纯度优先);有效半径 `R_cm = (cutter_diameter_mm/2 + compensation_margin_mm) / 10`,开关关闭时 R=0。
- `cutter_compensation` dataclass 默认 **False**(零回归惯例,同 collector_x_positive / machine_y_min_mm);app.yaml 置 true。
- `compensation_margin_mm ∈ [0, 10]`,loader 越界 raise ValueError。
- **收集路径(g_cx/g_cy)在补偿开/关下逐点不变**;keep_ratio 作用在腐蚀后区间(先几何、后工艺)。
- 带窄于刀绝不能变成占位不刮(pass_count 必须保持正常);收拢中线 + WARN。
- 所有点数组保持 400 点契约(SCRAPE_POINT_COUNT / COLLECT_POINT_COUNT)不变。
- Python 解释器:`"C:/ProgramData/miniforge3/python.exe"`;测试文件既有 pytest 风格,新测试一律 pytest 函数追加在对应文件末尾。
- 提交信息走仓库中文惯例(`feat(cnc): ...` / `test(cnc): ...`)。

---

### Task 1: 配置层 — ToolCfg 新字段 + loader 解析校验 + app.yaml 注释位

**Files:**
- Modify: `eit_ptlc/config/models.py:269-275`(ToolCfg)
- Modify: `eit_ptlc/config/loader.py:387-396`(`_parse_gcode` 的 tool 段)
- Test: `eit_ptlc/tests/test_cnc_path_offline.py`(文件末尾追加)

**Interfaces:**
- Consumes: 现有 `ToolCfg` dataclass、`loader._parse_gcode(d: dict) -> GCodeCfg`。
- Produces: `ToolCfg.cutter_compensation: bool = False`、`ToolCfg.compensation_margin_mm: float = 0.0`,后续任务经 `gcode_cfg.tool.*` 读取。

- [ ] **Step 1: 写失败测试**(追加到 `test_cnc_path_offline.py` 末尾)

```python
def test_loader_parses_cutter_compensation():
    """刀具半径补偿配置: 开关+安全边解析; margin 越界 [0,10] 拒绝; 默认关(零回归)。"""
    from eit_ptlc.config.loader import _parse_gcode
    cfg = _parse_gcode({"tool": {"cutter_compensation": True, "compensation_margin_mm": 1.5}})
    assert cfg.tool.cutter_compensation is True
    assert abs(cfg.tool.compensation_margin_mm - 1.5) < 1e-9
    # 缺省 = dataclass 默认: 关 + 0
    cfg0 = _parse_gcode({})
    assert cfg0.tool.cutter_compensation is False
    assert abs(cfg0.tool.compensation_margin_mm) < 1e-9
    with pytest.raises(ValueError):
        _parse_gcode({"tool": {"compensation_margin_mm": -0.1}})
    with pytest.raises(ValueError):
        _parse_gcode({"tool": {"compensation_margin_mm": 10.5}})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_path_offline.py::test_loader_parses_cutter_compensation -v`
Expected: FAIL(`TypeError: ToolCfg... unexpected keyword` 或 assert 失败——loader 未解析新键)

- [ ] **Step 3: 实现**

`models.py` — `ToolCfg` 增加两字段(放在 `cutter_diameter_mm` 之后):

```python
@dataclass
class ToolCfg:
    """刀具与收集瓶物理参数."""
    cutter_diameter_mm: float = 2.0
    # 刀径半径补偿(纯度优先): 刮扫中心路径内缩 R=刀半径+安全边, 刀刃外缘不越谱带轮廓,
    # 大刀径不刮进相邻杂带。默认关=零回归; 真机 app.yaml 显式开。收集路径不受影响。
    cutter_compensation: bool = False
    compensation_margin_mm: float = 0.0  # 额外纯度安全边(mm/单侧), 补视觉分割边界误差, [0,10]
    bottle_diameter_mm: float = 5.0
    bottle_x_offset_mm: float = 85.0
    bottle_y_offset_mm: float = 0.0   # 铣刀↔收集器 Y 向装配偏移补偿(只作用收集路径, 默认0=零行为变化)
```

`loader.py` — `_parse_gcode` 的 tool 段(在 `bottle_y_offset_mm` 校验后、`ToolCfg(...)` 构造中):

```python
    compensation_margin_mm = float(tool_raw.get("compensation_margin_mm", ToolCfg.compensation_margin_mm))
    if not (0.0 <= compensation_margin_mm <= 10.0):
        raise ValueError(
            f"gcode.tool.compensation_margin_mm 必须在 [0, 10]mm, 得到: {compensation_margin_mm}"
        )
    tool = ToolCfg(
        cutter_diameter_mm=float(tool_raw.get("cutter_diameter_mm", ToolCfg.cutter_diameter_mm)),
        cutter_compensation=bool(tool_raw.get("cutter_compensation", ToolCfg.cutter_compensation)),
        compensation_margin_mm=compensation_margin_mm,
        bottle_diameter_mm=float(tool_raw.get("bottle_diameter_mm", ToolCfg.bottle_diameter_mm)),
        bottle_x_offset_mm=float(tool_raw.get("bottle_x_offset_mm", ToolCfg.bottle_x_offset_mm)),
        bottle_y_offset_mm=bottle_y_offset_mm,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_path_offline.py::test_loader_parses_cutter_compensation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/config/models.py eit_ptlc/config/loader.py eit_ptlc/tests/test_cnc_path_offline.py
git commit -m "feat(cnc): ToolCfg 刀径补偿开关+纯度安全边 — loader 解析校验 [0,10]mm, 默认关零回归"
```

---

### Task 2: 几何原语 — `_erode_column_interval` + `_inset_interval`

**Files:**
- Modify: `eit_ptlc/controller/cnc_path.py`(在 `_sample_contour_y_scanline` 之后新增两个模块级函数)
- Test: `eit_ptlc/tests/test_cnc_path_offline.py`(末尾追加)

**Interfaces:**
- Consumes: `_sample_contour_y_scanline(contour: np.ndarray, x: float) -> tuple[float, float] | None`(已有)。
- Produces:
  - `_erode_column_interval(contour: np.ndarray, x: float, radius_cm: float, x_clamp: tuple[float, float], n_samples: int = 17) -> tuple[float, float] | None` — 返回 `(y_top', y_bot')`;**可能 y_top' < y_bot'(收拢信号),由调用方判定**;radius≤0 时等价直通 `_sample_contour_y_scanline`。
  - `_inset_interval(lo: float, hi: float, r: float) -> tuple[float, float]` — 双侧内缩,宽度不足 2r 收拢为中点 `(mid, mid)`。

- [ ] **Step 1: 写失败测试**

```python
def test_inset_interval():
    from eit_ptlc.controller.cnc_path import _inset_interval
    assert _inset_interval(0.0, 10.0, 1.0) == (1.0, 9.0)
    lo, hi = _inset_interval(0.0, 1.0, 0.6)   # 宽 1 < 2×0.6 → 收拢中点
    assert abs(lo - 0.5) < 1e-12 and abs(hi - 0.5) < 1e-12


def test_erode_column_interval_rectangle_and_zero_radius():
    import numpy as np
    from eit_ptlc.controller.cnc_path import _erode_column_interval, _sample_contour_y_scanline
    rect = np.asarray([[1.0, 0.5], [16.0, 0.5], [16.0, 1.5], [1.0, 1.5]])
    top, bot = _erode_column_interval(rect, 8.0, 0.2, (1.0, 16.0))
    assert abs(top - 1.3) < 1e-6 and abs(bot - 0.7) < 1e-6      # 矩形腐蚀 = 恒减 R
    # radius=0 → 直通扫描线(逐字节零回归)
    assert _erode_column_interval(rect, 8.0, 0.0, (1.0, 16.0)) == _sample_contour_y_scanline(rect, 8.0)


def test_erode_column_interval_sloped_edge_tighter_than_naive():
    """斜边(slope=1)处真腐蚀 top' ≈ y_top − R·√2, 朴素恒减 R 会欠补偿 —— 弦高项守卫。"""
    import numpy as np
    from eit_ptlc.controller.cnc_path import _erode_column_interval
    tri = np.asarray([[1.0, 0.5], [6.0, 0.5], [6.0, 5.5]])      # 斜边 (1,0.5)→(6,5.5)
    top, bot = _erode_column_interval(tri, 3.0, 0.25, (1.0, 6.0))
    # y_top(3.0)=2.5; 朴素=2.25; 真值≈2.5−0.25√2≈2.1464(17 采样误差 <0.01)
    assert 2.14 <= top <= 2.16
    assert abs(bot - 0.75) < 1e-6                                # 底边平直 → 恒加 R


def test_erode_column_interval_collapse_signal():
    """带高 0.3 < 2R=0.5 → 返回倒置区间(top'<bot'), 调用方据此收拢中线。"""
    import numpy as np
    from eit_ptlc.controller.cnc_path import _erode_column_interval
    thin = np.asarray([[1.0, 0.5], [16.0, 0.5], [16.0, 0.8], [1.0, 0.8]])
    top, bot = _erode_column_interval(thin, 8.0, 0.25, (1.0, 16.0))
    assert top < bot
    assert abs((top + bot) / 2.0 - 0.65) < 1e-6                  # 倒置区间中点 = 带中线
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_path_offline.py -k "inset_interval or erode_column" -v`
Expected: FAIL with `ImportError: cannot import name '_erode_column_interval'`

- [ ] **Step 3: 实现**(`cnc_path.py`,插在 `_sample_contour_y_scanline` 之后、`_sample_contour_y` 之前)

```python
def _erode_column_interval(
    contour: np.ndarray,
    x: float,
    radius_cm: float,
    x_clamp: tuple[float, float],
    n_samples: int = 17,
) -> tuple[float, float] | None:
    """列向圆盘腐蚀: 列 x 处刀具中心可行 Y 区间(刀刃不越轮廓)。

    圆盘腐蚀的精确列向投影(dx 均匀采样近似):
      y_top'(x) = min over dx∈[−R,R] of ( y_top(x+dx) − √(R²−dx²) )
      y_bot'(x) = max over dx∈[−R,R] of ( y_bot(x+dx) + √(R²−dx²) )
    斜边处弦高项收得比"朴素恒减 R"更紧(大刀径动机场景)。

    radius_cm ≤ 0 → 直通 _sample_contour_y_scanline(零回归)。
    采样 x+dx 钳到 x_clamp 内(留 1e-6 防扫描线在垂直端边失效); 单点采样 None 则跳过。
    返回可能 y_top' < y_bot'(带窄于刀的收拢信号), 由调用方判定; 全部采样失败返回 None。
    """
    if radius_cm <= 1e-12:
        return _sample_contour_y_scanline(contour, x)
    lo, hi = x_clamp
    eps = 1e-6
    y_top = math.inf
    y_bot = -math.inf
    found = False
    for i in range(n_samples):
        dx = -radius_cm + (2.0 * radius_cm) * i / (n_samples - 1)
        xq = min(max(x + dx, lo + eps), hi - eps)
        sample = _sample_contour_y_scanline(contour, xq)
        if sample is None:
            continue
        chord = math.sqrt(max(radius_cm * radius_cm - dx * dx, 0.0))
        y_top = min(y_top, sample[0] - chord)
        y_bot = max(y_bot, sample[1] + chord)
        found = True
    if not found:
        return None
    return y_top, y_bot


def _inset_interval(lo: float, hi: float, r: float) -> tuple[float, float]:
    """区间双侧内缩 r; 宽度 ≤ 2r 时收拢为中点(带窄于刀, 对称过切最小)。"""
    if hi - lo <= 2.0 * r:
        mid = (lo + hi) / 2.0
        return mid, mid
    return lo + r, hi - r
```

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_path_offline.py -k "inset_interval or erode_column" -v`
Expected: PASS ×4

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/cnc_path.py eit_ptlc/tests/test_cnc_path_offline.py
git commit -m "feat(cnc): 列向圆盘腐蚀原语 _erode_column_interval + _inset_interval — 弦高项斜边紧界, R=0 直通零回归"
```

---

### Task 3: `_path_contour` 接 `tool_radius_cm` — 每列腐蚀 + 收拢中线 WARN

**Files:**
- Modify: `eit_ptlc/controller/cnc_path.py:322-423`(`_path_contour`)
- Test: `eit_ptlc/tests/test_cnc_path_offline.py`(末尾追加)

**Interfaces:**
- Consumes: Task 2 的 `_erode_column_interval`。
- Produces: `_path_contour(..., tool_radius_cm: float = 0.0, **_)` — 默认 0 逐字节零回归;`generate_scrape_arrays`(Task 4)经 `strategy_kwargs` 传入;收集路径不传(默认 0)。

- [ ] **Step 1: 写失败测试**(直接调 `_path_contour`,机床系 = 板坐标×10,无翻转)

```python
def test_path_contour_tool_radius_erodes_y(tmp_path):
    """tool_radius_cm>0: 每列 Y 上下限收进腐蚀区间(矩形轮廓 → 恒减 R); 默认 0 不动。"""
    import numpy as np
    from eit_ptlc.controller.cnc_path import _path_contour
    rect = np.asarray([[1.0, 0.5], [16.0, 0.5], [16.0, 1.5], [1.0, 1.5]])
    kw = dict(
        x_offset_mm=0.0, plate_origin_x=0.0, plate_origin_y=0.0,
        flip_x=False, flip_y=False, n_points=400, columns=20, contour=rect,
    )
    pts_on = _path_contour((1.2, 0.7, 15.8, 1.3), tool_radius_cm=0.2, **kw)   # bbox 已由调用方内缩
    ys = [p[1] for p in pts_on]
    assert max(ys) <= 13.0 + 1e-6 and min(ys) >= 7.0 - 1e-6                    # [0.7,1.3]cm → [7,13]mm
    pts_off = _path_contour((1.0, 0.5, 16.0, 1.5), **kw)                       # 未传 → 老行为
    ys0 = [p[1] for p in pts_off]
    assert abs(max(ys0) - 15.0) < 1e-6 and abs(min(ys0) - 5.0) < 1e-6


def test_path_contour_collapsed_columns_center_line(caplog):
    """带高 0.3 < 2R: 所有列收拢中线 6.5mm, 且 WARN 汇总一条。"""
    import logging
    import numpy as np
    from eit_ptlc.controller.cnc_path import _path_contour
    thin = np.asarray([[1.0, 0.5], [16.0, 0.5], [16.0, 0.8], [1.0, 0.8]])
    with caplog.at_level(logging.WARNING, logger="eit_ptlc.controller.cnc_path"):
        pts = _path_contour(
            (1.25, 0.65, 15.75, 0.65), x_offset_mm=0.0,
            plate_origin_x=0.0, plate_origin_y=0.0, flip_x=False, flip_y=False,
            n_points=400, columns=20, contour=thin, tool_radius_cm=0.25,
        )
    assert all(abs(p[1] - 6.5) < 1e-6 for p in pts)
    assert any("收拢中线" in rec.message for rec in caplog.records)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_path_offline.py -k "path_contour_tool_radius or collapsed_columns" -v`
Expected: FAIL(`unexpected keyword argument 'tool_radius_cm'` 被 `**_` 吞 → Y 未腐蚀,assert 失败)

- [ ] **Step 3: 实现**

`_path_contour` 签名在 `y_ratio: float = 1.0,` 之后加:

```python
    tool_radius_cm: float = 0.0,
```

docstring 追加一段:

```
    tool_radius_cm(刀具半径补偿, 刮取专用, 收集传 0):
      每列采样改走 _erode_column_interval(圆盘腐蚀列向投影), 刀刃外缘不越轮廓;
      腐蚀区间倒置(带窄于刀)的列收拢到区间中点(对称过切 ≤ 刀半径), 汇总 WARN 一条。
      0 = 直通老采样, 逐字节零回归。
```

循环体改造(替换 `sample = _sample_contour_y_scanline(contour, x_query)` 到 `half_len = ...` 的分支):

```python
    contour_x_lo = float(contour[:, 0].min())
    contour_x_hi = float(contour[:, 0].max())
    n_collapsed = 0
    points: list[tuple[float, float]] = []
    for col in range(columns):
        col_idx = (columns - 1 - col) if reverse_x else col
        x_query = start_x + col_idx * x_step_cm
        # 圆盘腐蚀采样(radius=0 时等价原扫描线); 上下交点 → 刀具中心可行区间
        sample = _erode_column_interval(
            contour, x_query, tool_radius_cm, (contour_x_lo, contour_x_hi),
        )
        collapsed = (
            tool_radius_cm > 1e-12
            and sample is not None
            and (sample[0] - sample[1]) < 1e-9
        )
        # 真正用到轮廓采样（非 None 且非退化截面）才叠加收集偏移/余量
        used_contour = sample is not None and (sample[0] - sample[1]) >= 1e-9
        if collapsed:
            # 带窄于刀: 收拢腐蚀区间中点(对称过切 ≤ 刀半径; Z 全程下压无法跳列)
            y_top, y_bot = sample
            center_y = (y_top + y_bot) / 2.0 + y_shift_cm
            half_len = 0.0
            n_collapsed += 1
        elif used_contour:
            y_top, y_bot = sample
            center_y = (y_top + y_bot) / 2.0 + y_shift_cm
            half_len = max(0.0, y_ratio * (y_top - y_bot) * keep_ratio / 2.0 + y_extra_cm)
        else:
            # 超出轮廓 X 范围 / 上下边缘重合 → 退回 bbox 截面（已含偏移余量，不再叠 delta）
            y_top, y_bot = y_max, y_min
            center_y = (y_top + y_bot) / 2.0
            half_len = (y_top - y_bot) * keep_ratio / 2.0
        y_hi = center_y + half_len
        y_lo = center_y - half_len
        y_step_cm = (y_hi - y_lo) / (per_col - 1)

        downward = (col % 2 == 0)  # 偶列 y_hi → y_lo；奇列反向
        for k in range(per_col):
            if downward:
                y = y_hi - k * y_step_cm
            else:
                y = y_lo + k * y_step_cm
            mx, my = _to_machine(
                x_query + offset_cm, y,
                plate_origin_x, plate_origin_y, flip_x, flip_y,
            )
            points.append((mx, my))
    if n_collapsed:
        log.warning(
            "_path_contour: %d/%d 列腐蚀后窄于刀径, 已收拢中线(对称过切 ≤ 刀半径)",
            n_collapsed, columns,
        )
    return points
```

(注意 `points` 初始化从原位置挪到 `contour_x_lo` 之后,勿重复定义;原 `# 使用扫描线算法求上下交点` 注释由新注释替代。)

- [ ] **Step 4: 跑测试确认通过 + 既有 contour 测试无回归**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_path_offline.py -v`
Expected: 全 PASS(既有 bottle_y_offset/collect_margin/expand_ratio 的 contour 测试 tool_radius 默认 0,不受影响)

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/cnc_path.py eit_ptlc/tests/test_cnc_path_offline.py
git commit -m "feat(cnc): _path_contour 接 tool_radius_cm — 每列圆盘腐蚀采样, 窄列收拢中线+WARN, 默认0零回归"
```

---

### Task 4: `generate_scrape_arrays` 接线 — bbox 内缩/单列收拢/列数跨度/日志 + 行为测试

**Files:**
- Modify: `eit_ptlc/controller/cnc_path.py:800-865`(镜像块之后到刮扫 path_fn 调用)与 `:951-964`(INFO 日志)
- Test: `eit_ptlc/tests/test_cnc_path_offline.py`(末尾追加)

**Interfaces:**
- Consumes: Task 1 的 `gcode_cfg.tool.cutter_compensation / compensation_margin_mm`;Task 2 的 `_inset_interval`;Task 3 的 `tool_radius_cm` 形参。
- Produces: 无新公开接口——`generate_scrape_arrays` 行为变化:补偿开时 `g_sx/g_sy` 内缩,`g_cx/g_cy` 逐点不变。

- [ ] **Step 1: 写失败测试**

```python
def test_compensation_insets_scrape_not_collect(tmp_path):
    """comp on: 刮扫 X/Y 各内缩 R(矩形轮廓); 收集数组逐点不变; margin 叠加内缩。"""
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    a_off = generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="contour")
    cfg_on = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=4.0, cutter_compensation=True))
    a_on = generate_scrape_arrays(s, "band_01", cfg_on, strategy="contour")
    # X: [10,160]mm → [12,158]mm; Y: [5,15]mm → [7,13]mm (R=2mm)
    assert abs(min(a_off.g_sx) - 10.0) < 1e-6 and abs(max(a_off.g_sx) - 160.0) < 1e-6
    assert abs(min(a_on.g_sx) - 12.0) < 1e-6 and abs(max(a_on.g_sx) - 158.0) < 1e-6
    assert abs(min(a_on.g_sy) - 7.0) < 1e-6 and abs(max(a_on.g_sy) - 13.0) < 1e-6
    # 收集路径不补偿: 逐点不变
    assert a_on.g_cx == a_off.g_cx and a_on.g_cy == a_off.g_cy
    # margin 每 +1mm → 每侧再 +1mm
    cfg_m = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=4.0, cutter_compensation=True,
                                  compensation_margin_mm=1.0))
    a_m = generate_scrape_arrays(s, "band_01", cfg_m, strategy="contour")
    assert abs(min(a_m.g_sx) - 13.0) < 1e-6 and abs(max(a_m.g_sx) - 157.0) < 1e-6


def test_compensation_off_zero_regression(tmp_path):
    """开关关(含 margin>0 但开关关)→ 数组与默认逐点相等。"""
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    a0 = generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="contour")
    cfg = GCodeCfg(tool=ToolCfg(cutter_compensation=False, compensation_margin_mm=5.0))
    a1 = generate_scrape_arrays(s, "band_01", cfg, strategy="contour")
    assert a0.g_sx == a1.g_sx and a0.g_sy == a1.g_sy and a0.g_cx == a1.g_cx and a0.g_cy == a1.g_cy


def test_compensation_narrow_band_single_center_column(tmp_path, caplog):
    """整带 X 跨 0.3cm ≤ 2R=0.4cm → 收拢中心单列(11.5mm), 仍正常刮(绝非占位)。"""
    import logging
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 1.3, "y_max": 1.5})
    cfg = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=4.0, cutter_compensation=True))
    with caplog.at_level(logging.WARNING, logger="eit_ptlc.controller.cnc_path"):
        a = generate_scrape_arrays(s, "band_01", cfg, strategy="contour")
    assert all(abs(v - 11.5) < 0.01 for v in a.g_sx)          # 中心 1.15cm, round(3) 后同一机床点
    assert a.pass_count == cfg.scrape.num_passes               # 不是占位不刮
    assert any(v != 0 for v in a.g_sy)
    assert any("中心单列" in rec.message for rec in caplog.records)


def test_compensation_keep_ratio_applies_after_erosion(tmp_path):
    """keep_ratio 作用在腐蚀后区间: 腐蚀 [7,13]mm × keep 0.5 → [8.5,11.5]mm。"""
    s = _write_band_summary_contour(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    cfg = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=4.0, cutter_compensation=True))
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="contour", keep_ratio=0.5)
    assert abs(max(a.g_sy) - 11.5) < 1e-6 and abs(min(a.g_sy) - 8.5) < 1e-6


def _write_summary_free_contour(dirpath, bbox, contour_xy):
    """任意多边形轮廓 summary(三角/梯形用, _write_band_summary_contour 只会写矩形)。"""
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "band_01_path.json").write_text(json.dumps({
        "scrape_path": {"bbox_cm": bbox},
        "contour_cm": [{"x_cm": x, "y_cm": y} for x, y in contour_xy],
    }), encoding="utf-8")
    s = dirpath / "summary.json"
    s.write_text(json.dumps(
        {"bands": [{"band_id": "band_01", "path_json": "band_01_path.json"}]}
    ), encoding="utf-8")
    return s


def _point_in_poly(poly, x, y):
    """射线法点在多边形内(独立 oracle, 不复用生产扫描线)。"""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xt = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < xt:
                inside = not inside
    return inside


def test_compensation_disk_inside_polygon_oracle(tmp_path):
    """独立 oracle: 每个刮扫点为圆心、0.92R 圆盘(16 方向)须整体落在轮廓内 —— 刀刃不越界的直接判据。
    尖角处腐蚀区间为空的列(收拢中线, 物理不可避免的过切)按生产同款判据跳过。"""
    import math as _m
    from eit_ptlc.controller.cnc_path import _erode_column_interval
    import numpy as np
    tri = [(1.0, 0.5), (6.0, 0.5), (6.0, 5.5)]                 # 斜边 slope=1
    s = _write_summary_free_contour(
        tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 6.0, "y_max": 5.5}, tri)
    cfg = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=5.0, cutter_compensation=True))  # R=0.25cm
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="contour")
    contour = np.asarray(tri)
    r_test = 0.25 * 0.92                                        # 采样近似 + round(3) 容差
    checked = 0
    for mx, my in zip(a.g_sx, a.g_sy):
        x_cm, y_cm = mx / 10.0, my / 10.0                       # 默认 lower-left 原点(0,0)无翻转
        ero = _erode_column_interval(contour, x_cm, 0.25, (1.0, 6.0), n_samples=201)
        if ero is None or ero[0] - ero[1] < 1e-9:
            continue                                            # 收拢列: 过切物理不可避免, 跳过
        for i in range(16):
            ang = 2.0 * _m.pi * i / 16.0
            px, py = x_cm + r_test * _m.cos(ang), y_cm + r_test * _m.sin(ang)
            assert _point_in_poly(tri, px, py), f"刀刃越界: 中心({x_cm},{y_cm}) 边缘({px},{py})"
        checked += 1
    assert checked > 300                                        # 绝大多数点被实际校验


def test_compensation_sloped_edge_beats_naive(tmp_path):
    """斜边列 top ≤ y_top−1.3R < 朴素恒减 R 的 y_top−R —— 弦高项在整链生效。"""
    tri = [(1.0, 0.5), (6.0, 0.5), (6.0, 5.5)]
    s = _write_summary_free_contour(
        tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 6.0, "y_max": 5.5}, tri)
    cfg = GCodeCfg(tool=ToolCfg(cutter_diameter_mm=5.0, cutter_compensation=True))
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="contour")
    hit = [(mx / 10.0, my / 10.0) for mx, my in zip(a.g_sx, a.g_sy) if 2.85 < mx / 10.0 < 3.15]
    assert hit                                                  # 该窗口至少一列
    for x_cm, y_cm in hit:
        naive_top = (0.5 + (x_cm - 1.0)) - 0.25                 # 斜边 y_top(x) − R
        assert y_cm <= naive_top - 0.25 * 0.3                   # 至少再紧 0.3R
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_path_offline.py -k "compensation" -v`
Expected: 除 `test_compensation_off_zero_regression` 外全 FAIL(接线未做,comp on 不生效)

- [ ] **Step 3: 实现**(`generate_scrape_arrays`)

镜像块(`else: eff_bbox, eff_contour, ... = ...`)之后、`# ── 铣刀覆盖率` 之前插入:

```python
    # ── 刀具半径补偿(纯度优先, spec: docs/superpowers/specs/2026-07-13-cutter-compensation-design.md):
    #   刮扫中心路径内缩 R = 刀半径 + 纯度安全边 → 刀刃外缘不越谱带轮廓, 不刮进相邻杂带;
    #   收集路径不补偿(粉末落在切削区内, 桶口覆盖只多不少)。默认关 = 零回归, 真机 app.yaml 显式开。
    comp_r_cm = (
        (gcode_cfg.tool.cutter_diameter_mm / 2.0 + gcode_cfg.tool.compensation_margin_mm) / 10.0
        if gcode_cfg.tool.cutter_compensation else 0.0
    )
    scrape_bbox = eff_bbox
    if comp_r_cm > 0.0:
        sx_lo, sx_hi = _inset_interval(eff_bbox[0], eff_bbox[2], comp_r_cm)
        sy_lo, sy_hi = _inset_interval(eff_bbox[1], eff_bbox[3], comp_r_cm)
        if sx_hi - sx_lo <= 1e-12:
            # 整带 X 跨 ≤ 刀径+边: 收拢中心单列一刀过(对称过切物理不可避免)。名义半宽 1e-6cm
            # 避开 _check_degenerate 的占位分支(那会整段不刮丢材料), round(3) 后为同一机床点。
            sx_lo, sx_hi = sx_lo - 1e-6, sx_hi + 1e-6
            log.warning(
                "[cnc_path_generator] 刀具补偿: band X 跨 %.3fcm ≤ 2R=%.3fcm, 收拢为中心单列",
                eff_bbox[2] - eff_bbox[0], 2.0 * comp_r_cm,
            )
        scrape_bbox = (sx_lo, sy_lo, sx_hi, sy_hi)
```

覆盖列数改用内缩后跨度(替换 `x_span_scrape_mm = (x_max - x_min) * 10.0` 一行;其上 `x_min, _, x_max, _ = bbox_cm` 保留,后面日志还在用):

```python
    x_span_scrape_mm = (scrape_bbox[2] - scrape_bbox[0]) * 10.0
```

`strategy_kwargs` 增加一项:

```python
    strategy_kwargs: dict[str, Any] = {
        "columns":        effective_columns,
        "keep_ratio":     effective_keep_ratio,
        "contour":        eff_contour,
        "tool_radius_cm": comp_r_cm,   # 刀具半径补偿(zigzag/boustrophedon 靠 bbox 内缩, 由 **_ 吞掉)
    }
```

刮扫调用第一个实参 `eff_bbox` 改为 `scrape_bbox`:

```python
    g_sxy = path_fn(
        scrape_bbox,
        x_offset_mm=0.0,
        ...
    )
```

(收集 `_build_collect_points(eff_bbox, ...)` 调用**保持原样**——不补偿。)

收尾 INFO 日志格式串 `"... expand=%.2f y_off=%.1fmm"` 追加 ` comp=%s`,实参列表末尾追加:

```python
        "on(R=%.2fmm)" % (comp_r_cm * 10.0) if comp_r_cm > 0 else "off",
```

- [ ] **Step 4: 跑本文件全量确认通过(含既有用例零回归)**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_path_offline.py -v`
Expected: 全 PASS

- [ ] **Step 5: 跑相邻消费者回归**(photoscrape 流程离线套件)

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_photoscrape_gate_flow_offline.py eit_ptlc/tests/test_cnc_preview_offline.py -q`
Expected: 全 PASS(默认关,行为不变)

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/controller/cnc_path.py eit_ptlc/tests/test_cnc_path_offline.py
git commit -m "feat(cnc): 刀具半径补偿接线 — 刮扫bbox内缩R+安全边/窄带中心单列/列数按内缩跨度, 收集路径不动, 默认关零回归"
```

---

### Task 5: 预览刀宽扫掠带 — payload `cutter_width_px` + 半透明 swath 渲染

**Files:**
- Modify: `eit_ptlc/controller/cnc_preview.py:100-127`(`preview_payload_from_arrays`)、`:130-164`(`render_cnc_overlay`)
- Test: `eit_ptlc/tests/test_cnc_preview_offline.py`(末尾追加)

**Interfaces:**
- Consumes: `cfg.tool.cutter_diameter_mm`(既有字段,与补偿开关无关——刀宽是物理事实,预览恒画)。
- Produces: preview payload 新键 `"cutter_width_px": float`;`render_cnc_overlay` 读该键画扫掠带,键缺失/0 时跳过(向后兼容旧 payload)。

- [ ] **Step 1: 写失败测试**(追加到 `test_cnc_preview_offline.py`)

```python
def test_preview_payload_includes_cutter_width(tmp_path):
    """payload 带 cutter_width_px = 刀径(cm)/板尺(cm)×板宽(px): 2mm/20cm×200px = 2.0px。"""
    root = tmp_path / "vision"
    summary = _case(root)
    cfg = GCodeCfg(path_strategy="contour")
    controller = CncPathController(lambda: cfg, image_root_provider=lambda: root)
    result = asyncio.run(controller.generate_cnc_path(str(summary), "band_01"))
    arrays = SimpleNamespace(
        g_sx=result["g_sx"], g_sy=result["g_sy"],
        g_cx=result["g_cx"], g_cy=result["g_cy"],
        g_scrape_feed=result["g_scrape_feed"], pass_count=result["pass_count"],
        pass_z_list=result["pass_z_list"],
    )
    preview = preview_payload_from_arrays(summary, "band_01", arrays, cfg)
    assert abs(preview["cutter_width_px"] - 2.0) < 1e-6
    # 渲染路径(controller 内部已带 swath 分支)不炸且出图: 上面 result 已断言过 preview_available
    assert result["preview_available"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_preview_offline.py -v`
Expected: 新用例 FAIL with `KeyError: 'cutter_width_px'`;旧用例 PASS

- [ ] **Step 3: 实现**

`preview_payload_from_arrays` 的 return 前加宽度换算,return dict 加一键:

```python
    _px, _py, plate_w_px, _ph = _plate_bbox_xywh(plate_bbox_px)
    cutter_width_px = cfg.tool.cutter_diameter_mm / 10.0 / plate_size_cm * plate_w_px
    return {
        ...
        "feed": int(arrays.g_scrape_feed),
        "cutter_width_px": round(cutter_width_px, 1),  # 刀宽扫掠带(物理事实, 与补偿开关无关)
    }
```

`render_cnc_overlay` 在三条 `_polyline(...)` 之前插入扫掠带(半透明,让"刀刃是否越出轮廓"可直接目视核对):

```python
    # 刀宽扫掠带: 以刀径像素宽半透明铺底, 中心线照旧 —— 补偿后刀刃贴轮廓内侧可直接目视核对
    swath_px = float(preview.get("cutter_width_px") or 0.0)
    scrape_pts = preview.get("scrape_px")
    if swath_px >= 1.0 and scrape_pts and len(scrape_pts) >= 2:
        arr = np.rint(np.asarray(scrape_pts, dtype=np.float32)).astype(np.int32)
        overlay = image.copy()
        cv2.polylines(overlay, [arr], False, cutter_cyan, max(1, int(round(swath_px))), cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.35, image, 0.65, 0.0, image)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_cnc_preview_offline.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/cnc_preview.py eit_ptlc/tests/test_cnc_preview_offline.py
git commit -m "feat(cnc): 预览叠刀宽扫掠带 — payload cutter_width_px + 半透明swath, 刀刃越界目视可核"
```

---

### Task 6: app.yaml 真机开启 + 全量离线回归

**Files:**
- Modify: `eit_ptlc/config/app.yaml:182-186`(gcode.tool 段)

**Interfaces:**
- Consumes: Task 1-4 全链路。
- Produces: 真机配置生效(`CncPathController` 的 provider 每次执行实时读 app.yaml,无需重启)。

- [ ] **Step 1: 修改 app.yaml**(`tool:` 段,保持既有注释,新增两行)

```yaml
  tool:
    cutter_diameter_mm: 2
    cutter_compensation: true          # 刀径半径补偿: 刮扫中心路径内缩 R=刀半径+安全边, 刀刃不越谱带轮廓(纯度优先); 收集路径不受影响
    compensation_margin_mm: 0          # 额外纯度安全边(mm/单侧), 补视觉分割边界误差, [0,10]
    bottle_diameter_mm: 5
    bottle_x_offset_mm: 90            # 真机实测铣刀↔收集器 X 间距≈90mm(补偿拖尾够到 x_max, 治 −X 端堆积)
    bottle_y_offset_mm: -3             # 真机实测: 收集器偏 −Y ≈1mm, 补偿 +Y 侧残留(真机拨符号) 此值越+,收集器口越朝外走(Y轴负方向)
```

- [ ] **Step 2: 确认配置能被加载**

Run: `"C:/ProgramData/miniforge3/python.exe" -c "from eit_ptlc.config.loader import load_app_config; c = load_app_config(); print(c.gcode.tool.cutter_compensation, c.gcode.tool.compensation_margin_mm)"`
Expected: `True 0.0`
(若 `load_app_config` 签名带必选参数,改跑 `-c "import yaml; from eit_ptlc.config.loader import _parse_gcode; print(_parse_gcode(yaml.safe_load(open('eit_ptlc/config/app.yaml', encoding='utf-8'))['gcode']).tool)"`,预期打印 `cutter_compensation=True`。)

- [ ] **Step 3: 全量离线套件回归**

Run: `"C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests -q`
Expected: 全绿(基线 ≈446+ 用例;新增本计划用例数)。任何失败必须修复后才能提交。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/config/app.yaml
git commit -m "feat(cnc): app.yaml 开启刀具半径补偿 (2mm 刀内缩 1mm, 方向正确影响小)"
```

- [ ] **Step 5: 记录上机验证项**(不阻塞合并,提醒即可)

上机 pending:开补偿跑一次 photoscrape,核对 ①预览图扫掠带贴轮廓内侧不越界 ②真机刮完相邻杂带残留完好 ③收集拖尾首步与刮取终点间隙 = R(mm 级,预期内,收集器几何未变)。

---

## Self-Review 记录

- **Spec 覆盖**:配置(T1)/X 内缩+列数跨度(T4)/每列腐蚀(T2+T3)/退化两规则(T3 列收拢、T4 单列)/zigzag+boustrophedon bbox 内缩(T4 的 scrape_bbox 对所有策略生效)/预览(T5)/日志(T3 WARN + T4 INFO)/测试清单 1-8(T1: #8, T4: #1#2#3#4#5#6#7)/app.yaml(T6)。收拢列计数在 `_path_contour` WARN(spec 原写进 INFO 行,实现放 WARN 更醒目,语义等价)。
- **无占位符**:全部代码块完整可粘贴。
- **类型一致性**:`_erode_column_interval(contour, x, radius_cm, x_clamp, n_samples=17)`、`_inset_interval(lo, hi, r)`、`tool_radius_cm` 形参名在 T2/T3/T4 一致;payload 键 `cutter_width_px` 在 T5 两处一致。
