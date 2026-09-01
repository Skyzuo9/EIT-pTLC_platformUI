from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


material: MaterialProxy = device('material')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='aace2ab2-33a5-5fbc-80a6-f4794d53d8f5',
    displayname='启动自检 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_startup_check_operation_view_v2() -> None:
    # [OPERATION robot_startup_check] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=36104cba-6834-5b12-ad8a-07e482637c9a disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_startup_check',
        inputs_json='{}',
        expected_sha256='f4f94f6d5e1b8ff635d2155fc97fda7f9fff9adf87ebad7932240fdef3eb891d',
    )
    # [VERIFY comment] 只读来源校验 robot_startup_check@body/0；本视图中静态 disabled。
    # unilab:node_uuid=c91f8ff7-026c-5367-a666-88300abd188b disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_startup_check',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='7cda7a2fb7460e665015213b9a975c4b3a78c495d7d0fcb076aa076007dc6eb1',
    )
    # [ACTION robot.query] 来源 robot_startup_check@body/1；原节点 {"action":"robot.query","mode":"RUN","op":"call"}
    # unilab:node_uuid=6a6657f6-e534-5466-bb5c-c904b601250a disabled=true
    projected_action_0003 = robot.query()
    # [VERIFY comment] 只读来源校验 robot_startup_check@body/2；本视图中静态 disabled。
    # unilab:node_uuid=9c1e9fbf-fc30-5f6b-a134-655ccd1e3ddf disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='robot_startup_check',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='6a40ecad06e39bc4c89d9d25afcd0734398fd903d1756e8f0f416e326f41ba14',
    )
    # [ACTION robot.home_ensure] 来源 robot_startup_check@body/3；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=233770fb-a27d-5e9b-be1d-96f999f830c4 disabled=true
    projected_action_0005 = robot.home_ensure()
