from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)
from eit_ptlc.workflows.transfer_bottle_staging_b_to_rack_operation_view_v2 import (
    transfer_bottle_staging_b_to_rack_operation_view_v2,
)
from eit_ptlc.workflows.transfer_bottle_rack_to_staging_b_operation_view_v2 import (
    transfer_bottle_rack_to_staging_b_operation_view_v2,
)


material: MaterialProxy = device('material')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='f191f1cb-f66b-5b6a-a326-1e4bf9b8da19',
    displayname='耗材-玻璃收集瓶就位保证 (读账本决策 -> 够用则跳过 / 否则条件换板) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def ensure_bottle_staged_operation_view_v2() -> None:
    # [OPERATION ensure_bottle_staged] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=a31e031f-0867-562c-a9eb-2b1834fefdaa disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='ensure_bottle_staged',
        inputs_json='{"reserve_for":""}',
        expected_sha256='f2c575634cef063aedd1c7aa6f93cf8c997b1008ee4f3876856ba675971a059a',
    )
    # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/0；本视图中静态 disabled。
    # unilab:node_uuid=6d263dfa-83d4-5596-9643-966c6e00d816 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='ensure_bottle_staged',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='45f3c29500a1bc3022db4f51abb140b9b0e1c850aca535346d63e986ce86c314',
    )
    # [ACTION material.plan_staging] 来源 ensure_bottle_staged@body/1；原节点 {"action":"material.plan_staging","args":{"kind":{"lit":"bottle"},"reserve_for":{"var":"reserve_for"}},"assign":{"var":"plan"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=d70bf1c2-f325-5995-a790-7565ea271887 disabled=true
    projected_action_0003 = material.plan_staging(
        kind='bottle',
    )
    # [VERIFY assign] 只读来源校验 ensure_bottle_staged@body/2；本视图中静态 disabled。
    # unilab:node_uuid=86a9254c-1982-52bf-8297-de328c600b08 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='ensure_bottle_staged',
        node_path='body/2',
        control_kind='assign',
        expected_sha256='752a8e7ac062b5aa2e33a6a2b515271a78f200116fa26e4d00d4329175c46e62',
    )
    # [VERIFY assign] 只读来源校验 ensure_bottle_staged@body/3；本视图中静态 disabled。
    # unilab:node_uuid=9b4e0452-751c-5ea4-81c5-d86a8510dd2a disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='ensure_bottle_staged',
        node_path='body/3',
        control_kind='assign',
        expected_sha256='0fa3379fc03f812629d15c29be64125a73fcf8fe233e44134a51cc3b8c57dd12',
    )
    # [VERIFY assign] 只读来源校验 ensure_bottle_staged@body/4；本视图中静态 disabled。
    # unilab:node_uuid=e69ba5c6-6ad7-5fb7-a1d4-f73d2e0260e3 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='ensure_bottle_staged',
        node_path='body/4',
        control_kind='assign',
        expected_sha256='cbc19c59699b67029e4de5b8a1c8224b6d104b1467266ea88c3a714ab58d30e1',
    )
    # [VERIFY assign] 只读来源校验 ensure_bottle_staged@body/5；本视图中静态 disabled。
    # unilab:node_uuid=971fff9f-e132-597f-9527-87b3c09df040 disabled=true
    projected_control_0007 = material.review_control_node_v1(
        operation_name='ensure_bottle_staged',
        node_path='body/5',
        control_kind='assign',
        expected_sha256='80038b1850b9abbfa9ddc48239e7e240f9dc013796291b091335ff8bb6625419',
    )
    # [CONTROL if] 来源 ensure_bottle_staged@body/6；原节点 {"cond":{"binop":"!=","left":{"var":"op"},"right":{"lit":"NONE"}},"op":"if","then":[{"op":"comment","text":"要动整板才切工具2大夹爪 (NONE 复用时全程不换刀, 也不进货架区)"},{"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"},{"cond":{"binop":"==","left":{"var":"op"},"right":{"lit":"SWAP"}},"op":"if","then":...
    # unilab:node_uuid=fe9b3563-6453-5465-becb-527554fb1c8b
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 ensure_bottle_staged@body/6；本视图中静态 disabled。
        # unilab:node_uuid=ec993e4b-790b-5f1f-a5f9-c99e4915fc25 disabled=true
        projected_control_0008 = material.review_control_node_v1(
            operation_name='ensure_bottle_staged',
            node_path='body/6',
            control_kind='if',
            expected_sha256='ee0fbe8373c6e2d28221d31637096f52d0860619ee14ed2085eab7884ffdeac1',
        )
        # unilab:node_uuid=4671b395-93dc-5d8b-a99f-4806021e135f
        with group(name='THEN（互斥分支）'):
            # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/6/then/0；本视图中静态 disabled。
            # unilab:node_uuid=7d971340-6d0c-5188-961c-9d6ba8483a7b disabled=true
            projected_control_0009 = material.review_control_node_v1(
                operation_name='ensure_bottle_staged',
                node_path='body/6/then/0',
                control_kind='comment',
                expected_sha256='9eb63c0c84887a794ac9bb5a9b24241a3e243341286c731d6087fb89649fb8a6',
            )
            # [SUBWORKFLOW robot_tool_ensure] 来源 ensure_bottle_staged@body/6/then/1；原节点 {"inputs":{"needed":{"lit":2}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
            # unilab:node_uuid=921c1b35-37a1-5f22-aa28-050844610454
            nested_operation_0010 = robot_tool_ensure_operation_view_v2()
            # [CONTROL if] 来源 ensure_bottle_staged@body/6/then/2；原节点 {"cond":{"binop":"==","left":{"var":"op"},"right":{"lit":"SWAP"}},"op":"if","then":[{"op":"comment","text":"SWAP: 先把装满成品瓶的中转板送回它载入时的那个货架库位 (成品随板归档)"},{"inputs":{"slot_id":{"var":"old_rack_slot"}},"op":"run_script","outputs":{},"script":"transfer_bottle_staging_b_to_rack"}]}
            # unilab:node_uuid=d360ecd2-5330-5099-8216-5bb41748a071
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 ensure_bottle_staged@body/6/then/2；本视图中静态 disabled。
                # unilab:node_uuid=83508d7d-4a8d-5d89-9188-b088d6474d9a disabled=true
                projected_control_0011 = material.review_control_node_v1(
                    operation_name='ensure_bottle_staged',
                    node_path='body/6/then/2',
                    control_kind='if',
                    expected_sha256='fe3ac98e9c09b236795fd80bf489ff20b8968bfa446ddf1d1825aca70ccf7872',
                )
                # unilab:node_uuid=aa7ae9d8-8fe3-5f66-9f7e-22c061fb5c67
                with group(name='THEN（互斥分支）'):
                    # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/6/then/2/then/0；本视图中静态 disabled。
                    # unilab:node_uuid=9c28aa38-fdf8-515e-a00a-761bfa3708c1 disabled=true
                    projected_control_0012 = material.review_control_node_v1(
                        operation_name='ensure_bottle_staged',
                        node_path='body/6/then/2/then/0',
                        control_kind='comment',
                        expected_sha256='7de517cda994ae0bed89b00da40e8311ddaa938cc35456a196332f5d188cac94',
                    )
                    # [SUBWORKFLOW transfer_bottle_staging_b_to_rack] 来源 ensure_bottle_staged@body/6/then/2/then/1；原节点 {"inputs":{"slot_id":{"var":"old_rack_slot"}},"op":"run_script","outputs":{},"script":"transfer_bottle_staging_b_to_rack"}
                    # unilab:node_uuid=ed9491c8-5f58-5564-9dd8-c3bec524613c
                    nested_operation_0013 = transfer_bottle_staging_b_to_rack_operation_view_v2()
                # unilab:node_uuid=90ea0f79-6227-592e-a5b9-b4e65231fc9f
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 ensure_bottle_staged@body/6/then/2；本视图中静态 disabled。
                    # unilab:node_uuid=1086661f-b7fb-591a-8aad-7462a5d0d093 disabled=true
                    projected_control_0014 = material.review_control_node_v1(
                        operation_name='ensure_bottle_staged',
                        node_path='body/6/then/2',
                        control_kind='if',
                        expected_sha256='fe3ac98e9c09b236795fd80bf489ff20b8968bfa446ddf1d1825aca70ccf7872',
                    )
            # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/6/then/3；本视图中静态 disabled。
            # unilab:node_uuid=371ea0eb-0785-5104-9037-3010f3f0d56d disabled=true
            projected_control_0015 = material.review_control_node_v1(
                operation_name='ensure_bottle_staged',
                node_path='body/6/then/3',
                control_kind='comment',
                expected_sha256='6d8b20744c7184f26acf0bd58b15cf0ddc85d55d4eb2073262ddaebafafc3756',
            )
            # [SUBWORKFLOW transfer_bottle_rack_to_staging_b] 来源 ensure_bottle_staged@body/6/then/4；原节点 {"inputs":{"slot_id":{"var":"rack_slot"}},"op":"run_script","outputs":{},"script":"transfer_bottle_rack_to_staging_b"}
            # unilab:node_uuid=6553c987-0c23-5f6c-8d6e-36bb62e48dfd
            nested_operation_0016 = transfer_bottle_rack_to_staging_b_operation_view_v2()
        # unilab:node_uuid=0008ed81-8fd3-552c-aba5-54a8a42a3980
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 ensure_bottle_staged@body/6；本视图中静态 disabled。
            # unilab:node_uuid=b82c01ab-9127-5189-b4af-e0f6f1f17243 disabled=true
            projected_control_0017 = material.review_control_node_v1(
                operation_name='ensure_bottle_staged',
                node_path='body/6',
                control_kind='if',
                expected_sha256='ee0fbe8373c6e2d28221d31637096f52d0860619ee14ed2085eab7884ffdeac1',
            )
    # [VERIFY comment] 只读来源校验 ensure_bottle_staged@body/7；本视图中静态 disabled。
    # unilab:node_uuid=3df8d015-ec6d-5426-8ba4-31737f8fe243 disabled=true
    projected_control_0018 = material.review_control_node_v1(
        operation_name='ensure_bottle_staged',
        node_path='body/7',
        control_kind='comment',
        expected_sha256='2a5b66672e5e81a06fede17b587bd55d0ea0dd4e5788d4054436a88d2887ba41',
    )
    # [ACTION staging_a.locator_b] 来源 ensure_bottle_staged@body/8；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=f7cc8eac-013b-55e2-a343-81d40717ff38 disabled=true
    projected_action_0019 = staging_a.locator_b(
        target=True,
    )
