-- src0.lua —— 主线程：通信协议状态机 + 功能分发
-- 定义见 global.lua（寄存器映射、通信封装、轨迹原语、业务流程）。

-- Version: Lua 5.4.4
----------------------------------


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
