"""离线: 调度方案读/校验/保存面 (前端调度编排器的后端契约) + serial_v1 串行方案契约.

覆盖:
    1. read_recipe_text: 真方案可读、名字非法/不存在拒绝
    2. serial_v1: 真配置全链静态校验零错误; 拓扑序 = af0..s11 全链式 (零可并行段对)
    3. validate_recipe_text/doc 干跑: 好输入 -> (无错, 段DTO); 坏 YAML / 缺脚本 / 成环
       -> 错误清单, 不落盘
    4. save_recipe_text: 校验通过才落盘 + get_recipe 缓存失效; name 不符 400 语义;
       坏文本拒存且文件不动; PUT 新名字=另存为; 非终态批次引用 -> conflict (409 语义)
    5. 结构化 doc 面 (画布主路): read_recipe_doc 的 depends 显式化; doc 往返等价;
       save_recipe_doc 同守卫 (name 不符 / 活跃批次 409 / 缓存失效)

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_recipe_raw_api_offline.py -v
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.operation.recipe import topo_order, transitive_deps  # noqa: E402
from eit_ptlc.operation.resources import load_resource_specs  # noqa: E402
from eit_ptlc.operation.scheduler import FlowScheduler, SubmitError  # noqa: E402
from eit_ptlc.runtime.experiment_store import ExperimentStore  # noqa: E402

_CFG = _PKG / "config"
_OP_DIR = _CFG / "operation"
_REAL_RECIPES = _CFG / "recipes"


def _script_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for path in _OP_DIR.rglob("*.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("name"):
            index[doc["name"]] = doc
    return index


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_CFG / "actions")
        specs = load_resource_specs(_CFG / "resources.yaml")
        cls.modes = {rid: s.mode for rid, s in specs.items()}
        cls.index = _script_index()

    def make_sched(self, recipes_dir: Path, store: ExperimentStore | None = None) -> FlowScheduler:
        # vm/res_gate/material_store 传 None: 配方原文面不触碰派发链路
        return FlowScheduler(
            vm=None, res_gate=None, resolve_script=self.index.__getitem__,
            material_store=None, experiment_store=store or ExperimentStore(":memory:"),
            registry=self.registry, resource_modes=self.modes, recipes_dir=recipes_dir)


class ReadAndSerialContractTest(_Base):
    """真配置只读面: raw 读取 + serial_v1 契约."""

    def setUp(self) -> None:
        self.sched = self.make_sched(_REAL_RECIPES)

    def test_read_real_recipe_text(self) -> None:
        text = self.sched.read_recipe_text("parallel_v1")
        self.assertIn("schema: ptlc.recipe/v1", text)
        self.assertIn("# ", text, "raw 端点必须回原文 (含注释), 不是重序列化")

    def test_read_rejects_bad_names(self) -> None:
        with self.assertRaises(KeyError):
            self.sched.read_recipe_text("no_such_recipe")
        with self.assertRaises(KeyError):
            self.sched.read_recipe_text("../resources")

    def test_serial_v1_validates_clean(self) -> None:
        errors = self.sched.validate_recipe_by_name("serial_v1")
        self.assertEqual(errors, [], "serial_v1 全链静态校验必须零错误:\n" + "\n".join(errors))

    def test_serial_v1_is_pure_chain(self) -> None:
        """全链式 = 拓扑序上每段传递依赖之前全部段 (零可并行段对)."""
        recipe = self.sched.get_recipe("serial_v1")
        order = [f.id for f in topo_order(recipe)]
        self.assertEqual(order, ["af0"] + [f"s{i}" for i in range(1, 12)])
        closure = transitive_deps(recipe)
        for k, fid in enumerate(order):
            self.assertEqual(closure[fid], frozenset(order[:k]),
                             f"段 {fid} 应传递依赖之前全部段 (串行), 实际 {sorted(closure[fid])}")

    def test_validate_text_dry_run(self) -> None:
        good = self.sched.read_recipe_text("serial_v1")
        errors, dto = self.sched.validate_recipe_text(good)
        self.assertEqual(errors, [])
        self.assertEqual(len(dto["segments"]), 12)
        self.assertTrue(all(s["label"] for s in dto["segments"]))

        errors, dto = self.sched.validate_recipe_text("schema: [broken")
        self.assertTrue(errors and dto is None)

        missing = ("schema: ptlc.recipe/v1\nname: t_missing\nflows:\n"
                   "  - id: a\n    script: no_such_script\n    scope: sample\n")
        errors, dto = self.sched.validate_recipe_text(missing)
        self.assertTrue(any("不存在" in e for e in errors))
        self.assertIsNone(dto)

    # ---- 结构化 doc 面 (图形化画布主路) ----

    def test_read_doc_makes_depends_explicit(self) -> None:
        """serial_v1 源文件一个 depends_on 都不写 (链式糖), doc 必须给出显式边 —— 画布要画线."""
        raw_doc = yaml.safe_load(self.sched.read_recipe_text("serial_v1"))
        self.assertFalse(any("depends_on" in f for f in raw_doc["flows"]),
                         "serial_v1 应保持不写 depends_on 的链式糖形态")
        doc = self.sched.read_recipe_doc("serial_v1")
        chain = [(f["id"], f["depends_on"]) for f in doc["flows"]]
        self.assertEqual(chain[0], ("af0", []))
        self.assertEqual(chain[1], ("s1", ["af0"]))
        self.assertEqual(chain[-1], ("s11", ["s10"]))
        self.assertTrue(all("depends_on" in f for f in doc["flows"]))

    def test_read_doc_keeps_wiring_and_omits_empties(self) -> None:
        doc = self.sched.read_recipe_doc("parallel_v1")
        self.assertEqual(doc["schema"], "ptlc.recipe/v1")
        self.assertEqual(doc["consumables"], ["collector", "bottle"])
        by_id = {f["id"]: f for f in doc["flows"]}
        self.assertEqual(by_id["s3"]["inputs"], {"tank": {"ctx": "tank"}})
        self.assertEqual(by_id["s4"]["outputs"], {"before_path": "before_path"})
        self.assertEqual(by_id["s7"]["occupy"], ["scrape-holder"])
        self.assertEqual(by_id["s10"]["release"], ["scrape-holder"])
        self.assertTrue(by_id["s9"]["ingest_results"])
        # 空值键省略 (回写的 YAML 不长空壳)
        self.assertNotIn("inputs", by_id["s1"])
        self.assertNotIn("occupy", by_id["s1"])
        self.assertNotIn("ingest_results", by_id["s1"])

    def test_validate_doc_dry_run(self) -> None:
        doc = self.sched.read_recipe_doc("parallel_v1")
        errors, dto = self.sched.validate_recipe_doc(doc)
        self.assertEqual(errors, [])
        self.assertEqual(len(dto["segments"]), 12)

        errors, dto = self.sched.validate_recipe_doc({"schema": "wrong"})
        self.assertTrue(errors and dto is None)

        # 成环: s1 反过来依赖 s2 (画布拖线成环时前端已拦, 后端仍必须是最后一道)
        cyc = self.sched.read_recipe_doc("serial_v1")
        by_id = {f["id"]: f for f in cyc["flows"]}
        by_id["s1"]["depends_on"] = ["s2"]
        errors, dto = self.sched.validate_recipe_doc(cyc)
        self.assertTrue(any("成环" in e for e in errors), errors)
        self.assertIsNone(dto)


class SaveRecipeTest(_Base):
    """落盘面: 每用例独立 tmp 配方目录 + 独立内存实验库."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ptlc_recipes_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name in ("parallel_v1.yaml", "serial_v1.yaml"):
            shutil.copy2(_REAL_RECIPES / name, self.tmp / name)
        self.store = ExperimentStore(":memory:")
        self.sched = self.make_sched(self.tmp, self.store)

    def test_save_updates_file_and_busts_cache(self) -> None:
        before = self.sched.get_recipe("serial_v1")   # 先命中缓存
        text = self.sched.read_recipe_text("serial_v1").replace(
            "label: 串行全流程 v1 (12 段全链式)", "label: 串行改")
        out = self.sched.save_recipe_text("serial_v1", text)
        self.assertTrue(out["ok"])
        self.assertIn("label: 串行改", (self.tmp / "serial_v1.yaml").read_text(encoding="utf-8"))
        after = self.sched.get_recipe("serial_v1")
        self.assertEqual(after.label, "串行改", "保存后缓存必须失效 (get_recipe 现读)")
        self.assertNotEqual(before.label, after.label)

    def test_save_rejects_name_mismatch(self) -> None:
        text = self.sched.read_recipe_text("serial_v1")
        with self.assertRaises(SubmitError) as cm:
            self.sched.save_recipe_text("other_name", text)
        self.assertFalse(cm.exception.conflict)
        self.assertFalse((self.tmp / "other_name.yaml").exists())

    def test_save_rejects_invalid_and_keeps_file(self) -> None:
        original = (self.tmp / "serial_v1.yaml").read_text(encoding="utf-8")
        with self.assertRaises(SubmitError):
            self.sched.save_recipe_text("serial_v1", original.replace(
                "script: pf_s9_scrape", "script: no_such_script"))
        self.assertEqual((self.tmp / "serial_v1.yaml").read_text(encoding="utf-8"),
                         original, "校验失败绝不能动文件")

    def test_save_as_creates_new_recipe(self) -> None:
        text = self.sched.read_recipe_text("serial_v1").replace(
            "name: serial_v1", "name: serial_copy")
        out = self.sched.save_recipe_text("serial_copy", text)
        self.assertTrue(out["ok"])
        self.assertTrue((self.tmp / "serial_copy.yaml").exists())
        self.assertEqual(self.sched.validate_recipe_by_name("serial_copy"), [])

    def test_save_blocked_by_active_batch(self) -> None:
        self.store.create_batch("B1", name="在制批", recipe="serial_v1")   # QUEUED 即算活跃
        text = self.sched.read_recipe_text("serial_v1")
        with self.assertRaises(SubmitError) as cm:
            self.sched.save_recipe_text("serial_v1", text)
        self.assertTrue(cm.exception.conflict, "活跃批次引用必须是 conflict (409 语义)")
        self.assertIn("B1", str(cm.exception))
        # 不受影响的另一个方案仍可保存
        other = self.sched.read_recipe_text("parallel_v1")
        self.assertTrue(self.sched.save_recipe_text("parallel_v1", other)["ok"])

    # ---- 结构化 doc 保存 (画布保存路; 与文本路同守卫) ----

    def test_save_doc_roundtrip_is_stable(self) -> None:
        """读 doc -> 存 doc -> 再读 doc 必须等价 (规范化输出的不动点), 且校验仍零错误."""
        doc = self.sched.read_recipe_doc("parallel_v1")
        self.assertTrue(self.sched.save_recipe_doc("parallel_v1", doc)["ok"])
        again = self.sched.read_recipe_doc("parallel_v1")
        self.assertEqual(doc, again)
        self.assertEqual(self.sched.validate_recipe_by_name("parallel_v1"), [])
        # 落盘的是规范化 YAML (中文 label 不转义, 原文注释已被取代)
        text = (self.tmp / "parallel_v1.yaml").read_text(encoding="utf-8")
        self.assertIn("并行全流程 v1", text)
        self.assertNotIn("\\u", text)

    def test_save_doc_structural_edit_and_cache_bust(self) -> None:
        """画布式改动 (把 s3 依赖从 s1 改成 s2 = 由并行改回串行) 经 doc 落盘并即时生效."""
        doc = self.sched.read_recipe_doc("parallel_v1")
        by_id = {f["id"]: f for f in doc["flows"]}
        self.assertEqual(by_id["s3"]["depends_on"], ["s1"])   # 原本与 s2 并行
        by_id["s3"]["depends_on"] = ["s2"]
        self.sched.get_recipe("parallel_v1")                  # 先把旧定义焐进缓存
        self.assertTrue(self.sched.save_recipe_doc("parallel_v1", doc)["ok"])
        after = self.sched.get_recipe("parallel_v1")
        self.assertEqual(after.flow("s3").depends_on, ("s2",), "保存后缓存必须失效")

    def test_save_doc_rejects_bad_payload(self) -> None:
        original = (self.tmp / "serial_v1.yaml").read_text(encoding="utf-8")
        doc = self.sched.read_recipe_doc("serial_v1")

        with self.assertRaises(SubmitError):                  # name 不符
            self.sched.save_recipe_doc("other_name", doc)
        with self.assertRaises(SubmitError):                  # 非 mapping
            self.sched.save_recipe_doc("serial_v1", None)

        broken = self.sched.read_recipe_doc("serial_v1")
        {f["id"]: f for f in broken["flows"]}["s9"]["script"] = "no_such_script"
        with self.assertRaises(SubmitError):
            self.sched.save_recipe_doc("serial_v1", broken)
        self.assertEqual((self.tmp / "serial_v1.yaml").read_text(encoding="utf-8"),
                         original, "任何拒绝路径都不得动文件")

    def test_save_doc_blocked_by_active_batch(self) -> None:
        self.store.create_batch("B2", name="在制批", recipe="serial_v1")
        doc = self.sched.read_recipe_doc("serial_v1")
        with self.assertRaises(SubmitError) as cm:
            self.sched.save_recipe_doc("serial_v1", doc)
        self.assertTrue(cm.exception.conflict)


if __name__ == "__main__":
    unittest.main()
