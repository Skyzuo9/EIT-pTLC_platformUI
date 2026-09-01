# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS8ToScrapeMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='d9b8a129-594f-5bdd-a0be-d63a3027fdbe',
    displayname='6 出缸上刮板台 · 物料合同',
    description="执行原始 PlatformUI operation pf_s8_to_scrape；可搬运物料输入/输出=['plate']，工位自管物料=['无']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s8_to_scrape_material_v1(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS8ToScrapeMaterialV1Result:
    # unilab:node_uuid=16e71655-4071-5e1a-8156-dee54d1b4010
    execution = material.run_operation_review_v1(
        operation_name='pf_s8_to_scrape',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=c682f00b-1c37-56aa-be12-bf1be52fa5db
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
    }
