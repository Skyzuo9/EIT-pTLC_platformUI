-- src0.lua —— 主线程：通信协议状态机 + 功能分发
-- 定义见 global.lua（寄存器映射、通信封装、轨迹原语、业务流程）。

-- Version: Lua 5.4.4
------------------测试区↓-------------------------------------
----------------------------------

-- Robot action MVP minimal program.
--
-- Purpose:
--   Copy this file into the robot engineer's latest project when only the
--   FastAPI robot MVP is needed.
--
-- Scope:
--   FunctionID 24: query current pose/joint
--   FunctionID 25: MovJ to target pose
--   FunctionID 26: MovJ to P1 home/standby point
--
-- Assumptions:
--   1. P1 exists in the robot project and is the agreed home/standby point.
--   2. The peer device exposes Modbus TCP holding registers. In the new MVP,
--      this peer can be the pTLC upper computer instead of PLC.
--   3. Safety mode gating, resource locking, and collision policy are enforced
--      by the upper computer and/or robot controller safety configuration.

-- ======================================================================
-- 1. Modbus register map
-- ======================================================================
-- Upper computer/PLC -> Robot
REG_EXECUTE     = 3100
REG_RESET       = 3101
REG_FUNCTION_ID = 3102

-- Robot -> Upper computer/PLC
REG_STATUS  = 3200
REG_ERRORID = 3202

-- Atom action parameters: upper computer/PLC -> Robot
REG_ATOM_USER = 3400
REG_ATOM_TOOL = 3401
REG_ATOM_ACC  = 3402
REG_ATOM_VEL  = 3403
REG_ATOM_CP   = 3404
REG_ATOM_TARGET_POSE = { 3410, 3412, 3414, 3416, 3418, 3420 } -- x y z rx ry rz, F32

-- Atom action feedback: Robot -> upper computer/PLC
REG_ATOM_FB_POSE  = { 3440, 3442, 3444, 3446, 3448, 3450 } -- x y z rx ry rz, F32
REG_ATOM_FB_JOINT = { 3460, 3462, 3464, 3466, 3468, 3470 } -- j1..j6, F32
REG_ATOM_CHECK_RESULT = 3480
REG_ATOM_LAST_ACTION  = 3481

-- ======================================================================
-- 2. Status, function IDs, and errors
-- ======================================================================
ST_FREE  = 0
ST_BUSY  = 1
ST_DONE  = 2
ST_ERROR = 3

FID_QUERY_STATUS_POSE = 24
FID_MOVEJ_POSE      = 25
FID_HOME          = 26

ERR_NONE                    = 0
ERR_RUNTIME                 = 1
ERR_NOT_ALLOWED             = 255
ERR_ATOM_INVALID_PARAM      = 10
ERR_ATOM_CHECK_MOVJ_FAILED  = 11
ERR_ATOM_POSE_READ_FAILED   = 12
ERR_ATOM_FEEDBACK_FAILED    = 13

ATOM_DEFAULT_USER = 0
ATOM_DEFAULT_TOOL = 1
ATOM_DEFAULT_ACC  = 20
ATOM_DEFAULT_VEL  = 20
ATOM_DEFAULT_CP   = 0

LAST_ERROR_ID = ERR_RUNTIME

-- Set this to the Modbus TCP server address.
-- If the robot runs as Modbus client, this is the pTLC upper computer IP.
MODBUS_SERVER_IP = '192.168.0.15'
MODBUS_SERVER_PORT = 502

-- ======================================================================
-- 3. Modbus helpers
-- ======================================================================
function ModbusConnect()
  local err
  repeat
    err, MODBUS_ID = ModbusCreate(MODBUS_SERVER_IP, MODBUS_SERVER_PORT, 1)
    if err ~= 0 or MODBUS_ID == nil then
      Wait(500)
    end
  until err == 0 and MODBUS_ID ~= nil
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
    RaiseRobotError(ERR_ATOM_POSE_READ_FAILED, 'F32 read failed: ' .. tostring(addr))
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
  WriteU16(REG_STATUS, status)
end

function WriteError(errid)
  WriteU16(REG_ERRORID, errid)
end

-- ======================================================================
-- 4. Data helpers
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
    RaiseRobotError(ERR_ATOM_INVALID_PARAM, name .. ' out of range: ' .. tostring(value))
  end
  return value
end

function ReadMotionOptions()
  local user = tonumber(ReadU16(REG_ATOM_USER)) or ATOM_DEFAULT_USER
  local tool = tonumber(ReadU16(REG_ATOM_TOOL)) or ATOM_DEFAULT_TOOL
  if tool == 0 then tool = ATOM_DEFAULT_TOOL end
  if user < 0 or tool < 0 then
    RaiseRobotError(ERR_ATOM_INVALID_PARAM, 'invalid user/tool')
  end
  return {
    user = user,
    tool = tool,
    a = ReadPercent(REG_ATOM_ACC, ATOM_DEFAULT_ACC, false, 'acc'),
    v = ReadPercent(REG_ATOM_VEL, ATOM_DEFAULT_VEL, false, 'vel'),
    cp = ReadPercent(REG_ATOM_CP, ATOM_DEFAULT_CP, true, 'cp')
  }
end

function ReadTargetPose()
  local pose = {}
  local has_non_zero = false
  for i = 1, 6 do
    local value = ReadF32(REG_ATOM_TARGET_POSE[i])
    if not IsNumber(value) then
      RaiseRobotError(ERR_ATOM_INVALID_PARAM, 'invalid pose item: ' .. tostring(i))
    end
    if math.abs(value) > 0.000001 then has_non_zero = true end
    pose[i] = value
  end
  if not has_non_zero then
    RaiseRobotError(ERR_ATOM_INVALID_PARAM, 'empty target pose')
  end
  return { pose = pose }
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
    RaiseRobotError(ERR_ATOM_FEEDBACK_FAILED, 'invalid ' .. label .. ' feedback')
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
      RaiseRobotError(ERR_ATOM_FEEDBACK_FAILED, 'invalid ' .. label .. ' item: ' .. tostring(i))
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
end

-- ======================================================================
-- 5. Atom actions
-- ======================================================================
function ActionQueryStatusPose()
  local opts = ReadMotionOptions()
  WriteU16(REG_ATOM_CHECK_RESULT, 0)
  WriteFeedback(opts.user, opts.tool)
  WriteU16(REG_ATOM_LAST_ACTION, FID_QUERY_STATUS_POSE)
end

function ActionMoveJPose()
  local opts = ReadMotionOptions()
  local target = ReadTargetPose()
  local check = CheckMovJ(target, opts)
  WriteU16(REG_ATOM_CHECK_RESULT, check or ERR_ATOM_CHECK_MOVJ_FAILED)
  if check ~= 0 then
    RaiseRobotError(ERR_ATOM_CHECK_MOVJ_FAILED, 'CheckMovJ failed: ' .. tostring(check))
  end
  MovJ(target, opts)
  WriteFeedback(opts.user, opts.tool)
  WriteU16(REG_ATOM_LAST_ACTION, FID_MOVEJ_POSE)
end

function ActionHome()
  local opts = ReadMotionOptions()
  MovJ(P1, opts)
  WriteFeedback(opts.user, opts.tool)
  WriteU16(REG_ATOM_CHECK_RESULT, 0)
  WriteU16(REG_ATOM_LAST_ACTION, FID_HOME)
end

HANDLERS = {
  [FID_QUERY_STATUS_POSE] = ActionQueryStatusPose,
  [FID_MOVEJ_POSE] = ActionMoveJPose,
  [FID_HOME] = ActionHome
}

-- ======================================================================
-- 6. Main loop
-- ======================================================================
function Init()
  ModbusConnect()
  ClearAtomFeedback()
  WriteError(ERR_NONE)
  WriteStatus(ST_FREE)
end

function HandleError(errid)
  WriteError(errid)
  WriteStatus(ST_ERROR)
  WaitValue(REG_RESET, 1)
  WaitValue(REG_RESET, 0)
  WriteError(ERR_NONE)
end

Init()
while true do
  WriteStatus(ST_FREE)
  WaitValue(REG_EXECUTE, 1)

  local fid = ReadU16(REG_FUNCTION_ID)
  local handler = HANDLERS[fid]

  if handler == nil then
    HandleError(ERR_NOT_ALLOWED)
  else
    WriteStatus(ST_BUSY)
    LAST_ERROR_ID = ERR_RUNTIME
    local ok, err = pcall(handler)
    if ok then
      WriteStatus(ST_DONE)
    else
      HandleError(ConsumeLastError())
    end
  end

  WaitValue(REG_EXECUTE, 0)
  WriteStatus(ST_FREE)
end





-----------------测试区↑-------------------------------------

--[[
--==================================================================
-- 1. 功能分发表：FunctionID → 动作
--    新增功能只需在此加一行，主循环无需改动。
--==================================================================
--Pause()

HANDLERS = {
  [1]  = function() PL4_Path() end,       -- Area_4 取升降机硅胶板（上料）
  [2]  = function() PL2_Path() end,       -- Area_3 放点样硅胶板
  [3]  = function() PL2_2Path() end,      -- Area_3 取点样硅胶板
  [4]  = function() PL1_Path(2) end,      -- Area_2 放展缸硅胶板
  [5]  = function() PL1_Path(1) end,      -- Area_2 取展缸硅胶板
  [6]  = function() PL5_Path() end,       -- Area_9 放拍照硅胶板
  [7]  = function() PL5_Path() end,       -- Area_9 取拍照硅胶板
  [8]  = function() PL4_2_Path_Put() end, -- Area_4 放废品到升降机
  [9]  = function() PL7_Path(1) end,      -- Area_7 取暂存收集器
  [10] = function() PL5_Path() end,       -- Area_10 放刮板收集器
  [11] = function() PL5_Path() end,       -- Area_10 取刮板收集器
  [12] = function() PL8_Path() end,       -- Area_11 放收集器到夹持位
  [13] = function() PL9_Path(1) end,       -- Area_11 取收集器/瓶暂存工位
  [14] = function() PL6_Path(2) end,      -- Area_6 放收集组到仓库
  [15] = function() PL8_Path() end,       -- Area_11 放收集工位瓶
  [19] = function() PL6_Path(1) end,      -- Area_6 取收集器组
  [20] = function() PL6_Path(13) end,     -- Area_6 放暂存收集器组
  [21] = function() PL6_Path(16) end,     -- Area_6 取收集瓶组
  [22] = function() PL6_Path(14) end,     -- Area_6 放暂存收集瓶组
  [23] = function() ToolGet_Put() end,    -- 工具区 取/放工具
}

--==================================================================
-- 2. 初始化
--==================================================================
function Init()
  print('[Init] 开始初始化...')
  ModbusConnect()                  -- 唯一一次建立 Modbus 连接
  --print(..tostring(GetHoldRegs(1, 3220, 2, "F32"))
  InitIO()
  tooloa, toolob, tooloc = 0, 0, 0 -- 三个工具工位在位标志
  zcgetQ, zcgetPing = 0, 0         -- 收集器/收集瓶最近工位记录

  ClearReplies(1)
  WritePoint(0)
  WriteError(ERR_NONE)
  WriteStatus(ST_FREE)

  SpeedFactor(20)
  AccJ(20); AccL(20); VelJ(30); VelL(20)
  
  MovJ(P1) -- 回待命点
  print('[Init] 初始化完成，进入主循环')
end

-- 报错处理：写错误码与 Error 状态，等待 PLC 复位完整脉冲后清除
function HandleError(errid)
  print('[HandleError] 报错 errid=' .. tostring(errid))
  WriteError(errid)
  WriteStatus(ST_ERROR)
  print('[HandleError] 等待 PLC 复位上升沿...')
  WaitValue(REG_RESET, 1) -- 等复位上升沿
  print('[HandleError] 收到复位上升沿，等待回落...')
  WaitValue(REG_RESET, 0) -- 等复位回落，避免误清下一次报错
  WriteError(ERR_NONE)
  print('[HandleError] 复位完成，错误已清除')
end

--==================================================================
-- 3. 主循环（严格对齐通信协议状态表）
--    Free → Execute↑ → Busy → (Complete | Error) → Execute↓ → Free
--==================================================================
Init()
while true do
  WriteStatus(ST_FREE)
  print('[主循环] 待命中，等待 Execute 上升沿...')
  --DO(3, ON)
  WaitValue(REG_EXECUTE, 1) -- 等 Execute 上升沿
  local fid = ReadReg(REG_FUNCTION_ID)
  local handler = HANDLERS[fid]
  print('[主循环] 收到执行触发 FunctionID=' .. tostring(fid))

  if not handler then
    print('[主循环] 未知 FunctionID=' .. tostring(fid) .. '，报错')
    HandleError(ERR_NOT_ALLOWED) -- 未知功能：不允许执行
  else
    print('[主循环] 开始执行 FunctionID=' .. tostring(fid))
    WriteStatus(ST_BUSY)
    local ok, err = pcall(handler)
    if ok then
      print('[主循环] 业务执行结束，正在回到待命位置')
      SpeedFactor(30)
      AccJ(50)
      VelJ( 37 )
      CP(2)
      MovJ(P1) -- 回待命点
      --Wait(500)
      print('[主循环] FunctionID=' .. tostring(fid) .. ' 执行完成')
      WriteStatus(ST_DONE)
    else
      print('[主循环] FunctionID=' .. tostring(fid) .. ' 运行时报错: ' .. tostring(err))
      HandleError(ERR_RUNTIME)
    end
  end

  print('[主循环] 等待 Execute 下降沿...')
  WaitValue(REG_EXECUTE, 0) -- 无条件等 Execute 下降沿（防重复执行）
  ClearReplies(0)
  WritePoint(0)
  WriteStatus(ST_FREE)
  print('[主循环] 状态写Free')
end
]]