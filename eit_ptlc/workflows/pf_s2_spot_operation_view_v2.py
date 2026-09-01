from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.sampling_execute_operation_view_v2 import (
    sampling_execute_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='1eeab1fc-ca8e-5e1f-8208-ab6743f4c244',
    displayname='2-1 点样执行 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s2_spot_operation_view_v2() -> None:
    # [OPERATION pf_s2_spot] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=6be84050-1e25-5781-a14e-58b69f66b02c disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s2_spot',
        inputs_json='{}',
        expected_sha256='114e6489c48cfde641bf3b183843ca4d2c36457a6b2106988e24b1f3d02f9ef2',
    )
    # [VERIFY comment] 只读来源校验 pf_s2_spot@body/0；本视图中静态 disabled。
    # unilab:node_uuid=788d091f-1ae0-5f19-a15f-a0cf3520f461 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s2_spot',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='9d32413268e2aa8da3032089c2d7dfdae67e84cfd89023e5d594b035c4b67067',
    )
    # [SUBWORKFLOW sampling_execute] 来源 pf_s2_spot@body/1；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"sampling_execute"}
    # unilab:node_uuid=47c0a616-6869-5ed6-a749-3d01a3ce4631
    nested_operation_0003 = sampling_execute_operation_view_v2()
