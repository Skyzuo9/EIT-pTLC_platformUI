from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_develop import PLCDevelop
from eit_ptlc.unilab_domain.devices.material import MaterialProxy


develop: PLCDevelop = device('plc_develop')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='b7f54d16-3d97-5356-857a-48e8cde7d729',
    displayname='5-1 展开等待 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s6_develop_wait_operation_view_v2() -> None:
    # [OPERATION pf_s6_develop_wait] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=7822a23c-a9e4-57ba-9c77-619583931e67 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s6_develop_wait',
        inputs_json='{"auto_drain":true,"dry_duration_s":0.0,"tank":1}',
        expected_sha256='ecb3d9ce806ed4f5912c25db809f48cee211b8de6eb2844d295992a83c85cbbd',
    )
    # [VERIFY comment] 只读来源校验 pf_s6_develop_wait@body/0；本视图中静态 disabled。
    # unilab:node_uuid=1544823e-8a01-53f5-883d-976484cf48d4 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s6_develop_wait',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='e73e95bf5cefb0c003d19c3b6b69be54ec6a0be0114039224a341589e7066728',
    )
    # [ACTION develop.capture_reference] 来源 pf_s6_develop_wait@body/1；原节点 {"action":"develop.capture_reference","args":{"target_tank":{"var":"tank"}},"assign":{"var":"ref_result"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=377848e2-2e13-5ed5-9b77-5be759ba7cd3 disabled=true
    projected_action_0003 = develop.capture_reference(
        target_tank=1,
    )
    # [CONTROL if] 来源 pf_s6_develop_wait@body/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"ref_result"},"name":"ok"},"right":{"lit":false}},"else":[{"cond":{"var":"auto_drain"},"else":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"展开完成? 确认开始 PLC L2 排液"}},{"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target...
    # unilab:node_uuid=a3c42f1c-11dd-56e4-9339-56f2288805a5
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 pf_s6_develop_wait@body/2；本视图中静态 disabled。
        # unilab:node_uuid=f4cc0d89-4d5f-5020-90db-e11177335c0e disabled=true
        projected_control_0004 = material.review_control_node_v1(
            operation_name='pf_s6_develop_wait',
            node_path='body/2',
            control_kind='if',
            expected_sha256='3c58977e81a815c4fc9c63006c377c7cc96a1245b63d12d9b0db6b3e335a8234',
        )
        # unilab:node_uuid=e753b6bf-783d-5bcb-93d2-c359c21b6cf8
        with group(name='THEN（互斥分支）'):
            # [VERIFY human] 只读来源校验 pf_s6_develop_wait@body/2/then/0；本视图中静态 disabled。
            # unilab:node_uuid=a17ae114-da84-5412-a234-fbd25e2078fe disabled=true
            projected_control_0005 = material.review_control_node_v1(
                operation_name='pf_s6_develop_wait',
                node_path='body/2/then/0',
                control_kind='human',
                expected_sha256='03670111a9f164d38eba18cfea71cc3a379d2f14e8467e1b41041431876887b2',
            )
            # [CONTROL with_resources] 来源 pf_s6_develop_wait@body/2/then/1；原节点 {"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["station:develop"]}
            # unilab:node_uuid=2164b227-420a-5711-b127-a44e5bf96ede
            with group(name='🔒 局部 ResourceGate · station:develop'):
                # [VERIFY with_resources] 只读来源校验 pf_s6_develop_wait@body/2/then/1；本视图中静态 disabled。
                # unilab:node_uuid=12a8fae3-8a28-5d9c-8c4f-3c26781c059c disabled=true
                projected_control_0006 = material.review_control_node_v1(
                    operation_name='pf_s6_develop_wait',
                    node_path='body/2/then/1',
                    control_kind='with_resources',
                    expected_sha256='95a5975aaeec4c216c326c80ddb6f1765a7b0bd43a20c37c9b38d87bfd9d14c3',
                )
                # unilab:node_uuid=b12d50b0-2742-5f3d-8960-ae3c0a371746
                with group(name='BODY（结构展开一次）'):
                    # [ACTION develop.drain] 来源 pf_s6_develop_wait@body/2/then/1/body/0；原节点 {"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=c8f3c5a3-8563-5945-9ca9-dc8cfa13b5e8 disabled=true
                    projected_action_0007 = develop.drain(
                        target_tank=1,
                    )
        # unilab:node_uuid=3cc01fe3-d225-578e-86cc-4e57560dfbe1
        with group(name='ELSE（互斥分支）'):
            # [CONTROL if] 来源 pf_s6_develop_wait@body/2/else/0；原节点 {"cond":{"var":"auto_drain"},"else":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"展开完成? 确认开始 PLC L2 排液"}},{"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["station:de...
            # unilab:node_uuid=c928d330-070d-5cb3-acf5-f0a286466655
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 pf_s6_develop_wait@body/2/else/0；本视图中静态 disabled。
                # unilab:node_uuid=603f431c-0a2c-568e-bc8b-1eb7ca5e5f19 disabled=true
                projected_control_0008 = material.review_control_node_v1(
                    operation_name='pf_s6_develop_wait',
                    node_path='body/2/else/0',
                    control_kind='if',
                    expected_sha256='4f8a4d62321490fe32986952cba538ad441aeb4c43ab1f01cfe122655479441c',
                )
                # unilab:node_uuid=c1afebb3-072b-5aae-88a9-71be937fcb3c
                with group(name='THEN（互斥分支）'):
                    # [VERIFY comment] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/0；本视图中静态 disabled。
                    # unilab:node_uuid=2d1fabd3-9dc6-5140-80be-0b97fd71e418 disabled=true
                    projected_control_0009 = material.review_control_node_v1(
                        operation_name='pf_s6_develop_wait',
                        node_path='body/2/else/0/then/0',
                        control_kind='comment',
                        expected_sha256='dbcffa3955424f021fe73ba1fa00b3fe4ca6e9082893a3bf95004b2f8ccd4970',
                    )
                    # [ACTION develop.wait_level] 来源 pf_s6_develop_wait@body/2/else/0/then/1；原节点 {"action":"develop.wait_level","args":{"stage":{"lit":"t1"},"target_tank":{"var":"tank"}},"assign":{"var":"wl_result"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=31c5d9ec-d2cd-5ea2-8aa1-c73d82a2c622 disabled=true
                    projected_action_0010 = develop.wait_level(
                        target_tank=1,
                        stage='t1',
                    )
                    # [CONTROL if] 来源 pf_s6_develop_wait@body/2/else/0/then/2；原节点 {"cond":{"binop":"==","left":{"field":{"var":"wl_result"},"name":"status"},"right":{"lit":"reached"}},"op":"if","then":[{"op":"comment","text":"T2 等待: 硬上限 = 总预算 3600s 扣除 T1 已耗 (max 兜零)"},{"action":"develop.wait_level","args":{"hard_cap_s":{"args":[{"lit":0.0},{"binop":"-","left":{"lit":3600.0},"right":{"field...
                    # unilab:node_uuid=5e5c95f9-f30b-5179-888f-5fb9536ca62e
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/2；本视图中静态 disabled。
                        # unilab:node_uuid=d5faa06d-bf2c-528e-8d11-a117f6331f13 disabled=true
                        projected_control_0011 = material.review_control_node_v1(
                            operation_name='pf_s6_develop_wait',
                            node_path='body/2/else/0/then/2',
                            control_kind='if',
                            expected_sha256='83f074ac0a7bc4a632f8d50b3ec04efe58e9524b07fc27f1cd117f26e12b892f',
                        )
                        # unilab:node_uuid=9e3a6e5f-7338-5551-a059-191a96a39c2f
                        with group(name='THEN（互斥分支）'):
                            # [VERIFY comment] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/2/then/0；本视图中静态 disabled。
                            # unilab:node_uuid=efb91617-c6d2-5c06-8e01-ff9c688d84bf disabled=true
                            projected_control_0012 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/then/2/then/0',
                                control_kind='comment',
                                expected_sha256='662f8d88ea28e0c3bfda4a955345b84074532f638bd19ff478781aaf229b6f9c',
                            )
                            # [ACTION develop.wait_level] 来源 pf_s6_develop_wait@body/2/else/0/then/2/then/1；原节点 {"action":"develop.wait_level","args":{"hard_cap_s":{"args":[{"lit":0.0},{"binop":"-","left":{"lit":3600.0},"right":{"field":{"var":"wl_result"},"name":"elapsed_s"}}],"call":"max"},"stage":{"lit":"t2"},"target_tank":{"var":"tank"}},"assign":{"var":"wl_result"},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=ce41faa0-03a2-59f3-999d-8aeb0b2db297 disabled=true
                            projected_action_0013 = develop.wait_level(
                                target_tank=1,
                                stage='t2',
                            )
                        # unilab:node_uuid=78785b19-d7a5-5e07-b093-c3c03ece0f0c
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/2；本视图中静态 disabled。
                            # unilab:node_uuid=7eca367b-12cb-50cd-9a35-57985540c1de disabled=true
                            projected_control_0014 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/then/2',
                                control_kind='if',
                                expected_sha256='83f074ac0a7bc4a632f8d50b3ec04efe58e9524b07fc27f1cd117f26e12b892f',
                            )
                    # [CONTROL if] 来源 pf_s6_develop_wait@body/2/else/0/then/3；原节点 {"cond":{"binop":"==","left":{"field":{"var":"wl_result"},"name":"status"},"right":{"lit":"degraded"}},"op":"if","then":[{"kind":"confirm","on_cancel":"raise","op":"human","prompt":{"lit":"液位检测异常 (数据陈旧/掉流/前沿无效), 人工确认后开始 PLC L2 排液?"}}]}
                    # unilab:node_uuid=3a77ac80-d0e2-567b-81c3-401ecff473e2
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/3；本视图中静态 disabled。
                        # unilab:node_uuid=e4c2a612-e264-58a3-a792-35af7aa7fd49 disabled=true
                        projected_control_0015 = material.review_control_node_v1(
                            operation_name='pf_s6_develop_wait',
                            node_path='body/2/else/0/then/3',
                            control_kind='if',
                            expected_sha256='a75e006cb43cc711aa129c2471484b9840987b21abcf244fef59a72edc81f0b0',
                        )
                        # unilab:node_uuid=0b876f27-dbed-5802-9835-ceda886a832e
                        with group(name='THEN（互斥分支）'):
                            # [VERIFY human] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/3/then/0；本视图中静态 disabled。
                            # unilab:node_uuid=6a619760-72fc-5d49-80a1-7705dd19fdfb disabled=true
                            projected_control_0016 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/then/3/then/0',
                                control_kind='human',
                                expected_sha256='c925698e17ad4c5435449161a1db70c3a221531b90402c1f4c105096040372f5',
                            )
                        # unilab:node_uuid=ce1ad005-a85f-589c-965f-d1e8712d9459
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/3；本视图中静态 disabled。
                            # unilab:node_uuid=c0c98500-2763-579b-ad55-d437e377177a disabled=true
                            projected_control_0017 = material.review_control_node_v1(
                                operation_name='pf_s6_develop_wait',
                                node_path='body/2/else/0/then/3',
                                control_kind='if',
                                expected_sha256='a75e006cb43cc711aa129c2471484b9840987b21abcf244fef59a72edc81f0b0',
                            )
                    # [VERIFY comment] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/4；本视图中静态 disabled。
                    # unilab:node_uuid=015eac6c-4947-5205-a478-87a47006b849 disabled=true
                    projected_control_0018 = material.review_control_node_v1(
                        operation_name='pf_s6_develop_wait',
                        node_path='body/2/else/0/then/4',
                        control_kind='comment',
                        expected_sha256='80cbe62147d807d52aa7c5845ca670910d6b0506c81f67c7b92eff3c767a53ac',
                    )
                    # [CONTROL with_resources] 来源 pf_s6_develop_wait@body/2/else/0/then/5；原节点 {"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["station:develop"]}
                    # unilab:node_uuid=5a27cc16-f470-51e9-8da0-360f1f5f5e6b
                    with group(name='🔒 局部 ResourceGate · station:develop'):
                        # [VERIFY with_resources] 只读来源校验 pf_s6_develop_wait@body/2/else/0/then/5；本视图中静态 disabled。
                        # unilab:node_uuid=01e1e1fe-0d94-5b94-8ed8-fd7c3c5668ad disabled=true
                        projected_control_0019 = material.review_control_node_v1(
                            operation_name='pf_s6_develop_wait',
                            node_path='body/2/else/0/then/5',
                            control_kind='with_resources',
                            expected_sha256='95a5975aaeec4c216c326c80ddb6f1765a7b0bd43a20c37c9b38d87bfd9d14c3',
                        )
                        # unilab:node_uuid=5752402c-9dd3-512e-ba8f-f8bf89910907
                        with group(name='BODY（结构展开一次）'):
                            # [ACTION develop.drain] 来源 pf_s6_develop_wait@body/2/else/0/then/5/body/0；原节点 {"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=ff69a521-34f2-59bb-ab8a-93ad8d769a58 disabled=true
                            projected_action_0020 = develop.drain(
                                target_tank=1,
                            )
                # unilab:node_uuid=940e5e96-8c8f-5142-bba5-187de4e03be4
                with group(name='ELSE（互斥分支）'):
                    # [VERIFY human] 只读来源校验 pf_s6_develop_wait@body/2/else/0/else/0；本视图中静态 disabled。
                    # unilab:node_uuid=68e4e988-8578-5536-bb1a-d369fcdb4286 disabled=true
                    projected_control_0021 = material.review_control_node_v1(
                        operation_name='pf_s6_develop_wait',
                        node_path='body/2/else/0/else/0',
                        control_kind='human',
                        expected_sha256='494432f8d3728205ee96478209d2b24eba08123321cde92645badabf57c3003e',
                    )
                    # [CONTROL with_resources] 来源 pf_s6_develop_wait@body/2/else/0/else/1；原节点 {"body":[{"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["station:develop"]}
                    # unilab:node_uuid=9539531b-c3cf-5237-87cc-535494ae2f28
                    with group(name='🔒 局部 ResourceGate · station:develop'):
                        # [VERIFY with_resources] 只读来源校验 pf_s6_develop_wait@body/2/else/0/else/1；本视图中静态 disabled。
                        # unilab:node_uuid=6859f676-71ff-5111-b084-be5f7432c1f3 disabled=true
                        projected_control_0022 = material.review_control_node_v1(
                            operation_name='pf_s6_develop_wait',
                            node_path='body/2/else/0/else/1',
                            control_kind='with_resources',
                            expected_sha256='95a5975aaeec4c216c326c80ddb6f1765a7b0bd43a20c37c9b38d87bfd9d14c3',
                        )
                        # unilab:node_uuid=dc33c8b6-282b-5d46-b423-38d58ccbed65
                        with group(name='BODY（结构展开一次）'):
                            # [ACTION develop.drain] 来源 pf_s6_develop_wait@body/2/else/0/else/1/body/0；原节点 {"action":"develop.drain","args":{"dry_duration_s":{"var":"dry_duration_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=70bf8821-5292-5073-b6f0-2da9e35db831 disabled=true
                            projected_action_0023 = develop.drain(
                                target_tank=1,
                            )
