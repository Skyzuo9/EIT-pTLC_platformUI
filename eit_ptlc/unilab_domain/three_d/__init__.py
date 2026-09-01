"""UniLab-facing, read-only view of the existing PlatformUI 3D assets."""

from .facade import (
    DeviceVisualBinding,
    MaterialVisualBinding,
    ThreeDAssetFacade,
    load_three_d_asset_facade,
)
from .gltf_index import GltfNodeRecord, GltfSceneIndex, load_gltf_scene_index
from .scene_graph import CompiledSceneGraph, SceneEntity, compile_graph_scene

__all__ = [
    "DeviceVisualBinding",
    "MaterialVisualBinding",
    "ThreeDAssetFacade",
    "CompiledSceneGraph",
    "GltfNodeRecord",
    "GltfSceneIndex",
    "SceneEntity",
    "compile_graph_scene",
    "load_gltf_scene_index",
    "load_three_d_asset_facade",
]
