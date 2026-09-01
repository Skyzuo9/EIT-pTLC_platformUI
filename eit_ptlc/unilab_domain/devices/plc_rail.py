from __future__ import annotations

from typing import TypedDict

from unilabos.registry.decorators import action, device

from eit_ptlc.unilab_domain.devices.base import PlatformUIProxyBase


class PlatformActionResult(TypedDict):
    action: str
    request_id: str
    command_id: str
    status: str
    accepted: bool
    result_json: str


@device(
    id='plc_rail',
    category=['ptlc', 'rail', 'platformui-proxy'],
    displayname='plc.rail',
    description='PlatformUI plc.rail 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'$ref': 'ptlc_shared_scene',
 'selector': {'kind': 'gltf_subtree',
              'node_index': 1133,
              'node_path': 'ST_RAIL',
              'root_transform': 'reset_translation',
              'exclude_node_paths': ['ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT']}},
    metadata={'platformui_device_id': 'plc.rail',
 'platformui_action_namespace': 'rail',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_RAIL', 'manifest_section': None}},
)
class PLCRail(PlatformUIProxyBase):
    platformui_namespace = 'plc.rail'

    @action(action_name='ensure', displayname='地轨去指定站位', description='执行步骤：读取地轨实际毫米位置与目标槽；在容差内直接幂等返回，超差时先断言机械臂已在P1再复用 rail.move 管线下发目标槽，auto_rail关闭时为空操作。 前置与安全：本原语只在原子入口(require_anchor P1 之后)调用，故补移时机械臂必在P1；断言式校验不自动回零，不在位即判定为编排缺入口移轨而拒绝，随后仍经单写者、回读和 L2 派发；同毫米但槽号不同也按位置容差判断。 完成与异常：已在位或补移到位返回 DONE；实际位不可读、未回零、需补移但机械臂已离开P1、伺服或 L2 结果不明确返回拒绝/ERROR/TIMEOUT。 实现核对：ActionExecutor._exec_rail_ensure/_ensure_rail；容差为5毫米，未回零或实际位读取失败时拒绝补移。')
    async def ensure(self, Rail_Target_Position: int) -> PlatformActionResult:
        return await self._invoke('rail.ensure', {'Rail_Target_Position': Rail_Target_Position})

    @action(action_name='move', displayname='地轨-移动到位', description='执行步骤：上位机先执行P1安全锚点门并把槽号1–6写入Rail_Target_Position；PLC读取Rail_Pos_Target[槽号]，要求毫米目标>0且≤3000，写入11Y绝对目标并置xMoveAbs，等待bAbMoveDone后撤销移动命令。 前置与安全：PLC须处于运行/就绪态；P1硬门由上位机在下发前执行，PLC Rail_L2本身不读取机器人姿态。Rail_Pos_Target必须已由PC同步，机械臂伸展时禁止移轨，物理动作不自动重发。 完成与异常：11Y的bAbMoveDone成立后返回DONE；非法动作码/槽号为ErrorCode 101，目标为0或超3000为102。现役PLC代码未接地轨伺服报警分支，轴不完成时由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Rail_L2 动作码10；PLC_MainPRG已周期调用该POU。')
    async def move(self, Rail_Target_Position: int) -> PlatformActionResult:
        return await self._invoke('rail.move', {'Rail_Target_Position': Rail_Target_Position})


__all__ = ['PLCRail']
