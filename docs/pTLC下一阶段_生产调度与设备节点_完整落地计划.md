# pTLC 下一阶段：生产调度、设备节点与工程师前端完整落地计划

> 文档状态：实施基线 v1
>
> 编写日期：2026-07-20
>
> 关联文档：[pTLC 工程师编排平台：下一阶段开发重点](./pTLC工程师编排平台_产品定位与技术方向.md)

## 1. 目标与决策

下一阶段的交付目标不是再增加流程语法，而是完成一条可用于真实 PLC 生产的闭环：

> 多个样品进入系统后，pTLC 能根据设备、工位、槽位和机械空间决定动作何时启动；动作下发后能够记录 PLC 的真实受理与终态；进程重启或通信中断后能够对账，且不会重复执行非幂等物理动作。

本计划固定以下决策：

1. 继续采用单个 FastAPI 后端进程，不建设分布式调度集群。
2. 当前 `runs.db` 升级为事务型执行状态库，不再只是运行事件归档。
3. 下一阶段继续使用 SQLite，但必须启用 WAL、外键、强同步和事务化资源租约。
4. 一台主 PLC 对应一个 `plc-main` Device Node；各 PLC 工位是能力和资源，不是一组独立进程。
5. 所有普通动作统一经过 `ActionExecutor → Scheduler → Device Node`；维护操作也必须经过资源准入。
6. 急停和安全停止走独立高优先级安全通道，最终仍由 PLC L1 或独立安全系统执行。
7. PLC、机器人和现场设备是真实物理状态的权威；数据库不能凭自己的记录宣布物理动作已经结束。
8. 静态动作、工作流、点位和标定继续使用版本化文件作为定义源；数据库保存每次运行实际使用的内容快照与哈希。
9. 下一阶段固定采用“L2 RUNNING 时拒绝 HMI 普通手动操作”的语义；动作中途只允许独立安全回路介入，不实现自动/手动中途交权。
10. 同一时刻只允许一个 Scheduler/PLC 普通命令写者，启动时使用进程锁和数据库所有权记录双重阻止重复实例。

如果未来要求多台上位机同时写入、多个 Scheduler 主备切换或跨主机直接共享数据库，需要另行决定 PostgreSQL 和分布式租约。本计划不包含该范围。

## 2. 当前基线与缺口

| 当前能力 | 代码现状 | 下一阶段缺口 |
|---|---|---|
| 运行记录 | `runtime/run_store.py` 只有 `runs`、`run_events` 两张表，并自动保留最近 1000 次运行 | 不能恢复动作、租约和对账状态，生产记录也不应自动淘汰 |
| VM 运行 | `VmController` 在内存中保存运行、Task、输入和调试状态 | 进程重启后活动运行全部丢失 |
| 资源互斥 | `ResourceGate` 是进程内 `asyncio.Lock` 字符串集合 | 没有所有者、等待原因、租约记录和故障恢复 |
| PLC 动作 | 每个 PLC 工位已有独立锁及 RequestSeq/AcceptedSeq/CompletedSeq 协议 | 上层没有把 RequestSeq 与 Action Run、租约和恢复流程持久关联 |
| 设备节点 | `NodeRegistry` 只提供描述、快照和健康派生；当前将各 PLC 工位显示成节点 | 没有统一执行、取消、能力和结果对账接口 |
| 动作直发 | `/api/actions/{name}/run` 可以直接调用 `ActionExecutor` | 会绕过 Scheduler 和资源租约，也不写完整执行历史 |
| 执行界面 | 只能显示最近一次实时运行和单次历史事件回放 | 不能显示多样品队列、真实并行、资源等待和结果对账 |

因此不应新建另一套历史库或另一套设备调用路径，而应把当前能力收敛成同一条生产执行链。

## 3. PLC 生产边界

### 3.1 状态真源

| 信息 | 权威来源 | 数据库的作用 |
|---|---|---|
| PLC 轴、泵、阀、气缸和安全互锁 | PLC L1 | 只记录必要结果，不参与实时闭环 |
| PLC L2 动作是否受理、执行到哪一步、最终结果 | PLC 的 AcceptedSeq、CompletedSeq、State、Step、ErrorCode、SafeState | 保存观察结果和对账证据 |
| 机器人真实位姿、报警和控制器连接状态 | 机器人控制器 | 保存动作结果、状态变化和异常 |
| 工作流生命周期、动作排队和资源租约 | Scheduler | 事务持久化，供重启恢复 |
| 动作、工作流、点位和标定定义 | 版本化配置文件与 PLC 工程 | 保存运行时快照、版本和哈希 |

数据库是执行事实的持久化记录，不是 PLC 状态镜像，也不能成为新的全局变量池。

### 3.2 必须保持的 PLC 约束

1. 工作流只能调用 PLC L2 工艺动作，不能直接编排裸 IO、EtherCAT 从站或单扫描内部步骤。
2. 同一 PLC 工位一次只运行一个 L2 动作；不同工位可以并行，当前 `PlcController` 的 per-prefix lock 必须保留。
3. OPC UA 写锁只保护短时间读写和命令串行化，不能在等待长动作终态时阻塞其他工位。
4. 下发顺序保持：`Start=FALSE → 等 IDLE → 写参数/ActionCode/RequestSeq → 回读确认 → Start=TRUE`。
5. Scheduler 获得资源租约不代表 PLC 必须执行；PLC 仍保留忙碌、安全互锁和状态异常时的最终拒绝权。
6. 在 `AcceptedSeq` 确认前失败，可根据明确证据结束为 REJECTED 或 FAILED；不得仅凭网络超时猜测。
7. `AcceptedSeq` 已匹配后通信中断，动作进入 `OUTCOME_UNKNOWN`，禁止自动重发，并保留相关资源租约。
8. 只有 `CompletedSeq`、`ActiveCode` 与本次命令匹配并取得明确终态，或人工完成有证据的结果对账，才能认领该终态。
9. RequestSeq 必须和 PLC 启动代次一起解释。PLC 需要发布单调变化的 `ControllerEpoch/BootId`；缺少该字段时，PLC 重启后的旧动作只能进入人工对账。
10. 运行时超时使用单调时钟；数据库时间统一存 UTC 毫秒时间戳，不能用系统时钟变化驱动看门狗。
11. PLC/HMI 手动动作不能与 Scheduler 形成双写者：RUN 模式必须走 pTLC；DEBUG/维护模式必须先取得维护资源租约。
12. 急停可以绕过普通租约直接生效，但急停后不能把在飞动作直接标记为 CANCELLED，必须重新读取设备状态并对账。
13. PLC 工程部署前必须确认没有活动生产运行，并取得整机维护租约；编译成功、版本快照和部署结果必须留痕。
14. 工位命令锁必须覆盖序号分配、命令下发、等待终态、终态落库、`Start=FALSE` 和 IDLE 清理；Reset/reconcile 进入同一控制门，只有急停绕过。
15. RequestSeq 按工位取 PLC 当前 RequestSeq/AcceptedSeq/CompletedSeq、数据库最后序号和进程计数的最大值加一；到达 DINT 上限时停机维护，禁止静默回绕。
16. PLC 所有终态应保持到 `Start=FALSE`，CompletedSeq 不得回到 IDLE 时清零。上位机必须先持久化完整终态，再清 Start。
17. 订阅镜像只用于加速；OPC UA 重连后旧镜像作废，必须在新连接上取得带质量与源时间戳的完整快照后才能对账。
18. `Start=TRUE` 写调用超时或返回异常也可能已经到达 PLC，必须保持 START_INTENT 并查询原 RequestSeq，不能按“写失败”直接重发。

### 3.3 断线和重启的唯一处理规则

```text
命令尚未写入 PLC
    → 可以结束为 FAILED，资源按明确状态释放

RequestSeq 已写入但尚未确认 AcceptedSeq
    → 先查询 PLC，不直接重发

AcceptedSeq 已匹配
    → PLC 自治执行；断线后标记 OUTCOME_UNKNOWN 并保留资源

恢复连接
    → 先核对 ControllerEpoch/BootId
    → 再读取 AcceptedSeq / CompletedSeq / State / Step / ErrorCode / SafeState
    → 对账成功后写入终态并释放资源
    → PLC 已重启或无法形成证据时进入人工对账
```

明确终态后的收尾顺序：

```text
终态快照落库
    → 校验 CompletedSeq / ActiveCode / SafeState
    → 写 Start=FALSE
    → 确认工位回到允许的新命令状态
    → 更新物料放置关系和动作输出
    → 写入 VM checkpoint
    → 释放满足条件的 Lease
```

`DONE` 不等于资源必然空闲。板仍被夹持、机器人仍持有物料、泵内已有液体或展缸仍放有样品时，必须继续保留跨动作租约或放置关系。

### 3.4 当前 PLC 接入必须修正的风险

| 当前实现 | 生产风险 | 目标改动 |
|---|---|---|
| `PlcController.reset()` 不进入工位动作锁 | Reset 可能与活动命令竞争 | Reset/reconcile 与普通命令共用工位控制门 |
| RequestSeq 只参考 PLC 和进程内计数 | 重启后无法与数据库命令关联 | 纳入数据库最大序号和 PLC BootId |
| 结果不明被转换为 TIMEOUT，结果中没有 RequestSeq | 无法自动定位原 PLC 命令 | 建立 OUTCOME_UNKNOWN 和持久化 plc command |
| 终态后的 Start 清理失败只记录 warning | 上层可能误认为资源已经可用 | 引入 CLOSEOUT，清理完成前不释放 Lease |
| OPC UA 订阅镜像没有明确连接代次 | 重连后可能使用旧值判断 | 镜像绑定 connection_epoch，重连后强制完整直读 |
| 当前 L2 快照没有 Start、RequestSeq、BootId | 无法区分准备、启动和 PLC 重启 | 扩展恢复快照和 PLC 符号协议 |

## 4. 目标执行架构

```text
工程师前端 / Workflow VM / 维护 API
                │
                ▼
ActionExecutor：动作契约、参数、模式和权限校验
                │
                ▼
Scheduler：排队、优先级、节点准入、状态迁移
                │
                ├──── ExecutionStore：运行、动作、租约、事件、报警
                │
                ▼
LeaseManager：一次性取得动作所需的全部资源
                │
                ▼
DeviceNode：execute / cancel / reconcile / health
                │
                ▼
Controller / Driver：OPC UA、Dobot TCP、相机 SDK、MQTT
                │
                ▼
PLC / 机器人 / 相机 / 外部工控机
```

安全通道不进入普通排队：

```text
急停 / 安全停止 → SafetyService → PLC L1 / 安全系统 / 机器人控制器
                              └→ Scheduler 冻结新下发并启动状态对账
```

## 5. 领域对象与状态机

### 5.1 Workflow Run

一次工作流定义的实际运行，一个样品通常对应一个 Workflow Run。

生命周期只保存以下主状态：

```text
QUEUED → RUNNING → DONE
              ├→ PAUSED → RUNNING
              ├→ RECONCILING → RUNNING | FAILED
              ├→ FAILED
              └→ CANCELLED
```

`WAITING_RESOURCE`、`WAITING_NODE` 和 `WAITING_HUMAN` 是 Action Run 状态。Workflow Run 的页面显示状态由其活动动作聚合，不再额外保存一份容易冲突的“当前等待状态”。

### 5.2 Action Run

一次工作流动作节点的实际执行。一个 Action Run 只对应一个稳定的 `command_id`，不得把自动重试隐藏在同一条记录内。

```text
SUBMITTED → WAITING_RESOURCE / WAITING_NODE → DISPATCH_READY → DISPATCHED
    ├→ CANCELLED                         （下发前取消）
    ├→ REJECTED / FAILED                 （明确未受理）
    └→ ACCEPTED → RUNNING
                   ├→ OUTCOME_UNKNOWN → RECONCILING
                   │                  ├→ RUNNING      （证实设备仍在执行）
                   │                  ├→ CLOSEOUT     （取得真实终态）
                   │                  └→ OUTCOME_UNKNOWN（证据仍不足）
                   └→ CLOSEOUT → DONE / FAILED / CANCELLED
```

规则：

- `TIMEOUT` 不再作为模糊物理终态；它记录为失败原因，例如 `DISPATCH_TIMEOUT`、`STALL_TIMEOUT`。
- 已确认设备未受理时，超时可以归为 FAILED。
- 设备可能已经受理但结果无法确认时，必须归为 `OUTCOME_UNKNOWN`。
- `OUTCOME_UNKNOWN` 和 `RECONCILING` 都是非终态阻塞状态；不能结束 Workflow Run，也不能释放 Lease。
- `CLOSEOUT` 表示设备终态已经观察并持久化，但 Start/IDLE、SafeState、Placement 或租约收尾尚未完成。
- `join:any` 的所有可能遗留物理分支必须具备可验证的取消协议，否则工作流发布或启动校验失败。
- 并行分支使用独立变量作用域，输出只能按显式映射合并。

### 5.3 Device Node 健康

```text
ONLINE | DEGRADED | FAULT | OFFLINE
```

节点健康不包含 `busy`。工作负载由活动 Action Run、Capability 状态和 Resource Lease 表示。

### 5.4 Resource Lease

```text
ACTIVE → RELEASED
   └──→ HELD_FOR_RECONCILIATION → RELEASED
```

等待动作没有“半个租约”。Scheduler 必须在一个事务中取得动作要求的全部资源，否则一个也不取得。

## 6. Action Contract 必须新增的字段

静态动作契约仍保存在 `config/actions/**/*.yaml`。当前 `ActionDef` 已有 kind、station、action_code、timeout、参数和模式门控，下一阶段增加：

| 字段 | 示例 | 作用 |
|---|---|---|
| `version` | `1.2.0` | 固定动作接口版本 |
| `target_node` | `plc-main` | 指定执行节点 |
| `capability` | `sampling.aspirate` | 协议无关的设备能力 |
| `resources` | `[station:sampling, pump:sampling]` | 调度前必须取得的全部资源 |
| `idempotent` | `false` | 是否允许在证据充分时重新调用 |
| `cancellable` | `false` | 是否存在经过验证的物理取消协议 |
| `reconcile_mode` | `request_seq` | `request_seq / device_query / manual` |
| `timeout` | `120` | 动作绝对上限 |
| `stall_timeout` | `30` | 无状态推进的对账触发时间 |
| `result_schema` | `{actual_volume: float}` | 结果结构与类型 |
| `plc_binding` | `{station: sampling, action_code: 50}` | PLC 动作的 L2 绑定 |
| `source_ref` | `{pou: FB_Sampling, state: 50}` | 工程师界面下探 PLC ST 的定位信息 |
| `release_safe_states` | `[EMPTY, CLAMPED_SAFE]` | 允许释放动作租约的物理安全状态 |
| `recovery_procedure` | `sampling.reconcile_aspirate` | 结果不明或异常后的独立恢复流程 |

示例：

```yaml
sampling.aspirate:
  version: 1.2.0
  kind: plc_l2
  target_node: plc-main
  capability: sampling.aspirate
  resources:
    - station:sampling
    - pump:sampling
  idempotent: false
  cancellable: false
  reconcile_mode: request_seq
  action_timeout: 120
  stall_timeout: 30
  station: sampling
  action_code: 50
  source_ref:
    pou: FB_Sampling_L2
    action_code: 50
  release_safe_states: [EMPTY]
  recovery_procedure: sampling.reconcile_aspirate
```

## 7. 执行状态库设计

### 7.1 数据库选择与运行参数

下一阶段按单进程部署继续使用 SQLite，配置必须改为：

```text
PRAGMA journal_mode = WAL
PRAGMA synchronous = FULL
PRAGMA foreign_keys = ON
PRAGMA busy_timeout = 5000
```

约束：

- 只有后端 ExecutionStore 写数据库；Device Node 和前端不能直连数据库。
- ExecutionStore 是物理命令下发前的强依赖，核心状态写入失败必须阻止下发；不能沿用“事件 sink 写失败只记日志”的 best-effort 行为。
- 状态迁移和对应事件必须在同一个数据库事务中写入。
- 资源租约使用 `BEGIN IMMEDIATE` 完成检查和授予，避免两个动作同时取得同一资源。
- 所有时间字段使用 UTC epoch milliseconds，字段名统一以 `_at` 结尾。
- JSON 使用 UTF-8 文本保存，写入前由模型校验；查询频繁的字段必须独立成列。
- 生产库不再按 1000 次运行自动删除；归档和清理由显式保留策略执行。
- 图片、PLC 工程快照和大型测量文件不直接写入 SQLite，只保存 URI、哈希和元数据。
- WebSocket 只是通知通道；页面重连后以数据库查询结果为准。

### 7.2 `runtime_sessions`

记录每次后端启动，支持判断哪些活动记录来自已经崩溃的旧进程。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `session_id` | TEXT PK | 是 | 本次后端启动唯一 ID |
| `host_name` | TEXT | 是 | 运行主机 |
| `process_id` | INTEGER | 是 | 进程号，仅用于诊断 |
| `runtime_mode` | TEXT | 是 | `sim / real` |
| `software_version` | TEXT | 是 | pTLC 版本 |
| `git_commit` | TEXT | 是 | 代码提交哈希 |
| `started_at` | INTEGER | 是 | 启动时间 |
| `ended_at` | INTEGER | 否 | 正常退出时间 |
| `exit_reason` | TEXT | 否 | 正常退出、异常或被终止 |

启动时还要取得名为 `scheduler` 的单实例所有权记录，至少保存 `session_id、fencing_epoch、acquired_at、heartbeat_at`。存在未过期所有者时，新进程不得进入 READY 或下发 PLC 普通命令。

### 7.3 `workflow_runs`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `run_id` | TEXT PK | 是 | Workflow Run 唯一 ID |
| `session_id` | TEXT FK | 是 | 创建该运行的 runtime session |
| `run_kind` | TEXT | 是 | `WORKFLOW / MANUAL / MAINTENANCE` |
| `workflow_id` | TEXT | 是 | 工作流定义 ID |
| `workflow_version` | TEXT | 是 | 工作流版本 |
| `workflow_hash` | TEXT | 是 | 工作流内容 SHA-256 |
| `workflow_snapshot_json` | TEXT | 是 | 本次运行冻结的完整工作流定义 |
| `sample_id` | TEXT | 否 | 样品唯一标识 |
| `batch_id` | TEXT | 否 | 批次标识 |
| `priority` | INTEGER | 是 | 队列优先级；同优先级按入队时间 FIFO |
| `queue_seq` | INTEGER | 是 | 相同优先级下稳定排序序号 |
| `status` | TEXT | 是 | Workflow Run 主状态 |
| `control_intent` | TEXT | 是 | NONE、PAUSE 或 CANCEL；不等同于已完成控制 |
| `control_requested_at` | INTEGER | 否 | 暂停/取消请求时间 |
| `control_requested_by` | TEXT | 否 | 请求工程师 |
| `control_reason` | TEXT | 否 | 请求原因 |
| `control_mode` | TEXT | 是 | `DEBUG / RUN` |
| `inputs_json` | TEXT | 是 | 用户输入和运行前旋钮值 |
| `overrides_json` | TEXT | 是 | 本次运行显式覆盖的旋钮参数 |
| `outputs_json` | TEXT | 否 | 工作流最终输出 |
| `runtime_manifest_json` | TEXT | 是 | 软件、PLC 工程、动作集、点位和标定版本清单 |
| `requested_by` | TEXT | 是 | 发起工程师或系统账户 |
| `client_request_id` | TEXT UNIQUE | 是 | 防止前端双击重复创建运行 |
| `created_at` | INTEGER | 是 | 创建时间 |
| `started_at` | INTEGER | 否 | 首个动作开始时间 |
| `finished_at` | INTEGER | 否 | 运行终态时间 |
| `failure_code` | TEXT | 否 | 结构化失败原因 |
| `message` | TEXT | 否 | 中文说明 |
| `updated_at` | INTEGER | 是 | 最近状态更新时间 |
| `row_version` | INTEGER | 是 | 乐观并发版本 |

`runtime_manifest_json` 至少冻结：

```json
{
  "ptlc_git_commit": "...",
  "plc_project_sha256": "...",
  "plc_build_id": "...",
  "action_set_sha256": "...",
  "workflow_sha256": "...",
  "robot_points_sha256": "...",
  "plc_points_sha256": "...",
  "water_level_calibration_version": "...",
  "photoscrape_alignment_version": "...",
  "device_config_sha256": "..."
}
```

### 7.4 `workflow_checkpoints`

事件回放不能恢复 Python 协程栈。VM 只能在确定的安全边界保存显式 checkpoint，并从该 checkpoint 恢复。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `checkpoint_id` | TEXT PK | 是 | Checkpoint ID |
| `run_id` | TEXT FK | 是 | 所属 Workflow Run |
| `checkpoint_seq` | INTEGER | 是 | 单次运行内递增序号 |
| `workflow_hash` | TEXT | 是 | 必须与运行冻结版本一致 |
| `vm_engine_version` | TEXT | 是 | VM 状态格式版本 |
| `vm_state_json` | TEXT | 是 | Frame、变量、游标、循环、并行和 HITL 状态 |
| `active_action_ids_json` | TEXT | 是 | 保存时仍在飞的 Action Run |
| `last_event_id` | INTEGER FK | 是 | 已纳入 checkpoint 的最后事件 |
| `created_at` | INTEGER | 是 | 创建时间 |
| `checksum` | TEXT | 是 | Checkpoint 内容哈希，损坏时禁止自动恢复 |
| `is_current` | INTEGER | 是 | 每个 run 只能有一个当前 checkpoint |

`vm_state_json` 至少包含：

```text
每个并行分支的 branch_path、当前 AID 和局部 Frame
循环变量、当前迭代次数和退出条件状态
全局变量、输入、已完成动作输出和显式合并结果
子流程调用栈及每层 workflow_hash
断点、边界暂停、HITL 节点和人工回复
等待中的 action_run_id 列表
```

Checkpoint 在以下边界写入：运行创建后、物理动作下发前、动作终态后、HITL 挂起/回复、暂停和取消边界。动作终态、输出合并、Lease 释放、事件和新 checkpoint 必须在同一个事务中提交。

### 7.5 `action_runs`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `action_run_id` | TEXT PK | 是 | 一次动作节点执行 ID |
| `run_id` | TEXT FK | 是 | 所属 Workflow Run |
| `workflow_node_id` | TEXT | 是 | VM 的稳定 AID |
| `invocation_path_json` | TEXT | 是 | 子流程栈、循环序号和并行分支组成的动态调用路径 |
| `invocation_no` | INTEGER | 是 | 同一 AID 的第几次动态调用 |
| `parent_action_run_id` | TEXT FK | 否 | 子流程或父节点关联 |
| `branch_path` | TEXT | 否 | 并行分支路径 |
| `action_id` | TEXT | 是 | 动作契约名称 |
| `action_version` | TEXT | 是 | 动作契约版本 |
| `action_hash` | TEXT | 是 | 动作契约哈希 |
| `action_snapshot_json` | TEXT | 是 | 本次运行冻结的动作契约 |
| `target_node_id` | TEXT | 是 | 目标 Device Node |
| `capability` | TEXT | 是 | 目标能力 |
| `status` | TEXT | 是 | Action Run 状态 |
| `requested_args_json` | TEXT | 是 | 用户或工作流请求参数 |
| `resolved_args_json` | TEXT | 是 | 默认值、旋钮、点位解析后的实际参数 |
| `result_json` | TEXT | 否 | 结构化结果 |
| `idempotent` | INTEGER | 是 | 0/1 |
| `cancellable` | INTEGER | 是 | 0/1 |
| `reconcile_mode` | TEXT | 是 | `request_seq / device_query / manual` |
| `wait_kind` | TEXT | 否 | `RESOURCE / NODE / HUMAN` |
| `wait_target` | TEXT | 否 | 具体等待资源或节点 |
| `wait_started_at` | INTEGER | 否 | 开始等待时间 |
| `reject_code` | TEXT | 否 | 接受前拒绝原因 |
| `failure_code` | TEXT | 否 | 执行失败或超时原因 |
| `device_error_code` | TEXT | 否 | PLC/机器人/设备错误码 |
| `safe_state` | TEXT | 否 | 设备报告的安全状态 |
| `retryable` | INTEGER | 是 | 设备明确给出的可重试标志 |
| `submitted_at` | INTEGER | 是 | 提交时间 |
| `dispatch_ready_at` | INTEGER | 否 | 已取得全部租约时间 |
| `resources_acquired_at` | INTEGER | 否 | 全部资源授予时间 |
| `dispatched_at` | INTEGER | 否 | 开始调用节点时间 |
| `accepted_at` | INTEGER | 否 | 设备确认受理时间 |
| `last_progress_at` | INTEGER | 否 | 最近状态推进时间 |
| `finished_at` | INTEGER | 否 | 明确终态时间 |
| `message` | TEXT | 否 | 中文说明 |
| `terminal_source` | TEXT | 否 | DEVICE、RECONCILE 或 OPERATOR |
| `updated_at` | INTEGER | 是 | 最近状态更新时间 |
| `row_version` | INTEGER | 是 | 乐观并发版本 |

### 7.6 `device_commands`

Action Run 是工作流语义，Device Command 是一次实际设备命令。第一版一个 Action Run 只允许一个普通 Command，由 `device_commands.action_run_id UNIQUE` 反查；Action Run 不重复保存 command_id。结果不明时禁止偷偷创建新 Command 重发。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `command_id` | TEXT PK | 是 | 端到端稳定命令 ID |
| `action_run_id` | TEXT FK UNIQUE | 是 | 所属 Action Run |
| `node_id` | TEXT | 是 | 目标 Device Node |
| `node_session_id` | TEXT | 否 | 节点原生连接/运行会话 |
| `capability` | TEXT | 是 | 调用能力 |
| `phase` | TEXT | 是 | PREPARED、DISPATCHING、START_INTENT、START_SENT、ACCEPTED、TERMINAL、CLEANED、UNKNOWN |
| `idempotency_key` | TEXT | 否 | 设备支持时使用；不代表允许盲目重发 |
| `request_json` | TEXT | 是 | 真正提交节点的请求快照 |
| `response_json` | TEXT | 否 | 节点接受或终态响应 |
| `prepared_at` | INTEGER | 是 | 命令意图持久化时间 |
| `dispatch_intent_at` | INTEGER | 否 | 即将调用真实设备的时间 |
| `start_intent_at` | INTEGER | 否 | PLC 类命令已提交 Start 意图的时间 |
| `accepted_at` | INTEGER | 否 | 设备确认受理时间 |
| `terminal_at` | INTEGER | 否 | 明确终态时间 |
| `last_reconciled_at` | INTEGER | 否 | 最近对账时间 |
| `row_version` | INTEGER | 是 | 乐观并发版本 |

### 7.7 `plc_action_runtime`

只用于 `plc_l2` Device Command，一对一关联 `device_commands`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `command_id` | TEXT PK/FK | 是 | 对应 Device Command |
| `plc_node_id` | TEXT | 是 | 通常为 `plc-main` |
| `station` | TEXT | 是 | sampling、develop 等语义工位名 |
| `station_prefix` | TEXT | 是 | Sampling、Develop 等 PLC 前缀 |
| `action_code` | INTEGER | 是 | PLC L2 ActionCode |
| `request_seq` | INTEGER | 是 | 本次 PLC 请求序号 |
| `observed_request_seq` | INTEGER | 否 | 决定性快照中从 PLC 实际读到的 RequestSeq |
| `dispatch_phase` | TEXT | 是 | PREPARED、PARAMS_VERIFIED、START_INTENT、START_SENT、ACCEPTED、TERMINAL、CLEANED |
| `active_code` | INTEGER | 否 | 最近观察到的 ActiveCode |
| `accepted_seq` | INTEGER | 否 | 最近观察到的 AcceptedSeq |
| `completed_seq` | INTEGER | 否 | 最近观察到的 CompletedSeq |
| `plc_state` | INTEGER | 否 | PLC L2 State 原值 |
| `plc_step` | INTEGER | 否 | PLC L2 Step 原值 |
| `plc_error_code` | INTEGER | 否 | PLC ErrorCode |
| `plc_safe_state` | INTEGER | 否 | PLC SafeState |
| `plc_retryable` | INTEGER | 否 | PLC Retryable |
| `plc_start` | INTEGER | 否 | 决定性快照中的 Start 值 |
| `control_mode` | TEXT | 否 | 自动、手动或维护模式 |
| `estop_active` | INTEGER | 否 | 决定性快照中的急停状态 |
| `command_payload_json` | TEXT | 是 | 实际写入 PLC 的参数与通道值 |
| `command_payload_hash` | TEXT | 是 | 翻译后参数哈希 |
| `write_verify_json` | TEXT | 否 | 写入后的回读核对结果 |
| `connection_epoch` | INTEGER | 是 | OPC UA 每次重连递增的连接代次 |
| `plc_boot_id` | TEXT | 是 | PLC ControllerEpoch/BootId，区分 PLC 重启前后的 Seq |
| `status_revision` | INTEGER | 否 | PLC 一致快照修订号 |
| `control_owner` | TEXT | 否 | NONE、PTLC 或 HMI |
| `control_epoch` | INTEGER | 否 | 控制所有权切换代次 |
| `plc_build_id` | TEXT | 是 | 执行时 PLC 工程构建版本 |
| `node_map_version` | TEXT | 是 | 执行时 OPC UA 节点表版本 |
| `last_observed_at` | INTEGER | 是 | 最近一次 PLC 状态观察时间 |
| `source_timestamp` | INTEGER | 否 | OPC UA 源时间戳 |
| `quality` | TEXT | 否 | OPC UA 数据质量 |
| `terminal_at` | INTEGER | 否 | 明确观察到终态的时间 |
| `start_intent_at` | INTEGER | 否 | START_INTENT 事务提交时间 |
| `start_sent_at` | INTEGER | 否 | Start 写调用返回或新鲜快照观察到 TRUE 的时间 |
| `cleanup_at` | INTEGER | 否 | Start 下降沿及 IDLE 清理完成时间 |
| `terminal_snapshot_id` | TEXT FK | 否 | 最终裁决使用的不可变 Node Snapshot |
| `reconcile_status` | TEXT | 是 | `NOT_REQUIRED / PENDING / RESOLVED / MANUAL_REQUIRED` |
| `reconcile_message` | TEXT | 否 | 对账依据和结论 |
| `reconciled_at` | INTEGER | 否 | 完成对账时间 |
| `reconciled_by` | TEXT | 否 | 系统或工程师账户 |

RequestSeq 必须在写 PLC `Start=TRUE` 前持久化。推荐顺序：PLC Node 在工位锁内分配序号，ExecutionStore 先保存 `command_id ↔ plc_boot_id ↔ request_seq`，再执行 PLC 写入和回读。序号跨 PLC 启动代次保持递增，因此数据库对 `(plc_node_id, station, request_seq)` 建唯一约束；BootId 作为对账证据，不是允许复用序号的命名空间。

### 7.8 `resource_instances`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `resource_id` | TEXT PK | 是 | 如 `station:sampling`、`tank:1`、`zone:robot-transfer` |
| `resource_type` | TEXT | 是 | station、device、slot、zone、bus |
| `label` | TEXT | 是 | 工程师可读名称 |
| `node_id` | TEXT | 否 | 关联 Device Node |
| `parent_resource_id` | TEXT FK | 否 | 资源层级 |
| `logical_location_id` | TEXT | 否 | 当前逻辑位置 |
| `capacity` | INTEGER | 是 | 第一版固定为 1；多槽位拆成多个实例 |
| `state` | TEXT | 是 | `AVAILABLE / UNAVAILABLE / MAINTENANCE / FAULT` |
| `enabled` | INTEGER | 是 | 是否允许调度 |
| `config_hash` | TEXT | 是 | 资源定义版本哈希 |
| `metadata_json` | TEXT | 否 | 型号、规格等低频信息 |
| `updated_at` | INTEGER | 是 | 最近更新 |
| `row_version` | INTEGER | 是 | 乐观并发版本 |

第一版不实现复杂共享容量。八个展开槽应建成 `tank:1` 至 `tank:8` 八个独占资源，而不是一个 capacity=8 的锁。

### 7.9 `resource_placements`

Lease 表示“某个动作现在有使用权”，Placement 表示“某个样品、容器或工具现在位于哪里”。长时间留在展缸中的样品不能靠一直持有短动作租约来表达。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `placement_id` | TEXT PK | 是 | 放置记录 ID |
| `subject_type` | TEXT | 是 | SAMPLE、CARRIER、TOOL、MATERIAL |
| `subject_id` | TEXT | 是 | 样品、容器或工具标识 |
| `location_resource_id` | TEXT FK | 否 | 已知时所在逻辑位置；UNKNOWN 时可为空 |
| `candidate_resource_ids_json` | TEXT | 否 | UNKNOWN 时可能涉及且必须冻结的候选位置 |
| `run_id` | TEXT FK | 否 | 关联运行 |
| `action_run_id` | TEXT FK | 否 | 建立该关系的动作 |
| `status` | TEXT | 是 | ACTIVE_VERIFIED、ACTIVE_UNVERIFIED、ENDED、UNKNOWN |
| `placed_at` | INTEGER | 是 | 放入时间 |
| `removed_at` | INTEGER | 否 | 移出时间 |
| `evidence_json` | TEXT | 是 | 传感器、PLC/机器人命令或人工确认依据 |
| `updated_at` | INTEGER | 是 | 最近更新时间 |
| `row_version` | INTEGER | 是 | 乐观并发版本 |

同一 subject 最多存在一个活动/UNKNOWN Placement，同一位置最多存在一个活动 Placement。ACTIVE_VERIFIED 和 ACTIVE_UNVERIFIED 都消耗位置容量并参与 Lease 准入；UNKNOWN 时冻结全部候选位置。跨设备交接在 CLOSEOUT 事务中原子结束旧 Placement 并建立新 Placement，无法确定时建立 UNKNOWN，不能靠释放 Lease 消除不确定性。

### 7.10 `action_resource_claims`

保存本次 Action Run 已解析出的完整资源需求。等待队列由该表与 Action Run 状态查询得到，不单独维护第二张队列表。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `action_run_id` | TEXT PK/FK | 是 | Action Run |
| `resource_id` | TEXT PK/FK | 是 | 要求的资源 |
| `mode` | TEXT | 是 | 第一版只允许 EXCLUSIVE |
| `claim_order` | INTEGER | 是 | 稳定排序，仅用于显示和诊断 |
| `resolved_from` | TEXT | 是 | 动作契约或动态选择来源 |
| `created_at` | INTEGER | 是 | 解析完成时间 |

### 7.11 `lease_sets` 与 `resource_leases`

一次动作需要的全部资源属于同一个 Lease Set，整组成功或整组回滚：

```text
lease_set_id, run_id, action_run_id, scope,
owner_session_id, status, acquired_at, released_at,
release_reason, row_version
```

Lease Set 状态为 `ACTIVE / HELD_FOR_RECONCILIATION / RELEASED`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `lease_id` | TEXT PK | 是 | 租约 ID |
| `lease_set_id` | TEXT FK | 是 | 所属整组租约 |
| `resource_id` | TEXT FK | 是 | 被占用资源 |
| `run_id` | TEXT FK | 是 | 所属运行 |
| `action_run_id` | TEXT FK | 否 | ACTION scope 的所属动作 |
| `scope` | TEXT | 是 | ACTION 或 RUN；跨动作交接使用 RUN |
| `mode` | TEXT | 是 | 第一版只允许 `EXCLUSIVE` |
| `status` | TEXT | 是 | ACTIVE、HELD_FOR_RECONCILIATION、RELEASED |
| `scheduler_session_id` | TEXT FK | 是 | 授予租约的 runtime session |
| `acquired_at` | INTEGER | 是 | 取得时间 |
| `last_confirmed_at` | INTEGER | 是 | 最近与动作状态共同确认时间 |
| `held_reason` | TEXT | 否 | 进入对账保留的原因 |
| `release_condition_json` | TEXT | 是 | 动作终态、SafeState、清理和 Placement 的机器可判定条件 |
| `condition_schema_version` | TEXT | 是 | 释放条件结构版本 |
| `release_evidence_json` | TEXT | 否 | Snapshot、SafeState、cleanup 和 Placement 版本证据 |
| `released_at` | INTEGER | 否 | 释放时间 |
| `release_reason` | TEXT | 否 | 正常终态、失败、取消或对账结论 |

数据库必须建立约束，保证同一资源不能同时存在两个 `ACTIVE/HELD_FOR_RECONCILIATION` 独占租约。
Lease 不设置基于墙上时间自动释放的 TTL。进程心跳丢失只能将旧 Lease Set 转为 HELD，不能推断物理资源已经空闲。

### 7.12 `node_runtime_state` 与 `node_snapshots`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `node_id` | TEXT PK | 是 | Device Node ID |
| `kind` | TEXT | 是 | plc、robot、camera、vision、gateway |
| `label` | TEXT | 是 | 显示名称 |
| `health` | TEXT | 是 | ONLINE、DEGRADED、FAULT、OFFLINE |
| `connection_epoch` | INTEGER | 是 | 每次重新建立连接递增 |
| `device_boot_id` | TEXT | 否 | PLC/控制器自身启动代次；与连接代次不同 |
| `software_version` | TEXT | 否 | 节点软件/驱动版本 |
| `device_firmware_version` | TEXT | 否 | PLC build 或控制器固件版本 |
| `capabilities_json` | TEXT | 是 | 能力及取消、对账支持情况 |
| `active_command_count` | INTEGER | 是 | 负载，不属于健康状态 |
| `last_seen_at` | INTEGER | 是 | 最近成功通信时间 |
| `last_error_code` | TEXT | 否 | 最近错误码 |
| `last_error_message` | TEXT | 否 | 中文错误说明 |
| `snapshot_json` | TEXT | 否 | 有界最新快照，不保存无限遥测 |
| `snapshot_seq` | INTEGER | 是 | 节点内递增快照序号 |
| `updated_at` | INTEGER | 是 | 最近状态更新 |
| `row_version` | INTEGER | 是 | 乐观并发版本 |

关键命令边界和故障对账另存不可变 `node_snapshots`：

```text
snapshot_id, node_id, command_id, reason,
connection_epoch, device_boot_id, observed_at,
source_timestamp, quality, data_json, sha256
```

`reason` 至少支持 `STARTUP / BEFORE_DISPATCH / ACCEPTED / TERMINAL / FAULT / RECONCILE`。每秒普通遥测不进入该表。

### 7.13 `execution_events`

该表取代当前只服务回放的 `run_events`，作为不可修改的审计事件流。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `event_id` | INTEGER PK | 是 | 全局递增序号 |
| `event_uuid` | TEXT UNIQUE | 是 | 事件唯一 ID |
| `run_id` | TEXT FK | 否 | 关联运行 |
| `action_run_id` | TEXT FK | 否 | 关联动作 |
| `node_id` | TEXT | 否 | 关联节点 |
| `resource_id` | TEXT | 否 | 关联资源 |
| `command_id` | TEXT | 否 | 关联命令 |
| `sequence_in_run` | INTEGER | 否 | 单次运行内严格递增序号 |
| `event_type` | TEXT | 是 | 状态迁移、租约、节点、报警或人工操作 |
| `schema_version` | TEXT | 是 | 事件 payload 结构版本 |
| `severity` | TEXT | 是 | INFO、WARNING、ERROR、CRITICAL |
| `actor_type` | TEXT | 是 | SYSTEM、SCHEDULER、NODE、PLC、OPERATOR |
| `actor_id` | TEXT | 否 | 节点或工程师账户 |
| `occurred_at` | INTEGER | 是 | 事件发生时间 |
| `recorded_at` | INTEGER | 是 | 服务端持久化时间；事件顺序仍以 event_id 为准 |
| `payload_json` | TEXT | 是 | 事件详情 |

以下情况才写节点/设备事件：健康状态变化、连接代次变化、动作状态推进、报警和关键参数变化。不得把每秒遥测全量写入 SQLite。

### 7.14 `artifacts` 与 `alarms`

`artifacts` 保存照片、视觉结果、PLC 工程快照和测量文件的索引：

```text
artifact_id, run_id, action_run_id, kind, logical_name,
relative_uri, sha256, mime_type, size_bytes, state,
retention_class, created_at, producer_node_id, metadata_json
```

`alarms` 保存需要工程师处理的生产异常：

```text
alarm_id, dedupe_key, run_id, action_run_id, command_id,
node_id, resource_id, source, code, severity, title, message,
status, raised_at, last_seen_at, occurrence_count,
acknowledged_at, acknowledged_by, ack_comment,
cleared_at, clear_reason, clear_evidence_json,
details_json, row_version
```

报警状态固定为 `ACTIVE / ACKNOWLEDGED / CLEARED`。确认报警只表示工程师已看到，不等于设备故障已经消失。
活动报警对 `dedupe_key` 建唯一约束，避免同一锁存故障每次遥测都新建一条报警。

### 7.15 不可拆开的事务边界

1. **创建运行**：Workflow snapshot、输入参数、运行清单、QUEUED 状态和创建事件一次提交。
2. **物化动作并取得资源**：Action Run 和 Resource Claims 必须先存在。`BEGIN IMMEDIATE` 内检查全部资源；有冲突时不插入任何 Lease，提交 WAITING_RESOURCE、精确 blocker 和事件；无冲突时才整组插入 Lease Set/Lease 并更新为 DISPATCH_READY。事务内禁止 await 或设备 I/O。
3. **准备设备命令**：先持久化 Device Command、精确参数和调度意图；PLC 命令还要先保存 BootId、RequestSeq、station、ActionCode 和通道值，提交成功后才能写 PLC。
4. **写 Start**：包含本次 action_run_id、动态调用路径和输出目标的 pre-dispatch checkpoint 必须已经提交。随后提交 `START_INTENT/start_intent_at`，再写 `Start=TRUE`；写调用返回或新鲜快照确认后才能记 START_SENT。DB 与 PLC 不存在分布式事务，该崩溃窗口只能通过已持久化意图和 PLC 握手对账关闭。
5. **观察终态**：先持久化不可变 Terminal Snapshot，并把 Action 置为 CLOSEOUT，之后才允许写 `Start=FALSE`。
6. **完成收尾**：Action 最终状态、动作输出、VM checkpoint、Placement、Lease 释放和审计事件一次提交。
7. **节点断线**：按 dispatch phase 处理。WAITING/DISPATCH_READY 进入 WAITING_NODE；已下发且结果可能不明的 Action 才进入 OUTCOME_UNKNOWN；CLOSEOUT 保持 CLOSEOUT。需要冻结时，Node 状态、Action 状态、Lease HELD、报警和事件一次提交。

所有状态更新使用 `row_version` 和允许的前序状态做 compare-and-swap。迟到的完成回调不能覆盖已经人工处置或进入其他终态的记录。

### 7.16 明确不进入执行状态库的数据

- 每秒全量 telemetry、机器人每帧 pose/joint、PLC 每次轮询镜像和液位视频帧。
- Python Task、Lock、Queue、socket 句柄和内存对象地址。
- 图片、视频、PLC 工程和大型数组 BLOB；这些进入受控文件目录，由 artifacts 保存相对 URI 和 SHA-256。
- OPC UA、机器人或外部服务的密码和 token；参数与快照写库前必须脱敏。
- 每次变量广播和进度心跳；只保存恢复 checkpoint、状态变化和决定性快照。
- 只有中文 message 而没有结构化 code 的错误记录。

生产备份使用 SQLite Backup API，不能只复制主 `.db` 文件而遗漏 WAL。启动时执行 schema migration 和 `quick_check`；数据库只读、损坏或磁盘满时，Scheduler 不得进入 READY。

Artifact 若是下一步工作流输入，写入顺序固定为“临时文件完整写入并 fsync → 原子 rename → 计算 SHA-256 → 在 CLOSEOUT 最终事务写 artifact metadata、Action 结果和 VM checkpoint”。数据库不得先前进到下一步再等待文件落盘。

## 8. Device Node 落地

### 8.1 最小接口

```text
describe()    节点 ID、版本、能力和协议特性
health()      ONLINE / DEGRADED / FAULT / OFFLINE
execute()     使用稳定 command_id 执行动作
cancel()      请求并验证物理取消
reconcile()   查询指定 command_id/native_request_id 的真实结果
snapshot()    获取有界工程状态快照
```

每项 Capability 还要声明：

- 是否允许并发。
- 是否支持取消，以及如何确认取消完成。
- 是否支持按命令 ID 对账。
- 节点离线后动作通常继续、停止还是未知。
- 需要哪些设备级资源。

### 8.2 节点划分

| 现场对象 | Device Node | 能力/资源建模 |
|---|---|---|
| 一台主 PLC 及全部 EtherCAT/IO/L2 工位 | `plc-main` | Sampling、Develop、Collect 等是 capability；各工位、泵和槽位是 resource |
| Dobot 控制器 | `robot-main` | move、tool_action 等 capability；机器人和机械区是 resource |
| 独立相机 SDK | `camera-main` | capture 等 capability；相机是 resource |
| PALLAS 视觉服务 | `vision-main` | capture/analyse capability |
| 香橙派液位服务 | `water-level-main` | measure/calibrate capability；按实际协议声明对账能力 |
| 共用串口/CAN 的设备组 | 一个 Gateway Node | 各从设备为 capability/resource |

当前 UI 中的 `plc.sampling`、`plc.develop` 等可继续显示为工位卡片，但控制模型中它们是 `plc-main` 的子能力，不是独立连接和进程。

### 8.3 运行方式

- 第一版所有节点对象与 Scheduler 同进程运行。
- 每个 Workflow Run 和并行分支使用 asyncio Task。
- OPC UA、TCP 和 MQTT 节点保持长期连接。
- 阻塞式机器人或相机 SDK 放入线程池，但线程不是节点身份。
- 只有 SDK 崩溃隔离、远程主机或独立重启确有需要时，才把某个节点拆成独立进程。

### 8.4 PLC Node 特殊实现

1. 共享一条 OPC UA 连接，但保持每个 station prefix 的独立动作锁。
2. `execute()` 在工位锁内分配 RequestSeq，并在写 Start 前持久化 command_id、RequestSeq 和参数快照。
3. 参数写入、ActionCode、RequestSeq 和回读确认必须作为一次可审计准备过程记录。
4. 等待终态使用订阅事件、soft recheck、stall timeout 和绝对 timeout，不能只依赖轮询数据库。
5. OPC UA 重连时增加 `connection_epoch`，并触发所有非终态 PLC 动作对账。
6. 一个工位故障时 `plc-main` 可以是 DEGRADED；Scheduler 只阻止受影响 capability/resource，不应阻止其他健康工位。
7. PLC 在同一 BootId 内拒绝已经接受、已经完成或倒退的 RequestSeq；重复 Start 上升沿不得再次执行同一非幂等动作。
8. 所有实际通道值、ActionCode 和 RequestSeq 必须全量写入并回读一致后才允许 Start；未知节点、坏质量、缺字段或任一值不一致均失败关闭，不能“警告后跳过”。PLC 在接受沿锁存完整参数。
9. 恢复快照必须来自同一逻辑扫描。优先由 PLC 发布结构化快照及 `StatusRevision`；否则使用 `BootId/StatusRevision` 前后双读，只有两次一致时才接受中间字段，变化时继续重读。
10. `Start`、RequestSeq、ActiveCode、AcceptedSeq、CompletedSeq、State、Step、ErrorCode、SafeState、Retryable、BootId 和 StatusRevision 都属于恢复快照必读字段。

## 9. Scheduler 与 LeaseManager

### 9.1 调度顺序

```text
1. 接收 Workflow Run / Manual Run
2. 冻结工作流、动作、点位、标定和软件版本清单
3. VM 产生 SUBMITTED Action Run
4. 校验动作契约、参数、控制模式和节点能力
5. 在一个事务中尝试取得全部 Resource Lease
6. 资源不足 → WAITING_RESOURCE，并记录具体资源和前序持有者
7. 节点不可用 → WAITING_NODE，不下发设备命令
8. 租约齐全且节点可用 → DISPATCH_READY
9. Device Node 下发稳定 command_id
10. 记录 ACCEPTED/RUNNING/终态或 OUTCOME_UNKNOWN
11. 明确终态先落库，再完成 Start/IDLE、SafeState、Placement 和 VM checkpoint 收尾
12. 满足每个 Lease 的 release_condition_json 并保存 release_evidence_json 后释放并唤醒等待者
```

### 9.2 调度策略

- 第一版使用 `priority DESC, submitted_at ASC`，同优先级严格 FIFO。
- 不实现动态最短工期、批量合并或复杂优化算法。
- 动作申请多个资源时必须全取或全不取，消除持有一半资源导致的死锁。
- 资源选择在进入租约事务前完成，事务中只验证并授予。
- 同一资源释放后只唤醒队首候选，再重新验证其全部资源，避免惊群。
- Scheduler 可以并行等待多个设备动作，但不能绕过设备本身的命令串行规则。
- 数据库在物理下发前不可写时，动作保持等待并禁止下发；设备已完成但终态尚未成功持久化时，保持 PLC 终态和 Lease，不进入下一动作。
- 工位命令锁与 Scheduler Lease 不能互相替代：前者串行化命令通道，后者保护跨设备物理资源。

### 9.3 进程重启恢复

后端启动后先进入 `RECOVERY`，暂停新动作下发：

1. 取得 OS 单实例锁和数据库 Scheduler 所有权，创建新的 `runtime_session`。
2. 第一笔恢复事务把非终态 Workflow/Action 标记为 RECONCILING，并把旧 session 的所有 ACTIVE Lease Set 转为 HELD；完成前不访问设备。
3. 读取每次运行 checksum 合法的当前 VM checkpoint，不尝试恢复 Python 协程栈。
4. 连接 Device Node，取得带 BootId、connection_epoch、snapshot_id、质量和源时间的新鲜快照。
5. 按下表处理每个 Action/Command，不使用统一的“全部重试”逻辑。

| 持久化阶段 | 恢复处理 |
|---|---|
| WAITING_RESOURCE / WAITING_NODE | 按 priority、queue_seq 和 Claims 重建等待队列 |
| DISPATCH_READY，尚无设备 I/O | 新 session 审计接管原 Lease Set，恢复首次 dispatch |
| PREPARED / PARAMS_VERIFIED，且无 START_INTENT | 核对 BootId、Observed RequestSeq 和 Start；证明确未启动后继续首次 dispatch，否则转 UNKNOWN |
| START_INTENT / START_SENT | 只查询原 RequestSeq，禁止生成新 Seq 或重发 |
| ACCEPTED / RUNNING | 重新挂接监视，保持 HELD Lease；若仍在运行则恢复为 RUNNING |
| TERMINAL / CLOSEOUT | 不再 dispatch，只完成终态落库、Start/IDLE、SafeState、Placement 和 checkpoint 收尾 |
| CLEANED 但最终事务未提交 | 使用 terminal_snapshot_id 完成 DB 收尾和有证据的 Lease 释放 |
| OUTCOME_UNKNOWN | 继续保持 HELD，自动对账或进入人工处置 |

6. 数据库无在途动作但 PLC 为 RUNNING，或 PLC 序号超过数据库记录时，按孤儿/外部命令隔离工位。
7. 所有相关节点完成首次对账后，Scheduler 才进入 `READY` 接受新生产运行。

禁止在启动时执行“释放所有锁”或“重跑所有未完成动作”。

### 9.4 手动控制与维护

- 动作调试、机器人 jog、PLC 工位复位等操作创建 `MANUAL` 或 `MAINTENANCE` Run，进入同一 ExecutionStore。
- 普通点动必须取得机器人、工具和机械空间资源；松开按钮时调用真实停止接口并确认。
- PLC 工程部署、点位写入和标定发布需要整机或对应工位维护租约。
- 急停不等待租约；急停后的恢复必须由工程师确认设备状态，再由 Scheduler 对账。
- 不提供普通“强制释放资源”按钮。结果不明的租约只能通过对账中心处理。
- L2 RUNNING 时拒绝 HMI 普通手动、Reset 和点位下发；急停后也不自动恢复原 Workflow Run。
- `recovery_procedure` 不重新竞争自己的 HELD 资源，而是经审计接管原 Lease Set，在原保护范围内执行检查、安全复位和结果确认；恢复完成后仍按 release_condition_json 释放。
- PLC/HMI 增加控制所有权握手，例如 `ControlOwner(NONE/PTLC/HMI)、ControlEpoch、OwnerRequest/OwnerAck`。只有 PLC 确认相关工位稳定、没有生产授权和在飞动作时才允许转入 HMI；通信丢失不能自动把控制权交给 HMI。

## 10. 工程师前端页面计划

现有 PLC、设备、动作、流程、点位、视觉、液位和执行记录页面保留。顶层导航只新增一个“调度”入口，内部包含活动运行、资源占用和待对账三个子视图，不再增加通用运维大屏。

### 10.1 页面与路由

| 优先级 | 页面 | 路由建议 | 类型 | 必须展示/操作 |
|---|---|---|---|---|
| P0 | 活动运行 | `/scheduler/active/:runId?` | 调度子视图 | 活动样品、排队顺序、多个活动动作、等待原因、运行控制 |
| P0 | 资源占用 | `/scheduler/resources/:resourceId?` | 调度子视图 | 资源、Placement、当前 Lease、等待队列和冻结原因 |
| P0 | 设备节点 | `/nodes/:id` | 改造 | 节点健康、连接代次、能力、版本、活动命令、子工位状态和对账状态 |
| P0 | 运行详情 | `/runs/:id` | 改造 | 多泳道时间线、动作、资源、参数、PLC 证据、事件、产物 |
| P0 | 待对账 | `/scheduler/reconcile/:actionRunId?` | 调度子视图 | OUTCOME_UNKNOWN、HELD 租约、设备证据、人工结论和审计 |
| P0 | 动作定义 | `/library/action/:name` | 改造 | 节点、能力、资源、幂等、取消、对账、ST 映射校验 |
| P0 | 工作流编辑器 | `/library/operation/:name` | 改造 | 资源冲突、并行作用域、join:any 取消能力、发布前校验 |
| P0 | 常驻运行监视器 | 现有 MonitorDock | 改造 | 多个活动 Run、等待资源、节点异常，不再只跟随最后启动的一次运行 |
| P0 | 状态栏 | 现有 StatusBar | 改造 | 运行中、等待资源、等待节点、待对账和离线节点数量 |
| P0 | 执行记录 | `/runs/:id?` | 改造 | 服务端分页和按运行、样品、流程、状态、时间筛选 |
| P1 | PLC 工程页 | `/plc` | 改造 | 当前部署版本、每工位 L2 状态、RequestSeq、活动动作、ST 下探、部署维护门 |

### 10.2 生产运行与队列页

主表字段：

```text
sample_id / batch_id / run_id / workflow / priority
run_status / display_state
queued_at / started_at / elapsed / requested_by
```

每个 Run 下展开零到多个活动 Action 子行，支持工作流内部并行：

```text
action_run_id / action / status / target_node / capability
resources / wait_kind / wait_target / wait_started_at / blocker
```

操作规则：

- 工作流页和调度页提供统一启动弹窗，冻结 workflow version/hash、样品标识和输入。前端生成稳定 `client_request_id`，网络重试复用同一 ID。
- 只能从已保存、已校验且具备所需工程版本的 Workflow Definition 启动。
- `run_status` 来自数据库主状态；`display_state` 由多个活动 Action 聚合，不能把 WAITING_RESOURCE 写回 Workflow Run status。
- 只有 QUEUED 状态可以请求修改优先级；优先级、暂停和取消请求都提交 `row_version、operator、reason`。
- 点击暂停只写 `control_intent=PAUSE`，界面显示“暂停请求中”；到达动作边界并由服务端确认后才显示 PAUSED。
- 点击取消只写 `control_intent=CANCEL`，界面显示“取消请求中”；不能立即显示 CANCELLED 或释放 Lease。
- “取消”先展示当前动作是否 cancellable；不可取消动作进入“停止后续步骤，等待当前动作终态”。
- 页面必须直接显示“等待 robot”“等待 tank:2”或“等待 plc-main 恢复”，不能只显示 Pending。

### 10.3 资源与租约页

按资源类型和工站分组显示：

- resource_id、名称、状态、关联节点和逻辑位置。
- 当前 Lease 的 `lease_id、run_id、action_run_id、取得时间、持有时长、release_condition_json、held_reason`。
- 等待该资源的动作队列，包括阻塞者 run/action 和 wait_started_at。
- Placement 的 `placement_id、subject_type/id、location_resource_id、status、时间和证据来源`。
- ACTIVE 与 HELD_FOR_RECONCILIATION 使用不同颜色和说明。
- P0 页面只读；资源状态由节点事件或经过守卫的 MAINTENANCE Run 更新，不在本阶段新增通用资源编辑器。
- 不提供跳过证据的强制释放；点击 HELD 租约跳转结果对账页。
- 长期样品/容器占用显示为 Placement，短期动作使用权显示为 Lease，不得混成一个“占用”字段。

### 10.4 设备节点页

节点概要：

```text
node_id / health / last_seen / snapshot_age / snapshot_id / snapshot_seq
connection_epoch / device_boot_id
software_version / firmware_or_plc_build / capabilities
active_command_count / last_error
```

`plc-main` 下显示各工位子卡：ActionCode、RequestSeq、Start、State、ActiveCode、AcceptedSeq、CompletedSeq、Step、ErrorCode、SafeState、Retryable、StatusRevision、ControlOwner/ControlEpoch、command_id、Lease、OPC UA quality/source_timestamp、connection_epoch 和 device_boot_id。BootId 或一致快照证据缺失时明确显示“禁止自动裁决”。工位 busy 只显示在子卡，不改变整个节点的健康语义。

设备执行操作必须跳转或调用统一 Action API，不在节点页增加第二套直接驱动按钮。已有复位、机器人点动等维护功能需要接入维护 Run 和资源租约；快照过期、存在冲突租约或待对账动作时，前后端共同禁止危险操作。

### 10.5 运行详情页

由现在的“事件回放”升级为六个页签：

1. **概览**：样品、工作流版本、运行状态、发起人和最终结果。
2. **时间线**：按 Workflow Run、Device Node 和 Resource 泳道显示真实重叠、等待和执行区间。
3. **动作**：Action Run、Device Command、wait_started_at、实际资源、CLOSEOUT、参数、结果、取消和对账能力。
4. **PLC 证据**：station、ActionCode、BootId、RequestSeq、Start、ActiveCode、AcceptedSeq、CompletedSeq、State、Step、ErrorCode、SafeState、Retryable、connection_epoch、terminal_source、不可变 snapshot_id、PLC build、快照时间与质量。
5. **资源**：每个 Lease 的取得、保留和释放原因。
6. **事件与产物**：完整审计事件、照片、视觉结果、测量文件和哈希。

### 10.6 结果对账页

对账详情左右对比：

| 数据库记录 | 设备当前证据 |
|---|---|
| command_id、最后状态、最后时间、持有资源 | 连接代次、原生命令 ID、PLC Seq、State、Step、位姿或报警 |

PLC 证据必须逐项显示 RequestSeq、Observed RequestSeq、AcceptedSeq、CompletedSeq、ActionCode、ActiveCode、Start、State、Step、ErrorCode、SafeState、Retryable、BootId、StatusRevision、快照质量和源时间，不能合并成一个模糊的“PLC Seq”。

允许的处理由后端返回 `allowed_decisions`，前端不得自行根据字段推断：

- 继续等待设备恢复。
- 根据明确 BootId、CompletedSeq、ActiveCode 和终态证据标记 DONE、FAILED 或 CANCELLED。
- 无法自动判断时提交人工结论、证据说明和工程师身份。

禁止的处理：

- 对非幂等动作点击“重新发送原命令”。
- 在没有设备终态或人工证据时释放 HELD 租约。
- 通过修改数据库字段绕过对账。

人工裁决请求必须携带当前 Action Run 的 `row_version` 和不可变 `snapshot_id`。后端发现状态或证据已经变化时拒绝旧页面提交，并要求工程师重新查看证据。裁决 Action 终态不自动等于释放 Lease；页面继续显示 release_condition_json、Placement 和 CLOSEOUT 进度。

### 10.7 动作与工作流编辑器

动作页新增表单和校验：version/hash、target_node、capability、resources、idempotent、cancellable、reconcile_mode、timeout、stall_timeout、plc_binding、result_schema、source_ref、release_safe_states、recovery_procedure。现有“执行”改为创建 MANUAL Run，并显示排队状态和调度页链接。

工作流发布前新增静态检查：

- 引用动作和版本存在。
- 输入输出类型与单位一致。
- Resource Claim 有效。
- 并行分支没有隐式写同一变量。
- `join:any` 的物理分支均可验证取消。
- PLC 动作已绑定 station、action_code 和 ST source_ref。
- 真机运行需要的点位、标定和 PLC build 已发布。

### 10.8 前端运行状态同步

当前 `runs.live` 单例会被后启动运行覆盖，必须改为：

```text
activeById: run_id → live projection
selectedRunId: 工程师当前关注的运行
lastEventId: 已消费的持久化事件序号
```

- 页面首次进入、刷新和 WebSocket 重连后，重新通过 REST 获取 Scheduler 权威投影。
- WebSocket 事件按 run_id/action_run_id 分区，并按 event_id 去重。
- localStorage 只能保存布局、筛选和选中项，不能保存 Run、Lease 或对账状态。
- UI 不乐观显示“动作完成、复位成功、资源释放”；必须等待后端确认。
- StatusBar 汇总运行中、等待资源、等待节点、待对账和离线节点数量；MonitorDock 在同一 Run 内同时展示多个活动 Action。
- HTTP 成功只显示“急停请求已受理”；另行用新鲜 PLC/安全输入显示 `estop_active=已激活/未激活/未知`，不得把 API 回包当成物理急停确认。
- 点位写入、标定发布、视觉/液位参数发布、PLC 部署、机器人点动和动作页直发都必须创建 MAINTENANCE/MANUAL Run 并取得 Lease；安全停止和急停明确绕过普通租约门。

### 10.9 执行记录

现有执行记录保留为历史入口，不与实时调度混用。列表改为服务端游标分页，至少支持 `run_id/样品/流程/状态/时间范围` 筛选；历史状态读取数据库投影，不由浏览器重新根据事件猜测。

## 11. API 与实时事件

### 11.1 REST API

```text
POST   /api/runs                         创建 Workflow/Manual Run
GET    /api/runs                         查询队列、活动和历史运行
GET    /api/runs/{run_id}                查询运行完整投影
POST   /api/runs/{run_id}/pause          动作边界暂停
POST   /api/runs/{run_id}/resume         恢复
POST   /api/runs/{run_id}/cancel         请求取消/停止后续步骤
GET    /api/scheduler/snapshot            活动 Run、Action、Lease 和待对账权威投影

GET    /api/resources                    资源状态
GET    /api/leases                       活动和 HELD 租约

GET    /api/nodes                        节点和 capability 状态
GET    /api/nodes/{id}/commands          活动命令

GET    /api/reconciliations              待对账动作
GET    /api/reconciliations/{action_run_id}  数据库与设备证据
POST   /api/reconciliations/{action_run_id}/resolve  提交有审计记录的结论

GET    /api/alarms                       报警列表
POST   /api/alarms/{id}/acknowledge      确认报警
```

现有 `/api/actions/{name}/run` 必须改为创建 `MANUAL` Run 并进入 Scheduler，不能继续直调设备。

运行列表使用服务端游标分页，不再固定为最近 50 条。人工对账请求必须提交 `action_row_version、snapshot_id、decision、reason`，由后端再次核对证据版本。

### 11.2 WebSocket 事件

```text
run_created / run_status_changed
action_status_changed / action_progress
lease_acquired / lease_held / lease_released
node_health_changed / node_connection_changed
alarm_raised / alarm_acknowledged / alarm_cleared
reconciliation_required / reconciliation_resolved
```

事件只用于增量刷新。前端断线重连后重新拉取 REST 投影，不能假设 WebSocket 事件从不丢失。

## 12. 代码落点

| 位置 | 改动 |
|---|---|
| `action/registry.py` | 扩展 ActionDef 契约字段及 YAML 校验 |
| `action/models.py` | 建立新的 Action Run 状态和 `OUTCOME_UNKNOWN` |
| `action/executor.py` | 只作为统一校验入口并提交 Scheduler；设备 dispatch 下沉到 Node |
| `operation/scheduler.py` | 新建多运行调度器、恢复流程和公平队列 |
| `operation/resources.py` | 用事务型 Lease Set/LeaseManager 替换进程内 ResourceGate |
| `operation/vm/thread.py` | call 统一提交 Scheduler；并行分支独立 Frame 和显式输出合并 |
| `operation/vm/controller.py` | 引入可序列化 cursor/checkpoint，启动恢复后再接收新运行 |
| `runtime/execution_store.py` | 新建目标数据库实现，替代当前只归档事件的 RunStore |
| `runtime/node_registry.py` | 注册真实 Device Node；工位改为 capability/status 子视图 |
| `runtime/device_node.py` | DeviceNode 协议、命令和对账结果模型 |
| `controller/plc_controller.py` | 序号预留、BootId、恢复快照、CLOSEOUT 和 Reset 控制门 |
| `api/` | runs、resources、leases、reconciliation、alarms 路由 |
| `web/src/stores/` | 新增 scheduler、resources、reconciliation store |
| `web/src/stores/runs.js` | `runs.live` 改为 activeById，支持事件去重和 REST 重建 |
| `web/src/views/` | 新增调度子视图，升级 RunDetail/NodeDetail/执行记录 |
| `web/src/components/StatusBar.vue` | 显示多运行、等待、待对账、离线和急停确认状态 |

当前开发期 `runs.db` 可以在导出需要保留的历史后按新 schema 重新创建。实现中不做新旧表双写，也不保留两套运行状态真源。

## 13. 分阶段实施与验收

### 阶段 0：冻结契约和状态机

交付：

- Action Contract 新字段和示例。
- Workflow Run、Action Run、Lease、Node 状态枚举。
- 数据库 schema 与状态迁移规则。
- PLC/机器人取消和对账能力矩阵。
- PLC ControllerEpoch/BootId、Start、RequestSeq 恢复字段和 HMI 手动拒绝策略。

验收：所有动作能够回答“在哪个节点执行、占哪些资源、能否取消、断线后如何确认结果”。

### 阶段 1：ExecutionStore

交付：

- 新 SQLite schema、WAL 参数和事务仓库。
- 状态迁移与事件同事务写入。
- Workflow checkpoint、Device Command、Lease Set、Placement 和 Node Snapshot。
- 活动运行、动作、租约和报警查询。
- 旧 RunStore 测试替换为新状态库测试。

验收：在任意状态杀死后端后，数据库仍能列出未完成动作和未释放租约，不会因为重启自动删除。

### 阶段 2：Device Node

交付：

- PLC、Robot、Camera 的最小节点适配器。
- capability、health、connection_epoch、execute、cancel、reconcile。
- NodeRegistry 从工位快照表改为节点注册和工位子状态投影。

验收：同一个 `plc-main` 节点可以让两个独立 PLC 工位并发执行，同时保持每工位单命令。

### 阶段 3：Scheduler 与 LeaseManager

交付：

- 多 Workflow Run 队列。
- 原子资源授予、等待原因、公平唤醒。
- VM、手动动作和维护动作统一入口。
- 重启恢复和结果对账队列。

验收：双样品资源不冲突时真实重叠，冲突时进入 WAITING_RESOURCE 并显示具体资源。

### 阶段 4：工程师前端 P0

交付：生产队列、资源租约、节点升级、运行详情、报警对账、动作与工作流校验、常驻多运行监视器。

验收：工程师不查日志即可回答某个动作为什么未启动、由哪个节点执行、占用哪些资源、PLC 是否受理以及如何恢复。

### 阶段 5：仿真故障验收

必须自动化验证：

1. 不同资源动作真实并行。
2. 同一资源严格互斥并按优先级/FIFO 唤醒。
3. 获取多个资源时全取或全不取。
4. 节点离线时新动作不下发。
5. dispatch 前、RequestSeq 写入后、AcceptedSeq 后三个时间点模拟进程崩溃。
6. PLC 物理完成但终态尚未落库、终态已落库但 Start 未清、Start 已清但 Lease 未释放三个崩溃点。
7. 已受理动作断线后不重发，Lease 转 HELD。
8. 恢复连接后按 BootId、CompletedSeq、ActiveCode、SafeState 和 cleanup 状态完成对账。
9. PLC 冷/热启动、OPC UA 服务重启和 PLC 程序下载后不误认旧 Seq。
10. 不可取消物理动作不能用于 `join:any`。
11. 前端 WebSocket 断开重连后从 REST 恢复正确投影。

### 阶段 6：真机生产验收

使用两个样品：

```text
样品 A：点样 → 机器人转运 → 槽位 1 长时处理 → 机器人取回
样品 B：                       点样 → 等待机器人 → 槽位 2 处理
```

必须满足：

- A 离开点样工位后，B 可以进入点样。
- A/B 不同时占用机器人和共同机械空间。
- 槽位 1 与槽位 2 实际重叠运行，并有数据库时间证据。
- 拔掉 OPC UA 网络后，PLC 已受理动作不被自动重发。
- 重启 pTLC 后先对账再恢复调度。
- HMI/维护动作不能绕过资源冲突保护。
- 急停立即生效，恢复后所有在飞动作均完成真实状态对账。

双样品通过还不等于所有 PLC L2 工位可投产。每个工位必须分别完成协议准入：

- 重复和倒退 RequestSeq 被拒绝，不产生第二次物理动作。
- DONE、REJECTED、ERROR、INTERRUPTED 都锁存匹配的 CompletedSeq、ActiveCode 和 SafeState。
- 终态保持到 Start 下降沿，Start/IDLE cleanup 失败时不释放资源。
- PLC 冷启动、热启动和程序下载后 BootId/RequestSeq 行为符合定义。
- 在参数写入、START_INTENT、Start 写出、Accepted、RUNNING、物理完成、终态落库和 cleanup 各点拔网线或强杀后端。
- 急停及 Reset 后的真实输出、安全状态和物料位置经过现场观察确认。
- 逐工位审计 Retryable；只有明确未产生物理副作用的拒绝才能为 TRUE。

现有 FeedLift 等工位若在 RUNNING Reset 时直接回 IDLE、未写 CompletedSeq/INTERRUPTED/SafeState，或无条件把动作错误标为 Retryable，必须先修正 PLC FSM，不能接入自动资源释放。

## 14. 各工位进入真机验收前的工程基线

这些现场事项不阻塞 ExecutionStore、Device Node 和 Scheduler 的软件开发，但会阻塞对应工位的最终真机验收：

| 工位 | 当前事项 | 验收前必须形成的基线 |
|---|---|---|
| 上样/点样 | 更换三通阀；点样参数基本确定；当前缺少板物理到位传感器 | 阀 I/O 与控制逻辑版本、点样参数版本、动作回归结果；Placement 标记为命令级 UNVERIFIED，不能显示为物理到位已验证 |
| 展开 | 液位标定进行中 | 液位标定版本、误差和重复性记录 |
| 刮板 | 作业区域与绘制区域略有偏差；对刀程序未实装 | 对刀程序版本、坐标偏置、安全作业区域和真机轨迹结果 |
| 收集 | 耗材滤芯尺寸需要改进 | 滤芯规格、安装验证；若影响流量则同步超时和报警阈值 |

这些版本写入 `runtime_manifest_json` 或相关 Action Run 参数快照，保证以后能够解释某次生产使用的是哪一版现场参数。

## 15. 本阶段完成标准

本阶段只有同时满足以下条件才算完成：

1. 两个样品在资源不冲突时真实并行，冲突时有原因地等待。
2. 每个动作都能追溯到工作流版本、动作版本、command_id、Device Node 和 Resource Lease。
3. PLC 动作额外追溯到 ActionCode、RequestSeq、AcceptedSeq、CompletedSeq、Step、ErrorCode、SafeState 和 PLC build。
4. 进程崩溃、OPC UA 断线或急停后，不自动重发结果不明的物理动作，也不错误释放资源。
5. 工程师能够在前端完成排队、观察、诊断和有证据的结果对账，不需要直接修改数据库。
6. PLC L1 安全互锁、每工位动作自治和 HMI/上位机单一写者原则没有被上层调度破坏。

本阶段不包含 AI 自动审查、分布式节点部署、复杂排产优化、完整库存系统或在浏览器中替代 PLC IDE。
