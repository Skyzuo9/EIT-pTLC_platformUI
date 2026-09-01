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
    workflow_uuid='7c2577e7-c852-5552-a56a-1db9afb7c3a0',
    displayname='展缸放板 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_tank_put_operation_view_v2() -> None:
    # [OPERATION robot_tank_put] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=9ebd7027-abd7-56e5-84f3-0ea9ade88ea7 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_tank_put',
        inputs_json='{"tank_id":1}',
        expected_sha256='5cf9357ec1355ac94fbe37c8f3ff07af004bd779e0d5f55fffa49d98087b6ed6',
    )
    # [VERIFY comment] 只读来源校验 robot_tank_put@body/0；本视图中静态 disabled。
    # unilab:node_uuid=60fece14-ce61-50cb-9c35-164a8ea75fd8 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_tank_put',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
    )
    # [ACTION robot.home_ensure] 来源 robot_tank_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=32418af6-3344-55a3-bb3e-473d59cd8cf6 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_tank_put@body/2；原节点 {"inputs":{"needed":{"lit":1}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=f91778a3-693c-5096-b3e3-58ab85fa3979
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_tank_put@body/3；原节点 {"cond":{"binop":"==","left":{"var":"tank_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":...
    # unilab:node_uuid=7f05f8e7-7d32-5105-9888-d9d78ca26f6c
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_tank_put@body/3；本视图中静态 disabled。
        # unilab:node_uuid=cbaa0a53-836f-5f14-834d-65169eacd587 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_tank_put',
            node_path='body/3',
            control_kind='if',
            expected_sha256='7cac4ccf99418e919c33ae5e47bac4a426b84d6c9049626da54c690b9241a381',
        )
        # unilab:node_uuid=b92828d5-bf5b-5cc1-805e-f78a138d0e1c
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=163f839f-534d-5747-8057-ba25657a19c7 disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f197fa37-fe18-54c7-a50e-5804540fc3c1 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e7322e5b-4e89-5ce5-a197-4110977580b5 disabled=true
            projected_action_0008 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=217adfa6-c786-5fa6-80fd-2015ac9392fd disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=32e22679-d589-544e-8806-54cfffb9c9de disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4180e80a-280b-5ddc-b8e3-7e1c16940262 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b9e97fd5-d754-5573-9227-04359b98950f disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5f908cef-313c-521e-bebf-e773a930afa7 disabled=true
            projected_action_0013 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bb5a1816-4e02-53b7-beda-102bfb567e1a disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P11"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b9a63745-edc7-59a9-a32f-08dcd7795b09 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='P11',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/then/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3ecb2616-f436-55bf-a466-c2d3a3d7dce3 disabled=true
            projected_action_0016 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=57770a55-b472-580a-980d-e1d374aacecd disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7edaab89-e555-5630-926f-42415156aa5e disabled=true
            projected_action_0018 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=26981558-6c7a-5372-9644-e36fd41dc8ae disabled=true
            projected_action_0019 = robot.move_to_point(
                point_id_or_robot_name='tank.1.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=84cb4dc4-df4e-52d1-b4d7-2e227ea9b946 disabled=true
            projected_action_0020 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=614bf880-bfbe-592e-a24c-4b571c7f27a9 disabled=true
            projected_action_0021 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b608446f-75ee-58af-9975-230f6d2fffa7 disabled=true
            projected_action_0022 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8e72e46f-bf3d-5cd2-a636-1f70dced2b1a disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/then/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=17749c4d-4b79-5270-a20f-9449a4b9025f disabled=true
            projected_action_0024 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=7018d2fc-dd6f-513e-a328-0e8d0c07e206
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8ef355d0-d4a7-51c0-9010-ffeb878e773e disabled=true
            projected_action_0025 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cc4688c6-d1d2-5836-ba6c-051f9dbbae17 disabled=true
            projected_action_0026 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4222ba03-b020-5ac3-919c-f11f3257ae9c disabled=true
            projected_action_0027 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e26d1fe5-cd8e-534a-b886-30912607865e disabled=true
            projected_action_0028 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=076683f9-4a6d-5fd5-beea-7c1ff8ceafcb disabled=true
            projected_action_0029 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3775749b-e474-5610-b589-246f4d62f96e disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c327e787-aaa0-5664-857e-29be94e92b07 disabled=true
            projected_action_0031 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=891f2764-a815-5143-98ae-1716f38dae25 disabled=true
            projected_action_0032 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f4d50d1d-f0ce-55b1-a2f2-21bc628823d7 disabled=true
            projected_action_0033 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P12"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dc2eea1e-14ee-5922-a9ba-8b11d40c8397 disabled=true
            projected_action_0034 = robot.move_to_point(
                point_id_or_robot_name='P12',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/0/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e9561e7c-94bb-5085-abd6-fafda23f8754 disabled=true
            projected_action_0035 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e6e60f22-7334-502a-aecf-a931d4d1f6d0 disabled=true
            projected_action_0036 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e1356c3d-3c38-5d4c-b4a9-5eb73c5b0564 disabled=true
            projected_action_0037 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ff3991af-34d0-52c9-a426-2ff7d2d739ca disabled=true
            projected_action_0038 = robot.move_to_point(
                point_id_or_robot_name='tank.2.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2382901f-0f48-5f1b-97b9-67c6e67ba55c disabled=true
            projected_action_0039 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a7918a09-b5f5-569b-b09e-0d8d4d9f4ee1 disabled=true
            projected_action_0040 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8423f817-5c0e-5a58-ab30-8817386d267e disabled=true
            projected_action_0041 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e6284677-f88e-52b8-8f10-c0d9aab95842 disabled=true
            projected_action_0042 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/0/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=75186827-1bbd-5b1f-8f32-1a90f7e29173 disabled=true
            projected_action_0043 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=6085b794-257e-5046-9dda-4b9227a3bda1
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=62e3cdf9-39a6-561f-9a29-47dd3f29a6fa disabled=true
            projected_action_0044 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cd825e91-208c-560d-8d00-78e9558cd696 disabled=true
            projected_action_0045 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d6deb5be-c3c8-5b74-a956-1f15391b130f disabled=true
            projected_action_0046 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=39e134cc-81ff-5e6b-b213-b4f9e8fdcead disabled=true
            projected_action_0047 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dadbf46e-8e0c-5131-a1ed-427be2874806 disabled=true
            projected_action_0048 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=689b02ef-cbb6-587e-b21a-694430b5d29c disabled=true
            projected_action_0049 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6ce56413-7c31-583b-a3c0-8e405b5daa35 disabled=true
            projected_action_0050 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8e18fd87-6234-5e5c-afd0-eb44bfd87db1 disabled=true
            projected_action_0051 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d73227f2-e2e8-59b5-a99b-2ec9798bfcf5 disabled=true
            projected_action_0052 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P13"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=99b73be6-b0e9-5b95-b6bd-2141150d3b6d disabled=true
            projected_action_0053 = robot.move_to_point(
                point_id_or_robot_name='P13',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/1/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=017b36cf-f781-5881-9fc0-7648c6f82006 disabled=true
            projected_action_0054 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3159aeba-2d8b-51ad-bf51-cdb67c314ef3 disabled=true
            projected_action_0055 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d7f8b031-12ef-56af-be48-61d113632f8c disabled=true
            projected_action_0056 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=13f5e4d9-af57-5bdc-932d-4b762219e89c disabled=true
            projected_action_0057 = robot.move_to_point(
                point_id_or_robot_name='tank.3.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=78fefdc2-c630-5123-9080-de638cd7e153 disabled=true
            projected_action_0058 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=74b38585-4f29-564c-9c01-9897f96a357f disabled=true
            projected_action_0059 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2dd2ca08-af03-5b07-94ca-227f8f238187 disabled=true
            projected_action_0060 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6930b9ac-5de5-5189-a5b6-6b437e7a6574 disabled=true
            projected_action_0061 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/1/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=beb65396-f9d2-542d-a70c-87415e53d9f8 disabled=true
            projected_action_0062 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=16b21dc9-1a46-5513-9d0d-d887a0946362
        with group(name='ELIF 3（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bd157ae6-ddc0-54db-adbd-c076161e1d30 disabled=true
            projected_action_0063 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c37df245-e446-54e3-87c2-b9046f28f027 disabled=true
            projected_action_0064 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/2/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=05b8a903-34a2-5a80-9459-a111e883e336 disabled=true
            projected_action_0065 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8dcdbd85-d650-5732-bad0-64f15d8d8bd0 disabled=true
            projected_action_0066 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d143cf3f-f194-5518-ba7d-60be0ed0f8cd disabled=true
            projected_action_0067 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4c5752a8-8c51-5401-872b-b8b2e830b46a disabled=true
            projected_action_0068 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5ec31d56-9256-5d18-85d4-70186f36a470 disabled=true
            projected_action_0069 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=13727330-a519-537a-ba8b-f1b9dd7a5b67 disabled=true
            projected_action_0070 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f0d0cc22-ef36-5033-aec7-c88919660116 disabled=true
            projected_action_0071 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P14"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b1ae8539-db11-523c-86c9-36d21fdc2b9d disabled=true
            projected_action_0072 = robot.move_to_point(
                point_id_or_robot_name='P14',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/2/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7e38b937-11e2-568a-89ae-14059e525726 disabled=true
            projected_action_0073 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6e396af4-077b-5be7-8e2e-2fa9ff4b718d disabled=true
            projected_action_0074 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6bf6d66c-e47b-5326-a5ed-086d7e187b58 disabled=true
            projected_action_0075 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a1dd53ae-9bd4-59d7-97e8-49c970a6d19c disabled=true
            projected_action_0076 = robot.move_to_point(
                point_id_or_robot_name='tank.4.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4c218daa-25c7-53f3-a5f0-496c251c7e81 disabled=true
            projected_action_0077 = robot.move_to_point(
                point_id_or_robot_name='P59',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=626502a4-ae44-5867-98d2-0ac6d207060e disabled=true
            projected_action_0078 = robot.move_to_point(
                point_id_or_robot_name='P84',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=591be4dc-e7be-5e1b-8626-e7b47c6683b8 disabled=true
            projected_action_0079 = robot.move_to_point(
                point_id_or_robot_name='P75',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f731cb9d-9669-5c33-ba03-fa5fff7f90ad disabled=true
            projected_action_0080 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/2/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4735e57c-74e3-5820-9082-f11ef195d8dc disabled=true
            projected_action_0081 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=31432161-50fe-517f-be3a-e0329cc2d1d5
        with group(name='ELIF 4（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cd1497ad-171d-5903-ad23-4537ecad85c3 disabled=true
            projected_action_0082 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c9bf8091-9ef8-5594-af4e-408905a47893 disabled=true
            projected_action_0083 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/3/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=04d31d4e-3868-5dac-a1ab-ccb8d79860d6 disabled=true
            projected_action_0084 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=66f6c0a5-f03d-5994-8e9e-6b3c9d24e0e9 disabled=true
            projected_action_0085 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4861a37e-dd4a-5be2-8237-d78aae572a31 disabled=true
            projected_action_0086 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5fd5d055-e838-5a15-96e8-978fd3a2f117 disabled=true
            projected_action_0087 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4d54541e-a3dd-59d7-a94c-a65633ae0bd5 disabled=true
            projected_action_0088 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P15"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=54510dc0-925e-5a80-ad4c-acfd559d918a disabled=true
            projected_action_0089 = robot.move_to_point(
                point_id_or_robot_name='P15',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/3/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d099b120-bfe5-51db-83c9-d4430a321ede disabled=true
            projected_action_0090 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c6766ff8-e2bd-5587-94b6-4a8870b00c93 disabled=true
            projected_action_0091 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=41a75fa7-4701-542c-ad3c-b636ffa790f9 disabled=true
            projected_action_0092 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5123efb6-39d5-507d-aaf6-408ba9a1881e disabled=true
            projected_action_0093 = robot.move_to_point(
                point_id_or_robot_name='tank.5.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=516844e6-bad5-58f1-93c3-5b17775d5a93 disabled=true
            projected_action_0094 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ea3b0f9e-bfb8-5f94-952e-b956ca379239 disabled=true
            projected_action_0095 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/3/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=52cc330a-e9fb-5b54-a05a-416d937897c5 disabled=true
            projected_action_0096 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=cd804576-5a40-5c91-8094-a24be40333bb
        with group(name='ELIF 5（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8b13d857-2bc2-5391-98aa-febdf6ea8ec2 disabled=true
            projected_action_0097 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a66000d6-d3de-5aa7-9acc-b1e447abc32a disabled=true
            projected_action_0098 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/4/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=375d6077-baaa-59b4-ab64-586e7f227a7a disabled=true
            projected_action_0099 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0bf38397-cc17-552e-97e1-775b5a5a5f90 disabled=true
            projected_action_0100 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=00248897-9b81-5cfd-9a83-f4228ccce527 disabled=true
            projected_action_0101 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fd7b00f2-963e-537a-84ee-9dcb64653961 disabled=true
            projected_action_0102 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d4ed934a-1613-5e3e-80eb-960dabd288e8 disabled=true
            projected_action_0103 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P16"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ec8af298-826d-5c95-8c47-18b4a7f47061 disabled=true
            projected_action_0104 = robot.move_to_point(
                point_id_or_robot_name='P16',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/4/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7b0471b1-6243-5099-b073-6fe7bae115ad disabled=true
            projected_action_0105 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0dd5e774-c498-5713-92b5-2eca46ec2ced disabled=true
            projected_action_0106 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9224482f-2567-5315-a232-2c6cfa1f9708 disabled=true
            projected_action_0107 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=abfe15c5-831f-5378-8edb-26909a1ff984 disabled=true
            projected_action_0108 = robot.move_to_point(
                point_id_or_robot_name='tank.6.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3bf72d89-608f-588c-be44-fe74feab46c7 disabled=true
            projected_action_0109 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=07cabc6c-1587-5f22-9653-f2c1d241e237 disabled=true
            projected_action_0110 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/4/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=74f2844c-5e6b-5604-981a-534d1200ca21 disabled=true
            projected_action_0111 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=c500cf5b-ebc7-5f98-b0d5-455a25ace0ec
        with group(name='ELIF 6（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=35d791d8-751a-58f1-8a00-4f38ba4d7027 disabled=true
            projected_action_0112 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ed4b8c13-c0a6-5777-a56a-4e483f5a78f3 disabled=true
            projected_action_0113 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/5/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8ed0313c-454d-598c-abf7-f61338c29be1 disabled=true
            projected_action_0114 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=48cbe4f4-4320-5718-8ebc-32ee6100950d disabled=true
            projected_action_0115 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ff357d01-ad86-5f75-97f8-488dc91db7bd disabled=true
            projected_action_0116 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f04a6efb-de81-568c-82e4-d53a99866732 disabled=true
            projected_action_0117 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=00fedd10-3a60-5ba3-bb9a-62dd65efa4b9 disabled=true
            projected_action_0118 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P17"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2359ecd4-0ed7-530f-b514-4235bea9b136 disabled=true
            projected_action_0119 = robot.move_to_point(
                point_id_or_robot_name='P17',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/5/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5ea73bb1-535a-5c9c-856f-4094cdce01e2 disabled=true
            projected_action_0120 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5102c0c3-24ab-589a-9c60-3186517b9f56 disabled=true
            projected_action_0121 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=af63ea25-c618-5000-ae14-52201970e830 disabled=true
            projected_action_0122 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7f962f00-ed3d-5e87-937e-6562df15ef53 disabled=true
            projected_action_0123 = robot.move_to_point(
                point_id_or_robot_name='tank.7.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=93138886-c629-5035-be38-d8270d9b5f8e disabled=true
            projected_action_0124 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c7fd5ec9-219c-5050-8d2d-d8cc6f60b571 disabled=true
            projected_action_0125 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/5/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2439e567-7482-517a-9b7f-6423cfb76dba disabled=true
            projected_action_0126 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=740aa15c-3f54-5fd3-8915-da2f66353d2b
        with group(name='ELIF 7（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=476ba641-49b2-5e36-8eab-2c0d6a7ea6fa disabled=true
            projected_action_0127 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b5e0738a-55b0-5408-848a-28928f3a3559 disabled=true
            projected_action_0128 = rail.ensure(
                Rail_Target_Position=5,
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/6/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ac50b734-11d2-58a0-b63e-65899325ff88 disabled=true
            projected_action_0129 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=593230d0-7090-5c0a-9c2f-4415b0c66f0a disabled=true
            projected_action_0130 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a5b897ac-4d01-52ab-99da-cd3c61e9f013 disabled=true
            projected_action_0131 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c87aa521-abf5-5f95-84e8-6573f14740c2 disabled=true
            projected_action_0132 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9283da95-7a48-5630-b4c4-c3195258f9be disabled=true
            projected_action_0133 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P18"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=80aec024-bcef-5184-9c57-1b1e725588c6 disabled=true
            projected_action_0134 = robot.move_to_point(
                point_id_or_robot_name='P18',
            )
            # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/6/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c50c39de-d2d6-53de-9550-a654d44a6ca6 disabled=true
            projected_action_0135 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ad08394c-def0-502a-a8d0-d8830938e857 disabled=true
            projected_action_0136 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3f588b5f-342c-5579-9d6f-222edffdf4df disabled=true
            projected_action_0137 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=77e2b34e-bed7-5c1a-938c-5651096b391d disabled=true
            projected_action_0138 = robot.move_to_point(
                point_id_or_robot_name='tank.8.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ebb8f78b-c49a-5386-8882-cace59405268 disabled=true
            projected_action_0139 = robot.move_to_point(
                point_id_or_robot_name='P3',
            )
            # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6cc50cc0-48a0-5fb2-8ca2-8082d0016d89 disabled=true
            projected_action_0140 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/6/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=24d61316-b07b-57cd-baae-48f036561cb1 disabled=true
            projected_action_0141 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=4f443c65-db89-5329-a50f-cdb99187082d
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_tank_put@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=d67d2206-5bde-52fd-96f1-a7bc32abe3f2 disabled=true
            projected_control_0142 = material.review_control_node_v1(
                operation_name='robot_tank_put',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='de61415eb83d471c2a3b728a840f3467de1f470c18605c1098d37289a9851744',
            )
