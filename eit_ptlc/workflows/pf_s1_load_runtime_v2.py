# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s1_load_operation_view_v2 import (
    pf_s1_load_operation_view_v2,
)


class PfS1LoadRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='8b19fb70-5e1c-507f-8496-231e65339141',
    displayname='1 上样上料 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s1_load；可搬运物料输入/输出=['plate']，工位自管物料=['sampling_wash_solvent']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s1_load_runtime_v2(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS1LoadRuntimeV2Result:
    # unilab:node_uuid=15ce13cf-e752-5206-95d8-80c4967d2bc0
    structure = pf_s1_load_operation_view_v2()
    # unilab:node_uuid=e173b4bf-266d-57e6-991c-6e4f6807073c
    execution = material.run_operation_review_v1(
        operation_name='pf_s1_load',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=3adb6748-3248-58bd-92bd-4d50e6c11df6
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
