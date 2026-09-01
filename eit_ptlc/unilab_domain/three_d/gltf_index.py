"""Small, dependency-free index over a binary glTF scene.

The index keeps exact node paths, node/mesh identities and both local/world
matrices.  It does not render or rewrite the GLB.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

Matrix4 = tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True, slots=True)
class GltfNodeRecord:
    index: int
    name: str
    path: str
    parent_index: int | None
    child_indices: tuple[int, ...]
    mesh_index: int | None
    subtree_mesh_indices: tuple[int, ...]
    local_matrix: Matrix4
    world_matrix: Matrix4

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "path": self.path,
            "parent_index": self.parent_index,
            "child_indices": list(self.child_indices),
            "mesh_index": self.mesh_index,
            "subtree_mesh_indices": list(self.subtree_mesh_indices),
            "local_matrix": [list(row) for row in self.local_matrix],
            "world_matrix": [list(row) for row in self.world_matrix],
        }


@dataclass(frozen=True, slots=True)
class GltfSceneIndex:
    asset_path: Path
    nodes: tuple[GltfNodeRecord, ...]
    paths: Mapping[str, int]
    scene_roots: tuple[int, ...]

    def resolve(self, path: str) -> GltfNodeRecord:
        try:
            return self.nodes[self.paths[path]]
        except KeyError as error:
            raise KeyError(f"GLB 中不存在精确节点路径: {path}") from error

    def is_descendant(self, child_path: str, ancestor_path: str) -> bool:
        child = self.resolve(child_path)
        ancestor = self.resolve(ancestor_path)
        cursor = child.parent_index
        while cursor is not None:
            if cursor == ancestor.index:
                return True
            cursor = self.nodes[cursor].parent_index
        return False


def load_gltf_scene_index(path: str | Path) -> GltfSceneIndex:
    """Read only the JSON chunk and build a deterministic hierarchy index."""

    asset_path = Path(path).resolve()
    document = _read_glb_json(asset_path)
    raw_nodes = document.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("GLB 必须包含非空 nodes")
    nodes = [_mapping(item, f"nodes[{index}]") for index, item in enumerate(raw_nodes)]
    parent_by_child: dict[int, int] = {}
    for parent_index, node in enumerate(nodes):
        for raw_child in _indices(node.get("children"), len(nodes), "children"):
            if raw_child in parent_by_child:
                raise ValueError(f"GLB 节点 {raw_child} 存在多个父节点")
            parent_by_child[raw_child] = parent_index

    scene_roots = _scene_roots(document, len(nodes), parent_by_child)
    path_by_index: dict[int, str] = {}
    world_by_index: dict[int, Matrix4] = {}
    visiting: set[int] = set()

    def visit(index: int) -> None:
        if index in path_by_index:
            return
        if index in visiting:
            raise ValueError("GLB 节点层级存在环")
        visiting.add(index)
        node = nodes[index]
        parent = parent_by_child.get(index)
        if parent is not None:
            visit(parent)
        name = str(node.get("name") or f"__node_{index}")
        local = _node_matrix(node)
        if parent is None:
            node_path = name
            world = local
        else:
            node_path = f"{path_by_index[parent]}/{name}"
            world = multiply_matrix(world_by_index[parent], local)
        path_by_index[index] = node_path
        world_by_index[index] = world
        visiting.remove(index)

    for node_index in range(len(nodes)):
        visit(node_index)
    paths: dict[str, int] = {}
    for node_index, node_path in path_by_index.items():
        if node_path in paths:
            raise ValueError(f"GLB 精确节点路径重复: {node_path}")
        paths[node_path] = node_index

    subtree_cache: dict[int, tuple[int, ...]] = {}

    def subtree_meshes(index: int) -> tuple[int, ...]:
        cached = subtree_cache.get(index)
        if cached is not None:
            return cached
        node = nodes[index]
        meshes: list[int] = []
        mesh = node.get("mesh")
        if mesh is not None:
            meshes.append(_index(mesh, len(document.get("meshes") or []), "mesh"))
        for child in _indices(node.get("children"), len(nodes), "children"):
            meshes.extend(subtree_meshes(child))
        result = tuple(dict.fromkeys(meshes))
        subtree_cache[index] = result
        return result

    records = tuple(
        GltfNodeRecord(
            index=index,
            name=str(node.get("name") or f"__node_{index}"),
            path=path_by_index[index],
            parent_index=parent_by_child.get(index),
            child_indices=_indices(node.get("children"), len(nodes), "children"),
            mesh_index=(
                _index(node["mesh"], len(document.get("meshes") or []), "mesh")
                if node.get("mesh") is not None
                else None
            ),
            subtree_mesh_indices=subtree_meshes(index),
            local_matrix=_node_matrix(node),
            world_matrix=world_by_index[index],
        )
        for index, node in enumerate(nodes)
    )
    return GltfSceneIndex(asset_path, records, paths, scene_roots)


def identity_matrix() -> Matrix4:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def multiply_matrix(left: Matrix4, right: Matrix4) -> Matrix4:
    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(4))
            for column in range(4)
        )
        for row in range(4)
    )


def graph_pose_matrix(node: Mapping[str, Any]) -> Matrix4:
    """Match UniLab OS graph_pose: millimetres, degree RPY, Z-up."""

    raw_pose = node.get("pose")
    raw_position = node.get("position")
    if isinstance(raw_pose, Mapping) and isinstance(raw_position, Mapping):
        raise ValueError("物理图成员不能同时声明 pose 与 position")
    container = raw_pose if isinstance(raw_pose, Mapping) else raw_position
    if not isinstance(container, Mapping):
        container = {}
    nested = container.get("position")
    position = nested if isinstance(nested, Mapping) else container
    raw_rotation = container.get("rotation")
    rotation = raw_rotation if isinstance(raw_rotation, Mapping) else {}
    x, y, z = (_finite(position.get(axis), f"position.{axis}") / 1000.0 for axis in "xyz")
    roll, pitch, yaw = (
        math.radians(_finite(rotation.get(axis), f"rotation.{axis}")) for axis in "xyz"
    )
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, x),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, y),
        (-sp, cp * sr, cp * cr, z),
        (0.0, 0.0, 0.0, 1.0),
    )


def _read_glb_json(path: Path) -> Mapping[str, Any]:
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError("GLB header 不完整")
        magic, version, total_length = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2 or total_length != path.stat().st_size:
            raise ValueError("只支持长度一致的 glTF 2.0 GLB")
        chunk_header = stream.read(8)
        if len(chunk_header) != 8:
            raise ValueError("GLB JSON chunk header 不完整")
        chunk_length, chunk_type = struct.unpack("<I4s", chunk_header)
        if chunk_type != b"JSON":
            raise ValueError("GLB 第一块必须是 JSON")
        payload = stream.read(chunk_length)
    try:
        value = json.loads(payload.rstrip(b"\x00 ").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("GLB JSON chunk 非法") from error
    return _mapping(value, "GLB JSON")


def _scene_roots(
    document: Mapping[str, Any], node_count: int, parent_by_child: Mapping[int, int]
) -> tuple[int, ...]:
    scenes = document.get("scenes")
    scene_index = document.get("scene", 0)
    if isinstance(scenes, list) and scenes:
        selected = scenes[_index(scene_index, len(scenes), "scene")]
        return _indices(_mapping(selected, "scene").get("nodes"), node_count, "scene.nodes")
    return tuple(index for index in range(node_count) if index not in parent_by_child)


def _node_matrix(node: Mapping[str, Any]) -> Matrix4:
    matrix = node.get("matrix")
    if matrix is not None:
        if not isinstance(matrix, list) or len(matrix) != 16:
            raise ValueError("GLB node.matrix 必须有 16 个数")
        values = tuple(_finite(value, "node.matrix") for value in matrix)
        # glTF serializes matrices column-major; runtime storage here is row-major.
        return tuple(tuple(values[column * 4 + row] for column in range(4)) for row in range(4))
    translation = _vector(node.get("translation"), 3, (0.0, 0.0, 0.0), "translation")
    quaternion = _vector(node.get("rotation"), 4, (0.0, 0.0, 0.0, 1.0), "rotation")
    scale = _vector(node.get("scale"), 3, (1.0, 1.0, 1.0), "scale")
    x, y, z, w = quaternion
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 0.0:
        raise ValueError("GLB node.rotation 四元数不能为零")
    x, y, z, w = (value / norm for value in quaternion)
    sx, sy, sz = scale
    tx, ty, tz = translation
    return (
        ((1 - 2 * (y * y + z * z)) * sx, (2 * (x * y - z * w)) * sy, (2 * (x * z + y * w)) * sz, tx),
        ((2 * (x * y + z * w)) * sx, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z - x * w)) * sz, ty),
        ((2 * (x * z - y * w)) * sx, (2 * (y * z + x * w)) * sy, (1 - 2 * (x * x + y * y)) * sz, tz),
        (0.0, 0.0, 0.0, 1.0),
    )


def _vector(value: object, length: int, default: tuple[float, ...], label: str) -> tuple[float, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"GLB node.{label} 长度必须是 {length}")
    return tuple(_finite(item, f"node.{label}") for item in value)


def _indices(value: object, upper: int, label: str) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"GLB {label} 必须是数组")
    return tuple(_index(item, upper, label) for item in value)


def _index(value: object, upper: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value >= upper:
        raise ValueError(f"GLB {label} 索引越界")
    return value


def _finite(value: object, label: str) -> float:
    if value is None:
        return 0.0
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} 必须是数值") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} 必须是有限值")
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} 必须是对象")
    return value


__all__ = [
    "GltfNodeRecord",
    "GltfSceneIndex",
    "Matrix4",
    "graph_pose_matrix",
    "identity_matrix",
    "load_gltf_scene_index",
    "multiply_matrix",
]
