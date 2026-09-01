from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_sampling import PLCSampling


material: MaterialProxy = device('material')
sampling: PLCSampling = device('plc_sampling')


@workflow(
    workflow_uuid='450ac528-57c4-58a9-a0c7-d3976e816e75',
    displayname='上样-准备 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def sampling_prepare_operation_view_v2() -> None:
    # [OPERATION sampling_prepare] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=2120ead1-bdda-5540-98be-27755dc5bf5d disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='sampling_prepare',
        inputs_json='{"asp_speed":250,"flush_disp_speed":300,"flush_volume_ml":17.0,"outer_wash_volume_ml":5.0,"spot_head_disp_speed":100,"spot_head_volume_ml":3.0,"step_delay":1500}',
        expected_sha256='ce29a3044bccc79faa9b75c7a1621f05befe1755534ab5a65322ed6519b2728b',
    )
    # [ACTION sampling.init] 来源 sampling_prepare@body/0；原节点 {"action":"sampling.init","mode":"RUN","op":"call"}
    # unilab:node_uuid=36baf18d-2e17-5039-be5b-3fdf48b7d0f6 disabled=true
    projected_action_0002 = sampling.init()
    # [VERIFY comment] 只读来源校验 sampling_prepare@body/1；本视图中静态 disabled。
    # unilab:node_uuid=91deed33-a34f-50e7-ab19-63a0996f769f disabled=true
    projected_control_0003 = material.review_control_node_v1(
        operation_name='sampling_prepare',
        node_path='body/1',
        control_kind='comment',
        expected_sha256='13a1220dcb5d58b2ac330dd364aa80c608cebe642496effd651de607bf467071',
    )
    # [CONTROL with_resources] 来源 sampling_prepare@body/2；原节点 {"body":[{"action":"sampling.flush","args":{"asp_speed":{"var":"asp_speed"},"flush_disp_speed":{"var":"flush_disp_speed"},"flush_volume_ml":{"var":"flush_volume_ml"},"outer_wash_volume_ml":{"var":"outer_wash_volume_ml"},"spot_head_disp_speed":{"var":"spot_head_disp_speed"},"spot_head_volume_ml":{"var":"spot_head_volume_ml"},...
    # unilab:node_uuid=921c7a09-66ae-5458-9ef1-37bf8763bd3c
    with group(name='🔒 局部 ResourceGate · device:vacuum_pump'):
        # [VERIFY with_resources] 只读来源校验 sampling_prepare@body/2；本视图中静态 disabled。
        # unilab:node_uuid=5b55f72d-95fa-5b07-8113-77fa889ce69c disabled=true
        projected_control_0004 = material.review_control_node_v1(
            operation_name='sampling_prepare',
            node_path='body/2',
            control_kind='with_resources',
            expected_sha256='d7b1bbab7f9a6898115f579cde1f36fadb8ea359d9f04f0265a8d0982535652a',
        )
        # unilab:node_uuid=2451e8cc-3eda-5ccd-a1c3-931a46ac81c6
        with group(name='BODY（结构展开一次）'):
            # [ACTION sampling.flush] 来源 sampling_prepare@body/2/body/0；原节点 {"action":"sampling.flush","args":{"asp_speed":{"var":"asp_speed"},"flush_disp_speed":{"var":"flush_disp_speed"},"flush_volume_ml":{"var":"flush_volume_ml"},"outer_wash_volume_ml":{"var":"outer_wash_volume_ml"},"spot_head_disp_speed":{"var":"spot_head_disp_speed"},"spot_head_volume_ml":{"var":"spot_head_volume_ml"},"s...
            # unilab:node_uuid=9647f153-3a17-5eac-9816-9dc2138d6e83 disabled=true
            projected_action_0005 = sampling.flush()
    # [VERIFY comment] 只读来源校验 sampling_prepare@body/3；本视图中静态 disabled。
    # unilab:node_uuid=0af2a504-c4f2-5579-a014-5f59ee07c300 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='sampling_prepare',
        node_path='body/3',
        control_kind='comment',
        expected_sha256='14c13af489e079a2dd4cecc53e352bb065851fc261b0bc989706f522e9c61163',
    )
    # [ACTION sampling.place_axis] 来源 sampling_prepare@body/4；原节点 {"action":"sampling.place_axis","mode":"RUN","op":"call"}
    # unilab:node_uuid=dbd514f0-699f-52f4-901c-ece8676b337f disabled=true
    projected_action_0007 = sampling.place_axis()
