"""动作目录金样的漂移看门狗
===========================
功能:
    web/tests/three-d/actions.catalog.json 是前端受众分类 (actionAudience.js) 的比对基准。
    本测试重新从 config/actions/**/*.yaml 渲染并逐字节比对 —— 增删改动作而忘了重生成,
    金样就会腐烂成一份过期清单, 那时 node 侧那三条断言全都在对着旧数据点头。

    另外锁住资源钩子集: 前端 BLOCKED_ACTIONS 必须与 config/resources.yaml 声明的
    activate/deactivate 一致, 否则界面上会出现两个必然 409 的按钮。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from eit_ptlc.tools.gen_action_catalog_fixture import build_payload, render

_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = _ROOT / "web" / "tests" / "three-d" / "actions.catalog.json"
_RESOURCES = _ROOT / "config" / "resources.yaml"
_AUDIENCE = _ROOT / "web" / "src" / "three-d" / "twin" / "actionAudience.js"

_HINT = ('运行 & "C:/ProgramData/miniforge3/python.exe" '
         "-m eit_ptlc.tools.gen_action_catalog_fixture 重生成")


def test_fixture_exists():
    assert _FIXTURE.exists(), f"动作目录金样缺失 —— {_HINT}"


def test_fixture_is_byte_identical():
    assert _FIXTURE.read_text(encoding="utf-8") == render(build_payload()), (
        f"actions.catalog.json 与 config/actions 不一致 —— {_HINT}")


def test_blocked_actions_match_resource_hooks():
    """前端隐藏的资源钩子名单 == resources.yaml 里的 activate/deactivate 全集.

    2026-08-15 起前端不再渲染"不可单独执行"段, 这些动作整体从面板消失
    (RESOURCE_GATE_ACTIONS); 集合仍必须与 resources.yaml 逐字一致 ——
    少了会出现必然 409 的按钮, 多了会白藏一个可用动作。
    """
    doc = yaml.safe_load(_RESOURCES.read_text(encoding="utf-8")) or {}
    hooks = set()
    for spec in (doc.get("resources") or {}).values():
        if not isinstance(spec, dict):
            continue
        for key in ("activate", "deactivate"):
            if spec.get(key):
                hooks.add(str(spec[key]))

    source = _AUDIENCE.read_text(encoding="utf-8")
    block = re.search(r"RESOURCE_GATE_ACTIONS\s*=\s*new Set\(\[(.*?)\]\)", source, re.S)
    assert block, "actionAudience.js 里找不到 RESOURCE_GATE_ACTIONS"
    declared = set(re.findall(r"'([a-z_]+\.[a-z_]+)'", block.group(1)))

    assert declared == hooks, (
        f"前端 RESOURCE_GATE_ACTIONS {sorted(declared)} 与 resources.yaml 的资源钩子 "
        f"{sorted(hooks)} 不一致 —— 少了会出现必然 409 的按钮, 多了会白藏一个可用动作")


def test_ops_whitelist_names_all_exist():
    """运维白名单里的名字都要在动作目录里 (node 侧也测, 这里是双保险: 后端改名先红)."""
    known = {action["name"] for action in build_payload()["actions"]}
    source = _AUDIENCE.read_text(encoding="utf-8")
    block = re.search(r"OPS_ACTIONS\s*=\s*new Set\(\[(.*?)\]\)", source, re.S)
    assert block, "actionAudience.js 里找不到 OPS_ACTIONS"
    names = set(re.findall(r"'([a-z_]+\.[a-z_]+)'", block.group(1)))
    assert names, "运维白名单解析为空, 正则可能与源码格式脱节"
    missing = sorted(names - known)
    assert not missing, f"运维白名单里这些动作不存在: {missing}"
