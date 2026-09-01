"""mini-VM 表达式与类型系统离线测试
==================================
功能:
    验证 eval_expr (字面量/变量/二元/一元/白名单函数/下标/字段, 含 and/or 短路) 与
    coerce_value/default_value 类型强转 (含 POSE 长度校验、常量错误).

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_vm_expr_offline
"""

from __future__ import annotations

import sys

from eit_ptlc.operation.vm.errors import VmError
from eit_ptlc.operation.vm.expr import coerce_value, default_value, eval_expr


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    env = {"x": 5, "y": [1, 2, 3], "d": {"a": 1}}
    read = lambda n: env[n]

    # 基本
    check("lit", eval_expr({"lit": 42}, read) == 42)
    check("var", eval_expr({"var": "x"}, read) == 5)

    # 二元
    check("binop_add", eval_expr({"binop": "+", "left": {"var": "x"}, "right": {"lit": 3}}, read) == 8)
    check("binop_gt", eval_expr({"binop": ">", "left": {"var": "x"}, "right": {"lit": 3}}, read) is True)
    check("binop_floordiv", eval_expr({"binop": "//", "left": {"lit": 7}, "right": {"lit": 2}}, read) == 3)

    # 短路: and 假值不求右; or 真值不求右 (右侧读不存在变量, 若被求值会 KeyError)
    check("and_shortcircuit",
          eval_expr({"binop": "and", "left": {"lit": False}, "right": {"var": "missing"}}, read) is False)
    check("or_shortcircuit",
          eval_expr({"binop": "or", "left": {"lit": 1}, "right": {"var": "missing"}}, read) == 1)

    # 一元
    check("unop_not", eval_expr({"unop": "not", "operand": {"lit": False}}, read) is True)
    check("unop_neg", eval_expr({"unop": "neg", "operand": {"lit": 5}}, read) == -5)

    # 白名单函数
    check("call_len", eval_expr({"call": "len", "args": [{"var": "y"}]}, read) == 3)
    check("call_max", eval_expr({"call": "max", "args": [{"lit": 2}, {"lit": 9}]}, read) == 9)
    check("call_contains", eval_expr({"call": "contains", "args": [{"var": "y"}, {"lit": 2}]}, read) is True)
    check("call_get", eval_expr({"call": "get", "args": [{"var": "d"}, {"lit": "a"}]}, read) == 1)

    # 下标 / 字段
    check("index", eval_expr({"index": {"var": "y"}, "key": {"lit": 0}}, read) == 1)
    check("field", eval_expr({"field": {"var": "d"}, "name": "a"}, read) == 1)

    # 错误
    try:
        eval_expr({"foo": 1}, read)
        check("bad_expr_raises", False, "未抛")
    except VmError:
        check("bad_expr_raises", True)
    try:
        eval_expr({"call": "open", "args": []}, read)
        check("call_whitelist", False, "未拦截非白名单")
    except VmError:
        check("call_whitelist", True)

    # 类型强转
    check("coerce_int", coerce_value("INT", "7") == 7)
    check("coerce_float", coerce_value("FLOAT", "1.5") == 1.5)
    check("coerce_bool", coerce_value("BOOL", "yes") is True and coerce_value("BOOL", "0") is False)
    check("coerce_pose", coerce_value("POSE", [1, 2, 3, 4, 5, 6]) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    check("coerce_none_default", coerce_value("INT", None) == 0 and coerce_value("LIST", None) == [])
    check("default_value", default_value("DICT") == {} and default_value("STRING") == "")
    try:
        coerce_value("POSE", [1, 2])
        check("coerce_pose_len", False, "未校验长度")
    except VmError:
        check("coerce_pose_len", True)

    print(f"\n共 {21} 用例, 失败 {len(failures)}")
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
