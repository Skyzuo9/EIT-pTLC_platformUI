#!/usr/bin/env python3
"""建议脚本变量的有限取值域 (enum) —— 只读, 只打印建议, 绝不落盘
================================================================
用法:
    python -m eit_ptlc.tools.suggest_var_enum            # 列出所有待补 enum 的入参
    python -m eit_ptlc.tools.suggest_var_enum rack_id    # 只看某个变量名

原理:
    反扫脚本 body 里 `{binop: ==, left: {var: X}, right: {lit: V}}` (含左右镜像形) 的
    字面量集合 —— 决定跑不跑进 `else: raise ROBOT_FLOW_SELECTOR` 的就是它, 故它是取值域
    的事实真源。再拿 config/backup/robot_flows_v2.yaml 的 selectors: 段做交叉参考。

⚠️ 反扫结果**只能当建议**, 不能自动落盘, 有两类已证实的假阳性:
    * enter_anchor: 本脚本只比较 == P1, 但 transfer_bottle_collect_to_staging_b.yaml
      与 collect_unload.yaml 实际传 {lit: P70}, robot_collect_bottle_put 注释写明可传 P52。
      照反扫写死会锁死 P70/P52 交接路线。
    * fixed_summary_path: 与 {lit: ""} 的比较是存在性判定, 不是枚举。
    同理不写自动改写器: operation YAML 是手改真源, 行内 flow 与块风格混用、注释密集,
    而 repo.py 的 yaml.safe_dump 回写会抹掉全部注释 (那正是 06_robot/*.yaml 顶部
    【手改·勿重生成 (G-1)】要防的事)。产出建议、人工落笔, 是这里唯一安全的做法。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.operation.vm.schema import var_enum  # noqa: E402

OPDIR = _PKG / "config" / "operation"
FLOWS_V2 = _PKG / "config" / "backup" / "robot_flows_v2.yaml"


def _cond_bindings(cond):
    """把一个分支条件解成 {变量名: 字面量}; 含非"变量==字面量"的成分则返回 None.

    支持 and 合取式 —— 双选择子脚本 (rack_id × slot_id) 的分支条件正是
    `rack_id == collector and slot_id == 3` 这种形状, 12 条 elif 穷举全部组合。
    """
    if not isinstance(cond, dict):
        return None
    op = cond.get("binop")
    if op == "and":
        left = _cond_bindings(cond.get("left"))
        right = _cond_bindings(cond.get("right"))
        if left is None or right is None:
            return None
        merged = dict(left)
        for k, v in right.items():
            if k in merged and merged[k] != v:
                return None                   # 同一变量在一条分支里被绑两个值: 不可满足, 不解析
            merged[k] = v
        return merged
    if op == "==":
        left, right = cond.get("left"), cond.get("right")
        if isinstance(left, dict) and isinstance(right, dict):
            if list(left) == ["var"] and list(right) == ["lit"]:
                return {left["var"]: right["lit"]}
            if list(right) == ["var"] and list(left) == ["lit"]:
                return {right["var"]: left["lit"]}
    return None


def _has_selector_raise(block) -> bool:
    """一段 body 里是否直接抛 *FLOW_SELECTOR (取值域穷举的标志)."""
    for node in block or []:
        if isinstance(node, dict) and node.get("op") == "raise" \
                and str(node.get("error", "")).endswith("FLOW_SELECTOR"):
            return True
    return False


def selector_chains(doc: dict) -> dict:
    """找出脚本里的"选择子 if 链", 返回 {变量名: {"values": [...], "closed": bool}}.

    选择子 if 链 = 一条 if/elif 链, 其每个分支条件都能解成"变量==字面量"的合取
    (单选择子如 station_id, 或双选择子如 rack_id × slot_id 的 12 条组合)。只有在**每条
    分支里都出现**的变量才算被该链穷举 —— 否则它的取值域不完整, 不作建议。
    closed = 该链的 else 直接 `raise *FLOW_SELECTOR` —— 意味着链外的值必炸, 取值域是闭集。

    这个"按 if 链"的判据比"数一数全文有几个 == 字面量"精确得多, 两类实证差别:
      * station_id 只有一个取值 default, 但它的 if 有 else: raise SELECTOR -> 闭集, 该有 enum
      * enter_anchor 也只比较 == P1, 但那个 if 没有 selector-else (走 else 是正常的
        "非 P1 入口不做 home 保证") -> 不是取值域, 且 P70/P52 是调用方真实会传的值
    """
    out: dict = {}

    def note(var, values, closed):
        slot = out.setdefault(var, {"values": [], "closed": False})
        for v in values:
            if v not in slot["values"]:
                slot["values"].append(v)
        slot["closed"] = slot["closed"] or closed

    def scan(node):
        if isinstance(node, dict):
            if node.get("op") == "if":
                conds = [node.get("cond")] + [br.get("cond") for br in (node.get("elifs") or [])]
                parsed = [_cond_bindings(c) for c in conds]
                if all(b for b in parsed):
                    closed = _has_selector_raise(node.get("else"))
                    common = set(parsed[0])
                    for b in parsed[1:]:
                        common &= set(b)
                    for var in common:
                        note(var, [b[var] for b in parsed], closed)
            for v in node.values():
                scan(v)
        elif isinstance(node, list):
            for v in node:
                scan(v)

    scan(doc.get("body"))
    return out


def selector_keys() -> dict:
    """robot_flows_v2.yaml 的 selectors: 段 -> {selector 名: 一级键列表} (只作交叉参考)."""
    if not FLOWS_V2.is_file():
        return {}
    data = yaml.safe_load(FLOWS_V2.read_text(encoding="utf-8")) or {}
    out = {}
    for sel, table in (data.get("selectors") or {}).items():
        if isinstance(table, dict):
            out[sel] = sorted(str(k) for k in table)
    return out


def main() -> int:
    want = sys.argv[1] if len(sys.argv) > 1 else ""
    sels = selector_keys()
    rows = []
    for path in sorted(OPDIR.rglob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict) or doc.get("kind") != "operation":
            continue
        chains = selector_chains(doc)
        for vd in (doc.get("vars") or []):
            if not isinstance(vd, dict) or vd.get("io") != "in":
                continue
            name = vd.get("name")
            if want and name != want:
                continue
            if var_enum(vd):
                continue                       # 已有取值域
            chain = chains.get(name)
            if not chain or not chain["closed"]:
                continue                       # 只建议"闭集选择子"(链外必炸), 其余留自由输入
            rows.append((path.relative_to(_PKG).as_posix(), name, vd.get("type"),
                         vd.get("default"), chain["values"], chain["closed"]))

    for rel, name, vtype, default, lits, closed in rows:
        flag = " [闭集: else raise SELECTOR]" if closed else ""
        print(f"{rel}  {name} ({vtype}, default={default!r}){flag}")
        print(f"    建议: enum: {lits!r}")
    print(f"---- 共 {len(rows)} 处待补")
    if sels:
        print("\n路线表 selectors 一级键 (交叉参考, 非断言基准 —— 该文件在 backup/ 下,")
        print("bootstrap 运行期不加载, 且生成物已被【手改·勿重生成】授权与模板分叉):")
        for sel, keys in sorted(sels.items()):
            print(f"    {sel}: {keys}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
