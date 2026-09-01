"""Compile a UniLab physical graph into independently instantiable 3D entities.

The compiler is deliberately descriptive: it neither starts ROS nor renders
Three.js.  Its output is the stable boundary consumed by either runtime.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .facade import ThreeDAssetFacade, load_three_d_asset_facade
from .gltf_index import (
    GltfNodeRecord,
    Matrix4,
    graph_pose_matrix,
    load_gltf_scene_index,
    multiply_matrix,
)

_SLOT = re.compile(r"^(?P<prefix>.+?)(?P<index>[1-9][0-9]*)$")


@dataclass(frozen=True, slots=True)
class SceneEntity:
    graph_id: str
    graph_class: str
    graph_type: str
    parent_id: str | None
    children: tuple[str, ...]
    local_matrix: Matrix4
    world_matrix: Matrix4
    model: Mapping[str, Any]
    selector: Mapping[str, Any]
    attachment: Mapping[str, Any] | None
    provenance: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "graph_class": self.graph_class,
            "graph_type": self.graph_type,
            "parent_id": self.parent_id,
            "children": list(self.children),
            "local_matrix": _matrix_json(self.local_matrix),
            "world_matrix": _matrix_json(self.world_matrix),
            "model": dict(self.model),
            "selector": dict(self.selector),
            "attachment": dict(self.attachment) if self.attachment is not None else None,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True, slots=True)
class CompiledSceneGraph:
    schema: str
    graph_source: str | None
    asset_path: Path
    asset_sha256: str
    entities: Mapping[str, SceneEntity]
    root_ids: tuple[str, ...]
    shared_asset_loads: tuple[Path, ...]
    motion: Mapping[str, Any]
    provenance_gaps: tuple[Mapping[str, Any], ...]

    def entity(self, graph_id: str) -> SceneEntity:
        try:
            return self.entities[graph_id]
        except KeyError as error:
            raise KeyError(f"scene graph 不存在实体: {graph_id}") from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "graph_source": self.graph_source,
            "asset": {
                "path": str(self.asset_path),
                "sha256": self.asset_sha256,
                "load_count": len(self.shared_asset_loads),
            },
            "root_ids": list(self.root_ids),
            "entities": {
                graph_id: entity.to_dict()
                for graph_id, entity in self.entities.items()
            },
            "motion": dict(self.motion),
            "provenance_gaps": [dict(item) for item in self.provenance_gaps],
        }


def compile_graph_scene(
    graph: str | Path | Mapping[str, Any],
    *,
    facade: ThreeDAssetFacade | None = None,
) -> CompiledSceneGraph:
    """Compile and validate all device/resource/submaterial scene entities."""

    active_facade = facade or load_three_d_asset_facade()
    document, graph_source = _graph_document(graph)
    nodes = _graph_nodes(document)
    parents = _graph_parents(nodes)
    children = _validate_children(nodes, parents)
    local_matrices = {graph_id: graph_pose_matrix(node) for graph_id, node in nodes.items()}
    world_matrices = _world_matrices(local_matrices, parents)

    gltf = load_gltf_scene_index(active_facade.asset_path("scene"))
    _validate_graph_anchors(nodes, world_matrices, gltf)
    tool_mount = _unique_suffix_node(gltf, "/TOOL_MOUNT")
    graph_rules = _mapping(active_facade.config.get("graph_entities"), "graph_entities")
    device_rules = _mapping(graph_rules.get("devices"), "graph_entities.devices")
    resource_rules = _mapping(graph_rules.get("resources"), "graph_entities.resources")
    shared_ref = _required_text(
        _mapping(active_facade.config.get("catalog"), "catalog").get(
            "shared_scene_model_ref"
        ),
        "catalog.shared_scene_model_ref",
    )
    scene_pin = active_facade.assets["scene"]

    entities: dict[str, SceneEntity] = {}
    for graph_id, node in nodes.items():
        class_name = _class_id(node)
        node_type = _required_text(node.get("type"), f"graph.{graph_id}.type")
        rules = device_rules if node_type == "device" else resource_rules
        rule = _mapping(rules.get(class_name), f"graph_entities rule {class_name}")
        kind = _required_text(rule.get("kind"), f"rule {class_name}.kind")
        model, selector, attachment, lineage_gap = _resolve_entity_model(
            graph_id=graph_id,
            node=node,
            nodes=nodes,
            parents=parents,
            rule=rule,
            kind=kind,
            shared_ref=shared_ref,
            facade=active_facade,
            gltf=gltf,
            tool_mount_path=tool_mount.path,
        )
        provenance = _entity_provenance(
            facade=active_facade,
            graph_id=graph_id,
            node=node,
            selector=selector,
            lineage_gap=lineage_gap,
        )
        entities[graph_id] = SceneEntity(
            graph_id=graph_id,
            graph_class=_required_text(node.get("class"), f"graph.{graph_id}.class"),
            graph_type=node_type,
            parent_id=parents[graph_id],
            children=children[graph_id],
            local_matrix=local_matrices[graph_id],
            world_matrix=world_matrices[graph_id],
            model=MappingProxyType(model),
            selector=MappingProxyType(selector),
            attachment=MappingProxyType(attachment) if attachment is not None else None,
            provenance=MappingProxyType(provenance),
        )

    _validate_entity_hierarchy(entities, gltf)
    _validate_exclusive_subtrees(entities, gltf)
    return CompiledSceneGraph(
        schema="unilab.ptlc-compiled-scene/v1",
        graph_source=graph_source,
        asset_path=scene_pin.path,
        asset_sha256=scene_pin.sha256,
        entities=MappingProxyType(entities),
        root_ids=tuple(graph_id for graph_id, parent in parents.items() if parent is None),
        shared_asset_loads=(scene_pin.path,),
        motion=MappingProxyType(dict(active_facade.moveit_model_contract())),
        provenance_gaps=tuple(
            MappingProxyType(dict(_mapping(item, "provenance gap")))
            for item in _sequence(active_facade.provenance.get("gaps"), "provenance.gaps")
        ),
    )


def _resolve_entity_model(
    *,
    graph_id: str,
    node: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    parents: Mapping[str, str | None],
    rule: Mapping[str, Any],
    kind: str,
    shared_ref: str,
    facade: ThreeDAssetFacade,
    gltf: Any,
    tool_mount_path: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str | None]:
    model = {
        "$ref": shared_ref,
        "asset_sha256": facade.assets["scene"].sha256,
        "instance_id": graph_id,
        "instance_mode": "clone_subtree",
    }
    attachment: dict[str, Any] | None = None
    lineage_gap: str | None = "exact_part_for_scene_selector"

    if kind in {"gltf_subtree", "moveit_with_gltf_projection"}:
        namespace = _required_text(rule.get("namespace"), f"rule {graph_id}.namespace")
        binding = facade.device_visual(namespace)
        record = gltf.resolve(_required_text(binding.glb_node, f"{namespace}.glb_node"))
        selector = _gltf_selector(
            record,
            excluded_node_paths=binding.excluded_glb_nodes,
        )
        if kind == "moveit_with_gltf_projection":
            model = {
                "type": "package_moveit",
                "provider": "unilab_arm_cr5:build_moveit_model",
                "source_digest": "8c8b9ea935fd83122b19b572c84d107e81b4864d4310c94d0906cc361e7631c2",
                "display_projection": model,
                "motion_authority": "moveit",
            }
            selector["articulation"] = "joint_state_projection_only"
        return model, selector, None, lineage_gap

    if kind == "logical_manifest_section":
        namespace = _required_text(rule.get("namespace"), f"rule {graph_id}.namespace")
        binding = facade.device_visual(namespace)
        selector = {
            "kind": "logical_manifest_section",
            "manifest_section": binding.manifest_section,
            "geometry": False,
        }
        model["instance_mode"] = "logical_projection"
        return model, selector, None, None

    if kind == "procedural_plate":
        inventory_key = _required_text(rule.get("anchor_inventory"), "plate.anchor_inventory")
        anchor_id = _required_text(rule.get("anchor_id"), "plate.anchor_id")
        inventory = _mapping(facade.platform_manifest.get("inventory"), "inventory")
        candidates = [
            _mapping(item, "inventory anchor")
            for item in _sequence(inventory.get(inventory_key), f"inventory.{inventory_key}")
            if _mapping(item, "inventory anchor").get("id") == anchor_id
        ]
        if len(candidates) != 1:
            raise ValueError(f"pTLC plate 锚点不唯一: {anchor_id}")
        record = gltf.resolve(_required_text(candidates[0].get("node"), "plate anchor.node"))
        source_module = _validated_package_file(
            facade,
            _required_text(rule.get("source_module"), "plate.source_module"),
        )
        state_module = _validated_package_file(
            facade,
            _required_text(rule.get("state_module"), "plate.state_module"),
        )
        geometry_module = _validated_package_file(
            facade,
            _required_text(rule.get("geometry_module"), "plate.geometry_module"),
        )
        selector = _gltf_selector(record)
        selector.update(
            {
                "kind": "procedural_plate",
                "provider": {
                    "kind": _required_text(
                        rule.get("provider_kind"), "plate.provider_kind"
                    ),
                    "source_module": source_module,
                    "state_module": state_module,
                    "geometry_module": geometry_module,
                },
                "anchor_id": anchor_id,
                "plate_state": _mapping(node.get("data"), f"graph.{graph_id}.data").get(
                    "plate_state", "blank"
                ),
            }
        )
        model["instance_mode"] = "procedural_child"
        return model, selector, None, _required_text(
            rule.get("part_lineage_gap"), "plate.part_lineage_gap"
        )

    attachment_id = _attachment_id_for_rule(
        graph_id=graph_id,
        node=node,
        nodes=nodes,
        parents=parents,
        rule=rule,
        kind=kind,
    )
    visual = facade.material_visual(attachment_id)
    record = gltf.resolve(visual.node)
    excluded_attachment_ids = rule.get("exclude_attachment_ids", [])
    if not isinstance(excluded_attachment_ids, list):
        raise ValueError(f"rule {graph_id}.exclude_attachment_ids 必须是数组")
    excluded_node_paths = tuple(
        facade.material_visual(
            _required_text(value, f"rule {graph_id}.exclude_attachment_id")
        ).node
        for value in excluded_attachment_ids
    )
    selector = _gltf_selector(
        record,
        excluded_node_paths=excluded_node_paths,
    )
    selector.update({"kind": "gltf_attachment", "attachment_id": attachment_id})
    payload = next(
        _mapping(item, "attachment")
        for item in _sequence(facade.platform_manifest.get("attachments"), "attachments")
        if _mapping(item, "attachment").get("id") == attachment_id
    )
    attachment = {
        "attachment_id": attachment_id,
        "payload_kind": visual.kind,
        "home": {
            "asset_parent_path": _parent_path(record.path),
            "pose": dict(visual.home_pose),
        },
        "graph_parent": {
            "graph_id": parents[graph_id],
            "pose_authority": "graph_local_matrix",
        },
        "robot": {
            "node_path": tool_mount_path,
            "grip": dict(visual.tool_mount_grip),
            "mount_local": dict(
                _mapping(_mapping(payload.get("payload"), "payload").get("mountLocal"), "mountLocal")
            ),
        },
        "follow_policy": "exclusive_parent_switch",
        "runtime": {
            "follow": _validated_package_file(
                facade,
                _required_text(
                    _mapping(facade.config.get("materials"), "materials").get(
                        "follow_runtime"
                    ),
                    "materials.follow_runtime",
                ),
            ),
            "pick_controller": _validated_package_file(
                facade,
                _required_text(
                    _mapping(facade.config.get("materials"), "materials").get(
                        "pick_controller"
                    ),
                    "materials.pick_controller",
                ),
            ),
        },
        "states": ["home", "graph_parent", "tool_mount"],
    }
    return model, selector, attachment, lineage_gap


def _attachment_id_for_rule(
    *,
    graph_id: str,
    node: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    parents: Mapping[str, str | None],
    rule: Mapping[str, Any],
    kind: str,
) -> str:
    data = _mapping(node.get("data"), f"graph.{graph_id}.data")
    explicit = str(data.get("platformui_attachment_id") or "").strip()
    if explicit:
        return explicit
    if kind == "gltf_attachment":
        return _required_text(rule.get("attachment_id"), f"rule {graph_id}.attachment_id")
    if kind == "gltf_attachment_by_site":
        site = _required_text(data.get("platformui_site"), f"graph.{graph_id}.platformui_site")
        return _required_text(
            _mapping(rule.get("site_map"), f"rule {graph_id}.site_map").get(site),
            f"site attachment {site}",
        )
    if kind == "gltf_attachment_by_parent_site":
        parent_id = parents[graph_id]
        if parent_id is None:
            raise ValueError(f"物料 {graph_id} 必须有父资源")
        site = _occupied_site(nodes[parent_id], graph_id)
        prefix = _required_text(rule.get("site_prefix"), f"rule {graph_id}.site_prefix")
        match = _SLOT.fullmatch(site)
        if match is None or match.group("prefix") != prefix:
            raise ValueError(f"物料 {graph_id} 父 Site 不符合 {prefix}N: {site}")
        return _required_text(
            rule.get("attachment_prefix"), f"rule {graph_id}.attachment_prefix"
        ) + match.group("index")
    raise ValueError(f"不支持的 scene entity kind: {kind}")


def _gltf_selector(
    record: GltfNodeRecord,
    *,
    excluded_node_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not record.subtree_mesh_indices:
        raise ValueError(f"GLB selector 没有可实例化 mesh: {record.path}")
    return {
        "kind": "gltf_subtree",
        "node_path": record.path,
        "node_index": record.index,
        "mesh_index": record.mesh_index,
        "subtree_mesh_indices": list(record.subtree_mesh_indices),
        "exclude_node_paths": list(excluded_node_paths),
        "asset_local_matrix": _matrix_json(record.local_matrix),
        "asset_world_matrix": _matrix_json(record.world_matrix),
    }


def _entity_provenance(
    *,
    facade: ThreeDAssetFacade,
    graph_id: str,
    node: Mapping[str, Any],
    selector: Mapping[str, Any],
    lineage_gap: str | None,
) -> dict[str, Any]:
    source = _mapping(facade.provenance.get("source"), "provenance.source")
    export = _mapping(
        _mapping(facade.provenance.get("export"), "provenance.export").get("preferred"),
        "provenance.export.preferred",
    )
    gaps = {
        _required_text(_mapping(item, "gap").get("id"), "gap.id"): _mapping(item, "gap")
        for item in _sequence(facade.provenance.get("gaps"), "provenance.gaps")
    }
    part = (
        {"status": "not_applicable", "reason": "logical entity has no geometry"}
        if lineage_gap is None
        else {
            "status": "gap",
            "gap_id": lineage_gap,
            "reason": _required_text(gaps[lineage_gap].get("reason"), f"gap {lineage_gap}.reason"),
        }
    )
    result = {
        "graph_entity": graph_id,
        "cad_assembly": _required_text(source.get("assembly"), "source.assembly"),
        "cad_repository_presence": source.get("repository_presence"),
        "export_artifact": _required_text(export.get("artifact"), "export.artifact"),
        "final_glb": str(facade.asset_path("scene")),
        "final_glb_sha256": facade.assets["scene"].sha256,
        "selector": {
            key: selector[key]
            for key in ("kind", "node_path", "node_index", "subtree_mesh_indices")
            if key in selector
        },
        "solidworks_part": part,
    }
    data = _mapping(node.get("data"), f"graph.{graph_id}.data")
    graph_anchor = str(data.get("platformui_glb_anchor") or "").strip()
    if graph_anchor:
        result["graph_pose"] = {
            "coordinate_authority": _required_text(
                data.get("coordinate_authority"),
                f"graph.{graph_id}.data.coordinate_authority",
            ),
            "glb_anchor": graph_anchor,
            "conversion": "graph_mm=[gltf_x,-gltf_z,gltf_y]*1000",
        }
    return result


def _graph_document(graph: str | Path | Mapping[str, Any]) -> tuple[Mapping[str, Any], str | None]:
    if isinstance(graph, Mapping):
        return graph, None
    path = Path(graph).resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 UniLab physical graph: {path}") from error
    return _mapping(value, str(path)), str(path)


def _graph_nodes(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw_nodes = _sequence(document.get("nodes"), "graph.nodes")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in raw_nodes:
        node = _mapping(raw, "graph node")
        graph_id = _required_text(node.get("id"), "graph node.id")
        if graph_id in result:
            raise ValueError(f"physical graph 节点 id 重复: {graph_id}")
        result[graph_id] = node
    if not result:
        raise ValueError("physical graph 不能为空")
    return result


def _graph_parents(nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, str | None]:
    by_uuid: dict[str, str] = {}
    for graph_id, node in nodes.items():
        uuid = str(node.get("uuid") or "").strip()
        if uuid:
            if uuid in by_uuid:
                raise ValueError(f"physical graph uuid 重复: {uuid}")
            by_uuid[uuid] = graph_id
    result: dict[str, str | None] = {}
    for graph_id, node in nodes.items():
        resolved: str | None = None
        for raw in (node.get("parent"), node.get("parent_uuid")):
            token = str(raw or "").strip()
            if not token:
                continue
            candidate = token if token in nodes else by_uuid.get(token)
            if candidate is None:
                raise ValueError(f"physical graph 父节点不存在: {token}")
            if resolved is not None and resolved != candidate:
                raise ValueError(f"physical graph parent/parent_uuid 冲突: {graph_id}")
            resolved = candidate
        result[graph_id] = resolved
    return result


def _validate_children(
    nodes: Mapping[str, Mapping[str, Any]], parents: Mapping[str, str | None]
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for graph_id, node in nodes.items():
        raw = node.get("children", [])
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise ValueError(f"physical graph children 非法: {graph_id}")
        children = tuple(raw)
        if len(set(children)) != len(children):
            raise ValueError(f"physical graph children 重复: {graph_id}")
        for child in children:
            if child not in nodes or parents[child] != graph_id:
                raise ValueError(f"physical graph parent/children 不对称: {graph_id}/{child}")
        expected = {child for child, parent in parents.items() if parent == graph_id}
        if set(children) != expected:
            raise ValueError(f"physical graph children 未完整声明: {graph_id}")
        result[graph_id] = children
    return result


def _world_matrices(
    local: Mapping[str, Matrix4], parents: Mapping[str, str | None]
) -> dict[str, Matrix4]:
    result: dict[str, Matrix4] = {}
    visiting: set[str] = set()

    def resolve(graph_id: str) -> Matrix4:
        if graph_id in result:
            return result[graph_id]
        if graph_id in visiting:
            raise ValueError("physical graph 父子关系存在环")
        visiting.add(graph_id)
        parent = parents[graph_id]
        value = local[graph_id] if parent is None else multiply_matrix(resolve(parent), local[graph_id])
        visiting.remove(graph_id)
        result[graph_id] = value
        return value

    for graph_id in local:
        resolve(graph_id)
    return result


def _validate_graph_anchors(
    nodes: Mapping[str, Mapping[str, Any]],
    world_matrices: Mapping[str, Matrix4],
    gltf: Any,
) -> None:
    """Prove graph translations are projections of exact GLB world anchors.

    PlatformUI/Three.js consumes the GLB as Y-up metres; the physical graph is
    Z-up millimetres.  The subtree selector retains the selected root's GLB
    rotation and scale, so only translation belongs in the graph pose.
    """

    expected_authority = "machine.official-cr5.glb#world_matrix"
    for graph_id, node in nodes.items():
        data = _mapping(node.get("data"), f"graph.{graph_id}.data")
        anchor_path = str(data.get("platformui_glb_anchor") or "").strip()
        if not anchor_path:
            continue
        authority = _required_text(
            data.get("coordinate_authority"),
            f"graph.{graph_id}.data.coordinate_authority",
        )
        if authority != expected_authority:
            raise ValueError(
                f"graph {graph_id} 坐标权威必须是 {expected_authority}: {authority}"
            )
        anchor = gltf.resolve(anchor_path)
        gltf_x = anchor.world_matrix[0][3]
        gltf_y = anchor.world_matrix[1][3]
        gltf_z = anchor.world_matrix[2][3]
        expected = (gltf_x, -gltf_z, gltf_y)
        actual = tuple(world_matrices[graph_id][axis][3] for axis in range(3))
        if any(abs(left - right) > 1e-6 for left, right in zip(actual, expected)):
            raise ValueError(
                f"graph {graph_id} 坐标未对齐 GLB anchor {anchor_path}: "
                f"actual={actual}, expected={expected}"
            )


def _validate_entity_hierarchy(entities: Mapping[str, SceneEntity], gltf: Any) -> None:
    for entity in entities.values():
        node_path = entity.selector.get("node_path")
        excluded_paths = entity.selector.get("exclude_node_paths", [])
        if not isinstance(excluded_paths, list) or any(
            not isinstance(item, str) for item in excluded_paths
        ):
            raise ValueError(f"scene entity {entity.graph_id} 排除节点必须是字符串数组")
        if len(excluded_paths) != len(set(excluded_paths)):
            raise ValueError(f"scene entity {entity.graph_id} 排除节点不得重复")
        if isinstance(node_path, str):
            for excluded_path in excluded_paths:
                gltf.resolve(excluded_path)
                if not gltf.is_descendant(excluded_path, node_path):
                    raise ValueError(
                        f"scene entity {entity.graph_id} 只能排除 selector 的后代: "
                        f"{excluded_path}"
                    )
        if entity.parent_id is None:
            continue
        parent = entities[entity.parent_id]
        child_path = entity.selector.get("node_path")
        parent_path = parent.selector.get("node_path")
        if isinstance(child_path, str) and isinstance(parent_path, str):
            is_asset_descendant = gltf.is_descendant(child_path, parent_path)
            expected = is_asset_descendant
            # Independent source templates (for example a sample vial cloned
            # from COLLECT into SAMPLING) are intentionally graph-reparented.
            if not expected and entity.attachment is None and entity.selector.get("kind") != "procedural_plate":
                raise ValueError(
                    f"scene entity {entity.graph_id} 既非 GLB 子树也没有可重挂载合同"
                )


def _validate_exclusive_subtrees(
    entities: Mapping[str, SceneEntity], gltf: Any
) -> None:
    """Reject two independently rendered entities that retain the same GLB subtree."""

    geometric = [
        entity
        for entity in entities.values()
        if isinstance(entity.selector.get("node_path"), str)
    ]
    for ancestor in geometric:
        ancestor_path = str(ancestor.selector["node_path"])
        excluded = tuple(ancestor.selector.get("exclude_node_paths", []))
        for child in geometric:
            if child.graph_id == ancestor.graph_id:
                continue
            child_path = str(child.selector["node_path"])
            if not gltf.is_descendant(child_path, ancestor_path):
                continue
            removed = any(
                child_path == exclusion
                or gltf.is_descendant(child_path, exclusion)
                for exclusion in excluded
            )
            if not removed:
                raise ValueError(
                    f"GLB 子树重复实例化: {ancestor.graph_id} 保留了 "
                    f"{child.graph_id} 的 {child_path}"
                )


def _occupied_site(parent: Mapping[str, Any], child_id: str) -> str:
    config = _mapping(parent.get("config"), f"parent {parent.get('id')}.config")
    matches = [
        _mapping(site, "site")
        for site in _sequence(config.get("sites"), "parent sites")
        if _mapping(site, "site").get("occupied_by") == child_id
    ]
    if len(matches) != 1:
        raise ValueError(f"父资源必须恰好一个 Site 占用 {child_id}")
    return _required_text(matches[0].get("label") or matches[0].get("name"), "site label")


def _class_id(node: Mapping[str, Any]) -> str:
    return _required_text(node.get("class"), "graph node.class").rsplit(".", 1)[-1]


def _unique_suffix_node(gltf: Any, suffix: str) -> GltfNodeRecord:
    matches = [path for path in gltf.paths if path.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"GLB 后缀 selector 不唯一: {suffix}")
    return gltf.resolve(matches[0])


def _parent_path(path: str) -> str | None:
    return path.rsplit("/", 1)[0] if "/" in path else None


def _validated_package_file(facade: ThreeDAssetFacade, reference: str) -> str:
    package_root = facade.manifest_path.parent.parent.resolve()
    candidate = (package_root / reference).resolve()
    try:
        candidate.relative_to(package_root)
    except ValueError as error:
        raise ValueError(f"程序化模型来源越出 eit_ptlc 包: {reference}") from error
    if not candidate.is_file():
        raise ValueError(f"程序化模型来源不存在: {reference}")
    return candidate.relative_to(package_root).as_posix()


def _matrix_json(matrix: Matrix4) -> list[list[float]]:
    return [list(row) for row in matrix]


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


__all__ = ["CompiledSceneGraph", "SceneEntity", "compile_graph_scene"]
