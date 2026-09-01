from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.plc_develop import PLCDevelop
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.unilab_domain.devices.plc_rail import PLCRail
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


class PlatformOperationReviewV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    before_path: str
    collector_hole: int
    bottle_hole: int

develop: PLCDevelop = device('plc_develop')
material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='286ecda1-c222-5ed5-a43b-613f3c2a7da7',
    displayname='4 取板进缸 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s5_to_tank_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s5_to_tank] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=250eebd1-50b7-5fb1-8119-18ab4a3e37f5
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s5_to_tank@body/0；原节点 {"op":"comment","text":"刮板侧取板: 松定位 -> 机器人取板 -> retr_stoprot (photoscrape_unload 幂等兜底 press(false))"}
        # unilab:node_uuid=444cd531-ca62-5399-a72e-4d57f9a31049
        with group(name='说明 · 刮板侧取板: 松定位 -> 机器人取板 -> retr_stoprot (photoscrape_unload '):
            # [VERIFY comment] 只读来源校验 pf_s5_to_tank@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=55cb8ec6-60f7-5c23-8eb3-05b218d25a60 disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s5_to_tank',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='c1f7ff400e80e579c5ea2f2d8d15637e092231587a3d13dea9685f779ad1efc9',
            )
        # [SUBWORKFLOW photoscrape_unload] 由 pf_s5_to_tank@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=918cbd3a-f2ad-51d0-bc17-1b8744afd407
        with group(name='↳ photoscrape_unload'):
            # [CONTROL comment] 来源 photoscrape_unload@body/0；原节点 {"op":"comment","text":"unload/板: 若生产 recipe 需要先转走接粉收集器, 应在 execute 与本 step 间执行 collect_load handoff"}
            # unilab:node_uuid=fcc9876d-9ecb-5e15-b825-85cf7b09dfcb
            with group(name='说明 · unload/板: 若生产 recipe 需要先转走接粉收集器, 应在 execute 与本 step 间执行 '):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=52c1a9d3-dde4-5e6c-87e3-ba6a3d9e45ab disabled=true
                projected_control_0002 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='090f54ab39d61c0f619db3e62dd8567d1c8cd386f721a4cd80841f8b2960a951',
                )
            # [SUBWORKFLOW robot_tool_ensure] 由 photoscrape_unload@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=e0c4a90b-a295-5226-8c6b-b1fcd393e4a6
            with group(name='↳ robot_tool_ensure'):
                # [CONTROL comment] 来源 robot_tool_ensure@body/0；原节点 {"op":"comment","text":"读权威工具态 (mounted_tool 启动已从状态文件恢复","回显在 tool_state.mounted_tool)":null}
                # unilab:node_uuid=1f6d419b-1e3b-56ab-a93b-0041de9c3627
                with group(name='说明 · 读权威工具态 (mounted_tool 启动已从状态文件恢复'):
                    # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=213506ad-e595-506e-a161-acc3880b4965 disabled=true
                    projected_control_0003 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='d809e1de31eaaae6a28b91dfdc9f8587e53c48ce272668a1d7794e15c68d86f9',
                    )
                # [ACTION robot.query] 来源 robot_tool_ensure@body/1；原节点 {"action":"robot.query","assign":{"var":"fb"},"mode":"RUN","op":"call"}
                # unilab:node_uuid=a278bf0e-3ea6-5f5b-8ba9-5f00cc191929 disabled=true
                projected_action_0004 = robot.query()
                # [CONTROL assign] 来源 robot_tool_ensure@body/2；原节点 {"op":"assign","target":{"var":"current"},"value":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"mounted_tool"}}
                # unilab:node_uuid=71e5346a-9a19-514c-b6e0-34ce9cb5ffde
                with group(name='变量赋值'):
                    # [VERIFY assign] 只读来源校验 robot_tool_ensure@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=1853e235-d637-5f40-9ebc-73d6170ed601 disabled=true
                    projected_control_0005 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/2',
                        control_kind='assign',
                        expected_sha256='0a8bed4ab1ed21eab44aa30c3cdc41f38a8147534c728fa885ef1da0ba3237c7',
                    )
                # [CONTROL if] 来源 robot_tool_ensure@body/3；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"var":"needed"}},"op":"if","then":[{"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"},{"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"},{"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"r...
                # unilab:node_uuid=f34608f1-09f9-5fb4-82f6-38d0222c99bb
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=36b33950-751f-57b7-842b-9df4105e944e disabled=true
                    projected_control_0006 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                    )
                    # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=ea8d884b-7537-5385-9009-1008c7a1b297
                    with group(name='THEN（互斥分支）'):
                        # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/0；原节点 {"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"}
                        # unilab:node_uuid=b71d888c-d490-5d28-a562-03e80315dbe1
                        with group(name='说明 · 当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标'):
                            # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=2d087c82-f89c-57c2-9cde-5662312a81bb disabled=true
                            projected_control_0007 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/0',
                                control_kind='comment',
                                expected_sha256='f1c1621fc9a3af0fead9abddfba4acc6d628c4e07f02d5e1d6e79342f780d4b5',
                            )
                        # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/1；原节点 {"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"}
                        # unilab:node_uuid=241a2a10-99a8-5957-bf36-d2c260e18bed
                        with group(name='说明 · 卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止'):
                            # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/1；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=c1e55ff7-f6c1-5e10-9137-9cf8b27550a2 disabled=true
                            projected_control_0008 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/1',
                                control_kind='comment',
                                expected_sha256='ab6b298fa1974e89ffba98e42a169ccd9b213ac1a03a6723584be2b1be7e6898',
                            )
                        # [CONTROL if] 来源 robot_tool_ensure@body/3/then/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"right":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"suction_on"}},"op":"if","then":[{"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}]}
                        # unilab:node_uuid=dd7a2226-3afa-5c26-927e-f3536a9449ad
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=e0da1886-ba84-5eb2-801d-ef72ee93f728 disabled=true
                            projected_control_0009 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/2',
                                control_kind='if',
                                expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                            )
                            # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/2/then 的静态审阅分支。
                            # unilab:node_uuid=ad1faafb-6e58-57b6-80f8-c980c70fbaa0
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL raise] 来源 robot_tool_ensure@body/3/then/2/then/0；原节点 {"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}
                                # unilab:node_uuid=b8559b86-8ef8-5875-9e58-4900d72bc12b
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_tool_ensure@body/3/then/2/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=bec27000-00f6-5506-8751-f0544d2bd636 disabled=true
                                    projected_control_0010 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/2/then/0',
                                        control_kind='raise',
                                        expected_sha256='8ade635dfc3c21601ac8fa50ba7a168191332f67cbf70e021465f2765df9b23f',
                                    )
                            # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/2/else 的静态审阅分支。
                            # unilab:node_uuid=37b01555-780d-53fb-ba0c-311e495647fa
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=5573f583-4c61-5158-a335-da7c0f2a3b8e disabled=true
                                projected_control_0011 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/2',
                                    control_kind='if',
                                    expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                )
                        # [SUBWORKFLOW rail_move_safe] 由 robot_tool_ensure@body/3/then/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                        # unilab:node_uuid=ae9c6fd9-4650-59e9-bcf8-6b5265f750d3
                        with group(name='↳ rail_move_safe'):
                            # [CONTROL comment] 来源 rail_move_safe@body/0；原节点 {"op":"comment","text":"确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)"}
                            # unilab:node_uuid=d5e7e6d1-0c4b-5d6c-a113-03d364339f38
                            with group(name='说明 · 确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)'):
                                # [VERIFY comment] 只读来源校验 rail_move_safe@body/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=cdc2fd77-3244-5a48-9562-2bf8818054c4 disabled=true
                                projected_control_0012 = material.review_control_node_v1(
                                    operation_name='rail_move_safe',
                                    node_path='body/0',
                                    control_kind='comment',
                                    expected_sha256='cc629ec60964ec74a746185851e52069f3b991388ab52755ebea4f3b92ed1740',
                                )
                            # [ACTION robot.home_ensure] 来源 rail_move_safe@body/1；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=0ada6f30-a06b-56ef-aa0e-86bcf3d30478 disabled=true
                            projected_action_0013 = robot.home_ensure()
                            # [CONTROL comment] 来源 rail_move_safe@body/2；原节点 {"op":"comment","text":"安全位确认 -> 移动地轨到目标位"}
                            # unilab:node_uuid=00996809-8bb8-5d3f-b04c-eeec6004bed3
                            with group(name='说明 · 安全位确认 -> 移动地轨到目标位'):
                                # [VERIFY comment] 只读来源校验 rail_move_safe@body/2；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=054904b8-d3e5-59cb-b24d-dfac59f15d09 disabled=true
                                projected_control_0014 = material.review_control_node_v1(
                                    operation_name='rail_move_safe',
                                    node_path='body/2',
                                    control_kind='comment',
                                    expected_sha256='38f90a43c3043b67cd1207e8d94cd7c595a01ab69567c39518284d36ecb68702',
                                )
                            # [ACTION rail.move] 来源 rail_move_safe@body/3；原节点 {"action":"rail.move","args":{"Rail_Target_Position":{"var":"target"}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=3c14aa5c-4b84-5a0d-9524-c1f158caaa6a disabled=true
                            projected_action_0015 = rail.move(
                                Rail_Target_Position=1,
                            )
                        # [CONTROL if] 来源 robot_tool_ensure@body/3/then/4；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"lit":0}},"op":"if","then":[{"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}]}
                        # unilab:node_uuid=e837d8a2-2dad-5cbc-a284-cc74d66aff92
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=bc742ede-6bc8-565b-ba1d-03a76a1cd7b7 disabled=true
                            projected_control_0016 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/4',
                                control_kind='if',
                                expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                            )
                            # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/4/then 的静态审阅分支。
                            # unilab:node_uuid=8e877a17-487c-5b06-9736-df09ede4fa1c
                            with group(name='THEN（互斥分支）'):
                                # [SUBWORKFLOW robot_tool_put] 由 robot_tool_ensure@body/3/then/4/then/0 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                # unilab:node_uuid=847232e5-b553-5a6e-8742-206aa4722325
                                with group(name='↳ robot_tool_put'):
                                    # [CONTROL if] 来源 robot_tool_put@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit...
                                    # unilab:node_uuid=009511fb-91fe-59f9-8ce8-161c55aea567
                                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                                        # [VERIFY if] 只读来源校验 robot_tool_put@body/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=045e5ee5-ed0a-5751-92d8-835502c7e622 disabled=true
                                        projected_control_0017 = material.review_control_node_v1(
                                            operation_name='robot_tool_put',
                                            node_path='body/0',
                                            control_kind='if',
                                            expected_sha256='9c64b805f035e287559b6a10c2883f201fed2852028900bfd6c9c7526352d298',
                                        )
                                        # [BRANCH THEN（互斥分支）] robot_tool_put@body/0/then 的静态审阅分支。
                                        # unilab:node_uuid=9a3c4747-1387-5fc2-b8dd-93fbb84608da
                                        with group(name='THEN（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d281533b-326f-5f2f-aa96-a1dfd7fcf6f1 disabled=true
                                            projected_action_0018 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b38d1641-d6c7-5f5c-8250-18ec9a48aa56 disabled=true
                                            projected_action_0019 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6a224170-5e0c-5e9b-80de-9df1353acd08 disabled=true
                                            projected_action_0020 = robot.tool_action(
                                                action='rotary-down',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=16c08702-59d6-52a9-9fc9-36b933b9d682 disabled=true
                                            projected_action_0021 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=90a2a09f-837a-5510-877e-5be96d7a903e disabled=true
                                            projected_action_0022 = robot.tool_action(
                                                action='tool-change-aux-on',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=709e3932-789b-5eff-af0b-93d91644a8e0 disabled=true
                                            projected_action_0023 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ad257f3c-df12-5b4e-9bbd-31c56cc9f454 disabled=true
                                            projected_action_0024 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=71bd70c9-f186-59ef-9703-796a3a2a8379 disabled=true
                                            projected_action_0025 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3d381d14-6cad-5558-b54a-d6e05ecbb684 disabled=true
                                            projected_action_0026 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/9；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=5a15ca1d-3265-5d45-b650-1c16b5046bea disabled=true
                                            projected_action_0027 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/then/10；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=7948e643-9a14-52c6-a7ca-11d75d1e344b disabled=true
                                            projected_action_0028 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6a393453-8fda-59cd-afd6-60cc8d8732df disabled=true
                                            projected_action_0029 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=5e5a0b5c-6672-5fa8-8301-76d0c1f726bf disabled=true
                                            projected_action_0030 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                        # [BRANCH ELIF 1（互斥分支）] robot_tool_put@body/0/elifs/0/body 的静态审阅分支。
                                        # unilab:node_uuid=e5942f62-1a56-5e57-848c-6243a3f9b03d
                                        with group(name='ELIF 1（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6c1f03db-64da-56cc-8486-20674d2c9f85 disabled=true
                                            projected_action_0031 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2ff9eeee-ef72-525b-aedb-4f3b286d825c disabled=true
                                            projected_action_0032 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a5216852-de57-50a7-b708-426bc6c87db4 disabled=true
                                            projected_action_0033 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=355f9b00-ba09-59e8-bf28-6f5d7880ae3c disabled=true
                                            projected_action_0034 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d7de3309-64e6-5cb7-b668-bc2781664056 disabled=true
                                            projected_action_0035 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e6c9a41e-5824-53d1-85ba-c91a7e567200 disabled=true
                                            projected_action_0036 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c1650491-cdc5-5277-8ba7-679d44f01f31 disabled=true
                                            projected_action_0037 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=638df665-e76d-5b8d-8c59-7da8776f6759 disabled=true
                                            projected_action_0038 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c77943f5-9861-5fa2-abb2-86ff7e43bcb4 disabled=true
                                            projected_action_0039 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/0/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=5df1df7a-326d-580f-86eb-90505dcc87ac disabled=true
                                            projected_action_0040 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=74b268b3-0894-5150-95c6-d9d8b0634fb4 disabled=true
                                            projected_action_0041 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8570bf54-772f-5840-a1f6-874747b96882 disabled=true
                                            projected_action_0042 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                        # [BRANCH ELIF 2（互斥分支）] robot_tool_put@body/0/elifs/1/body 的静态审阅分支。
                                        # unilab:node_uuid=1915b919-288e-5a32-ad73-ed985abddb2c
                                        with group(name='ELIF 2（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b262dfc9-bf9a-57f2-ae93-b70397dab3c3 disabled=true
                                            projected_action_0043 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=20bb7faf-9f99-5682-bdbb-64cd37a76843 disabled=true
                                            projected_action_0044 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f466aa1f-cc68-5402-8efb-495873617b52 disabled=true
                                            projected_action_0045 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a8bd1645-dd4e-50fc-9040-a5eb38bc9eb2 disabled=true
                                            projected_action_0046 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=431b36a8-23d6-5b90-9162-ff7280748ef2 disabled=true
                                            projected_action_0047 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d7f4b234-e623-52d0-b50e-a7a2cd9e328e disabled=true
                                            projected_action_0048 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=5e88b5ee-2a1d-57db-a2cb-37186a848a60 disabled=true
                                            projected_action_0049 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=cebda996-8e4b-5e66-93c1-0c518b7aed73 disabled=true
                                            projected_action_0050 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f7c913bf-2efa-5e3c-9c23-331b04b6f7cf disabled=true
                                            projected_action_0051 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/1/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=bd6f0cb6-133b-5491-9be1-0a8a0a47daa2 disabled=true
                                            projected_action_0052 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1ac68ace-902c-59e0-8ea8-71b3c5d8f918 disabled=true
                                            projected_action_0053 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=cf95c162-0d8a-5f17-9dda-f6b8d5e3bb2c disabled=true
                                            projected_action_0054 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                        # [BRANCH ELSE（互斥分支）] robot_tool_put@body/0/else 的静态审阅分支。
                                        # unilab:node_uuid=0b6979c4-9ab6-5e8a-b316-e0f5ff3d6674
                                        with group(name='ELSE（互斥分支）'):
                                            # [FLATTENED CONTROL raise] 只读来源校验 robot_tool_put@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=4f9ed0f5-00c6-500c-8da6-6da6f011f007 disabled=true
                                            projected_control_0055 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='8aa6aa6f749c6777b2a7040e04f4316dd03cc80d36de51eec476b3dbb6c6de75',
                                            )
                            # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/4/else 的静态审阅分支。
                            # unilab:node_uuid=9cd9fb3e-aeab-5a76-a58a-931c409dbac8
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=c1e66953-3f45-5ece-86f1-3de0d381ff19 disabled=true
                                projected_control_0056 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/4',
                                    control_kind='if',
                                    expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                )
                        # [SUBWORKFLOW robot_tool_pick] 由 robot_tool_ensure@body/3/then/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                        # unilab:node_uuid=a7c2fc37-0496-5ab9-be12-58a6ae255308
                        with group(name='↳ robot_tool_pick'):
                            # [CONTROL if] 来源 robot_tool_pick@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"},{"action":"robot.move...
                            # unilab:node_uuid=cef23787-9c54-5282-9a50-a6291791f597
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_tool_pick@body/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=808d294e-8524-5ac2-9854-05271df8b59e disabled=true
                                projected_control_0057 = material.review_control_node_v1(
                                    operation_name='robot_tool_pick',
                                    node_path='body/0',
                                    control_kind='if',
                                    expected_sha256='47a5b48eb2b065101041caadd225ef492b21028bb19039ac3a19991997da1895',
                                )
                                # [BRANCH THEN（互斥分支）] robot_tool_pick@body/0/then 的静态审阅分支。
                                # unilab:node_uuid=fe6e25c5-c1b9-57af-ad21-eadba21474dd
                                with group(name='THEN（互斥分支）'):
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8a4d91e0-66c8-5837-a226-593bc7c89800 disabled=true
                                    projected_action_0058 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=637fbddb-3a29-5017-a70a-a9fdbc2c1fd7 disabled=true
                                    projected_action_0059 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=de68844e-0c3b-5d4b-af06-05fa60ddd36b disabled=true
                                    projected_action_0060 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=319cc6ba-0c33-59d9-8463-89d49c266758 disabled=true
                                    projected_action_0061 = robot.tool_action(
                                        action='quick-change-lock',
                                    )
                                    # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/then/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":1}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c2fe6efc-abc8-5b1f-80f1-f82f6b460258 disabled=true
                                    projected_action_0062 = robot.set_mounted_tool(
                                        tool_id='0',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=1bd57a4b-92bb-53f2-b435-d54108aca535 disabled=true
                                    projected_action_0063 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f4743cc6-9c75-58b8-9a8a-9e273e598c11 disabled=true
                                    projected_action_0064 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f43211b6-b45f-53e4-9322-2c04ac714dc3 disabled=true
                                    projected_action_0065 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.ready',
                                    )
                                    # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=ae5d1c13-e018-5870-a9a8-c085dedd032b disabled=true
                                    projected_action_0066 = robot.dwell(
                                        duration_ms=500,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c5567b2d-4420-5f69-b5d3-85ae36e4c058 disabled=true
                                    projected_action_0067 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.home',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=85c757e4-4767-55e0-a2a3-684ccd6798b4 disabled=true
                                    projected_action_0068 = robot.require_anchor(
                                        point_id='robot-main.home',
                                    )
                                # [BRANCH ELIF 1（互斥分支）] robot_tool_pick@body/0/elifs/0/body 的静态审阅分支。
                                # unilab:node_uuid=900a34bd-261f-593d-9f64-934a4f8d28d1
                                with group(name='ELIF 1（互斥分支）'):
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=abf172ab-b1be-5807-921f-f420478a5f1d disabled=true
                                    projected_action_0069 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8069211b-210c-5692-9c20-dfcc8565e43a disabled=true
                                    projected_action_0070 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=6a86cc00-2c69-54f8-ab5f-57e0f6d92f8a disabled=true
                                    projected_action_0071 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=038389ac-887a-5ab5-84ef-19dd84f809ff disabled=true
                                    projected_action_0072 = robot.tool_action(
                                        action='quick-change-lock',
                                    )
                                    # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/0/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":2}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=5db76f4a-d12c-5416-8cb5-95eea8cde993 disabled=true
                                    projected_action_0073 = robot.set_mounted_tool(
                                        tool_id='0',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a16061a8-5ded-5222-b038-32f95dd0ca9d disabled=true
                                    projected_action_0074 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=1568f9c2-695c-5a57-ac58-99c3fdb5efaa disabled=true
                                    projected_action_0075 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=eec91b63-6c94-559d-8338-ab17fefae2e6 disabled=true
                                    projected_action_0076 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.ready',
                                    )
                                    # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/0/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=7fabfc86-4ae8-55a8-b212-d687707f65f6 disabled=true
                                    projected_action_0077 = robot.dwell(
                                        duration_ms=500,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=aa255d60-6a72-5be0-8ded-05bb6744e03c disabled=true
                                    projected_action_0078 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.home',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8ffab4b8-ef9a-598b-a72b-cf9a57439561 disabled=true
                                    projected_action_0079 = robot.require_anchor(
                                        point_id='robot-main.home',
                                    )
                                # [BRANCH ELIF 2（互斥分支）] robot_tool_pick@body/0/elifs/1/body 的静态审阅分支。
                                # unilab:node_uuid=a60aa488-375d-5153-9764-c04f9bea41ad
                                with group(name='ELIF 2（互斥分支）'):
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=965f8b0a-443c-5887-8342-daaa336bf8cb disabled=true
                                    projected_action_0080 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a0e8f473-bfea-56eb-94ad-19a7a825c920 disabled=true
                                    projected_action_0081 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e642c2dc-15ac-54ff-8033-691d7de909a3 disabled=true
                                    projected_action_0082 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/1/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c4c3af41-f9d5-54fd-9727-7bcfc84d861b disabled=true
                                    projected_action_0083 = robot.tool_action(
                                        action='quick-change-lock',
                                    )
                                    # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/1/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":3}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=fab28c70-ffb0-5ba2-be3d-37e899ff3105 disabled=true
                                    projected_action_0084 = robot.set_mounted_tool(
                                        tool_id='0',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=86e3d50f-46cb-5d6b-bf96-c7a90db00ddd disabled=true
                                    projected_action_0085 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=463536b7-9c80-5207-a939-5287f3da0c34 disabled=true
                                    projected_action_0086 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=ab35cb9f-4be0-587c-8d73-f995d6b0ea68 disabled=true
                                    projected_action_0087 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.ready',
                                    )
                                    # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/1/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=51e4f0c6-e891-5de5-b9e6-2b87abbd3b55 disabled=true
                                    projected_action_0088 = robot.dwell(
                                        duration_ms=500,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c83b882d-1be6-5c1c-9dd0-e40995735661 disabled=true
                                    projected_action_0089 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.home',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d6411428-6fc9-53b4-8d97-cc00772e3073 disabled=true
                                    projected_action_0090 = robot.require_anchor(
                                        point_id='robot-main.home',
                                    )
                                # [BRANCH ELSE（互斥分支）] robot_tool_pick@body/0/else 的静态审阅分支。
                                # unilab:node_uuid=11429541-7ee4-591f-8d94-b93425f422dc
                                with group(name='ELSE（互斥分支）'):
                                    # [CONTROL raise] 来源 robot_tool_pick@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"tool.pick: 无效选择值"},"op":"raise"}
                                    # unilab:node_uuid=c420df8c-6439-5e0d-82c8-c6211ed5cd8e
                                    with group(name='抛出流程错误'):
                                        # [VERIFY raise] 只读来源校验 robot_tool_pick@body/0/else/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=210f4301-2c09-5ac4-9363-4125d180ea42 disabled=true
                                        projected_control_0091 = material.review_control_node_v1(
                                            operation_name='robot_tool_pick',
                                            node_path='body/0/else/0',
                                            control_kind='raise',
                                            expected_sha256='70c2a7e291023e9375102dc659639ba2604e87ffa8a3a94cca033c80b83c21e8',
                                        )
                    # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=7ef0fb8c-7904-53ec-9163-76773c1fd2fc
                    with group(name='ELSE（互斥分支）'):
                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=183b2c41-2757-5706-be71-ce2c6d3e4468 disabled=true
                        projected_control_0092 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/3',
                            control_kind='if',
                            expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                        )
            # [CONTROL comment] 来源 photoscrape_unload@body/2；原节点 {"op":"comment","text":"unload/板: 换刀可能把地轨带到工具位; 松定位前先安全回到刮板拍照位(位2)"}
            # unilab:node_uuid=3fa16a8e-d8e8-5ed3-8ce6-5c64508aadf9
            with group(name='说明 · unload/板: 换刀可能把地轨带到工具位; 松定位前先安全回到刮板拍照位(位2)'):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=556d3320-4c82-5ab4-a0f8-73b1a4c2e228 disabled=true
                projected_control_0093 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='f757b741e63ecef01416b43876c84f448fc33fd8263c1eaa57e30a885a8bc2c2',
                )
            # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 photoscrape_unload@body/3；节点在本工作流中静态 disabled。
            # unilab:node_uuid=651bb71e-ef84-5b6e-8c38-b0c0299a33ad disabled=true
            projected_control_0094 = material.review_control_node_v1(
                operation_name='photoscrape_unload',
                node_path='body/3',
                control_kind='run_script',
                expected_sha256='3375626c6140464d00aa9cbdffc04532e0598412bbb03a5cdc11186253b17bd1',
            )
            # [CONTROL comment] 来源 photoscrape_unload@body/4；原节点 {"op":"comment","text":"unload/板: 先松下压气缸再松定位气缸。press 生产释放点原仅在 collect_load(转走接粉收集器时), 独立/短流程(无 collect 段)会漏放, 板卡在压头下。此处补放 press(false) 幂等——full 流程 collect_load 已放过, 再放无副作用; 保证任何路径下板都不卡压头下, 机器人方可安全取板。"}
            # unilab:node_uuid=cb490deb-b495-52bc-b360-d786754faa0c
            with group(name='说明 · unload/板: 先松下压气缸再松定位气缸。press 生产释放点原仅在 collect_load(转走接粉收'):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=6769e4e9-2de6-5950-ba43-dbc1944b387c disabled=true
                projected_control_0095 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/4',
                    control_kind='comment',
                    expected_sha256='2e88f06e980d94312534dddefa1ec480813bffd17a96170f584aa1ef8e268ad7',
                )
            # [ACTION photoscrape.press_cylinder] 来源 photoscrape_unload@body/5；原节点 {"action":"photoscrape.press_cylinder","args":{"pressed":{"lit":false}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b575a343-76b5-5285-8dc7-b05c13333212 disabled=true
            projected_action_0096 = photoscrape.press_cylinder(
                pressed=False,
            )
            # [CONTROL comment] 来源 photoscrape_unload@body/6；原节点 {"op":"comment","text":"unload/板: 松定位气缸"}
            # unilab:node_uuid=dcd8bc11-b64c-5a5a-ada7-9e2d67c3baa4
            with group(name='说明 · unload/板: 松定位气缸'):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/6；节点在本工作流中静态 disabled。
                # unilab:node_uuid=ce360177-efb9-5310-bca0-0217f96216e1 disabled=true
                projected_control_0097 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/6',
                    control_kind='comment',
                    expected_sha256='24a83be66051ea0aabfd800e906bd880439b5531b0e83a4dc22552f0cf80785f',
                )
            # [ACTION photoscrape.locate_cylinder] 来源 photoscrape_unload@body/7；原节点 {"action":"photoscrape.locate_cylinder","args":{"clamped":{"lit":false}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7923d2e6-c0d8-5ce1-a873-f756ec2a835a disabled=true
            projected_action_0098 = photoscrape.locate_cylinder(
                clamped=False,
            )
            # [CONTROL comment] 来源 photoscrape_unload@body/8；原节点 {"op":"comment","text":"unload/板: 机器人从刮板夹具取板并持板"}
            # unilab:node_uuid=61272c44-a501-5f8c-9ef2-6a1d5f937a7b
            with group(name='说明 · unload/板: 机器人从刮板夹具取板并持板'):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/8；节点在本工作流中静态 disabled。
                # unilab:node_uuid=31ed4cc1-8c80-5bd0-9e6d-a7025f6fe45b disabled=true
                projected_control_0099 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/8',
                    control_kind='comment',
                    expected_sha256='b1aa2e95cccd55c66d6920ddfbcab498ad85ed79d4e37091bab682a6367a685f',
                )
            # [SUBWORKFLOW robot_suction_pick] 由 photoscrape_unload@body/9 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=bcf46895-119b-567b-abc5-010f0db64584
            with group(name='↳ robot_suction_pick'):
                # [CONTROL comment] 来源 robot_suction_pick@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                # unilab:node_uuid=3023cbcd-3335-5d43-b198-6c9c871d9080
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                    # [VERIFY comment] 只读来源校验 robot_suction_pick@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=a1d8557a-540b-51d7-9abe-f53c29680a28 disabled=true
                    projected_control_0100 = material.review_control_node_v1(
                        operation_name='robot_suction_pick',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                    )
                # [ACTION robot.home_ensure] 来源 robot_suction_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=e7d8efa7-e453-5278-af5b-19f12836243f disabled=true
                projected_action_0101 = robot.home_ensure()
                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_suction_pick@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=d2a996a1-a447-5e94-9482-c9211050ad41 disabled=true
                projected_control_0102 = material.review_control_node_v1(
                    operation_name='robot_suction_pick',
                    node_path='body/2',
                    control_kind='run_script',
                    expected_sha256='6248fd65698183b23b0962f697364ce4f9a7187fdfd05d12bfc8d8f678e645b1',
                )
                # [CONTROL if] 来源 robot_suction_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"spotting"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"...
                # unilab:node_uuid=9d79c85c-e314-5ef9-ae69-1295cafe9953
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_suction_pick@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=79919fb8-83a6-5145-8954-0fbb14fc834b disabled=true
                    projected_control_0103 = material.review_control_node_v1(
                        operation_name='robot_suction_pick',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='7cf59bced5f5b2dcd49557f999dbd90eb52637f34cb412ab2176135f0e83d084',
                    )
                    # [BRANCH THEN（互斥分支）] robot_suction_pick@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=637cdc7a-68c8-5bd0-b177-54cf10c65784
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7805b7d9-2119-5c06-9778-d4d8f2607507 disabled=true
                        projected_action_0104 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cbbf9317-f439-5685-9552-7b9377f50539 disabled=true
                        projected_action_0105 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=094c3168-efde-5000-88cb-260221fac396 disabled=true
                        projected_action_0106 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=da8b28ae-f718-5855-9989-a0e76ea51df0 disabled=true
                        projected_action_0107 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b6075b02-4352-5474-8fa6-ac63ef3e70bf disabled=true
                        projected_action_0108 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c50b24b6-eb9a-598e-94e5-2bd12b6a2d14 disabled=true
                        projected_action_0109 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P19"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d8717622-d1c6-530e-b754-0b2e7c203751 disabled=true
                        projected_action_0110 = robot.move_to_point(
                            point_id_or_robot_name='P19',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7b75c73a-141c-5721-bd1d-9635186b497e disabled=true
                        projected_action_0111 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5fae8ce4-d77d-5e19-aae7-f174b0c139ed disabled=true
                        projected_action_0112 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d3ce4bec-ac6b-579a-b57c-7f6cc0c08ecc disabled=true
                        projected_action_0113 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ae566010-ff74-5cee-94f6-906971f42a96 disabled=true
                        projected_action_0114 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=393f3ac8-3b5d-54ed-90c0-3753bbc19ac1 disabled=true
                        projected_action_0115 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/then/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=12a07528-3805-52f0-aafc-c4eae18eee5c disabled=true
                        projected_action_0116 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_suction_pick@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=b406aae0-0d25-5293-ac6d-bd22607db63b
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a4b21490-888f-50d2-a7bc-2958925c2b54 disabled=true
                        projected_action_0117 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7b9643a7-c3fb-5e45-92a6-efc8a248037d disabled=true
                        projected_action_0118 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=300fe980-7381-5e9b-99a3-a8186d39a083 disabled=true
                        projected_action_0119 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cb4e08a6-ecbd-5492-bb55-bce2c389d5ae disabled=true
                        projected_action_0120 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6acab85a-d9b0-58d7-8ac9-adf3fefe495d disabled=true
                        projected_action_0121 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f1521cc0-ab48-5b8d-a200-be0782dad6e3 disabled=true
                        projected_action_0122 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_pick@body/3/elifs/0/body/6；原节点 {"op":"comment","text":"刮板位取/放同基点: 取板与放板同点 P65 (吸附基准=板中心); P64 弃用保留在点表, 勿再引用"}
                        # unilab:node_uuid=c523deec-3c8e-5a13-a431-719d689ba086
                        with group(name='说明 · 刮板位取/放同基点: 取板与放板同点 P65 (吸附基准=板中心); P64 弃用保留在点表, 勿再引用'):
                            # [VERIFY comment] 只读来源校验 robot_suction_pick@body/3/elifs/0/body/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=bf881a30-0e05-5614-8ad9-fa308a94ea5f disabled=true
                            projected_control_0123 = material.review_control_node_v1(
                                operation_name='robot_suction_pick',
                                node_path='body/3/elifs/0/body/6',
                                control_kind='comment',
                                expected_sha256='ce61ff1eddd64c4a26507b7df53f7a45d978ed30161b8ea6895afc3afcafc7bc',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P65"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6778e516-b04c-572a-887f-d8d1784d98a1 disabled=true
                        projected_action_0124 = robot.move_to_point(
                            point_id_or_robot_name='P65',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=21f27736-98ac-51a4-a446-5f976b79aad0 disabled=true
                        projected_action_0125 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8b61545d-1015-5e95-a748-7d2571d2239a disabled=true
                        projected_action_0126 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=54afd8ad-2fa1-5048-bb2f-3c6ef15c197c disabled=true
                        projected_action_0127 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=872f12ef-78eb-5691-bf6a-0b5755e480f6 disabled=true
                        projected_action_0128 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [CONTROL comment] 来源 robot_suction_pick@body/3/elifs/0/body/12；原节点 {"op":"comment","text":"Safety fix: after scraping pick, confirm rotary-up only after retreating to P63."}
                        # unilab:node_uuid=5524bd07-83e5-5ddb-9daa-a354350aa69a
                        with group(name='说明 · Safety fix: after scraping pick, confirm rotary-up only '):
                            # [VERIFY comment] 只读来源校验 robot_suction_pick@body/3/elifs/0/body/12；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=775e245d-395b-582e-9838-99783e5f4dfd disabled=true
                            projected_control_0129 = material.review_control_node_v1(
                                operation_name='robot_suction_pick',
                                node_path='body/3/elifs/0/body/12',
                                control_kind='comment',
                                expected_sha256='0c6391714e618a81ff71411339cb422212bba6d05a807e18d569fcabaea39c2f',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2a52c675-6481-57bd-83cf-98fa13f32466 disabled=true
                        projected_action_0130 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4e800efc-b46a-5167-8db2-c185f15de92f disabled=true
                        projected_action_0131 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/elifs/0/body/15；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1b12d625-a062-543f-8404-97303ab1f14a disabled=true
                        projected_action_0132 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_suction_pick@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=b98e85ee-96f7-589d-92ec-34d172e9148f
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_suction_pick@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"suction.pick: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=315ea1c7-b40d-58ee-b0d8-1ceac0f95637
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_suction_pick@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=ccd5ae1e-b3ec-525c-a6cf-b886a276dfdc disabled=true
                            projected_control_0133 = material.review_control_node_v1(
                                operation_name='robot_suction_pick',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='7324ece78b8e478b8be13e31abd1d3bdbbc53d99d674cd9200fe986e9b80917f',
                            )
        # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 pf_s5_to_tank@body/2；节点在本工作流中静态 disabled。
        # unilab:node_uuid=950abe0c-6573-5d12-a4cb-10c1d8c975bd disabled=true
        projected_control_0134 = material.review_control_node_v1(
            operation_name='pf_s5_to_tank',
            node_path='body/2',
            control_kind='run_script',
            expected_sha256='a5867c808b6e64a92014452968a692b570a56811038f57abe8f8475966f0c7f4',
        )
        # [CONTROL comment] 来源 pf_s5_to_tank@body/3；原节点 {"op":"comment","text":"放板入缸: plate_retract -> robot_tank_put(tank) -> plate_extend; 段末板在缸内 (稳定停放)"}
        # unilab:node_uuid=59838a8e-eaa7-515a-b94c-0999235c9bcc
        with group(name='说明 · 放板入缸: plate_retract -> robot_tank_put(tank) -> plate_ext'):
            # [VERIFY comment] 只读来源校验 pf_s5_to_tank@body/3；节点在本工作流中静态 disabled。
            # unilab:node_uuid=408e0424-4e5f-51a1-9f58-3c950eafee2f disabled=true
            projected_control_0135 = material.review_control_node_v1(
                operation_name='pf_s5_to_tank',
                node_path='body/3',
                control_kind='comment',
                expected_sha256='4f28be509a684771b3a0085e1d01bb5958414291d94338b8fade1a7e14baecb2',
            )
        # [SUBWORKFLOW develop_load] 由 pf_s5_to_tank@body/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=b42664dc-d88f-5c4f-9c32-99813838ad5d
        with group(name='↳ develop_load'):
            # [CONTROL comment] 来源 develop_load@body/0；原节点 {"op":"comment","text":"load: 机器人放板入缸; 前提是 handoff 已让机器人持板到展开位"}
            # unilab:node_uuid=5092fcb5-c9e6-5d09-a3c2-834c86daf560
            with group(name='说明 · load: 机器人放板入缸; 前提是 handoff 已让机器人持板到展开位'):
                # [VERIFY comment] 只读来源校验 develop_load@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=ff2d3334-ce65-51c2-bc3a-66ea428f5e30 disabled=true
                projected_control_0136 = material.review_control_node_v1(
                    operation_name='develop_load',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='9e52f477960de30727544183d80dd63c5c386a99b5f98d17852c8576156c7100',
                )
            # [ACTION develop.plate_retract] 来源 develop_load@body/1；原节点 {"action":"develop.plate_retract","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=40913599-b2f8-51ed-aabf-9085a484942c disabled=true
            projected_action_0137 = develop.plate_retract(
                target_tank=1,
            )
            # [SUBWORKFLOW robot_tank_put] 由 develop_load@body/2 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=5f8658ea-1b5b-551d-9070-b1ae1872efdd
            with group(name='↳ robot_tank_put'):
                # [CONTROL comment] 来源 robot_tank_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                # unilab:node_uuid=938cc75a-a17d-5a3c-870c-a06080d17a4f
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                    # [VERIFY comment] 只读来源校验 robot_tank_put@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=ce410c44-183e-5eb0-a790-f204af8aa1ab disabled=true
                    projected_control_0138 = material.review_control_node_v1(
                        operation_name='robot_tank_put',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                    )
                # [ACTION robot.home_ensure] 来源 robot_tank_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=90f336fd-266c-5bae-8f8f-a4bc059e1e73 disabled=true
                projected_action_0139 = robot.home_ensure()
                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_tank_put@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=229e7f62-779c-5a41-bcbd-5dbc45b6b6fc disabled=true
                projected_control_0140 = material.review_control_node_v1(
                    operation_name='robot_tank_put',
                    node_path='body/2',
                    control_kind='run_script',
                    expected_sha256='6248fd65698183b23b0962f697364ce4f9a7187fdfd05d12bfc8d8f678e645b1',
                )
                # [CONTROL if] 来源 robot_tank_put@body/3；原节点 {"cond":{"binop":"==","left":{"var":"tank_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":...
                # unilab:node_uuid=701ebfd5-5f41-5bd6-b5be-b7de7669f207
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_tank_put@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=ae9af34f-4b88-524d-a44b-85c7cfdb67a3 disabled=true
                    projected_control_0141 = material.review_control_node_v1(
                        operation_name='robot_tank_put',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='7cac4ccf99418e919c33ae5e47bac4a426b84d6c9049626da54c690b9241a381',
                    )
                    # [BRANCH THEN（互斥分支）] robot_tank_put@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=1d40e47a-d153-5552-8251-1080d554b1be
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=73e73027-bd02-527d-bc5e-bb6f592e3563 disabled=true
                        projected_action_0142 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f830d24e-4428-5d36-8cad-535247a7c78e disabled=true
                        projected_action_0143 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c731928b-a62a-543c-90a7-4a2e0d7f2126 disabled=true
                        projected_action_0144 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ab990c2c-109f-5044-9844-da24cfe44e3b disabled=true
                        projected_action_0145 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=88eafebe-8ad1-50a3-9493-385781176c00 disabled=true
                        projected_action_0146 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=74d759de-0980-5c71-a24d-de8c5eed1e34 disabled=true
                        projected_action_0147 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4f56974a-144d-5b09-9b76-591df8307aef disabled=true
                        projected_action_0148 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=64bf6d55-7066-50fb-8a92-310460d0c10d disabled=true
                        projected_action_0149 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=67ebfb6e-3716-586f-a324-5f727df52c0c disabled=true
                        projected_action_0150 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P11"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6c75e7e6-e091-5794-ace9-d3e4ad6ec8d5 disabled=true
                        projected_action_0151 = robot.move_to_point(
                            point_id_or_robot_name='P11',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/then/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=eb0ca099-dad7-5384-ad29-62d0f6ef826a disabled=true
                        projected_action_0152 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=87a9d127-b652-5106-8823-d7074414ac43 disabled=true
                        projected_action_0153 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a7f99944-77ca-5db3-8e06-5b65dccd122a disabled=true
                        projected_action_0154 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d1a9a5bb-f308-596e-a87b-2327601a4355 disabled=true
                        projected_action_0155 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e4a716f5-6b1f-5429-8a40-da53c7e43fec disabled=true
                        projected_action_0156 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a7e6beed-c4e8-5dec-a6f0-c1fa812e9ef8 disabled=true
                        projected_action_0157 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5e7ba7ae-6c51-5d9d-b055-44bc1ad6d48f disabled=true
                        projected_action_0158 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/then/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7a36516d-7e28-5133-bb20-8656b5669bd6 disabled=true
                        projected_action_0159 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/then/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9f62873e-d4f6-51f1-9e03-3bf7eb3792ed disabled=true
                        projected_action_0160 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_tank_put@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=df0e29a9-ca18-545d-a855-8b91ed8776c9
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=02f0dc9a-885d-5556-a774-737ab3ecf949 disabled=true
                        projected_action_0161 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f4d2df03-44ba-5dcd-8b20-3c844b12b0f9 disabled=true
                        projected_action_0162 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=aa9b6da5-ed53-5151-977e-e5fcb73d44c6 disabled=true
                        projected_action_0163 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b2ee7d70-d181-5938-b034-ba28898c11b7 disabled=true
                        projected_action_0164 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b58ea299-74c0-50e7-961b-61da3279c623 disabled=true
                        projected_action_0165 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bf60cec1-228d-5aa0-aeb2-03cbba0ad309 disabled=true
                        projected_action_0166 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6fcda735-26c0-5194-a71d-9e01e9305f2c disabled=true
                        projected_action_0167 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1e5fb40e-ee5f-5a9f-84c8-af310dcd46b1 disabled=true
                        projected_action_0168 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f2a68475-042f-5709-90b1-29e20b976c02 disabled=true
                        projected_action_0169 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P12"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f53993fa-e2f5-5d96-88d5-6f94cab4a443 disabled=true
                        projected_action_0170 = robot.move_to_point(
                            point_id_or_robot_name='P12',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/0/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d5b4f67a-9513-5000-9bee-98881d12cee3 disabled=true
                        projected_action_0171 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=14a9addb-cf60-5081-bd6a-c3381c731a27 disabled=true
                        projected_action_0172 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f002fcd1-7351-5050-990c-e0ac6a190fe5 disabled=true
                        projected_action_0173 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=84b4f5ab-1b8a-5abb-8306-a5db04460f8a disabled=true
                        projected_action_0174 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cfa1d724-81db-5e57-a2ba-457c6dd7c2af disabled=true
                        projected_action_0175 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=029db268-b6aa-5904-8c82-eb32439456cd disabled=true
                        projected_action_0176 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6e6defbc-458d-51df-8b8d-e8a0615fb7bf disabled=true
                        projected_action_0177 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/0/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=085f84a2-dc2e-5519-a4f6-aa1292ca9d9f disabled=true
                        projected_action_0178 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/0/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9ae07d79-7111-5267-8c03-ebc474939817 disabled=true
                        projected_action_0179 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 2（互斥分支）] robot_tank_put@body/3/elifs/1/body 的静态审阅分支。
                    # unilab:node_uuid=fe49aa71-f671-54ff-8f0a-ee2f9dbee929
                    with group(name='ELIF 2（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a9555ffa-e4f7-5de9-a1ed-b00fe2b7892b disabled=true
                        projected_action_0180 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d845fe2d-bcdd-53f2-98f8-0efac9a3a88a disabled=true
                        projected_action_0181 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bd4c0f8b-97bc-596b-a722-64b8ccd562ad disabled=true
                        projected_action_0182 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e1e8ba0d-3719-5c09-b94a-c3c0b0419220 disabled=true
                        projected_action_0183 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=35f4f505-435b-5993-9ab8-14580206510e disabled=true
                        projected_action_0184 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=558ca88f-5415-5eb9-9e1c-2d49b3f9889b disabled=true
                        projected_action_0185 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=def52bdb-3b18-58a0-bbd0-e2a34f164025 disabled=true
                        projected_action_0186 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f904f154-f37e-546d-862d-135a09f59ad9 disabled=true
                        projected_action_0187 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6b27ba67-4ca9-5e5f-91ee-accd89414714 disabled=true
                        projected_action_0188 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P13"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=067d3c38-721e-5637-bdb8-201414c5e879 disabled=true
                        projected_action_0189 = robot.move_to_point(
                            point_id_or_robot_name='P13',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/1/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9a39612b-557d-5d0a-8183-f88af45f4a1f disabled=true
                        projected_action_0190 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6e2a19c0-b736-51ef-9319-b8d8bd7ec5f8 disabled=true
                        projected_action_0191 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4128dcb5-842b-5ac3-bd22-c2042eddd404 disabled=true
                        projected_action_0192 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3fbeac34-1701-54e8-8d1e-54ec978c9fcf disabled=true
                        projected_action_0193 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=84fe39f6-72f6-5aef-95f2-fe13507675bd disabled=true
                        projected_action_0194 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2ce0d3a0-1035-5075-add9-a3a7b018b7fe disabled=true
                        projected_action_0195 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a65a31b1-f6ac-5cf9-a570-68fdba8bed8b disabled=true
                        projected_action_0196 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/1/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c7cea8aa-5b58-59ae-8b01-785ec6f037d8 disabled=true
                        projected_action_0197 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/1/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=df3de275-4b0f-5246-aaa6-cd91c07ef061 disabled=true
                        projected_action_0198 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 3（互斥分支）] robot_tank_put@body/3/elifs/2/body 的静态审阅分支。
                    # unilab:node_uuid=46855a9c-f17c-5b55-b4b2-31729039de6c
                    with group(name='ELIF 3（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1b3564fc-f46a-5f98-a472-abf248eafdb6 disabled=true
                        projected_action_0199 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=03c96484-7147-5072-b553-e5d07dc810c1 disabled=true
                        projected_action_0200 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/2/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d10ff2e5-6d27-55a0-a342-f413608b613a disabled=true
                        projected_action_0201 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c5e35efc-9a12-5128-b064-4532171ceeed disabled=true
                        projected_action_0202 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=244fb6f5-7018-5308-b997-dfe14020e34d disabled=true
                        projected_action_0203 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e28192e1-b9bf-5eb9-8368-1890739178a5 disabled=true
                        projected_action_0204 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5c12eb86-6d3c-5829-9286-836524b6dff8 disabled=true
                        projected_action_0205 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=54146c01-87b6-508e-b28f-06bd54945236 disabled=true
                        projected_action_0206 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6d16670c-f3fd-5cbc-a52b-4133a525825a disabled=true
                        projected_action_0207 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P14"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=754e3551-daae-585a-85cf-4b8a2ffc3021 disabled=true
                        projected_action_0208 = robot.move_to_point(
                            point_id_or_robot_name='P14',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/2/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2a366acc-3563-5432-b9c0-717b86bbd97a disabled=true
                        projected_action_0209 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1ff00e02-5db5-5d6d-80ba-66df389fcee9 disabled=true
                        projected_action_0210 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f8db46c5-f6a3-53b1-9f3d-4746e4631387 disabled=true
                        projected_action_0211 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=49aaea86-dad6-57d6-8ba6-1247825b6814 disabled=true
                        projected_action_0212 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f9ae1026-a95f-5729-9c4a-b9998432ff72 disabled=true
                        projected_action_0213 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8a07f7c4-7ded-592b-b4fe-1e979940a50c disabled=true
                        projected_action_0214 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=13ccb66a-3e10-5a24-ad86-4f836957c995 disabled=true
                        projected_action_0215 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/2/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ce3f7b16-ee47-5e88-831d-140a11d612bc disabled=true
                        projected_action_0216 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/2/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4e31fba6-896e-5d6b-b1f8-fbbde834f8ba disabled=true
                        projected_action_0217 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 4（互斥分支）] robot_tank_put@body/3/elifs/3/body 的静态审阅分支。
                    # unilab:node_uuid=f0da0364-7428-5810-a16a-7b8bed8025f2
                    with group(name='ELIF 4（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7bf9696c-ea40-52fb-b84d-773bcde04221 disabled=true
                        projected_action_0218 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=700a1258-22a4-5036-8b29-923331d085db disabled=true
                        projected_action_0219 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/3/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9155fd0e-438e-5735-9972-7a0d1c2bb05d disabled=true
                        projected_action_0220 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=584c17a7-a15f-5dc1-80f3-2715087c11a3 disabled=true
                        projected_action_0221 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9c77d695-2104-5a61-bf38-893841e56bf7 disabled=true
                        projected_action_0222 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7f54c6ae-80a8-535b-a231-c58b0a8e4b69 disabled=true
                        projected_action_0223 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=654c8527-c3a0-5a1c-8728-aceaf068981b disabled=true
                        projected_action_0224 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P15"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1edc846b-5e6c-5a0a-856b-e79dba41d122 disabled=true
                        projected_action_0225 = robot.move_to_point(
                            point_id_or_robot_name='P15',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/3/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=36ca3ce5-1c26-57b9-8291-00e75b396b64 disabled=true
                        projected_action_0226 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ce710300-90ab-5b7a-9320-87423c0d02ea disabled=true
                        projected_action_0227 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=eabed363-0325-5bd6-b893-8b353849e25a disabled=true
                        projected_action_0228 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=00afe299-c21b-53ae-ba2b-88c392eda382 disabled=true
                        projected_action_0229 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e672f57d-7c14-5e6d-b433-84d032752430 disabled=true
                        projected_action_0230 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/3/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cfb3a637-a85d-5237-989d-5323bdadf70e disabled=true
                        projected_action_0231 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/3/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4c190f9b-2402-5b62-81ac-acaf24aee1ed disabled=true
                        projected_action_0232 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 5（互斥分支）] robot_tank_put@body/3/elifs/4/body 的静态审阅分支。
                    # unilab:node_uuid=1d271963-7112-5147-b9ea-61a866c781c5
                    with group(name='ELIF 5（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=29e2d7b9-3f98-5ce6-abec-a2ce25d8fcce disabled=true
                        projected_action_0233 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2034db3c-5727-52e2-b84e-7a0d0b709d3f disabled=true
                        projected_action_0234 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/4/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6c90536d-1c8a-570c-bf63-518d5e7e490f disabled=true
                        projected_action_0235 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4aa8b8fd-be06-59a8-9387-8d511619aa2d disabled=true
                        projected_action_0236 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a17b0220-1aec-50bf-9fe1-3d2d73034bfd disabled=true
                        projected_action_0237 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8754825c-f309-53e7-a023-5034e6197047 disabled=true
                        projected_action_0238 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=16378de5-a3c8-5c6f-9013-0ffc95cbe0de disabled=true
                        projected_action_0239 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P16"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=72c124c8-43f6-5046-94f9-daa84df46c8b disabled=true
                        projected_action_0240 = robot.move_to_point(
                            point_id_or_robot_name='P16',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/4/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bbb4952f-7b37-5f5d-9239-bb384f27355e disabled=true
                        projected_action_0241 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9abe7d79-ed11-5f92-95ec-c44f6f3d507b disabled=true
                        projected_action_0242 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4dcecf30-943a-5239-8e2d-b0ddc2df36ab disabled=true
                        projected_action_0243 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0a69c62b-a8ce-5502-b136-5b294d1ba253 disabled=true
                        projected_action_0244 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d294e4a4-9b4f-5118-859b-d73ddc09a12e disabled=true
                        projected_action_0245 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/4/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=86f3976c-d85f-59e4-8fb1-01d8fe33b8c3 disabled=true
                        projected_action_0246 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/4/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7d4d9446-b29f-5eb1-b94d-f04b181457ca disabled=true
                        projected_action_0247 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 6（互斥分支）] robot_tank_put@body/3/elifs/5/body 的静态审阅分支。
                    # unilab:node_uuid=267a2b1c-651b-5666-991c-3f28b44b9cc6
                    with group(name='ELIF 6（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5d29fca6-7e58-5805-b9dd-2f0ed30b2a8a disabled=true
                        projected_action_0248 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=94d45e8b-7ddb-54af-96db-e48050a877f9 disabled=true
                        projected_action_0249 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/5/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f1967876-c301-5a43-ae90-d9c2327568c1 disabled=true
                        projected_action_0250 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b1986412-dcf7-5acc-852a-f10422eb4028 disabled=true
                        projected_action_0251 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=594c5549-ecc0-5590-af89-6ad55d951e6a disabled=true
                        projected_action_0252 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ef08523d-9a08-56e8-95a5-68a9c3957e91 disabled=true
                        projected_action_0253 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3790f5c1-45ca-5c16-82dd-e67f044aa81e disabled=true
                        projected_action_0254 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P17"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8e48b68b-e04d-501f-a365-1ed17be875e2 disabled=true
                        projected_action_0255 = robot.move_to_point(
                            point_id_or_robot_name='P17',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/5/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fde7a988-ccb7-59bf-b989-c7d75963826f disabled=true
                        projected_action_0256 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f473823d-122a-54cf-96dc-511503f263a1 disabled=true
                        projected_action_0257 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5538bd30-33d0-59a5-8bb2-71d448200dab disabled=true
                        projected_action_0258 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8efefe10-e46f-5bb2-83dc-4a3286542dc1 disabled=true
                        projected_action_0259 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=44dc7ef0-34a7-5bbe-8b8e-2d9824c5e709 disabled=true
                        projected_action_0260 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/5/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e9bbabca-00f1-502b-9ec9-3ab96a6d07e0 disabled=true
                        projected_action_0261 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/5/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a3b0c40f-03e6-5a43-b453-6f34c4f7743d disabled=true
                        projected_action_0262 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 7（互斥分支）] robot_tank_put@body/3/elifs/6/body 的静态审阅分支。
                    # unilab:node_uuid=99867e2a-6938-5c0f-9a02-02f64c55b9ab
                    with group(name='ELIF 7（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c9adcbaf-12c6-5896-9f0f-099e22fdf277 disabled=true
                        projected_action_0263 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_put@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=25ed362d-875c-529f-b78a-a5b8a7a32b01 disabled=true
                        projected_action_0264 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/6/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ec66c54f-de75-518c-8647-ebf409ef83dd disabled=true
                        projected_action_0265 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fa5fc7e4-a717-53ba-ac19-34887f8cb32c disabled=true
                        projected_action_0266 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b3bdf5cf-e20d-5b91-b6ea-59a5abdb6626 disabled=true
                        projected_action_0267 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e74b09a3-caf2-5959-af3d-846b8ea9f52c disabled=true
                        projected_action_0268 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=441c8e5c-cd77-5100-abb9-e8c0298360fd disabled=true
                        projected_action_0269 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P18"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=941b3f81-80b4-5de0-b860-59c202df948a disabled=true
                        projected_action_0270 = robot.move_to_point(
                            point_id_or_robot_name='P18',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_put@body/3/elifs/6/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3ca1c92d-da75-574e-9629-918b841d2142 disabled=true
                        projected_action_0271 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=663ab8d4-f0fb-5733-8224-f24fcf32964b disabled=true
                        projected_action_0272 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1a2da65f-7012-5df4-9306-88ad8377bf80 disabled=true
                        projected_action_0273 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6c18db73-611e-5913-a0a4-e2fa4c373527 disabled=true
                        projected_action_0274 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9b103681-b04d-5491-8d06-76275a38691f disabled=true
                        projected_action_0275 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_put@body/3/elifs/6/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5793b7cf-c6d4-5b5f-a825-5ac0906f673e disabled=true
                        projected_action_0276 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_put@body/3/elifs/6/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fefa367e-3374-5655-b1b1-7a228c486546 disabled=true
                        projected_action_0277 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_tank_put@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=f8b492ba-ee30-5f2f-b174-81dbd08163b5
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_tank_put@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"tank.put: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=858093fa-9021-5478-b564-a6b210805988
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_tank_put@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=b8d09be9-7d4b-5a75-a6c3-4ee4f5af17fd disabled=true
                            projected_control_0278 = material.review_control_node_v1(
                                operation_name='robot_tank_put',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='de61415eb83d471c2a3b728a840f3467de1f470c18605c1098d37289a9851744',
                            )
            # [CONTROL comment] 来源 develop_load@body/3；原节点 {"op":"comment","text":"load: 放板缸到动点, 完成入缸夹持"}
            # unilab:node_uuid=38b9c3fc-f5b3-5e8f-bc9f-21ff5928e259
            with group(name='说明 · load: 放板缸到动点, 完成入缸夹持'):
                # [VERIFY comment] 只读来源校验 develop_load@body/3；节点在本工作流中静态 disabled。
                # unilab:node_uuid=fe4656e6-21fa-58b7-a0a9-bd072cb1a8cc disabled=true
                projected_control_0279 = material.review_control_node_v1(
                    operation_name='develop_load',
                    node_path='body/3',
                    control_kind='comment',
                    expected_sha256='33e1f53125c648616fbd4e7a62aa6617558fea2a18a89afdfc7d05beea884fad',
                )
            # [ACTION develop.plate_extend] 来源 develop_load@body/4；原节点 {"action":"develop.plate_extend","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9bc28664-4215-5c5b-a067-df3a16e25eaf disabled=true
            projected_action_0280 = develop.plate_extend(
                target_tank=1,
            )
    # [EXECUTE ROOT pf_s5_to_tank] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=bc7d2f07-55d7-5483-a6c2-3551e670f41a
    execution = material.run_operation_review_v1(
        operation_name='pf_s5_to_tank',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        "before_path": execution.before_path,
        "collector_hole": execution.collector_hole,
        "bottle_hole": execution.bottle_hole,
    }
