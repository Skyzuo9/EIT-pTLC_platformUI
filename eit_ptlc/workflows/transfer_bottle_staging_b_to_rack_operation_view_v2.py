from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.workflows.robot_group_staging_pick_operation_view_v2 import (
    robot_group_staging_pick_operation_view_v2,
)
from eit_ptlc.workflows.robot_group_rack_put_operation_view_v2 import (
    robot_group_rack_put_operation_view_v2,
)


material: MaterialProxy = device('material')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='8119ce75-e109-5505-99ce-f4d12cb4bbd0',
    displayname='转运-瓶组 中转B→货架 (上位机, 参 slot_id) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def transfer_bottle_staging_b_to_rack_operation_view_v2() -> None:
    # [OPERATION transfer_bottle_staging_b_to_rack] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=a12b7fea-bb43-5762-b655-da184e0b03bd disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='transfer_bottle_staging_b_to_rack',
        inputs_json='{"slot_id":1}',
        expected_sha256='3976f27812fd83db8666f87fae8d31da6a372dab490ba48e2ffc16857fdf000d',
    )
    # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_rack@body/0；本视图中静态 disabled。
    # unilab:node_uuid=9b5d4d43-6062-5efe-a4a4-e5e81758a077 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='transfer_bottle_staging_b_to_rack',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='bc991ad1c728d83f7fe72c9210978816945b8b712052844c9bc15d5688d70143',
    )
    # [ACTION staging_a.locator_b] 来源 transfer_bottle_staging_b_to_rack@body/1；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=32579ea3-fe63-5691-8a13-bb72e2eeebff disabled=true
    projected_action_0003 = staging_a.locator_b(
        target=False,
    )
    # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_rack@body/2；本视图中静态 disabled。
    # unilab:node_uuid=15d387bf-7b98-596d-b18c-d34e0d414102 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='transfer_bottle_staging_b_to_rack',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='77274029c2d93583b190df167fb981342a1fc9eb9f9e165cb0873d12735f986f',
    )
    # [SUBWORKFLOW robot_group_staging_pick] 来源 transfer_bottle_staging_b_to_rack@body/3；原节点 {"inputs":{"rack_id":{"lit":"bottle"}},"op":"run_script","outputs":{},"script":"robot_group_staging_pick"}
    # unilab:node_uuid=3571b1c7-e50a-5a1b-9970-ea9cf5f38867
    nested_operation_0005 = robot_group_staging_pick_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_rack@body/4；本视图中静态 disabled。
    # unilab:node_uuid=d9760acd-ab2c-5ba7-b764-55d6a5c629e6 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='transfer_bottle_staging_b_to_rack',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='6c3ca15e34cfa6fa0490e42abdc7fe479de26249808fcf40da4c99050d4cf5f7',
    )
    # [SUBWORKFLOW robot_group_rack_put] 来源 transfer_bottle_staging_b_to_rack@body/5；原节点 {"inputs":{"rack_id":{"lit":"bottle"},"slot_id":{"var":"slot_id"}},"op":"run_script","outputs":{},"script":"robot_group_rack_put"}
    # unilab:node_uuid=f002a16e-eec4-51ef-958c-151d85e8e3d8
    nested_operation_0007 = robot_group_rack_put_operation_view_v2()
