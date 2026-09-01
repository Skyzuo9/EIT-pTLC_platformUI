from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_collect import PLCCollect
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.transfer_bottle_collect_to_staging_b_operation_view_v2 import (
    transfer_bottle_collect_to_staging_b_operation_view_v2,
)
from eit_ptlc.workflows.robot_collect_holder_pick_enter_operation_view_v2 import (
    robot_collect_holder_pick_enter_operation_view_v2,
)
from eit_ptlc.workflows.robot_collect_holder_pick_exit_operation_view_v2 import (
    robot_collect_holder_pick_exit_operation_view_v2,
)
from eit_ptlc.workflows.robot_collector_return_put_operation_view_v2 import (
    robot_collector_return_put_operation_view_v2,
)


collect: PLCCollect = device('plc_collect')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='14a77545-a1a8-5caa-92e0-f74d14866919',
    displayname='收集-下料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def collect_unload_operation_view_v2() -> None:
    # [OPERATION collect_unload] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=efd7728d-5ec3-5688-bdb2-af741ff5b62c disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='collect_unload',
        inputs_json='{"bottle_slot":1,"collector_slot":1}',
        expected_sha256='3bc396b991a438442b2eba5c30981b74a0cd71a1f15002158fc197c76862db91',
    )
    # [VERIFY comment] 只读来源校验 collect_unload@body/0；本视图中静态 disabled。
    # unilab:node_uuid=430f288d-2886-5b0c-a00c-b3a6dd11b35d disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='collect_unload',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='e74de94ebd951ce56e510c2b7a2673722325cc6ae30cf7ea97c783ea7a0c4e60',
    )
    # [SUBWORKFLOW transfer_bottle_collect_to_staging_b] 来源 collect_unload@body/1；原节点 {"inputs":{"slot_id":{"var":"bottle_slot"}},"op":"run_script","outputs":{},"script":"transfer_bottle_collect_to_staging_b"}
    # unilab:node_uuid=0aa19800-7fcb-552f-89f1-49b23c369682
    nested_operation_0003 = transfer_bottle_collect_to_staging_b_operation_view_v2()
    # [VERIFY comment] 只读来源校验 collect_unload@body/2；本视图中静态 disabled。
    # unilab:node_uuid=be34e083-3f41-5e2e-9f4c-59e2981f99e6 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='collect_unload',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='e6b7b29fa6b24cf7f5cf9e680bd17294995f37909d17dbf8701a8a9968f694ad',
    )
    # [ACTION collect.retract] 来源 collect_unload@body/3；原节点 {"action":"collect.retract","mode":"RUN","op":"call"}
    # unilab:node_uuid=bedb31ca-e531-58ee-bd8e-36c092424981 disabled=true
    projected_action_0005 = collect.retract()
    # [SUBWORKFLOW robot_collect_holder_pick_enter] 来源 collect_unload@body/4；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_collect_holder_pick_enter"}
    # unilab:node_uuid=e0f28ed3-a888-5de1-9d7e-09a4a6e1cd7d
    nested_operation_0006 = robot_collect_holder_pick_enter_operation_view_v2()
    # [ACTION collect.release_clamp] 来源 collect_unload@body/5；原节点 {"action":"collect.release_clamp","mode":"RUN","op":"call"}
    # unilab:node_uuid=47e50bb4-4484-5911-9937-f9f0a6461ab1 disabled=true
    projected_action_0007 = collect.release_clamp()
    # [SUBWORKFLOW robot_collect_holder_pick_exit] 来源 collect_unload@body/6；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_collect_holder_pick_exit"}
    # unilab:node_uuid=f4572148-f017-583e-a78f-604379a36abf
    nested_operation_0008 = robot_collect_holder_pick_exit_operation_view_v2()
    # [VERIFY comment] 只读来源校验 collect_unload@body/7；本视图中静态 disabled。
    # unilab:node_uuid=a6bf10e6-be2a-5eb0-afcb-0480b52e494a disabled=true
    projected_control_0009 = material.review_control_node_v1(
        operation_name='collect_unload',
        node_path='body/7',
        control_kind='comment',
        expected_sha256='cc0466de9d8f030a14f5be93c3990c2603fc2967fa733958a5de8ea9dafa213e',
    )
    # [SUBWORKFLOW robot_collector_return_put] 来源 collect_unload@body/8；原节点 {"inputs":{"enter_anchor":{"lit":"P70"},"slot_id":{"var":"collector_slot"}},"op":"run_script","outputs":{},"script":"robot_collector_return_put"}
    # unilab:node_uuid=05b7264f-e5fb-55cf-bcfb-4a5a54f21f8f
    nested_operation_0010 = robot_collector_return_put_operation_view_v2()
