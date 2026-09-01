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
    workflow_uuid='44107a19-7d9b-5316-9cb6-80797f136026',
    displayname='收集工位取瓶 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_collect_bottle_pick_operation_view_v2() -> None:
    # [OPERATION robot_collect_bottle_pick] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=83e8d587-66eb-5407-a29b-0db54e14b429 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_collect_bottle_pick',
        inputs_json='{"station_id":"default"}',
        expected_sha256='1968f3524a4082f7beac962f9a519c05d22ecebf05ca8c6b78dcf59e62250140',
    )
    # [VERIFY comment] 只读来源校验 robot_collect_bottle_pick@body/0；本视图中静态 disabled。
    # unilab:node_uuid=4eeabb2c-924a-5734-bc8d-d233d4e8ad16 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_collect_bottle_pick',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
    )
    # [ACTION robot.home_ensure] 来源 robot_collect_bottle_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=bbd85721-035c-5102-99c0-e9333e44e328 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_collect_bottle_pick@body/2；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=10b8367a-bef5-5774-b3bb-051422d9d14b
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_collect_bottle_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.bottle.pick: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"li...
    # unilab:node_uuid=23b6b9c5-20b7-5c40-91ff-0c398b448808
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_collect_bottle_pick@body/3；本视图中静态 disabled。
        # unilab:node_uuid=d70c49ef-b657-5602-8f62-f87f6e5d6847 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_collect_bottle_pick',
            node_path='body/3',
            control_kind='if',
            expected_sha256='259d06699346e86121785c6f63a8fa923bf9cebbaa97c79997da521f7f5fc6c3',
        )
        # unilab:node_uuid=209eb243-9758-5e60-862d-eb49208e5dad
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collect_bottle_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e41978fb-2758-5c21-bed2-5ff5b618b3cf disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_collect_bottle_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6f3c062b-fecf-58bc-8fc3-e64e91cd787e disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=07c6729c-6070-5f38-a8d9-a92a4d885364 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P70',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-pick.far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=baa2777a-90bb-5bc1-8706-63bcd1e3d722 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='collect-bottle-pick.far',
            )
            # [ACTION robot.tool_action] 来源 robot_collect_bottle_pick@body/3/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=45b989ef-3614-5255-a880-9cff21e9b26f disabled=true
            projected_action_0010 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2d517d33-0134-531f-83af-a9ea02bcfd46 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='collect-bottle-pick.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P72"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=85cb8b26-a256-5031-b900-facd0229d9bd disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='P72',
            )
            # [ACTION robot.tool_action] 来源 robot_collect_bottle_pick@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4665b971-6eb2-5f3e-934c-ab7fa5b24c84 disabled=true
            projected_action_0013 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=edb2540e-44f6-5314-9a97-7af7a69e35a1 disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='collect-bottle-pick.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=abc054c1-858a-5ba6-99a1-bde980130dcf disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='collect-bottle-pick.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=711fd41a-24df-5f8a-853f-a99d7300901a disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='P70',
            )
            # [ACTION robot.require_anchor] 来源 robot_collect_bottle_pick@body/3/then/11；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P70"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=94a0c5b8-e4b5-5a7f-962d-ad91dcb80bd1 disabled=true
            projected_action_0017 = robot.require_anchor(
                point_id='P70',
            )
        # unilab:node_uuid=c04a1993-56d3-5b83-a649-1f8111855235
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_collect_bottle_pick@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=01d0b7f7-4962-5b75-ad7e-f0bfa72ada19 disabled=true
            projected_control_0018 = material.review_control_node_v1(
                operation_name='robot_collect_bottle_pick',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='ccec1bdef11cc2d1cb1ffd1a08331b9c9fea90d80bdbd2f42fa2b79a4c4548aa',
            )
