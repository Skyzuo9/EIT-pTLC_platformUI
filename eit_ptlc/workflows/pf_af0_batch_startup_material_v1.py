# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfAf0BatchStartupMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='d5079b84-dd0e-5026-9a51-bcdfbe86786c',
    displayname='0 批次起手 · 物料合同',
    description="执行原始 PlatformUI operation pf_af0_batch_startup；可搬运物料输入/输出=['无']，工位自管物料=['无']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_af0_batch_startup_material_v1(
    *,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfAf0BatchStartupMaterialV1Result:
    # unilab:node_uuid=42d05ac3-9579-5a34-8a02-a71609541b0e
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
