from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


material: MaterialProxy = device('material')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='c3dc80bb-f155-5ac7-aa00-8d577bc686a3',
    displayname='收集工位放收集器-退出 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_collect_holder_put_exit_operation_view_v2() -> None:
    # [OPERATION robot_collect_holder_put_exit] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=e9eab36d-a81c-546e-9c99-60d73b75c8fe disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_collect_holder_put_exit',
        inputs_json='{"station_id":"default"}',
        expected_sha256='39b195aab7d3eba3612f9f47619cc1d63b4539b1dc4ea1144fff4b495a8c4c73',
    )
    # [CONTROL if] 来源 robot_collect_holder_put_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.put-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P73"},"pos_tol...
    # unilab:node_uuid=08e7b640-207b-548a-aa9b-a82ca57d7174
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_collect_holder_put_exit@body/0；本视图中静态 disabled。
        # unilab:node_uuid=47e2d166-3526-5d5e-8423-84cd9b791b74 disabled=true
        projected_control_0002 = material.review_control_node_v1(
            operation_name='robot_collect_holder_put_exit',
            node_path='body/0',
            control_kind='if',
            expected_sha256='a3aa46084d0ea108b59e38c5ce3c41e308a6fc9c20c808ffa6c9ae9b2dbae8fe',
        )
        # unilab:node_uuid=1ee47049-d9b1-561f-ac92-aa00d8e8c788
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collect_holder_put_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P73"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=68aa7f59-b0ad-5572-8189-a27789a6c1b2 disabled=true
            projected_action_0003 = robot.require_anchor(
                point_id='P73',
            )
            # [ACTION robot.tool_action] 来源 robot_collect_holder_put_exit@body/0/then/1；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=701c3ae6-3aa3-53df-807e-811d5552e181 disabled=true
            projected_action_0004 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_exit@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=76091ee4-8ee3-5e27-a880-dd4b3f979189 disabled=true
            projected_action_0005 = robot.move_to_point(
                point_id_or_robot_name='collect-holder-put.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9422cbcb-5c61-5471-8146-038de4ba33e3 disabled=true
            projected_action_0006 = robot.move_to_point(
                point_id_or_robot_name='collect-holder-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_exit@body/0/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=09afa1fd-42b4-5147-a543-13b09cad6079 disabled=true
            projected_action_0007 = robot.move_to_point(
                point_id_or_robot_name='P70',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_exit@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1d31829a-920d-540c-b047-1076be9e3d4e disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_collect_holder_put_exit@body/0/then/6；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=61b6e7b5-8911-5128-9073-dbd646b45cb3 disabled=true
            projected_action_0009 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=d60cec41-f957-5019-bcf3-ab530bf92e27
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_collect_holder_put_exit@body/0/else/0；本视图中静态 disabled。
            # unilab:node_uuid=5269f0fa-9992-5a45-8cf4-37948f9898a4 disabled=true
            projected_control_0010 = material.review_control_node_v1(
                operation_name='robot_collect_holder_put_exit',
                node_path='body/0/else/0',
                control_kind='raise',
                expected_sha256='697f5435718fb591b5ef7749d1aa903038695d353ee9c2ad32b48a7adc755b13',
            )
