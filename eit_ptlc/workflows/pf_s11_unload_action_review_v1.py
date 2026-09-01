from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.plc_feedlift import PLCFeedLift
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

feedlift: PLCFeedLift = device('plc_feedlift')
material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')
vision: VisionProxy = device('vision')


@workflow(
    workflow_uuid='ad5c26a6-4c80-5bec-a6e9-8c77f477abbe',
    displayname='9 废板下料 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s11_unload_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s11_unload] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=fd08f737-f4f7-552c-a5a9-1e3382697c05
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s11_unload@body/0；原节点 {"op":"comment","text":"废板下料: 刮板台取废板 -> feedlift 废料仓掩埋; 换刀回吸盘与地轨回位由子脚本自管"}
        # unilab:node_uuid=41e26f11-7112-525a-9487-4dc94c97ba5e
        with group(name='说明 · 废板下料: 刮板台取废板 -> feedlift 废料仓掩埋; 换刀回吸盘与地轨回位由子脚本自管'):
            # [VERIFY comment] 只读来源校验 pf_s11_unload@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=e658fc24-5aa6-5184-8e92-f310ee0a7ea9 disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s11_unload',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='137362b55c7a05bde19021c754b58065557964ef73582695be98ed5462b5943a',
            )
        # [SUBWORKFLOW photoscrape_unload] 由 pf_s11_unload@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=10d06a1f-e19a-57ec-b6bf-a9de6847f289
        with group(name='↳ photoscrape_unload'):
            # [CONTROL comment] 来源 photoscrape_unload@body/0；原节点 {"op":"comment","text":"unload/板: 若生产 recipe 需要先转走接粉收集器, 应在 execute 与本 step 间执行 collect_load handoff"}
            # unilab:node_uuid=9fe1c0f4-e982-535a-8922-7b64588f3fb4
            with group(name='说明 · unload/板: 若生产 recipe 需要先转走接粉收集器, 应在 execute 与本 step 间执行 '):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=b8836cb7-b756-522e-a497-d48f4827654c disabled=true
                projected_control_0002 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='090f54ab39d61c0f619db3e62dd8567d1c8cd386f721a4cd80841f8b2960a951',
                )
            # [SUBWORKFLOW robot_tool_ensure] 由 photoscrape_unload@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=9fa88f84-819c-5222-b477-4df92da8accf
            with group(name='↳ robot_tool_ensure'):
                # [CONTROL comment] 来源 robot_tool_ensure@body/0；原节点 {"op":"comment","text":"读权威工具态 (mounted_tool 启动已从状态文件恢复","回显在 tool_state.mounted_tool)":null}
                # unilab:node_uuid=0f7568fe-ad1e-59e0-ad66-88290c454224
                with group(name='说明 · 读权威工具态 (mounted_tool 启动已从状态文件恢复'):
                    # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=135bfd2e-9663-5282-872c-a6c9cf074a54 disabled=true
                    projected_control_0003 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='d809e1de31eaaae6a28b91dfdc9f8587e53c48ce272668a1d7794e15c68d86f9',
                    )
                # [ACTION robot.query] 来源 robot_tool_ensure@body/1；原节点 {"action":"robot.query","assign":{"var":"fb"},"mode":"RUN","op":"call"}
                # unilab:node_uuid=b2805dc3-2c1c-53ff-b46d-1427a4906655 disabled=true
                projected_action_0004 = robot.query()
                # [CONTROL assign] 来源 robot_tool_ensure@body/2；原节点 {"op":"assign","target":{"var":"current"},"value":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"mounted_tool"}}
                # unilab:node_uuid=bb63cdd0-3442-5065-8b31-8ee0fb81719b
                with group(name='变量赋值'):
                    # [VERIFY assign] 只读来源校验 robot_tool_ensure@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=415dd790-2129-5f95-93da-c4e2e2c75481 disabled=true
                    projected_control_0005 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/2',
                        control_kind='assign',
                        expected_sha256='0a8bed4ab1ed21eab44aa30c3cdc41f38a8147534c728fa885ef1da0ba3237c7',
                    )
                # [CONTROL if] 来源 robot_tool_ensure@body/3；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"var":"needed"}},"op":"if","then":[{"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"},{"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"},{"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"r...
                # unilab:node_uuid=93831eab-0f2c-5c25-b0ea-b8efe5458f8d
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=6adf5da2-1bc7-5069-af01-f8488d80ad2a disabled=true
                    projected_control_0006 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                    )
                    # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=afcc367b-7a11-5e95-8b9d-9af14d7c4838
                    with group(name='THEN（互斥分支）'):
                        # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/0；原节点 {"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"}
                        # unilab:node_uuid=77a25fc5-5f41-5592-a74e-560c5c435b4f
                        with group(name='说明 · 当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标'):
                            # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=158d5102-61ae-55d9-bbdb-d4093f63f729 disabled=true
                            projected_control_0007 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/0',
                                control_kind='comment',
                                expected_sha256='f1c1621fc9a3af0fead9abddfba4acc6d628c4e07f02d5e1d6e79342f780d4b5',
                            )
                        # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/1；原节点 {"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"}
                        # unilab:node_uuid=df6be8e7-5849-56ab-b7c3-0d1b47a64387
                        with group(name='说明 · 卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止'):
                            # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/1；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=95da23ba-f8a6-56bf-8bca-b387c02a745b disabled=true
                            projected_control_0008 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/1',
                                control_kind='comment',
                                expected_sha256='ab6b298fa1974e89ffba98e42a169ccd9b213ac1a03a6723584be2b1be7e6898',
                            )
                        # [CONTROL if] 来源 robot_tool_ensure@body/3/then/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"right":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"suction_on"}},"op":"if","then":[{"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}]}
                        # unilab:node_uuid=07a36b1d-8d9d-56ae-84c9-043716ff3e51
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=26e055ce-e9a1-5338-9e1a-3d8275a2ed6e disabled=true
                            projected_control_0009 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/2',
                                control_kind='if',
                                expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                            )
                            # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/2/then 的静态审阅分支。
                            # unilab:node_uuid=a0ecfccc-79a4-5e14-bc9f-3f785038c34d
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL raise] 来源 robot_tool_ensure@body/3/then/2/then/0；原节点 {"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}
                                # unilab:node_uuid=4d64163c-47c0-508e-b2f3-221af8e5f4d1
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_tool_ensure@body/3/then/2/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=6fd46d4b-1ead-58b1-9a7d-bd73739b3ed5 disabled=true
                                    projected_control_0010 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/2/then/0',
                                        control_kind='raise',
                                        expected_sha256='8ade635dfc3c21601ac8fa50ba7a168191332f67cbf70e021465f2765df9b23f',
                                    )
                            # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/2/else 的静态审阅分支。
                            # unilab:node_uuid=bd64adc6-680a-5a55-955f-c0dff257f58b
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=89f62b78-6d9b-506f-b1a0-3ee23505dd31 disabled=true
                                projected_control_0011 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/2',
                                    control_kind='if',
                                    expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                )
                        # [SUBWORKFLOW rail_move_safe] 由 robot_tool_ensure@body/3/then/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                        # unilab:node_uuid=e3cbc28a-28a3-5854-878c-619e572ad898
                        with group(name='↳ rail_move_safe'):
                            # [CONTROL comment] 来源 rail_move_safe@body/0；原节点 {"op":"comment","text":"确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)"}
                            # unilab:node_uuid=f39c5fef-b980-58b1-9243-f0fdb2c0c341
                            with group(name='说明 · 确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)'):
                                # [VERIFY comment] 只读来源校验 rail_move_safe@body/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=d192fcf6-ccc1-5964-806b-5c327d59638f disabled=true
                                projected_control_0012 = material.review_control_node_v1(
                                    operation_name='rail_move_safe',
                                    node_path='body/0',
                                    control_kind='comment',
                                    expected_sha256='cc629ec60964ec74a746185851e52069f3b991388ab52755ebea4f3b92ed1740',
                                )
                            # [ACTION robot.home_ensure] 来源 rail_move_safe@body/1；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=ad3110b0-8150-5359-98f2-81432c15cd9b disabled=true
                            projected_action_0013 = robot.home_ensure()
                            # [CONTROL comment] 来源 rail_move_safe@body/2；原节点 {"op":"comment","text":"安全位确认 -> 移动地轨到目标位"}
                            # unilab:node_uuid=1cf93b08-dc6b-598e-99a9-98aa77a12233
                            with group(name='说明 · 安全位确认 -> 移动地轨到目标位'):
                                # [VERIFY comment] 只读来源校验 rail_move_safe@body/2；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=b7cfb074-039b-5129-84ec-33b4eeaed8cd disabled=true
                                projected_control_0014 = material.review_control_node_v1(
                                    operation_name='rail_move_safe',
                                    node_path='body/2',
                                    control_kind='comment',
                                    expected_sha256='38f90a43c3043b67cd1207e8d94cd7c595a01ab69567c39518284d36ecb68702',
                                )
                            # [ACTION rail.move] 来源 rail_move_safe@body/3；原节点 {"action":"rail.move","args":{"Rail_Target_Position":{"var":"target"}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=1bcedfef-03f4-578b-adcc-1166555f639f disabled=true
                            projected_action_0015 = rail.move(
                                Rail_Target_Position=1,
                            )
                        # [CONTROL if] 来源 robot_tool_ensure@body/3/then/4；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"lit":0}},"op":"if","then":[{"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}]}
                        # unilab:node_uuid=8c9b0ab0-3e57-5614-9911-4364142fe3d6
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=84c6c36e-7031-5553-adca-2bf4299160bb disabled=true
                            projected_control_0016 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3/then/4',
                                control_kind='if',
                                expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                            )
                            # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/4/then 的静态审阅分支。
                            # unilab:node_uuid=0e425dce-e379-554e-85ee-52b0500145bf
                            with group(name='THEN（互斥分支）'):
                                # [SUBWORKFLOW robot_tool_put] 由 robot_tool_ensure@body/3/then/4/then/0 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                # unilab:node_uuid=a01bafb8-5036-5194-af9e-eeff399a2264
                                with group(name='↳ robot_tool_put'):
                                    # [CONTROL if] 来源 robot_tool_put@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit...
                                    # unilab:node_uuid=23137e3e-a072-5c01-8fca-00e2d50fdbf7
                                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                                        # [VERIFY if] 只读来源校验 robot_tool_put@body/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=28a86c6a-6357-55af-b239-122312531899 disabled=true
                                        projected_control_0017 = material.review_control_node_v1(
                                            operation_name='robot_tool_put',
                                            node_path='body/0',
                                            control_kind='if',
                                            expected_sha256='9c64b805f035e287559b6a10c2883f201fed2852028900bfd6c9c7526352d298',
                                        )
                                        # [BRANCH THEN（互斥分支）] robot_tool_put@body/0/then 的静态审阅分支。
                                        # unilab:node_uuid=14f7e22e-f780-5d18-8980-8abee3d648bf
                                        with group(name='THEN（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=46bea949-faa8-52ff-8e47-5510650d69c1 disabled=true
                                            projected_action_0018 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=20a8c0c2-6dd5-556c-a8c0-2e4fa4299969 disabled=true
                                            projected_action_0019 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=03b54d5d-f47a-5dd1-a22f-59dabd7d86c9 disabled=true
                                            projected_action_0020 = robot.tool_action(
                                                action='rotary-down',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ddcaaede-6919-575d-9563-c68bb0d1d110 disabled=true
                                            projected_action_0021 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=39af7aae-83a4-5c85-9a67-ccfce1f00f43 disabled=true
                                            projected_action_0022 = robot.tool_action(
                                                action='tool-change-aux-on',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ad2477a1-e061-5316-9055-042ecae69634 disabled=true
                                            projected_action_0023 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c94bce21-9b2a-5980-86c2-cfdecc5c75d2 disabled=true
                                            projected_action_0024 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ec8cccaf-7820-58c3-8a8a-bf0e19f4cabe disabled=true
                                            projected_action_0025 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9e3a044a-c1ee-5594-86ea-8e0a9cccd571 disabled=true
                                            projected_action_0026 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/9；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0342677d-705e-5d7d-bacd-bef819e4ae36 disabled=true
                                            projected_action_0027 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/then/10；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ad69e0f1-ec76-5524-b2c1-5f8296f3d4bf disabled=true
                                            projected_action_0028 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=af01c400-bf58-599f-aab2-b71d3f50cf2e disabled=true
                                            projected_action_0029 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b4166e5f-f62d-5342-b2aa-873d44f11bb2 disabled=true
                                            projected_action_0030 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                        # [BRANCH ELIF 1（互斥分支）] robot_tool_put@body/0/elifs/0/body 的静态审阅分支。
                                        # unilab:node_uuid=10f0d62d-85b4-5d82-8dc8-056115ab724a
                                        with group(name='ELIF 1（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=cb6c773e-4f9c-5d3d-a806-67ec9b68da29 disabled=true
                                            projected_action_0031 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=71e0e54a-7eca-5588-af23-e9524c6bf7dd disabled=true
                                            projected_action_0032 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=63c88b58-f89e-54e2-9826-f52f82b64197 disabled=true
                                            projected_action_0033 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b0695ed1-f9f2-5173-b133-48b5fe16aa64 disabled=true
                                            projected_action_0034 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=bde5090c-05ac-5f88-9f6d-ebdf8f7d7ac1 disabled=true
                                            projected_action_0035 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=09ddfae2-64c5-514a-8897-75ff5253864e disabled=true
                                            projected_action_0036 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2299047f-4ef3-558d-b20a-7e959ca99e8d disabled=true
                                            projected_action_0037 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d0e11ba2-d633-509d-af93-ef898b8afd8f disabled=true
                                            projected_action_0038 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ba7ef3c0-e9cd-587b-ac8a-c819a22ee1c4 disabled=true
                                            projected_action_0039 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/0/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c3c58c95-33a6-5190-97a3-e70ec92f8262 disabled=true
                                            projected_action_0040 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e0942c8b-d215-5670-aead-1f55e438c7ac disabled=true
                                            projected_action_0041 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ad0bb578-3225-5060-b1b2-44eee9e7172f disabled=true
                                            projected_action_0042 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                        # [BRANCH ELIF 2（互斥分支）] robot_tool_put@body/0/elifs/1/body 的静态审阅分支。
                                        # unilab:node_uuid=77066aac-a6ae-5958-a845-a36f892f18e4
                                        with group(name='ELIF 2（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=62ac5575-55a8-5e59-81d5-4fd7758bfa0d disabled=true
                                            projected_action_0043 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2f11526a-69d1-5499-826c-ccf1f49c9e5f disabled=true
                                            projected_action_0044 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8a74b2b6-1ec8-50cd-9a4a-e54fc92c55b0 disabled=true
                                            projected_action_0045 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=394db864-07ef-5e6f-9a4c-1eaac0c1a0c6 disabled=true
                                            projected_action_0046 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9804f537-d968-50fc-82e2-f0212c2b959d disabled=true
                                            projected_action_0047 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2a052396-b18d-5774-977a-7d87efb85cc5 disabled=true
                                            projected_action_0048 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c5835fd8-2812-5385-b07f-e04becd6e98f disabled=true
                                            projected_action_0049 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9e682bed-a437-5a2f-9a63-37f76ac4810b disabled=true
                                            projected_action_0050 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0146d01c-edc5-59ef-9284-166bc162c29e disabled=true
                                            projected_action_0051 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/1/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d584312d-1db4-5ad1-929f-abe4267ab88f disabled=true
                                            projected_action_0052 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=867034fb-184e-5a86-9c53-15752aa6c6d3 disabled=true
                                            projected_action_0053 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=27bc30d6-89a9-5c12-95d5-fa0883787050 disabled=true
                                            projected_action_0054 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                        # [BRANCH ELSE（互斥分支）] robot_tool_put@body/0/else 的静态审阅分支。
                                        # unilab:node_uuid=34f3b495-bec0-5961-a655-bbcfd03cd01d
                                        with group(name='ELSE（互斥分支）'):
                                            # [FLATTENED CONTROL raise] 只读来源校验 robot_tool_put@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=746a74f5-5a0f-5005-97b6-a13c93c84205 disabled=true
                                            projected_control_0055 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='8aa6aa6f749c6777b2a7040e04f4316dd03cc80d36de51eec476b3dbb6c6de75',
                                            )
                            # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/4/else 的静态审阅分支。
                            # unilab:node_uuid=209451ab-4af2-5700-b6eb-6338d8fc0d19
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=c344b5fb-0b98-514a-a082-780e776060cc disabled=true
                                projected_control_0056 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/4',
                                    control_kind='if',
                                    expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                )
                        # [SUBWORKFLOW robot_tool_pick] 由 robot_tool_ensure@body/3/then/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                        # unilab:node_uuid=b779f2c0-55a4-56c1-b424-a72922f85fa0
                        with group(name='↳ robot_tool_pick'):
                            # [CONTROL if] 来源 robot_tool_pick@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"},{"action":"robot.move...
                            # unilab:node_uuid=1aeaaef4-3597-5b10-8f21-e8756b8d26ef
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_tool_pick@body/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=c55fa528-1550-5534-a632-85e2162ab663 disabled=true
                                projected_control_0057 = material.review_control_node_v1(
                                    operation_name='robot_tool_pick',
                                    node_path='body/0',
                                    control_kind='if',
                                    expected_sha256='47a5b48eb2b065101041caadd225ef492b21028bb19039ac3a19991997da1895',
                                )
                                # [BRANCH THEN（互斥分支）] robot_tool_pick@body/0/then 的静态审阅分支。
                                # unilab:node_uuid=39905843-ad68-5078-a02e-b310ba9f7509
                                with group(name='THEN（互斥分支）'):
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=76c75aa4-e2a3-5e06-8673-f9866c1f351c disabled=true
                                    projected_action_0058 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2c2097e6-e553-5858-9edc-3bd9bcc25fc0 disabled=true
                                    projected_action_0059 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=08066fb2-c459-5c6f-9779-8f7fcf69427e disabled=true
                                    projected_action_0060 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0b5466f7-721f-5ada-8404-c1f13b6b2735 disabled=true
                                    projected_action_0061 = robot.tool_action(
                                        action='quick-change-lock',
                                    )
                                    # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/then/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":1}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=4053ad89-e35a-5372-a4d3-405f820b42d5 disabled=true
                                    projected_action_0062 = robot.set_mounted_tool(
                                        tool_id='0',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3ea70bbf-d15f-5954-9516-e34d78631280 disabled=true
                                    projected_action_0063 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=48f980c5-5952-571e-abe4-ffef6b51b38a disabled=true
                                    projected_action_0064 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b624fae0-fe55-5c38-bce2-e0cbb8909979 disabled=true
                                    projected_action_0065 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.ready',
                                    )
                                    # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d6feb0ea-7bb9-5830-b068-a175013f9577 disabled=true
                                    projected_action_0066 = robot.dwell(
                                        duration_ms=500,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2a3038ad-2c81-57ab-a7da-aacf8e4ec0ca disabled=true
                                    projected_action_0067 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.home',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=861ad2da-fd62-54de-8afa-ddb7e01ea116 disabled=true
                                    projected_action_0068 = robot.require_anchor(
                                        point_id='robot-main.home',
                                    )
                                # [BRANCH ELIF 1（互斥分支）] robot_tool_pick@body/0/elifs/0/body 的静态审阅分支。
                                # unilab:node_uuid=a6c5a362-13fa-571d-b9e4-4334ba8451b2
                                with group(name='ELIF 1（互斥分支）'):
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a1a3f9eb-e99d-5492-a0a6-104ea9c6fbec disabled=true
                                    projected_action_0069 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=9d401ace-646b-5d0d-8cbc-2265cd487298 disabled=true
                                    projected_action_0070 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0cf08308-3474-5dfa-9eab-ca83aba5783b disabled=true
                                    projected_action_0071 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=322cca7d-af05-5182-ab93-39694ef576b1 disabled=true
                                    projected_action_0072 = robot.tool_action(
                                        action='quick-change-lock',
                                    )
                                    # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/0/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":2}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d71d67c6-f8a7-57e5-bec4-c3e5c505e417 disabled=true
                                    projected_action_0073 = robot.set_mounted_tool(
                                        tool_id='0',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=9f0a911a-d492-5544-bff8-ac1c37b1da68 disabled=true
                                    projected_action_0074 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e894d12d-f1af-5c34-9379-33f047c40422 disabled=true
                                    projected_action_0075 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e1fe49ba-0f22-5f65-8255-8d79f9bfb5db disabled=true
                                    projected_action_0076 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.ready',
                                    )
                                    # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/0/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b3e1e348-5248-508d-aea9-c7fd20779979 disabled=true
                                    projected_action_0077 = robot.dwell(
                                        duration_ms=500,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d445f679-f8e7-5c15-9476-992248f6a880 disabled=true
                                    projected_action_0078 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.home',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a825bb7a-e419-5bbc-8b54-e34012ec8a73 disabled=true
                                    projected_action_0079 = robot.require_anchor(
                                        point_id='robot-main.home',
                                    )
                                # [BRANCH ELIF 2（互斥分支）] robot_tool_pick@body/0/elifs/1/body 的静态审阅分支。
                                # unilab:node_uuid=d363b7d5-0174-5dec-a38f-fd51540f6aa2
                                with group(name='ELIF 2（互斥分支）'):
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c616f46f-dec5-54b9-a322-8f083f367e3c disabled=true
                                    projected_action_0080 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=70767b32-7b67-5919-8dd6-59620b2162ba disabled=true
                                    projected_action_0081 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f36d76da-200c-5b8b-a4b2-a7c2c4699374 disabled=true
                                    projected_action_0082 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/1/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=535c2500-606f-5b44-9408-6ed055b93b4f disabled=true
                                    projected_action_0083 = robot.tool_action(
                                        action='quick-change-lock',
                                    )
                                    # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/1/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":3}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2754d953-6bdc-5547-806e-1160b4da5d6e disabled=true
                                    projected_action_0084 = robot.set_mounted_tool(
                                        tool_id='0',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=9b7a1f82-7a71-5a83-8981-6ad9eeda79c2 disabled=true
                                    projected_action_0085 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=7d49412d-6986-59fb-8f6a-bff793a27644 disabled=true
                                    projected_action_0086 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=6c7e046d-27b1-5032-81e4-c94d6b8d46b3 disabled=true
                                    projected_action_0087 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.tool-change.ready',
                                    )
                                    # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/1/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=ad1c9c84-2498-501c-9500-34402bceac01 disabled=true
                                    projected_action_0088 = robot.dwell(
                                        duration_ms=500,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0015ab60-eb28-5281-8c96-0d511cc35a71 disabled=true
                                    projected_action_0089 = robot.move_to_point(
                                        point_id_or_robot_name='robot-main.home',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b4c50fbb-2956-51f2-b7a8-6a46c1e6ac5d disabled=true
                                    projected_action_0090 = robot.require_anchor(
                                        point_id='robot-main.home',
                                    )
                                # [BRANCH ELSE（互斥分支）] robot_tool_pick@body/0/else 的静态审阅分支。
                                # unilab:node_uuid=d825aaef-2c81-528c-9fab-2e6039b04f71
                                with group(name='ELSE（互斥分支）'):
                                    # [CONTROL raise] 来源 robot_tool_pick@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"tool.pick: 无效选择值"},"op":"raise"}
                                    # unilab:node_uuid=57baa644-18aa-5d04-80ee-e4b7c7ddcb69
                                    with group(name='抛出流程错误'):
                                        # [VERIFY raise] 只读来源校验 robot_tool_pick@body/0/else/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=cc3a6c39-44bf-5be6-a43c-f1d3b93576e8 disabled=true
                                        projected_control_0091 = material.review_control_node_v1(
                                            operation_name='robot_tool_pick',
                                            node_path='body/0/else/0',
                                            control_kind='raise',
                                            expected_sha256='70c2a7e291023e9375102dc659639ba2604e87ffa8a3a94cca033c80b83c21e8',
                                        )
                    # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=338e73f6-4254-5064-ac19-4490c6af6526
                    with group(name='ELSE（互斥分支）'):
                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=bc09cc74-1564-5fcb-985e-b7b80bef0e7b disabled=true
                        projected_control_0092 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/3',
                            control_kind='if',
                            expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                        )
            # [CONTROL comment] 来源 photoscrape_unload@body/2；原节点 {"op":"comment","text":"unload/板: 换刀可能把地轨带到工具位; 松定位前先安全回到刮板拍照位(位2)"}
            # unilab:node_uuid=762f02cd-2596-5db4-8f1f-e08e04472305
            with group(name='说明 · unload/板: 换刀可能把地轨带到工具位; 松定位前先安全回到刮板拍照位(位2)'):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=8af51340-f74e-515f-b208-36fc58db9ce9 disabled=true
                projected_control_0093 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='f757b741e63ecef01416b43876c84f448fc33fd8263c1eaa57e30a885a8bc2c2',
                )
            # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 photoscrape_unload@body/3；节点在本工作流中静态 disabled。
            # unilab:node_uuid=04adcba8-d2f7-5b02-82d0-537f9fbf4a10 disabled=true
            projected_control_0094 = material.review_control_node_v1(
                operation_name='photoscrape_unload',
                node_path='body/3',
                control_kind='run_script',
                expected_sha256='3375626c6140464d00aa9cbdffc04532e0598412bbb03a5cdc11186253b17bd1',
            )
            # [CONTROL comment] 来源 photoscrape_unload@body/4；原节点 {"op":"comment","text":"unload/板: 先松下压气缸再松定位气缸。press 生产释放点原仅在 collect_load(转走接粉收集器时), 独立/短流程(无 collect 段)会漏放, 板卡在压头下。此处补放 press(false) 幂等——full 流程 collect_load 已放过, 再放无副作用; 保证任何路径下板都不卡压头下, 机器人方可安全取板。"}
            # unilab:node_uuid=ad00e073-6678-56ed-98f2-c2e309c4effd
            with group(name='说明 · unload/板: 先松下压气缸再松定位气缸。press 生产释放点原仅在 collect_load(转走接粉收'):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=5f73794f-ca60-5190-92c8-d605a330add5 disabled=true
                projected_control_0095 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/4',
                    control_kind='comment',
                    expected_sha256='2e88f06e980d94312534dddefa1ec480813bffd17a96170f584aa1ef8e268ad7',
                )
            # [ACTION photoscrape.press_cylinder] 来源 photoscrape_unload@body/5；原节点 {"action":"photoscrape.press_cylinder","args":{"pressed":{"lit":false}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=d34c383b-e6e5-5ab7-9d43-74c1e6c8aeeb disabled=true
            projected_action_0096 = photoscrape.press_cylinder(
                pressed=False,
            )
            # [CONTROL comment] 来源 photoscrape_unload@body/6；原节点 {"op":"comment","text":"unload/板: 松定位气缸"}
            # unilab:node_uuid=00a01b4b-a5e9-5aa9-82ef-f63c8b6c6992
            with group(name='说明 · unload/板: 松定位气缸'):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/6；节点在本工作流中静态 disabled。
                # unilab:node_uuid=f08fc847-82f6-5c2d-97db-3f69d9b9fe73 disabled=true
                projected_control_0097 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/6',
                    control_kind='comment',
                    expected_sha256='24a83be66051ea0aabfd800e906bd880439b5531b0e83a4dc22552f0cf80785f',
                )
            # [ACTION photoscrape.locate_cylinder] 来源 photoscrape_unload@body/7；原节点 {"action":"photoscrape.locate_cylinder","args":{"clamped":{"lit":false}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f0aeb96f-5c4c-566f-a58a-7bf5e8fa1e46 disabled=true
            projected_action_0098 = photoscrape.locate_cylinder(
                clamped=False,
            )
            # [CONTROL comment] 来源 photoscrape_unload@body/8；原节点 {"op":"comment","text":"unload/板: 机器人从刮板夹具取板并持板"}
            # unilab:node_uuid=43b8e55b-c452-51fa-ae72-d4dcb1d7b880
            with group(name='说明 · unload/板: 机器人从刮板夹具取板并持板'):
                # [VERIFY comment] 只读来源校验 photoscrape_unload@body/8；节点在本工作流中静态 disabled。
                # unilab:node_uuid=1c3dac09-a9cf-58ed-8dea-a95379ca7bbd disabled=true
                projected_control_0099 = material.review_control_node_v1(
                    operation_name='photoscrape_unload',
                    node_path='body/8',
                    control_kind='comment',
                    expected_sha256='b1aa2e95cccd55c66d6920ddfbcab498ad85ed79d4e37091bab682a6367a685f',
                )
            # [SUBWORKFLOW robot_suction_pick] 由 photoscrape_unload@body/9 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=fe30dc6d-bff9-5892-9e56-7f15845d7dd1
            with group(name='↳ robot_suction_pick'):
                # [CONTROL comment] 来源 robot_suction_pick@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                # unilab:node_uuid=de8dd61b-0b67-51a6-bf36-b135eecb6e32
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                    # [VERIFY comment] 只读来源校验 robot_suction_pick@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=b28e5c71-989b-5fa1-86ff-7e6a4a781264 disabled=true
                    projected_control_0100 = material.review_control_node_v1(
                        operation_name='robot_suction_pick',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                    )
                # [ACTION robot.home_ensure] 来源 robot_suction_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=d74eba78-c674-552b-ac0a-b40252b1ca97 disabled=true
                projected_action_0101 = robot.home_ensure()
                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_suction_pick@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=9fdf9d8b-121f-5697-8e9c-7eb25839ff64 disabled=true
                projected_control_0102 = material.review_control_node_v1(
                    operation_name='robot_suction_pick',
                    node_path='body/2',
                    control_kind='run_script',
                    expected_sha256='6248fd65698183b23b0962f697364ce4f9a7187fdfd05d12bfc8d8f678e645b1',
                )
                # [CONTROL if] 来源 robot_suction_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"spotting"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"...
                # unilab:node_uuid=5a6e92b7-be6b-51d4-b4c3-7723db1ef7cf
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_suction_pick@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=af10fa95-3f6f-5a09-b080-cd8db146b985 disabled=true
                    projected_control_0103 = material.review_control_node_v1(
                        operation_name='robot_suction_pick',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='7cf59bced5f5b2dcd49557f999dbd90eb52637f34cb412ab2176135f0e83d084',
                    )
                    # [BRANCH THEN（互斥分支）] robot_suction_pick@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=4cecb6da-d89b-5e7e-b205-49a4aa897f55
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5821ffa9-c9a9-5518-8004-d2d88e8c3164 disabled=true
                        projected_action_0104 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ec1106f7-9940-5cf7-90fa-7ea58712c9ba disabled=true
                        projected_action_0105 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f039c13e-9ae8-58fc-8f99-a090e737a93e disabled=true
                        projected_action_0106 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e4dbec2a-294b-59b9-846c-8d7d1dff6e04 disabled=true
                        projected_action_0107 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f34d9523-0e66-5bcc-9220-00706d512975 disabled=true
                        projected_action_0108 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8cfc4cf1-e16e-55da-98da-c1646f38f5e5 disabled=true
                        projected_action_0109 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P19"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3d1119a0-d803-50b6-a713-602510db349f disabled=true
                        projected_action_0110 = robot.move_to_point(
                            point_id_or_robot_name='P19',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3157890d-4705-5ef1-9447-9824820e22ef disabled=true
                        projected_action_0111 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=05d47e50-0dbb-5919-a0ca-3581606a7339 disabled=true
                        projected_action_0112 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.pick.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=52de0e8a-7d24-5de4-b45b-005077b82178 disabled=true
                        projected_action_0113 = robot.move_to_point(
                            point_id_or_robot_name='spotting.pick.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b11215f3-b4a4-5021-ae29-2643ee6654ed disabled=true
                        projected_action_0114 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=56bd20ae-6345-5f68-ada2-4aa450d79159 disabled=true
                        projected_action_0115 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/then/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0da0c6d9-49d7-5942-bb8b-809b77bb1620 disabled=true
                        projected_action_0116 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_suction_pick@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=e2e178ad-d70d-52b8-801c-aaa21baff100
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4d0290a4-085f-5389-91fd-db36fabf19eb disabled=true
                        projected_action_0117 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e00313dd-0548-5009-bbed-d1a5e1861bc4 disabled=true
                        projected_action_0118 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b20b5fc1-4ea3-50ed-a8db-a42e21ff8299 disabled=true
                        projected_action_0119 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6a0f2473-5fbf-55b0-9117-1b469fb2673c disabled=true
                        projected_action_0120 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e78d5ab4-1d7a-5ef8-9e43-f159f970ae15 disabled=true
                        projected_action_0121 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=660db8fa-c850-5d72-9d3c-fe7972c0c18e disabled=true
                        projected_action_0122 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_pick@body/3/elifs/0/body/6；原节点 {"op":"comment","text":"刮板位取/放同基点: 取板与放板同点 P65 (吸附基准=板中心); P64 弃用保留在点表, 勿再引用"}
                        # unilab:node_uuid=0267e249-af1d-5739-820d-5561ddee6333
                        with group(name='说明 · 刮板位取/放同基点: 取板与放板同点 P65 (吸附基准=板中心); P64 弃用保留在点表, 勿再引用'):
                            # [VERIFY comment] 只读来源校验 robot_suction_pick@body/3/elifs/0/body/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=aeee17ac-e0d4-5778-926e-5187a6c834ae disabled=true
                            projected_control_0123 = material.review_control_node_v1(
                                operation_name='robot_suction_pick',
                                node_path='body/3/elifs/0/body/6',
                                control_kind='comment',
                                expected_sha256='ce61ff1eddd64c4a26507b7df53f7a45d978ed30161b8ea6895afc3afcafc7bc',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P65"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=70f9f5dc-be2e-5d62-bcbc-29cb0b47871b disabled=true
                        projected_action_0124 = robot.move_to_point(
                            point_id_or_robot_name='P65',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=600ff25e-0d46-5d1b-a640-375e0287802f disabled=true
                        projected_action_0125 = robot.tool_action(
                            action='suction-on',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9017806a-04a0-5d33-9d05-e6a48744723e disabled=true
                        projected_action_0126 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-pick.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=06bd9a86-2d3f-5695-8901-4f1bd3e6656c disabled=true
                        projected_action_0127 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-pick.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a158ae4d-b10f-58d2-ada3-fcea2f9ca933 disabled=true
                        projected_action_0128 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [CONTROL comment] 来源 robot_suction_pick@body/3/elifs/0/body/12；原节点 {"op":"comment","text":"Safety fix: after scraping pick, confirm rotary-up only after retreating to P63."}
                        # unilab:node_uuid=63dad4e9-4346-5373-aed0-7f65d046a9dd
                        with group(name='说明 · Safety fix: after scraping pick, confirm rotary-up only '):
                            # [VERIFY comment] 只读来源校验 robot_suction_pick@body/3/elifs/0/body/12；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=4807f97e-4e5e-5169-b40e-6590f4575b57 disabled=true
                            projected_control_0129 = material.review_control_node_v1(
                                operation_name='robot_suction_pick',
                                node_path='body/3/elifs/0/body/12',
                                control_kind='comment',
                                expected_sha256='0c6391714e618a81ff71411339cb422212bba6d05a807e18d569fcabaea39c2f',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cbe2b419-1c85-5636-b25d-8785ea58da63 disabled=true
                        projected_action_0130 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0e5f0608-a2cb-5d2a-98b5-eaace6922b51 disabled=true
                        projected_action_0131 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_pick@body/3/elifs/0/body/15；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9601ce89-997b-56a5-88ac-05e6ad204f18 disabled=true
                        projected_action_0132 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_suction_pick@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=fc945616-0a92-5855-8e48-4632ec4b95df
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_suction_pick@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"suction.pick: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=f89998c9-3115-5d3b-8e61-0356fb8e72c4
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_suction_pick@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=e61fc943-f88a-5415-9ad3-c87479326459 disabled=true
                            projected_control_0133 = material.review_control_node_v1(
                                operation_name='robot_suction_pick',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='7324ece78b8e478b8be13e31abd1d3bdbbc53d99d674cd9200fe986e9b80917f',
                            )
        # [SUBWORKFLOW feedlift_unload_cycle] 由 pf_s11_unload@body/2 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=a749f847-5c82-58e0-83d6-73f023726596
        with group(name='↳ feedlift_unload_cycle'):
            # [CONTROL comment] 来源 feedlift_unload_cycle@body/0；原节点 {"op":"comment","text":"[phase: prepare] 先换刀再移轨: 换刀需要动作时会自己把地轨开到工具站(位4)且不还原, 排在移轨之后会让位1那趟白跑 (168->500->168)"}
            # unilab:node_uuid=f67f002a-c829-53a7-af74-9a8017f45a3f
            with group(name='说明 · [phase: prepare] 先换刀再移轨: 换刀需要动作时会自己把地轨开到工具站(位4)且不还原, 排在移'):
                # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=8a3063e1-1928-5659-a389-847e8767bea8 disabled=true
                projected_control_0134 = material.review_control_node_v1(
                    operation_name='feedlift_unload_cycle',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='4acdb1112605ade896676c495c39f230fcf686d851254f44bea07c3fa95fb594',
                )
            # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 feedlift_unload_cycle@body/1；节点在本工作流中静态 disabled。
            # unilab:node_uuid=9186b430-c6af-5b76-895b-73c18bc10422 disabled=true
            projected_control_0135 = material.review_control_node_v1(
                operation_name='feedlift_unload_cycle',
                node_path='body/1',
                control_kind='run_script',
                expected_sha256='6248fd65698183b23b0962f697364ce4f9a7187fdfd05d12bfc8d8f678e645b1',
            )
            # [CONTROL comment] 来源 feedlift_unload_cycle@body/2；原节点 {"op":"comment","text":"[phase: prepare] 确定地轨在废料下料站(位1≡位2); 不在则先安全移轨(先校验机械臂在 P1 安全位再移)"}
            # unilab:node_uuid=9c300a10-274c-5dd6-a8c7-ccc312a62316
            with group(name='说明 · [phase: prepare] 确定地轨在废料下料站(位1≡位2); 不在则先安全移轨(先校验机械臂在 P1 '):
                # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=f73001be-c6c9-5db8-b80f-f44b0d8a0312 disabled=true
                projected_control_0136 = material.review_control_node_v1(
                    operation_name='feedlift_unload_cycle',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='2e6b1f7c6a64f2d4cf2d36e3d93ac046825a6491b280709c346f5686410c2c60',
                )
            # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 feedlift_unload_cycle@body/3；节点在本工作流中静态 disabled。
            # unilab:node_uuid=0adf2b89-58c6-5a9d-ad97-5c1a350bdbe0 disabled=true
            projected_control_0137 = material.review_control_node_v1(
                operation_name='feedlift_unload_cycle',
                node_path='body/3',
                control_kind='run_script',
                expected_sha256='d080707abdd7c69af97667b5d59dc29bdabff48485e22748770f2475b550a8ba',
            )
            # [CONTROL comment] 来源 feedlift_unload_cycle@body/4；原节点 {"op":"comment","text":"[phase: load] 先降轴至光电消失(清零)再升轴到放废料位 —— 探测前必须清零, 见下方说明"}
            # unilab:node_uuid=ea233198-6c8e-5a7b-8ad9-9d1ec51bc461
            with group(name='说明 · [phase: load] 先降轴至光电消失(清零)再升轴到放废料位 —— 探测前必须清零, 见下方说明'):
                # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=faad1885-243e-5440-9c21-32274451a9d5 disabled=true
                projected_control_0138 = material.review_control_node_v1(
                    operation_name='feedlift_unload_cycle',
                    node_path='body/4',
                    control_kind='comment',
                    expected_sha256='4f6753b67557cc01c9619e683c57a9b98f2a7011da9cb7f47d11cc15956eb4ee',
                )
            # [ACTION feedlift.unload_bury] 来源 feedlift_unload_cycle@body/5；原节点 {"action":"feedlift.unload_bury","mode":"RUN","op":"call"}
            # unilab:node_uuid=6cef3695-cf9c-5234-8dda-0a4845e463da disabled=true
            projected_action_0139 = feedlift.unload_bury()
            # [ACTION feedlift.unload_ready] 来源 feedlift_unload_cycle@body/6；原节点 {"action":"feedlift.unload_ready","mode":"RUN","op":"call"}
            # unilab:node_uuid=cb3d40f7-6650-51ea-988f-ac527ecfc072 disabled=true
            projected_action_0140 = feedlift.unload_ready()
            # [ACTION feedlift.probe_stack] 来源 feedlift_unload_cycle@body/7；原节点 {"action":"feedlift.probe_stack","args":{"magazine":{"lit":"waste"},"reconcile":{"lit":true}},"assign":{"var":"p0"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5563740b-484a-532f-9142-39882397767d disabled=true
            projected_action_0141 = feedlift.probe_stack(
                magazine='waste',
            )
            # [CONTROL comment] 来源 feedlift_unload_cycle@body/8；原节点 {"op":"comment","text":"[phase: execute] 机器人放废板 (降 P22->suction-off 松料->退回 P1)"}
            # unilab:node_uuid=6b1cf77e-9382-57ba-a4c2-62521fe6bd68
            with group(name='说明 · [phase: execute] 机器人放废板 (降 P22->suction-off 松料->退回 P1)'):
                # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/8；节点在本工作流中静态 disabled。
                # unilab:node_uuid=83397330-a847-57d0-a073-a6f3d8704ef0 disabled=true
                projected_control_0142 = material.review_control_node_v1(
                    operation_name='feedlift_unload_cycle',
                    node_path='body/8',
                    control_kind='comment',
                    expected_sha256='05014a4407e0e05ef15644da15deb4c94400e723939d966709938d930c42971d',
                )
            # [SUBWORKFLOW robot_suction_put] 由 feedlift_unload_cycle@body/9 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=07c2b8be-b3a5-5ec8-9d60-e6b72ba95bb2
            with group(name='↳ robot_suction_put'):
                # [CONTROL comment] 来源 robot_suction_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                # unilab:node_uuid=4e0fc549-2cbf-58f7-b9dd-683e0c6b2621
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                    # [VERIFY comment] 只读来源校验 robot_suction_put@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=8ed04d46-d973-5b8a-bd12-620cf5619961 disabled=true
                    projected_control_0143 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                    )
                # [ACTION robot.home_ensure] 来源 robot_suction_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=9b903ee7-eb81-5e68-9f89-a6ff9103eb41 disabled=true
                projected_action_0144 = robot.home_ensure()
                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_suction_put@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=4bbc36a5-be3d-53d6-ac64-b1bf5c1c6634 disabled=true
                projected_control_0145 = material.review_control_node_v1(
                    operation_name='robot_suction_put',
                    node_path='body/2',
                    control_kind='run_script',
                    expected_sha256='6248fd65698183b23b0962f697364ce4f9a7187fdfd05d12bfc8d8f678e645b1',
                )
                # [CONTROL if] 来源 robot_suction_put@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"spotting"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}...
                # unilab:node_uuid=fa083b7b-b2f4-5761-a2cf-38571c52bd14
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=deca7aed-8eae-5b0a-b99c-d37ec7d712b8 disabled=true
                    projected_control_0146 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='c6e01866d4b84eab4021c0d16f3f62c88f5591b3d547740457d335c5752f77cc',
                    )
                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=854e7344-731e-5301-9293-497f49934afb
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1564fc39-38f7-58bf-a83f-0c72d4f7fe3a disabled=true
                        projected_action_0147 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a1f0f6d5-82f6-52fa-8597-d7d54340360b disabled=true
                        projected_action_0148 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=52b322a9-d41b-51cc-a053-9e5684e89e73 disabled=true
                        projected_action_0149 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=65724b89-57b2-5b81-9716-a8e8a309b70f disabled=true
                        projected_action_0150 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/4；原节点 {"op":"comment","text":"视觉拍照 photo"}
                        # unilab:node_uuid=6d175bad-0da8-5688-9e4f-fa342d74c724
                        with group(name='说明 · 视觉拍照 photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=cdb32462-896e-5956-bdff-c67a6de7474c disabled=true
                            projected_control_0151 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/4',
                                control_kind='comment',
                                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":30},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=dfca249a-98b1-5b41-b498-4e6f161124cb disabled=true
                        projected_action_0152 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/6；原节点 {"op":"comment","text":"视觉拍照 photo"}
                        # unilab:node_uuid=ae8d448b-219f-5bce-925a-c46e05d2a660
                        with group(name='说明 · 视觉拍照 photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=e42d5f9a-95e1-5678-82a7-80cb7753d12a disabled=true
                            projected_control_0153 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/6',
                                control_kind='comment',
                                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
                            )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/7；原节点 {"op":"comment","text":"拍照前整定: 视觉触发路径无内建 settle, 先驻留让机械臂到位后残振衰减再拍 (photo #1)"}
                        # unilab:node_uuid=e8ba1f66-4abe-521e-a0bb-415321cab32f
                        with group(name='说明 · 拍照前整定: 视觉触发路径无内建 settle, 先驻留让机械臂到位后残振衰减再拍 (photo #1)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/7；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=b852809d-e34c-5e5c-9f29-28bade589cc8 disabled=true
                            projected_control_0154 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/7',
                                control_kind='comment',
                                expected_sha256='6eb397dae264a9b5a09ae3c1405d64b2e9c5a940c36db02de4fccc6dbc9c1bcc',
                            )
                        # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b3fbc74c-1eda-5cfc-be8d-07191acc59b3 disabled=true
                        projected_action_0155 = robot.dwell(
                            duration_ms=300,
                        )
                        # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/9；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cd083219-4400-5792-a260-c9b4ff68e0f3 disabled=true
                        projected_action_0156 = vision.capture_plate_offset()
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/10；原节点 {"op":"comment","text":"photo #1 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)"}
                        # unilab:node_uuid=551aa100-f7be-5a88-9ba0-00f109563859
                        with group(name='说明 · photo #1 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/10；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=cbf047a1-f6b6-500a-94d1-4e3e830c0e08 disabled=true
                            projected_control_0157 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/10',
                                control_kind='comment',
                                expected_sha256='da1eff387eb64169c00489a80c9924bb0712d59bd3a8c496e6bbce7259465c59',
                            )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/11；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_r...
                        # unilab:node_uuid=6a9a9188-34d4-5616-9cb0-56a264a429b4
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6bf57981-ddd0-5118-9ab5-486c154b8abb disabled=true
                            projected_control_0158 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/11',
                                control_kind='if',
                                expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/11/then 的静态审阅分支。
                            # unilab:node_uuid=8f3c3127-0a6a-5d25-a5dd-8ef4fb6a3c88
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL human] 来源 robot_suction_put@body/3/then/11/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}}
                                # unilab:node_uuid=d06fc50c-67c9-53b2-aeed-a0f2245a6b39
                                with group(name='◆ HITL 人工门'):
                                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/11/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=916fad2b-18ee-581b-ac76-86bf017abc8f disabled=true
                                    projected_control_0159 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/11/then/0',
                                        control_kind='human',
                                        expected_sha256='8b6554332d59da20e8cd66a97f4e67c5e9471404e4488c74e2aede653f7c5a9d',
                                    )
                                # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/11/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=8c99548a-1b96-5d49-b60c-f4d927210bf4 disabled=true
                                projected_action_0160 = vision.capture_plate_offset()
                                # [CONTROL if] 来源 robot_suction_put@body/3/then/11/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别仍失败(err=111), 中止放板"},"op":"raise"}]}
                                # unilab:node_uuid=c695c8fa-4007-5577-97c9-3a534ab9333f
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=699786ad-fe87-5337-be6c-6c2c6344f583 disabled=true
                                    projected_control_0161 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/11/then/2',
                                        control_kind='if',
                                        expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/11/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=7ddcae71-3e8b-5828-bcee-811b2491388c
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_suction_put@body/3/then/11/then/2/then/0；原节点 {"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别仍失败(err=111), 中止放板"},"op":"raise"}
                                        # unilab:node_uuid=67cf4eec-203f-5950-8297-9713bdf0075e
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/11/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=e76a6470-d505-5a21-8203-8fd958464748 disabled=true
                                            projected_control_0162 = material.review_control_node_v1(
                                                operation_name='robot_suction_put',
                                                node_path='body/3/then/11/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='be10d3c30d5567c5173255006de750689ae329cb8beab67051668e78cfe857d1',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/11/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=315cf905-fec7-555b-88c7-8e6a89b2c48c
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=81e192ba-f2fb-52bb-b916-8ac9bc76f03e disabled=true
                                        projected_control_0163 = material.review_control_node_v1(
                                            operation_name='robot_suction_put',
                                            node_path='body/3/then/11/then/2',
                                            control_kind='if',
                                            expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                                        )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/11/else 的静态审阅分支。
                            # unilab:node_uuid=3e0ff95f-e9dd-5cfe-9511-b6ba913779e3
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=f050806f-7b98-5886-ad43-1697f88bb109 disabled=true
                                projected_control_0164 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/11',
                                    control_kind='if',
                                    expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                                )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/12；原节点 {"op":"comment","text":"Correction at P86: rotate Rz first so the plate angle matches the template."}
                        # unilab:node_uuid=679c430d-61f5-5a57-9b35-d551ec5a213b
                        with group(name='说明 · Correction at P86: rotate Rz first so the plate angle ma'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/12；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=de4a1075-971d-52c0-8b4d-01658c36be41 disabled=true
                            projected_control_0165 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/12',
                                control_kind='comment',
                                expected_sha256='048674f96cc7d9fb228936ecdb955de10db5887d33835cfc6ea532a5508b4f8c',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"lit":0},"dy_mm":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fe7befc5-ee74-59c4-97e5-b40543d94504 disabled=true
                        projected_action_0166 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/14；原节点 {"op":"comment","text":"视觉拍照 #2 after Rz correction: verify residual Rz and re-measure current dx/dy."}
                        # unilab:node_uuid=4f719bc1-e3cd-5c0b-8397-e4c9933f799b
                        with group(name='说明 · 视觉拍照 #2 after Rz correction: verify residual Rz and re-m'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/14；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=a9368fe9-9bc0-59c6-843f-2cb5dc2c343c disabled=true
                            projected_control_0167 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/14',
                                control_kind='comment',
                                expected_sha256='edde8dc0a1dbbe5d4b7696db96096110c9413ee1e108d8eeaadcc4acca4b40a7',
                            )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/15；原节点 {"op":"comment","text":"拍照前整定: Rz 纠偏 move 到位后先驻留让残振衰减再拍, 提升二次纠偏 dx/dy 读数稳定性 (photo #2)"}
                        # unilab:node_uuid=69422b6f-56cf-5c0f-b266-6f58f8e677a3
                        with group(name='说明 · 拍照前整定: Rz 纠偏 move 到位后先驻留让残振衰减再拍, 提升二次纠偏 dx/dy 读数稳定性 (pho'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/15；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6b207375-5369-5d5b-aca8-5fbd6899f666 disabled=true
                            projected_control_0168 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/15',
                                control_kind='comment',
                                expected_sha256='c80c2f69ad6f5f186109645ffa15fa383576a369addd3d672205333e130a5b58',
                            )
                        # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/16；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=324b13de-d0c3-5af6-964c-f22c32df6a89 disabled=true
                        projected_action_0169 = robot.dwell(
                            duration_ms=300,
                        )
                        # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/17；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c7ac7c25-38f6-5138-a09e-6f2659d9bbf9 disabled=true
                        projected_action_0170 = vision.capture_plate_offset()
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/18；原节点 {"op":"comment","text":"photo #2 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)"}
                        # unilab:node_uuid=b01bd355-b3dd-54f0-a059-0c00eb07637d
                        with group(name='说明 · photo #2 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/18；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=94ffe57d-dd36-5b93-ba32-a0e77121c7db disabled=true
                            projected_control_0171 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/18',
                                control_kind='comment',
                                expected_sha256='c883d653edf20b229c98087fef4e0a7a74c71315be24a495a2ab4d63627ddbc7',
                            )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/19；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机二次识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff...
                        # unilab:node_uuid=3cbeb927-b77d-5f3f-a163-e51101000616
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=ef3840cb-03ad-505d-a71f-6a888538dbbf disabled=true
                            projected_control_0172 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/19',
                                control_kind='if',
                                expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/19/then 的静态审阅分支。
                            # unilab:node_uuid=ddb2fae6-c5b9-5d04-a21a-6bc079bed838
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL human] 来源 robot_suction_put@body/3/then/19/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机二次识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}}
                                # unilab:node_uuid=8adc29b0-5ce9-5942-98fd-45823b19429b
                                with group(name='◆ HITL 人工门'):
                                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/19/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=8c3dd92f-0df9-5131-8065-634eb2d2e2eb disabled=true
                                    projected_control_0173 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/19/then/0',
                                        control_kind='human',
                                        expected_sha256='cac0a9d59b9391aae093bca3c1049db6e51757d3aae2d1a433addc60e61ea15d',
                                    )
                                # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/19/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4000ffe2-c772-568f-8404-f7230a2d5ec6 disabled=true
                                projected_action_0174 = vision.capture_plate_offset()
                                # [CONTROL if] 来源 robot_suction_put@body/3/then/19/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别重拍仍失败(err=111), 中止放板"},"op":"raise"}]}
                                # unilab:node_uuid=bb8b30b9-873b-5af5-b5e0-708d956a0599
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=52bb48be-192c-5443-9530-ec92bf134c9e disabled=true
                                    projected_control_0175 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/19/then/2',
                                        control_kind='if',
                                        expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/19/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=c16ebe43-b4a4-59d8-83dd-5e3665e238a5
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_suction_put@body/3/then/19/then/2/then/0；原节点 {"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别重拍仍失败(err=111), 中止放板"},"op":"raise"}
                                        # unilab:node_uuid=f7422a7d-2f7f-5d9c-9b66-018fe270fdaa
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/19/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=b4b66161-f184-50e1-965d-08c9a44fe82b disabled=true
                                            projected_control_0176 = material.review_control_node_v1(
                                                operation_name='robot_suction_put',
                                                node_path='body/3/then/19/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='6a40626789cfd5679600b1a1b2f6f06f22050fa14f437045f3d9d5dcc6da4252',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/19/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=ff967d45-5858-5a9d-bda6-70bf4b8cbfd5
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=f5e5a247-7689-5392-a6aa-63e2f47da56e disabled=true
                                        projected_control_0177 = material.review_control_node_v1(
                                            operation_name='robot_suction_put',
                                            node_path='body/3/then/19/then/2',
                                            control_kind='if',
                                            expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                                        )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/19/else 的静态审阅分支。
                            # unilab:node_uuid=818c27d3-6241-5380-9f98-d562eb99abdb
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=0573a34e-18b7-5d90-8226-21acef9bfc15 disabled=true
                                projected_control_0178 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/19',
                                    control_kind='if',
                                    expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                                )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/20；原节点 {"cond":{"binop":">","left":{"args":[{"field":{"var":"voff_xy"},"name":"drz_deg"}],"call":"abs"},"right":{"var":"drz_threshold_deg"}},"op":"if","then":[{"error":"VISION_RZ_NOT_CONVERGED","message":{"lit":"二次拍照后 Rz 残差仍超阈值, 中止放板"},"op":"raise"}]}
                        # unilab:node_uuid=923142d8-7885-5e34-a14a-73c2e3dd24db
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/20；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=f272e31f-a47b-5aaa-8323-394ab675ac09 disabled=true
                            projected_control_0179 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/20',
                                control_kind='if',
                                expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/20/then 的静态审阅分支。
                            # unilab:node_uuid=f3e36a24-552f-5eb6-9b81-8d2463d4402e
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL raise] 来源 robot_suction_put@body/3/then/20/then/0；原节点 {"error":"VISION_RZ_NOT_CONVERGED","message":{"lit":"二次拍照后 Rz 残差仍超阈值, 中止放板"},"op":"raise"}
                                # unilab:node_uuid=c665892c-ef19-590b-9c7d-a6c82b4ce421
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/20/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=8002cb92-fb3c-5ec1-98b2-d8464b3c3dd1 disabled=true
                                    projected_control_0180 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/20/then/0',
                                        control_kind='raise',
                                        expected_sha256='d1a24a4f91395a726e8540c6184463fd49fc2fe218385828e42af6f5c642b12d',
                                    )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/20/else 的静态审阅分支。
                            # unilab:node_uuid=4f9ff188-02db-5b9d-9d1b-79378326f71b
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/20；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=6d4f4f5d-963d-531b-9975-7b98d9378e48 disabled=true
                                projected_control_0181 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/20',
                                    control_kind='if',
                                    expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                                )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/21；原节点 {"op":"comment","text":"Correction preview at P86: translate XY from photo #2 while keeping the Rz correction from photo #1."}
                        # unilab:node_uuid=ad0ab5af-79e8-52f8-8857-7a2368a20f5d
                        with group(name='说明 · Correction preview at P86: translate XY from photo #2 wh'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/21；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=623d523c-6107-5a28-a6d0-e909c3029127 disabled=true
                            projected_control_0182 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/21',
                                control_kind='comment',
                                expected_sha256='152da6bbb7e27be6e627d1a263fc9073bba19a63e635f096a9db1c353d46245d',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/22；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode...
                        # unilab:node_uuid=a6372e11-6d5e-5807-8e2b-8e6e1e2dd8a2 disabled=true
                        projected_action_0183 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/23；原节点 {"op":"comment","text":"Final spotting put carries photo"}
                        # unilab:node_uuid=20b82311-9f98-5385-ad19-06b24015f383
                        with group(name='说明 · Final spotting put carries photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/23；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=0ba01b4d-3178-5685-b88b-ed9629b4253a disabled=true
                            projected_control_0184 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/23',
                                control_kind='comment',
                                expected_sha256='d34a5964054eb7bfa4a11d998941ad9c474d621664cbe44fff1c7a011f963154',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/24；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6642294f-6363-50cb-ada6-2c1ee87777bd disabled=true
                        projected_action_0185 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/25；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=60967f70-b9a6-5fa3-ae14-b992bf53c3ca disabled=true
                        projected_action_0186 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/26；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_near"},"...
                        # unilab:node_uuid=7af0ad2f-81ad-5c19-9d71-75475e78d2cd disabled=true
                        projected_action_0187 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/27；原节点 {"op":"comment","text":"Release at P19 with closed-loop correction from vision photo"}
                        # unilab:node_uuid=7888705e-b194-54df-bebe-a12cc286e78a
                        with group(name='说明 · Release at P19 with closed-loop correction from vision p'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/27；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6a404e14-5682-5eec-b9b1-efdc16553aba disabled=true
                            projected_control_0188 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/27',
                                control_kind='comment',
                                expected_sha256='d16b5d31b63a1b0b0f9c85c8e09a509abf646d4812b6ef38723c29608e0c02bd',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/28；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P19"},"vel":{"lit":5}},"mode":...
                        # unilab:node_uuid=48c6ada2-d22a-51af-9bcc-a3832d43d50b disabled=true
                        projected_action_0189 = robot.move_to_point(
                            point_id_or_robot_name='P19',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/29；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=11aecc54-ffd3-5a52-a331-7f125c6fb592 disabled=true
                        projected_action_0190 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/30；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_near"},"v...
                        # unilab:node_uuid=fece4f29-66e7-5ba1-a29d-2302ece5343f disabled=true
                        projected_action_0191 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/31；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4bcdc8aa-6c5f-5931-95a0-bcb5dbf90e61 disabled=true
                        projected_action_0192 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/32；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=31cf3427-2d85-50fc-b4f0-41dc3bf98430 disabled=true
                        projected_action_0193 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/33；原节点 {"op":"comment","text":"Safety fix: execute rotary-down only after returning to fixed transition point P4."}
                        # unilab:node_uuid=20883fb3-3804-5c70-be40-eb6846038950
                        with group(name='说明 · Safety fix: execute rotary-down only after returning to '):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/33；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=7fb93c7f-cec4-553a-ab42-838077d5d8f6 disabled=true
                            projected_control_0194 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/33',
                                control_kind='comment',
                                expected_sha256='8805176604a784f2e55230a1248ed02398b6d66a330667628b5e04cf578d6a79',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/34；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bf2108f1-3fa3-5f08-b3ea-e0b5d8b88fea disabled=true
                        projected_action_0195 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/35；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e17859ad-b44b-5c4e-bebd-b2ba34cce2d6 disabled=true
                        projected_action_0196 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/36；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4b34e958-4662-533b-9dec-eb31916b65aa disabled=true
                        projected_action_0197 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_suction_put@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=fe4e59f1-5a52-5002-b781-0ea9a2418eff
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d4cf9a01-cfaf-509e-8df7-604381d080a9 disabled=true
                        projected_action_0198 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fce2c20f-1bbe-5c03-a5c4-685cc17ed824 disabled=true
                        projected_action_0199 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a6aa18b5-40a0-52f5-86df-447a26693b70 disabled=true
                        projected_action_0200 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1b650ecc-7d5b-588d-9be6-9390dcb58ee6 disabled=true
                        projected_action_0201 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/4；原节点 {"op":"comment","text":"No later vision correction after spotting; scrape put uses nominal locator points."}
                        # unilab:node_uuid=af40ad2c-5e2a-5498-97ba-88cd1b4c03a0
                        with group(name='说明 · No later vision correction after spotting; scrape put us'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=899a0007-4f24-5877-ba56-36443272d87c disabled=true
                            projected_control_0202 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/4',
                                control_kind='comment',
                                expected_sha256='72c75af1e4a1520e92d0910d1ec5bb1fbe7428fd161fbc792048931e3b80b01d',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=032c3e30-a473-5e12-9e8d-476311241362 disabled=true
                        projected_action_0203 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e3f46cd3-32dc-5735-a5ed-f5ccc5881064 disabled=true
                        projected_action_0204 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e32f827b-592b-5102-9d4a-75c3dea45cf2 disabled=true
                        projected_action_0205 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/8；原节点 {"op":"comment","text":"Release at nominal P65; no later vision correction after spotting."}
                        # unilab:node_uuid=2493a117-4ba9-56b5-a8fe-b26da6dc30ca
                        with group(name='说明 · Release at nominal P65; no later vision correction after'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/8；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=4178dff0-59d3-5f7f-b562-a7bf16e9befe disabled=true
                            projected_control_0206 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/8',
                                control_kind='comment',
                                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P65"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b9336cee-aa13-59f2-a5dd-8d732a136489 disabled=true
                        projected_action_0207 = robot.move_to_point(
                            point_id_or_robot_name='P65',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=02ac2e99-0513-5939-86cf-ca4bd10b03f4 disabled=true
                        projected_action_0208 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2c896fed-cefd-565b-817e-a96cefee0eb1 disabled=true
                        projected_action_0209 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=68d46076-6239-5ed7-b569-568f1e2134af disabled=true
                        projected_action_0210 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=93d91a98-2661-59f8-8d65-fb01759cf6b0 disabled=true
                        projected_action_0211 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/14；原节点 {"op":"comment","text":"Release at nominal P65; no later vision correction after spotting."}
                        # unilab:node_uuid=236fd01a-08fb-50b5-8ebc-304c00074e48
                        with group(name='说明 · Release at nominal P65; no later vision correction after'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/14；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=e794f510-01bb-51a4-b614-155e25dcd949 disabled=true
                            projected_control_0212 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/14',
                                control_kind='comment',
                                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/15；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d92a963a-c7d3-5a61-a6c8-c9117ae0e369 disabled=true
                        projected_action_0213 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bcf32573-5a69-5057-9a5e-30406fde2fe0 disabled=true
                        projected_action_0214 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/17；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d4633202-38e7-5166-a55a-6bc337573ddb disabled=true
                        projected_action_0215 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 2（互斥分支）] robot_suction_put@body/3/elifs/1/body 的静态审阅分支。
                    # unilab:node_uuid=ea3fc873-26e1-50da-a5a1-6a2080af439d
                    with group(name='ELIF 2（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d7c6c24c-2517-578e-8260-4cf5ae30632f disabled=true
                        projected_action_0216 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=aa1664b4-040f-5b3c-967e-053fd210872a disabled=true
                        projected_action_0217 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=08b0831e-ca86-5794-a3a1-9f796208622e disabled=true
                        projected_action_0218 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=87cff522-656b-5417-b089-51b1ca9cb0bb disabled=true
                        projected_action_0219 = robot.move_to_point(
                            point_id_or_robot_name='P5',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d35bbe2b-34f9-51a2-a54f-edcd3c4f3872 disabled=true
                        projected_action_0220 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bc551700-7fc3-5a6e-ac61-d100b5a8e8a7 disabled=true
                        projected_action_0221 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P22"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b65cbf34-4871-5f0a-ab79-c942260bd999 disabled=true
                        projected_action_0222 = robot.move_to_point(
                            point_id_or_robot_name='P22',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=df8ee55d-2362-5b76-a3b7-763dcafc6d55 disabled=true
                        projected_action_0223 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3990f274-5dc6-59db-a4e5-4fc9f57abb2f disabled=true
                        projected_action_0224 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3836dc60-0613-5569-b4dd-354e4e265fe2 disabled=true
                        projected_action_0225 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=82c5e8af-66cd-53cf-840d-7bc088be5c04 disabled=true
                        projected_action_0226 = robot.move_to_point(
                            point_id_or_robot_name='P5',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fb23c442-cc70-5a47-87db-feb2738d2c51 disabled=true
                        projected_action_0227 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6d15081a-f187-5e40-ba73-96d9b5d62323 disabled=true
                        projected_action_0228 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=79ddf2ae-efcb-53e2-a070-2232b1d7d2fe
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_suction_put@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"suction.put: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=0e0354f2-590f-5b96-a6aa-c5af7f4fcd4d
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6e9d1e75-3cc9-5ffe-89a9-d28b4973491a disabled=true
                            projected_control_0229 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='7ee4ffd8bc9852082873ab137113eb00aa6df1b10ce72423cb995bbc3e2c295a',
                            )
            # [CONTROL comment] 来源 feedlift_unload_cycle@body/10；原节点 {"op":"comment","text":"[phase: unload] 埋料至光电消失"}
            # unilab:node_uuid=d633dc6b-a804-53e3-ad3a-6500cc65d652
            with group(name='说明 · [phase: unload] 埋料至光电消失'):
                # [VERIFY comment] 只读来源校验 feedlift_unload_cycle@body/10；节点在本工作流中静态 disabled。
                # unilab:node_uuid=9629b422-5662-5ece-8ee7-31a58c863651 disabled=true
                projected_control_0230 = material.review_control_node_v1(
                    operation_name='feedlift_unload_cycle',
                    node_path='body/10',
                    control_kind='comment',
                    expected_sha256='28585da5e43853ab9476c0bd446fd2ecbade36e8104be8e0877145fa08f0d31a',
                )
            # [ACTION feedlift.unload_bury] 来源 feedlift_unload_cycle@body/11；原节点 {"action":"feedlift.unload_bury","mode":"RUN","op":"call"}
            # unilab:node_uuid=e0e210bb-ec5c-5959-9d85-792d15278261 disabled=true
            projected_action_0231 = feedlift.unload_bury()
    # [EXECUTE ROOT pf_s11_unload] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=ce8332a3-1e51-5d21-b8af-f02b3ace38cc
    execution = material.run_operation_review_v1(
        operation_name='pf_s11_unload',
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
