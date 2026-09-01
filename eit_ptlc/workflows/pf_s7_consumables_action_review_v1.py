from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
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

material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='74e6871d-47cb-54b5-a72f-75e724f3dbd6',
    displayname='5-2 备耗材 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s7_consumables_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s7_consumables] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=dfe0df78-3151-5540-a16c-089ec0f2c563
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s7_consumables@body/0；原节点 {"op":"comment","text":"耗材就位保证 (按账本决策): 中转板还有未用孔就原地复用; 中转空则取新板; 耗尽则先送回满板再取新板 (整板转运的工具2大夹爪由 ensure_* 内部按需切换)"}
        # unilab:node_uuid=35d35b7c-b79f-5a8e-8307-e3686b5c544d
        with group(name='说明 · 耗材就位保证 (按账本决策): 中转板还有未用孔就原地复用; 中转空则取新板; 耗尽则先送回满板再取新板 (整板'):
            # [VERIFY comment] 只读来源校验 pf_s7_consumables@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=c88d7326-9acf-5e11-92c0-3d505101c663 disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s7_consumables',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='4cb1bb24e4f3411490f78db9bc55fe7613593b23560c55fa1a9a171627827c7e',
            )
        # [SUBWORKFLOW ensure_collector_staged] 由 pf_s7_consumables@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=5ef7bd4b-4f00-5090-8e48-426be46bf0c4
        with group(name='↳ ensure_collector_staged'):
            # [CONTROL comment] 来源 ensure_collector_staged@body/0；原节点 {"op":"comment","text":"读账本决策 (含中转A 在位防呆); 账上无未用孔或账实不符时本动作直接抛错停机"}
            # unilab:node_uuid=1b2bd0ec-027d-5f17-b2b0-e0a4386e390d
            with group(name='说明 · 读账本决策 (含中转A 在位防呆); 账上无未用孔或账实不符时本动作直接抛错停机'):
                # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=6e04112c-2a46-517d-a9ae-281a9ecdf203 disabled=true
                projected_control_0002 = material.review_control_node_v1(
                    operation_name='ensure_collector_staged',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='9f4fd728acf47dc72b9c5e3d2d3f0853aeee948ce1ef8dd555e4ba5c94277932',
                )
            # [ACTION material.plan_staging] 来源 ensure_collector_staged@body/1；原节点 {"action":"material.plan_staging","args":{"kind":{"lit":"collector"},"reserve_for":{"var":"reserve_for"}},"assign":{"var":"plan"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=7f50ccbc-e22f-58eb-8db7-b2bb2003e235 disabled=true
            projected_action_0003 = material.plan_staging(
                kind='collector',
            )
            # [CONTROL assign] 来源 ensure_collector_staged@body/2；原节点 {"op":"assign","target":{"var":"op"},"value":{"field":{"var":"plan"},"name":"op"}}
            # unilab:node_uuid=569835fa-696c-554d-b6a1-c69f622b2138
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 ensure_collector_staged@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=976eaf0d-c5c5-597d-8fe2-ae52292e4bda disabled=true
                projected_control_0004 = material.review_control_node_v1(
                    operation_name='ensure_collector_staged',
                    node_path='body/2',
                    control_kind='assign',
                    expected_sha256='752a8e7ac062b5aa2e33a6a2b515271a78f200116fa26e4d00d4329175c46e62',
                )
            # [CONTROL assign] 来源 ensure_collector_staged@body/3；原节点 {"op":"assign","target":{"var":"rack_slot"},"value":{"field":{"var":"plan"},"name":"rack_slot"}}
            # unilab:node_uuid=c5e2297f-21eb-5a96-b517-7ca80698fe96
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 ensure_collector_staged@body/3；节点在本工作流中静态 disabled。
                # unilab:node_uuid=cdf27f79-7e73-5d57-af59-3d40c7185086 disabled=true
                projected_control_0005 = material.review_control_node_v1(
                    operation_name='ensure_collector_staged',
                    node_path='body/3',
                    control_kind='assign',
                    expected_sha256='0fa3379fc03f812629d15c29be64125a73fcf8fe233e44134a51cc3b8c57dd12',
                )
            # [CONTROL assign] 来源 ensure_collector_staged@body/4；原节点 {"op":"assign","target":{"var":"old_rack_slot"},"value":{"field":{"var":"plan"},"name":"old_rack_slot"}}
            # unilab:node_uuid=917a5742-17dd-54f9-96f6-cdfa45e6155b
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 ensure_collector_staged@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=4d87f71f-09e8-56b1-a9f3-5e2fed542b0d disabled=true
                projected_control_0006 = material.review_control_node_v1(
                    operation_name='ensure_collector_staged',
                    node_path='body/4',
                    control_kind='assign',
                    expected_sha256='cbc19c59699b67029e4de5b8a1c8224b6d104b1467266ea88c3a714ab58d30e1',
                )
            # [CONTROL assign] 来源 ensure_collector_staged@body/5；原节点 {"op":"assign","target":{"var":"hole"},"value":{"field":{"var":"plan"},"name":"hole"}}
            # unilab:node_uuid=1fc7a2de-c6c1-50cf-9f26-a6a8a9f1f4cb
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 ensure_collector_staged@body/5；节点在本工作流中静态 disabled。
                # unilab:node_uuid=f33eb585-466c-5ce5-937f-7edfe43af91b disabled=true
                projected_control_0007 = material.review_control_node_v1(
                    operation_name='ensure_collector_staged',
                    node_path='body/5',
                    control_kind='assign',
                    expected_sha256='80038b1850b9abbfa9ddc48239e7e240f9dc013796291b091335ff8bb6625419',
                )
            # [CONTROL if] 来源 ensure_collector_staged@body/6；原节点 {"cond":{"binop":"!=","left":{"var":"op"},"right":{"lit":"NONE"}},"op":"if","then":[{"op":"comment","text":"要动整板才切工具2大夹爪 (NONE 复用时全程不换刀, 也不进货架区)"},{"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"},{"cond":{"binop":"==","left":{"var":"op"},"right":{"lit":"SWAP"}},"op":"if","the...
            # unilab:node_uuid=461eaf67-8bf4-586f-a27d-508d435a647a
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 ensure_collector_staged@body/6；节点在本工作流中静态 disabled。
                # unilab:node_uuid=072b8d09-5820-5095-ae3a-9a8be5c9912b disabled=true
                projected_control_0008 = material.review_control_node_v1(
                    operation_name='ensure_collector_staged',
                    node_path='body/6',
                    control_kind='if',
                    expected_sha256='2f96e2815b391809df61d7fae0211fa194970aa2d2170f8033e708ba69837b69',
                )
                # [BRANCH THEN（互斥分支）] ensure_collector_staged@body/6/then 的静态审阅分支。
                # unilab:node_uuid=1e1356a3-934c-5abc-b31c-d45f6b85dfeb
                with group(name='THEN（互斥分支）'):
                    # [CONTROL comment] 来源 ensure_collector_staged@body/6/then/0；原节点 {"op":"comment","text":"要动整板才切工具2大夹爪 (NONE 复用时全程不换刀, 也不进货架区)"}
                    # unilab:node_uuid=dd748a9f-2253-511a-a009-74a44c7854e3
                    with group(name='说明 · 要动整板才切工具2大夹爪 (NONE 复用时全程不换刀, 也不进货架区)'):
                        # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/6/then/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=a8d3c29f-4b25-5844-a354-d6fcfd3a59f2 disabled=true
                        projected_control_0009 = material.review_control_node_v1(
                            operation_name='ensure_collector_staged',
                            node_path='body/6/then/0',
                            control_kind='comment',
                            expected_sha256='9eb63c0c84887a794ac9bb5a9b24241a3e243341286c731d6087fb89649fb8a6',
                        )
                    # [SUBWORKFLOW robot_tool_ensure] 由 ensure_collector_staged@body/6/then/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=aeaed079-8ee6-5c07-a9e6-e5b7d7c0ecd2
                    with group(name='↳ robot_tool_ensure'):
                        # [CONTROL comment] 来源 robot_tool_ensure@body/0；原节点 {"op":"comment","text":"读权威工具态 (mounted_tool 启动已从状态文件恢复","回显在 tool_state.mounted_tool)":null}
                        # unilab:node_uuid=65781c0c-3ca8-546c-9835-5028c252e439
                        with group(name='说明 · 读权威工具态 (mounted_tool 启动已从状态文件恢复'):
                            # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=ceb4af83-9545-536b-bbd7-f30a15d93d8a disabled=true
                            projected_control_0010 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/0',
                                control_kind='comment',
                                expected_sha256='d809e1de31eaaae6a28b91dfdc9f8587e53c48ce272668a1d7794e15c68d86f9',
                            )
                        # [ACTION robot.query] 来源 robot_tool_ensure@body/1；原节点 {"action":"robot.query","assign":{"var":"fb"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bfbf598e-e17f-555a-b8ef-a94a5f67bedc disabled=true
                        projected_action_0011 = robot.query()
                        # [CONTROL assign] 来源 robot_tool_ensure@body/2；原节点 {"op":"assign","target":{"var":"current"},"value":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"mounted_tool"}}
                        # unilab:node_uuid=e021a31a-2833-55fb-9ce3-72204bba98c7
                        with group(name='变量赋值'):
                            # [VERIFY assign] 只读来源校验 robot_tool_ensure@body/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=d738fc14-65cb-5ecd-965e-cbedd8ff7c0a disabled=true
                            projected_control_0012 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/2',
                                control_kind='assign',
                                expected_sha256='0a8bed4ab1ed21eab44aa30c3cdc41f38a8147534c728fa885ef1da0ba3237c7',
                            )
                        # [CONTROL if] 来源 robot_tool_ensure@body/3；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"var":"needed"}},"op":"if","then":[{"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"},{"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"},{"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"r...
                        # unilab:node_uuid=0e2fc826-4951-5314-9f75-13d095b95d6c
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=3064e498-7619-5425-a24b-c68ea1b48a2a disabled=true
                            projected_control_0013 = material.review_control_node_v1(
                                operation_name='robot_tool_ensure',
                                node_path='body/3',
                                control_kind='if',
                                expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                            )
                            # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then 的静态审阅分支。
                            # unilab:node_uuid=92665661-cff3-5fd6-bd66-326963474854
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/0；原节点 {"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"}
                                # unilab:node_uuid=f7f42c3b-9958-59c8-a7cb-4ee9010f877d
                                with group(name='说明 · 当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标'):
                                    # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=b3ca6759-01a3-5875-938d-cb957645a5fb disabled=true
                                    projected_control_0014 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/0',
                                        control_kind='comment',
                                        expected_sha256='f1c1621fc9a3af0fead9abddfba4acc6d628c4e07f02d5e1d6e79342f780d4b5',
                                    )
                                # [CONTROL comment] 来源 robot_tool_ensure@body/3/then/1；原节点 {"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"}
                                # unilab:node_uuid=47cb6be4-4f62-5015-976f-f5d85eff374e
                                with group(name='说明 · 卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止'):
                                    # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/1；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=8ee1694d-c972-5e9f-ac27-6c54918b78e1 disabled=true
                                    projected_control_0015 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/1',
                                        control_kind='comment',
                                        expected_sha256='ab6b298fa1974e89ffba98e42a169ccd9b213ac1a03a6723584be2b1be7e6898',
                                    )
                                # [CONTROL if] 来源 robot_tool_ensure@body/3/then/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"right":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"suction_on"}},"op":"if","then":[{"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}]}
                                # unilab:node_uuid=7bb3b73b-c3a6-516b-9331-6f29d8d8bac3
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=97b88bf2-3449-50ef-b6be-d24dd1a52b77 disabled=true
                                    projected_control_0016 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/2',
                                        control_kind='if',
                                        expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/2/then 的静态审阅分支。
                                    # unilab:node_uuid=df42b222-0d0e-52a9-be9a-66fe7bfeb596
                                    with group(name='THEN（互斥分支）'):
                                        # [CONTROL raise] 来源 robot_tool_ensure@body/3/then/2/then/0；原节点 {"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}
                                        # unilab:node_uuid=a3dfe4f2-a652-5143-9eb5-99a3bf79c878
                                        with group(name='抛出流程错误'):
                                            # [VERIFY raise] 只读来源校验 robot_tool_ensure@body/3/then/2/then/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=3b69ec52-9b04-5c17-bee2-bedf97a1a18d disabled=true
                                            projected_control_0017 = material.review_control_node_v1(
                                                operation_name='robot_tool_ensure',
                                                node_path='body/3/then/2/then/0',
                                                control_kind='raise',
                                                expected_sha256='8ade635dfc3c21601ac8fa50ba7a168191332f67cbf70e021465f2765df9b23f',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/2/else 的静态审阅分支。
                                    # unilab:node_uuid=cc441275-024d-5b86-8adc-163d411c44fc
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=bef51443-0294-5f22-84b0-5e52c0f7e2a6 disabled=true
                                        projected_control_0018 = material.review_control_node_v1(
                                            operation_name='robot_tool_ensure',
                                            node_path='body/3/then/2',
                                            control_kind='if',
                                            expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                                        )
                                # [SUBWORKFLOW rail_move_safe] 由 robot_tool_ensure@body/3/then/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                # unilab:node_uuid=364b9a25-9b5c-546d-9cc0-625bc564c1c6
                                with group(name='↳ rail_move_safe'):
                                    # [CONTROL comment] 来源 rail_move_safe@body/0；原节点 {"op":"comment","text":"确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)"}
                                    # unilab:node_uuid=48cdfb7f-4acb-514d-9310-91cdc21e94d1
                                    with group(name='说明 · 确保机械臂在安全位 P1 (安全邻域内自动回零; 邻域外/持真空停流程)'):
                                        # [VERIFY comment] 只读来源校验 rail_move_safe@body/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=6d0f1c4d-0550-54ec-872a-cff0097e947d disabled=true
                                        projected_control_0019 = material.review_control_node_v1(
                                            operation_name='rail_move_safe',
                                            node_path='body/0',
                                            control_kind='comment',
                                            expected_sha256='cc629ec60964ec74a746185851e52069f3b991388ab52755ebea4f3b92ed1740',
                                        )
                                    # [ACTION robot.home_ensure] 来源 rail_move_safe@body/1；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e96aec66-b6f1-514e-bf42-186dfcb94534 disabled=true
                                    projected_action_0020 = robot.home_ensure()
                                    # [CONTROL comment] 来源 rail_move_safe@body/2；原节点 {"op":"comment","text":"安全位确认 -> 移动地轨到目标位"}
                                    # unilab:node_uuid=0c9fa26a-64d1-5717-acd0-d7a5a1e7e583
                                    with group(name='说明 · 安全位确认 -> 移动地轨到目标位'):
                                        # [VERIFY comment] 只读来源校验 rail_move_safe@body/2；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=ab91322e-23b7-5b71-b314-938aaf8ebc2f disabled=true
                                        projected_control_0021 = material.review_control_node_v1(
                                            operation_name='rail_move_safe',
                                            node_path='body/2',
                                            control_kind='comment',
                                            expected_sha256='38f90a43c3043b67cd1207e8d94cd7c595a01ab69567c39518284d36ecb68702',
                                        )
                                    # [ACTION rail.move] 来源 rail_move_safe@body/3；原节点 {"action":"rail.move","args":{"Rail_Target_Position":{"var":"target"}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=1b252e11-8ce4-5d09-b0cb-568c064724ab disabled=true
                                    projected_action_0022 = rail.move(
                                        Rail_Target_Position=1,
                                    )
                                # [CONTROL if] 来源 robot_tool_ensure@body/3/then/4；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"lit":0}},"op":"if","then":[{"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}]}
                                # unilab:node_uuid=9f083b30-f5f6-5596-b163-ae914bddf807
                                with group(name='◇ IF 条件（PlatformUI 判定）'):
                                    # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=74e43296-d8fb-564a-b44f-0862b0b6548a disabled=true
                                    projected_control_0023 = material.review_control_node_v1(
                                        operation_name='robot_tool_ensure',
                                        node_path='body/3/then/4',
                                        control_kind='if',
                                        expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                    )
                                    # [BRANCH THEN（互斥分支）] robot_tool_ensure@body/3/then/4/then 的静态审阅分支。
                                    # unilab:node_uuid=0348e1bd-9e81-568d-9aa8-d9408465fa14
                                    with group(name='THEN（互斥分支）'):
                                        # [SUBWORKFLOW robot_tool_put] 由 robot_tool_ensure@body/3/then/4/then/0 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                        # unilab:node_uuid=dc2cc4da-fa05-5d52-b743-17933bfce21e
                                        with group(name='↳ robot_tool_put'):
                                            # [FLATTENED CONTROL if] 只读来源校验 robot_tool_put@body/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=e1dc7bae-6626-5198-9026-86c97db09471 disabled=true
                                            projected_control_0024 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0',
                                                control_kind='if',
                                                expected_sha256='9c64b805f035e287559b6a10c2883f201fed2852028900bfd6c9c7526352d298',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c2452b12-9fae-5055-92ce-7c1395dd563d disabled=true
                                            projected_action_0025 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8a6b7fa7-c779-50c3-b67a-5ef242dad356 disabled=true
                                            projected_action_0026 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"rotary-down"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=92146f2d-49a0-5cca-af14-e177a5aa5270 disabled=true
                                            projected_action_0027 = robot.tool_action(
                                                action='rotary-down',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=62884094-c89d-5c55-ab26-355c3bcf9c12 disabled=true
                                            projected_action_0028 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-on"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1baa329b-e788-58bd-8ffe-186d17508ec5 disabled=true
                                            projected_action_0029 = robot.tool_action(
                                                action='tool-change-aux-on',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d276c22f-0677-5288-b293-e94afcb6640e disabled=true
                                            projected_action_0030 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=50efdeea-0d1a-51ec-be80-107bfb878ae7 disabled=true
                                            projected_action_0031 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2998729c-6e9c-524e-b40f-0c027df91aa6 disabled=true
                                            projected_action_0032 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b6a82e10-e27b-5903-9fcc-508c1e28bc05 disabled=true
                                            projected_action_0033 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/then/9；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1dcecf30-615a-5c2b-8606-f1bb2e15401b disabled=true
                                            projected_action_0034 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/then/10；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0392d8ad-be10-5c34-b874-caed6e69ff1d disabled=true
                                            projected_action_0035 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ecaf5829-87f1-5e6a-84d2-769380426eb8 disabled=true
                                            projected_action_0036 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ed8587b6-f507-5530-a908-b265a9d2f5af disabled=true
                                            projected_action_0037 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=36cc9c6e-dea5-5164-97e4-7ccfc619255e disabled=true
                                            projected_action_0038 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3123bde0-e5b0-5a51-a5c9-b7b484982b37 disabled=true
                                            projected_action_0039 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=cfa8c267-19e2-579c-aace-824bc5fd2479 disabled=true
                                            projected_action_0040 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b5d4e395-7300-51db-a48c-fde7a84b2df5 disabled=true
                                            projected_action_0041 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9af6b3f2-2a09-50d4-a1a6-70020cebc3fc disabled=true
                                            projected_action_0042 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=cfb5be60-6fb0-5743-8e1d-ded1b2fbf163 disabled=true
                                            projected_action_0043 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=62131a68-ac46-54d6-bbe1-b8bceef6c8b1 disabled=true
                                            projected_action_0044 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=05aabc71-5d02-5e2d-95b2-d75d895c6e44 disabled=true
                                            projected_action_0045 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=88954ff5-f4de-5b8f-b963-63653f9fcbc3 disabled=true
                                            projected_action_0046 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/0/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9c5d8c76-da25-59d3-a8db-355a9e55fe13 disabled=true
                                            projected_action_0047 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=59d503bd-f49f-52ba-98dc-deb4cffd1e7a disabled=true
                                            projected_action_0048 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a7314f44-60ab-5f60-97f6-5b47a7cdfb10 disabled=true
                                            projected_action_0049 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_put@body/0/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8b4c2019-dbe2-5653-9fe2-4f37db23e2a8 disabled=true
                                            projected_action_0050 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_tool_put@body/0/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":4}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=5eef7f0f-170b-53e7-bd57-8091845694a4 disabled=true
                                            projected_action_0051 = rail.ensure(
                                                Rail_Target_Position=4,
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b0c5b3f7-15cd-5494-9841-c464c169f30a disabled=true
                                            projected_action_0052 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4627523c-7548-5f3b-9d3c-2cfb15079d74 disabled=true
                                            projected_action_0053 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d6fe1f66-0282-54bd-a395-29532345c745 disabled=true
                                            projected_action_0054 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d3faa7a4-5140-5fc0-a1c2-6a3d714c2716 disabled=true
                                            projected_action_0055 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=fe04022b-2781-5a91-9ed7-19a212b89e81 disabled=true
                                            projected_action_0056 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-release"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e2efe991-6ea6-5e3e-a5c2-fc1647dc35e0 disabled=true
                                            projected_action_0057 = robot.tool_action(
                                                action='quick-change-release',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_put@body/0/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"tool-change-aux-off"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f5d506c2-a151-5f76-a7b6-3671dfece8ec disabled=true
                                            projected_action_0058 = robot.tool_action(
                                                action='tool-change-aux-off',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_put@body/0/elifs/1/body/9；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ce285047-c456-525c-b3d3-64d5dcee4b6a disabled=true
                                            projected_action_0059 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ef3699d2-74c3-5f78-8cf8-eb05f02ff3f2 disabled=true
                                            projected_action_0060 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_put@body/0/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b608513d-4940-59da-a9f0-66fa6af10c2a disabled=true
                                            projected_action_0061 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [FLATTENED CONTROL raise] 只读来源校验 robot_tool_put@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=9116859a-c588-59ca-8052-8caa4a7398ff disabled=true
                                            projected_control_0062 = material.review_control_node_v1(
                                                operation_name='robot_tool_put',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='8aa6aa6f749c6777b2a7040e04f4316dd03cc80d36de51eec476b3dbb6c6de75',
                                            )
                                    # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/then/4/else 的静态审阅分支。
                                    # unilab:node_uuid=eaba85b5-995f-5e2f-844e-8a299f723ddb
                                    with group(name='ELSE（互斥分支）'):
                                        # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/4；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=939829ef-a694-5c36-8878-7029753f4a0b disabled=true
                                        projected_control_0063 = material.review_control_node_v1(
                                            operation_name='robot_tool_ensure',
                                            node_path='body/3/then/4',
                                            control_kind='if',
                                            expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                                        )
                                # [SUBWORKFLOW robot_tool_pick] 由 robot_tool_ensure@body/3/then/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                # unilab:node_uuid=01a5a033-2b51-5b73-a021-d062ad52b63d
                                with group(name='↳ robot_tool_pick'):
                                    # [CONTROL if] 来源 robot_tool_pick@body/0；原节点 {"cond":{"binop":"==","left":{"var":"tool_id"},"right":{"lit":1}},"elifs":[{"body":[{"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"},{"action":"robot.move...
                                    # unilab:node_uuid=a9d6335c-8e17-592f-a286-4da041cdee1f
                                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                                        # [VERIFY if] 只读来源校验 robot_tool_pick@body/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=ca36007a-098d-596b-934b-0447354d666b disabled=true
                                        projected_control_0064 = material.review_control_node_v1(
                                            operation_name='robot_tool_pick',
                                            node_path='body/0',
                                            control_kind='if',
                                            expected_sha256='47a5b48eb2b065101041caadd225ef492b21028bb19039ac3a19991997da1895',
                                        )
                                        # [BRANCH THEN（互斥分支）] robot_tool_pick@body/0/then 的静态审阅分支。
                                        # unilab:node_uuid=4ba8b834-e190-54ed-aa63-085a5980f2ab
                                        with group(name='THEN（互斥分支）'):
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a92d02c4-88e1-5994-9b86-47d2ed029494 disabled=true
                                            projected_action_0065 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0ee3fc10-6933-5576-be3a-f74c81bd1522 disabled=true
                                            projected_action_0066 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b607456b-8bc9-5ad7-999b-b4597d26da6c disabled=true
                                            projected_action_0067 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/then/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0be5384d-53e0-52d4-bafe-6814c609fcf2 disabled=true
                                            projected_action_0068 = robot.tool_action(
                                                action='quick-change-lock',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/then/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":1}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f84bf774-d57e-5e1b-8d96-a4937777518c disabled=true
                                            projected_action_0069 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9c961c79-0eec-5f0c-946b-504803bfb1fc disabled=true
                                            projected_action_0070 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-1.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=360e7cd0-c904-5a7c-b0b2-12c30167b718 disabled=true
                                            projected_action_0071 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-1.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c6dd2344-b73f-5e73-a48d-d71836068200 disabled=true
                                            projected_action_0072 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/then/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=77650720-6b0f-5b76-8813-38a96d0a4bc8 disabled=true
                                            projected_action_0073 = robot.dwell(
                                                duration_ms=500,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2eb13a77-cbf7-5e5a-950b-c77bfc5dfad6 disabled=true
                                            projected_action_0074 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.home',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/then/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0bc77bdc-7998-5c77-8c2d-3949fbf79de1 disabled=true
                                            projected_action_0075 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                        # [BRANCH ELIF 1（互斥分支）] robot_tool_pick@body/0/elifs/0/body 的静态审阅分支。
                                        # unilab:node_uuid=560766ee-2384-5903-b92a-6e7748a63b6c
                                        with group(name='ELIF 1（互斥分支）'):
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=73126a22-81e7-500e-b920-5a6bd1fa958b disabled=true
                                            projected_action_0076 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=928c0bd9-45e8-52f4-9570-4fa26f9c0aac disabled=true
                                            projected_action_0077 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ee9629d4-ff66-5875-9473-9fdbb5c7787a disabled=true
                                            projected_action_0078 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/0/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4a3143e0-0263-5c71-9425-0381db52bef7 disabled=true
                                            projected_action_0079 = robot.tool_action(
                                                action='quick-change-lock',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/0/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":2}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f0be5df7-8503-5970-91fa-0495fd914e63 disabled=true
                                            projected_action_0080 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=32200646-f19a-579f-9498-70b8cbceeb6a disabled=true
                                            projected_action_0081 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-2.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4bfba0dd-1ecc-5354-87b6-6517f37fd2f5 disabled=true
                                            projected_action_0082 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-2.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=50a18e87-5829-5b75-8936-496ac14a0516 disabled=true
                                            projected_action_0083 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/0/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=740fc0d0-ccad-5e44-8075-7d3b38119073 disabled=true
                                            projected_action_0084 = robot.dwell(
                                                duration_ms=500,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=044e81a7-f47a-5cc8-b42f-1aa63a104ac9 disabled=true
                                            projected_action_0085 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.home',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/0/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d56d4848-55d2-5501-ac2e-8e53a2466ac5 disabled=true
                                            projected_action_0086 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                        # [BRANCH ELIF 2（互斥分支）] robot_tool_pick@body/0/elifs/1/body 的静态审阅分支。
                                        # unilab:node_uuid=59ed60bf-74d6-5395-92dd-ed03dbead257
                                        with group(name='ELIF 2（互斥分支）'):
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/0；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d7e24eb0-e609-52aa-b67b-ba2cbd95fe52 disabled=true
                                            projected_action_0087 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/1；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0f9e76be-20b7-5585-9e6b-f0fedabfc455 disabled=true
                                            projected_action_0088 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.target"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=853f4362-b045-5289-a6a0-457389c8fa94 disabled=true
                                            projected_action_0089 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.target',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_tool_pick@body/0/elifs/1/body/3；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"quick-change-lock"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=946bece1-2cb5-5edf-899f-0dfb30267f5d disabled=true
                                            projected_action_0090 = robot.tool_action(
                                                action='quick-change-lock',
                                            )
                                            # [ACTION robot.set_mounted_tool] 来源 robot_tool_pick@body/0/elifs/1/body/4；原节点 {"action":"robot.set_mounted_tool","args":{"tool_id":{"lit":3}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2e5fbe29-f82b-513a-9e9b-1a827dd291a9 disabled=true
                                            projected_action_0091 = robot.set_mounted_tool(
                                                tool_id='0',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0c6cc714-0c64-5c4b-ab53-84aa513bcedb disabled=true
                                            projected_action_0092 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.slot-3.approach-high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=595f07de-aea9-556d-9153-0d6c385f9f06 disabled=true
                                            projected_action_0093 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.slot-3.approach-high',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":50},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.tool-change.ready"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8464a2db-ca7f-5984-ae00-53fb6b04f401 disabled=true
                                            projected_action_0094 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.tool-change.ready',
                                            )
                                            # [ACTION robot.dwell] 来源 robot_tool_pick@body/0/elifs/1/body/8；原节点 {"action":"robot.dwell","args":{"duration_ms":{"lit":500}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4f4d30e0-d5ad-5b38-90ad-d20066502885 disabled=true
                                            projected_action_0095 = robot.dwell(
                                                duration_ms=500,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_tool_pick@body/0/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"robot-main.home"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6c781418-268b-560b-b510-43029f95518b disabled=true
                                            projected_action_0096 = robot.move_to_point(
                                                point_id_or_robot_name='robot-main.home',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_tool_pick@body/0/elifs/1/body/10；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2},"point_id":{"lit":"robot-main.home"},"pos_tol_mm":{"lit":5},"rot_tol_deg":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=debd5fd6-910c-51be-ad45-b4603ff9dbd0 disabled=true
                                            projected_action_0097 = robot.require_anchor(
                                                point_id='robot-main.home',
                                            )
                                        # [BRANCH ELSE（互斥分支）] robot_tool_pick@body/0/else 的静态审阅分支。
                                        # unilab:node_uuid=e724ec05-f6a7-5ae1-bd9f-02bb4cac666b
                                        with group(name='ELSE（互斥分支）'):
                                            # [FLATTENED CONTROL raise] 只读来源校验 robot_tool_pick@body/0/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=4e28fff2-6dca-579f-89b9-3bb4838afb7c disabled=true
                                            projected_control_0098 = material.review_control_node_v1(
                                                operation_name='robot_tool_pick',
                                                node_path='body/0/else/0',
                                                control_kind='raise',
                                                expected_sha256='70c2a7e291023e9375102dc659639ba2604e87ffa8a3a94cca033c80b83c21e8',
                                            )
                            # [BRANCH ELSE（互斥分支）] robot_tool_ensure@body/3/else 的静态审阅分支。
                            # unilab:node_uuid=99509847-3762-558c-a313-12329e453e88
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=6c12a05f-98b7-5ad2-b0a9-f105be49429e disabled=true
                                projected_control_0099 = material.review_control_node_v1(
                                    operation_name='robot_tool_ensure',
                                    node_path='body/3',
                                    control_kind='if',
                                    expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
                                )
                    # [CONTROL if] 来源 ensure_collector_staged@body/6/then/2；原节点 {"cond":{"binop":"==","left":{"var":"op"},"right":{"lit":"SWAP"}},"op":"if","then":[{"op":"comment","text":"SWAP: 先把耗尽的中转板送回它载入时的那个货架库位 (账本据此比对, 不一致会告警留痕)"},{"inputs":{"slot_id":{"var":"old_rack_slot"}},"op":"run_script","outputs":{},"script":"transfer_collector_staging_a_to_rack"}]}
                    # unilab:node_uuid=4235ddba-5310-525f-aa05-181095be4c80
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 ensure_collector_staged@body/6/then/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=e8d96111-fa2d-566d-ba93-66fb3aa6d447 disabled=true
                        projected_control_0100 = material.review_control_node_v1(
                            operation_name='ensure_collector_staged',
                            node_path='body/6/then/2',
                            control_kind='if',
                            expected_sha256='3dc081f354285e007817d557717334f4f98825aa201abf5a11bece7e6845765d',
                        )
                        # [BRANCH THEN（互斥分支）] ensure_collector_staged@body/6/then/2/then 的静态审阅分支。
                        # unilab:node_uuid=ab8851a7-4ba8-5e38-a821-d8018ee92160
                        with group(name='THEN（互斥分支）'):
                            # [CONTROL comment] 来源 ensure_collector_staged@body/6/then/2/then/0；原节点 {"op":"comment","text":"SWAP: 先把耗尽的中转板送回它载入时的那个货架库位 (账本据此比对, 不一致会告警留痕)"}
                            # unilab:node_uuid=c339a44e-a9ca-5d2d-9d1a-84a7a8a3a35c
                            with group(name='说明 · SWAP: 先把耗尽的中转板送回它载入时的那个货架库位 (账本据此比对, 不一致会告警留痕)'):
                                # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/6/then/2/then/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=f458630c-05d0-5f14-b91f-a95cb6f14b8b disabled=true
                                projected_control_0101 = material.review_control_node_v1(
                                    operation_name='ensure_collector_staged',
                                    node_path='body/6/then/2/then/0',
                                    control_kind='comment',
                                    expected_sha256='c0c1292e472751a26c8277757f093045ebc33db595b5a85a1d33c6ea2c602b67',
                                )
                            # [SUBWORKFLOW transfer_collector_staging_a_to_rack] 由 ensure_collector_staged@body/6/then/2/then/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                            # unilab:node_uuid=96c5471b-116f-5ae6-a926-062eee9f4de3
                            with group(name='↳ transfer_collector_staging_a_to_rack'):
                                # [CONTROL comment] 来源 transfer_collector_staging_a_to_rack@body/0；原节点 {"op":"comment","text":"取板前先松开中转A定位气缸 (自守卫: 夹紧态下拔整板会顶坏气缸/托盘); 取毕保持松开, 区已空不夹空气"}
                                # unilab:node_uuid=322864be-7c7f-5564-898c-f8798bc952ba
                                with group(name='说明 · 取板前先松开中转A定位气缸 (自守卫: 夹紧态下拔整板会顶坏气缸/托盘); 取毕保持松开, 区已空不夹空气'):
                                    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_rack@body/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=14493adc-38b8-5d3b-94ab-678105acda5a disabled=true
                                    projected_control_0102 = material.review_control_node_v1(
                                        operation_name='transfer_collector_staging_a_to_rack',
                                        node_path='body/0',
                                        control_kind='comment',
                                        expected_sha256='0c10039e98bd8fb1a2969f4083e2000c186846b533c5996087ed1cc70ba97630',
                                    )
                                # [ACTION staging_a.locator_a] 来源 transfer_collector_staging_a_to_rack@body/1；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=ced76705-daf2-5054-9390-208a8a610a18 disabled=true
                                projected_action_0103 = staging_a.locator_a(
                                    target=False,
                                )
                                # [CONTROL comment] 来源 transfer_collector_staging_a_to_rack@body/2；原节点 {"op":"comment","text":"从中转A取收集器整板(位3=350","金标准; 点 P39@位3) —— 地轨由 robot_group_staging_pick enter 处 rail.ensure(3) 自动到位":null}
                                # unilab:node_uuid=e48756d6-2fc0-584b-9d50-996d2ce60a2b
                                with group(name='说明 · 从中转A取收集器整板(位3=350'):
                                    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_rack@body/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=6bf042a9-b67f-5334-8a06-417d27952d88 disabled=true
                                    projected_control_0104 = material.review_control_node_v1(
                                        operation_name='transfer_collector_staging_a_to_rack',
                                        node_path='body/2',
                                        control_kind='comment',
                                        expected_sha256='f127149c514311bedab2c37bf177730410d185721eed531480f52e5945b1885b',
                                    )
                                # [SUBWORKFLOW robot_group_staging_pick] 由 transfer_collector_staging_a_to_rack@body/3 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                # unilab:node_uuid=59e69496-fd59-531f-9512-b803bf825742
                                with group(name='↳ robot_group_staging_pick'):
                                    # [CONTROL comment] 来源 robot_group_staging_pick@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (大夹爪)"}
                                    # unilab:node_uuid=c9cfdb93-c4e7-5b45-b3ef-d0253a6000e2
                                    with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (大夹爪)'):
                                        # [VERIFY comment] 只读来源校验 robot_group_staging_pick@body/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=4d1438ad-329b-5946-a509-1609b9eb4ad0 disabled=true
                                        projected_control_0105 = material.review_control_node_v1(
                                            operation_name='robot_group_staging_pick',
                                            node_path='body/0',
                                            control_kind='comment',
                                            expected_sha256='e39d4d29dad9ddaeb2a8577b39843afb69f527adda4225bc7355c38ab532c9fe',
                                        )
                                    # [ACTION robot.home_ensure] 来源 robot_group_staging_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                                    # unilab:node_uuid=9630f1ba-86eb-52a9-b396-80e129a0259e disabled=true
                                    projected_action_0106 = robot.home_ensure()
                                    # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_group_staging_pick@body/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=cac0cec3-b2c1-53f3-8798-d48cbdb6d200 disabled=true
                                    projected_control_0107 = material.review_control_node_v1(
                                        operation_name='robot_group_staging_pick',
                                        node_path='body/2',
                                        control_kind='run_script',
                                        expected_sha256='ba9d83e2dd6420a262ad94775a61abaaba8af3a4bf2d4fef774c9f4fa825eb81',
                                    )
                                    # [CONTROL if] 来源 robot_group_staging_pick@body/3；原节点 {"cond":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position...
                                    # unilab:node_uuid=c0410227-948f-5c39-bee4-5c1d0f76c43f
                                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                                        # [VERIFY if] 只读来源校验 robot_group_staging_pick@body/3；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=b2ac9f3f-e959-57ce-a035-9cb3957824da disabled=true
                                        projected_control_0108 = material.review_control_node_v1(
                                            operation_name='robot_group_staging_pick',
                                            node_path='body/3',
                                            control_kind='if',
                                            expected_sha256='ad662023165e753aaeebc11cbd97f36159d4c68805a11312c8cd86a5cf1fe4e8',
                                        )
                                        # [BRANCH THEN（互斥分支）] robot_group_staging_pick@body/3/then 的静态审阅分支。
                                        # unilab:node_uuid=aa5c9fc4-29b0-5e8a-a44c-61a14d86f27d
                                        with group(name='THEN（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_staging_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ee1ccdaa-721f-5f28-9056-3b3b6062120e disabled=true
                                            projected_action_0109 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_staging_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2a1fdab9-410e-5a3a-8a8f-b3726b15a8ff disabled=true
                                            projected_action_0110 = rail.ensure(
                                                Rail_Target_Position=3,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=65827bfa-b450-53a1-9da9-d91ea3a68ce3 disabled=true
                                            projected_action_0111 = robot.move_to_point(
                                                point_id_or_robot_name='P4',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3a21b749-2ff6-526d-a78d-c0a897b62072 disabled=true
                                            projected_action_0112 = robot.move_to_point(
                                                point_id_or_robot_name='collector-group-staging-pick.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b10574ec-8652-513c-940f-408a61ee1186 disabled=true
                                            projected_action_0113 = robot.move_to_point(
                                                point_id_or_robot_name='collector-group-staging-pick.mid',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_staging_pick@body/3/then/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a512ece4-7199-57c9-8c92-bed15d326f39 disabled=true
                                            projected_action_0114 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6a0e7782-b159-5537-8908-1a72ca1e609a disabled=true
                                            projected_action_0115 = robot.move_to_point(
                                                point_id_or_robot_name='collector-group-staging-pick.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P39"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=091583ce-9faa-5f81-ad47-9f8618b3edd4 disabled=true
                                            projected_action_0116 = robot.move_to_point(
                                                point_id_or_robot_name='P39',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_staging_pick@body/3/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=33493a8e-f5d7-5454-ad87-443724b3b107 disabled=true
                                            projected_action_0117 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c4a3e481-445c-5809-8b5f-f476c04a9f36 disabled=true
                                            projected_action_0118 = robot.move_to_point(
                                                point_id_or_robot_name='collector-group-staging-pick.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8d5f3385-60df-50ac-8183-0e5eed59576a disabled=true
                                            projected_action_0119 = robot.move_to_point(
                                                point_id_or_robot_name='collector-group-staging-pick.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=458d2b98-691c-52ee-aa74-5439bbd7bd4d disabled=true
                                            projected_action_0120 = robot.move_to_point(
                                                point_id_or_robot_name='collector-group-staging-pick.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=70bda610-795a-542b-8ae8-254270047abf disabled=true
                                            projected_action_0121 = robot.move_to_point(
                                                point_id_or_robot_name='P4',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f56db14e-9343-548d-b95b-9471a14bc295 disabled=true
                                            projected_action_0122 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_staging_pick@body/3/then/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b153c138-0f44-5a8f-9c1c-f1e744b3fa73 disabled=true
                                            projected_action_0123 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 1（互斥分支）] robot_group_staging_pick@body/3/elifs/0/body 的静态审阅分支。
                                        # unilab:node_uuid=04b57034-2f34-51a0-bf0e-d67d6f1e5bd1
                                        with group(name='ELIF 1（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_staging_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e1f0f301-c934-56b9-895a-a65db53f9c0e disabled=true
                                            projected_action_0124 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_staging_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=7c8a2cb1-6710-58ca-af5e-d892978c4db7 disabled=true
                                            projected_action_0125 = rail.ensure(
                                                Rail_Target_Position=3,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=07519cc0-e160-57d6-9f32-2d64ad2d00c8 disabled=true
                                            projected_action_0126 = robot.move_to_point(
                                                point_id_or_robot_name='P52',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f42a03f4-a53e-57a4-8bf4-879a4e9eef5f disabled=true
                                            projected_action_0127 = robot.move_to_point(
                                                point_id_or_robot_name='bottle-group-staging-pick.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=fa203833-8521-55b0-b9a0-defaf48337d6 disabled=true
                                            projected_action_0128 = robot.move_to_point(
                                                point_id_or_robot_name='bottle-group-staging-pick.mid',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_staging_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9651a9d9-d529-5a19-9190-6fad62332c16 disabled=true
                                            projected_action_0129 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=231b56b5-323d-5926-ba8e-607ad5069ff4 disabled=true
                                            projected_action_0130 = robot.move_to_point(
                                                point_id_or_robot_name='bottle-group-staging-pick.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P40"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0f7e7bba-1b0b-5c4f-ab4b-0c00e27c725f disabled=true
                                            projected_action_0131 = robot.move_to_point(
                                                point_id_or_robot_name='P40',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_staging_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b9e28cd7-2c8d-5293-bac0-873ceb8b4518 disabled=true
                                            projected_action_0132 = robot.tool_action(
                                                action='gripper-close',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e0212387-be2e-556f-a73a-7204956c414a disabled=true
                                            projected_action_0133 = robot.move_to_point(
                                                point_id_or_robot_name='bottle-group-staging-pick.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1d3e5ad2-df47-5133-b901-f8f006adfb18 disabled=true
                                            projected_action_0134 = robot.move_to_point(
                                                point_id_or_robot_name='bottle-group-staging-pick.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-pick.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1e4bcd7c-7afb-58c5-a14c-7878e36f4ae1 disabled=true
                                            projected_action_0135 = robot.move_to_point(
                                                point_id_or_robot_name='bottle-group-staging-pick.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=7340d021-c6f2-5e4f-96e7-d589941ec83f disabled=true
                                            projected_action_0136 = robot.move_to_point(
                                                point_id_or_robot_name='P52',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_staging_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=42b96af8-6071-555e-912a-10e2924ee00f disabled=true
                                            projected_action_0137 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_staging_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=12fa4604-5b39-5c1d-a4b3-13274ac9a71f disabled=true
                                            projected_action_0138 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELSE（互斥分支）] robot_group_staging_pick@body/3/else 的静态审阅分支。
                                        # unilab:node_uuid=3bf9d90b-f18b-53e1-add2-96a924faf304
                                        with group(name='ELSE（互斥分支）'):
                                            # [FLATTENED CONTROL raise] 只读来源校验 robot_group_staging_pick@body/3/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=fecc19e4-a25b-5eeb-9aa0-c73d2963fa16 disabled=true
                                            projected_control_0139 = material.review_control_node_v1(
                                                operation_name='robot_group_staging_pick',
                                                node_path='body/3/else/0',
                                                control_kind='raise',
                                                expected_sha256='d82391d1c24fbf25fc71751808512bb67a8dabf3a6c3c5860d7dad3e45bb08f1',
                                            )
                                # [CONTROL comment] 来源 transfer_collector_staging_a_to_rack@body/4；原节点 {"op":"comment","text":"放收集器组回货架(位6) —— 地轨由 robot_group_rack_put enter 处 rail.ensure(6) 自动到位"}
                                # unilab:node_uuid=421d4b9e-1a44-59da-a948-9d87bcd9bc34
                                with group(name='说明 · 放收集器组回货架(位6) —— 地轨由 robot_group_rack_put enter 处 rail.en'):
                                    # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_rack@body/4；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=19972984-aa51-5010-9809-c4049df31b18 disabled=true
                                    projected_control_0140 = material.review_control_node_v1(
                                        operation_name='transfer_collector_staging_a_to_rack',
                                        node_path='body/4',
                                        control_kind='comment',
                                        expected_sha256='62481f69228cbbb4dadcb498e8f4f7cf6dde0fc47a9d95e83b0cb2fd7cd288d9',
                                    )
                                # [SUBWORKFLOW robot_group_rack_put] 由 transfer_collector_staging_a_to_rack@body/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                                # unilab:node_uuid=32b74482-0407-5a55-b81c-39c73050ce68
                                with group(name='↳ robot_group_rack_put'):
                                    # [CONTROL comment] 来源 robot_group_rack_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (大夹爪)"}
                                    # unilab:node_uuid=df556815-4b5e-58f6-9508-1640e7a03892
                                    with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (大夹爪)'):
                                        # [VERIFY comment] 只读来源校验 robot_group_rack_put@body/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=8f70412b-3413-5d29-a900-048716469e23 disabled=true
                                        projected_control_0141 = material.review_control_node_v1(
                                            operation_name='robot_group_rack_put',
                                            node_path='body/0',
                                            control_kind='comment',
                                            expected_sha256='e39d4d29dad9ddaeb2a8577b39843afb69f527adda4225bc7355c38ab532c9fe',
                                        )
                                    # [ACTION robot.home_ensure] 来源 robot_group_rack_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                                    # unilab:node_uuid=bc06939b-f3d1-5b4f-93ae-e4fb19328f92 disabled=true
                                    projected_action_0142 = robot.home_ensure()
                                    # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_group_rack_put@body/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=3db02a4b-5e0f-5aca-87d7-d8b2bd07b804 disabled=true
                                    projected_control_0143 = material.review_control_node_v1(
                                        operation_name='robot_group_rack_put',
                                        node_path='body/2',
                                        control_kind='run_script',
                                        expected_sha256='ba9d83e2dd6420a262ad94775a61abaaba8af3a4bf2d4fef774c9f4fa825eb81',
                                    )
                                    # [CONTROL if] 来源 robot_group_rack_put@body/3；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"right":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":...
                                    # unilab:node_uuid=00c84352-49ee-5f85-8b8d-9c79b7263c7c
                                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                                        # [VERIFY if] 只读来源校验 robot_group_rack_put@body/3；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=f36d563e-9a3c-5125-9c52-02af4138671b disabled=true
                                        projected_control_0144 = material.review_control_node_v1(
                                            operation_name='robot_group_rack_put',
                                            node_path='body/3',
                                            control_kind='if',
                                            expected_sha256='8f3899ceb2a6e4a73860e57bad52ae737ff82eac9663fcac51880d36fa675be3',
                                        )
                                        # [BRANCH THEN（互斥分支）] robot_group_rack_put@body/3/then 的静态审阅分支。
                                        # unilab:node_uuid=89ed80f7-2988-56ec-9803-c810dff7200a
                                        with group(name='THEN（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=998ef415-54fc-58fe-a972-105d057560d9 disabled=true
                                            projected_action_0145 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a22ff03c-1819-5e29-b13c-ed52e88f77d1 disabled=true
                                            projected_action_0146 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8e9fc0e2-d538-5211-959a-58502979d60a disabled=true
                                            projected_action_0147 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2b4cbbed-fc7d-540a-9c1d-6314f96aa804 disabled=true
                                            projected_action_0148 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p25.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6e451da5-3aff-5a83-8ae6-710e5cb09940 disabled=true
                                            projected_action_0149 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p25.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=fcf72b01-54d5-51ed-bfe7-9fd6d5577dc2 disabled=true
                                            projected_action_0150 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p25.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P25"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=7a904fc8-e84f-5df1-b4a6-3816b477249a disabled=true
                                            projected_action_0151 = robot.move_to_point(
                                                point_id_or_robot_name='P25',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=27720b77-f916-5c60-a4da-3e18decbf8c5 disabled=true
                                            projected_action_0152 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ca59fd78-7e5e-5dd9-9890-6e2c41a6ad5f disabled=true
                                            projected_action_0153 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p25.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4224786d-3b21-5569-8ee5-0d39b6ed0462 disabled=true
                                            projected_action_0154 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p25.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0eae32a3-16b5-5d62-9a4c-b85af70e4415 disabled=true
                                            projected_action_0155 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p25.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9abef7ef-b629-5288-a224-9ebd1b838664 disabled=true
                                            projected_action_0156 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c19564ca-a52f-54b7-9614-8f3924bbcb2d disabled=true
                                            projected_action_0157 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/then/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d1d52b95-11fd-5684-bc7c-756a8818488b disabled=true
                                            projected_action_0158 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 1（互斥分支）] robot_group_rack_put@body/3/elifs/0/body 的静态审阅分支。
                                        # unilab:node_uuid=3108f64b-1a25-5478-8718-05e3b07617f6
                                        with group(name='ELIF 1（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=46b32cc3-2d3b-50f8-96b1-daf89ce8a06e disabled=true
                                            projected_action_0159 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3f9a3a2c-5366-5b0b-8332-7c05f5133e9d disabled=true
                                            projected_action_0160 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c435ded6-1bc8-5cff-8044-e517d3014c8d disabled=true
                                            projected_action_0161 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=91a5d9fe-d567-515f-bef2-99601d9fe18b disabled=true
                                            projected_action_0162 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p26.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0ac98659-1bb3-5e18-abb3-c486c6087b99 disabled=true
                                            projected_action_0163 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p26.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e0e1c6d0-75d1-542a-8d14-8fc0c8aad616 disabled=true
                                            projected_action_0164 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p26.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P26"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8f466521-9957-5d34-85c1-1effdf0d2c28 disabled=true
                                            projected_action_0165 = robot.move_to_point(
                                                point_id_or_robot_name='P26',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f1ad3111-19ad-59c0-9dee-553d8fae77d5 disabled=true
                                            projected_action_0166 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=33b7951f-9c7e-5d31-8970-fdf36a9ebdb1 disabled=true
                                            projected_action_0167 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p26.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3d922615-1aaa-5504-aa88-c5bdc8a87d94 disabled=true
                                            projected_action_0168 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p26.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=039747cd-5c14-58f9-9c80-9f33dc56c31d disabled=true
                                            projected_action_0169 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p26.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=20fac516-7853-5711-aa72-d67291382a08 disabled=true
                                            projected_action_0170 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6d55381a-c0bf-5827-be7c-d303735d6e61 disabled=true
                                            projected_action_0171 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/0/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=88960f4a-f94f-575a-b338-4190c2dd249d disabled=true
                                            projected_action_0172 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 2（互斥分支）] robot_group_rack_put@body/3/elifs/1/body 的静态审阅分支。
                                        # unilab:node_uuid=e8cca072-4229-5bb3-932c-ed292488de95
                                        with group(name='ELIF 2（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=094fab51-0f97-5636-8e32-650256de70b8 disabled=true
                                            projected_action_0173 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e11e399a-7c87-5b9e-a1ce-70d9842f9327 disabled=true
                                            projected_action_0174 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1eb3ad04-6c69-5d5f-8d7d-9047e4db9079 disabled=true
                                            projected_action_0175 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=dda27081-bc02-5fa7-b8a8-04f3220283a9 disabled=true
                                            projected_action_0176 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p27.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2fb2021a-222c-544f-b9af-da3ee0afa8a8 disabled=true
                                            projected_action_0177 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p27.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=19961485-ff00-536e-ac37-45eea6e67330 disabled=true
                                            projected_action_0178 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p27.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P27"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=df71f341-05ab-543c-aaff-832b8a361c13 disabled=true
                                            projected_action_0179 = robot.move_to_point(
                                                point_id_or_robot_name='P27',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c498c6f5-30b2-5c3b-bcee-2edb07b5435b disabled=true
                                            projected_action_0180 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c1aa363e-a622-546a-8247-91502b2ae0d9 disabled=true
                                            projected_action_0181 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p27.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ba8c638b-b3d2-57b8-b3d0-0ac5bfeb9c81 disabled=true
                                            projected_action_0182 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p27.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=801abc8c-6bc8-55f2-9770-fc708923b81c disabled=true
                                            projected_action_0183 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p27.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=52531b0f-a661-5373-87f1-e464a777b30f disabled=true
                                            projected_action_0184 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/1/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ed4fbb8e-4179-5e51-ae12-8f40de23c478 disabled=true
                                            projected_action_0185 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/1/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1669eb79-17d1-55bf-bfc2-e1fad36a2ba9 disabled=true
                                            projected_action_0186 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 3（互斥分支）] robot_group_rack_put@body/3/elifs/2/body 的静态审阅分支。
                                        # unilab:node_uuid=44336789-f734-5a33-9536-ac432ee185ca
                                        with group(name='ELIF 3（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8704572c-a6e5-5ec6-adc7-811f6e4929b5 disabled=true
                                            projected_action_0187 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=99128d3b-1539-5a1d-aa0a-257d01d242ab disabled=true
                                            projected_action_0188 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=dbb492b2-78ef-5c38-b86a-7030fbab6ff0 disabled=true
                                            projected_action_0189 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=496d1d6a-6c2a-51bd-b8b4-745225c1a611 disabled=true
                                            projected_action_0190 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p28.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3730b675-b766-5781-866c-99e46e964e8d disabled=true
                                            projected_action_0191 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p28.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a497c048-1cec-54b2-8042-e3503038e33d disabled=true
                                            projected_action_0192 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p28.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P28"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3fbcd161-7960-5cb7-bc4e-f1acc75c06c3 disabled=true
                                            projected_action_0193 = robot.move_to_point(
                                                point_id_or_robot_name='P28',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/2/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8a9f3c16-65b0-54a2-8d6e-b6fc3f8faf90 disabled=true
                                            projected_action_0194 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6327e735-be76-5a2a-a38a-34ea05905571 disabled=true
                                            projected_action_0195 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p28.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ec2af06a-7aa0-5213-88de-7a976da68c8c disabled=true
                                            projected_action_0196 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p28.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=7ba3821c-c3f5-5dbc-b929-40b238937299 disabled=true
                                            projected_action_0197 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p28.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=7a4659b3-b8c6-5858-b2a2-64cb299f4846 disabled=true
                                            projected_action_0198 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/2/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6679f0dc-7c93-5367-8a91-d03646404467 disabled=true
                                            projected_action_0199 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/2/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ef8223c9-708a-5265-b608-28778679fbb7 disabled=true
                                            projected_action_0200 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 4（互斥分支）] robot_group_rack_put@body/3/elifs/3/body 的静态审阅分支。
                                        # unilab:node_uuid=87cbc84c-f447-5309-95da-16950321c2d6
                                        with group(name='ELIF 4（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=eae6e6be-7596-5c91-93b3-4d0879b1a09b disabled=true
                                            projected_action_0201 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f93a347f-0d8f-5547-8416-b8288fc0f4c5 disabled=true
                                            projected_action_0202 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=63cf2a65-e86e-578b-9a29-10cadeb4a2fa disabled=true
                                            projected_action_0203 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=41f60893-9ea9-5fd4-941b-29930d8c8baa disabled=true
                                            projected_action_0204 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p29.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4e5283e0-cc85-5aad-b399-7d074f4f40ee disabled=true
                                            projected_action_0205 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p29.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=30bd59d9-5df4-5e86-8501-715f4d6852b3 disabled=true
                                            projected_action_0206 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p29.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P29"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=dd98a71b-5f28-5453-97bb-040470936d93 disabled=true
                                            projected_action_0207 = robot.move_to_point(
                                                point_id_or_robot_name='P29',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/3/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8acc30fe-2389-5d0e-aeb0-65000d0fe6ae disabled=true
                                            projected_action_0208 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=93505ac5-90f9-57f1-afa4-e7f692999fd2 disabled=true
                                            projected_action_0209 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p29.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3d14c543-a75a-5caf-aaa4-e472227896b2 disabled=true
                                            projected_action_0210 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p29.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=cb3f6a7e-36b3-513d-9c31-03fdb9ac1966 disabled=true
                                            projected_action_0211 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p29.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=90bed354-0bee-5524-a087-f01a426de66d disabled=true
                                            projected_action_0212 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/3/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b85c30b2-00eb-505b-8ea1-68dbc53fbfa0 disabled=true
                                            projected_action_0213 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/3/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d3567300-5acf-5dd3-9c47-79d84311f53d disabled=true
                                            projected_action_0214 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 5（互斥分支）] robot_group_rack_put@body/3/elifs/4/body 的静态审阅分支。
                                        # unilab:node_uuid=58d0f88c-89bd-54b5-86ed-683b02d6b724
                                        with group(name='ELIF 5（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b63dc084-959c-5900-aec2-2df5b735e0c4 disabled=true
                                            projected_action_0215 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=81587c2b-ba85-5aa2-8734-079cd1c672c5 disabled=true
                                            projected_action_0216 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ab0a83c2-8063-5cfc-b179-5b7f9c972379 disabled=true
                                            projected_action_0217 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=846cfccf-ac1a-5766-85c3-70d62fae3ed1 disabled=true
                                            projected_action_0218 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p30.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=21fdc18d-c35c-5278-b0a8-c0bd968c6ed1 disabled=true
                                            projected_action_0219 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p30.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f743da79-73a4-59a9-9efb-3ac646af276c disabled=true
                                            projected_action_0220 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p30.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P30"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ea60af87-d43f-5f78-b244-393eec739f6d disabled=true
                                            projected_action_0221 = robot.move_to_point(
                                                point_id_or_robot_name='P30',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/4/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9b0b853a-acd6-52db-9bc1-0dbea78ebe02 disabled=true
                                            projected_action_0222 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b0803f9a-bc5e-5a59-a9ce-2dc1c378c730 disabled=true
                                            projected_action_0223 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p30.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=42607413-4326-55c6-8f55-22cae947096e disabled=true
                                            projected_action_0224 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p30.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2ed9b457-0ddb-56ed-aebb-71b24be8a0d9 disabled=true
                                            projected_action_0225 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p30.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=bbd5c028-d35d-572d-b78a-b83923758be4 disabled=true
                                            projected_action_0226 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/4/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=37528536-dec1-5303-8cf5-040c28c19f16 disabled=true
                                            projected_action_0227 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/4/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2c307dc2-5cec-5c0b-8e7e-37907e080498 disabled=true
                                            projected_action_0228 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 6（互斥分支）] robot_group_rack_put@body/3/elifs/5/body 的静态审阅分支。
                                        # unilab:node_uuid=22bacddc-ece2-5d5d-bbd1-2e8a3a0f96ce
                                        with group(name='ELIF 6（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=552cf295-e3f5-557b-95a3-af598de41b90 disabled=true
                                            projected_action_0229 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9982f243-a274-5806-9f11-aa8e8ab92237 disabled=true
                                            projected_action_0230 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=aeca94cf-c91f-54cb-b97a-1c78b5428f85 disabled=true
                                            projected_action_0231 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=02da5f94-2898-5145-82fc-0a1f2f462362 disabled=true
                                            projected_action_0232 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p31.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f57330d4-a3b0-5a5e-8e9a-3b7237b319ea disabled=true
                                            projected_action_0233 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p31.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=27cbfead-6599-5939-8160-12c0898a0b74 disabled=true
                                            projected_action_0234 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p31.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P31"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=71d069a6-27f5-5c60-afa3-8f4d15dadcd5 disabled=true
                                            projected_action_0235 = robot.move_to_point(
                                                point_id_or_robot_name='P31',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/5/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=14b4e251-9d88-59ae-bfd9-0adddd5176cf disabled=true
                                            projected_action_0236 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d33f357b-1b7f-5353-8362-f042f33fd1ef disabled=true
                                            projected_action_0237 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p31.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8e0fa66e-0f68-5135-858d-336ffcbb4161 disabled=true
                                            projected_action_0238 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p31.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0459624e-705d-5a08-ae24-20bc7eafe98f disabled=true
                                            projected_action_0239 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p31.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9ea7f6a5-7d4f-54a9-8a0c-daf6a8417a1d disabled=true
                                            projected_action_0240 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/5/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=5321bf19-f764-5404-9f0b-81c4e5fb7ba6 disabled=true
                                            projected_action_0241 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/5/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4db6474b-cb51-58e9-995c-125834b2be54 disabled=true
                                            projected_action_0242 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 7（互斥分支）] robot_group_rack_put@body/3/elifs/6/body 的静态审阅分支。
                                        # unilab:node_uuid=eb13c86f-f300-5ea9-a0ac-621670bf7cf7
                                        with group(name='ELIF 7（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=5913510d-27b1-5f94-9d59-2a5f0a639ac2 disabled=true
                                            projected_action_0243 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ef742e1b-1edb-590b-a45a-7f210545af94 disabled=true
                                            projected_action_0244 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=6c7da675-9401-5aed-ab7f-9e19b25676b4 disabled=true
                                            projected_action_0245 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=91e3394c-fb4f-574f-9d88-148fe368e341 disabled=true
                                            projected_action_0246 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p32.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e568aba5-9c0e-5fc5-9806-db841d398477 disabled=true
                                            projected_action_0247 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p32.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f4e49da9-917f-57c8-bad9-33922275a6c8 disabled=true
                                            projected_action_0248 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p32.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P32"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3876ee16-3b90-56ca-ae78-a225c2f2d6eb disabled=true
                                            projected_action_0249 = robot.move_to_point(
                                                point_id_or_robot_name='P32',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/6/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1bbd4a57-8139-5f96-a3a1-8b757ff9478e disabled=true
                                            projected_action_0250 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c91791a0-534a-59cf-ae3f-d1b014c3bc4e disabled=true
                                            projected_action_0251 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p32.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b603a257-89ce-527b-a566-645abeb4b1cb disabled=true
                                            projected_action_0252 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p32.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f724eb10-7408-59e3-90e8-c3bb5f28a7d5 disabled=true
                                            projected_action_0253 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p32.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=75897a41-b56f-5f30-b1a9-9e75a8ba03b9 disabled=true
                                            projected_action_0254 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/6/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=64dfcaed-2473-5f7e-9a90-c0d8c01a8b1b disabled=true
                                            projected_action_0255 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/6/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=edbfeb1d-52dc-5a05-a483-42f519d2e07e disabled=true
                                            projected_action_0256 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 8（互斥分支）] robot_group_rack_put@body/3/elifs/7/body 的静态审阅分支。
                                        # unilab:node_uuid=1a86ee61-4829-5f50-9b0f-110090765e7b
                                        with group(name='ELIF 8（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/7/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=9f886b43-1d75-51db-a6e7-c0d009f5fa20 disabled=true
                                            projected_action_0257 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/7/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=f93faec9-2d3f-5a11-8bd8-841cac1dcb0c disabled=true
                                            projected_action_0258 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=93af7ddb-3103-5032-b9d9-c5bbe065ba46 disabled=true
                                            projected_action_0259 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=89f30a5c-918c-5ca5-81b0-fa00e5ee34fe disabled=true
                                            projected_action_0260 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p33.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2099f35e-1656-5b37-80a1-2b8c3451bd5c disabled=true
                                            projected_action_0261 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p33.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1de38421-8b3d-5733-ab4b-dece73473a47 disabled=true
                                            projected_action_0262 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p33.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P33"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c41f9e3a-7079-513d-9b25-cdc591fb8a17 disabled=true
                                            projected_action_0263 = robot.move_to_point(
                                                point_id_or_robot_name='P33',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/7/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=503419e4-cea3-54ce-886e-df4a21a24029 disabled=true
                                            projected_action_0264 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8df6b6e9-a1fd-5f8b-b1c1-5b01ef61d06e disabled=true
                                            projected_action_0265 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p33.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=fda6bcea-f66f-5947-b2a9-46d16502db92 disabled=true
                                            projected_action_0266 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p33.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=16cbb13c-9ff4-5f85-9d8f-81db9513307b disabled=true
                                            projected_action_0267 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p33.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8ad012ad-4de2-52f3-8a43-dfa45925ca46 disabled=true
                                            projected_action_0268 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/7/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3deaa60d-3bb6-549c-8e17-704f72a81e5f disabled=true
                                            projected_action_0269 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/7/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=85955b01-45a6-5ee1-9ac1-0ec4a3b99fb4 disabled=true
                                            projected_action_0270 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 9（互斥分支）] robot_group_rack_put@body/3/elifs/8/body 的静态审阅分支。
                                        # unilab:node_uuid=9fb331a6-d116-555f-80a2-ff82bccdbaf4
                                        with group(name='ELIF 9（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/8/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=997b5ebf-3d03-5c1f-996a-97ecd7d4dfea disabled=true
                                            projected_action_0271 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/8/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e0b7c7bd-97b5-55d4-92df-dbbdabaaf47a disabled=true
                                            projected_action_0272 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4fcb4a5d-f8eb-5927-aa7b-53cee9348711 disabled=true
                                            projected_action_0273 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a987cfcb-607e-5250-950a-abf0a0cf5a4e disabled=true
                                            projected_action_0274 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p34.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=7e6e96a6-5ca9-5b36-ac3d-f47743a85ced disabled=true
                                            projected_action_0275 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p34.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=bd0c700f-1e7b-510f-9695-5f6d962ffbf9 disabled=true
                                            projected_action_0276 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p34.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P34"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=32135883-c2bf-50a1-adeb-662a878d2ecb disabled=true
                                            projected_action_0277 = robot.move_to_point(
                                                point_id_or_robot_name='P34',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/8/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4d747220-276a-5234-8232-2d1c7b37d96a disabled=true
                                            projected_action_0278 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a725b5ec-ea3d-536d-a666-21b6c997c018 disabled=true
                                            projected_action_0279 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p34.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=939af2ca-cdd9-502e-9ebd-0b698cd679b7 disabled=true
                                            projected_action_0280 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p34.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=bda9564c-5bc8-538f-8ce3-dd4e29574fed disabled=true
                                            projected_action_0281 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p34.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=c6caab47-08a8-51d0-b05d-013d53c878ae disabled=true
                                            projected_action_0282 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/8/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1e00d1b2-157b-5882-9c94-472e92f1ca9b disabled=true
                                            projected_action_0283 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/8/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1c577bfb-0060-5dd3-a548-394f11ec2436 disabled=true
                                            projected_action_0284 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 10（互斥分支）] robot_group_rack_put@body/3/elifs/9/body 的静态审阅分支。
                                        # unilab:node_uuid=f5e5bf90-4d19-517a-aa92-941b3b9143fd
                                        with group(name='ELIF 10（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/9/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=a37fa433-d6f0-5eec-84c8-86c2dac38646 disabled=true
                                            projected_action_0285 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/9/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b75f61be-8f72-526f-83da-3d214a388445 disabled=true
                                            projected_action_0286 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=625ab32f-b06a-5b14-baee-e036aa366f5f disabled=true
                                            projected_action_0287 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=e98484e9-5a17-504a-9b9e-f25724abf509 disabled=true
                                            projected_action_0288 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p35.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=87bf77e3-612a-51b7-ae00-7b252a57db77 disabled=true
                                            projected_action_0289 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p35.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=617e9494-1a3b-5253-89ec-354f43f1e89f disabled=true
                                            projected_action_0290 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p35.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P35"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=aec23539-8c85-5a22-aa1b-34216737d4de disabled=true
                                            projected_action_0291 = robot.move_to_point(
                                                point_id_or_robot_name='P35',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/9/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=7da41427-fae5-5754-bd43-c59b76664758 disabled=true
                                            projected_action_0292 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=319ce6e0-7e2a-54ec-ac87-d1a4253f5c3a disabled=true
                                            projected_action_0293 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p35.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=3d91e283-9f19-5626-82fd-aef11c788099 disabled=true
                                            projected_action_0294 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p35.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=1eedf807-81dc-54dc-9ba2-0ecebf2e879b disabled=true
                                            projected_action_0295 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p35.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=2dd5097a-93dd-59c3-a542-e7e7af2100fa disabled=true
                                            projected_action_0296 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/9/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=0a534a5c-dd0a-579c-a7e8-6da0e6edc820 disabled=true
                                            projected_action_0297 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/9/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8b0caadf-e1ad-5843-a272-d2568ff8a4a5 disabled=true
                                            projected_action_0298 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELIF 11（互斥分支）] robot_group_rack_put@body/3/elifs/10/body 的静态审阅分支。
                                        # unilab:node_uuid=fa077142-08ec-5532-96ee-39aff1561dd0
                                        with group(name='ELIF 11（互斥分支）'):
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/10/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=62492250-1194-5b0d-a2e3-29bf6decd91c disabled=true
                                            projected_action_0299 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                            # [ACTION rail.ensure] 来源 robot_group_rack_put@body/3/elifs/10/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=411e7dc5-3f26-51d3-9204-356fabf52fe0 disabled=true
                                            projected_action_0300 = rail.ensure(
                                                Rail_Target_Position=6,
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ebb4dae1-814f-5be5-8f5f-9fe3aa74f003 disabled=true
                                            projected_action_0301 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=8c25e7c5-ba24-5e69-8c09-4709add6437f disabled=true
                                            projected_action_0302 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p36.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=51b4712d-b34b-53c9-a3b8-74eaf4932ab3 disabled=true
                                            projected_action_0303 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p36.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=47b096b8-5b9d-534e-a072-49558bc5f7fb disabled=true
                                            projected_action_0304 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p36.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P36"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=95252bf6-0f27-5622-b615-7e0a83eac530 disabled=true
                                            projected_action_0305 = robot.move_to_point(
                                                point_id_or_robot_name='P36',
                                            )
                                            # [ACTION robot.tool_action] 来源 robot_group_rack_put@body/3/elifs/10/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=4aa46699-1e08-5194-8cf6-ae5ed472374a disabled=true
                                            projected_action_0306 = robot.tool_action(
                                                action='gripper-open',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=57280478-678b-5729-83b9-6c8dd7036fa5 disabled=true
                                            projected_action_0307 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p36.near',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=880e7e83-acfd-58c1-b58d-49988a2fff9a disabled=true
                                            projected_action_0308 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p36.mid',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=ab3d2671-6db2-56bf-a863-c1ce1a742c60 disabled=true
                                            projected_action_0309 = robot.move_to_point(
                                                point_id_or_robot_name='group-rack.p36.far',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=dcd89d66-c82a-5cda-bbb4-1ef84baa45ff disabled=true
                                            projected_action_0310 = robot.move_to_point(
                                                point_id_or_robot_name='P7',
                                            )
                                            # [ACTION robot.move_to_point] 来源 robot_group_rack_put@body/3/elifs/10/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=b4005003-4a1c-5b56-9e39-da6f0bbc60ab disabled=true
                                            projected_action_0311 = robot.move_to_point(
                                                point_id_or_robot_name='P1',
                                            )
                                            # [ACTION robot.require_anchor] 来源 robot_group_rack_put@body/3/elifs/10/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                            # unilab:node_uuid=d52d94e4-eb0a-5cc4-ae51-b69445598354 disabled=true
                                            projected_action_0312 = robot.require_anchor(
                                                point_id='P1',
                                            )
                                        # [BRANCH ELSE（互斥分支）] robot_group_rack_put@body/3/else 的静态审阅分支。
                                        # unilab:node_uuid=15f9e13c-7bd5-58fa-82c3-9a6f32fbd50d
                                        with group(name='ELSE（互斥分支）'):
                                            # [FLATTENED CONTROL raise] 只读来源校验 robot_group_rack_put@body/3/else/0；节点在本工作流中静态 disabled。
                                            # unilab:node_uuid=8d953eda-6f50-5b14-a43c-b799ac328569 disabled=true
                                            projected_control_0313 = material.review_control_node_v1(
                                                operation_name='robot_group_rack_put',
                                                node_path='body/3/else/0',
                                                control_kind='raise',
                                                expected_sha256='c9f6108a83b1bbb80b1623d016e1043aa8953b0ce506af4aaee0bed2ffb0d752',
                                            )
                        # [BRANCH ELSE（互斥分支）] ensure_collector_staged@body/6/then/2/else 的静态审阅分支。
                        # unilab:node_uuid=f6d392b1-1414-5860-a96b-4091f88a4c8e
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 ensure_collector_staged@body/6/then/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=0f6190b4-eb30-57f1-abae-4f68cc330514 disabled=true
                            projected_control_0314 = material.review_control_node_v1(
                                operation_name='ensure_collector_staged',
                                node_path='body/6/then/2',
                                control_kind='if',
                                expected_sha256='3dc081f354285e007817d557717334f4f98825aa201abf5a11bece7e6845765d',
                            )
                    # [CONTROL comment] 来源 ensure_collector_staged@body/6/then/3；原节点 {"op":"comment","text":"PUT_NEW / SWAP: 从货架取有料的新板进中转A, 落位后由该脚本自行夹紧"}
                    # unilab:node_uuid=79d81e1b-d909-5249-87bb-ee2672df35bd
                    with group(name='说明 · PUT_NEW / SWAP: 从货架取有料的新板进中转A, 落位后由该脚本自行夹紧'):
                        # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/6/then/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=fcb1fc3d-e886-5bbd-a7f0-54907f8162bb disabled=true
                        projected_control_0315 = material.review_control_node_v1(
                            operation_name='ensure_collector_staged',
                            node_path='body/6/then/3',
                            control_kind='comment',
                            expected_sha256='c1887bba9d6e94a5dfbb91ca44b16ad6490e4b728e9795af9b12ffdf733dffd7',
                        )
                    # [SUBWORKFLOW transfer_collector_rack_to_staging_a] 由 ensure_collector_staged@body/6/then/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=ecee072d-30fb-5966-b065-fb80fe94b27d
                    with group(name='↳ transfer_collector_rack_to_staging_a'):
                        # [CONTROL comment] 来源 transfer_collector_rack_to_staging_a@body/0；原节点 {"op":"comment","text":"从货架(位6)取收集器组 —— 地轨由 robot_group_rack_pick enter 处 rail.ensure(6) 自动到位"}
                        # unilab:node_uuid=a181b1ae-92f9-55fa-b6c4-264ad4f50a74
                        with group(name='说明 · 从货架(位6)取收集器组 —— 地轨由 robot_group_rack_pick enter 处 rail.e'):
                            # [VERIFY comment] 只读来源校验 transfer_collector_rack_to_staging_a@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=22a14c8f-b215-5573-8b93-d19ddb33f40a disabled=true
                            projected_control_0316 = material.review_control_node_v1(
                                operation_name='transfer_collector_rack_to_staging_a',
                                node_path='body/0',
                                control_kind='comment',
                                expected_sha256='ad0cf7d202cfd46e6424db1fa1b2a4eebf41360fc16b8113ca52354653205ab2',
                            )
                        # [SUBWORKFLOW robot_group_rack_pick] 由 transfer_collector_rack_to_staging_a@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                        # unilab:node_uuid=ca5f3b5b-5eba-5e4b-a455-6e4af356850c
                        with group(name='↳ robot_group_rack_pick'):
                            # [CONTROL comment] 来源 robot_group_rack_pick@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (大夹爪)"}
                            # unilab:node_uuid=f896ab1a-65e4-5a65-a93e-5637b12b699f
                            with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (大夹爪)'):
                                # [VERIFY comment] 只读来源校验 robot_group_rack_pick@body/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=c6ac71a3-b4f3-58be-9f55-d0f2801d4c02 disabled=true
                                projected_control_0317 = material.review_control_node_v1(
                                    operation_name='robot_group_rack_pick',
                                    node_path='body/0',
                                    control_kind='comment',
                                    expected_sha256='e39d4d29dad9ddaeb2a8577b39843afb69f527adda4225bc7355c38ab532c9fe',
                                )
                            # [ACTION robot.home_ensure] 来源 robot_group_rack_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                            # unilab:node_uuid=2b4e9cf1-77c8-5b2f-99f5-6eeafa091d85 disabled=true
                            projected_action_0318 = robot.home_ensure()
                            # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_group_rack_pick@body/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=e7e54f92-24e8-51d4-a676-42e29c93058b disabled=true
                            projected_control_0319 = material.review_control_node_v1(
                                operation_name='robot_group_rack_pick',
                                node_path='body/2',
                                control_kind='run_script',
                                expected_sha256='ba9d83e2dd6420a262ad94775a61abaaba8af3a4bf2d4fef774c9f4fa825eb81',
                            )
                            # [CONTROL if] 来源 robot_group_rack_pick@body/3；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"right":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit"...
                            # unilab:node_uuid=aeab9b96-d938-54e7-a17e-8e53aff71b69
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_group_rack_pick@body/3；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=3a56a0c6-2781-532d-962f-d2df25a7aabf disabled=true
                                projected_control_0320 = material.review_control_node_v1(
                                    operation_name='robot_group_rack_pick',
                                    node_path='body/3',
                                    control_kind='if',
                                    expected_sha256='c443e7f9e714f9c17db4a6ab5e3d774e059705b154d55a1816b41ecd71584664',
                                )
                                # [BRANCH THEN（互斥分支）] robot_group_rack_pick@body/3/then 的静态审阅分支。
                                # unilab:node_uuid=19d85808-67d7-570b-aeba-406d4f7ca3e6
                                with group(name='THEN（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=ad6bd531-81a8-5116-ba86-28ac23ae0145 disabled=true
                                    projected_action_0321 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=860506da-6e83-5b53-8f70-8842fbe8d2fc disabled=true
                                    projected_action_0322 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=53884160-67cd-55d7-9bef-eb5ee46b4772 disabled=true
                                    projected_action_0323 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=163e3905-b829-51d8-8cd2-a2ad97705ca3 disabled=true
                                    projected_action_0324 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p25.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=af2f7bb5-a054-552e-a958-b89b450b08aa disabled=true
                                    projected_action_0325 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p25.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/then/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=cabfca4a-db81-529f-b31c-6e397d5ca345 disabled=true
                                    projected_action_0326 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a064a311-459a-5674-822e-70866c16f42c disabled=true
                                    projected_action_0327 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p25.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P25"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=963a20b2-f015-54d4-b2d6-8b8a1bdaf0a2 disabled=true
                                    projected_action_0328 = robot.move_to_point(
                                        point_id_or_robot_name='P25',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/then/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=add91083-c170-5279-8e88-d04ded6a4824 disabled=true
                                    projected_action_0329 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0ad7df99-5222-5cb1-aae1-25711990ee43 disabled=true
                                    projected_action_0330 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p25.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0fe0bf1e-03bf-5d10-a094-ae42fe073ea9 disabled=true
                                    projected_action_0331 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p25.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p25.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=bba47f6b-31a5-59a9-b9ba-4a8f4ce55eae disabled=true
                                    projected_action_0332 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p25.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=50b53950-f095-53af-bc49-a4447149576a disabled=true
                                    projected_action_0333 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/then/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f364d397-113d-578b-824b-35adde2eef12 disabled=true
                                    projected_action_0334 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/then/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=4c6a53a4-1f5b-5891-802f-e28a98bab34c disabled=true
                                    projected_action_0335 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 1（互斥分支）] robot_group_rack_pick@body/3/elifs/0/body 的静态审阅分支。
                                # unilab:node_uuid=239f8179-8ede-5d1f-bd3b-3efb13877c7b
                                with group(name='ELIF 1（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d2a5a394-beb9-590c-be57-f187f65d10da disabled=true
                                    projected_action_0336 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=caeb910a-b097-56f8-967f-975bff040be0 disabled=true
                                    projected_action_0337 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=1f9dfb6c-2889-55e4-8023-a4d56b6f948c disabled=true
                                    projected_action_0338 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=6b6370ba-6aff-5a9c-be73-62d6ad8876d6 disabled=true
                                    projected_action_0339 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p26.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=4315ee1e-ac5c-5530-9d14-892b4eaa63ab disabled=true
                                    projected_action_0340 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p26.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0e0cce63-018e-5be8-aaee-abcc322c01ec disabled=true
                                    projected_action_0341 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=71179027-c1ec-51e9-a8d2-fd85441794e2 disabled=true
                                    projected_action_0342 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p26.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P26"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=ed18e984-c0e6-5baf-8cde-b5a0590fdd70 disabled=true
                                    projected_action_0343 = robot.move_to_point(
                                        point_id_or_robot_name='P26',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=415b6356-2a1f-570a-8974-afd01bde58a4 disabled=true
                                    projected_action_0344 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=35bfee6d-ec06-590d-9b2c-50b895fecb7f disabled=true
                                    projected_action_0345 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p26.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2c2b1051-7484-5604-9e92-b140f346bcc3 disabled=true
                                    projected_action_0346 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p26.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p26.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a9476da4-3b3a-591e-b8c6-2f12776e70c6 disabled=true
                                    projected_action_0347 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p26.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0d4c326d-ec78-5e89-b2b5-716dbadc83d9 disabled=true
                                    projected_action_0348 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/0/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3e33c64f-1182-5bfd-aded-e83ced04a97e disabled=true
                                    projected_action_0349 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/0/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=23c706b8-b734-5a78-a7c4-84ae5ab6e83d disabled=true
                                    projected_action_0350 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 2（互斥分支）] robot_group_rack_pick@body/3/elifs/1/body 的静态审阅分支。
                                # unilab:node_uuid=77ddddf3-6947-574f-833a-b4aa8d4ca23f
                                with group(name='ELIF 2（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=6341d761-37b2-5822-b963-92f99cf71067 disabled=true
                                    projected_action_0351 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e6e56573-d7fa-5fa1-a77d-fd10aeb6e7f5 disabled=true
                                    projected_action_0352 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=4d3b0677-d3cf-5e82-9b36-dd9ab7ebadef disabled=true
                                    projected_action_0353 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=5944d0ce-2680-5504-b8a2-bfa8c7c4b6ba disabled=true
                                    projected_action_0354 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p27.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=502c9470-0d28-52de-9a47-834b9210ef63 disabled=true
                                    projected_action_0355 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p27.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/1/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=828e2eaf-6056-59b4-94e3-91686f1adb4a disabled=true
                                    projected_action_0356 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=341034ce-f461-5efb-a158-5728292b0601 disabled=true
                                    projected_action_0357 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p27.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P27"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=03760e7c-23f1-522e-85be-7bc75ca07c91 disabled=true
                                    projected_action_0358 = robot.move_to_point(
                                        point_id_or_robot_name='P27',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/1/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=baacdde4-bf53-57fb-9be0-25faca4827f6 disabled=true
                                    projected_action_0359 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0c3c3c49-8f22-5300-b980-d8ee72e92b4a disabled=true
                                    projected_action_0360 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p27.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=9376b63d-c7c7-5bad-b712-62c568729cda disabled=true
                                    projected_action_0361 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p27.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p27.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f128ea32-8656-5c3a-ac47-4b7497404f65 disabled=true
                                    projected_action_0362 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p27.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=167f7d97-bda2-5365-895d-019a8458ea59 disabled=true
                                    projected_action_0363 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/1/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=52e1d4df-4b77-5f2f-b3b7-84826d6a6cf0 disabled=true
                                    projected_action_0364 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/1/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b421e582-afa2-56db-b43f-40aee950bd89 disabled=true
                                    projected_action_0365 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 3（互斥分支）] robot_group_rack_pick@body/3/elifs/2/body 的静态审阅分支。
                                # unilab:node_uuid=e8e08295-88bb-5232-98ca-4e9fcb90a13e
                                with group(name='ELIF 3（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=aa508497-d3e9-589b-bdcf-f8f6dec43498 disabled=true
                                    projected_action_0366 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=9a3b3d13-0536-5b4d-81cb-cb445a74dd85 disabled=true
                                    projected_action_0367 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=217dc395-a76e-5333-8daa-a7203b224ac4 disabled=true
                                    projected_action_0368 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=dd3c1e5d-90f2-5163-a47c-5557f22dd195 disabled=true
                                    projected_action_0369 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p28.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=673f114b-0221-55c1-aac0-fde0146a51fe disabled=true
                                    projected_action_0370 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p28.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/2/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e01eb84b-9248-55db-a2c1-5cdd590be290 disabled=true
                                    projected_action_0371 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2354d8d6-042e-5369-9c19-2c93ad716f13 disabled=true
                                    projected_action_0372 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p28.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P28"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a9ab1986-22bb-5738-9943-568b3bf5c872 disabled=true
                                    projected_action_0373 = robot.move_to_point(
                                        point_id_or_robot_name='P28',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/2/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=45fdf7d0-a832-5e76-9b17-6c78d3e28c61 disabled=true
                                    projected_action_0374 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=1fc41705-9963-5ad9-b3e8-61456aa8110c disabled=true
                                    projected_action_0375 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p28.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a2a0d14e-80cc-5a81-9d07-bc08c4055ad4 disabled=true
                                    projected_action_0376 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p28.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p28.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=972b3361-e2dc-55dd-ab82-8b3fd1581e3d disabled=true
                                    projected_action_0377 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p28.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d4b67a06-cb38-5fbf-a5f9-c90b951233e3 disabled=true
                                    projected_action_0378 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/2/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=6aa86847-2b0a-5e99-8b26-2ccc67c7250f disabled=true
                                    projected_action_0379 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/2/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c4051cc4-a494-5e67-ab4b-8d2a6bd0dde3 disabled=true
                                    projected_action_0380 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 4（互斥分支）] robot_group_rack_pick@body/3/elifs/3/body 的静态审阅分支。
                                # unilab:node_uuid=08fbfd4d-6e63-5810-9a2e-4e600abe0159
                                with group(name='ELIF 4（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a8a9ac37-105e-5681-8ec4-fd8f9db3bd52 disabled=true
                                    projected_action_0381 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d6d9a480-a1d6-5139-819f-21c81bab53ae disabled=true
                                    projected_action_0382 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b4c1fcae-486b-5da1-aed2-8b0f4345beea disabled=true
                                    projected_action_0383 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=90588d99-7fd2-5f96-8197-f9a0a02faa3f disabled=true
                                    projected_action_0384 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p29.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d8047dce-6759-558b-a852-93952a834ac3 disabled=true
                                    projected_action_0385 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p29.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/3/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0fdea63a-5469-5c35-bd98-393682a36150 disabled=true
                                    projected_action_0386 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=35751394-98e3-505f-bd80-93ed9ddb7e01 disabled=true
                                    projected_action_0387 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p29.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P29"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d7f50a5d-8931-55ea-9b9b-711f778389b1 disabled=true
                                    projected_action_0388 = robot.move_to_point(
                                        point_id_or_robot_name='P29',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/3/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e58d356b-5237-5f7b-a33e-0ca5c95d14e1 disabled=true
                                    projected_action_0389 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f9f97863-7df3-536b-8b43-263c1781048e disabled=true
                                    projected_action_0390 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p29.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d1cdadfd-84ed-5d33-abc8-41eecf1a3da3 disabled=true
                                    projected_action_0391 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p29.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p29.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=570341de-1275-5af2-81d3-cfec9136f914 disabled=true
                                    projected_action_0392 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p29.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=4bd14197-70e7-556e-9c62-d76561387307 disabled=true
                                    projected_action_0393 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/3/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8c14d38f-bd7b-5250-924a-f963807ceaa1 disabled=true
                                    projected_action_0394 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/3/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=23a483ce-7544-5e67-a7f9-ec27e081535b disabled=true
                                    projected_action_0395 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 5（互斥分支）] robot_group_rack_pick@body/3/elifs/4/body 的静态审阅分支。
                                # unilab:node_uuid=3ef0ddbf-efdf-5fde-b52c-0c6333684996
                                with group(name='ELIF 5（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f6fb4cca-2c9a-5ead-9360-a19a4e4eea6b disabled=true
                                    projected_action_0396 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3de9a58f-63b7-54ec-af9a-5d8aeb7dac89 disabled=true
                                    projected_action_0397 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a9b8d09f-ea5f-53b5-b3a8-314dd33ef599 disabled=true
                                    projected_action_0398 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=1480598a-d158-5a79-ae46-627d13496e72 disabled=true
                                    projected_action_0399 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p30.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b0cae7a4-a62b-50b0-80c9-c6240ae8be50 disabled=true
                                    projected_action_0400 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p30.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/4/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=60744b99-6db4-5878-9415-01105e9d5809 disabled=true
                                    projected_action_0401 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2a07d20e-fa3c-5bd3-9971-c2ba61dfe132 disabled=true
                                    projected_action_0402 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p30.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P30"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=128eadf9-995a-5414-bf7b-d9b1c94b0c74 disabled=true
                                    projected_action_0403 = robot.move_to_point(
                                        point_id_or_robot_name='P30',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/4/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0f185636-757f-5244-a4e8-66380812563c disabled=true
                                    projected_action_0404 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=66e518be-2225-597b-b749-c19badddb1b6 disabled=true
                                    projected_action_0405 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p30.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=4c724d95-8a68-5a43-a486-8b0f541933aa disabled=true
                                    projected_action_0406 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p30.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p30.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=79824233-104e-5f1a-b1ab-ee1b7b1c4639 disabled=true
                                    projected_action_0407 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p30.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=cbad6636-7ea4-56d0-b704-838ce09083c2 disabled=true
                                    projected_action_0408 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/4/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=02125775-8d49-5a98-832b-c466b809b92d disabled=true
                                    projected_action_0409 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/4/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=6d43b352-1b23-5a72-b506-90e8be5aba25 disabled=true
                                    projected_action_0410 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 6（互斥分支）] robot_group_rack_pick@body/3/elifs/5/body 的静态审阅分支。
                                # unilab:node_uuid=cbadbcbb-60d5-5577-9b6c-5ae03323375a
                                with group(name='ELIF 6（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=9ac95060-daa2-5f32-b8d0-d01b507d910d disabled=true
                                    projected_action_0411 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=84239617-9f4c-5e15-b8c5-47ff795b3c28 disabled=true
                                    projected_action_0412 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e7f02a23-9e8b-5e7a-ba36-54417888651c disabled=true
                                    projected_action_0413 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=1daab3d5-c6a2-57b0-b1c5-03cb61317ec9 disabled=true
                                    projected_action_0414 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p31.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=669ca8df-fd0d-5c61-8eed-6de54f006ef2 disabled=true
                                    projected_action_0415 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p31.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/5/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f00827d5-53ec-5ab2-a097-7272538e8d4f disabled=true
                                    projected_action_0416 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f7ec658e-f0dd-57c0-9bd0-e5cc3998363b disabled=true
                                    projected_action_0417 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p31.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P31"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=10f547a5-8e98-5b24-b68d-498223711cd0 disabled=true
                                    projected_action_0418 = robot.move_to_point(
                                        point_id_or_robot_name='P31',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/5/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c5f8565b-060a-5c44-a82e-ab8b1c120e44 disabled=true
                                    projected_action_0419 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8279cdc7-f0b7-5230-b1d7-f9eb09ecf0c2 disabled=true
                                    projected_action_0420 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p31.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=456e0bca-3a83-5f8b-9283-d510a7fb20fc disabled=true
                                    projected_action_0421 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p31.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p31.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b46a4bb4-a4e6-5241-8eee-1caabd16acbd disabled=true
                                    projected_action_0422 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p31.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e2177cda-1f6f-5447-b6ab-882b7d6ef429 disabled=true
                                    projected_action_0423 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/5/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=6d4548bc-c5e1-5b72-9a89-da2e6cb81439 disabled=true
                                    projected_action_0424 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/5/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=09feda09-7c20-5872-a873-1bcfd2eb0a26 disabled=true
                                    projected_action_0425 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 7（互斥分支）] robot_group_rack_pick@body/3/elifs/6/body 的静态审阅分支。
                                # unilab:node_uuid=61a32283-a72c-539f-8006-d9b59c397d2d
                                with group(name='ELIF 7（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=61767ab9-6baa-58da-9632-5a3435645bd4 disabled=true
                                    projected_action_0426 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c3bd760b-f526-5cf2-9c73-a9e33b7c4fbc disabled=true
                                    projected_action_0427 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3dec42a6-da71-5e97-952a-69f1cc1f9c24 disabled=true
                                    projected_action_0428 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=12283c6b-1983-5371-9243-6754c7213402 disabled=true
                                    projected_action_0429 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p32.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b6a5d6d4-715c-5871-bc00-1dedb9a1a88a disabled=true
                                    projected_action_0430 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p32.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/6/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=6ae95c4a-fd58-544d-99cb-b0445a2e2158 disabled=true
                                    projected_action_0431 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=ae9258f0-4ee1-532a-9d60-67970cfce946 disabled=true
                                    projected_action_0432 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p32.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P32"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=312857cc-0432-5e2f-9ce9-dea61ea6456a disabled=true
                                    projected_action_0433 = robot.move_to_point(
                                        point_id_or_robot_name='P32',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/6/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=339ab2a3-d55d-540b-8dee-5653b28d3dbc disabled=true
                                    projected_action_0434 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=47b8b573-06f0-557f-9b43-ee742427d711 disabled=true
                                    projected_action_0435 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p32.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8f0aab4e-3fe1-5b07-88da-0cce45ece782 disabled=true
                                    projected_action_0436 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p32.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p32.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=aa3b3363-ecc6-5280-b2d2-c042e8fafa51 disabled=true
                                    projected_action_0437 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p32.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=fe832ff9-0007-51f8-85b3-09d41ac472dc disabled=true
                                    projected_action_0438 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/6/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=99e73b7f-332f-58d2-a90a-5e0d3d508f55 disabled=true
                                    projected_action_0439 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/6/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a0b0b14e-58c8-56dd-83bb-4864e571841a disabled=true
                                    projected_action_0440 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 8（互斥分支）] robot_group_rack_pick@body/3/elifs/7/body 的静态审阅分支。
                                # unilab:node_uuid=48fce35d-b8c7-503c-9b57-e7adc1e04ebd
                                with group(name='ELIF 8（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/7/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=79dfa2cd-b56f-556b-8c4c-2ca1b1c256f9 disabled=true
                                    projected_action_0441 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/7/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3590b5e6-e784-5ed8-83a3-167b44712611 disabled=true
                                    projected_action_0442 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c4f63a7d-8a04-5f48-9c6a-a84fe0cc7040 disabled=true
                                    projected_action_0443 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=ad8ba24d-351e-5a9b-8061-3778ee39bae5 disabled=true
                                    projected_action_0444 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p33.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b67230f5-fedc-556c-9e2b-3b327dca3900 disabled=true
                                    projected_action_0445 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p33.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/7/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=06b07ad4-7095-512d-85fe-96a88314f5e2 disabled=true
                                    projected_action_0446 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f52d97fc-1348-5513-9e13-bcc619baf392 disabled=true
                                    projected_action_0447 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p33.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P33"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=ab50ac89-caba-56c7-892a-74541517f03d disabled=true
                                    projected_action_0448 = robot.move_to_point(
                                        point_id_or_robot_name='P33',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/7/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8327aaeb-4287-54a4-89d5-7a21827f56fb disabled=true
                                    projected_action_0449 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=617856c1-36aa-5620-b416-2dcfb587c5cc disabled=true
                                    projected_action_0450 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p33.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3cdb95cf-dbc0-555f-bcf5-ad54a02e5d36 disabled=true
                                    projected_action_0451 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p33.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p33.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d8d85172-9f1a-5b65-8875-e812d534c5b7 disabled=true
                                    projected_action_0452 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p33.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=fb480688-345d-5af0-86f8-2b4d5b4267b3 disabled=true
                                    projected_action_0453 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/7/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=eedb26ab-346a-59ae-9c28-04f746c7b885 disabled=true
                                    projected_action_0454 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/7/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=622e8d1a-1cd0-59e7-bf3e-1fd4adfd1ddc disabled=true
                                    projected_action_0455 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 9（互斥分支）] robot_group_rack_pick@body/3/elifs/8/body 的静态审阅分支。
                                # unilab:node_uuid=1115ac7f-6f71-523d-a112-81a0dc6db308
                                with group(name='ELIF 9（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/8/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a25d35f6-5643-57af-a0b9-52abc092eb18 disabled=true
                                    projected_action_0456 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/8/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d1c2f37e-acfe-5293-bc08-bccda8eacabd disabled=true
                                    projected_action_0457 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=93e5931b-66a4-53aa-a7f2-cf07fb5fc692 disabled=true
                                    projected_action_0458 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8b2ee7f5-0289-56c4-8aba-af2eb762fefe disabled=true
                                    projected_action_0459 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p34.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0b047fa5-c91b-50de-8d88-b14765fcc90f disabled=true
                                    projected_action_0460 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p34.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/8/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=82668011-261a-5d8f-a5d8-58af337019a8 disabled=true
                                    projected_action_0461 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=49450041-2659-5ae0-964a-11e37c3f6a05 disabled=true
                                    projected_action_0462 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p34.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P34"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=434d377b-97a6-5bc4-a812-1381f2578d21 disabled=true
                                    projected_action_0463 = robot.move_to_point(
                                        point_id_or_robot_name='P34',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/8/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b5cffcf8-eb9a-58b3-84e6-db0116f484c3 disabled=true
                                    projected_action_0464 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=cc30ad81-3096-595f-8a45-8b979e344568 disabled=true
                                    projected_action_0465 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p34.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a1dd6a3f-3c93-5c63-bfcc-10b8fb9ad174 disabled=true
                                    projected_action_0466 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p34.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p34.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=80b7ebdd-0fb6-5c85-83be-b4ef02f14187 disabled=true
                                    projected_action_0467 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p34.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=4c9b5672-801b-5492-b9e5-281e3307d8e0 disabled=true
                                    projected_action_0468 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/8/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0b0f7f74-a6d6-56b2-a9fc-ab78f5e55ee9 disabled=true
                                    projected_action_0469 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/8/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f92c0522-718f-5743-885d-80340266db81 disabled=true
                                    projected_action_0470 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 10（互斥分支）] robot_group_rack_pick@body/3/elifs/9/body 的静态审阅分支。
                                # unilab:node_uuid=46ffde42-dff9-56ea-8194-bcf3a87007d1
                                with group(name='ELIF 10（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/9/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2b99e788-de7a-5e62-844f-3f2b59dcf2e3 disabled=true
                                    projected_action_0471 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/9/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3eb09955-3872-57c4-9105-e1c88b480d99 disabled=true
                                    projected_action_0472 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2ef2626a-7269-5a66-b0d4-26d9a9ea67d2 disabled=true
                                    projected_action_0473 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=fc729301-18ce-535b-9c2b-14748f5a77c5 disabled=true
                                    projected_action_0474 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p35.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e5105077-4bb3-5f6d-a4b0-b13e6d1867ac disabled=true
                                    projected_action_0475 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p35.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/9/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=882baaec-78c1-5197-87a5-0b343e86c946 disabled=true
                                    projected_action_0476 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c5251641-0947-5692-92bc-f36ddcd58da7 disabled=true
                                    projected_action_0477 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p35.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P35"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=023f00ae-0b82-5e88-b91a-1cecf4d533fd disabled=true
                                    projected_action_0478 = robot.move_to_point(
                                        point_id_or_robot_name='P35',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/9/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=13ba3ea3-0fe6-5442-83a3-74f47cd7a10c disabled=true
                                    projected_action_0479 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=0f2b1995-b3c1-52b4-bf59-df1f93e06dc8 disabled=true
                                    projected_action_0480 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p35.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b32a0a56-5705-5967-b587-23d5c163043a disabled=true
                                    projected_action_0481 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p35.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p35.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=4586404f-8700-5c28-8348-3fdde07b28d7 disabled=true
                                    projected_action_0482 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p35.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=1c2f13a5-45c5-5a0a-ab41-4a60691145ce disabled=true
                                    projected_action_0483 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/9/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=45b3d103-dfdd-56e2-81bb-ccab85836dea disabled=true
                                    projected_action_0484 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/9/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=5cea7841-e3cd-5275-b8ed-a78617df4dc5 disabled=true
                                    projected_action_0485 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 11（互斥分支）] robot_group_rack_pick@body/3/elifs/10/body 的静态审阅分支。
                                # unilab:node_uuid=c1bb7edf-b108-5f4a-a3ee-733dc08899cd
                                with group(name='ELIF 11（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/10/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3a40fc68-dc17-5f3e-9419-fd2f1b177bef disabled=true
                                    projected_action_0486 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_rack_pick@body/3/elifs/10/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":6}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=1df86679-0aad-5ecc-9b65-04987c1e7414 disabled=true
                                    projected_action_0487 = rail.ensure(
                                        Rail_Target_Position=6,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=314b5a83-e249-5a56-81ce-4a30d06a9d84 disabled=true
                                    projected_action_0488 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8e4d32e3-790a-52d5-80bd-17b63ed19dc0 disabled=true
                                    projected_action_0489 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p36.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a12a135a-6c5e-5596-925b-08dec448e90b disabled=true
                                    projected_action_0490 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p36.mid',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/10/body/5；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=5ab46b49-63e2-59f1-8eab-93bd6cd3a3d5 disabled=true
                                    projected_action_0491 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3964ebc6-4bc2-5e01-bd0e-f4e04e6e7ad9 disabled=true
                                    projected_action_0492 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p36.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P36"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a8018b5b-e25c-52dd-a207-c6a6e4546067 disabled=true
                                    projected_action_0493 = robot.move_to_point(
                                        point_id_or_robot_name='P36',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_rack_pick@body/3/elifs/10/body/8；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=122dacad-5706-50bb-9646-4d62d17cf110 disabled=true
                                    projected_action_0494 = robot.tool_action(
                                        action='gripper-close',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=578c9173-b7e0-5475-9094-dec0df0fe748 disabled=true
                                    projected_action_0495 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p36.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d42349e2-646c-5adf-822f-7e6f2ded5c78 disabled=true
                                    projected_action_0496 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p36.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"group-rack.p36.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=8bbd12cc-d524-584d-a3af-1738190d5cdf disabled=true
                                    projected_action_0497 = robot.move_to_point(
                                        point_id_or_robot_name='group-rack.p36.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P7"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=7d444f5a-065f-55d9-a7d7-676225cd49a7 disabled=true
                                    projected_action_0498 = robot.move_to_point(
                                        point_id_or_robot_name='P7',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_rack_pick@body/3/elifs/10/body/13；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=4d8183de-eed1-52ef-8507-ccc0e419fc98 disabled=true
                                    projected_action_0499 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_rack_pick@body/3/elifs/10/body/14；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3fbbaa54-113d-534a-8a45-93a85207ffb9 disabled=true
                                    projected_action_0500 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELSE（互斥分支）] robot_group_rack_pick@body/3/else 的静态审阅分支。
                                # unilab:node_uuid=14d415de-8213-562b-a68b-2125c0724a16
                                with group(name='ELSE（互斥分支）'):
                                    # [CONTROL raise] 来源 robot_group_rack_pick@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"group-rack.pick: 无效选择值"},"op":"raise"}
                                    # unilab:node_uuid=d74d4ea5-4ca2-5e07-ad1d-4c44b05497aa
                                    with group(name='抛出流程错误'):
                                        # [VERIFY raise] 只读来源校验 robot_group_rack_pick@body/3/else/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=e6cabb9b-3d82-5ac0-a70b-e6322e235a9e disabled=true
                                        projected_control_0501 = material.review_control_node_v1(
                                            operation_name='robot_group_rack_pick',
                                            node_path='body/3/else/0',
                                            control_kind='raise',
                                            expected_sha256='dbb045f0d18c415e9c183f6e6bc9acd38d3aa443e39ca1d6237b8ade965e61f8',
                                        )
                        # [CONTROL comment] 来源 transfer_collector_rack_to_staging_a@body/2；原节点 {"op":"comment","text":"放板前先松开中转A定位气缸 (自守卫: 不依赖调用方留下的气缸态, 否则整板会怼上夹紧的气缸)"}
                        # unilab:node_uuid=e69d118f-ccff-59c9-83a5-131df7f0dee0
                        with group(name='说明 · 放板前先松开中转A定位气缸 (自守卫: 不依赖调用方留下的气缸态, 否则整板会怼上夹紧的气缸)'):
                            # [VERIFY comment] 只读来源校验 transfer_collector_rack_to_staging_a@body/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=53f48a0b-5422-50cd-972a-9077fa2f77b8 disabled=true
                            projected_control_0502 = material.review_control_node_v1(
                                operation_name='transfer_collector_rack_to_staging_a',
                                node_path='body/2',
                                control_kind='comment',
                                expected_sha256='874b52ca18b9c1e742846ffeddc5fd49d4bf4b83cd270a706f7e8ff4f05d6315',
                            )
                        # [ACTION staging_a.locator_a] 来源 transfer_collector_rack_to_staging_a@body/3；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=46dcc209-808c-50b2-b0f6-0c1358ae2ea5 disabled=true
                        projected_action_0503 = staging_a.locator_a(
                            target=False,
                        )
                        # [CONTROL comment] 来源 transfer_collector_rack_to_staging_a@body/4；原节点 {"op":"comment","text":"放收集器整板入中转A(位3=350","金标准; 点 P37@位3) —— 地轨由 robot_group_staging_put enter 处 rail.ensure(3) 自动到位":null}
                        # unilab:node_uuid=25c89632-d0ee-5407-918a-2eb1e1eaa5ca
                        with group(name='说明 · 放收集器整板入中转A(位3=350'):
                            # [VERIFY comment] 只读来源校验 transfer_collector_rack_to_staging_a@body/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=77320896-0abd-547a-a14c-0d3de193637e disabled=true
                            projected_control_0504 = material.review_control_node_v1(
                                operation_name='transfer_collector_rack_to_staging_a',
                                node_path='body/4',
                                control_kind='comment',
                                expected_sha256='0acc0b5c152e0d671128450553bc905a4afc0d545b06787b95c2d423d254feaa',
                            )
                        # [SUBWORKFLOW robot_group_staging_put] 由 transfer_collector_rack_to_staging_a@body/5 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                        # unilab:node_uuid=5cf46653-101d-5db6-9375-0f03c8078f45
                        with group(name='↳ robot_group_staging_put'):
                            # [CONTROL comment] 来源 robot_group_staging_put@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (大夹爪)"}
                            # unilab:node_uuid=970d1388-4f5c-5c98-804d-9bbee71fae83
                            with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (大夹爪)'):
                                # [VERIFY comment] 只读来源校验 robot_group_staging_put@body/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=8fd1f077-8a55-5b9f-a7e7-bcc6569c14c6 disabled=true
                                projected_control_0505 = material.review_control_node_v1(
                                    operation_name='robot_group_staging_put',
                                    node_path='body/0',
                                    control_kind='comment',
                                    expected_sha256='e39d4d29dad9ddaeb2a8577b39843afb69f527adda4225bc7355c38ab532c9fe',
                                )
                            # [ACTION robot.home_ensure] 来源 robot_group_staging_put@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                            # unilab:node_uuid=ced2c7d5-3bc5-586f-ac47-23c01fa3e4c9 disabled=true
                            projected_action_0506 = robot.home_ensure()
                            # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_group_staging_put@body/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=20c6d2ff-90e4-5071-99aa-c885a4b45749 disabled=true
                            projected_control_0507 = material.review_control_node_v1(
                                operation_name='robot_group_staging_put',
                                node_path='body/2',
                                control_kind='run_script',
                                expected_sha256='ba9d83e2dd6420a262ad94775a61abaaba8af3a4bf2d4fef774c9f4fa825eb81',
                            )
                            # [CONTROL if] 来源 robot_group_staging_put@body/3；原节点 {"cond":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"},{"action":"rail.ensure","args":{"Rail_Target_Position"...
                            # unilab:node_uuid=f5559313-2931-5298-8050-763b84623b21
                            with group(name='◇ IF 条件（PlatformUI 判定）'):
                                # [VERIFY if] 只读来源校验 robot_group_staging_put@body/3；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=4568f3ff-87b0-5bdc-9834-47b61e3cd9e9 disabled=true
                                projected_control_0508 = material.review_control_node_v1(
                                    operation_name='robot_group_staging_put',
                                    node_path='body/3',
                                    control_kind='if',
                                    expected_sha256='67ef0fd04b8ae6b9101f677df3a492a0229bc0ec9d4e7853e580b89612db7eb5',
                                )
                                # [BRANCH THEN（互斥分支）] robot_group_staging_put@body/3/then 的静态审阅分支。
                                # unilab:node_uuid=28f45d3d-90ef-542b-8aa1-aeb28d7a66c9
                                with group(name='THEN（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_staging_put@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=6f95df07-48c2-5a42-808a-e94ee6248e68 disabled=true
                                    projected_action_0509 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_staging_put@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=bba58d86-49c4-56a1-a3df-c75fa7136e1a disabled=true
                                    projected_action_0510 = rail.ensure(
                                        Rail_Target_Position=3,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a1a0ec8f-3422-591b-87d9-adf09d958869 disabled=true
                                    projected_action_0511 = robot.move_to_point(
                                        point_id_or_robot_name='P4',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=c9cc9286-c769-5f9a-8ee2-9a55a213b2cc disabled=true
                                    projected_action_0512 = robot.move_to_point(
                                        point_id_or_robot_name='collector-group-staging-put.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=399e2ce0-e449-5ba7-977a-6fe44324e12b disabled=true
                                    projected_action_0513 = robot.move_to_point(
                                        point_id_or_robot_name='collector-group-staging-put.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=97f9c60e-d1b1-59b2-9cb2-3dacec32c0e5 disabled=true
                                    projected_action_0514 = robot.move_to_point(
                                        point_id_or_robot_name='collector-group-staging-put.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P37"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e8c498dc-e7cb-5cf0-b2ca-544e56a76873 disabled=true
                                    projected_action_0515 = robot.move_to_point(
                                        point_id_or_robot_name='P37',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_staging_put@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=9c4d1ea2-1e2c-5e29-a310-ab854d070e48 disabled=true
                                    projected_action_0516 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e68337e6-b357-54dc-85f9-21d83ad8b4c6 disabled=true
                                    projected_action_0517 = robot.move_to_point(
                                        point_id_or_robot_name='collector-group-staging-put.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2f24ee2b-a7c2-5902-8101-9ebb263600e7 disabled=true
                                    projected_action_0518 = robot.move_to_point(
                                        point_id_or_robot_name='collector-group-staging-put.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"collector-group-staging-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=5fc99072-3dce-5708-ae08-26795f3f3f3c disabled=true
                                    projected_action_0519 = robot.move_to_point(
                                        point_id_or_robot_name='collector-group-staging-put.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P4"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=3f0de632-f243-53d2-9489-1da73cc9feae disabled=true
                                    projected_action_0520 = robot.move_to_point(
                                        point_id_or_robot_name='P4',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2b19efa3-e387-59e7-9f84-4dc96866628f disabled=true
                                    projected_action_0521 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_staging_put@body/3/then/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=219e05f4-a004-5348-abc4-e1237715e9c9 disabled=true
                                    projected_action_0522 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELIF 1（互斥分支）] robot_group_staging_put@body/3/elifs/0/body 的静态审阅分支。
                                # unilab:node_uuid=fcbffd25-7aa5-585f-a715-67240c7aa62b
                                with group(name='ELIF 1（互斥分支）'):
                                    # [ACTION robot.require_anchor] 来源 robot_group_staging_put@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=28f7ab04-7e5c-5ba5-84f2-77eb04e7981b disabled=true
                                    projected_action_0523 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                    # [ACTION rail.ensure] 来源 robot_group_staging_put@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=e23dcd34-03d3-5302-8e0c-683564f55fc0 disabled=true
                                    projected_action_0524 = rail.ensure(
                                        Rail_Target_Position=3,
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=22614cf7-0728-5196-9ac1-8150c2dfb9c2 disabled=true
                                    projected_action_0525 = robot.move_to_point(
                                        point_id_or_robot_name='P52',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.far"},"vel":{"lit":30}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=bfd17ad4-2fac-5828-8e3b-57490f3da6f7 disabled=true
                                    projected_action_0526 = robot.move_to_point(
                                        point_id_or_robot_name='bottle-group-staging-put.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":2},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.mid"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=2cf09393-88b9-523a-81f3-1709974fc57d disabled=true
                                    projected_action_0527 = robot.move_to_point(
                                        point_id_or_robot_name='bottle-group-staging-put.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=50be57cf-d3c9-5dcf-97da-521653fa43fe disabled=true
                                    projected_action_0528 = robot.move_to_point(
                                        point_id_or_robot_name='bottle-group-staging-put.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P38"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b46a66a7-ccdb-5622-a0ba-6463c0c2d136 disabled=true
                                    projected_action_0529 = robot.move_to_point(
                                        point_id_or_robot_name='P38',
                                    )
                                    # [ACTION robot.tool_action] 来源 robot_group_staging_put@body/3/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=b7c23251-89ad-5c68-be9f-859be573082c disabled=true
                                    projected_action_0530 = robot.tool_action(
                                        action='gripper-open',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=f99cf4d0-47c9-580a-b25c-5f5378b04490 disabled=true
                                    projected_action_0531 = robot.move_to_point(
                                        point_id_or_robot_name='bottle-group-staging-put.near',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.mid"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=dddedeee-9e39-5238-bce2-aed419c9baab disabled=true
                                    projected_action_0532 = robot.move_to_point(
                                        point_id_or_robot_name='bottle-group-staging-put.mid',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"bottle-group-staging-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=d7cce7c1-c4be-57e7-9a97-850543a5e4ad disabled=true
                                    projected_action_0533 = robot.move_to_point(
                                        point_id_or_robot_name='bottle-group-staging-put.far',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=a10e34bd-6203-5416-9bc3-0a0a1b91bb33 disabled=true
                                    projected_action_0534 = robot.move_to_point(
                                        point_id_or_robot_name='P52',
                                    )
                                    # [ACTION robot.move_to_point] 来源 robot_group_staging_put@body/3/elifs/0/body/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=ca9e919d-e11d-51a3-a3d2-215a32a852f3 disabled=true
                                    projected_action_0535 = robot.move_to_point(
                                        point_id_or_robot_name='P1',
                                    )
                                    # [ACTION robot.require_anchor] 来源 robot_group_staging_put@body/3/elifs/0/body/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                                    # unilab:node_uuid=20b7b0a0-2242-53ab-9979-4fed1a8a930d disabled=true
                                    projected_action_0536 = robot.require_anchor(
                                        point_id='P1',
                                    )
                                # [BRANCH ELSE（互斥分支）] robot_group_staging_put@body/3/else 的静态审阅分支。
                                # unilab:node_uuid=3df47f64-0f5d-5bf7-a7d0-2f4d35daf673
                                with group(name='ELSE（互斥分支）'):
                                    # [CONTROL raise] 来源 robot_group_staging_put@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"group-staging.put: 无效选择值"},"op":"raise"}
                                    # unilab:node_uuid=9c1602b9-91dd-5b84-a9e4-94fe47c3d1e7
                                    with group(name='抛出流程错误'):
                                        # [VERIFY raise] 只读来源校验 robot_group_staging_put@body/3/else/0；节点在本工作流中静态 disabled。
                                        # unilab:node_uuid=1e5eb207-649d-5c7f-bc4a-333f57a62d3d disabled=true
                                        projected_control_0537 = material.review_control_node_v1(
                                            operation_name='robot_group_staging_put',
                                            node_path='body/3/else/0',
                                            control_kind='raise',
                                            expected_sha256='a0f011e9b9ded2a6fc9b5c25d962930118a92f39b694b1ba2ff22d063b5a5d1d',
                                        )
                        # [CONTROL comment] 来源 transfer_collector_rack_to_staging_a@body/6；原节点 {"op":"comment","text":"板已落位","后续小夹爪取单件才不会把整板带走)":null,"夹紧定位气缸 (终态板被固定":null}
                        # unilab:node_uuid=2b582735-ff0b-579a-8af1-0b3e93b274ac
                        with group(name='说明 · 板已落位'):
                            # [VERIFY comment] 只读来源校验 transfer_collector_rack_to_staging_a@body/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=c8392803-0d30-50aa-aab3-f72ddda1a649 disabled=true
                            projected_control_0538 = material.review_control_node_v1(
                                operation_name='transfer_collector_rack_to_staging_a',
                                node_path='body/6',
                                control_kind='comment',
                                expected_sha256='2d0b62dec54e4a38231ef77c6f73193f67df25879893c8139e80135a29b3372a',
                            )
                        # [ACTION staging_a.locator_a] 来源 transfer_collector_rack_to_staging_a@body/7；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d8848ffe-5150-566e-b382-b5f7123407ed disabled=true
                        projected_action_0539 = staging_a.locator_a(
                            target=True,
                        )
                # [BRANCH ELSE（互斥分支）] ensure_collector_staged@body/6/else 的静态审阅分支。
                # unilab:node_uuid=2daf2733-f2b8-5d5b-a04c-7fca9ef6a9b0
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 ensure_collector_staged@body/6；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=9137ed7c-aebe-5499-aae9-fd24e4ca17ba disabled=true
                    projected_control_0540 = material.review_control_node_v1(
                        operation_name='ensure_collector_staged',
                        node_path='body/6',
                        control_kind='if',
                        expected_sha256='2f96e2815b391809df61d7fae0211fa194970aa2d2170f8033e708ba69837b69',
                    )
            # [CONTROL comment] 来源 ensure_collector_staged@body/7；原节点 {"op":"comment","text":"终态自声明: 退出时中转A 板必被夹紧 —— 调用方随后要用小夹爪取单件, 板没夹住会被整板带走。NONE 路径下板本就夹着, 此写为幂等兜底 (直接赋值, 同扫描周期 DONE)"}
            # unilab:node_uuid=75c93953-0ae1-5f9b-9d95-7f550980a632
            with group(name='说明 · 终态自声明: 退出时中转A 板必被夹紧 —— 调用方随后要用小夹爪取单件, 板没夹住会被整板带走。NONE 路径'):
                # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/7；节点在本工作流中静态 disabled。
                # unilab:node_uuid=42a846e0-04ff-5664-b7b6-513bb9452924 disabled=true
                projected_control_0541 = material.review_control_node_v1(
                    operation_name='ensure_collector_staged',
                    node_path='body/7',
                    control_kind='comment',
                    expected_sha256='3515de9b64820739bb8855879b0c6224d6762003f1ed2724c7ccfc34dfe3f55d',
                )
            # [ACTION staging_a.locator_a] 来源 ensure_collector_staged@body/8；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=3f7d0f75-9880-5db5-aeb9-e6858bee6cfb disabled=true
            projected_action_0542 = staging_a.locator_a(
                target=True,
            )
        # [SUBWORKFLOW ensure_bottle_staged] 由 pf_s7_consumables@body/2 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=d8b9b95f-335b-51e6-8806-c21aa28beed9
        with group(name='↳ ensure_bottle_staged'):
            # [CONTROL comment] 来源 ensure_bottle_staged@body/0；原节点 {"op":"comment","text":"读账本决策 (含中转B 在位防呆); 账上无未用孔或账实不符时本动作直接抛错停机"}
            # unilab:node_uuid=97196ef4-e984-517c-a333-6ea2e4b30991
            with group(name='说明 · 读账本决策 (含中转B 在位防呆); 账上无未用孔或账实不符时本动作直接抛错停机'):
                # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=a80507ad-caaa-58a3-addd-d550afc08425 disabled=true
                projected_control_0543 = material.review_control_node_v1(
                    operation_name='ensure_bottle_staged',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='45f3c29500a1bc3022db4f51abb140b9b0e1c850aca535346d63e986ce86c314',
                )
            # [ACTION material.plan_staging] 来源 ensure_bottle_staged@body/1；原节点 {"action":"material.plan_staging","args":{"kind":{"lit":"bottle"},"reserve_for":{"var":"reserve_for"}},"assign":{"var":"plan"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0443704d-2b27-580b-b964-b31f220703e7 disabled=true
            projected_action_0544 = material.plan_staging(
                kind='bottle',
            )
            # [CONTROL assign] 来源 ensure_bottle_staged@body/2；原节点 {"op":"assign","target":{"var":"op"},"value":{"field":{"var":"plan"},"name":"op"}}
            # unilab:node_uuid=44aad067-2d45-5734-aa71-c3851800e2e8
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 ensure_bottle_staged@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=358f1ffe-c780-5831-aed0-c6b09afffef8 disabled=true
                projected_control_0545 = material.review_control_node_v1(
                    operation_name='ensure_bottle_staged',
                    node_path='body/2',
                    control_kind='assign',
                    expected_sha256='752a8e7ac062b5aa2e33a6a2b515271a78f200116fa26e4d00d4329175c46e62',
                )
            # [CONTROL assign] 来源 ensure_bottle_staged@body/3；原节点 {"op":"assign","target":{"var":"rack_slot"},"value":{"field":{"var":"plan"},"name":"rack_slot"}}
            # unilab:node_uuid=070ca42e-206a-53b8-b547-db5ffe480515
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 ensure_bottle_staged@body/3；节点在本工作流中静态 disabled。
                # unilab:node_uuid=b1575fdc-21bd-5a6a-b74e-573749c3c7fa disabled=true
                projected_control_0546 = material.review_control_node_v1(
                    operation_name='ensure_bottle_staged',
                    node_path='body/3',
                    control_kind='assign',
                    expected_sha256='0fa3379fc03f812629d15c29be64125a73fcf8fe233e44134a51cc3b8c57dd12',
                )
            # [CONTROL assign] 来源 ensure_bottle_staged@body/4；原节点 {"op":"assign","target":{"var":"old_rack_slot"},"value":{"field":{"var":"plan"},"name":"old_rack_slot"}}
            # unilab:node_uuid=bcfc7cfa-fe04-5b87-8450-f3903534a60e
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 ensure_bottle_staged@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=c85dcea4-f5b4-5ba9-ba01-3306647d2efd disabled=true
                projected_control_0547 = material.review_control_node_v1(
                    operation_name='ensure_bottle_staged',
                    node_path='body/4',
                    control_kind='assign',
                    expected_sha256='cbc19c59699b67029e4de5b8a1c8224b6d104b1467266ea88c3a714ab58d30e1',
                )
            # [CONTROL assign] 来源 ensure_bottle_staged@body/5；原节点 {"op":"assign","target":{"var":"hole"},"value":{"field":{"var":"plan"},"name":"hole"}}
            # unilab:node_uuid=20ca182b-66fb-5ecf-be30-455f1ea11676
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 ensure_bottle_staged@body/5；节点在本工作流中静态 disabled。
                # unilab:node_uuid=569c7d48-13af-527c-8a4e-1ff8236949db disabled=true
                projected_control_0548 = material.review_control_node_v1(
                    operation_name='ensure_bottle_staged',
                    node_path='body/5',
                    control_kind='assign',
                    expected_sha256='80038b1850b9abbfa9ddc48239e7e240f9dc013796291b091335ff8bb6625419',
                )
            # [CONTROL if] 来源 ensure_bottle_staged@body/6；原节点 {"cond":{"binop":"!=","left":{"var":"op"},"right":{"lit":"NONE"}},"op":"if","then":[{"op":"comment","text":"要动整板才切工具2大夹爪 (NONE 复用时全程不换刀, 也不进货架区)"},{"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"},{"cond":{"binop":"==","left":{"var":"op"},"right":{"lit":"SWAP"}},"op":"if","then":...
            # unilab:node_uuid=e35d53cb-1228-55bd-a080-a00299671c2c
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 ensure_bottle_staged@body/6；节点在本工作流中静态 disabled。
                # unilab:node_uuid=4fa7beff-4183-55cf-8dd8-924f2adbca20 disabled=true
                projected_control_0549 = material.review_control_node_v1(
                    operation_name='ensure_bottle_staged',
                    node_path='body/6',
                    control_kind='if',
                    expected_sha256='ee0fbe8373c6e2d28221d31637096f52d0860619ee14ed2085eab7884ffdeac1',
                )
                # [BRANCH THEN（互斥分支）] ensure_bottle_staged@body/6/then 的静态审阅分支。
                # unilab:node_uuid=02419bfd-ae7d-5e6a-9cfb-e33f1cfac87a
                with group(name='THEN（互斥分支）'):
                    # [CONTROL comment] 来源 ensure_bottle_staged@body/6/then/0；原节点 {"op":"comment","text":"要动整板才切工具2大夹爪 (NONE 复用时全程不换刀, 也不进货架区)"}
                    # unilab:node_uuid=fd06bd72-f8f9-5c88-b83f-c77f47189ef0
                    with group(name='说明 · 要动整板才切工具2大夹爪 (NONE 复用时全程不换刀, 也不进货架区)'):
                        # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/6/then/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=1af8e905-8cef-5a4e-a79c-5fd98cf870a3 disabled=true
                        projected_control_0550 = material.review_control_node_v1(
                            operation_name='ensure_bottle_staged',
                            node_path='body/6/then/0',
                            control_kind='comment',
                            expected_sha256='9eb63c0c84887a794ac9bb5a9b24241a3e243341286c731d6087fb89649fb8a6',
                        )
                    # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 ensure_bottle_staged@body/6/then/1；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=935ac669-1e68-5126-8afb-201c5f728b68 disabled=true
                    projected_control_0551 = material.review_control_node_v1(
                        operation_name='ensure_bottle_staged',
                        node_path='body/6/then/1',
                        control_kind='run_script',
                        expected_sha256='ba9d83e2dd6420a262ad94775a61abaaba8af3a4bf2d4fef774c9f4fa825eb81',
                    )
                    # [CONTROL if] 来源 ensure_bottle_staged@body/6/then/2；原节点 {"cond":{"binop":"==","left":{"var":"op"},"right":{"lit":"SWAP"}},"op":"if","then":[{"op":"comment","text":"SWAP: 先把装满成品瓶的中转板送回它载入时的那个货架库位 (成品随板归档)"},{"inputs":{"slot_id":{"var":"old_rack_slot"}},"op":"run_script","outputs":{},"script":"transfer_bottle_staging_b_to_rack"}]}
                    # unilab:node_uuid=db8b7c21-a8e8-53d2-b130-30f385d5d30d
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 ensure_bottle_staged@body/6/then/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=45c999bf-2463-5111-817a-8540638bfbab disabled=true
                        projected_control_0552 = material.review_control_node_v1(
                            operation_name='ensure_bottle_staged',
                            node_path='body/6/then/2',
                            control_kind='if',
                            expected_sha256='fe3ac98e9c09b236795fd80bf489ff20b8968bfa446ddf1d1825aca70ccf7872',
                        )
                        # [BRANCH THEN（互斥分支）] ensure_bottle_staged@body/6/then/2/then 的静态审阅分支。
                        # unilab:node_uuid=4c3267f4-08c5-53ac-8a52-2ef7fdcc5c29
                        with group(name='THEN（互斥分支）'):
                            # [CONTROL comment] 来源 ensure_bottle_staged@body/6/then/2/then/0；原节点 {"op":"comment","text":"SWAP: 先把装满成品瓶的中转板送回它载入时的那个货架库位 (成品随板归档)"}
                            # unilab:node_uuid=a02b0101-a39b-5504-8dcc-7614c94327e7
                            with group(name='说明 · SWAP: 先把装满成品瓶的中转板送回它载入时的那个货架库位 (成品随板归档)'):
                                # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/6/then/2/then/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=f38f375f-8cc4-5175-afab-eebce07e4389 disabled=true
                                projected_control_0553 = material.review_control_node_v1(
                                    operation_name='ensure_bottle_staged',
                                    node_path='body/6/then/2/then/0',
                                    control_kind='comment',
                                    expected_sha256='7de517cda994ae0bed89b00da40e8311ddaa938cc35456a196332f5d188cac94',
                                )
                            # [SUBWORKFLOW transfer_bottle_staging_b_to_rack] 由 ensure_bottle_staged@body/6/then/2/then/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                            # unilab:node_uuid=6868b1a3-6feb-520f-9848-823e57c1e62a
                            with group(name='↳ transfer_bottle_staging_b_to_rack'):
                                # [CONTROL comment] 来源 transfer_bottle_staging_b_to_rack@body/0；原节点 {"op":"comment","text":"取板前先松开中转B定位气缸 (自守卫: 夹紧态下拔整板会顶坏气缸/托盘); 取毕保持松开, 区已空不夹空气"}
                                # unilab:node_uuid=e9da0745-434a-5ef6-b4fb-547b1a1c62bd
                                with group(name='说明 · 取板前先松开中转B定位气缸 (自守卫: 夹紧态下拔整板会顶坏气缸/托盘); 取毕保持松开, 区已空不夹空气'):
                                    # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_rack@body/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=dbf70e15-b553-5970-9bea-da20689b0249 disabled=true
                                    projected_control_0554 = material.review_control_node_v1(
                                        operation_name='transfer_bottle_staging_b_to_rack',
                                        node_path='body/0',
                                        control_kind='comment',
                                        expected_sha256='bc991ad1c728d83f7fe72c9210978816945b8b712052844c9bc15d5688d70143',
                                    )
                                # [ACTION staging_a.locator_b] 来源 transfer_bottle_staging_b_to_rack@body/1；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=cbea4829-3794-5201-a585-d01ef2b2b5e8 disabled=true
                                projected_action_0555 = staging_a.locator_b(
                                    target=False,
                                )
                                # [CONTROL comment] 来源 transfer_bottle_staging_b_to_rack@body/2；原节点 {"op":"comment","text":"从中转B(位3)取瓶组 —— 地轨由 robot_group_staging_pick enter 处 rail.ensure(3) 自动到位"}
                                # unilab:node_uuid=2b7d8717-bd3b-5bd2-aa6a-2545e8846489
                                with group(name='说明 · 从中转B(位3)取瓶组 —— 地轨由 robot_group_staging_pick enter 处 rail'):
                                    # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_rack@body/2；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=49322204-05eb-551b-b40e-42fba49b8734 disabled=true
                                    projected_control_0556 = material.review_control_node_v1(
                                        operation_name='transfer_bottle_staging_b_to_rack',
                                        node_path='body/2',
                                        control_kind='comment',
                                        expected_sha256='77274029c2d93583b190df167fb981342a1fc9eb9f9e165cb0873d12735f986f',
                                    )
                                # [SUBWORKFLOW REF robot_group_staging_pick · DEFINITION ALREADY SHOWN] 只读来源校验 transfer_bottle_staging_b_to_rack@body/3；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=ba0c1392-13d3-51b6-8402-2dc544faecfc disabled=true
                                projected_control_0557 = material.review_control_node_v1(
                                    operation_name='transfer_bottle_staging_b_to_rack',
                                    node_path='body/3',
                                    control_kind='run_script',
                                    expected_sha256='34b9648123e6c34c8f96ea73b56ed4ee53b594d4448d780173176be44aee94f1',
                                )
                                # [CONTROL comment] 来源 transfer_bottle_staging_b_to_rack@body/4；原节点 {"op":"comment","text":"放瓶组回货架(位6) —— 地轨由 robot_group_rack_put enter 处 rail.ensure(6) 自动到位"}
                                # unilab:node_uuid=c053a9fa-a7db-5dda-b6c7-b0287f086d4e
                                with group(name='说明 · 放瓶组回货架(位6) —— 地轨由 robot_group_rack_put enter 处 rail.ensu'):
                                    # [VERIFY comment] 只读来源校验 transfer_bottle_staging_b_to_rack@body/4；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=f7f3d0d7-1218-5f81-89b6-c5c98c01d389 disabled=true
                                    projected_control_0558 = material.review_control_node_v1(
                                        operation_name='transfer_bottle_staging_b_to_rack',
                                        node_path='body/4',
                                        control_kind='comment',
                                        expected_sha256='6c3ca15e34cfa6fa0490e42abdc7fe479de26249808fcf40da4c99050d4cf5f7',
                                    )
                                # [SUBWORKFLOW REF robot_group_rack_put · DEFINITION ALREADY SHOWN] 只读来源校验 transfer_bottle_staging_b_to_rack@body/5；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=56e69a0e-eb44-57fa-84cb-41bac7fd5d55 disabled=true
                                projected_control_0559 = material.review_control_node_v1(
                                    operation_name='transfer_bottle_staging_b_to_rack',
                                    node_path='body/5',
                                    control_kind='run_script',
                                    expected_sha256='bfd25c97d3c7a38152f7f2f606ea7607e42bb0b42c5791aaaad3973c50a9723e',
                                )
                        # [BRANCH ELSE（互斥分支）] ensure_bottle_staged@body/6/then/2/else 的静态审阅分支。
                        # unilab:node_uuid=4b39636f-ef0e-550f-979f-dd9e4e64474d
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 ensure_bottle_staged@body/6/then/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=431de0cd-1c4d-5737-88f7-4b94abc315dc disabled=true
                            projected_control_0560 = material.review_control_node_v1(
                                operation_name='ensure_bottle_staged',
                                node_path='body/6/then/2',
                                control_kind='if',
                                expected_sha256='fe3ac98e9c09b236795fd80bf489ff20b8968bfa446ddf1d1825aca70ccf7872',
                            )
                    # [CONTROL comment] 来源 ensure_bottle_staged@body/6/then/3；原节点 {"op":"comment","text":"PUT_NEW / SWAP: 从货架取有料的新板进中转B, 落位后由该脚本自行夹紧"}
                    # unilab:node_uuid=716caa5a-9467-578e-839b-47ed47adbf6c
                    with group(name='说明 · PUT_NEW / SWAP: 从货架取有料的新板进中转B, 落位后由该脚本自行夹紧'):
                        # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/6/then/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=cd194920-417b-53f3-9a6f-1b286616bec4 disabled=true
                        projected_control_0561 = material.review_control_node_v1(
                            operation_name='ensure_bottle_staged',
                            node_path='body/6/then/3',
                            control_kind='comment',
                            expected_sha256='6d8b20744c7184f26acf0bd58b15cf0ddc85d55d4eb2073262ddaebafafc3756',
                        )
                    # [SUBWORKFLOW transfer_bottle_rack_to_staging_b] 由 ensure_bottle_staged@body/6/then/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
                    # unilab:node_uuid=3e6c32b8-37f4-5341-8177-c9debb840cb3
                    with group(name='↳ transfer_bottle_rack_to_staging_b'):
                        # [CONTROL comment] 来源 transfer_bottle_rack_to_staging_b@body/0；原节点 {"op":"comment","text":"从货架(位6)取瓶组 —— 地轨由 robot_group_rack_pick enter 处 rail.ensure(6) 自动到位"}
                        # unilab:node_uuid=980462a7-e5ea-5c16-8474-00f5af24f491
                        with group(name='说明 · 从货架(位6)取瓶组 —— 地轨由 robot_group_rack_pick enter 处 rail.ens'):
                            # [VERIFY comment] 只读来源校验 transfer_bottle_rack_to_staging_b@body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=d59dc573-abd4-5fbd-977f-72dcedcd0f95 disabled=true
                            projected_control_0562 = material.review_control_node_v1(
                                operation_name='transfer_bottle_rack_to_staging_b',
                                node_path='body/0',
                                control_kind='comment',
                                expected_sha256='a92854b765d0f81d44f72acef8faeb069db5995c71cb2ca7faa1859ccbbddcfd',
                            )
                        # [SUBWORKFLOW REF robot_group_rack_pick · DEFINITION ALREADY SHOWN] 只读来源校验 transfer_bottle_rack_to_staging_b@body/1；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=8b16bc8d-75dc-5bcc-9e03-bdd62d3ed581 disabled=true
                        projected_control_0563 = material.review_control_node_v1(
                            operation_name='transfer_bottle_rack_to_staging_b',
                            node_path='body/1',
                            control_kind='run_script',
                            expected_sha256='91b0a646b4287f2bea2424102051f40a3162682f514ed2a8fa1229147ef67280',
                        )
                        # [CONTROL comment] 来源 transfer_bottle_rack_to_staging_b@body/2；原节点 {"op":"comment","text":"放板前先松开中转B定位气缸 (自守卫: 不依赖调用方留下的气缸态, 否则整板会怼上夹紧的气缸)"}
                        # unilab:node_uuid=03e37d5b-5cec-5016-a708-888d503e36e3
                        with group(name='说明 · 放板前先松开中转B定位气缸 (自守卫: 不依赖调用方留下的气缸态, 否则整板会怼上夹紧的气缸)'):
                            # [VERIFY comment] 只读来源校验 transfer_bottle_rack_to_staging_b@body/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=99f034bd-32f4-5090-ba69-25380fae1d7b disabled=true
                            projected_control_0564 = material.review_control_node_v1(
                                operation_name='transfer_bottle_rack_to_staging_b',
                                node_path='body/2',
                                control_kind='comment',
                                expected_sha256='a458d2f8c7857e784ff38b77fdf6b9cb62b688f33c0fd63a5ddfc8106a8e7aa7',
                            )
                        # [ACTION staging_a.locator_b] 来源 transfer_bottle_rack_to_staging_b@body/3；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":false}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=da77db74-da51-5147-b86d-92264e393a74 disabled=true
                        projected_action_0565 = staging_a.locator_b(
                            target=False,
                        )
                        # [CONTROL comment] 来源 transfer_bottle_rack_to_staging_b@body/4；原节点 {"op":"comment","text":"放瓶组入中转B(位3) —— 地轨由 robot_group_staging_put enter 处 rail.ensure(3) 自动到位"}
                        # unilab:node_uuid=a987a4e7-54a9-5406-a67f-6a56534aee47
                        with group(name='说明 · 放瓶组入中转B(位3) —— 地轨由 robot_group_staging_put enter 处 rail.'):
                            # [VERIFY comment] 只读来源校验 transfer_bottle_rack_to_staging_b@body/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6967d909-cfa2-569d-addb-7f965b537718 disabled=true
                            projected_control_0566 = material.review_control_node_v1(
                                operation_name='transfer_bottle_rack_to_staging_b',
                                node_path='body/4',
                                control_kind='comment',
                                expected_sha256='12264cb46d230cd7c35504e2bb1a48c9c1478e12ff6d5206aa77c2d7aa3f4d36',
                            )
                        # [SUBWORKFLOW REF robot_group_staging_put · DEFINITION ALREADY SHOWN] 只读来源校验 transfer_bottle_rack_to_staging_b@body/5；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=2364ade1-44c5-5ec5-b198-22fe67206a3a disabled=true
                        projected_control_0567 = material.review_control_node_v1(
                            operation_name='transfer_bottle_rack_to_staging_b',
                            node_path='body/5',
                            control_kind='run_script',
                            expected_sha256='0275a3aecf8ff2a87ff6526f52f64f77bf7ef3093005c17356d7e80339aaa0ca',
                        )
                        # [CONTROL comment] 来源 transfer_bottle_rack_to_staging_b@body/6；原节点 {"op":"comment","text":"板已落位","后续小夹爪取单瓶才不会把整板带走)":null,"夹紧定位气缸 (终态板被固定":null}
                        # unilab:node_uuid=b0902786-7262-5da1-a0a7-972f34eb724e
                        with group(name='说明 · 板已落位'):
                            # [VERIFY comment] 只读来源校验 transfer_bottle_rack_to_staging_b@body/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=12bb94cc-858d-5e9f-9abc-eb556425c642 disabled=true
                            projected_control_0568 = material.review_control_node_v1(
                                operation_name='transfer_bottle_rack_to_staging_b',
                                node_path='body/6',
                                control_kind='comment',
                                expected_sha256='051c9928443d369f57cc2b6d1191d631379837c3e51323e512e04781d16de403',
                            )
                        # [ACTION staging_a.locator_b] 来源 transfer_bottle_rack_to_staging_b@body/7；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=bf7583cf-a502-5e41-9d11-b6b6e5f131a5 disabled=true
                        projected_action_0569 = staging_a.locator_b(
                            target=True,
                        )
                # [BRANCH ELSE（互斥分支）] ensure_bottle_staged@body/6/else 的静态审阅分支。
                # unilab:node_uuid=ece6a742-273e-5936-9c8e-e84840ff9175
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 ensure_bottle_staged@body/6；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=0a997ee6-03fe-5d15-9da6-7ff1b1be941b disabled=true
                    projected_control_0570 = material.review_control_node_v1(
                        operation_name='ensure_bottle_staged',
                        node_path='body/6',
                        control_kind='if',
                        expected_sha256='ee0fbe8373c6e2d28221d31637096f52d0860619ee14ed2085eab7884ffdeac1',
                    )
            # [CONTROL comment] 来源 ensure_bottle_staged@body/7；原节点 {"op":"comment","text":"终态自声明: 退出时中转B 板必被夹紧 —— 调用方随后要用小夹爪取单瓶, 板没夹住会被整板带走。NONE 路径下板本就夹着, 此写为幂等兜底 (直接赋值, 同扫描周期 DONE)"}
            # unilab:node_uuid=a3e3eb2b-bbbf-5acd-8998-82b1e0dd3eb9
            with group(name='说明 · 终态自声明: 退出时中转B 板必被夹紧 —— 调用方随后要用小夹爪取单瓶, 板没夹住会被整板带走。NONE 路径'):
                # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/7；节点在本工作流中静态 disabled。
                # unilab:node_uuid=d85b2f70-c9aa-583d-8d62-bd1da658c109 disabled=true
                projected_control_0571 = material.review_control_node_v1(
                    operation_name='ensure_bottle_staged',
                    node_path='body/7',
                    control_kind='comment',
                    expected_sha256='2a5b66672e5e81a06fede17b587bd55d0ea0dd4e5788d4054436a88d2887ba41',
                )
            # [ACTION staging_a.locator_b] 来源 ensure_bottle_staged@body/8；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=857805f4-39ea-5b94-a280-b9bee54243a9 disabled=true
            projected_action_0572 = staging_a.locator_b(
                target=True,
            )
        # [CONTROL comment] 来源 pf_s7_consumables@body/3；原节点 {"op":"comment","text":"段级兜底: 两个 ensure_* 退出时已各自把本区夹紧, 此处成对再写一次保持显式终态 (幂等; 与 V2 同)"}
        # unilab:node_uuid=41292cae-1ff2-5d40-872e-d13a6004c7e7
        with group(name='说明 · 段级兜底: 两个 ensure_* 退出时已各自把本区夹紧, 此处成对再写一次保持显式终态 (幂等; 与 V2 '):
            # [VERIFY comment] 只读来源校验 pf_s7_consumables@body/3；节点在本工作流中静态 disabled。
            # unilab:node_uuid=54169335-9d0a-5a6b-9184-4b8f65bafeb6 disabled=true
            projected_control_0573 = material.review_control_node_v1(
                operation_name='pf_s7_consumables',
                node_path='body/3',
                control_kind='comment',
                expected_sha256='df3a5a1237a2931bcc94957d03c30ad3362c254c6534ae7665abf2fb95e7a99f',
            )
        # [ACTION staging_a.locator_a] 来源 pf_s7_consumables@body/4；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
        # unilab:node_uuid=70071c5e-72e2-5c98-8c21-a1989e7b130c disabled=true
        projected_action_0574 = staging_a.locator_a(
            target=True,
        )
        # [ACTION staging_a.locator_b] 来源 pf_s7_consumables@body/5；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
        # unilab:node_uuid=036f9c09-8907-5cad-ae90-c1891666194f disabled=true
        projected_action_0575 = staging_a.locator_b(
            target=True,
        )
        # [CONTROL comment] 来源 pf_s7_consumables@body/6；原节点 {"op":"comment","text":"取单件切工具3小夹爪 (整板转运是大夹爪; 单件取点 P46-51 按小夹爪示教)"}
        # unilab:node_uuid=6bbea906-e4ca-596e-8b48-5db947ad8452
        with group(name='说明 · 取单件切工具3小夹爪 (整板转运是大夹爪; 单件取点 P46-51 按小夹爪示教)'):
            # [VERIFY comment] 只读来源校验 pf_s7_consumables@body/6；节点在本工作流中静态 disabled。
            # unilab:node_uuid=1ca7a590-30ea-5f90-8f28-a6629c9a1ac8 disabled=true
            projected_control_0576 = material.review_control_node_v1(
                operation_name='pf_s7_consumables',
                node_path='body/6',
                control_kind='comment',
                expected_sha256='f1afdfa7f6df52c97f96e168db6e75c9601cf9bd79500bd6db93eff2bd6698f8',
            )
        # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 pf_s7_consumables@body/7；节点在本工作流中静态 disabled。
        # unilab:node_uuid=24bccd66-0a84-57fb-b2e0-a7b32401ec4a disabled=true
        projected_control_0577 = material.review_control_node_v1(
            operation_name='pf_s7_consumables',
            node_path='body/7',
            control_kind='run_script',
            expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
        )
        # [CONTROL comment] 来源 pf_s7_consumables@body/8；原节点 {"op":"comment","text":"收集器链放入刮板接粉夹具 (必须在 s9 刮取前就位, 粉末落入其中)"}
        # unilab:node_uuid=d2b19b96-a07d-561d-9d7a-e5d6397a255b
        with group(name='说明 · 收集器链放入刮板接粉夹具 (必须在 s9 刮取前就位, 粉末落入其中)'):
            # [VERIFY comment] 只读来源校验 pf_s7_consumables@body/8；节点在本工作流中静态 disabled。
            # unilab:node_uuid=f89792fa-fd12-543e-8788-81fdbfcd4f87 disabled=true
            projected_control_0578 = material.review_control_node_v1(
                operation_name='pf_s7_consumables',
                node_path='body/8',
                control_kind='comment',
                expected_sha256='0c4e309ceaaefa08a5d4bc2c0404b4e5984655ecb8eb79f23e72d72af80d5831',
            )
        # [SUBWORKFLOW transfer_collector_staging_a_to_scrape] 由 pf_s7_consumables@body/9 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=8a1d6fd9-0735-5ebd-8a2a-9e32f7ddd444
        with group(name='↳ transfer_collector_staging_a_to_scrape'):
            # [CONTROL comment] 来源 transfer_collector_staging_a_to_scrape@body/0；原节点 {"op":"comment","text":"地轨到中转A(位2≡刮板/拍照 168.0, 与收集站位3异位); 从中转A取单个收集器"}
            # unilab:node_uuid=4faa0a81-7537-5eb3-a0e7-49282a893428
            with group(name='说明 · 地轨到中转A(位2≡刮板/拍照 168.0, 与收集站位3异位); 从中转A取单个收集器'):
                # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=0785e21e-1974-5d3d-b206-54626b8210ab disabled=true
                projected_control_0579 = material.review_control_node_v1(
                    operation_name='transfer_collector_staging_a_to_scrape',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='3739b2b1dc16f5183ccab2794bfc7c271750731112496ba53bd2d15f1fde36e0',
                )
            # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 transfer_collector_staging_a_to_scrape@body/1；节点在本工作流中静态 disabled。
            # unilab:node_uuid=b774328c-d311-50d5-9bfe-8682c85aa472 disabled=true
            projected_control_0580 = material.review_control_node_v1(
                operation_name='transfer_collector_staging_a_to_scrape',
                node_path='body/1',
                control_kind='run_script',
                expected_sha256='3375626c6140464d00aa9cbdffc04532e0598412bbb03a5cdc11186253b17bd1',
            )
            # [CONTROL comment] 来源 transfer_collector_staging_a_to_scrape@body/2；原节点 {"op":"comment","text":"中转A定位气缸保持动点后, 再从中转A取单个收集器"}
            # unilab:node_uuid=54704901-e518-5b71-8059-0eb2d0580a75
            with group(name='说明 · 中转A定位气缸保持动点后, 再从中转A取单个收集器'):
                # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=8fcbf874-6903-55ae-b6e8-007f69285995 disabled=true
                projected_control_0581 = material.review_control_node_v1(
                    operation_name='transfer_collector_staging_a_to_scrape',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='070f2fef18f2f549fa4de453b1f7abef1610a3e484c8bcf8ca521a994bcd0ece',
                )
            # [ACTION staging_a.locator_a] 来源 transfer_collector_staging_a_to_scrape@body/3；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5bae8460-0e37-5d25-a2c8-c50175fb3cee disabled=true
            projected_action_0582 = staging_a.locator_a(
                target=True,
            )
            # [SUBWORKFLOW robot_individual_pick] 由 transfer_collector_staging_a_to_scrape@body/4 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=af1750f2-cd83-51ac-a736-fd43227f4ecb
            with group(name='↳ robot_individual_pick'):
                # [CONTROL comment] 来源 robot_individual_pick@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)"}
                # unilab:node_uuid=3da7f71f-01be-5100-9128-4cc7ada40535
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)'):
                    # [VERIFY comment] 只读来源校验 robot_individual_pick@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=5cbc0357-0300-5cf5-8940-bbbc75eebf8f disabled=true
                    projected_control_0583 = material.review_control_node_v1(
                        operation_name='robot_individual_pick',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
                    )
                # [ACTION robot.home_ensure] 来源 robot_individual_pick@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=7e9236ec-e7ef-58ae-9a93-17ebba14869a disabled=true
                projected_action_0584 = robot.home_ensure()
                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_individual_pick@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=a4612c76-4f5e-5998-8ceb-d19fc980f367 disabled=true
                projected_control_0585 = material.review_control_node_v1(
                    operation_name='robot_individual_pick',
                    node_path='body/2',
                    control_kind='run_script',
                    expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
                )
                # [CONTROL if] 来源 robot_individual_pick@body/3；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"rack_id"},"right":{"lit":"collector"}},"right":{"binop":"==","left":{"var":"slot_id"},"right":{"lit":1}}},"elifs":[{"body":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit"...
                # unilab:node_uuid=987af12b-4075-504b-a336-f83bcc3120b9
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_individual_pick@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=16be9451-d332-5cd9-b2bd-3d48d58a81ac disabled=true
                    projected_control_0586 = material.review_control_node_v1(
                        operation_name='robot_individual_pick',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='10ac28536da762f8be3b04b3bc814687c2e9427c2573ad6aeac2f3378299f9d1',
                    )
                    # [BRANCH THEN（互斥分支）] robot_individual_pick@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=98b35baa-fd50-53ba-875e-a4fbdd00caf4
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=dea85088-250d-5f2b-b3ae-75cb022e2ccf disabled=true
                        projected_action_0587 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b3af35fb-19a1-56af-bfcb-de43f6949191 disabled=true
                        projected_action_0588 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=46961f79-14b0-5a49-abf0-0f880201ed0c disabled=true
                        projected_action_0589 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9c4a498a-90a1-55fb-ac85-5445527b3e85 disabled=true
                        projected_action_0590 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p46.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/then/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=62daed75-7433-5977-ac8e-bdf5a5e2c399 disabled=true
                        projected_action_0591 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0d208aa7-fdbe-5abc-b1ac-1d9db2a1379d disabled=true
                        projected_action_0592 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p46.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P46"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5d6fd51b-8bf9-5c85-a057-31fa0a3b6249 disabled=true
                        projected_action_0593 = robot.move_to_point(
                            point_id_or_robot_name='P46',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/then/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ebcf1080-f7db-5f2b-953c-ba5506701fee disabled=true
                        projected_action_0594 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c0768716-2bb2-51ac-90fb-31716cd01c81 disabled=true
                        projected_action_0595 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p46.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p46.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1ad9e12c-d594-5819-878a-fa1dc965f599 disabled=true
                        projected_action_0596 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p46.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=efd65bde-6599-5eb8-80ce-a1033ddb081d disabled=true
                        projected_action_0597 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ae65da38-023d-5eac-8278-920ee20172f8 disabled=true
                        projected_action_0598 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/then/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c53b5637-f50f-5f72-8eda-9d7417825aaa disabled=true
                        projected_action_0599 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 1（互斥分支）] robot_individual_pick@body/3/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=ecc587dc-0a5f-5f25-80e8-13fd882d3f67
                    with group(name='ELIF 1（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/0/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a7e7dcac-fbff-561a-b84e-89c330b3efbb disabled=true
                        projected_action_0600 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/0/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4d7381a5-ecb7-58fa-87c6-25b898760957 disabled=true
                        projected_action_0601 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4ca7dcbe-23c5-50e3-8be3-20216b9794a8 disabled=true
                        projected_action_0602 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0efdcaac-2915-595c-9948-cee1e050aee7 disabled=true
                        projected_action_0603 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p47.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/0/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fd8e0ae1-de0a-50ef-846b-87c3507916a3 disabled=true
                        projected_action_0604 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d2ef2503-2a38-586d-b79e-4babe98e21ab disabled=true
                        projected_action_0605 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p47.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P47"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d051fef9-4e09-5153-8175-cc7d2e9a7f09 disabled=true
                        projected_action_0606 = robot.move_to_point(
                            point_id_or_robot_name='P47',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/0/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2eaa4a49-ab27-515a-9d8c-53a2babc45e3 disabled=true
                        projected_action_0607 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=70f91a74-aaca-5d4c-a6ee-6f9516e72616 disabled=true
                        projected_action_0608 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p47.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p47.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=61d2c555-e4a7-50e7-9a6a-9de6833a296b disabled=true
                        projected_action_0609 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p47.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fb4931e4-8f15-518e-922e-d6d5577359ad disabled=true
                        projected_action_0610 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/0/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=79ed68dc-7eef-5ebb-897f-5262a1b429b0 disabled=true
                        projected_action_0611 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/0/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7c3e0fc3-99bc-5afd-81e0-13bbd1c6843c disabled=true
                        projected_action_0612 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 2（互斥分支）] robot_individual_pick@body/3/elifs/1/body 的静态审阅分支。
                    # unilab:node_uuid=01a300d9-2a0d-568d-9219-878d3d099d2b
                    with group(name='ELIF 2（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/1/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8ab24c7b-2d5e-50ed-833f-65ae7aa27736 disabled=true
                        projected_action_0613 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/1/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a8145f75-9194-5d9b-a844-75b091893594 disabled=true
                        projected_action_0614 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e9c7255c-0de5-5e54-b704-563a846fa76e disabled=true
                        projected_action_0615 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1e2a93dc-0ba0-5a8b-952f-f8ee6e4e0e2f disabled=true
                        projected_action_0616 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p48.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/1/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c5deb092-4aad-5ecf-8be6-d6aec602fc6a disabled=true
                        projected_action_0617 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2846c941-d7ef-5119-897f-69774d84a5aa disabled=true
                        projected_action_0618 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p48.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P48"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cff9d248-b62d-550c-9ee1-743d76bdd4f5 disabled=true
                        projected_action_0619 = robot.move_to_point(
                            point_id_or_robot_name='P48',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/1/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5cdde5f1-8c5f-54e9-9820-5a49c61aa5b8 disabled=true
                        projected_action_0620 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7d31e092-8144-5a44-9656-d1887f034a89 disabled=true
                        projected_action_0621 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p48.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p48.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=eecde63c-119e-5718-a6eb-e75a0c473459 disabled=true
                        projected_action_0622 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p48.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9f977d6d-be18-527c-a4ee-04a7bf36f44e disabled=true
                        projected_action_0623 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/1/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=84eb7c92-4e65-5355-af9b-7e60e0a6b552 disabled=true
                        projected_action_0624 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/1/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7441ee83-6918-5e89-9c88-486f6a558416 disabled=true
                        projected_action_0625 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 3（互斥分支）] robot_individual_pick@body/3/elifs/2/body 的静态审阅分支。
                    # unilab:node_uuid=43e9a311-bb9f-5f82-8efe-f80c51da25e8
                    with group(name='ELIF 3（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/2/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3a652059-c6e2-5415-8b8e-de1a8fa4b0c7 disabled=true
                        projected_action_0626 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/2/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=51292b86-b3d5-541d-a61c-53d6dafc6a17 disabled=true
                        projected_action_0627 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=34a05b31-5e2b-534d-96ad-63b10aac1bf7 disabled=true
                        projected_action_0628 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=06f09d73-b6e7-5e8c-8b7b-23df4fe3b5b8 disabled=true
                        projected_action_0629 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p49.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/2/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e6d976b2-3c3d-5b30-9853-2a887bb14362 disabled=true
                        projected_action_0630 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a74a76af-71ed-5485-9909-771c6374bea4 disabled=true
                        projected_action_0631 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p49.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P49"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=864e60ee-4c49-511d-a69a-053facf4ecd7 disabled=true
                        projected_action_0632 = robot.move_to_point(
                            point_id_or_robot_name='P49',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/2/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d048d68c-da64-594c-b095-d5d1a354250d disabled=true
                        projected_action_0633 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9178bd4a-1e99-5970-9077-f356d1c90f3a disabled=true
                        projected_action_0634 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p49.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p49.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=ec27ef8b-18bd-551b-938e-b3ae748a90cc disabled=true
                        projected_action_0635 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p49.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9808616f-116a-500f-99eb-c7e3a0bf5e44 disabled=true
                        projected_action_0636 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/2/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e2ff12b8-3716-54a1-8557-81bb54c1d4ab disabled=true
                        projected_action_0637 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/2/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=60fad7eb-8ab9-56fe-8f27-f0698d5f99a8 disabled=true
                        projected_action_0638 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 4（互斥分支）] robot_individual_pick@body/3/elifs/3/body 的静态审阅分支。
                    # unilab:node_uuid=9295d67c-6672-5393-a9ec-595fbbd86b80
                    with group(name='ELIF 4（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/3/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e600b17a-e9d2-5a3a-9b8c-298fb500b783 disabled=true
                        projected_action_0639 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/3/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d8a101fe-297a-5331-9ba4-cf7f6418eb6b disabled=true
                        projected_action_0640 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6120e0ff-4b79-544a-b736-4e41c0cfc1cb disabled=true
                        projected_action_0641 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b37bdbec-c9f7-5fe4-bfca-4ee609430772 disabled=true
                        projected_action_0642 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p50.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/3/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e0b532fe-a791-50d7-8c01-39066e5d1e7c disabled=true
                        projected_action_0643 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7df15539-4895-5c2b-9c86-99961b895b6d disabled=true
                        projected_action_0644 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p50.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P50"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e11a5d74-15a2-5d7c-929b-8f36f4f2d97b disabled=true
                        projected_action_0645 = robot.move_to_point(
                            point_id_or_robot_name='P50',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/3/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f5fe154c-dfd0-5cc5-a773-744c76135631 disabled=true
                        projected_action_0646 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=207ff1c1-cdca-5203-8107-660df88a2f3e disabled=true
                        projected_action_0647 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p50.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p50.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b28b61aa-87cb-595d-8504-aa2c60470580 disabled=true
                        projected_action_0648 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p50.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1341c503-21fe-5be6-a6c5-8002a4f5b67f disabled=true
                        projected_action_0649 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/3/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=aab2d248-1f1d-5eb0-a501-300c46b828a4 disabled=true
                        projected_action_0650 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/3/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a84d0d81-9dfa-5770-a7ed-ae65b18a18e8 disabled=true
                        projected_action_0651 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 5（互斥分支）] robot_individual_pick@body/3/elifs/4/body 的静态审阅分支。
                    # unilab:node_uuid=5e55587f-1a91-5b3f-8795-23decee12612
                    with group(name='ELIF 5（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/4/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=84455fbb-1a7e-5b34-99e7-0319d82067e5 disabled=true
                        projected_action_0652 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/4/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e712a6b0-b5a8-5add-a091-382e77d67bd7 disabled=true
                        projected_action_0653 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=231c0348-6de4-5d6d-a6a6-2ca96ed13bf2 disabled=true
                        projected_action_0654 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c72fb09d-be06-597c-96ad-31f5ab6bb4c7 disabled=true
                        projected_action_0655 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p51.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/4/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a0120d02-44b0-5a40-90ec-68e5244151e0 disabled=true
                        projected_action_0656 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3b8edd7b-5da8-5c93-9ce8-a4cc6200f6b2 disabled=true
                        projected_action_0657 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p51.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P51"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5bbd701f-e81e-5a50-ad24-21d991f3778a disabled=true
                        projected_action_0658 = robot.move_to_point(
                            point_id_or_robot_name='P51',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/4/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e1c22059-d902-5d34-a309-d508a36f525f disabled=true
                        projected_action_0659 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=160ce2f0-bf1f-5703-bc3e-4004ec729906 disabled=true
                        projected_action_0660 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p51.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-a.p51.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e2e86077-bdc4-517e-8874-bd4e71772ad1 disabled=true
                        projected_action_0661 = robot.move_to_point(
                            point_id_or_robot_name='staging-a.p51.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P45"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=29f024be-c9d5-55d2-8c66-fbb683a84d6c disabled=true
                        projected_action_0662 = robot.move_to_point(
                            point_id_or_robot_name='P45',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/4/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=42e016ed-a33e-5632-a79c-4a4470bc4b9d disabled=true
                        projected_action_0663 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/4/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4d8edaf4-3fa8-50fa-a386-edc78da613ce disabled=true
                        projected_action_0664 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELIF 6（互斥分支）] robot_individual_pick@body/3/elifs/5/body 的静态审阅分支。
                    # unilab:node_uuid=5e7ad25f-62a6-5e0f-8bee-fd1c9b768ad8
                    with group(name='ELIF 6（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/5/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7e612290-7851-5e28-b648-9cdd2da3bc72 disabled=true
                        projected_action_0665 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/5/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0f17fb78-9144-52d1-86fc-0402d306cbc9 disabled=true
                        projected_action_0666 = rail.ensure(
                            Rail_Target_Position=3,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=654c9c3f-5c6e-5e54-b475-c944a3936918 disabled=true
                        projected_action_0667 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=68fa3bb9-5270-55e9-9d4a-f90829cd109f disabled=true
                        projected_action_0668 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p53.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/5/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f8cbef1d-ab1f-5dca-879e-4dcb7dcdd387 disabled=true
                        projected_action_0669 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4f2b754a-343e-5383-82d2-b848e058edc4 disabled=true
                        projected_action_0670 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p53.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P53"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b3b2e466-8db8-5661-9fc7-18146e62a098 disabled=true
                        projected_action_0671 = robot.move_to_point(
                            point_id_or_robot_name='P53',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/5/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4cd79ff3-eb63-5fe0-b6b8-13b2b2596734 disabled=true
                        projected_action_0672 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=09f1045f-9517-5d54-9dc3-3114912d21b4 disabled=true
                        projected_action_0673 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p53.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p53.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2acbace3-8ef3-55fd-bef8-5a1fecbceb16 disabled=true
                        projected_action_0674 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p53.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=74f89ad6-6def-5652-9a01-d563e8a3b2d4 disabled=true
                        projected_action_0675 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/5/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0562551a-f1c1-54ae-baa1-451b928477c2 disabled=true
                        projected_action_0676 = robot.move_to_point(
                            point_id_or_robot_name='review-only',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/5/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=12fbd690-2fd9-54f8-8fcb-509b6f5aa121 disabled=true
                        projected_action_0677 = robot.require_anchor(
                            point_id='review-only',
                        )
                    # [BRANCH ELIF 7（互斥分支）] robot_individual_pick@body/3/elifs/6/body 的静态审阅分支。
                    # unilab:node_uuid=acb1597a-713e-5fac-86f3-5e518077e645
                    with group(name='ELIF 7（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/6/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8f2e4f42-7608-5fd2-8314-1cbfb4c82bff disabled=true
                        projected_action_0678 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/6/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0bdfcf4e-6e74-5b09-873c-fe3d4d9802e6 disabled=true
                        projected_action_0679 = rail.ensure(
                            Rail_Target_Position=3,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=28aaa075-eebe-578d-8b47-c49bbfda3fcb disabled=true
                        projected_action_0680 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3b18bbd9-3f70-51a2-8e7c-2ec6763e205e disabled=true
                        projected_action_0681 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p54.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/6/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5681c0f2-c7ef-5cc4-8155-06fe084b4da3 disabled=true
                        projected_action_0682 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7886da4e-a768-53e3-bbce-c2feba112935 disabled=true
                        projected_action_0683 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p54.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P54"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6aa958e1-2264-5af3-8a53-4ec984db0421 disabled=true
                        projected_action_0684 = robot.move_to_point(
                            point_id_or_robot_name='P54',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/6/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=878f332b-7092-5ad4-a286-5d97df58240f disabled=true
                        projected_action_0685 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0fd6937b-e2ae-5e3e-8683-ef1dfd3451da disabled=true
                        projected_action_0686 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p54.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p54.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=20db7a53-0a43-5b6d-bba5-76f3651337a8 disabled=true
                        projected_action_0687 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p54.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=89f677be-d829-5010-bf0a-9100c66c1720 disabled=true
                        projected_action_0688 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/6/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d72156dc-cc83-52f4-9b3d-6f12155e4fb1 disabled=true
                        projected_action_0689 = robot.move_to_point(
                            point_id_or_robot_name='review-only',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/6/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5653dc55-7f46-5889-87af-0cb1fba066e2 disabled=true
                        projected_action_0690 = robot.require_anchor(
                            point_id='review-only',
                        )
                    # [BRANCH ELIF 8（互斥分支）] robot_individual_pick@body/3/elifs/7/body 的静态审阅分支。
                    # unilab:node_uuid=542c44b4-6469-5f26-bb21-4d58ea2a6328
                    with group(name='ELIF 8（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/7/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a9261efb-0d90-59e7-92ab-b6984e6df9e4 disabled=true
                        projected_action_0691 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/7/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c88a6eac-7408-5809-9a5e-4596cacb34a8 disabled=true
                        projected_action_0692 = rail.ensure(
                            Rail_Target_Position=3,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=13707051-8e56-51b1-b146-d8c111c5272b disabled=true
                        projected_action_0693 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=d5cd0d81-6a31-5fb4-a0c5-44479b3fc860 disabled=true
                        projected_action_0694 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p55.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/7/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c7a2b5c5-fae3-54d5-a2d8-1631a909510a disabled=true
                        projected_action_0695 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e8fc9bbe-5408-5a9f-b72b-829f9dbc5356 disabled=true
                        projected_action_0696 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p55.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P55"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7d004ea9-47ee-5631-b444-eadfb258315c disabled=true
                        projected_action_0697 = robot.move_to_point(
                            point_id_or_robot_name='P55',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/7/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=eee3a8a0-9782-5daa-8786-6f03a7f3ef64 disabled=true
                        projected_action_0698 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=10740d35-ba99-569b-8ff6-45a3f893fb71 disabled=true
                        projected_action_0699 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p55.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p55.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4f41c2be-2f25-5c74-b85e-23debdd48f55 disabled=true
                        projected_action_0700 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p55.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6616b44b-b52e-5c2f-b48a-ed5651e15ad5 disabled=true
                        projected_action_0701 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/7/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=983473ef-47fc-5d56-b89d-b145dcbe5b14 disabled=true
                        projected_action_0702 = robot.move_to_point(
                            point_id_or_robot_name='review-only',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/7/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e23908a5-c265-57a5-90f3-f0e21c0264a6 disabled=true
                        projected_action_0703 = robot.require_anchor(
                            point_id='review-only',
                        )
                    # [BRANCH ELIF 9（互斥分支）] robot_individual_pick@body/3/elifs/8/body 的静态审阅分支。
                    # unilab:node_uuid=fad12ea0-d99c-5964-a81a-77259a70329d
                    with group(name='ELIF 9（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/8/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=9c394f60-7b1c-54fb-9358-7ff6f62fef53 disabled=true
                        projected_action_0704 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/8/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=726e2f4c-9975-54e9-adc2-63afae3c4dc7 disabled=true
                        projected_action_0705 = rail.ensure(
                            Rail_Target_Position=3,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8a8bb81f-c192-5df9-a5d4-d79ceabf93df disabled=true
                        projected_action_0706 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b03638aa-d3ed-57af-806e-5bb5ba5f79e3 disabled=true
                        projected_action_0707 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p56.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/8/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4e6ff937-60b9-5d8e-b41c-c281cdb109e5 disabled=true
                        projected_action_0708 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=91042862-b3e9-5009-bfea-903636a4f18c disabled=true
                        projected_action_0709 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p56.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P56"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=73af8bd6-66c7-5271-8bc8-18aca010dc00 disabled=true
                        projected_action_0710 = robot.move_to_point(
                            point_id_or_robot_name='P56',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/8/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=a64b33a6-bc37-5c88-adb5-d98caff2cb6e disabled=true
                        projected_action_0711 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=b7aafdc1-64c3-5beb-85a3-db2b62ce6a7a disabled=true
                        projected_action_0712 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p56.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p56.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=30b3098c-8d6a-5605-93ea-82bbe198e0df disabled=true
                        projected_action_0713 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p56.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f6f97f60-56db-5e01-a883-5ba72f0fa0a2 disabled=true
                        projected_action_0714 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/8/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=4d554ec3-00e9-5f70-ad8a-fc1131b04963 disabled=true
                        projected_action_0715 = robot.move_to_point(
                            point_id_or_robot_name='review-only',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/8/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6ebfcb67-7adf-5792-b371-95b1f441fa60 disabled=true
                        projected_action_0716 = robot.require_anchor(
                            point_id='review-only',
                        )
                    # [BRANCH ELIF 10（互斥分支）] robot_individual_pick@body/3/elifs/9/body 的静态审阅分支。
                    # unilab:node_uuid=413c929b-0ad0-54fe-985c-25abc9377693
                    with group(name='ELIF 10（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/9/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1f107a7c-c640-5295-a897-057c3141f0c6 disabled=true
                        projected_action_0717 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/9/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=762a0970-db82-5b3e-a944-773b1e095ee3 disabled=true
                        projected_action_0718 = rail.ensure(
                            Rail_Target_Position=3,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=478220e1-1cc5-5e25-adb7-ed6ee82d2230 disabled=true
                        projected_action_0719 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=df9ad9d6-5730-5ba3-a10b-4565cb384522 disabled=true
                        projected_action_0720 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p57.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/9/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3332f8c2-9157-54cc-90b2-b684f9e30647 disabled=true
                        projected_action_0721 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2331faa9-ca0b-5cb5-8494-9c53d6146d9b disabled=true
                        projected_action_0722 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p57.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P57"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=185cc284-6b4a-5694-b837-c3823a117113 disabled=true
                        projected_action_0723 = robot.move_to_point(
                            point_id_or_robot_name='P57',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/9/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1408f7d7-d6df-5aae-8451-53bad825a24e disabled=true
                        projected_action_0724 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c2b46776-6312-5d98-8ab8-6b6d4cfe9bd9 disabled=true
                        projected_action_0725 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p57.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p57.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6f5a0cb9-dbdd-513c-9439-6a25db8ef20e disabled=true
                        projected_action_0726 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p57.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3449d5ba-1fda-56ab-a928-cc56f85a6d73 disabled=true
                        projected_action_0727 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/9/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=158eae48-26bd-5f74-8f96-12b2d73086ee disabled=true
                        projected_action_0728 = robot.move_to_point(
                            point_id_or_robot_name='review-only',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/9/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=1bef270f-752c-5332-899d-0687c11a60d7 disabled=true
                        projected_action_0729 = robot.require_anchor(
                            point_id='review-only',
                        )
                    # [BRANCH ELIF 11（互斥分支）] robot_individual_pick@body/3/elifs/10/body 的静态审阅分支。
                    # unilab:node_uuid=3e145d03-b08a-54b2-94ae-1a36853eb0fc
                    with group(name='ELIF 11（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/10/body/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f6cb154f-f8e6-537c-8449-75ba8dfbfbf4 disabled=true
                        projected_action_0730 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_individual_pick@body/3/elifs/10/body/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":3}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=af3a0105-6117-52ed-a681-c8f701e926bd disabled=true
                        projected_action_0731 = rail.ensure(
                            Rail_Target_Position=3,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=cdf9a837-79ac-5c89-85a9-5afdbca9d411 disabled=true
                        projected_action_0732 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":12},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":15}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=21cb781b-f4ca-594a-9ed2-051075ae1dbc disabled=true
                        projected_action_0733 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p58.high',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/10/body/4；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=fb658a50-f05a-52c3-8fb9-61813bf5baa9 disabled=true
                        projected_action_0734 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c9fad8b3-148e-5c84-8dd8-f21efd79583c disabled=true
                        projected_action_0735 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p58.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/6；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P58"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=96e8152d-64fa-5b54-96d4-ee29a6d38154 disabled=true
                        projected_action_0736 = robot.move_to_point(
                            point_id_or_robot_name='P58',
                        )
                        # [ACTION robot.tool_action] 来源 robot_individual_pick@body/3/elifs/10/body/7；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-close"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=0ef94aaa-6e95-5972-ba76-f54b93b3fd89 disabled=true
                        projected_action_0737 = robot.tool_action(
                            action='gripper-close',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6d53ef2a-68fd-5d1a-aafe-49432edcf011 disabled=true
                        projected_action_0738 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p58.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"staging-b.p58.high"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=7d21ed4f-57d5-50f3-a2c4-c59a178b1a5b disabled=true
                        projected_action_0739 = robot.move_to_point(
                            point_id_or_robot_name='staging-b.p58.high',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P52"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c58ab60b-6ad9-5393-ab06-e701eab02c22 disabled=true
                        projected_action_0740 = robot.move_to_point(
                            point_id_or_robot_name='P52',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_individual_pick@body/3/elifs/10/body/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"var":"exit_anchor"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=f02eacc4-a930-553b-ba9c-a72922581ddf disabled=true
                        projected_action_0741 = robot.move_to_point(
                            point_id_or_robot_name='review-only',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_individual_pick@body/3/elifs/10/body/12；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"var":"exit_anchor"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2759144b-aa90-5bbe-a0e9-a0148e883f53 disabled=true
                        projected_action_0742 = robot.require_anchor(
                            point_id='review-only',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_individual_pick@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=e829a6c7-ebcd-53d1-8cba-60d3917e1278
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_individual_pick@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"individual.pick: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=18fcf55b-2b39-5653-9f8c-1a2f109500d3
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_individual_pick@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=f4567cc5-5ae9-5e29-9725-646b7cfe60f4 disabled=true
                            projected_control_0743 = material.review_control_node_v1(
                                operation_name='robot_individual_pick',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='cc5774ae8e9be2644c843edf5b39e2745282a7ccdc79ab43f19f14a4f145246d',
                            )
            # [CONTROL comment] 来源 transfer_collector_staging_a_to_scrape@body/5；原节点 {"op":"comment","text":"地轨到刮板区(位2); 放收集器到刮板夹具 (进-夹紧-退)"}
            # unilab:node_uuid=ad80b213-d4c3-5d15-8637-3a941d71e50e
            with group(name='说明 · 地轨到刮板区(位2); 放收集器到刮板夹具 (进-夹紧-退)'):
                # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/5；节点在本工作流中静态 disabled。
                # unilab:node_uuid=0e582393-fd67-59ce-8d3f-db16e04312cb disabled=true
                projected_control_0744 = material.review_control_node_v1(
                    operation_name='transfer_collector_staging_a_to_scrape',
                    node_path='body/5',
                    control_kind='comment',
                    expected_sha256='855499bf7fd92f6943e05a5742590c861532d34580f0b26a5770424a017953f3',
                )
            # [SUBWORKFLOW REF rail_move_safe · DEFINITION ALREADY SHOWN] 只读来源校验 transfer_collector_staging_a_to_scrape@body/6；节点在本工作流中静态 disabled。
            # unilab:node_uuid=6086bc26-5bbe-557d-89ea-c9fa26dc7be4 disabled=true
            projected_control_0745 = material.review_control_node_v1(
                operation_name='transfer_collector_staging_a_to_scrape',
                node_path='body/6',
                control_kind='run_script',
                expected_sha256='3375626c6140464d00aa9cbdffc04532e0598412bbb03a5cdc11186253b17bd1',
            )
            # [SUBWORKFLOW robot_scrape_holder_put_enter] 由 transfer_collector_staging_a_to_scrape@body/7 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=4a25b471-2679-5474-9f69-eac6ac385f42
            with group(name='↳ robot_scrape_holder_put_enter'):
                # [CONTROL comment] 来源 robot_scrape_holder_put_enter@body/0；原节点 {"op":"comment","text":"入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)"}
                # unilab:node_uuid=292857eb-1b55-564d-8b09-a7f34883a71e
                with group(name='说明 · 入口保证(手改): 确保在 home (安全邻域内自动回零) + 智能换刀到本流程固定工具 (小夹爪)'):
                    # [VERIFY comment] 只读来源校验 robot_scrape_holder_put_enter@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=05dfdc09-af12-5445-a9e5-8b7f7501df8a disabled=true
                    projected_control_0746 = material.review_control_node_v1(
                        operation_name='robot_scrape_holder_put_enter',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='25f59d38a3cb289ba1c633b91fdd26311ccf87057b51785a50a54f068eda985d',
                    )
                # [ACTION robot.home_ensure] 来源 robot_scrape_holder_put_enter@body/1；原节点 {"action":"robot.home_ensure","mode":"RUN","op":"call"}
                # unilab:node_uuid=6997cc55-bfed-5dc1-b1da-f3c20b876e41 disabled=true
                projected_action_0747 = robot.home_ensure()
                # [SUBWORKFLOW REF robot_tool_ensure · DEFINITION ALREADY SHOWN] 只读来源校验 robot_scrape_holder_put_enter@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=60f019ba-0ebc-5350-8ecc-eb6fe631e7b3 disabled=true
                projected_control_0748 = material.review_control_node_v1(
                    operation_name='robot_scrape_holder_put_enter',
                    node_path='body/2',
                    control_kind='run_script',
                    expected_sha256='2f67db039e17e0f68cdb218859ca6964a676cd9910413d82b4f9904cf420c8da',
                )
                # [CONTROL if] 来源 robot_scrape_holder_put_enter@body/3；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.put-enter: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_...
                # unilab:node_uuid=bfa06662-a882-5c1b-b63d-41cb00ecb4ad
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_scrape_holder_put_enter@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=ba65ebed-e383-54f4-8852-d0cf2ccccefb disabled=true
                    projected_control_0749 = material.review_control_node_v1(
                        operation_name='robot_scrape_holder_put_enter',
                        node_path='body/3',
                        control_kind='if',
                        expected_sha256='889ead3dd615334a51a10135bcf5cf81a22f302b8c78cfe8118136239929efb7',
                    )
                    # [BRANCH THEN（互斥分支）] robot_scrape_holder_put_enter@body/3/then 的静态审阅分支。
                    # unilab:node_uuid=7b103803-a560-5248-89ae-b3b18ea5b4c6
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_scrape_holder_put_enter@body/3/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=34bb5b6d-dde2-531c-8f1c-d47411a1e9fa disabled=true
                        projected_action_0750 = robot.require_anchor(
                            point_id='P1',
                        )
                        # [ACTION rail.ensure] 来源 robot_scrape_holder_put_enter@body/3/then/1；原节点 {"action":"rail.ensure","args":{"Rail_Target_Position":{"lit":2}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=36459ec2-7a32-5751-9668-40258587cd35 disabled=true
                        projected_action_0751 = rail.ensure(
                            Rail_Target_Position=2,
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/2；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P67"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=2ee1a9dd-873e-5b9f-aebe-2550664864d6 disabled=true
                        projected_action_0752 = robot.move_to_point(
                            point_id_or_robot_name='P67',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.far"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=08121fff-25a3-516d-b1ff-e1de52e6ab12 disabled=true
                        projected_action_0753 = robot.move_to_point(
                            point_id_or_robot_name='scrape-holder-put.far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.near"},"vel":{"lit":10}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6f98605b-7063-5677-9e5b-7ea7c49f42ff disabled=true
                        projected_action_0754 = robot.move_to_point(
                            point_id_or_robot_name='scrape-holder-put.near',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P68"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c3b241ba-36ab-5a35-b15f-b9eba778103d disabled=true
                        projected_action_0755 = robot.move_to_point(
                            point_id_or_robot_name='P68',
                        )
                        # [CONTROL comment] 来源 robot_scrape_holder_put_enter@body/3/then/6；原节点 {"op":"comment","text":"[手改 #3 planB] 微调对位(x±/y±)前移至此: 放到位后先精定位, 再由 transfer 触发 press_cylinder(true) 夹紧, 最后 put_exit 松爪退回"}
                        # unilab:node_uuid=6e13624a-5b8a-5f3a-b20a-78f0301e3cac
                        with group(name='说明 · [手改 #3 planB] 微调对位(x±/y±)前移至此: 放到位后先精定位, 再由 transfer 触发 '):
                            # [VERIFY comment] 只读来源校验 robot_scrape_holder_put_enter@body/3/then/6；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=fe7ad1ff-4606-5469-87be-a3a758f4a741 disabled=true
                            projected_control_0756 = material.review_control_node_v1(
                                operation_name='robot_scrape_holder_put_enter',
                                node_path='body/3/then/6',
                                control_kind='comment',
                                expected_sha256='eaafeb2fe9c5b3588791aa1f250b354965bdb69679c7f3dfbfcae5539fbe5e8a',
                            )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/7；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.x-plus"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=27cb51b8-ab51-51e9-a252-916a0a5f4dd1 disabled=true
                        projected_action_0757 = robot.move_to_point(
                            point_id_or_robot_name='scrape-holder-put.x-plus',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/8；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.x-minus"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=eea40c1a-5895-5dff-818a-37b32240bee8 disabled=true
                        projected_action_0758 = robot.move_to_point(
                            point_id_or_robot_name='scrape-holder-put.x-minus',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/9；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P68"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=e09c5524-192a-5726-ab10-4d7abddcddc5 disabled=true
                        projected_action_0759 = robot.move_to_point(
                            point_id_or_robot_name='P68',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/10；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.y-minus"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5e8d695c-e2aa-5798-9969-2eddaa9e2323 disabled=true
                        projected_action_0760 = robot.move_to_point(
                            point_id_or_robot_name='scrape-holder-put.y-minus',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/11；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.y-plus"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=8c7297fa-c29a-5c9c-9faf-c198d48b3c41 disabled=true
                        projected_action_0761 = robot.move_to_point(
                            point_id_or_robot_name='scrape-holder-put.y-plus',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_enter@body/3/then/12；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":6},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"P68"},"vel":{"lit":5}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=53c52730-94b6-5d24-af31-5ed56eb07a62 disabled=true
                        projected_action_0762 = robot.move_to_point(
                            point_id_or_robot_name='P68',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_scrape_holder_put_enter@body/3/then/13；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P68"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5e1237f0-7ba8-5353-bbc4-29a0c9583f81 disabled=true
                        projected_action_0763 = robot.require_anchor(
                            point_id='P68',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_scrape_holder_put_enter@body/3/else 的静态审阅分支。
                    # unilab:node_uuid=e85ef63e-1fbd-5c3a-951a-0b6e194e3608
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_scrape_holder_put_enter@body/3/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.put-enter: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=10561d41-84ad-58a4-b2d8-13db844c8e88
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_scrape_holder_put_enter@body/3/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=d2eeb8c2-050a-5bf4-a466-280b5bf006f7 disabled=true
                            projected_control_0764 = material.review_control_node_v1(
                                operation_name='robot_scrape_holder_put_enter',
                                node_path='body/3/else/0',
                                control_kind='raise',
                                expected_sha256='ffc292dd7914745d71afcb9fc032a1108cd8929a102a53b2352d6717519577b8',
                            )
            # [CONTROL comment] 来源 transfer_collector_staging_a_to_scrape@body/8；原节点 {"op":"comment","text":"[#3] 收集器已精定位(put_enter 含微调); 机器人保持夹持, 先下压气缸夹紧收集器"}
            # unilab:node_uuid=8f546297-f4fd-52be-bfdb-fbb34873cb5b
            with group(name='说明 · [#3] 收集器已精定位(put_enter 含微调); 机器人保持夹持, 先下压气缸夹紧收集器'):
                # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/8；节点在本工作流中静态 disabled。
                # unilab:node_uuid=dba185af-9676-5fa7-b688-959fe3b2c86e disabled=true
                projected_control_0765 = material.review_control_node_v1(
                    operation_name='transfer_collector_staging_a_to_scrape',
                    node_path='body/8',
                    control_kind='comment',
                    expected_sha256='c9334a73422d291c6f604a5ae405f8c4ca620b2c55ddbefb803db235c7801c57',
                )
            # [ACTION photoscrape.press_cylinder] 来源 transfer_collector_staging_a_to_scrape@body/9；原节点 {"action":"photoscrape.press_cylinder","args":{"pressed":{"lit":true}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=a554071b-d3e3-5d10-903e-999eece38f24 disabled=true
            projected_action_0766 = photoscrape.press_cylinder(
                pressed=True,
            )
            # [CONTROL comment] 来源 transfer_collector_staging_a_to_scrape@body/10；原节点 {"op":"comment","text":"夹紧确认后机器人松爪退出 (put_exit 开头 require_anchor P68 校验夹持期间未移位)"}
            # unilab:node_uuid=9be18566-89fd-50fe-842d-902106708884
            with group(name='说明 · 夹紧确认后机器人松爪退出 (put_exit 开头 require_anchor P68 校验夹持期间未移位)'):
                # [VERIFY comment] 只读来源校验 transfer_collector_staging_a_to_scrape@body/10；节点在本工作流中静态 disabled。
                # unilab:node_uuid=7c45fa63-017f-587c-8004-38986fefb5ea disabled=true
                projected_control_0767 = material.review_control_node_v1(
                    operation_name='transfer_collector_staging_a_to_scrape',
                    node_path='body/10',
                    control_kind='comment',
                    expected_sha256='59bd34c997874336c64e830b7836720460df4f403ba36fcd3465453b75033a29',
                )
            # [SUBWORKFLOW robot_scrape_holder_put_exit] 由 transfer_collector_staging_a_to_scrape@body/11 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=327818e8-2cd5-5a27-8447-fd90a08c510e
            with group(name='↳ robot_scrape_holder_put_exit'):
                # [CONTROL if] 来源 robot_scrape_holder_put_exit@body/0；原节点 {"cond":{"binop":"==","left":{"var":"station_id"},"right":{"lit":"default"}},"elifs":[],"else":[{"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.put-exit: 无效选择值"},"op":"raise"}],"op":"if","then":[{"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P68"},"pos_tol_m...
                # unilab:node_uuid=72ccdff3-96aa-53c9-a265-7ede2c932a5b
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 robot_scrape_holder_put_exit@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=a61dd008-2815-5c78-9d68-3ab79809902e disabled=true
                    projected_control_0768 = material.review_control_node_v1(
                        operation_name='robot_scrape_holder_put_exit',
                        node_path='body/0',
                        control_kind='if',
                        expected_sha256='34b9488360a3c2764ff71cc03d5c63982e06cf6c556f3dbe90d7b748760b1d48',
                    )
                    # [BRANCH THEN（互斥分支）] robot_scrape_holder_put_exit@body/0/then 的静态审阅分支。
                    # unilab:node_uuid=8388465a-128d-5c75-ba08-e7667cdf9284
                    with group(name='THEN（互斥分支）'):
                        # [ACTION robot.require_anchor] 来源 robot_scrape_holder_put_exit@body/0/then/0；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P68"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=3248044f-d674-5dc0-9841-d42734459153 disabled=true
                        projected_action_0769 = robot.require_anchor(
                            point_id='P68',
                        )
                        # [CONTROL comment] 来源 robot_scrape_holder_put_exit@body/0/then/1；原节点 {"op":"comment","text":"[手改 #3 planB] 微调对位(x±/y±)已前移至 put_enter; 收集器已由 press_cylinder(true) 夹紧, 本流程仅确认在位(上方 require_anchor P68)后松爪退回"}
                        # unilab:node_uuid=b3e53d06-daca-520b-b524-84b6d84443fc
                        with group(name='说明 · [手改 #3 planB] 微调对位(x±/y±)已前移至 put_enter; 收集器已由 press_cyl'):
                            # [VERIFY comment] 只读来源校验 robot_scrape_holder_put_exit@body/0/then/1；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=4069a816-62ba-5691-8ff1-2ffc87f93bb6 disabled=true
                            projected_control_0770 = material.review_control_node_v1(
                                operation_name='robot_scrape_holder_put_exit',
                                node_path='body/0/then/1',
                                control_kind='comment',
                                expected_sha256='37d8dce2c25cab12a35df6c1a205d43efe467c8a44f2613c653a3155667fa6c0',
                            )
                        # [ACTION robot.tool_action] 来源 robot_scrape_holder_put_exit@body/0/then/2；原节点 {"action":"robot.tool_action","args":{"action":{"lit":"gripper-open"},"timeout_ms":{"lit":3000}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c4b42e7e-8ae7-5b7f-85e8-61dea0290251 disabled=true
                        projected_action_0771 = robot.tool_action(
                            action='gripper-open',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_exit@body/0/then/3；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":18},"cp":{"lit":0},"motion":{"lit":"move_l"},"point_id_or_robot_name":{"lit":"scrape-holder-put.far"},"vel":{"lit":20}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c5c9f6c5-a6c2-5e6e-a13e-22fc854b67bd disabled=true
                        projected_action_0772 = robot.move_to_point(
                            point_id_or_robot_name='scrape-holder-put.far',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_exit@body/0/then/4；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":60},"cp":{"lit":20},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P67"},"vel":{"lit":50}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=5015eb15-f6d3-5c26-b722-9e67141af533 disabled=true
                        projected_action_0773 = robot.move_to_point(
                            point_id_or_robot_name='P67',
                        )
                        # [ACTION robot.move_to_point] 来源 robot_scrape_holder_put_exit@body/0/then/5；原节点 {"action":"robot.move_to_point","args":{"acc":{"lit":50},"cp":{"lit":2},"motion":{"lit":"move_j"},"point_id_or_robot_name":{"lit":"P1"},"vel":{"lit":37}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=26ac6442-de6a-5061-a43a-0a76f7284a0e disabled=true
                        projected_action_0774 = robot.move_to_point(
                            point_id_or_robot_name='P1',
                        )
                        # [ACTION robot.require_anchor] 来源 robot_scrape_holder_put_exit@body/0/then/6；原节点 {"action":"robot.require_anchor","args":{"joint_tol_deg":{"lit":2.0},"point_id":{"lit":"P1"},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=c168f1c1-7033-5d9d-9306-24fdeffb99b8 disabled=true
                        projected_action_0775 = robot.require_anchor(
                            point_id='P1',
                        )
                    # [BRANCH ELSE（互斥分支）] robot_scrape_holder_put_exit@body/0/else 的静态审阅分支。
                    # unilab:node_uuid=639980e1-659e-5c9e-98f3-926facb3879d
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL raise] 来源 robot_scrape_holder_put_exit@body/0/else/0；原节点 {"error":"ROBOT_FLOW_SELECTOR","message":{"lit":"scrape.holder.put-exit: 无效选择值"},"op":"raise"}
                        # unilab:node_uuid=c2efd994-734d-5445-ae48-d743be88a35a
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 robot_scrape_holder_put_exit@body/0/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=8ee5780d-893b-542c-a3fe-b6348b953ef6 disabled=true
                            projected_control_0776 = material.review_control_node_v1(
                                operation_name='robot_scrape_holder_put_exit',
                                node_path='body/0/else/0',
                                control_kind='raise',
                                expected_sha256='fea1843dd5dad78a2ed780489140855b9748bf64c63d146c4f1ef673ba8c7fef',
                            )
    # [EXECUTE ROOT pf_s7_consumables] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=100775bf-a237-54a8-ab28-660e79576ef9
    execution = material.run_operation_review_v1(
        operation_name='pf_s7_consumables',
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
