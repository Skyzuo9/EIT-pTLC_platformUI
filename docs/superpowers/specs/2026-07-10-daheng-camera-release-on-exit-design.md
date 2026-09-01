# 大恒观板相机（.169）拍照后 / 退出时的相机资源释放 — 设计

- 日期: 2026-07-10
- 分支: codex/ui-upper-next
- 相关: [[ptlc-active-work]] PALLAS vision / vision debug station；相机拍照路径 `daheng_capture`

## 1. 背景与现象

在大恒原厂软件 GxViewer 上对**观板相机（FAN26010020，IP 192.168.0.169）**点“开始采集”后：
`采集帧率 = 0.00 帧/秒`、`帧数 = 0`、`带宽 = 0.0 Mbps`；重启 GxViewer 或断连重连都不恢复。

该相机由上位机的 `eit_ptlc/driver/daheng_capture.py`（gxipy）驱动，用于 photoscrape 的整板拍照（含 UV 荧光）。PALLAS 纠偏相机（`pallas.host 192.168.0.168`）是另一套独立程序，与本问题无关。

## 2. 根因

`capture()` 为 UV 安全契约默认用**软触发**（`DEFAULT_PARAMS["trigger_mode"]="On"`, `daheng_capture.py:87`；`app.yaml:111` 同）：
- 配置阶段 `daheng_capture.py:491-492` 把相机设成 `TriggerMode=On` / `TriggerSource=Software`。
- 最外层 `finally`（`daheng_capture.py:667-679`）只做 `stream_off()` + `close_device()`，**从不把 `TriggerMode` 复位回 `Off`**。

`close_device()`（`GXCloseDevice`）只断控制通道，**不还原相机 GenICam 寄存器**。`TriggerMode` 是相机端寄存器态，跨 GVCP 断连重连保持，只有断电重载 UserSet 或显式写 `Off` 才复位。于是每次拍完相机被留在“软触发待命”态；GxViewer 的连续采集在等一个永不到来的触发 → 0 帧 / 0 带宽 / 0 fps。这与观察到的“重连也恢复不了”完全吻合。

**这是一次回归**：冻结原版 `UI-Upper/scripts/daheng_capture.py:71` 默认 `trigger_mode="Off"`（连续），拍完停在 Off，GxViewer 正常；现版本为 UV 安全把默认翻成 On，却没同步在 finally 复位。

**句柄释放本身没问题**：`test_camera_safety.py` 已覆盖成功、取图 None、取图抛错、存图失败四条路径，均 `stream_off_count==1` 且 `closed is True`。问题不是句柄泄漏，是“释放了句柄但没把相机留成可复用的中性态”。

## 3. 相机生命周期与退出现状（实测结论）

- `DahengCameraService`（`camera_driver.py`）**不持有常开句柄**，只存参数 + 一把 `asyncio.Lock`；每次 `capture()` 走 open→配参→`stream_on`→抓 1 帧→`stream_off`→`close_device`（全在 finally 保护内）。
- 因此两次拍照之间相机全关；FastAPI `lifespan` 收尾（`bootstrap.py:543-557`）没有相机这一步——没有常驻对象要关。非拍照时刻退出天然干净。
- **缺口**：launcher（`main.py`）在 [停止]/[退出]/[重启] 用 `taskkill /F /T` 强杀后端（`_terminate_tree`, `main.py:191-206`）。强杀 = 不跑 lifespan、不跑任何 finally。非拍照时刻无所谓；但若强杀时正有一次 UV 拍照在跑，`capture()` 的 finally 不执行 → 相机留在开着+armed，且负责兜底关灯的 `threading.Timer` 随进程死 → **UV 灯可能一直亮**，相机侧要等 GVCP 心跳超时（~3s）才放开控制通道，寄存器态要断电才复位。

## 4. 目标与非目标

**目标**
1. 根治 GxViewer 0fps：每次拍完把相机留成中性态（连续采集 + 关闭）。
2. 上位机菜单式退出/停止/重启时可靠释放相机：让 lifespan 收尾与在飞拍照的 finally 有机会跑完（顺带 UV 熄灯、PLC 断开、机器人 close、run_store 关闭）。

**非目标**
- 不改相机模型：维持 Option A“按需拍照”（open/close per shot），不引入常开句柄 / 实时预览。
- 不覆盖真正的崩溃 / 断电 / `taskkill /F`（`TerminateProcess`）下的 UV 安全——那属硬件/PLC 联锁，见 §8。

## 5. 设计

### 组件 A — 相机侧复位契约（`daheng_capture.py`）

1. 在 `try:`（现 `477`）之前加 `remote = None`，避免 `get_remote_device_feature_control()` 抛错时最外层 finally 引用未绑定的 `remote` → `NameError`。
2. 最外层 finally（现 `667-679`）在 `stream_off()` 之后、`close_device()` 之前，插 best-effort 复位：

```python
if remote is not None:
    try:
        remote.get_enum_feature("TriggerMode").set("Off")
        log.info("触发模式已复位: Off（连续采集）")
    except Exception:
        log.warning("复位 TriggerMode=Off 失败", exc_info=True)
```

**性质**：幂等、无条件尝试（不论本次 On/Off、成功/异常/被取消）；异常被吞,永不阻断 `close_device()`。语义 = 每次 `capture()` 结束后相机 = 连续采集 + 已关闭，下一个消费者（GxViewer / 下次拍照）按“开始采集”即出帧。stream_off 后、close 前写 TriggerMode 在 GenICam 语义下合法（配触发须在采集停止时）。

### 组件 C — launcher 优雅关停后端（`main.py`）

后端是 `CREATE_NEW_CONSOLE` 独立控制台里的 uvicorn；uvicorn 在 Windows 默认捕获 `SIGBREAK` → `should_exit=True` → 跑 lifespan shutdown。跨控制台投递 CTRL_BREAK 用**一次性 helper 子进程**隔离，避免扰动 launcher 自己的控制台/交互菜单：

```python
def _graceful_stop_backend(proc, *, break_timeout=5.0, wait_timeout=8.0) -> bool:
    """向后端控制台组广播 CTRL_BREAK，等待其优雅退出；成功返回 True。"""
    if proc.poll() is not None:
        return True
    try:
        subprocess.run(
            [sys.executable, "-c",
             "import ctypes,sys;k=ctypes.windll.kernel32;"
             "k.FreeConsole();k.AttachConsole(int(sys.argv[1]));"
             "k.GenerateConsoleCtrlEvent(1,0)",   # CTRL_BREAK_EVENT=1, group 0 = 该控制台全部
             str(proc.pid)],
            timeout=break_timeout, check=False,
        )
        proc.wait(timeout=wait_timeout)   # 等 lifespan 收尾 + 在飞拍照 finally 跑完
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False
```

`_terminate_tree`（或新 `_stop_backend`）改为：先 `_graceful_stop_backend`，失败/超时再 `taskkill /F /T` 兜底。

**范围**：只对**后端**优雅关停（它才有 lifespan 收尾）。PALLASBridge / vite 前端无关键收尾，维持 `taskkill /F`，不扩大改动面。

**降级安全**：CTRL_BREAK 投递失败或 uvicorn 收尾卡住 → `proc.wait` 超时 → `taskkill /F` 兜底，进程必死。最坏 = 退回今天的行为，不会更糟。

### 组件间交互（C 为何能救 UV）

CTRL_BREAK → uvicorn 优雅关 → 取消在跑的请求任务 → `DahengCameraService.capture_with_timing` 的 `except asyncio.CancelledError` 里 `await asyncio.shield(future)` 等后台 SDK 线程把 finally 跑完（**关 UV 灯 + 组件 A 复位 TriggerMode + close_device**）→ 再抛。于是菜单停机时若正有 UV 拍照在跑，灯被正常熄灭、相机干净释放。

## 6. 测试

**组件 A（离线,扩 `test_camera_safety.py`）**：成功路径 + 取图 None + 取图抛错三条,均断言 `remote.events` 中**最后一次** `TriggerMode` 事件为 `"Off"`：
```python
trigger_vals = [v for (n, v, *_) in remote.events if n == "TriggerMode"]
assert trigger_vals[-1] == "Off"
```
现有断言（software_trigger_count / stream_off_count / closed / timing）不受影响（finally 仅多追加一个事件）。

**组件 C**：
- 离线单测 `_graceful_stop_backend` 的回退逻辑：mock 一个 `poll()` 返回 None、`wait()` 抛 `TimeoutExpired` 的假 proc → 断言函数返回 False（触发上层 taskkill）。
- 跨控制台信号投递靠**真机手测**：起后端 → 跑一次 photoscrape 拍照 → 菜单选 [停止] → 后端控制台应出现 lifespan shutdown 日志 + `相机已断开`，且相机 UV 熄灭、GxViewer 可正常连续采集。

## 7. 影响文件

- `eit_ptlc/driver/daheng_capture.py` — 组件 A
- `eit_ptlc/tests/test_camera_safety.py` — 组件 A 回归测试
- `eit_ptlc/main.py` — 组件 C

## 8. 范围外 / 后续项

真正的崩溃 / 断电 / `taskkill /F`（`TerminateProcess`）下，任何 Python finally/atexit/信号都跑不了。要在这种情况下也保证 UV 熄灭，正解是**硬件/PLC 联锁**：UV 供电经继电器由 PLC 控制，PLC 检测上位机心跳丢失即断 UV；或 UV 电源加独立看门狗。列入路线图,不在本次范围。

## 9. 风险

| 风险 | 缓解 |
|---|---|
| Windows 跨控制台 CTRL_BREAK 投递不生效 | `taskkill /F` 兜底,降级即今天行为;实现阶段真机实测确认 |
| uvicorn 优雅收尾被卡住的 driver 拖住 | `proc.wait` 有界超时 → taskkill 兜底 |
| 组件 A 在相机物理断连时写 TriggerMode 抛错 | best-effort try/except 吞掉,不阻断 close_device;断连时本无相机态需担心 |
