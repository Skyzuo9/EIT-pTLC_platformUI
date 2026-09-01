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
    workflow_uuid='9b726c9c-c70e-5393-8815-2b50a42e631b',
    displayname='转运-收集器组 中转A→货架 (上位机, 参 slot_id) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def transfer_collector_staging_a_to_rack_operation_view_v2() -> None:
    # [OPERATION transfer_collector_staging_a_to_rack] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=743ca419-0754-546b-8644-1ce56122ba65 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='transfer_collector_staging_a_to_rack',
        inputs_json='{"slot_id":1}',
        expected_sha256='957a96aefe7f02524c1ae5c45b5e463fd24f008171b63ae9ec45209b54a4bb91',
    )
    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_rack@body/0；本视图中静态 disabled。
    # unilab:node_uuid=f7b7fbaf-ef4f-5c75-b06b-33dbfbb21ea6 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='transfer_collector_staging_a_to_rack',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='0c10039e98bd8fb1a2969f4083e2000c186846b533c5996087ed1cc70ba97630',
    )
    # [ACTION staging_a.locator_a] 来源 transfer_collector_staging_a_to_rack@body/1；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=5f17c01e-8924-5f43-a2a3-25e16618189e disabled=true
    projected_action_0003 = staging_a.locator_a(
        target=False,
    )
    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_rack@body/2；本视图中静态 disabled。
    # unilab:node_uuid=d7e8a908-ca6b-53d3-8997-6e73c8de027e disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='transfer_collector_staging_a_to_rack',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='f127149c514311bedab2c37bf177730410d185721eed531480f52e5945b1885b',
    )
    # [SUBWORKFLOW robot_group_staging_pick] 来源 transfer_collector_staging_a_to_rack@body/3；原节点 {"inputs":{"rack_id":{"lit":"collector"}},"op":"run_script","outputs":{},"script":"robot_group_staging_pick"}
    # unilab:node_uuid=7b6697e0-a236-5746-b342-8f1d0fbc806b
    nested_operation_0005 = robot_group_staging_pick_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_rack@body/4；本视图中静态 disabled。
    # unilab:node_uuid=e0818592-2661-5221-b5d7-29b5d6afd8cf disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='transfer_collector_staging_a_to_rack',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='62481f69228cbbb4dadcb498e8f4f7cf6dde0fc47a9d95e83b0cb2fd7cd288d9',
    )
    # [SUBWORKFLOW robot_group_rack_put] 来源 transfer_collector_staging_a_to_rack@body/5；原节点 {"inputs":{"rack_id":{"lit":"collector"},"slot_id":{"var":"slot_id"}},"op":"run_script","outputs":{},"script":"robot_group_rack_put"}
    # unilab:node_uuid=bf827443-f4a1-5c56-b7f4-275ef255eeba
    nested_operation_0007 = robot_group_rack_put_operation_view_v2()
