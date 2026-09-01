# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s6_develop_wait_operation_view_v2 import (
    pf_s6_develop_wait_operation_view_v2,
)


class PfS6DevelopWaitRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='5f5e63da-c47a-58b8-be85-aed688aa91f0',
    displayname='5-1 展开等待 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s6_develop_wait；可搬运物料输入/输出=['plate']，工位自管物料=['prepared_developing_bath']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s6_develop_wait_runtime_v2(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS6DevelopWaitRuntimeV2Result:
    # unilab:node_uuid=20e1d5eb-d9e4-57a2-abf2-55f4dbfd22a2
    structure = pf_s6_develop_wait_operation_view_v2()
    # unilab:node_uuid=79d2c0f3-6c52-5e26-aace-9b4bb2d73d8e
    execution = material.run_operation_review_v1(
        operation_name='pf_s6_develop_wait',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'plate': plate,
    }
