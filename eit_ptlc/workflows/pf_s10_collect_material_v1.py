# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS10CollectMaterialV1Result(TypedDict):
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
    workflow_uuid='c22a5058-d936-5f1d-85ba-decef8cff52f',
    displayname='8 粉末收集 · 物料合同',
    description="执行原始 PlatformUI operation pf_s10_collect；可搬运物料输入/输出=['collector', 'vial']，工位自管物料=['collection_elution_solvent']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s10_collect_material_v1(
    *,
    collector: ResourceSlot,
    vial: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
    bottle_site: str = 'bottle-item-1',
    collector_site: str = 'collector-item-1',
    collector_hole: int = 0,
    bottle_hole: int = 0,
) -> PfS10CollectMaterialV1Result:
    # unilab:node_uuid=93428b98-e363-5114-b2a7-105c5fac7f82
    bound = material.bind_parallel_operation_inputs_v1(
        inputs_json=inputs_json,
        collector_hole=collector_hole,
        bottle_hole=bottle_hole,
    )
    # unilab:node_uuid=809ec7f2-477e-5435-99d8-c55d24967cce
    execution = material.run_operation_review_v1(
        operation_name='pf_s10_collect',
        inputs_json=bound.inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=42c7d8b4-9154-569c-aad1-3986336b2ef7
    linked = material.record_collection_v4(
        powder_collector=collector,
        vial=vial,
    )
    # unilab:node_uuid=61176bab-5e4e-5ce0-851a-23e26a0c2075
    committed_collector = host_node.transfer_resource(
        resource=linked.powder_collector,
        target_device='plc_staginga',
        mount_resource=resource_ref('staging_a_stack'),
        site=collector_site,
    )
    # unilab:node_uuid=07b65475-8b2c-5ecd-91c0-91f31fe0ca3f
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
