"""pTLC materials projected onto PlatformUI's mature scene assets."""

from __future__ import annotations

from pylabrobot.resources import Container, Resource
from unilabos.registry.decorators import resource

@resource(
    id="ptlc_plate",
    displayname="pTLC 20 cm 硅胶板",
    category=["ptlc", "chromatography", "plate"],
    description="PlatformUI plateTrace 四态物料；位置由同一库存提交链驱动。",
    model={
        "$ref": "ptlc_shared_scene",
        "selector": {
            "kind": "gltf_subtree",
            "node_index": 397,
            "node_path": "ST_FEEDLIFT/AXIS_AXIS_1Z/CARRIAGE.001/INV_MAGAZINE_FEED_TEMPLATE",
            "root_transform": "reset_translation",
        },
    },
)
def ptlc_plate(name: str = "PTLCSilicaPlate") -> Resource:
    return Resource(name=name, size_x=200.0, size_y=200.0, size_z=1.0, category="ptlc_plate")


@resource(
    id="ptlc_source_sample_vial",
    displayname="pTLC 输入样品瓶",
    category=["ptlc", "container", "primary_sample"],
    description="点样输入物料；复用 PlatformUI 成熟玻璃瓶附件并保留样品身份。",
    model={
        "$ref": "ptlc_shared_scene",
        "selector": {
            "kind": "gltf_subtree",
            "node_index": 8,
            "node_path": "ST_COLLECT/ACTUATOR_COL_EXTEND/样品瓶-2",
            "root_transform": "reset_translation",
        },
    },
)
def source_sample_vial(name: str = "PTLCSourceSampleVial") -> Container:
    return Container(name=name, size_x=16.0, size_y=16.0, size_z=45.0, max_volume=12_000.0, category="sample_vial")


@resource(
    id="ptlc_powder_collector",
    displayname="pTLC 粉末收集器",
    category=["ptlc", "consumable", "powder_collector"],
    description="复用 PlatformUI 中转 A 单件、接粉夹具和 TOOL_MOUNT 跟随合同。",
    model={
        "$ref": "ptlc_shared_scene",
        "selector": {
            "kind": "gltf_subtree",
            "node_index": 1302,
            "node_path": "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A/INV_STAGING_A_ITEM_1",
            "root_transform": "reset_translation",
        },
    },
)
def powder_collector(name: str = "PTLCPowderCollector") -> Resource:
    return Resource(name=name, size_x=30.0, size_y=30.0, size_z=45.0, category="powder_collector")


@resource(
    id="ptlc_collection_vial",
    displayname="pTLC 收集瓶",
    category=["ptlc", "container", "collection_vial"],
    description="复用 PlatformUI 中转 B 单件、收集瓶座和 TOOL_MOUNT 跟随合同。",
    model={
        "$ref": "ptlc_shared_scene",
        "selector": {
            "kind": "gltf_subtree",
            "node_index": 1337,
            "node_path": "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B/INV_STAGING_B_ITEM_1",
            "root_transform": "reset_translation",
        },
    },
)
def collection_vial(name: str = "PTLCCollectionVial") -> Container:
    return Container(name=name, size_x=25.0, size_y=25.0, size_z=60.0, max_volume=25_000.0, category="collection_vial")


@resource(
    id="ptlc_collector_rack",
    displayname="pTLC 收集器整架",
    category=["ptlc", "rack", "collector"],
    description="复用 PlatformUI INV_RACK_COLLECTOR_* 整架资产。",
    model={
        "$ref": "ptlc_shared_scene",
        "selector": {
            "kind": "gltf_subtree",
            "node_index": 1334,
            "node_path": "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A",
            "root_transform": "reset_translation",
            "exclude_node_paths": [
                "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A/INV_STAGING_A_ITEM_1",
                "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A/INV_STAGING_A_ITEM_2",
                "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A/INV_STAGING_A_ITEM_3",
                "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A/INV_STAGING_A_ITEM_4",
                "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A/INV_STAGING_A_ITEM_5",
                "ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A/INV_STAGING_A_ITEM_6",
            ],
        },
    },
)
def collector_rack(name: str = "PTLCCollectorRack") -> Resource:
    return Resource(name=name, size_x=120.0, size_y=140.0, size_z=130.0, category="collector_rack")


@resource(
    id="ptlc_vial_rack",
    displayname="pTLC 收集瓶整架",
    category=["ptlc", "rack", "vial"],
    description="复用 PlatformUI INV_RACK_BOTTLE_* 整架资产。",
    model={
        "$ref": "ptlc_shared_scene",
        "selector": {
            "kind": "gltf_subtree",
            "node_index": 1349,
            "node_path": "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B",
            "root_transform": "reset_translation",
            "exclude_node_paths": [
                "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B/INV_STAGING_B_ITEM_1",
                "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B/INV_STAGING_B_ITEM_2",
                "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B/INV_STAGING_B_ITEM_3",
                "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B/INV_STAGING_B_ITEM_4",
                "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B/INV_STAGING_B_ITEM_5",
                "ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B/INV_STAGING_B_ITEM_6",
            ],
        },
    },
)
def vial_rack(name: str = "PTLCVialRack") -> Resource:
    return Resource(name=name, size_x=120.0, size_y=140.0, size_z=130.0, category="vial_rack")


__all__ = [
    "collection_vial",
    "collector_rack",
    "powder_collector",
    "ptlc_plate",
    "source_sample_vial",
    "vial_rack",
]
