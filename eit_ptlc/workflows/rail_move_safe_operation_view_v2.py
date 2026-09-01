from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_rail import PLCRail
from eit_ptlc.unilab_domain.devices.robot import RobotProxy


material: MaterialProxy = device('material')
rail: PLCRail = device('plc_rail')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='1a87a0e4-f57f-5f2f-9496-0bab9e08e74a',
    displayname='地轨-安全移动 (先校验机械臂在安全位再移动) · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def rail_move_safe_operation_view_v2() -> None:
    # [OPERATION rail_move_safe] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=2dfd15d2-1b3f-59a9-ae2b-ffd642e375ed disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='rail_move_safe',
        inputs_json='{"target":1}',
        expected_sha256='bc4b82cfd1909b9768ba57fd4ed1f765b4e31b89fdc9f4250f923291e6395630',
    )
    # [VERIFY comment] 只读来源校验 rail_move_safe@body/0；本视图中静态 disabled。
    # unilab:node_uuid=56290893-05c2-5932-8bb4-2dd953df3951 disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='rail_move_safe',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='cc629ec60964ec74a746185851e52069f3b991388ab52755ebea4f3b92ed1740',
    )
    # [ACTION robot.home_ensure] 来源 rail_move_safe@body/1；原节点 {"action":"robot.home_ensure","args":{"joint_tol_deg":{"lit":2.0},"pos_tol_mm":{"lit":5.0},"rot_tol_deg":{"lit":5.0}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=1106bf39-edcf-54be-a255-45398a281a2f disabled=true
    projected_action_0003 = robot.home_ensure()
    # [VERIFY comment] 只读来源校验 rail_move_safe@body/2；本视图中静态 disabled。
    # unilab:node_uuid=7a2af2ac-1b25-502b-919d-8c8bd393f668 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='rail_move_safe',
        node_path='body/2',
        control_kind='comment',
        expected_sha256='38f90a43c3043b67cd1207e8d94cd7c595a01ab69567c39518284d36ecb68702',
    )
    # [ACTION rail.move] 来源 rail_move_safe@body/3；原节点 {"action":"rail.move","args":{"Rail_Target_Position":{"var":"target"}},"mode":"RUN","op":"call"}
    # unilab:node_uuid=aa4e9483-88bf-59df-9ba1-7ec68a16e51a disabled=true
    projected_action_0005 = rail.move(
        Rail_Target_Position=1,
    )
