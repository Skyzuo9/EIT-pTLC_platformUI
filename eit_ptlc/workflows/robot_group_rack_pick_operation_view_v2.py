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
    workflow_uuid='e514466f-150c-5b3f-8b82-e65fa7719369',
    displayname='货架取整组 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_group_rack_pick_operation_view_v2() -> None:
    # [OPERATION robot_group_rack_pick] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=b3149a2e-16ef-5409-9daf-d4b42c1f08ef disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_group_rack_pick',
        inputs_json='{"rack_id":"collector","slot_id":1}',
        expected_sha256='48bbfd275c2ddaec583e7ce202395f2636092ae45c2538eeb87ba110fd3494f0',
    )
    # [VERIFY comment] 只读来源校验 robot_group_rack_pick@body/0；本视图中静态 disabled。
    # unilab:node_uuid=0e30f694-1962-5499-87c0-ee4ae933089f disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_group_rack_pick',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='e39d4d29dad9ddaeb2a8577b39843afb69f527adda4225bc7355c38ab532c9fe',
    )
    # [ACTION robot.home_ensure] 来源 robot_group_rack_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=a562d992-6c5d-5484-92e8-3cf8eb327918 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_group_rack_pick@body/2；原节点 {"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=a25dd881-6396-5fdb-9567-4d72f662670d
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_group_rack_pick@body/3；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"right":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit"...
    # unilab:node_uuid=78aa4f8f-8c7c-534f-a746-6084718dfafc
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_group_rack_pick@body/3；本视图中静态 disabled。
        # unilab:node_uuid=745f1ed7-08f4-5783-86a7-331dc1d3eb70 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_group_rack_pick',
            node_path='body/3',
            control_kind='if',
            expected_sha256='c443e7f9e714f9c17db4a6ab5e3d774e059705b154d55a1816b41ecd71584664',
        )
        # unilab:node_uuid=517ade45-0a8b-5fce-96b7-6da88f2d94e0
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=74eadb47-0530-5a8d-bdfb-8fcc77334c2e disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=78733316-089e-5202-bebd-d452f6d26c79 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=46790664-1bf8-5993-bcb1-8407c28957df disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cbc6d6c9-d815-5235-90f6-abf77174ebb1 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=83d9fa92-5ad7-5d2e-826e-af1732fa193d disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/then/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b273380a-a665-50a0-afb8-29a4730b49ae disabled=true
            projected_action_0011 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a0a48869-c0a2-5c90-aaa4-726722e73a6a disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P25"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=db55787b-cf98-5b6a-b0b1-4ef13878d7f6 disabled=true
            projected_action_0013 = robot.move_to_point(
                point_id_or_robot_name='P25',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d6305a4c-748c-5df2-a903-abaa91c9744e disabled=true
            projected_action_0014 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=92950e83-57e2-5680-95f5-84fd0834c653 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=92894a48-1714-553b-a9b8-cef7db2ebab3 disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0d304b21-c4fb-5153-891f-7fea187a6ae6 disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=faf762c4-16d7-5e16-9a95-e8ef669e42df disabled=true
            projected_action_0018 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2640ebed-4991-540a-a665-2576e2a9eee9 disabled=true
            projected_action_0019 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/then/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b77b49ee-a050-57ab-82f5-cad317820761 disabled=true
            projected_action_0020 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=c4392f79-f3a0-5d26-af74-f9c4e80800fa
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ec4c3ca8-64fe-57d6-9b5b-1fdc429c6f16 disabled=true
            projected_action_0021 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=46c1e209-1c70-500d-981a-2fa705ec0088 disabled=true
            projected_action_0022 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=87ef448b-822f-5d79-91da-58ac3d290fcc disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6c3ab03b-acc2-5d1b-9d28-32b580dc28de disabled=true
            projected_action_0024 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=583d06a1-6e5c-5899-baa1-b09d31214706 disabled=true
            projected_action_0025 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4902e0a6-eb8d-5674-90a7-c61f88d031ef disabled=true
            projected_action_0026 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f54bc1f5-932d-5244-ad80-5214cc98b6ef disabled=true
            projected_action_0027 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P26"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b177731b-1b0f-57e0-b60f-ff7c1dad3f44 disabled=true
            projected_action_0028 = robot.move_to_point(
                point_id_or_robot_name='P26',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f379a15b-2ed8-5281-bf73-7afa64658baf disabled=true
            projected_action_0029 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e7fd7371-d431-524a-b07e-f6ce534bee57 disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f15de6ee-87f5-5208-bec8-5674fa69cb15 disabled=true
            projected_action_0031 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=78080791-4c54-5675-b381-5023526c133e disabled=true
            projected_action_0032 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a9e625f2-aab6-5993-9e04-474efb7fe160 disabled=true
            projected_action_0033 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ed89740e-d59e-5e1d-926b-2fafc942a92e disabled=true
            projected_action_0034 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c18d3d6e-6c03-5239-9da0-b00046284a2b disabled=true
            projected_action_0035 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=4c1ac25d-2c55-5e06-9392-73b27b747065
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c9e8528d-a988-53a2-9c4e-96ef87a698b9 disabled=true
            projected_action_0036 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5caface3-ae9e-595a-8d47-52c409267004 disabled=true
            projected_action_0037 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5a50f9a3-66f5-5302-bf61-9e131d1c7269 disabled=true
            projected_action_0038 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=af9b16f6-2b99-530d-9755-3d2c64ef5303 disabled=true
            projected_action_0039 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a3e2e76f-5a3e-5956-83d8-bc596e16e60d disabled=true
            projected_action_0040 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/1/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0d0a04c1-bb2c-5524-8adc-12282059ac1e disabled=true
            projected_action_0041 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8ea979e1-0962-5371-9d96-8e8ea918267b disabled=true
            projected_action_0042 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P27"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=920d125d-e198-5edd-adb9-9d996b2814df disabled=true
            projected_action_0043 = robot.move_to_point(
                point_id_or_robot_name='P27',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b29b9999-c3e8-562e-aa6d-3afd637e8024 disabled=true
            projected_action_0044 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=df936def-f4c7-5884-83f9-8d36e8c52326 disabled=true
            projected_action_0045 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f5be1c4a-110c-551b-a333-486aefb4b6b8 disabled=true
            projected_action_0046 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f179e630-4904-5e35-9a91-25243cf0ce26 disabled=true
            projected_action_0047 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0ccd9ea3-5041-5c10-93dd-c70e9a816135 disabled=true
            projected_action_0048 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1539c9a2-1f73-5a05-a889-59cdd736b505 disabled=true
            projected_action_0049 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/1/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=54372b33-a466-5575-8d32-23dd92ef38e2 disabled=true
            projected_action_0050 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=c7590ea5-ff53-52fd-8843-f96de9fb0f53
        with group(name='ELIF 3（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bf3749ab-b213-5f28-b073-ebe3c5638c59 disabled=true
            projected_action_0051 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cf25ebb9-745a-5bc1-8a4f-e69bd18edf3a disabled=true
            projected_action_0052 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5619ddc1-e2e4-5edb-ae3e-1281ffbd654d disabled=true
            projected_action_0053 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0163a8c8-3e83-58c1-9e78-1ec36e07721e disabled=true
            projected_action_0054 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1ae2072c-c864-54a9-8328-ee3ab55468b0 disabled=true
            projected_action_0055 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/2/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a56b0921-49a2-5ae4-836f-284083bdb77f disabled=true
            projected_action_0056 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f60f3d0f-e5f6-535c-8a49-1b7da5a64976 disabled=true
            projected_action_0057 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P28"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fd720889-cdd7-5a87-b750-53a3b108b39d disabled=true
            projected_action_0058 = robot.move_to_point(
                point_id_or_robot_name='P28',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/2/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f1f45f23-f2cd-5b61-866e-692345dc3f0d disabled=true
            projected_action_0059 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=05034a3e-060f-58e3-9895-01b49d868ace disabled=true
            projected_action_0060 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=025a57fa-0648-556d-84ff-2ad29e6ed6fd disabled=true
            projected_action_0061 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8fd16117-047d-5646-85a6-d89db82919c3 disabled=true
            projected_action_0062 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ad244120-691f-59e7-92f0-387419282fda disabled=true
            projected_action_0063 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=27d20771-3c22-5441-950a-3aed994c69cf disabled=true
            projected_action_0064 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/2/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6cf73401-e485-583d-bb34-613ab789a7e6 disabled=true
            projected_action_0065 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=9587b6b3-f5a5-5174-96c9-2a732085107b
        with group(name='ELIF 4（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5ab55514-028a-5692-9a2f-790d63c4ce74 disabled=true
            projected_action_0066 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=371b8e2b-7a46-59f5-a5b7-e3c415427da6 disabled=true
            projected_action_0067 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=35689649-2e04-55ed-8290-6cd5ee683d0c disabled=true
            projected_action_0068 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=be95a4a4-078f-53dc-b238-8d901755bea9 disabled=true
            projected_action_0069 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c072dab9-5626-5fae-843d-ecd0d921b5e7 disabled=true
            projected_action_0070 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/3/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8f9a6d2b-4771-5962-a559-7f5c9882fc1e disabled=true
            projected_action_0071 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=190fb5ab-7905-5d31-a679-dc7961643c05 disabled=true
            projected_action_0072 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P29"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f9a71d0e-a1a3-51e7-9013-0c0d46339ff3 disabled=true
            projected_action_0073 = robot.move_to_point(
                point_id_or_robot_name='P29',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/3/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d93a1ef5-c428-5042-9001-2d49fddec3de disabled=true
            projected_action_0074 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cc5156b0-8751-5cd9-9f47-72e48c7f7534 disabled=true
            projected_action_0075 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=38e71e8d-30a7-58a0-bba6-b4b3425a8948 disabled=true
            projected_action_0076 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1a4425f6-1d82-5e24-b2ab-5f68bc23c821 disabled=true
            projected_action_0077 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=17248338-61db-58bc-b297-884b8085d94d disabled=true
            projected_action_0078 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=199933ae-06ee-5db7-a8ae-95e6490c47cb disabled=true
            projected_action_0079 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/3/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=55020692-8bb2-5dd4-9518-d8193b4ddd8c disabled=true
            projected_action_0080 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=f46ca871-288d-54af-84b4-aa82dea04eb7
        with group(name='ELIF 5（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6b8d8d53-ca27-56e2-8e66-89be3ea5ff3a disabled=true
            projected_action_0081 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=704949ce-a6bb-5fd4-a6da-ccba50128311 disabled=true
            projected_action_0082 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1a31deba-6185-5a63-8dcb-1064adf494c8 disabled=true
            projected_action_0083 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2f2bfa58-4747-5c4e-b769-73d55ebb8fc2 disabled=true
            projected_action_0084 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ed59a4b4-ab38-51a6-8b73-16f796817f6b disabled=true
            projected_action_0085 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/4/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e9fa4c8f-6786-5036-b2c2-31543f36746a disabled=true
            projected_action_0086 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=61958d8a-b8f4-585d-914d-79a82723c35c disabled=true
            projected_action_0087 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P30"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=03bb0120-b441-5e59-bc2c-83c5f196488c disabled=true
            projected_action_0088 = robot.move_to_point(
                point_id_or_robot_name='P30',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/4/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8aa44bb8-fb6a-5573-a511-191a64281219 disabled=true
            projected_action_0089 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1b770dfe-bbc3-5621-98ef-c12199a8318c disabled=true
            projected_action_0090 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2e352f70-0685-5c10-91c6-9442e039dd6d disabled=true
            projected_action_0091 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9d8b2bd4-e1ef-517d-add8-519f73798ea4 disabled=true
            projected_action_0092 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=03295e42-e720-58fc-b2e9-9b99ebd532b5 disabled=true
            projected_action_0093 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4afef2d6-4c3b-598b-99c1-6c3c53894539 disabled=true
            projected_action_0094 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/4/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7240aa3e-bb64-5261-a2a4-24e60b8f6c3c disabled=true
            projected_action_0095 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=efa678e1-ee07-5994-957f-e3daca361dc6
        with group(name='ELIF 6（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=345e2cd9-81a2-522f-91a4-748af6928734 disabled=true
            projected_action_0096 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c0ba5d15-4d8d-5c4d-9b42-446ffccb0728 disabled=true
            projected_action_0097 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=992d044a-74f2-56a0-8b25-ed614ff3aae8 disabled=true
            projected_action_0098 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0c542085-9aff-5a56-8848-197a82e04ec9 disabled=true
            projected_action_0099 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b1503bfd-e0ad-5f24-a0cc-68d22ff4af55 disabled=true
            projected_action_0100 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/5/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c02a4131-3605-5fe6-acea-d184a29756f8 disabled=true
            projected_action_0101 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1df9b95f-8f4e-5fe2-8e3c-df0f325379f8 disabled=true
            projected_action_0102 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P31"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=033b4155-8db9-5846-8ecc-a657f4480ba7 disabled=true
            projected_action_0103 = robot.move_to_point(
                point_id_or_robot_name='P31',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/5/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8344a801-d88f-5632-941c-ee3a91593e79 disabled=true
            projected_action_0104 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8fc9c50d-33bc-58f2-aefe-f3b0461dcaab disabled=true
            projected_action_0105 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0c02f6c3-e7af-5e47-81ac-c1353d8add65 disabled=true
            projected_action_0106 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=207f68dd-b230-58db-badd-f3a5a7241243 disabled=true
            projected_action_0107 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=59dce415-dde9-53b8-9e95-5ffbb453f68a disabled=true
            projected_action_0108 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f639cd15-23da-5a9d-8188-6d67a4092115 disabled=true
            projected_action_0109 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/5/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5119445d-3d00-5aa1-9a1b-3bb6e25ef5b2 disabled=true
            projected_action_0110 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=2598a31a-733d-5ad4-b486-27654708157f
        with group(name='ELIF 7（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=31ce44a0-dd3a-5643-bbd7-46ece9d47377 disabled=true
            projected_action_0111 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ac578dc3-9da2-5462-9405-9970de634932 disabled=true
            projected_action_0112 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2bf5cd98-50e2-59a0-ab3d-bb7d1e1935b0 disabled=true
            projected_action_0113 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3662307b-2ec4-50a2-a762-a53521606242 disabled=true
            projected_action_0114 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f792d373-65bb-522a-8679-9a62d171f9d1 disabled=true
            projected_action_0115 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/6/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8a577af7-aa1e-558d-a201-569dc115230e disabled=true
            projected_action_0116 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e6e643a2-9d99-5e62-8843-4d3a8a417413 disabled=true
            projected_action_0117 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P32"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=84c9ae16-c718-5cda-af97-3cc618a9a8f6 disabled=true
            projected_action_0118 = robot.move_to_point(
                point_id_or_robot_name='P32',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/6/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ed2f0344-e568-5a2d-8fe6-2f27a2179f7d disabled=true
            projected_action_0119 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c498ac9b-623d-5109-aaa4-f05a71681c01 disabled=true
            projected_action_0120 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=75234b2f-0106-54d6-b805-2cb26bae223a disabled=true
            projected_action_0121 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1cc0dedb-7085-58fe-8edb-dc468f3e145b disabled=true
            projected_action_0122 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=eeb310fb-82d5-5b77-a71a-982c59d5ba1c disabled=true
            projected_action_0123 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bf2d34d5-0eff-504d-9dca-7be713bef596 disabled=true
            projected_action_0124 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/6/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=34cd9d1f-bc35-569f-9cf8-25357d742415 disabled=true
            projected_action_0125 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=22310837-7527-5c99-b1cb-ed1ae63b9406
        with group(name='ELIF 8（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/7/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bd64a105-1e73-5252-9214-2700d6c1b5e2 disabled=true
            projected_action_0126 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/7/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=38fb5866-8ce8-5276-a566-40fa312302cb disabled=true
            projected_action_0127 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3164c994-ead8-5492-86ba-a342048d03b1 disabled=true
            projected_action_0128 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4e80b0d9-b749-5ea5-bf2e-72f8cfb9ee5b disabled=true
            projected_action_0129 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bfbeb3a3-3c03-5d50-9383-4bf3fd86e0bf disabled=true
            projected_action_0130 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/7/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=854d6781-5000-5217-908c-50b004e0764e disabled=true
            projected_action_0131 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d9f37891-5f3b-5bf4-9267-6b4d0c53a492 disabled=true
            projected_action_0132 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P33"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=92d4a430-b75d-59d1-b9f6-b2add096d50d disabled=true
            projected_action_0133 = robot.move_to_point(
                point_id_or_robot_name='P33',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/7/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f8eef0ab-a898-51ea-a4ed-b2090f3a3c19 disabled=true
            projected_action_0134 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=26a26abf-1e2b-504d-8029-0c4c3493a454 disabled=true
            projected_action_0135 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=44cdad02-c2d0-5161-b2dc-dbba01af2c07 disabled=true
            projected_action_0136 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cb573cdb-6dfa-5a5f-9630-8bbe9d7d7c4f disabled=true
            projected_action_0137 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d246f676-ddb8-514f-8dfc-6521f402cac1 disabled=true
            projected_action_0138 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a8d641b6-2bc3-565d-bbeb-88304a0b484a disabled=true
            projected_action_0139 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/7/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7ffbfa5d-0f0f-5b7a-8b08-e0b5b55cbf07 disabled=true
            projected_action_0140 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=66264da6-3a45-5bd8-affc-bd52a35249a7
        with group(name='ELIF 9（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/8/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7dbba8da-8eed-5ae2-8559-90f208b27d93 disabled=true
            projected_action_0141 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/8/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e450f167-5f1a-5114-b1b2-67ea1359be4f disabled=true
            projected_action_0142 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=98a6d067-cde9-5536-97e4-0bea529d9eb8 disabled=true
            projected_action_0143 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1a9b960f-b1bb-5e30-87f8-61e28b1f39fa disabled=true
            projected_action_0144 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e3dc9769-ac96-54c1-b092-45ebb598be9c disabled=true
            projected_action_0145 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/8/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=466cb673-9af8-510d-9272-a411d9056a65 disabled=true
            projected_action_0146 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=295698f4-a939-5847-9f6f-5390bd15191c disabled=true
            projected_action_0147 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P34"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4f16a87e-0042-5fe5-816a-63f7d183f332 disabled=true
            projected_action_0148 = robot.move_to_point(
                point_id_or_robot_name='P34',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/8/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fb4a9497-3a03-5599-aa1c-3de829b00136 disabled=true
            projected_action_0149 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=70286ca6-02d4-5fbb-86d7-f56a341ed2af disabled=true
            projected_action_0150 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ffefd988-4550-5f58-8af8-6d07e4c063cf disabled=true
            projected_action_0151 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0d7dd65c-5643-5909-a8e2-c474d44d4469 disabled=true
            projected_action_0152 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2e9c3618-8d3e-564d-bee3-0b1cee70c788 disabled=true
            projected_action_0153 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cd4fc8c9-61c6-53fe-89b9-2b1319c4d795 disabled=true
            projected_action_0154 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/8/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=959a9fc9-309a-59fa-a456-98f4bb8ea2b2 disabled=true
            projected_action_0155 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=c32b972d-acc7-5899-9254-549d5803b45e
        with group(name='ELIF 10（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/9/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=88974ff3-d01a-51cd-8075-20dfd74e28da disabled=true
            projected_action_0156 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/9/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=70cb8949-2ae7-55b6-8c12-889e56256e61 disabled=true
            projected_action_0157 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7440bdcb-5a38-5d5a-bf27-a8ffc870b8ad disabled=true
            projected_action_0158 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f37e8af7-e6f2-530a-9199-eba0248ad716 disabled=true
            projected_action_0159 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7494e56e-0751-544f-a1ae-d64e368d6a72 disabled=true
            projected_action_0160 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/9/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=72c45d20-af9c-53b7-b72a-10fdb5eb0356 disabled=true
            projected_action_0161 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d522564d-a662-581d-b9e4-e4eec7ee074f disabled=true
            projected_action_0162 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P35"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f649a518-f5bc-5539-9242-19f098d16f77 disabled=true
            projected_action_0163 = robot.move_to_point(
                point_id_or_robot_name='P35',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/9/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a342be9b-1d8d-5c29-8361-4db0466fb810 disabled=true
            projected_action_0164 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5fdeacec-bc28-516f-9b39-4a05040c7811 disabled=true
            projected_action_0165 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4f1f14e4-6dbf-5395-9dac-c2eb74738cd1 disabled=true
            projected_action_0166 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7634db77-1301-5ddc-b724-1c7034404ef1 disabled=true
            projected_action_0167 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=09d085e2-437a-5e42-94ea-bfb0f727e55e disabled=true
            projected_action_0168 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5d9d28dd-06c7-5ee7-b250-fa0550b106ad disabled=true
            projected_action_0169 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/9/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=482acd18-6da3-577e-884c-0ad825b3e015 disabled=true
            projected_action_0170 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=e6c89636-0fea-51b6-ab23-edd557dfc60a
        with group(name='ELIF 11（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/10/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1132e0d7-6127-5a07-b0ed-04a5bf796e48 disabled=true
            projected_action_0171 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/10/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0ca18dab-65b1-5df8-b5c8-872b40c52e24 disabled=true
            projected_action_0172 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b0fa9036-750a-51d2-ae28-51f1b3d83eb4 disabled=true
            projected_action_0173 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b6c1d1b3-604f-560f-a09a-e84984acba9f disabled=true
            projected_action_0174 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=094c99fe-3387-5df0-b039-7679d16e29ac disabled=true
            projected_action_0175 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/10/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=caa0c9e7-5b9e-542a-bfee-8fab800dadd7 disabled=true
            projected_action_0176 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d5bc0cc7-58f9-5b89-9222-1f8f8e5c3868 disabled=true
            projected_action_0177 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P36"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8cc63a4e-575d-5893-967f-84edd03d29fb disabled=true
            projected_action_0178 = robot.move_to_point(
                point_id_or_robot_name='P36',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/10/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ace5628a-3eb0-5d3c-877f-d9ab3a7c77e6 disabled=true
            projected_action_0179 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7c1e3348-8a68-58b6-8d79-ca19768d75d7 disabled=true
            projected_action_0180 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=62ae6cca-b2c8-58f6-bcd0-96be15536b10 disabled=true
            projected_action_0181 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e9d6610d-7f7b-516f-b43c-2407d01a0bc7 disabled=true
            projected_action_0182 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c5aab496-709d-58ed-8365-3b4f083495b9 disabled=true
            projected_action_0183 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=48a99919-7b71-51eb-846a-1628d2bb31e4 disabled=true
            projected_action_0184 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/10/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f4cca95d-486e-55bd-8dad-bd2c82fd0e55 disabled=true
            projected_action_0185 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=9e551cab-5562-5277-a1eb-d5981d0a5546
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_group_rack_pick@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=0fcae3d0-d5a4-5cb5-917a-08546172fce4 disabled=true
            projected_control_0186 = material.review_control_node_v1(
                operation_name='robot_group_rack_pick',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='dbb045f0d18c415e9c183f6e6bc9acd38d3aa443e39ca1d6237b8ade965e61f8',
            )
