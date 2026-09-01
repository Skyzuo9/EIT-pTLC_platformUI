"""
StageExecutor - Batch 6 阶段执行器基类
========================================
每个 Stage（spotting / develop / scrape / collect / before_photo）继承 StageExecutor，
把 flowchart 里的子流程顺序硬编码在 `run()` 方法里。

协议 v1.1+：参数 → PLC 变量的映射在各 Stage 子类内部就地声明，
不维护全局 ACTION_PARAM_MAP，单一事实源。

约定：
- PARAMS_SCHEMA：UI 表单渲染用；{key: {type, default, min, max, label}}
- run()：子类覆盖，实现工位级业务逻辑（电平范式）
"""

from __future__ import annotations

import asyncio
import logging
import time
from core import flow_events as fe
from core.log_store import LogStore
from core.plc_client import PLCClient

log = logging.getLogger(__name__)



class StageExecutor:
    """Stage 基类。子类需设置 NAME / PLC_NAME / PARAMS_SCHEMA 并实现 run()。"""

    NAME: str = ""
    PLC_NAME: str = ""    # PLC 变量前缀；默认等于 NAME，develop 工位为 "Expand"
    PARAMS_SCHEMA: dict = {}
    STAGE_TIMEOUT: float = 300.0   # 整个工位 await_stage_done 超时（秒），与 action_timeout 解耦

    def __init__(
        self,
        plc: PLCClient,
        log_store: LogStore,
        params: dict,
        sample_id: str,
        action_timeout: float = 30.0,
    ) -> None:
        self._plc = plc
        self._log = log_store
        self._params = params or {}
        self._sample_id = sample_id
        self._timeout = action_timeout

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """子类覆盖：按 flowchart 顺序调用 self._run_step(...)。默认空实现。"""
        raise NotImplementedError

    async def execute(self) -> None:
        """外层包裹：发 STAGE_DONE 事件并捕获异常。

        STAGE_START 不再由此处发出（方案A：延迟到子类 run() 持锁后），
        确保事件流与实际硬件占用对齐——等锁期间不标记工位为 running。

        CancelledError（Python 3.9+ BaseException 子类）不被 except Exception 捕获，
        必须显式处理，否则 STAGE_DONE 事件缺失，导致 StageStateRegistry 工位
        永久卡在 running。
        """
        t0 = time.monotonic()
        try:
            await self.run()
        except asyncio.CancelledError:
            from core.estop import is_estop_active
            status = "ESTOP" if is_estop_active() else "CANCELLED"
            dur = int((time.monotonic() - t0) * 1000)
            self._log.append(
                self._sample_id, fe.STAGE_DONE,
                fe.fmt_detail(stage=self.NAME, status=status, duration_ms=dur),
            )
            raise
        except Exception:
            dur = int((time.monotonic() - t0) * 1000)
            self._log.append(
                self._sample_id, fe.STAGE_DONE,
                fe.fmt_detail(stage=self.NAME, status="ERROR", duration_ms=dur),
            )
            raise
        dur = int((time.monotonic() - t0) * 1000)
        self._log.append(
            self._sample_id, fe.STAGE_DONE,
            fe.fmt_detail(stage=self.NAME, status="OK", duration_ms=dur),
        )

    def _emit_stage_start(self) -> None:
        """发出 STAGE_START 事件。子类应在 run() 持锁后调用（方案A），
        确保事件流与实际硬件占用对齐。
        """
        self._log.append(
            self._sample_id, fe.STAGE_START,
            fe.fmt_detail(stage=self.NAME),
        )

    # ------------------------------------------------------------------
    # 子步骤工具
    # ------------------------------------------------------------------

    def translate_params(self, params: dict) -> dict:
        """将用户友好参数翻译为 PLC 可用参数。

        默认实现为恒等映射（无需翻译）；子类可覆盖。
        约束：必须返回新 dict，禁止就地修改 params。
        """
        return dict(params)

    # ------------------------------------------------------------------
    # 静态参数校验（配方提交/保存前统一调用）
    # ------------------------------------------------------------------

    @classmethod
    def validate_params(cls, params: dict) -> list[str]:
        """根据 PARAMS_SCHEMA 静态校验参数。

        返回错误消息列表（空列表 = 合法）；不抛异常，便于 UI 聚合呈现。
        检查项：
          - 缺项 → 默认值兑底，视为合法（与 RecipeStore.recipe_from_dict 语义一致）
          - type=int    ：需为 int/float（非 bool）且在 [min,max]
          - type=float  ：需为 int/float（非 bool）且在 [min,max]
          - type=str    ：需为 str
          - type=select ：需在 options 中
        子类可覆盖以补充业务约束（如跨 key 关联检查）。
        """
        errors: list[str] = []
        schema = cls.PARAMS_SCHEMA or {}
        params = params or {}
        stage_name = cls.NAME or cls.__name__

        for key, meta in schema.items():
            if key not in params:
                # 缺项 → 默认值兑底，视为合法
                continue
            val = params[key]
            ptype = meta.get("type", "float")
            label = meta.get("label", key)
            prefix = f"[{stage_name}] {key}({label})"

            if ptype == "int":
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    errors.append(
                        f"{prefix}: 类型应为 int，得到 {type(val).__name__}"
                    )
                    continue
                ival = int(val)
                mn, mx = meta.get("min"), meta.get("max")
                if mn is not None and ival < mn:
                    errors.append(f"{prefix}: {ival} 小于下限 {mn}")
                if mx is not None and ival > mx:
                    errors.append(f"{prefix}: {ival} 超过上限 {mx}")
            elif ptype == "float":
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    errors.append(
                        f"{prefix}: 类型应为 number，得到 {type(val).__name__}"
                    )
                    continue
                fv = float(val)
                mn, mx = meta.get("min"), meta.get("max")
                if mn is not None and fv < float(mn):
                    errors.append(f"{prefix}: {fv} 小于下限 {mn}")
                if mx is not None and fv > float(mx):
                    errors.append(f"{prefix}: {fv} 超过上限 {mx}")
            elif ptype in ("str", "string"):
                if not isinstance(val, str):
                    errors.append(
                        f"{prefix}: 类型应为 str，得到 {type(val).__name__}"
                    )
            elif ptype == "select":
                options = list(meta.get("options") or [])
                if options and val not in options:
                    errors.append(
                        f"{prefix}: 值 {val!r} 不在合法选项 {options}"
                    )
            # 其他 type 暂不检查，保留扩展空间
        return errors
