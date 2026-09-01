from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.workflows.collect_cycle_operation_view_v2 import (
    collect_cycle_operation_view_v2,
)


material: MaterialProxy = device('material')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='59ff36e1-03ad-5b64-917e-0c5a20ccf9d6',
    displayname='8 粉末收集 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s10_collect_operation_view_v2() -> None:
    # [OPERATION pf_s10_collect] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=eb3a30b9-652b-5d50-9686-fb230caa771e disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s10_collect',
        inputs_json='{"bottle_hole":1,"collector_hole":1}',
        expected_sha256='f4f05185949016884ccdb3cbb6b8c11397e28396015a56c449d8140eb324775b',
    )
    # [SUBWORKFLOW collect_cycle] 来源 pf_s10_collect@body/0；原节点 {"inputs":{"bottle_slot":{"var":"bottle_hole"},"collector_slot":{"var":"collector_hole"}},"op":"run_script","outputs":{},"script":"collect_cycle"}
    # unilab:node_uuid=65e07e5d-269c-5479-bcfe-5a87f892a9df
    nested_operation_0002 = collect_cycle_operation_view_v2()
    # [VERIFY comment] 只读来源校验 pf_s10_collect@body/1；本视图中静态 disabled。
    # unilab:node_uuid=7b5dcfec-93c9-5173-8c3c-0accfe029e87 disabled=true
    projected_control_0003 = material.review_control_node_v1(
        operation_name='pf_s10_collect',
        node_path='body/1',
        control_kind='comment',
        expected_sha256='5955a3adc3265a47b8736720cc92d1501ee7b4ccdf0f4d2eeaa6aa582f27a506',
    )
    # [ACTION staging_a.locator_b] 来源 pf_s10_collect@body/2；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=6129c763-e927-54af-b8a8-d84b221454ae disabled=true
    projected_action_0004 = staging_a.locator_b(
        target=False,
    )
    # [ACTION staging_a.locator_a] 来源 pf_s10_collect@body/3；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=4f2060b3-0ea0-53a9-af41-38f5ce6a576f disabled=true
    projected_action_0005 = staging_a.locator_a(
        target=False,
    )
