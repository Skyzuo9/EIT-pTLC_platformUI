from __future__ import annotations

from typing import TypedDict

from unilabos.workflow.authoring import device, group, parallel, workflow
from eit_ptlc.unilab_domain.devices.plc_develop import PLCDevelop
from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class PlatformOperationReviewV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    before_path: str
    collector_hole: int
    bottle_hole: int

develop: PLCDevelop = device('plc_develop')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='b9e28440-a333-5b78-a62d-a90d0b4f83ca',
    displayname='2-2 展缸预备 · PlatformUI Action 审阅',
    description=(
        '真实 PlatformUI action 与控制结构的只读投影；所有投影动作静态 disabled。'
        '循环只显示边界节点、不展开 body；唯一启用节点一次提交原根 operation，'
        'ResourceGate、条件、循环和 HITL 语义不变。'
    ),
)
def pf_s3_tank_prep_action_review_v1(
    *, inputs_json: str = '{}', timeout_s: float = 3600.0
) -> PlatformOperationReviewV1Result:
    """Inspect every source node, then execute only the unchanged root operation."""
    # [审阅投影 pf_s3_tank_prep] 组内节点只用于查看来源，全部 disabled，不会向设备下发。
    # unilab:node_uuid=047a0f7a-6f0a-5ef2-b7ed-01dcfc227478
    with group(name='审阅投影（全部禁用）'):
        # [CONTROL comment] 来源 pf_s3_tank_prep@body/0；原节点 {"op":"comment","text":"展缸预备: 润洗xN -> 正式上液 (develop_prepare 全包); 只占展开工位、不碰样品, 与点样并行"}
        # unilab:node_uuid=709232ed-aeeb-5469-b5a0-a2332cf4cfa0
        with group(name='说明 · 展缸预备: 润洗xN -> 正式上液 (develop_prepare 全包); 只占展开工位、不碰样品, 与点'):
            # [VERIFY comment] 只读来源校验 pf_s3_tank_prep@body/0；节点在本工作流中静态 disabled。
            # unilab:node_uuid=5002126c-93a7-5be1-8681-a0aa24187f3e disabled=true
            projected_control_0001 = material.review_control_node_v1(
                operation_name='pf_s3_tank_prep',
                node_path='body/0',
                control_kind='comment',
                expected_sha256='028e0098e04665759f149440c52d1a4292551c86c3673beb80020cf30759567b',
            )
        # [SUBWORKFLOW develop_prepare] 由 pf_s3_tank_prep@body/1 内联展开；其根资源仍由最外层 PlatformUI operation 持有。
        # unilab:node_uuid=29727494-18b9-588e-889d-3f9c1a82b2be
        with group(name='↳ develop_prepare'):
            # [CONTROL comment] 来源 develop_prepare@body/0；原节点 {"op":"comment","text":"prepare: 展缸初始化 (按目标缸号; 周期内一次)"}
            # unilab:node_uuid=3aea7371-7ca9-5785-afc9-cecf37c603ae
            with group(name='说明 · prepare: 展缸初始化 (按目标缸号; 周期内一次)'):
                # [VERIFY comment] 只读来源校验 develop_prepare@body/0；节点在本工作流中静态 disabled。
                # unilab:node_uuid=8414cbbd-6b41-5db2-ab39-d67c2f5680bb disabled=true
                projected_control_0002 = material.review_control_node_v1(
                    operation_name='develop_prepare',
                    node_path='body/0',
                    control_kind='comment',
                    expected_sha256='f430038a708d287cda5f6aa9cc10061639b7021957ccabb1d9612bf873cc2b3e',
                )
            # [ACTION develop.init] 来源 develop_prepare@body/1；原节点 {"action":"develop.init","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=39e9fa57-54c2-5eb7-aaf7-cab66af7cf46 disabled=true
            projected_action_0003 = develop.init(
                target_tank=1,
            )
            # [CONTROL comment] 来源 develop_prepare@body/2；原节点 {"op":"comment","text":"prepare: 空展缸主动关盖; 后续润洗/正式上液全程保持关盖, 开盖只在 load 放板前执行"}
            # unilab:node_uuid=952293d4-0a1a-5b4d-a23d-32d9a6f8b989
            with group(name='说明 · prepare: 空展缸主动关盖; 后续润洗/正式上液全程保持关盖, 开盖只在 load 放板前执行'):
                # [VERIFY comment] 只读来源校验 develop_prepare@body/2；节点在本工作流中静态 disabled。
                # unilab:node_uuid=f0b4342c-80cb-5ddf-9f71-8f3b7b397b9d disabled=true
                projected_control_0004 = material.review_control_node_v1(
                    operation_name='develop_prepare',
                    node_path='body/2',
                    control_kind='comment',
                    expected_sha256='c7a809fc8f0a78aa2a7d75e8e2df70659b40d4735493d847b7d4900a4cd6dc49',
                )
            # [ACTION develop.plate_extend] 来源 develop_prepare@body/3；原节点 {"action":"develop.plate_extend","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=598d8315-88de-53fb-aeb0-60d244c00414 disabled=true
            projected_action_0005 = develop.plate_extend(
                target_tank=1,
            )
            # [CONTROL comment] 来源 develop_prepare@body/4；原节点 {"op":"comment","text":"prepare: 润洗展缸 (第 1 轮顶掉管路残留, 第 2 轮起润缸; 注液无真空 -> 抽吸段声明真空资源, 由资源门引用计数开关泵)"}
            # unilab:node_uuid=420afeae-352a-5a0d-b833-7fde7585329e
            with group(name='说明 · prepare: 润洗展缸 (第 1 轮顶掉管路残留, 第 2 轮起润缸; 注液无真空 -> 抽吸段声明真空资源'):
                # [VERIFY comment] 只读来源校验 develop_prepare@body/4；节点在本工作流中静态 disabled。
                # unilab:node_uuid=25cae06d-78a8-56ea-b336-1d1dcb6af0d6 disabled=true
                projected_control_0006 = material.review_control_node_v1(
                    operation_name='develop_prepare',
                    node_path='body/4',
                    control_kind='comment',
                    expected_sha256='6bc57f152a541b3de808a5af9f90ffe3c871328db5f562ca3e613b803586715c',
                )
            # [ACTION develop.rinse_fill] 来源 develop_prepare@body/5；原节点 {"action":"develop.rinse_fill","args":{"asp_speed":{"var":"tank_asp_speed"},"disp_speed":{"var":"tank_disp_speed"},"rinse_repeat_count":{"var":"rinse_repeat_count"},"solvent_ratio_1":{"var":"solvent_ratio_1"},"solvent_ratio_2":{"var":"solvent_ratio_2"},"solvent_ratio_3":{"var":"solvent_ratio_3"},"solvent_ratio_4":{"var":"solv...
            # unilab:node_uuid=de0a6fc5-ff96-5acd-86dd-91575efa2bc5 disabled=true
            projected_action_0007 = develop.rinse_fill(
                target_tank=1,
            )
            # [CONTROL with_resources] 来源 develop_prepare@body/6；原节点 {"body":[{"action":"develop.rinse_suction","args":{"cap_s":{"var":"tank_suction_cap_s"},"empty_s":{"var":"tank_suction_empty_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["device:vacuum_pump"]}
            # unilab:node_uuid=7f101e71-9fa4-5d0d-9b06-f76078187f3a
            with group(name='🔒 局部 ResourceGate · device:vacuum_pump'):
                # [VERIFY with_resources] 只读来源校验 develop_prepare@body/6；节点在本工作流中静态 disabled。
                # unilab:node_uuid=1dc609ad-8521-5b3f-8ba6-0e2d80ef01c0 disabled=true
                projected_control_0008 = material.review_control_node_v1(
                    operation_name='develop_prepare',
                    node_path='body/6',
                    control_kind='with_resources',
                    expected_sha256='2eb6bda354c90e102dbe4030b10af810ec877d451063c1cdb5bdde0589ccec37',
                )
                # [BRANCH BODY（结构展开一次）] develop_prepare@body/6/body 的静态审阅分支。
                # unilab:node_uuid=f651f82f-4259-54a6-9ad5-f09ad9dfb8b7
                with group(name='BODY（结构展开一次）'):
                    # [ACTION develop.rinse_suction] 来源 develop_prepare@body/6/body/0；原节点 {"action":"develop.rinse_suction","args":{"cap_s":{"var":"tank_suction_cap_s"},"empty_s":{"var":"tank_suction_empty_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
                    # unilab:node_uuid=c80ae29f-5f99-574e-957f-cbe9ca8658b0 disabled=true
                    projected_action_0009 = develop.rinse_suction(
                        target_tank=1,
                    )
            # [CONTROL comment] 来源 develop_prepare@body/7；原节点 {"op":"comment","text":"prepare: 预置上液 (板进入前完成目标液位; 无真空)"}
            # unilab:node_uuid=82042425-3013-586e-b6d0-667d7cfac0f2
            with group(name='说明 · prepare: 预置上液 (板进入前完成目标液位; 无真空)'):
                # [VERIFY comment] 只读来源校验 develop_prepare@body/7；节点在本工作流中静态 disabled。
                # unilab:node_uuid=e933c5f5-70a4-52e2-9340-0e88415da1ac disabled=true
                projected_control_0010 = material.review_control_node_v1(
                    operation_name='develop_prepare',
                    node_path='body/7',
                    control_kind='comment',
                    expected_sha256='7362ce3bf93efa9cb4c91c18d1ad46ad087d75b1606270ae2b456cac118435f9',
                )
            # [ACTION develop.fill] 来源 develop_prepare@body/8；原节点 {"action":"develop.fill","args":{"asp_speed":{"var":"tank_asp_speed"},"disp_speed":{"var":"tank_disp_speed"},"solvent_ratio_1":{"var":"solvent_ratio_1"},"solvent_ratio_2":{"var":"solvent_ratio_2"},"solvent_ratio_3":{"var":"solvent_ratio_3"},"solvent_ratio_4":{"var":"solvent_ratio_4"},"solvent_volume_ml":{"var":"develop_volume...
            # unilab:node_uuid=ea91a411-fb79-5cc9-b999-c56fb1222fce disabled=true
            projected_action_0011 = develop.fill(
                target_tank=1,
            )
    # [EXECUTE ROOT pf_s3_tank_prep] 本子工作流唯一启用节点：一次提交 PlatformUI 根 operation，整段锁与控制流留在 VM 内。
    # unilab:node_uuid=6cad4b5c-049e-5526-b37f-15054d6e1271
    execution = material.run_operation_review_v1(
        operation_name='pf_s3_tank_prep',
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
