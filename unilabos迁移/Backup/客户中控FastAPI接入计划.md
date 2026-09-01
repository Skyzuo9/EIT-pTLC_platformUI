# 客户中控 FastAPI 接入计划

> 更新日期：2026-06-18
> 状态：当前主线，用于承接本次客户讨论后的计划更新。

## 0. 当前实施进展

机器人 MVP 最小通信闭环已经跑通：

- 机器人侧使用 `robotsoftware/robot_mvp_minimal.lua`。
- 上位机侧使用 `UI-Upper/scripts/robot_mvp_modbus_test.py`，作为 Modbus TCP client/master 连接机器人控制器提供的 Modbus TCP server。脚本支持直接位姿 `--pose` 和命名点 `--point`（需 `--point-source`）两种运动方式。
- 已验证上位机可以读写机器人寄存器并触发 `home`；现场 F32 寄存器采用交换 16-bit word 的顺序，必须传入 `--byte-order word-swap`。
- 该结果证明当前 Modbus 寄存器协议可作为第一批 MVP 的 `RobotTransport` 实现，不再把“是否继续使用 Modbus”作为 FastAPI 开工前的阻塞项。

当前已确认的是通信读写闭环和 `home` 动作。`query` 的 pose/joint 数值正确性、`move_j` 安全位姿、不可达位姿、复位、超时和断线恢复仍应单独验收，不能由本次结果外推为全部通过。

当前点表与末端 IO 的整理、`MoveL` 接入和实施顺序详见 `机器人点表与末端IO整理计划.md`。现有 `机器人程序/机器人程序v0.11/roboprogram/point.json` 作为首批点位导入源；上位机建立规范化 `PointRegistry`，不让 FastAPI 直接读写机器人原始工程文件。

## 1. 本次客户讨论结论

客户明确要求我方提供 FastAPI 接口。第一批落地仍聚焦机器人 MVP，但技术路线从“上位机 -> PLC -> 机器人”调整为“客户中控 -> FastAPI -> pTLC 上位机 -> 机器人直连”，暂不走 PLC 中间通讯。

新的主线判断如下：

```text
客户中控
  -> FastAPI
  -> pTLC 上位机
      -> 点位/标定/资源账本/流程编排/反馈聚合
      -> 机器人直连执行 MVP 动作
      -> 后续按需调度 PLC 工位动作
```

PLC 和机器人后续可能不暴露完整流程信息。实验流程与 pTLC 内部流程编排优先放在上位机侧，由上位机把机器人、PLC、资源账本和数据库组合成可控动作。

## 2. 第一批 MVP 范围

第一批仍以机器人动作为最小闭环，暂定包含：

| 动作 | 说明 | 备注 |
| --- | --- | --- |
| `robot.query` | 查询机器人状态、位姿、关节角 | 反馈粒度需要超过 Done/Error |
| `robot.move_j` | 上位机接收目标 pose 后直连机器人执行 MovJ | 限制范围与碰撞管理仍需讨论 |
| `robot.move_l` | 在已验收命名点或安全运动段之间执行直线运动 | 用于接近、取放和退出；首批不开放任意路径 |
| `robot.home` | 回待命点/原点 | 不作为每个原子动作的隐含后处理 |
| `robot.tool_action` | 快换、吸盘、夹爪等末端工具语义动作 | 生产接口不直接开放任意 DO 写入 |

`home` 不应强行绑定到每个原子动作后。是否回原点应由上位机流程编排决定，以免在原子动作层引入不必要复杂度。

暂不纳入第一批：

- PLC 工位小粒度动作，例如气缸、泵阀、展缸盖、CNC 单步动作。
- 完整 pTLC 流程对外编排接口。
- 复杂碰撞管理。
- 多动作队列与跨设备流程引擎。

这些内容后续继续推进，但不阻塞第一批 FastAPI 机器人 MVP。

## 3. 职责边界

| 模块 | 当前建议职责 |
| --- | --- |
| 客户中控 | 调用 FastAPI、跨工作站实验编排、读取数据库/结果、按需调用上位机暴露的点表和动作 |
| pTLC 上位机 | FastAPI 服务、机器人直连、点位表维护、标定程序、资源账本、数据库、流程编排、状态/日志/反馈聚合 |
| PLC | 保留现有 pTLC 工位 FSM 与安全执行能力；第一批机器人 MVP 不经 PLC 中转 |
| 机器人 | 执行上位机直连下发的查询、MovJ、Home 等动作 |
| 数据库 | 承载资源账本、点位/标定信息、动作日志与结果索引，供中控查询 |

关键变化：

- 点位维护由 pTLC 上位机负责。
- pTLC 上位机需要向中控提供点表信息和标定程序，支撑柔性生产。
- 资源账本由 pTLC 上位机管理，中控侧通过数据库或 API 获取状态。
- 后续若由上位机做完整流程编排，PLC 和机器人可以只作为执行层，不需要理解完整流程。

## 4. FastAPI 接口方向

第一批接口建议分为四类。

### 4.1 机器人动作接口

```http
POST /api/v1/robot/query
POST /api/v1/robot/move-j
POST /api/v1/robot/move-l
POST /api/v1/robot/home
POST /api/v1/robot/tool-actions
GET  /api/v1/robot/actions/{request_id}
```

`move-j` 请求建议包含：

```json
{
  "request_id": "optional-client-id",
  "pose": [300.0, 200.0, 300.0, 180.0, 0.0, 0.0],
  "user": 0,
  "tool": 1,
  "acc_percent": 20,
  "vel_percent": 20,
  "cp_percent": 0,
  "timeout_ms": 60000,
  "return_home": false,
  "metadata": {
    "caller": "central-control",
    "purpose": "calibration"
  }
}
```

`return_home` 只作为上位机编排参数，不作为底层动作默认行为。

### 4.2 点位与标定接口

```http
GET  /api/v1/points
GET  /api/v1/points/{point_id}
POST /api/v1/calibration/jobs
GET  /api/v1/calibration/jobs/{job_id}
```

这部分是客户柔性生产的关键接口。点表应至少包含点位 ID、位姿、坐标系、工具号、用途、所属工位、更新时间和标定来源。

### 4.3 资源账本与数据库查询接口

```http
GET /api/v1/resources
GET /api/v1/resources/{resource_id}
GET /api/v1/samples/{sample_id}
GET /api/v1/actions
```

资源账本权威方为 pTLC 上位机。中控可以查询数据库或通过 API 查询，但不直接绕过上位机修改资源状态。

### 4.4 状态与反馈接口

动作反馈不能只包含 Done/Error，至少需要：

- `request_id`
- `action_id`
- `status`
- `step`
- `progress`
- `pose`
- `joint`
- `robot_status`
- `reject_code`
- `error_code`
- `message`
- `started_at`
- `updated_at`
- `finished_at`
- `logs`

推荐动作生命周期：

```text
SUBMITTED -> ACCEPTED / REJECTED
ACCEPTED -> RUNNING
RUNNING -> DONE / ERROR / CANCELLED / TIMEOUT
```

## 5. 受限 MovJ 与碰撞管理

客户需求中仍存在一个关键待讨论点：`MovJ` 限制范围如何定义。

可选限制层级：

1. 仅做参数范围限制：速度、加速度、姿态、坐标范围。
2. 增加命名区域限制：只允许进入标定过的安全工作区。
3. 增加工位占用限制：结合资源账本判断目标区域是否被占用。
4. 增加碰撞模型：需要维护设备、夹具、耗材与机器人模型，实施成本最高。

当前判断：第一批 MVP 可以先实现参数范围、命名区域、工位占用等轻量限制；完整碰撞管理需要单独评估，不宜作为首批闭环的前置条件。

## 6. 后续 PLC 与工位动作方向

客户暂未要求第一阶段开放 PLC 工位原子动作，但后续需要推进。建议仍按三层拆分：

- 大粒度工位动作：拍照、准备展开、单次点样、单次刮取准备等。
- 小粒度执行器动作：气缸、展缸盖、泵阀、伺服、CNC 单步动作。
- 只读状态：工位占用、传感器、气缸到位、PLC 模式、错误码。

短期不把这些动作混入机器人 MVP，避免接口边界过早膨胀。

## 7. 当前待推进事项

1. 整理现有 86 个点位，补充工位、角色、允许运动方式、校验状态和来源版本；先处置疑似占位点与重复位姿。
2. 现场确认末端工具 IO 接线、极性、到位反馈和安全状态，将其收敛为快换、吸盘、夹爪语义动作。
3. 扩展机器人 MVP 协议并验收 `query / home / move_j / move_l / tool_action`，覆盖不可达位姿、错误复位、超时、断线和重连。
4. 将已验证脚本抽取为 `RobotTransport` / `ModbusRobotTransport`，并实现点位导入器与 `PointRegistry`；配置显式包含 `byte_order=word-swap`。
5. 固化动作串行化、单所有者、模式门控和安全限制，避免脚本、FastAPI、NiceGUI 或其他进程同时写机器人。
6. 用命名点、`MoveJ/MoveL` 和工具动作复刻至少一条旧机器人固定取放路径并完成现场验收。
7. 设计并实现 FastAPI 路由、请求/响应、错误码和动作查询；路由不直接访问寄存器或原始 `point.json`。
8. 定义动作反馈粒度，并将 `FREE/BUSY/DONE/ERROR` 映射为外部动作生命周期。
9. 在机器人基础能力稳定后推进标定接口、资源账本数据库与更高层流程模板。

## 8. 归档说明

原 `机器人原子动作MVP_PLC接口手册.md` 基于 PLC 中转方案，已被本方案替代，作为历史方案归档。`pTLC对齐简要说明.md` 与 `pTLC当前程序组织与样品生命周期说明.md` 的有效内容已并入本计划、需求草案与 PLC 流程事实文档，后续作为历史对齐材料归档。
