# 大恒观板相机拍照后/退出时资源释放 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `daheng_capture` 每次拍完把相机留成连续采集中性态,并让上位机菜单式退出优雅关停后端,从根上消除 GxViewer 观板相机 0fps 且保证退出时相机/UV 被干净释放。

**Architecture:** 两个独立组件。组件 A 在 `capture()` 最外层 finally best-effort 复位 `TriggerMode=Off`(相机侧寄存器态)。组件 C 在 launcher 停止后端时先投递 CTRL_BREAK 触发 uvicorn 优雅关(跑 lifespan 收尾 + 在飞拍照 finally),超时再 `taskkill /F` 兜底。相机模型维持 Option A“按需拍照”,不引入常开句柄。

**Tech Stack:** Python 3.10+, gxipy(大恒 SDK), pytest, uvicorn/FastAPI, Windows ctypes(kernel32 控制台信号)。

**设计依据:** `docs/superpowers/specs/2026-07-10-daheng-camera-release-on-exit-design.md`

## Global Constraints

- Python `>=3.10`。测试从**仓库根目录**运行:`python -m pytest ...`;若 `python` 不在 PATH,用 `C:/ProgramData/miniforge3/python.exe -m pytest ...`。
- 平台为 Windows;组件 C 用 `ctypes.windll.kernel32`,仅在 Windows 生效(本项目上位机即 Windows)。
- 仅提交每个 Task 明确列出的文件;**不要 `git add -A`**——工作区有大量无关未提交改动,勿裹挟。
- 保持既有代码风格:中文注释/日志,沿用现有函数与命名。
- 相机模型维持 Option A(每次 `capture()` open→抓 1 帧→close),**不引入常开句柄 / 实时预览**。
- best-effort 复位/优雅关停必须**永不阻断**既有的 `close_device()` / `taskkill` 兜底路径。

---

### Task 1: 组件 A — capture() finally 复位 TriggerMode=Off

**Files:**
- Modify: `eit_ptlc/driver/daheng_capture.py`(`try:` 前加 `remote = None`;最外层 finally 加复位块)
- Test: `eit_ptlc/tests/test_camera_safety.py`(追加 3 个测试)

**Interfaces:**
- Consumes: 现有测试夹具 `_install_fake_camera`, `_safe_params`, `_work_path`, `_DataStream`(均已在 `test_camera_safety.py` 中)。
- Produces: 无后续 Task 依赖(独立组件)。行为契约:`capture()` 返回/抛出后,相机 `TriggerMode` 已被置 `Off`(只要 `remote` 曾成功取得)。

- [ ] **Step 1: 写失败测试(追加到 `test_camera_safety.py` 末尾)**

```python
def test_trigger_mode_reset_off_on_success(monkeypatch):
    camera = _install_fake_camera(monkeypatch)

    dc.capture(_work_path("reset-ok.jpg"), _safe_params())

    trigger_vals = [v for (n, v, *_) in camera.remote.events if n == "TriggerMode"]
    assert trigger_vals, "应至少配置过一次 TriggerMode"
    assert trigger_vals[-1] == "Off", "拍完必须把相机留在连续采集态 (TriggerMode=Off)"


@pytest.mark.parametrize(
    "data_stream",
    [
        _DataStream(return_none=True),
        _DataStream(raise_error=True),
    ],
)
def test_trigger_mode_reset_off_even_on_get_image_failure(monkeypatch, data_stream):
    camera = _install_fake_camera(monkeypatch, data_stream=data_stream)

    with pytest.raises(RuntimeError):
        dc.capture(_work_path("reset-fail.jpg"), _safe_params())

    trigger_vals = [v for (n, v, *_) in camera.remote.events if n == "TriggerMode"]
    assert trigger_vals[-1] == "Off", "拍照失败路径也必须复位 TriggerMode=Off"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest eit_ptlc/tests/test_camera_safety.py -k trigger_mode_reset -v`
Expected: 3 项全 FAIL,报 `AssertionError: 拍完必须把相机留在连续采集态` —— 当前 finally 不复位,最后一次 TriggerMode 事件是 `"On"`。

- [ ] **Step 3: 实现——`try:` 前加 `remote = None`**

在 `daheng_capture.py` 中,把(现约 476-478 行):

```python
    try:
        remote = cam.get_remote_device_feature_control()
```

改为:

```python
    remote = None
    try:
        remote = cam.get_remote_device_feature_control()
```

- [ ] **Step 4: 实现——最外层 finally 插复位块**

把最外层 finally(现约 667-679 行):

```python
        if safety_timer is not None and timing_info.get("line1_close_ok"):
            safety_timer.cancel()
        cam.close_device()
        log.info("相机已断开")
```

改为:

```python
        if safety_timer is not None and timing_info.get("line1_close_ok"):
            safety_timer.cancel()
        # 复位触发模式: 把相机留成连续采集态, 供下一个消费者(GxViewer/下次拍照)直接取流。
        # 否则相机停在软触发 On 态, 别的软件"开始采集"会 0 帧/0 带宽(等一个永不到来的触发)。
        if remote is not None:
            try:
                remote.get_enum_feature("TriggerMode").set("Off")
                log.info("触发模式已复位: Off（连续采集）")
            except Exception:
                log.warning("复位 TriggerMode=Off 失败", exc_info=True)
        cam.close_device()
        log.info("相机已断开")
```

- [ ] **Step 5: 运行新测试确认通过**

Run: `python -m pytest eit_ptlc/tests/test_camera_safety.py -k trigger_mode_reset -v`
Expected: 3 项全 PASS。

- [ ] **Step 6: 运行整份相机安全套件确认无回归**

Run: `python -m pytest eit_ptlc/tests/test_camera_safety.py -v`
Expected: 全部 PASS(原有 `test_capture_sends_software_trigger_and_returns_timing` 等不受影响——finally 仅多追加一个 TriggerMode 事件,无既有断言计数事件)。

- [ ] **Step 7: 提交**

```bash
git add eit_ptlc/driver/daheng_capture.py eit_ptlc/tests/test_camera_safety.py
git commit -m "fix(camera): capture() 结束复位 TriggerMode=Off 留连续采集态 (根治 GxViewer 0fps)

组件A: capture() 最外层 finally best-effort 把相机 TriggerMode 复位 Off,
使每次拍完(成功/异常)相机都留成连续采集+已关闭的中性态; try 前置 remote=None
防 get_remote_device_feature_control 抛错时 finally NameError. 扩 test_camera_safety
断言成功+两条取图失败路径下最后一次 TriggerMode 事件均为 Off.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 组件 C-1 — `_graceful_stop_backend` 优雅关停 helper

**Files:**
- Modify: `eit_ptlc/main.py`(在 `_terminate_tree` 之后新增 `_graceful_stop_backend`)
- Test: `eit_ptlc/tests/test_launcher_graceful_stop.py`(新建)

**Interfaces:**
- Consumes: `eit_ptlc.main` 的模块级 `subprocess` / `sys`。
- Produces: `_graceful_stop_backend(proc, *, break_timeout: float = 5.0, wait_timeout: float = 8.0) -> bool` —— 返回 True 表示后端已(优雅)退出;False 表示超时/失败,调用方应 `taskkill` 兜底。Task 3 依赖此签名。

- [ ] **Step 1: 写失败测试(新建 `eit_ptlc/tests/test_launcher_graceful_stop.py`)**

```python
"""launcher 优雅关停后端的离线单测。

只验证 _graceful_stop_backend 的回退/短路逻辑与 _stop_all 的路由:
mock 掉真正投递 CTRL_BREAK 的 subprocess.run 与假 proc,不起真进程。
跨控制台 CTRL_BREAK 的真实投递靠真机手测 (见实施计划 Task 4)。
"""

from __future__ import annotations

import subprocess

import eit_ptlc.main as m


class _FakeProc:
    def __init__(self, *, poll_val, wait_raises=False, pid=54321):
        self._poll = poll_val
        self._wait_raises = wait_raises
        self.pid = pid

    def poll(self):
        return self._poll

    def wait(self, timeout=None):
        if self._wait_raises:
            raise subprocess.TimeoutExpired(cmd="uvicorn", timeout=timeout)
        return 0


def test_graceful_stop_returns_true_when_backend_exits(monkeypatch):
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: None)
    assert m._graceful_stop_backend(_FakeProc(poll_val=None)) is True


def test_graceful_stop_returns_false_on_wait_timeout(monkeypatch):
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: None)
    assert m._graceful_stop_backend(_FakeProc(poll_val=None, wait_raises=True)) is False


def test_graceful_stop_short_circuits_when_already_dead(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("已退出的后端不应再投递 CTRL_BREAK")

    monkeypatch.setattr(m.subprocess, "run", _boom)
    assert m._graceful_stop_backend(_FakeProc(poll_val=0)) is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest eit_ptlc/tests/test_launcher_graceful_stop.py -v`
Expected: FAIL,报 `AttributeError: module 'eit_ptlc.main' has no attribute '_graceful_stop_backend'`。

- [ ] **Step 3: 实现 helper(在 `main.py` 的 `_terminate_tree` 之后插入)**

```python
def _graceful_stop_backend(
    proc: subprocess.Popen, *, break_timeout: float = 5.0, wait_timeout: float = 8.0,
) -> bool:
    """功能: 优雅关停独立控制台里的后端 uvicorn, 让其跑完 lifespan 收尾。

    机制: uvicorn 在 Windows 默认捕获 SIGBREAK → should_exit → lifespan shutdown
    (含 PLC 断开 / 机器人 close / 在飞拍照 finally 关 UV+复位相机 / run_store 关闭)。
    后端在 CREATE_NEW_CONSOLE 独立控制台, 故用一次性 helper 子进程 FreeConsole →
    AttachConsole(后端) → GenerateConsoleCtrlEvent(CTRL_BREAK, 组0) 广播, 避免扰动
    launcher 自身控制台/交互菜单。

    参数:
        proc: 后端子进程
        break_timeout: 投递 helper 的最长等待 (秒)
        wait_timeout: 投递后等后端优雅退出的最长等待 (秒)
    返回:
        bool, 后端已(优雅)退出为 True; 超时/失败为 False (调用方 taskkill 兜底)
    """
    if proc.poll() is not None:
        return True
    log.info("[后端] 优雅关停: 投递 CTRL_BREAK 并等待 lifespan 收尾 ...")
    try:
        subprocess.run(
            [sys.executable, "-c",
             "import ctypes,sys;k=ctypes.windll.kernel32;"
             "k.FreeConsole();k.AttachConsole(int(sys.argv[1]));"
             "k.GenerateConsoleCtrlEvent(1,0)",   # 1=CTRL_BREAK_EVENT, 0=该控制台全部
             str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=break_timeout, check=False,
        )
        proc.wait(timeout=wait_timeout)
        return True
    except (subprocess.TimeoutExpired, OSError):
        log.warning("[后端] 优雅关停超时/失败, 回退强杀")
        return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest eit_ptlc/tests/test_launcher_graceful_stop.py -v`
Expected: 3 项全 PASS。

- [ ] **Step 5: 提交**

```bash
git add eit_ptlc/main.py eit_ptlc/tests/test_launcher_graceful_stop.py
git commit -m "feat(launcher): _graceful_stop_backend 优雅关停后端 (CTRL_BREAK helper + 超时回退)

组件C-1: 用一次性 helper 子进程 AttachConsole 到后端独立控制台再广播 CTRL_BREAK,
触发 uvicorn(Windows 默认捕获 SIGBREAK) 跑 lifespan 收尾优雅退出; 投递失败/等待
超时返回 False 由调用方 taskkill 兜底. 离线单测覆盖 exit/timeout/已退出三分支.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 组件 C-2 — `_stop_all` 后端走优雅、其余强杀

**Files:**
- Modify: `eit_ptlc/main.py`(`_stop_all` 路由后端到 `_graceful_stop_backend`)
- Test: `eit_ptlc/tests/test_launcher_graceful_stop.py`(追加 2 个路由测试)

**Interfaces:**
- Consumes: `_graceful_stop_backend`(Task 2)、`_terminate_tree`(现有)。后端子进程在 `procs` 中登记名为 `"后端"`(见 `_start_all` 的 `procs["后端"] = _start_backend(...)`)。
- Produces: 无后续 Task 依赖。

- [ ] **Step 1: 写失败测试(追加到 `test_launcher_graceful_stop.py` 末尾)**

```python
def test_stop_all_backend_graceful_others_forced(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "_graceful_stop_backend", lambda proc: seen.append("graceful-backend") or True)
    monkeypatch.setattr(m, "_terminate_tree", lambda name, proc: seen.append(f"terminate-{name}"))

    procs = {"PALLASBridge": object(), "后端": object(), "前端": object()}
    m._stop_all(procs)

    assert "graceful-backend" in seen
    assert "terminate-PALLASBridge" in seen
    assert "terminate-前端" in seen
    assert "terminate-后端" not in seen   # 后端优雅退出成功, 不再强杀
    assert procs == {}


def test_stop_all_backend_falls_back_to_force_when_graceful_fails(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "_graceful_stop_backend", lambda proc: seen.append("graceful-fail") or False)
    monkeypatch.setattr(m, "_terminate_tree", lambda name, proc: seen.append(f"terminate-{name}"))

    procs = {"后端": object()}
    m._stop_all(procs)

    assert seen == ["graceful-fail", "terminate-后端"]   # 优雅失败 → 强杀兜底
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest eit_ptlc/tests/test_launcher_graceful_stop.py -k stop_all -v`
Expected: FAIL —— 现 `_stop_all` 对所有进程(含后端)只调 `_terminate_tree`,`seen` 不含 `"graceful-backend"`,断言失败。

- [ ] **Step 3: 实现——改 `_stop_all` 路由**

把 `_stop_all`(现约 345-356 行):

```python
def _stop_all(procs: dict[str, subprocess.Popen]) -> None:
    """功能: 终止已登记的全部子进程树并清空登记表 (幂等).

    参数:
        procs: 名称 → 子进程 的登记表
    """
    if not procs:
        return
    for name, proc in list(procs.items()):
        _terminate_tree(name, proc)
    procs.clear()
    log.info("已停止 Bridge/前后端")
```

改为:

```python
def _stop_all(procs: dict[str, subprocess.Popen]) -> None:
    """功能: 终止已登记的全部子进程树并清空登记表 (幂等).

    后端优先优雅关停 (跑 lifespan 收尾 + 在飞拍照 finally 释放相机/关 UV), 超时/失败
    再强杀兜底; PALLASBridge / 前端无关键收尾, 直接强杀。

    参数:
        procs: 名称 → 子进程 的登记表
    """
    if not procs:
        return
    for name, proc in list(procs.items()):
        if name == "后端":
            if _graceful_stop_backend(proc):
                log.info("[后端] 已优雅退出 (lifespan 收尾完成)")
                continue
            log.warning("[后端] 优雅退出未完成, 强制终止")
        _terminate_tree(name, proc)
    procs.clear()
    log.info("已停止 Bridge/前后端")
```

- [ ] **Step 4: 运行路由测试确认通过**

Run: `python -m pytest eit_ptlc/tests/test_launcher_graceful_stop.py -k stop_all -v`
Expected: 2 项 PASS。

- [ ] **Step 5: 运行整份 launcher 套件确认无回归**

Run: `python -m pytest eit_ptlc/tests/test_launcher_graceful_stop.py -v`
Expected: 5 项全 PASS。

- [ ] **Step 6: 提交**

```bash
git add eit_ptlc/main.py eit_ptlc/tests/test_launcher_graceful_stop.py
git commit -m "feat(launcher): _stop_all 后端走优雅关停、其余维持强杀

组件C-2: [停止]/[退出]/[重启] 时后端先 _graceful_stop_backend, 成功即跳过强杀;
失败/超时回退 _terminate_tree. Bridge/前端无关键收尾, 维持 taskkill /F 不扩面.
追加路由单测: 后端优雅+其余强杀、优雅失败回退强杀.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 真机验收(手测,无自动化代码)

**Files:** 无(仅执行与记录)。

**说明:** 组件 A 的相机侧行为、组件 C 的跨控制台 CTRL_BREAK 真实投递,离线测不了,须在装了大恒相机的真机 `--real` 模式手测。逐条勾选并记录结果。

- [ ] **A-1 相机复位根治 0fps:** 起后端 `--real`,经视觉调试台/photoscrape 触发一次观板相机(.169)拍照并成功出图。随后打开大恒 GxViewer 选该相机点“开始采集”,应**正常连续出帧**(采集帧率>0、带宽>0),不再是 0fps。
- [ ] **A-2 复位日志:** 后端控制台该次拍照日志出现 `触发模式已复位: Off（连续采集）` 与 `相机已断开`。
- [ ] **C-1 优雅关停:** 后端运行中,launcher 菜单选 [停止]。后端控制台应出现 uvicorn 的 `Shutting down` / `Application shutdown complete`(即 lifespan 收尾跑到)且窗口随后关闭;而非瞬间被强杀。
- [ ] **C-2 在飞拍照被干净排空(UV 安全):** 触发一次带 UV 的拍照,在其进行中(UV 灯亮的 ~1-2s 窗口内)于 launcher 选 [停止]。应观察到 **UV 灯被熄灭**、后端日志出现该次拍照的 finally 关灯/`相机已断开`,再进入 lifespan 收尾。
- [ ] **C-3 兜底不劣化:** 若某次后端优雅关停未在 8s 内完成(如 driver 卡住),确认 launcher 打印 `[后端] 优雅退出未完成, 强制终止` 并最终 `taskkill` 使进程退出(不残留占端口)。

**验收记录(实施时填):**
- A-1/A-2: ______
- C-1/C-2/C-3: ______

---

## Self-Review

**1. Spec coverage(逐条对 spec §5–§9):**
- §5 组件 A(remote=None + finally 复位)→ Task 1 Step 3/4。✓
- §5 组件 C(_graceful_stop_backend helper + _stop_all 路由 + 后端-only 范围)→ Task 2 + Task 3。✓
- §5 组件间交互(CTRL_BREAK→uvicorn→取消请求→shield 排空在飞拍照)→ Task 4 C-2 手测验收。✓
- §6 测试(组件A 三路径断言 last TriggerMode==Off;组件C 回退离线单测 + 跨控制台真机手测)→ Task 1 Step 1 / Task 2 Step 1 / Task 4。✓
- §7 影响文件(daheng_capture.py / test_camera_safety.py / main.py)全部覆盖;另按 §6 新增 test_launcher_graceful_stop.py。✓
- §8 范围外(硬件/PLC UV 联锁)→ 明确不含,未建 Task。✓
- §9 风险(跨控制台投递失败→taskkill 兜底;收尾卡住→wait 超时;断连写 TriggerMode 抛错→try 吞掉)→ 分别由 Task 2 回退分支、Task 1 finally try/except 覆盖。✓

**2. Placeholder scan:** 无 TBD/TODO/“类似上文”;每个代码步给出完整代码;每个运行步给出确切命令与期望。✓

**3. Type consistency:** `_graceful_stop_backend(proc, *, break_timeout=5.0, wait_timeout=8.0) -> bool` 在 Task 2 定义、Task 3 以 `_graceful_stop_backend(proc)` 调用(用默认 kwargs),一致;`_stop_all` 对后端名 `"后端"` 与 `_start_all` 登记键一致;测试引用的 `_install_fake_camera/_safe_params/_work_path/_DataStream` 均为 `test_camera_safety.py` 现有夹具。✓
