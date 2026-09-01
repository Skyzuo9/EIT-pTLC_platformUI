"""Debug 变量调试 Tab - PLC 变量实时表 + 工位调试

功能：
  - 变量实时表：显示 VariableMonitor snapshot 中所有变量值
  - 变量快捷操作：读取/Toggle/写入任意 PLC 变量
  - 工位调试：启动 collect/develop/spotting/before_photo/scrape Stage
  - 工位级调试辅助：PLC_EStop 置位/复位
  - 审计：JOG_START / JOG_DONE / JOG_FAIL
"""

import asyncio
import json
import logging
import time
from dataclasses import replace as dc_replace
from datetime import datetime
from pathlib import Path
from typing import Optional

from nicegui import ui

from core.cnc_path_generator import generate_scrape_arrays, safe_placeholder_arrays
from core.config import GCodeCfg
from core.plc_client import NODE_TYPES
from core.stages.before_photo import BeforePhotoStage
from core.stages.collect import CollectStage
from core.stages.develop import DevelopStage
from core.stages.scrape import ScrapeStage
from core.stages.spotting import SpottingStage
from ui.state import get_state

log = logging.getLogger(__name__)


def render() -> dict:
    """渲染 Debug 变量调试 Tab。"""

    _executing = {"flag": False, "start": 0.0}
    _notification_queue: list[tuple[str, str]] = []  # (message, type) 通用通知队列
    _scan_result_queue: list[tuple[str, str]] = []  # (message, type) 扫描结果队列

    def _safe_notify(message: str, ntype: str = "info") -> None:
        """安全地在后台任务中排队通知，由 UI timer 在主线程消费并显示。"""
        _notification_queue.append((message, ntype))

    # ──────────────────────────────────────────────────────────────
    # 变量实时表 + 扫描按钮
    # ──────────────────────────────────────────────────────────────

    async def _do_scan_plc_nodes() -> None:
        """扫描 PLC 对象下所有变量节点，缓存到 _dynamic_nodes 供轮询读取。"""
        state = get_state()
        plc = state.plc_client
        if plc is None:
            _safe_notify("PLC 未连接", "negative")
            return
        try:
            # 1. 浏览 PLC 节点（副作用：缓存到 _dynamic_nodes/_dynamic_types）
            discovered = await plc.browse_plc_nodes()
            if not discovered:
                _scan_result_queue.append(("未发现任何变量", "warning"))
                return

            # 2. 找出新变量（不在当前 snapshot 中的）
            new_vars = [name for name in discovered if name not in state.variable_snapshot]

            # 3. 手动读取新变量值到 snapshot（后续由 _poll_loop 自动刷新）
            for name in new_vars:
                try:
                    val = await plc.read_variable(name)
                    state.variable_snapshot[name] = val
                except Exception:
                    pass

            # 4. 排队 UI 更新（由 _update_ui_state timer 在主线程消费）
            total = len(discovered)
            new_count = len(new_vars)
            _scan_result_queue.append((f"发现 {total} 个变量（新增 {new_count} 个）", "positive"))
            _safe_notify(f"扫描完成：{total} 个变量，{new_count} 个新增", "positive")
            state.log_store.append(
                "DEBUG", "SCAN_PLC",
                f"total={total} new={new_count}",
            )
        except Exception as e:
            _scan_result_queue.append((f"扫描失败: {e}", "negative"))
            _safe_notify(f"扫描失败: {e}", "negative")

    with ui.row().classes("items-center gap-3 q-mb-sm"):
        scan_btn = ui.button(
            "扫描 PLC 变量",
            icon="search",
            on_click=lambda: asyncio.create_task(_do_scan_plc_nodes()),
        ).props("dense color=primary unelevated")
        scan_result_label = ui.label("点击按钮发现 PLC 端所有可用变量").classes(
            "text-caption text-grey"
        )

    # ── 变量实时表（就地更新 rows，不销毁重建 DOM） ──
    _var_table_columns = [
        {"name": "var", "label": "变量名", "field": "var", "align": "left"},
        {"name": "val", "label": "当前值", "field": "val", "align": "left"},
        {"name": "type", "label": "类型", "field": "type", "align": "left"},
        {"name": "time", "label": "更新时间", "field": "time", "align": "left"},
    ]

    with ui.card().classes("w-full q-pa-md"):
        ui.label("PLC 变量实时快照").classes(
            "text-subtitle1 text-weight-bold q-mb-sm"
        )
        _var_empty_label = ui.label(
            '暂无数据（PLC 未连接或 VariableMonitor 未启动，可点击上方"扫描 PLC 变量"）'
        ).classes("text-grey")
        scan_table = ui.table(
            columns=_var_table_columns, rows=[], row_key="var",
        ).classes("w-full").props("dense flat bordered")
        _var_empty_label.visible = True
        scan_table.visible = False
        # 点击行：回填变量名+类型到下方「BOOL 变量状态刷新测试」区
        scan_table.on(
            "rowClick",
            lambda e: _fill_from_scan(e.args[1])
            if isinstance(e.args, list) and len(e.args) > 1 else None,
        )

    _last_var_snapshot_hash: list[int] = [0]  # 脏检查缓存

    def _update_variable_table(force: bool = False) -> None:
        """就地更新变量表 rows（不销毁 DOM，保持滚动位置和选中状态）。

        使用脏检查：仅在 snapshot 内容变化时才更新 rows，
        避免不必要的 DOM 操作影响用户交互。
        """
        state = get_state()
        snapshot = state.variable_snapshot

        # 脏检查：计算 snapshot 当前哈希（基于变量名+值），与缓存对比
        snap_hash = hash(tuple(sorted(
            (k, str(v)) for k, v in snapshot.items()
        )))
        if not force and snap_hash == _last_var_snapshot_hash[0]:
            return
        _last_var_snapshot_hash[0] = snap_hash

        if not snapshot:
            _var_empty_label.visible = True
            scan_table.visible = False
            return

        _var_empty_label.visible = False
        scan_table.visible = True

        # 有序遍历：已知变量（NODE_TYPES 顺序）→ 动态变量
        known_vars = [v for v in NODE_TYPES if v in snapshot]
        dynamic_vars = [v for v in snapshot if v not in NODE_TYPES]

        # 获取类型映射（合并 NODE_TYPES + _dynamic_types）
        plc = state.plc_client
        type_map = plc.get_all_variable_types() if plc else {}

        rows = []
        for var_name in known_vars + dynamic_vars:
            val = snapshot.get(var_name, "—")
            type_str = type_map.get(var_name, "?")
            rows.append({
                "var": var_name,
                "val": str(val),
                "type": type_str,
                "time": datetime.now().strftime("%H:%M:%S") if var_name in snapshot else "—",
            })

        scan_table.rows = rows

    # ──────────────────────────────────────────────────────────────
    # 变量快捷操作区
    # ──────────────────────────────────────────────────────────────

    with ui.card().classes("w-full q-pa-md"):
        ui.label("变量快捷操作").classes(
            "text-subtitle1 text-weight-bold q-mb-sm"
        )
        ui.label(
            "选择变量后读取/置位/Toggle；仅限 Mock 或调试环境。"
        ).classes("text-caption text-grey q-mb-sm")

        with ui.row().classes("items-center gap-3 q-mt-sm"):
            test_bool_read_btn = ui.button(
                "读取 Test_BOOL", icon="visibility",
                on_click=lambda: asyncio.create_task(_async_read_test_bool()),
            ).props("dense")
            test_bool_toggle_btn = ui.button(
                "Toggle Test_BOOL", icon="swap_horiz",
                on_click=lambda: _confirm_toggle_custom_var(),
            ).props("dense color=warning")
        test_bool_status_label = ui.label("").classes("text-caption q-mt-xs")

        async def _async_read_test_bool() -> None:
            state = get_state()
            plc = state.plc_client
            if plc is None:
                test_bool_status_label.text = "PLC 未就绪"
                test_bool_status_label.classes("text-negative", remove="text-positive text-warning")
                return
            try:
                val = await plc.read_variable("Test_BOOL")
                test_bool_status_label.text = f"Test_BOOL = {val}"
                test_bool_status_label.classes("text-positive", remove="text-negative text-warning")
            except Exception as e:
                test_bool_status_label.text = f"读取失败: {e}"
                test_bool_status_label.classes("text-negative", remove="text-positive text-warning")

    # ──────────────────────────────────────────────────────────────
    # PLC 状态置位区（调试专用，Mock/实机兼容）
    # ──────────────────────────────────────────────────────────────

    def _is_mock_env() -> bool:
        url = get_state().plc_url.lower()
        return "localhost" in url or "127.0.0.1" in url

    _override_enabled = {"flag": False}

    with ui.card().classes("w-full q-pa-md"):
        ui.label("工位级调试辅助（仅限 Mock/调试环境）").classes(
            "text-subtitle1 text-weight-bold q-mb-sm"
        )
        ui.label(
            "置位/复位工位级状态变量（如 PLC_EStop、工位 Reset 等）。"
            "旧全局变量 PLC_Busy/PLC_Done/PLC_Error 已在 Phase C 中删除。"
        ).classes("text-caption text-grey q-mb-sm")

        is_mock = _is_mock_env()

        # 环境提示
        env_label = ui.label("")
        env_label.classes("text-caption q-mb-sm")
        if is_mock:
            env_label.text = "Mock 环境已检测，置位功能已解锁"
            env_label.classes("text-positive", remove="text-negative text-warning")
        else:
            env_label.text = "已连接至非本地 PLC，请确认处于调试环境后再操作"
            env_label.classes("text-negative", remove="text-positive text-warning")

        if not is_mock:
            ui.checkbox(
                "我确认当前处于调试/测试环境，允许手动置位 PLC 状态变量",
                value=False,
                on_change=lambda e: _override_enabled.update(flag=e.value),
            ).classes("q-mb-sm")

        # E-Stop 控制（保留，这是唯一的全局调试状态）
        with ui.row().classes("items-center gap-2 q-mb-xs"):
            ui.label("PLC_EStop").classes("text-body2")
            estop_true_btn = ui.button(
                "置 True", on_click=lambda: asyncio.create_task(_async_set_var("PLC_EStop", True)),
            ).props("dense color=red")
            estop_false_btn = ui.button(
                "置 False", on_click=lambda: asyncio.create_task(_async_set_var("PLC_EStop", False)),
            ).props("dense")

    _estop_ctrl_buttons = [estop_true_btn, estop_false_btn]

    # ── 一键清零 PLC 变量 ──
    with ui.card().classes("w-full q-pa-md q-mt-sm"):
        ui.label("一键清零 PLC 变量").classes(
            "text-subtitle1 text-weight-bold q-mb-sm"
        )
        ui.label(
            "批量重置所有由 PC 端在自动化流程中写入 PLC 的变量："
            "工位 Enable、展缸排液、工艺参数、CNC 数组、耗材动作码等。"
            "不包含 PLC_EStop（安全变量）和 PLC→PC 传感器信号。"
        ).classes("text-caption text-grey q-mb-sm")

        with ui.row().classes("items-center gap-3"):
            reset_all_btn = ui.button(
                "一键清零", icon="restart_alt",
                on_click=lambda: _confirm_reset_all_plc_vars(),
            ).props("dense color=red unelevated")
            reset_all_status_label = ui.label("").classes("text-caption")

    # ──────────────────────────────────────────────────────────────
    # BOOL 变量状态刷新测试区（方案B：支持自定义变量名）
    # ──────────────────────────────────────────────────────────────

    # ────────────────────────────────────────────────────
    # 工位电平范式调试（collect / develop；契约 docs/PLC_Unified_Stage_Protocol.md v1.2）
    # ────────────────────────────────────────────────────

    with ui.card().classes("w-full q-pa-md"):
        ui.label("工位调试：启动 collect（电平范式）").classes(
            "text-subtitle1 text-weight-bold q-mb-sm"
        )
        ui.label(
            "与 Scheduler 同走 CollectStage.execute() 路径；"
            "PLC 自治推进子步 0→10→20→30→0(+Done)。"
        ).classes("text-caption text-grey q-mb-sm")

        with ui.row().classes("items-center gap-3 flex-wrap"):
            collect_volume_input = ui.number(
                label="溶剂体积(mL)", value=2.0, min=0.0, max=25.0, step=0.1,
            ).classes("w-40").props("dense outlined")
            collect_channel_input = ui.number(
                label="溶剂通道号", value=1, min=1, max=4, step=1,
            ).classes("w-32").props("dense outlined")
            collect_repeat_input = ui.number(
                label="重复打液次数", value=1, min=1, max=20, step=1,
            ).classes("w-36").props("dense outlined")

        with ui.row().classes("items-center gap-3 q-mt-sm"):
            start_collect_btn = ui.button(
                "启动 collect", icon="play_arrow",
                on_click=lambda: asyncio.create_task(_do_start_collect()),
            ).props("color=warning unelevated")
            reset_collect_btn = ui.button(
                "Reset collect", icon="restart_alt",
                on_click=lambda: asyncio.create_task(_do_reset_collect()),
            ).props("dense")
        collect_status_label = ui.label("").classes("text-caption q-mt-xs")

    # ── develop 工位调试区 ──
    with ui.card().classes("w-full q-pa-md q-mt-sm"):
        ui.label("工位调试：启动 develop / 展开（电平范式 v1.3）").classes(
            "text-subtitle1 text-weight-bold q-mb-sm"
        )
        ui.label(
            "协议 v1.3：prep → 展开等待 → 排液 → 释放；Step 35 乒乓握手已废弃。"
        ).classes("text-caption text-grey q-mb-sm")

        with ui.row().classes("items-center gap-3 flex-wrap"):
            develop_mode_select = ui.select(
                label="润洗模式",
                options={"cylinder": "润洗缸", "line": "清洗管路"},
                value="cylinder",
            ).classes("w-36").props("dense outlined")
            develop_tank_input = ui.number(
                label="目标缸号(1-8)", value=1, min=1, max=8, step=1,
            ).classes("w-36").props("dense outlined")
            develop_duration_input = ui.number(
                label="展开时间(min)", value=0.2, min=0.1, max=120.0, step=0.1,
            ).classes("w-36").props("dense outlined")

        with ui.row().classes("items-center gap-3 flex-wrap q-mt-xs"):
            develop_volume_input = ui.number(
                label="展开剂总体积(mL)", value=2.0, min=0.0, max=25.0, step=0.1,
            ).classes("w-44").props("dense outlined")

        with ui.row().classes("items-center gap-2 flex-wrap q-mt-xs"):
            ui.label("溶剂比例").classes("text-body2 text-weight-medium q-mr-xs")
            develop_ratio_inputs = {}
            for _ch in range(1, 6):
                develop_ratio_inputs[_ch] = ui.number(
                    label=f"Ch{_ch}", value=0.0, min=0.0, max=100.0, step=0.1,
                ).classes("w-20").props("dense outlined")

        with ui.row().classes("items-center gap-3 q-mt-sm"):
            start_develop_btn = ui.button(
                "启动 develop", icon="play_arrow",
                on_click=lambda: asyncio.create_task(_do_start_develop()),
            ).props("color=warning unelevated")
            reset_develop_btn = ui.button(
                "Reset develop", icon="restart_alt",
                on_click=lambda: asyncio.create_task(_do_reset_develop()),
            ).props("dense")
            drain_btn = ui.button(
                "触发排液", icon="water_drop",
                on_click=lambda: asyncio.create_task(_do_trigger_drain()),
            ).props("dense color=blue-8 unelevated")
        develop_status_label = ui.label("").classes("text-caption q-mt-xs")

    # ── spotting（上样点样）工位调试区 ──
    with ui.card().classes("w-full q-pa-md q-mt-sm"):
        ui.label("工位调试：启动 spotting / 上样点样（电平范式 v1.4 / v2 空气驱动策略）").classes(
            "text-subtitle1 text-weight-bold q-mb-sm"
        )
        ui.label(
            "v2 空气驱动策略：清洗 → 上样准备(回抽空气/吸样品/排废/驱动空气) → 放硅胶板 → 吸液 → 点样；"
            "PLC 自治推进子步 0→10→20→30→40→50→0(+Done)。"
        ).classes("text-caption text-grey q-mb-sm")

        with ui.row().classes("items-center gap-3 flex-wrap"):
            spotting_sample_vol = ui.number(
                label="样品体积(mL)", value=5.0, min=0.1, max=12.0, step=0.1,
            ).classes("w-36").props("dense outlined")
            spotting_air_buffer = ui.number(
                label="空气隔离段(mL)", value=3.0, min=0.1, max=10.0, step=0.1,
            ).classes("w-32").props("dense outlined")
            spotting_wash_vol = ui.number(
                label="单次清洗体积(mL)", value=25.0, min=0.1, max=25.0, step=0.1,
            ).classes("w-36").props("dense outlined")

        with ui.row().classes("items-center gap-3 flex-wrap q-mt-xs"):
            # 孔位坐标改为双板可视化选择器（与 Recipe Tab 体验一致）
            spotting_well: dict = {"x": 1, "y": 1}
            with ui.column().classes("gap-1"):
                ui.label("料筒孔位（点击选择，双 24 孔板并排）").classes("text-caption text-grey")
                from ui.components.dual_plate_picker import render_dual_plate_picker
                render_dual_plate_picker(
                    spotting_well["x"], spotting_well["y"],
                    on_change=lambda nx, ny: spotting_well.update(x=nx, y=ny),
                )
            spotting_clean_count = ui.number(
                label="清洗次数", value=3, min=1, max=20, step=1,
            ).classes("w-28").props("dense outlined")

        with ui.row().classes("items-center gap-3 q-mt-sm"):
            start_spotting_btn = ui.button(
                "启动 spotting", icon="play_arrow",
                on_click=lambda: asyncio.create_task(_do_start_spotting()),
            ).props("color=warning unelevated")
            reset_spotting_btn = ui.button(
                "Reset spotting", icon="restart_alt",
                on_click=lambda: asyncio.create_task(_do_reset_spotting()),
            ).props("dense")
        spotting_status_label = ui.label("").classes("text-caption q-mt-xs")

    # ── before_photo / scrape 拍照刮板调试区（电平范式 v1.6） ──
    with ui.card().classes("w-full q-pa-md q-mt-sm"):
        ui.label("工位调试：before_photo / scrape 拍照刮板（电平范式 v1.6）").classes(
            "text-subtitle1 text-weight-bold q-mb-sm"
        )
        ui.label(
            "协议 v1.6：PhotoMode=1 → Step 15(点样后拍照) / PhotoMode=0 → Step 20(展开后拍照+刮取)；"
            "BeforePhotoStage 与 ScrapeStage 共享 _scrape_lock 确保硬件互斥。"
        ).classes("text-caption text-grey q-mb-sm")

        # 实时状态徽章
        with ui.row().classes("items-center gap-3 q-mb-sm"):
            scrape_photomode_badge = ui.badge("PhotoMode: —", color="grey")
            scrape_step_badge = ui.badge("scrape_Step: —", color="grey")
            scrape_lock_badge = ui.badge("_scrape_lock: 空闲", color="green")

        with ui.row().classes("items-center gap-3 q-mt-sm"):
            start_before_photo_btn = ui.button(
                "启动 before_photo", icon="photo_camera",
                on_click=lambda: asyncio.create_task(_do_start_before_photo()),
            ).props("color=warning unelevated")
            start_scrape_btn = ui.button(
                "启动 scrape", icon="content_cut",
                on_click=lambda: asyncio.create_task(_do_start_scrape()),
            ).props("color=warning unelevated")
            reset_scrape_btn = ui.button(
                "Reset scrape", icon="restart_alt",
                on_click=lambda: asyncio.create_task(_do_reset_scrape()),
            ).props("dense")
        scrape_status_label = ui.label("").classes("text-caption q-mt-xs")

    # ── CNC 刮取测试折叠面板（端到端验证：写 ScrapeCNC + scrape FSM 完整时序） ──
    with ui.card().classes("w-full q-pa-md q-mt-sm"):
        with ui.expansion("CNC 刮取测试", icon="precision_manufacturing").classes("w-full"):
            ui.label(
                "复用真实 sample 的 summary.json 生成 200 点坐标，batch 写 12 个 ScrapeCNC "
                "变量后触发 scrape FSM。Scheduler 运行时禁用以避免 FSM 抢占。"
            ).classes("text-caption text-grey q-mb-sm")

            with ui.row().classes("items-center gap-3 q-mb-sm"):
                cnc_sample_select = ui.select(
                    options=[], label="样品",
                ).classes("w-40").props("dense outlined")
                cnc_band_select = ui.select(
                    options=[], label="Band",
                ).classes("w-44").props("dense outlined")
                cnc_passes_input = ui.number(
                    label="passes", value=3, min=1, max=10, step=1,
                ).classes("w-28").props("dense outlined")
                cnc_total_depth_input = ui.number(
                    label="total_depth (mm)", value=1.0, min=0.0, step=0.1, format="%.2f",
                ).classes("w-36").props("dense outlined")

            with ui.row().classes("items-center gap-3 q-mb-sm"):
                cnc_feed_rate_input = ui.number(
                    label="feed_rate (mm/min)", value=800, min=1, max=5000, step=10,
                ).classes("w-40").props("dense outlined")
                cnc_plunge_rate_input = ui.number(
                    label="plunge_rate (mm/min)", value=200, min=1, max=2000, step=10,
                ).classes("w-40").props("dense outlined")
                # 路径策略运行时覆盖：(default) 走 gcode_cfg.path_strategy，
                # 其余选项 → state.cnc_path_strategy_override + generate_scrape_arrays(strategy=...)
                cnc_strategy_select = ui.select(
                    options=["(default)", "zigzag", "boustrophedon", "contour"],
                    value="(default)",
                    label="path_strategy",
                ).classes("w-44").props("dense outlined")
                # contour 策略下生效：每列保留比例覆盖（0,1]
                cnc_keep_ratio_input = ui.number(
                    label="keep_ratio (contour)", value=1.0,
                    min=0.05, max=1.0, step=0.05, format="%.2f",
                ).classes("w-40").props("dense outlined")

            with ui.row().classes("items-center gap-3"):
                cnc_send_btn = ui.button(
                    "发送点位数据", icon="upload",
                    on_click=lambda: asyncio.create_task(_do_cnc_send()),
                ).props("dense color=primary unelevated")
                cnc_run_btn = ui.button(
                    "触发 CNC 执行", icon="play_arrow",
                    on_click=lambda: asyncio.create_task(_do_cnc_run()),
                ).props("color=warning unelevated")
                cnc_safe_btn = ui.button(
                    "安全占位", icon="shield",
                    on_click=lambda: asyncio.create_task(_do_cnc_safe()),
                ).props("dense")
            cnc_status_label = ui.label("").classes("text-caption q-mt-xs")

    # ── CNC 测试辅助函数 ──
    def _cnc_summary_path(sample_id: str) -> Optional[Path]:
        state = get_state()
        if state.sample_store is not None:
            try:
                p = state.sample_store.get_summary_path(sample_id)
                if p is not None and p.is_file():
                    return p
            except Exception:
                pass
        # 回退：data/samples/<id>/analysis/<id>/summary.json
        candidate = Path("data") / "samples" / sample_id / "analysis" / sample_id / "summary.json"
        return candidate if candidate.is_file() else None

    def _cnc_load_bands(sample_id: str) -> list[str]:
        sp = _cnc_summary_path(sample_id)
        if sp is None:
            return []
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            return [b.get("band_id", "") for b in data.get("bands", []) if b.get("band_id")]
        except (OSError, json.JSONDecodeError):
            return []

    def _cnc_refresh_samples() -> None:
        """从 SampleStore 拉取含分析结果的样品列表，刷新下拉框。"""
        state = get_state()
        if state.sample_store is None:
            cnc_sample_select.options = []
            cnc_sample_select.update()
            return
        try:
            samples = [
                s for s in state.sample_store.list_samples()
                if state.sample_store.has_analysis(s)
            ]
        except Exception:
            samples = []
        cnc_sample_select.options = samples
        if samples and cnc_sample_select.value not in samples:
            cnc_sample_select.value = samples[0]
        cnc_sample_select.update()
        _cnc_refresh_bands()

    def _cnc_refresh_bands() -> None:
        sid = cnc_sample_select.value
        bands = _cnc_load_bands(sid) if sid else []
        cnc_band_select.options = bands
        # 优先选第一条非 origin 的 band
        default_band = next((b for b in bands if not b.endswith("_origin")), bands[0] if bands else None)
        if default_band and cnc_band_select.value not in bands:
            cnc_band_select.value = default_band
        cnc_band_select.update()

    cnc_sample_select.on_value_change(lambda e: _cnc_refresh_bands())

    def _cnc_block_reason() -> str:
        """完整互锁检查（用于 _do_cnc_run：触发 FSM 上升沿，需要完全互斥）。"""
        state = get_state()
        if state.plc_client is None or state.plc_state != "connected":
            return "PLC 未连接"
        if getattr(state, "scheduler_running", False):
            return "Scheduler 运行中，禁止触发 CNC 执行"
        if state.active_sample_ids:
            return f"有样品在跑: {', '.join(sorted(state.active_sample_ids))}"
        # 同 PLC 硬件 FSM 不可有两条互不感知的控制路径：
        # ScrapeStage / BeforePhotoStage 共享 _scrape_lock，CNC 直驱也必须尊重该锁。
        if ScrapeStage._scrape_lock.locked():
            return "_scrape_lock 已被 scrape/before_photo 占用，禁止 CNC 测试"
        return ""

    def _cnc_send_block_reason() -> str:
        """轻量互锁检查（用于 _do_cnc_send / _do_cnc_safe：仅写 PLC 变量，不触发 FSM）。

        仅检查 PLC 连接 + _scrape_lock（防止写入被正在运行的 ScrapeStage 覆盖）。
        不检查 scheduler_running / active_sample_ids：仅写变量不触发 FSM 上升沿。
        """
        state = get_state()
        if state.plc_client is None or state.plc_state != "connected":
            return "PLC 未连接"
        if ScrapeStage._scrape_lock.locked():
            return "_scrape_lock 已被占用，PLC 变量可能被正在运行的工位覆盖"
        return ""

    def _cnc_build_gcode_cfg() -> GCodeCfg:
        # 以 state.gcode_cfg（config.yaml 注入的真机标定参数）为基础，
        # 覆盖 Debug Tab 表单中可编辑的工艺参数（passes / depth / feed / plunge）
        state_cfg = getattr(get_state(), "gcode_cfg", None) or GCodeCfg()
        cfg = state_cfg
        try:
            n = int(cnc_passes_input.value) if cnc_passes_input.value else cfg.scrape.num_passes
        except (TypeError, ValueError):
            n = cfg.scrape.num_passes
        try:
            td = float(cnc_total_depth_input.value) if cnc_total_depth_input.value else cfg.scrape.total_depth_mm
        except (TypeError, ValueError):
            td = cfg.scrape.total_depth_mm
        try:
            fr = int(cnc_feed_rate_input.value) if cnc_feed_rate_input.value else cfg.scrape.feed_rate
        except (TypeError, ValueError):
            fr = cfg.scrape.feed_rate
        try:
            pr = int(cnc_plunge_rate_input.value) if cnc_plunge_rate_input.value else cfg.scrape.plunge_rate
        except (TypeError, ValueError):
            pr = cfg.scrape.plunge_rate
        scrape = dc_replace(
            cfg.scrape,
            num_passes=max(1, n), total_depth_mm=td,
            feed_rate=max(1, fr), plunge_rate=max(1, pr),
        )
        return dc_replace(cfg, scrape=scrape)

    def _cnc_strategy_override() -> Optional[str]:
        """读下拉框当前选择 + 同步到 state；(default) 返回 None（走 gcode_cfg 默认值）。"""
        v = cnc_strategy_select.value
        override = None if (not v or v == "(default)") else str(v).strip().lower()
        try:
            get_state().cnc_path_strategy_override = override
        except AttributeError:
            pass
        return override

    def _cnc_keep_ratio_override() -> Optional[float]:
        """读 keep_ratio 输入框。仅 contour 策略生效；越界/不合法返回 None 走 gcode_cfg.scrape_keep_ratio。"""
        v = cnc_keep_ratio_input.value
        try:
            k = float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
        if k is None or not (0.0 < k <= 1.0):
            return None
        return k

    async def _do_cnc_send() -> None:
        """按当前选择生成点位数组并 batch 写入 11 个 ScrapeCNC 变量（不触发 FSM）。

        g_pass_z 不下发——由 PLC Step 30 内部计算。
        使用轻量互锁（_cnc_send_block_reason）：允许 Scheduler 运行期间写入参数。
        """
        block = _cnc_send_block_reason()
        if block:
            _safe_notify(block, "warning")
            cnc_status_label.text = block
            return
        sid = cnc_sample_select.value
        bid = cnc_band_select.value
        if not sid or not bid:
            _safe_notify("请先选择样品与 band", "warning")
            return
        sp = _cnc_summary_path(sid)
        if sp is None:
            _safe_notify(f"summary.json 不存在: {sid}", "negative")
            return
        try:
            arrays = generate_scrape_arrays(
                sp, bid, _cnc_build_gcode_cfg(),
                strategy=_cnc_strategy_override(),
                keep_ratio=_cnc_keep_ratio_override(),
            )
        except (FileNotFoundError, KeyError, ValueError) as e:
            _safe_notify(f"点位生成失败: {e}", "negative")
            cnc_status_label.text = f"生成失败: {e}"
            return
        plc = get_state().plc_client
        try:
            await plc.send_recipe_params(arrays.as_plc_dict())
        except Exception as e:
            _safe_notify(f"OPC UA 写入失败: {e}", "negative")
            cnc_status_label.text = f"写入失败: {e}"
            return
        keep_msg = f" keep={_cnc_keep_ratio_override():.2f}" if _cnc_keep_ratio_override() is not None else ""
        msg = f"已写入 sample={sid} band={bid} pass_count={arrays.g_pass_count} strategy={_cnc_strategy_override() or 'default'}{keep_msg}"
        cnc_status_label.text = msg
        cnc_status_label.classes("text-positive", remove="text-negative text-grey")
        _safe_notify(msg, "positive")
        get_state().log_store.append("DEBUG", "CNC_SEND", msg)

    async def _do_cnc_safe() -> None:
        """下发安全占位（g_pass_count=0），验证 PLC 端跳过 SMC pipeline 短路逻辑。

        使用轻量互锁（_cnc_send_block_reason）：允许 Scheduler 运行期间写入参数。
        """
        block = _cnc_send_block_reason()
        if block:
            _safe_notify(block, "warning")
            cnc_status_label.text = block
            return
        arrays = safe_placeholder_arrays(_cnc_build_gcode_cfg())
        plc = get_state().plc_client
        try:
            await plc.send_recipe_params(arrays.as_plc_dict())
        except Exception as e:
            _safe_notify(f"OPC UA 写入失败: {e}", "negative")
            cnc_status_label.text = f"写入失败: {e}"
            return
        msg = "已写入安全占位（g_pass_count=0，全 0 数组）"
        cnc_status_label.text = msg
        cnc_status_label.classes("text-positive", remove="text-negative text-grey")
        _safe_notify(msg, "positive")
        get_state().log_store.append("DEBUG", "CNC_SAFE_PLACEHOLDER", msg)

    async def _do_cnc_run() -> None:
        """端到端时序：start_stage → await_step(15) → confirm → await_done。

        前置条件：调用方已调用 _do_cnc_send 或 _do_cnc_safe 写入参数。
        Step 15 为唯一乒乓点（A10 FB 内部等 Confirm），Confirm 后 PLC 自动走 20(CNC)→30(机器人)→Done。
        """
        block = _cnc_block_reason()
        if block:
            _safe_notify(block, "warning")
            cnc_status_label.text = block
            return
        plc = get_state().plc_client
        cnc_status_label.text = "启动 scrape FSM..."
        cnc_status_label.classes("text-grey", remove="text-positive text-negative")
        try:
            await plc.start_stage("scrape")
            # Step 15: 唯一乒乓点（A10 FB 内部等 Confirm）
            cnc_status_label.text = "等待 Step=15（A10 拍照+乒乓）..."
            await plc.await_stage_step("scrape", 15, timeout=120.0)
            cnc_status_label.text = "写 Confirm → PLC 进入 CNC 流程..."
            await plc.confirm_stage("scrape")
            await plc.await_stage_done("scrape", timeout=600.0)
        except (RuntimeError, TimeoutError) as e:
            cnc_status_label.text = f"CNC 执行失败: {e}"
            cnc_status_label.classes("text-negative", remove="text-positive text-grey")
            _safe_notify(f"CNC 执行失败: {e}", "negative")
            get_state().log_store.append("DEBUG", "CNC_RUN_FAIL", str(e))
            return
        except Exception as e:
            # 兜底捕获 OPC UA / 连接类异常，避免 create_task 静默吞噬
            cnc_status_label.text = f"CNC 执行异常: {e}"
            cnc_status_label.classes("text-negative", remove="text-positive text-grey")
            _safe_notify(f"CNC 执行异常: {e}", "negative")
            get_state().log_store.append("DEBUG", "CNC_RUN_FAIL", f"unexpected: {e}")
            return
        cnc_status_label.text = "CNC 端到端测试通过 ✓"
        cnc_status_label.classes("text-positive", remove="text-negative text-grey")
        _safe_notify("CNC 端到端测试通过", "positive")
        get_state().log_store.append("DEBUG", "CNC_RUN_OK", "end-to-end pass")

    # 首次渲染时填充样品下拉（延迟到 SampleStore 就绪后再刷一次也可由 timer 完成）
    _cnc_refresh_samples()

    async def _do_start_collect() -> None:
        """复用 CollectStage.execute()，与 Scheduler 同路径，产出完整 STAGE/STEP 事件流。

        sample_id 固定为 "DEBUG"，Flow Tab 的甘特/时间轴/stage 卡片三视图会自动跟随。
        """
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return
        if getattr(state, "scheduler_running", False):
            _safe_notify("Scheduler 正在执行队列，禁止 Debug 启动 collect", "warning")
            return

        # 组装 CollectStage 参数（与 PARAMS_SCHEMA 对齐）
        params: dict = {}
        vol = collect_volume_input.value
        if vol is not None and vol > 0:
            params["solvent_volume_ml"] = float(vol)
        ch = int(collect_channel_input.value) if collect_channel_input.value else None
        if ch is not None and ch > 0:
            params["solvent_channel"] = ch
        try:
            rep = int(collect_repeat_input.value) if collect_repeat_input.value is not None else None
        except (TypeError, ValueError):
            rep = None
        if rep is not None and rep > 0:
            params["liquid_repeat_count"] = rep

        stage = CollectStage(
            plc=plc,
            log_store=state.log_store,
            params=params,
            sample_id="DEBUG",
        )
        task = asyncio.create_task(stage.execute())

        collect_status_label.text = f"已启动 collect，params={params}"
        collect_status_label.classes("text-positive", remove="text-negative text-grey")
        _safe_notify("已启动 collect 状态机（CollectStage）", "positive")

        def _on_done(t: asyncio.Task) -> None:
            exc = t.exception()
            if exc is None:
                collect_status_label.text = "collect 已完成"
                collect_status_label.classes("text-positive", remove="text-negative text-grey")
                _safe_notify("collect 执行完成", "positive")
            else:
                collect_status_label.text = f"collect 执行失败: {exc}"
                collect_status_label.classes("text-negative", remove="text-positive text-grey")
                _safe_notify(f"collect 执行失败: {exc}", "negative")

        task.add_done_callback(_on_done)

    async def _do_reset_collect() -> None:
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return
        try:
            await plc.write_variable("collect_Reset", True)
            await asyncio.sleep(0.1)
            await plc.write_variable("collect_Reset", False)
            collect_status_label.text = "已发送 collect_Reset 脉冲"
            collect_status_label.classes("text-positive", remove="text-negative text-grey")
            state.log_store.append("DEBUG", "STAGE_RESET", "stage=collect")
            _safe_notify("collect 已复位", "positive")
        except Exception as e:
            collect_status_label.text = f"Reset 失败: {e}"
            collect_status_label.classes("text-negative", remove="text-positive text-grey")
            _safe_notify(f"Reset 失败: {e}", "negative")

    async def _do_start_develop() -> None:
        """复用 DevelopStage.execute()，与 Scheduler 同路径（v1.3 四阶段流程）。"""
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return
        if getattr(state, "scheduler_running", False):
            _safe_notify("Scheduler 正在执行队列，禁止 Debug 启动 develop", "warning")
            return
        # 互斥：已有 develop stage 在运行
        if state.active_develop_stage is not None:
            _safe_notify("develop 工位正在执行中，请等待完成或手动排液", "warning")
            return

        # 锁占用检测（快照提示，存在 TOCTOU 窗口：检查与实际锁获取之间可能有并发变化）
        target_tank = int(develop_tank_input.value or 1)
        target_group = (target_tank - 1) // 4 + 1
        if DevelopStage._prep_lock.locked():
            _safe_notify("⚠ PLC prep 序列器当前正忙，启动后可能阻塞等待", "warning")
        elif DevelopStage._group_locks[target_group].locked():
            _safe_notify(f"⚠ Group {target_group} 流路当前正忙，启动后可能阻塞等待", "warning")

        # 组装 DevelopStage 参数（与 PARAMS_SCHEMA v1.3 对齐）
        params: dict = {
            "rinse_mode": develop_mode_select.value or "cylinder",
            "target_tank": int(develop_tank_input.value or 1),
            "develop_duration_min": float(develop_duration_input.value or 0.2),
        }
        vol = develop_volume_input.value
        if vol is not None and vol > 0:
            params["solvent_volume_ml"] = float(vol)
        # 5 通道溶剂比例
        for _ch in range(1, 6):
            rv = develop_ratio_inputs[_ch].value
            if rv is not None and rv > 0:
                params[f"solvent_ratio_{_ch}"] = float(rv)

        stage = DevelopStage(
            plc=plc,
            log_store=state.log_store,
            params=params,
            sample_id="DEBUG",
        )
        # 注册到全局状态（供“触发排液”按钮访问）
        state.active_develop_stage = stage
        task = asyncio.create_task(stage.execute())

        develop_status_label.text = f"已启动 develop，params={params}"
        develop_status_label.classes("text-positive", remove="text-negative text-grey")
        _safe_notify("已启动 develop 状态机（v1.3 四阶段流程）", "positive")

        def _on_done(t: asyncio.Task) -> None:
            state.active_develop_stage = None
            exc = t.exception()
            if exc is None:
                develop_status_label.text = "develop 已完成"
                develop_status_label.classes("text-positive", remove="text-negative text-grey")
                _safe_notify("develop 执行完成", "positive")
            else:
                develop_status_label.text = f"develop 执行失败: {exc}"
                develop_status_label.classes("text-negative", remove="text-positive text-grey")
                _safe_notify(f"develop 执行失败: {exc}", "negative")

        task.add_done_callback(_on_done)

    async def _do_reset_develop() -> None:
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return
        try:
            await plc.write_variable("Expand_Reset", True)
            await asyncio.sleep(0.1)
            await plc.write_variable("Expand_Reset", False)
            develop_status_label.text = "已发送 Expand_Reset 脉冲"
            develop_status_label.classes("text-positive", remove="text-negative text-grey")
            state.log_store.append("DEBUG", "STAGE_RESET", "stage=develop")
            _safe_notify("develop 已复位", "positive")
        except Exception as e:
            develop_status_label.text = f"Reset 失败: {e}"
            develop_status_label.classes("text-negative", remove="text-positive text-grey")
            _safe_notify(f"Reset 失败: {e}", "negative")

    async def _do_trigger_drain() -> None:
        """触发排液：优先通过 DevelopStage.trigger_early_drain() 中断展开等待；
        降级为直接写 PLC 变量（standalone 排液测试场景）。
        """
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return

        # 优先：通过正在运行的 DevelopStage 中断等待
        if state.active_develop_stage is not None:
            stage = state.active_develop_stage
            if stage.is_waiting_drain:
                triggered = stage.trigger_early_drain()
                if triggered:
                    develop_status_label.text = "已提前触发排液（中断展开等待）"
                    develop_status_label.classes("text-positive", remove="text-negative text-grey")
                    _safe_notify("已提前触发排液", "positive")
                    return
                else:
                    _safe_notify("develop 正在执行但不在展开等待阶段", "warning")
                    return
            else:
                _safe_notify("develop 正在执行 prep 阶段，无法提前排液", "warning")
                return

        # 降级：直接写 PLC 变量（standalone 排液测试）
        tank_id = int(develop_tank_input.value or 1)
        try:
            await plc.trigger_drain(tank_id)
            develop_status_label.text = f"已触发排液: Tank_Drain_Enable[{tank_id}]=TRUE"
            develop_status_label.classes("text-positive", remove="text-negative text-grey")
            _safe_notify(f"排液已触发: Tank {tank_id}", "positive")
        except Exception as e:
            develop_status_label.text = f"触发排液失败: {e}"
            develop_status_label.classes("text-negative", remove="text-positive text-grey")
            _safe_notify(f"触发排液失败: {e}", "negative")

    async def _do_start_spotting() -> None:
        """复用 SpottingStage.execute()，与 Scheduler 同路径（v2 空气驱动策略）。"""
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return
        if getattr(state, "scheduler_running", False):
            _safe_notify("Scheduler 正在执行队列，禁止 Debug 启动 spotting", "warning")
            return
        # 互斥：spotting 锁占用检测
        if SpottingStage._spotting_lock.locked():
            _safe_notify("⚠ spotting 工位当前正忙，启动后可能阻塞等待", "warning")

        # 组装 SpottingStage 参数（v2 空气驱动策略，与 PARAMS_SCHEMA 对齐）
        params: dict = {}
        sv = spotting_sample_vol.value
        if sv is not None and sv > 0:
            params["sample_volume_ml"] = float(sv)
        mv = spotting_air_buffer.value
        if mv is not None and mv > 0:
            params["air_buffer_ml"] = float(mv)
        wv = spotting_wash_vol.value
        if wv is not None and wv > 0:
            params["wash_volume_ml"] = float(wv)
        sx = spotting_well["x"]
        if sx is not None:
            params["source_x"] = int(sx)
        sy = spotting_well["y"]
        if sy is not None:
            params["source_y"] = int(sy)
        cc = int(spotting_clean_count.value) if spotting_clean_count.value is not None else None
        if cc is not None and cc > 0:
            params["cleaning_count"] = cc

        stage = SpottingStage(
            plc=plc,
            log_store=state.log_store,
            params=params,
            sample_id="DEBUG",
        )
        task = asyncio.create_task(stage.execute())

        spotting_status_label.text = f"已启动 spotting，params={params}"
        spotting_status_label.classes("text-positive", remove="text-negative text-grey")
        _safe_notify("已启动 spotting 状态机（v2 空气驱动策略）", "positive")

        def _on_done(t: asyncio.Task) -> None:
            exc = t.exception()
            if exc is None:
                spotting_status_label.text = "spotting 已完成"
                spotting_status_label.classes("text-positive", remove="text-negative text-grey")
                _safe_notify("spotting 执行完成", "positive")
            else:
                spotting_status_label.text = f"spotting 执行失败: {exc}"
                spotting_status_label.classes("text-negative", remove="text-positive text-grey")
                _safe_notify(f"spotting 执行失败: {exc}", "negative")

        task.add_done_callback(_on_done)

    async def _do_reset_spotting() -> None:
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return
        try:
            await plc.write_variable("Sampling_Reset", True)
            await asyncio.sleep(0.1)
            await plc.write_variable("Sampling_Reset", False)
            spotting_status_label.text = "已发送 Sampling_Reset 脉冲"
            spotting_status_label.classes("text-positive", remove="text-negative text-grey")
            state.log_store.append("DEBUG", "STAGE_RESET", "stage=spotting")
            _safe_notify("spotting 已复位", "positive")
        except Exception as e:
            spotting_status_label.text = f"Reset 失败: {e}"
            spotting_status_label.classes("text-negative", remove="text-positive text-grey")
            _safe_notify(f"Reset 失败: {e}", "negative")

    async def _do_start_before_photo() -> None:
        """复用 BeforePhotoStage.execute()，与 Scheduler 同路径（v1.6 PhotoMode=1 → Step 15）。"""
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return
        if getattr(state, "scheduler_running", False):
            _safe_notify("Scheduler 正在执行队列，禁止 Debug 启动 before_photo", "warning")
            return
        # _scrape_lock 占用检测
        if ScrapeStage._scrape_lock.locked():
            _safe_notify("⚠ _scrape_lock 当前被占用，启动后可能阻塞等待", "warning")

        camera = getattr(state, 'camera', None)
        sample_store = state.sample_store

        stage = BeforePhotoStage(
            plc=plc,
            log_store=state.log_store,
            params={},
            sample_id="DEBUG",
            camera=camera,
            sample_store=sample_store,
        )
        task = asyncio.create_task(stage.execute())

        scrape_status_label.text = "已启动 before_photo（PhotoMode=1 → Step 15）"
        scrape_status_label.classes("text-positive", remove="text-negative text-grey")
        _safe_notify("已启动 before_photo 状态机（v1.6 PhotoMode=1）", "positive")

        def _on_bp_done(t: asyncio.Task) -> None:
            exc = t.exception()
            if exc is None:
                scrape_status_label.text = "before_photo 已完成"
                scrape_status_label.classes("text-positive", remove="text-negative text-grey")
                _safe_notify("before_photo 执行完成", "positive")
            else:
                scrape_status_label.text = f"before_photo 执行失败: {exc}"
                scrape_status_label.classes("text-negative", remove="text-positive text-grey")
                _safe_notify(f"before_photo 执行失败: {exc}", "negative")

        task.add_done_callback(_on_bp_done)

    async def _do_start_scrape() -> None:
        """复用 ScrapeStage.execute()，与 Scheduler 同路径（v1.6 PhotoMode=0 → Step 20）。

        无视觉服务时写入安全占位 G-code，PLC 走完整 10→20→30→40→Done 轨迹。
        """
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return
        if getattr(state, "scheduler_running", False):
            _safe_notify("Scheduler 正在执行队列，禁止 Debug 启动 scrape", "warning")
            return
        # _scrape_lock 占用检测
        if ScrapeStage._scrape_lock.locked():
            _safe_notify("⚠ _scrape_lock 当前被占用，启动后可能阻塞等待", "warning")

        camera = getattr(state, 'camera', None)
        sample_store = state.sample_store

        stage = ScrapeStage(
            plc=plc,
            log_store=state.log_store,
            params={},
            sample_id="DEBUG",
            camera=camera,
            sample_store=sample_store,
        )
        task = asyncio.create_task(stage.execute())

        scrape_status_label.text = "已启动 scrape（PhotoMode=0，无视觉→安全占位G-code）"
        scrape_status_label.classes("text-positive", remove="text-negative text-grey")
        _safe_notify("已启动 scrape 状态机（v1.6 PhotoMode=0）", "positive")

        def _on_scrape_done(t: asyncio.Task) -> None:
            exc = t.exception()
            if exc is None:
                scrape_status_label.text = "scrape 已完成"
                scrape_status_label.classes("text-positive", remove="text-negative text-grey")
                _safe_notify("scrape 执行完成", "positive")
            else:
                scrape_status_label.text = f"scrape 执行失败: {exc}"
                scrape_status_label.classes("text-negative", remove="text-positive text-grey")
                _safe_notify(f"scrape 执行失败: {exc}", "negative")

        task.add_done_callback(_on_scrape_done)

    async def _do_reset_scrape() -> None:
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return
        try:
            # 先写 Enable=False，防止 Reset 后 FSM 因 Enable=True 立即重启
            await plc.write_variable("scrape_Enable", False)
            await asyncio.sleep(0.05)
            await plc.write_variable("scrape_Reset", True)
            await asyncio.sleep(0.1)
            await plc.write_variable("scrape_Reset", False)
            scrape_status_label.text = "已发送 scrape Enable=False + Reset 脉冲"
            scrape_status_label.classes("text-positive", remove="text-negative text-grey")
            state.log_store.append("DEBUG", "STAGE_RESET", "stage=scrape")
            _safe_notify("scrape 已复位（Enable=False + Reset）", "positive")
        except Exception as e:
            scrape_status_label.text = f"Reset 失败: {e}"
            scrape_status_label.classes("text-negative", remove="text-positive text-grey")
            _safe_notify(f"Reset 失败: {e}", "negative")

    _custom_var_state = {
        "name": "Test_BOOL",     # 当前目标变量名（默认 Test_BOOL）
        "value": None,           # 最近读取的值
        "last_refresh": "—",     # 最近刷新时间
        "resolved": False,       # 变量名是否已成功解析
    }

    with ui.card().classes("w-full q-pa-md"):
        ui.label("BOOL 变量状态刷新测试").classes(
            "text-subtitle1 text-weight-bold q-mb-sm"
        )
        ui.label(
            "输入 PLC 端暴露的 BOOL 变量名（需与 OPC UA 节点名一致），"
            "即可对该变量进行读写测试。也可通过 Action ID 5001 触发 PLC 侧切换。"
        ).classes("text-caption text-grey q-mb-sm")

        # ── 变量名输入 + 类型选择 ──
        with ui.row().classes("items-center gap-3 q-mb-sm"):
            var_name_input = ui.input(
                label="变量名",
                value="Test_BOOL",
                placeholder="输入 PLC 变量名（如 Test_BOOL / UV_Lamp / ...）",
            ).classes("w-64").props("dense outlined")
            var_type_select = ui.select(
                label="类型",
                options={
                    "Boolean": "BOOL (Boolean)",
                    "Int16":   "INT (Int16)",
                    "Int32":   "DINT (Int32)",
                    "UInt16":  "UINT (UInt16)",
                    "UInt32":  "UDINT (UInt32)",
                    "Float":   "REAL (Float)",
                    "Double":  "LREAL (Double)",
                    "String":  "STRING (String)",
                },
                value="Boolean",
            ).classes("w-48").props("dense outlined")
            apply_var_btn = ui.button(
                "应用",
                icon="check",
                on_click=lambda: _apply_custom_var(),
            ).props("dense color=primary unelevated")

        with ui.row().classes("items-center gap-4 q-mb-sm"):
            # 当前值显示
            custom_var_badge = ui.badge("Test_BOOL: —", color="grey")
            # 刷新时间
            custom_var_time_label = ui.label("").classes("text-caption text-grey")

        # 写入值通用入口（支持所有类型）
        with ui.row().classes("items-center gap-3 q-mb-sm"):
            write_value_input = ui.input(
                label="写入值",
                placeholder="BOOL: True/False | 数值: 直接输入 | STRING: $R=回车 $$=$",
            ).classes("w-64").props("dense outlined")
            write_btn = ui.button(
                "写入",
                icon="edit",
                on_click=lambda: _confirm_write_custom_var(),
            ).props("dense color=primary unelevated")

        with ui.row().classes("items-center gap-3 q-mb-sm"):
            # 刷新按钮（读取当前值）
            refresh_btn = ui.button(
                "刷新读取",
                icon="refresh",
                on_click=lambda: _do_refresh_custom_var(),
            ).props("dense color=primary unelevated")
            # Toggle 按钮（读 → 取反 → 写回，仅 BOOL 有效）
            toggle_btn = ui.button(
                "Toggle 切换",
                icon="swap_horiz",
                on_click=lambda: _confirm_toggle_custom_var(),
            ).props("dense color=warning unelevated")
            # 置 True / False 按钮
            set_true_btn = ui.button(
                "置 True",
                icon="toggle_on",
                on_click=lambda: _confirm_set_custom_var(True),
            ).props("dense color=positive")
            set_false_btn = ui.button(
                "置 False",
                icon="toggle_off",
                on_click=lambda: _confirm_set_custom_var(False),
            ).props("dense")

        # 测试结果日志
        custom_var_log_label = ui.label("").classes(
            "text-caption q-mt-xs"
        )

    # ─── 自定义 BOOL 变量测试的回调函数（方案B） ───

    def _get_current_var_name() -> str:
        """获取当前目标变量名（从输入框读取，去空格）。"""
        raw = var_name_input.value.strip() if var_name_input.value else ""
        return raw or "Test_BOOL"

    def _get_current_var_vtype_str() -> str:
        """获取当前选择的类型字符串。"""
        return var_type_select.value or "Boolean"

    _INT_RANGES = {
        "Int16":  (-32768, 32767),
        "Int32":  (-2147483648, 2147483647),
        "UInt16": (0, 65535),
        "UInt32": (0, 4294967295),
    }

    def _parse_value(text: str, vtype_str: str):
        """根据类型解析字符串为具体值；超范围/非法则抛 ValueError。"""
        text = (text or "").strip()
        if not text:
            raise ValueError("写入值不能为空")
        if vtype_str == "Boolean":
            low = text.lower()
            if low in ("true", "1", "on", "yes"):
                return True
            if low in ("false", "0", "off", "no"):
                return False
            raise ValueError(f"Boolean 期望 True/False/1/0，实际: {text}")
        if vtype_str == "String":
            # 支持 CODESYS 转义序列：$R→CR, $N→LF, $$→$
            # 先用占位符保护 $$，避免 $R 替换后再被误处理
            text = text.replace('$$', '\x00')
            text = text.replace('$R', '\r').replace('$r', '\r')
            text = text.replace('$N', '\n').replace('$n', '\n')
            text = text.replace('$P', '\x0c').replace('$p', '\x0c')  # form feed
            text = text.replace('$L', '\n').replace('$l', '\n')  # line feed (same as $N)
            text = text.replace('\x00', '$')  # 还原 $$ → $
            return text
        if vtype_str in ("Float", "Double"):
            return float(text)
        v = int(text)
        if vtype_str in _INT_RANGES:
            lo, hi = _INT_RANGES[vtype_str]
            if not (lo <= v <= hi):
                raise ValueError(f"{vtype_str} 超出范围 [{lo}, {hi}]: {v}")
        return v

    def _confirm_write_custom_var() -> None:
        """统一写入确认对话框（支持 BOOL/INT/UINT/REAL/LREAL/STRING）。"""
        name = _get_current_var_name()
        vtype_str = _get_current_var_vtype_str()
        state = get_state()
        if state.plc_client is None or state.plc_state != "connected":
            ui.notify("PLC 未连接", type="negative")
            return
        try:
            value = _parse_value(write_value_input.value, vtype_str)
        except ValueError as e:
            ui.notify(f"解析失败: {e}", type="negative")
            return
        current = _custom_var_state.get("value")
        with ui.dialog() as dialog, ui.card():
            ui.label(f"确认写入 {name}").classes("text-h6 text-weight-bold")
            ui.label(f"类型: {vtype_str}").classes("text-body2")
            ui.label(f"当前值: {current}").classes("text-body2")
            ui.label(f"目标值: {value!r}").classes("text-body2 text-weight-bold")
            if not _is_mock_env():
                ui.label(
                    "⚠ 警告：当前连接至实机 PLC，此操作将直接影响设备变量！"
                ).classes("text-negative text-caption q-mt-sm")
            with ui.row().classes("gap-4 q-mt-md"):
                ui.button("取消", on_click=dialog.close).props("flat")
                ui.button(
                    "确认执行",
                    color="warning",
                    on_click=lambda: _do_set_custom_var(value, dialog),
                )
        dialog.open()

    def _fill_from_scan(row: dict) -> None:
        """扫描表格点击行：回填变量名+类型到测试区，自动触发读取。"""
        if not isinstance(row, dict):
            return
        var_name = row.get("var", "")
        type_str = row.get("type", "")
        if not var_name:
            return
        var_name_input.value = var_name
        _custom_var_state["name"] = var_name
        _custom_var_state["value"] = None
        _custom_var_state["last_refresh"] = "—"
        _custom_var_state["resolved"] = False
        supported = var_type_select.options  # dict
        if type_str in supported:
            var_type_select.value = type_str
            ui.notify(f"已回填: {var_name} (类型: {type_str})", type="info")
        else:
            ui.notify(
                f"已回填: {var_name}（类型 {type_str} 暂不支持直接写入，请手动选择）",
                type="warning",
            )
        custom_var_badge.text = f"{var_name}: —"
        custom_var_badge.color = "grey"
        custom_var_time_label.text = ""
        _update_custom_var_display()
        # 自动读一次，立刻展示当前值
        asyncio.create_task(_do_refresh_custom_var())

    def _apply_custom_var() -> None:
        """应用变量名：更新显示标题并重置状态。"""
        name = _get_current_var_name()
        _custom_var_state["name"] = name
        _custom_var_state["value"] = None
        _custom_var_state["last_refresh"] = "—"
        _custom_var_state["resolved"] = False
        custom_var_badge.text = f"{name}: —"
        custom_var_badge.color = "grey"
        custom_var_time_label.text = ""
        ui.notify(f"目标变量已切换为: {name}", type="info")

    def _update_custom_var_display() -> None:
        """更新自定义变量的显示状态（badge + 时间 + 按钮）。"""
        name = _custom_var_state["name"]
        val = _custom_var_state["value"]
        snapshot = get_state().variable_snapshot
        # 优先从 snapshot 同步（如果有）
        snap_val = snapshot.get(name)
        if snap_val is not None and val is None:
            _custom_var_state["value"] = snap_val
            val = snap_val

        if val is True:
            custom_var_badge.text = f"{name}: True"
            custom_var_badge.color = "green"
        elif val is False:
            custom_var_badge.text = f"{name}: False"
            custom_var_badge.color = "grey"
        elif val is not None:
            # 非 BOOL 类型值（Int32/Float）
            custom_var_badge.text = f"{name}: {val}"
            custom_var_badge.color = "blue"
        else:
            custom_var_badge.text = f"{name}: —"
            custom_var_badge.color = "grey"

        # 刷新时间
        if _custom_var_state["last_refresh"] != "—":
            custom_var_time_label.text = f"刷新于 {_custom_var_state['last_refresh']}"
        else:
            custom_var_time_label.text = ""

        # 按钮可用性：需 PLC 已连接
        state = get_state()
        connected = state.plc_client is not None and state.plc_state == "connected"
        for btn in (refresh_btn, toggle_btn, set_true_btn, set_false_btn, write_btn):
            if connected:
                btn.enable()
            else:
                btn.disable()

        # Toggle / 置True/False 仅对 Boolean 类型有意义
        is_bool = _get_current_var_vtype_str() == "Boolean"
        toggle_btn.visible = is_bool
        set_true_btn.visible = is_bool
        set_false_btn.visible = is_bool

    async def _do_refresh_custom_var() -> None:
        """主动读取当前变量值并刷新显示。"""
        name = _get_current_var_name()
        state = get_state()
        plc = state.plc_client
        if plc is None:
            _safe_notify("PLC 未连接", "negative")
            return
        try:
            val = await plc.read_variable(name)
            _custom_var_state["name"] = name
            _custom_var_state["value"] = val
            _custom_var_state["last_refresh"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            _custom_var_state["resolved"] = True
            _update_custom_var_display()
            _safe_notify(f"{name} = {val}", "info")
            state.log_store.append(
                "DEBUG", "VAR_REFRESH",
                f"{name}={val}",
            )
        except KeyError as e:
            _safe_notify(f"变量未找到: {e}", "negative")
            custom_var_log_label.text = f"变量 '{name}' 未在 PLC 端找到"
            custom_var_log_label.classes("text-negative", remove="text-positive text-warning")
        except Exception as e:
            _safe_notify(f"读取失败: {e}", "negative")
            custom_var_log_label.text = f"读取失败: {e}"
            custom_var_log_label.classes("text-negative", remove="text-positive text-warning")

    def _confirm_toggle_custom_var() -> None:
        """确认对话框：Toggle 当前变量（读→取反→写回）。"""
        name = _get_current_var_name()
        state = get_state()
        if state.plc_client is None or state.plc_state != "connected":
            ui.notify("PLC 未连接", type="negative")
            return
        current = _custom_var_state.get("value")
        target = not current if isinstance(current, bool) else True
        with ui.dialog() as dialog, ui.card():
            ui.label(f"确认 Toggle {name}").classes("text-h6 text-weight-bold")
            ui.label(f"当前值: {current}").classes("text-body2")
            ui.label(f"目标值: {target}").classes("text-body2 text-weight-bold")
            if not _is_mock_env():
                ui.label(
                    "⚠ 警告：当前连接至实机 PLC，此操作将直接影响设备变量！"
                ).classes("text-negative text-caption q-mt-sm")
            with ui.row().classes("gap-4 q-mt-md"):
                ui.button("取消", on_click=dialog.close).props("flat")
                ui.button(
                    "确认执行",
                    color="warning",
                    on_click=lambda: _do_set_custom_var(target, dialog),
                )
        dialog.open()

    def _confirm_set_custom_var(value: bool) -> None:
        """确认对话框：置当前变量为指定值。"""
        name = _get_current_var_name()
        state = get_state()
        if state.plc_client is None or state.plc_state != "connected":
            ui.notify("PLC 未连接", type="negative")
            return
        current = _custom_var_state.get("value")
        with ui.dialog() as dialog, ui.card():
            ui.label(f"确认置位 {name}").classes("text-h6 text-weight-bold")
            ui.label(f"当前值: {current}").classes("text-body2")
            ui.label(f"目标值: {value}").classes("text-body2 text-weight-bold")
            if not _is_mock_env():
                ui.label(
                    "⚠ 警告：当前连接至实机 PLC，此操作将直接影响设备变量！"
                ).classes("text-negative text-caption q-mt-sm")
            with ui.row().classes("gap-4 q-mt-md"):
                ui.button("取消", on_click=dialog.close).props("flat")
                ui.button(
                    "确认执行",
                    color="warning",
                    on_click=lambda: _do_set_custom_var(value, dialog),
                )
        dialog.open()

    def _do_set_custom_var(value, dialog) -> None:
        """关闭对话框并异步写入变量。"""
        dialog.close()
        asyncio.create_task(_async_set_custom_var(value))

    async def _async_set_custom_var(value) -> None:
        """异步写入当前变量并更新显示。"""
        name = _get_current_var_name()
        state = get_state()
        plc = state.plc_client
        if plc is None:
            return
        # 根据类型选择写入方法
        vtype_str = _get_current_var_vtype_str()
        from asyncua import ua as _ua
        vtype_map = {
            "Boolean": _ua.VariantType.Boolean,
            "Int16":   _ua.VariantType.Int16,
            "Int32":   _ua.VariantType.Int32,
            "UInt16":  _ua.VariantType.UInt16,
            "UInt32":  _ua.VariantType.UInt32,
            "Float":   _ua.VariantType.Float,
            "Double":  _ua.VariantType.Double,
            "String":  _ua.VariantType.String,
        }
        vtype = vtype_map.get(vtype_str, _ua.VariantType.Boolean)
        try:
            await plc.write_variable_dynamic(name, value, vtype)
            _custom_var_state["name"] = name
            _custom_var_state["value"] = value
            _custom_var_state["last_refresh"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            _update_custom_var_display()
            custom_var_log_label.text = f"{name} 已设为 {value} ({_custom_var_state['last_refresh']})"
            custom_var_log_label.classes("text-positive", remove="text-negative text-warning")
            _safe_notify(f"{name} 已设为 {value}", "positive")
            state.log_store.append(
                "DEBUG", "VAR_SET",
                f"{name}={value}",
            )
        except KeyError as e:
            custom_var_log_label.text = f"变量 '{name}' 未在 PLC 端找到"
            custom_var_log_label.classes("text-negative", remove="text-positive text-warning")
            _safe_notify(f"变量 '{name}' 未找到: {e}", "negative")
        except Exception as e:
            custom_var_log_label.text = f"写入失败: {e}"
            custom_var_log_label.classes("text-negative", remove="text-positive text-warning")
            _safe_notify(f"{name} 写入失败: {e}", "negative")

    def _confirm_set_var(var_name: str, value: bool) -> None:
        """弹出确认对话框后异步置位 PLC 变量。"""
        if not _is_mock_env() and not _override_enabled["flag"]:
            ui.notify("实机环境下请先勾选“允许调试置位”确认框", type="warning")
            return
        state = get_state()
        if state.plc_client is None or state.plc_state != "connected":
            ui.notify("PLC 未连接", type="negative")
            return

        with ui.dialog() as dialog, ui.card():
            ui.label(f"确认置位 {var_name}").classes("text-h6 text-weight-bold")
            current = state.variable_snapshot.get(var_name, "—")
            ui.label(f"当前值: {current}").classes("text-body2")
            ui.label(f"目标值: {value}").classes("text-body2 text-weight-bold")
            if not _is_mock_env():
                ui.label(
                    "警告：当前连接至实机 PLC，此操作将直接影响设备运行！"
                ).classes("text-negative text-caption q-mt-sm")
            with ui.row().classes("gap-4 q-mt-md"):
                ui.button("取消", on_click=dialog.close).props("flat")
                ui.button(
                    "确认执行",
                    color="warning",
                    on_click=lambda: _do_set_var(var_name, value, dialog),
                )
        dialog.open()

    def _do_set_var(var_name: str, value, dialog) -> None:
        dialog.close()
        asyncio.create_task(_async_set_var(var_name, value))

    async def _async_set_var(var_name: str, value) -> None:
        state = get_state()
        plc = state.plc_client
        if plc is None:
            return
        try:
            await plc.write_variable(var_name, value)
            state.log_store.append(
                "DEBUG", "PLC_SET",
                f"var={var_name} value={value}",
            )
            _safe_notify(f"{var_name} 已设为 {value}", "positive")
        except Exception as e:
            _safe_notify(f"置位失败: {e}", "negative")

    # ──────────────────────────────────────────────────────────────
    # 一键清零 PLC 变量（全工位 PC 侧写入变量批量重置）
    # ──────────────────────────────────────────────────────────────

    # PC→PLC 写入变量分类定义（第一性原理：遍历 NODE_TYPES 中所有 PC 写入变量）
    # 不包含：PLC_EStop（安全变量不自动清零）、IX11/IX12（PLC→PC 传感器）、
    # Tank_State/Tank_SampleID/Tank_Drain_Done（PLC 内部状态）
    _RESET_VAR_DEFS: dict[str, dict] = {
        "工位 FSM 控制信号 (Enable=False)": {
            "vars": [
                "collect_Enable", "Expand_Enable",
                "Sampling_Enable", "scrape_Enable",
            ],
            "value": False,
        },
        "scrape 乒乓/模式信号": {
            "vars": ["scrape_Confirm"],
            "value": False,
        },
        "展缸排液信号 Tank_Drain_Enable[1-8]": {
            "tank_array": "Tank_Drain_Enable",
            "size": 8,
            "value": False,
        },
        "scrape 工艺参数": {
            "vars": [
                "scrape_PhotoMode", "scrape_IsLast",
                "scrape_Source_Tank", "scrape_gcode_instructions",
            ],
            "zero": True,  # 按类型写零值 (int→0, bool→False, str→"")
        },
        "Expand 工艺参数": {
            "vars": [
                "Expand_Mode_Flag", "Expand_Target_Tank",
                "Expand_forward_instructions",
                "Expand_rinse_count", "Expand_up_liquid_count",
            ],
            "zero": True,
        },
        "Sampling 工艺参数": {
            "vars": [
                "Sampling_clean_count", "Sampling_X_coordinate",
                "Sampling_Y_coordinate",
            ],
            "zero": True,
        },
        "collect 工艺参数": {
            "vars": ["collect_forward_instructions", "collect_count"],
            "zero": True,
        },
        "CNC 标量参数": {
            "vars": [
                "g_safe_z", "g_approach_z", "g_pass_z",
                "g_pass_count", "g_total_depth",
                "g_plate_surface_z", "g_scrape_feed", "g_plunge_feed",
            ],
            "zero": True,
        },
        "CNC 点位数组 (400 点)": {
            "arrays": {
                "g_sx": 400, "g_sy": 400,
                "g_cx": 400, "g_cy": 400,
            },
            "value": 0.0,
        },
        "耗材动作码 (scrape)": {
            "vars": [
                "scrape_Plate_Op", "scrape_Fetch_Rack_Plate",
                "scrape_Old_Plate_Slot", "scrape_Consume_Slot",
            ],
            "zero": True,
        },
        "耗材动作码 (collect)": {
            "vars": [
                "collect_Plate_Op", "collect_Fetch_Rack_Plate",
                "collect_Old_Plate_Slot", "collect_Consume_Slot",
                "collect_Powder_Return_Slot",
            ],
            "zero": True,
        },
    }

    async def _do_reset_all_plc_vars() -> None:
        """一键清零所有 PC 侧写入的 PLC 变量。

        变量级容错：单个变量写失败（PLC 端不存在该节点等）自动跳过，
        不影响其余变量清零。失败仅记录 debug 日志，不计为错误。
        """
        state = get_state()
        plc = state.plc_client
        if plc is None or state.plc_state != "connected":
            _safe_notify("PLC 未连接", "negative")
            return

        total_ok = 0
        total_skip = 0

        async def _safe_write(name: str, value) -> bool:
            """写单个变量，失败返回 False（KeyError=PLC无此节点，最常见）。"""
            nonlocal total_ok, total_skip
            try:
                await plc.write_variable(name, value)
                total_ok += 1
                return True
            except Exception as e:
                total_skip += 1
                log.debug("[Debug] 清零跳过 %s: %s", name, e)
                return False

        for group_name, spec in _RESET_VAR_DEFS.items():
            # ── 类型 A：直接写值（BOOL=False 等） ──
            if "value" in spec and "vars" in spec:
                for var in spec["vars"]:
                    await _safe_write(var, spec["value"])

            # ── 类型 B：展缸数组元素逐个写入 ──
            elif "tank_array" in spec:
                arr_name = spec["tank_array"]
                for i in range(1, spec["size"] + 1):
                    try:
                        await plc.write_tank_element(arr_name, i, spec["value"])
                        total_ok += 1
                    except Exception as e:
                        total_skip += 1
                        log.debug("[Debug] 清零跳过 %s[%d]: %s", arr_name, i, e)

            # ── 类型 C：按类型归零 ──
            elif spec.get("zero") and "vars" in spec:
                from asyncua import ua as _ua
                for var in spec["vars"]:
                    vtype = NODE_TYPES.get(var)
                    if vtype is None:
                        total_skip += 1
                        continue
                    if vtype == _ua.VariantType.Boolean:
                        val: object = False
                    elif vtype in (_ua.VariantType.Int16, _ua.VariantType.Int32):
                        val = 0
                    elif vtype == _ua.VariantType.Float:
                        val = 0.0
                    elif vtype == _ua.VariantType.String:
                        val = ""
                    else:
                        val = 0
                    await _safe_write(var, val)

            # ── 类型 D：CNC 大数组批量写零 ──
            elif "arrays" in spec:
                for arr_name, size in spec["arrays"].items():
                    try:
                        await plc.send_recipe_params(
                            {arr_name: [spec["value"]] * size}
                        )
                        total_ok += 1
                    except Exception as e:
                        total_skip += 1
                        log.debug("[Debug] 清零跳过数组 %s: %s", arr_name, e)

        msg = f"已清零 {total_ok} 个变量"
        if total_skip:
            msg += f"（{total_skip} 个跳过，PLC 端可能未暴露）"

        state.log_store.append(
            "DEBUG", "RESET_ALL_PLC",
            f"ok={total_ok} skip={total_skip}",
        )

        if total_skip and total_skip > total_ok:
            _safe_notify(msg, "warning")
        else:
            _safe_notify(msg, "positive")

    def _confirm_reset_all_plc_vars() -> None:
        """一键清零确认对话框。

        安全机制：
        - Mock 环境：标准确认对话框
        - 实机环境：额外警告 + 标准确认（_override_enabled 门控）
        """
        state = get_state()
        if state.plc_client is None or state.plc_state != "connected":
            ui.notify("PLC 未连接", type="negative")
            return
        if not _is_mock_env() and not _override_enabled["flag"]:
            ui.notify("实机环境下请先勾选上方「允许调试置位」确认框", type="warning")
            return

        with ui.dialog() as dialog, ui.card():
            ui.label("一键清零 PLC 变量").classes("text-h6 text-weight-bold")
            ui.label(
                "将批量重置所有由 PC 端写入 PLC 的变量至初始状态："
            ).classes("text-body2 q-mb-xs")

            # 变量清单预览
            with ui.column().classes("q-mb-sm").style("max-height: 200px; overflow-y: auto"):
                for group_name, spec in _RESET_VAR_DEFS.items():
                    if "vars" in spec:
                        count = len(spec["vars"])
                    elif "tank_array" in spec:
                        count = spec["size"]
                    elif "arrays" in spec:
                        count = len(spec["arrays"])
                    else:
                        count = 0
                    ui.label(f"• {group_name} ({count})").classes("text-caption")

            total = sum(
                len(s.get("vars", [])) or s.get("size", 0) or len(s.get("arrays", {}))
                for s in _RESET_VAR_DEFS.values()
            )
            ui.label(f"共计约 {total} 个变量").classes("text-body2 text-weight-bold")

            if not _is_mock_env():
                ui.label(
                    "⚠ 警告：当前连接至实机 PLC，此操作将直接影响设备运行状态！"
                ).classes("text-negative text-caption q-mt-sm")

            with ui.row().classes("gap-4 q-mt-md"):
                ui.button("取消", on_click=dialog.close).props("flat")
                ui.button(
                    "确认清零",
                    color="red",
                    on_click=lambda: (
                        dialog.close(),
                        asyncio.create_task(_do_reset_all_plc_vars()),
                    ),
                )
        dialog.open()

    # ──────────────────────────────────────────────────────────────
    # 状态更新函数
    # ──────────────────────────────────────────────────────────────

    def _get_jog_block_reason() -> str:
        """返回调试阻塞原因，空字符串表示可以执行。

        Phase C：移除 PLC_Busy 旧全局互锁判断，改用 active_sample_ids 检测。
        """
        state = get_state()
        plc = state.plc_client
        connected = plc is not None and state.plc_state == "connected"
        if not connected:
            return "PLC 未连接"
        if state.active_sample_ids:
            return f"有样品在跑: {', '.join(sorted(state.active_sample_ids))}"
        if state.scheduler is not None:
            try:
                qsize = state.scheduler.qsize()
                if qsize > 0:
                    return f"队列非空（{qsize} 个待执行）"
            except Exception:
                pass
        # 第 6 条：视觉分析中检测
        entries = state.log_store.get_all()
        if entries:
            last = entries[-1]
            if last.event == "STEP_START" and "action_id=20" in last.detail and "stage=scrape" in last.detail:
                return "视觉分析中（scrape photo Step 20），暂时锁定"
        return ""

    def _update_ui_state() -> None:
        """更新按钮/状态/徽章（不 rebuild DOM）。

        Phase C：移除旧 Jog/PLC_Busy/PLC_Done/PLC_Error/quick_done 的 UI 引用。
        """
        state = get_state()
        plc = state.plc_client

        # 连接状态
        connected = plc is not None and state.plc_state == "connected"
        snapshot = state.variable_snapshot

        # ── scrape 工位实时状态徽章 ──
        pm_val = snapshot.get("scrape_PhotoMode")
        if pm_val is not None:
            try:
                pm_int = int(pm_val)
                if pm_int == 0:
                    scrape_photomode_badge.text = "PhotoMode: 0 (刮取)"
                    scrape_photomode_badge.color = "blue"
                elif pm_int == 1:
                    scrape_photomode_badge.text = "PhotoMode: 1 (拍照)"
                    scrape_photomode_badge.color = "cyan"
                else:
                    scrape_photomode_badge.text = f"PhotoMode: {pm_int}"
                    scrape_photomode_badge.color = "grey"
            except (ValueError, TypeError):
                scrape_photomode_badge.text = f"PhotoMode: {pm_val}"
                scrape_photomode_badge.color = "grey"
        else:
            scrape_photomode_badge.text = "PhotoMode: —"
            scrape_photomode_badge.color = "grey"

        step_val = snapshot.get("scrape_Step")
        if step_val is not None:
            scrape_step_badge.text = f"scrape_Step: {step_val}"
            scrape_step_badge.color = "blue" if int(step_val) > 0 else "grey"
        else:
            scrape_step_badge.text = "scrape_Step: —"
            scrape_step_badge.color = "grey"

        if ScrapeStage._scrape_lock.locked():
            scrape_lock_badge.text = "_scrape_lock: 占用中"
            scrape_lock_badge.color = "orange"
        else:
            scrape_lock_badge.text = "_scrape_lock: 空闲"
            scrape_lock_badge.color = "green"

        # 按钮可用性（PLC_EStop 置位按钮）
        allow_ctrl = connected and (_is_mock_env() or _override_enabled["flag"])
        for btn in _estop_ctrl_buttons:
            if allow_ctrl:
                btn.enable()
            else:
                btn.disable()

        # 消费通知队列（后台任务排队的通知，在UI线程安全显示）
        while _notification_queue:
            msg, ntype = _notification_queue.pop(0)
            try:
                ui.notify(msg, type=ntype)
            except Exception:
                pass
        # 消费全局通知队列（来自 queue.py 等后台 Task）
        while state._notification_queue:
            msg, ntype = state._notification_queue.pop(0)
            try:
                ui.notify(msg, type=ntype)
            except Exception:
                pass

        # 消费扫描结果队列（后台扫描任务排队的结果，在UI线程安全更新）
        while _scan_result_queue:
            msg, stype = _scan_result_queue.pop(0)
            try:
                scan_result_label.text = msg
                if stype == "positive":
                    scan_result_label.classes("text-positive", remove="text-negative text-warning text-grey")
                elif stype == "warning":
                    scan_result_label.classes("text-warning", remove="text-positive text-negative text-grey")
                elif stype == "negative":
                    scan_result_label.classes("text-negative", remove="text-positive text-warning text-grey")
                # 扫描后强制刷新表格以显示新变量
                _update_variable_table(force=True)
            except Exception:
                pass

        # 自定义变量显示刷新（从 snapshot 同步）
        _update_custom_var_display()

        # 液位监控 UI 刷新 (late binding via _wl_refresh)
        _wl_refresh()

    # 定时更新状态（100ms，不 rebuild DOM）
    ui.timer(0.1, _update_ui_state)

    # 液位监控刷新占位 (在下方定义 _wl_update_ui 后替换)
    def _wl_refresh():
        pass

    # ──────────────────────────────────────────────────────────────
    # 渲染
    # ──────────────────────────────────────────────────────────────

    # 初始填充变量表
    _update_variable_table()
    ui.separator()

    # ═══════════════════════════════════════════════════════════════
    # 液位监控
    # ═══════════════════════════════════════════════════════════════
    state = get_state()
    wl_client = state.water_level_client
    wl_configured = bool(state.water_level_enabled and state.water_level_orangepi_ip)
    _wl_device_online = False
    _wl_channel_data: dict[int, dict] = {}  # {channel_id: {height_cm, calibrated, ...}}
    _wl_labels: dict[int, dict[str, any]] = {}  # {channel_id: {status_label, height_label, eye_btn}}

    def _wl_update_ui():
        """将 _wl_channel_data 同步到 UI 控件"""
        for ch_id in range(1, 9):
            labels = _wl_labels.get(ch_id)
            if not labels:
                continue
            ch_data = _wl_channel_data.get(ch_id, {})

            def _disable_btns():
                labels["eye_btn"].disable()
                if "ref_btn" in labels:
                    labels["ref_btn"].disable()
                if "reload_btn" in labels:
                    labels["reload_btn"].disable()
                if "reset_btn" in labels:
                    labels["reset_btn"].disable()

            def _enable_btns():
                labels["eye_btn"].enable()
                if "ref_btn" in labels:
                    labels["ref_btn"].enable()
                if "reload_btn" in labels:
                    labels["reload_btn"].enable()
                if "reset_btn" in labels:
                    labels["reset_btn"].enable()

            if not _wl_device_online:
                labels["status_label"].text = "离线"
                labels["status_label"].classes("text-grey", remove="text-positive text-negative text-warning")
                labels["height_label"].text = "—.— cm"
                _disable_btns()
            elif ch_data:
                h = ch_data.get("height_cm")
                calibrated = ch_data.get("calibrated", False)
                if h is not None:
                    labels["height_label"].text = f"{h:.2f} cm"
                else:
                    labels["height_label"].text = "N/A"

                if calibrated:
                    labels["status_label"].text = "已标定"
                    labels["status_label"].classes("text-positive", remove="text-grey text-negative text-warning")
                else:
                    labels["status_label"].text = "未标定"
                    labels["status_label"].classes("text-warning", remove="text-grey text-positive text-negative")
                _enable_btns()
            else:
                labels["status_label"].text = "无数据"
                labels["status_label"].classes("text-grey", remove="text-positive text-negative text-warning")
                labels["height_label"].text = "—.— cm"
                _enable_btns()

    with ui.card().classes("w-full q-pa-md q-mt-sm"):
        ui.label("📹 液位监控").classes("text-subtitle1 text-weight-bold q-mb-sm")

        if not wl_configured:
            ui.label("未配置 water_level (config.yaml → water_level.enabled=false)").classes("text-grey text-caption")
        elif not wl_client:
            ui.label("MQTT 客户端不可用 (paho-mqtt 未安装或连接失败)").classes("text-warning text-caption")
        else:
            # 设备在线状态指示
            _wl_status_row = ui.row().classes("items-center gap-4 q-mb-sm")
            with _wl_status_row:
                _wl_device_badge = ui.label("设备: 检测中...").classes("text-caption text-grey")
                _wl_stream_url_prefix = ui.label("").classes("text-caption text-grey")
                _wl_grid_btn = ui.button(
                    "📺 网格预览 (8路)",
                    icon="grid_view",
                    on_click=lambda: _open_grid_preview(),
                ).props("dense color=primary unelevated").tooltip(
                    "一个连接看全部8路，不受浏览器6连接限制")

            # 注册 MQTT 数据回调
            def _on_wl_data(channels):
                for ch in channels:
                    cid = ch.get("channel", 0)
                    _wl_channel_data[cid] = ch
                # 注意: 此回调在 paho 线程中, 但 _wl_update_ui 在 UI timer 中调用,
                # 无需显式线程安全 (Python GIL + 简单字典操作)

            def _on_wl_device_state(online):
                nonlocal _wl_device_online
                _wl_device_online = online
                _wl_device_badge.text = "设备: 在线" if online else "设备: 离线"
                _wl_device_badge.classes(
                    "text-positive" if online else "text-negative",
                    remove="text-grey text-negative text-positive")
                if online:
                    _wl_grid_btn.enable()
                else:
                    _wl_grid_btn.disable()

            wl_client.on_data(_on_wl_data)
            wl_client.on_device_state_change(_on_wl_device_state)
            _wl_device_online = wl_client.device_online

            # 每通道操作辅助函数
            async def _wl_reload_config(ch_id: int):
                """重载单通道配置 (保留校准, 从文件恢复 ROI+参数)"""
                wl = state.water_level_client
                if not wl:
                    get_state()._notification_queue.append(("MQTT 客户端不可用", "negative"))
                    return
                ok = await wl.send_command("reload_config", {"channel": ch_id})
                if ok:
                    get_state()._notification_queue.append((f"CH{ch_id} 配置已重载", "positive"))
                else:
                    get_state()._notification_queue.append((f"CH{ch_id} 重载失败", "negative"))

            async def _wl_capture_reference(ch_id: int):
                """拍摄当前帧作为干板参考图 (P0: 参考图差分检测)"""
                wl = state.water_level_client
                if not wl:
                    get_state()._notification_queue.append(("MQTT 客户端不可用", "negative"))
                    return
                ok = await wl.send_command("capture_reference", {"channel": ch_id})
                if ok:
                    get_state()._notification_queue.append((f"CH{ch_id} 参考图已请求捕获 (下一帧自动抓取)", "positive"))
                else:
                    get_state()._notification_queue.append((f"CH{ch_id} 参考图请求失败", "negative"))

            async def _wl_factory_reset(ch_id: int):
                """工厂重置单通道 (清除校准+ROI+参数, 回到出厂状态)"""
                wl = state.water_level_client
                if not wl:
                    get_state()._notification_queue.append(("MQTT 客户端不可用", "negative"))
                    return
                ok = await wl.send_command("factory_reset", {"channel": ch_id})
                if ok:
                    get_state()._notification_queue.append((f"CH{ch_id} 已恢复出厂设置", "warning"))
                else:
                    get_state()._notification_queue.append((f"CH{ch_id} 恢复出厂失败", "negative"))

            def _wl_confirm_factory_reset(ch_id: int):
                """弹出确认对话框后执行工厂重置"""
                with ui.dialog() as confirm_dlg, ui.card():
                    ui.label(f"确认恢复 CH{ch_id} 出厂设置?").classes("text-h6 q-mb-sm")
                    ui.label("将清除: 校准数据 / ROI / 检测参数 → 回到默认值").classes("text-grey text-caption q-mb-md")
                    with ui.row().classes("gap-3 justify-end"):
                        ui.button("取消", on_click=lambda: confirm_dlg.close()).props("flat")
                        ui.button("确认重置", on_click=lambda: (
                            confirm_dlg.close(),
                            asyncio.create_task(_wl_factory_reset(ch_id)),
                        )).props("flat color=negative")
                confirm_dlg.open()

            orangepi_ip = state.water_level_orangepi_ip
            stream_port = state.water_level_stream_port
            _wl_stream_url_prefix.set_text(
                "MJPEG 同源代理 /wl_proxy/ch/N (不受浏览器连接限制)")

            # 8 通道行
            _wl_grid = ui.element("div").classes(
                "grid gap-2")
            _wl_grid.style("grid-template-columns: repeat(4, 1fr)")

            for ch_id in range(1, 9):
                with _wl_grid:
                    with ui.card().classes("q-pa-sm").style("min-width: 180px"):
                        with ui.row().classes("items-center justify-between"):
                            ui.label(f"CH{ch_id}").classes("text-weight-bold")
                            status_lbl = ui.label("—").classes("text-caption text-grey")
                        height_lbl = ui.label("—.— cm").classes("text-h6 q-mt-xs")
                        # 操作按钮行
                        with ui.row().classes("w-full justify-end items-center gap-1 q-mt-sm"):
                            ref_btn = ui.button(
                                "📷", on_click=lambda cid=ch_id: asyncio.create_task(
                                    _wl_capture_reference(cid)),
                            ).props("flat round dense size=sm").tooltip(f"CH{ch_id} 拍摄参考图")

                            reload_btn = ui.button(
                                "🔄", on_click=lambda cid=ch_id: asyncio.create_task(
                                    _wl_reload_config(cid)),
                            ).props("flat round dense size=sm").tooltip(f"CH{ch_id} 重载配置")

                            reset_btn = ui.button(
                                "🗑", on_click=lambda cid=ch_id: _wl_confirm_factory_reset(cid),
                            ).props("flat round dense size=sm").tooltip(f"CH{ch_id} 恢复出厂")

                            eye_btn = ui.button(
                                "👁", on_click=lambda cid=ch_id: _open_vision_dialog(cid)
                            ).props("flat round size=sm").tooltip(f"查看通道 {ch_id} 实时画面")

                            if not _wl_device_online:
                                ref_btn.disable()
                                reload_btn.disable()
                                reset_btn.disable()
                                eye_btn.disable()

                        _wl_labels[ch_id] = {
                            "status_label": status_lbl,
                            "height_label": height_lbl,
                            "eye_btn": eye_btn,
                            "ref_btn": ref_btn,
                            "reload_btn": reload_btn,
                            "reset_btn": reset_btn,
                        }

            # 初始: 设备离线, 禁用全部预览按钮
            _wl_grid_btn.disable()

    # 网格预览 Dialog 打开函数
    def _open_grid_preview():
        from ui.components.tank_vision_dialog import _build_grid_preview_dialog
        dlg = _build_grid_preview_dialog()
        dlg.open_preview()

    # TankVisionDialog 打开函数
    async def _open_vision_dialog(channel_id: int):
        wl = state.water_level_client
        if not wl:
            ui.notify("MQTT 客户端不可用", type="negative")
            return
        from ui.components.tank_vision_dialog import _build_tank_vision_dialog
        dlg = _build_tank_vision_dialog(channel_id, wl)
        # 注意: 不能使用 asyncio.create_task() —— 会丢失 NiceGUI slot context
        # 导致 ui.run_javascript() 抛出 "slot stack is empty"
        # NiceGUI 自动检测 handler 返回的 coroutine 并在保留 slot context 的
        # 前提下调度执行 (_await_and_handle_in_context)
        await dlg.open_channel()

    # 将 _wl_refresh 占位替换为实际的更新函数
    # （_wl_refresh 在同作用域 line 1660 定义，闭包 _update_ui_state 通过名字查找，
    #   此处直接赋值即可覆盖占位，不需要 nonlocal）
    _wl_refresh = _wl_update_ui

    # 注册 PLC 状态变化回调
    state = get_state()
    state._plc_state_callbacks.append(_update_ui_state)

    return {
        "variable_table_update": _update_variable_table,
    }
