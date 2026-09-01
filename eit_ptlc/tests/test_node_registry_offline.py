"""设备节点注册表离线测试
==========================
功能:
    验证 derive_health 健康派生 (plc_station / robot)、NodeRegistry 快照与单节点失败兜底为
    offline、build_node_registry 由 fake 控制器构建节点并正确序列化机器人快照,
    以及 Develop 工位附加数组镜像 (Tank_State/Tank_Drain_Done) 的透出与读失败兜底.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_node_registry_offline
"""

from __future__ import annotations

import asyncio
import sys

from eit_ptlc.driver.robot_transport import RobotFeedback, ToolState
from eit_ptlc.runtime.node_registry import (
    NodeRegistry,
    NodeSpec,
    build_node_registry,
    derive_health,
)


class _FakeRobot:
    """fake 机器人: query 返回固定 RobotFeedback."""

    speed_factor = 20   # 遥测回显全局速度比 (与 RobotController.speed_factor 对齐)

    def query(self) -> RobotFeedback:
        return RobotFeedback(
            pose=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0), joint=(0.0,) * 6, check_result=0, last_action=24,
            tool_state=ToolState(commanded_bits=0, actual_bits=0, di_bits=0, di_available=False, di_confirmed=False),
            robot_mode=5, connected=True,
        )


class _FakePlc:
    """fake PLC: Collect 工位置 ERROR (State=40), 其余 IDLE; 附加标量/数组镜像可控.

    Tank_State 造成 1 号缸 =98 (DrainedIdle), 复刻"排液秒 DONE"现场;
    Tank_Drain_Done 故意抛错, 验证单数组未下装不打掉整个工位节点遥测。
    """

    async def snapshot(self, station: str) -> dict:
        state = 40 if station == "Collect" else 0
        return {"State": state, "ActiveCode": 0, "AcceptedSeq": 0, "CompletedSeq": 0,
                "Step": 0, "ErrorCode": 0, "SafeState": 0, "Retryable": False}

    async def read_host_var(self, name: str):
        return True

    async def read_host_array(self, name: str) -> list:
        if name == "Tank_State":
            return [98, 0, 0, 0, 0, 0, 0, 0]
        raise KeyError(f"节点未下装: {name}")


async def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # ---- derive_health: plc_station ----
    check("plc_idle_ok", derive_health("plc_station", {"State": 0}) == "ok")
    check("plc_running_busy", derive_health("plc_station", {"State": 10}) == "busy")
    check("plc_done_ok", derive_health("plc_station", {"State": 20}) == "ok")
    check("plc_rejected_error", derive_health("plc_station", {"State": 30}) == "error")
    check("plc_error_error", derive_health("plc_station", {"State": 40}) == "error")
    check("plc_interrupted_error", derive_health("plc_station", {"State": 50}) == "error")
    check("plc_recovery_error", derive_health("plc_station", {"State": 0, "SafeState": 90}) == "error")

    # ---- derive_health: robot ----
    check("robot_ok", derive_health("robot", {"connected": True, "check_result": 0, "error_ids": []}) == "ok")
    check("robot_offline", derive_health("robot", {"connected": False}) == "offline")
    check("robot_alarm_error", derive_health("robot", {"connected": True, "error_ids": [5]}) == "error")
    check("robot_check_error", derive_health("robot", {"connected": True, "check_result": 3}) == "error")

    # ---- NodeRegistry: ok + 取快照失败兜底 offline ----
    async def ok_reader() -> dict:
        return {"State": 0}

    async def boom_reader() -> dict:
        raise RuntimeError("链路断开")

    reg = NodeRegistry([NodeSpec("a", "甲", "plc_station", ok_reader),
                        NodeSpec("b", "乙", "plc_station", boom_reader)])
    snaps = await reg.snapshot_all()
    check("snapshot_all_order", [s["id"] for s in snaps] == ["a", "b"], str([s["id"] for s in snaps]))
    check("snapshot_ok", snaps[0]["health"] == "ok", str(snaps[0]))
    check("snapshot_offline", snaps[1]["health"] == "offline" and "error" in snaps[1]["data"], str(snaps[1]))
    check("snapshot_one", (await reg.snapshot("a"))["label"] == "甲", "")
    check("snapshot_unknown", await reg.snapshot("zzz") is None, "")
    check("descriptors", reg.descriptors() == [{"id": "a", "label": "甲", "kind": "plc_station"},
                                               {"id": "b", "label": "乙", "kind": "plc_station"}], str(reg.descriptors()))

    # ---- build_node_registry: robot + 三工位 ----
    built = build_node_registry(robot=_FakeRobot(), plc=_FakePlc(),
                                stations=("Sampling", "Collect", "Develop"))
    check("built_ids", built.list_ids() == ["robot", "plc.sampling", "plc.collect", "plc.develop"],
          str(built.list_ids()))
    by_id = {s["id"]: s for s in await built.snapshot_all()}
    check("built_robot_ok", by_id["robot"]["health"] == "ok", str(by_id["robot"]))
    check("built_robot_pose", by_id["robot"]["data"]["pose"] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], str(by_id["robot"]["data"]))
    check("built_robot_tool", isinstance(by_id["robot"]["data"]["tool_state"], dict), str(by_id["robot"]["data"].get("tool_state")))
    check("built_sampling_ok", by_id["plc.sampling"]["health"] == "ok", str(by_id["plc.sampling"]))
    check("built_collect_error", by_id["plc.collect"]["health"] == "error", str(by_id["plc.collect"]))

    # ---- Develop 附加数组镜像: Tank_State 透出 + 单数组读失败不打掉节点 ----
    develop = by_id["plc.develop"]["data"]
    check("develop_tank_state", develop.get("Tank_State") == [98, 0, 0, 0, 0, 0, 0, 0], str(develop.get("Tank_State")))
    check("develop_tank_done_none", develop.get("Tank_Drain_Done", "缺键") is None, str(develop.get("Tank_Drain_Done", "缺键")))
    check("develop_scalar_mirror", develop.get("Expand_Waste_Empty_G1") is True, str(develop.get("Expand_Waste_Empty_G1")))
    check("develop_health_ok", by_id["plc.develop"]["health"] == "ok", str(by_id["plc.develop"]["health"]))

    # ---- 非 Develop 工位不带展缸阵列 (表驱动只对 Develop 生效) ----
    check("sampling_no_tank_array", "Tank_State" not in by_id["plc.sampling"]["data"],
          str(by_id["plc.sampling"]["data"].keys()))

    print(f"\n共 28 用例, 失败 {len(failures)}")
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
