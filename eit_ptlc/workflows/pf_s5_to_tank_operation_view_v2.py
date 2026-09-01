from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.photoscrape_unload_operation_view_v2 import (
    photoscrape_unload_operation_view_v2,
)
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.develop_load_operation_view_v2 import (
    develop_load_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='570f3c34-6a59-5c94-b279-0e24981a6e25',
    displayname='4 取板进缸 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s5_to_tank_operation_view_v2() -> None:
    # [OPERATION pf_s5_to_tank] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=33ac7a06-b52b-5e86-b4c4-ba060f398971 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s5_to_tank',
        inputs_json='{"tank":1}',
        expected_sha256='bffdf7deb5b82a6102cc32265057000087865653895c2a439e3a935360c06842',
    )
    # [VERIFY comment] 只读来源校验 pf_s5_to_tank@body/0；本视图中静态 disabled。
    # unilab:node_uuid=8edb0a76-f43f-51b8-aad3-e583b96f6b82 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s5_to_tank',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='c1f7ff400e80e579c5ea2f2d8d15637e092231587a3d13dea9685f779ad1efc9',
    )
    # [SUBWORKFLOW photoscrape_unload] 来源 pf_s5_to_tank@body/1；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"photoscrape_unload"}
    # unilab:node_uuid=f49ea411-a628-5ff9-82bc-b8e3e27286a6
    nested_operation_0003 = photoscrape_unload_operation_view_v2()
    # [SUBWORKFLOW rail_move_safe] 来源 pf_s5_to_tank@body/2；原节点 {"inputs":{"target":{"lit":5}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
    # unilab:node_uuid=314bd0d4-e14a-5675-99e8-733d47fdb9b4
    nested_operation_0004 = rail_move_safe_operation_view_v2()
    # [VERIFY comment] 只读来源校验 pf_s5_to_tank@body/3；本视图中静态 disabled。
    # unilab:node_uuid=691c3e5e-ae67-5a4e-b67d-9f152ffcb179 disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='pf_s5_to_tank',
        node_path='body/3',
        control_kind='comment',
        expected_sha256='4f28be509a684771b3a0085e1d01bb5958414291d94338b8fade1a7e14baecb2',
    )
    # [SUBWORKFLOW develop_load] 来源 pf_s5_to_tank@body/4；原节点 {"inputs":{"tank":{"var":"tank"}},"op":"run_script","outputs":{},"script":"develop_load"}
    # unilab:node_uuid=767fd68a-18db-504a-b8d2-499bef367f8a
    nested_operation_0006 = develop_load_operation_view_v2()
