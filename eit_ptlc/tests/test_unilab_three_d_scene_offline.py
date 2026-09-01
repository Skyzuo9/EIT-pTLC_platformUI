"""Actual UniLab graph/Catalog contracts for the PlatformUI 3D facade."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from eit_ptlc.unilab_domain.three_d import compile_graph_scene


REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH = REPO_ROOT / "deployment/graphs/ptlc-platformui-local-debug.json"
REAL_GRAPH = REPO_ROOT / "deployment/graphs/ptlc-platformui-real.json"


def test_started_graph_keeps_robot_execution_on_platformui() -> None:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    robot = next(node for node in graph["nodes"] if node.get("id") == "robot")

    assert robot["config"]["standard_execution_backend"] == "platformui"
    assert robot["config"]["platformui_url"] == "http://127.0.0.1:18080/api/sim"


def test_real_graph_uses_production_api_and_keeps_robot_on_platformui() -> None:
    graph = json.loads(REAL_GRAPH.read_text(encoding="utf-8"))
    proxies = [
        node for node in graph["nodes"]
        if (node.get("config") or {}).get("platformui_url")
    ]
    robot = next(node for node in proxies if node.get("id") == "robot")

    assert len(proxies) == 11
    assert {
        node["config"]["platformui_url"] for node in proxies
    } == {"http://127.0.0.1:18080"}
    assert robot["class"] == "community.eit_ptlc.robot"
    assert robot["config"]["standard_execution_backend"] == "platformui"


def test_started_graph_compiles_every_device_resource_and_submaterial() -> None:
    scene = compile_graph_scene(GRAPH)

    assert len(scene.entities) == 17
    assert set(scene.entities) == {
        "plc_sampling",
        "plc_develop",
        "plc_collect",
        "plc_photoscrape",
        "plc_feedlift",
        "plc_rail",
        "robot",
        "plc_pump",
        "vision",
        "plc_staginga",
        "material",
        "staging_a_stack",
        "staging_b_stack",
        "debug_source_sample",
        "debug_ptlc_plate",
        "debug_powder_collector",
        "debug_collection_vial",
    }
    assert scene.shared_asset_loads == (scene.asset_path,)
    assert scene.entity("robot").model["type"] == "package_moveit"
    assert scene.entity("robot").model["motion_authority"] == "moveit"
    assert scene.entity("material").selector == {
        "kind": "logical_manifest_section",
        "manifest_section": "inventory",
        "geometry": False,
    }
    for graph_id, entity in scene.entities.items():
        if graph_id == "material":
            continue
        assert entity.selector["node_path"]
        assert entity.selector["node_index"] >= 0
        assert entity.selector["subtree_mesh_indices"]


def test_graph_parent_local_world_and_asset_subtree_relationships_are_both_kept() -> None:
    scene = compile_graph_scene(GRAPH)
    rack = scene.entity("staging_a_stack")
    collector = scene.entity("debug_powder_collector")
    plate = scene.entity("debug_ptlc_plate")

    assert collector.parent_id == "staging_a_stack"
    assert rack.children == ("debug_powder_collector",)
    assert tuple(row[3] for row in collector.local_matrix[:3]) == pytest.approx(
        (0.564919531, -0.078598663, 0.188999757)
    )
    assert tuple(row[3] for row in collector.world_matrix[:3]) == pytest.approx(
        (0.564919531, -0.074498664, 0.191829757)
    )
    assert collector.selector["node_path"].startswith(
        rack.selector["node_path"] + "/"
    )
    assert plate.parent_id == "plc_feedlift"
    assert tuple(row[3] for row in plate.world_matrix[:3]) == pytest.approx(
        (0.567418754, -0.436097204, -0.442271832)
    )
    assert plate.selector["kind"] == "procedural_plate"
    assert plate.selector["node_path"].startswith("ST_FEEDLIFT/")


def test_nested_selected_entities_are_pruned_from_every_ancestor_clone() -> None:
    scene = compile_graph_scene(GRAPH)

    assert scene.entity("plc_rail").selector["exclude_node_paths"] == [
        "ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT"
    ]
    assert scene.entity("plc_collect").selector["exclude_node_paths"] == [
        "ST_COLLECT/ACTUATOR_COL_EXTEND/样品瓶-2"
    ]
    assert scene.entity("plc_feedlift").selector["exclude_node_paths"] == [
        "ST_FEEDLIFT/AXIS_AXIS_1Z/CARRIAGE.001/INV_MAGAZINE_FEED_TEMPLATE"
    ]
    assert scene.entity("plc_staginga").selector["exclude_node_paths"] == [
        "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A",
        "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B",
    ]
    assert len(scene.entity("staging_a_stack").selector["exclude_node_paths"]) == 6
    assert len(scene.entity("staging_b_stack").selector["exclude_node_paths"]) == 6
    assert scene.entity("debug_powder_collector").selector["exclude_node_paths"] == []
    assert scene.entity("debug_collection_vial").selector["exclude_node_paths"] == []


def test_materials_have_exclusive_graph_home_and_tool_mount_follow_contracts() -> None:
    scene = compile_graph_scene(GRAPH)
    attachments = [
        entity for entity in scene.entities.values() if entity.attachment is not None
    ]

    assert {entity.graph_id for entity in attachments} == {
        "staging_a_stack",
        "staging_b_stack",
        "debug_source_sample",
        "debug_powder_collector",
        "debug_collection_vial",
    }
    for entity in attachments:
        binding = entity.attachment
        assert binding is not None
        assert binding["follow_policy"] == "exclusive_parent_switch"
        assert binding["states"] == ["home", "graph_parent", "tool_mount"]
        assert binding["home"]["asset_parent_path"]
        assert binding["robot"]["node_path"].endswith("/TOOL_MOUNT")
        assert binding["robot"]["grip"]
        assert binding["robot"]["mount_local"]
        assert binding["runtime"]["follow"].endswith("/TrayBinding.js")
        assert binding["runtime"]["pick_controller"].endswith(
            "/MaterialPickController.js"
        )


def test_provenance_is_machine_readable_and_never_guesses_part_files() -> None:
    scene = compile_graph_scene(GRAPH)

    assert {item["id"] for item in scene.provenance_gaps} == {
        "exact_part_for_scene_selector",
        "procedural_plate_part_file",
    }
    for entity in scene.entities.values():
        provenance = entity.provenance
        assert provenance["cad_assembly"].endswith("TLC设备总装.SLDASM")
        assert provenance["export_artifact"] == "exports/TLC_full_native.glb"
        assert provenance["final_glb_sha256"] == scene.asset_sha256
        part = provenance["solidworks_part"]
        assert part["status"] in {"gap", "not_applicable"}
        assert "source_part" not in part
        if entity.graph_id != "material":
            assert provenance["graph_pose"]["coordinate_authority"] == (
                "machine.official-cr5.glb#world_matrix"
            )
            assert provenance["graph_pose"]["conversion"] == (
                "graph_mm=[gltf_x,-gltf_z,gltf_y]*1000"
            )
    assert (
        scene.entity("debug_ptlc_plate").provenance["solidworks_part"]["gap_id"]
        == "procedural_plate_part_file"
    )


def test_unknown_graph_class_fails_closed() -> None:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    changed = copy.deepcopy(graph)
    changed["nodes"][0]["class"] = "community.eit_ptlc.unknown_station"

    with pytest.raises(ValueError, match="graph_entities rule unknown_station"):
        compile_graph_scene(changed)


def test_real_unilab_material_catalog_resolves_one_glb_into_selected_subtrees() -> None:
    from unilabos.package_manager import (
        WorkspaceSource,
        compile_package_source,
        compile_workspace_material_models,
        compile_workspace_startup,
    )

    source = WorkspaceSource(REPO_ROOT)
    startup = compile_workspace_startup(source)
    package = compile_package_source(source, startup_plan=startup)
    catalog = compile_workspace_material_models(startup, package)
    shared = catalog.models_by_template["community.eit_ptlc.ptlc_shared_scene"]

    assert len(catalog.models_by_template) == 16
    assert "community.eit_ptlc.robot" not in catalog.models_by_template
    assert "community.eit_ptlc.material" not in catalog.models_by_template
    assert shared["format"] == "glb"
    assert shared["path"].endswith(
        "/eit_ptlc/three_d/models/machine.official-cr5.glb"
    )
    context = shared["model_origin"]["scene_context"]
    assert context == {
        "id": "ptlc-official-static-context-v1",
        "coordinate_authority": "machine.official-cr5.glb#world_matrix",
        "mode": "static-read-only",
        "selectors": [
            {
                "kind": "gltf_subtree",
                "node_index": 558,
                "node_path": "ST_FRAME",
                "root_transform": "preserve",
            },
            {
                "kind": "gltf_subtree",
                "node_index": 1078,
                "node_path": "ST_RACK",
                "root_transform": "preserve",
            },
            {
                "kind": "gltf_subtree",
                "node_index": 1424,
                "node_path": "ST_TOOLING",
                "root_transform": "preserve",
            },
        ],
    }
    selected = {
        template: model
        for template, model in catalog.models_by_template.items()
        if template != "community.eit_ptlc.ptlc_shared_scene"
    }
    assert len(selected) == 15
    assert all(model["path"] == shared["path"] for model in selected.values())
    assert all(model["format"] == "glb" for model in selected.values())
    assert all(model["selector"]["kind"] == "gltf_subtree" for model in selected.values())
    assert len({model["selector"]["node_index"] for model in selected.values()}) == 15
    assert selected["community.eit_ptlc.plc_collect"]["selector"] == {
        "kind": "gltf_subtree",
        "node_index": 91,
        "node_path": "ST_COLLECT",
        "root_transform": "reset_translation",
        "exclude_node_paths": ["ST_COLLECT/ACTUATOR_COL_EXTEND/样品瓶-2"],
    }
    assert selected["community.eit_ptlc.ptlc_collection_vial"]["selector"] == {
        "kind": "gltf_subtree",
        "node_index": 1337,
        "node_path": "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B/INV_STAGING_B_ITEM_1",
        "root_transform": "reset_translation",
    }
    assert len(
        selected["community.eit_ptlc.ptlc_collector_rack"]["selector"][
            "exclude_node_paths"
        ]
    ) == 6
    assert len(
        selected["community.eit_ptlc.ptlc_vial_rack"]["selector"][
            "exclude_node_paths"
        ]
    ) == 6
    asset = catalog.read_asset(shared["path"])
    assert asset.media_type == "model/gltf-binary"
    assert asset.etag == "sha256:" + hashlib.sha256(asset.content).hexdigest()
    assert len(asset.content) == scene_asset_size()


def scene_asset_size() -> int:
    return (REPO_ROOT / "eit_ptlc/three_d/models/machine.official-cr5.glb").stat().st_size
