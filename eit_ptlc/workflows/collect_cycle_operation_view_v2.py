from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.collect_prepare_operation_view_v2 import (
    collect_prepare_operation_view_v2,
)
from eit_ptlc.workflows.collect_load_operation_view_v2 import (
    collect_load_operation_view_v2,
)
from eit_ptlc.workflows.collect_execute_operation_view_v2 import (
    collect_execute_operation_view_v2,
)
from eit_ptlc.workflows.collect_unload_operation_view_v2 import (
    collect_unload_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='76d578b7-3390-5669-9bc8-d108492abf65',
    displayname='收集-周期 (准备 -> 上料 -> 执行 -> 下料) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def collect_cycle_operation_view_v2() -> None:
    # [OPERATION collect_cycle] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=51a8d6d2-f792-507b-a6b8-fc17585e1b0b disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='collect_cycle',
        inputs_json='{"bottle_slot":1,"collector_slot":1,"liquid_repeat_count":1,"solvent_volume_ml":0.1}',
        expected_sha256='798ad3a700f17231deadb99c5a1e4b04ef67e0b28d241e174a96eecbef93dde1',
    )
    # [VERIFY comment] 只读来源校验 collect_cycle@body/0；本视图中静态 disabled。
    # unilab:node_uuid=5258ff5f-b3ee-51d0-be3d-465b947bc2f8 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='collect_cycle',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='67325383555ba17cd0db7320b3c3d6cddf8c884e572a03b64f36fccf8d890a19',
    )
    # [SUBWORKFLOW collect_prepare] 来源 collect_cycle@body/1；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"collect_prepare"}
    # unilab:node_uuid=ec5e25f6-9353-5dfa-a0d2-5a03ff59ddec
    nested_operation_0003 = collect_prepare_operation_view_v2()
    # [VERIFY comment] 只读来源校验 collect_cycle@body/2；本视图中静态 disabled。
    # unilab:node_uuid=199f8586-a96c-5c8b-ac61-63f62cad884c disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='collect_cycle',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='8e2eb7f2b27ec8eb70c74692cfb428d3433d2b72f6fe92ea30b4e1727f8e7f93',
    )
    # [SUBWORKFLOW collect_load] 来源 collect_cycle@body/3；原节点 {"inputs":{"bottle_slot":{"var":"bottle_slot"}},"op":"run_script","outputs":{},"script":"collect_load"}
    # unilab:node_uuid=65fe1d49-1e42-510b-b046-371153a1784c
    nested_operation_0005 = collect_load_operation_view_v2()
    # [VERIFY comment] 只读来源校验 collect_cycle@body/4；本视图中静态 disabled。
    # unilab:node_uuid=9d6316b2-090a-59cc-99e5-8ac2a25f2cd7 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='collect_cycle',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='42ac154d7fb9a377e35c732e2f0630943596c7b61b2686b773f1e6b4145f7d0c',
    )
    # [SUBWORKFLOW collect_execute] 来源 collect_cycle@body/5；原节点 {"inputs":{"liquid_repeat_count":{"var":"liquid_repeat_count"},"solvent_volume_ml":{"var":"solvent_volume_ml"}},"op":"run_script","outputs":{},"script":"collect_execute"}
    # unilab:node_uuid=80f5a065-ef9a-5753-ad4f-ec5e798f323c
    nested_operation_0007 = collect_execute_operation_view_v2()
    # [VERIFY comment] 只读来源校验 collect_cycle@body/6；本视图中静态 disabled。
    # unilab:node_uuid=550fb66e-c964-54c7-8b15-03614a650337 disabled=true
    projected_control_0008 = material.review_control_node_v1(
        operation_name='collect_cycle',
        node_path='body/6',
        control_kind='comment',
        expected_sha256='962d54e29d53a142d99c9d835188e814d3a9eae6918ee1f446713fa687907f98',
    )
    # [SUBWORKFLOW collect_unload] 来源 collect_cycle@body/7；原节点 {"inputs":{"bottle_slot":{"var":"bottle_slot"},"collector_slot":{"var":"collector_slot"}},"op":"run_script","outputs":{},"script":"collect_unload"}
    # unilab:node_uuid=37632d39-31de-5a5f-9c92-e31c714b957b
    nested_operation_0009 = collect_unload_operation_view_v2()
