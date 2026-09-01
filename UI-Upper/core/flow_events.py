"""
FlowEvents - Batch 6 阶段/子步骤事件常量
==========================================
集中管理 log_store.event 字段的取值，便于 Flow Tab 统一解析。

旧事件（Batch 2-5，向后兼容）：
    ENQUEUED / STATE_CHANGE / VISION_OK / VISION_FAIL
    CONFIRM_CONT / CONFIRM_STOP / DONE / ERROR
    PLC_RECONNECTING / PLC_RECONNECTED / QUEUE_STOPPED / QUEUE_RESUMED

新事件（Batch 6）：
    STAGE_START / STAGE_DONE / STAGE_SKIPPED
    STEP_START  / STEP_DONE / STEP_SKIPPED
    VAR_WRITE         - 受限写入审计

LogEntry.detail 约定（可解析的 key=value 片段）：
    stage=<name> step=<index> action_id=<int> iter=<int>
"""

# 阶段级
STAGE_START   = "STAGE_START"
STAGE_DONE    = "STAGE_DONE"
STAGE_SKIPPED = "STAGE_SKIPPED"

# 子步骤级
STEP_START   = "STEP_START"
STEP_DONE    = "STEP_DONE"
STEP_SKIPPED = "STEP_SKIPPED"   # guard 判定不满足时记一条

# 受限写入审计
VAR_WRITE = "VAR_WRITE"


def fmt_detail(**kwargs) -> str:
    """统一的 detail 格式化：key=value key2=value2 ...（保持人读和机读兼容）。"""
    parts = []
    for k, v in kwargs.items():
        if v is None:
            continue
        parts.append(f"{k}={v}")
    return " ".join(parts)
