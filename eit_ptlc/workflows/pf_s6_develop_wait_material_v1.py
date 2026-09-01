# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS6DevelopWaitMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='cbdc04be-4b79-597d-aeae-e1981e6b226b',
    displayname='5-1 展开等待 · 物料合同',
    description="执行原始 PlatformUI operation pf_s6_develop_wait；可搬运物料输入/输出=['plate']，工位自管物料=['prepared_developing_bath']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s6_develop_wait_material_v1(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS6DevelopWaitMaterialV1Result:
    # unilab:node_uuid=618adbbe-15c2-5da0-98c4-76bca60e3bd6
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
