"""Develop Stage - 电平范式（协议 v1.3 / 多通道展开 Phase 1）

契约：docs/PLC_Unified_Stage_Protocol.md v1.3
流程（4阶段）：
    Phase 1: allocate tank + start_stage('Expand') → await_stage_done
             prep 完成（Expand_Done=TRUE），目标缸进入 Tank_State=40（Developing）
    Phase 2: 等待排液触发（可中断）
             - 超时自动触发：develop_duration_min 到期后自动 set drain_event
             - 手动提前触发：外部调用 trigger_early_drain()（Debug 按钮 / 未来视觉模块）
    Phase 3: trigger_drain(tank_id) → await_drain_done — 排液
    Phase 4: release_tank(tank_id) — 释放缸，Tank_State[tank_id]=0

变量语义（v1.3）：
    Expand_Mode_Flag       0=缸模式润洗, 1=管路模式润洗（仅影响 step 10）
    Expand_Target_Tank     目标缸号 (1-8)，PC 写入，PLC 自动推导 Group/Number
    Expand_forward_instructions  注射泵转发指令字符串
    Expand_rinse_count     润洗注射泵重复执行次数（Step 10）
    Expand_up_liquid_count 上液注射泵重复执行次数（Step 20）
    Tank_State[1..8]       每缸状态 {0,10,40,50,99,90}
    Tank_Drain_Enable[i]   per-tank 排液触发
    Tank_Drain_Done[i]     per-tank 排液完成锁存

子步 {0,10,20,30,40,50,55,60,65,90}：
    0  idle           空闲
    10 rinse          润洗/清洗（互斥：缸模式 vs 管路模式）
    20 up_liquid      上液（展开剂加入展缸）
    30 silica_plate   放硅胶板
    40 deliver        交付至展开态（prep 完成，序列器释放）
    50 drain          排液（Phase A：排液阀+真空泵）
    55 blow_air       吹气清扫（Phase B：追加吹气阀）
    60 cylinder       气缸退回（Phase C：关阀+气缸复位）
    65 robot_pickup   机器人取板（Phase D：电平握手，串行）
    90 error          故障
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, TYPE_CHECKING

from core import flow_events as fe
from scripts.develop_pump_translator import translate_develop_params
from core.stages.base import StageExecutor

if TYPE_CHECKING:
    from core.resource_manager import ResourceManager

log = logging.getLogger(__name__)

# 子步编号 → (英文键, 中文标签)；与契约 v1.3 对齐
# 注：55/60/65 为 PLC 排液内部子状态，PC 侧 await_drain_done 仅轮询 Drain_Done，
#     不主动读取 Tank_State 中间值；此处定义供 Flow 工位卡片显示和未来轮询增强使用
DEVELOP_SUB_STEPS: dict[int, tuple[str, str]] = {
    0:  ("idle",          "空闲"),
    10: ("rinse",         "润洗/清洗"),
    20: ("up_liquid",     "上液"),
    30: ("silica_plate",  "放硅胶板"),
    40: ("deliver",       "交付至展开态"),
    50: ("drain",         "排液"),
    55: ("blow_air",      "吹气清扫"),
    60: ("cylinder",      "气缸退回"),
    65: ("robot_pickup",  "机器人取板"),
    90: ("error",         "故障"),
}


def _is_cylinder_mode(params: dict) -> bool:
    return str(params.get("rinse_mode", "cylinder")).lower() == "cylinder"


def _is_line_mode(params: dict) -> bool:
    return str(params.get("rinse_mode", "cylinder")).lower() == "line"


class DevelopStage(StageExecutor):
    NAME = "develop"
    PLC_NAME = "Expand"     # PLC Host_Computer 变量前缀（实机命名）
    STAGE_TIMEOUT = 600.0   # prep 序列含润洗/上液多次泵操作，实机可超 300s

    # ── 并发互斥锁（类级属性，所有实例共享） ──
    _prep_lock: asyncio.Lock = asyncio.Lock()          # 全局：Expand FSM 串行化
    _group_locks: dict[int, asyncio.Lock] = {          # 组级：上液阶段注射泵互斥（排液不持）
        1: asyncio.Lock(),   # Group 1: Tank 1-4
        2: asyncio.Lock(),   # Group 2: Tank 5-8
    }

    @staticmethod
    def _tank_group(tank_id: int) -> int:
        """根据缸号推导所属泵组（1-4→Group1, 5-8→Group2）。"""
        return (tank_id - 1) // 4 + 1

    PARAMS_SCHEMA = {
        "rinse_mode": {
            "type": "select", "default": "cylinder",
            "options": ["cylinder", "line"],
            "label": "润洗模式（互斥）", "step_label": "润洗",
        },
        "target_tank": {
            "type": "int", "default": 1, "min": 1, "max": 8,
            "label": "目标缸号(1-8)", "step_label": "润洗",
        },
        "solvent_volume_ml": {
            "type": "float", "default": 2.0, "min": 0.0, "max": 25.0,
            "label": "展开剂总体积(mL)", "step_label": "上液",
        },
        "solvent_ratio_1": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 100.0,
            "label": "溶剂1比例", "step_label": "上液",
        },
        "solvent_ratio_2": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 100.0,
            "label": "溶剂2比例", "step_label": "上液",
        },
        "solvent_ratio_3": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 100.0,
            "label": "溶剂3比例", "step_label": "上液",
        },
        "solvent_ratio_4": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 100.0,
            "label": "溶剂4比例", "step_label": "上液",
        },
        "solvent_ratio_5": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 100.0,
            "label": "溶剂5比例", "step_label": "上液",
        },
        "develop_duration_min": {
            "type": "float", "default": 1.0, "min": 0.1, "max": 120.0,
            "label": "展开时间(分钟)", "step_label": "展开",
        },
        "rinse_repeat_count": {
            "type": "int", "default": 1, "min": 1, "max": 20,
            "label": "润洗重复次数", "step_label": "润洗",
        },
        "up_liquid_repeat_count": {
            "type": "int", "default": 1, "min": 1, "max": 20,
            "label": "上液重复次数", "step_label": "上液",
        },
    }

    # ------------------------------------------------------------------
    # 静态参数校验（覆盖基类）
    # ------------------------------------------------------------------

    @classmethod
    def validate_params(cls, params: dict) -> list[str]:
        """覆盖基类：在 SCHEMA 校验之上补充展开业务约束。

        业务约束：5 个溶剂比例之和必须 > 0（全 0 会导致上液路径为空）。
        """
        errors = super().validate_params(params)
        params = params or {}
        ratios: list[float] = []
        for i in range(1, 6):
            key = f"solvent_ratio_{i}"
            raw = params.get(key, cls.PARAMS_SCHEMA[key]["default"])
            try:
                ratios.append(float(raw))
            except (TypeError, ValueError):
                # 类型错误 super() 已报，此处以 0 占位避免再炸
                ratios.append(0.0)
        if sum(ratios) <= 0:
            errors.append(
                f"[{cls.NAME}] 展开溶剂配比全为 0，无法上液（solvent_ratio_1..5 之和必须 > 0）"
            )
        return errors

    # 协议 v1.3：翻译后的 PLC 变量名映射
    # Expand_Group / Expand_Number 不再由上位机写入
    PARAM_CHANNEL_MAP = {
        "Expand_Mode_Flag":               "Expand_Mode_Flag",
        "Expand_Target_Tank":             "Expand_Target_Tank",
        "Expand_forward_instructions":     "Expand_forward_instructions",
        "Expand_rinse_count":              "Expand_rinse_count",
        "Expand_up_liquid_count":          "Expand_up_liquid_count",
    }

    def __init__(
        self,
        plc,
        log_store,
        params: dict,
        sample_id: str,
        action_timeout: float = 30.0,
        resource_manager: Optional[ResourceManager] = None,
    ) -> None:
        super().__init__(plc, log_store, params, sample_id, action_timeout)
        self._resource_manager = resource_manager
        # Phase 2 可中断排液等待事件：超时自动 set / 外部 trigger_early_drain() set
        self._drain_event: Optional[asyncio.Event] = None
        # Phase 2 旁路检测：外部直接写 PLC 触发排液（绕过 trigger_early_drain）时置 True
        self._external_drain_detected: bool = False
        # Phase 4 handoff：交付给 RecipeTask 在 ScrapeStage._scrape_lock 内释放的缸号。
        # 语义：Drain_Done=TRUE 后物理上硅胶板仍在缸中，只有 RecipeTask 拿到
        # _scrape_lock（拍照刮板工位就绪）那一刻才是机器人取走板的逻辑完成点。
        self.pending_handoff_tank_id: Optional[int] = None

    def trigger_early_drain(self) -> bool:
        """外部触发提前排液（Debug 按钮 / 未来视觉模块）。

        仅在 Phase 2（展开等待）期间有效。
        Returns True: 成功中断等待; False: 当前不在 Phase 2 或已被触发。
        """
        if self._drain_event is not None and not self._drain_event.is_set():
            log.info("[Develop %s] 外部触发提前排液", self._sample_id)
            self._drain_event.set()
            return True
        return False

    @property
    def is_waiting_drain(self) -> bool:
        """当前是否处于 Phase 2 展开等待（可被 trigger_early_drain 中断）。"""
        return (
            self._drain_event is not None
            and not self._drain_event.is_set()
        )

    def translate_params(self, params: dict) -> dict:
        """将用户友好参数翻译为 PLC 可用参数。

        映射逻辑（v1.3）：
          rinse_mode="cylinder" → Expand_Mode_Flag=0
          rinse_mode="line"     → Expand_Mode_Flag=1
          target_tank            → Expand_Target_Tank（PLC 自动推导 Group/Number）
          solvent_ratio_1~5 + solvent_volume_ml
              → Expand_forward_instructions (注射泵转发指令)
        """
        rinse_mode = str(params.get("rinse_mode", "cylinder"))
        target_tank = int(params.get("target_tank", 1))
        expand_group = (target_tank - 1) // 4 + 1  # 仅用于泵地址推导
        total_volume = float(params.get("solvent_volume_ml", 0))
        rinse_repeat_count = int(params.get("rinse_repeat_count", 1))
        up_liquid_repeat_count = int(params.get("up_liquid_repeat_count", 1))

        # 5 通道比例 → 注射泵转发指令
        ratios = [
            float(params.get(f"solvent_ratio_{i}", 0))
            for i in range(1, 6)
        ]

        return translate_develop_params(
            ratios=ratios,
            total_volume_ml=total_volume,
            rinse_mode=rinse_mode,
            expand_group=expand_group,
            target_tank=target_tank,
            rinse_repeat_count=rinse_repeat_count,
            up_liquid_repeat_count=up_liquid_repeat_count,
        )

    async def run(self) -> None:
        """展开流程（v1.3 四阶段）：
        Phase 1: allocate + start_stage → await_stage_done（prep 完成）
        Phase 2: 可中断等待（超时自动排液 / 外部提前触发排液）
        Phase 3: trigger_drain → await_drain_done（排液）
        Phase 4: release_tank（释放缸）

        try/finally 保证：CancelledError 传播时 Phase 4 展缸仍被释放（asyncio.shield），
        避免任务取消后展缸在 ResourceManager 中永久占用。
        """
        channels = self.translate_params(self._params)
        target_tank = int(self._params.get("target_tank", 1))
        develop_duration_min = float(self._params.get("develop_duration_min", 1.0))
        allocated_tank: Optional[int] = None  # 追踪 RM 分配的缸号，供 finally 保底释放

        try:
            # ── Phase 1: 分配展缸 + 启动 prep ──
            # Step 1: 先分配展缸（确定实际缸号和组，再获取对应组锁——避免 GroupLock 错配）
            if self._resource_manager is not None:
                preferred = int(self._params.get("target_tank", 1))
                allocated_tank = await self._resource_manager.allocate(
                    self._sample_id, preferred_tank=preferred,
                )
                if allocated_tank != preferred:
                    log.warning(
                        "[Develop %s] 指定缸 %d 不可用，降级分配缸 %d",
                        self._sample_id, preferred, allocated_tank,
                    )
                    self._log.append(
                        self._sample_id, fe.STEP_START,
                        fe.fmt_detail(
                            stage=self.NAME, action_id=0,
                            label=f"展缸降级: 指定{preferred}→分配{allocated_tank}",
                        ),
                    )
                    # 降级到不同组 → 重算 channels（泵地址需匹配实际缸号）
                    channels = self.translate_params(
                        {**self._params, "target_tank": allocated_tank},
                    )
                target_tank = allocated_tank
                log.info(
                    "[Develop %s] 展缸分配: tank=%d (preferred=%d)",
                    self._sample_id, target_tank, preferred,
                )
            target_group = self._tank_group(target_tank)

            # Step 2: 持双锁启动 prep（prep_lock: Expand FSM 串行, group_lock: 流路互斥）
            log.info(
                "[Develop %s] Phase 1 获取锁: prep_lock + group%d_lock (tank=%d)",
                self._sample_id, target_group, target_tank,
            )
            async with DevelopStage._prep_lock:
                async with DevelopStage._group_locks[target_group]:
                    # group_lock 范围仅覆盖 prep（Step 10/20/30：润洗上液放板）——同组 4 缸
                    # 共享 1 台注射泵，所以同组上液必须串行。排液 (Phase 3) 不持此锁，
                    # 因为每缸出口二通阀独立、真空废液瓶提供稳态负压，多缸可并行。
                    self._emit_stage_start()  # 方案A：持双锁后才标记工位为 running
                    t0 = time.monotonic()
                    last_code: list[int | None] = [None]
                    last_start_ts: list[float | None] = [None]

                    async def _on_step_change(code: int) -> None:
                        prev = last_code[0]
                        if prev is not None and prev in DEVELOP_SUB_STEPS and prev not in (0, 90):
                            dur = int((time.monotonic() - (last_start_ts[0] or t0)) * 1000)
                            self._log.append(
                                self._sample_id, fe.STEP_DONE,
                                fe.fmt_detail(stage=self.NAME, action_id=prev, duration_ms=dur),
                            )
                        if code in DEVELOP_SUB_STEPS and code not in (0,):
                            _, label = DEVELOP_SUB_STEPS[code]
                            self._log.append(
                                self._sample_id, fe.STEP_START,
                                fe.fmt_detail(stage=self.NAME, action_id=code, label=label),
                            )
                            last_start_ts[0] = time.monotonic()
                            log.info("[Develop %s] 子步 → %d (%s)", self._sample_id, code, label)
                        last_code[0] = code

                    log.info(
                        "[Develop %s] start_stage tank=%d channels=%s",
                        self._sample_id, target_tank, channels,
                    )
                    await self._plc.start_stage(self.PLC_NAME, channels)

                    # prep 阶段：等待 Step 10→20→30→40，Expand_Done=TRUE 表示 prep 完成
                    await self._plc.await_stage_done(
                        self.PLC_NAME, on_step_change=_on_step_change, timeout=self.STAGE_TIMEOUT,
                    )
            # Phase 1 完成：prep_lock + group_lock 已释放

            # ── Phase 2: 可中断等待排液触发 ──
            develop_seconds = develop_duration_min * 60.0
            log.info(
                "[Develop %s] 进入展开等待: tank=%d, duration=%.1fmin (%.0fs) 或外部触发",
                self._sample_id, target_tank, develop_duration_min, develop_seconds,
            )
            self._log.append(
                self._sample_id, fe.STEP_START,
                fe.fmt_detail(stage=self.NAME, action_id=40, label="展开等待"),
            )
            # 创建排液事件 + 超时自动触发协程 + Tank_State 旁路检测协程
            self._drain_event = asyncio.Event()
            self._external_drain_detected = False

            async def _auto_drain_after_timeout():
                await asyncio.sleep(develop_seconds)
                if not self._drain_event.is_set():
                    log.info(
                        "[Develop %s] 展开时间到期，自动触发排液", self._sample_id,
                    )
                    self._drain_event.set()

            async def _poll_external_drain():
                """旁路检测：外部直接写 Tank_Drain_Enable 绕过 trigger_early_drain 时，
                通过轮询 Tank_State 变化感知排液已在进行，提前标记 handoff_pending 防止
                sync_states 产生 WARNING 刷屏。"""
                while not self._drain_event.is_set():
                    await asyncio.sleep(1.0)
                    if self._drain_event.is_set():
                        break
                    try:
                        state_val = await self._plc.read_tank_state(target_tank)
                    except Exception:
                        continue
                    if state_val > 40:  # 40=Developing; >40 意味着排液已开始
                        log.info(
                            "[Develop %s] 检测到外部排液 (Tank_State=%d)，提前标记 handoff",
                            self._sample_id, state_val,
                        )
                        self._external_drain_detected = True
                        if self._resource_manager is not None:
                            await self._resource_manager.mark_handoff_pending(target_tank)
                        self._drain_event.set()
                        break

            wait_t0 = time.monotonic()
            timeout_task = asyncio.create_task(_auto_drain_after_timeout())
            poll_task = asyncio.create_task(_poll_external_drain())
            try:
                await self._drain_event.wait()
            finally:
                timeout_task.cancel()
                poll_task.cancel()
                for t in (timeout_task, poll_task):
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass

            wait_dur_ms = int((time.monotonic() - wait_t0) * 1000)
            self._log.append(
                self._sample_id, fe.STEP_DONE,
                fe.fmt_detail(stage=self.NAME, action_id=40, label="展开等待",
                              duration_ms=wait_dur_ms),
            )

            # ── Phase 3: 触发排液 + 等待排液完成（无锁，per-tank 独立并行） ──
            # 硬件依据：每缸出口有独立二通阀，真空泵→真空废液瓶（缓冲容器，稳态负压），
            # 多缸同时打开二通排液互不干扰；组间/组内均可全部并行。
            log.info("[Develop %s] 触发排液: tank=%d", self._sample_id, target_tank)
            self._log.append(
                self._sample_id, fe.STEP_START,
                fe.fmt_detail(stage=self.NAME, action_id=50, label="排液"),
            )
            drain_t0 = time.monotonic()

            if self._external_drain_detected:
                # 外部已直接写 Tank_Drain_Enable，跳过重复触发
                log.info(
                    "[Develop %s] 外部已触发排液，跳过 trigger_drain", self._sample_id,
                )
            else:
                await self._plc.trigger_drain(target_tank)

            # ── 排液一触发即声明 handoff_pending，关闭 sync_states 误清扫 race window ──
            # 根因：mock 端 _drain_complete 为保证 "Drain_Done=TRUE 时 Tank_State 一定是 99"
            # 必须先写 Tank_State=99 再写 Drain_Done=TRUE，两次写入之间存在数十毫秒窗口；
            # 若该窗口内 sync_states 周期扫描发现 Tank_State=99 且 handoff_pending=False，
            # 旧实现会误判为 "含残留绑定" 触发 release_tank → 写 Drain_Enable=FALSE →
            # mock 端清 Drain_Done=FALSE → DevelopStage await_drain_done 永远等不到 Done。
            # 前移到此处后，handoff_pending 覆盖整段 排液中→DONE→RecipeTask 接管，
            # sync_states 永远不会在正常路径中触碰本缸，竞态在源头消除。
            # 语义扩展：handoff_pending = "develop 阶段已结束，缸进入 handoff 流程"
            # （旧语义 "等 RecipeTask 接管" 是其子集）。
            # 注：若 _external_drain_detected=True，handoff_pending 已在 _poll_external_drain 中标记。
            if self._resource_manager is not None and not self._external_drain_detected:
                await self._resource_manager.mark_handoff_pending(target_tank)

            await self._plc.await_drain_done(target_tank, timeout=300.0)
            drain_dur = int((time.monotonic() - drain_t0) * 1000)
            self._log.append(
                self._sample_id, fe.STEP_DONE,
                fe.fmt_detail(stage=self.NAME, action_id=50, label="排液",
                              duration_ms=drain_dur),
            )

            # ── Phase 4: 交付展缸给 RecipeTask 释放 ──
            # 物理依据：Drain_Done=TRUE 仅表示 PLC 排液 FSM 到达 state=99，但物理上硅胶板
            # 还在缸中等待机器人取走送至拍照刮板工位。在 RecipeTask 拿到
            # ScrapeStage._scrape_lock 之前，展缸不可释放，否则排队样品会被错误分配
            # 到尚未空出的缸，按下一样品的 develop 会在同一缸里放新硅胶板，与原板冲突。
            #
            # 方案：
            #   * 有 ResourceManager：handoff_pending 已在 Phase 3 trigger_drain 后声明，
            #     此处仅暴露 pending_handoff_tank_id 给 RecipeTask 在
            #     "async with ScrapeStage._scrape_lock" 内第一时间 release()。
            #   * 无 ResourceManager（collect-only 调试路径等）：直接写 PLC release_tank()。
            if self._resource_manager is not None:
                self._log.append(
                    self._sample_id, fe.STEP_START,
                    fe.fmt_detail(stage=self.NAME, action_id=60,
                                  label="等待拍照刮板工位接管"),
                )
                self.pending_handoff_tank_id = target_tank
                allocated_tank = None  # 跳过 finally 兜底释放，释放权交给 RecipeTask
                self._log.append(
                    self._sample_id, fe.STEP_DONE,
                    fe.fmt_detail(stage=self.NAME, action_id=60,
                                  label="等待拍照刮板工位接管",
                                  duration_ms=0),
                )
                log.info(
                    "[Develop %s] 展缸 handoff: tank=%d 交付 RecipeTask 在 scrape_lock 内释放",
                    self._sample_id, target_tank,
                )
            else:
                self._log.append(
                    self._sample_id, fe.STEP_START,
                    fe.fmt_detail(stage=self.NAME, action_id=60, label="释放资源"),
                )
                release_t0 = time.monotonic()
                await self._plc.release_tank(target_tank)
                release_dur = int((time.monotonic() - release_t0) * 1000)
                self._log.append(
                    self._sample_id, fe.STEP_DONE,
                    fe.fmt_detail(stage=self.NAME, action_id=60, label="释放资源",
                                  duration_ms=release_dur),
                )
                log.info("[Develop %s] 展缸已释放(直接): tank=%d", self._sample_id, target_tank)

        finally:
            # 保底释放：CancelledError / 异常传播时确保展缸归还
            if allocated_tank is not None and self._resource_manager is not None:
                # E-Stop 路径：标记 NEEDS_DRAIN，等待 Recovery UI 强制排液后才能重用
                from core.estop import is_estop_active
                needs_drain = is_estop_active()
                if needs_drain:
                    log.warning(
                        "[Develop %s] E-Stop 路径，展缸标记 NEEDS_DRAIN: tank=%d",
                        self._sample_id, allocated_tank,
                    )
                else:
                    log.warning(
                        "[Develop %s] 异常路径保底释放展缸: tank=%d",
                        self._sample_id, allocated_tank,
                    )
                try:
                    # asyncio.shield 防止 release 本身被取消，保证 RM 状态一致性
                    await asyncio.shield(
                        self._resource_manager.release(
                            allocated_tank,
                            mark_needs_drain=needs_drain,
                        )
                    )
                except asyncio.CancelledError:
                    # shield 保证 release() 在后台继续执行，本任务被取消
                    pass
                except Exception:
                    log.error(
                        "[Develop %s] 保底释放失败: tank=%d",
                        self._sample_id, allocated_tank, exc_info=True,
                    )
