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
    workflow_uuid='55770c2f-675c-53c7-a3b2-29f013aa517f',
    displayname='中转台放单件 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_individual_put_operation_view_v2() -> None:
    # [OPERATION robot_individual_put] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=a93b7b1e-012c-5082-9f41-2477ad4fc8ba disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_individual_put',
        inputs_json='{"enter_anchor":"P1","rack_id":"collector","slot_id":1}',
        expected_sha256='3e575ea822d8e3d7e173b2c72a55e812345dbb2fdec3015f5e06702ef96fdff5',
    )
    # [VERIFY comment] 只读来源校验 robot_individual_put@body/0；本视图中静态 disabled。
    # unilab:node_uuid=89c7af15-8ad1-5e68-a365-748932206b4b disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_individual_put',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='da3d13aa283fa7ee70ee87b04f53a55c8dbc6fffedcabcf1143ea331c6239200',
    )
    # [CONTROL if] 来源 robot_individual_put@body/1；原节点 {"cond":{"binop":"==","left":{"var":"enter_anchor"},"right":{"lit":"P1"}},"op":"if","then":[{"action":"robot.home_ensure","mode":"RUN","op":"call"},{"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}]}
    # unilab:node_uuid=7f9f625d-9149-5f87-bc61-1563cf6fcc8e
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_individual_put@body/1；本视图中静态 disabled。
        # unilab:node_uuid=10491137-1349-5219-8354-c962f0bad1e0 disabled=true
        projected_control_0003 = material.review_control_node_v1(
            operation_name='robot_individual_put',
            node_path='body/1',
            control_kind='if',
            expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
        )
        # unilab:node_uuid=8f03645a-8e56-549f-a82a-a2f7b818ee21
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.home_ensure] 来源 robot_individual_put@body/1/then/0；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
            # unilab:node_uuid=b43fae25-5e62-5b6c-a420-4c1829233716 disabled=true
            projected_action_0004 = robot.home_ensure()
            # [SUBWORKFLOW robot_tool_ensure] 来源 robot_individual_put@body/1/then/1；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
            # unilab:node_uuid=62974c4e-70e0-5440-abee-39947040aebf
            nested_operation_0005 = robot_tool_ensure_operation_view_v2()
        # unilab:node_uuid=e886da31-5c2f-5af8-b20a-14ed699d92f3
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_individual_put@body/1；本视图中静态 disabled。
            # unilab:node_uuid=a12650f3-6014-58de-98a3-41890d9eae2e disabled=true
            projected_control_0006 = material.review_control_node_v1(
                operation_name='robot_individual_put',
                node_path='body/1',
                control_kind='if',
                expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
            )
    # [CONTROL if] 来源 robot_individual_put@body/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"right":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":...
    # unilab:node_uuid=fb8da9a7-92f5-5e9c-86d8-92a447596521
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_individual_put@body/2；本视图中静态 disabled。
        # unilab:node_uuid=0e66ba4c-c385-555d-adaa-d500b6279762 disabled=true
        projected_control_0007 = material.review_control_node_v1(
            operation_name='robot_individual_put',
            node_path='body/2',
            control_kind='if',
            expected_sha256='5eb23b5166747f641204ad7085b5275b765e7c9e9e8a6babe06c0618627d2cda',
        )
        # unilab:node_uuid=d16d0c2b-fc9d-5072-89d5-5cfeae00e88b
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b8a8e312-9c7e-5c55-9f22-d27adbd0441e disabled=true
            projected_action_0008 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_put@body/2/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=edff0b33-6f25-5408-b38c-571d1bb760f8 disabled=true
            projected_action_0009 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9ad61c88-67c0-5a62-814b-cbe65fb6a2ce disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=70aafd13-a017-5c54-8f9f-eb0f2edd4752 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p46.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=86e8305b-e850-5dd9-98f1-c5e86fbf9967 disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p46.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/then/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bf7090dc-6cce-5917-b686-4a07a04bb2e2 disabled=true
            projected_action_0013 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d63f2596-8c8c-5927-baf1-bf95766ae503 disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p46.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=53b5672f-ae1f-5c6a-94a7-046d88eeeb21 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p46.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8f6ea7c4-3923-5115-9f08-35ec37d7065f disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2976c764-effd-5d95-adcb-2fffc7c23854 disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cb87ba1d-e498-5f0b-be80-9b513e900eb8 disabled=true
            projected_action_0018 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=15fc5e34-ebe1-5724-a917-246cb9dea543
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=344dfcef-37b0-5581-9b9d-78f7951a107c disabled=true
            projected_action_0019 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=95430df4-dbce-55ac-a71c-346b4c9d4fa1 disabled=true
            projected_action_0020 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8580a5ff-d679-52aa-9f43-deba704bdb7e disabled=true
            projected_action_0021 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=01c13e90-926f-53d2-8673-242d2742bc5c disabled=true
            projected_action_0022 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p47.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=85ee095c-3773-5f10-b1ff-bdeda3eb72a2 disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p47.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/0/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3456538a-8027-5456-a0ac-6a2c9d3c8cb9 disabled=true
            projected_action_0024 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b4390d3f-22df-551d-8849-9febb08e16e6 disabled=true
            projected_action_0025 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p47.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1354e9a1-c775-5d8d-abfd-4639c1b53c3b disabled=true
            projected_action_0026 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p47.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=783e32a0-edad-5fea-9c2b-b291543a6806 disabled=true
            projected_action_0027 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0c8fe4c9-409d-57fe-9cfd-633259273653 disabled=true
            projected_action_0028 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=665d6c74-da34-522d-956d-83b9509676af disabled=true
            projected_action_0029 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=6b1f0960-6731-5088-8c31-139c1e4fd00e
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a029bc65-26da-5e12-b534-def629711944 disabled=true
            projected_action_0030 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8effedf4-2e9e-566d-984e-8ff9fd2d787d disabled=true
            projected_action_0031 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3adb3dd7-e3ca-5407-8b5c-b4ec979dcf92 disabled=true
            projected_action_0032 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=68a2292f-ff1c-5393-a3eb-44ce41300ae9 disabled=true
            projected_action_0033 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p48.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=71914a84-2461-5352-9894-3ff2e0efb9ec disabled=true
            projected_action_0034 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p48.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/1/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b80e9009-5955-5efe-be52-e1782a3287a7 disabled=true
            projected_action_0035 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2f047623-bf58-510a-ae21-d583f06132b6 disabled=true
            projected_action_0036 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p48.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b3b219b1-ad9b-56ad-9aba-5edc42643ec8 disabled=true
            projected_action_0037 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p48.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b1e32195-3180-5ade-93c5-d900ef01fd5f disabled=true
            projected_action_0038 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d21dd11a-9bfb-5940-b0f6-5bd1b648a2b0 disabled=true
            projected_action_0039 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=28741a7a-3701-5378-bb80-323c97d31e0c disabled=true
            projected_action_0040 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=2fafed09-7423-5d7e-a1d2-5fa4bdf02ba1
        with group(name='ELIF 3（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=66bfbced-c7a7-54cb-8877-fe1dfaf85afe disabled=true
            projected_action_0041 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1f90e76c-48c8-5125-8375-851d5d145400 disabled=true
            projected_action_0042 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4cfc06f0-02d0-5191-abcc-6fca3692777d disabled=true
            projected_action_0043 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b69b295c-6f28-556c-8f5e-d4a368b64599 disabled=true
            projected_action_0044 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p49.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2546a5e7-7703-5284-88c8-4647d18209fa disabled=true
            projected_action_0045 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p49.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/2/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3aa40810-c981-53ce-a714-b968eade0046 disabled=true
            projected_action_0046 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4b3fafd2-4b1e-5caa-94e6-20542cb69b24 disabled=true
            projected_action_0047 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p49.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7c0ac0c3-6f9a-519a-b64b-c69554badc49 disabled=true
            projected_action_0048 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p49.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=201f47c9-9eed-5162-afcb-38fc6b328ed7 disabled=true
            projected_action_0049 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=89f5c293-7788-57dc-8828-4168695f9c61 disabled=true
            projected_action_0050 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/2/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7fb888a9-55c2-5235-8b12-9862cafa0234 disabled=true
            projected_action_0051 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=45833cfc-9b69-5c3e-a47b-c9b717f1b0db
        with group(name='ELIF 4（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e658ba78-63bd-5237-82c8-1cd23a7c8943 disabled=true
            projected_action_0052 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bc46ed36-8760-52f3-b09f-576688571cad disabled=true
            projected_action_0053 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=98bad0de-cf3b-5d48-b90a-c2a42943b93c disabled=true
            projected_action_0054 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=63cb2bf2-001c-54e7-b79e-08cc547dc3d0 disabled=true
            projected_action_0055 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p50.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0b10d3cb-5ec1-5093-8e59-4577a8e1a0a9 disabled=true
            projected_action_0056 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p50.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/3/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=660b0b41-61d5-5139-90cb-2888e4ebdd33 disabled=true
            projected_action_0057 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fec0e509-295b-5825-8e3c-319889dd7793 disabled=true
            projected_action_0058 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p50.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b70a7b28-51e5-5c6c-a112-f6eed0df8f2e disabled=true
            projected_action_0059 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p50.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a4a1b46f-160f-599a-964e-664f00e5615d disabled=true
            projected_action_0060 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=644e3406-d76e-5aa2-9184-12a245b71064 disabled=true
            projected_action_0061 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/3/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=896b8618-082d-5f95-9363-7a0b104fb56b disabled=true
            projected_action_0062 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=a962fc8b-75ad-5b84-813d-e2c91c5dddff
        with group(name='ELIF 5（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=076b81d7-bf15-5170-b313-4dc79c5417b8 disabled=true
            projected_action_0063 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a5080e6f-796a-596d-ae66-9c8872243d1f disabled=true
            projected_action_0064 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=010782b2-378f-5dc8-a9ae-4af36775473c disabled=true
            projected_action_0065 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5e11fe4a-b411-5500-b739-ce7ee5cd5306 disabled=true
            projected_action_0066 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p51.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=143633ab-32bf-5c49-811a-f31829a71466 disabled=true
            projected_action_0067 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p51.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/4/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=650d768b-8ed5-5c88-96c5-f3785cf31fa4 disabled=true
            projected_action_0068 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=619b0736-00b8-5916-8418-1b8d6e82d31e disabled=true
            projected_action_0069 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p51.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=575a4133-0688-5cc4-9837-4e7f473c64d8 disabled=true
            projected_action_0070 = robot.move_to_point(
                point_id_or_robot_name='staging-a.p51.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=39933bf5-c43e-503a-9f74-d9fc6c33d0f7 disabled=true
            projected_action_0071 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5aca8c58-e5e4-5d89-ad0f-5858097fe71e disabled=true
            projected_action_0072 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/4/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=622f8bd8-fa3e-589b-a8a7-f9b89e0ddbcf disabled=true
            projected_action_0073 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=775dfe52-954f-57cc-97cd-42af40ce96cd
        with group(name='ELIF 6（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d38131a3-b3b1-5555-b4c4-8c1dab0e78b8 disabled=true
            projected_action_0074 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=249ed382-1ebe-5ccc-8d1d-38da1d780dd1 disabled=true
            projected_action_0075 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f72e3292-f1f3-5b41-bb4c-ebd240b3a347 disabled=true
            projected_action_0076 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p53.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=15636cfe-8b9d-5683-8bbc-27a209c411c2 disabled=true
            projected_action_0077 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p53.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/5/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0bc11039-adb7-56d8-9084-05e135a3be2e disabled=true
            projected_action_0078 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2b948508-8d89-5517-b807-5533963f54f7 disabled=true
            projected_action_0079 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p53.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e4f91620-3a46-510d-87b5-63480fbdac0e disabled=true
            projected_action_0080 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p53.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=195e4def-5e7d-5790-b18f-fb0addca9e34 disabled=true
            projected_action_0081 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=71790421-7a2a-5f62-967a-4d70ec3c5777 disabled=true
            projected_action_0082 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/5/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5e913662-b5ff-54ca-97fa-836ddef64832 disabled=true
            projected_action_0083 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=5a54b290-5ff9-5617-85e5-a721c002f483
        with group(name='ELIF 7（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a2ab2c17-179c-5969-b5ff-cd86060c1d3f disabled=true
            projected_action_0084 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a5c7db26-7fe4-51fd-9728-7ad8e3c7849c disabled=true
            projected_action_0085 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5267ce3a-b369-52f4-a17f-a31e78c1362d disabled=true
            projected_action_0086 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p54.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4a24cf62-b39b-5aaa-845c-99fbecd90f4d disabled=true
            projected_action_0087 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p54.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/6/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ea4097fa-b6bd-5197-8690-e1d59f8ebab8 disabled=true
            projected_action_0088 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8f22a500-b95b-5d94-bfdf-260d0026693c disabled=true
            projected_action_0089 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p54.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b6f44d7d-a25e-54ca-9f5d-af348807f45a disabled=true
            projected_action_0090 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p54.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=98084b34-e1e8-5c90-a127-311065e6dcc7 disabled=true
            projected_action_0091 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=93f78285-7b30-5a75-8e76-648f0130127a disabled=true
            projected_action_0092 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/6/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ce6d20c1-024f-58be-bc5b-84110e9eef6c disabled=true
            projected_action_0093 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=3f1f3781-94a0-5ccd-b4a4-95db8e256310
        with group(name='ELIF 8（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/7/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=da0c55f7-48f4-54e6-85fc-f30b4e4cdb32 disabled=true
            projected_action_0094 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=17ee5ece-c512-5565-99b4-a13acb8fea64 disabled=true
            projected_action_0095 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d0272eb7-81cd-52e6-af77-e997b27b45b9 disabled=true
            projected_action_0096 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p55.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ea6f2408-5f90-5c5b-875a-49e8de6e80a2 disabled=true
            projected_action_0097 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p55.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/7/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=461c560f-83c5-5b07-836e-86ea0d652cc3 disabled=true
            projected_action_0098 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=49e756f1-7060-5118-9536-57b88c1cf3a9 disabled=true
            projected_action_0099 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p55.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e2c35b2e-05c4-5281-863d-f531046ebd92 disabled=true
            projected_action_0100 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p55.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ec89db71-093c-5179-8161-71259a7bd0d9 disabled=true
            projected_action_0101 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=529d69d2-587b-51a6-b3b8-ce5a5cd2ac42 disabled=true
            projected_action_0102 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/7/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f18c62ec-efc7-58d1-9795-56127bbf6873 disabled=true
            projected_action_0103 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=b491aa92-4e7c-5663-a9b3-150e6327c017
        with group(name='ELIF 9（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/8/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9f693d45-16dd-5acf-bc1e-3461f065c63d disabled=true
            projected_action_0104 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=97a7d1ac-f231-50a1-955b-7996da4417e0 disabled=true
            projected_action_0105 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9e81448c-93ca-544e-9b39-bc48525b0846 disabled=true
            projected_action_0106 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p56.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=483252d5-9d4f-5aaf-a0d1-36842707beab disabled=true
            projected_action_0107 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p56.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/8/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9ed5bd4b-ecb3-51bd-bd4f-f0f376179951 disabled=true
            projected_action_0108 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7c085cc7-8047-566e-85c7-5c610253b481 disabled=true
            projected_action_0109 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p56.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9016ffe2-626d-5a3b-8116-8f451f4c9860 disabled=true
            projected_action_0110 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p56.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=36106692-2f31-5208-ac30-7da7dc56fc2c disabled=true
            projected_action_0111 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=accef36a-f39c-5fe5-bf0e-566ada8e9065 disabled=true
            projected_action_0112 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/8/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=13a81c61-7fff-509b-ad29-2a8de744b975 disabled=true
            projected_action_0113 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=df84f0f0-04f9-521f-a978-3dd87c73a077
        with group(name='ELIF 10（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/9/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7bf78be3-2ae2-5566-9304-273a03ebb2a9 disabled=true
            projected_action_0114 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=584bbf6c-f003-5b2e-9191-095e692c7335 disabled=true
            projected_action_0115 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a3927171-085a-5591-bda7-a64b415003d3 disabled=true
            projected_action_0116 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p57.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1ff6a177-daa8-5530-b420-27411409e3cf disabled=true
            projected_action_0117 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p57.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/9/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0cb53944-7d57-543d-9d20-7d6ac49a1c6f disabled=true
            projected_action_0118 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4765a83f-ca8e-5e78-b8a0-648290de4764 disabled=true
            projected_action_0119 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p57.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bd126c59-b7f4-541c-ab5e-90da6a9afe6e disabled=true
            projected_action_0120 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p57.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0dabde72-f9a8-5a48-8a9b-e25323bc7717 disabled=true
            projected_action_0121 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ff94eddb-cb6e-5910-8246-8cb7317f0450 disabled=true
            projected_action_0122 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/9/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e77b2834-15a6-55a1-b1d1-3a2d941103ae disabled=true
            projected_action_0123 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=7a03a8db-f185-5399-9d1d-b03c7833226e
        with group(name='ELIF 11（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/10/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=be5391b6-a133-5069-9bf6-d4ef3ca195e1 disabled=true
            projected_action_0124 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=183c2cb6-9155-5de0-b97e-0c54fab5224f disabled=true
            projected_action_0125 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fa601299-ab24-5a97-9c05-3892800259cc disabled=true
            projected_action_0126 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p58.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2ce23528-489e-5707-a6c4-8bf0dc918c8e disabled=true
            projected_action_0127 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p58.near',
            )
            # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/10/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8ca8468b-7a6c-5493-b842-7696a3218652 disabled=true
            projected_action_0128 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=19588c05-8197-59e0-9aec-84cf451294c2 disabled=true
            projected_action_0129 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p58.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=333d2ed9-04d4-52d6-8acc-75a51fd0185f disabled=true
            projected_action_0130 = robot.move_to_point(
                point_id_or_robot_name='staging-b.p58.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a7a00bd1-c581-526c-825b-7ecacb36e19f disabled=true
            projected_action_0131 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7defc23b-1b8b-531f-8519-66ccfec13d1e disabled=true
            projected_action_0132 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/10/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d0159f43-8871-589d-96dc-2e9034431954 disabled=true
            projected_action_0133 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=8eb817bf-d416-5b56-bfcf-1ef5edb8315d
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_individual_put@body/2/else/0；本视图中静态 disabled。
            # unilab:node_uuid=cc22b5ed-82e2-546b-863a-90b57f4db1f9 disabled=true
            projected_control_0134 = material.review_control_node_v1(
                operation_name='robot_individual_put',
                node_path='body/2/else/0',
                control_kind='raise',
                expected_sha256='82bf1a17283cb1d76e559d071719bf7252fd0fe0d6f7c00622f156e5cf58486c',
            )
