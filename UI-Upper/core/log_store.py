"""
LogStore - 运行事件内存日志
============================
记录样品状态变更与关键事件，MVP 阶段纯内存存储，不持久化。

事件类型（event 字段）：
    ENQUEUED     - 样品入队
    STATE_CHANGE - 状态机变更
    VISION_OK    - 视觉分析成功
    VISION_FAIL  - 视觉分析失败
    CONFIRM_CONT - 人工确认：继续
    CONFIRM_STOP - 人工确认：终止
    DONE         - 样品完成
    ERROR        - 样品出错
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.log_persistence import LogPersistence

log = logging.getLogger(__name__)


@dataclass
class LogEntry:
    """单条日志记录。"""
    timestamp: datetime
    sample_id: str
    event: str    # 见模块头部事件类型说明
    detail: str   # 附加描述


class LogStore:
    """内存日志存储。

    使用方式：
        store = LogStore()
        store.append("S001", "ENQUEUED", "入队位置=1")
        store.append("S001", "STATE_CHANGE", "PENDING → SPOTTING")
        store.print_summary()
    """

    def __init__(self, persistence: Optional["LogPersistence"] = None) -> None:
        self._entries: list[LogEntry] = []
        self._persistence: Optional["LogPersistence"] = persistence

    def attach_persistence(self, persistence: Optional["LogPersistence"]) -> None:
        """将持久化服务注入到现有 LogStore；传 None 表示解绑（停服时调用）。幂等。"""
        self._persistence = persistence

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def append(self, sample_id: str, event: str, detail: str = "") -> None:
        """追加一条日志，同时通过 logging 输出到终端。

        若绑定了 LogPersistence，同步 enqueue 到后台写队列（零阻塞）。
        """
        entry = LogEntry(
            timestamp=datetime.now(),
            sample_id=sample_id,
            event=event,
            detail=detail,
        )
        self._entries.append(entry)
        log.info("[Log] %-12s  %-14s  %s", sample_id, event, detail)
        if self._persistence is not None:
            try:
                self._persistence.enqueue(entry)
            except Exception as e:
                # 崩溃保护：持久化失败不影响内存日志主路径
                log.error("[LogStore] persistence.enqueue 异常（已忽略）: %s", e)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_all(self) -> list[LogEntry]:
        """返回全部日志条目（按时间顺序）。"""
        return list(self._entries)

    def get_sample(self, sample_id: str) -> list[LogEntry]:
        """返回指定样品的全部日志条目。"""
        return [e for e in self._entries if e.sample_id == sample_id]

    def all_sample_ids(self) -> list[str]:
        """返回已记录过的样品 ID 列表（去重，保留入队顺序）。"""
        seen: list[str] = []
        for e in self._entries:
            if e.sample_id not in seen:
                seen.append(e.sample_id)
        return seen

    def final_state(self, sample_id: str) -> Optional[str]:
        """返回指定样品最后一条 DONE/ERROR 事件的 detail，若无则返回 None。"""
        for entry in reversed(self._entries):
            if entry.sample_id == sample_id and entry.event in ("DONE", "ERROR"):
                return entry.detail
        return None

    def __len__(self) -> int:
        """返回日志条目总数。"""
        return len(self._entries)

    # ------------------------------------------------------------------
    # 终端摘要
    # ------------------------------------------------------------------

    def print_summary(self) -> None:
        """在终端打印所有样品的最终状态汇总。"""
        ids = self.all_sample_ids()
        print()
        print("=" * 50)
        print(f"  队列执行摘要（共 {len(ids)} 个样品）")
        print("=" * 50)
        for sid in ids:
            state = self.final_state(sid) or "UNKNOWN"
            print(f"  {sid:<16} {state}")
        print("=" * 50)
