from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.develop_prepare_operation_view_v2 import (
    develop_prepare_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='69a3f1ff-d2dc-5487-8350-d1d0576336f9',
    displayname='2-2 展缸预备 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s3_tank_prep_operation_view_v2() -> None:
    # [OPERATION pf_s3_tank_prep] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=d549afae-6c04-56b9-b241-9100b4f3da51 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s3_tank_prep',
        inputs_json='{"tank":1}',
        expected_sha256='a63f4ec1973bbd83c0acfae00cbdb671cd2f8277ed263c631b9f16bd72d4b1d0',
    )
    # [VERIFY comment] 只读来源校验 pf_s3_tank_prep@body/0；本视图中静态 disabled。
    # unilab:node_uuid=66d14e41-8ba5-5b00-932a-be2a5436ae9b disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s3_tank_prep',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='028e0098e04665759f149440c52d1a4292551c86c3673beb80020cf30759567b',
    )
    # [SUBWORKFLOW develop_prepare] 来源 pf_s3_tank_prep@body/1；原节点 {"inputs":{"tank":{"var":"tank"}},"op":"run_script","outputs":{},"script":"develop_prepare"}
    # unilab:node_uuid=fe84cdcd-8ded-5ed2-99aa-4f995ab95078
    nested_operation_0003 = develop_prepare_operation_view_v2()
