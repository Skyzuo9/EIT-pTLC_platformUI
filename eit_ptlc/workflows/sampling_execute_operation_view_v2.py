from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_sampling import PLCSampling
from eit_ptlc.workflows.sampling_volume_model_operation_view_v2 import (
    sampling_volume_model_operation_view_v2,
)


material: MaterialProxy = device('material')
sampling: PLCSampling = device('plc_sampling')


@workflow(
    workflow_uuid='4743971b-8af1-52c4-a726-ef86e6051ab7',
    displayname='上样-执行 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def sampling_execute_operation_view_v2() -> None:
    # [OPERATION sampling_execute] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=3fed2c32-d7d8-55f3-a14e-a126abb1fcbb disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='sampling_execute',
        inputs_json='{"air_gap_ml":0.2,"dry_cycles":1,"dry_speed_mm_s":20,"mix_count":3,"mix_volume_ml":1.5,"over_aspirate_ml":1.5,"plate_no":"1","plate_spec":"4×6","rinse_rounds":1,"rinse_volume_ml":3,"sample_volume_ml":2,"spot_disp_speed":6,"spot_speed_mm_s":40,"spot_x_end":0.0,"spot_x_start":0.0,"spot_y_height":0.0,"well":"A1"}',
        expected_sha256='a6faff625c82d547d3460079695231d52b8549f755b2c5c2cf674b40c70852ff',
    )
    # [VERIFY comment] 只读来源校验 sampling_execute@body/0；本视图中静态 disabled。
    # unilab:node_uuid=0cf5c307-8125-5555-9c79-eb1529cf4e47 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='sampling_execute',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='b829a9dc009509dc6b8c80f41c8d9b87f857f257060d526723da1047af42b981',
    )
    # [SUBWORKFLOW sampling_volume_model] 来源 sampling_execute@body/1；原节点 {"inputs":{"air_gap_ml":{"var":"air_gap_ml"},"over_aspirate_ml":{"var":"over_aspirate_ml"},"rinse_volume_ml":{"var":"rinse_volume_ml"},"sample_volume_ml":{"var":"sample_volume_ml"}},"op":"run_script","outputs":{"aspirate_round_ml":{"var":"aspirate_round_ml"},"aspirate_total_ml":{"var":"aspirate_total_ml"},"band_end_ml":{"var...
    # unilab:node_uuid=00f3febc-0d98-592d-9e5b-1f2711ba1f97
    nested_operation_0003 = sampling_volume_model_operation_view_v2()
    # [VERIFY comment] 只读来源校验 sampling_execute@body/2；本视图中静态 disabled。
    # unilab:node_uuid=9601d1d9-d61f-5538-a39d-758a76cecceb disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='sampling_execute',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='ec4422ecd6f19be526669bce8f911a739c8cac8eab346583bbb7994160cec9fe',
    )
    # [VERIFY comment] 只读来源校验 sampling_execute@body/3；本视图中静态 disabled。
    # unilab:node_uuid=cb93ec7a-da33-5404-927f-a9ae2d8e828e disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='sampling_execute',
        node_path='body/3',
        control_kind='comment',
        expected_sha256='ae72e871b505785aed60aa80f0971ee88896943d18c7c3fd64adfd47c8bcf89f',
    )
    # [ACTION sampling.aspirate] 来源 sampling_execute@body/4；原节点 {"action":"sampling.aspirate","args":{"air_gap_ml":{"var":"air_gap_ml"},"asp_speed":{"lit":50},"plate_no":{"var":"plate_no"},"plate_spec":{"var":"plate_spec"},"sample_volume_ml":{"var":"aspirate_total_ml"},"step_delay":{"lit":1500},"well":{"var":"well"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=6d5ea5ce-69fc-5b4a-9cb0-86a605f26797 disabled=true
    projected_action_0006 = sampling.aspirate(
        plate_spec='4×6',
        plate_no='1',
        well='A1',
    )
    # [VERIFY comment] 只读来源校验 sampling_execute@body/5；本视图中静态 disabled。
    # unilab:node_uuid=c9b868c4-bc44-57c7-9a5d-bf996b8dc70d disabled=true
    projected_control_0007 = material.review_control_node_v1(
        operation_name='sampling_execute',
        node_path='body/5',
        control_kind='comment',
        expected_sha256='17365a714842c66f273f1d600b4bd50edc50c65a495b4e8d480aff0a2b19cac4',
    )
    # [ACTION sampling.spot_band_layer] 来源 sampling_execute@body/6；原节点 {"action":"sampling.spot_band_layer","args":{"dry_cycles":{"var":"dry_cycles"},"dry_speed_mm_s":{"var":"dry_speed_mm_s"},"ref_spot":{"lit":"spot_pose"},"spot_disp_speed":{"var":"spot_disp_speed"},"spot_end_position_ml":{"var":"band_end_ml"},"spot_speed_mm_s":{"var":"spot_speed_mm_s"},"step_delay":{"lit":1500},"x_end":{"var":...
    # unilab:node_uuid=f62ae672-7083-5b14-9b4d-2e616a4cb8b8 disabled=true
    projected_action_0008 = sampling.spot_band_layer(
        ref_spot='spot_pose',
    )
    # [VERIFY comment] 只读来源校验 sampling_execute@body/7；本视图中静态 disabled。
    # unilab:node_uuid=8afbcc26-d1c9-5b5f-ae5d-e3cd1bffa2f5 disabled=true
    projected_control_0009 = material.review_control_node_v1(
        operation_name='sampling_execute',
        node_path='body/7',
        control_kind='comment',
        expected_sha256='a0b196d054ee4b4e068cce4caeba8bf33ea55d742dcd1be2cc140aa3a9d8490f',
    )
    # [LOOP for · BODY NOT EXPANDED] 只读来源校验 sampling_execute@body/8；本视图中静态 disabled。
    # unilab:node_uuid=8a00a146-9618-59b5-b6dc-7f5d2d6be2ae disabled=true
    projected_control_0010 = material.review_control_node_v1(
        operation_name='sampling_execute',
        node_path='body/8',
        control_kind='for',
        expected_sha256='9bee4fc22510df57121dbee3dfa3c3ad9fd7f30dac35b8f960005afd620a13bf',
    )
