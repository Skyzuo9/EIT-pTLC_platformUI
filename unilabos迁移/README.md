# pTLC 接入与迁移文档索引

本目录用于保存 pTLC 接入 Uni-LabOS / 客户中控系统的阶段性讨论文档。

## 当前主线文档

> 2026-06-19 进展：Modbus 机器人 MVP 已完成现场最小闭环验证；基于官方
> TCP-IP-V4 的 `DobotTcpRobotTransport`、配置切换、独立 CLI 和 fake/mock 离线验证已完成，
> TCP 真机运动与异常恢复待现场验收。`robot_mvp_minimal.lua` 与
> `UI-Upper/scripts/robot_mvp_modbus_test.py` 已实现上位机对机器人寄存器的读写联动；
> 现场 F32 字序必须使用 `--byte-order word-swap`，已验证 `home` 动作可执行。
> 2026-06-19 追加：旧版工具交换路径已结构化为六条上位机动作流，显式接近点、
> 路径段速度、DO1/DO6 时序、整流独占与 home 锚点校验已完成离线验证；
> 完整工具动作流真机验收及 RecipeTask/FastAPI 接入仍待后续阶段。

> 2026-06-20 追加：机器人动作 schema v2、PointSet/StationRegistry、14 条业务路线、
> PLC/相机主机编排、进程内业务资源租约和独立 Modbus CLI 已完成；68 组合法参数
> 离线解析与软件闭环通过。14 路线真机仍待现场，TCP-IP-V4 不计入本轮结论。

- 机器人动作流参数化与14路线说明.md
  - 当前机器人动作流与业务路线主线设计，含软件验证边界和风险。

- 机器人动作流14路线现场验收指导.md
  - Modbus 工具小闭环、展缸/槽位和 PLC+机器人+相机 14 路线现场清单。
- `客户中控FastAPI接入计划.md`
  - 当前主线计划。
  - 记录 2026-06-17 客户讨论后的新结论：客户要求 FastAPI；第一批仍做机器人 MVP；MVP 优先采用 pTLC 上位机直连机器人，暂不走 PLC 中间通讯；点位、标定、资源账本和流程编排由上位机承担。

- `客户中控原子动作接入需求草案.md`
  - 用于内部梳理最新需求。
  - 重点描述客户中控原子动作接入、机器人动作 API、点位下发、上位机资源账本、反馈粒度和后续 PLC 工位动作拆分问题。

- `PLC_Current_Workstation_Flow.md`
  - 当前 PLC 工位动作事实文档。
  - 只维护最新 XML、已跑通流程和当前 Python 契约，不承载目标架构。

- `PLC_L2_Workstation_Action_Decomposition.md`
  - 当前 PLC 工位 L2 目标动作目录。
  - 定义 Sampling、PhotoScrape、Develop、Collect 的业务动作、PLC Prepare/Closeout 和机器人动作边界。

- `机器人TCP直连控制主线说明.md`
  - 当前机器人控制实施主线。
  - 说明 29999/30004 与 Modbus 502 边界、transport 切换、PointRegistry、安全策略、CLI、Lua 回退和当前验证状态。

- `机器人TCP直连现场验收指导.md`
  - 现场工程师逐项记录用验收表。
  - 覆盖 TCP 模式、控制权、点表、运动、工具 IO、报警、断线重连及 Modbus 回退。

- `L2分层架构迁移代码分析.md`
  - 当前 L2 迁移实施主线。
  - 定义代码保留/删除策略、统一动作通道、资源权威边界、单层调度锁、HMI 高优先级切换和展缸 TON 保险。

## 历史方案文档

- `pTLC对齐简要说明.md`
  - 已归档。
  - 此前用于客户沟通的对齐稿，主要内容已被当前 FastAPI 接入计划吸收。

- `pTLC当前程序组织与样品生命周期说明.md`
  - 已归档。
  - 此前用于解释现有 pTLC 程序组织和样品生命周期，核心事实保留在 `PLC_Current_Workstation_Flow.md` 与当前计划中。

- `机器人原子动作MVP_PLC接口手册.md`
  - 已归档。
  - 此前基于“上位机 -> PLC -> 机器人”的中转方案。客户讨论后第一批 MVP 改为上位机直连机器人，因此该文档仅作为历史依据保留。

- `机器人点表与末端IO整理计划_已归档_20260619.md`、`机器人运动IO与取放路径验收_已归档_20260619.md`
  - 阶段计划和旧验收记录已移入 `Backup/`；当前执行与验收以 TCP 主线两份文档为准。

- `ptlc_unilabos接入阶段说明.md`
  - 此前“渐进式接入 Uni-LabOS”的阶段性说明。
  - 已在文首标注状态，作为历史设计依据保留。

- `unilabos迁移改造计划.md`
  - 此前较完整的 Uni-LabOS 迁移计划。
  - 已在文首标注状态，作为历史设计依据保留。

## 当前判断

旧方案不是完全作废，而是优先级发生变化：

```text
旧主线：
黑盒 Workstation 接入 -> 状态观测 -> 参数上移 -> primitive -> 局部编排上移

上一轮主线：
状态/资源建模 -> 机器人原子动作协议 -> 安全准入与反馈 -> 客户中控编排接入 -> 保留完整 pTLC 流程作为兼容能力

当前主线：
机器人 RouteExecutor/PointRegistry 现场验收 -> PLC L2 动作通道试点 -> RecipeTask 逐工位切换 -> 删除旧 Stage/PLC 机器人调度 -> FastAPI 业务动作
```

机器人侧继续按现场验收文档验证 14 条业务路线。PLC 侧先以无机器人参与的 L2 动作验证统一通道，再迁移 Prepare → Robot Route → PLC Closeout；对应工位验收后删除旧 Stage 和冗余判断。FastAPI 在上位机业务动作稳定后接入。
