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
    id='plc_staginga',
    category=['ptlc', 'staging_a', 'platformui-proxy'],
    displayname='plc.staginga',
    description='PlatformUI plc.staginga 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'$ref': 'ptlc_shared_scene',
 'selector': {'kind': 'gltf_subtree',
              'node_index': 1352,
              'node_path': 'ST_STAGINGA',
              'root_transform': 'reset_translation',
              'exclude_node_paths': ['ST_STAGINGA/收集瓶支架总装-1/INV_STAGING_A',
                                     'ST_STAGINGA/样品瓶支架总装-1/INV_STAGING_B']}},
    metadata={'platformui_device_id': 'plc.staginga',
 'platformui_action_namespace': 'staging_a',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_STAGINGA', 'manifest_section': None}},
)
class PLCStagingA(PlatformUIProxyBase):
    platformui_namespace = 'plc.staginga'

    @action(action_name='locator_a', displayname='中转A-定位气缸目标态', description='执行步骤：把target写入StagingA_LocatorA_Target；StagingA_L2动作码24将“粉末收集器定位自动”直接赋为该值，把Step置99并在同一扫描周期进入DONE。 前置与安全：PLC须处于运行/就绪态；定位前物料正确落座且机器人退出气缸运动区，松开后物料不再受定位约束。PLC不检查这些编排前置。 完成与异常：DONE只表示定位输出已写入，不读取原点/动点反馈，也不生成气缸错误；Reset在运行态会返回INTERRUPTED/ErrorCode 402。 PLC核对：现役 20260702.project，Application/50_action/StagingA_L2 动作码24内联逻辑；PLC_MainPRG已周期调用。')
    async def locator_a(self, target: bool) -> PlatformActionResult:
        return await self._invoke('staging_a.locator_a', {'target': target})

    @action(action_name='locator_b', displayname='中转B-定位气缸目标态', description='执行步骤：把target写入StagingA_LocatorB_Target；StagingA_L2动作码25将“溶液收集瓶定位自动”直接赋为该值，把Step置99并在同一扫描周期进入DONE。 前置与安全：PLC须处于运行/就绪态；中转B不是独立L2工位，气缸由StagingA_L2管理。定位/松开前物料与机器人安全由编排保证。 完成与异常：DONE只表示定位输出已写入，不读取原点/动点反馈，也不生成气缸错误；Reset在运行态会返回INTERRUPTED/ErrorCode 402。 PLC核对：现役 20260702.project，Application/50_action/StagingA_L2 动作码25内联逻辑；PLC_MainPRG已周期调用。')
    async def locator_b(self, target: bool) -> PlatformActionResult:
        return await self._invoke('staging_a.locator_b', {'target': target})


__all__ = ['PLCStagingA']
