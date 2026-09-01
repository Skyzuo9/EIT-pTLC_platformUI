#!/usr/bin/env python3
"""PLC 符号导出 pragma 解析/编辑 离线测试
==========================================
覆盖 controller/plc_symbol_pragma.py 的纯函数 (不依赖真机 / CODESYS):
  1. parse_symbols: 识别变量名/类型/已导出态, 跳过注释/区段关键字, 子串名不误判;
  2. set_symbol_pragma: 插入/删除 pragma, 幂等, 其余文本逐字保留, round-trip 还原;
  3. 边界: AT %地址 / ARRAY / STRING(n) / := 初值 / \r\n 换行 / 未找到变量。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.plc_symbol_pragma import (  # noqa: E402
    SYMBOL_PRAGMA,
    parse_symbols,
    set_symbol_pragma,
)

# 仿真 Host_Computer GVL 风格的声明片段 (GrpComment / AT 地址 / 数组 / STRING / := 初值 / 子串名)
_DECL = (
    "VAR_GLOBAL\n"
    "\tbOutput: BOOL;\n"
    "\t/// <GrpComment>\n"
    "\t/// <GrpComment_zh-cn>PLC 正在执行动作</GrpComment_zh-cn>\n"
    "\t/// </GrpComment>\n"
    "\t// PLC 正在执行动作 \n"
    "\tPLC_Busy: BOOL := FALSE;\n"
    "\tSampling_4X_ActPos  : LREAL;\n"
    "\tRail_ActPos         : LREAL;   // 地轨11Y 实际位置(mm) 每扫描镜像\n"
    "\tRail_Homed          : BOOL;    // 地轨11Y 已回零\n"
    "\tRail_ActPosX        : LREAL;\n"
    "\tTank_State: ARRAY[1..8] OF INT;\n"
    "\tSampling_clean_instructions: ARRAY[1..2] OF STRING(128);\n"
    "\tDrainDuration: TIME := TIME#5s0ms;\n"
    "\tIX0 AT %IB0: BYTE;\n"
    "\t{attribute 'symbol' := 'readwrite'}\n"
    "\tAlready_Exported: BOOL;\n"
    "END_VAR\n"
)


class ParseSymbolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.syms = parse_symbols(_DECL)
        self.by_name = {s["name"]: s for s in self.syms}

    def test_picks_all_variables_only(self) -> None:
        names = [s["name"] for s in self.syms]
        # 含全部变量, 不含区段关键字 / 注释
        self.assertIn("Rail_ActPos", names)
        self.assertIn("Rail_Homed", names)
        self.assertIn("IX0", names)
        self.assertIn("Already_Exported", names)
        self.assertNotIn("VAR_GLOBAL", names)
        self.assertNotIn("END_VAR", names)

    def test_types_extracted(self) -> None:
        self.assertEqual(self.by_name["Rail_ActPos"]["type"], "LREAL")
        self.assertEqual(self.by_name["Tank_State"]["type"], "ARRAY[1..8] OF INT")
        self.assertEqual(self.by_name["Sampling_clean_instructions"]["type"], "ARRAY[1..2] OF STRING(128)")
        # := 初值被剥离, 仅留纯类型
        self.assertEqual(self.by_name["DrainDuration"]["type"], "TIME")
        self.assertEqual(self.by_name["IX0"]["type"], "BYTE")

    def test_exported_flag(self) -> None:
        self.assertFalse(self.by_name["Rail_ActPos"]["exported"])
        self.assertTrue(self.by_name["Already_Exported"]["exported"])


class SetSymbolPragmaTests(unittest.TestCase):
    def test_enable_inserts_pragma_above(self) -> None:
        out = set_symbol_pragma(_DECL, "Rail_ActPos", True)
        self.assertIn(f"\t{SYMBOL_PRAGMA}\n\tRail_ActPos", out)
        by = {s["name"]: s for s in parse_symbols(out)}
        self.assertTrue(by["Rail_ActPos"]["exported"])

    def test_enable_does_not_touch_substring_var(self) -> None:
        out = set_symbol_pragma(_DECL, "Rail_ActPos", True)
        by = {s["name"]: s for s in parse_symbols(out)}
        self.assertTrue(by["Rail_ActPos"]["exported"])
        self.assertFalse(by["Rail_ActPosX"]["exported"])      # 子串变量未被波及

    def test_enable_idempotent(self) -> None:
        once = set_symbol_pragma(_DECL, "Rail_ActPos", True)
        twice = set_symbol_pragma(once, "Rail_ActPos", True)
        self.assertEqual(once, twice)                          # 已导出再 enable 不重复插入

    def test_disable_removes_pragma(self) -> None:
        out = set_symbol_pragma(_DECL, "Already_Exported", False)
        by = {s["name"]: s for s in parse_symbols(out)}
        self.assertFalse(by["Already_Exported"]["exported"])
        self.assertNotIn(f"{SYMBOL_PRAGMA}\n\tAlready_Exported", out)

    def test_disable_idempotent_on_non_exported(self) -> None:
        out = set_symbol_pragma(_DECL, "Rail_ActPos", False)   # 本未导出
        self.assertEqual(out, _DECL)                           # 无变化, 逐字相同

    def test_round_trip_restores_verbatim(self) -> None:
        enabled = set_symbol_pragma(_DECL, "Rail_Homed", True)
        restored = set_symbol_pragma(enabled, "Rail_Homed", False)
        self.assertEqual(restored, _DECL)                      # enable 再 disable 完全还原

    def test_only_target_line_changes(self) -> None:
        out = set_symbol_pragma(_DECL, "Rail_Homed", True)
        # 仅多出一行 pragma, 其余行逐字保留
        self.assertEqual(out.replace(f"\t{SYMBOL_PRAGMA}\n", "", 1), _DECL)

    def test_crlf_preserved(self) -> None:
        decl_crlf = _DECL.replace("\n", "\r\n")
        out = set_symbol_pragma(decl_crlf, "Rail_ActPos", True)
        self.assertIn(f"\t{SYMBOL_PRAGMA}\r\n\tRail_ActPos", out)   # 用 \r\n 换行
        self.assertEqual(set_symbol_pragma(out, "Rail_ActPos", False), decl_crlf)

    def test_missing_variable_raises(self) -> None:
        with self.assertRaises(ValueError):
            set_symbol_pragma(_DECL, "NoSuchVar", True)


if __name__ == "__main__":
    unittest.main()
