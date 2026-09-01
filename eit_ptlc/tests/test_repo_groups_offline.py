#!/usr/bin/env python3
"""ScriptRepo 单根 + 组子目录 离线测试
=====================================
功能:
    校验流程仓库的"组=子文件夹"模型: create 落到组子目录、list_scripts 返回组、按名跨组
    get/rename/clone/delete、重名拒绝、版本历史落独立 history_root (不污染库目录)。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.operation.vm.repo import ScriptRepo  # noqa: E402


def _doc(name: str) -> dict:
    return {"schema": "ptlc.script/v1", "kind": "operation", "name": name, "label": name, "vars": [], "body": []}


class ScriptRepoGroupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "operation"
        self.hist = Path(self._tmp.name) / "history"
        self.repo = ScriptRepo(self.root, history_root=self.hist)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_in_group_lands_in_subfolder(self) -> None:
        self.repo.create("default", "alpha", _doc("alpha"), group="01_x")
        self.repo.create("default", "beta", _doc("beta"), group="02_y")
        self.repo.create("default", "root_op", _doc("root_op"))           # 组为空 -> 库根
        self.assertTrue((self.root / "01_x" / "alpha.yaml").is_file())
        self.assertTrue((self.root / "02_y" / "beta.yaml").is_file())
        self.assertTrue((self.root / "root_op.yaml").is_file())
        groups = {s["name"]: s["group"] for s in self.repo.list_scripts("default", "operation")}
        self.assertEqual(groups, {"alpha": "01_x", "beta": "02_y", "root_op": ""})

    def test_get_and_lifecycle_by_name_across_groups(self) -> None:
        self.repo.create("default", "alpha", _doc("alpha"), group="01_x")
        self.assertEqual(self.repo.get("default", "alpha")["name"], "alpha")   # 按名跨组取到
        self.assertTrue(self.repo.exists("default", "alpha"))
        # rename 保持原组
        self.repo.rename("default", "alpha", "alpha2")
        self.assertTrue((self.root / "01_x" / "alpha2.yaml").is_file())
        self.assertFalse((self.root / "01_x" / "alpha.yaml").is_file())
        # clone 保持原组
        self.repo.clone("default", "alpha2", "alpha3")
        self.assertTrue((self.root / "01_x" / "alpha3.yaml").is_file())
        # delete 按名
        self.repo.delete("default", "alpha2")
        self.assertFalse(self.repo.exists("default", "alpha2"))

    def test_duplicate_name_rejected_across_groups(self) -> None:
        self.repo.create("default", "dup", _doc("dup"), group="01_x")
        with self.assertRaises(ValueError):
            self.repo.create("default", "dup", _doc("dup"), group="02_y")

    def test_history_in_separate_root_not_in_repo(self) -> None:
        self.repo.create("default", "alpha", _doc("alpha"), group="01_x")
        self.repo.update("default", "alpha", {**_doc("alpha"), "label": "改名"})
        self.assertTrue(self.hist.is_dir())
        self.assertTrue(any(self.hist.glob("alpha/*.yaml")))                  # 快照落 history_root
        self.assertFalse((self.root / ".history").exists())                  # 库目录不含历史
        self.assertGreaterEqual(len(self.repo.history("default", "alpha")), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
