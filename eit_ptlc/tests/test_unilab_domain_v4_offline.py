"""Fixed-point acceptance for the in-place UniLab v4 domain facade."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

import pytest
import yaml

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.unilab_domain.runtime_port import InMemoryPtlcRuntimePort
from eit_ptlc.unilab_domain.transport_runtime import (
    TransportOutcomeUnknown,
    execute_transport_root,
    preflight_transport,
)
from tools.export_unilab_workflow_variants import (
    EXPECTED_RECIPE_DAG,
    HIERARCHICAL_SEGMENTS_UUID,
    MATERIAL_SEGMENTS_UUID,
    render_outputs,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT / "eit_ptlc"
OS_ROOT = Path("/Users/dp/Design_projects/Uni-Lab-Core/Uni-Lab-OS")
MAIN_UUID = "1a424e61-d0fe-5489-86ae-11ca393d21b8"
GENERIC_MAIN_UUID = "c76bb7fd-add3-58b7-b950-bdf494c9af80"
TRANSPORT_UUID = "75067f83-c472-51de-8dc5-e99fdc655df6"


class _Node:
    def __init__(self, name: str, parent: object | None = None) -> None:
        self.name = name
        self.parent = parent
        self.metadata: dict[str, object] = {}


def _yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_generated_manifest_is_exactly_the_93_platformui_actions() -> None:
    registry = ActionRegistry.load(ROOT / "config" / "actions")
    manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_actions.v1.yaml"
    )
    actual = {row["name"] for row in manifest["actions"]}
    expected = {action.name for action in registry.list()}
    assert manifest["external_action_count"] == 93
    assert manifest["typed_operation_action_count"] == 7
    assert manifest["proxy_device_count"] == 11
    assert actual == expected
    assert Counter(row["namespace"] for row in manifest["actions"]) == {
        "sampling": 12,
        "develop": 11,
        "collect": 9,
        "photoscrape": 20,
        "feedlift": 11,
        "rail": 2,
        "robot": 21,
        "pump": 2,
        "vision": 1,
        "staging_a": 2,
        "material": 2,
    }
    write_path = next(
        row
        for row in manifest["actions"]
        if row["name"] == "photoscrape.write_cnc_path"
    )
    assert [item["name"] for item in write_path["params"]] == [
        "sx",
        "sy",
        "cx",
        "cy",
        "feed",
    ]
    typed = {row["operation_name"]: row for row in manifest["typed_operation_actions"]}
    assert set(typed) == {
        "sampling_prepare",
        "sampling_execute",
        "develop_prepare",
        "pf_s6_develop_wait",
        "photoscrape_before_photo_capture",
        "photoscrape_process",
        "collect_execute",
    }
    assert [
        item["name"] for item in typed["photoscrape_before_photo_capture"]["params"]
    ] == ["sample_id", "save_dir"]


def test_all_longest_flow_variants_are_generated_from_parallel_v1() -> None:
    outputs, expected_manifest = render_outputs()
    for path, expected_source in outputs.items():
        assert path.read_text(encoding="utf-8") == expected_source
        assert expected_source.startswith("# AUTO-GENERATED FILE. DO NOT EDIT.")
    manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_workflow_variants.v1.yaml"
    )
    assert manifest == expected_manifest
    assert [item["operation_projection"] for item in manifest["variants"]] == [
        "named_typed_action",
        "generic_run_station_operation_action",
        "expandable_scheme_1_subworkflows",
        "expandable_material_segment_subworkflows",
        "hierarchical_display_atomic_runtime_subworkflows",
    ]
    assert manifest["source_segments"] == [item[1] for item in EXPECTED_RECIPE_DAG]
    assert len(manifest["material_segment_workflows"]) == 12
    assert len(manifest["runtime_segment_workflows_v2"]) == 12
    assert manifest["material_contract"] == (
        "eit_ptlc/config/recipes/parallel_v1.materials.yaml"
    )


def test_material_segment_contract_tracks_every_portable_and_station_material() -> None:
    manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_workflow_variants.v1.yaml"
    )
    rows = {row["segment_id"]: row for row in manifest["material_segment_workflows"]}
    assert tuple(rows) == tuple(item[0] for item in EXPECTED_RECIPE_DAG)
    assert rows["s2"]["portable_inputs"] == ["sample_vial", "plate"]
    assert rows["s2"]["lineage"] == "spotting"
    assert rows["s3"]["station_materials"][-1] == {
        "name": "prepared_developing_bath",
        "role": "produced_in_tank",
        "authority": "PlatformUI",
    }
    assert rows["s7"]["portable_inputs"] == ["collector", "vial"]
    assert rows["s4"]["operation_outputs"] == {"before_path": "STRING"}
    assert rows["s7"]["operation_outputs"] == {
        "collector_hole": "INT",
        "bottle_hole": "INT",
    }
    assert rows["s9"]["bind_inputs"] == {"before_path": "STRING"}
    assert rows["s10"]["bind_inputs"] == {
        "collector_hole": "INT",
        "bottle_hole": "INT",
    }
    assert rows["s9"]["lineage"] == "scraping"
    assert rows["s10"]["lineage"] == "collection"
    assert rows["s10"]["station_materials"] == [
        {
            "name": "collection_elution_solvent",
            "role": "consumed",
            "authority": "PlatformUI",
        }
    ]
    assert rows["s11"]["station_materials"] == [
        {
            "name": "waste_magazine_seed_plate",
            "role": "required",
            "authority": "PlatformUI",
        }
    ]


def test_material_segment_parent_preserves_parallel_v1_dag() -> None:
    pytest.importorskip("unilabos.workflow.authoring_ast")
    from unilabos.workflow.authoring_ast import parse_authoring_source

    program = parse_authoring_source(
        python_source=(ROOT / "workflows" / "ptlc_parallel_segments_v1.py").read_text(
            encoding="utf-8"
        ),
        expected_workflow_uuid=MATERIAL_SEGMENTS_UUID,
    )
    composites = {
        action.symbol: action.node_uuid
        for action in program.actions
        if action.__class__.__name__ == "CompositeDeclaration"
    }
    edges = set(program.order_dependencies)
    assert len(composites) == 12
    assert (
        composites["pf_s1_load_material_v1"],
        composites["pf_s2_spot_material_v1"],
    ) in edges
    assert (
        composites["pf_s1_load_material_v1"],
        composites["pf_s3_tank_prep_material_v1"],
    ) in edges
    assert (
        composites["pf_s2_spot_material_v1"],
        composites["pf_s3_tank_prep_material_v1"],
    ) not in edges
    assert (
        composites["pf_s4_photo_before_material_v1"],
        composites["pf_s5_to_tank_material_v1"],
    ) in edges
    assert (
        composites["pf_s3_tank_prep_material_v1"],
        composites["pf_s5_to_tank_material_v1"],
    ) in edges
    assert (
        composites["pf_s5_to_tank_material_v1"],
        composites["pf_s6_develop_wait_material_v1"],
    ) in edges
    assert (
        composites["pf_s5_to_tank_material_v1"],
        composites["pf_s7_consumables_material_v1"],
    ) in edges
    assert (
        composites["pf_s8_to_scrape_material_v1"],
        composites["pf_s9_scrape_material_v1"],
    ) in edges
    assert (
        composites["pf_s7_consumables_material_v1"],
        composites["pf_s9_scrape_material_v1"],
    ) in edges
    by_symbol = {
        action.symbol: action
        for action in program.actions
        if action.__class__.__name__ == "CompositeDeclaration"
    }
    s9_arguments = dict(by_symbol["pf_s9_scrape_material_v1"].arguments)
    assert (
        s9_arguments["before_path"].kind,
        s9_arguments["before_path"].result_name,
        s9_arguments["before_path"].value,
    ) == ("node_output", "s4", "before_path")
    s10_arguments = dict(by_symbol["pf_s10_collect_material_v1"].arguments)
    assert (
        s10_arguments["collector_hole"].kind,
        s10_arguments["collector_hole"].result_name,
        s10_arguments["collector_hole"].value,
    ) == ("node_output", "s7", "collector_hole")
    assert (
        s10_arguments["bottle_hole"].kind,
        s10_arguments["bottle_hole"].result_name,
        s10_arguments["bottle_hole"].value,
    ) == ("node_output", "s7", "bottle_hole")


def test_each_material_segment_executes_one_atomic_root_then_preserves_slots() -> None:
    pytest.importorskip("unilabos.workflow.authoring_ast")
    from unilabos.workflow.authoring_ast import parse_authoring_source

    manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_workflow_variants.v1.yaml"
    )
    for row in manifest["material_segment_workflows"]:
        program = parse_authoring_source(
            python_source=(REPO_ROOT / row["source"]).read_text(encoding="utf-8"),
            expected_workflow_uuid=row["workflow_uuid"],
        )
        composites = [
            action
            for action in program.actions
            if action.__class__.__name__ == "CompositeDeclaration"
        ]
        assert composites == []
        root_runs = [
            action
            for action in program.actions
            if getattr(action, "action_name", None) == "run_operation_review_v1"
        ]
        assert len(root_runs) == 1
        assert dict(root_runs[0].arguments)["operation_name"].value == row[
            "operation_name"
        ]
        declared_outputs = dict(program.declared_output_schemas)
        input_parameters = {
            item["name"]: item["schema"]
            for item in program.input_contract["parameters"]
        }
        for material_name in row["portable_inputs"]:
            assert input_parameters[material_name] == {"$slot": "ResourceSlot"}
            assert declared_outputs[material_name] == {"$slot": "ResourceSlot"}
        assert set(row["portable_inputs"]) == set(row["portable_outputs"])
        assert not program.disabled_node_uuids


def test_each_runtime_v2_segment_has_one_disabled_view_and_one_root_submission() -> None:
    pytest.importorskip("unilabos.workflow.authoring_ast")
    from unilabos.workflow.authoring_ast import parse_authoring_source

    manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_workflow_variants.v1.yaml"
    )
    for row in manifest["runtime_segment_workflows_v2"]:
        program = parse_authoring_source(
            python_source=(REPO_ROOT / row["source"]).read_text(encoding="utf-8"),
            expected_workflow_uuid=row["workflow_uuid"],
        )
        composites = [
            action
            for action in program.actions
            if action.__class__.__name__ == "CompositeDeclaration"
        ]
        assert [item.symbol for item in composites] == [
            f"{row['operation_name']}_operation_view_v2"
        ]
        # The composite is an interactive, expandable display boundary.  Its
        # projected action nodes are disabled by the operation-view workflow;
        # disabling the boundary itself would prevent layered inspection.
        assert composites[0].node_uuid not in set(program.disabled_node_uuids)
        root_runs = [
            action
            for action in program.actions
            if getattr(action, "action_name", None) == "run_operation_review_v1"
        ]
        assert len(root_runs) == 1
        assert root_runs[0].node_uuid not in set(program.disabled_node_uuids)
        assert dict(root_runs[0].arguments)["operation_name"].value == row["operation_name"]


def test_hierarchical_v2_parent_keeps_the_parallel_v1_dag() -> None:
    pytest.importorskip("unilabos.workflow.authoring_ast")
    from unilabos.workflow.authoring_ast import parse_authoring_source

    program = parse_authoring_source(
        python_source=(ROOT / "workflows" / "ptlc_parallel_segments_v2.py").read_text(
            encoding="utf-8"
        ),
        expected_workflow_uuid=HIERARCHICAL_SEGMENTS_UUID,
    )
    input_parameters = {
        item["name"]: item["schema"]
        for item in program.input_contract["parameters"]
    }
    assert {
        name: input_parameters[name]
        for name in ("sample_vial", "plate", "collector", "vial")
    } == {
        "sample_vial": {"$slot": "ResourceSlot"},
        "plate": {"$slot": "ResourceSlot"},
        "collector": {"$slot": "ResourceSlot"},
        "vial": {"$slot": "ResourceSlot"},
    }
    assert not any(
        getattr(action, "action_name", None) == "material_source"
        for action in program.actions
    )
    composites = {
        action.symbol: action.node_uuid
        for action in program.actions
        if action.__class__.__name__ == "CompositeDeclaration"
    }
    edges = set(program.order_dependencies)
    assert len(composites) == 12
    assert (
        composites["pf_s1_load_runtime_v2"],
        composites["pf_s2_spot_runtime_v2"],
    ) in edges
    assert (
        composites["pf_s1_load_runtime_v2"],
        composites["pf_s3_tank_prep_runtime_v2"],
    ) in edges
    assert (
        composites["pf_s2_spot_runtime_v2"],
        composites["pf_s3_tank_prep_runtime_v2"],
    ) not in edges
    assert (
        composites["pf_s4_photo_before_runtime_v2"],
        composites["pf_s5_to_tank_runtime_v2"],
    ) in edges
    assert (
        composites["pf_s3_tank_prep_runtime_v2"],
        composites["pf_s5_to_tank_runtime_v2"],
    ) in edges
    assert (
        composites["pf_s5_to_tank_runtime_v2"],
        composites["pf_s6_develop_wait_runtime_v2"],
    ) in edges
    assert (
        composites["pf_s5_to_tank_runtime_v2"],
        composites["pf_s7_consumables_runtime_v2"],
    ) in edges
    assert (
        composites["pf_s8_to_scrape_runtime_v2"],
        composites["pf_s9_scrape_runtime_v2"],
    ) in edges
    assert (
        composites["pf_s7_consumables_runtime_v2"],
        composites["pf_s9_scrape_runtime_v2"],
    ) in edges


def test_typed_operation_action_encodes_fields_for_the_unchanged_vm() -> None:
    port = InMemoryPtlcRuntimePort()
    proxy = PLCPhotoScrape(config={"runtime_port": port})
    result = asyncio.run(
        proxy.photoscrape_before_photo_capture(
            sample_id="SAMPLE-42",
            save_dir="var/photoscrape/SAMPLE-42",
        )
    )
    assert result["operation_name"] == "photoscrape_before_photo_capture"
    assert result["status"] == "DONE"
    assert port.invocations == []
    assert len(port.root_runs) == 1
    assert port.root_runs[0]["operation"] == "photoscrape_before_photo_capture"
    assert port.root_runs[0]["inputs"] == {
        "sample_id": "SAMPLE-42",
        "save_dir": "var/photoscrape/SAMPLE-42",
    }


def test_every_generated_transport_root_holds_robot_and_rail_once() -> None:
    catalog = _yaml(ROOT / "unilab_domain" / "generated" / "transport_routes.v1.yaml")
    assert catalog["contract_inputs"] == [
        "resource",
        "target_device",
        "target_mount",
        "target_site",
    ]
    names = set()
    for route in catalog["routes"]:
        name = route["operation"]
        names.add(name)
        assert {"robot", "station:rail"} <= set(route["resources"])
        document = _yaml(
            ROOT / "config" / "operation" / "12_unilab_transport" / f"{name}.yaml"
        )
        assert document["name"] == name
        assert {"robot", "station:rail"} <= set(document["resources"])
        assert document["ui"] == {
            "role": "unilab_transport_v4",
            "projection_only": True,
        }
    assert len(names) == 14


def test_transport_submits_one_root_and_remembers_the_same_material_location() -> None:
    resource = _Node("plate-001", parent=_Node("plc_feedlift"))
    target = _Node("plc_sampling")
    preflight = preflight_transport(
        resource=resource,
        target_device="plc_sampling",
        target_mount=target,
        target_site="plate",
    )
    assert preflight["operation_name"] == "unilab_transport_v4_feedlift_to_spot"
    assert (preflight["source_rail_target"], preflight["target_rail_target"]) == (1, 2)

    port = InMemoryPtlcRuntimePort()
    physical = asyncio.run(
        execute_transport_root(
            port,
            resource=resource,
            operation_name=preflight["operation_name"],
            operation_inputs_json=preflight["operation_inputs_json"],
            command_id=preflight["command_id"],
            target_site=preflight["target_site"],
        )
    )
    assert physical["resource"] is resource
    assert len(port.root_runs) == 1
    assert port.invocations == []
    assert resource.metadata["ptlc_site"] == "spot-seat"

    next_contract = preflight_transport(
        resource=resource,
        target_device="plc_photoscrape",
        target_mount=_Node("plc_photoscrape"),
        target_site="plate",
    )
    assert next_contract["source_site"] == "spot-seat"
    assert next_contract["operation_name"] == "unilab_transport_v4_spot_to_scrape"


def test_unknown_transport_outcome_is_never_retried_or_committed() -> None:
    resource = _Node("plate-unknown", parent=_Node("plc_feedlift"))
    port = InMemoryPtlcRuntimePort(
        operation_results={
            "unilab_transport_v4_feedlift_to_spot": {"status": "UNKNOWN"}
        }
    )
    with pytest.raises(TransportOutcomeUnknown):
        asyncio.run(
            execute_transport_root(
                port,
                resource=resource,
                operation_name="unilab_transport_v4_feedlift_to_spot",
                operation_inputs_json="{}",
                command_id="unknown-command",
                target_site="spot-seat",
            )
        )
    assert len(port.root_runs) == 1
    assert "ptlc_site" not in resource.metadata


def test_platformui_root_command_id_is_idempotent_at_http_boundary() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from eit_ptlc.api.vm_routes import register_vm_routes

    document = {
        "schema": "ptlc.script/v1",
        "kind": "operation",
        "name": "safe_station_test",
        "label": "safe",
        "vars": [],
        "resources": [],
        "body": [],
    }

    class _Repo:
        def get(self, workspace: str, name: str) -> dict:
            assert (workspace, name) == ("default", "safe_station_test")
            return document

    class _Vm:
        def __init__(self) -> None:
            self.calls = 0
            self.states: dict[str, dict[str, object]] = {}

        def state(self, run_id: str) -> dict:
            if run_id not in self.states:
                raise KeyError(run_id)
            return dict(self.states[run_id])

        async def start(self, doc: dict, inputs: dict, **kwargs: object) -> dict:
            self.calls += 1
            run_id = str(kwargs["run_id"])
            state = {"run_id": run_id, "status": "RUNNING", "current_aid": None}
            self.states[run_id] = state
            return dict(state)

    app = FastAPI()
    register_vm_routes(app)
    vm = _Vm()
    app.state.script_repo = _Repo()
    app.state.vm = vm
    command = {"inputs": {}, "command_id": "transport-command-fixed"}
    with TestClient(app) as client:
        first = client.post("/api/scripts/safe_station_test/debug/run", json=command)
        second = client.post("/api/scripts/safe_station_test/debug/run", json=command)
    assert first.status_code == second.status_code == 200
    assert first.json()["run_id"] == second.json()["run_id"] == command["command_id"]
    assert vm.calls == 1


@pytest.fixture(scope="module")
def authoring_programs():
    pytest.importorskip("unilabos.workflow.authoring_ast")
    from unilabos.workflow.authoring_ast import parse_authoring_source

    return {
        "main": parse_authoring_source(
            python_source=(ROOT / "workflows" / "ptlc_parallel_v4.py").read_text(
                encoding="utf-8"
            ),
            expected_workflow_uuid=MAIN_UUID,
        ),
        "transport": parse_authoring_source(
            python_source=(ROOT / "workflows" / "transport_resource_v4.py").read_text(
                encoding="utf-8"
            ),
            expected_workflow_uuid=TRANSPORT_UUID,
        ),
        "generic": parse_authoring_source(
            python_source=(
                ROOT / "workflows" / "ptlc_parallel_station_operation_v1.py"
            ).read_text(encoding="utf-8"),
            expected_workflow_uuid=GENERIC_MAIN_UUID,
        ),
    }


def test_parallel_v1_dependencies_are_exact_in_authoring_graph(
    authoring_programs,
) -> None:
    program = authoring_programs["main"]
    edges = set(program.order_dependencies)
    # s1 transport -> s2 and s3 (parallel)
    assert (
        "af6604c6-bfb7-5090-b95d-0e2df503d520",
        "a3b4b72c-a32a-5332-832a-13e6cb908e30",
    ) in edges
    assert (
        "af6604c6-bfb7-5090-b95d-0e2df503d520",
        "ecc6799c-244d-541e-9edc-399dd7f08cd8",
    ) in edges
    # s2 lineage -> s4 transport, with no s3->s2 or s2->s3 edge.
    assert (
        "dce51443-96e8-5573-8040-c44c3efe2d14",
        "75979140-6056-5a39-a16a-544740232122",
    ) in edges
    assert (
        "a3b4b72c-a32a-5332-832a-13e6cb908e30",
        "ecc6799c-244d-541e-9edc-399dd7f08cd8",
    ) not in edges
    assert (
        "ecc6799c-244d-541e-9edc-399dd7f08cd8",
        "a3b4b72c-a32a-5332-832a-13e6cb908e30",
    ) not in edges
    # s5 joins s4 and s3.
    assert (
        "2d7596ba-229c-58c2-b232-3022fe7cb95d",
        "7ae98e6e-01ee-50db-89a2-b6f9e6786f10",
    ) in edges
    assert (
        "ecc6799c-244d-541e-9edc-399dd7f08cd8",
        "7ae98e6e-01ee-50db-89a2-b6f9e6786f10",
    ) in edges
    # s6 and s7 both start only after s5; s8 follows s6 inside its branch.
    assert (
        "7ae98e6e-01ee-50db-89a2-b6f9e6786f10",
        "edc228e6-8f22-59be-87be-aee4bb52ba79",
    ) in edges
    assert (
        "7ae98e6e-01ee-50db-89a2-b6f9e6786f10",
        "1e1898e8-d982-5aad-b497-40984b6f3874",
    ) in edges
    assert (
        "edc228e6-8f22-59be-87be-aee4bb52ba79",
        "ff039f9d-ac56-5d84-b8af-0d115742e9c8",
    ) in edges
    # s9 joins s8 and the last s7 transfer.
    assert (
        "ff039f9d-ac56-5d84-b8af-0d115742e9c8",
        "ae450f82-ec40-517b-92fe-c26feacbb0e8",
    ) in edges
    assert (
        "4c86c845-7061-50a2-aa9e-824bb02bec1c",
        "ae450f82-ec40-517b-92fe-c26feacbb0e8",
    ) in edges


def test_longest_flow_uses_named_typed_operation_actions(authoring_programs) -> None:
    main = authoring_programs["main"]
    device_actions = [
        action for action in main.actions if hasattr(action, "action_name")
    ]
    action_names = [action.action_name for action in device_actions]
    assert "run_station_operation_v4" not in action_names
    for action_name in {
        "sampling_prepare",
        "sampling_execute",
        "develop_prepare",
        "pf_s6_develop_wait",
        "photoscrape_before_photo_capture",
        "photoscrape_process",
        "collect_execute",
    }:
        assert action_names.count(action_name) == 1

    before_photo = next(
        action
        for action in device_actions
        if action.action_name == "photoscrape_before_photo_capture"
    )
    assert [name for name, _ in before_photo.arguments] == ["sample_id", "save_dir"]


def test_generic_variant_uses_only_run_station_operation_actions(
    authoring_programs,
) -> None:
    generic = authoring_programs["generic"]
    device_actions = [
        action for action in generic.actions if hasattr(action, "action_name")
    ]
    station_actions = [
        action
        for action in device_actions
        if action.action_name == "run_station_operation_v4"
    ]
    assert len(station_actions) == 7
    assert {
        dict(action.arguments)["operation_name"].value for action in station_actions
    } == {
        "sampling_prepare",
        "sampling_execute",
        "develop_prepare",
        "pf_s6_develop_wait",
        "photoscrape_before_photo_capture",
        "photoscrape_process",
        "collect_execute",
    }
    assert not {
        "sampling_prepare",
        "sampling_execute",
        "develop_prepare",
        "pf_s6_develop_wait",
        "photoscrape_before_photo_capture",
        "photoscrape_process",
        "collect_execute",
    } & {action.action_name for action in device_actions}


def test_robot_and_rail_never_escape_transport_boundary(authoring_programs) -> None:
    main = authoring_programs["main"]
    assert {item.symbol for item in main.devices}.isdisjoint({"robot", "rail"})
    assert all(
        getattr(action, "device_symbol", None) not in {"robot", "rail"}
        for action in main.actions
    )
    transport = authoring_programs["transport"]
    assert {item.symbol for item in transport.devices} == {"material", "host_node"}
    assert [action.action_name for action in transport.actions] == [
        "transport_preflight_v4",
        "transport_physical_v4",
        "transfer_resource",
    ]


def test_current_unilab_catalog_keeps_v4_while_adding_review_workflows() -> None:
    pytest.importorskip("unilabos.package_manager")
    from unilabos.package_manager import WorkspaceSource, compile_package_source

    catalog = compile_package_source(WorkspaceSource(REPO_ROOT))
    assert len(catalog.definitions.devices) == 11
    assert len(catalog.definitions.resources) == 7
    view_manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_operation_views.v2.yaml"
    )
    review_manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_operation_review.v1.yaml"
    )
    variants_manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_workflow_variants.v1.yaml"
    )
    assert len(catalog.definitions.workflows) == (
        1
        + view_manifest["workflow_count"]
        + review_manifest["root_count"]
        + len(variants_manifest["material_segment_workflows"])
        + len(variants_manifest["runtime_segment_workflows_v2"])
        + len(variants_manifest["variants"])
    )
    assert {
        "ptlc_parallel_v4",
        "ptlc_parallel_station_operation_v1",
        "transport_resource_v4",
        "ptlc_parallel_operation_review_v1",
        "ptlc_parallel_segments_v1",
        "ptlc_parallel_segments_v2",
    } <= {item.id for item in catalog.definitions.workflows}
    main = next(
        item for item in catalog.definitions.workflows if item.id == "ptlc_parallel_v4"
    )
    assert len(main.details["action_references"]) == 30
    assert all(
        item["schema"] == {"$slot": "ResourceSlot"}
        for item in main.details["output_contract"]
    )
    photoscrape = next(
        item for item in catalog.definitions.devices if item.id == "plc_photoscrape"
    )
    typed_action = photoscrape.details["registry_entry"]["class"][
        "action_value_mappings"
    ]["photoscrape_before_photo_capture"]
    assert typed_action["schema"]["x-unilabos-action-contract"]["input_order"] == (
        "sample_id",
        "save_dir",
        "timeout_s",
    )
    goal_properties = typed_action["schema"]["properties"]["goal"]["properties"]
    assert goal_properties["sample_id"]["title"] == "样品ID"
    assert goal_properties["save_dir"]["title"] == "拍照图保存目录"
