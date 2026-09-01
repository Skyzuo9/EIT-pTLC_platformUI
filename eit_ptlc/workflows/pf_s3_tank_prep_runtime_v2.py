# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s3_tank_prep_operation_view_v2 import (
    pf_s3_tank_prep_operation_view_v2,
)


class PfS3TankPrepRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='0ab6a6ae-48e0-50df-b938-6f0395bd06b8',
    displayname='2-2 展缸预备 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s3_tank_prep；可搬运物料输入/输出=['无']，工位自管物料=['developing_solvent_1', 'developing_solvent_2', 'developing_solvent_3', 'developing_solvent_4', 'prepared_developing_bath']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s3_tank_prep_runtime_v2(
    *,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS3TankPrepRuntimeV2Result:
    # unilab:node_uuid=453affd2-ac6c-55a1-929c-725a818364c8
    structure = pf_s3_tank_prep_operation_view_v2()
    # unilab:node_uuid=7a7f1737-c183-5dd6-b8b3-f7366de08591
    execution = material.run_operation_review_v1(
        operation_name='pf_s3_tank_prep',
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
