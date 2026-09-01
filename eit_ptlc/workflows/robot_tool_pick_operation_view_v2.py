from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


material: MaterialProxy = device('material')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='777b5f31-0c92-5f15-83ea-2aeaa22d62a4',
    displayname='装刀 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_tool_pick_operation_view_v2() -> None:
    # [OPERATION robot_tool_pick] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=4eb98de9-4d5f-576f-af17-a20d1f995df0 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_tool_pick',
        inputs_json='{"tool_id":1}',
        expected_sha256='aed374d7c8a37f6e518d339f294af4761b40ea4320aa7a9b3a37aef438838884',
    )
    # [CONTROL if] 来源 robot_tool_pick@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"},{"action":"robot.move...
    # unilab:node_uuid=3ae5b7af-33ad-5a87-b8d4-07fa3eb637b1
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_tool_pick@body/0；本视图中静态 disabled。
        # unilab:node_uuid=889e8c80-3b7e-54df-88e4-2236f93e9c5e disabled=true
        projected_control_0002 = material.review_control_node_v1(
            operation_name='robot_tool_pick',
            node_path='body/0',
            control_kind='if',
            expected_sha256='47a5b48eb2b065101041caadd225ef492b21028bb19039ac3a19991997da1895',
        )
        # unilab:node_uuid=08688865-9085-5318-bc02-8ed43fb8c8de
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=292e0692-8fa0-5841-98dc-6ac8fa4c1aca disabled=true
            projected_action_0003 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e2bc10d5-1153-566a-abbd-59fe827b9f26 disabled=true
            projected_action_0004 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f3857e9c-02c6-5cbe-ab54-b6b8e7e56c3a disabled=true
            projected_action_0005 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.target',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=14f2c8f3-57ab-58e8-a0bd-2b4bc165e4f8 disabled=true
            projected_action_0006 = robot.tool_action(
                action='quick-change-lock',
            )
            # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/then/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":1}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5e64ab19-bc0b-57f0-83b1-3a22c7c26e72 disabled=true
            projected_action_0007 = robot.set_mounted_tool(
                tool_id='0',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4b3e6923-775d-5386-9a25-a2ff06794a6d disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=837e6e4c-9591-52fe-b180-8885c8d2a2d9 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=27e5edd5-8b0b-57c5-9db5-e8511436b6d1 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.ready',
            )
            # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7b6e78ba-632e-538c-93ce-666df89aa603 disabled=true
            projected_action_0011 = robot.dwell(
                duration_ms=500,
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b61a55b3-93ec-5150-860c-295e4f676d93 disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='robot-main.home',
            )
            # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=09d00532-8267-5755-ad06-9ccfb12db0c1 disabled=true
            projected_action_0013 = robot.require_anchor(
                point_id='robot-main.home',
            )
        # unilab:node_uuid=de149b40-26c0-54c1-841b-3593d7daf474
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e7763e6d-87f2-5bcd-9b49-993114602d8c disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=623af036-3361-5ab5-9559-1e409d4e9678 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ac8398ba-c678-5578-86d0-5c18b7baaa15 disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.target',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=30d0dfbd-a809-5be8-abe7-d84cfe5c578d disabled=true
            projected_action_0017 = robot.tool_action(
                action='quick-change-lock',
            )
            # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/0/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7d3bf0a9-bc4b-5528-b62b-a0171adbb32e disabled=true
            projected_action_0018 = robot.set_mounted_tool(
                tool_id='0',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=956452db-74df-56a5-bab9-03046128d98e disabled=true
            projected_action_0019 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=475f0919-70da-5efe-878a-ce8c90f8eb22 disabled=true
            projected_action_0020 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=efb34f86-c647-5a0d-ae15-fbbe21744d11 disabled=true
            projected_action_0021 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.ready',
            )
            # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/0/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b5c86bea-0786-5673-9030-1cb22c36774b disabled=true
            projected_action_0022 = robot.dwell(
                duration_ms=500,
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c4e85466-dfd3-524e-b77b-67e8f0d6f7d3 disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='robot-main.home',
            )
            # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9443ea1e-8c54-5b90-a46e-87fa8d35febb disabled=true
            projected_action_0024 = robot.require_anchor(
                point_id='robot-main.home',
            )
        # unilab:node_uuid=4652df09-8bad-5e87-b1e5-4237a879803d
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2e526167-c83d-5087-92ea-10eaec3ccf4d disabled=true
            projected_action_0025 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=09c8cc18-0ee0-5ca5-a7d2-19d7c1057c7b disabled=true
            projected_action_0026 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=02b0b7b8-3fdf-56a4-898c-aabe8ef9511f disabled=true
            projected_action_0027 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.target',
            )
            # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/1/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f0559288-d56e-5703-a9e8-ef039a7c7e39 disabled=true
            projected_action_0028 = robot.tool_action(
                action='quick-change-lock',
            )
            # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/1/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4e89734b-2e28-5d5b-b35b-cf4843adf963 disabled=true
            projected_action_0029 = robot.set_mounted_tool(
                tool_id='0',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=88815ac3-1287-5adf-aa3b-4ecb0000b2c2 disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=617b439e-8d5f-5797-98f9-dba2c6f94ecf disabled=true
            projected_action_0031 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dc630111-e39b-5c2b-8d7f-f1a5f82c04cd disabled=true
            projected_action_0032 = robot.move_to_point(
                point_id_or_robot_name='robot-main.tool-change.ready',
            )
            # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/1/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=df8354fc-e3a8-5199-b588-e8c1f27599e4 disabled=true
            projected_action_0033 = robot.dwell(
                duration_ms=500,
            )
            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d7027547-60b9-5375-ae0b-e31939e85be9 disabled=true
            projected_action_0034 = robot.move_to_point(
                point_id_or_robot_name='robot-main.home',
            )
            # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1f3ebd14-b7b3-5c11-90c1-1b5ca1e20451 disabled=true
            projected_action_0035 = robot.require_anchor(
                point_id='robot-main.home',
            )
        # unilab:node_uuid=8d01b4f8-20a5-539e-95e4-a8e0d15a4690
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_tool_pick@body/0/else/0；本视图中静态 disabled。
            # unilab:node_uuid=6bf7097e-7db5-5243-815c-7d0da496bf7e disabled=true
            projected_control_0036 = material.review_control_node_v1(
                operation_name='robot_tool_pick',
                node_path='body/0/else/0',
                control_kind='raise',
                expected_sha256='70c2a7e291023e9375102dc659639ba2604e87ffa8a3a94cca033c80b83c21e8',
            )
