from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_feedlift import PLCFeedLift
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.robot_suction_put_operation_view_v2 import (
    robot_suction_put_operation_view_v2,
)


feedlift: PLCFeedLift = device('plc_feedlift')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='81b8b6ae-15cd-5031-856c-b4a71153fcdd',
    displayname='废料下料-周期 (伺服升轴接料↔机械臂放废板 交错; R2 单站 cycle) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def feedlift_unload_cycle_operation_view_v2() -> None:
    # [OPERATION feedlift_unload_cycle] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=47ebff60-39cd-582a-b163-4e05dc85ede1 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='feedlift_unload_cycle',
        inputs_json='{}',
        expected_sha256='317e8e3fe17abbfb5ad8b207ebde1ec5e61bc44e662fdc685aaee9cbb0f588ee',
    )
    # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/0；本视图中静态 disabled。
    # unilab:node_uuid=fbe12664-0885-5d29-969d-9455ff67deec disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='feedlift_unload_cycle',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='4acdb1112605ade896676c495c39f230fcf686d851254f44bea07c3fa95fb594',
    )
    # [SUBWORKFLOW robot_tool_ensure] 来源 feedlift_unload_cycle@body/1；原节点 {"inputs":{"needed":{"lit":1}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=d5570dc9-f3e5-56f9-95b0-bc85f8e27d35
    nested_operation_0003 = robot_tool_ensure_operation_view_v2()
    # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/2；本视图中静态 disabled。
    # unilab:node_uuid=56ca8ed5-8e3d-57b6-86bc-fd8d83e4ba22 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='feedlift_unload_cycle',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='2e6b1f7c6a64f2d4cf2d36e3d93ac046825a6491b280709c346f5686410c2c60',
    )
    # [SUBWORKFLOW rail_move_safe] 来源 feedlift_unload_cycle@body/3；原节点 {"inputs":{"target":{"lit":1}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=8d28449d-16b9-5caa-b672-141b44df09d8
    nested_operation_0005 = rail_move_safe_operation_view_v2()
    # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/4；本视图中静态 disabled。
    # unilab:node_uuid=0fb93378-d283-553f-ba59-2be08fce61d2 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='feedlift_unload_cycle',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='4f6753b67557cc01c9619e683c57a9b98f2a7011da9cb7f47d11cc15956eb4ee',
    )
    # [ACTION feedlift.unload_bury] 来源 feedlift_unload_cycle@body/5；原节点 {"action":"feedlift.unload_bury","mode":"RUN","op":"call"}
    # unilab:node_uuid=e61014ec-baa6-5817-9c9d-6a1209452619 disabled=true
    projected_action_0007 = feedlift.unload_bury()
    # [ACTION feedlift.unload_ready] 来源 feedlift_unload_cycle@body/6；原节点 {"action":"feedlift.unload_ready","mode":"RUN","op":"call"}
    # unilab:node_uuid=7ffc0329-f635-53db-a730-5d1ac28f4522 disabled=true
    projected_action_0008 = feedlift.unload_ready()
    # [ACTION feedlift.probe_stack] 来源 feedlift_unload_cycle@body/7；原节点 {"action":"feedlift.probe_stack","args":{"magazine":{"lit":"waste"},"reconcile":{"lit":true}},"assign":{"var":"p0"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=195268eb-f574-54c4-b986-c002184e5337 disabled=true
    projected_action_0009 = feedlift.probe_stack(
        magazine='waste',
    )
    # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/8；本视图中静态 disabled。
    # unilab:node_uuid=963eb1e2-8667-58d5-9454-069ecda50e1a disabled=true
    projected_control_0010 = material.review_control_node_v1(
        operation_name='feedlift_unload_cycle',
        node_path='body/8',
        control_kind='comment',
        expected_sha256='05014a4407e0e05ef15644da15deb4c94400e723939d966709938d930c42971d',
    )
    # [SUBWORKFLOW robot_suction_put] 来源 feedlift_unload_cycle@body/9；原节点 {"inputs":{"station_id":{"lit":"waste"}},"op":"run_script","outputs":{},"script":"robot_suction_put"}
    # unilab:node_uuid=78c32aa0-12d5-575c-91f6-358b4714483f
    nested_operation_0011 = robot_suction_put_operation_view_v2()
    # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/10；本视图中静态 disabled。
    # unilab:node_uuid=4d404527-d129-54be-b49b-5e97f4515ada disabled=true
    projected_control_0012 = material.review_control_node_v1(
        operation_name='feedlift_unload_cycle',
        node_path='body/10',
        control_kind='comment',
        expected_sha256='28585da5e43853ab9476c0bd446fd2ecbade36e8104be8e0877145fa08f0d31a',
    )
    # [ACTION feedlift.unload_bury] 来源 feedlift_unload_cycle@body/11；原节点 {"action":"feedlift.unload_bury","mode":"RUN","op":"call"}
    # unilab:node_uuid=ee1f5f51-0938-549c-b4d6-0b7e56dddea8 disabled=true
    projected_action_0013 = feedlift.unload_bury()
