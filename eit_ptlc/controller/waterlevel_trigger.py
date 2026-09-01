"""液位阈值等待 (develop.wait_level 的 host 计算函数)
====================================================
职责:
    轮询 WaterLevelDetectService 快照, 等待通道 front_percent 到达阈值档 (t1/t2)。
    阈值真源在 ChannelConfig.params (trigger_percent_t2 / t1_offset), 经 detect.get_params 读。
    纯 stdlib (禁 cv2/httpx): 只消费 snapshot()/get_params() 的 dict 形状, 离线可测。

三态返回 (均为正常 DONE 结果, 由流程 if 分支消费; 优先级契约 检测 > HITL > 硬上限,
见 docs/superpowers/specs/2026-07-13-waterlevel-auto-drain-design.md):
    reached   front_percent >= 阈值, 连续 confirm_n 个**不同检测拍**命中 (去抖, 挡单帧尖峰); 优先级最高
    degraded  仅限传输/配置故障 → 流程升级 HITL, 人决定:
              · 传输类 (掉流/无效帧/暗帧/observed_at 超龄) 持续 >= staleness_s 才降级;
                最坏检测盲窗 ~2×staleness_s (超龄本身按坏帧累计)
              · 配置类 (标定缺失 no_reference / ROI 缺失 no_roi/empty_roi) 立即降级 (等不来)
    hard_cap  展开时长硬上限到 (无人介入兜底直排, 宁欠展开不过展开)

坏帧三分类 (spec 2026-07-16-waterlevel-wait-semantics-autoref §3.1): 前沿未进 ROI
(no_front) / 前沿线未成形 (front_none) 是物理正常等待态, 不算降级, 只由 hard_cap 兜底;
degraded 仅留给传输/配置故障与整区判湿伪迹 (roi_saturated)。

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


# 正常等待 (不降级): 前沿未进 ROI — 物理等待态, 只由 hard_cap 兜底。
# no_front = 流入侧湿平台幅值未起来 (analyze_front 锚定判据)。
_WAITING_REASONS = {"no_front"}
# 配置错误 (立即降级): 标定/ROI 缺失 — 等不来, 立刻升级人处理
_CONFIG_REASONS = {"no_roi", "empty_roi"}


async def wait_level(detect: Any, *, target_tank: int, stage: str,
                     staleness_s: float = 30.0, hard_cap_s: float = 3600.0,
                     poll_s: float = 2.0, confirm_n: int = 2,
                     time_fn: Callable[[], float] = time.monotonic,
                     sleep: Callable[[float], Any] = asyncio.sleep) -> dict:
    """阻塞等待通道 front_percent 到阈值档; 见模块 docstring 的三态契约。

    坏帧三分类 (spec 2026-07-16-waterlevel-wait-semantics-autoref):
      waiting   no_front / front_none — 前沿未到为正常态, 不降级, hard_cap 兜底;
      transport unreachable / stale / channel_missing / frame_dark / roi_saturated 等 —
                持续 >= staleness_s → degraded (原语义)。roi_saturated = 整条 profile 被
                抬平的照度突变伪迹, 持续不散确实该叫人来看, 故归此类;
      config    no_roi / empty_roi / 无参考图 — 等不来, 立即 degraded (reason 前缀 config:)。
    confirm_n: 连续 N 个**不同检测拍** >= 阈值才 reached (去抖, 挡单帧尖峰); hard_cap
    到点时当前采样已达阈仍按 reached 计 (检测 > 硬上限契约)。
    按 observed_at 去重是必须的: poll_s 默认 2.0s 而检测周期 = interval + 处理耗时 > 2.0s,
    同一拍必被重复读到 —— 不去重则"连续 N 拍"退化成"连续 N 次轮询", 一拍即可凑满
    (2026-07-26 真机 T2 就是被同一拍数两次骗过, 2.0s 内判 reached 触发了自动排液)。
    """
    ch = int(target_tank)
    threshold = resolve_threshold(detect.get_params(ch) or {}, str(stage))
    need = max(1, int(confirm_n))
    start = time_fn()
    bad_since: Optional[float] = None
    bad_reason = ""
    last_fp: Optional[float] = None
    last_seen_at: Optional[str] = None   # 上一次计入 streak 的检测拍时刻 (去重键)
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
            observed = chd.get("observed_at")
            # 同一检测拍被重复读到 → streak 不动 (既不加也不清), 只有新的一拍才是新证据
            if observed != last_seen_at:
                last_seen_at = observed
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
