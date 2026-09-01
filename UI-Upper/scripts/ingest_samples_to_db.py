"""
ingest_samples_to_db.py - \u6279\u91cf\u5c06\u6837\u54c1\u6587\u4ef6\u7cfb\u7edf\u6570\u636e\u5bfc\u5165 SQLite \u4e8c\u7ea7\u7d22\u5f15\u5c42
========================================================================

\u9762\u5411\u5b58\u91cf\u6837\u54c1\uff08data/samples/<sample_id>/\uff09\u7684\u4e00\u6b21\u6027\u5bfc\u5165\u5de5\u5177\u3002

\u4e0e\u8fd0\u884c\u65f6\u5199\u5165\u8def\u5f84\uff08SampleStore.trigger_db_*\uff09\u4f7f\u7528\u540c\u4e00 DatabaseService\uff0c
\u4fdd\u8bc1 schema \u548c\u8def\u5f84\u5904\u7406\u7b49\u4e00\u6b21\u3002\u91cd\u590d\u8fd0\u884c\u5e42\u7b49\uff08DELETE + INSERT\uff09\u3002

\u4f7f\u7528\u793a\u4f8b\uff1a
    # \u5bfc\u5165\u9ed8\u8ba4 data/samples \u76ee\u5f55\u5230 data/tlc_data.sqlite
    python scripts/ingest_samples_to_db.py

    # \u6307\u5b9a\u8def\u5f84
    python scripts/ingest_samples_to_db.py --data data/samples --db data/tlc_data.sqlite

    # \u5148\u91cd\u5efa\u8868\u518d\u5bfc\u5165
    python scripts/ingest_samples_to_db.py --reset
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# \u5141\u8bb8\u4ece UI-Upper \u6839\u76ee\u5f55\u8fd0\u884c
_HERE = Path(__file__).resolve().parent
_UI_UPPER = _HERE.parent
if str(_UI_UPPER) not in sys.path:
    sys.path.insert(0, str(_UI_UPPER))

from core.database import DatabaseService  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest_samples_to_db")


def _find_summary_path(sample_dir: Path, sample_id: str) -> Path | None:
    """\u67e5\u627e summary.json\uff0c\u517c\u5bb9\u591a\u79cd\u5e03\u5c40\u3002"""
    candidates = [
        sample_dir / "analysis" / sample_id / "summary.json",
        sample_dir / "analysis" / "summary.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    analysis_dir = sample_dir / "analysis"
    if analysis_dir.exists():
        matches = sorted(analysis_dir.rglob("summary.json"))
        if matches:
            return matches[0]
    return None


async def ingest_sample(db: DatabaseService, sample_dir: Path) -> bool:
    """\u5bfc\u5165\u5355\u4e2a\u6837\u54c1\u3002\u6210\u529f\u8fd4\u56de True\u3002"""
    metadata_path = sample_dir / "metadata.json"
    if not metadata_path.exists():
        log.warning("[ingest] %s \u7f3a\u5c11 metadata.json\uff0c\u8df3\u8fc7", sample_dir.name)
        return False

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("[ingest] %s metadata.json \u8bfb\u53d6\u5931\u8d25: %s", sample_dir.name, e)
        return False

    sample_id = metadata.get("sample_id") or sample_dir.name

    # 1. \u4e3b\u8868
    await db.upsert_sample(sample_id, metadata, sample_dir)

    # 2. \u5206\u6790\u7ed3\u679c
    summary_path = _find_summary_path(sample_dir, sample_id)
    if summary_path:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            await db.upsert_analysis(sample_id, summary, summary_path)
            await db.upsert_bands(sample_id, summary.get("bands", []))
        except Exception as e:
            log.warning("[ingest] %s summary \u5904\u7406\u5f02\u5e38: %s", sample_id, e)

    # 3. G-code \u6587\u4ef6
    gcode_dir = sample_dir / "gcode"
    if gcode_dir.exists():
        await db.upsert_gcode(sample_id, gcode_dir, metadata)

    log.info("[ingest] \u2713 %s", sample_id)
    return True


async def ingest_all(db: DatabaseService, data_dir: Path) -> int:
    """\u904d\u5386 data_dir \u4e0b\u6240\u6709\u6837\u54c1\u76ee\u5f55\u5e76\u5bfc\u5165\u3002"""
    if not data_dir.exists():
        log.error("[ingest] \u6837\u54c1\u6839\u76ee\u5f55\u4e0d\u5b58\u5728: %s", data_dir)
        return 0

    count = 0
    for sample_dir in sorted(data_dir.iterdir()):
        if not sample_dir.is_dir():
            continue
        # \u8df3\u8fc7\u4fdd\u7559\u76ee\u5f55
        if sample_dir.name in ("debug", "_system") or sample_dir.name.startswith("."):
            continue
        if await ingest_sample(db, sample_dir):
            count += 1
    return count


async def reset_database(db: DatabaseService) -> None:
    """\u5220\u9664\u6240\u6709\u8868\u540e\u91cd\u65b0\u5efa\u8868\u3002"""
    if db._conn is None:
        return
    await db._conn.executescript(
        """
        DROP TABLE IF EXISTS event_log;
        DROP TABLE IF EXISTS image_assets;
        DROP TABLE IF EXISTS gcode_files;
        DROP TABLE IF EXISTS scrape_path_points;
        DROP TABLE IF EXISTS band_paths;
        DROP TABLE IF EXISTS bands;
        DROP TABLE IF EXISTS analyses;
        DROP TABLE IF EXISTS sample_selected_bands;
        DROP TABLE IF EXISTS samples;
        """
    )
    await db._conn.commit()
    # \u91cd\u65b0\u5efa\u8868
    from core.database import SCHEMA
    await db._conn.executescript(SCHEMA)
    await db._conn.commit()
    log.info("[ingest] \u5df2\u91cd\u5efa\u6240\u6709\u8868")


async def print_report(db: DatabaseService) -> None:
    """\u6253\u5370\u5bfc\u5165\u540e\u7684\u6458\u8981\u62a5\u544a\u3002"""
    if db._conn is None:
        return

    print()
    print("=" * 60)
    print("  \u5bfc\u5165\u62a5\u544a")
    print("=" * 60)

    cursor = await db._conn.execute(
        """
        SELECT s.sample_id,
               s.selected_gcode_path,
               (SELECT COUNT(*) FROM bands WHERE sample_id = s.sample_id) AS band_count,
               (SELECT COUNT(*) FROM gcode_files WHERE sample_id = s.sample_id) AS gcode_count,
               (SELECT COUNT(*) FROM image_assets WHERE sample_id = s.sample_id) AS image_count
        FROM samples s
        ORDER BY s.sample_id
        """
    )
    rows = await cursor.fetchall()
    if not rows:
        print("(\u65e0\u6837\u54c1\u8bb0\u5f55)")
        return

    for row in rows:
        selected_bands = await db.get_selected_bands(row["sample_id"])
        print(
            f"- {row['sample_id']}: bands={row['band_count']}, "
            f"gcode={row['gcode_count']}, images={row['image_count']}, "
            f"selected={selected_bands}"
        )
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=Path("data/samples"),
        help="\u6837\u54c1\u6839\u76ee\u5f55\uff08\u9ed8\u8ba4 data/samples\uff09",
    )
    parser.add_argument(
        "--db", type=Path, default=Path("data/tlc_data.sqlite"),
        help="\u6570\u636e\u5e93\u6587\u4ef6\u8def\u5f84\uff08\u9ed8\u8ba4 data/tlc_data.sqlite\uff09",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="\u5bfc\u5165\u524d\u5148\u91cd\u5efa\u6240\u6709\u8868\uff08\u6e05\u7a7a\u73b0\u6709\u6570\u636e\uff09",
    )
    parser.add_argument(
        "--no-report", action="store_true",
        help="\u5bfc\u5165\u540e\u4e0d\u6253\u5370\u62a5\u544a",
    )
    return parser.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    db = DatabaseService(args.db)
    await db.start()
    try:
        if args.reset:
            await reset_database(db)
        count = await ingest_all(db, args.data)
        log.info("[ingest] \u5df2\u5bfc\u5165 %d \u4e2a\u6837\u54c1 \u2192 %s", count, args.db)
        if not args.no_report:
            await print_report(db)
    finally:
        await db.stop()
    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
