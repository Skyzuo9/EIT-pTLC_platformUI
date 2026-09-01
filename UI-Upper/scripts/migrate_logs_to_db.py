"""
migrate_logs_to_db.py - 日志 JSONL → SQLite 迁移占位脚本（P2-1）
================================================================

当前状态：占位（未实现）。

背景：
    `core/log_persistence.py` 当前用 JsonlFileSink 落盘，字段已与未来 DB 表
    1:1 对齐。本脚本预留从 JSONL 迁移到 SQLite 的入口。

未来实现路径：

1. 创建表结构（aiosqlite）：
    CREATE TABLE IF NOT EXISTS event_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          TEXT NOT NULL,            -- ISO8601
        sample_id   TEXT NOT NULL,
        event       TEXT NOT NULL,
        detail      TEXT,
        extra       TEXT                       -- JSON
    );
    CREATE INDEX idx_event_log_sample_id ON event_log(sample_id);
    CREATE INDEX idx_event_log_ts ON event_log(ts);

2. 遍历 data/logs/by_date/*.jsonl(.gz)：
    for path in sorted(glob("data/logs/by_date/*.jsonl*")):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as f:
            rows = []
            for line in f:
                obj = json.loads(line)
                rows.append((
                    obj["ts"],
                    obj["sample_id"],
                    obj["event"],
                    obj.get("detail", ""),
                    json.dumps(obj.get("extra") or {}, ensure_ascii=False),
                ))
            await db.executemany(
                "INSERT INTO event_log(ts,sample_id,event,detail,extra) VALUES (?,?,?,?,?)",
                rows,
            )
            await db.commit()

3. 切换运行态：
    - 实现 SqliteSink(LogSink)：write_batch 直接 executemany INSERT
    - 修改 build_default_persistence 改注入 SqliteSink 替代 JsonlFileSink
    - 上层 LogStore / LogPersistence 不感知差异

字段对齐保证：
    JSONL 单行字段 (ts, sample_id, event, detail, extra) 与 event_log 表列
    1:1 对应，迁移时 json.loads → INSERT 即可，无任何格式转换。
"""

import sys


def main() -> int:
    print("[migrate_logs_to_db] 占位脚本，尚未实现。", file=sys.stderr)
    print("[migrate_logs_to_db] 详见模块顶部 docstring 说明的迁移路径。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
