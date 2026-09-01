"""段级流水线调度器 (FlowScheduler)
==================================
功能:
    以"原子流程"为最小派发单元, 把批量样品按调度方案 DAG 展开为段作业 (job), 在资源/停放位/
    缸池/占位账全部满足时派发为独立 VM 运行, 实现多样品流水线并行 (8 缸同时展开、点样期间
    机器人服务他样品、缸预备与点样重叠)。

调度策略 (对齐 docs/pTLC下一阶段_生产调度与设备节点_完整落地计划.md §9.2):
    priority DESC, submitted_at ASC, 同优先级 FIFO; 打破平局偏向后段作业 (-af_index,
    防 WIP 拥塞); 资源全取或全不取 (派发前全部就绪, 不半持等待); 不做动态优化。

就绪条件 (_ready):
    依赖段全 DONE/SKIPPED + 样品非 HOLD + 位置==from (位置中立段跳过) + 目的停放位空闲
    (spot_seat/scrape_table 容量 1 —— 防把板放到还停着他样品板的台上) + 根独占资源全空闲
    (自身派发账本 + 资源门快照双查, 防与手动运行冲突) + 占位账 (occupy 名空闲) +
    首段加: 在制样品数 < wip_limit; 需缸段 (inputs 含 ctx:tank 且未分配) 加: 缸池有空。

失败与恢复 (两级检查点):
    段边界 = 一级检查点 (位置+outputs+context 落库, 失败后从下一段重派的锚);
    段内 = 二级: ERROR 时记 failed_aid/failed_step + 根帧 vars 快照; retry:resume 段可经
    resume 动词带 start_aid + 变量回注续跑。全部恢复动词人工触发, 重启后 PAUSED 待对账,
    禁止自动重派 (§9.3 明令)。

线程模型:
    单事件循环: 派发循环 + 每段一个跟踪 task; on_vm_event 由引擎 emit 同步调用 (轻量,
    全捕获)。SQLite 写经 ExperimentStore 的进程内锁。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from eit_ptlc.operation.recipe import (Recipe, RecipeError, dump_recipe_yaml, load_recipe,
                                       load_recipe_doc, load_recipe_text, recipe_source_doc,
                                       topo_order, validate_recipe)
from eit_ptlc.operation.vm.inputs import validate_inputs
from eit_ptlc.operation.vm.knobs import collect_knobs, validate_overrides
from eit_ptlc.runtime.experiment_store import JOB_SATISFIED, ExperimentStore
from eit_ptlc.runtime.maintenance_gate import MaintenanceActiveError

log = logging.getLogger(__name__)

# 停放位容量 1 的槽 (feedlift/waste 为仓, 不限; tank 由缸池管)
_SINGLE_SLOTS = {"spot_seat", "scrape_table"}

# 等待原因闭集 (前端 waitReasonText 按此映射)
WAIT_QUEUED = "queued"
WAIT_DEPENDS = "depends_on"
WAIT_RESOURCE = "waiting_resource"
WAIT_SLOT = "no_slot"
WAIT_TANK = "no_tank"
WAIT_WIP = "wip_limit"
WAIT_HOLD = "hold"
WAIT_PAUSED = "paused"
WAIT_POSITION = "position"
WAIT_OCCUPANCY = "occupancy"
WAIT_MAINTENANCE = "maintenance"


class SubmitError(ValueError):
    """批次提交被拒 (校验失败/重名/耗材不足); API 层映射 400/409."""

    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


class FlowScheduler:
    """段级流水线调度器."""

    def __init__(self, *, vm, res_gate, resolve_script: Callable[[str], dict],
                 material_store, experiment_store: ExperimentStore,
                 registry, resource_modes: dict[str, str],
                 recipes_dir: Path, bus=None,
                 wip_limit: int = 3, tank_pool: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8),
                 default_recipe: str = "parallel_v1",
                 vision_output_dir: Optional[Path] = None,
                 time_fn: Callable[[], float] = time.time) -> None:
        self._vm = vm
        self._gate = res_gate
        self._resolve = resolve_script
        self._materials = material_store
        self._store = experiment_store
        self._registry = registry
        self._modes = dict(resource_modes)
        self._recipes_dir = Path(recipes_dir)
        self._bus = bus
        self._wip_limit = int(wip_limit)
        self._tank_pool = tuple(tank_pool)
        self._default_recipe = default_recipe
        self._vision_output_dir = Path(vision_output_dir) if vision_output_dir else None
        self._time = time_fn

        self._recipes: dict[str, Recipe] = {}
        self._task: Optional[asyncio.Task] = None
        self._trackers: set[asyncio.Task] = set()
        self._wake = asyncio.Event()
        self._stopping = False
        self._revision = 0
        self._last_publish = 0.0
        # 派发账本: 资源名 -> job_id (派发起至终态; 补 VM 尚未 acquire 的窗口)
        self._res_ledger: dict[str, str] = {}
        # 缸池: 缸号 -> sample_id|None
        self._tanks: dict[int, Optional[str]] = {t: None for t in self._tank_pool}
        # 跨段占位账: 占位名 -> sample_id|None (如 scrape-holder)
        self._occupancy: dict[str, Optional[str]] = {}
        # 待展示的等待原因: job_id -> {reason, detail}
        self._wait_reasons: dict[str, dict] = {}
        # 启动对账结果 (快照透出)
        self._boot_report: dict = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动派发循环 (进程唯一, 须在事件循环内调用); 先做重启对账再收活."""
        self._boot_report = self._store.mark_interrupted_on_boot()
        self._rebuild_ledgers()
        self._task = asyncio.create_task(self._loop(), name="flow-scheduler")
        log.info("[调度] 派发循环已启动 (重启对账: %s)", self._boot_report)

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        for t in list(self._trackers):
            t.cancel()
        if self._trackers:
            await asyncio.gather(*self._trackers, return_exceptions=True)

    def _rebuild_ledgers(self) -> None:
        """重启后从库重建缸池/占位账 (位置账本身持久在 samples.position).

        缸: 样品 tank 非空且未走完出缸段 (或非正常终止) 即视为占用 —— 宁可多占等人工
        对账释放, 不可少占造成两个样品进同一缸。
        """
        samples = self._store.list_samples()
        jobs_by_sample: dict[str, list[dict]] = {}
        for j in self._store.list_jobs():
            if j.get("sample_id"):
                jobs_by_sample.setdefault(j["sample_id"], []).append(j)
        for s in samples:
            if s.get("status") in ("DONE",):
                continue
            sid = s["sample_id"]
            tank = s.get("tank")
            if tank:
                recipe = self._recipe_of_batch(s.get("batch_id"))
                released = False
                if recipe is not None:
                    out_flow = self._tank_release_flow(recipe)
                    if out_flow is not None:
                        job = next((j for j in jobs_by_sample.get(sid, [])
                                    if j["flow_id"] == out_flow.id), None)
                        released = bool(job and job["status"] in JOB_SATISFIED)
                if not released and int(tank) in self._tanks:
                    self._tanks[int(tank)] = sid
            recipe = self._recipe_of_batch(s.get("batch_id"))
            if recipe is None:
                continue
            for f in recipe.flows:
                if not f.occupy:
                    continue
                occ_job = next((j for j in jobs_by_sample.get(sid, [])
                                if j["flow_id"] == f.id), None)
                if not (occ_job and occ_job["status"] in JOB_SATISFIED):
                    continue
                rel_flow = next((g for g in recipe.flows if set(f.occupy) & set(g.release)), None)
                rel_job = next((j for j in jobs_by_sample.get(sid, [])
                                if rel_flow and j["flow_id"] == rel_flow.id), None)
                if not (rel_job and rel_job["status"] in JOB_SATISFIED):
                    for name in f.occupy:
                        self._occupancy[name] = sid
        occupied = {t: s for t, s in self._tanks.items() if s}
        if occupied or self._occupancy:
            log.warning("[调度] 账本重建: 缸占用=%s 占位=%s (待批次对账确认)",
                        occupied, {k: v for k, v in self._occupancy.items() if v})

    # ------------------------------------------------------------------
    # 调度方案 (UI 的"调度"层; 代码内标识符沿用 recipe)
    # ------------------------------------------------------------------

    def get_recipe(self, name: str) -> Recipe:
        if name not in self._recipes:
            path = self._recipes_dir / f"{name}.yaml"
            if not path.exists():
                raise KeyError(f"调度方案不存在: {name}")
            self._recipes[name] = load_recipe(path)
        return self._recipes[name]

    def list_recipes(self) -> list[dict]:
        """枚举 recipes_dir 下全部 ptlc.recipe/v1 调度方案 (供前端下拉与段清单预览).

        配置默认方案 (config experiment.recipe) 置顶并打 default 标 —— 否则文件名字母序会把
        parallel_smoke (冒烟) 排在 parallel_v1 之前, 前端下拉默认落在冒烟方案上。
        """
        out = []
        if not self._recipes_dir.exists():
            return out
        for path in sorted(self._recipes_dir.glob("*.yaml")):
            try:
                recipe = load_recipe(path)
            except Exception:
                continue
            dto = self._recipe_dto(recipe)
            dto["default"] = recipe.name == self._default_recipe
            out.append(dto)
        out.sort(key=lambda r: (not r["default"], r["name"]))
        return out

    def _recipe_dto(self, recipe: Recipe) -> dict:
        segments = []
        for i, f in enumerate(topo_order(recipe)):
            flow_meta = {}
            try:
                flow_meta = (self._resolve(f.script) or {}).get("flow") or {}
            except KeyError:
                pass
            segments.append({
                "seq": i, "id": f.id, "op": f.script, "scope": f.scope,
                "label": self._script_label(f.script),
                "from": flow_meta.get("from"), "to": flow_meta.get("to"),
                "hitl": flow_meta.get("hitl", "none"),
                "retry": flow_meta.get("retry", "manual"),
                "depends_on": list(f.depends_on),
            })
        return {"name": recipe.name, "label": recipe.label,
                "consumables": list(recipe.consumables), "segments": segments}

    def _script_label(self, name: str) -> str:
        try:
            return (self._resolve(name) or {}).get("label") or name
        except KeyError:
            return name

    def validate_recipe_by_name(self, name: str) -> list[str]:
        recipe = self.get_recipe(name)
        return validate_recipe(recipe, resolve=self._resolve, registry=self._registry,
                               resource_modes=self._modes)

    # ------------------------------------------------------------------
    # 调度方案读写 (前端调度编排器; 方案=段间串/并行结构的唯一定义处, 工程师改它不改代码)
    #
    # 两条对等的编辑路, 共用同一条落盘守卫链 (_persist_recipe):
    #   doc  路 = 图形化画布 (结构化, 前端零 YAML 依赖) —— 主路
    #   text 路 = 文本页签 (保原文 # 注释) —— 高级路
    # ------------------------------------------------------------------

    @staticmethod
    def _check_recipe_name(name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", name or ""):
            raise KeyError(f"调度方案名非法 (仅限字母/数字/下划线/连字符): {name!r}")

    def _recipe_path(self, name: str) -> Path:
        self._check_recipe_name(name)
        return self._recipes_dir / f"{name}.yaml"

    def read_recipe_text(self, name: str) -> str:
        path = self._recipe_path(name)
        if not path.is_file():
            raise KeyError(f"调度方案不存在: {name}")
        return path.read_text(encoding="utf-8")

    def read_recipe_doc(self, name: str) -> dict:
        """结构化读 (画布加载): 源 doc, depends_on 已显式化 (省略糖展开成显式边)."""
        recipe = load_recipe_text(self.read_recipe_text(name), fallback_name=name)
        return recipe_source_doc(recipe)

    def validate_recipe_text(self, text: str) -> tuple[list[str], Optional[dict]]:
        """文本干跑校验 (不落盘): 返回 (错误清单, 校验干净时的段DTO预览)."""
        try:
            recipe = load_recipe_text(text)
        except RecipeError as exc:
            return [str(exc)], None
        return self._validate_recipe_obj(recipe)

    def validate_recipe_doc(self, doc) -> tuple[list[str], Optional[dict]]:
        """结构化干跑校验 (画布每次编辑后/保存前): 同上, 入参是源 doc."""
        try:
            recipe = load_recipe_doc(doc)
        except RecipeError as exc:
            return [str(exc)], None
        return self._validate_recipe_obj(recipe)

    def _validate_recipe_obj(self, recipe: Recipe) -> tuple[list[str], Optional[dict]]:
        errors = validate_recipe(recipe, resolve=self._resolve, registry=self._registry,
                                 resource_modes=self._modes)
        return errors, (self._recipe_dto(recipe) if not errors else None)

    def save_recipe_text(self, name: str, text: str) -> dict:
        """文本保存: 校验通过才落盘 (原文逐字保留, # 注释不丢)."""
        try:
            recipe = load_recipe_text(text)
        except RecipeError as exc:
            raise SubmitError(f"调度方案解析失败: {exc}")
        return self._persist_recipe(name, recipe, text)

    def save_recipe_doc(self, name: str, doc) -> dict:
        """结构化保存: 源 doc -> 规范化 YAML 落盘 (原文注释被规范化输出取代)."""
        try:
            recipe = load_recipe_doc(doc)
        except RecipeError as exc:
            raise SubmitError(f"调度方案解析失败: {exc}")
        return self._persist_recipe(name, recipe, dump_recipe_yaml(recipe_source_doc(recipe)))

    def _persist_recipe(self, name: str, recipe: Recipe, text: str) -> dict:
        """落盘守卫 (doc/text 两路共用): 校验通过才写, 写后失效内存缓存.

        拒绝 (SubmitError, API 层映射 400/409):
            - 静态校验失败; 内容 name 与目标名不符 (防文件名与内容漂移);
            - 非终态批次 (QUEUED/RUNNING/PAUSED) 正引用该方案 —— 调度器运行期按名重读方案
              (_recipe_of_batch), 半路换定义会让已落库的段作业与新 DAG 失配。
        """
        try:
            self._check_recipe_name(name)
        except KeyError as exc:
            raise SubmitError(str(exc))
        if recipe.name != name:
            raise SubmitError(f"内容里的 name ({recipe.name}) 与目标调度方案名 ({name}) 不符")
        errors = validate_recipe(recipe, resolve=self._resolve, registry=self._registry,
                                 resource_modes=self._modes)
        if errors:
            raise SubmitError("调度方案静态校验失败:\n" + "\n".join(errors[:10]))
        active = self._store.active_batches_using_recipe(name)
        if active:
            raise SubmitError(
                f"调度方案正被未完结批次引用, 拒绝修改: {', '.join(active[:5])}", conflict=True)
        self._recipes_dir.mkdir(parents=True, exist_ok=True)
        (self._recipes_dir / f"{name}.yaml").write_text(text, encoding="utf-8")
        self._recipes.pop(name, None)
        log.info("[调度] 方案已保存: %s (%d 段)", name, len(recipe.flows))
        return {"name": name, "ok": True}

    def _recipe_of_batch(self, batch_id: Optional[str]) -> Optional[Recipe]:
        if not batch_id:
            return None
        batch = self._store.get_batch(batch_id)
        if batch is None:
            return None
        try:
            return self.get_recipe(batch.get("recipe") or self._default_recipe)
        except (KeyError, Exception):
            return None

    def _tank_release_flow(self, recipe: Recipe):
        """出缸段 = flow.from 为 tank 模板且 to 非 tank 的位移段 (DONE 后释放缸池)."""
        for f in recipe.flows:
            meta = self._flow_meta(f)
            frm, to = str(meta.get("from", "")), str(meta.get("to", ""))
            if frm.startswith("tank") and not to.startswith("tank"):
                return f
        return None

    # ------------------------------------------------------------------
    # 批次提交与动词
    # ------------------------------------------------------------------

    async def submit_batch(self, req: dict) -> dict:
        """校验并落库一个批次 (QUEUED, 需显式 start); 返回 {batch_id, sample_ids}.

        req: {recipe?, name?, priority?, sample_count, id_prefix, params?,
              per_sample_overrides?, auto_drain?, wip_limit?, tank_subset?, note?}
        """
        recipe_name = str(req.get("recipe") or self._default_recipe)
        recipe = self.get_recipe(recipe_name)
        errors = self.validate_recipe_by_name(recipe_name)
        if errors:
            raise SubmitError("调度方案静态校验失败:\n" + "\n".join(errors[:10]))

        count = int(req.get("sample_count") or 0)
        if not 1 <= count <= 64:
            raise SubmitError(f"样品数量非法 (1-64): {count}")
        prefix = str(req.get("id_prefix") or "").strip()
        if not prefix or not all(c.isalnum() or c in "_-" for c in prefix):
            raise SubmitError(f"样品ID前缀非法 (字母数字_-, 非空): {prefix!r}")
        sample_ids = [f"{prefix}-{i:02d}" for i in range(1, count + 1)]
        dup = self._store.sample_ids_exist(sample_ids)
        if dup:
            raise SubmitError(f"样品ID已存在 (换前缀或续号): {dup}", conflict=True)

        params = dict(req.get("params") or {})
        knob_errors = self._validate_batch_params(recipe, params)
        if knob_errors:
            raise SubmitError("批参数校验失败:\n" + "\n".join(knob_errors))
        overrides_list = list(req.get("per_sample_overrides") or [])
        if overrides_list and len(overrides_list) != count:
            raise SubmitError(f"每样品覆盖行数 ({len(overrides_list)}) 与样品数 ({count}) 不符")

        tank_subset = req.get("tank_subset") or list(self._tank_pool)
        tank_subset = sorted({int(t) for t in tank_subset} & set(self._tank_pool))
        if not tank_subset:
            raise SubmitError("缸子集为空 (与调度器缸池无交集)")

        # 耗材准入: 逐样品逐类计数级预留, 不足即整批拒收并回滚已预留
        reserved: list[str] = []
        try:
            for sid in sample_ids:
                for kind in recipe.consumables:
                    if not self._materials.reserve_count(sid, kind):
                        raise SubmitError(
                            f"耗材不足: 第 {len(reserved) // max(1, len(recipe.consumables)) + 1} 个样品"
                            f"起 {kind} 无可预留余量; 请补料或减少样品数")
                reserved.append(sid)
        except SubmitError:
            for sid in set(reserved + sample_ids):
                self._materials.release_reservations(sid)
            raise

        batch_id = f"B{uuid.uuid4().hex[:8]}"
        auto_drain = bool(req.get("auto_drain", True))
        if auto_drain:
            params.setdefault("auto_drain", True)
        config_snapshot = self._snapshot_config()
        order = topo_order(recipe)
        # 样品初始停放位 = 首个位移段的 from (parallel_v1 即 feedlift 料仓)
        initial_pos = ""
        for f in order:
            if f.scope != "sample":
                continue
            frm = str(self._flow_meta(f).get("from", "none"))
            if frm not in ("same", "none"):
                initial_pos = frm
                break
        samples = []
        jobs = []
        for fid_index, f in enumerate(order):
            if f.scope == "batch":
                jobs.append({"job_id": f"{batch_id}-{f.id}", "sample_id": None,
                             "flow_id": f.id, "af_index": fid_index, "script": f.script,
                             "depends": list(f.depends_on)})
        for seq, sid in enumerate(sample_ids, start=1):
            row_overrides = overrides_list[seq - 1] if overrides_list else {}
            samples.append({"sample_id": sid, "seq": seq, "position": initial_pos,
                            "overrides": row_overrides})
            for fid_index, f in enumerate(order):
                if f.scope != "sample":
                    continue
                jobs.append({"job_id": f"{sid}-{f.id}", "sample_id": sid,
                             "flow_id": f.id, "af_index": fid_index, "script": f.script,
                             "depends": list(f.depends_on)})
        self._store.create_batch(
            batch_id, name=str(req.get("name") or f"{recipe.label} x{count}"),
            recipe=recipe_name, priority=int(req.get("priority") or 0),
            wip_limit=req.get("wip_limit"), tank_pool=tank_subset, params=params,
            per_sample_overrides=overrides_list, config_snapshot=config_snapshot,
            auto_drain=auto_drain, note=str(req.get("note") or ""),
            samples=samples, jobs=jobs)
        self._store.log_event("batch_submitted", batch_id=batch_id,
                              payload={"samples": sample_ids, "recipe": recipe_name})
        self._publish("batch_submitted", batch_id=batch_id)
        return {"batch_id": batch_id, "sample_ids": sample_ids}

    def _validate_batch_params(self, recipe: Recipe, params: dict) -> list[str]:
        """批参数 = 各段脚本旋钮的并集; 键必须命中至少一个段的旋钮且值合法."""
        if not params:
            return []
        union: dict[str, dict] = {}
        for f in recipe.flows:
            try:
                doc = self._resolve(f.script)
            except KeyError:
                continue
            for k in collect_knobs(doc, self._resolve):
                union.setdefault(k["name"], k)
        errors: list[str] = []
        unknown = [k for k in params if k not in union]
        if unknown:
            errors.append(f"未知旋钮 (不属于调度方案任何段): {sorted(unknown)}")
        known = {k: v for k, v in params.items() if k in union}
        errors.extend(validate_overrides(list(union.values()), known))
        return errors

    def _snapshot_config(self) -> dict:
        """提交时冻结 gcode/pump/vision 三段配置 (复现一次实验的完整参数面)."""
        snapshot: dict = {}
        svc = getattr(self, "config_service", None)
        if svc is None:
            return snapshot
        for section in ("gcode", "pump", "vision"):
            try:
                snapshot[section] = svc.read_section(section)
            except Exception as exc:
                snapshot[section] = {"error": str(exc)}
        return snapshot

    async def batch_start(self, batch_id: str) -> dict:
        batch = self._require_batch(batch_id)
        if batch["status"] == "PAUSED" and batch.get("needs_reconcile"):
            raise ValueError("批次待对账 (needs_reconcile): 先完成 reconcile 再启动")
        if batch["status"] not in ("QUEUED", "PAUSED"):
            raise ValueError(f"批次状态 {batch['status']} 不可启动")
        self._store.update_batch(batch_id, status="RUNNING",
                                 started_at=batch.get("started_at") or self._time())
        self._store.log_event("batch_started", batch_id=batch_id)
        self._publish("batch_started", batch_id=batch_id)
        self._wake.set()
        return {"batch_id": batch_id, "status": "RUNNING"}

    async def batch_pause(self, batch_id: str) -> dict:
        """暂停 = 停止派发新段; 在飞段作业跑完当前段自然停在段边界."""
        self._require_batch(batch_id)
        self._store.update_batch(batch_id, status="PAUSED")
        self._store.log_event("batch_paused", batch_id=batch_id)
        self._publish("batch_paused", batch_id=batch_id)
        return {"batch_id": batch_id, "status": "PAUSED"}

    async def batch_resume(self, batch_id: str) -> dict:
        return await self.batch_start(batch_id)

    async def batch_abort(self, batch_id: str) -> dict:
        """中止 = 不再派发 + 待派段 CANCELLED + 释放物料预留; 在飞段跑完记账.

        物理残留 (缸内板/夹具收集器) 不自动清 —— 批置 needs_reconcile, 经对账释放。
        """
        batch = self._require_batch(batch_id)
        had_active = False
        for s in self._store.list_samples(batch_id):
            if s["status"] in ("ACTIVE", "HOLD"):
                had_active = True
            if s["status"] not in ("DONE",):
                self._store.update_sample(s["sample_id"], status="ABORTED")
            self._materials.release_reservations(s["sample_id"])
        for j in self._store.list_jobs(batch_id=batch_id, status="PENDING"):
            self._store.update_job(j["job_id"], status="CANCELLED",
                                   finished_at=self._time(), message="批次中止")
            self._wait_reasons.pop(j["job_id"], None)
        self._store.update_batch(batch_id, status="ABORTED", finished_at=self._time(),
                                 needs_reconcile=1 if had_active else batch.get("needs_reconcile", 0))
        self._store.log_event("batch_aborted", batch_id=batch_id)
        self._publish("batch_aborted", batch_id=batch_id)
        self._wake.set()
        return {"batch_id": batch_id, "status": "ABORTED"}

    async def sample_abort(self, batch_id: str, sample_id: str) -> dict:
        sample = self._require_sample(batch_id, sample_id)
        if sample["status"] in ("DONE", "ABORTED"):
            raise ValueError(f"样品已终态: {sample['status']}")
        self._store.update_sample(sample_id, status="ABORTED", message="人工终止")
        for j in self._store.list_jobs(sample_id=sample_id, status="PENDING"):
            self._store.update_job(j["job_id"], status="CANCELLED",
                                   finished_at=self._time(), message="样品终止")
            self._wait_reasons.pop(j["job_id"], None)
        self._materials.release_reservations(sample_id)
        # 缸/占位不自动清 (可能有物理残留), 留待批次对账; 在飞段任其跑完由 _track 收口
        self._store.log_event("sample_aborted", batch_id=batch_id, sample_id=sample_id)
        self._publish("sample_aborted", batch_id=batch_id, sample_id=sample_id)
        self._wake.set()
        return {"sample_id": sample_id, "status": "ABORTED"}

    async def sample_hold(self, batch_id: str, sample_id: str) -> dict:
        """段边界软停: 跑完当前段后不再派发该样品的后续段."""
        sample = self._require_sample(batch_id, sample_id)
        if sample["status"] != "ACTIVE":
            raise ValueError(f"样品状态 {sample['status']} 不可暂停 (仅 ACTIVE)")
        self._store.update_sample(sample_id, status="HOLD")
        self._publish("sample_hold", batch_id=batch_id, sample_id=sample_id)
        return {"sample_id": sample_id, "status": "HOLD"}

    async def sample_resume(self, batch_id: str, sample_id: str) -> dict:
        sample = self._require_sample(batch_id, sample_id)
        if sample["status"] != "HOLD":
            raise ValueError(f"样品状态 {sample['status']} 不可恢复 (仅 HOLD)")
        self._store.update_sample(sample_id, status="ACTIVE")
        self._publish("sample_resume", batch_id=batch_id, sample_id=sample_id)
        self._wake.set()
        return {"sample_id": sample_id, "status": "ACTIVE"}

    # ------------------------------------------------------------------
    # 段作业恢复动词 (全部人工触发)
    # ------------------------------------------------------------------

    def _job_and_flow(self, batch_id: str, sample_id: str, seq_or_flow) -> tuple[dict, object, Recipe]:
        recipe = self._recipe_of_batch(batch_id)
        if recipe is None:
            raise ValueError(f"批次 {batch_id} 不存在或调度方案缺失")
        order = topo_order(recipe)
        flow = None
        if isinstance(seq_or_flow, int) or str(seq_or_flow).isdigit():
            idx = int(seq_or_flow)
            if not 0 <= idx < len(order):
                raise ValueError(f"段序号越界: {idx}")
            flow = order[idx]
        else:
            flow = recipe.flow(str(seq_or_flow))
        owner = batch_id if flow.scope == "batch" else sample_id
        job = self._store.get_job(f"{owner}-{flow.id}")
        if job is None:
            raise ValueError(f"段作业不存在: {owner}-{flow.id}")
        return job, flow, recipe

    async def job_retry(self, batch_id: str, sample_id: str, seq_or_flow, *,
                        confirm: bool = False) -> dict:
        """整段重跑: retry:restart 段直接重派; resume/manual 段要求 confirm=true (人工确认物理态)."""
        job, flow, _ = self._job_and_flow(batch_id, sample_id, seq_or_flow)
        if job["status"] not in ("ERROR", "INTERRUPTED", "CANCELLED"):
            raise ValueError(f"段状态 {job['status']} 不可重试")
        retry_decl = self._flow_retry(flow)
        if retry_decl != "restart" and not confirm:
            raise ValueError(
                f"段 {flow.id} 声明 retry:{retry_decl}, 整段重跑需人工确认物理态 (confirm=true)")
        self._store.update_job(job["job_id"], status="PENDING", resume_from=None,
                               message=f"人工重试 (第{job.get('attempt', 0) + 1}次)")
        self._reactivate_sample(sample_id)
        self._store.log_event("job_retry", batch_id=batch_id, sample_id=sample_id or "",
                              job_id=job["job_id"])
        self._wake.set()
        return {"job_id": job["job_id"], "status": "PENDING"}

    async def job_resume(self, batch_id: str, sample_id: str, seq_or_flow) -> dict:
        """断点续跑: 仅 retry:resume 段; 从失败 AID 的顶层语句边界续, 回注 vars 快照."""
        job, flow, _ = self._job_and_flow(batch_id, sample_id, seq_or_flow)
        if job["status"] not in ("ERROR", "INTERRUPTED"):
            raise ValueError(f"段状态 {job['status']} 不可续跑")
        if self._flow_retry(flow) != "resume":
            raise ValueError(f"段 {flow.id} 未声明 retry:resume, 只能整段重试或人工处置")
        failed_aid = job.get("failed_aid") or ""
        if not failed_aid:
            raise ValueError("无失败断点记录 (failed_aid 为空), 请改用整段重试")
        # 向上取整到 wrapper 顶层语句边界: AID 首两段 (b/N)
        top = "/".join(failed_aid.split("/")[:2])
        self._store.update_job(job["job_id"], status="PENDING", resume_from=top,
                               message=f"断点续跑自 {top}")
        self._reactivate_sample(sample_id)
        self._store.log_event("job_resume", batch_id=batch_id, sample_id=sample_id or "",
                              job_id=job["job_id"], payload={"resume_from": top})
        self._wake.set()
        return {"job_id": job["job_id"], "status": "PENDING", "resume_from": top}

    async def job_skip(self, batch_id: str, sample_id: str, seq_or_flow, *,
                       position: Optional[str] = None,
                       context: Optional[dict] = None, mark_done: bool = False) -> dict:
        """跳过/标记完成: 依赖视为满足, 位置与占位账按人工声明推进."""
        job, flow, recipe = self._job_and_flow(batch_id, sample_id, seq_or_flow)
        if job["status"] in JOB_SATISFIED:
            raise ValueError(f"段已满足: {job['status']}")
        status = "DONE" if mark_done else "SKIPPED"
        self._store.update_job(job["job_id"], status=status, finished_at=self._time(),
                               message="人工标记完成" if mark_done else "人工跳过")
        if context and sample_id:
            self._store.merge_sample_context(sample_id, context)
        if sample_id:
            self._apply_flow_effects(flow, recipe, sample_id, position_override=position)
            self._reactivate_sample(sample_id)
        self._store.log_event("job_skip" if not mark_done else "job_mark_done",
                              batch_id=batch_id, sample_id=sample_id or "",
                              job_id=job["job_id"], payload={"position": position})
        self._wake.set()
        return {"job_id": job["job_id"], "status": status}

    async def reconcile(self, batch_id: str, decisions: Optional[list] = None,
                        *, release_tanks: Optional[list] = None,
                        clear_occupancy: Optional[list] = None) -> dict:
        """人工对账: 逐段处置 INTERRUPTED/ERROR + 确认缸/占位释放, 然后清 needs_reconcile.

        decisions: [{sample_id, flow, action: retry|resume|skip|mark_done, position?, context?,
                     confirm?}]
        release_tanks: 确认已清理可回池的缸号
        clear_occupancy: 确认已清空的占位名 (如 scrape-holder)
        """
        self._require_batch(batch_id)
        results = []
        for d in decisions or []:
            action = d.get("action")
            sid = d.get("sample_id") or ""
            flow = d.get("flow")
            try:
                if action == "retry":
                    r = await self.job_retry(batch_id, sid, flow, confirm=True)
                elif action == "resume":
                    r = await self.job_resume(batch_id, sid, flow)
                elif action in ("skip", "mark_done"):
                    r = await self.job_skip(batch_id, sid, flow,
                                            position=d.get("position"),
                                            context=d.get("context"),
                                            mark_done=action == "mark_done")
                elif action == "abort_sample":
                    r = await self.sample_abort(batch_id, sid)
                else:
                    raise ValueError(f"未知处置动作: {action}")
                results.append({"ok": True, **r})
            except ValueError as exc:
                results.append({"ok": False, "error": str(exc), "sample_id": sid,
                                "flow": flow})
        for t in release_tanks or []:
            t = int(t)
            if t in self._tanks:
                self._tanks[t] = None
        for name in clear_occupancy or []:
            self._occupancy[name] = None
        self._store.update_batch(batch_id, needs_reconcile=0)
        self._store.log_event("batch_reconciled", batch_id=batch_id,
                              payload={"decisions": len(results)})
        self._publish("batch_reconciled", batch_id=batch_id)
        self._wake.set()
        return {"batch_id": batch_id, "results": results}

    def _reactivate_sample(self, sample_id: str) -> None:
        if not sample_id:
            return
        sample = self._store.get_sample(sample_id)
        if sample and sample["status"] == "HOLD":
            self._store.update_sample(sample_id, status="ACTIVE")

    # ------------------------------------------------------------------
    # 派发循环
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self._pass()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("[调度] 派发轮异常 (循环继续)")
            try:
                # 5s 兜底 tick: 资源门无释放回调, 手动运行释放靠事件唤醒 + 周期双保险
                await asyncio.wait_for(self._wake.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _pass(self) -> None:
        batches = [b for b in self._store.list_batches(limit=200) if b["status"] == "RUNNING"]
        if not batches:
            return
        batches.sort(key=lambda b: (-int(b.get("priority") or 0), b.get("submitted_at") or 0))
        candidates: list[tuple[tuple, dict, dict]] = []   # (排序键, batch, job)
        for b in batches:
            for j in self._store.list_jobs(batch_id=b["batch_id"], status="PENDING"):
                key = (-int(b.get("priority") or 0), -int(j.get("af_index") or 0),
                       b.get("submitted_at") or 0,
                       self._sample_seq(b["batch_id"], j.get("sample_id")))
                candidates.append((key, b, j))
        candidates.sort(key=lambda item: item[0])
        for _, batch, job in candidates:
            reason = self._ready(batch, job)
            if reason is None:
                self._wait_reasons.pop(job["job_id"], None)
                await self._dispatch(batch, job)
            else:
                self._wait_reasons[job["job_id"]] = reason

    def _sample_seq(self, batch_id: str, sample_id: Optional[str]) -> int:
        if not sample_id:
            return -1
        sample = self._store.get_sample(sample_id)
        return int(sample.get("seq") or 0) if sample else 0

    def _flow_meta(self, flow) -> dict:
        try:
            return (self._resolve(flow.script) or {}).get("flow") or {}
        except KeyError:
            return {}

    def _flow_retry(self, flow) -> str:
        return str(self._flow_meta(flow).get("retry", "manual"))

    def _resolve_loc(self, template: str, sample: Optional[dict]) -> str:
        """tank:{var} 模板按样品缸号落地; 其余原样."""
        if isinstance(template, str) and template.startswith("tank:{"):
            tank = (sample or {}).get("tank")
            return f"tank:{tank}" if tank else "tank:?"
        return template

    def _ready(self, batch: dict, job: dict) -> Optional[dict]:
        """返回 None=可派发; 否则 {reason, detail} 等待原因."""
        recipe = self._recipe_of_batch(batch["batch_id"])
        if recipe is None:
            return {"reason": WAIT_QUEUED, "detail": "调度方案缺失"}
        flow = recipe.flow(job["flow_id"])
        sample = self._store.get_sample(job["sample_id"]) if job.get("sample_id") else None

        # 依赖全满足
        for dep in flow.depends_on:
            dep_scope = recipe.flow(dep).scope
            owner = batch["batch_id"] if dep_scope == "batch" else job.get("sample_id")
            dep_job = self._store.get_job(f"{owner}-{dep}")
            if dep_job is None or dep_job["status"] not in JOB_SATISFIED:
                return {"reason": WAIT_DEPENDS, "detail": dep}
        # 样品态
        if sample is not None:
            if sample["status"] == "HOLD":
                return {"reason": WAIT_HOLD, "detail": ""}
            if sample["status"] == "ABORTED":
                return {"reason": WAIT_HOLD, "detail": "样品已终止"}
        # WIP 准入门 (放在位置/停放检查之前: 对未开跑样品, "未被准入"是最本质的等待原因)
        if sample is not None and sample["status"] == "PENDING":
            wip = int(batch.get("wip_limit") or self._wip_limit)
            active = len([s for s in self._store.list_samples()
                          if s["status"] in ("ACTIVE", "HOLD")])
            if active >= wip:
                return {"reason": WAIT_WIP, "detail": f"在制 {active}/{wip}"}
        meta = self._flow_meta(flow)
        frm = meta.get("from", "none")
        to = meta.get("to", "none")
        # 位置前置
        if sample is not None and frm not in ("same", "none"):
            expect = self._resolve_loc(frm, sample)
            if (sample.get("position") or "") != expect:
                return {"reason": WAIT_POSITION,
                        "detail": f"样品在 {sample.get('position') or '?'}, 段要求 {expect}"}
        # 缸分配 (inputs 含 ctx:tank 且未分配 -> 本段是首个需缸段, 派发时分配)
        needs_tank = any(src.get("ctx") == "tank" for src in flow.inputs.values()
                         if isinstance(src, dict))
        if needs_tank and sample is not None and not sample.get("tank"):
            subset = set(int(t) for t in (batch.get("tank_pool") or self._tank_pool))
            free = [t for t, owner in self._tanks.items() if owner is None and t in subset]
            if not free:
                return {"reason": WAIT_TANK, "detail": "缸池无空缸"}
        # 目的停放位容量
        if sample is not None and to not in ("same", "none") and to != frm:
            dest = self._resolve_loc(to, sample)
            if dest in _SINGLE_SLOTS:
                holder = self._slot_holder(dest, exclude=sample["sample_id"])
                if holder:
                    return {"reason": WAIT_SLOT, "detail": f"{dest} 被样品 {holder} 占用"}
        # 占位账 (occupy 名必须空闲)
        for name in flow.occupy:
            owner = self._occupancy.get(name)
            if owner and owner != job.get("sample_id"):
                return {"reason": WAIT_OCCUPANCY, "detail": f"{name} 被样品 {owner} 占用"}
        # 根独占资源全取或全不取 (账本 + 资源门双查)
        try:
            doc = self._resolve(flow.script)
        except KeyError:
            return {"reason": WAIT_QUEUED, "detail": f"脚本缺失 {flow.script}"}
        for name in doc.get("resources") or []:
            if self._modes.get(name) == "shared":
                continue
            holder_job = self._res_ledger.get(name)
            if holder_job:
                return {"reason": WAIT_RESOURCE,
                        "detail": f"{name} 被段 {holder_job} 占用"}
            if self._gate.locked(name):
                info = self._gate.snapshot().get(name) or {}
                return {"reason": WAIT_RESOURCE,
                        "detail": f"{name} 被运行 {info.get('holder', '?')} 占用 (手动/其他)"}
        return None

    async def _dispatch(self, batch: dict, job: dict) -> None:
        recipe = self._recipe_of_batch(batch["batch_id"])
        flow = recipe.flow(job["flow_id"])
        sample = self._store.get_sample(job["sample_id"]) if job.get("sample_id") else None
        doc = self._resolve(flow.script)

        # 首个需缸段: 派发时分配缸并落库
        needs_tank = any(isinstance(src, dict) and src.get("ctx") == "tank"
                         for src in flow.inputs.values())
        if needs_tank and sample is not None and not sample.get("tank"):
            subset = set(int(t) for t in (batch.get("tank_pool") or self._tank_pool))
            free = sorted(t for t, owner in self._tanks.items()
                          if owner is None and t in subset)
            if not free:
                # _ready 与 _dispatch 之间同轮派发耗尽缸池的兜底 (下一轮重排)
                self._wait_reasons[job["job_id"]] = {"reason": WAIT_TANK,
                                                     "detail": "缸池无空缸"}
                return
            tank = free[0]
            self._tanks[tank] = sample["sample_id"]
            self._store.update_sample(sample["sample_id"], tank=tank)
            sample["tank"] = tank
            self._store.log_event("tank_allocated", batch_id=batch["batch_id"],
                                  sample_id=sample["sample_id"], payload={"tank": tank})

        inputs = self._build_inputs(flow, batch, sample)
        overrides = dict(batch.get("params") or {})
        if sample is not None:
            overrides.update(dict(sample.get("overrides") or {}))
        # 取值域预检: 配方里 {lit:} 接线或 ctx 解析出的值若不在该 in 变量的 enum 内, 跑起来
        # 必落 else 抛 FLOW_SELECTOR (那时机器人已动过)。此处提前拦。
        # 刻意**不 raise**: 调度器里抛异常会让整批停摆, 故只让这一个 job 落 ERROR、样品 HOLD,
        # 与下方"派发失败"分支同样的处置 (此刻资源账还没登记, 无需回滚)。
        enum_errors = validate_inputs(doc, inputs)
        if enum_errors:
            detail = "; ".join(enum_errors)
            log.error("[调度] %s 入参非法, 不派发: %s", job["job_id"], detail)
            self._store.update_job(job["job_id"], status="ERROR", finished_at=self._time(),
                                   message=f"入参非法: {detail}")
            if job.get("sample_id"):
                self._store.update_sample(job["sample_id"], status="HOLD",
                                          message=f"段 {flow.id} 入参非法: {detail}")
            return
        attempt = int(job.get("attempt") or 0) + 1
        run_id = job["job_id"] if attempt == 1 else f"{job['job_id']}-r{attempt}"
        resume_from = job.get("resume_from") or None
        preset_vars = None
        if resume_from:
            snapshot = job.get("vars_snapshot") or {}
            preset_vars = {name: item.get("value") for name, item in snapshot.items()
                           if isinstance(item, dict)}
        meta = {"origin": "scheduler", "batch_id": batch["batch_id"],
                "sample_id": job.get("sample_id") or "", "flow": flow.id}
        # 先落库再启动: 单 human/零动作段可能在 start() 返回前就发出事件, 此时 run_id
        # 必须已可反查, 否则 WAITING_HUMAN 等映射丢失 (竞态实证于 sim 集成)。
        now = self._time()
        for name in doc.get("resources") or []:
            if self._modes.get(name) != "shared":
                self._res_ledger[name] = job["job_id"]
        self._store.update_job(job["job_id"], status="RUNNING", run_id=run_id,
                               attempt=attempt, inputs=inputs, resume_from=None,
                               started_at=now, message="")
        try:
            await self._vm.start(doc, inputs, mode_run="run", run_id=run_id,
                                 start_aid=resume_from, overrides=overrides, meta=meta,
                                 preset_vars=preset_vars)
        except MaintenanceActiveError:
            self._rollback_dispatch(job, resume_from)
            self._wait_reasons[job["job_id"]] = {"reason": WAIT_MAINTENANCE,
                                                 "detail": "维护态 (PLC 部署中)"}
            return
        except Exception as exc:
            log.exception("[调度] 派发 %s 失败", job["job_id"])
            self._release_ledger(job["job_id"])
            self._store.update_job(job["job_id"], status="ERROR", finished_at=self._time(),
                                   message=f"派发失败: {exc}")
            if job.get("sample_id"):
                self._store.update_sample(job["sample_id"], status="HOLD",
                                          message=f"段 {flow.id} 派发失败")
            return
        if sample is not None and sample["status"] == "PENDING":
            self._store.update_sample(sample["sample_id"], status="ACTIVE")
        if not batch.get("started_at"):
            self._store.update_batch(batch["batch_id"], started_at=now)
        self._store.log_event("job_dispatched", batch_id=batch["batch_id"],
                              sample_id=job.get("sample_id") or "", job_id=job["job_id"],
                              payload={"run_id": run_id, "attempt": attempt,
                                       "resume_from": resume_from})
        tracker = asyncio.create_task(
            self._track(batch["batch_id"], job["job_id"], flow.id, run_id),
            name=f"track-{run_id}")
        self._trackers.add(tracker)
        tracker.add_done_callback(self._trackers.discard)
        self._publish("job_dispatched", batch_id=batch["batch_id"], job_id=job["job_id"])

    def _release_ledger(self, job_id: str) -> None:
        for name, holder in list(self._res_ledger.items()):
            if holder == job_id:
                self._res_ledger.pop(name, None)

    def _rollback_dispatch(self, job: dict, resume_from: Optional[str]) -> None:
        """启动被拒 (维护态) 的回滚: 账本释放 + 段回 PENDING (续跑起点保留)."""
        self._release_ledger(job["job_id"])
        self._store.update_job(job["job_id"], status="PENDING", started_at=None,
                               resume_from=resume_from, message="维护态, 等待重派")

    def _build_inputs(self, flow, batch: dict, sample: Optional[dict]) -> dict:
        ctx = {}
        if sample is not None:
            ctx = dict(sample.get("context") or {})
            ctx.setdefault("sample_id", sample["sample_id"])
            ctx.setdefault("save_dir", f"var/photoscrape/{batch['batch_id']}/{sample['sample_id']}")
            if sample.get("tank"):
                ctx["tank"] = int(sample["tank"])
        params = dict(batch.get("params") or {})
        inputs: dict = {}
        for var, src in (flow.inputs or {}).items():
            if not isinstance(src, dict):
                continue
            if "lit" in src:
                inputs[var] = src["lit"]
            elif "ctx" in src:
                key = src["ctx"]
                if key in ctx:
                    inputs[var] = ctx[key]
                else:
                    log.warning("[调度] 段 %s 输入 %s 的上下文键 %s 缺失, 用脚本默认",
                                flow.id, var, key)
            elif "batch" in src:
                key = src["batch"]
                if key in params:
                    inputs[var] = params[key]
        return inputs

    async def _track(self, batch_id: str, job_id: str, flow_id: str, run_id: str) -> None:
        """跟踪一次段运行至终态并记账."""
        try:
            state = await self._vm.wait_final(run_id)
        except Exception as exc:
            log.exception("[调度] 跟踪 %s 异常", run_id)
            state = {"status": "ERROR", "current_aid": "", "script": ""}
            self._store.update_job(job_id, message=f"跟踪异常: {exc}")
        finally:
            # 无论成败, 派发账本必须清 (VM 侧 gate 已按其生命周期释放)
            for name, holder in list(self._res_ledger.items()):
                if holder == job_id:
                    self._res_ledger.pop(name, None)
        status = state.get("status") or "ERROR"
        now = self._time()
        job = self._store.get_job(job_id) or {}
        sample_id = job.get("sample_id") or ""
        recipe = self._recipe_of_batch(batch_id)
        flow = recipe.flow(flow_id) if recipe else None

        if status == "DONE":
            outputs = self._extract_outputs(flow, run_id)
            self._store.update_job(job_id, status="DONE", finished_at=now,
                                   outputs=outputs, message="")
            if sample_id:
                if outputs:
                    self._store.merge_sample_context(sample_id, outputs)
                if flow is not None:
                    self._apply_flow_effects(flow, recipe, sample_id)
                    if flow.ingest_results:
                        self._ingest_results_safe(sample_id)
                self._finalize_sample_if_complete(batch_id, sample_id, recipe)
            self._finalize_batch_if_complete(batch_id)
        elif status == "KILLED":
            self._store.update_job(job_id, status="CANCELLED", finished_at=now,
                                   message="运行被终止")
            if sample_id:
                self._hold_sample(sample_id, f"段 {flow_id} 被终止")
        else:
            failed_aid = state.get("current_aid") or ""
            failed_step = f"{state.get('script') or ''}@{failed_aid}"
            vars_snapshot = {}
            try:
                vars_snapshot = (self._vm.vars(run_id) or {}).get("vars") or {}
            except Exception:
                pass
            self._store.update_job(job_id, status="ERROR", finished_at=now,
                                   failed_aid=failed_aid, failed_step=failed_step,
                                   vars_snapshot=vars_snapshot)
            if sample_id:
                self._hold_sample(sample_id, f"段 {flow_id} 失败 @ {failed_step}")
        self._store.log_event("job_finished", batch_id=batch_id, sample_id=sample_id,
                              job_id=job_id, payload={"status": status, "run_id": run_id})
        self._publish("job_finished", batch_id=batch_id, job_id=job_id, status=status)
        self._wake.set()

    def _ingest_results_safe(self, sample_id: str) -> None:
        """刮取段完成后摄取视觉结果 (best-effort: 文件缺失只记日志, 不影响调度)."""
        if self._vision_output_dir is None:
            return
        try:
            self._store.ingest_vision_results(sample_id, self._vision_output_dir / sample_id)
        except Exception:
            log.warning("[调度] 样品 %s 视觉结果摄取失败 (忽略)", sample_id, exc_info=True)

    def _extract_outputs(self, flow, run_id: str) -> dict:
        if flow is None or not flow.outputs:
            return {}
        try:
            snapshot = (self._vm.vars(run_id) or {}).get("vars") or {}
        except Exception:
            return {}
        out = {}
        for out_var, ctx_key in flow.outputs.items():
            item = snapshot.get(out_var)
            if isinstance(item, dict) and "value" in item:
                out[ctx_key] = item["value"]
        return out

    def _apply_flow_effects(self, flow, recipe: Recipe, sample_id: str,
                            *, position_override: Optional[str] = None) -> None:
        """段满足后的账务: 位置推进 / 缸释放 / 占位 occupy-release."""
        sample = self._store.get_sample(sample_id) or {}
        meta = self._flow_meta(flow)
        frm, to = meta.get("from", "none"), meta.get("to", "none")
        if position_override:
            self._store.update_sample(sample_id, position=position_override)
        elif to not in ("same", "none") and to != frm:
            self._store.update_sample(sample_id, position=self._resolve_loc(to, sample))
        # 出缸段 (from=tank* 且 to 非 tank): 释放缸池
        if str(frm).startswith("tank") and not str(to).startswith("tank"):
            tank = sample.get("tank")
            if tank and self._tanks.get(int(tank)) == sample_id:
                self._tanks[int(tank)] = None
                self._store.log_event("tank_released", sample_id=sample_id,
                                      batch_id=sample.get("batch_id") or "",
                                      payload={"tank": int(tank)})
        for name in flow.occupy:
            self._occupancy[name] = sample_id
        for name in flow.release:
            if self._occupancy.get(name) == sample_id or self._occupancy.get(name):
                self._occupancy[name] = None

    def _finalize_sample_if_complete(self, batch_id: str, sample_id: str,
                                     recipe: Optional[Recipe]) -> None:
        if recipe is None:
            return
        jobs = self._store.list_jobs(sample_id=sample_id)
        if jobs and all(j["status"] in JOB_SATISFIED for j in jobs):
            self._store.update_sample(sample_id, status="DONE")
            self._materials.release_reservations(sample_id)
            self._store.log_event("sample_done", batch_id=batch_id, sample_id=sample_id)

    def _finalize_batch_if_complete(self, batch_id: str) -> None:
        batch = self._store.get_batch(batch_id)
        if batch is None or batch["status"] not in ("RUNNING",):
            return
        samples = self._store.list_samples(batch_id)
        if samples and all(s["status"] in ("DONE", "ABORTED") for s in samples):
            self._store.update_batch(batch_id, status="COMPLETED", finished_at=self._time())
            self._store.log_event("batch_completed", batch_id=batch_id)
            self._publish("batch_completed", batch_id=batch_id)

    def _hold_sample(self, sample_id: str, message: str) -> None:
        sample = self._store.get_sample(sample_id)
        if sample and sample["status"] == "ACTIVE":
            self._store.update_sample(sample_id, status="HOLD", message=message)

    def _slot_holder(self, slot: str, *, exclude: str = "") -> Optional[str]:
        for s in self._store.list_samples():
            if s["sample_id"] == exclude or s["status"] in ("DONE", "ABORTED"):
                continue
            if (s.get("position") or "") == slot:
                return s["sample_id"]
        return None

    # ------------------------------------------------------------------
    # 事件与快照
    # ------------------------------------------------------------------

    def on_vm_event(self, event: dict) -> None:
        """作为 event sink (bootstrap 经 late-box 注入): 轻量、全捕获、不阻塞."""
        try:
            etype = event.get("type") or ""
            run_id = event.get("run_id") or ""
            if etype in ("operation_done", "operation_failed"):
                # 任何运行 (含手动) 终态都可能释放资源 -> 补踢派发
                self._wake.set()
                return
            if etype in ("vm_human_request", "vm_human_reply") and run_id:
                job = self._store.job_by_run_id(run_id)
                if job and job["status"] in ("RUNNING", "WAITING_HUMAN"):
                    new_status = "WAITING_HUMAN" if etype == "vm_human_request" else "RUNNING"
                    if job["status"] != new_status:
                        self._store.update_job(job["job_id"], status=new_status)
                        self._publish("job_human", batch_id=job.get("batch_id") or "",
                                      job_id=job["job_id"], status=new_status)
        except Exception:
            log.debug("[调度] on_vm_event 异常 (忽略)", exc_info=True)

    def _publish(self, reason: str, **fields) -> None:
        self._revision += 1
        if self._bus is None:
            return
        now = self._time()
        # 合并节流 >=0.5s (前端另有 3s 轮询兜底); revision 单调, 丢一条不丢账
        if now - self._last_publish < 0.5 and reason not in ("batch_completed",):
            return
        self._last_publish = now
        try:
            self._bus.publish({"type": "scheduler_update", "reason": reason,
                               "revision": self._revision, "ts": now, **fields})
        except Exception:
            log.debug("[调度] 事件发布失败 (忽略)", exc_info=True)

    def snapshot(self) -> dict:
        """看板权威投影: 队列+样品段作业阵+资源占用+缸池+占位+等待原因+服务端钟."""
        batches = self._store.list_batches(limit=50)
        active = [b for b in batches if b["status"] in ("QUEUED", "RUNNING", "PAUSED")]
        out_batches = []
        for b in active:
            samples = self._store.list_samples(b["batch_id"])
            jobs = self._store.list_jobs(batch_id=b["batch_id"])
            by_sample: dict[str, list] = {}
            batch_jobs = []
            for j in jobs:
                row = {
                    "flow_id": j["flow_id"], "seq": j["af_index"], "script": j["script"],
                    "label": self._script_label(j["script"]),
                    "status": j["status"], "run_id": j.get("run_id") or "",
                    "attempt": j.get("attempt") or 0,
                    "started_at": j.get("started_at"), "finished_at": j.get("finished_at"),
                    "message": j.get("message") or "",
                    "failed_step": j.get("failed_step") or "",
                    "wait": self._wait_reasons.get(j["job_id"]),
                }
                if j.get("sample_id"):
                    by_sample.setdefault(j["sample_id"], []).append(row)
                else:
                    batch_jobs.append(row)
            out_batches.append({
                "batch_id": b["batch_id"], "name": b.get("name") or "",
                "recipe": b.get("recipe") or "", "status": b["status"],
                "priority": b.get("priority") or 0,
                "needs_reconcile": bool(b.get("needs_reconcile")),
                "sample_total": b.get("sample_total"), "sample_done": b.get("sample_done"),
                "batch_jobs": batch_jobs,
                "samples": [{
                    "sample_id": s["sample_id"], "seq": s["seq"], "status": s["status"],
                    "tank": s.get("tank"), "position": s.get("position") or "",
                    "message": s.get("message") or "",
                    "jobs": sorted(by_sample.get(s["sample_id"], []),
                                   key=lambda r: r["seq"]),
                } for s in samples],
            })
        return {
            "now": self._time(),
            "revision": self._revision,
            "boot_report": self._boot_report,
            "batches": out_batches,
            "resources": self._gate.snapshot(),
            "tanks": {str(t): owner for t, owner in sorted(self._tanks.items())},
            "occupancy": {k: v for k, v in self._occupancy.items()},
            "reservations": self._reservations_safe(),
            "wip_limit": self._wip_limit,
        }

    def _reservations_safe(self) -> dict:
        try:
            return self._materials.reserved_summary()
        except Exception:
            return {}

    def _require_batch(self, batch_id: str) -> dict:
        batch = self._store.get_batch(batch_id)
        if batch is None:
            raise KeyError(f"批次不存在: {batch_id}")
        return batch

    def _require_sample(self, batch_id: str, sample_id: str) -> dict:
        sample = self._store.get_sample(sample_id)
        if sample is None or sample.get("batch_id") != batch_id:
            raise KeyError(f"样品不存在于批次 {batch_id}: {sample_id}")
        return sample
