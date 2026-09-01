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
    workflow_uuid='6959fb23-7632-53f1-928c-c8a81382eb10',
    displayname='台面取板 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_suction_pick_operation_view_v2() -> None:
    # [OPERATION robot_suction_pick] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=96675771-20eb-5c6b-beb6-3b2febec3057 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_suction_pick',
        inputs_json='{"station_id":"spotting"}',
        expected_sha256='b66aa5aee033a7f2c307f6502a217763e34ab015401c1d1104839f0737b6b4ba',
    )
    # [VERIFY comment] 只读来源校验 robot_suction_pick@body/0；本视图中静态 disabled。
    # unilab:node_uuid=98717d83-7c8a-5a62-b4c3-3ab36a3dddda disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_suction_pick',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
    )
    # [ACTION robot.home_ensure] 来源 robot_suction_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=77457f3f-27ac-57e7-b9cf-1d192cdaef14 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_suction_pick@body/2；原节点 {"inputs":{"needed":{"lit":1}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=b08c1ce3-7da5-5816-a370-a52ee2bbb790
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_suction_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"spotting"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"...
    # unilab:node_uuid=7c607c3b-0718-527c-9eec-6b551555a424
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_suction_pick@body/3；本视图中静态 disabled。
        # unilab:node_uuid=7c874f8f-8066-5097-b439-5eca6c3a3a6d disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_suction_pick',
            node_path='body/3',
            control_kind='if',
            expected_sha256='7cf59bced5f5b2dcd49557f999dbd90eb52637f34cb412ab2176135f0e83d084',
        )
        # unilab:node_uuid=2ce6fde4-0c4f-52fe-adac-bacf441c74a9
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e09e14c7-9f69-58bd-9015-2610574243be disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_suction_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0ba6bf09-5beb-5978-892d-a12b363a3907 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=1,
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3974aa74-6561-51f1-b924-77ad228eb0da disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P4',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5e72428f-d47a-58b9-a329-bebf7866b51b disabled=true
            projected_action_0009 = robot.tool_action(
                action='rotary-up',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dab2b1e1-ae45-5df9-91b1-ca393412ea59 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='spotting.pick.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c85c1110-ff4b-509d-ac9a-920497f0bd1a disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='spotting.pick.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P19"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1d06c120-40b3-54bf-87b8-5ee6f7d3a6df disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='P19',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b2cc6433-04eb-53cb-ad53-f595c07e552d disabled=true
            projected_action_0013 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c8b53aad-b10f-5693-a452-cc273144e40b disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='spotting.pick.retreat_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3f937422-3f78-5f93-9ec1-fb1401e1c351 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='spotting.pick.retreat_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=036305f0-4309-5960-8e0b-a86f1af8767c disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='P4',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3dc4d5ab-2702-50f4-8925-2ec6578c2ecb disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/then/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c37e12e5-9682-5cbe-b1d0-180725a004d9 disabled=true
            projected_action_0018 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=c653f67f-a117-5839-986e-c9bb97602e20
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c461c722-d6d0-5f23-a8a8-2042fbd92ec9 disabled=true
            projected_action_0019 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_suction_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=af81d7a9-d62f-5efd-801c-1bf6d1065c88 disabled=true
            projected_action_0020 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d3e72b5e-3931-5787-9603-f5a0cd23069e disabled=true
            projected_action_0021 = robot.move_to_point(
                point_id_or_robot_name='P63',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=57837e7f-87b6-54b7-a2b9-e242693a1d74 disabled=true
            projected_action_0022 = robot.tool_action(
                action='rotary-up',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4104ff12-b6a6-5e03-aa54-49d74db88280 disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='scrape.plate-pick.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=73821360-a122-5a4d-8355-f34829a4bfe0 disabled=true
            projected_action_0024 = robot.move_to_point(
                point_id_or_robot_name='scrape.plate-pick.approach_near',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_pick@body/3/elifs/0/body/6；本视图中静态 disabled。
            # unilab:node_uuid=e4271380-f24b-563a-b38c-8f706527bbf5 disabled=true
            projected_control_0025 = material.review_control_node_v1(
                operation_name='robot_suction_pick',
                node_path='body/3/elifs/0/body/6',
                control_kind='comment',
                expected_sha256='ce61ff1eddd64c4a26507b7df53f7a45d978ed30161b8ea6895afc3afcafc7bc',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P65"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1d3f3756-eec2-5b7e-a537-a6107db07f96 disabled=true
            projected_action_0026 = robot.move_to_point(
                point_id_or_robot_name='P65',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bb599079-662b-57f9-8129-12929007baa6 disabled=true
            projected_action_0027 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a6397b6c-f45b-577f-80f7-75e21edd6e75 disabled=true
            projected_action_0028 = robot.move_to_point(
                point_id_or_robot_name='scrape.plate-pick.retreat_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=29086151-2e7c-5d89-90bc-e3167a14d09f disabled=true
            projected_action_0029 = robot.move_to_point(
                point_id_or_robot_name='scrape.plate-pick.retreat_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9245086e-72d4-5e62-91dc-70d38e980677 disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='P63',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_pick@body/3/elifs/0/body/12；本视图中静态 disabled。
            # unilab:node_uuid=cc4ec693-d66f-5a34-bb35-e80cf503f20f disabled=true
            projected_control_0031 = material.review_control_node_v1(
                operation_name='robot_suction_pick',
                node_path='body/3/elifs/0/body/12',
                control_kind='comment',
                expected_sha256='0c6391714e618a81ff71411339cb422212bba6d05a807e18d569fcabaea39c2f',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0c9fbb90-07d6-5c10-8661-c24be418d7dc disabled=true
            projected_action_0032 = robot.tool_action(
                action='rotary-up',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7d82a54f-1581-517e-b6bd-f27d1b942a70 disabled=true
            projected_action_0033 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/elifs/0/body/15；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fea2ba8f-52b9-5fbf-bf13-f6ab325fa721 disabled=true
            projected_action_0034 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=cfc6753b-6f25-5c4a-8c3d-e06e812461d0
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_suction_pick@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=972da90a-4dc4-5ae1-9dc5-51b4f6b0731d disabled=true
            projected_control_0035 = material.review_control_node_v1(
                operation_name='robot_suction_pick',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='7324ece78b8e478b8be13e31abd1d3bdbbc53d99d674cd9200fe986e9b80917f',
            )
