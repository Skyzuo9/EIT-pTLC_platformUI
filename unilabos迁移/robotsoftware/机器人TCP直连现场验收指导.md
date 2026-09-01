# 机器人 TCP 直连现场验收指导

> 适用：`DobotTcpRobotTransport` 首次现场验收。每项必须记录实际结果；任何安全条件不满足都停止，不得用 `ClearError` 掩盖原因。

统一命令前缀：

```powershell
$CLI = "python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml"
```

PowerShell 如不接受字符串直接执行，可复制各节完整 `python ...` 命令。

## 验收记录头

| 项目 | 记录 |
|---|---|
| 日期/地点 | |
| 机器人型号/控制器版本 | |
| 机器人 IP | |
| 点表版本与 SHA256 | |
| 操作人/监护人 | |
| 安全负责人 | |
| TCP 配置文件版本 | |

## 1. 环境和安全检查

- 前置条件：急停有效；防护区清空；机器人低速；末端工具、负载、user/tool 坐标系与点表一致；监护人在急停旁。
- 命令：无运动命令。检查配置与实物，运行 `... points-check`。
- 预期：仅 P1/home 等已逐项批准点为 validated；无意外开放点。
- 实际结果：________________________________
- 失败处置：停止验收，修正点表/负载/工具标定；不得临时批量改 validated。
- 下一项条件：安全负责人签字，点表 SHA256 已记录。

## 2. TCP 模式与 29999/30004 连通性

- 前置条件：完成第 1 项；机器人设置为 TCP 控制模式。
- 命令：`Test-NetConnection <机器人IP> -Port 29999`；对 30004 重复；随后执行 `... connect`。
- 预期：两端口可达；CLI 能读到反馈，不出现 `Not Tcp`、包长或 TestValue 错误。
- 实际结果：________________________________
- 失败处置：检查控制器 TCP 模式、IP、网卡路由、防火墙；不要尝试运动。
- 下一项条件：两个端口均连通且 connect 返回成功。

## 3. 控制权和端口独占

- 前置条件：完成第 2 项。
- 命令：关闭官方 Demo、其他 29999/30004 client、Lua/Modbus 动作客户端；用 `Get-NetTCPConnection` 或现场工具核对连接。
- 预期：只有当前验收机控制连接；无脚本工程与 TCP 队列并行下发。
- 实际结果：________________________________
- 失败处置：停止冲突进程；若 CommandId 已变化，人工确认机器人状态后重新 connect。
- 下一项条件：唯一控制者得到现场负责人确认。

## 4. query/status（只读）

- 前置条件：完成第 3 项；机器人静止。
- 命令：`... status`，再执行 `... query`。
- 预期：RobotMode、pose、joint、DI/DO、CurrentCommandId 连续两次合理且稳定；状态不是 9/10/11。
- 实际结果：________________________________
- 失败处置：对照示教器；状态不一致或反馈跳变时检查 30004 对齐与控制器版本。
- 下一项条件：只读反馈与示教器一致。

## 5. PointRegistry 检查

- 前置条件：点表是现场当前导出版本。
- 命令：`... points-check`。
- 预期：数量、SHA256、重复位姿组和状态统计符合记录；home 为 validated、role=home、allowed_motion=[move_j]。
- 实际结果：________________________________
- 失败处置：停止运动；重新导入点表并逐点维护 overrides，不修改原始快照冒充验收。
- 下一项条件：本次运动涉及的每个点都有单独验收记录。

## 6. home 低速验证

- 前置条件：机器人已使能空闲；P1/home 已人工核对；路径清空；速度/加速度建议先设 5–10。
- 命令：`... home --confirm-motion`。
- 预期：发送已验收 home 的 joint；RobotMode 进入运行再回 5；CurrentCommandId 匹配；`last_action=26`。
- 实际结果：________________________________
- 失败处置：急停/现场安全流程；记录 RobotMode、CommandId、GetError，禁止自动重试。
- 下一项条件：home 实际位置与方向确认，无碰撞或异常报警。

## 7. move_j

- 前置条件：目标点已 validated 且允许 move_j；从已知安全起点开始。
- 命令：`... move-j <point_id或Pxx> --confirm-motion`。
- 预期：发送点表 joint 与 user/tool/acc/vel/cp；到位后 CommandId 匹配、RobotMode=5、`last_action=25`。
- 实际结果：________________________________
- 失败处置：停止，不改为任意 pose 绕过 registry；检查点位许可和关节路径。
- 下一项条件：关节路径和终点逐项签字。

## 8. move_l

- 前置条件：起点/终点和整段直线路径均验收；目标点允许 move_l；低速。
- 命令：`... move-l <point_id或Pxx> --confirm-motion`。
- 预期：TCP 按点表 pose 直线运动，user/tool/acc/vel/cp 正确；`last_action=27`。
- 实际结果：________________________________
- 失败处置：停止；不可把 move_j 验收自动外推为 move_l 许可。
- 下一项条件：整段扫掠空间确认安全，终点和姿态合格。

## 9. tool_action 与 DI

- 前置条件：末端无危险负载；确认 DO1/DO3/DO2+DO6 极性和 DI1/DI2 物理含义；确认后才将 `tool_di_feedback_enabled` 改为 true。
- 命令：先 `... tool-action get-state`；再逐项执行 `quick-change-*`、`suction-*`、`gripper-* --confirm-tool`。
- 预期：只出现白名单 DO；夹爪动作在 timeout 内得到目标 DI；反馈 commanded/actual/di_bits 可解释。
- 实际结果：________________________________
- 失败处置：立即停止工具动作，人工卸载风险；核对接线和极性，不扩大 DO 白名单。
- 下一项条件：每个语义动作、极性、DI 和超时均有记录。

## 10. 不可达点与报警复位

- 前置条件：由机器人工程师准备安全的不可达测试点，不加入 validated 生产表；允许测试报警流程。
- 命令：先验证未验收点被 CLI 本地拒绝；控制器报警后运行 `... status`。确需清警时，负责人先将 `allow_clear_error_command: true`，排除原因后执行 `... clear-error --confirm`。
- 预期：未验收点在发送前拒绝；RobotMode=9 映射为 RobotActionError；不自动 ClearError；原因存在时清警不成功。
- 实际结果：________________________________
- 失败处置：按控制器报警说明处理；碰撞/急停不得仅靠软件清警。
- 下一项条件：报警原因消除、RobotMode 恢复，配置重新改回禁止自动清警。

## 11. 超时、断线与重连

- 前置条件：使用安全低速动作；现场负责人批准拔网线/禁用网卡测试。
- 命令：动作中制造 30004 或网络中断；观察 CLI 退出；恢复网络后先 `... connect`、`... status`，不要直接重发动作。
- 预期：超时/断线关闭 29999 与 30004；机器人运行或暂停时拒绝接管；空闲且 CommandId 可核对后才允许下一条命令。
- 实际结果：________________________________
- 失败处置：若机器人仍运动，按现场安全流程处理；若 CommandId 变化，排查其他控制者。
- 下一项条件：状态、最后命令和机械位置三者均人工确认。

## 12. TCP 失败后切回 Lua + Modbus

- 前置条件：机器人静止，无 TCP 未完成命令；保存 TCP 故障记录。
- 命令：停止 TCP 客户端；恢复机器人端 `robot_mvp_minimal.lua`；确认 502 无 `mbpoll.exe` 占用；执行：

```powershell
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap query
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap home
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap move-j --pose X Y Z RX RY RZ
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap --point-source <point.json> move-j --point P1
```

- 预期：Modbus query 正常；经再次安全确认后 home 正常；TCP 与 Modbus 不同时控制。
- 实际结果：________________________________
- 失败处置：停止两条链路，检查机器人 Lua 角色、502 占用和寄存器字序。
- 下一项条件：回退路径已单独签字，可恢复既有 MVP 使用。

## 13. 工具动作流

- 前置条件：1–9 项通过；机器人位于 P1/home；P2、P8–P10 和六个显式接近点与旧版
  `global.lua` 一致；工具架、负载和气路状态已确认。
- 先离线检查：

```powershell
python UI-Upper/scripts/robot_flow_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml resolve-flow tool.pick --tool-id 1
```

- 按工具 1→3 分别验收 `tool.pick.N` 与 `tool.put.N`；每次只运行一条：

```powershell
# schema v2 的 run-flow 当前限定 Modbus；TCP 动作继续使用 robot_tcp_acceptance.py 单独验收
```

- [ ] 入口不在 P1/home 时，动作流在第一条运动前拒绝。
- [ ] P1→P2→high→near→target 的运动方式和速度与旧版一致。
- [ ] 取工具执行 DO1=0（前后各等待 1s）→ DO6=1。
- [ ] 放工具执行 DO1=1（前后各等待 1s）→ DO6=0；slot 1 进入前先 DO6=1。
- [ ] 退出按 near→high→P2→P1；取工具在 P2 后保留 500ms 等待。
- [ ] 任一步失败后不继续、不自动回 home、不清警、不自动使能。
- [ ] Modbus 与 TCP 各至少完成一条相同动作流，并记录反馈和最终工具状态。
- 失败处置：保持当前物理状态，记录 `flow/failed_step/completed_steps`，按现场恢复流程
  人工确认机器人姿态和工具状态后再决定恢复动作；不得直接重跑完整流。

## 验收结论

| 能力 | 通过/失败/未测 | 证据或问题编号 |
|---|---|---|
| 29999/30004 连接 | | |
| query/status | | |
| PointRegistry 安全门 | | |
| home | | |
| move_j | | |
| move_l | | |
| tool_action/DI | | |
| 报警与显式复位 | | |
| 超时/断线/重连 | | |
| Lua + Modbus 回退 | | |

结论：□ 允许候选主路径试运行　□ 仅允许继续测试　□ 回退 Modbus

签字：操作人________ 机器人工程师________ 安全负责人________ 日期________
