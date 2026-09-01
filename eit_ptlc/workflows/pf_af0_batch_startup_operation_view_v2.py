from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.robot_startup_check_operation_view_v2 import (
    robot_startup_check_operation_view_v2,
)
from eit_ptlc.workflows.robot_tool_ensure_operation_view_v2 import (
    robot_tool_ensure_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='aa182a64-c8a9-5521-8c5d-a2db5088d394',
    displayname='0 批次起手 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_af0_batch_startup_operation_view_v2() -> None:
    # [OPERATION pf_af0_batch_startup] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=389d1243-522f-51d3-a1bb-27e9688f893a disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_af0_batch_startup',
        inputs_json='{}',
        expected_sha256='8bb0d272d6d2977daa1b7a45f6d131144ab9b2c3d4912b64846b622be5d0af9c',
    )
    # [VERIFY comment] 只读来源校验 pf_af0_batch_startup@body/0；本视图中静态 disabled。
    # unilab:node_uuid=f87cc216-a93f-564a-bfba-f9249904a71f disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_af0_batch_startup',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='483d9528a9766ec010b04e4873d0c8a6908f9d75486d5fdaa1aab3200a46301a',
    )
    # [VERIFY human] 只读来源校验 pf_af0_batch_startup@body/1；本视图中静态 disabled。
    # unilab:node_uuid=b624812d-abb6-551f-a210-62f44abd80a8 disabled=true
    projected_control_0003 = material.review_control_node_v1(
        operation_name='pf_af0_batch_startup',
        node_path='body/1',
        control_kind='human',
        expected_sha256='eb7d8802f32c26556f283e379b3ea489917575cc9b6a19c0b881c20685d1a086',
    )
    # [SUBWORKFLOW robot_startup_check] 来源 pf_af0_batch_startup@body/2；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"robot_startup_check"}
    # unilab:node_uuid=d19dc017-6aa6-57d6-a628-0ff5b5c523c2
    nested_operation_0004 = robot_startup_check_operation_view_v2()
    # [VERIFY comment] 只读来源校验 pf_af0_batch_startup@body/3；本视图中静态 disabled。
    # unilab:node_uuid=dc56b6ea-4e96-5e83-a0e2-fd06b2d70c26 disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='pf_af0_batch_startup',
        node_path='body/3',
        control_kind='comment',
        expected_sha256='266c516d8ad532a1da8bef8aa777f12ee11361103c747d4c15e4d45938111b94',
    )
    # [SUBWORKFLOW robot_tool_ensure] 来源 pf_af0_batch_startup@body/4；原节点 {"inputs":{"needed":{"lit":1}},"op":"run_script","outputs":{},"script":"robot_tool_ensure"}
    # unilab:node_uuid=e3d455e6-d05f-5579-b32b-226ca2036cc0
    nested_operation_0006 = robot_tool_ensure_operation_view_v2()
