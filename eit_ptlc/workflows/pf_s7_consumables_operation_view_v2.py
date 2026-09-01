from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.workflows.ensure_collector_staged_operation_view_v2 import (
    ensure_collector_staged_operation_view_v2,
)
from eit_ptlc.workflows.ensure_bottle_staged_operation_view_v2 import (
    ensure_bottle_staged_operation_view_v2,
)
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)
from eit_ptlc.workflows.transfer_collector_staging_a_to_scrape_operation_view_v2 import (
    transfer_collector_staging_a_to_scrape_operation_view_v2,
)


material: MaterialProxy = device('material')
staging_a: PLCStagingA = device('plc_staginga')


@workflow(
    workflow_uuid='ae8abb23-c302-57a9-9f39-796f9963162b',
    displayname='5-2 备耗材 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s7_consumables_operation_view_v2() -> None:
    # [OPERATION pf_s7_consumables] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=25c0207f-033b-5680-845e-a4eab53655a1 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s7_consumables',
        inputs_json='{"reserve_for":""}',
        expected_sha256='2f298d4a6b7765104410f6ff8b488f684b98f6db3beb93d11c88781585b271e4',
    )
    # [VERIFY comment] 只读来源校验 pf_s7_consumables@body/0；本视图中静态 disabled。
    # unilab:node_uuid=8e2b30cc-f136-5827-8880-05c54ca8e978 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s7_consumables',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='4cb1bb24e4f3411490f78db9bc55fe7613593b23560c55fa1a9a171627827c7e',
    )
    # [SUBWORKFLOW ensure_collector_staged] 来源 pf_s7_consumables@body/1；原节点 {"inputs":{"reserve_for":{"var":"reserve_for"}},"op":"run_script","outputs":{"hole":{"var":"collector_hole"}},"script":"ensure_collector_staged"}
    # unilab:node_uuid=b6ed4a00-2f6a-51ef-ba01-391c717cb45e
    nested_operation_0003 = ensure_collector_staged_operation_view_v2()
    # [SUBWORKFLOW ensure_bottle_staged] 来源 pf_s7_consumables@body/2；原节点 {"inputs":{"reserve_for":{"var":"reserve_for"}},"op":"run_script","outputs":{"hole":{"var":"bottle_hole"}},"script":"ensure_bottle_staged"}
    # unilab:node_uuid=402f4026-bba8-5f2c-b64f-c51ca30a19d6
    nested_operation_0004 = ensure_bottle_staged_operation_view_v2()
    # [VERIFY comment] 只读来源校验 pf_s7_consumables@body/3；本视图中静态 disabled。
    # unilab:node_uuid=6e17b3c5-c576-5faa-b559-1f9091d1fac7 disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='pf_s7_consumables',
        node_path='body/3',
        control_kind='comment',
        expected_sha256='df3a5a1237a2931bcc94957d03c30ad3362c254c6534ae7665abf2fb95e7a99f',
    )
    # [ACTION staging_a.locator_a] 来源 pf_s7_consumables@body/4；原节点 {"action":"staging_a.locator_a","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=a60412a8-bed9-5e28-991c-8a269c620c64 disabled=true
    projected_action_0006 = staging_a.locator_a(
        target=True,
    )
    # [ACTION staging_a.locator_b] 来源 pf_s7_consumables@body/5；原节点 {"action":"staging_a.locator_b","args":{"target":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=5b1f2264-6af5-5081-9336-74732fb10139 disabled=true
    projected_action_0007 = staging_a.locator_b(
        target=True,
    )
    # [VERIFY comment] 只读来源校验 pf_s7_consumables@body/6；本视图中静态 disabled。
    # unilab:node_uuid=f39f4fef-323f-5dd9-9ba4-f41236bb6fa4 disabled=true
    projected_control_0008 = material.review_control_node_v1(
        operation_name='pf_s7_consumables',
        node_path='body/6',
        control_kind='comment',
        expected_sha256='f1afdfa7f6df52c97f96e168db6e75c9601cf9bd79500bd6db93eff2bd6698f8',
    )
    # [SUBWORKFLOW robot_tool_ensure] 来源 pf_s7_consumables@body/7；原节点 {"inputs":{"needed":{"lit":3}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=3636ea9e-f0ed-51b8-a3b9-352e50748821
    nested_operation_0009 = robot_tool_ensure_operation_view_v2()
    # [VERIFY comment] 只读来源校验 pf_s7_consumables@body/8；本视图中静态 disabled。
    # unilab:node_uuid=b4c32bb4-57b9-5165-8bab-a9574cdda263 disabled=true
    projected_control_0010 = material.review_control_node_v1(
        operation_name='pf_s7_consumables',
        node_path='body/8',
        control_kind='comment',
        expected_sha256='0c4e309ceaaefa08a5d4bc2c0404b4e5984655ecb8eb79f23e72d72af80d5831',
    )
    # [SUBWORKFLOW transfer_collector_staging_a_to_scrape] 来源 pf_s7_consumables@body/9；原节点 {"inputs":{"slot_id":{"var":"collector_hole"}},"op":"run_script","outputs":{},"script":"transfer_collector_staging_a_to_scrape"}
    # unilab:node_uuid=866256d4-fc4b-5c26-8d48-6227328335c1
    nested_operation_0011 = transfer_collector_staging_a_to_scrape_operation_view_v2()
