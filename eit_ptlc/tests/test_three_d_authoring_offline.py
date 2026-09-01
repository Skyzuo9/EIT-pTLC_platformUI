"""三维工程资产与 authoring 服务离线测试."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.app import create_app
from eit_ptlc.runtime.three_d_authoring import (
    _flow_argv,
    ThreeDAuthoringService,
    ThreeDRebuildBusy,
    ThreeDWorkspaceUnavailable,
)


def _workspace(root: Path) -> Path:
    """
    功能:
        创建不包含真实工程数据的最小三维测试工作区.

    参数:
        root: pytest 临时目录.

    返回:
        已创建的三维工程根目录.
    """
    workspace = root / "three-d"
    for relative in ("pipeline", "work", "models", "clips", "generated", "docs"):
        (workspace / relative).mkdir(parents=True, exist_ok=True)
    (workspace / "pipeline/materials.yaml").write_text("version: 1\n", encoding="utf-8")
    (workspace / "models/device-manifest.json").write_text("{}", encoding="utf-8")
    (workspace / "clips/beta.yaml").write_text("tracks: []\n", encoding="utf-8")
    (workspace / "clips/alpha.yaml").write_text("tracks: []\n", encoding="utf-8")
    return workspace


def test_managed_files_assets_and_path_guards(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    service = ThreeDAuthoringService(workspace)

    assert service.read_file(key="materials")["content"] == "version: 1\n"
    result = service.write_file("version: 2\n", key="materials")
    assert result["backup"] == "pipeline/materials.yaml.bak"
    assert (workspace / "pipeline/materials.yaml.bak").read_text(encoding="utf-8") == "version: 1\n"
    assert service.list_clips() == ["alpha", "beta"]
    assert service.resolve_asset("models/device-manifest.json").is_file() is True

    # 装配台标红基线: 只读放行, 但绝不能进可写名单 —— 它是管线产物, 人写进去就等于
    # 让"预览"与"真实删减"再次各说各话, 而那正是这套基线要收口的问题.
    (workspace / "work/prune_preview.json").write_text('{"version": 1}', encoding="utf-8")
    assert service.read_file(key="prune_preview")["content"] == '{"version": 1}'
    with pytest.raises(ValueError, match="未知的写入目标"):
        service.write_file("{}", key="prune_preview")

    with pytest.raises(ValueError, match="路径越界"):
        service.resolve_asset("../pipeline/materials.yaml")
    with pytest.raises(ValueError, match="未知的读取目标"):
        service.read_file(key="outside")
    with pytest.raises(ValueError, match="片段名不合法"):
        service.write_file("tracks: []\n", clip="../outside")
    with pytest.raises(FileNotFoundError):
        service.resolve_asset("models/missing.glb")


def test_missing_workspace_reports_unavailable(tmp_path: Path) -> None:
    service = ThreeDAuthoringService(tmp_path / "missing")

    assert service.workspace_status()["available"] is False
    with pytest.raises(ThreeDWorkspaceUnavailable):
        service.read_file(key="materials")
    with pytest.raises(ThreeDWorkspaceUnavailable):
        service.resolve_asset("models/machine.glb")


def test_hardware_source_marker_and_status(tmp_path: Path) -> None:
    """
    功能:
        验证仓库标记指向唯一硬件源目录, 服务状态也回显外部目录可用性.

    参数:
        tmp_path: pytest 临时目录.

    返回:
        无.
    """
    repository_root = Path(__file__).resolve().parents[2]
    marker_path = repository_root / "eit_ptlc" / "three_d" / "SOURCE_ASSETS.yaml"
    marker = yaml.safe_load(marker_path.read_text(encoding="utf-8"))
    assert marker["hardware_root"] == "E:/eit_lab/eit_lab_hardware/eit_ptlc_station"
    assert marker["repository_policy"] == "excluded"

    workspace = _workspace(tmp_path)
    hardware_root = tmp_path / "hardware"
    hardware_root.mkdir()
    service = ThreeDAuthoringService(workspace, hardware_root=hardware_root)
    status = service.workspace_status()
    assert status["hardware_root"] == str(hardware_root.resolve())
    assert status["hardware_available"] is True


def test_rebuild_is_single_task_and_reports_steps(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = _workspace(tmp_path)
        started = asyncio.Event()
        release = asyncio.Event()

        async def runner(argv: tuple[str, ...], cwd: Path) -> dict:
            assert cwd == workspace / "pipeline"
            assert len(argv) > 0
            started.set()
            await release.wait()
            return {"ok": True, "code": 0, "stdout": "完成\n", "stderr": ""}

        service = ThreeDAuthoringService(workspace, runner=runner)
        accepted = await service.start_rebuild(["manifest"])
        assert accepted["running"] is True
        assert accepted["steps"][0]["status"] == "pending"
        await started.wait()
        with pytest.raises(ThreeDRebuildBusy):
            await service.start_rebuild(["report"])
        release.set()
        await service._task
        completed = service.status()
        assert completed["running"] is False
        assert completed["steps"][0]["status"] == "done"
        assert completed["error"] == ""

    asyncio.run(scenario())


def test_rebuild_stops_after_failed_step(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = _workspace(tmp_path)

        async def runner(argv: tuple[str, ...], cwd: Path) -> dict:
            return {"ok": False, "code": 9, "stdout": "", "stderr": "管线失败"}

        service = ThreeDAuthoringService(workspace, runner=runner)
        await service.start_rebuild(["manifest", "report"])
        await service._task
        status = service.status()
        assert [step["status"] for step in status["steps"]] == ["failed", "pending"]
        assert "失败" in status["error"]
        assert "管线失败" in status["steps"][0]["tail"]

    asyncio.run(scenario())


def test_authoring_routes_and_debug_gate(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    service = ThreeDAuthoringService(workspace)
    debug_app = create_app(
        ActionRegistry({}),
        control_mode="DEBUG",
        three_d_authoring=service,
    )

    with TestClient(debug_app) as client:
        status = client.get("/api/3d/authoring/status")
        assert status.status_code == 200
        assert status.json()["authoring_allowed"] is True
        assert client.get("/api/3d/assets/models/device-manifest.json").status_code == 200
        assert client.get("/api/3d/assets/models/missing.glb").status_code == 404
        assert client.post("/api/3d/authoring/read", json={"key": "materials"}).status_code == 200
        assert client.post("/api/3d/authoring/read", json={"key": "outside"}).status_code == 400
        written = client.post(
            "/api/3d/authoring/write",
            json={"clip": "route-test", "content": "tracks: []\n"},
        )
        assert written.status_code == 200
        assert (workspace / "clips/route-test.yaml").is_file() is True

    run_app = create_app(
        ActionRegistry({}),
        control_mode="RUN",
        three_d_authoring=service,
    )
    with TestClient(run_app) as client:
        assert client.get("/api/3d/assets/models/device-manifest.json").status_code == 200
        assert client.post("/api/3d/authoring/read", json={"key": "materials"}).status_code == 200
        assert client.post(
            "/api/3d/authoring/write",
            json={"key": "materials", "content": "version: 3\n"},
        ).status_code == 403
        assert client.post("/api/3d/authoring/rebuild", json={"only": ["manifest"]}).status_code == 403


def test_unavailable_authoring_route_returns_503(tmp_path: Path) -> None:
    app = create_app(
        ActionRegistry({}),
        control_mode="DEBUG",
        three_d_authoring=ThreeDAuthoringService(tmp_path / "missing"),
    )

    with TestClient(app) as client:
        assert client.get("/api/3d/assets/models/machine.glb").status_code == 503
        assert client.post("/api/3d/authoring/read", json={"key": "materials"}).status_code == 503
        assert client.post("/api/3d/authoring/rebuild", json={"only": ["manifest"]}).status_code == 503


def test_flow_rebuild_argv_drops_plates_and_carries_inputs(tmp_path: Path) -> None:
    """定向编一条流程: argv 必须带 --only/--inputs 且**不含 --plates**.

    --plates 会把 43 条 plate.* 一起重编 —— 全量时那是必须的(那 12 条硬编码路线的
    home.axis_mm 靠它更新), 但定向编一条 flow 时它和被点名的流程毫无关系, 白花十几分钟。
    "改个参数看一眼"这件事到底做不做得成, 就取决于这一个开关。
    """
    async def scenario() -> None:
        workspace = _workspace(tmp_path)
        seen: list[tuple[str, ...]] = []

        async def runner(argv: tuple[str, ...], cwd: Path) -> dict:
            seen.append(argv)
            return {"ok": True, "code": 0, "stdout": "", "stderr": ""}

        service = ThreeDAuthoringService(workspace, runner=runner)
        await service.start_rebuild(
            ["flows"],
            flow={"operation": "collect_execute",
                  "inputs": {"solvent_volume_ml": 5, "liquid_repeat_count": 3}},
        )
        await service._task

        assert len(seen) == 1
        argv = seen[0]
        assert "--flows" in argv
        assert "--plates" not in argv, "定向编一条流程时不该重编 43 个 plate.* 片段"
        assert "--only" in argv and argv[argv.index("--only") + 1] == "flow.collect_execute*"
        payload = argv[argv.index("--inputs") + 1]
        assert json.loads(payload) == {
            "collect_execute": {"solvent_volume_ml": 5, "liquid_repeat_count": 3}}
        # 全量路径一个字都不能变
        assert "--plates" in _flow_argv("py", None)

    asyncio.run(scenario())


def test_flow_rebuild_rejects_bad_requests(tmp_path: Path) -> None:
    """流程名/入参名/取值/长度 一律在 argv 边界前拦下, 不放进子进程再让它一路走到 SystemExit.

    那种失败会夹在几百行编译日志里, 前端只看得到"flows 步失败", 等于没有报错。
    """
    async def scenario() -> None:
        workspace = _workspace(tmp_path)

        async def runner(argv: tuple[str, ...], cwd: Path) -> dict:
            return {"ok": True, "code": 0, "stdout": "", "stderr": ""}

        service = ThreeDAuthoringService(workspace, runner=runner)
        good = {"operation": "collect_execute", "inputs": {"solvent_volume_ml": 5}}

        # flow 只有 flows 步认得; 混着别的步跑等于允许一个静默无效的请求
        with pytest.raises(ValueError):
            await service.start_rebuild(["manifest"], flow=good)
        with pytest.raises(ValueError):
            await service.start_rebuild(["flows", "report"], flow=good)
        with pytest.raises(ValueError):
            await service.start_rebuild([], flow=good)

        for bad in (
            {"operation": "collect execute", "inputs": {"a": 1}},     # 名字带空格
            {"operation": "../etc", "inputs": {"a": 1}},              # 路径穿越形
            {"operation": "collect_execute", "inputs": {}},           # 空 inputs
            {"operation": "collect_execute", "inputs": {"1bad": 1}},  # 入参名非标识符
            {"operation": "collect_execute", "inputs": {"a": [1, 2]}},  # 取值类型不受支持
            {"operation": "collect_execute", "inputs": {"a": "x" * 4096}},  # 超长
        ):
            with pytest.raises(ValueError):
                await service.start_rebuild(["flows"], flow=bad)

    asyncio.run(scenario())


def test_flow_rebuild_route_passes_flow_through(tmp_path: Path) -> None:
    """路由把 flow 透传下去, 非法 flow 走 400 而不是 500."""
    workspace = _workspace(tmp_path)
    seen: list[tuple[str, ...]] = []

    async def runner(argv: tuple[str, ...], cwd: Path) -> dict:
        seen.append(argv)
        return {"ok": True, "code": 0, "stdout": "", "stderr": ""}

    app = create_app(
        ActionRegistry({}),
        control_mode="DEBUG",
        three_d_authoring=ThreeDAuthoringService(workspace, runner=runner),
    )
    with TestClient(app) as client:
        assert client.post("/api/3d/authoring/rebuild", json={
            "only": ["flows"],
            "flow": {"operation": "collect_execute", "inputs": {"solvent_volume_ml": 5}},
        }).status_code == 202
        # flow 不是映射 -> 400
        assert client.post("/api/3d/authoring/rebuild", json={
            "only": ["flows"], "flow": "collect_execute",
        }).status_code == 400
        # 流程名非法 -> 400(而不是 500)
        assert client.post("/api/3d/authoring/rebuild", json={
            "only": ["flows"], "flow": {"operation": "a b", "inputs": {"x": 1}},
        }).status_code == 400
