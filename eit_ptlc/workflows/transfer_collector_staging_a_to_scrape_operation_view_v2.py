from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.robot_individual_pick_operation_view_v2 import (
    robot_individual_pick_operation_view_v2,
)
from eit_ptlc.workflows.robot_scrape_holder_put_enter_operation_view_v2 import (
    robot_scrape_holder_put_enter_operation_view_v2,
)
from eit_ptlc.workflows.robot_scrape_holder_put_exit_operation_view_v2 import (
    robot_scrape_holder_put_exit_operation_view_v2,
)


material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='886b5a2b-1896-500a-93a9-170c739ce960',
    displayname='转运-单收集器 中转A→刮板夹具 (上位机, 参 slot_id) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def transfer_collector_staging_a_to_scrape_operation_view_v2() -> None:
    # [OPERATION transfer_collector_staging_a_to_scrape] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=da7aa828-f3aa-58ea-863a-4d4d7a2f7646 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='transfer_collector_staging_a_to_scrape',
        inputs_json='{"slot_id":1}',
        expected_sha256='2759a71117c20b9499de51f7e8a567504611d1175db60b53512eea0c92be5d85',
    )
    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/0；本视图中静态 disabled。
    # unilab:node_uuid=6cca3846-aada-5650-b77b-e64b7e4c69b5 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='transfer_collector_staging_a_to_scrape',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='3739b2b1dc16f5183ccab2794bfc7c271750731112496ba53bd2d15f1fde36e0',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 transfer_collector_staging_a_to_scrape@body/1；原节点 {"inputs":{"target":{"lit":2}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=8cc2f371-0417-5ff1-902e-e4c425fe5980
    nested_operation_0003 = rail_move_safe_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/2；本视图中静态 disabled。
    # unilab:node_uuid=e30b26e3-96ea-51a0-bcc0-bccd0e4e158c disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='transfer_collector_staging_a_to_scrape',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='070f2fef18f2f549fa4de453b1f7abef1610a3e484c8bcf8ca521a994bcd0ece',
    )
    # [ACTION staging_a.locator_a] 来源 transfer_collector_staging_a_to_scrape@body/3；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=1be8751a-1244-5c0c-9641-8a28b329a65f disabled=true
    projected_action_0005 = staging_a.locator_a(
        target=True,
    )
    # [SUBWORKFLOW robot_individual_pick] 来源 transfer_collector_staging_a_to_scrape@body/4；原节点 {"inputs":{"rack_id":{"lit":"collector"},"slot_id":{"var":"slot_id"}},"op":"run_script","outputs":{},"script":"robot_individual_pick"}
    # unilab:node_uuid=a3f67f29-9040-5d3d-ac23-c46ff9ce1043
    nested_operation_0006 = robot_individual_pick_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/5；本视图中静态 disabled。
    # unilab:node_uuid=04a5a481-5124-5ae3-9e5e-55b6a3fa03bd disabled=true
    projected_control_0007 = material.review_control_node_v1(
        operation_name='transfer_collector_staging_a_to_scrape',
        node_path='body/5',
        control_kind='comment',
        expected_sha256='855499bf7fd92f6943e05a5742590c861532d34580f0b26a5770424a017953f3',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 transfer_collector_staging_a_to_scrape@body/6；原节点 {"inputs":{"target":{"lit":2}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=46c633e9-1b24-5cec-96e8-70dfd5907f34
    nested_operation_0008 = rail_move_safe_operation_view_v2()
    # [SUBWORKFLOW robot_scrape_holder_put_enter] 来源 transfer_collector_staging_a_to_scrape@body/7；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_scrape_holder_put_enter"}
    # unilab:node_uuid=dc90f2f8-db2a-5a6b-a392-18dc3cba7fce
    nested_operation_0009 = robot_scrape_holder_put_enter_operation_view_v2()
    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/8；本视图中静态 disabled。
    # unilab:node_uuid=89e09402-b07e-5203-b44d-ace298643b79 disabled=true
    projected_control_0010 = material.review_control_node_v1(
        operation_name='transfer_collector_staging_a_to_scrape',
        node_path='body/8',
        control_kind='comment',
        expected_sha256='c9334a73422d291c6f604a5ae405f8c4ca620b2c55ddbefb803db235c7801c57',
    )
    # [ACTION photoscrape.press_cylinder] 来源 transfer_collector_staging_a_to_scrape@body/9；原节点 {"action":"photoscrape.press_cylinder","args":{"pressed":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=ed6abc0d-43c7-53c5-8a60-b1cd64c2aa72 disabled=true
    projected_action_0011 = photoscrape.press_cylinder(
        pressed=True,
    )
    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/10；本视图中静态 disabled。
    # unilab:node_uuid=5eb144b2-cea9-55ec-8150-73c76ce6cf19 disabled=true
    projected_control_0012 = material.review_control_node_v1(
        operation_name='transfer_collector_staging_a_to_scrape',
        node_path='body/10',
        control_kind='comment',
        expected_sha256='59bd34c997874336c64e830b7836720460df4f403ba36fcd3465453b75033a29',
    )
    # [SUBWORKFLOW robot_scrape_holder_put_exit] 来源 transfer_collector_staging_a_to_scrape@body/11；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_scrape_holder_put_exit"}
    # unilab:node_uuid=2bb173b8-662f-5721-9cf3-857a8434c3ca
    nested_operation_0013 = robot_scrape_holder_put_exit_operation_view_v2()
