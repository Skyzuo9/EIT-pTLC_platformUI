# 机器人动作 API 最小接入说明

本文面向机器人工程师，目标是把现有机器人侧实验代码收敛成可以复制到最新机器人工程里的最小程序。

> 验证状态（2026-06-18）：最小通信闭环已跑通。上位机脚本可以连接机器人 Modbus TCP server，完成寄存器读写并触发 `home`。现场 F32 必须使用 `word-swap` 字序。

> 2026-06-18：代码已增加受限 `move_l` 和末端 `tool_action`，待按
> `../机器人运动IO与取放路径验收.md` 完成现场验收。点位来源仍为
> `机器人程序/机器人程序v0.11/roboprogram/point.json`。

## 推荐交付文件

- `robot_mvp_minimal.lua`：唯一推荐部署文件，包含 Modbus TCP 握手及
  `query / move_j / home / move_l / tool_action`。
- 历史 `global.lua`、`src0.lua` 和重复工程副本已从本目录删除。

## 动作范围

以下为当前 `robot_mvp_minimal.lua` 已实现范围：

| FunctionID | 动作 | 行为 |
| --- | --- | --- |
| 24 | `QUERY_STATUS_POSE` | 读取当前 pose 和 joint，写回反馈寄存器，不运动 |
| 25 | `MOVEJ_POSE` | 读取目标 pose，`CheckMovJ` 通过后执行 `MovJ` |
| 26 | `HOME` | 执行 `MovJ(P1)`，并写回 pose 和 joint |

`MOVEJ_POSE` 完成后默认停留在目标位姿；是否回原点由上位机再单独调用 `HOME`，不要把回原点隐含在每个动作后面。

当前扩展协议已增加：

- `MOVE_L`：复用目标 pose 与运动参数，用于已验收命名点之间的直线接近和退出。
- `TOOL_ACTION`：只接受快换、吸盘、夹爪白名单语义，不把任意 DO 写入作为生产接口。

`MOVE_L=27`，`TOOL_ACTION=28`。工具动作 8/9 是旧版工具交换专用的 DO6 开/关；
快换动作 1/2 对齐旧版，在 DO1 改变前后各等待 1 秒。工具 IO 默认仅报告命令态；
现场确认 DI1/DI2 含义与极性后，才可在 Lua 中启用
`TOOL_DI_FEEDBACK_ENABLED`。

## 调用顺序

1. 上位机写 `3400..3404`：`user/tool/acc/vel/cp`。
2. 如果是 `MOVEJ_POSE`，上位机写 `3410..3421`：6 个 F32，顺序为 `x/y/z/rx/ry/rz`。
3. 上位机写 `3102 = FunctionID`。
4. 上位机写 `3100 = 1` 触发执行。
5. 上位机轮询 `3200`：`0=FREE, 1=BUSY, 2=DONE, 3=ERROR`。
6. 成功时读取 `3440..3471` 的 pose/joint 反馈，再写 `3100 = 0`。
7. 如果报错，读取 `3202`，再对 `3101` 写 `1 -> 0` 完成错误复位。
8. 等 `3200 = 0` 后再发下一条动作。

`BUSY` 持续时间由真实运动决定，不应使用固定 60 秒作为默认失败条件。当前验收脚本
只要求机器人在 5 秒内从 `FREE` 接单进入 `BUSY/DONE/ERROR`，动作完成默认无限等待；
如现场确实需要硬截止，可显式传入 `--timeout <秒>`。等待期间每 5 秒打印一次当前状态。
机器人侧的 `DONE` 会一直锁存到上位机读取反馈并写 `EXECUTE=0`。

现场兼容：部分机器人控制器运行时会出现 `BUSY -> FREE`，未观测到 `DONE`。验收脚本
对此只做受限兼容：必须先观测到 `BUSY`，随后 `FREE`，并且反馈寄存器
`last_action` 必须等于本次 FunctionID，才按成功处理；否则报告协议错误。机器人侧仍应
优先部署本目录 Lua，并保持 `DONE` 锁存语义。

## 上位机测试脚本

当前线 A 先用独立脚本验证机器人最小动作，不直接接入 NiceGUI Debug 页。

脚本位置：

```bash
# 直接位姿发送（--pose），运动参数走 CLI --acc/--vel/--cp
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap query
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap home
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap move-j --pose 300 200 300 180 0 0
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap move-l --pose 300 200 100 180 0 0

# 命名点运动（--point），位姿和运动参数自动从注册点提取
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap --point-source <point.json路径> move-j --point P1
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap --point-source <point.json路径> move-l --point <点名>

# 查看所有点位验收状态
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap --point-source <point.json路径> points-check

# 工具动作
python UI-Upper/scripts/robot_mvp_modbus_test.py --host <机器人IP> --port 502 --byte-order word-swap tool-action get-state
```

脚本是纯标准库实现的 Modbus TCP client/master；机器人控制器提供 Modbus TCP server，并由 `robot_mvp_minimal.lua` 处理寄存器握手和动作。

现场已确认 F32 的两个 16-bit word 顺序需要交换；脚本当前默认值已经是
`word-swap`。`--host` 必须填写机器人控制器实际 IP，不能使用监听地址 `0.0.0.0`。

## 最小现场验证

当前已完成：上位机寄存器读写联动，以及使用 `--byte-order word-swap home` 触发回 `P1`。以下其余项目仍需形成逐项记录：

1. 触发 `FunctionID=24`，确认机器人不运动，`3440..3471` 有反馈，`3481=24`。
2. 通过命名点 `--point P1 --point-source <point.json>` 触发 `FunctionID=25`，确认机器人使用注册点的 pose/参数运动到位，`3480=0`，`3481=25`。
3. 通过直接位姿 `--pose` 写入一个已知安全 pose，触发 `FunctionID=25`，确认 `3480=0`，机器人停留在目标 pose，`3481=25`。
4. 触发 `FunctionID=26`，确认机器人回 `P1`，`3481=26`。
5. 写入不可达 pose，触发 `FunctionID=25`，确认 `3200=3`，`3202=11`。

## Modbus TCP 方案判断

当前 Modbus TCP 寄存器方案可以继续用于机器人 MVP，但建议只作为“机器人 transport adapter”，不要把它作为长期对外接口。

可复用的部分：

- FastAPI 到机器人动作的语义：`query / move_j / home`。
- 动作生命周期：`FREE/BUSY/DONE/ERROR`，后续可映射到 `ACCEPTED/RUNNING/DONE/ERROR`。
- pose、joint、错误码等反馈字段。
- 上位机侧的动作封装和超时控制。

不建议复用的部分：

- 具体寄存器地址不应成为客户中控 API 合同。
- 机器人寄存器协议不能直接复用为 PC 直连 PLC 的主协议；PLC 工位 FSM 已有更丰富的 OPC UA 变量、类型和握手语义。
- Modbus 缺少结构化类型、订阅、节点语义和版本自描述，后续动作多起来后维护成本会明显上升。

建议路线：

1. 第一批 MVP：保留 Modbus TCP，pTLC 上位机实现 Modbus server/client 适配，FastAPI 对外保持稳定。
2. 代码结构上抽象 `RobotTransport`，不要让 FastAPI 路由直接依赖寄存器地址。
3. 如果机器人厂商提供 TCP/SDK/脚本远程调用接口，下一阶段优先评估直接控制接口；Modbus 作为 fallback。
4. PC 直连 PLC 仍建议继续以 OPC UA 或 PLC 原生结构化协议为主；只有在 PLC 侧必须开放少量简单 I/O 或兼容客户现场时，再用 Modbus TCP 做局部桥接。
