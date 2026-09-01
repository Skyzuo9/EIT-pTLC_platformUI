from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.robot_suction_put_operation_view_v2 import (
    robot_suction_put_operation_view_v2,
)


material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')


@workflow(
    workflow_uuid='17252b6e-a06c-5dce-a6dc-7943f9ca484d',
    displayname='拍照刮板-板上料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def photoscrape_plate_load_operation_view_v2() -> None:
    # [OPERATION photoscrape_plate_load] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=004d0c48-7b73-5c7f-8f8e-294b3dc430a6 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='photoscrape_plate_load',
        inputs_json='{}',
        expected_sha256='1700cfbb13ba2a34464be3446be51809acb4b49d5af29780ee76ba9f274c65db',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_plate_load@body/0；本视图中静态 disabled。
    # unilab:node_uuid=921544fd-ad12-58bd-a422-0f01840fd260 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='photoscrape_plate_load',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='c09130d84bbc0959a4a189ffdb8721d9f926ee10327f2fc574ae06c38494b205',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 photoscrape_plate_load@body/1；原节点 {"inputs":{"target":{"lit":2}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=e4756660-183f-5110-82c0-763fc13fa268
    nested_operation_0003 = rail_move_safe_operation_view_v2()
    # [VERIFY comment] 只读来源校验 photoscrape_plate_load@body/2；本视图中静态 disabled。
    # unilab:node_uuid=84210230-a7de-53fe-8339-211d2449cd6a disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='photoscrape_plate_load',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='1dab2be17eeb939e5f05cdda6abab036c1e8bc8d8abe8d03343004ba23e6ed8b',
    )
    # [SUBWORKFLOW robot_suction_put] 来源 photoscrape_plate_load@body/3；原节点 {"inputs":{"station_id":{"lit":"scrape"}},"op":"run_script","outputs":{},"script":"robot_suction_put"}
    # unilab:node_uuid=049d3030-67d7-591b-8dc7-66fd4d10fe7c
    nested_operation_0005 = robot_suction_put_operation_view_v2()
    # [VERIFY comment] 只读来源校验 photoscrape_plate_load@body/4；本视图中静态 disabled。
    # unilab:node_uuid=f7939b92-6650-5bf2-9547-f11ca709d6e1 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='photoscrape_plate_load',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='8b7eee6760b1c33a19c19bb503d44fecd4b4bdb7fa010f633dd57dc94bb5357c',
    )
    # [ACTION photoscrape.locate_cylinder] 来源 photoscrape_plate_load@body/5；原节点 {"action":"photoscrape.locate_cylinder","args":{"clamped":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=792d48e8-885a-5c03-b57e-0cc77cd9389f disabled=true
    projected_action_0007 = photoscrape.locate_cylinder(
        clamped=True,
    )
