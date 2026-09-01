from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_develop import PLCDevelop
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.robot_tank_put_operation_view_v2 import (
    robot_tank_put_operation_view_v2,
)


develop: PLCDevelop = device('plc_develop')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='a147ebec-8cd4-50f9-9cd0-a8dcd97d136c',
    displayname='展开-上料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def develop_load_operation_view_v2() -> None:
    # [OPERATION develop_load] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=3e808b63-66f7-5953-8041-0c00918a789a disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='develop_load',
        inputs_json='{"tank":1}',
        expected_sha256='5ffca8c5617155e4d5b8c901b3d977b82d1ac84f25eca0e9c2b20792deaaf057',
    )
    # [VERIFY comment] 只读来源校验 develop_load@body/0；本视图中静态 disabled。
    # unilab:node_uuid=fd9aa203-da7a-5ef8-b5a7-7e93fc543cab disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='develop_load',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='9e52f477960de30727544183d80dd63c5c386a99b5f98d17852c8576156c7100',
    )
    # [ACTION develop.plate_retract] 来源 develop_load@body/1；原节点 {"action":"develop.plate_retract","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=235ddc40-1af0-5174-afd5-e780d5caf988 disabled=true
    projected_action_0003 = develop.plate_retract(
        target_tank=1,
    )
    # [SUBWORKFLOW robot_tank_put] 来源 develop_load@body/2；原节点 {"inputs":{"tank_id":{"var":"tank"}},"op":"run_script","outputs":{},"script":"robot_tank_put"}
    # unilab:node_uuid=9ad2d06a-ae6a-5f8a-8688-da41f45d5244
    nested_operation_0004 = robot_tank_put_operation_view_v2()
    # [VERIFY comment] 只读来源校验 develop_load@body/3；本视图中静态 disabled。
    # unilab:node_uuid=20188e72-6203-52ab-9c5f-be960b7c59be disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='develop_load',
        node_path='body/3',
        control_kind='comment',
        expected_sha256='33e1f53125c648616fbd4e7a62aa6617558fea2a18a89afdfc7d05beea884fad',
    )
    # [ACTION develop.plate_extend] 来源 develop_load@body/4；原节点 {"action":"develop.plate_extend","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=f8feea65-6855-5a96-b8b7-9c395d7d5cc8 disabled=true
    projected_action_0006 = develop.plate_extend(
        target_tank=1,
    )
