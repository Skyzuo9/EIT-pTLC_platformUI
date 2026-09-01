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
    workflow_uuid='100e83b2-4ab9-5cf4-bc74-3c53b5d024bf',
    displayname='中转台取整组 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_group_staging_pick_operation_view_v2() -> None:
    # [OPERATION robot_group_staging_pick] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=734923c9-c86f-57cb-9558-c4b47073b1de disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_group_staging_pick',
        inputs_json='{"rack_id":"collector"}',
        expected_sha256='57785dfd62df327b1c231070f57f1fd3b8859526ffc99579c77af2f199df0e67',
    )
    # [VERIFY comment] 只读来源校验 robot_group_staging_pick@body/0；本视图中静态 disabled。
    # unilab:node_uuid=109e6c4a-72df-543c-9e35-c87e98bff15b disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_group_staging_pick',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='e39d4d29dad9ddaeb2a8577b39843afb69f527adda4225bc7355c38ab532c9fe',
    )
    # [ACTION robot.home_ensure] 来源 robot_group_staging_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=f3b27057-3fd4-5a1b-9c95-5276827eec5e disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_group_staging_pick@body/2；原节点 {"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=c6f35a07-8407-55b4-97e7-29603ae7593b
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_group_staging_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position...
    # unilab:node_uuid=5074a0d7-7f65-53ca-a9a3-3f55aa9d5183
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_group_staging_pick@body/3；本视图中静态 disabled。
        # unilab:node_uuid=c8dc87af-b3e0-52ce-840d-03ad7e2437c6 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_group_staging_pick',
            node_path='body/3',
            control_kind='if',
            expected_sha256='ad662023165e753aaeebc11cbd97f36159d4c68805a11312c8cd86a5cf1fe4e8',
        )
        # unilab:node_uuid=2bdf2cd2-f3ab-5e9c-9468-15e40735b4e1
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_staging_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=77c74f66-c336-5a69-a602-9c418ef6559f disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_staging_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6bde2601-5426-5a1c-8740-5ce1851d0d0a disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a37540bf-72af-508b-831e-cdab095b3963 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P4',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9fc8fa88-0216-54b0-85af-5cb3119c958d disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-pick.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=108829cf-72a4-53c4-aef5-a3ff6a34ed4e disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-pick.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_staging_pick@body/3/then/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=835ccde0-b200-51d4-aea7-2fffe7b87da9 disabled=true
            projected_action_0011 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=743d4c88-0004-5b67-bba2-113db3cd5e07 disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-pick.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P39"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=08f0f225-9735-5b88-b465-d1fd5c5fcfd9 disabled=true
            projected_action_0013 = robot.move_to_point(
                point_id_or_robot_name='P39',
            )
            # [ACTION robot.tool_action] 来源 robot_group_staging_pick@body/3/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1d6f2128-f54f-5fa4-af7d-f68332e49d5c disabled=true
            projected_action_0014 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4f1324cf-b15c-53d4-bf8d-006c00c812b1 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-pick.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ca07e9a4-8604-5b9a-8763-83e9c00d2802 disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-pick.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cfe04d97-1c18-5434-9193-c65923064646 disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-pick.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7bfa000c-d3ff-53f8-afe6-25ede7e9e707 disabled=true
            projected_action_0018 = robot.move_to_point(
                point_id_or_robot_name='P4',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=80edcd3b-6d0a-50cc-b6c8-9f282b4fe3bd disabled=true
            projected_action_0019 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_staging_pick@body/3/then/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2f472275-4ac9-534c-ba30-6e2863a0c42e disabled=true
            projected_action_0020 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=c775f0f7-fb3f-5bc3-8a7c-fad6e8b8ccf1
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_staging_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a2451ef4-b15f-54b3-8a22-4c71a70a4802 disabled=true
            projected_action_0021 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_staging_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5cc1a2d2-e283-5031-8d47-52d0f0aa1cc2 disabled=true
            projected_action_0022 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=85cd0915-26a8-5257-bb7c-437038f684da disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=370a68a7-d313-5dae-94cf-822583edc3bb disabled=true
            projected_action_0024 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-pick.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4947c1f4-36b1-5270-9ccf-5b8f5d473654 disabled=true
            projected_action_0025 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-pick.mid',
            )
            # [ACTION robot.tool_action] 来源 robot_group_staging_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1c4dbf08-6679-5c89-96fa-82143d5205d7 disabled=true
            projected_action_0026 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=68f3430c-195b-568b-875d-6ebad22d5f64 disabled=true
            projected_action_0027 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-pick.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P40"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f43386b2-39ee-54e8-bb4d-4edfdef4c906 disabled=true
            projected_action_0028 = robot.move_to_point(
                point_id_or_robot_name='P40',
            )
            # [ACTION robot.tool_action] 来源 robot_group_staging_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=87a4f7d7-f9ab-5764-87ce-dcb08a298728 disabled=true
            projected_action_0029 = robot.tool_action(
                action='gripper-close',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=67be7475-0f92-5ffe-bcef-64f3fb3c04d5 disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-pick.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9da29c2d-110f-5d29-9b98-428fd836c6da disabled=true
            projected_action_0031 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-pick.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6921dbd5-9542-5c5e-8fa7-04b5a5b8a96e disabled=true
            projected_action_0032 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-pick.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=49393a51-6dff-5199-98ef-35d79d8af905 disabled=true
            projected_action_0033 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=72ff26d2-5ae9-58ae-9b2a-9c2aecd3020e disabled=true
            projected_action_0034 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_staging_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f2d93469-3471-5c13-b2e3-f97039c7a11f disabled=true
            projected_action_0035 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=7de4e443-3d04-529d-948a-bf3f2bb72910
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_group_staging_pick@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=6efc104b-29f0-5a29-8548-36104168379e disabled=true
            projected_control_0036 = material.review_control_node_v1(
                operation_name='robot_group_staging_pick',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='d82391d1c24fbf25fc71751808512bb67a8dabf3a6c3c5860d7dad3e45bb08f1',
            )
