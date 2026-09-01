"""mini-VM 人工介入 (HITL) 离线测试
==================================
功能:
    验证 human 节点: 发出 vm_human_request 并挂起 (WAITING_HUMAN), 回复后绑定变量并继续;
    confirm 取消触发 raise; 等待人工时 stop 可中止.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_vm_human_offline
"""

from __future__ import annotations

import asyncio
import sys

from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.tests.test_vm_debug_offline import wait_status
from eit_ptlc.tests.test_vm_thread_offline import FakeExecutor, arg_seq, script


def _req_id(events):
    return next(e for e in events if e["type"] == "vm_human_request")["req_id"]


async def _run() -> int:
    failures: list[str] = []

    def check(name, cond, detail=""):
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # 1) input 类型: 挂起 -> 回复绑定变量 -> 继续执行
    ex = FakeExecutor()
    events: list[dict] = []
    doc = script("hin", [{"name": "note", "scope": "local", "type": "STRING", "io": "var", "default": ""}],
                 [{"op": "human", "kind": "input", "prompt": {"lit": "请输入备注"},
                   "fields": [{"var": "note"}]},
                  {"op": "call", "action": "A", "args": {"n": {"var": "note"}}}])
    c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append)
    s = await c.start(doc, mode_run="run")
    rid = s["run_id"]
    ok = await wait_status(c, rid, "WAITING_HUMAN")
    check("waiting_human", ok, c.state(rid))
    check("human_request_event", any(e["type"] == "vm_human_request" for e in events))

    res = await c.human_reply(rid, _req_id(events), {"values": {"note": "已就位"}})
    check("reply_accepted", res["accepted"] is True, str(res))
    ok = await wait_status(c, rid, "DONE")
    check("resume_after_reply", ok and arg_seq(ex, "n") == ["已就位"], f"{c.state(rid)} {arg_seq(ex,'n')}")

    # 出门对称广播 (patch A): 回复后必须紧跟一条 vm_state=RUNNING, 否则前端徽标会冻在 WAITING_HUMAN,
    # 直到下一条稀疏 vm_state —— 门后进长 plc_l2 动作时看着像"卡死在等待人工"。
    reply_idx = next(i for i, e in enumerate(events) if e["type"] == "vm_human_reply")
    tail = events[reply_idx + 1:]
    first_state = next((e for e in tail if e["type"] == "vm_state"), None)
    check("state_running_after_reply",
          first_state is not None and first_state["status"] == "RUNNING",
          f"回复后首个 vm_state={first_state}")

    # 2) confirm 取消 -> raise HUMAN_CANCELLED -> ERROR
    ex2 = FakeExecutor()
    ev2: list[dict] = []
    doc2 = script("hc", [{"name": "ch", "scope": "local", "type": "STRING", "io": "var", "default": ""}],
                  [{"op": "human", "kind": "confirm", "prompt": {"lit": "确认?"},
                    "assign_choice": {"var": "ch"}, "on_cancel": "raise"}])
    c2 = VmController(executor=ex2, res_gate=ResourceGate(), event_sink=ev2.append)
    s = await c2.start(doc2, mode_run="run")
    await wait_status(c2, s["run_id"], "WAITING_HUMAN")
    await c2.human_reply(s["run_id"], _req_id(ev2), {"choice": "cancel"})
    ok = await wait_status(c2, s["run_id"], "ERROR")
    check("confirm_cancel_raises", ok, c2.state(s["run_id"]))

    # 3) 等待人工时 stop -> KILLED
    ex3 = FakeExecutor()
    doc3 = script("hk", [], [{"op": "human", "kind": "confirm", "prompt": {"lit": "等待"}}])
    c3 = VmController(executor=ex3, res_gate=ResourceGate())
    s = await c3.start(doc3, mode_run="run")
    await wait_status(c3, s["run_id"], "WAITING_HUMAN")
    s = await c3.stop(s["run_id"])
    check("stop_while_waiting", s["status"] == "KILLED", str(s))

    # 4) pending_human 可重建: 门挂起时 state 携带与事件一致的请求全文; 连门 req_id 更新; 终态清空
    ex4 = FakeExecutor()
    ev4: list[dict] = []
    doc4 = script("hp", [{"name": "note", "scope": "local", "type": "STRING", "io": "var", "default": ""}],
                  [{"op": "human", "kind": "input", "prompt": {"lit": "第一道门"},
                    "fields": [{"var": "note"}]},
                   {"op": "human", "kind": "confirm", "prompt": {"lit": "第二道门"}}])
    c4 = VmController(executor=ex4, res_gate=ResourceGate(), event_sink=ev4.append)
    s = await c4.start(doc4, mode_run="run")
    rid4 = s["run_id"]
    await wait_status(c4, rid4, "WAITING_HUMAN")
    st = c4.state(rid4)
    evreq = next(e for e in ev4 if e["type"] == "vm_human_request")
    expect = {k: evreq[k] for k in ("req_id", "kind", "prompt", "fields", "image", "options", "context", "aid")}
    check("pending_human_matches_event", st.get("pending_human") == expect,
          f"state={st.get('pending_human')} event={expect}")
    await c4.human_reply(rid4, evreq["req_id"], {"values": {"note": "ok"}})
    ok = await wait_status(c4, rid4, "WAITING_HUMAN")
    st2 = c4.state(rid4)
    check("pending_human_second_gate",
          ok and bool(st2.get("pending_human")) and st2["pending_human"]["req_id"] != evreq["req_id"]
          and st2["pending_human"]["prompt"] == "第二道门", str(st2.get("pending_human")))
    await c4.human_reply(rid4, st2["pending_human"]["req_id"], {"choice": "ok"})
    ok = await wait_status(c4, rid4, "DONE")
    check("pending_human_cleared_after_done", ok and c4.state(rid4).get("pending_human") is None,
          str(c4.state(rid4)))

    # 5) active(): 门挂起时列出非终态 run (含 operation 与 pending_human); 终态后出列
    ex5 = FakeExecutor()
    doc5 = script("ha", [], [{"op": "human", "kind": "confirm", "prompt": {"lit": "在吗"}}])
    c5 = VmController(executor=ex5, res_gate=ResourceGate())
    check("active_empty_initially", c5.active() == {"runs": []}, str(c5.active()))
    s = await c5.start(doc5, mode_run="run")
    rid5 = s["run_id"]
    await wait_status(c5, rid5, "WAITING_HUMAN")
    act = c5.active()["runs"]
    check("active_lists_waiting_run",
          len(act) == 1 and act[0]["run_id"] == rid5 and act[0]["operation"] == "ha"
          and act[0]["status"] == "WAITING_HUMAN" and act[0]["pending_human"]["prompt"] == "在吗",
          str(act))
    await c5.human_reply(rid5, act[0]["pending_human"]["req_id"], {"choice": "ok"})
    await wait_status(c5, rid5, "DONE")
    check("active_excludes_final", c5.active() == {"runs": []}, str(c5.active()))

    # 6) 契约锁: 门挂起时 terminate → 终态出 active 列表且 pending_human 清空;
    #    step 停驻 (STOPPED, 无门) 是非终态 → 在列且 pending_human 为 None
    ex6 = FakeExecutor()
    doc6 = script("ht", [], [{"op": "human", "kind": "confirm", "prompt": {"lit": "等待"}}])
    c6 = VmController(executor=ex6, res_gate=ResourceGate())
    s = await c6.start(doc6, mode_run="run")
    rid6 = s["run_id"]
    await wait_status(c6, rid6, "WAITING_HUMAN")
    s = await c6.stop(rid6)
    check("terminate_clears_pending",
          s["status"] == "KILLED" and c6.state(rid6).get("pending_human") is None
          and c6.active() == {"runs": []}, f"{s} {c6.state(rid6).get('pending_human')}")

    ex7 = FakeExecutor()
    doc7 = script("hs", [], [{"op": "call", "action": "A", "args": {}}])
    c7 = VmController(executor=ex7, res_gate=ResourceGate())
    s = await c7.start(doc7, mode_run="step")
    rid7 = s["run_id"]
    act = c7.active()["runs"]
    check("active_lists_stopped_no_gate",
          len(act) == 1 and act[0]["run_id"] == rid7 and act[0]["status"] == "STOPPED"
          and act[0]["pending_human"] is None, str(act))
    await c7.stop(rid7)

    print(f"\n共 15 用例, 失败 {len(failures)}")
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
