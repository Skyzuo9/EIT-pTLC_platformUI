from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.plc_develop import PLCDevelop
from eit_ptlc.unilab_domain.devices.material import MaterialProxy


develop: PLCDevelop = device('plc_develop')
material: MaterialProxy = device('material')


@workflow(
    workflow_uuid='165162ee-9eef-5fc0-88e0-406f3ca2fa0a',
    displayname='展开-准备 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def develop_prepare_operation_view_v2() -> None:
    # [OPERATION develop_prepare] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=8afa6b48-c352-5f53-b2bb-f1815e4b431c disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='develop_prepare',
        inputs_json='{"develop_volume_ml":20,"rinse_repeat_count":2,"solvent_ratio_1":1,"solvent_ratio_2":0,"solvent_ratio_3":0,"solvent_ratio_4":0,"tank":1,"tank_asp_speed":300,"tank_disp_speed":300,"tank_rinse_volume_ml":10,"tank_suction_cap_s":120.0,"tank_suction_empty_s":10.0,"up_liquid_repeat_count":3}',
        expected_sha256='2e969296a1fc7bf81124c452008f5e6f09542da1d25a4477e3533150ccef358d',
    )
    # [VERIFY comment] 只读来源校验 develop_prepare@body/0；本视图中静态 disabled。
    # unilab:node_uuid=ca6a8d30-b8b7-5d15-8dbe-820ebd804b61 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='develop_prepare',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='f430038a708d287cda5f6aa9cc10061639b7021957ccabb1d9612bf873cc2b3e',
    )
    # [ACTION develop.init] 来源 develop_prepare@body/1；原节点 {"action":"develop.init","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=3abb2c15-df6f-5fe9-b56c-774cf3e78755 disabled=true
    projected_action_0003 = develop.init(
        target_tank=1,
    )
    # [VERIFY comment] 只读来源校验 develop_prepare@body/2；本视图中静态 disabled。
    # unilab:node_uuid=4b1e6d82-6659-5893-bbf8-930591432627 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='develop_prepare',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='c7a809fc8f0a78aa2a7d75e8e2df70659b40d4735493d847b7d4900a4cd6dc49',
    )
    # [ACTION develop.plate_extend] 来源 develop_prepare@body/3；原节点 {"action":"develop.plate_extend","args":{"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=ca716f74-fdc2-57fd-9283-4720498eb12b disabled=true
    projected_action_0005 = develop.plate_extend(
        target_tank=1,
    )
    # [VERIFY comment] 只读来源校验 develop_prepare@body/4；本视图中静态 disabled。
    # unilab:node_uuid=ec534d5c-e63b-5f88-b43f-810fc905a350 disabled=true
    projected_control_0006 = material.review_control_node_v1(
        operation_name='develop_prepare',
        node_path='body/4',
        control_kind='comment',
        expected_sha256='6bc57f152a541b3de808a5af9f90ffe3c871328db5f562ca3e613b803586715c',
    )
    # [ACTION develop.rinse_fill] 来源 develop_prepare@body/5；原节点 {"action":"develop.rinse_fill","args":{"asp_speed":{"var":"tank_asp_speed"},"disp_speed":{"var":"tank_disp_speed"},"rinse_repeat_count":{"var":"rinse_repeat_count"},"solvent_ratio_1":{"var":"solvent_ratio_1"},"solvent_ratio_2":{"var":"solvent_ratio_2"},"solvent_ratio_3":{"var":"solvent_ratio_3"},"solvent_ratio_4":{"var":"solv...
    # unilab:node_uuid=f7534630-4693-5f83-a29c-73fb64e79b2f disabled=true
    projected_action_0007 = develop.rinse_fill(
        target_tank=1,
    )
    # [CONTROL with_resources] 来源 develop_prepare@body/6；原节点 {"body":[{"action":"develop.rinse_suction","args":{"cap_s":{"var":"tank_suction_cap_s"},"empty_s":{"var":"tank_suction_empty_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}],"op":"with_resources","resources":["device:vacuum_pump"]}
    # unilab:node_uuid=21420972-db34-5d9b-ac9f-28f4de3346dc
    with group(name='🔒 局部 ResourceGate · device:vacuum_pump'):
        # [VERIFY with_resources] 只读来源校验 develop_prepare@body/6；本视图中静态 disabled。
        # unilab:node_uuid=3fff7a0e-5542-5787-ba3d-377a9ce9e88c disabled=true
        projected_control_0008 = material.review_control_node_v1(
            operation_name='develop_prepare',
            node_path='body/6',
            control_kind='with_resources',
            expected_sha256='2eb6bda354c90e102dbe4030b10af810ec877d451063c1cdb5bdde0589ccec37',
        )
        # unilab:node_uuid=5967f648-362a-57bf-91dc-9c3fdaf96864
        with group(name='BODY（结构展开一次）'):
            # [ACTION develop.rinse_suction] 来源 develop_prepare@body/6/body/0；原节点 {"action":"develop.rinse_suction","args":{"cap_s":{"var":"tank_suction_cap_s"},"empty_s":{"var":"tank_suction_empty_s"},"target_tank":{"var":"tank"}},"mode":"RUN","op":"call"}
            # unilab:node_uuid=b2f6f4d3-dc54-5dd6-bd21-0b054dbd9aa7 disabled=true
            projected_action_0009 = develop.rinse_suction(
                target_tank=1,
            )
    # [VERIFY comment] 只读来源校验 develop_prepare@body/7；本视图中静态 disabled。
    # unilab:node_uuid=6ed0c1c2-3f4c-590c-92a6-e0fe41b3dbee disabled=true
    projected_control_0010 = material.review_control_node_v1(
        operation_name='develop_prepare',
        node_path='body/7',
        control_kind='comment',
        expected_sha256='7362ce3bf93efa9cb4c91c18d1ad46ad087d75b1606270ae2b456cac118435f9',
    )
    # [ACTION develop.fill] 来源 develop_prepare@body/8；原节点 {"action":"develop.fill","args":{"asp_speed":{"var":"tank_asp_speed"},"disp_speed":{"var":"tank_disp_speed"},"solvent_ratio_1":{"var":"solvent_ratio_1"},"solvent_ratio_2":{"var":"solvent_ratio_2"},"solvent_ratio_3":{"var":"solvent_ratio_3"},"solvent_ratio_4":{"var":"solvent_ratio_4"},"solvent_volume_ml":{"var":"develop_volume...
    # unilab:node_uuid=cdd4547d-ffa2-59ce-8b76-0b4370885339 disabled=true
    projected_action_0011 = develop.fill(
        target_tank=1,
    )
