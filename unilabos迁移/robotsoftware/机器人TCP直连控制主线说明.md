# 机器人 TCP 直连控制主线说明

> 状态：代码完成、离线验证通过；Dobot TCP 真机运动、IO、断线重连仍待现场验收。
> 本阶段不接入 FastAPI，不读取相机 Modbus 寄存器，不实现相机纠偏。

## 1. 当前主线

```text
客户中控 / 未来 FastAPI
        ↓（后续阶段）
RobotActionService：点位许可、home、工具语义
        ↓
RobotTransport（单动作锁、统一反馈/异常）
  ├─ DobotTcpRobotTransport：29999 + 30004，候选主路径
  └─ ModbusRobotTransport：502 + robot_mvp_minimal.lua，保留回退
```

上位机是机器人动作的唯一调用者。`RobotActionService` 是业务边界；外部调用方不能获得任意官方 API、任意 DO 或原始 `point.json` 的执行权。

## 2. 端口职责与连接方向

| 端口 | 连接方向 | 职责 | 是否与相机链路共用 |
|---|---|---|---|
| TCP 29999 | 上位机 client → 机器人 controller server | `RobotMode/GetPose/GetAngle/MovJ/MovL/DO/DI/ClearError/EnableRobot` | 否 |
| TCP 30004 | 上位机 client → 机器人 controller server | 1440 字节实时反馈：pose、joint、RobotMode、CurrentCommandId、DI/DO、碰撞/报警状态 | 否 |
| HTTP 22000 | 上位机 client → 机器人 controller | 官方 V4 `GetError` 报警详情；失败时回退 29999 `GetErrorID` | 否 |
| Modbus TCP 502 | 上位机 master/client → 机器人 Lua server | 现有 Lua MVP 回退：寄存器动作与反馈 | 不得占用现有相机寄存器 |

TCP 主路径不启动 Lua Modbus 动作循环；Modbus 回退不连接 29999/30004。两条路径不能同时控制同一机器人。

## 3. 实现边界

### 3.1 DobotTcpRobotTransport

- `connect/close`：分别建立/关闭 29999 与 30004；连接后先读取反馈并确认 RobotMode、报警和上一 CommandId。
- `query`：通过 `RobotMode/GetPose/GetAngle` 与 30004 交叉读取 pose、joint、DI/DO、CommandId。
- `move_j`：命名点优先发送已标定 joint，避免同一 pose 的多逆解；仍保留 transport 级 pose 能力，但不向 CLI 暴露任意位姿。
- `move_l`：发送已验收命名点 pose。
- `tool_action`：只允许快换、吸盘、夹爪和状态查询，不提供通用 `set_do`。
- DI1/DI2 原始位始终可见，但只有现场确认接线和极性并显式设置
  `tool_di_feedback_enabled: true` 后，才等待 DI 并标记 `di_available/di_confirmed`。
- 完成条件：29999 返回的 CommandId 与 30004 `CurrentCommandId` 一致，且 `RobotMode=5`。仅“回到空闲”不算完成。
- 动作、查询和工具调用共用一把锁，保持单一控制者和命令串行。

### 3.2 RobotMode 和异常

- `5`：使能空闲，可接收动作。
- `7/8`：运行/单次运动，等待完成。
- `9`：报警；返回 `RobotActionError`，读取 `GetError/GetErrorID`，不自动清警。
- `10`：暂停；拒绝在重连后继续下发。
- `11`：碰撞；返回显式错误，不自动 `ClearError`。
- 断线或超时：立即关闭两个 TCP channel。重新 `connect` 后必须重新核对 RobotMode 与 CommandId；机器人仍在运行、暂停或 CommandId 被其他控制者改变时拒绝接管。

`EnableRobot` 与 `ClearError` 采用双重显式策略：配置先允许，CLI 再传 `--confirm`。默认配置均为 `false`，连接和动作失败路径绝不自动调用。

### 3.3 官方 V4 快照的使用与规避

`unilabos迁移/robotsoftware/TCP-IP-V4/` 保持官方源码快照，不做业务修改。适配层复用了它的命令格式和反馈字段布局，但规避以下示例级风险：

1. 官方 `send_data/reConnect` 在失败后无限重连，可能在状态未知时重发命令；本实现失败即封锁连接，要求显式重连核对。
2. 官方 `feedBackData` 假设单次 `recv` 可得到完整 1440 字节；本实现按 TCP 字节流处理半包/粘包，并用 `len=1440 + TestValue` 对齐。
3. 官方示例用正则提取响应中的全部数字，可能把命令回显参数当 CommandId；本实现只解析响应前两段。
4. 官方 `GetError` 实际走 22000 HTTP；本实现记录该边界，并提供 `GetErrorID` 回退。

`RelPointUser` 保留为官方后续能力，本阶段没有调用，也没有相机纠偏输入。

## 4. PointRegistry 与生产许可

导入源沿用 v0.11 的 roboprogram/point.json，统一运行许可与补充点元数据位于 UI-Upper/config/robot_points_meta.json：

- 原始点默认 `unreviewed`，疑似占位点为 `placeholder`。
- 只有 `status=validated` 且 `allowed_motion` 包含目标动作时才能运动。
- 可使用稳定 `point_id` 或机器人点名（如 `P1`）查找；业务文档和未来 API 应使用稳定 `point_id`。
- `home` 必须指向 `role=home` 且允许 `move_j` 的已验收点。
- 点级 `user/tool/acc/vel/cp` 由 registry 传入 transport；不得散落在业务代码中。
- 当前业务动作流还会加载 robot_flows_v2.yaml 中显式声明的派生点；源点与派生点均须通过 validated 和运动类型许可。软件许可不等同于本轮全路线真机复验。

检查命令：

```powershell
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml points-check
```

## 5. 配置切换

主配置 `robot.transport` 支持：

- `modbus`：默认值，使用 `host/modbus_port/modbus_unit_id/modbus_byte_order`。
- `dobot_tcp`：使用 `host/command_port/feedback_port/error_http_port`。

独立 TCP 示例在 `UI-Upper/config/robot_dobot_tcp.example.yaml`。IP、端口、超时、点表、home 和控制策略全部从配置读取。修改 transport 后必须停止另一条控制程序，确认端口独占，再启动验收 CLI。

## 6. CLI

只读命令：

```powershell
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml connect
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml status
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml query
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml points-check
```

会运动或改变输出的命令：

```powershell
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml home --confirm-motion
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml move-j P1 --confirm-motion
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml move-l <已验收点> --confirm-motion
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml move-to-point <point_id> --motion auto --confirm-motion
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml tool-action gripper-open --confirm-tool
```

`enable/clear-error` 仅限现场负责人先修改配置许可，再带 `--confirm` 执行。

## 7. 机器人动作流编排

动作流位于原子动作服务之上，不改变 Modbus/TCP transport 协议边界：

```text
未来 RecipeTask / FastAPI
        ↓
RobotFlowService（完整路径独占、锚点校验、逐步状态、失败即停）
        ↓
RobotActionService（命名点与运动许可）
        ↓
RobotTransport（Modbus / Dobot TCP）
```

当前文件与职责：

- `UI-Upper/config/robot_flow_points.json`：将旧版
  `RelPointUser(P8/P9/P10, +200Z/+20Z)` 的已验证结果冻结为 6 个显式 MoveL 点，
  保留来源、推导式和校验状态；不修改原始 `point.json`。
- `UI-Upper/config/robot_flows_v1_baseline.yaml`：冻结保存旧版六条工具动作流，仅用于 schema v2 等价回归：
  `tool.pick.1..3`、`tool.put.1..3`。
- `UI-Upper/core/robot_flow.py`：启动预检、入口/出口 home 锚点校验、整流独占执行、
  结构化步骤结果与失败步骤。
- `UI-Upper/scripts/robot_flow_acceptance.py`：transport 无关的独立验收 CLI。

工具动作严格对齐旧版 `global.lua`：

- 取工具：P1 → P2 → high → near → target → DO1=0（前后各等待 1s）
  → DO6=1 → near → high → P2 → 等待 500ms → P1。
- 放工具：P1 → P2；slot 1 先 DO6=1；随后 high → near → target
  → DO1=1（前后各等待 1s）→ DO6=0 → near → high → P2 → P1。
- 进退方向使用旧版不同的 acc/vel/cp，参数属于路径段，不覆盖点位 user/tool。
- `ToolAction 8/9` 只表达工具交换专用 DO6 开/关，不开放任意 DO。

离线检查和执行入口：

```powershell
python UI-Upper/scripts/robot_flow_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml list
python UI-Upper/scripts/robot_flow_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml resolve-flow tool.pick --tool-id 1
# schema v2 的 run-flow 当前限定 Modbus；TCP 动作继续使用 robot_tcp_acceptance.py 单独验收
```

动作流执行前必须匹配入口 home 锚点；任一步失败后停止，不自动重试、回 home、
清警或使能。当前已完成离线顺序、互斥、锚点拒绝和失败停止验证；完整真机动作流仍待现场验收，
尚未接入 RecipeTask、FastAPI 或工具资源账本。

## 8. Lua MVP 回退

1. 停止 TCP 验收 CLI/服务，确认 29999、30004 已释放且没有未完成运动。
2. 在机器人端恢复/启动 `robot_mvp_minimal.lua`，确认机器人作为 Modbus TCP server。
3. 将 `robot.transport` 改回 `modbus`，保持 `host=<机器人IP>`、`port=502`、`word-swap`。
4. 确认 `mbpoll.exe` 等其他 Modbus client 未占用 502。
5. 先执行原入口 `robot_mvp_modbus_test.py ... query`，再按现场流程低速 `home`。脚本同时支持直接位姿 `--pose` 和命名点 `--point P1 --point-source <point.json>` 两种方式。
6. 不同时运行 TCP 与 Modbus 两个控制者。

## 9. 完成状态

| 项目 | 状态 |
|---|---|
| 代码实现、配置切换、CLI | 完成 |
| py_compile、CLI help、points-check | 离线通过 |
| 协议解析、反馈包、CommandId、RobotMode/ERROR、串行化、超时、断线、点位拒绝、工具白名单 | fake/mock 离线通过 |
| Lua/Modbus 原入口语法与 help | 离线回归通过（以最终验证记录为准） |
| 显式接近点、六条工具取放动作流、整流锁、锚点与失败语义 | 离线通过 |
| 完整工具动作流真机运动与 DO1/DO6 时序 | 待现场验收 |
| 29999/30004 真机连接与控制权 | 待现场验收 |
| home/MovJ/MovL/tool_action 真机动作 | 待现场验收 |
| 报警、碰撞、断线重连、TCP→Modbus 回退 | 待现场验收 |
| FastAPI、相机纠偏 | 后续阶段，未实现 |
