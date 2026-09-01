"""Validated UniLab facade over PlatformUI's existing 3D source of truth.

The facade deliberately separates two concerns:

* PlatformUI owns the detailed scene, device subtrees, payload meshes, rig and
  action-to-animation metadata.
* UniLab MoveIt remains the robot planning/execution authority and publishes
  the joint stream used for dynamic display.

No asset is copied and this module does not mutate or replace PlatformUI's 3D
runtime.  It only resolves pinned package-local files for Catalog adapters.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MANIFEST = _PACKAGE_ROOT / "three_d" / "unilab_facade.v1.yaml"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TEXT_ASSET_SUFFIXES = frozenset({".json", ".yaml", ".yml"})
_EXPECTED_NAMESPACES = frozenset(
    {
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
)


@dataclass(frozen=True, slots=True)
class AssetPin:
    """One package-local asset whose bytes match a pinned SHA-256."""

    name: str
    path: Path
    sha256: str
    media_type: str


@dataclass(frozen=True, slots=True)
class DeviceVisualBinding:
    """One proxy device's deterministic projection into the shared GLB."""

    action_namespace: str
    station_id: str | None
    glb_node: str | None
    manifest_section: str | None
    excluded_glb_nodes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MaterialVisualBinding:
    """One movable payload's scene node, home pose and tool-mount grip."""

    attachment_id: str
    node: str
    kind: str
    home_pose: Mapping[str, Any]
    tool_mount_grip: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ThreeDAssetFacade:
    """Fully validated, read-only 3D contract for the UniLab domain layer."""

    manifest_path: Path
    assets: Mapping[str, AssetPin]
    config: Mapping[str, Any]
    platform_manifest: Mapping[str, Any]
    payload_poses: Mapping[str, Any]
    payload_grips: Mapping[str, Any]
    provenance: Mapping[str, Any]

    def asset_path(self, name: str) -> Path:
        """Return a verified package-local asset path."""

        try:
            return self.assets[name].path
        except KeyError as error:
            raise KeyError(f"3D facade 未声明资产: {name}") from error

    def device_visual(self, action_namespace: str) -> DeviceVisualBinding:
        """Resolve one public action namespace to a shared-scene subtree."""

        key = str(action_namespace).strip()
        raw = _mapping(
            _mapping(self.config.get("device_visuals"), "device_visuals").get(key),
            f"device_visuals.{key}",
        )
        station_id = _optional_text(raw.get("station_id"))
        manifest_section = _optional_text(raw.get("manifest_section"))
        glb_node: str | None = None
        if station_id is not None:
            matches = [
                item
                for item in _sequence(self.platform_manifest.get("stations"), "stations")
                if _mapping(item, "station").get("id") == station_id
            ]
            if len(matches) != 1:
                raise ValueError(f"3D facade 工位选择不唯一: {station_id}")
            glb_node = _required_text(
                _mapping(matches[0], "station").get("glbNode"),
                f"station {station_id}.glbNode",
            )
        excluded_glb_nodes: list[str] = []
        excluded_station_ids = raw.get("exclude_station_ids", [])
        if not isinstance(excluded_station_ids, list):
            raise ValueError(f"device_visuals.{key}.exclude_station_ids 必须是数组")
        for excluded_station_id in excluded_station_ids:
            target = str(excluded_station_id or "").strip()
            matches = [
                item
                for item in _sequence(
                    self.platform_manifest.get("stations"), "stations"
                )
                if _mapping(item, "station").get("id") == target
            ]
            if len(matches) != 1:
                raise ValueError(f"3D facade 排除工位选择不唯一: {target}")
            excluded_glb_nodes.append(
                _required_text(
                    _mapping(matches[0], "station").get("glbNode"),
                    f"station {target}.glbNode",
                )
            )
        excluded_node_paths = raw.get("exclude_node_paths", [])
        if not isinstance(excluded_node_paths, list):
            raise ValueError(f"device_visuals.{key}.exclude_node_paths 必须是数组")
        for node_path in excluded_node_paths:
            excluded_glb_nodes.append(
                _required_text(
                    node_path,
                    f"device_visuals.{key}.exclude_node_paths",
                )
            )
        if len(excluded_glb_nodes) != len(set(excluded_glb_nodes)):
            raise ValueError(f"device_visuals.{key} 排除节点不得重复")
        return DeviceVisualBinding(
            key,
            station_id,
            glb_node,
            manifest_section,
            tuple(excluded_glb_nodes),
        )

    def material_visual(self, attachment_id: str) -> MaterialVisualBinding:
        """Resolve one PlatformUI payload without copying its geometry."""

        requested = str(attachment_id).strip()
        attachments = _sequence(
            self.platform_manifest.get(
                _required_text(
                    _mapping(self.config.get("materials"), "materials").get(
                        "attachment_collection"
                    ),
                    "materials.attachment_collection",
                )
            ),
            "material attachments",
        )
        matches = [
            _mapping(item, "attachment")
            for item in attachments
            if _mapping(item, "attachment").get("id") == requested
        ]
        if len(matches) != 1:
            raise KeyError(f"3D facade 未找到唯一物料挂载: {requested}")
        attachment = matches[0]
        payload = _mapping(attachment.get("payload"), f"attachment {requested}.payload")
        return MaterialVisualBinding(
            attachment_id=requested,
            node=_required_text(attachment.get("node"), f"attachment {requested}.node"),
            kind=_required_text(payload.get("kind"), f"attachment {requested}.kind"),
            home_pose=_mapping(
                self.payload_poses.get(requested), f"payload pose {requested}"
            ),
            tool_mount_grip=_mapping(
                self.payload_grips.get(requested), f"payload grip {requested}"
            ),
        )

    def moveit_model_contract(self) -> Mapping[str, Any]:
        """Return the external MoveIt model/trajectory/display contract."""

        motion = _mapping(self.config.get("motion"), "motion")
        return {
            "planning_authority": motion["planning_authority"],
            "model": dict(_mapping(motion.get("model"), "motion.model")),
            "trajectory": dict(
                _mapping(motion.get("trajectory"), "motion.trajectory")
            ),
            "joint_display": dict(
                _mapping(motion.get("joint_display"), "motion.joint_display")
            ),
        }


def load_three_d_asset_facade(
    manifest_path: str | Path | None = None,
) -> ThreeDAssetFacade:
    """Load and validate the pinned facade without importing UniLab or ROS."""

    path = Path(manifest_path or _DEFAULT_MANIFEST).resolve()
    raw = _yaml_mapping(path)
    if raw.get("schema") != "unilab.ptlc-three-d-facade/v1":
        raise ValueError("3D facade schema 必须是 unilab.ptlc-three-d-facade/v1")
    if raw.get("package") != "eit_ptlc":
        raise ValueError("3D facade package 必须是 eit_ptlc")

    assets: dict[str, AssetPin] = {}
    for name, value in _mapping(raw.get("assets"), "assets").items():
        item = _mapping(value, f"assets.{name}")
        digest = _required_text(item.get("sha256"), f"assets.{name}.sha256")
        if _DIGEST.fullmatch(digest) is None:
            raise ValueError(f"3D facade 资产摘要非法: {name}")
        asset_path = _resolve_package_path(
            path.parent,
            _required_text(item.get("path"), f"assets.{name}.path"),
        )
        if _sha256(asset_path) != digest:
            raise ValueError(f"3D facade 资产摘要漂移: {name}")
        assets[str(name)] = AssetPin(
            name=str(name),
            path=asset_path,
            sha256=digest,
            media_type=_required_text(
                item.get("media_type"), f"assets.{name}.media_type"
            ),
        )

    required_assets = {
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
    missing_assets = sorted(required_assets - set(assets))
    if missing_assets:
        raise ValueError("3D facade 缺少资产: " + ", ".join(missing_assets))

    platform_manifest = _json_mapping(assets["scene_manifest"].path)
    pose_document = _json_mapping(assets["payload_poses"].path)
    grip_document = _json_mapping(assets["payload_grips"].path)
    provenance = _yaml_mapping(assets["provenance"].path)
    poses = _mapping(pose_document.get("poses"), "payload poses")
    grips = _mapping(grip_document.get("grips"), "payload grips")

    facade = ThreeDAssetFacade(
        manifest_path=path,
        assets=assets,
        config=raw,
        platform_manifest=platform_manifest,
        payload_poses=poses,
        payload_grips=grips,
        provenance=provenance,
    )
    _validate_platform_contract(facade)
    return facade


def _validate_platform_contract(facade: ThreeDAssetFacade) -> None:
    if facade.platform_manifest.get("version") != 2:
        raise ValueError("PlatformUI 3D manifest 必须是 version 2")
    units = _mapping(facade.platform_manifest.get("units"), "scene units")
    if units.get("sceneUnit") != "m":
        raise ValueError("PlatformUI 3D sceneUnit 必须是 m")

    configured_namespaces = set(
        _mapping(facade.config.get("device_visuals"), "device_visuals")
    )
    if configured_namespaces != _EXPECTED_NAMESPACES:
        raise ValueError("3D facade 必须恰好覆盖 11 个 PlatformUI 动作命名空间")
    for namespace in sorted(configured_namespaces):
        binding = facade.device_visual(namespace)
        selectors = int(binding.station_id is not None) + int(
            binding.manifest_section is not None
        )
        if selectors != 1:
            raise ValueError(f"3D facade 设备必须只有一个选择器: {namespace}")
        if binding.manifest_section is not None:
            _mapping(
                facade.platform_manifest.get(binding.manifest_section),
                f"scene manifest section {binding.manifest_section}",
            )

    robot = _mapping(facade.platform_manifest.get("robot"), "scene robot")
    joints = _sequence(robot.get("joints"), "scene robot.joints")
    if robot.get("jointsRigged") is not True or len(joints) != 6:
        raise ValueError("PlatformUI CR5 必须保持完整六关节 rig")
    if [_mapping(item, "robot joint").get("id") for item in joints] != [
        "J1",
        "J2",
        "J3",
        "J4",
        "J5",
        "J6",
    ]:
        raise ValueError("PlatformUI CR5 关节顺序必须是 J1..J6")

    motion = _mapping(facade.config.get("motion"), "motion")
    model = _mapping(motion.get("model"), "motion.model")
    trajectory = _mapping(motion.get("trajectory"), "motion.trajectory")
    joint_display = _mapping(motion.get("joint_display"), "motion.joint_display")
    static_scene = _mapping(motion.get("static_scene"), "motion.static_scene")
    kinematics = _mapping(robot.get("kinematicsSource"), "scene robot.kinematicsSource")
    if (
        motion.get("planning_authority") != "moveit"
        or model.get("type") != "package_moveit"
        or model.get("format") != "urdf"
        or model.get("provider") != "unilab_arm_cr5:build_moveit_model"
        or model.get("upstream_commit") != kinematics.get("commit")
        or model.get("upstream_xacro") != kinematics.get("xacro")
        or trajectory.get("source") != "moveit"
        or trajectory.get("execute_action") != "/execute_trajectory"
        or joint_display.get("source") != "moveit_joint_states"
        or joint_display.get("topic") != "/joint_states"
        or joint_display.get("joint_count") != 6
        or static_scene.get("supplies_motion_authority") is not False
        or static_scene.get("robot_articulation")
        != "joint_state_projection_only"
    ):
        raise ValueError("3D facade 不得用静态 GLB 替代 MoveIt 轨迹或关节显示")

    materials = _mapping(facade.config.get("materials"), "materials")
    for field in ("follow_runtime", "pick_controller"):
        _resolve_package_path(
            facade.manifest_path.parent.parent,
            _required_text(materials.get(field), f"materials.{field}"),
        )
    attachments = _sequence(
        facade.platform_manifest.get(
            _required_text(
                materials.get("attachment_collection"),
                "materials.attachment_collection",
            )
        ),
        "material attachments",
    )
    attachment_ids = {
        _required_text(_mapping(item, "attachment").get("id"), "attachment.id")
        for item in attachments
    }
    if not attachment_ids:
        raise ValueError("PlatformUI 3D manifest 未声明可搬运物料")
    missing_poses = sorted(attachment_ids - set(facade.payload_poses))
    missing_grips = sorted(attachment_ids - set(facade.payload_grips))
    if missing_poses or missing_grips:
        raise ValueError(
            "PlatformUI 物料缺少位姿/夹持数据: "
            + ", ".join(missing_poses + missing_grips)
        )
    for attachment_id in sorted(attachment_ids):
        facade.material_visual(attachment_id)

    catalog = _mapping(facade.config.get("catalog"), "catalog")
    if (
        catalog.get("shared_scene_template") != "ptlc_shared_scene"
        or catalog.get("shared_scene_model_ref") != "ptlc_shared_scene"
        or catalog.get("entry") != "models/machine.official-cr5.glb"
        or catalog.get("format") != "glb"
        or catalog.get("instance_mode") != "clone_subtree"
    ):
        raise ValueError("3D facade Catalog 必须复用唯一共享 GLB")
    _resolve_package_path(
        facade.manifest_path.parent,
        _required_text(catalog.get("declaration"), "catalog.declaration"),
    )
    if _resolve_package_path(
        facade.manifest_path.parent,
        _required_text(catalog.get("entry"), "catalog.entry"),
    ) != facade.asset_path("scene"):
        raise ValueError("3D facade Catalog entry 必须指向已 pin 的共享 GLB")
    graph_entities = _mapping(facade.config.get("graph_entities"), "graph_entities")
    device_rules = _mapping(graph_entities.get("devices"), "graph_entities.devices")
    resource_rules = _mapping(graph_entities.get("resources"), "graph_entities.resources")
    if set(device_rules) != {
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
    } or set(resource_rules) != {
        "ptlc_source_sample_vial",
        "ptlc_plate",
        "ptlc_collector_rack",
        "ptlc_vial_rack",
        "ptlc_powder_collector",
        "ptlc_collection_vial",
    }:
        raise ValueError("3D facade graph_entities 必须覆盖领域包全部设备与物料")

    provenance = facade.provenance
    if (
        provenance.get("schema") != "unilab.ptlc-three-d-provenance/v1"
        or provenance.get("package") != "eit_ptlc"
    ):
        raise ValueError("3D provenance schema/package 非法")
    gaps = _sequence(provenance.get("gaps"), "provenance.gaps")
    gap_ids = {
        _required_text(_mapping(item, "provenance gap").get("id"), "gap.id")
        for item in gaps
    }
    if gap_ids != {"exact_part_for_scene_selector", "procedural_plate_part_file"}:
        raise ValueError("3D provenance 必须显式声明已知零件溯源缺口")
    source = _mapping(provenance.get("source"), "provenance.source")
    pipeline = _mapping(provenance.get("pipeline"), "provenance.pipeline")
    evidence_files = [
        _required_text(source.get("declaration"), "provenance.source.declaration"),
        _required_text(pipeline.get("config"), "provenance.pipeline.config"),
        _required_text(pipeline.get("rig"), "provenance.pipeline.rig"),
        _required_text(pipeline.get("final_scene"), "provenance.pipeline.final_scene"),
        _required_text(
            pipeline.get("final_manifest"), "provenance.pipeline.final_manifest"
        ),
        *(
            _required_text(value, "provenance.pipeline.stage")
            for value in _sequence(
                pipeline.get("stages"), "provenance.pipeline.stages"
            )
        ),
    ]
    for reference in evidence_files:
        _resolve_package_path(facade.manifest_path.parent, reference)


def _resolve_package_path(base: Path, reference: str) -> Path:
    candidate = (base / reference).resolve()
    try:
        candidate.relative_to(_PACKAGE_ROOT)
    except ValueError as error:
        raise ValueError(f"3D facade 资产越出 eit_ptlc 包: {reference}") from error
    if not candidate.is_file():
        raise ValueError(f"3D facade 资产不存在: {reference}")
    return candidate


def _sha256(path: Path) -> str:
    """计算可跨 Git 换行策略复现的资产摘要。

    JSON/YAML 的锁定值按仓库 LF 字节生成；Windows checkout 可能把同一文本改成
    CRLF，语义未变却会误报漂移。文本先归一换行，GLB 等二进制仍逐字节严格校验。
    """

    content = path.read_bytes()
    if path.suffix.lower() in _TEXT_ASSET_SUFFIXES:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def _yaml_mapping(path: Path) -> Mapping[str, Any]:
    return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))


def _json_mapping(path: Path) -> Mapping[str, Any]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} 必须是对象")
    return value


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是数组")
    return value


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} 不能为空")
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
