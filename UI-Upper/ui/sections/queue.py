"""样品队列 Tab - 显示样品列表与状态 + 入队表单

从 app.py 的 queue_section 迁移，新增入队表单功能。
"""

import asyncio
import copy
import logging
from pathlib import Path

from nicegui import ui

from ui.state import get_state
from core.scheduler import SampleRequest
from core.recipe import RecipeStore, default_recipe, validate_recipe

log = logging.getLogger(__name__)

# Queue Tab 入队时的临时配方伪选项（从 Recipe Tab 当前编辑中的配方落盘为快照）
_CURRENT_EDITING_OPTION = "<当前编辑中>"
_RECIPES_DIR = Path("recipes")

# ── 状态显示常量 ──
_STATUS_COLOR = {
    "PENDING":   "grey-6",
    "RUNNING":   "blue",
    "WAITING":   "amber-9",
    "DONE":      "green",
    "ERROR":     "red",
    "CANCELLED": "orange",
    "ESTOP":     "deep-orange",
}

_STATUS_LABEL = {
    "PENDING":   "待执行",
    "RUNNING":   "执行中 ▶",
    "WAITING":   "等待中 ⏳",
    "DONE":      "完成 ✓",
    "ERROR":     "错误 ✗",
    "CANCELLED": "已取消 ⊘",
    "ESTOP":     "急停中止 ⚠",
}


def render() -> dict:
    """渲染样品队列 Tab 内容。返回 refreshable 引用供 timer 刷新。"""

    @ui.refreshable
    def queue_section() -> None:
        state = get_state()
        if not state.sample_statuses:
            ui.label("暂无样品数据").classes("text-grey")
            return

        # 统计各状态数量
        pending = sum(1 for s in state.sample_statuses.values() if s == "PENDING")
        running = sum(1 for s in state.sample_statuses.values() if s == "RUNNING")
        waiting = sum(1 for s in state.sample_statuses.values() if s == "WAITING")
        done    = sum(1 for s in state.sample_statuses.values() if s == "DONE")
        errors  = sum(1 for s in state.sample_statuses.values() if s == "ERROR")

        with ui.row().classes("gap-3 q-mb-md flex-wrap"):
            ui.badge(f"待执行 {pending}", color="grey-6")
            if waiting:
                ui.badge(f"等待中 {waiting}", color="amber-9")
            ui.badge(f"执行中 {running}", color="blue")
            ui.badge(f"完成 {done}",   color="green")
            if errors:
                ui.badge(f"错误 {errors}", color="red")

        with ui.column().classes("w-full gap-2"):
            for sid, raw_status in state.sample_statuses.items():
                # 方案A：区分 WAITING（等锁/等资源）与 RUNNING（实际驱动 PLC）
                # 进一步：worker 接管但尚未走过任何工位的样品显示为 PENDING，
                # 避免连续入队同配方时后面的样品被误认为“等待中”。
                if raw_status == "RUNNING":
                    display_status = _classify_running_sample(state, sid)
                else:
                    display_status = raw_status
                color = _STATUS_COLOR.get(display_status, "grey")
                label = _STATUS_LABEL.get(display_status, display_status)
                with ui.card().classes("w-full q-pa-sm"):
                    with ui.row().classes("items-center gap-3"):
                        ui.badge(label, color=color)
                        ui.label(sid).classes("font-mono text-weight-medium")
                        # 显示最终结果
                        if display_status in ("DONE", "ERROR"):
                            detail = state.log_store.final_state(sid) or ""
                            if detail:
                                cls = (
                                    "text-caption text-grey"
                                    if display_status == "DONE"
                                    else "text-caption text-negative"
                                )
                                ui.label(detail).classes(cls)
                        # 取消按钮：所有未终止状态的样品均可取消
                        # PENDING / WAITING：无 PLC 副作用，直接取消
                        # RUNNING（驱动 PLC）：弹二次确认 dialog；NiceGUI 在事件 handler
                        # 协程上下文中 await 返回的 coroutine，保留 slot stack
                        if raw_status == "PENDING":
                            ui.button(
                                "取消", icon="cancel",
                                on_click=lambda s=sid: _cancel_sample(s),
                            ).props("flat dense size=sm color=orange")
                        elif raw_status == "RUNNING":
                            ui.button(
                                "取消", icon="cancel",
                                on_click=lambda s=sid: _cancel_sample(s),
                            ).props("flat dense size=sm color=orange")
                        # P2：配方参数预览
                        recipe = state.sample_recipes.get(sid)
                        if recipe is not None:
                            _render_recipe_preview(recipe)

    # 入队表单（静态，不需要刷新）
    with ui.card().classes("w-full q-pa-md q-mb-md"):
        ui.label("入队新样品").classes("text-subtitle1 text-weight-bold q-mb-sm")
        with ui.row().classes("items-center gap-3 flex-wrap"):
            sample_input = ui.input(
                "样品 ID", placeholder="例: S004"
            ).classes("w-40")

            # 动态拉取 recipes/*.yaml 名称，首位插入伪选项“<当前编辑中>”
            try:
                store = RecipeStore(_RECIPES_DIR)
                names = store.list_names()
            except Exception as e:
                log.warning("[Queue] 读取 recipes/ 失败: %s", e)
                names = []
            options = [_CURRENT_EDITING_OPTION] + names
            default_value = (
                _CURRENT_EDITING_OPTION
                if get_state().current_recipe is not None
                else (names[0] if names else _CURRENT_EDITING_OPTION)
            )

            recipe_select = ui.select(
                options=options, value=default_value, label="Recipe",
            ).classes("w-56")

            ui.button("刷新列表", icon="refresh", on_click=lambda: _refresh_options(
                recipe_select,
            )).props("flat dense")
            ui.button("入队", icon="add", on_click=lambda: _enqueue(
                sample_input, recipe_select,
            )).props("color=primary unelevated")

    queue_section()

    return {"queue": queue_section}


def _refresh_options(recipe_select) -> None:
    """重新扫 recipes/*.yaml，更新下拉选项。"""
    try:
        names = RecipeStore(_RECIPES_DIR).list_names()
    except Exception as e:
        ui.notify(f"刷新失败: {e}", type="negative")
        return
    recipe_select.options = [_CURRENT_EDITING_OPTION] + names
    recipe_select.update()
    ui.notify("配方列表已刷新", type="info")


def _enqueue(sample_input, recipe_select) -> None:
    """入队按钮回调：将新样品追加到 sample_statuses 并调用 Scheduler.enqueue。

    调度器未运行时：先触发 state.scheduler_starter 懒启动，等待最多 10s 就绪，
    再完成入队；若仍未就绪则提示用户检查 PLC 连接。
    """
    sid = sample_input.value.strip()
    if not sid:
        ui.notify("请输入样品 ID", type="warning")
        return
    state = get_state()
    if sid in state.sample_statuses:
        ui.notify(f"样品 {sid} 已存在", type="warning")
        return

    recipe_name = recipe_select.value
    store = RecipeStore(_RECIPES_DIR)

    # 分支 1：伪选项“<当前编辑中>” → 从 state.current_recipe 深拷贝 + 落盘临时文件
    if recipe_name == _CURRENT_EDITING_OPTION:
        if state.current_recipe is None:
            ui.notify("请先在 Recipe Tab 加载或新建配方", type="warning")
            return
        recipe_tpl = copy.deepcopy(state.current_recipe)
        try:
            tmp_path = store.save_tmp(recipe_tpl, sid)
            # 内存副本改名为临时快照标识，避免 Queue 卡片 / DONE 日志
            # 误把 state.current_recipe.name（如 standard_pTLC）当成实际入队配方。
            # 落盘 yaml 保留源 name 字段，便于追溯血缘。
            recipe_tpl.name = f"<editing>:{tmp_path.stem}"
            log.info("[Queue] 样品 %s 使用临时快照: %s", sid, tmp_path)
            audit_name = f"<editing>:{tmp_path.name}"
        except Exception as e:
            ui.notify(f"临时配方落盘失败: {e}", type="negative")
            return
    else:
        # 分支 2：具体配方名 → 读盘
        try:
            recipe_tpl = store.load(recipe_name)
        except FileNotFoundError:
            recipe_tpl = default_recipe()
            ui.notify(f"Recipe '{recipe_name}' 未找到，使用默认配方", type="info")
        audit_name = recipe_name

    # 构造 SampleRequest
    # 配方静态校验（预检）：参数越界 / 业务约束不过 → 拒绝入队
    # 避免在 RecipeTask.run() 跑到特定 Stage 才暴露在参数问题。
    errors = validate_recipe(recipe_tpl)
    if errors:
        msg = "配方校验失败，未入队：\n• " + "\n• ".join(errors)
        log.warning("[Queue] 样品 %s 配方校验失败: %s", sid, errors)
        ui.notify(msg, type="negative", multi_line=True, timeout=10000,
                  close_button="关闭")
        return

    req = SampleRequest(
        sample_id=sid,
        before_path=Path(""),
        after_path=Path(""),
        action_timeout=15.0,
        recipe=recipe_tpl,
    )

    # 调度器可用 → 直接入队
    # UI 层防护：Debug Tab 不经 RM 分配展缸，Scheduler 并发任务可能分配同一展缸
    if state.active_develop_stage is not None:
        ui.notify("Debug 工位 develop 正在执行中，请等待完成后再入队", type="warning")
        return
    if state.scheduler is not None:
        asyncio.create_task(state.scheduler.enqueue(req))
        state.sample_statuses[sid] = "PENDING"
        state.sample_recipes[sid] = copy.deepcopy(recipe_tpl)  # P2：配方快照
        state.log_store.append(sid, "ENQUEUED", f"UI入队 recipe={audit_name}")
        sample_input.value = ""
        ui.notify(f"样品 {sid} 已入队", type="positive")
        return

    # 调度器未运行 → 触发懒启动，并在后台等待就绪后入队
    starter = getattr(state, "scheduler_starter", None)
    if starter is None:
        ui.notify("调度器未初始化，请检查 UI 启动流程", type="negative")
        return
    starter()  # 启动后台任务，由其负责连 PLC 并赋值 state.scheduler
    sample_input.value = ""
    ui.notify(f"调度器正在启动，样品 {sid} 将在就绪后自动入队…", type="info")
    asyncio.create_task(_deferred_enqueue(req, audit_name))


async def _deferred_enqueue(req: SampleRequest, audit_name: str) -> None:
    """等待 scheduler 就绪后完成入队（最多 10 秒）。

    注意：本函数在后台 asyncio Task 中运行，不能直接调用 ui.notify()
    （会触发 NiceGUI slot stack 为空的 RuntimeError），
    改用 state._notification_queue 排队，由 UI timer 在主线程消费。
    """
    state = get_state()
    for _ in range(100):
        if state.scheduler is not None:
            break
        await asyncio.sleep(0.1)
    if state.scheduler is None:
        state.log_store.append(req.sample_id, "ENQUEUE_FAILED", "调度器启动超时")
        _queue_notify(state, f"样品 {req.sample_id} 入队失败：调度器启动超时", "negative")
        return
    await state.scheduler.enqueue(req)
    state.sample_statuses[req.sample_id] = "PENDING"
    state.sample_recipes[req.sample_id] = copy.deepcopy(req.recipe)  # P2：配方快照
    state.log_store.append(req.sample_id, "ENQUEUED", f"UI入队(延迟) recipe={audit_name}")
    _queue_notify(state, f"样品 {req.sample_id} 已入队", "positive")


def _queue_notify(state, message: str, ntype: str = "info") -> None:
    """在后台任务中安全排队通知，由 UI timer 消费。"""
    q = getattr(state, "_notification_queue", None)
    if q is not None:
        q.append((message, ntype))
    else:
        log.info("[Queue] 通知（无队列）: %s", message)


def _classify_running_sample(state, sid: str) -> str:
    """对 raw_status==RUNNING 的样品进一步分类（方案A 扩展）。

    扫描 log_store 事件流（从新到旧）：
    - 最近一条阶段事件是 STAGE_START 且未匹配 STAGE_DONE
      → "RUNNING"（实际驱动 PLC）
    - 最近一条阶段事件是 STAGE_DONE
      → "WAITING"（某阶段已完成，正在等下一阶段锁/资源）
    - 没有任何 STAGE_START
      → "PENDING"（worker 接管但未起步，连续入队同配方时后面的样品处于该状态）
    """
    from core import flow_events as fe
    for entry in reversed(state.log_store.get_sample(sid)):
        if entry.event == fe.STAGE_DONE:
            return "WAITING"
        if entry.event == fe.STAGE_START:
            return "RUNNING"
    return "PENDING"


def _is_sample_actively_running(state, sid: str) -> bool:
    """兼容保留：仅当样品“实际驱动 PLC”时返回 True。"""
    return _classify_running_sample(state, sid) == "RUNNING"


def _cancel_sample(sample_id: str):
    """取消样品同步包装：可被 on_click 直接调用，返回协程交给 NiceGUI await。

    NiceGUI 能将同步 handler 返回的 coroutine 在事件 slot 上下文内 await，
    从而保留 dialog 的 slot stack 上下文（不能用 asyncio.create_task，
    否则 slot stack empty）。
    """
    return _cancel_sample_async(sample_id)


async def _cancel_sample_async(sample_id: str) -> None:
    """取消样品（三态分发）。

    PENDING: 调用 Scheduler.cancel_sample() 从队列移除，立即更新状态。
    WAITING（RUNNING 但未驱动 PLC）: 调用 Scheduler.cancel_running_sample()
        通过 task.cancel() 中断等锁，安全无 PLC 副作用。
    RUNNING（实际驱动 PLC）: 弹二次确认 dialog 后调用 cancel_running_sample()。
        上位机仅释放自身资源（耗材占位 / 展缸 / handoff）；
        PLC 侧由用户到 PLC HMI 切手动 / Recovery Tab Reset 脉冲处理。
    """
    state = get_state()
    status = state.sample_statuses.get(sample_id)
    if status not in ("PENDING", "RUNNING"):
        ui.notify(f"样品 {sample_id} 当前状态为 {status}，无法取消", type="warning")
        return

    # 区分 display 状态：RUNNING 中进一步分类
    if status == "RUNNING":
        display = _classify_running_sample(state, sample_id)
    else:
        display = status

    # 真 RUNNING（驱动 PLC）→ 弹 dialog 二次确认
    if display == "RUNNING":
        await _cancel_running_with_confirm(sample_id)
        return

    # PENDING / WAITING / 未起步 → 直接取消
    if state.scheduler is not None:
        if status == "PENDING":
            ok = state.scheduler.cancel_sample(sample_id)
            if not ok:
                # PENDING → 可能已变为 RUNNING，尝试 cancel_running
                ok2 = state.scheduler.cancel_running_sample(sample_id)
                if not ok2:
                    cur = state.sample_statuses.get(sample_id)
                    if cur in ("DONE", "ERROR", "CANCELLED"):
                        ui.notify(f"样品 {sample_id} 已结束（{cur}）", type="info")
                        return
                    ui.notify(f"样品 {sample_id} 无法取消", type="warning")
                    return
                state.log_store.append(sample_id, "CANCEL_REQUEST", f"用户取消({display})")
                ui.notify(f"样品 {sample_id} 正在取消…", type="info")
                return
            # PENDING 取消成功
            state.sample_statuses[sample_id] = "CANCELLED"
            state.log_store.append(sample_id, "CANCELLED", "队列中取消")
            ui.notify(f"样品 {sample_id} 已取消", type="info")
        else:  # RUNNING (display == WAITING / PENDING)
            state.log_store.append(sample_id, "CANCEL_REQUEST", f"用户取消({display})")
            ok = state.scheduler.cancel_running_sample(sample_id)
            if not ok:
                cur = state.sample_statuses.get(sample_id)
                if cur in ("DONE", "ERROR", "CANCELLED"):
                    ui.notify(f"样品 {sample_id} 已结束（{cur}）", type="info")
                    return
                ui.notify(f"样品 {sample_id} 无法取消", type="warning")
                return
            ui.notify(f"样品 {sample_id} 正在取消…", type="info")
    else:
        # 无 scheduler 时直接设 CANCELLED
        state.sample_statuses[sample_id] = "CANCELLED"
        state.log_store.append(sample_id, "CANCELLED", "UI 取消")
        ui.notify(f"样品 {sample_id} 已取消", type="info")


async def _cancel_running_with_confirm(sample_id: str) -> None:
    """二次确认后取消真正驱动 PLC 的 RUNNING 样品。

    本函数需在 NiceGUI 事件 handler 的 await 调用链中运行以保留 slot 上下文；
    禁止包在 asyncio.create_task 内调用（会丢失 slot context 并报 stack empty）。
    """
    with ui.dialog() as dlg, ui.card().classes("q-pa-md").style("min-width: 480px"):
        ui.label(f"确认取消样品 {sample_id}?").classes("text-h6")
        ui.label("上位机将：").classes("text-body2 q-mt-sm text-weight-medium")
        ui.label(
            "  ✓ 释放该样品占用的耗材占位、展缸资源\n"
            "  ✓ 标记任务取消，停止后续 stage 调度"
        ).classes("text-body2").style("white-space: pre-line")
        ui.label("PLC 工位：").classes("text-body2 q-mt-sm text-weight-medium")
        ui.label(
            "  ✗ 上位机不会主动操作 PLC FSM\n"
            "  ✗ 当前正在执行的硬件动作会自然跑完\n"
            "  → 取消后请确认 PLC 工位状态：\n"
            "     如卡在中间子步，请到 PLC HMI 切手动复位\n"
            "     或在 Recovery Tab → Reset 脉冲区点击对应工位 Reset"
        ).classes("text-caption text-orange-9").style("white-space: pre-line")
        ui.label("其他正在执行的样品不受影响。").classes("text-caption text-grey q-mt-sm")
        with ui.row().classes("justify-end gap-2 q-mt-md"):
            ui.button("返回", on_click=lambda: dlg.submit(False)).props(
                "flat color=grey"
            )
            ui.button("确认取消", on_click=lambda: dlg.submit(True)).props(
                "color=orange unelevated"
            )
    result = await dlg
    if not result:
        return

    state = get_state()
    if state.scheduler is None:
        ui.notify("调度器未运行", type="warning")
        return
    state.log_store.append(sample_id, "CANCEL_REQUEST", "用户取消(RUNNING,已确认)")
    ok = state.scheduler.cancel_running_sample(sample_id)
    if not ok:
        cur = state.sample_statuses.get(sample_id)
        if cur in ("DONE", "ERROR", "CANCELLED"):
            ui.notify(f"样品 {sample_id} 已结束（{cur}）", type="info")
        else:
            ui.notify(f"样品 {sample_id} 无法取消", type="warning")
        return
    ui.notify(f"样品 {sample_id} 正在取消…", type="info")


def _render_recipe_preview(recipe) -> None:
    """在队列卡片中渲染配方参数预览（只读）。"""
    from core.stages import STAGE_ORDER, STAGE_REGISTRY

    with ui.expansion(f"配方: {recipe.name}", icon="science").classes("w-full"):
        with ui.column().classes("gap-1 w-full"):
            for sp in recipe.stages:
                stage_cls = STAGE_REGISTRY.get(sp.name)
                enabled_icon = "check_circle" if sp.enabled else "cancel"
                enabled_color = "green" if sp.enabled else "grey"
                with ui.row().classes("items-center gap-2"):
                    ui.icon(enabled_icon, color=enabled_color, size="xs")
                    ui.label(sp.name).classes("text-caption font-mono text-weight-medium")
                    if not sp.enabled:
                        ui.label("(跳过)").classes("text-caption text-grey")
                if sp.enabled and sp.params and stage_cls is not None:
                    schema = stage_cls.PARAMS_SCHEMA
                    with ui.row().classes("gap-3 q-ml-md flex-wrap"):
                        for key, val in sp.params.items():
                            meta = schema.get(key)
                            label = meta["label"] if meta else key
                            ui.label(f"{label}: {val}").classes(
                                "text-caption text-grey-7"
                            )
