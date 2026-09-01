# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_af0_batch_startup_operation_view_v2 import (
    pf_af0_batch_startup_operation_view_v2,
)


class PfAf0BatchStartupRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='42edb8c6-91d8-5da7-8473-8522af81ca27',
    displayname='0 批次起手 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_af0_batch_startup；可搬运物料输入/输出=['无']，工位自管物料=['无']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_af0_batch_startup_runtime_v2(
    *,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfAf0BatchStartupRuntimeV2Result:
    # unilab:node_uuid=2744b34f-27e6-52e6-aafd-f899647a6105
    structure = pf_af0_batch_startup_operation_view_v2()
    # unilab:node_uuid=225945a2-f57b-5f8d-a3ee-99a13d1bf976
    execution = material.run_operation_review_v1(
        operation_name='pf_af0_batch_startup',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
    }
