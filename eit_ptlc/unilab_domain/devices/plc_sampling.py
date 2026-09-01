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
    id='plc_sampling',
    category=['ptlc', 'sampling', 'platformui-proxy'],
    displayname='plc.sampling',
    description='PlatformUI plc.sampling 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'$ref': 'ptlc_shared_scene',
 'selector': {'kind': 'gltf_subtree',
              'node_index': 1290,
              'node_path': 'ST_SAMPLING',
              'root_transform': 'reset_translation',
              'exclude_node_paths': []}},
    metadata={'platformui_device_id': 'plc.sampling',
 'platformui_action_namespace': 'sampling',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_SAMPLING', 'manifest_section': None}},
)
class PLCSampling(PlatformUIProxyBase):
    platformui_namespace = 'plc.sampling'

    @action(action_name='aspirate', displayname='上样-吸取样品', description='执行步骤：5Z先升到0；若指令[2]非空则在此原位空气中发送该绝对吸气指令并经/4Q确认空闲后释放泵总线（建立针尖气隔断），随后4X/3Y才移到主机下发孔位，再把5Z降到HMI position[2]；PLC从指令[1]解析P增量，查询/4?得到真实活塞位，校验当前位置+增量≤6000后发送相对回抽指令，/4Q空闲后抬5Z到0。 前置与安全：PLC须处于运行/就绪态；孔板标定、4X/3Y目标和P指令必须有效，针路无碰撞。气隔断必须在移向孔位之前吸入——吸气前针尖内为满液，带液移动途中的挂壁滴液会滴进样品孔稀释样品；指令[2]为绝对A{gap}，故润洗轮（进入时活塞已在A{gap}）为零位移，天然幂等。该吸液为非幂等物理动作，不自动重发。 完成与异常：回抽完成且5Z安全抬起后返回DONE；P指令无效或行程越界为ErrorCode 463，/4?连续5次无有效帧为464，错误路径同样先抬针；轴/泵停滞由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码50 → A50_absorb_吸收液体（step 2/3 为气隔断段）。')
    async def aspirate(self, plate_spec: str, plate_no: str, well: str, sample_volume_ml: float = 5.0, air_gap_ml: float | None = None, asp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('sampling.aspirate', {'plate_spec': plate_spec, 'plate_no': plate_no, 'well': well, 'sample_volume_ml': sample_volume_ml, 'air_gap_ml': air_gap_ml, 'asp_speed': asp_speed, 'step_delay': step_delay})

    @action(action_name='clean', displayname='上样-重清洗', description='执行步骤：先把5Z升到0，再把4X移到Sampling_4X_WashTarget、6X移到清洗位并下降5Z；重清洗模式每轮依次发送指令1（三通点样头侧）、再次发送指令1（三通上样针侧）和指令2，每段均用/4Q确认4号泵空闲。 前置与安全：PLC须处于运行/就绪态，清洗目标和泵指令须已由上位机写入；针头与排液端应在清洗/废液安全位置。该液体动作非幂等，不自动重发，停滞预算为120秒。 完成与异常：完成Sampling_clean_count轮后复位三通到上样针侧并返回DONE；该PLC子程序没有显式bActionError分支，泵无响应、轴不到位等由上位机停滞/绝对超时报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码20 → A20_clean_清洗（Sampling_clean_mode=0）。')
    async def clean(self, wash_volume_ml: float = 25.0, cleaning_count: int = 3, asp_speed: int | None = None, disp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('sampling.clean', {'wash_volume_ml': wash_volume_ml, 'cleaning_count': cleaning_count, 'asp_speed': asp_speed, 'disp_speed': disp_speed, 'step_delay': step_delay})

    @action(action_name='flush', displayname='上样-充液润洗', description='执行步骤：与clean共用动作码20；轴先进入相同清洗位，Sampling_clean_mode=1时在三通为上样针侧发送指令1，/4Q确认泵空闲后切到点样头侧发送指令2，第二次确认空闲后把三通复位到上样针侧。 前置与安全：PLC须处于运行/就绪态；上样针必须在废液/清洗位、点样头在清洗位，充液润洗两条DT指令及三段总体积须已通过上位机校验。 完成与异常：两条指令均收到泵空闲确认且三通命令复位后返回DONE；PLC不读取三通到位反馈，也无显式泵错误分支，泵或轴不完成时由上位机超时报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码20 → A20_clean_清洗（Sampling_clean_mode=1）。')
    async def flush(self, flush_volume_ml: float = 17.0, outer_wash_volume_ml: float = 5.0, spot_head_volume_ml: float = 3.0, asp_speed: int | None = None, flush_disp_speed: int | None = None, spot_head_disp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('sampling.flush', {'flush_volume_ml': flush_volume_ml, 'outer_wash_volume_ml': outer_wash_volume_ml, 'spot_head_volume_ml': spot_head_volume_ml, 'asp_speed': asp_speed, 'flush_disp_speed': flush_disp_speed, 'spot_head_disp_speed': spot_head_disp_speed, 'step_delay': step_delay})

    @action(action_name='init', displayname='上样工位复位', description='执行步骤：清除上样定位、三通和吹气的手/自动输出及各动作状态，先把5Z移到0，再把4X、6X、7Y移到0；随后向4号注射泵发送 /4Z0,1,1R 初始化命令并轮询 /4Q。 前置与安全：PLC须处于运行态、PLC_Ready成立且不在部署维护态；机器人须退出轴运动区。本动作只把3Y目标写为0，并未命令3Y移动，也不包含机器人放板或样品吸取。 完成与异常：4X、5Z、6X、7Y到位且泵空闲上升沿到达后返回DONE；本子程序没有单独的伺服/泵错误分支，轴或泵不完成时由上位机停滞/绝对超时判定，启动门失败为ErrorCode 190。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码10 → A10_init_初始化。')
    async def init(self) -> PlatformActionResult:
        return await self._invoke('sampling.init', {})

    @action(action_name='place_axis', displayname='上样-移轴至放板位', description='执行步骤：把点样7Y轴绝对目标设为HMI_点样轴7Y.position[1]，置位xMoveAbs并等待bAbMoveDone，随后撤销移动命令。 前置与安全：PLC须处于运行/就绪态；定位夹具应让位，机器人不得伸入7Y运动区域。本动作不操作机器人，也不校验机器人位置。 完成与异常：7Y的bAbMoveDone成立后返回DONE；PLC动作内没有伺服报警分支，未到位时由L2停滞/绝对超时返回TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码31 → A31_放板移轴。')
    async def place_axis(self) -> PlatformActionResult:
        return await self._invoke('sampling.place_axis', {})

    @action(action_name='place_locate', displayname='上样-定位夹紧', description='执行步骤：把“上样定位自动”置TRUE，同时置Sampling_Place_materials_OK为TRUE，并在同一扫描周期返回DONE。 前置与安全：PLC须处于运行/就绪态；板必须正确落座、机器人已退出夹具范围且7Y已在放板位。PLC本动作不检查这些编排前置。 完成与异常：DONE仅表示定位输出命令已写入，不表示气缸已到夹紧反馈；PLC子程序不等待到位也不产生气缸错误，物理到位必须由设备联锁/外部诊断确认。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码32 → A32_放板定位。')
    async def place_locate(self) -> PlatformActionResult:
        return await self._invoke('sampling.place_locate', {})

    @action(action_name='place_release', displayname='上样-定位松开', description='执行步骤：把“上样定位自动”置FALSE，并在同一扫描周期返回DONE，为后续机器人取板发出松开命令。 前置与安全：PLC须处于运行/就绪态；工艺运动应已停止且取板路径安全，松开后板件不再由夹具约束。 完成与异常：DONE仅表示松开输出已写入，不表示原位反馈成立；PLC子程序不等待气缸反馈，机器人进入前必须由编排/设备信号另行确认安全。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码33 → A33_定位松开。')
    async def place_release(self) -> PlatformActionResult:
        return await self._invoke('sampling.place_release', {})

    @action(action_name='prep', displayname='上样-蓄驱动液', description='执行步骤：先把5Z抬到0使针尖离液悬空；取得共享泵总线后只发送Sampling_prep_instructions[1]（自口3绝对回抽至A{n}），随后循环/4Q直到4号泵空闲，回抽量和泵速由上位机生成该DT指令。 前置与安全：PLC须处于运行/就绪态，充液润洗应已完成使管路满液，针尖须在空气中（本动作自带抬针）。液柱不可压缩，一次回抽在两端同时成立：泵腔侧吸入等量清洗液（点样驱动液储备），针尖侧同时形成等量空气段；现行过阀排空点样流程按后者即“气隔断”语义消费该参数，隔离样品与共管清洗液柱。 完成与异常：5Z到0且收到泵空闲上升沿后释放泵总线并返回DONE；PLC无显式泵/伺服错误分支，不完成时由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码40 → A40_prep_上样准备。')
    async def prep(self, air_buffer_ml: float = 0.2, asp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('sampling.prep', {'air_buffer_ml': air_buffer_ml, 'asp_speed': asp_speed, 'step_delay': step_delay})

    @action(action_name='rinse_mix', displayname='上样-原孔润洗混匀', description='执行步骤：5Z升到0后4X/3Y回到主机下发的原样品孔，再下降5Z；三通保持上样针侧，依次执行“泵腔余量回打并回A0”“口1吸润洗液后经口3全部打入原孔”两条命令；随后抬5Z到0在空气中执行“口3吸气隔断至A{gap}”，再下降5Z执行“口3吸至A{gap+mix}并回打A{gap}”混匀命令，第四条按count循环，最后抬针。 前置与安全：PLC须处于运行/就绪态；只用于点样轮之间且仍指向同一原样品孔，四条命令非空、count为1–20。Reset会先停三轴/关闭三通并在泵总线空闲时发送/4T，不自动重发。 完成与异常：每条命令均经/4Q空闲确认、全部循环结束且5Z抬到0后返回DONE；终态活塞停在A{gap}(气隔断保留在针尖端)；参数/指令非法为ErrorCode 466且不可重试，泵或轴停滞由600秒预算判TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码55 → A55_润洗吹打混匀(四条指令+抬针吸气版)。')
    async def rinse_mix(self, plate_spec: str, plate_no: str, well: str, rinse_volume_ml: float, mix_volume_ml: float, mix_count: int, air_gap_ml: float = 0.2, asp_speed: int | None = None, disp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('sampling.rinse_mix', {'plate_spec': plate_spec, 'plate_no': plate_no, 'well': well, 'rinse_volume_ml': rinse_volume_ml, 'mix_volume_ml': mix_volume_ml, 'mix_count': mix_count, 'air_gap_ml': air_gap_ml, 'asp_speed': asp_speed, 'disp_speed': disp_speed, 'step_delay': step_delay})

    @action(action_name='spot', displayname='上样-点样(旧单次)', description='执行步骤：6X/7Y先到主机写入的Spot起点/Y目标，三通切到点样头并执行dispense指令1；泵空闲后开启吹气、发送指令2并让6X扫到终点，泵未空闲时6X在起止点往返；收尾把6X/7Y移到各自HMI position[1]并松开上样定位。 前置与安全：PLC须处于运行/就绪态，Spot目标和两条DT指令须已写入；这是旧兼容链路，当前prep保液/P相对吸液工艺应使用spot_band_layer。PLC不检查板件夹紧或机器人位置。 完成与异常：泵空闲、6X完成扫线、6X/7Y回清洗位并关闭三通/吹气后返回DONE；该子程序无显式设备错误分支，泵或轴不完成由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码60 → A60_spray_点样。')
    async def spot(self, ref_spot: str, sample_volume_ml: float = 5.0, asp_speed: int | None = None, spot_disp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('sampling.spot', {'ref_spot': ref_spot, 'sample_volume_ml': sample_volume_ml, 'asp_speed': asp_speed, 'spot_disp_speed': spot_disp_speed, 'step_delay': step_delay})

    @action(action_name='spot_band_layer', displayname='上样-单条带点样+吹干', description='执行步骤：6X/7Y到Spot起点/Y目标后，开启点样头三通和吹气，发送一程Sampling_band_run_instruction并按当前方向液体扫线；到端点立即发/4T，同时以干燥速度往返dry_cycles次并并行查询/4?活塞位，未到end_position+5则反向开始下一程，最多60程；结束后带气回6X/7Y清洗位并关闭输出。 前置与安全：PLC须处于运行/就绪态；板已夹紧，Spot几何、液体/干燥速度、干燥次数和活塞终点须已写入且在上位机范围内。每次只处理一个条带/一层，非幂等，不自动重发。 完成与异常：活塞达到目标、扫线/吹干和清洗位收尾完成后返回DONE；超过60程为ErrorCode 462，/4?连续5次无有效帧为465并停轴关气关阀，其他轴/泵停滞由600秒预算报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码62 → A62_单条带点样。')
    async def spot_band_layer(self, ref_spot: str, x_start: float | None = None, x_end: float | None = None, y_height: float | None = None, spot_disp_speed: int | None = None, spot_speed_mm_s: float = 5.0, dry_speed_mm_s: float = 20.0, dry_cycles: int = 1, step_delay: int | None = None, spot_end_position_ml: float | None = None) -> PlatformActionResult:
        return await self._invoke('sampling.spot_band_layer', {'ref_spot': ref_spot, 'x_start': x_start, 'x_end': x_end, 'y_height': y_height, 'spot_disp_speed': spot_disp_speed, 'spot_speed_mm_s': spot_speed_mm_s, 'dry_speed_mm_s': dry_speed_mm_s, 'dry_cycles': dry_cycles, 'step_delay': step_delay, 'spot_end_position_ml': spot_end_position_ml})

    @action(action_name='spray_axis', displayname='上样-移轴至点样位', description='执行步骤：把点样7Y绝对目标设为HMI_点样轴7Y.position[2]，置位xMoveAbs，等待bAbMoveDone后撤销移动命令。 前置与安全：PLC须处于运行/就绪态；硅胶板应已定位夹紧且机器人已退出工位，PLC本动作不检查这些编排前置。 完成与异常：7Y到位位成立后返回DONE；PLC无显式伺服报警分支，未到位由L2停滞/绝对超时报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Sampling_L2 动作码61 → A61_喷涂移轴。')
    async def spray_axis(self) -> PlatformActionResult:
        return await self._invoke('sampling.spray_axis', {})

    @action(
        action_name='sampling_prepare',
        displayname='上样-准备',
        description='PlatformUI operation sampling_prepare 的类型化 UniLab Action；逐字段参数会编码后交给既有 VM，工位资源锁与控制流语义不变。',
    )
    async def sampling_prepare(
        self,
        flush_volume_ml: float = 17.0,
        outer_wash_volume_ml: float = 5.0,
        spot_head_volume_ml: float = 3.0,
        asp_speed: int = 250,
        flush_disp_speed: int = 300,
        spot_head_disp_speed: int = 100,
        step_delay: int = 1500,
        timeout_s: float = 3600.0,
    ) -> PlatformOperationResult:
        """Run sampling_prepare through the unchanged PlatformUI operation VM.

        Args:
            flush_volume_ml[上样流路充液体积 (mL)]: 上样流路充液体积 (mL); 泵→三通15.7+针1.1≈16.8 的 1.01×
            outer_wash_volume_ml[针外壁清洗体积 (mL)]: 针外壁清洗体积 (mL)
            spot_head_volume_ml[点样头清洗体积 (mL)]: 点样头清洗体积 (mL)
            asp_speed[吸液速度 V]: 吸液速度 V (DT, 半步/s)
            flush_disp_speed[充液/外壁打速 V]: 充液/外壁打速 V (偏高冲刷贴壁气泡)
            spot_head_disp_speed[点样头打速 V]: 点样头打速 V
            step_delay[步间延时 (ms)]: 步间延时 M (ms)
            timeout_s[运行超时（秒）]: PlatformUI 根 operation 的绝对等待上限。
        """
        return await self._run_typed_station_operation(
            'sampling_prepare',
            {
                'flush_volume_ml': flush_volume_ml,
                'outer_wash_volume_ml': outer_wash_volume_ml,
                'spot_head_volume_ml': spot_head_volume_ml,
                'asp_speed': asp_speed,
                'flush_disp_speed': flush_disp_speed,
                'spot_head_disp_speed': spot_head_disp_speed,
                'step_delay': step_delay,
            },
            timeout_s=timeout_s,
        )

    @action(
        action_name='sampling_execute',
        displayname='上样-执行',
        description='PlatformUI operation sampling_execute 的类型化 UniLab Action；逐字段参数会编码后交给既有 VM，工位资源锁与控制流语义不变。',
    )
    async def sampling_execute(
        self,
        plate_spec: str = '4×6',
        plate_no: str = '1',
        well: str = 'A1',
        spot_x_start: float | None = None,
        spot_x_end: float | None = None,
        spot_y_height: float | None = None,
        sample_volume_ml: float = 2,
        dry_cycles: int = 1,
        spot_speed_mm_s: float = 40,
        dry_speed_mm_s: float = 20,
        spot_disp_speed: int = 6,
        over_aspirate_ml: float = 1.5,
        air_gap_ml: float = 0.2,
        rinse_rounds: int = 1,
        rinse_volume_ml: float = 3,
        mix_volume_ml: float = 1.5,
        mix_count: int = 3,
        timeout_s: float = 3600.0,
    ) -> PlatformOperationResult:
        """Run sampling_execute through the unchanged PlatformUI operation VM.

        Args:
            plate_spec[吸样孔板规格]: 上样吸液孔板规格
            plate_no[吸样盘位号]: 上样吸液盘位号
            well[吸样孔位]: 上样吸液孔位
            spot_x_start[点样X起点]: 点样X起点 (缺省=示教基准)
            spot_x_end[点样X终点]: 点样X终点 (缺省=示教基准)
            spot_y_height[点样Y高度]: 点样Y高度 (缺省=示教基准)
            sample_volume_ml[孔内样品体积(mL)]: 孔内实际装样体积 (mL); 吸取按抽干计, 点样推送量=本值+喷出冗余
            dry_cycles[每程吹气往复趟数(1趟=来回一遍)]: 每程喷涂后吹气往复趟数 (1趟=来回一遍)
            spot_speed_mm_s[喷涂扫线速度(mm/s)]: 喷涂扫线速度 (mm/s)
            dry_speed_mm_s[吹气扫线速度(mm/s)]: 吹气扫线速度 (mm/s)
            spot_disp_speed[供液泵速(mL/min)]: 条带供液泵速度 (底层 DT V 1..500; 界面 mL/min, 步进0.25)
            over_aspirate_ml[排空余量(mL, >1.125)]: 排空余量E (mL); 必须大于针流路死体积1.125, 多出的部分成为每轮点样起始空喷段
            air_gap_ml[气隔断(mL)]: 气隔断G (mL); 首轮由 prep 建立, 润洗轮由 A55 抬针吸入
            rinse_rounds[润洗回收轮数]: 润洗回收轮数 (0=只点一轮不回收; 每轮=润洗混匀+再吸样+再点样)
            rinse_volume_ml[润洗液体积(mL)]: 每轮润洗液体积 (mL); A55 的[1]已把针流路重新填满液, 故本值全量入孔
            mix_volume_ml[单次吹打体积(mL)]: 每轮单次吹打体积 (mL, 应不大于净润洗量)
            mix_count[吹打次数]: 每轮吹打次数
            timeout_s[运行超时（秒）]: PlatformUI 根 operation 的绝对等待上限。
        """
        return await self._run_typed_station_operation(
            'sampling_execute',
            {
                'plate_spec': plate_spec,
                'plate_no': plate_no,
                'well': well,
                'spot_x_start': spot_x_start,
                'spot_x_end': spot_x_end,
                'spot_y_height': spot_y_height,
                'sample_volume_ml': sample_volume_ml,
                'dry_cycles': dry_cycles,
                'spot_speed_mm_s': spot_speed_mm_s,
                'dry_speed_mm_s': dry_speed_mm_s,
                'spot_disp_speed': spot_disp_speed,
                'over_aspirate_ml': over_aspirate_ml,
                'air_gap_ml': air_gap_ml,
                'rinse_rounds': rinse_rounds,
                'rinse_volume_ml': rinse_volume_ml,
                'mix_volume_ml': mix_volume_ml,
                'mix_count': mix_count,
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


__all__ = ['PLCSampling']
