from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_develop import PLCDevelop
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.robot_tank_pick_operation_view_v2 import (
    robot_tank_pick_operation_view_v2,
)


develop: PLCDevelop = device('plc_develop')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='868da645-58c1-58a2-aa83-88948e67ed43',
    displayname='展开-下料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def develop_unload_operation_view_v2() -> None:
    # [OPERATION develop_unload] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=fbc90b53-c37c-5bdd-a3df-e6ceda341eb7 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='develop_unload',
        inputs_json='{"tank":1}',
        expected_sha256='14bcfb1d95f9c36300707acd14a4b23627751c734a9ad963182e8f52c1c57489',
    )
    # [VERIFY comment] 只读来源校验 develop_unload@body/0；本视图中静态 disabled。
    # unilab:node_uuid=fc985b4b-df68-5931-b78f-10af83829229 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='develop_unload',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='2beda758cac8314f74ff459463d7f28c737d72ce065de22c3b05f87a5cff73f3',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 develop_unload@body/1；原节点 {"inputs":{"target":{"lit":5}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=e4e04f10-efa7-5996-bee2-7a9724e7f8b4
    nested_operation_0003 = rail_move_safe_operation_view_v2()
    # [VERIFY comment] 只读来源校验 develop_unload@body/2；本视图中静态 disabled。
    # unilab:node_uuid=357196d8-96fd-561b-9003-80e97c2c0f93 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='develop_unload',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='fe8d4b7fe862f45a05c9e482b4803da64c3475f87c42d39c7f701016b2ad919a',
    )
    # [ACTION develop.plate_retract] 来源 develop_unload@body/3；原节点 {"action":"develop.plate_retract","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=a3125eb2-55da-5a4f-bee6-e3c8566aa6b6 disabled=true
    projected_action_0005 = develop.plate_retract(
        target_tank=1,
    )
    # [VERIFY comment] 只读来源校验 develop_unload@body/4；本视图中静态 disabled。
    # unilab:node_uuid=dd6aebce-7fb0-5295-9942-b63517425754 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='develop_unload',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='5abdcb4bd85a722a39a4acc007f07b009d624d3ca0b1a12c403a10a9d53e54f7',
    )
    # [SUBWORKFLOW robot_tank_pick] 来源 develop_unload@body/5；原节点 {"inputs":{"tank_id":{"var":"tank"}},"op":"run_script","outputs":{},"script":"robot_tank_pick"}
    # unilab:node_uuid=99188100-0c31-539f-969b-753a7ad05b5a
    nested_operation_0007 = robot_tank_pick_operation_view_v2()
    # [VERIFY comment] 只读来源校验 develop_unload@body/6；本视图中静态 disabled。
    # unilab:node_uuid=d7da4e8e-71f3-5820-a261-fdd62ea0d361 disabled=true
    projected_control_0008 = material.review_control_node_v1(
        operation_name='develop_unload',
        node_path='body/6',
        control_kind='comment',
        expected_sha256='91242470a85358aff13b2419163f7ea077795bc8c922645d6634f0d29bad516e',
    )
    # [ACTION develop.plate_extend] 来源 develop_unload@body/7；原节点 {"action":"develop.plate_extend","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=801f6bc9-6821-5047-a1eb-0faaa8a00f74 disabled=true
    projected_action_0009 = develop.plate_extend(
        target_tank=1,
    )
    # [VERIFY comment] 只读来源校验 develop_unload@body/8；本视图中静态 disabled。
    # unilab:node_uuid=c0cdc5ed-90a8-5e03-9ddb-d8d23802313d disabled=true
    projected_control_0010 = material.review_control_node_v1(
        operation_name='develop_unload',
        node_path='body/8',
        control_kind='comment',
        expected_sha256='2c2aa0894f821022b11ae6aa9d430edca7a47d8fdf428bee27ca8bc7c29254f8',
    )
    # [ACTION develop.release_tank] 来源 develop_unload@body/9；原节点 {"action":"develop.release_tank","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=33a17d2a-3357-59a7-b73f-3902aad9b599 disabled=true
    projected_action_0011 = develop.release_tank(
        target_tank=1,
    )
