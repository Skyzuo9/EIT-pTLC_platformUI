"""
LogPersistence - 事件日志异步持久化（P2-1）
==============================================
将 LogStore 的内存事件流落盘为 JSONL 文件，并预留 SQLite/aiosqlite 迁移点。

存储布局（双轨：样品归档 + 日期索引）：
    data/samples/<sample_id>/logs/run_<YYYYMMDD_HHMMSS_ffffff>.jsonl
    data/samples/_system/logs/run_<YYYYMMDD>.jsonl     # 无主事件兜底
    data/logs/by_date/<YYYYMMDD>.jsonl                 # 当日全量事件软索引

JSONL 单行 Schema（与未来 DB 表列 1:1 对齐）：
    {"ts": "ISO8601", "sample_id": "S1", "event": "STAGE_START",
     "detail": "...", "extra": {}}

写入机制：
    LogStore.append() → LogPersistence.enqueue()  ← 同步、O(1)、零阻塞
                              ↓ asyncio.Queue
                       _writer_loop (后台 task)
                              ↓ flush_interval / batch_size 触发
                       LogSink.write_batch()       ← 当前 = JsonlFileSink

并发可行性（最坏场景：100 样品同批入队 + 8 缸并发）：
    - 峰值事件率 < 50 ev/s
    - 单批 flush 涉及文件数 ≤ 10（活跃 run + _system + by_date）
    - 文件 handle 懒打开 + 写后 close，无长期持有 → 无 ulimit 风险

DB 迁移点：
    LogSink Protocol 是抽象层；未来实现 SqliteSink 替换 JsonlFileSink，
    上层 LogStore / LogPersistence 不感知差异。
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    from core.log_store import LogEntry, LogStore

log = logging.getLogger(__name__)


# ======================================================================
# 抽象 Sink 协议（DB 迁移点）
# ======================================================================


class LogSink(Protocol):
    """日志写入抽象。当前实现：JsonlFileSink；未来可替换 SqliteSink。"""

    async def write_batch(self, entries: list["LogEntry"]) -> None:
        """批量写入一组日志条目。必须保证不抛异常到调用方（内部 try/except 兜底）。"""
        ...

    async def close(self) -> None:
        """关闭 sink（清理资源）。"""
        ...


# ======================================================================
# JSONL 文件实现
# ======================================================================


def _entry_to_jsonl(entry: "LogEntry") -> str:
    """将 LogEntry 序列化为 JSONL 单行（不带换行）。"""
    return json.dumps(
        {
            "ts": entry.timestamp.isoformat(),
            "sample_id": entry.sample_id,
            "event": entry.event,
            "detail": entry.detail,
            "extra": {},
        },
        ensure_ascii=False,
    )


class JsonlFileSink:
    """JSONL 文件 sink。

    路径策略：
      - 每条 ENQUEUED 事件触发新建 run 文件（微秒级命名，避免同样品复跑冲突）
      - sample_id → 当前活跃 run 文件路径（仅路径，不持有 handle）
      - 无 ENQUEUED 头的事件 → samples/_system/logs/run_<YYYYMMDD>.jsonl
      - 全部事件同时写 logs/by_date/<YYYYMMDD>.jsonl 软索引

    Handle 策略：懒打开 + 写后 close，单批 flush 最多 ~10 个文件。
    并发：单 writer task 串行调用 write_batch，无需文件锁。
    """

    def __init__(self, samples_root: Path, by_date_root: Path) -> None:
        self._samples_root = Path(samples_root)
        self._by_date_root = Path(by_date_root)
        self._run_paths: dict[str, Path] = {}   # sample_id → 当前活跃 run 文件路径

    # -- 路径计算 --

    def _run_file_for_enqueue(self, sample_id: str, ts: datetime) -> Path:
        """ENQUEUED 事件 → 新建 run 文件路径（微秒级唯一）。"""
        fname = f"run_{ts.strftime('%Y%m%d_%H%M%S_%f')}.jsonl"
        return self._samples_root / sample_id / "logs" / fname

    def _system_file(self, ts: datetime) -> Path:
        """无主事件 → _system 兜底（按日期切片）。"""
        fname = f"run_{ts.strftime('%Y%m%d')}.jsonl"
        return self._samples_root / "_system" / "logs" / fname

    def _by_date_file(self, ts: datetime) -> Path:
        """日期索引文件路径（按 entry.timestamp.date() 切片）。"""
        fname = f"{ts.strftime('%Y%m%d')}.jsonl"
        return self._by_date_root / fname

    def _route_target(self, entry: "LogEntry") -> Path:
        """路由 entry 到样品 run 文件或 _system 兜底。"""
        # ENQUEUED 触发新建 run 文件并更新映射
        if entry.event == "ENQUEUED":
            new_path = self._run_file_for_enqueue(entry.sample_id, entry.timestamp)
            self._run_paths[entry.sample_id] = new_path
            return new_path
        # 已有活跃 run 文件 → 写入
        if entry.sample_id in self._run_paths:
            return self._run_paths[entry.sample_id]
        # 无主事件 → _system 兜底
        return self._system_file(entry.timestamp)

    # -- 实际 I/O --

    @staticmethod
    def _append_lines_sync(path: Path, lines: list[str]) -> None:
        """同步 append 写入（在 to_thread 中调用，避免阻塞事件循环）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        # 单批 open → 批量写 → close（懒打开 + 写后 close）
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    async def write_batch(self, entries: list["LogEntry"]) -> None:
        """批量写入一组 entries。

        实现要点：
          1. 顺序遍历保持时间序，ENQUEUED 即时更新 _run_paths 映射
          2. 按目标路径分组：每个样品 run 文件 + _system + by_date 索引
          3. 每个目标路径只 open/write/close 一次
        """
        if not entries:
            return

        # 按目标路径分组累计写入行（保持时间序）
        path_to_lines: dict[Path, list[str]] = defaultdict(list)

        for entry in entries:
            line = _entry_to_jsonl(entry)
            # 1) 路由到 run 文件 / _system
            target = self._route_target(entry)
            path_to_lines[target].append(line)
            # 2) 同时写 by_date 索引
            by_date = self._by_date_file(entry.timestamp)
            path_to_lines[by_date].append(line)

        # 单批 open/close（每个目标路径一次 I/O）
        for path, lines in path_to_lines.items():
            try:
                await asyncio.to_thread(self._append_lines_sync, path, lines)
            except Exception as e:
                log.error("[LogPersistence] 写入失败 %s: %s", path, e)
                # 写入失败仅记录，不影响其他文件

    async def close(self) -> None:
        """文件 sink 无长期 handle，无需特殊清理。"""
        self._run_paths.clear()


# ======================================================================
# 持久化服务（异步队列 + 后台 writer）
# ======================================================================


class LogPersistence:
    """异步日志持久化服务。

    生命周期：
        sink = JsonlFileSink(samples_root, by_date_root)
        persistence = LogPersistence(sink)
        await persistence.start()
        log_store.attach_persistence(persistence)
        ...
        await persistence.stop()   # drain 队列 → close sink

    并发安全：
        - enqueue() 同步，put_nowait 在单事件循环下原子
        - 单 writer task 串行 flush，无需文件锁
        - 队列满（默认 maxsize=10000）丢弃 + log.warning，绝不抛回主流程
    """

    def __init__(
        self,
        sink: LogSink,
        flush_interval: float = 0.5,
        batch_size: int = 10,
        queue_maxsize: int = 10000,
    ) -> None:
        self._sink = sink
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._queue: asyncio.Queue["LogEntry"] = asyncio.Queue(maxsize=queue_maxsize)
        self._writer_task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()
        self._dropped_count = 0

    # -- 公共 API --

    def enqueue(self, entry: "LogEntry") -> None:
        """同步入队，非阻塞。队列满则丢弃单条 + log.warning。"""
        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            self._dropped_count += 1
            # 限流告警：每丢 100 条记一次 warning，避免刷屏
            if self._dropped_count % 100 == 1:
                log.warning(
                    "[LogPersistence] 队列已满（%d/%d），累计丢弃 %d 条",
                    self._queue.qsize(), self._queue.maxsize, self._dropped_count,
                )

    async def start(self) -> None:
        """启动 writer 后台任务。幂等。"""
        if self._writer_task is not None and not self._writer_task.done():
            return
        self._stopping.clear()
        self._writer_task = asyncio.create_task(
            self._writer_loop(), name="LogPersistence._writer_loop"
        )
        log.info(
            "[LogPersistence] 启动（flush_interval=%.2fs, batch_size=%d, queue_max=%d）",
            self._flush_interval, self._batch_size, self._queue.maxsize,
        )

    async def stop(self) -> None:
        """停止 writer：触发 stopping → drain 剩余队列 → close sink。幂等。"""
        if self._writer_task is None:
            return
        self._stopping.set()
        try:
            await asyncio.wait_for(self._writer_task, timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("[LogPersistence] writer 停止超时，强制取消")
            self._writer_task.cancel()
            try:
                await self._writer_task
            except (asyncio.CancelledError, Exception):
                pass
        except Exception as e:
            log.error("[LogPersistence] writer 异常退出: %s", e)
        self._writer_task = None
        try:
            await self._sink.close()
        except Exception as e:
            log.error("[LogPersistence] sink 关闭失败: %s", e)
        if self._dropped_count > 0:
            log.warning("[LogPersistence] 进程总计丢弃 %d 条事件（队列满）", self._dropped_count)
        log.info("[LogPersistence] 已停止")

    # -- 内部 loop --

    async def _writer_loop(self) -> None:
        """后台 writer：每 flush_interval 或累积到 batch_size 即 flush。"""
        try:
            while not self._stopping.is_set():
                batch = await self._collect_batch()
                if batch:
                    try:
                        await self._sink.write_batch(batch)
                    except Exception as e:
                        # 兜底：写失败不能影响主流程
                        log.error("[LogPersistence] write_batch 失败: %s", e)
            # stopping → drain 剩余队列
            await self._drain_remaining()
        except asyncio.CancelledError:
            # 被强制取消时也尽量 drain
            try:
                await self._drain_remaining()
            except Exception:
                pass
            raise

    async def _collect_batch(self) -> list["LogEntry"]:
        """收集一批 entries：超时或达到 batch_size 即返回。"""
        batch: list["LogEntry"] = []
        try:
            # 第一条用 wait_for（带超时）
            first = await asyncio.wait_for(
                self._queue.get(), timeout=self._flush_interval
            )
            batch.append(first)
        except asyncio.TimeoutError:
            return batch
        # 后续直到 batch_size 或队列空
        while len(batch) < self._batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def _drain_remaining(self) -> None:
        """关闭前 drain 队列剩余事件，分批写入。"""
        drained: list["LogEntry"] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not drained:
            return
        # 分批刷盘
        for i in range(0, len(drained), self._batch_size):
            chunk = drained[i:i + self._batch_size]
            try:
                await self._sink.write_batch(chunk)
            except Exception as e:
                log.error("[LogPersistence] drain 写入失败: %s", e)
        log.info("[LogPersistence] drain 完成，刷盘 %d 条", len(drained))


# ======================================================================
# 启动辅助：归档过期 by_date 文件
# ======================================================================


def archive_old_by_date_files(by_date_root: Path, older_than_days: int) -> int:
    """启动时一次扫描：把 mtime 早于 N 天的 .jsonl 压缩为 .jsonl.gz。

    Returns:
        归档的文件数。
    """
    by_date_root = Path(by_date_root)
    if not by_date_root.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=older_than_days)
    archived = 0
    for f in by_date_root.glob("*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime >= cutoff:
                continue
            gz_path = f.with_suffix(".jsonl.gz")
            if gz_path.exists():
                # 已归档过，跳过
                continue
            with f.open("rb") as src, gzip.open(gz_path, "wb") as dst:
                dst.writelines(src)
            f.unlink()
            archived += 1
        except Exception as e:
            log.warning("[LogPersistence] 归档失败 %s: %s", f, e)
    if archived > 0:
        log.info("[LogPersistence] 归档 %d 个 by_date 文件（早于 %d 天）", archived, older_than_days)
    return archived


# ======================================================================
# 工厂方法（便于上层调用）
# ======================================================================


def build_default_persistence(
    samples_root: Path,
    by_date_root: Optional[Path] = None,
    flush_interval: float = 0.5,
    batch_size: int = 10,
    archive_older_than_days: int = 30,
) -> LogPersistence:
    """按默认布局构建 LogPersistence（未启动）。

    Args:
        samples_root: data/samples/ 路径
        by_date_root: data/logs/by_date/ 路径（默认 samples_root.parent/logs/by_date）
        flush_interval / batch_size: writer 调参
        archive_older_than_days: 启动时一次性归档 N 天前的 by_date 文件
    """
    samples_root = Path(samples_root)
    if by_date_root is None:
        by_date_root = samples_root.parent / "logs" / "by_date"
    # 启动前一次归档
    archive_old_by_date_files(by_date_root, archive_older_than_days)
    sink = JsonlFileSink(samples_root=samples_root, by_date_root=by_date_root)
    return LogPersistence(sink, flush_interval=flush_interval, batch_size=batch_size)
