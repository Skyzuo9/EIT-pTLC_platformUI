from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.photoscrape_unload_operation_view_v2 import (
    photoscrape_unload_operation_view_v2,
)
from eit_ptlc.workflows.feedlift_unload_cycle_operation_view_v2 import (
    feedlift_unload_cycle_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='27f83cb9-53d1-55e7-ad5f-cd81073b0370',
    displayname='9 废板下料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s11_unload_operation_view_v2() -> None:
    # [OPERATION pf_s11_unload] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=e2b3789c-8089-5d78-89c9-532b307894a7 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s11_unload',
        inputs_json='{}',
        expected_sha256='6c60e4f50e584baee93f13859e29af3a7b1651bd441a0dd86b21f0628f67276b',
    )
    # [VERIFY comment] 只读来源校验 pf_s11_unload@body/0；本视图中静态 disabled。
    # unilab:node_uuid=02e96896-3db7-5461-ae0e-376b6969b75d disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s11_unload',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='137362b55c7a05bde19021c754b58065557964ef73582695be98ed5462b5943a',
    )
    # [SUBWORKFLOW photoscrape_unload] 来源 pf_s11_unload@body/1；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"photoscrape_unload"}
    # unilab:node_uuid=8afe5b3a-32ba-5840-bf3f-41a02c439f54
    nested_operation_0003 = photoscrape_unload_operation_view_v2()
    # [SUBWORKFLOW feedlift_unload_cycle] 来源 pf_s11_unload@body/2；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"feedlift_unload_cycle"}
    # unilab:node_uuid=eee67cef-3083-584e-8a7f-6df31f8aac70
    nested_operation_0004 = feedlift_unload_cycle_operation_view_v2()
