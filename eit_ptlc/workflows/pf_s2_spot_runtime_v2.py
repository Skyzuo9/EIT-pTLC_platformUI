# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s2_spot_operation_view_v2 import (
    pf_s2_spot_operation_view_v2,
)


class PfS2SpotRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    sample_vial: ResourceSlot
    plate: ResourceSlot


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='8cea4a6a-8f36-535f-bd94-ea2da47606bd',
    displayname='2-1 点样执行 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s2_spot；可搬运物料输入/输出=['sample_vial', 'plate']，工位自管物料=['sampling_rinse_solvent']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s2_spot_runtime_v2(
    *,
    sample_vial: ResourceSlot,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS2SpotRuntimeV2Result:
    # unilab:node_uuid=07aada66-9d36-5be7-8d77-31ddfc81b7aa
    structure = pf_s2_spot_operation_view_v2()
    # unilab:node_uuid=0371a964-a213-56ba-b9d4-0593692468b3
    execution = material.run_operation_review_v1(
        operation_name='pf_s2_spot',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=f931c592-401f-5e24-84e7-e35fe22bbbaf
    linked = material.record_spotting_v4(
        sample_vial=sample_vial,
        plate=plate,
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'sample_vial': linked.sample_vial,
        'plate': linked.plate,
    }
