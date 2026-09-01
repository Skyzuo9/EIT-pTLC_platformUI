"""实验数据库 (批次 / 样品 / 段作业 / 结果)
==========================================
功能:
    并行实验系统的持久化实体库: 批次(batch) -> 样品(sample) -> 段作业(job, 原子流程的
    一次 VM 运行), 外加视觉结果指标(results)与调度决策审计流水(sched_events)。
    工艺参数快照(批参数/每样品覆盖/config 三段)在提交时冻结入库, 事后可复现一次实验。

设计取向:
    - 独立库文件 var/experiments.db: 绝不并入 var/runs.db —— 后者 max_runs LRU 淘汰
      最旧运行连带其事件, 而实验记录不能被淘汰 (与 material_store 同一分库原则)。
    - 纯记录式仓库: 本模块不做任何调度决策; 实体状态的权威写者是 FlowScheduler,
      本库只负责持久化与查询。jobs.run_id 是对 runs.db 的弱引用 —— runs 被 LRU 淘汰后
      本库记录仍自足 (起止/状态/message 均自存)。
    - 结果数据: 文件系统是真相源 (vision_output/<sample_id>/), 本库的 results 表只是
      检索加速 (关键标量列 rf/band_count + 路径 + data_json)。
    - 一行一格: 每 (样品, 段) 恒一行 jobs, 重试原地更新 attempt 计数 (历史经
      sched_events 与 runs.db 追溯), 使看板"样品x段"矩阵可直接 SELECT。

线程模型:
    与 run_store/material_store 相同: sqlite3 + check_same_thread=False + 进程内锁串行化。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# 状态枚举 (闭集; 迁移合法性由调度器保证, 本库只校验取值)
BATCH_STATUSES = ("QUEUED", "RUNNING", "PAUSED", "COMPLETED", "ABORTED")
SAMPLE_STATUSES = ("PENDING", "ACTIVE", "HOLD", "DONE", "ABORTED")
JOB_STATUSES = ("PENDING", "DISPATCHED", "RUNNING", "WAITING_HUMAN",
                "DONE", "ERROR", "SKIPPED", "INTERRUPTED", "CANCELLED")
# 段作业终态 (不再被调度器派发)
JOB_FINAL = frozenset({"DONE", "ERROR", "SKIPPED", "INTERRUPTED", "CANCELLED"})
# 依赖满足判定: DONE 与 SKIPPED (人工跳过视为已完成) 均放行后续段
JOB_SATISFIED = frozenset({"DONE", "SKIPPED"})
# 在飞态: 进程重启时无法恢复协程栈, 一律标 INTERRUPTED 待人工对账
_JOB_INFLIGHT = ("DISPATCHED", "RUNNING", "WAITING_HUMAN")


def _dumps(obj: Any) -> str:
    return json.dumps(obj if obj is not None else {}, ensure_ascii=False)


def _loads(text: Optional[str]) -> Any:
    if not text:
        return {}
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return {}


class ExperimentStore:
    """实验数据的 SQLite 存储 (批次/样品/段作业/结果/调度审计)."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._path = str(db_path)
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
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id             TEXT PRIMARY KEY,
                    name                 TEXT,
                    recipe               TEXT,
                    status               TEXT,
                    priority             INTEGER DEFAULT 0,
                    wip_limit            INTEGER,
                    tank_pool            TEXT,    -- json [缸号...]
                    params_json          TEXT,    -- 批级工艺参数 (旋钮覆盖)
                    overrides_json       TEXT,    -- 每样品覆盖 [{...}] (按 seq 对齐)
                    config_snapshot_json TEXT,    -- 提交时 gcode/pump/vision 三段快照
                    auto_drain           INTEGER DEFAULT 1,
                    needs_reconcile      INTEGER DEFAULT 0,
                    note                 TEXT,
                    submitted_at         REAL,
                    started_at           REAL,
                    finished_at          REAL,
                    message              TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS samples (
                    sample_id     TEXT PRIMARY KEY,
                    batch_id      TEXT,
                    seq           INTEGER,
                    status        TEXT,
                    tank          INTEGER,
                    position      TEXT,
                    context_json  TEXT,           -- 跨段上下文 (before_path/collector_hole/...)
                    overrides_json TEXT,          -- 本样品的参数覆盖 (冻结快照)
                    created_at    REAL,
                    updated_at    REAL,
                    message       TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_samples_batch ON samples(batch_id, seq);
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id        TEXT PRIMARY KEY,  -- {sample_id|batch_id}-{flow_id}
                    batch_id      TEXT,
                    sample_id     TEXT,              -- NULL = 批级段 (scope: batch)
                    flow_id       TEXT,              -- 配方段 id (af0/s1/...)
                    af_index      INTEGER,           -- 配方内序号 (策略序用)
                    script        TEXT,
                    run_id        TEXT,              -- 最近一次派发的 VM run_id (弱引用)
                    attempt       INTEGER DEFAULT 0,
                    status        TEXT,
                    depends_json  TEXT,              -- ["s1", ...] flow_id 列表
                    inputs_json   TEXT,              -- 最近一次派发的实际 inputs
                    outputs_json  TEXT,              -- DONE 时抽取的 out 变量
                    failed_aid    TEXT,              -- 段内断点: 失败时的 AID
                    failed_step   TEXT,              -- 失败步骤可读名 (script/action)
                    vars_snapshot_json TEXT,         -- 失败时根帧变量快照 (resume 回注源)
                    resume_from   TEXT,              -- 断点续跑起点 AID (resume 动词写入, 派发消费)
                    queued_at     REAL,
                    started_at    REAL,
                    finished_at   REAL,
                    message       TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id, af_index);
                CREATE INDEX IF NOT EXISTS idx_jobs_sample ON jobs(sample_id, af_index);
                CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
                CREATE TABLE IF NOT EXISTS results (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id     TEXT,
                    sample_id    TEXT,
                    kind         TEXT,             -- vision_summary | band
                    band_id      INTEGER,
                    rf           REAL,             -- 条带 Rf (= 条带距原点 / 溶剂前沿距原点)
                    band_count   INTEGER,
                    summary_path TEXT,
                    metrics_path TEXT,
                    data_json    TEXT,
                    created_at   REAL
                );
                CREATE INDEX IF NOT EXISTS idx_results_sample ON results(sample_id, id);
                CREATE TABLE IF NOT EXISTS sched_events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts        REAL,
                    batch_id  TEXT,
                    sample_id TEXT,
                    job_id    TEXT,
                    type      TEXT,
                    payload   TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_sched_events_batch ON sched_events(batch_id, id);
                """
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # 批次创建 (单事务: 批 + 样品 + 全部段作业)
    # ------------------------------------------------------------------

    def create_batch(self, batch_id: str, *, name: str, recipe: str,
                     priority: int = 0, wip_limit: Optional[int] = None,
                     tank_pool: Optional[list[int]] = None,
                     params: Optional[dict] = None,
                     per_sample_overrides: Optional[list] = None,
                     config_snapshot: Optional[dict] = None,
                     auto_drain: bool = True, note: str = "",
                     samples: Optional[list[dict]] = None,
                     jobs: Optional[list[dict]] = None) -> None:
        """一个事务写入整批实体 (批 QUEUED, 样品 PENDING, 段作业 PENDING).

        参数:
            samples: [{sample_id, seq, position, overrides?}]  position=配方首段 from 停放位
            jobs:    [{job_id, sample_id|None, flow_id, af_index, script, depends: [flow_id]}]
        """
        now = time.time()
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                self._conn.execute(
                    "INSERT INTO batches(batch_id, name, recipe, status, priority, wip_limit,"
                    " tank_pool, params_json, overrides_json, config_snapshot_json, auto_drain,"
                    " note, submitted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (batch_id, name, recipe, "QUEUED", int(priority), wip_limit,
                     _dumps(list(tank_pool or [])), _dumps(params),
                     _dumps(per_sample_overrides or []), _dumps(config_snapshot),
                     1 if auto_drain else 0, note, now))
                for s in samples or []:
                    self._conn.execute(
                        "INSERT INTO samples(sample_id, batch_id, seq, status, position,"
                        " context_json, overrides_json, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (s["sample_id"], batch_id, int(s["seq"]), "PENDING",
                         s.get("position", ""), _dumps({}), _dumps(s.get("overrides")),
                         now, now))
                for j in jobs or []:
                    self._conn.execute(
                        "INSERT INTO jobs(job_id, batch_id, sample_id, flow_id, af_index,"
                        " script, status, depends_json, inputs_json, outputs_json, queued_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (j["job_id"], batch_id, j.get("sample_id"), j["flow_id"],
                         int(j["af_index"]), j["script"], "PENDING",
                         _dumps(list(j.get("depends") or [])), _dumps({}), _dumps({}), now))
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def sample_ids_exist(self, sample_ids: list[str]) -> list[str]:
        """返回已存在的样品 id 子集 (提交前查重, API 层据此回 409)."""
        if not sample_ids:
            return []
        ph = ",".join("?" * len(sample_ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT sample_id FROM samples WHERE sample_id IN ({ph})",
                list(sample_ids)).fetchall()
        return [r["sample_id"] for r in rows]

    # ------------------------------------------------------------------
    # 更新 (权威写者 = FlowScheduler)
    # ------------------------------------------------------------------

    _BATCH_FIELDS = {"status", "started_at", "finished_at", "message", "needs_reconcile",
                     "wip_limit", "priority"}
    _SAMPLE_FIELDS = {"status", "tank", "position", "message", "updated_at"}
    _JOB_FIELDS = {"status", "run_id", "attempt", "inputs_json", "outputs_json",
                   "failed_aid", "failed_step", "vars_snapshot_json", "resume_from",
                   "queued_at", "started_at", "finished_at", "message"}

    def _update(self, table: str, key_col: str, key: str, allowed: set[str], fields: dict) -> None:
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"{table} 不允许更新字段: {sorted(bad)}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE {table} SET {sets} WHERE {key_col} = ?",
                               (*fields.values(), key))
            self._conn.commit()

    def update_batch(self, batch_id: str, **fields) -> None:
        if "status" in fields and fields["status"] not in BATCH_STATUSES:
            raise ValueError(f"batch status 非法: {fields['status']}")
        self._update("batches", "batch_id", batch_id, self._BATCH_FIELDS, fields)

    def update_sample(self, sample_id: str, **fields) -> None:
        if "status" in fields and fields["status"] not in SAMPLE_STATUSES:
            raise ValueError(f"sample status 非法: {fields['status']}")
        fields.setdefault("updated_at", time.time())
        self._update("samples", "sample_id", sample_id, self._SAMPLE_FIELDS, fields)

    def update_job(self, job_id: str, **fields) -> None:
        if "status" in fields and fields["status"] not in JOB_STATUSES:
            raise ValueError(f"job status 非法: {fields['status']}")
        for k in ("inputs", "outputs", "vars_snapshot"):
            if k in fields:
                fields[f"{k}_json"] = _dumps(fields.pop(k))
        self._update("jobs", "job_id", job_id, self._JOB_FIELDS, fields)

    def merge_sample_context(self, sample_id: str, patch: dict) -> dict:
        """把段 outputs 并入样品跨段上下文, 返回合并后的完整上下文."""
        with self._lock:
            row = self._conn.execute(
                "SELECT context_json FROM samples WHERE sample_id = ?", (sample_id,)).fetchone()
            ctx = _loads(row["context_json"]) if row else {}
            ctx.update(patch or {})
            self._conn.execute(
                "UPDATE samples SET context_json = ?, updated_at = ? WHERE sample_id = ?",
                (_dumps(ctx), time.time(), sample_id))
            self._conn.commit()
        return ctx

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, json_cols: tuple[str, ...] = ()) -> dict:
        d = dict(row)
        for col in json_cols:
            if col in d:
                d[col.removesuffix("_json")] = _loads(d.pop(col))
        return d

    def get_batch(self, batch_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row, ("tank_pool", "params_json", "overrides_json",
                                       "config_snapshot_json"))

    def list_batches(self, *, limit: int = 50, status: Optional[str] = None) -> list[dict]:
        """批次列表 (带 sample_total/sample_done 聚合, 供左栏行渲染)."""
        sql = ("SELECT b.*, "
               " (SELECT COUNT(*) FROM samples s WHERE s.batch_id = b.batch_id) AS sample_total, "
               " (SELECT COUNT(*) FROM samples s WHERE s.batch_id = b.batch_id"
               "   AND s.status = 'DONE') AS sample_done "
               "FROM batches b")
        args: list = []
        if status:
            sql += " WHERE b.status = ?"
            args.append(status)
        sql += " ORDER BY b.submitted_at DESC LIMIT ?"
        args.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_dict(r, ("tank_pool", "params_json", "overrides_json",
                                      "config_snapshot_json")) for r in rows]

    def active_batches_using_recipe(self, recipe: str) -> list[str]:
        """非终态 (QUEUED/RUNNING/PAUSED) 且使用指定配方的批次 id (配方保存保护用)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT batch_id FROM batches WHERE recipe = ?"
                " AND status IN ('QUEUED','RUNNING','PAUSED') ORDER BY submitted_at",
                (recipe,)).fetchall()
        return [r["batch_id"] for r in rows]

    def list_samples(self, batch_id: Optional[str] = None,
                     status: Optional[str] = None) -> list[dict]:
        sql, args = "SELECT * FROM samples", []
        conds = []
        if batch_id:
            conds.append("batch_id = ?")
            args.append(batch_id)
        if status:
            conds.append("status = ?")
            args.append(status)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY batch_id, seq"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_dict(r, ("context_json", "overrides_json")) for r in rows]

    def get_sample(self, sample_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM samples WHERE sample_id = ?", (sample_id,)).fetchone()
        return self._row_to_dict(row, ("context_json", "overrides_json")) if row else None

    def list_jobs(self, *, batch_id: Optional[str] = None, sample_id: Optional[str] = None,
                  status: Optional[str] = None) -> list[dict]:
        sql, args, conds = "SELECT * FROM jobs", [], []
        for col, val in (("batch_id", batch_id), ("sample_id", sample_id), ("status", status)):
            if val:
                conds.append(f"{col} = ?")
                args.append(val)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY af_index"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_dict(r, ("depends_json", "inputs_json", "outputs_json",
                                      "vars_snapshot_json")) for r in rows]

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_dict(row, ("depends_json", "inputs_json", "outputs_json",
                                       "vars_snapshot_json")) if row else None

    def job_by_run_id(self, run_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE run_id = ? ORDER BY finished_at IS NULL DESC LIMIT 1",
                (run_id,)).fetchone()
        return self._row_to_dict(row, ("depends_json", "inputs_json", "outputs_json",
                                       "vars_snapshot_json")) if row else None

    def get_batch_detail(self, batch_id: str) -> Optional[dict]:
        """批 + 样品 (各带段作业链) + 批级段, 供批次详情页一次取全."""
        batch = self.get_batch(batch_id)
        if batch is None:
            return None
        samples = self.list_samples(batch_id)
        jobs = self.list_jobs(batch_id=batch_id)
        by_sample: dict[str, list[dict]] = {}
        batch_jobs: list[dict] = []
        for j in jobs:
            if j.get("sample_id"):
                by_sample.setdefault(j["sample_id"], []).append(j)
            else:
                batch_jobs.append(j)
        for s in samples:
            s["jobs"] = by_sample.get(s["sample_id"], [])
        batch["samples"] = samples
        batch["batch_jobs"] = batch_jobs
        return batch

    # ------------------------------------------------------------------
    # 重启恢复 (v1: 标记 + 人工对账, 禁止自动重派)
    # ------------------------------------------------------------------

    def mark_interrupted_on_boot(self) -> dict:
        """启动时把在飞段作业标 INTERRUPTED, 所在批置 PAUSED + needs_reconcile.

        返回:
            {"jobs": 受影响段数, "batches": [batch_id...]}
        QUEUED 批 (尚无在飞) 不动 —— 它们可以在调度器就绪后正常起跑。
        """
        now = time.time()
        with self._lock:
            ph = ",".join("?" * len(_JOB_INFLIGHT))
            victims = self._conn.execute(
                f"SELECT job_id, batch_id FROM jobs WHERE status IN ({ph})",
                list(_JOB_INFLIGHT)).fetchall()
            batch_ids = sorted({r["batch_id"] for r in victims})
            if victims:
                self._conn.execute(
                    f"UPDATE jobs SET status = 'INTERRUPTED', finished_at = ?,"
                    f" message = '进程重启: 运行态丢失, 待人工对账' WHERE status IN ({ph})",
                    (now, *list(_JOB_INFLIGHT)))
                bph = ",".join("?" * len(batch_ids))
                self._conn.execute(
                    f"UPDATE batches SET status = 'PAUSED', needs_reconcile = 1"
                    f" WHERE batch_id IN ({bph}) AND status IN ('QUEUED','RUNNING')",
                    batch_ids)
            self._conn.commit()
        if victims:
            log.warning("[实验库] 重启对账: %d 个在飞段作业标 INTERRUPTED (批 %s)",
                        len(victims), batch_ids)
        return {"jobs": len(victims), "batches": batch_ids}

    # ------------------------------------------------------------------
    # 结果摄取 (文件系统真相源 -> 检索列)
    # ------------------------------------------------------------------

    def ingest_vision_results(self, sample_id: str, case_dir: str | Path) -> int:
        """摄取一个视觉分析 case 目录的 summary 与逐条带 metrics; 返回写入行数.

        参数:
            case_dir: vision_output/<case> 目录 (含 summary.json 与 task3_metrics/)
        幂等: 重摄取前先删除该样品旧 results 行 (文件系统为真相源, 行可重建)。
        Rf = 条带质心距原点 / 溶剂前沿距原点 (两值齐备才算, 否则留 NULL)。
        """
        case = Path(case_dir)
        summary_path = case / "summary.json"
        if not summary_path.exists():
            log.warning("[实验库] 结果摄取: %s 无 summary.json, 跳过", case)
            return 0
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("[实验库] 结果摄取: 读 %s 失败: %s", summary_path, exc)
            return 0
        sample = self.get_sample(sample_id)
        batch_id = sample.get("batch_id", "") if sample else ""
        now = time.time()
        bands = summary.get("bands") or []
        solvent = (summary.get("solvent_front") or {}).get("distance_from_origin_cm")
        rows: list[tuple] = [(batch_id, sample_id, "vision_summary", None, None, len(bands),
                              str(summary_path), None, _dumps({
                                  "solvent_front": summary.get("solvent_front"),
                                  "origin_band": summary.get("origin_band"),
                                  "plate_bbox_px": summary.get("plate_bbox_px"),
                              }), now)]
        for metrics_path in sorted((case / "task3_metrics").glob("band_*_metrics.json")):
            try:
                m = json.loads(metrics_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log.warning("[实验库] 结果摄取: 读 %s 失败: %s", metrics_path, exc)
                continue
            band = m.get("band") or m
            dist = band.get("distance_to_origin_cm")
            sf = (m.get("solvent_front") or {}).get("distance_from_origin_cm") or solvent
            rf = None
            try:
                if dist is not None and sf:
                    rf = round(float(dist) / float(sf), 4)
            except (TypeError, ValueError, ZeroDivisionError):
                rf = None
            rows.append((batch_id, sample_id, "band", band.get("band_id"), rf, None,
                         str(summary_path), str(metrics_path), _dumps(m), now))
        with self._lock:
            self._conn.execute("DELETE FROM results WHERE sample_id = ?", (sample_id,))
            self._conn.executemany(
                "INSERT INTO results(batch_id, sample_id, kind, band_id, rf, band_count,"
                " summary_path, metrics_path, data_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self._conn.commit()
        log.info("[实验库] 样品 %s 结果摄取完成: %d 行 (含 summary)", sample_id, len(rows))
        return len(rows)

    def list_results(self, *, batch_id: Optional[str] = None,
                     sample_id: Optional[str] = None) -> list[dict]:
        sql, args, conds = "SELECT * FROM results", [], []
        for col, val in (("batch_id", batch_id), ("sample_id", sample_id)):
            if val:
                conds.append(f"{col} = ?")
                args.append(val)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY sample_id, kind DESC, band_id"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_dict(r, ("data_json",)) for r in rows]

    # ------------------------------------------------------------------
    # 调度决策审计
    # ------------------------------------------------------------------

    def log_event(self, event_type: str, *, batch_id: str = "", sample_id: str = "",
                  job_id: str = "", payload: Optional[dict] = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sched_events(ts, batch_id, sample_id, job_id, type, payload)"
                " VALUES (?,?,?,?,?,?)",
                (time.time(), batch_id, sample_id, job_id, event_type, _dumps(payload)))
            self._conn.commit()

    def list_events(self, batch_id: str, *, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sched_events WHERE batch_id = ? ORDER BY id DESC LIMIT ?",
                (batch_id, max(1, int(limit)))).fetchall()
        return [self._row_to_dict(r, ("payload",)) for r in rows][::-1]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
