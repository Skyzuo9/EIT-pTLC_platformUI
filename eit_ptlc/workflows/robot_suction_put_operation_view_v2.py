from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_rail import PLCRail
from eit_ptlc.unilab_domain.devices.robot import RobotProxy
from eit_ptlc.unilab_domain.devices.vision import VisionProxy
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)


material: MaterialProxy = device('material')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')
vision: VisionProxy = device('vision')


@workflow(
    workflow_uuid='7e3c9520-4867-571f-b5a8-3c54deda4b48',
    displayname='台面放板 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_suction_put_operation_view_v2() -> None:
    # [OPERATION robot_suction_put] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=64e0093a-ad49-59ed-86fa-80124a7639f7 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_suction_put',
        inputs_json='{"station_id":"spotting"}',
        expected_sha256='63c841ea30da7453816cee7a1e642aa710a974707815b2f161e380e7ec907d7f',
    )
    # [VERIFY comment] 只读来源校验 robot_suction_put@body/0；本视图中静态 disabled。
    # unilab:node_uuid=8224ad52-ccaf-5415-a996-cccd1cda42ec disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_suction_put',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
    )
    # [ACTION robot.home_ensure] 来源 robot_suction_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
    # unilab:node_uuid=59f7f8a1-a687-5431-8ee2-9bc439dca8e5 disabled=true
    projected_action_0003 = robot.home_ensure()
    # [SUBWORKFLOW robot_tool_ensure] 来源 robot_suction_put@body/2；原节点 {"inputs":{"needed":{"lit":1}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=6ee90302-ef97-5c44-a9a1-aeda57c254c7
    nested_operation_0004 = robot_tool_ensure_operation_view_v2()
    # [CONTROL if] 来源 robot_suction_put@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"spotting"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}...
    # unilab:node_uuid=f12e8cc1-0c42-5bcf-b003-802a2ce73840
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_suction_put@body/3；本视图中静态 disabled。
        # unilab:node_uuid=38e1b0ea-3b8a-5e77-aac6-20d4b7b55278 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_suction_put',
            node_path='body/3',
            control_kind='if',
            expected_sha256='c6e01866d4b84eab4021c0d16f3f62c88f5591b3d547740457d335c5752f77cc',
        )
        # unilab:node_uuid=82510bbf-7904-52f8-b947-b402e3119ad4
        with group(name='THEN（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9a20ac60-117d-5349-b70b-744a7d836323 disabled=true
            projected_action_0006 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_suction_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=601f1ace-cb24-50b9-8bf6-8ee4c374b631 disabled=true
            projected_action_0007 = rail.ensure(
                Rail_Target_Position=1,
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=574cf33d-85ba-55c0-a5d7-592c1680ecd6 disabled=true
            projected_action_0008 = robot.move_to_point(
                point_id_or_robot_name='P4',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=41604067-fadb-539c-bde2-d5da3b671fc0 disabled=true
            projected_action_0009 = robot.tool_action(
                action='rotary-up',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/4；本视图中静态 disabled。
            # unilab:node_uuid=264fb86a-30b0-51d1-b8c3-3533328e6385 disabled=true
            projected_control_0010 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/4',
                control_kind='comment',
                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":30},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=eb83d793-acb7-5e61-b78e-7c066dd05271 disabled=true
            projected_action_0011 = robot.move_to_point(
                point_id_or_robot_name='P86',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/6；本视图中静态 disabled。
            # unilab:node_uuid=01c7cddc-1fec-548b-be92-a6f45a8cb1e9 disabled=true
            projected_control_0012 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/6',
                control_kind='comment',
                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/7；本视图中静态 disabled。
            # unilab:node_uuid=f467ec04-da76-5eb8-afda-f2221e5d4723 disabled=true
            projected_control_0013 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/7',
                control_kind='comment',
                expected_sha256='6eb397dae264a9b5a09ae3c1405d64b2e9c5a940c36db02de4fccc6dbc9c1bcc',
            )
            # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cadaf50b-fdb4-572f-90c7-ffa7b038a7af disabled=true
            projected_action_0014 = robot.dwell(
                duration_ms=300,
            )
            # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/9；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8db20e48-cb62-5443-af15-f2b05d121e75 disabled=true
            projected_action_0015 = vision.capture_plate_offset()
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/10；本视图中静态 disabled。
            # unilab:node_uuid=ff7bb019-29d2-5ee8-8c4d-31e1376316b6 disabled=true
            projected_control_0016 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/10',
                control_kind='comment',
                expected_sha256='da1eff387eb64169c00489a80c9924bb0712d59bd3a8c496e6bbce7259465c59',
            )
            # [CONTROL if] 来源 robot_suction_put@body/3/then/11；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_r...
            # unilab:node_uuid=7257d606-7078-5979-89f5-f74fa9e42479
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11；本视图中静态 disabled。
                # unilab:node_uuid=8bd431d7-8eee-5987-860f-c93ff2ce42fa disabled=true
                projected_control_0017 = material.review_control_node_v1(
                    operation_name='robot_suction_put',
                    node_path='body/3/then/11',
                    control_kind='if',
                    expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                )
                # unilab:node_uuid=5e991139-bbe6-50d3-bcd9-84d8077b644e
                with group(name='THEN（互斥分支）'):
                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/11/then/0；本视图中静态 disabled。
                    # unilab:node_uuid=73dc384f-9550-52ed-b9b5-7d600aa98f51 disabled=true
                    projected_control_0018 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3/then/11/then/0',
                        control_kind='human',
                        expected_sha256='8b6554332d59da20e8cd66a97f4e67c5e9471404e4488c74e2aede653f7c5a9d',
                    )
                    # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/11/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=1f66eb47-d206-55d3-8c57-4ced1e748c07 disabled=true
                    projected_action_0019 = vision.capture_plate_offset()
                    # [CONTROL if] 来源 robot_suction_put@body/3/then/11/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别仍失败(err=111), 中止放板"},"op":"raise"}]}
                    # unilab:node_uuid=32a46b7b-b731-534b-ac27-df77e32c05a5
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11/then/2；本视图中静态 disabled。
                        # unilab:node_uuid=8210d4d0-b33e-52d3-9191-4e38160ca62f disabled=true
                        projected_control_0020 = material.review_control_node_v1(
                            operation_name='robot_suction_put',
                            node_path='body/3/then/11/then/2',
                            control_kind='if',
                            expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                        )
                        # unilab:node_uuid=427dbf80-01db-5451-95a6-80bcc3e4fee4
                        with group(name='THEN（互斥分支）'):
                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/11/then/2/then/0；本视图中静态 disabled。
                            # unilab:node_uuid=31a7cc12-89ee-5f42-ba21-c2c18f54a447 disabled=true
                            projected_control_0021 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/11/then/2/then/0',
                                control_kind='raise',
                                expected_sha256='be10d3c30d5567c5173255006de750689ae329cb8beab67051668e78cfe857d1',
                            )
                        # unilab:node_uuid=cf05ec68-945a-5a44-8487-2cade53ab07c
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11/then/2；本视图中静态 disabled。
                            # unilab:node_uuid=c7efcbf9-2afc-589c-8631-e44d8484e38a disabled=true
                            projected_control_0022 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/11/then/2',
                                control_kind='if',
                                expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                            )
                # unilab:node_uuid=2d627288-d6fd-51a3-83d5-b12a477f3608
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11；本视图中静态 disabled。
                    # unilab:node_uuid=5d20fda8-fd79-55b4-88d7-8ed2c625b37e disabled=true
                    projected_control_0023 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3/then/11',
                        control_kind='if',
                        expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                    )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/12；本视图中静态 disabled。
            # unilab:node_uuid=e8ce4e11-fa1a-5963-9101-b19534eae629 disabled=true
            projected_control_0024 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/12',
                control_kind='comment',
                expected_sha256='048674f96cc7d9fb228936ecdb955de10db5887d33835cfc6ea532a5508b4f8c',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"lit":0},"dy_mm":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9e812517-2ce7-5838-b5e3-344c687eda7c disabled=true
            projected_action_0025 = robot.move_to_point(
                point_id_or_robot_name='P86',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/14；本视图中静态 disabled。
            # unilab:node_uuid=754f9361-df63-52b6-acd7-da3fabb4553a disabled=true
            projected_control_0026 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/14',
                control_kind='comment',
                expected_sha256='edde8dc0a1dbbe5d4b7696db96096110c9413ee1e108d8eeaadcc4acca4b40a7',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/15；本视图中静态 disabled。
            # unilab:node_uuid=b28a79a6-63e1-5cbe-8e57-fe9e74625e68 disabled=true
            projected_control_0027 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/15',
                control_kind='comment',
                expected_sha256='c80c2f69ad6f5f186109645ffa15fa383576a369addd3d672205333e130a5b58',
            )
            # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/16；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=73bb9cf5-56a7-580e-be4c-0087d2472771 disabled=true
            projected_action_0028 = robot.dwell(
                duration_ms=300,
            )
            # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/17；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2cf4bf8b-5a2f-5d77-9f6c-6aaf036f49eb disabled=true
            projected_action_0029 = vision.capture_plate_offset()
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/18；本视图中静态 disabled。
            # unilab:node_uuid=aa31a8a3-90a0-5b3f-9fd5-df51d85a146a disabled=true
            projected_control_0030 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/18',
                control_kind='comment',
                expected_sha256='c883d653edf20b229c98087fef4e0a7a74c71315be24a495a2ab4d63627ddbc7',
            )
            # [CONTROL if] 来源 robot_suction_put@body/3/then/19；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机二次识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff...
            # unilab:node_uuid=c4f99ac7-1181-521b-aaf9-8fb727503a93
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19；本视图中静态 disabled。
                # unilab:node_uuid=c7fd469d-4696-5695-b726-49830a3f3187 disabled=true
                projected_control_0031 = material.review_control_node_v1(
                    operation_name='robot_suction_put',
                    node_path='body/3/then/19',
                    control_kind='if',
                    expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                )
                # unilab:node_uuid=f174f39e-2d58-52b6-8710-35283e5bf8cf
                with group(name='THEN（互斥分支）'):
                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/19/then/0；本视图中静态 disabled。
                    # unilab:node_uuid=9b74e714-ae21-5c83-b971-d1d83617a888 disabled=true
                    projected_control_0032 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3/then/19/then/0',
                        control_kind='human',
                        expected_sha256='cac0a9d59b9391aae093bca3c1049db6e51757d3aae2d1a433addc60e61ea15d',
                    )
                    # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/19/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=a6e3f0fa-ca2c-5a7f-a1eb-663e06da7194 disabled=true
                    projected_action_0033 = vision.capture_plate_offset()
                    # [CONTROL if] 来源 robot_suction_put@body/3/then/19/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别重拍仍失败(err=111), 中止放板"},"op":"raise"}]}
                    # unilab:node_uuid=9797c0ef-ad1b-5231-ab11-7f2849cb041b
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19/then/2；本视图中静态 disabled。
                        # unilab:node_uuid=8af755c4-066a-59d3-ae6a-96d50d4ac79a disabled=true
                        projected_control_0034 = material.review_control_node_v1(
                            operation_name='robot_suction_put',
                            node_path='body/3/then/19/then/2',
                            control_kind='if',
                            expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                        )
                        # unilab:node_uuid=adb3a93f-6d5a-545f-8b9d-beaace57f7fe
                        with group(name='THEN（互斥分支）'):
                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/19/then/2/then/0；本视图中静态 disabled。
                            # unilab:node_uuid=3e5dab23-ce73-527b-9059-209bca26c355 disabled=true
                            projected_control_0035 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/19/then/2/then/0',
                                control_kind='raise',
                                expected_sha256='6a40626789cfd5679600b1a1b2f6f06f22050fa14f437045f3d9d5dcc6da4252',
                            )
                        # unilab:node_uuid=d17f00e7-d383-5570-a094-2bf97cbabb2b
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19/then/2；本视图中静态 disabled。
                            # unilab:node_uuid=16c71b04-0b20-5ac2-95fd-7b4e7b001519 disabled=true
                            projected_control_0036 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/19/then/2',
                                control_kind='if',
                                expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                            )
                # unilab:node_uuid=7d460af3-6c3e-500e-b9e6-6b504e45ff7e
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19；本视图中静态 disabled。
                    # unilab:node_uuid=7008ef66-9e3e-55e8-8aed-9fa7d6d11e24 disabled=true
                    projected_control_0037 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3/then/19',
                        control_kind='if',
                        expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                    )
            # [CONTROL if] 来源 robot_suction_put@body/3/then/20；原节点 {"cond":{"binop":">","left":{"args":[{"field":{"var":"voff_xy"},"name":"drz_deg"}],"call":"abs"},"right":{"var":"drz_threshold_deg"}},"op":"if","then":[{"error":"VISION_RZ_NOT_CONVERGED","message":{"lit":"二次拍照后 Rz 残差仍超阈值, 中止放板"},"op":"raise"}]}
            # unilab:node_uuid=05ea3a65-a522-555f-8601-1ed4f57ddc3e
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/20；本视图中静态 disabled。
                # unilab:node_uuid=78bf55ef-1cb6-5c02-a17e-2e6c6abce198 disabled=true
                projected_control_0038 = material.review_control_node_v1(
                    operation_name='robot_suction_put',
                    node_path='body/3/then/20',
                    control_kind='if',
                    expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                )
                # unilab:node_uuid=f0001a1f-5811-5f27-9afa-799071ae99fc
                with group(name='THEN（互斥分支）'):
                    # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/20/then/0；本视图中静态 disabled。
                    # unilab:node_uuid=e0996387-82bc-558d-a630-6299d2edf336 disabled=true
                    projected_control_0039 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3/then/20/then/0',
                        control_kind='raise',
                        expected_sha256='d1a24a4f91395a726e8540c6184463fd49fc2fe218385828e42af6f5c642b12d',
                    )
                # unilab:node_uuid=6308a7aa-505e-57ab-97f6-47678a2c4f4e
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/20；本视图中静态 disabled。
                    # unilab:node_uuid=c27596d7-60e6-5a3c-9611-6dc3e1e43d52 disabled=true
                    projected_control_0040 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3/then/20',
                        control_kind='if',
                        expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                    )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/21；本视图中静态 disabled。
            # unilab:node_uuid=0b5616b6-dc85-58ba-bb7f-c4ab95368490 disabled=true
            projected_control_0041 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/21',
                control_kind='comment',
                expected_sha256='152da6bbb7e27be6e627d1a263fc9073bba19a63e635f096a9db1c353d46245d',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/22；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode...
            # unilab:node_uuid=96cd1eed-4015-5dd4-9b87-53b9ce646127 disabled=true
            projected_action_0042 = robot.move_to_point(
                point_id_or_robot_name='P86',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/23；本视图中静态 disabled。
            # unilab:node_uuid=640cdbfd-c1e3-53f9-a5fc-442e6aecedf5 disabled=true
            projected_control_0043 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/23',
                control_kind='comment',
                expected_sha256='d34a5964054eb7bfa4a11d998941ad9c474d621664cbe44fff1c7a011f963154',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/24；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=de9b16d3-e9b6-5ec4-8e06-512f8b18966f disabled=true
            projected_action_0044 = robot.move_to_point(
                point_id_or_robot_name='P4',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/25；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=986ee785-1570-5c43-b2ca-8f1a2bf48a85 disabled=true
            projected_action_0045 = robot.move_to_point(
                point_id_or_robot_name='spotting.put.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/26；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_near"},"...
            # unilab:node_uuid=22b134c0-b05b-5b2a-91a0-f02c32d0e745 disabled=true
            projected_action_0046 = robot.move_to_point(
                point_id_or_robot_name='spotting.put.approach_near',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/27；本视图中静态 disabled。
            # unilab:node_uuid=480e1fd5-5909-59a4-9ab8-e7c29373b20a disabled=true
            projected_control_0047 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/27',
                control_kind='comment',
                expected_sha256='d16b5d31b63a1b0b0f9c85c8e09a509abf646d4812b6ef38723c29608e0c02bd',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/28；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P19"},"vel":{"lit":5}},"mode":...
            # unilab:node_uuid=7ab7ce5d-e14b-5671-a564-b6915c4c7fd1 disabled=true
            projected_action_0048 = robot.move_to_point(
                point_id_or_robot_name='P19',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/29；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=22d3f608-1005-5b98-93b9-7f6cf6ec8258 disabled=true
            projected_action_0049 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/30；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_near"},"v...
            # unilab:node_uuid=6959f95f-90be-5aad-b0ad-42b7b049ff15 disabled=true
            projected_action_0050 = robot.move_to_point(
                point_id_or_robot_name='spotting.put.retreat_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/31；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=877b9dfc-c8a5-535c-98bf-632ea71d43d9 disabled=true
            projected_action_0051 = robot.move_to_point(
                point_id_or_robot_name='spotting.put.retreat_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/32；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7d87cba0-5b90-5f24-b749-46b9a6eceebb disabled=true
            projected_action_0052 = robot.move_to_point(
                point_id_or_robot_name='P4',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/33；本视图中静态 disabled。
            # unilab:node_uuid=40d455db-b98e-5984-9edb-4a06bf139ee3 disabled=true
            projected_control_0053 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/then/33',
                control_kind='comment',
                expected_sha256='8805176604a784f2e55230a1248ed02398b6d66a330667628b5e04cf578d6a79',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/34；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f3bdc126-a1af-5fb1-a159-639c0afd62ba disabled=true
            projected_action_0054 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/35；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=bf7b739d-95d3-5d2b-b1eb-0b57595b1a95 disabled=true
            projected_action_0055 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/36；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7b4df755-ff3e-54f1-841b-7990f3cd708d disabled=true
            projected_action_0056 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=d995c2c5-069c-5166-8d44-e14f49d945e0
        with group(name='ELIF 1（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b15c8028-76d2-52d0-90c2-69286b9af43b disabled=true
            projected_action_0057 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2a7de738-0a9d-5427-a6ed-274bffd6e3fc disabled=true
            projected_action_0058 = rail.ensure(
                Rail_Target_Position=2,
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=83815688-9747-57ca-9d6e-f98092b9ad36 disabled=true
            projected_action_0059 = robot.move_to_point(
                point_id_or_robot_name='P63',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e2254680-b123-5d9a-95ae-eaf9f0ffe8f9 disabled=true
            projected_action_0060 = robot.tool_action(
                action='rotary-up',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/4；本视图中静态 disabled。
            # unilab:node_uuid=5ce65bd7-249d-5e0b-b787-a898b1563198 disabled=true
            projected_control_0061 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/elifs/0/body/4',
                control_kind='comment',
                expected_sha256='72c75af1e4a1520e92d0910d1ec5bb1fbe7428fd161fbc792048931e3b80b01d',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7e18e9bd-7a7d-5bd7-bf3a-44fc63053ce5 disabled=true
            projected_action_0062 = robot.move_to_point(
                point_id_or_robot_name='P63',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7eeb5e20-ff71-5b5c-a5a3-dc81a909ebd7 disabled=true
            projected_action_0063 = robot.move_to_point(
                point_id_or_robot_name='scrape.plate-put.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2286f89a-1be8-5e07-a67b-f174052db3e9 disabled=true
            projected_action_0064 = robot.move_to_point(
                point_id_or_robot_name='scrape.plate-put.approach_near',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/8；本视图中静态 disabled。
            # unilab:node_uuid=04687665-9979-5cf9-94e3-18d1cb22f5c1 disabled=true
            projected_control_0065 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/elifs/0/body/8',
                control_kind='comment',
                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P65"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7e48b215-345e-5a08-a4e5-0c74b6168c20 disabled=true
            projected_action_0066 = robot.move_to_point(
                point_id_or_robot_name='P65',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=819e6156-a891-5648-8694-a9f75e6030c9 disabled=true
            projected_action_0067 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b31794b6-aed0-5913-aa69-aeced8392253 disabled=true
            projected_action_0068 = robot.move_to_point(
                point_id_or_robot_name='scrape.plate-put.retreat_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0c23dfa8-41e7-5ffc-8d06-c64ecd222317 disabled=true
            projected_action_0069 = robot.move_to_point(
                point_id_or_robot_name='scrape.plate-put.retreat_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=34f9d824-b2ad-53f5-9776-afaa2cb3165d disabled=true
            projected_action_0070 = robot.move_to_point(
                point_id_or_robot_name='P63',
            )
            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/14；本视图中静态 disabled。
            # unilab:node_uuid=c22d49bb-1834-5907-921b-d9776a7b0900 disabled=true
            projected_control_0071 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/elifs/0/body/14',
                control_kind='comment',
                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/15；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=06157736-8a6c-5ef5-9886-aa45284c5792 disabled=true
            projected_action_0072 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=1ffaf36e-7459-5903-92ab-8dc203c024e2 disabled=true
            projected_action_0073 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/17；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=ffc7d615-26ad-56af-b334-71d8b4ec1b27 disabled=true
            projected_action_0074 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=495fae84-6357-5e8c-97bc-e8c58ddf1e05
        with group(name='ELIF 2（互斥分支）'):
            # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2b3fbdaf-5167-55bd-be23-2c88cb771ba5 disabled=true
            projected_action_0075 = robot.require_anchor(
                point_id='P1',
            )
            # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c2a7d678-052c-5121-9b81-5d647b12cf2e disabled=true
            projected_action_0076 = rail.ensure(
                Rail_Target_Position=1,
            )
            # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a4d46844-d47c-5eab-ae19-f5b8aa1f706b disabled=true
            projected_action_0077 = robot.tool_action(
                action='rotary-down',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b105b9d0-88f6-5794-b53c-e9b11374a742 disabled=true
            projected_action_0078 = robot.move_to_point(
                point_id_or_robot_name='P5',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3680e9d1-37aa-5895-924f-27714d9fcae9 disabled=true
            projected_action_0079 = robot.move_to_point(
                point_id_or_robot_name='waste.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5ab33e0e-db93-5e41-9b11-7c1a7a0c6710 disabled=true
            projected_action_0080 = robot.move_to_point(
                point_id_or_robot_name='waste.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P22"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e450d20a-3ead-55cb-b12d-655048a42b10 disabled=true
            projected_action_0081 = robot.move_to_point(
                point_id_or_robot_name='P22',
            )
            # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5acc1f4f-bdef-5b1a-9ecb-e2e7ed8c7b16 disabled=true
            projected_action_0082 = robot.tool_action(
                action='suction-off',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=08c479b5-4874-53a7-8286-02189be9a3b0 disabled=true
            projected_action_0083 = robot.move_to_point(
                point_id_or_robot_name='waste.approach_near',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b4056b82-d223-5cbe-a58c-049efff9b1c8 disabled=true
            projected_action_0084 = robot.move_to_point(
                point_id_or_robot_name='waste.approach_far',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=726a1d15-9d2c-59d5-820c-5790896be124 disabled=true
            projected_action_0085 = robot.move_to_point(
                point_id_or_robot_name='P5',
            )
            # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5814b044-0018-59be-bf5d-87f920ddb485 disabled=true
            projected_action_0086 = robot.move_to_point(
                point_id_or_robot_name='P1',
            )
            # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=e74fabde-dd5b-55b4-b2d6-de88fdef69da disabled=true
            projected_action_0087 = robot.require_anchor(
                point_id='P1',
            )
        # unilab:node_uuid=b537ee08-f396-51c7-ba95-ee0389d5c872
        with group(name='ELSE（互斥分支）'):
            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/else/0；本视图中静态 disabled。
            # unilab:node_uuid=6255ed17-dc76-5f09-bca1-0d26f1510423 disabled=true
            projected_control_0088 = material.review_control_node_v1(
                operation_name='robot_suction_put',
                node_path='body/3/else/0',
                control_kind='raise',
                expected_sha256='7ee4ffd8bc9852082873ab137113eb00aa6df1b10ce72423cb995bbc3e2c295a',
            )
