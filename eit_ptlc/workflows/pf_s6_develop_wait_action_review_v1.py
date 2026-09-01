from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.plc_develop import PLCDevelop
from eit_ptlc.unilab_domain.devices.material import MaterialProxy


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


@workflow(
    workflow_uuid='ea15b5e8-6ed1-5cdd-a2c6-61b3f3176103',
    displayname='5-1 展开等待 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s6_develop_wait_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s6_develop_wait] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=649a57dc-7c7f-5807-a445-3ac2aa6d59c2
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s6_develop_wait@body/0；原节点 {"op":"comment","text":"起点先自动采集干板参考 (host 动作, 不占工位); 失败则液位检测不可用, 退化人工门"}
        # unilab:node_uuid=c551d131-b365-54a8-b69b-28935007762a
        with group(name='说明 · 起点先自动采集干板参考 (host 动作, 不占工位); 失败则液位检测不可用, 退化人工门'):
            # [VERIFY comment] 只读来源校验 pf_s6_develop_wait@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=864ade6c-2708-5d10-b994-17be993c0371 disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s6_develop_wait',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='e73e95bf5cefb0c003d19c3b6b69be54ec6a0be0114039224a341589e7066728',
            )
        # [ACTION develop.capture_reference] 来源 pf_s6_develop_wait@body/1；原节点 {"action":"develop.capture_reference","args":{"target_tank":{"var":"tank"}},"assign":{"var":"ref_result"},"mode":"RUN","op":"call"}
        # unilab:node_uuid=65abc057-98b5-5615-982a-b592240d9aef disabled=true
        projected_action_0002 = develop.capture_reference(
            target_tank=1,
        )
        # [CONTROL if] 来源 pf_s6_develop_wait@body/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"ref_result"},"name":"ok"},"right":{"lit":false}},"else":[{"cond":{"var":"auto_drain"},"else":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"展开完成? 确认开始 PLC L2 排液"}},{"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target...
        # unilab:node_uuid=d7d187c3-eaa0-5e4e-a843-fd60ffa41e02
        with group(name='◇ IF 条件（PlatformUI 判定）'):
            # [VERIFY if] 只读来源校验 pf_s6_develop_wait@body/2；节点在本工作流中静态 disabled。
            # unilab:node_uuid=7516b7fe-d6e6-5f8a-bbb3-992f1ef0ff8d disabled=true
            projected_control_0003 = material.review_control_node_v1(
                operation_name='pf_s6_develop_wait',
                node_path='body/2',
                control_kind='if',
                expected_sha256='3c58977e81a815c4fc9c63006c377c7cc96a1245b63d12d9b0db6b3e335a8234',
            )
            # [BRANCH THEN（互斥分支）] pf_s6_develop_wait@body/2/then 的静态审阅分支。
            # unilab:node_uuid=0141c427-de13-506c-b2e3-224a7837e990
            with group(name='THEN（互斥分支）'):
                # [CONTROL human] 来源 pf_s6_develop_wait@body/2/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"参考图采集失败, 本次液位检测不可用; 展开完成后确认开始 PLC L2 排液"}}
                # unilab:node_uuid=c0d7c6c2-86d3-5ee9-bfcb-51d5eadc628d
                with group(name='◆ HITL 人工门'):
                    # [VERIFY human] 只读来源校验 pf_s6_develop_wait@body/2/then/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=250c855c-076a-5e36-a697-25c6b4e30089 disabled=true
                    projected_control_0004 = material.review_control_node_v1(
                        operation_name='pf_s6_develop_wait',
                        node_path='body/2/then/0',
                        control_kind='human',
                        expected_sha256='03670111a9f164d38eba18cfea71cc3a379d2f14e8467e1b41041431876887b2',
                    )
                # [CONTROL with_resources] 来源 pf_s6_develop_wait@body/2/then/1；原节点 {"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["station:develop"]}
                # unilab:node_uuid=d7090f2a-14b7-5908-8ea2-a7d8a4bba24c
                with group(name='🔒 局部 ResourceGate · station:develop'):
                    # [VERIFY with_resources] 只读来源校验 pf_s6_develop_wait@body/2/then/1；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=d57a2866-ffc6-576d-9575-e54c86b923d5 disabled=true
                    projected_control_0005 = material.review_control_node_v1(
                        operation_name='pf_s6_develop_wait',
                        node_path='body/2/then/1',
                        control_kind='with_resources',
                        expected_sha256='95a5975aaeec4c216c326c80ddb6f1765a7b0bd43a20c37c9b38d87bfd9d14c3',
                    )
                    # [BRANCH BODY（结构展开一次）] pf_s6_develop_wait@body/2/then/1/body 的静态审阅分支。
                    # unilab:node_uuid=24df2f92-2b4d-5185-b39f-63f009f4411a
                    with group(name='BODY（结构展开一次）'):
                        # [ACTION develop.drain] 来源 pf_s6_develop_wait@body/2/then/1/body/0；原节点 {"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=6ed79f21-2f87-53c1-9710-4cae7caf78a7 disabled=true
                        projected_action_0006 = develop.drain(
                            target_tank=1,
                        )
            # [BRANCH ELSE（互斥分支）] pf_s6_develop_wait@body/2/else 的静态审阅分支。
            # unilab:node_uuid=59774a3e-40b8-5cb7-98b9-aea38528809c
            with group(name='ELSE（互斥分支）'):
                # [CONTROL if] 来源 pf_s6_develop_wait@body/2/else/0；原节点 {"cond":{"var":"auto_drain"},"else":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"展开完成? 确认开始 PLC L2 排液"}},{"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["station:de...
                # unilab:node_uuid=3ad40269-c8dd-592b-861d-cff06541d273
                with group(name='◇ IF 条件（PlatformUI 判定）'):
                    # [VERIFY if] 只读来源校验 pf_s6_develop_wait@body/2/else/0；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=399ae5ad-8d5d-5700-906a-8c3843487bc4 disabled=true
                    projected_control_0007 = material.review_control_node_v1(
                        operation_name='pf_s6_develop_wait',
                        node_path='body/2/else/0',
                        control_kind='if',
                        expected_sha256='4f8a4d62321490fe32986952cba538ad441aeb4c43ab1f01cfe122655479441c',
                    )
                    # [BRANCH THEN（互斥分支）] pf_s6_develop_wait@body/2/else/0/then 的静态审阅分支。
                    # unilab:node_uuid=065bc4ff-428b-51e6-83a4-952fd56935d3
                    with group(name='THEN（互斥分支）'):
                        # [CONTROL comment] 来源 pf_s6_develop_wait@body/2/else/0/then/0；原节点 {"op":"comment","text":"T1 等待 (host 轮询液位, 空手): 命中预告才续 T2; degraded/hard_cap 直落排液"}
                        # unilab:node_uuid=76669620-623c-50b7-aaed-c84ffd87da0d
                        with group(name='说明 · T1 等待 (host 轮询液位, 空手): 命中预告才续 T2; degraded/hard_cap 直落排液'):
                            # [VERIFY comment] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=0925a231-83dd-509c-8d27-50c6bca8de35 disabled=true
                            projected_control_0008 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/then/0',
                                control_kind='comment',
                                expected_sha256='dbcffa3955424f021fe73ba1fa00b3fe4ca6e9082893a3bf95004b2f8ccd4970',
                            )
                        # [ACTION develop.wait_level] 来源 pf_s6_develop_wait@body/2/else/0/then/1；原节点 {"action":"develop.wait_level","args":{"stage":{"lit":"t1"},"target_tank":{"var":"tank"}},"assign":{"var":"wl_result"},"mode":"RUN","op":"call"}
                        # unilab:node_uuid=20abcb7b-b438-5855-94e5-bc7760dbe35a disabled=true
                        projected_action_0009 = develop.wait_level(
                            target_tank=1,
                            stage='t1',
                        )
                        # [CONTROL if] 来源 pf_s6_develop_wait@body/2/else/0/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"wl_result"},"name":"status"},"right":{"lit":"reached"}},"op":"if","then":[{"op":"comment","text":"T2 等待: 硬上限 = 总预算 3600s 扣除 T1 已耗 (max 兜零)"},{"action":"develop.wait_level","args":{"hard_cap_s":{"args":[{"lit":0.0},{"binop":"-","left":{"lit":3600.0},"right":{"field...
                        # unilab:node_uuid=63e90c5a-d47a-57f0-81e6-ae52685d1746
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/2；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6122352f-1415-5b6d-bd49-3540769a6a9d disabled=true
                            projected_control_0010 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/then/2',
                                control_kind='if',
                                expected_sha256='83f074ac0a7bc4a632f8d50b3ec04efe58e9524b07fc27f1cd117f26e12b892f',
                            )
                            # [BRANCH THEN（互斥分支）] pf_s6_develop_wait@body/2/else/0/then/2/then 的静态审阅分支。
                            # unilab:node_uuid=17c05480-015a-5945-9455-eac1b63fd224
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL comment] 来源 pf_s6_develop_wait@body/2/else/0/then/2/then/0；原节点 {"op":"comment","text":"T2 等待: 硬上限 = 总预算 3600s 扣除 T1 已耗 (max 兜零)"}
                                # unilab:node_uuid=3c0b6d6e-c393-5368-aa91-a3ab4d646588
                                with group(name='说明 · T2 等待: 硬上限 = 总预算 3600s 扣除 T1 已耗 (max 兜零)'):
                                    # [VERIFY comment] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/2/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=b146670a-06cb-5425-a2d1-aaf2749f0544 disabled=true
                                    projected_control_0011 = material.review_control_node_v1(
                                        operation_name='pf_s6_develop_wait',
                                        node_path='body/2/else/0/then/2/then/0',
                                        control_kind='comment',
                                        expected_sha256='662f8d88ea28e0c3bfda4a955345b84074532f638bd19ff478781aaf229b6f9c',
                                    )
                                # [ACTION develop.wait_level] 来源 pf_s6_develop_wait@body/2/else/0/then/2/then/1；原节点 {"action":"develop.wait_level","args":{"hard_cap_s":{"args":[{"lit":0.0},{"binop":"-","left":{"lit":3600.0},"right":{"field":{"var":"wl_result"},"name":"elapsed_s"}}],"call":"max"},"stage":{"lit":"t2"},"target_tank":{"var":"tank"}},"assign":{"var":"wl_result"},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=9630a493-9e15-5d7d-aee1-26975d1c72ca disabled=true
                                projected_action_0012 = develop.wait_level(
                                    target_tank=1,
                                    stage='t2',
                                )
                            # [BRANCH ELSE（互斥分支）] pf_s6_develop_wait@body/2/else/0/then/2/else 的静态审阅分支。
                            # unilab:node_uuid=7c1a3fc8-5a5d-5ef7-bae7-06d6206249de
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/2；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=a4560d3e-cadb-5299-9410-bb559556da83 disabled=true
                                projected_control_0013 = material.review_control_node_v1(
                                    operation_name='pf_s6_develop_wait',
                                    node_path='body/2/else/0/then/2',
                                    control_kind='if',
                                    expected_sha256='83f074ac0a7bc4a632f8d50b3ec04efe58e9524b07fc27f1cd117f26e12b892f',
                                )
                        # [CONTROL if] 来源 pf_s6_develop_wait@body/2/else/0/then/3；原节点 {"cond":{"binop":"==","left":{"field":{"var":"wl_result"},"name":"status"},"right":{"lit":"degraded"}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"液位检测异常 (数据陈旧/掉流/前沿无效), 人工确认后开始 PLC L2 排液?"}}]}
                        # unilab:node_uuid=93be7fa1-cdbb-5e5b-af54-51cb82cfd98e
                        with group(name='◇ IF 条件（PlatformUI 判定）'):
                            # [VERIFY if] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/3；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=9f36dfb2-8c5c-5dbb-9d03-6c8c45473acb disabled=true
                            projected_control_0014 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/then/3',
                                control_kind='if',
                                expected_sha256='a75e006cb43cc711aa129c2471484b9840987b21abcf244fef59a72edc81f0b0',
                            )
                            # [BRANCH THEN（互斥分支）] pf_s6_develop_wait@body/2/else/0/then/3/then 的静态审阅分支。
                            # unilab:node_uuid=e38ea5b7-cbe5-5850-8ac6-3d0573a969f0
                            with group(name='THEN（互斥分支）'):
                                # [CONTROL human] 来源 pf_s6_develop_wait@body/2/else/0/then/3/then/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"液位检测异常 (数据陈旧/掉流/前沿无效), 人工确认后开始 PLC L2 排液?"}}
                                # unilab:node_uuid=78f6d339-2c33-51ea-b00f-4805186a5c4c
                                with group(name='◆ HITL 人工门'):
                                    # [VERIFY human] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/3/then/0；节点在本工作流中静态 disabled。
                                    # unilab:node_uuid=890f6b1a-2fd2-57d1-956c-3da3d0c20ee2 disabled=true
                                    projected_control_0015 = material.review_control_node_v1(
                                        operation_name='pf_s6_develop_wait',
                                        node_path='body/2/else/0/then/3/then/0',
                                        control_kind='human',
                                        expected_sha256='c925698e17ad4c5435449161a1db70c3a221531b90402c1f4c105096040372f5',
                                    )
                            # [BRANCH ELSE（互斥分支）] pf_s6_develop_wait@body/2/else/0/then/3/else 的静态审阅分支。
                            # unilab:node_uuid=a8bb2ff8-f69e-5de7-bba2-2fece2d3b845
                            with group(name='ELSE（互斥分支）'):
                                # [EMPTY ELSE（互斥分支）] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/3；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=9f495e3f-edd4-5c2f-bd59-af45a289349d disabled=true
                                projected_control_0016 = material.review_control_node_v1(
                                    operation_name='pf_s6_develop_wait',
                                    node_path='body/2/else/0/then/3',
                                    control_kind='if',
                                    expected_sha256='a75e006cb43cc711aa129c2471484b9840987b21abcf244fef59a72edc81f0b0',
                                )
                        # [CONTROL comment] 来源 pf_s6_develop_wait@body/2/else/0/then/4；原节点 {"op":"comment","text":"reached/hard_cap/人已确认 -> 排液 (短取工位, 用毕即还; 化学上排液须即时, 最坏等一个装卸窗)"}
                        # unilab:node_uuid=88bdc755-ccc8-5591-b8ed-782c621fc493
                        with group(name='说明 · reached/hard_cap/人已确认 -> 排液 (短取工位, 用毕即还; 化学上排液须即时, 最坏等一个'):
                            # [VERIFY comment] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/4；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=ead75b1b-bbf5-5714-8d76-ba9a7a45b07c disabled=true
                            projected_control_0017 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/then/4',
                                control_kind='comment',
                                expected_sha256='80cbe62147d807d52aa7c5845ca670910d6b0506c81f67c7b92eff3c767a53ac',
                            )
                        # [CONTROL with_resources] 来源 pf_s6_develop_wait@body/2/else/0/then/5；原节点 {"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["station:develop"]}
                        # unilab:node_uuid=ebd28276-60eb-5627-8c23-5b508e64426d
                        with group(name='🔒 局部 ResourceGate · station:develop'):
                            # [VERIFY with_resources] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/5；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=5127a1ef-08a4-5f93-9d0b-6e4d7e55d69d disabled=true
                            projected_control_0018 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/then/5',
                                control_kind='with_resources',
                                expected_sha256='95a5975aaeec4c216c326c80ddb6f1765a7b0bd43a20c37c9b38d87bfd9d14c3',
                            )
                            # [BRANCH BODY（结构展开一次）] pf_s6_develop_wait@body/2/else/0/then/5/body 的静态审阅分支。
                            # unilab:node_uuid=ba2827eb-35b1-5dfb-9528-cc73f8a7eb67
                            with group(name='BODY（结构展开一次）'):
                                # [ACTION develop.drain] 来源 pf_s6_develop_wait@body/2/else/0/then/5/body/0；原节点 {"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=51b2590b-e7e5-5d54-bda4-bb103cf050ed disabled=true
                                projected_action_0019 = develop.drain(
                                    target_tank=1,
                                )
                    # [BRANCH ELSE（互斥分支）] pf_s6_develop_wait@body/2/else/0/else 的静态审阅分支。
                    # unilab:node_uuid=0cdaecf8-fcb1-5e9c-85a6-8a8257658cce
                    with group(name='ELSE（互斥分支）'):
                        # [CONTROL human] 来源 pf_s6_develop_wait@body/2/else/0/else/0；原节点 {"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"展开完成? 确认开始 PLC L2 排液"}}
                        # unilab:node_uuid=ff465e6f-8b39-5e95-91b9-3d7eab2fbf86
                        with group(name='◆ HITL 人工门'):
                            # [VERIFY human] 只读来源校验 pf_s6_develop_wait@body/2/else/0/else/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=c82def98-1ca0-5b04-b629-ea63b0626ed7 disabled=true
                            projected_control_0020 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/else/0',
                                control_kind='human',
                                expected_sha256='494432f8d3728205ee96478209d2b24eba08123321cde92645badabf57c3003e',
                            )
                        # [CONTROL with_resources] 来源 pf_s6_develop_wait@body/2/else/0/else/1；原节点 {"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["station:develop"]}
                        # unilab:node_uuid=3edcce56-bf2f-5c84-9ce1-dee44b5d692e
                        with group(name='🔒 局部 ResourceGate · station:develop'):
                            # [VERIFY with_resources] 只读来源校验 pf_s6_develop_wait@body/2/else/0/else/1；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=6d849b9b-9f37-56a1-9842-dc96c54bcb41 disabled=true
                            projected_control_0021 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/else/1',
                                control_kind='with_resources',
                                expected_sha256='95a5975aaeec4c216c326c80ddb6f1765a7b0bd43a20c37c9b38d87bfd9d14c3',
                            )
                            # [BRANCH BODY（结构展开一次）] pf_s6_develop_wait@body/2/else/0/else/1/body 的静态审阅分支。
                            # unilab:node_uuid=66528caa-8c9c-549b-9524-d4bee1bea54f
                            with group(name='BODY（结构展开一次）'):
                                # [ACTION develop.drain] 来源 pf_s6_develop_wait@body/2/else/0/else/1/body/0；原节点 {"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
                                # unilab:node_uuid=854bce1a-a574-583f-8019-b753dc2e5645 disabled=true
                                projected_action_0022 = develop.drain(
                                    target_tank=1,
                                )
    # [EXECUTE ROOT pf_s6_develop_wait] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=b543a9a0-6705-5050-99be-4e207130a52d
    execution = material.run_operation_review_v1(
        operation_name='pf_s6_develop_wait',
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
