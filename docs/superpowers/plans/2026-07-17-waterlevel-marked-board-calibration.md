# 液位标记板标注 + 物理刻度标定 (整定台方案 B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在离线整定台 (wl_replay_tune) 加标记板真值打标热键与 %↔cm 物理刻度报告, 并根治 `c` 键卡死。

**Architecture:** 新纯函数模块 `eit_ptlc/tools/wl_marks.py` (纯 stdlib, 无 cv2/numpy) 承载 marks 文件读写与全部标定计算; `wl_replay_tune.py` 只做接线 (热键/HUD/报告触发)。`c` 键的整段回放拆成"计算 (`_run_series`, 带事件泵+Esc 中断)"与"渲染 (matplotlib Agg → BGR ndarray → cv2.imshow + PNG 落盘)"两半, 全程只保留 HighGUI 一套事件循环。

**Tech Stack:** Python 3.11 (conda env `platformupper`), OpenCV HighGUI, matplotlib (仅 `FigureCanvasAgg`, 禁 pyplot/plt.show), pytest。

**Spec:** `docs/superpowers/specs/2026-07-17-waterlevel-marked-board-calibration-design.md`

## Global Constraints

- 生产链路零改动: 只碰 `eit_ptlc/tools/`、`eit_ptlc/tests/`、`docs/`; 检测服务 / develop.wait_level / 触发链路一行不动。
- `wl_marks.py` 纯 stdlib: 不 import cv2、不 import numpy (测试中有守卫用例)。
- 键位规则: **数字键 = 距板顶 cm 整数值本身** (默认表与 `--marks` 覆盖同一语义), 标线高度限 1–9 的整数 cm。
- 缺标线内建支持: 拟合 ≥2 点即出; 区间速度按**实际 Δcm** 相邻分段; `ts` 缺失的段跳过并注明; 任何计算不得假设 5 条标线齐全。
- `marks.json` **只存纯真值** (cm/frame_idx/ts), 不存检测值; front_percent 出报告时用当前参数现算 (单帧口径, 报告标 `"front_source": "single_frame"`)。
- `frame_idx` 恒为原始帧序 (与 `c_speed` 抽帧无关); `ts` 取录制 `.jsonl` 真实墙钟。
- 落盘一律原子写 (tmp + `os.replace`)。
- matplotlib 只允许 `matplotlib.figure.Figure` + `FigureCanvasAgg`; 严禁 `import matplotlib.pyplot` / `plt.show()` (那就是卡死根因)。
- 测试解释器: `E:/Anaconda/envs/platformupper/python.exe`; 提交前全套件 `-m pytest eit_ptlc/tests -q` 必须全绿。
- 注释/输出中文为主体、技术术语保留英文 (与仓库既有风格一致)。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `eit_ptlc/tools/wl_marks.py` | Create | marks/report 文件读写 + 拟合/残差/速度/建议/格式化 (纯函数) |
| `eit_ptlc/tests/test_waterlevel_marks_offline.py` | Create | wl_marks 全量离线测试 (不 import cv2) |
| `eit_ptlc/tools/wl_replay_tune.py` | Modify | `c` 根治 (`_run_series`/`_build_curve_fig`/`_fig_to_bgr`/`_show_and_save_curve`), 数字键打标, HUD, 报告接线, `--marks` |
| `eit_ptlc/tests/test_waterlevel_tune_curve_offline.py` | Create | tune 侧新纯逻辑测试 (`_fig_to_bgr`/`_parse_marks_arg`/`_mark_lines`) |
| `docs/液位自动排液_P0实验手册_20260713.md` | Modify | 标线为主尺 / 实验B降抽查 / 新增全通道战役 |

命名说明: spec §9 原写 `test_wl_marks_offline.py`, 落地对齐仓库既有 `test_waterlevel_*` 命名。

---

### Task 1: `wl_marks.py` 骨架 — 路径/时间戳/marks 文件读写与打标变更

**Files:**
- Create: `eit_ptlc/tools/wl_marks.py`
- Test: `eit_ptlc/tests/test_waterlevel_marks_offline.py`

**Interfaces:**
- Consumes: 录制旁挂 `.jsonl` 行格式 `{"i": int, "t": epoch_seconds}` (见 `eit_ptlc/controller/waterlevel_recorder.py:290`)。
- Produces (Task 2/4 依赖, 签名钉死):
  - `MARKS_SCHEMA = "ptlc.wl-marks/v1"`, `DEFAULT_MARKS_CM = (5.0, 4.0, 3.0, 2.0, 1.0)`
  - `jsonl_path(avi_path) -> Path` / `marks_path(avi_path) -> Path` (`<stem>.marks.json`) / `report_path(avi_path) -> Path` (`<stem>.marks_report.json`) / `curve_png_path(avi_path) -> Path` (`<stem>.curve.png`)
  - `load_timestamps(path) -> dict[int, float]` (缺文件→空 dict; 坏行跳过)
  - `new_marks(channel, recording, marks_cm=DEFAULT_MARKS_CM) -> dict`
  - `load_marks(path) -> Optional[dict]` (缺文件→None; 坏 JSON/schema 不符→raise ValueError)
  - `get_event(marks, cm) -> Optional[dict]`
  - `toggle_event(marks, cm, frame_idx, ts) -> str` (返回 `"set"|"moved"|"cleared"`; 原地改 `marks`)
  - `save_marks(path, marks) -> None` (原子写; 写前刷 `updated_at`)
  - `save_report(path, report) -> None` (原子写)

- [ ] **Step 1: 写失败测试**

创建 `eit_ptlc/tests/test_waterlevel_marks_offline.py`:

```python
"""液位标记板真值标注模块离线测试 (纯函数, 无 cv2/numpy)
==========================================================
覆盖: 旁挂路径推导 / jsonl 时间戳载入 / marks 新建-打标-覆盖-取消 /
原子写盘与读回 / 缺文件与坏文件语义 / (Task 2 追加) 拟合-残差-速度-报告。

运行 (pytest):
    E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_marks_offline.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eit_ptlc.tools import wl_marks


def test_pure_stdlib():
    """全局约束守卫: wl_marks 不得依赖 cv2/numpy。"""
    src = Path(wl_marks.__file__).read_text(encoding="utf-8")
    assert "import cv2" not in src
    assert "import numpy" not in src


def test_sidecar_paths(tmp_path):
    avi = tmp_path / "ch3_20260717_101500.avi"
    assert wl_marks.jsonl_path(avi).name == "ch3_20260717_101500.jsonl"
    assert wl_marks.marks_path(avi).name == "ch3_20260717_101500.marks.json"
    assert wl_marks.report_path(avi).name == "ch3_20260717_101500.marks_report.json"
    assert wl_marks.curve_png_path(avi).name == "ch3_20260717_101500.curve.png"


def test_load_timestamps_tolerant(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"i": 0, "t": 100.5}\n\n{"i": 2, "t": 102.0}\n{oops\n', encoding="utf-8")
    assert wl_marks.load_timestamps(p) == {0: 100.5, 2: 102.0}
    assert wl_marks.load_timestamps(tmp_path / "missing.jsonl") == {}


def test_toggle_set_move_clear():
    m = wl_marks.new_marks(3, "a.avi", (5.0, 4.0, 3.0, 2.0, 1.0))
    assert wl_marks.toggle_event(m, 5.0, 210, 100.5) == "set"
    assert wl_marks.get_event(m, 5.0) == {"cm": 5.0, "frame_idx": 210, "ts": 100.5}
    assert wl_marks.toggle_event(m, 5.0, 250, 101.0) == "moved"      # 换帧 = 覆盖
    assert wl_marks.get_event(m, 5.0)["frame_idx"] == 250
    assert wl_marks.toggle_event(m, 5.0, 250, 101.0) == "cleared"    # 同帧重按 = 取消
    assert wl_marks.get_event(m, 5.0) is None
    wl_marks.toggle_event(m, 2.0, 731, None)                          # ts 缺 (jsonl 缺行)
    assert wl_marks.get_event(m, 2.0)["ts"] is None


def test_events_sorted_cm_desc():
    m = wl_marks.new_marks(1, "a.avi")
    wl_marks.toggle_event(m, 2.0, 731, 300.0)
    wl_marks.toggle_event(m, 5.0, 210, 100.0)
    assert [e["cm"] for e in m["events"]] == [5.0, 2.0]


def test_save_load_roundtrip_atomic(tmp_path):
    m = wl_marks.new_marks(3, "a.avi")
    wl_marks.toggle_event(m, 5.0, 210, 100.5)
    p = tmp_path / "a.marks.json"
    wl_marks.save_marks(p, m)
    assert not list(tmp_path.glob("*.tmp"))          # 原子写不留临时文件
    m2 = wl_marks.load_marks(p)
    assert m2["schema"] == wl_marks.MARKS_SCHEMA
    assert m2["channel"] == 3 and m2["events"] == m["events"]
    assert m2["updated_at"]                          # save 时已刷


def test_load_marks_missing_and_corrupt(tmp_path):
    assert wl_marks.load_marks(tmp_path / "none.marks.json") is None
    bad = tmp_path / "bad.marks.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        wl_marks.load_marks(bad)
    wrong = tmp_path / "wrong.marks.json"
    wrong.write_text(json.dumps({"schema": "other/v9"}), encoding="utf-8")
    with pytest.raises(ValueError):
        wl_marks.load_marks(wrong)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_marks_offline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eit_ptlc.tools.wl_marks'`

- [ ] **Step 3: 最小实现**

创建 `eit_ptlc/tools/wl_marks.py`:

```python
"""液位标记板真值标注 + %↔cm 物理刻度计算 (纯函数, 无 cv2/numpy)
====================================================================
职责:
    整定台 (wl_replay_tune) 的标记板打标数据层与计算层。标记板 = 距板顶
    5/4/3/2/1cm 画横标线的 TLC 板; 人在整定台拖帧到前沿越线帧按数字键打标,
    本模块负责真值文件 (<stem>.marks.json) 读写与报告计算。

设计决策 (spec 2026-07-17-waterlevel-marked-board-calibration-design.md):
    - marks.json 只存纯真值 {cm, frame_idx, ts}; front_percent 由调用方在
      出报告时用**当前参数**现算后经 build_report 传入 —— 改参数后标定自动
      跟新, 真值永不过期 (与整定台 ref_frame_idx 每次现算参考图同一哲学)。
    - 缺标线内建: 拟合 ≥2 点即出; 区间速度按实际 Δcm 相邻分段; ts 缺失段跳过。
    - 本模块纯 stdlib, 离线测试零重依赖 (test_waterlevel_marks_offline.py)。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

MARKS_SCHEMA = "ptlc.wl-marks/v1"
REPORT_SCHEMA = "ptlc.wl-marks-report/v1"
DEFAULT_MARKS_CM = (5.0, 4.0, 3.0, 2.0, 1.0)


# ---- 旁挂路径 (与 waterlevel_recorder._sidecar_paths 同构; 双点后缀手拼) ----
def _stem(avi_path) -> Path:
    return Path(avi_path).with_suffix("")


def jsonl_path(avi_path) -> Path:
    return _stem(avi_path).with_suffix(".jsonl")


def marks_path(avi_path) -> Path:
    return Path(str(_stem(avi_path)) + ".marks.json")


def report_path(avi_path) -> Path:
    return Path(str(_stem(avi_path)) + ".marks_report.json")


def curve_png_path(avi_path) -> Path:
    return Path(str(_stem(avi_path)) + ".curve.png")


# ---- jsonl 时间戳 ----
def load_timestamps(path) -> dict[int, float]:
    """录制 .jsonl → {frame_idx: epoch_seconds}; 缺文件→空, 坏行跳过。"""
    path = Path(path)
    stamps: dict[int, float] = {}
    if not path.is_file():
        return stamps
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            stamps[int(row["i"])] = float(row["t"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return stamps


# ---- marks 文件 ----
def new_marks(channel, recording, marks_cm=DEFAULT_MARKS_CM) -> dict:
    return {
        "schema": MARKS_SCHEMA,
        "channel": int(channel) if channel is not None else None,
        "recording": str(recording),
        "marks_cm": [float(c) for c in marks_cm],
        "events": [],
        "updated_at": None,
    }


def load_marks(path) -> Optional[dict]:
    """缺文件 → None; 坏 JSON / schema 不符 → ValueError (调用方决定怎么提示)。"""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"marks 文件不可解析: {path} ({exc})") from exc
    if not isinstance(data, dict) or data.get("schema") != MARKS_SCHEMA:
        raise ValueError(f"marks schema 不符: {path} ({data.get('schema')!r})")
    data.setdefault("events", [])
    data.setdefault("marks_cm", list(DEFAULT_MARKS_CM))
    return data


def get_event(marks: dict, cm) -> Optional[dict]:
    for ev in marks["events"]:
        if float(ev["cm"]) == float(cm):
            return ev
    return None


def toggle_event(marks: dict, cm, frame_idx: int, ts) -> str:
    """打标语义: 无 → set; 换帧 → moved (覆盖); 同帧重按 → cleared (取消)。"""
    ev = get_event(marks, cm)
    if ev is not None and int(ev["frame_idx"]) == int(frame_idx):
        marks["events"].remove(ev)
        return "cleared"
    if ev is not None:
        ev["frame_idx"] = int(frame_idx)
        ev["ts"] = float(ts) if ts is not None else None
        return "moved"
    marks["events"].append({"cm": float(cm), "frame_idx": int(frame_idx),
                            "ts": float(ts) if ts is not None else None})
    marks["events"].sort(key=lambda e: -float(e["cm"]))
    return "set"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    os.replace(temp, path)


def save_marks(path, marks: dict) -> None:
    marks["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(Path(path), marks)


def save_report(path, report: dict) -> None:
    _write_json_atomic(Path(path), report)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_marks_offline.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/tools/wl_marks.py eit_ptlc/tests/test_waterlevel_marks_offline.py
git commit -m "feat(wl-marks): 标记板真值文件层 — 旁挂路径/jsonl时间戳/打标toggle/原子读写"
```

---

### Task 2: `wl_marks.py` 计算层 — 拟合/残差/速度/报告/格式化

**Files:**
- Modify: `eit_ptlc/tools/wl_marks.py` (追加到文件末尾)
- Test: `eit_ptlc/tests/test_waterlevel_marks_offline.py` (追加)

**Interfaces:**
- Consumes: Task 1 的 `marks` dict 形状 (`events: [{cm, frame_idx, ts}]`, cm 降序)。
- Produces (Task 4 依赖, 签名钉死):
  - `linear_fit(pairs) -> Optional[dict]` — 入参 `[(cm, front_percent), ...]`; n<2 或全同 cm → None; 返回 `{"slope_pct_per_cm", "intercept_pct", "r2", "n"}` (r2 仅 n≥3 且方差>0, 否则 None)
  - `invert_fit(fit, front_percent) -> float` — d = (front−b)/a; |a|<1e-9 → ValueError
  - `residuals(pairs, fit) -> list[dict]` — `[{"cm", "front_percent", "residual"}]`
  - `segment_velocities(events) -> list[dict]` — cm 降序相邻配对; 正常段 `{"from_cm","to_cm","dt_s","cm_per_min"}`, 坏段 `{"from_cm","to_cm","skipped": 原因}`
  - `build_report(marks, fronts, calib_snapshot=None, params_snapshot=None, r2_warn=0.98) -> dict` — `fronts: dict[float cm → Optional[float] front]`; 返回 schema `ptlc.wl-marks-report/v1` 报告 (形状见实现)
  - `format_report(report) -> str` — 终端多行中文文本
  - `format_hud_line(marks) -> str` — 形如 `marks: 5cm@f210 4cm@f388 (1cm 缺)`

- [ ] **Step 1: 追加失败测试**

追加到 `eit_ptlc/tests/test_waterlevel_marks_offline.py`:

```python
# ---- Task 2: 计算层 ----

def _perfect_pairs():
    """front = −4·d + 90 的理想直线 (5..1cm)。"""
    return [(5.0, 70.0), (4.0, 74.0), (3.0, 78.0), (2.0, 82.0), (1.0, 86.0)]


def test_linear_fit_perfect_and_invert():
    fit = wl_marks.linear_fit(_perfect_pairs())
    assert abs(fit["slope_pct_per_cm"] + 4.0) < 1e-9
    assert abs(fit["intercept_pct"] - 90.0) < 1e-9
    assert fit["n"] == 5 and fit["r2"] > 0.999999
    assert abs(wl_marks.invert_fit(fit, 80.0) - 2.5) < 1e-9


def test_linear_fit_degenerate():
    assert wl_marks.linear_fit([]) is None
    assert wl_marks.linear_fit([(5.0, 70.0)]) is None                 # 1 点不拟合
    assert wl_marks.linear_fit([(5.0, 70.0), (5.0, 71.0)]) is None    # 同 cm 两点
    fit2 = wl_marks.linear_fit([(5.0, 70.0), (3.0, 78.0)])            # 2 点: 有拟合无 R²
    assert fit2["n"] == 2 and fit2["r2"] is None
    with pytest.raises(ValueError):
        wl_marks.invert_fit({"slope_pct_per_cm": 0.0, "intercept_pct": 50.0}, 60.0)


def test_residuals():
    pairs = [(5.0, 70.0), (3.0, 78.5), (2.0, 82.0)]
    fit = {"slope_pct_per_cm": -4.0, "intercept_pct": 90.0, "r2": None, "n": 3}
    res = {r["cm"]: r["residual"] for r in wl_marks.residuals(pairs, fit)}
    assert abs(res[5.0]) < 1e-9 and abs(res[3.0] - 0.5) < 1e-9


def test_segment_velocities_gaps_and_missing_ts():
    # 只标 5/3/2 (缺 4、1): 段按实际 Δcm; 5→3 = 2cm/120s = 1.0 cm/min
    events = [{"cm": 5.0, "frame_idx": 10, "ts": 100.0},
              {"cm": 3.0, "frame_idx": 50, "ts": 220.0},
              {"cm": 2.0, "frame_idx": 80, "ts": 300.0}]
    segs = wl_marks.segment_velocities(events)
    assert segs[0]["from_cm"] == 5.0 and segs[0]["to_cm"] == 3.0
    assert abs(segs[0]["cm_per_min"] - 1.0) < 1e-9 and segs[0]["dt_s"] == 120.0
    assert abs(segs[1]["cm_per_min"] - 0.75) < 1e-9
    # ts 缺失段跳过并注明
    events[1]["ts"] = None
    segs2 = wl_marks.segment_velocities(events)
    assert segs2[0]["skipped"] == "ts_missing" and segs2[1]["skipped"] == "ts_missing"
    # dt<=0 (时序倒挂) 跳过
    bad = [{"cm": 5.0, "frame_idx": 1, "ts": 200.0},
           {"cm": 4.0, "frame_idx": 2, "ts": 100.0}]
    assert "skipped" in wl_marks.segment_velocities(bad)[0]


def test_build_report_full_path():
    m = wl_marks.new_marks(3, "a.avi")
    wl_marks.toggle_event(m, 5.0, 10, 100.0)
    wl_marks.toggle_event(m, 3.0, 50, 220.0)
    wl_marks.toggle_event(m, 2.0, 80, 300.0)     # 缺 4cm、1cm
    fronts = {5.0: 70.0, 3.0: 78.0, 2.0: 82.0}   # 落在 front=−4d+90 上
    rep = wl_marks.build_report(m, fronts, calib_snapshot={"x": 1},
                                params_snapshot={"y": 2})
    assert rep["schema"] == wl_marks.REPORT_SCHEMA
    assert rep["fit"]["n"] == 3 and abs(rep["fit"]["slope_pct_per_cm"] + 4.0) < 1e-6
    assert rep["r2_warning"] is False
    assert rep["front_source"] == "single_frame"
    assert rep["marks"][0]["cm"] == 5.0 and abs(rep["marks"][0]["residual"]) < 1e-6
    # 建议: 最靠板顶可用段 3→2cm (0.75 cm/min) × |−4| %/cm ÷ 60 = 0.05 %/s
    assert abs(rep["suggestion"]["speed_pct_per_s"] - 0.05) < 1e-6
    assert rep["suggestion"]["segment"] == [3.0, 2.0]
    txt = wl_marks.format_report(rep)
    assert "d(front%)" in txt and "cm/min" in txt and "就位时间" in txt


def test_build_report_invalid_front_excluded_and_no_reference():
    m = wl_marks.new_marks(3, "a.avi")
    wl_marks.toggle_event(m, 5.0, 10, 100.0)
    wl_marks.toggle_event(m, 3.0, 50, 220.0)
    # 某帧检测 invalid → front None → 不入拟合
    rep = wl_marks.build_report(m, {5.0: 70.0, 3.0: None})
    assert rep["fit"] is None                      # 只剩 1 有效点
    # 全 None (未设参考帧) → 无拟合, 文本给提示
    rep2 = wl_marks.build_report(m, {5.0: None, 3.0: None})
    assert rep2["fit"] is None
    assert "无拟合" in wl_marks.format_report(rep2)


def test_format_hud_line():
    m = wl_marks.new_marks(3, "a.avi")
    for cm, f in ((5.0, 210), (4.0, 388), (3.0, 560), (2.0, 731)):
        wl_marks.toggle_event(m, cm, f, None)
    assert wl_marks.format_hud_line(m) == \
        "marks: 5cm@f210 4cm@f388 3cm@f560 2cm@f731 (1cm 缺)"
    empty = wl_marks.new_marks(3, "a.avi", (5.0, 3.0))
    assert wl_marks.format_hud_line(empty) == "marks: (无) (5cm/3cm 缺)"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_marks_offline.py -q`
Expected: FAIL — `AttributeError: module 'eit_ptlc.tools.wl_marks' has no attribute 'linear_fit'`

- [ ] **Step 3: 实现计算层**

追加到 `eit_ptlc/tools/wl_marks.py`:

```python
# ====================================================================
# 计算层: %↔cm 拟合 / 残差 / 区间速度 / 报告 (全部内建缺标线支持)
# ====================================================================
def linear_fit(pairs) -> Optional[dict]:
    """最小二乘 front_percent = a·d + b (d = 距板顶 cm)。

    n<2 或 d 全同 → None (不拟合); r2 仅 n≥3 且 front 有方差时给出。
    """
    pts = [(float(d), float(f)) for d, f in pairs]
    n = len(pts)
    if n < 2:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in pts) / sxx
    intercept = my - slope * mx
    r2 = None
    if n >= 3:
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in pts)
        ss_tot = sum((y - my) ** 2 for _, y in pts)
        if ss_tot > 0:
            r2 = 1.0 - ss_res / ss_tot
    return {"slope_pct_per_cm": slope, "intercept_pct": intercept,
            "r2": r2, "n": n}


def invert_fit(fit: dict, front_percent) -> float:
    """反演读数器: d(front%) = (front% − b) / a  [cm, 距板顶]。"""
    a = float(fit["slope_pct_per_cm"])
    if abs(a) < 1e-9:
        raise ValueError("拟合斜率≈0, 无法反演 d(front%)")
    return (float(front_percent) - float(fit["intercept_pct"])) / a


def residuals(pairs, fit: dict) -> list[dict]:
    a, b = float(fit["slope_pct_per_cm"]), float(fit["intercept_pct"])
    return [{"cm": float(d), "front_percent": float(f),
             "residual": float(f) - (a * float(d) + b)} for d, f in pairs]


def segment_velocities(events) -> list[dict]:
    """相邻已标线对 (cm 降序 = 时间正序) → 实际 Δcm/Δt。

    ts 缺失或 dt≤0 (时序倒挂) 的段跳过并注明 —— 缺 1cm/跳档 (只标 5/3/2)
    自动适配, 不假设标线齐全。
    """
    evs = sorted(events, key=lambda e: -float(e["cm"]))
    out: list[dict] = []
    for hi, lo in zip(evs, evs[1:]):
        seg: dict[str, Any] = {"from_cm": float(hi["cm"]), "to_cm": float(lo["cm"])}
        t_hi, t_lo = hi.get("ts"), lo.get("ts")
        if t_hi is None or t_lo is None:
            seg["skipped"] = "ts_missing"
        else:
            dt = float(t_lo) - float(t_hi)
            if dt <= 0:
                seg["skipped"] = f"dt_nonpositive:{dt:.3f}"
            else:
                seg["dt_s"] = round(dt, 3)
                seg["cm_per_min"] = (float(hi["cm"]) - float(lo["cm"])) / dt * 60.0
        out.append(seg)
    return out


def build_report(marks: dict, fronts: dict, calib_snapshot=None,
                 params_snapshot=None, r2_warn: float = 0.98) -> dict:
    """组装报告 (纯函数)。fronts = {cm: front_percent|None}, 由调用方现算传入。

    front 为 None 的线 (未设参考/检测 invalid) 不入拟合但保留在 marks 行。
    """
    rows: list[dict] = []
    pairs: list[tuple[float, float]] = []
    for ev in sorted(marks["events"], key=lambda e: -float(e["cm"])):
        cm = float(ev["cm"])
        front = fronts.get(cm)
        rows.append({"cm": cm, "frame_idx": ev["frame_idx"], "ts": ev.get("ts"),
                     "front_percent": front, "residual": None})
        if front is not None:
            pairs.append((cm, float(front)))
    fit = linear_fit(pairs)
    if fit is not None:
        res_by_cm = {r["cm"]: r["residual"] for r in residuals(pairs, fit)}
        for row in rows:
            if row["front_percent"] is not None:
                row["residual"] = res_by_cm.get(row["cm"])
    vels = segment_velocities(marks["events"])
    suggestion = None
    if fit is not None:
        usable = [v for v in vels if "cm_per_min" in v]
        if usable:
            top = min(usable, key=lambda v: v["to_cm"])   # 最靠板顶的可用段
            speed = top["cm_per_min"] / 60.0 * abs(fit["slope_pct_per_cm"])
            suggestion = {
                "segment": [top["from_cm"], top["to_cm"]],
                "speed_pct_per_s": round(speed, 5),
                "formula": (f"t1_offset ≈ 就位时间(s) × {speed:.4f} %/s"
                            f" (如 60s → {60 * speed:.1f}%)"),
            }
    r2 = fit.get("r2") if fit else None
    return {
        "schema": REPORT_SCHEMA,
        "channel": marks.get("channel"),
        "recording": marks.get("recording"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "marks": rows,
        "fit": fit,
        "r2_warning": bool(r2 is not None and r2 < r2_warn),
        "velocities": vels,
        "suggestion": suggestion,
        "front_source": "single_frame",
        "calib_snapshot": calib_snapshot,
        "params_snapshot": params_snapshot,
    }


def format_report(report: dict) -> str:
    """终端可读多行文本 (报告头带物理前提)。"""
    lines = [f"[标记板报告] CH{report.get('channel')} {report.get('recording')}"
             f"  (前提: 标记与板同框进干板参考, 参考窗口后未改动)"]
    for row in report["marks"]:
        f, r = row["front_percent"], row["residual"]
        lines.append(f"  {row['cm']:g}cm @f{row['frame_idx']}  front="
                     + (f"{f:.2f}%" if f is not None else "—")
                     + (f"  残差 {r:+.2f}%" if r is not None else ""))
    fit = report["fit"]
    if fit is None:
        lines.append("  ! 可用 front <2 点, 无拟合"
                     " (未设参考帧 r / 检测 invalid / 标注不足)"
                     if report["marks"] else
                     "  (尚无标注: 拖帧到前沿越线时刻按数字键打标)")
    else:
        a, b = fit["slope_pct_per_cm"], fit["intercept_pct"]
        r2_txt = f", R²={fit['r2']:.4f}" if fit["r2"] is not None else ""
        lines.append(f"  拟合 front% = {a:.3f}·d + {b:.2f}  (n={fit['n']}{r2_txt})")
        lines.append(f"  反演 d(front%) = (front% − {b:.2f}) / ({a:.3f})  [cm, 距板顶]")
        if report["r2_warning"]:
            lines.append("  ⚠ R² 偏低: 可能透视/ROI 不正, 物理映射慎用")
    for v in report["velocities"]:
        if "cm_per_min" in v:
            lines.append(f"  速度 {v['from_cm']:g}→{v['to_cm']:g}cm:"
                         f" {v['cm_per_min']:.3f} cm/min (Δt={v['dt_s']:.0f}s)")
        else:
            lines.append(f"  速度 {v['from_cm']:g}→{v['to_cm']:g}cm:"
                         f" 跳过 ({v['skipped']})")
    if report["suggestion"]:
        lines.append("  建议(参考): " + report["suggestion"]["formula"])
    return "\n".join(lines)


def format_hud_line(marks: dict) -> str:
    """HUD 单行: 已标 `5cm@f210`, 缺标聚合括号注明。"""
    parts: list[str] = []
    missing: list[str] = []
    for cm in sorted((float(c) for c in marks["marks_cm"]), reverse=True):
        ev = get_event(marks, cm)
        if ev is None:
            missing.append(f"{cm:g}cm")
        else:
            parts.append(f"{cm:g}cm@f{ev['frame_idx']}")
    line = "marks: " + (" ".join(parts) if parts else "(无)")
    if missing:
        line += f" ({'/'.join(missing)} 缺)"
    return line
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_marks_offline.py -q`
Expected: `14 passed`

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/tools/wl_marks.py eit_ptlc/tests/test_waterlevel_marks_offline.py
git commit -m "feat(wl-marks): 计算层 — %↔cm 拟合/反演/残差/区间速度/报告/HUD, 缺标线内建"
```

---

### Task 3: `c` 键卡死根治 — 计算/渲染拆半 + Agg + 事件泵

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py` (替换 `_plot_full_run`, 改 main 的 `c` 分支)
- Test: `eit_ptlc/tests/test_waterlevel_tune_curve_offline.py` (Create)

**Interfaces:**
- Consumes: Task 1 的 `wl_marks.curve_png_path(avi)`。
- Produces (Task 4 依赖, 签名钉死):
  - `_run_series(avi, calib, params, ref_frame, stride=1, n_total=None) -> Optional[dict]` — 返回 `{"ts","pct","front","diff","drifts","gains","valid","frozen_at","guard_reason","t0"}` (`t0`=首个真实墙钟, 无 jsonl 时 None); 用户 Esc 中断 → None
  - `_build_curve_fig(avi, calib, params, series, stride, mark_lines=()) -> Figure` — `mark_lines: [(相对秒 x, 标签), ...]`
  - `_fig_to_bgr(fig) -> np.ndarray`
  - `_show_and_save_curve(avi, fig) -> None` — PNG 落盘 + `cv2.imshow(CURVE_WIN, ...)`
  - `CURVE_WIN = "curve (X 关闭; 每次 c 刷新)"`

- [ ] **Step 0: 复现确认诊断 (有真录像的环境; 无则跳过并在 Task 5 上机清单补)**

Run: `E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tools.wl_replay_tune`
按 `c`: 预期复现 — 整段跑期间预览窗"未响应", 跑完弹 matplotlib 窗后 OpenCV 窗冻结
(关图窗才恢复)。与 spec §6 两层诊断一致方可继续; 若现象不同, 先回 spec 修诊断。

- [ ] **Step 1: 写失败测试**

创建 `eit_ptlc/tests/test_waterlevel_tune_curve_offline.py`:

```python
"""整定台曲线渲染/纯逻辑离线测试 (需 cv2+matplotlib, 无 GUI 窗口)
====================================================================
'c' 卡死根治的可测半: Figure(Agg)→BGR ndarray 形状正确; 其余 (事件泵/
Esc 中断/imshow) 为 GUI 行为, 见 plan 的人工验证清单。

运行 (pytest):
    E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_tune_curve_offline.py -q
"""

from __future__ import annotations

import numpy as np

from eit_ptlc.tools.wl_replay_tune import _fig_to_bgr


def test_fig_to_bgr_shape_and_dtype():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    fig = Figure(figsize=(2, 1), dpi=50)
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.plot([0, 1], [0, 1])
    img = _fig_to_bgr(fig)
    assert img.shape == (50, 100, 3) and img.dtype == np.uint8
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_tune_curve_offline.py -q`
Expected: FAIL — `ImportError: cannot import name '_fig_to_bgr'`

- [ ] **Step 3: 实现 — 替换 `_plot_full_run`**

在 `eit_ptlc/tools/wl_replay_tune.py`:

3a. 顶部 import 区追加 (紧跟 `from eit_ptlc.controller.waterlevel_store import (...)` 之后):

```python
from eit_ptlc.tools import wl_marks
```

3b. 模块级常量 (`VIEW_WIN` 定义行之后) 追加:

```python
CURVE_WIN = "curve (X 关闭; 每次 c 刷新)"
```

3c. **整段删除** `_plot_full_run` 函数 (含其上的分节注释), 原位替换为:

```python
# ====================================================================
# 整段 percent(t) 时序曲线 (按 'c' 触发) —— 计算/渲染拆半, 根治卡死:
#   层1 旧循环不泵 cv2 事件 → Windows "未响应";
#   层2 plt.show() 把 matplotlib GUI mainloop 嵌进 OpenCV 键循环互卡。
#   现: _run_series 每 ~30 采样帧泵一次事件 (可 Esc 中断);
#       渲染只用 FigureCanvasAgg (无 GUI) → BGR → cv2.imshow + PNG 落盘。
# ====================================================================
def _run_series(avi: Path, calib, params, ref_frame, stride: int = 1,
                n_total: Optional[int] = None) -> Optional[dict]:
    """整段回放跑检测出时序 (计算半)。返回 None = 用户 Esc 中断。

    stride>1 = 倍速抽帧 (跳过帧不解码); 守卫按采样帧推进 (等效低 fps 服务),
    大倍速下光照快变可能提前触发 gain_step 冻结 —— 看细节用 1x。
    泵事件期间按键会被本函数吃掉 (除 Esc), 属整段跑模态的已知取舍。
    """
    stride = max(1, int(stride))
    ref = compute_reference(ref_frame, calib, params) if ref_frame is not None else None
    is_log = params.separation_mode == "log"
    guard = DryGainGuard()
    zone_pct = dry_zone_front_percent(calib, params)
    front_max: Optional[float] = None
    frozen_at: Optional[float] = None
    ts, pct, front, diff, drifts, gains, valid = [], [], [], [], [], [], []
    t0 = None
    approx = ((int(n_total) + stride - 1) // stride) if n_total else None
    for i, (frame, t) in enumerate(replay(avi, stride=stride)):
        if i % 30 == 0:
            if (cv2.waitKey(1) & 0xFF) == 27:
                print(f"\n[整定台] 整段跑已中断 (Esc) @ 采样帧 {i}")
                return None
            if approx:
                print(f"\r[整定台] 整段回放 {i}/{approx} ...", end="", flush=True)
        gain_ov = None
        if ref is not None and is_log:
            gain_ov = guard.filter(measure_dry_gain(frame, calib, ref, params),
                                   front_max, zone_pct)
        r = detect_level(frame, calib, ref=ref, params=params, gain_override=gain_ov)
        if r.valid and r.front_percent is not None:
            front_max = max(front_max or 0.0, r.front_percent)
        if t is not None and t0 is None:
            t0 = t
        tx = (t - t0) if (t is not None and t0 is not None) else float(i * stride)
        if frozen_at is None and guard.frozen:
            frozen_at = tx
        ts.append(tx)
        pct.append(r.percent if r.valid else np.nan)
        front.append(r.front_percent if (r.valid and r.front_percent is not None) else np.nan)
        diff.append(r.diff_mean)
        drifts.append(r.drift)
        gains.append(r.gain)
        valid.append(r.valid)
    if approx:
        print()
    n_valid = sum(valid)
    sep_thr = params.diff_threshold_log if is_log else params.diff_threshold
    wet_desc = (f"k={params.wet_rel_threshold}" if is_log
                else f"wet_thr={params.wet_pixel_threshold}")
    print(f"[整定台] 整段跑完: {len(ts)} 帧"
          + (f" (x{stride} 抽帧)" if stride > 1 else "")
          + f", valid {n_valid} 帧 "
          f"({100*n_valid/max(1,len(ts)):.0f}%), sep={params.separation_mode} "
          f"diff_thr={sep_thr} {wet_desc} front_lvl={params.front_ratio_level}"
          + (f"  [gain 冻结 @t={frozen_at:.1f} ({guard.reason})]" if frozen_at is not None else ""))
    return {"ts": ts, "pct": pct, "front": front, "diff": diff, "drifts": drifts,
            "gains": gains, "valid": valid, "frozen_at": frozen_at,
            "guard_reason": (guard.reason if frozen_at is not None else None),
            "t0": t0}


def _build_curve_fig(avi: Path, calib, params, series: dict, stride: int,
                     mark_lines=()):
    """时序 → matplotlib Figure (渲染半)。只用 FigureCanvasAgg, 严禁 pyplot。"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    ts, pct, front = series["ts"], series["pct"], series["front"]
    is_log = params.separation_mode == "log"
    sep_thr = params.diff_threshold_log if is_log else params.diff_threshold
    frozen_at = series["frozen_at"]
    fig = Figure(figsize=(11, 6))
    FigureCanvasAgg(fig)
    ax1, ax2 = fig.subplots(2, 1, sharex=True)
    ax1.plot(ts, pct, ".-", ms=3, label="percent (面积占比)")
    ax1.plot(ts, front, ".-", ms=3, alpha=0.6, label="front (线位置)")
    ax1.set_ylabel("%"); ax1.set_ylim(-5, 105); ax1.grid(alpha=0.3)
    ax1.set_title(f"{avi.name}  rot={calib.rotation_angle_deg:+.1f} flow={calib.flow_direction} "
                  f"sep={params.separation_mode}"
                  + (f"  x{stride}" if stride > 1 else ""))
    for x, label in mark_lines:
        ax1.axvline(x, ls="--", color="tab:green", alpha=0.7)
        ax1.annotate(label, (x, 102), fontsize=8, color="tab:green",
                     ha="center", va="bottom", annotation_clip=False)
    ax1.legend(loc="best")
    ax2.plot(ts, series["diff"], ".-", ms=3, color="tab:red", label="diff_mean")
    if is_log:
        ax2.plot(ts, (np.asarray(series["gains"]) - 1.0) * 100.0, ".-", ms=2,
                 alpha=0.6, color="tab:blue", label="gain-1 (%, 干区增益)")
    else:
        ax2.plot(ts, series["drifts"], ".-", ms=2, alpha=0.6,
                 color="tab:blue", label="drift (干区漂移)")
    ax2.axhline(sep_thr, ls="--", color="gray", label=f"diff_threshold={sep_thr}")
    if frozen_at is not None:
        for ax in (ax1, ax2):
            ax.axvline(frozen_at, ls=":", color="tab:purple", alpha=0.8)
        ax2.plot([], [], ls=":", color="tab:purple",
                 label=f"gain 冻结 ({series['guard_reason']})")
    ax2.set_xlabel("t (s, 相对起始; 无时间戳时为帧序)"); ax2.set_ylabel("diff_mean")
    ax2.grid(alpha=0.3); ax2.legend(loc="best")
    fig.tight_layout()
    return fig


def _fig_to_bgr(fig) -> np.ndarray:
    """matplotlib Figure (Agg canvas) → BGR ndarray (供 cv2.imshow / imwrite)。"""
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())
    return cv2.cvtColor(buf, cv2.COLOR_RGBA2BGR)


def _show_and_save_curve(avi: Path, fig) -> None:
    """曲线 → PNG 落盘 + 普通 cv2 窗口显示 (主循环 waitKeyEx 持续泵它, 不阻塞)。"""
    img = _fig_to_bgr(fig)
    png = wl_marks.curve_png_path(avi)
    try:
        cv2.imwrite(str(png), img)
        print(f"[整定台] 曲线已落盘 → {png.name}")
    except cv2.error as exc:
        print(f"[整定台] 曲线 PNG 落盘失败: {exc}", file=sys.stderr)
    cv2.imshow(CURVE_WIN, img)
```

3d. main 循环 `c` 分支 (原 `_plot_full_run(avi, calib, params, src.get(ridx), stride=stride)` 一行) 替换为:

```python
        elif key == ord("c"):
            stride = max(1, cv2.getTrackbarPos("c_speed(xN)", CTRL_WIN))
            series = _run_series(avi, calib, params, src.get(ridx),
                                 stride=stride, n_total=src.n)
            if series is not None:
                fig = _build_curve_fig(avi, calib, params, series, stride)
                _show_and_save_curve(avi, fig)
```

3e. `HELP` 文本中 `c 跑整段画 percent(t) 曲线` 行补一句 (同行末尾): `  (进度条实时打印, Esc 中断; 曲线窗 X 关, PNG 自动落盘)`

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_tune_curve_offline.py eit_ptlc/tests/test_waterlevel_marks_offline.py -q`
Expected: `15 passed`

- [ ] **Step 5: 真录像人工冒烟 (开发机有录制数据时)**

Run: `E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tools.wl_replay_tune`
验证: 按 `c` → 终端滚动 `整段回放 i/N ...` 进度 → 期间预览窗**不再"未响应"** → 曲线出现在 `curve` 窗口 (X 可关) → `<stem>.curve.png` 已生成 → 再按一次 `c` 期间敲 Esc → 打印 `整段跑已中断`。
无录制数据的环境: 跳过本步, 留给 Task 5 的上机清单。

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/tools/wl_replay_tune.py eit_ptlc/tests/test_waterlevel_tune_curve_offline.py
git commit -m "fix(整定台): 根治 c 键卡死 — 计算/渲染拆半, Agg→cv2 单事件循环, 进度泵+Esc 中断, PNG 落盘"
```

---

### Task 4: 打标热键 + HUD + 报告接线

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py` (argparse / main 启动段 / 键循环 / `_render` / `HELP`)
- Test: `eit_ptlc/tests/test_waterlevel_tune_curve_offline.py` (追加)

**Interfaces:**
- Consumes: Task 1/2 的 `wl_marks` 全部 API + Task 3 的 `_run_series`/`_build_curve_fig`/`_show_and_save_curve`。
- Produces:
  - `_parse_marks_arg(s: str) -> tuple[float, ...]` — 非法直接 `SystemExit`
  - `_mark_lines(series: dict, marks: dict) -> list[tuple[float, str]]`
  - `_marks_report(src, avi, calib, params, ref_frame, marks) -> dict` — 现算 front + 打印 + 落盘
  - `_render(..., marks_line: Optional[str] = None)` — 新增末参数, HUD 追加一行

- [ ] **Step 1: 追加失败测试**

追加到 `eit_ptlc/tests/test_waterlevel_tune_curve_offline.py`:

```python
import pytest

from eit_ptlc.tools.wl_replay_tune import _mark_lines, _parse_marks_arg


def test_parse_marks_arg():
    assert _parse_marks_arg("5,4,3,2,1") == (5.0, 4.0, 3.0, 2.0, 1.0)
    assert _parse_marks_arg("6, 4, 2") == (6.0, 4.0, 2.0)
    for bad in ("5,4.5", "0,3", "10,3", "5,5", "", "abc"):
        with pytest.raises(SystemExit):
            _parse_marks_arg(bad)


def test_mark_lines():
    series = {"t0": 100.0}
    marks = {"events": [{"cm": 5.0, "frame_idx": 10, "ts": 110.0},
                        {"cm": 3.0, "frame_idx": 50, "ts": None}]}   # ts 缺 → 跳过
    assert _mark_lines(series, marks) == [(10.0, "5cm")]
    assert _mark_lines({"t0": None}, marks) == []                    # 无墙钟 → 不叠线
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_tune_curve_offline.py -q`
Expected: FAIL — `ImportError: cannot import name '_mark_lines'`

- [ ] **Step 3: 实现接线**

在 `eit_ptlc/tools/wl_replay_tune.py`:

3a. 模块级 (紧跟 `_show_and_save_curve` 之后) 追加三个函数:

```python
# ====================================================================
# 标记板打标 (数字键=距板顶 cm 整数值; 真值文件 <stem>.marks.json)
# ====================================================================
def _parse_marks_arg(s: str) -> tuple[float, ...]:
    """--marks 解析: 逗号分隔, 限 1–9 整数 cm (键位=cm 值本身), 去重非空。"""
    try:
        vals = [float(tok) for tok in s.split(",") if tok.strip()]
    except ValueError:
        raise SystemExit(f"--marks 非法: {s!r} (应为逗号分隔数字, 如 5,4,3,2,1)")
    for v in vals:
        if v != int(v) or not 1 <= v <= 9:
            raise SystemExit(f"--marks 项 {v:g} 非法: 数字键=cm 整数值, 限 1–9 整数")
    if not vals or len(set(vals)) != len(vals):
        raise SystemExit(f"--marks 为空或重复: {s!r}")
    return tuple(vals)


def _mark_lines(series: dict, marks: dict) -> list[tuple[float, str]]:
    """标注事件 → 曲线竖线 [(相对秒, '5cm'), ...]; 无墙钟基准或 ts 缺 → 跳过。"""
    t0 = series.get("t0")
    if t0 is None:
        return []
    return [(float(ev["ts"]) - float(t0), f"{float(ev['cm']):g}cm")
            for ev in marks["events"] if ev.get("ts") is not None]


def _marks_report(src, avi: Path, calib, params, ref_frame, marks: dict) -> dict:
    """出标记板报告: 每个标注帧用当前参数现算 front (单帧口径, 同预览; 非守卫
    时序口径 —— 标定用途足够), 组装 → 打印 → 原子落盘。"""
    import dataclasses
    ref = compute_reference(ref_frame, calib, params) if ref_frame is not None else None
    if marks["events"] and ref is None:
        print("[整定台] 未设参考帧 (r), 无法现算标注帧 front — 报告只含真值事件")
    fronts: dict[float, Optional[float]] = {}
    for ev in marks["events"]:
        cm = float(ev["cm"])
        frame = src.get(int(ev["frame_idx"]))
        if ref is None or frame is None:
            fronts[cm] = None
            continue
        r = detect_level(frame, calib, ref=ref, params=params)
        fronts[cm] = r.front_percent if (r.valid and r.front_percent is not None) else None
    report = wl_marks.build_report(
        marks, fronts,
        calib_snapshot=dataclasses.asdict(calib),
        params_snapshot=dataclasses.asdict(params))
    print(wl_marks.format_report(report))
    wl_marks.save_report(wl_marks.report_path(avi), report)
    print(f"[整定台] 报告已落盘 → {wl_marks.report_path(avi).name}")
    return report
```

3b. `_render` 签名与 HUD: `def _render(frame, ref_frame, calib, params, ui=None):` 改为
`def _render(frame, ref_frame, calib, params, ui=None, marks_line=None):`;
`lines = [...]` 列表定义之后追加:

```python
    if marks_line:
        lines.append(marks_line)
```

3c. argparse (main 内 `--backend` 之后) 追加:

```python
    ap.add_argument("--marks", default="5,4,3,2,1",
                    help="标线高度表 (距板顶 cm, 逗号分隔 1–9 整数; 数字键=cm 值本身)")
```

3d. main 启动段 (在 `print(HELP)` 之前) 追加:

```python
    marks_cm_cli = _parse_marks_arg(args.marks)
    mpath = wl_marks.marks_path(avi)
    try:
        marks = wl_marks.load_marks(mpath)
    except ValueError as exc:
        print(f"[整定台] {exc} — 忽略损坏 marks, 从空白开始 (首次打标才覆盖原文件)")
        marks = None
    if marks is None:
        marks = wl_marks.new_marks(meta.get("channel"), avi.name, marks_cm_cli)
    elif tuple(float(c) for c in marks["marks_cm"]) != marks_cm_cli \
            and args.marks != "5,4,3,2,1":
        print(f"[整定台] marks 文件已有标线表 {marks['marks_cm']} (文件权威), 忽略 --marks")
    stamps = wl_marks.load_timestamps(wl_marks.jsonl_path(avi))
    if not stamps:
        print("[整定台] ! 无 .jsonl 时间戳: 打标可用, 但区间速度/曲线叠线缺席")
    if marks["events"]:
        print(f"[整定台] {wl_marks.format_hud_line(marks)}")
```

3e. 主循环: `sig = (...)` 元组改为在末尾追加一项 `wl_marks.format_hud_line(marks)`
(标注变更即触发重渲染); `_render(frame, ref_frame, calib, params, ui)` 调用改为:

```python
                canvas, _res = _render(frame, ref_frame, calib, params, ui,
                                       marks_line=wl_marks.format_hud_line(marks))
```

3f. 键循环追加数字键分支 (放在 `elif key == ord("h"):` 之前; 现有热键无数字, 无冲突):

```python
        elif ord("1") <= key <= ord("9"):
            cm = float(key - ord("0"))
            if cm not in (float(c) for c in marks["marks_cm"]):
                print(f"[整定台] {cm:g}cm 不在标线表 {marks['marks_cm']} (--marks 可改)")
            else:
                action = wl_marks.toggle_event(marks, cm, fidx, stamps.get(fidx))
                wl_marks.save_marks(mpath, marks)
                zh = {"set": "打标", "moved": "改标", "cleared": "取消"}[action]
                print(f"[整定台] {cm:g}cm 线 {zh} @f{fidx}  → {mpath.name}")
```

3g. `c` 分支 (Task 3d 的版本) 扩为报告 + 叠线:

```python
        elif key == ord("c"):
            stride = max(1, cv2.getTrackbarPos("c_speed(xN)", CTRL_WIN))
            series = _run_series(avi, calib, params, src.get(ridx),
                                 stride=stride, n_total=src.n)
            if series is not None:
                _marks_report(src, avi, calib, params, src.get(ridx), marks)
                fig = _build_curve_fig(avi, calib, params, series, stride,
                                       mark_lines=_mark_lines(series, marks))
                _show_and_save_curve(avi, fig)
```

3h. `HELP` 追加一行 (在鼠标行之前):

```
              数字键1-9 打标: 当前帧=该 cm 标线越线帧 (键=距板顶 cm 值; 重按换帧, 同帧再按取消)
```

- [ ] **Step 4: 跑测试确认通过 + 全套件回归**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_tune_curve_offline.py eit_ptlc/tests/test_waterlevel_marks_offline.py -q`
Expected: `17 passed`

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests -q`
Expected: 全绿 (基线 623+ passed, 0 failed)

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/tools/wl_replay_tune.py eit_ptlc/tests/test_waterlevel_tune_curve_offline.py
git commit -m "feat(整定台): 标记板打标热键+HUD+%↔cm报告 — 数字键=cm值, marks.json 真值旁挂, c 出报告+曲线叠线"
```

---

### Task 5: P0 实验手册修订 + 收尾

**Files:**
- Modify: `docs/液位自动排液_P0实验手册_20260713.md`

**Interfaces:**
- Consumes: Task 4 的完整工具链 (打标 → `c` 报告)。
- Produces: 修订后的实验手册 (标线为主尺)。

- [ ] **Step 1: 修订手册**

对 `docs/液位自动排液_P0实验手册_20260713.md` 做三处修改:

1a. 实验 A 第 5 步整段替换:

```markdown
5. 整定台 (wl_replay_tune) 打开录制: 拖帧到前沿越各标线帧按数字键打标
   (键=距板顶 cm 值; 1cm 被盖挡住可不标, 缺省自动适配), 按 c 出报告 ——
   %↔cm 拟合 / 每线残差 / 区间速度自动算, 落 <stem>.marks_report.json。
   触发→排液完成净推进量 (含砂芯残液段) **以标线为主尺直读**:
   对齐时间戳看 t2 命中帧与 Tank_State=99 帧的前沿各在哪两条标线之间;
   front_percent(t) 曲线降为辅助交叉。
```

1b. 实验 B 标题行 `## 实验 B: 色素滴注交叉验证 (不依赖检测算法)` 之后紧跟追加一段:

```markdown
> 2026-07-17 降级为抽查: 标记板真值已内建于实验 A (每段录像自带 ≤5 个
> 免费真值事件, 离线可反复读)。仅当标线读数与检测曲线差异大、需要第三方
> 仲裁时才做色素滴注。
```

1c. 文末 (看门狗行之后) 新增一节:

```markdown
## 实验 C: 标定板全通道战役 (%↔cm 物理刻度)

1. 同一块标记板 (距板顶 5/4/3/2/1cm 标线) 在各通道各跑一次展开 + 录制。
2. 整定台逐段打标 + c 出报告 → 每通道一份 %↔cm 线性映射
   (<stem>.marks_report.json, 含反演公式 d(front%) 与 R² 线性度)。
3. 用途: 把任意 front_percent 读数换算成"液位距板顶 X cm"; R² 偏低的
   通道提示透视/ROI 不正, 先复核标定再采信物理读数。
4. 净推进量换算不再依赖 ROI 物理长度目测: 直接用该通道拟合斜率
   |a| (%/cm) 换算。此数据同时为"标定写回 config"(方案 C, 缓议) 备料。
```

- [ ] **Step 2: 全套件最终回归**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests -q`
Expected: 全绿

- [ ] **Step 3: Commit**

```bash
git add "docs/液位自动排液_P0实验手册_20260713.md"
git commit -m "docs(P0手册): 标线为主尺读数 / 实验B降抽查 / 新增标定板全通道战役"
```

- [ ] **Step 4: 上机人工验证清单 (留给真机时段, 不阻塞合并)**

- [ ] 真录像按 `c`: 进度实时滚动, 预览窗不再"未响应", Esc 可中断;
- [ ] 曲线窗显示正常 + `<stem>.curve.png` 落盘 (中文 label 若显示为方框, 属 matplotlib 字体既有现状, 不在本期范围);
- [ ] 拖帧打标 5/4/3/2 (1cm 缺): HUD 行正确, 重开工具标注还在;
- [ ] `c` 报告: 拟合/反演公式/区间速度/建议行齐全, 曲线上有标线竖虚线;
- [ ] 故意不设参考帧按 `c`: 报告提示"先按 r 设参考帧"语义 (只列真值事件);
- [ ] 标定板全通道战役首块板走通后, 回填 marks_report 数据到手册。
