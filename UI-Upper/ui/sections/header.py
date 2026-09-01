"""Header 区域 - PLC 状态徽章 + 连接指示 + 人工确认区 + 重连确认区

从 app.py 的 status_section / reconnect_section / confirm_section 迁移。
使用 NiceGUI 的 ui.header() 固定顶部。

Phase F 新增：
  - "连接 PLC" 按钮：独立于调度器，允许用户手动建立 PLC 连接（点动调试用）
  - "断开 PLC" 按钮：手动断开，清理 plc_client 引用
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from nicegui import ui

from core.plc_client import PLCClient, PLCState
from core.stages.collect import COLLECT_SUB_STEPS
from core.variable_monitor import VariableMonitor
from ui.state import get_state, resolve_confirm, resolve_resume, on_plc_state_ui

log = logging.getLogger(__name__)


def _estop_goto_recovery() -> None:
    """E-Stop 横幅按钮：跳转到 Recovery Tab 供用户按向导解除急停。

    不直接调用 reset_estop()——绕过 Recovery 三段式安全闸门（排液检查 +
    Reset 脉冲 + 现场确认）会遗留 PLC 侧锁存状态和未排液的展缸。
    """
    state = get_state()
    tab_panels = getattr(state, '_tab_panels', None)
    tab_recovery = getattr(state, '_tab_recovery', None)
    if tab_panels and tab_recovery:
        tab_panels.set_value(tab_recovery)
    else:
        ui.notify("请手动切换到 Recovery Tab 解除急停", type="info")


def render() -> None:
    """渲染固定 Header 区域。"""

    @ui.refreshable
    def status_section() -> None:
        with ui.card().classes("w-full q-pa-md"):
            # E-Stop 急停警告横幅（最顶部，醒目红色）
            state = get_state()
            if state.estop_active:
                with ui.card().classes("w-full").style(
                    "border: 2px solid #dc2626; background: #fef2f2;"
                ):
                    with ui.row().classes("items-center gap-4"):
                        ui.icon("warning", color="red", size="lg")
                        ui.label("⚠ 急停信号触发！所有运行中任务已终止").classes(
                            "text-h6 text-weight-bold text-red"
                        )
                        ui.button(
                            "前往 Recovery Tab",
                            icon="health_and_safety",
                            on_click=lambda: _estop_goto_recovery(),
                        ).props("color=negative unelevated")

            with ui.row().classes("items-center gap-4 flex-wrap"):
                # PLC 连接状态
                state = get_state()
                if state.plc_state == "connected":
                    ui.badge("● PLC 已连接", color="green")
                elif state.plc_state == "reconnecting":
                    ui.badge("↻ PLC 重连中", color="orange")
                elif state.plc_state == "error":
                    ui.badge("✕ PLC 错误", color="red")
                else:
                    ui.badge("○ PLC 未连接", color="grey")
                    # 独立连接按钮：不依赖调度器，允许点动调试
                    ui.button(
                        "连接 PLC",
                        icon="cable",
                        on_click=lambda: _connect_plc(),
                    ).props("color=primary unelevated dense size=sm")

                # 已连接时显示断开按钮（仅未运行调度器时）
                if state.plc_state == "connected" and not state.scheduler_running:
                    ui.button(
                        "断开 PLC",
                        icon="link_off",
                        on_click=lambda: _disconnect_plc(),
                    ).props("color=grey unelevated dense size=sm")

                # 调度器状态
                if state.scheduler_running:
                    ui.badge("⚙ 运行中", color="blue")
                elif state.scheduler_done:
                    ui.badge("✓ 已完成", color="green")
                else:
                    ui.badge("⏳ 待启动", color="grey")

                # 重连次数（> 0 才显示）
                if state.reconnect_count > 0:
                    ui.badge(f"重连过 {state.reconnect_count} 次", color="purple")

            # 当前样品（并发安全：展示所有活跃样品）
            if state.active_sample_ids:
                ui.separator()
                ids_str = ", ".join(sorted(state.active_sample_ids))
                ui.label(
                    f"当前样品：{ids_str}"
                ).classes("text-weight-bold text-blue")

            # 收集流程子步徽章（仅在 collect_Step != 0 时显示）
            collect_step = state.variable_snapshot.get("collect_Step")
            if collect_step is not None:
                try:
                    code = int(collect_step)
                except (TypeError, ValueError):
                    code = 0
                if code != 0 and code in COLLECT_SUB_STEPS:
                    _, label = COLLECT_SUB_STEPS[code]
                    color = "red" if code == 90 else "green"
                    ui.separator()
                    with ui.row().classes("items-center gap-2"):
                        ui.label("收集子步：").classes("text-caption")
                        ui.badge(f"{code} · {label}", color=color)

            # 错误信息
            if state.error_msg:
                ui.separator()
                ui.label(f"错误：{state.error_msg}").classes("text-negative")

    @ui.refreshable
    def reconnect_section() -> None:
        state = get_state()
        # RECONNECTING 时展示黄色提示
        if state.plc_state == "reconnecting":
            with ui.card().classes("w-full").style(
                "border-left: 4px solid #f59e0b; background: #fffbeb;"
            ):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sync", color="orange", size="sm")
                    ui.label("PLC 失联中，自动重连已启动…队列已暂停").classes(
                        "text-subtitle1 text-weight-bold"
                    )

        # 重连成功后等待用户确认是否继续队列
        if state.resume_future is not None:
            with ui.card().classes("w-full").style(
                "border-left: 4px solid #10b981; background: #ecfdf5;"
            ):
                with ui.row().classes("items-center gap-2 q-mb-sm"):
                    ui.icon("check_circle", color="green", size="sm")
                    ui.label("PLC 已重连— 是否继续执行剩余样品？").classes(
                        "text-subtitle1 text-weight-bold"
                    )
                with ui.row().classes("gap-4 q-mt-sm"):
                    ui.button(
                        "继续队列",
                        on_click=lambda: resolve_resume(True),
                    ).props("color=positive icon=play_arrow unelevated")
                    ui.button(
                        "停止队列",
                        on_click=lambda: resolve_resume(False),
                    ).props("color=negative icon=stop unelevated")

    @ui.refreshable
    def confirm_section() -> None:
        state = get_state()
        if state.confirm_sample_id is None:
            return
        with ui.card().classes("w-full").style(
            "border-left: 4px solid #f59e0b; background: #fffbeb;"
        ):
            with ui.row().classes("items-center gap-2 q-mb-sm"):
                ui.icon("warning", color="orange", size="sm")
                ui.label("视觉分析失败 — 需要人工确认").classes(
                    "text-subtitle1 text-weight-bold"
                )
            ui.label(
                f"样品 {state.confirm_sample_id} 的视觉识别结果无效，"
                "请选择如何处理："
            ).classes("text-body2")
            with ui.row().classes("gap-4 q-mt-md"):
                ui.button(
                    "继续执行",
                    on_click=lambda: resolve_confirm(True),
                ).props("color=positive icon=play_arrow unelevated")
                ui.button(
                    "终止该样品",
                    on_click=lambda: resolve_confirm(False),
                ).props("color=negative icon=stop unelevated")

    # Header 下方状态/确认/重连卡片区（非顶级元素，可放在 column 内）
    # 注意：ui.header() 标题栏由 app.py 在 ui.column() 外部渲染，不能在此处调用
    with ui.column().classes("w-full gap-2"):
        reconnect_section()
        confirm_section()
        status_section()

    # 返回 refreshable 引用供 timer 刷新
    return {
        "status": status_section,
        "reconnect": reconnect_section,
        "confirm": confirm_section,
    }


# ──────────────────────────────────────────────────────────────
# PLC 独立连接 / 断开（供点动调试用，不依赖调度器）
# ──────────────────────────────────────────────────────────────

async def _plc_standalone_task(plc_url: str, reconnect_wait_timeout: float) -> None:
    """独立 PLC 连接后台任务：建连 + 心跳 + VariableMonitor + 轮询回退，不启动调度器。"""
    state = get_state()
    vm = VariableMonitor()
    # 将 VariableMonitor 快照同步到 state.variable_snapshot
    def _sync_snapshot(var_name: str, val: Any) -> None:
        state.variable_snapshot[var_name] = val
    vm.add_listener(_sync_snapshot)
    poll_task = None
    try:
        async with PLCClient(
            url=plc_url,
            reconnect_wait_timeout=reconnect_wait_timeout,
        ) as plc:
            plc.add_state_listener(on_plc_state_ui)
            state.plc_state = plc.state.value
            state.plc_connected = True
            state.plc_client = plc
            # 启动 VariableMonitor（用 PLCClient 内部 client_session）
            try:
                await vm.start(plc.client_session)
                state.variable_snapshot.update(vm.snapshot)
            except Exception as e:
                log.warning("[PLC独立连接] VariableMonitor 启动失败: %s", e)
            # 自动扫描 PLC 全部变量并扩展订阅（实机可能有额外变量）
            try:
                new_count = await vm.auto_discover(plc.client_session)
                state.variable_snapshot.update(vm.snapshot)
                if new_count > 0:
                    log.info("[PLC独立连接] auto_discover 新增 %d 个变量", new_count)
            except Exception as e:
                log.debug("[PLC独立连接] auto_discover 失败（不影响基本功能）: %s", e)
            # 注入 VariableMonitor，供 Debug Tab 扫描变量调用
            state.variable_monitor = vm
            # 启动轮询回退：每 500ms 通过 PLCClient 主动读取所有变量
            poll_task = asyncio.create_task(_poll_loop(vm, plc, state))
            state.log_store.append(
                "DEBUG", "PLC_CONNECTED",
                f"url={plc_url} (独立连接，无调度器)",
            )
            # 阻塞保持连接，直到被取消
            while True:
                await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        log.info("[PLC独立连接] 被取消，正常退出")
    except Exception as e:
        state.error_msg = f"PLC 连接失败: {e}"
        log.error("[PLC独立连接] 失败: %s", e)
    finally:
        if poll_task and not poll_task.done():
            poll_task.cancel()
        await vm.stop()
        state.plc_connected = False
        state.plc_client = None
        state.variable_monitor = None
        state.plc_state = "disconnected"
        state.variable_snapshot.clear()
        # 触发 PLC 状态回调（刷新 jog_section 等）
        for cb in list(state._plc_state_callbacks):
            try:
                cb()
            except Exception:
                pass


def _connect_plc() -> None:
    """点击“连接 PLC”按钮：启动独立后台连接任务。"""
    state = get_state()
    if state.plc_client is not None:
        ui.notify("PLC 已连接", type="info")
        return
    # 将后台任务保存在 state 上，方便后续断开
    task = asyncio.create_task(
        _plc_standalone_task(state.plc_url, state.reconnect_wait_timeout)
    )
    state._standalone_plc_task = task
    ui.notify("正在连接 PLC…", type="info")


def _disconnect_plc() -> None:
    """点击“断开 PLC”按钮：取消独立后台连接任务。"""
    state = get_state()
    task = getattr(state, "_standalone_plc_task", None)
    if task is not None and not task.done():
        task.cancel()
        state._standalone_plc_task = None
        ui.notify("PLC 已断开", type="info")
    else:
        ui.notify("PLC 未在独立连接模式", type="warning")


async def _poll_loop(vm: VariableMonitor, plc: PLCClient, state) -> None:
    """轮询回退：每 500ms 通过 PLCClient 主动读取所有变量，更新 VariableMonitor 快照和 state。

    当 asyncua 订阅通知不可靠时（如 mock server 场景），此轮询保证 UI 快照与 PLC 实际值同步。
    同步全部 polled 变量到 vm.snapshot（不再仅限于 MONITORED_VARS），
    确保 guarded_write / extend_subscription 等读 vm.snapshot 的逻辑看到完整数据。
    """
    while True:
        await asyncio.sleep(0.5)
        try:
            polled = await plc.poll_snapshot()
            if not polled:
                continue
            # 同步全部 polled 变量到 vm.snapshot + 触发监听器
            for var_name, val in polled.items():
                old = vm.snapshot.get(var_name)
                vm.snapshot[var_name] = val
                vm.timestamps[var_name] = datetime.now()
                if old != val:
                    for cb in vm._listeners:
                        try:
                            cb(var_name, val)
                        except Exception:
                            pass
            # 同步到 state.variable_snapshot
            state.variable_snapshot.update(polled)
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.debug("[PollLoop] 轮询失败: %s", e)
