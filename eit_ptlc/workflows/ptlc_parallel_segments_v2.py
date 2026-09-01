# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.workflow.authoring import (
    group,
    parallel,
    workflow,
)
from eit_ptlc.workflows.pf_af0_batch_startup_runtime_v2 import (
    pf_af0_batch_startup_runtime_v2,
)
from eit_ptlc.workflows.pf_s1_load_runtime_v2 import (
    pf_s1_load_runtime_v2,
)
from eit_ptlc.workflows.pf_s2_spot_runtime_v2 import (
    pf_s2_spot_runtime_v2,
)
from eit_ptlc.workflows.pf_s3_tank_prep_runtime_v2 import (
    pf_s3_tank_prep_runtime_v2,
)
from eit_ptlc.workflows.pf_s4_photo_before_runtime_v2 import (
    pf_s4_photo_before_runtime_v2,
)
from eit_ptlc.workflows.pf_s5_to_tank_runtime_v2 import (
    pf_s5_to_tank_runtime_v2,
)
from eit_ptlc.workflows.pf_s6_develop_wait_runtime_v2 import (
    pf_s6_develop_wait_runtime_v2,
)
from eit_ptlc.workflows.pf_s7_consumables_runtime_v2 import (
    pf_s7_consumables_runtime_v2,
)
from eit_ptlc.workflows.pf_s8_to_scrape_runtime_v2 import (
    pf_s8_to_scrape_runtime_v2,
)
from eit_ptlc.workflows.pf_s9_scrape_runtime_v2 import (
    pf_s9_scrape_runtime_v2,
)
from eit_ptlc.workflows.pf_s10_collect_runtime_v2 import (
    pf_s10_collect_runtime_v2,
)
from eit_ptlc.workflows.pf_s11_unload_runtime_v2 import (
    pf_s11_unload_runtime_v2,
)


class PTLCParallelSegmentsV2Result(TypedDict):
    sample: ResourceSlot
    waste_plate: ResourceSlot
    powder_collector: ResourceSlot


@workflow(
    workflow_uuid='6b2cc909-7fbc-56b0-88ac-0e98f279a7ea',
    displayname='并行全流程 v2（分层展示 + 原子运行，12 段）',
    description=(
        '由 PlatformUI parallel_v1 和 12 段物料合同自动导出。每段是可展开子工作流，'
        '输入物料由显式 ResourceSlot 绑定；先分层展示 operation 结构，再由唯一根节点执行；'
        's2∥s3、(s6→s8)∥s7，且 s7 严格在 s5 后开始。'
    ),
)
def ptlc_parallel_segments_v2(
    *,
    sample_vial: ResourceSlot,
    plate: ResourceSlot,
    collector: ResourceSlot,
    vial: ResourceSlot,
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
) -> PTLCParallelSegmentsV2Result:
    # unilab:node_uuid=c89c93b7-65c2-5e1b-a689-f3d0c74af922
    af0 = pf_af0_batch_startup_runtime_v2(
        inputs_json=af0_inputs_json,
    )
    # unilab:node_uuid=6a88d0df-4399-58d4-8964-e58cf65ead16
    s1 = pf_s1_load_runtime_v2(
        plate=plate,
        inputs_json=s1_inputs_json,
    )
    with parallel():
        # unilab:node_uuid=617ddb98-fbbf-565b-8996-c2c5f8d2a077
        with group(name='s2 点样 → s4 展开前拍照'):
            # unilab:node_uuid=e160ebb3-5786-5e3e-9a85-18ee3d138b5a
            s2 = pf_s2_spot_runtime_v2(
                sample_vial=sample_vial,
                plate=s1.plate,
                inputs_json=s2_inputs_json,
            )
            # unilab:node_uuid=be6026ed-7c8f-57b7-8593-7632949acf55
            s4 = pf_s4_photo_before_runtime_v2(
                plate=s2.plate,
                inputs_json=s4_inputs_json,
            )
        # unilab:node_uuid=9a24edf3-5ba1-50e0-8416-0f7c667bc72d
        with group(name='s3 展缸预备'):
            # unilab:node_uuid=12bac56d-a452-5e83-ae9a-7d64044d6040
            s3 = pf_s3_tank_prep_runtime_v2(
                inputs_json=s3_inputs_json,
            )
    # unilab:node_uuid=845f1efa-0882-5a4e-82ee-6917de8944ab
    s5 = pf_s5_to_tank_runtime_v2(
        plate=s4.plate,
        inputs_json=s5_inputs_json,
        tank_site=tank_site,
    )
    with parallel():
        # unilab:node_uuid=e45b918a-5cc6-52c3-9df4-d18abf08c8ca
        with group(name='s6 展开等待 → s8 出缸上刮板台'):
            # unilab:node_uuid=71490836-4b2e-581a-aaf1-38c1ef5ec10f
            s6 = pf_s6_develop_wait_runtime_v2(
                plate=s5.plate,
                inputs_json=s6_inputs_json,
            )
            # unilab:node_uuid=fc05c06e-e0eb-5ea2-b85a-964b73e7be83
            s8 = pf_s8_to_scrape_runtime_v2(
                plate=s6.plate,
                inputs_json=s8_inputs_json,
            )
        # unilab:node_uuid=00d895c7-aa12-5c40-b71c-01a3854a459f
        with group(name='s7 备耗材（严格在 s5 后）'):
            # unilab:node_uuid=062c8140-9d39-588d-a9ec-41544a07c9be
            s7 = pf_s7_consumables_runtime_v2(
                collector=collector,
                vial=vial,
                inputs_json=s7_inputs_json,
            )
    # unilab:node_uuid=2c43d923-2c25-5372-b394-195b6898ee4a
    s9 = pf_s9_scrape_runtime_v2(
        plate=s8.plate,
        collector=s7.collector,
        inputs_json=s9_inputs_json,
        before_path=s4.before_path,
    )
    # unilab:node_uuid=58139582-527a-5f13-88a9-af99d852e623
    s10 = pf_s10_collect_runtime_v2(
        collector=s9.collector,
        vial=s7.vial,
        inputs_json=s10_inputs_json,
        collector_hole=s7.collector_hole,
        bottle_hole=s7.bottle_hole,
        collector_site=collector_site,
        bottle_site=bottle_site,
    )
    # unilab:node_uuid=44209877-e415-5dcc-8097-56111f6eb9ec
    s11 = pf_s11_unload_runtime_v2(
        plate=s9.plate,
        inputs_json=s11_inputs_json,
    )
    return {
        'sample': s10.vial,
        'waste_plate': s11.plate,
        'powder_collector': s10.collector,
    }
