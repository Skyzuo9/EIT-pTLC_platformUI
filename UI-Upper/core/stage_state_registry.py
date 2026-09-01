"""StageStateRegistry - 从 LogStore 事件流推导 Stage 实时状态（Phase A）

单一职责：扫 LogStore 事件，产出 {stage: StageState} 快照供 Flow Tab 卡片消费。
- idle   : 未启动或上一次已完成/故障后回到空闲
- running: STAGE_START 后、尚未 STAGE_DONE
- done   : 最近一次 STAGE_DONE(status=OK)
- error  : 最近一次 STAGE_DONE(status=ERROR/CANCELLED) 或出现 STEP_SKIPPED(reason=plc_error)
- estop  : 最近一次 STAGE_DONE(status=ESTOP)，急停导致的强制中止
          （ESTOP_DEACTIVATE 系统事件后所有工位回到 idle）

collect 子步号：从最后一条 STEP_START 的 action_id 取（与 COLLECT_SUB_STEPS 对齐）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from core import flow_events as fe
from core.log_store import LogStore


@dataclass
class StageState:
    stage: str
    state: str = "idle"           # idle / running / done / error / estop
    sample_id: Optional[str] = None
    step: Optional[int] = None    # 最后已知子步号（running/error 态保留）
    step_label: Optional[str] = None
    since: Optional[datetime] = None   # 本次 RUNNING/DONE/ERROR 开始时间戳
    duration_ms: Optional[int] = None  # done 态时的阶段累计耗时


def _kv(detail: str, key: str) -> Optional[str]:
    if not detail:
        return None
    for part in detail.split():
        if part.startswith(f"{key}="):
            return part.split("=", 1)[1]
    return None


class StageStateRegistry:
    """按需从 LogStore 推导 Stage 状态。无自身缓存，读即新鲜。

    并发安全：当多个样品同时使用同一工位时（如 S001 在 spotting 执行中，
    S002 也发出 STAGE_START），仅当 STAGE_DONE 的 sample_id 与当前持有者
    匹配时才转移状态，避免 A 样品的 DONE 错误覆盖 B 样品的 running。
    """

    def __init__(self, log_store: LogStore) -> None:
        self._log = log_store

    def snapshot(self, stages: list[str] | None = None) -> dict[str, StageState]:
        """扫一遍 LogStore，返回 {stage_name: StageState}。

        stages: 限定返回哪些工位（默认 ['collect', 'develop', 'spotting', 'scrape']）。
        """
        targets = set(stages or ["collect", "develop", "spotting", "before_photo", "scrape"])
        out: dict[str, StageState] = {s: StageState(stage=s) for s in targets}

        for entry in self._log.get_all():
            # ── SYSTEM 级事件（无 stage= 键）：在 stage 过滤前处理 ──
            if entry.event == "ESTOP_DEACTIVATE":
                # 急停解除：所有工位回归 idle（包括 estop/done/error）
                # 急停恢复意味着系统全面重置，之前的完成/故障状态不再有意义
                for s in out.values():
                    s.state = "idle"
                    s.step = None
                    s.step_label = None
                    s.duration_ms = None
                    s.sample_id = None
                    s.since = None
                continue

            # ── Stage 级事件：需要 stage= 键 ──
            stage = _kv(entry.detail, "stage")
            if not stage or stage not in targets:
                continue
            cur = out[stage]

            if entry.event == fe.STAGE_START:
                # 并发安全：仅当工位当前非 running 或同一样品时才覆盖
                # 避免 B 样品的 START 覆盖 A 样品的 running（A 的 DONE 还未到）
                if cur.state != "running" or cur.sample_id == entry.sample_id:
                    cur.state = "running"
                    cur.sample_id = entry.sample_id
                    cur.since = entry.timestamp
                    cur.step = None
                    cur.step_label = None
                    cur.duration_ms = None

            elif entry.event == fe.STAGE_DONE:
                # 并发安全：仅当 DONE 的 sample_id 与当前持有者匹配时才转移状态
                # 避免 A 样品的 DONE 覆盖 B 样品的 running
                if cur.sample_id == entry.sample_id:
                    status = _kv(entry.detail, "status") or "OK"
                    if status == "ESTOP":
                        cur.state = "estop"
                    elif status in ("ERROR", "CANCELLED"):
                        cur.state = "error"
                    else:
                        cur.state = "done"
                    cur.sample_id = entry.sample_id
                    cur.since = entry.timestamp
                    d = _kv(entry.detail, "duration_ms")
                    cur.duration_ms = int(d) if d and d.isdigit() else None
                # else: 另一个样品的 DONE，当前持有者仍在 running，忽略

            elif entry.event == fe.STEP_START and cur.state == "running":
                # 仅更新当前持有者的子步信息
                if cur.sample_id == entry.sample_id:
                    aid = _kv(entry.detail, "action_id")
                    label = _kv(entry.detail, "label")
                    try:
                        cur.step = int(aid) if aid else None
                    except ValueError:
                        cur.step = None
                    cur.step_label = label

            elif entry.event == fe.STEP_SKIPPED and cur.state == "running":
                if cur.sample_id == entry.sample_id:
                    reason = _kv(entry.detail, "reason")
                    if reason == "plc_error":
                        cur.state = "error"
                        aid = _kv(entry.detail, "action_id")
                        try:
                            cur.step = int(aid) if aid else cur.step
                        except ValueError:
                            pass

        return out
