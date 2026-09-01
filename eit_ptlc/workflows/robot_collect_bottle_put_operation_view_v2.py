from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.robot import RobotProxy
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)


material: MaterialProxy = device('material')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='d278f43b-0039-505a-8d96-1c292da73ec3',
    displayname='收集工位放瓶 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_collect_bottle_put_operation_view_v2() -> None:
    # [OPERATION robot_collect_bottle_put] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=c4f25fd2-1118-50c0-ab41-a710930e9534 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_collect_bottle_put',
        inputs_json='{"enter_anchor":"P1","station_id":"default"}',
        expected_sha256='d2e61b77983ecc5740bdd89f85ece02bf07008ad65b0af522a73056ae44e7a3d',
    )
    # [VERIFY comment] 只读来源校验 robot_collect_bottle_put@body/0；本视图中静态 disabled。
    # unilab:node_uuid=ba9adb98-aefa-50bb-99f5-9e37309b0c0e disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_collect_bottle_put',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='c94f5206680744de11103e2b10080fea2f88c5ec7996c9e333b26f5c605d8f94',
    )
    # [CONTROL if] 来源 robot_collect_bottle_put@body/1；原节点 {"cond":{"binop":"==","left":{"var":"enter_anchor"},"right":{"lit":"P1"}},"op":"if","then":[{"action":"robot.home_ensure","mode":"RUN","op":"call"},{"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}]}
    # unilab:node_uuid=6369708b-c725-5304-a421-d445772ff6bb
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_collect_bottle_put@body/1；本视图中静态 disabled。
        # unilab:node_uuid=80cc32c3-fb63-5939-a5f7-c6ae9fb5185a disabled=true
        projected_control_0003 = material.review_control_node_v1(
            operation_name='robot_collect_bottle_put',
            node_path='body/1',
            control_kind='if',
            expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
        )
        # unilab:node_uuid=80919100-3d62-562c-8c06-493664321fcb
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.home_ensure] 来源 robot_collect_bottle_put@body/1/then/0；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
            # unilab:node_uuid=4656e848-675b-529b-9f3a-65bccdf4ab81 disabled=true
            projected_action_0004 = robot.home_ensure()
            # [SUBWORKFLOW robot_tool_ensure] 来源 robot_collect_bottle_put@body/1/then/1；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
            # unilab:node_uuid=4ac8d939-bb90-56a7-b027-0644774d8f5f
            nested_operation_0005 = robot_tool_ensure_operation_view_v2()
        # unilab:node_uuid=21713b8f-fa45-565b-bd83-022c2b63fa0a
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_collect_bottle_put@body/1；本视图中静态 disabled。
            # unilab:node_uuid=97435cb4-3123-573d-a285-777e415830c7 disabled=true
            projected_control_0006 = material.review_control_node_v1(
                operation_name='robot_collect_bottle_put',
                node_path='body/1',
                control_kind='if',
                expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
            )
    # [CONTROL if] 来源 robot_collect_bottle_put@body/2；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.bottle.put: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_...
    # unilab:node_uuid=26ee5e83-71b5-57e1-b88d-d675548d0e24
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_collect_bottle_put@body/2；本视图中静态 disabled。
        # unilab:node_uuid=36062ace-9faa-5ff5-bb94-cecdcad45664 disabled=true
        projected_control_0007 = material.review_control_node_v1(
            operation_name='robot_collect_bottle_put',
            node_path='body/2',
            control_kind='if',
            expected_sha256='e9400d3ff591d1e43f0cab25104669e73231ac5a9f8126bce1f2ce939b4474ab',
        )
        # unilab:node_uuid=6a9ce261-89ea-562b-8ea6-8463b28d3cd8
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collect_bottle_put@body/2/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d5571b39-c2cc-5d9f-8465-6e888e76ae6d disabled=true
            projected_action_0008 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=864c49eb-6e50-5102-b05a-52fed8620e0f disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='P70',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-put.far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2c70e8ae-9785-5298-b168-fb829995be11 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='collect-bottle-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bb044893-7991-5152-bdba-a81fe97a8c5b disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='collect-bottle-put.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P71"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c38e53ec-c91b-5e70-8e63-1aefe9d45a75 disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='P71',
            )
            # [ACTION robot.tool_action] 来源 robot_collect_bottle_put@body/2/then/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e7a6ded0-46c7-53a8-9345-c2056fbe4c0f disabled=true
            projected_action_0013 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=000de29d-354c-50b5-9910-e2d83a33383e disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='collect-bottle-put.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b72ea3ca-3cd6-5eba-a063-d214767375e0 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='collect-bottle-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=34a0ccd1-c60b-5854-bc11-387f8badbbc9 disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='P70',
            )
            # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1a003089-11bf-5de7-bfd6-6e2c1ab42fd8 disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_collect_bottle_put@body/2/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2f0081be-9459-534b-bc57-22a83f3b5361 disabled=true
            projected_action_0018 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=c33436ec-16d7-5cba-8b47-50beb95fd432
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_collect_bottle_put@body/2/else/0；本视图中静态 disabled。
            # unilab:node_uuid=fa47540b-f166-596e-80bc-1013030d434f disabled=true
            projected_control_0019 = material.review_control_node_v1(
                operation_name='robot_collect_bottle_put',
                node_path='body/2/else/0',
                control_kind='raise',
                expected_sha256='1e4445019c6c0d5841f97876971f21988fceb257969d0a2c50ad2d5ca147769c',
            )
