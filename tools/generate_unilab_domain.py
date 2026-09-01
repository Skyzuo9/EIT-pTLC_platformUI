#!/usr/bin/env python3
"""Generate the UniLab facade from PlatformUI's active declarations.

The generated Python is intentionally static: UniLab's AST registry can
inspect all devices, action signatures and models without importing the live
PlatformUI runtime.  Re-running this file is the drift repair mechanism.
"""

from __future__ import annotations

import hashlib
import json
import keyword
import re
import uuid
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from pprint import pformat
from typing import Any

import yaml

from eit_ptlc.action.registry import ActionDef, ActionRegistry
from eit_ptlc.unilab_domain.three_d import load_three_d_asset_facade
from eit_ptlc.unilab_domain.three_d.gltf_index import load_gltf_scene_index
from tools.export_unilab_workflow_variants import (
    export_workflow_variants,
    operation_view_uuid,
)


ROOT = Path(__file__).resolve().parents[1]
ACTIONS_DIR = ROOT / "eit_ptlc" / "config" / "actions"
DOMAIN_DIR = ROOT / "eit_ptlc" / "unilab_domain"
DEVICES_DIR = DOMAIN_DIR / "devices"
GENERATED_DIR = DOMAIN_DIR / "generated"
TRANSPORT_OPERATIONS_DIR = (
    ROOT / "eit_ptlc" / "config" / "operation" / "12_unilab_transport"
)
OPERATIONS_DIR = ROOT / "eit_ptlc" / "config" / "operation"
REVIEW_WORKFLOWS_DIR = ROOT / "eit_ptlc" / "workflows"
REVIEW_NAMESPACE = uuid.UUID("8a9f6e6c-7cc3-5e8f-a1ef-c5f4dd346e3a")
# CPython rejects modules with more than twenty statically nested blocks.
# Below this indentation the review keeps true group hierarchy; deeper VM
# nodes stay complete but are path-labelled at the nearest safe group level.
MAX_REVIEW_GROUP_INDENT = 44
LOOP_REVIEW_OPS = frozenset({"for", "while", "repeat"})
REVIEW_ROOTS = (
    "pf_af0_batch_startup",
    "pf_s1_load",
    "pf_s2_spot",
    "pf_s3_tank_prep",
    "pf_s4_photo_before",
    "pf_s5_to_tank",
    "pf_s6_develop_wait",
    "pf_s7_consumables",
    "pf_s8_to_scrape",
    "pf_s9_scrape",
    "pf_s10_collect",
    "pf_s11_unload",
)

# These are the station-level PlatformUI roots used by the longest executable
# UniLab workflow.  Each is projected as its own typed Action instead of making
# authors pass ``operation_name`` plus an opaque JSON string on the canvas.
# The generated implementation still delegates to PlatformUI's unchanged VM.
STATION_OPERATION_ACTIONS = {
    "sampling": ("sampling_prepare", "sampling_execute"),
    "develop": ("develop_prepare", "pf_s6_develop_wait"),
    "photoscrape": (
        "photoscrape_before_photo_capture",
        "photoscrape_process",
    ),
    "collect": ("collect_execute",),
}

OPERATION_VAR_TYPES = {
    "STRING": "str",
    "INT": "int",
    "FLOAT": "float",
    "BOOL": "bool",
    "DICT": "dict[str, Any]",
    "LIST": "list[Any]",
}

DEVICES = {
    "sampling": ("plc_sampling", "PLCSampling", "plc.sampling", "plc_sampling.py"),
    "develop": ("plc_develop", "PLCDevelop", "plc.develop", "plc_develop.py"),
    "collect": ("plc_collect", "PLCCollect", "plc.collect", "plc_collect.py"),
    "photoscrape": (
        "plc_photoscrape",
        "PLCPhotoScrape",
        "plc.photoscrape",
        "plc_photoscrape.py",
    ),
    "feedlift": ("plc_feedlift", "PLCFeedLift", "plc.feedlift", "plc_feedlift.py"),
    "rail": ("plc_rail", "PLCRail", "plc.rail", "plc_rail.py"),
    "robot": ("robot", "RobotProxy", "robot", "robot.py"),
    "pump": ("plc_pump", "PLCPump", "plc.pump", "plc_pump.py"),
    "vision": ("vision", "VisionProxy", "vision", "vision.py"),
    "staging_a": ("plc_staginga", "PLCStagingA", "plc.staginga", "plc_staginga.py"),
    "material": ("material", "MaterialProxy", "material", "material.py"),
}

FIELD_TYPES = {
    ("photoscrape.write_cnc_path", "sx"): "list[float]",
    ("photoscrape.write_cnc_path", "sy"): "list[float]",
    ("photoscrape.write_cnc_path", "cx"): "list[float]",
    ("photoscrape.write_cnc_path", "cy"): "list[float]",
    ("photoscrape.write_cnc_path", "feed"): "int",
    ("photoscrape.write_pass_z", "z"): "float",
}


def main() -> None:
    DEVICES_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    TRANSPORT_OPERATIONS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    registry = ActionRegistry.load(ACTIONS_DIR)
    actions = sorted(registry.list(), key=lambda item: item.name)
    if len(actions) != 93:
        raise RuntimeError(
            f"PlatformUI action catalog drifted: expected 93, got {len(actions)}"
        )
    facade = load_three_d_asset_facade()
    gltf = load_gltf_scene_index(facade.asset_path("scene"))
    station_operations = _load_named_operations(
        {
            operation_name
            for operation_names in STATION_OPERATION_ACTIONS.values()
            for operation_name in operation_names
        }
    )
    grouped = {namespace: [] for namespace in DEVICES}
    for action in actions:
        grouped[action.name.split(".", 1)[0]].append(action)
    if set(grouped) != set(DEVICES):
        raise RuntimeError("PlatformUI action namespaces drifted")
    for namespace, namespace_actions in grouped.items():
        _write_device(
            namespace,
            namespace_actions,
            station_operations,
            facade,
            gltf,
        )
    _write_devices_init()
    _write_action_manifest(actions, station_operations)
    _write_transport_catalog_and_operations()
    _write_operation_view_workflows_v2({item.name: item for item in actions})
    _write_operation_review_workflows({item.name: item for item in actions})
    export_workflow_variants()


def _write_device(
    namespace: str,
    actions: list[ActionDef],
    station_operations: dict[str, dict[str, Any]],
    facade: Any,
    gltf: Any,
) -> None:
    registry_id, class_name, canonical_id, filename = DEVICES[namespace]
    visual = facade.device_visual(namespace)
    if namespace == "robot":
        # This is the OS-native executable/renderable kinematic contract.
        # The richer PlatformUI scene remains a visual reference in metadata;
        # it must never be interpreted as a collision or planning model.
        model = {
            "type": "package_moveit",
            "provider": "unilab_arm_cr5:build_moveit_model",
            "source_digest": "8c8b9ea935fd83122b19b572c84d107e81b4864d4310c94d0906cc361e7631c2",
        }
    elif namespace == "material":
        # The material ledger is a logical authority, not another copy of the
        # physical machine scene.
        model = {}
    else:
        # The source-of-truth facade owns the stable entity binding.  Generated
        # registry code carries the pinned, format-specific projection only so
        # UniLab can instantiate the matching subtree of the shared GLB.
        record = gltf.resolve(visual.glb_node)
        model = {
            "$ref": "ptlc_shared_scene",
            "selector": {
                "kind": "gltf_subtree",
                "node_index": record.index,
                "node_path": record.path,
                "root_transform": "reset_translation",
                "exclude_node_paths": list(visual.excluded_glb_nodes),
            },
        }
    imports = [
        "from __future__ import annotations",
        "",
        "from typing import TypedDict",
        "",
        "from unilabos.registry.decorators import action, device",
        "",
        "from eit_ptlc.unilab_domain.devices.base import PlatformUIProxyBase",
    ]
    if namespace == "material":
        imports.extend(
            [
                "from eit_ptlc.unilab_domain.transport_runtime import (",
                "    execute_transport_root,",
                "    preflight_transport,",
                ")",
                "from eit_ptlc.unilab_domain.material_lineage import (",
                "    record_collection,",
                "    record_scraping,",
                "    record_spotting,",
                ")",
                "from eit_ptlc.unilab_domain.operation_review import (",
                "    bind_parallel_operation_inputs,",
                "    run_review_root,",
                "    verify_operation_call,",
                "    verify_review_node,",
                ")",
                "from unilabos.registry.placeholder_type import ResourceSlot",
            ]
        )
    lines = imports + [
        "",
        "",
        "class PlatformActionResult(TypedDict):",
        "    action: str",
        "    request_id: str",
        "    command_id: str",
        "    status: str",
        "    accepted: bool",
        "    result_json: str",
    ]
    if namespace == "material":
        lines.extend(
            [
                "",
                "",
                "class TransportPreflightV4Result(TypedDict):",
                "    operation_name: str",
                "    operation_inputs_json: str",
                "    source_site: str",
                "    target_site: str",
                "    required_tool: str",
                "    source_rail_target: int",
                "    target_rail_target: int",
                "    safety_anchor: str",
                "    command_id: str",
                "",
                "",
                "class TransportPhysicalV4Result(TypedDict):",
                "    resource: ResourceSlot",
                "    target_site: str",
                "    operation_name: str",
                "    command_id: str",
                "    status: str",
                "",
                "",
                "class SpottingLineageV4Result(TypedDict):",
                "    sample_vial: ResourceSlot",
                "    plate: ResourceSlot",
                "    stage: str",
                "",
                "",
                "class ScrapingLineageV4Result(TypedDict):",
                "    plate: ResourceSlot",
                "    powder_collector: ResourceSlot",
                "    stage: str",
                "",
                "",
                "class CollectionLineageV4Result(TypedDict):",
                "    powder_collector: ResourceSlot",
                "    vial: ResourceSlot",
                "    stage: str",
                "",
                "",
                "class PlatformOperationReviewV1Result(TypedDict):",
                "    operation_name: str",
                "    command_id: str",
                "    run_id: str",
                "    status: str",
                "    result_json: str",
                "    before_path: str",
                "    collector_hole: int",
                "    bottle_hole: int",
                "",
                "",
                "class ParallelOperationInputsV1Result(TypedDict):",
                "    inputs_json: str",
                "",
                "",
                "class OperationReviewMarkerV1Result(TypedDict):",
                "    operation_name: str",
                "    node_path: str",
                "    control_kind: str",
                "    status: str",
                "",
                "",
                "class OperationCallReviewV2Result(TypedDict):",
                "    operation_name: str",
                "    inputs_json: str",
                "    status: str",
            ]
        )
    elif namespace not in {"robot", "rail", "pump", "vision", "staging_a"}:
        lines.extend(
            [
                "",
                "",
                "class PlatformOperationResult(TypedDict):",
                "    operation_name: str",
                "    command_id: str",
                "    run_id: str",
                "    status: str",
                "    result_json: str",
            ]
        )
    metadata = {
        "platformui_device_id": canonical_id,
        "platformui_action_namespace": namespace,
        "runtime_authority": "PlatformUI",
        "shared_runtime_port": "eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort",
        "three_d_facade": "eit_ptlc/three_d/unilab_facade.v1.yaml",
        "three_d_selector": {
            "node": visual.glb_node,
            "manifest_section": visual.manifest_section,
        },
    }
    if namespace == "robot":
        metadata["platformui_display_scene"] = {
            "asset": "eit_ptlc/three_d/models/machine.official-cr5.glb",
            "node": visual.glb_node,
            "motion_authority": False,
        }
    lines.extend(
        [
            "",
            "",
            "@device(",
            f"    id={registry_id!r},",
            f"    category={['ptlc', namespace, 'platformui-proxy']!r},",
            f"    displayname={canonical_id!r},",
            f"    description={'PlatformUI ' + canonical_id + ' 的原样动作代理；不复制设备业务逻辑。'!r},",
            "    version='4.0.0',",
            f"    model={pformat(model, width=100, sort_dicts=False)},",
            f"    metadata={pformat(metadata, width=100, sort_dicts=False)},",
            ")",
            f"class {class_name}(PlatformUIProxyBase):",
            f"    platformui_namespace = {canonical_id!r}",
        ]
    )
    for item in actions:
        lines.extend(_render_action(item))
    for operation_name in STATION_OPERATION_ACTIONS.get(namespace, ()):
        lines.extend(
            _render_typed_station_operation_action(station_operations[operation_name])
        )
    if namespace == "material":
        lines.extend(_render_transport_actions())
    elif namespace not in {"robot", "rail", "pump", "vision", "staging_a"}:
        lines.extend(_render_station_operation_action())
    lines.extend(["", "", f"__all__ = [{class_name!r}]", ""])
    (DEVICES_DIR / filename).write_text("\n".join(lines), encoding="utf-8")


def _render_action(item: ActionDef) -> list[str]:
    suffix = item.name.split(".", 1)[1]
    method_name = _identifier(suffix)
    parameters: list[tuple[str, str, bool, Any]] = []
    for param in item.params:
        parameters.append(
            (
                _identifier(param.name),
                _type_name(param.type),
                param.required,
                param.default,
            )
        )
    for field in item.fields:
        parameters.append(
            (_identifier(field.key), FIELD_TYPES[(item.name, field.key)], True, None)
        )
    parameters.sort(key=lambda row: not row[2])
    rendered = ["self"]
    for name, type_name, required, default in parameters:
        if required:
            rendered.append(f"{name}: {type_name}")
        else:
            if default is None:
                rendered.append(f"{name}: {type_name} | None = None")
            else:
                rendered.append(f"{name}: {type_name} = {default!r}")
    signature = ", ".join(rendered)
    params_dict = ", ".join(f"{name!r}: {name}" for name, *_ in parameters)
    description = " ".join(item.desc.split())
    return [
        "",
        f"    @action(action_name={method_name!r}, displayname={item.label!r}, description={description!r})",
        f"    async def {method_name}({signature}) -> PlatformActionResult:",
        f"        return await self._invoke({item.name!r}, {{{params_dict}}})",
    ]


def _render_transport_actions() -> list[str]:
    return [
        "",
        "    @action(",
        "        action_name='transport_preflight_v4',",
        "        displayname='pTLC 通用转运 v4·合同解析',",
        "        description='只读解析物料源位、目标位、工具、地轨目标和唯一 PlatformUI 根 operation。',",
        "    )",
        "    async def transport_preflight_v4(",
        "        self,",
        "        resource: ResourceSlot,",
        "        target_device: str,",
        "        target_mount: ResourceSlot,",
        "        target_site: str,",
        "    ) -> TransportPreflightV4Result:",
        "        return preflight_transport(",
        "            resource=resource,",
        "            target_device=target_device,",
        "            target_mount=target_mount,",
        "            target_site=target_site,",
        "        )",
        "",
        "    @action(",
        "        action_name='transport_physical_v4',",
        "        displayname='pTLC 通用转运 v4·锁内执行',",
        "        description='恰好一次提交根 operation；由既有 ResourceGate 全程锁定机器人和地轨。',",
        "    )",
        "    async def transport_physical_v4(",
        "        self,",
        "        resource: ResourceSlot,",
        "        operation_name: str,",
        "        operation_inputs_json: str,",
        "        command_id: str,",
        "        target_site: str,",
        "        timeout_s: float = 3600.0,",
        "    ) -> TransportPhysicalV4Result:",
        "        return await execute_transport_root(",
        "            self._runtime,",
        "            resource=resource,",
        "            operation_name=operation_name,",
        "            operation_inputs_json=operation_inputs_json,",
        "            command_id=command_id,",
        "            target_site=target_site,",
        "            timeout_s=timeout_s,",
        "        )",
        "",
        "    @action(",
        "        action_name='record_spotting_v4',",
        "        displayname='记录点样物料谱系',",
        "        description='纯数据连接：把输入样品瓶身份与完成点样的同一硅胶板关联。',",
        "        always_free=True,",
        "    )",
        "    async def record_spotting_v4(",
        "        self, sample_vial: ResourceSlot, plate: ResourceSlot",
        "    ) -> SpottingLineageV4Result:",
        "        return record_spotting(sample_vial, plate)",
        "",
        "    @action(",
        "        action_name='record_scraping_v4',",
        "        displayname='记录刮取物料谱系',",
        "        description='纯数据连接：把刮下的样品身份从同一硅胶板关联到接粉器。',",
        "        always_free=True,",
        "    )",
        "    async def record_scraping_v4(",
        "        self, plate: ResourceSlot, powder_collector: ResourceSlot",
        "    ) -> ScrapingLineageV4Result:",
        "        return record_scraping(plate, powder_collector)",
        "",
        "    @action(",
        "        action_name='record_collection_v4',",
        "        displayname='记录收集物料谱系',",
        "        description='纯数据连接：把接粉器中的样品身份汇入同一收集瓶。',",
        "        always_free=True,",
        "    )",
        "    async def record_collection_v4(",
        "        self, powder_collector: ResourceSlot, vial: ResourceSlot",
        "    ) -> CollectionLineageV4Result:",
        "        return record_collection(powder_collector, vial)",
        "",
        "    @action(",
        "        action_name='bind_parallel_operation_inputs_v1',",
        "        displayname='绑定并行段跨段输出',",
        "        description='把 s4/s7 的真实运行输出覆盖进 s9/s10 输入 JSON；纯数据动作。',",
        "        always_free=True,",
        "    )",
        "    async def bind_parallel_operation_inputs_v1(",
        "        self, inputs_json: str = '{}', before_path: str = '', collector_hole: int = 0, bottle_hole: int = 0",
        "    ) -> ParallelOperationInputsV1Result:",
        "        return bind_parallel_operation_inputs(",
        "            inputs_json=inputs_json,",
        "            before_path=before_path,",
        "            collector_hole=collector_hole,",
        "            bottle_hole=bottle_hole,",
        "        )",
        "",
        "    @action(",
        "        action_name='review_operation_call_v2',",
        "        displayname='PlatformUI operation 调用合同',",
        "        description='只读展示并校验 operation 名、格式化参数和源 YAML 摘要；不提交 operation。',",
        "        always_free=True,",
        "    )",
        "    async def review_operation_call_v2(",
        "        self, operation_name: str, inputs_json: str, expected_sha256: str",
        "    ) -> OperationCallReviewV2Result:",
        "        return verify_operation_call(",
        "            operation_name=operation_name,",
        "            inputs_json=inputs_json,",
        "            expected_sha256=expected_sha256,",
        "        )",
        "",
        "    @action(",
        "        action_name='review_control_node_v1',",
        "        displayname='PlatformUI 控制节点来源校验',",
        "        description='只读校验审阅投影中的条件、循环、HITL、变量和说明节点仍与源 operation 一致。',",
        "        always_free=True,",
        "    )",
        "    async def review_control_node_v1(",
        "        self, operation_name: str, node_path: str, control_kind: str, expected_sha256: str",
        "    ) -> OperationReviewMarkerV1Result:",
        "        return verify_review_node(",
        "            operation_name=operation_name,",
        "            node_path=node_path,",
        "            control_kind=control_kind,",
        "            expected_sha256=expected_sha256,",
        "        )",
        "",
        "    @action(",
        "        action_name='run_operation_review_v1',",
        "        displayname='原子执行 PlatformUI 根 operation',",
        "        description='审阅投影唯一启用的物理节点；整段一次提交，条件、HITL 与 ResourceGate 全由 PlatformUI 执行。',",
        # The material proxy is only a bridge.  Serializing every root operation
        # on this virtual UniLab device would destroy PlatformUI's independent
        # ResourceGate concurrency.  OS material locks and DAG dependencies are
        # still enforced separately by the scheduler.
        "        always_free=True,",
        "    )",
        "    async def run_operation_review_v1(",
        "        self, operation_name: str, inputs_json: str = '{}', timeout_s: float = 3600.0",
        "    ) -> PlatformOperationReviewV1Result:",
        "        return await run_review_root(",
        "            self._runtime,",
        "            operation_name=operation_name,",
        "            inputs_json=inputs_json,",
        "            timeout_s=timeout_s,",
        "        )",
    ]


def _render_station_operation_action() -> list[str]:
    return [
        "",
        "    @action(",
        "        action_name='run_station_operation_v4',",
        "        displayname='运行 PlatformUI 工位流程',",
        "        description='一次提交不含机器人和地轨的现有 PlatformUI 根 operation；运动根会被硬拒绝。',",
        "    )",
        "    async def run_station_operation_v4(",
        "        self, operation_name: str, inputs_json: str = '{}', timeout_s: float = 3600.0",
        "    ) -> PlatformOperationResult:",
        "        return await self._run_station_operation(",
        "            operation_name, inputs_json, timeout_s=timeout_s",
        "        )",
    ]


def _render_typed_station_operation_action(document: dict[str, Any]) -> list[str]:
    operation_name = str(document["name"])
    method_name = _identifier(operation_name)
    input_vars = [
        item
        for item in document.get("vars") or []
        if isinstance(item, dict) and item.get("io") in {"in", "inout"}
    ]
    parameters: list[tuple[str, str, Any]] = []
    for item in input_vars:
        name = _identifier(str(item["name"]))
        type_name = OPERATION_VAR_TYPES.get(str(item.get("type") or "").upper())
        if type_name is None:
            raise RuntimeError(
                f"unsupported PlatformUI operation input type: "
                f"{operation_name}.{item.get('name')}={item.get('type')}"
            )
        default = item.get("default") if "default" in item else None
        parameters.append((name, type_name, default))

    signature_parts = ["self"]
    for name, type_name, default in parameters:
        if default is None:
            signature_parts.append(f"{name}: {type_name} | None = None")
        else:
            signature_parts.append(f"{name}: {type_name} = {default!r}")
    signature_parts.append("timeout_s: float = 3600.0")

    label = str(document.get("label") or operation_name)
    description = (
        f"PlatformUI operation {operation_name} 的类型化 UniLab Action；"
        "逐字段参数会编码后交给既有 VM，工位资源锁与控制流语义不变。"
    )
    lines = [
        "",
        "    @action(",
        f"        action_name={method_name!r},",
        f"        displayname={label!r},",
        f"        description={description!r},",
        "    )",
        f"    async def {method_name}(",
    ]
    lines.extend(f"        {part}," for part in signature_parts)
    lines.extend(
        [
            "    ) -> PlatformOperationResult:",
            f'        """Run {operation_name} through the unchanged PlatformUI operation VM.',
            "",
            "        Args:",
        ]
    )
    for item, (name, _, _) in zip(input_vars, parameters, strict=True):
        ui = item.get("ui") if isinstance(item.get("ui"), dict) else {}
        title = str(ui.get("label") or item.get("comment") or item["name"])
        title = " ".join(title.replace("]", ")").split())
        detail = " ".join(str(item.get("comment") or title).split())
        lines.append(f"            {name}[{title}]: {detail}")
    lines.extend(
        [
            "            timeout_s[运行超时（秒）]: PlatformUI 根 operation 的绝对等待上限。",
            '        """',
            "        return await self._run_typed_station_operation(",
            f"            {operation_name!r},",
            "            {",
        ]
    )
    for name, _, _ in parameters:
        lines.append(f"                {name!r}: {name},")
    lines.extend(
        [
            "            },",
            "            timeout_s=timeout_s,",
            "        )",
        ]
    )
    return lines


def _load_named_operations(names: set[str]) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for path in OPERATIONS_DIR.rglob("*.yaml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        name = document.get("name")
        if name not in names:
            continue
        if name in documents:
            raise RuntimeError(f"duplicate PlatformUI operation: {name}")
        documents[name] = document
    missing = names - set(documents)
    if missing:
        raise RuntimeError(f"missing typed station operations: {sorted(missing)}")
    return documents


def _write_devices_init() -> None:
    imports = []
    names = []
    for _, class_name, _, filename in DEVICES.values():
        module = filename.removesuffix(".py")
        imports.append(
            f"from eit_ptlc.unilab_domain.devices.{module} import {class_name}"
        )
        names.append(class_name)
    body = "\n".join(imports) + "\n\n__all__ = " + pformat(names, width=100) + "\n"
    (DEVICES_DIR / "__init__.py").write_text(body, encoding="utf-8")


def _write_action_manifest(
    actions: list[ActionDef],
    station_operations: dict[str, dict[str, Any]],
) -> None:
    sources = sorted(ACTIONS_DIR.rglob("*.yaml"))
    digest = hashlib.sha256()
    for source in sources:
        digest.update(source.relative_to(ROOT).as_posix().encode())
        digest.update(source.read_bytes())
    rows = []
    for item in actions:
        namespace = item.name.split(".", 1)[0]
        registry_id = DEVICES[namespace][0]
        params = [asdict(param) for param in item.params]
        for field in item.fields:
            params.append(
                {
                    "name": field.key,
                    "type": FIELD_TYPES[(item.name, field.key)],
                    "required": True,
                    "label": field.label,
                    "plc_node": field.node,
                }
            )
        rows.append(
            {
                "name": item.name,
                "namespace": namespace,
                "unilab_device_id": registry_id,
                "unilab_action": _identifier(item.name.split(".", 1)[1]),
                "kind": item.kind,
                "modes": list(item.modes),
                "retryable": item.retryable,
                "params": params,
            }
        )
    payload = {
        "schema": "unilab.platformui-actions/v1",
        "generated_from": "eit_ptlc/config/actions/**/*.yaml",
        "source_sha256": digest.hexdigest(),
        "external_action_count": len(rows),
        "typed_operation_action_count": len(station_operations),
        "proxy_device_count": len(DEVICES),
        "actions": rows,
        "typed_operation_actions": [
            {
                "operation_name": operation_name,
                "namespace": namespace,
                "unilab_device_id": DEVICES[namespace][0],
                "unilab_action": _identifier(operation_name),
                "params": [
                    {
                        "name": str(item["name"]),
                        "type": str(item.get("type") or ""),
                        "required": "default" not in item,
                        **({"default": item["default"]} if "default" in item else {}),
                        "label": str(
                            (item.get("ui") or {}).get("label")
                            or item.get("comment")
                            or item["name"]
                        ),
                    }
                    for item in station_operations[operation_name].get("vars") or []
                    if isinstance(item, dict) and item.get("io") in {"in", "inout"}
                ],
            }
            for namespace, operation_names in STATION_OPERATION_ACTIONS.items()
            for operation_name in operation_names
        ],
    }
    _dump_yaml(GENERATED_DIR / "platformui_actions.v1.yaml", payload)


def _write_transport_catalog_and_operations() -> None:
    aliases = {
        "feedlift": "feedlift",
        "feedlift:plate": "feedlift",
        "plc-feedlift": "feedlift",
        "sampling": "spot-seat",
        "plc-sampling": "spot-seat",
        "sampling:plate": "spot-seat",
        "plc-sampling:plate": "spot-seat",
        "spot-seat": "spot-seat",
        "photoscrape": "scrape-table",
        "plc-photoscrape": "scrape-table",
        "photoscrape:plate": "scrape-table",
        "plc-photoscrape:plate": "scrape-table",
        "scrape-table": "scrape-table",
        "waste": "waste",
        "plc-feedlift:waste-stack": "waste",
        "scrape-holder": "scrape-holder",
        "plc-photoscrape:collector": "scrape-holder",
        "collect-holder": "collect-holder",
        "plc-collect:collector": "collect-holder",
        "collect-bottle": "collect-bottle",
        "plc-collect:vial": "collect-bottle",
        "staging-a-stack:rack": "staging-a:rack",
        "staging-b-stack:rack": "staging-b:rack",
        "staging-a-stack": "staging-a:1",
        "staging-b-stack": "staging-b:1",
    }
    for index in range(1, 9):
        aliases[f"develop:tank-{index}"] = f"tank:{index}"
        aliases[f"plc-develop:tank-{index}"] = f"tank:{index}"
        aliases[f"tank-{index}"] = f"tank:{index}"
        aliases[f"tank:{index}"] = f"tank:{index}"
    for index in range(1, 13):
        aliases[f"collector-rack-{index}"] = f"collector-rack:{index}"
        aliases[f"bottle-rack-{index}"] = f"bottle-rack:{index}"
    for index in range(1, 7):
        aliases[f"staging-a-stack:item-{index}"] = f"staging-a:{index}"
        aliases[f"staging-b-stack:item-{index}"] = f"staging-b:{index}"
        aliases[f"plc-staginga:collector-item-{index}"] = f"staging-a:{index}"
        aliases[f"plc-staginga:bottle-item-{index}"] = f"staging-b:{index}"

    routes = [
        _route(
            "feedlift",
            "spot-seat",
            "plc_sampling",
            "unilab_transport_v4_feedlift_to_spot",
            {},
            "suction",
            1,
            2,
            ["robot", "station:rail", "station:feedlift", "station:sampling"],
        ),
        _route(
            "spot-seat",
            "scrape-table",
            "plc_photoscrape",
            "unilab_transport_v4_spot_to_scrape",
            {},
            "suction",
            2,
            2,
            ["robot", "station:rail", "station:sampling", "station:photo_scrape"],
        ),
        _route(
            "scrape-table",
            "tank:{tank}",
            "plc_develop",
            "unilab_transport_v4_scrape_to_tank",
            {"tank": "{tank}"},
            "suction",
            2,
            5,
            ["robot", "station:rail", "station:photo_scrape", "station:develop"],
        ),
        _route(
            "tank:{tank}",
            "scrape-table",
            "plc_photoscrape",
            "unilab_transport_v4_tank_to_scrape",
            {"tank": "{tank}"},
            "suction",
            5,
            2,
            ["robot", "station:rail", "station:develop", "station:photo_scrape"],
        ),
        _route(
            "scrape-table",
            "waste",
            "plc_feedlift",
            "unilab_transport_v4_scrape_to_waste",
            {},
            "suction",
            2,
            1,
            ["robot", "station:rail", "station:photo_scrape", "station:feedlift"],
        ),
        _route(
            "staging-a:{slot}",
            "scrape-holder",
            "plc_photoscrape",
            "unilab_transport_v4_collector_staging_to_scrape",
            {"slot_id": "{slot}"},
            "small_gripper",
            2,
            2,
            [
                "robot",
                "station:rail",
                "staging-a",
                "scrape-holder",
                "station:photo_scrape",
            ],
        ),
        _route(
            "scrape-holder",
            "collect-holder",
            "plc_collect",
            "unilab_transport_v4_collector_scrape_to_collect",
            {},
            "small_gripper",
            2,
            3,
            [
                "robot",
                "station:rail",
                "scrape-holder",
                "collect-holder",
                "station:photo_scrape",
                "station:collect",
            ],
        ),
        _route(
            "staging-b:{slot}",
            "collect-bottle",
            "plc_collect",
            "unilab_transport_v4_bottle_staging_to_collect",
            {"slot_id": "{slot}"},
            "small_gripper",
            3,
            3,
            ["robot", "station:rail", "staging-b", "collect-bottle"],
        ),
        _route(
            "collect-bottle",
            "staging-b:{slot}",
            "plc_staginga",
            "unilab_transport_v4_bottle_collect_to_staging",
            {"slot_id": "{slot}"},
            "small_gripper",
            3,
            3,
            ["robot", "station:rail", "collect-bottle", "staging-b"],
        ),
        _route(
            "collect-holder",
            "staging-a:{slot}",
            "plc_staginga",
            "unilab_transport_v4_collector_collect_to_staging",
            {"slot_id": "{slot}"},
            "small_gripper",
            3,
            3,
            ["robot", "station:rail", "collect-holder", "staging-a", "station:collect"],
        ),
        _route(
            "collector-rack:{slot}",
            "staging-a:rack",
            "plc_staginga",
            "unilab_transport_v4_collector_rack_to_staging",
            {"slot_id": "{slot}"},
            "large_gripper",
            4,
            2,
            ["robot", "station:rail", "consumable-group", "staging-a"],
        ),
        _route(
            "staging-a:rack",
            "collector-rack:{slot}",
            "material",
            "unilab_transport_v4_collector_staging_to_rack",
            {"slot_id": "{slot}"},
            "large_gripper",
            2,
            4,
            ["robot", "station:rail", "consumable-group", "staging-a"],
        ),
        _route(
            "bottle-rack:{slot}",
            "staging-b:rack",
            "plc_staginga",
            "unilab_transport_v4_bottle_rack_to_staging",
            {"slot_id": "{slot}"},
            "large_gripper",
            4,
            3,
            ["robot", "station:rail", "consumable-group", "staging-b"],
        ),
        _route(
            "staging-b:rack",
            "bottle-rack:{slot}",
            "material",
            "unilab_transport_v4_bottle_staging_to_rack",
            {"slot_id": "{slot}"},
            "large_gripper",
            3,
            4,
            ["robot", "station:rail", "consumable-group", "staging-b"],
        ),
    ]
    payload = {
        "schema": "unilab.ptlc-transport-routes/v1",
        "generated_from": [
            "eit_ptlc/config/operation/01_sampling..08_rail",
            "eit_ptlc/config/operation/11_parallel",
            "eit_ptlc/config/material_bindings.yaml",
        ],
        "contract_inputs": ["resource", "target_device", "target_mount", "target_site"],
        "lock_authority": "eit_ptlc.operation.resources.ResourceGate",
        "site_aliases": aliases,
        "routes": routes,
    }
    _dump_yaml(GENERATED_DIR / "transport_routes.v1.yaml", payload)

    operations = _transport_operations()
    for name, document in operations.items():
        _dump_yaml(TRANSPORT_OPERATIONS_DIR / f"{name}.yaml", document)


def _route(
    source: str,
    target: str,
    target_device: str,
    operation: str,
    inputs: dict[str, Any],
    tool: str,
    source_rail_target: int,
    target_rail_target: int,
    resources: list[str],
) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "target_device": target_device,
        "operation": operation,
        "inputs": inputs,
        "tool": tool,
        "source_rail_target": source_rail_target,
        "target_rail_target": target_rail_target,
        "safety_anchor": "P1",
        "resources": resources,
    }


def _transport_operations() -> dict[str, dict[str, Any]]:
    def operation(
        name: str,
        label: str,
        resources: list[str],
        body: list[dict[str, Any]],
        vars: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": "ptlc.script/v1",
            "kind": "operation",
            "name": name,
            "label": label,
            "ui": {"role": "unilab_transport_v4", "projection_only": True},
            "vars": vars or [],
            "resources": resources,
            "body": body,
        }

    def run(script: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "op": "run_script",
            "script": script,
            "inputs": inputs or {},
            "outputs": {},
        }

    def var(name: str) -> dict[str, str]:
        return {"var": name}

    def lit(value: Any) -> dict[str, Any]:
        return {"lit": value}

    tank_var = [
        {"name": "tank", "scope": "local", "type": "INT", "io": "in", "default": 1}
    ]
    slot_var = [
        {"name": "slot_id", "scope": "local", "type": "INT", "io": "in", "default": 1}
    ]
    documents: dict[str, dict[str, Any]] = {}
    documents["unilab_transport_v4_feedlift_to_spot"] = operation(
        "unilab_transport_v4_feedlift_to_spot",
        "v4 转运 板仓→点样座",
        ["robot", "station:rail", "station:feedlift", "station:sampling"],
        [run("sampling_load")],
    )
    documents["unilab_transport_v4_spot_to_scrape"] = operation(
        "unilab_transport_v4_spot_to_scrape",
        "v4 转运 点样座→刮板台",
        ["robot", "station:rail", "station:sampling", "station:photo_scrape"],
        [
            run("sampling_unload"),
            run("photoscrape_prepare"),
            run("photoscrape_plate_load"),
        ],
    )
    documents["unilab_transport_v4_scrape_to_tank"] = operation(
        "unilab_transport_v4_scrape_to_tank",
        "v4 转运 刮板台→展开缸",
        ["robot", "station:rail", "station:photo_scrape", "station:develop"],
        [
            run("photoscrape_unload"),
            run("rail_move_safe", {"target": lit(5)}),
            run("develop_load", {"tank": var("tank")}),
        ],
        tank_var,
    )
    documents["unilab_transport_v4_tank_to_scrape"] = operation(
        "unilab_transport_v4_tank_to_scrape",
        "v4 转运 展开缸→刮板台",
        ["robot", "station:rail", "station:develop", "station:photo_scrape"],
        [
            run("develop_unload", {"tank": var("tank")}),
            run("photoscrape_prepare"),
            run("photoscrape_plate_load"),
        ],
        tank_var,
    )
    documents["unilab_transport_v4_scrape_to_waste"] = operation(
        "unilab_transport_v4_scrape_to_waste",
        "v4 转运 刮板台→废板仓",
        ["robot", "station:rail", "station:photo_scrape", "station:feedlift"],
        [run("photoscrape_unload"), run("feedlift_unload_cycle")],
    )

    existing = {
        "unilab_transport_v4_collector_staging_to_scrape": (
            "transfer_collector_staging_a_to_scrape",
            [
                "robot",
                "station:rail",
                "staging-a",
                "scrape-holder",
                "station:photo_scrape",
            ],
        ),
        "unilab_transport_v4_bottle_staging_to_collect": (
            "transfer_bottle_staging_b_to_collect",
            ["robot", "station:rail", "staging-b", "collect-bottle"],
        ),
        "unilab_transport_v4_bottle_collect_to_staging": (
            "transfer_bottle_collect_to_staging_b",
            ["robot", "station:rail", "collect-bottle", "staging-b"],
        ),
        "unilab_transport_v4_collector_rack_to_staging": (
            "transfer_collector_rack_to_staging_a",
            ["robot", "station:rail", "consumable-group", "staging-a"],
        ),
        "unilab_transport_v4_collector_staging_to_rack": (
            "transfer_collector_staging_a_to_rack",
            ["robot", "station:rail", "consumable-group", "staging-a"],
        ),
        "unilab_transport_v4_bottle_rack_to_staging": (
            "transfer_bottle_rack_to_staging_b",
            ["robot", "station:rail", "consumable-group", "staging-b"],
        ),
        "unilab_transport_v4_bottle_staging_to_rack": (
            "transfer_bottle_staging_b_to_rack",
            ["robot", "station:rail", "consumable-group", "staging-b"],
        ),
    }
    for name, (script, resources) in existing.items():
        documents[name] = operation(
            name,
            f"v4 转运 {script}",
            resources,
            [run(script, {"slot_id": var("slot_id")})],
            slot_var,
        )

    documents["unilab_transport_v4_collector_scrape_to_collect"] = operation(
        "unilab_transport_v4_collector_scrape_to_collect",
        "v4 转运 刮板接粉夹具→收集夹具",
        [
            "robot",
            "station:rail",
            "scrape-holder",
            "collect-holder",
            "station:photo_scrape",
            "station:collect",
        ],
        [
            run("rail_move_safe", {"target": lit(2)}),
            run("robot_scrape_holder_pick_enter", {"station_id": lit("default")}),
            {
                "op": "call",
                "action": "photoscrape.press_cylinder",
                "mode": "RUN",
                "args": {"pressed": lit(False)},
            },
            run("robot_scrape_holder_pick_exit", {"station_id": lit("default")}),
            {"op": "call", "action": "photoscrape.retr_stoprot", "mode": "RUN"},
            run("rail_move_safe", {"target": lit(3)}),
            run("robot_collect_holder_put_enter", {"station_id": lit("default")}),
            {"op": "call", "action": "collect.clamp", "mode": "RUN"},
            run("robot_collect_holder_put_exit", {"station_id": lit("default")}),
            {"op": "call", "action": "collect.extend", "mode": "RUN"},
        ],
    )
    documents["unilab_transport_v4_collector_collect_to_staging"] = operation(
        "unilab_transport_v4_collector_collect_to_staging",
        "v4 转运 收集夹具→中转A",
        ["robot", "station:rail", "collect-holder", "staging-a", "station:collect"],
        [
            {"op": "call", "action": "collect.retract", "mode": "RUN"},
            run("robot_collect_holder_pick_enter", {"station_id": lit("default")}),
            {"op": "call", "action": "collect.release_clamp", "mode": "RUN"},
            run("robot_collect_holder_pick_exit", {"station_id": lit("default")}),
            run(
                "robot_collector_return_put",
                {"slot_id": var("slot_id"), "enter_anchor": lit("P70")},
            ),
        ],
        slot_var,
    )
    return documents


def _write_operation_view_workflows_v2(actions: dict[str, ActionDef]) -> None:
    """Generate child-first, display-only operation views without recursive inlining."""

    documents: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for path in OPERATIONS_DIR.rglob("*.yaml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        name = document.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name in documents:
            raise RuntimeError(f"duplicate PlatformUI operation: {name}")
        documents[name] = document
        paths[name] = path
    missing_roots = set(REVIEW_ROOTS) - set(documents)
    if missing_roots:
        raise RuntimeError(f"missing operation-view roots: {sorted(missing_roots)}")

    def direct_children(operation_name: str) -> list[str]:
        children: list[str] = []
        for node in _review_visible_operation_nodes(
            documents[operation_name].get("body") or []
        ):
            if node.get("op") != "run_script":
                continue
            child = str(node.get("script") or "")
            if child not in documents:
                raise RuntimeError(
                    f"unknown PlatformUI child operation: {operation_name} -> {child}"
                )
            if child not in children:
                children.append(child)
        return children

    ordered_operations: list[str] = []
    visited: set[str] = set()
    visiting: set[str] = set()
    cycle_edges: set[tuple[str, str]] = set()

    def visit(operation_name: str) -> None:
        if operation_name in visited:
            return
        visiting.add(operation_name)
        for child in direct_children(operation_name):
            if child in visiting:
                cycle_edges.add((operation_name, child))
                continue
            visit(child)
        visiting.remove(operation_name)
        visited.add(operation_name)
        ordered_operations.append(operation_name)

    for root_name in REVIEW_ROOTS:
        visit(root_name)

    operation_rows: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for operation_name in ordered_operations:
        renderer = _OperationViewV2Renderer(
            operation_name=operation_name,
            documents=documents,
            actions=actions,
            cycle_edges=cycle_edges,
        )
        output_path = (
            REVIEW_WORKFLOWS_DIR / f"{operation_name}_operation_view_v2.py"
        )
        output_path.write_text(renderer.render(), encoding="utf-8")
        source_path = paths[operation_name]
        digest.update(source_path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(source_path.read_bytes())
        operation_rows.append(
            {
                "operation_name": operation_name,
                "workflow_uuid": renderer.workflow_uuid,
                "source": output_path.relative_to(ROOT).as_posix(),
                "direct_source_node_count": renderer.direct_source_node_count,
                "direct_action_count": renderer.action_count,
                "direct_run_script_children": direct_children(operation_name),
                "loop_boundary_count": renderer.loop_boundary_count,
                "recursive_reference_count": renderer.recursive_reference_count,
                "projection_node_count": renderer.projection_node_count,
                "group_node_count": renderer.group_node_count,
            }
        )

    manifest = {
        "schema": "unilab.platformui-operation-views/v2",
        "generated_from": "eit_ptlc/config/operation/**/*.yaml",
        "source_sha256": digest.hexdigest(),
        "semantics": {
            "projection_actions_disabled": True,
            "run_script_projection": "expandable_composite_children_display_only",
            "operation_parameter_projection": (
                "formatted_source_defaults_and_parent_call_binding_metadata"
            ),
            "loop_projection": "marker_only_body_not_expanded",
            "execution": "display_only_no_platformui_submission",
            "recursive_reference_projection": "disabled_reference_marker",
        },
        "root_count": len(REVIEW_ROOTS),
        "roots": list(REVIEW_ROOTS),
        "workflow_count": len(operation_rows),
        "operations": operation_rows,
    }
    _dump_yaml(GENERATED_DIR / "platformui_operation_views.v2.yaml", manifest)


def _operation_view_inputs_json(document: dict[str, Any]) -> str:
    """Format source-declared input defaults for the disabled review action."""

    fallback_by_type: dict[str, Any] = {
        "BOOL": False,
        "DICT": {},
        "FLOAT": 0.0,
        "INT": 0,
        "LIST": [],
        "STRING": "",
    }
    values: dict[str, Any] = {}
    for item in document.get("vars") or []:
        if not isinstance(item, dict) or item.get("io") not in {"in", "inout"}:
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        values[name] = (
            item["default"]
            if "default" in item
            else fallback_by_type.get(str(item.get("type") or "").upper())
        )
    return json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class _OperationViewV2Renderer:
    """Render one operation as disabled leaves and expandable child views."""

    def __init__(
        self,
        *,
        operation_name: str,
        documents: dict[str, dict[str, Any]],
        actions: dict[str, ActionDef],
        cycle_edges: set[tuple[str, str]],
    ) -> None:
        self.operation_name = operation_name
        self.documents = documents
        self.actions = actions
        self.cycle_edges = cycle_edges
        self.workflow_uuid = operation_view_uuid(operation_name)
        self._workflow_namespace = uuid.UUID(self.workflow_uuid)
        self.lines: list[str] = []
        self.result_index = 0
        self.action_count = 0
        self.loop_boundary_count = 0
        self.recursive_reference_count = 0
        self.projection_node_count = 0
        self.group_node_count = 0
        self.direct_source_node_count = len(
            _review_visible_operation_nodes(
                documents[operation_name].get("body") or []
            )
        )

    def render(self) -> str:
        document = self.documents[self.operation_name]
        operation_inputs_json = _operation_view_inputs_json(document)
        visible_nodes = _review_visible_operation_nodes(document.get("body") or [])
        namespaces = {
            str(node.get("action") or "").split(".", 1)[0]
            for node in visible_nodes
            if node.get("op") == "call"
        }
        namespaces.add("material")
        child_names: list[str] = []
        for node in visible_nodes:
            if node.get("op") != "run_script":
                continue
            child = str(node.get("script") or "")
            if (self.operation_name, child) in self.cycle_edges:
                continue
            if child not in child_names:
                child_names.append(child)

        imports = [
            "from __future__ import annotations",
            "",
            "from unilabos.workflow.authoring import device, group, workflow",
        ]
        for namespace in sorted(namespaces):
            if namespace not in DEVICES:
                raise RuntimeError(
                    f"unknown PlatformUI action namespace in view: {namespace}"
                )
            _, class_name, _, filename = DEVICES[namespace]
            imports.append(
                f"from eit_ptlc.unilab_domain.devices.{filename.removesuffix('.py')} import {class_name}"
            )
        for child in child_names:
            imports.extend(
                [
                    f"from eit_ptlc.workflows.{child}_operation_view_v2 import (",
                    f"    {child}_operation_view_v2,",
                    ")",
                ]
            )
        imports.append("")
        imports.append("")
        for namespace in sorted(namespaces):
            registry_id, class_name, _, _ = DEVICES[namespace]
            imports.append(
                f"{_review_device_symbol(namespace)}: {class_name} = device({registry_id!r})"
            )
        imports.extend(
            [
                "",
                "",
                "@workflow(",
                f"    workflow_uuid={self.workflow_uuid!r},",
                f"    displayname={(str(document.get('label') or self.operation_name) + ' · Operation 分层视图 v2')!r},",
                "    description=(",
                "        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'",
                "        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'",
                "        '循环 body 不展开，也不会提交 PlatformUI operation。'",
                "    ),",
                ")",
                f"def {self.operation_name}_operation_view_v2() -> None:",
            ]
        )
        self.lines = imports
        from eit_ptlc.unilab_domain.operation_review import canonical_node_sha256

        self.projection_node_count += 1
        self.result_index += 1
        self._emit_metadata(
            4,
            f"OPERATION {self.operation_name}",
            "只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。",
        )
        self._emit_anchor(4, "operation-call", "operation-call", disabled=True)
        self.lines.extend(
            [
                f"    operation_call_{self.result_index:04d} = material.review_operation_call_v2(",
                f"        operation_name={self.operation_name!r},",
                f"        inputs_json={operation_inputs_json!r},",
                f"        expected_sha256={canonical_node_sha256(document)!r},",
                "    )",
            ]
        )
        for index, node in enumerate(document.get("body") or []):
            if not isinstance(node, dict):
                continue
            self._render_node(
                node=node,
                node_path=f"body/{index}",
                indent=4,
                expansion_path=f"body/{index}",
            )
        if self.projection_node_count == 0:
            self.lines.append("    pass")
        self.lines.append("")
        return "\n".join(self.lines)

    def _render_node(
        self,
        *,
        node: dict[str, Any],
        node_path: str,
        indent: int,
        expansion_path: str,
    ) -> None:
        kind = str(node.get("op") or "unknown")
        if kind == "call":
            self._render_call(node, node_path, indent, expansion_path)
            return
        if kind == "run_script":
            child = str(node.get("script") or "")
            if (self.operation_name, child) in self.cycle_edges:
                self.recursive_reference_count += 1
                self._render_marker(
                    node,
                    node_path,
                    indent,
                    expansion_path,
                    title=f"RECURSIVE SUBWORKFLOW REF {child}",
                )
                return
            self.projection_node_count += 1
            self.result_index += 1
            self._emit_metadata(
                indent,
                f"SUBWORKFLOW {child}",
                _review_description(self.operation_name, node_path, node),
            )
            # Composite declarations are coordinators, not physical jobs.  Keep
            # them enabled so the frontend can traverse the operation hierarchy;
            # their action/control leaves remain statically disabled.  Recursive
            # edges never reach this branch and stay disabled reference markers.
            self._emit_anchor(indent, "composite", expansion_path)
            self.lines.extend(
                [
                    indent * " "
                    + f"nested_operation_{self.result_index:04d} = {child}_operation_view_v2()",
                ]
            )
            return
        if kind in LOOP_REVIEW_OPS:
            self.loop_boundary_count += 1
            self._render_marker(
                node,
                node_path,
                indent,
                expansion_path,
                title=f"LOOP {kind} · BODY NOT EXPANDED",
            )
            return
        branches = _control_branches(node)
        if not branches:
            self._render_marker(node, node_path, indent, expansion_path)
            return
        self.group_node_count += 1
        self._emit_metadata(
            indent,
            f"CONTROL {kind}",
            _review_description(self.operation_name, node_path, node),
        )
        self._emit_anchor(indent, "group", expansion_path)
        self.lines.append(
            indent * " " + f"with group(name={_control_group_name(kind, node)!r}):"
        )
        self._render_marker(
            node,
            node_path,
            indent + 4,
            f"{expansion_path}/marker",
        )
        for label, children, branch_path in branches:
            self.group_node_count += 1
            self._emit_anchor(indent + 4, "group", f"{expansion_path}/{branch_path}")
            self.lines.append(
                (indent + 4) * " " + f"with group(name={label!r}):"
            )
            if not children:
                self._render_marker(
                    node,
                    node_path,
                    indent + 8,
                    f"{expansion_path}/{branch_path}/empty",
                    title=f"EMPTY {label}",
                )
            for index, child in enumerate(children):
                self._render_node(
                    node=child,
                    node_path=f"{node_path}/{branch_path}/{index}",
                    indent=indent + 8,
                    expansion_path=f"{expansion_path}/{branch_path}/{index}",
                )

    def _render_call(
        self,
        node: dict[str, Any],
        node_path: str,
        indent: int,
        expansion_path: str,
    ) -> None:
        action_name = str(node.get("action") or "")
        action = self.actions.get(action_name)
        if action is None:
            raise RuntimeError(f"unknown PlatformUI action in view: {action_name}")
        self.action_count += 1
        self.projection_node_count += 1
        self.result_index += 1
        namespace, suffix = action_name.split(".", 1)
        arguments = _review_action_arguments(action, node.get("args") or {})
        self._emit_metadata(
            indent,
            f"ACTION {action_name}",
            _review_description(self.operation_name, node_path, node),
        )
        self._emit_anchor(indent, "action", expansion_path, disabled=True)
        call = f"{_review_device_symbol(namespace)}.{_identifier(suffix)}"
        result_name = f"projected_action_{self.result_index:04d}"
        if not arguments:
            self.lines.append(indent * " " + f"{result_name} = {call}()")
            return
        self.lines.append(indent * " " + f"{result_name} = {call}(")
        for name, value in arguments:
            self.lines.append((indent + 4) * " " + f"{name}={value!r},")
        self.lines.append(indent * " " + ")")

    def _render_marker(
        self,
        node: dict[str, Any],
        node_path: str,
        indent: int,
        expansion_path: str,
        *,
        title: str | None = None,
    ) -> None:
        from eit_ptlc.unilab_domain.operation_review import canonical_node_sha256

        kind = str(node.get("op") or "unknown")
        self.projection_node_count += 1
        self.result_index += 1
        self._emit_metadata(
            indent,
            title or f"VERIFY {kind}",
            f"只读来源校验 {self.operation_name}@{node_path}；本视图中静态 disabled。",
        )
        self._emit_anchor(indent, "marker", expansion_path, disabled=True)
        self.lines.extend(
            [
                indent * " "
                + f"projected_control_{self.result_index:04d} = material.review_control_node_v1(",
                (indent + 4) * " " + f"operation_name={self.operation_name!r},",
                (indent + 4) * " " + f"node_path={node_path!r},",
                (indent + 4) * " " + f"control_kind={kind!r},",
                (indent + 4) * " "
                + f"expected_sha256={canonical_node_sha256(node)!r},",
                indent * " " + ")",
            ]
        )

    def _emit_metadata(self, indent: int, title: str, description: str) -> None:
        safe_title = " ".join(title.replace("]", ")").split())
        safe_description = " ".join(description.split())
        if len(safe_description) > 360:
            safe_description = safe_description[:357] + "..."
        self.lines.append(indent * " " + f"# [{safe_title}] {safe_description}")

    def _emit_anchor(
        self,
        indent: int,
        kind: str,
        expansion_path: str,
        *,
        disabled: bool = False,
    ) -> None:
        node_uuid = uuid.uuid5(self._workflow_namespace, f"{kind}:{expansion_path}")
        suffix = " disabled=true" if disabled else ""
        self.lines.append(indent * " " + f"# unilab:node_uuid={node_uuid}{suffix}")


def _write_operation_review_workflows(actions: dict[str, ActionDef]) -> None:
    """Generate twelve disabled action projections plus their audit manifest."""

    documents: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for path in OPERATIONS_DIR.rglob("*.yaml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        name = document.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name in documents:
            raise RuntimeError(f"duplicate PlatformUI operation: {name}")
        documents[name] = document
        paths[name] = path
    missing_roots = set(REVIEW_ROOTS) - set(documents)
    if missing_roots:
        raise RuntimeError(f"missing review roots: {sorted(missing_roots)}")

    union_operations: set[str] = set()
    root_rows: list[dict[str, Any]] = []
    expanded_control_counts: Counter[str] = Counter()
    expanded_action_total = 0
    for root_name in REVIEW_ROOTS:
        renderer = _ReviewWorkflowRenderer(
            root_name=root_name,
            documents=documents,
            actions=actions,
        )
        source = renderer.render()
        output_path = REVIEW_WORKFLOWS_DIR / f"{root_name}_action_review_v1.py"
        output_path.write_text(source, encoding="utf-8")
        union_operations.update(renderer.source_operation_names)
        expanded_action_total += renderer.action_count
        expanded_control_counts.update(renderer.control_counts)
        root_rows.append(
            {
                "root_operation": root_name,
                "workflow_uuid": renderer.workflow_uuid,
                "source": output_path.relative_to(ROOT).as_posix(),
                "root_resources": list(documents[root_name].get("resources") or []),
                "operation_count": len(renderer.source_operation_names),
                "display_operation_count": len(renderer.operation_names),
                "expanded_action_count": renderer.action_count,
                "expanded_control_counts": dict(
                    sorted(renderer.control_counts.items())
                ),
                "deduplicated_subworkflow_reference_count": renderer.deduplicated_subworkflow_reference_count,
                "bypassed_loop_count": renderer.bypassed_loop_count,
                "bypassed_loop_body_node_count": renderer.bypassed_loop_body_node_count,
                "bypassed_loop_body_action_count": renderer.bypassed_loop_body_action_count,
                "projection_node_count": renderer.projection_node_count,
            }
        )

    direct_action_count = 0
    unique_control_counts: Counter[str] = Counter()
    digest = hashlib.sha256()
    for operation_name in sorted(union_operations):
        path = paths[operation_name]
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
        for node in _direct_operation_nodes(
            documents[operation_name].get("body") or []
        ):
            kind = str(node.get("op") or "")
            if kind == "call":
                direct_action_count += 1
            elif kind != "run_script":
                unique_control_counts[kind] += 1

    manifest = {
        "schema": "unilab.platformui-operation-review/v1",
        "generated_from": "eit_ptlc/config/operation/**/*.yaml",
        "source_sha256": digest.hexdigest(),
        "semantics": {
            "projection_actions_disabled": True,
            "loop_projection": "marker_only_body_not_expanded",
            "repeated_subworkflow_projection": "first_definition_then_reference_marker",
            "enabled_execution_nodes_per_root": 1,
            "execution": "single_unchanged_platformui_root_operation",
            "resource_gate_authority": "eit_ptlc.operation.resources.ResourceGate",
            "control_flow_authority": "eit_ptlc.operation.vm.VmThread",
        },
        "root_count": len(REVIEW_ROOTS),
        "unique_operation_count": len(union_operations),
        "unique_source_action_call_count": direct_action_count,
        "unique_control_counts": dict(sorted(unique_control_counts.items())),
        "segment_expanded_action_count": expanded_action_total,
        "segment_expanded_control_counts": dict(
            sorted(expanded_control_counts.items())
        ),
        "roots": root_rows,
    }
    _dump_yaml(GENERATED_DIR / "platformui_operation_review.v1.yaml", manifest)


class _ReviewWorkflowRenderer:
    """Render one segment closure as disabled real-action nodes."""

    def __init__(
        self,
        *,
        root_name: str,
        documents: dict[str, dict[str, Any]],
        actions: dict[str, ActionDef],
    ) -> None:
        self.root_name = root_name
        self.documents = documents
        self.actions = actions
        self.workflow_uuid = str(
            uuid.uuid5(REVIEW_NAMESPACE, f"platformui-operation-review-v1:{root_name}")
        )
        self._workflow_namespace = uuid.UUID(self.workflow_uuid)
        self.lines: list[str] = []
        self.result_index = 0
        self.operation_names: set[str] = set()
        self.source_operation_names: set[str] = set()
        self.action_count = 0
        self.control_counts: Counter[str] = Counter()
        self.deduplicated_subworkflow_reference_count = 0
        self.bypassed_loop_count = 0
        self.bypassed_loop_body_node_count = 0
        self.bypassed_loop_body_action_count = 0
        self.projection_node_count = 0

    def render(self) -> str:
        namespaces = self._used_namespaces()
        root_document = self.documents[self.root_name]
        imports = [
            "from __future__ import annotations",
            "",
            "from typing import TypedDict",
            "",
            "from unilabos.workflow.authoring import device, group, parallel, workflow",
        ]
        for namespace in sorted(namespaces):
            _, class_name, _, filename = DEVICES[namespace]
            module = filename.removesuffix(".py")
            imports.append(
                f"from eit_ptlc.unilab_domain.devices.{module} import {class_name}"
            )
        imports.extend(
            [
                "",
                "",
                "class PlatformOperationReviewV1Result(TypedDict):",
                "    operation_name: str",
                "    command_id: str",
                "    run_id: str",
                "    status: str",
                "    result_json: str",
                "    before_path: str",
                "    collector_hole: int",
                "    bottle_hole: int",
                "",
            ]
        )
        for namespace in sorted(namespaces):
            registry_id, class_name, _, _ = DEVICES[namespace]
            imports.append(
                f"{_review_device_symbol(namespace)}: {class_name} = device({registry_id!r})"
            )
        imports.extend(
            [
                "",
                "",
                "@workflow(",
                f"    workflow_uuid={self.workflow_uuid!r},",
                f"    displayname={(str(root_document.get('label') or self.root_name) + ' · PlatformUI Action 审阅')!r},",
                "    description=(",
                "        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'",
                "        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'",
                "        'ResourceGate、条件、循环和 HITL 语义不变。'",
                "    ),",
                ")",
                f"def {self.root_name}_action_review_v1(",
                "    *, inputs_json: str = '{}', timeout_s: float = 3600.0",
                ") -> PlatformOperationReviewV1Result:",
                '    """Inspect every source node, then execute only the unchanged root operation."""',
            ]
        )
        self.lines = imports
        root_path = f"root:{self.root_name}"
        self._emit_metadata(
            4,
            f"审阅投影 {self.root_name}",
            "组内节点只用于查看来源，全部 disabled，不会向设备下发。",
        )
        self._emit_anchor(4, "group", root_path)
        self.lines.append(4 * " " + f"with group(name={'审阅投影（全部禁用）'!r}):")
        self._render_operation(
            operation_name=self.root_name,
            indent=8,
            expansion_path=root_path,
            stack=(),
        )
        execution_path = f"execute:{self.root_name}"
        self._emit_metadata(
            4,
            f"EXECUTE ROOT {self.root_name}",
            "本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。",
        )
        self._emit_anchor(4, "execute", execution_path, disabled=False)
        self.lines.extend(
            [
                4 * " " + "execution = material.run_operation_review_v1(",
                8 * " " + f"operation_name={self.root_name!r},",
                8 * " " + "inputs_json=inputs_json,",
                8 * " " + "timeout_s=timeout_s,",
                4 * " " + ")",
                4 * " " + "return {",
                8 * " " + '"operation_name": execution.operation_name,',
                8 * " " + '"command_id": execution.command_id,',
                8 * " " + '"run_id": execution.run_id,',
                8 * " " + '"status": execution.status,',
                8 * " " + '"result_json": execution.result_json,',
                8 * " " + '"before_path": execution.before_path,',
                8 * " " + '"collector_hole": execution.collector_hole,',
                8 * " " + '"bottle_hole": execution.bottle_hole,',
                4 * " " + "}",
                "",
            ]
        )
        return "\n".join(self.lines)

    def _used_namespaces(self) -> set[str]:
        namespaces = {"material"}
        visited: set[str] = set()

        def visit(operation_name: str) -> None:
            if operation_name in visited:
                return
            visited.add(operation_name)
            document = self.documents.get(operation_name)
            if document is None:
                raise RuntimeError(
                    f"unknown PlatformUI child operation: {operation_name}"
                )
            for node in _review_visible_operation_nodes(document.get("body") or []):
                if node.get("op") == "call":
                    action_name = str(node.get("action") or "")
                    if action_name not in self.actions:
                        raise RuntimeError(
                            f"unknown PlatformUI action in review: {action_name}"
                        )
                    namespaces.add(action_name.split(".", 1)[0])
                elif node.get("op") == "run_script":
                    visit(str(node.get("script") or ""))

        visit(self.root_name)
        self.source_operation_names = _operation_closure(
            root_name=self.root_name,
            documents=self.documents,
        )
        return namespaces

    def _render_operation(
        self,
        *,
        operation_name: str,
        indent: int,
        expansion_path: str,
        stack: tuple[str, ...],
    ) -> None:
        if operation_name in stack:
            raise RuntimeError(
                f"recursive PlatformUI operation is not reviewable: {stack + (operation_name,)}"
            )
        document = self.documents.get(operation_name)
        if document is None:
            raise RuntimeError(f"unknown PlatformUI operation: {operation_name}")
        self.operation_names.add(operation_name)
        for index, node in enumerate(document.get("body") or []):
            if not isinstance(node, dict):
                continue
            self._render_node(
                node=node,
                operation_name=operation_name,
                node_path=f"body/{index}",
                indent=indent,
                expansion_path=f"{expansion_path}/body/{index}",
                stack=stack + (operation_name,),
            )

    def _render_node(
        self,
        *,
        node: dict[str, Any],
        operation_name: str,
        node_path: str,
        indent: int,
        expansion_path: str,
        stack: tuple[str, ...],
    ) -> None:
        kind = str(node.get("op") or "unknown")
        if kind == "call":
            self._render_call(
                node=node,
                operation_name=operation_name,
                node_path=node_path,
                indent=indent,
                expansion_path=expansion_path,
            )
            return
        if kind == "run_script":
            child_name = str(node.get("script") or "")
            if child_name in self.operation_names:
                self.deduplicated_subworkflow_reference_count += 1
                self._render_marker(
                    node=node,
                    operation_name=operation_name,
                    node_path=node_path,
                    indent=indent,
                    expansion_path=f"{expansion_path}/subworkflow-reference",
                    title=f"SUBWORKFLOW REF {child_name} · DEFINITION ALREADY SHOWN",
                )
                return
            if indent >= MAX_REVIEW_GROUP_INDENT:
                self._render_marker(
                    node=node,
                    operation_name=operation_name,
                    node_path=node_path,
                    indent=indent,
                    expansion_path=f"{expansion_path}/flattened-run-script",
                    title=f"FLATTENED SUBWORKFLOW {child_name}",
                )
                self._render_operation(
                    operation_name=child_name,
                    indent=indent,
                    expansion_path=f"{expansion_path}/run:{child_name}",
                    stack=stack,
                )
                return
            self._emit_metadata(
                indent,
                f"SUBWORKFLOW {child_name}",
                f"由 {operation_name}@{node_path} 内联展开；其根资源仍由最外层 PlatformUI operation 持有。",
            )
            self._emit_anchor(indent, "group", expansion_path)
            self.lines.append(
                indent * " " + f"with group(name={('↳ ' + child_name)!r}):"
            )
            self._render_operation(
                operation_name=child_name,
                indent=indent + 4,
                expansion_path=f"{expansion_path}/run:{child_name}",
                stack=stack,
            )
            return
        self.control_counts[kind] += 1
        if kind in LOOP_REVIEW_OPS:
            loop_body_nodes = _direct_operation_nodes(node.get("body") or [])
            self.bypassed_loop_count += 1
            self.bypassed_loop_body_node_count += len(loop_body_nodes)
            self.bypassed_loop_body_action_count += sum(
                1 for child in loop_body_nodes if child.get("op") == "call"
            )
            self._render_marker(
                node=node,
                operation_name=operation_name,
                node_path=node_path,
                indent=indent,
                expansion_path=f"{expansion_path}/loop-boundary",
                title=f"LOOP {kind} · BODY NOT EXPANDED",
            )
            return
        if indent >= MAX_REVIEW_GROUP_INDENT:
            self._render_marker(
                node=node,
                operation_name=operation_name,
                node_path=node_path,
                indent=indent,
                expansion_path=f"{expansion_path}/flattened-control",
                title=f"FLATTENED CONTROL {kind}",
            )
            for _, child_nodes, child_path in _control_branches(node):
                for index, child in enumerate(child_nodes):
                    if not isinstance(child, dict):
                        continue
                    self._render_node(
                        node=child,
                        operation_name=operation_name,
                        node_path=f"{node_path}/{child_path}/{index}",
                        indent=indent,
                        expansion_path=f"{expansion_path}/{child_path}/{index}",
                        stack=stack,
                    )
            return
        self._emit_metadata(
            indent,
            f"CONTROL {kind}",
            _review_description(operation_name, node_path, node),
        )
        self._emit_anchor(indent, "group", expansion_path)
        self.lines.append(
            indent * " " + f"with group(name={_control_group_name(kind, node)!r}):"
        )
        self._render_marker(
            node=node,
            operation_name=operation_name,
            node_path=node_path,
            indent=indent + 4,
            expansion_path=f"{expansion_path}/marker",
        )
        for child_label, child_nodes, child_path in _control_branches(node):
            self._emit_metadata(
                indent + 4,
                f"BRANCH {child_label}",
                f"{operation_name}@{node_path}/{child_path} 的静态审阅分支。",
            )
            self._emit_anchor(indent + 4, "group", f"{expansion_path}/{child_path}")
            self.lines.append((indent + 4) * " " + f"with group(name={child_label!r}):")
            if not child_nodes:
                self._render_marker(
                    node=node,
                    operation_name=operation_name,
                    node_path=node_path,
                    indent=indent + 8,
                    expansion_path=f"{expansion_path}/{child_path}/empty",
                    title=f"EMPTY {child_label}",
                )
            for index, child in enumerate(child_nodes):
                if not isinstance(child, dict):
                    continue
                self._render_node(
                    node=child,
                    operation_name=operation_name,
                    node_path=f"{node_path}/{child_path}/{index}",
                    indent=indent + 8,
                    expansion_path=f"{expansion_path}/{child_path}/{index}",
                    stack=stack,
                )

    def _render_call(
        self,
        *,
        node: dict[str, Any],
        operation_name: str,
        node_path: str,
        indent: int,
        expansion_path: str,
    ) -> None:
        action_name = str(node.get("action") or "")
        action = self.actions.get(action_name)
        if action is None:
            raise RuntimeError(f"unknown PlatformUI action in review: {action_name}")
        self.action_count += 1
        self.projection_node_count += 1
        self.result_index += 1
        namespace, suffix = action_name.split(".", 1)
        arguments = _review_action_arguments(action, node.get("args") or {})
        self._emit_metadata(
            indent,
            f"ACTION {action_name}",
            _review_description(operation_name, node_path, node),
        )
        self._emit_anchor(indent, "action", expansion_path, disabled=True)
        call = f"{_review_device_symbol(namespace)}.{_identifier(suffix)}"
        result_name = f"projected_action_{self.result_index:04d}"
        if not arguments:
            self.lines.append(indent * " " + f"{result_name} = {call}()")
            return
        self.lines.append(indent * " " + f"{result_name} = {call}(")
        for name, value in arguments:
            self.lines.append((indent + 4) * " " + f"{name}={value!r},")
        self.lines.append(indent * " " + ")")

    def _render_marker(
        self,
        *,
        node: dict[str, Any],
        operation_name: str,
        node_path: str,
        indent: int,
        expansion_path: str,
        title: str | None = None,
    ) -> None:
        from eit_ptlc.unilab_domain.operation_review import canonical_node_sha256

        kind = str(node.get("op") or "unknown")
        self.projection_node_count += 1
        self.result_index += 1
        self._emit_metadata(
            indent,
            title or f"VERIFY {kind}",
            f"只读来源校验 {operation_name}@{node_path}；节点在本工作流中静态 disabled。",
        )
        self._emit_anchor(indent, "marker", expansion_path, disabled=True)
        self.lines.extend(
            [
                indent * " "
                + f"projected_control_{self.result_index:04d} = material.review_control_node_v1(",
                (indent + 4) * " " + f"operation_name={operation_name!r},",
                (indent + 4) * " " + f"node_path={node_path!r},",
                (indent + 4) * " " + f"control_kind={kind!r},",
                (indent + 4) * " "
                + f"expected_sha256={canonical_node_sha256(node)!r},",
                indent * " " + ")",
            ]
        )

    def _emit_metadata(self, indent: int, title: str, description: str) -> None:
        safe_title = " ".join(title.replace("]", ")").split())
        safe_description = " ".join(description.split())
        if len(safe_description) > 360:
            safe_description = safe_description[:357] + "..."
        self.lines.append(indent * " " + f"# [{safe_title}] {safe_description}")

    def _emit_anchor(
        self,
        indent: int,
        kind: str,
        expansion_path: str,
        *,
        disabled: bool = False,
    ) -> None:
        node_uuid = uuid.uuid5(
            self._workflow_namespace,
            f"{kind}:{expansion_path}",
        )
        suffix = " disabled=true" if disabled else ""
        self.lines.append(indent * " " + f"# unilab:node_uuid={node_uuid}{suffix}")


def _direct_operation_nodes(nodes: list[Any]) -> list[dict[str, Any]]:
    """Return every VM statement physically present in one operation document."""

    result: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        if isinstance(value.get("op"), str):
            result.append(value)
        for child in value.values():
            if isinstance(child, (list, dict)):
                visit(child)

    visit(nodes)
    return result


def _review_visible_operation_nodes(nodes: list[Any]) -> list[dict[str, Any]]:
    """Return review-visible VM statements while treating loops as boundaries."""

    result: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        kind = value.get("op")
        if isinstance(kind, str):
            result.append(value)
            if kind in LOOP_REVIEW_OPS:
                return
        for child in value.values():
            if isinstance(child, (list, dict)):
                visit(child)

    visit(nodes)
    return result


def _operation_closure(
    *, root_name: str, documents: dict[str, dict[str, Any]]
) -> set[str]:
    """Return the complete source closure, including operations called in loops."""

    visited: set[str] = set()

    def visit(operation_name: str) -> None:
        if operation_name in visited:
            return
        document = documents.get(operation_name)
        if document is None:
            raise RuntimeError(f"unknown PlatformUI child operation: {operation_name}")
        visited.add(operation_name)
        for node in _direct_operation_nodes(document.get("body") or []):
            if node.get("op") == "run_script":
                visit(str(node.get("script") or ""))

    visit(root_name)
    return visited


def _control_branches(
    node: dict[str, Any],
) -> list[tuple[str, list[dict[str, Any]], str]]:
    """Project VM control containers without pretending UniLab executes them."""

    kind = str(node.get("op") or "")
    branches: list[tuple[str, list[dict[str, Any]], str]] = []
    if kind == "if":
        branches.append(("THEN（互斥分支）", _node_list(node.get("then")), "then"))
        for index, clause in enumerate(node.get("elifs") or []):
            body = clause.get("body") if isinstance(clause, dict) else []
            branches.append(
                (
                    f"ELIF {index + 1}（互斥分支）",
                    _node_list(body),
                    f"elifs/{index}/body",
                )
            )
        branches.append(("ELSE（互斥分支）", _node_list(node.get("else")), "else"))
    elif kind == "try":
        branches.append(("TRY", _node_list(node.get("body")), "body"))
        for index, clause in enumerate(node.get("catch") or []):
            body = clause.get("body") if isinstance(clause, dict) else []
            branches.append(
                (f"CATCH {index + 1}", _node_list(body), f"catch/{index}/body")
            )
        if "finally" in node:
            branches.append(("FINALLY", _node_list(node.get("finally")), "finally"))
    elif kind == "parallel":
        for index, branch in enumerate(node.get("branches") or node.get("body") or []):
            body = (
                branch
                if isinstance(branch, list)
                else branch.get("body", [])
                if isinstance(branch, dict)
                else []
            )
            branches.append(
                (f"PARALLEL {index + 1}", _node_list(body), f"branches/{index}")
            )
    elif kind == "with_resources":
        branches.append(("BODY（结构展开一次）", _node_list(node.get("body")), "body"))
    else:
        nested = []
        for key, value in node.items():
            if key == "op":
                continue
            candidates = _node_list(value)
            if any(
                isinstance(item, dict) and isinstance(item.get("op"), str)
                for item in candidates
            ):
                nested.extend(candidates)
        if nested:
            branches.append(("NESTED", nested, "nested"))
    return branches


def _node_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, dict) and isinstance(item.get("op"), str)
    ]


def _control_group_name(kind: str, node: dict[str, Any]) -> str:
    labels = {
        "if": "◇ IF 条件（PlatformUI 判定）",
        "for": "↻ FOR 循环（仅显示边界）",
        "while": "↻ WHILE 循环（仅显示边界）",
        "repeat": "↻ REPEAT 循环（仅显示边界）",
        "try": "TRY / CATCH（PlatformUI 异常语义）",
        "human": "◆ HITL 人工门",
        "with_resources": "🔒 局部 ResourceGate",
        "assign": "变量赋值",
        "raise": "抛出流程错误",
        "comment": "说明",
        "parallel": "并行分支（PlatformUI VM）",
    }
    label = labels.get(kind, f"CONTROL {kind}")
    if kind == "comment":
        text = " ".join(str(node.get("text") or "").split())
        if text:
            label = f"说明 · {text[:56]}"
    if kind == "with_resources":
        resources = ", ".join(str(item) for item in node.get("resources") or [])
        label = f"🔒 局部 ResourceGate · {resources}"
    return label


def _review_description(
    operation_name: str, node_path: str, node: dict[str, Any]
) -> str:
    payload = json.dumps(
        node, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"来源 {operation_name}@{node_path}；原节点 {payload}"


def _review_device_symbol(namespace: str) -> str:
    return {
        "sampling": "sampling",
        "develop": "develop",
        "collect": "collect",
        "photoscrape": "photoscrape",
        "feedlift": "feedlift",
        "rail": "rail",
        "robot": "robot",
        "pump": "pump",
        "vision": "vision",
        "staging_a": "staging_a",
        "material": "material",
    }[namespace]


def _review_action_arguments(
    action: ActionDef,
    original_args: dict[str, Any],
) -> list[tuple[str, Any]]:
    arguments: list[tuple[str, Any]] = []
    for param in action.params:
        if not param.required:
            continue
        expression = original_args.get(param.name)
        value = _literal_for_review(expression, param.type)
        if value is None:
            value = _review_placeholder(param.type, param)
        arguments.append((_identifier(param.name), value))
    for field in action.fields:
        type_name = FIELD_TYPES[(action.name, field.key)]
        expression = original_args.get(field.key)
        value = _literal_for_review(expression, type_name)
        if value is None:
            value = _review_placeholder(type_name, None)
        arguments.append((_identifier(field.key), value))
    return arguments


def _literal_for_review(expression: Any, type_name: str) -> Any | None:
    if not isinstance(expression, dict) or set(expression) != {"lit"}:
        return None
    value = expression["lit"]
    if type_name == "bool" and isinstance(value, bool):
        return value
    if type_name == "int" and isinstance(value, int) and not isinstance(value, bool):
        return value
    if (
        type_name == "float"
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        return float(value)
    if type_name in {"string", "enum", "point_ref"} and isinstance(value, str):
        return value
    if type_name == "list[float]" and isinstance(value, list):
        return [float(item) for item in value]
    return None


def _review_placeholder(type_name: str, param: Any | None) -> Any:
    if param is not None and param.default is not None:
        return param.default
    if type_name == "bool":
        return False
    if type_name == "int":
        if param is not None and param.options:
            return int(param.options[0].value)
        if param is not None and param.minimum is not None:
            return int(param.minimum)
        return 1
    if type_name == "float":
        if param is not None and param.minimum is not None:
            return float(param.minimum)
        return 0.0
    if type_name == "enum":
        if param is not None and param.options:
            return str(param.options[0].value)
        return "review-only"
    if type_name in {"string", "point_ref"}:
        return "review-only"
    if type_name == "list[float]":
        return [0.0]
    raise RuntimeError(f"unsupported review placeholder type: {type_name}")


def _type_name(value: str) -> str:
    return {
        "int": "int",
        "float": "float",
        "bool": "bool",
        "string": "str",
        "enum": "str",
        "point_ref": "str",
    }[value]


def _identifier(value: str) -> str:
    result = re.sub(r"\W", "_", value)
    if not result or result[0].isdigit() or keyword.iskeyword(result):
        result = f"action_{result}"
    return result


def _dump_yaml(path: Path, value: Any) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
