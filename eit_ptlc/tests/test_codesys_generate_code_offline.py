"""Offline contract tests for CODESYS ``generate_code`` symbol XML export."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eit_ptlc.api.plc_program_routes import register_plc_program_routes
from eit_ptlc.controller.plc_program_service import PlcProgramService
from eit_ptlc.driver.codesys_ipc import _EXCLUSIVE_OPS


_ROOT = Path(__file__).resolve().parent.parent
_WORKER_BODY = _ROOT / "tools" / "codesys-mcp" / "worker_body.py"
_MCP_SERVER = _ROOT / "tools" / "codesys-mcp" / "server.mjs"


class _ForbiddenOnline:
    def __getattr__(self, name):
        raise AssertionError(f"offline generate_code touched online API: {name}")


class _NamedObject:
    def __init__(self, name: str, *, parent=None, is_device: bool = False) -> None:
        self._name = name
        self.parent = parent
        self.is_device = is_device

    def get_name(self, *_args):
        return self._name


class _FakeApplication(_NamedObject):
    def __init__(self, xml_path: Path, parent) -> None:
        super().__init__("Application", parent=parent)
        self.xml_path = xml_path
        self.generate_calls = 0

    def generate_code(self) -> None:
        self.generate_calls += 1
        self.xml_path.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<Symbolconfiguration xmlns="http://www.3s-software.com/schemas/'
            'Symbolconfiguration.xsd"><Header/></Symbolconfiguration>\n',
            encoding="utf-8",
        )


class _FakeSystem:
    def __init__(self) -> None:
        self.clear_calls = 0
        self.messages = [
            SimpleNamespace(severity="warning", text="offline warning"),
            SimpleNamespace(severity="info", text="generated"),
        ]

    def clear_messages(self, _category) -> None:
        self.clear_calls += 1

    def get_message_objects(self, _category):
        return self.messages


def _load_worker_functions(tmp_path: Path):
    """Exec worker definitions without starting its polling main loop."""
    project_path = tmp_path / "demo.project"
    project_path.write_bytes(b"fake project")
    xml_path = tmp_path / "demo.Device.Application.xml"
    xml_path.write_text("<Symbolconfiguration>old</Symbolconfiguration>", encoding="utf-8")

    device = _NamedObject("Device", is_device=True)
    logic = _NamedObject("Plc Logic", parent=device)
    application = _FakeApplication(xml_path, logic)
    project = SimpleNamespace(active_application=application)
    fake_system = _FakeSystem()

    source = _WORKER_BODY.read_text(encoding="utf-8")
    definitions = source.rsplit("\nmain()\n", 1)[0]
    namespace = {
        "__name__": "codesys_worker_generate_code_test",
        "IPC_DIR": str(tmp_path / "ipc"),
        "PROJECT_PATH": str(project_path),
        "POLL_SEC": 0.01,
        "COMPILE_CATEGORY": "test",
        "PLC_IP": "",
        "IDLE_TIMEOUT_SEC": 0,
        "unicode": str,
        "system": fake_system,
        "online": _ForbiddenOnline(),
    }
    exec(compile(definitions, "worker_body_generate_code_test", "exec"), namespace)
    return namespace, project, application, fake_system, xml_path


def test_worker_generate_code_writes_symbol_xml_without_online_api(tmp_path: Path) -> None:
    ns, project, application, fake_system, xml_path = _load_worker_functions(tmp_path)

    result = ns["op_generate_code"](project, {})

    assert application.generate_calls == 1
    assert fake_system.clear_calls == 1
    assert result["generated"] is True
    assert Path(result["xml_path"]) == xml_path.resolve()
    assert result["xml_size"] == xml_path.stat().st_size
    assert result["xml_mtime"] == xml_path.stat().st_mtime
    assert result["xml_changed"] is True
    assert result["error_count"] == 0
    assert result["warning_count"] == 1
    assert result["info_count"] == 1
    assert ns["OPS"]["generate_code"] is ns["op_generate_code"]


class _FakeIpc:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, float]] = []

    async def call(self, op, args=None, timeout=60.0):
        self.calls.append((op, args or {}, timeout))
        return {
            "generated": True,
            "xml_path": r"E:\\project\\demo.Device.Application.xml",
            "xml_mtime": 123.5,
            "xml_size": 456,
            "xml_changed": True,
            "error_count": 0,
            "warning_count": 0,
            "info_count": 1,
            "errors": [],
            "warnings": [],
        }


def test_generate_code_service_and_rest_route_are_offline_entrypoints() -> None:
    fake = _FakeIpc()
    service = PlcProgramService(fake)

    direct = asyncio.run(service.generate_code())
    assert direct["generated"] is True
    assert fake.calls == [("generate_code", {}, 240.0)]

    app = FastAPI()
    app.state.plc_program = service
    register_plc_program_routes(app)
    with TestClient(app) as client:
        response = client.post("/api/plc/generate_code")

    assert response.status_code == 200
    assert response.json()["xml_size"] == 456
    assert fake.calls[-1] == ("generate_code", {}, 240.0)
    assert all(call[0] not in {"online_status", "deploy"} for call in fake.calls)


def test_generate_code_is_exclusive_in_python_and_node_clients() -> None:
    assert "generate_code" in _EXCLUSIVE_OPS

    server = _MCP_SERVER.read_text(encoding="utf-8")
    exclusive_line = next(line for line in server.splitlines() if "const EXCLUSIVE_OPS" in line)
    assert '"generate_code"' in exclusive_line
    assert 'server.tool("codesys_generate_code"' in server
    assert 'call("generate_code", {}, 240000)' in server
