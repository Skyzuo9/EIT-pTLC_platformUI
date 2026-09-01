from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


material: MaterialProxy = device('material')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='051f2e16-c35d-5319-becf-103080179d3d',
    displayname='刮板工位取收集器-退出 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_scrape_holder_pick_exit_operation_view_v2() -> None:
    # [OPERATION robot_scrape_holder_pick_exit] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=37cffcc7-5a92-59ec-8774-b7868cb9917a disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_scrape_holder_pick_exit',
        inputs_json='{"station_id":"default"}',
        expected_sha256='121d0945ee2423235d942ebc02a9d2da7ca59e77a5bbeb7b7644aee01a75bdff',
    )
    # [CONTROL if] 来源 robot_scrape_holder_pick_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.pick-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P77"},"pos_tol...
    # unilab:node_uuid=1d000370-b55e-53bb-9f8e-9fc42052eb73
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_scrape_holder_pick_exit@body/0；本视图中静态 disabled。
        # unilab:node_uuid=b7d6bf5a-9d7c-59e6-bbcc-f23afdce1d91 disabled=true
        projected_control_0002 = material.review_control_node_v1(
            operation_name='robot_scrape_holder_pick_exit',
            node_path='body/0',
            control_kind='if',
            expected_sha256='4cdf772c3843f2bb01be941535f7816b0d728dadf8c2e8216ad1bbbfb8e09b91',
        )
        # unilab:node_uuid=f90b7262-2dec-5a0f-93e1-483e089d5300
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_pick_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P77"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d7e5e878-e8ef-5564-8a03-6dbc09284fa1 disabled=true
            projected_action_0003 = robot.require_anchor(
                point_id='P77',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.retreat-0"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5c892e03-db6d-532c-a66a-5d3892bd2d19 disabled=true
            projected_action_0004 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-pick.retreat-0',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.retreat-1"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1dc54a64-8c9b-58b9-8f52-fd02df93fb23 disabled=true
            projected_action_0005 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-pick.retreat-1',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.retreat-2"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9ac5c3ea-1436-5967-a09f-ae3437ab02c2 disabled=true
            projected_action_0006 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-pick.retreat-2',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=23be810c-7e4d-5aa2-a81f-3e67fc13ee69 disabled=true
            projected_action_0007 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-pick.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P67"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0ef01367-3c06-5caf-8dc4-cbdac111c4a5 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P67',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=aa4f745b-7e82-5f35-94e3-71989257c6db disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_pick_exit@body/0/then/7；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f6f358b4-8cd7-5907-be6f-dc5a170b93dc disabled=true
            projected_action_0010 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=53f78582-ad57-5ed6-b834-44e0cf21e2c7
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_scrape_holder_pick_exit@body/0/else/0；本视图中静态 disabled。
            # unilab:node_uuid=c49e1ad9-ecb3-5f9b-842a-c8da0a4395f9 disabled=true
            projected_control_0011 = material.review_control_node_v1(
                operation_name='robot_scrape_holder_pick_exit',
                node_path='body/0/else/0',
                control_kind='raise',
                expected_sha256='8ad827fbe1c421b806be759c6159b104d8809f2fd925bf203dab094a6a6aae90',
            )
