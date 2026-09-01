from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_feedlift import PLCFeedLift
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.robot_feed_lift_pick_enter_operation_view_v2 import (
    robot_feed_lift_pick_enter_operation_view_v2,
)
from eit_ptlc.workflows.robot_feed_lift_pick_exit_operation_view_v2 import (
    robot_feed_lift_pick_exit_operation_view_v2,
)


feedlift: PLCFeedLift = device('plc_feedlift')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='e385b2cf-f3de-5be8-b0d2-c660ab234325',
    displayname='升降上料-周期 (伺服升轴↔机械臂吸板 交错; R2 单站 cycle) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def feedlift_load_cycle_operation_view_v2() -> None:
    # [OPERATION feedlift_load_cycle] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=4c45b4ce-c9b6-5e31-9964-4183baf66984 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='feedlift_load_cycle',
        inputs_json='{}',
        expected_sha256='b89d8c11977845a7e3cf3c29f019e7bcfd6a662e2aa4406227f2b18461030e87',
    )
    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/0；本视图中静态 disabled。
    # unilab:node_uuid=0dd2dce7-205b-5ba5-93fe-e31e634832db disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='feedlift_load_cycle',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='4acdb1112605ade896676c495c39f230fcf686d851254f44bea07c3fa95fb594',
    )
    # [SUBWORKFLOW robot_tool_ensure] 来源 feedlift_load_cycle@body/1；原节点 {"inputs":{"needed":{"lit":1}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=14a5ba43-dc6f-5eed-b7d7-1135f9f6ea54
    nested_operation_0003 = robot_tool_ensure_operation_view_v2()
    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/2；本视图中静态 disabled。
    # unilab:node_uuid=b0dff8e3-3d02-5531-b2c3-3b56515af2fc disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='feedlift_load_cycle',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='9308b8bfbd633d6ab33023e4424e4bc0b919a5228bb62dcc6d296a76dd977ff1',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 feedlift_load_cycle@body/3；原节点 {"inputs":{"target":{"lit":1}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=55a35a93-892f-53a2-91ae-f1061e8d85b9
    nested_operation_0005 = rail_move_safe_operation_view_v2()
    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/4；本视图中静态 disabled。
    # unilab:node_uuid=e88202fd-4f67-5243-a9fa-5f5ffddeb093 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='feedlift_load_cycle',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='0ebf7b01b5b78c9075aac242cca0dd7ba0b9a9cde5e5fa2d287c10e6f4c43b6f',
    )
    # [ACTION feedlift.feed_clear] 来源 feedlift_load_cycle@body/5；原节点 {"action":"feedlift.feed_clear","mode":"RUN","op":"call"}
    # unilab:node_uuid=a7a4365e-8bd5-56ca-a974-2bdd3a48a42f disabled=true
    projected_action_0007 = feedlift.feed_clear()
    # [ACTION feedlift.feed_raise] 来源 feedlift_load_cycle@body/6；原节点 {"action":"feedlift.feed_raise","mode":"RUN","op":"call"}
    # unilab:node_uuid=bf54c51a-edfc-5ebd-8603-8ed2f1ff284b disabled=true
    projected_action_0008 = feedlift.feed_raise()
    # [ACTION feedlift.probe_stack] 来源 feedlift_load_cycle@body/7；原节点 {"action":"feedlift.probe_stack","args":{"magazine":{"lit":"feed"},"reconcile":{"lit":true}},"assign":{"var":"p0"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=bf02e4c9-4231-58dd-860f-d3bf2863cc05 disabled=true
    projected_action_0009 = feedlift.probe_stack(
        magazine='feed',
    )
    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/8；本视图中静态 disabled。
    # unilab:node_uuid=cb29f03d-a960-54a4-bb9c-95ae14a253ed disabled=true
    projected_control_0010 = material.review_control_node_v1(
        operation_name='feedlift_load_cycle',
        node_path='body/8',
        control_kind='comment',
        expected_sha256='2a9d500b0fb7322b9bf2b9e8d24baba3374348e7a7af2aa5fc202bece42bd8eb',
    )
    # [SUBWORKFLOW robot_feed_lift_pick_enter] 来源 feedlift_load_cycle@body/9；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_feed_lift_pick_enter"}
    # unilab:node_uuid=ce3687d8-a511-58f2-aa00-34ffb5490aac
    nested_operation_0011 = robot_feed_lift_pick_enter_operation_view_v2()
    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/10；本视图中静态 disabled。
    # unilab:node_uuid=92e0b3e5-5e23-5081-81ee-6a99f00889f1 disabled=true
    projected_control_0012 = material.review_control_node_v1(
        operation_name='feedlift_load_cycle',
        node_path='body/10',
        control_kind='comment',
        expected_sha256='503bc219bf1316943cf46870de6ec60c377427a59da7cabc70900dc4d1e88978',
    )
    # [ACTION feedlift.feed_lower] 来源 feedlift_load_cycle@body/11；原节点 {"action":"feedlift.feed_lower","mode":"RUN","op":"call"}
    # unilab:node_uuid=757b1c08-3764-53d8-b4c7-6f0a25c76769 disabled=true
    projected_action_0013 = feedlift.feed_lower()
    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/12；本视图中静态 disabled。
    # unilab:node_uuid=e3e332b1-0287-5c27-a191-850d30493398 disabled=true
    projected_control_0014 = material.review_control_node_v1(
        operation_name='feedlift_load_cycle',
        node_path='body/12',
        control_kind='comment',
        expected_sha256='a5df47772713760de82386686f7710196f5e8d1da278eacc7f264a0f18d201a7',
    )
    # [SUBWORKFLOW robot_feed_lift_pick_exit] 来源 feedlift_load_cycle@body/13；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_feed_lift_pick_exit"}
    # unilab:node_uuid=ce544461-8ced-5934-9eac-6eddbec1e218
    nested_operation_0015 = robot_feed_lift_pick_exit_operation_view_v2()
    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/14；本视图中静态 disabled。
    # unilab:node_uuid=03ce8e6f-21d1-5913-8fd0-956ad67db2ed disabled=true
    projected_control_0016 = material.review_control_node_v1(
        operation_name='feedlift_load_cycle',
        node_path='body/14',
        control_kind='comment',
        expected_sha256='e986df8cdf54968443a6bc93f0ace1c8aa5b177b29ae2be33be87916da116f44',
    )
    # [ACTION feedlift.feed_raise] 来源 feedlift_load_cycle@body/15；原节点 {"action":"feedlift.feed_raise","mode":"RUN","op":"call"}
    # unilab:node_uuid=702715f0-f4f8-5119-b052-eddf64b55d17 disabled=true
    projected_action_0017 = feedlift.feed_raise()
    # [ACTION feedlift.probe_stack] 来源 feedlift_load_cycle@body/16；原节点 {"action":"feedlift.probe_stack","args":{"expect_taken":{"lit":1},"magazine":{"lit":"feed"},"z_prev":{"field":{"var":"p0"},"name":"z_mm"}},"assign":{"var":"p1"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=dedef31a-3eb3-583f-aa83-b0ef5d3ec93a disabled=true
    projected_action_0018 = feedlift.probe_stack(
        magazine='feed',
    )
