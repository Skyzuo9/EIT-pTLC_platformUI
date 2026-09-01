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
    workflow_uuid='746ea352-5f48-517d-aa83-d4e3e60dd80d',
    displayname='刮板工位取收集器-进入 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_scrape_holder_pick_enter_operation_view_v2() -> None:
    # [OPERATION robot_scrape_holder_pick_enter] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=f0053e03-5cfe-52b6-a891-038308d62f55 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_scrape_holder_pick_enter',
        inputs_json='{"station_id":"default"}',
        expected_sha256='fd713bbf2288cfc67eb5f353da958f763b3897a082c41648acd08bfb57cd42e1',
    )
    # [VERIFY comment] 只读来源校验 robot_scrape_holder_pick_enter@body/0；本视图中静态 disabled。
    # unilab:node_uuid=87319d90-d3f4-5c6c-9585-5ca2490e956f disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_scrape_holder_pick_enter',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
    )
    # [ACTION robot.home_ensure] 来源 robot_scrape_holder_pick_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=f741200f-82d9-506c-8f1f-278176af2bc0 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_scrape_holder_pick_enter@body/2；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=02181b55-081b-5851-b2aa-1416fc677df1
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_scrape_holder_pick_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.pick-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_to...
    # unilab:node_uuid=cccd3d49-f198-584f-9654-c84b88d72565
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_scrape_holder_pick_enter@body/3；本视图中静态 disabled。
        # unilab:node_uuid=c42a39f7-4abe-592a-92f8-0f383801f5cb disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_scrape_holder_pick_enter',
            node_path='body/3',
            control_kind='if',
            expected_sha256='54bddca290173db9b7a87509722da4384ba9ae57b88faef9c3a9d2395e972fc5',
        )
        # unilab:node_uuid=f1100612-273b-54db-91fe-1d482590c27b
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_pick_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e675e709-1f9c-5f69-bdda-5b789f5249e4 disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_scrape_holder_pick_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fe01e5f5-b29a-5d10-814a-48b82330c14a disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_enter@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P67"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=26745ef9-b35f-517e-8c49-9d73c11f26b3 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P67',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=97bb5767-e648-5c91-9c8c-7a20a565b9fa disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-pick.far',
            )
            # [ACTION robot.tool_action] 来源 robot_scrape_holder_pick_enter@body/3/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1b311306-5fc3-52f5-a6f2-3e63090e2248 disabled=true
            projected_action_0010 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cf4b93b6-267e-5854-aeec-93cba54e5b23 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-pick.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_enter@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P77"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e78ea896-feb6-5ec5-bfc5-4a97f4d8cdc9 disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='P77',
            )
            # [ACTION robot.tool_action] 来源 robot_scrape_holder_pick_enter@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2ce4af6b-6bef-5ce6-93e9-a71869dd052b disabled=true
            projected_action_0013 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_pick_enter@body/3/then/8；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P77"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=75ecb808-ec62-511d-aaa5-e29b47b1a6dd disabled=true
            projected_action_0014 = robot.require_anchor(
                point_id='P77',
            )
        # unilab:node_uuid=9ed04f66-4eaf-54a5-bb44-16bfcb783236
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_scrape_holder_pick_enter@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=2d560efe-9b9d-5298-a281-76203ddcd67a disabled=true
            projected_control_0015 = material.review_control_node_v1(
                operation_name='robot_scrape_holder_pick_enter',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='10a3942e9af994de26601221bf44e912fde18a6269074a37f4f55e7a96e1a1aa',
            )
