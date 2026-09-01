"""录像会话 / 块 / 标记的落盘与检索。

设计要点:

WAL + 立即提交 (不沿用仓内既有 store 的 delete 日志写法)
    runs.db / materials.db / experiments.db 都是 journal_mode=delete。那套在本模块
    的写入速率上会 fsync 抖死, 所以这里用 WAL + synchronous=NORMAL。
    但**不**攒批提交: 块是十秒一个、标记是步骤级, 攒着省不下什么, 却会让写事务一直
    开着。sqlite 的写锁是库级的, 于是维护工具/另一个实例/一个只想看看的脚本全会撞
    "database is locked" —— 而且 busy_timeout 再长也没用, 因为持锁方压根没打算在
    超时之内提交。(这条是实测踩出来的: 攒 6 块提交一次 = 写锁最长攥 60 秒。)

块存文件、索引存库
    块是几十 KB 的二进制, 塞进 sqlite 只会让库文件膨胀且难以按天清理。索引里只放
    时间范围与路径, 按时间检索走索引, 取数据直接读文件。

会话目录自包含
    meta.json 里带通道策略快照与设备清单哈希, 整个目录拷到另一台机器即可回放。
    这台是开发机, 部署机另有其人, 所以存储根一律可配置, 绝不写死。

sessions.kind 区分真机与仿真
    仿真沙盒有独立总线, 它的事件绝不能混进真机录像 —— 事故追溯时分不清哪条是真的
    比没有录像更糟。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    started_at    REAL NOT NULL,
    ended_at      REAL,
    schema_ver    INTEGER NOT NULL,
    manifest_hash TEXT,
    note          TEXT,
    dir           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
CREATE TABLE IF NOT EXISTS chunks (
    session_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    t0         REAL NOT NULL,
    t1         REAL NOT NULL,
    path       TEXT NOT NULL,
    bytes      INTEGER NOT NULL,
    frames     INTEGER NOT NULL,
    PRIMARY KEY (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_chunks_t0 ON chunks(t0);
CREATE INDEX IF NOT EXISTS idx_chunks_t1 ON chunks(t1);
CREATE TABLE IF NOT EXISTS chunk_activity (
    session_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    active     INTEGER NOT NULL,
    stations   TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);
CREATE TABLE IF NOT EXISTS markers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    ts         REAL NOT NULL,
    kind       TEXT NOT NULL,
    run_id     TEXT,
    label      TEXT,
    payload    TEXT
);
CREATE INDEX IF NOT EXISTS idx_markers_ts ON markers(ts);
CREATE INDEX IF NOT EXISTS idx_markers_kind ON markers(kind, ts);
CREATE TABLE IF NOT EXISTS lowfreq (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    ts         REAL NOT NULL,
    type       TEXT NOT NULL,
    run_id     TEXT,
    payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lowfreq_session_ts ON lowfreq(session_id, ts);
"""

SCHEMA_VERSION = 1
_ENV_ROOT = "PTLC_RECORD_ROOT"

# 合理纪元秒的下界 (2001-09-09)。比它小的时间戳一定不是墙钟 —— 而一条这样的值写进
# chunks.t0 就会让 coverage() 的下界永久停在 1970, 前端时间轴跨度变成 56 年、seek
# 落进虚空。录制侧据此拦截, 整理侧据此清理, **只此一处定义**, 免得两边各飘各的。
MIN_PLAUSIBLE_TS = 1_000_000_000.0


def default_root() -> Path:
    """录像存储根。环境变量优先 —— 部署机的盘符与开发机不同, 不可写死。"""
    env = os.environ.get(_ENV_ROOT)
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "var" / "recordings").resolve()


@dataclass(frozen=True)
class SessionInfo:
    id: str
    kind: str
    started_at: float
    ended_at: float | None
    dir: str
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "dir": self.dir,
            "note": self.note,
        }


class RecordingStore:
    """录像索引 (sqlite, WAL) + 块文件目录。线程安全。"""

    def __init__(self, root: Path | str | None = None, *,
                 retention_days: float = 30.0,
                 max_bytes: int | None = None,
                 busy_timeout_ms: int = 15_000) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention_days = float(retention_days)
        self.max_bytes = int(max_bytes) if max_bytes else None
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.root / "index.db", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL: 允许写入与读取并发, 且提交不必每次 fsync 整个库文件
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # busy_timeout 与 WAL 是一对: WAL 让读写并发, 但两个**写**者仍会撞锁。
        # 不设超时的话第二个写者立刻抛 "database is locked" 而不是等一下再来 ——
        # 同机多进程(上位机 + 一次离线测试 + 另一个会话)同时开库是常态。
        # 维护工具会把它调到分钟级: 老版本上位机进程可能攥着写事务几十秒不放,
        # 等得起总比让人去杀进程强。
        self._conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- 会话 ---------------------------------------------------------

    def start_session(self, *, kind: str = "real", note: str = "",
                      manifest_hash: str | None = None,
                      meta: dict | None = None,
                      now: float | None = None) -> SessionInfo:
        started = float(now if now is not None else time.time())
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(started))
        day = time.strftime("%Y-%m-%d", time.localtime(started))
        session_id = f"sess_{stamp}_{kind}"
        rel = f"{day}/{session_id}"
        target = self.root / rel
        suffix = 0
        while target.exists():
            suffix += 1
            session_id = f"sess_{stamp}_{kind}_{suffix}"
            rel = f"{day}/{session_id}"
            target = self.root / rel
        target.mkdir(parents=True, exist_ok=True)

        payload = {
            "id": session_id,
            "kind": kind,
            "started_at": started,
            "schema_ver": SCHEMA_VERSION,
            "manifest_hash": manifest_hash,
            "note": note,
            **(meta or {}),
        }
        (target / "meta.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, kind, started_at, ended_at, schema_ver,"
                " manifest_hash, note, dir) VALUES (?,?,?,?,?,?,?,?)",
                (session_id, kind, started, None, SCHEMA_VERSION, manifest_hash, note, rel),
            )
            self._conn.commit()
        return SessionInfo(session_id, kind, started, None, rel, note)

    def end_session(self, session_id: str, *, now: float | None = None) -> None:
        with self._lock:
            self._conn.execute("UPDATE sessions SET ended_at=? WHERE id=?",
                               (float(now if now is not None else time.time()), session_id))
            self._conn.commit()

    # -- 写入 ---------------------------------------------------------

    def set_chunk_activity(self, session_id: str, seq: int, stations: list[str]) -> None:
        """登记某一块里"在动"的工位。

        刻意用独立表而不是给 chunks 加一列: 加列意味着对既有 index.db 做 ALTER。独立
        表用 LEFT JOIN 读, 老块自然是 NULL, 前端把 NULL 画成"未补算"而不是撒谎说
        "当时空闲" —— 后者会让人对着一段其实很忙的时间得出相反结论。
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO chunk_activity (session_id, seq, active, stations)"
                " VALUES (?,?,?,?)",
                (session_id, int(seq), len(stations),
                 json.dumps(sorted(stations), ensure_ascii=False)))
            self._conn.commit()

    def append_chunk(self, session: SessionInfo, seq: int, t0: float, t1: float,
                     blob: bytes, frames: int) -> Path:
        """写一块并登记索引, 立即提交。

        这里**不做**批量提交。块本来就是十秒一个, 攒着提交省不下任何东西, 却会让写
        事务一直开着 —— sqlite 的写锁是库级的, 于是任何第二个进程 (维护工具、另一个
        上位机实例、只是想看一眼的脚本) 都会撞 "database is locked", 且 busy_timeout
        再长也没用, 因为对方压根没打算在超时之内提交。
        顺带还少了一条尾巴: 崩溃时不会丢掉最近几块**已经写进磁盘**的索引行。
        """
        rel = f"{session.dir}/chunk_{seq:06d}.ptc"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO chunks (session_id, seq, t0, t1, path, bytes, frames)"
                " VALUES (?,?,?,?,?,?,?)",
                (session.id, int(seq), float(t0), float(t1), rel, len(blob), int(frames)),
            )
            self._conn.commit()
        return path

    def add_markers(self, session_id: str | None, markers: list[dict]) -> None:
        if not markers:
            return
        rows = [
            (session_id, float(m["ts"]), str(m.get("kind") or "event"),
             m.get("run_id"), m.get("label"),
             json.dumps(m.get("payload"), ensure_ascii=False) if m.get("payload") is not None else None)
            for m in markers if m.get("ts") is not None
        ]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT INTO markers (session_id, ts, kind, run_id, label, payload)"
                " VALUES (?,?,?,?,?,?)", rows)
            # 同样立即提交: 标记是步骤级低频事件, 攒着只会把写锁一直攥在手里
            self._conn.commit()

    def add_lowfreq(self, session_id: str | None, events: list[dict]) -> int:
        """把增量类事件原样登记进索引, 供 seek 时重建派生态。

        为什么要在块之外再存一份: 板在谁手里 / 托盘挂载 / 夹爪持握都是浏览器按事件
        历史算出来的, 关键帧里根本没有。要重建就得拿到"从会话起点到 t"的这批事件,
        而它们散落在几千个块里 —— 为几十条事件去解几千块不可行。这张表按 (会话, ts)
        建了索引, 同样的检索是一条 SQL。

        收录范围 = 非帧流且不在录制器 _DROPPABLE 里的事件, 也就是录制器承诺"一条都
        不许丢"的那批。这不是新划的线: 需要重建派生态的事件与不许丢的事件本来就是
        同一批 (见 recorder 模块 docstring)。

        参数:
            session_id: 所属会话; events: 事件原文列表
        返回:
            int, 实际写入行数
        """
        rows = [
            (session_id, float(e["ts"]), str(e.get("type") or ""), e.get("run_id"),
             json.dumps(e, ensure_ascii=False))
            for e in events
            if isinstance(e, dict) and isinstance(e.get("ts"), (int, float))
            and not isinstance(e.get("ts"), bool)
        ]
        if not rows:
            return 0
        with self._lock:
            self._conn.executemany(
                "INSERT INTO lowfreq (session_id, ts, type, run_id, payload)"
                " VALUES (?,?,?,?,?)", rows)
            self._conn.commit()
        return len(rows)

    def flush(self) -> None:
        """保留给调用方显式收口; 写路径本身已经每次提交, 这里通常是空操作。"""
        with self._lock:
            self._conn.commit()

    # -- 检索 ---------------------------------------------------------

    def list_sessions(self, *, since: float | None = None, until: float | None = None,
                      kind: str | None = None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM sessions WHERE 1=1"
        args: list = []
        if since is not None:
            sql += " AND (ended_at IS NULL OR ended_at >= ?)"
            args.append(float(since))
        if until is not None:
            sql += " AND started_at < ?"
            args.append(float(until))
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def chunks_in_range(self, t0: float, t1: float, *,
                        session_id: str | None = None) -> list[dict]:
        """与 [t0, t1) 有交集的块 (带活动度; 未补算的块 active 为 None)。

        半开区间, 与 /api/runs 的既有约定一致。
        """
        sql = ("SELECT c.*, a.active AS active, a.stations AS stations FROM chunks c"
               " LEFT JOIN chunk_activity a"
               " ON a.session_id = c.session_id AND a.seq = c.seq"
               " WHERE c.t1 >= ? AND c.t0 < ?")
        args: list = [float(t0), float(t1)]
        if session_id:
            sql += " AND c.session_id = ?"
            args.append(session_id)
        sql += " ORDER BY c.t0"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def chunk_before(self, ts: float, *, session_id: str | None = None) -> dict | None:
        """t 时刻所在或之前最近的一块 —— seek 时用它取关键帧。"""
        sql = "SELECT * FROM chunks WHERE t0 <= ?"
        args: list = [float(ts)]
        if session_id:
            sql += " AND session_id = ?"
            args.append(session_id)
        sql += " ORDER BY t0 DESC LIMIT 1"
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def read_chunk(self, rel_path: str) -> bytes:
        target = (self.root / rel_path).resolve()
        if not str(target).startswith(str(self.root.resolve())):
            raise ValueError("块路径越界")
        return target.read_bytes()

    def markers_in_range(self, t0: float, t1: float, *, kinds: list[str] | None = None,
                         limit: int = 5000) -> list[dict]:
        sql = "SELECT * FROM markers WHERE ts >= ? AND ts < ?"
        args: list = [float(t0), float(t1)]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        sql += " ORDER BY ts LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            if item.get("payload"):
                try:
                    item["payload"] = json.loads(item["payload"])
                except (TypeError, ValueError):
                    pass
            out.append(item)
        return out

    def lowfreq_before(self, session_id: str | None, ts: float, *,
                       limit: int = 20000) -> tuple[list[dict], bool]:
        """取该会话中 ts 之前(含)的增量事件, 按时间升序返回。

        **倒序取最近 limit 条再反转**, 而不是顺序取前 limit 条。派生态是"最后一次写
        赢"的锁存量, 真撞上限时该留的是最近的那批; 顺序截断留下的是最早的那批, 等于
        把最关键的近期交接全丢了, 而画面上只表现为"板莫名其妙不在手里"。

        参数:
            session_id: 限定会话 (跨会话重放没有意义: 中间隔着一次上位机重启)
            ts: 上界(含); limit: 最多返回条数
        返回:
            (事件列表, 是否被截断)
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM lowfreq WHERE session_id IS ? AND ts <= ?"
                " ORDER BY ts DESC, id DESC LIMIT ?",
                (session_id, float(ts), int(limit) + 1)).fetchall()
        truncated = len(rows) > int(limit)
        if truncated:
            rows = rows[:int(limit)]
        out = []
        for row in reversed(rows):
            try:
                out.append(json.loads(row["payload"]))
            except (TypeError, ValueError):
                continue
        return out, truncated

    def coverage(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n, MIN(t0) AS t0, MAX(t1) AS t1,"
                " COALESCE(SUM(bytes),0) AS bytes FROM chunks").fetchone()
        return {"chunks": row["n"], "t0": row["t0"], "t1": row["t1"],
                "bytes": row["bytes"]}

    # -- 保留 ---------------------------------------------------------

    def sweep_retention(self, *, now: float | None = None) -> dict:
        """按天数与总容量清理整个会话目录。

        仓里此前没有任何保留策略 (var/ 已到 1.6 GB, 单个日志 133 MB), 录像是持续
        写入的, 必须自己管住。
        """
        now = float(now if now is not None else time.time())
        cutoff = now - self.retention_days * 86400.0
        removed: list[str] = []

        with self._lock:
            stale = self._conn.execute(
                "SELECT id, dir FROM sessions WHERE started_at < ?"
                " AND (ended_at IS NOT NULL OR started_at < ?)",
                (cutoff, cutoff)).fetchall()
        for row in stale:
            self._drop_session(row["id"], row["dir"])
            removed.append(row["id"])

        if self.max_bytes:
            while True:
                total = self.coverage()["bytes"] or 0
                if total <= self.max_bytes:
                    break
                with self._lock:
                    row = self._conn.execute(
                        "SELECT id, dir FROM sessions ORDER BY started_at ASC LIMIT 1"
                    ).fetchone()
                if row is None:
                    break
                self._drop_session(row["id"], row["dir"])
                removed.append(row["id"])

        return {"removed": removed, "coverage": self.coverage()}

    def _drop_session(self, session_id: str, rel_dir: str) -> None:
        """删一个会话: **先删索引行, 再删文件**。

        顺序是有讲究的, 两种崩溃后果并不对等:
          先删行崩了 -> 剩一个无主目录, 无害, 下次 reconcile 扫掉即可;
          先删文件崩了 -> 索引里留下一堆指向空气的行, 之后每次读都 500。
        本项目已经吃过后者的亏(手工清理录像目录时 index.db 被占用删不掉, 留下 545
        行孤儿, 回放直接不可用)。
        """
        with self._lock:
            self._conn.execute("DELETE FROM chunks WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM chunk_activity WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM markers WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM lowfreq WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self._conn.commit()
        target = (self.root / rel_dir).resolve()
        if str(target).startswith(str(self.root.resolve())) and target.exists():
            shutil.rmtree(target, ignore_errors=True)

    # -- 整理 ---------------------------------------------------------

    def reconcile(self, *, deep: bool = False, active_session_id: str | None = None,
                  min_plausible_ts: float = MIN_PLAUSIBLE_TS) -> dict:
        """把索引与磁盘对齐, 返回各项计数。

        索引与文件分家是常态而非异常: 人工清理过录像目录、盘满被清、只拷了会话目录
        没拷索引、保留策略删到一半被打断。放着不管的话读路径会一直读到空气。

        deep=False (启动时用): 只做便宜的两项 —— 目录整个没了的会话、时间戳不合理的
        块行。前者每个会话一次 stat, 后者一条 SQL。
        deep=True  (人工触发): 另外逐块 stat, 清掉所有指向不存在文件的行。30 天录像
        约 26 万行, 这一趟不该在启动路径上跑。
        """
        result = {"sessions_dropped": 0, "chunks_dropped": 0,
                  "bad_ts_dropped": 0, "sessions_closed": 0}

        # ① 目录整个不见了的会话 -> 连行带标记一起丢
        with self._lock:
            rows = self._conn.execute("SELECT id, dir FROM sessions").fetchall()
        for row in rows:
            if row["id"] == active_session_id:
                continue
            if not (self.root / row["dir"]).exists():
                self._drop_session(row["id"], row["dir"])
                result["sessions_dropped"] += 1

        # ② 时间戳不合理的块行: 它们会把 coverage() 的下界拖到 1970, 整条时间轴作废
        with self._lock:
            cur = self._conn.execute("DELETE FROM chunks WHERE t0 < ?", (float(min_plausible_ts),))
            result["bad_ts_dropped"] = cur.rowcount or 0
            self._conn.commit()

        # ③ 逐块核对文件是否还在
        if deep:
            with self._lock:
                rows = self._conn.execute("SELECT session_id, seq, path FROM chunks").fetchall()
            missing = [(r["session_id"], r["seq"]) for r in rows
                       if not (self.root / r["path"]).exists()]
            if missing:
                with self._lock:
                    self._conn.executemany(
                        "DELETE FROM chunks WHERE session_id=? AND seq=?", missing)
                    self._conn.commit()
                result["chunks_dropped"] = len(missing)

        # ④ 进程被杀留下的僵尸会话: ended_at 永远是 NULL, 保留策略据此判断会一直留着
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id, MAX(c.t1) AS last_t1 FROM sessions s"
                " LEFT JOIN chunks c ON c.session_id = s.id"
                " WHERE s.ended_at IS NULL GROUP BY s.id").fetchall()
        for row in rows:
            if row["id"] == active_session_id:
                continue
            with self._lock:
                self._conn.execute(
                    "UPDATE sessions SET ended_at=? WHERE id=?",
                    (row["last_t1"] if row["last_t1"] is not None else time.time(), row["id"]))
                self._conn.commit()
            result["sessions_closed"] += 1

        result["coverage"] = self.coverage()
        return result

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
            finally:
                self._conn.close()
