"""离线: parallel_v1 配方契约 (真配置全链静态校验).

覆盖:
    1. 配方可加载, 全部段脚本存在且 validate_script + validate_flow (R1-R3) 全绿
    2. 位置连续性: feedlift -> spot_seat -> scrape_table -> tank -> scrape_table -> waste
    3. s6 展开等待段: 根资源为空, 全部 develop.drain 都在 with_resources [station:develop] 区间内
    4. 并行结构: s3 与 s2 无相互依赖 (可并行), s7 与 s6 无相互依赖 (可并行)
    5. 工位执行段 (s2/s6/s9) 不占 robot
    6. flowspec 的 STATION_RESOURCE 与资源表互验

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_recipe_contract_offline.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.operation.flowspec import check_station_map  # noqa: E402
from eit_ptlc.operation.recipe import load_recipe, topo_order, transitive_deps, validate_recipe  # noqa: E402
from eit_ptlc.operation.resources import load_resource_specs  # noqa: E402

_CFG = _PKG / "config"
_OP_DIR = _CFG / "operation"
_RECIPE = _CFG / "recipes" / "parallel_v1.yaml"


def _script_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for path in _OP_DIR.rglob("*.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("name"):
            index[doc["name"]] = doc
    return index


class RecipeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_CFG / "actions")
        specs = load_resource_specs(_CFG / "resources.yaml")
        cls.modes = {rid: s.mode for rid, s in specs.items()}
        cls.index = _script_index()
        cls.recipe = load_recipe(_RECIPE)

    def _resolve(self, name: str) -> dict:
        try:
            return self.index[name]
        except KeyError as exc:
            raise KeyError(f"缺脚本 {name}") from exc

    def test_station_map_matches_resource_table(self) -> None:
        self.assertEqual(check_station_map(self.modes), [])

    def test_recipe_validates_clean(self) -> None:
        errors = validate_recipe(self.recipe, resolve=self._resolve,
                                 registry=self.registry, resource_modes=self.modes)
        self.assertEqual(errors, [], "parallel_v1 全链静态校验必须零错误:\n" + "\n".join(errors))

    def test_position_trajectory(self) -> None:
        """位移段链: feedlift -> spot_seat -> scrape_table -> tank -> scrape_table -> waste."""
        chain = []
        for f in topo_order(self.recipe):
            if f.scope != "sample":
                continue
            flow = self._resolve(f.script).get("flow") or {}
            frm, to = flow.get("from"), flow.get("to")
            if frm != to and frm not in ("same", "none"):
                chain.append((f.id, frm, to))
        self.assertEqual(
            [(c[1], c[2]) for c in chain],
            [("feedlift", "spot_seat"), ("spot_seat", "scrape_table"),
             ("scrape_table", "tank:{tank}"), ("tank:{tank}", "scrape_table"),
             ("scrape_table", "waste")])

    def test_develop_wait_holds_nothing_and_drains_in_regions(self) -> None:
        doc = self._resolve("pf_s6_develop_wait")
        self.assertEqual(doc.get("resources"), [], "s6 根资源必须为空 (8 缸并行前提)")

        drains_outside: list[str] = []

        def walk(nodes, inside_region: bool) -> None:
            for n in nodes or []:
                if not isinstance(n, dict):
                    continue
                if n.get("op") == "call" and n.get("action") == "develop.drain":
                    if not inside_region:
                        drains_outside.append(n.get("action"))
                if n.get("op") == "with_resources":
                    covered = "station:develop" in (n.get("resources") or [])
                    walk(n.get("body") or [], inside_region or covered)
                    continue
                for key in ("then", "else", "body", "finally"):
                    if n.get(key):
                        walk(n[key], inside_region)
                for br in n.get("elifs") or []:
                    walk(br.get("body") or [], inside_region)
                for h in n.get("catch") or []:
                    walk(h.get("body") or [], inside_region)
                for br in n.get("branches") or []:
                    walk(br, inside_region)

        walk(doc.get("body") or [], False)
        self.assertEqual(drains_outside, [], "全部 develop.drain 必须包在 station:develop 区间内")

    def test_parallel_structure(self) -> None:
        closure = transitive_deps(self.recipe)
        self.assertNotIn("s2", closure["s3"], "s3 缸预备不得依赖 s2 点样 (设计为并行)")
        self.assertNotIn("s3", closure["s2"])
        self.assertNotIn("s6", closure["s7"], "s7 备耗材不得依赖 s6 展开等待 (设计为重叠)")
        self.assertNotIn("s7", closure["s6"])
        # 汇合点: s5 须同时依赖 s3/s4; s9 须同时依赖 s7/s8
        self.assertIn("s3", closure["s5"])
        self.assertIn("s4", closure["s5"])
        self.assertIn("s7", closure["s9"])
        self.assertIn("s8", closure["s9"])

    def test_station_phases_do_not_hold_robot(self) -> None:
        for fid in ("s2", "s6", "s9"):
            script = self.recipe.flow(fid).script
            res = self._resolve(script).get("resources") or []
            self.assertNotIn("robot", res, f"{fid} 是工位执行段, 不得占 robot")
            self.assertNotIn("station:rail", res, f"{fid} 不得占地轨")


if __name__ == "__main__":
    unittest.main()
