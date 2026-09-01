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
    workflow_uuid='51599550-cdf9-5a8c-8238-eba2856ffc2f',
    displayname='刮板工位放收集器-进入 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_scrape_holder_put_enter_operation_view_v2() -> None:
    # [OPERATION robot_scrape_holder_put_enter] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=2083705a-3768-5bfb-8fc7-79483ffe3161 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_scrape_holder_put_enter',
        inputs_json='{"station_id":"default"}',
        expected_sha256='3314664bccf9c4cc50f88fc2d086bb0822d165f4488c4dfcf605121f9d4d4a40',
    )
    # [VERIFY comment] 只读来源校验 robot_scrape_holder_put_enter@body/0；本视图中静态 disabled。
    # unilab:node_uuid=759dd9ac-6dfd-583b-8c87-f6499fd3bc08 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_scrape_holder_put_enter',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
    )
    # [ACTION robot.home_ensure] 来源 robot_scrape_holder_put_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=8c9ab412-e426-58d4-80d6-25bdc02b14cd disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_scrape_holder_put_enter@body/2；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=f138120e-0a16-550d-a735-12361081b91e
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_scrape_holder_put_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.put-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_...
    # unilab:node_uuid=ab81670b-03d4-54ed-a9df-18258479124d
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_scrape_holder_put_enter@body/3；本视图中静态 disabled。
        # unilab:node_uuid=dcd73e0d-beed-542a-b077-4a56a7708255 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_scrape_holder_put_enter',
            node_path='body/3',
            control_kind='if',
            expected_sha256='889ead3dd615334a51a10135bcf5cf81a22f302b8c78cfe8118136239929efb7',
        )
        # unilab:node_uuid=d95aba5e-0d80-5b1b-921f-364f2395bd36
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_put_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=636fd00f-8041-5f51-8e46-5a5c193dc881 disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_scrape_holder_put_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b28246ee-eac5-5346-9a6d-94c428bca4f4 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P67"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=13a69a8c-ea4a-59ba-b071-ce581e5d7e37 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P67',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.far"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9a74fabf-3e87-588d-9bed-dd07cf9ad1d4 disabled=true
            projected_action_0009 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-put.far',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5f0b978d-64eb-534f-856f-7cf08b5d75e3 disabled=true
            projected_action_0010 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-put.near',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P68"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=6030f1cc-0bf2-58e7-9bb6-6e051382fb25 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='P68',
            )
            # [VERIFY comment] 只读来源校验 robot_scrape_holder_put_enter@body/3/then/6；本视图中静态 disabled。
            # unilab:node_uuid=174a073f-d7d7-57f0-8895-ab380bd237f5 disabled=true
            projected_control_0012 = material.review_control_node_v1(
                operation_name='robot_scrape_holder_put_enter',
                node_path='body/3/then/6',
                control_kind='comment',
                expected_sha256='eaafeb2fe9c5b3588791aa1f250b354965bdb69679c7f3dfbfcae5539fbe5e8a',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.x-plus"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b3500cd1-086f-5483-ab9a-094597df767b disabled=true
            projected_action_0013 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-put.x-plus',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.x-minus"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=58b1ea93-107c-54fe-8f4e-0d7eb2a0274d disabled=true
            projected_action_0014 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-put.x-minus',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P68"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7daf5174-1077-5642-ab61-dfa4f13d02d2 disabled=true
            projected_action_0015 = robot.move_to_point(
                point_id_or_robot_name='P68',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.y-minus"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=951b76a8-b7e5-50ac-84de-2a8156edf81a disabled=true
            projected_action_0016 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-put.y-minus',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.y-plus"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5d47657f-9131-5908-8989-bbe34f55bbac disabled=true
            projected_action_0017 = robot.move_to_point(
                point_id_or_robot_name='scrape-holder-put.y-plus',
            )
            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P68"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f2328502-ced0-5a8c-befd-480bd3966ba4 disabled=true
            projected_action_0018 = robot.move_to_point(
                point_id_or_robot_name='P68',
            )
            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_put_enter@body/3/then/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P68"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=caee4eae-8a63-5871-bc00-faf72ab98ab6 disabled=true
            projected_action_0019 = robot.require_anchor(
                point_id='P68',
            )
        # unilab:node_uuid=b053452a-29bf-5164-93e5-bdee031b5582
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_scrape_holder_put_enter@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=6f2c40b3-f9b0-5d22-86ef-9da7fc6e427b disabled=true
            projected_control_0020 = material.review_control_node_v1(
                operation_name='robot_scrape_holder_put_enter',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='ffc292dd7914745d71afcb9fc032a1108cd8929a102a53b2352d6717519577b8',
            )
