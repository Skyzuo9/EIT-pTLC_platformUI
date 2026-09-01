from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_rail import PLCRail
from eit_ptlc.unilab_domain.devices.robot import RobotProxy
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)


material: MaterialProxy = device('material')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='12d9222f-6ded-506c-b2c6-fb541b30edb7',
    displayname='收集工位放收集器-进入 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_collect_holder_put_enter_operation_view_v2() -> None:
    # [OPERATION robot_collect_holder_put_enter] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=406ce04a-efce-5311-9523-7c5c70ab43dc disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_collect_holder_put_enter',
        inputs_json='{"station_id":"default"}',
        expected_sha256='c90a860f8198c90185271d7b526e37efa48ea38594444c4353667aaa45c83093',
    )
    # [VERIFY comment] 只读来源校验 robot_collect_holder_put_enter@body/0；本视图中静态 disabled。
    # unilab:node_uuid=8b1ee376-dea1-5030-9dc7-aad94d485f35 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_collect_holder_put_enter',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
    )
    # [ACTION robot.home_ensure] 来源 robot_collect_holder_put_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=15a48396-7d52-5612-b4b0-953afbb9e668 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_collect_holder_put_enter@body/2；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=e8d54632-080b-5ef3-9d79-0e73e8e7d9f6
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_collect_holder_put_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.put-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_to...
    # unilab:node_uuid=d56bb239-61a0-52a5-8a0c-8a4f8d1f2ccc
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_collect_holder_put_enter@body/3；本视图中静态 disabled。
        # unilab:node_uuid=c41030e3-044a-50fb-a95e-3d23848c4e9b disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_collect_holder_put_enter',
            node_path='body/3',
            control_kind='if',
            expected_sha256='4d81054bb36570a2980ffe064460c520586ffd4c3e190a63646325a011a0ee8d',
        )
        # unilab:node_uuid=908e0b49-483a-5c55-b911-e6fa4f40db0e
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collect_holder_put_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cb21442e-aa08-58a6-89fb-de226773d65d disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_collect_holder_put_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=abb68001-abea-5d69-b8fc-9340be265491 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_enter@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e156df8b-f0ce-5e59-9d2a-00182e19f675 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P70',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-put.far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0780f3d2-396e-5995-80a8-346c29e102f4 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='collect-holder-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_enter@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0a2dfc47-07c5-5d8d-8fcd-54befc37b864 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='collect-holder-put.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P73"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9e6243c6-623f-5f93-8a8c-19d18f61ec6d disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='P73',
            )
            # [ACTION robot.require_anchor] 来源 robot_collect_holder_put_enter@body/3/then/6；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P73"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e22ad995-87d5-5211-a526-20110afb5c24 disabled=true
            projected_action_0012 = robot.require_anchor(
                point_id='P73',
            )
        # unilab:node_uuid=ed0e0e81-9cfb-5180-b233-f5bb80205be7
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_collect_holder_put_enter@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=35d1c219-a34f-5cdf-be7a-6a14a52d9820 disabled=true
            projected_control_0013 = material.review_control_node_v1(
                operation_name='robot_collect_holder_put_enter',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='28f4b762a315a533e9e04aced9d44189e64a426dcf5129981795664622a4a3ee',
            )
