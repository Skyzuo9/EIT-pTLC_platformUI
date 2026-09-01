"""日志查询 - 加载并过滤单样品 JSONL 日志（Phase 3）。

设计原则（奥卡姆剃刀）：
- 直接从文件系统读取 ``<samples_root>/<sample_id>/logs/*.jsonl``。
- 单样品全量加载，封顶 ``MAX_ENTRIES_PER_SAMPLE`` 条，避免 UI 卡顿。
- 仅支持单样品查询；不做跨样品全局查询、不做实时刷新。
- 与未来 ``SqliteSink`` 迁移兼容：返回的 dict Schema 与
  ``core.log_persistence._entry_to_jsonl`` 完全一致
  （``ts`` / ``sample_id`` / ``event`` / ``detail`` / ``extra``）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# 加载上限：避免单样品异常日志撑爆 UI 表格
MAX_ENTRIES_PER_SAMPLE = 5000


def load_sample_logs(sample_id: str, samples_root: Path) -> list[dict]:
    """加载指定样品的全部 JSONL 日志条目。

    扫描 ``<samples_root>/<sample_id>/logs/*.jsonl``，按文件名升序逐行解析。
    文件名包含微秒级时间戳（见 ``JsonlFileSink._run_file_for_enqueue``），
    因此文件名升序等价于时间序，无需额外排序。

    达到 :data:`MAX_ENTRIES_PER_SAMPLE` 后立即返回，剩余文件不再读取。

    Args:
        sample_id: 样品 ID
        samples_root: ``data/samples`` 根目录

    Returns:
        日志条目列表；每条 dict 至少包含 ``ts`` / ``event`` / ``detail`` 字段。
        目录不存在、文件不可读、JSON 行损坏时静默跳过。
    """
    logs_dir = Path(samples_root) / sample_id / "logs"
    if not logs_dir.is_dir():
        return []

    try:
        files = sorted(logs_dir.glob("*.jsonl"))
    except OSError as e:
        log.warning("[log_query] 列举日志目录失败 (%s): %s", sample_id, e)
        return []

    entries: list[dict] = []
    for f in files:
        try:
            with f.open("r", encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        entries.append(json.loads(s))
                    except json.JSONDecodeError:
                        continue
                    if len(entries) >= MAX_ENTRIES_PER_SAMPLE:
                        log.info(
                            "[log_query] %s 日志条目达到上限 %d，截断",
                            sample_id, MAX_ENTRIES_PER_SAMPLE,
                        )
                        return entries
        except OSError as e:
            log.warning("[log_query] 读取日志文件失败 %s: %s", f, e)
            continue
    return entries


def filter_logs(
    entries: list[dict],
    event_filter: Optional[str] = None,
    search_text: Optional[str] = None,
) -> list[dict]:
    """按事件类型 + 文本子串过滤日志。

    Args:
        entries: 原始日志条目（不会被修改）
        event_filter: 事件名精确匹配；``None`` / ``""`` / ``"全部"`` 表示不过滤
        search_text: 文本子串匹配（不区分大小写，跨 ``event`` / ``detail`` /
            ``extra`` 三个字段，``extra`` 以 JSON 字符串形式参与匹配）

    Returns:
        过滤后的条目（新列表，原顺序保留）。
    """
    if not entries:
        return []
    result = entries
    if event_filter and event_filter not in ("", "全部"):
        result = [e for e in result if e.get("event") == event_filter]
    if search_text:
        needle = search_text.strip().lower()
        if needle:
            def _hit(e: dict) -> bool:
                if needle in str(e.get("event", "")).lower():
                    return True
                if needle in str(e.get("detail", "")).lower():
                    return True
                extra = e.get("extra") or {}
                if extra:
                    try:
                        extra_str = json.dumps(extra, ensure_ascii=False)
                    except Exception:
                        extra_str = str(extra)
                    if needle in extra_str.lower():
                        return True
                return False
            result = [e for e in result if _hit(e)]
    return result


def list_unique_events(entries: list[dict]) -> list[str]:
    """提取条目中出现过的全部事件名（升序去重，用于下拉选项）。"""
    return sorted({str(e.get("event", "")) for e in entries if e.get("event")})
