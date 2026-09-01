from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
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

material: MaterialProxy = device('material')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='da8d24df-05cc-55af-841f-d9801c0420d9',
    displayname='0 批次起手 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_af0_batch_startup_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_af0_batch_startup] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=148608ad-d4de-5387-b2b4-7fcac4636007
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_af0_batch_startup@body/0；原节点 {"op":"comment","text":"批次级安全确认门 (HITL): 只确认机器人在安全态、末端为空; 挂的是哪把刀交给下面的智能换刀读权威态自行判定 (与 V2 起手式同文案, 但每批一次而非每样品一次)"}
        # unilab:node_uuid=f5a8b068-3ebc-5d36-86bf-db1dfc948fb5
        with group(name='说明 · 批次级安全确认门 (HITL): 只确认机器人在安全态、末端为空; 挂的是哪把刀交给下面的智能换刀读权威态自行判'):
            # [VERIFY comment] 只读来源校验 pf_af0_batch_startup@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=626edad8-10c0-57cd-9941-cac0c24cd7ec disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_af0_batch_startup',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='483d9528a9766ec010b04e4873d0c8a6908f9d75486d5fdaa1aab3200a46301a',
            )
        # [CONTROL human] 来源 pf_af0_batch_startup@body/1；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"[批次起手] 确认机器人处于安全态且末端已空 (吸盘无残留板 / 夹爪无残留件)? 当前挂载工具由系统读 robot_tool_state.json 自行判定并按需换到吸盘, 无需人工声明"}}
        # unilab:node_uuid=e319cfbb-4ae7-5089-b6e4-3838b7686631
        with group(name='◆ HITL 人工门'):
            # [VERIFY human] 只读来源校验 pf_af0_batch_startup@body/1；节点在本工作流中静态 disabled。
            # unilab:node_uuid=fed8a29e-f08d-5380-baf0-75c4c56d559e disabled=true
            projected_control_0002 = material.review_control_node_v1(
                operation_name='pf_af0_batch_startup',
                node_path='body/1',
                control_kind='human',
                expected_sha256='eb7d8802f32c26556f283e379b3ea489917575cc9b6a19c0b881c20685d1a086',
            )
        # [SUBWORKFLOW robot_startup_check] 由 pf_af0_batch_startup@body/2 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=6e900775-e4f5-5821-b4be-e60a1cdeca4a
        with group(name='↳ robot_startup_check'):
            # [CONTROL comment] 来源 robot_startup_check@body/0；原节点 {"op":"comment","text":"读机器人状态 (态/报警/使能; 操作员据此判断)"}
            # unilab:node_uuid=b66d2e59-509e-54bc-9f2b-e2647a983289
            with group(name='说明 · 读机器人状态 (态/报警/使能; 操作员据此判断)'):
                # [VERIFY comment] 只读来源校验 robot_startup_check@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=deb439ad-1e32-5add-a5cd-28b4682ddcf1 disabled=true
                projected_control_0003 = material.review_control_node_v1(
                    operation_name='robot_startup_check',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='7cda7a2fb7460e665015213b9a975c4b3a78c495d7d0fcb076aa076007dc6eb1',
                )
            # [ACTION robot.query] 来源 robot_startup_check@body/1；原节点 {"action":"robot.query","mode":"RUN","op":"call"}
            # unilab:node_uuid=918e8031-3733-5bf3-ae83-af87d345c5d7 disabled=true
            projected_action_0004 = robot.query()
            # [CONTROL comment] 来源 robot_startup_check@body/2；原节点 {"op":"comment","text":"确保已在原点 P1 (=robot-main.home); 安全邻域内自动回零","邻域外/持真空停流程":null}
            # unilab:node_uuid=265f9e49-59e2-523c-9545-1f7d0347ad3e
            with group(name='说明 · 确保已在原点 P1 (=robot-main.home); 安全邻域内自动回零'):
                # [VERIFY comment] 只读来源校验 robot_startup_check@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=cddabca3-6d17-5459-aca5-4d05c046c71a disabled=true
                projected_control_0005 = material.review_control_node_v1(
                    operation_name='robot_startup_check',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='6a40ecad06e39bc4c89d9d25afcd0734398fd903d1756e8f0f416e326f41ba14',
                )
            # [ACTION robot.home_ensure] 来源 robot_startup_check@body/3；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=92384926-cf88-53a6-a05a-a08d550a0610 disabled=true
            projected_action_0006 = robot.home_ensure()
        # [CONTROL comment] 来源 pf_af0_batch_startup@body/3；原节点 {"op":"comment","text":"起手换刀: 读权威工具态 -> 已是吸盘则跳过, 否则自动换到吸盘 (幂等, 整段可盲重跑)"}
        # unilab:node_uuid=e955e730-25df-569b-9076-e169d140ddf0
        with group(name='说明 · 起手换刀: 读权威工具态 -> 已是吸盘则跳过, 否则自动换到吸盘 (幂等, 整段可盲重跑)'):
            # [VERIFY comment] 只读来源校验 pf_af0_batch_startup@body/3；节点在本工作流中静态 disabled。
            # unilab:node_uuid=f7d6cb45-7964-5422-b7a9-d6c2c34b8447 disabled=true
            projected_control_0007 = material.review_control_node_v1(
                operation_name='pf_af0_batch_startup',
                node_path='body/3',
                control_kind='comment',
                expected_sha256='266c516d8ad532a1da8bef8aa777f12ee11361103c747d4c15e4d45938111b94',
            )
        # [SUBWORKFLOW robot_tool_ensure] 由 pf_af0_batch_startup@body/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=3bc8cdf0-6a76-5bbd-bc94-b3b5a02c24b9
        with group(name='↳ robot_tool_ensure'):
            # [CONTROL comment] 来源 robot_tool_ensure@body/0；原节点 {"op":"comment","text":"读权威工具态 (mounted_tool 启动已从状态文件恢复","回显在 tool_state.mounted_tool)":null}
            # unilab:node_uuid=78bb37f7-0512-55ad-bb9f-3154414b56ee
            with group(name='说明 · 读权威工具态 (mounted_tool 启动已从状态文件恢复'):
                # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=0967caba-5867-5c05-9a5b-d700d5079227 disabled=true
                projected_control_0008 = material.review_control_node_v1(
                    operation_name='robot_tool_ensure',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='d809e1de31eaaae6a28b91dfdc9f8587e53c48ce272668a1d7794e15c68d86f9',
                )
            # [ACTION robot.query] 来源 robot_tool_ensure@body/1；原节点 {"action":"robot.query","assign":{"var":"fb"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2cd15fa0-9f48-50aa-8cae-15db57c815d9 disabled=true
            projected_action_0009 = robot.query()
            # [CONTROL assign] 来源 robot_tool_ensure@body/2；原节点 {"op":"assign","target":{"var":"current"},"value":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"mounted_tool"}}
            # unilab:node_uuid=ee8651b3-9c00-59ea-922a-c201cdeffbf2
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 robot_tool_ensure@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=96a13b51-3016-52cb-9046-d7abb87ff151 disabled=true
                projected_control_0010 = material.review_control_node_v1(
                    operation_name='robot_tool_ensure',
                    node_path='body/2',
                    control_kind='assign',
                    expected_sha256='0a8bed4ab1ed21eab44aa30c3cdc41f38a8147534c728fa885ef1da0ba3237c7',
                )
            # [CONTROL if] 来源 robot_tool_ensure@body/3；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"var":"needed"}},"op":"if","then":[{"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"},{"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"},{"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"r...
            # unilab:node_uuid=6fc36264-54e1-5013-bd71-1fa7962bd838
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                # unilab:node_uuid=722a3570-50ae-50af-bd8a-02fbccae05f7 disabled=true
                projected_control_0011 = material.review_control_node_v1(
                    operation_name='robot_tool_ensure',
                    node_path='body/3',
                    control_kind='if',
                    expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                )
                # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then 的静态审阅分支。
                # unilab:node_uuid=fc7d0a20-8d61-57d3-a182-a16c148dbae9
                with group(name='THEN（互斥分支）'):
                    # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/0；原节点 {"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"}
                    # unilab:node_uuid=ada32552-841c-50d8-9fb2-8944ae2372f6
                    with group(name='说明 · 当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标'):
                        # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=71ae82ea-9281-5be6-89d9-a0bc6e91f05c disabled=true
                        projected_control_0012 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/3/then/0',
                            control_kind='comment',
                            expected_sha256='f1c1621fc9a3af0fead9abddfba4acc6d628c4e07f02d5e1d6e79342f780d4b5',
                        )
                    # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/1；原节点 {"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"}
                    # unilab:node_uuid=1235513e-5208-587b-bcf2-03ed917d437c
                    with group(name='说明 · 卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止'):
                        # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/1；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=42cfa785-44dc-5107-93e3-418a589864ae disabled=true
                        projected_control_0013 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/3/then/1',
                            control_kind='comment',
                            expected_sha256='ab6b298fa1974e89ffba98e42a169ccd9b213ac1a03a6723584be2b1be7e6898',
                        )
                    # [CONTROL if] 来源 robot_tool_ensure@body/3/then/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"right":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"suction_on"}},"op":"if","then":[{"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}]}
                    # unilab:node_uuid=0652ee60-4187-5512-beae-5521268157c9
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=20242589-19a0-5cc9-9d9f-4b41a15e6327 disabled=true
                        projected_control_0014 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/3/then/2',
                            control_kind='if',
                            expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                        )
                        # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/2/then 的静态审阅分支。
                        # unilab:node_uuid=d20017d6-098d-50c0-8525-6bca32db7b64
                        with group(name='THEN（互斥分支）'):
                            # [CONTROL raise] 来源 robot_tool_ensure@body/3/then/2/then/0；原节点 {"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}
                            # unilab:node_uuid=69bd39c4-24f3-5417-bd24-2276d6f87c87
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_tool_ensure@body/3/then/2/then/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=f305454d-20d1-5749-92b4-c9a5aba2b777 disabled=true
                                projected_control_0015 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/2/then/0',
                                    control_kind='raise',
                                    expected_sha256='8ade635dfc3c21601ac8fa50ba7a168191332f67cbf70e021465f2765df9b23f',
                                )
                        # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/2/else 的静态审阅分支。
                        # unilab:node_uuid=df0007d7-c383-5c95-9d15-8f3af2c3a814
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=dde481c3-5f68-56e9-85d9-89c2074e9722 disabled=true
                            projected_control_0016 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/2',
                                control_kind='if',
                                expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                            )
                    # [SUBWORKFLOW rail_move_safe] 由 robot_tool_ensure@body/3/then/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=4fda376e-864c-5d5a-b367-32a2836e0442
                    with group(name='↳ rail_move_safe'):
                        # [CONTROL comment] 来源 rail_move_safe@body/0；原节点 {"op":"comment","text":"确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)"}
                        # unilab:node_uuid=034e0d90-6f51-56f8-a6b2-d0111be8e71e
                        with group(name='说明 · 确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)'):
                            # [VERIFY comment] 只读来源校验 rail_move_safe@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=57795d6e-f2b1-5348-b606-14bddde4e23e disabled=true
                            projected_control_0017 = material.review_control_node_v1(
                                operation_name='rail_move_safe',
                                node_path='body/0',
                                control_kind='comment',
                                expected_sha256='cc629ec60964ec74a746185851e52069f3b991388ab52755ebea4f3b92ed1740',
                            )
                        # [ACTION robot.home_ensure] 来源 rail_move_safe@body/1；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d2aa6b15-cfcb-5d59-b663-427217e86705 disabled=true
                        projected_action_0018 = robot.home_ensure()
                        # [CONTROL comment] 来源 rail_move_safe@body/2；原节点 {"op":"comment","text":"安全位确认 -> 移动地轨到目标位"}
                        # unilab:node_uuid=235c93e0-e3dd-56fc-a0c0-9ab6a0d3f961
                        with group(name='说明 · 安全位确认 -> 移动地轨到目标位'):
                            # [VERIFY comment] 只读来源校验 rail_move_safe@body/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=b468ade6-bcd5-56a0-a90f-d2afd1dbf91d disabled=true
                            projected_control_0019 = material.review_control_node_v1(
                                operation_name='rail_move_safe',
                                node_path='body/2',
                                control_kind='comment',
                                expected_sha256='38f90a43c3043b67cd1207e8d94cd7c595a01ab69567c39518284d36ecb68702',
                            )
                        # [ACTION rail.move] 来源 rail_move_safe@body/3；原节点 {"action":"rail.move","args":{"Rail_Target_Position":{"var":"target"}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1cf99070-fc4f-5f8f-84de-e7043cc444d2 disabled=true
                        projected_action_0020 = rail.move(
                            Rail_Target_Position=1,
                        )
                    # [CONTROL if] 来源 robot_tool_ensure@body/3/then/4；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"lit":0}},"op":"if","then":[{"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}]}
                    # unilab:node_uuid=954d75e5-06eb-5c4f-94b8-e05efdea437c
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=9392d399-d7a8-5904-8f91-63bdae0dcdc9 disabled=true
                        projected_control_0021 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/3/then/4',
                            control_kind='if',
                            expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                        )
                        # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/4/then 的静态审阅分支。
                        # unilab:node_uuid=43eeeb10-cfc6-5b98-83d7-9d67e5cc018d
                        with group(name='THEN（互斥分支）'):
                            # [SUBWORKFLOW robot_tool_put] 由 robot_tool_ensure@body/3/then/4/then/0 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                            # unilab:node_uuid=ad9cf584-2c23-59aa-8414-374bf69ef86a
                            with group(name='↳ robot_tool_put'):
                                # [CONTROL if] 来源 robot_tool_put@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit...
                                # unilab:node_uuid=57251890-9fa9-52fd-a939-116d4f3f7b3d
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_tool_put@body/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=950721bd-c3fd-55b6-adea-753574873b5f disabled=true
                                    projected_control_0022 = material.review_control_node_v1(
                                        operation_name='robot_tool_put',
                                        node_path='body/0',
                                        control_kind='if',
                                        expected_sha256='9c64b805f035e287559b6a10c2883f201fed2852028900bfd6c9c7526352d298',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_tool_put@body/0/then 的静态审阅分支。
                                    # unilab:node_uuid=9cbc082f-d732-530f-a2c8-fe346ba6253a
                                    with group(name='THEN（互斥分支）'):
                                        # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=78c707b6-4915-5ff0-b90c-985c172aa87c disabled=true
                                        projected_action_0023 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                        # [ACTION rail.ensure] 来源 robot_tool_put@body/0/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=4baeb81e-4352-563b-be5f-e07efa371f5e disabled=true
                                        projected_action_0024 = rail.ensure(
                                            Rail_Target_Position=4,
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=339f85db-4444-5990-bb86-d60e76dca039 disabled=true
                                        projected_action_0025 = robot.tool_action(
                                            action='rotary-down',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=61fd0679-e951-58a6-ba90-71514d315c05 disabled=true
                                        projected_action_0026 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=de756d0c-7ef4-5618-8581-8ace73f4f3ff disabled=true
                                        projected_action_0027 = robot.tool_action(
                                            action='tool-change-aux-on',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=29bcf9b4-0d66-5688-bc5a-0be19c0e0da5 disabled=true
                                        projected_action_0028 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=c0277121-bc26-59f5-92eb-2d8dd4ea01f2 disabled=true
                                        projected_action_0029 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=ebb9cb3f-8050-5c7e-b236-d3c7dbc9ea47 disabled=true
                                        projected_action_0030 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=95dc31f5-516b-5ef4-8891-31b1d136eee3 disabled=true
                                        projected_action_0031 = robot.tool_action(
                                            action='quick-change-release',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/9；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=e47a64f9-867e-51ae-93be-980250c73b36 disabled=true
                                        projected_action_0032 = robot.tool_action(
                                            action='tool-change-aux-off',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/then/10；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=e506d1e5-b63b-5bb6-bdfe-e7a1919cae91 disabled=true
                                        projected_action_0033 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=8baceb35-2bfd-5ba2-a953-66f8569139e7 disabled=true
                                        projected_action_0034 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=53436c87-b1ff-55c1-a23e-63b359754f7b disabled=true
                                        projected_action_0035 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                        )
                                    # [BRANCH ELIF 1（互斥分支）] robot_tool_put@body/0/elifs/0/body 的静态审阅分支。
                                    # unilab:node_uuid=c8cfdefe-a86f-526e-9363-f898f6511eed
                                    with group(name='ELIF 1（互斥分支）'):
                                        # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=5a72bd55-c1ad-5ad3-aa69-b51db3c7178c disabled=true
                                        projected_action_0036 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                        # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=659a3fbe-6586-5a80-8fe8-4a35906e4955 disabled=true
                                        projected_action_0037 = rail.ensure(
                                            Rail_Target_Position=4,
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=d99a9f9c-cf5d-5789-b49e-c1bb26fe87fc disabled=true
                                        projected_action_0038 = robot.tool_action(
                                            action='gripper-close',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=850547cd-d0cd-5506-ac58-ce4599c81785 disabled=true
                                        projected_action_0039 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=4e30c6bd-7648-5248-a881-d14ebdbebb55 disabled=true
                                        projected_action_0040 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=a13d352a-2b96-5d5d-9700-264e33feac32 disabled=true
                                        projected_action_0041 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=f1900260-e48b-5202-9d89-18e90c90a446 disabled=true
                                        projected_action_0042 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=aca88cc0-56d2-5240-a0ed-24c234d4ea7b disabled=true
                                        projected_action_0043 = robot.tool_action(
                                            action='quick-change-release',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=0e8e3271-cd8a-54dd-a858-c1b4a12eea2f disabled=true
                                        projected_action_0044 = robot.tool_action(
                                            action='tool-change-aux-off',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/0/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=e78b3c5b-d77c-534c-84ea-b15081460098 disabled=true
                                        projected_action_0045 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=4db699ba-a7fc-5505-a793-24011b2f759b disabled=true
                                        projected_action_0046 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=7f17c568-d974-51c5-88ab-75007aa75b9e disabled=true
                                        projected_action_0047 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                        )
                                    # [BRANCH ELIF 2（互斥分支）] robot_tool_put@body/0/elifs/1/body 的静态审阅分支。
                                    # unilab:node_uuid=05f189d0-2aa7-59a4-9bbc-fb80bef5a728
                                    with group(name='ELIF 2（互斥分支）'):
                                        # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=c7c9325f-477b-5311-b161-4fc827803523 disabled=true
                                        projected_action_0048 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                        # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=fdcb67c8-731f-589a-bb86-ea894ad0bbca disabled=true
                                        projected_action_0049 = rail.ensure(
                                            Rail_Target_Position=4,
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=4da917d0-9344-5f3e-89f9-0b8924cb71dd disabled=true
                                        projected_action_0050 = robot.tool_action(
                                            action='gripper-close',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=be3ff2dc-fe85-5f05-8ec7-56ac42143d74 disabled=true
                                        projected_action_0051 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=dfda287f-be20-5f9c-9457-38fee7327e86 disabled=true
                                        projected_action_0052 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=aac7088b-3538-57f2-a413-1bf23f160e7a disabled=true
                                        projected_action_0053 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=602c5b87-d75e-5982-89a3-5099a9f9f2e2 disabled=true
                                        projected_action_0054 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=3edbebe4-12b7-51cc-a830-a656ddf72b98 disabled=true
                                        projected_action_0055 = robot.tool_action(
                                            action='quick-change-release',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=d4afdef2-9a16-5ef9-b0d6-db65c7f78e33 disabled=true
                                        projected_action_0056 = robot.tool_action(
                                            action='tool-change-aux-off',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/1/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=24303545-72fe-5eaf-af93-352e1f8e56a0 disabled=true
                                        projected_action_0057 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=60716cb9-30a4-5a39-89fc-9d0c6f0626e1 disabled=true
                                        projected_action_0058 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=c3351fe0-fa9f-5bf2-8086-ddf5908920ea disabled=true
                                        projected_action_0059 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                        )
                                    # [BRANCH ELSE（互斥分支）] robot_tool_put@body/0/else 的静态审阅分支。
                                    # unilab:node_uuid=6b3127e4-e85e-506a-b819-140e2b9bc441
                                    with group(name='ELSE（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_tool_put@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"tool.put: 无效选择值"},"op":"raise"}
                                        # unilab:node_uuid=e433f07a-f093-5066-b0e9-4c5b009d1e3a
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_tool_put@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=6aa3c2fb-f7c5-5944-a28c-d8db91d2f622 disabled=true
                                            projected_control_0060 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='8aa6aa6f749c6777b2a7040e04f4316dd03cc80d36de51eec476b3dbb6c6de75',
                                            )
                        # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/4/else 的静态审阅分支。
                        # unilab:node_uuid=8d1a7c04-e551-5f49-82d0-cf52243e0584
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=90a99b04-e560-5cb5-8e64-8d1584e07808 disabled=true
                            projected_control_0061 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/4',
                                control_kind='if',
                                expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                            )
                    # [SUBWORKFLOW robot_tool_pick] 由 robot_tool_ensure@body/3/then/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=b1ea827a-9268-53e5-8c4a-fe4acac52b0d
                    with group(name='↳ robot_tool_pick'):
                        # [CONTROL if] 来源 robot_tool_pick@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"},{"action":"robot.move...
                        # unilab:node_uuid=fb0f32a7-5569-5b4f-b4ab-e11898a54635
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_tool_pick@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=f0d977ca-0b74-5671-916a-43530244f142 disabled=true
                            projected_control_0062 = material.review_control_node_v1(
                                operation_name='robot_tool_pick',
                                node_path='body/0',
                                control_kind='if',
                                expected_sha256='47a5b48eb2b065101041caadd225ef492b21028bb19039ac3a19991997da1895',
                            )
                            # [BRANCH THEN（互斥分支）] robot_tool_pick@body/0/then 的静态审阅分支。
                            # unilab:node_uuid=80eb1746-97eb-5679-a38a-2f8385885a81
                            with group(name='THEN（互斥分支）'):
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=96d6177e-6e45-5072-84e8-fb7ba5894659 disabled=true
                                projected_action_0063 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=d16b1e55-8c7e-535a-8ad4-c2ab595e292a disabled=true
                                projected_action_0064 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=47ea4b1a-743c-587e-92fe-0b7dab985939 disabled=true
                                projected_action_0065 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                )
                                # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2e96aa86-ecec-51a3-92bc-eb727467067b disabled=true
                                projected_action_0066 = robot.tool_action(
                                    action='quick-change-lock',
                                )
                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/then/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":1}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=c1d2d808-1d7b-56b0-99e0-40896a1fadd3 disabled=true
                                projected_action_0067 = robot.set_mounted_tool(
                                    tool_id='0',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ad25e971-db67-5f3a-a542-c3292efcf9cb disabled=true
                                projected_action_0068 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=37a3e2cb-8cdd-514d-ac40-a1479d7b2dc7 disabled=true
                                projected_action_0069 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=31082ab9-1532-5fb2-867f-03248e503573 disabled=true
                                projected_action_0070 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                )
                                # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=07c793ae-a5ae-5f90-9ca5-c003f24912f1 disabled=true
                                projected_action_0071 = robot.dwell(
                                    duration_ms=500,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=44212a8e-ffa1-548c-9944-4c03b682664c disabled=true
                                projected_action_0072 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.home',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=47d68ec7-a91f-546b-9f97-d52b6570f6ec disabled=true
                                projected_action_0073 = robot.require_anchor(
                                    point_id='robot-main.home',
                                )
                            # [BRANCH ELIF 1（互斥分支）] robot_tool_pick@body/0/elifs/0/body 的静态审阅分支。
                            # unilab:node_uuid=2d05b615-8584-529c-a9e8-28821f36dff6
                            with group(name='ELIF 1（互斥分支）'):
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=238590f0-4dc6-5ec9-8d67-991c162fe24a disabled=true
                                projected_action_0074 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=acc4732e-ccb9-5df5-8b35-04949bfea289 disabled=true
                                projected_action_0075 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=b3ea4114-8a2d-5e9b-a011-8bcb7c2b3e19 disabled=true
                                projected_action_0076 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                )
                                # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=e9b4bd80-3323-59da-b408-ad7f23e5deb7 disabled=true
                                projected_action_0077 = robot.tool_action(
                                    action='quick-change-lock',
                                )
                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/0/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":2}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=3cb37fda-b6d9-5146-a3b7-3ead21aaaf58 disabled=true
                                projected_action_0078 = robot.set_mounted_tool(
                                    tool_id='0',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a7246fe3-557f-594c-8df2-37add4096318 disabled=true
                                projected_action_0079 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=2e3326a2-4dd1-5064-adc8-d91ac9638515 disabled=true
                                projected_action_0080 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9f13c203-b9ba-5a41-9e15-6e16582dc9c4 disabled=true
                                projected_action_0081 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                )
                                # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/0/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=f31d5e28-c62f-5a63-b937-e32e5304a929 disabled=true
                                projected_action_0082 = robot.dwell(
                                    duration_ms=500,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ff294dae-deac-5a48-a36e-091de44f3289 disabled=true
                                projected_action_0083 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.home',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4551c689-a214-57f0-a542-9d10d63c0da5 disabled=true
                                projected_action_0084 = robot.require_anchor(
                                    point_id='robot-main.home',
                                )
                            # [BRANCH ELIF 2（互斥分支）] robot_tool_pick@body/0/elifs/1/body 的静态审阅分支。
                            # unilab:node_uuid=add12124-7c32-5c9f-b0a5-c40095a39e51
                            with group(name='ELIF 2（互斥分支）'):
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=bf8921a2-efb3-5300-b21d-f51e7e1f1583 disabled=true
                                projected_action_0085 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a0b5e7ec-a10b-5626-904b-bdf1360fe720 disabled=true
                                projected_action_0086 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a58b99b2-7606-50af-bdb8-9c0cfb2495e3 disabled=true
                                projected_action_0087 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                )
                                # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/1/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=04ab60c9-f5ae-517c-8e97-20773e3fa170 disabled=true
                                projected_action_0088 = robot.tool_action(
                                    action='quick-change-lock',
                                )
                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/1/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":3}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=6882a580-5328-5992-9614-622bee455e9f disabled=true
                                projected_action_0089 = robot.set_mounted_tool(
                                    tool_id='0',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=49db1bcb-5026-5395-84f4-fc73584779a4 disabled=true
                                projected_action_0090 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=6424f4b0-1f2e-58c0-96d6-220194dacf69 disabled=true
                                projected_action_0091 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=591ff597-03dc-55f8-bcc2-1eb765ee748d disabled=true
                                projected_action_0092 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                )
                                # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/1/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a5002198-a585-5823-a1ad-f5e575cdc6bb disabled=true
                                projected_action_0093 = robot.dwell(
                                    duration_ms=500,
                                )
                                # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a5f5f3a2-9112-5ee7-9437-fa4faba6ed7e disabled=true
                                projected_action_0094 = robot.move_to_point(
                                    point_id_or_robot_name='robot-main.home',
                                )
                                # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=87d88dba-214d-5889-b56e-3f5d4742b612 disabled=true
                                projected_action_0095 = robot.require_anchor(
                                    point_id='robot-main.home',
                                )
                            # [BRANCH ELSE（互斥分支）] robot_tool_pick@body/0/else 的静态审阅分支。
                            # unilab:node_uuid=e9197e04-aa28-5c5e-a72f-b3551645d4a4
                            with group(name='ELSE（互斥分支）'):
                                # [CONTROL raise] 来源 robot_tool_pick@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"tool.pick: 无效选择值"},"op":"raise"}
                                # unilab:node_uuid=8ff0700a-e764-5c4f-ac22-4ac1b58d4787
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_tool_pick@body/0/else/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=2e0bd68a-157f-50e5-8fe1-942b9111403e disabled=true
                                    projected_control_0096 = material.review_control_node_v1(
                                        operation_name='robot_tool_pick',
                                        node_path='body/0/else/0',
                                        control_kind='raise',
                                        expected_sha256='70c2a7e291023e9375102dc659639ba2604e87ffa8a3a94cca033c80b83c21e8',
                                    )
                # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/else 的静态审阅分支。
                # unilab:node_uuid=d3c1f063-fb16-5247-baa1-247e110da0a2
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=93ef209f-4682-52b9-96eb-6c9776edc6ae disabled=true
                    projected_control_0097 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                    )
    # [EXECUTE ROOT pf_af0_batch_startup] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=492067d3-de74-51c2-a523-474c0e909b9a
    execution = material.run_operation_review_v1(
        operation_name='pf_af0_batch_startup',
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
