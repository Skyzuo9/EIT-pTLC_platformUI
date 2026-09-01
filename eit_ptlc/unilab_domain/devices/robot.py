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
    id='robot',
    category=['ptlc', 'robot', 'platformui-proxy'],
    displayname='robot',
    description='PlatformUI robot 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'type': 'package_moveit',
 'provider': 'unilab_arm_cr5:build_moveit_model',
 'source_digest': '8c8b9ea935fd83122b19b572c84d107e81b4864d4310c94d0906cc361e7631c2'},
    metadata={'platformui_device_id': 'robot',
 'platformui_action_namespace': 'robot',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT', 'manifest_section': None},
 'platformui_display_scene': {'asset': 'eit_ptlc/three_d/models/machine.official-cr5.glb',
                              'node': 'ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT',
                              'motion_authority': False}},
)
class RobotProxy(PlatformUIProxyBase):
    platformui_namespace = 'robot'

    @action(action_name='clear_error', displayname='清除报警', description='执行步骤：在 confirm=true 后调用控制器清警命令，清除允许软件复位的机器人报警并重新读取状态。 前置与安全：仅 DEBUG 模式且配置允许清警时可用；必须先排除报警根因，清警不会自动释放急停或启动运动。 完成与异常：报警被控制器接受清除后返回 DONE；未确认、配置门关闭、仍有硬件故障或通信失败返回拒绝/ERROR。 实现核对：RobotController.clear_error → transport.clear_error；配置allow_clear_error_command与confirm双门。')
    async def clear_error(self, confirm: bool) -> PlatformActionResult:
        return await self._invoke('robot.clear_error', {'confirm': confirm})

    @action(action_name='connect', displayname='重连机械臂', description='执行步骤：关闭失效的 Dobot 通信会话，重新建立控制/反馈连接并执行传输层握手和状态校验，不发送运动命令。 前置与安全：不限控制模式；重连不会自动清警、使能或重放结果不明确的物理动作。confirm=true 表示操作员已人工确认机械臂已物理停止且无其他控制者，此时先清除 CurrentCommandId 接管守卫的比对基准再重连（守卫报错"需人工确认"的唯一落点）；缺省 false 时守卫照常拦截，"仍在运行/暂停"的拒绝不受 confirm 影响。 完成与异常：连接与状态通道恢复后返回 DONE；地址不可达、握手或状态校验失败返回 ERROR，原动作不会自动重试。 实现核对：RobotController.reconnect按close→connect→query执行；connect中的所有权对账可在他人运动/命令变化时拒绝接管。')
    async def connect(self, confirm: bool = False) -> PlatformActionResult:
        return await self._invoke('robot.connect', {'confirm': confirm})

    @action(action_name='disable', displayname='下使能机械臂', description='执行步骤：在 confirm=true 后向控制器发送下使能，撤销机器人伺服使能并停止接受普通运动命令。 前置与安全：仅 DEBUG 模式且配置允许时可用；应先确保机器人处于稳定可承载姿态，避免重力或工具负载造成风险。 完成与异常：控制器报告未使能后返回 DONE；未确认、配置门关闭或通信失败返回拒绝/ERROR。 实现核对：RobotController.disable_robot → transport.disable_robot；复用allow_enable_command+confirm双门，等待DISABLED并释放jog租约。')
    async def disable(self, confirm: bool) -> PlatformActionResult:
        return await self._invoke('robot.disable', {'confirm': confirm})

    @action(action_name='dwell', displayname='驻留等待', description='执行步骤：在线程池中调用time.sleep等待duration_ms，用于工具动作后稳压、夹持或振动消退，不发送运动和IO。 前置与安全：时长由动作参数限制为1–60000毫秒；这是同步睡眠，流程停止/任务取消不能中途打断该sleep，只能等待本次驻留结束。 完成与异常：睡眠结束返回DONE；非法时长在执行前拒绝，线程内异常返回ERROR，不会产生机器人CANCELLED反馈。 实现核对：RobotController.dwell，经ActionExecutor._exec_robot放入run_in_executor执行。')
    async def dwell(self, duration_ms: int) -> PlatformActionResult:
        return await self._invoke('robot.dwell', {'duration_ms': duration_ms})

    @action(action_name='emergency_stop', displayname='急停', description='执行步骤：pressed=true 时向控制器施加急停并立即抑制运动；pressed=false 时仅发送急停释放命令，不自动清警、使能或恢复轨迹。 前置与安全：不限控制模式；危险情况优先按下，释放前必须完成现场确认，随后按需清警和重新使能。 完成与异常：控制器确认急停状态后返回 DONE；通信失败返回 ERROR，急停导致的在途动作归一为 CANCELLED。 实现核对：RobotController.emergency_stop不占动作锁；pressed=true同时释放jog租约，传输层等待目标机器人模式。')
    async def emergency_stop(self, pressed: bool = True) -> PlatformActionResult:
        return await self._invoke('robot.emergency_stop', {'pressed': pressed})

    @action(action_name='enable', displayname='使能机械臂', description='执行步骤：在 confirm=true 后向控制器发送伺服使能，使机器人进入可接受运动命令的上电状态。 前置与安全：仅 DEBUG 模式且配置允许使能时可用；使能前必须确认急停已释放、报警已处理且工作空间安全。 完成与异常：控制器报告已使能后返回 DONE；未确认、配置门关闭、急停/报警或通信失败返回拒绝/ERROR。 实现核对：RobotController.enable_robot → transport.enable_robot；配置allow_enable_command与confirm双门，并等待ENABLED_IDLE。')
    async def enable(self, confirm: bool) -> PlatformActionResult:
        return await self._invoke('robot.enable', {'confirm': confirm})

    @action(action_name='home', displayname='回原点', description='执行步骤：从点位注册表读取配置的home点，要求其role=home，再使用该点标定的user/tool/acc/vel/cp和关节角执行move_j；这不是控制器内建Home命令。 前置与安全：仅DEBUG模式；工作空间无人、末端工具和地轨位置安全。该动作不会先做safe_anchor邻域判定，需要确保式回零时应调用home_ensure。 完成与异常：move_j到配置home点并收到控制器完成后返回DONE；点位角色错误、报警、未使能、急停、轨迹失败或显式中止返回拒绝/ERROR/CANCELLED。 实现核对：RobotController.home，Dobot TCP路径为registry.require_motion(home_point, move_j) → transport.move_j。')
    async def home(self) -> PlatformActionResult:
        return await self._invoke('robot.home', {})

    @action(action_name='home_ensure', displayname='确保在原点 (安全邻域自动回零)', description='执行步骤：读取当前位姿；在 P1 容差内直接通过；否则先做吸盘真空守卫，再判定当前位姿是否处于某个 safe_anchor 安全点邻域内，是则 move_j 回 P1 并复验，否则拒绝。 前置与安全：不限控制模式；自动回零仅从已验证自由空间安全点发起；吸盘有真空(疑似持板)或邻域外一律硬停，由操作员处置。 完成与异常：已在位或回零复验通过返回 DONE；持真空/邻域外/复验失败返回 UNSAFE，不产生进一步运动。 实现核对：RobotController.ensure_home；只接受配置home点，真空守卫读取同一query快照中的mounted_tool和DO3语义位。')
    async def home_ensure(self, point_id: str | None = None, joint_tol_deg: float = 2.0, pos_tol_mm: float = 5.0, rot_tol_deg: float = 5.0) -> PlatformActionResult:
        return await self._invoke('robot.home_ensure', {'point_id': point_id, 'joint_tol_deg': joint_tol_deg, 'pos_tol_mm': pos_tol_mm, 'rot_tol_deg': rot_tol_deg})

    @action(action_name='jog_start', displayname='点动开始 (按住起)', description='执行步骤：把所选关节轴或笛卡尔轴方向发送给控制器并启动连续点动，运动持续到 jog_stop 或安全中止命令到达。 前置与安全：仅 DEBUG 模式允许；属于按住即动的维护命令，操作员必须持续观察机器人和线缆、工具、工装间隙。 完成与异常：控制器接受点动后返回 DONE（机器人仍在移动）；非法轴、未使能、报警或通信失败返回拒绝/ERROR。 实现核对：RobotController.jog_start；维护活动租约跨越本动作返回边界，直到jog_stop/stop/急停成功释放。')
    async def jog_start(self, axis_id: str) -> PlatformActionResult:
        return await self._invoke('robot.jog_start', {'axis_id': axis_id})

    @action(action_name='jog_stop', displayname='点动停止 (松开停)', description='执行步骤：向机器人控制器发送点动停止，结束当前由 jog_start 发起的连续点动并等待停止命令确认。 前置与安全：仅 DEBUG 模式允许；松开点动按钮必须立即调用，本动作不负责清除控制器报警。 完成与异常：点动停止或本来就未点动时返回 DONE；通信失败返回 ERROR，必要时应使用 stop 或急停。 实现核对：RobotController.jog_stop → transport.jog_stop，并释放连续点动维护活动租约。')
    async def jog_stop(self) -> PlatformActionResult:
        return await self._invoke('robot.jog_stop', {})

    @action(action_name='move_to_point', displayname='运动到点位', description='执行步骤：从机器人点位注册表解析点位及默认运动参数，可用 acc/vel/cp 覆盖速度档；move_l 时再在点位用户坐标系叠加 dx/dy/drz 视觉偏移，然后下发并等待到位。 前置与安全：点位必须存在且偏移只允许用于直线运动；流程应先完成地轨到位、工具态和锚点检查，控制器负责运动限位与报警门控。 完成与异常：实际到达目标位姿返回 DONE；未知点位、参数不成对、偏移不合法、报警、超时或显式停止返回拒绝/ERROR/CANCELLED。 实现核对：ActionExecutor._exec_robot合成MotionProfile/offset并可先执行auto_rail；RobotController.move_to_point解析点位许可后调用move_j或move_l。')
    async def move_to_point(self, point_id_or_robot_name: str, motion: str | None = None, acc: int | None = None, vel: int | None = None, cp: int | None = None, dx_mm: float | None = None, dy_mm: float | None = None, drz_deg: float | None = None) -> PlatformActionResult:
        return await self._invoke('robot.move_to_point', {'point_id_or_robot_name': point_id_or_robot_name, 'motion': motion, 'acc': acc, 'vel': vel, 'cp': cp, 'dx_mm': dx_mm, 'dy_mm': dy_mm, 'drz_deg': drz_deg})

    @action(action_name='pause', displayname='暂停运动', description='执行步骤：向机器人控制器发送暂停，使当前可暂停轨迹停在控制器保持点，不清除队列或报警。 前置与安全：不限控制模式；暂停后机器人可能仍保持伺服力矩，不能替代停止或急停。 完成与异常：控制器进入暂停态返回 DONE；无可暂停任务通常按控制器响应处理，通信或状态错误返回 ERROR。 实现核对：RobotController.pause直接调用transport.pause且不占动作锁；作为原子动作调用时控制器拒绝不会按best-effort吞掉。')
    async def pause(self) -> PlatformActionResult:
        return await self._invoke('robot.pause', {})

    @action(action_name='query', displayname='读取机械臂状态', description='执行步骤：调用 RobotController.query，读取控制柜连接、使能、运行、暂停、急停、报警及当前位姿等状态，不发送运动或 IO 命令。 前置与安全：不限控制模式；属于只读诊断动作，断联时仅返回通信或状态读取失败。 完成与异常：读取成功返回最新状态快照；通信失败或控制器拒绝时返回 ERROR，不改变机器人状态。 实现核对：RobotController.query → RobotTransport.query；ActionExecutor在线程池执行并序列化RobotFeedback。')
    async def query(self) -> PlatformActionResult:
        return await self._invoke('robot.query', {})

    @action(action_name='require_anchor', displayname='校验锚点位姿', description='执行步骤：读取当前反馈并校验锚点status=validated；锚点有六轴joint且反馈齐全时优先只比较最大关节角偏差，否则比较笛卡尔位置和姿态偏差，全程不运动。 前置与安全：锚点必须存在且已验证；容差只用于判断，不能自动纠正位置，通常作为取放流程入口/退出硬门。 完成与异常：所选比较方式在容差内返回DONE；超差或锚点未验证返回UNSAFE，点位/反馈错误返回拒绝或ERROR。 实现核对：RobotController.require_anchor/_check_anchor；ActionExecutor把PermissionError归一为UNSAFE。')
    async def require_anchor(self, point_id: str, joint_tol_deg: float = 2.0, pos_tol_mm: float = 5.0, rot_tol_deg: float = 5.0) -> PlatformActionResult:
        return await self._invoke('robot.require_anchor', {'point_id': point_id, 'joint_tol_deg': joint_tol_deg, 'pos_tol_mm': pos_tol_mm, 'rot_tol_deg': rot_tol_deg})

    @action(action_name='resume', displayname='继续运动', description='执行步骤：向机器人控制器发送继续命令，从已暂停的轨迹保持点恢复剩余运动。 前置与安全：不限控制模式；恢复前必须重新确认人员、工具和工装已离开运动区域，且报警/急停已解除。 完成与异常：控制器接受继续命令返回 DONE；未处于可恢复状态、报警或通信失败返回 ERROR。 实现核对：RobotController.resume通过维护活动登记后调用transport.resume；作为原子动作时控制器拒绝返回ERROR。')
    async def resume(self) -> PlatformActionResult:
        return await self._invoke('robot.resume', {})

    @action(action_name='set_do', displayname='裸 DO 直控', description='执行步骤：绕过工具语义动作，直接把白名单通道 DO1/DO2/DO3/DO6 写为 enabled 指定电平并等待控制器确认。 前置与安全：仅 DEBUG 模式允许且无工具联锁；DO1=0 锁紧、1 松开，DO2=1 夹/0 松，DO3=1 吸/0 放，DO6=1 开/0 关，误操作可能掉落工具或物料。 完成与异常：控制器接受输出后返回 DONE；非白名单通道、模式不允许、断联或写入失败返回拒绝/ERROR。 实现核对：RobotController.set_do → DobotTcpRobotTransport.set_do/_queue_do；写后等待控制器CommandId完成并同步commanded_bits。')
    async def set_do(self, channel: str, enabled: bool) -> PlatformActionResult:
        return await self._invoke('robot.set_do', {'channel': channel, 'enabled': enabled})

    @action(action_name='set_mounted_tool', displayname='声明挂载工具', description='执行步骤：把tool_id 0/1/2/3转换为MountedTool，更新内存权威工具态并尝试写入tool_state文件；不驱动快换、DO或运动。 前置与安全：声明必须与实际挂载一致；0为裸腕、1–3为工具槽，错误声明会错误放行/拒绝后续DO2/DO6双义动作。 完成与异常：枚举合法即返回DONE；非法工具号被拒。持久化IO失败只记录警告并仍返回DONE，因此重启后可能退回旧值/NONE，需启动对账确认。 实现核对：RobotController.set_mounted_tool → DobotTcpRobotTransport.set_mounted_tool/_persist_tool。')
    async def set_mounted_tool(self, tool_id: str) -> PlatformActionResult:
        return await self._invoke('robot.set_mounted_tool', {'tool_id': tool_id})

    @action(action_name='set_speed_factor', displayname='设置全局速度比', description='执行步骤：把 1–100% 的 ratio 写入机器人控制器全局速度倍率，后续点动和运动指令按该倍率缩放。 前置与安全：仅 DEBUG 模式允许；修改只影响控制器速度倍率，不会主动启动或停止运动，调高前需确认现场安全。 完成与异常：控制器确认新倍率后返回 DONE并由节点遥测回显；越界、非数值或通信失败返回拒绝/ERROR。 实现核对：RobotController.set_speed_factor → RobotTransport.set_speed_factor；不占机器人动作锁，可在运动中抢发调速。')
    async def set_speed_factor(self, ratio: int) -> PlatformActionResult:
        return await self._invoke('robot.set_speed_factor', {'ratio': ratio})

    @action(action_name='step', displayname='步进 (单轴增量)', description='执行步骤：按 axis 和 distance 生成单轴增量目标，以直线(l)或关节(j)插补执行一次相对运动并等待到位。 前置与安全：仅 DEBUG 模式允许；调用方必须确认增量方向、单位和目标空间无碰撞，控制器仍执行自身软限位检查。 完成与异常：到达增量目标返回 DONE；非法轴/距离、未使能、报警、超限或中止返回拒绝、ERROR 或 CANCELLED。 实现核对：RobotController.step；distance缺省时笛卡尔轴用step_distance_mm、关节轴用step_angle_deg，再调用transport.step。')
    async def step(self, axis: str, distance: float | None = None, motion: str = 'l') -> PlatformActionResult:
        return await self._invoke('robot.step', {'axis': axis, 'distance': distance, 'motion': motion})

    @action(action_name='stop', displayname='停止运动', description='执行步骤：向机器人发送停止命令，中止当前点动或轨迹运动，并把由显式停止终止的在途机器人动作归一为 CANCELLED。 前置与安全：不限控制模式，可随时用于普通运动中止；它不是硬件急停，危险状态应使用 emergency_stop。 完成与异常：停止命令确认后返回 DONE；断联或控制器拒绝返回 ERROR，在途动作会按可确认状态结束。 实现核对：RobotController.stop不占动作锁并释放jog租约；在途move抛RobotMotionInterrupted时由ActionExecutor归一为CANCELLED。')
    async def stop(self) -> PlatformActionResult:
        return await self._invoke('robot.stop', {})

    @action(action_name='tool_action', displayname='工具动作', description='执行步骤：把名称映射到ToolAction并经过挂载工具白名单；快换锁/放分别写DO1=0/1并前后各等待1秒，吸盘写DO3，夹爪开为DO6=1后DO2=0、夹紧为DO6=0后DO2=1，旋转上/下在DO2与DO6间加入200毫秒互锁，辅助开写DO6=1、辅助关同时清DO2/DO6。 前置与安全：动作必须匹配权威mounted_tool；取工具用quick-change-lock、放工具用quick-change-release，禁止按旧Lua中文名猜极性。快换/吸盘只确认DO命令完成；夹爪/旋转是否等DI取决于tool_confirm的di/dwell/di_or_dwell策略。 完成与异常：DO命令及配置的DI/沉降确认完成后返回DONE；工具态冲突、非法枚举、DI超时、通信失败返回拒绝/ERROR。它本身不是轨迹动作，显式stop不一定把工具动作归一为CANCELLED。 实现核对：ActionExecutor._exec_robot名称转换；DobotTcpRobotTransport.tool_action/_confirm_tool_action及_TOOL_BITS/DI映射。')
    async def tool_action(self, action: str, timeout_ms: int = 3000) -> PlatformActionResult:
        return await self._invoke('robot.tool_action', {'action': action, 'timeout_ms': timeout_ms})


__all__ = ['RobotProxy']
