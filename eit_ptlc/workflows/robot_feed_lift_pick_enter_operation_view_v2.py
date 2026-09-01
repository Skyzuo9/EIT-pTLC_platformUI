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
    workflow_uuid='76bc5915-8119-5e91-a812-28a37fee383b',
    displayname='升降仓吸板-进入 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_feed_lift_pick_enter_operation_view_v2() -> None:
    # [OPERATION robot_feed_lift_pick_enter] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=fe9fb7bc-8dd5-5b14-9671-01e9f3c39898 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_feed_lift_pick_enter',
        inputs_json='{"station_id":"default"}',
        expected_sha256='e4af37bf878180221722891c4bb4bd65a62eeec8b525a54635cdc3d322e7f0b6',
    )
    # [VERIFY comment] 只读来源校验 robot_feed_lift_pick_enter@body/0；本视图中静态 disabled。
    # unilab:node_uuid=f3ef42b9-7d1b-5012-a41b-04a3030dec74 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_feed_lift_pick_enter',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
    )
    # [ACTION robot.home_ensure] 来源 robot_feed_lift_pick_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=33204e4d-933d-550a-8fcc-5f461110ad8d disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_feed_lift_pick_enter@body/2；原节点 {"inputs":{"needed":{"lit":1}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=bf53bb0a-379a-5c63-a43c-30272a5b270a
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_feed_lift_pick_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"feed-lift.pick-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"...
    # unilab:node_uuid=da3ea6bd-c547-5171-96a0-b68c67fcea83
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_feed_lift_pick_enter@body/3；本视图中静态 disabled。
        # unilab:node_uuid=f052cf35-abff-5d3f-8269-7440f9c3c82b disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_feed_lift_pick_enter',
            node_path='body/3',
            control_kind='if',
            expected_sha256='77ad9ea57ed5342e2d1bd8ae425ff877f6bb6f2c0e506d10d79a3c3f50c7f147',
        )
        # unilab:node_uuid=b84dabfb-4744-5750-8bd7-a4d90dfb7fe6
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_feed_lift_pick_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2f6ec577-e452-557c-b077-6f0866a336b7 disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_feed_lift_pick_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ef474072-ec4d-5955-befc-9b33e40dce81 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=1,
            )
            # [ACTION robot.tool_action] 来源 robot_feed_lift_pick_enter@body/3/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=96b0f74c-a84e-5724-a132-81be89fe7774 disabled=true
            projected_action_0008 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0852f394-5a48-5760-ae75-2f1c4ffc2511 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='P5',
            )
            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_enter@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"feed-lift.approach_far"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=638b673d-f7a7-556c-8ed5-0bb951c331b6 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='feed-lift.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"feed-lift.approach_near"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=337c2f5c-1262-54c7-89c6-dc304d3a3149 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='feed-lift.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_enter@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P21"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d0705c02-cd56-52b5-95a3-0f47a2f8f7d3 disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='P21',
            )
            # [ACTION robot.tool_action] 来源 robot_feed_lift_pick_enter@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4d6acb86-5c3c-561e-8076-c55403182c10 disabled=true
            projected_action_0013 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.require_anchor] 来源 robot_feed_lift_pick_enter@body/3/then/8；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P21"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5273599b-1d77-58ac-8a09-ae695e6e8b9d disabled=true
            projected_action_0014 = robot.require_anchor(
                point_id='P21',
            )
        # unilab:node_uuid=d9f1189d-e8d6-5d27-8f16-86c4714e7321
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_feed_lift_pick_enter@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=806930db-95c6-5e90-9289-e405adf85015 disabled=true
            projected_control_0015 = material.review_control_node_v1(
                operation_name='robot_feed_lift_pick_enter',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='0f36308f82ec64e6c236c7b3baf64c97a839955661e14b38ef39106d62bfa5f6',
            )
