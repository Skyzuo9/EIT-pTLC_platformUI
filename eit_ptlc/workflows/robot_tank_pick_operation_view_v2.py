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
    workflow_uuid='6ec0021b-47ca-5c31-8496-dc0ac693c198',
    displayname='展缸取板 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_tank_pick_operation_view_v2() -> None:
    # [OPERATION robot_tank_pick] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=8ada98a4-8972-5a96-9cd0-92b7a640e5c3 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_tank_pick',
        inputs_json='{"tank_id":1}',
        expected_sha256='2e30cda0346da1ac36f580a9d8601c7c9ddda202c744a9b1690da243676f0635',
    )
    # [VERIFY comment] 只读来源校验 robot_tank_pick@body/0；本视图中静态 disabled。
    # unilab:node_uuid=adea04e5-23f6-506a-82c9-ce5bc6daaaaf disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_tank_pick',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
    )
    # [ACTION robot.home_ensure] 来源 robot_tank_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=497b4aa8-d7fa-5fba-9a31-dd0cbe5128de disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_tank_pick@body/2；原节点 {"inputs":{"needed":{"lit":1}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=b972ae0a-8c6c-5ee0-abe6-3daaaf648121
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_tank_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"tank_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode"...
    # unilab:node_uuid=c5a6d236-3be8-5c46-8e9d-d1c16d4ed54d
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_tank_pick@body/3；本视图中静态 disabled。
        # unilab:node_uuid=2ea2c910-c767-5725-8969-4fb88d79dc92 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_tank_pick',
            node_path='body/3',
            control_kind='if',
            expected_sha256='123c731101772197874bc2b6b927dfc9ebbf6a503055158d6fc26ec5b18a4692',
        )
        # unilab:node_uuid=27b2d1f1-5f94-5857-b1ba-7ecd3f9b96c3
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=69d4b386-5d81-5b79-a6d0-2a7343ea69a4 disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b78d66ab-daef-5b8c-a554-b8ae58d7337c disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b732cb43-e0d0-59b3-b4f4-8cb735352ed9 disabled=true
            projected_action_0008 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=753b8691-4c88-587e-b681-ae9b1848bd16 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c27391c6-e8e9-55c0-a9ca-a92021c8eaf0 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1991a11a-7f87-5e79-9a54-869a4670ea92 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7eb7f1e1-c70f-5d45-bcee-96e1a6499850 disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5ff719dc-a938-59a8-bf07-c408729d725e disabled=true
            projected_action_0013 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=173b2af6-95ce-55f3-9f51-c2c525b60bba disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P11"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2941d991-e83e-5c9e-911c-75b8c28f52ed disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='P11',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/then/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=00f40923-568a-5842-bb41-c27711a06744 disabled=true
            projected_action_0016 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5c0cac90-320e-5da9-85c9-08a9b7dcdfe1 disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=faab824d-f344-5cc0-9b48-01040a627887 disabled=true
            projected_action_0018 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c37952eb-9161-579a-8790-5d3f6568f7f1 disabled=true
            projected_action_0019 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=443ba94f-b760-54ae-a606-6b2b70cf3bc8 disabled=true
            projected_action_0020 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bc5ad098-ac6c-5d5a-91ef-5185fc055ebb disabled=true
            projected_action_0021 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cdaa7dd3-b947-5492-8757-ea6ecbb4d7a8 disabled=true
            projected_action_0022 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fe98d3a6-15f5-5d66-9f0c-435bc2cb9ae2 disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/then/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c093f9d0-c50c-53af-b29c-2f1450c5fa5d disabled=true
            projected_action_0024 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=31de8938-c799-5908-844c-78c37b0282a8
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1842d689-cc9b-5831-9113-eb20a079379f disabled=true
            projected_action_0025 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=41cb76a9-844d-5b35-a4c0-c9774f84891d disabled=true
            projected_action_0026 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d899d36d-0610-501b-9b4a-73753f62a5bc disabled=true
            projected_action_0027 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c5227ee7-3c84-548a-aa44-d5e2d026af4b disabled=true
            projected_action_0028 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e77cce82-6bc9-5b02-987d-9f4d64ad7676 disabled=true
            projected_action_0029 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9019c4c8-688c-5e34-8f76-fc06917b7e69 disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=525e9707-597e-5205-94da-1906ae63b97d disabled=true
            projected_action_0031 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=43cfaafd-9be4-5e12-b912-1f03e2cc7257 disabled=true
            projected_action_0032 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bfffe135-7daa-5dc2-8d5d-44dcbd679780 disabled=true
            projected_action_0033 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P12"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9c0ced8e-a67c-5c91-a229-4d9edba5eb64 disabled=true
            projected_action_0034 = robot.move_to_point(
                point_id_or_robot_name='P12',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b0ebfc55-3723-5dbf-95f9-8606199605f3 disabled=true
            projected_action_0035 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bd01a3d1-e204-586b-b79c-9ea76509ba88 disabled=true
            projected_action_0036 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=46720a56-b678-544b-bcb1-32ca2c094305 disabled=true
            projected_action_0037 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a087b504-1880-54d6-9cff-8e8b9c853db8 disabled=true
            projected_action_0038 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e014ab95-e8e1-51c3-adff-8f8494b2057d disabled=true
            projected_action_0039 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=478630bf-ee14-5122-ae16-cd6c05fb2ab3 disabled=true
            projected_action_0040 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a5982472-a024-5497-a0fb-277fc929c730 disabled=true
            projected_action_0041 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=db9b2f08-7bd4-5ce4-9720-397b4e304507 disabled=true
            projected_action_0042 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/0/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c9649e6b-ad50-5ff5-95e4-009abb4328ae disabled=true
            projected_action_0043 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=ee6a9997-724b-5cf2-a0e8-040721440dbf
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b7c4c266-8dd9-5fcb-9f93-6620764bebcd disabled=true
            projected_action_0044 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6498570e-efb8-5c75-9959-b7db46feca9d disabled=true
            projected_action_0045 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=163e71a8-9d3c-55a6-8019-e6ab212798f3 disabled=true
            projected_action_0046 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8454bf82-6653-5147-8ca5-1324ebbe160d disabled=true
            projected_action_0047 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=056c8ffe-5879-53c6-bfe8-0713d15170c7 disabled=true
            projected_action_0048 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ec58c610-cbf6-54ae-92ee-28261d6b5847 disabled=true
            projected_action_0049 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5c4ce5c1-4a9b-590e-96a2-f02a4bc9ea68 disabled=true
            projected_action_0050 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=96a5e9b4-6917-5cbe-868f-53638bb9ec66 disabled=true
            projected_action_0051 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9f97f120-9b9f-5092-a834-ec498d0eab7e disabled=true
            projected_action_0052 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P13"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e07a306a-bc52-58f0-beca-d6951b002df3 disabled=true
            projected_action_0053 = robot.move_to_point(
                point_id_or_robot_name='P13',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/1/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=721f8e79-31d4-532b-b04c-808e1d2fd934 disabled=true
            projected_action_0054 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8d6da0b6-972c-5d90-a875-cc18da232140 disabled=true
            projected_action_0055 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1972e074-db81-52b9-b25f-5b4c25cd5f6a disabled=true
            projected_action_0056 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=296a8f77-3db2-5721-ae47-3c4c0ff49211 disabled=true
            projected_action_0057 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7c566bd9-992a-582e-86ea-a5354e2fd385 disabled=true
            projected_action_0058 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=912d591b-ba96-5a8f-b18f-ba2e0170f692 disabled=true
            projected_action_0059 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cc8fa0d8-00e9-5dc9-a3e9-42ebdf72f713 disabled=true
            projected_action_0060 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=74a9b2ce-7bd1-5ce0-9897-076c7500f7b3 disabled=true
            projected_action_0061 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/1/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d7d62852-1894-5436-abb2-2ade2a9c3d02 disabled=true
            projected_action_0062 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=10430974-8baa-5ca7-becb-32508557caeb
        with group(name='ELIF 3（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5ee2e5a0-70a4-56fc-84b6-9b237f6a83b2 disabled=true
            projected_action_0063 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c1475b05-d161-5e34-bbea-920fdd892824 disabled=true
            projected_action_0064 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/2/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b69bd547-e01f-5408-bdc0-ef6de3d8b70b disabled=true
            projected_action_0065 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=902d534c-4fbd-5c96-b5b6-1509c3902bd5 disabled=true
            projected_action_0066 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=676b2d34-9110-5df0-8eda-bc83bcaf5dd3 disabled=true
            projected_action_0067 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5a6dd34d-d733-5ec0-b060-e3e6fc5f2338 disabled=true
            projected_action_0068 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bc242dd4-45bc-5c06-9e22-d108db9a8084 disabled=true
            projected_action_0069 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d5b11dc6-95b7-58d0-9295-5c26a0538e84 disabled=true
            projected_action_0070 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=111c884d-25da-5b7e-a90b-f8657ae3b650 disabled=true
            projected_action_0071 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P14"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1bbb3c04-e55c-5dd3-a442-b7c1673f6c3a disabled=true
            projected_action_0072 = robot.move_to_point(
                point_id_or_robot_name='P14',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/2/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d127e008-7d7c-5262-9aae-7fec5dab2e52 disabled=true
            projected_action_0073 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fdb3c99f-aeb5-5d4d-9022-29d8e8d3552b disabled=true
            projected_action_0074 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=605ed1eb-e975-54dd-85f2-90f1d6c9ec33 disabled=true
            projected_action_0075 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1722792d-d97a-5097-a937-3ee96e9a4f3b disabled=true
            projected_action_0076 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c1eacc78-019d-571d-9c0a-c18596d1a2d2 disabled=true
            projected_action_0077 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6038eb7a-7bfc-5f84-a452-efcc65c5cf63 disabled=true
            projected_action_0078 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3e4e2182-ec29-540a-8fca-7f388017626a disabled=true
            projected_action_0079 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=08ca9814-4f0e-543f-a9b6-c836bac5f4e0 disabled=true
            projected_action_0080 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/2/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=de29fa1e-d8b6-5a5d-9a01-62b2f36ade99 disabled=true
            projected_action_0081 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=e84941ed-11fc-5da1-9832-408c02a48e7f
        with group(name='ELIF 4（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8a1f1823-d540-5f5b-9152-5188efae3344 disabled=true
            projected_action_0082 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=06066768-efe5-5bbb-9071-4adf5a34a77e disabled=true
            projected_action_0083 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/3/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8db02c26-e0b6-5c0a-8266-bc6cded71be3 disabled=true
            projected_action_0084 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f2a873d7-0dd8-559c-9dba-11e23c424321 disabled=true
            projected_action_0085 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dbf7a202-73da-54e9-a1a1-c7245d43a29c disabled=true
            projected_action_0086 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c4c62c2d-4e6f-5b94-a2ee-89d144a8208c disabled=true
            projected_action_0087 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8ed9ebcb-cbeb-5fad-8d7c-cf94b12ede9e disabled=true
            projected_action_0088 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P15"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b44e59aa-05d0-5e13-bb1f-c086bc766aa6 disabled=true
            projected_action_0089 = robot.move_to_point(
                point_id_or_robot_name='P15',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/3/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=15f30b50-21d9-5126-b2d9-c7c5d9264e45 disabled=true
            projected_action_0090 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a14804c7-be38-5532-8cc9-687713dc0923 disabled=true
            projected_action_0091 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1cdc80e6-b8da-5a1e-9000-e9300fe26e65 disabled=true
            projected_action_0092 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8858a9e3-e66d-5f11-a0c5-5ea699d32634 disabled=true
            projected_action_0093 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=40e5798f-e904-50c7-9b0c-270ff071b4b2 disabled=true
            projected_action_0094 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6b1e771e-4f04-54ee-b721-1b95fecb8741 disabled=true
            projected_action_0095 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/3/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5647299e-ad7d-50bf-ba15-2b099a0f3504 disabled=true
            projected_action_0096 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=ac7eda8e-6802-5651-8dc1-ea0c7f6dd7e4
        with group(name='ELIF 5（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3ec53187-6245-5ec5-91ea-726fb498415a disabled=true
            projected_action_0097 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=607779eb-5d15-5639-ad18-c7f219a8634d disabled=true
            projected_action_0098 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/4/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=60252ae0-0b9a-5b9e-8b4d-1d024e2bd148 disabled=true
            projected_action_0099 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4ba90848-93d5-5033-b286-b1f30d2aa8f9 disabled=true
            projected_action_0100 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=34de7420-c06d-5bf8-8507-75923af97626 disabled=true
            projected_action_0101 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b4aea27c-3538-58b0-869b-7117ec7f8be8 disabled=true
            projected_action_0102 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7b1a8403-6449-5384-b1e7-0436946cc3f0 disabled=true
            projected_action_0103 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P16"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fe1d5eba-1027-52de-8713-2208bd1329d9 disabled=true
            projected_action_0104 = robot.move_to_point(
                point_id_or_robot_name='P16',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/4/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1958f7dc-72eb-595b-8e16-f4d399f31a5d disabled=true
            projected_action_0105 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7cbdec16-0a79-518c-8524-1fa8b12d3f70 disabled=true
            projected_action_0106 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=596197ac-4cb6-5905-9f96-7a32dbeed2d3 disabled=true
            projected_action_0107 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1f3ec28b-3862-5158-bb2b-fd0558470fed disabled=true
            projected_action_0108 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=88bbdaae-041a-5a1c-b713-9deee6815339 disabled=true
            projected_action_0109 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ff19d74d-ce8a-53f0-a25e-afce106d0c0a disabled=true
            projected_action_0110 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/4/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8dbf1d61-300a-5f1b-abe7-05b04c9c3128 disabled=true
            projected_action_0111 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=3102fbcc-19cd-5c6c-857d-a96f857caccf
        with group(name='ELIF 6（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=72ec9080-f297-5869-a119-0e948dafa28b disabled=true
            projected_action_0112 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=388b3c2c-2e3c-5448-b497-1053180e7bc2 disabled=true
            projected_action_0113 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/5/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=aa490475-7dea-58cc-b0ff-982042d75323 disabled=true
            projected_action_0114 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c53bc8cf-0a1b-5215-aab5-35c674ca4b21 disabled=true
            projected_action_0115 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4fddc8e3-04ce-5c94-a06c-a60396d4e0b7 disabled=true
            projected_action_0116 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9c277d16-445c-52bb-b9bd-32e7873e9b77 disabled=true
            projected_action_0117 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6ac05567-a443-525c-a374-bf149e7820ab disabled=true
            projected_action_0118 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P17"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=04ec8ef8-9b92-5cc3-b8d8-8f7a95f27338 disabled=true
            projected_action_0119 = robot.move_to_point(
                point_id_or_robot_name='P17',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/5/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=61fcd89e-cbe3-5ecc-a6b2-c0600f315c52 disabled=true
            projected_action_0120 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d4de37ab-d86b-5395-ac52-af03b2b3d52a disabled=true
            projected_action_0121 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f5bfb397-e7c2-57e0-a40c-e96e84fc2eb4 disabled=true
            projected_action_0122 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5615267f-fa2c-5c75-89fe-e0e0294e1064 disabled=true
            projected_action_0123 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d288417a-d3b9-5030-8ff5-279583a4feac disabled=true
            projected_action_0124 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b0f89bd3-cff4-5500-92e9-20b223928c56 disabled=true
            projected_action_0125 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/5/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=eedc5051-f32e-52c3-858a-0b18506ebb0b disabled=true
            projected_action_0126 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=7de9425c-5fe8-576e-96e3-b10b4ebad8c1
        with group(name='ELIF 7（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6ab531c8-f01f-552a-8b42-0210eb999859 disabled=true
            projected_action_0127 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2a994d24-56f1-5736-bc4c-4c2a6e5a72e9 disabled=true
            projected_action_0128 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/6/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3313a0f6-5e2d-5414-aea8-32e03eab4668 disabled=true
            projected_action_0129 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=23cda9f3-d35f-528a-a4aa-89415363933d disabled=true
            projected_action_0130 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b9a25dd1-8fce-547b-b9e5-0c95e130992f disabled=true
            projected_action_0131 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=22bc8f5b-9251-5ae9-a2e2-07184d4d96a4 disabled=true
            projected_action_0132 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=be00452a-5ce9-56d5-97dd-9f8724cb36e3 disabled=true
            projected_action_0133 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P18"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c3c42aac-d138-51f3-af41-45652a0eaf3e disabled=true
            projected_action_0134 = robot.move_to_point(
                point_id_or_robot_name='P18',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/6/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2c5d448a-7c27-5645-ac64-24bba5ff1516 disabled=true
            projected_action_0135 = robot.tool_action(
                action='suction-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=40e126f2-11c2-59d0-8bf7-078ba05e4a40 disabled=true
            projected_action_0136 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c3edd64a-c59b-5a4b-aa96-5677a137657d disabled=true
            projected_action_0137 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7809327f-4d55-59b2-86ce-02962111e9bf disabled=true
            projected_action_0138 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=471d0e3e-eed1-5086-8843-4d742555c63f disabled=true
            projected_action_0139 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=45b7a3c4-ce0a-5dda-bfd8-555acb477ace disabled=true
            projected_action_0140 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/6/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8b19d5e0-9696-5fe6-8de0-feab302cc9e0 disabled=true
            projected_action_0141 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=fdd7b007-f5f1-5f60-a19f-090f1cccc24f
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_tank_pick@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=1757005b-fd75-5f1f-b6de-3eec7ebfb685 disabled=true
            projected_control_0142 = material.review_control_node_v1(
                operation_name='robot_tank_pick',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='32ae16ae681aa5148137c6786f43f7e401bde992d06a0128c8cf67758c6949ee',
            )
