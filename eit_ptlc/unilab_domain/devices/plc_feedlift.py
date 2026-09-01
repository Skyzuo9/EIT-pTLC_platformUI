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
    id='plc_feedlift',
    category=['ptlc', 'feedlift', 'platformui-proxy'],
    displayname='plc.feedlift',
    description='PlatformUI plc.feedlift 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'$ref': 'ptlc_shared_scene',
 'selector': {'kind': 'gltf_subtree',
              'node_index': 469,
              'node_path': 'ST_FEEDLIFT',
              'root_transform': 'reset_translation',
              'exclude_node_paths': ['ST_FEEDLIFT/AXIS_AXIS_1Z/CARRIAGE.001/INV_MAGAZINE_FEED_TEMPLATE']}},
    metadata={'platformui_device_id': 'plc.feedlift',
 'platformui_action_namespace': 'feedlift',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_FEEDLIFT', 'manifest_section': None}},
)
class PLCFeedLift(PlatformUIProxyBase):
    platformui_namespace = 'plc.feedlift'

    @action(action_name='calib_record', displayname='板仓-记一组标定样本', description='执行步骤：先用清零位与触发位之差自校验逼近动作确实搜索过，再把（张数，触发位）追加进该板仓的采样表，对全部样本做最小二乘拟合得出空仓基准位与堆叠节距，最后落盘到 config/feedlift_calib.json。 前置与安全：必须在同一次测量的清零动作与逼近动作都返回 DONE 之后调用，且两个位置取自同一次测量；张数须是此刻仓内的实际张数，空仓填零，这个数直接决定节距精度。纯算与落盘动作，不下发任何 PLC 指令、不驱动轴运动。 完成与异常：返回本组样本、逼近位移、样本组数与拟合结果；逼近位移不大于零点零二毫米时返回 ERROR，说明逼近动作是幂等直通、读数为陈旧值，拒绝采用。拟合定不出直线或节距落在一点五到四毫米之外时保留样本但不写入标定常数，由 reject_reason 说明原因——样本是现场事实，坏常数才是要挡住的东西。 实现核对：runtime/bootstrap.py::_feedlift_calib_record 调 controller/feedlift_count.py 的 fit_calib 与 save_calib。')
    async def calib_record(self, magazine: str, plates: int, z_clear: float, z_trigger: float) -> PlatformActionResult:
        return await self._invoke('feedlift.calib_record', {'magazine': magazine, 'plates': plates, 'z_clear': z_clear, 'z_trigger': z_trigger})

    @action(action_name='debug_check_photoelectric_edge', displayname='DEBUG-光电边沿确认诊断', description='执行步骤：按axis读取光电开关1或2，不发任何JOG或定位命令；仅检查该输入是否连续200毫秒等于expected_final。配置仍预下发搜索边界，但PLC动作码91不读取这些边界。 前置与安全：PLC须处于运行/就绪态且仅DEBUG模式；这是无运动的稳定态读数诊断，不是边沿搜索，不能用来验证搜索窗口或伺服运动。 完成与异常：输入连续200毫秒符合期望后返回DONE；axis不是1/2为ErrorCode 306；输入一直不符时PLC不会主动报错，而由上位机超时结束。 PLC核对：现役 20260702.project，Application/50_action/FeedLift_L2 动作码91 → A91_endcheck。')
    async def debug_check_photoelectric_edge(self, axis: int, expected_final: bool) -> PlatformActionResult:
        return await self._invoke('feedlift.debug_check_photoelectric_edge', {'axis': axis, 'expected_final': expected_final})

    @action(action_name='feed_clear', displayname='上料-降轴至光电消失', description='执行步骤：Start前写入1Z搜索上下边界；PLC先等待1Z已回零、玻璃升降接近开关1（仓底有板）且Alarm.0为FALSE（上料机构有料），随后仅向下JOG搜索“玻璃升降光电开关1=FALSE”，停轴并连续稳定300毫秒；抖回TRUE时最多两次、每次最多向下2毫米重捕获。 前置与安全：PLC须处于运行/就绪态，SearchLow必须小于SearchHigh，机器人退出升降区；本动作不使用绝对定位，只在下界内JOG。⚠ 本动作仍受物料互锁约束，空仓时跑不通：门里的接近开关1是仓底的有无板检测、Alarm.0是“上料机构无物料”，两者在空仓时都不满足。相比feed_raise只少了上料进料传感器一项，并非“不检查有无料”——标定因此不能采空仓那一组，改用不同的已知非零张数即可（空仓基准位是拟合截距，由这些组外推得出）。 完成与异常：光电FALSE稳定300毫秒后返回DONE；窗口非法为303，前置10秒未满足为301（空仓是最常见成因），到下界或两次重捕获失败为307，轴动作停滞由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/FeedLift_L2 动作码13 → A13_feed_clear。')
    async def feed_clear(self) -> PlatformActionResult:
        return await self._invoke('feedlift.feed_clear', {})

    @action(action_name='feed_lower', displayname='上料-降轴5mm让位', description='执行步骤：把1Z相对目标固定写为-5.0毫米并置xMoveRel，等待bReMoveDone后撤销相对移动命令。 前置与安全：PLC须处于运行/就绪态；机器人吸盘应已可靠吸住最上层玻璃并保持取料姿态。PLC动作内不检查吸盘、光电或剩余轴行程。 完成与异常：1Z相对移动完成位成立后返回DONE；PLC无显式伺服/限位错误分支，未完成由上位机停滞/绝对超时报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/FeedLift_L2 动作码12 → A12_feed_lower。')
    async def feed_lower(self) -> PlatformActionResult:
        return await self._invoke('feedlift.feed_lower', {})

    @action(action_name='feed_raise', displayname='上料-升轴至取料光电', description='执行步骤：Start前写入1Z搜索上下边界；PLC先等待1Z已回零、接近开关1、上料进料传感器且Alarm.0为FALSE，随后仅向上JOG搜索“玻璃升降光电开关1=TRUE”，停轴并连续稳定300毫秒；抖动时最多两次、每次最多向上2毫米重捕获。 前置与安全：PLC须处于运行/就绪态，SearchLow必须小于SearchHigh，机器人退出升降区；本动作不使用绝对定位，只在上界内JOG。 完成与异常：光电TRUE稳定300毫秒后返回DONE；窗口非法为303，前置10秒未满足为301，到上界或两次重捕获失败为304，轴动作停滞由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/FeedLift_L2 动作码11 → A11_feed_raise。')
    async def feed_raise(self) -> PlatformActionResult:
        return await self._invoke('feedlift.feed_raise', {})

    @action(action_name='init', displayname='板仓复位', description='执行步骤：清 1Z/2Z 的四个 jog 命令位与两轴相对移动命令位，随后校验 1Z、2Z 均已回零。 前置与安全：PLC须处于运行/就绪态；本动作不产生任何轴运动，只清残留命令位与读状态，故不受物料互锁约束，空仓也能跑。清位是必要的——搜索类动作被 L2_Reset 中止时 jog 位会停在 TRUE，feed_lower 中途被中止时 xMoveRel 也留 TRUE。 完成与异常：双轴 bHomed 均为 TRUE 即返回 DONE；5秒内未满足为 308。⚠ 308 只能由人工在 HMI 按【一键回原点】解决——1Z/2Z 回零通道不对上位机开放，本动作不会也不能自行回零。 PLC核对：现役 20260702.project，Application/50_action/FeedLift_L2 动作码10 → A10_init_初始化。')
    async def init(self) -> PlatformActionResult:
        return await self._invoke('feedlift.init', {})

    @action(action_name='preflight', displayname='板仓-发动作前可见前置自检', description='执行步骤：读输入字节 IX8 与 PLC_Ready，按板仓取出对应的玻璃升降接近开关与光电开关状态（IX8 的 bit5/bit6 为接近开关1/2，bit3/bit4 为光电开关1/2），与 PLC 侧光电搜索动作的前置门比对。 前置与安全：纯读动作，不下发任何 PLC 指令、不驱动轴运动，任何时刻可调用。判定按 IX8 裸位等于 1 即满足，与 PLC 的 ST 判据逐位一致，不做常开常闭折算——物料对账那边按有料无料折算极性是另一回事，不可一并"修正"。 完成与异常：可见前置全部满足时返回各开关现值与 ok 为真；接近开关为 FALSE 或 PLC_Ready 为 FALSE 时返回 ERROR 并点名是哪一项，避免白等十秒的 301/302；IX8 读回空值时报错而不当作全零。轴是否已回零与 Alarm 是否为 FALSE 上位机读不到，一律列进 unobservable，故 ok 为真不代表随后的动作一定能跑。 实现核对：runtime/bootstrap.py::_feedlift_preflight 读 PLC 镜像并调用 controller/feedlift_count.py::preflight_gate。')
    async def preflight(self, magazine: str) -> PlatformActionResult:
        return await self._invoke('feedlift.preflight', {'magazine': magazine})

    @action(action_name='probe_stack', displayname='板仓-行程盘点', description='执行步骤：上位机读取对应升降轴实际位置，按标定的空仓基准位与堆叠节距换算仓内板数；若调用方给出前一次探测位置，则再由两次位置之差推算这一段实际取走的张数；给了同次测量的清零位时先校验逼近动作确实搜索过；reconcile 为真时把实测张数写回物料账本并留痕。 前置与安全：必须在 feed_raise、unload_ready 或 unload_bury 返回 DONE 之后调用（轴已停稳 300 毫秒）；该板仓须已完成空仓与满仓两步标定；reconcile 只能置于板尚未移动的那次探测。这是纯读动作，不下发任何 PLC 指令、不驱动轴运动。 完成与异常：读数落在整数张位置且实取张数符合预期时返回板数、残差与预警标志；未标定、残差越界、换算张数超量程、实取张数与预期不符（双张/空吸）一律返回 ERROR 停机。给了清零位而逼近位移不大于零点零二毫米时同样返回 ERROR——那说明逼近是幂等直通、读数为上次停轴的陈旧值。账实不符不报错，以实测为准校正账本并留痕。 实现核对：runtime/bootstrap.py::_feedlift_probe 读 PLC 镜像并调用 controller/feedlift_count.py::evaluate。')
    async def probe_stack(self, magazine: str, z_prev: float | None = None, expect_taken: int | None = None, reconcile: bool = False, z_clear: float | None = None) -> PlatformActionResult:
        return await self._invoke('feedlift.probe_stack', {'magazine': magazine, 'z_prev': z_prev, 'expect_taken': expect_taken, 'reconcile': reconcile, 'z_clear': z_clear})

    @action(action_name='read_pos', displayname='板仓-读升降轴位置', description='执行步骤：按板仓取对应轴号（feed 为 1Z，waste 为 2Z），读 FeedLift_1Z/2Z_ActPos 并四舍五入到三位小数返回。 前置与安全：纯读动作，不下发任何 PLC 指令、不驱动轴运动。节点由 PLC_MainPRG 每扫描无条件镜像 fActPos，故任何时刻可读；但只有在光电搜索动作返回 DONE 之后（轴已停稳 300 毫秒）读到的值才对应板堆高度，其余时刻数值有效但无意义。 完成与异常：返回板仓、轴号与位置毫米值；板仓标识非法或节点未下装时返回 ERROR。本动作只读不判，换算与判定见 feedlift.probe_stack。 实现核对：runtime/bootstrap.py::_feedlift_read_pos 调 PlcController.read_feedlift_pos。')
    async def read_pos(self, magazine: str) -> PlatformActionResult:
        return await self._invoke('feedlift.read_pos', {'magazine': magazine})

    @action(action_name='unload_bury', displayname='下料-埋料至光电消失', description='执行步骤：PLC等待2Z已回零、玻璃升降接近开关2（仓底有板）且Alarm.1为FALSE（下料机构未满），然后仅向下JOG搜索“光电开关2=FALSE”，停轴稳定300毫秒；抖回TRUE时最多两次、每次最多向下2毫米重捕获。 前置与安全：PLC须处于运行/就绪态，SearchLow小于SearchHigh；废玻璃已释放且机器人退出2Z区域。动作不反向上扫。⚠ 门里的接近开关2是仓底的有无板检测，空仓时为FALSE，故空仓跑不通——标定不要采空仓那一组，改用不同的已知非零张数即可。 完成与异常：光电FALSE稳定300毫秒后返回DONE；窗口非法为303，前置10秒未满足为302（空仓是最常见成因），到下界或重捕获失败为305，其余停滞由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/FeedLift_L2 动作码22 → A22_unload_bury。')
    async def unload_bury(self) -> PlatformActionResult:
        return await self._invoke('feedlift.unload_bury', {})

    @action(action_name='unload_ready', displayname='下料-到放废料位', description='执行步骤：Start前写入2Z窗口；PLC等待2Z已回零、下料出料传感器且Alarm.1为FALSE，然后仅向上JOG搜索“光电开关2=TRUE”，停轴稳定300毫秒；抖动时最多两次、每次最多向上2毫米重捕获。 前置与安全：PLC须处于运行/就绪态，SearchLow小于SearchHigh，机器人不得进入2Z搜索区；动作不向下反搜。 完成与异常：光电TRUE稳定300毫秒后返回DONE；窗口非法为303，前置10秒未满足为302，到上界或重捕获失败为305，其余停滞由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/FeedLift_L2 动作码21 → A21_unload_ready。')
    async def unload_ready(self) -> PlatformActionResult:
        return await self._invoke('feedlift.unload_ready', {})

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


__all__ = ['PLCFeedLift']
