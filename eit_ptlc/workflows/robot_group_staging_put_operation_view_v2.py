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
    workflow_uuid='08a62565-1d8a-519f-a91c-1cbf774ee08f',
    displayname='中转台放整组 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_group_staging_put_operation_view_v2() -> None:
    # [OPERATION robot_group_staging_put] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=f9a36bdf-07ba-5ac3-89ee-486372ffdedd disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_group_staging_put',
        inputs_json='{"rack_id":"collector"}',
        expected_sha256='f47767c9f09facf5cb03fc8bffeaa6eec3b8f4574f61a41eb1274fbdaa63543f',
    )
    # [VERIFY comment] 只读来源校验 robot_group_staging_put@body/0；本视图中静态 disabled。
    # unilab:node_uuid=a17029d1-cb93-5ee7-bedb-d3e8e196c649 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_group_staging_put',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='e39d4d29dad9ddaeb2a8577b39843afb69f527adda4225bc7355c38ab532c9fe',
    )
    # [ACTION robot.home_ensure] 来源 robot_group_staging_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=022154cb-7a7c-51a8-a3f6-d3763f3a2f87 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_group_staging_put@body/2；原节点 {"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=ff7ba705-2569-566a-9e28-c2e7eb152eaa
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_group_staging_put@body/3；原节点 {"cond":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position"...
    # unilab:node_uuid=0ad80358-15e7-55c5-b820-477ef2e68e03
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_group_staging_put@body/3；本视图中静态 disabled。
        # unilab:node_uuid=2d27d487-187b-5d42-b1d9-a2d53ee85a14 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_group_staging_put',
            node_path='body/3',
            control_kind='if',
            expected_sha256='67ef0fd04b8ae6b9101f677df3a492a0229bc0ec9d4e7853e580b89612db7eb5',
        )
        # unilab:node_uuid=b87c7d9d-5689-5430-8e18-6d75b1c3ebe2
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_staging_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a455c6b2-7bca-5169-b73b-939a68087756 disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_staging_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d2cceffd-0acf-54d9-9bf3-e368d4c659cb disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c100abe6-50ea-50f5-9788-644f7645e98a disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P4',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=993ac86c-2eb3-5fda-ae2b-2b1ff83d033c disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a7624351-884f-5713-a37e-1d13e2668822 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-put.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c64cabb5-7279-571c-89fa-74742b7f1600 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-put.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P37"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cc8b0f6d-81ac-5b43-a377-f3cc6299c42e disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='P37',
            )
            # [ACTION robot.tool_action] 来源 robot_group_staging_put@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=915b506c-081b-53c2-a5e5-fed76f9ed82e disabled=true
            projected_action_0013 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=24b5bc05-f134-5f84-b753-06d0670efcab disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-put.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=79320460-e379-5498-a4d3-92936ed048b3 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-put.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bc40b7f4-b979-5d90-9bbb-c53786b46ed1 disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='collector-group-staging-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1b661c35-1bca-5562-bb31-98fc75c47069 disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='P4',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0c0fccaf-7e5c-5665-9dd8-b8b81477cbc4 disabled=true
            projected_action_0018 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_staging_put@body/3/then/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c2b24a23-622e-51a5-81d5-6320fb4be12e disabled=true
            projected_action_0019 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=95005008-d77c-5e4f-b396-ce0d542ccf0e
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_staging_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=999555ec-1fe6-5fdc-a93e-5383f3a69eb5 disabled=true
            projected_action_0020 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_staging_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ce8cb263-d42c-5227-a954-bdc252ec99bb disabled=true
            projected_action_0021 = rail.ensure(
                Rail_Target_Position=3,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=92440ab3-2afe-5b1b-9924-eb88b3e1d9c9 disabled=true
            projected_action_0022 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=372864b7-2b6a-5bc1-bf51-0da758276098 disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c97b44c4-cd4e-5e07-bda4-66e7a0c469b1 disabled=true
            projected_action_0024 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-put.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ad440c8d-f4a7-5643-bde7-5684fb8244e7 disabled=true
            projected_action_0025 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-put.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P38"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5c13a1e6-661d-5382-88d3-b14c944ec6c5 disabled=true
            projected_action_0026 = robot.move_to_point(
                point_id_or_robot_name='P38',
            )
            # [ACTION robot.tool_action] 来源 robot_group_staging_put@body/3/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=068c0cb1-3d02-5ff0-a97d-bbe30db99645 disabled=true
            projected_action_0027 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7c4fb081-e784-5a71-80d4-c35d9184f98f disabled=true
            projected_action_0028 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-put.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=18c0269a-5bf6-5be3-89eb-72e1d0dcbfbe disabled=true
            projected_action_0029 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-put.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=87917d4f-18a5-5703-ad1a-c2a21d6c7210 disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='bottle-group-staging-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0c876b56-dc4a-533e-a4e4-df3d8cd0bf63 disabled=true
            projected_action_0031 = robot.move_to_point(
                point_id_or_robot_name='P52',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a984401d-2e28-5ff5-a3b0-f57773467cf4 disabled=true
            projected_action_0032 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_staging_put@body/3/elifs/0/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4b631641-a372-5d18-a9a3-8d58626efa12 disabled=true
            projected_action_0033 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=5bb061da-8974-5e91-94fd-2dfede1846db
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_group_staging_put@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=8be44442-5a99-5036-b09c-c7a78ab51073 disabled=true
            projected_control_0034 = material.review_control_node_v1(
                operation_name='robot_group_staging_put',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='a0f011e9b9ded2a6fc9b5c25d962930118a92f39b694b1ba2ff22d063b5a5d1d',
            )
