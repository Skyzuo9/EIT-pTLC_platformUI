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
    id='plc_photoscrape',
    category=['ptlc', 'photoscrape', 'platformui-proxy'],
    displayname='plc.photoscrape',
    description='PlatformUI plc.photoscrape 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'$ref': 'ptlc_shared_scene',
 'selector': {'kind': 'gltf_subtree',
              'node_index': 735,
              'node_path': 'ST_PHOTOSCRAPE',
              'root_transform': 'reset_translation',
              'exclude_node_paths': []}},
    metadata={'platformui_device_id': 'plc.photoscrape',
 'platformui_action_namespace': 'photoscrape',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_PHOTOSCRAPE', 'manifest_section': None}},
)
class PLCPhotoScrape(PlatformUIProxyBase):
    platformui_namespace = 'plc.photoscrape'

    @action(action_name='align_home', displayname='对位-结束回零', description='执行步骤：先要求遮光上位，再用绝对移动把10Z移到0、9X移到335毫米停放位、8Y移到0；各轴按顺序等待bAbMoveDone，不执行MC_Home。 前置与安全：PLC须处于运行/就绪态且遮光上位，机器人退出三轴区域；9X的“回零”实际是335毫米工位停放位，不是机床零点。 完成与异常：三段绝对移动完成后返回DONE；遮光初始不上位为ErrorCode 425，轴不完成没有显式错误分支，由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码43内联align_home。')
    async def align_home(self) -> PlatformActionResult:
        return await self._invoke('photoscrape.align_home', {})

    @action(action_name='align_move', displayname='对位-移动XY', description='执行步骤：把x_mm/y_mm写入对位目标；PLC要求10Z实际位置<6且遮光气缸上位，将目标经K/O帧变换后校验板区窗，再以40毫米/秒移动9X和8Y，完成后恢复原速度并停在目标处。 前置与安全：现役工程中ALIGN_X/Y_WIN_MIN=0、MAX=-1，软限位窗为空集，所以当前任何XY目标都会被拒绝，禁止按可用动作编排；现场测量并受控更新窗口/帧变换前不能运动。 完成与异常：当前预期结果为ErrorCode 422；此外Z门失败为421、遮光不上位为425。完成条件虽已实现为双轴bAbMoveDone，但只有校准常量后才可能到达。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码42内联align_move；已确认空集常量。')
    async def align_move(self, x_mm: float, y_mm: float) -> PlatformActionResult:
        return await self._invoke('photoscrape.align_move', {'x_mm': x_mm, 'y_mm': y_mm})

    @action(action_name='align_readout', displayname='对位-读数回显', description='执行步骤：上位机读取9X/8Y/10Z实际位置和当前 gcode 配置，计算实读相对原点角的偏差，并生成建议 plate_origin 新值与可直接用于人工门的格式化文本；不写回配置。 前置与安全：对应实际位置节点必须已导出并可读；这是纯读 host 动作，不下发 PLC L2、轴运动或配置修改。 完成与异常：成功返回三轴实读、偏差、建议值和文本；节点未下装、读取或配置解析失败返回 ERROR。 实现核对：runtime/bootstrap.py::_align_readout 读取 PLC 三轴镜像并调用 controller/align_check.py::build_align_readout。')
    async def align_readout(self) -> PlatformActionResult:
        return await self._invoke('photoscrape.align_readout', {})

    @action(action_name='align_z', displayname='对位-Z升降(0~18mm)', description='执行步骤：把z_mm写入目标；PLC实际接受连续范围0–18毫米而非“两档”，以5毫米/秒移动10Z并在完成后恢复原速度。z=0可直接抬起，z>0前检查当前9X/8Y位于板区窗。 前置与安全：现役工程的XY板区窗为空集，因此任何z>0下降请求都会被拒绝；目前只允许z=0安全抬升。现场标定并受控更新窗口前不得用于下降检查。 完成与异常：z<0或z>18为ErrorCode 421，当前z>0因空集窗为424；z=0到位可返回DONE，轴不到位由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码44内联align_z；已确认0–18范围和空集窗口。')
    async def align_z(self, z_mm: float) -> PlatformActionResult:
        return await self._invoke('photoscrape.align_z', {'z_mm': z_mm})

    @action(action_name='analyze', displayname='视觉-识别条带', description='执行步骤：读取 before/after 图像，按 config.vision 基线和本次可选覆盖执行板姿态矫正、差分/条带识别与评分，落盘 case、summary.json 和标注产物并返回 band_ids。 前置与安全：两张图及样品ID必须有效；这是纯视觉计算，不下发 PLC，识别参数覆盖只作用于本次调用。 完成与异常：识别完成返回 summary_path、case_dir和谱带列表，无谱带作为可分支结果处理；图像、算法或落盘失败返回 ERROR。 实现核对：bootstrap注册的视觉analyze方法，经 ActionExecutor._exec_vision 校验参数并异步执行。')
    async def analyze(self, sample_id: str, before_path: str, after_path: str, image_plate_orientation: str | None = None, auto_rectify_tilt: bool | None = None, rectify_min_angle_deg: float | None = None, min_row_score: float | None = None, image_plate_rotation_deg: float | None = None) -> PlatformActionResult:
        return await self._invoke('photoscrape.analyze', {'sample_id': sample_id, 'before_path': before_path, 'after_path': after_path, 'image_plate_orientation': image_plate_orientation, 'auto_rectify_tilt': auto_rectify_tilt, 'rectify_min_angle_deg': rectify_min_angle_deg, 'min_row_score': min_row_score, 'image_plate_rotation_deg': image_plate_rotation_deg})

    @action(action_name='cam_photohome', displayname='相机回拍照位', description='执行步骤：清除遮光自动输出，等待遮光上位输入后把拍照8Y绝对目标设为0，置位xMoveAbs并等待bAbMoveDone。 前置与安全：PLC须处于运行/就绪态；相机曝光/保存已结束，机器人不得进入遮光和8Y运动区。 完成与异常：遮光上位且8Y绝对到0后返回DONE；PLC无独立气缸/伺服错误分支，不到位由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码35 → A35_cam_回零。')
    async def cam_photohome(self) -> PlatformActionResult:
        return await self._invoke('photoscrape.cam_photohome', {})

    @action(action_name='cam_photopos', displayname='拍照-相机就位+遮光下', description='执行步骤：上位机先把ref_8y点位写入Photo_8Y_Target；PLC仅在遮光上位输入成立时移动8Y到该目标，到位后置遮光自动输出TRUE并等待遮光下位输入。 前置与安全：PLC须处于运行/就绪态；板件应已定位/下压，点位有效且机器人退出相机区域。本动作不触发相机曝光。 完成与异常：8Y到位且遮光下位反馈成立后返回DONE；遮光初始不上位、轴或气缸不到位时无独立ErrorCode，由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码34 → A34_cam_相机位。')
    async def cam_photopos(self, ref_8y: str) -> PlatformActionResult:
        return await self._invoke('photoscrape.cam_photopos', {'ref_8y': ref_8y})

    @action(action_name='cam_x335', displayname='让位-刮板X到放板位335', description='执行步骤：把刮板9X绝对目标固定写为335毫米，置位xMoveAbs，等待bAbMoveDone后撤销移动命令。 前置与安全：PLC须处于运行/就绪态；定位、下压和刀头应处于让位状态，机器人不得在9X运动期间进入工位。PLC动作内不检查这些前置。 完成与异常：9X到位位成立后返回DONE；PLC无显式伺服报警分支，未到位由上位机停滞/绝对超时报告TIMEOUT。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码31 → A31_cam_移轴335。')
    async def cam_x335(self) -> PlatformActionResult:
        return await self._invoke('photoscrape.cam_x335', {})

    @action(action_name='capture', displayname='拍照-触发相机采集', description='执行步骤：上位机按 profile 合并曝光、增益等本次覆盖参数，触发相机采集一帧，并按 sample_id/save_dir/filename 保存图像后返回实际文件路径。 前置与安全：应夹在 cam_photopos DONE 与 cam_photohome 之间，相机已连接且保存目录可写；本动作不移动工位轴。 完成与异常：图像采集并落盘成功返回 DONE；相机超时、参数非法或文件保存失败返回 ERROR。 实现核对：ActionExecutor._exec_camera 分离控制参数与相机覆盖后调用 CameraController.capture。')
    async def capture(self, sample_id: str, save_dir: str, filename: str = 'after.jpg', profile: str = '', exposure_time: float | None = None, gain: float | None = None) -> PlatformActionResult:
        return await self._invoke('photoscrape.capture', {'sample_id': sample_id, 'save_dir': save_dir, 'filename': filename, 'profile': profile, 'exposure_time': exposure_time, 'gain': gain})

    @action(action_name='cnc_path', displayname='视觉-计算刮取路径', description='执行步骤：读取视觉 summary 和选定 band，按实时 gcode 标定、strategy 与 keep_ratio 生成最多400点的刮取/收集四数组、进给、pass_count 和逐层 pass_z_list；placeholder=true 时生成0 pass安全占位。 前置与安全：正常路径必须提供有效 summary_path 和 band_id；这是纯计算 vision 动作，不写 PLC，输出仍需经 plc_write 回读确认后才能刮取。 完成与异常：合法路径返回数组和逐层Z列表；视觉结果缺失、谱带无效、标定或路径生成失败返回 ERROR。 实现核对：eit_ptlc/controller/cnc_path.py::generate_cnc_path，经 ActionExecutor._exec_vision 异步派发。')
    async def cnc_path(self, summary_path: str, band_id: str, strategy: str | None = None, keep_ratio: float | None = None, placeholder: bool = False) -> PlatformActionResult:
        return await self._invoke('photoscrape.cnc_path', {'summary_path': summary_path, 'band_id': band_id, 'strategy': strategy, 'keep_ratio': keep_ratio, 'placeholder': placeholder})

    @action(action_name='init', displayname='拍照工位复位', description='执行步骤：清除真空、无刷电机、定位、粉末收集器定位、遮光、旋转和下压的手/自动输出；撤销三轴移动命令，依次把10Z移到0、9X移到335，确认遮光气缸上位后把8Y移到0。 前置与安全：PLC须处于运行/就绪态，机器人和刀头工作区无干涉；本动作不触发相机、视觉或CNC。遮光输出清零后必须实际到上位，否则流程停在8Y移动前。 完成与异常：10Z=0、9X=335、遮光上位且8Y=0后返回DONE；其它被清零执行件不读取反馈，PLC无显式初始化错误分支，未到位由上位机超时判定。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码10 → A10_init_初始化。')
    async def init(self) -> PlatformActionResult:
        return await self._invoke('photoscrape.init', {})

    @action(action_name='locate_cylinder', displayname='装夹-定位气缸目标态(夹板)', description='执行步骤：把clamped写入PhotoScrape_CamLocate_Target；PLC将“刮板拍照定位气缸自动”直接赋为该值，并在同一扫描周期返回DONE。 前置与安全：PLC须处于运行/就绪态；夹紧前板件正确落座且机器人退出，松开后板件不再受定位约束。PLC不检查物料或机器人位置。 完成与异常：DONE只表示目标输出已写入，不表示原点/动点反馈成立；PLC不读取定位气缸反馈，也不生成气缸错误。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码32 → A32_cam_定位。')
    async def locate_cylinder(self, clamped: bool) -> PlatformActionResult:
        return await self._invoke('photoscrape.locate_cylinder', {'clamped': clamped})

    @action(action_name='press_cylinder', displayname='压紧/松开收集器', description='执行步骤：把pressed写入PhotoScrape_CamPress_Target；TRUE时置下压自动输出并立即DONE，FALSE时清输出并等待“下压气缸上位”后DONE。 前置与安全：PLC须处于运行/就绪态；下压前板和接粉收集器已就位且机器人退出。释放不能替代scrape_finish。 完成与异常：释放方向确认上位反馈；下压方向的DONE只表示输出已置位，不等待下位反馈。释放不到位由上位机超时，下压方向PLC不提供到位错误。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码33 → A33_cam_下压。')
    async def press_cylinder(self, pressed: bool) -> PlatformActionResult:
        return await self._invoke('photoscrape.press_cylinder', {'pressed': pressed})

    @action(action_name='retr_stoprot', displayname='翻料-旋转气缸复位(取桶后)', description='执行步骤：把刮板拍照旋转气缸自动输出置FALSE，并在同一扫描周期返回DONE。 前置与安全：PLC须处于运行/就绪态；刮取和翻料已结束。由于PLC不等待旋转气缸反馈，机器人不能仅凭该DONE立即进入，必须另行确认机构已让位。 完成与异常：DONE只表示停止/复位命令已写入，不表示原点反馈；该子程序不生成气缸错误。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码52 → A52_取料停旋转。')
    async def retr_stoprot(self) -> PlatformActionResult:
        return await self._invoke('photoscrape.retr_stoprot', {})

    @action(action_name='scrape', displayname='刮取-单层(刮粉+收粉)', description='执行步骤：PLC把刮板拍照真空阀与吸粉无刷电机同时置TRUE并置CNC启动；实际路径、进给和g_pass_z由既有PLC_CNC/SoftMotion逻辑消费，A40只持续等待内部CNC完成信号，成立后撤销CNC启动。 前置与安全：PLC须处于运行/就绪态；板/接粉夹具已压紧，接粉桶定位气缸已由staging_a.locator_a定位，路径数组、切深和进给已由前置写动作回读确认，刀具区域安全。非幂等且L2 Step静默，不自动重发。 完成与异常：收到CNC完成后返回DONE并保留真空与电机，供后续pass或finish承接；A40没有读取CNC错误码的分支，CNC不完成由900秒停滞预算报告TIMEOUT。中止在跑的插补须脉冲PhotoScrape_L2_Reset（PLC_MainPRG闸门块据此置CNC停止并撤CNC启动），上位机terminate已自动执行。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码40 → A40_scrape_刮取；2026-07-26补回移植时遗漏的无刷电机开启行（真空阀%QX7.2只是通断，吸力源是无刷电机%QX7.3，缺它则刮取无吸力导致粉末飞溅）。')
    async def scrape(self) -> PlatformActionResult:
        return await self._invoke('photoscrape.scrape', {})

    @action(action_name='scrape_finish', displayname='刮取-收尾(关吸粉+翻料倒粉)', description='执行步骤：把刮板拍照真空自动和无刷电机自动清FALSE，把旋转气缸自动置TRUE，并在同一扫描周期返回DONE。 前置与安全：PLC须处于运行/就绪态；所有计划pass已完成或由受控异常路径决定收尾。本动作不释放定位/下压，也不检查翻料区是否有机器人。 完成与异常：DONE只表示三个输出命令已写入，不等待真空关闭、无刷电机停止或旋转气缸到位反馈；物理收尾须由后续流程/设备信号确认。 PLC核对：现役 20260702.project，Application/50_action/PhotoScrape_L2 动作码41 → A41_scrape_收尾。')
    async def scrape_finish(self) -> PlatformActionResult:
        return await self._invoke('photoscrape.scrape_finish', {})

    @action(action_name='scraped_overlay', displayname='视觉-刮后对账叠加', description='执行步骤：读取刮后照片和下发候选 summary，把照片回放到同一归一化板坐标，并叠加实际下发的刮取路径生成 scraped_annotated.png 供“计划与刮后结果”对账。 前置与安全：summary_path、scraped_path及其标定上下文必须可读；这是刮后哨兵计算，不驱动 PLC、机器人或相机。 完成与异常：成功返回 ok和标注图路径；文件/标定/渲染失败以 ok=false结果返回供流程记录，不应触发物理动作重试。 实现核对：eit_ptlc/controller/scrape_reconcile.py::scraped_overlay，经 ActionExecutor._exec_vision 派发。')
    async def scraped_overlay(self, summary_path: str, scraped_path: str) -> PlatformActionResult:
        return await self._invoke('photoscrape.scraped_overlay', {'summary_path': summary_path, 'scraped_path': scraped_path})

    @action(action_name='wait_rot', displayname='翻料-等旋转气缸到位', description='执行步骤：按 poll 间隔轮询输入字节 IX9，按位取刮板拍照旋转气缸的两个到位信号（bit7 为动点即已翻倒，bit6 为原点即刮取位），直到 target 指定的那一位成立或超过 timeout_s 为止，返回是否到位、两位现值与实际耗时。 前置与安全：纯读动作，不下发任何 PLC 指令、不驱动气缸或轴，任何时刻可调用。IX9 是共享输入字节，bit0/bit1 是上样料架检测，必须按位取不可整字节比较。本动作只确认气缸到位，不确认粉末是否已落入桶内。 完成与异常：到位返回 ok 为真并附耗时；超时或 IX9 读回空值返回 ok 为假并记 WARNING，但一律不抛错——翻料未完成既不影响板子也不影响标定数值，而在收尾这一步抛错会把已完成的标定判成中止、生产侧让板卡在压头下。IX9 读回空值按读不到处理而不当作全零，因为全零恰好也是两个到位位都未到的故障态会指错方向。默认超时六秒对齐 PLC 气缸功能块自身的五秒超时，超过该时长 PLC 侧应已置 cyinderAlarm 的第十三位，但该字未暴露成节点故上位机看不到。 实现核对：runtime/bootstrap.py::_photoscrape_wait_rot 读 IX9 并调用 controller/photoscrape_rot.py::wait_rot；位号常量 _IX9_ROT_EXTEND_BIT/_IX9_ROT_HOME_BIT 须经真机核对（气缸动作.xml 的 cylinder_14 接线与同文件其它气缸相反）。')
    async def wait_rot(self, target: str | None = None, timeout_s: float | None = None) -> PlatformActionResult:
        return await self._invoke('photoscrape.wait_rot', {'target': target, 'timeout_s': timeout_s})

    @action(action_name='write_cnc_path', displayname='下发-写刮取路径到PLC', description='执行步骤：把 sx/sy/cx/cy 四个最多400点 REAL 数组和 feed 块写到 PLC 的 g_sx/g_sy/g_cx/g_cy/g_scrape_feed 节点，再逐字段/逐元素回读并按 atol=0.001 比较。 前置与安全：输入必须来自已审查的 cnc_path 结果且数组长度/数值合法；单写者锁串行化写入，本动作只下发参数、不启动 CNC。 完成与异常：全部回读一致后返回 DONE；节点缺失、类型/长度错误、写入或回读不一致返回 ERROR。 实现核对：ActionExecutor._exec_plc_write → OpcUaDriver.write_block_confirmed，字段映射以本动作 fields 为唯一入口。')
    async def write_cnc_path(self, sx: list[float], sy: list[float], cx: list[float], cy: list[float], feed: int) -> PlatformActionResult:
        return await self._invoke('photoscrape.write_cnc_path', {'sx': sx, 'sy': sy, 'cx': cx, 'cy': cy, 'feed': feed})

    @action(action_name='write_pass_z', displayname='下发-写本层Z切深', description='执行步骤：在每个 scrape pass 前把本层 z 写入 PLC g_pass_z，并立即回读以 atol=0.001 确认实际下发值。 前置与安全：z 应来自 cnc_path 的 pass_z_list 且满足机床Z安全范围；本动作只写参数，不启动刀具运动。 完成与异常：回读与目标一致后返回 DONE；节点缺失、数值非法、写入或回读不一致返回 ERROR。 实现核对：ActionExecutor._exec_plc_write → OpcUaDriver.write_block_confirmed，写入目标由fields中的g_pass_z限定。')
    async def write_pass_z(self, z: float) -> PlatformActionResult:
        return await self._invoke('photoscrape.write_pass_z', {'z': z})

    @action(
        action_name='photoscrape_before_photo_capture',
        displayname='拍照刮板-before拍照',
        description='PlatformUI operation photoscrape_before_photo_capture 的类型化 UniLab Action；逐字段参数会编码后交给既有 VM，工位资源锁与控制流语义不变。',
    )
    async def photoscrape_before_photo_capture(
        self,
        sample_id: str = '',
        save_dir: str = '',
        timeout_s: float = 3600.0,
    ) -> PlatformOperationResult:
        """Run photoscrape_before_photo_capture through the unchanged PlatformUI operation VM.

        Args:
            sample_id[样品ID]: 样品ID
            save_dir[拍照图保存目录]: 拍照图保存目录
            timeout_s[运行超时（秒）]: PlatformUI 根 operation 的绝对等待上限。
        """
        return await self._run_typed_station_operation(
            'photoscrape_before_photo_capture',
            {
                'sample_id': sample_id,
                'save_dir': save_dir,
            },
            timeout_s=timeout_s,
        )

    @action(
        action_name='photoscrape_process',
        displayname='拍照刮板-执行',
        description='PlatformUI operation photoscrape_process 的类型化 UniLab Action；逐字段参数会编码后交给既有 VM，工位资源锁与控制流语义不变。',
    )
    async def photoscrape_process(
        self,
        sample_id: str = '',
        save_dir: str = '',
        before_path: str = '',
        band_id: str = 'band_01',
        mode: str = 'manual',
        fixed_summary_path: str = '',
        fixed_band_id: str = 'fixed_01',
        reconcile_photo: bool = True,
        timeout_s: float = 3600.0,
    ) -> PlatformOperationResult:
        """Run photoscrape_process through the unchanged PlatformUI operation VM.

        Args:
            sample_id[样品ID]: 样品ID
            save_dir[拍照图保存目录]: 拍照图保存目录
            before_path[before图路径(显影前/测试预置图)]: before图路径(显影前/测试预置图)
            band_id[选带ID(manual 模式人工覆盖; auto 用默认)]: 选带ID(manual 模式人工覆盖; auto 用默认)
            mode[路径来源模式]: 路径来源模式
            fixed_summary_path[固定路径实验: 非空则用此 summary 覆盖视觉/手绘, 直接下发跳过人工门]: 固定路径实验: 非空则用此 summary 覆盖视觉/手绘, 直接下发跳过人工门
            fixed_band_id[固定路径 band_id(与 fixed_scrape_path 脚本默认对齐)]: 固定路径 band_id(与 fixed_scrape_path 脚本默认对齐)
            reconcile_photo[刮后对账照片开关(漂移哨兵/标定验收唯一凭据); 生产嫌节拍可关]: 刮后对账照片开关(漂移哨兵/标定验收唯一凭据); 生产嫌节拍可关
            timeout_s[运行超时（秒）]: PlatformUI 根 operation 的绝对等待上限。
        """
        return await self._run_typed_station_operation(
            'photoscrape_process',
            {
                'sample_id': sample_id,
                'save_dir': save_dir,
                'before_path': before_path,
                'band_id': band_id,
                'mode': mode,
                'fixed_summary_path': fixed_summary_path,
                'fixed_band_id': fixed_band_id,
                'reconcile_photo': reconcile_photo,
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


__all__ = ['PLCPhotoScrape']
