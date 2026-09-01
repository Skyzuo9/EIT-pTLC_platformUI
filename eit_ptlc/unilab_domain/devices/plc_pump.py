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
    id='plc_pump',
    category=['ptlc', 'pump', 'platformui-proxy'],
    displayname='plc.pump',
    description='PlatformUI plc.pump 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'$ref': 'ptlc_shared_scene',
 'selector': {'kind': 'gltf_subtree',
              'node_index': 774,
              'node_path': 'ST_PUMP',
              'root_transform': 'reset_translation',
              'exclude_node_paths': []}},
    metadata={'platformui_device_id': 'plc.pump',
 'platformui_action_namespace': 'pump',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_PUMP', 'manifest_section': None}},
)
class PLCPump(PlatformUIProxyBase):
    platformui_namespace = 'plc.pump'

    @action(action_name='vacuum_off', displayname='真空泵-关 (资源钩子, 勿直调)', description='执行步骤：Pump_L2动作码20把大真空泵站位[11]置FALSE并立即DONE；PLC_Pump_泵管理重新OR全部站位，仅当[0..11]均为FALSE时才撤销“大真空泵自动”物理输出。 前置与安全：本动作是共享资源 device:vacuum_pump 的 deactivate 钩子，只由资源门在引用计数1->0时调用，编排层与动作目录禁止直调。PLC须处于运行/就绪态；不会清除展缸排液等其它站位，因此共享泵可能继续运行。 完成与异常：DONE只表示站位[11]已清除，不确认物理泵已停；若其它站位残留或通信结果不明确，必须查看站位总线和泵输出，不能仅凭该动作DONE判断停泵。关闭失败时资源门记ERROR并在正常退出路径抛出，提示该设备可能仍在运行。 PLC核对：现役 20260702.project，Application/50_action/Pump_L2 动作码20 → A20_vacuum_off；Application/50_action/PLC_Pump_泵管理负责聚合。')
    async def vacuum_off(self) -> PlatformActionResult:
        return await self._invoke('pump.vacuum_off', {})

    @action(action_name='vacuum_on', displayname='真空泵-开 (资源钩子, 勿直调)', description='执行步骤：Pump_L2动作码10把大真空泵站位[11]置TRUE并立即DONE；PLC_Pump_泵管理每扫描对站位[0..11]做OR，在PLC_Ready、部署状态允许且启动门已重新装载时驱动“大真空泵自动”，再由气缸FB驱动物理输出%QX2.4。 前置与安全：本动作是共享资源 device:vacuum_pump 的 activate 钩子，只由资源门在引用计数0->1时调用，编排层与动作目录禁止直调（直调会绕过计数，把并发流程的真空一起掐掉）。PLC须处于运行/就绪态；该动作不抢占或清除其它站位，维护期间出现的站位请求会被启动门阻止补执行，须全部回FALSE后重新装载。 完成与异常：DONE只表示站位[11]已置位，不读取泵接触器、真空度或物理输出反馈；共享泵可能因其它站位保持运行，物理泵状态须通过设备节点另行监视。开启失败时资源门回滚计数并让持有方运行以失败收口。 PLC核对：现役 20260702.project，Application/50_action/Pump_L2 动作码10 → A10_vacuum_on；Application/50_action/PLC_Pump_泵管理负责聚合。')
    async def vacuum_on(self) -> PlatformActionResult:
        return await self._invoke('pump.vacuum_on', {})


__all__ = ['PLCPump']
