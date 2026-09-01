# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.workflow.authoring import (
    MaterialFlowRole,
    group,
    material_source,
    parallel,
    resource_ref,
    workflow,
)

from eit_ptlc.unilab_domain.resources.materials import (
    collection_vial,
    powder_collector,
    ptlc_plate,
    source_sample_vial,
)
from eit_ptlc.workflows.pf_af0_batch_startup_material_v1 import (
    pf_af0_batch_startup_material_v1,
)
from eit_ptlc.workflows.pf_s1_load_material_v1 import (
    pf_s1_load_material_v1,
)
from eit_ptlc.workflows.pf_s2_spot_material_v1 import (
    pf_s2_spot_material_v1,
)
from eit_ptlc.workflows.pf_s3_tank_prep_material_v1 import (
    pf_s3_tank_prep_material_v1,
)
from eit_ptlc.workflows.pf_s4_photo_before_material_v1 import (
    pf_s4_photo_before_material_v1,
)
from eit_ptlc.workflows.pf_s5_to_tank_material_v1 import (
    pf_s5_to_tank_material_v1,
)
from eit_ptlc.workflows.pf_s6_develop_wait_material_v1 import (
    pf_s6_develop_wait_material_v1,
)
from eit_ptlc.workflows.pf_s7_consumables_material_v1 import (
    pf_s7_consumables_material_v1,
)
from eit_ptlc.workflows.pf_s8_to_scrape_material_v1 import (
    pf_s8_to_scrape_material_v1,
)
from eit_ptlc.workflows.pf_s9_scrape_material_v1 import (
    pf_s9_scrape_material_v1,
)
from eit_ptlc.workflows.pf_s10_collect_material_v1 import (
    pf_s10_collect_material_v1,
)
from eit_ptlc.workflows.pf_s11_unload_material_v1 import (
    pf_s11_unload_material_v1,
)


class PTLCParallelSegmentsV1Result(TypedDict):
    sample: ResourceSlot
    waste_plate: ResourceSlot
    powder_collector: ResourceSlot


@workflow(
    workflow_uuid='62a2f155-1b29-5ac2-b8bf-463656c98621',
    displayname='并行全流程 v1 (12 段, 四段式对齐)',
    description=(
        '由 PlatformUI parallel_v1 和 12 段物料合同自动导出。每段是可展开子工作流，'
        '内部只执行一次原根 operation；s2∥s3、(s6→s8)∥s7，且 s7 严格在 s5 后开始。'
    ),
)
def ptlc_parallel_segments_v1(
    *,
    af0_inputs_json: str = '{}',
    s1_inputs_json: str = '{}',
    s2_inputs_json: str = '{}',
    s3_inputs_json: str = '{"tank":1}',
    s4_inputs_json: str = '{"sample_id":"DEMO-001","save_dir":"var/photoscrape/demo"}',
    s5_inputs_json: str = '{"tank":1}',
    s6_inputs_json: str = '{"tank":1,"auto_drain":true}',
    s7_inputs_json: str = '{"reserve_for":"DEMO-001"}',
    s8_inputs_json: str = '{"tank":1}',
    s9_inputs_json: str = '{"sample_id":"DEMO-001","save_dir":"var/photoscrape/demo","before_path":"var/photoscrape/demo/before.jpg","mode":"auto"}',
    s10_inputs_json: str = '{"collector_hole":1,"bottle_hole":1}',
    s11_inputs_json: str = '{}',
    tank_site: str = 'tank-1',
    collector_site: str = 'collector-item-1',
    bottle_site: str = 'bottle-item-1',
) -> PTLCParallelSegmentsV1Result:
    # unilab:node_uuid=b26acf65-e650-591e-955f-c2ba2ab01828
    sample_vial = material_source(
        resource_template=source_sample_vial,
        mode='existing',
        mount=resource_ref('plc_sampling'),
        material_uuid=None,
        site=None,
        slot_range=None,
        flow_role=MaterialFlowRole.PRIMARY_SAMPLE,
    )
    # unilab:node_uuid=4b497413-53b2-5e5d-87d3-1d324b467a89
    plate = material_source(
        resource_template=ptlc_plate,
        mode='existing',
        mount=resource_ref('plc_feedlift'),
        material_uuid=None,
        site=None,
        slot_range=None,
        flow_role=MaterialFlowRole.ALIQUOT_SAMPLE,
    )
    # unilab:node_uuid=a3f37aa6-2782-549c-bd7d-4c74a2fcf18d
    collector = material_source(
        resource_template=powder_collector,
        mode='existing',
        mount=resource_ref('staging_a_stack'),
        material_uuid=None,
        site=None,
        slot_range=None,
        flow_role=MaterialFlowRole.CONSUMABLE,
    )
    # unilab:node_uuid=ebffcae4-3874-5887-8f5a-d9c8a51e4eff
    vial = material_source(
        resource_template=collection_vial,
        mode='existing',
        mount=resource_ref('staging_b_stack'),
        material_uuid=None,
        site=None,
        slot_range=None,
        flow_role=MaterialFlowRole.CONSUMABLE,
    )
    # unilab:node_uuid=00346087-a35d-50e6-8921-1afe1c4ad010
    af0 = pf_af0_batch_startup_material_v1(
        inputs_json=af0_inputs_json,
    )
    # unilab:node_uuid=c787748c-4ff0-5414-af07-d457a2e13b6a
    s1 = pf_s1_load_material_v1(
        plate=plate,
        inputs_json=s1_inputs_json,
    )
    with parallel():
        # unilab:node_uuid=7b59c51f-6b73-53fd-82a1-a8da8c1d0842
        with group(name='s2 点样 → s4 展开前拍照'):
            # unilab:node_uuid=d6135a1d-49c8-5419-b080-448ea7501e04
            s2 = pf_s2_spot_material_v1(
                sample_vial=sample_vial,
                plate=s1.plate,
                inputs_json=s2_inputs_json,
            )
            # unilab:node_uuid=daf2c449-1a20-55c7-af23-ea22f95782ed
            s4 = pf_s4_photo_before_material_v1(
                plate=s2.plate,
                inputs_json=s4_inputs_json,
            )
        # unilab:node_uuid=e1895930-c85e-5080-85ba-5e2e7240ae0e
        with group(name='s3 展缸预备'):
            # unilab:node_uuid=e6b66c89-ec93-5d42-a8af-fc9f406214fe
            s3 = pf_s3_tank_prep_material_v1(
                inputs_json=s3_inputs_json,
            )
    # unilab:node_uuid=349e9d9f-e19c-5c3b-8069-e3f0c8b06de6
    s5 = pf_s5_to_tank_material_v1(
        plate=s4.plate,
        inputs_json=s5_inputs_json,
        tank_site=tank_site,
    )
    with parallel():
        # unilab:node_uuid=3e10a0fe-03bf-5c4f-945b-54ae1f684d2d
        with group(name='s6 展开等待 → s8 出缸上刮板台'):
            # unilab:node_uuid=4f50d6d7-a034-5e56-9135-67e99e6efe71
            s6 = pf_s6_develop_wait_material_v1(
                plate=s5.plate,
                inputs_json=s6_inputs_json,
            )
            # unilab:node_uuid=6e056a3d-e2d9-5c4d-978d-59b33c17e8be
            s8 = pf_s8_to_scrape_material_v1(
                plate=s6.plate,
                inputs_json=s8_inputs_json,
            )
        # unilab:node_uuid=54356bd2-2ac2-52e4-a72f-2a081588c54f
        with group(name='s7 备耗材（严格在 s5 后）'):
            # unilab:node_uuid=b1c8b01b-5d5f-5543-9199-c1c8b1e08531
            s7 = pf_s7_consumables_material_v1(
                collector=collector,
                vial=vial,
                inputs_json=s7_inputs_json,
            )
    # unilab:node_uuid=f9b0eeb8-d077-5f82-8dba-903f2befbdd6
    s9 = pf_s9_scrape_material_v1(
        plate=s8.plate,
        collector=s7.collector,
        inputs_json=s9_inputs_json,
        before_path=s4.before_path,
    )
    # unilab:node_uuid=d546dc0a-f685-57ed-9f47-d00cb843f399
    s10 = pf_s10_collect_material_v1(
        collector=s9.collector,
        vial=s7.vial,
        inputs_json=s10_inputs_json,
        collector_hole=s7.collector_hole,
        bottle_hole=s7.bottle_hole,
        collector_site=collector_site,
        bottle_site=bottle_site,
    )
    # unilab:node_uuid=e608a240-8f91-52d7-ad29-4a3021dbe353
    s11 = pf_s11_unload_material_v1(
        plate=s9.plate,
        inputs_json=s11_inputs_json,
    )
    return {
        'sample': s10.vial,
        'waste_plate': s11.plate,
        'powder_collector': s10.collector,
    }
