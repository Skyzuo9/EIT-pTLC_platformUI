# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS11UnloadMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='2d9caf43-123e-5289-880b-9fdf8c8697e0',
    displayname='9 废板下料 · 物料合同',
    description="执行原始 PlatformUI operation pf_s11_unload；可搬运物料输入/输出=['plate']，工位自管物料=['waste_magazine_seed_plate']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s11_unload_material_v1(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS11UnloadMaterialV1Result:
    # unilab:node_uuid=59ed673b-a9e6-55e1-9e41-bbeb647672cd
    execution = material.run_operation_review_v1(
        operation_name='pf_s11_unload',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=1341fd9b-99c6-5409-b9fd-2e7fe23e576d
    committed_plate = host_node.transfer_resource(
        resource=plate,
        target_device='plc_feedlift',
        mount_resource=resource_ref('plc_feedlift'),
        site='waste-stack',
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'plate': committed_plate.resource,
    }
