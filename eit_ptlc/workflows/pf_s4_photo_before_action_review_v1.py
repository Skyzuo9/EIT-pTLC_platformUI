from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.unilab_domain.devices.plc_rail import PLCRail
from eit_ptlc.unilab_domain.devices.robot import RobotProxy
from eit_ptlc.unilab_domain.devices.plc_sampling import PLCSampling
from eit_ptlc.unilab_domain.devices.vision import VisionProxy


class PlatformOperationReviewV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    before_path: str
    collector_hole: int
    bottle_hole: int

material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')
sampling: PLCSampling = device('plc_sampling')
vision: VisionProxy = device('vision')


@workflow(
    workflow_uuid='234f5206-adbb-53b0-a3c5-2bddcd65d9a0',
    displayname='3 展开前拍照 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s4_photo_before_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s4_photo_before] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=86d009aa-9698-55d2-bb9c-76c5bc5d6fa4
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s4_photo_before@body/0；原节点 {"op":"comment","text":"unload: 松开点样定位并取板; 机器人持板 (段内在手, 不落边界)"}
        # unilab:node_uuid=e4345965-83a7-543d-b923-afcab0612f02
        with group(name='说明 · unload: 松开点样定位并取板; 机器人持板 (段内在手, 不落边界)'):
            # [VERIFY comment] 只读来源校验 pf_s4_photo_before@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=5f0183e8-b9c1-5207-a83e-c6c08f09c903 disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s4_photo_before',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='7556137ab575f0f3c3a611cffa18627baabca6737530cd497e40c14be7996467',
            )
        # [SUBWORKFLOW sampling_unload] 由 pf_s4_photo_before@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=6241e5ea-aa68-5b6a-8919-4c92ff2582ab
        with group(name='↳ sampling_unload'):
            # [CONTROL comment] 来源 sampling_unload@body/0；原节点 {"op":"comment","text":"unload: 松开定位夹具 -> 机器人从上样位取板; robot_suction_pick 末尾回 P1 并 require_anchor"}
            # unilab:node_uuid=2ef5c540-65d0-586c-8d69-337feb95f3b8
            with group(name='说明 · unload: 松开定位夹具 -> 机器人从上样位取板; robot_suction_pick 末尾回 P1 并'):
                # [VERIFY comment] 只读来源校验 sampling_unload@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=3782e62e-150b-5cb1-a1b1-b810f916e76e disabled=true
                projected_control_0002 = material.review_control_node_v1(
                    operation_name='sampling_unload',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='e32199707f27c99f7660635456603939b8c9c90696074927bfcae0750c96bc5c',
                )
            # [CONTROL comment] 来源 sampling_unload@body/1；原节点 {"op":"comment","text":"跨站自动运行时必须由 handoff(A -> B) 包裹; 机器人持板 home 不是可抢占空闲态"}
            # unilab:node_uuid=15eef51a-544c-596f-84b6-2ba71ce6750b
            with group(name='说明 · 跨站自动运行时必须由 handoff(A -> B) 包裹; 机器人持板 home 不是可抢占空闲态'):
                # [VERIFY comment] 只读来源校验 sampling_unload@body/1；节点在本工作流中静态 disabled。
                # unilab:node_uuid=a1c1f140-533c-5c9c-a9a4-d9319d31ecba disabled=true
                projected_control_0003 = material.review_control_node_v1(
                    operation_name='sampling_unload',
                    node_path='body/1',
                    control_kind='comment',
                    expected_sha256='25bc708652757982bd004b069ade76b535dc5798e7f030aca2238492a02d482c',
                )
            # [CONTROL comment] 来源 sampling_unload@body/2；原节点 {"op":"comment","text":"取板前先把 7Y 带板从喷涂位退回放板位, 使取/放同点 (机器人在 P19 取, 与放板同点); 必须先回位再松夹, 反之会在 7Y 行程中移/丢板"}
            # unilab:node_uuid=23398747-3b9d-5f6e-ad8a-f577f8555636
            with group(name='说明 · 取板前先把 7Y 带板从喷涂位退回放板位, 使取/放同点 (机器人在 P19 取, 与放板同点); 必须先回位再'):
                # [VERIFY comment] 只读来源校验 sampling_unload@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=ed7dfa33-af09-5912-b207-c818b800d3ec disabled=true
                projected_control_0004 = material.review_control_node_v1(
                    operation_name='sampling_unload',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='b5741b2c6e3a156f79e99e9298c66a9a85379569839be23075639e804e4d0838',
                )
            # [ACTION sampling.place_axis] 来源 sampling_unload@body/3；原节点 {"action":"sampling.place_axis","mode":"RUN","op":"call"}
            # unilab:node_uuid=3bcf988b-7fc9-5950-9d97-48d8cf6a3627 disabled=true
            projected_action_0005 = sampling.place_axis()
            # [ACTION sampling.place_release] 来源 sampling_unload@body/4；原节点 {"action":"sampling.place_release","mode":"RUN","op":"call"}
            # unilab:node_uuid=8ec0c11a-b584-5dd7-8b93-76f1d9f4d36c disabled=true
            projected_action_0006 = sampling.place_release()
            # [CONTROL comment] 来源 sampling_unload@body/5；原节点 {"op":"comment","text":"自守卫地轨在上样位(位1); 幂等, 使本 step 可单独点跑"}
            # unilab:node_uuid=e3031376-90ba-5165-9b82-b37555a45edb
            with group(name='说明 · 自守卫地轨在上样位(位1); 幂等, 使本 step 可单独点跑'):
                # [VERIFY comment] 只读来源校验 sampling_unload@body/5；节点在本工作流中静态 disabled。
                # unilab:node_uuid=db3aa05b-ee15-58cb-b4cd-a9f0f52aa7ed disabled=true
                projected_control_0007 = material.review_control_node_v1(
                    operation_name='sampling_unload',
                    node_path='body/5',
                    control_kind='comment',
                    expected_sha256='3a2032a34a7b8ee9aa6aa4a86dc8c970dc5af8d74e19b5de5fd63525583730c3',
                )
            # [SUBWORKFLOW rail_move_safe] 由 sampling_unload@body/6 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=9388870e-ef1c-5be9-9e87-52a8746d16fe
            with group(name='↳ rail_move_safe'):
                # [CONTROL comment] 来源 rail_move_safe@body/0；原节点 {"op":"comment","text":"确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)"}
                # unilab:node_uuid=fb3fd476-4e6a-5fd4-89bb-855f47baa299
                with group(name='说明 · 确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)'):
                    # [VERIFY comment] 只读来源校验 rail_move_safe@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=45109327-2315-5a58-93c6-8441b9c377fe disabled=true
                    projected_control_0008 = material.review_control_node_v1(
                        operation_name='rail_move_safe',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='cc629ec60964ec74a746185851e52069f3b991388ab52755ebea4f3b92ed1740',
                    )
                # [ACTION robot.home_ensure] 来源 rail_move_safe@body/1；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                # unilab:node_uuid=ad2bea02-f186-5a3d-932f-631d88d11ded disabled=true
                projected_action_0009 = robot.home_ensure()
                # [CONTROL comment] 来源 rail_move_safe@body/2；原节点 {"op":"comment","text":"安全位确认 -> 移动地轨到目标位"}
                # unilab:node_uuid=8923df09-330c-5efe-bdd1-cbe4ada45d86
                with group(name='说明 · 安全位确认 -> 移动地轨到目标位'):
                    # [VERIFY comment] 只读来源校验 rail_move_safe@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=092e52ac-e4da-5c35-be14-2e636ccf4c66 disabled=true
                    projected_control_0010 = material.review_control_node_v1(
                        operation_name='rail_move_safe',
                        node_path='body/2',
                        control_kind='comment',
                        expected_sha256='38f90a43c3043b67cd1207e8d94cd7c595a01ab69567c39518284d36ecb68702',
                    )
                # [ACTION rail.move] 来源 rail_move_safe@body/3；原节点 {"action":"rail.move","args":{"Rail_Target_Position":{"var":"target"}},"mode":"RUN","op":"call"}
                # unilab:node_uuid=39cbb879-d4a5-5a3d-8756-b19803acc665 disabled=true
                projected_action_0011 = rail.move(
                    Rail_Target_Position=1,
                )
            # [SUBWORKFLOW robot_suction_pick] 由 sampling_unload@body/7 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=dc61b1dd-cf89-5ddf-88de-ed9e37c24426
            with group(name='↳ robot_suction_pick'):
                # [CONTROL comment] 来源 robot_suction_pick@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                # unilab:node_uuid=e275091d-e97d-5bcc-93d8-7befb91b7a35
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                    # [VERIFY comment] 只读来源校验 robot_suction_pick@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=2febe64e-9a60-5549-aa9a-ab340e85eea4 disabled=true
                    projected_control_0012 = material.review_control_node_v1(
                        operation_name='robot_suction_pick',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                    )
                # [ACTION robot.home_ensure] 来源 robot_suction_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=b2b727c9-b2bf-56eb-929d-c1ed3ec469f2 disabled=true
                projected_action_0013 = robot.home_ensure()
                # [SUBWORKFLOW robot_tool_ensure] 由 robot_suction_pick@body/2 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=6a7ba4a1-c499-5d16-b1a3-7ae78e6724ca
                with group(name='↳ robot_tool_ensure'):
                    # [CONTROL comment] 来源 robot_tool_ensure@body/0；原节点 {"op":"comment","text":"读权威工具态 (mounted_tool 启动已从状态文件恢复","回显在 tool_state.mounted_tool)":null}
                    # unilab:node_uuid=3bc4f32b-3b78-5eff-ac07-668665112d42
                    with group(name='说明 · 读权威工具态 (mounted_tool 启动已从状态文件恢复'):
                        # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=fe59517d-f921-5d0b-90c4-c2324854cc2d disabled=true
                        projected_control_0014 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='d809e1de31eaaae6a28b91dfdc9f8587e53c48ce272668a1d7794e15c68d86f9',
                        )
                    # [ACTION robot.query] 来源 robot_tool_ensure@body/1；原节点 {"action":"robot.query","assign":{"var":"fb"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=7f435526-8436-576c-90a3-997e85e9cdb3 disabled=true
                    projected_action_0015 = robot.query()
                    # [CONTROL assign] 来源 robot_tool_ensure@body/2；原节点 {"op":"assign","target":{"var":"current"},"value":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"mounted_tool"}}
                    # unilab:node_uuid=a25fc681-fa22-5a65-8499-4a16ad7652ef
                    with group(name='变量赋值'):
                        # [VERIFY assign] 只读来源校验 robot_tool_ensure@body/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=7a233392-cf20-5a59-84c2-38d9f08f3f2d disabled=true
                        projected_control_0016 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/2',
                            control_kind='assign',
                            expected_sha256='0a8bed4ab1ed21eab44aa30c3cdc41f38a8147534c728fa885ef1da0ba3237c7',
                        )
                    # [CONTROL if] 来源 robot_tool_ensure@body/3；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"var":"needed"}},"op":"if","then":[{"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"},{"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"},{"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"r...
                    # unilab:node_uuid=ad9ef35b-0659-5944-8f17-4db187502e79
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=06d89967-5601-5ffc-9181-449e00e95f54 disabled=true
                        projected_control_0017 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/3',
                            control_kind='if',
                            expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                        )
                        # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then 的静态审阅分支。
                        # unilab:node_uuid=b09875f7-f119-5f78-9689-fd2487f08944
                        with group(name='THEN（互斥分支）'):
                            # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/0；原节点 {"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"}
                            # unilab:node_uuid=bc3c3cf6-8b71-5c8d-9a83-ad249e55eedf
                            with group(name='说明 · 当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标'):
                                # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=161b9dd9-915c-5f3d-a3e7-a9b1fe29485c disabled=true
                                projected_control_0018 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/0',
                                    control_kind='comment',
                                    expected_sha256='f1c1621fc9a3af0fead9abddfba4acc6d628c4e07f02d5e1d6e79342f780d4b5',
                                )
                            # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/1；原节点 {"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"}
                            # unilab:node_uuid=e09f5b73-c828-520b-aa87-6539171720f9
                            with group(name='说明 · 卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止'):
                                # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/1；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=01b01967-2cb4-58c2-a7ad-8fce06a692f0 disabled=true
                                projected_control_0019 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/1',
                                    control_kind='comment',
                                    expected_sha256='ab6b298fa1974e89ffba98e42a169ccd9b213ac1a03a6723584be2b1be7e6898',
                                )
                            # [CONTROL if] 来源 robot_tool_ensure@body/3/then/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"right":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"suction_on"}},"op":"if","then":[{"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}]}
                            # unilab:node_uuid=d75f438e-117e-58f9-bac1-2d60823c09e2
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=dbdba9b2-f886-58b0-bcb6-49c9a668e7bc disabled=true
                                projected_control_0020 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/2',
                                    control_kind='if',
                                    expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                )
                                # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/2/then 的静态审阅分支。
                                # unilab:node_uuid=cf205aa7-b6d4-5ce6-9b56-346c5dc31040
                                with group(name='THEN（互斥分支）'):
                                    # [CONTROL raise] 来源 robot_tool_ensure@body/3/then/2/then/0；原节点 {"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}
                                    # unilab:node_uuid=ca282082-210c-5501-a357-ebaeec4020f9
                                    with group(name='抛出流程错误'):
                                        # [VERIFY raise] 只读来源校验 robot_tool_ensure@body/3/then/2/then/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=caa5738b-12e3-5f70-96ba-f44911c2a580 disabled=true
                                        projected_control_0021 = material.review_control_node_v1(
                                            operation_name='robot_tool_ensure',
                                            node_path='body/3/then/2/then/0',
                                            control_kind='raise',
                                            expected_sha256='8ade635dfc3c21601ac8fa50ba7a168191332f67cbf70e021465f2765df9b23f',
                                        )
                                # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/2/else 的静态审阅分支。
                                # unilab:node_uuid=5dadecce-cf4b-5f9d-a43d-0079b816a283
                                with group(name='ELSE（互斥分支）'):
                                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=6655ec45-1583-590d-bf87-d7dfd55fcb6f disabled=true
                                    projected_control_0022 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/2',
                                        control_kind='if',
                                        expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                    )
                            # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 robot_tool_ensure@body/3/then/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=7b2829ed-b2b5-5676-80d6-b1461707ede6 disabled=true
                            projected_control_0023 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/3',
                                control_kind='run_script',
                                expected_sha256='a71d68a21f68d19b7cde73b5c95737ce6077a1b162074653e98fadbcdf8c69f9',
                            )
                            # [CONTROL if] 来源 robot_tool_ensure@body/3/then/4；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"lit":0}},"op":"if","then":[{"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}]}
                            # unilab:node_uuid=73222fe4-2dc3-5a19-b701-a37b148b275b
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=9612c29f-4014-5ef9-9550-8492989f630f disabled=true
                                projected_control_0024 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/4',
                                    control_kind='if',
                                    expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                )
                                # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/4/then 的静态审阅分支。
                                # unilab:node_uuid=262809b0-1fcc-59a0-9b1f-2ee592dfe4bd
                                with group(name='THEN（互斥分支）'):
                                    # [SUBWORKFLOW robot_tool_put] 由 robot_tool_ensure@body/3/then/4/then/0 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                    # unilab:node_uuid=66432934-534e-5029-bea0-3f3ea5c794ff
                                    with group(name='↳ robot_tool_put'):
                                        # [CONTROL if] 来源 robot_tool_put@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit...
                                        # unilab:node_uuid=3d0e1a5d-6b8e-55d2-b02f-736ba14376bd
                                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                                            # [VERIFY if] 只读来源校验 robot_tool_put@body/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=cd11cd46-31ae-565d-b36b-a6346be08ec5 disabled=true
                                            projected_control_0025 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0',
                                                control_kind='if',
                                                expected_sha256='9c64b805f035e287559b6a10c2883f201fed2852028900bfd6c9c7526352d298',
                                            )
                                            # [BRANCH THEN（互斥分支）] robot_tool_put@body/0/then 的静态审阅分支。
                                            # unilab:node_uuid=39c0f9b1-146e-500c-aabf-6917c30f5b1e
                                            with group(name='THEN（互斥分支）'):
                                                # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=384cdd47-07bc-5946-9991-916aa7f7966a disabled=true
                                                projected_action_0026 = robot.require_anchor(
                                                    point_id='robot-main.home',
                                                )
                                                # [ACTION rail.ensure] 来源 robot_tool_put@body/0/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=de7fed8c-dec7-502d-9007-a42ec35e7730 disabled=true
                                                projected_action_0027 = rail.ensure(
                                                    Rail_Target_Position=4,
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=cad1f09b-a1ab-5a1f-8ad7-35435261d920 disabled=true
                                                projected_action_0028 = robot.tool_action(
                                                    action='rotary-down',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=642d8a95-9a20-598b-b316-b62247608ebd disabled=true
                                                projected_action_0029 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=222d7e86-61e4-50af-87cd-c92f46065179 disabled=true
                                                projected_action_0030 = robot.tool_action(
                                                    action='tool-change-aux-on',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=4978f08d-2baa-5145-a106-ce9a4a90fc4e disabled=true
                                                projected_action_0031 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=18f04935-9338-5b8e-9b71-1b52862dfb7b disabled=true
                                                projected_action_0032 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=9c7a7187-3fbf-5ff4-8f4c-82b10f22fdd0 disabled=true
                                                projected_action_0033 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=92c17bd5-429a-5a39-86bc-bc26f2ecf0f9 disabled=true
                                                projected_action_0034 = robot.tool_action(
                                                    action='quick-change-release',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/9；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=6ed4d3d2-704f-565a-af91-f39d2fa1ba74 disabled=true
                                                projected_action_0035 = robot.tool_action(
                                                    action='tool-change-aux-off',
                                                )
                                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/then/10；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=c32114a9-c455-50b4-b066-a8c8003580db disabled=true
                                                projected_action_0036 = robot.set_mounted_tool(
                                                    tool_id='0',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=3bca4a4a-cf12-5d6b-a32f-aadef33ecb3d disabled=true
                                                projected_action_0037 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=2294fee8-d805-50cb-aac3-3d86ffedce87 disabled=true
                                                projected_action_0038 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                                )
                                            # [BRANCH ELIF 1（互斥分支）] robot_tool_put@body/0/elifs/0/body 的静态审阅分支。
                                            # unilab:node_uuid=add73229-6688-5f8c-9ef7-4ca1526de985
                                            with group(name='ELIF 1（互斥分支）'):
                                                # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=627cb87e-086f-562a-b100-08b594eb3447 disabled=true
                                                projected_action_0039 = robot.require_anchor(
                                                    point_id='robot-main.home',
                                                )
                                                # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=a4d481cd-f6a0-5eef-9e16-da811b7fa623 disabled=true
                                                projected_action_0040 = rail.ensure(
                                                    Rail_Target_Position=4,
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=c581a368-d0b3-52a0-899f-5a38d5b5dac1 disabled=true
                                                projected_action_0041 = robot.tool_action(
                                                    action='gripper-close',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=cab044d2-dd55-55f1-b829-f38c2d82ede1 disabled=true
                                                projected_action_0042 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=6b794323-0f02-5058-9696-9a0c7b7ea7a9 disabled=true
                                                projected_action_0043 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=639da4f0-b478-51af-ac27-ce6aade1cfd8 disabled=true
                                                projected_action_0044 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=4d82e613-4cfc-510d-9ca0-d0f614130483 disabled=true
                                                projected_action_0045 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=fc918f65-33f9-52d5-ba16-7afeb132c8b8 disabled=true
                                                projected_action_0046 = robot.tool_action(
                                                    action='quick-change-release',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=151db33d-1ad0-5e67-89ad-5b6cc8366a20 disabled=true
                                                projected_action_0047 = robot.tool_action(
                                                    action='tool-change-aux-off',
                                                )
                                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/0/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=7583eee2-8937-595a-8e1d-262a7df98348 disabled=true
                                                projected_action_0048 = robot.set_mounted_tool(
                                                    tool_id='0',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=6503e351-23b3-5790-be7e-12f6fc71ba6c disabled=true
                                                projected_action_0049 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=8d8a5e9d-eb10-51bc-a851-138e9b46c2ec disabled=true
                                                projected_action_0050 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                                )
                                            # [BRANCH ELIF 2（互斥分支）] robot_tool_put@body/0/elifs/1/body 的静态审阅分支。
                                            # unilab:node_uuid=f24604c0-2670-5a58-a28b-3e9235cb3681
                                            with group(name='ELIF 2（互斥分支）'):
                                                # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=8a2f51f2-600c-55a5-a43d-53748cb29e77 disabled=true
                                                projected_action_0051 = robot.require_anchor(
                                                    point_id='robot-main.home',
                                                )
                                                # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=9efe9c3b-4850-5388-8918-29366cfcabe8 disabled=true
                                                projected_action_0052 = rail.ensure(
                                                    Rail_Target_Position=4,
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=bce26cd4-9b1d-5955-a799-1053c5315349 disabled=true
                                                projected_action_0053 = robot.tool_action(
                                                    action='gripper-close',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=1e8e3a46-b7f2-56b5-9032-7d6aea5505ce disabled=true
                                                projected_action_0054 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=c0a81448-6d57-5d9a-902a-ce0631cfb758 disabled=true
                                                projected_action_0055 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=72a9c1f7-46b8-56c1-bb80-6b4f05773489 disabled=true
                                                projected_action_0056 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=bea1e893-42cc-5824-91b8-5c54a8773f0d disabled=true
                                                projected_action_0057 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=4f82b41d-5bc3-5cec-a197-b82f6c5c0173 disabled=true
                                                projected_action_0058 = robot.tool_action(
                                                    action='quick-change-release',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=3fa6d963-62e5-5141-aea1-e14c360f7b48 disabled=true
                                                projected_action_0059 = robot.tool_action(
                                                    action='tool-change-aux-off',
                                                )
                                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/1/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=d7d148f7-9b4f-503a-b51d-d16018e68a55 disabled=true
                                                projected_action_0060 = robot.set_mounted_tool(
                                                    tool_id='0',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=e29c7602-e4b9-55dd-8456-c3ba26a91f9d disabled=true
                                                projected_action_0061 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=faf07b99-6423-5072-9364-0cafe4c81134 disabled=true
                                                projected_action_0062 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                                )
                                            # [BRANCH ELSE（互斥分支）] robot_tool_put@body/0/else 的静态审阅分支。
                                            # unilab:node_uuid=73aec211-d32d-5f66-829d-41ee145ff6e0
                                            with group(name='ELSE（互斥分支）'):
                                                # [FLATTENED CONTROL raise] 只读来源校验 robot_tool_put@body/0/else/0；节点在本工作流中静态 disabled。
                                                # unilab:node_uuid=5f9367f7-d6ef-5083-a65b-803c0aa78659 disabled=true
                                                projected_control_0063 = material.review_control_node_v1(
                                                    operation_name='robot_tool_put',
                                                    node_path='body/0/else/0',
                                                    control_kind='raise',
                                                    expected_sha256='8aa6aa6f749c6777b2a7040e04f4316dd03cc80d36de51eec476b3dbb6c6de75',
                                                )
                                # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/4/else 的静态审阅分支。
                                # unilab:node_uuid=0391e787-ca6a-5056-8edb-1fef3431cf73
                                with group(name='ELSE（互斥分支）'):
                                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=27f3223f-ed06-5e82-878d-931fa9253190 disabled=true
                                    projected_control_0064 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/4',
                                        control_kind='if',
                                        expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                    )
                            # [SUBWORKFLOW robot_tool_pick] 由 robot_tool_ensure@body/3/then/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                            # unilab:node_uuid=1a910402-33d1-513e-a496-07a60d5987b5
                            with group(name='↳ robot_tool_pick'):
                                # [CONTROL if] 来源 robot_tool_pick@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"},{"action":"robot.move...
                                # unilab:node_uuid=43bf4f28-7235-5887-857b-b9c68c45d93f
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_tool_pick@body/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=79370cf8-fb92-5515-9bef-f0d2708cef79 disabled=true
                                    projected_control_0065 = material.review_control_node_v1(
                                        operation_name='robot_tool_pick',
                                        node_path='body/0',
                                        control_kind='if',
                                        expected_sha256='47a5b48eb2b065101041caadd225ef492b21028bb19039ac3a19991997da1895',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_tool_pick@body/0/then 的静态审阅分支。
                                    # unilab:node_uuid=e3d775ce-ef97-5b59-b2e4-7c291e2d03be
                                    with group(name='THEN（互斥分支）'):
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=00d9bb6f-1110-55c9-b12e-18450bbaf188 disabled=true
                                        projected_action_0066 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=3d982217-14a6-5446-933b-b9071a36b550 disabled=true
                                        projected_action_0067 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=44a260e9-c59c-50b8-bbd7-a70aaeceafea disabled=true
                                        projected_action_0068 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=f993fcd3-805e-5c09-b307-2e1a6ea88f2a disabled=true
                                        projected_action_0069 = robot.tool_action(
                                            action='quick-change-lock',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/then/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":1}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=a70aa280-5c26-521c-ae45-e720ac1bc794 disabled=true
                                        projected_action_0070 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=6e7663ee-1192-583c-bca4-acaaebfbbf22 disabled=true
                                        projected_action_0071 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=3d938640-53fa-5f86-9de5-9b3406a47e75 disabled=true
                                        projected_action_0072 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=9945c4d1-4fdf-5a9f-bd34-b85015be00c7 disabled=true
                                        projected_action_0073 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=2693eea7-f8aa-57e7-a151-0490c8fd5f88 disabled=true
                                        projected_action_0074 = robot.dwell(
                                            duration_ms=500,
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=0055a6ca-3115-57cf-98f2-3aa1eb0263f2 disabled=true
                                        projected_action_0075 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.home',
                                        )
                                        # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=3f71a95e-5a23-5f14-9f38-201ba44c747f disabled=true
                                        projected_action_0076 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                    # [BRANCH ELIF 1（互斥分支）] robot_tool_pick@body/0/elifs/0/body 的静态审阅分支。
                                    # unilab:node_uuid=198c931d-f44a-57a7-9325-7606d3904955
                                    with group(name='ELIF 1（互斥分支）'):
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=0e75928b-3fc3-5930-9eac-ce99f86d816a disabled=true
                                        projected_action_0077 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=e57ab10a-fb1f-57a4-866b-0b6f726b320c disabled=true
                                        projected_action_0078 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=ae6cd287-a7b6-562c-abf1-168dbdfde02b disabled=true
                                        projected_action_0079 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=230f1b88-f171-5a82-878d-aa635fd27810 disabled=true
                                        projected_action_0080 = robot.tool_action(
                                            action='quick-change-lock',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/0/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":2}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=e2896a6f-a654-510e-9ef6-5970b7ff6ce0 disabled=true
                                        projected_action_0081 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=24fa38f4-e471-59e9-a8b3-6b3b1d7cd465 disabled=true
                                        projected_action_0082 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=968826f8-dba6-50f8-a3eb-51c7106764b8 disabled=true
                                        projected_action_0083 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=f38a28af-8be9-5a27-a0ff-04e0058b3900 disabled=true
                                        projected_action_0084 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/0/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=12c23ac5-5a6e-542b-8582-29f3980dd0cf disabled=true
                                        projected_action_0085 = robot.dwell(
                                            duration_ms=500,
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=5daaf576-1995-54e0-9546-b54c8e025bc7 disabled=true
                                        projected_action_0086 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.home',
                                        )
                                        # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=30011862-3a6d-5f4f-9e87-fcaeebe8d01c disabled=true
                                        projected_action_0087 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                    # [BRANCH ELIF 2（互斥分支）] robot_tool_pick@body/0/elifs/1/body 的静态审阅分支。
                                    # unilab:node_uuid=6dae712a-126d-5098-b271-6bb082fdd9d6
                                    with group(name='ELIF 2（互斥分支）'):
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=887e2f85-0f86-56eb-b975-e4245919361e disabled=true
                                        projected_action_0088 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=c62c311a-21ac-5d7a-a4d1-5078148a55a8 disabled=true
                                        projected_action_0089 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=83bc3501-0116-5c47-b1ef-4bfb1ad47e11 disabled=true
                                        projected_action_0090 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/1/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=90d3c6eb-3dfd-5417-837c-c6b2c24c2f8a disabled=true
                                        projected_action_0091 = robot.tool_action(
                                            action='quick-change-lock',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/1/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":3}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=308edee3-c314-5ae8-a719-dc553cc56820 disabled=true
                                        projected_action_0092 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=dcb13a5e-4f72-5a4e-9f5f-dc10440e75e0 disabled=true
                                        projected_action_0093 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=7f863073-700d-599e-b33e-ab807652af51 disabled=true
                                        projected_action_0094 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=27638e19-653f-538a-9000-b88a1d25f136 disabled=true
                                        projected_action_0095 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/1/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=fba4818c-2adf-585f-a852-05f784f5f26d disabled=true
                                        projected_action_0096 = robot.dwell(
                                            duration_ms=500,
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=2e90d6a5-8408-5b4c-ab81-284f11e9436a disabled=true
                                        projected_action_0097 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.home',
                                        )
                                        # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=e53e4b6b-6f32-5553-9ec8-976b6eb62810 disabled=true
                                        projected_action_0098 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                    # [BRANCH ELSE（互斥分支）] robot_tool_pick@body/0/else 的静态审阅分支。
                                    # unilab:node_uuid=d33226c1-1b92-5ea8-9eb1-4c237c31da1e
                                    with group(name='ELSE（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_tool_pick@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"tool.pick: 无效选择值"},"op":"raise"}
                                        # unilab:node_uuid=08846620-fc60-5a56-b52a-5b7d35114bc7
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_tool_pick@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=1649dec8-a10d-5762-8c05-0ed06ac5e984 disabled=true
                                            projected_control_0099 = material.review_control_node_v1(
                                                operation_name='robot_tool_pick',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='70c2a7e291023e9375102dc659639ba2604e87ffa8a3a94cca033c80b83c21e8',
                                            )
                        # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/else 的静态审阅分支。
                        # unilab:node_uuid=aa76cb04-a8e0-531b-a087-7448ec21c0ef
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=d520d215-d1b3-5b0b-bf2d-310e4e5768e1 disabled=true
                            projected_control_0100 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3',
                                control_kind='if',
                                expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                            )
                # [CONTROL if] 来源 robot_suction_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"spotting"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"...
                # unilab:node_uuid=b2e59ab3-7f89-5471-8e05-731994f86126
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_suction_pick@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=aaa40b37-7450-5eb2-afbe-5e6bf3563f64 disabled=true
                    projected_control_0101 = material.review_control_node_v1(
                        operation_name='robot_suction_pick',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='7cf59bced5f5b2dcd49557f999dbd90eb52637f34cb412ab2176135f0e83d084',
                    )
                    # [BRANCH THEN（互斥分支）] robot_suction_pick@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=46016ad2-d32a-5797-8e4c-7e1ba0804838
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3d8fb08f-da54-50ca-bf88-006e8a91ff8a disabled=true
                        projected_action_0102 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f9ad0eb1-2cb7-5e33-8ab6-b5ec7eb7c320 disabled=true
                        projected_action_0103 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7330b14e-cc8e-53c2-b33a-4822b4ec92be disabled=true
                        projected_action_0104 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1b2a6ade-9396-51b7-839b-07b5d27f7870 disabled=true
                        projected_action_0105 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ab76c7e7-3129-5d19-a58c-3b8eac8f9b72 disabled=true
                        projected_action_0106 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=51cbd5a2-4787-50e4-91fe-8d3709d6dc42 disabled=true
                        projected_action_0107 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P19"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=70e6204d-a669-5f67-8d49-a225b1126849 disabled=true
                        projected_action_0108 = robot.move_to_point(
                            point_id_or_robot_name='P19',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c2c8fcd6-40ad-5eb4-b0b7-931f6ab97cfd disabled=true
                        projected_action_0109 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e39f6772-051a-54f4-bec6-a34481bbffd9 disabled=true
                        projected_action_0110 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e9800136-abbd-5c6c-9d52-ef14330513dd disabled=true
                        projected_action_0111 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2aa4d67b-6724-53ac-b15c-679527f611ab disabled=true
                        projected_action_0112 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=986d71eb-3ea8-5470-87e5-534702eb220d disabled=true
                        projected_action_0113 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/then/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b7f44eb1-6e2c-586f-962a-26cc2c6f4d22 disabled=true
                        projected_action_0114 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_suction_pick@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=b5442a94-872e-5696-97aa-e294305dc0be
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b3db2ac2-b6d1-59a0-af13-4090a5206364 disabled=true
                        projected_action_0115 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f4d11457-2f82-5a9e-b68c-8f6ffbbe9a09 disabled=true
                        projected_action_0116 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a539d37b-7e60-5f44-8784-7aa279f90c98 disabled=true
                        projected_action_0117 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=09629774-e4b5-5fbc-8d05-8179fc132074 disabled=true
                        projected_action_0118 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c5c22455-8ecf-52ad-9099-3fdc70ce42b2 disabled=true
                        projected_action_0119 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0055d6a2-9a5b-5457-9b42-b5f5b9a07b0e disabled=true
                        projected_action_0120 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_pick@body/3/elifs/0/body/6；原节点 {"op":"comment","text":"刮板位取/放同基点: 取板与放板同点 P65 (吸附基准=板中心); P64 弃用保留在点表, 勿再引用"}
                        # unilab:node_uuid=c3705d5c-b22a-5253-8a6d-5c8556b81bf2
                        with group(name='说明 · 刮板位取/放同基点: 取板与放板同点 P65 (吸附基准=板中心); P64 弃用保留在点表, 勿再引用'):
                            # [VERIFY comment] 只读来源校验 robot_suction_pick@body/3/elifs/0/body/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=7e5da65f-ed09-522b-9f3d-b0bb37a2e048 disabled=true
                            projected_control_0121 = material.review_control_node_v1(
                                operation_name='robot_suction_pick',
                                node_path='body/3/elifs/0/body/6',
                                control_kind='comment',
                                expected_sha256='ce61ff1eddd64c4a26507b7df53f7a45d978ed30161b8ea6895afc3afcafc7bc',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P65"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=86ceed4a-72bf-5d70-a33f-93926d3133d5 disabled=true
                        projected_action_0122 = robot.move_to_point(
                            point_id_or_robot_name='P65',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0e3e29a3-6f83-583a-9dd7-6ae040d7b065 disabled=true
                        projected_action_0123 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5d1635f4-700d-5a36-acdf-3646453551d7 disabled=true
                        projected_action_0124 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7a81f436-dc47-5585-9e44-8d94b5d25d43 disabled=true
                        projected_action_0125 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=92ca3572-1032-5409-a734-6715f1247e0a disabled=true
                        projected_action_0126 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [CONTROL comment] 来源 robot_suction_pick@body/3/elifs/0/body/12；原节点 {"op":"comment","text":"Safety fix: after scraping pick, confirm rotary-up only after retreating to P63."}
                        # unilab:node_uuid=aac37844-e1c2-5509-878f-ce7f9a49be21
                        with group(name='说明 · Safety fix: after scraping pick, confirm rotary-up only '):
                            # [VERIFY comment] 只读来源校验 robot_suction_pick@body/3/elifs/0/body/12；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=aadcc525-ec05-5121-a74c-0b2c639d9ba1 disabled=true
                            projected_control_0127 = material.review_control_node_v1(
                                operation_name='robot_suction_pick',
                                node_path='body/3/elifs/0/body/12',
                                control_kind='comment',
                                expected_sha256='0c6391714e618a81ff71411339cb422212bba6d05a807e18d569fcabaea39c2f',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ca6e0383-1dfd-53bc-b4fb-45501f3bc734 disabled=true
                        projected_action_0128 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9341e6be-951b-5d9a-bf0c-d838ea8f753e disabled=true
                        projected_action_0129 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/elifs/0/body/15；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=91850b11-1f70-5883-b832-6d1d77b64585 disabled=true
                        projected_action_0130 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_suction_pick@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=ee29af2d-215a-5bad-97c2-87c8322f502c
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_suction_pick@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"suction.pick: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=f3cbaad2-261f-5ba6-a9ba-5679a42e2292
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_suction_pick@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=cc672072-7206-5f46-9fa1-9a7f78af2ce8 disabled=true
                            projected_control_0131 = material.review_control_node_v1(
                                operation_name='robot_suction_pick',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='7324ece78b8e478b8be13e31abd1d3bdbbc53d99d674cd9200fe986e9b80917f',
                            )
        # [CONTROL comment] 来源 pf_s4_photo_before@body/2；原节点 {"op":"comment","text":"刮板侧准备 + 板上料 (地轨到拍照区位2由 plate_load 自管; 位1≡位2=168mm 实为零位移)"}
        # unilab:node_uuid=cf14b6ab-070b-5ce6-a304-b0307eb54329
        with group(name='说明 · 刮板侧准备 + 板上料 (地轨到拍照区位2由 plate_load 自管; 位1≡位2=168mm 实为零位移)'):
            # [VERIFY comment] 只读来源校验 pf_s4_photo_before@body/2；节点在本工作流中静态 disabled。
            # unilab:node_uuid=9f898080-a40a-5170-b38f-76f81f134bfe disabled=true
            projected_control_0132 = material.review_control_node_v1(
                operation_name='pf_s4_photo_before',
                node_path='body/2',
                control_kind='comment',
                expected_sha256='a01247dbcca231c98a788bd800044681bdb3162817b6b3423f70747345bd359e',
            )
        # [SUBWORKFLOW photoscrape_prepare] 由 pf_s4_photo_before@body/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=18dd63a9-c31e-5fa1-b7d7-bf1bf60bd199
        with group(name='↳ photoscrape_prepare'):
            # [CONTROL comment] 来源 photoscrape_prepare@body/0；原节点 {"op":"comment","text":"prepare: 工位初始化; 每次受板前复位, 真机验收双访 init 是否需去重"}
            # unilab:node_uuid=4620b729-3c86-5b6f-9bb4-70f799eb1d7c
            with group(name='说明 · prepare: 工位初始化; 每次受板前复位, 真机验收双访 init 是否需去重'):
                # [VERIFY comment] 只读来源校验 photoscrape_prepare@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=7c501163-13f5-5463-868f-ea5d7cad7a7a disabled=true
                projected_control_0133 = material.review_control_node_v1(
                    operation_name='photoscrape_prepare',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='3a6a45c54d35018d37f1e0c76f494eab38f439747ec068d11e3717c8eccd5bb4',
                )
            # [ACTION photoscrape.init] 来源 photoscrape_prepare@body/1；原节点 {"action":"photoscrape.init","mode":"RUN","op":"call"}
            # unilab:node_uuid=5c1baa72-333f-5afb-9deb-e7a27399a634 disabled=true
            projected_action_0134 = photoscrape.init()
            # [CONTROL comment] 来源 photoscrape_prepare@body/2；原节点 {"op":"comment","text":"prepare: 刮板X到放板位335, 让位机器人放板"}
            # unilab:node_uuid=8a1b9c7f-d701-505d-9db7-f45c17037e2f
            with group(name='说明 · prepare: 刮板X到放板位335, 让位机器人放板'):
                # [VERIFY comment] 只读来源校验 photoscrape_prepare@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=df7e878e-ab29-5877-ac88-19c2a5e7fe61 disabled=true
                projected_control_0135 = material.review_control_node_v1(
                    operation_name='photoscrape_prepare',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='c308c06b8cdeb95bb13c30d2e20a936da35461395f6a00075a1f403dc14b2ff5',
                )
            # [ACTION photoscrape.cam_x335] 来源 photoscrape_prepare@body/3；原节点 {"action":"photoscrape.cam_x335","mode":"RUN","op":"call"}
            # unilab:node_uuid=2e5484be-4325-526d-85b9-e6e1755b7ccc disabled=true
            projected_action_0136 = photoscrape.cam_x335()
        # [SUBWORKFLOW photoscrape_plate_load] 由 pf_s4_photo_before@body/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=3a8c2179-2720-5688-941a-e0c4a406aa27
        with group(name='↳ photoscrape_plate_load'):
            # [CONTROL comment] 来源 photoscrape_plate_load@body/0；原节点 {"op":"comment","text":"plate/load: 机器人已持板; 先安全建立刮板拍照位(位2)地轨窗口"}
            # unilab:node_uuid=b4a423b3-e675-5662-a035-1008f19b4a8d
            with group(name='说明 · plate/load: 机器人已持板; 先安全建立刮板拍照位(位2)地轨窗口'):
                # [VERIFY comment] 只读来源校验 photoscrape_plate_load@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=8a5941eb-4e8f-5148-8713-cbb622950470 disabled=true
                projected_control_0137 = material.review_control_node_v1(
                    operation_name='photoscrape_plate_load',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='c09130d84bbc0959a4a189ffdb8721d9f926ee10327f2fc574ae06c38494b205',
                )
            # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 photoscrape_plate_load@body/1；节点在本工作流中静态 disabled。
            # unilab:node_uuid=2181f44b-fe67-56cc-84b8-9cf318961a1f disabled=true
            projected_control_0138 = material.review_control_node_v1(
                operation_name='photoscrape_plate_load',
                node_path='body/1',
                control_kind='run_script',
                expected_sha256='3375626c6140464d00aa9cbdffc04532e0598412bbb03a5cdc11186253b17bd1',
            )
            # [CONTROL comment] 来源 photoscrape_plate_load@body/2；原节点 {"op":"comment","text":"plate/load: 机器人放板 持板->刮板"}
            # unilab:node_uuid=fb4cbecf-7c1a-5411-8534-8d8fb248e7b3
            with group(name='说明 · plate/load: 机器人放板 持板->刮板'):
                # [VERIFY comment] 只读来源校验 photoscrape_plate_load@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=8cc0eff8-ccdd-5cf7-a789-5ba5831eb6be disabled=true
                projected_control_0139 = material.review_control_node_v1(
                    operation_name='photoscrape_plate_load',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='1dab2be17eeb939e5f05cdda6abab036c1e8bc8d8abe8d03343004ba23e6ed8b',
                )
            # [SUBWORKFLOW robot_suction_put] 由 photoscrape_plate_load@body/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=98fffdb7-6c98-57c4-84ff-2b4a6c1d27c9
            with group(name='↳ robot_suction_put'):
                # [CONTROL comment] 来源 robot_suction_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                # unilab:node_uuid=1cc96670-2f7a-51a8-beb2-4335537071fd
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                    # [VERIFY comment] 只读来源校验 robot_suction_put@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=e8084f83-3fbb-55e6-a4dd-ff782737094c disabled=true
                    projected_control_0140 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                    )
                # [ACTION robot.home_ensure] 来源 robot_suction_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=32afedb8-bd4d-5b4f-87b4-ec38994bbe2f disabled=true
                projected_action_0141 = robot.home_ensure()
                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_suction_put@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=70d2ce46-44e4-56bb-bd55-2c6643128fbe disabled=true
                projected_control_0142 = material.review_control_node_v1(
                    operation_name='robot_suction_put',
                    node_path='body/2',
                    control_kind='run_script',
                    expected_sha256='6248fd65698183b23b0962f697364ce4f9a7187fdfd05d12bfc8d8f678e645b1',
                )
                # [CONTROL if] 来源 robot_suction_put@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"spotting"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}...
                # unilab:node_uuid=a57667c6-33ff-5a9e-bd44-0ca615e3602a
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=a968719c-16d9-5d94-902a-95a1eff11992 disabled=true
                    projected_control_0143 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='c6e01866d4b84eab4021c0d16f3f62c88f5591b3d547740457d335c5752f77cc',
                    )
                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=0e814f99-b052-5fab-af5b-3c96490aaa20
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=99a1649c-fee8-5898-a051-3c27bb980be9 disabled=true
                        projected_action_0144 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3d3610e3-421f-59c5-893f-8368524f64e7 disabled=true
                        projected_action_0145 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4af58e91-6205-51b1-9591-cf80b87cd79a disabled=true
                        projected_action_0146 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ece63f29-e448-51e2-b4e1-d9ed1f5215aa disabled=true
                        projected_action_0147 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/4；原节点 {"op":"comment","text":"视觉拍照 photo"}
                        # unilab:node_uuid=4d3fc95f-4a34-5773-b04b-8cc4b37f369b
                        with group(name='说明 · 视觉拍照 photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=0bad38b3-e56d-5928-8c98-566a3d678d2d disabled=true
                            projected_control_0148 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/4',
                                control_kind='comment',
                                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":30},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a18dcca8-c60a-58dd-ab7c-cf6e6f3733a0 disabled=true
                        projected_action_0149 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/6；原节点 {"op":"comment","text":"视觉拍照 photo"}
                        # unilab:node_uuid=6164f8c0-9fd9-5d25-9c46-03c9dd26f554
                        with group(name='说明 · 视觉拍照 photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=09d878b1-51c7-52bd-80ed-8fef660b8466 disabled=true
                            projected_control_0150 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/6',
                                control_kind='comment',
                                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
                            )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/7；原节点 {"op":"comment","text":"拍照前整定: 视觉触发路径无内建 settle, 先驻留让机械臂到位后残振衰减再拍 (photo #1)"}
                        # unilab:node_uuid=34c5c518-fb4d-5c50-a964-78c4199f0712
                        with group(name='说明 · 拍照前整定: 视觉触发路径无内建 settle, 先驻留让机械臂到位后残振衰减再拍 (photo #1)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/7；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=03f8d6e0-1e12-5c9a-8eb7-8e4aad334919 disabled=true
                            projected_control_0151 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/7',
                                control_kind='comment',
                                expected_sha256='6eb397dae264a9b5a09ae3c1405d64b2e9c5a940c36db02de4fccc6dbc9c1bcc',
                            )
                        # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f0c4499e-e649-566d-8187-445c8815afd7 disabled=true
                        projected_action_0152 = robot.dwell(
                            duration_ms=300,
                        )
                        # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/9；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3bde8d1f-148d-502f-a5d6-79ac40f670a3 disabled=true
                        projected_action_0153 = vision.capture_plate_offset()
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/10；原节点 {"op":"comment","text":"photo #1 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)"}
                        # unilab:node_uuid=49d895fc-a3a9-597d-ade9-2ecaea7a5323
                        with group(name='说明 · photo #1 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/10；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=e7ee360b-5071-5cf1-bf6a-36b04e6d3209 disabled=true
                            projected_control_0154 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/10',
                                control_kind='comment',
                                expected_sha256='da1eff387eb64169c00489a80c9924bb0712d59bd3a8c496e6bbce7259465c59',
                            )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/11；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_r...
                        # unilab:node_uuid=20d73b01-da90-5f25-961f-b3e4bc636d04
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=26f3cbfb-3b01-5f54-b77e-36df99a5b776 disabled=true
                            projected_control_0155 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/11',
                                control_kind='if',
                                expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/11/then 的静态审阅分支。
                            # unilab:node_uuid=80618d15-d034-5c0d-9169-b46becb5da55
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL human] 来源 robot_suction_put@body/3/then/11/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}}
                                # unilab:node_uuid=8337767d-262f-5fe8-aaa6-95a6e992f93f
                                with group(name='◆ HITL 人工门'):
                                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/11/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=c0723297-4a16-5e74-adf3-255cabc5c83e disabled=true
                                    projected_control_0156 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/11/then/0',
                                        control_kind='human',
                                        expected_sha256='8b6554332d59da20e8cd66a97f4e67c5e9471404e4488c74e2aede653f7c5a9d',
                                    )
                                # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/11/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0587e55a-4aab-5b4c-aed1-dd79fbadc4c0 disabled=true
                                projected_action_0157 = vision.capture_plate_offset()
                                # [CONTROL if] 来源 robot_suction_put@body/3/then/11/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别仍失败(err=111), 中止放板"},"op":"raise"}]}
                                # unilab:node_uuid=6b35b0c2-9a9d-58a5-b46b-edab2c2c2586
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=b0acaed1-323a-522b-b35c-1266d52bd2c1 disabled=true
                                    projected_control_0158 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/11/then/2',
                                        control_kind='if',
                                        expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/11/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=ce435472-8394-59a0-bb22-18e295c6b078
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_suction_put@body/3/then/11/then/2/then/0；原节点 {"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别仍失败(err=111), 中止放板"},"op":"raise"}
                                        # unilab:node_uuid=20a5cb55-1466-5c9d-be76-bda007161df5
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/11/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=e9cdc52b-2429-507a-a21c-57a20ec79ef9 disabled=true
                                            projected_control_0159 = material.review_control_node_v1(
                                                operation_name='robot_suction_put',
                                                node_path='body/3/then/11/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='be10d3c30d5567c5173255006de750689ae329cb8beab67051668e78cfe857d1',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/11/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=10f63456-6e97-5bb5-b64f-4c8bb24077f4
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=ea6dd65f-f76e-5319-8c34-d75a53ae1f46 disabled=true
                                        projected_control_0160 = material.review_control_node_v1(
                                            operation_name='robot_suction_put',
                                            node_path='body/3/then/11/then/2',
                                            control_kind='if',
                                            expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                                        )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/11/else 的静态审阅分支。
                            # unilab:node_uuid=7923a450-140d-587f-99e6-8402710f2a66
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=9081ea98-34b4-5b5d-a81b-cc56ae60c255 disabled=true
                                projected_control_0161 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/11',
                                    control_kind='if',
                                    expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                                )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/12；原节点 {"op":"comment","text":"Correction at P86: rotate Rz first so the plate angle matches the template."}
                        # unilab:node_uuid=90be6b3f-d07f-56ba-b87a-7ebf44611d90
                        with group(name='说明 · Correction at P86: rotate Rz first so the plate angle ma'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/12；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=d11734ce-179b-592f-945a-216f2e165378 disabled=true
                            projected_control_0162 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/12',
                                control_kind='comment',
                                expected_sha256='048674f96cc7d9fb228936ecdb955de10db5887d33835cfc6ea532a5508b4f8c',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"lit":0},"dy_mm":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3896ae4f-3a7d-5ec6-beb5-8dbc62bdd20d disabled=true
                        projected_action_0163 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/14；原节点 {"op":"comment","text":"视觉拍照 #2 after Rz correction: verify residual Rz and re-measure current dx/dy."}
                        # unilab:node_uuid=a6453807-3ab5-5bcd-af11-9cc3a48f4010
                        with group(name='说明 · 视觉拍照 #2 after Rz correction: verify residual Rz and re-m'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/14；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=50fed513-9751-5b2e-92e1-44ffff3e8a62 disabled=true
                            projected_control_0164 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/14',
                                control_kind='comment',
                                expected_sha256='edde8dc0a1dbbe5d4b7696db96096110c9413ee1e108d8eeaadcc4acca4b40a7',
                            )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/15；原节点 {"op":"comment","text":"拍照前整定: Rz 纠偏 move 到位后先驻留让残振衰减再拍, 提升二次纠偏 dx/dy 读数稳定性 (photo #2)"}
                        # unilab:node_uuid=594cddea-305f-5407-b640-88ff4e8c39a5
                        with group(name='说明 · 拍照前整定: Rz 纠偏 move 到位后先驻留让残振衰减再拍, 提升二次纠偏 dx/dy 读数稳定性 (pho'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/15；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=d0fe0483-7382-5a8e-8f87-5d7ada03c981 disabled=true
                            projected_control_0165 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/15',
                                control_kind='comment',
                                expected_sha256='c80c2f69ad6f5f186109645ffa15fa383576a369addd3d672205333e130a5b58',
                            )
                        # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/16；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e43585f1-f125-5af7-98ca-1f72abf7efb4 disabled=true
                        projected_action_0166 = robot.dwell(
                            duration_ms=300,
                        )
                        # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/17；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=853d0b49-ec9a-5218-b864-af2eebd61fc1 disabled=true
                        projected_action_0167 = vision.capture_plate_offset()
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/18；原节点 {"op":"comment","text":"photo #2 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)"}
                        # unilab:node_uuid=18a3f480-df9c-5186-aec2-05a3b72cb4a6
                        with group(name='说明 · photo #2 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/18；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=cf3a6b10-bf19-5023-bcd4-1bc4754fcc31 disabled=true
                            projected_control_0168 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/18',
                                control_kind='comment',
                                expected_sha256='c883d653edf20b229c98087fef4e0a7a74c71315be24a495a2ab4d63627ddbc7',
                            )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/19；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机二次识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff...
                        # unilab:node_uuid=96de6edd-ee6f-58a5-8e0b-ad72a3005f37
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=9b2cc337-84c5-5cbe-aa50-9c1acc1dbed9 disabled=true
                            projected_control_0169 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/19',
                                control_kind='if',
                                expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/19/then 的静态审阅分支。
                            # unilab:node_uuid=2538948a-8209-5a1e-ada7-b4c8ad36bc98
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL human] 来源 robot_suction_put@body/3/then/19/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机二次识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}}
                                # unilab:node_uuid=63245544-be14-50d8-ad7f-675126f7ef22
                                with group(name='◆ HITL 人工门'):
                                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/19/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=2a043472-e514-5195-8f72-4f8c522270b0 disabled=true
                                    projected_control_0170 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/19/then/0',
                                        control_kind='human',
                                        expected_sha256='cac0a9d59b9391aae093bca3c1049db6e51757d3aae2d1a433addc60e61ea15d',
                                    )
                                # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/19/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9bf3be1a-2c07-5ba7-a833-80eea0fbd1b5 disabled=true
                                projected_action_0171 = vision.capture_plate_offset()
                                # [CONTROL if] 来源 robot_suction_put@body/3/then/19/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别重拍仍失败(err=111), 中止放板"},"op":"raise"}]}
                                # unilab:node_uuid=20a4e68f-fcd9-5aa0-863a-d5860cea685d
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=25f33eed-ba60-539b-84d5-636c0e3b1221 disabled=true
                                    projected_control_0172 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/19/then/2',
                                        control_kind='if',
                                        expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/19/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=846b9632-875b-5677-92cc-2352687a56fc
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_suction_put@body/3/then/19/then/2/then/0；原节点 {"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别重拍仍失败(err=111), 中止放板"},"op":"raise"}
                                        # unilab:node_uuid=67548c17-fecf-55c5-ac46-67a10f8b549d
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/19/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=c77634b1-cc94-5561-9957-8d6f4dd004b4 disabled=true
                                            projected_control_0173 = material.review_control_node_v1(
                                                operation_name='robot_suction_put',
                                                node_path='body/3/then/19/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='6a40626789cfd5679600b1a1b2f6f06f22050fa14f437045f3d9d5dcc6da4252',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/19/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=fcb8d25b-e2ba-5bb6-936a-3fd6de812c6f
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=e9a45b0e-6f69-5f24-82e4-f58e8a1864f9 disabled=true
                                        projected_control_0174 = material.review_control_node_v1(
                                            operation_name='robot_suction_put',
                                            node_path='body/3/then/19/then/2',
                                            control_kind='if',
                                            expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                                        )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/19/else 的静态审阅分支。
                            # unilab:node_uuid=bb4f4920-04d6-52da-87a5-37c256aa5d30
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=17543a80-f088-5501-a4c0-f1b87bc180a5 disabled=true
                                projected_control_0175 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/19',
                                    control_kind='if',
                                    expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                                )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/20；原节点 {"cond":{"binop":">","left":{"args":[{"field":{"var":"voff_xy"},"name":"drz_deg"}],"call":"abs"},"right":{"var":"drz_threshold_deg"}},"op":"if","then":[{"error":"VISION_RZ_NOT_CONVERGED","message":{"lit":"二次拍照后 Rz 残差仍超阈值, 中止放板"},"op":"raise"}]}
                        # unilab:node_uuid=47872aa5-233a-5b4a-9fc6-eb9da886c003
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/20；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=9e98eac8-3ca2-5a30-a6fe-06539d38be1b disabled=true
                            projected_control_0176 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/20',
                                control_kind='if',
                                expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/20/then 的静态审阅分支。
                            # unilab:node_uuid=06304ef1-39ab-58ed-aaa9-087f6c6a7cdc
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL raise] 来源 robot_suction_put@body/3/then/20/then/0；原节点 {"error":"VISION_RZ_NOT_CONVERGED","message":{"lit":"二次拍照后 Rz 残差仍超阈值, 中止放板"},"op":"raise"}
                                # unilab:node_uuid=24cf614b-93a7-5f24-aaf5-790024cc1398
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/20/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=bf7d7f69-b74c-5966-be04-6fd77a781be1 disabled=true
                                    projected_control_0177 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/20/then/0',
                                        control_kind='raise',
                                        expected_sha256='d1a24a4f91395a726e8540c6184463fd49fc2fe218385828e42af6f5c642b12d',
                                    )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/20/else 的静态审阅分支。
                            # unilab:node_uuid=aa12e321-013e-557a-b94f-94e65b712db9
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/20；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=4ef664bd-3634-5ca5-aac1-ebdc2e55ffd2 disabled=true
                                projected_control_0178 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/20',
                                    control_kind='if',
                                    expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                                )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/21；原节点 {"op":"comment","text":"Correction preview at P86: translate XY from photo #2 while keeping the Rz correction from photo #1."}
                        # unilab:node_uuid=4d7f2923-f28c-5f59-a4de-4f6b40ffeb8d
                        with group(name='说明 · Correction preview at P86: translate XY from photo #2 wh'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/21；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=4a917f57-0213-5b8f-b213-f720484183fd disabled=true
                            projected_control_0179 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/21',
                                control_kind='comment',
                                expected_sha256='152da6bbb7e27be6e627d1a263fc9073bba19a63e635f096a9db1c353d46245d',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/22；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode...
                        # unilab:node_uuid=53e8e7c3-6dd8-5e98-8a92-14a3a4d94315 disabled=true
                        projected_action_0180 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/23；原节点 {"op":"comment","text":"Final spotting put carries photo"}
                        # unilab:node_uuid=3aa33477-5de2-59d9-99d3-7e0c4d336384
                        with group(name='说明 · Final spotting put carries photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/23；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=35ad34ee-43d1-56e8-9c48-aff10915be80 disabled=true
                            projected_control_0181 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/23',
                                control_kind='comment',
                                expected_sha256='d34a5964054eb7bfa4a11d998941ad9c474d621664cbe44fff1c7a011f963154',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/24；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b8661ef8-e2aa-5381-b6c2-0aa85ca82930 disabled=true
                        projected_action_0182 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/25；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=867025b4-dfec-5f83-9243-2e3dd8df46b6 disabled=true
                        projected_action_0183 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/26；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_near"},"...
                        # unilab:node_uuid=7e82b7fb-a752-5f58-b709-33753493a50d disabled=true
                        projected_action_0184 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/27；原节点 {"op":"comment","text":"Release at P19 with closed-loop correction from vision photo"}
                        # unilab:node_uuid=f5f9a66e-02a0-5178-a372-efd9fedf5325
                        with group(name='说明 · Release at P19 with closed-loop correction from vision p'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/27；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=c04681b2-5018-5147-bdb6-e29ae5e098e9 disabled=true
                            projected_control_0185 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/27',
                                control_kind='comment',
                                expected_sha256='d16b5d31b63a1b0b0f9c85c8e09a509abf646d4812b6ef38723c29608e0c02bd',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/28；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P19"},"vel":{"lit":5}},"mode":...
                        # unilab:node_uuid=6b923520-b43a-563c-a359-dae4004a2b85 disabled=true
                        projected_action_0186 = robot.move_to_point(
                            point_id_or_robot_name='P19',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/29；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=09170a10-5d2b-5bcd-8a72-f96d592e8764 disabled=true
                        projected_action_0187 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/30；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_near"},"v...
                        # unilab:node_uuid=2493ce33-bf71-5068-bcf8-84e57e1c5486 disabled=true
                        projected_action_0188 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/31；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7f775710-1cd4-5c48-8c4c-8b02c7b1288e disabled=true
                        projected_action_0189 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/32；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a65abd1f-d792-586e-b10b-33e5e5b41c53 disabled=true
                        projected_action_0190 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/33；原节点 {"op":"comment","text":"Safety fix: execute rotary-down only after returning to fixed transition point P4."}
                        # unilab:node_uuid=eb9395cc-142d-5990-b451-06b2ce040bcd
                        with group(name='说明 · Safety fix: execute rotary-down only after returning to '):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/33；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=3b6be317-bf96-5e63-ab68-6fd306b92dfe disabled=true
                            projected_control_0191 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/33',
                                control_kind='comment',
                                expected_sha256='8805176604a784f2e55230a1248ed02398b6d66a330667628b5e04cf578d6a79',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/34；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0112f452-cc36-5ef4-8bc6-aa93ea0eeb68 disabled=true
                        projected_action_0192 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/35；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b5be190a-8886-52dd-af03-ea644564bf24 disabled=true
                        projected_action_0193 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/36；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=975c2a92-5410-55e1-8a3a-d1be40bab402 disabled=true
                        projected_action_0194 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_suction_put@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=9054e3d6-5f94-5cbb-850b-7b38ac9d72b7
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ccc6dae7-1f27-5c68-9212-538587730919 disabled=true
                        projected_action_0195 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=33408d4a-48c7-523e-a038-f02795adbb63 disabled=true
                        projected_action_0196 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=92f16413-8df2-59d6-b364-d423e0804583 disabled=true
                        projected_action_0197 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f670d513-5130-5947-9e0e-8d6b4c98611c disabled=true
                        projected_action_0198 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/4；原节点 {"op":"comment","text":"No later vision correction after spotting; scrape put uses nominal locator points."}
                        # unilab:node_uuid=0200043f-efcc-5e7f-8a29-7f825ecbceec
                        with group(name='说明 · No later vision correction after spotting; scrape put us'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=59073d0c-7ab5-50a1-99ac-8633f4bbaa05 disabled=true
                            projected_control_0199 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/4',
                                control_kind='comment',
                                expected_sha256='72c75af1e4a1520e92d0910d1ec5bb1fbe7428fd161fbc792048931e3b80b01d',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=81650815-7956-56ec-95df-6c35a4e15a78 disabled=true
                        projected_action_0200 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=151e91d1-4a2b-548b-81df-21c5f122564d disabled=true
                        projected_action_0201 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=46a55010-9b2d-5cb4-918a-c3fedf039b57 disabled=true
                        projected_action_0202 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/8；原节点 {"op":"comment","text":"Release at nominal P65; no later vision correction after spotting."}
                        # unilab:node_uuid=b68e0a24-2e08-50ed-a2b1-9276af215be4
                        with group(name='说明 · Release at nominal P65; no later vision correction after'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/8；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=4290cb65-2251-5aa5-8b78-b10b87a94d62 disabled=true
                            projected_control_0203 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/8',
                                control_kind='comment',
                                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P65"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=239af4cb-ca9a-5709-8401-46f757420b6e disabled=true
                        projected_action_0204 = robot.move_to_point(
                            point_id_or_robot_name='P65',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0096d32a-4376-56bd-bd05-8d93c4e8fbe5 disabled=true
                        projected_action_0205 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a2cb62a9-5c20-5215-a023-58ffc99ee909 disabled=true
                        projected_action_0206 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3959c47b-a8a8-5336-ac9e-3d0c139fc368 disabled=true
                        projected_action_0207 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cd726250-2f4f-5c2b-9217-694b6ce61a23 disabled=true
                        projected_action_0208 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/14；原节点 {"op":"comment","text":"Release at nominal P65; no later vision correction after spotting."}
                        # unilab:node_uuid=411ef006-7970-5f2e-b346-d982d81a6010
                        with group(name='说明 · Release at nominal P65; no later vision correction after'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/14；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=7037fcdb-d9d8-5583-9b5e-dee1125f0a20 disabled=true
                            projected_control_0209 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/14',
                                control_kind='comment',
                                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/15；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=48b19d1b-b1d3-5127-8d9f-6c1c7d2eb45d disabled=true
                        projected_action_0210 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=487369e9-8f37-5488-a96f-e8cfe19013af disabled=true
                        projected_action_0211 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/17；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=04258993-ae46-546d-8104-519ef3719a40 disabled=true
                        projected_action_0212 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 2（互斥分支）] robot_suction_put@body/3/elifs/1/body 的静态审阅分支。
                    # unilab:node_uuid=43e34185-a573-52f4-bf63-e93a3a601b44
                    with group(name='ELIF 2（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=68f31b2a-17e0-5cb2-9bbd-19574b21cbbc disabled=true
                        projected_action_0213 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cc8c2c6b-b70f-5b28-85cc-86c90c35e58d disabled=true
                        projected_action_0214 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fed27d46-ba23-5925-919b-fde3ca37903b disabled=true
                        projected_action_0215 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cc72a6f4-b8b3-5249-8558-1acb67f42cec disabled=true
                        projected_action_0216 = robot.move_to_point(
                            point_id_or_robot_name='P5',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1d61759b-c97a-5871-ac8b-d158e7b77ca1 disabled=true
                        projected_action_0217 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5b03e22d-6958-534f-bed9-1c58aeb6cc0e disabled=true
                        projected_action_0218 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P22"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=13df9c9a-1420-5c47-8ab1-823dfe42aaaa disabled=true
                        projected_action_0219 = robot.move_to_point(
                            point_id_or_robot_name='P22',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7ed82c4a-e8f5-5782-ae07-6b480307a801 disabled=true
                        projected_action_0220 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=21b08d39-467e-53ca-8d4c-0d10310655a3 disabled=true
                        projected_action_0221 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2dd83aff-f59c-5c24-9503-2639d6d47d63 disabled=true
                        projected_action_0222 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0685ab5b-347c-5af3-a5e1-52e036ac8f61 disabled=true
                        projected_action_0223 = robot.move_to_point(
                            point_id_or_robot_name='P5',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ba8b05d1-db67-5fc5-8bb4-c61032a0f9bb disabled=true
                        projected_action_0224 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c043dab8-545b-55c2-9352-7051f3025fcf disabled=true
                        projected_action_0225 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=e6b8ee5b-4810-538a-b504-6e0e67ab853d
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_suction_put@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"suction.put: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=4bfa582e-d288-5339-8a0c-e9244f61344c
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=b01c395f-5011-502e-ad51-9900cc2ba47f disabled=true
                            projected_control_0226 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='7ee4ffd8bc9852082873ab137113eb00aa6df1b10ce72423cb995bbc3e2c295a',
                            )
            # [CONTROL comment] 来源 photoscrape_plate_load@body/4；原节点 {"op":"comment","text":"plate/load: 定位气缸夹紧"}
            # unilab:node_uuid=4484734b-65d6-5101-91a0-747e37ff60ee
            with group(name='说明 · plate/load: 定位气缸夹紧'):
                # [VERIFY comment] 只读来源校验 photoscrape_plate_load@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=c6938dc7-3fd3-5dbe-af00-1ae03a3d886a disabled=true
                projected_control_0227 = material.review_control_node_v1(
                    operation_name='photoscrape_plate_load',
                    node_path='body/4',
                    control_kind='comment',
                    expected_sha256='8b7eee6760b1c33a19c19bb503d44fecd4b4bdb7fa010f633dd57dc94bb5357c',
                )
            # [ACTION photoscrape.locate_cylinder] 来源 photoscrape_plate_load@body/5；原节点 {"action":"photoscrape.locate_cylinder","args":{"clamped":{"lit":true}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0e4e95a7-f0fc-5732-a66a-b03834244714 disabled=true
            projected_action_0228 = photoscrape.locate_cylinder(
                clamped=True,
            )
        # [CONTROL comment] 来源 pf_s4_photo_before@body/5；原节点 {"op":"comment","text":"拍 before.jpg; 段末板仍被定位夹具夹在刮板台上 (稳定停放), 机器人空手"}
        # unilab:node_uuid=9f65ce2d-01e2-50c1-81f2-c21166ef21f4
        with group(name='说明 · 拍 before.jpg; 段末板仍被定位夹具夹在刮板台上 (稳定停放), 机器人空手'):
            # [VERIFY comment] 只读来源校验 pf_s4_photo_before@body/5；节点在本工作流中静态 disabled。
            # unilab:node_uuid=b2438090-4de2-50c1-8b20-dbf4e417f77e disabled=true
            projected_control_0229 = material.review_control_node_v1(
                operation_name='pf_s4_photo_before',
                node_path='body/5',
                control_kind='comment',
                expected_sha256='2be4cb88c57d611838e0d346dfc8e8ea03e5a47ca39e29930ae140476dbf157f',
            )
        # [SUBWORKFLOW photoscrape_before_photo_capture] 由 pf_s4_photo_before@body/6 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=5e9fee5a-2cf6-55fe-94af-431e7f2172a2
        with group(name='↳ photoscrape_before_photo_capture'):
            # [CONTROL comment] 来源 photoscrape_before_photo_capture@body/0；原节点 {"op":"comment","text":"before/photo: 移相机位+遮光下, 就绪待拍"}
            # unilab:node_uuid=7d6754af-b7a5-54cb-91ee-96a4f2cf09a0
            with group(name='说明 · before/photo: 移相机位+遮光下, 就绪待拍'):
                # [VERIFY comment] 只读来源校验 photoscrape_before_photo_capture@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=76bc0829-3281-5f2c-8b8f-921a57af95d4 disabled=true
                projected_control_0230 = material.review_control_node_v1(
                    operation_name='photoscrape_before_photo_capture',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='29ff9de63428ed8db8791c4a5c3320b96950d735578fe77ce785cde9353795ff',
                )
            # [ACTION photoscrape.cam_photopos] 来源 photoscrape_before_photo_capture@body/1；原节点 {"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=36c0af8c-e39e-5076-9bf8-ec8b52f76e0e disabled=true
            projected_action_0231 = photoscrape.cam_photopos(
                ref_8y='photo_8y',
            )
            # [CONTROL comment] 来源 photoscrape_before_photo_capture@body/2；原节点 {"op":"comment","text":"before/photo: 上位机触发相机拍 before.jpg"}
            # unilab:node_uuid=3c8dd8d2-fd5f-50b8-a551-5a04560f1f2a
            with group(name='说明 · before/photo: 上位机触发相机拍 before.jpg'):
                # [VERIFY comment] 只读来源校验 photoscrape_before_photo_capture@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=39bb3a3e-70b9-5485-8c5f-4f95ac6fded6 disabled=true
                projected_control_0232 = material.review_control_node_v1(
                    operation_name='photoscrape_before_photo_capture',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='3b65ef612784f89b1a0937733df2574c8f4d1fc25295abfbc08b4e8613a2da6b',
                )
            # [ACTION photoscrape.capture] 来源 photoscrape_before_photo_capture@body/3；原节点 {"action":"photoscrape.capture","args":{"filename":{"lit":"before.jpg"},"profile":{"lit":"photoscrape"},"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"assign":{"var":"shot"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=aa7d65aa-0abe-527d-a963-b6c649c59ac0 disabled=true
            projected_action_0233 = photoscrape.capture(
                sample_id='review-only',
                save_dir='review-only',
            )
            # [CONTROL assign] 来源 photoscrape_before_photo_capture@body/4；原节点 {"op":"assign","target":{"var":"before_path"},"value":{"field":{"var":"shot"},"name":"image_path"}}
            # unilab:node_uuid=2c425f5b-24f6-5e4c-a38e-8f8df0301f69
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 photoscrape_before_photo_capture@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=6664986f-d1f9-5fa3-826f-2620b93dea4e disabled=true
                projected_control_0234 = material.review_control_node_v1(
                    operation_name='photoscrape_before_photo_capture',
                    node_path='body/4',
                    control_kind='assign',
                    expected_sha256='5b4a0c560b1af2c8ef48593b51f8871721eac7bc9fc91bf1bba2f654a2947eb4',
                )
            # [ACTION photoscrape.cam_photohome] 来源 photoscrape_before_photo_capture@body/5；原节点 {"action":"photoscrape.cam_photohome","mode":"RUN","op":"call"}
            # unilab:node_uuid=d1db0863-6ce9-55eb-9c23-b9de2b591dae disabled=true
            projected_action_0235 = photoscrape.cam_photohome()
    # [EXECUTE ROOT pf_s4_photo_before] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=ddfe9496-df54-5030-8dec-5927028892b2
    execution = material.run_operation_review_v1(
        operation_name='pf_s4_photo_before',
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
