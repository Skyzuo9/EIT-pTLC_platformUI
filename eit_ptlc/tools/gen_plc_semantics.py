"""PLC 语义表生成器 (供三维实时页把 ErrorCode / Step 翻成中文)
================================================================
功能:
    把 mock/behavior/specs/*.yaml 里的动作名 / 错误码中文 / 段号表, 渲染成一份
    提交进仓的前端模块 web/src/three-d/twin/plcSemantics.generated.js。

为什么是"生成一份副本"而不是"开一个后端端点":
    三维实时页 (TwinView) 明确设计成脱离上位机也能跑 (live 默认 false), 为纯展示数据
    新开一条后端路由不划算; 而 /api/sim/diagnostics 是**沙盒专用**, 真机没有对等端点,
    action/plc_error_hints.describe 又只在"你发的动作失败了"那一刻可达, 回答不了
    "我盯着的这个 ErrorCode 301 是什么意思"。

为什么这份副本不构成"第二真源":
    specs 是静态 CODESYS 提取物, 本身已有两道看门狗 (tests/test_plc_spec_offline.py 与
    tools/plc_spec_drift.py); 本生成物再加一道逐字节比对 (tests/test_plc_semantics_gen_offline.py),
    人手改它必红。**不许手工编辑生成物。**

明确不做的事:
    steps[].phase 是英文蛇形 (wait_all_axes_home), **不在这里翻译** —— 那才是真的第二
    真源。前端只把它原样显示在工程师层, 给操作员看的是位置 (第 k/n 段)。

用法:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tools.gen_plc_semantics
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tools.gen_plc_semantics --check
退出码:
    0 = 已写入 / 内容一致; 1 = --check 下发现内容不一致 (需重新生成)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eit_ptlc.mock.behavior.spec_loader import load_all_specs

_OUT = (Path(__file__).resolve().parent.parent
        / "web" / "src" / "three-d" / "twin" / "plcSemantics.generated.js")

_HEADER = """/**
 * 功能: PLC L2 动作码 / 错误码 / 段号的中文释义 —— **本文件由脚本生成, 不要手改**.
 *
 * 生成器: eit_ptlc/tools/gen_plc_semantics.py
 * 真源:   eit_ptlc/mock/behavior/specs/*.yaml (从 CODESYS 现役工程逐字提取)
 * 看门狗: eit_ptlc/tests/test_plc_semantics_gen_offline.py (逐字节比对, 手改必红)
 *
 * 改法: 改真源 yaml, 然后
 *   & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tools.gen_plc_semantics
 *
 * 形状: { <工位L2前缀>: { unknownCodeError, gateErrors:{码:中文},
 *                        actions: { <动作码>: { name, summary, steps:[[段号,phase]], errors:{码:中文} } } } }
 * 注意 steps 里的 phase 是英文蛇形原文 —— 刻意不译, 只给工程师层看.
 */
"""


def build_payload() -> dict:
    """把全部工位 spec 收敛成前端要的最小形状.

    返回:
        dict, 见模块 docstring 的形状说明
    """
    out: dict = {}
    for station, spec in sorted(load_all_specs().items()):
        actions: dict = {}
        for code, action in sorted(spec.actions.items()):
            actions[str(code)] = {
                "name": action.name,
                "summary": action.summary,
                # 二元组数组比对象省一半体积, 且天然保序 (段号顺序是有意义的)
                "steps": [[int(item["step"]), str(item["phase"])] for item in action.steps],
                "errors": {str(k): v for k, v in sorted(action.errors.items())},
            }
        out[station] = {
            "unknownCodeError": int(spec.unknown_code_error),
            "gateErrors": {str(k): v for k, v in sorted(spec.gate_errors.items())},
            "actions": actions,
        }
    return out


def render(payload: dict) -> str:
    """渲染成 JS 模块文本 (稳定排序 + 固定缩进, 保证可逐字节比对)."""
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return f"{_HEADER}\nexport const PLC_SEMANTICS = Object.freeze({body})\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成三维实时页的 PLC 语义表")
    parser.add_argument("--check", action="store_true",
                        help="只比对不写盘; 内容不一致时退出码 1")
    args = parser.parse_args(argv)

    text = render(build_payload())
    if args.check:
        current = _OUT.read_text(encoding="utf-8") if _OUT.exists() else ""
        if current != text:
            print(f"[漂移] {_OUT.name} 与 specs 不一致, 请重新生成", file=sys.stderr)
            return 1
        print(f"[一致] {_OUT.name}")
        return 0

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    # 显式 UTF-8 无 BOM + LF: PowerShell 的 Out-File 会写 BOM, 而 BOM 会让别的工具链炸
    _OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"[已写入] {_OUT} ({len(text)} 字符)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
