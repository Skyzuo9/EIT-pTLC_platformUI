# 液位 wait_level 降级语义修正 + 参考图自动采集 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** develop_execute 干板等待期不再 30s 误升 HITL;参考图每 run 自动采集;无参考/暗帧不再产出可信假象;阈值命中去抖。

**Architecture:** `wait_level` 内坏帧三分类 (正常等待 / 传输降级 / 配置错误) + `confirm_n` 去抖;新纯函数 `capture_reference` (waterlevel_trigger 内, 与 wait_level 同注入模式) 经 bootstrap `vision_methods` 挂成 host action `develop.capture_reference`,接在 develop_execute body 开头;检测服务加暗帧守卫与 `has_reference/cancel_reference`;前端 reason 文案映射。

**Tech Stack:** Python (asyncio, stdlib-only trigger 模块), FastAPI host actions, ptlc.script/v1 YAML VM, Vue3。

**Spec:** `docs/superpowers/specs/2026-07-16-waterlevel-wait-semantics-autoref-design.md`

## Global Constraints

- `wait_level` 返回契约形状不变: `{status, front_percent, threshold, stage, elapsed_s, reason}`,status ∈ reached/degraded/hard_cap。
- 优先级契约保持: 检测 > HITL > 硬上限;hard_cap 到点时当前采样已达阈 → 按 `reached` 计 (既有测试 test_hard_cap_zero_immediate 锁定)。
- `waterlevel_trigger.py` 纯 stdlib (禁 cv2/httpx/numpy) — capture_reference 同样遵守。
- 香橙派载荷 `eit_ptlc/driver/water_level_payload/` 禁改。
- `auto_drain` 默认 false 不动 (test_auto_drain_knob_defaults_off 锁定)。
- 决策值 (spec §7): D1 参考失败=HITL 确认继续 (合并单门);D2 不加无前沿超时;D3 `confirm_n` 默认 2 (函数与 action YAML 同值);D4 暗帧守卫 `DARK_FRAME_RATIO = 0.35`。
- 离线测试无真实 sleep/网络: 假时钟 (`FakeClock`) 注入;测试解释器 `E:/Anaconda/envs/platformupper/python.exe`。
- 注释/日志中文, `[WL]`/`[WL-trigger]` 前缀与现存一致;YAML 流程内设计知识用 `op: comment` (web 编辑器回写会剥 YAML 注释)。
- 每个 Task 只 `git add` 本 Task 文件 (工作树有无关 WIP);commit message 末尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

---

### Task 0: 提交 spec 与本计划

**Files:**
- Add: `docs/superpowers/specs/2026-07-16-waterlevel-wait-semantics-autoref-design.md`
- Add: `docs/superpowers/plans/2026-07-16-waterlevel-wait-semantics-autoref.md`

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/specs/2026-07-16-waterlevel-wait-semantics-autoref-design.md docs/superpowers/plans/2026-07-16-waterlevel-wait-semantics-autoref.md
git commit -m "docs(waterlevel): wait_level 降级语义修正+参考图自动采集 spec+plan

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 1: wait_level 三分类 + confirm_n 去抖

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_trigger.py` (wait_level 主体)
- Test: `eit_ptlc/tests/test_waterlevel_trigger_offline.py`

**Interfaces:**
- Consumes: `detect.snapshot()` 通道字段 `reachable/valid/reason/front_percent/observed_at/has_ref` (has_ref 已存在于生产 snapshot)。
- Produces: `async def wait_level(detect, *, target_tank, stage, staleness_s=30.0, hard_cap_s=3600.0, poll_s=2.0, confirm_n=2, time_fn=time.monotonic, sleep=asyncio.sleep) -> dict` — 返回形状不变;reason 新增取值 `config:no_reference`、`config:no_roi`、`config:empty_roi`、`invalid:frame_dark`、`waiting:no_signal`、`waiting:front_none`。

分类语义 (spec §3.1, 判定顺序即优先级):
1. `chd is None` → transport `channel_missing`
2. `not reachable` → transport `unreachable`
3. `observed_at` 缺失/超龄 (对所有后续判定生效, 从 valid 分支上移) → transport `stale:*`
4. `has_ref is False` (显式 False 才触发; 缺键跳过, 兼容旧假服务) → config `no_reference` **立即** degraded
5. `not valid`: reason ∈ {no_signal} → waiting;∈ {no_roi, empty_roi} → config 立即 degraded;其余 (含 frame_dark、未知) → transport `invalid:<reason>`
6. `front_percent is None` → waiting `front_none`
7. 有读数: `fp >= threshold` 连续 `confirm_n` 拍 → reached;否则连击清零继续等
- waiting 类清零 bad_since 与连击, 首拍 INFO 一条日志, 之后静默等 (hard_cap 兜底)。
- hard_cap 到点: 当前采样 fp≥threshold → reached (契约), 否则 hard_cap。

- [ ] **Step 1: 更新既有测试期望 + 写新失败测试**

在 `test_waterlevel_trigger_offline.py`:

1. `_chan` 帮助函数加 `has_ref=True` 默认字段:

```python
def _chan(front_percent, *, valid=True, reachable=True, reason="", age_s=0.0,
          has_ref=True) -> dict:
    observed = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {"front_percent": front_percent, "valid": valid, "reachable": reachable,
            "reason": reason, "observed_at": observed.isoformat(), "has_ref": has_ref}
```

2. `test_reached_t2`: `confirm_n=2` 下第 3 帧首击、驻留帧二击 → `elapsed_s` 期望 `4.0` 改 `6.0`。
3. 删除 `test_degraded_front_none`, 替换为等待语义 + 新增用例:

```python
    def test_front_none_waits_to_hard_cap(self) -> None:
        # 前沿线未成形 = 正常等待, 不再 30s 降级; 由 hard_cap 兜底
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None)]), clock, hard_cap_s=20.0)
        self.assertEqual(res["status"], "hard_cap")
        self.assertEqual(res["reason"], "waiting:front_none")

    def test_no_signal_waits_to_hard_cap(self) -> None:
        # 前沿未进 ROI (invalid:no_signal) = 物理正常等待态, 不降级 (0715 ch6 回放根因)
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None, valid=False, reason="no_signal")]),
                         clock, hard_cap_s=20.0)
        self.assertEqual(res["status"], "hard_cap")
        self.assertEqual(res["reason"], "waiting:no_signal")

    def test_no_signal_then_ramp_reaches(self) -> None:
        # 0715 时间线缩样: 长 no_signal 等待后前沿爬坡 → reached, 全程不降级
        clock = FakeClock()
        frames = [_chan(None, valid=False, reason="no_signal")] * 30 + [
            _chan(40.0), _chan(70.0), _chan(85.0), _chan(85.0)]
        res = self._wait(FakeDetect(frames), clock, hard_cap_s=500.0)
        self.assertEqual(res["status"], "reached")

    def test_no_reference_config_degraded_immediately(self) -> None:
        # 无参考 → Otsu 回退值不可信: 立即配置错误降级, 不等 staleness_s
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(85.0, has_ref=False)]), clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "config:no_reference")
        self.assertEqual(res["elapsed_s"], 0.0)

    def test_no_roi_config_degraded_immediately(self) -> None:
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None, valid=False, reason="no_roi")]), clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "config:no_roi")

    def test_frame_dark_transport_degraded(self) -> None:
        # 暗帧按传输类累计: 持续 >= staleness_s 才降级 (曝光爬坡数秒不触发)
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(None, valid=False, reason="frame_dark")]), clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "invalid:frame_dark")
        self.assertGreaterEqual(res["elapsed_s"], 6.0)

    def test_confirm_n_blocks_single_spike(self) -> None:
        # 单拍尖峰 (85) 不触发; 回落后到 hard_cap
        clock = FakeClock()
        frames = [_chan(85.0), _chan(50.0), _chan(50.0)]
        res = self._wait(FakeDetect(frames), clock, hard_cap_s=10.0)
        self.assertEqual(res["status"], "hard_cap")

    def test_confirm_n_one_keeps_single_hit(self) -> None:
        # confirm_n=1 = 旧行为单拍即触
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(85.0)]), clock, confirm_n=1)
        self.assertEqual(res["status"], "reached")
        self.assertEqual(res["elapsed_s"], 0.0)
```

- [ ] **Step 2: 跑测试确认新用例失败、旧改期望失败**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_trigger_offline -v
```
Expected: FAIL — `test_no_signal_waits_to_hard_cap` 等得到 `degraded`≠`hard_cap`;`test_reached_t2` elapsed 4.0≠6.0;`wait_level() got an unexpected keyword argument 'confirm_n'`。

- [ ] **Step 3: 实现 wait_level 三分类**

`waterlevel_trigger.py` 中 `wait_level` 整体替换为 (模块 docstring 的三态说明同步改写: degraded 仅限传输/配置故障, no_signal/front_none 为正常等待):

```python
# 正常等待 (不降级): 前沿未进 ROI — 物理等待态, 只由 hard_cap 兜底
_WAITING_REASONS = {"no_signal"}
# 配置错误 (立即降级): 标定/ROI 缺失 — 等不来, 立刻升级人处理
_CONFIG_REASONS = {"no_roi", "empty_roi"}


async def wait_level(detect: Any, *, target_tank: int, stage: str,
                     staleness_s: float = 30.0, hard_cap_s: float = 3600.0,
                     poll_s: float = 2.0, confirm_n: int = 2,
                     time_fn: Callable[[], float] = time.monotonic,
                     sleep: Callable[[float], Any] = asyncio.sleep) -> dict:
    """阻塞等待通道 front_percent 到阈值档; 见模块 docstring 的三态契约。

    坏帧三分类 (spec 2026-07-16-waterlevel-wait-semantics-autoref):
      waiting   no_signal / front_none — 前沿未到为正常态, 不降级, hard_cap 兜底;
      transport unreachable / stale / channel_missing / frame_dark 等 — 持续
                >= staleness_s → degraded (原语义);
      config    no_roi / empty_roi / 无参考图 — 等不来, 立即 degraded (reason 前缀 config:)。
    confirm_n: 连续 N 拍 >= 阈值才 reached (去抖, 挡单帧尖峰); hard_cap 到点时
    当前采样已达阈仍按 reached 计 (检测 > 硬上限契约)。
    """
    ch = int(target_tank)
    threshold = resolve_threshold(detect.get_params(ch) or {}, str(stage))
    need = max(1, int(confirm_n))
    start = time_fn()
    bad_since: Optional[float] = None
    bad_reason = ""
    last_fp: Optional[float] = None
    hit_streak = 0
    waiting_logged = False

    def _result(status: str) -> dict:
        elapsed = round(time_fn() - start, 3)
        if status != STATUS_REACHED:
            log.warning("[WL-trigger] CH%s stage=%s → %s (front=%s 阈值=%.2f 历时=%.1fs %s)",
                        ch, stage, status, last_fp, threshold, elapsed, bad_reason)
        else:
            log.info("[WL-trigger] CH%s stage=%s 命中 (front=%.2f >= %.2f, 历时=%.1fs)",
                     ch, stage, last_fp, threshold, elapsed)
        return {"status": status, "front_percent": last_fp, "threshold": threshold,
                "stage": str(stage), "elapsed_s": elapsed, "reason": bad_reason}

    while True:
        snap = detect.snapshot() or {}
        channels = snap.get("channels") or {}
        chd = channels.get(ch) or channels.get(str(ch))
        now = time_fn()

        fp: Optional[float] = None
        klass = "reading"
        if chd is None:
            klass, bad_reason = "transport", "channel_missing"
        elif not chd.get("reachable", False):
            klass, bad_reason = "transport", "unreachable"
        else:
            age = _observed_age_s(chd.get("observed_at"))
            if age is None or age > staleness_s:
                klass, bad_reason = "transport", f"stale:{age}"
            elif chd.get("has_ref") is False:
                # 无参考 → detect_level 走 Otsu 回退, valid=True 但 percent 乱值, 不可采信
                klass, bad_reason = "config", "no_reference"
            elif not chd.get("valid", False):
                reason = str(chd.get("reason") or "")
                if reason in _WAITING_REASONS:
                    klass, bad_reason = "waiting", f"waiting:{reason}"
                elif reason in _CONFIG_REASONS:
                    klass, bad_reason = "config", reason
                else:
                    klass, bad_reason = "transport", f"invalid:{reason}"
            elif chd.get("front_percent") is None:
                klass, bad_reason = "waiting", "waiting:front_none"
            else:
                fp = float(chd["front_percent"])

        if klass == "config":
            if not bad_reason.startswith("config:"):
                bad_reason = f"config:{bad_reason}"
            return _result(STATUS_DEGRADED)
        if klass == "transport":
            hit_streak = 0
            bad_since = now if bad_since is None else bad_since
            if now - bad_since >= staleness_s:
                return _result(STATUS_DEGRADED)
        elif klass == "waiting":
            hit_streak = 0
            bad_since = None
            if not waiting_logged:
                waiting_logged = True
                log.info("[WL-trigger] CH%s stage=%s 前沿未出现 (%s), 正常等待中 (hard_cap 兜底)",
                         ch, stage, bad_reason)
        else:
            bad_since = None
            bad_reason = ""
            last_fp = fp
            if fp >= threshold:
                hit_streak += 1
                if hit_streak >= need:
                    return _result(STATUS_REACHED)
            else:
                hit_streak = 0

        if now - start >= hard_cap_s:
            if fp is not None and fp >= threshold:
                return _result(STATUS_REACHED)   # 检测 > 硬上限: 到点已在阈上按 reached 计
            return _result(STATUS_HARD_CAP)
        await sleep(poll_s)
```

- [ ] **Step 4: 跑测试确认全绿**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_trigger_offline -v
```
Expected: PASS (注意 `HostActionDispatchTests` 此时仍绿 — YAML 未加 confirm_n, executor 不注入该参数, 函数默认值 2 生效)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/waterlevel_trigger.py eit_ptlc/tests/test_waterlevel_trigger_offline.py
git commit -m "feat(waterlevel): wait_level 坏帧三分类+confirm_n 去抖 — 干板等待不再 30s 误升 HITL, 无参考不采信 Otsu (spec 0716 §3.1-3.2)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: capture_reference 等待函数 + 服务 has_reference/cancel_reference

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_trigger.py` (追加 capture_reference)
- Modify: `eit_ptlc/controller/waterlevel_service.py` (追加两个小方法, 放在 `request_reference` 之后)
- Test: `eit_ptlc/tests/test_waterlevel_trigger_offline.py` (追加 CaptureReferenceTests)

**Interfaces:**
- Consumes: `detect.request_reference(ch)` (已有), `detect.ensure_active(ch)` (已有, async, 可缺省), 新增 `detect.has_reference(ch) -> bool`、`detect.cancel_reference(ch) -> None`。
- Produces: `async def capture_reference(detect, *, target_tank: int, timeout_s: float = 90.0, poll_s: float = 1.0, time_fn=time.monotonic, sleep=asyncio.sleep) -> dict` 返回 `{"ok": bool, "has_ref": bool, "elapsed_s": float}`。Task 4 的 bootstrap 包装与 Task 5 的流程 `ref_result.ok` 依赖此形状。

- [ ] **Step 1: 写失败测试**

```python
class FakeRefDetect:
    """假检测服务: has_reference 在第 ready_after 次轮询后转真; ready_after=None 永不就绪."""

    def __init__(self, ready_after=2) -> None:
        self.requests: list[int] = []
        self.cancels: list[int] = []
        self.ensured: list[int] = []
        self._polls = 0
        self._ready_after = ready_after

    async def ensure_active(self, ch: int) -> None:
        self.ensured.append(int(ch))

    def request_reference(self, ch: int) -> None:
        self.requests.append(int(ch))

    def cancel_reference(self, ch: int) -> None:
        self.cancels.append(int(ch))

    def has_reference(self, ch: int) -> bool:
        self._polls += 1
        return self._ready_after is not None and self._polls > self._ready_after


class CaptureReferenceTests(unittest.TestCase):
    def test_ok_after_window(self) -> None:
        clock = FakeClock()
        det = FakeRefDetect(ready_after=2)
        res = _run(capture_reference(det, target_tank=6, timeout_s=90.0, poll_s=1.0,
                                     time_fn=clock.time, sleep=clock.sleep))
        self.assertEqual(res, {"ok": True, "has_ref": True, "elapsed_s": 2.0})
        self.assertEqual(det.ensured, [6])     # 采集前确保通道在采
        self.assertEqual(det.requests, [6])    # 每 run 无条件重拍
        self.assertEqual(det.cancels, [])

    def test_timeout_cancels_pending(self) -> None:
        # 超时必须撤销挂起窗口: 防帧源迟到后在湿板上补采毒参考
        clock = FakeClock()
        det = FakeRefDetect(ready_after=None)
        res = _run(capture_reference(det, target_tank=3, timeout_s=5.0, poll_s=1.0,
                                     time_fn=clock.time, sleep=clock.sleep))
        self.assertFalse(res["ok"])
        self.assertFalse(res["has_ref"])
        self.assertGreaterEqual(res["elapsed_s"], 5.0)
        self.assertEqual(det.cancels, [3])
```

导入行改为 `from eit_ptlc.controller.waterlevel_trigger import capture_reference, resolve_threshold, wait_level`。

服务侧两方法的用例加进 `test_waterlevel_service_offline.py` 第 1) 节之后 (哨兵行 `check("ref_tick_no_result", ...)` 之后插入, 文件尾 `total = 22` 改 `total = 24`):

```python
        # 1b) has_reference / cancel_reference (capture_reference 轮询与超时撤销用)
        check("has_reference_true", svc.has_reference(1) is True, "")
        svc.request_reference(1)                       # 重开窗口 → pending
        svc.cancel_reference(1)
        check("cancel_clears_pending", 1 not in svc._ref_pending and 1 not in svc._ref_accum,
              f"pending={svc._ref_pending}")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_trigger_offline -v
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_service_offline
```
Expected: FAIL — `ImportError: cannot import name 'capture_reference'`;service 套件 `AttributeError: has_reference`。

- [ ] **Step 3: 实现**

`waterlevel_trigger.py` 追加 (wait_level 之后):

```python
async def capture_reference(detect: Any, *, target_tank: int,
                            timeout_s: float = 90.0, poll_s: float = 1.0,
                            time_fn: Callable[[], float] = time.monotonic,
                            sleep: Callable[[float], Any] = asyncio.sleep) -> dict:
    """展开 run 起点自动采集干板参考: 请求窗口并等完成 (develop.capture_reference 的 host 函数)。

    参考是板专属基线 (换板即作废) → 每 run 无条件重拍, 覆盖旧参考。窗口本体约
    ref_frames×interval (默认 15×2s ≈ 30s); timeout_s 兜底通道不可达/无帧。
    超时必须 cancel_reference 撤销挂起窗口 —— 否则帧源若在展开中途恢复, 会在
    湿板上补采一张毒参考, 反而给 wait_level 喂假信号。
    """
    ch = int(target_tank)
    start = time_fn()
    ensure = getattr(detect, "ensure_active", None)
    if ensure is not None:
        await ensure(ch)          # 保通道在采 (max_active 上限下的查看 pin; cap=0 时无副作用)
    detect.request_reference(ch)
    while True:
        if detect.has_reference(ch):
            elapsed = round(time_fn() - start, 3)
            log.info("[WL-trigger] CH%s 参考图采集完成 (%.1fs)", ch, elapsed)
            return {"ok": True, "has_ref": True, "elapsed_s": elapsed}
        if time_fn() - start >= timeout_s:
            detect.cancel_reference(ch)
            elapsed = round(time_fn() - start, 3)
            log.warning("[WL-trigger] CH%s 参考图采集超时 (%.1fs) — 通道不可达/无帧? 本次液位检测不可用",
                        ch, elapsed)
            return {"ok": False, "has_ref": bool(detect.has_reference(ch)),
                    "elapsed_s": elapsed}
        await sleep(poll_s)
```

`waterlevel_service.py` 在 `request_reference` 方法之后追加:

```python
    def has_reference(self, channel: int) -> bool:
        """该通道是否已有干板参考 (capture_reference 轮询完成判据)。"""
        return int(channel) in self._refs

    def cancel_reference(self, channel: int) -> None:
        """撤销挂起的参考窗口 (采集超时时调): 防帧源迟到后在湿板上补采毒参考。"""
        ch = int(channel)
        self._ref_pending.discard(ch)
        self._ref_accum.pop(ch, None)
```

- [ ] **Step 4: 跑两套测试确认全绿**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_trigger_offline -v
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_service_offline
```
Expected: 全 PASS;service 套件打印 `共 24 用例, 失败 0`。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/waterlevel_trigger.py eit_ptlc/controller/waterlevel_service.py eit_ptlc/tests/test_waterlevel_trigger_offline.py eit_ptlc/tests/test_waterlevel_service_offline.py
git commit -m "feat(waterlevel): capture_reference 等待函数 + 服务 has/cancel_reference — 参考每 run 重拍, 超时撤销防湿板毒参考 (spec 0716 §3.3)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 检测服务暗帧守卫

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_service.py` (`_process` + 模块常量 + import)
- Test: `eit_ptlc/tests/test_waterlevel_service_offline.py`

**Interfaces:**
- Consumes: `extract_roi_gray(frame_bgr, calib, params)` (waterlevel_detector 已有纯函数)。
- Produces: snapshot 通道 `reason` 新增取值 `"frame_dark"` (Task 1 的 wait_level 按传输类消费; Task 6 的 UI 文案映射消费)。

- [ ] **Step 1: 写失败测试**

`test_waterlevel_service_offline.py` 第 2) 节 (`check("snapshot_gain_frozen", ...)` 行) 之后插入 (`total` 24 → 27):

```python
        # 2b) 暗帧守卫: 相机重开曝光爬坡的近黑帧 → frame_dark 无效帧, 不喂 front_max
        front_max_before = svc._front_max.get(1)
        det.frame = np.full((200, 300, 3), 20, np.uint8)   # 均亮 20 << 0.35×参考(~200)
        await svc._tick()
        c1 = svc.snapshot()["channels"].get(1)
        check("dark_frame_reason", c1 is not None and not c1["valid"]
              and c1["reason"] == "frame_dark", str(c1))
        check("dark_frame_front_max_kept", svc._front_max.get(1) == front_max_before,
              f"{svc._front_max.get(1)} != {front_max_before}")
        det.frame = _half_wet()
        await svc._tick()
        c1 = svc.snapshot()["channels"].get(1)
        check("dark_frame_recovery", c1 is not None and c1["valid"], str(c1))
```

- [ ] **Step 2: 跑测试确认失败**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_service_offline
```
Expected: FAIL `dark_frame_reason` — 现状黑帧算出 `valid=True` (log 域全板伪湿), 正是要堵的洞。

- [ ] **Step 3: 实现守卫**

`waterlevel_service.py`:

1. import 块 `detect_level,` 后加一行 `extract_roi_gray,` (来自 waterlevel_detector)。
2. `log = logging.getLogger(__name__)` 之后加模块常量:

```python
# 暗帧守卫: ROI 均亮 < 此比例×参考均亮 → 判暗帧 (相机重开曝光爬坡等), 弃帧不检测。
# 全板浸润的真实变暗 ~10-30% (wet_rel_threshold 5%/px 即判湿), 远到不了 65% — 0.35 安全。
DARK_FRAME_RATIO = 0.35
```

3. `_process` 中 `ref = self._refs.get(ch)` 行之后、`gain_override = None` 之前插入:

```python
        if ref is not None:
            gray = await loop.run_in_executor(
                None, extract_roi_gray, frame, cfg.calib, cfg.params)
            if (gray is not None
                    and float(gray.mean()) < DARK_FRAME_RATIO * float(ref.plate_gray.mean())):
                prev = self._results.get(ch)
                if prev is None or prev.reason != "frame_dark":   # 边沿日志, 持续暗不刷屏
                    log.warning("[WL] CH%s 暗帧 (ROI 均亮 %.1f < %.2f×参考 %.1f), 弃帧不检测",
                                ch, float(gray.mean()), DARK_FRAME_RATIO,
                                float(ref.plate_gray.mean()))
                self._results[ch] = LevelResult(valid=False, reason="frame_dark",
                                                roi_size=(gray.shape[1], gray.shape[0]))
                self._observed_at[ch] = datetime.now(timezone.utc).isoformat()
                return
```

(放行路径不缓存 gray 复用 — detect_level 内部自取, 双提取每 2s 一次可忽略, 换代码简单。)

- [ ] **Step 4: 跑测试确认全绿**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_service_offline
```
Expected: `共 27 用例, 失败 0`。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/waterlevel_service.py eit_ptlc/tests/test_waterlevel_service_offline.py
git commit -m "feat(waterlevel): 暗帧守卫 — 曝光爬坡近黑帧记 frame_dark 弃帧, 堵 percent≈100 假信号与 front_max 污染 (spec 0716 §3.4)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: action YAML + bootstrap 注册

**Files:**
- Modify: `eit_ptlc/config/actions/02_develop/waterlevel.yaml`
- Modify: `eit_ptlc/runtime/bootstrap.py` (`_wait_level` 旁 + `vision_methods`)
- Test: `eit_ptlc/tests/test_waterlevel_trigger_offline.py` (HostActionDispatchTests)

**Interfaces:**
- Consumes: Task 2 的 `capture_reference(detect, **kwargs)`。
- Produces: action `develop.capture_reference` (kind=host, method=capture_reference, params: target_tank 必填 1-8, timeout_s 默认 90.0);`develop.wait_level` 新参 `confirm_n` 默认 2 — Task 5 流程 YAML 依赖两者。

- [ ] **Step 1: 写失败测试**

`HostActionDispatchTests` 内 `test_action_definition` 追加断言, 并新增两用例:

```python
        # test_action_definition 尾部追加:
        self.assertEqual(adef.param("confirm_n").default, 2)

    def test_capture_action_definition(self) -> None:
        adef = self.registry.get("develop.capture_reference")
        self.assertEqual(adef.kind, "host")
        self.assertEqual(adef.method, "capture_reference")
        tank = adef.param("target_tank")
        self.assertTrue(tank.required)
        self.assertEqual((tank.minimum, tank.maximum), (1, 8))
        self.assertEqual(adef.param("timeout_s").default, 90.0)

    def test_capture_dispatch(self) -> None:
        from eit_ptlc.action.executor import ActionExecutor
        from eit_ptlc.action.models import ActionStatus
        seen = {}

        async def fake_capture(**kwargs):
            seen.update(kwargs)
            return {"ok": True, "has_ref": True, "elapsed_s": 31.0}

        executor = ActionExecutor(self.registry, vision_methods={"capture_reference": fake_capture})
        res = asyncio.run(executor.execute("develop.capture_reference", {"target_tank": 6}))
        self.assertIs(res.status, ActionStatus.DONE)
        self.assertTrue(res.result["ok"])
        self.assertEqual(seen, {"target_tank": 6, "timeout_s": 90.0})
```

同文件 `test_executor_dispatches_to_injected_method` 的 `seen` 期望字典加 `"confirm_n": 2`。

- [ ] **Step 2: 跑测试确认失败**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_trigger_offline -v
```
Expected: FAIL — registry 无 `develop.capture_reference`;`confirm_n` 参数缺失。

- [ ] **Step 3: 实现 YAML + bootstrap**

`config/actions/02_develop/waterlevel.yaml` 头注释三态说明改为 "degraded = 传输/配置故障 (掉流/陈旧/无参考/未标定); 前沿未到 (no_signal/front_none) 为正常等待不降级 — spec 2026-07-16", `develop.wait_level` params 追加一行, 文件尾追加新 action:

```yaml
    - {name: confirm_n, type: int, required: false, default: 2, min: 1, max: 10, label: 命中确认拍数 (去抖)}

# 参考图自动采集 (host kind): 展开 run 起点拍干板基线 (板专属, 每 run 重拍)。
# 返回 {ok, has_ref, elapsed_s}; ok=false (不可达/超时) 由流程升 HITL 退化人工门。
# 设计: docs/superpowers/specs/2026-07-16-waterlevel-wait-semantics-autoref-design.md
develop.capture_reference:
  kind: host
  method: capture_reference
  label: 展缸-采集参考图
  desc: 板入缸后拍干板参考基线并等窗口完成 (~30s); 超时撤销窗口返回 ok=false。
  modes: []
  params:
    - {name: target_tank, type: int, required: true, min: 1, max: 8, label: 目标缸号}
    - {name: timeout_s, type: float, required: false, default: 90.0, min: 10.0, max: 600.0, label: 采集超时 (s)}
```

`bootstrap.py` 在 `_wait_level` 函数后追加同构包装, 并在 `vision_methods` 字典加 `"capture_reference": _wl_capture_reference,`:

```python
    async def _wl_capture_reference(**kwargs):
        """VM develop.capture_reference 入口: run 起点自动采集干板参考 (服务未启用则拒绝)。"""
        detect = getattr(app.state, "water_level_detect", None)
        if detect is None:
            raise ValueError("液位检测服务未启用 (water_level.enabled=false), develop.capture_reference 不可用")
        from eit_ptlc.controller.waterlevel_trigger import capture_reference
        return await capture_reference(detect, **kwargs)
```

- [ ] **Step 4: 跑测试确认全绿**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_waterlevel_trigger_offline -v
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/config/actions/02_develop/waterlevel.yaml eit_ptlc/runtime/bootstrap.py eit_ptlc/tests/test_waterlevel_trigger_offline.py
git commit -m "feat(waterlevel): develop.capture_reference action + wait_level confirm_n 参数注册 (spec 0716 §3.2-3.3)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: develop_execute.yaml 接线 + 流程测试更新

**Files:**
- Modify: `eit_ptlc/config/operation/02_develop/develop_execute.yaml`
- Test: `eit_ptlc/tests/test_develop_auto_drain_flow_offline.py`
- Test: `eit_ptlc/tests/test_develop_four_stage_offline.py`

**Interfaces:**
- Consumes: `develop.capture_reference` action (Task 4), 返回 `{ok, has_ref, elapsed_s}`。
- Produces: develop_execute 新契约 — body = capture_reference → (ok=false: 合并 HITL 门+排液) / (ok=true: 原 auto/manual 大 if 原样嵌入 else)。

- [ ] **Step 1: 更新测试期望 (先红)**

`test_develop_auto_drain_flow_offline.py`:

1. `SeqExecutor.execute` 中 result 行改为:

```python
        if name == "develop.wait_level":
            result = self._wait.pop(0)
        elif name == "develop.capture_reference":
            result = {"ok": True, "has_ref": True, "elapsed_s": 31.0}
        else:
            result = {}
```

2. 既有 4 个运行时用例的期望序列/下标更新 (capture 在首位, 全部 +1):
   - `test_reached_then_reached_full_path`: names 期望 `["develop.capture_reference", "develop.wait_level", "robot.require_anchor", "rail.move", "develop.wait_level", "develop.drain"]`;`rail_args = dict(ex.calls[3][1])`;`t2_args = dict(ex.calls[4][1])`。
   - `test_t1_hard_cap_skips_standby_and_drains`: 期望 `["develop.capture_reference", "develop.wait_level", "develop.drain"]`。
   - `test_t2_budget_never_negative`: `t2_args = dict(ex.calls[4][1])`。
   - `test_dry_duration_knob_passthrough`: 不改断言 (取 `calls[-1]`)。
3. `test_drain_calls_and_unload_order_structural`: drains 期望 `2` → `3` (fail/auto/manual 三处), 消息文案改 "develop_execute 应有 ref-fail/auto/manual 三处 drain"。
4. 新增结构用例 (human 门路径 mini-VM 跑不了, 结构断言守卫):

```python
    def test_ref_fail_branch_structural(self) -> None:
        """参考采集失败分支: 合并 HITL 门 (告知失败+确认排液) + drain, 在 auto/manual 大 if 之外."""
        execute = _load("develop_execute")
        body = execute["body"]
        capture = [n for n in body if isinstance(n, dict)
                   and n.get("op") == "call" and n.get("action") == "develop.capture_reference"]
        self.assertEqual(len(capture), 1)
        self.assertEqual(capture[0]["args"].get("target_tank"), {"var": "tank"})
        self.assertEqual(capture[0].get("assign"), {"var": "ref_result"})
        fail_if = next(n for n in body if isinstance(n, dict) and n.get("op") == "if"
                       and (n.get("cond") or {}).get("binop") == "==")
        prompts = [str((x.get("prompt") or {}).get("lit", ""))
                   for x in fail_if["then"] if isinstance(x, dict) and x.get("op") == "human"]
        self.assertTrue(any("参考图采集失败" in p for p in prompts))
        drains = [x for x in fail_if["then"] if isinstance(x, dict)
                  and x.get("op") == "call" and x.get("action") == "develop.drain"]
        self.assertEqual(len(drains), 1)
```

`test_develop_four_stage_offline.py` 的 execute_events 期望改为:

```python
            [
                ("call", "develop.capture_reference"),  # run 起点: 干板参考自动采集
                ("call", "develop.drain"),              # ref 失败: 退化人工门后排液
                ("call", "develop.wait_level"),         # auto: T1 等待
                ("run_script", "develop_standby"),      # auto: T1 命中物理就位
                ("call", "develop.wait_level"),         # auto: T2 等待
                ("call", "develop.drain"),              # auto: 排液 (reached/hard_cap/人已确认)
                ("call", "develop.drain"),              # manual else: HITL 后排液
            ],
```

- [ ] **Step 2: 跑两套确认失败**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_develop_auto_drain_flow_offline -v
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_develop_four_stage_offline -v
```
Expected: FAIL (YAML 尚无 capture_reference 节点)。

- [ ] **Step 3: 改 develop_execute.yaml**

vars 追加 (在 `wl_result` 条目后):

```yaml
- name: ref_result
  scope: local
  type: DICT
  io: var
  default: {}
  comment: develop.capture_reference 返回 (ok/has_ref/elapsed_s)
```

body 改为 (首条 comment 原文追加一句参考图说明; capture + ref-fail if 置于最前, 原 `op: if cond: var: auto_drain` 整块原样缩进进 else):

```yaml
body:
- op: comment
  text: "execute: 展开等待 + 排液闭环。run 起点先自动采集干板参考 (板已入缸/几何定型, 前沿距 ROI 尚远; 参考是板专属基线, 每 run 重拍)。auto_drain=true 走液位双阈值自动触发 (T1物理就位 / T2自动排液), false 保持人工 HITL 门。优先级: 检测 > HITL > 硬上限 (spec 2026-07-13-waterlevel-auto-drain + 2026-07-16 语义修正: 前沿未到为正常等待不降级)。排液恒走 develop.drain (PLC L2 code 50)。"
- op: call
  action: develop.capture_reference
  args:
    target_tank:
      var: tank
  assign:
    var: ref_result
  mode: RUN
- op: if
  cond:
    binop: ==
    left:
      field:
        var: ref_result
      name: ok
    right:
      lit: false
  then:
  - op: comment
    text: "参考采集失败 (通道不可达/超时): 本次液位检测不可用, 退化人工门 (spec 0716 决策 D1); 单门合并告知+确认, 确认后直接排液"
  - op: human
    kind: confirm
    on_cancel: raise
    prompt:
      lit: 参考图采集失败, 本次液位检测不可用; 展开完成后确认开始 PLC L2 排液
  - op: call
    action: develop.drain
    args:
      target_tank:
        var: tank
      dry_duration_s:
        var: dry_duration_s
    mode: RUN
  else:
  - op: if
    cond:
      var: auto_drain
    then:
    # …… (原 auto 分支全部节点原样, 含 T1/T2 wait_level、degraded HITL、drain)
    else:
    # …… (原 manual 分支两节点原样: human 展开完成确认 + drain)
```

("原样" 指现文件 51-144 行的 auto/manual 大 if 整块平移缩进, 节点零改动 — 实施时直接整段搬移, 勿重敲。)

- [ ] **Step 4: 跑测试确认全绿**

```bash
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_develop_auto_drain_flow_offline -v
E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_develop_four_stage_offline -v
```
Expected: 全 PASS (mini-VM 真跑 capture→auto 链, 结构断言守 ref-fail 分支)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/config/operation/02_develop/develop_execute.yaml eit_ptlc/tests/test_develop_auto_drain_flow_offline.py eit_ptlc/tests/test_develop_four_stage_offline.py
git commit -m "feat(develop): execute 起点自动采集参考图 + ref 失败退化人工门 (spec 0716 §3.7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: UI reason 文案映射

**Files:**
- Create: `eit_ptlc/web/src/wlStatus.js`
- Modify: `eit_ptlc/web/src/components/WaterLevelGrid.vue` (cells 的 status 行)
- Modify: `eit_ptlc/web/src/components/WaterLevelChannel.vue` (readout 信号行)

**Interfaces:**
- Consumes: snapshot 通道 `reason` 取值 no_signal/frame_dark/no_roi/empty_roi (Task 3 加入 frame_dark)。
- Produces: `export function wlReasonLabel(reason: string): string`。

- [ ] **Step 1: 新建 wlStatus.js**

```js
// 液位 reason → 用户可读状态 (与 waterlevel_detector/service 的 reason 口径对齐)。
// no_signal 是"前沿未进 ROI"的物理正常等待态 — 旧 UI 原样打出 reason/"无信号"造成误解
// (2026-07-16 诊断: 用户把正常等待读成检测失效)。
const REASON_LABELS = {
  no_signal: '等待前沿',
  frame_dark: '画面过暗',
  no_roi: '未标定 ROI',
  empty_roi: 'ROI 越界',
}

export function wlReasonLabel(reason) {
  return REASON_LABELS[reason] || (reason ? `无效 (${reason})` : '无信号')
}
```

- [ ] **Step 2: 两组件接入**

`WaterLevelGrid.vue`: `import { wlReasonLabel } from '../wlStatus'`;cells 的 status 行改为:

```js
      status: d
        ? (d.valid
            ? (d.has_ref ? '检测中' : '检测中 (无参考)')
            : d.reachable ? wlReasonLabel(d.reason) : '不可达')
        : null,
```

`WaterLevelChannel.vue`: `import { wlReasonLabel } from '../wlStatus'`;readout 的信号行改为:

```js
    ['信号', d.valid ? '有效' : wlReasonLabel(d.reason)],
```

- [ ] **Step 3: 构建验证**

```bash
cd eit_ptlc/web && npm run build
```
Expected: `✓ built` 无错误。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/web/src/wlStatus.js eit_ptlc/web/src/components/WaterLevelGrid.vue eit_ptlc/web/src/components/WaterLevelChannel.vue
git commit -m "feat(waterlevel-ui): reason 语义化文案 — no_signal 显示等待前沿, 消除正常等待被读成检测失效 (spec 0716 §3.6)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: 全量回归 + 收尾

**Files:** 无新改动 (纯验证)。

- [ ] **Step 1: 液位全家桶 + develop 相关离线回归**

```bash
for t in test_waterlevel_trigger_offline test_waterlevel_service_offline test_waterlevel_recorder_offline test_waterlevel_frame_proxy_offline test_waterlevel_stream_proxy_offline test_waterlevel_frame_endpoint_offline test_waterlevel_observation_offline test_waterlevel_autodrain_params_offline test_waterlevel_single_writer_offline test_develop_auto_drain_flow_offline test_develop_four_stage_offline; do echo "== $t"; E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.$t || echo "!! FAIL $t"; done
```
Expected: 无 `!! FAIL` 行。

- [ ] **Step 2: (可选, 有真机录像时) 0715 时间线离线对照**

用本会话的回放脚本思路 (scratchpad `wl_replay_service_sim.py`) 重跑 `data/water_level_recordings/adhoc/ch6_20260715_182001.avi`: 修正语义下预期 — 全程 0 次 degraded (原 6 个 ≥30s invalid 窗口全部归为 waiting), T2 命中时刻不变 ±1 拍 (confirm_n=2 延迟)。

- [ ] **Step 3: 上机验证清单登记 (不在本计划内执行)**

1. auto_drain=true 全程: 无 30s 误 HITL;日志见 `[WL-trigger] CHx 参考图采集完成`。
2. 拔一路相机 USB ≥ staleness_s → degraded→HITL 仍触发。
3. 手动清参考后直接跑 execute → capture_reference 自动补齐。
4. T2 触发排液时刻与人工判断偏差记录。

---

## Self-Review (已执行)

- **Spec 覆盖**: §3.1→Task 1, §3.2→Task 1+4, §3.3→Task 2+4+5, §3.4→Task 3, §3.5→无代码 (决策为不加), §3.6→Task 6, §3.7→Task 5, §5 测试→各 Task 内嵌, §6→Task 7 Step 3。
- **类型一致**: `capture_reference` 返回 `{ok, has_ref, elapsed_s}` 在 Task 2 定义、Task 4 fake、Task 5 SeqExecutor/YAML `ref_result.ok` 三处一致;`confirm_n` 函数默认=YAML 默认=2;`frame_dark` 字符串 Task 1/3/6 一致。
- **既有测试兼容**: test_reached_t2 elapsed 4→6、front_none 语义改写、seen 字典 +confirm_n、drains 2→3、execute_events +2 节点 — 均已写入对应 Task Step 1。
