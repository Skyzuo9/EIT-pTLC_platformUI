from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.workflows.sampling_unload_operation_view_v2 import (
    sampling_unload_operation_view_v2,
)
from eit_ptlc.workflows.photoscrape_prepare_operation_view_v2 import (
    photoscrape_prepare_operation_view_v2,
)
from eit_ptlc.workflows.photoscrape_plate_load_operation_view_v2 import (
    photoscrape_plate_load_operation_view_v2,
)
from eit_ptlc.workflows.photoscrape_before_photo_capture_operation_view_v2 import (
    photoscrape_before_photo_capture_operation_view_v2,
)


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='cafecf27-c3f2-51ce-8f6d-f054cc0157f8',
    displayname='3 展开前拍照 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def pf_s4_photo_before_operation_view_v2() -> None:
    # [OPERATION pf_s4_photo_before] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=a653b94d-de3a-583b-b834-f65db0d89220 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='pf_s4_photo_before',
        inputs_json='{"sample_id":"","save_dir":""}',
        expected_sha256='9304f8e52cadc22f13e1836e7a0c581f7c67f1bbb9b79bd62f36fd1a38bba766',
    )
    # [VERIFY comment] 只读来源校验 pf_s4_photo_before@body/0；本视图中静态 disabled。
    # unilab:node_uuid=c2de948a-d9e3-51c0-a72b-4e4c66af6936 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='pf_s4_photo_before',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='7556137ab575f0f3c3a611cffa18627baabca6737530cd497e40c14be7996467',
    )
    # [SUBWORKFLOW sampling_unload] 来源 pf_s4_photo_before@body/1；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"sampling_unload"}
    # unilab:node_uuid=22d3644b-8cbb-5a84-b2e0-345f5a47eed6
    nested_operation_0003 = sampling_unload_operation_view_v2()
    # [VERIFY comment] 只读来源校验 pf_s4_photo_before@body/2；本视图中静态 disabled。
    # unilab:node_uuid=d960e6fa-2636-59ea-a988-acb06fc9b765 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='pf_s4_photo_before',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='a01247dbcca231c98a788bd800044681bdb3162817b6b3423f70747345bd359e',
    )
    # [SUBWORKFLOW photoscrape_prepare] 来源 pf_s4_photo_before@body/3；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"photoscrape_prepare"}
    # unilab:node_uuid=757d4e20-e9c5-5eb5-b25c-9f20faec06ac
    nested_operation_0005 = photoscrape_prepare_operation_view_v2()
    # [SUBWORKFLOW photoscrape_plate_load] 来源 pf_s4_photo_before@body/4；原节点 {"inputs":{},"op":"run_script","outputs":{},"script":"photoscrape_plate_load"}
    # unilab:node_uuid=71842a62-3dfd-5636-9c08-8533dae02573
    nested_operation_0006 = photoscrape_plate_load_operation_view_v2()
    # [VERIFY comment] 只读来源校验 pf_s4_photo_before@body/5；本视图中静态 disabled。
    # unilab:node_uuid=72a86142-15be-5e24-b629-0baf7846201f disabled=true
    projected_control_0007 = material.review_control_node_v1(
        operation_name='pf_s4_photo_before',
        node_path='body/5',
        control_kind='comment',
        expected_sha256='2be4cb88c57d611838e0d346dfc8e8ea03e5a47ca39e29930ae140476dbf157f',
    )
    # [SUBWORKFLOW photoscrape_before_photo_capture] 来源 pf_s4_photo_before@body/6；原节点 {"inputs":{"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"op":"run_script","outputs":{"before_path":{"var":"before_path"}},"script":"photoscrape_before_photo_capture"}
    # unilab:node_uuid=660e6256-e4b4-5f51-b033-5fd338eb4e46
    nested_operation_0008 = photoscrape_before_photo_capture_operation_view_v2()
