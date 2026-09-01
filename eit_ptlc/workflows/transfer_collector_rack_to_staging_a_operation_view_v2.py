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
    workflow_uuid='d3b0d482-ff76-5d9f-a854-b21dd59e5799',
    displayname='转运-收集器组 货架→中转A (上位机, 参 slot_id) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def transfer_collector_rack_to_staging_a_operation_view_v2() -> None:
    # [OPERATION transfer_collector_rack_to_staging_a] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=5521e666-bf00-5142-b957-b9828f4a5e16 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='transfer_collector_rack_to_staging_a',
        inputs_json='{"slot_id":1}',
        expected_sha256='8cf31951d61f466a61575c5d29e944de3f2d0d7880017208b0d3d08e43658e58',
    )
    # [VERIFY comment] 只读来源校验 transfer_collector_rack_to_staging_a@body/0；本视图中静态 disabled。
    # unilab:node_uuid=0d51514d-85dd-5edc-895e-94108dfd9a13 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='transfer_collector_rack_to_staging_a',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='ad0cf7d202cfd46e6424db1fa1b2a4eebf41360fc16b8113ca52354653205ab2',
    )
    # [SUBWORKFLOW robot_group_rack_pick] 来源 transfer_collector_rack_to_staging_a@body/1；原节点 {"inputs":{"rack_id":{"lit":"collector"},"slot_id":{"var":"slot_id"}},"op":"run_script","outputs":{},"script":"robot_group_rack_pick"}
    # unilab:node_uuid=5cb380b3-ad20-5860-ab8c-913db51ef58b
    nested_operation_0003 = robot_group_rack_pick_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_collector_rack_to_staging_a@body/2；本视图中静态 disabled。
    # unilab:node_uuid=6112cc30-1368-5660-890f-f1939f4539ae disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='transfer_collector_rack_to_staging_a',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='874b52ca18b9c1e742846ffeddc5fd49d4bf4b83cd270a706f7e8ff4f05d6315',
    )
    # [ACTION staging_a.locator_a] 来源 transfer_collector_rack_to_staging_a@body/3；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=7bb382cf-7cf9-5a79-afab-e5eda89fecea disabled=true
    projected_action_0005 = staging_a.locator_a(
        target=False,
    )
    # [VERIFY comment] 只读来源校验 transfer_collector_rack_to_staging_a@body/4；本视图中静态 disabled。
    # unilab:node_uuid=b2cf8c10-ee4d-5f64-bbdc-4476d5b4aa3c disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='transfer_collector_rack_to_staging_a',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='0acc0b5c152e0d671128450553bc905a4afc0d545b06787b95c2d423d254feaa',
    )
    # [SUBWORKFLOW robot_group_staging_put] 来源 transfer_collector_rack_to_staging_a@body/5；原节点 {"inputs":{"rack_id":{"lit":"collector"}},"op":"run_script","outputs":{},"script":"robot_group_staging_put"}
    # unilab:node_uuid=8a3b4362-edaa-576b-b76d-ebc8e3861a33
    nested_operation_0007 = robot_group_staging_put_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_collector_rack_to_staging_a@body/6；本视图中静态 disabled。
    # unilab:node_uuid=6edd1975-0d6d-591b-b3f1-e9436b90863a disabled=true
    projected_control_0008 = material.review_control_node_v1(
        operation_name='transfer_collector_rack_to_staging_a',
        node_path='body/6',
        control_kind='comment',
        expected_sha256='2d0b62dec54e4a38231ef77c6f73193f67df25879893c8139e80135a29b3372a',
    )
    # [ACTION staging_a.locator_a] 来源 transfer_collector_rack_to_staging_a@body/7；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=e346499c-e7c1-5717-81bc-f339a979e4c5 disabled=true
    projected_action_0009 = staging_a.locator_a(
        target=True,
    )
