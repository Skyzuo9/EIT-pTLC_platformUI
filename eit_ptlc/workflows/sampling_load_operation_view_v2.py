from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_sampling import PLCSampling
from eit_ptlc.workflows.feedlift_load_cycle_operation_view_v2 import (
    feedlift_load_cycle_operation_view_v2,
)
from eit_ptlc.workflows.robot_suction_put_operation_view_v2 import (
    robot_suction_put_operation_view_v2,
)


material: MaterialProxy = device('material')
sampling: PLCSampling = device('plc_sampling')


@workflow(
    workflow_uuid='c522d9da-29dd-5ffb-8bdb-5e3fb63a1e83',
    displayname='上样-上料 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def sampling_load_operation_view_v2() -> None:
    # [OPERATION sampling_load] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=3bbb210d-2843-5178-a684-bc0f0d07c27f disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='sampling_load',
        inputs_json='{}',
        expected_sha256='9f4b238f3296d990e3f84b2ccd12b562a21244453c8bdc668932a0e90f507636',
    )
    # [VERIFY comment] 只读来源校验 sampling_load@body/0；本视图中静态 disabled。
    # unilab:node_uuid=40da4c3a-4763-58e6-ac2a-022fbeb2b0fc disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='sampling_load',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='279b8b83f21735b58aa21eb02e056f24be31fc165a245096593597c77413a23e',
    )
    # [ACTION sampling.place_release] 来源 sampling_load@body/1；原节点 {"action":"sampling.place_release","mode":"RUN","op":"call"}
    # unilab:node_uuid=95e545a9-cc99-53db-b147-756ebd7a5f3a disabled=true
    projected_action_0003 = sampling.place_release()
    # [ACTION sampling.place_axis] 来源 sampling_load@body/2；原节点 {"action":"sampling.place_axis","mode":"RUN","op":"call"}
    # unilab:node_uuid=4badc601-eba4-5ab3-8ca9-a3c9d3cc77d4 disabled=true
    projected_action_0004 = sampling.place_axis()
    # [VERIFY comment] 只读来源校验 sampling_load@body/3；本视图中静态 disabled。
    # unilab:node_uuid=409fb790-ec04-5941-b8fc-6b2c14964f86 disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='sampling_load',
        node_path='body/3',
        control_kind='comment',
        expected_sha256='261c709adebc42053d1aecb9aba388b21dca097333190537fe3afffa2d80d504',
    )
    # [SUBWORKFLOW feedlift_load_cycle] 来源 sampling_load@body/4；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"feedlift_load_cycle"}
    # unilab:node_uuid=ac5f7a35-c58f-5214-b08e-f05525500d7c
    nested_operation_0006 = feedlift_load_cycle_operation_view_v2()
    # [SUBWORKFLOW robot_suction_put] 来源 sampling_load@body/5；原节点 {"inputs":{"station_id":{"lit":"spotting"}},"op":"run_script","outputs":{},"script":"robot_suction_put"}
    # unilab:node_uuid=c32d8411-97ee-58ee-9e46-781a9ea61b12
    nested_operation_0007 = robot_suction_put_operation_view_v2()
    # [VERIFY comment] 只读来源校验 sampling_load@body/6；本视图中静态 disabled。
    # unilab:node_uuid=1c92dcbd-7e2e-5d33-8884-d73eb5eed6e5 disabled=true
    projected_control_0008 = material.review_control_node_v1(
        operation_name='sampling_load',
        node_path='body/6',
        control_kind='comment',
        expected_sha256='3938c51eb423a7bc48f539f82c00867079fec7a661bbdbb4f592a9e44a5033c0',
    )
    # [ACTION sampling.place_locate] 来源 sampling_load@body/7；原节点 {"action":"sampling.place_locate","mode":"RUN","op":"call"}
    # unilab:node_uuid=7de6f58b-8ba5-5fc7-8321-bbdc891a8064 disabled=true
    projected_action_0009 = sampling.place_locate()
