# 液位整定台终端敲值 + 两级存盘 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `wl_replay_tune.py` 整定台加终端精确敲值 REPL(`e`)与显式两级存盘(`w` 存草稿 / `W` 并入生产真源),并把散落的滑块标度换算抽成单一真源 `PARAM_SPECS`。

**Architecture:** 全部改动落在单文件 `eit_ptlc/tools/wl_replay_tune.py` + 一份纯函数离线测试 `eit_ptlc/tests/test_waterlevel_tune_offline.py`。核心是把"自然值 ↔ 滑块 int"的标度封进纯函数表 `PARAM_SPECS`,建轨/读轨/敲值三处共用;敲值走既有"回填滑块 → 主循环 `_read_state` 每帧读"数据流,不新开并行状态;`W` 走 `load_channel_configs → 换单通道 → save_channel_configs`(覆盖写但保留其余通道)。

**Tech Stack:** Python 3, OpenCV(HighGUI trackbar,已有依赖),项目自研 `check()` 离线测试框架(非 pytest)。

## Global Constraints

- **零新依赖 / 零新算法**:只用已有 `cv2`、`waterlevel_detector`、`waterlevel_store`。逐字沿用文件既有哲学"只把现成积木串成交互外壳"。
- **滑块层保持可用**:敲值即时生效仍走"回填 trackbar → `_read_state` 每帧读"既有数据流;改值看效果不需要任何 commit,是实时的。
- **写生产真源是较重的 outward-facing 动作**:`W` 必须显式 + 一次终端确认;无 ROI(`not calib.calibrated`)拒写;`meta['channel']` 缺失则中止不猜。
- **纯函数可无 GUI 离线测**:`PARAM_SPECS` 的 `to_pos/from_pos`、`parse_edit_command`、`commit_to_source` 不得依赖活 trackbar;涉及 trackbar 的薄封装(`_current_value`/`_apply_value`)与 GUI 运行时校验为手动步骤。
- **测试约定**:项目用自研离线测试,非 pytest。测试文件形如 `_run()` + `check(name, cond, detail)`,`python -m eit_ptlc.tests.test_xxx_offline` 运行,返回 0/1。
- **通道键 1-based**:store 与 recorder 均用 1-based 通道号,`meta['channel']` 与真源槽位一致。
- **真源路径**:`Path(__file__).resolve().parents[1] / "config" / "water_level_calib.json"`(与既有 `_load_initial` 同一路径)。

---

### Task 1: `PARAM_SPECS` 标度单一真源 + `parse_edit_command`(纯函数, 离线测)

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py`(在 `FLOWS` 常量后、`_UIState` 前插入新代码块)
- Test: `eit_ptlc/tests/test_waterlevel_tune_offline.py`(新建)

**Interfaces:**
- Consumes: 无(纯声明)。
- Produces:
  - `class ParamSpec`(frozen dataclass):字段 `key:str, trackbar:str, track_hi:int, lo:float, hi:float, to_pos:Callable[[float],int], from_pos:Callable[[int],float], is_int:bool, hint:str`。
  - `PARAM_SPECS: list[ParamSpec]`、`SPECS: dict[str, ParamSpec]`。
  - `ROTATION_KEY = "rotation_deg"`。
  - `edit_menu() -> list[tuple[str, str]]`:返回 `[(key, hint)]`,index 0 = rotation,其后 `PARAM_SPECS`。
  - `parse_edit_command(line: str) -> tuple[Optional[str], object]`:成功 `(key, float_value)`;错误 `("__error__", msg)`;退出 `(None, None)`。

- [ ] **Step 1: 写失败测试** — 新建 `eit_ptlc/tests/test_waterlevel_tune_offline.py`

```python
"""液位整定台纯函数离线测试
============================
功能:
    验证 tools/wl_replay_tune 的无 GUI 纯逻辑:
      - PARAM_SPECS 标度往返 (from_pos(to_pos(v)) ≈ v) + 与旧内联公式等价
      - parse_edit_command 解析 (编号/短名/空行/非法/越界)
      - commit_to_source load-merge-save (Task 4 追加)

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline
"""

from __future__ import annotations

import sys

from eit_ptlc.tools.wl_replay_tune import (
    PARAM_SPECS,
    SPECS,
    ROTATION_KEY,
    edit_menu,
    parse_edit_command,
)


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # ---- PARAM_SPECS 标度往返 ----
    samples = {
        "diff_thr": 7.5, "wet_thr": 12.0, "front_lvl": 0.5,
        "roi_fx": 0.30, "roi_fy": 0.05, "roi_fw": 0.20, "roi_fh": 0.80,
        "crop_x": 0.12, "crop_y": 0.10, "blur_ksize": 5, "flow": 1,
    }
    for key, v in samples.items():
        s = SPECS[key]
        back = s.from_pos(s.to_pos(v))
        tol = 1.0 if s.is_int else 1.0 / 100.0 + 1e-9
        check(f"roundtrip_{key}", abs(back - v) <= tol, f"{v} -> {s.to_pos(v)} -> {back}")

    # ---- 与旧内联公式等价 (钉死 dedup 不改行为) ----
    check("eq_diff_thr", SPECS["diff_thr"].to_pos(7.5) == 75, str(SPECS["diff_thr"].to_pos(7.5)))
    check("eq_wet_thr", SPECS["wet_thr"].to_pos(12.0) == 120, str(SPECS["wet_thr"].to_pos(12.0)))
    check("eq_front_lvl", SPECS["front_lvl"].to_pos(0.5) == 50, str(SPECS["front_lvl"].to_pos(0.5)))
    check("eq_roi_fx", SPECS["roi_fx"].to_pos(0.30) == 300, str(SPECS["roi_fx"].to_pos(0.30)))
    check("eq_roi_fw_floor", SPECS["roi_fw"].from_pos(0) == 1 / 1000.0, str(SPECS["roi_fw"].from_pos(0)))
    check("eq_crop_x", SPECS["crop_x"].to_pos(0.12) == 12, str(SPECS["crop_x"].to_pos(0.12)))
    check("eq_blur", SPECS["blur_ksize"].to_pos(5) == 2 and SPECS["blur_ksize"].from_pos(2) == 5,
          f"{SPECS['blur_ksize'].to_pos(5)}/{SPECS['blur_ksize'].from_pos(2)}")

    # ---- 越界 clamp 到滑块范围 ----
    check("clamp_diff_hi", SPECS["diff_thr"].to_pos(999.0) == 500, str(SPECS["diff_thr"].to_pos(999.0)))
    check("clamp_crop_hi", SPECS["crop_x"].to_pos(9.0) == 40, str(SPECS["crop_x"].to_pos(9.0)))

    # ---- edit_menu: 0=rotation ----
    menu = edit_menu()
    check("menu_head_rotation", menu[0][0] == ROTATION_KEY, str(menu[0]))
    check("menu_len", len(menu) == 1 + len(PARAM_SPECS), str(len(menu)))

    # ---- parse_edit_command ----
    check("parse_by_index", parse_edit_command("10 7.5") == (PARAM_SPECS[9].key, 7.5),
          str(parse_edit_command("10 7.5")))
    check("parse_by_name", parse_edit_command("diff_thr 7.5") == ("diff_thr", 7.5),
          str(parse_edit_command("diff_thr 7.5")))
    check("parse_rotation", parse_edit_command("0 -3.2") == (ROTATION_KEY, -3.2),
          str(parse_edit_command("0 -3.2")))
    check("parse_empty_exit", parse_edit_command("") == (None, None), str(parse_edit_command("")))
    check("parse_q_exit", parse_edit_command("q") == (None, None), str(parse_edit_command("q")))
    k, m = parse_edit_command("foo 1")
    check("parse_unknown", k == "__error__", f"{k}/{m}")
    k, m = parse_edit_command("diff_thr abc")
    check("parse_nan", k == "__error__", f"{k}/{m}")
    k, m = parse_edit_command("diff_thr")
    check("parse_arity", k == "__error__", f"{k}/{m}")

    print(f"\n失败 {len(failures)}")
    return 1 if failures else 0


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

Run: `"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline`
Expected: FAIL — `ImportError: cannot import name 'PARAM_SPECS'`(实现未写)。

- [ ] **Step 3: 写实现** — 在 `wl_replay_tune.py` 的 `FLOWS = [...]` 行之后插入:

```python
from dataclasses import dataclass
from typing import Callable


# ====================================================================
# 参数标度单一真源: 自然值 <-> 滑块 int (建轨/读轨/敲值 REPL 三处共用)
# ====================================================================
@dataclass(frozen=True)
class ParamSpec:
    """一个可敲参数的标度规格。to_pos/from_pos 为纯函数, 无 cv2 依赖, 可离线测。"""
    key: str
    trackbar: str
    track_hi: int
    lo: float
    hi: float
    to_pos: Callable[[float], int]
    from_pos: Callable[[int], float]
    is_int: bool
    hint: str


PARAM_SPECS: list[ParamSpec] = [
    ParamSpec("flow", "flow 0L>R1R>L2B>T", 2, 0, 2,
              lambda v: max(0, min(2, int(round(v)))), lambda p: int(p), True, "0=L>R 1=R>L 2=B>T"),
    ParamSpec("roi_fx", "roi_fx(/1000)", 999, 0.0, 0.999,
              lambda v: max(0, min(999, int(round(v * 1000)))), lambda p: p / 1000.0, False, "比例 0~0.999"),
    ParamSpec("roi_fy", "roi_fy(/1000)", 999, 0.0, 0.999,
              lambda v: max(0, min(999, int(round(v * 1000)))), lambda p: p / 1000.0, False, "比例 0~0.999"),
    ParamSpec("roi_fw", "roi_fw(/1000)", 1000, 0.001, 1.0,
              lambda v: max(1, min(1000, int(round(v * 1000)))), lambda p: max(1, p) / 1000.0, False, "比例 0.001~1.0"),
    ParamSpec("roi_fh", "roi_fh(/1000)", 1000, 0.001, 1.0,
              lambda v: max(1, min(1000, int(round(v * 1000)))), lambda p: max(1, p) / 1000.0, False, "比例 0.001~1.0"),
    ParamSpec("crop_x", "crop_x(%)", 40, 0.0, 0.40,
              lambda v: max(0, min(40, int(round(v * 100)))), lambda p: p / 100.0, False, "比例 0~0.40"),
    ParamSpec("crop_y", "crop_y(%)", 40, 0.0, 0.40,
              lambda v: max(0, min(40, int(round(v * 100)))), lambda p: p / 100.0, False, "比例 0~0.40"),
    ParamSpec("blur_ksize", "blur(2v+1)", 15, 1, 31,
              lambda v: max(0, min(15, int(round((v - 1) / 2)))), lambda p: 2 * int(p) + 1, True, "奇数核 1~31"),
    ParamSpec("diff_thr", "diff_thr(x10)", 500, 0.0, 50.0,
              lambda v: max(0, min(500, int(round(v * 10)))), lambda p: p / 10.0, False, "0~50"),
    ParamSpec("wet_thr", "wet_thr(x10)", 1000, 0.0, 100.0,
              lambda v: max(0, min(1000, int(round(v * 10)))), lambda p: p / 10.0, False, "0~100"),
    ParamSpec("front_lvl", "front_lvl(%)", 100, 0.0, 1.0,
              lambda v: max(0, min(100, int(round(v * 100)))), lambda p: p / 100.0, False, "0~1"),
]
SPECS: dict[str, ParamSpec] = {s.key: s for s in PARAM_SPECS}
ROTATION_KEY = "rotation_deg"


def edit_menu() -> list[tuple[str, str]]:
    """敲值菜单顺序: index 0 = rotation(非滑块, 写 ui.angle_deg), 其后 PARAM_SPECS 各项。"""
    return [(ROTATION_KEY, "角度 -45~45")] + [(s.key, s.hint) for s in PARAM_SPECS]


def parse_edit_command(line: str):
    """解析一行敲值命令 → (key, value)。

    '<编号|短名> <值>' → (key, float);空行/'q' → (None, None);非法 → ('__error__', 提示串)。
    纯函数, 不碰 cv2, 供离线测。
    """
    line = line.strip()
    if line == "" or line.lower() == "q":
        return (None, None)
    parts = line.split()
    if len(parts) != 2:
        return ("__error__", "格式: <编号|短名> <值>")
    tok, valstr = parts
    menu = edit_menu()
    keys = [k for k, _ in menu]
    key = None
    if tok.isdigit():
        i = int(tok)
        if 0 <= i < len(menu):
            key = keys[i]
    elif tok in keys:
        key = tok
    if key is None:
        return ("__error__", f"未知参数: {tok}")
    try:
        value = float(valstr)
    except ValueError:
        return ("__error__", f"非数字: {valstr}")
    return (key, value)
```

**注意**:文件顶部已 `from typing import Optional`;`dataclass`/`Callable` 用局部 import(如上)避免动顶部 import 块。若顶部已有 `from typing import ...`,把 `Callable` 并入即可。

- [ ] **Step 4: 跑测试确认通过**

Run: `"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline`
Expected: PASS(全部用例 PASS,末行 `失败 0`)。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/tools/wl_replay_tune.py eit_ptlc/tests/test_waterlevel_tune_offline.py
git commit -m "feat(wl-tune): PARAM_SPECS 标度单一真源 + parse_edit_command (纯函数+离线测)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 建轨/读轨路由到 `PARAM_SPECS`(去重 x10/1000 换算)

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py`(`_add_trackbars` 与 `_read_state` 两函数)

**Interfaces:**
- Consumes: Task 1 的 `PARAM_SPECS` / `SPECS`。
- Produces: 行为等价的 `_add_trackbars` / `_read_state`(签名不变),标度换算不再内联。

- [ ] **Step 1: 改 `_add_trackbars` 用 spec** — 保留 `frame`/`ref_frame` 两个导航轨直接创建,其余参数轨改为遍历规格。用初值 calib/params 折出各自然值,经 `spec.to_pos` 定初始位置。替换 `_add_trackbars` 函数体为:

```python
def _add_trackbars(calib: ChannelCalibration, params: WaterLevelDetectParams,
                   n_frames: int, roi_frac: tuple) -> None:
    cv2.namedWindow(CTRL_WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(CTRL_WIN, 460, 640)
    noop = lambda _v: None
    fx, fy, fw, fh = roi_frac

    # 导航轨 (非参数)
    cv2.createTrackbar("frame", CTRL_WIN, 0, max(1, n_frames - 1), noop)
    cv2.createTrackbar("ref_frame", CTRL_WIN, 0, max(1, n_frames - 1), noop)

    # 各参数初值 (自然值) → 经 spec.to_pos 定初始滑块位
    flow_idx = FLOWS.index(calib.flow_direction) if calib.flow_direction in FLOWS else 0
    init = {
        "flow": flow_idx,
        "roi_fx": fx, "roi_fy": fy, "roi_fw": fw, "roi_fh": fh,
        "crop_x": params.roi_crop_x, "crop_y": params.roi_crop_y,
        "blur_ksize": params.blur_ksize,
        "diff_thr": params.diff_threshold,
        "wet_thr": params.wet_pixel_threshold,
        "front_lvl": params.front_ratio_level,
    }
    for s in PARAM_SPECS:
        cv2.createTrackbar(s.trackbar, CTRL_WIN, s.to_pos(init[s.key]), s.track_hi, noop)
```

- [ ] **Step 2: 改 `_read_state` 用 spec** — 读位置经 `spec.from_pos` 还原自然值,再装配 calib/params。替换 `_read_state` 函数体为:

```python
def _read_state(ui):
    """从滑块 + UIState 读回 (calib, params, frame_idx, ref_idx)。旋转角来自画线定角 (ui.angle_deg)。"""
    def val(key):
        s = SPECS[key]
        return s.from_pos(cv2.getTrackbarPos(s.trackbar, CTRL_WIN))
    calib = ChannelCalibration(
        rotation_angle_deg=ui.angle_deg,
        flow_direction=FLOWS[int(val("flow"))],
        roi_frac=(val("roi_fx"), val("roi_fy"), val("roi_fw"), val("roi_fh")),
    )
    params = WaterLevelDetectParams(
        roi_crop_x=val("crop_x"),
        roi_crop_y=val("crop_y"),
        blur_ksize=int(val("blur_ksize")),
        diff_threshold=val("diff_thr"),
        wet_pixel_threshold=val("wet_thr"),
        front_ratio_level=val("front_lvl"),
    )
    g = lambda name: cv2.getTrackbarPos(name, CTRL_WIN)
    return calib, params, g("frame"), g("ref_frame")
```

- [ ] **Step 3: 回归测 + import 冒烟** — 等价性由 Task 1 测试钉死(`eq_*` 用例);再确认模块可导入(无窗口副作用)。

Run: `"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline`
Expected: PASS(`失败 0`)。

Run: `"E:/Anaconda/envs/platformupper/python.exe" -c "import eit_ptlc.tools.wl_replay_tune as m; print('import ok', bool(m.PARAM_SPECS))"`
Expected: `import ok True`

- [ ] **Step 4: 提交**

```bash
git add eit_ptlc/tools/wl_replay_tune.py
git commit -m "refactor(wl-tune): 建轨/读轨路由到 PARAM_SPECS, 去重标度换算 (行为等价)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 终端敲值 REPL(热键 `e`)+ 菜单文案

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py`(新增 `_current_value`/`_apply_value`/`run_edit_repl`;主循环加 `e` 分支;`HELP`、`VIEW_WIN` 标题、模块 docstring 热键表补 `e`)

**Interfaces:**
- Consumes: Task 1 的 `SPECS`/`ROTATION_KEY`/`edit_menu`/`parse_edit_command`;`CTRL_WIN` 上的 trackbar;`ui.angle_deg`。
- Produces:
  - `_current_value(ui, key) -> float`:读当前自然值(rotation 读 `ui.angle_deg`,余读 trackbar 经 `from_pos`)。
  - `_apply_value(ui, key, value) -> float`:clamp 后应用(rotation 写 `ui.angle_deg`,余 `setTrackbarPos`),返回回读值。
  - `run_edit_repl(ui) -> None`:阻塞式模态编辑循环。

- [ ] **Step 1: 写敲值函数** — 在 `_read_state` 之后插入:

```python
def _current_value(ui, key):
    """读某可敲项当前自然值 (rotation 读 ui.angle_deg, 余读 trackbar)。"""
    if key == ROTATION_KEY:
        return round(ui.angle_deg, 2)
    s = SPECS[key]
    return round(s.from_pos(cv2.getTrackbarPos(s.trackbar, CTRL_WIN)), 4)


def _apply_value(ui, key, value):
    """应用敲入的自然值 (clamp → rotation 写 ui.angle_deg / 余回填 trackbar), 返回回读值。"""
    if key == ROTATION_KEY:
        ui.angle_deg = max(-45.0, min(45.0, float(value)))
        return round(ui.angle_deg, 2)
    s = SPECS[key]
    v = max(s.lo, min(s.hi, float(value)))
    cv2.setTrackbarPos(s.trackbar, CTRL_WIN, s.to_pos(v))
    return _current_value(ui, key)


def run_edit_repl(ui) -> None:
    """终端模态敲值: 列可编辑项 → 逐行 '<编号|短名> <值>' → 即时生效并回填滑块。

    空行/'q' 退出。input() 阻塞期间预览窗不刷新 (模态编辑的已知取舍)。
    """
    menu = edit_menu()
    print("\n[整定台] 敲值编辑 (逐行输入; 空行/q 退出):")
    for i, (key, hint) in enumerate(menu):
        print(f"  {i:2d}  {key:12s} = {_current_value(ui, key):<8}  ({hint})")
    while True:
        try:
            line = input("编辑> ")
        except EOFError:
            break
        key, value = parse_edit_command(line)
        if key is None:
            break
        if key == "__error__":
            print(f"  ! {value}")
            continue
        print(f"  {key} → {_apply_value(ui, key, value)}")
```

- [ ] **Step 2: 主循环加 `e` 分支** — 在 `main()` 的按键 `elif` 链里(`elif key == ord("h"):` 之后)插入:

```python
        elif key == ord("e"):
            playing = False
            run_edit_repl(ui)
```

- [ ] **Step 3: 补文案** — 三处补 `e` 敲值提示:

`HELP` 字符串改为:
```python
HELP = """\
[整定台热键]  空格 播放/暂停   ←/a 上一帧   →/d 下一帧   , . 快退/快进10帧
              e 终端敲精确值   r 设当前帧为参考(干板)帧   c 跑整段画 percent(t) 曲线
              w 存当前参数为 <stem>.tuned.json(草稿)   h 本帮助   q/Esc 退出"""
```

`VIEW_WIN` 常量改为(在既有基础上加 `e敲值`):
```python
VIEW_WIN = "preview (热键: 空格播放 e敲值 r参考 c曲线 w存草稿 q退出; 左键拖=画竖直边定角 右键拖=框ROI)"
```

模块顶部 docstring 的"热键"段(第 23-27 行附近)加一行:
```
    e    终端敲精确值 (逐项输入)
```

- [ ] **Step 4: import 冒烟 + 回归** — REPL 本身是 I/O 交互(手动验),此处确认新函数不破坏导入与既有测试。

Run: `"E:/Anaconda/envs/platformupper/python.exe" -c "import eit_ptlc.tools.wl_replay_tune as m; print('repl', callable(m.run_edit_repl), callable(m._apply_value))"`
Expected: `repl True True`

Run: `"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline`
Expected: PASS(`失败 0`)。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/tools/wl_replay_tune.py
git commit -m "feat(wl-tune): 终端敲精确值 REPL (热键 e; rotation 亦可敲)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `W` 并入生产真源(load-merge-save + 确认)+ 离线测

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py`(新增 `commit_to_source`;主循环加 `W` 分支;`HELP`/`VIEW_WIN`/docstring 补 `W`)
- Test: `eit_ptlc/tests/test_waterlevel_tune_offline.py`(追加 commit 用例)

**Interfaces:**
- Consumes: `load_channel_configs`、`save_channel_configs`、`ChannelConfig`(顶部已 import);`ChannelCalibration`。
- Produces: `commit_to_source(calib_json_path, ch, calib, params, confirm) -> bool`。

- [ ] **Step 1: 追加失败测试** — 在测试文件 `_run()` 内、`parse_*` 用例之后、`print(f"\n失败 ...")` 之前插入:

```python
    # ---- commit_to_source load-merge-save ----
    import tempfile
    from pathlib import Path
    from eit_ptlc.controller.waterlevel_detector import ChannelCalibration, WaterLevelDetectParams
    from eit_ptlc.controller.waterlevel_store import (
        ChannelConfig, load_channel_configs, save_channel_configs,
    )
    from eit_ptlc.tools.wl_replay_tune import commit_to_source

    def _cal(rot):
        return ChannelCalibration(rotation_angle_deg=rot, flow_direction="left_to_right",
                                  roi_frac=(0.3, 0.05, 0.2, 0.8))

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "water_level_calib.json"
        save_channel_configs(path, {
            1: ChannelConfig(calib=_cal(1.0), params=WaterLevelDetectParams()),
            2: ChannelConfig(calib=_cal(2.0), params=WaterLevelDetectParams()),
        })

        ok = commit_to_source(path, 5, _cal(5.0), WaterLevelDetectParams(), confirm=lambda: True)
        after = load_channel_configs(path)
        check("commit_add_ch5", ok and set(after.keys()) == {1, 2, 5}, str(sorted(after.keys())))
        check("commit_keep_ch2", after.get(2) is not None
              and abs(after[2].calib.rotation_angle_deg - 2.0) < 1e-6, "")

        ok2 = commit_to_source(path, 1, _cal(9.9), WaterLevelDetectParams(), confirm=lambda: True)
        after2 = load_channel_configs(path)
        check("commit_replace_ch1", ok2 and abs(after2[1].calib.rotation_angle_deg - 9.9) < 1e-6,
              str(after2[1].calib.rotation_angle_deg))
        check("commit_replace_keep_ch2", abs(after2[2].calib.rotation_angle_deg - 2.0) < 1e-6, "")

        # 取消 → 不改
        ok3 = commit_to_source(path, 7, _cal(7.0), WaterLevelDetectParams(), confirm=lambda: False)
        after3 = load_channel_configs(path)
        check("commit_cancel_noop", (ok3 is False) and (7 not in after3), str(sorted(after3.keys())))

        # 未标定 → 拒写
        ok4 = commit_to_source(path, 8, ChannelCalibration(), WaterLevelDetectParams(),
                               confirm=lambda: True)
        after4 = load_channel_configs(path)
        check("commit_uncalibrated_refused", (ok4 is False) and (8 not in after4),
              str(sorted(after4.keys())))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline`
Expected: FAIL — `ImportError: cannot import name 'commit_to_source'`。

- [ ] **Step 3: 写 `commit_to_source`** — 在 `_save_params` 之后插入:

```python
def commit_to_source(calib_json_path, ch, calib, params, confirm) -> bool:
    """把当前通道 calib/params 并入生产真源 config/water_level_calib.json (load-merge-save)。

    只替换该通道, 其余通道原样保留 (save_channel_configs 覆盖写但传入完整 dict)。
    守卫: 无 ROI (not calibrated) 拒写; confirm() 假则中止。返回是否已写。
    """
    if not calib.calibrated:
        print("[整定台] 当前无 ROI (未标定), 拒绝并入真源")
        return False
    existing = load_channel_configs(calib_json_path)
    old = existing.get(int(ch))
    print(f"[整定台] 拟并入 CH{ch} → {calib_json_path}")
    if old is not None:
        print(f"   旧: rot={old.calib.rotation_angle_deg:+.2f} roi_frac={old.calib.roi_frac}")
    else:
        print("   旧: (该通道原不存在)")
    print(f"   新: rot={calib.rotation_angle_deg:+.2f} roi_frac={calib.roi_frac}")
    if not confirm():
        print("[整定台] 已取消, 真源未改")
        return False
    existing[int(ch)] = ChannelConfig(calib=calib, params=params)
    save_channel_configs(calib_json_path, existing)
    print(f"[整定台] CH{ch} 已并入真源, 保留其余 {len(existing) - 1} 通道")
    return True
```

- [ ] **Step 4: 主循环加 `W` 分支** — 在 Task 3 的 `e` 分支之后插入:

```python
        elif key == ord("W"):
            ch = meta.get("channel")
            if ch is None:
                print("[整定台] meta 无 channel, 无法定位真源槽位, 中止")
            else:
                calib_json = Path(__file__).resolve().parents[1] / "config" / "water_level_calib.json"
                commit_to_source(
                    calib_json, int(ch), calib, params,
                    confirm=lambda: input(f"确认并入 CH{ch} 到真源? [y/N] ").strip().lower() == "y",
                )
```

- [ ] **Step 5: 补文案** — `HELP` 加 `W` 行、`VIEW_WIN` 加 `W并入真源`、docstring 热键段加一行:

`HELP` 的 `w` 行改为两行:
```python
              w 存草稿 <stem>.tuned.json   W 并入真源 config/water_level_calib.json(确认)
```
`VIEW_WIN` 改为:
```python
VIEW_WIN = "preview (热键: 空格播放 e敲值 r参考 c曲线 w存草稿 W并入真源 q退出; 左键拖=画竖直边定角 右键拖=框ROI)"
```
docstring 热键段的 `w` 行补一行:
```
    W    并入生产真源 config/water_level_calib.json (load-merge-save + 确认)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline`
Expected: PASS(全部 PASS,`失败 0`)。

- [ ] **Step 7: 提交**

```bash
git add eit_ptlc/tools/wl_replay_tune.py eit_ptlc/tests/test_waterlevel_tune_offline.py
git commit -m "feat(wl-tune): W 并入生产真源 (load-merge-save + 确认, 守卫无ROI/缺channel)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 手动 GUI 运行时校验(收尾, 非自动化)

**Files:** 无(仅人工验证 + 记录)

GUI 交互无法离线自动化,收尾在真机/带录制的环境跑一次冒烟:

- [ ] **Step 1: 启动整定台**

Run: `"E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tools.wl_replay_tune data/water_level_recordings/`
Expected: 预览窗 + 控制窗正常出现,滑块初值与录制 meta 标定一致(等价性未回退)。

- [ ] **Step 2: 验 `e` 敲值** — 按 `e`,终端列出 0=rotation..11 各项当前值;敲 `10 7.5`(diff_thr)→ 回显 `diff_thr → 7.5`,预览左上角 `diff_thr` 文字与滑块同步变 7.5;敲 `0 -3` → 旋转变化;空行退出。

- [ ] **Step 3: 验 `w` / `W`** — 按 `w` 生成 `<stem>.tuned.json`(单通道);按 `W` → 终端打印旧→新摘要 + `确认并入 CHx? [y/N]`,答 `n` 不改、答 `y` 写入 `config/water_level_calib.json` 且其余通道保留(diff 该文件确认只增/改当前通道)。

- [ ] **Step 4: 记录结论** — 把冒烟结果(通过/异常)追加到本 plan 末尾或对应 memory。

---

## Self-Review

**1. Spec coverage:**
- 终端敲值 REPL(spec §2)→ Task 3 ✓;`rotation_deg` 纳入(spec §1 末)→ Task 1 `edit_menu` + Task 3 `_apply_value` ✓
- `PARAM_SPECS` 标度单一真源(spec §1)→ Task 1 定义 + Task 2 路由 ✓
- `w` 不变(spec §3)→ 未触碰 `_save_params` ✓
- `W` load-merge-save + 确认 + 守卫(spec §4)→ Task 4 ✓
- 热键/HELP/标题(spec §5)→ Task 3 Step3 + Task 4 Step5 ✓
- 测试三目标(spec 测试节)→ Task 1(标度往返 + parse)+ Task 4(commit merge)✓
- 错误处理表(spec)→ parse clamp(Task1)、`e` 前 `playing=False`(Task3)、`W` 缺 channel/无 ROI/取消(Task4)✓

**2. Placeholder scan:** 无 TBD/TODO;每个代码步给出完整代码。✓

**3. Type consistency:** `to_pos:Callable[[float],int]`/`from_pos:Callable[[int],float]` 全程一致;`commit_to_source(calib_json_path, ch, calib, params, confirm)` 在 Task 4 定义与主循环调用签名一致;`parse_edit_command` 返回三态 `(key,value)/("__error__",msg)/(None,None)` 在 Task 1 定义与 Task 3 `run_edit_repl` 消费一致;`edit_menu` index 0=rotation 在 Task 1 与 Task 3 `_current_value` 特判一致。✓
