# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS7ConsumablesMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    collector: ResourceSlot
    vial: ResourceSlot
    collector_hole: int
    bottle_hole: int


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='578553d9-0bd1-5528-9dc3-3197b51ac72c',
    displayname='5-2 备耗材 · 物料合同',
    description="执行原始 PlatformUI operation pf_s7_consumables；可搬运物料输入/输出=['collector', 'vial']，工位自管物料=['无']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s7_consumables_material_v1(
    *,
    collector: ResourceSlot,
    vial: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS7ConsumablesMaterialV1Result:
    # unilab:node_uuid=4e3a2feb-037d-5e01-a94f-6ebd4686e0a3
    execution = material.run_operation_review_v1(
        operation_name='pf_s7_consumables',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=c3b66191-8816-5aef-89f7-c27be08853ef
    committed_collector = host_node.transfer_resource(
        resource=collector,
        target_device='plc_photoscrape',
        mount_resource=resource_ref('plc_photoscrape'),
        site='collector',
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'collector': committed_collector.resource,
        'vial': vial,
        'collector_hole': execution.collector_hole,
        'bottle_hole': execution.bottle_hole,
    }
