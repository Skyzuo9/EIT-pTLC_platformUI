"""
Recipe - Batch 6 配方数据模型
==============================
配方三层：Stage（4 个固定）→ Step（硬编码在 StageExecutor）→ ActionID（PLC 原子动作）。
YAML 只描述 Stage 层的启用与参数集；Step 顺序由 StageExecutor 决定。

数据模型：
    StageParams   : 单个 Stage 的参数（name / enabled / params）
    RecipeTemplate: 一份完整配方（name + 4 个 StageParams）
    RecipeStore   : recipes/*.yaml 的加载 / 保存 / 列表入口

使用：
    store = RecipeStore(Path("recipes"))
    recipe = store.load("standard_pTLC")          # 返回 RecipeTemplate 的新实例（深拷贝安全）
    store.save(recipe)                            # 写入 recipes/<name>.yaml

奥卡姆修订 4：RecipeStore.load() 每次返回深拷贝实例；
Scheduler.enqueue() 会再 deepcopy 一次挂到 SampleRequest，保证并发安全。
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml

from core.stages import STAGE_ORDER, STAGE_REGISTRY

log = logging.getLogger(__name__)


@dataclass
class StageParams:
    """单个 Stage 的 YAML 参数。"""
    name: str
    enabled: bool = True
    params: dict = field(default_factory=dict)


@dataclass
class RecipeTemplate:
    """完整配方模板。stages 顺序与 STAGE_ORDER 保持一致。"""
    name: str
    stages: List[StageParams] = field(default_factory=list)
    # 耗材偏好（Phase 2 数据先行，Phase 4 接入 prepare_for_scrape/collect）
    # {"powder_plate": null|"A".."D", "bottle_plate": null|"E".."H"}
    consumable_preference: dict = field(default_factory=dict)

    def get_stage(self, name: str) -> Optional[StageParams]:
        for s in self.stages:
            if s.name == name:
                return s
        return None


# ---------------------------------------------------------------------- 
# YAML ↔ dataclass
# ---------------------------------------------------------------------- 


def recipe_from_dict(data: dict) -> RecipeTemplate:
    """从 dict（yaml.safe_load 结果）构造 RecipeTemplate，缺失 Stage 用默认参数补齐。"""
    if not isinstance(data, dict):
        raise ValueError(f"recipe 根节点必须是 mapping，得到 {type(data).__name__}")

    name = str(data.get("name") or "unnamed")
    raw_stages = data.get("stages") or []

    # 构建 name -> StageParams 映射（容忍用户未声明的 Stage）
    user_map: dict[str, StageParams] = {}
    for i, item in enumerate(raw_stages):
        if not isinstance(item, dict):
            raise ValueError(f"stages[{i}] 必须是 mapping")
        sname = str(item.get("name") or "").strip()
        if not sname:
            raise ValueError(f"stages[{i}].name 不能为空")
        if sname not in STAGE_REGISTRY:
            raise ValueError(
                f"stages[{i}].name='{sname}' 不在合法 Stage 集合 {list(STAGE_REGISTRY)}"
            )
        user_map[sname] = StageParams(
            name=sname,
            enabled=bool(item.get("enabled", True)),
            params=dict(item.get("params") or {}),
        )

    # 按 STAGE_ORDER 补全；未声明的 Stage 默认 enabled=False（奥卡姆：显式才执行）
    stages: List[StageParams] = []
    for sname in STAGE_ORDER:
        if sname in user_map:
            stages.append(user_map[sname])
        else:
            stages.append(StageParams(name=sname, enabled=False, params={}))

    return RecipeTemplate(
        name=name,
        stages=stages,
        consumable_preference=dict(data.get("consumable_preference") or {}),
    )


def recipe_to_dict(recipe: RecipeTemplate) -> dict:
    """RecipeTemplate → dict（用于 yaml.safe_dump）。只写 enabled=True 的 Stage 也 ok，此处全写便于往返一致。"""
    d = {
        "name": recipe.name,
        "stages": [
            {"name": s.name, "enabled": s.enabled, "params": dict(s.params)}
            for s in recipe.stages
        ],
    }
    if recipe.consumable_preference:
        d["consumable_preference"] = dict(recipe.consumable_preference)
    return d


# ---------------------------------------------------------------------- 
# RecipeStore
# ---------------------------------------------------------------------- 


class RecipeStore:
    """基于文件系统的 Recipe 仓库（recipes/*.yaml）。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def list_names(self) -> list[str]:
        """返回 recipes/ 下所有 *.yaml 的文件名（不含扩展名），按字母序。"""
        return sorted(p.stem for p in self._root.glob("*.yaml"))

    def load(self, name: str) -> RecipeTemplate:
        """加载 recipe；每次返回深拷贝的新实例（修订 4）。"""
        path = self._root / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"recipe 不存在: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        recipe = recipe_from_dict(data)
        # load 层返回深拷贝，避免同一实例被不同调用方意外共享
        return copy.deepcopy(recipe)

    def save(self, recipe: RecipeTemplate) -> Path:
        """把 recipe 写入 recipes/<name>.yaml。"""
        if not recipe.name:
            raise ValueError("recipe.name 不能为空")
        path = self._root / f"{recipe.name}.yaml"
        data = recipe_to_dict(recipe)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        log.info("[RecipeStore] 已保存: %s", path)
        return path

    def save_tmp(self, recipe: RecipeTemplate, sample_id: str) -> Path:
        """把 recipe 快照落盘到 recipes/.tmp/<sample_id>_<YYYYMMDD_HHMMSS>.yaml。

        用于 Queue Tab 入队时将“当前编辑中的配方”临时落盘，
        既可供 Scheduler 读取构造 SampleRequest，也保留可追溯的样品级快照。
        不影响 list_names()（glob 不扫子目录）。
        """
        tmp_dir = self._root / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = tmp_dir / f"{sample_id}_{ts}.yaml"
        data = recipe_to_dict(recipe)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        log.info("[RecipeStore] 临时快照已落盘: %s", path)
        return path


# ---------------------------------------------------------------------- 
# 默认配方（代码级兜底，避免 recipes/ 目录为空时 UI 无 recipe 可选）
# ---------------------------------------------------------------------- 


def default_recipe() -> RecipeTemplate:
    """返回一份内置默认配方（对应 recipes/standard_pTLC.yaml 的默认值）。"""
    stages: List[StageParams] = []
    for sname in STAGE_ORDER:
        stage_cls = STAGE_REGISTRY[sname]
        default_params = {
            key: meta["default"] for key, meta in stage_cls.PARAMS_SCHEMA.items()
        }
        stages.append(StageParams(name=sname, enabled=True, params=default_params))
    return RecipeTemplate(name="standard_pTLC", stages=stages)


# ----------------------------------------------------------------------
# 配方静态校验（提交/保存前统一入口）
# ----------------------------------------------------------------------


def validate_recipe(recipe: Optional[RecipeTemplate]) -> list[str]:
    """静态校验配方：仅针对 enabled=True 的 stage 调用其 validate_params。

    返回错误消息列表（空列表 = 合法）；UI 可一次性并提示。
    不调 PLC、不动调度器，仅依赖 PARAMS_SCHEMA 与各 Stage 自身业务约束。
    """
    if recipe is None:
        return ["recipe 为 None"]

    errors: list[str] = []
    enabled_count = 0
    for sp in recipe.stages:
        if not sp.enabled:
            continue
        enabled_count += 1
        cls = STAGE_REGISTRY.get(sp.name)
        if cls is None:
            errors.append(f"[{sp.name}] Stage 未注册")
            continue
        try:
            stage_errors = cls.validate_params(sp.params or {})
        except Exception as e:  # 防护：子类覆盖意外报错不该能中止调用方
            log.warning(
                "[validate_recipe] %s.validate_params 异常: %s", sp.name, e,
            )
            errors.append(f"[{sp.name}] validate_params 异常: {e}")
            continue
        errors.extend(stage_errors)

    if enabled_count == 0:
        errors.append("配方中没有启用的 Stage，无法执行")
    return errors
