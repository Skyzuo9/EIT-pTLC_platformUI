from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_collect import PLCCollect
from eit_ptlc.unilab_domain.devices.material import MaterialProxy


collect: PLCCollect = device('plc_collect')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='782ba7a2-765f-5d69-957a-31f72d3eb420',
    displayname='收集-执行 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def collect_execute_operation_view_v2() -> None:
    # [OPERATION collect_execute] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=fe287dfb-f3a6-56e3-860c-db989ad16f54 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='collect_execute',
        inputs_json='{"liquid_repeat_count":1,"solvent_volume_ml":0.1}',
        expected_sha256='68356a50fb6a018714f39cfc4cb6efe860ae1bffcd515ded6483493b23c5c771',
    )
    # [VERIFY comment] 只读来源校验 collect_execute@body/0；本视图中静态 disabled。
    # unilab:node_uuid=c585d730-9cf5-5bb8-ac2a-7217dcc603f3 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='collect_execute',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='952af31590e9e80c47dc80310562ff8fc4251c3b2fd05811f3ade379892b49df',
    )
    # [ACTION collect.lift_press] 来源 collect_execute@body/1；原节点 {"action":"collect.lift_press","mode":"RUN","op":"call"}
    # unilab:node_uuid=b0e9ba23-d21a-5459-9883-02f226f9ae32 disabled=true
    projected_action_0003 = collect.lift_press()
    # [ACTION collect.collect] 来源 collect_execute@body/2；原节点 {"action":"collect.collect","args":{"liquid_repeat_count":{"var":"liquid_repeat_count"},"solvent_volume_ml":{"var":"solvent_volume_ml"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=a14f8414-b09d-5cc8-9b2f-a9680d000790 disabled=true
    projected_action_0004 = collect.collect()
    # [ACTION collect.transport_extend] 来源 collect_execute@body/3；原节点 {"action":"collect.transport_extend","mode":"RUN","op":"call"}
    # unilab:node_uuid=bfa73774-2f68-5816-ada7-6c3c30e2fd74 disabled=true
    projected_action_0005 = collect.transport_extend()
