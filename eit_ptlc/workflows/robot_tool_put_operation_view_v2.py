from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_rail import PLCRail
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


material: MaterialProxy = device('material')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='7326d442-3b82-509c-b47e-81050ac0dec7',
    displayname='卸刀 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_tool_put_operation_view_v2() -> None:
    # [OPERATION robot_tool_put] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=0c214219-75ee-5183-b479-7b7d5870efb8 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_tool_put',
        inputs_json='{"tool_id":1}',
        expected_sha256='d623810e60b08514d926141dffcf5e086f7cc7d165180913bc31c792a30c1517',
    )
    # [CONTROL if] 来源 robot_tool_put@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit...
    # unilab:node_uuid=5dde19c3-1e07-5976-909a-9b36bf27c63d
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_tool_put@body/0；本视图中静态 disabled。
        # unilab:node_uuid=a6fc29ba-8499-51c8-b968-2cc847bfd1cf disabled=true
        projected_control_0002 = material.review_control_node_v1(
            operation_name='robot_tool_put',
            node_path='body/0',
            control_kind='if',
            expected_sha256='9c64b805f035e287559b6a10c2883f201fed2852028900bfd6c9c7526352d298',
        )
        # unilab:node_uuid=da53a15c-a127-5c49-adb3-8edce641c8b9
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=54e39834-55a7-5ff2-8e2c-72b1115fb553 disabled=true
            projected_action_0003 = robot.require_anchor(
                point_id='robot-main.home',
            )
            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e59887e8-83b6-5090-a2be-88ddfbb87d1b disabled=true
            projected_action_0004 = rail.ensure(
                Rail_Target_Position=4,
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f0c275a2-acb3-5b41-ab18-d94f2c5d377a disabled=true
            projected_action_0005 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=04bd6c43-2a72-58cd-b79c-c91a262c9c75 disabled=true
            projected_action_0006 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.ready',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ccc03f1d-4c18-5cde-a5b6-76ecb5ef0f9a disabled=true
            projected_action_0007 = robot.tool_action(
                action='tool-change-aux-on',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0b551011-c593-5702-91bc-7054b3cb6203 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b4cdaa7d-622b-5318-a59a-8cb3cd14a95c disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=43c5fa69-7501-5157-aeb7-7f89afeedf73 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.target',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2679c329-f0f7-5577-a42f-e38a4e1e8a80 disabled=true
            projected_action_0011 = robot.tool_action(
                action='quick-change-release',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/9；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fd291841-85de-5c18-900e-0e7cc3ac88fc disabled=true
            projected_action_0012 = robot.tool_action(
                action='tool-change-aux-off',
            )
            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/then/10；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c911fea5-5490-5aa4-b182-e55ea31fef1b disabled=true
            projected_action_0013 = robot.set_mounted_tool(
                tool_id='0',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c930d637-929f-5326-b977-eaaa832ac2c9 disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9d74be37-a647-5259-82dd-94c23bf3c817 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
            )
        # unilab:node_uuid=b97035e5-8f3a-53bf-9fcd-980323fb7bf9
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3eac07b0-ecf4-5f85-af46-26945bb3326b disabled=true
            projected_action_0016 = robot.require_anchor(
                point_id='robot-main.home',
            )
            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=28a6ffb8-c89f-5e37-b989-138cccaa5dde disabled=true
            projected_action_0017 = rail.ensure(
                Rail_Target_Position=4,
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=727bf809-c8fc-5ec9-8d74-5a3d3c4cffd1 disabled=true
            projected_action_0018 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=76286d76-6dfa-5ae5-bd8e-6422dd8ee002 disabled=true
            projected_action_0019 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.ready',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cf569c69-520b-50c9-bd64-b1b38d4a031d disabled=true
            projected_action_0020 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2700bc66-9b50-5e97-8abb-06c84f380ff7 disabled=true
            projected_action_0021 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=df3e605f-f863-5c97-8846-faf898d7a05b disabled=true
            projected_action_0022 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.target',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=09464ab4-5653-5b75-af50-bbd0ec1ef269 disabled=true
            projected_action_0023 = robot.tool_action(
                action='quick-change-release',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=52766bf7-9089-51d1-a4ec-8867051f8300 disabled=true
            projected_action_0024 = robot.tool_action(
                action='tool-change-aux-off',
            )
            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/0/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=12f0b79a-e6f6-554f-b9a5-cbaf7a983b8a disabled=true
            projected_action_0025 = robot.set_mounted_tool(
                tool_id='0',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d47577ef-ecd5-502a-bca1-2e783c5a471d disabled=true
            projected_action_0026 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=41be1aa8-18f1-5114-a262-77d07b413ecc disabled=true
            projected_action_0027 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
            )
        # unilab:node_uuid=612de1b4-5153-584e-af06-04aa9e5f0e92
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=df76526b-27c5-5d23-8df1-3f59cc306365 disabled=true
            projected_action_0028 = robot.require_anchor(
                point_id='robot-main.home',
            )
            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=67b94fbb-df1c-5e22-a6ce-bc789a77ff3c disabled=true
            projected_action_0029 = rail.ensure(
                Rail_Target_Position=4,
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f8ac1921-9746-58f9-af8a-b5c88324ec3a disabled=true
            projected_action_0030 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f9380f5a-0737-5d6d-b811-aebfbad3847b disabled=true
            projected_action_0031 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.ready',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=19525f4a-6d3d-5dd6-afc7-59c3012a1eb7 disabled=true
            projected_action_0032 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=36c78d49-61c2-579c-8256-54e19a859b58 disabled=true
            projected_action_0033 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5f0bd3bb-4dc7-5a10-a6dc-3688a9ba58fe disabled=true
            projected_action_0034 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.target',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=34e9a2b6-e386-575b-8d90-d50022c57464 disabled=true
            projected_action_0035 = robot.tool_action(
                action='quick-change-release',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=97e94d64-f563-5f4c-b63c-2f6f0fba9489 disabled=true
            projected_action_0036 = robot.tool_action(
                action='tool-change-aux-off',
            )
            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/1/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dedf926e-a32e-5cc6-bcb7-47fa0f74e690 disabled=true
            projected_action_0037 = robot.set_mounted_tool(
                tool_id='0',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=824e9204-9760-52a5-8777-c4fe42931496 disabled=true
            projected_action_0038 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=81b7e998-2da7-53fb-9959-6a17a5ff6854 disabled=true
            projected_action_0039 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
            )
        # unilab:node_uuid=e63db451-e6d8-570d-8f78-33b7459cd43a
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_tool_put@body/0/else/0；本视图中静态 disabled。
            # unilab:node_uuid=db7dc38e-0841-594f-89db-bb1cf567daeb disabled=true
            projected_control_0040 = material.review_control_node_v1(
                operation_name='robot_tool_put',
                node_path='body/0/else/0',
                control_kind='raise',
                expected_sha256='8aa6aa6f749c6777b2a7040e04f4316dd03cc80d36de51eec476b3dbb6c6de75',
            )
