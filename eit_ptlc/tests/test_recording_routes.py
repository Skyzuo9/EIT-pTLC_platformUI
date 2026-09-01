"""状态录像路由: 检索、任意时刻快照、帧流对齐与截断诚实性。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eit_ptlc.api.recording_routes import register_recording_routes
from eit_ptlc.runtime.recording.activity import load_station_map
from eit_ptlc.runtime.recording.recorder import StateRecorder
from eit_ptlc.runtime.recording.store import RecordingStore

T0 = 1786000000.0


def _drain(recorder, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if recorder.status()["queued"] == 0:
            time.sleep(0.05)
            if recorder.status()["queued"] == 0:
                return
        time.sleep(0.02)
    raise AssertionError("写盘线程未清空队列")


@pytest.fixture()
def client(tmp_path):
    store = RecordingStore(tmp_path / "rec")
    # 用仓内真实点表: 工位归属是"利用率条画的是什么"的全部依据, 拿假映射测等于没测
    recorder = StateRecorder(store, chunk_seconds=2.0, station_map=load_station_map(
        Path(__file__).resolve().parents[1] / "config" / "manual_points.yaml"))
    recorder.start()
    try:
        # 一段真实感的录像: 轴匀速走 + 机构翻转 + 一次失败的流程
        for i in range(200):
            ts = T0 + i * 0.05
            recorder.on_event({"type": "axis_pose", "ts": ts,
                               "positions": {"axis_9x": 100.0 + i * 0.5},
                               "velocities": {"axis_9x": 25.0}})
            if i % 10 == 0:
                recorder.on_event({"type": "mechanism_state", "ts": ts,
                                   "states": {"dev_t1_cyl1": {"commanded": bool((i // 10) % 2),
                                                         "confirmed": None,
                                                         "source": "feedback"}}})
        recorder.on_event({"type": "operation_start", "ts": T0 + 1, "run_id": "R1",
                           "operation": "collect"})
        recorder.on_event({"type": "operation_failed", "ts": T0 + 8, "run_id": "R1",
                           "operation": "collect", "message": "撞了"})
        _drain(recorder)
        recorder.stop()
        store.flush()

        app = FastAPI()
        app.state.recorder = recorder
        register_recording_routes(app)
        with TestClient(app) as c:
            yield c
    finally:
        store.close()


def test_status_reports_dropped_count(client):
    body = client.get("/api/recording/status").json()
    assert body["root"] and "dropped" in body, "录像有洞必须能被看到"
    assert body["coverage"]["chunks"] > 0


def test_sessions_and_coverage(client):
    sessions = client.get("/api/recording/sessions").json()["sessions"]
    assert len(sessions) == 1 and sessions[0]["kind"] == "real"
    coverage = client.get("/api/recording/coverage").json()
    assert coverage["t0"] <= T0 + 0.01 and coverage["t1"] >= T0 + 9.9


def test_state_at_returns_snapshot_without_replaying_from_start(client):
    body = client.get("/api/recording/state_at", params={"t": T0 + 7.0}).json()
    assert body["t"] == T0 + 7.0
    # 只解一块就能定位 —— 块自足是"拖动即到位"的前提
    assert body["chunk_t0"] <= T0 + 7.0
    assert body["chunk_t0"] >= T0 + 6.0 - 1e-6, "应落在 t 所在的那一块, 而不是从头累加"
    axis = body["state"]["streams"]["axis_pose"]["axis_9x.position"]
    assert axis == pytest.approx(100.0 + 140 * 0.5, abs=0.3)


def test_state_at_404_outside_coverage(client):
    assert client.get("/api/recording/state_at", params={"t": T0 - 500}).status_code == 404


def test_frames_columns_align_with_timestamps(client):
    body = client.get("/api/recording/frames",
                      params={"t0": T0, "t1": T0 + 4, "streams": "axis_pose"}).json()
    stream = body["streams"]["axis_pose"]
    n = len(stream["ts"])
    assert n > 0
    for key, column in stream["channels"].items():
        assert len(column) == n, f"{key} 列长与时间戳不等长会让回放出现瞬移"
    assert all(a < b for a, b in zip(stream["ts"], stream["ts"][1:])), "时间戳应递增"
    assert body["truncated"] is False


def test_frames_window_is_half_open(client):
    body = client.get("/api/recording/frames",
                      params={"t0": T0, "t1": T0 + 2, "streams": "axis_pose"}).json()
    stamps = body["streams"]["axis_pose"]["ts"]
    assert min(stamps) >= T0 and max(stamps) < T0 + 2


def test_frames_carry_keyframe_for_seek(client):
    body = client.get("/api/recording/frames", params={"t0": T0 + 4, "t1": T0 + 6}).json()
    assert "keyframe" in body and isinstance(body["keyframe"], dict)


def test_frames_rejects_absurd_window(client):
    r = client.get("/api/recording/frames", params={"t0": T0, "t1": T0 + 99999})
    assert r.status_code == 400
    assert client.get("/api/recording/frames",
                      params={"t0": T0 + 5, "t1": T0}).status_code == 400


def test_timeline_reports_which_stations_were_moving(client):
    """条上给的是"有几个工位在动", 不是块字节数。

    夹具里 axis_9x 一路在走 (拍照刮板工位)、dev_t1_cyl1 的 confirmed 恒为 None (展开工位
    的阀在途), 所以这两个工位必须双双上榜。
    """
    body = client.get("/api/recording/timeline",
                      params={"t0": T0, "t1": T0 + 10, "buckets": 10}).json()
    assert len(body["active"]) == 10 and len(body["stations"]) == 10
    assert body["modules_total"] >= 9, "8 个 PLC 工位 + 机器人"
    busy = [s for s in body["stations"] if s]
    assert busy, "夹具里设备明明在动"
    assert {"photoscrape", "develop"} <= set(busy[0])
    assert body["active"][0] == len(body["stations"][0])
    kinds = {m["kind"] for m in body["markers"]}
    assert "operation" in kinds and "alarm" in kinds, "事故追溯靠标记一键跳转"


def test_timeline_marks_unbackfilled_chunks_null_not_idle(client, tmp_path):
    """0 是"确实没动", null 是"还没补算过" —— 画成一样会让人得出相反结论。"""
    store = client.app.state.recorder.store
    with store._lock:
        store._conn.execute("DELETE FROM chunk_activity")
        store._conn.commit()
    body = client.get("/api/recording/timeline",
                      params={"t0": T0, "t1": T0 + 10, "buckets": 10}).json()
    assert all(v is None for v in body["active"])


def test_markers_filter_by_kind(client):
    body = client.get("/api/recording/markers",
                      params={"t0": T0, "t1": T0 + 10, "kinds": "alarm"}).json()
    assert body["markers"] and {m["kind"] for m in body["markers"]} == {"alarm"}
    assert body["markers"][0]["payload"]["message"] == "撞了"


def test_503_when_recording_disabled():
    app = FastAPI()
    app.state.recorder = None
    register_recording_routes(app)
    with TestClient(app) as c:
        assert c.get("/api/recording/status").status_code == 503


def test_tri_state_confirmed_survives_the_api(client):
    body = client.get("/api/recording/frames",
                      params={"t0": T0, "t1": T0 + 4, "streams": "mechanism_state"}).json()
    column = body["streams"]["mechanism_state"]["channels"]["dev_t1_cyl1.confirmed"]
    assert column and all(v is None for v in column), "None 是真实状态, 不能变成 False"


# -- 相机 / 溯源 / 导出 -------------------------------------------------

def test_camera_capture_becomes_a_marker_without_restoring_the_image(tmp_path):
    """拍照动作结果里本就带 image_path, 随 vm_node_done 入库; 不必另存一份图。"""
    store = RecordingStore(tmp_path / "cam")
    rec = StateRecorder(store, chunk_seconds=5.0)
    rec.start()
    try:
        rec.on_event({"type": "vm_node_done", "ts": T0 + 1, "run_id": "R1",
                      "action": "camera.shoot", "script": "collect",
                      "result": {"image_path": "vision_output/S1/after.jpg"}})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()

    marks = [m for m in store.markers_in_range(T0, T0 + 10) if m["kind"] == "camera"]
    assert len(marks) == 1
    assert marks[0]["payload"]["image_path"] == "vision_output/S1/after.jpg"
    store.close()


def test_provenance_separates_measured_from_estimated(client):
    """回放把推算值伪装成实测值, 对事故追溯比没有回放更糟。"""
    body = client.get("/api/recording/provenance", params={"t": T0 + 5}).json()
    mech = body["mechanisms"]
    assert mech["total"] > 0
    # 夹具里 confirmed 恒为 None(到位信号都不成立) -> 必须算推算
    assert "dev_t1_cyl1" in mech["estimated"]
    assert "dev_t1_cyl1" not in mech["measured"]
    assert 0.0 <= mech["measured_ratio"] <= 1.0
    assert body["pumps"]["measured"] is False
    assert "无位置回读" in body["pumps"]["reason"]


def test_export_returns_verbatim_chunks_with_digest(client):
    body = client.get("/api/recording/export",
                      params={"t0": T0, "t1": T0 + 10}).json()
    assert body["chunks"], "应导出至少一块"
    assert body["chunk_magic"] == "PTCDVR01"
    assert body["schema_ver"] >= 1
    import base64 as b64
    import hashlib
    for chunk in body["chunks"]:
        raw = b64.b64decode(chunk["data_b64"])
        assert raw.startswith(b"PTCDVR01"), "块必须原样导出, 不解码"
        assert hashlib.sha256(raw).hexdigest() == chunk["sha256"], "摘要要能证明是同一份"
        assert len(raw) == chunk["bytes"]


def test_export_chunks_are_independently_decodable_after_transfer(client):
    """导出到别的机器上必须能直接解 —— 块自足是这条的前提。"""
    from eit_ptlc.runtime.recording.codec import decode_chunk
    import base64 as b64
    body = client.get("/api/recording/export", params={"t0": T0, "t1": T0 + 10}).json()
    for entry in body["chunks"]:
        chunk = decode_chunk(b64.b64decode(entry["data_b64"]))
        assert chunk.t0 == entry["t0"]
        assert isinstance(chunk.keyframe, dict)


# -- 索引与磁盘失配 (本次 500 故障的直接回归) ---------------------------

def _delete_one_chunk_file(client) -> str:
    """删掉一块的文件但**保留索引行** —— 复现本次故障的现场。"""
    store = client.app.state.recorder.store
    meta = store.chunks_in_range(T0, T0 + 100)[0]
    (store.root / meta["path"]).unlink()
    return meta["path"]


def test_frames_survives_a_missing_chunk_file(client):
    """索引里有、磁盘上没有 —— 端点必须降级并如实报数, 而不是 500。

    这正是线上那次 `帧流读取失败: Request failed with status code 500` 的成因:
    手工清理过录像目录、index.db 被占用没删掉, 留下一堆指向空气的行。
    """
    _delete_one_chunk_file(client)
    r = client.get("/api/recording/frames", params={"t0": T0, "t1": T0 + 10})
    assert r.status_code == 200, "缺一块文件不该让整个端点炸掉"
    body = r.json()
    assert body["skipped"] == 1, "跳过几块必须写在响应里, 静默少给会被当成'机器没动'"
    assert body["frames"] > 0, "其余块仍应正常返回"


def test_state_at_walks_back_to_an_earlier_readable_chunk(client):
    """命中的块读不出时往前找, 而不是立刻 404 —— 关键帧是滚动合并的, 早一点也有用。"""
    store = client.app.state.recorder.store
    metas = store.chunks_in_range(T0, T0 + 100)
    assert len(metas) >= 2
    (store.root / metas[1]["path"]).unlink()
    r = client.get("/api/recording/state_at", params={"t": metas[1]["t1"] - 0.01})
    assert r.status_code == 200
    body = r.json()
    assert body["skipped"] == 1
    assert body["chunk_seq"] == metas[0]["seq"], "应退回到前一块"


def test_provenance_and_export_also_survive(client):
    _delete_one_chunk_file(client)
    prov = client.get("/api/recording/provenance", params={"t": T0 + 9.5})
    assert prov.status_code == 200

    exp = client.get("/api/recording/export", params={"t0": T0, "t1": T0 + 10})
    assert exp.status_code == 200
    body = exp.json()
    assert body["skipped"] == 1
    assert body["chunks"], "其余块仍应导出"


def test_state_at_404_when_nothing_readable(client):
    store = client.app.state.recorder.store
    for meta in store.chunks_in_range(T0, T0 + 100):
        (store.root / meta["path"]).unlink()
    r = client.get("/api/recording/state_at", params={"t": T0 + 5})
    assert r.status_code == 404
    assert "可读" in r.json()["detail"], "要说清楚是读不出来, 不是压根没录"


def test_reconcile_drops_orphan_rows_and_restores_coverage(client):
    """整理后 coverage 必须回到合理区间 —— 这是修复线上库的入口。"""
    store = client.app.state.recorder.store
    path = _delete_one_chunk_file(client)
    before = store.coverage()["chunks"]

    r = client.post("/api/recording/reconcile", params={"deep": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["chunks_dropped"] == 1
    assert store.coverage()["chunks"] == before - 1
    assert not any(m["path"] == path for m in store.chunks_in_range(T0, T0 + 100))

    # 整理完再查, 不该再有跳过
    assert client.get("/api/recording/frames",
                      params={"t0": T0, "t1": T0 + 10}).json()["skipped"] == 0


# -- 动作列表 (时间线右栏的数据源) ---------------------------------------

def _run_flow(rec, run_id="R1", base=T0):
    """跑一段带嵌套与控制流的流程事件, 形状照 VM 真实发的那套。"""
    rec.on_event({"type": "operation_start", "ts": base, "run_id": run_id, "operation": "collect"})
    rec.on_event({"type": "vm_node_enter", "ts": base + 1, "run_id": run_id, "op": "run_script",
                  "script": "collect", "aid": "s1", "action": "collect_sub"})
    rec.on_event({"type": "vm_node_enter", "ts": base + 2, "run_id": run_id, "op": "call",
                  "script": "collect_sub", "aid": "a1", "action": "robot.pick"})
    rec.on_event({"type": "vm_node_done", "ts": base + 5, "run_id": run_id, "op": "call",
                  "script": "collect_sub", "aid": "a1", "action": "robot.pick", "status": "DONE"})
    # 控制流不该成步
    rec.on_event({"type": "vm_node_enter", "ts": base + 6, "run_id": run_id, "op": "for",
                  "script": "collect_sub", "aid": "f1"})
    rec.on_event({"type": "vm_node_done", "ts": base + 7, "run_id": run_id, "op": "for",
                  "script": "collect_sub", "aid": "f1", "status": "DONE"})
    rec.on_event({"type": "vm_node_done", "ts": base + 8, "run_id": run_id, "op": "run_script",
                  "script": "collect", "aid": "s1", "action": "collect_sub", "status": "DONE"})


def test_actions_pairs_start_and_done(tmp_path):
    store = RecordingStore(tmp_path / "act")
    rec = StateRecorder(store, chunk_seconds=60.0)
    rec.start()
    try:
        _run_flow(rec)
        _drain(rec)
    finally:
        rec.stop()
    store.flush()

    app = FastAPI()
    app.state.recorder = rec
    register_recording_routes(app)
    with TestClient(app) as c:
        body = c.get("/api/recording/actions", params={"t0": T0, "t1": T0 + 60}).json()
    actions = body["actions"]
    by_aid = {a["aid"]: a for a in actions}

    assert "f1" not in by_aid, "控制流 for 不该成步 —— 否则 100 次循环写进 200 行标记"
    assert set(by_aid) == {"s1", "a1"}
    assert by_aid["a1"]["action"] == "robot.pick"
    assert by_aid["a1"]["done_ts"] == pytest.approx(T0 + 5, abs=1e-3)
    assert by_aid["a1"]["duration"] == pytest.approx(3.0, abs=1e-3)
    assert by_aid["a1"]["status"] == "DONE"
    assert by_aid["s1"]["op"] == "run_script"
    store.close()


def test_actions_unclosed_start_reports_running(tmp_path):
    store = RecordingStore(tmp_path / "act2")
    rec = StateRecorder(store, chunk_seconds=60.0)
    rec.start()
    try:
        rec.on_event({"type": "vm_node_enter", "ts": T0, "run_id": "R1", "op": "call",
                      "script": "s", "aid": "a1", "action": "robot.move"})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()
    app = FastAPI()
    app.state.recorder = rec
    register_recording_routes(app)
    with TestClient(app) as c:
        actions = c.get("/api/recording/actions",
                        params={"t0": T0 - 1, "t1": T0 + 10}).json()["actions"]
    assert len(actions) == 1
    assert actions[0]["done_ts"] is None
    assert actions[0]["status"] == "RUNNING", "还在跑的动作要看得出来"
    store.close()


def test_actions_recursion_same_aid_does_not_cross(tmp_path):
    """递归/并行会让同一个 aid 重入; 必须 LIFO 配最近一个未闭合的, 否则首尾串台。"""
    store = RecordingStore(tmp_path / "act3")
    rec = StateRecorder(store, chunk_seconds=60.0)
    rec.start()
    try:
        for ts in (T0, T0 + 1):
            rec.on_event({"type": "vm_node_enter", "ts": ts, "run_id": "R1", "op": "call",
                          "script": "s", "aid": "a1", "action": "x"})
        rec.on_event({"type": "vm_node_done", "ts": T0 + 2, "run_id": "R1", "op": "call",
                      "script": "s", "aid": "a1", "action": "x", "status": "DONE"})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()
    app = FastAPI()
    app.state.recorder = rec
    register_recording_routes(app)
    with TestClient(app) as c:
        actions = c.get("/api/recording/actions",
                        params={"t0": T0 - 1, "t1": T0 + 10}).json()["actions"]
    assert len(actions) == 2
    # 纪元秒必须用绝对容差: pytest.approx 默认是 1e-6 **相对**容差, 在 1.786e9 上
    # 等于 ±1786 秒, 两条记录会互相匹配, 断言形同虚设。
    actions.sort(key=lambda a: a["ts"])
    outer, inner = actions
    assert inner["ts"] == pytest.approx(T0 + 1, abs=1e-3)
    assert inner["done_ts"] == pytest.approx(T0 + 2, abs=1e-3), "该闭合的是内层那次"
    assert outer["done_ts"] is None


def test_index_endpoints_accept_windows_far_beyond_one_hour(client):
    """缩放到全览的前提。/timeline 只读索引行, 当初被 /frames 的上限连坐了。"""
    wide = {"t0": T0, "t1": T0 + 20 * 86400}
    assert client.get("/api/recording/timeline", params={**wide, "buckets": 100}).status_code == 200
    assert client.get("/api/recording/markers", params=wide).status_code == 200
    assert client.get("/api/recording/actions", params=wide).status_code == 200
    # 但要解块的仍然必须拒绝: 一小时的帧解出来就是几十 MB
    assert client.get("/api/recording/frames", params=wide).status_code == 400
    assert client.get("/api/recording/export", params=wide).status_code == 400


def test_status_exposes_chunk_seconds(client):
    """前端据此把"尚未落盘的那一小段"画成独立区域(那段 state_at 会 404)。"""
    assert client.get("/api/recording/status").json()["chunk_seconds"] > 0


def test_history_returns_incremental_events_in_ascending_order(client):
    """派生态重建的数据源: 板在谁手里/托盘挂载/夹爪持握都靠重放这批事件。"""
    body = client.get("/api/recording/history", params={"t": T0 + 9}).json()
    types = [e["type"] for e in body["events"]]
    assert "operation_start" in types and "operation_failed" in types
    stamps = [e["ts"] for e in body["events"]]
    assert stamps == sorted(stamps), "必须升序: 宿主是按顺序重放的"
    assert body["truncated"] is False


def test_history_excludes_frames_and_snapshot_only_events(client):
    """帧流走列式编码、快照类由关键帧表达 —— 都不该再进历史, 否则一天几百万条。"""
    body = client.get("/api/recording/history", params={"t": T0 + 20}).json()
    types = {e["type"] for e in body["events"]}
    assert not (types & {"axis_pose", "robot_pose", "mechanism_state", "signal_light",
                         "telemetry", "material_state"})


def test_history_stops_at_the_cursor(client):
    """t 之后的事件一条都不许给: 回放到 T0+2 却带着 T0+8 的失败, 就是在说谎。"""
    body = client.get("/api/recording/history", params={"t": T0 + 2}).json()
    assert [e["type"] for e in body["events"]] == ["operation_start"]


def test_history_truncation_keeps_the_newest(client):
    """派生态是"最后一次写赢", 撞上限时该留最近的那批而不是最早的。"""
    body = client.get("/api/recording/history", params={"t": T0 + 9, "limit": 1}).json()
    assert body["truncated"] is True
    assert [e["type"] for e in body["events"]] == ["operation_failed"]


def test_history_404_when_no_recording_at_that_moment(client):
    assert client.get("/api/recording/history", params={"t": T0 - 86400}).status_code == 404


def test_timeline_distinguishes_a_recording_gap_from_an_idle_machine(client):
    """没录到 != 没动。把录像空洞画成"空闲", 等于用一段空白证明设备当时是好的。"""
    body = client.get("/api/recording/timeline",
                      params={"t0": T0 - 100, "t1": T0 + 10, "buckets": 11}).json()
    # 前 10 个桶落在录像开始之前 —— 无块可依, covered 必须是 False
    assert body["covered"][0] is False and body["active"][0] is None
    assert body["covered"][-1] is True, "最后一个桶有录像"


def _manual_op(rec, ts, run_id, name):
    """复刻真机手动操作发的三条事件 —— 注意它**不发 step_start**。

    实测 (18080 真机录像, 08-13):
        operation_start  {operation: manual.session}
        step_done        {action: manual.session, step: m1, status: DONE}
        operation_done   {operation: manual.session, status: DONE}
    三条同一秒。原先 /actions 只读 ["action","step"], 于是那条孤零零的 step_done 被
    当成一个永不闭合的 start, 前端把它画成横贯整个时间轴的假长条。
    """
    rec.on_event({"type": "operation_start", "ts": ts, "run_id": run_id, "operation": name})
    rec.on_event({"type": "step_done", "ts": ts, "run_id": run_id,
                  "action": name, "step": "m1", "status": "DONE"})
    rec.on_event({"type": "operation_done", "ts": ts + 0.02, "run_id": run_id,
                  "operation": name, "status": "DONE"})


def test_actions_include_manual_operations_that_never_send_step_start(tmp_path):
    """手动操作只有 operation 层。读不到它, 泳道里这类操作就整个消失。"""
    store = RecordingStore(tmp_path / "manual")
    rec = StateRecorder(store, chunk_seconds=60.0)
    rec.start()
    try:
        _manual_op(rec, T0 + 1, "manual-1", "manual.session")
        _manual_op(rec, T0 + 3, "manual-2", "manual.cylinder.dev_t1_cyl1")
        _drain(rec)
    finally:
        rec.stop()
    store.flush()

    app = FastAPI()
    app.state.recorder = rec
    register_recording_routes(app)
    with TestClient(app) as c:
        actions = c.get("/api/recording/actions",
                        params={"t0": T0, "t1": T0 + 60}).json()["actions"]
    assert [a["action"] for a in actions] == ["manual.session", "manual.cylinder.dev_t1_cyl1"]
    assert all(a["done_ts"] is not None for a in actions), "operation 层首尾是齐的, 必须闭合"
    assert all(a["duration"] == pytest.approx(0.02, abs=1e-3) for a in actions)
    store.close()


def test_actions_take_the_finest_layer_per_run(tmp_path):
    """脚本运行同时有 operation 与 vm_node 两层, 只留细的那层。

    两层同时画会让同一件事在两行里出现两遍(名字还一样), 那不是层次, 是重复。
    """
    store = RecordingStore(tmp_path / "fine")
    rec = StateRecorder(store, chunk_seconds=60.0)
    rec.start()
    try:
        # 一个脚本运行: 外层 operation + 内层 vm_node
        rec.on_event({"type": "operation_start", "ts": T0 + 1, "run_id": "R1",
                      "operation": "robot.pick"})
        rec.on_event({"type": "vm_node_enter", "ts": T0 + 1, "run_id": "R1", "op": "call",
                      "action": "robot.pick", "script": "collect", "aid": "a1"})
        rec.on_event({"type": "vm_node_done", "ts": T0 + 4, "run_id": "R1", "op": "call",
                      "action": "robot.pick", "script": "collect", "aid": "a1",
                      "status": "DONE"})
        rec.on_event({"type": "operation_done", "ts": T0 + 4, "run_id": "R1",
                      "operation": "robot.pick", "status": "DONE"})
        # 另一个运行只有 operation 层
        _manual_op(rec, T0 + 10, "manual-9", "manual.session")
        _drain(rec)
    finally:
        rec.stop()
    store.flush()

    app = FastAPI()
    app.state.recorder = rec
    register_recording_routes(app)
    with TestClient(app) as c:
        actions = c.get("/api/recording/actions",
                        params={"t0": T0, "t1": T0 + 60}).json()["actions"]
    by_run = {}
    for a in actions:
        by_run.setdefault(a["run_id"], []).append(a)
    assert len(by_run["R1"]) == 1, "有 vm_node 的运行不许再画一条 operation 的重复段"
    assert by_run["R1"][0]["kind"] == "action"
    assert by_run["R1"][0]["aid"] == "a1"
    assert len(by_run["manual-9"]) == 1, "没有 vm_node 的运行要用 operation 层兜住"
    assert by_run["manual-9"][0]["kind"] == "operation"
    store.close()


def test_unclosed_action_stops_at_the_end_of_evidence(tmp_path):
    """未闭合动作要给出"证据止于何时", 而不是让前端拿视窗右缘去补。

    交给前端补的直接后果是**段长随缩放变化**: 缩到 1.3 天时, 一条 27 小时前没闭合的
    动作会画成一条横贯整个时间轴的色带。段的长度必须来自数据。
    """
    store = RecordingStore(tmp_path / "open")
    rec = StateRecorder(store, chunk_seconds=60.0)
    session = rec.start()
    try:
        rec.on_event({"type": "vm_node_enter", "ts": T0 + 1, "run_id": "R1", "op": "call",
                      "action": "robot.move", "script": "collect", "aid": "a1"})
        _drain(rec)
    finally:
        rec.stop()          # 会话就此结束 —— 证据止于此
    store.flush()
    ended = store.list_sessions()[0]["ended_at"]

    app = FastAPI()
    app.state.recorder = rec
    register_recording_routes(app)
    with TestClient(app) as c:
        actions = c.get("/api/recording/actions",
                        params={"t0": T0, "t1": T0 + 60}).json()["actions"]
    assert len(actions) == 1
    assert actions[0]["done_ts"] is None, "确实没看到它结束"
    # 这条 start 就是该运行的最后一条标记 —— 证据到此为止, 段宽退化成一个点
    assert actions[0]["open_until"] == pytest.approx(T0 + 1, abs=1e-3)
    assert actions[0]["open_until"] < ended, "会话又录了很久, 但那不是这个运行的证据"
    assert session.id
    store.close()


def test_unclosed_action_still_alive_extends_to_the_runs_last_sign_of_life(tmp_path):
    """被打断的运行: 证据止于我们最后一次看见它有动静, 而不是会话结束。"""
    store = RecordingStore(tmp_path / "open2")
    rec = StateRecorder(store, chunk_seconds=60.0)
    rec.start()
    try:
        rec.on_event({"type": "vm_node_enter", "ts": T0 + 1, "run_id": "R1", "op": "call",
                      "action": "robot.move", "script": "collect", "aid": "a1"})
        # 同一运行后来还跑过一步(有始有终), 之后整个运行被打断
        rec.on_event({"type": "vm_node_enter", "ts": T0 + 5, "run_id": "R1", "op": "call",
                      "action": "robot.grip", "script": "collect", "aid": "a2"})
        rec.on_event({"type": "vm_node_done", "ts": T0 + 6, "run_id": "R1", "op": "call",
                      "action": "robot.grip", "script": "collect", "aid": "a2",
                      "status": "DONE"})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()

    app = FastAPI()
    app.state.recorder = rec
    register_recording_routes(app)
    with TestClient(app) as c:
        actions = c.get("/api/recording/actions",
                        params={"t0": T0, "t1": T0 + 60}).json()["actions"]
    outer = next(a for a in actions if a["aid"] == "a1")
    assert outer["done_ts"] is None
    assert outer["open_until"] == pytest.approx(T0 + 6, abs=1e-3), "止于该运行最后一条标记"
    store.close()
