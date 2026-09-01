from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


material: MaterialProxy = device('material')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='09e71180-50d6-5b19-a078-201a22494107',
    displayname='升降仓吸板-退出 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_feed_lift_pick_exit_operation_view_v2() -> None:
    # [OPERATION robot_feed_lift_pick_exit] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=a0c764ee-3ff4-5415-b7e9-3d1bab3f245a disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_feed_lift_pick_exit',
        inputs_json='{"station_id":"default"}',
        expected_sha256='1fdb4b2357608b9de78fb7e12d91da9725a5b94b300a69194503ec0537c03dad',
    )
    # [CONTROL if] 来源 robot_feed_lift_pick_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"feed-lift.pick-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P21"},"pos_tol_mm":{"l...
    # unilab:node_uuid=96541cb5-3010-5b71-ad42-6f439bf1d958
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_feed_lift_pick_exit@body/0；本视图中静态 disabled。
        # unilab:node_uuid=1ef327d4-a7b1-5269-96c9-f02fa06094d7 disabled=true
        projected_control_0002 = material.review_control_node_v1(
            operation_name='robot_feed_lift_pick_exit',
            node_path='body/0',
            control_kind='if',
            expected_sha256='db88caeaaa60c637a17315b7794e00579e62623b9714659fdab07ccfe9c041df',
        )
        # unilab:node_uuid=1de851dd-c67c-54cc-81b1-21acfb50be28
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_feed_lift_pick_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P21"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e0c10369-a880-5e2b-88f9-f4d86366b1f2 disabled=true
            projected_action_0003 = robot.require_anchor(
                point_id='P21',
            )
            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_exit@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"feed-lift.approach_near"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9b6e48ba-f8a4-533c-b0c5-7995a672ab4e disabled=true
            projected_action_0004 = robot.move_to_point(
                point_id_or_robot_name='feed-lift.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_exit@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"feed-lift.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cbd390b2-ddc8-59e3-bbf1-188d65a85460 disabled=true
            projected_action_0005 = robot.move_to_point(
                point_id_or_robot_name='feed-lift.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=efbcfb86-b5b6-5f8a-8ad8-2a3b32cc1b38 disabled=true
            projected_action_0006 = robot.move_to_point(
                point_id_or_robot_name='P5',
            )
            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_exit@body/0/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fa0b1a4d-1a20-5eb4-bd7a-96ed3be0f4a6 disabled=true
            projected_action_0007 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_feed_lift_pick_exit@body/0/then/5；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e1a8505a-b476-55ee-b9c7-4bd25a4f46dc disabled=true
            projected_action_0008 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=33dca665-958b-5c37-b084-8a4425b0de53
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_feed_lift_pick_exit@body/0/else/0；本视图中静态 disabled。
            # unilab:node_uuid=1129434f-72c6-50a1-9f1c-61c4f670ee60 disabled=true
            projected_control_0009 = material.review_control_node_v1(
                operation_name='robot_feed_lift_pick_exit',
                node_path='body/0/else/0',
                control_kind='raise',
                expected_sha256='4e5326ad80db078e1931ffa127f63062555f96bc6acbf42e96dd6236ec512b55',
            )
