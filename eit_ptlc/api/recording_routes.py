"""状态录像 (3D DVR) 路由
========================
功能:
    把设备状态录像的检索与回放端点注册到 FastAPI 应用。录像内容是三维场景所需的完整
    状态向量 (11 轴 / 55 机构 / 机器人位姿 / 信号灯 / 物料账本 / 运行事件), 回放时由
    前端合成同构事件喂回实时渲染链, 因而画面与当时 1:1。

    解码放在服务端: 前端没有任何压缩/解码依赖也没有 Web Worker, 与其给浏览器塞一个
    zstd 解码器和一条 worker 链路, 不如服务端解好再以普通 JSON 发出。8 倍速回放约
    450 KB/s, 局域网无压力。

端点 (前缀 /api/recording):
    GET  /status                     录制器健康度 (含 dropped —— 录像有洞必须如实报)
    POST /start                      开始录制 (已在录则原样返回)
    POST /stop                       停止录制并把最后一块落盘
    GET  /sessions?since=&until=     录像会话列表 (半开区间纪元秒, 同 /api/runs 约定)
    GET  /timeline?t0=&t1=           工位利用率条 + 标记层, 画 DVR 日历条用
    GET  /state_at?t=                该时刻的完整状态快照 (由块关键帧解算), 秒级 seek
    GET  /history?t=                 该时刻之前的增量事件流, 供 seek 重建派生态
    GET  /frames?t0=&t1=             时间窗内的帧流, 供播放预取
    GET  /markers?t0=&t1=&kinds=     时间窗内的标记 (报警/流程/人工干预/抓拍)
    GET  /actions?t0=&t1=            时间窗内的动作区间 (首尾已配对), 供动作泳道
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time

from fastapi import FastAPI, HTTPException, Request

from eit_ptlc.runtime.recording.codec import CHUNK_MAGIC, decode_chunk, is_missing
from eit_ptlc.runtime.recording.store import SCHEMA_VERSION

log = logging.getLogger(__name__)


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


# 已经就"索引里有、磁盘上没有"告过警的会话; 每个只喊一次, 不刷屏
_WARNED_SESSIONS: set[str] = set()


def _read_chunk(store, meta: dict):
    """读并解一块; 读不出来返回 None 而不是抛。

    索引与磁盘分家有太多正当原因: 人工清理过录像目录、盘损、只拷了会话目录没拷索引、
    保留策略删到一半被打断。DVR 在这种时候的正确行为是**少给几块并说清楚少了几块**,
    而不是整个端点 500 —— 后者会让"录像到底还在不在"这个最该被回答的问题也答不出来,
    而用户看到的只是一句 "Request failed with status code 500"。
    """
    try:
        return decode_chunk(store.read_chunk(meta["path"]))
    except (FileNotFoundError, OSError, ValueError) as exc:
        session = str(meta.get("session_id") or "")
        if session not in _WARNED_SESSIONS:
            _WARNED_SESSIONS.add(session)
            log.warning("[dvr] 块读取失败(该会话仅告警一次) %s: %s —— "
                        "可 POST /api/recording/reconcile 整理索引",
                        meta.get("path"), exc)
        return None


def _chunk_at_or_before(store, t: float, session_id: str | None, *, max_back: int = 8):
    """取 t 所在或之前最近的**可读**块, 返回 (meta, chunk, 跳过数)。

    往前退是有限步的: 索引整块坏掉时不该把整条时间轴扫一遍, 退不到就老实说没有。
    """
    cursor = t
    skipped = 0
    for _ in range(max_back):
        meta = store.chunk_before(cursor, session_id=session_id)
        if meta is None:
            return None, None, skipped
        chunk = _read_chunk(store, meta)
        if chunk is not None:
            return meta, chunk, skipped
        skipped += 1
        # 退到这一块起点之前, 否则会原地打转
        cursor = float(meta["t0"]) - 1e-6
    return None, None, skipped


def _stations_of(chunk: dict) -> list[str]:
    """块行里的工位清单 (存的是 JSON 文本)。"""
    raw = chunk.get("stations")
    if not raw:
        return []
    try:
        names = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(n) for n in names] if isinstance(names, list) else []


def _load_chunks(store, metas) -> tuple[list, int]:
    """解一批块, 返回 ([(meta, chunk), …], 跳过的块数)。

    调用方必须把跳过数如实放进响应体: 静默少几块会让人以为"当时机器就没动"。
    """
    out = []
    skipped = 0
    for meta in metas:
        chunk = _read_chunk(store, meta)
        if chunk is None:
            skipped += 1
        else:
            out.append((meta, chunk))
    return out, skipped


# 单次 /frames 允许返回的最大帧数。回放是按窗口预取的, 没有理由一次拉一整天;
# 不设上限的话前端一个手滑的时间范围就能把后端拖到 OOM。
_MAX_FRAMES = 60000
# 要**解块**的端点(/frames, /export)才需要这个上限: 一小时的帧解出来就是几十 MB。
_MAX_WINDOW_S = 3600.0
# 只读索引行的端点(/timeline, /markers, /actions)完全不受它约束 —— 实测 3~13 ms。
# 当初把它们也卡在 3600 秒是从 /frames 抄错的, 直接后果是时间轴缩放不到全览, 而前端
# 为了绕开它只取前一小时却按全宽渲染, 于是 24.8 小时的录像上密度条整个是错的。
_MAX_INDEX_WINDOW_S = 32 * 86400.0


def register_recording_routes(app: FastAPI, *, prefix: str = "/api/recording",
                              recorder_getter=None) -> None:
    """注册状态录像路由。

    参数:
        app: FastAPI 应用; prefix: 端点前缀
        recorder_getter: (request) -> StateRecorder; 缺省取 app.state.recorder
    """

    def _default_recorder(request: Request):
        recorder = getattr(request.app.state, "recorder", None)
        if recorder is None:
            raise HTTPException(503, "状态录制未启用 (PTLC_RECORD_ENABLED=0 或启动失败)")
        return recorder

    _recorder = recorder_getter or _default_recorder

    def _store(request: Request):
        return _recorder(request).store

    def _window(t0: float, t1: float, *, limit: float = _MAX_WINDOW_S) -> tuple[float, float]:
        if t1 <= t0:
            raise HTTPException(400, "t1 必须大于 t0")
        if t1 - t0 > limit:
            raise HTTPException(400, f"时间窗最大 {limit:.0f} 秒, 请分段拉取")
        return float(t0), float(t1)

    # -- 录制器控制 ---------------------------------------------------

    @app.get(f"{prefix}/status")
    async def recording_status(request: Request):
        return _recorder(request).status()

    @app.post(f"{prefix}/start")
    async def recording_start(request: Request, body: dict | None = None):
        recorder = _recorder(request)
        if recorder.running:
            return {"started": False, "reason": "已在录制", **recorder.status()}
        note = str((body or {}).get("note") or "手动开始")
        recorder.start(note=note)
        return {"started": True, **recorder.status()}

    @app.post(f"{prefix}/stop")
    async def recording_stop(request: Request):
        recorder = _recorder(request)
        if not recorder.running:
            return {"stopped": False, "reason": "未在录制", **recorder.status()}
        recorder.stop()
        return {"stopped": True, **recorder.status()}

    @app.post(f"{prefix}/reconcile")
    async def recording_reconcile(request: Request, deep: bool = False):
        """把索引与磁盘对齐 —— 不必重启上位机即可修复"读到空气"的录像库。

        deep=true 会逐块核对文件是否还在(30 天录像约 26 万行, 需要几秒), 默认只做
        便宜的会话级与坏时间戳清理。
        """
        recorder = _recorder(request)
        session = recorder.status().get("session") or {}
        result = recorder.store.reconcile(deep=bool(deep),
                                          active_session_id=session.get("id"))
        # 之前告过警的会话在整理后应重新允许告警, 否则修完再坏就没人提醒了
        _WARNED_SESSIONS.clear()
        log.info("[dvr] 人工整理索引 deep=%s: %s", deep,
                 {k: v for k, v in result.items() if k != "coverage"})
        return result

    # -- 检索 ---------------------------------------------------------

    @app.get(f"{prefix}/sessions")
    async def recording_sessions(request: Request, since: float | None = None,
                                 until: float | None = None, kind: str | None = None,
                                 limit: int = 200):
        return {"sessions": _store(request).list_sessions(
            since=since, until=until, kind=kind, limit=min(int(limit), 1000))}

    @app.get(f"{prefix}/coverage")
    async def recording_coverage(request: Request):
        """录像覆盖到的时间范围与总量 —— 时间轴画可拖动区间要先知道它。"""
        return _store(request).coverage()

    @app.get(f"{prefix}/markers")
    async def recording_markers(request: Request, t0: float, t1: float,
                                kinds: str | None = None, limit: int = 5000):
        t0, t1 = _window(t0, t1, limit=_MAX_INDEX_WINDOW_S)
        kind_list = [k for k in (kinds or "").split(",") if k] or None
        return {"markers": _store(request).markers_in_range(
            t0, t1, kinds=kind_list, limit=min(int(limit), 20000))}

    @app.get(f"{prefix}/actions")
    async def recording_actions(request: Request, t0: float, t1: float, limit: int = 5000):
        """时间窗内的动作区间(首尾已配对), 供时间线的动作泳道用。

        为什么不让前端自己配: 标记是首尾两行分开存的, 配对要按 (run_id, script, aid)
        且**后进先出** —— 递归/并行会让同一个 aid 重入, 这与 stores/runs.js 里
        run_script 完成时反向搜栈是同一个道理。这段逻辑只该有一处实现。

        为什么不扫块里的事件流: 实测块内非帧事件 61.4 万条里 99.8% 是 telemetry,
        扫它找动作完全不可行; 而标记表按 ts 建了索引, 同期只有几十行。

        **收 action 与 operation 两层, 每个运行取它记到的最细那层。**
        实测真机数据: 手动操作 (manual.session / manual.cylinder.*) 只发
        operation_start + step_done + operation_done —— 压根没有 step_start。所以
        原先只读 ["action","step"] 会把 12 条 step_done 全当成未闭合的 start。而
        operation 层每次操作都是完整的首尾一对。两层同时收又会让脚本流程的同一件事
        画两遍(实测 16 个 vm_node 对 9 个 operation, 名字还一样), 所以按运行取细的
        那层: 有 vm_node 就用 vm_node, 没有才用 operation。step 层彻底不用 —— 它在
        真实数据里本来就是残的。
        """
        t0, t1 = _window(t0, t1, limit=_MAX_INDEX_WINDOW_S)
        rows = _store(request).markers_in_range(
            t0, t1, kinds=["action", "operation"], limit=min(int(limit) * 2, 20000))
        # 未闭合动作的"证据末端"。绝不能交给前端拿视窗右缘去补 —— 那样段长会随缩放
        # 变化, 缩到 1.3 天时一条 27 小时前没闭合的动作会横贯整个时间轴。
        #
        # 取两个上界里更紧的那个:
        #   会话结束(还在录就是现在) —— 会话没了, 它不可能还在跑;
        #   该运行**最后一条标记** —— 这是我们最后一次看见这个运行有动静。
        # 后者才是真正紧的界: 一个跑了 1 小时就被打断的运行, 哪怕会话又录了 26 小时,
        # 它的证据也只到被打断那一刻。若这条未闭合动作本身就是该运行的最后一条标记,
        # open_until 就等于它自己的时刻 —— 画成一个最小宽的斜纹块, 如实表达
        # "看见它开始了, 之后这个运行再没有任何消息"。
        session_end = {s["id"]: s["ended_at"] for s in _store(request).list_sessions(limit=1000)}
        now = time.time()
        last_ts_by_run: dict = {}
        for row in rows:
            run = row.get("run_id")
            if row["ts"] > last_ts_by_run.get(run, 0.0):
                last_ts_by_run[run] = row["ts"]

        open_stack: dict[tuple, list[dict]] = {}
        out: list[dict] = []
        for row in rows:
            payload = row.get("payload") or {}
            key = (row["kind"], row.get("run_id"), payload.get("script"), payload.get("aid"))
            if payload.get("phase") == "done":
                stack = open_stack.get(key)
                if stack:
                    item = stack.pop()          # LIFO: 配最近一个未闭合的
                    item["done_ts"] = row["ts"]
                    item["duration"] = round(row["ts"] - item["ts"], 3)
                    item["status"] = payload.get("status") or item["status"]
                    item["open_until"] = None
                    if payload.get("message"):
                        item["message"] = payload["message"]
                continue
            ended = session_end.get(row.get("session_id"))
            evidence = min(float(ended) if ended else now,
                           last_ts_by_run.get(row.get("run_id"), row["ts"]))
            item = {
                "kind": row["kind"],
                "run_id": row.get("run_id"), "script": payload.get("script"),
                "aid": payload.get("aid"), "op": payload.get("op"),
                "action": payload.get("action") or row.get("label"),
                "status": payload.get("status") or "RUNNING",
                "ts": row["ts"], "done_ts": None, "duration": None,
                "open_until": max(evidence, row["ts"]),
            }
            out.append(item)
            open_stack.setdefault(key, []).append(item)

        # 每个运行取最细那层: 有 vm_node(kind=action) 就丢掉同一运行的 operation 行
        fine_runs = {a["run_id"] for a in out if a["kind"] == "action"}
        out = [a for a in out if a["kind"] == "action" or a["run_id"] not in fine_runs]
        out.sort(key=lambda a: a["ts"])

        return {"t0": t0, "t1": t1, "actions": out[:int(limit)],
                # 截断要说出来: 静默截断会让人以为"当时就只跑了这些"
                "truncated": len(out) > int(limit)}

    @app.get(f"{prefix}/timeline")
    async def recording_timeline(request: Request, t0: float, t1: float, buckets: int = 240):
        """设备利用率条 + 标记层。

        每桶给的是**那段时间里同时有几个工位在动**(9 个模块: 8 个 PLC 工位 + 机器人),
        以及具体是哪几个。原先画的是块字节数 —— "动得越多差分越大"听着成立, 实际上
        连续录制下字节数近似常量, 整条是一样高的噪声, 看图的人得不到任何信息。

        每桶要能分出**四种**状态, 混起来就会让人得出相反结论:
            covered=False           该时段根本没有录像 (上位机没开/掉过链子)
            covered=True, active=None   有块但还没补算过活动度
            active=0                有录像, 设备确实空闲
            active>0                有几个工位在动
        尤其是头两种: 都画成"空闲"就等于把一段录像空洞说成"当时机器没动"。
        """
        t0, t1 = _window(t0, t1, limit=_MAX_INDEX_WINDOW_S)
        store = _store(request)
        buckets = max(1, min(int(buckets), 2000))
        width = (t1 - t0) / buckets
        active: list[int | None] = [None] * buckets
        covered = [False] * buckets
        stations: list[list[str]] = [[] for _ in range(buckets)]
        for chunk in store.chunks_in_range(t0, t1):
            # 一块可能跨多个桶。这里取**并集**而不是按重叠比例摊 —— 活动度是"有没有
            # 在动", 不是可以线性摊分的量; 摊了会让一次跨桶的动作在两侧都变成半高。
            first = max(0, int((chunk["t0"] - t0) / width))
            last = min(buckets - 1, int((chunk["t1"] - t0) / width))
            names = _stations_of(chunk)
            for b in range(first, last + 1):
                covered[b] = True
                if chunk.get("active") is None:
                    continue
                merged = set(stations[b]) | set(names)
                stations[b] = sorted(merged)
                active[b] = len(merged)
        status = _recorder(request).status()
        return {
            "t0": t0, "t1": t1, "buckets": buckets, "bucket_seconds": width,
            "active": active,
            "covered": covered,
            "stations": stations,
            # 归一化分母: 前端据此把"3 个在动"画成 3/9 高, 而不是按窗口峰值缩放 ——
            # 按峰值缩放会让"只有一根轴动过"的一小时看起来跟满负荷一样满。
            "modules_total": status.get("modules_total") or 1,
            "markers": store.markers_in_range(t0, t1),
        }

    # -- 回放 ---------------------------------------------------------

    @app.get(f"{prefix}/state_at")
    async def recording_state_at(request: Request, t: float, session_id: str | None = None):
        """t 时刻的完整状态快照。

        取 t 所在块的关键帧, 再把块内 <= t 的帧向前叠加 —— 因为块是自足的, 这一步只
        需解一块, 与 t 距离录像起点多远无关。这正是"拖动即到位"的实现。
        """
        store = _store(request)
        # 命中的那一块可能读不出(索引与磁盘失配)。此时继续往前找上一块 —— 关键帧是
        # 滚动合并出来的, 用稍早一点的那份仍然比直接 404 有用得多。
        meta, chunk, skipped = _chunk_at_or_before(store, float(t), session_id)
        if chunk is None:
            raise HTTPException(404, "该时刻没有可读的录像" if skipped else "该时刻没有录像")
        state = dict(chunk.keyframe)
        applied = 0
        for stream, data in chunk.streams.items():
            latest: dict = {}
            for i, ts in enumerate(data["ts"]):
                if ts > t:
                    break
                for key, values in data["channels"].items():
                    value = values[i]
                    if not is_missing(value):
                        latest[key] = value
                applied += 1
            if latest:
                state.setdefault("streams", {})[stream] = latest
        return {
            "t": float(t),
            "session_id": meta["session_id"],
            "chunk_seq": meta["seq"],
            "chunk_t0": meta["t0"],
            "frames_applied": applied,
            "skipped": skipped,
            "state": state,
        }

    @app.get(f"{prefix}/history")
    async def recording_history(request: Request, t: float, limit: int = 20000):
        """t 之前(含)的增量事件流, 供 seek 重建**派生态**。

        为什么必须有这一条: 板在谁手里、托盘挂载、夹爪持握都不是后端能看到的量, 它们
        是浏览器按事件历史算出来的。state_at 只给块关键帧, 于是跳转之后这些锁存态全
        丢 —— 回放到机器人正端着板的那一刻, 板会掉回料仓原位。录制侧的设计本来就写着
        "块关键帧 -> 连续量瞬间到位; 自会话起点快进低频事件流 -> 重建派生态", 这是后
        半句的实现。

        限定在 t 所在的会话内: 跨会话重放没有意义, 中间隔着一次上位机重启, 那一刻机器
        上有什么、夹爪里有什么, 录像本来就答不上来。
        """
        store = _store(request)
        meta = store.chunk_before(float(t), session_id=None)
        if meta is None:
            raise HTTPException(404, "该时刻没有录像")
        events, truncated = store.lowfreq_before(
            meta["session_id"], float(t), limit=max(1, min(int(limit), 50000)))
        return {
            "t": float(t),
            "session_id": meta["session_id"],
            "events": events,
            # 截断了要说出来: 派生态可能因此不完整, 界面上是"板莫名其妙不在手里"
            "truncated": truncated,
        }

    @app.get(f"{prefix}/provenance")
    async def recording_provenance(request: Request, t: float):
        """该时刻各机构的**来源**构成: 实测 / 推算 / 冲突。

        事故追溯的硬要求。回放若把推算值伪装成实测值, 比没有回放更糟 —— 看图的人会
        据此下判断。已知非实测的有:
          · 注射泵柱塞位置: 真机泵没有位置回读, 全程是包络推算;
          · 机构反馈过期时回落到指令值 (confirmed 为 None 即"两个到位信号都不成立");
          · 55 个机构里 35 个是 data-only, 只有状态没有几何, 本就不参与动画。
        """
        store = _store(request)
        meta, chunk, skipped = _chunk_at_or_before(store, float(t), None)
        if chunk is None:
            raise HTTPException(404, "该时刻没有可读的录像" if skipped else "该时刻没有录像")
        mechanisms = chunk.keyframe.get("mechanisms") or {}

        measured, estimated, conflict = [], [], []
        for mech_id, record in mechanisms.items():
            source = record.get("source")
            if source == "feedback_conflict":
                conflict.append(mech_id)
            elif record.get("confirmed") is None or source != "feedback":
                # confirmed=None 是"运动途中/到位信号都不成立", 前端据此回退 commanded
                estimated.append(mech_id)
            else:
                measured.append(mech_id)

        total = len(mechanisms)
        return {
            "t": float(t),
            "skipped": skipped,
            "mechanisms": {
                "total": total,
                "measured": sorted(measured),
                "estimated": sorted(estimated),
                "conflict": sorted(conflict),
                "measured_ratio": round(len(measured) / total, 4) if total else 0.0,
            },
            # 泵是构造性推算, 不随时刻变 —— 如实标出来而不是留给看图的人去猜
            "pumps": {"measured": False,
                      "reason": "真机注射泵无位置回读, 柱塞位置全程由动作包络推算"},
        }

    @app.get(f"{prefix}/export")
    async def recording_export(request: Request, t0: float, t1: float):
        """导出时间窗的原始块 + 标记, 供取证与跨机回放。

        块原样吐出(不解码): 目标机器上用同一个解码器即可回放, 且字节级可比对 ——
        取证场景下"我导出的和你那边的是同一份"必须能证明。
        """
        t0, t1 = _window(t0, t1)
        store = _store(request)
        metas = store.chunks_in_range(t0, t1)
        chunks = []
        skipped = 0
        for meta in metas:
            try:
                blob = store.read_chunk(meta["path"])
            except (FileNotFoundError, OSError):
                # 取证导出更不能整个失败: 少了哪几块必须写在结果里让人看见
                skipped += 1
                continue
            chunks.append({
                "seq": meta["seq"], "session_id": meta["session_id"],
                "t0": meta["t0"], "t1": meta["t1"], "bytes": len(blob),
                "sha256": _sha256(blob),
                "data_b64": base64.b64encode(blob).decode("ascii"),
            })
        return {
            "t0": t0, "t1": t1,
            "schema_ver": SCHEMA_VERSION,
            "chunk_magic": CHUNK_MAGIC.decode("ascii"),
            "chunks": chunks,
            "skipped": skipped,
            "markers": store.markers_in_range(t0, t1),
        }

    @app.get(f"{prefix}/frames")
    async def recording_frames(request: Request, t0: float, t1: float,
                               streams: str | None = None,
                               session_id: str | None = None):
        """时间窗内的帧流。

        每个流各自返回 {ts: [...], channels: {id: [...]}} —— 保持列式而不是摊成一帧
        一个对象, 因为前端拿到后就是按通道喂给各个 buffer 的, 列式省掉一次转置, 也
        省掉几十万个临时对象。
        """
        t0, t1 = _window(t0, t1)
        store = _store(request)
        wanted = {s for s in (streams or "").split(",") if s} or None

        out: dict[str, dict] = {}
        total = 0
        truncated = False
        keyframe: dict = {}
        metas = store.chunks_in_range(t0, t1, session_id=session_id)
        # 一次解完复用: 原先流与事件各扫一遍, 等于把每块解了两次
        loaded, skipped = _load_chunks(store, metas)
        for index, (meta, chunk) in enumerate(loaded):
            if index == 0:
                keyframe = chunk.keyframe
            for stream, data in chunk.streams.items():
                if wanted and stream not in wanted:
                    continue
                bucket = out.setdefault(stream, {"ts": [], "channels": {}})
                for i, ts in enumerate(data["ts"]):
                    if ts < t0 or ts >= t1:
                        continue
                    if total >= _MAX_FRAMES:
                        truncated = True
                        break
                    bucket["ts"].append(ts)
                    for key, values in data["channels"].items():
                        column = bucket["channels"].setdefault(key, [])
                        # 列必须与本流的 ts 等长, 缺帧显式补 None 而不是跳过 ——
                        # 跳过会让通道与时间戳错位, 回放出来是"轴突然瞬移"。
                        while len(column) < len(bucket["ts"]) - 1:
                            column.append(None)
                        value = values[i]
                        column.append(None if is_missing(value) else value)
                    total += 1
                for column in bucket["channels"].values():
                    while len(column) < len(bucket["ts"]):
                        column.append(None)
                if truncated:
                    break
            if truncated:
                break

        events = []
        for _meta, chunk in loaded:
            events.extend(e for e in chunk.events
                          if t0 <= float(e.get("ts") or t0) < t1)

        return {
            "t0": t0, "t1": t1,
            "keyframe": keyframe,
            "streams": out,
            "events": events,
            "frames": total,
            # 静默截断会让人以为"录像里就这么多", 必须显式告知
            "truncated": truncated,
            # 索引里有、磁盘上读不出来的块数; >0 说明该整理索引了
            "skipped": skipped,
        }
