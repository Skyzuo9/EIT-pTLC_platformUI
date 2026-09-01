from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_collect import PLCCollect
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.robot_scrape_holder_pick_enter_operation_view_v2 import (
    robot_scrape_holder_pick_enter_operation_view_v2,
)
from eit_ptlc.workflows.robot_scrape_holder_pick_exit_operation_view_v2 import (
    robot_scrape_holder_pick_exit_operation_view_v2,
)
from eit_ptlc.workflows.robot_collect_holder_put_enter_operation_view_v2 import (
    robot_collect_holder_put_enter_operation_view_v2,
)
from eit_ptlc.workflows.robot_collect_holder_put_exit_operation_view_v2 import (
    robot_collect_holder_put_exit_operation_view_v2,
)
from eit_ptlc.workflows.transfer_bottle_staging_b_to_collect_operation_view_v2 import (
    transfer_bottle_staging_b_to_collect_operation_view_v2,
)


collect: PLCCollect = device('plc_collect')
material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')


@workflow(
    workflow_uuid='085c785c-ad1a-560d-95fc-93c8a4404954',
    displayname='收集-上料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def collect_load_operation_view_v2() -> None:
    # [OPERATION collect_load] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=13bf1091-7baa-55eb-9017-97573ba20ddf disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='collect_load',
        inputs_json='{"bottle_slot":1}',
        expected_sha256='0b1b81a9932f9f34623666c84263182fe9973ed2b0570c82e476c8c000d5cd45',
    )
    # [VERIFY comment] 只读来源校验 collect_load@body/0；本视图中静态 disabled。
    # unilab:node_uuid=d565ba52-0ffe-53c5-bf55-3dc1b432892c disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='collect_load',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='d22617b3c5a20512c63ba4ff13777c3902ef4c0dcab1af270e6e1ce36c62ace6',
    )
    # [VERIFY comment] 只读来源校验 collect_load@body/1；本视图中静态 disabled。
    # unilab:node_uuid=5c349241-7485-5ba5-9875-ee88f81ee1e9 disabled=true
    projected_control_0003 = material.review_control_node_v1(
        operation_name='collect_load',
        node_path='body/1',
        control_kind='comment',
        expected_sha256='e39b990ef44c67991b62cfa973f27b27808671496ce5e7ad4503d76de6743704',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 collect_load@body/2；原节点 {"inputs":{"target":{"lit":2}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=1254b923-aa47-5d5b-99a2-5f3315034d6e
    nested_operation_0004 = rail_move_safe_operation_view_v2()
    # [VERIFY comment] 只读来源校验 collect_load@body/3；本视图中静态 disabled。
    # unilab:node_uuid=aaf2a4d3-a91c-5720-b1ef-491a0db7f81c disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='collect_load',
        node_path='body/3',
        control_kind='comment',
        expected_sha256='78e70af8c03ad6624d22d40e6775dc441a754e4e48fe62e7523832475c309a48',
    )
    # [SUBWORKFLOW robot_scrape_holder_pick_enter] 来源 collect_load@body/4；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_scrape_holder_pick_enter"}
    # unilab:node_uuid=942f03fe-b2dc-5eb9-a93b-f86e53a1d5d1
    nested_operation_0006 = robot_scrape_holder_pick_enter_operation_view_v2()
    # [VERIFY comment] 只读来源校验 collect_load@body/5；本视图中静态 disabled。
    # unilab:node_uuid=80681ea7-5ccf-52f0-a43d-94516fd2b585 disabled=true
    projected_control_0007 = material.review_control_node_v1(
        operation_name='collect_load',
        node_path='body/5',
        control_kind='comment',
        expected_sha256='7c0ef7f227c336e9697ef24f8f07ce3f0d0410971705a91a6533066cf9205b0d',
    )
    # [ACTION photoscrape.press_cylinder] 来源 collect_load@body/6；原节点 {"action":"photoscrape.press_cylinder","args":{"pressed":{"lit":false}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=d7b85851-2eae-54d3-a9cc-3b66a2a08283 disabled=true
    projected_action_0008 = photoscrape.press_cylinder(
        pressed=False,
    )
    # [SUBWORKFLOW robot_scrape_holder_pick_exit] 来源 collect_load@body/7；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_scrape_holder_pick_exit"}
    # unilab:node_uuid=43716b5a-5b65-5abe-8307-9f61ec967903
    nested_operation_0009 = robot_scrape_holder_pick_exit_operation_view_v2()
    # [VERIFY comment] 只读来源校验 collect_load@body/8；本视图中静态 disabled。
    # unilab:node_uuid=7f9125d2-8ffb-55c6-bcaa-73262c4e65d8 disabled=true
    projected_control_0010 = material.review_control_node_v1(
        operation_name='collect_load',
        node_path='body/8',
        control_kind='comment',
        expected_sha256='f7d3fabef020edd0abd77b2b3d02a7a1913f7f5468ed808958fc029d2ce50414',
    )
    # [ACTION photoscrape.retr_stoprot] 来源 collect_load@body/9；原节点 {"action":"photoscrape.retr_stoprot","mode":"RUN","op":"call"}
    # unilab:node_uuid=031b31aa-1b9b-5380-a5b8-164c89182401 disabled=true
    projected_action_0011 = photoscrape.retr_stoprot()
    # [VERIFY comment] 只读来源校验 collect_load@body/10；本视图中静态 disabled。
    # unilab:node_uuid=9542f4d3-0a5b-5f6e-921d-9e58a3602758 disabled=true
    projected_control_0012 = material.review_control_node_v1(
        operation_name='collect_load',
        node_path='body/10',
        control_kind='comment',
        expected_sha256='a599c850a2345e0d6b5a5f95acddcfd69be56dbe8c2ed1470c21c3ebb0e9884d',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 collect_load@body/11；原节点 {"inputs":{"target":{"lit":3}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=f4f2fa13-1068-5455-9938-d5d836d9652b
    nested_operation_0013 = rail_move_safe_operation_view_v2()
    # [VERIFY comment] 只读来源校验 collect_load@body/12；本视图中静态 disabled。
    # unilab:node_uuid=6943ad60-b00e-525d-b3b2-0222c0ba4810 disabled=true
    projected_control_0014 = material.review_control_node_v1(
        operation_name='collect_load',
        node_path='body/12',
        control_kind='comment',
        expected_sha256='29c7bf947379bb7250523912b24eb9a4853bb304924068335784b0d97eae457f',
    )
    # [SUBWORKFLOW robot_collect_holder_put_enter] 来源 collect_load@body/13；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_collect_holder_put_enter"}
    # unilab:node_uuid=0259c572-d213-5ba6-9d06-d0da39e98181
    nested_operation_0015 = robot_collect_holder_put_enter_operation_view_v2()
    # [ACTION collect.clamp] 来源 collect_load@body/14；原节点 {"action":"collect.clamp","mode":"RUN","op":"call"}
    # unilab:node_uuid=ff341bbd-1ebb-5783-befd-a45696154754 disabled=true
    projected_action_0016 = collect.clamp()
    # [SUBWORKFLOW robot_collect_holder_put_exit] 来源 collect_load@body/15；原节点 {"inputs":{"station_id":{"lit":"default"}},"op":"run_script","outputs":{},"script":"robot_collect_holder_put_exit"}
    # unilab:node_uuid=84167e00-e0d0-5275-ac3c-a9a7e2369fad
    nested_operation_0017 = robot_collect_holder_put_exit_operation_view_v2()
    # [ACTION collect.extend] 来源 collect_load@body/16；原节点 {"action":"collect.extend","mode":"RUN","op":"call"}
    # unilab:node_uuid=37f41573-0f7d-5f74-8991-d022a71bf3b1 disabled=true
    projected_action_0018 = collect.extend()
    # [VERIFY comment] 只读来源校验 collect_load@body/17；本视图中静态 disabled。
    # unilab:node_uuid=62639249-91ae-5298-a7fc-7697008f89e1 disabled=true
    projected_control_0019 = material.review_control_node_v1(
        operation_name='collect_load',
        node_path='body/17',
        control_kind='comment',
        expected_sha256='a61d68f877adc716b848e4638c7fddbabc613fc38c27a409acb7ecf8ffe78f72',
    )
    # [SUBWORKFLOW transfer_bottle_staging_b_to_collect] 来源 collect_load@body/18；原节点 {"inputs":{"slot_id":{"var":"bottle_slot"}},"op":"run_script","outputs":{},"script":"transfer_bottle_staging_b_to_collect"}
    # unilab:node_uuid=08b69098-da92-5ebf-917a-46d2ecf77215
    nested_operation_0020 = transfer_bottle_staging_b_to_collect_operation_view_v2()
