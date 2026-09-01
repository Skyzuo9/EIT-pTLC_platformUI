from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy


material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='d77d632c-20f0-5c23-bb16-1fbc46a80127',
    displayname='上样-体积模型(派生+守卫) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def sampling_volume_model_operation_view_v2() -> None:
    # [OPERATION sampling_volume_model] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=1ebaa0e0-2836-5efc-8dd7-9b1af59efcd6 disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='sampling_volume_model',
        inputs_json='{"air_gap_ml":0.2,"over_aspirate_ml":1.5,"rinse_volume_ml":3,"sample_volume_ml":2}',
        expected_sha256='3b7485f556c642dbc7ea351382aeb9906336893a33f1c251b6150dd47f04db25',
    )
    # [VERIFY comment] 只读来源校验 sampling_volume_model@body/0；本视图中静态 disabled。
    # unilab:node_uuid=26e31294-4b7d-5ebc-bd4c-57391c7c549c disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='sampling_volume_model',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='52c5826d842d42e3362635f59ac0c88e55f96f2ca9de6dec560ed3f6b7796a4c',
    )
    # [VERIFY assign] 只读来源校验 sampling_volume_model@body/1；本视图中静态 disabled。
    # unilab:node_uuid=da0c099d-e4e6-506e-aaf9-1d49ea18c04c disabled=true
    projected_control_0003 = material.review_control_node_v1(
        operation_name='sampling_volume_model',
        node_path='body/1',
        control_kind='assign',
        expected_sha256='d9f024f0091f26648c1178ba35c332575c326f3832af33ce0ece77606a8bf294',
    )
    # [VERIFY comment] 只读来源校验 sampling_volume_model@body/2；本视图中静态 disabled。
    # unilab:node_uuid=d75d1546-185d-5469-889d-5c3939ab9db8 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='sampling_volume_model',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='97d8140b69d15b4ba9c5f7aa8b434fa53cd62a96c9916976dd37a0d23de3ede0',
    )
    # [VERIFY assign] 只读来源校验 sampling_volume_model@body/3；本视图中静态 disabled。
    # unilab:node_uuid=11323701-0d1c-5870-b160-e2889e10b547 disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='sampling_volume_model',
        node_path='body/3',
        control_kind='assign',
        expected_sha256='063974fd90f11b9cb4fff512766bd5b7047014bec551ddb5e9c2266d6bbe1100',
    )
    # [VERIFY assign] 只读来源校验 sampling_volume_model@body/4；本视图中静态 disabled。
    # unilab:node_uuid=a9438006-4f7d-5869-8fc9-ffeac11f7d12 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='sampling_volume_model',
        node_path='body/4',
        control_kind='assign',
        expected_sha256='bca03e4a0cd78d09c1baffe323e5d792455cc622cdf7aaf31fa94c4cecb9b9f5',
    )
    # [VERIFY assign] 只读来源校验 sampling_volume_model@body/5；本视图中静态 disabled。
    # unilab:node_uuid=7a9ea8a1-891e-5c43-bc23-399f72e5c5c3 disabled=true
    projected_control_0007 = material.review_control_node_v1(
        operation_name='sampling_volume_model',
        node_path='body/5',
        control_kind='assign',
        expected_sha256='1362d3f22d936698d6cf6c4ba5fa0012f06a194b61298ec6b4b36af838bfe652',
    )
    # [VERIFY comment] 只读来源校验 sampling_volume_model@body/6；本视图中静态 disabled。
    # unilab:node_uuid=1462f41f-cf4f-5c82-a821-6143a32f5b36 disabled=true
    projected_control_0008 = material.review_control_node_v1(
        operation_name='sampling_volume_model',
        node_path='body/6',
        control_kind='comment',
        expected_sha256='7ce7d03eea47324625a7b6448bd6761a9a0c355dd3c6ba610d5e6efa078c9dfa',
    )
    # [CONTROL if] 来源 sampling_volume_model@body/7；原节点 {"cond":{"binop":"<=","left":{"var":"over_aspirate_ml"},"right":{"lit":1.125}},"elifs":[{"body":[{"error":"SAMPLING_VOLUME_CHAIN","message":{"lit":"点样活塞终点 N=针流路死体积+气隔断/2 越界 [0,5] mL, 请检查气隔断旋钮"},"op":"raise"}],"cond":{"binop":"or","left":{"binop":"<","left":{"var":"band_end_ml"},"right":{"lit":0.0}},"right":{"binop":">",...
    # unilab:node_uuid=cb0aad6e-9cf1-531d-8d2c-28f8443cff49
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 sampling_volume_model@body/7；本视图中静态 disabled。
        # unilab:node_uuid=ed1048ba-78f1-5da6-8984-818f6ac15509 disabled=true
        projected_control_0009 = material.review_control_node_v1(
            operation_name='sampling_volume_model',
            node_path='body/7',
            control_kind='if',
            expected_sha256='c8d3e759fcba73955828b695bb3cb94fd1d3de350d794ed7b145435b706fff99',
        )
        # unilab:node_uuid=9987efa9-9e34-5747-b586-09df82b9c36f
        with group(name='THEN（互斥分支）'):
            # [VERIFY raise] 只读来源校验 sampling_volume_model@body/7/then/0；本视图中静态 disabled。
            # unilab:node_uuid=1945cbdf-69d1-5b40-94a6-59a6cd704ed3 disabled=true
            projected_control_0010 = material.review_control_node_v1(
                operation_name='sampling_volume_model',
                node_path='body/7/then/0',
                control_kind='raise',
                expected_sha256='9d4f62990864ccf1a94b8ed38ffd322304127c443ecc96afc63b6b6c3867781c',
            )
        # unilab:node_uuid=39de94f1-88e7-5631-807b-5845f4e6ae61
        with group(name='ELIF 1（互斥分支）'):
            # [VERIFY raise] 只读来源校验 sampling_volume_model@body/7/elifs/0/body/0；本视图中静态 disabled。
            # unilab:node_uuid=c74d2c4b-67a0-514e-8f49-b66d31bd1732 disabled=true
            projected_control_0011 = material.review_control_node_v1(
                operation_name='sampling_volume_model',
                node_path='body/7/elifs/0/body/0',
                control_kind='raise',
                expected_sha256='fc021fd63950ae3570c03819d1905ba8db011cc929657bc3aec29891b02ceb81',
            )
        # unilab:node_uuid=95815418-dc27-5b58-9795-074b3178d82c
        with group(name='ELIF 2（互斥分支）'):
            # [VERIFY raise] 只读来源校验 sampling_volume_model@body/7/elifs/1/body/0；本视图中静态 disabled。
            # unilab:node_uuid=a2f04bb4-ab57-535b-a729-625405d95544 disabled=true
            projected_control_0012 = material.review_control_node_v1(
                operation_name='sampling_volume_model',
                node_path='body/7/elifs/1/body/0',
                control_kind='raise',
                expected_sha256='f7f2c0dd180a75bfbc32cbf71addbfc0f62d712ad59fddc484d5c227b879a0bd',
            )
        # unilab:node_uuid=08719450-894f-5b55-a71e-ad97bf57b5c6
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 sampling_volume_model@body/7；本视图中静态 disabled。
            # unilab:node_uuid=43ba9574-30ac-5690-91ac-c1f683739bfc disabled=true
            projected_control_0013 = material.review_control_node_v1(
                operation_name='sampling_volume_model',
                node_path='body/7',
                control_kind='if',
                expected_sha256='c8d3e759fcba73955828b695bb3cb94fd1d3de350d794ed7b145435b706fff99',
            )
