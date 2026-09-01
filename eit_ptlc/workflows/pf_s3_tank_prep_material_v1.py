# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS3TankPrepMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='35242728-92f7-5156-88b4-365e1630d5ff',
    displayname='2-2 展缸预备 · 物料合同',
    description="执行原始 PlatformUI operation pf_s3_tank_prep；可搬运物料输入/输出=['无']，工位自管物料=['developing_solvent_1', 'developing_solvent_2', 'developing_solvent_3', 'developing_solvent_4', 'prepared_developing_bath']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s3_tank_prep_material_v1(
    *,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS3TankPrepMaterialV1Result:
    # unilab:node_uuid=d05f5c68-53f4-568c-bf3b-5b60a0321b9e
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
