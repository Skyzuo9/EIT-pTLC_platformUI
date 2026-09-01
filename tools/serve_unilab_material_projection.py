"""为本地 Workbench 提供只读 pTLC 物料与 3D 模型投影。

该入口只编译工作区声明、物理图和模型资产，不激活 ROS 设备、工作流或动作。
它用于没有 ROS 2 的开发机进行可视化验收，不能作为机器人执行后端。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from unilabos.app.scheduler.inventory.backend_api import (
    install_backend_resource_api,
)
from unilabos.app.scheduler.inventory.backend_contract import (
    BackendResourceService,
)
from unilabos.app.scheduler.inventory.resource_graph_bootstrap import (
    bootstrap_local_resource_graph,
)
from unilabos.app.scheduler.inventory.store import InventoryStore
from unilabos.package_manager.package_catalog.material_models import (
    compile_workspace_material_models,
)
from unilabos.package_manager.workspace_runtime.lifecycle import (
    prepare_stable_workspace_product_generation_in_worker,
)
from unilabos.registry.template_snapshot import RegistryTemplateSnapshot


class _RegistryProjection:
    """把不可变 PackageCatalog 快照适配为模板同步的只读接口。"""

    def __init__(self, snapshot: Any):
        self._devices = tuple(
            _template_definition(definition) for definition in snapshot.devices
        )
        self._resources = tuple(
            _template_definition(definition) for definition in snapshot.resources
        )

    def obtain_registry_device_info(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._devices]

    def obtain_registry_resource_info(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._resources]


class _ResourceTreeProjection:
    """把 Node-Link 物理图投影为库存启动器消费的确定性节点树。"""

    def __init__(self, graph: Mapping[str, Any], source_id: str):
        raw_nodes = graph.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValueError("pTLC 物理图必须包含非空 nodes")
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"unilabos:{source_id}:runtime")
        self._trees = [[_resource_node(node, namespace) for node in raw_nodes]]

    def dump(self) -> list[list[dict[str, Any]]]:
        return json.loads(json.dumps(self._trees, ensure_ascii=False))


def _template_definition(definition: Any) -> dict[str, Any]:
    raw = definition.to_dict()
    details = raw.get("details")
    entry = details.get("registry_entry") if isinstance(details, Mapping) else None
    if not isinstance(entry, Mapping):
        raise ValueError(f"资源模板缺少 registry_entry: {definition.fqid}")
    projected = json.loads(json.dumps(dict(entry), ensure_ascii=False))
    projected["id"] = definition.fqid
    projected["source_fqid"] = f"{definition.module}:{definition.symbol}"
    return projected


def _resource_node(node: Any, namespace: uuid.UUID) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise ValueError("pTLC 物理图节点必须是对象")
    node_id = str(node.get("id") or "").strip()
    if not node_id:
        raise ValueError("pTLC 物理图节点缺少 id")
    position = node.get("position")
    size = node.get("size")
    scale = node.get("scale")
    rotation = node.get("rotation")
    return {
        **json.loads(json.dumps(dict(node), ensure_ascii=False)),
        "uuid": str(uuid.uuid5(namespace, node_id)),
        "pose": {
            "position": dict(position) if isinstance(position, Mapping) else {},
            "size": dict(size) if isinstance(size, Mapping) else {},
            "scale": dict(scale) if isinstance(scale, Mapping) else {},
            "rotation": dict(rotation) if isinstance(rotation, Mapping) else {},
        },
    }


def _models_by_template(candidate: Any, model_catalog: Any) -> dict[str, Any]:
    del candidate
    return {
        template_fqid: dict(model)
        for template_fqid, model in model_catalog.models_by_template.items()
    }


def _install_read_only_runtime_routes(app: FastAPI) -> None:
    @app.get("/api/v1/health")
    @app.get("/api/v1/readiness")
    def readiness() -> dict[str, Any]:
        return {"code": 0, "data": {"status": "ready", "mode": "read-only"}}

    @app.get("/api/v1/workflows")
    def workflows(page: int = 1, page_size: int = 100) -> dict[str, Any]:
        return {
            "code": 0,
            "data": {"items": [], "total": 0, "page": page, "page_size": page_size},
        }

    async def event_stream():
        while True:
            yield ": ptlc-read-only-material-projection\n\n"
            await asyncio.sleep(5)

    for route in (
        "/api/v1/events",
        "/api/v1/monitor/events",
        "/api/v1/device-telemetry/events",
    ):
        app.add_api_route(route, lambda: StreamingResponse(event_stream(), media_type="text/event-stream"))

    @app.websocket("/api/v1/ws/device_status")
    async def device_status(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(
                    {
                        "type": "device_status",
                        "data": {
                            "device_status": {},
                            "device_status_timestamps": {},
                        },
                    }
                )
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return


def create_app(workspace: Path, graph_path: str, database: Path, origin: str) -> FastAPI:
    arguments = {
        "workspace": str(workspace),
        "graph": graph_path,
        "working_dir": str(database.parent / "candidate"),
        "config": "deployment/local_config.py",
        "app_bridges": ["fastapi"],
        "devices": None,
        "workflow_editable_package_root": None,
    }
    prepared = prepare_stable_workspace_product_generation_in_worker(arguments)
    if prepared is None:
        raise RuntimeError("未能编译 pTLC 工作区")
    candidate = prepared.candidate
    model_catalog = compile_workspace_material_models(
        candidate.startup_plan,
        candidate.catalog,
    )
    template_snapshot = RegistryTemplateSnapshot.from_registry(
        _RegistryProjection(candidate.registry_snapshot)
    )
    store = InventoryStore(str(database))
    bootstrap_local_resource_graph(
        store=store,
        resource_tree_set=_ResourceTreeProjection(
            candidate.graph_copy(),
            Path(graph_path).name,
        ),
        registry_snapshot=template_snapshot,
        source_id=graph_path,
        material_rendering_by_template=_models_by_template(candidate, model_catalog),
        material_shapes_by_template=candidate.material_shapes_by_template,
    )

    app = FastAPI(title="pTLC UniLab read-only material projection")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def reject_mutations(request, call_next):
        """Fail closed before inventory routes can persist a browser mutation."""

        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            return JSONResponse(
                status_code=405,
                content={
                    "code": 405,
                    "message": "只读物料投影不允许修改、移动或创建资源",
                },
            )
        return await call_next(request)

    install_backend_resource_api(
        app,
        BackendResourceService(store),
        material_shapes=candidate.material_shapes,
        material_model_catalog=model_catalog,
    )
    _install_read_only_runtime_routes(app)
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--graph",
        default="deployment/graphs/ptlc-platformui-local-debug.json",
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--port", type=int, default=18144)
    parser.add_argument("--allow-origin", default="http://127.0.0.1:3100")
    args = parser.parse_args()
    uvicorn.run(
        create_app(
            Path(args.workspace).resolve(),
            args.graph,
            Path(args.database).resolve(),
            args.allow_origin,
        ),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
