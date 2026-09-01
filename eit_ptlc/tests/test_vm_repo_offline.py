"""脚本仓库离线测试
==================
功能:
    在临时目录验证 ScriptRepo: create/get/update(快照增长)/无改动跳过快照/clone/rename(历史迁移)/
    delete/版本历史/内容哈希, 以及校验器拒绝非法脚本.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_vm_repo_offline
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from eit_ptlc.operation.vm.repo import ScriptRepo
from eit_ptlc.operation.vm.schema import validate_script


def _doc(name, body):
    return {"schema": "ptlc.script/v1", "kind": "operation", "name": name, "label": name,
            "vars": [], "body": body}


def _run() -> int:
    failures: list[str] = []

    def check(name, cond, detail=""):
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    root = Path(tempfile.mkdtemp(prefix="ptlc_repo_"))
    try:
        repo = ScriptRepo(root, validator=lambda d: validate_script(d, valid_actions={"A"}))

        # create + get
        repo.create("default", "s1", _doc("s1", [{"op": "call", "action": "A", "args": {}}]))
        got = repo.get("default", "s1")
        check("create_get", got["name"] == "s1" and got["body"][0]["action"] == "A")
        check("history_after_create", len(repo.history("default", "s1")) == 1, str(repo.history("default", "s1")))

        # update changes content -> snapshot grows
        repo.update("default", "s1", _doc("s1", [{"op": "call", "action": "A", "args": {}},
                                                 {"op": "comment", "text": "新增"}]))
        check("history_after_update", len(repo.history("default", "s1")) == 2)

        # update same content -> no new snapshot
        repo.update("default", "s1", repo.get("default", "s1"))
        check("noop_skip_snapshot", len(repo.history("default", "s1")) == 2,
              str(len(repo.history("default", "s1"))))

        # content hash stable
        h1 = repo.content_hash(repo.get("default", "s1"))
        h2 = repo.content_hash(repo.get("default", "s1"))
        check("content_hash_stable", h1 == h2 and len(h1) == 16)

        # list + kind filter
        check("list_scripts", [s["name"] for s in repo.list_scripts("default")] == ["s1"])
        check("kind_filter_empty", repo.list_scripts("default", kind="action") == [])

        # clone
        repo.clone("default", "s1", "s2")
        check("clone", repo.exists("default", "s2") and repo.get("default", "s2")["name"] == "s2")

        # rename moves file + history
        repo.rename("default", "s1", "s1b")
        check("rename", not repo.exists("default", "s1") and repo.exists("default", "s1b"))
        check("rename_history_moved", len(repo.history("default", "s1b")) == 2
              and repo.history("default", "s1") == [])

        # version restore content
        rev = repo.history("default", "s1b")[0]["rev"]
        v0 = repo.get_version("default", "s1b", rev)
        check("get_version", v0["name"] in ("s1", "s1b"))

        # delete removes file + history
        repo.delete("default", "s2")
        check("delete", not repo.exists("default", "s2") and repo.history("default", "s2") == [])

        # validator rejects unknown action
        try:
            repo.create("default", "bad", _doc("bad", [{"op": "call", "action": "B", "args": {}}]))
            check("validator_reject", False, "未拒绝未知动作")
        except ValueError:
            check("validator_reject", True)

        # workspaces
        check("list_workspaces", repo.list_workspaces() == ["default"])
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n共 14 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return _run()


if __name__ == "__main__":
    sys.exit(main())
