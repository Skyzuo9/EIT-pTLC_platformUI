from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


material: MaterialProxy = device('material')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='809b71ce-1bb2-5234-bc08-f92f2b0d5ee7',
    displayname='刮板工位放收集器-退出 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_scrape_holder_put_exit_operation_view_v2() -> None:
    # [OPERATION robot_scrape_holder_put_exit] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=f92be7f9-b58b-50cd-bda0-2fa925e4c63f disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_scrape_holder_put_exit',
        inputs_json='{"station_id":"default"}',
        expected_sha256='2a4a1d70a5fcd4c9425ee3a8ec4c385309041f165061a947a2e836d3f70c0c86',
    )
    # [CONTROL if] 来源 robot_scrape_holder_put_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.put-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P68"},"pos_tol_m...
    # unilab:node_uuid=236f3df0-d5f6-530c-9842-2cc08ad07df1
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_scrape_holder_put_exit@body/0；本视图中静态 disabled。
        # unilab:node_uuid=97109c19-9218-5e98-aa21-3f5f17f188a1 disabled=true
        projected_control_0002 = material.review_control_node_v1(
            operation_name='robot_scrape_holder_put_exit',
            node_path='body/0',
            control_kind='if',
            expected_sha256='34b9488360a3c2764ff71cc03d5c63982e06cf6c556f3dbe90d7b748760b1d48',
        )
        # unilab:node_uuid=2dbb78bf-3f6d-5127-8be9-efc7a78df052
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_put_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P68"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=12aed682-8491-5c96-b1b5-b3811bc23e62 disabled=true
            projected_action_0003 = robot.require_anchor(
                point_id='P68',
            )
            # [VERIFY comment] 只读来源校验 robot_scrape_holder_put_exit@body/0/then/1；本视图中静态 disabled。
            # unilab:node_uuid=1bd5392e-5e2d-594e-ae47-bb2c3b9fb2d8 disabled=true
            projected_control_0004 = material.review_control_node_v1(
                operation_name='robot_scrape_holder_put_exit',
                node_path='body/0/then/1',
                control_kind='comment',
                expected_sha256='37d8dce2c25cab12a35df6c1a205d43efe467c8a44f2613c653a3155667fa6c0',
            )
            # [ACTION robot.tool_action] 来源 robot_scrape_holder_put_exit@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ee88e6fa-1430-5270-8c89-07f44d26e7a9 disabled=true
            projected_action_0005 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=969398bf-06ca-544a-9cad-68a2574df6bb disabled=true
            projected_action_0006 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_exit@body/0/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P67"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e3c9cc77-9ca7-55d4-a3c9-57db6e34d37a disabled=true
            projected_action_0007 = robot.move_to_point(
                point_id_or_robot_name='P67',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_exit@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4ee47487-125a-5931-bc7f-7d16a0cd156e disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_put_exit@body/0/then/6；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=eeb0eb76-536b-5dbb-ad4e-bc0e179e3b4e disabled=true
            projected_action_0009 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=701dae5c-53fd-5c82-8051-352f2ccfcaa5
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_scrape_holder_put_exit@body/0/else/0；本视图中静态 disabled。
            # unilab:node_uuid=ae4e690f-2a98-594e-93c6-25e10489ee94 disabled=true
            projected_control_0010 = material.review_control_node_v1(
                operation_name='robot_scrape_holder_put_exit',
                node_path='body/0/else/0',
                control_kind='raise',
                expected_sha256='fea1843dd5dad78a2ed780489140855b9748bf64c63d146c4f1ef673ba8c7fef',
            )
