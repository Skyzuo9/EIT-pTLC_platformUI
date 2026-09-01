# 收集路径 Y 偏移 + 绝对余量重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把收集路径的两个正交物理量各自第一性化 —— 新增 `tool.bottle_y_offset_mm`（收集器 Y 装配偏移补偿，只作用 g_cy）+ 用绝对量纲 `collect_margin_mm`（并真扣桶口半径）取代乘性 `collect_expand_ratio`。

**Architecture:** 收集路径 Y 由 `y_center`（谱带中心 + 标定偏移）和 `y_half`（谱带半高 + 绝对余量 − 桶口半径）两个正交项决定，均在 `generate_scrape_arrays` 的收集分支计算后喂给 `_build_collect_points`。偏移是单向 bias（治一侧残留），余量是对称绝对量（治覆盖），二者数学正交、可独立标定。

**Tech Stack:** Python 3.11（conda env `platformupper`）、dataclass 配置层、pytest 离线测试。

## Global Constraints

- PLC 契约不变：块写 `g_sx/g_sy/g_cx/g_cy` 各 **400** 点 + `g_scrape_feed`；scrape 路径（g_sx/g_sy）与 g_cx 一律不受本次改动影响。
- `tool.bottle_y_offset_mm`：模型默认 **0.0**（回归安全）；app.yaml 真机值 **1.0**。
- `collect_margin_mm`：模型默认与 app.yaml 均 **4.0**；桶口半径 = `tool.bottle_diameter_mm / 2`（当前 5mm → 2.5mm）。
- 校验：`collect_margin_mm >= 0`；`abs(bottle_y_offset_mm) <= 20`（mm）。
- 运行测试用 env python：`E:/Anaconda/envs/platformupper/python.exe -m pytest <path> -v`。
- `collect_expand_ratio` 全仓仅 4 文件引用（models/loader/app.yaml/cnc_path），无前端/API 触及；重命名安全。
- 每个 Task 完成后跑全套离线测试确认绿。

---

### Task 1: 新增 `tool.bottle_y_offset_mm`（纯additive，收集器 Y 偏移补偿）

**Files:**
- Modify: `eit_ptlc/config/models.py:318-322`（ToolCfg）
- Modify: `eit_ptlc/config/loader.py:430-435`（_parse_gcode tool 解析）
- Modify: `eit_ptlc/controller/cnc_path.py:831`（y_center 加偏移）
- Modify: `eit_ptlc/config/app.yaml:189-192`（tool 段加 bottle_y_offset_mm）
- Test: `eit_ptlc/tests/test_cnc_path_offline.py`（加 helper + 正交性测试 + loader 偏移校验测试）

**Interfaces:**
- Consumes: 现有 `generate_scrape_arrays(summary_path, band_id, gcode_cfg, *, strategy, keep_ratio, collect_expand_ratio)`、`ToolCfg`、`GCodeCfg`、`_parse_gcode(d) -> GCodeCfg`。
- Produces: `ToolCfg.bottle_y_offset_mm: float`（默认 0.0）；收集路径 g_cy 整体平移 `bottle_y_offset_mm`（板空间，经 flip_y 变换）；g_sx/g_sy/g_cx 不变。

- [ ] **Step 1: 写失败测试（正交性 + 平移量）**

在 `eit_ptlc/tests/test_cnc_path_offline.py` 顶部 import 区（第 19 行 `from eit_ptlc.config.models import GCodeCfg` 处）改为同时导入 `ToolCfg`，并在文件末尾（`test_generate_cnc_path_placeholder_reachable` 之后）追加 helper 与测试：

```python
import pytest
from eit_ptlc.config.models import GCodeCfg, ToolCfg


def _write_band_summary(dirpath: Path, bbox: dict) -> Path:
    """写一个最小 summary.json + band path_json, 返回 summary 路径。"""
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "band_01_path.json").write_text(
        json.dumps({"scrape_path": {"bbox_cm": bbox}}), encoding="utf-8"
    )
    (dirpath / "summary.json").write_text(
        json.dumps({"bands": [{"band_id": "band_01", "path_json": "band_01_path.json"}]}),
        encoding="utf-8",
    )
    return dirpath / "summary.json"


def test_bottle_y_offset_shifts_only_collect_y(tmp_path):
    """bottle_y_offset_mm 使 g_cy 整体平移常量, 而 g_sx/g_sy/g_cx 逐点不变（正交性铁证）。"""
    summary = _write_band_summary(
        tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5}
    )
    base = GCodeCfg()  # bottle_y_offset_mm 默认 0.0
    shifted = GCodeCfg(tool=ToolCfg(bottle_y_offset_mm=3.0))
    a0 = generate_scrape_arrays(summary, "band_01", base, strategy="boustrophedon")
    a1 = generate_scrape_arrays(summary, "band_01", shifted, strategy="boustrophedon")

    assert a0.g_sx == a1.g_sx
    assert a0.g_sy == a1.g_sy
    assert a0.g_cx == a1.g_cx  # X 维完全不受 Y 偏移影响

    deltas = [c1 - c0 for c0, c1 in zip(a0.g_cy, a1.g_cy)]
    assert max(deltas) - min(deltas) < 1e-6      # 常量平移(非缩放/非局部)
    assert abs(deltas[0] - 3.0) < 1e-6           # 默认 lower-left(flip_y=False): 板+Y→机床+Y, 平移=+offset_mm
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_cnc_path_offline.py::test_bottle_y_offset_shifts_only_collect_y -v`
Expected: FAIL —— `TypeError: ToolCfg.__init__() got an unexpected keyword argument 'bottle_y_offset_mm'`。

- [ ] **Step 3: ToolCfg 加字段**

`eit_ptlc/config/models.py` ToolCfg（当前 318-322）改为：

```python
@dataclass
class ToolCfg:
    """刀具与收集瓶物理参数."""
    cutter_diameter_mm: float = 2.0
    bottle_diameter_mm: float = 5.0
    bottle_x_offset_mm: float = 85.0
    bottle_y_offset_mm: float = 0.0   # 铣刀↔收集器 Y 向装配偏移补偿(只作用收集路径, 默认0=零行为变化)
```

- [ ] **Step 4: loader 解析 + 校验**

`eit_ptlc/config/loader.py` `_parse_gcode` 中 tool 构造（当前 430-435）改为：

```python
    tool_raw = d.get("tool") or {}
    bottle_y_offset_mm = float(tool_raw.get("bottle_y_offset_mm", ToolCfg.bottle_y_offset_mm))
    if abs(bottle_y_offset_mm) > 20.0:
        raise ValueError(f"gcode.tool.bottle_y_offset_mm 必须在 [-20, 20]mm, 得到: {bottle_y_offset_mm}")
    tool = ToolCfg(
        cutter_diameter_mm=float(tool_raw.get("cutter_diameter_mm", ToolCfg.cutter_diameter_mm)),
        bottle_diameter_mm=float(tool_raw.get("bottle_diameter_mm", ToolCfg.bottle_diameter_mm)),
        bottle_x_offset_mm=float(tool_raw.get("bottle_x_offset_mm", ToolCfg.bottle_x_offset_mm)),
        bottle_y_offset_mm=bottle_y_offset_mm,
    )
```

- [ ] **Step 5: cnc_path 应用偏移到 y_center**

`eit_ptlc/controller/cnc_path.py` 第 831 行（`y_center = (bbox_cm[1] + bbox_cm[3]) / 2.0`）改为：

```python
    y_center = (bbox_cm[1] + bbox_cm[3]) / 2.0 + gcode_cfg.tool.bottle_y_offset_mm / 10.0
```

（第 832 行 `y_half` 本 Task 不动，Task 2 再改。）

- [ ] **Step 6: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_cnc_path_offline.py::test_bottle_y_offset_shifts_only_collect_y -v`
Expected: PASS。

- [ ] **Step 7: 写 loader 偏移校验测试 + 跑**

在 `test_cnc_path_offline.py` 末尾追加：

```python
def test_loader_rejects_out_of_range_bottle_y_offset():
    from eit_ptlc.config.loader import _parse_gcode
    with pytest.raises(ValueError):
        _parse_gcode({"tool": {"bottle_y_offset_mm": 30.0}})
    # 边界内合法, 正常返回
    cfg = _parse_gcode({"tool": {"bottle_y_offset_mm": 1.0}})
    assert abs(cfg.tool.bottle_y_offset_mm - 1.0) < 1e-9
```

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_cnc_path_offline.py::test_loader_rejects_out_of_range_bottle_y_offset -v`
Expected: PASS。

- [ ] **Step 8: app.yaml 落真机偏移值**

`eit_ptlc/config/app.yaml` tool 段（当前 189-192）改为：

```yaml
  tool:
    cutter_diameter_mm: 2
    bottle_diameter_mm: 5
    bottle_x_offset_mm: 85
    bottle_y_offset_mm: 1.0           # 真机实测: 收集器偏 −Y ≈1mm, 补偿 +Y 侧残留(真机拨符号)
```

- [ ] **Step 9: 全套离线测试确认绿**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_cnc_path_offline.py eit_ptlc/tests/test_config_service_offline.py -v`
Expected: 全 PASS（默认 offset=0 → 既有几何不变）。

- [ ] **Step 10: 提交**

```bash
git add eit_ptlc/config/models.py eit_ptlc/config/loader.py eit_ptlc/controller/cnc_path.py eit_ptlc/config/app.yaml eit_ptlc/tests/test_cnc_path_offline.py
git commit -m "feat(collect-path): 新增 tool.bottle_y_offset_mm 收集器 Y 偏移补偿(只作用 g_cy, 默认0)"
```

---

### Task 2: `collect_expand_ratio`（乘性）→ `collect_margin_mm`（绝对, 扣桶口半径）

**Files:**
- Modify: `eit_ptlc/config/models.py:353-367`（GCodeCfg 换字段）
- Modify: `eit_ptlc/config/loader.py:427-429, 461`（_parse_gcode 换解析/校验/返回）
- Modify: `eit_ptlc/controller/cnc_path.py`（形参 713/922、docstring 724、注释 822、公式 823-832、log 874/880、透传 947）
- Modify: `eit_ptlc/config/app.yaml:188`（换键）
- Test: `eit_ptlc/tests/test_cnc_path_offline.py`（绝对膨胀 / 扣半径 / 下钳 / 负值拒绝）

**Interfaces:**
- Consumes: Task 1 的 `ToolCfg.bottle_y_offset_mm`、`_write_band_summary` helper。
- Produces: `GCodeCfg.collect_margin_mm: float`（默认 4.0）；`generate_scrape_arrays(..., collect_margin_mm: float | None)` 与 `CncPathController.generate_cnc_path(..., collect_margin_mm)`；收集 Y 半 span = `max(0, 带半高 + (collect_margin_mm − bottle_diameter_mm/2)/10)`（cm）。

- [ ] **Step 1: 写失败测试（绝对膨胀 + 扣半径 + 下钳 + 负值拒绝）**

在 `test_cnc_path_offline.py` 末尾追加（复用 Task 1 的 `_write_band_summary`）：

```python
def test_collect_margin_absolute_independent_of_band_height(tmp_path):
    """同 margin、不同带高 → 收集 Y span 之差 == 2×带半高之差（绝对膨胀, 与 margin 无关）。"""
    cfg = GCodeCfg()  # collect_margin_mm 默认 4.0
    s1 = _write_band_summary(tmp_path / "b1", {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})  # 带高1cm
    s2 = _write_band_summary(tmp_path / "b2", {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 3.5})  # 带高3cm
    a1 = generate_scrape_arrays(s1, "band_01", cfg, strategy="boustrophedon")
    a2 = generate_scrape_arrays(s2, "band_01", cfg, strategy="boustrophedon")
    span1 = max(a1.g_cy) - min(a1.g_cy)
    span2 = max(a2.g_cy) - min(a2.g_cy)
    assert abs((span2 - span1) - 20.0) < 1e-6   # 带半高差1cm → span 差 2×10mm=20mm


def test_collect_margin_equals_radius_gives_band_edge(tmp_path):
    """collect_margin_mm == 桶口半径 → y_half == 带半高 → 收集 Y span == 带高（真扣桶口半径）。"""
    cfg = GCodeCfg(collect_margin_mm=2.5)  # == bottle_diameter_mm(5)/2
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})  # 带高1cm=10mm
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="boustrophedon")
    assert abs((max(a.g_cy) - min(a.g_cy)) - 10.0) < 1e-6


def test_collect_margin_below_radius_clamps_to_zero(tmp_path):
    """margin < 桶口半径 → y_half 下钳到 0（单中心线, span 0）, 不出负值。"""
    cfg = GCodeCfg(collect_margin_mm=0.0)  # 0 < 半径2.5
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 0.7})  # 带半高0.1cm
    a = generate_scrape_arrays(s, "band_01", cfg, strategy="boustrophedon")
    assert abs(max(a.g_cy) - min(a.g_cy)) < 1e-6


def test_collect_margin_negative_rejected(tmp_path):
    """collect_margin_mm < 0 抛 ValueError。"""
    s = _write_band_summary(tmp_path, {"x_min": 1.0, "y_min": 0.5, "x_max": 16.0, "y_max": 1.5})
    with pytest.raises(ValueError):
        generate_scrape_arrays(s, "band_01", GCodeCfg(), strategy="boustrophedon", collect_margin_mm=-1.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_cnc_path_offline.py -k "collect_margin" -v`
Expected: FAIL —— `TypeError: GCodeCfg.__init__() got an unexpected keyword argument 'collect_margin_mm'` / `generate_scrape_arrays() got an unexpected keyword argument 'collect_margin_mm'`。

- [ ] **Step 3: GCodeCfg 换字段**

`eit_ptlc/config/models.py` GCodeCfg 中第 364 行 `collect_expand_ratio: float = 1.0` 改为：

```python
    collect_margin_mm: float = 4.0
```

（`scrape_keep_ratio` 上一行保持不变。）

- [ ] **Step 4: loader 换解析/校验/返回**

`eit_ptlc/config/loader.py` `_parse_gcode`：把第 427-429 行

```python
    collect_expand_ratio = float(d.get("collect_expand_ratio", GCodeCfg.collect_expand_ratio))
    if not (1.0 <= collect_expand_ratio <= 2.0):
        raise ValueError(f"gcode.collect_expand_ratio 必须在 [1.0, 2.0], 得到: {collect_expand_ratio}")
```

替换为：

```python
    collect_margin_mm = float(d.get("collect_margin_mm", GCodeCfg.collect_margin_mm))
    if collect_margin_mm < 0.0:
        raise ValueError(f"gcode.collect_margin_mm 必须 ≥ 0, 得到: {collect_margin_mm}")
```

并把第 461 行 `collect_expand_ratio=collect_expand_ratio,` 改为：

```python
        collect_margin_mm=collect_margin_mm,
```

- [ ] **Step 5: cnc_path 换公式（含 Task 1 的 y_center 偏移）**

`eit_ptlc/controller/cnc_path.py`：

(a) 主接口签名第 713 行 `collect_expand_ratio: float | None = None,` 改为 `collect_margin_mm: float | None = None,`。

(b) docstring 第 724-726 行的 `collect_expand_ratio: ...` 段改为：

```python
        collect_margin_mm: 收集路径 Y 方向绝对余量(mm)覆盖(None 时取 gcode_cfg.collect_margin_mm)。
            收集 Y 半span = 带半高 + (collect_margin_mm − 桶口半径)/10; 桶口半径 = bottle_diameter_mm/2。
```

(c) 第 822 行注释 `# 无 Z 粉桶：...Y 向按 collect_expand_ratio 全局放大。` 改为：

```python
    # 无 Z 粉桶：路径保证桶壁永不朝 x_max 开口边推粉。Y 向 = 带半高 + 绝对余量 − 桶口半径, 中心加装配偏移。
```

(d) 第 823-832 行整块（`effective_collect_expand` 解析 + 校验 + y_center/y_half）替换为：

```python
    effective_collect_margin_mm = (
        float(collect_margin_mm) if collect_margin_mm is not None
        else float(gcode_cfg.collect_margin_mm)
    )
    if effective_collect_margin_mm < 0.0:
        raise ValueError(
            f"collect_margin_mm 必须 ≥ 0, 得到: {effective_collect_margin_mm}"
        )
    mouth_radius_cm = gcode_cfg.tool.bottle_diameter_mm / 2.0 / 10.0
    y_center = (bbox_cm[1] + bbox_cm[3]) / 2.0 + gcode_cfg.tool.bottle_y_offset_mm / 10.0
    y_half = max(
        0.0,
        (bbox_cm[3] - bbox_cm[1]) / 2.0 + effective_collect_margin_mm / 10.0 - mouth_radius_cm,
    )
```

(e) log：第 874 行格式串末尾 `"collect=%s(tail=%.1fcm) collect_expand=%.2f",` 改为 `"collect=%s(tail=%.1fcm) collect_margin=%.1fmm y_off=%.1fmm",`；第 880 行参数 `gcode_cfg.tool.bottle_x_offset_mm / 10.0, effective_collect_expand,` 改为：

```python
        gcode_cfg.tool.bottle_x_offset_mm / 10.0, effective_collect_margin_mm, gcode_cfg.tool.bottle_y_offset_mm,
```

(f) `CncPathController.generate_cnc_path`：第 922 行形参 `collect_expand_ratio: float | None = None,` 改为 `collect_margin_mm: float | None = None,`；第 947 行 `collect_expand_ratio=collect_expand_ratio,` 改为 `collect_margin_mm=collect_margin_mm,`。

- [ ] **Step 6: 跑收集测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_cnc_path_offline.py -k "collect_margin" -v`
Expected: 4 项全 PASS。

- [ ] **Step 7: app.yaml 换键**

`eit_ptlc/config/app.yaml` 第 188 行 `collect_expand_ratio: 1.2` 改为：

```yaml
  collect_margin_mm: 4.0             # 收集 Y 绝对余量(mm), 真扣桶口半径; net每侧=4.0−2.5=板边外+1.5mm
```

- [ ] **Step 8: 全套离线测试确认绿**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_cnc_path_offline.py eit_ptlc/tests/test_config_service_offline.py -v`
Expected: 全 PASS。若有其它引用 `collect_expand_ratio` 的失败，全仓再 grep 确认已无残留：`git grep -n collect_expand_ratio`（应无输出）。

- [ ] **Step 9: 提交**

```bash
git add eit_ptlc/config/models.py eit_ptlc/config/loader.py eit_ptlc/controller/cnc_path.py eit_ptlc/config/app.yaml eit_ptlc/tests/test_cnc_path_offline.py
git commit -m "feat(collect-path): collect_expand_ratio(乘性)→collect_margin_mm(绝对, 真扣桶口半径)"
```

---

### Task 3: 真机配置校准 `bottle_x_offset_mm: 85 → 90`（纯 app.yaml）

**Files:**
- Modify: `eit_ptlc/config/app.yaml:192`（tool.bottle_x_offset_mm）

**Interfaces:**
- Consumes: 无代码接口变化（既有 `bottle_x_offset_mm` 语义 = 拖尾长度 + 收集器 X 补偿）。
- Produces: 无新接口；仅拖尾段覆盖到板 x_max（top-right/flip_x 下即机床 −X 端），治拖尾堆积。

- [ ] **Step 1: 改配置值**

`eit_ptlc/config/app.yaml` tool 段 `bottle_x_offset_mm: 85` 改为：

```yaml
    bottle_x_offset_mm: 90            # 真机实测铣刀↔收集器 X 间距≈90mm(补偿拖尾够到 x_max, 治 −X 端堆积)
```

- [ ] **Step 2: 全套离线测试确认绿**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_cnc_path_offline.py eit_ptlc/tests/test_config_service_offline.py -v`
Expected: 全 PASS（测试用 GCodeCfg() 默认 85，不受 app.yaml 影响；此步仅确认配置可加载无回归）。

- [ ] **Step 3: 提交**

```bash
git add eit_ptlc/config/app.yaml
git commit -m "chore(collect-path): bottle_x_offset_mm 85→90 真机校准(拖尾够到 x_max)"
```

---

## Self-Review

**1. Spec coverage:**
- 新增 `bottle_y_offset_mm`（模型/loader/cnc_path/app.yaml + 校验 ≤20）→ Task 1 全覆盖。✔
- `collect_expand_ratio`→`collect_margin_mm`（绝对 + 扣半径 + 下钳 + 校验 ≥0 + 4 文件改）→ Task 2 全覆盖。✔
- 真机配置落点：`bottle_x_offset_mm 85→90`（Task 3）、`bottle_y_offset_mm 1.0`（Task 1 Step 8）、`collect_margin_mm 4.0`（Task 2 Step 7）。✔
- 测试"正交性铁证"5 项：偏移只平移 g_cy（Task 1）、余量绝对（Task 2）、扣半径（Task 2）、默认 offset=0 隐含在 Task 1 orthogonality 的 a0 基线 + Step 9 全套绿、下钳（Task 2）、校验负值/超限（Task 1+2）。✔
- PLC 契约 400 点不变：各 Task 只改 Y 标量项，不改点数/结构。✔

**2. Placeholder scan:** 无 TBD/TODO；每个 code step 均含完整替换代码与精确行锚点。✔

**3. Type consistency:** `collect_margin_mm: float | None`（cnc_path 两处签名一致）；`GCodeCfg.collect_margin_mm: float`；`ToolCfg.bottle_y_offset_mm: float`；`_parse_gcode(d) -> GCodeCfg` 返回字段名与 model 字段名一致（`collect_margin_mm`、`bottle_y_offset_mm`）；helper `_write_band_summary` 在 Task 1 定义、Task 2 复用（同文件）。✔
