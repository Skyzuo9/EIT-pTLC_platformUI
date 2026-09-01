from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


material: MaterialProxy = device('material')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='3f36876d-9736-56ce-b353-a8132a85e774',
    displayname='收集工位取收集器-退出 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_collect_holder_pick_exit_operation_view_v2() -> None:
    # [OPERATION robot_collect_holder_pick_exit] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=1abb6b39-1c6f-54b2-a7fd-d5a0c58f94dd disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_collect_holder_pick_exit',
        inputs_json='{"station_id":"default"}',
        expected_sha256='204d15fcbd306cb2a54a7844db256ff2c32f5f4fc9ccbaa47dda621018d68248',
    )
    # [CONTROL if] 来源 robot_collect_holder_pick_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.pick-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P74"},"pos_t...
    # unilab:node_uuid=e4a1eb8b-2a4d-545a-94c7-448f710544d3
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_collect_holder_pick_exit@body/0；本视图中静态 disabled。
        # unilab:node_uuid=5b718eaa-bb61-58cc-a7e3-410e44b4f86e disabled=true
        projected_control_0002 = material.review_control_node_v1(
            operation_name='robot_collect_holder_pick_exit',
            node_path='body/0',
            control_kind='if',
            expected_sha256='9dd19a9682f6bba7bd2e92567e4bb0d4189fe1cd4152a88dbe99e68aa46578a8',
        )
        # unilab:node_uuid=f58eb265-85fd-5b71-9c92-aae95854e2e7
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collect_holder_pick_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P74"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6b3ec7cc-5d1f-5a44-8142-ab861a4dd511 disabled=true
            projected_action_0003 = robot.require_anchor(
                point_id='P74',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_exit@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d35e0b1d-5ec4-59ee-80a7-a778ab020c04 disabled=true
            projected_action_0004 = robot.move_to_point(
                point_id_or_robot_name='collect-holder-pick.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_exit@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0bf14433-614c-532a-bd22-cf4c4a6d2060 disabled=true
            projected_action_0005 = robot.move_to_point(
                point_id_or_robot_name='collect-holder-pick.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f25ea099-20f6-5e3d-90e5-9467b9657c1e disabled=true
            projected_action_0006 = robot.move_to_point(
                point_id_or_robot_name='P70',
            )
            # [ACTION robot.require_anchor] 来源 robot_collect_holder_pick_exit@body/0/then/4；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P70"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=987589d6-a1dc-5a9d-83bc-55e68663c7b4 disabled=true
            projected_action_0007 = robot.require_anchor(
                point_id='P70',
            )
        # unilab:node_uuid=268164b8-5428-5a36-b5df-8f68edf4291f
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_collect_holder_pick_exit@body/0/else/0；本视图中静态 disabled。
            # unilab:node_uuid=84914a1c-29c6-5052-834b-01c166267907 disabled=true
            projected_control_0008 = material.review_control_node_v1(
                operation_name='robot_collect_holder_pick_exit',
                node_path='body/0/else/0',
                control_kind='raise',
                expected_sha256='b11f10a0feb8744b7c58d4e70abd796e993e4ac814885c2570751251942e60cf',
            )
