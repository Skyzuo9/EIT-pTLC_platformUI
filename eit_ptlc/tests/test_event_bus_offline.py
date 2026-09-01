"""事件总线离线测试
==================
功能:
    验证 EventBus 满载丢弃策略: 只挤掉可丢类型 (telemetry/vm_vars), 运行生命周期事件
    (operation_*/vm_node_*/vm_state 等) 保证送达且保序; 全运行事件积压允许临时超限;
    空队列消费端挂起等待; 退订后不再投递; 慢订阅者不影响其它订阅者;
    运行事件积压超硬上限 (4x max) 宁断不丢: 标死清缓冲, get 抛错促使连接关闭重连补种.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_event_bus_offline
"""

from __future__ import annotations

import asyncio
import sys

from eit_ptlc.runtime.events import EventBus


def _telemetry(i: int) -> dict:
    return {"type": "telemetry", "node": "robot", "health": "ok", "data": {"i": i}, "ts": float(i)}


def _vars(i: int) -> dict:
    return {"type": "vm_vars", "run_id": "r1", "vars": {"i": i}, "ts": float(i)}


def _robot_pose(i: int) -> dict:
    return {"type": "robot_pose", "joint": [float(i)] * 6, "pose": [0.0] * 6,
            "tool": 1, "ts": float(i), "seq": i}


def _axis_pose(i: int) -> dict:
    return {"type": "axis_pose", "positions": {"axis_11y": float(i)}, "ts": float(i), "seq": i}


def _mechanism_state(i: int) -> dict:
    return {"type": "mechanism_state", "states": {"ps_shade": {"commanded": bool(i % 2)}},
            "ts": float(i), "seq": i}


def _enter(aid: str) -> dict:
    return {"type": "vm_node_enter", "run_id": "r1", "aid": aid, "op": "call", "ts": 0.0}


def _done(aid: str) -> dict:
    return {"type": "vm_node_done", "run_id": "r1", "aid": aid, "op": "call", "status": "DONE", "ts": 0.0}


async def _drain(queue, n: int) -> list[dict]:
    """消费 n 条事件 (每条限时, 防止用例死等)."""
    out = []
    for _ in range(n):
        out.append(await asyncio.wait_for(queue.get(), timeout=1.0))
    return out


async def _run_async(check) -> None:
    # 基本投递保序
    bus = EventBus(max_queue=10)
    async with bus.subscribe() as q:
        for aid in ("b/0", "b/1", "b/2"):
            bus.publish(_enter(aid))
        got = await _drain(q, 3)
        check("fifo_order", [e["aid"] for e in got] == ["b/0", "b/1", "b/2"], str(got))

    # 满载只挤可丢类型: 5 条遥测占满后, 运行事件逐条挤掉最旧遥测, 新遥测同样挤旧遥测
    bus = EventBus(max_queue=5)
    async with bus.subscribe() as q:
        for i in range(5):
            bus.publish(_telemetry(i))          # 队列: t0..t4 (满)
        bus.publish(_enter("b/7"))              # 挤 t0
        bus.publish(_done("b/7"))               # 挤 t1
        bus.publish({"type": "operation_done", "run_id": "r1", "status": "DONE", "ts": 9.0})  # 挤 t2
        bus.publish(_telemetry(5))              # 挤 t3
        got = await _drain(q, 5)
        types = [e["type"] for e in got]
        check("evict_droppable_only",
              types == ["telemetry", "vm_node_enter", "vm_node_done", "operation_done", "telemetry"],
              str(types))
        check("terminal_survives", any(e["type"] == "operation_done" for e in got), str(types))
        check("oldest_telemetry_evicted",
              [e["data"]["i"] for e in got if e["type"] == "telemetry"] == [4, 5], str(got))

    # vm_vars 亦可丢 (最新快照即全部语义)
    bus = EventBus(max_queue=2)
    async with bus.subscribe() as q:
        bus.publish(_vars(0))
        bus.publish(_enter("b/0"))              # 队列满: [vars, enter]
        bus.publish(_done("b/0"))               # 挤 vars
        got = await _drain(q, 2)
        check("vm_vars_droppable",
              [e["type"] for e in got] == ["vm_node_enter", "vm_node_done"], str(got))

    # 20 Hz robot_pose 同样是最新快照语义；慢客户端只保留最新帧，运行事件不丢。
    bus = EventBus(max_queue=2)
    async with bus.subscribe() as q:
        bus.publish(_robot_pose(1))
        bus.publish(_robot_pose(2))
        bus.publish(_enter("b/pose"))
        got = await _drain(q, 2)
        check("robot_pose_droppable",
              [event["type"] for event in got] == ["robot_pose", "vm_node_enter"]
              and got[0]["seq"] == 2, str(got))

    # 新增两类孪生快照同样只能挤旧快照，不能挤运行生命周期事件。
    for factory, label in ((_axis_pose, "axis_pose"), (_mechanism_state, "mechanism_state")):
        bus = EventBus(max_queue=2)
        async with bus.subscribe() as q:
            bus.publish(factory(1))
            bus.publish(factory(2))
            bus.publish(_enter(f"b/{label}"))
            got = await _drain(q, 2)
            check(f"{label}_droppable",
                  [event["type"] for event in got] == [label, "vm_node_enter"]
                  and got[0]["seq"] == 2, str(got))

    # 全运行事件积压: 无可丢事件时允许临时超限, 一条不丢
    bus = EventBus(max_queue=3)
    async with bus.subscribe() as q:
        for i in range(6):
            bus.publish(_enter(f"b/{i}"))
        got = await _drain(q, 6)
        check("run_events_never_dropped", [e["aid"] for e in got] == [f"b/{i}" for i in range(6)], str(got))

    # 空队列挂起等待, publish 后唤醒
    bus = EventBus(max_queue=5)
    async with bus.subscribe() as q:
        waiter = asyncio.create_task(q.get())
        await asyncio.sleep(0)                   # 让 waiter 进入挂起
        check("get_pending_when_empty", not waiter.done(), "")
        bus.publish(_enter("b/9"))
        got = await asyncio.wait_for(waiter, timeout=1.0)
        check("get_wakes_on_publish", got["aid"] == "b/9", str(got))

    # 退订后不再投递
    check("unsubscribed", bus.subscriber_count == 0, str(bus.subscriber_count))
    bus.publish(_enter("b/x"))                   # 无订阅者: 不抛错即可

    # 慢订阅者 (满载) 不影响其它订阅者收全量
    bus = EventBus(max_queue=2)
    async with bus.subscribe() as slow, bus.subscribe() as fast:
        for i in range(4):
            bus.publish(_telemetry(i))
            got = await asyncio.wait_for(fast.get(), timeout=1.0)   # fast 及时消费
            check_ok = got["data"]["i"] == i
            if not check_ok:
                check(f"fast_gets_{i}", False, str(got))
        check("fast_all_delivered", True, "")
        slow_got = await _drain(slow, 2)          # slow 只剩最新 2 条遥测
        check("slow_capped", [e["data"]["i"] for e in slow_got] == [2, 3], str(slow_got))

    # 宁断不丢: 运行事件积压达硬上限 (4x max) -> 标死清缓冲护内存, get 抛错促使连接关闭
    bus = EventBus(max_queue=2)
    async with bus.subscribe() as q:
        for i in range(9):                        # 第 9 条 put 时 len=8 >= 2*4, 触发标死
            bus.publish(_enter(f"b/{i}"))
        try:
            await asyncio.wait_for(q.get(), timeout=1.0)
            check("dead_sub_get_raises", False, "get 未抛错")
        except RuntimeError:
            check("dead_sub_get_raises", True, "")
        bus.publish(_enter("b/9"))                # 标死后 put 变 no-op (不抛错不积压)
        try:
            await asyncio.wait_for(q.get(), timeout=0.2)
            check("dead_sub_stays_dead", False, "标死后仍取到事件")
        except RuntimeError:
            check("dead_sub_stays_dead", True, "")

    # 标死前挂起中的 get 被唤醒并立刻抛错 (不永久悬挂)
    bus = EventBus(max_queue=1)
    async with bus.subscribe() as q:
        waiter = asyncio.create_task(q.get())
        await asyncio.sleep(0)                    # waiter 进入挂起
        for i in range(5):                        # len=4 >= 1*4 时标死并 set 唤醒
            bus.publish(_enter(f"b/{i}"))
        try:
            await asyncio.wait_for(waiter, timeout=1.0)
            # 标死前 waiter 可能已取走首条 (b/0): 属正常时序, 再 get 必抛错
            try:
                await asyncio.wait_for(q.get(), timeout=1.0)
                check("pending_get_wakes_dead", False, "标死后 get 未抛错")
            except RuntimeError:
                check("pending_get_wakes_dead", True, "")
        except RuntimeError:
            check("pending_get_wakes_dead", True, "")

    # 死订阅者隔离: 不影响其它订阅者收全量, 也不影响总线继续投递
    bus = EventBus(max_queue=2)
    async with bus.subscribe() as doomed, bus.subscribe() as healthy:
        healthy_ok = True
        for i in range(9):
            bus.publish(_enter(f"b/{i}"))
            got = await asyncio.wait_for(healthy.get(), timeout=1.0)   # healthy 及时消费
            if got["aid"] != f"b/{i}":
                healthy_ok = False
        check("healthy_unaffected_by_dead_peer", healthy_ok, "")
        try:
            await asyncio.wait_for(doomed.get(), timeout=1.0)
            check("doomed_dies_alone", False, "应已标死")
        except RuntimeError:
            check("doomed_dies_alone", True, "")
    check("all_unsubscribed_after_dead", bus.subscriber_count == 0, str(bus.subscriber_count))


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    asyncio.run(_run_async(check))

    print(f"\n失败 {len(failures)}")
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
