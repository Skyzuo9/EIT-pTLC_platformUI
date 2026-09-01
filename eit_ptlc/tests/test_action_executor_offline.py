"""动作层离线测试
================
功能:
    验证 ActionRegistry 加载 + ActionExecutor 统一调度: 机器人原子 (fake 传输) 与
    PLC L2 (Mock FSM) 都归一为 ActionResult; 模式门控 / 参数校验 / 必填缺失 拒绝路径.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_action_executor_offline
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from eit_ptlc.action.executor import ActionExecutor
from eit_ptlc.action.models import ActionStatus, RejectCode
from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.config.loader import load_plc_nodes
from eit_ptlc.controller.calibration_service import CalibrationService
from eit_ptlc.controller.plate_catalog import PlateCatalog
from eit_ptlc.controller.plc_controller import PlcController
from eit_ptlc.controller.point_registry import PointRegistry
from eit_ptlc.controller.points_service import PointsService
from eit_ptlc.controller.robot_controller import RobotController
from eit_ptlc.driver.opcua_driver import OpcUaDriver
from eit_ptlc.driver.robot_transport import RobotActionError, RobotTransportError
from eit_ptlc.mock.plc_server import build_mock_server, run_l2_fsm
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.tests.test_robot_controller_offline import _RecordingTransport

_CFG = Path(__file__).resolve().parent.parent / "config"
_URL = "opc.tcp://127.0.0.1:48479/eit_ptlc/mock/"


async def _run() -> int:
    failures: list[str] = []
    tally = {"n": 0}

    def check(name: str, cond: bool, detail: str = "") -> None:
        tally["n"] += 1
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    registry = ActionRegistry.load(_CFG / "actions")
    check("registry_loaded", len(registry) >= 8, f"len={len(registry)}")

    # ---- Part A: 机器人原子动作 (fake 传输) ----
    pts = PointRegistry.load(_CFG / "points" / "robot" / "robot_points.json", source_version="v0.11",
                             meta_path=_CFG / "points" / "robot" / "robot_points_meta.json")
    t = _RecordingTransport()
    robot = RobotController(t, pts, home_point="robot-main.home")
    ex = ActionExecutor(registry, robot=robot)

    r = await ex.execute("robot.jog_start", {"axis_id": "X+"}, current_mode="DEBUG")
    check("robot_jog", r.status is ActionStatus.DONE and t.calls[-1][0] == "jog_start", str(r.status))

    r = await ex.execute("robot.step", {"axis": "Z", "distance": -2.0}, current_mode="DEBUG")
    check("robot_step", r.status is ActionStatus.DONE and t.calls[-1] == ("step", "Z", -2.0, "l"), str(t.calls[-1]))

    r = await ex.execute("robot.move_to_point",
                         {"point_id_or_robot_name": "robot-main.home", "motion": "move_j"},
                         current_mode="DEBUG")
    check("robot_move", r.status is ActionStatus.DONE and "joint" in r.result, str(r.status))

    r = await ex.execute("robot.jog_start", {"axis_id": "X+"}, current_mode="RUN")
    check("mode_gate", r.status is ActionStatus.REJECTED and r.reject_code == RejectCode.MODE_NOT_ALLOWED.value, str(r))

    r = await ex.execute("robot.jog_start", {"axis_id": "BAD"}, current_mode="DEBUG")
    check("invalid_enum", r.status is ActionStatus.REJECTED and r.reject_code == RejectCode.INVALID_PARAM.value, str(r))

    r = await ex.execute("robot.step", {}, current_mode="DEBUG")
    check("missing_required", r.status is ActionStatus.REJECTED, str(r))

    # ---- Part A2: 点样几何可选参数 (step ①: None ≡ 未提供) + 成员覆盖透传 push (step ②) ----
    # _validate 直测: None 的可选参数被跳过 (不入 coerced, 使能 base-by-read); 必填给 None 仍报缺失;
    # 给了的值仍强制 min/max (真安全闸)。
    adef_band = registry.get("sampling.spot_band_layer")
    ok_v, coerced_v, _ = ex._validate(adef_band, {"ref_spot": "spot_pose", "x_start": None})
    check("validate_none_optional_skipped", ok_v and "x_start" not in coerced_v, f"{ok_v} {coerced_v}")
    ok2, _, msg2 = ex._validate(adef_band, {"ref_spot": None})
    check("validate_none_required_missing", (not ok2) and "缺少必填" in msg2, msg2)
    ok3, _, _ = ex._validate(adef_band, {"ref_spot": "spot_pose", "x_start": 9999.0})
    check("validate_optional_over_max", not ok3, "x_start=9999 应越上限 500")
    ok4, c4, _ = ex._validate(adef_band, {"ref_spot": "spot_pose", "x_start": 123.0})
    check("validate_optional_value_kept", ok4 and abs(float(c4.get("x_start", -1)) - 123.0) < 1e-9, str(c4))

    # 整链胶合 (假 plc + 假 points): 执行器据 ref_spot 组合成员把同名几何参数从 coerced 弹出作 member_overrides
    # 透传 push_point_ref; 几何不泄漏到 PLC 通道; 未给几何 → member_overrides=None (走点表基准)。
    class _RecPoints:
        def __init__(self) -> None:
            self.pushes: list[tuple] = []

        def sync_group(self, station):
            return None

        def composite_entry(self, key):
            if key != "spot_pose":
                return None
            return SimpleNamespace(members=[SimpleNamespace(key=k) for k in ("x_start", "x_end", "y_height")])

        async def push_point_ref(self, key, member_overrides=None):
            self.pushes.append((key, member_overrides))
            return {"key": key, "written": []}

    class _OkPlc:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        async def execute(self, station, code, channels, *, timeout=None, stall_timeout=None):
            self.calls.append((station, code, dict(channels)))
            return SimpleNamespace(request_seq=1, action_code=code, step=0,
                                   safe_state=SimpleNamespace(name="IDLE"))

    recp, okplc = _RecPoints(), _OkPlc()
    ex3 = ActionExecutor(registry, plc=okplc, points=recp)
    r = await ex3.execute("sampling.spot_band_layer",
                          {"ref_spot": "spot_pose", "x_start": 100.0}, current_mode="RUN")
    leaked = any(k in okplc.calls[-1][2] for k in ("x_start", "x_end", "y_height")) if okplc.calls else True
    check("band_override_forwarded",
          r.status is ActionStatus.DONE and recp.pushes == [("spot_pose", {"x_start": 100.0})] and not leaked,
          f"{r.status} {recp.pushes} leaked={leaked}")
    recp.pushes.clear()
    r = await ex3.execute("sampling.spot_band_layer", {"ref_spot": "spot_pose"}, current_mode="RUN")
    check("band_no_geometry_baseline",
          r.status is ActionStatus.DONE and recp.pushes == [("spot_pose", None)],
          f"{r.status} {recp.pushes}")

    # ---- Part B: PLC L2 动作 (Mock FSM) ----
    node_map = load_plc_nodes(_CFG / "plc_nodes.yaml")
    server = await build_mock_server(_URL, node_map)
    async with server:
        stop = asyncio.Event()
        fsm = asyncio.create_task(run_l2_fsm(server, "Sampling", stop))
        driver = OpcUaDriver(_URL, node_map, reconnect_wait_timeout=5.0, subscription_period_ms=20)
        await driver.connect()
        plc = PlcController(driver, poll_interval=0.02, action_timeout=5.0)
        # points 服务: sampling.spot 含 point_ref 参数, 触发前据其下发 Spot_*_Target (合并自 push_spot_targets)
        points = PointsService(_CFG / "points", pts, driver=driver)
        # 孔位寻址: 注入标定服务 (4×6#1 已标定 → 算 xy 写 *_Target); calibration_path 仅 commit 用, 本测试不 commit
        calib = CalibrationService(
            PlateCatalog.load(_CFG / "plates.yaml", _CFG / "calibration.yaml"),
            driver, _CFG / "calibration.yaml")
        ex2 = ActionExecutor(registry, plc=plc, points=points, calibration=calib)
        try:
            r = await ex2.execute("sampling.init", current_mode="RUN")
            check("plc_l2_init", r.status is ActionStatus.DONE and r.action == "sampling.init", str(r))
            # 点样: 显式传组合点位引用, 执行前展开为各成员 push 到 PLC, 再触发动作 60
            r = await ex2.execute("sampling.spot",
                                  {"ref_spot": "spot_pose"},
                                  current_mode="RUN")
            check("plc_l2_spot", r.status is ActionStatus.DONE, str(r))
            # 吸液: (规格+盘位号+孔) → 标定算 xy 写 Sampling_4X/3Y_Target (非裸索引); 4×6#1 A1 → X=23.0
            r = await ex2.execute("sampling.aspirate",
                                  {"plate_spec": "4×6", "plate_no": "1", "well": "A1"},
                                  current_mode="RUN")
            t4x = float(await driver.read_variable("Sampling_4X_Target"))
            xc = int(await driver.read_variable("Sampling_X_coordinate"))
            check("plc_l2_aspirate", r.status is ActionStatus.DONE, str(r))
            check("aspirate_writes_target", abs(t4x - 23.0) < 1e-6, f"4X_Target={t4x}")
            check("aspirate_no_coordinate", xc == 0, f"X_coordinate={xc} (应保持 0, 不再写裸索引)")
            # 润洗混匀复用同一孔位寻址块；孔位参数由执行器消费，不泄漏到 PLC 通道。
            r = await ex2.execute(
                "sampling.rinse_mix",
                {
                    "plate_spec": "4×6", "plate_no": "1", "well": "A1",
                    "rinse_volume_ml": 2.0, "mix_volume_ml": 1.5, "mix_count": 3,
                },
                current_mode="RUN",
            )
            t4x_rinse = float(await driver.read_variable("Sampling_4X_Target"))
            rinse_cmds = await driver.read_array("Sampling_rinse_mix_instructions")
            check(
                "rinse_mix_writes_target_and_code55",
                r.status is ActionStatus.DONE and abs(t4x_rinse - 23.0) < 1e-6
                and r.result.get("action_code") == 55,
                f"result={r.result} target={t4x_rinse}",
            )
            check(
                "rinse_mix_channels_no_plate_params",
                len(rinse_cmds) == 4
                and int(await driver.read_variable("Sampling_rinse_mix_count")) == 3,
                f"commands={rinse_cmds}",
            )
            # 未标定规格盘位 (6×8#1 points 空) → 拒绝, 不兜底
            r = await ex2.execute("sampling.aspirate",
                                  {"plate_spec": "6×8", "plate_no": "1", "well": "A1"},
                                  current_mode="RUN")
            check("aspirate_uncalibrated_reject",
                  r.status is ActionStatus.REJECTED and r.reject_code == RejectCode.INVALID_PARAM.value, str(r))
            r = await ex2.execute(
                "sampling.rinse_mix",
                {
                    "plate_spec": "6×8", "plate_no": "1", "well": "A1",
                    "rinse_volume_ml": 2.0, "mix_volume_ml": 1.5, "mix_count": 3,
                },
                current_mode="RUN",
            )
            check(
                "rinse_mix_uncalibrated_reject",
                r.status is ActionStatus.REJECTED and r.reject_code == RejectCode.INVALID_PARAM.value,
                str(r),
            )
        finally:
            stop.set()
            await fsm
            await driver.disconnect()

    # ---- Part C: 机器人中止原语 best-effort (机器人 offline/断链不阻断 terminate/reset/estop) ----
    # 置于 PLC 段之后, 避免其 _settle 轮询扰动 Mock L2 FSM 的 seq 时序 (与本用例无关的既有敏感点)。
    # 真机机器人连不上时 RobotController 仍被构造 (bootstrap 不阻断起服), executor._robot 非 None;
    # 中止类命令 (stop/pause/resume/estop) 的目的是让臂停下, 臂够不着即已停 —— 连接级失败必须降级跳过,
    # 否则 VmController.terminate/reset/estop 会被抛错整体阻断 (真机现场"点复位无效、报错反复"即此)。
    class _OfflineRobot:  # 中止类命令一律抛"未连接" (RobotTransportError 基类 = 链路级)
        def stop(self): raise RobotTransportError("机器人 TCP transport 未连接")
        def pause(self): raise RobotTransportError("机器人 TCP transport 未连接")
        def resume(self): raise RobotTransportError("机器人 TCP transport 未连接")
        def emergency_stop(self, pressed=True): raise RobotTransportError("机器人 TCP transport 未连接")

    ex_off = ActionExecutor(registry, robot=_OfflineRobot())
    try:
        await ex_off.robot_stop(); await ex_off.robot_pause()
        await ex_off.robot_resume(); await ex_off.robot_estop()
        check("preempt_offline_swallow", True)
    except Exception as exc:  # noqa: BLE001
        check("preempt_offline_swallow", False, f"离线中止不应抛, 却抛 {exc!r}")

    class _RejectingRobot:  # 在线但拒绝命令 (RobotActionError 子类)
        def stop(self): raise RobotActionError(1, 1, "机器人拒绝 Stop")
        def pause(self): raise RobotActionError(-1, -1, "机器人拒绝 Pause: -1,{},Pause();")
        def resume(self): raise RobotActionError(-1, -1, "机器人拒绝 Continue: -1,{},Continue();")

    reraised = False
    try:
        await ActionExecutor(registry, robot=_RejectingRobot()).robot_stop()
    except RobotActionError:
        reraised = True
    check("preempt_reject_reraise", reraised, "在线拒绝 (RobotActionError) 应上抛, 却被吞")

    # pause/resume (strict=False): 无在飞运动时机器人拒 Pause/Continue (ErrorID=-1) 属良性空操作,
    # 不得上抛打断流程 (对空闲臂"冻结/续跑"的意图本就已满足)。区别于 stop/estop 的厳格上抛。
    try:
        rej = ActionExecutor(registry, robot=_RejectingRobot())
        await rej.robot_pause(); await rej.robot_resume()
        check("preempt_pause_reject_swallow", True)
    except Exception as exc:  # noqa: BLE001
        check("preempt_pause_reject_swallow", False, f"pause/resume 被拒不应上抛, 却抛 {exc!r}")

    # 端到端: 机器人 offline 下 VmController.terminate/reset 能正常收尾 (不再被抛错阻断)。
    # step 模式停在 call 叶子 (未执行, 故 action 名不必真存在); terminate/reset 内部走 robot_stop。
    vc = VmController(executor=ActionExecutor(registry, robot=_OfflineRobot()), res_gate=ResourceGate())
    demo = {"schema": "ptlc.script/v1", "kind": "operation", "name": "off", "label": "off", "vars": [],
            "body": [{"op": "comment", "text": "prepare"}, {"op": "call", "action": "photoscrape.init"}]}
    s = await vc.start(demo, mode_run="step")
    check("vm_start_offline_stopped", s["status"] == "STOPPED" and s["current_aid"] == "b/1", str(s))
    st = await vc.terminate(s["run_id"])
    check("vm_terminate_offline_ok", st["status"] == "KILLED", str(st))
    s2 = await vc.reset(s["run_id"])
    check("vm_reset_offline_ok", s2["status"] == "STOPPED" and s2["current_aid"] == "b/1", str(s2))
    await vc.terminate(s2["run_id"])  # 收尾: 取消 reset 新建的驻留任务, 不留悬挂 task

    print(f"\n共 {tally['n']} 用例, 失败 {len(failures)}")
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
