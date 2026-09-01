from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.robot_suction_pick_operation_view_v2 import (
    robot_suction_pick_operation_view_v2,
)


material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')


@workflow(
    workflow_uuid='c16ab294-a2be-56a0-a137-e83097969bbc',
    displayname='拍照刮板-下料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def photoscrape_unload_operation_view_v2() -> None:
    # [OPERATION photoscrape_unload] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=51293ce6-b80f-5e97-8aae-201aa3271c61 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='photoscrape_unload',
        inputs_json='{}',
        expected_sha256='fe16b40bc8dd7c3f42fc8bfbaac98c160d37398221e283e609b66cec4d72cddf',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_unload@body/0；本视图中静态 disabled。
    # unilab:node_uuid=8c25a338-5ec8-5d17-8553-55e063bfe9c5 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='photoscrape_unload',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='090f54ab39d61c0f619db3e62dd8567d1c8cd386f721a4cd80841f8b2960a951',
    )
    # [SUBWORKFLOW robot_tool_ensure] 来源 photoscrape_unload@body/1；原节点 {"inputs":{"needed":{"lit":1}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=65e36af7-8c17-5e97-841a-e36e0c4bc136
    nested_operation_0003 = robot_tool_ensure_operation_view_v2()
    # [VERIFY comment] 只读来源校验 photoscrape_unload@body/2；本视图中静态 disabled。
    # unilab:node_uuid=a5a8f066-f05e-5112-ae88-d74a890fffb0 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='photoscrape_unload',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='f757b741e63ecef01416b43876c84f448fc33fd8263c1eaa57e30a885a8bc2c2',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 photoscrape_unload@body/3；原节点 {"inputs":{"target":{"lit":2}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=2ed10af3-d0c5-550c-bf12-3c4351cd97fc
    nested_operation_0005 = rail_move_safe_operation_view_v2()
    # [VERIFY comment] 只读来源校验 photoscrape_unload@body/4；本视图中静态 disabled。
    # unilab:node_uuid=939fe41e-5460-5d66-99f1-189d8ddb926d disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='photoscrape_unload',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='2e88f06e980d94312534dddefa1ec480813bffd17a96170f584aa1ef8e268ad7',
    )
    # [ACTION photoscrape.press_cylinder] 来源 photoscrape_unload@body/5；原节点 {"action":"photoscrape.press_cylinder","args":{"pressed":{"lit":false}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=e1d42c74-c1e5-5923-9a8a-6f4253d83ed0 disabled=true
    projected_action_0007 = photoscrape.press_cylinder(
        pressed=False,
    )
    # [VERIFY comment] 只读来源校验 photoscrape_unload@body/6；本视图中静态 disabled。
    # unilab:node_uuid=1deae594-3a8a-53f8-92a4-ac74d7b58ed7 disabled=true
    projected_control_0008 = material.review_control_node_v1(
        operation_name='photoscrape_unload',
        node_path='body/6',
        control_kind='comment',
        expected_sha256='24a83be66051ea0aabfd800e906bd880439b5531b0e83a4dc22552f0cf80785f',
    )
    # [ACTION photoscrape.locate_cylinder] 来源 photoscrape_unload@body/7；原节点 {"action":"photoscrape.locate_cylinder","args":{"clamped":{"lit":false}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=a859c0f6-bf21-534a-b902-df01da42c1d9 disabled=true
    projected_action_0009 = photoscrape.locate_cylinder(
        clamped=False,
    )
    # [VERIFY comment] 只读来源校验 photoscrape_unload@body/8；本视图中静态 disabled。
    # unilab:node_uuid=b1a07f63-9916-55f3-b341-6e2a7c7c120f disabled=true
    projected_control_0010 = material.review_control_node_v1(
        operation_name='photoscrape_unload',
        node_path='body/8',
        control_kind='comment',
        expected_sha256='b1aa2e95cccd55c66d6920ddfbcab498ad85ed79d4e37091bab682a6367a685f',
    )
    # [SUBWORKFLOW robot_suction_pick] 来源 photoscrape_unload@body/9；原节点 {"inputs":{"station_id":{"lit":"scrape"}},"op":"run_script","outputs":{},"script":"robot_suction_pick"}
    # unilab:node_uuid=2e437297-87dc-5b35-b46d-0471eafd40e4
    nested_operation_0011 = robot_suction_pick_operation_view_v2()
