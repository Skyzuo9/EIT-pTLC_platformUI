from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.sampling_prepare_operation_view_v2 import (
    sampling_prepare_operation_view_v2,
)
from eit_ptlc.workflows.sampling_load_operation_view_v2 import (
    sampling_load_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='f46360f6-1b5a-52ea-8e72-330f1fee7f44',
    displayname='1 上样上料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s1_load_operation_view_v2() -> None:
    # [OPERATION pf_s1_load] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=746cf617-4fec-58a6-a2ec-052ab5fd2af3 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s1_load',
        inputs_json='{}',
        expected_sha256='b4860c9ed3a77d959785829dcc969433d316b3eb2a7823c5fe38daced9f4bcaa',
    )
    # [VERIFY comment] 只读来源校验 pf_s1_load@body/0；本视图中静态 disabled。
    # unilab:node_uuid=63691e59-0cfa-5c8d-919f-46ad1edaaedd disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s1_load',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='4ed49823bdf8377f7705fef6e1e8682c4e5837c0c532ea143385796092fb8d02',
    )
    # [SUBWORKFLOW sampling_prepare] 来源 pf_s1_load@body/1；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"sampling_prepare"}
    # unilab:node_uuid=eb36e982-99a6-5248-812d-1e8060f9f13e
    nested_operation_0003 = sampling_prepare_operation_view_v2()
    # [VERIFY comment] 只读来源校验 pf_s1_load@body/2；本视图中静态 disabled。
    # unilab:node_uuid=19a3b9f8-ccd1-5281-8e9c-2190b35af639 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='pf_s1_load',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='3c6ba814232f4d8d71c54ed8f0fe06e4e7122bb3a7e393f8f75b298608ce9ab1',
    )
    # [SUBWORKFLOW sampling_load] 来源 pf_s1_load@body/3；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"sampling_load"}
    # unilab:node_uuid=fac66ede-61f0-586b-8a00-dea54d42f104
    nested_operation_0005 = sampling_load_operation_view_v2()
