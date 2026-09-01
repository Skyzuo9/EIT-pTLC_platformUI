# 机器人控制程序与官方 TCP 快照

本目录只保留当前应部署到机器人控制器的程序：`robot_mvp_minimal.lua`。旧的
`global.lua`、`src0.lua` 以及重复工程副本已删除，避免与当前协议混淆。点表权威导入源仍为：

`机器人程序/机器人程序v0.11/roboprogram/point.json`

`TCP-IP-V4/` 是官方源码快照，不直接改造成业务程序。当前上位机候选主路径通过
`UI-Upper/core/dobot_tcp_transport.py` 使用官方 29999/30004 协议；本 Lua MVP 与
`ModbusRobotTransport` 继续作为 502 回退路径。两条路径不得同时控制机器人。

## 当前协议

| FunctionID | 动作 | 行为 |
| --- | --- | --- |
| 24 | `query` | 读取 pose、joint 与工具状态，不运动 |
| 25 | `move_j` | `CheckMovJ` 后执行 `MovJ` |
| 26 | `home` | `MovJ(P1)` |
| 27 | `move_l` | `CheckMovL` 后执行 `MovL` |
| 28 | `tool_action` | 执行快换、吸盘、夹爪白名单动作 |

沿用 `3100..3202` 握手和 `3400..3481` 参数/反馈。新增寄存器：

| 地址 | 方向 | 含义 |
| --- | --- | --- |
| 3405 | PC→Robot | 工具动作 ID：1 快换锁紧、2 释放、3 吸盘开、4 关、5 夹爪开、6 关、7 查询、8 工具交换 DO6 开、9 关 |
| 3406 | PC→Robot | 工具反馈超时，100..60000 ms，0 使用 3000 ms |
| 3482 | Robot→PC | 工具命令状态位：bit0 快换锁紧、bit1 吸盘开、bit2 夹爪关 |
| 3483 | Robot→PC | 实际状态位；`65535` 表示当前 IO 尚不足以确认 |
| 3484 | Robot→PC | bit0 命令态有效、bit1 DI 可用、bit2 DI 已确认 |
| 3485 | Robot→PC | DI 位：bit0 DI1、bit1 DI2 |

新增错误码：14=`CheckMovL` 失败，15=工具动作不在白名单，16=工具反馈超时。

## IO 安全边界

程序对齐已验证的旧生产 Lua：DO1=快换，动作 1/2 前后各等待 1s；DO6 在工具交换中
通过动作 8/9 独立控制，不复用会同时改变 DO2 的夹爪动作。DO3=吸盘，DO2+DO6
仍用于夹爪组合时序。DI1/DI2 暂定为夹爪两端到位；默认
`TOOL_DI_FEEDBACK_ENABLED=false`，此时只返回 `commanded_state`，不会伪报 actual state。
现场确认 DI 接线和极性后才能打开该开关。

## 上位机入口

`UI-Upper/core/robot_transport.py` 提供 `RobotTransport` 与
`ModbusRobotTransport`；`UI-Upper/core/point_registry.py` 提供只读
`PointRegistry`；`UI-Upper/core/dobot_tcp_transport.py` 提供
`DobotTcpRobotTransport`；`UI-Upper/core/robot_service.py` 负责阻止未验收点运动。
`UI-Upper/core/robot_flow.py` 在其上执行完整路径独占、home 锚点和失败即停。

TCP 主路径入口：

```powershell
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml points-check
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml status
python UI-Upper/scripts/robot_tcp_acceptance.py --config UI-Upper/config/robot_dobot_tcp.example.yaml home --confirm-motion
```

Modbus/Lua 回退入口：

```powershell
# 直接位姿
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> query
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> move-j --pose X Y Z RX RY RZ
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> move-l --pose X Y Z RX RY RZ
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> tool-action get-state

# 命名点运动（需 --point-source）
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --point-source <point.json> move-j --point P1
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --point-source <point.json> points-check
```

schema v2 动作流与路线入口（当前真机 run 仅允许 Modbus 配置）：

    python UI-Upper/scripts/robot_flow_acceptance.py --config UI-Upper/config.example.yaml check
    python UI-Upper/scripts/robot_flow_acceptance.py --config UI-Upper/config.example.yaml resolve-flow tool.pick --tool-id 1
    python UI-Upper/scripts/robot_flow_acceptance.py --config UI-Upper/config.example.yaml resolve-route plate.scrape-to-tank --tank-id 8
    python UI-Upper/scripts/robot_flow_acceptance.py --config UI-Upper/config.example.yaml run-flow tool.pick --tool-id 1 --confirm-flow

robot_flows_v1_baseline.yaml 仅用于等价回归；runtime 唯一读取 robot_flows_v2.yaml。
test.gripper 位于独立测试模板清单，不计入 14 条生产路线。PLC/相机语义节点由
robot_host_actions.json 显式映射，缺失映射时启动失败。
F32 默认使用现场已确认的 `word-swap`。

完整说明与逐项验收表见：

- `../机器人TCP直连控制主线说明.md`
- `../机器人TCP直连现场验收指导.md`
