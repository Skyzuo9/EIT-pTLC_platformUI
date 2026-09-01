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
    workflow_uuid='94c6a320-0c9e-5f8e-a2b6-419d0de6c858',
    displayname='货架放整组 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_group_rack_put_operation_view_v2() -> None:
    # [OPERATION robot_group_rack_put] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=5843ee49-19f0-5672-9c49-bac1a2d9fa06 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_group_rack_put',
        inputs_json='{"rack_id":"collector","slot_id":1}',
        expected_sha256='2f0fc00dd2b2896bae9557d4ab8b40c239de7c9a50572d5da4cfbfdaa0464cea',
    )
    # [VERIFY comment] 只读来源校验 robot_group_rack_put@body/0；本视图中静态 disabled。
    # unilab:node_uuid=a618b3fc-44ac-5d57-9027-63ca25df27a9 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_group_rack_put',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='e39d4d29dad9ddaeb2a8577b39843afb69f527adda4225bc7355c38ab532c9fe',
    )
    # [ACTION robot.home_ensure] 来源 robot_group_rack_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=85ea8432-cf0c-568f-8396-2091afd90525 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_group_rack_put@body/2；原节点 {"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=b5bb35d1-9a3b-561b-a54a-01c09779bb1b
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_group_rack_put@body/3；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"right":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":...
    # unilab:node_uuid=02e1f4df-1ca8-5985-8854-8c58aa588072
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_group_rack_put@body/3；本视图中静态 disabled。
        # unilab:node_uuid=b97a543e-39c2-580f-83ec-70192f2d9d3b disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_group_rack_put',
            node_path='body/3',
            control_kind='if',
            expected_sha256='8f3899ceb2a6e4a73860e57bad52ae737ff82eac9663fcac51880d36fa675be3',
        )
        # unilab:node_uuid=d7005240-102f-55ce-a370-929ad205b4e8
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a05077a5-8195-52c9-a56b-f7c7fe5fce44 disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2ff8de8b-2f7e-5878-a9ec-b0cfadbc05d7 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7dae60dc-2f13-50d1-a946-6e74bfe6fde1 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3e42e505-8c25-5e49-9bd3-93b60d32f3dd disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1f1f3b51-e4f7-5ba1-bece-ca1ec3cc3ac4 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a384b42b-e50e-5116-93ed-464c3f65ea57 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P25"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8dc7950f-6d5a-5b9f-a392-94fcf5f6eb96 disabled=true
            projected_action_0012 = robot.move_to_point(
                point_id_or_robot_name='P25',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e7e699e0-c16b-5631-be35-e4618264d62d disabled=true
            projected_action_0013 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1d33da8c-2545-534f-95fd-c67e9d69e210 disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7846995e-240d-54c4-932d-09dad14712a1 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1fd505e1-17dc-53ce-bfd1-989aa9d8ff5e disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p25.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=561da5e5-5891-5522-a433-c256b057ea92 disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9decf11a-7f59-56e2-be8d-f5a186720974 disabled=true
            projected_action_0018 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/then/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e9ad96c2-c93b-57e3-9840-d73fb173bc73 disabled=true
            projected_action_0019 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=52a28252-5797-511b-851a-b4103e617f21
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bfb4dc29-a115-5567-bd99-c87d2c1e6d05 disabled=true
            projected_action_0020 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=464127ea-ed62-55ab-b3a5-fff370a833d9 disabled=true
            projected_action_0021 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4c497eb2-e657-5b12-9f31-5e0f818236f8 disabled=true
            projected_action_0022 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4192c7d3-a400-563d-8e88-8b3bdeaba5a0 disabled=true
            projected_action_0023 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=38dfb24b-2181-5ac5-9acf-6395815b97ac disabled=true
            projected_action_0024 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4d84b334-34df-595e-85c6-1f2700b6c0ea disabled=true
            projected_action_0025 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P26"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=33a5de06-7df2-56fe-9c02-55c7da44b8e4 disabled=true
            projected_action_0026 = robot.move_to_point(
                point_id_or_robot_name='P26',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ee23b0c7-e349-5ce9-8f2b-a3a836b6edfd disabled=true
            projected_action_0027 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b1a98fa2-50f9-5cc8-a929-de8622c2196c disabled=true
            projected_action_0028 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=91134de6-b2c3-5c71-a808-529866b39c6d disabled=true
            projected_action_0029 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7397bee3-6b64-5a21-9f2d-ca7492a06221 disabled=true
            projected_action_0030 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p26.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dbd0e68b-072b-5342-9672-152958c5b348 disabled=true
            projected_action_0031 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=12ba4120-d2c0-5da0-8023-1ca3d93c093a disabled=true
            projected_action_0032 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/0/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=77357ff6-994d-5532-b846-6408c716a097 disabled=true
            projected_action_0033 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=683ebabb-8cbe-5f5b-a20b-747a3c4476bb
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2d586c33-f38a-5ba0-b6c8-26342f7e86b9 disabled=true
            projected_action_0034 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=309c28f9-2d83-596e-87d7-8c03e2f6f9ae disabled=true
            projected_action_0035 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=44222e98-eb57-50d3-b0da-11ea39ffbd31 disabled=true
            projected_action_0036 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3dffb250-e175-5a03-afae-e7a8613f48e6 disabled=true
            projected_action_0037 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=acd21357-a5a5-53fd-8dfd-342879a0beba disabled=true
            projected_action_0038 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=97678b36-40e7-52bc-8a4c-b0328b827967 disabled=true
            projected_action_0039 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P27"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7012ef81-e1cb-5b3a-8b72-ec11545eba7e disabled=true
            projected_action_0040 = robot.move_to_point(
                point_id_or_robot_name='P27',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b2f328e8-ecac-5321-994b-96db86d269a3 disabled=true
            projected_action_0041 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f52a232c-6863-5691-9f85-eac828be36cd disabled=true
            projected_action_0042 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=181c3d88-b21c-5db9-874a-9e585700c03d disabled=true
            projected_action_0043 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d4e193b0-64b4-5aaa-8c19-67cddb660750 disabled=true
            projected_action_0044 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p27.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e8702f09-3d1d-5305-8d80-be280b8a5e10 disabled=true
            projected_action_0045 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fb4dcd70-61cc-5fb6-8506-979d9d4aaec4 disabled=true
            projected_action_0046 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/1/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=28c61fe5-8933-55d1-a7b4-105c53d0d9d1 disabled=true
            projected_action_0047 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=1ab49fbf-48c9-5c79-88a7-d82f9f565c24
        with group(name='ELIF 3（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8044de4f-00c5-5512-86e8-f287932cf992 disabled=true
            projected_action_0048 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f2d22747-2bb2-55f7-8407-e92993372e42 disabled=true
            projected_action_0049 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5f1f3ff2-c1ee-5e28-83ee-63cf36f0c4ee disabled=true
            projected_action_0050 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a2078864-0c62-5ee0-8c73-55ef774f82e6 disabled=true
            projected_action_0051 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c48ebf91-8fe9-5b6e-92ea-9959798a59fb disabled=true
            projected_action_0052 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=065daec9-6491-5159-951e-e5804d994937 disabled=true
            projected_action_0053 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P28"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6d77179e-a809-5252-890a-b6fce67975e7 disabled=true
            projected_action_0054 = robot.move_to_point(
                point_id_or_robot_name='P28',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/2/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=23b33189-b7f6-5b28-ab17-24b9a57b0355 disabled=true
            projected_action_0055 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f0f1bdaf-5b0d-5cb1-9ee7-03139af861b1 disabled=true
            projected_action_0056 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f17b3680-dd65-5479-8786-868b4785f0ae disabled=true
            projected_action_0057 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7558f8d2-9202-57dd-8743-2c5a2d03b162 disabled=true
            projected_action_0058 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p28.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b0200730-054a-58cb-a933-cbb9652bdbf7 disabled=true
            projected_action_0059 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bca91b35-c009-531a-acfc-54005a13e50c disabled=true
            projected_action_0060 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/2/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=449a66be-4aaf-53ae-a0cf-7dccd5884947 disabled=true
            projected_action_0061 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=9e30af0f-a6f5-5237-9b90-0ad3caefc900
        with group(name='ELIF 4（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4ed3d3d6-0375-5cdd-9f80-f9a732792f6e disabled=true
            projected_action_0062 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6f6eff8d-909b-52c8-a4a7-8a21a6d64e6d disabled=true
            projected_action_0063 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a46cf8dc-44ea-5d20-92e4-80ea7108edd4 disabled=true
            projected_action_0064 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a48d23ca-0bb7-5fdf-b1e4-ac3632f0359e disabled=true
            projected_action_0065 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a0e80cfa-3a24-571b-8862-9d580f0effb6 disabled=true
            projected_action_0066 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7f9055b5-e49b-5657-bcb7-bd6305e9dbe1 disabled=true
            projected_action_0067 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P29"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9c0b34f8-53b5-5e50-a7ba-606b9d51b69d disabled=true
            projected_action_0068 = robot.move_to_point(
                point_id_or_robot_name='P29',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/3/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cf6b5f2d-c219-5b25-895b-04b9557ff003 disabled=true
            projected_action_0069 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7975cb7c-9ba8-5db3-923d-f06e59c8cc2c disabled=true
            projected_action_0070 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=634d92a5-f084-574c-be43-634fc5a5d5b0 disabled=true
            projected_action_0071 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=52b19465-9b03-528f-a9f3-ab9d4c2d51e6 disabled=true
            projected_action_0072 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p29.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=20473ae1-3f14-5c12-b338-cfd255739bbb disabled=true
            projected_action_0073 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=42398d5f-06b2-56e8-99ea-b20277395a76 disabled=true
            projected_action_0074 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/3/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=93f87332-c215-5ac8-8985-4bcc36fbca72 disabled=true
            projected_action_0075 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=d0830948-fcb9-5a88-8369-fa83372d0603
        with group(name='ELIF 5（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c4b72eaa-7782-51f1-be5e-dcb1ec6f3835 disabled=true
            projected_action_0076 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cd8cea40-8e2d-578e-be1d-c77896274bf1 disabled=true
            projected_action_0077 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1b3590d4-edae-555b-8829-61bfcf1ee93f disabled=true
            projected_action_0078 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=813bf3cb-d4b8-5705-87f3-2d45a83f6465 disabled=true
            projected_action_0079 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b7f2f4ba-7eae-5da6-b78b-94e4712cb11e disabled=true
            projected_action_0080 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2e615d60-da9a-5c5f-a99b-e5aa0a01434b disabled=true
            projected_action_0081 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P30"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=28e6ec25-0499-56d1-a5fb-078b741564ea disabled=true
            projected_action_0082 = robot.move_to_point(
                point_id_or_robot_name='P30',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/4/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a5193e7a-1446-5f99-9d58-80f1091bdf38 disabled=true
            projected_action_0083 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c2d292cf-a4dc-5964-ae66-40eff36af9e4 disabled=true
            projected_action_0084 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e650ad43-487c-5505-9469-298b117eefd7 disabled=true
            projected_action_0085 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=375f6993-c226-5db2-8b31-303bee4329c4 disabled=true
            projected_action_0086 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p30.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ebb62aea-d3b4-5f1d-8967-f950f0f0517d disabled=true
            projected_action_0087 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d04983b5-0b24-5175-a38e-9d946ab14fa3 disabled=true
            projected_action_0088 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/4/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=02aa592d-2366-598f-b43b-f56ffcbfce24 disabled=true
            projected_action_0089 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=f42b17bf-f20b-5277-a94a-6715c0394162
        with group(name='ELIF 6（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0c2297ef-6c95-5854-b34d-1abad6e1609e disabled=true
            projected_action_0090 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=558e95d3-91ac-5222-b7da-46b1d67c19d0 disabled=true
            projected_action_0091 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=786227f7-a7d4-581c-b5ab-dc7541ec685a disabled=true
            projected_action_0092 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b1c743b1-21fc-5f1f-9492-73e470381862 disabled=true
            projected_action_0093 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d07597a7-663a-5520-bfba-d1ccd9a4406a disabled=true
            projected_action_0094 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=89a7c41d-5a45-5fba-b8d4-3a11b7b5c519 disabled=true
            projected_action_0095 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P31"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a8560121-f989-52df-a237-d0853cacb1e4 disabled=true
            projected_action_0096 = robot.move_to_point(
                point_id_or_robot_name='P31',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/5/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3fd02fe2-8427-5ee8-b4c2-72b651448ed1 disabled=true
            projected_action_0097 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9fedb238-6ee3-5847-9c44-537de007c0d1 disabled=true
            projected_action_0098 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bda24b17-a202-509c-a48c-b72f86c36558 disabled=true
            projected_action_0099 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6ed2514c-c39a-50bb-bb8e-ff3158acda91 disabled=true
            projected_action_0100 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p31.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a0376fa6-a47c-577a-ac59-650990ea41cf disabled=true
            projected_action_0101 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=829af017-2343-519a-a26d-3b36a2c4e8d6 disabled=true
            projected_action_0102 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/5/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4ffc164c-1497-55dd-a6c2-261c3c67bd4f disabled=true
            projected_action_0103 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=9df8f08a-2a6e-51c3-9666-a51a93c7ab4e
        with group(name='ELIF 7（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f0d80034-2e76-50f7-bf6f-c3cf2a86a849 disabled=true
            projected_action_0104 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3c0b1860-0121-5db4-9675-bc96f0c5bb59 disabled=true
            projected_action_0105 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=18649f0a-d622-5733-9d3a-93705a724d6b disabled=true
            projected_action_0106 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0759fc24-1899-51cd-9222-fbb83cd20abf disabled=true
            projected_action_0107 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=543a87c1-5eb5-5cf8-a875-da50b180cf79 disabled=true
            projected_action_0108 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4af8ac21-8d26-5510-9bec-d89946671609 disabled=true
            projected_action_0109 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P32"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=52dfa038-04df-5bca-8f1d-b3c2b3cde3d2 disabled=true
            projected_action_0110 = robot.move_to_point(
                point_id_or_robot_name='P32',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/6/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0f2acf3b-e174-5561-8d6b-f6e25998b6ab disabled=true
            projected_action_0111 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b64e00c8-0cef-5a98-a1a6-a7c723afa952 disabled=true
            projected_action_0112 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=86bf8da3-3341-5240-b22a-46914b89d85e disabled=true
            projected_action_0113 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5d291b02-f6a8-50e4-9ba2-72f6a89871bd disabled=true
            projected_action_0114 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p32.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=848c6e90-9bba-5e2b-983c-b94c0b1d9d69 disabled=true
            projected_action_0115 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2ee533c2-6187-529b-bf19-06e80b2f5434 disabled=true
            projected_action_0116 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/6/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5ca0317a-dcde-5b84-8182-71da202579c9 disabled=true
            projected_action_0117 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=a4c2faf9-5fc6-5cff-a0c5-52be389b9b3c
        with group(name='ELIF 8（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/7/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a68e2769-4f35-5b5a-8eb1-cfebbf1b4a69 disabled=true
            projected_action_0118 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/7/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=84c3590d-b385-510f-be64-8658ab7ec255 disabled=true
            projected_action_0119 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=27941926-849e-5782-a4ec-116fc78e9615 disabled=true
            projected_action_0120 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dad59147-3212-581f-a48e-fbc1416b0a91 disabled=true
            projected_action_0121 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7701b341-05d1-5525-9202-afd035ba0749 disabled=true
            projected_action_0122 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b15b2f99-d7ec-55b5-8a96-ef682de4fc07 disabled=true
            projected_action_0123 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P33"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=73c44a74-6945-5349-9016-f84b30d7bf5a disabled=true
            projected_action_0124 = robot.move_to_point(
                point_id_or_robot_name='P33',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/7/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6f587b21-677b-5ea5-a75f-ab149943bbd2 disabled=true
            projected_action_0125 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=887689b1-0577-5e2f-a208-5eae158e96ef disabled=true
            projected_action_0126 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b6fc77c0-ce77-55cd-b959-ba66f98f717f disabled=true
            projected_action_0127 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2c732a97-ac29-52f6-9058-8b70f400c415 disabled=true
            projected_action_0128 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p33.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7cfeae80-2f9d-5146-abe1-169f65028679 disabled=true
            projected_action_0129 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=86fcebe0-674c-5ff5-9233-5976f43f4630 disabled=true
            projected_action_0130 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/7/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9919dcfa-d8ce-5e50-83ae-528901359993 disabled=true
            projected_action_0131 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=09b80950-32b3-596d-af41-98d8bdc9255b
        with group(name='ELIF 9（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/8/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2321f765-512d-54be-98b7-513ef76437d6 disabled=true
            projected_action_0132 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/8/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1eba740a-42f0-5c29-82c2-23cab814606c disabled=true
            projected_action_0133 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b35a45d5-2549-51d4-a027-b31bbc83fa51 disabled=true
            projected_action_0134 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bad085f9-e88c-5d89-b0d5-d560d1a2ec73 disabled=true
            projected_action_0135 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1fd96a8c-eab4-58c3-97a1-e4f133b864b4 disabled=true
            projected_action_0136 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bdbc4e86-1fc3-5edb-b7d8-ce2f4e5e0831 disabled=true
            projected_action_0137 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P34"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=93921b0c-904e-5968-8fcc-4ae6c3cd28b8 disabled=true
            projected_action_0138 = robot.move_to_point(
                point_id_or_robot_name='P34',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/8/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d338f3ee-3f10-50bd-8ae6-2692c8df62ea disabled=true
            projected_action_0139 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b8e15740-d7e9-5218-a515-3f6e8d9b2805 disabled=true
            projected_action_0140 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0a3b0098-2e51-5a08-a1c0-52f8f65a2858 disabled=true
            projected_action_0141 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b00c7193-22e4-5cf6-ae82-6470ab7a7e52 disabled=true
            projected_action_0142 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p34.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9de70329-c48b-5b24-9bb1-e0634b427d48 disabled=true
            projected_action_0143 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d6f52969-6027-52a0-b46a-bd9416472703 disabled=true
            projected_action_0144 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/8/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e779b73f-e349-50c8-a3e4-60632535b779 disabled=true
            projected_action_0145 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=20f0d10b-37b6-5082-a8f5-270f16eb120a
        with group(name='ELIF 10（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/9/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=30d8c68d-ca98-5504-ae4f-68b427c1afec disabled=true
            projected_action_0146 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/9/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a235d188-7869-5fb7-b97a-f6e8c7cf22cf disabled=true
            projected_action_0147 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ad9a3fbf-3802-504d-9472-6a3d5c5256ca disabled=true
            projected_action_0148 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d50bdae4-b441-5e90-a1a3-216621cb4496 disabled=true
            projected_action_0149 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b90884a4-0671-5d64-98b7-388e1b8a8f98 disabled=true
            projected_action_0150 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=743f8710-9734-55ca-b8f8-e0497df182af disabled=true
            projected_action_0151 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P35"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=fb02ea97-9a1c-59d4-97ef-5681dc34c9d1 disabled=true
            projected_action_0152 = robot.move_to_point(
                point_id_or_robot_name='P35',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/9/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e7615614-9d31-53fb-b8bb-51c47f8afe10 disabled=true
            projected_action_0153 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2235e7d7-dd6d-5687-8387-a9ba39ae0cf1 disabled=true
            projected_action_0154 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b8aac87b-434d-55f1-9e62-f0f4a62e289b disabled=true
            projected_action_0155 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8efe9408-db88-5e64-a6e1-8640f8d081a7 disabled=true
            projected_action_0156 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p35.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7cad7689-fd2d-5ebe-87c0-0d3828f3e032 disabled=true
            projected_action_0157 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=02bd9a25-75ec-570c-b3a2-a28d72936fd7 disabled=true
            projected_action_0158 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/9/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8c898549-e082-5c9e-bd9c-34fa206bd65b disabled=true
            projected_action_0159 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=35cc4519-3d12-5c4f-b181-e14213d516c6
        with group(name='ELIF 11（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/10/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=35ee157f-73cf-58ac-98f9-f9013708be8c disabled=true
            projected_action_0160 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/10/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=11c2d5eb-fa44-5a31-8926-d15743ef2f33 disabled=true
            projected_action_0161 = rail.ensure(
                Rail_Target_Position=6,
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f5f9f42c-7ffc-54ad-9341-025df9ac79f2 disabled=true
            projected_action_0162 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e9f31fef-7c46-5d67-81f6-f735628138cf disabled=true
            projected_action_0163 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5e4e6a47-58b3-54be-bffc-a618c4bde2a1 disabled=true
            projected_action_0164 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=027de36f-93d8-5e0a-b08e-04939d044f24 disabled=true
            projected_action_0165 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P36"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=82fd4b3a-5ef9-5152-91b1-488616d1d4f5 disabled=true
            projected_action_0166 = robot.move_to_point(
                point_id_or_robot_name='P36',
            )
            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/10/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=eac4555e-632b-57fd-8653-65b8c362c7d4 disabled=true
            projected_action_0167 = robot.tool_action(
                action='gripper-open',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=4f08fd5e-947c-5792-b711-8433ec1f0826 disabled=true
            projected_action_0168 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=859f248e-bb9a-502b-92db-869b47b27515 disabled=true
            projected_action_0169 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.mid',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ad3e82de-df7f-5473-bbe3-b0c7a61b61b3 disabled=true
            projected_action_0170 = robot.move_to_point(
                point_id_or_robot_name='group-rack.p36.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dff61017-0d98-51b2-bffa-038e9e7bf8ad disabled=true
            projected_action_0171 = robot.move_to_point(
                point_id_or_robot_name='P7',
            )
            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e7eab2aa-69d2-5095-b25b-1736c05b4614 disabled=true
            projected_action_0172 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/10/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=dc724a49-ba2d-541e-9131-f26ca670c144 disabled=true
            projected_action_0173 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=3b021c96-1f4f-559d-95a3-610532cf5da7
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_group_rack_put@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=de1d52ec-b5dd-5c86-a818-8d718a8a5c60 disabled=true
            projected_control_0174 = material.review_control_node_v1(
                operation_name='robot_group_rack_put',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='c9f6108a83b1bbb80b1623d016e1043aa8953b0ce506af4aaee0bed2ffb0d752',
            )
