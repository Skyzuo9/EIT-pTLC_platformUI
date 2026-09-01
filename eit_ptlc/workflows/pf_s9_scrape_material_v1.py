# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PfS9ScrapeMaterialV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot
    collector: ResourceSlot


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='fc971558-26d6-5422-9b1f-ea25da3af912',
    displayname='7 拍照刮取 · 物料合同',
    description="执行原始 PlatformUI operation pf_s9_scrape；可搬运物料输入/输出=['plate', 'collector']，工位自管物料=['无']。根 operation 成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s9_scrape_material_v1(
    *,
    plate: ResourceSlot,
    collector: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
    before_path: str = '',
) -> PfS9ScrapeMaterialV1Result:
    # unilab:node_uuid=149eed64-2d94-57f1-adb3-8890d7c5aa7c
    bound = material.bind_parallel_operation_inputs_v1(
        inputs_json=inputs_json,
        before_path=before_path,
    )
    # unilab:node_uuid=9989bbcd-a3f8-51e0-ab85-ad692f556df9
    execution = material.run_operation_review_v1(
        operation_name='pf_s9_scrape',
        inputs_json=bound.inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=50ccbaad-b439-566e-9f4f-637aa74e2a8c
    linked = material.record_scraping_v4(
        plate=plate,
        powder_collector=collector,
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'plate': linked.plate,
        'collector': linked.powder_collector,
    }
