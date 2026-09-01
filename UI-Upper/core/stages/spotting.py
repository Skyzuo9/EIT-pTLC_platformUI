"""Spotting Stage - 电平范式（协议 v1.5 / 上样点样 Phase B2 / v2 空气驱动策略 / 4 数组重构）

契约：docs/PLC_Unified_Stage_Protocol.md v1.5 §6
PLC 变量前缀：Sampling（实机 Host_Computer 命名，对标 develop → Expand）

流程（6 阶段）：
    Step 0:  idle           空闲（等待 Enable=TRUE 启动）
    Step 10: clean          清洗（消费 Sampling_clean_instructions[1..2] + Sampling_clean_count）
    Step 20: prepare        上样准备（消费 Sampling_prep_instructions[1..2]）
    Step 30: silica_plate   放硅胶板（PLC 自治，机器人动作）
    Step 40: sample         上样吸液（消费 Sampling_X/Y_coordinate + Sampling_sample_instructions[1..2]）
    Step 50: spot           点样（消费 Sampling_dispense_instructions[1..2]，完成后 Done=TRUE 回 0）
    Step 90: error          故障（锁存）

参数翻译策略（PC 侧翻译，v2 空气驱动策略 / 4 数组）：
    清洗数组：build_clean_array() → Sampling_clean_instructions [内壁清洗, 外壁清洗]
    上样准备数组：build_prep_array() → Sampling_prep_instructions [吸取空气, 废液打出]
    上样数组：build_sample_array() → Sampling_sample_instructions [回抽样品, 废液排废]
    点样数组：build_dispense_array() → Sampling_dispense_instructions [抽取空气, 打气点样+回抽释压]

v2 空气驱动策略（7 步）：
    Step 1: 清洗（Step 10 消费） — 内壁清洗（吸清洗液→输出口打出）+ 外壁清洗（吸清洗液→废液口打出）
    Step 2: 回抽空气（Step 20）  — 从输出口吸入 air_buffer mL（上样针在空气中，建立隔离段）
    Step 3: 排废液（Step 20）    — 将泵腔内全部从废液口打出（清空泵腔）
    Step 4: 吸取样品（Step 40）  — 从输出口吸入 sample_vol mL（上样针入样品液面）
    Step 5: 排废液（Step 40）    — 将泵腔内全部从废液口打出（清空泵腔）
    Step 6: 点样打出（Step 50）  — 抽取驱动空气 + 从输出口打出，推动管路中样品进入点样流路
    Step 7: 回抽释压（Step 50 复合指令内）— 点样后回抽 ~1mL，释放点样器/公共腔正压，防滴液

并发安全：
    _spotting_lock（类级 asyncio.Lock）保证多样品并发时串行访问 Sampling FSM，
    与 CollectStage._collect_lock / DevelopStage._prep_lock 设计对齐。
"""

from __future__ import annotations

import asyncio
import logging
import time

from core import flow_events as fe
from scripts.sample_pump_translator import (
    SYRINGE_ML,
    SAMPLE_PUMP_ADDR,
)
from scripts.sample_pump_translator_v2 import (
    build_clean_array,
    build_prep_array,
    build_sample_array,
    build_dispense_array,
    DEFAULT_AIR_BUFFER_ML,
    DEFAULT_WASH_ML,
    DEFAULT_DISPENSE_DISP_SPEED,
)
from core.stages.base import StageExecutor

log = logging.getLogger(__name__)

# 子步编号 → (英文键, 中文标签)；与契约 v1.4 对齐
SPOTTING_SUB_STEPS: dict[int, tuple[str, str]] = {
    0:  ("idle",          "空闲"),
    10: ("clean",         "清洗"),
    20: ("prepare",       "上样准备"),
    30: ("silica_plate",  "放硅胶板"),
    40: ("sample",        "上样(吸液)"),
    50: ("spot",          "点样"),
    90: ("error",         "故障"),
}


class SpottingStage(StageExecutor):
    NAME = "spotting"
    PLC_NAME = "Sampling"     # PLC Host_Computer 变量前缀（实机命名，对标 develop → Expand）

    # ── 并发互斥锁（类级属性，所有实例共享） ──
    _spotting_lock: asyncio.Lock = asyncio.Lock()

    PARAMS_SCHEMA = {
        "sample_volume_ml": {
            "type": "float", "default": 5.0, "min": 0.1, "max": 12.0,
            "label": "样品体积(mL)", "step_label": "上样准备",
        },
        "air_buffer_ml": {
            "type": "float", "default": 3.0, "min": 0.1, "max": 10.0,
            "label": "空气隔离段(mL)", "step_label": "上样准备",
        },
        "wash_volume_ml": {
            "type": "float", "default": 25.0, "min": 0.1, "max": 25.0,
            "label": "单次清洗体积(mL)", "step_label": "清洗",
        },
        "source_x": {
            "type": "int", "default": 1, "min": 1, "max": 8,    # 双板并排：板1 X=1..4, 板2 X=5..8
            "label": "料筒孔位 X (列)", "step_label": "上样",
        },
        "source_y": {
            "type": "int", "default": 1, "min": 1, "max": 6,    # 24孔板：行 1..6 (A..F)
            "label": "料筒孔位 Y (行)", "step_label": "上样",
        },
        "cleaning_count": {
            "type": "int", "default": 3, "min": 1, "max": 20,
            "label": "清洗次数", "step_label": "清洗",
        },
    }

    def __init__(
        self,
        plc,
        log_store,
        params,
        sample_id,
        action_timeout=30.0,
        *,
        plc_action_client=None,
        robot_runtime=None,
        robot_resources=None,
        camera=None,
        sample_store=None,
    ) -> None:
        super().__init__(
            plc=plc,
            log_store=log_store,
            params=params,
            sample_id=sample_id,
            action_timeout=action_timeout,
        )
        self._plc_action_client = plc_action_client
        self._robot_runtime = robot_runtime
        self._robot_resources = robot_resources
        self._camera = camera
        self._sample_store = sample_store

    @property
    def l2_enabled(self) -> bool:
        return all(
            item is not None
            for item in (
                self._plc_action_client,
                self._robot_runtime,
                self._robot_resources,
                self._camera,
            )
        )

    def translate_params(self, params: dict) -> dict:
        """将用户友好参数翻译为 PLC 可用参数（4 数组 + 标量通道 dict）。

        基类契约：返回 dict，供 start_stage 使用。
        协议 v1.5：4 个 1×2 STRING 数组 + clean_count + X/Y 坐标标量。
        4 个数组均在 channels dict 内，由 start_stage → write_variable 统一写入
        （NODE_ARRAYS 中声明后自动路由到 _write_array）。

        数组映射：
          清洗（Step 10）：build_clean_array(wash_volume_ml) → [内壁清洗, 外壁清洗]
          上样准备（Step 20）：build_prep_array(sample_vol, air_buffer) → [吸取空气, 废液打出]
          上样（Step 40）：build_sample_array(sample_vol) → [回抽样品, 废液排废]
          点样（Step 50）：build_dispense_array(sample_vol) → [抽取空气, 打气点样]
          坐标：source_x/source_y（孔板索引）直接写入 Sampling_X/Y_coordinate
                物理坐标由 PLC 内部查表映射，上位机只传逻辑索引
        """
        sample_volume_ml = float(params.get("sample_volume_ml", 5.0))
        air_buffer_ml = float(params.get("air_buffer_ml", DEFAULT_AIR_BUFFER_ML))
        wash_volume_ml = float(params.get("wash_volume_ml", DEFAULT_WASH_ML))
        source_x = int(params.get("source_x", 1))
        source_y = int(params.get("source_y", 1))
        cleaning_count = int(params.get("cleaning_count", 3))

        # 4 个 1×2 数组（协议 v1.5）
        clean_array = build_clean_array(wash_volume_ml)
        prep_array = build_prep_array(sample_volume_ml, air_buffer_ml)
        sample_array = build_sample_array(sample_volume_ml)
        dispense_array = build_dispense_array(
            sample_volume_ml,
            dispense_disp_speed=DEFAULT_DISPENSE_DISP_SPEED,
        )

        channels = {
            "Sampling_clean_instructions":       clean_array,
            "Sampling_clean_count":              cleaning_count,
            "Sampling_prep_instructions":        prep_array,
            "Sampling_X_coordinate":             source_x,
            "Sampling_Y_coordinate":             source_y,
            "Sampling_sample_instructions":      sample_array,
            "Sampling_dispense_instructions":    dispense_array,
        }

        log.info(
            "[Spotting] translate_params 完成 (v1.5/4数组): "
            "clean=%d, prep=%d, sample=%d, dispense=%d",
            len(clean_array), len(prep_array),
            len(sample_array), len(dispense_array),
        )
        return channels

    async def run(self) -> None:
        if not self.l2_enabled:
            await self._run_legacy()
            return
        await self._run_l2()

    async def _run_l2(self) -> None:
        from core import flow_events as fe
        from core.plc_action_client import SamplingAction
        from core.robot_route_runtime import execute_route

        channels = self.translate_params(self._params)
        local_actions = (
            (
                SamplingAction.INIT,
                {},
                "Sampling_Init",
            ),
            (
                SamplingAction.CLEAN,
                {
                    "Sampling_clean_instructions":
                        channels["Sampling_clean_instructions"],
                    "Sampling_clean_count":
                        channels["Sampling_clean_count"],
                },
                "Sampling_Clean",
            ),
            (
                SamplingAction.PREPARE_FLUID,
                {
                    "Sampling_prep_instructions":
                        channels["Sampling_prep_instructions"],
                },
                "Sampling_PrepareFluid",
            ),
        )
        post_load_actions = (
            (
                SamplingAction.ASPIRATE_SAMPLE,
                {
                    "Sampling_X_coordinate":
                        channels["Sampling_X_coordinate"],
                    "Sampling_Y_coordinate":
                        channels["Sampling_Y_coordinate"],
                    "Sampling_sample_instructions":
                        channels["Sampling_sample_instructions"],
                },
                "Sampling_AspirateSample",
            ),
            (
                SamplingAction.DISPENSE_SAMPLE,
                {
                    "Sampling_dispense_instructions":
                        channels["Sampling_dispense_instructions"],
                },
                "Sampling_DispenseSample",
            ),
        )

        async with SpottingStage._spotting_lock:
            self._emit_stage_start()
            for action, params, label in local_actions:
                await self._execute_l2_action(action, params, label, fe)
            await self._execute_robot_route(
                "plate.feed-to-spotting", execute_route
            )
            for action, params, label in post_load_actions:
                await self._execute_l2_action(action, params, label, fe)
            await self._execute_robot_route(
                "plate.spotting-to-scrape", execute_route
            )

    async def _execute_l2_action(self, action, params, label, fe) -> None:
        t0 = time.monotonic()
        self._log.append(
            self._sample_id,
            fe.STEP_START,
            fe.fmt_detail(
                stage=self.NAME,
                action_id=int(action),
                label=label,
            ),
        )
        result = await self._plc_action_client.execute(
            "sampling",
            action,
            params,
            timeout=self.STAGE_TIMEOUT,
        )
        self._log.append(
            self._sample_id,
            fe.STEP_DONE,
            fe.fmt_detail(
                stage=self.NAME,
                action_id=int(action),
                duration_ms=int((time.monotonic() - t0) * 1000),
                safe_state=int(result.safe_state),
                physical_confirmation="unverified",
            ),
        )

    async def _execute_robot_route(self, route_id, execute_route) -> None:
        save_dir = (
            self._sample_store.get_sample_dir(self._sample_id)
            if self._sample_store is not None
            else __import__("pathlib").Path("data/samples") / self._sample_id
        )
        plan = self._robot_runtime.route_planner.resolve(route_id, {})
        await execute_route(
            runtime=self._robot_runtime,
            plan=plan,
            plc=self._plc,
            plc_action_client=self._plc_action_client,
            camera=self._camera,
            sample_id=self._sample_id,
            save_dir=save_dir,
            resources=self._robot_resources,
            host_call_timeout_s=self.STAGE_TIMEOUT,
        )

    async def _run_legacy(self) -> None:
        """上样点样流程（电平范式 v1.5 / v2 空气驱动策略 / 4 数组）：
        1. 翻译参数 → channels dict（含 4 个 1×2 数组 + 标量）
        2. start_stage('Sampling', channels) → 写变量 + 置 Enable=TRUE
        3. await_stage_done → 轮询 Step/Done/Error
        4. 完成 → 写 Enable=FALSE
        """
        channels = self.translate_params(self._params)

        # 持锁驱动 PLC 上样点样状态机（单实例互斥）
        async with SpottingStage._spotting_lock:
            self._emit_stage_start()  # 方案A：持锁后才标记工位为 running
            t0 = time.monotonic()
            last_code: list[int | None] = [None]
            last_start_ts: list[float | None] = [None]

            async def _on_step_change(code: int) -> None:
                prev = last_code[0]
                if prev is not None and prev in SPOTTING_SUB_STEPS and prev not in (0, 90):
                    dur = int((time.monotonic() - (last_start_ts[0] or t0)) * 1000)
                    self._log.append(
                        self._sample_id, fe.STEP_DONE,
                        fe.fmt_detail(stage=self.NAME, action_id=prev, duration_ms=dur),
                    )
                if code in SPOTTING_SUB_STEPS and code not in (0,):
                    _, label = SPOTTING_SUB_STEPS[code]
                    self._log.append(
                        self._sample_id, fe.STEP_START,
                        fe.fmt_detail(stage=self.NAME, action_id=code, label=label),
                    )
                    last_start_ts[0] = time.monotonic()
                    log.info("[Spotting %s] 子步 → %d (%s)", self._sample_id, code, label)
                last_code[0] = code

            # 4 个 1×2 数组已在 channels dict 内，start_stage → write_variable 统一写入

            log.info(
                "[Spotting %s] start_stage channels=%s",
                self._sample_id, {k: (f'<list len={len(v)}>' if isinstance(v, list) else v) for k, v in channels.items()},
            )
            await self._plc.start_stage(self.PLC_NAME, channels)
            await self._plc.await_stage_done(
                self.PLC_NAME, on_step_change=_on_step_change, timeout=self.STAGE_TIMEOUT,
            )
