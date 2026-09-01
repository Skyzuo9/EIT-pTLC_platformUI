from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape


material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')


@workflow(
    workflow_uuid='cdfbe337-117c-50b4-b47c-17780d64904d',
    displayname='拍照刮板-before拍照 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def photoscrape_before_photo_capture_operation_view_v2() -> None:
    # [OPERATION photoscrape_before_photo_capture] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=ac8450e1-0d7f-5b1f-a784-9e549d8a2c9e disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='photoscrape_before_photo_capture',
        inputs_json='{"sample_id":"","save_dir":""}',
        expected_sha256='a4a9c4f11837b795122f0a5230004087c5f6ed9e6e7c9f08ac0dd7393829b2c7',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_before_photo_capture@body/0；本视图中静态 disabled。
    # unilab:node_uuid=e27e3eb3-859c-5e8f-9cb1-9928673e3b74 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='photoscrape_before_photo_capture',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='29ff9de63428ed8db8791c4a5c3320b96950d735578fe77ce785cde9353795ff',
    )
    # [ACTION photoscrape.cam_photopos] 来源 photoscrape_before_photo_capture@body/1；原节点 {"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=835f2693-0124-5b78-82f6-3f0531c3d659 disabled=true
    projected_action_0003 = photoscrape.cam_photopos(
        ref_8y='photo_8y',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_before_photo_capture@body/2；本视图中静态 disabled。
    # unilab:node_uuid=b01ead39-ea01-5b81-99cb-2e21becb3f4d disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='photoscrape_before_photo_capture',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='3b65ef612784f89b1a0937733df2574c8f4d1fc25295abfbc08b4e8613a2da6b',
    )
    # [ACTION photoscrape.capture] 来源 photoscrape_before_photo_capture@body/3；原节点 {"action":"photoscrape.capture","args":{"filename":{"lit":"before.jpg"},"profile":{"lit":"photoscrape"},"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"assign":{"var":"shot"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=f7d9b5fe-e243-5ed3-9b55-0451b4e0ca45 disabled=true
    projected_action_0005 = photoscrape.capture(
        sample_id='review-only',
        save_dir='review-only',
    )
    # [VERIFY assign] 只读来源校验 photoscrape_before_photo_capture@body/4；本视图中静态 disabled。
    # unilab:node_uuid=0c0dc898-ae5e-59cc-a375-91336d3e927a disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='photoscrape_before_photo_capture',
        node_path='body/4',
        control_kind='assign',
        expected_sha256='5b4a0c560b1af2c8ef48593b51f8871721eac7bc9fc91bf1bba2f654a2947eb4',
    )
    # [ACTION photoscrape.cam_photohome] 来源 photoscrape_before_photo_capture@body/5；原节点 {"action":"photoscrape.cam_photohome","mode":"RUN","op":"call"}
    # unilab:node_uuid=38b4e3b3-96f3-5471-8c62-3274c32c6123 disabled=true
    projected_action_0007 = photoscrape.cam_photohome()
