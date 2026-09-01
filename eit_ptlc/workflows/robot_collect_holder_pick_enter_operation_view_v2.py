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
    workflow_uuid='6837a7a6-e875-5c1d-ab9e-1f3a5e2f6e1d',
    displayname='收集工位取收集器-进入 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_collect_holder_pick_enter_operation_view_v2() -> None:
    # [OPERATION robot_collect_holder_pick_enter] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=0eefa792-342c-5df8-addc-2b20bfa4daea disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_collect_holder_pick_enter',
        inputs_json='{"station_id":"default"}',
        expected_sha256='3e59e5c0840dc774da5597229ba8e166c3600f44b61ba532bba4508d2307ff40',
    )
    # [VERIFY comment] 只读来源校验 robot_collect_holder_pick_enter@body/0；本视图中静态 disabled。
    # unilab:node_uuid=459eb9f7-ff48-579a-a3d0-942df1c94756 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_collect_holder_pick_enter',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
    )
    # [ACTION robot.home_ensure] 来源 robot_collect_holder_pick_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=69d58632-616d-50c0-8436-804a723a84e2 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_collect_holder_pick_enter@body/2；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=08c090c9-f420-5123-9c4b-563a6ee18eae
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_collect_holder_pick_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.pick-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_...
    # unilab:node_uuid=a85c24da-ee7d-5ed4-87e5-460acd7de1d5
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_collect_holder_pick_enter@body/3；本视图中静态 disabled。
        # unilab:node_uuid=d94fcabd-3498-518e-8274-640f3c53f196 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_collect_holder_pick_enter',
            node_path='body/3',
            control_kind='if',
            expected_sha256='684bbc4080ef6888fa0e463f987da6edd06ee78b60f94938e062f931d40b25db',
        )
        # unilab:node_uuid=335a7d4e-3362-5a12-85df-bcf1afe2c23b
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collect_holder_pick_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=11ed2774-803b-540d-ad8c-224c26821e3a disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_collect_holder_pick_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ad550d1b-39d7-5cfd-b4bf-52fd510a13a1 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_enter@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cfb02eb4-e3b5-5c0e-829d-9b0917f133a6 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P70',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-pick.far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=371b2e07-ac98-5a1b-8ac6-59898ae7af76 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='collect-holder-pick.far',
            )
            # [ACTION robot.tool_action] 来源 robot_collect_holder_pick_enter@body/3/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6eb17ac2-88f7-5870-9aef-597d9d906753 disabled=true
            projected_action_0010 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bf89188a-d141-55ab-a54e-0c5e7e590c86 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='collect-holder-pick.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_enter@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P74"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5d931534-a274-5fde-bbe5-d448c3b15b16 disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='P74',
            )
            # [ACTION robot.tool_action] 来源 robot_collect_holder_pick_enter@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3b233c7e-120a-53a5-8726-de88f025d5b6 disabled=true
            projected_action_0013 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.require_anchor] 来源 robot_collect_holder_pick_enter@body/3/then/8；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P74"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=729beda3-ba22-578e-82d6-36739dfcfa86 disabled=true
            projected_action_0014 = robot.require_anchor(
                point_id='P74',
            )
        # unilab:node_uuid=a784e92b-c250-573b-8056-bdbc3ee5638b
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_collect_holder_pick_enter@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=c9c30c2e-a9f8-5eae-bb30-88fda61780cd disabled=true
            projected_control_0015 = material.review_control_node_v1(
                operation_name='robot_collect_holder_pick_enter',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='8971f910dc9f0dda4a813c1065a771ce86e4f84133b15a4a61ccf4bbb19b64c9',
            )
