from __future__ import annotations

from unilabos.workflow.authoring import device, group, workflow
from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.robot import RobotProxy
from eit_ptlc.workflows.rail_move_safe_operation_view_v2 import (
    rail_move_safe_operation_view_v2,
)
from eit_ptlc.workflows.robot_tool_put_operation_view_v2 import (
    robot_tool_put_operation_view_v2,
)
from eit_ptlc.workflows.robot_tool_pick_operation_view_v2 import (
    robot_tool_pick_operation_view_v2,
)


material: MaterialProxy = device('material')
robot: RobotProxy = device('robot')


@workflow(
    workflow_uuid='4784411c-74fc-5482-ba70-770e96e20972',
    displayname='智能换刀保证 · Operation 分层视图 v2',
    description=(
        '仅展示当前 operation 的直接 action、控制边界和 run_script 子工作流。'
        '实体 action 与控制标记静态 disabled；run_script 协调节点可展开。'
        '循环 body 不展开，也不会提交 PlatformUI operation。'
    ),
)
def robot_tool_ensure_operation_view_v2() -> None:
    # [OPERATION robot_tool_ensure] 只读调用合同：展示格式化参数并校验源 operation；本视图中静态 disabled。
    # unilab:node_uuid=7f16a5d3-fa4a-5e19-92ab-7adb23e9187a disabled=true
    operation_call_0001 = material.review_operation_call_v2(
        operation_name='robot_tool_ensure',
        inputs_json='{"needed":1}',
        expected_sha256='6b6bda1f25882a99cd0f23aaebca91afdf061c781cc9a09c0bedd5015a18cb88',
    )
    # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/0；本视图中静态 disabled。
    # unilab:node_uuid=30739582-885e-5627-acfe-09a40ec039de disabled=true
    projected_control_0002 = material.review_control_node_v1(
        operation_name='robot_tool_ensure',
        node_path='body/0',
        control_kind='comment',
        expected_sha256='d809e1de31eaaae6a28b91dfdc9f8587e53c48ce272668a1d7794e15c68d86f9',
    )
    # [ACTION robot.query] 来源 robot_tool_ensure@body/1；原节点 {"action":"robot.query","assign":{"var":"fb"},"mode":"RUN","op":"call"}
    # unilab:node_uuid=8b0c97ad-fe15-55aa-a1ca-98ea53e99569 disabled=true
    projected_action_0003 = robot.query()
    # [VERIFY assign] 只读来源校验 robot_tool_ensure@body/2；本视图中静态 disabled。
    # unilab:node_uuid=f00bb5c9-4c28-5f90-9d60-b285234b2008 disabled=true
    projected_control_0004 = material.review_control_node_v1(
        operation_name='robot_tool_ensure',
        node_path='body/2',
        control_kind='assign',
        expected_sha256='0a8bed4ab1ed21eab44aa30c3cdc41f38a8147534c728fa885ef1da0ba3237c7',
    )
    # [CONTROL if] 来源 robot_tool_ensure@body/3；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"var":"needed"}},"op":"if","then":[{"op":"comment","text":"当前 != 目标: 先安全移轨到工具站(位4=工具位), 再卸当前 (非空腕才卸) 再装目标"},{"op":"comment","text":"卸吸盘前真空守卫: 当前是吸盘(1)且仍有真空 -> 默认吸着板子, 任何移动前报错中止"},{"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"r...
    # unilab:node_uuid=de7f85f8-6d02-544f-8b33-0d26091ba743
    with group(name='◇ IF 条件（PlatformUI 判定）'):
        # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3；本视图中静态 disabled。
        # unilab:node_uuid=b423e5fb-c155-56e8-bfa4-d5a47c8634e7 disabled=true
        projected_control_0005 = material.review_control_node_v1(
            operation_name='robot_tool_ensure',
            node_path='body/3',
            control_kind='if',
            expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
        )
        # unilab:node_uuid=f0fe9c70-abbb-5085-a465-e60f8a1330ed
        with group(name='THEN（互斥分支）'):
            # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/0；本视图中静态 disabled。
            # unilab:node_uuid=82723082-0c44-5237-a29a-d03cebd31192 disabled=true
            projected_control_0006 = material.review_control_node_v1(
                operation_name='robot_tool_ensure',
                node_path='body/3/then/0',
                control_kind='comment',
                expected_sha256='f1c1621fc9a3af0fead9abddfba4acc6d628c4e07f02d5e1d6e79342f780d4b5',
            )
            # [VERIFY comment] 只读来源校验 robot_tool_ensure@body/3/then/1；本视图中静态 disabled。
            # unilab:node_uuid=bc9e7eb5-6851-5fc9-a9d0-7d7714c32850 disabled=true
            projected_control_0007 = material.review_control_node_v1(
                operation_name='robot_tool_ensure',
                node_path='body/3/then/1',
                control_kind='comment',
                expected_sha256='ab6b298fa1974e89ffba98e42a169ccd9b213ac1a03a6723584be2b1be7e6898',
            )
            # [CONTROL if] 来源 robot_tool_ensure@body/3/then/2；原节点 {"cond":{"binop":"and","left":{"binop":"==","left":{"var":"current"},"right":{"lit":1}},"right":{"field":{"field":{"var":"fb"},"name":"tool_state"},"name":"suction_on"}},"op":"if","then":[{"error":"ROBOT_TOOL_SUCTION_HELD","message":{"lit":"吸盘仍有真空(疑似吸着板子), 禁止换刀; 请先确认放板完成"},"op":"raise"}]}
            # unilab:node_uuid=1ee220b2-a646-5b46-be43-dda2e03c9e84
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/2；本视图中静态 disabled。
                # unilab:node_uuid=1c3fda9e-b4c9-5d18-9615-0fd18c946409 disabled=true
                projected_control_0008 = material.review_control_node_v1(
                    operation_name='robot_tool_ensure',
                    node_path='body/3/then/2',
                    control_kind='if',
                    expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                )
                # unilab:node_uuid=12e6ffa8-1962-531a-bb9a-4bd297bbffe4
                with group(name='THEN（互斥分支）'):
                    # [VERIFY raise] 只读来源校验 robot_tool_ensure@body/3/then/2/then/0；本视图中静态 disabled。
                    # unilab:node_uuid=c62851d2-4b5f-5eaf-a044-46aa804b46a3 disabled=true
                    projected_control_0009 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/3/then/2/then/0',
                        control_kind='raise',
                        expected_sha256='8ade635dfc3c21601ac8fa50ba7a168191332f67cbf70e021465f2765df9b23f',
                    )
                # unilab:node_uuid=91846735-d8c3-5d11-9a96-e1d09eb33b1b
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/2；本视图中静态 disabled。
                    # unilab:node_uuid=6d2987fb-6e68-5620-b397-83780f2ee7e7 disabled=true
                    projected_control_0010 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/3/then/2',
                        control_kind='if',
                        expected_sha256='7390368bcb8426a61aa6610074198d61935d04e49d4f0534117f6f868a4307a3',
                    )
            # [SUBWORKFLOW rail_move_safe] 来源 robot_tool_ensure@body/3/then/3；原节点 {"inputs":{"target":{"lit":4}},"op":"run_script","outputs":{},"script":"rail_move_safe"}
            # unilab:node_uuid=e2ae7873-d503-568a-b37c-5d53d7ab6fa2
            nested_operation_0011 = rail_move_safe_operation_view_v2()
            # [CONTROL if] 来源 robot_tool_ensure@body/3/then/4；原节点 {"cond":{"binop":"!=","left":{"var":"current"},"right":{"lit":0}},"op":"if","then":[{"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}]}
            # unilab:node_uuid=74e99297-2903-596a-b043-343505f50556
            with group(name='◇ IF 条件（PlatformUI 判定）'):
                # [VERIFY if] 只读来源校验 robot_tool_ensure@body/3/then/4；本视图中静态 disabled。
                # unilab:node_uuid=0320a19a-cac8-59be-a828-7729bc1321f6 disabled=true
                projected_control_0012 = material.review_control_node_v1(
                    operation_name='robot_tool_ensure',
                    node_path='body/3/then/4',
                    control_kind='if',
                    expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                )
                # unilab:node_uuid=53dba104-033e-5a64-94d3-ca89def163a0
                with group(name='THEN（互斥分支）'):
                    # [SUBWORKFLOW robot_tool_put] 来源 robot_tool_ensure@body/3/then/4/then/0；原节点 {"inputs":{"tool_id":{"var":"current"}},"op":"run_script","outputs":{},"script":"robot_tool_put"}
                    # unilab:node_uuid=d542cef9-327f-53f9-81f0-63204b5b2d23
                    nested_operation_0013 = robot_tool_put_operation_view_v2()
                # unilab:node_uuid=1399e792-d7c0-5872-9428-9ab497bd09d2
                with group(name='ELSE（互斥分支）'):
                    # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3/then/4；本视图中静态 disabled。
                    # unilab:node_uuid=eabbc3d8-30c5-5a3c-85b3-54609edc6003 disabled=true
                    projected_control_0014 = material.review_control_node_v1(
                        operation_name='robot_tool_ensure',
                        node_path='body/3/then/4',
                        control_kind='if',
                        expected_sha256='d5aafcb5dc9295863418e2ee609fdcc82bc9f47b1bcc0832250d2e4a1a7994ef',
                    )
            # [SUBWORKFLOW robot_tool_pick] 来源 robot_tool_ensure@body/3/then/5；原节点 {"inputs":{"tool_id":{"var":"needed"}},"op":"run_script","outputs":{},"script":"robot_tool_pick"}
            # unilab:node_uuid=f5e0b919-db87-5924-bd3a-62e06487c38a
            nested_operation_0015 = robot_tool_pick_operation_view_v2()
        # unilab:node_uuid=1ab50dc2-98e2-5112-9057-b4be9171f930
        with group(name='ELSE（互斥分支）'):
            # [EMPTY ELSE（互斥分支）] 只读来源校验 robot_tool_ensure@body/3；本视图中静态 disabled。
            # unilab:node_uuid=19a044e4-ceb2-5369-b5e3-ff21f70a2e0f disabled=true
            projected_control_0016 = material.review_control_node_v1(
                operation_name='robot_tool_ensure',
                node_path='body/3',
                control_kind='if',
                expected_sha256='2f923dbfed93e3544e356794517629c767f40a4de9de82367f78970c15b56303',
            )
