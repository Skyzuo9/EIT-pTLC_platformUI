# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS2SpotMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    sample_vial: ResourceSlot
    plate: ResourceSlot


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='1957469b-c632-56a8-a950-59fcdc2b2e5a',
    displayname='2-1 点样执行 · 物料合同',
    description="执行原始 PlatformUI operation pf_s2_spot；可搬运物料输入/输出=['sample_vial', 'plate']，工位自管物料=['sampling_rinse_solvent']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s2_spot_material_v1(
    *,
    sample_vial: ResourceSlot,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS2SpotMaterialV1Result:
    # unilab:node_uuid=c6f182e9-2730-5620-947f-845c8b5c404c
    execution = material.run_operation_review_v1(
        operation_name='pf_s2_spot',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=077df0b6-f78d-5654-8b79-d7934811c649
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
