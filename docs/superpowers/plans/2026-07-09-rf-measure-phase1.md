# Rf 测量 Phase 1（scrape 侧几何 + spot 检测核心）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建一个纯离线、可单测的 Rf 计算核心：板归一化坐标映射 + spot 检测（合成图夹具）+ `Rf = D_s / D_f`，不接 PLC/相机/真机。

**Architecture:** 新增纯模块 `eit_ptlc/controller/rf_measure.py`：`to_plate_uv`（bbox 仿射把像素→板归一化 [0,1]²，复用现有已去旋转/透视的分析帧，故轴对齐仿射足够，单应留作后续 YAGNI）→ `detect_spots`（UV 暗斑打亮底，阈值+形态学+连通域，返回板归一化中心）→ `compute_rf`（`D_s = (spot_axis − origin_frac)*dir`，`Rf = D_s/D_f`）。再加一个调试叠加 CLI `eit_ptlc/tools/rf_spot_check.py` 便于真机图肉眼核验。origin 用伺服常量 `origin_frac`、`D_f` 用外部传入常量，二者的来源/存储属 Phase 2，不在本计划。

**Tech Stack:** Python 3.11、cv2(OpenCV)、numpy、pytest。imaging 导入按 `vision_quality.py` 的 lazy/guarded 风格。

## Global Constraints

- Python 解释器: `E:\Anaconda\envs\platformupper\python.exe`（conda env `platformupper`，3.11）。
- 全部离线：不依赖 PLC / 相机 / 真机 / 网络。测试用 numpy/cv2 合成图，确定性断言。
- 文件放置（用户洁癖）：核心逻辑进 `eit_ptlc/controller/`，命令行工具进 `eit_ptlc/tools/`，测试进 `eit_ptlc/tests/` 且命名 `test_*_offline.py`。
- imaging 库导入 lazy/guarded（`import cv2` 放函数内），模块顶层可无 cv2 导入。
- 坐标约定：板归一化 `u ∈ [0,1]` 左→右，`v ∈ [0,1]` 上→下（图像惯例）。
- 迁移量正负：`migration = (coord − origin_frac) * direction`，`direction ∈ {+1,-1}`，取号使斑点/前沿迁移为正。`D_f` 传入为正幅值。
- TDD：每任务先写失败测试→跑挂→最小实现→跑过→提交。频繁提交。
- 分支 `codex/ui-upper-next`，沿用其提交风格（中文 subject + Co-Authored-By 尾注）。

---

### Task 1: 板归一化坐标映射 `to_plate_uv`

**Files:**
- Create: `eit_ptlc/controller/rf_measure.py`
- Test: `eit_ptlc/tests/test_rf_measure_offline.py`

**Interfaces:**
- Consumes: 无（本任务起头）。
- Produces:
  - `to_plate_uv(px: float, py: float, plate_bbox: dict[str, int]) -> tuple[float, float]`
    —— `plate_bbox = {"x","y","w","h"}`（复用 `vision_quality.QualityMetrics.plate_bbox_px` 同结构）。返回 `(u, v)`，`u=(px-x)/w`，`v=(py-y)/h`。`w<=0` 或 `h<=0` 抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

在 `eit_ptlc/tests/test_rf_measure_offline.py`:

```python
"""离线单测: Rf 测量核心 (rf_measure)。全部合成/纯算, 无相机无 PLC。"""
import math
import pytest

from eit_ptlc.controller import rf_measure


class TestToPlateUv:
    def test_corners_map_to_unit_square(self):
        bbox = {"x": 100, "y": 200, "w": 400, "h": 800}
        assert rf_measure.to_plate_uv(100, 200, bbox) == (0.0, 0.0)
        assert rf_measure.to_plate_uv(500, 1000, bbox) == (1.0, 1.0)

    def test_center_maps_to_half(self):
        bbox = {"x": 0, "y": 0, "w": 200, "h": 100}
        u, v = rf_measure.to_plate_uv(100, 50, bbox)
        assert u == pytest.approx(0.5)
        assert v == pytest.approx(0.5)

    def test_zero_size_raises(self):
        with pytest.raises(ValueError):
            rf_measure.to_plate_uv(10, 10, {"x": 0, "y": 0, "w": 0, "h": 100})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_measure_offline.py -v`
Expected: FAIL —— `ModuleNotFoundError: eit_ptlc.controller.rf_measure` 或 `AttributeError: to_plate_uv`。

- [ ] **Step 3: 写最小实现**

在 `eit_ptlc/controller/rf_measure.py`:

```python
"""Rf 测量核心 (纯算 + spot 检测)
================================
把两段迁移距离都放进同一「板归一化坐标系」→ 尺度约掉 → Rf = D_s / D_f。
坐标: u∈[0,1] 左→右, v∈[0,1] 上→下 (图像惯例)。
本模块不做 D_f/origin_frac 的来源或存储 (属 Phase 2), 只消费传入常量。
imaging 导入 lazy/guarded, 顶层无 cv2 依赖。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


def to_plate_uv(px: float, py: float, plate_bbox: dict[str, int]) -> tuple[float, float]:
    """把图像像素 (px,py) 映到板归一化 (u,v)。

    plate_bbox: {"x","y","w","h"} (同 vision_quality.plate_bbox_px)。
    复用现有去旋转/透视归一化后的分析帧, 故轴对齐仿射足够。
    """
    w = plate_bbox["w"]
    h = plate_bbox["h"]
    if w <= 0 or h <= 0:
        raise ValueError(f"plate_bbox 宽高须为正: w={w} h={h}")
    u = (px - plate_bbox["x"]) / w
    v = (py - plate_bbox["y"]) / h
    return (u, v)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_measure_offline.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/controller/rf_measure.py eit_ptlc/tests/test_rf_measure_offline.py
git commit -m "feat(rf): to_plate_uv 板归一化坐标映射 (bbox 仿射)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 迁移量与 Rf 纯计算 `migration` / `compute_rf`

**Files:**
- Modify: `eit_ptlc/controller/rf_measure.py`
- Test: `eit_ptlc/tests/test_rf_measure_offline.py`

**Interfaces:**
- Consumes: 无（纯算，独立于 Task 1）。
- Produces:
  - `@dataclass SpotHit` 字段: `u: float`, `v: float`, `area_frac: float`, `center_px: tuple[float, float]`。
  - `migration(coord: float, origin_frac: float, direction: int) -> float` = `(coord - origin_frac) * direction`。
  - `@dataclass RfResult` 字段: `index: int`, `u: float`, `v: float`, `d_s: float`, `rf: float | None`。
  - `compute_rf(spots: list[SpotHit], *, origin_frac: float, d_f: float, axis: str = "v", direction: int = -1) -> list[RfResult]`
    —— `axis ∈ {"u","v"}` 选展开方向轴分量；`d_s = migration(coord, origin_frac, direction)`；`rf = d_s / d_f` 若 `d_f > 0` 否则 `None`；`axis` 非法抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

追加到 `eit_ptlc/tests/test_rf_measure_offline.py`:

```python
class TestMigrationAndRf:
    def test_migration_direction_negative(self):
        # origin 在 v=0.9 (板下方), 斑点在 v=0.3 (上方), 向上迁移 direction=-1 → 正
        assert rf_measure.migration(0.3, 0.9, -1) == pytest.approx(0.6)

    def test_migration_direction_positive(self):
        assert rf_measure.migration(0.7, 0.2, 1) == pytest.approx(0.5)

    def test_compute_rf_basic(self):
        spots = [
            rf_measure.SpotHit(u=0.5, v=0.3, area_frac=0.001, center_px=(0.0, 0.0)),
            rf_measure.SpotHit(u=0.5, v=0.6, area_frac=0.001, center_px=(0.0, 0.0)),
        ]
        # origin_frac=0.9 (v), d_f=0.8 (前沿到 v=0.1), direction=-1
        res = rf_measure.compute_rf(spots, origin_frac=0.9, d_f=0.8, axis="v", direction=-1)
        assert [round(r.d_s, 3) for r in res] == [0.6, 0.3]
        assert [round(r.rf, 3) for r in res] == [0.75, 0.375]
        assert [r.index for r in res] == [0, 1]

    def test_compute_rf_zero_df_gives_none(self):
        spots = [rf_measure.SpotHit(u=0.5, v=0.3, area_frac=0.001, center_px=(0.0, 0.0))]
        res = rf_measure.compute_rf(spots, origin_frac=0.9, d_f=0.0)
        assert res[0].rf is None

    def test_compute_rf_axis_u(self):
        spots = [rf_measure.SpotHit(u=0.4, v=0.5, area_frac=0.001, center_px=(0.0, 0.0))]
        res = rf_measure.compute_rf(spots, origin_frac=0.1, d_f=0.6, axis="u", direction=1)
        assert res[0].d_s == pytest.approx(0.3)
        assert res[0].rf == pytest.approx(0.5)

    def test_compute_rf_bad_axis_raises(self):
        with pytest.raises(ValueError):
            rf_measure.compute_rf([], origin_frac=0.5, d_f=0.5, axis="z")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_measure_offline.py::TestMigrationAndRf -v`
Expected: FAIL —— `AttributeError: SpotHit` / `migration` / `compute_rf`。

- [ ] **Step 3: 写最小实现**

追加到 `eit_ptlc/controller/rf_measure.py`（在 `to_plate_uv` 之后）:

```python
@dataclass
class SpotHit:
    """一个斑点在板归一化系里的位置。"""
    u: float
    v: float
    area_frac: float           # blob 面积 / 板面积
    center_px: tuple[float, float]  # 原图绝对像素中心 (调试用)


@dataclass
class RfResult:
    index: int
    u: float
    v: float
    d_s: float
    rf: float | None           # d_f<=0 时为 None


def migration(coord: float, origin_frac: float, direction: int) -> float:
    """迁移量 = (coord - origin_frac) * direction。取号使迁移为正。"""
    return (coord - origin_frac) * direction


def compute_rf(
    spots: list[SpotHit],
    *,
    origin_frac: float,
    d_f: float,
    axis: str = "v",
    direction: int = -1,
) -> list[RfResult]:
    """由斑点板归一化位置算 Rf。

    axis: 展开方向轴 ("u" 或 "v")。origin_frac: 原点在该轴的坐标。
    d_f: 前沿迁移幅值 (板归一化, 正)。direction: 迁移取号 (+1/-1)。
    """
    if axis not in ("u", "v"):
        raise ValueError(f"axis 须为 'u' 或 'v', got {axis!r}")
    results: list[RfResult] = []
    for i, s in enumerate(spots):
        coord = s.v if axis == "v" else s.u
        d_s = migration(coord, origin_frac, direction)
        rf = (d_s / d_f) if d_f > 0 else None
        results.append(RfResult(index=i, u=s.u, v=s.v, d_s=d_s, rf=rf))
    return results
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_measure_offline.py -v`
Expected: PASS（Task1 的 3 + 本任务 6 = 9 passed）。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/controller/rf_measure.py eit_ptlc/tests/test_rf_measure_offline.py
git commit -m "feat(rf): migration + compute_rf 纯计算 (Rf=D_s/D_f, 板归一化)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: spot 检测 `detect_spots`（合成图夹具）

**Files:**
- Modify: `eit_ptlc/controller/rf_measure.py`
- Test: `eit_ptlc/tests/test_rf_measure_offline.py`

**Interfaces:**
- Consumes: `to_plate_uv`（Task 1）、`SpotHit`（Task 2）。
- Produces:
  - `detect_spots(image_bgr, plate_bbox: dict[str, int], *, min_area_frac: float = 1e-4, max_area_frac: float = 0.05, darkness_k: float = 2.0) -> list[SpotHit]`
    —— `image_bgr` 为 numpy BGR 数组（`cv2.imread` 结果）。在 `plate_bbox` 裁剪区内把**比局部均值暗 `darkness_k*std` 以上**的像素二值化→形态学开→连通域→按面积占比 `[min_area_frac, max_area_frac]` 过滤→质心。返回按展开轴排序前的 `SpotHit` 列表（`center_px` 为原图绝对坐标，`u,v` 经 `to_plate_uv`）。无 cv2 时抛 `RuntimeError`。

- [ ] **Step 1: 写失败测试**

追加到 `eit_ptlc/tests/test_rf_measure_offline.py`（顶部补 `import numpy as np` 与 cv2 skip 守卫）:

在文件 import 段追加:
```python
import numpy as np

cv2 = pytest.importorskip("cv2")
```

追加测试类:
```python
def _synth_plate(w=400, h=600, spots_uv=((0.3, 0.4), (0.6, 0.7))):
    """造一张 UV 风格合成图: 亮绿底 + 暗斑。返回 (image_bgr, plate_bbox)。"""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 1] = 200  # 绿底 (BGR 的 G 通道)
    r = 12
    for (u, v) in spots_uv:
        cx, cy = int(u * w), int(v * h)
        cv2.circle(img, (cx, cy), r, (0, 40, 0), -1)  # 暗斑
    bbox = {"x": 0, "y": 0, "w": w, "h": h}
    return img, bbox


class TestDetectSpots:
    def test_recovers_known_spots(self):
        img, bbox = _synth_plate(spots_uv=((0.3, 0.4), (0.6, 0.7)))
        hits = rf_measure.detect_spots(img, bbox)
        assert len(hits) == 2
        found = sorted((round(h.u, 1), round(h.v, 1)) for h in hits)
        assert found == [(0.3, 0.4), (0.6, 0.7)]

    def test_area_filter_rejects_tiny_noise(self):
        img, bbox = _synth_plate(spots_uv=((0.5, 0.5),))
        # 加一个 1px 噪点, 应被 min_area_frac 滤掉
        img[10, 10] = (0, 40, 0)
        hits = rf_measure.detect_spots(img, bbox)
        assert len(hits) == 1
        assert hits[0].u == pytest.approx(0.5, abs=0.05)

    def test_center_px_absolute(self):
        img, bbox = _synth_plate(w=400, h=600, spots_uv=((0.5, 0.5),))
        hits = rf_measure.detect_spots(img, bbox)
        cx, cy = hits[0].center_px
        assert cx == pytest.approx(200, abs=6)
        assert cy == pytest.approx(300, abs=6)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_measure_offline.py::TestDetectSpots -v`
Expected: FAIL —— `AttributeError: detect_spots`。

- [ ] **Step 3: 写最小实现**

追加到 `eit_ptlc/controller/rf_measure.py`:

```python
def detect_spots(
    image_bgr,
    plate_bbox: dict[str, int],
    *,
    min_area_frac: float = 1e-4,
    max_area_frac: float = 0.05,
    darkness_k: float = 2.0,
) -> list[SpotHit]:
    """在 plate_bbox 内检测 UV 暗斑 (暗打亮底), 返回板归一化中心。

    algorithm: 裁剪→灰度→比局部均值暗 darkness_k*std 的像素二值化→
    形态学开去噪→连通域→按面积占比过滤→质心。
    """
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - 环境保证有 cv2
        raise RuntimeError("detect_spots 需要 cv2/numpy") from exc

    x, y, w, h = plate_bbox["x"], plate_bbox["y"], plate_bbox["w"], plate_bbox["h"]
    if w <= 0 or h <= 0:
        raise ValueError(f"plate_bbox 宽高须为正: w={w} h={h}")
    roi = image_bgr[y : y + h, x : x + w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    mean = float(gray.mean())
    std = float(gray.std())
    thresh_val = max(0.0, mean - darkness_k * std)
    # 暗斑 = 低于阈值
    dark = (gray < thresh_val).astype(np.uint8) * 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    opened = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)

    num, labels, stats, centroids = cv2.connectedComponentsWithStats(opened, connectivity=8)
    plate_area = float(w * h)
    hits: list[SpotHit] = []
    for lbl in range(1, num):  # 0 = 背景
        area = float(stats[lbl, cv2.CC_STAT_AREA])
        frac = area / plate_area
        if frac < min_area_frac or frac > max_area_frac:
            continue
        cx_roi, cy_roi = centroids[lbl]
        abs_px = (x + float(cx_roi), y + float(cy_roi))
        u, v = to_plate_uv(abs_px[0], abs_px[1], plate_bbox)
        hits.append(SpotHit(u=u, v=v, area_frac=frac, center_px=abs_px))
    return hits
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_measure_offline.py -v`
Expected: PASS（9 + 3 = 12 passed）。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/controller/rf_measure.py eit_ptlc/tests/test_rf_measure_offline.py
git commit -m "feat(rf): detect_spots UV 暗斑检测 (阈值+形态学+连通域, 合成图夹具)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 端到端 `analyze_rf`（检测→Rf，含轴排序）

**Files:**
- Modify: `eit_ptlc/controller/rf_measure.py`
- Test: `eit_ptlc/tests/test_rf_measure_offline.py`

**Interfaces:**
- Consumes: `detect_spots`（Task 3）、`compute_rf`（Task 2）。
- Produces:
  - `analyze_rf(image_bgr, plate_bbox: dict[str, int], *, origin_frac: float, d_f: float, axis: str = "v", direction: int = -1, spot_params: dict | None = None) -> list[RfResult]`
    —— 调 `detect_spots`（`spot_params` 透传其关键字）→ `compute_rf` → 结果**按展开轴迁移量 `d_s` 升序**返回（离原点近的在前）。`spot_params=None` 用默认。

- [ ] **Step 1: 写失败测试**

追加到 `eit_ptlc/tests/test_rf_measure_offline.py`:

```python
class TestAnalyzeRf:
    def test_end_to_end_two_spots_sorted(self):
        # v=0.4 与 v=0.7; origin_frac=0.9, direction=-1 → d_s = 0.5 与 0.2
        # 期望按 d_s 升序: 先 0.2 (v=0.7), 后 0.5 (v=0.4)
        img, bbox = _synth_plate(spots_uv=((0.5, 0.4), (0.5, 0.7)))
        res = rf_measure.analyze_rf(
            img, bbox, origin_frac=0.9, d_f=0.8, axis="v", direction=-1,
        )
        assert len(res) == 2
        assert res[0].d_s < res[1].d_s
        assert res[0].v == pytest.approx(0.7, abs=0.05)
        assert res[1].v == pytest.approx(0.4, abs=0.05)
        assert res[1].rf == pytest.approx(0.5 / 0.8, abs=0.02)

    def test_spot_params_passthrough(self):
        img, bbox = _synth_plate(spots_uv=((0.5, 0.5),))
        # 把 min_area_frac 抬到 1.0 → 应过滤掉所有斑点
        res = rf_measure.analyze_rf(
            img, bbox, origin_frac=0.9, d_f=0.8,
            spot_params={"min_area_frac": 1.0},
        )
        assert res == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_measure_offline.py::TestAnalyzeRf -v`
Expected: FAIL —— `AttributeError: analyze_rf`。

- [ ] **Step 3: 写最小实现**

追加到 `eit_ptlc/controller/rf_measure.py`:

```python
def analyze_rf(
    image_bgr,
    plate_bbox: dict[str, int],
    *,
    origin_frac: float,
    d_f: float,
    axis: str = "v",
    direction: int = -1,
    spot_params: dict | None = None,
) -> list[RfResult]:
    """端到端: 检测斑点 → 算 Rf → 按迁移量 d_s 升序返回。"""
    params = spot_params or {}
    spots = detect_spots(image_bgr, plate_bbox, **params)
    results = compute_rf(
        spots, origin_frac=origin_frac, d_f=d_f, axis=axis, direction=direction,
    )
    results.sort(key=lambda r: r.d_s)
    # 排序后重编 index 以反映输出顺序
    for new_i, r in enumerate(results):
        r.index = new_i
    return results
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_measure_offline.py -v`
Expected: PASS（12 + 2 = 14 passed）。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/controller/rf_measure.py eit_ptlc/tests/test_rf_measure_offline.py
git commit -m "feat(rf): analyze_rf 端到端 (检测→Rf→按 d_s 升序)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 调试叠加 CLI `rf_spot_check`（真机图肉眼核验）

**Files:**
- Create: `eit_ptlc/tools/rf_spot_check.py`
- Test: `eit_ptlc/tests/test_rf_spot_check_offline.py`

**Interfaces:**
- Consumes: `rf_measure.analyze_rf`（Task 4）。
- Produces:
  - `render_overlay(image_bgr, plate_bbox, results, *, origin_frac, axis="v") -> np.ndarray`
    —— 在图上画板 bbox、原点线、各斑点圈 + `Rf=` 文本，返回叠加图。
  - CLI: `python -m eit_ptlc.tools.rf_spot_check <image> --x --y --w --h --origin-frac --d-f [--axis v] [--direction -1] [--out overlay.png]`，打印每斑点 `u,v,d_s,rf` 并落叠加图。

用途：Phase 0 spike 的**肉眼核验**入口——相机锁定后拿真 UV 板图跑它，确认 spot 分割/排序对。测试只验合成图路径与叠加图非空（真机图人工核验，不入自动化）。

- [ ] **Step 1: 写失败测试**

在 `eit_ptlc/tests/test_rf_spot_check_offline.py`:

```python
"""离线测: rf_spot_check 调试叠加 (合成图路径)。"""
import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from eit_ptlc.tools import rf_spot_check
from eit_ptlc.controller import rf_measure


def _synth(w=400, h=600, spots_uv=((0.5, 0.5),)):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 1] = 200
    for (u, v) in spots_uv:
        cv2.circle(img, (int(u * w), int(v * h)), 12, (0, 40, 0), -1)
    return img, {"x": 0, "y": 0, "w": w, "h": h}


def test_render_overlay_returns_same_shape():
    img, bbox = _synth()
    res = rf_measure.analyze_rf(img, bbox, origin_frac=0.9, d_f=0.8)
    overlay = rf_spot_check.render_overlay(img, bbox, res, origin_frac=0.9)
    assert overlay.shape == img.shape
    # 叠加应改变部分像素 (画了东西)
    assert bool((overlay != img).any())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_spot_check_offline.py -v`
Expected: FAIL —— `ModuleNotFoundError: eit_ptlc.tools.rf_spot_check`。

- [ ] **Step 3: 写最小实现**

在 `eit_ptlc/tools/rf_spot_check.py`:

```python
"""rf_spot_check —— Rf spot 检测调试叠加 CLI。

相机锁定后拿真 UV 板图肉眼核验 spot 分割/排序/Rf。用法::

    python -m eit_ptlc.tools.rf_spot_check plate.png \\
        --x 100 --y 80 --w 900 --h 900 --origin-frac 0.9 --d-f 0.8 \\
        [--axis v] [--direction -1] [--out overlay.png]
"""

from __future__ import annotations

import argparse
import sys

from eit_ptlc.controller import rf_measure


def render_overlay(image_bgr, plate_bbox, results, *, origin_frac, axis="v"):
    """在图上画 bbox / 原点线 / 斑点圈 + Rf 文本, 返回叠加图。"""
    import cv2

    out = image_bgr.copy()
    x, y, w, h = plate_bbox["x"], plate_bbox["y"], plate_bbox["w"], plate_bbox["h"]
    cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), 2)
    # 原点线 (沿非展开轴画一条)
    if axis == "v":
        oy = int(y + origin_frac * h)
        cv2.line(out, (x, oy), (x + w, oy), (255, 0, 0), 2)
    else:
        ox = int(x + origin_frac * w)
        cv2.line(out, (ox, y), (ox, y + h), (255, 0, 0), 2)
    for r in results:
        cx, cy = int(x + r.u * w), int(y + r.v * h)
        cv2.circle(out, (cx, cy), 10, (0, 255, 255), 2)
        label = f"Rf={r.rf:.2f}" if r.rf is not None else "Rf=NA"
        cv2.putText(out, label, (cx + 12, cy), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rf spot 检测调试叠加")
    p.add_argument("image")
    p.add_argument("--x", type=int, required=True)
    p.add_argument("--y", type=int, required=True)
    p.add_argument("--w", type=int, required=True)
    p.add_argument("--h", type=int, required=True)
    p.add_argument("--origin-frac", type=float, required=True)
    p.add_argument("--d-f", type=float, required=True)
    p.add_argument("--axis", default="v", choices=["u", "v"])
    p.add_argument("--direction", type=int, default=-1, choices=[-1, 1])
    p.add_argument("--out", default="rf_overlay.png")
    args = p.parse_args(argv)

    import cv2

    img = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if img is None:
        print(f"无法读取图像: {args.image}", file=sys.stderr)
        return 2
    bbox = {"x": args.x, "y": args.y, "w": args.w, "h": args.h}
    results = rf_measure.analyze_rf(
        img, bbox, origin_frac=args.origin_frac, d_f=args.d_f,
        axis=args.axis, direction=args.direction,
    )
    for r in results:
        rf_str = f"{r.rf:.3f}" if r.rf is not None else "NA"
        print(f"idx={r.index} u={r.u:.3f} v={r.v:.3f} d_s={r.d_s:.3f} rf={rf_str}")
    overlay = render_overlay(img, bbox, results, origin_frac=args.origin_frac, axis=args.axis)
    cv2.imwrite(args.out, overlay)
    print(f"overlay={args.out} spots={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_spot_check_offline.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/tools/rf_spot_check.py eit_ptlc/tests/test_rf_spot_check_offline.py
git commit -m "feat(rf): rf_spot_check 调试叠加 CLI (真机图肉眼核验入口)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 全套离线回归 + 模块 docstring 收口

**Files:**
- Modify: `eit_ptlc/controller/rf_measure.py`（仅补顶部 `Usage` docstring，不改逻辑）

- [ ] **Step 1: 跑本计划全部离线测试**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_rf_measure_offline.py eit_ptlc/tests/test_rf_spot_check_offline.py -v`
Expected: PASS（14 + 1 = 15 passed）。

- [ ] **Step 2: 跑既有视觉套确认零回归**

Run: `E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_vision_quality.py eit_ptlc/tests/test_photoscrape_four_stage_offline.py -v`
Expected: PASS（全绿，本计划纯新增未触碰既有模块）。

- [ ] **Step 3: 补模块用法 docstring**

在 `eit_ptlc/controller/rf_measure.py` 顶部 docstring 末尾追加:

```python
#     Usage::
#
#         from eit_ptlc.controller.rf_measure import analyze_rf
#         results = analyze_rf(
#             image_bgr, plate_bbox,
#             origin_frac=0.9,   # 伺服常量 (Phase 2 提供)
#             d_f=0.8,           # 前沿迁移幅值 (Phase 2 标定)
#             axis="v", direction=-1,
#         )
#         for r in results:
#             print(r.index, r.rf)
```

（把上述作为普通三引号内文本并入现有 docstring，不要用 `#` 注释——此处 `#` 仅为计划排版。）

- [ ] **Step 4: 提交**

```bash
git add eit_ptlc/controller/rf_measure.py
git commit -m "docs(rf): rf_measure 用法 docstring 收口 + Phase1 全绿

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 本计划边界（明确不做，属后续 plan）

- **Phase 2**: `origin_frac` 来源（伺服位置换算 vs 一次实测）+ `D_f` 一次性标定流程（标记湿态前沿板）+ 二者的 `config/` 存储（每通道/全局）。
- **Phase 3**: 接入 photoscrape 主管线（`vision_quality`/`vision_controller` 消费 `analyze_rf`）+ summary 契约落盘 + 前端展示。
- **Phase 0 真机验证**: 相机锁定后用 `rf_spot_check` 跑真 UV 板图肉眼核验 spot 分割——本计划已交付该 CLI 工具，验证动作本身待真机。
- 单应/透视映射（`to_plate_uv` 现为 bbox 仿射）：仅当真机图证明去旋转后仍有显著透视时再加，YAGNI。

## Self-Review

- **Spec 覆盖**: 设计 §4 公式→Task 2；§5.1 origin(板归一化投影)→Task 1 + `origin_frac` 参数（来源属 Phase 2）；§5.2 spot 检测→Task 3；§5.4 Rf 组装→Task 4；§5.5 spike 肉眼核验入口→Task 5。§5.3 `D_f` 标定 / §5 存储 = 明确划入 Phase 2（见边界节）。
- **占位扫描**: 无 TBD/TODO；每步含完整代码与可跑命令。
- **类型一致**: `SpotHit`/`RfResult` 字段贯穿 Task 2→3→4→5；`to_plate_uv`/`detect_spots`/`compute_rf`/`analyze_rf`/`render_overlay` 签名前后一致；`plate_bbox` 键 `{"x","y","w","h"}` 全程统一（对齐 `vision_quality.plate_bbox_px`）。
