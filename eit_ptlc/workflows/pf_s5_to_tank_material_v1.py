# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS5ToTankMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='7f0a7e8d-2f59-56e9-a8d4-88f120ec2910',
    displayname='4 取板进缸 · 物料合同',
    description="执行原始 PlatformUI operation pf_s5_to_tank；可搬运物料输入/输出=['plate']，工位自管物料=['prepared_developing_bath']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s5_to_tank_material_v1(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
    tank_site: str = 'tank-1',
) -> PfS5ToTankMaterialV1Result:
    # unilab:node_uuid=c87f94b5-e5a6-505c-8a64-f7b08a225cd2
    execution = material.run_operation_review_v1(
        operation_name='pf_s5_to_tank',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=e0c9cdec-4a44-5d1a-9943-6878b7b51acf
    committed_plate = host_node.transfer_resource(
        resource=plate,
        target_device='plc_develop',
        mount_resource=resource_ref('plc_develop'),
        site=tank_site,
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'plate': committed_plate.resource,
    }
