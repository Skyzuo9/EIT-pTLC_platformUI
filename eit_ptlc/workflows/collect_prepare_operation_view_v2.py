from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_collect import PLCCollect
from eit_ptlc.unilab_domain.devices.material import MaterialProxy


collect: PLCCollect = device('plc_collect')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='467ee411-128d-5e36-8cc7-e26279ed9803',
    displayname='收集-准备 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def collect_prepare_operation_view_v2() -> None:
    # [OPERATION collect_prepare] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=6c9023db-8485-5f8d-9ded-0cc176c2b3bb disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='collect_prepare',
        inputs_json='{}',
        expected_sha256='8f8c2f53748db71feff6cb7fc793d74001dbc0b18ff82956dc6db752d8e59fae',
    )
    # [VERIFY comment] 只读来源校验 collect_prepare@body/0；本视图中静态 disabled。
    # unilab:node_uuid=3c6c1aac-7b16-5c9a-af82-21872ce8b09b disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='collect_prepare',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='aa19b5a61a50cb6debd48f175c9c60d6cc0d2e61afeb90f3cb9a33de5f8cd1be',
    )
    # [ACTION collect.init] 来源 collect_prepare@body/1；原节点 {"action":"collect.init","mode":"RUN","op":"call"}
    # unilab:node_uuid=450afa07-e676-50c1-9ce7-1a88c92a1808 disabled=true
    projected_action_0003 = collect.init()
