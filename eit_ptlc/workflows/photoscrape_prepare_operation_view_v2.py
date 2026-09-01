from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape


material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')


@workflow(
    workflow_uuid='fd7813fd-3acc-5898-8c3b-7e4de98720b6',
    displayname='拍照刮板-准备 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def photoscrape_prepare_operation_view_v2() -> None:
    # [OPERATION photoscrape_prepare] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=3507bbaa-8b99-518d-aec9-24f03483e6e9 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='photoscrape_prepare',
        inputs_json='{}',
        expected_sha256='2dc9cd6c05e40e79c92f2f6309a464218bf6636a62c1e9c53d156ae55b2f4b2d',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_prepare@body/0；本视图中静态 disabled。
    # unilab:node_uuid=b46c43a0-5714-534a-b627-3c81c52104f1 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='photoscrape_prepare',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='3a6a45c54d35018d37f1e0c76f494eab38f439747ec068d11e3717c8eccd5bb4',
    )
    # [ACTION photoscrape.init] 来源 photoscrape_prepare@body/1；原节点 {"action":"photoscrape.init","mode":"RUN","op":"call"}
    # unilab:node_uuid=92abf4d0-464c-53a9-b8b2-5772eedaad95 disabled=true
    projected_action_0003 = photoscrape.init()
    # [VERIFY comment] 只读来源校验 photoscrape_prepare@body/2；本视图中静态 disabled。
    # unilab:node_uuid=45053a83-c402-5e84-b070-38830edca66e disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='photoscrape_prepare',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='c308c06b8cdeb95bb13c30d2e20a936da35461395f6a00075a1f403dc14b2ff5',
    )
    # [ACTION photoscrape.cam_x335] 来源 photoscrape_prepare@body/3；原节点 {"action":"photoscrape.cam_x335","mode":"RUN","op":"call"}
    # unilab:node_uuid=f8468fee-84fe-5a24-b430-cd68cbf426ab disabled=true
    projected_action_0005 = photoscrape.cam_x335()
