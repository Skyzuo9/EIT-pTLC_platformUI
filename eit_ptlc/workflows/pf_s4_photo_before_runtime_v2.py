# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s4_photo_before_operation_view_v2 import (
    pf_s4_photo_before_operation_view_v2,
)


class PfS4PhotoBeforeRuntimeV2Result(TypedDict):
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
    workflow_uuid='a2cd9847-57f6-5e64-af97-8e74bfac38c6',
    displayname='3 展开前拍照 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s4_photo_before；可搬运物料输入/输出=['plate']，工位自管物料=['无']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s4_photo_before_runtime_v2(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS4PhotoBeforeRuntimeV2Result:
    # unilab:node_uuid=11aec18a-a660-523b-a52d-51eccc110bdc
    structure = pf_s4_photo_before_operation_view_v2()
    # unilab:node_uuid=90d2d3f0-22e1-56db-b8fd-a5f230bd6dd5
    execution = material.run_operation_review_v1(
        operation_name='pf_s4_photo_before',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=de73faa4-93c6-5568-b56a-a7a0025cdc04
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
