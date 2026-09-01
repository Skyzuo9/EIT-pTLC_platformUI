from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)
from eit_ptlc.workflows.transfer_collector_staging_a_to_rack_operation_view_v2 import (
    transfer_collector_staging_a_to_rack_operation_view_v2,
)
from eit_ptlc.workflows.transfer_collector_rack_to_staging_a_operation_view_v2 import (
    transfer_collector_rack_to_staging_a_operation_view_v2,
)


material: MaterialProxy = device('material')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='d1de52fc-4c92-50bb-a8b7-60726fbc8a85',
    displayname='耗材-粉末收集器就位保证 (读账本决策 -> 够用则跳过 / 否则条件换板) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def ensure_collector_staged_operation_view_v2() -> None:
    # [OPERATION ensure_collector_staged] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=1a9688fa-61fa-5f9e-bec5-9d50f07ffa7f disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='ensure_collector_staged',
        inputs_json='{"reserve_for":""}',
        expected_sha256='298296a0e219d8a88766dc5b930262c307c3625cd6a67e8b1d7333f4156752c5',
    )
    # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/0；本视图中静态 disabled。
    # unilab:node_uuid=060ebdf4-a2f0-5a7c-b231-c6cd4b7f7151 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='ensure_collector_staged',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='9f4fd728acf47dc72b9c5e3d2d3f0853aeee948ce1ef8dd555e4ba5c94277932',
    )
    # [ACTION material.plan_staging] 来源 ensure_collector_staged@body/1；原节点 {"action":"material.plan_staging","args":{"kind":{"lit":"collector"},"reserve_for":{"var":"reserve_for"}},"assign":{"var":"plan"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=538e7402-6180-5f28-876d-72a7549bca0e disabled=true
    projected_action_0003 = material.plan_staging(
        kind='collector',
    )
    # [VERIFY assign] 只读来源校验 ensure_collector_staged@body/2；本视图中静态 disabled。
    # unilab:node_uuid=50e0647c-9b66-5a22-a10c-3d813e035867 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='ensure_collector_staged',
        node_path='body/2',
        control_kind='assign',
        expected_sha256='752a8e7ac062b5aa2e33a6a2b515271a78f200116fa26e4d00d4329175c46e62',
    )
    # [VERIFY assign] 只读来源校验 ensure_collector_staged@body/3；本视图中静态 disabled。
    # unilab:node_uuid=b60b8e75-4d87-5b97-84fc-4157484e380f disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='ensure_collector_staged',
        node_path='body/3',
        control_kind='assign',
        expected_sha256='0fa3379fc03f812629d15c29be64125a73fcf8fe233e44134a51cc3b8c57dd12',
    )
    # [VERIFY assign] 只读来源校验 ensure_collector_staged@body/4；本视图中静态 disabled。
    # unilab:node_uuid=f4607a43-9e83-5f3b-a3ed-777919b73234 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='ensure_collector_staged',
        node_path='body/4',
        control_kind='assign',
        expected_sha256='cbc19c59699b67029e4de5b8a1c8224b6d104b1467266ea88c3a714ab58d30e1',
    )
    # [VERIFY assign] 只读来源校验 ensure_collector_staged@body/5；本视图中静态 disabled。
    # unilab:node_uuid=beb58e52-d145-52b0-be58-074ec6adf484 disabled=true
    projected_control_0007 = material.review_control_node_v1(
        operation_name='ensure_collector_staged',
        node_path='body/5',
        control_kind='assign',
        expected_sha256='80038b1850b9abbfa9ddc48239e7e240f9dc013796291b091335ff8bb6625419',
    )
    # [CONTROL if] 来源 ensure_collector_staged@body/6；原节点 {"cond":{"binop":"!=","left":{"var":"op"},"right":{"lit":"NONE"}},"op":"if","then":[{"op":"comment","text":"要动整板才切工具2大夹爪 (NONE 复用时全程不换刀, 也不进货架区)"},{"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"},{"cond":{"binop":"==","left":{"var":"op"},"right":{"lit":"SWAP"}},"op":"if","the...
    # unilab:node_uuid=6eb29b86-4966-5fb7-bb00-fe0e30bcb2c3
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 ensure_collector_staged@body/6；本视图中静态 disabled。
        # unilab:node_uuid=a9f8b57c-5dd3-591f-aa85-3cb3cf5a6771 disabled=true
        projected_control_0008 = material.review_control_node_v1(
            operation_name='ensure_collector_staged',
            node_path='body/6',
            control_kind='if',
            expected_sha256='2f96e2815b391809df61d7fae0211fa194970aa2d2170f8033e708ba69837b69',
        )
        # unilab:node_uuid=95a41eeb-33e7-5035-b8d9-96a90a51ae83
        with group(name='THEN（互斥分支）'):
            # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/6/then/0；本视图中静态 disabled。
            # unilab:node_uuid=4a9786cf-b0f2-58fb-95dd-ab6e0edfcd70 disabled=true
            projected_control_0009 = material.review_control_node_v1(
                operation_name='ensure_collector_staged',
                node_path='body/6/then/0',
                control_kind='comment',
                expected_sha256='9eb63c0c84887a794ac9bb5a9b24241a3e243341286c731d6087fb89649fb8a6',
            )
            # [SUBWORKFLOW robot_tool_ensure] 来源 ensure_collector_staged@body/6/then/1；原节点 {"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
            # unilab:node_uuid=d24d5027-6ae8-564c-b305-8eeef9b21417
            nested_operation_0010 = robot_tool_ensure_operation_view_v2()
            # [CONTROL if] 来源 ensure_collector_staged@body/6/then/2；原节点 {"cond":{"binop":"==","left":{"var":"op"},"right":{"lit":"SWAP"}},"op":"if","then":[{"op":"comment","text":"SWAP: 先把耗尽的中转板送回它载入时的那个货架库位 (账本据此比对, 不一致会告警留痕)"},{"inputs":{"slot_id":{"var":"old_rack_slot"}},"op":"run_script","outputs":{},"script":"transfer_collector_staging_a_to_rack"}]}
            # unilab:node_uuid=ab9d7f94-edc9-5c64-9e53-7adc87e8c472
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 ensure_collector_staged@body/6/then/2；本视图中静态 disabled。
                # unilab:node_uuid=a8f73240-511d-5e3b-b985-c0d8ac4823ca disabled=true
                projected_control_0011 = material.review_control_node_v1(
                    operation_name='ensure_collector_staged',
                    node_path='body/6/then/2',
                    control_kind='if',
                    expected_sha256='3dc081f354285e007817d557717334f4f98825aa201abf5a11bece7e6845765d',
                )
                # unilab:node_uuid=c215277d-5e85-5eef-83b2-d9680ece631b
                with group(name='THEN（互斥分支）'):
                    # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/6/then/2/then/0；本视图中静态 disabled。
                    # unilab:node_uuid=2c4c5e98-1c63-5b09-b4a6-29619b23f107 disabled=true
                    projected_control_0012 = material.review_control_node_v1(
                        operation_name='ensure_collector_staged',
                        node_path='body/6/then/2/then/0',
                        control_kind='comment',
                        expected_sha256='c0c1292e472751a26c8277757f093045ebc33db595b5a85a1d33c6ea2c602b67',
                    )
                    # [SUBWORKFLOW transfer_collector_staging_a_to_rack] 来源 ensure_collector_staged@body/6/then/2/then/1；原节点 {"inputs":{"slot_id":{"var":"old_rack_slot"}},"op":"run_script","outputs":{},"script":"transfer_collector_staging_a_to_rack"}
                    # unilab:node_uuid=61d8470f-58f1-5849-a1e2-da1d592e59ec
                    nested_operation_0013 = transfer_collector_staging_a_to_rack_operation_view_v2()
                # unilab:node_uuid=545f0be1-3102-5945-a067-18644c2c3eb6
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 ensure_collector_staged@body/6/then/2；本视图中静态 disabled。
                    # unilab:node_uuid=9c470d0e-bd3a-5618-8b0d-a060d997736a disabled=true
                    projected_control_0014 = material.review_control_node_v1(
                        operation_name='ensure_collector_staged',
                        node_path='body/6/then/2',
                        control_kind='if',
                        expected_sha256='3dc081f354285e007817d557717334f4f98825aa201abf5a11bece7e6845765d',
                    )
            # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/6/then/3；本视图中静态 disabled。
            # unilab:node_uuid=3c745a26-000e-53a8-accb-a36f06670121 disabled=true
            projected_control_0015 = material.review_control_node_v1(
                operation_name='ensure_collector_staged',
                node_path='body/6/then/3',
                control_kind='comment',
                expected_sha256='c1887bba9d6e94a5dfbb91ca44b16ad6490e4b728e9795af9b12ffdf733dffd7',
            )
            # [SUBWORKFLOW transfer_collector_rack_to_staging_a] 来源 ensure_collector_staged@body/6/then/4；原节点 {"inputs":{"slot_id":{"var":"rack_slot"}},"op":"run_script","outputs":{},"script":"transfer_collector_rack_to_staging_a"}
            # unilab:node_uuid=d1e60611-0507-5a91-ba22-f6956ecba804
            nested_operation_0016 = transfer_collector_rack_to_staging_a_operation_view_v2()
        # unilab:node_uuid=8e68917a-e86a-5b23-8e70-a984e80ab358
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 ensure_collector_staged@body/6；本视图中静态 disabled。
            # unilab:node_uuid=b0c888b3-2a2c-586b-9072-3264d9e5097d disabled=true
            projected_control_0017 = material.review_control_node_v1(
                operation_name='ensure_collector_staged',
                node_path='body/6',
                control_kind='if',
                expected_sha256='2f96e2815b391809df61d7fae0211fa194970aa2d2170f8033e708ba69837b69',
            )
    # [VERIFY comment] 只读来源校验 ensure_collector_staged@body/7；本视图中静态 disabled。
    # unilab:node_uuid=fef9a5e3-ad97-58b1-a32e-eb07ef310207 disabled=true
    projected_control_0018 = material.review_control_node_v1(
        operation_name='ensure_collector_staged',
        node_path='body/7',
        control_kind='comment',
        expected_sha256='3515de9b64820739bb8855879b0c6224d6762003f1ed2724c7ccfc34dfe3f55d',
    )
    # [ACTION staging_a.locator_a] 来源 ensure_collector_staged@body/8；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=4fb94783-98be-5448-9ce5-d0c05242b142 disabled=true
    projected_action_0019 = staging_a.locator_a(
        target=True,
    )
