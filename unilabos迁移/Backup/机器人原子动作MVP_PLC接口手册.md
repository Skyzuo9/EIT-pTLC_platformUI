# 机器人原子动作 MVP PLC 接口手册草案

## 1. 目标与边界

本文档定义客户中控接入 pTLC 机器人原子动作 MVP 时，PLC 与机器人侧需要新增或约定的最小接口。

MVP 只包含 3 个动作：

| 动作 | 含义 | 是否运动 | 机器人执行方式 |
| --- | --- | --- | --- |
| `robot.query` | 查询机器人当前状态与位姿 | 否 | `GetPose` / `GetAngle` |
| `robot.move_j` | 移动到客户中控下发的任意笛卡尔 pose | 是 | `CheckMovJ` 后 `MovJ` |
| `robot.home` | 回机器人待命/原点 | 是 | `MovJ(P1)` |

不属于 MVP 的内容：

- `MovL`
- 路径规划
- 碰撞检查
- 点位库维护
- 多动作队列
- 后台实时位姿发布线程
- mock PLC 实现

客户中控负责维护点位与碰撞检查；PLC 负责模式门控、安全准入、互锁和动作状态；机器人只执行 PLC 授权后的动作。

## 2. 总体链路

```text
客户中控
  -> HTTP API
  -> pTLC 上位机
  -> OPC UA
  -> PLC 安全准入与动作 FSM
  -> ModbusTCP
  -> 机器人 Lua FunctionID
```

HTTP 不是上位机直连机器人。上位机不绕过 PLC 直接写机器人 Modbus，PLC 保留最终准入权。

## 3. 机器人手册依据

机器人手册已经支持本 MVP 所需的基础能力：

- `MovJ({pose={x,y,z,rx,ry,rz}}, {user=..., tool=..., a=..., v=..., cp=...})`
- `GetPose(user_index, tool_index)` 获取实时笛卡尔位姿
- `GetAngle()` 获取实时关节角
- `CheckMovJ(P, opts)` 检查关节运动可运行性
- Modbus `F32` 为 32 位浮点，占 2 个寄存器

本设计使用 `F32` 传输 pose，单位约定为：

| 字段 | 单位 |
| --- | --- |
| `x/y/z` | mm |
| `rx/ry/rz` | degree |
| `a/v/cp` | percent，0-100 |

手册索引：

| 能力 | 手册位置 | 本方案用途 |
| --- | --- | --- |
| pose 形式 `MovJ` | `资料/机器人/DobotStudio Pro 用户手册_V4.6.5_20251024_cn_page201-400/full.md:7442` | 支持客户中控下发任意 pose 后由机器人执行 `MovJ` |
| `GetPose` | `资料/机器人/DobotStudio Pro 用户手册_V4.6.5_20251024_cn_page401-551/full.md:5339` | 支持 `robot.query` 和动作完成后的 pose 反馈 |
| `CheckMovJ` | `资料/机器人/DobotStudio Pro 用户手册_V4.6.5_20251024_cn_page401-551/full.md:5442` | 在 `MovJ` 前做机器人侧可达性检查 |
| `F32` 寄存器 | `资料/机器人/DobotStudio Pro 用户手册_V4.6.5_20251024_cn_page401-551/full.md:6652` | 用 2 个保持寄存器传输 1 个 REAL/F32 |
| `GetHoldRegs` | `资料/机器人/DobotStudio Pro 用户手册_V4.6.5_20251024_cn_page401-551/full.md:6730` | 机器人 Lua 读取 PLC 写入的目标 pose |
| `SetHoldRegs` | `资料/机器人/DobotStudio Pro 用户手册_V4.6.5_20251024_cn_page401-551/full.md:6769` | 机器人 Lua 写回 pose/joint 反馈 |

## 4. PLC 对上位机 OPC UA 变量建议

变量名前缀建议统一为 `RobotAtom_`。PLC 可按实际工程命名调整，但语义建议保持一致。

### 4.1 控制变量

| 变量 | 类型 | 方向 | 说明 |
| --- | --- | --- | --- |
| `RobotAtom_Enable` | BOOL | PC -> PLC | 上升沿提交动作；下降沿清除完成态 |
| `RobotAtom_ActionId` | INT | PC -> PLC | `1=query`, `2=move_j`, `3=home` |
| `RobotAtom_RequestId` | UDINT | PC -> PLC | 请求序号，用于幂等与日志关联 |
| `RobotAtom_User` | INT | PC -> PLC | 用户坐标系，默认 0 |
| `RobotAtom_Tool` | INT | PC -> PLC | 工具坐标系，默认 1 |
| `RobotAtom_AccPercent` | INT | PC -> PLC | 关节加速度比例，建议默认 20 |
| `RobotAtom_VelPercent` | INT | PC -> PLC | 关节速度比例，建议默认 20 |
| `RobotAtom_CpPercent` | INT | PC -> PLC | 平滑过渡比例，建议默认 0 |
| `RobotAtom_TargetPose[1..6]` | REAL | PC -> PLC | `x,y,z,rx,ry,rz`，仅 `move_j` 必填 |
| `RobotAtom_TimeoutMs` | UDINT | PC -> PLC | 动作超时，默认由 PLC 给定 |

### 4.2 状态变量

| 变量 | 类型 | 方向 | 说明 |
| --- | --- | --- | --- |
| `RobotAtom_Busy` | BOOL | PLC -> PC | 动作执行中 |
| `RobotAtom_Done` | BOOL | PLC -> PC | 动作完成锁存，等待 `Enable=FALSE` 清除 |
| `RobotAtom_Error` | BOOL | PLC -> PC | 动作失败锁存 |
| `RobotAtom_Step` | INT | PLC -> PC | PLC 侧动作 FSM 子步骤 |
| `RobotAtom_Status` | INT | PLC -> PC | 聚合状态，见 4.3 |
| `RobotAtom_RejectCode` | INT | PLC -> PC | PLC 准入拒绝原因 |
| `RobotAtom_ErrorCode` | INT | PLC -> PC | PLC 或机器人错误码 |
| `RobotAtom_ActiveRequestId` | UDINT | PLC -> PC | 当前正在处理的请求序号 |
| `RobotAtom_CurrentPose[1..6]` | REAL | PLC -> PC | 最近一次机器人反馈 pose |
| `RobotAtom_CurrentJoint[1..6]` | REAL | PLC -> PC | 最近一次机器人反馈关节角 |

### 4.3 聚合状态码

| 值 | 名称 | 含义 |
| --- | --- | --- |
| 0 | `IDLE` | 空闲 |
| 10 | `ACCEPTED` | PLC 已接受请求 |
| 20 | `RUNNING` | 动作执行中 |
| 30 | `DONE` | 完成 |
| 40 | `REJECTED` | PLC 拒绝执行 |
| 50 | `ERROR` | 执行错误 |
| 60 | `TIMEOUT` | PLC 等待机器人超时 |

### 4.4 PLC 准入建议

PLC 在写机器人 `Execute=1` 前至少检查：

- 当前模式允许外部原子动作，例如 `EXTERNAL_CONTROL`
- 急停、安全门、气压等安全条件正常
- 当前没有 pTLC 自动任务占用机器人
- 机器人反馈 `Status=FREE`
- 参数范围合法
- `move_j` 的目标 pose 不为空，速度/加速度未超过现场限制

客户中控已做碰撞检查，但 PLC 仍保留拒绝权。

## 5. PLC 与机器人 Modbus 寄存器建议

现有机器人程序已使用：

| 地址 | 用途 |
| --- | --- |
| `3100` | `REG_EXECUTE` |
| `3101` | `REG_RESET` |
| `3102` | `REG_FUNCTION_ID` |
| `3103..3112` | `REG_PARAM[1..10]` |
| `3200` | `REG_STATUS` |
| `3201` | `REG_POINT` |
| `3202` | `REG_ERRORID` |
| `3203..3212` | `REG_RO1..10` |
| `3220/3222` | 视觉纠偏 F32 |
| `3300/3301/3302` | 视觉纠偏触发/状态 |

为避免与现有视觉纠偏通信冲突，原子动作新增寄存器建议使用独立地址块：

### 5.1 机器人动作参数块：PLC -> Robot

| 地址 | 类型 | 名称 | 说明 |
| --- | --- | --- | --- |
| `3400` | U16 | `ATOM_USER` | 用户坐标系 |
| `3401` | U16 | `ATOM_TOOL` | 工具坐标系 |
| `3402` | U16 | `ATOM_ACC` | 加速度百分比 |
| `3403` | U16 | `ATOM_VEL` | 速度百分比 |
| `3404` | U16 | `ATOM_CP` | 平滑过渡百分比 |
| `3405` | U16 | `ATOM_RESERVED` | 预留 |
| `3410..3411` | F32 | `ATOM_TARGET_X` | 目标 X |
| `3412..3413` | F32 | `ATOM_TARGET_Y` | 目标 Y |
| `3414..3415` | F32 | `ATOM_TARGET_Z` | 目标 Z |
| `3416..3417` | F32 | `ATOM_TARGET_RX` | 目标 RX |
| `3418..3419` | F32 | `ATOM_TARGET_RY` | 目标 RY |
| `3420..3421` | F32 | `ATOM_TARGET_RZ` | 目标 RZ |

### 5.2 机器人反馈块：Robot -> PLC

| 地址 | 类型 | 名称 | 说明 |
| --- | --- | --- | --- |
| `3440..3441` | F32 | `ATOM_FB_X` | 当前 X |
| `3442..3443` | F32 | `ATOM_FB_Y` | 当前 Y |
| `3444..3445` | F32 | `ATOM_FB_Z` | 当前 Z |
| `3446..3447` | F32 | `ATOM_FB_RX` | 当前 RX |
| `3448..3449` | F32 | `ATOM_FB_RY` | 当前 RY |
| `3450..3451` | F32 | `ATOM_FB_RZ` | 当前 RZ |
| `3460..3461` | F32 | `ATOM_FB_J1` | 当前 J1 |
| `3462..3463` | F32 | `ATOM_FB_J2` | 当前 J2 |
| `3464..3465` | F32 | `ATOM_FB_J3` | 当前 J3 |
| `3466..3467` | F32 | `ATOM_FB_J4` | 当前 J4 |
| `3468..3469` | F32 | `ATOM_FB_J5` | 当前 J5 |
| `3470..3471` | F32 | `ATOM_FB_J6` | 当前 J6 |
| `3480` | U16 | `ATOM_CHECK_RESULT` | `CheckMovJ` 返回值 |
| `3481` | U16 | `ATOM_LAST_ACTION` | 最近执行的原子动作 FunctionID |

说明：若现场机器人寄存器映射要求使用 PLC 地址 `41025+` 对应脚本地址 `1024+`，则以上地址需要由 PLC/机器人调试人员按实际地址体系平移。本文使用的是现有 Lua 程序中的脚本地址风格。

## 6. Lua FunctionID 建议

沿用现有主循环：

```text
Wait Execute=1
Read FunctionID
Write Status=BUSY
Execute handler
Write Status=DONE/ERROR
Wait Execute=0
Write Status=FREE
```

新增 FunctionID：

| FunctionID | 名称 | 行为 |
| --- | --- | --- |
| 24 | `QUERY_STATUS_POSE` | 读取 `GetPose` / `GetAngle` 并写入反馈块 |
| 25 | `MOVEJ_POSE` | 读取目标 pose，`CheckMovJ` 通过后执行 `MovJ` |
| 26 | `HOME` | 执行 `MovJ(P1)`，然后写入反馈块 |

### 6.1 `QUERY_STATUS_POSE`

机器人侧逻辑：

1. `GetPose(user, tool)`
2. `GetAngle()`
3. 写入 `3440..3471`
4. `ATOM_LAST_ACTION=24`
5. 返回 `DONE`

该动作不移动，不需要新增后台线程。

### 6.2 `MOVEJ_POSE`

机器人侧逻辑：

1. 读取 `3400..3421`
2. 构造：

```lua
local target = {pose={x, y, z, rx, ry, rz}}
local opts = {user=user, tool=tool, a=acc, v=vel, cp=cp}
```

3. `local check = CheckMovJ(target, opts)`
4. 写 `ATOM_CHECK_RESULT=check`
5. 若 `check ~= 0`，抛出错误，主循环写 `Status=ERROR`
6. 若 `check == 0`，执行 `MovJ(target, opts)`
7. 执行结束后写入当前 pose/joint 反馈块
8. `ATOM_LAST_ACTION=25`

### 6.3 `HOME`

机器人侧逻辑：

1. `MovJ(P1)`
2. 写入当前 pose/joint 反馈块
3. `ATOM_LAST_ACTION=26`

注意：现有主循环在所有 handler 成功后会无条件 `MovJ(P1)`。若保留这个行为，则 `MOVEJ_POSE` 完成后会立即回原点，不符合“移动到任意 pose 并停留”的语义。因此实现时需要调整主循环：

- 对既有业务 FunctionID `1..23` 保持完成后回 `P1`
- 对原子动作 FunctionID `24..26` 不自动追加回 `P1`
- `HOME` 动作自身负责回 `P1`

## 7. PLC 动作 FSM 建议

```text
0 IDLE
10 VALIDATE_PARAMS
20 WAIT_ROBOT_FREE
30 WRITE_ROBOT_PARAMS
40 TRIGGER_ROBOT_EXECUTE
50 WAIT_ROBOT_BUSY
60 WAIT_ROBOT_DONE_OR_ERROR
70 READ_ROBOT_FEEDBACK
80 CLEAR_ROBOT_EXECUTE
90 DONE
900 ERROR
```

关键规则：

- PLC 写机器人 `Execute=1` 前必须先写完 FunctionID 和参数。
- PLC 读到机器人 `Status=DONE` 后，先读取反馈块，再写 `Execute=0`。
- PLC 必须等待机器人回到 `Status=FREE` 后才允许下一次动作。
- PLC 拒绝动作时，不写机器人 `Execute=1`。
- `RobotAtom_Done/Error` 应锁存到上位机写 `RobotAtom_Enable=FALSE`。

## 8. 错误码建议

### 8.1 PLC 拒绝码 `RobotAtom_RejectCode`

| 值 | 名称 | 含义 |
| --- | --- | --- |
| 0 | `NONE` | 无拒绝 |
| 1 | `MODE_NOT_ALLOWED` | 当前模式不允许外部控制 |
| 2 | `ESTOP_ACTIVE` | 急停中 |
| 3 | `ROBOT_BUSY` | 机器人非空闲 |
| 4 | `LOCAL_TASK_RUNNING` | 本地 pTLC 任务运行中 |
| 5 | `INVALID_ACTION` | 未知动作 |
| 6 | `INVALID_PARAM` | 参数非法 |
| 7 | `SAFETY_NOT_READY` | 安全条件不满足 |
| 8 | `TIMEOUT` | 等待机器人超时 |

### 8.2 机器人错误码 `REG_ERRORID`

现有：

| 值 | 名称 | 含义 |
| --- | --- | --- |
| 0 | `ERR_NONE` | 无错误 |
| 1 | `ERR_RUNTIME` | 运行时错误 |
| 255 | `ERR_NOT_ALLOWED` | 未知 FunctionID 或不允许执行 |

建议新增：

| 值 | 名称 | 含义 |
| --- | --- | --- |
| 10 | `ERR_ATOM_INVALID_PARAM` | 原子动作参数非法 |
| 11 | `ERR_ATOM_CHECK_MOVJ_FAILED` | `CheckMovJ` 未通过 |
| 12 | `ERR_ATOM_POSE_READ_FAILED` | 目标 pose 读取失败 |
| 13 | `ERR_ATOM_FEEDBACK_WRITE_FAILED` | 反馈写入失败 |

## 9. HTTP API 最小形态

HTTP API 属于上位机对客户中控的入口。MVP 可先提供同步等待接口，内部仍通过 PLC FSM 执行。

### 9.1 查询

```http
POST /api/robot/actions/query
```

响应包含：

```json
{
  "request_id": 1001,
  "status": "DONE",
  "pose": [0, 0, 0, 0, 0, 0],
  "joint": [0, 0, 0, 0, 0, 0],
  "robot_status": 0,
  "error_code": 0
}
```

### 9.2 MovJ

```http
POST /api/robot/actions/move-j
Content-Type: application/json
```

```json
{
  "request_id": 1002,
  "pose": [300.0, 200.0, 300.0, 180.0, 0.0, 0.0],
  "user": 0,
  "tool": 1,
  "acc_percent": 20,
  "vel_percent": 20,
  "cp_percent": 0,
  "timeout_ms": 60000
}
```

### 9.3 Home

```http
POST /api/robot/actions/home
```

## 10. MVP 实施顺序

建议分三步：

1. PLC 与机器人侧先按本文档确认变量和寄存器地址，不接 HTTP。
2. 修改机器人 Lua：新增寄存器读写函数、3 个 handler、原子动作不自动回 `P1`。
3. 修改上位机：增加 HTTP API 与 OPC UA 写读封装，不实现 mock。

## 11. 后续 Lua 实现检查点

后续真正修改机器人程序时，建议只做以下最小改动：

| 文件 | 必须改动 | 不建议改动 |
| --- | --- | --- |
| `机器人程序/HHWS_tjcx2v01/global.lua` | 新增原子动作寄存器常量、F32 读写函数、pose/joint 反馈函数、`QUERY_STATUS_POSE`、`MOVEJ_POSE`、`HOME` | 不改既有 `PL1..PL9` 业务路径 |
| `机器人程序/HHWS_tjcx2v01/src0.lua` | 在 `HANDLERS` 增加 `24..26`；成功后按 FunctionID 判断是否自动回 `P1` | 不改现有 `1..23` 的握手机制和完成后回待命点语义 |

检查点：

1. `MOVEJ_POSE` 完成后停留在目标 pose，不被主循环自动 `MovJ(P1)` 覆盖。
2. `HOME` 明确执行 `MovJ(P1)`，并写回实际 pose/joint。
3. `QUERY_STATUS_POSE` 不运动，只写反馈。
4. 新地址块不使用现有视觉纠偏的 `3220/3222/3300/3301/3302`。
5. `CheckMovJ` 不通过时写入 `ATOM_CHECK_RESULT` 并返回错误。

## 12. 待确认事项

1. `3400..3481` 地址块是否与现场机器人/PLC 其他程序冲突。
2. `P1` 是否就是客户语义里的“原点/回原点”。
3. `move_j` 完成后是否必须停留在目标 pose。本文默认停留。
4. `user/tool` 是否允许客户中控下发，还是由 PLC 固定为 `user=0, tool=1`。
5. 现场速度/加速度上限建议值是多少。
6. PLC 是否已有外部控制模式变量；若没有，需要新增模式门控。
7. HTTP API 是同步等待到完成，还是提交后通过 request_id 查询。MVP 默认同步等待，后续可扩展异步查询。
