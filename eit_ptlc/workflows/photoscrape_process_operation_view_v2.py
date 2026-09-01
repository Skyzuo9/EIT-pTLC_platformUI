from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape


material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')


@workflow(
    workflow_uuid='18c81f71-1175-5365-b6d2-6741787936b4',
    displayname='拍照刮板-执行 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def photoscrape_process_operation_view_v2() -> None:
    # [OPERATION photoscrape_process] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=a0f71b40-b311-5906-9e95-f3532f5ff9ef disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='photoscrape_process',
        inputs_json='{"band_id":"band_01","before_path":"","fixed_band_id":"fixed_01","fixed_summary_path":"","mode":"manual","reconcile_photo":true,"sample_id":"","save_dir":""}',
        expected_sha256='a0b80f10881c8414b25740b3c4c3a4dc1fabd127534f33b506bbee84c194ef56',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/0；本视图中静态 disabled。
    # unilab:node_uuid=89066764-0b66-57c4-aa7a-f6425f59251d disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='99ac6eee333fccef11675b8640c54b9da070f689d2b201fc858c16cc0eadb56f',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/1；本视图中静态 disabled。
    # unilab:node_uuid=c294d0b6-8d6b-5237-898d-ce221ce64d0f disabled=true
    projected_control_0003 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/1',
        control_kind='comment',
        expected_sha256='9d57bc03eb386851911485fe3e343ee6c3edc6e6d02bb542fe8bdd0f10c8c095',
    )
    # [ACTION photoscrape.press_cylinder] 来源 photoscrape_process@body/2；原节点 {"action":"photoscrape.press_cylinder","args":{"pressed":{"lit":true}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=f9c63c12-b16c-5d0f-bc1d-8f0e2270dd7f disabled=true
    projected_action_0004 = photoscrape.press_cylinder(
        pressed=True,
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/3；本视图中静态 disabled。
    # unilab:node_uuid=b5f96be5-c2d1-51f7-8d81-c7d32fb2e3c5 disabled=true
    projected_control_0005 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/3',
        control_kind='comment',
        expected_sha256='4f80e938256768bc26478b28e90fe37e580a1e12d40d5b4ad2a11aead4b9528c',
    )
    # [ACTION photoscrape.cam_photopos] 来源 photoscrape_process@body/4；原节点 {"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=133a81ae-da43-57f6-8c00-f400d28d097b disabled=true
    projected_action_0006 = photoscrape.cam_photopos(
        ref_8y='photo_8y',
    )
    # [ACTION photoscrape.capture] 来源 photoscrape_process@body/5；原节点 {"action":"photoscrape.capture","args":{"filename":{"lit":"after.jpg"},"profile":{"lit":"photoscrape"},"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"assign":{"var":"shot"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=7620f728-7750-5e24-a6a9-c20029bd45ff disabled=true
    projected_action_0007 = photoscrape.capture(
        sample_id='review-only',
        save_dir='review-only',
    )
    # [ACTION photoscrape.cam_photohome] 来源 photoscrape_process@body/6；原节点 {"action":"photoscrape.cam_photohome","mode":"RUN","op":"call"}
    # unilab:node_uuid=6806c31b-2df6-533f-bf5b-222cc68d8b50 disabled=true
    projected_action_0008 = photoscrape.cam_photohome()
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/7；本视图中静态 disabled。
    # unilab:node_uuid=80edf677-7848-50d3-819d-f744b096d32e disabled=true
    projected_control_0009 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/7',
        control_kind='comment',
        expected_sha256='8707764dd7d600d3b648cb6aab5bdfc6a29ae7e6f91863a5811fe953f67652c3',
    )
    # [ACTION photoscrape.analyze] 来源 photoscrape_process@body/8；原节点 {"action":"photoscrape.analyze","args":{"after_path":{"field":{"var":"shot"},"name":"image_path"},"before_path":{"var":"before_path"},"sample_id":{"var":"sample_id"}},"assign":{"var":"vis"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=1930018e-b2ab-51a3-af57-2035da74e773 disabled=true
    projected_action_0010 = photoscrape.analyze(
        sample_id='review-only',
        before_path='review-only',
        after_path='review-only',
    )
    # [VERIFY assign] 只读来源校验 photoscrape_process@body/9；本视图中静态 disabled。
    # unilab:node_uuid=77792081-af47-59eb-8490-1d20e000f2e1 disabled=true
    projected_control_0011 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/9',
        control_kind='assign',
        expected_sha256='68d9890b6892bb1b7ffcf516b88e06e3150fc97c73995bcf109e4a185818bc5b',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/10；本视图中静态 disabled。
    # unilab:node_uuid=ca675b5f-5015-5b50-9eb5-b918010f112f disabled=true
    projected_control_0012 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/10',
        control_kind='comment',
        expected_sha256='2dba8952b2e177db6ac54e23cc31603a86e379a6d26ade55f7a7d8150c834191',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/11；本视图中静态 disabled。
    # unilab:node_uuid=8105629c-1646-56cf-badd-1115e43a4fa9 disabled=true
    projected_control_0013 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/11',
        control_kind='comment',
        expected_sha256='ffe3404d40c5e1cea486d093f9e356c4ffa51d99e04d5d24901d78642e53f0c3',
    )
    # [CONTROL if] 来源 photoscrape_process@body/12；原节点 {"cond":{"binop":"and","left":{"field":{"var":"vis"},"name":"ok"},"right":{"binop":"==","left":{"var":"fixed_summary_path"},"right":{"lit":""}}},"op":"if","then":[{"cond":{"binop":"==","left":{"var":"mode"},"right":{"lit":"manual"}},"op":"if","then":[{"fields":[{"label":"条带ID","var":"band_id"}],"image":{"field":{"var":"v...
    # unilab:node_uuid=30757f63-bc72-5a2f-8619-38987cf8e893
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 photoscrape_process@body/12；本视图中静态 disabled。
        # unilab:node_uuid=e2bcea78-ce1f-5012-b733-7d2293a12423 disabled=true
        projected_control_0014 = material.review_control_node_v1(
            operation_name='photoscrape_process',
            node_path='body/12',
            control_kind='if',
            expected_sha256='bef7b8f0c41ad97b1b4ed49231ff5fe7791a0b8e44c62720217a5b9090dab9a8',
        )
        # unilab:node_uuid=cc68a2f9-6ad2-52db-86a5-e6a13b350150
        with group(name='THEN（互斥分支）'):
            # [CONTROL if] 来源 photoscrape_process@body/12/then/0；原节点 {"cond":{"binop":"==","left":{"var":"mode"},"right":{"lit":"manual"}},"op":"if","then":[{"fields":[{"label":"条带ID","var":"band_id"}],"image":{"field":{"var":"vis"},"name":"annotated_url"},"kind":"input","op":"human","prompt":{"binop":"+","left":{"binop":"+","left":{"lit":"识别到的条带: "},"right":{"args":[{"field":{"var...
            # unilab:node_uuid=bece8f5e-345d-5963-9976-9a8ec2f32dac
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 photoscrape_process@body/12/then/0；本视图中静态 disabled。
                # unilab:node_uuid=c51e5387-1b48-5306-a348-bee71a07e9fa disabled=true
                projected_control_0015 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/12/then/0',
                    control_kind='if',
                    expected_sha256='b9d42452c1325e911dc37c5bfa2133a491b50ff21bb3dd894680790e4ac57d2d',
                )
                # unilab:node_uuid=2d0e93f0-cce2-50bb-9120-1a52c85c0803
                with group(name='THEN（互斥分支）'):
                    # [VERIFY human] 只读来源校验 photoscrape_process@body/12/then/0/then/0；本视图中静态 disabled。
                    # unilab:node_uuid=a64da853-1d58-5aa9-929a-c3bb7bcd2986 disabled=true
                    projected_control_0016 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/12/then/0/then/0',
                        control_kind='human',
                        expected_sha256='fde0e464ca9e57653c3925f80a74ad0bf7737930e6205cee6b77365e1455ad87',
                    )
                # unilab:node_uuid=b7684954-7f63-5d5b-966f-aea6c6e328fc
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/12/then/0；本视图中静态 disabled。
                    # unilab:node_uuid=24e62f3e-0008-5523-ac52-66a8057d1a39 disabled=true
                    projected_control_0017 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/12/then/0',
                        control_kind='if',
                        expected_sha256='b9d42452c1325e911dc37c5bfa2133a491b50ff21bb3dd894680790e4ac57d2d',
                    )
            # [CONTROL try] 来源 photoscrape_process@body/12/then/1；原节点 {"body":[{"op":"comment","text":"据视觉 summary + 选带算 CNC 路径; 成功即候选就绪"},{"action":"photoscrape.cnc_path","args":{"band_id":{"var":"band_id"},"summary_path":{"field":{"var":"vis"},"name":"summary_path"}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"},{"op":"assign","target":{"var":"cand_summary_path"},"value":{"fiel...
            # unilab:node_uuid=d1406a8e-1d6a-56f6-b28d-c4b9522e0d53
            with group(name='TRY / CATCH（PlatformUI 异常语义）'):
                # [VERIFY try] 只读来源校验 photoscrape_process@body/12/then/1；本视图中静态 disabled。
                # unilab:node_uuid=c7e9f60b-11e7-5c9e-a8b3-f859db6d2a67 disabled=true
                projected_control_0018 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/12/then/1',
                    control_kind='try',
                    expected_sha256='25a787f20d403ca70ec69d71745f479d615ea544c674e1fd4986646e9db253ee',
                )
                # unilab:node_uuid=19fc9b07-4391-56a5-9ef6-d93ad5a74122
                with group(name='TRY'):
                    # [VERIFY comment] 只读来源校验 photoscrape_process@body/12/then/1/body/0；本视图中静态 disabled。
                    # unilab:node_uuid=9c7ba113-9b9f-5437-a5c0-2b73e45c8bda disabled=true
                    projected_control_0019 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/12/then/1/body/0',
                        control_kind='comment',
                        expected_sha256='ed36a7fc47e8b48fb1a8cc47fe5e757ed1f4c1d15762f34a06a1742da9ab7c32',
                    )
                    # [ACTION photoscrape.cnc_path] 来源 photoscrape_process@body/12/then/1/body/1；原节点 {"action":"photoscrape.cnc_path","args":{"band_id":{"var":"band_id"},"summary_path":{"field":{"var":"vis"},"name":"summary_path"}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=23116f8c-861a-5fba-a6a5-4768227de0f9 disabled=true
                    projected_action_0020 = photoscrape.cnc_path(
                        summary_path='review-only',
                        band_id='review-only',
                    )
                    # [VERIFY assign] 只读来源校验 photoscrape_process@body/12/then/1/body/2；本视图中静态 disabled。
                    # unilab:node_uuid=e4756efb-5778-5530-8474-1e1f448b94d2 disabled=true
                    projected_control_0021 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/12/then/1/body/2',
                        control_kind='assign',
                        expected_sha256='deea15449539735a5483a2f8561f1cb4600410ca2fcb51b85d5b0eaa14a55c95',
                    )
                    # [VERIFY assign] 只读来源校验 photoscrape_process@body/12/then/1/body/3；本视图中静态 disabled。
                    # unilab:node_uuid=dbc21dcb-fc15-5cee-bc5d-848214fb1947 disabled=true
                    projected_control_0022 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/12/then/1/body/3',
                        control_kind='assign',
                        expected_sha256='6c51fb6a2812a0bd9597fea6208bc8dd02cbb0ab14706abacc058a3e287fd591',
                    )
                    # [VERIFY assign] 只读来源校验 photoscrape_process@body/12/then/1/body/4；本视图中静态 disabled。
                    # unilab:node_uuid=4ed63633-4b33-582f-ad13-c351373eb080 disabled=true
                    projected_control_0023 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/12/then/1/body/4',
                        control_kind='assign',
                        expected_sha256='0de53db5d7fe626f69a037677f5427ecd0ee5844a4cf90ab14acb3c6903e87ec',
                    )
                    # [VERIFY assign] 只读来源校验 photoscrape_process@body/12/then/1/body/5；本视图中静态 disabled。
                    # unilab:node_uuid=4cbf6b01-cd3a-5df4-89a6-f825fc981bc5 disabled=true
                    projected_control_0024 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/12/then/1/body/5',
                        control_kind='assign',
                        expected_sha256='d8f3a9179a29d24513ab396906aeefce9b0926b8d3e726cf13f1fecdb6562400',
                    )
                # unilab:node_uuid=d10b43d5-203c-5daa-9335-74a197bbf599
                with group(name='CATCH 1'):
                    # [VERIFY comment] 只读来源校验 photoscrape_process@body/12/then/1/catch/0/body/0；本视图中静态 disabled。
                    # unilab:node_uuid=48a31169-0e7c-51ff-b055-83a869265870 disabled=true
                    projected_control_0025 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/12/then/1/catch/0/body/0',
                        control_kind='comment',
                        expected_sha256='2e025c35e27322bc04858a6a4c05c1cee6359092e581861746ac46f9c916e796',
                    )
        # unilab:node_uuid=ba3356fb-3e84-52da-a283-330184dd72e4
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/12；本视图中静态 disabled。
            # unilab:node_uuid=2e147d19-a167-56e5-969b-5958be1ed30c disabled=true
            projected_control_0026 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/12',
                control_kind='if',
                expected_sha256='bef7b8f0c41ad97b1b4ed49231ff5fe7791a0b8e44c62720217a5b9090dab9a8',
            )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/13；本视图中静态 disabled。
    # unilab:node_uuid=06edd77e-c9a4-5557-989b-8ebc573ec63d disabled=true
    projected_control_0027 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/13',
        control_kind='comment',
        expected_sha256='62d72928b49b6258e279c0c92677b4f104813443418b77ce4165d26006d6a3eb',
    )
    # [CONTROL if] 来源 photoscrape_process@body/14；原节点 {"cond":{"binop":"!=","left":{"var":"fixed_summary_path"},"right":{"lit":""}},"op":"if","then":[{"action":"photoscrape.cnc_path","args":{"band_id":{"var":"fixed_band_id"},"summary_path":{"var":"fixed_summary_path"}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"},{"op":"assign","target":{"var":"cand_summary_path"},"valu...
    # unilab:node_uuid=4820427d-0644-5ea2-bf84-507d1ebe0fb8
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 photoscrape_process@body/14；本视图中静态 disabled。
        # unilab:node_uuid=3a5cad88-0ebf-5ae6-9ab5-d6d483df4632 disabled=true
        projected_control_0028 = material.review_control_node_v1(
            operation_name='photoscrape_process',
            node_path='body/14',
            control_kind='if',
            expected_sha256='1f8f297e4a9be82a4e9958e0734fc991b675c9e2b90ee8e01e4083fe08240dd1',
        )
        # unilab:node_uuid=0d625fc8-17d1-57a4-bf57-2c74b9629c91
        with group(name='THEN（互斥分支）'):
            # [ACTION photoscrape.cnc_path] 来源 photoscrape_process@body/14/then/0；原节点 {"action":"photoscrape.cnc_path","args":{"band_id":{"var":"fixed_band_id"},"summary_path":{"var":"fixed_summary_path"}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=cd862978-52f6-5e9c-ae2c-b9a887b9bd21 disabled=true
            projected_action_0029 = photoscrape.cnc_path(
                summary_path='review-only',
                band_id='review-only',
            )
            # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/1；本视图中静态 disabled。
            # unilab:node_uuid=2f8188c8-087e-525c-9cdf-1ce2d133fe92 disabled=true
            projected_control_0030 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/14/then/1',
                control_kind='assign',
                expected_sha256='93aeffa6c5c7cfbe2efbaffafeb5ca2373f9917164efa5bd7b277192a19c26be',
            )
            # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/2；本视图中静态 disabled。
            # unilab:node_uuid=f1aed3f2-b73f-5178-9f55-a0a368f36869 disabled=true
            projected_control_0031 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/14/then/2',
                control_kind='assign',
                expected_sha256='0fc9c6ac422b29e28ece3dff7d97d9a27e348d7df5c8c250ac7fc915b4df6446',
            )
            # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/3；本视图中静态 disabled。
            # unilab:node_uuid=e39c6b5a-662a-5fd0-995d-67191d57ce9d disabled=true
            projected_control_0032 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/14/then/3',
                control_kind='assign',
                expected_sha256='0de53db5d7fe626f69a037677f5427ecd0ee5844a4cf90ab14acb3c6903e87ec',
            )
            # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/4；本视图中静态 disabled。
            # unilab:node_uuid=b301890a-1154-5a00-a5eb-7993d80042af disabled=true
            projected_control_0033 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/14/then/4',
                control_kind='assign',
                expected_sha256='d8f3a9179a29d24513ab396906aeefce9b0926b8d3e726cf13f1fecdb6562400',
            )
            # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/5；本视图中静态 disabled。
            # unilab:node_uuid=d5b1c5c9-18d9-5387-9d66-4395031830f0 disabled=true
            projected_control_0034 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/14/then/5',
                control_kind='assign',
                expected_sha256='4c0312b294cf799e4298d9ac5f86db983ce646321e167a34ce095caae54823ca',
            )
        # unilab:node_uuid=6cb3d964-0883-5a65-a6be-7f8cd308bb11
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/14；本视图中静态 disabled。
            # unilab:node_uuid=31d2bcf5-7c20-5a0c-8ce7-e0409a4c65eb disabled=true
            projected_control_0035 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/14',
                control_kind='if',
                expected_sha256='1f8f297e4a9be82a4e9958e0734fc991b675c9e2b90ee8e01e4083fe08240dd1',
            )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/15；本视图中静态 disabled。
    # unilab:node_uuid=3a5e92ea-f84c-5f53-a5f0-e06f85af3916 disabled=true
    projected_control_0036 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/15',
        control_kind='comment',
        expected_sha256='88835eccbc2c537802d2bb3c5676965019a23bbc61fe776e9227b8f723ab6dcf',
    )
    # [CONTROL if] 来源 photoscrape_process@body/16；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"mode"},"right":{"lit":"auto"}},"right":{"var":"cand_valid"}},"op":"if","then":[{"op":"assign","target":{"var":"dispatched"},"value":{"lit":true}}]}
    # unilab:node_uuid=9d8608c0-f413-54ad-9c63-568c432d2ad4
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 photoscrape_process@body/16；本视图中静态 disabled。
        # unilab:node_uuid=e48932c3-6b1b-5546-88c2-e619cfc90569 disabled=true
        projected_control_0037 = material.review_control_node_v1(
            operation_name='photoscrape_process',
            node_path='body/16',
            control_kind='if',
            expected_sha256='9a7cd55d2e2df352b347fc47aa7d90bd876604f336a80edfca2244dcce18a292',
        )
        # unilab:node_uuid=b886cb2a-60b0-5773-92dc-cc9bac5f52a4
        with group(name='THEN（互斥分支）'):
            # [VERIFY assign] 只读来源校验 photoscrape_process@body/16/then/0；本视图中静态 disabled。
            # unilab:node_uuid=2ea69d4e-dc0c-5898-882a-f4ec645f34c7 disabled=true
            projected_control_0038 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/16/then/0',
                control_kind='assign',
                expected_sha256='4c0312b294cf799e4298d9ac5f86db983ce646321e167a34ce095caae54823ca',
            )
        # unilab:node_uuid=3a672f48-3acc-5f54-b996-e596b0ecb6bc
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/16；本视图中静态 disabled。
            # unilab:node_uuid=09fe7027-60fb-5401-bcc4-7fdf28bbe7d1 disabled=true
            projected_control_0039 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/16',
                control_kind='if',
                expected_sha256='9a7cd55d2e2df352b347fc47aa7d90bd876604f336a80edfca2244dcce18a292',
            )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/17；本视图中静态 disabled。
    # unilab:node_uuid=30bd473b-d0bf-5b25-8c61-ff9567b89e07 disabled=true
    projected_control_0040 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/17',
        control_kind='comment',
        expected_sha256='26b67b5edb78b29314a26fb5736037763d8947f04c641d71177906547be5a5e4',
    )
    # [LOOP while · BODY NOT EXPANDED] 只读来源校验 photoscrape_process@body/18；本视图中静态 disabled。
    # unilab:node_uuid=f75966a9-82ec-542f-b2be-9db49d0605d9 disabled=true
    projected_control_0041 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/18',
        control_kind='while',
        expected_sha256='97cb3a2650fc0d7eff3a3a366ca51a2d026a592ed928ab155b2db2af81ce781e',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/19；本视图中静态 disabled。
    # unilab:node_uuid=1c0a3a5d-77c7-549d-aaf9-fda4588140ae disabled=true
    projected_control_0042 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/19',
        control_kind='comment',
        expected_sha256='c0b0060a7696639df3793848978f57cd511136ec0d94353bd7dd65031c672d87',
    )
    # [CONTROL if] 来源 photoscrape_process@body/20；原节点 {"cond":{"var":"skip_scrape"},"op":"if","then":[{"op":"comment","text":"无谱带/跳过刮板: cnc_path(placeholder=true) → pass_count=0 全 0 数组, scrape 一次不跑, 空跑收尾"},{"action":"photoscrape.cnc_path","args":{"band_id":{"lit":""},"placeholder":{"lit":true},"summary_path":{"lit":""}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"}]}
    # unilab:node_uuid=58c60a27-4b05-5948-8da1-0665c9e71979
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 photoscrape_process@body/20；本视图中静态 disabled。
        # unilab:node_uuid=70bed8f6-5e6f-541c-84ba-4840d5a80984 disabled=true
        projected_control_0043 = material.review_control_node_v1(
            operation_name='photoscrape_process',
            node_path='body/20',
            control_kind='if',
            expected_sha256='421742e29baadc4e257de5dddab830ab620c5becb50f1a176b6833889141db5b',
        )
        # unilab:node_uuid=1bda3450-9487-5e9f-a9c9-e249017eb968
        with group(name='THEN（互斥分支）'):
            # [VERIFY comment] 只读来源校验 photoscrape_process@body/20/then/0；本视图中静态 disabled。
            # unilab:node_uuid=7c826a1f-2b04-51e7-b43f-6bc2454708f5 disabled=true
            projected_control_0044 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/20/then/0',
                control_kind='comment',
                expected_sha256='8eb02bbf758937db75580fc46aa213c3c5b00b11eece4d9732631fdf40823806',
            )
            # [ACTION photoscrape.cnc_path] 来源 photoscrape_process@body/20/then/1；原节点 {"action":"photoscrape.cnc_path","args":{"band_id":{"lit":""},"placeholder":{"lit":true},"summary_path":{"lit":""}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=0ea77553-059d-5039-80d6-da5055075561 disabled=true
            projected_action_0045 = photoscrape.cnc_path(
                summary_path='',
                band_id='',
            )
        # unilab:node_uuid=48765d2c-b7ec-533b-bc63-df3545d14dce
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/20；本视图中静态 disabled。
            # unilab:node_uuid=9f8895c5-f238-50bc-820d-0b3af478c2a9 disabled=true
            projected_control_0046 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/20',
                control_kind='if',
                expected_sha256='421742e29baadc4e257de5dddab830ab620c5becb50f1a176b6833889141db5b',
            )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/21；本视图中静态 disabled。
    # unilab:node_uuid=280b9ac3-369b-5955-a151-e263e2c4a5e7 disabled=true
    projected_control_0047 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/21',
        control_kind='comment',
        expected_sha256='15cb99a88abe73ce5a8085c1c9fb75139e3000552e7a6ef6ad4c1ed90792ba8e',
    )
    # [ACTION photoscrape.write_cnc_path] 来源 photoscrape_process@body/22；原节点 {"action":"photoscrape.write_cnc_path","args":{"cx":{"field":{"var":"cnc"},"name":"g_cx"},"cy":{"field":{"var":"cnc"},"name":"g_cy"},"feed":{"field":{"var":"cnc"},"name":"g_scrape_feed"},"sx":{"field":{"var":"cnc"},"name":"g_sx"},"sy":{"field":{"var":"cnc"},"name":"g_sy"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=ee3951e5-0ec6-571f-b327-95617d453a96 disabled=true
    projected_action_0048 = photoscrape.write_cnc_path(
        sx=[0.0],
        sy=[0.0],
        cx=[0.0],
        cy=[0.0],
        feed=1,
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/23；本视图中静态 disabled。
    # unilab:node_uuid=cb5df81f-f881-5aa4-a7fb-561ff650f79c disabled=true
    projected_control_0049 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/23',
        control_kind='comment',
        expected_sha256='69b202a1602a12b76a73278cdd6a0aa5ca8952dc526169cc91b66c4c86d0c36b',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/24；本视图中静态 disabled。
    # unilab:node_uuid=ec2e7c3d-0a47-530d-a582-e194df796b62 disabled=true
    projected_control_0050 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/24',
        control_kind='comment',
        expected_sha256='a7227fda72c9978fb74ac93a2075e5668869a0bd5a261f7355b7ee61c7b01f6c',
    )
    # [LOOP for · BODY NOT EXPANDED] 只读来源校验 photoscrape_process@body/25；本视图中静态 disabled。
    # unilab:node_uuid=b4de2a91-9371-5058-b372-20486190bc2e disabled=true
    projected_control_0051 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/25',
        control_kind='for',
        expected_sha256='f81813ba4a0ed43e467ac7ab08a075b8f945fdc64baf68533f30f5c9abe52dc0',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/26；本视图中静态 disabled。
    # unilab:node_uuid=cb6dfc4c-1b86-5e34-883b-a2040f356c63 disabled=true
    projected_control_0052 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/26',
        control_kind='comment',
        expected_sha256='82d246ab29f67dcd0eba5ebf004698052f788be7dfab19bf028f50350d06a0be',
    )
    # [CONTROL if] 来源 photoscrape_process@body/27；原节点 {"cond":{"binop":"and","left":{"var":"reconcile_photo"},"right":{"operand":{"var":"skip_scrape"},"unop":"not"}},"op":"if","then":[{"body":[{"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"},{"action":"photoscrape.capture","args":{"filename":{"lit":"scraped.jpg"},"profile":...
    # unilab:node_uuid=17047b28-8825-5df2-a776-71f1dcdc4138
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 photoscrape_process@body/27；本视图中静态 disabled。
        # unilab:node_uuid=b8bac284-95ce-57e6-ab19-f1cbc355a57d disabled=true
        projected_control_0053 = material.review_control_node_v1(
            operation_name='photoscrape_process',
            node_path='body/27',
            control_kind='if',
            expected_sha256='f5190107a512fbdaeeb5704b9a40446d7b133d1712c1c39bb03870b5f413cf11',
        )
        # unilab:node_uuid=9c457c09-7dd9-5681-a69c-5c66371dede7
        with group(name='THEN（互斥分支）'):
            # [CONTROL try] 来源 photoscrape_process@body/27/then/0；原节点 {"body":[{"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"},{"action":"photoscrape.capture","args":{"filename":{"lit":"scraped.jpg"},"profile":{"lit":"photoscrape"},"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"assign":{"var":"scraped_shot"},"mode"...
            # unilab:node_uuid=a6c9cbe0-b55d-5212-9837-4f3b5762f997
            with group(name='TRY / CATCH（PlatformUI 异常语义）'):
                # [VERIFY try] 只读来源校验 photoscrape_process@body/27/then/0；本视图中静态 disabled。
                # unilab:node_uuid=37d549e4-07f9-5b01-819f-d68e780784b7 disabled=true
                projected_control_0054 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/27/then/0',
                    control_kind='try',
                    expected_sha256='c065fc6e0ee4f56a11581bb600251502a3cb64612c732abc11af1b4595c85a02',
                )
                # unilab:node_uuid=29f30cfb-449c-5fbc-9f84-292266de986b
                with group(name='TRY'):
                    # [ACTION photoscrape.cam_photopos] 来源 photoscrape_process@body/27/then/0/body/0；原节点 {"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=4ad2bf5c-7be5-510d-9b76-cf70600cd06f disabled=true
                    projected_action_0055 = photoscrape.cam_photopos(
                        ref_8y='photo_8y',
                    )
                    # [ACTION photoscrape.capture] 来源 photoscrape_process@body/27/then/0/body/1；原节点 {"action":"photoscrape.capture","args":{"filename":{"lit":"scraped.jpg"},"profile":{"lit":"photoscrape"},"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"assign":{"var":"scraped_shot"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=8daf648c-82e4-56e0-b8a3-5f004ee5da37 disabled=true
                    projected_action_0056 = photoscrape.capture(
                        sample_id='review-only',
                        save_dir='review-only',
                    )
                    # [ACTION photoscrape.cam_photohome] 来源 photoscrape_process@body/27/then/0/body/2；原节点 {"action":"photoscrape.cam_photohome","mode":"RUN","op":"call"}
                    # unilab:node_uuid=415900d2-6c44-5962-a6c5-5848de14df50 disabled=true
                    projected_action_0057 = photoscrape.cam_photohome()
                    # [ACTION photoscrape.scraped_overlay] 来源 photoscrape_process@body/27/then/0/body/3；原节点 {"action":"photoscrape.scraped_overlay","args":{"scraped_path":{"field":{"var":"scraped_shot"},"name":"image_path"},"summary_path":{"var":"cand_summary_path"}},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=e84ba48c-149d-5eff-b8b9-3e0f45596563 disabled=true
                    projected_action_0058 = photoscrape.scraped_overlay(
                        summary_path='review-only',
                        scraped_path='review-only',
                    )
                # unilab:node_uuid=80d350d7-3f3a-5575-b294-45477ae77058
                with group(name='CATCH 1'):
                    # [VERIFY comment] 只读来源校验 photoscrape_process@body/27/then/0/catch/0/body/0；本视图中静态 disabled。
                    # unilab:node_uuid=4c81949a-ab8c-5b6d-8061-130b2090fad5 disabled=true
                    projected_control_0059 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/27/then/0/catch/0/body/0',
                        control_kind='comment',
                        expected_sha256='bb25ca942792e4bdebc34f20044adb5737fee5712502a336023d424c3d61cc31',
                    )
                    # [ACTION photoscrape.cam_photohome] 来源 photoscrape_process@body/27/then/0/catch/0/body/1；原节点 {"action":"photoscrape.cam_photohome","mode":"RUN","op":"call"}
                    # unilab:node_uuid=33db9929-16bd-5823-ba85-b5ad113474f9 disabled=true
                    projected_action_0060 = photoscrape.cam_photohome()
        # unilab:node_uuid=2f2e3142-0376-5b64-a5cf-ce901791a835
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/27；本视图中静态 disabled。
            # unilab:node_uuid=b956672e-f0f0-5670-9c3d-04e02fdd4f12 disabled=true
            projected_control_0061 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/27',
                control_kind='if',
                expected_sha256='f5190107a512fbdaeeb5704b9a40446d7b133d1712c1c39bb03870b5f413cf11',
            )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/28；本视图中静态 disabled。
    # unilab:node_uuid=c82d6e16-b235-5ef0-b1f3-8052b72ec95f disabled=true
    projected_control_0062 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/28',
        control_kind='comment',
        expected_sha256='94b3e7d18efab694e0706f3e89e91c28b565263185ba6162383650804306e95c',
    )
    # [ACTION photoscrape.scrape_finish] 来源 photoscrape_process@body/29；原节点 {"action":"photoscrape.scrape_finish","mode":"RUN","op":"call"}
    # unilab:node_uuid=ad6e3f04-1312-5848-b79c-e794cefc592a disabled=true
    projected_action_0063 = photoscrape.scrape_finish()
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/30；本视图中静态 disabled。
    # unilab:node_uuid=d03a6448-d1ba-5bc3-8fb6-cfa3dc10ad10 disabled=true
    projected_control_0064 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/30',
        control_kind='comment',
        expected_sha256='bd4436a9c740451b22aacc5d24e4be7b95568584b8b81569c6dcfb01ee9cc005',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/31；本视图中静态 disabled。
    # unilab:node_uuid=34788863-b47e-54d8-986b-dda9780b92fc disabled=true
    projected_control_0065 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/31',
        control_kind='comment',
        expected_sha256='9ac117f3b8b56b0bd37015e580ba7aa9a2e65961b1211a3413a528c251402ad6',
    )
    # [VERIFY comment] 只读来源校验 photoscrape_process@body/32；本视图中静态 disabled。
    # unilab:node_uuid=9b2f914b-321d-560e-8c0a-e0781962b4b7 disabled=true
    projected_control_0066 = material.review_control_node_v1(
        operation_name='photoscrape_process',
        node_path='body/32',
        control_kind='comment',
        expected_sha256='7d7516b58d541f7a7c4703344481ee18eaa208960a0cd5d570947b5a4f0f7c35',
    )
    # [ACTION photoscrape.wait_rot] 来源 photoscrape_process@body/33；原节点 {"action":"photoscrape.wait_rot","args":{"target":{"lit":"extend"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=98c832aa-d4e4-50b2-9518-0a8cd1ceb23c disabled=true
    projected_action_0067 = photoscrape.wait_rot()
