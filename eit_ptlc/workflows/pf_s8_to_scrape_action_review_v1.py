from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.plc_develop import PLCDevelop
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.unilab_domain.devices.plc_rail import PLCRail
from eit_ptlc.unilab_domain.devices.robot import RobotProxy
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

develop: PLCDevelop = device('plc_develop')
material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')
vision: VisionProxy = device('vision')


@workflow(
    workflow_uuid='2289f4bd-8020-533c-9a9c-0ea4b6f679f6',
    displayname='6 出缸上刮板台 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s8_to_scrape_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s8_to_scrape] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=9bc5b742-e94b-5ac0-9498-e93b912220fc
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s8_to_scrape@body/0；原节点 {"op":"comment","text":"出缸: 开盖 -> plate_retract -> robot_tank_pick (持板出缸); 地轨到位由脚本自管"}
        # unilab:node_uuid=2f72c502-e924-5cf3-84a0-bf7f25c10114
        with group(name='说明 · 出缸: 开盖 -> plate_retract -> robot_tank_pick (持板出缸); 地轨到位由'):
            # [VERIFY comment] 只读来源校验 pf_s8_to_scrape@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=82b575f6-2b6a-50a3-bda9-d8eb8d822fff disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s8_to_scrape',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='254366bd515d3761b62e7fa181af00d53d8bb0cfc863ecefab2c91c322f55221',
            )
        # [SUBWORKFLOW develop_unload] 由 pf_s8_to_scrape@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=e6257300-3e4a-5ce9-a5cc-8cfaf3300c61
        with group(name='↳ develop_unload'):
            # [CONTROL comment] 来源 develop_unload@body/0；原节点 {"op":"comment","text":"unload: 先地轨就位再开盖 —— 地轨到展开区(位5) 必须早于 plate_retract, 否则板在开盖状态下白等一个移轨时长 (蒸气/干燥环境暴露)。原为 develop_execute 内 T1 命中后的 develop_standby, 挂在 execute 根上会让整段液位等待 (硬上限 3600s) 虚占机械臂与地轨, 故并入本段。rail_move_safe 自带 P1 确保式安全门 (地轨平移拖臂, 不可绕过); robot_tank_pick 入口的 rail.ensure(5) 保留为兜底, 此处已就位时退化为幂等空操作"}
            # unilab:node_uuid=f0cc64ea-666e-5cf8-ba15-d88e39c82658
            with group(name='说明 · unload: 先地轨就位再开盖 —— 地轨到展开区(位5) 必须早于 plate_retract, 否则板在开'):
                # [VERIFY comment] 只读来源校验 develop_unload@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=c7a6fec4-b45b-5e42-820d-3ad0e13b5aec disabled=true
                projected_control_0002 = material.review_control_node_v1(
                    operation_name='develop_unload',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='2beda758cac8314f74ff459463d7f28c737d72ce065de22c3b05f87a5cff73f3',
                )
            # [SUBWORKFLOW rail_move_safe] 由 develop_unload@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=a99a788d-122d-5051-b3b3-366fd3a4777b
            with group(name='↳ rail_move_safe'):
                # [CONTROL comment] 来源 rail_move_safe@body/0；原节点 {"op":"comment","text":"确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)"}
                # unilab:node_uuid=bab45f50-fe1f-5639-9978-fcdcb5c9a635
                with group(name='说明 · 确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)'):
                    # [VERIFY comment] 只读来源校验 rail_move_safe@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=529a7a25-addb-5e9e-b486-e6bcd1ba3307 disabled=true
                    projected_control_0003 = material.review_control_node_v1(
                        operation_name='rail_move_safe',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='cc629ec60964ec74a746185851e52069f3b991388ab52755ebea4f3b92ed1740',
                    )
                # [ACTION robot.home_ensure] 来源 rail_move_safe@body/1；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                # unilab:node_uuid=8b497f08-dac2-54fa-b63d-bb350f22f305 disabled=true
                projected_action_0004 = robot.home_ensure()
                # [CONTROL comment] 来源 rail_move_safe@body/2；原节点 {"op":"comment","text":"安全位确认 -> 移动地轨到目标位"}
                # unilab:node_uuid=fa07dbf9-4733-5b24-aaeb-2a0f2cceca2e
                with group(name='说明 · 安全位确认 -> 移动地轨到目标位'):
                    # [VERIFY comment] 只读来源校验 rail_move_safe@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=59cbf221-80ba-5cbb-964d-870289de974c disabled=true
                    projected_control_0005 = material.review_control_node_v1(
                        operation_name='rail_move_safe',
                        node_path='body/2',
                        control_kind='comment',
                        expected_sha256='38f90a43c3043b67cd1207e8d94cd7c595a01ab69567c39518284d36ecb68702',
                    )
                # [ACTION rail.move] 来源 rail_move_safe@body/3；原节点 {"action":"rail.move","args":{"Rail_Target_Position":{"var":"target"}},"mode":"RUN","op":"call"}
                # unilab:node_uuid=d76f82f9-b494-5a45-9403-6693e8226f4a disabled=true
                projected_action_0006 = rail.move(
                    Rail_Target_Position=1,
                )
            # [CONTROL comment] 来源 develop_unload@body/2；原节点 {"op":"comment","text":"unload: 开盖 (放板缸/展缸盖同一执行器回原点), 允许机器人取板出缸; 排液终态 Tank_State=98 盖保持关, 此处 just-in-time 开盖"}
            # unilab:node_uuid=392b1b5f-b53d-56b8-b8b1-519f0bcb8d86
            with group(name='说明 · unload: 开盖 (放板缸/展缸盖同一执行器回原点), 允许机器人取板出缸; 排液终态 Tank_State'):
                # [VERIFY comment] 只读来源校验 develop_unload@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=233fa108-2ee6-57bb-8376-0a980043ba49 disabled=true
                projected_control_0007 = material.review_control_node_v1(
                    operation_name='develop_unload',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='fe8d4b7fe862f45a05c9e482b4803da64c3475f87c42d39c7f701016b2ad919a',
                )
            # [ACTION develop.plate_retract] 来源 develop_unload@body/3；原节点 {"action":"develop.plate_retract","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=32eb359a-d7d4-5c32-afed-c88e2cae5d11 disabled=true
            projected_action_0008 = develop.plate_retract(
                target_tank=1,
            )
            # [CONTROL comment] 来源 develop_unload@body/4；原节点 {"op":"comment","text":"unload: 机器人取板出缸; Tank_State=98 表示已断液待取板 (板仍在缸内)"}
            # unilab:node_uuid=31cda09b-5696-5baf-8231-855572206688
            with group(name='说明 · unload: 机器人取板出缸; Tank_State=98 表示已断液待取板 (板仍在缸内)'):
                # [VERIFY comment] 只读来源校验 develop_unload@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=8215213e-e4d9-5c38-91d0-f0b224bbeeef disabled=true
                projected_control_0009 = material.review_control_node_v1(
                    operation_name='develop_unload',
                    node_path='body/4',
                    control_kind='comment',
                    expected_sha256='5abdcb4bd85a722a39a4acc007f07b009d624d3ca0b1a12c403a10a9d53e54f7',
                )
            # [SUBWORKFLOW robot_tank_pick] 由 develop_unload@body/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=6d1df6de-71e9-533e-b6dc-9407f89b6300
            with group(name='↳ robot_tank_pick'):
                # [CONTROL comment] 来源 robot_tank_pick@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                # unilab:node_uuid=1dbfb78c-b989-5c99-a40f-d02043eddfc1
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                    # [VERIFY comment] 只读来源校验 robot_tank_pick@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=a4ecf5b7-5d36-5d86-84cb-b9c8742492db disabled=true
                    projected_control_0010 = material.review_control_node_v1(
                        operation_name='robot_tank_pick',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                    )
                # [ACTION robot.home_ensure] 来源 robot_tank_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=166dc0b4-40d2-56aa-80e9-bed6d3f9b5ce disabled=true
                projected_action_0011 = robot.home_ensure()
                # [SUBWORKFLOW robot_tool_ensure] 由 robot_tank_pick@body/2 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=14757ee8-4936-58b7-b8d9-7addc3acf4e3
                with group(name='↳ robot_tool_ensure'):
                    # [CONTROL comment] 来源 robot_tool_ensure@body/0；原节点 {"op":"comment","text":"读权威工具态 (mounted_tool 启动已从状态文件恢复","回显在 tool_state.mounted_tool)":null}
                    # unilab:node_uuid=1f763ed4-7f0a-543a-8a8a-0815a4c5d7c5
                    with group(name='说明 · 读权威工具态 (mounted_tool 启动已从状态文件恢复'):
                        # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=5a47b0ff-3152-5587-aa8e-aeeed5de5553 disabled=true
                        projected_control_0012 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='d809e1de31eaaae6a28b91dfdc9f8587e53c48ce272668a1d7794e15c68d86f9',
                        )
                    # [ACTION robot.query] 来源 robot_tool_ensure@body/1；原节点 {"action":"robot.query","assign":{"var":"fb"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=b4f52b30-747b-5265-8bff-4a3fd09c2bff disabled=true
                    projected_action_0013 = robot.query()
                    # [CONTROL assign] 来源 robot_tool_ensure@body/2；原节点 {"op":"assign","target":{"var":"current"},"value":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"mounted_tool"}}
                    # unilab:node_uuid=fcaef1cb-ebaa-5b25-b18b-370e57bdf6a2
                    with group(name='变量赋值'):
                        # [VERIFY assign] 只读来源校验 robot_tool_ensure@body/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=8fa8598d-8951-585f-a1a1-780e5fa1ccc3 disabled=true
                        projected_control_0014 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/2',
                            control_kind='assign',
                            expected_sha256='0a8bed4ab1ed21eab44aa30c3cdc41f38a8147534c728fa885ef1da0ba3237c7',
                        )
                    # [CONTROL if] 来源 robot_tool_ensure@body/3；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"var":"needed"}},"op":"if","then":[{"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"},{"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"},{"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"r...
                    # unilab:node_uuid=49528d12-6692-59b5-b5d7-29a943847a9f
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=2ac91bf4-4f5c-5c9d-9374-1007708f8ab4 disabled=true
                        projected_control_0015 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/3',
                            control_kind='if',
                            expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                        )
                        # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then 的静态审阅分支。
                        # unilab:node_uuid=5f7e0564-5a05-5b03-821d-a35a049d8512
                        with group(name='THEN（互斥分支）'):
                            # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/0；原节点 {"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"}
                            # unilab:node_uuid=2020ead0-8564-5406-a7cd-8722a73170b4
                            with group(name='说明 · 当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标'):
                                # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=ef95fe7a-fa8f-5ef9-a87e-40d65df0c52f disabled=true
                                projected_control_0016 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/0',
                                    control_kind='comment',
                                    expected_sha256='f1c1621fc9a3af0fead9abddfba4acc6d628c4e07f02d5e1d6e79342f780d4b5',
                                )
                            # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/1；原节点 {"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"}
                            # unilab:node_uuid=c535893f-79f4-5cb7-990a-43d7f38b8060
                            with group(name='说明 · 卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止'):
                                # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/1；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=7cb87c1a-494d-585a-9da8-18f15185268e disabled=true
                                projected_control_0017 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/1',
                                    control_kind='comment',
                                    expected_sha256='ab6b298fa1974e89ffba98e42a169ccd9b213ac1a03a6723584be2b1be7e6898',
                                )
                            # [CONTROL if] 来源 robot_tool_ensure@body/3/then/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"right":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"suction_on"}},"op":"if","then":[{"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}]}
                            # unilab:node_uuid=9dbbb76c-dfde-5dc9-bee5-8c4ca4dcc31c
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=6ead5e10-7d9e-5d5d-82a9-1644e554509c disabled=true
                                projected_control_0018 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/2',
                                    control_kind='if',
                                    expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                )
                                # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/2/then 的静态审阅分支。
                                # unilab:node_uuid=df716f41-2286-51d9-98b2-3fa3b61c5ae1
                                with group(name='THEN（互斥分支）'):
                                    # [CONTROL raise] 来源 robot_tool_ensure@body/3/then/2/then/0；原节点 {"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}
                                    # unilab:node_uuid=71e21641-c9c4-5e4a-8013-18b58a825671
                                    with group(name='抛出流程错误'):
                                        # [VERIFY raise] 只读来源校验 robot_tool_ensure@body/3/then/2/then/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=fc4f2606-4015-5422-910d-52b786698da8 disabled=true
                                        projected_control_0019 = material.review_control_node_v1(
                                            operation_name='robot_tool_ensure',
                                            node_path='body/3/then/2/then/0',
                                            control_kind='raise',
                                            expected_sha256='8ade635dfc3c21601ac8fa50ba7a168191332f67cbf70e021465f2765df9b23f',
                                        )
                                # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/2/else 的静态审阅分支。
                                # unilab:node_uuid=670b1fbf-3261-549b-9554-c06c985f4581
                                with group(name='ELSE（互斥分支）'):
                                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=4a6b076e-3dd4-598d-aa49-b043bfe3f1e5 disabled=true
                                    projected_control_0020 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/2',
                                        control_kind='if',
                                        expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                    )
                            # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 robot_tool_ensure@body/3/then/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=293c12a1-f535-545b-b392-2f0767b7d785 disabled=true
                            projected_control_0021 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/3',
                                control_kind='run_script',
                                expected_sha256='a71d68a21f68d19b7cde73b5c95737ce6077a1b162074653e98fadbcdf8c69f9',
                            )
                            # [CONTROL if] 来源 robot_tool_ensure@body/3/then/4；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"lit":0}},"op":"if","then":[{"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}]}
                            # unilab:node_uuid=94ef43bd-aab6-5080-b9e4-cb132467f0b6
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=1e1741f3-f32c-5618-b4f7-eba93d096c52 disabled=true
                                projected_control_0022 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/4',
                                    control_kind='if',
                                    expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                )
                                # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/4/then 的静态审阅分支。
                                # unilab:node_uuid=57d8f9a7-7be1-565f-967c-3219741f23c8
                                with group(name='THEN（互斥分支）'):
                                    # [SUBWORKFLOW robot_tool_put] 由 robot_tool_ensure@body/3/then/4/then/0 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                    # unilab:node_uuid=3fd7502d-c286-50ae-935e-f371845fc84d
                                    with group(name='↳ robot_tool_put'):
                                        # [CONTROL if] 来源 robot_tool_put@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit...
                                        # unilab:node_uuid=9bc92a18-5266-54fa-808d-739c58af44a2
                                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                                            # [VERIFY if] 只读来源校验 robot_tool_put@body/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=22649f6e-fe82-564c-b60d-063a39838d47 disabled=true
                                            projected_control_0023 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0',
                                                control_kind='if',
                                                expected_sha256='9c64b805f035e287559b6a10c2883f201fed2852028900bfd6c9c7526352d298',
                                            )
                                            # [BRANCH THEN（互斥分支）] robot_tool_put@body/0/then 的静态审阅分支。
                                            # unilab:node_uuid=73eaff40-791a-5825-81c9-78567184cde3
                                            with group(name='THEN（互斥分支）'):
                                                # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=30a4e40c-559e-56bd-8c34-79393d7ff8d2 disabled=true
                                                projected_action_0024 = robot.require_anchor(
                                                    point_id='robot-main.home',
                                                )
                                                # [ACTION rail.ensure] 来源 robot_tool_put@body/0/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=043bd3b8-d5d5-5772-a533-2b0675f384b3 disabled=true
                                                projected_action_0025 = rail.ensure(
                                                    Rail_Target_Position=4,
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=24bbfec3-ecf5-5163-86bf-9316d173d535 disabled=true
                                                projected_action_0026 = robot.tool_action(
                                                    action='rotary-down',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=96fa965e-430f-5e24-81df-f20b8b500128 disabled=true
                                                projected_action_0027 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=3c2ffc6f-0cb9-51bd-8154-dffae7be9fff disabled=true
                                                projected_action_0028 = robot.tool_action(
                                                    action='tool-change-aux-on',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=9d201f31-9e3a-5236-a8ed-5f0faaca8b6a disabled=true
                                                projected_action_0029 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=2b25c693-eddc-5301-9627-c9448eef6e82 disabled=true
                                                projected_action_0030 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=d3d25cf8-e44d-5742-a725-fd9c1b8a3623 disabled=true
                                                projected_action_0031 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=2a3863f7-e8c5-5854-be7b-f06df86f856f disabled=true
                                                projected_action_0032 = robot.tool_action(
                                                    action='quick-change-release',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/9；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=2383ea94-21b3-5d73-852f-2a25e3bf2050 disabled=true
                                                projected_action_0033 = robot.tool_action(
                                                    action='tool-change-aux-off',
                                                )
                                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/then/10；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=690cff9d-b0d0-5a4b-9e4a-f5321d0072b4 disabled=true
                                                projected_action_0034 = robot.set_mounted_tool(
                                                    tool_id='0',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=e3ab94e9-dcc9-5751-a045-77ea192134b1 disabled=true
                                                projected_action_0035 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=5457370c-3d4d-5346-aced-c3a4faf8db29 disabled=true
                                                projected_action_0036 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                                )
                                            # [BRANCH ELIF 1（互斥分支）] robot_tool_put@body/0/elifs/0/body 的静态审阅分支。
                                            # unilab:node_uuid=b3881713-9c5c-54e2-8644-ce15c43fb100
                                            with group(name='ELIF 1（互斥分支）'):
                                                # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=8c2627b3-d8e5-5006-92a4-41000c6cb400 disabled=true
                                                projected_action_0037 = robot.require_anchor(
                                                    point_id='robot-main.home',
                                                )
                                                # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=11be72f6-cd09-5dbb-b6bd-3894fb1c102c disabled=true
                                                projected_action_0038 = rail.ensure(
                                                    Rail_Target_Position=4,
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=e0a5e775-1910-5b7f-a7d7-012f4d78587e disabled=true
                                                projected_action_0039 = robot.tool_action(
                                                    action='gripper-close',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=ad1950b8-6518-5f57-8eb2-3c30887ea757 disabled=true
                                                projected_action_0040 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=1ac6cb8d-be80-56e0-a0b2-75bffedd90e5 disabled=true
                                                projected_action_0041 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=96d2929a-bb56-531e-99cb-1883ee6a82ac disabled=true
                                                projected_action_0042 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=4b538dfa-c4ad-587c-ab77-0b5768e08b59 disabled=true
                                                projected_action_0043 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=11ae875b-d413-55b9-971c-50adf719611f disabled=true
                                                projected_action_0044 = robot.tool_action(
                                                    action='quick-change-release',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=c0287f7d-527c-58dc-8eb2-3374d7872fae disabled=true
                                                projected_action_0045 = robot.tool_action(
                                                    action='tool-change-aux-off',
                                                )
                                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/0/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=200eb527-b345-5eee-9b52-757ebb01163a disabled=true
                                                projected_action_0046 = robot.set_mounted_tool(
                                                    tool_id='0',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=73d8dd25-f9a2-57e7-8a40-e91d18bb7df6 disabled=true
                                                projected_action_0047 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=38be327d-df94-5c64-a7a1-53c31fb3d819 disabled=true
                                                projected_action_0048 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                                )
                                            # [BRANCH ELIF 2（互斥分支）] robot_tool_put@body/0/elifs/1/body 的静态审阅分支。
                                            # unilab:node_uuid=b099cced-accb-5826-b172-88ca7b62ae6e
                                            with group(name='ELIF 2（互斥分支）'):
                                                # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=8b718d49-3fad-5fcc-a0d8-233c054fa604 disabled=true
                                                projected_action_0049 = robot.require_anchor(
                                                    point_id='robot-main.home',
                                                )
                                                # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=a2a7a1ad-9ff7-52bc-9a8e-31a8b88414ce disabled=true
                                                projected_action_0050 = rail.ensure(
                                                    Rail_Target_Position=4,
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=c62a7ba7-4208-53b6-a2b4-edaa403e701e disabled=true
                                                projected_action_0051 = robot.tool_action(
                                                    action='gripper-close',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=cdc79e3e-860d-50cb-afa5-337ab8ce593b disabled=true
                                                projected_action_0052 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=b5508c33-4b23-56ae-b396-46c29b8a1cf3 disabled=true
                                                projected_action_0053 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=84a2de0f-0c9d-53ce-a9ad-b26fb2e30660 disabled=true
                                                projected_action_0054 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=f9ca23cc-1e6f-5f09-aaa3-834e415df881 disabled=true
                                                projected_action_0055 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=69e77a37-9d6b-51b9-bbf1-8511c8431afd disabled=true
                                                projected_action_0056 = robot.tool_action(
                                                    action='quick-change-release',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=60e6784a-7a9c-56b2-be02-995fbee59dd3 disabled=true
                                                projected_action_0057 = robot.tool_action(
                                                    action='tool-change-aux-off',
                                                )
                                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/1/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=0f4797a5-a3d0-5fe2-8dad-ce7d95d2f51f disabled=true
                                                projected_action_0058 = robot.set_mounted_tool(
                                                    tool_id='0',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=b29a000b-b680-56b8-83e2-050b3e6b8559 disabled=true
                                                projected_action_0059 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=db702bc3-0f88-54a8-b147-831cb324a6d8 disabled=true
                                                projected_action_0060 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                                )
                                            # [BRANCH ELSE（互斥分支）] robot_tool_put@body/0/else 的静态审阅分支。
                                            # unilab:node_uuid=d1147fa2-0045-5042-b542-c7e936108f34
                                            with group(name='ELSE（互斥分支）'):
                                                # [FLATTENED CONTROL raise] 只读来源校验 robot_tool_put@body/0/else/0；节点在本工作流中静态 disabled。
                                                # unilab:node_uuid=f1c0a8f1-9441-5ddb-b70d-f144b2bb3e06 disabled=true
                                                projected_control_0061 = material.review_control_node_v1(
                                                    operation_name='robot_tool_put',
                                                    node_path='body/0/else/0',
                                                    control_kind='raise',
                                                    expected_sha256='8aa6aa6f749c6777b2a7040e04f4316dd03cc80d36de51eec476b3dbb6c6de75',
                                                )
                                # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/4/else 的静态审阅分支。
                                # unilab:node_uuid=4ed42989-0d47-5bee-beb3-0c3db38a34f7
                                with group(name='ELSE（互斥分支）'):
                                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=40a7fed0-62a5-5558-bfde-c57c07a4040e disabled=true
                                    projected_control_0062 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/4',
                                        control_kind='if',
                                        expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                    )
                            # [SUBWORKFLOW robot_tool_pick] 由 robot_tool_ensure@body/3/then/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                            # unilab:node_uuid=92d6577e-ce04-5035-8328-d041849dc201
                            with group(name='↳ robot_tool_pick'):
                                # [CONTROL if] 来源 robot_tool_pick@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"},{"action":"robot.move...
                                # unilab:node_uuid=19a7d999-1dcf-5696-bf5e-1a49cf3660df
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_tool_pick@body/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=41663cea-f732-5008-892a-99b25285ae42 disabled=true
                                    projected_control_0063 = material.review_control_node_v1(
                                        operation_name='robot_tool_pick',
                                        node_path='body/0',
                                        control_kind='if',
                                        expected_sha256='47a5b48eb2b065101041caadd225ef492b21028bb19039ac3a19991997da1895',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_tool_pick@body/0/then 的静态审阅分支。
                                    # unilab:node_uuid=47e28fa4-250b-5f09-9d0c-c1cc9c2e4b60
                                    with group(name='THEN（互斥分支）'):
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=20dc47d9-5a0e-56ee-a922-11b2f8cb0e08 disabled=true
                                        projected_action_0064 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=50b0048d-e11c-5595-95ad-a28d1ca5ca3f disabled=true
                                        projected_action_0065 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=e5412d0e-491a-5592-8720-3d50c0b06e87 disabled=true
                                        projected_action_0066 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=aff5b593-7bb3-588e-b92f-fd3531a46f26 disabled=true
                                        projected_action_0067 = robot.tool_action(
                                            action='quick-change-lock',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/then/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":1}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=fd2e1cd2-f0ea-5b3e-a84c-8db383cdb59c disabled=true
                                        projected_action_0068 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=0e7b3f67-f8d0-59a7-9bc4-5a3ec29b65e5 disabled=true
                                        projected_action_0069 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=9a652e99-a7de-5f5e-aab4-b810171e4095 disabled=true
                                        projected_action_0070 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=a8ed659d-c9ae-53c1-9aa2-ab0aa484ae20 disabled=true
                                        projected_action_0071 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=1c951e85-62d0-5af9-bcba-1b32be084256 disabled=true
                                        projected_action_0072 = robot.dwell(
                                            duration_ms=500,
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=968ec9d2-bdce-55b4-8318-db6a41f79a92 disabled=true
                                        projected_action_0073 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.home',
                                        )
                                        # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=55b7704a-27a6-5162-8e67-a9e03734a3df disabled=true
                                        projected_action_0074 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                    # [BRANCH ELIF 1（互斥分支）] robot_tool_pick@body/0/elifs/0/body 的静态审阅分支。
                                    # unilab:node_uuid=1442be35-531c-5645-b8a9-02a11cfaa85d
                                    with group(name='ELIF 1（互斥分支）'):
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=c6c0addd-0ef9-50da-a4ad-189d0b76451a disabled=true
                                        projected_action_0075 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=cee86920-6c07-55e7-ba1e-898e096471e1 disabled=true
                                        projected_action_0076 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=2d5ee6fc-c129-5816-8c1e-5259a51f0969 disabled=true
                                        projected_action_0077 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=c86eeb88-8a4c-58a4-b7ea-11cf6517cbf7 disabled=true
                                        projected_action_0078 = robot.tool_action(
                                            action='quick-change-lock',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/0/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":2}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=dfc458db-bf36-5293-a221-8a51ee8aa163 disabled=true
                                        projected_action_0079 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=cdd7359c-f071-5084-b966-c1a5ff6ffee8 disabled=true
                                        projected_action_0080 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=f3cf42d8-6979-5639-bc45-f42a393a1c69 disabled=true
                                        projected_action_0081 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=bb59743c-3e02-5a4d-9899-97c17bbe0c5f disabled=true
                                        projected_action_0082 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/0/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=871399b0-1029-53d1-a114-ea379421d53a disabled=true
                                        projected_action_0083 = robot.dwell(
                                            duration_ms=500,
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=8039eebb-c7b7-56dc-adb4-0d6549bcdf55 disabled=true
                                        projected_action_0084 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.home',
                                        )
                                        # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=ddf097a8-37f3-5b2c-8f8a-916180d5efe0 disabled=true
                                        projected_action_0085 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                    # [BRANCH ELIF 2（互斥分支）] robot_tool_pick@body/0/elifs/1/body 的静态审阅分支。
                                    # unilab:node_uuid=8b00254d-69dd-55c2-961a-064146ffb216
                                    with group(name='ELIF 2（互斥分支）'):
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=7d0c81b9-8fab-57c0-bbc2-06b1a739fc97 disabled=true
                                        projected_action_0086 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=89bf00b1-14e3-5296-beac-34c93095f93e disabled=true
                                        projected_action_0087 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=450d6c9c-b371-5840-a9f3-4b65e7e76499 disabled=true
                                        projected_action_0088 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/1/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=0091de7b-c2e2-5703-87ce-5f3ad4287f53 disabled=true
                                        projected_action_0089 = robot.tool_action(
                                            action='quick-change-lock',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/1/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":3}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=86cd3d56-5cda-5cd9-8000-469f85d92cbc disabled=true
                                        projected_action_0090 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=67a7a67e-d072-5e45-b017-acaee3dc1e1c disabled=true
                                        projected_action_0091 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=fdf4da93-1631-559f-b4e6-2058442af5ed disabled=true
                                        projected_action_0092 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=eae76cc9-c56c-54d7-8f83-25b0d801add6 disabled=true
                                        projected_action_0093 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/1/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=fb50dc09-e8b5-5fe0-946e-ce7157b4d56e disabled=true
                                        projected_action_0094 = robot.dwell(
                                            duration_ms=500,
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=85ad4f69-e975-5c9c-bcce-49a14b5f8eb1 disabled=true
                                        projected_action_0095 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.home',
                                        )
                                        # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=ac015638-6407-5c48-846f-ce24e9be613a disabled=true
                                        projected_action_0096 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                    # [BRANCH ELSE（互斥分支）] robot_tool_pick@body/0/else 的静态审阅分支。
                                    # unilab:node_uuid=dad263b3-87b7-5549-8f6d-d32900368cbc
                                    with group(name='ELSE（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_tool_pick@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"tool.pick: 无效选择值"},"op":"raise"}
                                        # unilab:node_uuid=51db2fa7-4a44-552a-a274-a286cd3e1c93
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_tool_pick@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=0a6a04f3-5d33-5065-9359-49af8bb47a60 disabled=true
                                            projected_control_0097 = material.review_control_node_v1(
                                                operation_name='robot_tool_pick',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='70c2a7e291023e9375102dc659639ba2604e87ffa8a3a94cca033c80b83c21e8',
                                            )
                        # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/else 的静态审阅分支。
                        # unilab:node_uuid=722b7b5e-8f71-57ce-939a-a46304a8b1dd
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=5f7a08ce-18f5-5ea6-bf4b-f7612d483b19 disabled=true
                            projected_control_0098 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3',
                                control_kind='if',
                                expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                            )
                # [CONTROL if] 来源 robot_tank_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"tank_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode"...
                # unilab:node_uuid=50b347e9-f02f-5b2d-bef7-fe1e5b626a92
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_tank_pick@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=7152b538-8968-57eb-a209-ca6faf9eb518 disabled=true
                    projected_control_0099 = material.review_control_node_v1(
                        operation_name='robot_tank_pick',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='123c731101772197874bc2b6b927dfc9ebbf6a503055158d6fc26ec5b18a4692',
                    )
                    # [BRANCH THEN（互斥分支）] robot_tank_pick@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=6479d007-9bb6-5810-9261-bf29b1ccfe10
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=94ee6642-c41c-59a1-a1cc-1f3b3527f36b disabled=true
                        projected_action_0100 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7dadf49a-6dc4-5213-8f29-2894af945868 disabled=true
                        projected_action_0101 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1bf4bfe2-2448-55d0-9c65-7ac0a2b166a9 disabled=true
                        projected_action_0102 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8cad67ef-f0f5-5196-afbe-da2295e493cb disabled=true
                        projected_action_0103 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=44c01cc3-d9c1-5321-96fe-76097a078564 disabled=true
                        projected_action_0104 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1bdae843-4a8c-5a4d-bc7c-42cbcd87f020 disabled=true
                        projected_action_0105 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e7941620-2c3d-5947-bc03-d8366aff4609 disabled=true
                        projected_action_0106 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bb6124ae-0180-5ad5-9cce-4f953c0fffad disabled=true
                        projected_action_0107 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=307dd148-7b0f-58c9-b1c0-97673d04addc disabled=true
                        projected_action_0108 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P11"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f07e75c8-4fb5-5808-bc9c-23f826632edb disabled=true
                        projected_action_0109 = robot.move_to_point(
                            point_id_or_robot_name='P11',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/then/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=275eb899-a53c-5d6a-834e-3572f971b38f disabled=true
                        projected_action_0110 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4a8d334d-e8b9-5311-88d5-7d07ac559276 disabled=true
                        projected_action_0111 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=91fd85ad-e666-5223-8e59-082ae321b98c disabled=true
                        projected_action_0112 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.1.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=705e6f85-22ab-54b1-9faf-f22d55d0e8ec disabled=true
                        projected_action_0113 = robot.move_to_point(
                            point_id_or_robot_name='tank.1.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=96351c33-4632-59df-93c2-4e8ff42179e0 disabled=true
                        projected_action_0114 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6db0d2d3-d243-5eb3-8f20-b92875ef049e disabled=true
                        projected_action_0115 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=53189c36-20bc-57cb-8f83-d8b77ec29d89 disabled=true
                        projected_action_0116 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/then/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e609df85-f611-54c1-b178-f3f601523de3 disabled=true
                        projected_action_0117 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/then/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=626df359-fd42-5b6b-9c4a-a7064cebfbeb disabled=true
                        projected_action_0118 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_tank_pick@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=bffee97b-3e2f-5759-adef-4365a84ce7de
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=889e0e7d-740b-5693-b425-d623e3aa1a41 disabled=true
                        projected_action_0119 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=467da5a2-7a1d-518d-841a-b0a43f8d2680 disabled=true
                        projected_action_0120 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=78f04771-39b9-5b82-966f-7d5ea077899b disabled=true
                        projected_action_0121 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=beceeffa-f072-5fa5-9435-e681ebf4d197 disabled=true
                        projected_action_0122 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=08c8e3de-255e-5b04-a438-72a32f5af277 disabled=true
                        projected_action_0123 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0573723d-582a-5536-97eb-c424d9fbf3f7 disabled=true
                        projected_action_0124 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8c8c9cb8-9b27-5598-9abf-b930cbaffafd disabled=true
                        projected_action_0125 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a3b17539-ffa7-5988-b885-d27b72dae2d1 disabled=true
                        projected_action_0126 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=11f32614-6d7d-58c3-99c3-8dde15bedf9b disabled=true
                        projected_action_0127 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P12"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6f1ae5c9-34fb-53d3-8a76-088a765a6448 disabled=true
                        projected_action_0128 = robot.move_to_point(
                            point_id_or_robot_name='P12',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=25e039bf-42a8-55e4-9033-e9102fa736cd disabled=true
                        projected_action_0129 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=09fe3299-d3eb-5cdd-b22f-ba27d7c2ad11 disabled=true
                        projected_action_0130 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=23f261e0-832a-56a0-b926-ca4e639bd2bf disabled=true
                        projected_action_0131 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.2.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=63e04d1f-c782-5635-89ce-e45f1f2c3dc2 disabled=true
                        projected_action_0132 = robot.move_to_point(
                            point_id_or_robot_name='tank.2.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=353828e3-b233-531b-88ce-f9474dc3014a disabled=true
                        projected_action_0133 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a801559b-e0c1-5931-9edc-5c1d9be21bee disabled=true
                        projected_action_0134 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=828a6975-0e94-5348-93b4-77632f4d25ac disabled=true
                        projected_action_0135 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/0/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4576699f-25ef-5d19-9bbd-bada8c97897e disabled=true
                        projected_action_0136 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/0/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9d09780a-4f73-5db3-b431-b323d6c4fa48 disabled=true
                        projected_action_0137 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 2（互斥分支）] robot_tank_pick@body/3/elifs/1/body 的静态审阅分支。
                    # unilab:node_uuid=182f3285-15f1-5979-b9da-ecd32a2f4d54
                    with group(name='ELIF 2（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8ad765ca-ccfc-5e14-a4c0-59a57fd78ea4 disabled=true
                        projected_action_0138 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=43ed3307-af5a-56e7-9814-a5585d5bcd67 disabled=true
                        projected_action_0139 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e834b4d5-639b-502a-8667-c7aa797eaf7b disabled=true
                        projected_action_0140 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=00fcc763-3929-5ec0-8d1f-59edf22663df disabled=true
                        projected_action_0141 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=945e4674-41d9-59c6-8907-c5dce8658b23 disabled=true
                        projected_action_0142 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6db8abd4-1238-5f8a-b455-4ddd323df920 disabled=true
                        projected_action_0143 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=304424df-18af-5214-9aec-89be0ac3c0dd disabled=true
                        projected_action_0144 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=216b83ed-1da8-58fb-adce-3b973c05552c disabled=true
                        projected_action_0145 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8e31df9e-646d-5df4-b712-00cda6759b15 disabled=true
                        projected_action_0146 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P13"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c458c957-4399-5080-9f75-fbf55416542c disabled=true
                        projected_action_0147 = robot.move_to_point(
                            point_id_or_robot_name='P13',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/1/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1d3191b3-7773-5374-8cce-8a2955038e5a disabled=true
                        projected_action_0148 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a7dc68d0-ea3d-5be1-b801-14d6135e24c9 disabled=true
                        projected_action_0149 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d6bc1263-1408-5ee9-a02a-bf8cacd077ab disabled=true
                        projected_action_0150 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.3.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=28b5f257-7c39-511a-b5ec-246bec27fcc1 disabled=true
                        projected_action_0151 = robot.move_to_point(
                            point_id_or_robot_name='tank.3.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=aa6fe033-0911-5938-bca8-9c39d96e3841 disabled=true
                        projected_action_0152 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=632f9c14-1d79-58d8-884f-4e66968f9830 disabled=true
                        projected_action_0153 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e07f306e-706b-5b60-ae6a-4270a1dca2dd disabled=true
                        projected_action_0154 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/1/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e5fbdd3e-03d7-5baa-9154-cb8c2dc4be36 disabled=true
                        projected_action_0155 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/1/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=84edaed6-8247-59b3-9ad3-9bc946c2164c disabled=true
                        projected_action_0156 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 3（互斥分支）] robot_tank_pick@body/3/elifs/2/body 的静态审阅分支。
                    # unilab:node_uuid=1b5815b4-0934-5fd0-9ac4-9f6be0b1b27a
                    with group(name='ELIF 3（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=03dde196-56a2-5b04-8f3c-7f478768446d disabled=true
                        projected_action_0157 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1cf8d539-363d-5ff2-b24a-2a5e3b12e304 disabled=true
                        projected_action_0158 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/2/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=dd1ffd57-2fdc-5925-ac61-4487b5054125 disabled=true
                        projected_action_0159 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=48668101-33ce-543c-bfe5-5b872edaf322 disabled=true
                        projected_action_0160 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9233c5ce-c77c-54b3-9116-30ba1df4ff3a disabled=true
                        projected_action_0161 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f922c7df-eaa8-5fb0-8afc-4957b4e45cdb disabled=true
                        projected_action_0162 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4cf2c260-3955-557d-8f45-b9e8928cc8f5 disabled=true
                        projected_action_0163 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8225b060-d723-55ec-a102-28dcdf60f756 disabled=true
                        projected_action_0164 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b35764f5-4101-51fd-b35a-5192d67d6a61 disabled=true
                        projected_action_0165 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P14"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=65b3d42c-738e-5e9f-9c00-030c0339c28e disabled=true
                        projected_action_0166 = robot.move_to_point(
                            point_id_or_robot_name='P14',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/2/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3f8e785e-77f0-5e7f-b305-8b996d3db88c disabled=true
                        projected_action_0167 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=96ccdaee-7cd7-571e-b431-0e1cdc99964f disabled=true
                        projected_action_0168 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1ac5263a-aa5e-572b-b59f-402fd3f0a6a4 disabled=true
                        projected_action_0169 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.4.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d98c74fd-f86e-5be3-928d-9a91f60961b8 disabled=true
                        projected_action_0170 = robot.move_to_point(
                            point_id_or_robot_name='tank.4.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P59"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3598cb31-3d6a-5257-bea8-8869d0b2d872 disabled=true
                        projected_action_0171 = robot.move_to_point(
                            point_id_or_robot_name='P59',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/15；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P84"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=17325911-caf6-5fe7-9225-3c877d523899 disabled=true
                        projected_action_0172 = robot.move_to_point(
                            point_id_or_robot_name='P84',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P75"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e9a827d7-4801-5a9e-9df8-15d4b74d94ba disabled=true
                        projected_action_0173 = robot.move_to_point(
                            point_id_or_robot_name='P75',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/2/body/17；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ff036980-e47a-5ca5-bccf-c56b813252db disabled=true
                        projected_action_0174 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/2/body/18；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b9f60421-5996-5cd3-8284-65eb5b6470ab disabled=true
                        projected_action_0175 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 4（互斥分支）] robot_tank_pick@body/3/elifs/3/body 的静态审阅分支。
                    # unilab:node_uuid=5dde0eeb-3024-5fcf-8e7f-64d67e4d9553
                    with group(name='ELIF 4（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9bb299fa-f93b-504e-81d2-b634e7b9f58c disabled=true
                        projected_action_0176 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e3885a9a-1778-5318-9f43-ee40216122ab disabled=true
                        projected_action_0177 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/3/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=763e46e4-bbcd-52b6-a2fd-7ef380d855c2 disabled=true
                        projected_action_0178 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c59ff921-9980-5752-9485-8d9c655934c0 disabled=true
                        projected_action_0179 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f26d3073-1e1b-5c51-8f59-382f3bc3a905 disabled=true
                        projected_action_0180 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5f4aa123-a54a-57e4-b795-ad0342192a9e disabled=true
                        projected_action_0181 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8083584a-0609-53f3-9314-e3306cef0a47 disabled=true
                        projected_action_0182 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P15"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=73514ccc-2989-5b9c-ac27-25527e1e54ce disabled=true
                        projected_action_0183 = robot.move_to_point(
                            point_id_or_robot_name='P15',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/3/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=53e007a7-4d5f-520f-a680-6d969a15bfa6 disabled=true
                        projected_action_0184 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=af818be8-86b0-5356-8a2e-1fcff5414376 disabled=true
                        projected_action_0185 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7f09d50b-9543-5d70-b02b-95ba09b8013c disabled=true
                        projected_action_0186 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.5.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5a8dc534-61cd-55f1-8fde-c39b9ef296c0 disabled=true
                        projected_action_0187 = robot.move_to_point(
                            point_id_or_robot_name='tank.5.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7630f8b2-897b-5119-8166-2f7242d093fc disabled=true
                        projected_action_0188 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/3/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e8c9af6e-1d2b-500e-9759-11553df800c9 disabled=true
                        projected_action_0189 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/3/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7b3aac50-6b59-5a31-ad14-54e22de05f42 disabled=true
                        projected_action_0190 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 5（互斥分支）] robot_tank_pick@body/3/elifs/4/body 的静态审阅分支。
                    # unilab:node_uuid=452403a6-acab-5f6a-aac5-4991ff5149ec
                    with group(name='ELIF 5（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=10db6fcf-cc21-5049-8a88-51c66e25213c disabled=true
                        projected_action_0191 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6950b7a1-26e7-5e02-a7f0-e966f5285a47 disabled=true
                        projected_action_0192 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/4/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=eb6cfadd-94fb-5eff-b7ca-0aef681a8f23 disabled=true
                        projected_action_0193 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6206323c-8b56-595d-93ca-c9eb953d6efd disabled=true
                        projected_action_0194 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=28bbd385-2b2c-5648-bf4d-b790dcb9ea2e disabled=true
                        projected_action_0195 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b634de06-747d-5528-b0e4-fd093c1bc250 disabled=true
                        projected_action_0196 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=29894b37-1c35-5b64-8a42-c336f3b2c125 disabled=true
                        projected_action_0197 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P16"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cbf92178-b0f1-5ac7-b47e-42a7cc9ac20c disabled=true
                        projected_action_0198 = robot.move_to_point(
                            point_id_or_robot_name='P16',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/4/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6838c775-ec8b-5c9f-8468-c176d443a591 disabled=true
                        projected_action_0199 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bfa24068-7af9-50d5-b4b1-9ea53d0d6f06 disabled=true
                        projected_action_0200 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b735b373-35a6-5904-9e63-f55d585ce63e disabled=true
                        projected_action_0201 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.6.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8a22ad8a-dbb5-56d8-8ae3-f604fabb09ef disabled=true
                        projected_action_0202 = robot.move_to_point(
                            point_id_or_robot_name='tank.6.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6535cdf7-63cd-5cc1-ad62-8c38f1e287cc disabled=true
                        projected_action_0203 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/4/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=58d3b110-3473-504b-9b3d-dce34362a353 disabled=true
                        projected_action_0204 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/4/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=29d2cb04-89b5-5b41-a3fe-cedca8e5f055 disabled=true
                        projected_action_0205 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 6（互斥分支）] robot_tank_pick@body/3/elifs/5/body 的静态审阅分支。
                    # unilab:node_uuid=2569fb0d-6cca-52e6-9cde-7fb74cea625b
                    with group(name='ELIF 6（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=52190cef-aa51-5b2b-9603-ce0cbb885345 disabled=true
                        projected_action_0206 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ae89bbff-34bc-5044-a8d7-78bed065d20f disabled=true
                        projected_action_0207 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/5/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=69f0aebc-e3c0-572f-8bf1-76224d6a8658 disabled=true
                        projected_action_0208 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=678bae40-3b82-5d2b-8f0d-b435579aaff0 disabled=true
                        projected_action_0209 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7fbb8fa2-4167-5235-8138-ee97f77c7050 disabled=true
                        projected_action_0210 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e26a2466-ff58-52c9-b8b3-b82cf2f1275b disabled=true
                        projected_action_0211 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=35a3fbb4-1e29-54f6-b261-c652ac5cf154 disabled=true
                        projected_action_0212 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P17"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=db2c7ac8-bda1-546d-8b78-3553ef2910ac disabled=true
                        projected_action_0213 = robot.move_to_point(
                            point_id_or_robot_name='P17',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/5/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7ddcf487-92f6-5794-a815-71d1b0a46e7c disabled=true
                        projected_action_0214 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6ce8c39f-b43e-5968-98c0-17c14dfcfadf disabled=true
                        projected_action_0215 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fd985f8d-b467-599c-b66e-9d4e522c632a disabled=true
                        projected_action_0216 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.7.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cc4a6e57-3719-552b-a091-50a622b1b9f4 disabled=true
                        projected_action_0217 = robot.move_to_point(
                            point_id_or_robot_name='tank.7.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c4a9547d-e34a-5c6c-b2d8-c2b4f2647ef0 disabled=true
                        projected_action_0218 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/5/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=14099525-3aec-5024-8e47-1534dde3354c disabled=true
                        projected_action_0219 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/5/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2b9bd1e9-16b0-508b-951d-2af2636b6ffa disabled=true
                        projected_action_0220 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 7（互斥分支）] robot_tank_pick@body/3/elifs/6/body 的静态审阅分支。
                    # unilab:node_uuid=ac39a7e2-fc90-551e-9225-9016c23d8087
                    with group(name='ELIF 7（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=13c8a840-678a-5051-bbad-f3726d56428e disabled=true
                        projected_action_0221 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_tank_pick@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0659fc1a-ba82-59de-849f-8d7e388b0378 disabled=true
                        projected_action_0222 = rail.ensure(
                            Rail_Target_Position=5,
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/6/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8d55c4f7-0fcf-50d5-943a-2ea0d26611e0 disabled=true
                        projected_action_0223 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4c38c533-a8ea-5808-982f-12ddffe337a0 disabled=true
                        projected_action_0224 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cf856886-f5da-5d59-b1d9-d0d11a8dba95 disabled=true
                        projected_action_0225 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=be02ead2-9bbc-55bb-89ee-12f7b66d9a76 disabled=true
                        projected_action_0226 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3e37e3c1-60ae-5af1-91c3-e1393abf624e disabled=true
                        projected_action_0227 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P18"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=99935d55-bfca-5373-80b6-1df23e46c253 disabled=true
                        projected_action_0228 = robot.move_to_point(
                            point_id_or_robot_name='P18',
                        )
                        # [ACTION robot.tool_action] 来源 robot_tank_pick@body/3/elifs/6/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=01eaa34a-9b2b-5597-96c7-41401876d314 disabled=true
                        projected_action_0229 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ed7cd0db-88f5-5858-87d2-b52863698ffd disabled=true
                        projected_action_0230 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a0181682-26fc-5207-ab63-e35dd244420e disabled=true
                        projected_action_0231 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_mid',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"tank.8.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=697d23eb-dc06-54b9-a429-97548c8d0383 disabled=true
                        projected_action_0232 = robot.move_to_point(
                            point_id_or_robot_name='tank.8.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P3"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e4826a7d-4a5d-55f3-8016-51506a310f23 disabled=true
                        projected_action_0233 = robot.move_to_point(
                            point_id_or_robot_name='P3',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_tank_pick@body/3/elifs/6/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9cd31468-cc12-5017-9b35-55fe682713f4 disabled=true
                        projected_action_0234 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_tank_pick@body/3/elifs/6/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=44fcca4b-7bd7-5c04-9108-1ed7f914d69e disabled=true
                        projected_action_0235 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_tank_pick@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=232b3913-9b7e-5dfc-af55-1d80c428b624
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_tank_pick@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"tank.pick: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=74087585-c6ec-5ab8-b7b8-260abc77b7c0
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_tank_pick@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=10f3ae77-b1cf-5a79-9456-42b67592900c disabled=true
                            projected_control_0236 = material.review_control_node_v1(
                                operation_name='robot_tank_pick',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='32ae16ae681aa5148137c6786f43f7e401bde992d06a0128c8cf67758c6949ee',
                            )
            # [CONTROL comment] 来源 develop_unload@body/6；原节点 {"op":"comment","text":"unload: 板已出缸, 关盖回空缸待机态; 关盖须在 release_tank 之前, 保证 Tank_State 置 0 时缸盖已到动点"}
            # unilab:node_uuid=2fae6098-af3e-5ae9-9393-90f1b2f59174
            with group(name='说明 · unload: 板已出缸, 关盖回空缸待机态; 关盖须在 release_tank 之前, 保证 Tank_St'):
                # [VERIFY comment] 只读来源校验 develop_unload@body/6；节点在本工作流中静态 disabled。
                # unilab:node_uuid=abff558c-4bd6-5bb9-87b9-33e8e5beb747 disabled=true
                projected_control_0237 = material.review_control_node_v1(
                    operation_name='develop_unload',
                    node_path='body/6',
                    control_kind='comment',
                    expected_sha256='91242470a85358aff13b2419163f7ea077795bc8c922645d6634f0d29bad516e',
                )
            # [ACTION develop.plate_extend] 来源 develop_unload@body/7；原节点 {"action":"develop.plate_extend","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=617847e1-ffbc-5347-b72f-8458fcc2faa0 disabled=true
            projected_action_0238 = develop.plate_extend(
                target_tank=1,
            )
            # [CONTROL comment] 来源 develop_unload@body/8；原节点 {"op":"comment","text":"unload: 机器人取板后释放缸资源 Tank_State=0"}
            # unilab:node_uuid=ae4c0cdb-bcc0-5b0b-817b-088438016d6f
            with group(name='说明 · unload: 机器人取板后释放缸资源 Tank_State=0'):
                # [VERIFY comment] 只读来源校验 develop_unload@body/8；节点在本工作流中静态 disabled。
                # unilab:node_uuid=c6cec9b6-e06c-509b-af1d-874ff28b3cc6 disabled=true
                projected_control_0239 = material.review_control_node_v1(
                    operation_name='develop_unload',
                    node_path='body/8',
                    control_kind='comment',
                    expected_sha256='2c2aa0894f821022b11ae6aa9d430edca7a47d8fdf428bee27ca8bc7c29254f8',
                )
            # [ACTION develop.release_tank] 来源 develop_unload@body/9；原节点 {"action":"develop.release_tank","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=adc50ee2-ca9c-53ff-803a-8c2bb599a460 disabled=true
            projected_action_0240 = develop.release_tank(
                target_tank=1,
            )
        # [CONTROL comment] 来源 pf_s8_to_scrape@body/2；原节点 {"op":"comment","text":"放回刮板台: cam_x335 -> 机器人放板 -> locate_cylinder(true); 段末板夹在台上 (稳定停放)"}
        # unilab:node_uuid=c40dfbae-4483-580c-8df9-75d86ecbacc9
        with group(name='说明 · 放回刮板台: cam_x335 -> 机器人放板 -> locate_cylinder(true); 段末板夹在'):
            # [VERIFY comment] 只读来源校验 pf_s8_to_scrape@body/2；节点在本工作流中静态 disabled。
            # unilab:node_uuid=c1f325fe-facf-5484-9b19-e7e0d4a42955 disabled=true
            projected_control_0241 = material.review_control_node_v1(
                operation_name='pf_s8_to_scrape',
                node_path='body/2',
                control_kind='comment',
                expected_sha256='3f6115b9c3a126a5a4cb7af7672d428f781e8af522f4364f9ff65106d9064bd0',
            )
        # [SUBWORKFLOW photoscrape_prepare] 由 pf_s8_to_scrape@body/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=a1019f33-3d10-5981-8f53-aa7dd5a6e920
        with group(name='↳ photoscrape_prepare'):
            # [CONTROL comment] 来源 photoscrape_prepare@body/0；原节点 {"op":"comment","text":"prepare: 工位初始化; 每次受板前复位, 真机验收双访 init 是否需去重"}
            # unilab:node_uuid=10a8562f-1fbf-5b2c-a80d-d37dce3634ef
            with group(name='说明 · prepare: 工位初始化; 每次受板前复位, 真机验收双访 init 是否需去重'):
                # [VERIFY comment] 只读来源校验 photoscrape_prepare@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=dafeae16-30fe-5474-acf0-10c31dea821f disabled=true
                projected_control_0242 = material.review_control_node_v1(
                    operation_name='photoscrape_prepare',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='3a6a45c54d35018d37f1e0c76f494eab38f439747ec068d11e3717c8eccd5bb4',
                )
            # [ACTION photoscrape.init] 来源 photoscrape_prepare@body/1；原节点 {"action":"photoscrape.init","mode":"RUN","op":"call"}
            # unilab:node_uuid=976c542b-9ad4-56c0-8a11-4687e3a0169f disabled=true
            projected_action_0243 = photoscrape.init()
            # [CONTROL comment] 来源 photoscrape_prepare@body/2；原节点 {"op":"comment","text":"prepare: 刮板X到放板位335, 让位机器人放板"}
            # unilab:node_uuid=9e0d2ed1-c3a4-53f6-914f-f6e193923dc9
            with group(name='说明 · prepare: 刮板X到放板位335, 让位机器人放板'):
                # [VERIFY comment] 只读来源校验 photoscrape_prepare@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=b6d6d699-6dae-5e78-b798-ec5e430e2a43 disabled=true
                projected_control_0244 = material.review_control_node_v1(
                    operation_name='photoscrape_prepare',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='c308c06b8cdeb95bb13c30d2e20a936da35461395f6a00075a1f403dc14b2ff5',
                )
            # [ACTION photoscrape.cam_x335] 来源 photoscrape_prepare@body/3；原节点 {"action":"photoscrape.cam_x335","mode":"RUN","op":"call"}
            # unilab:node_uuid=2109b024-92bb-59a0-b12c-babbd87951bf disabled=true
            projected_action_0245 = photoscrape.cam_x335()
        # [SUBWORKFLOW photoscrape_plate_load] 由 pf_s8_to_scrape@body/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=04a59e20-c773-534e-ad3b-aca578d1401d
        with group(name='↳ photoscrape_plate_load'):
            # [CONTROL comment] 来源 photoscrape_plate_load@body/0；原节点 {"op":"comment","text":"plate/load: 机器人已持板; 先安全建立刮板拍照位(位2)地轨窗口"}
            # unilab:node_uuid=38e824a7-9a84-5db0-9564-625762e921c8
            with group(name='说明 · plate/load: 机器人已持板; 先安全建立刮板拍照位(位2)地轨窗口'):
                # [VERIFY comment] 只读来源校验 photoscrape_plate_load@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=061fdd57-650c-5f28-a582-0e6bbb390004 disabled=true
                projected_control_0246 = material.review_control_node_v1(
                    operation_name='photoscrape_plate_load',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='c09130d84bbc0959a4a189ffdb8721d9f926ee10327f2fc574ae06c38494b205',
                )
            # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 photoscrape_plate_load@body/1；节点在本工作流中静态 disabled。
            # unilab:node_uuid=a1334455-7662-5b8c-9b30-e5155f8fc309 disabled=true
            projected_control_0247 = material.review_control_node_v1(
                operation_name='photoscrape_plate_load',
                node_path='body/1',
                control_kind='run_script',
                expected_sha256='3375626c6140464d00aa9cbdffc04532e0598412bbb03a5cdc11186253b17bd1',
            )
            # [CONTROL comment] 来源 photoscrape_plate_load@body/2；原节点 {"op":"comment","text":"plate/load: 机器人放板 持板->刮板"}
            # unilab:node_uuid=99795dda-06ae-51ca-a406-761fcc1acddb
            with group(name='说明 · plate/load: 机器人放板 持板->刮板'):
                # [VERIFY comment] 只读来源校验 photoscrape_plate_load@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=f92449a7-3599-59ff-9891-b17f9e366ce2 disabled=true
                projected_control_0248 = material.review_control_node_v1(
                    operation_name='photoscrape_plate_load',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='1dab2be17eeb939e5f05cdda6abab036c1e8bc8d8abe8d03343004ba23e6ed8b',
                )
            # [SUBWORKFLOW robot_suction_put] 由 photoscrape_plate_load@body/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=bdc8d415-cf43-52ff-a6d5-31da362a868b
            with group(name='↳ robot_suction_put'):
                # [CONTROL comment] 来源 robot_suction_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                # unilab:node_uuid=8c1622a0-4efd-5460-adbd-e05d804420d4
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                    # [VERIFY comment] 只读来源校验 robot_suction_put@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=50d1b0de-c28b-5a0d-bfd3-b16430b33adc disabled=true
                    projected_control_0249 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                    )
                # [ACTION robot.home_ensure] 来源 robot_suction_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=5e6c345a-f1eb-504d-83ba-3e346568c44f disabled=true
                projected_action_0250 = robot.home_ensure()
                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_suction_put@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=a5f47482-a046-5c55-801d-52b35d024293 disabled=true
                projected_control_0251 = material.review_control_node_v1(
                    operation_name='robot_suction_put',
                    node_path='body/2',
                    control_kind='run_script',
                    expected_sha256='6248fd65698183b23b0962f697364ce4f9a7187fdfd05d12bfc8d8f678e645b1',
                )
                # [CONTROL if] 来源 robot_suction_put@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"spotting"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}...
                # unilab:node_uuid=3c989517-c0fe-5504-a462-981aa00a0fa8
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=9751f0d7-8b88-5536-9a2b-aabef29e12c0 disabled=true
                    projected_control_0252 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='c6e01866d4b84eab4021c0d16f3f62c88f5591b3d547740457d335c5752f77cc',
                    )
                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=9607a91b-b057-5915-adcd-d44ccb99b4c9
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=461771b6-27fd-57e4-a6ff-81033f04766b disabled=true
                        projected_action_0253 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d4b047d9-2743-5a20-a92b-8851c04849ba disabled=true
                        projected_action_0254 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=32130723-ffcf-5944-bb13-47c288edb39b disabled=true
                        projected_action_0255 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3c82a3a4-65a7-53e6-beee-fd3a893602e2 disabled=true
                        projected_action_0256 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/4；原节点 {"op":"comment","text":"视觉拍照 photo"}
                        # unilab:node_uuid=8788fad6-c6b4-58c2-bff5-135e26999936
                        with group(name='说明 · 视觉拍照 photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=9d067f56-e38f-568c-94af-088a08e9bf69 disabled=true
                            projected_control_0257 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/4',
                                control_kind='comment',
                                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":30},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c61ffcb8-443a-5f53-9892-f09e8d61e5b8 disabled=true
                        projected_action_0258 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/6；原节点 {"op":"comment","text":"视觉拍照 photo"}
                        # unilab:node_uuid=1d759247-057a-5673-bcaa-ecda3b7cf363
                        with group(name='说明 · 视觉拍照 photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=34badcce-5ef0-5b7b-81a4-6c0a4c3cf0e9 disabled=true
                            projected_control_0259 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/6',
                                control_kind='comment',
                                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
                            )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/7；原节点 {"op":"comment","text":"拍照前整定: 视觉触发路径无内建 settle, 先驻留让机械臂到位后残振衰减再拍 (photo #1)"}
                        # unilab:node_uuid=84b0dd35-9908-576c-ba08-ecb28288f7fb
                        with group(name='说明 · 拍照前整定: 视觉触发路径无内建 settle, 先驻留让机械臂到位后残振衰减再拍 (photo #1)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/7；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=e558741d-10f6-58de-a54f-9d85adc2719a disabled=true
                            projected_control_0260 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/7',
                                control_kind='comment',
                                expected_sha256='6eb397dae264a9b5a09ae3c1405d64b2e9c5a940c36db02de4fccc6dbc9c1bcc',
                            )
                        # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9912ea8b-eb30-5e00-8629-a2d69643dbbc disabled=true
                        projected_action_0261 = robot.dwell(
                            duration_ms=300,
                        )
                        # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/9；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8507943a-d4a9-55bd-acd0-dd26a02b9933 disabled=true
                        projected_action_0262 = vision.capture_plate_offset()
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/10；原节点 {"op":"comment","text":"photo #1 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)"}
                        # unilab:node_uuid=3390f8f8-4eda-584e-beb7-05f363beb372
                        with group(name='说明 · photo #1 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/10；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=b8e8b9be-2f73-5adb-b29c-1f962e3bc83b disabled=true
                            projected_control_0263 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/10',
                                control_kind='comment',
                                expected_sha256='da1eff387eb64169c00489a80c9924bb0712d59bd3a8c496e6bbce7259465c59',
                            )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/11；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_r...
                        # unilab:node_uuid=4a1f71ea-33a3-5394-accf-89096b9cac1c
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=c2a4f407-1de0-5c2e-831f-6fd6a2114993 disabled=true
                            projected_control_0264 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/11',
                                control_kind='if',
                                expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/11/then 的静态审阅分支。
                            # unilab:node_uuid=0b6bd73c-55b2-50f5-a4be-24a4fd571e74
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL human] 来源 robot_suction_put@body/3/then/11/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}}
                                # unilab:node_uuid=bae31ee7-5ceb-5ac8-837f-416472fb6188
                                with group(name='◆ HITL 人工门'):
                                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/11/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=a0ff11ea-1aab-56cc-adba-dbb28b3a8d48 disabled=true
                                    projected_control_0265 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/11/then/0',
                                        control_kind='human',
                                        expected_sha256='8b6554332d59da20e8cd66a97f4e67c5e9471404e4488c74e2aede653f7c5a9d',
                                    )
                                # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/11/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=a3f04042-e367-59e4-b971-dfcb8865df8a disabled=true
                                projected_action_0266 = vision.capture_plate_offset()
                                # [CONTROL if] 来源 robot_suction_put@body/3/then/11/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别仍失败(err=111), 中止放板"},"op":"raise"}]}
                                # unilab:node_uuid=9ed31bbf-1c7e-5f29-90b9-0493d669810b
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=da6d55dc-c7d0-5f23-b479-da6a42e0ebcb disabled=true
                                    projected_control_0267 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/11/then/2',
                                        control_kind='if',
                                        expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/11/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=6be7cf9e-8d9c-5de2-acd4-51b86304dfc9
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_suction_put@body/3/then/11/then/2/then/0；原节点 {"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别仍失败(err=111), 中止放板"},"op":"raise"}
                                        # unilab:node_uuid=77efa640-588c-5f48-9389-2617a6f8b4e1
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/11/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=c854b8ce-2d95-5541-af07-4bf7d2e18049 disabled=true
                                            projected_control_0268 = material.review_control_node_v1(
                                                operation_name='robot_suction_put',
                                                node_path='body/3/then/11/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='be10d3c30d5567c5173255006de750689ae329cb8beab67051668e78cfe857d1',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/11/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=51982f46-3435-5cbc-92a3-96211a614b52
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=d35d8a17-7f42-506a-99c7-7ec3e0380d3c disabled=true
                                        projected_control_0269 = material.review_control_node_v1(
                                            operation_name='robot_suction_put',
                                            node_path='body/3/then/11/then/2',
                                            control_kind='if',
                                            expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                                        )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/11/else 的静态审阅分支。
                            # unilab:node_uuid=2f60b85f-740e-5bf1-a872-fbb70b584853
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=d4806be7-e9be-52d9-b35a-283d82b91bba disabled=true
                                projected_control_0270 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/11',
                                    control_kind='if',
                                    expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                                )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/12；原节点 {"op":"comment","text":"Correction at P86: rotate Rz first so the plate angle matches the template."}
                        # unilab:node_uuid=292d31df-ccfd-591b-8982-f09410e7f8e0
                        with group(name='说明 · Correction at P86: rotate Rz first so the plate angle ma'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/12；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=052361e7-7d71-5afa-97bd-7391933eb654 disabled=true
                            projected_control_0271 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/12',
                                control_kind='comment',
                                expected_sha256='048674f96cc7d9fb228936ecdb955de10db5887d33835cfc6ea532a5508b4f8c',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"lit":0},"dy_mm":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2a81b830-3eb5-50fc-8f0b-f7b3f4ca20ca disabled=true
                        projected_action_0272 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/14；原节点 {"op":"comment","text":"视觉拍照 #2 after Rz correction: verify residual Rz and re-measure current dx/dy."}
                        # unilab:node_uuid=5481e799-6a09-510f-8d80-acf52182550e
                        with group(name='说明 · 视觉拍照 #2 after Rz correction: verify residual Rz and re-m'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/14；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=5e1e2b93-5b9b-5b7d-a39e-17a7f9605d86 disabled=true
                            projected_control_0273 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/14',
                                control_kind='comment',
                                expected_sha256='edde8dc0a1dbbe5d4b7696db96096110c9413ee1e108d8eeaadcc4acca4b40a7',
                            )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/15；原节点 {"op":"comment","text":"拍照前整定: Rz 纠偏 move 到位后先驻留让残振衰减再拍, 提升二次纠偏 dx/dy 读数稳定性 (photo #2)"}
                        # unilab:node_uuid=2f6a2a12-cfe6-5041-940c-5e5ccf7037c0
                        with group(name='说明 · 拍照前整定: Rz 纠偏 move 到位后先驻留让残振衰减再拍, 提升二次纠偏 dx/dy 读数稳定性 (pho'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/15；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=9e4e0838-5a6b-546b-b4da-eed57d38b4a3 disabled=true
                            projected_control_0274 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/15',
                                control_kind='comment',
                                expected_sha256='c80c2f69ad6f5f186109645ffa15fa383576a369addd3d672205333e130a5b58',
                            )
                        # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/16；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c9c4fe5b-9519-5496-ba13-a12af5b85669 disabled=true
                        projected_action_0275 = robot.dwell(
                            duration_ms=300,
                        )
                        # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/17；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ff36fcde-7cb7-55ec-9141-c0dd64f4a3d6 disabled=true
                        projected_action_0276 = vision.capture_plate_offset()
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/18；原节点 {"op":"comment","text":"photo #2 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)"}
                        # unilab:node_uuid=4412664f-e85b-5731-80ea-91b51b0425c0
                        with group(name='说明 · photo #2 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/18；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=1032a1d3-20a7-511b-8520-faee8db26168 disabled=true
                            projected_control_0277 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/18',
                                control_kind='comment',
                                expected_sha256='c883d653edf20b229c98087fef4e0a7a74c71315be24a495a2ab4d63627ddbc7',
                            )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/19；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机二次识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff...
                        # unilab:node_uuid=d3eb51e1-f909-57d1-b037-0d39a17d3342
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=015fec91-52d2-5d76-98c9-1dbb1ab3f3d8 disabled=true
                            projected_control_0278 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/19',
                                control_kind='if',
                                expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/19/then 的静态审阅分支。
                            # unilab:node_uuid=00779e0a-0b26-54eb-bc83-8ad7070e0c32
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL human] 来源 robot_suction_put@body/3/then/19/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机二次识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}}
                                # unilab:node_uuid=25268b76-62cd-5fe1-a152-93edf7a7fe84
                                with group(name='◆ HITL 人工门'):
                                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/19/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=ce6f4365-870c-5564-a5a2-f76999cd4e42 disabled=true
                                    projected_control_0279 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/19/then/0',
                                        control_kind='human',
                                        expected_sha256='cac0a9d59b9391aae093bca3c1049db6e51757d3aae2d1a433addc60e61ea15d',
                                    )
                                # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/19/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=cf7037aa-46c6-515a-aa3a-a8c30a2263b7 disabled=true
                                projected_action_0280 = vision.capture_plate_offset()
                                # [CONTROL if] 来源 robot_suction_put@body/3/then/19/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别重拍仍失败(err=111), 中止放板"},"op":"raise"}]}
                                # unilab:node_uuid=4f806ee3-2552-552c-b4c2-ec4d943e03c4
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=14ecd34a-0bf6-58b9-9509-61558fe7ba63 disabled=true
                                    projected_control_0281 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/19/then/2',
                                        control_kind='if',
                                        expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/19/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=1180132f-8b7f-5428-9063-6c074169f9f4
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_suction_put@body/3/then/19/then/2/then/0；原节点 {"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别重拍仍失败(err=111), 中止放板"},"op":"raise"}
                                        # unilab:node_uuid=21ac0bed-69d1-555c-814c-86fd753262b0
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/19/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=292a78bb-fcb0-5167-9e3c-f6d21964b3ed disabled=true
                                            projected_control_0282 = material.review_control_node_v1(
                                                operation_name='robot_suction_put',
                                                node_path='body/3/then/19/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='6a40626789cfd5679600b1a1b2f6f06f22050fa14f437045f3d9d5dcc6da4252',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/19/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=6bc19806-f559-5d65-88f1-157e2da3bf28
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=61db019b-3020-5281-bdcf-34b910286e69 disabled=true
                                        projected_control_0283 = material.review_control_node_v1(
                                            operation_name='robot_suction_put',
                                            node_path='body/3/then/19/then/2',
                                            control_kind='if',
                                            expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                                        )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/19/else 的静态审阅分支。
                            # unilab:node_uuid=d7895470-7965-5818-9c60-01a94d7c2011
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=957d3149-bb5c-52c8-9858-b5bda470864d disabled=true
                                projected_control_0284 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/19',
                                    control_kind='if',
                                    expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                                )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/20；原节点 {"cond":{"binop":">","left":{"args":[{"field":{"var":"voff_xy"},"name":"drz_deg"}],"call":"abs"},"right":{"var":"drz_threshold_deg"}},"op":"if","then":[{"error":"VISION_RZ_NOT_CONVERGED","message":{"lit":"二次拍照后 Rz 残差仍超阈值, 中止放板"},"op":"raise"}]}
                        # unilab:node_uuid=07f986ad-9b9c-5954-9948-bd96a3c0f608
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/20；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=0a407dc2-1a88-571b-8412-a839fd07f434 disabled=true
                            projected_control_0285 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/20',
                                control_kind='if',
                                expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/20/then 的静态审阅分支。
                            # unilab:node_uuid=c0d83ffe-fd51-5675-921e-1e9101dd664c
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL raise] 来源 robot_suction_put@body/3/then/20/then/0；原节点 {"error":"VISION_RZ_NOT_CONVERGED","message":{"lit":"二次拍照后 Rz 残差仍超阈值, 中止放板"},"op":"raise"}
                                # unilab:node_uuid=b2dca3a1-dbaf-5647-84f4-72226620dfb0
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/20/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=159efb47-289e-51c3-a417-a21cb7f99446 disabled=true
                                    projected_control_0286 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/20/then/0',
                                        control_kind='raise',
                                        expected_sha256='d1a24a4f91395a726e8540c6184463fd49fc2fe218385828e42af6f5c642b12d',
                                    )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/20/else 的静态审阅分支。
                            # unilab:node_uuid=abdf72b0-457f-5544-b853-d2b9bbe582ed
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/20；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=6078e077-f4bf-55c4-a722-5667b741b8ff disabled=true
                                projected_control_0287 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/20',
                                    control_kind='if',
                                    expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                                )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/21；原节点 {"op":"comment","text":"Correction preview at P86: translate XY from photo #2 while keeping the Rz correction from photo #1."}
                        # unilab:node_uuid=2d96a58b-bf4a-5ec4-a27a-7f820dc85926
                        with group(name='说明 · Correction preview at P86: translate XY from photo #2 wh'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/21；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=2e7cfc5e-b1f0-5c58-982b-0798a14288ad disabled=true
                            projected_control_0288 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/21',
                                control_kind='comment',
                                expected_sha256='152da6bbb7e27be6e627d1a263fc9073bba19a63e635f096a9db1c353d46245d',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/22；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode...
                        # unilab:node_uuid=a2d4dd69-307b-50c7-b0ed-bc70b97eec19 disabled=true
                        projected_action_0289 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/23；原节点 {"op":"comment","text":"Final spotting put carries photo"}
                        # unilab:node_uuid=bdd8fa24-86b4-595a-bcb4-9f49ec9a8d2c
                        with group(name='说明 · Final spotting put carries photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/23；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=15902385-03a4-50fa-8131-0a0696ee8faa disabled=true
                            projected_control_0290 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/23',
                                control_kind='comment',
                                expected_sha256='d34a5964054eb7bfa4a11d998941ad9c474d621664cbe44fff1c7a011f963154',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/24；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1fe17688-ae2c-5fd6-85dc-5ee6cb2051da disabled=true
                        projected_action_0291 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/25；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8aabb653-9e89-5ec9-ae52-3fe79f62f8f8 disabled=true
                        projected_action_0292 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/26；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_near"},"...
                        # unilab:node_uuid=bdc507d8-1fcd-5971-9d13-ea574b8db944 disabled=true
                        projected_action_0293 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/27；原节点 {"op":"comment","text":"Release at P19 with closed-loop correction from vision photo"}
                        # unilab:node_uuid=92a79a07-0fc1-5765-830f-aa6b800af1ad
                        with group(name='说明 · Release at P19 with closed-loop correction from vision p'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/27；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=0081ba11-b8f3-5c7d-af8a-faef5aa0e882 disabled=true
                            projected_control_0294 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/27',
                                control_kind='comment',
                                expected_sha256='d16b5d31b63a1b0b0f9c85c8e09a509abf646d4812b6ef38723c29608e0c02bd',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/28；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P19"},"vel":{"lit":5}},"mode":...
                        # unilab:node_uuid=78ad8530-5c11-59d0-a2b0-fda2567993ac disabled=true
                        projected_action_0295 = robot.move_to_point(
                            point_id_or_robot_name='P19',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/29；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=220c9815-a730-551e-a9b6-1442f729f859 disabled=true
                        projected_action_0296 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/30；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_near"},"v...
                        # unilab:node_uuid=c19d81ba-488c-560b-baa4-c50e56451cc9 disabled=true
                        projected_action_0297 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/31；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=701ced84-9013-5bfd-bcd2-5f2a680e413d disabled=true
                        projected_action_0298 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/32；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=beee9ead-43c5-5656-885d-8e5049a19faa disabled=true
                        projected_action_0299 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/33；原节点 {"op":"comment","text":"Safety fix: execute rotary-down only after returning to fixed transition point P4."}
                        # unilab:node_uuid=85e8627c-0bbb-5b41-b17a-3f57cb7716a5
                        with group(name='说明 · Safety fix: execute rotary-down only after returning to '):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/33；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=95cb1e97-fe16-5277-9006-ffb0ff29495d disabled=true
                            projected_control_0300 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/33',
                                control_kind='comment',
                                expected_sha256='8805176604a784f2e55230a1248ed02398b6d66a330667628b5e04cf578d6a79',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/34；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=98c444d0-866b-518b-90ed-7dc27a1d7b2d disabled=true
                        projected_action_0301 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/35；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3c86502b-111a-5dcb-b2c1-c7ec87698211 disabled=true
                        projected_action_0302 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/36；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d742c8aa-f3dc-5d14-b2b4-a765eb4d281c disabled=true
                        projected_action_0303 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_suction_put@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=61bdbcfd-b11b-572a-88dd-5673a4a7adad
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5087844a-9918-568e-b82c-cade6113a06a disabled=true
                        projected_action_0304 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a3118c78-54cd-552b-9bf4-8d7d3e730152 disabled=true
                        projected_action_0305 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=203e6695-e1b2-5078-8f2d-1baf77e11b7e disabled=true
                        projected_action_0306 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=39e5cfa1-3700-5f51-b76c-07762e8e76dc disabled=true
                        projected_action_0307 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/4；原节点 {"op":"comment","text":"No later vision correction after spotting; scrape put uses nominal locator points."}
                        # unilab:node_uuid=4f3792a6-4f86-5be4-9e69-3297557a55e4
                        with group(name='说明 · No later vision correction after spotting; scrape put us'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=7bcda407-20ee-5b8b-b97e-b207184a867d disabled=true
                            projected_control_0308 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/4',
                                control_kind='comment',
                                expected_sha256='72c75af1e4a1520e92d0910d1ec5bb1fbe7428fd161fbc792048931e3b80b01d',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=16029ad6-422f-5509-a0fd-8b3eb9ea8870 disabled=true
                        projected_action_0309 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d207b3d7-98cf-5f62-8cab-aff15251a4d2 disabled=true
                        projected_action_0310 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=da6792cf-4723-5180-86ec-e8b0f2ecda7d disabled=true
                        projected_action_0311 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/8；原节点 {"op":"comment","text":"Release at nominal P65; no later vision correction after spotting."}
                        # unilab:node_uuid=aeae2f60-ea75-5b15-bc84-e787caa64c3e
                        with group(name='说明 · Release at nominal P65; no later vision correction after'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/8；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=1f3f564d-440d-5919-b15a-11ffb0fe0ce8 disabled=true
                            projected_control_0312 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/8',
                                control_kind='comment',
                                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P65"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ba0a880f-350f-5e05-9a25-8a271ef0e5d0 disabled=true
                        projected_action_0313 = robot.move_to_point(
                            point_id_or_robot_name='P65',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2c3ff24e-b171-54e5-b1c8-4f8a8e8ad0fd disabled=true
                        projected_action_0314 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d6bb3849-c873-5adc-904e-3c74f8c08e33 disabled=true
                        projected_action_0315 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=64b9827c-282d-5ae7-8410-b69b5b342ca5 disabled=true
                        projected_action_0316 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7d717526-9fec-560c-b87f-a2044c1a2adc disabled=true
                        projected_action_0317 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/14；原节点 {"op":"comment","text":"Release at nominal P65; no later vision correction after spotting."}
                        # unilab:node_uuid=68130598-eee4-5906-aebd-815ec653411e
                        with group(name='说明 · Release at nominal P65; no later vision correction after'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/14；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=cf100405-ff61-5ac5-bea0-d2bd4cf55f19 disabled=true
                            projected_control_0318 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/14',
                                control_kind='comment',
                                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/15；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ee08b439-297f-5b81-9d7b-349331528e25 disabled=true
                        projected_action_0319 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4f438698-1554-56af-8924-6c737a257359 disabled=true
                        projected_action_0320 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/17；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a6ed1d28-4a0e-507f-ac7d-e9188f9833ff disabled=true
                        projected_action_0321 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 2（互斥分支）] robot_suction_put@body/3/elifs/1/body 的静态审阅分支。
                    # unilab:node_uuid=0f1d9d24-eab0-5ed1-b199-e2125e9b6ebd
                    with group(name='ELIF 2（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=873e9b46-e36e-515c-bd56-ba7f662b12ce disabled=true
                        projected_action_0322 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8f227bbb-720a-5a9a-a09c-eff0c21b4c89 disabled=true
                        projected_action_0323 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5f7ffd25-7fff-55c8-a162-0625a341a563 disabled=true
                        projected_action_0324 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=806cc9ee-550e-575e-ad08-c3c3a2b5c410 disabled=true
                        projected_action_0325 = robot.move_to_point(
                            point_id_or_robot_name='P5',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c4f1b42f-335a-5db3-bc48-a3845ac015c2 disabled=true
                        projected_action_0326 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5ef3c84c-e8a9-5056-ad06-79ab377b3b02 disabled=true
                        projected_action_0327 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P22"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b85ab447-7fc7-593e-a741-39c99d15b583 disabled=true
                        projected_action_0328 = robot.move_to_point(
                            point_id_or_robot_name='P22',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fb26ef36-b275-56b6-a2f7-a4f8e7e9b15c disabled=true
                        projected_action_0329 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cd4b322c-d624-54f3-add4-338e7141fd5b disabled=true
                        projected_action_0330 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=07e8e3ee-8bfc-5037-8d3c-ade057fdb4a5 disabled=true
                        projected_action_0331 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e19a2b7d-94dc-548c-ac76-8c4fa66c516b disabled=true
                        projected_action_0332 = robot.move_to_point(
                            point_id_or_robot_name='P5',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d9d47a05-9315-5da5-87a7-74f212361496 disabled=true
                        projected_action_0333 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=28f08bd9-f878-5364-99a2-d841a4bf18e3 disabled=true
                        projected_action_0334 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=78781818-9ae1-556f-bf11-ef33c4a4b8b5
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_suction_put@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"suction.put: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=d9dfe814-136a-5b13-bbb5-6d23a0a701e7
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6c520c8f-8758-5f2e-b9d7-c75698e04828 disabled=true
                            projected_control_0335 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='7ee4ffd8bc9852082873ab137113eb00aa6df1b10ce72423cb995bbc3e2c295a',
                            )
            # [CONTROL comment] 来源 photoscrape_plate_load@body/4；原节点 {"op":"comment","text":"plate/load: 定位气缸夹紧"}
            # unilab:node_uuid=c524120d-4f94-5695-9b5d-03d51ce39494
            with group(name='说明 · plate/load: 定位气缸夹紧'):
                # [VERIFY comment] 只读来源校验 photoscrape_plate_load@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=bea8d830-8739-5d99-be9a-eb3d7715d969 disabled=true
                projected_control_0336 = material.review_control_node_v1(
                    operation_name='photoscrape_plate_load',
                    node_path='body/4',
                    control_kind='comment',
                    expected_sha256='8b7eee6760b1c33a19c19bb503d44fecd4b4bdb7fa010f633dd57dc94bb5357c',
                )
            # [ACTION photoscrape.locate_cylinder] 来源 photoscrape_plate_load@body/5；原节点 {"action":"photoscrape.locate_cylinder","args":{"clamped":{"lit":true}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=af50ccf7-f42f-585f-b9c4-483b45687d21 disabled=true
            projected_action_0337 = photoscrape.locate_cylinder(
                clamped=True,
            )
    # [EXECUTE ROOT pf_s8_to_scrape] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=8502acbc-a8de-51ac-bd80-7ea1fc89d3f2
    execution = material.run_operation_review_v1(
        operation_name='pf_s8_to_scrape',
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
