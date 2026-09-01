#!/usr/bin/env python3
"""Export the UniLab longest-flow views from PlatformUI YAML sources.

The PlatformUI recipe owns segment names and DAG dependencies.  PlatformUI
operation YAML owns operation names and typed parameters.  The checked-in
templates contain only UniLab-specific material/transport projection code;
the generated ``eit_ptlc/workflows/*.py`` files are overwrite-only artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
RECIPE_PATH = ROOT / "eit_ptlc" / "config" / "recipes" / "parallel_v1.yaml"
MATERIAL_CONTRACT_PATH = (
    ROOT / "eit_ptlc" / "config" / "recipes" / "parallel_v1.materials.yaml"
)
OPERATIONS_DIR = ROOT / "eit_ptlc" / "config" / "operation"
WORKFLOWS_DIR = ROOT / "eit_ptlc" / "workflows"
GENERATED_DIR = ROOT / "eit_ptlc" / "unilab_domain" / "generated"
TEMPLATES_DIR = ROOT / "eit_ptlc" / "unilab_domain" / "templates"
PACKAGE_PATH = ROOT / "package.yaml"
LEGACY_PACKAGE_PATH = ROOT / "package.legacy.yaml"
OPERATION_VIEW_MANIFEST_PATH = (
    GENERATED_DIR / "platformui_operation_views.v2.yaml"
)
OPERATION_REVIEW_MANIFEST_PATH = (
    GENERATED_DIR / "platformui_operation_review.v1.yaml"
)

TYPED_TEMPLATE = TEMPLATES_DIR / "ptlc_parallel_v4.py.tmpl"
REVIEW_TEMPLATE = TEMPLATES_DIR / "ptlc_parallel_operation_review_v1.py.tmpl"

TYPED_UUID = "1a424e61-d0fe-5489-86ae-11ca393d21b8"
GENERIC_UUID = "c76bb7fd-add3-58b7-b950-bdf494c9af80"
REVIEW_UUID = "b2a6a5ef-07e9-5d3e-9695-f0ac1f26700f"
MATERIAL_SEGMENTS_UUID = "62a2f155-1b29-5ac2-b8bf-463656c98621"
MATERIAL_SEGMENT_NAMESPACE = uuid.UUID("8f49c8d6-a6d7-54fa-a8b3-e10a12e80557")
OPERATION_VIEW_NAMESPACE = uuid.UUID("e68b8d04-3e38-5cd2-a9cc-dd49385503af")
RUNTIME_SEGMENT_NAMESPACE = uuid.UUID("8f47b967-fe71-5262-9190-085812743faf")
HIERARCHICAL_SEGMENTS_UUID = "6b2cc909-7fbc-56b0-88ac-0e98f279a7ea"
TRANSPORT_UUID = "75067f83-c472-51de-8dc5-e99fdc655df6"

EXPECTED_RECIPE_DAG = (
    ("af0", "pf_af0_batch_startup", ()),
    ("s1", "pf_s1_load", ("af0",)),
    ("s2", "pf_s2_spot", ("s1",)),
    ("s3", "pf_s3_tank_prep", ("s1",)),
    ("s4", "pf_s4_photo_before", ("s2",)),
    ("s5", "pf_s5_to_tank", ("s4", "s3")),
    ("s6", "pf_s6_develop_wait", ("s5",)),
    ("s7", "pf_s7_consumables", ("s5",)),
    ("s8", "pf_s8_to_scrape", ("s6",)),
    ("s9", "pf_s9_scrape", ("s8", "s7")),
    ("s10", "pf_s10_collect", ("s9",)),
    ("s11", "pf_s11_unload", ("s10",)),
)

TYPED_OPERATION_OWNERS = {
    "sampling_prepare": "sampling",
    "sampling_execute": "sampling",
    "develop_prepare": "develop",
    "pf_s6_develop_wait": "develop",
    "photoscrape_before_photo_capture": "photoscrape",
    "photoscrape_process": "photoscrape",
    "collect_execute": "collect",
}

SEGMENT_INPUT_DEFAULTS = {
    "af0": "{}",
    "s1": "{}",
    "s2": "{}",
    "s3": '{"tank":1}',
    "s4": '{"sample_id":"DEMO-001","save_dir":"var/photoscrape/demo"}',
    "s5": '{"tank":1}',
    "s6": '{"tank":1,"auto_drain":true}',
    "s7": '{"reserve_for":"DEMO-001"}',
    "s8": '{"tank":1}',
    "s9": '{"sample_id":"DEMO-001","save_dir":"var/photoscrape/demo","before_path":"var/photoscrape/demo/before.jpg","mode":"auto"}',
    "s10": '{"collector_hole":1,"bottle_hole":1}',
    "s11": "{}",
}

MATERIAL_SOURCE_SPECS = {
    "sample_vial": (
        "source_sample_vial",
        "plc_sampling",
        "MaterialFlowRole.PRIMARY_SAMPLE",
    ),
    "plate": ("ptlc_plate", "plc_feedlift", "MaterialFlowRole.ALIQUOT_SAMPLE"),
    "collector": (
        "powder_collector",
        "staging_a_stack",
        "MaterialFlowRole.CONSUMABLE",
    ),
    "vial": (
        "collection_vial",
        "staging_b_stack",
        "MaterialFlowRole.CONSUMABLE",
    ),
}

OPERATION_DATA_TYPES = {"STRING": "str", "INT": "int"}
OPERATION_DATA_DEFAULTS = {"STRING": "", "INT": 0}

GENERATED_HEADER = """# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
"""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise RuntimeError(f"expected YAML object: {path}")
    return value


def _validate_recipe() -> dict[str, Any]:
    recipe = _load_yaml(RECIPE_PATH)
    actual = tuple(
        (
            str(item.get("id") or ""),
            str(item.get("script") or ""),
            tuple(str(value) for value in item.get("depends_on") or []),
        )
        for item in recipe.get("flows") or []
        if isinstance(item, dict)
    )
    if actual != EXPECTED_RECIPE_DAG:
        raise RuntimeError(
            "parallel_v1 DAG no longer matches the representable UniLab longest-flow "
            f"projection; expected={EXPECTED_RECIPE_DAG!r}, actual={actual!r}"
        )
    return recipe


def _load_operation_documents() -> dict[str, dict[str, Any]]:
    wanted = set(TYPED_OPERATION_OWNERS)
    found: dict[str, dict[str, Any]] = {}
    for path in OPERATIONS_DIR.rglob("*.yaml"):
        document = _load_yaml(path)
        name = document.get("name")
        if name not in wanted:
            continue
        if name in found:
            raise RuntimeError(f"duplicate PlatformUI operation: {name}")
        found[str(name)] = document
    missing = wanted - set(found)
    if missing:
        raise RuntimeError(f"missing PlatformUI station operations: {sorted(missing)}")
    return found


def _load_segment_operation_documents() -> dict[str, dict[str, Any]]:
    wanted = {item[1] for item in EXPECTED_RECIPE_DAG}
    found: dict[str, dict[str, Any]] = {}
    for path in OPERATIONS_DIR.rglob("*.yaml"):
        document = _load_yaml(path)
        name = str(document.get("name") or "")
        if name not in wanted:
            continue
        if name in found:
            raise RuntimeError(f"duplicate PlatformUI segment operation: {name}")
        found[name] = document
    missing = wanted - set(found)
    if missing:
        raise RuntimeError(f"missing PlatformUI segment operations: {sorted(missing)}")
    return found


def _validate_material_contract() -> dict[str, Any]:
    contract = _load_yaml(MATERIAL_CONTRACT_PATH)
    if contract.get("schema") != "ptlc.unilab-material-contract/v1":
        raise RuntimeError("parallel_v1 material contract schema drifted")
    if contract.get("recipe") != "parallel_v1":
        raise RuntimeError("parallel_v1 material contract names another recipe")
    portable = contract.get("portable_materials") or {}
    if portable != {
        name: f"ptlc_{'source_sample_vial' if name == 'sample_vial' else 'powder_collector' if name == 'collector' else 'collection_vial' if name == 'vial' else 'plate'}"
        for name in MATERIAL_SOURCE_SPECS
    }:
        raise RuntimeError("parallel_v1 portable material catalog drifted")
    rows = contract.get("segments") or []
    actual = tuple(
        (str(row.get("id") or ""), str(row.get("operation") or ""))
        for row in rows
        if isinstance(row, dict)
    )
    expected = tuple((item[0], item[1]) for item in EXPECTED_RECIPE_DAG)
    if actual != expected:
        raise RuntimeError(
            "parallel_v1 material segments must match recipe order; "
            f"expected={expected!r}, actual={actual!r}"
        )
    for row in rows:
        inputs = tuple(str(value) for value in row.get("portable_inputs") or [])
        outputs = tuple(str(value) for value in row.get("portable_outputs") or [])
        unknown = (set(inputs) | set(outputs)) - set(MATERIAL_SOURCE_SPECS)
        if unknown:
            raise RuntimeError(
                f"unknown portable material in {row['id']}: {sorted(unknown)}"
            )
        if set(inputs) != set(outputs):
            raise RuntimeError(
                f"segment {row['id']} must preserve each portable material identity"
            )
        commits = row.get("commits") or {}
        if set(commits) - set(outputs):
            raise RuntimeError(f"segment {row['id']} commits a non-output material")
        if row.get("lineage") not in {None, "spotting", "scraping", "collection"}:
            raise RuntimeError(f"segment {row['id']} has unknown lineage projection")
        for section in ("operation_outputs", "bind_inputs"):
            values = row.get(section) or {}
            if not isinstance(values, dict) or set(values.values()) - set(
                OPERATION_DATA_TYPES
            ):
                raise RuntimeError(
                    f"segment {row['id']} has invalid {section} declaration"
                )
    return contract


def _class_name(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in value.split("_"))


def _material_segment_uuid(operation_name: str) -> str:
    return str(uuid.uuid5(MATERIAL_SEGMENT_NAMESPACE, operation_name))


def operation_view_uuid(operation_name: str) -> str:
    return str(uuid.uuid5(OPERATION_VIEW_NAMESPACE, operation_name))


def _runtime_segment_uuid(operation_name: str) -> str:
    return str(uuid.uuid5(RUNTIME_SEGMENT_NAMESPACE, operation_name))


def _material_node_uuid(workflow_uuid: str, key: str) -> str:
    return str(uuid.uuid5(uuid.UUID(workflow_uuid), key))


def _material_segment_filename(operation_name: str) -> str:
    return f"{operation_name}_material_v1.py"


def _material_segment_symbol(operation_name: str) -> str:
    return f"{operation_name}_material_v1"


def _runtime_segment_symbol(operation_name: str) -> str:
    return f"{operation_name}_runtime_v2"


def _with_header(source: str) -> str:
    return GENERATED_HEADER + source.lstrip()


def _replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"workflow template drift: expected one block, found {count}: {old[:80]!r}"
        )
    return source.replace(old, new)


def _generic_node_uuid(old_value: str) -> str:
    return str(uuid.uuid5(uuid.UUID(GENERIC_UUID), old_value))


def _render_generic_variant(typed_template: str) -> str:
    source = typed_template
    source = _replace_once(source, TYPED_UUID, GENERIC_UUID)
    source = _replace_once(
        source, "def ptlc_parallel_v4(", "def ptlc_parallel_station_operation_v1("
    )
    source = _replace_once(
        source,
        'displayname="pTLC 最长全流程 v4（物料 + 最大并行）",',
        'displayname="pTLC 最长全流程 · 统一 run_station_operation Action 版",',
    )
    source = _replace_once(
        source,
        '        "原样调用 PlatformUI 的成熟工位 operation；所有机器人、地轨、工具与物料转移"\n'
        '        "只进入通用转运 v4。依赖图精确保持 parallel_v1：s2∥s3、(s6→s8)∥s7，"\n'
        '        "且 s7 的共同前驱为 s5。"',
        '        "所有工位 operation 都通过统一 run_station_operation_v4 Action 提交；"\n'
        '        "机器人、地轨、工具与物料转移仍只进入通用转运 v4。依赖图保持"\n'
        '        "parallel_v1：s2∥s3、(s6→s8)∥s7，且 s7 的共同前驱为 s5。"',
    )

    typed_inputs = """    sample_id: str = "DEMO-001",
    plate_spec: str = "4×6",
    plate_no: str = "1",
    well: str = "A1",
    tank: int = 1,
    auto_drain: bool = True,
    dry_duration_s: float = 0.0,
    save_dir: str = "var/photoscrape/demo",
    before_path: str = "var/photoscrape/demo/before.jpg",
    photoscrape_mode: str = "auto",
    solvent_volume_ml: float = 0.1,
    liquid_repeat_count: int = 1,"""
    generic_inputs = """    sample_id: str = "DEMO-001",
    sampling_prepare_inputs_json: str = "{}",
    sampling_execute_inputs_json: str = '{"plate_spec":"4×6","plate_no":"1","well":"A1"}',
    develop_prepare_inputs_json: str = '{"tank":1}',
    develop_wait_inputs_json: str = '{"tank":1,"auto_drain":true,"dry_duration_s":0.0}',
    before_photo_inputs_json: str = '{"sample_id":"DEMO-001","save_dir":"var/photoscrape/demo"}',
    photoscrape_inputs_json: str = '{"sample_id":"DEMO-001","save_dir":"var/photoscrape/demo","before_path":"var/photoscrape/demo/before.jpg","mode":"auto"}',
    collect_execute_inputs_json: str = '{"solvent_volume_ml":0.1,"liquid_repeat_count":1}', """.rstrip()
    source = _replace_once(source, typed_inputs, generic_inputs)

    replacements = (
        (
            """sampling.sampling_prepare()  # noqa: F841""",
            """sampling.run_station_operation_v4(  # noqa: F841
            operation_name="sampling_prepare",
            inputs_json=sampling_prepare_inputs_json,
        )""",
        ),
        (
            """sampling.sampling_execute(  # noqa: F841
                plate_spec=plate_spec,
                plate_no=plate_no,
                well=well,
            )""",
            """sampling.run_station_operation_v4(  # noqa: F841
                operation_name="sampling_execute",
                inputs_json=sampling_execute_inputs_json,
            )""",
        ),
        (
            """photoscrape.photoscrape_before_photo_capture(  # noqa: F841
                sample_id=sample_id,
                save_dir=save_dir,
            )""",
            """photoscrape.run_station_operation_v4(  # noqa: F841
                operation_name="photoscrape_before_photo_capture",
                inputs_json=before_photo_inputs_json,
            )""",
        ),
        (
            """develop.develop_prepare(  # noqa: F841
                tank=tank,
            )""",
            """develop.run_station_operation_v4(  # noqa: F841
                operation_name="develop_prepare",
                inputs_json=develop_prepare_inputs_json,
            )""",
        ),
        (
            """develop.pf_s6_develop_wait(  # noqa: F841
                tank=tank,
                auto_drain=auto_drain,
                dry_duration_s=dry_duration_s,
            )""",
            """develop.run_station_operation_v4(  # noqa: F841
                operation_name="pf_s6_develop_wait",
                inputs_json=develop_wait_inputs_json,
            )""",
        ),
        (
            """photoscrape.photoscrape_process(  # noqa: F841
            sample_id=sample_id,
            save_dir=save_dir,
            before_path=before_path,
            mode=photoscrape_mode,
        )""",
            """photoscrape.run_station_operation_v4(  # noqa: F841
            operation_name="photoscrape_process",
            inputs_json=photoscrape_inputs_json,
        )""",
        ),
        (
            """collect.collect_execute(  # noqa: F841
            solvent_volume_ml=solvent_volume_ml,
            liquid_repeat_count=liquid_repeat_count,
        )""",
            """collect.run_station_operation_v4(  # noqa: F841
            operation_name="collect_execute",
            inputs_json=collect_execute_inputs_json,
        )""",
        ),
    )
    for old, new in replacements:
        source = _replace_once(source, old, new)
    source = re.sub(
        r"(?m)(# unilab:node_uuid=)([0-9a-f-]{36})",
        lambda match: match.group(1) + _generic_node_uuid(match.group(2)),
        source,
    )
    return source


def _render_material_segment(
    row: dict[str, Any],
    operation_document: dict[str, Any],
    *,
    runtime_v2: bool = False,
) -> str:
    operation_name = str(row["operation"])
    workflow_uuid = (
        _runtime_segment_uuid(operation_name)
        if runtime_v2
        else _material_segment_uuid(operation_name)
    )
    symbol = (
        _runtime_segment_symbol(operation_name)
        if runtime_v2
        else _material_segment_symbol(operation_name)
    )
    result_class = f"{_class_name(symbol)}Result"
    inputs = [str(value) for value in row.get("portable_inputs") or []]
    outputs = [str(value) for value in row.get("portable_outputs") or []]
    commits = row.get("commits") or {}
    lineage = row.get("lineage")
    operation_outputs = dict(row.get("operation_outputs") or {})
    bind_inputs = dict(row.get("bind_inputs") or {})
    # Both executable projections submit the unchanged PlatformUI root through
    # one stable UniLab action.  The large ``*_action_review_v1`` composites
    # belong only to the dedicated source-audit canvas; nesting them here makes
    # the runtime boundary ambiguous and needlessly expands the execution DAG.
    needs_material_device = True
    site_parameters = sorted(
        {
            str(spec["site_parameter"])
            for spec in commits.values()
            if isinstance(spec, dict) and spec.get("site_parameter")
        }
    )
    site_defaults = {
        "tank_site": "tank-1",
        "collector_site": "collector-item-1",
        "bottle_site": "bottle-item-1",
    }

    imports = [
        "from __future__ import annotations",
        "",
        "from typing import TypedDict",
    ]
    if inputs:
        imports.extend(
            ["", "from unilabos.registry.placeholder_type import ResourceSlot"]
        )
    if commits:
        imports.extend(
            [
                "from unilabos.ros.nodes.presets.host_node import HostNode",
                "from unilabos.workflow.authoring import device, resource_ref, workflow",
            ]
        )
    elif needs_material_device:
        imports.append("from unilabos.workflow.authoring import device, workflow")
    else:
        imports.append("from unilabos.workflow.authoring import workflow")
    if needs_material_device:
        imports.extend(
            [
                "",
                "from eit_ptlc.unilab_domain.devices.material import MaterialProxy",
            ]
        )
    if runtime_v2:
        imported_workflow = f"{operation_name}_operation_view_v2"
        imports.extend(
            [
                f"from eit_ptlc.workflows.{imported_workflow} import (",
                f"    {imported_workflow},",
                ")",
            ]
        )
    imports.extend(
        [
            "",
            "",
            f"class {result_class}(TypedDict):",
            "    operation_name: str",
            "    command_id: str",
            "    run_id: str",
            "    status: str",
            "    result_json: str",
        ]
    )
    for material_name in outputs:
        imports.append(f"    {material_name}: ResourceSlot")
    for output_name, output_type in operation_outputs.items():
        imports.append(f"    {output_name}: {OPERATION_DATA_TYPES[str(output_type)]}")
    if needs_material_device:
        imports.extend(["", "", 'material: MaterialProxy = device("material")'])
    if commits:
        imports.extend(["", "", 'host_node: HostNode = device("host_node")'])

    station_materials = [
        str(item.get("name") or "")
        for item in row.get("station_materials") or []
        if isinstance(item, dict)
    ]
    label = str(operation_document.get("label") or operation_name)
    if runtime_v2:
        description = (
            f"分层展示并执行原始 PlatformUI operation {operation_name}；可搬运物料输入/输出="
            f"{inputs or ['无']}，工位自管物料={station_materials or ['无']}。"
            "只读结构节点全部禁用；唯一执行节点提交一次原根 operation。"
            "成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。"
        )
        display_suffix = " · 分层运行 v2"
    else:
        description = (
            f"执行原始 PlatformUI operation {operation_name}；可搬运物料输入/输出="
            f"{inputs or ['无']}，工位自管物料={station_materials or ['无']}。"
            "根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。"
        )
        display_suffix = " · 物料合同"
    lines = imports + [
        "",
        "",
        "@workflow(",
        f"    workflow_uuid={workflow_uuid!r},",
        f"    displayname={(label + display_suffix)!r},",
        f"    description={description!r},",
        ")",
        f"def {symbol}(",
        "    *,",
    ]
    for material_name in inputs:
        lines.append(f"    {material_name}: ResourceSlot,")
    lines.extend(
        [
            "    inputs_json: str = '{}',",
            "    timeout_s: float = 3600.0,",
        ]
    )
    for parameter in site_parameters:
        lines.append(f"    {parameter}: str = {site_defaults[parameter]!r},")
    for parameter, parameter_type in bind_inputs.items():
        default = OPERATION_DATA_DEFAULTS[str(parameter_type)]
        lines.append(
            f"    {parameter}: {OPERATION_DATA_TYPES[str(parameter_type)]} = {default!r},"
        )
    execution_inputs = "inputs_json"
    if bind_inputs:
        lines.extend(
            [
                f") -> {result_class}:",
                f"    # unilab:node_uuid={_material_node_uuid(workflow_uuid, 'bind-inputs')}",
                "    bound = material.bind_parallel_operation_inputs_v1(",
                "        inputs_json=inputs_json,",
            ]
        )
        for parameter in bind_inputs:
            lines.append(f"        {parameter}={parameter},")
        lines.append("    )")
        execution_inputs = "bound.inputs_json"
    else:
        lines.append(f") -> {result_class}:")
    if runtime_v2:
        lines.extend(
            [
                # Keep the composite invocation visible/enabled so the frontend can
                # traverse into its child workflow.  Every executable/control node
                # inside *_operation_view_v2 remains statically disabled, so this
                # coordinator contributes no physical job to the execution plan.
                f"    # unilab:node_uuid={_material_node_uuid(workflow_uuid, 'display-view')}",
                f"    structure = {operation_name}_operation_view_v2()",
                f"    # unilab:node_uuid={_material_node_uuid(workflow_uuid, 'execute-root')}",
                "    execution = material.run_operation_review_v1(",
                f"        operation_name={operation_name!r},",
                f"        inputs_json={execution_inputs},",
                "        timeout_s=timeout_s,",
                "    )",
            ]
        )
    else:
        lines.extend(
            [
                f"    # unilab:node_uuid={_material_node_uuid(workflow_uuid, 'execute-root')}",
                "    execution = material.run_operation_review_v1(",
                f"        operation_name={operation_name!r},",
                f"        inputs_json={execution_inputs},",
                "        timeout_s=timeout_s,",
                "    )",
            ]
        )

    material_values = {name: name for name in outputs}
    if lineage == "spotting":
        lines.extend(
            [
                f"    # unilab:node_uuid={_material_node_uuid(workflow_uuid, 'lineage-spotting')}",
                "    linked = material.record_spotting_v4(",
                "        sample_vial=sample_vial,",
                "        plate=plate,",
                "    )",
            ]
        )
        material_values.update(
            {"sample_vial": "linked.sample_vial", "plate": "linked.plate"}
        )
    elif lineage == "scraping":
        lines.extend(
            [
                f"    # unilab:node_uuid={_material_node_uuid(workflow_uuid, 'lineage-scraping')}",
                "    linked = material.record_scraping_v4(",
                "        plate=plate,",
                "        powder_collector=collector,",
                "    )",
            ]
        )
        material_values.update(
            {"plate": "linked.plate", "collector": "linked.powder_collector"}
        )
    elif lineage == "collection":
        lines.extend(
            [
                f"    # unilab:node_uuid={_material_node_uuid(workflow_uuid, 'lineage-collection')}",
                "    linked = material.record_collection_v4(",
                "        powder_collector=collector,",
                "        vial=vial,",
                "    )",
            ]
        )
        material_values.update(
            {"collector": "linked.powder_collector", "vial": "linked.vial"}
        )

    for material_name, spec in commits.items():
        site_value = (
            str(spec["site_parameter"])
            if spec.get("site_parameter")
            else repr(str(spec["site"]))
        )
        commit_symbol = f"committed_{material_name}"
        lines.extend(
            [
                f"    # unilab:node_uuid={_material_node_uuid(workflow_uuid, f'commit-{material_name}')}",
                f"    {commit_symbol} = host_node.transfer_resource(",
                f"        resource={material_values[material_name]},",
                f"        target_device={str(spec['target_device'])!r},",
                f"        mount_resource=resource_ref({str(spec['mount'])!r}),",
                f"        site={site_value},",
                "    )",
            ]
        )
        material_values[material_name] = f"{commit_symbol}.resource"

    lines.extend(
        [
            "    return {",
            '        "operation_name": execution.operation_name,',
            '        "command_id": execution.command_id,',
            '        "run_id": execution.run_id,',
            '        "status": execution.status,',
            '        "result_json": execution.result_json,',
        ]
    )
    for material_name in outputs:
        lines.append(f'        {material_name!r}: {material_values[material_name]},')
    for output_name in operation_outputs:
        lines.append(f'        {output_name!r}: execution.{output_name},')
    lines.extend(["    }", ""])
    return "\n".join(lines)


def _render_material_segments_parent(
    recipe: dict[str, Any],
    contract: dict[str, Any],
    *,
    hierarchical_v2: bool = False,
) -> str:
    rows = {str(row["id"]): row for row in contract["segments"]}
    parent_uuid = (
        HIERARCHICAL_SEGMENTS_UUID if hierarchical_v2 else MATERIAL_SEGMENTS_UUID
    )
    segment_symbol = (
        _runtime_segment_symbol if hierarchical_v2 else _material_segment_symbol
    )
    result_class = (
        "PTLCParallelSegmentsV2Result"
        if hierarchical_v2
        else "PTLCParallelSegmentsV1Result"
    )
    function_name = (
        "ptlc_parallel_segments_v2"
        if hierarchical_v2
        else "ptlc_parallel_segments_v1"
    )
    authoring_imports = (
        [
            "    MaterialFlowRole,",
            "    group,",
            "    material_source,",
            "    parallel,",
            "    resource_ref,",
            "    workflow,",
        ]
        if not hierarchical_v2
        else ["    group,", "    parallel,", "    workflow,"]
    )
    imports = [
        "from __future__ import annotations",
        "",
        "from typing import TypedDict",
        "",
        "from unilabos.registry.placeholder_type import ResourceSlot",
        "from unilabos.workflow.authoring import (",
        *authoring_imports,
        ")",
    ]
    if not hierarchical_v2:
        imports.extend(
            [
                "",
                "from eit_ptlc.unilab_domain.resources.materials import (",
                "    collection_vial,",
                "    powder_collector,",
                "    ptlc_plate,",
                "    source_sample_vial,",
                ")",
            ]
        )
    for _, operation_name, _ in EXPECTED_RECIPE_DAG:
        symbol = segment_symbol(operation_name)
        imports.extend(
            [
                f"from eit_ptlc.workflows.{symbol} import (",
                f"    {symbol},",
                ")",
            ]
        )
    imports.extend(
        [
            "",
            "",
            f"class {result_class}(TypedDict):",
            "    sample: ResourceSlot",
            "    waste_plate: ResourceSlot",
            "    powder_collector: ResourceSlot",
            "",
            "",
            "@workflow(",
            f"    workflow_uuid={parent_uuid!r},",
            f"    displayname={(('并行全流程 v2（分层展示 + 原子运行，12 段）' if hierarchical_v2 else str(recipe.get('label') or '并行全流程 v1 (12 段, 四段式对齐)')))!r},",
            "    description=(",
            "        '由 PlatformUI parallel_v1 和 12 段物料合同自动导出。每段是可展开子工作流，'",
            (
                "        '输入物料由显式 ResourceSlot 绑定；先分层展示 operation 结构，再由唯一根节点执行；'\n"
                "        's2∥s3、(s6→s8)∥s7，且 s7 严格在 s5 后开始。'"
                if hierarchical_v2
                else "        '内部只执行一次原根 operation；s2∥s3、(s6→s8)∥s7，且 s7 严格在 s5 后开始。'"
            ),
            "    ),",
            ")",
            f"def {function_name}(",
            "    *,",
        ]
    )
    if hierarchical_v2:
        imports.extend(
            [
                "    sample_vial: ResourceSlot,",
                "    plate: ResourceSlot,",
                "    collector: ResourceSlot,",
                "    vial: ResourceSlot,",
            ]
        )
    for segment_id, _, _ in EXPECTED_RECIPE_DAG:
        default_json = SEGMENT_INPUT_DEFAULTS[segment_id]
        imports.append(f"    {segment_id}_inputs_json: str = {default_json!r},")
    imports.extend(
        [
            "    tank_site: str = 'tank-1',",
            "    collector_site: str = 'collector-item-1',",
            "    bottle_site: str = 'bottle-item-1',",
            f") -> {result_class}:",
        ]
    )

    if not hierarchical_v2:
        source_rows = [
            ("sample_vial",) + MATERIAL_SOURCE_SPECS["sample_vial"],
            ("plate",) + MATERIAL_SOURCE_SPECS["plate"],
            ("collector",) + MATERIAL_SOURCE_SPECS["collector"],
            ("vial",) + MATERIAL_SOURCE_SPECS["vial"],
        ]
        for name, template, mount, flow_role in source_rows:
            imports.extend(
                [
                    f"    # unilab:node_uuid={_material_node_uuid(parent_uuid, f'source-{name}')}",
                    f"    {name} = material_source(",
                    f"        resource_template={template},",
                    "        mode='existing',",
                    f"        mount=resource_ref({mount!r}),",
                    "        material_uuid=None,",
                    "        site=None,",
                    "        slot_range=None,",
                    f"        flow_role={flow_role},",
                    "    )",
                ]
            )

    def call_lines(segment_id: str, material_args: dict[str, str], indent: int) -> list[str]:
        operation_name = str(rows[segment_id]["operation"])
        symbol = segment_symbol(operation_name)
        prefix = " " * indent
        values = [
            f"{prefix}# unilab:node_uuid={_material_node_uuid(parent_uuid, f'segment-{segment_id}')}",
            f"{prefix}{segment_id} = {symbol}(",
        ]
        for key, expression in material_args.items():
            values.append(f"{prefix}    {key}={expression},")
        values.append(f"{prefix}    inputs_json={segment_id}_inputs_json,")
        if segment_id == "s5":
            values.append(f"{prefix}    tank_site=tank_site,")
        elif segment_id == "s9":
            values.append(f"{prefix}    before_path=s4.before_path,")
        elif segment_id == "s10":
            values.extend(
                [
                    f"{prefix}    collector_hole=s7.collector_hole,",
                    f"{prefix}    bottle_hole=s7.bottle_hole,",
                    f"{prefix}    collector_site=collector_site,",
                    f"{prefix}    bottle_site=bottle_site,",
                ]
            )
        values.append(f"{prefix})")
        return values

    imports.extend(call_lines("af0", {}, 4))
    imports.extend(call_lines("s1", {"plate": "plate"}, 4))
    imports.extend(
        [
            "    with parallel():",
            f"        # unilab:node_uuid={_material_node_uuid(parent_uuid, 'group-s2-s4')}",
            "        with group(name='s2 点样 → s4 展开前拍照'):",
        ]
    )
    imports.extend(
        call_lines(
            "s2", {"sample_vial": "sample_vial", "plate": "s1.plate"}, 12
        )
    )
    imports.extend(call_lines("s4", {"plate": "s2.plate"}, 12))
    imports.extend(
        [
            f"        # unilab:node_uuid={_material_node_uuid(parent_uuid, 'group-s3')}",
            "        with group(name='s3 展缸预备'):",
        ]
    )
    imports.extend(call_lines("s3", {}, 12))
    imports.extend(call_lines("s5", {"plate": "s4.plate"}, 4))
    imports.extend(
        [
            "    with parallel():",
            f"        # unilab:node_uuid={_material_node_uuid(parent_uuid, 'group-s6-s8')}",
            "        with group(name='s6 展开等待 → s8 出缸上刮板台'):",
        ]
    )
    imports.extend(call_lines("s6", {"plate": "s5.plate"}, 12))
    imports.extend(call_lines("s8", {"plate": "s6.plate"}, 12))
    imports.extend(
        [
            f"        # unilab:node_uuid={_material_node_uuid(parent_uuid, 'group-s7')}",
            "        with group(name='s7 备耗材（严格在 s5 后）'):",
        ]
    )
    imports.extend(
        call_lines("s7", {"collector": "collector", "vial": "vial"}, 12)
    )
    imports.extend(
        call_lines(
            "s9", {"plate": "s8.plate", "collector": "s7.collector"}, 4
        )
    )
    imports.extend(
        call_lines("s10", {"collector": "s9.collector", "vial": "s7.vial"}, 4)
    )
    imports.extend(call_lines("s11", {"plate": "s9.plate"}, 4))
    imports.extend(
        [
            "    return {",
            "        'sample': s10.vial,",
            "        'waste_plate': s11.plate,",
            "        'powder_collector': s10.collector,",
            "    }",
            "",
        ]
    )
    return "\n".join(imports)


def _render_package_manifest(
    *,
    material_segment_rows: list[dict[str, Any]],
    runtime_segment_rows: list[dict[str, Any]],
) -> str:
    """Register every supported projection child-first in the active package."""

    operation_views = _load_yaml(OPERATION_VIEW_MANIFEST_PATH)
    operation_review = _load_yaml(OPERATION_REVIEW_MANIFEST_PATH)
    workflows = [
        {
            "workflow_uuid": TRANSPORT_UUID,
            "source": "eit_ptlc/workflows/transport_resource_v4.py",
        }
    ]
    workflows.extend(
        {
            "workflow_uuid": str(row["workflow_uuid"]),
            "source": str(row["source"]),
        }
        for row in operation_views["operations"]
    )
    workflows.extend(
        {
            "workflow_uuid": str(row["workflow_uuid"]),
            "source": str(row["source"]),
        }
        for row in operation_review["roots"]
    )
    workflows.extend(
        {
            "workflow_uuid": str(row["workflow_uuid"]),
            "source": str(row["source"]),
        }
        for row in material_segment_rows
    )
    workflows.extend(
        {
            "workflow_uuid": str(row["workflow_uuid"]),
            "source": str(row["source"]),
        }
        for row in runtime_segment_rows
    )
    workflows.extend(
        [
            {
                "workflow_uuid": TYPED_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_v4.py",
            },
            {
                "workflow_uuid": GENERIC_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_station_operation_v1.py",
            },
            {
                "workflow_uuid": REVIEW_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_operation_review_v1.py",
            },
            {
                "workflow_uuid": MATERIAL_SEGMENTS_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_segments_v1.py",
            },
            {
                "workflow_uuid": HIERARCHICAL_SEGMENTS_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_segments_v2.py",
            },
        ]
    )
    body = yaml.safe_dump(
        {"package": {"name": "eit_ptlc"}, "workflows": workflows},
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    return "# AUTO-GENERATED FILE. DO NOT EDIT.\n" + body


def _render_legacy_package_manifest(
    *, material_segment_rows: list[dict[str, Any]]
) -> str:
    """Keep the complete pre-v2 package registration as an opt-in profile."""

    operation_review = _load_yaml(OPERATION_REVIEW_MANIFEST_PATH)
    workflows = [
        {
            "workflow_uuid": TRANSPORT_UUID,
            "source": "eit_ptlc/workflows/transport_resource_v4.py",
        }
    ]
    workflows.extend(
        {
            "workflow_uuid": str(row["workflow_uuid"]),
            "source": str(row["source"]),
        }
        for row in operation_review["roots"]
    )
    workflows.extend(
        {
            "workflow_uuid": str(row["workflow_uuid"]),
            "source": str(row["source"]),
        }
        for row in material_segment_rows
    )
    workflows.extend(
        [
            {
                "workflow_uuid": TYPED_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_v4.py",
            },
            {
                "workflow_uuid": GENERIC_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_station_operation_v1.py",
            },
            {
                "workflow_uuid": REVIEW_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_operation_review_v1.py",
            },
            {
                "workflow_uuid": MATERIAL_SEGMENTS_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_segments_v1.py",
            },
        ]
    )
    body = yaml.safe_dump(
        {"package": {"name": "eit_ptlc_legacy"}, "workflows": workflows},
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    return "# AUTO-GENERATED FILE. DO NOT EDIT.\n" + body


def render_outputs() -> tuple[dict[Path, str], dict[str, Any]]:
    recipe = _validate_recipe()
    operations = _load_operation_documents()
    segment_operations = _load_segment_operation_documents()
    material_contract = _validate_material_contract()
    typed_template = TYPED_TEMPLATE.read_text(encoding="utf-8")
    review_template = REVIEW_TEMPLATE.read_text(encoding="utf-8")

    outputs = {
        WORKFLOWS_DIR / "ptlc_parallel_v4.py": _with_header(typed_template),
        WORKFLOWS_DIR / "ptlc_parallel_station_operation_v1.py": _with_header(
            _render_generic_variant(typed_template)
        ),
        WORKFLOWS_DIR / "ptlc_parallel_operation_review_v1.py": _with_header(
            review_template
        ),
    }
    material_segment_rows: list[dict[str, Any]] = []
    runtime_segment_rows: list[dict[str, Any]] = []
    for row in material_contract["segments"]:
        operation_name = str(row["operation"])
        workflow_uuid = _material_segment_uuid(operation_name)
        source = (
            WORKFLOWS_DIR / _material_segment_filename(operation_name)
        )
        outputs[source] = _with_header(
            _render_material_segment(row, segment_operations[operation_name])
        )
        material_segment_rows.append(
            {
                "segment_id": str(row["id"]),
                "operation_name": operation_name,
                "workflow_uuid": workflow_uuid,
                "source": source.relative_to(ROOT).as_posix(),
                "portable_inputs": list(row.get("portable_inputs") or []),
                "portable_outputs": list(row.get("portable_outputs") or []),
                "station_materials": list(row.get("station_materials") or []),
                "operation_outputs": dict(row.get("operation_outputs") or {}),
                "bind_inputs": dict(row.get("bind_inputs") or {}),
                "lineage": row.get("lineage"),
                "commits": dict(row.get("commits") or {}),
            }
        )
        runtime_workflow_uuid = _runtime_segment_uuid(operation_name)
        runtime_source = (
            WORKFLOWS_DIR / f"{_runtime_segment_symbol(operation_name)}.py"
        )
        outputs[runtime_source] = _with_header(
            _render_material_segment(
                row,
                segment_operations[operation_name],
                runtime_v2=True,
            )
        )
        runtime_segment_rows.append(
            {
                "segment_id": str(row["id"]),
                "operation_name": operation_name,
                "workflow_uuid": runtime_workflow_uuid,
                "source": runtime_source.relative_to(ROOT).as_posix(),
                "portable_inputs": list(row.get("portable_inputs") or []),
                "portable_outputs": list(row.get("portable_outputs") or []),
                "station_materials": list(row.get("station_materials") or []),
                "operation_outputs": dict(row.get("operation_outputs") or {}),
                "bind_inputs": dict(row.get("bind_inputs") or {}),
                "lineage": row.get("lineage"),
                "commits": dict(row.get("commits") or {}),
            }
        )
    material_parent_path = WORKFLOWS_DIR / "ptlc_parallel_segments_v1.py"
    outputs[material_parent_path] = _with_header(
        _render_material_segments_parent(recipe, material_contract)
    )
    hierarchical_parent_path = WORKFLOWS_DIR / "ptlc_parallel_segments_v2.py"
    outputs[hierarchical_parent_path] = _with_header(
        _render_material_segments_parent(
            recipe,
            material_contract,
            hierarchical_v2=True,
        )
    )
    source_digest = hashlib.sha256()
    source_digest.update(RECIPE_PATH.relative_to(ROOT).as_posix().encode("utf-8"))
    source_digest.update(RECIPE_PATH.read_bytes())
    source_digest.update(
        MATERIAL_CONTRACT_PATH.relative_to(ROOT).as_posix().encode("utf-8")
    )
    source_digest.update(MATERIAL_CONTRACT_PATH.read_bytes())
    for operation_name in sorted(segment_operations):
        source_digest.update(operation_name.encode("utf-8"))
        source_digest.update(
            yaml.safe_dump(segment_operations[operation_name], sort_keys=True).encode(
                "utf-8"
            )
        )
    manifest = {
        "schema": "unilab.platformui-workflow-variants/v1",
        "generated_from": RECIPE_PATH.relative_to(ROOT).as_posix(),
        "source_sha256": source_digest.hexdigest(),
        "source_recipe": str(recipe.get("name") or ""),
        "source_segments": [item[1] for item in EXPECTED_RECIPE_DAG],
        "material_contract": MATERIAL_CONTRACT_PATH.relative_to(ROOT).as_posix(),
        "material_segment_workflows": material_segment_rows,
        "runtime_segment_workflows_v2": runtime_segment_rows,
        "typed_station_operations": [
            {
                "operation_name": name,
                "namespace": TYPED_OPERATION_OWNERS[name],
                "inputs": [
                    str(item["name"])
                    for item in operations[name].get("vars") or []
                    if isinstance(item, dict) and item.get("io") in {"in", "inout"}
                ],
            }
            for name in TYPED_OPERATION_OWNERS
        ],
        "variants": [
            {
                "id": "ptlc_parallel_v4",
                "workflow_uuid": TYPED_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_v4.py",
                "operation_projection": "named_typed_action",
            },
            {
                "id": "ptlc_parallel_station_operation_v1",
                "workflow_uuid": GENERIC_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_station_operation_v1.py",
                "operation_projection": "generic_run_station_operation_action",
            },
            {
                "id": "ptlc_parallel_operation_review_v1",
                "workflow_uuid": REVIEW_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_operation_review_v1.py",
                "operation_projection": "expandable_scheme_1_subworkflows",
            },
            {
                "id": "ptlc_parallel_segments_v1",
                "workflow_uuid": MATERIAL_SEGMENTS_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_segments_v1.py",
                "operation_projection": "expandable_material_segment_subworkflows",
            },
            {
                "id": "ptlc_parallel_segments_v2",
                "workflow_uuid": HIERARCHICAL_SEGMENTS_UUID,
                "source": "eit_ptlc/workflows/ptlc_parallel_segments_v2.py",
                "operation_projection": "hierarchical_display_atomic_runtime_subworkflows",
            },
        ],
    }
    outputs[PACKAGE_PATH] = _render_package_manifest(
        material_segment_rows=material_segment_rows,
        runtime_segment_rows=runtime_segment_rows,
    )
    outputs[LEGACY_PACKAGE_PATH] = _render_legacy_package_manifest(
        material_segment_rows=material_segment_rows,
    )
    return outputs, manifest


def export_workflow_variants(*, check: bool = False) -> None:
    outputs, manifest = render_outputs()
    manifest_path = GENERATED_DIR / "platformui_workflow_variants.v1.yaml"
    manifest_text = yaml.safe_dump(
        manifest,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    expected = {**outputs, manifest_path: manifest_text}
    drifted: list[str] = []
    for path, source in expected.items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != source:
                drifted.append(path.relative_to(ROOT).as_posix())
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    if drifted:
        raise SystemExit(
            "generated UniLab workflow variants drifted; run "
            "`PYTHONPATH=. python tools/export_unilab_workflow_variants.py`: "
            + ", ".join(drifted)
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    export_workflow_variants(check=args.check)


if __name__ == "__main__":
    main()
