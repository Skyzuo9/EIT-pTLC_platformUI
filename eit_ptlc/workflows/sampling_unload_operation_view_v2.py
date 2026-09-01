from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_sampling import PLCSampling
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.robot_suction_pick_operation_view_v2 import (
    robot_suction_pick_operation_view_v2,
)


material: MaterialProxy = device('material')
sampling: PLCSampling = device('plc_sampling')


@workflow(
    workflow_uuid='c78c26fa-36b3-5181-bf0b-caeba50b7fb0',
    displayname='上样-下料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def sampling_unload_operation_view_v2() -> None:
    # [OPERATION sampling_unload] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=9b31f5af-8c59-5cbc-9e5b-29b3849799f2 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='sampling_unload',
        inputs_json='{}',
        expected_sha256='bd0787ea8d44165a2188ad9385280e7e79a49a0af74dce76fd6c156915c47a34',
    )
    # [VERIFY comment] 只读来源校验 sampling_unload@body/0；本视图中静态 disabled。
    # unilab:node_uuid=ef6d826c-354f-5aaa-ae78-212449c9ee75 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='sampling_unload',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='e32199707f27c99f7660635456603939b8c9c90696074927bfcae0750c96bc5c',
    )
    # [VERIFY comment] 只读来源校验 sampling_unload@body/1；本视图中静态 disabled。
    # unilab:node_uuid=614803e1-a2c5-5c07-bcc8-011b121338c3 disabled=true
    projected_control_0003 = material.review_control_node_v1(
        operation_name='sampling_unload',
        node_path='body/1',
        control_kind='comment',
        expected_sha256='25bc708652757982bd004b069ade76b535dc5798e7f030aca2238492a02d482c',
    )
    # [VERIFY comment] 只读来源校验 sampling_unload@body/2；本视图中静态 disabled。
    # unilab:node_uuid=fe7d74a1-fcca-5c82-9ffe-b5eeecde359f disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='sampling_unload',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='b5741b2c6e3a156f79e99e9298c66a9a85379569839be23075639e804e4d0838',
    )
    # [ACTION sampling.place_axis] 来源 sampling_unload@body/3；原节点 {"action":"sampling.place_axis","mode":"RUN","op":"call"}
    # unilab:node_uuid=f4da2f30-6722-5487-acb7-e4eb6b811fac disabled=true
    projected_action_0005 = sampling.place_axis()
    # [ACTION sampling.place_release] 来源 sampling_unload@body/4；原节点 {"action":"sampling.place_release","mode":"RUN","op":"call"}
    # unilab:node_uuid=9c3f381f-7de5-55d0-a50b-d56daedcb0f5 disabled=true
    projected_action_0006 = sampling.place_release()
    # [VERIFY comment] 只读来源校验 sampling_unload@body/5；本视图中静态 disabled。
    # unilab:node_uuid=17e32739-e344-5a91-bb45-fd13da349952 disabled=true
    projected_control_0007 = material.review_control_node_v1(
        operation_name='sampling_unload',
        node_path='body/5',
        control_kind='comment',
        expected_sha256='3a2032a34a7b8ee9aa6aa4a86dc8c970dc5af8d74e19b5de5fd63525583730c3',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 sampling_unload@body/6；原节点 {"inputs":{"target":{"lit":1}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=e98d96ac-55ca-5d17-91f9-a3159498abc3
    nested_operation_0008 = rail_move_safe_operation_view_v2()
    # [SUBWORKFLOW robot_suction_pick] 来源 sampling_unload@body/7；原节点 {"inputs":{"station_id":{"lit":"spotting"}},"op":"run_script","outputs":{},"script":"robot_suction_pick"}
    # unilab:node_uuid=4bf1a568-1cdc-5c5e-805a-048b068e08c3
    nested_operation_0009 = robot_suction_pick_operation_view_v2()
