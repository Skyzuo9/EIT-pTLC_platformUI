# 固定刮取路径（回收率实验） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给回收率实验提供一个「固定矩形刮取路径」——脚本产出与视觉/手绘同契约的 `summary.json`，`photoscrape_process` 经一个默认空的输入变量把它覆盖注入并跳过人工门。

**Architecture:** 两部分。(A) 命令行脚本 `eit_ptlc/tools/fixed_scrape_path.py`：把 (x0,y0,w,h)[板 cm] 转成 4 角 `contour_cm`，调用**现成** `sketch_path.write_manual_summary` 落盘，打印 `summary_path`。(B) `photoscrape_process.yaml` 加输入变量 `fixed_summary_path`（默认 `""`）+ 门前 8 行 `if`：非空则用它算路径并自动下发（`dispatched=true`），空则行为逐字节不变。

**Tech Stack:** Python 3.11（conda env `platformupper`）、pytest、既有 `eit_ptlc.controller.sketch_path` / `cnc_path` / `config`、operation VM（`eit_ptlc.operation.vm`）、YAML operation DSL。

## Global Constraints

- Python 环境：conda env `platformupper`（`E:\Anaconda\envs\platformupper\python.exe`，3.11）。测试命令一律用该 env 的 pytest。
- 全程**离线可跑**（SDD）：不接 PLC / 相机 / 真机；不得引入运行时依赖。
- 文件放置规范：脚本入 `eit_ptlc/tools/`（与既有 `tools/*` 同层）；测试入 `eit_ptlc/tests/`（`test_*_offline.py` 命名）。
- **零几何新代码**：路径落盘复用 `sketch_path.write_manual_summary`；预览复用未改动的 `cnc_path.generate_scrape_arrays`。
- **生产零回归**：`fixed_summary_path` 默认 `""` 时 `photoscrape_process` 现有全部离线测试必须继续绿。
- band_id 默认 `fixed_01`，脚本与 operation 输入变量 `fixed_band_id` 默认对齐。
- 坐标系：板 cm，原点在 `gcode.origin_corner`（当前 `top-right`），`+x/+y` 入板；cm→机床 mm 由未改动的 `cnc_path._to_machine` 处理。

---

### Task 1: 脚本 `fixed_scrape_path.py`（固定矩形 → summary.json）

**Files:**
- Create: `eit_ptlc/tools/fixed_scrape_path.py`
- Test: `eit_ptlc/tests/test_fixed_scrape_path_offline.py`

**Interfaces:**
- Consumes（现成，不改）:
  - `eit_ptlc.controller.sketch_path.write_manual_summary(contour_cm, workspace_dir, *, band_id="manual_01", plate_bbox_px=None) -> Path`（写 `summary.json` + `<band_id>_path.json`；`path.json` 结构 `{"scrape_path": {"bbox_cm": {"x_min","y_min","x_max","y_max"}}, "contour_cm": [{"x_cm","y_cm"}, ...]}`）
  - `eit_ptlc.controller.cnc_path.generate_scrape_arrays(summary_path, band_id, gcode_cfg, *, strategy=None) -> ScrapeArrays`（字段 `g_sx,g_sy,g_cx,g_cy: list[float]`、`g_scrape_feed: int`、`pass_count: int`）
  - `eit_ptlc.config.models.GCodeCfg`（无参构造 `GCodeCfg()` 给默认标定）
- Produces（后续任务 / 使用者依赖）:
  - `build_fixed_contour_cm(x0: float, y0: float, w: float, h: float) -> list[tuple[float, float]]` — 返回 4 角矩形，顺序 `[(x0,y0),(x0+w,y0),(x0+w,y0+h),(x0,y0+h)]`
  - `write_fixed_summary(x0, y0, w, h, out_dir: Path, *, band_id: str = "fixed_01") -> Path` — 返回 `summary.json` 绝对路径
  - `main(argv: list[str] | None = None) -> int` — CLI 入口；stdout 打印 `summary_path=<abs>` 与 `band_id=<id>`，`--preview` 时另打印 `preview pass_count=.. point_count=.. feed=..`

- [ ] **Step 1: 写失败测试**

创建 `eit_ptlc/tests/test_fixed_scrape_path_offline.py`：

```python
"""固定刮取路径脚本离线测试 — 证明 (x0,y0,w,h) → 与视觉/手绘同契约的 summary,
且被**未改动的** cnc_path.generate_scrape_arrays 消费得到非退化 400 点路径。"""

from __future__ import annotations

import json
from pathlib import Path

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller.cnc_path import SCRAPE_POINT_COUNT, generate_scrape_arrays
from eit_ptlc.tools import fixed_scrape_path as fsp


def test_build_fixed_contour_cm_is_rectangle():
    c = fsp.build_fixed_contour_cm(3.0, 4.0, 10.0, 5.0)
    assert c == [(3.0, 4.0), (13.0, 4.0), (13.0, 9.0), (3.0, 9.0)]


def test_write_fixed_summary_contract(tmp_path):
    summary_path = fsp.write_fixed_summary(3.0, 4.0, 10.0, 5.0, tmp_path, band_id="fixed_01")
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert [b["band_id"] for b in summary["bands"]] == ["fixed_01"]
    path_json = summary_path.parent / "fixed_01_path.json"
    assert path_json.is_file()
    doc = json.loads(path_json.read_text(encoding="utf-8"))
    bbox = doc["scrape_path"]["bbox_cm"]
    assert (bbox["x_min"], bbox["y_min"], bbox["x_max"], bbox["y_max"]) == (3.0, 4.0, 13.0, 9.0)
    assert len(doc["contour_cm"]) == 4


def test_summary_feeds_cnc_path_400_points(tmp_path):
    summary_path = fsp.write_fixed_summary(3.0, 4.0, 10.0, 5.0, tmp_path, band_id="fixed_01")
    arr = generate_scrape_arrays(summary_path, "fixed_01", GCodeCfg())
    assert len(arr.g_sx) == SCRAPE_POINT_COUNT == 400
    assert arr.pass_count >= 1
    # 非退化: 刮取点在 X 上有真实展开(不是全 collapse 到一点)
    assert max(arr.g_sx) - min(arr.g_sx) > 1.0


def test_main_prints_summary_path_and_preview(tmp_path, capsys):
    rc = fsp.main(["--x0", "3", "--y0", "4", "--w", "10", "--h", "5",
                   "--out", str(tmp_path), "--band-id", "fixed_01", "--preview"])
    assert rc == 0
    out = capsys.readouterr().out
    # write_fixed_summary 返回 .resolve() 后的绝对路径, 断言也用 resolve 防 Windows 路径规范化差异
    assert f"summary_path={(tmp_path / 'summary.json').resolve()}" in out
    assert "band_id=fixed_01" in out
    assert "preview pass_count=" in out
    assert "point_count=400" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_fixed_scrape_path_offline.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'eit_ptlc.tools.fixed_scrape_path'`

- [ ] **Step 3: 写脚本实现**

创建 `eit_ptlc/tools/fixed_scrape_path.py`：

```python
"""固定刮取路径 — 回收率实验用。

把一个已知起点、固定尺寸的矩形(板 cm)变成与视觉/手绘**同契约**的 summary.json,
交给**未改动的** cnc_path 消费。零新几何代码: 落盘复用 sketch_path.write_manual_summary,
预览复用 cnc_path.generate_scrape_arrays。

用法:
    python -m eit_ptlc.tools.fixed_scrape_path --x0 3 --y0 4 --w 10 --h 5 \
        [--band-id fixed_01] [--out DIR] [--preview]

坐标系: 板 cm, 原点在 gcode.origin_corner, +x/+y 入板(与视觉/手绘同框)。
输出(stdout): summary_path=<abs> / band_id=<id> / [preview pass_count=.. point_count=.. feed=..]
把 summary_path 传给 photoscrape_process 的 fixed_summary_path 输入变量即用固定路径跑刮取+收集。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eit_ptlc.controller import sketch_path as sp

DEFAULT_BAND_ID = "fixed_01"
DEFAULT_OUT = "vision_output/fixed_scrape"  # 与 config vision.output_dir 默认对齐; 自定义 output_dir 时用 --out
_PKG_DIR = Path(__file__).resolve().parent.parent          # eit_ptlc/
DEFAULT_CONFIG = _PKG_DIR / "config" / "app.yaml"           # 与其他 tools/ 定位方式一致


def build_fixed_contour_cm(x0: float, y0: float, w: float, h: float) -> list[tuple[float, float]]:
    """矩形 4 角(板 cm), 顺序 [左下→右下→右上→左上](按 x0,y0 起点 + w,h 展开)。"""
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]


def write_fixed_summary(
    x0: float, y0: float, w: float, h: float, out_dir: Path, *, band_id: str = DEFAULT_BAND_ID,
) -> Path:
    """落固定矩形的 summary.json + <band_id>_path.json, 返回 summary.json 绝对路径。

    直接用 cm 指定, 跳过像素↔cm 映射(plate_bbox_px=None); 产物与视觉/手绘完全同形。
    """
    contour_cm = build_fixed_contour_cm(x0, y0, w, h)
    return sp.write_manual_summary(contour_cm, Path(out_dir), band_id=band_id).resolve()


def _preview(summary_path: Path, band_id: str, config_path: Path) -> str:
    """跑未改动的 generate_scrape_arrays, 返回可读预览串; 需要 gcode 配置(仅 --preview 时)。"""
    from eit_ptlc.config.loader import load_config
    from eit_ptlc.controller.cnc_path import generate_scrape_arrays

    gcode_cfg = load_config(config_path).gcode  # 读 app.yaml 的实时 gcode 标定
    arr = generate_scrape_arrays(summary_path, band_id, gcode_cfg)
    return f"preview pass_count={arr.pass_count} point_count={len(arr.g_sx)} feed={arr.g_scrape_feed}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成固定矩形刮取路径 summary(回收率实验)")
    ap.add_argument("--x0", type=float, required=True, help="起点 X(板 cm)")
    ap.add_argument("--y0", type=float, required=True, help="起点 Y(板 cm)")
    ap.add_argument("--w", type=float, default=10.0, help="沿 X 宽度 cm(默认 10)")
    ap.add_argument("--h", type=float, default=5.0, help="沿 Y 高度 cm(默认 5)")
    ap.add_argument("--band-id", default=DEFAULT_BAND_ID, help="band_id(默认 fixed_01)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="summary 输出目录(默认 vision_output/fixed_scrape)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="app.yaml 路径(仅 --preview 用)")
    ap.add_argument("--preview", action="store_true", help="额外打印 pass数/点数/进给(需 gcode 配置)")
    a = ap.parse_args(argv)

    summary_path = write_fixed_summary(a.x0, a.y0, a.w, a.h, Path(a.out), band_id=a.band_id)
    print(f"summary_path={summary_path}")
    print(f"band_id={a.band_id}")
    if a.preview:
        print(_preview(summary_path, a.band_id, Path(a.config)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

**已核实的接口**：`eit_ptlc.config.loader.load_config(path: Path) -> AppConfig`（`loader.py:112`），`AppConfig.gcode` 即解析好的 `GCodeCfg`（`loader.py:147`）。`DEFAULT_CONFIG` 用 `_PKG_DIR / "config" / "app.yaml"`，与 `tools/plc_l2_acceptance.py` / `tools/gen_robot_point_operations.py` 定位方式一致。

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_fixed_scrape_path_offline.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/tools/fixed_scrape_path.py eit_ptlc/tests/test_fixed_scrape_path_offline.py
git commit -m "feat(fixed-scrape): 固定矩形刮取路径脚本(复用 write_manual_summary, 同契约 summary)"
```

---

### Task 2: `photoscrape_process.yaml` B1 注入（输入变量预种跳过门）

**Files:**
- Modify: `eit_ptlc/config/operation/03_photoscrape/photoscrape_process.yaml`（vars 段加 2 行；步骤 (3) 后插入 (3b) 块）
- Test: `eit_ptlc/tests/test_photoscrape_gate_flow_offline.py`（新增 2 个测试函数）

**Interfaces:**
- Consumes: Task 1 产出的 `summary.json` 路径（作为 `fixed_summary_path` 传入 operation）。
- Produces: `photoscrape_process` 新增 io:in 变量 `fixed_summary_path`（默认 `""`）与 `fixed_band_id`（默认 `fixed_01`）；非空时 `cnc` 来自该 summary、`dispatched=true`、不发任何 `vm_human_request`。

- [ ] **Step 1: 写失败测试**

在 `eit_ptlc/tests/test_photoscrape_gate_flow_offline.py` 末尾追加。先在文件顶部常量区（`CNC = {...}` 附近）加一个固定 summary 常量：

```python
FIXED_SUMMARY = "/fixed/summary.json"
```

然后追加两个测试：

```python
def test_fixed_summary_path_dispatches_without_gate():
    # B1: 传入 fixed_summary_path → 用它算路径, 直接下发, 无人工门
    ex = PhotoExecutor()
    events: list[dict] = []
    c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append)
    s = _run(c.start(_doc(), {"mode": "manual", "sample_id": "T", "save_dir": "/x",
                              "before_path": "/x/before.jpg",
                              "fixed_summary_path": FIXED_SUMMARY,
                              "fixed_band_id": "fixed_01"}, mode_run="run"))
    rid = s["run_id"]
    assert _run(wait_status(c, rid, "DONE")), f"未到 DONE: {c.state(rid)}"
    # 无任何人工门(即便 mode=manual)
    assert not any(e["type"] == "vm_human_request" for e in events)
    # cnc_path 用固定 summary 算过, 且真机块写发生(走到刮取收尾)
    cnc_calls = [p for (n, p) in ex.calls if n == "photoscrape.cnc_path"]
    assert any(p.get("summary_path") == FIXED_SUMMARY and p.get("band_id") == "fixed_01"
               for p in cnc_calls), f"cnc_path 未用固定 summary: {cnc_calls}"
    assert "photoscrape.write_cnc_path" in _names(ex)
    assert "photoscrape.scrape_finish" in _names(ex)


def test_empty_fixed_summary_path_keeps_manual_gate():
    # B1 默认: fixed_summary_path 缺省("") → 原 manual 门流程不变(仍进门)
    ex, events = _run(_drive("manual",
                             [{"values": {"band_id": "band_01"}}, {"choice": "dispatch"}], "DONE"))
    assert any(e["type"] == "vm_human_request" and e.get("kind") == "choose" for e in events)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_photoscrape_gate_flow_offline.py::test_fixed_summary_path_dispatches_without_gate -v`
Expected: FAIL —`fixed_summary_path` 未声明为变量 → VM 忽略输入或报未知变量；且 (3b) 块不存在 → 仍进门 → 卡 `WAITING_HUMAN` / 断言 `no vm_human_request` 失败。

（`test_empty_fixed_summary_path_keeps_manual_gate` 此刻应已通过——它是回归护栏。）

- [ ] **Step 3: 改 operation YAML**

在 `eit_ptlc/config/operation/03_photoscrape/photoscrape_process.yaml` 的 `vars:` 段，`reanalyze_annotated_url` 那条之后（约第 55 行）加两行：

```yaml
  - {name: fixed_summary_path, scope: local, type: STRING, io: in, default: "",        comment: "固定路径实验: 非空则用此 summary 覆盖视觉/手绘, 直接下发跳过人工门"}
  - {name: fixed_band_id,      scope: local, type: STRING, io: in, default: fixed_01,  comment: 固定路径 band_id(与 fixed_scrape_path 脚本默认对齐)}
```

在 `body:` 段，步骤 (3) 的 `try/catch` 块结束之后、步骤 (4) 的注释 `"(4) 自动模式: ..."` 之前，插入 (3b) 块：

```yaml
  - {op: comment, text: "(3b) 固定路径实验(回收率): fixed_summary_path 非空 → 用它算路径覆盖候选, 自动下发跳过门; 默认空则本块不进, 生产行为逐字节不变"}
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

设计意图（勿加 try/catch）：固定路径几何非法应显式 fault 交 run-control，不静默落回门——实验要么按预期跑要么明确报错。

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_photoscrape_gate_flow_offline.py -v`
Expected: PASS（原有全部 + 2 个新增，全绿）。重点：`test_fixed_summary_path_dispatches_without_gate` 与 `test_empty_fixed_summary_path_keeps_manual_gate` 均 PASS，且旧门测试（dispatch/sketch/reanalyze/skip/abort）不回归。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/config/operation/03_photoscrape/photoscrape_process.yaml eit_ptlc/tests/test_photoscrape_gate_flow_offline.py
git commit -m "feat(photoscrape): B1 固定路径注入(fixed_summary_path 预种跳过门, 默认空零回归)"
```

---

### Task 3: 全套离线回归 + 使用说明落文档

**Files:**
- Modify: `docs/superpowers/specs/2026-07-08-fixed-scrape-path-design.md`（可选：把「使用流程」定稿实际命令）

- [ ] **Step 1: 跑相关离线套件确认全绿**

Run:
```
E:/Anaconda/envs/platformupper/python.exe -m pytest \
  eit_ptlc/tests/test_fixed_scrape_path_offline.py \
  eit_ptlc/tests/test_photoscrape_gate_flow_offline.py \
  eit_ptlc/tests/test_photoscrape_four_stage_offline.py \
  eit_ptlc/tests/test_sketch_path_offline.py \
  eit_ptlc/tests/test_cnc_path_offline.py -v
```
Expected: 全 PASS，无回归。

- [ ] **Step 2: 端到端手验脚本（离线）**

Run:
```
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tools.fixed_scrape_path \
  --x0 3 --y0 4 --w 10 --h 5 --out var/tmp_fixed_exp --preview
```
Expected: stdout 出现 `summary_path=...var/tmp_fixed_exp/summary.json`、`band_id=fixed_01`、`preview pass_count=1 point_count=400 feed=800`（feed 随 config），且该目录下生成 `summary.json` + `fixed_01_path.json`。删除临时目录。

- [ ] **Step 3: 提交（若有文档改动）**

```bash
git add docs/superpowers/specs/2026-07-08-fixed-scrape-path-design.md
git commit -m "docs(fixed-scrape): 使用流程定稿实际命令"
```

（若 Step 2 只是验证、无文件改动，可跳过本提交。）

---

## 待真机（不在本计划离线范围）

- 首次用小尺寸 + 低进给 dry-run 核对起点方向与刮取覆盖（板 cm ↔ 机床 mm 翻转）。
- 回收率实验期间建议 `gcode.collection.return_sweep=true`（全面收集，见 memory `cnc-collect-path-tail-return`）。
- 越板保护：脚本不硬拦 `x0+w`/`y0+h` 越界；靠 `--preview` 机床 mm + dry-run 兜底。
