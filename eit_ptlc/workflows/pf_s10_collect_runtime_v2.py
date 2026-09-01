# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s10_collect_operation_view_v2 import (
    pf_s10_collect_operation_view_v2,
)


class PfS10CollectRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    collector: ResourceSlot
    vial: ResourceSlot


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='75e34240-fd00-51bd-80bf-78f384e9f0bd',
    displayname='8 粉末收集 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s10_collect；可搬运物料输入/输出=['collector', 'vial']，工位自管物料=['collection_elution_solvent']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s10_collect_runtime_v2(
    *,
    collector: ResourceSlot,
    vial: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
    bottle_site: str = 'bottle-item-1',
    collector_site: str = 'collector-item-1',
    collector_hole: int = 0,
    bottle_hole: int = 0,
) -> PfS10CollectRuntimeV2Result:
    # unilab:node_uuid=fb7f20d7-b0dd-501a-b2b9-8c6f1a65d9d9
    bound = material.bind_parallel_operation_inputs_v1(
        inputs_json=inputs_json,
        collector_hole=collector_hole,
        bottle_hole=bottle_hole,
    )
    # unilab:node_uuid=7323156b-7818-5cd7-af42-8dc1f3f73293
    structure = pf_s10_collect_operation_view_v2()
    # unilab:node_uuid=1a60fc00-d22c-5b47-9bdf-e467341c47e2
    execution = material.run_operation_review_v1(
        operation_name='pf_s10_collect',
        inputs_json=bound.inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=2f97262e-1c4c-5f09-bdb2-fd608ed45873
    linked = material.record_collection_v4(
        powder_collector=collector,
        vial=vial,
    )
    # unilab:node_uuid=786719ee-4852-515c-9e16-c0b61efb6e26
    committed_collector = host_node.transfer_resource(
        resource=linked.powder_collector,
        target_device='plc_staginga',
        mount_resource=resource_ref('staging_a_stack'),
        site=collector_site,
    )
    # unilab:node_uuid=d9130bb6-1e20-5e1d-ab15-29eaad000f5e
    committed_vial = host_node.transfer_resource(
        resource=linked.vial,
        target_device='plc_staginga',
        mount_resource=resource_ref('staging_b_stack'),
        site=bottle_site,
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'collector': committed_collector.resource,
        'vial': committed_vial.resource,
    }
