"""UniLab 3D facade must reuse PlatformUI assets without weakening MoveIt."""

from __future__ import annotations

from pathlib import Path

from eit_ptlc.unilab_domain.three_d import load_three_d_asset_facade
from eit_ptlc.unilab_domain.three_d.facade import _sha256


EXPECTED_NAMESPACES = {
    "collect",
    "develop",
    "feedlift",
    "material",
    "photoscrape",
    "pump",
    "rail",
    "robot",
    "sampling",
    "staging_a",
    "vision",
}


def test_text_asset_digest_is_stable_across_windows_line_endings(tmp_path) -> None:
    """Git 的 LF/CRLF checkout 不得制造 3D 文本资产假漂移。"""
    lf = tmp_path / "manifest.json"
    crlf = tmp_path / "manifest-crlf.json"
    lf.write_bytes(b'{\n  "version": 2\n}\n')
    crlf.write_bytes(b'{\r\n  "version": 2\r\n}\r\n')

    assert _sha256(lf) == _sha256(crlf)


def test_facade_pins_existing_platform_assets_without_copying_glb() -> None:
    """Every reference resolves inside eit_ptlc and the only scene is the existing GLB."""

    facade = load_three_d_asset_facade()
    package_root = Path(__file__).resolve().parents[1]
    assert set(facade.assets) == {
        "scene",
        "scene_manifest",
        "rig_source",
        "action_motion_map",
        "payload_poses",
        "payload_grips",
        "clip_index",
        "robot_points",
        "provenance",
    }
    for asset in facade.assets.values():
        assert asset.path.is_file()
        assert asset.path.is_relative_to(package_root)
        assert len(asset.sha256) == 64
    assert facade.asset_path("scene") == (
        package_root / "three_d/models/machine.official-cr5.glb"
    )
    assert not list((package_root / "unilab_domain").rglob("*.glb"))


def test_all_proxy_devices_resolve_to_shared_scene_or_inventory() -> None:
    """The 11 public action namespaces have deterministic visual selectors."""

    facade = load_three_d_asset_facade()
    bindings = {
        namespace: facade.device_visual(namespace)
        for namespace in EXPECTED_NAMESPACES
    }
    assert set(bindings) == EXPECTED_NAMESPACES
    assert bindings["robot"].glb_node.endswith("/ST_ROBOT")
    assert bindings["rail"].glb_node == "ST_RAIL"
    assert bindings["rail"].excluded_glb_nodes == (
        "ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT",
    )
    assert bindings["collect"].excluded_glb_nodes == (
        "ST_COLLECT/ACTUATOR_COL_EXTEND/样品瓶-2",
    )
    assert bindings["feedlift"].excluded_glb_nodes == (
        "ST_FEEDLIFT/AXIS_AXIS_1Z/CARRIAGE.001/INV_MAGAZINE_FEED_TEMPLATE",
    )
    assert bindings["staging_a"].excluded_glb_nodes == (
        "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A",
        "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B",
    )
    assert bindings["vision"].glb_node == "ST_VISION"
    assert bindings["material"].manifest_section == "inventory"
    assert bindings["material"].glb_node is None


def test_platform_payloads_keep_home_pose_and_tool_mount_grip() -> None:
    """Every movable payload is backed by PlatformUI pose and grip facts."""

    facade = load_three_d_asset_facade()
    attachments = facade.platform_manifest["attachments"]
    assert len(attachments) == 29
    bindings = [facade.material_visual(item["id"]) for item in attachments]
    assert {item.kind for item in bindings} == {"item", "tray"}
    assert all(item.node for item in bindings)
    assert all(item.home_pose for item in bindings)
    assert all(item.tool_mount_grip for item in bindings)


def test_moveit_remains_trajectory_and_joint_display_authority() -> None:
    """A richer static scene must not replace MoveIt planning or articulation."""

    facade = load_three_d_asset_facade()
    contract = facade.moveit_model_contract()
    assert contract["planning_authority"] == "moveit"
    assert contract["model"] == {
        "type": "package_moveit",
        "format": "urdf",
        "model_ref": "package://unilab_arm_cr5/models/model.yaml",
        "provider": "unilab_arm_cr5:build_moveit_model",
        "upstream_repository": "https://github.com/Dobot-Arm/DOBOT_6Axis_ROS2_V4",
        "upstream_commit": "37730d08b08c74061ae10d4fa5565b4c4c914885",
        "upstream_xacro": "cra_description/urdf/cr5_robot.xacro",
    }
    assert contract["trajectory"] == {
        "source": "moveit",
        "execute_action": "/execute_trajectory",
    }
    assert contract["joint_display"]["source"] == "moveit_joint_states"
    assert contract["joint_display"]["topic"] == "/joint_states"
    assert contract["joint_display"]["joint_count"] == 6
    assert facade.platform_manifest["robot"]["jointsRigged"] is True
    assert len(facade.platform_manifest["robot"]["joints"]) == 6
