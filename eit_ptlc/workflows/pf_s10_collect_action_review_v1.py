from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.plc_collect import PLCCollect
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.unilab_domain.devices.plc_rail import PLCRail
from eit_ptlc.unilab_domain.devices.robot import RobotProxy
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA


class PlatformOperationReviewV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    before_path: str
    collector_hole: int
    bottle_hole: int

collect: PLCCollect = device('plc_collect')
material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='9fac83e2-795f-5a9e-bc6f-8203028b5539',
    displayname='8 粉末收集 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s10_collect_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s10_collect] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=66be2a23-4da3-547b-8d3f-b230c463c602
    with group(name='审阅投影（全部禁用）'):
        # [SUBWORKFLOW collect_cycle] 由 pf_s10_collect@body/0 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=1a3fafd3-8f9d-58db-b759-c4b8e9c98515
        with group(name='↳ collect_cycle'):
            # [CONTROL comment] 来源 collect_cycle@body/0；原节点 {"op":"comment","text":"prepare: 收集站复位与泵/阀初始化"}
            # unilab:node_uuid=50fd33d3-d0d6-5c33-b015-968a82f556d8
            with group(name='说明 · prepare: 收集站复位与泵/阀初始化'):
                # [VERIFY comment] 只读来源校验 collect_cycle@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=669bf7e0-34a2-5ec0-ad70-e9354f26762b disabled=true
                projected_control_0001 = material.review_control_node_v1(
                    operation_name='collect_cycle',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='67325383555ba17cd0db7320b3c3d6cddf8c884e572a03b64f36fccf8d890a19',
                )
            # [SUBWORKFLOW collect_prepare] 由 collect_cycle@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=f2b972e5-05f0-5eaa-9d7c-bac52e2b5eb6
            with group(name='↳ collect_prepare'):
                # [CONTROL comment] 来源 collect_prepare@body/0；原节点 {"op":"comment","text":"准备: 复位收集站气缸/阀/泵, 必须早于接粉收集器放入"}
                # unilab:node_uuid=3de80324-c695-5f39-83ca-0db9446abebb
                with group(name='说明 · 准备: 复位收集站气缸/阀/泵, 必须早于接粉收集器放入'):
                    # [VERIFY comment] 只读来源校验 collect_prepare@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=9bb6bb77-5d09-5dda-abbd-9ffe9a7503ab disabled=true
                    projected_control_0002 = material.review_control_node_v1(
                        operation_name='collect_prepare',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='aa19b5a61a50cb6debd48f175c9c60d6cc0d2e61afeb90f3cb9a33de5f8cd1be',
                    )
                # [ACTION collect.init] 来源 collect_prepare@body/1；原节点 {"action":"collect.init","mode":"RUN","op":"call"}
                # unilab:node_uuid=97baaf55-e487-5656-94b2-11bda12517bb disabled=true
                projected_action_0003 = collect.init()
            # [CONTROL comment] 来源 collect_cycle@body/2；原节点 {"op":"comment","text":"load: 接粉收集器进入收集夹具, 收集瓶进入收集位"}
            # unilab:node_uuid=ecc329bc-55b8-5a4b-b74d-3682deb75fdc
            with group(name='说明 · load: 接粉收集器进入收集夹具, 收集瓶进入收集位'):
                # [VERIFY comment] 只读来源校验 collect_cycle@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=a44feda3-a63a-5e70-b626-af403307e5e2 disabled=true
                projected_control_0004 = material.review_control_node_v1(
                    operation_name='collect_cycle',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='8e2eb7f2b27ec8eb70c74692cfb428d3433d2b72f6fe92ea30b4e1727f8e7f93',
                )
            # [SUBWORKFLOW collect_load] 由 collect_cycle@body/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=a4a04422-6d9d-5772-a1bb-9aab315fd746
            with group(name='↳ collect_load'):
                # [CONTROL comment] 来源 collect_load@body/0；原节点 {"op":"comment","text":"前置: photoscrape_process 已完成刮取收尾; 本段释放刮板下压并取走接粉收集器"}
                # unilab:node_uuid=ee69a88e-237e-5ca5-b0a9-672092ead778
                with group(name='说明 · 前置: photoscrape_process 已完成刮取收尾; 本段释放刮板下压并取走接粉收集器'):
                    # [VERIFY comment] 只读来源校验 collect_load@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=8ae5f416-f179-5dcf-abae-237e22ac89a3 disabled=true
                    projected_control_0005 = material.review_control_node_v1(
                        operation_name='collect_load',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='d22617b3c5a20512c63ba4ff13777c3902ef4c0dcab1af270e6e1ce36c62ace6',
                    )
                # [CONTROL comment] 来源 collect_load@body/1；原节点 {"op":"comment","text":"自守卫地轨在刮板位(位2)再取接粉收集器: 幂等; 防上游(如 ptlc_full_v2 collect 前 rail.move(3))遗留错位撞夹具"}
                # unilab:node_uuid=e7b70001-0849-55f3-b92d-7a578ec05bed
                with group(name='说明 · 自守卫地轨在刮板位(位2)再取接粉收集器: 幂等; 防上游(如 ptlc_full_v2 collect 前 r'):
                    # [VERIFY comment] 只读来源校验 collect_load@body/1；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=7fcd724b-ce05-5637-9f3d-85e8525e2834 disabled=true
                    projected_control_0006 = material.review_control_node_v1(
                        operation_name='collect_load',
                        node_path='body/1',
                        control_kind='comment',
                        expected_sha256='e39b990ef44c67991b62cfa973f27b27808671496ce5e7ad4503d76de6743704',
                    )
                # [SUBWORKFLOW rail_move_safe] 由 collect_load@body/2 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=10f5caed-2d74-57f6-9b61-1f0e7ae504b6
                with group(name='↳ rail_move_safe'):
                    # [CONTROL comment] 来源 rail_move_safe@body/0；原节点 {"op":"comment","text":"确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)"}
                    # unilab:node_uuid=a6f26848-a067-561b-8f3d-bbb5319faab0
                    with group(name='说明 · 确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)'):
                        # [VERIFY comment] 只读来源校验 rail_move_safe@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=a4ec491c-2670-5b09-b3b3-e717d53b19b7 disabled=true
                        projected_control_0007 = material.review_control_node_v1(
                            operation_name='rail_move_safe',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='cc629ec60964ec74a746185851e52069f3b991388ab52755ebea4f3b92ed1740',
                        )
                    # [ACTION robot.home_ensure] 来源 rail_move_safe@body/1；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=81a4f5c7-67a6-5b0a-ad9d-c60d3795a4a5 disabled=true
                    projected_action_0008 = robot.home_ensure()
                    # [CONTROL comment] 来源 rail_move_safe@body/2；原节点 {"op":"comment","text":"安全位确认 -> 移动地轨到目标位"}
                    # unilab:node_uuid=d6cbb755-330b-55e4-b8de-e9f764ebbb9a
                    with group(name='说明 · 安全位确认 -> 移动地轨到目标位'):
                        # [VERIFY comment] 只读来源校验 rail_move_safe@body/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=869a4de0-6b1a-54b3-a957-644e27e7672d disabled=true
                        projected_control_0009 = material.review_control_node_v1(
                            operation_name='rail_move_safe',
                            node_path='body/2',
                            control_kind='comment',
                            expected_sha256='38f90a43c3043b67cd1207e8d94cd7c595a01ab69567c39518284d36ecb68702',
                        )
                    # [ACTION rail.move] 来源 rail_move_safe@body/3；原节点 {"action":"rail.move","args":{"Rail_Target_Position":{"var":"target"}},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=2f2e1bc0-03ea-524c-b845-bad2d53cc5b8 disabled=true
                    projected_action_0010 = rail.move(
                        Rail_Target_Position=1,
                    )
                # [CONTROL comment] 来源 collect_load@body/3；原节点 {"op":"comment","text":"放料/接粉收集器: 从刮板接粉夹具进入取料姿态"}
                # unilab:node_uuid=f5754e05-64cc-5e28-af82-464371229969
                with group(name='说明 · 放料/接粉收集器: 从刮板接粉夹具进入取料姿态'):
                    # [VERIFY comment] 只读来源校验 collect_load@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=21767b2b-d44c-523c-92d8-4d81e70dd1f7 disabled=true
                    projected_control_0011 = material.review_control_node_v1(
                        operation_name='collect_load',
                        node_path='body/3',
                        control_kind='comment',
                        expected_sha256='78e70af8c03ad6624d22d40e6775dc441a754e4e48fe62e7523832475c309a48',
                    )
                # [SUBWORKFLOW robot_scrape_holder_pick_enter] 由 collect_load@body/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=4f44eea3-9759-5008-be59-56382798fdf2
                with group(name='↳ robot_scrape_holder_pick_enter'):
                    # [CONTROL comment] 来源 robot_scrape_holder_pick_enter@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)"}
                    # unilab:node_uuid=75b7a3ba-1cf0-5f78-ab78-46c33266f4b1
                    with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)'):
                        # [VERIFY comment] 只读来源校验 robot_scrape_holder_pick_enter@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=afaf107e-6a7a-55f5-b658-ba64da921907 disabled=true
                        projected_control_0012 = material.review_control_node_v1(
                            operation_name='robot_scrape_holder_pick_enter',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
                        )
                    # [ACTION robot.home_ensure] 来源 robot_scrape_holder_pick_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                    # unilab:node_uuid=f97b1ecf-0b66-5fb5-81c7-0638bc04ccb0 disabled=true
                    projected_action_0013 = robot.home_ensure()
                    # [SUBWORKFLOW robot_tool_ensure] 由 robot_scrape_holder_pick_enter@body/2 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=cfa230a6-f322-55f2-bf2a-0d50e94ea125
                    with group(name='↳ robot_tool_ensure'):
                        # [CONTROL comment] 来源 robot_tool_ensure@body/0；原节点 {"op":"comment","text":"读权威工具态 (mounted_tool 启动已从状态文件恢复","回显在 tool_state.mounted_tool)":null}
                        # unilab:node_uuid=db1d68d0-b009-5ecd-ae6f-5bbfafbcaad9
                        with group(name='说明 · 读权威工具态 (mounted_tool 启动已从状态文件恢复'):
                            # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=b9dae438-4a56-57cb-952d-5bc52150c6b7 disabled=true
                            projected_control_0014 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/0',
                                control_kind='comment',
                                expected_sha256='d809e1de31eaaae6a28b91dfdc9f8587e53c48ce272668a1d7794e15c68d86f9',
                            )
                        # [ACTION robot.query] 来源 robot_tool_ensure@body/1；原节点 {"action":"robot.query","assign":{"var":"fb"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=272fea10-3995-525c-93fe-c94bb0db37d8 disabled=true
                        projected_action_0015 = robot.query()
                        # [CONTROL assign] 来源 robot_tool_ensure@body/2；原节点 {"op":"assign","target":{"var":"current"},"value":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"mounted_tool"}}
                        # unilab:node_uuid=f61da961-658b-5d33-b6c9-277e6e91cadf
                        with group(name='变量赋值'):
                            # [VERIFY assign] 只读来源校验 robot_tool_ensure@body/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=8aedd55e-5fe3-5d61-98cd-6d9fb90cfd9d disabled=true
                            projected_control_0016 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/2',
                                control_kind='assign',
                                expected_sha256='0a8bed4ab1ed21eab44aa30c3cdc41f38a8147534c728fa885ef1da0ba3237c7',
                            )
                        # [CONTROL if] 来源 robot_tool_ensure@body/3；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"var":"needed"}},"op":"if","then":[{"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"},{"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"},{"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"r...
                        # unilab:node_uuid=f0b69a3d-7f47-5e4e-898b-75d42312f080
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=224a4443-9955-53c3-88fd-364cdac7028a disabled=true
                            projected_control_0017 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3',
                                control_kind='if',
                                expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                            )
                            # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then 的静态审阅分支。
                            # unilab:node_uuid=aaa7df06-d937-57d9-8203-efc7949bd567
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/0；原节点 {"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"}
                                # unilab:node_uuid=44c4e7ed-bf21-533b-a4bc-403c5be4daf1
                                with group(name='说明 · 当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标'):
                                    # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=e4c24460-b7d0-5bec-8b49-a84851262dc3 disabled=true
                                    projected_control_0018 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/0',
                                        control_kind='comment',
                                        expected_sha256='f1c1621fc9a3af0fead9abddfba4acc6d628c4e07f02d5e1d6e79342f780d4b5',
                                    )
                                # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/1；原节点 {"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"}
                                # unilab:node_uuid=cdd7a57e-b421-53db-816f-98952a12fa8a
                                with group(name='说明 · 卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止'):
                                    # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/1；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=5ac0ea39-ddce-5e77-8b78-faea0ed50018 disabled=true
                                    projected_control_0019 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/1',
                                        control_kind='comment',
                                        expected_sha256='ab6b298fa1974e89ffba98e42a169ccd9b213ac1a03a6723584be2b1be7e6898',
                                    )
                                # [CONTROL if] 来源 robot_tool_ensure@body/3/then/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"right":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"suction_on"}},"op":"if","then":[{"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}]}
                                # unilab:node_uuid=779c7a2d-dffb-56d6-b427-57a48de5cc8a
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=f40aebc7-aa7f-5484-8cf8-a8952ea8f35c disabled=true
                                    projected_control_0020 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/2',
                                        control_kind='if',
                                        expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=761ce60c-f496-5c64-b682-58dd9c7dd77c
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_tool_ensure@body/3/then/2/then/0；原节点 {"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}
                                        # unilab:node_uuid=64ed5df1-ff01-5fea-9ea9-73386246c38b
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_tool_ensure@body/3/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=1d283215-69ee-5812-860a-67eeb2010ec0 disabled=true
                                            projected_control_0021 = material.review_control_node_v1(
                                                operation_name='robot_tool_ensure',
                                                node_path='body/3/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='8ade635dfc3c21601ac8fa50ba7a168191332f67cbf70e021465f2765df9b23f',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=4e24dade-074d-5c0c-b217-3fd74bcf26fe
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=0ee9c64f-bad3-5f14-b72b-18230dcc7c6e disabled=true
                                        projected_control_0022 = material.review_control_node_v1(
                                            operation_name='robot_tool_ensure',
                                            node_path='body/3/then/2',
                                            control_kind='if',
                                            expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                        )
                                # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 robot_tool_ensure@body/3/then/3；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=9dab3687-ae21-58d1-b6af-4cf5b487fc49 disabled=true
                                projected_control_0023 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/3',
                                    control_kind='run_script',
                                    expected_sha256='a71d68a21f68d19b7cde73b5c95737ce6077a1b162074653e98fadbcdf8c69f9',
                                )
                                # [CONTROL if] 来源 robot_tool_ensure@body/3/then/4；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"lit":0}},"op":"if","then":[{"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}]}
                                # unilab:node_uuid=ae6358d9-5172-53b7-ae02-d9bad491fdad
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=33e4a64e-05c8-567b-bfca-3db2b1e772a4 disabled=true
                                    projected_control_0024 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/4',
                                        control_kind='if',
                                        expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/4/then 的静态审阅分支。
                                    # unilab:node_uuid=486b2cbc-969d-5a5a-b7d4-e07936164a14
                                    with group(name='THEN（互斥分支）'):
                                        # [SUBWORKFLOW robot_tool_put] 由 robot_tool_ensure@body/3/then/4/then/0 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                        # unilab:node_uuid=9304dee7-8fc5-5ab6-82ab-540a728c18c7
                                        with group(name='↳ robot_tool_put'):
                                            # [FLATTENED CONTROL if] 只读来源校验 robot_tool_put@body/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=4033eaa9-ca48-58c5-ae01-6bfab08ada1d disabled=true
                                            projected_control_0025 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0',
                                                control_kind='if',
                                                expected_sha256='9c64b805f035e287559b6a10c2883f201fed2852028900bfd6c9c7526352d298',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=734da5b4-cdcc-51c3-9ec7-1d73fe85474f disabled=true
                                            projected_action_0026 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3c5083a1-1f95-5fca-91fb-1514acdc448c disabled=true
                                            projected_action_0027 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=eb23b0d1-85ab-540d-9e7d-40af8cd92511 disabled=true
                                            projected_action_0028 = robot.tool_action(
                                                action='rotary-down',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0f058599-f387-56c8-9d68-ecc6efdb3aef disabled=true
                                            projected_action_0029 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=67484dcd-b2d2-5b11-9132-f8133cadc13d disabled=true
                                            projected_action_0030 = robot.tool_action(
                                                action='tool-change-aux-on',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=5af51271-1c6b-52d3-8efe-548c506e76a3 disabled=true
                                            projected_action_0031 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8904faa6-0af0-5848-8907-faa046df85c9 disabled=true
                                            projected_action_0032 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6d2d3695-aed9-5a5b-a521-be2afdf69857 disabled=true
                                            projected_action_0033 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1bddbb1b-7755-5a5e-98d0-8cbe2739a57a disabled=true
                                            projected_action_0034 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/9；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b05fe0f6-c4d0-553d-b4b6-a843db5fa4d3 disabled=true
                                            projected_action_0035 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/then/10；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a2a4d3b0-3911-5ac3-ae71-cb69e8b696fe disabled=true
                                            projected_action_0036 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=7595d4e0-60c2-5899-ba3c-8594807786aa disabled=true
                                            projected_action_0037 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3ebf948a-9484-5188-becb-3f8592480688 disabled=true
                                            projected_action_0038 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=52dd4a30-d427-598e-9207-4b3ecebaeacd disabled=true
                                            projected_action_0039 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ab2f18ed-11b3-5c64-87bd-c52d224cec4c disabled=true
                                            projected_action_0040 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a2e8a1e0-8aa5-5251-b144-b83ff57742d0 disabled=true
                                            projected_action_0041 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=96990bdb-5ea7-5d76-bb10-a4e4cbbf74ba disabled=true
                                            projected_action_0042 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=771f0dfb-da32-5177-8b73-f2efe32090ab disabled=true
                                            projected_action_0043 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=93f16620-06e7-58b7-b50a-cb4b47b04a0f disabled=true
                                            projected_action_0044 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8b543533-1370-5d49-9e76-63c3fd3bcd19 disabled=true
                                            projected_action_0045 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=50556bbb-edf4-55c6-8aae-344983d01f0d disabled=true
                                            projected_action_0046 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3bcdeb04-a5a5-521e-b64a-09bed9c8a479 disabled=true
                                            projected_action_0047 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/0/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ea343c00-ef07-5b1a-9746-25c47178afea disabled=true
                                            projected_action_0048 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=73a7d54f-5184-5d98-839c-91b9b8b8f01c disabled=true
                                            projected_action_0049 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=05bcb9f9-03b5-57fc-98ba-0bb5dd041bb2 disabled=true
                                            projected_action_0050 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=88b1489e-1700-584a-9956-3a8f3ab0bc3e disabled=true
                                            projected_action_0051 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f3c341f6-bf39-53e9-ab27-1089aad64f3b disabled=true
                                            projected_action_0052 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c118e5a1-d5c1-58b0-bf4e-f2dfa99988b0 disabled=true
                                            projected_action_0053 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4e60c83d-6b26-5f7d-9763-47b6bf5526e0 disabled=true
                                            projected_action_0054 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a321f3de-c296-5d03-8683-951da5756abd disabled=true
                                            projected_action_0055 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a40a6972-25c7-5805-adcc-ba5b03470d62 disabled=true
                                            projected_action_0056 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=eade11eb-d897-553d-ac3d-6b89a2dd4cf3 disabled=true
                                            projected_action_0057 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d98a1294-d61d-5987-a412-71e1af6be3f4 disabled=true
                                            projected_action_0058 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=fca04029-99e1-5b7f-bcbe-d55b163330d1 disabled=true
                                            projected_action_0059 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/1/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9e688e28-a62c-525c-adda-28d5a28f0dee disabled=true
                                            projected_action_0060 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=cd9029d0-e74c-57ba-adeb-93d4d956c39b disabled=true
                                            projected_action_0061 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2ac5cfcc-1afb-51b6-afd9-43b61d092a6a disabled=true
                                            projected_action_0062 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [FLATTENED CONTROL raise] 只读来源校验 robot_tool_put@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=68f5e1c9-60eb-56de-a3d9-75b3333ba413 disabled=true
                                            projected_control_0063 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='8aa6aa6f749c6777b2a7040e04f4316dd03cc80d36de51eec476b3dbb6c6de75',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/4/else 的静态审阅分支。
                                    # unilab:node_uuid=9900c7ce-d2bd-580b-b2a0-c9ee1c0f56bf
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=a64f9997-bb19-5500-a785-8aaa9df242c4 disabled=true
                                        projected_control_0064 = material.review_control_node_v1(
                                            operation_name='robot_tool_ensure',
                                            node_path='body/3/then/4',
                                            control_kind='if',
                                            expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                        )
                                # [SUBWORKFLOW robot_tool_pick] 由 robot_tool_ensure@body/3/then/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                # unilab:node_uuid=195fcff4-ba6c-5df7-9f53-4b59e5cd5f49
                                with group(name='↳ robot_tool_pick'):
                                    # [CONTROL if] 来源 robot_tool_pick@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"},{"action":"robot.move...
                                    # unilab:node_uuid=bd517d6a-7515-5137-b82c-49bf01966f19
                                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                                        # [VERIFY if] 只读来源校验 robot_tool_pick@body/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=f4fd07ad-77a2-511b-bfca-fe918c3d6ac0 disabled=true
                                        projected_control_0065 = material.review_control_node_v1(
                                            operation_name='robot_tool_pick',
                                            node_path='body/0',
                                            control_kind='if',
                                            expected_sha256='47a5b48eb2b065101041caadd225ef492b21028bb19039ac3a19991997da1895',
                                        )
                                        # [BRANCH THEN（互斥分支）] robot_tool_pick@body/0/then 的静态审阅分支。
                                        # unilab:node_uuid=ac4a7d0b-8a7f-5ccc-9a40-fd09721a01f5
                                        with group(name='THEN（互斥分支）'):
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=18375861-bc7d-5949-ac78-30d873d5c417 disabled=true
                                            projected_action_0066 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8ae1edcb-81b0-591a-ae9a-e43993eb5970 disabled=true
                                            projected_action_0067 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=97c2d9c2-a2b6-57d4-92d4-59343b5f51d4 disabled=true
                                            projected_action_0068 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=aa79d496-8504-59a1-9fec-9ab7678abb63 disabled=true
                                            projected_action_0069 = robot.tool_action(
                                                action='quick-change-lock',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/then/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":1}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e3f5a31f-7c19-59f8-a179-a54fd285d8c1 disabled=true
                                            projected_action_0070 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=fbca4c5d-1601-5be7-b797-f1543223624e disabled=true
                                            projected_action_0071 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=25d4d150-0c83-5325-9fcc-cfe2a264f268 disabled=true
                                            projected_action_0072 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=5dd27ad7-957b-5089-a4ad-2a885c733936 disabled=true
                                            projected_action_0073 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a80d6a14-edf6-547a-944b-540d7996d5ae disabled=true
                                            projected_action_0074 = robot.dwell(
                                                duration_ms=500,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ecca7f0e-ae2c-5ace-a2a3-b96a2e2ef439 disabled=true
                                            projected_action_0075 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.home',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=07907fa5-bd29-5d28-8135-97289b408199 disabled=true
                                            projected_action_0076 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                        # [BRANCH ELIF 1（互斥分支）] robot_tool_pick@body/0/elifs/0/body 的静态审阅分支。
                                        # unilab:node_uuid=55223223-7f5e-557d-8e65-42b19269008c
                                        with group(name='ELIF 1（互斥分支）'):
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f962c0fb-04e8-5725-ad6b-f0cd72f35ebe disabled=true
                                            projected_action_0077 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=feafd764-ab36-536e-9190-82b6b91dd61f disabled=true
                                            projected_action_0078 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=dc77e78f-980d-5629-83b7-f192199ca312 disabled=true
                                            projected_action_0079 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=58ab5b51-306f-55fe-bafa-c27053ae7e6f disabled=true
                                            projected_action_0080 = robot.tool_action(
                                                action='quick-change-lock',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/0/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":2}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b7bf92d8-10c2-57ec-b025-9d7836c6f26f disabled=true
                                            projected_action_0081 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=743a4d42-b29a-55c5-9c1d-34b9a4badf1b disabled=true
                                            projected_action_0082 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a8cfb9b0-4da3-5158-9d92-dbb6bc59353e disabled=true
                                            projected_action_0083 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4e654e88-cd6c-53d2-889e-5bd6450a732c disabled=true
                                            projected_action_0084 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/0/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=07097dd8-dfd6-5b8e-9456-43d0895c098e disabled=true
                                            projected_action_0085 = robot.dwell(
                                                duration_ms=500,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=44c2f089-a8e8-5052-9267-a538c3a8d3f3 disabled=true
                                            projected_action_0086 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.home',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=472815ec-10ee-55e7-98db-bcbcd7c24126 disabled=true
                                            projected_action_0087 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                        # [BRANCH ELIF 2（互斥分支）] robot_tool_pick@body/0/elifs/1/body 的静态审阅分支。
                                        # unilab:node_uuid=97d52c3b-be05-58bf-9dd9-c8e94437ba05
                                        with group(name='ELIF 2（互斥分支）'):
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=eef4e3ea-b20c-583c-9b3c-ae0b76f84991 disabled=true
                                            projected_action_0088 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=bdacfc82-8edd-54d5-b3a8-2e63d9c44059 disabled=true
                                            projected_action_0089 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=774676aa-e5f9-5478-b0b3-9fa14fe02bd0 disabled=true
                                            projected_action_0090 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/1/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a8e27f8a-28d6-550a-a0a6-03089dfe56f1 disabled=true
                                            projected_action_0091 = robot.tool_action(
                                                action='quick-change-lock',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/1/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":3}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=40a83ebf-9d8f-5a79-a365-72e203a703f3 disabled=true
                                            projected_action_0092 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a3fe7936-b4c6-5d40-9eea-82d55e2d2e9a disabled=true
                                            projected_action_0093 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=63986696-5d13-5bdd-b7fa-cf51a3b8bc78 disabled=true
                                            projected_action_0094 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=dc82d45e-b150-5d35-9794-9e58f837ba8d disabled=true
                                            projected_action_0095 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/1/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3c80039d-7345-5753-a03c-ff545ab37670 disabled=true
                                            projected_action_0096 = robot.dwell(
                                                duration_ms=500,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e475e3f5-d9da-5a22-bec9-80e81138431e disabled=true
                                            projected_action_0097 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.home',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=29a9ef30-1043-55d0-a8de-951f430ac88b disabled=true
                                            projected_action_0098 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                        # [BRANCH ELSE（互斥分支）] robot_tool_pick@body/0/else 的静态审阅分支。
                                        # unilab:node_uuid=84010984-76a8-59fc-8a37-861a2ee999db
                                        with group(name='ELSE（互斥分支）'):
                                            # [FLATTENED CONTROL raise] 只读来源校验 robot_tool_pick@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=ba9c1946-fc43-539c-8d15-a2b3352022e7 disabled=true
                                            projected_control_0099 = material.review_control_node_v1(
                                                operation_name='robot_tool_pick',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='70c2a7e291023e9375102dc659639ba2604e87ffa8a3a94cca033c80b83c21e8',
                                            )
                            # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/else 的静态审阅分支。
                            # unilab:node_uuid=66620ec7-869d-53fc-8794-83197aa52cac
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=b288d606-77c6-5480-b6b8-88437137f1aa disabled=true
                                projected_control_0100 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3',
                                    control_kind='if',
                                    expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                                )
                    # [CONTROL if] 来源 robot_scrape_holder_pick_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.pick-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_to...
                    # unilab:node_uuid=355f5e5c-d951-54d7-9218-aec894616053
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_scrape_holder_pick_enter@body/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=5626dbac-14c6-57fa-ad65-a727bdfda6bc disabled=true
                        projected_control_0101 = material.review_control_node_v1(
                            operation_name='robot_scrape_holder_pick_enter',
                            node_path='body/3',
                            control_kind='if',
                            expected_sha256='54bddca290173db9b7a87509722da4384ba9ae57b88faef9c3a9d2395e972fc5',
                        )
                        # [BRANCH THEN（互斥分支）] robot_scrape_holder_pick_enter@body/3/then 的静态审阅分支。
                        # unilab:node_uuid=6a1236f0-2b37-5c94-9569-2aa71032fda9
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_pick_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=f991b4d4-3595-59c6-ada9-37e5a022119e disabled=true
                            projected_action_0102 = robot.require_anchor(
                                point_id='P1',
                            )
                            # [ACTION rail.ensure] 来源 robot_scrape_holder_pick_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=d5f044c1-03e3-5664-8dd1-d2eb193e93ab disabled=true
                            projected_action_0103 = rail.ensure(
                                Rail_Target_Position=2,
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_enter@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P67"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=c769fd81-d0fb-54d4-9e38-73878feb22d1 disabled=true
                            projected_action_0104 = robot.move_to_point(
                                point_id_or_robot_name='P67',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=64018ac3-7446-5750-a49b-46d290f55088 disabled=true
                            projected_action_0105 = robot.move_to_point(
                                point_id_or_robot_name='scrape-holder-pick.far',
                            )
                            # [ACTION robot.tool_action] 来源 robot_scrape_holder_pick_enter@body/3/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=0ce25370-96a1-5705-8ec7-f89665a9c977 disabled=true
                            projected_action_0106 = robot.tool_action(
                                action='gripper-open',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=a32380ef-fbaf-5c09-a225-9259e1ae4b25 disabled=true
                            projected_action_0107 = robot.move_to_point(
                                point_id_or_robot_name='scrape-holder-pick.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_enter@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P77"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=00844699-a026-58ef-b6e8-a5ccecc2b70e disabled=true
                            projected_action_0108 = robot.move_to_point(
                                point_id_or_robot_name='P77',
                            )
                            # [ACTION robot.tool_action] 来源 robot_scrape_holder_pick_enter@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=00f2d00d-24f3-5134-aa3d-9ee50d9cd62e disabled=true
                            projected_action_0109 = robot.tool_action(
                                action='gripper-close',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_pick_enter@body/3/then/8；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P77"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=576b26e3-8b79-55dc-81e6-fdc1540e671e disabled=true
                            projected_action_0110 = robot.require_anchor(
                                point_id='P77',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_scrape_holder_pick_enter@body/3/else 的静态审阅分支。
                        # unilab:node_uuid=b531f38e-c500-5eac-b3fa-79cbfcca552f
                        with group(name='ELSE（互斥分支）'):
                            # [CONTROL raise] 来源 robot_scrape_holder_pick_enter@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.pick-enter: 无效选择值"},"op":"raise"}
                            # unilab:node_uuid=7e8b06a9-f8ae-5660-9aaf-0deb95f3ca04
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_scrape_holder_pick_enter@body/3/else/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=342cdd2f-5d9e-5b9f-809a-4026655fa7b8 disabled=true
                                projected_control_0111 = material.review_control_node_v1(
                                    operation_name='robot_scrape_holder_pick_enter',
                                    node_path='body/3/else/0',
                                    control_kind='raise',
                                    expected_sha256='10a3942e9af994de26601221bf44e912fde18a6269074a37f4f55e7a96e1a1aa',
                                )
                # [CONTROL comment] 来源 collect_load@body/5；原节点 {"op":"comment","text":"接粉收集器释放: 下压气缸松开后由机器人取走"}
                # unilab:node_uuid=a6ed6a03-0f37-5f5f-8e3a-dc7c71bfd853
                with group(name='说明 · 接粉收集器释放: 下压气缸松开后由机器人取走'):
                    # [VERIFY comment] 只读来源校验 collect_load@body/5；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=1fedbee7-be96-5ac8-8ac5-0ff9795dcd89 disabled=true
                    projected_control_0112 = material.review_control_node_v1(
                        operation_name='collect_load',
                        node_path='body/5',
                        control_kind='comment',
                        expected_sha256='7c0ef7f227c336e9697ef24f8f07ce3f0d0410971705a91a6533066cf9205b0d',
                    )
                # [ACTION photoscrape.press_cylinder] 来源 collect_load@body/6；原节点 {"action":"photoscrape.press_cylinder","args":{"pressed":{"lit":false}},"mode":"RUN","op":"call"}
                # unilab:node_uuid=9fa16ec2-8bbb-5005-94ff-9cb65887e708 disabled=true
                projected_action_0113 = photoscrape.press_cylinder(
                    pressed=False,
                )
                # [SUBWORKFLOW robot_scrape_holder_pick_exit] 由 collect_load@body/7 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=7dae9a86-0376-51c9-a23b-565659b82b8c
                with group(name='↳ robot_scrape_holder_pick_exit'):
                    # [CONTROL if] 来源 robot_scrape_holder_pick_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.pick-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P77"},"pos_tol...
                    # unilab:node_uuid=f0b96f6b-84c8-5f27-9ba7-f8166f1ff152
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_scrape_holder_pick_exit@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=9e3871b8-28d8-56c6-8594-32068b39c314 disabled=true
                        projected_control_0114 = material.review_control_node_v1(
                            operation_name='robot_scrape_holder_pick_exit',
                            node_path='body/0',
                            control_kind='if',
                            expected_sha256='4cdf772c3843f2bb01be941535f7816b0d728dadf8c2e8216ad1bbbfb8e09b91',
                        )
                        # [BRANCH THEN（互斥分支）] robot_scrape_holder_pick_exit@body/0/then 的静态审阅分支。
                        # unilab:node_uuid=2f777af1-2e12-560c-814a-1c727a00f58b
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_pick_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P77"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=dc48178f-75a2-51cf-bd68-4a5e88cbbf9a disabled=true
                            projected_action_0115 = robot.require_anchor(
                                point_id='P77',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.retreat-0"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=78f5105e-b383-51e3-b235-c75b2ff36f51 disabled=true
                            projected_action_0116 = robot.move_to_point(
                                point_id_or_robot_name='scrape-holder-pick.retreat-0',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.retreat-1"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=c8d3826e-371f-51cd-afae-fba81320dd6e disabled=true
                            projected_action_0117 = robot.move_to_point(
                                point_id_or_robot_name='scrape-holder-pick.retreat-1',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.retreat-2"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=5988ac6e-95a3-5b58-a878-4afa3f84e310 disabled=true
                            projected_action_0118 = robot.move_to_point(
                                point_id_or_robot_name='scrape-holder-pick.retreat-2',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=cff84754-0f15-56ca-ad20-15d82e34c42e disabled=true
                            projected_action_0119 = robot.move_to_point(
                                point_id_or_robot_name='scrape-holder-pick.far',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P67"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=02487cb9-76b7-524e-b02e-5e1d2fe123e2 disabled=true
                            projected_action_0120 = robot.move_to_point(
                                point_id_or_robot_name='P67',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_scrape_holder_pick_exit@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=36e3be10-0e8a-5dc5-80dc-8b6308655649 disabled=true
                            projected_action_0121 = robot.move_to_point(
                                point_id_or_robot_name='P1',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_scrape_holder_pick_exit@body/0/then/7；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=85e0a841-bade-5870-a8a2-4bf36addf4b5 disabled=true
                            projected_action_0122 = robot.require_anchor(
                                point_id='P1',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_scrape_holder_pick_exit@body/0/else 的静态审阅分支。
                        # unilab:node_uuid=32c11f77-9060-560e-8317-b57dce1f245d
                        with group(name='ELSE（互斥分支）'):
                            # [CONTROL raise] 来源 robot_scrape_holder_pick_exit@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.pick-exit: 无效选择值"},"op":"raise"}
                            # unilab:node_uuid=fecd0944-47e7-5701-b37d-abdcd50e7f38
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_scrape_holder_pick_exit@body/0/else/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=4dbb2503-01fd-583b-a039-bdaeccdd259f disabled=true
                                projected_control_0123 = material.review_control_node_v1(
                                    operation_name='robot_scrape_holder_pick_exit',
                                    node_path='body/0/else/0',
                                    control_kind='raise',
                                    expected_sha256='8ad827fbe1c421b806be759c6159b104d8809f2fd925bf203dab094a6a6aae90',
                                )
                # [CONTROL comment] 来源 collect_load@body/8；原节点 {"op":"comment","text":"刮板侧复位: 接粉收集器已由机器人取走并退出后, 才允许旋转/停旋转气缸复位"}
                # unilab:node_uuid=8a73e670-5e80-5fb8-8806-6a150c830471
                with group(name='说明 · 刮板侧复位: 接粉收集器已由机器人取走并退出后, 才允许旋转/停旋转气缸复位'):
                    # [VERIFY comment] 只读来源校验 collect_load@body/8；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=2e4b24ca-0546-5ccb-ae33-0d971a94dc99 disabled=true
                    projected_control_0124 = material.review_control_node_v1(
                        operation_name='collect_load',
                        node_path='body/8',
                        control_kind='comment',
                        expected_sha256='f7d3fabef020edd0abd77b2b3d02a7a1913f7f5468ed808958fc029d2ce50414',
                    )
                # [ACTION photoscrape.retr_stoprot] 来源 collect_load@body/9；原节点 {"action":"photoscrape.retr_stoprot","mode":"RUN","op":"call"}
                # unilab:node_uuid=39ab9cf2-bcde-57ba-9ae7-b64415189473 disabled=true
                projected_action_0125 = photoscrape.retr_stoprot()
                # [CONTROL comment] 来源 collect_load@body/10；原节点 {"op":"comment","text":"地轨到收集位(位3): 机器人已带接粉收集器回安全位, 再进入收集夹具放置"}
                # unilab:node_uuid=b58cfe69-6f5f-523f-a510-c36e9cc81541
                with group(name='说明 · 地轨到收集位(位3): 机器人已带接粉收集器回安全位, 再进入收集夹具放置'):
                    # [VERIFY comment] 只读来源校验 collect_load@body/10；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=0b569cc5-f75c-5863-bc7a-1f254d7bb2cc disabled=true
                    projected_control_0126 = material.review_control_node_v1(
                        operation_name='collect_load',
                        node_path='body/10',
                        control_kind='comment',
                        expected_sha256='a599c850a2345e0d6b5a5f95acddcfd69be56dbe8c2ed1470c21c3ebb0e9884d',
                    )
                # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 collect_load@body/11；节点在本工作流中静态 disabled。
                # unilab:node_uuid=5b6618cc-d260-5de2-bd9d-36f69fb8419e disabled=true
                projected_control_0127 = material.review_control_node_v1(
                    operation_name='collect_load',
                    node_path='body/11',
                    control_kind='run_script',
                    expected_sha256='bf39d5fee5e30f2c2c8447a9aa8faca66191d5b50f05761d5f386539cf15e65f',
                )
                # [CONTROL comment] 来源 collect_load@body/12；原节点 {"op":"comment","text":"放料/收集夹具: 放入接粉收集器, 本站夹紧, 机器人退出"}
                # unilab:node_uuid=f14ba6c0-456d-51d6-9487-4f1402546a61
                with group(name='说明 · 放料/收集夹具: 放入接粉收集器, 本站夹紧, 机器人退出'):
                    # [VERIFY comment] 只读来源校验 collect_load@body/12；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=e30b2384-1d34-516f-9578-5278b2c17fa6 disabled=true
                    projected_control_0128 = material.review_control_node_v1(
                        operation_name='collect_load',
                        node_path='body/12',
                        control_kind='comment',
                        expected_sha256='29c7bf947379bb7250523912b24eb9a4853bb304924068335784b0d97eae457f',
                    )
                # [SUBWORKFLOW robot_collect_holder_put_enter] 由 collect_load@body/13 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=8f2a9c64-a637-52e8-bbfd-80abd01fb005
                with group(name='↳ robot_collect_holder_put_enter'):
                    # [CONTROL comment] 来源 robot_collect_holder_put_enter@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)"}
                    # unilab:node_uuid=82b0e133-9b90-5797-9306-a5518cc19fc9
                    with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)'):
                        # [VERIFY comment] 只读来源校验 robot_collect_holder_put_enter@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=9d79f78f-67b1-5483-bb82-01fc3de0ba68 disabled=true
                        projected_control_0129 = material.review_control_node_v1(
                            operation_name='robot_collect_holder_put_enter',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
                        )
                    # [ACTION robot.home_ensure] 来源 robot_collect_holder_put_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                    # unilab:node_uuid=d4960f9c-7328-58bc-82da-4f0c9ec381d8 disabled=true
                    projected_action_0130 = robot.home_ensure()
                    # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_collect_holder_put_enter@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=abf9fdb1-7786-5010-9731-5ecdcf9a2f89 disabled=true
                    projected_control_0131 = material.review_control_node_v1(
                        operation_name='robot_collect_holder_put_enter',
                        node_path='body/2',
                        control_kind='run_script',
                        expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
                    )
                    # [CONTROL if] 来源 robot_collect_holder_put_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.put-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_to...
                    # unilab:node_uuid=51d9b00d-5525-5ff5-9a39-bfd085594d7b
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_collect_holder_put_enter@body/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=79f28b4c-0410-5bfe-a930-ab0e3c445c5e disabled=true
                        projected_control_0132 = material.review_control_node_v1(
                            operation_name='robot_collect_holder_put_enter',
                            node_path='body/3',
                            control_kind='if',
                            expected_sha256='4d81054bb36570a2980ffe064460c520586ffd4c3e190a63646325a011a0ee8d',
                        )
                        # [BRANCH THEN（互斥分支）] robot_collect_holder_put_enter@body/3/then 的静态审阅分支。
                        # unilab:node_uuid=cc5ab831-7e2d-50e6-b2e1-1c135eaead98
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collect_holder_put_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=0b731580-98f0-5bb6-abf5-17b3e72efaed disabled=true
                            projected_action_0133 = robot.require_anchor(
                                point_id='P1',
                            )
                            # [ACTION rail.ensure] 来源 robot_collect_holder_put_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=260550dd-514d-5c7e-b2c7-fc372186e21f disabled=true
                            projected_action_0134 = rail.ensure(
                                Rail_Target_Position=3,
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_enter@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=8639d77e-9adc-5ce5-98b8-7da93ffdbebd disabled=true
                            projected_action_0135 = robot.move_to_point(
                                point_id_or_robot_name='P70',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-put.far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=59d0bbd8-bef7-555d-8dc1-b984252ccb4a disabled=true
                            projected_action_0136 = robot.move_to_point(
                                point_id_or_robot_name='collect-holder-put.far',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_enter@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=a2bdb5ad-bb5c-5e2e-81f4-2291aa23af17 disabled=true
                            projected_action_0137 = robot.move_to_point(
                                point_id_or_robot_name='collect-holder-put.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P73"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=033efb03-f40e-5fb0-bc65-0d6e8e596ae7 disabled=true
                            projected_action_0138 = robot.move_to_point(
                                point_id_or_robot_name='P73',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collect_holder_put_enter@body/3/then/6；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P73"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=4e54442c-0c3c-524e-9d0a-4f476d05d8ef disabled=true
                            projected_action_0139 = robot.require_anchor(
                                point_id='P73',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_collect_holder_put_enter@body/3/else 的静态审阅分支。
                        # unilab:node_uuid=f653f063-dc17-559c-82eb-e915d3a72468
                        with group(name='ELSE（互斥分支）'):
                            # [CONTROL raise] 来源 robot_collect_holder_put_enter@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.put-enter: 无效选择值"},"op":"raise"}
                            # unilab:node_uuid=cdc6a2fe-0f20-55e8-9b1d-38d654bc1d89
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_collect_holder_put_enter@body/3/else/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=a57618fe-d1e7-5c2e-abc6-23eded97a87b disabled=true
                                projected_control_0140 = material.review_control_node_v1(
                                    operation_name='robot_collect_holder_put_enter',
                                    node_path='body/3/else/0',
                                    control_kind='raise',
                                    expected_sha256='28f4b762a315a533e9e04aced9d44189e64a426dcf5129981795664622a4a3ee',
                                )
                # [ACTION collect.clamp] 来源 collect_load@body/14；原节点 {"action":"collect.clamp","mode":"RUN","op":"call"}
                # unilab:node_uuid=fccfbb2b-e3c4-53bb-b60a-4e3fbc4910a4 disabled=true
                projected_action_0141 = collect.clamp()
                # [SUBWORKFLOW robot_collect_holder_put_exit] 由 collect_load@body/15 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=eefc7d8f-d952-57de-b546-a097443ee57f
                with group(name='↳ robot_collect_holder_put_exit'):
                    # [CONTROL if] 来源 robot_collect_holder_put_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.put-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P73"},"pos_tol...
                    # unilab:node_uuid=d6ae0232-9925-57ce-be32-fb61d0e95c87
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_collect_holder_put_exit@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=4c85ff3f-fa4f-5889-8483-4d23f6dc081d disabled=true
                        projected_control_0142 = material.review_control_node_v1(
                            operation_name='robot_collect_holder_put_exit',
                            node_path='body/0',
                            control_kind='if',
                            expected_sha256='a3aa46084d0ea108b59e38c5ce3c41e308a6fc9c20c808ffa6c9ae9b2dbae8fe',
                        )
                        # [BRANCH THEN（互斥分支）] robot_collect_holder_put_exit@body/0/then 的静态审阅分支。
                        # unilab:node_uuid=6525cfcb-f0e7-5494-99de-1e67356d9f83
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collect_holder_put_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P73"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=b6984f3e-0ef6-5b5c-ad6d-dd6a5079684e disabled=true
                            projected_action_0143 = robot.require_anchor(
                                point_id='P73',
                            )
                            # [ACTION robot.tool_action] 来源 robot_collect_holder_put_exit@body/0/then/1；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=f917827e-99f1-5d2a-aacf-ebfe0b4cad7b disabled=true
                            projected_action_0144 = robot.tool_action(
                                action='gripper-open',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_exit@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=4ef4280b-29b3-52bc-97da-fd9591a6252c disabled=true
                            projected_action_0145 = robot.move_to_point(
                                point_id_or_robot_name='collect-holder-put.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=f90d0c90-ca2a-5dbd-88d7-d09d9996d725 disabled=true
                            projected_action_0146 = robot.move_to_point(
                                point_id_or_robot_name='collect-holder-put.far',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_exit@body/0/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=2c2e3742-a0ed-5295-b8ee-0f9d8f330fca disabled=true
                            projected_action_0147 = robot.move_to_point(
                                point_id_or_robot_name='P70',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_put_exit@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=c9b19445-6e33-5f28-afea-7188814d15c5 disabled=true
                            projected_action_0148 = robot.move_to_point(
                                point_id_or_robot_name='P1',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collect_holder_put_exit@body/0/then/6；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=7b2c0182-c828-5ecb-9dee-ee02b701735c disabled=true
                            projected_action_0149 = robot.require_anchor(
                                point_id='P1',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_collect_holder_put_exit@body/0/else 的静态审阅分支。
                        # unilab:node_uuid=491b8553-7558-5251-8b5e-fdc229cc9199
                        with group(name='ELSE（互斥分支）'):
                            # [CONTROL raise] 来源 robot_collect_holder_put_exit@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.put-exit: 无效选择值"},"op":"raise"}
                            # unilab:node_uuid=9bc14ad4-e9eb-5b7e-ac55-e29607f10f75
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_collect_holder_put_exit@body/0/else/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=030ce370-ac1d-5c13-ab75-c7383297f143 disabled=true
                                projected_control_0150 = material.review_control_node_v1(
                                    operation_name='robot_collect_holder_put_exit',
                                    node_path='body/0/else/0',
                                    control_kind='raise',
                                    expected_sha256='697f5435718fb591b5ef7749d1aa903038695d353ee9c2ad32b48a7adc755b13',
                                )
                # [ACTION collect.extend] 来源 collect_load@body/16；原节点 {"action":"collect.extend","mode":"RUN","op":"call"}
                # unilab:node_uuid=ea26518d-ba10-5099-a3bb-8bcaae26dfdc disabled=true
                projected_action_0151 = collect.extend()
                # [CONTROL comment] 来源 collect_load@body/17；原节点 {"op":"comment","text":"放料/收集瓶: 从中转B取单瓶并放入收集位; 中转B板锁不在本站上料段控制"}
                # unilab:node_uuid=05c437da-69b2-51b3-aa9f-e9272da8f6aa
                with group(name='说明 · 放料/收集瓶: 从中转B取单瓶并放入收集位; 中转B板锁不在本站上料段控制'):
                    # [VERIFY comment] 只读来源校验 collect_load@body/17；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=d5a4bf90-9ae4-5abd-84cd-04025fec251c disabled=true
                    projected_control_0152 = material.review_control_node_v1(
                        operation_name='collect_load',
                        node_path='body/17',
                        control_kind='comment',
                        expected_sha256='a61d68f877adc716b848e4638c7fddbabc613fc38c27a409acb7ecf8ffe78f72',
                    )
                # [SUBWORKFLOW transfer_bottle_staging_b_to_collect] 由 collect_load@body/18 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=634b2bd4-05d0-5eb0-b4f9-c307a40f3a10
                with group(name='↳ transfer_bottle_staging_b_to_collect'):
                    # [CONTROL comment] 来源 transfer_bottle_staging_b_to_collect@body/0；原节点 {"op":"comment","text":"中转B定位气缸保持动点后, 再从中转B取单瓶 (对称于 transfer_collector_staging_a_to_scrape; 板不压住会被小夹爪整块带走)"}
                    # unilab:node_uuid=a81a8a01-c7b2-5e00-8536-3cc48f25f7cd
                    with group(name='说明 · 中转B定位气缸保持动点后, 再从中转B取单瓶 (对称于 transfer_collector_staging_a'):
                        # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_collect@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=26a7046b-dd72-5adf-845b-4cbcb6e9cb64 disabled=true
                        projected_control_0153 = material.review_control_node_v1(
                            operation_name='transfer_bottle_staging_b_to_collect',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='689def4f830e57173646dd6a5ef11ece7baefcad5320003979c4641492934528',
                        )
                    # [ACTION staging_a.locator_b] 来源 transfer_bottle_staging_b_to_collect@body/1；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=34e0131a-4a05-5b35-b00d-d3bf95bdae8f disabled=true
                    projected_action_0154 = staging_a.locator_b(
                        target=True,
                    )
                    # [CONTROL comment] 来源 transfer_bottle_staging_b_to_collect@body/2；原节点 {"op":"comment","text":"从中转B取单瓶 —— 地轨由 robot_individual_pick enter 处 rail.ensure(3) 自动到位"}
                    # unilab:node_uuid=790e656b-bf11-59a8-a248-41a98def8aa4
                    with group(name='说明 · 从中转B取单瓶 —— 地轨由 robot_individual_pick enter 处 rail.ensure'):
                        # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_collect@body/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=6dc5e2fe-053d-50f5-bf8e-15bad2be154f disabled=true
                        projected_control_0155 = material.review_control_node_v1(
                            operation_name='transfer_bottle_staging_b_to_collect',
                            node_path='body/2',
                            control_kind='comment',
                            expected_sha256='a3ef62d89f9507ece1746554ff4bc2fd8308f0caed6228a0c8df9b9f0ea37336',
                        )
                    # [SUBWORKFLOW robot_individual_pick] 由 transfer_bottle_staging_b_to_collect@body/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=3e070cf3-9105-57d1-a995-4438150c436b
                    with group(name='↳ robot_individual_pick'):
                        # [CONTROL comment] 来源 robot_individual_pick@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)"}
                        # unilab:node_uuid=27350a21-ea79-5d33-ab13-e7bdfc5c5a9e
                        with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)'):
                            # [VERIFY comment] 只读来源校验 robot_individual_pick@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=9ff201cf-f942-52d2-a06f-5d9537095d0b disabled=true
                            projected_control_0156 = material.review_control_node_v1(
                                operation_name='robot_individual_pick',
                                node_path='body/0',
                                control_kind='comment',
                                expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
                            )
                        # [ACTION robot.home_ensure] 来源 robot_individual_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                        # unilab:node_uuid=b76ad888-6a65-5e12-bdad-ed695a14dbe3 disabled=true
                        projected_action_0157 = robot.home_ensure()
                        # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_individual_pick@body/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=0c1ca1bc-23db-5c41-ab68-82cd74c3e6df disabled=true
                        projected_control_0158 = material.review_control_node_v1(
                            operation_name='robot_individual_pick',
                            node_path='body/2',
                            control_kind='run_script',
                            expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
                        )
                        # [CONTROL if] 来源 robot_individual_pick@body/3；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"right":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit"...
                        # unilab:node_uuid=7edf9a2d-2aa2-5d9b-abb2-c5d9021b91db
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_individual_pick@body/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=c5bdf566-d325-57a8-beea-1f1389913059 disabled=true
                            projected_control_0159 = material.review_control_node_v1(
                                operation_name='robot_individual_pick',
                                node_path='body/3',
                                control_kind='if',
                                expected_sha256='10ac28536da762f8be3b04b3bc814687c2e9427c2573ad6aeac2f3378299f9d1',
                            )
                            # [BRANCH THEN（互斥分支）] robot_individual_pick@body/3/then 的静态审阅分支。
                            # unilab:node_uuid=4514081e-e2d7-55bc-bace-0fc8b43b2079
                            with group(name='THEN（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8720d490-3ac1-537f-896b-aa55a164e7db disabled=true
                                projected_action_0160 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=032bc26b-216d-5a9e-a1f9-4f406c7c84c1 disabled=true
                                projected_action_0161 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e00e2752-1cb9-5d2c-988b-c899544bb930 disabled=true
                                projected_action_0162 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3ae8797a-6fde-5e85-9743-95f80823a472 disabled=true
                                projected_action_0163 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p46.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=67a213b7-c3ff-5563-b05d-f545c7db735c disabled=true
                                projected_action_0164 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=26c1f6ea-b317-55d5-8057-1fc8e56ed5fb disabled=true
                                projected_action_0165 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p46.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P46"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d6ac2ddc-018c-5b2b-870d-959b16c526c8 disabled=true
                                projected_action_0166 = robot.move_to_point(
                                    point_id_or_robot_name='P46',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=5e1e80ef-2513-5aa9-a03c-57da11480eba disabled=true
                                projected_action_0167 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9afc19bc-26a1-5150-bbf5-cc982ccd3c0b disabled=true
                                projected_action_0168 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p46.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=dd9883c1-6d7f-52c7-a6dd-a09e000937e1 disabled=true
                                projected_action_0169 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p46.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=88901c3f-0176-5781-8add-df8aca1c0c40 disabled=true
                                projected_action_0170 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d436b04c-fc6c-56c5-84e8-7a010440a386 disabled=true
                                projected_action_0171 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/then/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=13674a73-d83a-5abc-8035-6a16d87f71f9 disabled=true
                                projected_action_0172 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 1（互斥分支）] robot_individual_pick@body/3/elifs/0/body 的静态审阅分支。
                            # unilab:node_uuid=24a00df7-25ca-526a-9f3e-8e98deb9e432
                            with group(name='ELIF 1（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=06bd00eb-b09b-5538-bd5a-62ed30ac40f7 disabled=true
                                projected_action_0173 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=55ca28c1-bd1a-59c5-9875-6fa6b7a18f95 disabled=true
                                projected_action_0174 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=da36a918-d636-538d-ba79-6dca0ea0cc9e disabled=true
                                projected_action_0175 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1792bdad-07ca-59fb-a895-1d946303f542 disabled=true
                                projected_action_0176 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p47.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=fceafaec-5aa8-5d0b-bc36-d169730ae92c disabled=true
                                projected_action_0177 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e11d99d8-81c5-582a-863a-fdc3564fdf81 disabled=true
                                projected_action_0178 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p47.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P47"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=69b16cf7-f992-5748-af17-b4f342c77fab disabled=true
                                projected_action_0179 = robot.move_to_point(
                                    point_id_or_robot_name='P47',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=71990c10-51b1-5a4d-ad0d-2380a08967df disabled=true
                                projected_action_0180 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=13a11224-f0cc-5e97-937a-8b2d06648067 disabled=true
                                projected_action_0181 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p47.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=71e6a387-40ab-5c51-ab38-74a28f6c716f disabled=true
                                projected_action_0182 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p47.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=88d50dd8-d41f-5c74-80f3-eb845737a99d disabled=true
                                projected_action_0183 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3f0d9991-ba60-5a18-a86f-1292d2005437 disabled=true
                                projected_action_0184 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/0/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=6b885217-5d84-59f6-8a66-b204542b0410 disabled=true
                                projected_action_0185 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 2（互斥分支）] robot_individual_pick@body/3/elifs/1/body 的静态审阅分支。
                            # unilab:node_uuid=46dee757-ebb1-5b07-8db9-de22cd85e7f4
                            with group(name='ELIF 2（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8d69ca45-9e59-5079-8a6b-a496e10a7414 disabled=true
                                projected_action_0186 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d25fc36b-034e-597b-9236-3e9b808dbe38 disabled=true
                                projected_action_0187 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=29a0dc1b-43ea-5107-a487-b0cda9284c97 disabled=true
                                projected_action_0188 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=712b07b1-07e3-5982-b35c-ac64c2c3d40d disabled=true
                                projected_action_0189 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p48.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/1/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=bf788793-09e1-5a0d-932f-441d1e5c50cb disabled=true
                                projected_action_0190 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3c52c109-68da-5cf8-a265-2d8dd8c70073 disabled=true
                                projected_action_0191 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p48.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P48"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=835b602e-f55c-5ba8-b41b-155bb74f031c disabled=true
                                projected_action_0192 = robot.move_to_point(
                                    point_id_or_robot_name='P48',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d906a78f-4528-5ccd-8f28-cc598d65e8bf disabled=true
                                projected_action_0193 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=5d9fb670-df42-58ff-99bc-9361dbbedf05 disabled=true
                                projected_action_0194 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p48.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=49697a32-4432-526b-bb03-e375b62f06e9 disabled=true
                                projected_action_0195 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p48.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e713d307-4464-5bc3-b790-8c4532190ef6 disabled=true
                                projected_action_0196 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2f905a93-ae03-5fb5-b169-ea86749d48cb disabled=true
                                projected_action_0197 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/1/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=442189b5-494f-56a2-ac13-040e36aa9a41 disabled=true
                                projected_action_0198 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 3（互斥分支）] robot_individual_pick@body/3/elifs/2/body 的静态审阅分支。
                            # unilab:node_uuid=04587cbc-8eea-597a-9d3e-ad47e5776332
                            with group(name='ELIF 3（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=85a4a35f-b187-5f81-8914-a39770a412f5 disabled=true
                                projected_action_0199 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2258434e-9bf7-5efd-8a1f-45b56ad4c5e2 disabled=true
                                projected_action_0200 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=897b5a2a-cda7-50f4-ad1e-5735bb776cc6 disabled=true
                                projected_action_0201 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d3d64ae3-181e-5310-9fb6-c0ad9d71d815 disabled=true
                                projected_action_0202 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p49.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/2/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b4a1e3ba-c757-580d-b0ce-ee0485a34dae disabled=true
                                projected_action_0203 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a941d59d-b84b-5949-b138-3d5b9b201830 disabled=true
                                projected_action_0204 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p49.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P49"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=044d63cc-a6c7-5382-9e07-caa696740641 disabled=true
                                projected_action_0205 = robot.move_to_point(
                                    point_id_or_robot_name='P49',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/2/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=20c28e6c-21ca-552b-920b-5deedc5947e9 disabled=true
                                projected_action_0206 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=53a81784-1a57-59d9-a6a4-bf5617e9b0a4 disabled=true
                                projected_action_0207 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p49.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0a0cd5e3-4f53-579c-b3f3-7633db420ea5 disabled=true
                                projected_action_0208 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p49.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9880ba2e-2381-55a9-8351-7006998ab90b disabled=true
                                projected_action_0209 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=bfecab82-ad4f-5b8b-911a-38cb323c89c9 disabled=true
                                projected_action_0210 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/2/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b898ccb9-d16f-5332-9c24-24aeef4741c1 disabled=true
                                projected_action_0211 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 4（互斥分支）] robot_individual_pick@body/3/elifs/3/body 的静态审阅分支。
                            # unilab:node_uuid=8839bdd5-239b-51f5-9e1f-2583ca8a5d7b
                            with group(name='ELIF 4（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8366f0ed-8c86-5861-b0b5-c39583158eb4 disabled=true
                                projected_action_0212 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=59c56d02-df44-510a-81d4-2c655584cbc7 disabled=true
                                projected_action_0213 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f45fbcfa-6ddb-55ce-b8de-d0f17440e592 disabled=true
                                projected_action_0214 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b97af874-8cc0-564e-bed0-cc20f463c0dd disabled=true
                                projected_action_0215 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p50.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/3/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2ac962db-33d1-590c-b37b-93f29ecaa8dd disabled=true
                                projected_action_0216 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e0107b01-a23a-5ff8-82b3-7c7e9069a7ce disabled=true
                                projected_action_0217 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p50.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P50"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c731fdbc-185f-5808-8038-6a3b057f20ce disabled=true
                                projected_action_0218 = robot.move_to_point(
                                    point_id_or_robot_name='P50',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/3/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c8da8f21-c0a0-5662-96ea-316e4c096a36 disabled=true
                                projected_action_0219 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0f5db970-3675-5fd1-a6ad-dd265d3a8151 disabled=true
                                projected_action_0220 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p50.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f6d03ea9-eeca-5368-a751-1a5c2763e5a8 disabled=true
                                projected_action_0221 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p50.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=157dbe22-b3f7-511f-a220-8fc14a649692 disabled=true
                                projected_action_0222 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=243e4e2f-05f3-5ec6-8a4a-d7ac8b8fd478 disabled=true
                                projected_action_0223 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/3/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=582096b2-b070-5804-8248-0a89a0c45528 disabled=true
                                projected_action_0224 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 5（互斥分支）] robot_individual_pick@body/3/elifs/4/body 的静态审阅分支。
                            # unilab:node_uuid=bae93dbd-007c-5507-92b6-8702c149d5b5
                            with group(name='ELIF 5（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=6a23b202-fd2a-589b-a756-60064340d745 disabled=true
                                projected_action_0225 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=7d0fe3a7-28de-5292-a83a-580b80d708be disabled=true
                                projected_action_0226 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=bd11e95f-66d7-53b9-b94b-c2f6fdcc9fe1 disabled=true
                                projected_action_0227 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=59b0bd22-c12c-547d-a58c-1640893ce1a9 disabled=true
                                projected_action_0228 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p51.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/4/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d124a06c-fa45-5019-be9f-3e9b0843cccd disabled=true
                                projected_action_0229 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4a7adfde-8fd1-512a-9adf-bda41b275938 disabled=true
                                projected_action_0230 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p51.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P51"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=91f06e12-09af-578c-b3d2-ef2b8308e138 disabled=true
                                projected_action_0231 = robot.move_to_point(
                                    point_id_or_robot_name='P51',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/4/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d27bae2a-9d37-5bbc-8278-a03f189cb013 disabled=true
                                projected_action_0232 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=cfb93885-a9dc-5ff3-97f2-1c2663696fcd disabled=true
                                projected_action_0233 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p51.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=31d5d617-c06d-5809-8e88-52568a0b8eac disabled=true
                                projected_action_0234 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p51.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e8904d7d-b103-55cb-bd6c-27eb18175aa0 disabled=true
                                projected_action_0235 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a4d24fb8-45fd-5796-a639-4d296d0643d3 disabled=true
                                projected_action_0236 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/4/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c60e8089-b647-51ab-a380-754b8f5567f4 disabled=true
                                projected_action_0237 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 6（互斥分支）] robot_individual_pick@body/3/elifs/5/body 的静态审阅分支。
                            # unilab:node_uuid=37779f29-b187-5f9c-b8e9-c931b35817fc
                            with group(name='ELIF 6（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=face80a4-2b84-59c9-a2cd-d7463dd370e4 disabled=true
                                projected_action_0238 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=72207872-5a77-5524-91b4-58f53315f938 disabled=true
                                projected_action_0239 = rail.ensure(
                                    Rail_Target_Position=3,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c0ddde6a-1ada-5623-bab6-36e18682a251 disabled=true
                                projected_action_0240 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c93af65e-65ad-557c-96dd-33b7a041982d disabled=true
                                projected_action_0241 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p53.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/5/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=33ce1927-6005-59de-999f-1980120af086 disabled=true
                                projected_action_0242 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f78f39d7-ec97-587f-aef3-7078df27d564 disabled=true
                                projected_action_0243 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p53.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P53"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=aea9d532-3f40-5aca-9d65-341ed039b617 disabled=true
                                projected_action_0244 = robot.move_to_point(
                                    point_id_or_robot_name='P53',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/5/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ca055abc-b44f-51b5-b0bc-2b5c720b47fd disabled=true
                                projected_action_0245 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=259e558e-f01e-5e15-800a-3d1d9ca95871 disabled=true
                                projected_action_0246 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p53.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9f3e709e-66ca-5872-91c5-4e4f6d1154fe disabled=true
                                projected_action_0247 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p53.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0f4aa9ec-e806-534a-895e-a259b38dcb86 disabled=true
                                projected_action_0248 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=593d8a5e-7c96-5f0b-a33a-553035f884f3 disabled=true
                                projected_action_0249 = robot.move_to_point(
                                    point_id_or_robot_name='review-only',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/5/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=bf7bb2fa-70f6-5498-94af-c1292aa5afde disabled=true
                                projected_action_0250 = robot.require_anchor(
                                    point_id='review-only',
                                )
                            # [BRANCH ELIF 7（互斥分支）] robot_individual_pick@body/3/elifs/6/body 的静态审阅分支。
                            # unilab:node_uuid=7e321f73-fd57-51bc-bbd7-49ea2e9ac3d5
                            with group(name='ELIF 7（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=99ced2bd-7fe7-5e29-b841-ee2e4788da80 disabled=true
                                projected_action_0251 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=12b3ea00-d28b-56b9-a645-ddc3c96e6eb8 disabled=true
                                projected_action_0252 = rail.ensure(
                                    Rail_Target_Position=3,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e0fa31f1-1446-5aa4-b0e4-9b368b9ce8bf disabled=true
                                projected_action_0253 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=428c8194-ee72-5a80-88c0-e54bd753b5e2 disabled=true
                                projected_action_0254 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p54.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/6/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b408b07e-916a-5f78-ad75-14aba7304d9d disabled=true
                                projected_action_0255 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0c0a7647-4baf-5732-b1aa-63cd41752510 disabled=true
                                projected_action_0256 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p54.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P54"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1e0ace91-814d-5062-8704-b23960531915 disabled=true
                                projected_action_0257 = robot.move_to_point(
                                    point_id_or_robot_name='P54',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/6/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a468b7af-1c29-532b-83a4-cdb04e97c344 disabled=true
                                projected_action_0258 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b600abae-a760-50da-b032-71b5d9a5da91 disabled=true
                                projected_action_0259 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p54.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=5bc75a80-12bc-50f4-97a2-f08d42a414cf disabled=true
                                projected_action_0260 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p54.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=87abd8e6-ef39-5f83-b3be-993166766ac2 disabled=true
                                projected_action_0261 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=91ea2d6f-051f-5630-9982-9a30af214a96 disabled=true
                                projected_action_0262 = robot.move_to_point(
                                    point_id_or_robot_name='review-only',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/6/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9a1b2257-0585-5304-beae-acea8b7a6bb2 disabled=true
                                projected_action_0263 = robot.require_anchor(
                                    point_id='review-only',
                                )
                            # [BRANCH ELIF 8（互斥分支）] robot_individual_pick@body/3/elifs/7/body 的静态审阅分支。
                            # unilab:node_uuid=f4d66576-0002-51d9-8da3-e5c81d9f0b02
                            with group(name='ELIF 8（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/7/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e9bad54f-f74a-5d94-9033-1113e91c7045 disabled=true
                                projected_action_0264 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/7/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8317152e-b5a0-57b5-83ef-f7089845714c disabled=true
                                projected_action_0265 = rail.ensure(
                                    Rail_Target_Position=3,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2f89291e-3596-5947-adb2-7c5ac6a6f47f disabled=true
                                projected_action_0266 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=49f355fa-966a-58d9-873e-a109915a7f2b disabled=true
                                projected_action_0267 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p55.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/7/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=552f6b57-dadb-5c59-9026-9e71247b339a disabled=true
                                projected_action_0268 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1d5518f3-812b-5944-b25e-3d2b11cdd477 disabled=true
                                projected_action_0269 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p55.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P55"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=51c0d347-0d38-5fdc-974c-1a321ec24e40 disabled=true
                                projected_action_0270 = robot.move_to_point(
                                    point_id_or_robot_name='P55',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/7/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b185e099-5db3-5b41-a469-b04ab4c0ebb6 disabled=true
                                projected_action_0271 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1cb85b07-c7ad-5201-9a18-af19f39b0e3a disabled=true
                                projected_action_0272 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p55.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4bd51393-ea83-5dd1-b6e2-f4aba5262625 disabled=true
                                projected_action_0273 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p55.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4915e53b-a08b-5d2b-96fa-be6eaacea569 disabled=true
                                projected_action_0274 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=44f782e7-b4c4-5df5-83e4-77e81db00fd7 disabled=true
                                projected_action_0275 = robot.move_to_point(
                                    point_id_or_robot_name='review-only',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/7/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3e0ca440-4371-59fb-b4f5-3e1a8d9bbe47 disabled=true
                                projected_action_0276 = robot.require_anchor(
                                    point_id='review-only',
                                )
                            # [BRANCH ELIF 9（互斥分支）] robot_individual_pick@body/3/elifs/8/body 的静态审阅分支。
                            # unilab:node_uuid=bc62d9b3-df77-5b8d-ae0b-5f2932ea5bd4
                            with group(name='ELIF 9（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/8/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=7fc3ed37-0505-55ad-8cae-fd69102dd99b disabled=true
                                projected_action_0277 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/8/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2cab4f8e-83eb-54b3-93bd-72741006ba32 disabled=true
                                projected_action_0278 = rail.ensure(
                                    Rail_Target_Position=3,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b1d4e26e-0227-5987-83fe-d21ff314db2f disabled=true
                                projected_action_0279 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=422ecd1c-dc0a-565b-b75a-849fe5a39ff9 disabled=true
                                projected_action_0280 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p56.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/8/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ad3c58b2-045c-5e51-a612-e98fb4939735 disabled=true
                                projected_action_0281 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=28e18587-d941-5e33-b846-9750b19e835d disabled=true
                                projected_action_0282 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p56.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P56"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3bf0410b-2215-594c-8a50-61164edfb26c disabled=true
                                projected_action_0283 = robot.move_to_point(
                                    point_id_or_robot_name='P56',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/8/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=507254be-0904-5b80-9ed2-1d5af5154772 disabled=true
                                projected_action_0284 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4747a588-1287-5bc6-823a-438386a6571e disabled=true
                                projected_action_0285 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p56.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=768fe731-6b35-5480-bf2d-be60904f5235 disabled=true
                                projected_action_0286 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p56.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1340e608-d0a3-547d-88fb-145309a0f79b disabled=true
                                projected_action_0287 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ea24bfc2-25d0-5cf3-9b5c-1e0e3df4e827 disabled=true
                                projected_action_0288 = robot.move_to_point(
                                    point_id_or_robot_name='review-only',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/8/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=39599ae0-944d-54f0-9ac5-7fdc6b2a6652 disabled=true
                                projected_action_0289 = robot.require_anchor(
                                    point_id='review-only',
                                )
                            # [BRANCH ELIF 10（互斥分支）] robot_individual_pick@body/3/elifs/9/body 的静态审阅分支。
                            # unilab:node_uuid=c953037d-fd14-5e29-a3d0-6ca066006a0c
                            with group(name='ELIF 10（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/9/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ab1c5aa0-8158-5258-9507-288dbd06f612 disabled=true
                                projected_action_0290 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/9/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2ead159d-2eae-5d0f-bb77-fd111e552b0f disabled=true
                                projected_action_0291 = rail.ensure(
                                    Rail_Target_Position=3,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a1e48efd-0446-5069-acfa-5f8c63b44deb disabled=true
                                projected_action_0292 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2632a943-3f2a-508f-bb79-5bcfa1c22fe2 disabled=true
                                projected_action_0293 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p57.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/9/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ec104290-e11d-5e7d-8e69-19afe8ba242d disabled=true
                                projected_action_0294 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=bcd52bd1-21a2-5728-8550-234139d228e9 disabled=true
                                projected_action_0295 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p57.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P57"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=145cc96b-3bcb-5473-b708-a6b2d67d0a14 disabled=true
                                projected_action_0296 = robot.move_to_point(
                                    point_id_or_robot_name='P57',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/9/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=74d4aa56-a547-5109-9abe-53a1caf211b2 disabled=true
                                projected_action_0297 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ec559360-3a32-5471-88cb-069607dc3b10 disabled=true
                                projected_action_0298 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p57.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=311330a8-eb48-59c1-a526-0f79bc88c27f disabled=true
                                projected_action_0299 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p57.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=bda60be9-d550-5d60-acb9-412df59bd7fd disabled=true
                                projected_action_0300 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=6a948cd4-9518-581b-8369-ef45286d8892 disabled=true
                                projected_action_0301 = robot.move_to_point(
                                    point_id_or_robot_name='review-only',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/9/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=fdbbb242-56cf-577a-8139-434f530ce72c disabled=true
                                projected_action_0302 = robot.require_anchor(
                                    point_id='review-only',
                                )
                            # [BRANCH ELIF 11（互斥分支）] robot_individual_pick@body/3/elifs/10/body 的静态审阅分支。
                            # unilab:node_uuid=a2d888bc-bc94-52a3-8a44-05b4ca1b838e
                            with group(name='ELIF 11（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/10/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=052692bf-b46b-57c8-b9e7-0a3125f8ae53 disabled=true
                                projected_action_0303 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/10/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3663c746-709e-515f-9c3d-f0a66dcc21d9 disabled=true
                                projected_action_0304 = rail.ensure(
                                    Rail_Target_Position=3,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d3b20aca-436e-5250-badb-02f56fbbdb38 disabled=true
                                projected_action_0305 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=59d20667-51f9-5f99-b893-80211279e67e disabled=true
                                projected_action_0306 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p58.high',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/10/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=5756bf67-bc51-5296-b87e-b79713a942a7 disabled=true
                                projected_action_0307 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=6739b53d-cdd6-59a1-9eaa-a7e578e43df2 disabled=true
                                projected_action_0308 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p58.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P58"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=042c8d9e-9180-5b28-9ff5-6babdadcec6d disabled=true
                                projected_action_0309 = robot.move_to_point(
                                    point_id_or_robot_name='P58',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/10/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=003e264b-17a5-5929-9537-5ca6425659c9 disabled=true
                                projected_action_0310 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d7c8bf28-cea2-5f24-aa85-362d9a1a8220 disabled=true
                                projected_action_0311 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p58.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a9f82647-bbd7-5a69-977f-f4389fe8aa83 disabled=true
                                projected_action_0312 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p58.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=16f334ce-bf03-5f73-814a-a4f5259fe132 disabled=true
                                projected_action_0313 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=7701d517-d485-57bf-8f45-8a2d34fa2db6 disabled=true
                                projected_action_0314 = robot.move_to_point(
                                    point_id_or_robot_name='review-only',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/10/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=938f9313-87fe-5179-9022-3f70430afa07 disabled=true
                                projected_action_0315 = robot.require_anchor(
                                    point_id='review-only',
                                )
                            # [BRANCH ELSE（互斥分支）] robot_individual_pick@body/3/else 的静态审阅分支。
                            # unilab:node_uuid=1de4dad6-8ae6-5e41-9178-f0aafaf1cfa0
                            with group(name='ELSE（互斥分支）'):
                                # [CONTROL raise] 来源 robot_individual_pick@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"individual.pick: 无效选择值"},"op":"raise"}
                                # unilab:node_uuid=f17f28f0-9819-5fad-ba46-b4b39a93c321
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_individual_pick@body/3/else/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=8082e3b3-ef02-5069-9fb2-f34d5d47611b disabled=true
                                    projected_control_0316 = material.review_control_node_v1(
                                        operation_name='robot_individual_pick',
                                        node_path='body/3/else/0',
                                        control_kind='raise',
                                        expected_sha256='cc5774ae8e9be2644c843edf5b39e2745282a7ccdc79ab43f19f14a4f145246d',
                                    )
                    # [CONTROL comment] 来源 transfer_bottle_staging_b_to_collect@body/4；原节点 {"op":"comment","text":"地轨保持收集位(位3, 全程不再移轨); 从 P52 直接交接放瓶到收集工位"}
                    # unilab:node_uuid=a3407420-9786-55d8-a7c6-46abfadb00b9
                    with group(name='说明 · 地轨保持收集位(位3, 全程不再移轨); 从 P52 直接交接放瓶到收集工位'):
                        # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_collect@body/4；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=c87e0734-08b5-58c4-aae4-13baec43424e disabled=true
                        projected_control_0317 = material.review_control_node_v1(
                            operation_name='transfer_bottle_staging_b_to_collect',
                            node_path='body/4',
                            control_kind='comment',
                            expected_sha256='d45be0f3d867f4e176e1fd854935b0fa8881837922a442ef5280c06aa7234a7d',
                        )
                    # [SUBWORKFLOW robot_collect_bottle_put] 由 transfer_bottle_staging_b_to_collect@body/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=5bef4c17-185b-547c-a346-c59867076144
                    with group(name='↳ robot_collect_bottle_put'):
                        # [CONTROL comment] 来源 robot_collect_bottle_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 仅 P1 入口时确保回零+换刀; P52 交接入口由分支锚断言把关 (上游取件流程已保证工具)"}
                        # unilab:node_uuid=3d791d7a-bfcf-5b0c-b6ca-1ff956fbd509
                        with group(name='说明 · 入口保证(手改): 仅 P1 入口时确保回零+换刀; P52 交接入口由分支锚断言把关 (上游取件流程已保证工具'):
                            # [VERIFY comment] 只读来源校验 robot_collect_bottle_put@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=77cc92c8-e104-5350-b276-138c60c6bdaf disabled=true
                            projected_control_0318 = material.review_control_node_v1(
                                operation_name='robot_collect_bottle_put',
                                node_path='body/0',
                                control_kind='comment',
                                expected_sha256='c94f5206680744de11103e2b10080fea2f88c5ec7996c9e333b26f5c605d8f94',
                            )
                        # [CONTROL if] 来源 robot_collect_bottle_put@body/1；原节点 {"cond":{"binop":"==","left":{"var":"enter_anchor"},"right":{"lit":"P1"}},"op":"if","then":[{"action":"robot.home_ensure","mode":"RUN","op":"call"},{"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}]}
                        # unilab:node_uuid=480de17e-a788-50b3-a24d-e6b7743ecc00
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_collect_bottle_put@body/1；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=ef471c68-ad1f-563f-800f-deda478f5bb6 disabled=true
                            projected_control_0319 = material.review_control_node_v1(
                                operation_name='robot_collect_bottle_put',
                                node_path='body/1',
                                control_kind='if',
                                expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
                            )
                            # [BRANCH THEN（互斥分支）] robot_collect_bottle_put@body/1/then 的静态审阅分支。
                            # unilab:node_uuid=3640b343-45c2-5674-adad-40603f9d9292
                            with group(name='THEN（互斥分支）'):
                                # [ACTION robot.home_ensure] 来源 robot_collect_bottle_put@body/1/then/0；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                                # unilab:node_uuid=7caf864d-701a-5eda-9de9-1cf815999eda disabled=true
                                projected_action_0320 = robot.home_ensure()
                                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_collect_bottle_put@body/1/then/1；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=79d0bd5c-af9f-5797-9b6b-cbd14776dfab disabled=true
                                projected_control_0321 = material.review_control_node_v1(
                                    operation_name='robot_collect_bottle_put',
                                    node_path='body/1/then/1',
                                    control_kind='run_script',
                                    expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
                                )
                            # [BRANCH ELSE（互斥分支）] robot_collect_bottle_put@body/1/else 的静态审阅分支。
                            # unilab:node_uuid=d0f82472-467c-5db8-af81-8fa2ac6a6937
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_collect_bottle_put@body/1；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=85e9e0fa-b2f2-5af8-a84f-e28fbc2159e6 disabled=true
                                projected_control_0322 = material.review_control_node_v1(
                                    operation_name='robot_collect_bottle_put',
                                    node_path='body/1',
                                    control_kind='if',
                                    expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
                                )
                        # [CONTROL if] 来源 robot_collect_bottle_put@body/2；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.bottle.put: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_...
                        # unilab:node_uuid=4c2fc2ce-64b4-5c8c-9efd-4a77aa37f3b9
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_collect_bottle_put@body/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=7d111ebe-4cd4-5f6a-b6d5-00d4281ae57c disabled=true
                            projected_control_0323 = material.review_control_node_v1(
                                operation_name='robot_collect_bottle_put',
                                node_path='body/2',
                                control_kind='if',
                                expected_sha256='e9400d3ff591d1e43f0cab25104669e73231ac5a9f8126bce1f2ce939b4474ab',
                            )
                            # [BRANCH THEN（互斥分支）] robot_collect_bottle_put@body/2/then 的静态审阅分支。
                            # unilab:node_uuid=22eee7bc-3ce7-5a15-a699-5201941a61e3
                            with group(name='THEN（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_collect_bottle_put@body/2/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f3df77bf-f2e3-5b6f-9165-4a407a2779ac disabled=true
                                projected_action_0324 = robot.require_anchor(
                                    point_id='review-only',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3f4e4f66-f17a-5618-b2b9-3532ee269930 disabled=true
                                projected_action_0325 = robot.move_to_point(
                                    point_id_or_robot_name='P70',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-put.far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8cda2c9b-5911-5b2d-a1f3-7a60d3709e23 disabled=true
                                projected_action_0326 = robot.move_to_point(
                                    point_id_or_robot_name='collect-bottle-put.far',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f3969ec6-ee85-56ab-8c09-536ea5663f71 disabled=true
                                projected_action_0327 = robot.move_to_point(
                                    point_id_or_robot_name='collect-bottle-put.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P71"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=557e34f0-1b87-531e-acf2-89d013c0e281 disabled=true
                                projected_action_0328 = robot.move_to_point(
                                    point_id_or_robot_name='P71',
                                )
                                # [ACTION robot.tool_action] 来源 robot_collect_bottle_put@body/2/then/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9095aef3-af49-5e82-9687-4e82b327619d disabled=true
                                projected_action_0329 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=fd62cd78-d494-5225-b215-94b6602abfcf disabled=true
                                projected_action_0330 = robot.move_to_point(
                                    point_id_or_robot_name='collect-bottle-put.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3b7114dd-4814-53cd-ab9e-e2cc47e8cb39 disabled=true
                                projected_action_0331 = robot.move_to_point(
                                    point_id_or_robot_name='collect-bottle-put.far',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=dbeb2ce1-6156-5242-ab12-47732c4affaa disabled=true
                                projected_action_0332 = robot.move_to_point(
                                    point_id_or_robot_name='P70',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_put@body/2/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=5a484037-2ba0-5df7-8e4e-4465726630fe disabled=true
                                projected_action_0333 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_collect_bottle_put@body/2/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d4a17876-fac8-55cb-a7a9-1a5196d3422f disabled=true
                                projected_action_0334 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELSE（互斥分支）] robot_collect_bottle_put@body/2/else 的静态审阅分支。
                            # unilab:node_uuid=fdedd37a-6962-51f4-b1df-f26093cf0835
                            with group(name='ELSE（互斥分支）'):
                                # [CONTROL raise] 来源 robot_collect_bottle_put@body/2/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.bottle.put: 无效选择值"},"op":"raise"}
                                # unilab:node_uuid=4353d73f-0f65-55e8-9efb-c52315fb5546
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_collect_bottle_put@body/2/else/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=44471980-23a7-51f8-a8ee-f07a6b6dd912 disabled=true
                                    projected_control_0335 = material.review_control_node_v1(
                                        operation_name='robot_collect_bottle_put',
                                        node_path='body/2/else/0',
                                        control_kind='raise',
                                        expected_sha256='1e4445019c6c0d5841f97876971f21988fceb257969d0a2c50ad2d5ca147769c',
                                    )
            # [CONTROL comment] 来源 collect_cycle@body/4；原节点 {"op":"comment","text":"execute: 进入洗脱姿态 -> 加液/排液洗脱循环 -> 退出洗脱姿态"}
            # unilab:node_uuid=0f5d20f0-0aff-58c5-85ba-e4fae7c7dca1
            with group(name='说明 · execute: 进入洗脱姿态 -> 加液/排液洗脱循环 -> 退出洗脱姿态'):
                # [VERIFY comment] 只读来源校验 collect_cycle@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=43c4d2e5-c44e-5224-bf5b-70784fb4ac77 disabled=true
                projected_control_0336 = material.review_control_node_v1(
                    operation_name='collect_cycle',
                    node_path='body/4',
                    control_kind='comment',
                    expected_sha256='42ac154d7fb9a377e35c732e2f0630943596c7b61b2686b773f1e6b4145f7d0c',
                )
            # [SUBWORKFLOW collect_execute] 由 collect_cycle@body/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=fe2ebcf2-ac00-542a-a499-a2835ff502bb
            with group(name='↳ collect_execute'):
                # [CONTROL comment] 来源 collect_execute@body/0；原节点 {"op":"comment","text":"执行: 升降/下压进入洗脱姿态, 完成设定次数洗脱循环, 再复位到取瓶姿态"}
                # unilab:node_uuid=6d6faa95-5e58-563b-ad45-018656896263
                with group(name='说明 · 执行: 升降/下压进入洗脱姿态, 完成设定次数洗脱循环, 再复位到取瓶姿态'):
                    # [VERIFY comment] 只读来源校验 collect_execute@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=defb84c4-10dc-5e43-a926-7a4bba9d958b disabled=true
                    projected_control_0337 = material.review_control_node_v1(
                        operation_name='collect_execute',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='952af31590e9e80c47dc80310562ff8fc4251c3b2fd05811f3ade379892b49df',
                    )
                # [ACTION collect.lift_press] 来源 collect_execute@body/1；原节点 {"action":"collect.lift_press","mode":"RUN","op":"call"}
                # unilab:node_uuid=69d36a55-9e13-536b-897c-605d82ea72d0 disabled=true
                projected_action_0338 = collect.lift_press()
                # [ACTION collect.collect] 来源 collect_execute@body/2；原节点 {"action":"collect.collect","args":{"liquid_repeat_count":{"var":"liquid_repeat_count"},"solvent_volume_ml":{"var":"solvent_volume_ml"}},"mode":"RUN","op":"call"}
                # unilab:node_uuid=738e0581-b51f-5ebc-92d5-c2d588ceacd3 disabled=true
                projected_action_0339 = collect.collect()
                # [ACTION collect.transport_extend] 来源 collect_execute@body/3；原节点 {"action":"collect.transport_extend","mode":"RUN","op":"call"}
                # unilab:node_uuid=80cfbabb-e1a4-56a3-a8be-60745181dc94 disabled=true
                projected_action_0340 = collect.transport_extend()
            # [CONTROL comment] 来源 collect_cycle@body/6；原节点 {"op":"comment","text":"unload: 先取瓶, 再缩回/松收集夹具并取走接粉收集器"}
            # unilab:node_uuid=91864843-b22f-580f-8734-2f62ab95b0c4
            with group(name='说明 · unload: 先取瓶, 再缩回/松收集夹具并取走接粉收集器'):
                # [VERIFY comment] 只读来源校验 collect_cycle@body/6；节点在本工作流中静态 disabled。
                # unilab:node_uuid=1981225e-7b9a-50c4-957d-7d6f44aebd84 disabled=true
                projected_control_0341 = material.review_control_node_v1(
                    operation_name='collect_cycle',
                    node_path='body/6',
                    control_kind='comment',
                    expected_sha256='962d54e29d53a142d99c9d835188e814d3a9eae6918ee1f446713fa687907f98',
                )
            # [SUBWORKFLOW collect_unload] 由 collect_cycle@body/7 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=9767818b-4e99-5466-9131-e6378dfc2668
            with group(name='↳ collect_unload'):
                # [CONTROL comment] 来源 collect_unload@body/0；原节点 {"op":"comment","text":"先取成品瓶回中转B; 执行段已复位下压/升降并伸出到取瓶位, 中转B板锁由独立补货/回库链处理"}
                # unilab:node_uuid=103a00ab-c3ac-5b35-9c72-b218b61bdc36
                with group(name='说明 · 先取成品瓶回中转B; 执行段已复位下压/升降并伸出到取瓶位, 中转B板锁由独立补货/回库链处理'):
                    # [VERIFY comment] 只读来源校验 collect_unload@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=3967f68c-f8f8-56d4-9024-a291957486ca disabled=true
                    projected_control_0342 = material.review_control_node_v1(
                        operation_name='collect_unload',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='e74de94ebd951ce56e510c2b7a2673722325cc6ae30cf7ea97c783ea7a0c4e60',
                    )
                # [SUBWORKFLOW transfer_bottle_collect_to_staging_b] 由 collect_unload@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=56262d36-4500-5900-9258-20f9592f6889
                with group(name='↳ transfer_bottle_collect_to_staging_b'):
                    # [CONTROL comment] 来源 transfer_bottle_collect_to_staging_b@body/0；原节点 {"op":"comment","text":"从收集工位(位3)取瓶 —— 地轨由 robot_collect_bottle_pick enter 处 rail.ensure(3) 自动到位"}
                    # unilab:node_uuid=bc132b7d-d82a-5e69-a506-2c648d5b7d58
                    with group(name='说明 · 从收集工位(位3)取瓶 —— 地轨由 robot_collect_bottle_pick enter 处 rai'):
                        # [VERIFY comment] 只读来源校验 transfer_bottle_collect_to_staging_b@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=ad5a84f3-adb9-5f45-a0d5-67984b1182b5 disabled=true
                        projected_control_0343 = material.review_control_node_v1(
                            operation_name='transfer_bottle_collect_to_staging_b',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='7c53d8d84eedce4cfa2f61e8169ecbabc51fe6fb45144c059e6c9df08dc2ad0d',
                        )
                    # [SUBWORKFLOW robot_collect_bottle_pick] 由 transfer_bottle_collect_to_staging_b@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=82171b49-37a2-5112-bf59-cc28774decd1
                    with group(name='↳ robot_collect_bottle_pick'):
                        # [CONTROL comment] 来源 robot_collect_bottle_pick@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)"}
                        # unilab:node_uuid=15100d64-ec49-57ef-b5bd-8b738a750d27
                        with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)'):
                            # [VERIFY comment] 只读来源校验 robot_collect_bottle_pick@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=f897452c-30be-55a8-8c7b-eee13a86319b disabled=true
                            projected_control_0344 = material.review_control_node_v1(
                                operation_name='robot_collect_bottle_pick',
                                node_path='body/0',
                                control_kind='comment',
                                expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
                            )
                        # [ACTION robot.home_ensure] 来源 robot_collect_bottle_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                        # unilab:node_uuid=02b23896-d14b-58ea-a7e3-6f25d72da526 disabled=true
                        projected_action_0345 = robot.home_ensure()
                        # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_collect_bottle_pick@body/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=5b8964fd-c428-50f3-b421-ec3143640497 disabled=true
                        projected_control_0346 = material.review_control_node_v1(
                            operation_name='robot_collect_bottle_pick',
                            node_path='body/2',
                            control_kind='run_script',
                            expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
                        )
                        # [CONTROL if] 来源 robot_collect_bottle_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.bottle.pick: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"li...
                        # unilab:node_uuid=58b207d0-a737-542f-a2e7-82861628cc8d
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_collect_bottle_pick@body/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=63fdd55c-40ba-598d-93fd-831a02e70e17 disabled=true
                            projected_control_0347 = material.review_control_node_v1(
                                operation_name='robot_collect_bottle_pick',
                                node_path='body/3',
                                control_kind='if',
                                expected_sha256='259d06699346e86121785c6f63a8fa923bf9cebbaa97c79997da521f7f5fc6c3',
                            )
                            # [BRANCH THEN（互斥分支）] robot_collect_bottle_pick@body/3/then 的静态审阅分支。
                            # unilab:node_uuid=f8a0ec40-00b7-504c-8821-943a845e48b9
                            with group(name='THEN（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_collect_bottle_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f2a24cc6-0b30-566b-a1fe-357d6a6eba3b disabled=true
                                projected_action_0348 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_collect_bottle_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d537d9cb-ee72-5ae6-abb0-71ddbeffd33b disabled=true
                                projected_action_0349 = rail.ensure(
                                    Rail_Target_Position=3,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2025f852-92ef-5055-900b-266d40734493 disabled=true
                                projected_action_0350 = robot.move_to_point(
                                    point_id_or_robot_name='P70',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-pick.far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=02369034-f3c8-56d5-8dc6-7f1acc96a6ca disabled=true
                                projected_action_0351 = robot.move_to_point(
                                    point_id_or_robot_name='collect-bottle-pick.far',
                                )
                                # [ACTION robot.tool_action] 来源 robot_collect_bottle_pick@body/3/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b7ae74a6-2dbb-5a3d-8c91-84584cfd3826 disabled=true
                                projected_action_0352 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2d4f1f79-0b82-5755-9329-d241329f80bc disabled=true
                                projected_action_0353 = robot.move_to_point(
                                    point_id_or_robot_name='collect-bottle-pick.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P72"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e64cbb85-5e36-517b-a0f5-db0abf38e130 disabled=true
                                projected_action_0354 = robot.move_to_point(
                                    point_id_or_robot_name='P72',
                                )
                                # [ACTION robot.tool_action] 来源 robot_collect_bottle_pick@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=093a81a4-24ec-5b4f-a8ff-fb0085201976 disabled=true
                                projected_action_0355 = robot.tool_action(
                                    action='gripper-close',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3dca8359-7299-5f9e-a32b-40a901ac8f79 disabled=true
                                projected_action_0356 = robot.move_to_point(
                                    point_id_or_robot_name='collect-bottle-pick.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-bottle-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1a21ff2d-4afa-59f7-9afd-83282740823a disabled=true
                                projected_action_0357 = robot.move_to_point(
                                    point_id_or_robot_name='collect-bottle-pick.far',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_collect_bottle_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=516c2788-aad4-535e-a2fd-8ba6232e1848 disabled=true
                                projected_action_0358 = robot.move_to_point(
                                    point_id_or_robot_name='P70',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_collect_bottle_pick@body/3/then/11；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P70"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=74794823-0270-58cb-9355-282817ae68fd disabled=true
                                projected_action_0359 = robot.require_anchor(
                                    point_id='P70',
                                )
                            # [BRANCH ELSE（互斥分支）] robot_collect_bottle_pick@body/3/else 的静态审阅分支。
                            # unilab:node_uuid=16c91192-8ed4-5c38-bf7c-dd8c7250c6a2
                            with group(name='ELSE（互斥分支）'):
                                # [CONTROL raise] 来源 robot_collect_bottle_pick@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.bottle.pick: 无效选择值"},"op":"raise"}
                                # unilab:node_uuid=5b5f62e3-6528-5a48-a57e-07002d393564
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_collect_bottle_pick@body/3/else/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=566c5314-6839-5c32-9322-98ba4c355c78 disabled=true
                                    projected_control_0360 = material.review_control_node_v1(
                                        operation_name='robot_collect_bottle_pick',
                                        node_path='body/3/else/0',
                                        control_kind='raise',
                                        expected_sha256='ccec1bdef11cc2d1cb1ffd1a08331b9c9fea90d80bdbd2f42fa2b79a4c4548aa',
                                    )
                    # [CONTROL comment] 来源 transfer_bottle_collect_to_staging_b@body/2；原节点 {"op":"comment","text":"放瓶前先压住中转B整板 (板浮动会插孔失准; 同扫描周期 DONE","不拖 P70 交接)":null}
                    # unilab:node_uuid=5d6075f6-5050-51c7-96b6-4dd87013f989
                    with group(name='说明 · 放瓶前先压住中转B整板 (板浮动会插孔失准; 同扫描周期 DONE'):
                        # [VERIFY comment] 只读来源校验 transfer_bottle_collect_to_staging_b@body/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=bd36a2c1-2c72-5ebc-97a6-20b4f900af23 disabled=true
                        projected_control_0361 = material.review_control_node_v1(
                            operation_name='transfer_bottle_collect_to_staging_b',
                            node_path='body/2',
                            control_kind='comment',
                            expected_sha256='5f0a4c1c3736f1891c393ca5e77819b7d4fe4be9cf56b8cdc763d2ddaa2909b7',
                        )
                    # [ACTION staging_a.locator_b] 来源 transfer_bottle_collect_to_staging_b@body/3；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=642734a0-8610-511a-bffa-6056eae82767 disabled=true
                    projected_action_0362 = staging_a.locator_b(
                        target=True,
                    )
                    # [CONTROL comment] 来源 transfer_bottle_collect_to_staging_b@body/4；原节点 {"op":"comment","text":"地轨保持收集位(位3","全程不再移轨); 从 P70 直接交接放瓶回中转B":null}
                    # unilab:node_uuid=ae690f76-592b-5f65-93b8-a03ea9e58991
                    with group(name='说明 · 地轨保持收集位(位3'):
                        # [VERIFY comment] 只读来源校验 transfer_bottle_collect_to_staging_b@body/4；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=d78ff6f5-edb8-5a98-b3a9-22647a8f1ced disabled=true
                        projected_control_0363 = material.review_control_node_v1(
                            operation_name='transfer_bottle_collect_to_staging_b',
                            node_path='body/4',
                            control_kind='comment',
                            expected_sha256='d4dc1f500f03544058a9dfdd7347e2ab593b36d78d03c55aea267d6f7cde49a1',
                        )
                    # [SUBWORKFLOW robot_individual_put] 由 transfer_bottle_collect_to_staging_b@body/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=892c74af-3a8c-59a1-a8a5-b54865c63398
                    with group(name='↳ robot_individual_put'):
                        # [CONTROL comment] 来源 robot_individual_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 仅 P1 入口时确保回零+换刀; P70/P52 交接入口由分支锚断言把关 (上游取件流程已保证工具)"}
                        # unilab:node_uuid=6f9e0c34-8a52-5762-a88a-b8ab835d88a6
                        with group(name='说明 · 入口保证(手改): 仅 P1 入口时确保回零+换刀; P70/P52 交接入口由分支锚断言把关 (上游取件流程已'):
                            # [VERIFY comment] 只读来源校验 robot_individual_put@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=a650579a-543b-5ed0-97b2-cfd2fbd3562e disabled=true
                            projected_control_0364 = material.review_control_node_v1(
                                operation_name='robot_individual_put',
                                node_path='body/0',
                                control_kind='comment',
                                expected_sha256='da3d13aa283fa7ee70ee87b04f53a55c8dbc6fffedcabcf1143ea331c6239200',
                            )
                        # [CONTROL if] 来源 robot_individual_put@body/1；原节点 {"cond":{"binop":"==","left":{"var":"enter_anchor"},"right":{"lit":"P1"}},"op":"if","then":[{"action":"robot.home_ensure","mode":"RUN","op":"call"},{"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}]}
                        # unilab:node_uuid=5944deb4-d425-5cf8-991c-4f87fc4e7e17
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_individual_put@body/1；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=1c61d966-386a-5ea3-9617-ecaedf55c53c disabled=true
                            projected_control_0365 = material.review_control_node_v1(
                                operation_name='robot_individual_put',
                                node_path='body/1',
                                control_kind='if',
                                expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
                            )
                            # [BRANCH THEN（互斥分支）] robot_individual_put@body/1/then 的静态审阅分支。
                            # unilab:node_uuid=284ee781-23c4-53b5-9bf4-90529e538b7d
                            with group(name='THEN（互斥分支）'):
                                # [ACTION robot.home_ensure] 来源 robot_individual_put@body/1/then/0；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                                # unilab:node_uuid=414662d2-70ce-5d9a-886b-9e4bcedc160c disabled=true
                                projected_action_0366 = robot.home_ensure()
                                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_individual_put@body/1/then/1；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=f93b58f7-25ae-52ba-8ab1-5ba5401bd17c disabled=true
                                projected_control_0367 = material.review_control_node_v1(
                                    operation_name='robot_individual_put',
                                    node_path='body/1/then/1',
                                    control_kind='run_script',
                                    expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
                                )
                            # [BRANCH ELSE（互斥分支）] robot_individual_put@body/1/else 的静态审阅分支。
                            # unilab:node_uuid=13e5ea22-d13b-5ceb-96c6-4ff3290fe3ff
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_individual_put@body/1；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=b8304855-8a85-5406-a951-aaf54ad7a5cd disabled=true
                                projected_control_0368 = material.review_control_node_v1(
                                    operation_name='robot_individual_put',
                                    node_path='body/1',
                                    control_kind='if',
                                    expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
                                )
                        # [CONTROL if] 来源 robot_individual_put@body/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"right":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":...
                        # unilab:node_uuid=36ebccd7-1aa4-5c95-b7b9-687244900f9b
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_individual_put@body/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=9de55a9a-f229-5baa-9b6f-5dad263e37ec disabled=true
                            projected_control_0369 = material.review_control_node_v1(
                                operation_name='robot_individual_put',
                                node_path='body/2',
                                control_kind='if',
                                expected_sha256='5eb23b5166747f641204ad7085b5275b765e7c9e9e8a6babe06c0618627d2cda',
                            )
                            # [BRANCH THEN（互斥分支）] robot_individual_put@body/2/then 的静态审阅分支。
                            # unilab:node_uuid=08b90673-d867-51a8-be0c-12a4c19307c9
                            with group(name='THEN（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d365063b-c25a-5adf-8e7d-89ea4f7227d2 disabled=true
                                projected_action_0370 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_put@body/2/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=12fad21e-40d5-5cdb-8f08-d6fd16366540 disabled=true
                                projected_action_0371 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1927fe36-b515-5078-b41e-a931d513519a disabled=true
                                projected_action_0372 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=bbc1ab30-1537-515c-b36f-e6bc3613b5a4 disabled=true
                                projected_action_0373 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p46.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=651d45a6-10a0-5e11-94da-f4f92311e461 disabled=true
                                projected_action_0374 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p46.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/then/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=17fc0b75-feb8-5d5b-80b7-c4cb1392b01a disabled=true
                                projected_action_0375 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4238065e-af6a-5d32-9a69-33bd094e02f9 disabled=true
                                projected_action_0376 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p46.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f3132b7e-1e33-5189-aef6-98bcef54e1f3 disabled=true
                                projected_action_0377 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p46.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1200ad32-265d-5682-b19d-fe4953e30cb7 disabled=true
                                projected_action_0378 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ab6219a5-8d99-5ead-a6af-921c5fa28bc6 disabled=true
                                projected_action_0379 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=438510d8-e954-5956-9b16-ce30563f12f0 disabled=true
                                projected_action_0380 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 1（互斥分支）] robot_individual_put@body/2/elifs/0/body 的静态审阅分支。
                            # unilab:node_uuid=50b15943-b55a-5578-80f3-f3c7ae21ca5b
                            with group(name='ELIF 1（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9b2a35f7-d2e9-56cf-a7da-3643395b459f disabled=true
                                projected_action_0381 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a33bf7a8-ecb1-5f1d-9e6e-b8dd22d8496a disabled=true
                                projected_action_0382 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=83823f6a-37c5-5638-a83a-1d95d5e1eab8 disabled=true
                                projected_action_0383 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ed884ab2-e2cd-5805-86c1-8138e07de7e1 disabled=true
                                projected_action_0384 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p47.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=53c879d0-c9f3-5066-9843-b33ced59e67e disabled=true
                                projected_action_0385 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p47.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/0/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8f0f1229-1f61-5f3b-b784-cadefe83600f disabled=true
                                projected_action_0386 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=681302c7-18e9-54e8-bde0-68fd9206ee37 disabled=true
                                projected_action_0387 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p47.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=86571d81-45d8-50d2-969c-b8e3e38771aa disabled=true
                                projected_action_0388 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p47.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e61544fc-d1e8-53d8-b936-9a1b21012016 disabled=true
                                projected_action_0389 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f1b4702b-59c5-5efe-be1d-42931a928ba8 disabled=true
                                projected_action_0390 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f462d73e-8c4b-5804-9e57-c6d10c2bea3f disabled=true
                                projected_action_0391 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 2（互斥分支）] robot_individual_put@body/2/elifs/1/body 的静态审阅分支。
                            # unilab:node_uuid=5b8de3ab-3ea2-522c-85af-046f40803b03
                            with group(name='ELIF 2（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b68dce1a-1a39-597d-ace0-1c9ed49b5e28 disabled=true
                                projected_action_0392 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b1491d31-2452-5796-a4ae-6402e951809f disabled=true
                                projected_action_0393 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3e11c755-11cd-5635-a665-400559aeeffa disabled=true
                                projected_action_0394 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4382ef5e-948a-5595-ac53-8864ba08acb4 disabled=true
                                projected_action_0395 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p48.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4b286e6e-908c-592a-ab18-deff98dfc229 disabled=true
                                projected_action_0396 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p48.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/1/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=6b4170fd-278b-57b2-b717-108ea3f51471 disabled=true
                                projected_action_0397 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8adfa7f5-5d9e-5f5d-b33a-73ac49d02e5d disabled=true
                                projected_action_0398 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p48.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8b099652-adca-59de-b370-163f860100e6 disabled=true
                                projected_action_0399 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p48.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a07cff09-d0ad-5a28-8dd6-eefb927fa9c2 disabled=true
                                projected_action_0400 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f84c48e6-2857-5dde-b509-f801c31d9127 disabled=true
                                projected_action_0401 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d5aa6eff-6fa3-56d3-a9c0-af9180a3adb3 disabled=true
                                projected_action_0402 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 3（互斥分支）] robot_individual_put@body/2/elifs/2/body 的静态审阅分支。
                            # unilab:node_uuid=a656c29e-3d42-50db-93ef-9b71661268cd
                            with group(name='ELIF 3（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=7179acec-96e7-5f6e-8146-756e9891951e disabled=true
                                projected_action_0403 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a56f823f-de10-528f-91c6-02a30b40895e disabled=true
                                projected_action_0404 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=85bd77db-e2ae-59ab-981c-31d66f6cf56c disabled=true
                                projected_action_0405 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=dddfe2c2-5a4d-5b3a-a7dd-47dd1bbcff6e disabled=true
                                projected_action_0406 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p49.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=34c33060-f932-54dc-ae48-5675ae2183fb disabled=true
                                projected_action_0407 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p49.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/2/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b4a108eb-ec7e-5be1-8f9f-f6f4513f9691 disabled=true
                                projected_action_0408 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c759a9aa-da06-54a8-9fa7-301c8ce72e23 disabled=true
                                projected_action_0409 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p49.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=00f11bea-609a-5f6c-bc2f-0daded8527d3 disabled=true
                                projected_action_0410 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p49.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f4181be4-77d9-580d-a81c-cdd861b0dcaa disabled=true
                                projected_action_0411 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0e0e2fa8-ace4-59da-9cbd-2e62bdf42cfe disabled=true
                                projected_action_0412 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/2/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=42a8590e-6159-59d6-98ac-6901212ed2dc disabled=true
                                projected_action_0413 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 4（互斥分支）] robot_individual_put@body/2/elifs/3/body 的静态审阅分支。
                            # unilab:node_uuid=6f05adec-d97a-5a6f-9f21-783fc63f51ac
                            with group(name='ELIF 4（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=58d63739-f89a-5b3b-867e-d89ae206882b disabled=true
                                projected_action_0414 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a8a6092d-80fd-5787-9346-673d526a58fa disabled=true
                                projected_action_0415 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=84b8ec99-3261-5194-8f1d-5b012b805827 disabled=true
                                projected_action_0416 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d8718e6c-48cf-58dc-b996-36a22e5c24b9 disabled=true
                                projected_action_0417 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p50.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=678fc9f2-aa52-5cf7-88d0-caa7e752c73e disabled=true
                                projected_action_0418 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p50.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/3/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=886e9e05-6c6a-5b72-8942-bc71a6c73f69 disabled=true
                                projected_action_0419 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=026cff1b-38a1-54d2-90a7-419b67d59f90 disabled=true
                                projected_action_0420 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p50.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=02ea3ba0-e8e2-51b0-8ca4-ed932dadc9d3 disabled=true
                                projected_action_0421 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p50.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=40d3a507-9085-525f-9d09-e04d9fbe5ccd disabled=true
                                projected_action_0422 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d23851b0-8a95-53df-baac-c5398d323b89 disabled=true
                                projected_action_0423 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/3/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f2d537cd-3336-506d-a451-f8804555d840 disabled=true
                                projected_action_0424 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 5（互斥分支）] robot_individual_put@body/2/elifs/4/body 的静态审阅分支。
                            # unilab:node_uuid=700ddf55-64d4-5f1d-bba1-650b6e969553
                            with group(name='ELIF 5（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e78b5957-e32f-5545-a9ce-843bc6fcfecc disabled=true
                                projected_action_0425 = robot.require_anchor(
                                    point_id='P1',
                                )
                                # [ACTION rail.ensure] 来源 robot_individual_put@body/2/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=efc39e8d-c62d-5d10-9077-9ec458ec15fe disabled=true
                                projected_action_0426 = rail.ensure(
                                    Rail_Target_Position=2,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c10d73c2-5138-5e02-b868-ab6a8b9a49db disabled=true
                                projected_action_0427 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=653a467a-a3e5-5622-8f38-b9e1724a203b disabled=true
                                projected_action_0428 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p51.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=01e47bca-9da7-570d-a1d4-b99b5d62cabd disabled=true
                                projected_action_0429 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p51.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/4/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=66e1aa6d-295c-512f-97a8-fe8383586861 disabled=true
                                projected_action_0430 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b298bc4e-d10e-55aa-9e35-3357791874d8 disabled=true
                                projected_action_0431 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p51.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=684e515d-d017-5864-bc2c-73f57cc2767c disabled=true
                                projected_action_0432 = robot.move_to_point(
                                    point_id_or_robot_name='staging-a.p51.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=5b533a42-fa48-5cce-8c02-7090601b56cf disabled=true
                                projected_action_0433 = robot.move_to_point(
                                    point_id_or_robot_name='P45',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=bc9c7942-b927-512f-b628-bec6af5897da disabled=true
                                projected_action_0434 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/4/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=60eacd12-e9d4-515c-9899-d6b290c8126a disabled=true
                                projected_action_0435 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 6（互斥分支）] robot_individual_put@body/2/elifs/5/body 的静态审阅分支。
                            # unilab:node_uuid=0184c4d0-aa05-50aa-9a62-9ad08456108c
                            with group(name='ELIF 6（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=df5d9686-4552-5ec7-95c8-6ead46681b8a disabled=true
                                projected_action_0436 = robot.require_anchor(
                                    point_id='review-only',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=43c79546-727f-5860-a4d6-a83e13692cad disabled=true
                                projected_action_0437 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=20c5ec75-5046-51ef-a1a1-94f791b7a358 disabled=true
                                projected_action_0438 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p53.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a69fd078-ed4c-5974-b3ad-52071d319ea1 disabled=true
                                projected_action_0439 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p53.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/5/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=cb624964-c167-5510-bce2-777e2fe2ac2a disabled=true
                                projected_action_0440 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=983c90a9-baf2-5cb6-96c3-8bd29c6d6f83 disabled=true
                                projected_action_0441 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p53.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a03bbd32-e833-5d41-9bd7-d83368faff9d disabled=true
                                projected_action_0442 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p53.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=59bd058e-ba2d-5e7f-8b5e-96e09443fa7e disabled=true
                                projected_action_0443 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/5/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a07332b3-1008-5710-a262-0eeb8bd98aea disabled=true
                                projected_action_0444 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/5/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=53d95559-8b79-5e0b-8641-13d555aa5f9e disabled=true
                                projected_action_0445 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 7（互斥分支）] robot_individual_put@body/2/elifs/6/body 的静态审阅分支。
                            # unilab:node_uuid=2f5467d1-7c3c-55a4-9d3d-b5d9a80c43b8
                            with group(name='ELIF 7（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9678f43e-854c-52bb-b200-78e877e44ec3 disabled=true
                                projected_action_0446 = robot.require_anchor(
                                    point_id='review-only',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8e5cb785-e266-5a28-8f5e-f41324da022f disabled=true
                                projected_action_0447 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=91761bbd-fea1-5330-9396-0611891ebd3b disabled=true
                                projected_action_0448 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p54.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9fea7b44-5cc1-568f-b78f-f6e2732a4ab4 disabled=true
                                projected_action_0449 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p54.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/6/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4e6f8da1-e912-5be2-9240-37966526f9d9 disabled=true
                                projected_action_0450 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=aa89b070-048d-5a7f-bb0b-653aade0b35c disabled=true
                                projected_action_0451 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p54.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f2eca7b5-09ab-55b8-98f2-2a6c2f288f8b disabled=true
                                projected_action_0452 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p54.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c8280a23-7e27-56cf-b2bb-2c2eb409f97f disabled=true
                                projected_action_0453 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/6/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=86863768-9373-5bb0-a1d6-8a8d88c8c285 disabled=true
                                projected_action_0454 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/6/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=76e6cca3-d2a8-5230-8629-c28f0740979a disabled=true
                                projected_action_0455 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 8（互斥分支）] robot_individual_put@body/2/elifs/7/body 的静态审阅分支。
                            # unilab:node_uuid=485a6841-98d7-5f0d-a34b-11f8208ee41f
                            with group(name='ELIF 8（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/7/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4d95d12d-eac6-5e31-a6e1-a641e0a3cb61 disabled=true
                                projected_action_0456 = robot.require_anchor(
                                    point_id='review-only',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9b5935d0-edeb-57e0-87e8-a32c55bf6905 disabled=true
                                projected_action_0457 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=42f903f3-68fb-5ca9-8802-3e73ee617421 disabled=true
                                projected_action_0458 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p55.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=16ebd17d-5946-5ad5-ab2f-599958f8eece disabled=true
                                projected_action_0459 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p55.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/7/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4d712912-1a09-5352-aeb2-f08268223359 disabled=true
                                projected_action_0460 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=303d3e38-8822-540c-9ed8-be02359bc8a4 disabled=true
                                projected_action_0461 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p55.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ba8d1d63-8cbb-5890-8dbf-ecb86ea2dea2 disabled=true
                                projected_action_0462 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p55.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1e08fac7-e0cd-5f10-b365-3d7af7fd1ac4 disabled=true
                                projected_action_0463 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/7/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=536814da-542c-53c0-9fba-d805211ac8f6 disabled=true
                                projected_action_0464 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/7/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=6b4cd292-f406-5f69-b256-33f81baf219a disabled=true
                                projected_action_0465 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 9（互斥分支）] robot_individual_put@body/2/elifs/8/body 的静态审阅分支。
                            # unilab:node_uuid=15d26add-4cf2-5f38-88f6-166a2366a940
                            with group(name='ELIF 9（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/8/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0166833d-60a1-5e0f-b573-e25ab592d3c1 disabled=true
                                projected_action_0466 = robot.require_anchor(
                                    point_id='review-only',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=351ff6e1-57c1-5479-9ff3-a4b122f2460f disabled=true
                                projected_action_0467 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=10a52918-8896-5cb6-b786-f9fd14d27c07 disabled=true
                                projected_action_0468 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p56.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ce90cd07-0d05-5486-9eb8-b9e1074e3172 disabled=true
                                projected_action_0469 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p56.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/8/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a63fcd76-ad6c-5105-bc75-bdd46f07bbdc disabled=true
                                projected_action_0470 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8e464ba0-1c91-5f52-aff7-d9f4146ef915 disabled=true
                                projected_action_0471 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p56.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=58800c30-dbf2-5000-8128-ee888693eafd disabled=true
                                projected_action_0472 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p56.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=efba4a13-32a5-508e-ae5d-f69b590e01fd disabled=true
                                projected_action_0473 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/8/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0eb076ba-c179-5bd9-8734-619bdac86958 disabled=true
                                projected_action_0474 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/8/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c1bef7ad-1abd-513a-aa37-da49a4078ee8 disabled=true
                                projected_action_0475 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 10（互斥分支）] robot_individual_put@body/2/elifs/9/body 的静态审阅分支。
                            # unilab:node_uuid=845a33da-c499-5d5a-bce2-91b34788f525
                            with group(name='ELIF 10（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/9/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=5dde1520-2419-577a-a978-311b3d2b0c61 disabled=true
                                projected_action_0476 = robot.require_anchor(
                                    point_id='review-only',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=258682ea-c912-52f6-83a9-3c8c8b929590 disabled=true
                                projected_action_0477 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=455b497d-fa6d-5522-9ff1-6ca7b4ff6b47 disabled=true
                                projected_action_0478 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p57.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=58d07e75-fa72-5ebd-8022-b909b9006b60 disabled=true
                                projected_action_0479 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p57.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/9/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=5f5c66ad-4209-535c-ab3e-7281ebcc97d0 disabled=true
                                projected_action_0480 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d3a2d31f-9e39-5afa-9abc-e63e5c758a83 disabled=true
                                projected_action_0481 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p57.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=837648b3-141e-514b-9921-4c2cb2c73bc4 disabled=true
                                projected_action_0482 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p57.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=fcc6d73d-0fed-5444-a9ae-1a4403b3e243 disabled=true
                                projected_action_0483 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/9/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0404a802-3aeb-582b-8dce-5eb84914be6a disabled=true
                                projected_action_0484 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/9/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3f751174-0e16-5cbf-902a-b7365f69411b disabled=true
                                projected_action_0485 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELIF 11（互斥分支）] robot_individual_put@body/2/elifs/10/body 的静态审阅分支。
                            # unilab:node_uuid=6dbb26a2-95d9-5114-a153-2fa2d0415d10
                            with group(name='ELIF 11（互斥分支）'):
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/10/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f86b4df2-a632-544c-a43e-ee3a2378680d disabled=true
                                projected_action_0486 = robot.require_anchor(
                                    point_id='review-only',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3d86e924-cb41-55bf-9989-9236256f6464 disabled=true
                                projected_action_0487 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d2f6158e-284e-511e-a844-e8cac4bf48f3 disabled=true
                                projected_action_0488 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p58.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=6e006dbe-f9dc-5144-a96f-fd70aa09b8f7 disabled=true
                                projected_action_0489 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p58.near',
                                )
                                # [ACTION robot.tool_action] 来源 robot_individual_put@body/2/elifs/10/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=64689d06-7aa6-57c5-8f2f-2273dde37f51 disabled=true
                                projected_action_0490 = robot.tool_action(
                                    action='gripper-open',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=0a864739-7bc8-549e-9cd2-2e8fdd7e5285 disabled=true
                                projected_action_0491 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p58.near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a79aa1b3-c720-5ab4-8d0e-fdaf721d0fff disabled=true
                                projected_action_0492 = robot.move_to_point(
                                    point_id_or_robot_name='staging-b.p58.high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=41e15985-d21b-5644-a627-fb9c06c2b99a disabled=true
                                projected_action_0493 = robot.move_to_point(
                                    point_id_or_robot_name='P52',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_individual_put@body/2/elifs/10/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4c166c8f-73f6-5061-b04c-6cb092a33a71 disabled=true
                                projected_action_0494 = robot.move_to_point(
                                    point_id_or_robot_name='P1',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_individual_put@body/2/elifs/10/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=1c34b0b3-a86c-5239-ad63-1323ff3e49d2 disabled=true
                                projected_action_0495 = robot.require_anchor(
                                    point_id='P1',
                                )
                            # [BRANCH ELSE（互斥分支）] robot_individual_put@body/2/else 的静态审阅分支。
                            # unilab:node_uuid=7a5704a9-b84b-5a4e-80fc-de8a433377cc
                            with group(name='ELSE（互斥分支）'):
                                # [CONTROL raise] 来源 robot_individual_put@body/2/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"individual.put: 无效选择值"},"op":"raise"}
                                # unilab:node_uuid=04e52e90-db89-572f-91d9-c5029b10fedc
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_individual_put@body/2/else/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=d9cec1ac-9b55-5961-b211-27b4ccaa83a6 disabled=true
                                    projected_control_0496 = material.review_control_node_v1(
                                        operation_name='robot_individual_put',
                                        node_path='body/2/else/0',
                                        control_kind='raise',
                                        expected_sha256='82bf1a17283cb1d76e559d071719bf7252fd0fe0d6f7c00622f156e5cf58486c',
                                    )
                # [CONTROL comment] 来源 collect_unload@body/2；原节点 {"op":"comment","text":"下料/取接粉收集器: 瓶已移出后缩回, 再进入夹具、松夹、退出"}
                # unilab:node_uuid=419575e8-81cf-54e6-b26e-18199485b378
                with group(name='说明 · 下料/取接粉收集器: 瓶已移出后缩回, 再进入夹具、松夹、退出'):
                    # [VERIFY comment] 只读来源校验 collect_unload@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=f0805935-b430-5c11-9f9d-2752d577bd07 disabled=true
                    projected_control_0497 = material.review_control_node_v1(
                        operation_name='collect_unload',
                        node_path='body/2',
                        control_kind='comment',
                        expected_sha256='e6b7b29fa6b24cf7f5cf9e680bd17294995f37909d17dbf8701a8a9968f694ad',
                    )
                # [ACTION collect.retract] 来源 collect_unload@body/3；原节点 {"action":"collect.retract","mode":"RUN","op":"call"}
                # unilab:node_uuid=26a65bde-e23a-5f5c-9334-9eb928f24c6c disabled=true
                projected_action_0498 = collect.retract()
                # [SUBWORKFLOW robot_collect_holder_pick_enter] 由 collect_unload@body/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=5fdf25b6-c4b7-5781-a24c-5f40d5c9b509
                with group(name='↳ robot_collect_holder_pick_enter'):
                    # [CONTROL comment] 来源 robot_collect_holder_pick_enter@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)"}
                    # unilab:node_uuid=25349944-f188-5415-98bf-4e811fd40cea
                    with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)'):
                        # [VERIFY comment] 只读来源校验 robot_collect_holder_pick_enter@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=85465579-ab05-5d4e-b116-c23733912cbc disabled=true
                        projected_control_0499 = material.review_control_node_v1(
                            operation_name='robot_collect_holder_pick_enter',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
                        )
                    # [ACTION robot.home_ensure] 来源 robot_collect_holder_pick_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                    # unilab:node_uuid=cf51a74f-f20f-5672-8a26-23b51c809d74 disabled=true
                    projected_action_0500 = robot.home_ensure()
                    # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_collect_holder_pick_enter@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=29a23458-2125-5b02-9fbc-f99ef272958b disabled=true
                    projected_control_0501 = material.review_control_node_v1(
                        operation_name='robot_collect_holder_pick_enter',
                        node_path='body/2',
                        control_kind='run_script',
                        expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
                    )
                    # [CONTROL if] 来源 robot_collect_holder_pick_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.pick-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_...
                    # unilab:node_uuid=4f64d918-f567-5177-8f60-e20fc110ec29
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_collect_holder_pick_enter@body/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=f3340eed-3ce5-58e8-b332-7ad587388b10 disabled=true
                        projected_control_0502 = material.review_control_node_v1(
                            operation_name='robot_collect_holder_pick_enter',
                            node_path='body/3',
                            control_kind='if',
                            expected_sha256='684bbc4080ef6888fa0e463f987da6edd06ee78b60f94938e062f931d40b25db',
                        )
                        # [BRANCH THEN（互斥分支）] robot_collect_holder_pick_enter@body/3/then 的静态审阅分支。
                        # unilab:node_uuid=56d48f54-21ff-5eeb-ab7d-37e769532aa9
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collect_holder_pick_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=fced62ba-8270-5b1a-ab9e-3e7349f0ae74 disabled=true
                            projected_action_0503 = robot.require_anchor(
                                point_id='P1',
                            )
                            # [ACTION rail.ensure] 来源 robot_collect_holder_pick_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=43961dcc-a35c-552c-a574-c651cedd9ef1 disabled=true
                            projected_action_0504 = rail.ensure(
                                Rail_Target_Position=3,
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_enter@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=aba77e1a-c150-5bff-8510-3b6a24f88fe6 disabled=true
                            projected_action_0505 = robot.move_to_point(
                                point_id_or_robot_name='P70',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-pick.far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=7f3e5594-227e-5586-aaa0-2b0f18d3d069 disabled=true
                            projected_action_0506 = robot.move_to_point(
                                point_id_or_robot_name='collect-holder-pick.far',
                            )
                            # [ACTION robot.tool_action] 来源 robot_collect_holder_pick_enter@body/3/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=7edf7422-d72e-5769-a78f-a3899bfd88c7 disabled=true
                            projected_action_0507 = robot.tool_action(
                                action='gripper-open',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=9a486329-7c5f-5e2a-ae70-4de1b804fa44 disabled=true
                            projected_action_0508 = robot.move_to_point(
                                point_id_or_robot_name='collect-holder-pick.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_enter@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P74"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=d8505e2b-703b-5235-ad93-c52f27324b43 disabled=true
                            projected_action_0509 = robot.move_to_point(
                                point_id_or_robot_name='P74',
                            )
                            # [ACTION robot.tool_action] 来源 robot_collect_holder_pick_enter@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=83837354-7d91-55e1-a8e6-3c07ea654117 disabled=true
                            projected_action_0510 = robot.tool_action(
                                action='gripper-close',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collect_holder_pick_enter@body/3/then/8；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P74"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=27434459-c4f3-5035-8163-160c05e3e42d disabled=true
                            projected_action_0511 = robot.require_anchor(
                                point_id='P74',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_collect_holder_pick_enter@body/3/else 的静态审阅分支。
                        # unilab:node_uuid=942be94a-dfe6-5ac7-a1f6-6a6c0b8ca482
                        with group(name='ELSE（互斥分支）'):
                            # [CONTROL raise] 来源 robot_collect_holder_pick_enter@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.pick-enter: 无效选择值"},"op":"raise"}
                            # unilab:node_uuid=31f126b3-05eb-5052-89ef-b1bcbab4eac5
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_collect_holder_pick_enter@body/3/else/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=b644ff81-beda-546c-aa8c-f421afff7153 disabled=true
                                projected_control_0512 = material.review_control_node_v1(
                                    operation_name='robot_collect_holder_pick_enter',
                                    node_path='body/3/else/0',
                                    control_kind='raise',
                                    expected_sha256='8971f910dc9f0dda4a813c1065a771ce86e4f84133b15a4a61ccf4bbb19b64c9',
                                )
                # [ACTION collect.release_clamp] 来源 collect_unload@body/5；原节点 {"action":"collect.release_clamp","mode":"RUN","op":"call"}
                # unilab:node_uuid=14e3e8e9-4b16-5456-84e2-099276126fc2 disabled=true
                projected_action_0513 = collect.release_clamp()
                # [SUBWORKFLOW robot_collect_holder_pick_exit] 由 collect_unload@body/6 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=7f7f42c0-685e-578b-a302-e4bc8974b32b
                with group(name='↳ robot_collect_holder_pick_exit'):
                    # [CONTROL if] 来源 robot_collect_holder_pick_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.pick-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P74"},"pos_t...
                    # unilab:node_uuid=7acbdd1f-887e-56a1-9041-cace31f81e43
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_collect_holder_pick_exit@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=f0f74fce-97bf-5f50-b774-1ef4047cb1b4 disabled=true
                        projected_control_0514 = material.review_control_node_v1(
                            operation_name='robot_collect_holder_pick_exit',
                            node_path='body/0',
                            control_kind='if',
                            expected_sha256='9dd19a9682f6bba7bd2e92567e4bb0d4189fe1cd4152a88dbe99e68aa46578a8',
                        )
                        # [BRANCH THEN（互斥分支）] robot_collect_holder_pick_exit@body/0/then 的静态审阅分支。
                        # unilab:node_uuid=98595039-c96d-50e9-adcb-ec521e28cb1d
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collect_holder_pick_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P74"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=6b5fc293-2b68-5f15-af7f-009b1593097f disabled=true
                            projected_action_0515 = robot.require_anchor(
                                point_id='P74',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_exit@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=d3a5a528-92cb-5387-9f7f-a4ef1dabb069 disabled=true
                            projected_action_0516 = robot.move_to_point(
                                point_id_or_robot_name='collect-holder-pick.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_exit@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collect-holder-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=a3b39b68-2442-52e1-a3f2-dacc5829a82c disabled=true
                            projected_action_0517 = robot.move_to_point(
                                point_id_or_robot_name='collect-holder-pick.far',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collect_holder_pick_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P70"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=c5848316-23a0-5c92-b2fe-df74a93a9999 disabled=true
                            projected_action_0518 = robot.move_to_point(
                                point_id_or_robot_name='P70',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collect_holder_pick_exit@body/0/then/4；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P70"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=d0a4468e-551b-5378-be9d-84f9cf53dd51 disabled=true
                            projected_action_0519 = robot.require_anchor(
                                point_id='P70',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_collect_holder_pick_exit@body/0/else 的静态审阅分支。
                        # unilab:node_uuid=839b2318-d393-5ccd-b751-d64ba4ad2227
                        with group(name='ELSE（互斥分支）'):
                            # [CONTROL raise] 来源 robot_collect_holder_pick_exit@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collect.holder.pick-exit: 无效选择值"},"op":"raise"}
                            # unilab:node_uuid=d9ea954d-a78f-501c-aa43-31e4f60de622
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_collect_holder_pick_exit@body/0/else/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=20d0de8f-f1a7-50d0-b5af-5cd8f0e91a18 disabled=true
                                projected_control_0520 = material.review_control_node_v1(
                                    operation_name='robot_collect_holder_pick_exit',
                                    node_path='body/0/else/0',
                                    control_kind='raise',
                                    expected_sha256='b11f10a0feb8744b7c58d4e70abd796e993e4ac814885c2570751251942e60cf',
                                )
                # [CONTROL comment] 来源 collect_unload@body/7；原节点 {"op":"comment","text":"收集器 return 用点 P78-83, 与 pick 点 P46-51 是同一排货位的两种(轨,点)配对: P78-83@位3 ≡ P46-51@位2 (坐标验证同世界坐标±2mm, 地轨与臂X反向耦合)。holder 在收集站位3 取毕, return 也落位3 → 全程不移轨, 从收集枢纽 P70 直接交接回中转A 免回 P1。⚠️此处位3只对 return 点 P78-83 成立, 勿据此把 pick(P46-51)也翻位3"}
                # unilab:node_uuid=68c25002-3079-5684-a59e-3f23194a6947
                with group(name='说明 · 收集器 return 用点 P78-83, 与 pick 点 P46-51 是同一排货位的两种(轨,点)配对: '):
                    # [VERIFY comment] 只读来源校验 collect_unload@body/7；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=410a5117-bbfe-5804-a547-7ef6e48af973 disabled=true
                    projected_control_0521 = material.review_control_node_v1(
                        operation_name='collect_unload',
                        node_path='body/7',
                        control_kind='comment',
                        expected_sha256='cc0466de9d8f030a14f5be93c3990c2603fc2967fa733958a5de8ea9dafa213e',
                    )
                # [SUBWORKFLOW robot_collector_return_put] 由 collect_unload@body/8 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=c9afd48b-d9e8-5fb1-b89d-e34371af1445
                with group(name='↳ robot_collector_return_put'):
                    # [CONTROL comment] 来源 robot_collector_return_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 仅 P1 入口时确保回零+换刀; P70 交接入口由分支锚断言把关 (上游取件流程已保证工具)"}
                    # unilab:node_uuid=68fbc1f9-9a07-536b-8278-cab283c3e1c6
                    with group(name='说明 · 入口保证(手改): 仅 P1 入口时确保回零+换刀; P70 交接入口由分支锚断言把关 (上游取件流程已保证工具'):
                        # [VERIFY comment] 只读来源校验 robot_collector_return_put@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=6902f3d5-c75c-518f-a8b3-ca6a86a0ec2d disabled=true
                        projected_control_0522 = material.review_control_node_v1(
                            operation_name='robot_collector_return_put',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='52d95a49b3516c8b471e4044dc213c8c24c95fa83fe64e49518e197b4b655b0c',
                        )
                    # [CONTROL if] 来源 robot_collector_return_put@body/1；原节点 {"cond":{"binop":"==","left":{"var":"enter_anchor"},"right":{"lit":"P1"}},"op":"if","then":[{"action":"robot.home_ensure","mode":"RUN","op":"call"},{"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}]}
                    # unilab:node_uuid=923c7aa9-de2f-585f-b763-80e7dc37d399
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_collector_return_put@body/1；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=e6acb07c-7e97-5ab8-9eb0-49d7f3f03471 disabled=true
                        projected_control_0523 = material.review_control_node_v1(
                            operation_name='robot_collector_return_put',
                            node_path='body/1',
                            control_kind='if',
                            expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
                        )
                        # [BRANCH THEN（互斥分支）] robot_collector_return_put@body/1/then 的静态审阅分支。
                        # unilab:node_uuid=c8580dca-f56e-5bbf-8dd3-d9a146cab1ff
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.home_ensure] 来源 robot_collector_return_put@body/1/then/0；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                            # unilab:node_uuid=467c9bff-ae85-5210-8f13-26f5b7b2943d disabled=true
                            projected_action_0524 = robot.home_ensure()
                            # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_collector_return_put@body/1/then/1；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=4a81e50e-b800-57ba-b559-1680fd878a29 disabled=true
                            projected_control_0525 = material.review_control_node_v1(
                                operation_name='robot_collector_return_put',
                                node_path='body/1/then/1',
                                control_kind='run_script',
                                expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_collector_return_put@body/1/else 的静态审阅分支。
                        # unilab:node_uuid=f439875d-61bc-5b5d-aa4a-d5562762ba95
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_collector_return_put@body/1；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=7e3590df-3c12-5b78-a548-8c42a9b898de disabled=true
                            projected_control_0526 = material.review_control_node_v1(
                                operation_name='robot_collector_return_put',
                                node_path='body/1',
                                control_kind='if',
                                expected_sha256='b3e5606c9d8117879d206e84e68f8103e13943a233f35fd82991fc3515866aba',
                            )
                    # [CONTROL if] 来源 robot_collector_return_put@body/2；原节点 {"cond":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"robot.move_to_point","args":{"acc":{"lit...
                    # unilab:node_uuid=48999d2e-5830-5f5e-9673-0fd3ae131c0f
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_collector_return_put@body/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=88cba14a-8aad-5c16-88a4-c2c6ae881f45 disabled=true
                        projected_control_0527 = material.review_control_node_v1(
                            operation_name='robot_collector_return_put',
                            node_path='body/2',
                            control_kind='if',
                            expected_sha256='8335be8a566a88a799ba0463516d9f1743d65290456880ccf38e4954da7d0852',
                        )
                        # [BRANCH THEN（互斥分支）] robot_collector_return_put@body/2/then 的静态审阅分支。
                        # unilab:node_uuid=5385a4ee-86f9-59da-a238-8a350a8ab531
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=6f7c94e5-aa0c-5764-98d0-fc4de4231e97 disabled=true
                            projected_action_0528 = robot.require_anchor(
                                point_id='review-only',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=395c4fe6-d138-51aa-98fc-590348b197c1 disabled=true
                            projected_action_0529 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p78.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=f8f8b110-dcaa-58da-a932-59e14646fe18 disabled=true
                            projected_action_0530 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p78.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p78.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=1937369f-3c72-5f2a-98cb-12d2057be257 disabled=true
                            projected_action_0531 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p78.near',
                            )
                            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=f5697ae7-1c12-5dba-9ffd-37f24297c5dc disabled=true
                            projected_action_0532 = robot.tool_action(
                                action='gripper-open',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p78.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=012ad2d3-5a85-5b31-b6f2-52b8fe52111e disabled=true
                            projected_action_0533 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p78.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p78.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=117be062-a85d-5eda-a27d-1c4d0cc0d66c disabled=true
                            projected_action_0534 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p78.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=e1fecb1f-4d16-52aa-92cb-67442e099871 disabled=true
                            projected_action_0535 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=ccb76c7e-baff-5d75-93ae-46c0c05d4474 disabled=true
                            projected_action_0536 = robot.move_to_point(
                                point_id_or_robot_name='P1',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/then/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=caacfc28-91a2-55ce-a9f7-40b999573037 disabled=true
                            projected_action_0537 = robot.require_anchor(
                                point_id='P1',
                            )
                        # [BRANCH ELIF 1（互斥分支）] robot_collector_return_put@body/2/elifs/0/body 的静态审阅分支。
                        # unilab:node_uuid=82a9a625-381a-5d88-a4c7-5812787bc1a7
                        with group(name='ELIF 1（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=42b88566-943c-5c8c-b658-714e7b53516c disabled=true
                            projected_action_0538 = robot.require_anchor(
                                point_id='review-only',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=29a3f5c4-0122-5f21-9b5f-edd957d60c54 disabled=true
                            projected_action_0539 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p79.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=d1f426a6-134e-51c5-8e04-12f8d986c0d2 disabled=true
                            projected_action_0540 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p79.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p79.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=35959377-efc8-562e-bad0-0e81132b2217 disabled=true
                            projected_action_0541 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p79.near',
                            )
                            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/0/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=2522547a-e36b-5a20-b5c8-439f328b2573 disabled=true
                            projected_action_0542 = robot.tool_action(
                                action='gripper-open',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p79.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=162f3a3c-2bc8-5817-b845-f4e417efe765 disabled=true
                            projected_action_0543 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p79.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p79.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=2ae15d0e-c182-50af-8ec1-b55a0d92da6b disabled=true
                            projected_action_0544 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p79.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=644a867b-6c61-551a-9b34-7b3433c1b168 disabled=true
                            projected_action_0545 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=6cc8e02d-2347-558d-bde6-13abce0562dc disabled=true
                            projected_action_0546 = robot.move_to_point(
                                point_id_or_robot_name='P1',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/0/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=63ce38b3-50e2-58e1-98b4-e8fb23f7f4f1 disabled=true
                            projected_action_0547 = robot.require_anchor(
                                point_id='P1',
                            )
                        # [BRANCH ELIF 2（互斥分支）] robot_collector_return_put@body/2/elifs/1/body 的静态审阅分支。
                        # unilab:node_uuid=35903690-7e5a-5c04-bdae-900519cfe8f9
                        with group(name='ELIF 2（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=c3d32804-c5f8-576d-bc44-864b0850f448 disabled=true
                            projected_action_0548 = robot.require_anchor(
                                point_id='review-only',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=cec2c24a-adf2-5b5d-a637-be7aafc550a8 disabled=true
                            projected_action_0549 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p80.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=5a3d0b91-fe24-5a19-a3d7-f0c9701f53bc disabled=true
                            projected_action_0550 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p80.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p80.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=90345658-fbec-56ea-98d8-767aaf00e2ef disabled=true
                            projected_action_0551 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p80.near',
                            )
                            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/1/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=bf062acf-76b4-5ed2-8d97-4dcd09e98f88 disabled=true
                            projected_action_0552 = robot.tool_action(
                                action='gripper-open',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p80.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=af4525d6-2b86-5a22-94d4-796ae42a8f47 disabled=true
                            projected_action_0553 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p80.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p80.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=571b5c5e-a87b-50de-a5bc-8d6387260c60 disabled=true
                            projected_action_0554 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p80.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=7f68e864-ccb3-5cac-9a30-ad013f765ff9 disabled=true
                            projected_action_0555 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=1a93bf09-5db0-5424-9b83-95b1e4f7cfd9 disabled=true
                            projected_action_0556 = robot.move_to_point(
                                point_id_or_robot_name='P1',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/1/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=ca434293-5c9f-5fae-9559-d34eb16e33e2 disabled=true
                            projected_action_0557 = robot.require_anchor(
                                point_id='P1',
                            )
                        # [BRANCH ELIF 3（互斥分支）] robot_collector_return_put@body/2/elifs/2/body 的静态审阅分支。
                        # unilab:node_uuid=698faa64-1122-5856-9f8d-4bf1c8cbd0e7
                        with group(name='ELIF 3（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=7b6e5768-4409-52ea-83c3-e024176a4b58 disabled=true
                            projected_action_0558 = robot.require_anchor(
                                point_id='review-only',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=e5484622-248a-59cf-98cd-89d2118b58bc disabled=true
                            projected_action_0559 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p81.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=da8ed330-3b30-5103-a6b7-9b202416b9c1 disabled=true
                            projected_action_0560 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p81.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p81.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=af5a6b3b-f077-5b32-963c-13dff0452036 disabled=true
                            projected_action_0561 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p81.near',
                            )
                            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/2/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=052d16b6-8e70-5f6a-aa4e-209fd964100b disabled=true
                            projected_action_0562 = robot.tool_action(
                                action='gripper-open',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p81.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=735ae9c5-2bb7-52c6-9620-8803cec06e64 disabled=true
                            projected_action_0563 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p81.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p81.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=3b0a5d38-786d-56f3-9d72-00e24fbfa9bb disabled=true
                            projected_action_0564 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p81.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=2c503d0a-5e23-550b-965e-ebea07860dda disabled=true
                            projected_action_0565 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=16345fbe-ea35-5bcf-ae86-8356f4da4cce disabled=true
                            projected_action_0566 = robot.move_to_point(
                                point_id_or_robot_name='P1',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/2/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=52c473c1-7429-5943-ab2f-3f178c224127 disabled=true
                            projected_action_0567 = robot.require_anchor(
                                point_id='P1',
                            )
                        # [BRANCH ELIF 4（互斥分支）] robot_collector_return_put@body/2/elifs/3/body 的静态审阅分支。
                        # unilab:node_uuid=d20f62e5-7913-51d4-a6be-28d29362a7bf
                        with group(name='ELIF 4（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=576cb5c7-b0da-5a2e-88d6-691d98fd9c6f disabled=true
                            projected_action_0568 = robot.require_anchor(
                                point_id='review-only',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=802cac54-eb1b-543b-9405-137440e5e45c disabled=true
                            projected_action_0569 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p82.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=63b0bb1e-2d11-5a36-8cc9-9cbb67ab5f99 disabled=true
                            projected_action_0570 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p82.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p82.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=a48f4a4e-c021-52d8-bbbd-b239f9991ff7 disabled=true
                            projected_action_0571 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p82.near',
                            )
                            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/3/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=26db2bcc-df28-5951-800e-485f5e4da833 disabled=true
                            projected_action_0572 = robot.tool_action(
                                action='gripper-open',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p82.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=68339184-dffa-513d-bfcb-cf9d387f214b disabled=true
                            projected_action_0573 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p82.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p82.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=235a988d-bd4d-5d0e-a3e7-8acb12340afd disabled=true
                            projected_action_0574 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p82.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=fb588699-153f-5982-be57-4a544107fd6d disabled=true
                            projected_action_0575 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/3/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=641b49a1-6023-5a14-bf9f-8e3a44ed7b79 disabled=true
                            projected_action_0576 = robot.move_to_point(
                                point_id_or_robot_name='P1',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/3/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=149f0513-ad93-5caf-b435-d03c4dcd4967 disabled=true
                            projected_action_0577 = robot.require_anchor(
                                point_id='P1',
                            )
                        # [BRANCH ELIF 5（互斥分支）] robot_collector_return_put@body/2/elifs/4/body 的静态审阅分支。
                        # unilab:node_uuid=4cd9d7af-56b2-5594-8c2e-a8604f6684ff
                        with group(name='ELIF 5（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"enter_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=328ff401-7871-5616-bdcb-20c9a58a4fda disabled=true
                            projected_action_0578 = robot.require_anchor(
                                point_id='review-only',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=77cb41db-27d1-57aa-a7c3-2b4e27beb0d6 disabled=true
                            projected_action_0579 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p83.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=80130050-2449-5dc8-b95a-39e6be2cdf40 disabled=true
                            projected_action_0580 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p83.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p83.near"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=8c386ed2-2f2e-5743-b74f-4b5a4195a98f disabled=true
                            projected_action_0581 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p83.near',
                            )
                            # [ACTION robot.tool_action] 来源 robot_collector_return_put@body/2/elifs/4/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=5e0cbb3d-46cd-5a51-b7e8-b7799725ee1c disabled=true
                            projected_action_0582 = robot.tool_action(
                                action='gripper-open',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p83.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=169be027-9025-564f-9cb6-318f74c908d5 disabled=true
                            projected_action_0583 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p83.near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a-return.p83.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=bda02bb3-f9c6-5419-a2a8-c7779a8b35e5 disabled=true
                            projected_action_0584 = robot.move_to_point(
                                point_id_or_robot_name='staging-a-return.p83.high',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=b48d71b9-2be7-520a-93ec-4b1a65ed7a2f disabled=true
                            projected_action_0585 = robot.move_to_point(
                                point_id_or_robot_name='P45',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_collector_return_put@body/2/elifs/4/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=6780093b-06f2-515e-a37f-763f42163f05 disabled=true
                            projected_action_0586 = robot.move_to_point(
                                point_id_or_robot_name='P1',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_collector_return_put@body/2/elifs/4/body/9；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=9db1ef00-dead-54a3-ac2e-01586430f695 disabled=true
                            projected_action_0587 = robot.require_anchor(
                                point_id='P1',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_collector_return_put@body/2/else 的静态审阅分支。
                        # unilab:node_uuid=545a8a9b-c380-5f05-b70f-2a6cb1572211
                        with group(name='ELSE（互斥分支）'):
                            # [CONTROL raise] 来源 robot_collector_return_put@body/2/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"collector.return.put: 无效选择值"},"op":"raise"}
                            # unilab:node_uuid=f52148e4-e864-5991-bad0-df746540379d
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_collector_return_put@body/2/else/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=09a6693b-beeb-51e5-80f6-fd03a7eeaeca disabled=true
                                projected_control_0588 = material.review_control_node_v1(
                                    operation_name='robot_collector_return_put',
                                    node_path='body/2/else/0',
                                    control_kind='raise',
                                    expected_sha256='a57328573180f43a956abcbb37f8fa364faa86665f2a8db135cfd6638cabdd09',
                                )
        # [CONTROL comment] 来源 pf_s10_collect@body/1；原节点 {"op":"comment","text":"收尾成对松开中转定位 (幂等; 顺序与 V2 一致: 先 b 后 a)"}
        # unilab:node_uuid=2fc50801-85df-50f7-aad9-0c654b9d04bc
        with group(name='说明 · 收尾成对松开中转定位 (幂等; 顺序与 V2 一致: 先 b 后 a)'):
            # [VERIFY comment] 只读来源校验 pf_s10_collect@body/1；节点在本工作流中静态 disabled。
            # unilab:node_uuid=aa61e5f2-5478-5c5c-bde9-1b0af23db976 disabled=true
            projected_control_0589 = material.review_control_node_v1(
                operation_name='pf_s10_collect',
                node_path='body/1',
                control_kind='comment',
                expected_sha256='5955a3adc3265a47b8736720cc92d1501ee7b4ccdf0f4d2eeaa6aa582f27a506',
            )
        # [ACTION staging_a.locator_b] 来源 pf_s10_collect@body/2；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
        # unilab:node_uuid=90384d21-f0ff-5e6d-9e0e-467c704e27c9 disabled=true
        projected_action_0590 = staging_a.locator_b(
            target=False,
        )
        # [ACTION staging_a.locator_a] 来源 pf_s10_collect@body/3；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
        # unilab:node_uuid=a24041a5-021a-5f04-9edc-9e2c4ad9719a disabled=true
        projected_action_0591 = staging_a.locator_a(
            target=False,
        )
    # [EXECUTE ROOT pf_s10_collect] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=841cd8d1-619a-5c98-9a2b-ea88e02cdab9
    execution = material.run_operation_review_v1(
        operation_name='pf_s10_collect',
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
