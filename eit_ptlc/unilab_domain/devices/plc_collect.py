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


class PlatformOperationResult(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str


@device(
    id='plc_collect',
    category=['ptlc', 'collect', 'platformui-proxy'],
    displayname='plc.collect',
    description='PlatformUI plc.collect 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'$ref': 'ptlc_shared_scene',
 'selector': {'kind': 'gltf_subtree',
              'node_index': 91,
              'node_path': 'ST_COLLECT',
              'root_transform': 'reset_translation',
              'exclude_node_paths': ['ST_COLLECT/ACTUATOR_COL_EXTEND/样品瓶-2']}},
    metadata={'platformui_device_id': 'plc.collect',
 'platformui_action_namespace': 'collect',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_COLLECT', 'manifest_section': None}},
)
class PLCCollect(PlatformUIProxyBase):
    platformui_namespace = 'plc.collect'

    @action(action_name='bottle_locator', displayname='中转B-瓶板定位气缸目标态', description='执行步骤：这是staging_a.locator_b的兼容别名；把target写入StagingA_LocatorB_Target，经StagingA_L2动作码25直接写“溶液收集瓶定位自动”，同一扫描进入DONE。 前置与安全：PLC须处于运行/就绪态；该气缸不属于Collect工位，新流程应使用staging_a.locator_b。物料和机器人安全位置由编排保证。 完成与异常：DONE只表示目标输出已写入，PLC不读取原点/动点反馈，也不生成气缸错误；物理到位须由外部诊断确认。 PLC核对：现役 20260702.project，Application/50_action/StagingA_L2 动作码25内联逻辑。')
    async def bottle_locator(self, target: bool) -> PlatformActionResult:
        return await self._invoke('collect.bottle_locator', {'target': target})

    @action(action_name='clamp', displayname='收集-夹持气缸夹紧', description='执行步骤：把收集夹持气缸自动输出置TRUE，持续等待“收集平台夹持气缸动点”输入成立。 前置与安全：PLC须处于运行/就绪态；收集器必须正确落座且机器人退出夹具范围。本动作不驱动伸缩、升降或瓶定位气缸。 完成与异常：夹持动点反馈成立后返回DONE；PLC无气缸超时ErrorCode，反馈不成立时由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Collect_L2 动作码21 → A21_夹持夹紧。')
    async def clamp(self) -> PlatformActionResult:
        return await self._invoke('collect.clamp', {})

    @action(action_name='collect', displayname='收集-加液/排液洗脱循环', description='执行步骤：若collect_forward_instructions非空则打开收集进液输出，发送该指令并轮询/3Q；泵空闲后关进液、开排液和正压排液20秒，再等待5秒沉淀；按collect_count重复，最后关闭排液与正压排液。 前置与安全：PLC须处于运行/就绪态；lift_press、瓶存在、收集器夹紧以及泵指令合法由上位机编排保证，A30自身不再次检查这些条件。液体动作非幂等，不自动重发。 完成与异常：全部泵循环与每轮25秒排液/沉淀完成后返回DONE；该PLC子程序没有缺瓶、阀反馈或泵错误分支，泵不空闲/动作停滞由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Collect_L2 动作码30 → A30_collect_收集。')
    async def collect(self, solvent_volume_ml: float = 2.0, liquid_repeat_count: int = 1, asp_speed: int | None = None, disp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('collect.collect', {'solvent_volume_ml': solvent_volume_ml, 'liquid_repeat_count': liquid_repeat_count, 'asp_speed': asp_speed, 'disp_speed': disp_speed, 'step_delay': step_delay})

    @action(action_name='extend', displayname='收集-伸缩气缸伸出', description='执行步骤：只有“推出气缸原点=TRUE且瓶子有无传感器=FALSE”时才把伸缩气缸自动输出置TRUE；随后等待推出气缸动点反馈。 前置与安全：PLC须处于运行/就绪态；收集器应已夹紧、放瓶位必须无瓶，机器人在DONE后才能进入。PLC动作内不检查夹持、升降或下压位置。 完成与异常：推出动点成立后返回DONE；初始条件不满足或气缸不到位时PLC不会主动报错而会停滞，最终由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Collect_L2 动作码22 → A22_伸缩伸出。')
    async def extend(self) -> PlatformActionResult:
        return await self._invoke('collect.extend', {})

    @action(action_name='init', displayname='收集工位复位', description='执行步骤：清除瓶定位、下压、夹持、升降、伸缩、进液、排液和正压排液的手/自动输出；取得泵总线后向3号泵发送/3Z0,2,2R并轮询/3Q。 前置与安全：PLC须处于运行/就绪态，机器人须退出四气缸运动区；初始化不包含机器人放收集器/瓶或中转定位动作。 完成与异常：3号泵空闲且下压、夹持、升降、推出四个原点输入全部成立后返回DONE；PLC没有单独超时ErrorCode，任一反馈不成立时由上位机停滞/绝对超时判TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Collect_L2 动作码10 → A10_init_初始化。')
    async def init(self) -> PlatformActionResult:
        return await self._invoke('collect.init', {})

    @action(action_name='lift_press', displayname='收集-缩回/升降/下压', description='执行步骤：先把伸缩自动输出置FALSE并等待推出气缸原点；若瓶存在则把升降自动输出置TRUE，等待升降动点后再把下压自动输出置TRUE并立即返回DONE。 前置与安全：PLC须处于运行/就绪态；瓶必须已放好且机器人退出。本动作不操作中转B定位气缸；PLC只在伸缩已回原点时检查瓶传感器。 完成与异常：伸缩原点和升降动点已确认，但DONE只表示下压命令已置位，不等待下压到位；原点时缺瓶为ErrorCode 201，伸缩/升降不到位则由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/Collect_L2 动作码23 → A23_缩回升降下压。')
    async def lift_press(self) -> PlatformActionResult:
        return await self._invoke('collect.lift_press', {})

    @action(action_name='release_clamp', displayname='松开收集夹爪', description='执行步骤：把收集夹持气缸自动输出置FALSE，并持续等待收集平台夹持气缸原点反馈。 前置与安全：PLC须处于运行/就绪态；retract应已完成，泵、升降和下压机构处于安全状态；松开后收集器不再受夹具约束。 完成与异常：夹持原点成立后返回DONE；PLC无独立超时ErrorCode，不到位由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Collect_L2 动作码43 → A43_松夹持。')
    async def release_clamp(self) -> PlatformActionResult:
        return await self._invoke('collect.release_clamp', {})

    @action(action_name='retract', displayname='收回伸缩台', description='执行步骤：把收集伸缩气缸自动输出置FALSE，并持续等待推出气缸原点反馈。 前置与安全：PLC须处于运行/就绪态；瓶应已取走且机器人退出伸缩运动路径，本动作不松开收集器夹持。 完成与异常：推出气缸原点成立后返回DONE；PLC无独立超时ErrorCode，不到位由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Collect_L2 动作码42 → A42_伸缩缩回。')
    async def retract(self) -> PlatformActionResult:
        return await self._invoke('collect.retract', {})

    @action(action_name='transport_extend', displayname='伸出到转运位', description='执行步骤：依次把下压自动输出置FALSE并等待下压原点，把升降自动输出置FALSE并等待升降原点，再把伸缩自动输出置TRUE并等待推出气缸动点。 前置与安全：PLC须处于运行/就绪态；泵和阀动作必须已结束，机器人只能在推出动点DONE后进入。本动作不操作中转B定位气缸。 完成与异常：三个气缸反馈按序成立后返回DONE；PLC无独立气缸超时ErrorCode，任一反馈不成立时由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Collect_L2 动作码41 → A41_复位伸出。')
    async def transport_extend(self) -> PlatformActionResult:
        return await self._invoke('collect.transport_extend', {})

    @action(
        action_name='collect_execute',
        displayname='收集-执行',
        description='PlatformUI operation collect_execute 的类型化 UniLab Action；逐字段参数会编码后交给既有 VM，工位资源锁与控制流语义不变。',
    )
    async def collect_execute(
        self,
        solvent_volume_ml: float = 0.1,
        liquid_repeat_count: int = 1,
        timeout_s: float = 3600.0,
    ) -> PlatformOperationResult:
        """Run collect_execute through the unchanged PlatformUI operation VM.

        Args:
            solvent_volume_ml[单次洗脱溶剂体积 mL]: 单次洗脱溶剂体积 mL
            liquid_repeat_count[洗脱循环次数]: 洗脱循环次数
            timeout_s[运行超时（秒）]: PlatformUI 根 operation 的绝对等待上限。
        """
        return await self._run_typed_station_operation(
            'collect_execute',
            {
                'solvent_volume_ml': solvent_volume_ml,
                'liquid_repeat_count': liquid_repeat_count,
            },
            timeout_s=timeout_s,
        )

    @action(
        action_name='run_station_operation_v4',
        displayname='运行 PlatformUI 工位流程',
        description='一次提交不含机器人和地轨的现有 PlatformUI 根 operation；运动根会被硬拒绝。',
    )
    async def run_station_operation_v4(
        self, operation_name: str, inputs_json: str = '{}', timeout_s: float = 3600.0
    ) -> PlatformOperationResult:
        return await self._run_station_operation(
            operation_name, inputs_json, timeout_s=timeout_s
        )


__all__ = ['PLCCollect']
