from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.workflows.robot_group_rack_pick_operation_view_v2 import (
    robot_group_rack_pick_operation_view_v2,
)
from eit_ptlc.workflows.robot_group_staging_put_operation_view_v2 import (
    robot_group_staging_put_operation_view_v2,
)


material: MaterialProxy = device('material')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='6d652cb4-fb9c-572f-bbea-29e14e523a3f',
    displayname='转运-瓶组 货架→中转B (上位机, 参 slot_id) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def transfer_bottle_rack_to_staging_b_operation_view_v2() -> None:
    # [OPERATION transfer_bottle_rack_to_staging_b] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=de565500-9ffc-5d56-91bd-7d8ddc60a524 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='transfer_bottle_rack_to_staging_b',
        inputs_json='{"slot_id":1}',
        expected_sha256='9454d5f3e117e52b9915df1dcad153448f70fc7e885f3a0e1160101c6f859a4d',
    )
    # [VERIFY comment] 只读来源校验 transfer_bottle_rack_to_staging_b@body/0；本视图中静态 disabled。
    # unilab:node_uuid=bc347e9e-01f4-5e95-9858-adfeef5a5765 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='transfer_bottle_rack_to_staging_b',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='a92854b765d0f81d44f72acef8faeb069db5995c71cb2ca7faa1859ccbbddcfd',
    )
    # [SUBWORKFLOW robot_group_rack_pick] 来源 transfer_bottle_rack_to_staging_b@body/1；原节点 {"inputs":{"rack_id":{"lit":"bottle"},"slot_id":{"var":"slot_id"}},"op":"run_script","outputs":{},"script":"robot_group_rack_pick"}
    # unilab:node_uuid=84c90f4f-519c-58fd-bc4d-8c7e209698d1
    nested_operation_0003 = robot_group_rack_pick_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_bottle_rack_to_staging_b@body/2；本视图中静态 disabled。
    # unilab:node_uuid=c6c4baa6-9fc8-56d5-82aa-05ec59c8f9ab disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='transfer_bottle_rack_to_staging_b',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='a458d2f8c7857e784ff38b77fdf6b9cb62b688f33c0fd63a5ddfc8106a8e7aa7',
    )
    # [ACTION staging_a.locator_b] 来源 transfer_bottle_rack_to_staging_b@body/3；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=dd3b9562-6fcb-5283-9c0a-2b2f48e5b4ee disabled=true
    projected_action_0005 = staging_a.locator_b(
        target=False,
    )
    # [VERIFY comment] 只读来源校验 transfer_bottle_rack_to_staging_b@body/4；本视图中静态 disabled。
    # unilab:node_uuid=79a269eb-d67d-542f-ae5a-29fcb3fd9b9a disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='transfer_bottle_rack_to_staging_b',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='12264cb46d230cd7c35504e2bb1a48c9c1478e12ff6d5206aa77c2d7aa3f4d36',
    )
    # [SUBWORKFLOW robot_group_staging_put] 来源 transfer_bottle_rack_to_staging_b@body/5；原节点 {"inputs":{"rack_id":{"lit":"bottle"}},"op":"run_script","outputs":{},"script":"robot_group_staging_put"}
    # unilab:node_uuid=3ea813e3-29c2-5333-a0d8-d5f2b6c78abb
    nested_operation_0007 = robot_group_staging_put_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_bottle_rack_to_staging_b@body/6；本视图中静态 disabled。
    # unilab:node_uuid=8be73f3e-6a85-555f-949b-e744f3f7699c disabled=true
    projected_control_0008 = material.review_control_node_v1(
        operation_name='transfer_bottle_rack_to_staging_b',
        node_path='body/6',
        control_kind='comment',
        expected_sha256='051c9928443d369f57cc2b6d1191d631379837c3e51323e512e04781d16de403',
    )
    # [ACTION staging_a.locator_b] 来源 transfer_bottle_rack_to_staging_b@body/7；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=bd30b78c-d977-5070-8677-fc99891d4cfa disabled=true
    projected_action_0009 = staging_a.locator_b(
        target=True,
    )
