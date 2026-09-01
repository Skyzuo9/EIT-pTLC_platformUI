"""PLC 程序编辑服务/路由离线测试
=================================
功能:
    不启动 InoProShop, 用假 IPC 客户端(记录 op/args/timeout, 按 op 返回或抛错)验证:
      - PlcProgramService 各方法是否把调用正确映射为 worker op + 参数 + 超时
      - /api/plc/* 路由: 服务未就绪(sim 默认)→503; 注入服务后正常返回;
        缺 path→400/422; IPC RuntimeError→502; TimeoutError→504
    全程离线, 不连真机, 不弹 IDE。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_plc_program_offline
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from eit_ptlc.controller.plc_program_service import PlcProgramService
from eit_ptlc.driver.codesys_ipc import CodesysIpcClient
from eit_ptlc.runtime.bootstrap import create_sim_app


class FakeIpc:
    """假 CodesysIpcClient: 记录每次调用, 按 op 返回预置结果或抛预置异常。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.responses: dict = {}
        self.control = {"manual_control": False, "owner": "shared"}

    async def call(self, op, args=None, timeout=60.0):
        self.calls.append((op, args, timeout))
        r = self.responses.get(op)
        if isinstance(r, Exception):
            raise r
        return r

    def session_snapshot(self):
        return {
            "manual_control": bool(self.control.get("manual_control")),
            "control": self.control,
            "worker_alive": False,
            "keeper_alive": False,
            "lease_active": False,
        }

    def takeover(self, *, by="operator", reason=""):
        self.control = {
            "manual_control": True,
            "owner": by,
            "reason": reason,
        }
        return self.session_snapshot()

    def release_takeover(self, *, by="operator"):
        self.control = {
            "manual_control": False,
            "owner": "shared",
            "updated_by": by,
        }
        return self.session_snapshot()


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

    # ---- 1) 服务层: 方法 → op/args/timeout 映射 ----
    async def svc_checks():
        fake = FakeIpc()
        fake.responses = {
            "status": {"state": "ready"},
            "list": {"pous": [{"path": "Application/Foo"}], "count": 1},
            "tree": {"nodes": [{"path": "Device", "name": "Device", "depth": 0, "has_children": True}], "count": 1},
            "read": {"path": "Application/Foo", "declaration": "VAR", "implementation": "x:=1;"},
            "write": {"path": "Application/Foo", "updated": ["implementation"], "saved": False},
            "compile": {"error_count": 0, "warning_count": 0, "errors": [], "warnings": []},
        }
        svc = PlcProgramService(fake)
        await svc.status()
        await svc.list_pous()
        await svc.tree()
        await svc.read_pou("Application/Foo")
        await svc.save_pou("Application/Foo", "decl", None, False)
        await svc.compile()
        before = svc.session()
        taken = svc.takeover("tester", "manual edit")
        released = svc.release_takeover("tester")
        return fake.calls, before, taken, released

    calls, sess_before, sess_taken, sess_released = asyncio.run(svc_checks())
    by_op = {c[0]: c for c in calls}
    check("svc_status_op", by_op.get("status") == ("status", {}, 160.0), str(by_op.get("status")))
    check("svc_list_op", by_op.get("list") == ("list", {"textual_only": True}, 120.0), str(by_op.get("list")))
    check("svc_tree_op", by_op.get("tree") == ("tree", {}, 120.0), str(by_op.get("tree")))
    check("svc_read_op", by_op.get("read") == ("read", {"path": "Application/Foo"}, 60.0), str(by_op.get("read")))
    check("svc_write_op",
          by_op.get("write") == ("write", {"path": "Application/Foo", "declaration": "decl",
                                            "implementation": None, "save": False}, 60.0),
          str(by_op.get("write")))
    check("svc_compile_op", by_op.get("compile") == ("compile", {}, 240.0), str(by_op.get("compile")))
    check("svc_session_idle", sess_before["manual_control"] is False and sess_before["allow_deploy"] is False,
          str(sess_before))
    check("svc_session_takeover", sess_taken["manual_control"] is True and sess_taken["control"]["owner"] == "tester",
          str(sess_taken))
    check("svc_session_release", sess_released["manual_control"] is False and sess_released["control"]["owner"] == "shared",
          str(sess_released))

    # ---- 1c) 真 IPC 客户端: manual_control 在 worker 启动前阻断非 status op ----
    async def ipc_manual_control_check(tmp):
        ipc = CodesysIpcClient(
            exe=str(Path(tmp) / "missing_InoProShop.exe"),
            profile="missing",
            project=Path(tmp) / "missing.project",
            ipc_dir=Path(tmp) / "ipc",
            compile_category="missing",
            ready_timeout=0.1,
        )
        taken = ipc.takeover(by="tester", reason="manual edit")
        blocked = ""
        try:
            await ipc.call("list", {"textual_only": True}, 0.1)
        except RuntimeError as exc:
            blocked = str(exc)
        released = ipc.release_takeover(by="tester")
        return taken, blocked, released, (Path(tmp) / "ipc" / "worker_active.py").exists()

    with tempfile.TemporaryDirectory() as tmp:
        ipc_taken, ipc_blocked, ipc_released, worker_script_exists = asyncio.run(ipc_manual_control_check(tmp))
    check("ipc_manual_takeover_snapshot", ipc_taken["manual_control"] is True, str(ipc_taken))
    check("ipc_manual_blocks_before_spawn",
          "manual control" in ipc_blocked and "list" in ipc_blocked and not worker_script_exists,
          f"blocked={ipc_blocked!r}, worker_script_exists={worker_script_exists}")
    check("ipc_manual_release_snapshot", ipc_released["manual_control"] is False, str(ipc_released))

    # ---- 1b) 符号导出: list_symbols 解析声明 + set_symbol_export 读→改 pragma→写 ----
    async def symbol_checks():
        fake = FakeIpc()
        fake.responses = {
            "read": {"declaration": "VAR_GLOBAL\n\tFoo: BOOL;\n\tBar: LREAL;\nEND_VAR\n"},
            "write": {"saved": True, "updated": ["declaration"]},
        }
        svc = PlcProgramService(fake)
        listed = await svc.list_symbols("Application/G")
        enabled = await svc.set_symbol_export("Application/G", "Foo", True)   # 本未导出 → 改动+写
        noop = await svc.set_symbol_export("Application/G", "Bar", False)     # 本未导出再 disable → 无变化
        return listed, enabled, noop, fake.calls

    listed, enabled, noop, sym_calls = asyncio.run(symbol_checks())
    check("svc_list_symbols", [s["name"] for s in listed["symbols"]] == ["Foo", "Bar"], str(listed))
    check("svc_set_symbol_changed",
          enabled == {"path": "Application/G", "name": "Foo", "exported": True, "changed": True}, str(enabled))
    write_calls = [c for c in sym_calls if c[0] == "write"]
    check("svc_set_symbol_wrote_pragma",
          len(write_calls) == 1 and "{attribute 'symbol'" in write_calls[0][1]["declaration"]
          and write_calls[0][1]["save"] is True, str(write_calls))
    check("svc_set_symbol_noop_no_write", noop["changed"] is False and len(write_calls) == 1, str(sym_calls))

    # ---- 2) 路由层: 经 TestClient(sim) 验证 503 门控 + 注入后行为 + 错误码映射 ----
    app = create_sim_app(opcua_url="opc.tcp://127.0.0.1:48497/eit_ptlc/sim/")
    with TestClient(app) as client:
        # 2a) sim 默认未装配 plc_program → 503
        check("route_503_when_unset", client.get("/api/plc/pous").status_code == 503,
              str(client.get("/api/plc/pous").status_code))

        # 2b) 注入假服务后正常返回 + 记录正确 op
        fake = FakeIpc()
        fake.responses = {
            "list": {"pous": [{"path": "Application/Foo"}], "count": 1},
            "tree": {"nodes": [
                {"path": "Device", "name": "Device", "depth": 0, "has_impl": False, "has_decl": False, "has_children": True},
                {"path": "Device/PLC 逻辑/Application/Foo", "name": "Foo", "depth": 2,
                 "has_impl": True, "has_decl": True, "has_children": False},
            ], "count": 2},
            "read": {"path": "Application/Foo", "declaration": "VAR", "implementation": "x:=1;"},
            "write": {"path": "Application/Foo", "updated": ["implementation"], "saved": True},
            "compile": {"error_count": 1, "warning_count": 0,
                        "errors": [{"severity": "error", "text": "未定义变量 X"}], "warnings": []},
            "status": {"state": "ready"},
        }
        app.state.plc_program = PlcProgramService(fake)

        r = client.get("/api/plc/session")
        check("route_session_200", r.status_code == 200 and r.json()["manual_control"] is False, r.text)
        r = client.post("/api/plc/session/takeover", json={"by": "tester", "reason": "manual"})
        check("route_session_takeover_200",
              r.status_code == 200 and r.json()["manual_control"] is True and r.json()["control"]["owner"] == "tester",
              r.text)
        r = client.post("/api/plc/session/release", json={"by": "tester"})
        check("route_session_release_200", r.status_code == 200 and r.json()["manual_control"] is False, r.text)

        r = client.get("/api/plc/pous")
        check("route_list_200", r.status_code == 200 and r.json()["count"] == 1, r.text)

        r = client.get("/api/plc/tree")
        check("route_tree_200", r.status_code == 200 and r.json()["count"] == 2
              and r.json()["nodes"][0]["name"] == "Device", r.text)
        check("route_tree_recorded", ("tree", {}, 120.0) in fake.calls, str(fake.calls))

        r = client.get("/api/plc/pou", params={"path": "Application/Foo"})
        check("route_read_200", r.status_code == 200 and r.json()["implementation"] == "x:=1;", r.text)
        check("route_read_recorded", ("read", {"path": "Application/Foo"}, 60.0) in fake.calls, str(fake.calls))

        # 缺 path 查询参数 → 422 (FastAPI 必填查询参数校验)
        check("route_read_missing_path_422", client.get("/api/plc/pou").status_code == 422,
              str(client.get("/api/plc/pou").status_code))

        # PUT 缺 path 字段 → 400
        check("route_save_missing_path_400", client.put("/api/plc/pou", json={}).status_code == 400,
              str(client.put("/api/plc/pou", json={}).status_code))

        r = client.put("/api/plc/pou", json={"path": "Application/Foo", "implementation": "y:=2;", "save": True})
        check("route_save_200", r.status_code == 200 and r.json()["saved"] is True, r.text)
        check("route_save_recorded",
              ("write", {"path": "Application/Foo", "declaration": None,
                         "implementation": "y:=2;", "save": True}, 60.0) in fake.calls,
              str(fake.calls))

        r = client.post("/api/plc/compile")
        check("route_compile_200", r.status_code == 200 and r.json()["error_count"] == 1, r.text)

        # ---- symbols 路由: 列出 + 切换 pragma + 入参/未知变量校验 ----
        fake.responses["read"] = {"declaration": "VAR_GLOBAL\n\tFoo: BOOL;\nEND_VAR\n"}
        fake.responses["write"] = {"saved": True, "updated": ["declaration"]}
        r = client.get("/api/plc/symbols", params={"path": "Application/G"})
        check("route_symbols_list_200",
              r.status_code == 200 and [s["name"] for s in r.json()["symbols"]] == ["Foo"], r.text)
        r = client.post("/api/plc/symbols", json={"path": "Application/G", "name": "Foo", "enabled": True})
        check("route_symbols_set_200", r.status_code == 200 and r.json()["changed"] is True, r.text)
        check("route_symbols_missing_name_400",
              client.post("/api/plc/symbols", json={"path": "Application/G"}).status_code == 400)
        r = client.post("/api/plc/symbols", json={"path": "Application/G", "name": "NoSuch", "enabled": True})
        check("route_symbols_unknown_var_400", r.status_code == 400, r.text)  # ValueError → 400

        # 2c) 错误码映射: RuntimeError→502, TimeoutError→504
        fake.responses["compile"] = RuntimeError("InoProShop build 失败")
        check("route_runtime_502", client.post("/api/plc/compile").status_code == 502,
              str(client.post("/api/plc/compile").status_code))
        fake.responses["status"] = TimeoutError("worker 无响应")
        check("route_timeout_504", client.get("/api/plc/status").status_code == 504,
              str(client.get("/api/plc/status").status_code))

        # ---- 3) 工位 L2 复位 (sim: 真 PlcController; 工位名从「设备」页节点派生, 去 plc. 前缀) ----
        nodes = client.get("/api/nodes").json()
        plc_node = next((n for n in nodes if n.get("kind") == "plc_station"), None)
        check("plc_station_node_present", plc_node is not None, str([n.get("id") for n in nodes]))
        if plc_node is not None:
            st = plc_node["id"].replace("plc.", "", 1)
            r_reset = client.post(f"/api/plc/stations/{st}/reset")
            check("station_reset_debug_200", r_reset.status_code == 200 and r_reset.json().get("reset") is True, r_reset.text)
            client.post("/api/mode", json={"control_mode": "RUN"})
            check("station_reset_run_403", client.post(f"/api/plc/stations/{st}/reset").status_code == 403)
            client.post("/api/mode", json={"control_mode": "DEBUG"})

    print(f"\nPLC 程序编辑服务/路由离线测试: 失败 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
