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
    workflow_uuid='55ad413c-4a72-555f-91bc-4196c2bde2a9',
    displayname='中转台取单件 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_individual_pick_operation_view_v2() -> None:
    # [OPERATION robot_individual_pick] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=b8482f0f-4c68-5b2f-9d96-f34debc33161 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_individual_pick',
        inputs_json='{"exit_anchor":"P1","rack_id":"collector","slot_id":1}',
        expected_sha256='e75669db707b97f8c9ac0f733ceb5d0e93fb7aaeff359657b33735aa67511c8e',
    )
    # [VERIFY comment] 只读来源校验 robot_individual_pick@body/0；本视图中静态 disabled。
    # unilab:node_uuid=dbdeabf4-554c-5f92-a466-78380f208b68 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_individual_pick',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
    )
    # [ACTION robot.home_ensure] 来源 robot_individual_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=9e63f712-8888-574e-a5f8-d85e95d3a00a disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_individual_pick@body/2；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=9725797d-fbae-5d1d-b34f-de6642afd51e
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_individual_pick@body/3；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"right":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit"...
    # unilab:node_uuid=065c4f79-be24-5321-8ef3-4333f61a1a88
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_individual_pick@body/3；本视图中静态 disabled。
        # unilab:node_uuid=adca26e1-e52d-5071-bdc7-9ba9a7db2492 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_individual_pick',
            node_path='body/3',
            control_kind='if',
            expected_sha256='10ac28536da762f8be3b04b3bc814687c2e9427c2573ad6aeac2f3378299f9d1',
        )
        # unilab:node_uuid=67af228f-140d-58da-959b-e5c45c91407a
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9a88cbc1-12d8-518b-8804-77957e91a734 disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=23f0784d-3b77-56c0-a948-845f25ccc8c1 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9b233941-c742-5a35-8db2-68f686a69cc9 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=898db2a7-f2ae-5caf-ab15-90bb4655ba41 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p46.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=45c53547-3e95-5b78-97a8-56091e9ecfd1 disabled=true
            projected_action_0010 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f2b80205-7033-5a16-bbcd-f702972b330e disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p46.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P46"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=41b388a3-24b2-5b28-beb5-7047c565e5cf disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='P46',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2f34a1f5-68f9-50e8-b68c-259e1c3aa900 disabled=true
            projected_action_0013 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b7761745-ea8e-5419-ae25-1087ad256a80 disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p46.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0bb11075-cd8c-5fcb-9ed2-8e301df696e8 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p46.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b74690b1-b367-5aed-9d67-d0ab88dd2bda disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1bfc96ee-b159-5d9e-a90b-4edd6286a8b5 disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/then/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0c900200-76a7-56f2-b1bc-92649ddc4625 disabled=true
            projected_action_0018 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=35516efd-06e8-50da-b34a-b77f46694cf6
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fe44d023-9127-555d-bbe4-f4eb815f2e50 disabled=true
            projected_action_0019 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a39b2316-1862-51bf-9ba6-ece6ad81c3c6 disabled=true
            projected_action_0020 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8a45f5d5-a569-57c5-8944-e5ebc3a74c80 disabled=true
            projected_action_0021 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=30f306fd-7e0b-50be-8727-e5aec9d3f832 disabled=true
            projected_action_0022 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p47.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e61a5779-db79-5514-a18d-da6b04600ebf disabled=true
            projected_action_0023 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0849ab39-3d41-5147-a648-cca63a3e7cd2 disabled=true
            projected_action_0024 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p47.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P47"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=93d83cdc-ce48-5230-bbde-7f6d5ec689f8 disabled=true
            projected_action_0025 = robot.move_to_point(
                point_id_or_robot_name='P47',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5e644e58-1d29-5a70-a078-bfcfa6d93123 disabled=true
            projected_action_0026 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=36328376-1744-5ca4-9607-d47ae6d7e125 disabled=true
            projected_action_0027 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p47.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=79b88ad7-38a0-531d-9ffc-0ac2cfd6d6ec disabled=true
            projected_action_0028 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p47.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=319dc0a3-7ab1-5482-8db5-cf879f2c5579 disabled=true
            projected_action_0029 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=07315f25-ca0e-5eae-916e-03327192195e disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/0/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=05934fdd-563c-5082-89b2-73589286feb9 disabled=true
            projected_action_0031 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=9b54a7d8-9aba-5c85-bb97-e78f6751d3a4
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=614b0c17-5e5e-5d57-99de-ef846392ca1b disabled=true
            projected_action_0032 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3f795b92-0f9e-5128-a2f1-35572ebc8ac2 disabled=true
            projected_action_0033 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a371050e-7325-571a-b864-1ae7c5418c3f disabled=true
            projected_action_0034 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2d55dc06-3b11-5ee5-9223-9d0dbb2ce0aa disabled=true
            projected_action_0035 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p48.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/1/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8c2021a7-0028-5dc0-b008-c2dcc573829d disabled=true
            projected_action_0036 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2e86020f-796c-5207-be2f-336fa90143a5 disabled=true
            projected_action_0037 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p48.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P48"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2eba3847-7a87-5507-b3bc-b3cfb709882d disabled=true
            projected_action_0038 = robot.move_to_point(
                point_id_or_robot_name='P48',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=02b5f376-597e-5fdd-bcc5-59be7c84cc21 disabled=true
            projected_action_0039 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2a8f3f1c-db6b-5d74-a074-92a8309a21b0 disabled=true
            projected_action_0040 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p48.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ff7ac088-7259-5824-9cb8-729548dc9783 disabled=true
            projected_action_0041 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p48.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5f63feb6-7523-5aed-9a96-5ef2ef56940f disabled=true
            projected_action_0042 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ac70e0af-36c9-5e02-8f68-0214374a1860 disabled=true
            projected_action_0043 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/1/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=591150e6-09bf-5525-bb2a-9282ac85a61b disabled=true
            projected_action_0044 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=95199130-0586-5f68-86f4-232e4d3ca625
        with group(name='ELIF 3（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9819851b-ab39-5d9d-971e-1da17557a7a9 disabled=true
            projected_action_0045 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=12356b5a-9af4-51e4-a80c-99ea7b418e5e disabled=true
            projected_action_0046 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8197cb1d-1a7f-505e-8505-02119f1928cc disabled=true
            projected_action_0047 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=92227987-6e1a-53bb-a18e-91040eb07aef disabled=true
            projected_action_0048 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p49.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/2/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=49c1ce9e-193b-530f-8ff2-eb2a17da3ba3 disabled=true
            projected_action_0049 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e11626b1-e856-5703-9fd5-3ec210e722ad disabled=true
            projected_action_0050 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p49.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P49"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=96137d56-5e8c-5da8-bd9a-caa5b391c1c2 disabled=true
            projected_action_0051 = robot.move_to_point(
                point_id_or_robot_name='P49',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/2/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0b3369a5-87c6-5b5c-a163-20f7a03d1f7b disabled=true
            projected_action_0052 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=843205d9-af51-56c8-86f6-2f15c7e05110 disabled=true
            projected_action_0053 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p49.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=14bd0a96-dd86-5a57-8f3a-cbff9c5c1512 disabled=true
            projected_action_0054 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p49.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2b2136f3-dac2-5254-805f-eef9422739ef disabled=true
            projected_action_0055 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1ff15bb9-f550-57c4-8116-a33565779e31 disabled=true
            projected_action_0056 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/2/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1b5c776e-0ef7-584d-aa76-065796b8c01e disabled=true
            projected_action_0057 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=ca310f3f-c147-5b65-95d0-d5238537e2b8
        with group(name='ELIF 4（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1d60811b-123a-5182-930b-dcf506f6dae9 disabled=true
            projected_action_0058 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c9f26428-989f-55be-9948-d62aa0641a71 disabled=true
            projected_action_0059 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dca1213b-745a-5574-a703-9c2c3d2e19a5 disabled=true
            projected_action_0060 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8760c1e2-019a-5616-b648-bb9bac714a1b disabled=true
            projected_action_0061 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p50.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/3/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d320c22a-a3cd-56b3-a45f-426a749890d1 disabled=true
            projected_action_0062 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=560c6512-1601-52cb-9136-4251ecf26fd4 disabled=true
            projected_action_0063 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p50.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P50"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b9163e5b-9eb9-5a21-b2b3-eb934bbda79a disabled=true
            projected_action_0064 = robot.move_to_point(
                point_id_or_robot_name='P50',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/3/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6ffc8b3b-db4a-5b86-831a-d64181f61f13 disabled=true
            projected_action_0065 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=74531fea-7523-5d03-a15d-688f89cf84ef disabled=true
            projected_action_0066 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p50.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d0369469-9062-5fa2-8cd9-cbabbe7a0bd3 disabled=true
            projected_action_0067 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p50.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=af25f66b-f4a1-50b6-8f8f-a00f6384e4ae disabled=true
            projected_action_0068 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bdd18dad-ac5a-54db-be10-301c12ac84b6 disabled=true
            projected_action_0069 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/3/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fbf865bf-76a5-5a03-9dc4-b9c15d740807 disabled=true
            projected_action_0070 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=2ec0c7b6-b250-5db6-ad9d-0e8407f4624d
        with group(name='ELIF 5（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ff890c01-1319-58eb-ad5b-bc8ba77503a9 disabled=true
            projected_action_0071 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ac9276d2-02ab-5fd0-a18b-17d1ec9ed495 disabled=true
            projected_action_0072 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=79df847d-5631-55c4-a571-5d4ed1c1f89d disabled=true
            projected_action_0073 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8e0079aa-1941-5263-8cf7-376d33e21794 disabled=true
            projected_action_0074 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p51.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/4/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8a306d79-4d9d-50a8-bbf4-2c15bc7da5d7 disabled=true
            projected_action_0075 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=142b523f-0b4f-55e8-8ac2-6d379c4cff45 disabled=true
            projected_action_0076 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p51.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P51"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5a9bd39f-cc7d-55e0-a764-df2efb89521a disabled=true
            projected_action_0077 = robot.move_to_point(
                point_id_or_robot_name='P51',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/4/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d06467ff-1eee-5dd6-8923-a468b904993d disabled=true
            projected_action_0078 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d76268a2-e793-5a89-b914-bf70db695938 disabled=true
            projected_action_0079 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p51.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b57e7821-15a5-5de3-afd0-9e4d5a0be03b disabled=true
            projected_action_0080 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p51.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9faf531d-f235-5c31-9a1b-aaa1a698f46c disabled=true
            projected_action_0081 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b895f337-6e3d-5ab4-94e0-df89bb62e289 disabled=true
            projected_action_0082 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/4/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ef2e44b8-2fae-5b04-ada6-2fe3c8db40f3 disabled=true
            projected_action_0083 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=3b88639f-a94d-5320-87d8-60dc76f366dc
        with group(name='ELIF 6（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b6893f0b-6a60-5b0d-8162-e572764e162a disabled=true
            projected_action_0084 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=31a354a4-a7c0-5467-8b67-a87d03a90984 disabled=true
            projected_action_0085 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c4671d4a-cb66-5c4f-aedb-b7eec6cd9959 disabled=true
            projected_action_0086 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4f9410ed-1d3f-575c-90a2-b4bcf863ed9b disabled=true
            projected_action_0087 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p53.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/5/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f92c4ed8-11f5-5998-aa68-8bec9fd85335 disabled=true
            projected_action_0088 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ab55dd37-c821-5fff-91db-b418f41749cd disabled=true
            projected_action_0089 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p53.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P53"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7198579b-670f-5ca6-b47b-3fe5b86f1a77 disabled=true
            projected_action_0090 = robot.move_to_point(
                point_id_or_robot_name='P53',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/5/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5455975d-3b5d-545d-a44a-018e2657f4b0 disabled=true
            projected_action_0091 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=12e0321e-0b01-5759-91b2-18b3ba9365a9 disabled=true
            projected_action_0092 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p53.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6b84539f-b8a8-59b3-a70b-77ba0fcd5790 disabled=true
            projected_action_0093 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p53.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d2324c11-9fa7-5991-8647-a812289fe035 disabled=true
            projected_action_0094 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=359b7f03-6e28-5d15-a2c4-dd54935fa03a disabled=true
            projected_action_0095 = robot.move_to_point(
                point_id_or_robot_name='review-only',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/5/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bc8e0d95-f438-5968-a242-93d94769e4b5 disabled=true
            projected_action_0096 = robot.require_anchor(
                point_id='review-only',
            )
        # unilab:node_uuid=abe6dfcf-112e-56c6-ac29-b46579f0d52b
        with group(name='ELIF 7（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=af6e7128-6362-57b8-9105-7fcbe879d97c disabled=true
            projected_action_0097 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6a42cfca-43a1-5b53-9ee4-d726bc4da92b disabled=true
            projected_action_0098 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f06914ce-b793-5e71-aaa6-10fd4fee69c3 disabled=true
            projected_action_0099 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a2a7f0e5-73df-5330-a59b-f197940708c1 disabled=true
            projected_action_0100 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p54.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/6/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4c013eb7-65b3-5130-8ad8-b96c29b379ef disabled=true
            projected_action_0101 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4fabc729-052f-5374-815f-034c4ea5461b disabled=true
            projected_action_0102 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p54.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P54"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1c99decb-813f-57db-b7a7-e75332d4c983 disabled=true
            projected_action_0103 = robot.move_to_point(
                point_id_or_robot_name='P54',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/6/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5bfbc2bb-5157-58ab-ad78-a44f273aaf1b disabled=true
            projected_action_0104 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c5797629-7e31-5ca7-abd1-9fb0163941bf disabled=true
            projected_action_0105 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p54.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7151b131-5bed-5f0c-a9ff-976e6bc89838 disabled=true
            projected_action_0106 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p54.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=49e920a4-f5b5-5beb-85ad-293eda4cc655 disabled=true
            projected_action_0107 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e529c0a2-f2b9-539f-b0eb-21a66bcb72d5 disabled=true
            projected_action_0108 = robot.move_to_point(
                point_id_or_robot_name='review-only',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/6/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7c105317-cf0e-5433-8707-1c3748c4711f disabled=true
            projected_action_0109 = robot.require_anchor(
                point_id='review-only',
            )
        # unilab:node_uuid=4f973a8d-bea9-526f-bda0-b7888fcfb31d
        with group(name='ELIF 8（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/7/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b67241b8-b2c7-5990-9a2a-930be8d79804 disabled=true
            projected_action_0110 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/7/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=33393ebf-d34f-5a8a-9475-4c63fd3f8983 disabled=true
            projected_action_0111 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=15b01db5-9ad0-525c-9c4c-4e4fcaf97f12 disabled=true
            projected_action_0112 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5c20dc34-72f8-53ac-a77a-b998090e744a disabled=true
            projected_action_0113 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p55.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/7/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9377baba-b6e7-5478-9f43-e8e00dd9c089 disabled=true
            projected_action_0114 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=56ef5ca5-2169-5b2b-96cb-4181a3eee1b1 disabled=true
            projected_action_0115 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p55.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P55"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f18da1c9-df0c-5bd7-8658-537a043d2240 disabled=true
            projected_action_0116 = robot.move_to_point(
                point_id_or_robot_name='P55',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/7/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5efdc10f-80d7-59ed-a187-dcbb7240bbeb disabled=true
            projected_action_0117 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d7d1e972-e206-56f4-8d18-e2ea94f4ae81 disabled=true
            projected_action_0118 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p55.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=874ad5a0-ddcd-5f3b-a8a2-ecbfc2ef470b disabled=true
            projected_action_0119 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p55.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=610d6c85-a471-5a42-9256-c44707b78c38 disabled=true
            projected_action_0120 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=002b4656-1535-515a-a749-60fec593dc77 disabled=true
            projected_action_0121 = robot.move_to_point(
                point_id_or_robot_name='review-only',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/7/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=65de3965-cab4-5cd7-8167-a77a3d3ae96d disabled=true
            projected_action_0122 = robot.require_anchor(
                point_id='review-only',
            )
        # unilab:node_uuid=9aa23dbd-c33f-5871-8efa-db35eedff57d
        with group(name='ELIF 9（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/8/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b3f5a0c1-b062-5449-9f63-5396a788ca69 disabled=true
            projected_action_0123 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/8/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=399c5d14-0bd2-5749-b0d6-4e634a443dd7 disabled=true
            projected_action_0124 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f0eabe01-6755-555e-b2d0-803a9f0778dc disabled=true
            projected_action_0125 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3ea6cd42-635d-55bc-999c-95bbdfda6a8e disabled=true
            projected_action_0126 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p56.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/8/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a5803a08-3082-50a5-a39e-9b1037221835 disabled=true
            projected_action_0127 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f2d5fcb3-ea28-5d95-8c97-58d5dcbc7d1c disabled=true
            projected_action_0128 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p56.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P56"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c1eb66d9-fe38-529d-a184-03be41630be3 disabled=true
            projected_action_0129 = robot.move_to_point(
                point_id_or_robot_name='P56',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/8/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e1349f8d-5427-57c0-b806-475fe13167d6 disabled=true
            projected_action_0130 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e0eef701-22b4-5f7a-859f-e9e29e807743 disabled=true
            projected_action_0131 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p56.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6bb72b45-8666-5bd2-b594-ec1d777ea287 disabled=true
            projected_action_0132 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p56.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d0260baa-37da-50b0-8861-50df3b6e8512 disabled=true
            projected_action_0133 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c4f2a7e3-be25-516b-ad05-18f8907dd708 disabled=true
            projected_action_0134 = robot.move_to_point(
                point_id_or_robot_name='review-only',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/8/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6328052c-720e-55e9-b7b7-40521212c8cc disabled=true
            projected_action_0135 = robot.require_anchor(
                point_id='review-only',
            )
        # unilab:node_uuid=0f9f06e2-3879-57ae-af9f-3c9d1e646fa0
        with group(name='ELIF 10（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/9/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9b43a6bd-9de2-556c-8dd4-a74533fe6781 disabled=true
            projected_action_0136 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/9/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=84ed4a42-6626-5bfd-877a-e54ca07eef67 disabled=true
            projected_action_0137 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=27b2c40f-26c9-549e-9e13-6e6736e8da6d disabled=true
            projected_action_0138 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=63bf9d2c-5a86-5387-bf3c-cfc1703a5d8d disabled=true
            projected_action_0139 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p57.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/9/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fd4c686b-22bf-5b80-b6ca-86c44fecb960 disabled=true
            projected_action_0140 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2abb4b9e-c4a6-5791-9b55-6c24045c7e96 disabled=true
            projected_action_0141 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p57.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P57"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=620ac75d-04b7-5b99-a49d-37fee92c5bfd disabled=true
            projected_action_0142 = robot.move_to_point(
                point_id_or_robot_name='P57',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/9/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=30bd8562-63ad-5429-9e16-d7068351de7a disabled=true
            projected_action_0143 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b65759b7-b717-56d4-b85f-c4f6ad6915ff disabled=true
            projected_action_0144 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p57.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7edbd598-169f-58b0-ac13-b2baa97e7c48 disabled=true
            projected_action_0145 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p57.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1d025e4e-c177-59e3-a0b0-f46c5eea53ff disabled=true
            projected_action_0146 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b4071881-72fc-5745-bb08-057aed0f8ab8 disabled=true
            projected_action_0147 = robot.move_to_point(
                point_id_or_robot_name='review-only',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/9/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=20fb657c-cfa0-5006-9cab-5d7bc70b2709 disabled=true
            projected_action_0148 = robot.require_anchor(
                point_id='review-only',
            )
        # unilab:node_uuid=e6ff0589-e0c2-54eb-bff8-47bef5291836
        with group(name='ELIF 11（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/10/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=02d8b597-f6dc-56fd-9fd0-9bfc19758bea disabled=true
            projected_action_0149 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/10/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=aba54db4-a7f5-5f98-ae3b-8c0c3ddc6609 disabled=true
            projected_action_0150 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3f002d33-33b2-56b9-be1b-b4b4bf0d03f1 disabled=true
            projected_action_0151 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=89633492-adb5-52a6-bcfe-dd0ebfe0a2de disabled=true
            projected_action_0152 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p58.high',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/10/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9e16a5a8-23ec-5b94-9f61-dadfb8b108ae disabled=true
            projected_action_0153 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=68490b45-0a60-5674-a8fb-51956570e0e0 disabled=true
            projected_action_0154 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p58.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P58"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9d15e902-991b-5efe-b4aa-886f5d481917 disabled=true
            projected_action_0155 = robot.move_to_point(
                point_id_or_robot_name='P58',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/10/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=78d3103c-cf2c-5011-92a4-4eefa3603128 disabled=true
            projected_action_0156 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=43dfbab8-479f-52bd-8dcd-6df12b5c6edd disabled=true
            projected_action_0157 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p58.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=433a95b9-793c-5d06-ba2f-2a42848b6343 disabled=true
            projected_action_0158 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p58.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=391537fb-f7a9-5196-9892-a27fcf774102 disabled=true
            projected_action_0159 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=44f99381-9114-5718-ac62-55034528ea4d disabled=true
            projected_action_0160 = robot.move_to_point(
                point_id_or_robot_name='review-only',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/10/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d2acd442-3b0e-59ab-b2dc-b227c4019f19 disabled=true
            projected_action_0161 = robot.require_anchor(
                point_id='review-only',
            )
        # unilab:node_uuid=bfa243c2-603e-5b56-b997-a193f828a549
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_individual_pick@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=b665c5fb-0a37-5374-8095-5c56f743f0fa disabled=true
            projected_control_0162 = material.review_control_node_v1(
                operation_name='robot_individual_pick',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='cc5774ae8e9be2644c843edf5b39e2745282a7ccdc79ab43f19f14a4f145246d',
            )
