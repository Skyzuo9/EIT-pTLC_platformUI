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
    id='plc_develop',
    category=['ptlc', 'develop', 'platformui-proxy'],
    displayname='plc.develop',
    description='PlatformUI plc.develop 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'$ref': 'ptlc_shared_scene',
 'selector': {'kind': 'gltf_subtree',
              'node_index': 393,
              'node_path': 'ST_DEVELOP',
              'root_transform': 'reset_translation',
              'exclude_node_paths': []}},
    metadata={'platformui_device_id': 'plc.develop',
 'platformui_action_namespace': 'develop',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_DEVELOP', 'manifest_section': None}},
)
class PLCDevelop(PlatformUIProxyBase):
    platformui_namespace = 'plc.develop'

    @action(action_name='capture_reference', displayname='展缸-采集参考图', description='执行步骤：板入目标缸后向液位服务开启本次运行的干板参考采集窗口，等待稳定帧生成板专属基线，并返回 ok、has_ref 和耗时。 前置与安全：应在展开注液前、板已就位时调用；只操作上位机/液位服务，不驱动 PLC，超时会主动撤销未完成窗口。 完成与异常：参考图建立成功返回 ok=true；不可达或 timeout_s 到期返回 ok=false供流程升级人工门，通信/服务异常返回 ERROR。 实现核对：eit_ptlc/controller/waterlevel_trigger.py::capture_reference；服务未启用时 bootstrap 返回 ok=false 而非驱动物理设备。')
    async def capture_reference(self, target_tank: int, timeout_s: float = 90.0) -> PlatformActionResult:
        return await self._invoke('develop.capture_reference', {'target_tank': target_tank, 'timeout_s': timeout_s})

    @action(action_name='clean_line', displayname='展缸-清洗管路', description='执行步骤：Develop_L2确定目标缸组后，A20只取得共享泵总线、发送上位机生成的Expand_forward_instructions，按组循环发送/1Q或/2Q；收到泵空闲上升沿后再等待3秒并置Expand_Group_clean_OK。 前置与安全：PLC须处于运行/就绪态，target_tank、配方和泵指令必须有效；该PLC子程序自身不打开目标缸进/排液阀、不启真空，也不按rinse_repeat_count循环，所需流路必须由工艺编排另行保证。 完成与异常：泵空闲并完成3秒收尾后返回DONE；本子程序无阀反馈和显式泵错误分支，泵不空闲或指令链停滞由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Develop_L2 动作码20 → A20_pipeline_清洗管路。')
    async def clean_line(self, target_tank: int, solvent_volume_ml: float = 2.0, solvent_ratio_1: float = 1.0, solvent_ratio_2: float = 0.0, solvent_ratio_3: float = 0.0, solvent_ratio_4: float = 0.0, rinse_repeat_count: int = 1, asp_speed: int | None = None, disp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('develop.clean_line', {'target_tank': target_tank, 'solvent_volume_ml': solvent_volume_ml, 'solvent_ratio_1': solvent_ratio_1, 'solvent_ratio_2': solvent_ratio_2, 'solvent_ratio_3': solvent_ratio_3, 'solvent_ratio_4': solvent_ratio_4, 'rinse_repeat_count': rinse_repeat_count, 'asp_speed': asp_speed, 'disp_speed': disp_speed, 'step_delay': step_delay})

    @action(action_name='drain', displayname='展缸-排液闭环', description='执行步骤：Develop_L2置目标缸Tank_Drain_Enable；独立Develop_TankDrain FSM取得该缸大真空泵票并开排液阀，废液组传感器持续满足drain_duration或达到drain_cap后开吹气，依次完成blow与dry计时，最后关排液/吹气、撤泵票、置Done和Tank_State=98。 前置与安全：PLC须处于运行/就绪态；仅Tank_State为0/40可新启动，10/90以501拒绝，50/55/56允许重挂，98/99幂等完成。缸盖全程不动；该动作非幂等、不自动重发，参数是全局标量，当前只能串行派发。 完成与异常：Tank_State=98/99或Tank_Drain_Done成立后L2返回DONE；急停会关泵票及阀并把在途缸置90，FSM态90映射ErrorCode 502；硬上限只锁存CapHit并继续吹扫，不直接报错。 PLC核对：现役 20260702.project，Application/50_action/Develop_L2 动作码50 + Application/40_Man/Develop_TankDrain/A50_Expand_liquid_discharge_排液。')
    async def drain(self, target_tank: int, drain_duration_s: float = 5.0, drain_cap_s: float = 120.0, blow_s: float = 30.0, dry_duration_s: float = 0.0) -> PlatformActionResult:
        return await self._invoke('develop.drain', {'target_tank': target_tank, 'drain_duration_s': drain_duration_s, 'drain_cap_s': drain_cap_s, 'blow_s': blow_s, 'dry_duration_s': dry_duration_s})

    @action(action_name='fill', displayname='展缸-上液', description='执行步骤：把所选缸进液阀自动输出置TRUE，按Expand_up_liquid_count重复发送上位机生成的Expand_forward_instructions，并按组轮询/1Q或/2Q；全部循环后清除该进液阀并置Expand_up_liquid_OK。 前置与安全：PLC须处于运行/就绪态，缸号1–8、配比、体积和泵指令须先通过上位机校验，目标缸应可接液；PLC不读取进液阀到位反馈。 完成与异常：全部泵循环收到空闲上升沿且进液输出清除后返回DONE；PLC子程序无显式泵/阀错误分支，未完成由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Develop_L2 动作码22 → A22_up_liquid_上液。')
    async def fill(self, target_tank: int, solvent_volume_ml: float = 2.0, solvent_ratio_1: float = 1.0, solvent_ratio_2: float = 0.0, solvent_ratio_3: float = 0.0, solvent_ratio_4: float = 0.0, up_liquid_repeat_count: int = 1, asp_speed: int | None = None, disp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('develop.fill', {'target_tank': target_tank, 'solvent_volume_ml': solvent_volume_ml, 'solvent_ratio_1': solvent_ratio_1, 'solvent_ratio_2': solvent_ratio_2, 'solvent_ratio_3': solvent_ratio_3, 'solvent_ratio_4': solvent_ratio_4, 'up_liquid_repeat_count': up_liquid_repeat_count, 'asp_speed': asp_speed, 'disp_speed': disp_speed, 'step_delay': step_delay})

    @action(action_name='init', displayname='展开工位复位', description='执行步骤：Develop_L2先把1–8号缸换算为组号/组内号；所选缸的气缸、进液、排液、吹气手/自动输出全部清零，再按组向1号或2号注射泵发送Z0,2,2R初始化命令并轮询Q状态。 前置与安全：PLC须处于运行/就绪态，target_tank必须为1–8；初始化只作用于所选缸，不包含机器人放板、缸盖到位或溶剂注入。 完成与异常：收到对应泵空闲上升沿后返回DONE；PLC不等待所清零阀/气缸的反馈，缸号越界在派发器以ErrorCode 102拒绝，泵无响应由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/Develop_L2 动作码10 → A10_init_初始化。')
    async def init(self, target_tank: int) -> PlatformActionResult:
        return await self._invoke('develop.init', {'target_tank': target_tank})

    @action(action_name='plate_extend', displayname='展缸关盖', description='执行步骤：按Expand_Group/Expand_Number选择目标缸，把对应气缸自动输出置TRUE，并持续等待该缸“气缸动点”输入成立。 前置与安全：PLC须处于运行/就绪态；机器人必须已放板并退出缸盖运动区，板件正确落座。本动作不注液、不启动展开计时，也不检查机器人位置。 完成与异常：对应动点反馈成立后返回DONE；缸号越界为102，气缸不到位无独立ErrorCode，由上位机停滞/绝对超时报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Develop_L2 动作码32 → A32_放板缸到动点。')
    async def plate_extend(self, target_tank: int) -> PlatformActionResult:
        return await self._invoke('develop.plate_extend', {'target_tank': target_tank})

    @action(action_name='plate_retract', displayname='展缸开盖(取板)', description='执行步骤：按Expand_Group/Expand_Number选择目标缸，把对应气缸自动输出置FALSE，并持续等待该缸“气缸原点”输入成立。 前置与安全：PLC须处于运行/就绪态；机器人进入前确认气缸运动区无干涉。取板通常在Tank_State=98后调用，但PLC动作码31不检查Tank_State。 完成与异常：对应原点反馈成立后返回DONE；缸号越界在派发器以102拒绝，气缸不到位没有独立ErrorCode，会由上位机停滞/绝对超时报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Develop_L2 动作码31 → A31_放板缸回原点。')
    async def plate_retract(self, target_tank: int) -> PlatformActionResult:
        return await self._invoke('develop.plate_retract', {'target_tank': target_tank})

    @action(action_name='release_tank', displayname='解除展缸占用', description='执行步骤：动作码51只检查所选缸Tank_State；状态为98、兼容99或已为0时，清Tank_Drain_Enable、Tank_Drain_Done并把Tank_State写0，不驱动泵、阀、气缸或缸盖。 前置与安全：PLC须处于运行/就绪态；机器人必须已完全取板且无需继续占用该缸，不得用本动作代替drain。 完成与异常：状态归0后同一扫描返回DONE；其它Tank_State以ErrorCode 511在接受门拒绝或运行态报ERROR，缸号越界为102。 PLC核对：现役 20260702.project，Application/50_action/Develop_L2 动作码51内联状态释放逻辑。')
    async def release_tank(self, target_tank: int) -> PlatformActionResult:
        return await self._invoke('develop.release_tank', {'target_tank': target_tank})

    @action(action_name='rinse_fill', displayname='展缸-润洗注液', description='执行步骤：把所选缸的进液阀、排液阀和气缸自动输出都置TRUE，随后按Expand_rinse_count重复发送Expand_forward_instructions并按组查询/1Q或/2Q；最后等待5秒并置Expand_Group_clean_OK，阀和气缸保持当前输出供后续抽吸承接。 前置与安全：PLC须处于运行/就绪态，目标缸与泵指令必须有效；本动作不启动大真空泵，标准编排应随后显式开真空并调用rinse_suction。PLC不检查三类执行件的到位反馈。 完成与异常：指定泵循环完成并等待5秒后返回DONE；DONE不代表阀或气缸到位，PLC子程序无显式设备错误分支，泵不空闲由上位机报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/Develop_L2 动作码21 → A21_rinse_润洗展缸。')
    async def rinse_fill(self, target_tank: int, solvent_volume_ml: float = 2.0, solvent_ratio_1: float = 1.0, solvent_ratio_2: float = 0.0, solvent_ratio_3: float = 0.0, solvent_ratio_4: float = 0.0, rinse_repeat_count: int = 1, asp_speed: int | None = None, disp_speed: int | None = None, step_delay: int | None = None) -> PlatformActionResult:
        return await self._invoke('develop.rinse_fill', {'target_tank': target_tank, 'solvent_volume_ml': solvent_volume_ml, 'solvent_ratio_1': solvent_ratio_1, 'solvent_ratio_2': solvent_ratio_2, 'solvent_ratio_3': solvent_ratio_3, 'solvent_ratio_4': solvent_ratio_4, 'rinse_repeat_count': rinse_repeat_count, 'asp_speed': asp_speed, 'disp_speed': disp_speed, 'step_delay': step_delay})

    @action(action_name='rinse_suction', displayname='展缸-润洗抽吸', description='执行步骤：承接A21已打开的排液路径；先等待settle_s秒沉降，再要求对应展缸组的废液检测传感器连续TRUE empty_s秒，随后关闭进液阀、打开吹气阀blow_s秒，最后关闭排液阀和吹气阀。 前置与安全：PLC须处于运行/就绪态，target_tank为1–8；调用前必须由上位机pump.vacuum_on，正常和异常路径都必须关闭真空。PLC只读组级废液传感器，不直接确认真空泵运行。 完成与异常：吹气结束、排液/吹气命令关闭后返回DONE；cap_s秒内废液传感器未连续满足判ErrorCode 402，其余阀反馈不参与完成条件，停滞由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/Develop_L2 动作码26 → A26_rinse_suction；四个时长经Tank_Suction_*通道直透，改值免下装。')
    async def rinse_suction(self, target_tank: int, settle_s: float = 3.0, empty_s: float = 10.0, blow_s: float = 30.0, cap_s: float = 120.0) -> PlatformActionResult:
        return await self._invoke('develop.rinse_suction', {'target_tank': target_tank, 'settle_s': settle_s, 'empty_s': empty_s, 'blow_s': blow_s, 'cap_s': cap_s})

    @action(action_name='wait_level', displayname='展缸-液位等待', description='执行步骤：上位机按目标缸轮询液位快照，对 front_percent 与 t1/t2 通道阈值比较并按 confirm_n 连续命中去抖（按 observed_at 去重，只认不同检测拍），同时监测数据陈旧和展开硬上限。 前置与安全：通道须有本次运行参考图和有效标定；前沿未进入/front_none 继续等待，掉流、陈旧、无参考、整区判湿或配置故障进入 degraded，不直接操作 PLC 或真空。 完成与异常：命中返回 reached，检测降级返回 degraded，达到硬上限返回 hard_cap，三者均以 DONE结果供流程分支；服务异常才返回 ERROR。 实现核对：eit_ptlc/controller/waterlevel_trigger.py::wait_level，经 runtime/bootstrap.py 注入 ActionExecutor 的 host 方法表。')
    async def wait_level(self, target_tank: int, stage: str, staleness_s: float = 30.0, hard_cap_s: float = 3600.0, confirm_n: int = 2) -> PlatformActionResult:
        return await self._invoke('develop.wait_level', {'target_tank': target_tank, 'stage': stage, 'staleness_s': staleness_s, 'hard_cap_s': hard_cap_s, 'confirm_n': confirm_n})

    @action(
        action_name='develop_prepare',
        displayname='展开-准备',
        description='PlatformUI operation develop_prepare 的类型化 UniLab Action；逐字段参数会编码后交给既有 VM，工位资源锁与控制流语义不变。',
    )
    async def develop_prepare(
        self,
        tank: int = 1,
        solvent_ratio_1: float = 1,
        solvent_ratio_2: float = 0,
        solvent_ratio_3: float = 0,
        solvent_ratio_4: float = 0,
        tank_rinse_volume_ml: float = 10,
        develop_volume_ml: float = 20,
        rinse_repeat_count: int = 2,
        up_liquid_repeat_count: int = 3,
        tank_asp_speed: int = 300,
        tank_disp_speed: int = 300,
        tank_suction_empty_s: float = 10.0,
        tank_suction_cap_s: float = 120.0,
        timeout_s: float = 3600.0,
    ) -> PlatformOperationResult:
        """Run develop_prepare through the unchanged PlatformUI operation VM.

        Args:
            tank[目标缸号 1-8]: 目标缸号 1-8
            solvent_ratio_1[溶剂1权重]: 溶剂1配比权重; 与溶剂2-4共同归一化, 润洗/正式上液共用
            solvent_ratio_2[溶剂2权重]: 溶剂2配比权重
            solvent_ratio_3[溶剂3权重]: 溶剂3配比权重
            solvent_ratio_4[溶剂4权重]: 溶剂4配比权重
            tank_rinse_volume_ml[润洗液量 (mL)]: 润洗展缸单趟液量 (mL); × rinse_repeat_count 为总润洗量 (当前 10 × 2 = 20 mL)。 名字不可退回 rinse_volume_ml —— 上样 sampling_execute 已占用该名 (点样针润洗), 旋钮覆盖按 变量名寻址, 同名会在 ptlc_full_v2 里互相遮蔽并跨站串值
            develop_volume_ml[正式展开剂液量 (mL)]: 正式展开剂单趟液量 (mL); × up_liquid_repeat_count 为缸内总液量 (当前 20 × 3 = 60 mL)
            rinse_repeat_count[润洗次数]: 润洗注液重复次数; 第 1 轮顶掉管路上次残留, 第 2 轮起才真正润缸
            up_liquid_repeat_count[正式上液次数]: 正式上液重复次数; 单趟受注射器 25 mL 量程限制, 总液量靠趟数凑
            tank_asp_speed[吸液泵速 (mL/min)]: 展缸泵吸液速度 V (DT 半步/s, 240 半步=1mL, 300=75mL/min); 润洗注液/正式上液共用。 名字须带 tank_ 前缀 —— 上样 sampling_prepare 已占用 asp_speed, 同名会在 ptlc_full_v2 里跨站串值
            tank_disp_speed[打液泵速 (mL/min)]: 展缸泵打液速度 V; 与吸速独立, 润洗注液/正式上液共用
            tank_suction_empty_s[走空判据 (s)]: 润洗抽吸走空判据 (s); 直透 PLC Tank_Suction_Empty_S。名字须带 tank_ 前缀 —— 旋钮覆盖按变量名寻址, 无前缀会在 ptlc_full_v2 里与其它工位同名旋钮互相遮蔽
            tank_suction_cap_s[抽吸超时 (s)]: 润洗抽吸超时窗口 (s); 直透 PLC Tank_Suction_Cap_S。上限锁 120 保证动作 stall_timeout(180) 恒覆盖最坏时长
            timeout_s[运行超时（秒）]: PlatformUI 根 operation 的绝对等待上限。
        """
        return await self._run_typed_station_operation(
            'develop_prepare',
            {
                'tank': tank,
                'solvent_ratio_1': solvent_ratio_1,
                'solvent_ratio_2': solvent_ratio_2,
                'solvent_ratio_3': solvent_ratio_3,
                'solvent_ratio_4': solvent_ratio_4,
                'tank_rinse_volume_ml': tank_rinse_volume_ml,
                'develop_volume_ml': develop_volume_ml,
                'rinse_repeat_count': rinse_repeat_count,
                'up_liquid_repeat_count': up_liquid_repeat_count,
                'tank_asp_speed': tank_asp_speed,
                'tank_disp_speed': tank_disp_speed,
                'tank_suction_empty_s': tank_suction_empty_s,
                'tank_suction_cap_s': tank_suction_cap_s,
            },
            timeout_s=timeout_s,
        )

    @action(
        action_name='pf_s6_develop_wait',
        displayname='5-1 展开等待',
        description='PlatformUI operation pf_s6_develop_wait 的类型化 UniLab Action；逐字段参数会编码后交给既有 VM，工位资源锁与控制流语义不变。',
    )
    async def pf_s6_develop_wait(
        self,
        tank: int = 1,
        auto_drain: bool = True,
        dry_duration_s: float = 0.0,
        timeout_s: float = 3600.0,
    ) -> PlatformOperationResult:
        """Run pf_s6_develop_wait through the unchanged PlatformUI operation VM.

        Args:
            tank[目标缸号 1-8]: 目标缸号 1-8
            auto_drain[自动排液]: 液位自动触发排液 (批量并行默认 true; false=每样品人工HITL门, 流水线会等人)
            dry_duration_s[原位干燥时长(s)]: 排液后原位干燥时长秒 (0=跳过; 直透 PLC Tank_Dry_S; 挥发/氧敏感样品慎开)
            timeout_s[运行超时（秒）]: PlatformUI 根 operation 的绝对等待上限。
        """
        return await self._run_typed_station_operation(
            'pf_s6_develop_wait',
            {
                'tank': tank,
                'auto_drain': auto_drain,
                'dry_duration_s': dry_duration_s,
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


__all__ = ['PLCDevelop']
