"""动作目录金样生成器 (供前端受众分类的漂移看门狗)
====================================================
功能:
    把 config/actions/**/*.yaml 里的动作清单渲染成 web/tests/three-d/actions.catalog.json。
    前端 three-d/twin/actionAudience.js 用它断言:
      ① 目录里每个动作都有受众分类 (运维 / 工程师);
      ② 运维白名单里每个名字都真的存在 (抓改名与手误);
      ③ 运维白名单里不许有 modes:[DEBUG] 的动作 —— 那种在运行模式下永远置灰, 属规格错误;
      ④ 运维白名单里每条都带非空 hint (常用区的操作员短说明, 新动作漏写即红)。

    只取分类需要的字段外加 has_hint 布尔, 不取 params/desc/hint 原文 ——
    金样越小, 无关改动 (措辞润色) 越不会让它红。

用法:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tools.gen_action_catalog_fixture
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tools.gen_action_catalog_fixture --check
退出码:
    0 = 已写入 / 内容一致; 1 = --check 下发现不一致
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eit_ptlc.action.registry import ActionRegistry

_ROOT = Path(__file__).resolve().parent.parent
_ACTIONS_DIR = _ROOT / "config" / "actions"
_OUT = _ROOT / "web" / "tests" / "three-d" / "actions.catalog.json"


def build_payload() -> dict:
    """收敛动作目录成金样形状 (按 name 排序, 保证可逐字节比对)."""
    registry = ActionRegistry.load(_ACTIONS_DIR)
    actions = []
    for adef in sorted(registry.list(), key=lambda item: item.name):
        actions.append({
            "name": adef.name,
            "kind": adef.kind,
            "group": adef.group or "",
            "station": adef.station or "",
            "action_code": adef.action_code if adef.action_code is not None else None,
            "modes": sorted(adef.modes or []),
            # 布尔而不是原文: 看门狗只关心"写没写", 措辞润色不该让金样红
            "has_hint": bool(adef.hint),
        })
    return {
        "_why": "config/actions/**/*.yaml 的动作清单金样; 由 "
                "eit_ptlc/tools/gen_action_catalog_fixture.py 生成, 勿手改",
        "actions": actions,
    }


def render(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成动作目录金样")
    parser.add_argument("--check", action="store_true", help="只比对不写盘")
    args = parser.parse_args(argv)

    text = render(build_payload())
    if args.check:
        current = _OUT.read_text(encoding="utf-8") if _OUT.exists() else ""
        if current != text:
            print(f"[漂移] {_OUT.name} 与 config/actions 不一致, 请重新生成", file=sys.stderr)
            return 1
        print(f"[一致] {_OUT.name}")
        return 0

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"[已写入] {_OUT} ({len(build_payload()['actions'])} 条动作)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
