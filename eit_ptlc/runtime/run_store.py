"""运行记录存储 (执行历史 + 回放)
==================================
功能:
    把 operation 引擎发出的运行事件 (operation_start / step_start / step_done /
    operation_done|failed) 持久化到 SQLite, 提供历史列表与单次运行的有序事件序列.
    设计取向: 有序事件日志即回放源 (历史 = 事件日志, 回放 = 重放), 与实时监视器同源.
    仅用标准库 sqlite3, 不引入额外依赖.

表结构:
    runs(run_id PK, operation, label, status, started_at, finished_at, message)
    run_events(id PK AUTOINCREMENT, run_id, ts, type, payload)  -- payload = json(event); 按 id 升序即时间序
    stat_baselines(operation PK, since_ts, updated_at)  -- 统计起算点; 只约束统计读侧, 不删运行记录

线程模型:
    on_event 由引擎协程 (事件循环线程) 调用, 查询由异步端点调用; 用 check_same_thread=False
    + 进程内锁串行化, 避免跨线程与并发写问题.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# 终态事件类型 -> 运行终态 (兜底, 优先用事件自带 status)
_TERMINAL_STATUS = {"operation_done": "DONE", "operation_failed": "FAILED"}


class RunStore:
    """运行记录的 SQLite 存储."""

    def __init__(self, db_path: str | Path = ":memory:", *, max_runs: int = 1000) -> None:
        """打开 (或创建) 运行记录库.

        参数:
            db_path: SQLite 文件路径; ":memory:" 用于离线测试
            max_runs: 保留最近运行条数上限 (含事件); <=0 表示不限。超出时在下次
                      operation_start 淘汰最旧运行及其事件, 防常驻进程库无界增长。
        """
        self._path = str(db_path)
        self._max_runs = int(max_runs)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id      TEXT PRIMARY KEY,
                    operation   TEXT,
                    label       TEXT,
                    status      TEXT,
                    started_at  REAL,
                    finished_at REAL,
                    message     TEXT
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id  TEXT,
                    ts      REAL,
                    type    TEXT,
                    payload TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, id);
                CREATE TABLE IF NOT EXISTS stat_baselines (
                    operation  TEXT PRIMARY KEY,
                    since_ts   REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # 写入 (作为引擎 event_sink 之一)
    # ------------------------------------------------------------------

    def on_event(self, event: dict) -> None:
        """记录一条运行事件; 非运行事件 (无 run_id, 如 telemetry) 直接忽略."""
        run_id = event.get("run_id")
        if not run_id:
            return
        event_type = event.get("type", "")
        ts = event.get("ts")
        with self._lock:
            if event_type == "operation_start":
                # 新运行入库 (RUNNING); 同 run_id 重跑则覆盖头记录
                self._conn.execute(
                    "INSERT OR REPLACE INTO runs"
                    "(run_id, operation, label, status, started_at, finished_at, message)"
                    " VALUES (?, ?, ?, 'RUNNING', ?, NULL, '')",
                    (run_id, event.get("operation", ""), event.get("label", ""), ts),
                )
                # 同 run_id 重跑: 清掉上次残留事件, 否则 get_run 回放新旧混淆 (孤儿事件)
                self._conn.execute("DELETE FROM run_events WHERE run_id = ?", (run_id,))
                self._prune_locked()
            elif event_type in _TERMINAL_STATUS:
                # 收尾: 更新终态 (优先事件自带 status, 否则按类型兜底)
                status = event.get("status") or _TERMINAL_STATUS[event_type]
                self._conn.execute(
                    "UPDATE runs SET status = ?, finished_at = ?, message = ? WHERE run_id = ?",
                    (status, ts, event.get("message", ""), run_id),
                )
            # 始终追加到事件日志 (回放源)
            self._conn.execute(
                "INSERT INTO run_events(run_id, ts, type, payload) VALUES (?, ?, ?, ?)",
                (run_id, ts, event_type, json.dumps(event, ensure_ascii=False)),
            )
            self._conn.commit()

    def _prune_locked(self) -> None:
        """淘汰超出 max_runs 的最旧运行及其事件 (须在持锁上下文调用)."""
        if self._max_runs <= 0:
            return
        victims = self._conn.execute(
            "SELECT run_id FROM runs ORDER BY started_at DESC LIMIT -1 OFFSET ?",
            (self._max_runs,),
        ).fetchall()
        if not victims:
            return
        ids = [r["run_id"] for r in victims]
        placeholders = ",".join("?" * len(ids))
        self._conn.execute(f"DELETE FROM run_events WHERE run_id IN ({placeholders})", ids)
        self._conn.execute(f"DELETE FROM runs WHERE run_id IN ({placeholders})", ids)

    def reconcile_orphans(self) -> list[str]:
        """启动时收敛孤儿运行: 把所有 RUNNING 行判为 INTERRUPTED.

        功能:
            进程启动那一刻本进程必然没有在跑的运行 (VmController 尚未构造, 线程表为空),
            所以库里凡是 RUNNING 的行都是上一个进程留下的残留 —— 判据零误伤, 不需要
            pid/心跳/时间阈值。两种真实成因 (2026-08-14 现场取证): 单步调试停驻
            (VmStatus.STOPPED 等 resume) 后被遗弃、进程后来重启; 或动作在飞时进程被杀。
            两种情况下 VmThread._finish() 都没机会执行 —— 它只在协程栈上可达。
            同一个坑 DVR 侧早已用启动收敛堵过 (recording/store.py 的僵尸会话清理), 这里是
            runs 侧的对应物。

        finished_at 取该运行**最后一条事件的 ts** 而不是 now(): 残留可能卡了许多天,
        用 now() 会把时长统计与三维时间线跨度污染成天级 (照抄 DVR 同款做法)。

        返回:
            list[str], 被收敛的 run_id 列表 (供启动日志)
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id FROM runs WHERE status = 'RUNNING'"
            ).fetchall()
            if not rows:
                return []
            ids = [r["run_id"] for r in rows]
            self._conn.execute(
                "UPDATE runs SET status = 'INTERRUPTED',"
                " finished_at = COALESCE("
                "   (SELECT MAX(ts) FROM run_events e WHERE e.run_id = runs.run_id),"
                "   started_at),"
                " message = '后端重启时该运行仍未终结, 已判为中断'"
                " WHERE status = 'RUNNING'"
            )
            self._conn.commit()
            return ids

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_runs(self, *, limit: int = 50, status: str | None = None,
                  since: float | None = None, until: float | None = None) -> list[dict]:
        """列出运行记录 (按开始时间倒序).

        参数:
            status: 非空时按终态/RUNNING 过滤
            since/until: started_at 的半开窗口 [since, until), epoch 秒; None 不限
        """
        conds: list[str] = []
        args: list = []
        if status:
            conds.append("status = ?")
            args.append(status.strip().upper())
        if since is not None:
            conds.append("started_at >= ?")
            args.append(float(since))
        if until is not None:
            conds.append("started_at < ?")
            args.append(float(until))
        query = "SELECT * FROM runs"
        if conds:
            query += " WHERE " + " AND ".join(conds)
        query += " ORDER BY started_at DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        return [dict(row) for row in rows]

    def list_runs_by_operation(self, operation: str, *, status: str | None = "DONE",
                               limit: int = 50, since: float | None = None) -> list[dict]:
        """按流程名过滤的运行列表 (按开始时间倒序).

        功能:
            排程统计取窗口用的只读查询; runs 表被 max_runs 封顶, 全表扫描可接受,
            不加索引不改 schema.
        参数:
            operation: 流程名 (runs.operation 精确匹配)
            status: 终态过滤, 默认 DONE; None 表示不过滤
            limit: 窗口大小 (最近 N 次)
            since: 统计基线, 只取 started_at >= 该值的运行; None 表示不限
        返回:
            list[dict], 行结构同 list_runs
        """
        query = "SELECT * FROM runs WHERE operation = ?"
        args: list = [operation]
        if status:
            query += " AND status = ?"
            args.append(status.strip().upper())
        if since is not None:
            query += " AND started_at >= ?"
            args.append(float(since))
        query += " ORDER BY started_at DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # 统计基线 (stat_baselines): 记录"从哪一刻起的运行才计入耗时统计"
    # 只影响统计读侧, 不删除任何运行记录; 执行历史与回放始终完整
    # ------------------------------------------------------------------

    def get_stat_baselines(self) -> dict[str, float]:
        """读取全部统计基线.

        返回:
            Dict[str, float], 键为流程名 ('*' 表示对所有流程生效的全局基线),
            值为基线时刻 (epoch 秒)
        """
        with self._lock:
            rows = self._conn.execute("SELECT operation, since_ts FROM stat_baselines").fetchall()
        return {row["operation"]: float(row["since_ts"]) for row in rows}

    def set_stat_baseline(self, operation: str, since_ts: float) -> None:
        """设置某流程 (或 '*' 全局) 的统计基线; 已存在则覆盖.

        参数:
            operation: 流程名, 或 '*' 表示全局基线
            since_ts: 基线时刻 (epoch 秒)
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO stat_baselines(operation, since_ts, updated_at)"
                " VALUES (?, ?, ?)",
                (operation, float(since_ts), time.time()),
            )
            self._conn.commit()

    def clear_stat_baseline(self, operation: str) -> None:
        """撤销某流程 (或 '*' 全局) 的统计基线; 不存在则无操作."""
        with self._lock:
            self._conn.execute("DELETE FROM stat_baselines WHERE operation = ?", (operation,))
            self._conn.commit()

    def clear_all_stat_baselines(self) -> None:
        """撤销全部统计基线 (恢复用全部历史运行做统计)."""
        with self._lock:
            self._conn.execute("DELETE FROM stat_baselines")
            self._conn.commit()

    def get_run(self, run_id: str) -> dict | None:
        """读取单次运行 + 其有序事件序列 (供回放); 不存在返回 None."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            events = self._conn.execute(
                "SELECT payload FROM run_events WHERE run_id = ? ORDER BY id ASC", (run_id,)
            ).fetchall()
        run = dict(row)
        run["events"] = [json.loads(e["payload"]) for e in events]
        return run

    def close(self) -> None:
        """关闭数据库连接."""
        with self._lock:
            self._conn.close()
