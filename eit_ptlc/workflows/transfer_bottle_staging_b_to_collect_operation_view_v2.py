from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.workflows.robot_individual_pick_operation_view_v2 import (
    robot_individual_pick_operation_view_v2,
)
from eit_ptlc.workflows.robot_collect_bottle_put_operation_view_v2 import (
    robot_collect_bottle_put_operation_view_v2,
)


material: MaterialProxy = device('material')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='82965ffe-8251-5181-84a5-de1c75c7b189',
    displayname='转运-单瓶 中转B→收集工位 (上位机, 参 slot_id) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def transfer_bottle_staging_b_to_collect_operation_view_v2() -> None:
    # [OPERATION transfer_bottle_staging_b_to_collect] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=15e14aae-970c-51db-b972-4d31e423dafa disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='transfer_bottle_staging_b_to_collect',
        inputs_json='{"slot_id":1}',
        expected_sha256='441eac8582d2ef67d63d318e2911531c1b9b093d7f2ebf8e0859c3e20e574b72',
    )
    # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_collect@body/0；本视图中静态 disabled。
    # unilab:node_uuid=1270c05c-056e-5737-b6c9-6fbc5407cb73 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='transfer_bottle_staging_b_to_collect',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='689def4f830e57173646dd6a5ef11ece7baefcad5320003979c4641492934528',
    )
    # [ACTION staging_a.locator_b] 来源 transfer_bottle_staging_b_to_collect@body/1；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=8f940385-e56c-5c61-af4d-141ec21887e4 disabled=true
    projected_action_0003 = staging_a.locator_b(
        target=True,
    )
    # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_collect@body/2；本视图中静态 disabled。
    # unilab:node_uuid=a64ed1c3-1803-5ebb-9d6c-49e17210d29c disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='transfer_bottle_staging_b_to_collect',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='a3ef62d89f9507ece1746554ff4bc2fd8308f0caed6228a0c8df9b9f0ea37336',
    )
    # [SUBWORKFLOW robot_individual_pick] 来源 transfer_bottle_staging_b_to_collect@body/3；原节点 {"inputs":{"exit_anchor":{"lit":"P52"},"rack_id":{"lit":"bottle"},"slot_id":{"var":"slot_id"}},"op":"run_script","outputs":{},"script":"robot_individual_pick"}
    # unilab:node_uuid=21192273-1380-5110-a698-e62bd5c8e0cc
    nested_operation_0005 = robot_individual_pick_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_collect@body/4；本视图中静态 disabled。
    # unilab:node_uuid=34835d6e-3139-5225-876a-985f3ddefe93 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='transfer_bottle_staging_b_to_collect',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='d45be0f3d867f4e176e1fd854935b0fa8881837922a442ef5280c06aa7234a7d',
    )
    # [SUBWORKFLOW robot_collect_bottle_put] 来源 transfer_bottle_staging_b_to_collect@body/5；原节点 {"inputs":{"enter_anchor":{"lit":"P52"},"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_collect_bottle_put"}
    # unilab:node_uuid=01c2ae48-786c-59d9-976c-4afbc8c9dfce
    nested_operation_0007 = robot_collect_bottle_put_operation_view_v2()
