"""排程路由
==========
功能:
    只读统计端点, 供前端 /planner 排程页 (甘特图): 流程窗口耗时统计与单流程
    步骤时间线. 只计算展示, 不控制设备执行. 数据源为 app.state.run_store (运行
    历史) 与 app.state.script_repo (流程摘要); 资源元数据尽力取 app.state.res_gate
    快照, 未就绪时为空列表 (前端可回退 /api/resources).

端点 (前缀 /api/planner):
    GET    /planner/stats?window=50                        全流程统计 + 全局动作统计 + 资源表
    GET    /planner/operations/{name}/timeline?window=50   单流程步骤时间线
    POST   /planner/baseline {operation?}                  设统计基线为当前时刻 (作废旧耗时)
    DELETE /planner/baseline?operation=                    撤销基线 (不带 operation 则清空全部)

说明:
    端点为同步 def, FastAPI 自动放线程池执行, 首次全量聚合不阻塞事件循环;
    流程改名后旧 runs.operation 不再匹配, 统计从零随新运行回填.
    基线只约束统计读侧, 不删任何运行记录: 执行记录与回放始终完整, 撤销即恢复旧统计.
"""

from __future__ import annotations

import logging
import time

from fastapi import Body, FastAPI, HTTPException, Request

from eit_ptlc.runtime.timing_stats import GLOBAL_BASELINE_KEY, TimingStats

log = logging.getLogger(__name__)

# window 上限: 防止一次请求扫过量历史 (runs 表本身按 max_runs=1000 封顶)
_WINDOW_MAX = 200


def register_planner_routes(app: FastAPI) -> None:
    """把排程只读统计路由注册到应用."""

    def _svc(request: Request) -> TimingStats:
        # 懒建单例: run_store 与 script_repo 就绪后首次访问构建, 挂 app.state.planner_stats
        svc = getattr(request.app.state, "planner_stats", None)
        if svc is not None:
            return svc
        run_store = getattr(request.app.state, "run_store", None)
        repo = getattr(request.app.state, "script_repo", None)
        if run_store is None or repo is None:
            raise HTTPException(503, "运行记录库或脚本仓库未就绪")
        svc = TimingStats(run_store, repo)
        request.app.state.planner_stats = svc
        return svc

    def _clamp_window(window: int) -> int:
        """把 window 夹紧到 [1, _WINDOW_MAX]."""
        return max(1, min(int(window), _WINDOW_MAX))

    def _resources_meta(request: Request) -> list[dict]:
        """资源元数据 [{id, label, mode}]; 资源门未就绪或异常时给空列表."""
        gate = getattr(request.app.state, "res_gate", None)
        if gate is None:
            return []
        try:
            return [{"id": rid, "label": item.get("label"), "mode": item.get("mode")}
                    for rid, item in gate.snapshot().items()]
        except Exception:  # 快照异常不拖垮统计端点
            log.exception("[planner] 读取资源快照失败")
            return []

    @app.get("/api/planner/stats")
    def planner_stats(request: Request, window: int = 50):
        """全流程窗口耗时统计 + 全局动作统计 + 资源元数据."""
        svc = _svc(request)
        return svc.stats(_clamp_window(window), resources_meta=_resources_meta(request))

    @app.get("/api/planner/operations/{name}/timeline")
    def planner_timeline(request: Request, name: str, window: int = 50):
        """单流程最近一次干净运行的步骤时间线 + 跨运行步骤统计."""
        svc = _svc(request)
        try:
            return svc.timeline(name, _clamp_window(window))
        except KeyError:
            raise HTTPException(404, f"流程不存在: {name}")

    def _store(request: Request):
        """取运行记录库 (基线读写宿主); 未就绪则 503."""
        run_store = getattr(request.app.state, "run_store", None)
        if run_store is None:
            raise HTTPException(503, "运行记录库未就绪")
        return run_store

    @app.post("/api/planner/baseline")
    def planner_set_baseline(request: Request, body: dict = Body(default=None)):
        """把统计基线设为当前时刻: 此刻之前的运行不再计入耗时统计.

        请求体:
            {"operation": "流程名"} 只作废该流程; 省略或 null 则作废全部流程 (全局基线)
        返回:
            {"operation": 流程名或 null, "since_ts": 基线时刻}
        """
        operation = (body or {}).get("operation")
        key = operation if operation else GLOBAL_BASELINE_KEY
        since_ts = time.time()
        _store(request).set_stat_baseline(key, since_ts)
        log.info("[planner] 设统计基线: %s -> %.3f", key, since_ts)
        return {"operation": operation or None, "since_ts": since_ts}

    @app.delete("/api/planner/baseline")
    def planner_clear_baseline(request: Request, operation: str | None = None):
        """撤销统计基线, 恢复用历史运行统计.

        参数:
            operation: 只撤销该流程的基线; 省略则清空全部基线 (含全局)
        返回:
            {"operation": 流程名或 null, "cleared": True}
        """
        store = _store(request)
        if operation:
            store.clear_stat_baseline(operation)
        else:
            store.clear_all_stat_baselines()
        log.info("[planner] 撤销统计基线: %s", operation or "全部")
        return {"operation": operation or None, "cleared": True}
