"""API 层端到端离线测试 (HTTP)
==============================
功能:
    用 FastAPI TestClient 跑通 sim 应用 (内存机器人 + Mock PLC): 健康/目录/机器人 jog-step-move/
    PLC L2/模式门控/404 全部经 HTTP 验证. 这是"运维页能点动+触发 PLC L2"的后端闭环证明.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_api_offline
"""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from eit_ptlc.runtime.bootstrap import create_sim_app


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    app = create_sim_app(opcua_url="opc.tcp://127.0.0.1:48491/eit_ptlc/sim/")
    with TestClient(app) as client:  # 进入即触发 lifespan: 启动 Mock PLC + 仿真机器人
        h = client.get("/api/health").json()
        check("health", h["status"] == "ok" and h["executor_ready"], str(h))

        acts = client.get("/api/actions").json()
        check("list_actions", len(acts) >= 8, f"len={len(acts)}")
        robot_acts = client.get("/api/actions?kind=robot").json()
        check("filter_kind", all(a["kind"] == "robot" for a in robot_acts) and len(robot_acts) >= 5, str(len(robot_acts)))

        # 机器人点动 (便捷端点)
        r = client.post("/api/robot/jog/start", json={"axis_id": "X+"}).json()
        check("jog_start", r["status"] == "DONE", str(r))
        r = client.post("/api/robot/jog/stop", json={}).json()
        check("jog_stop", r["status"] == "DONE", str(r))

        # 机器人步进 (便捷端点)
        r = client.post("/api/robot/step", json={"axis": "Z", "distance": -2.0}).json()
        check("step", r["status"] == "DONE", str(r))

        # 机器人使能 / 下使能 / 清警 (便捷端点, DEBUG)
        r = client.post("/api/robot/enable", json={}).json()
        check("enable", r["status"] == "DONE", str(r))
        r = client.post("/api/robot/disable", json={}).json()
        check("disable", r["status"] == "DONE", str(r))
        r = client.post("/api/robot/clear_error", json={}).json()
        check("clear_error", r["status"] == "DONE", str(r))

        # 机器人断联重连 (便捷端点, 不限模式)
        r = client.post("/api/robot/connect", json={}).json()
        check("connect", r["status"] == "DONE", str(r))

        # 全局速度比: 设置 -> 经遥测回显 -> 越界拒绝
        r = client.post("/api/robot/speed_factor", json={"ratio": 35}).json()
        check("speed_factor_set", r["status"] == "DONE", str(r))
        snap = client.get("/api/nodes/robot").json()
        check("speed_factor_telemetry", snap["data"].get("speed_factor") == 35, str(snap.get("data")))
        r = client.post("/api/robot/speed_factor", json={"ratio": 150}).json()
        check("speed_factor_range", r["status"] == "REJECTED", str(r))

        # 机器人到点 (通用 run 端点)
        r = client.post("/api/actions/robot.move_to_point/run",
                        json={"params": {"point_id_or_robot_name": "robot-main.home", "motion": "move_j"}}).json()
        check("move_to_point", r["status"] == "DONE" and "joint" in r["result"], str(r["status"]))

        # PLC L2 (通用 run 端点, 需 RUN)
        r = client.post("/api/actions/sampling.init/run", json={"params": {}, "mode": "RUN"}).json()
        check("plc_l2_init", r["status"] == "DONE", str(r))

        # 孔板标定/下发 (DEBUG; 只读 + 校验路径, 不落盘以免改仓库 calibration.yaml)
        insts = client.get("/api/calibration/instances").json()
        check("calib_instances",
              len(insts) == 4 and any(i["id"] == "plate_6x8_1" and not i["is_calibrated"] for i in insts),
              str(insts))
        ptypes = client.get("/api/calibration/plate_types").json()
        check("calib_plate_types", any(p["name"] == "4×6" for p in ptypes), str(ptypes))
        det = client.get("/api/calibration/plate_6x8_1").json()
        check("calib_detail", det["plate"]["rows"] == 6 and len(det["plate"]["calib_wells"]) == 3, str(det.get("plate")))
        ap = client.get("/api/calibration/actpos").json()
        check("calib_actpos", "x_mm" in ap and "y_mm" in ap, str(ap))
        cap = client.post("/api/calibration/plate_6x8_1/capture", json={"row": 1, "col": 1}).json()
        check("calib_capture", cap["well"] == [1, 1], str(cap))
        sc = client.post("/api/calibration/plate_6x8_1/push", json={"row": 2, "col": 2}).status_code
        check("calib_push_uncalibrated_400", sc == 400, f"status={sc}")
        sc = client.post("/api/calibration/plate_6x8_1/commit", json={"points": [
            {"well": [1, 1], "x_mm": 0, "y_mm": 0}, {"well": [1, 3], "x_mm": 10, "y_mm": 0},
            {"well": [1, 5], "x_mm": 20, "y_mm": 0}]}).status_code  # 共线退化 → 400, solve 前抛不落盘
        check("calib_commit_collinear_400", sc == 400, f"status={sc}")

        # 模式门控: 切 RUN 后点动被拒
        client.post("/api/mode", json={"control_mode": "RUN"})
        r = client.post("/api/robot/jog/start", json={"axis_id": "X+"}).json()
        check("mode_gate", r["status"] == "REJECTED" and r["reject_code"] == "MODE_NOT_ALLOWED", str(r))

        # 标定下发模式门控: RUN 下 push 被拒 (409)
        sc = client.post("/api/calibration/plate_6x8_1/push", json={"row": 1, "col": 1}).status_code
        check("calib_push_mode_gate_409", sc == 409, f"status={sc}")

        # 未知动作 404
        check("unknown_404", client.get("/api/actions/nope").status_code == 404)

    print(f"\n共 25 用例, 失败 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
