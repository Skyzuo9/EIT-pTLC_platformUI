# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS4PhotoBeforeMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot
    before_path: str


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='a8686956-7ff7-5fe6-8ac1-82e8e4bc712e',
    displayname='3 展开前拍照 · 物料合同',
    description="执行原始 PlatformUI operation pf_s4_photo_before；可搬运物料输入/输出=['plate']，工位自管物料=['无']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s4_photo_before_material_v1(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS4PhotoBeforeMaterialV1Result:
    # unilab:node_uuid=0bfcc1b1-d536-5867-8a1d-c136c18bdf8c
    execution = material.run_operation_review_v1(
        operation_name='pf_s4_photo_before',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=8f94c92e-cdfa-5fc3-ad08-b6c498d731c3
    committed_plate = host_node.transfer_resource(
        resource=plate,
        target_device='plc_photoscrape',
        mount_resource=resource_ref('plc_photoscrape'),
        site='plate',
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'plate': committed_plate.resource,
        'before_path': execution.before_path,
    }
