from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.photoscrape_process_operation_view_v2 import (
    photoscrape_process_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='361c1f89-8111-50ed-9d80-f2065b218c02',
    displayname='7 拍照刮取 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s9_scrape_operation_view_v2() -> None:
    # [OPERATION pf_s9_scrape] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=0ab87cac-47b2-5045-9161-9ede84c3b6ba disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s9_scrape',
        inputs_json='{"before_path":"","mode":"manual","sample_id":"","save_dir":""}',
        expected_sha256='a83aa296804ea35c03718318d47cf2c6745442c17539a5c3d443c6af1e4db48e',
    )
    # [VERIFY comment] 只读来源校验 pf_s9_scrape@body/0；本视图中静态 disabled。
    # unilab:node_uuid=2279e4e1-25e6-5c57-8e3c-debabdaf4b12 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s9_scrape',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='cec1b0d663b5989a1181d97e6c653492b7d3956160c3772d95c042688b788348',
    )
    # [SUBWORKFLOW photoscrape_process] 来源 pf_s9_scrape@body/1；原节点 {"inputs":{"before_path":{"var":"before_path"},"mode":{"var":"mode"},"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"op":"run_script","outputs":{},"script":"photoscrape_process"}
    # unilab:node_uuid=137cc9f3-1a79-5bf3-a3a9-d6a6d903dc54
    nested_operation_0003 = photoscrape_process_operation_view_v2()
