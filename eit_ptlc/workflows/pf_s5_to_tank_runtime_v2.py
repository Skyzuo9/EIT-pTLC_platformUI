# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, resource_ref, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.pf_s5_to_tank_operation_view_v2 import (
    pf_s5_to_tank_operation_view_v2,
)


class PfS5ToTankRuntimeV2Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    plate: ResourceSlot


material: MaterialProxy = device("material")


host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid='b0c52f6e-2618-5ab9-abf8-34ff39600610',
    displayname='4 取板进缸 · 分层运行 v2',
    description="分层展示并执行原始 PlatformUI operation pf_s5_to_tank；可搬运物料输入/输出=['plate']，工位自管物料=['prepared_developing_bath']。只读结构节点全部禁用；唯一执行节点提交一次原根 operation。成功后才提交 UniLab 位置与谱系，ResourceGate 保持不变。",
)
def pf_s5_to_tank_runtime_v2(
    *,
    plate: ResourceSlot,
    inputs_json: str = '{}',
    timeout_s: float = 3600.0,
    tank_site: str = 'tank-1',
) -> PfS5ToTankRuntimeV2Result:
    # unilab:node_uuid=1bb42c01-4cf9-503a-a51b-b3c74c551e7c
    structure = pf_s5_to_tank_operation_view_v2()
    # unilab:node_uuid=13581a81-e031-5880-8b42-eaac6c94121b
    execution = material.run_operation_review_v1(
        operation_name='pf_s5_to_tank',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    # unilab:node_uuid=6ff10526-4b95-564f-9a59-2f84b2cc6f2a
    committed_plate = host_node.transfer_resource(
        resource=plate,
        target_device='plc_develop',
        mount_resource=resource_ref('plc_develop'),
        site=tank_site,
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        'plate': committed_plate.resource,
    }
