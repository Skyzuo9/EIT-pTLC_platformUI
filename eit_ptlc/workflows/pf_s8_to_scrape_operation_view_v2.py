from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.develop_unload_operation_view_v2 import (
    develop_unload_operation_view_v2,
)
from eit_ptlc.workflows.photoscrape_prepare_operation_view_v2 import (
    photoscrape_prepare_operation_view_v2,
)
from eit_ptlc.workflows.photoscrape_plate_load_operation_view_v2 import (
    photoscrape_plate_load_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='a0a890ab-0c0d-511f-947f-c6ae1521fd5b',
    displayname='6 出缸上刮板台 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s8_to_scrape_operation_view_v2() -> None:
    # [OPERATION pf_s8_to_scrape] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=7fea4851-fd41-52d0-ac0d-a5246ede6247 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s8_to_scrape',
        inputs_json='{"tank":1}',
        expected_sha256='cdbb0a6fda93dac21ef28e53c2a7fd4eef2c867c77925c8a3a6461f6e477f4ec',
    )
    # [VERIFY comment] 只读来源校验 pf_s8_to_scrape@body/0；本视图中静态 disabled。
    # unilab:node_uuid=53492125-28ef-501f-b63d-469ad3ca6029 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s8_to_scrape',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='254366bd515d3761b62e7fa181af00d53d8bb0cfc863ecefab2c91c322f55221',
    )
    # [SUBWORKFLOW develop_unload] 来源 pf_s8_to_scrape@body/1；原节点 {"inputs":{"tank":{"var":"tank"}},"op":"run_script","outputs":{},"script":"develop_unload"}
    # unilab:node_uuid=ce1866e4-a78f-5dd6-9a1f-9c0865b8326f
    nested_operation_0003 = develop_unload_operation_view_v2()
    # [VERIFY comment] 只读来源校验 pf_s8_to_scrape@body/2；本视图中静态 disabled。
    # unilab:node_uuid=27759d5c-fd58-5aa6-a033-5b93f3c1b9b1 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='pf_s8_to_scrape',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='3f6115b9c3a126a5a4cb7af7672d428f781e8af522f4364f9ff65106d9064bd0',
    )
    # [SUBWORKFLOW photoscrape_prepare] 来源 pf_s8_to_scrape@body/3；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"photoscrape_prepare"}
    # unilab:node_uuid=e77dbf12-350c-5f34-9eac-c84bcb2dbf1a
    nested_operation_0005 = photoscrape_prepare_operation_view_v2()
    # [SUBWORKFLOW photoscrape_plate_load] 来源 pf_s8_to_scrape@body/4；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"photoscrape_plate_load"}
    # unilab:node_uuid=e0ef4331-4514-5d57-8af3-13e4038f573e
    nested_operation_0006 = photoscrape_plate_load_operation_view_v2()
