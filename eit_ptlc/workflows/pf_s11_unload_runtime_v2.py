# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s11_unload_operation_view_v2 import (
    pf_s11_unload_operation_view_v2,
)


class PfS11UnloadRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='26220c7a-7d51-59ec-88a0-d1350cbcdbb1',
    displayname='9 废板下料 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s11_unload；可搬运物料输入/输出=['plate']，工位自管物料=['waste_magazine_seed_plate']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s11_unload_runtime_v2(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS11UnloadRuntimeV2Result:
    # unilab:node_uuid=204ba7f0-f2a4-52c8-b5a3-8c34b75313fc
    structure = pf_s11_unload_operation_view_v2()
    # unilab:node_uuid=cbca8284-1084-5f91-b220-3fd3155eb5c0
    execution = material.run_operation_review_v1(
        operation_name='pf_s11_unload',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=f4624430-4c99-53ce-97f7-150eb803067d
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
