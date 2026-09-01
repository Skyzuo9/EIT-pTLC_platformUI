from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.plc_feedlift import PLCFeedLift
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
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

feedlift: PLCFeedLift = device('plc_feedlift')
material: MaterialProxy = device('material')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')
sampling: PLCSampling = device('plc_sampling')
vision: VisionProxy = device('vision')


@workflow(
    workflow_uuid='5fa6553b-dc7c-577e-ad22-f0061a57475e',
    displayname='1 上样上料 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s1_load_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s1_load] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=51a864c5-c5b7-5129-85fe-c50143d21db3
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s1_load@body/0；原节点 {"op":"comment","text":"prepare: 工位初始化、清洗、7Y 到放板位 (vacuum 在 step 内 try/finally 闭合)"}
        # unilab:node_uuid=ec4b6ed4-13b9-514f-a96d-a9dec064d463
        with group(name='说明 · prepare: 工位初始化、清洗、7Y 到放板位 (vacuum 在 step 内 try/finally 闭'):
            # [VERIFY comment] 只读来源校验 pf_s1_load@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=a9d5016a-8e8b-56be-a25a-f0a62c218fac disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s1_load',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='4ed49823bdf8377f7705fef6e1e8682c4e5837c0c532ea143385796092fb8d02',
            )
        # [SUBWORKFLOW sampling_prepare] 由 pf_s1_load@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=dc6b2907-3e33-57fb-aade-a1a2a650c1b1
        with group(name='↳ sampling_prepare'):
            # [ACTION sampling.init] 来源 sampling_prepare@body/0；原节点 {"action":"sampling.init","mode":"RUN","op":"call"}
            # unilab:node_uuid=39ec3a91-995f-542d-a1ba-3366228d560e disabled=true
            projected_action_0002 = sampling.init()
            # [CONTROL comment] 来源 sampling_prepare@body/1；原节点 {"op":"comment","text":"真空区间 (外壁段5mL打废液需真空抽走; 资源门按引用计数开关泵, 异常与并发流程都不会漏关或误关)"}
            # unilab:node_uuid=9a225582-a1eb-5d0a-86e3-a9f2fc44f317
            with group(name='说明 · 真空区间 (外壁段5mL打废液需真空抽走; 资源门按引用计数开关泵, 异常与并发流程都不会漏关或误关)'):
                # [VERIFY comment] 只读来源校验 sampling_prepare@body/1；节点在本工作流中静态 disabled。
                # unilab:node_uuid=e889085a-0cb9-514c-ba2b-45a555b04207 disabled=true
                projected_control_0003 = material.review_control_node_v1(
                    operation_name='sampling_prepare',
                    node_path='body/1',
                    control_kind='comment',
                    expected_sha256='13a1220dcb5d58b2ac330dd364aa80c608cebe642496effd651de607bf467071',
                )
            # [CONTROL with_resources] 来源 sampling_prepare@body/2；原节点 {"body":[{"action":"sampling.flush","args":{"asp_speed":{"var":"asp_speed"},"flush_disp_speed":{"var":"flush_disp_speed"},"flush_volume_ml":{"var":"flush_volume_ml"},"outer_wash_volume_ml":{"var":"outer_wash_volume_ml"},"spot_head_disp_speed":{"var":"spot_head_disp_speed"},"spot_head_volume_ml":{"var":"spot_head_volume_ml"},...
            # unilab:node_uuid=d9aebe2a-ab36-5279-a98c-ee62b4ac611c
            with group(name='🔒 局部 ResourceGate · device:vacuum_pump'):
                # [VERIFY with_resources] 只读来源校验 sampling_prepare@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=b6b94b1a-08bd-5be7-8b3a-be4852be7f91 disabled=true
                projected_control_0004 = material.review_control_node_v1(
                    operation_name='sampling_prepare',
                    node_path='body/2',
                    control_kind='with_resources',
                    expected_sha256='d7b1bbab7f9a6898115f579cde1f36fadb8ea359d9f04f0265a8d0982535652a',
                )
                # [BRANCH BODY（结构展开一次）] sampling_prepare@body/2/body 的静态审阅分支。
                # unilab:node_uuid=c0bb7a33-30b7-5df1-8a81-ccdf46ded82b
                with group(name='BODY（结构展开一次）'):
                    # [ACTION sampling.flush] 来源 sampling_prepare@body/2/body/0；原节点 {"action":"sampling.flush","args":{"asp_speed":{"var":"asp_speed"},"flush_disp_speed":{"var":"flush_disp_speed"},"flush_volume_ml":{"var":"flush_volume_ml"},"outer_wash_volume_ml":{"var":"outer_wash_volume_ml"},"spot_head_disp_speed":{"var":"spot_head_disp_speed"},"spot_head_volume_ml":{"var":"spot_head_volume_ml"},"s...
                    # unilab:node_uuid=2b5f2ec7-79a6-564e-9562-14e052100ad0 disabled=true
                    projected_action_0005 = sampling.flush()
            # [CONTROL comment] 来源 sampling_prepare@body/3；原节点 {"op":"comment","text":"放板移轴 (7Y 到放板位; 为机器人放板做准备, 不需真空)"}
            # unilab:node_uuid=c1bc6339-9f6a-5ff5-b3d6-5e6605ef0177
            with group(name='说明 · 放板移轴 (7Y 到放板位; 为机器人放板做准备, 不需真空)'):
                # [VERIFY comment] 只读来源校验 sampling_prepare@body/3；节点在本工作流中静态 disabled。
                # unilab:node_uuid=002b56fd-d2e2-5d91-9029-e430cd0359c7 disabled=true
                projected_control_0006 = material.review_control_node_v1(
                    operation_name='sampling_prepare',
                    node_path='body/3',
                    control_kind='comment',
                    expected_sha256='14c13af489e079a2dd4cecc53e352bb065851fc261b0bc989706f522e9c61163',
                )
            # [ACTION sampling.place_axis] 来源 sampling_prepare@body/4；原节点 {"action":"sampling.place_axis","mode":"RUN","op":"call"}
            # unilab:node_uuid=4c4eb30c-6ec9-59ce-a93b-1b22dfd56079 disabled=true
            projected_action_0007 = sampling.place_axis()
        # [CONTROL comment] 来源 pf_s1_load@body/2；原节点 {"op":"comment","text":"load: 升降上料取板 -> 机器人放板 -> 夹紧定位; 段末板停点样座, 机器人空手"}
        # unilab:node_uuid=d5ee8dd9-fbc3-5352-9269-9011c1cef40d
        with group(name='说明 · load: 升降上料取板 -> 机器人放板 -> 夹紧定位; 段末板停点样座, 机器人空手'):
            # [VERIFY comment] 只读来源校验 pf_s1_load@body/2；节点在本工作流中静态 disabled。
            # unilab:node_uuid=e64532db-48c3-5c8a-84dd-0b755dec9816 disabled=true
            projected_control_0008 = material.review_control_node_v1(
                operation_name='pf_s1_load',
                node_path='body/2',
                control_kind='comment',
                expected_sha256='3c6ba814232f4d8d71c54ed8f0fe06e4e7122bb3a7e393f8f75b298608ce9ab1',
            )
        # [SUBWORKFLOW sampling_load] 由 pf_s1_load@body/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=337092c7-bb98-59b2-82ec-a2f85edfc479
        with group(name='↳ sampling_load'):
            # [CONTROL comment] 来源 sampling_load@body/0；原节点 {"op":"comment","text":"自守卫点样座: 先松定位夹具再把 7Y 移到放板位 (place_axis 是绝对移动, 已在位则 bAbMoveDone 直通, 故无条件调即\"不在位才移\")。放在取板之前 —— 7Y 若超时可在机械臂空手时干净中止, 排在取板后则会让机械臂持板无处可放"}
            # unilab:node_uuid=c9644380-09b9-59d0-b14d-8f58558b73e6
            with group(name='说明 · 自守卫点样座: 先松定位夹具再把 7Y 移到放板位 (place_axis 是绝对移动, 已在位则 bAbMov'):
                # [VERIFY comment] 只读来源校验 sampling_load@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=1b412c50-4f88-53cd-b024-0d6c2974c97b disabled=true
                projected_control_0009 = material.review_control_node_v1(
                    operation_name='sampling_load',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='279b8b83f21735b58aa21eb02e056f24be31fc165a245096593597c77413a23e',
                )
            # [ACTION sampling.place_release] 来源 sampling_load@body/1；原节点 {"action":"sampling.place_release","mode":"RUN","op":"call"}
            # unilab:node_uuid=81534c78-1c7e-597f-a0c1-716a315ee3c0 disabled=true
            projected_action_0010 = sampling.place_release()
            # [ACTION sampling.place_axis] 来源 sampling_load@body/2；原节点 {"action":"sampling.place_axis","mode":"RUN","op":"call"}
            # unilab:node_uuid=f48cbc64-3c4c-5624-bc5c-723cc1364d8c disabled=true
            projected_action_0011 = sampling.place_axis()
            # [CONTROL comment] 来源 sampling_load@body/3；原节点 {"op":"comment","text":"load: 升降上料取板(feedlift_load_cycle) -> 机器人放板到点样位 -> 定位夹紧; 内含缺口B 2D相机纠偏占位"}
            # unilab:node_uuid=96ceb4e8-93f5-5d33-bd42-b01a5615e780
            with group(name='说明 · load: 升降上料取板(feedlift_load_cycle) -> 机器人放板到点样位 -> 定位夹紧; '):
                # [VERIFY comment] 只读来源校验 sampling_load@body/3；节点在本工作流中静态 disabled。
                # unilab:node_uuid=41063163-6e90-5ade-b85e-25f97678929c disabled=true
                projected_control_0012 = material.review_control_node_v1(
                    operation_name='sampling_load',
                    node_path='body/3',
                    control_kind='comment',
                    expected_sha256='261c709adebc42053d1aecb9aba388b21dca097333190537fe3afffa2d80d504',
                )
            # [SUBWORKFLOW feedlift_load_cycle] 由 sampling_load@body/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=2199abb1-7d8e-53d9-b346-fe1221a4673c
            with group(name='↳ feedlift_load_cycle'):
                # [CONTROL comment] 来源 feedlift_load_cycle@body/0；原节点 {"op":"comment","text":"[phase: prepare] 先换刀再移轨: 换刀需要动作时会自己把地轨开到工具站(位4)且不还原, 排在移轨之后会让位1那趟白跑 (168->500->168)"}
                # unilab:node_uuid=99665af1-e107-5d13-a3a5-8076f996cbaa
                with group(name='说明 · [phase: prepare] 先换刀再移轨: 换刀需要动作时会自己把地轨开到工具站(位4)且不还原, 排在移'):
                    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=29893d0d-48ba-5704-b489-70f18d958d3c disabled=true
                    projected_control_0013 = material.review_control_node_v1(
                        operation_name='feedlift_load_cycle',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='4acdb1112605ade896676c495c39f230fcf686d851254f44bea07c3fa95fb594',
                    )
                # [SUBWORKFLOW robot_tool_ensure] 由 feedlift_load_cycle@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=8d3b8724-ba38-5890-95be-95535921b3fe
                with group(name='↳ robot_tool_ensure'):
                    # [CONTROL comment] 来源 robot_tool_ensure@body/0；原节点 {"op":"comment","text":"读权威工具态 (mounted_tool 启动已从状态文件恢复","回显在 tool_state.mounted_tool)":null}
                    # unilab:node_uuid=4bf73932-9143-5516-9dce-2167af20d6e0
                    with group(name='说明 · 读权威工具态 (mounted_tool 启动已从状态文件恢复'):
                        # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=e4c4a9c1-4bae-501c-ab22-20e7244fb270 disabled=true
                        projected_control_0014 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='d809e1de31eaaae6a28b91dfdc9f8587e53c48ce272668a1d7794e15c68d86f9',
                        )
                    # [ACTION robot.query] 来源 robot_tool_ensure@body/1；原节点 {"action":"robot.query","assign":{"var":"fb"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=05428f60-9642-59dd-bc58-bc67e7dcab65 disabled=true
                    projected_action_0015 = robot.query()
                    # [CONTROL assign] 来源 robot_tool_ensure@body/2；原节点 {"op":"assign","target":{"var":"current"},"value":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"mounted_tool"}}
                    # unilab:node_uuid=b0cf5fd0-77e1-5e7a-ba27-c220972c0ea9
                    with group(name='变量赋值'):
                        # [VERIFY assign] 只读来源校验 robot_tool_ensure@body/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=73578475-6aea-5b31-bd7d-1dc09af65e4a disabled=true
                        projected_control_0016 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/2',
                            control_kind='assign',
                            expected_sha256='0a8bed4ab1ed21eab44aa30c3cdc41f38a8147534c728fa885ef1da0ba3237c7',
                        )
                    # [CONTROL if] 来源 robot_tool_ensure@body/3；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"var":"needed"}},"op":"if","then":[{"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"},{"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"},{"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"r...
                    # unilab:node_uuid=a246f62d-e142-5605-b0d7-9541e7c951cc
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=00d08dd9-905f-55f8-a59f-6bbb7efd5c18 disabled=true
                        projected_control_0017 = material.review_control_node_v1(
                            operation_name='robot_tool_ensure',
                            node_path='body/3',
                            control_kind='if',
                            expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                        )
                        # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then 的静态审阅分支。
                        # unilab:node_uuid=b1f88f7c-ef66-5650-af69-4cfc5dfee4bf
                        with group(name='THEN（互斥分支）'):
                            # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/0；原节点 {"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"}
                            # unilab:node_uuid=d5f32b40-456c-5da3-a8f7-c7f0252a2cad
                            with group(name='说明 · 当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标'):
                                # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=545104ee-de3c-525c-8dc4-9e2c4afdb0e7 disabled=true
                                projected_control_0018 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/0',
                                    control_kind='comment',
                                    expected_sha256='f1c1621fc9a3af0fead9abddfba4acc6d628c4e07f02d5e1d6e79342f780d4b5',
                                )
                            # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/1；原节点 {"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"}
                            # unilab:node_uuid=ea927e5b-088c-588f-beb5-07ef773b8388
                            with group(name='说明 · 卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止'):
                                # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/1；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=f4894aa3-9246-56a3-a1e2-cec4db0cf5e1 disabled=true
                                projected_control_0019 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/1',
                                    control_kind='comment',
                                    expected_sha256='ab6b298fa1974e89ffba98e42a169ccd9b213ac1a03a6723584be2b1be7e6898',
                                )
                            # [CONTROL if] 来源 robot_tool_ensure@body/3/then/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"right":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"suction_on"}},"op":"if","then":[{"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}]}
                            # unilab:node_uuid=7b78d65b-9023-57b4-b1e1-1eb8181a2cc3
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=05add7d2-393e-534d-98c2-86c06803b697 disabled=true
                                projected_control_0020 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/2',
                                    control_kind='if',
                                    expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                )
                                # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/2/then 的静态审阅分支。
                                # unilab:node_uuid=54207c46-3e47-56a4-9848-3dd558923557
                                with group(name='THEN（互斥分支）'):
                                    # [CONTROL raise] 来源 robot_tool_ensure@body/3/then/2/then/0；原节点 {"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}
                                    # unilab:node_uuid=4caa0c4e-755c-5982-9a1c-15b6346f463c
                                    with group(name='抛出流程错误'):
                                        # [VERIFY raise] 只读来源校验 robot_tool_ensure@body/3/then/2/then/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=dd3753cf-02d1-5852-aead-6b3a2a1a9d50 disabled=true
                                        projected_control_0021 = material.review_control_node_v1(
                                            operation_name='robot_tool_ensure',
                                            node_path='body/3/then/2/then/0',
                                            control_kind='raise',
                                            expected_sha256='8ade635dfc3c21601ac8fa50ba7a168191332f67cbf70e021465f2765df9b23f',
                                        )
                                # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/2/else 的静态审阅分支。
                                # unilab:node_uuid=294245f3-7921-5dae-a6b9-7b911711cfc3
                                with group(name='ELSE（互斥分支）'):
                                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=e65f3084-bbdc-56aa-9341-eef022fb1771 disabled=true
                                    projected_control_0022 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/2',
                                        control_kind='if',
                                        expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                    )
                            # [SUBWORKFLOW rail_move_safe] 由 robot_tool_ensure@body/3/then/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                            # unilab:node_uuid=9aaab4c7-1205-5f7b-8647-a53063cc9175
                            with group(name='↳ rail_move_safe'):
                                # [CONTROL comment] 来源 rail_move_safe@body/0；原节点 {"op":"comment","text":"确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)"}
                                # unilab:node_uuid=4528e2f8-7626-58eb-b475-9028e32780cd
                                with group(name='说明 · 确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)'):
                                    # [VERIFY comment] 只读来源校验 rail_move_safe@body/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=98cd8b7d-efb2-54dc-a84f-41180956d46e disabled=true
                                    projected_control_0023 = material.review_control_node_v1(
                                        operation_name='rail_move_safe',
                                        node_path='body/0',
                                        control_kind='comment',
                                        expected_sha256='cc629ec60964ec74a746185851e52069f3b991388ab52755ebea4f3b92ed1740',
                                    )
                                # [ACTION robot.home_ensure] 来源 rail_move_safe@body/1；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=4b8ed126-f4ac-5a5b-b576-0568e24ceaa5 disabled=true
                                projected_action_0024 = robot.home_ensure()
                                # [CONTROL comment] 来源 rail_move_safe@body/2；原节点 {"op":"comment","text":"安全位确认 -> 移动地轨到目标位"}
                                # unilab:node_uuid=d2c1be9a-1f1b-5a74-b24a-a58eb1731a54
                                with group(name='说明 · 安全位确认 -> 移动地轨到目标位'):
                                    # [VERIFY comment] 只读来源校验 rail_move_safe@body/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=0d5a5ee2-3c9d-5c88-aaff-cb8819fa7cac disabled=true
                                    projected_control_0025 = material.review_control_node_v1(
                                        operation_name='rail_move_safe',
                                        node_path='body/2',
                                        control_kind='comment',
                                        expected_sha256='38f90a43c3043b67cd1207e8d94cd7c595a01ab69567c39518284d36ecb68702',
                                    )
                                # [ACTION rail.move] 来源 rail_move_safe@body/3；原节点 {"action":"rail.move","args":{"Rail_Target_Position":{"var":"target"}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=73fe9157-aaba-5992-a17b-0e0d2705dba3 disabled=true
                                projected_action_0026 = rail.move(
                                    Rail_Target_Position=1,
                                )
                            # [CONTROL if] 来源 robot_tool_ensure@body/3/then/4；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"lit":0}},"op":"if","then":[{"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}]}
                            # unilab:node_uuid=97b42374-2845-5d56-8e80-41794ed65997
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=985232eb-c16d-50d7-8210-804f96efbcb0 disabled=true
                                projected_control_0027 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3/then/4',
                                    control_kind='if',
                                    expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                )
                                # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/4/then 的静态审阅分支。
                                # unilab:node_uuid=a364a7be-59a8-5fac-80b2-b4b1b0ad4551
                                with group(name='THEN（互斥分支）'):
                                    # [SUBWORKFLOW robot_tool_put] 由 robot_tool_ensure@body/3/then/4/then/0 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                    # unilab:node_uuid=53239bf7-a642-522e-9198-4164204d2e05
                                    with group(name='↳ robot_tool_put'):
                                        # [CONTROL if] 来源 robot_tool_put@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit...
                                        # unilab:node_uuid=12f1de09-c5fe-5316-9c90-62087fa3364a
                                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                                            # [VERIFY if] 只读来源校验 robot_tool_put@body/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=936a80b5-9734-580c-87c3-7f92f8203753 disabled=true
                                            projected_control_0028 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0',
                                                control_kind='if',
                                                expected_sha256='9c64b805f035e287559b6a10c2883f201fed2852028900bfd6c9c7526352d298',
                                            )
                                            # [BRANCH THEN（互斥分支）] robot_tool_put@body/0/then 的静态审阅分支。
                                            # unilab:node_uuid=d99fe9f4-d5cb-5b67-a6d8-470d8e3bc88f
                                            with group(name='THEN（互斥分支）'):
                                                # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=88d0ad08-92ee-5d1b-807f-5186743c621a disabled=true
                                                projected_action_0029 = robot.require_anchor(
                                                    point_id='robot-main.home',
                                                )
                                                # [ACTION rail.ensure] 来源 robot_tool_put@body/0/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=4bb2fdf3-17d1-5300-ba1c-4009d95c0208 disabled=true
                                                projected_action_0030 = rail.ensure(
                                                    Rail_Target_Position=4,
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=8303bcc3-0b49-544c-b76a-e5f322a7eb69 disabled=true
                                                projected_action_0031 = robot.tool_action(
                                                    action='rotary-down',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=01783e27-69c0-5333-a289-8db674b7f5f5 disabled=true
                                                projected_action_0032 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=650d4658-e3e3-5697-b0f2-930e8c79d2fa disabled=true
                                                projected_action_0033 = robot.tool_action(
                                                    action='tool-change-aux-on',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=3d51d3d1-6608-5d01-9b25-a5ad1dc623c4 disabled=true
                                                projected_action_0034 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=71306765-400d-565c-9432-c4f9670a10cd disabled=true
                                                projected_action_0035 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=6772232b-a6d8-5f67-a966-4099b789aaf5 disabled=true
                                                projected_action_0036 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=f1d66f02-d889-505f-9686-1eb2865782ac disabled=true
                                                projected_action_0037 = robot.tool_action(
                                                    action='quick-change-release',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/9；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=ae7e32a1-0be6-5b56-be67-29bda4c3ee09 disabled=true
                                                projected_action_0038 = robot.tool_action(
                                                    action='tool-change-aux-off',
                                                )
                                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/then/10；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=3f74158f-f0a0-5c76-aa08-e4a582347ddf disabled=true
                                                projected_action_0039 = robot.set_mounted_tool(
                                                    tool_id='0',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=057d9720-d4c0-5039-be87-fae398d42616 disabled=true
                                                projected_action_0040 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=572e550b-57c2-57d4-9464-fd51dea4c213 disabled=true
                                                projected_action_0041 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                                )
                                            # [BRANCH ELIF 1（互斥分支）] robot_tool_put@body/0/elifs/0/body 的静态审阅分支。
                                            # unilab:node_uuid=f618f2a7-38d8-55ff-aa1b-0ea82ce19ae8
                                            with group(name='ELIF 1（互斥分支）'):
                                                # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=c8085cde-536b-5eaf-9ad3-b37998eeaa54 disabled=true
                                                projected_action_0042 = robot.require_anchor(
                                                    point_id='robot-main.home',
                                                )
                                                # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=46137704-9fe9-52ae-94e6-d8bb6d0da0bf disabled=true
                                                projected_action_0043 = rail.ensure(
                                                    Rail_Target_Position=4,
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=d5080b8e-fc84-5b13-8c25-a92729561214 disabled=true
                                                projected_action_0044 = robot.tool_action(
                                                    action='gripper-close',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=15dfabe3-7032-54bc-b8e6-99f28c26ddde disabled=true
                                                projected_action_0045 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=fe5bc2fd-43f5-5131-9939-b0227020d145 disabled=true
                                                projected_action_0046 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=24d76f50-8d5b-5867-b71a-249d4795d9d6 disabled=true
                                                projected_action_0047 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=ed50b6fe-59a3-5065-828b-0a8c366ce7f5 disabled=true
                                                projected_action_0048 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=5d51a16e-b3ab-59a1-a29f-8094e636e950 disabled=true
                                                projected_action_0049 = robot.tool_action(
                                                    action='quick-change-release',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=1569cea1-4c7d-5541-bdca-eaf1b05ff625 disabled=true
                                                projected_action_0050 = robot.tool_action(
                                                    action='tool-change-aux-off',
                                                )
                                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/0/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=cfcfea83-1203-5c0e-8e85-d44f411f358d disabled=true
                                                projected_action_0051 = robot.set_mounted_tool(
                                                    tool_id='0',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=04ec883c-c122-5792-8786-71bfe3e912ee disabled=true
                                                projected_action_0052 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=bea1f0a2-8135-53e7-b000-25c1a888dd3d disabled=true
                                                projected_action_0053 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                                )
                                            # [BRANCH ELIF 2（互斥分支）] robot_tool_put@body/0/elifs/1/body 的静态审阅分支。
                                            # unilab:node_uuid=eedc6762-e042-52f2-915a-add451949556
                                            with group(name='ELIF 2（互斥分支）'):
                                                # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=2b19754a-7187-5440-ac0a-d5ead500b02c disabled=true
                                                projected_action_0054 = robot.require_anchor(
                                                    point_id='robot-main.home',
                                                )
                                                # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=0d6ee250-36c9-5c1d-8300-b02ad0a80764 disabled=true
                                                projected_action_0055 = rail.ensure(
                                                    Rail_Target_Position=4,
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=bef73b0d-cde5-53af-9257-8dec33d2ba48 disabled=true
                                                projected_action_0056 = robot.tool_action(
                                                    action='gripper-close',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=165f6ea8-e9bf-59ad-8c78-683b3f889edf disabled=true
                                                projected_action_0057 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.ready',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=eff5ed5b-0ace-58f7-9daf-9660040b32d7 disabled=true
                                                projected_action_0058 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=52007c6d-8d78-58cc-8328-bd0abcff233b disabled=true
                                                projected_action_0059 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=d5a157f7-b6bc-5936-b6a0-3e5fba72db90 disabled=true
                                                projected_action_0060 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=0fab2176-2744-52dc-a102-3abdbff08453 disabled=true
                                                projected_action_0061 = robot.tool_action(
                                                    action='quick-change-release',
                                                )
                                                # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=e9607efe-1055-5ebd-956a-6887f36e4c2a disabled=true
                                                projected_action_0062 = robot.tool_action(
                                                    action='tool-change-aux-off',
                                                )
                                                # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/1/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=63797c21-ca2d-5f4f-bc82-a06c69ba1f86 disabled=true
                                                projected_action_0063 = robot.set_mounted_tool(
                                                    tool_id='0',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=a7047f79-04c8-584f-8d61-7d10f4fcbc5c disabled=true
                                                projected_action_0064 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                                )
                                                # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                                # unilab:node_uuid=76c3e41d-104a-5060-9e93-a81119994a51 disabled=true
                                                projected_action_0065 = robot.move_to_point(
                                                    point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                                )
                                            # [BRANCH ELSE（互斥分支）] robot_tool_put@body/0/else 的静态审阅分支。
                                            # unilab:node_uuid=6db1486b-6a70-52f8-8db1-80cfb8e8d1b9
                                            with group(name='ELSE（互斥分支）'):
                                                # [FLATTENED CONTROL raise] 只读来源校验 robot_tool_put@body/0/else/0；节点在本工作流中静态 disabled。
                                                # unilab:node_uuid=7a68d43c-2ce4-51b7-9678-08eb356583b2 disabled=true
                                                projected_control_0066 = material.review_control_node_v1(
                                                    operation_name='robot_tool_put',
                                                    node_path='body/0/else/0',
                                                    control_kind='raise',
                                                    expected_sha256='8aa6aa6f749c6777b2a7040e04f4316dd03cc80d36de51eec476b3dbb6c6de75',
                                                )
                                # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/4/else 的静态审阅分支。
                                # unilab:node_uuid=4fee5ff0-b056-5c69-918d-c66da51b3449
                                with group(name='ELSE（互斥分支）'):
                                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=ec822aab-f3dd-5782-8bcf-6c2b3ee4359b disabled=true
                                    projected_control_0067 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/4',
                                        control_kind='if',
                                        expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                    )
                            # [SUBWORKFLOW robot_tool_pick] 由 robot_tool_ensure@body/3/then/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                            # unilab:node_uuid=4bf86911-ca45-5102-964d-834473dce898
                            with group(name='↳ robot_tool_pick'):
                                # [CONTROL if] 来源 robot_tool_pick@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"},{"action":"robot.move...
                                # unilab:node_uuid=2a55b7ba-7e98-54c6-aa70-11e85d47e6e2
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_tool_pick@body/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=9c50fe17-254b-5fa2-b5a8-a17ad5454cac disabled=true
                                    projected_control_0068 = material.review_control_node_v1(
                                        operation_name='robot_tool_pick',
                                        node_path='body/0',
                                        control_kind='if',
                                        expected_sha256='47a5b48eb2b065101041caadd225ef492b21028bb19039ac3a19991997da1895',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_tool_pick@body/0/then 的静态审阅分支。
                                    # unilab:node_uuid=bfb47dcf-a7b5-52f7-8199-985a49e3f750
                                    with group(name='THEN（互斥分支）'):
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=ecfb2e5a-06ab-52f6-8a48-b171ecbdcc7f disabled=true
                                        projected_action_0069 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=4bff6a73-7f5d-5ef9-b5a3-21bc376dd80a disabled=true
                                        projected_action_0070 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=b1bd5cb0-bf25-527e-86f8-621c3e4304c4 disabled=true
                                        projected_action_0071 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=0d2df95a-6356-5e67-b76c-0fee00ddd1d3 disabled=true
                                        projected_action_0072 = robot.tool_action(
                                            action='quick-change-lock',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/then/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":1}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=987b2016-c926-5946-90da-e025514fb460 disabled=true
                                        projected_action_0073 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=1e6b5808-f5c7-5118-b91c-06af41da5022 disabled=true
                                        projected_action_0074 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=1f647afb-1b88-584a-9ec5-e3aa2b15ab80 disabled=true
                                        projected_action_0075 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=222f4444-47c2-5ed6-aee5-d5a2e6a85945 disabled=true
                                        projected_action_0076 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=26dde666-96a5-554c-9873-ca4d474a7d0f disabled=true
                                        projected_action_0077 = robot.dwell(
                                            duration_ms=500,
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=14032cbb-4d79-57bb-9360-824c2a1b9259 disabled=true
                                        projected_action_0078 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.home',
                                        )
                                        # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=13dad300-bfa4-53f8-9cc6-86ffd7270992 disabled=true
                                        projected_action_0079 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                    # [BRANCH ELIF 1（互斥分支）] robot_tool_pick@body/0/elifs/0/body 的静态审阅分支。
                                    # unilab:node_uuid=55a15623-b86a-5e80-9321-9ca7599e2e93
                                    with group(name='ELIF 1（互斥分支）'):
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=2027b099-d076-5cf4-b074-332e287bb1f4 disabled=true
                                        projected_action_0080 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=7b6434f6-240f-597c-b60c-79a02dcd5fa4 disabled=true
                                        projected_action_0081 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=6e2fa29e-1a93-5241-95f9-03d6f95604f2 disabled=true
                                        projected_action_0082 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=d078e118-3f71-5856-813b-543381505a8c disabled=true
                                        projected_action_0083 = robot.tool_action(
                                            action='quick-change-lock',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/0/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":2}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=30ccf84e-25d5-5eaf-9378-c6af63f20bf1 disabled=true
                                        projected_action_0084 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=900fea9c-0514-5a53-a781-b5e22692b2d2 disabled=true
                                        projected_action_0085 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=df88b88e-ba39-59f9-b196-229505931a73 disabled=true
                                        projected_action_0086 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=1dd9fefb-b36d-58c4-b0c1-79a70be63d33 disabled=true
                                        projected_action_0087 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/0/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=6db4358b-6d9b-5dbe-8391-4f25afbcedb6 disabled=true
                                        projected_action_0088 = robot.dwell(
                                            duration_ms=500,
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=9b274522-5d4d-5b0e-bf6e-186c824b994d disabled=true
                                        projected_action_0089 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.home',
                                        )
                                        # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=d7067ef2-0112-55ce-a45b-b597fc7610d4 disabled=true
                                        projected_action_0090 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                    # [BRANCH ELIF 2（互斥分支）] robot_tool_pick@body/0/elifs/1/body 的静态审阅分支。
                                    # unilab:node_uuid=f8eaee95-16da-596a-9b66-024390bf6ae6
                                    with group(name='ELIF 2（互斥分支）'):
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=97008c2d-5f6c-59d8-9c52-211b25899bb5 disabled=true
                                        projected_action_0091 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=5d9746b6-2f5f-548b-ad96-69fa625e96a0 disabled=true
                                        projected_action_0092 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=e1636e18-d7b9-5fc0-bf17-3806fa7ef4e4 disabled=true
                                        projected_action_0093 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                        )
                                        # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/1/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=7420a3df-edbe-5384-a6ac-228cebe09e49 disabled=true
                                        projected_action_0094 = robot.tool_action(
                                            action='quick-change-lock',
                                        )
                                        # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/1/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":3}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=d9eb5501-3a4b-5ad5-a568-47d0da852c62 disabled=true
                                        projected_action_0095 = robot.set_mounted_tool(
                                            tool_id='0',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=707ec159-c619-5b41-b78f-2f9f55e4acfd disabled=true
                                        projected_action_0096 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=8dc5511c-9006-5c63-b0c4-da1d5ee36035 disabled=true
                                        projected_action_0097 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=7b98f0f9-d3c1-506d-ba03-103a68a83219 disabled=true
                                        projected_action_0098 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.tool-change.ready',
                                        )
                                        # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/1/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=372ae6a9-26f9-5cf8-b624-29fe70dfebe5 disabled=true
                                        projected_action_0099 = robot.dwell(
                                            duration_ms=500,
                                        )
                                        # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=64a7d1ea-aa29-550e-82cd-ed4c1490fbda disabled=true
                                        projected_action_0100 = robot.move_to_point(
                                            point_id_or_robot_name='robot-main.home',
                                        )
                                        # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                        # unilab:node_uuid=a132662e-c9b6-5691-8b9d-408969c2d045 disabled=true
                                        projected_action_0101 = robot.require_anchor(
                                            point_id='robot-main.home',
                                        )
                                    # [BRANCH ELSE（互斥分支）] robot_tool_pick@body/0/else 的静态审阅分支。
                                    # unilab:node_uuid=bf5259d7-600c-51ab-b452-e14bf7a47ce8
                                    with group(name='ELSE（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_tool_pick@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"tool.pick: 无效选择值"},"op":"raise"}
                                        # unilab:node_uuid=d2989df4-8d7a-5a3c-8012-2b59b263f55f
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_tool_pick@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=6dd7d7d3-670b-5673-b0d0-afe90fe36659 disabled=true
                                            projected_control_0102 = material.review_control_node_v1(
                                                operation_name='robot_tool_pick',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='70c2a7e291023e9375102dc659639ba2604e87ffa8a3a94cca033c80b83c21e8',
                                            )
                        # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/else 的静态审阅分支。
                        # unilab:node_uuid=de9d4257-5e4d-5895-94e2-9669653f0b40
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=266d217d-baf3-5019-b3ed-b25a63f392e7 disabled=true
                            projected_control_0103 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3',
                                control_kind='if',
                                expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                            )
                # [CONTROL comment] 来源 feedlift_load_cycle@body/2；原节点 {"op":"comment","text":"[phase: prepare] 确定地轨在升降上料站(位1); 不在则先安全移轨(先校验机械臂在 P1 安全位再移)"}
                # unilab:node_uuid=a81c95b6-f76f-548b-920a-6f7e783fc22f
                with group(name='说明 · [phase: prepare] 确定地轨在升降上料站(位1); 不在则先安全移轨(先校验机械臂在 P1 安全位'):
                    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=ec05ab92-d0c3-5cf3-a94a-63edadda7feb disabled=true
                    projected_control_0104 = material.review_control_node_v1(
                        operation_name='feedlift_load_cycle',
                        node_path='body/2',
                        control_kind='comment',
                        expected_sha256='9308b8bfbd633d6ab33023e4424e4bc0b919a5228bb62dcc6d296a76dd977ff1',
                    )
                # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 feedlift_load_cycle@body/3；节点在本工作流中静态 disabled。
                # unilab:node_uuid=220f96fc-24b8-54dc-9dc7-2d60971d18eb disabled=true
                projected_control_0105 = material.review_control_node_v1(
                    operation_name='feedlift_load_cycle',
                    node_path='body/3',
                    control_kind='run_script',
                    expected_sha256='d080707abdd7c69af97667b5d59dc29bdabff48485e22748770f2475b550a8ba',
                )
                # [CONTROL comment] 来源 feedlift_load_cycle@body/4；原节点 {"op":"comment","text":"[phase: load] 先降轴至光电消失再升至取料光电 —— 两步缺一不可, 见下方说明"}
                # unilab:node_uuid=e7681b9a-970f-5138-ba34-9128a3f45efb
                with group(name='说明 · [phase: load] 先降轴至光电消失再升至取料光电 —— 两步缺一不可, 见下方说明'):
                    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/4；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=585a4ffb-e6a4-59ca-a1ce-3bfeb81eb52f disabled=true
                    projected_control_0106 = material.review_control_node_v1(
                        operation_name='feedlift_load_cycle',
                        node_path='body/4',
                        control_kind='comment',
                        expected_sha256='0ebf7b01b5b78c9075aac242cca0dd7ba0b9a9cde5e5fa2d287c10e6f4c43b6f',
                    )
                # [ACTION feedlift.feed_clear] 来源 feedlift_load_cycle@body/5；原节点 {"action":"feedlift.feed_clear","mode":"RUN","op":"call"}
                # unilab:node_uuid=c49ecacf-93e1-5064-b790-f045c5d526f9 disabled=true
                projected_action_0107 = feedlift.feed_clear()
                # [ACTION feedlift.feed_raise] 来源 feedlift_load_cycle@body/6；原节点 {"action":"feedlift.feed_raise","mode":"RUN","op":"call"}
                # unilab:node_uuid=a7ef9f24-e263-573b-ba72-f239f82b8224 disabled=true
                projected_action_0108 = feedlift.feed_raise()
                # [ACTION feedlift.probe_stack] 来源 feedlift_load_cycle@body/7；原节点 {"action":"feedlift.probe_stack","args":{"magazine":{"lit":"feed"},"reconcile":{"lit":true}},"assign":{"var":"p0"},"mode":"RUN","op":"call"}
                # unilab:node_uuid=27782625-8529-5df3-9928-d2a79eb35aeb disabled=true
                projected_action_0109 = feedlift.probe_stack(
                    magazine='feed',
                )
                # [CONTROL comment] 来源 feedlift_load_cycle@body/8；原节点 {"op":"comment","text":"[phase: execute] 机器人进升降取料 (rotary-down 翻下->降 P21->suction-on 吸住玻璃)"}
                # unilab:node_uuid=54a6b1aa-24b8-5968-b5bb-2b8a71ba9971
                with group(name='说明 · [phase: execute] 机器人进升降取料 (rotary-down 翻下->降 P21->suctio'):
                    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/8；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=da0d77ae-ce35-50f3-9aaf-969c14d75742 disabled=true
                    projected_control_0110 = material.review_control_node_v1(
                        operation_name='feedlift_load_cycle',
                        node_path='body/8',
                        control_kind='comment',
                        expected_sha256='2a9d500b0fb7322b9bf2b9e8d24baba3374348e7a7af2aa5fc202bece42bd8eb',
                    )
                # [SUBWORKFLOW robot_feed_lift_pick_enter] 由 feedlift_load_cycle@body/9 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=05c4c203-000e-5653-92c7-db3fe0a196b9
                with group(name='↳ robot_feed_lift_pick_enter'):
                    # [CONTROL comment] 来源 robot_feed_lift_pick_enter@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                    # unilab:node_uuid=741b0b73-7f8b-5423-a8da-3bedb34b37aa
                    with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                        # [VERIFY comment] 只读来源校验 robot_feed_lift_pick_enter@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=14e88ec9-eec9-5351-a078-29e956f96885 disabled=true
                        projected_control_0111 = material.review_control_node_v1(
                            operation_name='robot_feed_lift_pick_enter',
                            node_path='body/0',
                            control_kind='comment',
                            expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                        )
                    # [ACTION robot.home_ensure] 来源 robot_feed_lift_pick_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                    # unilab:node_uuid=9687538b-b84c-543e-9767-e1cd224a69a6 disabled=true
                    projected_action_0112 = robot.home_ensure()
                    # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_feed_lift_pick_enter@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=6b2f78e4-4f63-573f-a587-3468222ae4da disabled=true
                    projected_control_0113 = material.review_control_node_v1(
                        operation_name='robot_feed_lift_pick_enter',
                        node_path='body/2',
                        control_kind='run_script',
                        expected_sha256='6248fd65698183b23b0962f697364ce4f9a7187fdfd05d12bfc8d8f678e645b1',
                    )
                    # [CONTROL if] 来源 robot_feed_lift_pick_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"feed-lift.pick-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"...
                    # unilab:node_uuid=10d81625-89bd-5071-a51d-313b9b3df6bc
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_feed_lift_pick_enter@body/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=300b72fd-1cfd-515c-aa5d-9a8cc5b837bb disabled=true
                        projected_control_0114 = material.review_control_node_v1(
                            operation_name='robot_feed_lift_pick_enter',
                            node_path='body/3',
                            control_kind='if',
                            expected_sha256='77ad9ea57ed5342e2d1bd8ae425ff877f6bb6f2c0e506d10d79a3c3f50c7f147',
                        )
                        # [BRANCH THEN（互斥分支）] robot_feed_lift_pick_enter@body/3/then 的静态审阅分支。
                        # unilab:node_uuid=7817939f-fce5-59e4-921f-7c798fb71a67
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_feed_lift_pick_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=bdda69ba-820f-5c51-8b0a-3803aee09038 disabled=true
                            projected_action_0115 = robot.require_anchor(
                                point_id='P1',
                            )
                            # [ACTION rail.ensure] 来源 robot_feed_lift_pick_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=4c09a44b-a14b-55d4-a2df-60e73e70ae89 disabled=true
                            projected_action_0116 = rail.ensure(
                                Rail_Target_Position=1,
                            )
                            # [ACTION robot.tool_action] 来源 robot_feed_lift_pick_enter@body/3/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=fd44d85a-a98d-56aa-9042-8703f4faa484 disabled=true
                            projected_action_0117 = robot.tool_action(
                                action='rotary-down',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=df373d33-8a41-5321-8b3e-b3b2940c4293 disabled=true
                            projected_action_0118 = robot.move_to_point(
                                point_id_or_robot_name='P5',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_enter@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"feed-lift.approach_far"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=cf7c7d50-e04e-5c69-85a3-5d8633dbb614 disabled=true
                            projected_action_0119 = robot.move_to_point(
                                point_id_or_robot_name='feed-lift.approach_far',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"feed-lift.approach_near"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=a1714d7d-fd0c-57e7-ac5c-caddd711ae7c disabled=true
                            projected_action_0120 = robot.move_to_point(
                                point_id_or_robot_name='feed-lift.approach_near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_enter@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P21"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=ad4ddf88-f9aa-5b80-9eb6-a5355eb9bbec disabled=true
                            projected_action_0121 = robot.move_to_point(
                                point_id_or_robot_name='P21',
                            )
                            # [ACTION robot.tool_action] 来源 robot_feed_lift_pick_enter@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=56e02aef-2128-5724-9100-b2ca8b351a84 disabled=true
                            projected_action_0122 = robot.tool_action(
                                action='suction-on',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_feed_lift_pick_enter@body/3/then/8；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P21"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=d48117fa-0981-5955-95fb-f6bcd475f792 disabled=true
                            projected_action_0123 = robot.require_anchor(
                                point_id='P21',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_feed_lift_pick_enter@body/3/else 的静态审阅分支。
                        # unilab:node_uuid=9a945cf6-de50-5027-9a4b-c9c644dce612
                        with group(name='ELSE（互斥分支）'):
                            # [CONTROL raise] 来源 robot_feed_lift_pick_enter@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"feed-lift.pick-enter: 无效选择值"},"op":"raise"}
                            # unilab:node_uuid=cacf427d-1ea8-5e45-b3c9-8332b71e2a36
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_feed_lift_pick_enter@body/3/else/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=8e32afc6-0939-540d-85e7-917a52740602 disabled=true
                                projected_control_0124 = material.review_control_node_v1(
                                    operation_name='robot_feed_lift_pick_enter',
                                    node_path='body/3/else/0',
                                    control_kind='raise',
                                    expected_sha256='0f36308f82ec64e6c236c7b3baf64c97a839955661e14b38ef39106d62bfa5f6',
                                )
                # [CONTROL comment] 来源 feedlift_load_cycle@body/10；原节点 {"op":"comment","text":"[phase: unload] 降轴5mm让位 (吸住后给机器人撤离空间)"}
                # unilab:node_uuid=a16baf2e-d6de-5c85-b933-c3ecfbaf845e
                with group(name='说明 · [phase: unload] 降轴5mm让位 (吸住后给机器人撤离空间)'):
                    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/10；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=241736eb-e672-5f5b-9dd5-df9eb31455f4 disabled=true
                    projected_control_0125 = material.review_control_node_v1(
                        operation_name='feedlift_load_cycle',
                        node_path='body/10',
                        control_kind='comment',
                        expected_sha256='503bc219bf1316943cf46870de6ec60c377427a59da7cabc70900dc4d1e88978',
                    )
                # [ACTION feedlift.feed_lower] 来源 feedlift_load_cycle@body/11；原节点 {"action":"feedlift.feed_lower","mode":"RUN","op":"call"}
                # unilab:node_uuid=a186ec9a-7dd5-55f5-848f-496c5a427eba disabled=true
                projected_action_0126 = feedlift.feed_lower()
                # [CONTROL comment] 来源 feedlift_load_cycle@body/12；原节点 {"op":"comment","text":"机器人持板退回 P1"}
                # unilab:node_uuid=b371dce8-0ae4-51ed-b6c3-36d9d3ce9514
                with group(name='说明 · 机器人持板退回 P1'):
                    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/12；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=767d1594-9ef8-559b-8c0f-21f32d7811f7 disabled=true
                    projected_control_0127 = material.review_control_node_v1(
                        operation_name='feedlift_load_cycle',
                        node_path='body/12',
                        control_kind='comment',
                        expected_sha256='a5df47772713760de82386686f7710196f5e8d1da278eacc7f264a0f18d201a7',
                    )
                # [SUBWORKFLOW robot_feed_lift_pick_exit] 由 feedlift_load_cycle@body/13 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                # unilab:node_uuid=e61c0184-35f1-5186-b124-c58e9cf818dc
                with group(name='↳ robot_feed_lift_pick_exit'):
                    # [CONTROL if] 来源 robot_feed_lift_pick_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"feed-lift.pick-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P21"},"pos_tol_mm":{"l...
                    # unilab:node_uuid=427d0c03-1230-5576-b63f-18325d1ede5a
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 robot_feed_lift_pick_exit@body/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=fac3d92f-efb4-5791-84d9-255e1f21294a disabled=true
                        projected_control_0128 = material.review_control_node_v1(
                            operation_name='robot_feed_lift_pick_exit',
                            node_path='body/0',
                            control_kind='if',
                            expected_sha256='db88caeaaa60c637a17315b7794e00579e62623b9714659fdab07ccfe9c041df',
                        )
                        # [BRANCH THEN（互斥分支）] robot_feed_lift_pick_exit@body/0/then 的静态审阅分支。
                        # unilab:node_uuid=01f70faa-90e4-5868-8103-6cd1d4297222
                        with group(name='THEN（互斥分支）'):
                            # [ACTION robot.require_anchor] 来源 robot_feed_lift_pick_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P21"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=64d2664e-09c6-5d19-b977-d8155bce9ed4 disabled=true
                            projected_action_0129 = robot.require_anchor(
                                point_id='P21',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_exit@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"feed-lift.approach_near"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=5c44e0b6-e2c6-52ff-9c81-2e1eaf7469f6 disabled=true
                            projected_action_0130 = robot.move_to_point(
                                point_id_or_robot_name='feed-lift.approach_near',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_exit@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"feed-lift.approach_far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=c648c9f2-045a-545a-9068-be5729a14b52 disabled=true
                            projected_action_0131 = robot.move_to_point(
                                point_id_or_robot_name='feed-lift.approach_far',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=c3ed2de1-818d-526d-b0ed-3b8987968d78 disabled=true
                            projected_action_0132 = robot.move_to_point(
                                point_id_or_robot_name='P5',
                            )
                            # [ACTION robot.move_to_point] 来源 robot_feed_lift_pick_exit@body/0/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=8d20c55e-cfbc-596e-9847-848cb21c7bc7 disabled=true
                            projected_action_0133 = robot.move_to_point(
                                point_id_or_robot_name='P1',
                            )
                            # [ACTION robot.require_anchor] 来源 robot_feed_lift_pick_exit@body/0/then/5；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=7e1239f6-0670-539a-bab8-09fedf44fc0f disabled=true
                            projected_action_0134 = robot.require_anchor(
                                point_id='P1',
                            )
                        # [BRANCH ELSE（互斥分支）] robot_feed_lift_pick_exit@body/0/else 的静态审阅分支。
                        # unilab:node_uuid=659a190c-f69d-53e1-b437-8c0501ff2d02
                        with group(name='ELSE（互斥分支）'):
                            # [CONTROL raise] 来源 robot_feed_lift_pick_exit@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"feed-lift.pick-exit: 无效选择值"},"op":"raise"}
                            # unilab:node_uuid=3cdea919-9b2a-586e-a7ee-26a45e66a9e3
                            with group(name='抛出流程错误'):
                                # [VERIFY raise] 只读来源校验 robot_feed_lift_pick_exit@body/0/else/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=570057bc-19f5-5f6e-98a3-6aaab8bee75d disabled=true
                                projected_control_0135 = material.review_control_node_v1(
                                    operation_name='robot_feed_lift_pick_exit',
                                    node_path='body/0/else/0',
                                    control_kind='raise',
                                    expected_sha256='4e5326ad80db078e1931ffa127f63062555f96bc6acbf42e96dd6236ec512b55',
                                )
                # [CONTROL comment] 来源 feedlift_load_cycle@body/14；原节点 {"op":"comment","text":"[phase: verify] 探测行程: 再升轴顶到新顶板, 与取板前位置相减判定实取张数 (≠1 即报错停机)"}
                # unilab:node_uuid=afb2afcc-47be-53aa-89cc-18a4690b3824
                with group(name='说明 · [phase: verify] 探测行程: 再升轴顶到新顶板, 与取板前位置相减判定实取张数 (≠1 即报错停机'):
                    # [VERIFY comment] 只读来源校验 feedlift_load_cycle@body/14；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=6a56485d-f2b2-5f29-8151-92b9628a9f89 disabled=true
                    projected_control_0136 = material.review_control_node_v1(
                        operation_name='feedlift_load_cycle',
                        node_path='body/14',
                        control_kind='comment',
                        expected_sha256='e986df8cdf54968443a6bc93f0ace1c8aa5b177b29ae2be33be87916da116f44',
                    )
                # [ACTION feedlift.feed_raise] 来源 feedlift_load_cycle@body/15；原节点 {"action":"feedlift.feed_raise","mode":"RUN","op":"call"}
                # unilab:node_uuid=5f521905-74fe-52df-859e-0ba4e6128033 disabled=true
                projected_action_0137 = feedlift.feed_raise()
                # [ACTION feedlift.probe_stack] 来源 feedlift_load_cycle@body/16；原节点 {"action":"feedlift.probe_stack","args":{"expect_taken":{"lit":1},"magazine":{"lit":"feed"},"z_prev":{"field":{"var":"p0"},"name":"z_mm"}},"assign":{"var":"p1"},"mode":"RUN","op":"call"}
                # unilab:node_uuid=0f6eaa68-b912-59ba-abff-be0eafb74490 disabled=true
                projected_action_0138 = feedlift.probe_stack(
                    magazine='feed',
                )
            # [SUBWORKFLOW robot_suction_put] 由 sampling_load@body/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=05a6a52b-2c84-5225-ab0a-f803934d7511
            with group(name='↳ robot_suction_put'):
                # [CONTROL comment] 来源 robot_suction_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)"}
                # unilab:node_uuid=ea218e28-e831-544a-9128-098da3bb15cd
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (吸盘)'):
                    # [VERIFY comment] 只读来源校验 robot_suction_put@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=c5f23738-960d-5fa1-ab9d-a459a5583cd1 disabled=true
                    projected_control_0139 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='c894d81e6b197d1f0294fb676307e39991dde32fdd2a6a9f76a1670dd25b81bd',
                    )
                # [ACTION robot.home_ensure] 来源 robot_suction_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=686e651b-b21c-52b6-b997-590a3c0434b2 disabled=true
                projected_action_0140 = robot.home_ensure()
                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_suction_put@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=d1ce9d8e-5178-59f0-b3c8-17370c2bef82 disabled=true
                projected_control_0141 = material.review_control_node_v1(
                    operation_name='robot_suction_put',
                    node_path='body/2',
                    control_kind='run_script',
                    expected_sha256='6248fd65698183b23b0962f697364ce4f9a7187fdfd05d12bfc8d8f678e645b1',
                )
                # [CONTROL if] 来源 robot_suction_put@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"spotting"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}...
                # unilab:node_uuid=61db460c-ea7a-54f1-9ec9-c9a869bb4623
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=8ba7c967-2faf-58ad-9eab-3c3b2c9376d7 disabled=true
                    projected_control_0142 = material.review_control_node_v1(
                        operation_name='robot_suction_put',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='c6e01866d4b84eab4021c0d16f3f62c88f5591b3d547740457d335c5752f77cc',
                    )
                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=18b3926b-2663-5613-8cde-2abd463eb545
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d7d91908-940a-598e-bedf-22aa817b5956 disabled=true
                        projected_action_0143 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=11f156eb-b238-54da-a6fb-94b61bf8a265 disabled=true
                        projected_action_0144 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4340682e-cd6f-55ac-9a47-1a006fb70e3e disabled=true
                        projected_action_0145 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=98a1e3e7-f581-54a5-bff0-4a7a024538bf disabled=true
                        projected_action_0146 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/4；原节点 {"op":"comment","text":"视觉拍照 photo"}
                        # unilab:node_uuid=dd5ecb8a-7eed-529d-a598-f7ea11179090
                        with group(name='说明 · 视觉拍照 photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=ff1dc649-e990-5d7c-87c8-7a0d4ee4f8ab disabled=true
                            projected_control_0147 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/4',
                                control_kind='comment',
                                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":30},"cp":{"lit":0},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7b5d2a1b-7224-567a-ae49-cbd765c5affe disabled=true
                        projected_action_0148 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/6；原节点 {"op":"comment","text":"视觉拍照 photo"}
                        # unilab:node_uuid=058219bc-6664-5001-9d8f-1f2210798d92
                        with group(name='说明 · 视觉拍照 photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=f44d6700-a4f7-5f86-bafa-359dced5dc47 disabled=true
                            projected_control_0149 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/6',
                                control_kind='comment',
                                expected_sha256='301683a039d511be8a4eb7124dbc4d57cf3b6714ba74ccb3bcb95a8a9a481e4e',
                            )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/7；原节点 {"op":"comment","text":"拍照前整定: 视觉触发路径无内建 settle, 先驻留让机械臂到位后残振衰减再拍 (photo #1)"}
                        # unilab:node_uuid=92488b5e-8ef0-5996-b488-0f1da4f4450e
                        with group(name='说明 · 拍照前整定: 视觉触发路径无内建 settle, 先驻留让机械臂到位后残振衰减再拍 (photo #1)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/7；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=7568ba12-1754-5e36-8d49-2bf7f8a4616b disabled=true
                            projected_control_0150 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/7',
                                control_kind='comment',
                                expected_sha256='6eb397dae264a9b5a09ae3c1405d64b2e9c5a940c36db02de4fccc6dbc9c1bcc',
                            )
                        # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=33ad92bb-ce91-57e3-b5d3-9e0264877014 disabled=true
                        projected_action_0151 = robot.dwell(
                            duration_ms=300,
                        )
                        # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/9；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b6fe8f5d-f248-58f1-b4ea-37bfb13e29fe disabled=true
                        projected_action_0152 = vision.capture_plate_offset()
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/10；原节点 {"op":"comment","text":"photo #1 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)"}
                        # unilab:node_uuid=e764b3df-af96-52fe-8b15-bc6a77095e1d
                        with group(name='说明 · photo #1 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/10；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=9b0ad0cd-99ab-57cf-bb51-9f5a2ef15b7d disabled=true
                            projected_control_0153 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/10',
                                control_kind='comment',
                                expected_sha256='da1eff387eb64169c00489a80c9924bb0712d59bd3a8c496e6bbce7259465c59',
                            )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/11；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_r...
                        # unilab:node_uuid=6f9e24cb-55ff-5306-bd82-8b5ffe199b8e
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=35b25787-7aa9-524c-ada6-5e836a03a3ee disabled=true
                            projected_control_0154 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/11',
                                control_kind='if',
                                expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/11/then 的静态审阅分支。
                            # unilab:node_uuid=4c0e49f0-58b6-51a6-8eb4-e41720e09a02
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL human] 来源 robot_suction_put@body/3/then/11/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}}
                                # unilab:node_uuid=dde1b06a-33ff-5b83-a2d7-8a6ba74beb43
                                with group(name='◆ HITL 人工门'):
                                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/11/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=46ac96b9-944c-58b0-b9a2-51da5cd054fb disabled=true
                                    projected_control_0155 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/11/then/0',
                                        control_kind='human',
                                        expected_sha256='8b6554332d59da20e8cd66a97f4e67c5e9471404e4488c74e2aede653f7c5a9d',
                                    )
                                # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/11/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_rz"},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=63dfabc3-9848-56f5-8c3b-a4535f98f655 disabled=true
                                projected_action_0156 = vision.capture_plate_offset()
                                # [CONTROL if] 来源 robot_suction_put@body/3/then/11/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_rz"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别仍失败(err=111), 中止放板"},"op":"raise"}]}
                                # unilab:node_uuid=bfb4ec8f-ce4f-5c8b-9832-705db2fc3a93
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/11/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=aad2b0d6-c9db-57cc-be03-3eade59e5210 disabled=true
                                    projected_control_0157 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/11/then/2',
                                        control_kind='if',
                                        expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/11/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=cfec68a7-cabf-5307-a336-2e52b8096fbd
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_suction_put@body/3/then/11/then/2/then/0；原节点 {"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别仍失败(err=111), 中止放板"},"op":"raise"}
                                        # unilab:node_uuid=5247aed2-2ea6-5dff-a978-b3068005c37b
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/11/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=b24a8906-7475-516a-b423-fc218f28fab7 disabled=true
                                            projected_control_0158 = material.review_control_node_v1(
                                                operation_name='robot_suction_put',
                                                node_path='body/3/then/11/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='be10d3c30d5567c5173255006de750689ae329cb8beab67051668e78cfe857d1',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/11/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=e383d74c-32b0-5c2d-8589-3e134d218efc
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=f5194a49-b8fb-5518-b153-b16df6dfc4db disabled=true
                                        projected_control_0159 = material.review_control_node_v1(
                                            operation_name='robot_suction_put',
                                            node_path='body/3/then/11/then/2',
                                            control_kind='if',
                                            expected_sha256='17d720a48e9abd7175aabd7a2067c2d97a95344f3596cb82432e8553cfba80c0',
                                        )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/11/else 的静态审阅分支。
                            # unilab:node_uuid=e1e9bce9-065e-5395-ab32-bfa8df577675
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/11；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=8688b17d-9ed7-5248-88cc-40c810ac641f disabled=true
                                projected_control_0160 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/11',
                                    control_kind='if',
                                    expected_sha256='4378c1c63f2d5f0c90863c3eb47f522c0ce9e114c719f082bb91c324fff89c8c',
                                )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/12；原节点 {"op":"comment","text":"Correction at P86: rotate Rz first so the plate angle matches the template."}
                        # unilab:node_uuid=c5a7dc31-e492-519d-b8d8-d3df4df274cf
                        with group(name='说明 · Correction at P86: rotate Rz first so the plate angle ma'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/12；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=db3e2653-4e71-5130-8fa9-88bc30ece028 disabled=true
                            projected_control_0161 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/12',
                                control_kind='comment',
                                expected_sha256='048674f96cc7d9fb228936ecdb955de10db5887d33835cfc6ea532a5508b4f8c',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"lit":0},"dy_mm":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ccaef9c8-9b05-5381-a568-a7163e3344cd disabled=true
                        projected_action_0162 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/14；原节点 {"op":"comment","text":"视觉拍照 #2 after Rz correction: verify residual Rz and re-measure current dx/dy."}
                        # unilab:node_uuid=a3292155-911a-5288-b83e-fe7c2ecf343e
                        with group(name='说明 · 视觉拍照 #2 after Rz correction: verify residual Rz and re-m'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/14；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=3dc8fde4-45ee-526b-9ad4-c8a89ed85441 disabled=true
                            projected_control_0163 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/14',
                                control_kind='comment',
                                expected_sha256='edde8dc0a1dbbe5d4b7696db96096110c9413ee1e108d8eeaadcc4acca4b40a7',
                            )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/15；原节点 {"op":"comment","text":"拍照前整定: Rz 纠偏 move 到位后先驻留让残振衰减再拍, 提升二次纠偏 dx/dy 读数稳定性 (photo #2)"}
                        # unilab:node_uuid=8b46eeba-d849-58db-9d67-288e5e421080
                        with group(name='说明 · 拍照前整定: Rz 纠偏 move 到位后先驻留让残振衰减再拍, 提升二次纠偏 dx/dy 读数稳定性 (pho'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/15；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=afc77a6b-e7ef-5538-9970-96257301063c disabled=true
                            projected_control_0164 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/15',
                                control_kind='comment',
                                expected_sha256='c80c2f69ad6f5f186109645ffa15fa383576a369addd3d672205333e130a5b58',
                            )
                        # [ACTION robot.dwell] 来源 robot_suction_put@body/3/then/16；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":300}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=53b033b9-0543-568e-8407-f46b1ebb960b disabled=true
                        projected_action_0165 = robot.dwell(
                            duration_ms=300,
                        )
                        # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/17；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b0881c05-9b3f-542c-bbf9-bce6ddba08b1 disabled=true
                        projected_action_0166 = vision.capture_plate_offset()
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/18；原节点 {"op":"comment","text":"photo #2 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)"}
                        # unilab:node_uuid=bb9a283b-b24c-5f3f-b0c8-d69656ff2584
                        with group(name='说明 · photo #2 err==111 识别失败: 暂停人工处置 (确认=重拍一次; 再失败则 raise 中止)'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/18；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=664fef00-a1f6-5023-9256-1cf1eec4840d disabled=true
                            projected_control_0167 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/18',
                                control_kind='comment',
                                expected_sha256='c883d653edf20b229c98087fef4e0a7a74c71315be24a495a2ab4d63627ddbc7',
                            )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/19；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机二次识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}},{"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff...
                        # unilab:node_uuid=8d88239f-53ac-521b-ba09-440bdeca05c5
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=42ccf732-5fb0-5a3b-b206-e9c44802b19a disabled=true
                            projected_control_0168 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/19',
                                control_kind='if',
                                expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/19/then 的静态审阅分支。
                            # unilab:node_uuid=e30fb88a-a38f-5c67-a156-d164fae5446a
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL human] 来源 robot_suction_put@body/3/then/19/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"相机二次识别失败(err=111), 已停。确认=重拍一次; 取消=中止放板"}}
                                # unilab:node_uuid=c6ceb696-212a-5849-842a-210923f78094
                                with group(name='◆ HITL 人工门'):
                                    # [VERIFY human] 只读来源校验 robot_suction_put@body/3/then/19/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=3bfbc951-5472-526a-a134-ae657be3d16c disabled=true
                                    projected_control_0169 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/19/then/0',
                                        control_kind='human',
                                        expected_sha256='cac0a9d59b9391aae093bca3c1049db6e51757d3aae2d1a433addc60e61ea15d',
                                    )
                                # [ACTION vision.capture_plate_offset] 来源 robot_suction_put@body/3/then/19/then/1；原节点 {"action":"vision.capture_plate_offset","args":{"apply_rz":{"lit":true}},"assign":{"var":"voff_xy"},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9ab8d3e8-c8a6-5b17-aed3-2190ca0b8247 disabled=true
                                projected_action_0170 = vision.capture_plate_offset()
                                # [CONTROL if] 来源 robot_suction_put@body/3/then/19/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"voff_xy"},"name":"valid"},"right":{"lit":false}},"op":"if","then":[{"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别重拍仍失败(err=111), 中止放板"},"op":"raise"}]}
                                # unilab:node_uuid=93f9950b-ab3b-57c4-a74c-9147f0701a73
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/19/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=35dffd24-ed3c-5b83-9eb9-6353cb570010 disabled=true
                                    projected_control_0171 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/19/then/2',
                                        control_kind='if',
                                        expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/19/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=c36a6b03-22dd-597d-97b1-db11f8fb2493
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_suction_put@body/3/then/19/then/2/then/0；原节点 {"error":"VISION_CORRECT_FAILED","message":{"lit":"相机二次识别重拍仍失败(err=111), 中止放板"},"op":"raise"}
                                        # unilab:node_uuid=0424074e-2507-588c-ad91-a5a05e282935
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/19/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=13600f44-4e16-5c1b-b5f4-1c298826efe5 disabled=true
                                            projected_control_0172 = material.review_control_node_v1(
                                                operation_name='robot_suction_put',
                                                node_path='body/3/then/19/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='6a40626789cfd5679600b1a1b2f6f06f22050fa14f437045f3d9d5dcc6da4252',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/19/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=880f0714-2734-5752-82c5-7989f20e00cb
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=a81ef2b7-8c15-53ef-8893-78fb75bb9524 disabled=true
                                        projected_control_0173 = material.review_control_node_v1(
                                            operation_name='robot_suction_put',
                                            node_path='body/3/then/19/then/2',
                                            control_kind='if',
                                            expected_sha256='7411340728984b369426a7e03f22be1f43819ac50708c55f92a844577e6033fd',
                                        )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/19/else 的静态审阅分支。
                            # unilab:node_uuid=fd2d6f80-eae8-50ee-857a-1173b682b9f1
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/19；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=e0288b85-21a3-5919-9486-3715a20b0a19 disabled=true
                                projected_control_0174 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/19',
                                    control_kind='if',
                                    expected_sha256='132e27f60cc5e94a2c167e80d50d4277fb7920749cf1caaf79927c1a320f162b',
                                )
                        # [CONTROL if] 来源 robot_suction_put@body/3/then/20；原节点 {"cond":{"binop":">","left":{"args":[{"field":{"var":"voff_xy"},"name":"drz_deg"}],"call":"abs"},"right":{"var":"drz_threshold_deg"}},"op":"if","then":[{"error":"VISION_RZ_NOT_CONVERGED","message":{"lit":"二次拍照后 Rz 残差仍超阈值, 中止放板"},"op":"raise"}]}
                        # unilab:node_uuid=fa9d15b1-5736-54d1-8439-006a94c82cc1
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_suction_put@body/3/then/20；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6b6e42dc-ecdc-5b0d-b60c-ffbc56daa3c0 disabled=true
                            projected_control_0175 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/20',
                                control_kind='if',
                                expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                            )
                            # [BRANCH THEN（互斥分支）] robot_suction_put@body/3/then/20/then 的静态审阅分支。
                            # unilab:node_uuid=24718724-7c74-5c08-9f1b-acccb45f5a0f
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL raise] 来源 robot_suction_put@body/3/then/20/then/0；原节点 {"error":"VISION_RZ_NOT_CONVERGED","message":{"lit":"二次拍照后 Rz 残差仍超阈值, 中止放板"},"op":"raise"}
                                # unilab:node_uuid=899e4616-44fa-5f0e-a845-5f210d11f5ae
                                with group(name='抛出流程错误'):
                                    # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/then/20/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=e9ff7faa-3198-54f9-b03b-52b7ca65a570 disabled=true
                                    projected_control_0176 = material.review_control_node_v1(
                                        operation_name='robot_suction_put',
                                        node_path='body/3/then/20/then/0',
                                        control_kind='raise',
                                        expected_sha256='d1a24a4f91395a726e8540c6184463fd49fc2fe218385828e42af6f5c642b12d',
                                    )
                            # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/then/20/else 的静态审阅分支。
                            # unilab:node_uuid=b224a5cf-6da8-5e7d-8ab5-8432ad816b06
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_suction_put@body/3/then/20；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=a34e2b47-2b6c-5ba1-bc2f-9d9859de3118 disabled=true
                                projected_control_0177 = material.review_control_node_v1(
                                    operation_name='robot_suction_put',
                                    node_path='body/3/then/20',
                                    control_kind='if',
                                    expected_sha256='b28531914f6c72c04aab8c984fa58b96b176b8e5de23b8768805c17624624f74',
                                )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/21；原节点 {"op":"comment","text":"Correction preview at P86: translate XY from photo #2 while keeping the Rz correction from photo #1."}
                        # unilab:node_uuid=dedb39a5-138d-55b2-ba17-49da4cee896c
                        with group(name='说明 · Correction preview at P86: translate XY from photo #2 wh'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/21；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=d9b3a156-fdbb-5cee-af19-59e57e2f8425 disabled=true
                            projected_control_0178 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/21',
                                control_kind='comment',
                                expected_sha256='152da6bbb7e27be6e627d1a263fc9073bba19a63e635f096a9db1c353d46245d',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/22；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P86"},"vel":{"lit":10}},"mode...
                        # unilab:node_uuid=fda8e60c-c6e0-5ba7-a67b-7e905b23671e disabled=true
                        projected_action_0179 = robot.move_to_point(
                            point_id_or_robot_name='P86',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/23；原节点 {"op":"comment","text":"Final spotting put carries photo"}
                        # unilab:node_uuid=86e000a8-bf0c-57cf-a6a0-9981bebb205e
                        with group(name='说明 · Final spotting put carries photo'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/23；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6c341b3c-41c3-5d93-904e-3dd78c2d6293 disabled=true
                            projected_control_0180 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/23',
                                control_kind='comment',
                                expected_sha256='d34a5964054eb7bfa4a11d998941ad9c474d621664cbe44fff1c7a011f963154',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/24；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=871b1c8a-bce9-5f54-a886-ea9984b257ee disabled=true
                        projected_action_0181 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/25；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d0214e69-4570-535d-82d3-ec243d3f37a1 disabled=true
                        projected_action_0182 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/26；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.approach_near"},"...
                        # unilab:node_uuid=e63da278-df96-5b47-afdf-31afad2fbdd0 disabled=true
                        projected_action_0183 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/27；原节点 {"op":"comment","text":"Release at P19 with closed-loop correction from vision photo"}
                        # unilab:node_uuid=0ee0a513-6797-58fb-b259-a48e6064ef45
                        with group(name='说明 · Release at P19 with closed-loop correction from vision p'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/27；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=e3b31f24-d62a-57c1-b3d5-06bbdd298340 disabled=true
                            projected_control_0184 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/27',
                                control_kind='comment',
                                expected_sha256='d16b5d31b63a1b0b0f9c85c8e09a509abf646d4812b6ef38723c29608e0c02bd',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/28；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P19"},"vel":{"lit":5}},"mode":...
                        # unilab:node_uuid=6d8e1874-d569-52ce-ab8c-103e6bb1666a disabled=true
                        projected_action_0185 = robot.move_to_point(
                            point_id_or_robot_name='P19',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/29；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5951764c-deec-5ff2-948a-a3ba9d7e0eb8 disabled=true
                        projected_action_0186 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/30；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"drz_deg":{"field":{"var":"voff_rz"},"name":"drz_deg"},"dx_mm":{"field":{"var":"voff_xy"},"name":"dx_mm"},"dy_mm":{"field":{"var":"voff_xy"},"name":"dy_mm"},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_near"},"v...
                        # unilab:node_uuid=dd0faa1c-87b1-5fa3-ba26-8c0704ead43c disabled=true
                        projected_action_0187 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/31；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"spotting.put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1b17b81f-e261-5b3e-88be-c338329d859e disabled=true
                        projected_action_0188 = robot.move_to_point(
                            point_id_or_robot_name='spotting.put.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/32；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b54dd076-0493-58a4-9e95-e53ddd5354c9 disabled=true
                        projected_action_0189 = robot.move_to_point(
                            point_id_or_robot_name='P4',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/then/33；原节点 {"op":"comment","text":"Safety fix: execute rotary-down only after returning to fixed transition point P4."}
                        # unilab:node_uuid=9ab1c88f-fa4b-5aef-bf3c-cf21995b40ac
                        with group(name='说明 · Safety fix: execute rotary-down only after returning to '):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/then/33；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=336ef660-8d11-5432-968a-0e5fdd306cfb disabled=true
                            projected_control_0190 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/then/33',
                                control_kind='comment',
                                expected_sha256='8805176604a784f2e55230a1248ed02398b6d66a330667628b5e04cf578d6a79',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/then/34；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=76472beb-b13b-503b-b74a-e98dd9e44cb9 disabled=true
                        projected_action_0191 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/then/35；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=be9d8e27-f5e2-51ca-a483-b0489089b44d disabled=true
                        projected_action_0192 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/then/36；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a181fe32-a731-59d1-b687-2c669b91ceb7 disabled=true
                        projected_action_0193 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_suction_put@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=6b3cff48-d12f-55b8-98a1-584d98429aac
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c20a27e5-382b-57b6-ba66-a0cff96bbeb9 disabled=true
                        projected_action_0194 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e9d742ce-03cf-5e41-8e30-9d93f7cf6262 disabled=true
                        projected_action_0195 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f8918a90-6157-5b4d-bf1a-207ae26688a8 disabled=true
                        projected_action_0196 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-up"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=44493493-e3d1-5ed8-a910-3d4b5fda7ef9 disabled=true
                        projected_action_0197 = robot.tool_action(
                            action='rotary-up',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/4；原节点 {"op":"comment","text":"No later vision correction after spotting; scrape put uses nominal locator points."}
                        # unilab:node_uuid=6158babb-ed44-53b6-9d50-ddb654328f04
                        with group(name='说明 · No later vision correction after spotting; scrape put us'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=02d1ef91-ae8a-5e62-a1a3-bce4673c16c5 disabled=true
                            projected_control_0198 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/4',
                                control_kind='comment',
                                expected_sha256='72c75af1e4a1520e92d0910d1ec5bb1fbe7428fd161fbc792048931e3b80b01d',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e8066b2e-fa30-56e9-8453-111cdc776b37 disabled=true
                        projected_action_0199 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=609cd9a7-e3af-57ff-80b4-4cd4ae639d80 disabled=true
                        projected_action_0200 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8057fccb-7383-588d-aeaf-e450db9a5576 disabled=true
                        projected_action_0201 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.approach_near',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/8；原节点 {"op":"comment","text":"Release at nominal P65; no later vision correction after spotting."}
                        # unilab:node_uuid=e279bab5-561c-5903-b2ab-2208e3248b03
                        with group(name='说明 · Release at nominal P65; no later vision correction after'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/8；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=636b3956-b9d8-5adb-8365-44304db223c5 disabled=true
                            projected_control_0202 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/8',
                                control_kind='comment',
                                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P65"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bee2f714-6fcf-52dd-8d6e-7494b4eaf7d6 disabled=true
                        projected_action_0203 = robot.move_to_point(
                            point_id_or_robot_name='P65',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/10；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c64da6f9-a457-5881-8ea1-d9a4109a6528 disabled=true
                        projected_action_0204 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f52d5838-8ad1-5943-995d-e9605e8f3b19 disabled=true
                        projected_action_0205 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.retreat_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape.plate-put.retreat_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=119e672b-b371-542e-956e-3d873f805285 disabled=true
                        projected_action_0206 = robot.move_to_point(
                            point_id_or_robot_name='scrape.plate-put.retreat_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P63"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ac293a0e-30cd-57ae-81c2-83e2a769fd45 disabled=true
                        projected_action_0207 = robot.move_to_point(
                            point_id_or_robot_name='P63',
                        )
                        # [CONTROL comment] 来源 robot_suction_put@body/3/elifs/0/body/14；原节点 {"op":"comment","text":"Release at nominal P65; no later vision correction after spotting."}
                        # unilab:node_uuid=d5b6e271-a064-55dc-9e5e-d460f2e7c430
                        with group(name='说明 · Release at nominal P65; no later vision correction after'):
                            # [VERIFY comment] 只读来源校验 robot_suction_put@body/3/elifs/0/body/14；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=26719d90-9173-5459-a55b-5c6259d1c874 disabled=true
                            projected_control_0208 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/elifs/0/body/14',
                                control_kind='comment',
                                expected_sha256='6526f7524b996512feaef1ebd05e7573555705129d7bc500da62ab80c6ae60ee',
                            )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/0/body/15；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=179e0258-a525-5884-a6a3-c18478f37352 disabled=true
                        projected_action_0209 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/0/body/16；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=dd0e3729-6c12-5660-9ec7-0bba3c6035d4 disabled=true
                        projected_action_0210 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/0/body/17；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3aebac48-bbcb-5a97-91f6-fb7940e1bd88 disabled=true
                        projected_action_0211 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 2（互斥分支）] robot_suction_put@body/3/elifs/1/body 的静态审阅分支。
                    # unilab:node_uuid=e008b7a7-b6f1-55df-a872-231b8a6a6429
                    with group(name='ELIF 2（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bac56962-7d03-5ace-980c-9c3fd3fb0a9a disabled=true
                        projected_action_0212 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_suction_put@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":1}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ef91ca19-43a5-53b3-9a0a-fa57636f5699 disabled=true
                        projected_action_0213 = rail.ensure(
                            Rail_Target_Position=1,
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bc907e6d-626c-59ff-b922-6cfde82fa5b6 disabled=true
                        projected_action_0214 = robot.tool_action(
                            action='rotary-down',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=90336400-091b-55e5-aaa9-7546e2b43c2d disabled=true
                        projected_action_0215 = robot.move_to_point(
                            point_id_or_robot_name='P5',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4c6b2a0f-8722-56cf-b717-5155d53a045b disabled=true
                        projected_action_0216 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1d48ee6a-5017-53df-979b-06042ec6d653 disabled=true
                        projected_action_0217 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P22"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=84c38f9e-e8ba-5d78-9a93-d11c91053366 disabled=true
                        projected_action_0218 = robot.move_to_point(
                            point_id_or_robot_name='P22',
                        )
                        # [ACTION robot.tool_action] 来源 robot_suction_put@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"suction-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=99f4f8b3-79aa-5a6d-8770-91845e334126 disabled=true
                        projected_action_0219 = robot.tool_action(
                            action='suction-off',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=851a5ff8-05f6-5473-a927-ca862d8d1dbe disabled=true
                        projected_action_0220 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"waste.approach_far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3274b558-6d65-51c9-80d9-f4c43f87e0f3 disabled=true
                        projected_action_0221 = robot.move_to_point(
                            point_id_or_robot_name='waste.approach_far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P5"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f8de5405-517d-510a-bc39-5e2d66ae6678 disabled=true
                        projected_action_0222 = robot.move_to_point(
                            point_id_or_robot_name='P5',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_suction_put@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a437fa62-aa23-5496-8cea-00f694e2807c disabled=true
                        projected_action_0223 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_suction_put@body/3/elifs/1/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5f267cbc-a855-544f-b015-8413e3e84c8c disabled=true
                        projected_action_0224 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_suction_put@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=e1805fb7-0447-5091-a550-946729d0f9f5
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_suction_put@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"suction.put: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=827fdc6a-ed22-5897-85dd-bff07b1cafc1
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_suction_put@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=2fa5c793-9149-583b-86ed-97d713626bfa disabled=true
                            projected_control_0225 = material.review_control_node_v1(
                                operation_name='robot_suction_put',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='7ee4ffd8bc9852082873ab137113eb00aa6df1b10ce72423cb995bbc3e2c295a',
                            )
            # [CONTROL comment] 来源 sampling_load@body/6；原节点 {"op":"comment","text":"机器人放板后定位夹紧"}
            # unilab:node_uuid=74e68028-26c8-587f-8179-77932c7b007f
            with group(name='说明 · 机器人放板后定位夹紧'):
                # [VERIFY comment] 只读来源校验 sampling_load@body/6；节点在本工作流中静态 disabled。
                # unilab:node_uuid=daa1d526-c9f5-59cb-bab6-5f8241085a3c disabled=true
                projected_control_0226 = material.review_control_node_v1(
                    operation_name='sampling_load',
                    node_path='body/6',
                    control_kind='comment',
                    expected_sha256='3938c51eb423a7bc48f539f82c00867079fec7a661bbdbb4f592a9e44a5033c0',
                )
            # [ACTION sampling.place_locate] 来源 sampling_load@body/7；原节点 {"action":"sampling.place_locate","mode":"RUN","op":"call"}
            # unilab:node_uuid=d8baea2c-e43d-5dba-8270-5e161f04f4f2 disabled=true
            projected_action_0227 = sampling.place_locate()
    # [EXECUTE ROOT pf_s1_load] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=0fac43f1-6001-51ec-bad1-cf3e4fafee2d
    execution = material.run_operation_review_v1(
        operation_name='pf_s1_load',
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
