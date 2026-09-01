"""Recipe 配方编辑 Tab - 加载 / 编辑 / 保存配方

功能：
  - 加载下拉：列出 recipes/ 目录下所有 .yaml
  - 按 STAGE_ORDER 显示各阶段卡片
  - 每个阶段：enabled 开关 + 参数表单（从 PARAMS_SCHEMA 渲染）
  - 保存 / 另存为按钮
"""

import logging
from pathlib import Path
from typing import Optional

from nicegui import ui

from core.recipe import RecipeStore, RecipeTemplate, StageParams, default_recipe, validate_recipe
from core.consumable_manager import ConsumableType, PLATES_BY_TYPE
from core.stages import STAGE_ORDER, STAGE_REGISTRY
from ui.state import get_state

log = logging.getLogger(__name__)

# 配方仓库路径
_RECIPES_DIR = Path(__file__).resolve().parent.parent.parent / "recipes"

# 临时配方占位符 —— 表示当前编辑的配方尚未关联到任何已保存配方
_EDITING_PLACEHOLDER = "<当前编辑>"


def render() -> dict:
    """渲染 Recipe 配方编辑 Tab。"""

    # 当前编辑的配方（内存副本） + 下拉框当前选中的配方名（保存目标的源头）
    _current_recipe: dict = {"template": None, "selected_name": None}

    @ui.refreshable
    def recipe_editor() -> None:
        recipe = _current_recipe["template"]
        if recipe is None:
            ui.label("请从上方加载或新建配方").classes("text-grey")
            return

        # 按 STAGE_ORDER 显示各阶段卡片
        for sp in recipe.stages:
            stage_cls = STAGE_REGISTRY.get(sp.name)
            schema = stage_cls.PARAMS_SCHEMA if stage_cls else {}

            with ui.card().classes("w-full q-pa-md"):
                with ui.row().classes("items-center gap-3"):
                    ui.switch(
                        sp.name, value=sp.enabled,
                        on_change=lambda e, s=sp: _toggle_enabled(s, e.value),
                    ).classes("text-weight-bold")
                    if stage_cls:
                        ui.badge(
                            f"PLC: {stage_cls.PLC_NAME}",
                            color="grey-6",
                        ).classes("text-xs")

                if sp.enabled and schema:
                    _render_params_form(sp, schema)
                elif not sp.enabled:
                    ui.label("（已禁用，启用后显示参数）").classes("text-grey text-xs q-mt-sm")
                elif not schema:
                    ui.label("（该阶段无可配置参数）").classes("text-grey text-xs q-mt-sm")

        # ── 耗材偏好（可选）──
        _render_consumable_preference(recipe)

    @ui.refreshable
    def recipe_load_bar() -> None:
        """配方加载/新建栏。"""
        store = RecipeStore(_RECIPES_DIR)
        names = store.list_names()

        # 下拉选项：临时占位符 + 实际配方列表
        options = [_EDITING_PLACEHOLDER] + names

        # 默认选中逻辑：临时状态或未加载时使用占位符，否则沿用已选中的实际配方
        cur = _current_recipe.get("selected_name")
        if cur and cur != _EDITING_PLACEHOLDER and cur in names:
            default_name = cur
        else:
            default_name = _EDITING_PLACEHOLDER
        _current_recipe["selected_name"] = default_name

        with ui.row().classes("items-center gap-3 q-mb-md flex-wrap"):
            recipe_select = ui.select(
                options=options, value=default_name,
                label="选择配方",
                on_change=lambda e: _current_recipe.__setitem__("selected_name", e.value),
            ).classes("w-56")

            ui.button(
                "加载", icon="folder_open",
                on_click=lambda: _load_recipe(recipe_select.value),
            ).props("color=primary unelevated")

            ui.button(
                "新建", icon="add",
                on_click=lambda: _new_recipe(),
            ).props("color=secondary unelevated")

    def _load_recipe(name: Optional[str]) -> None:
        if not name or name == _EDITING_PLACEHOLDER:
            ui.notify("请选择一个实际配方", type="warning")
            return
        store = RecipeStore(_RECIPES_DIR)
        try:
            _current_recipe["template"] = store.load(name)
            _current_recipe["selected_name"] = name
            get_state().current_recipe = _current_recipe["template"]
            recipe_editor.refresh()
            ui.notify(f"已加载配方: {name}", type="positive")
        except FileNotFoundError as e:
            ui.notify(str(e), type="negative")

    def _new_recipe() -> None:
        _current_recipe["template"] = default_recipe()
        _current_recipe["selected_name"] = _EDITING_PLACEHOLDER
        get_state().current_recipe = _current_recipe["template"]
        recipe_editor.refresh()
        recipe_load_bar.refresh()
        ui.notify("已创建默认配方（未保存）", type="info")

    def _toggle_enabled(sp: StageParams, value: bool) -> None:
        sp.enabled = bool(value)
        recipe_editor.refresh()

    def _save_recipe() -> None:
        recipe = _current_recipe["template"]
        if recipe is None:
            ui.notify("没有可保存的配方", type="warning")
            return
        # 保存前静态校验（与入队同一套规则）——拒绝落盘非法配方
        errors = validate_recipe(recipe)
        if errors:
            ui.notify(
                "配方校验失败，未保存：\n• " + "\n• ".join(errors),
                type="negative", multi_line=True, timeout=10000,
                close_button="关闭",
            )
            return
        # 以下拉框当前选中的名字作为保存目标
        target_name = _current_recipe.get("selected_name") or recipe.name
        # 临时配方走"另存为"流程，避免覆盖现有配方
        if target_name == _EDITING_PLACEHOLDER:
            _save_as_recipe()
            return
        if not target_name:
            ui.notify("请先在下拉框选择一个配方，或使用\u300c另存为\u300d", type="warning")
            return
        # 同步到 recipe.name，保证 RecipeStore.save 落到正确文件
        recipe.name = target_name
        store = RecipeStore(_RECIPES_DIR)
        try:
            path = store.save(recipe)
            ui.notify(f"已保存: {path}", type="positive")
            recipe_load_bar.refresh()
        except Exception as e:
            ui.notify(f"保存失败: {e}", type="negative")

    def _save_as_recipe() -> None:
        recipe = _current_recipe["template"]
        if recipe is None:
            ui.notify("没有可保存的配方", type="warning")
            return
        with ui.dialog() as dialog, ui.card():
            ui.label("另存为").classes("text-subtitle1 text-weight-bold")
            name_input = ui.input(
                "配方名称", value=recipe.name
            ).classes("w-full")
            with ui.row().classes("gap-4 q-mt-md"):
                ui.button("取消", on_click=dialog.close)
                ui.button("保存", on_click=lambda: _do_save_as(name_input.value, dialog))
        # 必须显式打开对话框，否则点击按钮无任何响应
        dialog.open()

    def _do_save_as(name: str, dialog) -> None:
        if not name.strip():
            ui.notify("名称不能为空", type="warning")
            return
        if name.strip() == _EDITING_PLACEHOLDER:
            ui.notify("不能使用保留名称", type="warning")
            return
        recipe = _current_recipe["template"]
        # 另存为前也静态校验，拒绝落盘非法配方
        errors = validate_recipe(recipe)
        if errors:
            ui.notify(
                "配方校验失败，未保存：\n• " + "\n• ".join(errors),
                type="negative", multi_line=True, timeout=10000,
                close_button="关闭",
            )
            return
        recipe.name = name.strip()
        _current_recipe["selected_name"] = recipe.name
        get_state().current_recipe = recipe
        store = RecipeStore(_RECIPES_DIR)
        try:
            path = store.save(recipe)
            dialog.close()
            ui.notify(f"已保存: {path}", type="positive")
            recipe_load_bar.refresh()
        except Exception as e:
            ui.notify(f"保存失败: {e}", type="negative")

    # 渲染
    recipe_load_bar()
    recipe_editor()

    # 保存按钮栏（静态）
    with ui.row().classes("gap-4 q-mt-md"):
        ui.button("保存", icon="save", on_click=_save_recipe).props(
            "color=positive unelevated"
        )
        ui.button("另存为…", icon="save_as", on_click=_save_as_recipe).props(
            "color=secondary unelevated"
        )

    return {"recipe_editor": recipe_editor, "recipe_load_bar": recipe_load_bar}


def _render_params_form(sp: StageParams, schema: dict) -> None:
    """根据 PARAMS_SCHEMA 渲染参数表单。"""
    # ── 特判：spotting 的 source_x/source_y 用双板可视化选择器替代两个 number ──
    if sp.name == "spotting" and "source_x" in schema and "source_y" in schema:
        from ui.components.dual_plate_picker import render_dual_plate_picker
        try:
            cur_x = int(sp.params.get("source_x", 1) or 1)
            cur_y = int(sp.params.get("source_y", 1) or 1)
        except (TypeError, ValueError):
            cur_x, cur_y = 1, 1

        def _on_well_change(nx: int, ny: int) -> None:
            sp.params["source_x"] = nx
            sp.params["source_y"] = ny  # 直接写回 StageParams，与 _save_recipe 同走 yaml 落盘

        with ui.column().classes("w-full q-mt-sm gap-1"):
            ui.label("料筒孔位（点击选择，双 24 孔板并排）").classes("text-caption text-grey")
            render_dual_plate_picker(cur_x, cur_y, _on_well_change)

        # 余下参数仍走原 grid 渲染，但跳过 source_x/source_y
        schema = {k: v for k, v in schema.items() if k not in ("source_x", "source_y")}

    with ui.grid(columns=3).classes("w-full gap-2 q-mt-sm"):
        for key, meta in schema.items():
            ptype = meta.get("type", "float")
            default = sp.params.get(key, meta.get("default"))
            label = meta.get("label", key)

            if ptype == "int":
                try:
                    init_val = float(default) if default is not None else 0.0
                except (TypeError, ValueError):
                    init_val = 0.0
                    log.warning("[Recipe] int 参数 %s 默认值无法转换: %r", key, default)
                ui.number(
                    label, value=init_val,
                    min=meta.get("min"), max=meta.get("max"),
                ).props("dense").classes("w-full").on_value_change(
                    lambda e, k=key, s=sp: _set_int_param(s, k, e.value),
                )
            elif ptype == "float":
                try:
                    init_val = float(default) if default is not None else 0.0
                except (TypeError, ValueError):
                    init_val = 0.0
                    log.warning("[Recipe] float 参数 %s 默认值无法转换: %r", key, default)
                ui.number(
                    label, value=init_val,
                    min=meta.get("min"), max=meta.get("max"),
                    format="%.2f",
                ).props("dense").classes("w-full").on_value_change(
                    lambda e, k=key, s=sp: _set_float_param(s, k, e.value),
                )
            elif ptype in ("str", "string"):
                ui.input(
                    label, value="" if default is None else str(default),
                ).props("dense").classes("w-full").on_value_change(
                    lambda e, k=key, s=sp: _set_param(s, k, e.value),
                )
            elif ptype == "select":
                options = list(meta.get("options") or [])
                init_val = default if default in options else (options[0] if options else None)
                ui.select(
                    options=options, value=init_val, label=label,
                ).props("dense").classes("w-full").on_value_change(
                    lambda e, k=key, s=sp: _set_param(s, k, e.value),
                )
            else:
                log.warning("[Recipe] 未识别的参数类型 %r（key=%s），已跳过渲染", ptype, key)


def _set_param(sp: StageParams, key: str, value) -> None:
    """更新 StageParams 中的参数值。"""
    sp.params[key] = value


def _set_int_param(sp: StageParams, key: str, value) -> None:
    """更新 int 型参数，空值或不可转换时打 warning 不崩溃。"""
    if value is None or value == "":
        return
    try:
        sp.params[key] = int(value)
    except (TypeError, ValueError):
        log.warning("[Recipe] int 参数 %s 写入失败: %r", key, value)


def _set_float_param(sp: StageParams, key: str, value) -> None:
    """更新 float 型参数，空值或不可转换时打 warning 不崩溃。"""
    if value is None or value == "":
        return
    try:
        sp.params[key] = float(value)
    except (TypeError, ValueError):
        log.warning("[Recipe] float 参数 %s 写入失败: %r", key, value)


# ---------------------------------------------------------------------------
# 耗材偏好（Phase 2 数据先行，Phase 4 接入决策）
# ---------------------------------------------------------------------------

_POWDER_PLATES = sorted(PLATES_BY_TYPE[ConsumableType.POWDER_COLLECTOR])   # 1-6
_BOTTLE_PLATES = sorted(PLATES_BY_TYPE[ConsumableType.GLASS_BOTTLE])       # 1-6
_AUTO_LABEL = "自动"


def _render_consumable_preference(recipe: RecipeTemplate) -> None:
    """渲染耗材偏好折叠区（粉末板 / 玻璃瓶板 dropdown）。"""
    pref = recipe.consumable_preference or {}

    with ui.expansion("耗材偏好（可选）", icon="inventory_2").classes("w-full q-mt-md"):
        with ui.card().classes("w-full q-pa-sm"):
            ui.label(
                "指定配方优先使用的耗材板；“自动”表示由系统按架上顺序选取"
            ).classes("text-caption text-grey q-mb-sm")

            powder_val = pref.get("powder_plate")
            bottle_val = pref.get("bottle_plate")
            powder_display = str(powder_val) if powder_val is not None else _AUTO_LABEL
            bottle_display = str(bottle_val) if bottle_val is not None else _AUTO_LABEL

            def _write_pref(key: str, val) -> None:
                if not recipe.consumable_preference:
                    recipe.consumable_preference = {}
                recipe.consumable_preference[key] = None if val == _AUTO_LABEL else int(val)

            powder_options = [_AUTO_LABEL] + [str(p) for p in _POWDER_PLATES]
            bottle_options = [_AUTO_LABEL] + [str(p) for p in _BOTTLE_PLATES]

            ui.select(
                options=powder_options,
                value=powder_display,
                label="粉末收集器板",
                on_change=lambda e: _write_pref("powder_plate", e.value),
            ).props("dense").classes("w-full")

            ui.select(
                options=bottle_options,
                value=bottle_display,
                label="玻璃收集瓶板",
                on_change=lambda e: _write_pref("bottle_plate", e.value),
            ).props("dense").classes("w-full")
