from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_sampling import PLCSampling


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
sampling: PLCSampling = device('plc_sampling')


@workflow(
    workflow_uuid='b631569f-12fd-5b92-a2b4-2c6ecd9d8403',
    displayname='2-1 点样执行 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s2_spot_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s2_spot] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=bb708f2c-77a6-5fe6-a7e6-da8fa31d413b
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s2_spot@body/0；原节点 {"op":"comment","text":"点样执行: 吸液 -> 条带点样 -> 吹干; 全程只占上样工位、不占机器人, 与展缸预备并行"}
        # unilab:node_uuid=b0ea6d04-9c74-5a59-8000-3a1f81670bee
        with group(name='说明 · 点样执行: 吸液 -> 条带点样 -> 吹干; 全程只占上样工位、不占机器人, 与展缸预备并行'):
            # [VERIFY comment] 只读来源校验 pf_s2_spot@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=1ee29606-b15d-562e-a895-0d79be7a911d disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s2_spot',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='9d32413268e2aa8da3032089c2d7dfdae67e84cfd89023e5d594b035c4b67067',
            )
        # [SUBWORKFLOW sampling_execute] 由 pf_s2_spot@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=8b12a59e-75d5-5a21-af9e-eb5b463d8680
        with group(name='↳ sampling_execute'):
            # [CONTROL comment] 来源 sampling_execute@body/0；原节点 {"op":"comment","text":"派生体积计算 + 守卫: 全部在 sampling_volume_model 里 (模型推导注释同处), 本处只取回四个派生量"}
            # unilab:node_uuid=f663add2-192a-547f-9ab3-9472f8678d23
            with group(name='说明 · 派生体积计算 + 守卫: 全部在 sampling_volume_model 里 (模型推导注释同处), 本处只'):
                # [VERIFY comment] 只读来源校验 sampling_execute@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=277f9397-ec31-5fca-92a7-f1ed40d8428d disabled=true
                projected_control_0002 = material.review_control_node_v1(
                    operation_name='sampling_execute',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='b829a9dc009509dc6b8c80f41c8d9b87f857f257060d526723da1047af42b981',
                )
            # [SUBWORKFLOW sampling_volume_model] 由 sampling_execute@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
            # unilab:node_uuid=7c509d09-4a7e-5c94-848c-7f125681bf4a
            with group(name='↳ sampling_volume_model'):
                # [CONTROL comment] 来源 sampling_volume_model@body/0；原节点 {"op":"comment","text":"派生体积计算 + 守卫 (体积模型见文件头注释)"}
                # unilab:node_uuid=5757cecf-4ef8-56ca-a7c0-d81c8c1e0dc7
                with group(name='说明 · 派生体积计算 + 守卫 (体积模型见文件头注释)'):
                    # [VERIFY comment] 只读来源校验 sampling_volume_model@body/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=fb1d66c9-a1f1-5c6a-baaf-c3dfea578ae1 disabled=true
                    projected_control_0003 = material.review_control_node_v1(
                        operation_name='sampling_volume_model',
                        node_path='body/0',
                        control_kind='comment',
                        expected_sha256='52c5826d842d42e3362635f59ac0c88e55f96f2ca9de6dec560ed3f6b7796a4c',
                    )
                # [CONTROL assign] 来源 sampling_volume_model@body/1；原节点 {"op":"assign","target":{"var":"aspirate_total_ml"},"value":{"binop":"+","left":{"var":"sample_volume_ml"},"right":{"var":"over_aspirate_ml"}}}
                # unilab:node_uuid=95b51911-9e71-50f9-953a-d5c20571c746
                with group(name='变量赋值'):
                    # [VERIFY assign] 只读来源校验 sampling_volume_model@body/1；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=e2e58f6a-9966-513b-be20-eaa72b9d25a9 disabled=true
                    projected_control_0004 = material.review_control_node_v1(
                        operation_name='sampling_volume_model',
                        node_path='body/1',
                        control_kind='assign',
                        expected_sha256='d9f024f0091f26648c1178ba35c332575c326f3832af33ce0ece77606a8bf294',
                    )
                # [CONTROL comment] 来源 sampling_volume_model@body/2；原节点 {"op":"comment","text":"S 取合法窗口 (E-1.125, E-1.125+G) 正中: 空喷段 + 半个气隔断; 详见文件头体积模型"}
                # unilab:node_uuid=5ace19bf-7b66-56ff-9d08-883c493b97a1
                with group(name='说明 · S 取合法窗口 (E-1.125, E-1.125+G) 正中: 空喷段 + 半个气隔断; 详见文件头体积模型'):
                    # [VERIFY comment] 只读来源校验 sampling_volume_model@body/2；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=af4508f4-be57-5fcb-8dee-58d1bf65d459 disabled=true
                    projected_control_0005 = material.review_control_node_v1(
                        operation_name='sampling_volume_model',
                        node_path='body/2',
                        control_kind='comment',
                        expected_sha256='97d8140b69d15b4ba9c5f7aa8b434fa53cd62a96c9916976dd37a0d23de3ede0',
                    )
                # [CONTROL assign] 来源 sampling_volume_model@body/3；原节点 {"op":"assign","target":{"var":"spray_margin_ml"},"value":{"binop":"+","left":{"binop":"-","left":{"var":"over_aspirate_ml"},"right":{"lit":1.125}},"right":{"binop":"/","left":{"var":"air_gap_ml"},"right":{"lit":2.0}}}}
                # unilab:node_uuid=5d14314e-bd7e-515d-9a9d-20e188a00ea8
                with group(name='变量赋值'):
                    # [VERIFY assign] 只读来源校验 sampling_volume_model@body/3；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=c1f74f18-658d-5ba9-a68a-ae6e4b9de7c9 disabled=true
                    projected_control_0006 = material.review_control_node_v1(
                        operation_name='sampling_volume_model',
                        node_path='body/3',
                        control_kind='assign',
                        expected_sha256='063974fd90f11b9cb4fff512766bd5b7047014bec551ddb5e9c2266d6bbe1100',
                    )
                # [CONTROL assign] 来源 sampling_volume_model@body/4；原节点 {"op":"assign","target":{"var":"band_end_ml"},"value":{"binop":"-","left":{"binop":"+","left":{"var":"air_gap_ml"},"right":{"var":"over_aspirate_ml"}},"right":{"var":"spray_margin_ml"}}}
                # unilab:node_uuid=f395d656-a535-522c-ada8-f5043efad3e7
                with group(name='变量赋值'):
                    # [VERIFY assign] 只读来源校验 sampling_volume_model@body/4；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=96cc6601-f43a-5ab4-ba35-b2d5604cf20e disabled=true
                    projected_control_0007 = material.review_control_node_v1(
                        operation_name='sampling_volume_model',
                        node_path='body/4',
                        control_kind='assign',
                        expected_sha256='bca03e4a0cd78d09c1baffe323e5d792455cc622cdf7aaf31fa94c4cecb9b9f5',
                    )
                # [CONTROL assign] 来源 sampling_volume_model@body/5；原节点 {"op":"assign","target":{"var":"aspirate_round_ml"},"value":{"binop":"+","left":{"var":"rinse_volume_ml"},"right":{"var":"over_aspirate_ml"}}}
                # unilab:node_uuid=26848280-f32b-5cc8-9eaf-36f435ccffea
                with group(name='变量赋值'):
                    # [VERIFY assign] 只读来源校验 sampling_volume_model@body/5；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=204af2c1-c9a2-5838-9e84-b0ba4ed8534c disabled=true
                    projected_control_0008 = material.review_control_node_v1(
                        operation_name='sampling_volume_model',
                        node_path='body/5',
                        control_kind='assign',
                        expected_sha256='1362d3f22d936698d6cf6c4ba5fa0012f06a194b61298ec6b4b36af838bfe652',
                    )
                # [CONTROL comment] 来源 sampling_volume_model@body/6；原节点 {"op":"comment","text":"守卫: 排空余量必须真正超过针流路死体积(否则样品没被拖过三通, 切阀即整段作废); ui.min 只是运行前兜底, 动作层不校验该值"}
                # unilab:node_uuid=27c6db9d-6c2b-5810-ae7b-6ad14c5c2aa7
                with group(name='说明 · 守卫: 排空余量必须真正超过针流路死体积(否则样品没被拖过三通, 切阀即整段作废); ui.min 只是运行前兜'):
                    # [VERIFY comment] 只读来源校验 sampling_volume_model@body/6；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=f6269b7e-176c-540f-86a9-05c7594e4a36 disabled=true
                    projected_control_0009 = material.review_control_node_v1(
                        operation_name='sampling_volume_model',
                        node_path='body/6',
                        control_kind='comment',
                        expected_sha256='7ce7d03eea47324625a7b6448bd6761a9a0c355dd3c6ba610d5e6efa078c9dfa',
                    )
                # [CONTROL if] 来源 sampling_volume_model@body/7；原节点 {"cond":{"binop":"<=","left":{"var":"over_aspirate_ml"},"right":{"lit":1.125}},"elifs":[{"body":[{"error":"SAMPLING_VOLUME_CHAIN","message":{"lit":"点样活塞终点 N=针流路死体积+气隔断/2 越界 [0,5] mL, 请检查气隔断旋钮"},"op":"raise"}],"cond":{"binop":"or","left":{"binop":"<","left":{"var":"band_end_ml"},"right":{"lit":0.0}},"right":{"binop":">",...
                # unilab:node_uuid=c3689cbe-bac2-53cc-ba7b-ec1db542378e
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 sampling_volume_model@body/7；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=6aa455ff-5e32-5123-ad4b-4a7aea2f45aa disabled=true
                    projected_control_0010 = material.review_control_node_v1(
                        operation_name='sampling_volume_model',
                        node_path='body/7',
                        control_kind='if',
                        expected_sha256='c8d3e759fcba73955828b695bb3cb94fd1d3de350d794ed7b145435b706fff99',
                    )
                    # [BRANCH THEN（互斥分支）] sampling_volume_model@body/7/then 的静态审阅分支。
                    # unilab:node_uuid=9c31cca6-76bf-53d4-b89a-f874d8fbeced
                    with group(name='THEN（互斥分支）'):
                        # [CONTROL raise] 来源 sampling_volume_model@body/7/then/0；原节点 {"error":"SAMPLING_VOLUME_CHAIN","message":{"lit":"排空余量必须大于针流路死体积 1.125 mL, 否则样品切阀后仍留在针流路里整段作废"},"op":"raise"}
                        # unilab:node_uuid=848d31d7-bf45-57a1-a0a9-a48301e93f62
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 sampling_volume_model@body/7/then/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=bed58600-bb77-5bd7-aa85-c72e1c1d8ba9 disabled=true
                            projected_control_0011 = material.review_control_node_v1(
                                operation_name='sampling_volume_model',
                                node_path='body/7/then/0',
                                control_kind='raise',
                                expected_sha256='9d4f62990864ccf1a94b8ed38ffd322304127c443ecc96afc63b6b6c3867781c',
                            )
                    # [BRANCH ELIF 1（互斥分支）] sampling_volume_model@body/7/elifs/0/body 的静态审阅分支。
                    # unilab:node_uuid=4a0a4f1b-a041-5631-8d2a-259dbb2271b6
                    with group(name='ELIF 1（互斥分支）'):
                        # [CONTROL raise] 来源 sampling_volume_model@body/7/elifs/0/body/0；原节点 {"error":"SAMPLING_VOLUME_CHAIN","message":{"lit":"点样活塞终点 N=针流路死体积+气隔断/2 越界 [0,5] mL, 请检查气隔断旋钮"},"op":"raise"}
                        # unilab:node_uuid=c002f5e8-5ff5-54f0-ad31-9b57f03d4629
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 sampling_volume_model@body/7/elifs/0/body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=45cbbdc2-abe8-5eb6-9111-f28cb37aa9ce disabled=true
                            projected_control_0012 = material.review_control_node_v1(
                                operation_name='sampling_volume_model',
                                node_path='body/7/elifs/0/body/0',
                                control_kind='raise',
                                expected_sha256='fc021fd63950ae3570c03819d1905ba8db011cc929657bc3aec29891b02ceb81',
                            )
                    # [BRANCH ELIF 2（互斥分支）] sampling_volume_model@body/7/elifs/1/body 的静态审阅分支。
                    # unilab:node_uuid=87257c0b-3ee8-5cf4-8f7e-ff0b25628fe3
                    with group(name='ELIF 2（互斥分支）'):
                        # [CONTROL raise] 来源 sampling_volume_model@body/7/elifs/1/body/0；原节点 {"error":"SAMPLING_VOLUME_CHAIN","message":{"lit":"单轮吸取总量超过 15 mL (样品或润洗液 + 排空余量), 再多样品段会被抽进泵腔造成交叉污染; 该上限与 sampling.aspirate 动作层硬闸同值, 在此提前拦截以免跑到一半才被拒"},"op":"raise"}
                        # unilab:node_uuid=9dbe6581-469e-5b1f-8335-15223d05c229
                        with group(name='抛出流程错误'):
                            # [VERIFY raise] 只读来源校验 sampling_volume_model@body/7/elifs/1/body/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=342777a2-15b9-5053-8a9c-60089fe335b6 disabled=true
                            projected_control_0013 = material.review_control_node_v1(
                                operation_name='sampling_volume_model',
                                node_path='body/7/elifs/1/body/0',
                                control_kind='raise',
                                expected_sha256='f7f2c0dd180a75bfbc32cbf71addbfc0f62d712ad59fddc484d5c227b879a0bd',
                            )
                    # [BRANCH ELSE（互斥分支）] sampling_volume_model@body/7/else 的静态审阅分支。
                    # unilab:node_uuid=8b9fba02-6610-509f-bfb8-dbafa375f79f
                    with group(name='ELSE（互斥分支）'):
                        # [EMPTY ELSE（互斥分支）] 只读来源校验 sampling_volume_model@body/7；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=5def24d0-64ec-5b9a-9d85-72b8112ec08a disabled=true
                        projected_control_0014 = material.review_control_node_v1(
                            operation_name='sampling_volume_model',
                            node_path='body/7',
                            control_kind='if',
                            expected_sha256='c8d3e759fcba73955828b695bb3cb94fd1d3de350d794ed7b145435b706fff99',
                        )
            # [CONTROL comment] 来源 sampling_execute@body/2；原节点 {"op":"comment","text":"execute: 首轮 = 过阀排空吸取 (A50 内置气隔断: 移孔位前于空气中吸G, 再下探抽干孔, 样品整段拖过三通)"}
            # unilab:node_uuid=88b6f147-e8ed-50bd-984f-b7e9621a2423
            with group(name='说明 · execute: 首轮 = 过阀排空吸取 (A50 内置气隔断: 移孔位前于空气中吸G, 再下探抽干孔, 样品整'):
                # [VERIFY comment] 只读来源校验 sampling_execute@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=41a7b8ef-c332-596f-b080-43e7e3a79714 disabled=true
                projected_control_0015 = material.review_control_node_v1(
                    operation_name='sampling_execute',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='ec4422ecd6f19be526669bce8f911a739c8cac8eab346583bbb7994160cec9fe',
                )
            # [CONTROL comment] 来源 sampling_execute@body/3；原节点 {"op":"comment","text":"全程无真空: aspirate 的两条指令均为口3回抽, 分配阀不切废液口2, 无废液流量需抽走"}
            # unilab:node_uuid=b74f0eb7-5874-50d1-98da-c6af7887c907
            with group(name='说明 · 全程无真空: aspirate 的两条指令均为口3回抽, 分配阀不切废液口2, 无废液流量需抽走'):
                # [VERIFY comment] 只读来源校验 sampling_execute@body/3；节点在本工作流中静态 disabled。
                # unilab:node_uuid=4b763b2f-0b03-501f-9e58-2b7f643e5591 disabled=true
                projected_control_0016 = material.review_control_node_v1(
                    operation_name='sampling_execute',
                    node_path='body/3',
                    control_kind='comment',
                    expected_sha256='ae72e871b505785aed60aa80f0971ee88896943d18c7c3fd64adfd47c8bcf89f',
                )
            # [ACTION sampling.aspirate] 来源 sampling_execute@body/4；原节点 {"action":"sampling.aspirate","args":{"air_gap_ml":{"var":"air_gap_ml"},"asp_speed":{"lit":50},"plate_no":{"var":"plate_no"},"plate_spec":{"var":"plate_spec"},"sample_volume_ml":{"var":"aspirate_total_ml"},"step_delay":{"lit":1500},"well":{"var":"well"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=9fbf0147-e14f-5e3d-b30f-69c5d2c1e0af disabled=true
            projected_action_0017 = sampling.aspirate(
                plate_spec='4×6',
                plate_no='1',
                well='A1',
            )
            # [CONTROL comment] 来源 sampling_execute@body/5；原节点 {"op":"comment","text":"execute: 单条带点样+连续吹干, 活塞停在 N (泵腔余液为纯驱动清洗液)"}
            # unilab:node_uuid=5e471423-b460-5dd7-bda0-d48137588874
            with group(name='说明 · execute: 单条带点样+连续吹干, 活塞停在 N (泵腔余液为纯驱动清洗液)'):
                # [VERIFY comment] 只读来源校验 sampling_execute@body/5；节点在本工作流中静态 disabled。
                # unilab:node_uuid=3b0a4a64-0ae8-5cec-8e8d-3ea61c3f65eb disabled=true
                projected_control_0018 = material.review_control_node_v1(
                    operation_name='sampling_execute',
                    node_path='body/5',
                    control_kind='comment',
                    expected_sha256='17365a714842c66f273f1d600b4bd50edc50c65a495b4e8d480aff0a2b19cac4',
                )
            # [ACTION sampling.spot_band_layer] 来源 sampling_execute@body/6；原节点 {"action":"sampling.spot_band_layer","args":{"dry_cycles":{"var":"dry_cycles"},"dry_speed_mm_s":{"var":"dry_speed_mm_s"},"ref_spot":{"lit":"spot_pose"},"spot_disp_speed":{"var":"spot_disp_speed"},"spot_end_position_ml":{"var":"band_end_ml"},"spot_speed_mm_s":{"var":"spot_speed_mm_s"},"step_delay":{"lit":1500},"x_end":{"var":...
            # unilab:node_uuid=0324a2b1-3dfa-5bfc-bd90-7f0872dda0a1 disabled=true
            projected_action_0019 = sampling.spot_band_layer(
                ref_spot='spot_pose',
            )
            # [CONTROL comment] 来源 sampling_execute@body/7；原节点 {"op":"comment","text":"润洗回收轮 xN: 回打余量(实排针流路气柱)+润洗混匀(A55自带气隔断, 终态活塞=G) -> 排空吸取 -> 点样"}
            # unilab:node_uuid=a0eefc90-a932-5d5e-802e-546ca7578c38
            with group(name='说明 · 润洗回收轮 xN: 回打余量(实排针流路气柱)+润洗混匀(A55自带气隔断, 终态活塞=G) -> 排空吸取 -'):
                # [VERIFY comment] 只读来源校验 sampling_execute@body/7；节点在本工作流中静态 disabled。
                # unilab:node_uuid=2cda9bfb-5853-5f08-b96a-91233d95d3d9 disabled=true
                projected_control_0020 = material.review_control_node_v1(
                    operation_name='sampling_execute',
                    node_path='body/7',
                    control_kind='comment',
                    expected_sha256='a0b196d054ee4b4e068cce4caeba8bf33ea55d742dcd1be2cc140aa3a9d8490f',
                )
            # [LOOP for · BODY NOT EXPANDED] 只读来源校验 sampling_execute@body/8；节点在本工作流中静态 disabled。
            # unilab:node_uuid=6484565b-e93b-5768-9038-dca7ccf0cd29 disabled=true
            projected_control_0021 = material.review_control_node_v1(
                operation_name='sampling_execute',
                node_path='body/8',
                control_kind='for',
                expected_sha256='9bee4fc22510df57121dbee3dfa3c3ad9fd7f30dac35b8f960005afd620a13bf',
            )
    # [EXECUTE ROOT pf_s2_spot] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=9536cae3-d159-5141-b99e-74f139dd29ce
    execution = material.run_operation_review_v1(
        operation_name='pf_s2_spot',
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
