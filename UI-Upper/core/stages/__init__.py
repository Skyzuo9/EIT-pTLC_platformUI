"""Stages package - 注册表

STAGE_ORDER：配方里 Stage 的固定顺序（spotting → before_photo → develop → scrape → collect）。
STAGE_REGISTRY：{name: StageExecutor 子类}，由 task.py 分派时查表。
"""

from core.stages.base import StageExecutor
from core.stages.before_photo import BeforePhotoStage
from core.stages.collect import CollectStage
from core.stages.develop import DevelopStage
from core.stages.scrape import ScrapeStage
from core.stages.spotting import SpottingStage

STAGE_ORDER = ["spotting", "before_photo", "develop", "scrape", "collect"]

STAGE_REGISTRY: dict[str, type[StageExecutor]] = {
    "spotting": SpottingStage,
    "before_photo": BeforePhotoStage,
    "develop":  DevelopStage,
    "scrape":   ScrapeStage,
    "collect":  CollectStage,
}

# 锁共享：BeforePhotoStage 与 ScrapeStage 使用同一个 _scrape_lock 实例
# 确保两个阶段对拍照刮板工位硬件的访问串行化
BeforePhotoStage._scrape_lock = ScrapeStage._scrape_lock


def get_stage_cls(name: str) -> type[StageExecutor]:
    if name not in STAGE_REGISTRY:
        raise KeyError(f"未知 Stage 名: {name}（合法：{list(STAGE_REGISTRY)}）")
    return STAGE_REGISTRY[name]


__all__ = [
    "StageExecutor",
    "STAGE_ORDER", "STAGE_REGISTRY", "get_stage_cls",
    "BeforePhotoStage", "SpottingStage", "DevelopStage", "ScrapeStage", "CollectStage",
]
