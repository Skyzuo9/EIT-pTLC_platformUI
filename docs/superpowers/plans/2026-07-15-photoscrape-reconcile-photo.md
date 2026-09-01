# 包2: 刮后对账照片 + 共享基建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每次刮取产出"说好的 vs 刮到的"对账照片 `scraped_annotated.png`,并落地它依赖的三条契约:坐标映射单一真源(C-4)、归一化参数持久化+帧回放(C-1/C-3)、preview payload 落盘(C-5)。

**Architecture:** pass 循环后补拍 `scraped.jpg` → 用 summary 里持久化的归一化参数**回放**(禁重新检测)到与 `after_normalized.jpg` 同帧 → 用 cnc_path 动作落盘的同一份 `preview_payload.json` 渲染叠加(never regenerates)。坐标映射收编进新模块 `plate_coords.py`,三处消费者(vision_controller / sketch_path / cnc_preview)引用同一实现。

**Tech Stack:** Python (numpy/cv2, FastAPI 之外的 controller 层) + ptlc.script/v1 YAML 流程 + pytest 离线套件。

**Spec:** `docs/superpowers/specs/2026-07-15-photoscrape-scrape-closedloop-design.md`(契约编号 C-1..C-5 均指此文件 §4)。

## Global Constraints

- **宁可无图,不可错帧**:回放参数缺失(旧 summary)或回放后尺寸与 `frame_size` 不符 → raise,调用方跳过叠加只留原图 + log。
- **回放禁止任何重新检测**:`replay_normalization` 路径中不得出现 `green_plate_mask` / `detect_plate` / `minAreaRect`。
- **对账渲染只消费落盘的 `preview_payload.json`**,不重新计算数组、不重新生成路径(维持 cnc_preview "never regenerates" 契约)。
- **补拍/叠加失败不得 fault 主流程**:动作级 fail-safe(返回 `ok=false` 不抛)+ YAML `try` 双保险。
- **不加新偏置旋钮**:`plate_origin_y` 即修正量的家;`bottle_y_offset_mm` 只作用收集器路径,不动。
- **老路不删**:4 角透视单应函数保留(测试兼容 + 包3 端点失败兜底)。
- `reconcile_photo` in-var knob 默认 `true`。
- 本机解释器 `E:/Anaconda/python.exe`;所有测试离线可跑(无相机/PLC)。
- 注释与文案:中文为主体,技术术语保留英文;遵循所在文件既有注释密度与风格。
- **YAML 注释会被 web 编辑器整体 PUT 回写剥光**——流程设计知识写进 `op: comment` 节点,不写 YAML `#` 注释(vars 块内 comment 字段安全)。

---

### Task 1: 创建 `plate_coords.py` 坐标映射单一真源 (C-4)

**Files:**
- Create: `eit_ptlc/controller/plate_coords.py`
- Test: `eit_ptlc/tests/test_plate_coords_offline.py`

**Interfaces:**
- Consumes: `eit_ptlc.controller.cnc_path._flip_from_corner`(现存,flip 查表唯一来源)、`eit_ptlc.config.models.GCodeCfg`。
- Produces(后续 Task 2/6/7 依赖,签名逐字):
  - `plate_bbox_xywh(plate_bbox_px: Any) -> tuple[float, float, float, float]`
  - `px_to_cm_affine(px_pts, plate_bbox_px, plate_size_cm) -> list[tuple[float, float]]`
  - `cm_to_px_affine(cm_pts, plate_bbox_px, plate_size_cm) -> list[tuple[float, float]]`
  - `px_to_cm_corners(px_pts, plate_corners_px, plate_size_cm) -> list[tuple[float, float]]`
  - `cm_to_px_corners(cm_pts, plate_corners_px, plate_size_cm) -> list[tuple[float, float]]`
  - `cm_to_px(cm_pts, *, plate_size_cm, plate_bbox_px=None, plate_corners_px=None) -> list[tuple[float, float]]`
  - `machine_mm_to_cm(pts_mm, gcode_cfg) -> list[tuple[float, float]]`
  - `machine_mm_to_px(pts_mm, gcode_cfg, plate_bbox_px=None, plate_size_cm=20.0, *, plate_corners_px=None) -> list[tuple[float, float]]`

- [ ] **Step 1: 写失败测试**

新建 `eit_ptlc/tests/test_plate_coords_offline.py`:

```python
"""plate_coords 单一真源 — 往返恒等 + 黄金值。

坐标映射公式此前有 3 份拷贝(vision_controller 闭包 / sketch_path / cnc_preview);
收编后本套件是唯一实现的守卫: px↔cm 与 machine↔cm 往返恒等 × 4 种 origin_corner。
"""

from __future__ import annotations

import math
import random

import pytest

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller import plate_coords as pc

_BBOX = {"x": 120.0, "y": 80.0, "w": 900.0, "h": 880.0}
_CORNERS = [(130.0, 90.0), (1010.0, 105.0), (1000.0, 955.0), (118.0, 940.0)]  # 左上,右上,右下,左下
_SIZE = 20.0


def _rand_cm(n=20, seed=7):
    rng = random.Random(seed)
    return [(rng.uniform(0.0, _SIZE), rng.uniform(0.0, _SIZE)) for _ in range(n)]


def test_affine_roundtrip_px_cm_px():
    cm = _rand_cm()
    px = pc.cm_to_px_affine(cm, _BBOX, _SIZE)
    back = pc.px_to_cm_affine(px, _BBOX, _SIZE)
    for (x0, y0), (x1, y1) in zip(cm, back):
        assert math.isclose(x0, x1, abs_tol=1e-9) and math.isclose(y0, y1, abs_tol=1e-9)


def test_corners_roundtrip_px_cm_px():
    cm = _rand_cm(seed=11)
    px = pc.cm_to_px_corners(cm, _CORNERS, _SIZE)
    back = pc.px_to_cm_corners(px, _CORNERS, _SIZE)
    for (x0, y0), (x1, y1) in zip(cm, back):
        assert math.isclose(x0, x1, abs_tol=1e-6) and math.isclose(y0, y1, abs_tol=1e-6)


@pytest.mark.parametrize("corner", ["lower-left", "lower-right", "upper-left", "upper-right"])
def test_machine_roundtrip_all_origin_corners(corner):
    cfg = GCodeCfg(origin_corner=corner, plate_origin_x=137.5, plate_origin_y=42.0)
    cm = _rand_cm(seed=13)
    from eit_ptlc.controller.cnc_path import _flip_from_corner, _to_machine
    flip_x, flip_y = _flip_from_corner(corner)
    mm = [_to_machine(x, y, cfg.plate_origin_x, cfg.plate_origin_y, flip_x, flip_y) for x, y in cm]
    back = pc.machine_mm_to_cm(mm, cfg)
    for (x0, y0), (x1, y1) in zip(cm, back):
        assert math.isclose(x0, x1, abs_tol=1e-9) and math.isclose(y0, y1, abs_tol=1e-9)


def test_affine_golden_values():
    # 黄金值: cm(0,0) → bbox 左下角; cm(S,S) → bbox 右上角 (图像 y 向下)
    px = pc.cm_to_px_affine([(0.0, 0.0), (_SIZE, _SIZE)], _BBOX, _SIZE)
    assert px[0] == (120.0, 80.0 + 880.0)
    assert px[1] == (120.0 + 900.0, 80.0)


def test_cm_to_px_affine_rejects_degenerate_bbox():
    with pytest.raises(ValueError):
        pc.cm_to_px_affine([(1.0, 1.0)], {"x": 0, "y": 0, "w": 0, "h": 100}, _SIZE)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_plate_coords_offline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eit_ptlc.controller.plate_coords'`

- [ ] **Step 3: 创建模块(从 sketch_path 原样迁移 + 收编 cnc_preview 校验)**

新建 `eit_ptlc/controller/plate_coords.py`。函数体**逐字迁移自** `eit_ptlc/controller/sketch_path.py:47-191`(`_plate_bbox_xywh`→改名 `plate_bbox_xywh`、`px_to_cm_affine`、`cm_to_px_affine`、`_solve_homography`、`_apply_homography`、`_corner_cm_targets`、`px_to_cm_corners`、`cm_to_px_corners`、`cm_to_px`、`machine_mm_to_cm`、`machine_mm_to_px`),仅两处改动:

```python
"""板坐标映射单一真源 — px ↔ 板cm ↔ 机床mm。

此前同一组公式存在 3 份拷贝(vision_controller 内部闭包 / sketch_path / cnc_preview,
后者连 _CORNER_FLIP 查表都自带一份)。刮后对账照片是测量仪器, 不能建立在"约定对齐"上,
故收编于此; 三处消费者全部引用本模块 (契约 C-4, spec 2026-07-15-photoscrape-scrape-closedloop)。

flip 查表唯一来源 cnc_path._flip_from_corner; 机床正变换 _to_machine 仍在 cnc_path
(路径生成职责), 本模块只做它的代数逆。
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller.cnc_path import _flip_from_corner

Point = tuple[float, float]
```

改动 1 — `cm_to_px_affine` 采纳 cnc_preview 的更严校验(退化板框必须炸,不能静默产出 NaN 级叠加):

```python
def cm_to_px_affine(
    cm_pts: Sequence[Point], plate_bbox_px: Any, plate_size_cm: float,
) -> list[Point]:
    """板 cm → 像素(轴对齐)。与 vision 渲染同式; 退化板框/尺寸直接拒绝。"""
    x, y, w, h = plate_bbox_xywh(plate_bbox_px)
    if w <= 0 or h <= 0 or plate_size_cm <= 0:
        raise ValueError("板框或 plate_size_cm 无效，无法建立 cm→px 映射")
    out: list[Point] = []
    for cx, cy in cm_pts:
        px = x + (float(cx) / plate_size_cm) * w
        py = y + h - (float(cy) / plate_size_cm) * h
        out.append((px, py))
    return out
```

改动 2 — `machine_mm_to_cm` 保持 sketch_path 版签名 `(pts_mm, gcode_cfg)`,内部 `_flip_from_corner(gcode_cfg.origin_corner)`(即 sketch_path.py:167-176 原文)。

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_plate_coords_offline.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/plate_coords.py eit_ptlc/tests/test_plate_coords_offline.py
git commit -m "feat(plate-coords): 坐标映射单一真源模块 — px↔cm↔machine 收编第一步, 往返恒等×4 origin_corner (契约C-4)"
```

---

### Task 2: 三处消费者收编(sketch_path / cnc_preview / vision_controller)

**Files:**
- Modify: `eit_ptlc/controller/sketch_path.py:44-191`(删除迁移走的函数体,换 re-export)
- Modify: `eit_ptlc/controller/cnc_preview.py:18-75`(删除 `_CORNER_FLIP`/`_plate_bbox_xywh`/`cm_to_px_affine`/`machine_mm_to_cm`/`machine_mm_to_px` 本地定义,换 import)
- Modify: `eit_ptlc/controller/vision_controller.py`(3 处直排公式:≈761-767 闭包、≈895-897 标签位、≈940-965 第二闭包)
- Test: 既有套件回归(无新测试文件)

**Interfaces:**
- Consumes: Task 1 的全部 `plate_coords` 公共函数。
- Produces: `sketch_path` 公共 API 名称与行为不变(`cm_to_px_affine` 新增退化校验除外);`cnc_preview.preview_payload_from_arrays` / `render_cnc_overlay` 签名不变。

- [ ] **Step 1: sketch_path 换 re-export**

删除 `sketch_path.py` 中已迁移的函数定义(47-191 行的 `_plate_bbox_xywh`、`px_to_cm_affine`、`cm_to_px_affine`、`_solve_homography`、`_apply_homography`、`_corner_cm_targets`、`px_to_cm_corners`、`cm_to_px_corners`、`cm_to_px`、`machine_mm_to_cm`、`machine_mm_to_px`),在文件头 import 区加:

```python
from eit_ptlc.controller.plate_coords import (  # noqa: F401 — 公共 API 兼容再导出(单一真源见 plate_coords)
    cm_to_px,
    cm_to_px_affine,
    cm_to_px_corners,
    machine_mm_to_cm,
    machine_mm_to_px,
    plate_bbox_xywh as _plate_bbox_xywh,
    px_to_cm_affine,
    px_to_cm_corners,
)
```

保留 `polygon_to_contour_cm`/`_clean_closed`/`write_manual_summary`/`read_plate_bbox`/`preview_from_polygon`/`render_sketch_overlay`/`commit_sketch` 等其余内容不动(它们经 re-export 名字继续工作)。同时删除文件内不再被剩余代码使用的 `numpy as np` 等 import(若 `render_sketch_overlay` 局部 import 已覆盖)。

- [ ] **Step 2: cnc_preview 换 import**

删除 `cnc_preview.py:18-75` 的 `_CORNER_FLIP`、`_plate_bbox_xywh`、`cm_to_px_affine`、`machine_mm_to_cm`、`machine_mm_to_px` 五个本地定义,文件头加:

```python
from eit_ptlc.controller.plate_coords import (
    cm_to_px_affine,
    machine_mm_to_cm,
    machine_mm_to_px,
    plate_bbox_xywh as _plate_bbox_xywh,
)
```

注意 `machine_mm_to_cm(points_mm, cfg)` 与原 cnc_preview 版签名一致,调用点(110-116)无需改。原 cnc_preview 版的 `raise ValueError(f"未知 origin_corner: ...")` 语义由 `_flip_from_corner` 的 ValueError 覆盖(消息不同,若有测试断言消息则更新断言)。

- [ ] **Step 3: vision_controller 三处直排公式收编**

文件头加 `from eit_ptlc.controller import plate_coords`。

3a. ≈761-767 的闭包(`def cm_to_px(cx_cm, cy_cm)`)改为:

```python
        def cm_to_px(cx_cm: float, cy_cm: float) -> tuple[int, int]:
            px, py = plate_coords.cm_to_px_affine(
                [(cx_cm, cy_cm)],
                {"x": plate_x, "y": plate_y, "w": plate_w, "h": plate_h},
                plate_size_cm,
            )[0]
            return int(round(px)), int(round(py))
```

3b. ≈895-897 的标签位直排公式:

```python
        x_min, y_min, x_max, y_max = band.bbox_cm
        lx, ly = plate_coords.cm_to_px_affine(
            [(x_min, y_max)],
            {"x": plate_x, "y": plate_y, "w": plate_w, "h": plate_h},
            plate_size_cm,
        )[0]
        label_px_x = int(lx)
        label_px_y = int(ly) - 5
```

3c. ≈940-965 的第二处映射闭包:同 3a 型替换。定位方法:`grep -n "plate_h - (" eit_ptlc/controller/vision_controller.py` 找齐全部直排公式点,逐一换掉;完成后该 grep 应 0 命中。

- [ ] **Step 4: 全量回归**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests -q`
Expected: 与基线同数 passed(基线 623;若 cnc_preview 错误消息断言失败,按 Step 2 说明更新该断言后复跑)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/sketch_path.py eit_ptlc/controller/cnc_preview.py eit_ptlc/controller/vision_controller.py
git commit -m "refactor(plate-coords): 三处消费者收编单一真源 — 删 cnc_preview 私有 _CORNER_FLIP/公式拷贝, vision 闭包改调 plate_coords (契约C-4收口)"
```

---

### Task 3: `normalize_applied` 持久化 (C-1)

**Files:**
- Modify: `View/pTLC_Viewing/tlc_analyze.py:2235-2301`(`_normalize_plate_image` 返回三元组)、`:2333`(prepare_manual_backdrop 调用点)、`:2356-2364`(其 summary)、`:2399` 附近(process_pair 调用点)、`:2540-2560`(process_pair summary)
- Modify: `eit_ptlc/controller/sketch_path.py`(`write_manual_summary` + `commit_sketch` 继承字段)
- Modify: `eit_ptlc/api/photoscrape_routes.py:98-106`(sketch_commit 透传 source summary)
- Test: `eit_ptlc/tests/test_normalize_replay_offline.py`(新建,本 Task 先放持久化用例,Task 4 续回放用例)

**Interfaces:**
- Consumes: 现有 `_ROTATION_MAP`(tlc_analyze.py:2201)、`_rotate_pair_about_center`(:2221)。
- Produces:
  - `_normalize_plate_image(...) -> tuple[np.ndarray, np.ndarray, dict]`,第三元 `normalize_applied` 形如 `{"orientation": "rot0", "tilt_deg": 1.23, "rotation_center": "image_center", "frame_size": [W, H]}`(`tilt_deg` 记**实际应用值**,未矫=0.0;`frame_size` 为归一化后 after 帧宽高)。
  - `process_pair` / `prepare_manual_backdrop` 产出的 summary.json 顶层含 `normalize_applied`。
  - `write_manual_summary(..., normalize_applied: dict | None = None)`、`commit_sketch(..., source_summary_path: str | None = None)`。

- [ ] **Step 1: 写失败测试**

新建 `eit_ptlc/tests/test_normalize_replay_offline.py`(import 模式照抄 `test_vision_backdrop_normalize_offline.py` 的 View 目录注入):

```python
"""normalize_applied 持久化 + replay_normalization 帧回放 (契约 C-1/C-3)。

错帧坑: auto_rectify_tilt 角度从当张图现测且只打 stdout; 刮后板绿掩膜已变,
重测角度不同 → 对账叠加错帧被误读成物理 bias。故: 分析时落实际应用参数,
回放只消费参数、禁重新检测。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_VIEW_DIR = Path(__file__).resolve().parents[2] / "View" / "pTLC_Viewing"
if str(_VIEW_DIR) not in sys.path:
    sys.path.insert(0, str(_VIEW_DIR))

cv2 = pytest.importorskip("cv2")
import tlc_analyze as ta  # noqa: E402


def _img(w=200, h=160):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (30, 20), (170, 140), (60, 200, 60), -1)  # 绿"板"
    return img


def test_normalize_returns_applied_dict_identity():
    before, after, applied = ta._normalize_plate_image(_img(), _img(), orientation="rot0")
    assert applied == {
        "orientation": "rot0", "tilt_deg": 0.0,
        "rotation_center": "image_center", "frame_size": [200, 160],
    }


def test_normalize_applied_records_fixed_tilt_and_rot90():
    _, after, applied = ta._normalize_plate_image(
        _img(), _img(), orientation="rot90cw", fixed_rotation_deg=2.0, min_angle_deg=0.5,
    )
    assert applied["orientation"] == "rot90cw"
    assert applied["tilt_deg"] == 2.0
    # rot90 后帧宽高互换
    assert applied["frame_size"] == [160, 200]
    assert [after.shape[1], after.shape[0]] == [160, 200]


def test_normalize_applied_fixed_below_threshold_is_zero():
    _, _, applied = ta._normalize_plate_image(
        _img(), _img(), fixed_rotation_deg=0.2, min_angle_deg=0.5,
    )
    assert applied["tilt_deg"] == 0.0


def test_write_manual_summary_inherits_normalize_applied(tmp_path):
    from eit_ptlc.controller.sketch_path import write_manual_summary
    napplied = {"orientation": "rot0", "tilt_deg": 0.0,
                "rotation_center": "image_center", "frame_size": [200, 160]}
    sp = write_manual_summary(
        [(1.0, 1.0), (5.0, 1.0), (5.0, 3.0)], tmp_path,
        plate_bbox_px={"x": 0, "y": 0, "w": 100, "h": 100},
        normalize_applied=napplied,
    )
    assert json.loads(sp.read_text(encoding="utf-8"))["normalize_applied"] == napplied
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_normalize_replay_offline.py -q`
Expected: FAIL — `ValueError: not enough values to unpack`(返回仍是二元组)/ `TypeError: unexpected keyword 'normalize_applied'`

- [ ] **Step 3: 改 `_normalize_plate_image` 返回三元组**

替换 `tlc_analyze.py:2235-2301` 全函数为(逻辑不变,只加 applied 记录;docstring Returns 同步改):

```python
def _normalize_plate_image(
    before_bgr: np.ndarray,
    after_bgr: np.ndarray,
    orientation: str = "rot0",
    auto_rectify_tilt: bool = False,
    min_angle_deg: float = 0.5,
    fixed_rotation_deg: float | None = None,
) -> tuple:
    """图像姿态归一化：保证下游算法“图像下沿=物理板原点边”假设成立。

    1. 静态旋转：rot0 / rot90cw / rot180 / rot270cw（cv2.rotate 无损 90° 旋转）
    2. 倾斜矫正（可选）：旋转后用 after 跑一次粗 plate 检测 → minAreaRect 求倾角 →
       |angle| >= min_angle_deg 时 warpAffine before 与 after（同一变换矩阵）

    Returns:
        (before_normalized, after_normalized, normalize_applied)
        normalize_applied 记录**实际应用**的变换参数(契约 C-1), 供 summary 持久化与
        replay_normalization 对刮后照片确定性回放(禁重新检测)。
    """
    orientation_key = orientation.strip().lower()

    def _applied(tilt: float) -> dict:
        # frame_size 取调用时刻 after 帧 — 必须在旋转重绑定之后调用
        return {
            "orientation": orientation_key,
            "tilt_deg": float(tilt),
            "rotation_center": "image_center",
            "frame_size": [int(after_bgr.shape[1]), int(after_bgr.shape[0])],
        }

    # --- Step 1: 静态 90° 旋转 ---
    rot_code = _ROTATION_MAP.get(orientation_key)
    if rot_code is not None:
        before_bgr = cv2.rotate(before_bgr, rot_code)
        after_bgr = cv2.rotate(after_bgr, rot_code)

    # --- Step 2a: 固定标定角 deskew（主路径；板+相机固定 => 倾角是常量，不每帧现估）---
    if fixed_rotation_deg is not None:
        angle = float(fixed_rotation_deg)
        if auto_rectify_tilt:  # 交叉校验：实测 vs 固定，仅告警不改旋转量
            observed = _detect_plate_tilt_deg(after_bgr)
            if observed is not None and abs(observed - angle) > _TILT_DRIFT_WARN_DEG:
                print("[normalize] WARN camera tilt drift: fixed=%.2f observed=%.2f -- check camera / re-cal image_plate_rotation_deg" % (angle, observed))
        if abs(angle) >= min_angle_deg:
            before_bgr, after_bgr = _rotate_pair_about_center(before_bgr, after_bgr, angle)
            print("[normalize] fixed_tilt=%.2f rectified" % angle)
            return before_bgr, after_bgr, _applied(angle)
        return before_bgr, after_bgr, _applied(0.0)

    # --- Step 2: 倾斜矫正 ---
    if not auto_rectify_tilt:
        return before_bgr, after_bgr, _applied(0.0)

    # 粗板检测：提取绿色区域的 minAreaRect
    _, green_mask = green_plate_mask(after_bgr)
    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return before_bgr, after_bgr, _applied(0.0)

    largest = max(contours, key=cv2.contourArea)
    rect = cv2.minAreaRect(largest)
    angle = rect[2]  # OpenCV minAreaRect angle ∈ (-90, 0]

    # 角度归一化到 [-45, 45] 范围
    if angle < -45:
        angle += 90

    if abs(angle) < min_angle_deg:
        return before_bgr, after_bgr, _applied(0.0)

    # 以图像中心为旋转中心，反向旋转使板边平行图像边
    h, w = after_bgr.shape[:2]
    center = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    before_bgr = cv2.warpAffine(before_bgr, M, (w, h), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_REPLICATE)
    after_bgr = cv2.warpAffine(after_bgr, M, (w, h), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE)

    print(f"[normalize] orientation={orientation} tilt={angle:.2f}° rectified=True")
    return before_bgr, after_bgr, _applied(angle)
```

- [ ] **Step 4: 更新全部调用点并写入 summary**

`grep -n "_normalize_plate_image(" View/pTLC_Viewing/tlc_analyze.py` 找齐调用点(已知 :2333 与 :2399 附近;若测试文件也调用,一并改):

4a. `prepare_manual_backdrop`(:2333):

```python
    _, after, normalize_applied = _normalize_plate_image(
        after.copy(), after,
        orientation=image_plate_orientation,
        auto_rectify_tilt=auto_rectify_tilt,
        min_angle_deg=rectify_min_angle_deg,
        fixed_rotation_deg=image_plate_rotation_deg,
    )
```

其 summary dict(:2356-2362)加一行:

```python
    summary: dict = {
        "ok": False,
        "source": "after_only_backdrop",
        "reason": "before_invalid",
        "plate_size_cm": float(plate_size_cm),
        "normalize_applied": normalize_applied,
        "bands": [],
    }
```

4b. `process_pair` 调用点(:2399 附近)同型改为三元解包 `before_bgr, after_bgr, normalize_applied = ...`;其 summary dict(:2540 起)在 `"plate_bbox_px"` 键旁加:

```python
        "normalize_applied": normalize_applied,
```

- [ ] **Step 5: `write_manual_summary` / `commit_sketch` / 路由继承**

5a. `sketch_path.write_manual_summary` 签名与体:

```python
def write_manual_summary(
    contour_cm: Sequence[Point],
    workspace_dir: Path,
    *,
    band_id: str = MANUAL_BAND_ID,
    plate_bbox_px: Any = None,
    normalize_applied: dict | None = None,
) -> Path:
```

在 `summary_doc` 构造后、写盘前加:

```python
    if normalize_applied is not None:
        summary_doc["normalize_applied"] = normalize_applied
```

5b. `commit_sketch` 加 kwarg `source_summary_path: str | None = None`,在 `write_manual_summary` 调用前读继承字段(C-1: manual summary 继承源 summary,刮后回放两级链路的第一级):

```python
    normalize_applied = None
    if source_summary_path:
        try:
            normalize_applied = json.loads(
                Path(source_summary_path).read_text(encoding="utf-8")
            ).get("normalize_applied")
        except (OSError, ValueError, TypeError):
            normalize_applied = None  # 旧 summary 无此字段: 对账叠加将 fail-safe 跳过
    summary_path = write_manual_summary(
        contour_cm, workspace, plate_bbox_px=plate_bbox_px,
        normalize_applied=normalize_applied,
    )
```

5c. `photoscrape_routes.py` sketch_commit(:98-106)透传:在 `sp.commit_sketch(...)` 实参里加 `source_summary_path=source_summary,`。

- [ ] **Step 6: 跑测试确认通过 + 回归**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_normalize_replay_offline.py eit_ptlc/tests/test_vision_backdrop_normalize_offline.py -q`
Expected: 全 passed(backdrop 套件守卫 prepare_manual_backdrop 行为未破)。
再跑 `E:/Anaconda/python.exe -m pytest eit_ptlc/tests -q` 全量,同基线。

- [ ] **Step 7: Commit**

```bash
git add View/pTLC_Viewing/tlc_analyze.py eit_ptlc/controller/sketch_path.py eit_ptlc/api/photoscrape_routes.py eit_ptlc/tests/test_normalize_replay_offline.py
git commit -m "feat(vision): normalize_applied 实际应用参数持久化进 summary — 全部生产者(process_pair/backdrop/manual继承) (契约C-1)"
```

---

### Task 4: `replay_normalization` 帧回放 (C-3)

**Files:**
- Modify: `View/pTLC_Viewing/tlc_analyze.py`(`_rotate_pair_about_center` 之后新增函数)
- Test: `eit_ptlc/tests/test_normalize_replay_offline.py`(追加用例)

**Interfaces:**
- Consumes: Task 3 的 `normalize_applied` summary 字段;`_ROTATION_MAP`。
- Produces: `replay_normalization(raw_image_path: Path|str, summary_path: Path|str, out_path: Path|str) -> Path`(Task 7 消费)。可选消费 summary 的 `manual_rectify` 字段(包3 产;形状 `{"plate_corners_px": [[x,y]×4], "px_per_cm": int, "frame_size": [W,H]}`)。

- [ ] **Step 1: 追加失败测试**

在 `test_normalize_replay_offline.py` 追加:

```python
def _write_case(tmp_path, applied, manual_rectify=None, img=None):
    raw = tmp_path / "scraped.jpg"
    cv2.imwrite(str(raw), _img() if img is None else img)
    summary = {"ok": True, "normalize_applied": applied}
    if manual_rectify is not None:
        summary["manual_rectify"] = manual_rectify
    sp = tmp_path / "summary.json"
    sp.write_text(json.dumps(summary), encoding="utf-8")
    return raw, sp


def test_replay_is_deterministic_and_matches_normalize(tmp_path):
    # 同参数: _normalize_plate_image 与 replay 输出逐像素一致 (同源 by construction)
    src = _img()
    _, expect, applied = ta._normalize_plate_image(
        src.copy(), src.copy(), orientation="rot180", fixed_rotation_deg=1.5, min_angle_deg=0.5,
    )
    raw, sp = _write_case(tmp_path, applied, img=src)
    out1 = ta.replay_normalization(raw, sp, tmp_path / "n1.png")
    out2 = ta.replay_normalization(raw, sp, tmp_path / "n2.png")
    got1 = cv2.imread(str(out1)); got2 = cv2.imread(str(out2))
    assert np.array_equal(got1, got2)                       # 确定性
    # 与在线归一化一致 (jpg 输入有量化损失, 允许极小差)
    assert got1.shape == expect.shape
    assert float(np.mean(np.abs(got1.astype(int) - expect.astype(int)))) < 3.0


def test_replay_missing_applied_raises(tmp_path):
    raw = tmp_path / "scraped.jpg"; cv2.imwrite(str(raw), _img())
    sp = tmp_path / "summary.json"
    sp.write_text(json.dumps({"ok": True}), encoding="utf-8")   # 旧 summary 无字段
    with pytest.raises(ValueError):
        ta.replay_normalization(raw, sp, tmp_path / "out.png")


def test_replay_frame_size_mismatch_raises(tmp_path):
    applied = {"orientation": "rot0", "tilt_deg": 0.0,
               "rotation_center": "image_center", "frame_size": [999, 999]}
    raw, sp = _write_case(tmp_path, applied)
    with pytest.raises(ValueError):
        ta.replay_normalization(raw, sp, tmp_path / "out.png")


def test_replay_applies_manual_rectify_second_stage(tmp_path):
    applied = {"orientation": "rot0", "tilt_deg": 0.0,
               "rotation_center": "image_center", "frame_size": [200, 160]}
    manual = {"plate_corners_px": [[30, 20], [170, 20], [170, 140], [30, 140]],
              "px_per_cm": 4, "frame_size": [80, 80]}
    raw, sp = _write_case(tmp_path, applied, manual_rectify=manual)
    out = cv2.imread(str(ta.replay_normalization(raw, sp, tmp_path / "out.png")))
    assert [out.shape[1], out.shape[0]] == [80, 80]         # 二级回放到手动矫正帧
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_normalize_replay_offline.py -q`
Expected: 新 4 例 FAIL — `AttributeError: module 'tlc_analyze' has no attribute 'replay_normalization'`

- [ ] **Step 3: 实现 `replay_normalization`**

在 `tlc_analyze.py` 的 `_rotate_pair_about_center` 之后加(与归一化实现同居一文件 = 同源 by construction):

```python
def replay_normalization(raw_image_path, summary_path, out_path):
    """对一张原始相机帧**确定性回放** summary 记录的归一化变换 (契约 C-3)。

    用途: 刮后对账照片 scraped.jpg 与 after_normalized.jpg 像素同帧, 叠加指令路径
    才有测量意义。**禁止任何重新检测**(刮后板绿掩膜已变, 重测角度=错帧=假 bias)。

    两级链: normalize_applied(姿态归一化) → 可选 manual_rectify(包3 手动 4 角矫正帧)。
    参数缺失(旧 summary)/尺寸不符 → ValueError: 调用方宁可无图, 不可错帧。
    """
    from pathlib import Path as _Path
    summary = json.loads(_Path(summary_path).read_text(encoding="utf-8"))
    applied = summary.get("normalize_applied")
    if not isinstance(applied, dict):
        raise ValueError("summary 缺少 normalize_applied, 拒绝回放(禁止重新检测)")
    img = cv2.imread(str(raw_image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法读取回放输入图 {raw_image_path}")

    rot_code = _ROTATION_MAP.get(str(applied.get("orientation", "rot0")).strip().lower())
    if rot_code is not None:
        img = cv2.rotate(img, rot_code)
    tilt = float(applied.get("tilt_deg", 0.0))
    if tilt != 0.0:
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), tilt, 1.0)
        img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
    frame = applied.get("frame_size") or []
    if len(frame) != 2 or [int(img.shape[1]), int(img.shape[0])] != [int(frame[0]), int(frame[1])]:
        raise ValueError(
            f"回放帧尺寸 {img.shape[1]}x{img.shape[0]} 与记录 frame_size {frame} 不符 -- 拒绝错帧叠加")

    manual = summary.get("manual_rectify")
    if isinstance(manual, dict):
        corners = manual["plate_corners_px"]
        mw, mh = (int(v) for v in manual["frame_size"])
        src = np.float32([[float(x), float(y)] for x, y in corners])
        dst = np.float32([[0, 0], [mw, 0], [mw, mh], [0, mh]])
        img = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (mw, mh))

    out_path = _Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out_path), img):
        raise ValueError(f"回放帧写盘失败: {out_path}")
    return out_path
```

(确认文件头已 `import json`;tlc_analyze 已有,若无则加。)

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_normalize_replay_offline.py -q`
Expected: 全 passed

- [ ] **Step 5: Commit**

```bash
git add View/pTLC_Viewing/tlc_analyze.py eit_ptlc/tests/test_normalize_replay_offline.py
git commit -m "feat(vision): replay_normalization 确定性帧回放 — 禁重新检测/尺寸守卫/manual_rectify 二级链 (契约C-3)"
```

---

### Task 5: preview payload 落盘 (C-5)

**Files:**
- Modify: `eit_ptlc/controller/cnc_preview.py:100-130`(payload 增补板参照两字段)
- Modify: `eit_ptlc/controller/cnc_path.py:1155-1174`(payload 先落盘再找 backdrop)
- Test: `eit_ptlc/tests/test_cnc_preview_offline.py`(追加)

**Interfaces:**
- Consumes: Task 1/2 的 `cm_to_px_affine` 等。
- Produces: `preview_payload_from_arrays` 返回 dict 新增键 `plate_bbox_px`(dict|list 原样)与 `plate_size_cm`(float);cnc_path 动作在 `summary.parent / "preview_payload.json"` 落盘该 dict,action result 新增 `preview_payload_path`(str)。Task 6 标注层与 Task 7 对账叠加消费。

- [ ] **Step 1: 追加失败测试**

在 `test_cnc_preview_offline.py` 追加(复用该文件既有的 summary/arrays 构造 helper;若其 helper 不便复用,用 `sketch_path.write_manual_summary` 自建):

```python
def test_payload_carries_plate_ref_fields(tmp_path):
    from eit_ptlc.controller.sketch_path import write_manual_summary
    from eit_ptlc.controller.cnc_path import generate_scrape_arrays
    from eit_ptlc.config.models import GCodeCfg
    cfg = GCodeCfg()
    summary = write_manual_summary(
        [(2.0, 4.0), (18.0, 4.0), (18.0, 6.0), (2.0, 6.0)], tmp_path,
        plate_bbox_px={"x": 0, "y": 0, "w": 400, "h": 400},
    )
    arrays = generate_scrape_arrays(summary, "manual_01", cfg)
    payload = preview_payload_from_arrays(summary, "manual_01", arrays, cfg)
    assert payload["plate_bbox_px"] == {"x": 0, "y": 0, "w": 400, "h": 400}
    assert payload["plate_size_cm"] == 20.0


def test_cnc_path_action_persists_payload(tmp_path):
    import asyncio, json as _json
    from eit_ptlc.controller.sketch_path import write_manual_summary
    from eit_ptlc.controller.cnc_path import CncPathController
    from eit_ptlc.config.models import GCodeCfg
    summary = write_manual_summary(
        [(2.0, 4.0), (18.0, 4.0), (18.0, 6.0), (2.0, 6.0)], tmp_path,
        plate_bbox_px={"x": 0, "y": 0, "w": 400, "h": 400},
    )
    ctrl = CncPathController(lambda: GCodeCfg())
    result = asyncio.run(ctrl.generate_cnc_path(str(summary), "manual_01"))
    payload_path = tmp_path / "preview_payload.json"
    assert payload_path.is_file()                      # 无 backdrop 也要落 payload
    doc = _json.loads(payload_path.read_text(encoding="utf-8"))
    assert doc["band_id"] == "manual_01" and "plate_bbox_px" in doc
    assert result["preview_payload_path"] == str(payload_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_cnc_preview_offline.py -q`
Expected: 新 2 例 FAIL(`KeyError: 'plate_bbox_px'` / payload 文件不存在)

- [ ] **Step 3: 实现**

3a. `cnc_preview.preview_payload_from_arrays` 返回 dict 末尾加两键:

```python
        "cutter_width_px": round(cutter_width_px, 1),  # 刀宽扫掠带(物理事实, 与补偿开关无关)
        # 板参照随 payload 落盘: 对账叠加/坐标系标注层同源消费 (契约 C-5)
        "plate_bbox_px": plate_bbox_px,
        "plate_size_cm": float(plate_size_cm),
    }
```

3b. `cnc_path.py` `_generate_and_preview` 内(:1162 起)重排 — payload 先算先落盘(几何有效即写,backdrop 缺失/渲染失败不影响),再找 backdrop:

```python
                preview = preview_payload_from_arrays(summary, band_id, arrays, cfg)
                # C-5: payload 先落盘 — 对账叠加只读此文件, 与门 preview 逐字节同源
                payload_path = summary.parent / "preview_payload.json"
                payload_path.write_text(
                    json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
                result["preview_payload_path"] = str(payload_path)
                backdrop = default_backdrop(summary)
                if backdrop is None:
                    result["preview_message"] = "未找到 after_normalized.jpg/after.jpg，未生成 CNC 预览"
                    return result
```

同时把上方 `result.update({...})` 初始化里加 `"preview_payload_path": "",`。确认 `cnc_path.py` 头部有 `import json`(现有 `_patch_summary_paths` 已用,应有;无则加)。

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_cnc_preview_offline.py eit_ptlc/tests/test_photoscrape_four_stage_offline.py -q`
Expected: 全 passed

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/cnc_preview.py eit_ptlc/controller/cnc_path.py eit_ptlc/tests/test_cnc_preview_offline.py
git commit -m "feat(cnc-preview): preview payload 携板参照并随 cnc_path 落盘 preview_payload.json — 对账叠加同源依据 (契约C-5)"
```

---

### Task 6: 板坐标系标注层 (spec §5.3, 用户 Q1)

**Files:**
- Modify: `eit_ptlc/controller/cnc_preview.py`(新函数 + `render_cnc_overlay` 接入)
- Modify: `eit_ptlc/web/src/overlayLegends.js:22-27`(CNC_LEGEND 加图例行)
- Test: `eit_ptlc/tests/test_cnc_preview_offline.py`(追加)

**Interfaces:**
- Consumes: Task 5 payload 的 `plate_bbox_px`/`plate_size_cm`;Task 1 `cm_to_px_affine`。
- Produces: `draw_plate_frame_annotation(image, plate_bbox_px, plate_size_cm) -> None`(就地画);`render_cnc_overlay` 行为扩展(payload 含板参照时自动加标注层)——门 preview 图与刮后对账图共用。

- [ ] **Step 1: 追加失败测试**

```python
def test_render_overlay_draws_plate_frame_annotation(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    from eit_ptlc.controller.cnc_preview import render_cnc_overlay
    backdrop = tmp_path / "after_normalized.jpg"
    cv2.imwrite(str(backdrop), np.zeros((400, 400, 3), dtype=np.uint8))
    payload = {"scrape_px": [[50, 50], [350, 50]], "collect_px": [], "contour_px": [],
               "cutter_width_px": 0.0,
               "plate_bbox_px": {"x": 20, "y": 20, "w": 360, "h": 360},
               "plate_size_cm": 20.0}
    out = tmp_path / "overlay.png"
    assert render_cnc_overlay(backdrop, payload, out)
    img = cv2.imread(str(out))
    # 原点角 cm(0,0) = bbox 左下 (20, 380) 附近应出现黄色标注像素 (B,G,R)=(0,255,255)
    patch = img[340:400, 0:80]
    yellow = (patch[:, :, 1] > 200) & (patch[:, :, 2] > 200) & (patch[:, :, 0] < 80)
    assert int(yellow.sum()) > 20
```

(文件头若无 `import pytest` 则加。)

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_cnc_preview_offline.py::test_render_overlay_draws_plate_frame_annotation -q`
Expected: FAIL — 黄色像素数为 0

- [ ] **Step 3: 实现标注层**

`cnc_preview.py` 新增(放 `render_cnc_overlay` 之前):

```python
def draw_plate_frame_annotation(image, plate_bbox_px, plate_size_cm) -> None:
    """板坐标系标注层: 四角 X + cm 语义标签, 原点 cm(0,0) 双圈, +x/+y 短箭头。

    标注全部经同一 cm_to_px_affine 画出 — 标注即同源探针: 映射有错, 箭头/角标立错。
    操作员核对口诀: cm 原点角应贴点样边。门 preview 与刮后对账图共用 (spec §5.3)。
    """
    import cv2  # type: ignore
    s = float(plate_size_cm)
    yellow, shadow = (0, 255, 255), (7, 7, 10)
    scale = max(0.5, image.shape[1] / 1600.0)
    r = max(4, int(round(10 * scale)))

    def _pt(cx: float, cy: float) -> tuple[int, int]:
        x, y = cm_to_px_affine([(cx, cy)], plate_bbox_px, s)[0]
        return int(round(x)), int(round(y))

    def _text(label: str, org: tuple[int, int]) -> None:
        for color, thick in ((shadow, 3), (yellow, 1)):
            cv2.putText(image, label, org, cv2.FONT_HERSHEY_SIMPLEX,
                        0.6 * scale + 0.2, color, thick, cv2.LINE_AA)

    for cx, cy in ((0.0, 0.0), (s, 0.0), (0.0, s), (s, s)):
        p = _pt(cx, cy)
        for color, thick in ((shadow, 4), (yellow, 2)):
            cv2.line(image, (p[0] - r, p[1] - r), (p[0] + r, p[1] + r), color, thick, cv2.LINE_AA)
            cv2.line(image, (p[0] - r, p[1] + r), (p[0] + r, p[1] - r), color, thick, cv2.LINE_AA)
        _text(f"cm({int(cx)},{int(cy)})", (p[0] + r + 3, p[1] - r - 3))

    origin = _pt(0.0, 0.0)
    for mul in (1.6, 2.4):  # 双圈: 原点角醒目于其余三角
        cv2.circle(image, origin, int(round(r * mul)), yellow, 2, cv2.LINE_AA)
    for tx, ty, label in ((3.0, 0.0, "+x"), (0.0, 3.0, "+y")):
        tip = _pt(tx, ty)
        cv2.arrowedLine(image, origin, tip, shadow, 4, cv2.LINE_AA, tipLength=0.25)
        cv2.arrowedLine(image, origin, tip, yellow, 2, cv2.LINE_AA, tipLength=0.25)
        _text(label, (tip[0] + 4, tip[1] - 4))
```

`render_cnc_overlay` 里三条 `_polyline(...)` 之后、写盘之前接入:

```python
    bbox = preview.get("plate_bbox_px")
    size = preview.get("plate_size_cm")
    if bbox is not None and size:
        try:
            draw_plate_frame_annotation(image, bbox, float(size))
        except Exception:  # noqa: BLE001 标注失败不挡叠加主体(旧 payload 无板参照即静默跳过)
            pass
```

- [ ] **Step 4: 前端图例文案**

`eit_ptlc/web/src/overlayLegends.js` CNC_LEGEND 数组(:22-26)追加一行:

```js
  { color: 'rgb(255,255,0)', shape: 'cross', label: '板角X/原点双圈/±轴箭头', note: '程序认定的板坐标系; 原点 cm(0,0) 应贴点样边' },
```

- [ ] **Step 5: 跑测试确认通过**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_cnc_preview_offline.py -q`
Expected: 全 passed

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/controller/cnc_preview.py eit_ptlc/web/src/overlayLegends.js eit_ptlc/tests/test_cnc_preview_offline.py
git commit -m "feat(cnc-preview): 板坐标系标注层 — 四角X+cm原点双圈+±轴箭头(同源探针), 门preview与对账图共用 (spec§5.3)"
```

---

### Task 7: `scrape_reconcile` 对账控制器 + 动作注册

**Files:**
- Create: `eit_ptlc/controller/scrape_reconcile.py`
- Create: `eit_ptlc/config/actions/04_photoscrape/scraped_overlay.yaml`
- Modify: `eit_ptlc/runtime/bootstrap.py:245-247`(控制器构造)与 `:326-331`(vision_methods 接线)
- Test: `eit_ptlc/tests/test_scrape_reconcile_offline.py`

**Interfaces:**
- Consumes: Task 4 `replay_normalization`、Task 5 `preview_payload.json`、Task 6 增强的 `render_cnc_overlay`。
- Produces:
  - `render_scraped_overlay(summary_path, scraped_path, *, image_root: Path | None = None) -> dict` 返回 `{"ok": bool, "scraped_url": str, "annotated_url": str, "message": str}`,**永不 raise**。
  - `ScrapeReconcileController(image_root_provider).scraped_overlay(summary_path: str = "", scraped_path: str = "") -> dict`(async,executor vision kind 消费)。
  - 动作名 `photoscrape.scraped_overlay`(Task 8 YAML 消费)。

- [ ] **Step 1: 写失败测试**

新建 `eit_ptlc/tests/test_scrape_reconcile_offline.py`:

```python
"""刮后对账叠加 — 帧回放 + payload 同源渲染 + 全链 fail-safe。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from eit_ptlc.controller.scrape_reconcile import render_scraped_overlay


def _case(tmp_path: Path, *, with_applied=True, with_payload=True) -> tuple[Path, Path]:
    """最小 case 目录: summary(+normalize_applied) + preview_payload.json + 原始 scraped.jpg。"""
    summary = {"ok": True, "bands": []}
    if with_applied:
        summary["normalize_applied"] = {"orientation": "rot0", "tilt_deg": 0.0,
                                        "rotation_center": "image_center",
                                        "frame_size": [200, 160]}
    sp = tmp_path / "summary.json"
    sp.write_text(json.dumps(summary), encoding="utf-8")
    if with_payload:
        payload = {"scrape_px": [[20, 80], [180, 80]], "collect_px": [], "contour_px": [],
                   "cutter_width_px": 0.0,
                   "plate_bbox_px": {"x": 10, "y": 10, "w": 180, "h": 140},
                   "plate_size_cm": 20.0}
        (tmp_path / "preview_payload.json").write_text(json.dumps(payload), encoding="utf-8")
    scraped = tmp_path / "scraped.jpg"
    cv2.imwrite(str(scraped), np.zeros((160, 200, 3), dtype=np.uint8))
    return sp, scraped


def test_happy_path_writes_normalized_and_annotated(tmp_path):
    sp, scraped = _case(tmp_path)
    res = render_scraped_overlay(sp, scraped, image_root=tmp_path)
    assert res["ok"] is True
    assert (tmp_path / "scraped_normalized.jpg").is_file()
    assert (tmp_path / "scraped_annotated.png").is_file()
    assert res["annotated_url"].startswith("/api/vision/image/")


def test_missing_normalize_applied_failsafe(tmp_path):
    sp, scraped = _case(tmp_path, with_applied=False)
    res = render_scraped_overlay(sp, scraped, image_root=tmp_path)
    assert res["ok"] is False and "normalize_applied" in res["message"]
    assert not (tmp_path / "scraped_annotated.png").exists()   # 宁可无图不可错帧


def test_missing_payload_failsafe(tmp_path):
    sp, scraped = _case(tmp_path, with_payload=False)
    res = render_scraped_overlay(sp, scraped, image_root=tmp_path)
    assert res["ok"] is False and "preview_payload" in res["message"]


def test_action_wrapper_never_raises(tmp_path):
    import asyncio
    from eit_ptlc.controller.scrape_reconcile import ScrapeReconcileController
    ctrl = ScrapeReconcileController(lambda: tmp_path)
    res = asyncio.run(ctrl.scraped_overlay(summary_path="", scraped_path=""))
    assert res["ok"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_scrape_reconcile_offline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eit_ptlc.controller.scrape_reconcile'`

- [ ] **Step 3: 实现模块**

新建 `eit_ptlc/controller/scrape_reconcile.py`:

```python
"""刮后对账叠加 — "说好的 vs 刮到的" (spec §5.2)。

scraped.jpg(原始相机帧) → replay_normalization 回放到归一化帧(禁重新检测, 契约 C-3)
→ 读 cnc_path 落盘的 preview_payload.json(契约 C-5, never regenerates) → render_cnc_overlay。
青色指令路径 vs 照片里白色刮槽的错位 = 相机链+机床链+刀具链总 bias 的直接图像测量。

全链 fail-safe: 对账是哨兵不是工艺步, 任何失败 ok=false 不抛 (YAML try 双保险)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from eit_ptlc.controller.cnc_preview import render_cnc_overlay

log = logging.getLogger(__name__)


def _ensure_tlc_analyze() -> Any:
    """动态注入 View/pTLC_Viewing 并导入 tlc_analyze (与 vision_quality 同模式)。"""
    view_dir = Path(__file__).resolve().parents[2] / "View" / "pTLC_Viewing"
    if str(view_dir) not in sys.path:
        sys.path.insert(0, str(view_dir))
    try:
        import tlc_analyze  # type: ignore  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(f"Unable to import tlc_analyze from {view_dir}: {exc}") from exc
    return tlc_analyze


def _url_for(path: Path, image_root: Path | None) -> str:
    if image_root is None:
        return ""
    try:
        rel = path.resolve().relative_to(Path(image_root).resolve()).as_posix()
        return f"/api/vision/image/{rel}"
    except (OSError, ValueError):
        return ""


def render_scraped_overlay(
    summary_path: Path | str, scraped_path: Path | str, *, image_root: Path | None = None,
) -> dict:
    """刮后照片 → scraped_normalized.jpg + scraped_annotated.png, 落 case 目录。永不 raise。"""
    out = {"ok": False, "scraped_url": "", "annotated_url": "", "message": ""}
    try:
        case_dir = Path(summary_path).parent
        payload_path = case_dir / "preview_payload.json"
        if not payload_path.is_file():
            out["message"] = "缺少 preview_payload.json(候选未经 cnc_path 或几何无板参照), 跳过对账叠加"
            return out
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        ta = _ensure_tlc_analyze()
        normalized = ta.replay_normalization(
            scraped_path, summary_path, case_dir / "scraped_normalized.jpg")
        out["scraped_url"] = _url_for(Path(normalized), image_root)
        annotated = case_dir / "scraped_annotated.png"
        if not render_cnc_overlay(normalized, payload, annotated):
            out["message"] = "对账叠加渲染失败(cv2 缺失或底图不可读)"
            return out
        out["ok"] = True
        out["annotated_url"] = _url_for(annotated, image_root)
        return out
    except Exception as exc:  # noqa: BLE001 哨兵步全链 fail-safe, 失败留 message 供日志/复盘
        log.warning("[reconcile] 刮后对账叠加失败(不阻断主流程): %s", exc, exc_info=True)
        out["message"] = f"对账叠加失败: {exc}"
        return out


class ScrapeReconcileController:
    """executor vision kind 的 async 入口 (与 CncPathController 同型)。"""

    def __init__(self, image_root_provider: Callable[[], Path] | None = None) -> None:
        self._image_root = image_root_provider

    async def scraped_overlay(self, summary_path: str = "", scraped_path: str = "") -> dict:
        loop = asyncio.get_running_loop()
        root = Path(self._image_root()) if self._image_root is not None else None
        return await loop.run_in_executor(
            None, lambda: render_scraped_overlay(summary_path, scraped_path, image_root=root))
```

- [ ] **Step 4: 动作 YAML + bootstrap 接线**

4a. 新建 `eit_ptlc/config/actions/04_photoscrape/scraped_overlay.yaml`:

```yaml
# 刮后对账叠加 (vision kind, 纯计算落图): scraped.jpg 回放归一化帧 + 同一 preview payload 叠加。
# 哨兵步非工艺步: 任何失败 result.ok=false 不抛 (流程 YAML 侧另有 try 双保险)。
photoscrape.scraped_overlay:
  kind: vision
  method: scraped_overlay
  label: 刮后对账叠加
  desc: 刮后照片回放到归一化帧, 叠加下发时的指令路径 → scraped_annotated.png(说好的vs刮到的)
  modes: []
  params:
    - {name: summary_path, type: string, required: true, label: 下发候选summary路径}
    - {name: scraped_path, type: string, required: true, label: 刮后照片路径}
```

4b. `bootstrap.py`:在 `cnc_ctrl = CncPathController(...)`(:245-247)之后加:

```python
    scrape_reconcile = ScrapeReconcileController(
        image_root_provider=lambda: Path(config.vision.output_dir),
    )
```

文件头 import 区加 `from eit_ptlc.controller.scrape_reconcile import ScrapeReconcileController`。
`vision_methods`(:326-331)加一项:

```python
        "scraped_overlay": scrape_reconcile.scraped_overlay,
```

- [ ] **Step 5: 跑测试确认通过**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_scrape_reconcile_offline.py -q`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/controller/scrape_reconcile.py eit_ptlc/config/actions/04_photoscrape/scraped_overlay.yaml eit_ptlc/runtime/bootstrap.py eit_ptlc/tests/test_scrape_reconcile_offline.py
git commit -m "feat(reconcile): photoscrape.scraped_overlay 对账动作 — 回放帧+payload同源叠加, 全链fail-safe (spec§5.2)"
```

---

### Task 8: 流程编排补拍块 + 门流离线测试

**Files:**
- Modify: `eit_ptlc/config/operation/03_photoscrape/photoscrape_process.yaml`(vars :32-57;body pass 循环后 :256-263)
- Modify: `eit_ptlc/tests/test_photoscrape_gate_flow_offline.py`(`_drive` 扩展 + 新用例)
- Modify(如断言破): `eit_ptlc/tests/test_photoscrape_four_stage_offline.py`

**Interfaces:**
- Consumes: Task 7 的动作 `photoscrape.scraped_overlay`;现有 `photoscrape.cam_photopos/capture/cam_photohome`。
- Produces: 运行流程新 in-var `reconcile_photo`(BOOL, default true)——包1 实验与生产运维消费。

- [ ] **Step 1: 扩展 `_drive` + 写失败测试**

1a. `_drive`(:87-102)加 `extra_vars=None` 形参,start 变量合并:

```python
async def _drive(mode, replies, terminal, analyze=ANALYZE_OK, executor=None, extra_vars=None):
    ex = executor if executor is not None else PhotoExecutor(analyze)
    events: list[dict] = []
    c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append)
    start_vars = {"mode": mode, "sample_id": "T", "save_dir": "/x", "before_path": "/x/before.jpg"}
    if extra_vars:
        start_vars.update(extra_vars)
    s = await c.start(_doc(), start_vars, mode_run="run")
```

(其余行不动。)

1b. 文件尾追加用例 + 失败注入执行器:

```python
class ScrapedCaptureFailExecutor(PhotoExecutor):
    """刮后补拍 capture 失败注入: 对账是哨兵, 失败不得 fault 主流程。"""

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        params = dict(params or {})
        if name == "photoscrape.capture" and params.get("filename") == "scraped.jpg":
            self.calls.append((name, params))
            return ActionResult(action=name, request_id="x", status=ActionStatus.REJECTED,
                                accepted=False, message="相机故障(注入)", result={})
        return await super().execute(name, params, request_id=request_id, current_mode=current_mode)


def test_reconcile_photo_captured_after_scrape_before_finish():
    ex, _ = _run(_drive("auto", [], "DONE"))
    names = _names(ex)
    captures = [c for c in ex.calls if c[0] == "photoscrape.capture"]
    assert len(captures) == 2, f"应有 段首after + 刮后scraped 两次拍照: {captures}"
    assert captures[1][1].get("filename") == "scraped.jpg"
    # 顺序: 最后一次 scrape → 补拍 → 对账叠加 → scrape_finish
    assert "photoscrape.scraped_overlay" in names
    last_scrape = max(i for i, n in enumerate(names) if n == "photoscrape.scrape")
    assert last_scrape < names.index("photoscrape.scraped_overlay") < names.index("photoscrape.scrape_finish")


def test_reconcile_photo_knob_off_skips_block():
    ex, _ = _run(_drive("auto", [], "DONE", extra_vars={"reconcile_photo": False}))
    captures = [c for c in ex.calls if c[0] == "photoscrape.capture"]
    assert len(captures) == 1                      # 只有段首 after.jpg
    assert "photoscrape.scraped_overlay" not in _names(ex)


def test_reconcile_photo_skipped_when_skip_scrape():
    ex, _ = _run(_drive("manual", [{"choice": "skip", "values": {}}], "DONE"))
    captures = [c for c in ex.calls if c[0] == "photoscrape.capture"]
    assert len(captures) == 1
    assert "photoscrape.scraped_overlay" not in _names(ex)


def test_reconcile_capture_failure_does_not_fault_run():
    ex, _ = _run(_drive("auto", [], "DONE", executor=ScrapedCaptureFailExecutor()))
    names = _names(ex)
    assert "photoscrape.scrape_finish" in names          # 主流程照常收尾
    # catch 内 best-effort 收相机: 失败 capture 之后仍有 cam_photohome
    fail_idx = max(i for i, c in enumerate(ex.calls)
                   if c[0] == "photoscrape.capture" and c[1].get("filename") == "scraped.jpg")
    assert any(i > fail_idx for i, n in enumerate(names) if n == "photoscrape.cam_photohome")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_photoscrape_gate_flow_offline.py -q`
Expected: 新 4 例 FAIL(capture 只有 1 次 / scraped_overlay 不存在);旧用例仍 passed

- [ ] **Step 3: 改 YAML**

3a. vars 块(:56 `fixed_summary_path` 行后)加两个变量:

```yaml
  - {name: reconcile_photo, scope: local, type: BOOL, io: in, default: true,     comment: "刮后对账照片开关(漂移哨兵/标定验收唯一凭据); 生产嫌节拍可关"}
  - {name: scraped_shot,    scope: local, type: DICT,                            comment: 刮后对账拍照结果(image_path)}
```

3b. body 的 pass 循环(`op: for`,:256-261)与 `scrape_finish` comment(:262)之间插入:

```yaml
  - {op: comment, text: "(7) 刮后对账照片(哨兵非工艺步): 板仍压紧+相机回同一拍照位 → scraped.jpg 与 after.jpg 像素对齐; 叠同一 preview payload = 说好的vs刮到的; 失败不 fault (reconcile_photo=false 或跳过刮板时不拍)"}
  - op: if
    cond: {binop: and, left: {var: reconcile_photo},
           right: {unop: not, operand: {var: skip_scrape}}}
    then:
      - op: try
        body:
          - {op: call, action: photoscrape.cam_photopos, mode: RUN, args: {ref_8y: {lit: photo_8y}}}
          - {op: call, action: photoscrape.capture, mode: RUN,
             args: {sample_id: {var: sample_id}, save_dir: {var: save_dir},
                    filename: {lit: scraped.jpg}, profile: {lit: photoscrape}},
             assign: {var: scraped_shot}}
          - {op: call, action: photoscrape.cam_photohome, mode: RUN}
          - {op: call, action: photoscrape.scraped_overlay, mode: RUN,
             args: {summary_path: {var: cand_summary_path},
                    scraped_path: {field: {var: scraped_shot}, name: image_path}}}
        catch:
          - error: "*"
            body:
              - {op: comment, text: "对账补拍/叠加失败不阻断收尾; best-effort 收相机(此步再失败交外层 fault, 相机确需人工)"}
              - {op: call, action: photoscrape.cam_photohome, mode: RUN}
```

- [ ] **Step 4: 跑门流测试确认通过**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_photoscrape_gate_flow_offline.py -q`
Expected: 全 passed

- [ ] **Step 5: 修联动套件断言**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_photoscrape_four_stage_offline.py eit_ptlc/tests/test_photoscrape_reanalyze_offline.py -q`

若 four_stage 有"精确调用序列/次数"断言因第二次 cam_photopos/capture 破:按新序列更新断言(语义:补拍块在 scrape 循环后、scrape_finish 前;`_index` 取首次出现的断言通常不破)。修完复跑至绿。

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/config/operation/03_photoscrape/photoscrape_process.yaml eit_ptlc/tests/test_photoscrape_gate_flow_offline.py eit_ptlc/tests/test_photoscrape_four_stage_offline.py
git commit -m "feat(photoscrape): 刮后对账补拍块 — reconcile_photo knob(默认开)+try双保险+skip联动, 门流离线4例 (spec§5.1)"
```

---

### Task 9: 全量回归 + 使用说明

**Files:**
- Create: `docs/photoscrape_对账照片使用说明_20260715.md`
- Test: 全量套件

- [ ] **Step 1: 全量离线回归**

Run: `E:/Anaconda/python.exe -m pytest eit_ptlc/tests -q`
Expected: 基线 623 + 本包新增(约 +19)全部 passed,0 failed。任何红 → 修复后复跑。

- [ ] **Step 2: 写测量方法说明(spec §5.4)**

新建 `docs/photoscrape_对账照片使用说明_20260715.md`:

```markdown
# 刮后对账照片 — 读图与测量方法

每次刮取(reconcile_photo=true, 默认)后, case 目录新增:
- `scraped.jpg` / `scraped_normalized.jpg`: 刮后照片(原始帧 / 回放到归一化帧)
- `scraped_annotated.png`: 归一化刮后照片 + 下发时的指令路径叠加

## 读图
- 青色线 = 指令路径(与写入 PLC 的 g_sx/g_sy 同源, 经 preview_payload.json 落盘复用)
- 照片中白色刮槽 = 机床实际刮到的位置(物理真值)
- 黄色标注 = 程序认定的板坐标系: 四角 X + cm 标签, 原点 cm(0,0) 双圈, ±轴箭头。
  核对口诀: **原点角应贴点样边**。

## 测量总 bias
y 向错位(px) ÷ (plate_bbox 高度 px / plate_size_cm) = 相机链+机床链+刀具链总偏差(cm)。
配合包1 定位实验(fixed_summary_path 刮已知位置直线 + 卡尺量 Δ_machine)即可分解:
相机链残差 A = 对账图总偏差 − Δ_machine。修正入 config gcode.plate_origin_y(不加新旋钮)。

## 注意
- 旧 case / fixed 实验 summary 无 normalize_applied 或 preview_payload.json 时,
  对账叠加自动跳过(宁可无图不可错帧), scraped.jpg 仍留档可人工量。
- auto_rectify_tilt 每帧现测角度不落盘的历史坑已由 normalize_applied 回放契约根治;
  老录像/老 case 回放须先重跑 analyze 落新字段。
```

- [ ] **Step 3: Commit**

```bash
git add docs/photoscrape_对账照片使用说明_20260715.md
git commit -m "docs(photoscrape): 对账照片读图与bias测量方法 (spec§5.4)"
```

---

## 上机验收(合并后, 非本 plan 范围)

1. 真机 manual 手绘全流程一次:`scraped_annotated.png` 落盘、帧对齐(目测板边与归一化帧一致)。
2. 包1 定位实验(见 spec §8):拿 `Δ_machine` 修 `plate_origin_y`;复跑一次对账图确认残差归零。
3. `reconcile_photo=false` 跑一次确认节拍无补拍。
