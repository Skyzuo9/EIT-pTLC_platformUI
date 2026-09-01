"""Acceptance tests for the safe PlatformUI operation-to-action review flow."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from eit_ptlc.unilab_domain import runtime_port
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.operation_review import (
    canonical_node_sha256,
    load_operation_document,
    verify_operation_call,
    verify_review_node,
)
from eit_ptlc.unilab_domain.runtime_port import (
    HttpPtlcRuntimePort,
    InMemoryPtlcRuntimePort,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT / "eit_ptlc"
MAIN_UUID = "b2a6a5ef-07e9-5d3e-9695-f0ac1f26700f"
VIEW_V2_MANIFEST = (
    ROOT / "unilab_domain" / "generated" / "platformui_operation_views.v2.yaml"
)


def _yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_review_manifest_covers_source_but_bypasses_loop_bodies() -> None:
    manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_operation_review.v1.yaml"
    )
    assert manifest["semantics"] == {
        "projection_actions_disabled": True,
        "loop_projection": "marker_only_body_not_expanded",
        "repeated_subworkflow_projection": "first_definition_then_reference_marker",
        "enabled_execution_nodes_per_root": 1,
        "execution": "single_unchanged_platformui_root_operation",
        "resource_gate_authority": "eit_ptlc.operation.resources.ResourceGate",
        "control_flow_authority": "eit_ptlc.operation.vm.VmThread",
    }
    assert manifest["root_count"] == 12
    # The earlier 69/409 estimate skipped elif/catch/HITL-nested statements.
    # Full recursive traversal is the acceptance authority.
    assert manifest["unique_operation_count"] == 70
    assert manifest["unique_source_action_call_count"] == 1402
    assert manifest["segment_expanded_action_count"] == 2270
    roots = {row["root_operation"]: row for row in manifest["roots"]}
    assert roots["pf_s2_spot"]["bypassed_loop_count"] == 1
    assert roots["pf_s9_scrape"]["bypassed_loop_count"] == 2
    assert sum(row["bypassed_loop_count"] for row in manifest["roots"]) == 3
    assert (
        sum(
            row["deduplicated_subworkflow_reference_count"] for row in manifest["roots"]
        )
        == 41
    )
    assert {row["root_operation"] for row in manifest["roots"]} == {
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
    }


def test_v2_operation_views_are_direct_only_nested_workflows() -> None:
    manifest = _yaml(VIEW_V2_MANIFEST)
    assert manifest["semantics"] == {
        "projection_actions_disabled": True,
        "run_script_projection": "expandable_composite_children_display_only",
        "operation_parameter_projection": (
            "formatted_source_defaults_and_parent_call_binding_metadata"
        ),
        "loop_projection": "marker_only_body_not_expanded",
        "execution": "display_only_no_platformui_submission",
        "recursive_reference_projection": "disabled_reference_marker",
    }
    assert manifest["root_count"] == 12
    rows = {row["operation_name"]: row for row in manifest["operations"]}
    s8 = rows["pf_s8_to_scrape"]
    assert s8["direct_run_script_children"] == [
        "develop_unload",
        "photoscrape_prepare",
        "photoscrape_plate_load",
    ]
    assert s8["direct_source_node_count"] == 5
    assert s8["projection_node_count"] == 6
    assert s8["group_node_count"] == 0
    assert s8["source"] == (
        "eit_ptlc/workflows/pf_s8_to_scrape_operation_view_v2.py"
    )


def test_s8_v2_view_uses_three_expandable_composites_instead_of_441_nodes() -> None:
    pytest.importorskip("unilabos.workflow.authoring_ast")
    from unilabos.workflow.authoring_ast import parse_authoring_source

    manifest = _yaml(VIEW_V2_MANIFEST)
    row = next(
        item
        for item in manifest["operations"]
        if item["operation_name"] == "pf_s8_to_scrape"
    )
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
        "develop_unload_operation_view_v2",
        "photoscrape_prepare_operation_view_v2",
        "photoscrape_plate_load_operation_view_v2",
    ]
    composite_node_uuids = {action.node_uuid for action in composites}
    assert not (composite_node_uuids & set(program.disabled_node_uuids))
    assert set(program.disabled_node_uuids) == {
        action.node_uuid
        for action in program.actions
        if action.__class__.__name__ != "CompositeDeclaration"
    }
    assert len(program.actions) == 6
    operation_call = program.actions[0]
    assert operation_call.action_name == "review_operation_call_v2"
    assert "inputs_json='{\"tank\":1}'" in (
        REPO_ROOT / row["source"]
    ).read_text(encoding="utf-8")


def test_runtime_v2_keeps_the_display_composite_expandable_without_running_it() -> None:
    """运行层须能展开只读视图，但只读视图本身不得产生物理作业。"""

    pytest.importorskip("unilabos.workflow.authoring_ast")
    from unilabos.workflow.authoring_ast import parse_authoring_source

    source = ROOT / "workflows" / "pf_s8_to_scrape_runtime_v2.py"
    program = parse_authoring_source(
        python_source=source.read_text(encoding="utf-8"),
        expected_workflow_uuid="8fc3216e-33b8-5b57-8b9a-4d23adbb7db1",
    )
    structure = program.actions[0]

    assert structure.__class__.__name__ == "CompositeDeclaration"
    assert structure.symbol == "pf_s8_to_scrape_operation_view_v2"
    assert structure.node_uuid not in set(program.disabled_node_uuids)
    assert dict(structure.arguments) == {}

    # The nested view's own acceptance test above proves only composite
    # coordinators are enabled; every physical action/control leaf is disabled.
    # This exposes hierarchy to the UI without submitting PlatformUI work.


@pytest.fixture(scope="module")
def parsed_review_programs():
    pytest.importorskip("unilabos.workflow.authoring_ast")
    from unilabos.workflow.authoring_ast import parse_authoring_source

    manifest = _yaml(
        ROOT / "unilab_domain" / "generated" / "platformui_operation_review.v1.yaml"
    )
    return {
        row["root_operation"]: (
            row,
            parse_authoring_source(
                python_source=(REPO_ROOT / row["source"]).read_text(encoding="utf-8"),
                expected_workflow_uuid=row["workflow_uuid"],
            ),
        )
        for row in manifest["roots"]
    }


def test_every_review_segment_has_one_enabled_atomic_root(
    parsed_review_programs,
) -> None:
    for root_name, (row, program) in parsed_review_programs.items():
        disabled = set(program.disabled_node_uuids)
        enabled = [
            action for action in program.actions if action.node_uuid not in disabled
        ]
        assert [action.action_name for action in enabled] == ["run_operation_review_v1"]
        assert dict(enabled[0].arguments)["operation_name"].value == root_name
        assert len(program.actions) - 1 == row["projection_node_count"]
        projected_platform_actions = [
            action
            for action in program.actions
            if action.action_name
            not in {
                "review_control_node_v1",
                "run_operation_review_v1",
            }
        ]
        assert len(projected_platform_actions) == row["expanded_action_count"]
        assert all(
            action.node_uuid in disabled for action in projected_platform_actions
        )


def test_loop_nodes_are_visible_disabled_boundaries_without_body_projection(
    parsed_review_programs,
) -> None:
    for root_name, (row, program) in parsed_review_programs.items():
        disabled = set(program.disabled_node_uuids)
        loop_markers = [
            action
            for action in program.actions
            if action.action_name == "review_control_node_v1"
            and dict(action.arguments)["control_kind"].value
            in {"for", "while", "repeat"}
        ]
        assert len(loop_markers) == row["bypassed_loop_count"], root_name
        assert all(marker.node_uuid in disabled for marker in loop_markers)
        source = (REPO_ROOT / row["source"]).read_text(encoding="utf-8")
        assert "循环（结构展开一次）" not in source
        if loop_markers:
            assert "BODY NOT EXPANDED" in source


def test_review_root_runs_once_without_invoking_projected_actions() -> None:
    port = InMemoryPtlcRuntimePort(
        operation_results={
            "pf_s6_develop_wait": {
                "result": {
                    "before_path": {"value": "var/photoscrape/S-1/before.jpg"},
                    "collector_hole": {"value": 3},
                    "bottle_hole": {"value": 5},
                }
            }
        }
    )
    proxy = MaterialProxy(config={"runtime_port": port})
    result = asyncio.run(
        proxy.run_operation_review_v1(
            operation_name="pf_s6_develop_wait",
            inputs_json='{"tank":1}',
        )
    )
    assert result["status"] == "DONE"
    assert len(port.root_runs) == 1
    assert port.root_runs[0]["operation"] == "pf_s6_develop_wait"
    assert port.invocations == []
    assert result["before_path"] == "var/photoscrape/S-1/before.jpg"
    assert result["collector_hole"] == 3
    assert result["bottle_hole"] == 5


def test_review_bridge_does_not_serialize_unrelated_platformui_resources() -> None:
    """虚拟 material 代理不得覆盖 PlatformUI 根 operation 的细粒度锁。"""

    metadata = MaterialProxy.run_operation_review_v1._action_registry_meta
    assert metadata["always_free"] is True


def _drive_without_event_loop(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("ROS-compatible coroutine unexpectedly yielded")


def test_http_runtime_port_supports_ros_coroutines_without_asyncio_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[object, ...]] = []

    def fake_json_request(*args, **kwargs):
        requests.append((*args, kwargs))
        return {"status": "ok"}

    monkeypatch.setattr(runtime_port, "_json_request", fake_json_request)
    port = HttpPtlcRuntimePort(request_timeout_s=7.0)

    result = _drive_without_event_loop(
        port._request("POST", "/api/test", {"value": 1})
    )

    assert result == {"status": "ok"}
    assert requests == [
        (
            "POST",
            "http://127.0.0.1:18080/api/test",
            {"value": 1},
            {"timeout_s": 7.0},
        )
    ]


def test_http_runtime_port_routes_explicit_sim_endpoint_without_double_api_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[object, ...]] = []

    def fake_json_request(*args, **kwargs):
        requests.append((*args, kwargs))
        return {"status": "RUNNING"}

    monkeypatch.setattr(runtime_port, "_json_request", fake_json_request)
    port = HttpPtlcRuntimePort("http://127.0.0.1:18080/api/sim")

    result = _drive_without_event_loop(
        port._request("GET", "/api/debug/sim-run/state")
    )

    assert result == {"status": "RUNNING"}
    assert requests[0][1] == (
        "http://127.0.0.1:18080/api/sim/debug/sim-run/state"
    )


def test_runtime_port_sleep_supports_ros_coroutines_without_asyncio_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(runtime_port.time, "sleep", slept.append)

    _drive_without_event_loop(runtime_port._cooperative_sleep(0.25))

    assert slept == [0.25]


def test_cross_segment_outputs_override_only_the_live_recipe_fields() -> None:
    proxy = MaterialProxy(config={"runtime_port": InMemoryPtlcRuntimePort()})
    result = asyncio.run(
        proxy.bind_parallel_operation_inputs_v1(
            inputs_json='{"mode":"auto","before_path":"stale","collector_hole":1}',
            before_path="var/photoscrape/S-2/before.jpg",
            collector_hole=4,
            bottle_hole=6,
        )
    )
    assert result["inputs_json"] == (
        '{"before_path": "var/photoscrape/S-2/before.jpg", '
        '"bottle_hole": 6, "collector_hole": 4, "mode": "auto"}'
    )


def test_control_marker_is_a_real_read_only_source_verification() -> None:
    document = load_operation_document("pf_s6_develop_wait")
    node = document["body"][2]
    assert (
        verify_review_node(
            operation_name="pf_s6_develop_wait",
            node_path="body/2",
            control_kind="if",
            expected_sha256=canonical_node_sha256(node),
        )["status"]
        == "VERIFIED"
    )
    with pytest.raises(ValueError, match="内容漂移"):
        verify_review_node(
            operation_name="pf_s6_develop_wait",
            node_path="body/2",
            control_kind="if",
            expected_sha256="0" * 64,
        )


def test_operation_call_marker_consumes_and_validates_formatted_inputs() -> None:
    document = load_operation_document("pf_s8_to_scrape")
    result = verify_operation_call(
        operation_name="pf_s8_to_scrape",
        inputs_json='{"tank": 1, "plate": "P-1"}',
        expected_sha256=canonical_node_sha256(document),
    )
    assert result == {
        "operation_name": "pf_s8_to_scrape",
        "inputs_json": '{"plate": "P-1", "tank": 1}',
        "status": "VERIFIED",
    }
    with pytest.raises(ValueError, match="JSON object"):
        verify_operation_call(
            operation_name="pf_s8_to_scrape",
            inputs_json="[]",
            expected_sha256=canonical_node_sha256(document),
        )


def test_review_longest_flow_keeps_parallel_v1_dependencies() -> None:
    pytest.importorskip("unilabos.workflow.authoring_ast")
    from unilabos.workflow.authoring_ast import parse_authoring_source

    program = parse_authoring_source(
        python_source=(
            ROOT / "workflows" / "ptlc_parallel_operation_review_v1.py"
        ).read_text(encoding="utf-8"),
        expected_workflow_uuid=MAIN_UUID,
    )
    edges = set(program.order_dependencies)
    # s2 and s3 fork after the s1 material commit; s4 remains behind s2.
    assert (
        "a067d065-86ca-5f04-b7aa-379eff9ec745",
        "4def5926-d421-52c0-8742-e971fb24c206",
    ) in edges
    assert (
        "a067d065-86ca-5f04-b7aa-379eff9ec745",
        "cbb059b9-fea9-5d2a-9408-e45acff607f1",
    ) in edges
    assert (
        "e0d297ff-e8b4-5df2-8bc5-1505e777e44b",
        "58a8fd13-608e-55cb-8722-da8e9f929bc3",
    ) in edges
    assert (
        "4def5926-d421-52c0-8742-e971fb24c206",
        "cbb059b9-fea9-5d2a-9408-e45acff607f1",
    ) not in edges
    # s5 joins s4 and s3.
    assert (
        "0e82a065-f72e-5702-bcf8-beaeca201bde",
        "347cd0ff-8d14-53e1-9f8e-157febf7884a",
    ) in edges
    assert (
        "cbb059b9-fea9-5d2a-9408-e45acff607f1",
        "347cd0ff-8d14-53e1-9f8e-157febf7884a",
    ) in edges
    # s6 and s7 both begin only after s5; s8 is sequentially behind s6.
    assert (
        "8a7a0dd9-540d-52a6-948d-dd7b4aaca1bd",
        "d4e52682-ebc8-58c2-9944-9a510e0664ab",
    ) in edges
    assert (
        "8a7a0dd9-540d-52a6-948d-dd7b4aaca1bd",
        "fad137bd-28ce-5ae0-bf89-29fc3117ae19",
    ) in edges
    assert (
        "d4e52682-ebc8-58c2-9944-9a510e0664ab",
        "a376fbd5-7889-591a-810e-6db5fa2364cf",
    ) in edges
    # s9 joins s8's plate commit and s7's collector commit.
    assert (
        "c1506bab-f13a-5d3c-9e44-1fa01d42a495",
        "7ab387c2-5a8a-5186-84b4-4bc940a39a31",
    ) in edges
    assert (
        "4c0a7e3a-81e6-5395-8b19-d1c5739a7a79",
        "7ab387c2-5a8a-5186-84b4-4bc940a39a31",
    ) in edges
    assert {item.symbol for item in program.devices} == {"material", "host_node"}


def test_package_compiles_children_before_both_longest_flows() -> None:
    pytest.importorskip("unilabos.package_manager")
    from unilabos.package_manager import WorkspaceSource, compile_package_source

    catalog = compile_package_source(WorkspaceSource(REPO_ROOT))
    assert len(catalog.definitions.devices) == 11
    assert len(catalog.definitions.resources) == 7
    view_manifest = _yaml(VIEW_V2_MANIFEST)
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
    ids = {item.id for item in catalog.definitions.workflows}
    assert {
        "transport_resource_v4",
        "ptlc_parallel_v4",
        "ptlc_parallel_station_operation_v1",
        "ptlc_parallel_operation_review_v1",
        "ptlc_parallel_segments_v1",
        "ptlc_parallel_segments_v2",
    } <= ids
    hierarchical_main = next(
        item
        for item in catalog.definitions.workflows
        if item.id == "ptlc_parallel_segments_v2"
    )
    assert all(
        item["schema"] == {"$slot": "ResourceSlot"}
        for item in hierarchical_main.details["output_contract"]
    )
    legacy = _yaml(REPO_ROOT / "package.legacy.yaml")
    assert len(legacy["workflows"]) == 29
    assert {
        "eit_ptlc/workflows/ptlc_parallel_operation_review_v1.py",
        "eit_ptlc/workflows/ptlc_parallel_segments_v1.py",
    } <= {row["source"] for row in legacy["workflows"]}
