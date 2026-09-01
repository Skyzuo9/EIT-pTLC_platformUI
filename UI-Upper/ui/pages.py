"""Tab 路由管理 - 构建 Header + 6 Tab（Queue/Recipe/Flow/Vision/History/Debug）+ Recovery Tab

页面布局：
  - 固定 Header：状态栏 + 人工确认 + 重连恢复
  - 6 Tab：Queue / Recipe / Flow / Vision / History / Debug
  - 1 Tab：Recovery（急停触发时自动切换）
  - 保留原有 Logs 视图（合并到 Flow Tab 的时间轴模式）
"""

from nicegui import ui

from ui.sections import header, queue, recipe, flow, debug, vision, recovery, history, consumable


def build_page() -> dict:
    """构建主页面：固定 Header + 7 Tab（包含历史样品 + Recovery）。

    Returns:
        dict: 所有 refreshable 引用，供 timer 调用刷新。
    """
    # ── 固定 Header ──
    header_refs = header.render()

    # ── 7 Tab 页面 ──
    with ui.tabs().classes("w-full") as tabs:
        tab_queue = ui.tab("Queue", label="样品队列", icon="list")
        tab_recipe = ui.tab("Recipe", label="配方编辑", icon="science")
        tab_flow = ui.tab("Flow", label="流程可视化", icon="timeline")
        tab_vision = ui.tab("Vision", label="视觉分析", icon="visibility")
        tab_history = ui.tab("History", label="历史样品", icon="history")
        tab_consumable = ui.tab("Consumable", label="耗材管理", icon="inventory_2")
        tab_debug = ui.tab("Debug", label="变量调试", icon="bug_report")
        tab_recovery = ui.tab("Recovery", label="急停恢复", icon="health_and_safety")

    with ui.tab_panels(tabs, value=tab_queue).classes("w-full") as tab_panels:
        with ui.tab_panel(tab_queue):
            queue_refs = queue.render()
        with ui.tab_panel(tab_recipe):
            recipe_refs = recipe.render()
        with ui.tab_panel(tab_flow):
            flow_refs = flow.render()
        with ui.tab_panel(tab_vision):
            vision_refs = vision.render()
        with ui.tab_panel(tab_history):
            history_refs = history.render()
        with ui.tab_panel(tab_consumable):
            consumable_refs = consumable.render()
        with ui.tab_panel(tab_debug):
            debug_refs = debug.render()
        with ui.tab_panel(tab_recovery):
            recovery_refs = recovery.render()

    # 合并所有 refreshable 引用
    refs = {}
    refs.update(header_refs or {})
    refs.update(queue_refs or {})
    refs.update(recipe_refs or {})
    refs.update(flow_refs or {})
    refs.update(vision_refs or {})
    refs.update(history_refs or {})
    refs.update(consumable_refs or {})
    refs.update(debug_refs or {})
    refs.update(recovery_refs or {})
    # 将 tab_panels 和 tab_recovery 保存为引用，供急停切换使用
    refs["_tab_panels"] = tab_panels
    refs["_tab_recovery"] = tab_recovery
    # Vision Tab 引用，供乒乓等待时 badge 提示
    refs["_tab_vision"] = tab_vision
    refs["_tab_consumable"] = tab_consumable
    return refs
