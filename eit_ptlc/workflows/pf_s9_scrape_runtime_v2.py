# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s9_scrape_operation_view_v2 import (
    pf_s9_scrape_operation_view_v2,
)


class PfS9ScrapeRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot
    collector: ResourceSlot


material: MaterialProxy = device("material")


@workflow(
    workflow_uuid='24c631bb-245d-543e-9b4c-7c80ff0fb702',
    displayname='7 拍照刮取 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s9_scrape；可搬运物料输入/输出=['plate', 'collector']，工位自管物料=['无']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s9_scrape_runtime_v2(
    *,
    plate: ResourceSlot,
    collector: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
    before_path: str = '',
) -> PfS9ScrapeRuntimeV2Result:
    # unilab:node_uuid=61a3ad15-cbf6-56e5-ac57-fba715b99028
    bound = material.bind_parallel_operation_inputs_v1(
        inputs_json=inputs_json,
        before_path=before_path,
    )
    # unilab:node_uuid=dc46b362-9c2d-5017-8eed-866fc47c7d15
    structure = pf_s9_scrape_operation_view_v2()
    # unilab:node_uuid=50581a4e-8434-5014-9327-3e81ef8be6c4
    execution = material.run_operation_review_v1(
        operation_name='pf_s9_scrape',
        inputs_json=bound.inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=332eaa53-2da3-5d32-ac8f-29f556cf4dc6
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
