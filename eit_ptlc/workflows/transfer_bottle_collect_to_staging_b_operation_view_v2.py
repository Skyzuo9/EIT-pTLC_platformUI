from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.workflows.robot_collect_bottle_pick_operation_view_v2 import (
    robot_collect_bottle_pick_operation_view_v2,
)
from eit_ptlc.workflows.robot_individual_put_operation_view_v2 import (
    robot_individual_put_operation_view_v2,
)


material: MaterialProxy = device('material')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='33397f8b-de86-537b-839a-8b222218f79d',
    displayname='转运-单瓶 收集工位→中转B (上位机, 参 slot_id) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def transfer_bottle_collect_to_staging_b_operation_view_v2() -> None:
    # [OPERATION transfer_bottle_collect_to_staging_b] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=fd1d8b02-1431-5365-b1af-53c1762803a9 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='transfer_bottle_collect_to_staging_b',
        inputs_json='{"slot_id":1}',
        expected_sha256='0b958704e4738280563c5087be1b13ea7182a9bcfa2e2c480f642d732abaac81',
    )
    # [VERIFY comment] 只读来源校验 transfer_bottle_collect_to_staging_b@body/0；本视图中静态 disabled。
    # unilab:node_uuid=92f83635-6fe4-5e77-b639-ce1d4ed7798a disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='transfer_bottle_collect_to_staging_b',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='7c53d8d84eedce4cfa2f61e8169ecbabc51fe6fb45144c059e6c9df08dc2ad0d',
    )
    # [SUBWORKFLOW robot_collect_bottle_pick] 来源 transfer_bottle_collect_to_staging_b@body/1；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_collect_bottle_pick"}
    # unilab:node_uuid=57486fb2-ff78-5a06-87d0-8f30b37ceb92
    nested_operation_0003 = robot_collect_bottle_pick_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_bottle_collect_to_staging_b@body/2；本视图中静态 disabled。
    # unilab:node_uuid=9df5e64e-59fc-5975-9867-85b9c3191660 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='transfer_bottle_collect_to_staging_b',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='5f0a4c1c3736f1891c393ca5e77819b7d4fe4be9cf56b8cdc763d2ddaa2909b7',
    )
    # [ACTION staging_a.locator_b] 来源 transfer_bottle_collect_to_staging_b@body/3；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=3947b405-4525-5fc5-b1ce-e27f0fec2d7d disabled=true
    projected_action_0005 = staging_a.locator_b(
        target=True,
    )
    # [VERIFY comment] 只读来源校验 transfer_bottle_collect_to_staging_b@body/4；本视图中静态 disabled。
    # unilab:node_uuid=2dd87d3d-8c93-5254-b1dc-660abf8b14ec disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='transfer_bottle_collect_to_staging_b',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='d4dc1f500f03544058a9dfdd7347e2ab593b36d78d03c55aea267d6f7cde49a1',
    )
    # [SUBWORKFLOW robot_individual_put] 来源 transfer_bottle_collect_to_staging_b@body/5；原节点 {"inputs":{"enter_anchor":{"lit":"P70"},"rack_id":{"lit":"bottle"},"slot_id":{"var":"slot_id"}},"op":"run_script","outputs":{},"script":"robot_individual_put"}
    # unilab:node_uuid=8cbdecae-f472-52f2-9b83-8e24fa8b45f1
    nested_operation_0007 = robot_individual_put_operation_view_v2()
