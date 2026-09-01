"""
pTLC Web UI - Phase E 模块化重构
=================================
NiceGUI Web 界面，提供系统状态监控与人工确认交互。

页面结构（4 Tab + 固定 Header）：
  - Header：PLC 连接状态、当前样品、调度器运行状态、人工确认区、重连恢复区
  - Queue Tab：样品队列 + 入队表单
  - Recipe Tab：配方加载/编辑/保存
  - Flow Tab：流程甘特图 + 事件时间轴
  - Debug Tab：PLC 变量只读表 + 受限写入

模块拆分：
  - ui/state.py     : AppState 单例 + 人工确认回调
  - ui/pages.py     : Tab 路由管理
  - ui/sections/*   : 各区域 UI 渲染
  - ui/app.py       : 入口（run_ui + 后台调度任务）

启动入口（main.py --batch4）：
  from ui.app import run_ui
  run_ui(requests, mock_vision=False)
"""

import asyncio
import logging
import os
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional

from nicegui import app as nicegui_app, ui

from core.plc_client import PLCClient, PLCState
from core.scheduler import Scheduler, SampleRequest
from core.variable_monitor import VariableMonitor
from core.vision_service import VisionService, build_vision_from_cfg
from core.consumable_manager import PLATE_SENSOR_COUNT
from ui.state import (
    AppState, get_state,
    ui_confirm, ui_resume_confirm, on_plc_state_ui,
)

# MJPEG 同源代理: 浏览器 → 上位机 → 香橙派
from starlette.requests import Request
from starlette.responses import StreamingResponse
import httpx

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# UI 感知调度器：运行每个样品前后同步更新 AppState
# ──────────────────────────────────────────────────────────────────────

class UIScheduler(Scheduler):
    """继承 Scheduler，在 _run_one 前后更新 AppState.sample_statuses。

    并发安全：
    - 使用 try/finally 保证 CancelledError 时状态也能更新为 ERROR
    - 使用 active_sample_ids（set）代替单值 current_sample，避免并发样品互相覆盖
    """

    async def _run_one(self, request: SampleRequest) -> None:
        state = get_state()
        sid = request.sample_id
        state.sample_statuses[sid] = "RUNNING"
        # 并发安全：多样品集合
        state.active_sample_ids.add(sid)

        try:
            await super()._run_one(request)  # 父类内部捕获 Exception，CancelledError 会传播
        except asyncio.CancelledError:
            # CancelledError 不被父类捕获，必须在此处理
            # 区分 E-Stop 与普通取消：急停是设备事件，取消是调度事件
            from core.estop import is_estop_active
            status = "ESTOP" if is_estop_active() else "CANCELLED"
            state.sample_statuses[sid] = status
            state.log_store.append(sid, status, "急停触发" if status == "ESTOP" else "任务被取消")
            log.warning("[UIScheduler] 样品 %s 状态: %s", sid, status)
            raise
        finally:
            # 正常完成：从 log_store 读取最终事件（DONE / ERROR）
            if state.sample_statuses.get(sid) == "RUNNING":
                for entry in reversed(self._log.get_sample(sid)):
                    if entry.event in ("DONE", "ERROR"):
                        state.sample_statuses[sid] = entry.event
                        break
                else:
                    # 无 DONE/ERROR 事件（不应发生），标记为 ERROR
                    state.sample_statuses[sid] = "ERROR"
            # 清理 active_sample_ids
            state.active_sample_ids.discard(sid)



# ──────────────────────────────────────────────────────────────────────
# 后台调度任务（在 NiceGUI 事件循环中运行）
# ──────────────────────────────────────────────────────────────────────

async def _scheduler_background_task() -> None:
    """在 NiceGUI 的 asyncio 事件循环中运行完整调度流程。

    语义约定：
    - state.scheduler_running 仅在“当前有样品在执行/队列非空”时为 True；
      后台任务存活但队列空闲时为 False，Debug Tab 可正常启用。
    """
    state = get_state()

    # 如果已有独立 PLC 连接（点动调试用），先断开避免冲突
    standalone_task = getattr(state, "_standalone_plc_task", None)
    if standalone_task is not None and not standalone_task.done():
        standalone_task.cancel()
        state._standalone_plc_task = None
        log.info("[后台调度] 已断开独立 PLC 连接，改由调度器接管")

    vision = build_vision_from_cfg(state.vision_cfg, output_dir=state.output_dir)
    vm = VariableMonitor()
    # 将 VariableMonitor 快照同步到 state.variable_snapshot
    def _sync_snapshot(var_name: str, val) -> None:
        state.variable_snapshot[var_name] = val
    vm.add_listener(_sync_snapshot)
    poll_task = None
    persistence = None
    try:
        async with PLCClient(
            url=state.plc_url,
            reconnect_wait_timeout=state.reconnect_wait_timeout,
        ) as plc:
            # 先注册 UI 状态监听（捕获后续 RECONNECTING/CONNECTED）
            plc.add_state_listener(on_plc_state_ui)
            state.plc_state = plc.state.value
            state.plc_connected = True
            # 注入 PLCClient，供 Debug Tab 点动 / 受限写入调用
            state.plc_client = plc
            # ── 尽早创建 Scheduler，解除 UI 入队对 VariableMonitor 的等待 ──
            # Scheduler 构造仅依赖 plc + vision + 回调，不依赖 VM / LogPersistence；
            # 入队操作只写 asyncio.Queue，真正执行 stage 时 VM 早已就绪。
            scheduler = UIScheduler(
                plc=plc,
                vision=vision,
                camera=getattr(state, 'camera', None),
                confirm_callback=ui_confirm,
                log_store=state.log_store,
                resume_confirm=ui_resume_confirm,
                sample_store=state.sample_store,
                consumable_manager=state.consumable_manager,
            )
            # E-Stop 回调延迟绑定：scheduler 创建后注册到 PLCClient
            from core.estop import broadcast_estop
            plc._on_estop = lambda: broadcast_estop(scheduler)
            # 将 scheduler 注入到 state，供 UI 入队按钮调用
            state.scheduler = scheduler
            # 将 ResourceManager 注入到 state，供 Recovery UI 查询 NEEDS_DRAIN 缸
            state.resource_manager = scheduler._resource_manager

            # 启动 VariableMonitor（实机约 10-25s，不阻塞入队）
            try:
                await vm.start(plc.client_session)
                state.variable_snapshot.update(vm.snapshot)
            except Exception as e:
                log.warning("[后台调度] VariableMonitor 启动失败: %s", e)
            # 自动扫描 PLC 全部变量并扩展订阅（实机可能有额外变量）
            try:
                new_count = await vm.auto_discover(plc.client_session)
                state.variable_snapshot.update(vm.snapshot)
                if new_count > 0:
                    log.info("[后台调度] auto_discover 新增 %d 个变量", new_count)
            except Exception as e:
                log.debug("[后台调度] auto_discover 失败（不影响基本功能）: %s", e)
            # 注入 VariableMonitor，供 Debug Tab 扫描变量调用
            state.variable_monitor = vm
            # 启动轮询回退：每 500ms 通过 PLCClient 主动读取所有变量
            poll_task = asyncio.create_task(_poll_loop(vm, plc, state))

            # 启动日志持久化（P2-1）：与 SampleStore 共用同一样品根目录
            if state.log_persistence_enabled and state.log_persistence is None:
                try:
                    from core.log_persistence import build_default_persistence
                    persistence = build_default_persistence(
                        samples_root=state.sample_store.root_dir,
                        flush_interval=state.log_persistence_flush_interval,
                        batch_size=state.log_persistence_batch_size,
                        archive_older_than_days=state.log_persistence_archive_days,
                    )
                    await persistence.start()
                    state.log_store.attach_persistence(persistence)
                    state.log_persistence = persistence
                except Exception as e:
                    log.error("[后台调度] LogPersistence 启动失败（已降级为纯内存日志）: %s", e)
                    persistence = None

            # 将启动配置中的请求全部入队，并初始化状态
            for req in state.startup_requests:
                await scheduler.enqueue(req)
                state.sample_statuses[req.sample_id] = "PENDING"

            # 持续运行：队列非空则执行，空则等待 UI 动态入队（不主动退出）
            # 动态维护 scheduler_running：仅在有样品执行中时为 True，
            # 队列空闲时为 False，以解除 Debug Tab 的 collect 启动互锁。
            while not getattr(scheduler, "_aborted", False):
                if scheduler.qsize() > 0:
                    state.scheduler_running = True
                    state.scheduler_done = False
                    await scheduler.run_until_empty()
                    state.scheduler_running = False
                else:
                    state.scheduler_running = False
                    await asyncio.sleep(0.3)
            state.reconnect_count = plc.reconnect_count
            state.log_store.print_summary()

    except Exception as e:
        state.error_msg = str(e)
        log.error("[后台调度] 失败: %s", e)
    finally:
        if poll_task and not poll_task.done():
            poll_task.cancel()
        await vm.stop()
        # 停止日志持久化（drain 队列 → close sink），并同步解除 LogStore 绑定
        if persistence is not None:
            try:
                await persistence.stop()
            except Exception as e:
                log.error("[后台调度] LogPersistence 停止异常: %s", e)
            state.log_persistence = None
            state.log_store.attach_persistence(None)
        state.plc_connected = False
        state.scheduler_running = False
        state.scheduler_done = True
        state.scheduler = None
        state.resource_manager = None
        state.plc_client = None
        state.variable_monitor = None
        state.variable_snapshot.clear()


# ──────────────────────────────────────────────────────────────────────
# 页面构建 + 定时刷新
# ──────────────────────────────────────────────────────────────────────

def _build_page() -> None:
    """在当前 NiceGUI 路由 context 中构建完整页面。"""
    from ui.pages import build_page

    state = get_state()

    # ui.header() 是顶级布局元素，必须在 ui.column() 外部渲染
    with ui.header().classes("items-start"):
        ui.label("pTLC 自动化工作站").classes("text-h6 q-mr-md")

    with ui.column().classes("w-full max-w-screen-2xl mx-auto q-pa-md gap-4"):
        refs = build_page()

    # 将 tab_panels 和 tab_recovery 存入 state，供 Header 急停导航按钮使用
    state._tab_panels = refs.get("_tab_panels")
    state._tab_recovery = refs.get("_tab_recovery")
    state._tab_consumable = refs.get("_tab_consumable")

    # ── 定时刷新（每 500 ms） ──
    async def _periodic_refresh() -> None:
        state = get_state()

        # ── 周期同步展缸状态（PLC → PC 缓存）──
        # allocate() 仅在分配时同步一次，prep/develop/drain 推进后 PC 缓存陈旧；
        # dashboard 展缸格子依赖 rm.all_tank_info() 的 .state 字段，必须周期 sync。
        rm = getattr(state, "resource_manager", None)
        if rm is not None:
            tick = (state._ui_refresh_cache.get("tank_sync_tick", 0) + 1) % 2  # 1s 节流
            state._ui_refresh_cache["tank_sync_tick"] = tick
            if tick == 0:
                try:
                    await rm.sync_states()
                except Exception as e:
                    log.debug("[App] tank sync_states 失败: %s", e)

        # ── 周期同步耗材架板级 DI（PLC IX11/IX12 BYTE → ConsumableManager._plate_present，2s 节流）──
        # PLC 工程打包为 2 BYTE，PLCClient.read_consumable_sensor() 内部位解码为 list[bool, 12]。
        # 仅同步 12 个板级在位 DI，不影响孔级账本（账本走 UI 录入 + JSON 落盘）。
        cm = getattr(state, "consumable_manager", None)
        plc = getattr(state, "plc_client", None)
        if cm is not None and plc is not None and plc.is_ok:
            c_tick = (state._ui_refresh_cache.get("consumable_sync_tick", 0) + 1) % 4  # 2s 节流
            state._ui_refresh_cache["consumable_sync_tick"] = c_tick
            if c_tick == 0:
                try:
                    sensors = await plc.read_consumable_sensor()
                    if sensors and len(sensors) == PLATE_SENSOR_COUNT:
                        await cm.sync_plate_presence(list(sensors))
                except Exception as e:
                    log.debug("[App] consumable plate presence sync 失败: %s", e)

        # ── Header 脏检查：仅当关键状态变化时才 refresh ──
        header_state = {
            "plc_state": state.plc_state,
            "scheduler_running": state.scheduler_running,
            "scheduler_done": state.scheduler_done,
            "reconnect_count": state.reconnect_count,
            "active_sample_ids": frozenset(state.active_sample_ids),
            "error_msg": state.error_msg,
            "confirm_sample_id": state.confirm_sample_id,
            "has_resume_future": state.resume_future is not None,
            "collect_Step": state.variable_snapshot.get("collect_Step"),
            "estop_active": state.estop_active,
        }
        if header_state != state._ui_refresh_cache.get("header"):
            status_sec = refs.get("status")
            reconnect_sec = refs.get("reconnect")
            confirm_sec = refs.get("confirm")
            if status_sec:
                status_sec.refresh()
            if reconnect_sec:
                reconnect_sec.refresh()
            if confirm_sec:
                confirm_sec.refresh()
            state._ui_refresh_cache["header"] = header_state

        # ── Queue 脏检查：仅当样品状态表变化才 refresh ──
        # 另外 log_store 总条数变化也需触发 refresh：display_status 依赖
        # STAGE_START/STAGE_DONE 事件流进一步区分 RUNNING/WAITING/PENDING，
        # 如果 log_store 增量事件未带动 sample_statuses 变动（如 STAGE_DONE
        # 之后等下一阶段锁），Queue Tab 会显示滞后。
        queue_state = (dict(state.sample_statuses), len(state.log_store))
        if queue_state != state._ui_refresh_cache.get("queue"):
            queue_sec = refs.get("queue")
            if queue_sec:
                queue_sec.refresh()
            state._ui_refresh_cache["queue"] = queue_state

        # ── Flow 脏检查：按 log_store 总条目数判断 ──
        # dashboard 模式由自身 1s timer 指纹管控，不在此处 refresh（避免 ui.expansion 折叠）
        flow_sec = refs.get("flow_content")
        if flow_sec:
            total_entries = len(state.log_store)
            if total_entries != state._ui_refresh_cache.get("flow_total", 0):
                flow_mode_fn = refs.get("flow_view_mode")
                if not flow_mode_fn or flow_mode_fn() != "dashboard":
                    flow_sec.refresh()
                state._ui_refresh_cache["flow_total"] = total_entries

        # ── variable_table 就地更新 rows（不再销毁重建 DOM，保持滚动位置）──
        var_table_update = refs.get("variable_table_update")
        if var_table_update:
            var_table_update()

        # ── Vision Tab 脏检查 ──
        vision_sec = refs.get("vision_section")
        vision_state = {
            "analyzing": state.vision_analyzing,
            "has_result": state.vision_analysis_result is not None,
            "selected_bands": list(state.vision_selected_bands),
            "gcode_text": bool(state.vision_gcode_text),
            "scrape_waiting": state.vision_scrape_waiting,
            "scrape_after_path": str(state.vision_scrape_after_path) if state.vision_scrape_after_path else None,
            "before_photo_waiting": state.vision_before_photo_waiting,
            "before_photo_path": str(state.vision_before_photo_path) if state.vision_before_photo_path else None,
            "current_sample": state.vision_current_sample_id,
            "waiting_sample": state.vision_waiting_sample_id,
        }
        if vision_state != state._ui_refresh_cache.get("vision"):
            from ui.sections.vision import refresh_vision
            refresh_vision(state, refs)
            state._ui_refresh_cache["vision"] = vision_state

        # 处理通知队列（所有 Tab 共享）
        while state._notification_queue:
            msg, msg_type = state._notification_queue.pop(0)
            ui.notify(msg, type=msg_type)

        # ── Vision Tab badge 提示：乒乓等待时在导航栏显示红点 ──
        tab_vision = refs.get("_tab_vision")
        if tab_vision:
            waiting = state.vision_scrape_waiting
            was_waiting = state._ui_refresh_cache.get("vision_badge_waiting", False)
            if waiting != was_waiting:
                state._ui_refresh_cache["vision_badge_waiting"] = waiting
                if waiting:
                    # 乒乓等待开始→显示红色提示点 + 更新标签文字
                    tab_vision.props('alert="red"')
                    sample_hint = state.vision_waiting_sample_id or ""
                    ui.notify(
                        f"样品 {sample_hint} 需要确认 G-code 下发，请前往 Vision Tab",
                        type="warning",
                        position="top",
                        timeout=8000,
                    )
                else:
                    # 乒乓结束→移除提示点
                    tab_vision.props(remove='alert')

        # ── Recovery Tab 脏检查刷新（独立于急停态）──
        # 关键状态：ResourceManager 是否就绪、NEEDS_DRAIN 缸列表、急停态
        # 解耦原因：调度器启动晚于页面构建时，Recovery Tab 首次渲染拿到的是
        # resource_manager=None 的过期视图，必须随调度器就绪自动刷新，否则
        # 用户切过去看到"ResourceManager 未连接"，需手动 reload 才能恢复。
        rm = getattr(state, "resource_manager", None)
        try:
            needs_drain = tuple(rm.needs_drain_tanks()) if rm is not None else ()
        except Exception:
            needs_drain = ()
        recovery_state = {
            "rm_ready": rm is not None,
            "needs_drain": needs_drain,
            "estop_active": state.estop_active,
        }
        if recovery_state != state._ui_refresh_cache.get("recovery"):
            recovery_alert = refs.get("recovery_alert")
            recovery_drain = refs.get("recovery_drain")
            if recovery_alert:
                recovery_alert.refresh()
            if recovery_drain:
                recovery_drain.refresh()
            state._ui_refresh_cache["recovery"] = recovery_state

        # ── 急停触发时自动切到 Recovery Tab ──
        if state.estop_active:
            tab_panels = refs.get("_tab_panels")
            tab_recovery = refs.get("_tab_recovery")
            if tab_panels and tab_recovery:
                if getattr(tab_panels, 'value', None) != tab_recovery:
                    tab_panels.set_value(tab_recovery)
            else:
                log.error(
                    "[App] E-Stop 触发但 Recovery Tab 引用缺失（_tab_panels=%s, _tab_recovery=%s），自动切换失败",
                    tab_panels, tab_recovery,
                )

    ui.timer(0.5, _periodic_refresh)


# ──────────────────────────────────────────────────────────────────────
# 公共入口
# ──────────────────────────────────────────────────────────────────────

def run_ui(
    requests: list,
    mock_vision: bool = False,
    output_dir: Path = Path("vision_output"),
    host: str = "0.0.0.0",
    port: int = 8080,
    plc_url: str = "opc.tcp://localhost:4840",
    reconnect_wait_timeout: float = 60.0,
    camera: Optional[object] = None,
    log_persistence_enabled: bool = True,
    log_persistence_flush_interval: float = 0.5,
    log_persistence_batch_size: int = 10,
    log_persistence_archive_days: int = 30,
    database_enabled: bool = True,
    database_path: str = "data/tlc_data.sqlite",
    gcode_cfg: Optional[object] = None,
    vision_cfg: Optional[object] = None,
    water_level_enabled: bool = False,
    water_level_broker_ip: str = "",
    water_level_broker_port: int = 1883,
    water_level_stream_port: int = 8080,
    water_level_orangepi_ip: str = "",
    orangepi_manager: Optional[object] = None,
) -> None:
    """启动 pTLC Web UI，并在后台运行调度器（阻塞直至服务器关闭）。

    参数：
        requests               : SampleRequest 列表（预先入队）
        mock_vision            : True = mock 视觉；False = 真实图像分析
        output_dir             : 视觉输出目录
        host                   : 监听地址，0.0.0.0 允许局域网手机访问
        port                   : 监听端口，默认 8080
        plc_url                : OPC UA 服务器地址
        reconnect_wait_timeout : send_* 等待重连恢复的最大秒数
        database_enabled       : 是否启用 SQLite 二级索引层
        database_path          : SQLite 数据库文件路径
    """
    state = get_state()
    state.startup_requests = requests
    state.mock_vision = mock_vision
    state.output_dir = output_dir
    state.plc_url = plc_url
    state.reconnect_wait_timeout = reconnect_wait_timeout
    state.camera = camera
    # P2-1：日志持久化参数注入到 state（供 _scheduler_background_task 读取）
    state.log_persistence_enabled = log_persistence_enabled
    state.log_persistence_flush_interval = log_persistence_flush_interval
    state.log_persistence_batch_size = log_persistence_batch_size
    state.log_persistence_archive_days = log_persistence_archive_days
    # 数据库二级索引层参数
    state.database_enabled = database_enabled
    state.database_path = database_path
    # G-code 真机标定参数（从 config.yaml 注入，供 vision.py / scrape.py 读取透传）
    state.gcode_cfg = gcode_cfg
    # 视觉姿态归一化参数（从 config.yaml vision 段注入）
    state.vision_cfg = vision_cfg
    # 液位检测 MQTT + MJPEG 配置
    state.water_level_enabled = water_level_enabled
    state.water_level_broker_ip = water_level_broker_ip
    state.water_level_broker_port = water_level_broker_port
    state.water_level_stream_port = water_level_stream_port
    state.water_level_orangepi_ip = water_level_orangepi_ip
    # OrangePiManager 引用（由 main.py 创建并传入，供 on_shutdown 远程停止）
    state.orangepi_manager = orangepi_manager

    @nicegui_app.on_startup
    async def _start_scheduler():
        # ── 与 PLC 解耦的基础服务（全生命周期）──
        # SampleStore + DatabaseService 在 UI 启动时即就绪，不依赖 PLC 连接。
        # 这样历史样品 Tab 在未连 PLC 状态下仍可读取 DB 索引。
        if state.sample_store is None:
            from core.sample_store import SampleStore
            state.sample_store = SampleStore(root_dir=Path("data/samples"))
        if state.database_enabled and state.database is None:
            try:
                from core.database import DatabaseService
                db_service = DatabaseService(db_path=Path(state.database_path))
                await db_service.start()
                state.database = db_service
                state.sample_store._db = db_service
            except Exception as e:
                log.error("[on_startup] DatabaseService 启动失败（历史样品 Tab 将显示为未启用）: %s", e)

        # ── ConsumableManager（账本持久化到 data/consumable_state.json）──
        # 账本是实验员通过 UI 录入的孔级余量状态，重启后从磁盘恢复。
        # PLC 真机联调时，PLCClient 轮询会调用 sync_plate_presence 同步 12 个板级 DI。
        if state.consumable_manager is None:
            from core.consumable_manager import ConsumableManager
            ledger_path = Path("data/consumable_state.json")
            cm = ConsumableManager(persistence_path=ledger_path)
            state.consumable_manager = cm
            log.info(
                "[on_startup] ConsumableManager 已初始化（账本文件=%s）",
                ledger_path,
            )

        # ── WaterLevelClient（液位检测 MQTT 客户端）──
        # 独立于 PLC 连接，按需启用
        if state.water_level_enabled and state.water_level_broker_ip:
            try:
                from core.water_level_client import WaterLevelClient
                wl = WaterLevelClient(
                    broker_ip=state.water_level_broker_ip,
                    broker_port=state.water_level_broker_port,
                )
                ok = await wl.connect()
                if ok:
                    state.water_level_client = wl
                    log.info("[on_startup] WaterLevelClient 已连接 %s:%s",
                             state.water_level_broker_ip, state.water_level_broker_port)
                else:
                    log.warning("[on_startup] WaterLevelClient 连接失败")
            except ImportError as e:
                log.warning("[on_startup] paho-mqtt 未安装, WaterLevelClient 不可用: %s", e)
            except Exception as e:
                log.error("[on_startup] WaterLevelClient 启动异常: %s", e)

        # 注入全局调度器启动器：供 Queue Tab 等入队时懒启动调用（避免 queue 反向 import app）
        def _start_if_needed() -> bool:
            if state.scheduler is not None:
                return False
            asyncio.create_task(_scheduler_background_task())
            return True
        state.scheduler_starter = _start_if_needed

        # 仅在有 startup_requests 时自动启动调度器；
        # 无样品时用户可通过"连接 PLC" 按钮手动建连（点动调试）或 Queue Tab 入队时懒启动
        if state.startup_requests:
            asyncio.create_task(_scheduler_background_task())

    @nicegui_app.on_shutdown
    async def _stop_basic_services():
        # 与 on_startup 对称：关闭 DatabaseService + WaterLevelClient + 远程停止香橙派。
        # （LogPersistence/Scheduler/PLC 由 _scheduler_background_task 的 finally 负责）
        db = state.database
        if db is not None:
            try:
                await db.stop()
            except Exception as e:
                log.error("[on_shutdown] DatabaseService 停止异常: %s", e)
            state.database = None
            if state.sample_store is not None:
                state.sample_store._db = None

        # WaterLevelClient 断开（带 3 秒超时保护）
        wl = state.water_level_client
        if wl is not None:
            try:
                await asyncio.wait_for(wl.disconnect(), timeout=3.0)
            except (asyncio.TimeoutError, Exception) as e:
                log.warning("[on_shutdown] WaterLevelClient 断开异常/超时，强制清理: %s", e)
                wl.force_cleanup()
            state.water_level_client = None

        # 远程停止香橙派液位检测脚本
        opi = state.orangepi_manager
        if opi is not None:
            try:
                await asyncio.wait_for(opi.stop_remote(), timeout=15.0)
            except (asyncio.TimeoutError, Exception) as e:
                log.warning("[on_shutdown] 香橙派远程停止异常: %s", e)
            state.orangepi_manager = None

    # ── MJPEG 同源代理 ──
    # 浏览器 <img> 标签指向 /wl_proxy/ch/N (同源, 不受 6-connection 限制),
    # 上位机透传到香橙派 MJPEG 服务。彻底解决浏览器 HTTP/1.1 并发限制。
    async def _wl_mjpeg_proxy(request: Request):
        sub_path = request.path_params.get("path", "")
        # 香橙派 MJPEG 端点是 /stream/chN (无斜杠), 代理 URL 是 /wl_proxy/ch/N
        # 把 "ch/1" 还原为 "ch1"
        if sub_path.startswith("ch/") and len(sub_path) > 3:
            sub_path = "ch" + sub_path[3:]
        qs = request.url.query  # 透传 ?raw=1 和 cache-bust 参数
        state = get_state()
        upstream = (
            f"http://{state.water_level_orangepi_ip}:"
            f"{state.water_level_stream_port}/stream/{sub_path}"
        )
        if qs:
            upstream += f"?{qs}"
        # ★ 诊断日志: 记录每次代理转发 (含 debug/raw 参数透传)
        log.info("[MJPEG-PROXY] %s → %s (qs=%r)", request.url.path, upstream, qs)
        async def _stream():
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(600.0, connect=5.0),
                ) as client:
                    async with client.stream("GET", upstream) as resp:
                        if resp.status_code != 200:
                            return
                        async for chunk in resp.aiter_bytes(65536):
                            yield chunk
            except (asyncio.CancelledError, GeneratorExit):
                return
            except Exception as e:
                log.debug("[MJPEG] 流 %s 终止: %s", upstream, e)
        return StreamingResponse(
            _stream(),
            media_type="multipart/x-mixed-replace; boundary=MJPEGBOUNDARY",
            status_code=200,
        )

    nicegui_app.add_route(
        "/wl_proxy/{path:path}",
        _wl_mjpeg_proxy,
        methods=["GET"],
    )

    @ui.page("/")
    def index():
        _build_page()

    # ── Ctrl+C 看门狗 ──
    # uvicorn graceful shutdown 在有活跃 MJPEG 代理流时会挂起
    # （Starlette BaseHTTPMiddleware 的 memory stream 未正确关闭）。
    # 收到 SIGINT 后先同步清理 MQTT，3 秒仍未退出则 force_cleanup + os._exit。
    def _sigint_watchdog(prev_handler):
        # 同步强制清理 MQTT（在 os._exit 前最后手段）
        wl = state.water_level_client
        if wl is not None:
            try:
                wl.force_cleanup()
            except Exception:
                pass

        loop = asyncio.get_event_loop()
        loop.call_later(3, lambda: os._exit(1))
        if callable(prev_handler) and prev_handler not in (signal.SIG_DFL, signal.SIG_IGN):
            prev_handler(signal.SIGINT, None)

    _prev_sigint = signal.signal(signal.SIGINT, lambda *_: _sigint_watchdog(_prev_sigint))

    ui.run(
        host=host,
        port=port,
        title="pTLC 工作站",
        reload=False,
        show=False,   # 不自动打开浏览器（便于移动端手动访问）
    )


# ──────────────────────────────────────────────────────────────────────
# 轮询回退循环（与 header.py 中的 _poll_loop 相同）
# ──────────────────────────────────────────────────────────────────────

async def _poll_loop(vm: VariableMonitor, plc: PLCClient, state) -> None:
    """轮询回退：每 500ms 通过 PLCClient 主动读取所有变量，更新快照和 state。

    同步全部 polled 变量到 vm.snapshot（不再仅限于 MONITORED_VARS），
    确保 guarded_write / extend_subscription 等读 vm.snapshot 的逻辑看到完整数据。
    """
    while True:
        await asyncio.sleep(0.5)
        try:
            polled = await plc.poll_snapshot()
            if not polled:
                continue
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
            state.variable_snapshot.update(polled)
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.debug("[PollLoop] 轮询失败: %s", e)
