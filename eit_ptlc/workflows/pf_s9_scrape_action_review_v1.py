from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape


class PlatformOperationReviewV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    before_path: str
    collector_hole: int
    bottle_hole: int

material: MaterialProxy = device('material')
photoscrape: PLCPhotoScrape = device('plc_photoscrape')


@workflow(
    workflow_uuid='6660af5f-106f-50cc-9955-f8c4642faed9',
    displayname='7 拍照刮取 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s9_scrape_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s9_scrape] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=041dfc45-3046-5106-bc2f-51e11a6ef470
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s9_scrape@body/0；原节点 {"op":"comment","text":"拍照刮取: 板在刮板台上拍照/分析/刮取 (含手绘/重识别人工门); 仅占拍照刮板工位、不占机器人"}
        # unilab:node_uuid=3c3b8096-7381-5a52-8002-1873b28c65f2
        with group(name='说明 · 拍照刮取: 板在刮板台上拍照/分析/刮取 (含手绘/重识别人工门); 仅占拍照刮板工位、不占机器人'):
            # [VERIFY comment] 只读来源校验 pf_s9_scrape@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=9701d1a2-5199-53b7-b9d9-f4f5d71b79cf disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s9_scrape',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='cec1b0d663b5989a1181d97e6c653492b7d3956160c3772d95c042688b788348',
            )
        # [SUBWORKFLOW photoscrape_process] 由 pf_s9_scrape@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=5cfbd470-9ab5-5b43-bc26-92e09546c60c
        with group(name='↳ photoscrape_process'):
            # [CONTROL comment] 来源 photoscrape_process@body/0；原节点 {"op":"comment","text":"【执行】接粉收集器已由 transfer_collector_staging_a_to_scrape 放入并定位; 板已由 photoscrape_place 放入定位"}
            # unilab:node_uuid=94fa54fe-5010-5aeb-9a86-e79c71915e27
            with group(name='说明 · 【执行】接粉收集器已由 transfer_collector_staging_a_to_scrape 放入并定位'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=fa7d480e-35a5-5da3-8398-176ed86d2499 disabled=true
                projected_control_0002 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='99ac6eee333fccef11675b8640c54b9da070f689d2b201fc858c16cc0eadb56f',
                )
            # [CONTROL comment] 来源 photoscrape_process@body/1；原节点 {"op":"comment","text":"【执行】下压气缸压下 (press_cylinder true 的唯一生产调用点; 此处夹紧开拍)"}
            # unilab:node_uuid=d3173abc-389f-5c2d-8877-4e546f952010
            with group(name='说明 · 【执行】下压气缸压下 (press_cylinder true 的唯一生产调用点; 此处夹紧开拍)'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/1；节点在本工作流中静态 disabled。
                # unilab:node_uuid=d9ce2d08-9f84-565d-a9b9-3d117c003073 disabled=true
                projected_control_0003 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/1',
                    control_kind='comment',
                    expected_sha256='9d57bc03eb386851911485fe3e343ee6c3edc6e6d02bb542fe8bdd0f10c8c095',
                )
            # [ACTION photoscrape.press_cylinder] 来源 photoscrape_process@body/2；原节点 {"action":"photoscrape.press_cylinder","args":{"pressed":{"lit":true}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=2c9cb37b-1236-5e8d-8ee1-739fa6c5329e disabled=true
            projected_action_0004 = photoscrape.press_cylinder(
                pressed=True,
            )
            # [CONTROL comment] 来源 photoscrape_process@body/3；原节点 {"op":"comment","text":"(1) 上位机触发相机拍照 (只拍一次; 重拍=run-control 复位重执行本 action)"}
            # unilab:node_uuid=ffd9533c-0d9c-5888-94d1-c09c90247059
            with group(name='说明 · (1) 上位机触发相机拍照 (只拍一次; 重拍=run-control 复位重执行本 action)'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/3；节点在本工作流中静态 disabled。
                # unilab:node_uuid=89934964-db35-5ee9-a867-fd31f0be5886 disabled=true
                projected_control_0005 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/3',
                    control_kind='comment',
                    expected_sha256='4f80e938256768bc26478b28e90fe37e580a1e12d40d5b4ad2a11aead4b9528c',
                )
            # [ACTION photoscrape.cam_photopos] 来源 photoscrape_process@body/4；原节点 {"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=f6ad77f3-a1d2-56c2-bd67-d3bcc28bb366 disabled=true
            projected_action_0006 = photoscrape.cam_photopos(
                ref_8y='photo_8y',
            )
            # [ACTION photoscrape.capture] 来源 photoscrape_process@body/5；原节点 {"action":"photoscrape.capture","args":{"filename":{"lit":"after.jpg"},"profile":{"lit":"photoscrape"},"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"assign":{"var":"shot"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=5bd43680-aa47-577e-a2e0-628ef45fafa3 disabled=true
            projected_action_0007 = photoscrape.capture(
                sample_id='review-only',
                save_dir='review-only',
            )
            # [ACTION photoscrape.cam_photohome] 来源 photoscrape_process@body/6；原节点 {"action":"photoscrape.cam_photohome","mode":"RUN","op":"call"}
            # unilab:node_uuid=50ecd318-f4b5-513a-a51f-c504f07fbdbd disabled=true
            projected_action_0008 = photoscrape.cam_photohome()
            # [CONTROL comment] 来源 photoscrape_process@body/7；原节点 {"op":"comment","text":"(2) 视觉分析 before+after → 结构化 vis{ok/reason/summary_path/band_ids/annotated_url}(可恢复失败不抛)"}
            # unilab:node_uuid=18a15ddb-439d-580e-a236-7042147d23ae
            with group(name='说明 · (2) 视觉分析 before+after → 结构化 vis{ok/reason/summary_path/b'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/7；节点在本工作流中静态 disabled。
                # unilab:node_uuid=efea3e00-6f87-54ec-9156-1fb71e1883d0 disabled=true
                projected_control_0009 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/7',
                    control_kind='comment',
                    expected_sha256='8707764dd7d600d3b648cb6aab5bdfc6a29ae7e6f91863a5811fe953f67652c3',
                )
            # [ACTION photoscrape.analyze] 来源 photoscrape_process@body/8；原节点 {"action":"photoscrape.analyze","args":{"after_path":{"field":{"var":"shot"},"name":"image_path"},"before_path":{"var":"before_path"},"sample_id":{"var":"sample_id"}},"assign":{"var":"vis"},"mode":"RUN","op":"call"}
            # unilab:node_uuid=c99a7f22-492a-5030-8eb0-6e8760de2aff disabled=true
            projected_action_0010 = photoscrape.analyze(
                sample_id='review-only',
                before_path='review-only',
                after_path='review-only',
            )
            # [CONTROL assign] 来源 photoscrape_process@body/9；原节点 {"op":"assign","target":{"var":"cand_annotated_url"},"value":{"field":{"var":"vis"},"name":"annotated_url"}}
            # unilab:node_uuid=f60a182a-8e26-580e-9f9c-048e2d5674c0
            with group(name='变量赋值'):
                # [VERIFY assign] 只读来源校验 photoscrape_process@body/9；节点在本工作流中静态 disabled。
                # unilab:node_uuid=1b792c95-8a41-522f-9d49-ac9bfb430dad disabled=true
                projected_control_0011 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/9',
                    control_kind='assign',
                    expected_sha256='68d9890b6892bb1b7ffcf516b88e06e3150fc97c73995bcf109e4a185818bc5b',
                )
            # [CONTROL comment] 来源 photoscrape_process@body/10；原节点 {"op":"comment","text":"(3) 初始候选(视觉): manual 人工选带; 视觉成功且算出路径 → cand_valid"}
            # unilab:node_uuid=e71e3acb-ae7c-5a90-a66a-026b1f9b01e0
            with group(name='说明 · (3) 初始候选(视觉): manual 人工选带; 视觉成功且算出路径 → cand_valid'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/10；节点在本工作流中静态 disabled。
                # unilab:node_uuid=7bb089f4-9d1d-59b7-8027-8d1a7a463aab disabled=true
                projected_control_0012 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/10',
                    control_kind='comment',
                    expected_sha256='2dba8952b2e177db6ac54e23cc31603a86e379a6d26ade55f7a7d8150c834191',
                )
            # [CONTROL comment] 来源 photoscrape_process@body/11；原节点 {"op":"comment","text":"固定路径实验(fixed_summary_path 非空)时整块跳过: 不选带、不算视觉候选(3b 会覆盖); analyze/拍照已在(2)照常, 前后照留档"}
            # unilab:node_uuid=5d9e8e6f-5f98-59b6-93be-1359182ccaf0
            with group(name='说明 · 固定路径实验(fixed_summary_path 非空)时整块跳过: 不选带、不算视觉候选(3b 会覆盖); '):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/11；节点在本工作流中静态 disabled。
                # unilab:node_uuid=0c7e9ecb-18c1-5f2d-b512-4cf34fe30f66 disabled=true
                projected_control_0013 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/11',
                    control_kind='comment',
                    expected_sha256='ffe3404d40c5e1cea486d093f9e356c4ffa51d99e04d5d24901d78642e53f0c3',
                )
            # [CONTROL if] 来源 photoscrape_process@body/12；原节点 {"cond":{"binop":"and","left":{"field":{"var":"vis"},"name":"ok"},"right":{"binop":"==","left":{"var":"fixed_summary_path"},"right":{"lit":""}}},"op":"if","then":[{"cond":{"binop":"==","left":{"var":"mode"},"right":{"lit":"manual"}},"op":"if","then":[{"fields":[{"label":"条带ID","var":"band_id"}],"image":{"field":{"var":"v...
            # unilab:node_uuid=3748188b-cb95-5ae3-937a-f9c89988bac6
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 photoscrape_process@body/12；节点在本工作流中静态 disabled。
                # unilab:node_uuid=a7b96ed8-bdfe-5620-8c5a-7a5cf4fbd575 disabled=true
                projected_control_0014 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/12',
                    control_kind='if',
                    expected_sha256='bef7b8f0c41ad97b1b4ed49231ff5fe7791a0b8e44c62720217a5b9090dab9a8',
                )
                # [BRANCH THEN（互斥分支）] photoscrape_process@body/12/then 的静态审阅分支。
                # unilab:node_uuid=4d619207-9416-5256-9712-b0d58e33722b
                with group(name='THEN（互斥分支）'):
                    # [CONTROL if] 来源 photoscrape_process@body/12/then/0；原节点 {"cond":{"binop":"==","left":{"var":"mode"},"right":{"lit":"manual"}},"op":"if","then":[{"fields":[{"label":"条带ID","var":"band_id"}],"image":{"field":{"var":"vis"},"name":"annotated_url"},"kind":"input","op":"human","prompt":{"binop":"+","left":{"binop":"+","left":{"lit":"识别到的条带: "},"right":{"args":[{"field":{"var...
                    # unilab:node_uuid=c3c3b976-eaa0-513c-9244-49d63fa13a27
                    with group(name='◇ IF 条件（PlatformUI 判定）'):
                        # [VERIFY if] 只读来源校验 photoscrape_process@body/12/then/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=c900b9e2-15d3-5c1c-9f0a-55db7d4f84ba disabled=true
                        projected_control_0015 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/12/then/0',
                            control_kind='if',
                            expected_sha256='b9d42452c1325e911dc37c5bfa2133a491b50ff21bb3dd894680790e4ac57d2d',
                        )
                        # [BRANCH THEN（互斥分支）] photoscrape_process@body/12/then/0/then 的静态审阅分支。
                        # unilab:node_uuid=951cec39-b522-58a3-9822-678493df9ca7
                        with group(name='THEN（互斥分支）'):
                            # [CONTROL human] 来源 photoscrape_process@body/12/then/0/then/0；原节点 {"fields":[{"label":"条带ID","var":"band_id"}],"image":{"field":{"var":"vis"},"name":"annotated_url"},"kind":"input","op":"human","prompt":{"binop":"+","left":{"binop":"+","left":{"lit":"识别到的条带: "},"right":{"args":[{"field":{"var":"vis"},"name":"band_ids"}],"call":"str"}},"right":{"lit":" — 对照标注图输入要刮取的 band_i...
                            # unilab:node_uuid=433ae600-fdbd-5fcb-b097-3ed764382869
                            with group(name='◆ HITL 人工门'):
                                # [VERIFY human] 只读来源校验 photoscrape_process@body/12/then/0/then/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=aedb6d7a-5958-5d48-b771-f35b73e40a6a disabled=true
                                projected_control_0016 = material.review_control_node_v1(
                                    operation_name='photoscrape_process',
                                    node_path='body/12/then/0/then/0',
                                    control_kind='human',
                                    expected_sha256='fde0e464ca9e57653c3925f80a74ad0bf7737930e6205cee6b77365e1455ad87',
                                )
                        # [BRANCH ELSE（互斥分支）] photoscrape_process@body/12/then/0/else 的静态审阅分支。
                        # unilab:node_uuid=6da6de60-f7e8-5cd3-800b-e2648808187a
                        with group(name='ELSE（互斥分支）'):
                            # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/12/then/0；节点在本工作流中静态 disabled。
                            # unilab:node_uuid=a509fd1b-fd32-517b-8245-58684ee0909a disabled=true
                            projected_control_0017 = material.review_control_node_v1(
                                operation_name='photoscrape_process',
                                node_path='body/12/then/0',
                                control_kind='if',
                                expected_sha256='b9d42452c1325e911dc37c5bfa2133a491b50ff21bb3dd894680790e4ac57d2d',
                            )
                    # [CONTROL try] 来源 photoscrape_process@body/12/then/1；原节点 {"body":[{"op":"comment","text":"据视觉 summary + 选带算 CNC 路径; 成功即候选就绪"},{"action":"photoscrape.cnc_path","args":{"band_id":{"var":"band_id"},"summary_path":{"field":{"var":"vis"},"name":"summary_path"}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"},{"op":"assign","target":{"var":"cand_summary_path"},"value":{"fiel...
                    # unilab:node_uuid=d54a39cc-9111-5046-8102-c7e5a57372a7
                    with group(name='TRY / CATCH（PlatformUI 异常语义）'):
                        # [VERIFY try] 只读来源校验 photoscrape_process@body/12/then/1；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=24e00172-a197-5519-a226-48bd3c1af333 disabled=true
                        projected_control_0018 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/12/then/1',
                            control_kind='try',
                            expected_sha256='25a787f20d403ca70ec69d71745f479d615ea544c674e1fd4986646e9db253ee',
                        )
                        # [BRANCH TRY] photoscrape_process@body/12/then/1/body 的静态审阅分支。
                        # unilab:node_uuid=c5daf96c-c8a4-5bc2-8cf6-c833257ccb08
                        with group(name='TRY'):
                            # [CONTROL comment] 来源 photoscrape_process@body/12/then/1/body/0；原节点 {"op":"comment","text":"据视觉 summary + 选带算 CNC 路径; 成功即候选就绪"}
                            # unilab:node_uuid=aca8f76c-572e-5998-9820-1fb7cb0573bf
                            with group(name='说明 · 据视觉 summary + 选带算 CNC 路径; 成功即候选就绪'):
                                # [VERIFY comment] 只读来源校验 photoscrape_process@body/12/then/1/body/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=b33c3e25-f8cd-5506-a670-20a866441c3c disabled=true
                                projected_control_0019 = material.review_control_node_v1(
                                    operation_name='photoscrape_process',
                                    node_path='body/12/then/1/body/0',
                                    control_kind='comment',
                                    expected_sha256='ed36a7fc47e8b48fb1a8cc47fe5e757ed1f4c1d15762f34a06a1742da9ab7c32',
                                )
                            # [ACTION photoscrape.cnc_path] 来源 photoscrape_process@body/12/then/1/body/1；原节点 {"action":"photoscrape.cnc_path","args":{"band_id":{"var":"band_id"},"summary_path":{"field":{"var":"vis"},"name":"summary_path"}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=f7bd6202-0af2-58b4-b2ca-3d77c783a5b8 disabled=true
                            projected_action_0020 = photoscrape.cnc_path(
                                summary_path='review-only',
                                band_id='review-only',
                            )
                            # [CONTROL assign] 来源 photoscrape_process@body/12/then/1/body/2；原节点 {"op":"assign","target":{"var":"cand_summary_path"},"value":{"field":{"var":"vis"},"name":"summary_path"}}
                            # unilab:node_uuid=4f4e97bf-73ea-50fb-91e6-2d787deecd36
                            with group(name='变量赋值'):
                                # [VERIFY assign] 只读来源校验 photoscrape_process@body/12/then/1/body/2；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=e3ce6475-339f-574d-9059-ce9ada58955a disabled=true
                                projected_control_0021 = material.review_control_node_v1(
                                    operation_name='photoscrape_process',
                                    node_path='body/12/then/1/body/2',
                                    control_kind='assign',
                                    expected_sha256='deea15449539735a5483a2f8561f1cb4600410ca2fcb51b85d5b0eaa14a55c95',
                                )
                            # [CONTROL assign] 来源 photoscrape_process@body/12/then/1/body/3；原节点 {"op":"assign","target":{"var":"cand_band_id"},"value":{"var":"band_id"}}
                            # unilab:node_uuid=c3d57896-33d1-5791-9df4-4928601b4cf3
                            with group(name='变量赋值'):
                                # [VERIFY assign] 只读来源校验 photoscrape_process@body/12/then/1/body/3；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=b6554aa1-c732-520f-8e9f-af887664c5e5 disabled=true
                                projected_control_0022 = material.review_control_node_v1(
                                    operation_name='photoscrape_process',
                                    node_path='body/12/then/1/body/3',
                                    control_kind='assign',
                                    expected_sha256='6c51fb6a2812a0bd9597fea6208bc8dd02cbb0ab14706abacc058a3e287fd591',
                                )
                            # [CONTROL assign] 来源 photoscrape_process@body/12/then/1/body/4；原节点 {"op":"assign","target":{"var":"cand_annotated_url"},"value":{"field":{"var":"cnc"},"name":"preview_url"}}
                            # unilab:node_uuid=1acad822-163c-5bda-ad3f-e939aa33d5a5
                            with group(name='变量赋值'):
                                # [VERIFY assign] 只读来源校验 photoscrape_process@body/12/then/1/body/4；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=be2239ca-9b8d-5a17-9e5b-d363840ec3a7 disabled=true
                                projected_control_0023 = material.review_control_node_v1(
                                    operation_name='photoscrape_process',
                                    node_path='body/12/then/1/body/4',
                                    control_kind='assign',
                                    expected_sha256='0de53db5d7fe626f69a037677f5427ecd0ee5844a4cf90ab14acb3c6903e87ec',
                                )
                            # [CONTROL assign] 来源 photoscrape_process@body/12/then/1/body/5；原节点 {"op":"assign","target":{"var":"cand_valid"},"value":{"lit":true}}
                            # unilab:node_uuid=c2e75e4f-1f6a-5ff1-a67f-6f0535fbcc15
                            with group(name='变量赋值'):
                                # [VERIFY assign] 只读来源校验 photoscrape_process@body/12/then/1/body/5；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=e46beb97-92a1-5fc6-b8bb-362937b7a520 disabled=true
                                projected_control_0024 = material.review_control_node_v1(
                                    operation_name='photoscrape_process',
                                    node_path='body/12/then/1/body/5',
                                    control_kind='assign',
                                    expected_sha256='d8f3a9179a29d24513ab396906aeefce9b0926b8d3e726cf13f1fecdb6562400',
                                )
                        # [BRANCH CATCH 1] photoscrape_process@body/12/then/1/catch/0/body 的静态审阅分支。
                        # unilab:node_uuid=1295fc19-b0fc-518f-b95d-949847e4ab39
                        with group(name='CATCH 1'):
                            # [CONTROL comment] 来源 photoscrape_process@body/12/then/1/catch/0/body/0；原节点 {"op":"comment","text":"路径生成失败(几何/选带非法): cand_valid 仍 false, 落到门人工处置"}
                            # unilab:node_uuid=72fc5af5-0950-59d5-a2c4-6bb8302144a4
                            with group(name='说明 · 路径生成失败(几何/选带非法): cand_valid 仍 false, 落到门人工处置'):
                                # [VERIFY comment] 只读来源校验 photoscrape_process@body/12/then/1/catch/0/body/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=43d66a2b-516f-5f2c-8494-f667b8dcb0c4 disabled=true
                                projected_control_0025 = material.review_control_node_v1(
                                    operation_name='photoscrape_process',
                                    node_path='body/12/then/1/catch/0/body/0',
                                    control_kind='comment',
                                    expected_sha256='2e025c35e27322bc04858a6a4c05c1cee6359092e581861746ac46f9c916e796',
                                )
                # [BRANCH ELSE（互斥分支）] photoscrape_process@body/12/else 的静态审阅分支。
                # unilab:node_uuid=f1fd2302-abd7-5eb4-a575-cac51e9e5b8b
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/12；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=ce2fa05f-85a5-5198-9843-783184e2f179 disabled=true
                    projected_control_0026 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/12',
                        control_kind='if',
                        expected_sha256='bef7b8f0c41ad97b1b4ed49231ff5fe7791a0b8e44c62720217a5b9090dab9a8',
                    )
            # [CONTROL comment] 来源 photoscrape_process@body/13；原节点 {"op":"comment","text":"(3b) 固定路径实验(回收率): fixed_summary_path 非空 → 用它算路径覆盖候选, 自动下发跳过门; 默认空则本块不进, 生产行为逐字节不变"}
            # unilab:node_uuid=3c43ada1-54ff-57e8-bb2e-e6e013eec49f
            with group(name='说明 · (3b) 固定路径实验(回收率): fixed_summary_path 非空 → 用它算路径覆盖候选, 自动下'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/13；节点在本工作流中静态 disabled。
                # unilab:node_uuid=4bd09baf-7390-59be-951b-d4e45e436b53 disabled=true
                projected_control_0027 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/13',
                    control_kind='comment',
                    expected_sha256='62d72928b49b6258e279c0c92677b4f104813443418b77ce4165d26006d6a3eb',
                )
            # [CONTROL if] 来源 photoscrape_process@body/14；原节点 {"cond":{"binop":"!=","left":{"var":"fixed_summary_path"},"right":{"lit":""}},"op":"if","then":[{"action":"photoscrape.cnc_path","args":{"band_id":{"var":"fixed_band_id"},"summary_path":{"var":"fixed_summary_path"}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"},{"op":"assign","target":{"var":"cand_summary_path"},"valu...
            # unilab:node_uuid=33885650-c6f6-57d1-80e1-0baebfff578b
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 photoscrape_process@body/14；节点在本工作流中静态 disabled。
                # unilab:node_uuid=63268df2-4caf-50d7-ac8c-b6322d6d1c6e disabled=true
                projected_control_0028 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/14',
                    control_kind='if',
                    expected_sha256='1f8f297e4a9be82a4e9958e0734fc991b675c9e2b90ee8e01e4083fe08240dd1',
                )
                # [BRANCH THEN（互斥分支）] photoscrape_process@body/14/then 的静态审阅分支。
                # unilab:node_uuid=648b582e-e2dc-52bf-87ff-b9c531cd8ee3
                with group(name='THEN（互斥分支）'):
                    # [ACTION photoscrape.cnc_path] 来源 photoscrape_process@body/14/then/0；原节点 {"action":"photoscrape.cnc_path","args":{"band_id":{"var":"fixed_band_id"},"summary_path":{"var":"fixed_summary_path"}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=53ed3db7-5906-5541-ad7b-f1432d516088 disabled=true
                    projected_action_0029 = photoscrape.cnc_path(
                        summary_path='review-only',
                        band_id='review-only',
                    )
                    # [CONTROL assign] 来源 photoscrape_process@body/14/then/1；原节点 {"op":"assign","target":{"var":"cand_summary_path"},"value":{"var":"fixed_summary_path"}}
                    # unilab:node_uuid=e7453080-667c-5cde-a76c-ce2f133f7f2a
                    with group(name='变量赋值'):
                        # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/1；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=cbf1a8f7-ff67-5d72-b679-88d88820cc06 disabled=true
                        projected_control_0030 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/14/then/1',
                            control_kind='assign',
                            expected_sha256='93aeffa6c5c7cfbe2efbaffafeb5ca2373f9917164efa5bd7b277192a19c26be',
                        )
                    # [CONTROL assign] 来源 photoscrape_process@body/14/then/2；原节点 {"op":"assign","target":{"var":"cand_band_id"},"value":{"var":"fixed_band_id"}}
                    # unilab:node_uuid=93bbc050-c558-556f-b4d2-ba71d0502e90
                    with group(name='变量赋值'):
                        # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/2；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=264cd989-7cc9-530f-b091-ca94aaabc37e disabled=true
                        projected_control_0031 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/14/then/2',
                            control_kind='assign',
                            expected_sha256='0fc9c6ac422b29e28ece3dff7d97d9a27e348d7df5c8c250ac7fc915b4df6446',
                        )
                    # [CONTROL assign] 来源 photoscrape_process@body/14/then/3；原节点 {"op":"assign","target":{"var":"cand_annotated_url"},"value":{"field":{"var":"cnc"},"name":"preview_url"}}
                    # unilab:node_uuid=b05d37f7-6846-5dd9-9394-bbcbff591686
                    with group(name='变量赋值'):
                        # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/3；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=1758ac7d-2957-526f-b95d-c1a032f38c12 disabled=true
                        projected_control_0032 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/14/then/3',
                            control_kind='assign',
                            expected_sha256='0de53db5d7fe626f69a037677f5427ecd0ee5844a4cf90ab14acb3c6903e87ec',
                        )
                    # [CONTROL assign] 来源 photoscrape_process@body/14/then/4；原节点 {"op":"assign","target":{"var":"cand_valid"},"value":{"lit":true}}
                    # unilab:node_uuid=14640169-70d1-53d5-9e30-738087df433f
                    with group(name='变量赋值'):
                        # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/4；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=18d13e36-1500-5360-bf33-8defb1517d86 disabled=true
                        projected_control_0033 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/14/then/4',
                            control_kind='assign',
                            expected_sha256='d8f3a9179a29d24513ab396906aeefce9b0926b8d3e726cf13f1fecdb6562400',
                        )
                    # [CONTROL assign] 来源 photoscrape_process@body/14/then/5；原节点 {"op":"assign","target":{"var":"dispatched"},"value":{"lit":true}}
                    # unilab:node_uuid=a7d6569d-4a8d-5a73-bc3e-e9992534de6c
                    with group(name='变量赋值'):
                        # [VERIFY assign] 只读来源校验 photoscrape_process@body/14/then/5；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=da73ebb3-9e62-5383-b5dc-f01c140b840d disabled=true
                        projected_control_0034 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/14/then/5',
                            control_kind='assign',
                            expected_sha256='4c0312b294cf799e4298d9ac5f86db983ce646321e167a34ce095caae54823ca',
                        )
                # [BRANCH ELSE（互斥分支）] photoscrape_process@body/14/else 的静态审阅分支。
                # unilab:node_uuid=d4f3e2cc-e018-5430-ac42-d6ef2aaada34
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/14；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=1ec15a48-ba08-590d-b2a4-0340713eca28 disabled=true
                    projected_control_0035 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/14',
                        control_kind='if',
                        expected_sha256='1f8f297e4a9be82a4e9958e0734fc991b675c9e2b90ee8e01e4083fe08240dd1',
                    )
            # [CONTROL comment] 来源 photoscrape_process@body/15；原节点 {"op":"comment","text":"(4) 自动模式: 候选有效 → 直接下发; 无效 → 不设 dispatched, 落到门(降级人工 1b)"}
            # unilab:node_uuid=50fb4030-0324-533a-939e-74aeb3d27b12
            with group(name='说明 · (4) 自动模式: 候选有效 → 直接下发; 无效 → 不设 dispatched, 落到门(降级人工 1b)'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/15；节点在本工作流中静态 disabled。
                # unilab:node_uuid=d44765fc-ccba-5b31-ada8-f4e05d76e733 disabled=true
                projected_control_0036 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/15',
                    control_kind='comment',
                    expected_sha256='88835eccbc2c537802d2bb3c5676965019a23bbc61fe776e9227b8f723ab6dcf',
                )
            # [CONTROL if] 来源 photoscrape_process@body/16；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"mode"},"right":{"lit":"auto"}},"right":{"var":"cand_valid"}},"op":"if","then":[{"op":"assign","target":{"var":"dispatched"},"value":{"lit":true}}]}
            # unilab:node_uuid=2f0b1e4a-fc3c-5d68-a48d-d1ac1b30fcda
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 photoscrape_process@body/16；节点在本工作流中静态 disabled。
                # unilab:node_uuid=59706978-a855-5438-a4f3-e66be0e0afad disabled=true
                projected_control_0037 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/16',
                    control_kind='if',
                    expected_sha256='9a7cd55d2e2df352b347fc47aa7d90bd876604f336a80edfca2244dcce18a292',
                )
                # [BRANCH THEN（互斥分支）] photoscrape_process@body/16/then 的静态审阅分支。
                # unilab:node_uuid=41152357-d87f-5215-8235-d2ab11b0b744
                with group(name='THEN（互斥分支）'):
                    # [CONTROL assign] 来源 photoscrape_process@body/16/then/0；原节点 {"op":"assign","target":{"var":"dispatched"},"value":{"lit":true}}
                    # unilab:node_uuid=9601ed38-f98d-56e7-a6d4-438273730ebe
                    with group(name='变量赋值'):
                        # [VERIFY assign] 只读来源校验 photoscrape_process@body/16/then/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=a94f971a-26c1-54b9-b53b-70ed29b38b8b disabled=true
                        projected_control_0038 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/16/then/0',
                            control_kind='assign',
                            expected_sha256='4c0312b294cf799e4298d9ac5f86db983ce646321e167a34ce095caae54823ca',
                        )
                # [BRANCH ELSE（互斥分支）] photoscrape_process@body/16/else 的静态审阅分支。
                # unilab:node_uuid=8309d135-6331-50b0-b3c0-16d8e0b34c35
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/16；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=427df2e8-5f52-5242-bb1c-3a841538d12b disabled=true
                    projected_control_0039 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/16',
                        control_kind='if',
                        expected_sha256='9a7cd55d2e2df352b347fc47aa7d90bd876604f336a80edfca2244dcce18a292',
                    )
            # [CONTROL comment] 来源 photoscrape_process@body/17；原节点 {"op":"comment","text":"(5) 统一门环(manual 或 auto 降级): 下发/手绘/跳过/中止"}
            # unilab:node_uuid=2c9a9efb-bf04-57de-a006-8febf5c003c3
            with group(name='说明 · (5) 统一门环(manual 或 auto 降级): 下发/手绘/跳过/中止'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/17；节点在本工作流中静态 disabled。
                # unilab:node_uuid=5d083969-b004-5277-ac82-a37ff8016fe2 disabled=true
                projected_control_0040 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/17',
                    control_kind='comment',
                    expected_sha256='26b67b5edb78b29314a26fb5736037763d8947f04c641d71177906547be5a5e4',
                )
            # [LOOP while · BODY NOT EXPANDED] 只读来源校验 photoscrape_process@body/18；节点在本工作流中静态 disabled。
            # unilab:node_uuid=8d4dc3c0-3385-5222-8bff-6f8102eb0372 disabled=true
            projected_control_0041 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/18',
                control_kind='while',
                expected_sha256='97cb3a2650fc0d7eff3a3a366ca51a2d026a592ed928ab155b2db2af81ce781e',
            )
            # [CONTROL comment] 来源 photoscrape_process@body/19；原节点 {"op":"comment","text":"(6) 收尾: 跳过→安全占位数组(pass_count=0); 否则 cnc 已在候选阶段算好"}
            # unilab:node_uuid=d0af95ef-94a9-52f6-bc26-0fe3402869e5
            with group(name='说明 · (6) 收尾: 跳过→安全占位数组(pass_count=0); 否则 cnc 已在候选阶段算好'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/19；节点在本工作流中静态 disabled。
                # unilab:node_uuid=720e23b9-f083-5291-b134-5d2cd41f794d disabled=true
                projected_control_0042 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/19',
                    control_kind='comment',
                    expected_sha256='c0b0060a7696639df3793848978f57cd511136ec0d94353bd7dd65031c672d87',
                )
            # [CONTROL if] 来源 photoscrape_process@body/20；原节点 {"cond":{"var":"skip_scrape"},"op":"if","then":[{"op":"comment","text":"无谱带/跳过刮板: cnc_path(placeholder=true) → pass_count=0 全 0 数组, scrape 一次不跑, 空跑收尾"},{"action":"photoscrape.cnc_path","args":{"band_id":{"lit":""},"placeholder":{"lit":true},"summary_path":{"lit":""}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"}]}
            # unilab:node_uuid=57b184eb-161f-5e90-8b04-ad0bff53295e
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 photoscrape_process@body/20；节点在本工作流中静态 disabled。
                # unilab:node_uuid=6a734edd-009a-57be-ba02-641310ab4d97 disabled=true
                projected_control_0043 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/20',
                    control_kind='if',
                    expected_sha256='421742e29baadc4e257de5dddab830ab620c5becb50f1a176b6833889141db5b',
                )
                # [BRANCH THEN（互斥分支）] photoscrape_process@body/20/then 的静态审阅分支。
                # unilab:node_uuid=49a86fd6-e42f-58ce-aeb7-cdaf16da299b
                with group(name='THEN（互斥分支）'):
                    # [CONTROL comment] 来源 photoscrape_process@body/20/then/0；原节点 {"op":"comment","text":"无谱带/跳过刮板: cnc_path(placeholder=true) → pass_count=0 全 0 数组, scrape 一次不跑, 空跑收尾"}
                    # unilab:node_uuid=1470f71e-858f-5abe-84db-51c60c5f35af
                    with group(name='说明 · 无谱带/跳过刮板: cnc_path(placeholder=true) → pass_count=0 全 0 '):
                        # [VERIFY comment] 只读来源校验 photoscrape_process@body/20/then/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=02cf2c09-f709-53c6-9ad5-61b7a3599b6d disabled=true
                        projected_control_0044 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/20/then/0',
                            control_kind='comment',
                            expected_sha256='8eb02bbf758937db75580fc46aa213c3c5b00b11eece4d9732631fdf40823806',
                        )
                    # [ACTION photoscrape.cnc_path] 来源 photoscrape_process@body/20/then/1；原节点 {"action":"photoscrape.cnc_path","args":{"band_id":{"lit":""},"placeholder":{"lit":true},"summary_path":{"lit":""}},"assign":{"var":"cnc"},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=a972d211-17e8-51a3-a66d-4f214da92a62 disabled=true
                    projected_action_0045 = photoscrape.cnc_path(
                        summary_path='',
                        band_id='',
                    )
                # [BRANCH ELSE（互斥分支）] photoscrape_process@body/20/else 的静态审阅分支。
                # unilab:node_uuid=707a4434-14d9-590a-8818-5bcb0c4b99cb
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/20；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=d142fa19-c7ab-595b-834d-da371e2e8922 disabled=true
                    projected_control_0046 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/20',
                        control_kind='if',
                        expected_sha256='421742e29baadc4e257de5dddab830ab620c5becb50f1a176b6833889141db5b',
                    )
            # [CONTROL comment] 来源 photoscrape_process@body/21；原节点 {"op":"comment","text":"块写 4 数组+进给 (回读确认), 一次, scrape 循环前"}
            # unilab:node_uuid=54f79f3b-efe2-5d8f-b4c1-d4a96d6b8b1b
            with group(name='说明 · 块写 4 数组+进给 (回读确认), 一次, scrape 循环前'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/21；节点在本工作流中静态 disabled。
                # unilab:node_uuid=c05975a5-e23a-5f12-a22e-fa770035e441 disabled=true
                projected_control_0047 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/21',
                    control_kind='comment',
                    expected_sha256='15cb99a88abe73ce5a8085c1c9fb75139e3000552e7a6ef6ad4c1ed90792ba8e',
                )
            # [ACTION photoscrape.write_cnc_path] 来源 photoscrape_process@body/22；原节点 {"action":"photoscrape.write_cnc_path","args":{"cx":{"field":{"var":"cnc"},"name":"g_cx"},"cy":{"field":{"var":"cnc"},"name":"g_cy"},"feed":{"field":{"var":"cnc"},"name":"g_scrape_feed"},"sx":{"field":{"var":"cnc"},"name":"g_sx"},"sy":{"field":{"var":"cnc"},"name":"g_sy"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=42bfdaf0-52a3-52bf-868d-23a872eeb7a0 disabled=true
            projected_action_0048 = photoscrape.write_cnc_path(
                sx=[0.0],
                sy=[0.0],
                cx=[0.0],
                cy=[0.0],
                feed=1,
            )
            # [CONTROL comment] 来源 photoscrape_process@body/23；原节点 {"op":"comment","text":"上位机循环 pass: 逐层写 Z 切深(回读确认)→触发单 pass; PLC 不内部循环 (跳过刮板时 pass_z_list 空, 0 次)"}
            # unilab:node_uuid=ee3dd46c-10ac-588f-8e91-c712949ad4b6
            with group(name='说明 · 上位机循环 pass: 逐层写 Z 切深(回读确认)→触发单 pass; PLC 不内部循环 (跳过刮板时 pa'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/23；节点在本工作流中静态 disabled。
                # unilab:node_uuid=6fb429a3-90e5-5e3d-9a50-db4d4dc4978c disabled=true
                projected_control_0049 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/23',
                    control_kind='comment',
                    expected_sha256='69b202a1602a12b76a73278cdd6a0aa5ca8952dc526169cc91b66c4c86d0c36b',
                )
            # [CONTROL comment] 来源 photoscrape_process@body/24；原节点 {"op":"comment","text":"scrape(40) 按下发路径同跑刮取(g_sx/g_sy)+收集(g_cx/g_cy), 无独立收集步"}
            # unilab:node_uuid=fbcadbcc-5160-519d-8851-7a1a0735dedd
            with group(name='说明 · scrape(40) 按下发路径同跑刮取(g_sx/g_sy)+收集(g_cx/g_cy), 无独立收集步'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/24；节点在本工作流中静态 disabled。
                # unilab:node_uuid=c0071d5d-1bd8-53a2-921f-7f636f55dd34 disabled=true
                projected_control_0050 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/24',
                    control_kind='comment',
                    expected_sha256='a7227fda72c9978fb74ac93a2075e5668869a0bd5a261f7355b7ee61c7b01f6c',
                )
            # [LOOP for · BODY NOT EXPANDED] 只读来源校验 photoscrape_process@body/25；节点在本工作流中静态 disabled。
            # unilab:node_uuid=aa282ea1-c1b4-5e35-b6a9-4d49e6bf145e disabled=true
            projected_control_0051 = material.review_control_node_v1(
                operation_name='photoscrape_process',
                node_path='body/25',
                control_kind='for',
                expected_sha256='f81813ba4a0ed43e467ac7ab08a075b8f945fdc64baf68533f30f5c9abe52dc0',
            )
            # [CONTROL comment] 来源 photoscrape_process@body/26；原节点 {"op":"comment","text":"(7) 刮后对账照片(哨兵非工艺步): 板仍压紧+相机回同一拍照位 → scraped.jpg 与 after.jpg 像素对齐; 叠同一 preview payload = 说好的vs刮到的; 失败不 fault (reconcile_photo=false 或跳过刮板时不拍)"}
            # unilab:node_uuid=46fa4ada-909a-5d49-be83-ec030e7284d8
            with group(name='说明 · (7) 刮后对账照片(哨兵非工艺步): 板仍压紧+相机回同一拍照位 → scraped.jpg 与 after.'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/26；节点在本工作流中静态 disabled。
                # unilab:node_uuid=e44df427-f09f-5397-adcf-07ab0e3a19ff disabled=true
                projected_control_0052 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/26',
                    control_kind='comment',
                    expected_sha256='82d246ab29f67dcd0eba5ebf004698052f788be7dfab19bf028f50350d06a0be',
                )
            # [CONTROL if] 来源 photoscrape_process@body/27；原节点 {"cond":{"binop":"and","left":{"var":"reconcile_photo"},"right":{"operand":{"var":"skip_scrape"},"unop":"not"}},"op":"if","then":[{"body":[{"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"},{"action":"photoscrape.capture","args":{"filename":{"lit":"scraped.jpg"},"profile":...
            # unilab:node_uuid=c098e0de-b3d3-550d-b924-dec1ad6d3637
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 photoscrape_process@body/27；节点在本工作流中静态 disabled。
                # unilab:node_uuid=1738276e-c0ad-57e5-bd16-5b4c5d01fcce disabled=true
                projected_control_0053 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/27',
                    control_kind='if',
                    expected_sha256='f5190107a512fbdaeeb5704b9a40446d7b133d1712c1c39bb03870b5f413cf11',
                )
                # [BRANCH THEN（互斥分支）] photoscrape_process@body/27/then 的静态审阅分支。
                # unilab:node_uuid=702eabdf-daf9-5c81-b65f-c9b00d8a1609
                with group(name='THEN（互斥分支）'):
                    # [CONTROL try] 来源 photoscrape_process@body/27/then/0；原节点 {"body":[{"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"},{"action":"photoscrape.capture","args":{"filename":{"lit":"scraped.jpg"},"profile":{"lit":"photoscrape"},"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"assign":{"var":"scraped_shot"},"mode"...
                    # unilab:node_uuid=7cf46180-5890-5ae0-9416-bc246329774e
                    with group(name='TRY / CATCH（PlatformUI 异常语义）'):
                        # [VERIFY try] 只读来源校验 photoscrape_process@body/27/then/0；节点在本工作流中静态 disabled。
                        # unilab:node_uuid=644ff60e-e8a2-529e-bf3e-29f4c43b67a2 disabled=true
                        projected_control_0054 = material.review_control_node_v1(
                            operation_name='photoscrape_process',
                            node_path='body/27/then/0',
                            control_kind='try',
                            expected_sha256='c065fc6e0ee4f56a11581bb600251502a3cb64612c732abc11af1b4595c85a02',
                        )
                        # [BRANCH TRY] photoscrape_process@body/27/then/0/body 的静态审阅分支。
                        # unilab:node_uuid=bc530aba-94c9-5bc9-8dc4-a8c5be571f84
                        with group(name='TRY'):
                            # [ACTION photoscrape.cam_photopos] 来源 photoscrape_process@body/27/then/0/body/0；原节点 {"action":"photoscrape.cam_photopos","args":{"ref_8y":{"lit":"photo_8y"}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=52368958-b974-5a74-8e17-bdef8d09edfa disabled=true
                            projected_action_0055 = photoscrape.cam_photopos(
                                ref_8y='photo_8y',
                            )
                            # [ACTION photoscrape.capture] 来源 photoscrape_process@body/27/then/0/body/1；原节点 {"action":"photoscrape.capture","args":{"filename":{"lit":"scraped.jpg"},"profile":{"lit":"photoscrape"},"sample_id":{"var":"sample_id"},"save_dir":{"var":"save_dir"}},"assign":{"var":"scraped_shot"},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=d5d03fb7-0480-5302-a37b-0b957bba82a1 disabled=true
                            projected_action_0056 = photoscrape.capture(
                                sample_id='review-only',
                                save_dir='review-only',
                            )
                            # [ACTION photoscrape.cam_photohome] 来源 photoscrape_process@body/27/then/0/body/2；原节点 {"action":"photoscrape.cam_photohome","mode":"RUN","op":"call"}
                            # unilab:node_uuid=75972246-b64c-57d8-b3be-c2285408a008 disabled=true
                            projected_action_0057 = photoscrape.cam_photohome()
                            # [ACTION photoscrape.scraped_overlay] 来源 photoscrape_process@body/27/then/0/body/3；原节点 {"action":"photoscrape.scraped_overlay","args":{"scraped_path":{"field":{"var":"scraped_shot"},"name":"image_path"},"summary_path":{"var":"cand_summary_path"}},"mode":"RUN","op":"call"}
                            # unilab:node_uuid=174ffd3a-9514-5a8d-bbaa-927d8d09fafe disabled=true
                            projected_action_0058 = photoscrape.scraped_overlay(
                                summary_path='review-only',
                                scraped_path='review-only',
                            )
                        # [BRANCH CATCH 1] photoscrape_process@body/27/then/0/catch/0/body 的静态审阅分支。
                        # unilab:node_uuid=cc99a218-7c1c-567c-b4b5-9aa48ed77c07
                        with group(name='CATCH 1'):
                            # [CONTROL comment] 来源 photoscrape_process@body/27/then/0/catch/0/body/0；原节点 {"op":"comment","text":"对账补拍/叠加失败不阻断收尾; best-effort 收相机(此步再失败交外层 fault, 相机确需人工)"}
                            # unilab:node_uuid=2731173e-16c0-5e0d-bc6e-e07d52ce4c6a
                            with group(name='说明 · 对账补拍/叠加失败不阻断收尾; best-effort 收相机(此步再失败交外层 fault, 相机确需人工)'):
                                # [VERIFY comment] 只读来源校验 photoscrape_process@body/27/then/0/catch/0/body/0；节点在本工作流中静态 disabled。
                                # unilab:node_uuid=ef2d6f80-d03f-55b8-98ed-ad6df68326b1 disabled=true
                                projected_control_0059 = material.review_control_node_v1(
                                    operation_name='photoscrape_process',
                                    node_path='body/27/then/0/catch/0/body/0',
                                    control_kind='comment',
                                    expected_sha256='bb25ca942792e4bdebc34f20044adb5737fee5712502a336023d424c3d61cc31',
                                )
                            # [ACTION photoscrape.cam_photohome] 来源 photoscrape_process@body/27/then/0/catch/0/body/1；原节点 {"action":"photoscrape.cam_photohome","mode":"RUN","op":"call"}
                            # unilab:node_uuid=d288d504-9a37-5642-9d26-60358dcc79de disabled=true
                            projected_action_0060 = photoscrape.cam_photohome()
                # [BRANCH ELSE（互斥分支）] photoscrape_process@body/27/else 的静态审阅分支。
                # unilab:node_uuid=5c1e1a58-c7e9-546e-aaa6-fb1ac0bd9d8a
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 photoscrape_process@body/27；节点在本工作流中静态 disabled。
                    # unilab:node_uuid=90566e6f-4047-55f3-8d7b-da759bd29ca1 disabled=true
                    projected_control_0061 = material.review_control_node_v1(
                        operation_name='photoscrape_process',
                        node_path='body/27',
                        control_kind='if',
                        expected_sha256='f5190107a512fbdaeeb5704b9a40446d7b133d1712c1c39bb03870b5f413cf11',
                    )
            # [CONTROL comment] 来源 photoscrape_process@body/28；原节点 {"op":"comment","text":"【执行收尾】刮取收尾复合动作; 不替代定位/下压/接粉夹具目标态释放"}
            # unilab:node_uuid=791f7e63-bd21-5541-8a7c-9c726fe3a684
            with group(name='说明 · 【执行收尾】刮取收尾复合动作; 不替代定位/下压/接粉夹具目标态释放'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/28；节点在本工作流中静态 disabled。
                # unilab:node_uuid=0937fc4f-4dff-5943-87c1-c5b04b984b71 disabled=true
                projected_control_0062 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/28',
                    control_kind='comment',
                    expected_sha256='94b3e7d18efab694e0706f3e89e91c28b565263185ba6162383650804306e95c',
                )
            # [ACTION photoscrape.scrape_finish] 来源 photoscrape_process@body/29；原节点 {"action":"photoscrape.scrape_finish","mode":"RUN","op":"call"}
            # unilab:node_uuid=ba90a944-8f44-5c37-9c08-14cd67722894 disabled=true
            projected_action_0063 = photoscrape.scrape_finish()
            # [CONTROL comment] 来源 photoscrape_process@body/30；原节点 {"op":"comment","text":"确认翻料缸真到动点: A41 是开环(同扫描周期返回 DONE, 不等气缸反馈), 生产此前从不确认 ——"}
            # unilab:node_uuid=5b2cf616-2641-52bc-ae08-d9c893936dc7
            with group(name='说明 · 确认翻料缸真到动点: A41 是开环(同扫描周期返回 DONE, 不等气缸反馈), 生产此前从不确认 ——'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/30；节点在本工作流中静态 disabled。
                # unilab:node_uuid=b6cca20e-cddd-59a5-9e3e-14c7ad594004 disabled=true
                projected_control_0064 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/30',
                    control_kind='comment',
                    expected_sha256='bd4436a9c740451b22aacc5d24e4be7b95568584b8b81569c6dcfb01ee9cc005',
                )
            # [CONTROL comment] 来源 photoscrape_process@body/31；原节点 {"op":"comment","text":"气压不足/机构卡滞导致压根没翻是完全看不见的哑故障(粉留在转运路径上, 后续掉出去)"}
            # unilab:node_uuid=04d8a821-3b9e-5322-b1e2-90cd3bfa05a5
            with group(name='说明 · 气压不足/机构卡滞导致压根没翻是完全看不见的哑故障(粉留在转运路径上, 后续掉出去)'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/31；节点在本工作流中静态 disabled。
                # unilab:node_uuid=fe6b7252-d25c-51fb-a4a7-25c1b5db7d6d disabled=true
                projected_control_0065 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/31',
                    control_kind='comment',
                    expected_sha256='9ac117f3b8b56b0bd37015e580ba7aa9a2e65961b1211a3413a528c251402ad6',
                )
            # [CONTROL comment] 来源 photoscrape_process@body/32；原节点 {"op":"comment","text":"复位在 collect_load(机器人取走粉桶之后), 故这里只确认不复位; 哨兵语义, 超时只 WARN 不抛"}
            # unilab:node_uuid=d7429f39-1755-549a-9250-248757de8f70
            with group(name='说明 · 复位在 collect_load(机器人取走粉桶之后), 故这里只确认不复位; 哨兵语义, 超时只 WARN 不'):
                # [VERIFY comment] 只读来源校验 photoscrape_process@body/32；节点在本工作流中静态 disabled。
                # unilab:node_uuid=0fc1a52e-ee32-5d58-9757-a2da5af8061b disabled=true
                projected_control_0066 = material.review_control_node_v1(
                    operation_name='photoscrape_process',
                    node_path='body/32',
                    control_kind='comment',
                    expected_sha256='7d7516b58d541f7a7c4703344481ee18eaa208960a0cd5d570947b5a4f0f7c35',
                )
            # [ACTION photoscrape.wait_rot] 来源 photoscrape_process@body/33；原节点 {"action":"photoscrape.wait_rot","args":{"target":{"lit":"extend"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=8128cfa8-f92b-5837-8c70-087b6e10657a disabled=true
            projected_action_0067 = photoscrape.wait_rot()
    # [EXECUTE ROOT pf_s9_scrape] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=1dfcafd6-b933-5c5c-b5f5-5fe5b85a7111
    execution = material.run_operation_review_v1(
        operation_name='pf_s9_scrape',
        inputs_json=inputs_json,
        timeout_s=timeout_s,
    )
    return {
        "operation_name": execution.operation_name,
        "command_id": execution.command_id,
        "run_id": execution.run_id,
        "status": execution.status,
        "result_json": execution.result_json,
        "before_path": execution.before_path,
        "collector_hole": execution.collector_hole,
        "bottle_hole": execution.bottle_hole,
    }
