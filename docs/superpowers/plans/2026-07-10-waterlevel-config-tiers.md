# 液位配置分层网关 + CLI 看板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `water_level_calib.json` 加一层"参数分三层 + 所有权网关 + CLI 一致性看板/广播台", 使调参时能在已标定基础上统一 ROI 尺寸/判据阈值, 并一眼看出 8 路是否漂。

**Architecture:** 新增一个纯函数网关模块 `waterlevel_config_tiers.py`(唯一懂"谁属哪层 / frac 如何由 px 派生 / 什么算漂"), 上面架一个薄 CLI 工具 `wl_config_board.py`(只读看板 + 唯一改真源的提交/广播入口)。真源文件格式**完全不动**, 运行时检测代码**零改**; "结构性防漂"通过**约束写者**(按层过滤写入)达成, 而非重构存储格式。

**Tech Stack:** Python 3.11 (conda env `platformupper`), 复用 `waterlevel_detector` 的 `rotation_matrix` / `box_to_roi_frac` / `ChannelCalibration.roi_pixels` 几何, 复用 `waterlevel_store` 的 `load/save_channel_configs` I/O。无新依赖。测试全离线, 无硬件。

设计源文档: `docs/superpowers/specs/2026-07-10-waterlevel-config-tiers-design.md`。

## Global Constraints

以下为项目级硬约束, **每个任务隐含包含**:

- **参考分辨率 = 1280×720** (`REFERENCE_CAPTURE = (1280, 720)`)。像素尺寸只在此声明分辨率下有意义; 由现有真源反推得到 (CH1 rot=0.8666° 时旋转后画布 1290×739, `133/1290=0.103101=roi_frac.fw`)。**不硬编码在散落各处**, 作为网关显式参数 (默认 `REFERENCE_CAPTURE`)。
- **运行时检测真源是 `roi_frac`(分辨率无关)**。`roi_frac = 像素 / 旋转后画布尺寸`, 旋转后画布尺寸依赖该通道自己的 `rotation_angle_deg`。**运行时检测代码零改** (照旧读 `roi_frac`); 各通道 frac 的微小差异是**有意的**(补偿各自 rotation), 不是漂移。
- **`split_tiers` 的 frac→px 与 `derive_roi_frac` 的 px→frac 是严格互逆的一对** (圆整误差 ≤1px)。已对 8 路真源验证: 往返 px 完全幂等, 反推 frac 与真源实测吻合 (偏差 < 1e-6)。
- **真源文件格式不动** (不重构成 `{shared, channels}`); 防漂靠**约束写者**(`apply_commit` 是唯一按层过滤写入点, 越权字段被丢弃), 非重构存储。
- **三层所有权** (层即所有权): 全局·判据 (`WaterLevelDetectParams` 全字段) + 全局·尺寸 (ROI 像素 w,h) → CLI 拥有; 逐通道·位姿 (`rotation_angle_deg` / `flow_direction` / ROI 位置 x,y) → 网页拥有。CLI commit **默认只落全局层**; 位姿仅 `--with-pose` 显式越权才写。
- **备份是写入前置条件**: 备份写失败 → **中止, 不写真源**。所有不可逆动作集中在 `wl_config_board --commit` 一处。
- **无共识不猜**: 一致性期望值取**严格多数 (> 半数)**; 无严格多数 (如 392×4 于 8 路, 4 不 > 4) → 报 `无共识`, 列出所有取值及其通道, **不猜、不自动选**。多数值是**展示概念**(只读看板用), 广播是**确定性动作**(源是 tuned 那一路的实测值, 不投票), 二者不耦合。
- **错误不静默造默认**: 真源不存在/解析失败 → 明确报错退出; tuned 通道号缺失/越界 → 拒绝; 退化 ROI (w≤0/h≤0/越界) → 抛错不写。
- **Python 环境**: `& "E:/Anaconda/envs/platformupper/python.exe"` (3.11)。
- **测试约定**: 沿用 `test_waterlevel_calib_*_offline.py` 家族的 `_run()/check()/main()` 独立脚本模式 (经 `python -m` 运行, 打印 `PASS/FAIL` 与 `共 N 用例, 失败 M`); **另加一行 pytest 桥** `def test_...(): assert _run() == 0` 使 AGENTS.md 记录的 `python -m pytest eit_ptlc/tests -q` 也能收集本文件 (避免 pytest 静默收 0 用例)。

---

## File Structure

| 文件 | 职责 | 变动 |
|------|------|------|
| `eit_ptlc/controller/waterlevel_config_tiers.py` | **网关**: 层定义 + `split_tiers`/`merge_tiers`/`derive_roi_frac` (frac↔px) + `audit` (一致性判据) + `apply_commit` (按层过滤写) | 新增 (Task 1-4) |
| `eit_ptlc/tools/wl_config_board.py` | **CLI 看板/提交台**: 只读渲染 + `--commit/--broadcast/--with-pose/--dry-run/--yes` (diff→备份→写→复核) | 新增 (Task 5-6) |
| `eit_ptlc/tools/wl_replay_tune.py` | 整定台: `w` 存盘后提示下一步命令 | 改动 1 处 (Task 7) |
| `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py` | 全套离线测试 (网关 + 看板 + 整定提示) | 新增 (贯穿 Task 1-7) |

网关是纯函数 (无 I/O 副作用, I/O 仍走 `waterlevel_store`); 看板是薄壳 (只做 argparse + 打印 + 备份/写)。读 (看板) 与写 (广播) 共用同一份 frac 派生 / 漂移判据实现。

---

### Task 1: 网关数据模型 + `split_tiers` + `derive_roi_frac` (读方向几何)

**Files:**
- Create: `eit_ptlc/controller/waterlevel_config_tiers.py`
- Test: `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py`

**Interfaces:**
- Consumes: `waterlevel_detector.{rotation_matrix, box_to_roi_frac, ChannelCalibration, WaterLevelDetectParams}`, `waterlevel_store.ChannelConfig`。
- Produces:
  - `REFERENCE_CAPTURE = (1280, 720)`, `GLOBAL_JUDGMENT_FIELDS: tuple[str, ...]`
  - `@dataclass(frozen=True) Pose(rotation_deg: float, flow: str, xy_px: Optional[tuple[int,int]])`
  - `@dataclass(frozen=True) TierView(judgment: WaterLevelDetectParams, size_px: Optional[tuple[int,int]], pose: Pose)`
  - `split_tiers(cfg: ChannelConfig, capture=REFERENCE_CAPTURE) -> TierView`
  - `derive_roi_frac(rotation_deg: float, xy_px: tuple[int,int], size_px: tuple[int,int], capture=REFERENCE_CAPTURE) -> tuple[float,float,float,float]`

- [ ] **Step 1: 写失败测试** — 创建测试文件, 含金标准快照 + split/derive 断言

创建 `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py`:

```python
"""液位配置分层网关 + CLI 看板离线测试
========================================
覆盖: split_tiers/derive_roi_frac (frac↔px 金标准) / merge_tiers (往返+退化守卫) /
      audit (严格多数/无共识, 真源 h 漂移金标准) / apply_commit (按层过滤/广播) /
      wl_config_board (只读渲染/dry-run/备份失败中止/广播写) / wl_replay_tune 存盘提示。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline
    或 (随套件)  & "E:/Anaconda/envs/platformupper/python.exe" -m pytest eit_ptlc/tests/test_waterlevel_config_tiers_offline.py -q
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    WaterLevelDetectParams,
)
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    load_channel_configs,
    save_channel_configs,
)


def _real_snapshot() -> dict[int, ChannelConfig]:
    """water_level_calib.json 快照 (2026-07-10); 参数均为检测器默认。
    用作金标准且与可变真源文件解耦 (frac 是真源, split_tiers 只读 frac, 故 roi_bbox 略)。"""
    rows = {
        1: (0.8665927624189634, "right_to_left", (0.10155, 0.006766, 0.103101, 0.537212)),
        2: (-0.6962686000719428, "right_to_left", (0.072981, 0.014966, 0.103261, 0.522449)),
        3: (-0.0, "right_to_left", (0.078125, 0.0, 0.103906, 0.55)),
        4: (0.5926938186167044, "right_to_left", (0.0777, 0.0, 0.103341, 0.527967)),
        5: (1.6560493162756562, "left_to_right", (0.205385, 0.0, 0.102308, 0.518519)),
        6: (0.5856264148077176, "left_to_right", (0.207459, 0.0, 0.103341, 0.534789)),
        7: (1.1632062452411367, "left_to_right", (0.206337, 0.0, 0.102782, 0.526174)),
        8: (-0.1932396703826922, "left_to_right", (0.208268, 0.001381, 0.103744, 0.541436)),
    }
    out: dict[int, ChannelConfig] = {}
    for ch, (rot, flow, frac) in rows.items():
        out[ch] = ChannelConfig(
            ChannelCalibration(rot, None, flow, frac), WaterLevelDetectParams())
    return out


def _run() -> int:
    results = {"pass": 0}
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            results["pass"] += 1
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # ============================ Task 1: split_tiers / derive_roi_frac ============================
    from eit_ptlc.controller.waterlevel_config_tiers import (
        REFERENCE_CAPTURE, split_tiers, derive_roi_frac,
    )
    # 金标准: 真源 CH1 / CH5 (仅 frac; split 读 frac 还原 px)
    ch1 = ChannelConfig(
        ChannelCalibration(0.8665927624189634, None, "right_to_left",
                           (0.10155, 0.006766, 0.103101, 0.537212)),
        WaterLevelDetectParams())
    ch5 = ChannelConfig(
        ChannelCalibration(1.6560493162756562, None, "left_to_right",
                           (0.205385, 0.0, 0.102308, 0.518519)),
        WaterLevelDetectParams())

    t1 = split_tiers(ch1)
    check("split_ch1_size", t1.size_px == (133, 397), str(t1.size_px))
    check("split_ch1_xy", t1.pose.xy_px == (131, 5), str(t1.pose.xy_px))
    check("split_ch1_flow", t1.pose.flow == "right_to_left", t1.pose.flow)
    check("split_ch1_rot", abs(t1.pose.rotation_deg - 0.8665927624189634) < 1e-9, str(t1.pose.rotation_deg))
    check("split_ch1_judgment", t1.judgment.diff_threshold == 5.0, str(t1.judgment.diff_threshold))

    t5 = split_tiers(ch5)
    check("split_ch5_size", t5.size_px == (133, 392), str(t5.size_px))
    check("split_ch5_xy", t5.pose.xy_px == (267, 0), str(t5.pose.xy_px))

    # derive_roi_frac 金标准: (rot, xy, size) → frac, 与真源实测吻合 (≤1e-4)
    f1 = derive_roi_frac(0.8665927624189634, (131, 5), (133, 397))
    exp1 = (0.10155, 0.006766, 0.103101, 0.537212)
    check("derive_ch1_frac", max(abs(a - b) for a, b in zip(f1, exp1)) < 1e-4, f"{f1} vs {exp1}")

    # 未标定通道 → size_px None, pose.xy None, 但保留 flow
    unc = ChannelConfig(ChannelCalibration(0.0, None, "bottom_to_top", None), WaterLevelDetectParams())
    tu = split_tiers(unc)
    check("split_uncalib_size_none", tu.size_px is None, str(tu.size_px))
    check("split_uncalib_xy_none", tu.pose.xy_px is None, str(tu.pose.xy_px))
    check("split_uncalib_flow_kept", tu.pose.flow == "bottom_to_top", tu.pose.flow)

    total = results["pass"] + len(failures)
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def test_waterlevel_config_tiers():
    """pytest 桥: 让 `pytest eit_ptlc/tests -q` 也覆盖本文件。"""
    assert _run() == 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return _run()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: FAIL — `ModuleNotFoundError: No module named 'eit_ptlc.controller.waterlevel_config_tiers'`

- [ ] **Step 3: 建网关模块 (模型 + split + derive)**

创建 `eit_ptlc/controller/waterlevel_config_tiers.py`:

```python
"""液位配置分层网关 (参数分三层 + 所有权 + frac 派生 + 一致性判据)
================================================================
第一性原理 (见 docs/superpowers/specs/2026-07-10-waterlevel-config-tiers-design.md):
    液位标定真源 water_level_calib.json 的每个参数按"定它需要什么信息"天然分三层, 层即所有权:
      - 全局·判据 (WaterLevelDetectParams 全字段): 一段时序录制才能定 → CLI 回放整定拥有;
      - 全局·尺寸  (ROI 像素 w,h, 在参考分辨率下): 同上 → CLI 拥有;
      - 逐通道·位姿 (rotation / flow / ROI 位置 x,y): 实时画面即可定 → 网页标定 UI 拥有。
    本模块是唯一懂"谁属哪层 / frac 如何由 px 派生 / 什么算漂"的网关。两个薄面 (网页/CLI)
    各自只提交自己拥有的层; apply_commit 是唯一的按层过滤写入点 (越权字段被丢弃)。

刻意约束:
    - 运行时检测真源是 roi_frac (分辨率无关); 像素 w,h 只在声明的参考分辨率 REFERENCE_CAPTURE
      下有意义, 是"人看的权威统一值"。frac 是派生值, 按每通道自己的 rotation 换算 (正反严格互逆,
      圆整误差 ≤1px)。运行时检测代码零改。
    - 真源文件格式不动; 防漂靠约束写者, 非重构存储。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Optional

from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    WaterLevelDetectParams,
    box_to_roi_frac,
    rotation_matrix,
)
from eit_ptlc.controller.waterlevel_store import ChannelConfig

# 像素尺寸的声明参考分辨率 (由现有真源反推: CH1 rot=0.8666° 时画布 1290x739, 133/1290=0.103101)。
REFERENCE_CAPTURE = (1280, 720)

# 全局·判据层字段 = WaterLevelDetectParams 全字段。
GLOBAL_JUDGMENT_FIELDS = (
    "roi_crop_x",
    "roi_crop_y",
    "blur_ksize",
    "diff_threshold",
    "wet_pixel_threshold",
    "front_ratio_level",
)


@dataclass(frozen=True)
class Pose:
    """逐通道·位姿层。xy_px 为旋转后画布 (参考分辨率) 的 ROI 左上角像素; 未标定通道为 None。"""
    rotation_deg: float
    flow: str
    xy_px: Optional[tuple[int, int]]


@dataclass(frozen=True)
class TierView:
    """一个通道拆成三层的视图。size_px=None 表示未标定 (无 ROI); pose 恒在 (承载 rotation+flow)。"""
    judgment: WaterLevelDetectParams
    size_px: Optional[tuple[int, int]]
    pose: Pose


def _rotated_canvas(rotation_deg: float, capture: tuple[int, int]) -> tuple[int, int]:
    """参考分辨率下, 该 rotation 的旋转后画布尺寸 (rw, rh)。"""
    _M, (rw, rh) = rotation_matrix(rotation_deg, capture[0], capture[1])
    return rw, rh


def split_tiers(cfg: ChannelConfig, capture: tuple[int, int] = REFERENCE_CAPTURE) -> TierView:
    """把一个通道配置拆成 判据 / 尺寸px / 位姿 三层 (读方向)。

    尺寸/位置像素在 capture 参考分辨率的旋转后画布下由 roi_frac 还原 (round)。
    未标定 (roi_frac 与 roi_bbox 皆空) → size_px=None, pose.xy_px=None (但保留 rotation+flow)。
    """
    calib = cfg.calib
    pose_xy: Optional[tuple[int, int]] = None
    size_px: Optional[tuple[int, int]] = None
    if calib.calibrated:
        rw, rh = _rotated_canvas(calib.rotation_angle_deg, capture)
        px = calib.roi_pixels(rw, rh)
        if px is not None:
            x, y, w, h = px
            pose_xy = (x, y)
            size_px = (w, h)
    pose = Pose(rotation_deg=calib.rotation_angle_deg, flow=calib.flow_direction, xy_px=pose_xy)
    return TierView(judgment=cfg.params, size_px=size_px, pose=pose)


def derive_roi_frac(rotation_deg: float, xy_px: tuple[int, int], size_px: tuple[int, int],
                    capture: tuple[int, int] = REFERENCE_CAPTURE) -> tuple[float, float, float, float]:
    """位姿 rotation + ROI 像素 (x,y,w,h, 参考分辨率) → 分辨率无关 roi_frac。

    按该 rotation 自己的旋转后画布尺寸换算 (复用 box_to_roi_frac), 与 split_tiers 严格互逆。
    """
    rw, rh = _rotated_canvas(rotation_deg, capture)
    x, y = xy_px
    w, h = size_px
    return box_to_roi_frac(x, y, w, h, rw, rh)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: PASS 全部 (`共 12 用例, 失败 0`)

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/controller/waterlevel_config_tiers.py eit_ptlc/tests/test_waterlevel_config_tiers_offline.py
git commit -m "feat(waterlevel): 配置分层网关 split_tiers/derive_roi_frac (frac↔px 读方向)"
```

---

### Task 2: `merge_tiers` (写方向几何 + frac 派生 + roi_bbox materialize + 退化守卫)

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_config_tiers.py` (追加 `merge_tiers`)
- Test: `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py` (追加往返/守卫断言)

**Interfaces:**
- Consumes: Task 1 的 `Pose`, `split_tiers`, `derive_roi_frac`, `_rotated_canvas`, `REFERENCE_CAPTURE`。
- Produces: `merge_tiers(judgment: WaterLevelDetectParams, size_px: Optional[tuple[int,int]], pose: Pose, capture=REFERENCE_CAPTURE) -> ChannelConfig`。标定成立当且仅当 `size_px` 与 `pose.xy_px` 皆非空; 退化 ROI 抛 `ValueError`。

- [ ] **Step 1: 写失败测试** — 在 `_run()` 的 Task 1 块之后、`total = ...` 之前插入:

```python
    # ============================ Task 2: merge_tiers 往返 + 守卫 ============================
    from eit_ptlc.controller.waterlevel_config_tiers import merge_tiers, Pose
    # round-trip: split → merge → split px 幂等 (8 路真源快照)
    for ch, cfg in _real_snapshot().items():
        a = split_tiers(cfg)
        merged = merge_tiers(a.judgment, a.size_px, a.pose)
        b = split_tiers(merged)
        check(f"roundtrip_ch{ch}_size", a.size_px == b.size_px, f"{a.size_px} != {b.size_px}")
        check(f"roundtrip_ch{ch}_xy", a.pose.xy_px == b.pose.xy_px, f"{a.pose.xy_px} != {b.pose.xy_px}")
    # roi_bbox materialize == px 框 (CH1); roi_frac 被设置
    m1 = merge_tiers(WaterLevelDetectParams(), (133, 397),
                     Pose(0.8665927624189634, "right_to_left", (131, 5)))
    check("merge_bbox_materialized", m1.calib.roi_bbox == (131, 5, 133, 397), str(m1.calib.roi_bbox))
    check("merge_frac_set", m1.calib.roi_frac is not None, "")

    def _raises_value(fn) -> bool:
        try:
            fn()
            return False
        except ValueError:
            return True

    # 退化 ROI → ValueError
    check("merge_degenerate_w0",
          _raises_value(lambda: merge_tiers(WaterLevelDetectParams(), (0, 50),
                                            Pose(0.0, "left_to_right", (10, 10)))), "")
    check("merge_out_of_bounds",
          _raises_value(lambda: merge_tiers(WaterLevelDetectParams(), (100, 50),
                                            Pose(0.0, "left_to_right", (1270, 10)))), "")
    # size None → 未标定 (仅保留 rotation+flow+判据)
    mu = merge_tiers(WaterLevelDetectParams(), None, Pose(2.0, "bottom_to_top", None))
    check("merge_uncalib_frac_none", mu.calib.roi_frac is None, str(mu.calib.roi_frac))
    check("merge_uncalib_flow", mu.calib.flow_direction == "bottom_to_top", mu.calib.flow_direction)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: FAIL — `ImportError: cannot import name 'merge_tiers'`

- [ ] **Step 3: 实现 `merge_tiers`** — 追加到 `waterlevel_config_tiers.py` 末尾 (在 `derive_roi_frac` 之后):

```python
def merge_tiers(judgment: WaterLevelDetectParams, size_px: Optional[tuple[int, int]],
                pose: Pose, capture: tuple[int, int] = REFERENCE_CAPTURE) -> ChannelConfig:
    """三层 → 通道配置 (写方向), 含 frac 派生 + roi_bbox materialize。

    标定成立当且仅当 size_px 与 pose.xy_px 皆非空 (有位置可锚 + 有尺寸)。此时:
      roi_frac = derive_roi_frac(rotation, xy, size); roi_bbox = 参考分辨率下 frac 还原的像素框。
    退化 ROI (w<=0 / h<=0 / 越出参考画布) → ValueError (不写)。
    否则 (无位置或无尺寸) → 未标定 calib (仅保留 rotation + flow + 判据)。
    """
    if size_px is not None and pose.xy_px is not None:
        w, h = size_px
        x, y = pose.xy_px
        rw, rh = _rotated_canvas(pose.rotation_deg, capture)
        if w <= 0 or h <= 0:
            raise ValueError(f"退化 ROI 尺寸 (w={w}, h={h})")
        if not (0 <= x and 0 <= y and x + w <= rw and y + h <= rh):
            raise ValueError(f"ROI 越出参考画布: box=({x},{y},{w},{h}) 画布=({rw},{rh})")
        roi_frac = derive_roi_frac(pose.rotation_deg, (x, y), (w, h), capture)
        roi_bbox = ChannelCalibration(
            rotation_angle_deg=pose.rotation_deg, roi_frac=roi_frac).roi_pixels(rw, rh)
        calib = ChannelCalibration(
            rotation_angle_deg=pose.rotation_deg,
            roi_bbox=tuple(roi_bbox),
            flow_direction=pose.flow,
            roi_frac=roi_frac,
        )
    else:
        calib = ChannelCalibration(
            rotation_angle_deg=pose.rotation_deg,
            roi_bbox=None,
            flow_direction=pose.flow,
            roi_frac=None,
        )
    return ChannelConfig(calib=calib, params=judgment)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: PASS 全部 (`共 30 用例, 失败 0`) — 含 8 路 ×2 往返 + 6 守卫/materialize。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/controller/waterlevel_config_tiers.py eit_ptlc/tests/test_waterlevel_config_tiers_offline.py
git commit -m "feat(waterlevel): merge_tiers 写方向 (frac 派生+bbox materialize+退化守卫)"
```

---

### Task 3: `audit` (一致性判据: 严格多数 / 无共识)

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_config_tiers.py` (追加 `FieldAudit`/`AuditReport`/`_consensus`/`audit`)
- Test: `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py`

**Interfaces:**
- Consumes: Task 1-2 的 `split_tiers`, `GLOBAL_JUDGMENT_FIELDS`。
- Produces:
  - `@dataclass(frozen=True) FieldAudit(field: str, consistent: bool, expected: Optional[Any], deviants: dict[int,Any], values: dict[int,Any])`
  - `@dataclass(frozen=True) AuditReport(fields: list[FieldAudit], uncalibrated: list[int])`
  - `audit(configs: dict[int, ChannelConfig], capture=REFERENCE_CAPTURE) -> AuditReport` — `fields` 顺序为 6 判据字段 + `"w"` + `"h"`。

- [ ] **Step 1: 写失败测试** — 在 Task 2 块之后插入:

```python
    # ============================ Task 3: audit 一致性判据 ============================
    from eit_ptlc.controller.waterlevel_config_tiers import audit
    rep = audit(_real_snapshot())
    fa = {f.field: f for f in rep.fields}
    check("audit_w_consistent", fa["w"].consistent and fa["w"].expected == 133, str(fa["w"]))
    check("audit_h_inconsistent", not fa["h"].consistent, str(fa["h"]))
    check("audit_h_no_consensus", fa["h"].expected is None, str(fa["h"].expected))   # 392x4 于 8 路, 非严格多数
    check("audit_h_values_8", len(fa["h"].values) == 8, str(fa["h"].values))
    check("audit_judgment_consistent",
          fa["diff_threshold"].consistent and fa["diff_threshold"].expected == 5.0, str(fa["diff_threshold"]))
    check("audit_no_uncalibrated", rep.uncalibrated == [], str(rep.uncalibrated))

    # 合成: 5 路 h=392 严格多数, 3 路偏离 → expected=392, deviants={6,7,8}
    synth: dict[int, ChannelConfig] = {}
    hs = {1: 392, 2: 392, 3: 392, 4: 392, 5: 392, 6: 380, 7: 381, 8: 382}
    for ch, cfg in _real_snapshot().items():
        tv = split_tiers(cfg)
        synth[ch] = merge_tiers(tv.judgment, (tv.size_px[0], hs[ch]), tv.pose)
    fh = {f.field: f for f in audit(synth).fields}["h"]
    check("audit_majority_expected", fh.expected == 392, str(fh.expected))
    check("audit_majority_deviants", sorted(fh.deviants) == [6, 7, 8], str(fh.deviants))

    # 合成: 一路未标定 → uncalibrated 列出且不计入字段值
    snap2 = _real_snapshot()
    snap2[3] = ChannelConfig(ChannelCalibration(0.0, None, "right_to_left", None), WaterLevelDetectParams())
    rep3 = audit(snap2)
    check("audit_uncalib_listed", rep3.uncalibrated == [3], str(rep3.uncalibrated))
    fh3 = {f.field: f for f in rep3.fields}["h"]
    check("audit_uncalib_excluded", 3 not in fh3.values, str(fh3.values))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: FAIL — `ImportError: cannot import name 'audit'`

- [ ] **Step 3: 实现 `audit`** — 追加到 `waterlevel_config_tiers.py` (在 `merge_tiers` 之后):

```python
@dataclass(frozen=True)
class FieldAudit:
    """单个全局层字段的一致性判据。

    consistent: 已标定各路是否全等。
    expected:   一致值 / 严格多数 (>半数) 值; 无共识时为 None。
    deviants:   偏离 expected 的通道 → 值 (一致 / 无共识时为空)。
    values:     已标定各路取值 (无共识时的主展示; 恒填)。
    """
    field: str
    consistent: bool
    expected: Optional[Any]
    deviants: dict[int, Any]
    values: dict[int, Any]


@dataclass(frozen=True)
class AuditReport:
    fields: list[FieldAudit]            # 6 判据字段 + 'w' + 'h'
    uncalibrated: list[int]             # 无 ROI 的通道号 (升序)


def _consensus(values: dict[int, Any]) -> tuple[bool, Optional[Any]]:
    """(consistent, expected)。consistent=全等; expected=一致值 / 严格多数(>半数)值; 无共识时 None。

    展示概念: 多数值只用于提示"谁偏离了大伙", 不用于广播 (广播源是确定的 tuned 那一路)。
    """
    if not values:
        return True, None
    uniq = set(values.values())
    if len(uniq) == 1:
        return True, next(iter(uniq))
    n = len(values)
    val, cnt = Counter(values.values()).most_common(1)[0]
    if cnt > n / 2:
        return False, val         # 严格多数
    return False, None            # 无共识 (平票 / 无过半) → 不猜


def _field_audit(field: str, values: dict[int, Any]) -> FieldAudit:
    consistent, expected = _consensus(values)
    deviants = {ch: v for ch, v in values.items() if expected is not None and v != expected}
    return FieldAudit(field=field, consistent=consistent, expected=expected,
                      deviants=deviants, values=values)


def audit(configs: dict[int, ChannelConfig],
          capture: tuple[int, int] = REFERENCE_CAPTURE) -> AuditReport:
    """8 路全局层一致性判据 (只读)。未标定通道 (无 ROI) 单列, 不参与字段一致性。"""
    views = {ch: split_tiers(cfg, capture) for ch, cfg in configs.items()}
    calibrated = {ch: v for ch, v in views.items() if v.size_px is not None}
    uncalibrated = sorted(ch for ch in views if ch not in calibrated)

    fields: list[FieldAudit] = []
    for name in GLOBAL_JUDGMENT_FIELDS:
        vals = {ch: getattr(configs[ch].params, name) for ch in calibrated}
        fields.append(_field_audit(name, vals))
    for i, name in enumerate(("w", "h")):
        vals = {ch: v.size_px[i] for ch, v in calibrated.items()}
        fields.append(_field_audit(name, vals))
    return AuditReport(fields=fields, uncalibrated=uncalibrated)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: PASS 全部 (`共 41 用例, 失败 0`)。**关键金标准**: `audit_h_no_consensus` 证明当前真源 `h` 漂移 (392×4 非严格多数) 被抓到。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/controller/waterlevel_config_tiers.py eit_ptlc/tests/test_waterlevel_config_tiers_offline.py
git commit -m "feat(waterlevel): audit 一致性判据 (严格多数/无共识, 抓到真源 h 漂移)"
```

---

### Task 4: `apply_commit` (唯一按层过滤写入点 + 广播)

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_config_tiers.py` (追加 `apply_commit`)
- Test: `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py`

**Interfaces:**
- Consumes: Task 1-3 的 `split_tiers`, `merge_tiers`, `Pose`, `audit`。
- Produces: `apply_commit(configs: dict[int, ChannelConfig], ch: int, tuned: ChannelConfig, *, broadcast_global: bool, with_pose: bool, capture=REFERENCE_CAPTURE) -> dict[int, ChannelConfig]`。
  - 判据+尺寸 (全局) 落 `ch` (默认) 或全部已标定通道 (`broadcast_global`); 各通道尺寸按自身 rotation+现位置重派 frac。
  - 位姿仅当 `with_pose` 且是 `ch` 自己才写。未标定通道参与广播只落判据 (尺寸无锚跳过)。
  - `ch` 不在 `configs` 或 `tuned` 无 ROI → `ValueError`。

- [ ] **Step 1: 写失败测试** — 在 Task 3 块之后插入:

```python
    # ============================ Task 4: apply_commit 按层过滤 + 广播 ============================
    from eit_ptlc.controller.waterlevel_config_tiers import apply_commit
    base = _real_snapshot()
    # tuned = CH5 但位姿全改 (rotation+xy), 用来验证 with_pose 过滤
    tv5 = split_tiers(base[5])
    tuned5 = merge_tiers(tv5.judgment, tv5.size_px, Pose(9.9, "left_to_right", (300, 40)))

    # with_pose=False: 位姿不写入 → CH5 保持原 rotation/xy
    r_nopose = apply_commit(base, 5, tuned5, broadcast_global=False, with_pose=False)
    o5 = split_tiers(base[5]); n5 = split_tiers(r_nopose[5])
    check("commit_pose_filtered_xy", n5.pose.xy_px == o5.pose.xy_px, f"{n5.pose.xy_px} vs {o5.pose.xy_px}")
    check("commit_pose_filtered_rot", abs(n5.pose.rotation_deg - o5.pose.rotation_deg) < 1e-9, str(n5.pose.rotation_deg))

    # with_pose=True: 位姿写入 → CH5 变成 tuned 的位姿
    r_pose = apply_commit(base, 5, tuned5, broadcast_global=False, with_pose=True)
    n5p = split_tiers(r_pose[5])
    check("commit_with_pose_xy", n5p.pose.xy_px == (300, 40), str(n5p.pose.xy_px))
    check("commit_with_pose_rot", abs(n5p.pose.rotation_deg - 9.9) < 1e-9, str(n5p.pose.rotation_deg))

    # 广播: 全局尺寸落 8 路 → 各路 size_px==(133,392), 位置不变, audit h 一致
    r_bc = apply_commit(base, 5, base[5], broadcast_global=True, with_pose=False)
    sizes = {ch: split_tiers(cfg).size_px for ch, cfg in r_bc.items()}
    check("broadcast_all_size", all(s == (133, 392) for s in sizes.values()), str(sizes))
    pos_kept = all(split_tiers(r_bc[ch]).pose.xy_px == split_tiers(base[ch]).pose.xy_px for ch in r_bc)
    check("broadcast_pos_kept", pos_kept, "")
    fh_bc = {f.field: f for f in audit(r_bc).fields}["h"]
    check("broadcast_h_consistent", fh_bc.consistent and fh_bc.expected == 392, str(fh_bc))
    # 各路 fh frac 不同 (补偿各自 rotation) — 有意的
    fh_fracs = {ch: cfg.calib.roi_frac[3] for ch, cfg in r_bc.items()}
    check("broadcast_fracs_differ", len({round(f, 6) for f in fh_fracs.values()}) > 1, str(fh_fracs))

    # 未标定通道参与广播: 只落判据, 尺寸跳过 (保持未标定)
    base_u = _real_snapshot()
    base_u[3] = ChannelConfig(ChannelCalibration(0.0, None, "right_to_left", None),
                              WaterLevelDetectParams(diff_threshold=1.0))
    r_u = apply_commit(base_u, 5, base_u[5], broadcast_global=True, with_pose=False)
    check("broadcast_uncalib_still_uncalib", r_u[3].calib.roi_frac is None, str(r_u[3].calib.roi_frac))
    check("broadcast_uncalib_judgment_updated",
          r_u[3].params.diff_threshold == base_u[5].params.diff_threshold, str(r_u[3].params.diff_threshold))

    # 错误: tuned 无 ROI → ValueError
    tuned_noroi = ChannelConfig(ChannelCalibration(0.0, None, "left_to_right", None), WaterLevelDetectParams())
    check("commit_tuned_no_roi_raises",
          _raises_value(lambda: apply_commit(base, 5, tuned_noroi, broadcast_global=False, with_pose=False)), "")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: FAIL — `ImportError: cannot import name 'apply_commit'`

- [ ] **Step 3: 实现 `apply_commit`** — 追加到 `waterlevel_config_tiers.py` (在 `audit` 之后):

```python
def apply_commit(configs: dict[int, ChannelConfig], ch: int, tuned: ChannelConfig, *,
                 broadcast_global: bool, with_pose: bool,
                 capture: tuple[int, int] = REFERENCE_CAPTURE) -> dict[int, ChannelConfig]:
    """唯一的按层过滤写入点 (所有权从"文档约定"升格为"代码强制")。

    - 判据层 + 尺寸层 (全局): 落 ch (默认) 或 broadcast_global 时落全部通道;
      每通道尺寸按自身 rotation + 现位置重新派生 frac (故各路 frac 各异是有意的)。
    - 位姿层 (逐通道): 仅当 with_pose 且是 tuned 自己的通道 ch 才写入 (显式越权逃生口)。
    - 尺寸层需要一个位置来锚定 (pose.xy_px); 无位置的通道 (未标定且不给位姿) 只落判据层。
    """
    if ch not in configs:
        raise ValueError(f"CH{ch} 不在真源通道中: {sorted(configs)}")
    tv = split_tiers(tuned, capture)
    if tv.size_px is None or tv.pose.xy_px is None:
        raise ValueError(f"tuned CH{ch} 无 ROI, 不能作全局层来源")

    targets = set(configs) if broadcast_global else {ch}
    result: dict[int, ChannelConfig] = {}
    for c, cfg in configs.items():
        cur = split_tiers(cfg, capture)
        pose = tv.pose if (c == ch and with_pose) else cur.pose
        if c in targets:
            judgment = tv.judgment
            size_px = tv.size_px if pose.xy_px is not None else None   # 无位置可锚 → 尺寸跳过
        else:
            judgment = cur.judgment
            size_px = cur.size_px
        result[c] = merge_tiers(judgment, size_px, pose, capture)
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: PASS 全部 (`共 53 用例, 失败 0`)

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/controller/waterlevel_config_tiers.py eit_ptlc/tests/test_waterlevel_config_tiers_offline.py
git commit -m "feat(waterlevel): apply_commit 按层过滤写 (默认只落全局层, --broadcast/--with-pose)"
```

---

### Task 5: CLI 看板只读模式 (`wl_config_board.py`)

**Files:**
- Create: `eit_ptlc/tools/wl_config_board.py`
- Test: `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py`

**Interfaces:**
- Consumes: 网关 `audit`/`split_tiers`/`REFERENCE_CAPTURE`; `waterlevel_store.{load_channel_configs, save_channel_configs, ChannelConfig}`。
- Produces:
  - `_default_calib_path() -> Path`
  - `load_true_source(path: Path) -> dict[int, ChannelConfig]` (不存在/空 → `SystemExit`)
  - `render_report(configs, capture=REFERENCE_CAPTURE) -> list[str]` (纯函数; 不一致字段行首 `✗`, 无共识列全值, 未标定单列)
  - `cmd_show(path, capture=REFERENCE_CAPTURE) -> int`
  - `main(argv=None) -> int`

- [ ] **Step 1: 写失败测试** — 在 Task 4 块之后插入:

```python
    # ============================ Task 5: 看板只读渲染 ============================
    from eit_ptlc.tools import wl_config_board as board
    lines = board.render_report(_real_snapshot())
    text = "\n".join(lines)
    check("board_h_flagged", any("✗" in l and "无共识" in l for l in lines), text)
    check("board_w_ok", any(l.lstrip().startswith("w ") and "一致" in l for l in lines), text)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "calib.json"
        save_channel_configs(p, _real_snapshot())
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = board.cmd_show(p)
        check("board_show_rc0", rc == 0, str(rc))
        check("board_show_prints", "液位配置看板" in buf.getvalue(), "")
        missing = Path(td) / "nope.json"

    def _show_missing_exits() -> bool:
        try:
            board.load_true_source(missing)   # td 已删, 文件必不存在
            return False
        except SystemExit:
            return True
    check("board_missing_source_exits", _show_missing_exits(), "")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: FAIL — `ModuleNotFoundError: No module named 'eit_ptlc.tools.wl_config_board'`

- [ ] **Step 3: 建看板模块 (只读部分)**

创建 `eit_ptlc/tools/wl_config_board.py`:

```python
"""液位配置一致性看板 + 提交/广播台 (CLI, 上位机侧)
====================================================
与 wl_replay_tune 同级同类。唯一改真源 water_level_calib.json 的入口 (不可逆动作集中一处, 可审计)。

只读 (默认):
    python -m eit_ptlc.tools.wl_config_board
    读真源 → 打印 8 通道 × 各全局层参数对齐表; 不一致字段行首标 ✗ + 期望值(多数)/无共识全值 +
    偏离通道号; 未标定通道 (无 ROI) 单列告警; 位姿层不判漂 (下期由网页走网关)。

提交/广播 (Task 6):
    python -m eit_ptlc.tools.wl_config_board --commit <stem>.tuned.json [--broadcast] [--with-pose] [--dry-run] [--yes]

所有权 (spec §6): CLI commit 默认只落全局层; 回放时画的角/拖的框只算本地草稿, 非 --with-pose 不写。
网页永远只写位姿 (下期通过网关强制)。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from eit_ptlc.controller.waterlevel_config_tiers import (
    GLOBAL_JUDGMENT_FIELDS,
    REFERENCE_CAPTURE,
    apply_commit,
    audit,
    split_tiers,
)
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    load_channel_configs,
    save_channel_configs,
)


def _default_calib_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "water_level_calib.json"


def load_true_source(path: Path) -> dict[int, ChannelConfig]:
    """读真源; 不存在/空/解析失败 → 明确报错退出 (不静默造默认)。"""
    if not path.is_file():
        raise SystemExit(f"[看板] 真源不存在: {path}")
    configs = load_channel_configs(path)
    if not configs:
        raise SystemExit(f"[看板] 真源为空或解析失败: {path}")
    return configs


def render_report(configs: dict[int, ChannelConfig],
                  capture: tuple[int, int] = REFERENCE_CAPTURE) -> list[str]:
    """把只读看板渲染成文本行 (纯函数, 供打印与测试)。不一致字段行首 ✗。"""
    rep = audit(configs, capture)
    chans = sorted(configs)
    lines = [f"液位配置看板 (参考分辨率 {capture[0]}x{capture[1]}; 通道 {chans})", ""]
    header = "  " + "字段".ljust(18) + "".join(f"CH{ch}".rjust(8) for ch in chans) + "   判据"
    lines.append(header)
    lines.append("-" * (len(header) + 4))
    for fa in rep.fields:
        mark = "  " if fa.consistent else "✗ "
        row = mark + fa.field.ljust(18)
        for ch in chans:
            v = fa.values.get(ch)
            row += ("-" if v is None else f"{v}").rjust(8)
        if fa.consistent:
            verdict = "一致"
        elif fa.expected is not None:
            verdict = f"期望(多数)={fa.expected}, 偏离 CH{sorted(fa.deviants)}"
        else:
            byval: dict = {}
            for ch, v in sorted(fa.values.items()):
                byval.setdefault(v, []).append(ch)
            verdict = "无共识: " + "; ".join(f"{v}→CH{chs}" for v, chs in byval.items())
        lines.append(row + "   " + verdict)
    if rep.uncalibrated:
        lines.append("")
        lines.append(f"⚠ 未标定通道 (无 ROI): {rep.uncalibrated}")
    return lines


def cmd_show(path: Path, capture: tuple[int, int] = REFERENCE_CAPTURE) -> int:
    for line in render_report(load_true_source(path), capture):
        print(line)
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="液位配置一致性看板 + 提交/广播台")
    ap.add_argument("--calib", default=None, help="真源路径 (默认 config/water_level_calib.json)")
    args = ap.parse_args(argv)
    path = Path(args.calib) if args.calib else _default_calib_path()
    return cmd_show(path)


if __name__ == "__main__":
    raise SystemExit(main())
```

> 说明: 采用 `✗` 行首标记 + `无共识`/`偏离` 判据文字表达"漂", 不用 ANSI 颜色 (终端友好 + 断言稳健; 颜色是 YAGNI 的锦上添花)。Task 6 会把 `main` 扩成含 `--commit` 分派。

- [ ] **Step 4: 跑测试确认通过**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: PASS 全部 (`共 58 用例, 失败 0`)

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/tools/wl_config_board.py eit_ptlc/tests/test_waterlevel_config_tiers_offline.py
git commit -m "feat(waterlevel): wl_config_board 只读看板 (标漂/无共识/未标定告警)"
```

---

### Task 6: CLI 看板提交/广播模式 (diff → 备份 → 写 → 复核)

**Files:**
- Modify: `eit_ptlc/tools/wl_config_board.py` (追加 `diff_lines`/`_backup`/`cmd_commit`, 扩 `main`)
- Test: `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py`

**Interfaces:**
- Consumes: Task 5 的 `load_true_source`/`render_report`; 网关 `apply_commit`/`split_tiers`/`GLOBAL_JUDGMENT_FIELDS`; `shutil`, `datetime`。
- Produces:
  - `diff_lines(old_configs, new_configs, capture=REFERENCE_CAPTURE) -> list[str]`
  - `_backup(path: Path, now: str) -> Path` (失败抛 `OSError`)
  - `cmd_commit(path, tuned_path, *, broadcast, with_pose, dry_run, yes, now: Optional[str]=None, capture=REFERENCE_CAPTURE, confirm: Callable[[str], str]=input) -> int` — 返回码: 0 成功/dry-run, 1 用户取消, 2 输入非法/退化, 3 备份失败中止。
  - `main` 支持 `--commit/--broadcast/--with-pose/--dry-run/--yes`。

- [ ] **Step 1: 写失败测试** — 在 Task 5 块之后插入:

```python
    # ============================ Task 6: 看板提交/广播 (备份前置/dry-run) ============================
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "calib.json"
        save_channel_configs(src, _real_snapshot())
        tuned_p = Path(td) / "ch5.tuned.json"
        save_channel_configs(tuned_p, {5: _real_snapshot()[5]})
        before = src.read_bytes()

        # dry-run: 不备份不写
        with contextlib.redirect_stdout(io.StringIO()):
            rc = board.cmd_commit(src, tuned_p, broadcast=True, with_pose=False,
                                  dry_run=True, yes=True, now="T")
        check("commit_dryrun_rc0", rc == 0, str(rc))
        check("commit_dryrun_no_write", src.read_bytes() == before, "src changed on dry-run")
        check("commit_dryrun_no_backup", not (Path(td) / "calib.T.bak.json").exists(), "backup on dry-run")

        # 备份失败 → 中止, 真源不变 (monkeypatch shutil.copy2 抛错)
        orig_copy = board.shutil.copy2
        board.shutil.copy2 = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = board.cmd_commit(src, tuned_p, broadcast=True, with_pose=False,
                                      dry_run=False, yes=True, now="BK")
        finally:
            board.shutil.copy2 = orig_copy
        check("commit_backup_fail_rc3", rc == 3, str(rc))
        check("commit_backup_fail_no_write", src.read_bytes() == before, "src changed despite backup fail")

        # 用户取消 (confirm 返回 n) → 不写
        with contextlib.redirect_stdout(io.StringIO()):
            rc = board.cmd_commit(src, tuned_p, broadcast=True, with_pose=False,
                                  dry_run=False, yes=False, now="NO", confirm=lambda _p: "n")
        check("commit_cancelled_rc1", rc == 1, str(rc))
        check("commit_cancelled_no_write", src.read_bytes() == before, "src changed on cancel")

        # 正常广播提交: 备份 + 写 + h 变一致
        with contextlib.redirect_stdout(io.StringIO()):
            rc = board.cmd_commit(src, tuned_p, broadcast=True, with_pose=False,
                                  dry_run=False, yes=True, now="OK")
        check("commit_ok_rc0", rc == 0, str(rc))
        check("commit_ok_backup", (Path(td) / "calib.OK.bak.json").exists(), "no backup")
        from eit_ptlc.controller.waterlevel_config_tiers import audit as _audit2
        fh = {f.field: f for f in _audit2(load_channel_configs(src)).fields}["h"]
        check("commit_ok_h_consistent", fh.consistent and fh.expected == 392, str(fh))

        # 非法 tuned: 通道号 0 (越界) → 拒绝 rc2
        bad = Path(td) / "bad.tuned.json"
        save_channel_configs(bad, {0: _real_snapshot()[5]})
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = board.cmd_commit(src, bad, broadcast=False, with_pose=False,
                                  dry_run=False, yes=True, now="X")
        check("commit_bad_channel_rc2", rc == 2, str(rc))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: FAIL — `AttributeError: module 'eit_ptlc.tools.wl_config_board' has no attribute 'cmd_commit'`

- [ ] **Step 3: 实现提交模式** — 追加 `diff_lines`/`_backup`/`cmd_commit` 到 `wl_config_board.py` (在 `cmd_show` 之后), 并替换 `main`:

```python
def diff_lines(old_configs: dict[int, ChannelConfig], new_configs: dict[int, ChannelConfig],
               capture: tuple[int, int] = REFERENCE_CAPTURE) -> list[str]:
    """逐通道逐字段 diff (现值 → 新值), 只列有变化的。"""
    lines: list[str] = []
    for ch in sorted(new_configs):
        old = split_tiers(old_configs[ch], capture) if ch in old_configs else None
        new = split_tiers(new_configs[ch], capture)
        changes: list[str] = []
        for f in GLOBAL_JUDGMENT_FIELDS:
            ov = getattr(old.judgment, f) if old else None
            nv = getattr(new.judgment, f)
            if ov != nv:
                changes.append(f"{f}: {ov} → {nv}")
        old_size = old.size_px if old else None
        if old_size != new.size_px:
            changes.append(f"size_px: {old_size} → {new.size_px}")
        old_pose = (old.pose.rotation_deg, old.pose.flow, old.pose.xy_px) if old else None
        new_pose = (new.pose.rotation_deg, new.pose.flow, new.pose.xy_px)
        if old_pose != new_pose:
            changes.append(f"pose(rot,flow,xy): {old_pose} → {new_pose}")
        if changes:
            lines.append(f"CH{ch}:")
            lines.extend(f"    {c}" for c in changes)
    return lines or ["(无变化)"]


def _backup(path: Path, now: str) -> Path:
    """备份真源 → <stem>.<now>.bak.json; 失败抛 OSError (调用方据此中止)。"""
    bak = path.with_name(f"{path.stem}.{now}.bak.json")
    shutil.copy2(path, bak)
    return bak


def cmd_commit(path: Path, tuned_path: Path, *, broadcast: bool, with_pose: bool,
               dry_run: bool, yes: bool, now: Optional[str] = None,
               capture: tuple[int, int] = REFERENCE_CAPTURE,
               confirm: Callable[[str], str] = input) -> int:
    """唯一改真源的入口。返回码: 0 成功/dry-run, 1 用户取消, 2 输入非法/退化, 3 备份失败中止。"""
    configs = load_true_source(path)
    tuned_map = load_channel_configs(tuned_path)
    if len(tuned_map) != 1:
        print(f"[看板] tuned 文件应恰含 1 个通道, 实含 {sorted(tuned_map)}", file=sys.stderr)
        return 2
    ch, tuned = next(iter(tuned_map.items()))
    if ch not in configs:
        print(f"[看板] CH{ch} 越界/不在真源 (真源含 {sorted(configs)})", file=sys.stderr)
        return 2

    try:
        new_configs = apply_commit(configs, ch, tuned,
                                   broadcast_global=broadcast, with_pose=with_pose, capture=capture)
    except ValueError as exc:
        print(f"[看板] 生成失败 (退化/越权): {exc}", file=sys.stderr)
        return 2

    print(f"[看板] 提交源 CH{ch}  广播={broadcast}  含位姿={with_pose}")
    print("---- 逐字段 diff (真源现值 → 新值) ----")
    for line in diff_lines(configs, new_configs, capture):
        print(line)

    if dry_run:
        print("[看板] --dry-run: 到此为止, 不备份不写。")
        return 0

    if not yes:
        ans = confirm("确认写入真源? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("[看板] 已取消, 未写入。")
            return 1

    ts = now or datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        bak = _backup(path, ts)
    except OSError as exc:
        print(f"[看板] 备份失败, 中止 (不写真源): {exc}", file=sys.stderr)
        return 3
    print(f"[看板] 已备份 → {bak}")

    save_channel_configs(path, new_configs)
    print(f"[看板] 已写入真源 → {path}")

    print("\n---- 写后自动复核 ----")
    for line in render_report(load_true_source(path), capture):
        print(line)
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="液位配置一致性看板 + 提交/广播台")
    ap.add_argument("--calib", default=None, help="真源路径 (默认 config/water_level_calib.json)")
    ap.add_argument("--commit", metavar="TUNED", default=None, help="某通道 <stem>.tuned.json; 进入提交模式")
    ap.add_argument("--broadcast", action="store_true", help="全局层落 8 路 (各按自身 rotation 重算 frac)")
    ap.add_argument("--with-pose", action="store_true", help="额外把位姿写入该通道 (显式越权逃生口)")
    ap.add_argument("--dry-run", action="store_true", help="走到 diff 即停, 不备份不写")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认 (脚本/测试)")
    args = ap.parse_args(argv)
    path = Path(args.calib) if args.calib else _default_calib_path()
    if args.commit:
        return cmd_commit(path, Path(args.commit), broadcast=args.broadcast,
                          with_pose=args.with_pose, dry_run=args.dry_run, yes=args.yes)
    return cmd_show(path)
```

> 注: 删掉 Task 5 里旧的 `main` (被此版替换); 其余 Task 5 函数保留。`confirm` 参数默认 `input`, 测试注入桩以绕过交互。`now` 参数使备份路径可预期 (测试注入定值)。

- [ ] **Step 4: 跑测试确认通过**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: PASS 全部 (`共 68 用例, 失败 0`)

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/tools/wl_config_board.py eit_ptlc/tests/test_waterlevel_config_tiers_offline.py
git commit -m "feat(waterlevel): wl_config_board 提交/广播 (diff→备份前置→写→复核, dry-run)"
```

---

### Task 7: 整定台存盘后提示下一步命令 (`wl_replay_tune.py`)

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py:396-401` (`_save_params`)
- Test: `eit_ptlc/tests/test_waterlevel_config_tiers_offline.py`

**Interfaces:**
- Consumes: 现有 `wl_replay_tune._save_params(avi, meta, calib, params) -> Path` (签名不变)。
- Produces: `_save_params` 存盘后多打印一行 `wl_config_board --commit <path>` 提示 (串起 workflow)。

- [ ] **Step 1: 写失败测试** — 在 Task 6 块之后插入:

```python
    # ============================ Task 7: 整定台存盘提示下一步 ============================
    from eit_ptlc.tools import wl_replay_tune as tune
    with tempfile.TemporaryDirectory() as td:
        avi = Path(td) / "ch5_rec.avi"   # 无需真实视频; _save_params 仅在旁写 .tuned.json
        calib = ChannelCalibration(1.656, None, "left_to_right", (0.2054, 0.0, 0.1023, 0.5185))
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            out = tune._save_params(avi, {"channel": 5}, calib, WaterLevelDetectParams())
        txt = buf.getvalue()
        check("tune_saved_file", out.exists(), str(out))
        check("tune_hint_printed", "wl_config_board --commit" in txt, txt)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: FAIL — `FAIL tune_hint_printed: ...` (现有 `_save_params` 只打印存盘位置, 无 commit 提示)

- [ ] **Step 3: 改 `_save_params`** — 在 `eit_ptlc/tools/wl_replay_tune.py` 中把:

```python
    save_channel_configs(out, {int(ch): ChannelConfig(calib=calib, params=params)})
    print(f"[整定台] 已存 CH{ch} 调好的参数 → {out}  (store 原生格式, 可并入标定真源)")
    return out
```

替换为:

```python
    save_channel_configs(out, {int(ch): ChannelConfig(calib=calib, params=params)})
    print(f"[整定台] 已存 CH{ch} 调好的参数 → {out}  (store 原生格式, 可并入标定真源)")
    print(f"[整定台] 下一步并入真源: python -m eit_ptlc.tools.wl_config_board --commit \"{out}\"")
    print("           (加 --broadcast 把全局层统一到 8 路; 加 --with-pose 才写该通道位姿; --dry-run 先看 diff)")
    return out
```

- [ ] **Step 4: 跑测试确认通过 (全套件)**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_config_tiers_offline`
Expected: PASS 全部 (`共 70 用例, 失败 0`)

再跑一次全离线套件确认无回归:

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m pytest eit_ptlc/tests/test_waterlevel_config_tiers_offline.py -q`
Expected: `1 passed` (pytest 桥收集到 `test_waterlevel_config_tiers`)

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/tools/wl_replay_tune.py eit_ptlc/tests/test_waterlevel_config_tiers_offline.py
git commit -m "feat(waterlevel): 整定台 w 存盘后提示 wl_config_board --commit 下一步"
```

---

## Self-Review

**1. Spec coverage** (逐节对照 `2026-07-10-waterlevel-config-tiers-design.md`):

- §2 三层划分 → `GLOBAL_JUDGMENT_FIELDS` + `Pose` + `split_tiers` (Task 1)。✓
- §2.1 像素只在参考分辨率下有意义 + frac 派生 + 运行时零改 → `REFERENCE_CAPTURE` + `derive_roi_frac` (Task 1) + `merge_tiers` materialize (Task 2); 运行时 `detect_level` 未触。✓
- §2.2 现状 h 漂移 → Task 3 `audit_h_no_consensus` 金标准 (已对真源核实 h=[397,384,396,387,392,392,392,392], 无严格多数)。✓
- §3 一个网关两个薄面 + 写入按层过滤 + frac 派生只一份 → 网关模块 (Task 1-4) + `apply_commit` 唯一过滤点。✓
- §3.1 不重构 shared/channels → 真源格式不动, 走 `waterlevel_store`。✓
- §4.1 网关签名 (`split_tiers`/`derive_roi_frac`/`merge_tiers`/`audit`/`apply_commit`) + 严格多数/无共识 + 读写解耦 → Task 1-4。✓ (`TierView.pose` 恒在且 `Pose.xy_px` 可空, 是对 spec 伪代码 `pose: Optional` 的精化, 为保留未标定通道 flow; 已在 Task 1/4 注明。)
- §4.2 看板只读 + 提交模式 (读 tuned → diff → 确认 → 备份 → 写 → 复核; `--dry-run`) → Task 5-6。✓
- §4.3 整定台最小改 (w 存盘提示下一步) → Task 7。✓
- §5 数据流闭环 → Task 7 提示 + Task 6 commit 串起。✓
- §6 所有权规则 (默认只落全局层; `--with-pose` 越权; 网页只写位姿) → `apply_commit` 默认过滤位姿 (Task 4 `commit_pose_filtered_*`)。✓ (网页侧走网关为下期。)
- §7 错误处理 (真源不存在/tuned 越界/备份失败中止/退化 ROI/未标定广播降级) → Task 5 `board_missing_source_exits`, Task 6 `commit_bad_channel_rc2`/`commit_backup_fail_*`, Task 2 `merge_degenerate_*`, Task 4 `broadcast_uncalib_*`。✓
- §9 测试清单 (往返/derive 金标准/audit 抓 h/apply_commit 过滤+广播/备份失败/未标定降级) → 全覆盖, 新增 `test_waterlevel_config_tiers_offline.py`。✓
- §10 非目标 (运行时接线/搬进网页/重构真源/香橙派) → 均未触。✓

**2. Placeholder scan:** 无 TBD/TODO; 每个代码步含完整函数体; 每个测试步含完整断言与预期输出。✓

**3. Type consistency:** `split_tiers`↔`merge_tiers` 经 `TierView(judgment, size_px, pose)` / `Pose(rotation_deg, flow, xy_px)` 一致; `audit` 用 `FieldAudit(field, consistent, expected, deviants, values)`; `apply_commit` 消费 `split_tiers`/`merge_tiers` 同签名; 看板 `render_report`/`diff_lines`/`cmd_commit` 消费 `GLOBAL_JUDGMENT_FIELDS`/`audit`/`apply_commit` 名称一致。用例累计计数 (12→30→41→53→58→68→70) 与各任务追加数吻合。✓

> 用例总数为估算 (随实现的 `check` 调用数); 若实际数略有出入, 以 `失败 0` 为通过判据, 非硬编码总数 (测试用运行期计数, 无需维护)。

---

## Execution Handoff

（保存后由主控在会话中给出执行方式选择：Subagent-Driven 或 Inline。）
