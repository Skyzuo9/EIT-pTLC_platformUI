# 液位双阈值自动触发排液 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** develop 工位液位前沿到 T2 阈值自动触发 `develop.drain`,T1 预告时地轨/机械臂物理就位,配两层看门狗(检测降级→HITL 回落、展开时长硬上限→兜底直排),HITL 保留为默认模式。

**Architecture:** 新增 host 类动作 `develop.wait_level`(纯 stdlib 轮询函数注入 executor 的 `vision_methods` 派发管线,复用 `photoscrape.analyze` 先例),在 `develop_execute.yaml` 内用 VM 原生 `if` 按返回三态(reached/degraded/hard_cap)分支。阈值落 `ChannelConfig.params`(每通道标定层)。spec: `docs/superpowers/specs/2026-07-13-waterlevel-auto-drain-design.md`。

**Tech Stack:** Python 3 (asyncio, stdlib only for新模块), ptlc mini-VM YAML 流程, unittest 离线测试, Vue3 前端参数面板。

**测试解释器:** `"C:/ProgramData/miniforge3/python.exe"`,工作目录恒为仓库根 `E:\PHD\PKU\MoGroup\pTLC_platform\EIT_Project-Next`。

## Global Constraints

- 触发信号 = `front_percent` 单变量;不得用 `percent`(湿润面积)兜底混用。
- 阈值真源 = `ChannelConfig.params` 新字段 `trigger_percent_t2`(默认 90.0)与 `t1_offset`(默认 15.0);T1 = T2 − offset;同通道每次同阈值(D_f-常量前提)。
- `auto_drain` 旋钮默认 **false**(manual/HITL 原样);上机验证前不得翻默认。
- 触发优先级:**检测算法 > HITL > 硬上限**;degraded 升级 HITL 后硬上限不再自动开火(结构保证:wait_level 已返回,人确认门无超时)。
- 排液恒走 `develop.drain`(PLC L2 code 50)+ ActionExecutor/VM;禁止 raw PLC write 替代(既有 test_drain_boundary 守卫)。
- 新模块 `waterlevel_trigger.py` 顶层**禁 cv2/httpx 依赖**(只消费 snapshot/get_params 的 dict 形状,离线可测)。
- 地轨移动只经 `rail_move_safe`(自带 P1 安全门);原子动作不嵌地轨。
- 编辑流程 YAML 直接改文件提交,不经 web 编辑器(整体 PUT 回写会剥光注释);设计知识写进 `op: comment` 节点。
- 每个 task 结束提交一次;commit message 中文,格式仿仓库近期提交(`feat(scope): ...`)。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `eit_ptlc/controller/waterlevel_detector.py` | Modify | `WaterLevelDetectParams` 加 2 阈值字段 |
| `eit_ptlc/controller/waterlevel_store.py` | Modify | 阈值字段持久化往返 |
| `eit_ptlc/controller/waterlevel_service.py` | Modify | `get_params`/`update_params` 暴露阈值字段 |
| `eit_ptlc/controller/waterlevel_trigger.py` | Create | `wait_level` 轮询核心(纯 stdlib) |
| `eit_ptlc/action/executor.py` | Modify | kind `host` 路由到 `_exec_vision` 派发 |
| `eit_ptlc/config/actions/02_develop/waterlevel.yaml` | Create | `develop.wait_level` 动作声明 |
| `eit_ptlc/runtime/bootstrap.py` | Modify | `vision_methods` 注入 `wait_level` |
| `eit_ptlc/config/operation/02_develop/develop_standby.yaml` | Create | T1 物理就位 helper 流程 |
| `eit_ptlc/config/operation/02_develop/develop_execute.yaml` | Modify | auto/manual 双分支 |
| `eit_ptlc/config/operation/02_develop/develop_cycle.yaml` | Modify | resources 补 `station:rail` |
| `eit_ptlc/web/src/components/WaterLevelChannel.vue` | Modify | 参数面板加 2 阈值输入 |
| `eit_ptlc/tests/test_waterlevel_trigger_offline.py` | Create | trigger 核心 + executor host 派发测试 |
| `eit_ptlc/tests/test_develop_auto_drain_flow_offline.py` | Create | VM 级 auto 分支集成测试 |
| `eit_ptlc/tests/test_develop_four_stage_offline.py` | Modify | YAML 契约断言更新 + 新契约 |
| `docs/液位自动排液_P0实验手册_20260713.md` | Create | 上机 P0 实验步骤 |

---

### Task 1: 阈值字段落 ChannelConfig.params(dataclass + store + service)

**Files:**
- Modify: `eit_ptlc/controller/waterlevel_detector.py`(`WaterLevelDetectParams` dataclass,约 line 50-60)
- Modify: `eit_ptlc/controller/waterlevel_store.py`(`_params_to_dict` / `_params_from_native`)
- Modify: `eit_ptlc/controller/waterlevel_service.py`(`update_params` 的 key 元组、`get_params` 返回 dict)
- Test: `eit_ptlc/tests/test_waterlevel_autodrain_params_offline.py`(Create)

**Interfaces:**
- Consumes: 既有 `WaterLevelDetectParams` / `save_channel_configs` / `load_channel_configs` / `WaterLevelDetectService.get_params(ch) -> dict` / `.update_params(ch, params: dict) -> bool`。
- Produces: `params` dict 里新增键 `trigger_percent_t2: float`(默认 90.0)与 `t1_offset: float`(默认 15.0),经 `get_params` 可读、`update_params` 可写、JSON 持久化可往返。Task 2 的 `resolve_threshold` 依赖这两个键名。

- [ ] **Step 1: 写失败测试**

新建 `eit_ptlc/tests/test_waterlevel_autodrain_params_offline.py`:

```python
"""离线单测: 液位自动排液阈值字段 (trigger_percent_t2 / t1_offset) 的参数面.

覆盖: dataclass 默认值 / store JSON 往返 / 旧文件缺字段回退默认 / service get\update_params 暴露.
运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_autodrain_params_offline
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.waterlevel_detector import WaterLevelDetectParams  # noqa: E402
from eit_ptlc.controller.waterlevel_store import (  # noqa: E402
    ChannelConfig,
    default_configs,
    load_channel_configs,
    save_channel_configs,
)


class ThresholdParamsTests(unittest.TestCase):
    def test_dataclass_defaults(self) -> None:
        p = WaterLevelDetectParams()
        self.assertEqual(p.trigger_percent_t2, 90.0)
        self.assertEqual(p.t1_offset, 15.0)

    def test_store_round_trip(self) -> None:
        cfgs = default_configs()
        cfgs[3].params.trigger_percent_t2 = 82.5
        cfgs[3].params.t1_offset = 12.0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calib.json"
            save_channel_configs(path, cfgs)
            loaded = load_channel_configs(path)
        self.assertEqual(loaded[3].params.trigger_percent_t2, 82.5)
        self.assertEqual(loaded[3].params.t1_offset, 12.0)
        # 未改的通道保持默认
        self.assertEqual(loaded[1].params.trigger_percent_t2, 90.0)

    def test_old_file_without_fields_falls_back_to_defaults(self) -> None:
        # 旧格式文件 (无新字段) 加载后回退 dataclass 默认, 不炸
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calib.json"
            path.write_text(
                '{"2": {"calib": {"rotation_angle_deg": 0.0, "roi_bbox": null, '
                '"flow_direction": "left_to_right"}, "params": {"roi_crop_x": 0.1, '
                '"roi_crop_y": 0.1, "blur_ksize": 5, "diff_threshold": 3.0, '
                '"wet_pixel_threshold": 10.0, "front_ratio_level": 0.5}}}',
                encoding="utf-8")
            loaded = load_channel_configs(path)
        self.assertEqual(loaded[2].params.trigger_percent_t2, 90.0)
        self.assertEqual(loaded[2].params.t1_offset, 15.0)


class ServiceParamsSurfaceTests(unittest.TestCase):
    def _make_service(self):
        from eit_ptlc.controller.waterlevel_service import WaterLevelDetectService
        return WaterLevelDetectService("127.0.0.1", 8080, config_path=None)

    def test_get_params_exposes_thresholds(self) -> None:
        svc = self._make_service()
        params = svc.get_params(1)
        self.assertEqual(params["trigger_percent_t2"], 90.0)
        self.assertEqual(params["t1_offset"], 15.0)

    def test_update_params_sets_thresholds(self) -> None:
        svc = self._make_service()
        ok = svc.update_params(1, {"trigger_percent_t2": 75.0, "t1_offset": 10.0}, save=False)
        self.assertTrue(ok)
        params = svc.get_params(1)
        self.assertEqual(params["trigger_percent_t2"], 75.0)
        self.assertEqual(params["t1_offset"], 10.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_autodrain_params_offline`
Expected: FAIL —— `AttributeError: 'WaterLevelDetectParams' object has no attribute 'trigger_percent_t2'` 及 KeyError 若干。

- [ ] **Step 3: 实现**

`eit_ptlc/controller/waterlevel_detector.py` 的 `WaterLevelDetectParams` dataclass(现有末字段 `front_ratio_level: float = 0.5`)之后追加两个字段:

```python
    # 自动排液触发阈值 (front_percent, 0~100; 每通道标定层真源 — D_f 常量前提, 见
    # docs/superpowers/specs/2026-07-13-waterlevel-auto-drain-design.md)
    trigger_percent_t2: float = 90.0   # T2: 命中即自动 develop.drain
    t1_offset: float = 15.0           # T1 = T2 - offset: 预告 (物理就位)
```

`eit_ptlc/controller/waterlevel_store.py` 两处:

`_params_to_dict` 返回 dict 追加两行:

```python
        "trigger_percent_t2": p.trigger_percent_t2,
        "t1_offset": p.t1_offset,
```

`_params_from_native` 构造追加两行(旧文件缺键回退 `base` 默认,与既有字段同法):

```python
        trigger_percent_t2=float(d.get("trigger_percent_t2", base.trigger_percent_t2)),
        t1_offset=float(d.get("t1_offset", base.t1_offset)),
```

`eit_ptlc/controller/waterlevel_service.py` 两处:

`update_params` 的 key 元组(现为 `("roi_crop_x", "roi_crop_y", "blur_ksize", "diff_threshold", "wet_pixel_threshold", "front_ratio_level")`)追加 `"trigger_percent_t2", "t1_offset"`。

`get_params` 返回 dict 追加两行:

```python
            "trigger_percent_t2": p.trigger_percent_t2,
            "t1_offset": p.t1_offset,
```

注意:香橙派迁移路径 `_from_orangepi_entry` **不改**(香橙派无对应字段,构造时走 dataclass 默认,天然正确)。

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_autodrain_params_offline`
Expected: PASS(5 个用例)

- [ ] **Step 5: 回归既有液位套件**

Run:
```bash
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_store_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_service_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_tune_offline
```
Expected: 全 PASS(若某文件对 `get_params` 的键集合做了**相等**断言,把新键补进期望集;只许补集合,不许删断言)。

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/controller/waterlevel_detector.py eit_ptlc/controller/waterlevel_store.py eit_ptlc/controller/waterlevel_service.py eit_ptlc/tests/test_waterlevel_autodrain_params_offline.py
git commit -m "feat(waterlevel): 阈值字段 trigger_percent_t2/t1_offset 落 ChannelConfig.params — 每通道标定层真源, 旧文件缺键回退默认"
```

---

### Task 2: wait_level 轮询核心(waterlevel_trigger.py)

**Files:**
- Create: `eit_ptlc/controller/waterlevel_trigger.py`
- Test: `eit_ptlc/tests/test_waterlevel_trigger_offline.py`(Create;本 task 只写 trigger 核心用例,executor 派发用例在 Task 3 追加到同文件)

**Interfaces:**
- Consumes: Task 1 的 `get_params(ch)` 键 `trigger_percent_t2`/`t1_offset`;`WaterLevelDetectService.snapshot()` 形状 `{"channels": {ch: {"front_percent", "valid", "reachable", "reason", "observed_at", ...}}}`(见 `waterlevel_service.py:314`)。
- Produces: `async def wait_level(detect, *, target_tank: int, stage: str, staleness_s: float = 30.0, hard_cap_s: float = 3600.0, poll_s: float = 2.0, time_fn=time.monotonic, sleep=asyncio.sleep) -> dict`,返回 `{"status": "reached"|"degraded"|"hard_cap", "front_percent": float|None, "threshold": float, "stage": str, "elapsed_s": float, "reason": str}`;阈值未配置/非法抛 `ValueError`。Task 3 bootstrap 与 Task 4 流程分支按此契约消费。

- [ ] **Step 1: 写失败测试**

新建 `eit_ptlc/tests/test_waterlevel_trigger_offline.py`:

```python
"""离线单测: 液位阈值等待核心 (waterlevel_trigger.wait_level) + host 动作派发.

全部假时钟/假检测服务, 无相机无 PLC 无真实 sleep.
运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_trigger_offline
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.waterlevel_trigger import resolve_threshold, wait_level  # noqa: E402


class FakeClock:
    """假单调钟: sleep 即推进, 测试零等待."""

    def __init__(self) -> None:
        self.t = 0.0

    def time(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += float(seconds)


def _chan(front_percent, *, valid=True, reachable=True, reason="", age_s=0.0) -> dict:
    observed = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {"front_percent": front_percent, "valid": valid, "reachable": reachable,
            "reason": reason, "observed_at": observed.isoformat()}


class FakeDetect:
    """假检测服务: 依次吐 frames (最后一帧驻留), get_params 返回固定阈值."""

    def __init__(self, frames, params=None) -> None:
        self._frames = list(frames)
        self._params = dict(params or {"trigger_percent_t2": 80.0, "t1_offset": 15.0})

    def get_params(self, channel: int) -> dict:
        return dict(self._params)

    def snapshot(self) -> dict:
        frame = self._frames.pop(0) if len(self._frames) > 1 else self._frames[0]
        channels = {} if frame is None else {1: frame}
        return {"channels": channels, "active": [1], "reachable_any": True}


def _run(coro):
    return asyncio.run(coro)


class ResolveThresholdTests(unittest.TestCase):
    def test_t2_and_t1(self) -> None:
        params = {"trigger_percent_t2": 80.0, "t1_offset": 15.0}
        self.assertEqual(resolve_threshold(params, "t2"), 80.0)
        self.assertEqual(resolve_threshold(params, "t1"), 65.0)

    def test_unconfigured_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_threshold({"trigger_percent_t2": 0.0, "t1_offset": 0.0}, "t2")
        with self.assertRaises(ValueError):
            resolve_threshold({"trigger_percent_t2": 10.0, "t1_offset": 20.0}, "t1")


class WaitLevelTests(unittest.TestCase):
    def _wait(self, detect, clock, **kw):
        kw.setdefault("target_tank", 1)
        kw.setdefault("stage", "t2")
        kw.setdefault("staleness_s", 6.0)
        kw.setdefault("hard_cap_s", 100.0)
        kw.setdefault("poll_s", 2.0)
        return _run(wait_level(detect, time_fn=clock.time, sleep=clock.sleep, **kw))

    def test_reached_t2(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(60.0), _chan(75.0), _chan(82.0)])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "reached")
        self.assertEqual(res["front_percent"], 82.0)
        self.assertEqual(res["threshold"], 80.0)
        self.assertEqual(res["elapsed_s"], 4.0)   # 2 次 sleep(2s) 后第三帧命中

    def test_reached_t1_uses_offset(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(70.0)])
        res = self._wait(detect, clock, stage="t1")
        self.assertEqual(res["status"], "reached")
        self.assertEqual(res["threshold"], 65.0)

    def test_degraded_unreachable(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(50.0, reachable=False)])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "unreachable")
        self.assertGreaterEqual(res["elapsed_s"], 6.0)

    def test_degraded_front_none(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(None)])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "front_none")

    def test_degraded_stale_observed_at(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(50.0, age_s=999.0)])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "degraded")
        self.assertTrue(res["reason"].startswith("stale:"))

    def test_degraded_channel_missing(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([None])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["reason"], "channel_missing")

    def test_bad_streak_resets_on_recovery(self) -> None:
        # 4s 坏 + 恢复 + 再坏: 不累计跨段, 恢复后从零重计 → 先命中阈值
        clock = FakeClock()
        detect = FakeDetect([_chan(50.0, reachable=False), _chan(50.0, reachable=False),
                             _chan(60.0), _chan(85.0)])
        res = self._wait(detect, clock)
        self.assertEqual(res["status"], "reached")

    def test_hard_cap(self) -> None:
        clock = FakeClock()
        detect = FakeDetect([_chan(50.0)])
        res = self._wait(detect, clock, hard_cap_s=10.0)
        self.assertEqual(res["status"], "hard_cap")
        self.assertEqual(res["front_percent"], 50.0)
        self.assertGreaterEqual(res["elapsed_s"], 10.0)

    def test_hard_cap_zero_immediate(self) -> None:
        # T2 段剩余预算被扣到 0: 首轮即 hard_cap (兜底直排), 但已到阈值优先 reached
        clock = FakeClock()
        res = self._wait(FakeDetect([_chan(50.0)]), clock, hard_cap_s=0.0)
        self.assertEqual(res["status"], "hard_cap")
        clock2 = FakeClock()
        res2 = self._wait(FakeDetect([_chan(85.0)]), clock2, hard_cap_s=0.0)
        self.assertEqual(res2["status"], "reached")   # 检测 > 硬上限


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_trigger_offline`
Expected: FAIL —— `ModuleNotFoundError: No module named 'eit_ptlc.controller.waterlevel_trigger'`

- [ ] **Step 3: 实现 waterlevel_trigger.py**

新建 `eit_ptlc/controller/waterlevel_trigger.py`(完整文件):

```python
"""液位阈值等待 (develop.wait_level 的 host 计算函数)
====================================================
职责:
    轮询 WaterLevelDetectService 快照, 等待通道 front_percent 到达阈值档 (t1/t2)。
    阈值真源在 ChannelConfig.params (trigger_percent_t2 / t1_offset), 经 detect.get_params 读。
    纯 stdlib (禁 cv2/httpx): 只消费 snapshot()/get_params() 的 dict 形状, 离线可测。

三态返回 (均为正常 DONE 结果, 由流程 if 分支消费; 优先级契约 检测 > HITL > 硬上限,
见 docs/superpowers/specs/2026-07-13-waterlevel-auto-drain-design.md):
    reached   front_percent >= 阈值 (每轮先判, 优先级最高)
    degraded  检测降级 (掉流/无效/前沿无 / observed_at 超龄) 持续 >= staleness_s
              → 流程升级 HITL, 人决定; 最坏检测盲窗 ~2×staleness_s (超龄本身按坏帧累计)
    hard_cap  展开时长硬上限到 (无人介入兜底直排, 宁欠展开不过展开)

取消语义: 轮询用注入的 sleep (默认 asyncio.sleep), VmController terminate 的 task.cancel
会经 CancelledError 自然穿透, 无需额外钩子。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

STATUS_REACHED = "reached"
STATUS_DEGRADED = "degraded"
STATUS_HARD_CAP = "hard_cap"


def resolve_threshold(params: dict, stage: str) -> float:
    """由通道 params 解出该档阈值 (t1 = t2 - offset); 未配置/非法抛 ValueError。"""
    t2 = float(params.get("trigger_percent_t2") or 0.0)
    offset = float(params.get("t1_offset") or 0.0)
    threshold = t2 if stage == "t2" else t2 - offset
    if not 0.0 < threshold <= 100.0:
        raise ValueError(
            f"液位触发阈值未配置或非法: stage={stage} t2={t2} offset={offset} → {threshold}")
    return threshold


def _observed_age_s(observed_at: Optional[str]) -> Optional[float]:
    """observed_at (UTC ISO) 距今秒数; 缺失/不可解析 → None (按坏帧处理)。"""
    if not observed_at:
        return None
    try:
        observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return max(0.0, (datetime.now(timezone.utc) - observed).total_seconds())


async def wait_level(detect: Any, *, target_tank: int, stage: str,
                     staleness_s: float = 30.0, hard_cap_s: float = 3600.0,
                     poll_s: float = 2.0,
                     time_fn: Callable[[], float] = time.monotonic,
                     sleep: Callable[[float], Any] = asyncio.sleep) -> dict:
    """阻塞等待通道 front_percent 到阈值档; 见模块 docstring 的三态契约。

    time_fn/sleep 可注入 (测试假时钟); 生产走默认 monotonic + asyncio.sleep。
    """
    ch = int(target_tank)
    threshold = resolve_threshold(detect.get_params(ch) or {}, str(stage))
    start = time_fn()
    bad_since: Optional[float] = None
    bad_reason = ""
    last_fp: Optional[float] = None

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
        if chd is None:
            bad_reason = "channel_missing"
        elif not chd.get("reachable", False):
            bad_reason = "unreachable"
        elif not chd.get("valid", False):
            bad_reason = f"invalid:{chd.get('reason') or ''}"
        elif chd.get("front_percent") is None:
            bad_reason = "front_none"
        else:
            age = _observed_age_s(chd.get("observed_at"))
            if age is None or age > staleness_s:
                bad_reason = f"stale:{age}"
            else:
                fp = float(chd["front_percent"])

        if fp is None:
            bad_since = now if bad_since is None else bad_since
            if now - bad_since >= staleness_s:
                return _result(STATUS_DEGRADED)
        else:
            bad_since = None
            bad_reason = ""
            last_fp = fp
            if fp >= threshold:
                return _result(STATUS_REACHED)

        if now - start >= hard_cap_s:
            return _result(STATUS_HARD_CAP)
        await sleep(poll_s)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_trigger_offline`
Expected: PASS(11 个用例)

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/waterlevel_trigger.py eit_ptlc/tests/test_waterlevel_trigger_offline.py
git commit -m "feat(waterlevel): wait_level 阈值等待核心 — 三态 reached/degraded/hard_cap, 假时钟可注入, 纯 stdlib"
```

---

### Task 3: host 动作接线(executor 路由 + 动作 YAML + bootstrap 注入)

**Files:**
- Modify: `eit_ptlc/action/executor.py:119-120`(kind 派发处)
- Create: `eit_ptlc/config/actions/02_develop/waterlevel.yaml`
- Modify: `eit_ptlc/runtime/bootstrap.py:315-319`(`vision_methods` dict)
- Test: `eit_ptlc/tests/test_waterlevel_trigger_offline.py`(追加 executor 派发测试类)

**Interfaces:**
- Consumes: Task 2 的 `wait_level(detect, **kwargs)`;`ActionExecutor._exec_vision`(method 派发 + result dict 透传);`ActionRegistry.load(actions_dir)`。
- Produces: 动作名 `develop.wait_level`(kind `host`, method `wait_level`),参数 `target_tank`(int, 1-8, 必填)、`stage`(enum t1/t2, 必填)、`staleness_s`(float, 默认 30.0)、`hard_cap_s`(float, 默认 3600.0, min 0);执行返回 `ActionResult.result` = wait_level 的三态 dict。Task 4 流程按此调用。

- [ ] **Step 1: 排查 kind 闭集**

Run: `grep -n "vision" eit_ptlc/action/registry.py eit_ptlc/action/models.py`
Expected: registry/models 中**没有** kind 白名单闭集(校验只按 kind 分支查必填字段)。若发现闭集(如 `KINDS = (...)` 或 `kind not in (...)` 报错),把 `"host"` 加入该集合(与 `"vision"` 并列)。

- [ ] **Step 2: 写失败测试(追加到 test_waterlevel_trigger_offline.py)**

在文件底部 `if __name__ == "__main__"` 之前追加:

```python
class HostActionDispatchTests(unittest.TestCase):
    """develop.wait_level 经 ActionRegistry + ActionExecutor (kind=host) 的派发契约."""

    @classmethod
    def setUpClass(cls) -> None:
        from eit_ptlc.action.registry import ActionRegistry
        cls.registry = ActionRegistry.load(_PKG / "config" / "actions")

    def test_action_definition(self) -> None:
        adef = self.registry.get("develop.wait_level")
        self.assertEqual(adef.kind, "host")
        self.assertEqual(adef.method, "wait_level")
        stage = adef.param("stage")
        self.assertEqual(stage.type, "enum")
        self.assertEqual(list(stage.options), ["t1", "t2"])
        tank = adef.param("target_tank")
        self.assertTrue(tank.required)
        self.assertEqual((tank.minimum, tank.maximum), (1, 8))
        self.assertEqual(adef.param("staleness_s").default, 30.0)
        self.assertEqual(adef.param("hard_cap_s").default, 3600.0)

    def test_executor_dispatches_to_injected_method(self) -> None:
        from eit_ptlc.action.executor import ActionExecutor
        from eit_ptlc.action.models import ActionStatus
        seen = {}

        async def fake_wait_level(**kwargs):
            seen.update(kwargs)
            return {"status": "reached", "front_percent": 91.0,
                    "threshold": 90.0, "stage": kwargs["stage"],
                    "elapsed_s": 1.0, "reason": ""}

        executor = ActionExecutor(self.registry, vision_methods={"wait_level": fake_wait_level})
        res = asyncio.run(executor.execute(
            "develop.wait_level", {"target_tank": 2, "stage": "t2"}))
        self.assertIs(res.status, ActionStatus.DONE)
        self.assertEqual(res.result["status"], "reached")
        # 默认参数应随校验强转一并进 kwargs
        self.assertEqual(seen, {"target_tank": 2, "stage": "t2",
                                "staleness_s": 30.0, "hard_cap_s": 3600.0})

    def test_executor_rejects_bad_stage(self) -> None:
        from eit_ptlc.action.executor import ActionExecutor
        from eit_ptlc.action.models import ActionStatus

        async def fake_wait_level(**kwargs):  # pragma: no cover - 不应被调到
            raise AssertionError("不应派发")

        executor = ActionExecutor(self.registry, vision_methods={"wait_level": fake_wait_level})
        res = asyncio.run(executor.execute(
            "develop.wait_level", {"target_tank": 2, "stage": "t9"}))
        self.assertIs(res.status, ActionStatus.REJECTED)
```

- [ ] **Step 3: 跑测试确认失败**

Run: `"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_trigger_offline`
Expected: 新增 3 用例 FAIL —— `KeyError: 'develop.wait_level'`(动作未注册)。

- [ ] **Step 4: 实现**

(a) 新建 `eit_ptlc/config/actions/02_develop/waterlevel.yaml`(完整文件):

```yaml
# 液位阈值等待 (host kind, 上位机纯轮询, 不进 PLC L2 FSM):
# develop.wait_level 阻塞等待通道 front_percent 到阈值档 (t1/t2)。阈值真源在
# ChannelConfig.params (trigger_percent_t2 / t1_offset) — 每通道每次同阈值 (D_f 常量前提)。
# 返回三态 result.status (均为 DONE, 流程 if 分支消费):
#   reached  = front_percent >= 阈值 (检测优先级最高)
#   degraded = 检测降级 (掉流/陈旧/前沿无效 持续 >= staleness_s) → 流程升级 HITL
#   hard_cap = 展开时长硬上限 → 流程兜底直排 (宁欠展开不过展开)
# 优先级契约: 检测 > HITL > 硬上限; degraded 升级 HITL 后硬上限不再自动开火。
# 设计: docs/superpowers/specs/2026-07-13-waterlevel-auto-drain-design.md
develop.wait_level:
  kind: host
  method: wait_level
  label: 展缸-液位等待
  desc: 轮询液位检测快照, 等 front_percent 到阈值档; 返回 reached/degraded/hard_cap 三态。
  modes: []
  params:
    - {name: target_tank, type: int, required: true, min: 1, max: 8, label: 目标缸号}
    - {name: stage, type: enum, required: true, options: [t1, t2], label: 阈值档}
    - {name: staleness_s, type: float, required: false, default: 30.0, min: 4.0, max: 600.0, label: 检测降级判据 (s)}
    - {name: hard_cap_s, type: float, required: false, default: 3600.0, min: 0.0, max: 14400.0, label: 展开时长硬上限 (s)}
```

(b) `eit_ptlc/action/executor.py` kind 派发处,把:

```python
            if adef.kind == "vision":
                return await self._exec_vision(adef, coerced, rid, started)
```

改为:

```python
            if adef.kind in ("vision", "host"):
                # host = 同 vision 的注入函数 method 派发, 语义上非视觉 (如液位等待); 共用管线
                return await self._exec_vision(adef, coerced, rid, started)
```

(c) `eit_ptlc/runtime/bootstrap.py`,在 `vision_methods = {...}` dict 定义前加包装函数、dict 内加一项:

```python
    async def _wait_level(**kwargs):
        """VM develop.wait_level 入口: 液位阈值等待 (host 轮询; 服务未启用则拒绝)。
        经 app.state 惰性取服务 — 不依赖 bootstrap 内构造顺序。"""
        detect = getattr(app.state, "water_level_detect", None)
        if detect is None:
            raise ValueError("液位检测服务未启用 (water_level.enabled=false), develop.wait_level 不可用")
        from eit_ptlc.controller.waterlevel_trigger import wait_level
        return await wait_level(detect, **kwargs)

    vision_methods = {
        "generate_cnc_path": cnc_ctrl.generate_cnc_path,
        "analyze": _analyze_live,
        "capture_plate_offset": pallas_vision.capture_plate_offset,
        "wait_level": _wait_level,
    }
```

(`ValueError` 会被 `_exec_vision` 归一为 REJECTED → VM 侧 VmActionError,auto 模式下检测服务未启用即快速失败;manual 模式不受影响。)

- [ ] **Step 5: 跑测试确认通过**

Run: `"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_trigger_offline`
Expected: 全 PASS(14 个用例)

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/action/executor.py eit_ptlc/config/actions/02_develop/waterlevel.yaml eit_ptlc/runtime/bootstrap.py eit_ptlc/tests/test_waterlevel_trigger_offline.py
git commit -m "feat(action): develop.wait_level 动作 — kind host 复用 vision method 派发管线, bootstrap 惰性注入检测服务"
```

---

### Task 4: 流程改造(develop_execute 双分支 + develop_standby + 契约测试更新)

**Files:**
- Create: `eit_ptlc/config/operation/02_develop/develop_standby.yaml`
- Modify: `eit_ptlc/config/operation/02_develop/develop_execute.yaml`(整文件替换)
- Modify: `eit_ptlc/config/operation/02_develop/develop_cycle.yaml`(resources 加一行)
- Test: `eit_ptlc/tests/test_develop_four_stage_offline.py`(断言更新 + 新增)

**Interfaces:**
- Consumes: Task 3 的 `develop.wait_level` 动作契约;既有 `rail_move_safe`(input `target: INT`, 位5=展开区)、`develop.drain`、VM `if`/`field`/`call:max` 表达式、knob 机制(`io: in` + `ui:` 块)。
- Produces: `develop_execute` 新 in 变量 `auto_drain: BOOL`(默认 false, 带 ui → 旋钮);helper 流程 `develop_standby`(无输入);`develop_execute`/`develop_cycle` resources 含 `station:rail`。Task 5 的 VM 集成测试跑这些 YAML。

- [ ] **Step 1: 更新契约测试(先红)**

`eit_ptlc/tests/test_develop_four_stage_offline.py` 三处修改:

(a) `test_develop_phase_actions_preserve_cycle_order` 中 execute 段断言,把:

```python
        execute_events = _events(self.docs["develop_execute"])
        self.assertEqual(
            [(kind, name) for kind, name, _ in execute_events],
            [
                ("call", "develop.drain"),
            ],
        )
```

改为(`_walk` 深度优先:auto 分支的 wait/standby/wait/drain 在前,manual else 分支的 drain 在后):

```python
        execute_events = _events(self.docs["develop_execute"])
        self.assertEqual(
            [(kind, name) for kind, name, _ in execute_events],
            [
                ("call", "develop.wait_level"),      # auto: T1 等待
                ("run_script", "develop_standby"),   # auto: T1 命中物理就位
                ("call", "develop.wait_level"),      # auto: T2 等待
                ("call", "develop.drain"),           # auto: 排液 (reached/hard_cap/人已确认)
                ("call", "develop.drain"),           # manual else: HITL 后排液
            ],
        )
```

(b) 类尾追加三个新测试方法:

```python
    def test_wait_level_action_contract(self) -> None:
        adef = self.actions["develop.wait_level"]
        self.assertEqual(adef.kind, "host")
        self.assertEqual(adef.method, "wait_level")
        stage = adef.param("stage")
        self.assertEqual(list(stage.options), ["t1", "t2"])
        tank = adef.param("target_tank")
        self.assertTrue(tank.required)
        self.assertEqual((tank.minimum, tank.maximum), (1, 8))

    def test_auto_drain_knob_defaults_off(self) -> None:
        # 上机验证前 auto_drain 必须默认 false (spec Global Constraint); ui 块使其成为运行前旋钮
        doc = self.docs["develop_execute"]
        var = next(v for v in doc["vars"] if v["name"] == "auto_drain")
        self.assertEqual(var["type"], "BOOL")
        self.assertEqual(var["io"], "in")
        self.assertIs(var["default"], False)
        self.assertIsInstance(var.get("ui"), dict)

    def test_auto_branch_error_paths(self) -> None:
        # degraded → HITL 确认门在 auto 分支内; execute 声明 rail/robot 资源 (standby 用)
        doc = self.docs["develop_execute"]
        prompts = [
            str((node.get("prompt") or {}).get("lit", ""))
            for node in _walk(doc.get("body")) if node.get("op") == "human"
        ]
        self.assertTrue(any("液位检测异常" in p for p in prompts))
        self.assertTrue(any("展开完成" in p for p in prompts))   # manual 门原样保留
        self.assertEqual(set(doc.get("resources") or []),
                         {"station:develop", "robot", "station:rail"})
        cycle = set(self.docs["develop_cycle"].get("resources") or [])
        self.assertIn("station:rail", cycle)
```

(c) `test_drain_boundary_is_l2_action_not_raw_output` 不动(prompts 检查 `开始 PLC L2 排液`,新旧两个 human 门 prompt 都含该词,自然通过)。

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_develop_four_stage_offline`
Expected: FAIL —— execute 事件序列不符 + `KeyError/StopIteration`(auto_drain 变量、develop.wait_level 未在流程)。

- [ ] **Step 3: 新建 develop_standby.yaml**

`eit_ptlc/config/operation/02_develop/develop_standby.yaml`(完整文件):

```yaml
schema: ptlc.script/v1
kind: operation
name: develop_standby
label: 展开-T1物理就位 (地轨到展开区)
ui:
  role: helper
  hidden: true
# T1 预告命中后的物理就位: 地轨提前到展开区(位5), 机械臂留在 P1 安全位待命 —
# 压缩 T2 排液完成开盖后板在蒸气/干燥环境中的取板等待。rail_move_safe 自带
# P1 安全门 (不在位即停, 操作员回位再续); 同位重复下发由 PLC 幂等吸收。
vars: []
resources:
- robot
- station:rail
body:
- op: comment
  text: 'T1 物理就位: 地轨到展开区(位5); 机械臂不预伸 (留 P1 安全位, 取板序列自带进近)'
- op: run_script
  script: rail_move_safe
  inputs:
    target:
      lit: 5
  outputs: {}
```

- [ ] **Step 4: 重写 develop_execute.yaml**

`eit_ptlc/config/operation/02_develop/develop_execute.yaml`(完整文件替换):

```yaml
schema: ptlc.script/v1
kind: operation
name: develop_execute
label: 展开-执行
ui:
  role: station_phase
  station: develop
  phase: execute
  primary: true
  order: 23
vars:
- name: tank
  scope: local
  type: INT
  io: in
  default: 1
  comment: 目标缸号 1-8
- name: auto_drain
  scope: local
  type: BOOL
  io: in
  default: false
  comment: 液位自动触发排液 (false=人工HITL门; 上机验证前默认关)
  ui:
    label: 自动排液
    group: 展开控制
- name: wl_result
  scope: local
  type: DICT
  io: var
  default: {}
  comment: develop.wait_level 返回 (status/front_percent/threshold/elapsed_s)
resources:
- station:develop
- robot
- station:rail
body:
- op: comment
  text: "execute: 展开等待 + 排液闭环。auto_drain=true 走液位双阈值自动触发 (T1物理就位 / T2自动排液), false 保持人工 HITL 门。优先级: 检测 > HITL > 硬上限 (spec 2026-07-13-waterlevel-auto-drain)。排液恒走 develop.drain (PLC L2 code 50), 由 PLC 等 Tank_Drain_Done/Tank_State=99。"
- op: if
  cond:
    var: auto_drain
  then:
  - op: comment
    text: "T1 等待: front_percent >= trigger_percent_t2 - t1_offset 即预告; degraded/hard_cap 时跳过物理就位"
  - op: call
    action: develop.wait_level
    args:
      target_tank:
        var: tank
      stage:
        lit: t1
    assign:
      var: wl_result
    mode: RUN
  - op: if
    cond:
      binop: ==
      left:
        field:
          var: wl_result
        name: status
      right:
        lit: reached
    then:
    - op: run_script
      script: develop_standby
      inputs: {}
      outputs: {}
    - op: comment
      text: "T2 等待: 硬上限 = 总预算 3600s 扣除 T1 段已耗 (max 兜零, 防负值触参数下限拒绝)"
    - op: call
      action: develop.wait_level
      args:
        target_tank:
          var: tank
        stage:
          lit: t2
        hard_cap_s:
          call: max
          args:
          - lit: 0.0
          - binop: '-'
            left:
              lit: 3600.0
            right:
              field:
                var: wl_result
              name: elapsed_s
      assign:
        var: wl_result
      mode: RUN
  - op: if
    cond:
      binop: ==
      left:
        field:
          var: wl_result
        name: status
      right:
        lit: degraded
    then:
    - op: comment
      text: "检测降级 (掉流/陈旧/前沿无效持续): 升级 HITL 人决定; 人介入后硬上限不再自动开火"
    - op: human
      kind: confirm
      on_cancel: raise
      prompt:
        lit: 液位检测异常 (数据陈旧/掉流/前沿无效), 人工确认后开始 PLC L2 排液?
  - op: comment
    text: "reached/hard_cap/人已确认 → 排液; hard_cap 为无人介入时的兜底直排 (宁欠展开不过展开)"
  - op: call
    action: develop.drain
    args:
      target_tank:
        var: tank
    mode: RUN
  else:
  - op: human
    kind: confirm
    on_cancel: raise
    prompt:
      lit: 展开完成? 确认开始 PLC L2 排液
  - op: call
    action: develop.drain
    args:
      target_tank:
        var: tank
    mode: RUN
```

- [ ] **Step 5: develop_cycle.yaml resources 补 rail**

`eit_ptlc/config/operation/02_develop/develop_cycle.yaml` 的:

```yaml
resources:
- station:develop
- robot
```

改为:

```yaml
resources:
- station:develop
- robot
- station:rail
```

(execute 段 standby 会移地轨;cycle 作为根运行时须声明持有。嵌套脚本的 resources 只在作根时生效,`ptlc_full_v2` 顶层地轨纪律不变、不改。)

- [ ] **Step 6: 跑测试确认通过**

Run:
```bash
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_develop_four_stage_offline
```
Expected: 全 PASS(`field`/`call:max` 表达式为 `schema._validate_expr` 原生支持,`schema.py:289-299` 已核实,无需改校验器)。

- [ ] **Step 7: Commit**

```bash
git add eit_ptlc/config/operation/02_develop/develop_standby.yaml eit_ptlc/config/operation/02_develop/develop_execute.yaml eit_ptlc/config/operation/02_develop/develop_cycle.yaml eit_ptlc/tests/test_develop_four_stage_offline.py
git commit -m "feat(develop): execute 双分支 — auto_drain 旋钮走 T1物理就位/T2自动排液/降级HITL/硬上限直排, manual 保持 HITL 原样"
```

---

### Task 5: VM 级集成测试(auto 分支端到端)

**Files:**
- Test: `eit_ptlc/tests/test_develop_auto_drain_flow_offline.py`(Create)

**Interfaces:**
- Consumes: Task 4 的三份 YAML(从 `config/operation` 实盘加载);`VmThread`(`executor=`, `res_gate=`, `resolve_script=`, `overrides=` 旋钮注入);`ActionResult`/`ActionStatus`;`ResourceGate`。
- Produces: 无(纯守卫)。

- [ ] **Step 1: 写测试**

新建 `eit_ptlc/tests/test_develop_auto_drain_flow_offline.py`(完整文件):

```python
"""离线集成: develop_execute auto 分支在 mini-VM 上端到端 (FakeExecutor, 实盘 YAML).

覆盖: reached→standby→reached→drain / T1 hard_cap 跳过 standby 直排 /
T2 硬上限预算扣减表达式 / manual 默认分支不含 wait_level (结构级).
human 门路径不在此跑 (需 HITL 应答机制), 由 test_develop_four_stage_offline 结构断言守卫.
运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_develop_auto_drain_flow_offline
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.models import ActionResult, ActionStatus  # noqa: E402
from eit_ptlc.operation.resources import ResourceGate  # noqa: E402
from eit_ptlc.operation.vm.state import VmStatus  # noqa: E402
from eit_ptlc.operation.vm.thread import VmThread  # noqa: E402

_OP_DIR = _PKG / "config" / "operation"


def _load(name: str) -> dict:
    for path in _OP_DIR.glob(f"*/{name}.yaml"):
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise AssertionError(f"缺流程 {name}")


class SeqExecutor:
    """假执行器: 全 DONE; develop.wait_level 依次弹出预置结果."""

    def __init__(self, wait_results) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._wait = list(wait_results)

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        params = dict(params or {})
        self.calls.append((name, params))
        result = self._wait.pop(0) if name == "develop.wait_level" else {}
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, message="ok", result=result)


def _run_execute(wait_results) -> SeqExecutor:
    docs = {n: _load(n) for n in ("develop_execute", "develop_standby", "rail_move_safe")}
    ex = SeqExecutor(wait_results)
    thread = VmThread(docs["develop_execute"], executor=ex, res_gate=ResourceGate(),
                      resolve_script=lambda n: docs[n], overrides={"auto_drain": True})
    status = asyncio.run(thread.run())
    if status is not VmStatus.DONE:
        raise AssertionError(f"运行未 DONE: {status}")
    return ex


def _names(ex: SeqExecutor) -> list[str]:
    return [c[0] for c in ex.calls]


class AutoDrainFlowTests(unittest.TestCase):
    def test_reached_then_reached_full_path(self) -> None:
        ex = _run_execute([
            {"status": "reached", "front_percent": 66.0, "threshold": 65.0,
             "stage": "t1", "elapsed_s": 100.0, "reason": ""},
            {"status": "reached", "front_percent": 81.0, "threshold": 80.0,
             "stage": "t2", "elapsed_s": 40.0, "reason": ""},
        ])
        names = _names(ex)
        # T1 → standby(P1 安全门 + 地轨位5) → T2 → 排液; 无 human 挂起
        self.assertEqual(names, ["develop.wait_level", "robot.require_anchor",
                                 "rail.move", "develop.wait_level", "develop.drain"])
        rail_args = dict(ex.calls[2][1])
        self.assertEqual(rail_args.get("Rail_Target_Position"), 5)
        # T2 硬上限 = 3600 - T1 已耗 100 (max 兜零)
        t2_args = dict(ex.calls[3][1])
        self.assertEqual(t2_args.get("stage"), "t2")
        self.assertEqual(t2_args.get("hard_cap_s"), 3500.0)

    def test_t1_hard_cap_skips_standby_and_drains(self) -> None:
        ex = _run_execute([
            {"status": "hard_cap", "front_percent": 50.0, "threshold": 65.0,
             "stage": "t1", "elapsed_s": 3600.0, "reason": ""},
        ])
        self.assertEqual(_names(ex), ["develop.wait_level", "develop.drain"])

    def test_t2_budget_never_negative(self) -> None:
        ex = _run_execute([
            {"status": "reached", "front_percent": 66.0, "threshold": 65.0,
             "stage": "t1", "elapsed_s": 3601.5, "reason": ""},
            {"status": "hard_cap", "front_percent": 66.0, "threshold": 80.0,
             "stage": "t2", "elapsed_s": 0.0, "reason": ""},
        ])
        t2_args = dict(ex.calls[3][1])
        self.assertEqual(t2_args.get("hard_cap_s"), 0.0)   # max(0, 3600-3601.5)
        self.assertEqual(_names(ex)[-1], "develop.drain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: 跑测试确认通过**

Run: `"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_develop_auto_drain_flow_offline`
Expected: PASS(3 个用例)。此测试在 Task 4 之后写,首跑即应绿;若 FAIL,按报错回修 Task 4 的 YAML(常见:表达式节点形态笔误)。

- [ ] **Step 3: 回归 VM 与旋钮套件**

Run:
```bash
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_vm_thread_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_knob_override_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_observation_offline
```
Expected: 全 PASS(observation collector 零改动,守其不回归)。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/tests/test_develop_auto_drain_flow_offline.py
git commit -m "test(develop): auto 分支 VM 级端到端离线守卫 — reached全径/hard_cap跳standby/预算扣减兜零"
```

---

### Task 6: 前端参数面板暴露两个阈值

**Files:**
- Modify: `eit_ptlc/web/src/components/WaterLevelChannel.vue`(检测参数条目表,约 line 28 附近)

**Interfaces:**
- Consumes: Task 1 的 `get_detect_param`/`set_detect_param` API(`water_level_routes.py` 已按 dict 透传,零改动);组件现有参数条目形态 `{ key, label, type: 'range', min, max, step }`。
- Produces: 面板可读写 `trigger_percent_t2` / `t1_offset`,保存走既有 `set_detect_param` + `save_detect_param` 通道。

- [ ] **Step 1: 加两个条目**

在 `WaterLevelChannel.vue` 的参数条目数组(含 `{ key: 'front_ratio_level', label: '前沿判定比例', type: 'range', min: 0.1, max: 0.9, step: 0.05 }` 的那份)末尾追加:

```js
  { key: 'trigger_percent_t2', label: 'T2触发阈值 (front%)', type: 'range', min: 1, max: 100, step: 0.5 },
  { key: 't1_offset', label: 'T1提前量 (T2−offset)', type: 'range', min: 0, max: 50, step: 0.5 },
```

(形态严格照抄既有条目;组件按 key 从 `get_detect_param` 回读、按 key 写 `set_detect_param`,数据驱动无需其他改动。)

- [ ] **Step 2: 验证**

Run: `grep -n "trigger_percent_t2\|t1_offset" eit_ptlc/web/src/components/WaterLevelChannel.vue`
Expected: 两行命中。(视觉核验留到上机联调;dev 环境 vite 热载即见,不在本计划重建 dist。)

- [ ] **Step 3: Commit**

```bash
git add eit_ptlc/web/src/components/WaterLevelChannel.vue
git commit -m "feat(web): 液位参数面板暴露 T2触发阈值/T1提前量 — 走既有 detect_param 通道"
```

---

### Task 7: P0 上机实验手册

**Files:**
- Create: `docs/液位自动排液_P0实验手册_20260713.md`

**Interfaces:**
- Consumes: 全部已落地功能;既有 `waterlevel_recorder`(`record_start/stop` 命令)、VM 事件时间戳(`vm_node_done` 携带 wait_level result)。
- Produces: 操作员可照做的上机步骤文档(不产码)。

- [ ] **Step 1: 写手册**

新建 `docs/液位自动排液_P0实验手册_20260713.md`(完整文件):

```markdown
# 液位自动排液 · P0 上机实验手册

日期: 2026-07-13
前置: 双阈值自动排液软件已落地离线绿 (spec/plan 见 docs/superpowers/)。
目的: 量化 **触发→排液序列期间的前沿净推进量** (含砂芯残液段), 反哺
`trigger_percent_t2` 提前量与 `t1_offset`; 同批采集 Rf 假设② (前沿可重复) 数据。

## 实验 A: auto 模式低阈值触发 + 全程录制 (主路)

1. 目标通道完成标定 (ROI/rotation/flow) 并捕获干板参考图。
2. 液位面板把该通道 `trigger_percent_t2` 设保守低值 (建议 50), `t1_offset` 设 10。
3. 启动该通道录制 (`record_start`), 再以 `auto_drain=true` 旋钮启动 develop_cycle
   (或单跑 develop_execute, tank=通道号)。
4. 运行结束 `record_stop`。取三个时间戳: wait_level t2 命中 (vm_node_done result),
   develop.drain 派发 (vm_node_enter), Tank_State=99 (drain DONE)。
5. 用录制帧离线跑检测 (wl_replay_tune 同源管线) 得 front_percent(t) 曲线,
   对齐时间戳读出: 触发→泵启动推进量 / 泵启动→排液完成推进量 (= 砂芯残液段)。
6. 重复 M>=10 块板 (同通道同阈值) → 该批同时是 Rf 假设② 数据
   (每块触发排液后送 scrape 拍照, 见 docs/Rf测量_真机测试与落地_数据采集清单_20260709.md)。

## 实验 B: 色素滴注交叉验证 (不依赖检测算法)

1. 在已知高度 (板上标线) 滴一滴色素。
2. 目视色素前沿到标线立即手动触发 develop.drain (HITL 门确认)。
3. 排液完成后取板, 直接量色素前沿越过标线的距离 = 触发后净推进量。
4. 与实验 A 的曲线读数互证; 差异大 → 检测标定或算法需复核。

## 判读与落数

- 净推进量换算 front_percent: Δ% = 推进 mm / ROI 长度 mm × 100。
- 设 `trigger_percent_t2 = 目标前沿% − Δ%` (提前量), `t1_offset` 取
  "机器人+地轨就位时间 × 阈值附近前沿速度" 换算的 % 再加裕量。
- 稳定复现后翻 `auto_drain` 默认值 (另行提交, 含本手册数据引用)。
- 看门狗现场演练: 拔一路相机 USB → 应在 staleness_s 内升级 HITL 门, 不静默。
```

- [ ] **Step 2: Commit**

```bash
git add "docs/液位自动排液_P0实验手册_20260713.md"
git commit -m "docs(waterlevel): P0 上机实验手册 — auto低阈值触发+录制主路 / 色素滴注交叉验证 / 落数规则"
```

---

### 收官: 全量回归

- [ ] **Step 1: 跑全部触及套件**

```bash
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_autodrain_params_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_trigger_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_develop_four_stage_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_develop_auto_drain_flow_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_store_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_service_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_waterlevel_observation_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_vm_thread_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_knob_override_offline
"C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_plc_l2_acceptance_offline
```
Expected: 全 PASS。任一 FAIL 回对应 task 修复后重跑。

- [ ] **Step 2: 汇报**

向用户汇报离线全绿 + 待上机项(P0 实验手册路径、`auto_drain` 默认仍 false)。
