"""mini-VM 调试器离线测试
========================
功能:
    用 VmController + Fake/Slow 执行器验证调试动词: start(step) 停在首叶子、step 逐叶子推进、
    vars 快照、run 跑完、reset 复位、reset 到节点 (跳过设备叶子)、断点停驻、
    stop_after/resume (边界停)、pause(冻结) hold 标记、terminate (终止)、
    从选中行起跑 (run/step 快进至指定 AID, 穿过 assign 不误停).

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_vm_debug_offline
"""

from __future__ import annotations

import asyncio
import sys

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm import controller as vm_controller
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.tests.test_vm_thread_offline import FakeExecutor, names, script


class SlowExecutor:
    """每次调用 await sleep, 供 pause/stop 时序测试."""

    def __init__(self, delay=0.02):
        self.calls = []
        self.delay = delay

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        self.calls.append(name)
        await asyncio.sleep(self.delay)
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE, accepted=True, result={})


class BlockingExecutor:
    """把叶子动作悬停在执行中，供检查完整活动调用链。"""

    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        self.started.set()
        await self.release.wait()
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, result={})


class CatchBlockingExecutor(BlockingExecutor):
    """子脚本动作失败，父 catch 中的 HOLD 动作保持在飞。"""

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        if name == "FAIL":
            return ActionResult(action=name, request_id="x", status=ActionStatus.ERROR,
                                accepted=True, message="预期失败", result={})
        return await super().execute(name, params, request_id=request_id, current_mode=current_mode)


class RaisingExecutor:
    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        raise RuntimeError("驱动越界异常")


def three_calls(vars_=None):
    return script("dbg", vars_ or [], [{"op": "call", "action": "A"},
                                       {"op": "call", "action": "B"},
                                       {"op": "call", "action": "C"}])


async def wait_status(c, run_id, status, tries=400):
    for _ in range(tries):
        if c.state(run_id)["status"] == status:
            return True
        await asyncio.sleep(0.005)
    return False


async def _run() -> int:
    failures: list[str] = []
    check_count = 0

    def check(name, cond, detail=""):
        nonlocal check_count
        check_count += 1
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # 1) start(step) 停在首叶子
    ex = FakeExecutor()
    events: list[dict] = []
    c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append)
    s = await c.start(three_calls(), mode_run="step")
    rid = s["run_id"]
    check("start_step_stopped", s["status"] == "STOPPED" and s["current_aid"] == "b/0", str(s))
    check("step_emits_state_vars",
          any(e["type"] == "vm_state" and e.get("status") == "STOPPED" for e in events)
          and any(e["type"] == "vm_vars" for e in events))

    # 2) step 逐叶子推进
    s = await c.step(rid)
    check("step1", s["current_aid"] == "b/1" and names(ex) == ["A"], f"{s} {names(ex)}")
    s = await c.step(rid)
    check("step2", s["current_aid"] == "b/2" and names(ex) == ["A", "B"], f"{s} {names(ex)}")

    # 3) run 跑完
    await c.run(rid)
    ok = await wait_status(c, rid, "DONE")
    check("run_to_done", ok and names(ex) == ["A", "B", "C"], f"{c.state(rid)} {names(ex)}")

    # 4) vars 快照
    ex2 = FakeExecutor()
    c2 = VmController(executor=ex2, res_gate=ResourceGate())
    s = await c2.start(three_calls([{"name": "k", "scope": "local", "type": "INT", "io": "var", "default": 7}]),
                       mode_run="step")
    first_generation = s["execution_generation"]
    snap = c2.vars(s["run_id"])
    check("vars_snapshot", snap["vars"].get("k", {}).get("value") == 7, str(snap))

    # 5) reset 复位到顶
    s = await c2.reset(s["run_id"])
    check("reset_top", s["status"] == "STOPPED" and s["current_aid"] == "b/0", str(s))
    check("reset_increments_execution_generation",
          s["execution_generation"] == first_generation + 1, str(s))

    # 6) reset 到节点 (跳过 b/0 设备叶子)
    ex3 = FakeExecutor()
    c3 = VmController(executor=ex3, res_gate=ResourceGate())
    r = await c3.start(three_calls(), mode_run="step")
    s = await c3.reset(r["run_id"], aid="b/1")
    check("reset_to_node", s["current_aid"] == "b/1" and names(ex3) == [], f"{s} {names(ex3)}")

    # 7) 断点: 单步起停后设断点再 run, 停在断点
    ex4 = FakeExecutor()
    c4 = VmController(executor=ex4, res_gate=ResourceGate())
    r = await c4.start(three_calls(), mode_run="step")
    c4.set_breakpoints(r["run_id"], ["b/2"])
    await c4.run(r["run_id"])
    ok = await wait_status(c4, r["run_id"], "STOPPED")
    st = c4.state(r["run_id"])
    check("breakpoint", ok and st["current_aid"] == "b/2" and names(ex4) == ["A", "B"], f"{st} {names(ex4)}")

    # 8) stop_after(运行后停止)/resume (慢执行器): 跑完当前动作停在边界, resume 放行下一动作
    se = SlowExecutor(0.02)
    c5 = VmController(executor=se, res_gate=ResourceGate())
    r = await c5.start(three_calls(), mode_run="run")
    await asyncio.sleep(0.005)
    s = await c5.stop_after(r["run_id"])
    check("stop_after_paused", c5.state(r["run_id"])["status"] == "PAUSED" and s["hold"] == "at_boundary",
          f"{c5.state(r['run_id'])} {s}")
    await c5.resume(r["run_id"])
    ok = await wait_status(c5, r["run_id"], "DONE")
    check("resume_done", ok and se.calls == ["A", "B", "C"], f"{c5.state(r['run_id'])} {se.calls}")

    # 8b) pause(冻结): 离线执行器无机器人, 抢发被安全跳过, 但应标记 hold=frozen; resume 续跑至完成
    se_f = SlowExecutor(0.02)
    cf = VmController(executor=se_f, res_gate=ResourceGate())
    rf = await cf.start(three_calls(), mode_run="run")
    sf = await cf.pause(rf["run_id"])
    check("pause_freeze_hold", sf.get("hold") == "frozen", str(sf))
    await cf.resume(rf["run_id"])
    okf = await wait_status(cf, rf["run_id"], "DONE")
    check("freeze_resume_done", okf and se_f.calls == ["A", "B", "C"], f"{cf.state(rf['run_id'])} {se_f.calls}")

    # 9) terminate(终止运行) -> KILLED + operation_failed CANCELLED (stop 为其别名)
    se2 = SlowExecutor(0.05)
    ev2: list[dict] = []
    c6 = VmController(executor=se2, res_gate=ResourceGate(), event_sink=ev2.append)
    r = await c6.start(three_calls(), mode_run="run")
    await asyncio.sleep(0.01)
    s = await c6.terminate(r["run_id"])
    check("terminate_killed", s["status"] == "KILLED", str(s))
    check("terminate_clears_active_nodes", s["active_nodes"] == [], str(s))
    check("terminate_event",
          any(e["type"] == "operation_failed" and e.get("status") == "CANCELLED" for e in ev2), str([e["type"] for e in ev2]))

    # 10) start(run) 从选中行起跑: 跳过 b/0 设备叶子, 从 b/1 跑到完成 (只执行 B, C)
    ex7 = FakeExecutor()
    c7 = VmController(executor=ex7, res_gate=ResourceGate())
    r = await c7.start(three_calls(), mode_run="run", start_aid="b/1")
    ok = await wait_status(c7, r["run_id"], "DONE")
    check("start_run_from_row", ok and names(ex7) == ["B", "C"], f"{c7.state(r['run_id'])} {names(ex7)}")

    # 11) start(step) 从选中行起跑: 快进至 b/1 停驻 (b/0 设备未执行)
    ex8 = FakeExecutor()
    c8 = VmController(executor=ex8, res_gate=ResourceGate())
    s = await c8.start(three_calls(), mode_run="step", start_aid="b/1")
    check("start_step_from_row",
          s["status"] == "STOPPED" and s["current_aid"] == "b/1" and names(ex8) == [], f"{s} {names(ex8)}")

    # 12) 快进穿过 assign 叶子: step 模式从 b/2 起跑, b/0 赋值照常执行 (k=5) 且不误停在它上面, 设备 A 被跳过
    asg = script("dbgA", [{"name": "k", "scope": "local", "type": "INT", "io": "var", "default": 0}],
                 [{"op": "assign", "target": {"var": "k"}, "value": {"lit": 5}},
                  {"op": "call", "action": "A"},
                  {"op": "call", "action": "B"}])
    ex9 = FakeExecutor()
    c9 = VmController(executor=ex9, res_gate=ResourceGate())
    s = await c9.start(asg, mode_run="step", start_aid="b/2")
    snap = c9.vars(s["run_id"])
    check("skip_runs_assign",
          s["status"] == "STOPPED" and s["current_aid"] == "b/2" and names(ex9) == []
          and snap["vars"]["k"]["value"] == 5, f"{s} {names(ex9)} {snap}")

    # 13) step_over(步过): run_script 算 1 步, 子叶子全执行但不下钻停驻, 停回父流程下一叶子 (栈深=1)
    sub_so = script("sub_so", [], [{"op": "call", "action": "C1"}, {"op": "call", "action": "C2"}])
    parent_so = script("par_so", [], [{"op": "run_script", "script": "sub_so"}, {"op": "call", "action": "P1"}])
    ex_so = FakeExecutor()
    c_so = VmController(executor=ex_so, res_gate=ResourceGate(), resolve_script=lambda n: {"sub_so": sub_so}[n])
    s = await c_so.start(parent_so, mode_run="step")
    check("step_over_start", s["current_aid"] == "b/0" and s["stack_depth"] == 1 and names(ex_so) == [], str(s))
    s = await c_so.step_over(s["run_id"])
    check("step_over_runs_sub",
          s["current_aid"] == "b/1" and s["stack_depth"] == 1 and names(ex_so) == ["C1", "C2"],
          f"{s} {names(ex_so)}")

    # 14) step(步入): 下钻子脚本停在子首叶子 (栈深=2, 子叶子尚未执行) —— 与步过对照
    ex_si = FakeExecutor()
    c_si = VmController(executor=ex_si, res_gate=ResourceGate(), resolve_script=lambda n: {"sub_so": sub_so}[n])
    s = await c_si.start(parent_so, mode_run="step")
    s = await c_si.step(s["run_id"])
    check("step_into_descends",
          s["current_aid"] == "b/0" and s["stack_depth"] == 2 and names(ex_si) == [],
          f"{s} {names(ex_si)}")
    check("step_into_keeps_parent_active",
          s["active_nodes"] == [{"script": "par_so", "aid": "b/0", "op": "run_script",
                                  "action": "sub_so"}], str(s["active_nodes"]))

    # 15) 三级同号 AID 活动链: 外层/中层 run_script 与叶子 call 同时在册，完成后全部清空
    leaf_active = script("leaf_active", [], [{"op": "call", "action": "LEAF"}])
    mid_active = script("mid_active", [], [{"op": "run_script", "script": "leaf_active"}])
    root_active = script("root_active", [], [{"op": "run_script", "script": "mid_active"}])
    active_docs = {d["name"]: d for d in (leaf_active, mid_active)}
    blocked = BlockingExecutor()
    c_active = VmController(executor=blocked, res_gate=ResourceGate(),
                            resolve_script=lambda n: active_docs[n])
    r_active = await c_active.start(root_active, mode_run="run")
    await asyncio.wait_for(blocked.started.wait(), timeout=1)
    active_state = c_active.state(r_active["run_id"])
    active_key = [(n["script"], n["aid"], n["op"], n["action"])
                  for n in active_state["active_nodes"]]
    check("nested_active_nodes",
          active_key == [
              ("root_active", "b/0", "run_script", "mid_active"),
              ("mid_active", "b/0", "run_script", "leaf_active"),
              ("leaf_active", "b/0", "call", "LEAF"),
          ], str(active_key))
    active_rehydrate = next(r for r in c_active.active()["runs"]
                            if r["run_id"] == r_active["run_id"])
    check("active_api_rehydrates_chain", active_rehydrate["active_nodes"] == active_state["active_nodes"],
          str(active_rehydrate))
    blocked.release.set()
    await wait_status(c_active, r_active["run_id"], "DONE")
    check("terminal_clears_active_nodes", c_active.state(r_active["run_id"])["active_nodes"] == [],
          str(c_active.state(r_active["run_id"])))

    # 16) 子脚本失败被父 try/catch 接住：失败的 run_script 必须退出活动集合，不能与 catch 动作一起残留高光
    child_fail = script("child_fail", [], [{"op": "call", "action": "FAIL"}])
    root_catch = script("root_catch", [], [{
        "op": "try",
        "body": [{"op": "run_script", "script": "child_fail"}],
        "catch": [{"error": "ERROR", "body": [{"op": "call", "action": "HOLD"}]}],
    }])
    catch_ex = CatchBlockingExecutor()
    catch_events: list[dict] = []
    c_catch = VmController(executor=catch_ex, res_gate=ResourceGate(),
                           resolve_script=lambda n: {"child_fail": child_fail}[n],
                           event_sink=catch_events.append)
    r_catch = await c_catch.start(root_catch, mode_run="run")
    await asyncio.wait_for(catch_ex.started.wait(), timeout=1)
    catch_active = c_catch.state(r_catch["run_id"])["active_nodes"]
    check("caught_child_failure_removes_run_script",
          [(n["script"], n["action"]) for n in catch_active] == [("root_catch", "HOLD")],
          str(catch_active))
    check("caught_child_failure_emits_done",
          any(e["type"] == "vm_node_done" and e.get("op") == "run_script"
              and e.get("status") == "ERROR" for e in catch_events), str(catch_events))
    catch_ex.release.set()
    await wait_status(c_catch, r_catch["run_id"], "DONE")

    # 17) 执行器抛普通异常也必须终态化并从 active API 消失
    c_raise = VmController(executor=RaisingExecutor(), res_gate=ResourceGate())
    r_raise = await c_raise.start(script("root_raise", [], [{"op": "call", "action": "BOOM"}]),
                                  mode_run="run")
    await wait_status(c_raise, r_raise["run_id"], "ERROR")
    raise_state = c_raise.state(r_raise["run_id"])
    check("unexpected_exception_terminal", raise_state["status"] == "ERROR"
          and raise_state["active_nodes"] == [], str(raise_state))
    check("unexpected_exception_not_active",
          all(x["run_id"] != r_raise["run_id"] for x in c_raise.active()["runs"]),
          str(c_raise.active()))

    # 18) 运行态淘汰: 上限设 3, 跑 5 个至完成, 驻留运行数被限且最旧被 forget (state 报无此运行)
    saved_cap = vm_controller._MAX_RETAINED_RUNS
    vm_controller._MAX_RETAINED_RUNS = 3
    try:
        ex_gc = FakeExecutor()
        c_gc = VmController(executor=ex_gc, res_gate=ResourceGate())
        rids = []
        for _ in range(5):
            r = await c_gc.start(three_calls(), mode_run="run")
            await wait_status(c_gc, r["run_id"], "DONE")
            rids.append(r["run_id"])
        check("purge_bounded", len(c_gc._threads) <= 3, f"驻留 {len(c_gc._threads)}")
        evicted = 0
        for rid_ in rids:
            try:
                c_gc.state(rid_)
            except KeyError:
                evicted += 1
        check("purge_evicts_oldest", evicted == len(rids) - len(c_gc._threads), f"淘汰 {evicted}")

        # 19) 未终结运行绝不淘汰: 一个慢运行仍在跑, 灌满快运行后它仍在册
        se_gc = SlowExecutor(0.05)
        c_live = VmController(executor=se_gc, res_gate=ResourceGate())
        live = await c_live.start(three_calls(), mode_run="run")   # 慢, 不会立即 DONE
        for _ in range(5):
            r = await c_live.start(three_calls(), mode_run="step")  # step 停在首叶, 也非 FINAL
        # 慢运行未终结, 必仍在册
        check("purge_keeps_running", live["run_id"] in c_live._threads, "运行中被误淘汰")
    finally:
        vm_controller._MAX_RETAINED_RUNS = saved_cap

    print(f"\n共 {check_count} 用例, 失败 {len(failures)}")
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
