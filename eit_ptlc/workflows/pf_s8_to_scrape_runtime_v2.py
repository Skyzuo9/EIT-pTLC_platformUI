# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s8_to_scrape_operation_view_v2 import (
    pf_s8_to_scrape_operation_view_v2,
)


class PfS8ToScrapeRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='8fc3216e-33b8-5b57-8b9a-4d23adbb7db1',
    displayname='6 出缸上刮板台 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s8_to_scrape；可搬运物料输入/输出=['plate']，工位自管物料=['无']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s8_to_scrape_runtime_v2(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
) -> PfS8ToScrapeRuntimeV2Result:
    # unilab:node_uuid=0af8acff-b895-5720-b937-cf51004a8135
    structure = pf_s8_to_scrape_operation_view_v2()
    # unilab:node_uuid=f3f795a1-5588-5dfd-beba-ad24c18aa6b3
    execution = material.run_operation_review_v1(
        operation_name='pf_s8_to_scrape',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=5a77d508-7a01-5e73-848f-4dca81bf4d6e
    committed_plate = host_node.transfer_resource(
        resource=plate,
        target_device='plc_photoscrape',
        mount_resource=resource_ref('plc_photoscrape'),
        site='plate',
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'plate': committed_plate.resource,
    }
