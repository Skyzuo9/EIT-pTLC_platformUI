"""mini-VM 解释线程离线测试
==========================
功能:
    用 FakeExecutor (不接 OPC UA) 验证 VmThread 执行语义: 线性/分支(if-elif-else)/循环(for-range/
    for-list/while)/赋值与表达式/try-catch(动作失败 + raise)/未捕获 raise/子脚本帧与 in-out 传参/
    全局变量跨帧共享/parallel/常量写拒绝/终态事件.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_vm_thread_offline
"""

from __future__ import annotations

import asyncio
import sys

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.state import VmStatus
from eit_ptlc.operation.vm.thread import VmThread


class FakeExecutor:
    """假执行器: 记录调用; 默认返回 DONE; fail 映射指定动作返回失败状态."""

    def __init__(self, fail: dict | None = None) -> None:
        self.calls: list[tuple] = []
        self._fail = fail or {}

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        params = dict(params or {})
        self.calls.append((name, params, current_mode))
        if name in self._fail:
            status, msg = self._fail[name]
            return ActionResult(action=name, request_id="x", status=status, accepted=True,
                                message=msg, result={"echo": params})
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE, accepted=True,
                            message="ok", result={"echo": params})


def script(name, variables, body, kind="operation"):
    return {"schema": "ptlc.script/v1", "kind": kind, "name": name, "label": name,
            "vars": variables, "body": body}


def names(ex):
    return [c[0] for c in ex.calls]


def arg_seq(ex, key):
    return [c[1].get(key) for c in ex.calls]


def rootvar(t, name):
    return t.stack[0].locals.vars[name].value if name in t.stack[0].locals.vars else t._global.vars[name].value


async def _run() -> int:
    failures: list[str] = []

    def check(name, cond, detail=""):
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # 1) 线性 + 终态事件
    ex = FakeExecutor()
    events: list[dict] = []
    t = VmThread(script("lin", [], [{"op": "call", "action": "A"}, {"op": "call", "action": "B"},
                                    {"op": "call", "action": "C"}]),
                 executor=ex, res_gate=ResourceGate(), emit=events.append)
    st = await t.run()
    check("linear", st is VmStatus.DONE and names(ex) == ["A", "B", "C"], f"{st} {names(ex)}")
    types = [e["type"] for e in events]
    check("terminal_events", types.count("operation_start") == 1 and types.count("operation_done") == 1, str(types))

    # 2) if true / else
    for xv, want in ((5, "A"), (1, "B")):
        ex = FakeExecutor()
        t = VmThread(script("ifs", [{"name": "x", "scope": "local", "type": "INT", "io": "var", "default": xv}],
                            [{"op": "if", "cond": {"binop": ">", "left": {"var": "x"}, "right": {"lit": 3}},
                              "then": [{"op": "call", "action": "A"}], "else": [{"op": "call", "action": "B"}]}]),
                     executor=ex, res_gate=ResourceGate())
        await t.run()
        check(f"if_x{xv}", names(ex) == [want], names(ex))

    # 3) elif
    ex = FakeExecutor()
    t = VmThread(script("elifs", [{"name": "x", "scope": "local", "type": "INT", "io": "var", "default": 2}],
                        [{"op": "if", "cond": {"binop": ">", "left": {"var": "x"}, "right": {"lit": 5}},
                          "then": [{"op": "call", "action": "A"}],
                          "elifs": [{"cond": {"binop": ">", "left": {"var": "x"}, "right": {"lit": 1}},
                                     "body": [{"op": "call", "action": "B"}]}],
                          "else": [{"op": "call", "action": "C"}]}]),
                 executor=ex, res_gate=ResourceGate())
    await t.run()
    check("elif", names(ex) == ["B"], names(ex))

    # 4) for range
    ex = FakeExecutor()
    t = VmThread(script("forr", [{"name": "i", "scope": "local", "type": "INT", "io": "var", "default": 0}],
                        [{"op": "for", "var": "i", "start": {"lit": 0}, "stop": {"lit": 3}, "step": {"lit": 1},
                          "body": [{"op": "call", "action": "A", "args": {"i": {"var": "i"}}}]}]),
                 executor=ex, res_gate=ResourceGate())
    await t.run()
    check("for_range", arg_seq(ex, "i") == [0, 1, 2], arg_seq(ex, "i"))

    # 5) for list
    ex = FakeExecutor()
    t = VmThread(script("forl", [{"name": "it", "scope": "local", "type": "INT", "io": "var", "default": 0},
                                 {"name": "items", "scope": "local", "type": "LIST", "io": "var", "default": [10, 20]}],
                        [{"op": "for", "var": "it", "in": {"var": "items"},
                          "body": [{"op": "call", "action": "A", "args": {"v": {"var": "it"}}}]}]),
                 executor=ex, res_gate=ResourceGate())
    await t.run()
    check("for_list", arg_seq(ex, "v") == [10, 20], arg_seq(ex, "v"))

    # 6) while + assign + 表达式
    ex = FakeExecutor()
    t = VmThread(script("wh", [{"name": "n", "scope": "local", "type": "INT", "io": "var", "default": 0}],
                        [{"op": "while", "cond": {"binop": "<", "left": {"var": "n"}, "right": {"lit": 3}},
                          "body": [{"op": "assign", "target": {"var": "n"},
                                    "value": {"binop": "+", "left": {"var": "n"}, "right": {"lit": 1}}},
                                   {"op": "call", "action": "A"}]}]),
                 executor=ex, res_gate=ResourceGate())
    await t.run()
    check("while", names(ex) == ["A", "A", "A"] and rootvar(t, "n") == 3, f"{names(ex)} n={rootvar(t,'n')}")

    # 7) 赋值算术
    ex = FakeExecutor()
    t = VmThread(script("ar", [{"name": "a", "scope": "local", "type": "INT", "io": "var", "default": 2},
                               {"name": "b", "scope": "local", "type": "INT", "io": "var", "default": 3},
                               {"name": "c", "scope": "local", "type": "INT", "io": "var", "default": 0}],
                        [{"op": "assign", "target": {"var": "c"},
                          "value": {"binop": "+", "left": {"binop": "*", "left": {"var": "a"}, "right": {"var": "b"}},
                                    "right": {"lit": 1}}},
                         {"op": "call", "action": "A", "args": {"c": {"var": "c"}}}]),
                 executor=ex, res_gate=ResourceGate())
    await t.run()
    check("assign_expr", arg_seq(ex, "c") == [7], arg_seq(ex, "c"))

    # 8) try/catch 动作失败
    ex = FakeExecutor(fail={"F": (ActionStatus.ERROR, "boom")})
    t = VmThread(script("tc", [],
                        [{"op": "try", "body": [{"op": "call", "action": "F"}],
                          "catch": [{"error": "*", "body": [{"op": "call", "action": "R"}]}]}]),
                 executor=ex, res_gate=ResourceGate())
    st = await t.run()
    check("try_catch_action", st is VmStatus.DONE and names(ex) == ["F", "R"], f"{st} {names(ex)}")

    # 9) try/catch raise 按名匹配
    ex = FakeExecutor()
    t = VmThread(script("tr", [],
                        [{"op": "try", "body": [{"op": "raise", "error": "X", "message": {"lit": "e"}}],
                          "catch": [{"error": "X", "body": [{"op": "call", "action": "R"}]}]}]),
                 executor=ex, res_gate=ResourceGate())
    st = await t.run()
    check("try_catch_raise", st is VmStatus.DONE and names(ex) == ["R"], f"{st} {names(ex)}")

    # 10) 未捕获 raise -> ERROR
    t = VmThread(script("uz", [], [{"op": "raise", "error": "Z"}]),
                 executor=FakeExecutor(), res_gate=ResourceGate())
    st = await t.run()
    check("uncaught_raise", st is VmStatus.ERROR, str(st))

    # 11) 子脚本 in-out 传参
    sub = script("sub", [{"name": "inp", "scope": "local", "type": "INT", "io": "in", "default": 0},
                         {"name": "outp", "scope": "local", "type": "INT", "io": "out", "default": 0}],
                 [{"op": "assign", "target": {"var": "outp"},
                   "value": {"binop": "+", "left": {"var": "inp"}, "right": {"lit": 100}}}])
    ex = FakeExecutor()
    main = script("main", [{"name": "v", "scope": "local", "type": "INT", "io": "var", "default": 5},
                           {"name": "r", "scope": "local", "type": "INT", "io": "var", "default": 0}],
                  [{"op": "run_script", "script": "sub", "inputs": {"inp": {"var": "v"}},
                    "outputs": {"outp": {"var": "r"}}},
                   {"op": "call", "action": "A", "args": {"z": {"var": "r"}}}])
    t = VmThread(main, executor=ex, res_gate=ResourceGate(), resolve_script=lambda n: {"sub": sub}[n])
    await t.run()
    check("subscript_io", arg_seq(ex, "z") == [105] and rootvar(t, "r") == 105, arg_seq(ex, "z"))

    # 12) 全局变量跨帧共享
    sub2 = script("sub2", [{"name": "g", "scope": "global", "type": "INT", "io": "var", "default": 0}],
                  [{"op": "assign", "target": {"var": "g"},
                    "value": {"binop": "+", "left": {"var": "g"}, "right": {"lit": 1}}}])
    ex = FakeExecutor()
    main2 = script("main2", [{"name": "g", "scope": "global", "type": "INT", "io": "var", "default": 10}],
                   [{"op": "run_script", "script": "sub2"},
                    {"op": "call", "action": "A", "args": {"z": {"var": "g"}}}])
    t = VmThread(main2, executor=ex, res_gate=ResourceGate(), resolve_script=lambda n: {"sub2": sub2}[n])
    await t.run()
    check("global_shared", arg_seq(ex, "z") == [11], arg_seq(ex, "z"))

    # 13) parallel
    ex = FakeExecutor()
    t = VmThread(script("par", [], [{"op": "parallel", "branches": [[{"op": "call", "action": "P1"}],
                                                                    [{"op": "call", "action": "P2"}]]}]),
                 executor=ex, res_gate=ResourceGate())
    st = await t.run()
    check("parallel", st is VmStatus.DONE and set(names(ex)) == {"P1", "P2"}, f"{st} {names(ex)}")

    # 14) 常量写拒绝
    t = VmThread(script("ck", [{"name": "K", "scope": "local", "type": "INT", "io": "const", "default": 1}],
                        [{"op": "assign", "target": {"var": "K"}, "value": {"lit": 2}}]),
                 executor=FakeExecutor(), res_gate=ResourceGate())
    st = await t.run()
    check("const_write_rejected", st is VmStatus.ERROR, str(st))

    print(f"\n共 17 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
