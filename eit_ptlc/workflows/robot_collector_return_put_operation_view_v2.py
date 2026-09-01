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
    workflow_uuid='ec99c217-2b4f-569b-9a80-b8ed09e54514',
    displayname='中转A放回单收集器 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_collector_return_put_operation_view_v2() -> None:
    # [OPERATION robot_collector_return_put] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=dbbb2438-eadd-52fa-95c3-ddd3d3b4d273 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_collector_return_put',
        inputs_json='{"enter_anchor":"P1","slot_id":1}',
        expected_sha256='39a9fecbcc0251fe28ea2f21eca92e10dc1485254a98415d928e714835da773f',
    )
    # [VERIFY comment] 只读来源校验 robot_collector_return_put@body/0；本视图中静态 disabled。
    # unilab:node_uuid=53f04916-c4e6-557a-8ae2-b6fb38fa2ce7 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_collector_return_put',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='52d95a49b3516c8b471e4044dc213c8c24c95fa83fe64e49518e197b4b655b0c',
    )
    # [CONTROL if] 来源 robot_collector_return_put@body/1；原节点 {"cond":{"binop":"==","left":{"var":"enter_anchor"},"right":{"lit":"P1"}},"op":"if","then":[{"action":"robot.home_ensure","mode":"RUN","op":"call"},{"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}]}
    # unilab:node_uuid=fc60e1e3-87d4-5f99-9f31-f7f785662be9
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_collector_return_put@body/1；本视图中静态 disabled。
        # unilab:node_uuid=fcfc30bb-606f-5a12-bdf8-d11dca0f8f44 disabled=true
        projected_control_0003 = material.review_control_node_v1(
            operation_name='robot_collector_return_put',
            node_path='body/1',
            control_kind='if',
            expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
        )
        # unilab:node_uuid=8ff3c046-62be-5d3d-a80d-a421d216297c
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.home_ensure] 来源 robot_collector_return_put@body/1/then/0；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
            # unilab:node_uuid=84cbd21d-e766-54c7-b0f8-10fb38ba7a6d disabled=true
            projected_action_0004 = robot.home_ensure()
            # [SUBWORKFLOW robot_tool_ensure] 来源 robot_collector_return_put@body/1/then/1；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
            # unilab:node_uuid=044b925d-a2ed-556b-97ed-2c720c958afd
            nested_operation_0005 = robot_tool_ensure_operation_view_v2()
        # unilab:node_uuid=6469c92f-d031-53d9-9609-92f25d042d97
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_collector_return_put@body/1；本视图中静态 disabled。
            # unilab:node_uuid=4bd0a4c1-a499-562f-bafa-6f361babd991 disabled=true
            projected_control_0006 = material.review_control_node_v1(
                operation_name='robot_collector_return_put',
                node_path='body/1',
                control_kind='if',
                expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
            )
    # [CONTROL if] 来源 robot_collector_return_put@body/2；原节点 {"cond":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"robot.move_to_point","args":{"acc":{"lit...
    # unilab:node_uuid=1934c31b-7ba9-51fc-b66d-bb8bb7156d8a
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_collector_return_put@body/2；本视图中静态 disabled。
        # unilab:node_uuid=76e7bf9c-70e1-575c-80f4-a86dbd3446ea disabled=true
        projected_control_0007 = material.review_control_node_v1(
            operation_name='robot_collector_return_put',
            node_path='body/2',
            control_kind='if',
            expected_sha256='8335be8a566a88a799ba0463516d9f1743d65290456880ccf38e4954da7d0852',
        )
        # unilab:node_uuid=d47053e8-70ff-5904-adf1-e18f83affb79
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bad9f96a-a2ac-5eed-ae66-3a8911da338b disabled=true
            projected_action_0008 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=494b26c5-1089-58a1-8b3a-2ee33979b006 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p78.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5cfb48d0-3661-5c49-8566-85eaabbc480b disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p78.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p78.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e8dd1704-2f44-584a-9d99-8c3807e5807f disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p78.near',
            )
            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=659a883b-eef3-5f4a-b36c-aecb33495633 disabled=true
            projected_action_0012 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p78.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cd6b86d4-ddfe-5d2e-a9b7-ef039d42db60 disabled=true
            projected_action_0013 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p78.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p78.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=168452bc-5061-5b83-9cab-0f9eefd6a983 disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p78.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=46e4f5b1-674c-5244-920f-3a5396392cf2 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=df6493e0-6fae-53a2-a568-888241643e84 disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/then/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d1b958ea-8839-5f93-9337-f611019f9bd0 disabled=true
            projected_action_0017 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=22804686-0693-50cd-af91-2f76e77cc206
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ad60e631-37da-5e1d-b3ad-44dfb8857c12 disabled=true
            projected_action_0018 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ace00215-1809-5f27-a780-8f98b68f21c2 disabled=true
            projected_action_0019 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p79.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4c64e7ec-8ec3-505d-ae9d-cf9d08be14a5 disabled=true
            projected_action_0020 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p79.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p79.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2aff2af0-9df3-528d-8d1c-4eca4d562d04 disabled=true
            projected_action_0021 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p79.near',
            )
            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/0/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c3a61f43-9460-57e0-8a16-a451bb6cd732 disabled=true
            projected_action_0022 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p79.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=933098f3-8d9e-52b0-a1fc-1afc91565c39 disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p79.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p79.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cea19247-0aaa-5359-a1b4-aacb5796d86b disabled=true
            projected_action_0024 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p79.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ede568e9-4fa4-53ff-bad8-236eb90f8a39 disabled=true
            projected_action_0025 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5a19bc11-de06-5981-9d68-a74813e830bd disabled=true
            projected_action_0026 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/0/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=60c9eca3-e202-52bc-b74b-01fa50247d4c disabled=true
            projected_action_0027 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=2b1d704b-ce8c-5c62-9a8e-9536b97ca8a4
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=485b7fab-2ade-50ac-b323-1bfc2b6b24a0 disabled=true
            projected_action_0028 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cfec352f-e251-5e1b-b4af-4cf335325432 disabled=true
            projected_action_0029 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p80.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d4cefd18-0c82-59a2-9ce3-8f3e5319de98 disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p80.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p80.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f4406b36-0d57-51c6-8456-15a1515d72bb disabled=true
            projected_action_0031 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p80.near',
            )
            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/1/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fa0d04e9-690b-52ef-9be3-8560f5644ecb disabled=true
            projected_action_0032 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p80.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7c81efbc-91bf-5dcf-87d7-1cc70116615a disabled=true
            projected_action_0033 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p80.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p80.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5813f5c6-1e7d-5927-9b0d-e2abdd47a120 disabled=true
            projected_action_0034 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p80.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=644f2f73-c418-5081-a909-153206505c46 disabled=true
            projected_action_0035 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=97b8cfee-f68e-55f9-803b-5a6dab37cff6 disabled=true
            projected_action_0036 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/1/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dbbfc629-99d4-59b9-a18b-8aeae8bd56b5 disabled=true
            projected_action_0037 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=eb32520a-005a-5bf1-bca0-430342db1b36
        with group(name='ELIF 3（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=26818801-07ad-59d6-883b-24fde18c15bf disabled=true
            projected_action_0038 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=613d6ff4-ea50-5003-8314-58ffbb4c2ab6 disabled=true
            projected_action_0039 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p81.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6135d66d-f8d3-5b00-8968-ca35edd2c95b disabled=true
            projected_action_0040 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p81.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p81.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=eee2ff97-9eca-5832-ba25-1226c8381e2b disabled=true
            projected_action_0041 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p81.near',
            )
            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/2/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=25ae1f64-9282-5f0d-8c9e-6325a9d8d491 disabled=true
            projected_action_0042 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p81.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=07434073-c734-5ac3-b7c5-379d0c258709 disabled=true
            projected_action_0043 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p81.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p81.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bd6367aa-0bda-5feb-a00c-c0491405460a disabled=true
            projected_action_0044 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p81.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=02a158f7-498c-5030-ba2c-b4e8cddc9e16 disabled=true
            projected_action_0045 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e1d3e62c-ff04-513d-9f0c-641157913172 disabled=true
            projected_action_0046 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/2/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=02860087-0908-5dd1-a8c0-d537a30a7a91 disabled=true
            projected_action_0047 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=c2ba1800-4665-577d-97d8-f699b92a193f
        with group(name='ELIF 4（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=307b9315-8253-55d8-bf54-4f79e6a3357f disabled=true
            projected_action_0048 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e14c0bef-6ead-5efc-800a-27b74cc424df disabled=true
            projected_action_0049 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p82.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7add867a-a152-5a2e-b9f5-a4ec5bf32d1d disabled=true
            projected_action_0050 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p82.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p82.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fb991082-8bec-5aa7-99d1-fb2cd69477f8 disabled=true
            projected_action_0051 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p82.near',
            )
            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/3/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bef6e32f-debb-5097-b5d2-7db40fa3efb3 disabled=true
            projected_action_0052 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p82.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=abf93bf9-3443-5a47-9a09-3a457cf886ba disabled=true
            projected_action_0053 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p82.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p82.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=91c64918-7516-59a8-bef6-971874b92f78 disabled=true
            projected_action_0054 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p82.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7a567d34-25a8-57bb-ab6e-c233a8cb9e78 disabled=true
            projected_action_0055 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3aacd36d-9802-5ab9-b843-597892f6321e disabled=true
            projected_action_0056 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/3/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=eb556637-f83b-5244-8696-08f3c9a81321 disabled=true
            projected_action_0057 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=5542ba17-3bd7-5e18-8b93-f1f2c14b0f22
        with group(name='ELIF 5（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fcc2b769-1e1a-53c8-8840-6b3a50ae00b0 disabled=true
            projected_action_0058 = robot.require_anchor(
                point_id='review-only',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=90f4c123-aed5-561a-9abf-cbdaf5999e72 disabled=true
            projected_action_0059 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p83.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=17df262d-f580-55fe-8f19-387e10d19706 disabled=true
            projected_action_0060 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p83.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p83.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=35046176-ee9a-52b0-a0ab-e7e22f4570d6 disabled=true
            projected_action_0061 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p83.near',
            )
            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/4/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a494feeb-6c82-545d-9c14-502edb0adccc disabled=true
            projected_action_0062 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p83.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f05c8494-26b9-59db-80f1-d9b2db8c81bd disabled=true
            projected_action_0063 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p83.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p83.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=89779791-ff73-5abd-8857-fc030e4d58e7 disabled=true
            projected_action_0064 = robot.move_to_point(
                point_id_or_robot_name='staging-a-return.p83.high',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c827acfa-5a55-5317-9002-7f3be3022ce4 disabled=true
            projected_action_0065 = robot.move_to_point(
                point_id_or_robot_name='P45',
            )
            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ca597da8-35d9-52ee-9666-46a8523da398 disabled=true
            projected_action_0066 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/4/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bc13f335-e3b5-516e-87e2-0b2e349bcb24 disabled=true
            projected_action_0067 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=6692a4d4-07e5-5331-8e9b-926338d43009
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_collector_return_put@body/2/else/0；本视图中静态 disabled。
            # unilab:node_uuid=563a0504-c898-51e0-90d0-c13001198299 disabled=true
            projected_control_0068 = material.review_control_node_v1(
                operation_name='robot_collector_return_put',
                node_path='body/2/else/0',
                control_kind='raise',
                expected_sha256='a57328573180f43a956abcbb37f8fa364faa86665f2a8db135cfd6638cabdd09',
            )
