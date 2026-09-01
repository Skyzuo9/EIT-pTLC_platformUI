"""VM 编排 API 端到端离线测试 (HTTP)
====================================
功能:
    经 TestClient (sim: Mock PLC 全工位 L2) 验证脚本仓库 CRUD + 校验拒绝 + 运行/单步/变量 +
    HITL 回复 + 运行历史回放. 证明新「库」IDE 的后端闭环.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_vm_api_offline
"""

from __future__ import annotations

import sys
import time

from fastapi.testclient import TestClient

from eit_ptlc.runtime.bootstrap import create_sim_app


def _poll_status(client, run_id, want, tries=600):
    for _ in range(tries):
        st = client.get(f"/api/debug/{run_id}/state").json()
        if st["status"] == want or st["status"] in ("DONE", "ERROR", "KILLED"):
            return st
        time.sleep(0.02)
    return client.get(f"/api/debug/{run_id}/state").json()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []

    def check(name, cond, detail=""):
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    app = create_sim_app(opcua_url="opc.tcp://127.0.0.1:48494/eit_ptlc/sim/")
    with TestClient(app) as client:
        # 清理可能的历史残留 (FS 仓库持久化)
        for n in ("t_demo", "t_human"):
            client.delete(f"/api/scripts/{n}")

        # 仓库列举
        check("workspaces", client.get("/api/scripts/workspaces").json() == ["default"])
        ops = {s["name"] for s in client.get("/api/scripts?kind=operation").json()}
        acts = {s["name"] for s in client.get("/api/scripts?kind=action").json()}
        # 仓库只存 operation (tank_prep 现为 operation 子流程); action 类已退役 (动作=config/actions 原子)
        check("seed_operations", {"ptlc_full", "sampling_full", "tank_prep"} <= ops, str(sorted(ops)))
        check("no_action_kind_scripts", acts == set(), str(sorted(acts)))

        # 读单脚本
        doc = client.get("/api/scripts/sampling_full").json()
        check("get_script", doc["kind"] == "operation" and len(doc["body"]) == 12, str(doc.get("body")))

        # 新建 -> 保存 (校验通过) -> 版本历史增长
        client.post("/api/scripts", json={"name": "t_demo", "kind": "operation", "label": "演示"})
        new_doc = {"schema": "ptlc.script/v1", "kind": "operation", "name": "t_demo", "label": "演示",
                   "vars": [], "body": [{"op": "call", "action": "sampling.init", "mode": "RUN"}]}
        r = client.put("/api/scripts/t_demo", json={"doc": new_doc})
        check("save_script", r.status_code == 200, r.text)
        check("versions_grow", len(client.get("/api/scripts/t_demo/versions").json()) >= 2,
              str(client.get("/api/scripts/t_demo/versions").json()))

        # 保存非法脚本 (未知动作) -> 400
        bad = dict(new_doc)
        bad["body"] = [{"op": "call", "action": "不存在的动作", "mode": "RUN"}]
        check("save_invalid_400", client.put("/api/scripts/t_demo", json={"doc": bad}).status_code == 400)

        # 单步运行 sampling_full: 停在 b/0 -> step 执行首叶子 init -> 跳过注释 b/1 -> 停在 b/2 (pump.vacuum_on)
        r = client.post("/api/scripts/sampling_full/debug/run",
                        json={"inputs": {}, "mode": "RUN", "mode_run": "step"}).json()
        rid = r["run_id"]
        check("debug_start_step", r["status"] == "STOPPED" and r["current_aid"] == "b/0", str(r))
        s1 = client.post(f"/api/debug/{rid}/step").json()
        check("debug_step", s1["current_aid"] == "b/2", str(s1))
        check("debug_vars", "vars" in client.get(f"/api/debug/{rid}/vars").json())

        # 继续跑完 -> 回放事件含 operation_start / vm_node_done / operation_done
        client.post(f"/api/debug/{rid}/run")
        st = _poll_status(client, rid, "DONE")
        check("debug_run_done", st["status"] == "DONE", str(st))
        ev_types = [e["type"] for e in client.get(f"/api/runs/{rid}").json().get("events", [])]
        check("replay_events", "operation_start" in ev_types and "vm_node_done" in ev_types
              and "operation_done" in ev_types, str(set(ev_types)))

        # HITL: 人工输入挂起 -> 回复绑定变量 -> 完成
        human_doc = {"schema": "ptlc.script/v1", "kind": "operation", "name": "t_human", "label": "人工",
                     "vars": [{"name": "note", "scope": "local", "type": "STRING", "io": "var", "default": ""}],
                     "body": [{"op": "human", "kind": "input", "prompt": {"lit": "请输入备注"},
                               "fields": [{"var": "note"}]}]}
        client.post("/api/scripts", json={"name": "t_human", "kind": "operation"})
        client.put("/api/scripts/t_human", json={"doc": human_doc})
        r = client.post("/api/scripts/t_human/debug/run",
                        json={"inputs": {}, "mode": "RUN", "mode_run": "run"}).json()
        hid = r["run_id"]
        st = _poll_status(client, hid, "WAITING_HUMAN")
        check("hitl_waiting", st["status"] == "WAITING_HUMAN", str(st))
        act = client.get("/api/debug/active").json()["runs"]
        mine = next((r for r in act if r["run_id"] == hid), None)
        check("active_has_pending_human",
              mine is not None and mine["operation"] == "t_human"
              and mine["pending_human"]["kind"] == "input" and mine["pending_human"]["req_id"],
              str(act))
        check("state_has_pending_human",
              client.get(f"/api/debug/{hid}/state").json().get("pending_human", {}).get("prompt") == "请输入备注",
              str(client.get(f"/api/debug/{hid}/state").json()))
        req = next(e["req_id"] for e in client.get(f"/api/runs/{hid}").json()["events"]
                   if e["type"] == "vm_human_request")
        rep = client.post(f"/api/debug/{hid}/human/{req}", json={"values": {"note": "已就位"}}).json()
        check("hitl_reply", rep["accepted"] is True, str(rep))
        st = _poll_status(client, hid, "DONE")
        note = client.get(f"/api/debug/{hid}/vars").json()["vars"].get("note", {}).get("value")
        check("hitl_done_bound", st["status"] == "DONE" and note == "已就位", f"{st} note={note}")
        act = client.get("/api/debug/active").json()["runs"]
        check("active_clears_after_done", all(r["run_id"] != hid for r in act), str(act))

        # 运行前旋钮: 从编排入口递归收集深层 prepare 旋钮 + 覆盖经 API 注入到帧 + 越界/未知拒
        knn = {k["name"] for k in client.get("/api/scripts/sampling_cycle/debug/knobs").json()["knobs"]}
        check("knobs_collect_deep", {"flush_volume_ml", "asp_speed", "step_delay"} <= knn, str(sorted(knn)))

        r = client.post("/api/scripts/sampling_prepare/debug/run",
                        json={"inputs": {}, "mode": "RUN", "mode_run": "step",
                              "overrides": {"flush_volume_ml": 10}}).json()
        krid = r["run_id"]
        cc = client.get(f"/api/debug/{krid}/vars").json()["vars"].get("flush_volume_ml", {}).get("value")
        check("knob_override_injected", cc == 10, f"flush_volume_ml={cc} {r}")
        client.post(f"/api/debug/{krid}/terminate")

        over_max = client.post("/api/scripts/sampling_prepare/debug/run",
                               json={"overrides": {"flush_volume_ml": 99}})
        check("knob_over_max_400", over_max.status_code == 400, over_max.text)
        unknown = client.post("/api/scripts/sampling_prepare/debug/run",
                              json={"overrides": {"nope": 1}})
        check("knob_unknown_400", unknown.status_code == 400, unknown.text)

        # 入参取值域: 事故复现钉子 —— rack_id 只认 collector|bottle, 填 control 必须
        # 在点"启动"时就被拒, 而不是跑到脚本末尾 else 抛 ROBOT_FLOW_SELECTOR
        # (那时机器人已 home 完并换过刀)。
        bad_in = client.post("/api/scripts/robot_group_staging_put/debug/run",
                             json={"inputs": {"rack_id": "control"}})
        check("input_bad_enum_400", bad_in.status_code == 400, bad_in.text)
        check("input_bad_enum_names_options",
              "collector" in bad_in.text and "bottle" in bad_in.text, bad_in.text)
        # 反向用例: 没声明取值域的入参传任意值仍放行 —— 证明这道闸没有误伤自由入参
        free_in = client.post("/api/scripts/photoscrape_full/debug/run",
                              json={"inputs": {"sample_id": "随便什么都行"}})
        check("input_free_var_passthrough", free_in.status_code == 200, free_in.text)
        if free_in.status_code == 200:
            client.post(f"/api/debug/{free_in.json()['run_id']}/terminate")

        # 清理
        for n in ("t_demo", "t_human"):
            client.delete(f"/api/scripts/{n}")

    print(f"\n共 26 用例, 失败 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
