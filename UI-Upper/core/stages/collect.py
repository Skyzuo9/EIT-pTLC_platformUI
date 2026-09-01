"""Collect Stage - 电平范式（Phase A.1 / 协议 v1.1）

契约：docs/PLC_Unified_Stage_Protocol.md v1.1
流程：
    1. 写业务参数（translate_params 将 volume+channel → DT指令
                     → collect_forward_instructions；
                     liquid_repeat_count   → collect_count）
    2. start_stage('collect')：≥50ms 后置 collect_Enable=TRUE
    3. await_stage_done：轮询 collect_Step/_Done/_Error
    4. 每次子步号变化 → STEP_START/STEP_DONE 事件
    5. _Done=TRUE → 清 collect_Enable，子步回 0
    6. _Error 或 _Step=90 → 抛 RuntimeError

并发安全：
    PLC 收集状态机为单实例（一组 collect_* 变量），
    同一时刻仅允许一个 CollectStage 实例驱动。
    _collect_lock（类级 asyncio.Lock）保证多样品并发时串行访问，
    与 DevelopStage._prep_lock 设计对齐。
"""

from __future__ import annotations

import asyncio
import logging
import time

from core import flow_events as fe
from scripts.collect_pump_translator import translate_collect_cmd
from core.stages.base import StageExecutor

log = logging.getLogger(__name__)

# 子步编号 → (英文键, 中文标签)；与契约 v1.0 对齐
COLLECT_SUB_STEPS: dict[int, tuple[str, str]] = {
    0:  ("idle",       "空闲"),
    10: ("prepare",    "收集准备"),
    20: ("collecting", "收集中"),
    30: ("transfer",   "物料转运"),
    90: ("error",      "故障"),
}


class CollectStage(StageExecutor):
    NAME = "collect"

    # ── 并发互斥锁（类级属性，所有实例共享） ──
    # 收集工位 PLC 状态机为单实例，同一时刻仅允许一个 CollectStage 驱动
    _collect_lock: asyncio.Lock = asyncio.Lock()

    PARAMS_SCHEMA = {
        "solvent_volume_ml": {
            "type": "float", "default": 2.0, "min": 0.0, "max": 25.0,
            "label": "溶剂体积(mL)", "step_label": "收集中",
        },
        "solvent_channel": {
            # 硬件支持通道 1-4；当前工艺默认通道 2。
            "type": "int", "default": 2, "min": 1, "max": 4,
            "label": "溶剂通道号", "step_label": "收集中",
        },
        "liquid_repeat_count": {
            "type": "int", "default": 1, "min": 1, "max": 20,
            "label": "重复打液次数", "step_label": "收集中",
        },
        "powder_return_slot": {
            "type": "int", "default": 0, "min": 0, "max": 6,
            "label": "粉末归还孔位(0=自动推导)", "step_label": "收集准备",
        },
    }

    # 协议 v1.1 §4.3：翻译后的 PLC 变量名映射
    # 翻译流程：solvent_volume_ml + solvent_channel → syringe_forward_cmd(DT指令)
    #            → collect_forward_instructions
    #            liquid_repeat_count → collect_count
    PARAM_CHANNEL_MAP = {
        "syringe_forward_cmd": "collect_forward_instructions",
        "liquid_repeat_count": "collect_count",
    }

    def __init__(
        self,
        *args,
        consumable_manager: object | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        # 耗材管理器（Phase 4 v2.5）。None 时降级跳过耗材决策，兼容遗留调用路径。
        self._cm = consumable_manager

    # 翻译钩子：用户友好参数 → PLC 可用参数
    def translate_params(self, params: dict) -> dict:
        """将 (solvent_volume_ml, solvent_channel) 翻译为 syringe_forward_cmd DT指令。

        同时透传 powder_return_slot（单 collect 流程配方显式指定）。
        返回新 dict，不修改原 params。
        """
        volume = float(params.get("solvent_volume_ml", 0))
        syringe_cmd = translate_collect_cmd(volume)
        return {
            "syringe_forward_cmd": syringe_cmd,
            "liquid_repeat_count": params.get("liquid_repeat_count", 1),
            "powder_return_slot": int(params.get("powder_return_slot", 0)),
        }

    async def run(self) -> None:
        # 先翻译：用户参数 → PLC 可用参数，再按 PARAM_CHANNEL_MAP 映射
        translated = self.translate_params(self._params)
        channels = {
            ch: translated[key]
            for key, ch in self.PARAM_CHANNEL_MAP.items()
            if key in translated
        }

        # 耗材决策（v2.5 动作码）：表示玻璃瓶动作 + 粉末收集器归还孔
        # 关键时序：必须 **先** get_powder_return_slot **再** prepare_for_collect——
        # 后者会用 (_, _, StagingId.B) 覆盖 _decisions[sample_id]
        if self._cm is not None:
            # 粉末归还孔位优先级链：
            # 1. 从 scrape 决策推导（全流程路径）
            powder_slot = await self._cm.get_powder_return_slot(self._sample_id)
            # 2. scrape 未走耗材路径 → 用配方显式值（单 collect 路径）
            if powder_slot == 0:
                powder_slot = int(translated.get("powder_return_slot", 0))
            # 3. 两者都为 0 → 真正的缺失，不可降级
            if powder_slot == 0:
                raise RuntimeError(
                    f"collect: 无粉末归还孔记录 sample={self._sample_id}"
                    "（scrape 未走耗材路径，且配方未指定 powder_return_slot）"
                )
            d = await self._cm.prepare_for_collect(self._sample_id)
            channels.update({
                "collect_Plate_Op":           d.op,
                "collect_Fetch_Rack_Plate":   d.fetch_rack_plate,
                "collect_Old_Plate_Slot":     d.old_plate_slot,
                "collect_Consume_Slot":       d.consume_slot,
                "collect_Powder_Return_Slot": powder_slot,
            })
            log.info(
                "[Collect %s] 耗材决策: op=%d fetch=%d old=%d slot=%d powder_return=%d",
                self._sample_id, d.op, d.fetch_rack_plate,
                d.old_plate_slot, d.consume_slot, powder_slot,
            )
        else:
            log.warning(
                "[Collect %s] consumable_manager 未注入，跳过耗材决策（遗留调用路径）",
                self._sample_id,
            )

        # 持锁驱动 PLC 收集状态机（单实例互斥，与 DevelopStage._prep_lock 对齐）
        # 无锁时并发 CollectStage 实例会互相覆盖参数/Enable 信号/Done 标志
        async with CollectStage._collect_lock:
            self._emit_stage_start()  # 方案A：持锁后才标记工位为 running
            t0 = time.monotonic()
            last_code: list[int | None] = [None]
            last_start_ts: list[float | None] = [None]

            async def _on_step_change(code: int) -> None:
                prev = last_code[0]
                if prev is not None and prev in COLLECT_SUB_STEPS and prev not in (0, 90):
                    dur = int((time.monotonic() - (last_start_ts[0] or t0)) * 1000)
                    self._log.append(
                        self._sample_id, fe.STEP_DONE,
                        fe.fmt_detail(stage=self.NAME, action_id=prev, duration_ms=dur),
                    )
                if code in COLLECT_SUB_STEPS and code not in (0,):
                    _, label = COLLECT_SUB_STEPS[code]
                    self._log.append(
                        self._sample_id, fe.STEP_START,
                        fe.fmt_detail(stage=self.NAME, action_id=code, label=label),
                    )
                    last_start_ts[0] = time.monotonic()
                    log.info("[Collect %s] 子步 → %d (%s)", self._sample_id, code, label)
                last_code[0] = code

            log.info("[Collect %s] start_stage channels=%s", self._sample_id, channels)
            await self._plc.start_stage("collect", channels)
            await self._plc.await_stage_done(
                "collect", on_step_change=_on_step_change, timeout=self.STAGE_TIMEOUT,
            )

            # 成功路径：on_collect_done 把暂存 B 对应孔 TAKEN → FILLED（装样瓶已放回）
            if self._cm is not None:
                try:
                    await self._cm.on_collect_done(self._sample_id)
                except Exception as e:
                    # 不阻断主流程：FILLED 状态可由 UI 手动修正
                    log.warning(
                        "[Collect %s] on_collect_done 异常（已忽略）: %s",
                        self._sample_id, e,
                    )
