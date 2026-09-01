#!/usr/bin/env python3
"""录像索引整理 CLI —— 把 index.db 与磁盘上的块文件对齐。

什么时候需要它:
    回放报 500 / 时间轴跨度离谱(比如从 1970 铺到今天) / 拖动后一片空白。
    根因通常是索引与文件分了家: 人工清理过录像目录、盘满被清、只拷了会话目录没拷
    索引、保留策略删到一半被打断。索引里留下指向空气的行, 读到就炸。

与 POST /api/recording/reconcile 的分工:
    端点适合"上位机正在跑、不想重启"; 本 CLI 适合上位机没起、或还在跑旧版本代码
    (那时端点根本不存在)。两者调的是同一个 RecordingStore.reconcile()。

安全:
    只删索引行与**目录已经不存在**的会话记录; 不动任何还在磁盘上的块文件。
    --deep 会逐块 stat, 30 天录像约 26 万行, 需要几秒。
    上位机正在录时也可以跑: sqlite 是 WAL, 且用 --active 排除当前会话最稳妥。

补算派生索引 (--rebuild-derived):
    时间轴上的利用率条读 chunk_activity, seek 重建派生态读 lowfreq。这两张表都是块
    落盘时顺手写的, 所以**在它们存在之前录下的块**是空的 —— 条上画不出东西、跳转
    后板会掉回料仓。这个开关把全部块解一遍把两张表补齐, 一趟解码同时喂两处。

运行:
    python -m eit_ptlc.tools.recording_reconcile --deep
    python -m eit_ptlc.tools.recording_reconcile --rebuild-derived
    python -m eit_ptlc.tools.recording_reconcile --root D:/ptlc-recordings --dry-run
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from eit_ptlc.runtime.recording.activity import chunk_activity, load_station_map
from eit_ptlc.runtime.recording.codec import decode_chunk
from eit_ptlc.runtime.recording.recorder import _DROPPABLE, _FRAME_STREAMS, _markers_for
from eit_ptlc.runtime.recording.store import MIN_PLAUSIBLE_TS, RecordingStore, default_root

_DEFAULT_POINTS = Path(__file__).resolve().parents[1] / "config" / "manual_points.yaml"


def _parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="录像索引整理 (只读磁盘, 只删索引行)")
    ap.add_argument("--root", default=None,
                    help="录像存储根; 省略则用 PTLC_RECORD_ROOT 或默认路径")
    ap.add_argument("--deep", action="store_true",
                    help="逐块核对文件是否还在(慢, 但能清掉全部孤儿行)")
    ap.add_argument("--active", default=None,
                    help="正在录制的会话 id; 传了就不动它")
    ap.add_argument("--rebuild-derived", action="store_true",
                    help="解全部块重建三张派生索引: chunk_activity(利用率条) / "
                         "lowfreq(派生态重建) / markers(动作与标记)。判据改过之后跑它 —— "
                         "在录时务必同时给 --active, 否则会丢掉当前未落盘块的那几行")
    ap.add_argument("--points", default=str(_DEFAULT_POINTS),
                    help="单点控制点表路径, 工位归属从它读")
    ap.add_argument("--dry-run", action="store_true", help="只报告, 不改动")
    ap.add_argument("--busy-timeout", type=int, default=180_000,
                    help="撞写锁时最长等待毫秒(默认 3 分钟)。上位机若在攒批提交, "
                         "写事务可能攥着几十秒不放, 等一等好过杀进程")
    return ap.parse_args(argv)


def _survey(store: RecordingStore) -> dict:
    """先照一张体检表 —— 不改任何东西。"""
    with store._lock:  # noqa: SLF001 - 维护工具, 有意直连
        rows = store._conn.execute("SELECT session_id, path, t0 FROM chunks").fetchall()
        sessions = store._conn.execute("SELECT id, dir, ended_at FROM sessions").fetchall()
    missing = sum(1 for r in rows if not (store.root / r["path"]).exists())
    bad_ts = sum(1 for r in rows if r["t0"] < MIN_PLAUSIBLE_TS)
    gone = sum(1 for s in sessions if not (store.root / s["dir"]).exists())
    zombie = sum(1 for s in sessions if s["ended_at"] is None)
    return {"chunks": len(rows), "chunks_missing_file": missing,
            "chunks_bad_ts": bad_ts, "sessions": len(sessions),
            "sessions_dir_gone": gone, "sessions_never_closed": zombie,
            "coverage": store.coverage()}


def rebuild_derived(store: RecordingStore, points_file, *,
                    active_session_id: str | None = None,
                    progress_every: int = 500) -> dict:
    """解全部块, 重建 chunk_activity / lowfreq / markers 三张派生索引。

    一趟解码同时喂三处: 都需要整块解开, 分三趟就是白解两遍。

    **markers 也是派生索引。** 它能从块里逐条重放出来 —— 每一条会产出标记的事件都是
    非帧事件, 必然进过 builder.add_event。把它当派生索引重建, 是为了让判据只有一个
    实现: 上一轮给 _markers_for 加了 phase(首尾配对的唯一依据), 旧构建写下的行没有,
    于是 done 被当成 start 永远配不上对, 前端把它画成一条横贯全宽的假长条。与其在读
    路径上兼容两套 schema, 不如重放一遍。

    读不出来的块直接跳过并计数 —— 补算工具的正确行为是"能补多少补多少并说清楚跳了
    几块", 而不是撞上一个坏块就整趟失败。

    **正在录的那个会话整个跳过。** 重建是"删掉再从已落盘的块里重放", 而在录会话手上
    还攥着一个未落盘的块(默认 10 秒), 它的标记与增量事件行**已经写进索引但源事件还
    没进块** —— 删了就再也回不来。上位机在跑时务必传 active_session_id。

    参数:
        store: 录像库; points_file: 单点控制点表(工位归属)
        active_session_id: 正在录制的会话 id, 传了就完全不碰它
        progress_every: 每处理这么多块打一行进度
    返回:
        dict, 各项计数 (含 markers 重建前后的行数, 少了就是有块被保留策略清掉了)
    """
    station_map = load_station_map(points_file)
    keep = active_session_id
    with store._lock:  # noqa: SLF001 - 维护工具, 有意直连
        rows = store._conn.execute(
            "SELECT session_id, seq, path FROM chunks WHERE session_id IS NOT ?"
            " ORDER BY session_id, seq", (keep,)).fetchall()
        markers_before = store._conn.execute(
            "SELECT COUNT(*) FROM markers WHERE session_id IS NOT ?", (keep,)).fetchone()[0]
        # 重建是幂等的: 先清掉旧行, 免得判据改过之后新旧两套结果混在一张表里
        for table in ("chunk_activity", "lowfreq", "markers"):
            store._conn.execute(f"DELETE FROM {table} WHERE session_id IS NOT ?", (keep,))
        store._conn.commit()

    result = {"chunks": len(rows), "chunks_read_failed": 0,
              "activity_rows": 0, "lowfreq_rows": 0,
              "markers_before": markers_before, "markers_after": 0}
    started = time.time()
    for index, row in enumerate(rows, start=1):
        try:
            chunk = decode_chunk(store.read_chunk(row["path"]))
        except (FileNotFoundError, OSError, ValueError):
            result["chunks_read_failed"] += 1
            continue
        streams = {name: data["channels"] for name, data in chunk.streams.items()}
        stations, _unmapped = chunk_activity(streams, station_map)
        store.set_chunk_activity(row["session_id"], row["seq"], stations)
        result["activity_rows"] += 1

        # 收录判据与录制侧逐字一致: 非帧流且不在 _DROPPABLE 里 = 增量事件
        incremental = [e for e in chunk.events
                       if isinstance(e, dict)
                       and e.get("type") not in _FRAME_STREAMS
                       and e.get("type") not in _DROPPABLE]
        result["lowfreq_rows"] += store.add_lowfreq(row["session_id"], incremental)

        markers = []
        for event in chunk.events:
            if not isinstance(event, dict):
                continue
            ts = event.get("ts")
            # 坏时间戳的事件当初就被录制侧用墙钟顶替过, 这里无从还原, 索性不重放它 ——
            # 一条 1970 的标记会把整条时间轴的下界拖到 56 年前
            if isinstance(ts, bool) or not isinstance(ts, (int, float)):
                continue
            if float(ts) < MIN_PLAUSIBLE_TS:
                continue
            markers.extend(_markers_for(event, float(ts)))
        if markers:
            store.add_markers(row["session_id"], markers)
            result["markers_after"] += len(markers)

        if progress_every and index % progress_every == 0:
            print(f"  ... {index}/{len(rows)} 块, 用时 {time.time() - started:.1f}s")
    result["seconds"] = round(time.time() - started, 1)
    return result


def main(argv=None) -> int:
    args = _parse_args(argv)
    store = RecordingStore(args.root or default_root(),
                           busy_timeout_ms=args.busy_timeout)
    try:
        before = _survey(store)
        print("=== 整理前 ===")
        print(json.dumps(before, ensure_ascii=False, indent=2))

        if args.dry_run:
            print("\n(--dry-run: 未做任何改动)")
            return 0

        result = store.reconcile(deep=args.deep, active_session_id=args.active)
        print("\n=== 整理结果 ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if args.rebuild_derived:
            # 先整理再补算: 否则会为一堆指向空气的孤儿行白解一遍
            print("\n=== 重建派生索引 (解全部块, 慢) ===")
            derived = rebuild_derived(store, args.points, active_session_id=args.active)
            print(json.dumps(derived, ensure_ascii=False, indent=2))
            if derived["markers_after"] < derived["markers_before"]:
                # 标记只该多不该少。少了说明有标记的源事件所在的块已被保留策略清掉,
                # 那些标记这次重建不回来 —— 必须说出来, 而不是让人以为一切正常。
                print(f"\n[警告] 标记从 {derived['markers_before']} 减到 "
                      f"{derived['markers_after']}: 有块已被清理, 对应标记无法重放")
                return 1

        cov = result["coverage"]
        if cov["t0"] is not None and cov["t0"] < MIN_PLAUSIBLE_TS:
            print("\n[警告] coverage 的 t0 仍不合理, 时间轴跨度会离谱")
            return 1
        if not args.deep and before["chunks_missing_file"]:
            print(f"\n[提示] 仍有 {before['chunks_missing_file']} 行可能指向不存在的文件, "
                  f"加 --deep 可一并清掉")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
