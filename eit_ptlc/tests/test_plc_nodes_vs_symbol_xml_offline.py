#!/usr/bin/env python3
"""plc_nodes.yaml 与 PLC 符号导出 对账 离线测试
================================================
背景: 节点表最初是从旧上位机 UI-Upper/core/plc_client.py 的 NODE_TYPES 照抄的, 那张表对应
更早的 PLC 世代。结果 11 个真机根本不存在的名字一路留到线上, 每次启动刷一行
"[PLC] 节点表声明但 PLC 端未发现的变量: ..." WARNING —— 而这行本该只在真漂移时响。

本测试把"节点表 == PLC 实际导出的符号"变成 CI 可验的硬约束, 不必等真机启动才发现:
  1. 非 optional 条目必须在 PLC 符号里 (漂移/写错名当场红);
  2. optional 条目必须确实不在 (PLC 已建则豁免过期, 该摘掉 optional 让它进入正式对账);
  3. 两边都有的, 类型与数组维度必须对得上 (防 T_REAL 写 Double 之类的静默类型错);
  4. PLC 有而节点表没声明的, 只打印不断言 —— 它们靠 driver 的动态节点回退工作 (类型在
     browse 时读到), 但不在 mock/plc_server.py 里, 离线测试覆盖不到, 是否补声明另行决策。

事实源是 plc/*.Device.Application.xml (CODESYS "生成代码" 产出的 Symbol Configuration),
即 OPC UA 服务器真正对外暴露的那份清单。取目录下最新的一份。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import load_plc_nodes          # noqa: E402

_NODES_YAML = _PKG / "config" / "plc_nodes.yaml"
_PLC_DIR = _PKG / "plc"

# CODESYS 符号类型名 -> plc_nodes.yaml 的 VALID_NODE_TYPES 名
_IEC_TO_NODE_TYPE = {
    "BOOL": "Boolean",
    "BYTE": "Byte",
    "SINT": "SByte",
    "USINT": "Byte",
    "INT": "Int16",
    "WORD": "UInt16",
    "UINT": "UInt16",
    "DINT": "Int32",
    "DWORD": "UInt32",
    "UDINT": "UInt32",
    "LINT": "Int64",
    "ULINT": "UInt64",
    "REAL": "Float",
    "LREAL": "Double",
}

# T_ARRAY__1__400__OF_REAL / T_ARRAY__1__2__OF_STRING_128_
_ARRAY_RE = re.compile(r"^T_ARRAY__(\d+)__(\d+)__OF_(.+)$")


def _node_type_of(sym_type: str) -> tuple[str, int]:
    """把符号 XML 的类型名翻成 (VALID_NODE_TYPES 名, array_len); 未知类型返回 ("", 0)."""
    array_len = 0
    body = sym_type
    m = _ARRAY_RE.match(sym_type)
    if m:
        lo, hi, body = int(m.group(1)), int(m.group(2)), m.group(3)
        array_len = hi - lo + 1
    else:
        body = body[2:] if body.startswith("T_") else body
    if body.startswith("STRING"):          # STRING / STRING_128_
        return "String", array_len
    return _IEC_TO_NODE_TYPE.get(body, ""), array_len


def _latest_symbol_xml() -> Path | None:
    """plc/ 下最新的 *.Device.Application.xml (按文件名倒序, 命名即日期)."""
    found = sorted(_PLC_DIR.glob("*.Device.Application.xml"))
    return found[-1] if found else None


def _host_computer_symbols(xml_path: Path) -> dict[str, str]:
    """抽 Host_Computer 容器下的 {变量名: 符号类型名}."""
    txt = xml_path.read_text(encoding="utf-8-sig", errors="replace")
    start = txt.find('<Node name="Host_Computer">')
    if start < 0:
        raise AssertionError(f"{xml_path.name} 里找不到 Host_Computer 容器")
    seg = txt[start:]
    end = seg.find("\n      </Node>")               # 同缩进层的闭合 = 容器结束
    if end < 0:
        raise AssertionError(f"{xml_path.name} 的 Host_Computer 段未闭合")
    return dict(re.findall(r'<Node name="([^"]+)" type="([^"]+)"', seg[:end]))


class PlcNodesVsSymbolXmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        xml = _latest_symbol_xml()
        if xml is None:
            raise unittest.SkipTest(f"{_PLC_DIR} 下没有 *.Device.Application.xml, 跳过对账")
        cls.xml = xml
        cls.plc = _host_computer_symbols(xml)
        cls.nodes = load_plc_nodes(_NODES_YAML).nodes

    def test_declared_nodes_exist_on_plc(self) -> None:
        """非 optional 条目必须真在 PLC 符号里 —— 缺一个就是启动那行 WARNING 的来源。"""
        drift = sorted(n for n, s in self.nodes.items() if not s.optional and n not in self.plc)
        self.assertEqual(drift, [], (
            f"节点表声明但 {self.xml.name} 的 Host_Computer 里没有: {drift}。\n"
            f"若 PLC 侧确实删了/改名了, 同步改 plc_nodes.yaml; "
            f"若是排期待建, 给该条目加 optional: true 并写明排期。"))

    def test_optional_exemptions_still_needed(self) -> None:
        """标了 optional 的必须确实不在 PLC 上 —— 已建就该摘掉豁免, 回到正式对账。"""
        stale = sorted(n for n, s in self.nodes.items() if s.optional and n in self.plc)
        self.assertEqual(stale, [], (
            f"这些条目标了 optional, 但 {self.xml.name} 里 PLC 已经建好了: {stale}。\n"
            f"请摘掉 optional: true, 让它们进入正式对账 (并检查上位机侧是否可以启用相关功能)。"))

    def test_types_and_array_len_match(self) -> None:
        """两边都有的条目, 类型与数组维度必须一致 (防写值时的静默类型错)。"""
        bad: list[str] = []
        for name, spec in self.nodes.items():
            sym = self.plc.get(name)
            if sym is None:
                continue
            want_type, want_len = _node_type_of(sym)
            if not want_type:
                continue                              # 结构体/FB 等非标量类型: 节点表本就管不了
            if want_type != spec.var_type or want_len != spec.array_len:
                bad.append(f"{name}: PLC={sym} (→{want_type}[{want_len}]) "
                           f"vs YAML={spec.var_type}[{spec.array_len}]")
        self.assertEqual(bad, [], "节点表类型/维度与 PLC 符号不符:\n  " + "\n  ".join(bad))

    def test_report_undeclared_plc_symbols(self) -> None:
        """信息项 (不断言): PLC 有而节点表未声明的变量。

        它们靠 driver 的动态节点回退可读写 (VariantType 在 browse 时读到, 不会踩 String 默认),
        但 mock/plc_server.py 按本表建 Mock GVL, 所以离线测试碰不到它们。
        """
        undeclared = sorted(n for n in self.plc if n not in self.nodes)
        if undeclared:
            print(f"\n[信息] {self.xml.name} 有而 plc_nodes.yaml 未声明的 {len(undeclared)} 个变量 "
                  f"(走动态节点回退, 离线测试无覆盖):")
            for n in undeclared:
                print(f"    {n}: {self.plc[n]}")


if __name__ == "__main__":
    unittest.main()
