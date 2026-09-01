-- global.lua —— 定义区：寄存器映射、通信封装、IO、轨迹原语与业务流程
-- 主流程见 src0.lua。本文件只定义，不主动执行。

--==================================================================
-- 1. 寄存器映射（ModbusTCP 保持寄存器）
--==================================================================
-- PLC → 机器人（机器人读）
REG_EXECUTE     = 3100        -- 执行触发：0 无 / 1 触发（上升沿启动）
REG_RESET       = 3101        -- 复位触发：0 无 / 1 触发（报错后复位）
REG_FUNCTION_ID = 3102        -- 功能编号
REG_PARAM       = { 3103, 3104, 3105, 3106, 3107,
                    3108, 3109, 3110, 3111, 3112 }  -- ParameterList1..10

-- 机器人 → PLC（机器人写）
REG_STATUS  = 3200            -- 0 空闲 / 1 运行 / 2 完成 / 3 报错
REG_POINT   = 3201            -- 当前点位反馈
REG_ERRORID = 3202            -- 0 无错 / 255 不允许执行 / 其它自定义
REG_RO1     = 3203            -- RO_PL1..RO_PL10 连续：3203..3212

-- 状态码与错误码
ST_FREE, ST_BUSY, ST_DONE, ST_ERROR = 0, 1, 2, 3
ERR_NONE, ERR_NOT_ALLOWED, ERR_RUNTIME = 0, 255, 1

-- 通信地址
ROBOT_IP, ROBOT_PORT = '192.168.0.15', 502

-- 视觉点位（Area: 视觉区域）
-- P59: 预留视觉点位
-- P61: 拍照位 (shijue_yangdian_pz)
-- P62: 相机区 (shi_juegd1)

--==================================================================
-- 2. 通信封装（连接仅在 Init 建立一次，全局复用 id）
--==================================================================
function ModbusConnect()
  local err
  print('[ModbusConnect] 正在连接 ModbusTCP ' .. ROBOT_IP .. ':' .. ROBOT_PORT)
  repeat
    err, id = ModbusCreate(ROBOT_IP, ROBOT_PORT, 1)
    print('[ModbusConnect] ModbusCreate err=' .. tostring(err) .. ' id=' .. tostring(id))
    if err ~= 0 or id == nil then Wait(500) end
  until err == 0 and id ~= nil
  print('[ModbusConnect] 连接成功 id=' .. tostring(id))
end

-- 读取单个保持寄存器，直接返回标量（杜绝忘写 [1] 的隐患）
function ReadReg(addr)
  return GetHoldRegs(id, addr, 1, 'U16')[1]
end

function WriteReg(addr, value)
  print('[WriteReg] addr=' .. addr .. ' val=' .. tostring(value))
  SetHoldRegs(id, addr, 1, { value }, 'U16')
end

--==================================================================
-- 3. 通信握手原语
--==================================================================
-- 阻塞直到寄存器等于目标值（用于边沿检测与子步握手）
function WaitValue(addr, target)
  print('[WaitValue] 等待 addr=' .. addr .. ' == ' .. target)
  while ReadReg(addr) ~= target do
    Wait(20)
  end
  print('[WaitValue] 达成 addr=' .. addr .. ' == ' .. target)
end

-- 阻塞直到寄存器值落入 [lo, hi]，返回该值（用于读取工位选择参数）
function WaitParam(addr, lo, hi)
  print('[WaitParam] 等待 addr=' .. addr .. ' ∈ [' .. lo .. ',' .. hi .. ']')
  while true do
    local v = ReadReg(addr)
    if v >= lo and v <= hi then
      print('[WaitParam] 达成 addr=' .. addr .. ' val=' .. v)
      return v
    end
    Wait(20)
  end
end

--==================================================================
-- 4. 状态与功能回复
--==================================================================
function WriteStatus(s)   WriteReg(REG_STATUS, s) end
function WritePoint(p)    WriteReg(REG_POINT, p) end
function WriteError(e)    WriteReg(REG_ERRORID, e) end

-- 写功能回复 RO_PLn（n = 1..10）
function WriteReply(n, v) WriteReg(REG_RO1 + (n - 1), v) end

function ClearReplies(full)
  if full == 1 then
    for n = 1, 10 do WriteReply(n, 0) end
  else
    for n = 1, 2 do WriteReply(n, 0) end 
    for n = 4, 10 do WriteReply(n, 0) end 
  end
end

--==================================================================
-- 5. 末端执行器 IO
--   DO1 快换 / DO2 夹爪夹紧 / DO3 吸盘 / DO6 夹爪脉冲
--==================================================================
function InitIO()
  print('[InitIO] 初始化末端执行器 IO')
  --DO(1, ON)        -- 快换锁紧
 -- DO(2, OFF)
  --DO(3, OFF)
  DO(5, OFF)
  --DO(6, OFF)
  DO(7, OFF)
  DO(8, OFF)
  print('[InitIO] IO 初始化完成')
end

function Kh_vac(on)        -- 快换：1 吸 / 0 放
  print('[Kh_vac] 快换 ' .. (on == 1 and '吸气' or '放气'))
  Wait(1000); DO(1, on); Wait(1000)
  print('[Kh_vac] 完成')
end

function Xp_vac(on)        -- 吸盘：1 吸 / 0 放
  print('[Xp_vac] 吸盘 ' .. (on == 1 and '吸气' or '放气'))
  Wait(1000); DO(3, on); Wait(1000)
  print('[Xp_vac] 完成')
end

function Jz_vac(release)   -- 夹爪：1 松开 / 0 夹紧
  print('[Jz_vac] 夹爪 ' .. (release == 1 and '松开' or '夹紧'))
  Wait(1000)
  if release == 1 then
    --DO(6, 1); DO(2, 0); DO(6, 0)----存疑
    DO(6, 1); DO(2, 0)
  else
    DO(6, 0); DO(2, 1)
  end
  Wait(1000)
  print('[Jz_vac] 完成')
end

--==================================================================
-- 6. 轨迹原语（接近 → 下探 → 作业 → 抬升 → 退回）
--==================================================================
function Path(ready, target, ht1, ht2, vac)         -- 夹爪，Z 向接近
  print('[Path] 夹爪Z向接近 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { 0, 0, ht1, 0, 0, 0 })
  local pos2 = RelPointUser(target, { 0, 0, ht2, 0, 0, 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(pos1,   { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Jz_vac(vac)
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos1,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path] 夹爪Z向接近 完成')
end

function Path_Z(ready, target, ht1, ht2, vac)       -- 夹爪，放置（Z+ 抬升退出）
  print('[Path_Z] 夹爪放置(Z+抬升) 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { 0, 0, ht1, 0, 0, 0 })
  local pos2 = RelPointUser(target, { 0, 0, ht2, 0, 0, 0 })
  MovJ(ready, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(pos1,  { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(pos2,  { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Jz_vac(vac)
  MovL(pos2,  { user = 0, tool = 1, a = 10, v = 10, cp = 0 })
  MovL(pos1,  { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovJ(ready, { user = 0, tool = 1, a = 100,  v = 50, cp = 20 })
  print('[Path_Z] 夹爪放置 完成')
end

function Path_y(ready, target, ht1, ht2, vac)       -- 夹爪，Y 向接近
  print('[Path_y] 夹爪Y向接近 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { 0, ht1, 0, 0, 0, 0 })
  local pos2 = RelPointUser(target, { 0, ht2, 0, 0, 0, 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(pos1,   { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Jz_vac(vac)
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos1,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path_y] 夹爪Y向接近 完成')
end


function Path_y_z(ready, target, ht2, ht3,ht5, vac)   -- 夹爪，y 偏移 + Z 抬升
  print('[Path_y_z] 夹爪X偏移+Z抬升 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { 0, ht2, ht3, 0, 0, 0 })
  local pos2 = RelPointUser(target, { 0, ht2, ht5, 0, 0, 0 })
  local pos3 = RelPointUser(target, { 0,   0, ht5, 0, 0, 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(pos1,   { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(pos3,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Jz_vac(vac)
  MovL(pos3,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovL(pos1,   { user = 0, tool = 1, a = 30, v = 20, cp = 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path_y_z] 夹爪X偏移+Z抬升 完成')
end


function Path_x_z(ready, target, ht2, ht3,ht5, vac)   -- 夹爪，X 偏移 + Z 抬升
  print('[Path_x_z] 夹爪X偏移+Z抬升 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { ht2, 0, ht3, 0, 0, 0 })
  local pos2 = RelPointUser(target, { ht2, 0, ht5, 0, 0, 0 })
  local pos3 = RelPointUser(target, { 0,   0, ht5, 0, 0, 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(pos1,   { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(pos3,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Jz_vac(vac)
  MovL(pos3,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovL(pos1,   { user = 0, tool = 1, a = 30, v = 20, cp = 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path_x_z] 夹爪X偏移+Z抬升 完成')
end

function Path_XP(ready, target, ht1, ht2, vac)      -- 吸盘，Z 向接近
  print('[Path_XP] 吸盘Z向接近 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { 0, 0, ht1, 0, 0, 0 })
  local pos2 = RelPointUser(target, { 0, 0, ht2, 0, 0, 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(pos1,   { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Xp_vac(vac)
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos1,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path_XP] 吸盘Z向接近 完成')
end

function Path_XP_y(ready, target, ht1, ht2,ht3, vac)    -- 吸盘，Y 偏移接近
  print('[Path_XP_y] 吸盘Y偏移接近 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { 0, ht1, ht2, 0, 0, 0 })
  local pos10 = RelPointUser(target, { 0, ht1, ht3, 0, 0, 0 })
  local pos2 = RelPointUser(target, { 0, 0,   ht3, 0, 0, 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  SpeedFactor(6)
  MovL(pos1,   { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
  MovL(pos10,   { user = 0, tool = 1, a = 20,  v = 15, cp = 2 })
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Xp_vac(vac)
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos10,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovL(pos1,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  SpeedFactor(6)
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path_XP_y] 吸盘Y偏移接近 完成')
end

function Path_XP_x_z(ready, target, ht1, ht2, ht3, vac)  -- 吸盘，X 偏移 + Z 抬升
  print('[Path_XP_x_z] 吸盘X偏移+Z抬升 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { ht1, 0, ht2, 0, 0, 0 })
  local pos2 = RelPointUser(target, { 0,   0, ht2, 0, 0, 0 })
  local pos3 = RelPointUser(target, { 0,   0, ht3, 0, 0, 0 })
  local pos4 = RelPointUser(target, { ht1, 0, ht3, 0, 0, 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(pos1,   { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v =10, cp = 0 })
  MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Xp_vac(vac)
  MovL(pos3,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos4,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path_XP_x_z] 吸盘X偏移+Z抬升 完成')
end

--==================================================================
-- 7. 业务流程
--   说明：每个流程末尾用 WriteReply 回复执行结果；Status 由主循环统一管理。
--==================================================================

-- 展缸：取/放硅胶板。a=1 取（吸盘放气） / a=2 放（吸盘吸气）
-- Area_2(展缸): P3=准备点, P11-P14=展缸1-4(Y+), P15-P18=展缸5-8(Y-)
function PL1_Path(a)
  print('[PL1_Path] 展缸取/放硅胶板 开始 action=' .. tostring(a) .. (a == 1 and ' (取)' or ' (放)'))
  local pts  = { P11, P12, P13, P14, P15, P16, P17, P18 }
  local ydir = { 267, 267, 267, 267, -287, -287, -287, -287 }
  local zdir = { 330, 151, 60, 20, 330, 151, 60, 20 }
  local sel  = WaitParam(REG_PARAM[1], 1, 8)
  print('[PL1_Path] 选择展缸 #' .. sel)
  DO(6, 1)                  ---吸盘气缸下
  while(true)do
    if (DI(2)==ON) then
	    break
    end

  end

  if sel<=4 then	
    SpeedFactor(20)
    MovJ(P75, {user = 0, tool = 1, a = 30, v = 30, cp = 0})---待命点到展缸前过度
    MovJ(P84, {user = 0, tool = 1, a = 30, v = 30, cp = 0})---待命点到展缸前过度
    SpeedFactor(14)
    Path_XP_y(P59, pts[sel], ydir[sel], zdir[sel],15, (a == 1) and 1 or 0)
    SpeedFactor(20)
    MovJ(P84, {user = 0, tool = 1, a = 30, v = 30, cp = 0})---待命点到展缸前过度
    MovJ(P75, {user = 0, tool = 1, a = 30, v = 30, cp = 0})---待命点到展缸前过度
  else
    SpeedFactor(10)
    Path_XP_y(P3, pts[sel], ydir[sel], zdir[sel],15, (a == 1) and 1 or 0)
    SpeedFactor(10)
  end

  WriteReply(1, sel)
  print('[PL1_Path] 展缸 #' .. sel .. ' 完成')
end

-- 点样：放硅胶板
-- Area_3(上样点样): P4=准备点, P19=放硅胶板点位
function PL2_Path()
  print('[PL2_Path] 点样放硅胶板 开始')
  WaitValue(REG_PARAM[2], 1)
  DO(6, 0); Wait(200); DO(2, 1)            -- 吸盘气缸向上（沿用原始时序）
  
  while(true)do
    if (DI(1)==ON) then
	    break
    end

  end
  
  print('[PL2_Path] 夹爪夹紧，开始移动')
  
  --DO(2, 0); Wait(200); DO(6, 1 )          -- 吸盘气缸向下（沿用原始时序）
  SetReadReg_F32()                   ----拍照纠偏
  print("Xt1a, Yt2b=",tostring(Xt1a),tostring(Yt2b))

  --Path_XP_x_z2D(P4, P19, -180, 20, -30,Xt1a,Yt2b, 0)
  ReadReg_err()                      ----拍照完成后读取是否识别成功
  ----------------------------------------------------------------------------------------------------------------------------
  if err==111 then
	
    print('查看相机识别错误！！！！！')
    Pause()
    
    SetReadReg_F32()                   ----拍照纠偏    第二次重新来
    print("Xt1a, Yt2b=",tostring(Xt1a),tostring(Yt2b))

  --Path_XP_x_z2D(P4, P19, -180, 20, -30,Xt1a,Yt2b, 0)
    ReadReg_err()                      ----拍照完成后读取是否识别成功
    
    if err==111 then
      print('查看相机识别错误！！！！！')
      Pause()
    else
      Path_XP_x_z2D(P4, P19, -180, 20, -30,Xt1a,Yt2b, 0)
    end
  else
  
    Path_XP_x_z2D(P4, P19, -180, 20, -30,Xt1a,Yt2b, 0)
  end

  --Path_XP_x_z(P4, P19, -180, 20, -30, 0)
  
  DO(2, 0); Wait(200); DO(6, 1 )          -- 吸盘气缸向下（沿用原始时序）
  while(true)do
    if (DI(2)==ON) then
	    break
    end

  end
  WriteReply(2, 1)
  print('[PL2_Path] 点样放硅胶板 完成')
end

-- 点样：取硅胶板
-- Area_3(上样点样): P4=准备点, P20=取硅胶板点位
function PL2_2Path()
  print('[PL2_2Path] 点样取硅胶板 开始')
  WaitValue(REG_PARAM[2], 2)
  DO(6, 0); Wait(200); DO(2, 1)
  
  while(true)do
    if (DI(1)==ON) then
	    break
    end

  end
  print('[PL2_2Path] 夹爪夹紧，开始移动')
  Path_XP_x_z(P4, P20, -180, -30, 20, 1)
  WriteReply(2, 2)
  print('[PL2_2Path] 点样取硅胶板 完成')
end

-- 升降机：上料（取硅胶板）
-- Area_4: P5=准备点, P21=取物料点, P22=放废料点, P23/P24=预留
function PL4_Path()
  print('[PL4_Path] 升降机上料(取硅胶板) 开始')
  WaitValue(REG_PARAM[4], 1)
  print('[PL4_Path] 收到上料信号，夹爪松开')
  DO(6, 1); Wait(200); DO(2, 0)            -- 夹爪松开
  
  while(true)do
    if (DI(2)==ON) then
	    break
    end

  end
  MovJ(P5, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  local up   = RelPointUser(P21, { 0, 0, 200, 0, 0, 0 })
  local near = RelPointUser(P21, { 0, 0, 20,  0, 0, 0 })
  MovL(up,   { user = 0, tool = 1, a = 100, v = 50, cp = 0 })
  MovL(near, { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
  MovL(P21,  { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  print('[PL4_Path] 到达取板位置，吸盘吸气')
  Xp_vac(1)
  WriteReply(4, 1)
  print('[PL4_Path] 等待上升信号')
  WaitValue(REG_PARAM[4], 2)
  print('[PL4_Path] 收到上升信号，抬升退出')
  MovL(near, { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
  MovL(up,   { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
  MovJ(P5,   { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  WriteReply(4, 2)
  print('[PL4_Path] 升降机上料 完成')
end

-- 升降机：放废料
function PL4_2_Path_Put()
  print('[PL4_2_Path_Put] 升降机放废料 开始')
  WaitValue(REG_PARAM[4], 3)
  print('[PL4_2_Path_Put] 收到放废料信号')
  DO(6, 1); Wait(200); DO(2, 0)----
  
  while(true)do
    if (DI(2)==ON) then
	    break
    end

  end
  MovJ(P5, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  local up   = RelPointUser(P22, { -150, 0, 40, 0, 0, 0 })
  local near = RelPointUser(P22, { 0, 0, 30,  0, 0, 0 })
  MovL(up,   { user = 0, tool = 1, a = 100, v = 50, cp = 0 })
  MovL(near, { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
  MovL(P22,  { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  print('[PL4_2_Path_Put] 到达废料位置，吸盘放气')
  Xp_vac(0)
  MovL(near, { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
  MovL(up,   { user = 0, tool = 1, a = 100, v = 50, cp = 0 })
  MovJ(P5,   { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  WriteReply(4, 3)
  print('[PL4_2_Path_Put] 升降机放废料 完成')
end

-- 刮板/拍照工位：子模式由 ParameterList5 指定，内部多步握手
-- Area_9(刮板区): P63=准备点, P64=放硅胶板, P65=取硅胶板
-- Area_10(吸粉尘区域): P67=准备点, P68=刮板收集器放, P69=刮板收集器取
function PL5_Path()
  local mode = WaitParam(REG_PARAM[5], 1, 7)     -- 等待PLC设置有效子模式
  print('[PL5_Path] 刮板/拍照工位 开始 mode=' .. tostring(mode))

  if mode == 1 then                              -- 放硅胶板
    print('[PL5_Path] 子模式1: 放硅胶板')
    Jz_vac(0)
    
  while(true)do
    if (DI(1)==ON) then
	    break
    end

  end
    --Path_XP_x_z(P63, P64, -180, 30, -20, 0)
    Path_XP_x_z(P63, P65, -180, 30, -20, 0)
    
    DO(2, 0); Wait(200); DO(6, 1 )          -- 吸盘气缸向下（沿用原始时序）
    
  while(true)do
    if (DI(2)==ON) then
	    break
    end

  end
    WriteReply(5, 1)
    print('[PL5_Path] 放硅胶板 完成')

  elseif mode == 2 then                          -- 放收集器到夹持工位
    print('[PL5_Path] 子模式2: 放收集器到夹持工位')
    local far  = RelPointUser(P68, { -180, 0, 0, 0, 0, 0 })
    local near = RelPointUser(P68, { -20,  0, 0, 0, 0, 0 })
    local near_x = RelPointUser(P68, { -1,  0, 0, 0, 0, 0 })
    local near_y = RelPointUser(P68, { 0,  1, 0, 0, 0, 0 })
    local near_x1 = RelPointUser(P68, { 1,  0, 0, 0, 0, 0 })
    local near_y1 = RelPointUser(P68, { 0,  -1, 0, 0, 0, 0 })
    MovJ(P67, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    MovL(far, { user = 0, tool = 1, a = 100, v = 50, cp = 0 })
    SpeedFactor(3)
    MovL(near,{ user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
    MovL(P68, { user = 0, tool = 1, a = 5,  v = 5, cp = 0 })
    WriteReply(5, 2)
    print('[PL5_Path] 放置完成，等待工位夹持')
    WaitValue(REG_PARAM[5], 3)                   -- 等待工位夹持
    Wait(500)
    MovL(near_x1,{ user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    MovL(near_x,{ user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    MovL(P68, { user = 0, tool = 1, a = 5,  v = 5, cp = 0 })
    MovL(near_y1,{ user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    MovL(near_y,{ user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    MovL(P68, { user = 0, tool = 1, a = 5,  v = 5, cp = 0 })
    print('[PL5_Path] 工位夹持完成，夹爪松开退出')
    Jz_vac(1)
    SpeedFactor(7)
    MovL(far, { user = 0, tool = 1, a = 100, v = 50, cp = 0 })
    MovJ(P67, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    WriteReply(5, 3)
    print('[PL5_Path] 放收集器到夹持工位 完成')

  --elseif mode == 4 then                          -- 取收集器（从夹持工位）
   -- print('[PL5_Path] 子模式4: 取收集器(从夹持工位)')
   -- local far  = RelPointUser(P69, { -180, 0, 15,    0, 0, 0 })
   -- local near = RelPointUser(P69, { -20,  0, 15, 0, 0, 0 })
   -- local nearce = RelPointUser(P69, { 0,  0, 15, 0, 0, 0 })
   --[[ local nearce0 = RelPointUser(P69, { 0,  0, 9, 0, 0, 0 })
    local nearce1 = RelPointUser(P69, { -5,  0, 9.4, 0, 0, 0 })
    local nearce2 = RelPointUser(P69, { -10,  0,10.3, 0,0, 0 })
    local nearce3 = RelPointUser(P69, { -13,  0,9.8,0, 0, 0 })
    local nearce4 = RelPointUser(P69, { -15,  0, 9.2, 0, 0, 0 })
    local nearce5 = RelPointUser(P69, { -18,  0, 10, 0, 0, 0 })
    local nearce6 = RelPointUser(P69, { -20,  0, 9.2, 0, 0, 0 })
    local nearce7 = RelPointUser(P69, { -23,  0, 9.5, 0, 0, 0 })
    MovJ(P67, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    MovL(far, { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
    MovL(near,{ user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
    SpeedFactor(8)
    --MovL(P69, { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
    MovL(nearce, { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
    Jz_vac(0)
    WriteReply(5, 4)
    print('[PL5_Path] 夹爪松开，等待工位松开')
    WaitValue(REG_PARAM[5], 5)                   -- 等待工位松开
    print('[PL5_Path] 工位松开，取回收集器')
    Wait(500)
    SpeedFactor(3)
    Wait(500)
    MovL(nearce, { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
    MovL(nearce0, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    Wait(200)
    MovL(nearce1, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    Wait(200)
    MovL(nearce2, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    MovL(nearce3, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    Wait(200)
    MovL(nearce4, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    MovL(nearce5, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    MovL(nearce6, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    MovL(nearce7, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    Wait(500)
    SpeedFactor(8)
    MovL(near,{ user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
    MovL(far, { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
    MovJ(P67, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    WriteReply(5, 5)
    print('[PL5_Path] 取收集器 完成')
]]

  elseif mode == 4 then                          -- 取收集器（从夹持工位）
    print('[PL5_Path] 子模式4: 取收集器(从夹持工位)')
    local far  = RelPointUser(P77, { -180, 0, 0, 0, 0, 0 })
    local near = RelPointUser(P77, { -20,  0, 0, 0, 0, 0 })
    local nearce = RelPointUser(P77, { 0,  0, -1, 0, 0, 0 })
    local nearce0 = RelPointUser(P77, { -10,  0, -1, 0, 0, 0 })
    local nearce1 = RelPointUser(P77, { -30,  0, -1, 0, 0, 0 })
   
    MovJ(P67, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    MovL(far, { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
    MovL(near,{ user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
    SpeedFactor(8)
    MovL(P77, { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
    --MovL(nearce, { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
    Jz_vac(0)
    WriteReply(5, 4)
    print('[PL5_Path] 夹爪松开，等待工位松开')
    WaitValue(REG_PARAM[5], 5)                   -- 等待工位松开
    print('[PL5_Path] 工位松开，取回收集器')
    Wait(500)
    SpeedFactor(3)
    Wait(500)
    MovL(nearce, { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
    MovL(nearce0, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    Wait(200)
    MovL(nearce1, { user = 0, tool = 1, a = 2,  v = 2, cp = 0 })
    Wait(200)
    SpeedFactor(8)
    --MovL(near,{ user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
    MovL(far, { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
    MovJ(P67, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    WriteReply(5, 5)
    print('[PL5_Path] 取收集器 完成')


  elseif mode == 6 then                          -- 取硅胶板
    print('[PL5_Path] 子模式6: 取硅胶板')
    Jz_vac(0)
    
  while(true)do
    if (DI(1)==ON) then
	    break
    end

  end
    --Path_XP_x_z(P63, P65, -180, -30, 30, 1)
    Path_XP_x_z(P63, P64, -180, -30, 30, 1)
    WriteReply(5, 6)
    DO(2, 0); Wait(200); DO(6, 1 )          -- 吸盘气缸向下（沿用原始时序）
    
  while(true)do
    if (DI(2)==ON) then
	    break
    end

  end
    print('[PL5_Path] 取硅胶板 完成')

  --[[elseif mode == 7 then                          -- 取硅胶板（到废料的）
    print('[PL5_Path] 子模式7: 取硅胶板')
    Jz_vac(0)
    --Path_XP_x_z(P63, P65, -180, -30, 30, 1)
    Path_XP_x_z(P63, P76, -180, -30, 30, 1)
    WriteReply(5, 7)
    DO(2, 0); Wait(200); DO(6, 1 )          -- 吸盘气缸向下（沿用原始时序）
    print('[PL5_Path] 取废料-硅胶板 完成')
    ]]
  else
    print('[PL5_Path] 错误: 未知子模式 ' .. tostring(mode))
    error('PL5 未知子模式: ' .. tostring(mode))
  end
end

-- 收集组：取/放/暂存。a=1 取 / a=2 放（仅 1..12 受 a 影响）
-- Area_6(收集组): P7=准备点, P25-P36=收集器组1-12,
--                  P37=暂放收集器, P38=暂放收集瓶, P39=取暂放收集器, P40=取暂放收集瓶
function PL6_Path(a)
  print('[PL6_Path] 收集组取/放 开始 action=' .. tostring(a) .. (a == 1 and ' (取)' or ' (放)'))
  local pts = { P25, P26, P27, P28, P29, P30, P31, P32, P33, P34, P35, P36 }
  local sel = WaitParam(REG_PARAM[6], 1, 16)
  print('[PL6_Path] 选择收集工位 #' .. tostring(sel))
  if sel <= 12 then
    Path_x_z(P7, pts[sel], 200, 12, 10, (a == 2) and 1 or 0)
  elseif sel == 13 then
    print('[PL6_Path] 放暂存收集器组')
    Path_x_z(P4, P37, 0, 100,10, 1)            -- 放暂存收集器组
  elseif sel == 14 then
    print('[PL6_Path] 放暂存收集瓶组')
    Path_y_z(P52, P38, 0, 100,10, 1)            -- 放暂存收集瓶组
  elseif sel == 15 then
    print('[PL6_Path] 取暂存收集器组')
    Path_x_z(P4, P39,  0, 100,10, 0)            -- 取暂存收集器组
  elseif sel == 16 then
    print('[PL6_Path] 取暂存收集瓶组')
    Path_y_z(P52, P40, 0, 100,10, 0)            -- 取暂存收集瓶组
  end
  WriteReply(6, sel)
  print('[PL6_Path] 收集组 #' .. tostring(sel) .. ' 完成')
end

-- 收集器：取/放。a=1 取 / a=2 放
-- Area_7(收集器): P45=准备点, P46-P51=收集器1-6
function PL7_Path(a)
  print('[PL7_Path] 收集器取/放 开始 action=' .. tostring(a) .. (a == 1 and ' (取)' or ' (放)'))
  local pts = { P46, P47, P48, P49, P50, P51 }
  local sel = WaitParam(REG_PARAM[7], 1, 6)
  print('[PL7_Path] 选择收集器工位 #' .. tostring(sel))
  zcgetQ = sel                                   -- 记录工位供收集工位流程复用
  if a == 1 then
    Path(P45, pts[sel], 200, 20, 0)
  else
    Path_Z(P45, pts[sel], 200, 20, 1)
  end
  WriteReply(7, sel)
  print('[PL7_Path] 收集器 #' .. tostring(sel) .. ' 完成')
end

-- 收集瓶：取/放。a=1 取 / a=2 放
-- Area_8(收集瓶): P52=准备点, P53-P58=收集瓶1-6
function PL9_Path(a)
  print('[PL9_Path] 收集瓶取/放 开始 action=' .. tostring(a) .. (a == 1 and ' (取)' or ' (放)'))
  local pts = { P53, P54, P55, P56, P57, P58 }
  local sel = WaitParam(REG_PARAM[9], 1, 6)
  print('[PL9_Path] 选择收集瓶工位 #' .. tostring(sel))
  zcgetPing = sel
  if a == 1 then
    Path(P52, pts[sel], 200, 20, 0)
  else
    Path_Z(P52, pts[sel], 200, 20, 1)
  end
  WriteReply(9, sel)
  print('[PL9_Path] 收集瓶 #' .. tostring(sel) .. ' 完成')
end

-- 收集工位：子模式由 ParameterList8 指定
-- Area_11(收集区): P70=准备点, P71=放入收集瓶, P72=取出收集瓶,
--                  P73=放入收集器位, P74=取出收集器
function PL8_Path()
  local mode       = WaitParam(REG_PARAM[8], 1, 7)  -- 等待PLC设置有效子模式
  ------------------------------------------------------------------------
  local bottlePts  = { P53, P54, P55, P56, P57, P58 }

  local holderPts  = { P78, P79, P80, P81, P82, P83 }       --放到暂存器工位6个点
  
  print('[PL8_Path] 收集工位 开始 mode=' .. tostring(mode))

  if mode == 1 then                              -- 放收集器到夹持工位并退出
    print('[PL8_Path] 子模式1: 放收集器到夹持工位')
    MovJ(P70, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    local far  = RelPointUser(P73, { 0, 200, 0, 0, 0, 0 })
    local near = RelPointUser(P73, { 0, 20,  0, 0, 0, 0 })
    MovL(far, { user = 0, tool = 1, a = 100, v = 50, cp = 0 })
    MovL(near,{ user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
    MovL(P73, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
    WriteReply(8, 1)
    print('[PL8_Path] 放置完成，等待工位夹持')
    WaitValue(REG_PARAM[8], 2)                   -- 等待工位夹持
    print('[PL8_Path] 工位夹持完成，夹爪松开退出')
    Jz_vac(1)
    MovL(near,{ user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
    MovL(far, { user = 0, tool = 1, a = 30, v = 20, cp = 0 })
    MovJ(P70, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    WriteReply(8, 2)
    print('[PL8_Path] 放收集器到夹持工位 完成')

  elseif mode == 3 then                          -- 放收集瓶
    print('[PL8_Path] 子模式3: 放收集瓶')
    Path(P70, P71, 100, 20, 1)
    WriteReply(8, 3)
    print('[PL8_Path] 放收集瓶 完成')

  elseif mode == 4 then                          -- 取收集瓶
    print('[PL8_Path] 子模式4: 取收集瓶')
    Path(P70, P72, 100, 20, 0)
    WriteReply(8, 4)
    print('[PL8_Path] 取收集瓶 完成')

  elseif mode == 5 then                          -- 放收集瓶到暂存工位
  
  ------------------------------------------------------------------------------------
  
    local sel1 = WaitParam(REG_PARAM[9], 1, 6)         --等待PLC发送放瓶号位
    print('[PL8_Path] 子模式5: 放收集瓶到暂存工位 sel1=' .. tostring(sel1))
    if sel1 >= 1 and sel1 <= 6 then
      Path_Z(P52, bottlePts[sel1], 200, 5, 1)      ---高度加高
      
    end
  
    --[[print('[PL8_Path] 子模式5: 放收集瓶到暂存工位 zcgetPing=' .. tostring(zcgetPing))
    if zcgetPing >= 1 and zcgetPing <= 6 then
      --Path(P52, bottlePts[zcgetPing], 200, 20, 1)      ---高度加高
      Path_Z(P52, bottlePts[zcgetPing], 200, 25, 1)      ---高度加高
      
    end]]
    
    WriteReply(8, 5)
    print('[PL8_Path] 放收集瓶到暂存工位 完成')

  elseif mode == 6 then                          -- 去取收集器
    --Path_y(P70, P74, 200, 20, 0)
    ------------------------------------------------------
    print('[PL8_Path] 子模式6: 去取收集器')
    MovJ(P70, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    local far  = RelPointUser(P74, { 0, 200, 0, 0, 0, 0 })
    local near = RelPointUser(P74, { 0, 20,  0, 0, 0, 0 })
    MovL(far, { user = 0, tool = 1, a = 100, v = 50, cp = 0 })
    MovL(near,{ user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
    MovL(P74, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
    Jz_vac(0)
    WriteReply(8, 6)
    print('[PL8_Path] 到达，等待工位松开')
    WaitValue(REG_PARAM[8], 7)                   -- 等待工位夹持
    print('[PL8_Path] 工具夹持完成，夹爪退出')
    MovL(near,{ user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
    MovL(far, { user = 0, tool = 1, a = 30, v = 30, cp = 0 })
    MovJ(P70, { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
    print('[PL8_Path] 去取收集器 完成')
  --elseif mode == 7 then                          -- 放收集器到暂存工位
    local sel2 = WaitParam(REG_PARAM[7], 1, 6)        --等待PLC发送放收集器号位
    print('[PL8_Path] 子模式7: 放收集器到暂存工位 zcgetQ=' .. tostring(sel2))
     if sel2 >= 1 and sel2 <= 6 then
      
      --Path_Z(P45, holderPts[sel2], 200, 25, 1)        --高度加高
      Path_Z(P45, holderPts[sel2], 200, 5, 1)        --高度加高
      
    end
  
  -------------------------------------------------------------------------
    --[[print('[PL8_Path] 子模式7: 放收集器到暂存工位 zcgetQ=' .. tostring(zcgetQ))
    if zcgetQ >= 1 and zcgetQ <= 6 then
      ---Path(P45, holderPts[zcgetQ], 200, 20, 1)        --高度加高
      Path_Z(P45, holderPts[zcgetQ], 200, 25, 1)        --高度加高
      
    end]]
    
    
    WriteReply(8, 7)
    print('[PL8_Path] 放收集器到暂存工位 完成')

  else
    print('[PL8_Path] 错误: 未知子模式 ' .. tostring(mode))
    error('PL8 未知子模式: ' .. tostring(mode))
  end
end

--==================================================================
-- 8. 工具：取/放（快换）。tooloa/toolob/tooloc 记录各工位是否在位
--==================================================================
function GetTool_Path(slot)
  print('[GetTool_Path] 取工具 slot=' .. tostring(slot))
  local pts = { P8, P9, P10 }
  local p   = pts[slot]
  MovJ(P2, { user = 0, tool = 1, a = 100, v = 50, cp = 50 })
  local up   = RelPointUser(p, { 0, 0, 200, 0, 0, 0 })
  local near = RelPointUser(p, { 0, 0, 20,  0, 0, 0 })
  MovL(up,   { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(near, { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(p,    { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  print('[GetTool_Path] 到达工具位，快换放气')
  Kh_vac(0)
  DO(6, 1)
  MovL(near, { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(up,   { user = 0, tool = 1, a = 30, v = 20, cp = 20 })
  MovJ(P2,   { user = 0, tool = 1, a = 100, v = 50, cp = 50 })
  Wait(500)
  WriteReply(3, slot)
  print('[GetTool_Path] 取工具 slot=' .. tostring(slot) .. ' 完成')
end

function PutTool_Path(slot)
  print('[PutTool_Path] 放工具 slot=' .. tostring(slot))
  local pts = { P8, P9, P10 }
  local p   = pts[slot]
  MovJ(P2, { user = 0, tool = 1, a = 100, v = 50, cp = 50 })
  if slot == 1 then DO(6, 1) end                 -- 仅工位1：放置前夹爪脉冲（沿用原程序）
  local up   = RelPointUser(p, { 0, 0, 200, 0, 0, 0 })
  local near = RelPointUser(p, { 0, 0, 20,  0, 0, 0 })
  MovL(up,   { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(near, { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(p,    { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  print('[PutTool_Path] 到达工具位，快换吸气')
  Kh_vac(1)
  DO(6, 0)
  MovL(near, { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(up,   { user = 0, tool = 1, a = 30, v = 20, cp = 20 })
  MovJ(P2,   { user = 0, tool = 1, a = 100, v = 50, cp = 50 })
  print('[PutTool_Path] 放工具 slot=' .. tostring(slot) .. ' 完成')
end

-- 取期望工具：先归还当前在手工具，再取目标工具
function ToolGet_Put()
  local want = ReadReg(REG_PARAM[3])             -- 3105：期望工具号 1/2/3
  print('[ToolGet_Put] 期望工具 #' .. tostring(want) .. ' 当前 tooloa=' .. tostring(tooloa) .. ' toolob=' .. tostring(toolob) .. ' tooloc=' .. tostring(tooloc))
  if want == 1 then
    if toolob == 1 then print('[ToolGet_Put] 先归还工具#2'); PutTool_Path(2); toolob = 0
    elseif tooloc == 1 then print('[ToolGet_Put] 先归还工具#3'); PutTool_Path(3); tooloc = 0 end
    GetTool_Path(1); tooloa = 1
  elseif want == 2 then
    if tooloa == 1 then print('[ToolGet_Put] 先归还工具#1'); PutTool_Path(1); tooloa = 0
    elseif tooloc == 1 then print('[ToolGet_Put] 先归还工具#3'); PutTool_Path(3); tooloc = 0 end
    GetTool_Path(2); toolob = 1
  elseif want == 3 then
    if tooloa == 1 then print('[ToolGet_Put] 先归还工具#1'); PutTool_Path(1); tooloa = 0
    elseif toolob == 1 then print('[ToolGet_Put] 先归还工具#2'); PutTool_Path(2); toolob = 0 end
    GetTool_Path(3); tooloc = 1
  end
  print('[ToolGet_Put] 完成 tooloa=' .. tostring(tooloa) .. ' toolob=' .. tostring(toolob) .. ' tooloc=' .. tostring(tooloc))
end

---------------------------------------------------------------------------------------------------------------------------------------------------------------
--ht2=30
--ht5=-30
--ht3=0
function biao_ding(ready, target, ht2, ht5,ht3, vac)   
  print('标定 开始 ')
  local pos1 = RelPointUser(target, { ht2, ht2,0, 0, 0, 0 })
  local pos2 = RelPointUser(target, { ht3, ht2,0, 0, 0, 0 })
  local pos3 = RelPointUser(target, { ht5, ht2,0, 0, 0, 0 })
  
  local pos4 = RelPointUser(target, { ht5, ht3,0, 0, 0, 0 })
  local pos5 = RelPointUser(target, { ht3, ht3,0, 0, 0, 0 })
  local pos6 = RelPointUser(target, { ht2, ht3,0, 0, 0, 0 })
  
  local pos7 = RelPointUser(target, { ht2, ht5,0, 0, 0, 0 })
  local pos8 = RelPointUser(target, { ht3, ht5,0, 0, 0, 0 })
  local pos9 = RelPointUser(target, { ht5, ht5,0, 0, 0, 0 })
  
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('准备运行 ')
  Pause()
  MovL(pos1,   { user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
  print('运行 1完成',pos1)
  Pause()
  MovL(pos2,   { user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
  print('运行 2完成',pos2)
  Pause()
  MovL(pos3,   { user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
  print('运行 3完成',pos3)
  Pause()
  MovL(pos4,   { user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
  print('运行 4完成',pos4)
  Pause()
  MovL(pos5,   { user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
  print('运行 5完成',pos5)
  Pause()
  MovL(pos6,   { user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
  print('运行 6完成',pos6)
  Pause()
  MovL(pos7,   { user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
  print('运行 7完成',pos7)
  Pause()
  MovL(pos8,   { user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
  print('运行 8完成',pos8)
  Pause()
  MovL(pos9,   { user = 0, tool = 1, a = 15,  v = 15, cp = 0 })
  print('运行 9完成',pos9)
  Pause()
  print('运行 完成')
end
  --- GetHoldRegs(0, 3220, 2, "F32")
   --- print(tostring(GetHoldRegs(0, 3220, 2, "F32")[1]))
    
function ReadReg_F321(addr1)  
  --local regdata
  print(addr1)
  regdata = GetHoldRegs(id, addr1, 2, 'F32')[1]
  print('XY=',regdata)
  SetHoldRegs(id, 3300, 1, {0}, 'U16')
  SetHoldRegs(id, 3301, 1, {59}, 'U16')
  --GetHoldRegs(id, 0, 2, "F32")[1]
  --print(tostring(GetHoldRegs(0, addr1, 2, "F32")[1]))
  --print(tostring(GetHoldRegs(0, addr1, 2, "F32")[1]))
  return regdata
end

function ReadReg_err()  
err = GetHoldRegs(id, 3302, 1, 'U16')[1]
  print("3302=",err)
  SetHoldRegs(id, 3300, 1, {0}, 'U16')
  SetHoldRegs(id, 3301, 1, {59}, 'U16')

end
function SetReadReg_F32()
 -- MovJ(P1)
  MovJ(P1, {user = 0, tool = 1, a = 20, v = 50, cp = 0})    ---拍照过度
  DO(7, ON)
  SetHoldRegs(id, 3220, 2, {0}, "F32")
  SetHoldRegs(id, 3222, 2, {0}, "F32")
  SetHoldRegs(id, 3224, 2, {0}, "F32")                      -----角度
  SetHoldRegs(id, 3300, 1, {0}, 'U16')
  SetHoldRegs(id, 3302, 1, {0}, 'U16')
  err = GetHoldRegs(id, 3302, 1, 'U16')[1]
  print("3302=",err)
  Wait(1000)
  MovJ(P86, {user = 0, tool = 1, a = 20, v = 50, cp = 0})    ---拍照位
  
  Wait(3000)
  --print('[WriteReg] addr=' .. addr .. ' val=' .. tostring(value))
  SetHoldRegs(id, 3300, 1, {49}, 'U16')
  SetHoldRegs(id, 3301, 1, {59}, 'U16')
 
  Wait(2000)
  
   Xt1a = ReadReg_F321(3220)
   Yt2b = ReadReg_F321(3222)
   ZRZ = ReadReg_F321(3224)

   -----------------------
  local pos1 = RelPointUser(P86, { 0, 0, 0, 0, 0, ZRZ })
  print("拍照+角度")
  MovL(pos1,   { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  SetHoldRegs(id, 3300, 1, {49}, 'U16')
  SetHoldRegs(id, 3301, 1, {59}, 'U16')
  Wait(2000)
   Xt1a = ReadReg_F321(3220)
   Yt2b = ReadReg_F321(3222)

  MovJ(P1, {user = 0, tool = 1, a = 20, v = 50, cp = 0})    ---拍照过度
  DO(7, OFF)
  
end
  -------------------------------------------------------------
function Path_XP_x_z2D(ready, target, ht1, ht2, ht3,Xt1, Yt2, vac)  -- 吸盘，X 偏移 + Z 抬升+2D相机纠偏的位置，放/上样位/刮板区
  print('[Path_XP_x_z] 吸盘X偏移+Z抬升 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { ht1, 0, ht2, 0, 0, 0 })
  local pos2 = RelPointUser(target, { Xt1, Yt2, ht2, 0, 0, 0 })
  local pos2_D = RelPointUser(target, { Xt1, Yt2, 0, 0, 0, 0 })
  local pos3 = RelPointUser(target, { Xt1,  Yt2, ht3, 0, 0, 0 })
  local pos4 = RelPointUser(target, { ht1, 0, ht3, 0, 0, 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(pos1,   { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v =10, cp = 0 })
  MovL(pos2_D, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  --MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Xp_vac(vac)
  MovL(pos3,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos4,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path_XP_x_z] 吸盘X偏移+Z抬升 完成')
end

 -------------------------------------------------------------
function Path_XP_x_Rz2D(ready, target, ht1, ht2, ht3,Xt1, Yt2,Zt3, vac)  -- 吸盘，X 偏移 + Z 抬升+2D相机纠偏的位置，放/上样位/刮板区
  print('[Path_XP_x_z] 吸盘X偏移+Z抬升 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { ht1, 0, ht2, 0, 0, Zt3 })
  local pos2 = RelPointUser(target, { Xt1, Yt2, ht2, 0, 0, Zt3 })
  local pos2_D = RelPointUser(target, { Xt1, Yt2, 0, 0, 0, Zt3 })
  local pos3 = RelPointUser(target, { Xt1,  Yt2, ht3, 0, 0, Zt3 })
  local pos4 = RelPointUser(target, { ht1, 0, ht3, 0, 0, Zt3 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  MovL(pos1,   { user = 0, tool = 1, a = 20,  v = 15, cp = 0 })
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v =10, cp = 0 })
  MovL(pos2_D, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  --MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Xp_vac(vac)
  MovL(pos3,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos4,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path_XP_x_z] 吸盘X偏移+Z抬升 完成')
end

function Path_XP_y2D(ready, target, ht1, ht2,ht3,Xt1, Yt2, vac)    -- 吸盘，Y 偏移接近--放展缸视觉2D相机纠偏的位置
  print('[Path_XP_y] 吸盘Y偏移接近 开始 vac=' .. tostring(vac))
  local pos1 = RelPointUser(target, { 0, ht1, ht2, 0, 0, 0 })
  local pos10 = RelPointUser(target, { Xt1, ht1, ht3, 0, 0, 0 })
  
  local pos2 = RelPointUser(target, { Xt1, Yt2,   ht3, 0, 0, 0 })
  local pos2_D = RelPointUser(target, { Xt1, Yt2,   ht3, 0, 0, 0 })
  
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  SpeedFactor(6)
  MovL(pos1,   { user = 0, tool = 1, a = 30,  v = 30, cp = 0 })
  MovL(pos10,   { user = 0, tool = 1, a = 20,  v = 15, cp = 2 })
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  --MovL(target, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  MovL(pos2_D, { user = 0, tool = 1, a = 10,  v = 5, cp = 0 })
  Xp_vac(vac)
  MovL(pos2,   { user = 0, tool = 1, a = 10,  v = 10, cp = 0 })
  MovL(pos10,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  MovL(pos1,   { user = 0, tool = 1, a = 30,  v = 20, cp = 0 })
  SpeedFactor(6)
  MovJ(ready,  { user = 0, tool = 1, a = 100, v = 50, cp = 20 })
  print('[Path_XP_y] 吸盘Y偏移接近 完成')
end
