"""耗材管理 Tab - ConsumableManager 可视化界面

布局：Top Action Bar + 左列（耗材架 4 层×3 板位） + 右列（暂存工位 A/B）

编号约定（v3，数字 ID）：
- 粉末收集器板 1-6 / 玻璃收集瓶板 1-6（各自独立编号）
- 内部索引：粉末 1-6 → 0-5，玻璃 1-6 → 6-11
- PLC 侧对玻璃做 +6 偏移，PC 始终发 1-6
- 板顶小灯 = `_plate_present`（由 PLC 实时 DI 驱动，仅防呆）
- 6 孔格子 = `RackSlot.has_consumable`（实验员录入账本 + 决策消耗，持久化）
- 顶部告警条：账本可用但 DI 不在位的板号列表
刷新策略：ui.timer(2.0) 周期刷新 + dialog 守卫（dialog open 期间跳过定时刷新）
"""

import logging
from datetime import datetime

from nicegui import ui

from core.consumable_manager import (
    ConsumableManager,
    ConsumableSnapshot,
    ConsumableType,
    PLATE_SENSOR_COUNT,
    PLATES_BY_TYPE,
    RackSlot,
    SlotStatus,
    StagedPlate,
    StagingId,
    _display_to_internal,
    _internal_to_display,
)
from ui.state import get_state

log = logging.getLogger(__name__)


def _format_plate_label(internal_num: int) -> str:
    """内部索引(1-12) → 面向操作员的语言：“粉1” / “玻1”。"""
    is_powder = internal_num <= 6
    ctype = ConsumableType.POWDER_COLLECTOR if is_powder else ConsumableType.GLASS_BOTTLE
    display = _internal_to_display(internal_num, ctype)
    prefix = "粉" if is_powder else "玻"
    return f"{prefix}{display}"

# 上次传感器同步时间
_last_sync: dict = {"time": None}

# dialog 守卫：dialog open 期间跳过定时刷新
_dialog_open: bool = False

# DI 变化检测：上次快照的 plate_present 状态
_last_di_snapshot: list[bool] = [False] * PLATE_SENSOR_COUNT


# ---------------------------------------------------------------------------
# 物理层定义（从顶到底渲染，模拟实际架子）
# plate_id 为显示编号 (1-6)，粉末与玻璃瓶各自独立编号
# ---------------------------------------------------------------------------

_LAYERS: list[tuple[int, list[int], str, ConsumableType]] = [
    # (层号, 显示板号列表, 类型标签, 耗材类型)
    (4, [4, 5, 6], "玻璃收集瓶", ConsumableType.GLASS_BOTTLE),   # 顶层
    (3, [1, 2, 3], "玻璃收集瓶", ConsumableType.GLASS_BOTTLE),
    (2, [4, 5, 6], "粉末收集器", ConsumableType.POWDER_COLLECTOR),
    (1, [1, 2, 3], "粉末收集器", ConsumableType.POWDER_COLLECTOR),   # 底层
]


# ---------------------------------------------------------------------------
# 刷新
# ---------------------------------------------------------------------------


def _refresh_all() -> None:
    """刷新所有 refreshable 区域（dialog open 期间跳过）。"""
    if _dialog_open:
        return
    for fn in (
        _refs.get("action_bar"),
        _refs.get("rack_section"),
        _refs.get("staging_section"),
    ):
        if fn is not None:
            fn.refresh()


_refs: dict = {}


# ---------------------------------------------------------------------------
# 操作（async handler）
# ---------------------------------------------------------------------------


async def _on_sync_di() -> None:
    """手动从 PLC 重读 12 个板级 DI（平时轮询走 ui/app.py，该按钮为调试备用）。"""
    cm: ConsumableManager | None = get_state().consumable_manager
    if cm is None:
        ui.notify("ConsumableManager 未就绪", type="warning")
        return
    plc = get_state().plc_client
    if plc is None or not getattr(plc, "is_ok", False):
        ui.notify("PLC 未连接，无法同步板级 DI", type="warning")
        return
    try:
        sensors = await plc.read_consumable_sensor()
        if not sensors or len(sensors) != PLATE_SENSOR_COUNT:
            ui.notify(
                f"IX11/IX12 解码后长度异常（期望 {PLATE_SENSOR_COUNT}，实际 {len(sensors) if sensors else 0}）",
                type="negative",
            )
            return
        await cm.sync_plate_presence(list(sensors))
        _last_sync["time"] = datetime.now()
        _refresh_all()
        ui.notify("板级 DI 已同步（IX11/IX12）", type="positive")
    except Exception as e:
        log.warning("[Consumable] 板级 DI 同步失败: %s", e)
        try:
            ui.notify(f"同步失败: {e}", type="negative")
        except RuntimeError:
            pass


async def _on_staging_place(staging_id: StagingId, plate_id: int) -> None:
    """放置板到暂存工位（全新板，6 孔全 AVAILABLE）。"""
    cm: ConsumableManager | None = get_state().consumable_manager
    if cm is None:
        return
    try:
        await cm.manual_reset_staging(staging_id, plate_id)
        _refresh_all()
        ui.notify(f"暂存 {staging_id.value} 已放置板 {plate_id}", type="positive")
    except Exception as e:
        ui.notify(f"放置失败: {e}", type="negative")


async def _on_staging_remove(staging_id: StagingId) -> None:
    """移除暂存板（设为 None）。"""
    cm: ConsumableManager | None = get_state().consumable_manager
    if cm is None:
        return
    try:
        await cm.manual_remove_staging(staging_id)
        _refresh_all()
        ui.notify(f"暂存 {staging_id.value} 已移除", type="positive")
    except Exception as e:
        ui.notify(f"移除失败: {e}", type="negative")


async def _on_plate_clear_rack(internal_num: int) -> None:
    """账本上该板整板清空（6 孔全 False）。"""
    cm: ConsumableManager | None = get_state().consumable_manager
    if cm is None:
        return
    try:
        await cm.mark_plate_emptied(internal_num)
        _refresh_all()
        ui.notify(f"板 {_format_plate_label(internal_num)} 账本已清空", type="positive")
    except Exception as e:
        ui.notify(f"清空失败: {e}", type="negative")


async def _on_plate_sync(internal_num: int) -> None:
    """装入新板（6 孔全装）。"""
    cm: ConsumableManager | None = get_state().consumable_manager
    if cm is None:
        return
    try:
        await cm.mark_plate_loaded(internal_num)
        _last_sync["time"] = datetime.now()
        _refresh_all()
        ui.notify(f"板 {_format_plate_label(internal_num)} 账本已标记装入（6 孔满）", type="positive")
    except Exception as e:
        ui.notify(f"装入失败: {e}", type="negative")


async def _on_staging_clear_filled(staging_id: StagingId) -> None:
    """清空 FILLED 装样瓶。"""
    cm: ConsumableManager | None = get_state().consumable_manager
    if cm is None:
        return
    try:
        await cm.manual_clear_filled_bottles(staging_id)
        _refresh_all()
        ui.notify(f"暂存 {staging_id.value} FILLED 已清空", type="positive")
    except Exception as e:
        ui.notify(f"清空失败: {e}", type="negative")


async def _on_clear_all_filled() -> None:
    """一键清空所有暂存工位的 FILLED 装样瓶（异常恢复用）。"""
    cm: ConsumableManager | None = get_state().consumable_manager
    if cm is None:
        ui.notify("ConsumableManager 未就绪", type="warning")
        return
    cleared = []
    for sid in (StagingId.A, StagingId.B):
        snap_plate = cm.snapshot().staging.get(sid.value)
        if snap_plate is not None and snap_plate.has_filled_bottles:
            try:
                await cm.manual_clear_filled_bottles(sid)
                cleared.append(sid.value)
            except Exception as e:
                log.warning("[Consumable] 清空 %s FILLED 失败: %s", sid.value, e)
    if cleared:
        _refresh_all()
        ui.notify(f"已清空暂存 {', '.join(cleared)} 的 FILLED", type="positive")
    else:
        ui.notify("当前无 FILLED 状态需要清空", type="info")


# ---------------------------------------------------------------------------
# 放置暂存板 Dialog
# ---------------------------------------------------------------------------


def _show_staging_place_dialog(staging_id: StagingId, ctype: ConsumableType) -> None:
    """选择板号放置到暂存工位。"""
    global _dialog_open
    _dialog_open = True

    type_label = "粉末收集器" if ctype == ConsumableType.POWDER_COLLECTOR else "玻璃收集瓶"
    valid_plates = sorted(PLATES_BY_TYPE[ctype])

    def _close_dialog(dialog) -> None:
        global _dialog_open
        _dialog_open = False
        dialog.close()

    with ui.dialog() as dialog, ui.card().classes("q-pa-md"):
        ui.label(f"放置{type_label}到暂存 {staging_id.value}").classes("text-subtitle1")
        choice = ui.radio(
            {str(p): f"板 {p}" for p in valid_plates},
            value=str(valid_plates[0]),
        ).classes("q-mt-sm")
        with ui.row().classes("gap-4 q-mt-md"):
            ui.button("取消", on_click=lambda: _close_dialog(dialog))
            ui.button(
                "放置",
                on_click=lambda: _do_place_staging(dialog, staging_id, choice),
            ).props("color=primary")
    dialog.open()


async def _do_place_staging(dialog, staging_id: StagingId, choice) -> None:
    global _dialog_open
    _dialog_open = False
    plate_id = int(choice.value)
    await _on_staging_place(staging_id, plate_id)
    dialog.close()


# ---------------------------------------------------------------------------
# 孔位 Dialog（架上）
# ---------------------------------------------------------------------------


def _show_rack_slot_dialog(
    cm: ConsumableManager, internal_num: int, slot: int, has_consumable: bool,
) -> None:
    """架上单孔位切换 dialog。"""
    global _dialog_open
    _dialog_open = True
    status_text = "有耗材" if has_consumable else "空"

    async def _apply(value: bool) -> None:
        await cm.manual_set_rack_slot(internal_num, slot, value)
        _refresh_all()

    def _close_dialog(dialog) -> None:
        global _dialog_open
        _dialog_open = False
        dialog.close()

    with ui.dialog() as dialog, ui.card().classes("q-pa-md"):
        ui.label(f"孔位 板{_format_plate_label(internal_num)}-孔{slot}（架上）  当前: {status_text}").classes(
            "text-subtitle1"
        )
        choice = ui.radio(
            {"True": "有耗材", "False": "空"},
            value=str(has_consumable),
        ).classes("q-mt-sm")
        with ui.row().classes("gap-4 q-mt-md"):
            ui.button("取消", on_click=lambda: _close_dialog(dialog))
            ui.button(
                "确认",
                on_click=lambda: _do_apply(dialog, _apply, choice),
            ).props("color=primary")
    dialog.open()


async def _do_apply(dialog, apply_fn, choice) -> None:
    """dialog 确认的通用 helper。"""
    global _dialog_open
    _dialog_open = False
    await apply_fn(choice.value == "True")
    dialog.close()


# ---------------------------------------------------------------------------
# 孔位 Dialog（暂存）
# ---------------------------------------------------------------------------


def _show_staging_slot_dialog(
    cm: ConsumableManager,
    staging_id: StagingId,
    plate_id: int,
    pos: int,
    current_status: SlotStatus,
) -> None:
    """暂存单孔位状态切换 dialog。"""
    global _dialog_open
    _dialog_open = True
    status_labels = {
        SlotStatus.AVAILABLE: "可用",
        SlotStatus.TAKEN: "已取走",
        SlotStatus.FILLED: "已装样",
    }

    async def _apply(status_str: str) -> None:
        new_status = SlotStatus[status_str]
        await cm.manual_set_staging_slot(staging_id, pos, new_status)
        _refresh_all()

    def _close_dialog(dialog) -> None:
        global _dialog_open
        _dialog_open = False
        dialog.close()

    with ui.dialog() as dialog, ui.card().classes("q-pa-md"):
        ui.label(
            f"暂存 {staging_id.value} 板 {plate_id} 孔 {pos}  "
            f"当前: {status_labels.get(current_status, current_status.name)}"
        ).classes("text-subtitle1")
        choice = ui.radio(
            {s.name: status_labels[s] for s in SlotStatus},
            value=current_status.name,
        ).classes("q-mt-sm")
        with ui.row().classes("gap-4 q-mt-md"):
            ui.button("取消", on_click=lambda: _close_dialog(dialog))
            ui.button(
                "确认",
                on_click=lambda: _do_apply_staging(dialog, _apply, choice),
            ).props("color=primary")
    dialog.open()


async def _do_apply_staging(dialog, apply_fn, choice) -> None:
    global _dialog_open
    _dialog_open = False
    await apply_fn(choice.value)
    dialog.close()


# ---------------------------------------------------------------------------
# 渲染入口
# ---------------------------------------------------------------------------


def render() -> dict:
    """渲染耗材管理 Tab。"""

    async def _periodic_refresh() -> None:
        global _last_di_snapshot
        if _dialog_open:
            return
        cm = get_state().consumable_manager
        if cm is None:
            return
        current_di = list(cm._plate_present)
        di_changed = current_di != _last_di_snapshot
        _last_di_snapshot = current_di
        ab = _refs.get("action_bar")
        if ab is not None:
            ab.refresh()
        if di_changed:
            for key in ("rack_section", "staging_section"):
                fn = _refs.get(key)
                if fn is not None:
                    fn.refresh()

    ui.timer(2.0, _periodic_refresh)

    # ── Action Bar ──
    @ui.refreshable
    def action_bar() -> None:
        cm: ConsumableManager | None = get_state().consumable_manager
        with ui.row().classes("w-full items-center gap-3 q-mb-md"):
            ui.button(
                "Sync DI",
                icon="sync",
                on_click=lambda: _on_sync_di(),
            ).props("color=primary unelevated").tooltip(
                "手动从 PLC 重读 12 个板级在位 DI（调试备用）"
            )
            ui.button(
                "清空所有 FILLED",
                icon="delete_sweep",
                on_click=lambda: _on_clear_all_filled(),
            ).props("color=orange unelevated").tooltip(
                "清空所有暂存工位的已装样瓶状态（仅用于异常恢复）"
            )
            sync_time = _last_sync.get("time")
            if sync_time:
                ui.label(f"最后同步: {sync_time.strftime('%H:%M:%S')}").classes(
                    "text-caption text-grey"
                )
            else:
                ui.label("尚未同步").classes("text-caption text-grey")
        # 一致性告警条：账本可用但 DI 不在位
        if cm is not None:
            try:
                missing = cm.detect_inconsistencies()
            except Exception:
                missing = []
            if missing:
                labels = ", ".join(
                    f"{'粉' if ct == ConsumableType.POWDER_COLLECTOR else '玻'}{n}"
                    for n, ct in missing
                )
                with ui.row().classes(
                    "w-full items-center gap-2 q-mb-md q-pa-sm"
                ).style(
                    "background-color: #FFF3E0; border-left: 4px solid #FB8C00; border-radius: 4px;"
                ):
                    ui.icon("warning", color="orange").classes("q-mr-xs")
                    ui.label(
                        f'板 {labels} 账本仍有可用孔，但 DI 显示不在位。请补放料板，或点击该板卡片菜单“整板清空”。'
                    ).classes("text-caption text-orange-9")

    # ── 左列：耗材架（4层×3板位，从顶到底）──
    @ui.refreshable
    def rack_section() -> None:
        cm: ConsumableManager | None = get_state().consumable_manager
        if cm is None:
            ui.label("ConsumableManager 未就绪").classes("text-grey")
            return

        snap = cm.snapshot()

        ui.label("耗材架").classes("text-h6 q-mb-sm")

        for layer_num, plates, type_label, ctype in _LAYERS:
            with ui.card().classes("w-full q-pa-sm q-mb-sm").style("border-left: 3px solid #90CAF9"):
                ui.label(f"第 {layer_num} 层 · {type_label}").classes(
                    "text-caption text-grey q-mb-xs"
                )
                with ui.row().classes("w-full gap-3"):
                    for display_num in plates:
                        internal = _display_to_internal(display_num, ctype)
                        _render_plate_card(cm, snap, display_num, internal, ctype, type_label)

    # ── 右列：暂存工位 ──
    @ui.refreshable
    def staging_section() -> None:
        cm: ConsumableManager | None = get_state().consumable_manager
        if cm is None:
            ui.label("ConsumableManager 未就绪").classes("text-grey")
            return

        snap = cm.snapshot()
        ui.label("暂存工位").classes("text-h6 q-mb-sm")
        _render_staging_card(cm, snap, StagingId.A, "粉末收集器", ConsumableType.POWDER_COLLECTOR)
        _render_staging_card(cm, snap, StagingId.B, "玻璃收集瓶", ConsumableType.GLASS_BOTTLE)

    # 构建布局
    action_bar()

    with ui.row().classes("w-full gap-4"):
        with ui.column().classes("flex-1"):
            rack_section()
        with ui.column().classes("w-80"):
            staging_section()

    _refs["action_bar"] = action_bar
    _refs["rack_section"] = rack_section
    _refs["staging_section"] = staging_section
    return {
        "consumable_action_bar": action_bar,
        "consumable_rack": rack_section,
        "consumable_staging": staging_section,
    }


# ---------------------------------------------------------------------------
# 架上板卡片（3行×2列网格）
# ---------------------------------------------------------------------------


def _render_plate_card(
    cm: ConsumableManager,
    snap: ConsumableSnapshot,
    display_num: int,
    internal_num: int,
    ctype: ConsumableType,
    type_label: str,
) -> None:
    """渲染耗材架上一块板的卡片。"""
    indices = ConsumableManager.plate_to_indices(internal_num)
    di_present = (
        snap.plate_present[internal_num - 1]
        if 1 <= internal_num <= len(snap.plate_present)
        else False
    )

    with ui.card().classes("q-pa-sm").style("min-width: 120px; flex: 1"):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.row().classes("items-center gap-1"):
                ui.icon(
                    "circle",
                    color="positive" if di_present else "negative",
                    size="xs",
                ).tooltip(
                    f"DI: {'在位' if di_present else '离位'}  该灯由 PLC 传感器驱动"
                )
                ui.label(f"板 {display_num}").classes("text-subtitle2 text-weight-bold")
            with ui.button(icon="more_vert").props("flat round dense size=sm"):
                with ui.menu():
                    ui.menu_item(
                        "装入新板（6 孔满）",
                        on_click=lambda _n=internal_num: _on_plate_sync(_n),
                    )
                    ui.menu_item(
                        "整板清空",
                        on_click=lambda _n=internal_num: _on_plate_clear_rack(_n),
                    )

        # 3行×2列网格
        with ui.element("div").style(
            "display: grid; grid-template-columns: repeat(2, 1fr); gap: 2px; margin-top: 4px;"
        ):
            for i, idx in enumerate(indices):
                slot: RackSlot = snap.rack[idx - 1]
                pos = i + 1
                icon = "radio_button_checked" if slot.has_consumable else "radio_button_unchecked"
                color = "primary" if slot.has_consumable else "grey"
                ui.button(
                    icon=icon,
                    on_click=lambda _n=internal_num, _p=pos, _h=slot.has_consumable: (
                        _show_rack_slot_dialog(cm, _n, _p, _h)
                    ),
                ).props(f"flat round dense size=sm color={color}").tooltip(
                    f"板{_format_plate_label(internal_num)}-孔{pos} 账本: {'可用' if slot.has_consumable else '已用/未装'}"
                )


# ---------------------------------------------------------------------------
# 暂存工位卡片（3行×2列网格 + 放置/移除控制）
# ---------------------------------------------------------------------------


def _render_staging_card(
    cm: ConsumableManager,
    snap: ConsumableSnapshot,
    staging_id: StagingId,
    type_label: str,
    ctype: ConsumableType,
) -> None:
    """渲染暂存工位卡片。"""
    staged: StagedPlate | None = snap.staging.get(staging_id.value)

    with ui.card().classes("w-full q-pa-sm q-mb-sm"):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.row().classes("items-center gap-2"):
                ui.label(f"暂存 {staging_id.value}").classes(
                    "text-subtitle2 text-weight-bold"
                )
                ui.label(f"({type_label})").classes("text-caption text-grey")
            if staged:
                ui.label(f"板 {staged.plate_id}").classes("text-caption")
                ui.badge(
                    f"余 {staged.remaining_available}",
                    color="positive" if staged.remaining_available > 0 else "grey",
                ).classes("text-xs")
            else:
                ui.badge("空", color="grey").classes("text-xs")

        if staged is None:
            # ── 空暂存工位：提供"放置板"操作 ──
            with ui.row().classes("items-center gap-2 q-mt-sm"):
                ui.label("暂无暂存板").classes("text-grey text-xs")
                ui.button(
                    "放置板",
                    icon="add_box",
                    on_click=lambda _sid=staging_id, _ct=ctype: (
                        _show_staging_place_dialog(_sid, _ct)
                    ),
                ).props("flat dense size=sm color=primary")
            return

        # FILLED 警告 + 清空按钮
        if staged.has_filled_bottles:
            with ui.row().classes("items-center gap-2 q-mt-xs"):
                ui.icon("warning", color="orange", size="sm")
                ui.label("含已装样瓶").classes("text-caption text-orange")
                ui.button(
                    "取走装样瓶",
                    icon="output",
                    on_click=lambda: _on_staging_clear_filled(staging_id),
                ).props("flat dense size=sm color=orange")

        # 3行×2列网格
        with ui.element("div").style(
            "display: grid; grid-template-columns: repeat(2, 1fr); gap: 2px; margin-top: 4px;"
        ):
            for i, status in enumerate(staged.slots):
                pos = i + 1
                if status == SlotStatus.AVAILABLE:
                    icon, color = "radio_button_checked", "positive"
                elif status == SlotStatus.TAKEN:
                    icon, color = "radio_button_unchecked", "grey"
                else:  # FILLED
                    icon, color = "trip_origin", "negative"
                ui.button(
                    icon=icon,
                    on_click=lambda _sid=staging_id, _pid=staged.plate_id, _p=pos, _st=status: (
                        _show_staging_slot_dialog(cm, _sid, _pid, _p, _st)
                    ),
                ).props(f"flat round dense size=sm color={color}").tooltip(
                    f"孔 {pos}: {status.name}"
                )

        # 操作行：更换新板 + 移除板
        with ui.row().classes("q-mt-xs gap-2"):
            ui.button(
                "更换新板",
                icon="refresh",
                on_click=lambda _sid=staging_id, _pid=staged.plate_id: _on_staging_replace(cm, _sid, _pid),
            ).props("flat dense size=sm color=primary").tooltip(
                "重置当前板为全 AVAILABLE（模拟换板）"
            )
            ui.button(
                "移除板",
                icon="remove_circle_outline",
                on_click=lambda _sid=staging_id: _on_staging_remove(_sid),
            ).props("flat dense size=sm color=negative").tooltip(
                "移除暂存板，下次 prepare 时会从料架搬新板"
            )


async def _on_staging_replace(cm: ConsumableManager, staging_id: StagingId, plate_id: int) -> None:
    """更换新板：先校验 FILLED，再重置为全 AVAILABLE。"""
    snap_plate = cm.snapshot().staging.get(staging_id.value)
    if snap_plate is not None and snap_plate.has_filled_bottles:
        ui.notify(
            f"暂存 {staging_id.value} 含已装样瓶，请先取走装样瓶",
            type="warning",
        )
        return
    try:
        await cm.manual_reset_staging(staging_id, plate_id)
        _refresh_all()
        ui.notify(f"暂存 {staging_id.value} 板 {plate_id} 已重置为全可用", type="positive")
    except Exception as e:
        ui.notify(f"重置失败: {e}", type="negative")
