"""UniLab Material Model Catalog entry for PlatformUI's shared scene.

Every device/resource template uses a named ``$ref`` to this declaration.
The graph-to-scene compiler then clones only its exact GLB node subtree, so the
14 MB assembly is served once without pretending that it is a robot model.
"""

from __future__ import annotations

from pylabrobot.resources import Resource
from unilabos.registry.decorators import resource


@resource(
    id="ptlc_shared_scene",
    displayname="pTLC PlatformUI 共享三维装配场景",
    category=["ptlc", "three-d", "shared-scene"],
    description="SolidWorks 整机 GLB；具体设备/物料由 graph-to-scene selector 独立实例化。",
    model={
        "format": "glb",
        "entry": "models/machine.official-cr5.glb",
        "model_origin": {
            "facade": "unilab_facade.v1.yaml",
            "provenance": "unilab_provenance.v1.yaml",
            "instancing": "shared_glb_subtree",
            "motion_authority": False,
            # These three top-level subtrees are visual context, not Material
            # instances.  Workbench loads them once in the same Pascal scene
            # and keeps every business object on its existing graph selector.
            "scene_context": {
                "id": "ptlc-official-static-context-v1",
                "coordinate_authority": (
                    "machine.official-cr5.glb#world_matrix"
                ),
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
            },
        },
    },
)
def ptlc_shared_scene(name: str = "PTLCSharedScene") -> Resource:
    """Return the logical Catalog resource; geometry lives in the GLB entry."""

    return Resource(
        name=name,
        size_x=3000.0,
        size_y=2200.0,
        size_z=1800.0,
        category="ptlc_shared_scene",
    )


__all__ = ["ptlc_shared_scene"]
