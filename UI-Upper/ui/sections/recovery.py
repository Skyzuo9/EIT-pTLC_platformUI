"""Recovery Tab - 急停恢复向导（极简方案 B）

急停触发后引导用户完成：
  1. 强制排液处于 NEEDS_DRAIN 状态的展缸
  2. 对各工位发送 _Reset 脉冲，清除 PLC 错误状态
  3. 人工确认现场安全后解除上位机急停状态

设计原则（奥卡姆剃刀）：
- 不创建 core/recovery/ 抽象层；直接调用 PLCClient + ResourceManager + estop 公共 API
- 不实施 AUTO_PLC/MANUAL_CHECK/USER_DECISION 三态 step 类型
- 不持久化 Recovery 进度（重启后从 PLC 读取 Tank_State 重建）
"""

import asyncio
import logging
import time

from nicegui import ui

from ui.state import get_state

log = logging.getLogger(__name__)

# 工位 Reset 变量映射（Stage名 → PLC Reset 变量名）
# scrape 和 before_photo 共用同一 PLC FSM (scrape 前缀)，只需一个按钮
_STAGE_RESET_MAP = {
    "spotting":   "Sampling_Reset",
    "scrape":     "scrape_Reset",
    "develop":    "Expand_Reset",
    "collect":    "collect_Reset",
}

_STAGE_LABEL_MAP = {
    "spotting": "点样工位 (Sampling)",
    "scrape":   "刮板/拍照工位 (scrape + before_photo)",
    "develop":  "展开工位 (Expand)",
    "collect":  "收集工位 (collect)",
}

# NEEDS_DRAIN 强制排液超时（秒）
_DRAIN_TIMEOUT = 120.0

# handoff 孤儿诊断阈值（秒）：handoff_pending 超过该时间且样品已下台 → 标记为孤儿
_HANDOFF_ORPHAN_THRESHOLD_S = 300.0


def render() -> dict:
    """渲染 Recovery 急停恢复 Tab。"""
    state = get_state()

    # ── 顶部告警条 ──────────────────────────────────────────────────────
    @ui.refreshable
    def _alert_bar():
        s = get_state()
        if s.estop_active:
            with ui.card().classes(
                "bg-red-600 text-white text-body1 q-pa-sm rounded"
            ):
                ui.label(
                    "⚠ 急停已触发 — 请按下方清单逐项处理后才可解除急停"
                )
        else:
            ui.label("系统正常运行中，无急停状态。").classes("text-grey q-pa-sm")

    _alert_bar()

    # ── Section 1：NEEDS_DRAIN 展缸列表 ─────────────────────────────────
    ui.separator()
    with ui.expansion("① 展缸强制排液（NEEDS_DRAIN）", icon="opacity",
                      value=True).classes("w-full"):

        @ui.refreshable
        def _drain_section():
            s = get_state()
            rm = getattr(s, "resource_manager", None)
            plc = s.plc_client

            if rm is None:
                ui.label("ResourceManager 未连接（调度器未运行）").classes("text-grey")
                return

            tanks = rm.needs_drain_tanks()
            if not tanks:
                ui.label("✓ 无待排液展缸").classes("text-positive")
                return

            ui.label(f"以下展缸处于 NEEDS_DRAIN 状态，需强制排液后方可重新使用：").classes(
                "text-warning q-mb-sm")

            for tank_id in tanks:
                with ui.row().classes("items-center gap-4 q-mb-xs"):
                    ui.label(f"展缸 {tank_id}").classes("text-body1 w-16 text-bold")
                    ui.badge("NEEDS_DRAIN", color="orange")

                    # 强制排液按钮（超时后禁用，防止重复置位 PLC Drain_Enable）
                    drain_btn = ui.button("强制排液并释放").props(
                        "color=orange dense"
                    )

                    async def _do_drain(tid=tank_id, btn=drain_btn):
                        if plc is None:
                            ui.notify("PLC 未连接，无法操作", type="warning")
                            return
                        try:
                            ui.notify(f"展缸 {tid}：触发强制排液...", type="info")
                            await plc.trigger_drain(tid)
                            await plc.await_drain_done(tid, timeout=_DRAIN_TIMEOUT)
                            await rm.manual_release(tid)
                            ui.notify(f"展缸 {tid} 排液完成，已释放", type="positive")
                            _drain_section.refresh()
                            _release_btn_update()  # 同步刷新"解除急停"按钮状态
                        except RuntimeError as e:
                            ui.notify(f"展缸 {tid} 排液失败: {e}", type="negative")
                        except (asyncio.TimeoutError, TimeoutError):
                            if btn:
                                btn.disable()
                            ui.notify(
                                f"展缸 {tid} 排液超时（{_DRAIN_TIMEOUT:.0f}s），请人工检查",
                                type="negative",
                            )
                        except Exception as e:
                            ui.notify(f"展缸 {tid} 操作异常: {e}", type="negative")
                            log.exception("[Recovery] 展缸 %d 强制排液异常", tid)

                    drain_btn.on_click(_do_drain)

        _drain_section()

    # ── Section 2：工位 Reset 脉冲 ───────────────────────────────────────
    ui.separator()
    with ui.expansion("② 工位 Reset 脉冲（清除 PLC 错误状态）", icon="refresh_circle",
                      value=True).classes("w-full"):
        ui.label(
            "对各工位发送 _Reset=TRUE→FALSE 脉冲，清除 PLC 侧 Error 锁存。"
        ).classes("text-caption text-grey q-mb-xs")
        ui.label(
            "提示：如某样品取消后该工位 FSM 卡住未自动归零"
            "（可在 Flow Tab 查看 Step 值），点击对应 Reset 即可清除。"
        ).classes("text-caption text-orange-8 q-mb-sm")

        with ui.grid(columns=2).classes("w-full gap-2"):
            for stage_key, reset_var in _STAGE_RESET_MAP.items():
                label = _STAGE_LABEL_MAP[stage_key]

                async def _do_reset(var=reset_var, lbl=label):
                    s = get_state()
                    if s.plc_client is None:
                        ui.notify("PLC 未连接", type="warning")
                        return
                    try:
                        await s.plc_client.write_variable(var, True)
                        await asyncio.sleep(0.15)
                        await s.plc_client.write_variable(var, False)
                        ui.notify(f"{lbl} Reset 脉冲已发送", type="positive")
                        log.info("[Recovery] %s Reset 脉冲发送完成", var)
                    except Exception as e:
                        ui.notify(f"{lbl} Reset 失败: {e}", type="negative")
                        log.warning("[Recovery] %s Reset 失败: %s", var, e)

                with ui.card().classes("q-pa-sm"):
                    ui.label(label).classes("text-caption text-bold")
                    ui.label(f"变量: {reset_var}").classes("text-caption text-grey")
                    ui.button("发送 Reset", on_click=_do_reset).props(
                        "color=blue-grey dense flat"
                    )

    # ── Section 2.5：handoff 孤儿诊断（PC 侧台账，不动 PLC）
    ui.separator()
    with ui.expansion(
        "②½ 展缸 handoff 诊断（PC 侧台账）",
        icon="swap_horiz",
        value=False,
    ).classes("w-full"):
        ui.label(
            "查看处于 handoff_pending=True 的展缸（已排液但尚未被刮板工位接管）。"
            "若对应样品已下台且标记超过阈值 → 为孤儿，可手动降级为 NEEDS_DRAIN。"
        ).classes("text-caption text-grey q-mb-sm")

        @ui.refreshable
        def _handoff_section():
            s = get_state()
            rm = getattr(s, "resource_manager", None)
            scheduler = s.scheduler
            if rm is None:
                ui.label("ResourceManager 未连接（调度器未运行）").classes("text-grey")
                return
            entries = rm.peek_handoff_pending()
            if not entries:
                ui.label("✓ 无处于 handoff_pending 的展缸").classes("text-positive")
                return

            running_ids = scheduler.running_sample_ids() if scheduler is not None else set()
            now = time.monotonic()

            for tank_id, sample_id, allocated_at in entries:
                age = (now - allocated_at) if allocated_at is not None else 0.0
                # 孤儿判定：样品不在运行集合 且 标记时长超阈值
                is_orphan = (
                    sample_id is not None
                    and sample_id not in running_ids
                    and age >= _HANDOFF_ORPHAN_THRESHOLD_S
                )
                with ui.row().classes("items-center gap-3 q-mb-xs"):
                    ui.label(f"展缸 {tank_id}").classes("text-body1 w-16 text-bold")
                    ui.label(f"sample={sample_id or '-'}").classes("text-caption w-32")
                    ui.label(f"时长={age:.0f}s").classes("text-caption w-20")
                    if is_orphan:
                        ui.badge("ORPHAN", color="red")
                    elif sample_id in running_ids:
                        ui.badge("RUNNING", color="blue")
                    else:
                        ui.badge("PENDING", color="grey")

                    btn = ui.button("降级为 NEEDS_DRAIN").props("color=orange dense flat")
                    if not is_orphan:
                        btn.disable()

                    async def _do_demote(tid=tank_id, sid=sample_id, ag=age):
                        # 二次确认 dialog：避免误点造成 NEEDS_DRAIN 池污染。
                        # 使用 await dialog 保证 slot 上下文（NiceGUI 已知陷阱）。
                        with ui.dialog() as confirm_dlg, ui.card().classes("q-pa-md"):
                            ui.label("手动降级为 NEEDS_DRAIN").classes("text-h6")
                            ui.label(
                                f"展缸 {tid}\u3000sample={sid or '-'}\u3000已标记 {ag:.0f}s"
                            ).classes("text-body2 q-mb-sm")
                            ui.label(
                                "该操作仅修改 PC 侧账本，不会写 PLC。后续需在 ① 中手动强制排液。"
                            ).classes("text-caption text-grey q-mb-sm")
                            with ui.row().classes("gap-2 q-mt-sm"):
                                ui.button(
                                    "取消",
                                    on_click=lambda: confirm_dlg.submit(False),
                                ).props("flat")
                                ui.button(
                                    "确认降级",
                                    on_click=lambda: confirm_dlg.submit(True),
                                ).props("color=orange")
                        confirmed = await confirm_dlg
                        if not confirmed:
                            return
                        try:
                            # 复用 E-Stop 路径：mark_needs_drain=True 不写 PLC，
                            # 仅 PC 侧账本降级，后续由 Section ① 强制排液接管。
                            await rm.release(tid, mark_needs_drain=True)
                            log.warning(
                                "[Recovery] handoff 孤儿手动降级: tank=%d (was sample=%s, age=%.0fs)",
                                tid, sid, ag,
                            )
                            ui.notify(
                                f"展缸 {tid} 已降级为 NEEDS_DRAIN，请在①中强制排液",
                                type="warning",
                            )
                            _handoff_section.refresh()
                            _drain_section.refresh()
                        except Exception as ex:
                            ui.notify(f"降级失败: {ex}", type="negative")
                            log.exception("[Recovery] tank=%d 降级 NEEDS_DRAIN 异常", tid)

                    btn.on_click(_do_demote)

        _handoff_section()

    # ── Section 3：现场安全确认 ──────────────────────────────────────────
    ui.separator()
    with ui.expansion("③ 现场安全确认", icon="verified_user", value=True).classes("w-full"):
        site_checked = {"v": False}

        def _on_check(e):
            site_checked["v"] = e.value
            _release_btn_update()

        with ui.row().classes("items-center gap-2"):
            ui.icon("warning", color="orange")
            check = ui.checkbox(
                "我已检查现场，所有工位处于安全状态，管路/机器人/泵均已停止",
                on_change=_on_check,
            ).classes("text-body2")

    # ── 底部：解除急停 ───────────────────────────────────────────────────
    ui.separator()

    def _can_release() -> bool:
        s = get_state()
        if not s.estop_active:
            return False
        rm = getattr(s, "resource_manager", None)
        if rm is not None and rm.needs_drain_tanks():
            return False
        return site_checked["v"]

    async def _release_estop():
        s = get_state()
        if not site_checked["v"]:
            ui.notify("请先勾选'现场安全确认'", type="warning")
            return
        rm = getattr(s, "resource_manager", None)
        if rm is not None and rm.needs_drain_tanks():
            ui.notify("仍有待排液展缸（NEEDS_DRAIN），请先处理", type="warning")
            return
        scheduler = s.scheduler
        from core.estop import reset_estop
        reset_estop(scheduler)
        log.info("[Recovery] 用户手动解除急停")
        ui.notify("急停已解除，可重新调度样品", type="positive")
        _alert_bar.refresh()
        _release_btn_update()

    with ui.row().classes("items-center justify-end gap-4 q-mt-md"):
        release_btn = ui.button(
            "✓ 解除急停",
            on_click=_release_estop,
            icon="lock_open",
            color="red",
        ).props("size=lg")

        def _release_btn_update():
            if _can_release():
                release_btn.enable()
            else:
                release_btn.disable()

        _release_btn_update()

    return {
        "recovery_alert": _alert_bar,
        "recovery_drain": _drain_section,
    }
