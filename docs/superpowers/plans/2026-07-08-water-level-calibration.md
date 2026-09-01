# 液位标定业务上位机化 + 整定台修缮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把液位"摆正画面 + 框 ROI + 选流向"的标定做成网页正式业务(冻结帧 canvas,画边线定角 + 拖框选 ROI),并修好离线整定台的方向键/卡顿,补齐后端 `roi_frac` 写入。

**Architecture:** 旋转几何由前端 canvas 本地复现(JS 移植 `rotation_matrix`),`roi_frac`(分辨率无关比例)纯数学算出,后端检测用同一矩阵复现 → 像素级一致。摆正用"画竖直参考边 → 算增量角"迭代收敛,非滑块。标定落 `set_calibration{rotation_angle_deg, roi_frac, flow_direction}` 进上位机标定真源 `water_level_calib.json`。

**Tech Stack:** Python 3.11 (conda env `platformupper`)、OpenCV(`cv2`)、NumPy、FastAPI、Vue 3 (`<script setup>`)、Vite。

## Global Constraints

- Python 解释器: `E:/Anaconda/envs/platformupper/python.exe`(conda env `platformupper`, 3.11)。
- 离线测试用**本仓库自研 harness**(非 pytest): 文件放 `eit_ptlc/tests/`,内部 `_run()` + `check(name, cond, detail)` 计数,`main()` 里 `stream.reconfigure(encoding="utf-8")`,`if __name__=="__main__": sys.exit(main())`;运行 `python -m eit_ptlc.tests.<模块名>`,退出码 0=全绿。
- 几何真源: `rotation_matrix` / `roi_pixels` 在 `eit_ptlc/controller/waterlevel_detector.py`;新增几何纯函数放同文件,JS 端只镜像并注释锚定 Python 源。
- 旋转是刚体旋转(`scale=1.0`),正角=逆时针,与 `cv2.getRotationMatrix2D` 一致。
- `roi_frac` 是分辨率无关真源;写入 `roi_frac` 时必须清 `roi_bbox`,避免陈旧像素框优先(与现有 `update_roi` 同纪律)。
- 前端引用文件/代码位置用相对路径;Vue 组件跟随现有 `<script setup>` 风格。
- 不改检测算法核心(`detect_level` 主体)、不动 OrangePi 载荷、不做时序滤波/状态机/mm 绝对标定/排液触发逻辑。
- 提交:本分支 `codex/ui-upper-next`;每个 Task 末尾一次提交,只 `git add` 该 Task 涉及文件(工作树有大量不相关改动,勿 `git add -A`)。

---

## File Structure

- `eit_ptlc/controller/waterlevel_detector.py` — 【改】新增两个几何纯函数 `angle_to_make_line_vertical`、`box_to_roi_frac`(与既有 `rotation_matrix`/`roi_pixels` 同处,几何真源)。
- `eit_ptlc/controller/waterlevel_service.py` — 【改】`update_calibration` 增 `roi_frac` 入参。
- `eit_ptlc/api/water_level_routes.py` — 【改】`set_calibration` 透传 `roi_frac`。
- `eit_ptlc/tools/wl_replay_tune.py` — 【改】方向键(waitKeyEx)+ 按需重渲(WS1);画边线定角 + 拖框选 ROI + 种子 fallback(WS1.5)。
- `eit_ptlc/tests/test_waterlevel_calib_geom_offline.py` — 【新】几何纯函数离线用例。
- `eit_ptlc/tests/test_waterlevel_calib_roi_frac_offline.py` — 【新】`roi_frac` 写入/持久化/路由透传离线用例。
- `eit_ptlc/web/src/api.js` — 【改】简化 `wlStreamUrl`(只留 raw)。
- `eit_ptlc/web/src/components/WaterLevelChannel.vue` — 【改】页签改 `原始`+`标定`,删 `标注`/`调试面板`,`标定` 模式挂 canvas 组件。
- `eit_ptlc/web/src/components/WaterLevelCalibrate.vue` — 【新】冻结帧 canvas 标定交互组件。

Task 顺序:1(后端 roi_frac)→ 2(整定台方向键/卡顿)→ 3(几何纯函数)→ 4(整定台鼠标交互,依赖 3)→ 5(前端模式清理)→ 6(前端标定组件,依赖 1、5,镜像 3)。

---

### Task 1: 后端 `update_calibration` 支持 `roi_frac` + 路由透传

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_service.py`(`update_calibration`,约 229–244 行)
- Modify: `eit_ptlc/api/water_level_routes.py`(`_dispatch_upper_cmd` 的 `set_calibration` 分支,约 67–74 行)
- Test: `eit_ptlc/tests/test_waterlevel_calib_roi_frac_offline.py`(新建)

**Interfaces:**
- Consumes: `WaterLevelDetectService`(现有);`ChannelCalibration.roi_frac`(现有字段,`Optional[tuple[float,float,float,float]]`)。
- Produces: `WaterLevelDetectService.update_calibration(channel, rotation_angle_deg=None, roi_bbox=None, roi_frac=None, flow_direction=None, save=True) -> bool`;路由 `set_calibration` 接受 body 里可选 `roi_frac`(4 元 list)。

- [ ] **Step 1: 写失败测试**

新建 `eit_ptlc/tests/test_waterlevel_calib_roi_frac_offline.py`:

```python
"""液位标定 roi_frac 写入/持久化离线测试
============================================
验证 update_calibration(roi_frac=...) → 设 calib.roi_frac + 清 roi_bbox + 持久化往返一致。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_roi_frac_offline
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from eit_ptlc.controller.waterlevel_detector import ChannelCalibration, WaterLevelDetectParams
from eit_ptlc.controller.waterlevel_service import WaterLevelDetectService
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    load_channel_configs,
    save_channel_configs,
)


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "calib.json"
        # 起始: 通道 3 只有旧像素 bbox
        save_channel_configs(cfg_path, {
            3: ChannelConfig(
                ChannelCalibration(0.0, (50, 50, 200, 100), "left_to_right"),
                WaterLevelDetectParams()),
        })
        svc = WaterLevelDetectService("127.0.0.1", 0, cfg_path)

        # roi_frac 写入: 设 frac + 清 bbox + 存旋转/流向
        ok = svc.update_calibration(
            3, rotation_angle_deg=1.7,
            roi_frac=[0.53, 0.0, 0.20, 1.0], flow_direction="left_to_right")
        c = svc.get_config(3)
        check("returns_true", ok is True, str(ok))
        check("frac_set", c.calib.roi_frac == (0.53, 0.0, 0.20, 1.0), str(c.calib.roi_frac))
        check("bbox_cleared", c.calib.roi_bbox is None, str(c.calib.roi_bbox))
        check("rotation_set", abs(c.calib.rotation_angle_deg - 1.7) < 1e-6, str(c.calib.rotation_angle_deg))
        check("calibrated", c.calib.calibrated, "")

        # 持久化往返一致
        reloaded = load_channel_configs(cfg_path)
        check("frac_persisted", reloaded[3].calib.roi_frac == (0.53, 0.0, 0.20, 1.0),
              str(reloaded[3].calib.roi_frac))
        check("bbox_persisted_none", reloaded[3].calib.roi_bbox is None,
              str(reloaded[3].calib.roi_bbox))

        # 改标定使参考图失效
        svc._refs[3] = "fake_ref"
        svc.update_calibration(3, roi_frac=[0.1, 0.1, 0.2, 0.2])
        check("frac_invalidates_ref", 3 not in svc._refs, str(list(svc._refs.keys())))

    total = 8
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
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

- [ ] **Step 2: 运行确认失败**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_roi_frac_offline`
Expected: FAIL(`update_calibration` 尚不接受 `roi_frac` → `TypeError: unexpected keyword argument 'roi_frac'`)

- [ ] **Step 3: 改 `update_calibration` 支持 `roi_frac`**

`eit_ptlc/controller/waterlevel_service.py`,把现有 `update_calibration` 整体替换为:

```python
    def update_calibration(self, channel: int, rotation_angle_deg=None,
                           roi_bbox=None, roi_frac=None, flow_direction=None,
                           save: bool = True) -> bool:
        cfg = self._configs.get(int(channel))
        if cfg is None:
            return False
        if rotation_angle_deg is not None:
            cfg.calib.rotation_angle_deg = float(rotation_angle_deg)
        # roi_frac 优先 (分辨率无关真源); 设 frac 即清 bbox 避免陈旧优先
        if roi_frac is not None and len(roi_frac) == 4:
            cfg.calib.roi_frac = tuple(float(v) for v in roi_frac)
            cfg.calib.roi_bbox = None
        elif roi_bbox is not None and len(roi_bbox) == 4:
            cfg.calib.roi_bbox = tuple(int(v) for v in roi_bbox)
            cfg.calib.roi_frac = None         # 新像素 ROI → 清旧比例 (同 update_roi)
        if flow_direction in ("left_to_right", "right_to_left", "bottom_to_top"):
            cfg.calib.flow_direction = flow_direction
        self._refs.pop(int(channel), None)   # 标定变 → 参考图失效
        if save:
            self._persist()
        return True
```

- [ ] **Step 4: 运行确认通过**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_roi_frac_offline`
Expected: PASS(`共 8 用例, 失败 0`,退出码 0)

- [ ] **Step 5: 路由 `set_calibration` 透传 `roi_frac`**

`eit_ptlc/api/water_level_routes.py`,把 `set_calibration` 分支替换为:

```python
    if cmd == "set_calibration":
        if ch is None:
            raise HTTPException(400, "set_calibration 需要 channel")
        detect.update_calibration(
            int(ch), rotation_angle_deg=body.get("rotation_angle_deg"),
            roi_bbox=body.get("roi_bbox"), roi_frac=body.get("roi_frac"),
            flow_direction=body.get("flow_direction"),
            save=bool(body.get("save", True)))
        return {"ok": True, "cmd": cmd, "channel": int(ch)}
```

- [ ] **Step 6: 回归 + 提交**

Run(确保既有液位标定写入测试仍绿):
`& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_write_offline`
Expected: PASS(`共 12 用例, 失败 0`)

```bash
git add eit_ptlc/controller/waterlevel_service.py eit_ptlc/api/water_level_routes.py eit_ptlc/tests/test_waterlevel_calib_roi_frac_offline.py
git commit -m "feat(water-level): set_calibration 支持 roi_frac 写入 (分辨率无关标定真源)"
```

---

### Task 2: 整定台方向键(waitKeyEx)+ 按需重渲(WS1,需求3)

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py`(`main` 主循环,约 363–400 行)

**Interfaces:**
- Consumes: 现有 `_read_state()`(返回 `calib, params, fidx, ridx`)、`_render()`、`_FrameSource`。
- Produces: 主循环只在状态变化或播放时 `_render`;方向键经 `cv2.waitKeyEx()` 识别;新增 `a`/`d` 单帧键。

- [ ] **Step 1: 用 waitKeyEx + 状态签名重写主循环**

`eit_ptlc/tools/wl_replay_tune.py`,把 `main()` 里从 `playing = False` 到循环结束(约 361–400 行)替换为:

```python
    playing = False
    last_sig = None          # 上次渲染的状态签名; 未变则不重算 (消卡顿)
    # Windows waitKeyEx 方向键全码 (Linux/GTK 为 81..84, 一并认)
    LEFT = {2424832, 81}
    RIGHT = {2555904, 83}
    while True:
        calib, params, fidx, ridx = _read_state()
        sig = (repr(calib), repr(params), fidx, ridx)
        if playing or sig != last_sig:
            frame = src.get(fidx)
            ref_frame = src.get(ridx)
            if frame is not None:
                canvas, _res = _render(frame, ref_frame, calib, params)
                cv2.imshow(VIEW_WIN, canvas)
            last_sig = sig

        keyfull = cv2.waitKeyEx(30 if playing else 20)
        key = keyfull & 0xFF if keyfull != -1 else 255
        if key in (ord("q"), 27):
            break
        elif key == ord(" "):
            playing = not playing
        elif key == ord("r"):
            cv2.setTrackbarPos("ref_frame", CTRL_WIN, fidx)
            print(f"[整定台] 参考帧 → {fidx}")
        elif key == ord("c"):
            _plot_full_run(avi, calib, params, src.get(ridx))
        elif key == ord("w"):
            _save_params(avi, meta, calib, params)
        elif key == ord("h"):
            print(HELP)
        elif keyfull in LEFT or key == ord("a"):        # ← / a: 上一帧
            cv2.setTrackbarPos("frame", CTRL_WIN, max(0, fidx - 1))
        elif keyfull in RIGHT or key == ord("d"):       # → / d: 下一帧
            cv2.setTrackbarPos("frame", CTRL_WIN, min(src.n - 1, fidx + 1))
        elif key == ord(","):
            cv2.setTrackbarPos("frame", CTRL_WIN, max(0, fidx - 10))
        elif key == ord("."):
            cv2.setTrackbarPos("frame", CTRL_WIN, min(src.n - 1, fidx + 10))

        if playing:
            nxt = fidx + 1
            if nxt >= src.n:
                nxt = 0
            cv2.setTrackbarPos("frame", CTRL_WIN, nxt)

        if cv2.getWindowProperty(VIEW_WIN, cv2.WND_PROP_VISIBLE) < 1:
            break
```

- [ ] **Step 2: 更新热键说明文本**

`eit_ptlc/tools/wl_replay_tune.py`,把 `HELP`(约 333–336 行)替换为:

```python
HELP = """\
[整定台热键]  空格 播放/暂停   ←/a 上一帧   →/d 下一帧   , . 快退/快进10帧
              r 设当前帧为参考(干板)帧   c 跑整段画 percent(t) 曲线
              w 存当前参数为 <stem>.tuned.json   h 本帮助   q/Esc 退出"""
```

- [ ] **Step 3: 冒烟(语法 + 导入)**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -c "import ast; ast.parse(open('eit_ptlc/tools/wl_replay_tune.py',encoding='utf-8').read()); print('OK syntax')"`
Expected: `OK syntax`

- [ ] **Step 4: 人工验证(有 GUI 环境时)**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tools.wl_replay_tune data/water_level_recordings/adhoc/ch5_20260707_125330.avi`
Expected: 焦点在 preview 窗口,按 `←/→`(或 `a/d`)能逐帧走且不卡;空闲时 CPU 不空转(不再每帧重算)。
(无 GUI/远程环境跳过此步,标注 "GUI 待现场验证"。)

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/tools/wl_replay_tune.py
git commit -m "fix(wl-tune): waitKeyEx 修方向键(Windows)+ 按需重渲消卡顿"
```

---

### Task 3: 几何纯函数 `angle_to_make_line_vertical` + `box_to_roi_frac`

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_detector.py`(在 `rotation_matrix` 之后,`extract_roi_gray` 之前新增)
- Test: `eit_ptlc/tests/test_waterlevel_calib_geom_offline.py`(新建)

**Interfaces:**
- Produces:
  - `angle_to_make_line_vertical(dx: float, dy: float) -> float` — 给定线段方向向量(旋转后显示坐标系,y 向下),返回把该线转竖直所需的**增量旋转角**(度,正角=逆时针,与 `cv2.getRotationMatrix2D` 一致),归一到 `(-90, 90]`。
  - `box_to_roi_frac(x, y, w, h, rot_w: int, rot_h: int) -> tuple[float,float,float,float]` — 旋转后画布像素框 → 分辨率无关 `roi_frac`。是 `ChannelCalibration.roi_pixels` 的逆。

- [ ] **Step 1: 写失败测试**

新建 `eit_ptlc/tests/test_waterlevel_calib_geom_offline.py`:

```python
"""液位标定几何纯函数离线测试
============================================
- angle_to_make_line_vertical: 用同一 cv2.getRotationMatrix2D 复核 —— 把返回增量角作用到方向
  向量上, 结果应竖直 (x 分量≈0)。此举把符号约定钉死在 cv2 上。
- box_to_roi_frac: 与 ChannelCalibration.roi_pixels 往返一致。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_geom_offline
"""

from __future__ import annotations

import sys

import cv2

from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    angle_to_make_line_vertical,
    box_to_roi_frac,
)


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # 1) 角度: 作用增量角到方向向量后应竖直 (x≈0)
    for dx, dy in [(10.0, 1.0), (10.0, -1.0), (1.0, 10.0), (-3.0, 20.0), (5.0, 5.0), (-5.0, 5.0)]:
        delta = angle_to_make_line_vertical(dx, dy)
        M = cv2.getRotationMatrix2D((0.0, 0.0), delta, 1.0)
        vx = M[0, 0] * dx + M[0, 1] * dy      # 旋转后向量的 x 分量
        check(f"vertical_dx{dx}_dy{dy}", abs(vx) < 1e-6, f"delta={delta} vx={vx}")

    # 2) 已竖直的线增量角为 0
    check("already_vertical", abs(angle_to_make_line_vertical(0.0, 10.0)) < 1e-9,
          str(angle_to_make_line_vertical(0.0, 10.0)))

    # 3) box_to_roi_frac 与 roi_pixels 往返一致
    rot_w, rot_h = 400, 480
    frac = box_to_roi_frac(200, 0, 80, 249, rot_w, rot_h)
    calib = ChannelCalibration(roi_frac=frac)
    px = calib.roi_pixels(rot_w, rot_h)
    check("roi_roundtrip", px == (200, 0, 80, 249), f"frac={frac} px={px}")

    total = 6 + 1 + 1
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
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

- [ ] **Step 2: 运行确认失败**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_geom_offline`
Expected: FAIL(`ImportError: cannot import name 'angle_to_make_line_vertical'`)

- [ ] **Step 3: 新增两个纯函数**

`eit_ptlc/controller/waterlevel_detector.py`,在 `rotation_matrix` 函数定义之后插入(并确保文件顶部 `import` 段有 `import math`;若无则加):

```python
def angle_to_make_line_vertical(dx: float, dy: float) -> float:
    """给定线段方向向量 (dx, dy)(旋转后显示坐标系, y 向下), 返回把该线转到竖直所需的
    增量旋转角 (度, 正角=逆时针, 与 cv2.getRotationMatrix2D 一致), 归一到 (-90, 90]。

    用途: 网页/整定台"画竖直参考边定角" —— 用户沿硅胶板竖直边点两点, 本函数给出让该边
    竖直的增量角, 累加到当前总角后从原始帧重渲 (角度可迭代逼近)。
    JS 端 (WaterLevelCalibrate.vue) 镜像本实现, 改此处须同步 JS。
    """
    theta = math.degrees(math.atan2(dy, dx))   # 线与 +x 轴夹角
    delta = theta - 90.0                       # 转到竖直所需增量 (符号对齐 cv2: vx=cos(delta)dx+sin(delta)dy=0)
    while delta <= -90.0:
        delta += 180.0
    while delta > 90.0:
        delta -= 180.0
    return delta


def box_to_roi_frac(x, y, w, h, rot_w: int, rot_h: int):
    """旋转后画布像素框 (x, y, w, h) → 分辨率无关 roi_frac (fx, fy, fw, fh)。
    是 ChannelCalibration.roi_pixels 的逆; rot_w/rot_h 为旋转后画布尺寸 (rotation_matrix 第二返回值)。
    """
    rot_w = max(1, int(rot_w))
    rot_h = max(1, int(rot_h))
    return (x / rot_w, y / rot_h, w / rot_w, h / rot_h)
```

- [ ] **Step 4: 运行确认通过**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_geom_offline`
Expected: PASS(`共 8 用例, 失败 0`)

- [ ] **Step 5: 回归检测器现有测试**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_calib_write_offline`
Expected: PASS(`共 12 用例, 失败 0`)

- [ ] **Step 6: 提交**

```bash
git add eit_ptlc/controller/waterlevel_detector.py eit_ptlc/tests/test_waterlevel_calib_geom_offline.py
git commit -m "feat(water-level): 标定几何纯函数 angle_to_make_line_vertical + box_to_roi_frac"
```

---

### Task 4: 整定台鼠标交互(画边线定角 + 拖框 ROI + 种子 fallback)(WS1.5,需求1)

**Files:**
- Modify: `eit_ptlc/tools/wl_replay_tune.py`(`_add_trackbars`、`_read_state`、`_load_initial`、`main`、鼠标回调新增)

**Interfaces:**
- Consumes: Task 3 的 `angle_to_make_line_vertical`、`box_to_roi_frac`;现有 `rotation_matrix`、`load_channel_configs`。
- Produces: 整定台用鼠标画线定角(取代 `rot(x10)+150` 滑块)、鼠标在旋转后画面拖框选 ROI(回填 4 个 `roi_f*` 滑块,双向同步);`_load_initial` 缺 meta 快照时回退读 `config/water_level_calib.json[通道]`。

**说明**:此 Task 把 Task 2 的主循环再改一版(角度改为模块级可变状态,ROI 由鼠标+滑块共同驱动)。渲染仍走 Task 2 的"按需重渲",签名里纳入角度状态。

- [ ] **Step 1: 引入几何函数 + 交互状态**

`eit_ptlc/tools/wl_replay_tune.py` 顶部 import 段,把从 `waterlevel_detector` 的导入改为(增两个函数):

```python
from eit_ptlc.controller.waterlevel_detector import (
    ChannelCalibration,
    WaterLevelDetectParams,
    angle_to_make_line_vertical,
    box_to_roi_frac,
    detect_level,
    extract_roi_gray,
    rotation_matrix,
)
```

在 `FLOWS = [...]` 之后新增一个交互状态容器(模块级,供鼠标回调与主循环共享):

```python
# 交互状态 (鼠标回调 <-> 主循环共享): 旋转总角 + 画线两点 + ROI 拖框
class _UIState:
    def __init__(self, angle_deg: float = 0.0):
        self.angle_deg = float(angle_deg)   # 旋转总角 (画线定角累加, 取代旋转滑块)
        self.line_p0 = None                 # 画线起点 (旋转后画布像素)
        self.line_cur = None                # 画线当前点 (拖动中)
        self.roi_drag0 = None               # ROI 拖框起点
        self.roi_drag_cur = None            # ROI 拖框当前点
        self.left_origin = (0, 0)           # 左图在合成画布中的原点 (恒 0,0)
        self.rot_size = (1, 1)              # 最近一次渲染的旋转后画布尺寸 (rw, rh)
```

- [ ] **Step 2: 去掉旋转滑块,`_read_state` 角度改读 UIState**

`_add_trackbars` 中删除这一行(旋转滑块不再需要,改画线定角):

```python
    cv2.createTrackbar("rot(x10)+150", CTRL_WIN, clamp(calib.rotation_angle_deg * 10 + 150, 0, 300), 300, noop)
```

`_read_state` 改为接受 UIState 提供角度(签名加参数),把 `rotation_angle_deg` 来源换掉:

```python
def _read_state(ui):
    """从滑块 + UIState 读回 (calib, params, frame_idx, ref_idx)。旋转角来自画线定角 (ui.angle_deg)。"""
    g = lambda name: cv2.getTrackbarPos(name, CTRL_WIN)
    calib = ChannelCalibration(
        rotation_angle_deg=ui.angle_deg,
        flow_direction=FLOWS[g("flow 0L>R1R>L2B>T")],
        roi_frac=(g("roi_fx(/1000)") / 1000.0, g("roi_fy(/1000)") / 1000.0,
                  max(1, g("roi_fw(/1000)")) / 1000.0, max(1, g("roi_fh(/1000)")) / 1000.0),
    )
    params = WaterLevelDetectParams(
        roi_crop_x=g("crop_x(%)") / 100.0,
        roi_crop_y=g("crop_y(%)") / 100.0,
        blur_ksize=2 * g("blur(2v+1)") + 1,
        diff_threshold=g("diff_thr(x10)") / 10.0,
        wet_pixel_threshold=g("wet_thr(x10)") / 10.0,
        front_ratio_level=g("front_lvl(%)") / 100.0,
    )
    return calib, params, g("frame"), g("ref_frame")
```

- [ ] **Step 3: 鼠标回调(画线定角 + 拖框 ROI)**

在 `_render` 函数之后新增鼠标回调工厂(用左键拖=画竖直参考边定角;右键拖=框 ROI):

```python
def _make_mouse_cb(ui):
    """preview 窗口鼠标回调: 左键拖=画竖直参考边(松开→定角); 右键拖=框 ROI(松开→回填滑块)。
    坐标为合成画布像素; 左图原点在 (0,0), 故直接就是旋转后画布坐标 (右图在右侧, 忽略)。"""
    def cb(event, x, y, flags, _param):
        rw, rh = ui.rot_size
        inside_left = 0 <= x < rw and 0 <= y < rh
        if event == cv2.EVENT_LBUTTONDOWN and inside_left:
            ui.line_p0 = (x, y); ui.line_cur = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and ui.line_p0 is not None:
            ui.line_cur = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and ui.line_p0 is not None:
            x0, y0 = ui.line_p0
            dx, dy = (x - x0), (y - y0)
            if abs(dx) + abs(dy) >= 5:                       # 忽略误点
                ui.angle_deg += angle_to_make_line_vertical(dx, dy)
                ui.angle_deg = max(-45.0, min(45.0, ui.angle_deg))
                print(f"[整定台] 画线定角 → 总角 {ui.angle_deg:+.2f}°")
            ui.line_p0 = ui.line_cur = None
        elif event == cv2.EVENT_RBUTTONDOWN and inside_left:
            ui.roi_drag0 = (x, y); ui.roi_drag_cur = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and ui.roi_drag0 is not None:
            ui.roi_drag_cur = (x, y)
        elif event == cv2.EVENT_RBUTTONUP and ui.roi_drag0 is not None:
            x0, y0 = ui.roi_drag0
            rx, ry = min(x0, x), min(y0, y)
            rww, rhh = abs(x - x0), abs(y - y0)
            if rww >= 3 and rhh >= 3:
                fx, fy, fw, fh = box_to_roi_frac(rx, ry, rww, rhh, rw, rh)
                cv2.setTrackbarPos("roi_fx(/1000)", CTRL_WIN, max(0, min(999, round(fx * 1000))))
                cv2.setTrackbarPos("roi_fy(/1000)", CTRL_WIN, max(0, min(999, round(fy * 1000))))
                cv2.setTrackbarPos("roi_fw(/1000)", CTRL_WIN, max(1, min(1000, round(fw * 1000))))
                cv2.setTrackbarPos("roi_fh(/1000)", CTRL_WIN, max(1, min(1000, round(fh * 1000))))
                print(f"[整定台] 拖框 ROI → frac ({fx:.3f},{fy:.3f},{fw:.3f},{fh:.3f})")
            ui.roi_drag0 = ui.roi_drag_cur = None
    return cb
```

- [ ] **Step 4: `_render` 记录旋转尺寸 + 叠画交互指引**

`_render` 增参 `ui`(在末尾用它记录旋转后尺寸并叠画线/拖框指引)。把 `_render` 签名与开头改为:

```python
def _render(frame, ref_frame, calib, params, ui=None):
    """构造展示画面: 左=旋转帧带ROI框, 右=ROI湿区掩膜叠加; 附检测结果文字。"""
    h, w = frame.shape[:2]
    M, (rw, rh) = rotation_matrix(calib.rotation_angle_deg, w, h)
    rotated = cv2.warpAffine(frame, M, (rw, rh))
    roi_px = calib.roi_pixels(rw, rh)
    if ui is not None:
        ui.rot_size = (rw, rh)
```

并在函数内 `canvas = np.hstack([left, right])` 之前,给 `left` 叠画一条竖直参考虚线 + 正在画的线/拖框(便于对齐):

```python
    # 竖直参考线 (画面中线) + 交互中的画线/拖框指引
    cv2.line(left, (rw // 2, 0), (rw // 2, rh), (180, 180, 180), 1)
    if ui is not None:
        if ui.line_p0 is not None and ui.line_cur is not None:
            cv2.line(left, ui.line_p0, ui.line_cur, (255, 0, 255), 2)
        if ui.roi_drag0 is not None and ui.roi_drag_cur is not None:
            cv2.rectangle(left, ui.roi_drag0, ui.roi_drag_cur, (0, 128, 255), 1)
```

（上面这段插在 `left` 的 ROI 框绘制之后、`ref_gray = ...` 之前。）

- [ ] **Step 5: `_load_initial` 缺快照回退读标定真源**

`eit_ptlc/tools/wl_replay_tune.py` 顶部 import 段补:

```python
from eit_ptlc.controller.waterlevel_store import (
    ChannelConfig,
    load_channel_configs,
    save_channel_configs,
)
```

在 `_load_initial` 的 `return calib, params, meta` 之前(即"无任何 ROI → 居中兜底"那段**之前**)插入 fallback:

```python
    # meta 快照无标定 → 回退读标定真源 config/water_level_calib.json[通道] (解 CH5-8 看着像没标定)
    if not calib.calibrated:
        ch = meta.get("channel")
        calib_json = Path(__file__).resolve().parents[1] / "config" / "water_level_calib.json"
        if ch is not None and calib_json.is_file():
            cfgs = load_channel_configs(calib_json)
            cc = cfgs.get(int(ch))
            if cc is not None and cc.calib.calibrated:
                calib = cc.calib
                params = cc.params
                log.info("[整定台] meta 无标定, 回退用真源 CH%s 标定", ch)
```

- [ ] **Step 6: `main` 接线 UIState + 鼠标回调 + 更新调用点**

`main()` 中,`_add_trackbars(...)` 之后、`playing = False` 之前插入:

```python
    ui = _UIState(angle_deg=calib0.rotation_angle_deg)
    cv2.setMouseCallback(VIEW_WIN, _make_mouse_cb(ui))
```

并把 Task 2 主循环里的 `_read_state()` 调用改为 `_read_state(ui)`,`_render(frame, ref_frame, calib, params)` 改为 `_render(frame, ref_frame, calib, params, ui)`,状态签名加入角度与拖框:

```python
        calib, params, fidx, ridx = _read_state(ui)
        sig = (repr(calib), repr(params), fidx, ridx,
               ui.line_p0, ui.line_cur, ui.roi_drag0, ui.roi_drag_cur)
```

`_plot_full_run(avi, calib, params, src.get(ridx))` 无需改(calib 已含 ui 角度)。同时更新 `_render` 内部其余调用一致性(该函数其余部分不变)。

更新窗口标题热键提示(可选):`VIEW_WIN` 常量注释补"左键拖=画竖直边定角 右键拖=框ROI"。

- [ ] **Step 7: 冒烟(语法 + 导入)**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -c "import ast; ast.parse(open('eit_ptlc/tools/wl_replay_tune.py',encoding='utf-8').read()); print('OK syntax')"`
Expected: `OK syntax`

Run(导入期无副作用崩溃): `& "E:/Anaconda/envs/platformupper/python.exe" -c "import importlib.util,pathlib; p=pathlib.Path('eit_ptlc/tools/wl_replay_tune.py'); s=importlib.util.spec_from_file_location('t',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('OK import')"`
Expected: `OK import`

- [ ] **Step 8: 人工验证(有 GUI 时)**

Run: `& "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tools.wl_replay_tune data/water_level_recordings/adhoc/ch5_20260707_125330.avi`
Expected: 左键沿硅胶板竖直边拖一条线→松开后画面把该边摆竖直(对齐中线);右键拖→ROI 框更新且 4 个 `roi_f*` 滑块同步回填;`w` 存参得到期望 `roi_frac`。(无 GUI 跳过并标注。)

- [ ] **Step 9: 提交**

```bash
git add eit_ptlc/tools/wl_replay_tune.py
git commit -m "feat(wl-tune): 画竖直边定角 + 右键拖框选ROI(双向同步)+ 缺快照回退读标定真源"
```

---

### Task 5: 前端视频模式清理(原始 + 标定,删标注/调试)(WS3 前半)

**Files:**
- Modify: `eit_ptlc/web/src/api.js`(`wlStreamUrl`,约 218–222 行)
- Modify: `eit_ptlc/web/src/components/WaterLevelChannel.vue`(页签栏 + `mode` + 视频区)

**Interfaces:**
- Produces: `wlStreamUrl(path)` 只回原始流 URL;`WaterLevelChannel` 的视频模式集为 `['live','calibrate']`,`live` 挂 MJPEG `<img>`,`calibrate` 挂 `<WaterLevelCalibrate>`(Task 6 提供,本 Task 先放占位)。

- [ ] **Step 1: 简化 `wlStreamUrl`**

`eit_ptlc/web/src/api.js`,把 `wlStreamUrl` 替换为:

```javascript
// 液位 MJPEG 流 URL (同源, 经 vite 代理到后端再代理香橙派): path=ch1/grid。
// 检测已搬上位机、香橙派 --no-detect ⇒ 无标注/调试叠加, 统一用原始帧流 (?raw=1)。
export function wlStreamUrl(path) {
  return `/api/water_level/stream/${path}?raw=1`
}
```

- [ ] **Step 2: 改 `WaterLevelChannel.vue` 模式集 + 页签**

`eit_ptlc/web/src/components/WaterLevelChannel.vue`:

(a) 顶部注释首行"视频 (标注/原始/调试三态)"改为"视频 (实时/标定两态)"。

(b) `const mode = ref('annotated')` 改为 `const mode = ref('live')`。

(c) `streamSrc` 计算属性去掉 `mode.value`(现在只有实时一种流):

```javascript
const streamSrc = computed(() => (props.online ? wlStreamUrl('ch' + props.channel) : ''))
```

(d) `setMode(m)` 保留;`bumpStream` 保留。

(e) 模板 `.vid-tabs` 三个流按钮替换为两个模式按钮:

```html
      <div class="vid-tabs">
        <button :class="{ active: mode === 'live' }" @click="setMode('live')">实时</button>
        <button :class="{ active: mode === 'calibrate' }" @click="setMode('calibrate')">标定</button>
        <button v-if="mode === 'live'" class="reload" @click="bumpStream" title="重连视频流">⟳</button>
      </div>
```

(f) 模板 `.vid` 区按模式二选一(标定模式挂 Task 6 组件;本 Task 先放占位 div,Task 6 替换):

```html
      <div class="vid">
        <template v-if="mode === 'live'">
          <img v-if="online" :key="streamKey" :src="streamSrc" :alt="'CH' + channel" @error="onStreamError" @load="onStreamLoad" />
          <div v-else class="noimg">设备离线 — 无视频</div>
        </template>
        <div v-else class="noimg">标定面板占位 (Task 6 接入)</div>
      </div>
```

(g) `onMounted` 里开流看门狗仅 `live` 模式需要;把开流那段包一层:

```javascript
onMounted(async () => {
  if (props.online && mode.value === 'live') {
    cmd('stream_start', { channel: props.channel }, '已请求视频流')
    armFirstFrameWatchdog()
  }
  loadParams()
  await pollRecStatus()
  if (recording.value) startRecTimer()
})
```

- [ ] **Step 3: 构建校验(前端能编过)**

Run(在 `eit_ptlc/web`): `cd eit_ptlc/web && npm run build`
Expected: 构建成功,无未使用 `wlStreamUrl` 参数报错、无语法错误。(若本机未装依赖,标注 "前端构建待现场" 并至少肉眼核对模板闭合。)

- [ ] **Step 4: 提交**

```bash
git add eit_ptlc/web/src/api.js eit_ptlc/web/src/components/WaterLevelChannel.vue
git commit -m "refactor(wl-ui): 视频模式收敛为 实时+标定, 删死的 标注/调试 流"
```

---

### Task 6: 网页标定组件 `WaterLevelCalibrate.vue`(WS3 后半,需求2主菜)

**Files:**
- Create: `eit_ptlc/web/src/components/WaterLevelCalibrate.vue`
- Modify: `eit_ptlc/web/src/components/WaterLevelChannel.vue`(用真组件替换 Task 5 占位)

**Interfaces:**
- Consumes: `api.wlCmd`、`wlFrameUrl`(`eit_ptlc/web/src/api.js` 现有导出);后端 `set_calibration{rotation_angle_deg, roi_frac, flow_direction, save}`(Task 1)、`capture_reference`。
- 镜像 Task 3 的 `angle_to_make_line_vertical`(JS 版)与 `rotation_matrix`(JS 版),注释锚定 Python 源。
- Produces: `<WaterLevelCalibrate :channel :online />` 组件。

- [ ] **Step 1: 新建标定组件**

新建 `eit_ptlc/web/src/components/WaterLevelCalibrate.vue`:

```vue
<script setup>
// 液位单通道可视标定 (冻结帧): 画竖直参考边定角 → 摆正; 拖框选 ROI(+roi_frac 数值双向同步);
// 选流向; 采参考图; 保存标定。旋转几何镜像上位机 waterlevel_detector.rotation_matrix /
// angle_to_make_line_vertical (改 Python 侧须同步此处), roi_frac 纯数学 → 后端同式复现, 像素级一致。
import { onMounted, reactive, ref, computed, nextTick } from 'vue'
import { api, wlFrameUrl, errText } from '../api'

const props = defineProps({
  channel: { type: Number, required: true },
  online: { type: Boolean, default: false },
})

const canvas = ref(null)          // 展示画布 (旋转后)
const rawImg = ref(null)          // 冻结的原始帧 (Image 元素)
const angle = ref(0)              // 旋转总角 (度)
const flow = ref('left_to_right')
const roiFrac = reactive({ fx: 0.30, fy: 0.05, fw: 0.20, fh: 0.80 })
const msg = ref('')
const rotSize = reactive({ w: 1, h: 1 })   // 旋转后画布尺寸
const FLOWS = ['left_to_right', 'right_to_left', 'bottom_to_top']

// 交互态
let lineP0 = null                 // 画线起点 (画布像素)
let lineCur = null
let roiDrag0 = null
let roiDragCur = null

// --- 几何: 镜像 Python rotation_matrix(scale=1) ---
function rotationMatrix(angleDeg, w, h) {
  const a = (angleDeg * Math.PI) / 180
  const cos = Math.cos(a), sin = Math.sin(a)
  const cosA = Math.abs(cos), sinA = Math.abs(sin)
  const newW = Math.round(h * sinA + w * cosA)
  const newH = Math.round(h * cosA + w * sinA)
  const cx = w / 2, cy = h / 2
  // cv2.getRotationMatrix2D(center, angle, 1): [[cos,sin,(1-cos)cx-sin*cy],[-sin,cos,sin*cx+(1-cos)cy]]
  let m02 = (1 - cos) * cx - sin * cy
  let m12 = sin * cx + (1 - cos) * cy
  m02 += newW / 2 - cx
  m12 += newH / 2 - cy
  return { m00: cos, m01: sin, m02, m10: -sin, m11: cos, m12, newW, newH }
}

// 镜像 Python angle_to_make_line_vertical
function angleToMakeLineVertical(dx, dy) {
  const theta = (Math.atan2(dy, dx) * 180) / Math.PI
  let delta = theta - 90   // 符号对齐 cv2.getRotationMatrix2D (与 Python angle_to_make_line_vertical 一致)
  while (delta <= -90) delta += 180
  while (delta > 90) delta -= 180
  return delta
}

function draw() {
  const cvs = canvas.value
  const img = rawImg.value
  if (!cvs || !img) return
  const R = rotationMatrix(angle.value, img.naturalWidth, img.naturalHeight)
  rotSize.w = R.newW; rotSize.h = R.newH
  cvs.width = R.newW; cvs.height = R.newH
  const ctx = cvs.getContext('2d')
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.clearRect(0, 0, R.newW, R.newH)
  // canvas.setTransform(a,b,c,d,e,f) = [[a,c,e],[b,d,f]] ← 对应 cv2 M
  ctx.setTransform(R.m00, R.m10, R.m01, R.m11, R.m02, R.m12)
  ctx.drawImage(img, 0, 0)
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  // 竖直参考线 (中线)
  ctx.strokeStyle = 'rgba(180,180,180,0.8)'; ctx.lineWidth = 1
  ctx.beginPath(); ctx.moveTo(R.newW / 2, 0); ctx.lineTo(R.newW / 2, R.newH); ctx.stroke()
  // ROI 框 (绿)
  ctx.strokeStyle = '#22c55e'; ctx.lineWidth = 2
  ctx.strokeRect(roiFrac.fx * R.newW, roiFrac.fy * R.newH, roiFrac.fw * R.newW, roiFrac.fh * R.newH)
  // 交互中的画线 / 拖框
  if (lineP0 && lineCur) {
    ctx.strokeStyle = '#d946ef'; ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(lineP0.x, lineP0.y); ctx.lineTo(lineCur.x, lineCur.y); ctx.stroke()
  }
  if (roiDrag0 && roiDragCur) {
    ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 1
    ctx.strokeRect(Math.min(roiDrag0.x, roiDragCur.x), Math.min(roiDrag0.y, roiDragCur.y),
      Math.abs(roiDragCur.x - roiDrag0.x), Math.abs(roiDragCur.y - roiDrag0.y))
  }
}

function evtPos(e) {
  const r = canvas.value.getBoundingClientRect()
  // 画布 CSS 尺寸可能被缩放 → 换算回画布像素
  const sx = canvas.value.width / r.width, sy = canvas.value.height / r.height
  return { x: (e.clientX - r.left) * sx, y: (e.clientY - r.top) * sy }
}

function onDown(e) {
  const p = evtPos(e)
  if (e.button === 2) { roiDrag0 = p; roiDragCur = p }   // 右键 = 拖 ROI
  else { lineP0 = p; lineCur = p }                        // 左键 = 画竖直边
}
function onMove(e) {
  if (!lineP0 && !roiDrag0) return
  const p = evtPos(e)
  if (roiDrag0) roiDragCur = p; else lineCur = p
  draw()
}
function onUp() {
  if (lineP0 && lineCur) {
    const dx = lineCur.x - lineP0.x, dy = lineCur.y - lineP0.y
    if (Math.abs(dx) + Math.abs(dy) >= 5) {
      angle.value = Math.max(-45, Math.min(45, angle.value + angleToMakeLineVertical(dx, dy)))
    }
    lineP0 = lineCur = null
  }
  if (roiDrag0 && roiDragCur) {
    const x = Math.min(roiDrag0.x, roiDragCur.x), y = Math.min(roiDrag0.y, roiDragCur.y)
    const w = Math.abs(roiDragCur.x - roiDrag0.x), h = Math.abs(roiDragCur.y - roiDrag0.y)
    if (w >= 3 && h >= 3) {
      roiFrac.fx = +(x / rotSize.w).toFixed(4); roiFrac.fy = +(y / rotSize.h).toFixed(4)
      roiFrac.fw = +(w / rotSize.w).toFixed(4); roiFrac.fh = +(h / rotSize.h).toFixed(4)
    }
    roiDrag0 = roiDragCur = null
  }
  draw()
}

function freezeFrame() {
  msg.value = '取帧中…'
  const img = new Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => { rawImg.value = img; msg.value = ''; nextTick(draw) }
  img.onerror = () => { msg.value = '取帧失败 (通道未激活/离线)' }
  // 加时间戳绕缓存, 拉一张最新原始帧
  img.src = wlFrameUrl('ch' + props.channel) + '?t=' + Date.now()
}

async function save() {
  msg.value = ''
  try {
    await api.wlCmd('set_calibration', {
      channel: props.channel,
      rotation_angle_deg: +angle.value.toFixed(3),
      roi_frac: [roiFrac.fx, roiFrac.fy, roiFrac.fw, roiFrac.fh],
      flow_direction: flow.value,
      save: true,
    })
    msg.value = '标定已保存 ✓'
  } catch (e) { msg.value = '保存失败: ' + errText(e) }
}

async function captureRef() {
  msg.value = ''
  try {
    await api.wlCmd('capture_reference', { channel: props.channel })
    msg.value = '已采集参考干板图 ✓'
  } catch (e) { msg.value = '采参考失败: ' + errText(e) }
}

function onRoiInput() { draw() }   // 数值改动 → 重绘框 (数值↔框双向)

onMounted(() => { if (props.online) freezeFrame() })
</script>

<template>
  <div class="calib">
    <div class="calib-canvas-wrap"
         @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @contextmenu.prevent>
      <canvas ref="canvas" class="calib-canvas"></canvas>
      <div v-if="!rawImg" class="calib-empty">{{ online ? '点「重新取帧」拉一张冻结帧' : '设备离线' }}</div>
    </div>
    <div class="calib-ctrl">
      <div class="row">
        <button @click="freezeFrame" :disabled="!online">重新取帧</button>
        <span class="hint">左键拖=沿硅胶板竖直边画线摆正 · 右键拖=框 ROI</span>
      </div>
      <div class="row"><label>旋转角</label><span class="mono">{{ angle.toFixed(2) }}°</span>
        <button class="mini" @click="angle = 0; draw()">归零</button></div>
      <div class="row"><label>流向</label>
        <select v-model="flow">
          <option v-for="f in FLOWS" :key="f" :value="f">{{ f }}</option>
        </select>
      </div>
      <div class="row roi">
        <label>fx<input type="number" step="0.001" v-model.number="roiFrac.fx" @input="onRoiInput" /></label>
        <label>fy<input type="number" step="0.001" v-model.number="roiFrac.fy" @input="onRoiInput" /></label>
        <label>fw<input type="number" step="0.001" v-model.number="roiFrac.fw" @input="onRoiInput" /></label>
        <label>fh<input type="number" step="0.001" v-model.number="roiFrac.fh" @input="onRoiInput" /></label>
      </div>
      <div class="row">
        <button class="primary" @click="save" :disabled="!online">保存标定</button>
        <button @click="captureRef" :disabled="!online">采集参考图</button>
      </div>
      <p v-if="msg" class="msg">{{ msg }}</p>
      <p class="muted">roi_frac 为分辨率无关比例, 跨通道可直接抄同值 (为将来统一液位阈值触发打一致性地基)。</p>
    </div>
  </div>
</template>

<style scoped>
.calib { display: grid; grid-template-columns: 1fr; gap: 10px; }
.calib-canvas-wrap { position: relative; background: #0b0f14; border-radius: 6px; display: flex; align-items: center; justify-content: center; min-height: 240px; }
.calib-canvas { max-width: 100%; max-height: 60vh; cursor: crosshair; }
.calib-empty { position: absolute; color: #cbd5e1; font-size: 13px; }
.calib-ctrl { display: flex; flex-direction: column; gap: 8px; }
.calib-ctrl .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.calib-ctrl label { font-size: 12px; color: var(--subtle); font-weight: 600; }
.calib-ctrl .roi label { display: inline-flex; flex-direction: column; }
.calib-ctrl .roi input { width: 72px; }
.calib-ctrl button { padding: 4px 12px; border: 1px solid var(--border); background: var(--surface-2); cursor: pointer; border-radius: 4px; }
.calib-ctrl button.primary { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
.calib-ctrl button.mini { padding: 2px 8px; font-size: 12px; }
.calib-ctrl button:disabled { opacity: .5; cursor: not-allowed; }
.hint { font-size: 12px; color: var(--muted); }
.mono { font-family: var(--font-mono); }
.msg { font-family: var(--font-mono); font-size: 12px; color: var(--accent); }
.muted { color: var(--muted); font-size: 12px; }
</style>
```

- [ ] **Step 2: 在 `WaterLevelChannel.vue` 接入真组件**

`eit_ptlc/web/src/components/WaterLevelChannel.vue`:

(a) `<script setup>` import 段加:

```javascript
import WaterLevelCalibrate from './WaterLevelCalibrate.vue'
```

(b) 把 Task 5 的标定占位 `<div v-else class="noimg">标定面板占位 (Task 6 接入)</div>` 替换为:

```html
        <WaterLevelCalibrate v-else :channel="channel" :online="online" />
```

- [ ] **Step 3: 构建校验**

Run(在 `eit_ptlc/web`): `cd eit_ptlc/web && npm run build`
Expected: 构建成功。(未装依赖则标注 "前端构建待现场",并肉眼核对 `<script setup>`/模板闭合与 import 路径。)

- [ ] **Step 4: 人工验证(需实机在线)**

进入某展缸单路视图 → 点「标定」页签:
- 「重新取帧」出现冻结原始帧;
- 左键沿硅胶板竖直边拖线 → 松开后画面把该边摆到与中线平行(竖直);
- 右键拖 → 绿色 ROI 框更新,fx/fy/fw/fh 数值同步;改数值 → 框同步;
- 选流向 → 「保存标定」提示成功 → `water_level_calib.json[通道]` 出现 `rotation_angle_deg`+`roi_frac`;
- 「采集参考图」提示成功;回「实时」看该通道 percent 读数随前沿推进合理。
(无实机则标注 "实机待验证"。)

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/web/src/components/WaterLevelCalibrate.vue eit_ptlc/web/src/components/WaterLevelChannel.vue
git commit -m "feat(wl-ui): 网页可视标定(冻结帧画边定角+拖框选ROI+roi_frac双向)接入标定页签"
```

---

## Self-Review

**1. Spec coverage:**
- §1 附带澄清(px-mm)→ 文档已答,无代码任务(正确,YAGNI)。✅
- §2 领域模型订正 → 体现在 UI 竖直参考线 + 画竖直边定角(Task 4/6)。✅
- §3 删标注/调试 → Task 5。✅
- §4.1 前端 canvas 旋转 → Task 6 `rotationMatrix`。✅
- §4.2 画边线定角 → Task 3(纯函数)+ Task 4(整定台)+ Task 6(网页)。✅
- §4.3 拖框 + 数值 `roi_frac` 双向 → Task 4(整定台滑块同步)+ Task 6(数值输入同步)。✅
- WS1 方向键/卡顿 → Task 2。✅
- WS1.5 种子 fallback → Task 4 Step 5。✅
- WS2 后端 `roi_frac` → Task 1。✅
- WS3 → Task 5 + Task 6。✅
- §8 几何 round-trip 测试 → Task 3。✅

**2. Placeholder scan:** 无 TBD/TODO;每个代码步给出完整代码;测试给出完整用例。Task 5 的"标定占位"是**有意的中间态**,Task 6 Step 2 明确替换。✅

**3. Type consistency:**
- `update_calibration(..., roi_frac=None, ...)`(Task 1)= 路由透传(Task 1 Step 5)= 前端 `roi_frac` 数组(Task 6 `save`)。✅
- `angle_to_make_line_vertical(dx, dy)`、`box_to_roi_frac(x,y,w,h,rot_w,rot_h)`(Task 3)在 Task 4 导入使用;JS 镜像 `angleToMakeLineVertical`/`rotationMatrix`(Task 6)。✅
- `wlStreamUrl(path)` 单参(Task 5)= `WaterLevelChannel` `streamSrc` 调用(Task 5 Step 2c)。✅
- `_read_state(ui)` 新签名(Task 4 Step 2)= 主循环调用(Task 4 Step 6)。✅

无遗漏,无签名冲突。

---

## 备注(实施者须知)

- **范围纪律**: `WaterLevelChannel.vue` 右侧现有"数值 ROI (bbox)"区、检测参数滑块、设备命令、录制区**本轮不动**(仍走 `set_roi`/`set_detect_param`)。标定改走 `roi_frac`,两条 ROI 路径暂共存;若后续要统一到 `roi_frac`、删旧 bbox 区,另开任务(超出本 spec)。
- **JS/Python 几何双实现**是已知取舍(spec §10):`WaterLevelCalibrate.vue` 的 `rotationMatrix`/`angleToMakeLineVertical` 改动须同步 `waterlevel_detector.py`;Task 3 的 round-trip 测试 + Task 6 Step 4 人工核对是兜底。
- 无 GUI/无前端依赖/无实机的步骤按提示"标注待现场",不阻塞其余 Task。
