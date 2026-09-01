"""薄层板工艺阶段: 两份里程碑表的漂移看门狗
============================================
功能:
    同一条工艺事实 ("跑完 sampling_execute 这块板就算点过样了") 在本仓有两个观测面:
      · 前端 `twin/bindings/plateTraceState.js` 的 STAGE_MILESTONES —— 从**调度器 jobs**
        推导, 实时页用 (真机有批次跑着时那份账是权威);
      · 后端 `config/material_bindings.yaml` 的 plate_stage 绑定 —— 从**流程完成**推导,
        写进 seat_occupancy.stage, 人工分段跑与仿真沙盒用。

    两份都必须存在 (各自的数据源不同, 合并不了), 于是唯一的防漂手段就是这条测试 ——
    本仓已有先例: plateTraceState.spotBandRegion ↔ clip_compiler._register_spot_region
    也是"一处规则两处实现 + 两侧各挂回归"。改任何一边不改另一边, 这里立刻红。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest \
        eit_ptlc/tests/test_plate_stage_milestones_offline.py -q
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from eit_ptlc.runtime.material_store import PLATE_STAGES, load_bindings, load_topology

_ROOT = Path(__file__).resolve().parents[1]
_BINDINGS = _ROOT / "config" / "material_bindings.yaml"
_TOPOLOGY = _ROOT / "config" / "material_topology.yaml"
_FRONTEND = _ROOT / "web" / "src" / "three-d" / "twin" / "bindings" / "plateTraceState.js"


def _frontend_milestones() -> dict[str, str]:
    """从 plateTraceState.js 里抠出 STAGE_MILESTONES 表 (脚本名 -> 阶段).

    参数:
        无
    返回:
        Dict[str, str]

    用正则读 JS 而不是跑 node: 这条测试要能在纯 Python 环境里跑 (后端 CI 不装 node)。
    表的写法是固定的 `key: STAGE.XXX,`, 变形了这里会抠空并让断言失败 —— 那也是想要的。
    """
    text = _FRONTEND.read_text(encoding="utf-8")
    block = re.search(r"STAGE_MILESTONES = Object\.freeze\(\{(.*?)\}\)", text, re.S)
    if block is None:
        raise AssertionError("plateTraceState.js 里找不到 STAGE_MILESTONES 表")
    return {name: stage.lower()
            for name, stage in re.findall(r"(\w+):\s*STAGE\.(\w+)", block.group(1))}


def _backend_milestones() -> dict[str, str]:
    """从 material_bindings.yaml 里取 plate_stage 绑定 (脚本名 -> 阶段)."""
    doc = yaml.safe_load(_BINDINGS.read_text(encoding="utf-8")) or {}
    return {name: str(spec.get("stage") or "")
            for name, spec in (doc.get("bindings") or {}).items()
            if isinstance(spec, dict) and spec.get("effect") == "plate_stage"}


class TestPlateStageMilestones(unittest.TestCase):
    """两份里程碑表逐条一致 + 词表一致 + 绑定能被加载器接住."""

    def test_tables_agree(self):
        """脚本名与阶段逐条相同 —— 差一条就是两个观测面对同一块板说不同的话."""
        front = _frontend_milestones()
        back = _backend_milestones()
        self.assertTrue(front, "前端表抠空了 (写法变了?)")
        self.assertTrue(back, "后端表是空的")
        self.assertEqual(
            set(front), set(back),
            f"脚本集不一致: 只在前端 {sorted(set(front) - set(back))}; "
            f"只在后端 {sorted(set(back) - set(front))}")
        for script in sorted(front):
            self.assertEqual(front[script], back[script],
                             f"{script} 的阶段两边不一致: 前端 {front[script]} / "
                             f"后端 {back[script]}")

    def test_stage_vocabulary_matches(self):
        """阶段词表三处同源 (后端常量 / 后端绑定取值 / 前端 STAGE)."""
        text = _FRONTEND.read_text(encoding="utf-8")
        block = re.search(r"export const STAGE = Object\.freeze\(\{(.*?)\}\)", text, re.S)
        self.assertIsNotNone(block, "plateTraceState.js 里找不到 STAGE 词表")
        front_values = set(re.findall(r"'(\w+)'", block.group(1)))
        self.assertEqual(front_values, set(PLATE_STAGES),
                         "前端 STAGE 与后端 PLATE_STAGES 词表不一致")

    def test_bindings_load_and_resolve_seats(self):
        """绑定项能被加载器接住, 且座名都在拓扑里 (拼错的座启动就该炸)."""
        topology = load_topology(_TOPOLOGY)
        bindings = load_bindings(_BINDINGS, topology)
        staged = {name: spec for name, spec in bindings.scripts.items()
                  if spec["effect"] in ("plate_stage", "plate_seat")}
        self.assertTrue(staged, "板位/阶段绑定一条都没加载进来")
        for name, spec in staged.items():
            targets = ([spec["seat"]] if spec["seat"]
                       else list(spec["seat_map"].values()))
            for seat in targets:
                self.assertIn(seat, topology.seats, f"{name} 的座 {seat} 不在拓扑里")

    def test_tank_seats_exist(self):
        """8 个展缸位在拓扑里 —— 没有它们, "板在哪个缸"仍然无处表达."""
        topology = load_topology(_TOPOLOGY)
        for index in range(1, 9):
            self.assertIn(f"tank_{index}", topology.seats)


if __name__ == "__main__":
    unittest.main(verbosity=2)
