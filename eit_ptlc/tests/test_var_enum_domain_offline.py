#!/usr/bin/env python3
"""脚本变量有限取值域 (enum) 的防漂移守卫.

杀的 bug 类: 运行前面板给的可选值, 与脚本实际认的分支值不一致 —— 两个方向都致命:
    * 少声明 -> 下拉里选不到某条真实存在的合法路线 (功能凭空消失);
    * 多声明 -> 下拉里能选到必炸的值, 而炸点在脚本末尾的 `else: raise *FLOW_SELECTOR`,
      那时机器人已经 home 完、换完刀 (本守卫的起因: rack_id 被填成 control)。

真源是**脚本自己的 if/elif 字面量** —— 决定跑不跑进 else 的就是它。
刻意不拿 config/backup/robot_flows_v2.yaml 的 selectors: 段做断言基准: 它在 backup/ 下,
runtime/bootstrap 运行期不加载, 且生成物顶部标了【手改·勿重生成 (G-1)】= 已被明确授权
与模板分叉; 拿归档文件当真源会把本守卫从"抓漂移"退化成"逼着改档案"。
它只作 tools/suggest_var_enum.py 的交叉参考。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.operation.vm.expr import coerce_value  # noqa: E402
from eit_ptlc.operation.vm.schema import var_enum  # noqa: E402
from eit_ptlc.tools.suggest_var_enum import selector_chains  # noqa: E402
from eit_ptlc.value_domain import enum_values  # noqa: E402

_OPDIR = _PKG / "config" / "operation"

# A5 覆盖率闸的豁免名单 —— 每条必须写清"为什么它不是取值域", 否则本守卫会退化成橡皮图章。
# (目前为空: 已知的两个假阳性 enter_anchor / fixed_summary_path 都不构成"闭集选择子链",
#  selector_chains 天然不会把它们算进来, 无需豁免。留此表是给将来真出现例外时用的。)
_A5_EXEMPT: dict[str, str] = {}

# 已知不该静态写死的取值域 (若哪天有人给它们加了 enum, 本守卫要拦下并解释原因)
_MUST_NOT_DECLARE = {
    "enter_anchor": "点位名域: 反扫只见 == P1, 但 transfer_bottle_collect_to_staging_b "
                    "与 collect_unload 实际传 {lit: P70}, robot_collect_bottle_put 可传 P52; "
                    "写死会锁死交接路线。应照 api/dto.py 给 point_ref 注 target_keys 的范式动态注入。",
    "exit_anchor": "同 enter_anchor (瓶分支可传 P52)。",
}


def _all_compared_lits(doc: dict, var_name: str) -> list:
    """收集 body 里与 {var: var_name} 做 == 比较的全部字面量 (含左右镜像形, 不限于选择子链)."""
    vals: list = []

    def scan(node):
        if isinstance(node, dict):
            if node.get("binop") == "==":
                left, right = node.get("left"), node.get("right")
                if isinstance(left, dict) and isinstance(right, dict):
                    if list(left) == ["var"] and left["var"] == var_name and list(right) == ["lit"]:
                        vals.append(right["lit"])
                    elif list(right) == ["var"] and right["var"] == var_name and list(left) == ["lit"]:
                        vals.append(left["lit"])
            for v in node.values():
                scan(v)
        elif isinstance(node, list):
            for v in node:
                scan(v)

    scan(doc.get("body"))
    return vals


class VarEnumDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.docs: list[tuple[str, dict]] = []
        for f in sorted(_OPDIR.rglob("*.yaml")):
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            if isinstance(d, dict) and d.get("kind") == "operation":
                cls.docs.append((f.relative_to(_PKG).as_posix(), d))

    def _in_vars(self, doc):
        for vd in (doc.get("vars") or []):
            if isinstance(vd, dict) and vd.get("io") == "in" and vd.get("name"):
                yield vd

    # ------------------------------------------------------------------
    def test_a1_compared_literals_are_all_declared(self) -> None:
        """A1: 脚本里与该变量比较过的每个字面量, 都必须在声明的 enum 内.

        违反 = 加了新分支忘了加进 enum -> 下拉里选不到那条真实存在的路线。
        """
        bad: list[str] = []
        for rel, doc in self.docs:
            for vd in self._in_vars(doc):
                opts = var_enum(vd)
                if not opts:
                    continue
                declared = [coerce_value(vd["type"], v) for v in enum_values(opts)]
                for lit in _all_compared_lits(doc, vd["name"]):
                    try:
                        clit = coerce_value(vd["type"], lit)
                    except Exception:
                        continue          # 类型不符的比较本身是别的问题, 不在此守卫范围
                    if clit not in declared:
                        bad.append(f"{rel}  {vd['name']}: 分支比较 {lit!r} 不在声明的 enum {declared}")
        uniq = sorted(set(bad))
        self.assertEqual(uniq, [], "分支字面量未声明进 enum:\n  " + "\n  ".join(uniq))

    # ------------------------------------------------------------------
    def test_a2_closed_selector_declares_exactly_its_branches(self) -> None:
        """A2: 闭集选择子 (链外 else 直接 raise *FLOW_SELECTOR) 声明的 enum 不得多于其分支.

        违反 = 下拉里能选到一个必然抛 SELECTOR 的值 —— 正是本次事故的镜像。

        必须条件化在"闭集"上, 有实证反例: feedlift_measure_count 的 magazine 声明
        [feed, waste] 但 body 只比较 == feed, waste 走 else 正常执行 —— 无条件的
        "声明必须等于比较" 会误报。
        """
        bad: list[str] = []
        for rel, doc in self.docs:
            chains = selector_chains(doc)
            for vd in self._in_vars(doc):
                opts = var_enum(vd)
                chain = chains.get(vd["name"])
                if not opts or not chain or not chain["closed"]:
                    continue
                branch = [coerce_value(vd["type"], v) for v in chain["values"]]
                for v in enum_values(opts):
                    cv = coerce_value(vd["type"], v)
                    if cv not in branch:
                        bad.append(f"{rel}  {vd['name']}: enum 含 {v!r}, 但该值没有对应分支 "
                                   f"(闭集选择子, 选中必抛 FLOW_SELECTOR)")
        uniq = sorted(set(bad))
        self.assertEqual(uniq, [], "enum 声明了必炸的值:\n  " + "\n  ".join(uniq))

    # ------------------------------------------------------------------
    def test_a3_default_is_within_enum(self) -> None:
        """A3: 声明了 enum 的变量, 其 default 必须落在域内 (留空起跑走的就是它)."""
        bad: list[str] = []
        for rel, doc in self.docs:
            for vd in self._in_vars(doc):
                opts = var_enum(vd)
                if not opts or vd.get("default") is None:
                    continue
                declared = [coerce_value(vd["type"], v) for v in enum_values(opts)]
                if coerce_value(vd["type"], vd["default"]) not in declared:
                    bad.append(f"{rel}  {vd['name']}: default={vd['default']!r} 不在 enum {declared}")
        self.assertEqual(sorted(bad), [], "default 越出取值域:\n  " + "\n  ".join(sorted(bad)))

    # ------------------------------------------------------------------
    def test_a4_int_enum_items_are_yaml_ints(self) -> None:
        """A4: INT 变量的 enum 必须写成 YAML 整数, 不能是 ['1','2'].

        字符串项经 coerce 后虽也能匹配, 但会让"声明的类型"与"写下的字面量"脱节, 且前端
        enumOf 字符串化后与 INT draft 的比较行为依赖 coerce, 容易在别处踩空。
        """
        bad: list[str] = []
        for rel, doc in self.docs:
            for vd in self._in_vars(doc):
                if vd.get("type") != "INT":
                    continue
                for v in enum_values(var_enum(vd)):
                    if not isinstance(v, int) or isinstance(v, bool):
                        bad.append(f"{rel}  {vd['name']}: INT 变量的 enum 项 {v!r} 不是整数")
        self.assertEqual(sorted(bad), [], "INT enum 项类型不对:\n  " + "\n  ".join(sorted(bad)))

    # ------------------------------------------------------------------
    def test_a5_closed_selectors_must_declare_enum(self) -> None:
        """A5 覆盖率闸: 凡是"闭集选择子"(链外必抛 FLOW_SELECTOR) 的 in 变量都必须声明 enum.

        这条才是真正兜住"下次又忘了"的闸 —— 只做 A1/A2 的守卫对"根本没声明"完全失明,
        而本次事故 (rack_id 是自由文本框) 恰恰就是"根本没声明"。
        """
        bad: list[str] = []
        for rel, doc in self.docs:
            chains = selector_chains(doc)
            for vd in self._in_vars(doc):
                chain = chains.get(vd["name"])
                if not chain or not chain["closed"] or var_enum(vd):
                    continue
                if vd["name"] in _A5_EXEMPT:
                    continue
                bad.append(f"{rel}  {vd['name']}: 是闭集选择子却没声明 enum "
                           f"(分支值 {chain['values']}) -> 界面会渲染成自由输入框")
        self.assertEqual(sorted(bad), [],
                         "闭集选择子缺 enum 声明 (跑 python -m eit_ptlc.tools.suggest_var_enum 看建议):\n  "
                         + "\n  ".join(sorted(bad)))

    # ------------------------------------------------------------------
    def test_dynamic_domains_are_not_frozen_into_enum(self) -> None:
        """点位锚点一类"调用方会传本脚本没比较过的值"的参数, 不得静态写死 enum."""
        bad: list[str] = []
        for rel, doc in self.docs:
            for vd in self._in_vars(doc):
                if vd["name"] in _MUST_NOT_DECLARE and var_enum(vd):
                    bad.append(f"{rel}  {vd['name']}: {_MUST_NOT_DECLARE[vd['name']]}")
        self.assertEqual(sorted(bad), [], "动态取值域被写死成静态 enum:\n  " + "\n  ".join(sorted(bad)))

    # ------------------------------------------------------------------
    def test_rack_kind_domain_matches_material_ledger(self) -> None:
        """跨副本对账: collector|bottle 这一个域在仓里有多份, 此处钉住其中两份.

        另有 three_d/pipeline 的 AREA_BY_KIND 与前端 SegmentPanel 的 CONSUMABLE_KINDS
        两份副本 (各自子系统的测试/评审负责), 此处不跨子系统 import。
        """
        from eit_ptlc.runtime.material_store import AREAS, KINDS

        # 逐个声明比对, 不取并集 —— 并集会让"某一个文件少了 bottle"被其它文件的声明掩盖
        found = 0
        bad: list[str] = []
        for rel, doc in self.docs:
            for vd in self._in_vars(doc):
                if vd["name"] != "rack_id":
                    continue
                found += 1
                declared = set(enum_values(var_enum(vd)))
                if declared != set(KINDS):
                    bad.append(f"{rel}  rack_id 取值域 {sorted(declared)} "
                               f"≠ material_store.KINDS {sorted(KINDS)}")
        self.assertTrue(found, "没找到任何 rack_id 的 enum 声明 (铺开被回退了?)")
        self.assertEqual(sorted(bad), [], "rack_id 与物料账本的 kind 域脱节:\n  " + "\n  ".join(sorted(bad)))
        self.assertEqual(set(AREAS.values()), set(KINDS),
                         "material_store.AREAS 的 kind 值与 KINDS 不一致")


if __name__ == "__main__":
    unittest.main()
