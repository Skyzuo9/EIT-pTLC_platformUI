-- 机器人原子动作 MVP 最小程序。
--
-- 用途：
--   当现场只需要机器人原子动作 MVP 时，将本文件合入机器人工程师的最新工程。
--
-- 动作范围：
--   FunctionID 24：查询当前位姿和关节角
--   FunctionID 25：以 MovJ 运动到目标位姿
--   FunctionID 26：以 MovJ 回到 P1 原点/待命点
--   FunctionID 27：以 MovL 运动到目标位姿
--   FunctionID 28：执行白名单末端工具动作
--
-- 前提：
--   1. 机器人工程中存在 P1，且 P1 已确认为原点/待命点。
--   2. 通信对端提供 Modbus TCP 保持寄存器；新 MVP 中可由 pTLC 上位机替代 PLC。
--   3. 安全模式门控、资源锁和碰撞策略由上位机或机器人控制器安全配置保证。

-- ======================================================================
-- 1. Modbus 寄存器映射
-- ======================================================================
-- 上位机/PLC -> 机器人
REG_EXECUTE     = 3100
REG_RESET       = 3101
REG_FUNCTION_ID = 3102

-- 机器人 -> 上位机/PLC
REG_STATUS  = 3200
REG_ERRORID = 3202

-- 原子动作参数：上位机/PLC -> 机器人
REG_ATOM_USER = 3400
REG_ATOM_TOOL = 3401
REG_ATOM_ACC  = 3402
REG_ATOM_VEL  = 3403
REG_ATOM_CP   = 3404
REG_ATOM_TOOL_ACTION = 3405
REG_ATOM_TOOL_TIMEOUT_MS = 3406
REG_ATOM_TARGET_POSE = { 3410, 3412, 3414, 3416, 3418, 3420 } -- x、y、z、rx、ry、rz，F32
REG_ATOM_TARGET_JOINT = { 3422, 3424, 3426, 3428, 3430, 3432 } -- j1..j6，F32
REG_ATOM_USE_JOINT_TARGET = 3407  -- 0=pose 模式（默认）, 1=joint 模式

-- 原子动作反馈：机器人 -> 上位机/PLC
REG_ATOM_FB_POSE  = { 3440, 3442, 3444, 3446, 3448, 3450 } -- x、y、z、rx、ry、rz，F32
REG_ATOM_FB_JOINT = { 3460, 3462, 3464, 3466, 3468, 3470 } -- j1..j6，F32
REG_ATOM_CHECK_RESULT = 3480
REG_ATOM_LAST_ACTION  = 3481
REG_ATOM_TOOL_COMMANDED_STATE = 3482
REG_ATOM_TOOL_ACTUAL_STATE    = 3483
REG_ATOM_TOOL_FEEDBACK_FLAGS  = 3484
REG_ATOM_TOOL_DI_BITS         = 3485

-- ======================================================================
-- 2. 状态码、功能编号和错误码
-- ======================================================================
ST_FREE  = 0
ST_BUSY  = 1
ST_DONE  = 2
ST_ERROR = 3

FID_QUERY_STATUS_POSE = 24
FID_MOVEJ_POSE        = 25
FID_HOME              = 26
FID_MOVEL_POSE         = 27
FID_TOOL_ACTION        = 28

ERR_NONE                    = 0
ERR_RUNTIME                 = 1
ERR_NOT_ALLOWED             = 255
ERR_ATOM_INVALID_PARAM      = 10
ERR_ATOM_CHECK_MOVJ_FAILED  = 11
ERR_ATOM_POSE_READ_FAILED   = 12
ERR_ATOM_FEEDBACK_FAILED    = 13
ERR_ATOM_CHECK_MOVL_FAILED  = 14
ERR_ATOM_TOOL_ACTION_INVALID = 15
ERR_ATOM_TOOL_TIMEOUT       = 16

ATOM_DEFAULT_USER = 0
ATOM_DEFAULT_TOOL = 1
ATOM_DEFAULT_ACC  = 20
ATOM_DEFAULT_VEL  = 20
ATOM_DEFAULT_CP   = 0
ATOM_DEFAULT_TOOL_TIMEOUT_MS = 3000

-- 白名单工具动作编号。生产调用方不得写入任意 DO。
TOOL_QUICK_CHANGE_LOCK    = 1
TOOL_QUICK_CHANGE_RELEASE = 2
TOOL_SUCTION_ON           = 3
TOOL_SUCTION_OFF          = 4
TOOL_GRIPPER_OPEN         = 5
TOOL_GRIPPER_CLOSE        = 6
TOOL_GET_STATE            = 7
TOOL_CHANGE_AUX_ON       = 8
TOOL_CHANGE_AUX_OFF      = 9
TOOL_ROTARY_UP           = 10
TOOL_ROTARY_DOWN         = 11

-- 以下 IO 映射继承自现有生产 Lua。现场确认电平极性和物理语义后，
-- 才能将 TOOL_DI_FEEDBACK_ENABLED 设为 true。
-- 快换 IO：DO1=true(1)=松开(release)，DO1=false(0)=锁紧(lock)
TOOL_DO_QUICK_CHANGE = 1
TOOL_DO_GRIPPER      = 2
TOOL_DO_SUCTION      = 3
TOOL_DO_GRIPPER_AUX  = 6
TOOL_DI_GRIPPER_OPEN   = 1
TOOL_DI_GRIPPER_CLOSED = 2
TOOL_DI_FEEDBACK_ENABLED = false

TOOL_STATE_QUICK_LOCKED  = 1
TOOL_STATE_SUCTION_ON    = 2
TOOL_STATE_GRIPPER_CLOSED = 4
TOOL_ACTUAL_UNKNOWN = 65535
TOOL_FB_COMMAND_VALID = 1
TOOL_FB_DI_AVAILABLE  = 2
TOOL_FB_DI_CONFIRMED  = 4
TOOL_COMMANDED_STATE = 0

LAST_ERROR_ID = ERR_RUNTIME

-- Modbus TCP 服务端地址。
-- 如果机器人作为 Modbus 客户端运行，此处填写 pTLC 上位机 IP。
MODBUS_SERVER_IP = '192.168.0.15'
MODBUS_SERVER_PORT = 502

-- ======================================================================
-- 3. Modbus 读写辅助函数
-- ======================================================================
function ModbusConnect()
  print('[初始化] 正在连接 Modbus ' .. MODBUS_SERVER_IP .. ':' .. tostring(MODBUS_SERVER_PORT) .. ' ...')
  local err, attempt = nil, 0
  repeat
    attempt = attempt + 1
    err, MODBUS_ID = ModbusCreate(MODBUS_SERVER_IP, MODBUS_SERVER_PORT, 1)
    if err ~= 0 or MODBUS_ID == nil then
      print('[初始化] Modbus 连接第 ' .. tostring(attempt) .. ' 次尝试失败 (错误码=' .. tostring(err) .. ')，重试中...')
      Wait(500)
    end
  until err == 0 and MODBUS_ID ~= nil
  print('[初始化] Modbus 连接成功，MODBUS_ID=' .. tostring(MODBUS_ID))
end

function ReadU16(addr)
  return GetHoldRegs(MODBUS_ID, addr, 1, 'U16')[1]
end

function WriteU16(addr, value)
  SetHoldRegs(MODBUS_ID, addr, 1, { value or 0 }, 'U16')
end

function ReadF32(addr)
  local values = GetHoldRegs(MODBUS_ID, addr, 2, 'F32')
  if values == nil or values[1] == nil then
    RaiseRobotError(ERR_ATOM_POSE_READ_FAILED, 'F32 读取失败: ' .. tostring(addr))
  end
  return values[1]
end

function WriteF32(addr, value)
  SetHoldRegs(MODBUS_ID, addr, 2, { value or 0 }, 'F32')
end

function WaitValue(addr, target)
  while ReadU16(addr) ~= target do
    Wait(20)
  end
end

function WriteStatus(status)
  local names = { [ST_FREE] = '空闲', [ST_BUSY] = '忙', [ST_DONE] = '完成', [ST_ERROR] = '错误' }
  print('[状态] -> ' .. (names[status] or '未知(' .. tostring(status) .. ')'))
  WriteU16(REG_STATUS, status)
end

function WriteError(errid)
  WriteU16(REG_ERRORID, errid)
end

-- 接收新命令时先清掉上一条命令的完成标识，再锁存 BUSY。
-- 位姿/关节反馈保留到本次动作完成并整体覆写，便于现场超时后诊断。
function BeginAction()
  print('[动作] 开始动作 - 清除错误并设置为忙状态')
  WriteError(ERR_NONE)
  WriteU16(REG_ATOM_CHECK_RESULT, 0)
  WriteU16(REG_ATOM_LAST_ACTION, 0)
  WriteStatus(ST_BUSY)
end

-- ======================================================================
-- 4. 数据处理辅助函数
-- ======================================================================
function RaiseRobotError(errid, message)
  LAST_ERROR_ID = errid or ERR_RUNTIME
  error(message)
end

function ConsumeLastError()
  local errid = LAST_ERROR_ID or ERR_RUNTIME
  LAST_ERROR_ID = ERR_RUNTIME
  return errid
end

function IsNumber(value)
  return type(value) == 'number' and value == value
end

function ReadPercent(addr, default_value, allow_zero, name)
  local value = tonumber(ReadU16(addr))
  if value == nil or (value == 0 and not allow_zero) then
    return default_value
  end
  if value < 0 or value > 100 then
    RaiseRobotError(ERR_ATOM_INVALID_PARAM, name .. ' 超出范围: ' .. tostring(value))
  end
  return value
end

function ReadMotionOptions()
  local user = tonumber(ReadU16(REG_ATOM_USER)) or ATOM_DEFAULT_USER
  local tool = tonumber(ReadU16(REG_ATOM_TOOL)) or ATOM_DEFAULT_TOOL
  if tool == 0 then tool = ATOM_DEFAULT_TOOL end
  if user < 0 or tool < 0 then
    RaiseRobotError(ERR_ATOM_INVALID_PARAM, '无效的 user/tool')
  end
  return {
    user = user,
    tool = tool,
    a = ReadPercent(REG_ATOM_ACC, ATOM_DEFAULT_ACC, false, '加速度'),
    v = ReadPercent(REG_ATOM_VEL, ATOM_DEFAULT_VEL, false, '速度'),
    cp = ReadPercent(REG_ATOM_CP, ATOM_DEFAULT_CP, true, '平滑过渡')
  }
end

function ReadTargetPose()
  local pose = {}
  local has_non_zero = false
  for i = 1, 6 do
    local value = ReadF32(REG_ATOM_TARGET_POSE[i])
    if not IsNumber(value) then
      RaiseRobotError(ERR_ATOM_INVALID_PARAM, '无效的位姿分量: ' .. tostring(i))
    end
    if math.abs(value) > 0.000001 then has_non_zero = true end
    pose[i] = value
  end
  if not has_non_zero then
    RaiseRobotError(ERR_ATOM_INVALID_PARAM, '目标位姿为空')
  end
  return { pose = pose }
end

function ReadTargetJoint()
  local joint = {}
  local has_non_zero = false
  for i = 1, 6 do
    local value = ReadF32(REG_ATOM_TARGET_JOINT[i])
    if not IsNumber(value) then
      RaiseRobotError(ERR_ATOM_INVALID_PARAM, '无效的关节分量: ' .. tostring(i))
    end
    if math.abs(value) > 0.000001 then has_non_zero = true end
    joint[i] = value
  end
  if not has_non_zero then
    RaiseRobotError(ERR_ATOM_INVALID_PARAM, '目标关节角为空')
  end
  return { joint = joint }
end

function ReadToolTimeoutMs()
  local value = tonumber(ReadU16(REG_ATOM_TOOL_TIMEOUT_MS)) or 0
  if value == 0 then return ATOM_DEFAULT_TOOL_TIMEOUT_MS end
  if value < 100 or value > 60000 then
    RaiseRobotError(ERR_ATOM_INVALID_PARAM, '工具超时超出范围: ' .. tostring(value))
  end
  return value
end

function SetStateBit(value, mask, enabled)
  local has_bit = (value % (mask * 2)) >= mask
  if enabled and not has_bit then return value + mask end
  if not enabled and has_bit then return value - mask end
  return value
end

function ReadToolDIBits()
  local bits = 0
  if DI(TOOL_DI_GRIPPER_OPEN) == ON then bits = bits + 1 end
  if DI(TOOL_DI_GRIPPER_CLOSED) == ON then bits = bits + 2 end
  return bits
end

function WriteToolFeedback(di_confirmed)
  local flags = TOOL_FB_COMMAND_VALID
  local actual = TOOL_ACTUAL_UNKNOWN
  local di_bits = 0
  if TOOL_DI_FEEDBACK_ENABLED then
    flags = flags + TOOL_FB_DI_AVAILABLE
    di_bits = ReadToolDIBits()
    if di_confirmed then flags = flags + TOOL_FB_DI_CONFIRMED end
  end
  WriteU16(REG_ATOM_TOOL_COMMANDED_STATE, TOOL_COMMANDED_STATE)
  WriteU16(REG_ATOM_TOOL_ACTUAL_STATE, actual)
  WriteU16(REG_ATOM_TOOL_FEEDBACK_FLAGS, flags)
  WriteU16(REG_ATOM_TOOL_DI_BITS, di_bits)
end

function WaitDI(channel, expected_on, timeout_ms)
  local elapsed = 0
  while elapsed < timeout_ms do
    local is_on = DI(channel) == ON
    if is_on == expected_on then return true end
    Wait(20)
    elapsed = elapsed + 20
  end
  return false
end

function ExtractSix(values, nested_name, label)
  local src = values
  if type(src) == 'table' and #src == 1 and type(src[1]) == 'table' then
    src = src[1]
  end
  if type(src) == 'table' and type(src[nested_name]) == 'table' then
    src = src[nested_name]
  end
  if type(src) ~= 'table' then
    RaiseRobotError(ERR_ATOM_FEEDBACK_FAILED, '无效的 ' .. label .. ' 反馈')
  end

  local keys = nil
  if label == 'pose' then
    keys = { 'x', 'y', 'z', 'rx', 'ry', 'rz' }
  elseif label == 'joint' then
    keys = { 'j1', 'j2', 'j3', 'j4', 'j5', 'j6' }
  end

  local out = {}
  for i = 1, 6 do
    local value = src[i]
    if value == nil and keys ~= nil then value = src[keys[i]] end
    if not IsNumber(value) then
      RaiseRobotError(ERR_ATOM_FEEDBACK_FAILED, '无效的 ' .. label .. ' 分量: ' .. tostring(i))
    end
    out[i] = value
  end
  return out
end

function WriteF32Array(addrs, values)
  for i = 1, 6 do
    WriteF32(addrs[i], values[i])
  end
end

function WriteFeedback(user, tool)
  local pose_values = { GetPose(user, tool) }
  local joint_values = { GetAngle() }
  local pose = ExtractSix(pose_values, 'pose', 'pose')
  local joint = ExtractSix(joint_values, 'joint', 'joint')
  WriteF32Array(REG_ATOM_FB_POSE, pose)
  WriteF32Array(REG_ATOM_FB_JOINT, joint)
end

function ClearAtomFeedback()
  WriteF32Array(REG_ATOM_FB_POSE, { 0, 0, 0, 0, 0, 0 })
  WriteF32Array(REG_ATOM_FB_JOINT, { 0, 0, 0, 0, 0, 0 })
  WriteU16(REG_ATOM_CHECK_RESULT, 0)
  WriteU16(REG_ATOM_LAST_ACTION, 0)
  WriteU16(REG_ATOM_TOOL_COMMANDED_STATE, 0)
  WriteU16(REG_ATOM_TOOL_ACTUAL_STATE, TOOL_ACTUAL_UNKNOWN)
  WriteU16(REG_ATOM_TOOL_FEEDBACK_FLAGS, 0)
  WriteU16(REG_ATOM_TOOL_DI_BITS, 0)
end

-- ======================================================================
-- 5. 原子动作
-- ======================================================================
function ActionQueryStatusPose()
  print('[动作] 查询状态 (FID=24) - 读取当前位姿和关节角')
  local opts = ReadMotionOptions()
  print('[动作] 查询状态 - 用户坐标系=' .. tostring(opts.user) .. ' 工具坐标系=' .. tostring(opts.tool))
  WriteU16(REG_ATOM_CHECK_RESULT, 0)
  WriteFeedback(opts.user, opts.tool)
  WriteToolFeedback(false)
  WriteU16(REG_ATOM_LAST_ACTION, FID_QUERY_STATUS_POSE)
  print('[动作] 查询状态完成')
end

function ActionMoveJPose()
  print('[动作] MoveJ (FID=25) - 读取运动参数')
  local opts = ReadMotionOptions()
  print('[动作] MoveJ - 用户坐标系=' .. tostring(opts.user) .. ' 工具坐标系=' .. tostring(opts.tool) ..
        ' 加速度=' .. tostring(opts.a) .. ' 速度=' .. tostring(opts.v) .. ' 平滑=' .. tostring(opts.cp))
  local use_joint = tonumber(ReadU16(REG_ATOM_USE_JOINT_TARGET)) == 1
  print('[动作] MoveJ - 使用关节角目标=' .. tostring(use_joint))
  local target
  if use_joint then
    target = ReadTargetJoint()
    print('[动作] MoveJ - 目标关节角: j1=' .. string.format('%.2f', target.joint[1]) ..
          ' j2=' .. string.format('%.2f', target.joint[2]) .. ' j3=' .. string.format('%.2f', target.joint[3]) ..
          ' j4=' .. string.format('%.2f', target.joint[4]) .. ' j5=' .. string.format('%.2f', target.joint[5]) ..
          ' j6=' .. string.format('%.2f', target.joint[6]))
  else
    target = ReadTargetPose()
    print('[动作] MoveJ - 目标位姿: x=' .. string.format('%.2f', target.pose[1]) ..
          ' y=' .. string.format('%.2f', target.pose[2]) .. ' z=' .. string.format('%.2f', target.pose[3]) ..
          ' rx=' .. string.format('%.2f', target.pose[4]) .. ' ry=' .. string.format('%.2f', target.pose[5]) ..
          ' rz=' .. string.format('%.2f', target.pose[6]))
  end
  print('[动作] MoveJ - 执行碰撞检测...')
  local check = CheckMovJ(target, opts)
  WriteU16(REG_ATOM_CHECK_RESULT, check or ERR_ATOM_CHECK_MOVJ_FAILED)
  if check ~= 0 then
    print('[动作] MoveJ - 碰撞检测失败: ' .. tostring(check))
    RaiseRobotError(ERR_ATOM_CHECK_MOVJ_FAILED, '碰撞检测失败: ' .. tostring(check))
  end
  print('[动作] MoveJ - 碰撞检测通过，执行 MovJ...')
  MovJ(target, opts)
  WriteFeedback(opts.user, opts.tool)
  WriteU16(REG_ATOM_LAST_ACTION, FID_MOVEJ_POSE)
  print('[动作] MoveJ 完成')
end

function ActionHome()
  print('[动作] 回原点 (FID=26) - 运动到 P1 原点位置')
  local opts = ReadMotionOptions()
  print('[动作] 回原点 - 用户坐标系=' .. tostring(opts.user) .. ' 工具坐标系=' .. tostring(opts.tool) ..
        ' 加速度=' .. tostring(opts.a) .. ' 速度=' .. tostring(opts.v))
  MovJ(P1, opts)
  WriteFeedback(opts.user, opts.tool)
  WriteU16(REG_ATOM_CHECK_RESULT, 0)
  WriteU16(REG_ATOM_LAST_ACTION, FID_HOME)
  print('[动作] 回原点完成')
end

function ActionMoveLPose()
  print('[动作] MoveL (FID=27) - 读取运动参数')
  local opts = ReadMotionOptions()
  print('[动作] MoveL - 用户坐标系=' .. tostring(opts.user) .. ' 工具坐标系=' .. tostring(opts.tool) ..
        ' 加速度=' .. tostring(opts.a) .. ' 速度=' .. tostring(opts.v) .. ' 平滑=' .. tostring(opts.cp))
  local target = ReadTargetPose()
  print('[动作] MoveL - 目标位姿: x=' .. string.format('%.2f', target.pose[1]) ..
        ' y=' .. string.format('%.2f', target.pose[2]) .. ' z=' .. string.format('%.2f', target.pose[3]) ..
        ' rx=' .. string.format('%.2f', target.pose[4]) .. ' ry=' .. string.format('%.2f', target.pose[5]) ..
        ' rz=' .. string.format('%.2f', target.pose[6]))
  print('[动作] MoveL - 执行碰撞检测...')
  local check = CheckMovL(target, opts)
  WriteU16(REG_ATOM_CHECK_RESULT, check or ERR_ATOM_CHECK_MOVL_FAILED)
  if check ~= 0 then
    print('[动作] MoveL - 碰撞检测失败: ' .. tostring(check))
    RaiseRobotError(ERR_ATOM_CHECK_MOVL_FAILED, '碰撞检测失败: ' .. tostring(check))
  end
  print('[动作] MoveL - 碰撞检测通过，执行 MovL...')
  MovL(target, opts)
  WriteFeedback(opts.user, opts.tool)
  WriteU16(REG_ATOM_LAST_ACTION, FID_MOVEL_POSE)
  print('[动作] MoveL 完成')
end

function ActionToolAction()
  print('[动作] 工具动作 (FID=28) - 读取动作参数')
  local opts = ReadMotionOptions()
  local action = tonumber(ReadU16(REG_ATOM_TOOL_ACTION)) or 0
  local timeout_ms = ReadToolTimeoutMs()
  local di_confirmed = false

  local action_names = {
    [TOOL_QUICK_CHANGE_LOCK] = '快换锁紧',
    [TOOL_QUICK_CHANGE_RELEASE] = '快换松开',
    [TOOL_SUCTION_ON] = '吸盘开启',
    [TOOL_SUCTION_OFF] = '吸盘关闭',
    [TOOL_GRIPPER_OPEN] = '夹爪张开',
    [TOOL_GRIPPER_CLOSE] = '夹爪闭合',
    [TOOL_GET_STATE] = '查询状态',
    [TOOL_CHANGE_AUX_ON] = '快换辅助开启',
    [TOOL_CHANGE_AUX_OFF] = '快换辅助关闭',
    [TOOL_ROTARY_UP] = '旋转向上',
    [TOOL_ROTARY_DOWN] = '旋转向下'
  }
  print('[动作] 工具动作 - 动作=' .. tostring(action) .. ' (' .. (action_names[action] or '未知') .. ') 超时=' .. tostring(timeout_ms) .. 'ms')

  if action == TOOL_QUICK_CHANGE_LOCK then
    -- DO1=false(0)=锁紧
    print('[动作] 工具动作 - 锁紧快换 (DO' .. tostring(TOOL_DO_QUICK_CHANGE) .. '=0)')
    Wait(1000)
    DO(TOOL_DO_QUICK_CHANGE, 0)
    Wait(1000)
    TOOL_COMMANDED_STATE = SetStateBit(TOOL_COMMANDED_STATE, TOOL_STATE_QUICK_LOCKED, true)
    print('[动作] 工具动作 - 快换已锁紧')
  elseif action == TOOL_QUICK_CHANGE_RELEASE then
    -- DO1=true(1)=松开
    print('[动作] 工具动作 - 松开快换 (DO' .. tostring(TOOL_DO_QUICK_CHANGE) .. '=1)')
    Wait(1000)
    DO(TOOL_DO_QUICK_CHANGE, 1)
    Wait(1000)
    TOOL_COMMANDED_STATE = SetStateBit(TOOL_COMMANDED_STATE, TOOL_STATE_QUICK_LOCKED, false)
    print('[动作] 工具动作 - 快换已松开')
  elseif action == TOOL_SUCTION_ON then
    print('[动作] 工具动作 - 吸盘开启 (DO' .. tostring(TOOL_DO_SUCTION) .. '=1)')
    DO(TOOL_DO_SUCTION, 1)
    TOOL_COMMANDED_STATE = SetStateBit(TOOL_COMMANDED_STATE, TOOL_STATE_SUCTION_ON, true)
    print('[动作] 工具动作 - 吸盘已开启')
  elseif action == TOOL_SUCTION_OFF then
    print('[动作] 工具动作 - 吸盘关闭 (DO' .. tostring(TOOL_DO_SUCTION) .. '=0)')
    DO(TOOL_DO_SUCTION, 0)
    TOOL_COMMANDED_STATE = SetStateBit(TOOL_COMMANDED_STATE, TOOL_STATE_SUCTION_ON, false)
    print('[动作] 工具动作 - 吸盘已关闭')
  elseif action == TOOL_GRIPPER_OPEN then
    print('[动作] 工具动作 - 夹爪张开 (DO' .. tostring(TOOL_DO_GRIPPER_AUX) .. '=1, DO' .. tostring(TOOL_DO_GRIPPER) .. '=0)')
    DO(TOOL_DO_GRIPPER_AUX, 1)
    DO(TOOL_DO_GRIPPER, 0)
    TOOL_COMMANDED_STATE = SetStateBit(TOOL_COMMANDED_STATE, TOOL_STATE_GRIPPER_CLOSED, false)
    if TOOL_DI_FEEDBACK_ENABLED then
      print('[动作] 工具动作 - 等待夹爪张开 DI 反馈 (超时=' .. tostring(timeout_ms) .. 'ms)...')
      di_confirmed = WaitDI(TOOL_DI_GRIPPER_OPEN, true, timeout_ms)
      if not di_confirmed then
        print('[动作] 工具动作 - 夹爪张开反馈超时')
        WriteToolFeedback(false)
        RaiseRobotError(ERR_ATOM_TOOL_TIMEOUT, '夹爪张开反馈超时')
      end
      print('[动作] 工具动作 - 夹爪张开反馈已确认')
    end
    print('[动作] 工具动作 - 夹爪已张开')
  elseif action == TOOL_GRIPPER_CLOSE then
    print('[动作] 工具动作 - 夹爪闭合 (DO' .. tostring(TOOL_DO_GRIPPER_AUX) .. '=0, DO' .. tostring(TOOL_DO_GRIPPER) .. '=1)')
    DO(TOOL_DO_GRIPPER_AUX, 0)
    DO(TOOL_DO_GRIPPER, 1)
    TOOL_COMMANDED_STATE = SetStateBit(TOOL_COMMANDED_STATE, TOOL_STATE_GRIPPER_CLOSED, true)
    if TOOL_DI_FEEDBACK_ENABLED then
      print('[动作] 工具动作 - 等待夹爪闭合 DI 反馈 (超时=' .. tostring(timeout_ms) .. 'ms)...')
      di_confirmed = WaitDI(TOOL_DI_GRIPPER_CLOSED, true, timeout_ms)
      if not di_confirmed then
        print('[动作] 工具动作 - 夹爪闭合反馈超时')
        WriteToolFeedback(false)
        RaiseRobotError(ERR_ATOM_TOOL_TIMEOUT, '夹爪闭合反馈超时')
      end
      print('[动作] 工具动作 - 夹爪闭合反馈已确认')
    end
    print('[动作] 工具动作 - 夹爪已闭合')
  elseif action == TOOL_CHANGE_AUX_ON then
    print('[动作] 工具动作 - 快换辅助开启 (DO' .. tostring(TOOL_DO_GRIPPER_AUX) .. '=1)')
    DO(TOOL_DO_GRIPPER_AUX, 1)
  elseif action == TOOL_CHANGE_AUX_OFF then
    print('[动作] 工具动作 - 快换辅助关闭 (DO' .. tostring(TOOL_DO_GRIPPER_AUX) .. '=0)')
    DO(TOOL_DO_GRIPPER_AUX, 0)
  elseif action == TOOL_ROTARY_UP then
    print('[动作] 工具动作 - 旋转向上 (DO' .. tostring(TOOL_DO_GRIPPER) .. '=1, DO' .. tostring(TOOL_DO_GRIPPER_AUX) .. '=0)')
    DO(TOOL_DO_GRIPPER_AUX, 0)
    DO(TOOL_DO_GRIPPER, 1)
    TOOL_COMMANDED_STATE = SetStateBit(TOOL_COMMANDED_STATE, TOOL_STATE_GRIPPER_CLOSED, false)
    print('[动作] 工具动作 - 旋转向上完成')
  elseif action == TOOL_ROTARY_DOWN then
    print('[动作] 工具动作 - 旋转向下 (DO' .. tostring(TOOL_DO_GRIPPER_AUX) .. '=1, DO' .. tostring(TOOL_DO_GRIPPER) .. '=0)')
    DO(TOOL_DO_GRIPPER, 0)
    DO(TOOL_DO_GRIPPER_AUX, 1)
    TOOL_COMMANDED_STATE = SetStateBit(TOOL_COMMANDED_STATE, TOOL_STATE_GRIPPER_CLOSED, false)
    print('[动作] 工具动作 - 旋转向下完成')
  elseif action ~= TOOL_GET_STATE then
    print('[动作] 工具动作 - 无效的动作: ' .. tostring(action))
    RaiseRobotError(ERR_ATOM_TOOL_ACTION_INVALID, '不允许的工具动作: ' .. tostring(action))
  end

  WriteToolFeedback(di_confirmed)
  WriteFeedback(opts.user, opts.tool)
  WriteU16(REG_ATOM_CHECK_RESULT, 0)
  WriteU16(REG_ATOM_LAST_ACTION, FID_TOOL_ACTION)
  print('[动作] 工具动作完成')
end

HANDLERS = {
  [FID_QUERY_STATUS_POSE] = ActionQueryStatusPose,
  [FID_MOVEJ_POSE] = ActionMoveJPose,
  [FID_HOME] = ActionHome,
  [FID_MOVEL_POSE] = ActionMoveLPose,
  [FID_TOOL_ACTION] = ActionToolAction
}

-- ======================================================================
-- 6. 主循环
-- ======================================================================
function Init()
  print('========================================')
  print('[初始化] 机器人 MVP 最小程序启动中...')
  print('========================================')
  ModbusConnect()
  ClearAtomFeedback()
  WriteError(ERR_NONE)
  WriteStatus(ST_FREE)
  print('[初始化] 初始化完成，进入主循环')
end

function HandleError(errid)
  print('[错误] 处理错误，错误码=' .. tostring(errid))
  WriteError(errid)
  WriteStatus(ST_ERROR)
  print('[错误] 等待复位信号 (REG_RESET=1 然后 0)...')
  WaitValue(REG_RESET, 1)
  print('[错误] 已收到 RESET=1，等待 RESET=0...')
  WaitValue(REG_RESET, 0)
  print('[错误] 已收到 RESET=0，清除错误')
  WriteError(ERR_NONE)
end

Init()
while true do
  WriteStatus(ST_FREE)
  print('[主循环] 等待 EXECUTE=1...')
  WaitValue(REG_EXECUTE, 1)

  local fid = ReadU16(REG_FUNCTION_ID)
  local fid_names = {
    [FID_QUERY_STATUS_POSE] = '查询位姿状态',
    [FID_MOVEJ_POSE] = 'MOVJ运动',
    [FID_HOME] = '回原点',
    [FID_MOVEL_POSE] = 'MOVL运动',
    [FID_TOOL_ACTION] = '工具动作'
  }
  print('[主循环] 收到执行命令，功能ID=' .. tostring(fid) .. ' (' .. (fid_names[fid] or '未知') .. ')')
  local handler = HANDLERS[fid]

  if handler == nil then
    print('[主循环] 未知功能ID，触发 ERR_NOT_ALLOWED(255)')
    HandleError(ERR_NOT_ALLOWED)
  else
    BeginAction()
    LAST_ERROR_ID = ERR_RUNTIME
    local ok, err = pcall(handler)
    if ok then
      -- DONE 必须保持到上位机读取完反馈并撤销 EXECUTE，不能做成短脉冲。
      print('[主循环] 动作执行成功，写入 DONE')
      WriteStatus(ST_DONE)
    else
      print('[主循环] 动作执行失败: ' .. tostring(err))
      HandleError(ConsumeLastError())
    end
  end

  print('[主循环] 等待 EXECUTE=0...')
  WaitValue(REG_EXECUTE, 0)
  print('[主循环] 已收到 EXECUTE=0，循环结束')
  WriteStatus(ST_FREE)
end
