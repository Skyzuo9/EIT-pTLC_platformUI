# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS1LoadMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='d290f93c-61d6-55ae-9eee-e2582de6afa0',
    displayname='1 上样上料 · 物料合同',
    description="执行原始 PlatformUI operation pf_s1_load；可搬运物料输入/输出=['plate']，工位自管物料=['sampling_wash_solvent']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s1_load_material_v1(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS1LoadMaterialV1Result:
    # unilab:node_uuid=66f13647-cd45-5ead-a93c-e9a16a68f37e
    execution = material.run_operation_review_v1(
        operation_name='pf_s1_load',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=2ca75738-e511-559e-bf54-37130e0dc43d
    committed_plate = host_node.transfer_resource(
        resource=plate,
        target_device='plc_sampling',
        mount_resource=resource_ref('plc_sampling'),
        site='plate',
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'plate': committed_plate.resource,
    }
