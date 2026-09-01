#!/usr/bin/env python3
"""运行前旋钮命名唯一性守卫 (跨工位)
=====================================
功能:
    守住 vm/knobs.py 明文写下的寻址契约 —— "覆盖按 var 名寻址 (语义具名): 同名即同一旋钮"。
    collect_knobs 对同名旋钮按首现去重, VmThread._make_frame 又按名把覆盖注入到每一个声明了
    该名的帧。两条合起来意味着: 若两个语义不同的旋钮重名, 面板只显示先被发现的那一个 (另一个
    的 label/默认值/量程被静默吞掉), 而操作员一改它就会跨站串值。

    本测试遍历每个入口 operation 的 run_script 树, 断言树内没有任何旋钮名被两个脚本各声明一次。
    历史事故: develop_prepare 与 sampling_execute 曾共用 rinse_volume_ml (展缸润洗 10 mL vs
    点样针润洗 3 mL), 在 ptlc_full_v2 里互相遮蔽; 已把展缸侧改名为 tank_rinse_volume_ml。

    注意本守卫按"入口树"判定而非全仓判定: 不同入口树之间重名无害 (collect_knobs 一次只走一棵
    树)。故 sampling_prepare 与 sampling_prepare_legacy 各自的 asp_speed/step_delay 允许并存 ——
    二者是同一工位的新旧两版入口, 从不出现在同一棵树里。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_knob_name_collision_offline.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.operation.vm.schema import child_blocks, is_knob_var  # noqa: E402

_OPERATION_DIR = _PKG / "config" / "operation"


def _load_all_docs() -> dict[str, dict]:
    """读取全部 operation 脚本, 返回 {脚本名: 节点树}."""
    docs: dict[str, dict] = {}
    for path in sorted(_OPERATION_DIR.glob("*/*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if doc.get("name"):
            docs[doc["name"]] = doc
    return docs


def _child_scripts(nodes: list) -> list[str]:
    """递归收集一段 body 内全部 run_script 的子脚本名 (含控制流子块)."""
    out: list[str] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if node.get("op") == "run_script" and node.get("script"):
            out.append(node["script"])
        for _name, block in child_blocks(node):
            out.extend(_child_scripts(block))
    return out


def _knob_declarations(entry: str, docs: dict[str, dict]) -> dict[str, list[str]]:
    """静态下钻入口树, 返回 {旋钮名: [声明它的脚本名, ...]}."""
    seen: set[str] = set()
    stack = [entry]
    found: dict[str, list[str]] = {}
    while stack:
        name = stack.pop()
        if name in seen or name not in docs:
            continue
        seen.add(name)
        doc = docs[name]
        for var in doc.get("vars") or []:
            if is_knob_var(var):
                found.setdefault(var["name"], []).append(name)
        stack.extend(_child_scripts(doc.get("body")))
    return found


class KnobNameCollisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.docs = _load_all_docs()
        # 每个脚本都当入口逐一下钻: 运行前旋钮面板对编辑器里打开的任意脚本调 collect_knobs
        # (见 web/src/components/editor/DebugDock.vue 的 loadKnobs), 不限于哪种 ui.role。
        # 早先版本按 ui.role 白名单挑入口, 结果漏掉了 ptlc_full_v2 (它根本没有 ui 块) ——
        # 恰恰是唯一真出过遮蔽的那棵树。改为全量后无白名单可漂移。
        cls.entries = sorted(cls.docs)

    def test_entry_set_covers_real_flows(self) -> None:
        # 守卫本身的自检: 入口集合塌空或漏掉多站配方, 下面的遮蔽检查会静默失效
        self.assertGreater(len(self.entries), 0, "未读到任何 operation 脚本, 检查目录约定")
        for must in ("ptlc_full_v2", "develop_prepare", "sampling_execute"):
            self.assertIn(must, self.entries)

    def test_no_knob_name_shadowing_within_any_entry_tree(self) -> None:
        for entry in self.entries:
            with self.subTest(entry=entry):
                shadowed = {
                    knob: scripts
                    for knob, scripts in _knob_declarations(entry, self.docs).items()
                    if len(scripts) > 1
                }
                self.assertEqual(
                    shadowed, {},
                    f"入口 {entry} 的树内出现同名旋钮: {shadowed}。"
                    f"覆盖按变量名寻址, 同名会被 collect_knobs 静默去重成一个并跨脚本串值; "
                    f"请给其中语义较窄的那个改名 (如加工位前缀)",
                )

    def test_develop_rinse_knob_keeps_station_prefixed_name(self) -> None:
        # 钉死这次修复: 展缸润洗液量不得退回 rinse_volume_ml (该名归 sampling_execute 的点样针润洗)
        prepare = self.docs["develop_prepare"]
        names = {var["name"] for var in prepare.get("vars") or []}
        self.assertIn("tank_rinse_volume_ml", names)
        self.assertNotIn("rinse_volume_ml", names)


if __name__ == "__main__":
    unittest.main()
