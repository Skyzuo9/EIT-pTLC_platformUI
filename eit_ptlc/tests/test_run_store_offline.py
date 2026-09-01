"""运行记录存储离线测试
========================
功能:
    验证 RunStore 持久化运行事件: 忽略非运行事件 (telemetry)、运行入库与终态收尾、
    事件有序且 step_done 携带 result、历史倒序与 status 过滤、未知运行返回 None.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_run_store_offline
"""

from __future__ import annotations

import sys

from eit_ptlc.runtime.run_store import RunStore


def _start(run_id: str, ts: float, label: str = "演示流程") -> dict:
    return {"type": "operation_start", "operation": "demo", "run_id": run_id, "label": label, "ts": ts}


def _step_done(run_id: str, idx: int, ts: float, status: str = "DONE") -> dict:
    return {"type": "step_done", "operation": "demo", "run_id": run_id, "index": idx,
            "step": f"s{idx}", "action": "plc.sampling.init", "status": status,
            "message": "", "result": {"state": status, "seq": idx}, "ts": ts}


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    store = RunStore(":memory:")

    # 非运行事件 (telemetry, 无 run_id) 应被忽略
    store.on_event({"type": "telemetry", "node": "robot", "health": "ok", "data": {}, "ts": 1.0})
    check("ignore_non_run", store.list_runs() == [], str(store.list_runs()))

    # r1: start + 2 步 + done
    store.on_event(_start("r1", 100.0))
    store.on_event(_step_done("r1", 0, 101.0))
    store.on_event(_step_done("r1", 1, 102.0))
    store.on_event({"type": "operation_done", "operation": "demo", "run_id": "r1",
                    "status": "DONE", "message": "", "ts": 103.0})

    runs = store.list_runs()
    check("run_recorded", len(runs) == 1 and runs[0]["run_id"] == "r1", str(runs))
    check("run_terminal", runs[0]["status"] == "DONE" and runs[0]["finished_at"] == 103.0, str(runs[0]))
    check("run_meta", runs[0]["operation"] == "demo" and runs[0]["label"] == "演示流程", str(runs[0]))

    detail = store.get_run("r1")
    types = [e["type"] for e in detail["events"]]
    check("events_ordered",
          types == ["operation_start", "step_done", "step_done", "operation_done"], str(types))
    sd = detail["events"][1]
    check("step_done_carries_result", sd.get("result") == {"state": "DONE", "seq": 0}, str(sd.get("result")))

    # r2: 失败终态 (operation_failed)
    store.on_event(_start("r2", 200.0))
    store.on_event(_step_done("r2", 0, 201.0, status="ERROR"))
    store.on_event({"type": "operation_failed", "operation": "demo", "run_id": "r2",
                    "status": "FAILED", "message": "步骤 s0 未完成", "ts": 202.0})
    r2 = store.get_run("r2")
    check("failed_status", r2["status"] == "FAILED" and "未完成" in r2["message"], str(r2["status"]))

    # 倒序: r2 (ts=200) 在 r1 (ts=100) 之前
    ordered = store.list_runs()
    check("list_desc", [r["run_id"] for r in ordered] == ["r2", "r1"], str([r["run_id"] for r in ordered]))

    # status 过滤: 新开一个仅 start 的 r3 即 RUNNING
    store.on_event(_start("r3", 300.0))
    running = store.list_runs(status="running")
    check("filter_running", [r["run_id"] for r in running] == ["r3"], str([r["run_id"] for r in running]))
    check("filter_done", [r["run_id"] for r in store.list_runs(status="DONE")] == ["r1"], "")

    # limit
    check("limit", len(store.list_runs(limit=1)) == 1, str(len(store.list_runs(limit=1))))

    # 日期窗口 [since, until): since 含边界, until 不含 (此时库内 r1@100 / r2@200 / r3@300)
    check("window_half_open",
          [r["run_id"] for r in store.list_runs(since=150.0, until=250.0)] == ["r2"], "")
    check("window_boundaries",
          [r["run_id"] for r in store.list_runs(since=200.0, until=300.0)] == ["r2"],
          "since 含 / until 不含")
    check("window_with_status",
          [r["run_id"] for r in store.list_runs(since=0.0, until=1000.0, status="FAILED")] == ["r2"], "")
    check("window_open_ended", len(store.list_runs(since=200.0)) == 2, "只给 since 不给 until")

    # 未知运行
    check("unknown_run", store.get_run("nope") is None, "")

    store.close()

    # 重跑同 run_id: 旧事件被清, get_run 只回放本次 (无孤儿混淆)
    store2 = RunStore(":memory:")
    store2.on_event(_start("rr", 10.0))
    store2.on_event(_step_done("rr", 0, 11.0))
    store2.on_event(_start("rr", 20.0))          # 重跑
    store2.on_event(_step_done("rr", 0, 21.0))
    rr = store2.get_run("rr")
    check("rerun_no_orphan", [e["type"] for e in rr["events"]] ==
          ["operation_start", "step_done"], str([e["type"] for e in rr["events"]]))
    check("rerun_single_head", len(store2.list_runs()) == 1, str(len(store2.list_runs())))
    store2.close()

    # 保留上限: max_runs=3, 灌 5 个运行, 只留最新 3 个且旧事件一并删除
    store3 = RunStore(":memory:", max_runs=3)
    for i in range(5):
        rid = f"g{i}"
        store3.on_event(_start(rid, 100.0 + i))
        store3.on_event(_step_done(rid, 0, 100.5 + i))
    kept = sorted(r["run_id"] for r in store3.list_runs(limit=100))
    check("retention_cap", kept == ["g2", "g3", "g4"], str(kept))
    check("retention_evicts_events", store3.get_run("g0") is None, "g0 应被淘汰")
    # 被淘汰运行的事件不残留
    orphan = store3._conn.execute(
        "SELECT COUNT(*) AS n FROM run_events WHERE run_id IN ('g0','g1')").fetchone()["n"]
    check("retention_no_orphan_events", orphan == 0, f"残留 {orphan} 条")
    store3.close()

    # max_runs<=0 表示不限
    store4 = RunStore(":memory:", max_runs=0)
    for i in range(10):
        store4.on_event(_start(f"u{i}", 1.0 + i))
    check("retention_unlimited", len(store4.list_runs(limit=100)) == 10, str(len(store4.list_runs(limit=100))))
    store4.close()

    print(f"\n共 22 用例, 失败 {len(failures)}")
    return 1 if failures else 0


# ------------------------------------------------------------------
# 启动收敛 (pytest 直采; 上面的 _run() 是历史遗留的手跑套件, pytest 采不到它)
# ------------------------------------------------------------------

def test_reconcile_orphans_marks_running_as_interrupted() -> None:
    """孤儿 RUNNING 判 INTERRUPTED, finished_at 取末条事件 ts (不是 now).

    真实成因 (2026-08-14 现场取证 5 条残留): 进程被杀/单步停驻被遗弃时
    VmThread._finish 没机会执行, 行永远停在 RUNNING。启动那一刻本进程必然
    没有在跑的运行, 所以"所有 RUNNING 都是残留"这个判据零误伤。
    """
    store = RunStore(":memory:")
    store.on_event(_start("orphan", 100.0))
    store.on_event(_step_done("orphan", 0, 101.0))
    store.on_event(_step_done("orphan", 1, 107.5))

    ids = store.reconcile_orphans()
    assert ids == ["orphan"]

    row = store.list_runs()[0]
    assert row["status"] == "INTERRUPTED"
    # finished_at 用末条事件 ts —— 用 now() 会把卡了多天的运行算成天级时长, 污染统计与时间线
    assert row["finished_at"] == 107.5
    assert "中断" in row["message"]
    store.close()


def test_reconcile_orphans_without_events_falls_back_to_started_at() -> None:
    """连一条事件都没有的 RUNNING 行 (理论上只有 operation_start 也是事件,
    这里直接造行模拟极端残留): finished_at 回落 started_at, 不留 NULL."""
    store = RunStore(":memory:")
    with store._lock:
        store._conn.execute(
            "INSERT INTO runs(run_id, operation, label, status, started_at, finished_at, message)"
            " VALUES ('bare', 'demo', '裸行', 'RUNNING', 55.0, NULL, '')")
        store._conn.commit()

    assert store.reconcile_orphans() == ["bare"]
    row = store.get_run("bare")
    assert row["status"] == "INTERRUPTED"
    assert row["finished_at"] == 55.0
    store.close()


def test_reconcile_orphans_leaves_terminal_rows_alone() -> None:
    """终态行 (DONE/FAILED/CANCELLED) 一个字都不动; 空库/无残留时是 no-op."""
    store = RunStore(":memory:")
    assert store.reconcile_orphans() == []          # 空库 no-op

    store.on_event(_start("ok", 10.0))
    store.on_event({"type": "operation_done", "operation": "demo", "run_id": "ok",
                    "status": "DONE", "message": "", "ts": 11.0})
    store.on_event(_start("bad", 20.0))
    store.on_event({"type": "operation_failed", "operation": "demo", "run_id": "bad",
                    "status": "FAILED", "message": "炸了", "ts": 21.0})
    store.on_event(_start("halted", 30.0))
    store.on_event({"type": "operation_failed", "operation": "demo", "run_id": "halted",
                    "status": "CANCELLED", "message": "已停止", "ts": 31.0})

    assert store.reconcile_orphans() == []
    statuses = {r["run_id"]: r["status"] for r in store.list_runs(limit=10)}
    assert statuses == {"ok": "DONE", "bad": "FAILED", "halted": "CANCELLED"}
    store.close()


def test_reconcile_orphans_is_idempotent() -> None:
    """收敛两次, 第二次没东西可收 —— INTERRUPTED 不会被再次改写."""
    store = RunStore(":memory:")
    store.on_event(_start("r", 1.0))
    assert store.reconcile_orphans() == ["r"]
    first = store.get_run("r")
    assert store.reconcile_orphans() == []
    assert store.get_run("r")["finished_at"] == first["finished_at"]
    store.close()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return _run()


if __name__ == "__main__":
    sys.exit(main())
