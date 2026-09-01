"""全局 UI 状态单例 + 人工确认回调

从 app.py 迁移 AppState dataclass 及 ui_confirm / ui_resume_confirm 回调，
使各 section 模块通过 get_state() 访问共享状态，不反向 import app。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.log_store import LogStore
from core.plc_client import PLCState
from core.recipe import RecipeTemplate
from core.task import SampleTask

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 全局应用状态（单例）
# ──────────────────────────────────────────────────────────────────────

@dataclass
class AppState:
    """调度器与 UI 共享的全局状态单例。"""

    # 运行状态
    plc_connected: bool = False
    plc_state: str = "disconnected"   # PLCState.value
    reconnect_count: int = 0          # PLC 重连次数
    # 当前正在执行的样品 ID 集合（并发安全，替代旧的单值 current_sample）
    active_sample_ids: set = field(default_factory=set)
    scheduler_running: bool = False
    scheduler_done: bool = False
    error_msg: str = ""

    # 样品状态表：sample_id -> "PENDING" / "RUNNING" / "DONE" / "ERROR"
    sample_statuses: dict = field(default_factory=dict)

    # 日志
    log_store: LogStore = field(default_factory=LogStore)

    # 日志持久化（P2-1）：由 _scheduler_background_task 启动后注入
    log_persistence: Optional[Any] = None                # LogPersistence 实例（运行中）
    log_persistence_enabled: bool = True                 # 总开关，可YAML 覆盖
    log_persistence_flush_interval: float = 0.5          # writer flush 周期（秒）
    log_persistence_batch_size: int = 10                 # 单批最大条数
    log_persistence_archive_days: int = 30               # by_date 文件归档阈值（天）

    # 数据库二级索引层：由 _scheduler_background_task 启动后注入
    database: Optional[Any] = None                       # DatabaseService 实例（运行中）
    database_enabled: bool = True                        # 总开关，可 YAML 覆盖
    database_path: str = "data/tlc_data.sqlite"           # DB 文件路径

    # 人工确认桥接（视觉失败）
    confirm_sample_id: Optional[str] = None
    confirm_future: Optional[asyncio.Future] = None

    # PLC 重连恢复确认桥接
    resume_future: Optional[asyncio.Future] = None

    # 启动配置（由 run_ui 注入，on_startup 读取）
    startup_requests: list = field(default_factory=list)
    mock_vision: bool = False
    output_dir: Path = field(default_factory=lambda: Path("vision_output"))
    plc_url: str = "opc.tcp://localhost:4840"
    reconnect_wait_timeout: float = 60.0

    # G-code 生成参数（真机标定相关）：由 run_ui 从 config.yaml 注入；
    # None 表示未注入（终端模式 / 极端场景），调用方需使用代码默认值
    gcode_cfg: Optional[Any] = None

    # 视觉姿态归一化参数（从 config.yaml vision 段注入）
    vision_cfg: Optional[Any] = None

    # CNC 主方案路径策略运行时覆盖（Debug Tab CNC 面板下拉设置）。
    # None 表示走 gcode_cfg.path_strategy 默认值；不污染 ScrapeStage 主流程。
    cnc_path_strategy_override: Optional[str] = None

    # Phase E 新增：variable_monitor 数据快照
    variable_snapshot: dict = field(default_factory=dict)

    # Recipe Tab 当前编辑中的配方（供 Queue Tab 入队时作为“临时快照”落盘）
    current_recipe: Optional[RecipeTemplate] = None

    # P2：样品配方快照 sample_id → RecipeTemplate（入队时深拷贝，供队列卡片预览）
    sample_recipes: dict = field(default_factory=dict)

    # 持有 Scheduler 引用（运行时由 app.py 注入），供 UI 入队调用
    scheduler: Optional[Any] = None

    # 调度器懒启动器（由 app.py 在 on_startup 中注入）：
    # 调用后如 scheduler 尚未运行将在后台启动完整调度流程，返回 True 表示本次调用触发了启动
    scheduler_starter: Optional[Any] = None

    # 当前正在运行的 DevelopStage 实例（供 Debug Tab 外部触发排液）
    active_develop_stage: Optional[Any] = None

    # Scheduler 并发任务池中的活跃 DevelopStage 实例（供未来 Flow Tab 展示）
    scheduler_active_stages: dict = field(default_factory=dict)

    # 持有 PLCClient 引用（运行时由 app.py 注入），供 UI 点动 / 受限写入调用
    plc_client: Optional[Any] = None

    # 持有 WaterLevelClient 引用（运行时由 app.py 注入），供 Debug Tab 液位监控
    water_level_client: Optional[Any] = None
    water_level_enabled: bool = False
    water_level_broker_ip: str = ""
    water_level_broker_port: int = 1883
    water_level_stream_port: int = 8080
    water_level_orangepi_ip: str = ""

    # 液位摄像头按需启停: 当前需要 CAPTURE 和 MJPEG 流的通道集合
    water_level_active_channels: set = field(default_factory=set)
    water_level_stream_channels: set = field(default_factory=set)
    water_level_max_active: int = 4   # 最大并发 CAPTURE 通道数 (USB 带宽保护)

    # OrangePiManager 引用（运行时由 app.py 注入），供关闭流程远程停止香橙派脚本
    orangepi_manager: Optional[Any] = None

    # 持有 VariableMonitor 引用（运行时由 app.py / header.py 注入），供 UI 扫描变量调用
    variable_monitor: Optional[Any] = None

    # UI 刷新回调：PLC 状态变化时触发（供 Debug Tab jog_section 等注册）
    _plc_state_callbacks: list = field(default_factory=list)

    # 独立 PLC 连接后台任务引用（由 header 的"连接PLC"按钮创建）
    _standalone_plc_task: Optional[Any] = None

    # P1-1: UI 刷新脏检查缓存（记录上一次刷新的状态快照）
    _ui_refresh_cache: dict = field(default_factory=dict)

    # ResourceManager 引用（运行时由 app.py 注入），供 Recovery UI 查询 NEEDS_DRAIN 缸
    resource_manager: Optional[Any] = None

    # ConsumableManager 引用（运行时由 app.py on_startup 注入），供耗材 Tab / Dashboard 渲染
    consumable_manager: Optional[Any] = None

    # E-Stop 急停状态
    estop_active: bool = False                          # E-Stop 激活标志（供 UI 显示急停指示器）

    # 后台任务通知队列：后台 Task 无法直接 ui.notify()，排队后由 UI timer 消费
    _notification_queue: list = field(default_factory=list)

    # Vision Tab 状态
    sample_store: Optional[Any] = None                       # SampleStore 实例
    vision_current_sample_id: Optional[str] = None           # 当前选中样品
    vision_analysis_result: Optional[Any] = None             # AnalysisResult
    vision_band_selection_mode: str = "manual"               # "auto" / "manual"（默认手动，不预选 band）
    vision_selected_bands: list = field(default_factory=list)  # ["band_01", ...]
    vision_gcode_text: Optional[str] = None        # 别名：ScrapeArrays 参数摘要文本（v2 语义不再是 .gcode文本）
    vision_gcode_path: Optional[Path] = None        # 别名：PNG 预览路径（v2 语义不再是 .gcode路径）
    # v2 (2026-06-07) 字段别名：与上面两个同一件事、同步赋值，语义更准确。
    # 下一轮迭代可移除旧名。
    vision_arrays_summary: Optional[str] = None
    vision_preview_path: Optional[Path] = None
    vision_analyzing: bool = False                            # 分析进行中标志
    vision_band_selection_future: Optional[asyncio.Future] = None  # 乒乓：拍照刮板流程等待用户选 band
    vision_scrape_waiting: bool = False                           # ScrapeStage 正在等待 band 选择
    vision_waiting_sample_id: Optional[str] = None                # 当前等待乒乓的样品（执行流写入；权威字段，用于权限判定）
    vision_scrape_after_path: Optional[Path] = None            # ScrapeStage 推送的 after.jpg 路径
    vision_before_photo_waiting: bool = False                      # BeforePhotoStage 正在执行拍照
    vision_before_photo_path: Optional[Path] = None                # BeforePhotoStage 推送的 before.jpg 路径

    # 历史样品 Tab 状态
    history_filter: dict = field(default_factory=dict)              # 当前筛选条件 {recipe_name, date_from, date_to, id_substring}
    history_selected_ids: set = field(default_factory=set)          # 表格多选状态
    history_compare_ids: list = field(default_factory=list)         # 触发对比时的快照
    history_include_deleted: bool = False                           # 是否显示软删除记录
    compare_active_view: str = "annotated"                          # before/after/annotated（Phase 2 用）


_state: Optional[AppState] = None


def get_state() -> AppState:
    """获取全局状态单例（懒初始化）。"""
    global _state
    if _state is None:
        _state = AppState()
    return _state


def reset_state() -> None:
    """重置全局状态（主要用于测试）。"""
    global _state
    _state = None


# ──────────────────────────────────────────────────────────────────────
# 人工确认回调（供 Scheduler 调用）
# ──────────────────────────────────────────────────────────────────────

async def ui_confirm(task: SampleTask) -> bool:
    """视觉失败时由调度器调用；挂起直到用户点击 UI 按钮。

    返回 True = 继续执行；False = 终止该样品。
    """
    state = get_state()
    loop = asyncio.get_running_loop()
    state.confirm_future = loop.create_future()
    state.confirm_sample_id = task.sample_id
    log.info("[UIConfirm] 等待人工确认，样品: %s", task.sample_id)
    try:
        result = await state.confirm_future
        log.info("[UIConfirm] 用户选择: %s", "继续" if result else "终止")
        return result
    finally:
        state.confirm_sample_id = None
        state.confirm_future = None


def resolve_confirm(value: bool) -> None:
    """UI 按钮点击时调用，向 confirm_future 写入结果。"""
    state = get_state()
    if state.confirm_future is not None and not state.confirm_future.done():
        state.confirm_future.set_result(value)


# PLC 重连恢复确认
async def ui_resume_confirm() -> bool:
    """PLC 重连成功后询问是否继续队列；挂起直到用户点击。"""
    state = get_state()
    loop = asyncio.get_running_loop()
    state.resume_future = loop.create_future()
    log.info("[UIResume] PLC 已重连，等待用户决定是否继续队列")
    try:
        result = await state.resume_future
        log.info("[UIResume] 用户选择: %s", "继续" if result else "停止")
        return result
    finally:
        state.resume_future = None


def resolve_resume(value: bool) -> None:
    """UI 按钮点击时调用，向 resume_future 写入结果。"""
    state = get_state()
    if state.resume_future is not None and not state.resume_future.done():
        state.resume_future.set_result(value)


async def on_plc_state_ui(state: PLCState) -> None:
    """注册到 PLCClient 的状态监听：同步 AppState.plc_state/plc_connected，并触发回调。"""
    s = get_state()
    s.plc_state = state.value
    s.plc_connected = (state == PLCState.CONNECTED)
    # 通知所有注册的 UI 刷新回调（如 jog_section）
    for cb in list(s._plc_state_callbacks):
        try:
            cb()
        except Exception as e:
            log.warning("[AppState] plc_state_callback 异常: %s", e)
