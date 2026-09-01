# 当前 PLC 工位动作流程梳理

> 整理日期：2026-06-17  
> 事实边界更新：2026-06-20
> 依据：最新 `PLCsoftware/OPCUAtest/*.xml` 与已跑通工作流；上位机依据为 `UI-Upper/core/stages/*.py`、`UI-Upper/core/plc_client.py`、`UI-Upper/core/task.py`。

本文面向两个用途：

1. 给客户解释当前设备按什么顺序动作、每个工位等待什么条件、异常时如何处理。
2. 给后续 PLC 原子级动作拆分提供边界：哪些动作已经是独立 FB/Action，哪些仍耦合在工位状态机里。

## 0. 版本与事实边界

本文采用以下事实优先级：

1. 最新 `PLCsoftware/OPCUAtest/*.xml` 与已经跑通的实机工作流。
2. `UI-Upper/core/plc_client.py`、`core/stages/*.py` 和 `core/task.py` 的当前上位机契约。
3. 协议和历史文档仅用于解释版本变化。

`plc_*.txt`、`ref_plc_*.txt` 视为旧版参考，不用于判断当前实现。XML 中保留的早期 TODO/调试批注也不单独证明功能未实现；是否需要补诊断、超时或错误码，应按最新 XML 分支和现场验收结果判断。

L2 目标设计见 `PLC_L2_Workstation_Action_Decomposition.md`，代码迁移和删除策略见 `L2分层架构迁移代码分析.md`。

## 1. 总体样品流程

标准 pTLC 样品流程：

```text
上样点样 Sampling
  -> 点样后拍照 before_photo（复用 scrape FSM, PhotoMode=1）
  -> 展开 develop prep / 展开等待 / 排液 / 展缸交接
  -> 展开后拍照 + 刮取 scrape（PhotoMode=0）
  -> 收集 collect
  -> DONE
```

当前上位机有一个并行优化：

- `before_photo` 与 `develop prep` 可以并行启动，因为拍照工位和展开工位硬件不同。
- 这要求机器人从拍照位取板去展开的准入条件不能只看 `Expand_Step=0`，否则 develop prep 未完全归零时会卡住。建议 PLC 条件为：

```pascal
拍照工位允许取硅胶板去展开 AND (Expand_Step = 0 OR 展开工位允许放硅胶板1)
```

当前 `机器人PLC侧程序.xml` 中仍可见条件 `拍照工位允许取硅胶板去展开 AND Expand_Step=0`，这是需要确认/修改的关键点。

多条带场景：

- 第一次 scrape 做拍照、视觉、选带、刮第一条带。
- 多条带中间循环：`collect` 收走当前粉末后，`scrape` 以重刮模式刮下一条带。
- 最后一条带刮完后，PLC 应按 `scrape_IsLast=TRUE` 将硅胶板送废料区；最后一次 collect 可在 scrape 锁外执行，让下一样品的 before_photo 提前抢占空出的拍照刮板工位。

## 2. 通用工位协议

每个工位用 6 变量电平状态机：

| 变量 | 方向 | 含义 |
|---|---|---|
| `<Stage>_Enable` | PC -> PLC | TRUE 启动，FALSE 让 PLC 清 Done |
| `<Stage>_Step` | PLC -> PC | 当前子步，0 idle，90 error |
| `<Stage>_Done` | PLC -> PC | 完成锁存，直到 Enable=FALSE |
| `<Stage>_Error` | PLC -> PC | 故障锁存，直到 Reset |
| `<Stage>_Reset` | PC -> PLC | 清错误、归零状态机 |
| `<Stage>_Busy` | PLC -> PC | Step 在运行区间且 Done=FALSE |

上位机启动时序（v1.10）：

1. 写入业务参数。
2. 写 `<Stage>_Enable=FALSE`，并清 `<Stage>_Confirm`。
3. 不直接写 `<Stage>_Done=FALSE`，而是轮询等待 PLC 自己把 Done 清掉。这是为了确认 PLC 已处理 Enable 下降沿。
4. 读回最后一个标量参数作为写入屏障；失败则回退 50 ms 等待。
5. 写 `<Stage>_Enable=TRUE`。

PLC 通用前提：

- `MODE_State=1`。
- 急停未触发。当前 PLC 程序里多处用 `IF NOT 急停 THEN ... Error ... RETURN`。
- 对应工位空闲，`Step=0`，上一周期 Done 已被 Enable=FALSE 清除。
- PC 已写好本次参数。

PLC 通用错误处理：

- 急停：工位 Step 归零，Done=FALSE，Busy=FALSE，Error=TRUE，并关闭本工位正在驱动的泵、阀、轴、机器人请求。
- Reset：`<Stage>_Reset=TRUE` 时清 Error、Step、Done、Busy，并复位内部子动作 step。
- 工位故障：进入 Step 90，Error=TRUE，等待人工/Recovery Reset。
- 上位机取消任务不会抢写硬件动作中断，只取消 Python 任务与释放账本资源；PLC 当前动作由人工 HMI 或 Recovery Reset 处理。

## 3. 上样点样工位 Sampling

### 3.1 入口参数

上位机写入：

- `Sampling_clean_instructions[1..2]`：内壁清洗、外壁清洗。
- `Sampling_clean_count`：清洗次数。
- `Sampling_prep_instructions[1..2]`：吸空气、废液打出。
- `Sampling_X_coordinate` / `Sampling_Y_coordinate`：料筒孔位逻辑坐标。
- `Sampling_sample_instructions[1..2]`：回抽样品、废液排废。
- `Sampling_dispense_instructions[1..2]`：抽空气、打气点样/释压。

### 3.2 PLC 动作流程

| Step | 动作 | 完成条件 |
|---:|---|---|
| 0 | 空闲，等待 `Sampling_Enable=TRUE` | 启动后进入 5 |
| 5 | `A00_initialization_初始化` | `Sampling_initialization_OK=TRUE` |
| 10 | `A10_clean_清洗` | `Sampling_Cleaning_OK=TRUE` |
| 20 | `A30_Sample_preparation_上样准备` | `Sampling_preparation_OK=TRUE` |
| 30 | `A20_Place_materials_放硅胶板` | `Sampling_Place_materials_OK=TRUE` |
| 40 | `A40_absorb_liquid_吸收液体` | `Sampling_liquid_absorption=TRUE` |
| 50 | `A50_Spray_sample_点样` | `Sampling_Spray_sample_OK=TRUE` |
| 60 | 等机器人取走点样后的硅胶板 | `取点样硅胶板完成=TRUE`，然后 Done |
| 90 | 故障锁存 | 等 `Sampling_Reset` |

客户视角可以理解为：

```text
初始化 -> 清洗上样流路 -> 建立空气隔离段 -> 机器人放硅胶板
-> 吸取样品 -> 点样 -> 机器人把点样后的板送去拍照位
```

### 3.3 前提条件

- 上样点样工位机械结构在初始位置。
- 升降上料机构允许取料，机器人 `Status=0`。
- 机器人调度里 `上样点样允许放硅胶板` 可触发“取升降机硅胶板放点样机构上”。
- 点样完成后，机器人取板去拍照前要求 `上样点样允许取硅胶板 AND scrape_Step=0`。

### 3.4 错误处理

- 急停：停止泵、三通阀回安全位，Sampling Error 锁存。
- Reset：清状态机、内部计数、内部动作 step。
- 泵通信、轴不到位、机器人超时目前在代码里多处仍是待完善判断，应在原子化时补超时和错误码。

### 3.5 可拆原子动作

- 泵初始化。
- 内壁清洗、外壁清洗。
- 吸空气隔离段。
- 样品吸取。
- 废液排废。
- 点样打出与回抽释压。
- 机器人取新硅胶板到点样位。
- 机器人取点样后硅胶板到拍照位。

## 4. 点样后拍照 before_photo / 拍照刮板 FSM 的 PhotoMode=1

`before_photo` 不是独立 PLC 工位，而是复用 `scrape` 工位：

- PC 写 `scrape_PhotoMode=1`。
- PC 启动 `scrape_Enable=TRUE`。
- PLC 到达 `scrape_Step=15` 且 `scrape_WaitConfirm=TRUE` 后，PC 拍照并写 `scrape_Confirm=TRUE`。

### 4.1 PLC 动作流程

| Step | 动作 | 完成条件 |
|---:|---|---|
| 0 | 空闲 | `scrape_Enable=TRUE` |
| 10 | `A00_initialization_初始化` | `Camera_scraper_initialization_OK=TRUE` |
| 15 | `A10_Material_camera_拍照硅胶板`，送板到拍照位并遮光 | `scrape_WaitConfirm=TRUE` 后等 PC Confirm |
| 15 内部 | PC 拍 before.jpg，写 `scrape_Confirm=TRUE` | PLC 关闭遮光、拍照轴回零，`Photo_preparation_completed_OK=TRUE` |
| 16 | PhotoMode=1 路径，允许机器人从拍照位取板去展开 | `取拍照硅胶板完成=TRUE`，然后 Done |
| 90 | 故障锁存 | 等 `scrape_Reset` |

### 4.2 前提条件

- scrape FSM 空闲。
- 拍照位空闲，机器人可把点样后的硅胶板放到拍照位。
- 相机由上位机控制，PLC 只负责把板送到稳定拍照位置并设置 `scrape_WaitConfirm`。
- 从拍照位去展开的机器人路径当前要求 `Expand_Step=0`；并行优化需要改为更宽准入条件。

### 4.3 错误处理

- PC 拍照失败会抛异常；当前上位机会在 Step 0/10/15 等安全点尝试写 `scrape_Enable=FALSE` 清理。
- PLC 急停：关真空/无刷电机/动作输出，Error 锁存。
- Reset：清 `scrape_Step`、`scrape_Error`、`scrape_WaitConfirm` 及初始化/拍照/刮板/机器人内部 step。

## 5. 展开工位 Expand

展开分两段：准备序列器和每缸排液 FSM。

### 5.1 展开准备入口参数

- `Expand_Target_Tank`：目标缸号 1-8。
- `Expand_Mode_Flag`：0=润洗展缸，1=清洗管路。
- `Expand_forward_instructions`：展开剂注射泵指令。
- `Expand_rinse_count`：润洗次数。
- `Expand_up_liquid_count`：上液次数。

PLC 自动推导：

- `Expand_Group = (tank - 1) / 4 + 1`
- `Expand_Number = (tank - 1) MOD 4 + 1`

### 5.2 展开准备流程

| Step | 动作 | 完成条件 |
|---:|---|---|
| 0 | 校验目标缸 | tank 在 1-8 且 `Tank_State[tank]=0` |
| 5 | `A00_initialization_初始化` | 泵初始化完成 |
| 10 | 润洗/清洗：`A20_clean_expand_润洗展缸` 或 `A10_pipeline_cleaning_清洗管路` | `Expand_Group_clean_OK=TRUE` |
| 20 | `A40_up_liquid_上液` | `Expand_up_liquid_OK=TRUE` |
| 30 | `A30_silica_gel_plate_放硅胶板` | `Expand_silica_gel_plate_OK=TRUE` |
| 40 | 交付至展开态 | `Tank_State[target]=40`，`Expand_Done=TRUE`，Step 回 0 |
| 90 | 故障锁存 | 等 `Expand_Reset` |

客户视角：

```text
选择展缸 -> 初始化 -> 润洗或清洗管路 -> 加展开剂
-> 机器人放入硅胶板 -> 缸进入展开静置状态
```

### 5.3 展开准备前提条件

- 目标缸空闲：`Tank_State[target]=0`。
- 同组泵资源未被其它 prep 占用。上位机通过 `_prep_lock + group_lock` 保证。
- 机器人可把拍照后的硅胶板放入目标展缸。
- 展开流程只负责 prep 完成，不等待展开时间结束。

### 5.4 排液流程

PC 在展开时间到或手动提前排液时写 `Tank_Drain_Enable[i]=TRUE`。

| Tank_State | 动作 | 完成条件 |
|---:|---|---|
| 40 | Developing，等待排液触发 | `Tank_Drain_Enable[i]=TRUE` |
| 50 | 打开排液阀，开启真空泵占位 | 组废液检测传感器 + `DrainTimer[i]` |
| 55 | 吹气清扫 | `BlowTimer[i]` |
| 60 | 关闭阀，气缸回原点 | 对应气缸原点信号 |
| 65 | 机器人取展缸硅胶板 | `RO_ParameterList1=i` 后置 `Tank_State=99` / `Drain_Done=TRUE` |
| 99 | 排液/取板完成 | PC 写 `Drain_Enable=FALSE`，再写 `Tank_State=0` 释放 |
| 90 | 急停/错误 | Recovery 强制排液或人工处理 |

当前排液支持 8 缸并行，机器人取板阶段通过机器人流程串行化。

### 5.5 错误处理

- 目标缸号非法或目标缸非 idle：`Expand_Error=TRUE`，`Expand_Step=90`。
- 急停：prep 中的缸或排液中的缸标记 90，关闭阀和真空泵。
- Reset：清 Expand 状态；若当前 prep 缸仍在 10，标记该缸 90，避免孤儿缸。
- PC 侧若任务取消或急停，会把资源账本标记为 `NEEDS_DRAIN`，等待 Recovery。

### 5.6 可拆原子动作

- 展缸占用校验与分配。
- 泵初始化。
- 管路清洗。
- 展缸润洗。
- 上液。
- 机器人放板入展缸。
- 展开等待。
- 单缸排液。
- 单缸吹气。
- 气缸复位。
- 机器人从展缸取板。

## 6. 展开后拍照 + 刮取 scrape / PhotoMode=0

当前上位机语义：

- 所有 scrape 都在 Step 15 做唯一 PC 介入点。
- PC 在 Step 15 / WaitConfirm 窗口完成：拍照、视觉分析、用户选 band、生成 CNC 点位数组、写入 PLC、Confirm。
- PLC 收到 Confirm 后继续 Step 20 CNC 刮取，再 Step 30 机器人取粉末收集器。

### 6.1 入口参数

- `scrape_PhotoMode`：0=完整拍照刮取，1=before_photo，2=重刮（上位机当前会写，但当前 PLC XML 未检出明确消费逻辑）。
- `scrape_IsLast`：是否最后一次刮取（上位机当前会写，但当前 PLC XML 未检出明确消费逻辑）。
- `scrape_Source_Tank`：诊断用源展缸号。
- `g_sx/g_sy/g_cx/g_cy[1..400]`：刮扫和收集路径点。
- `g_pass_count`：刮取 pass 数；0 表示安全占位，跳过刮取。
- `g_total_depth/g_plate_surface_z/g_safe_z/g_approach_z/g_scrape_feed/g_plunge_feed`：CNC 标量参数。
- 耗材参数：`scrape_Fetch_Rack_Plate`、`scrape_Old_Plate_Slot`、`scrape_Consume_Slot` 等。

### 6.2 PLC 动作流程

| Step | 动作 | 完成条件 |
|---:|---|---|
| 0 | 空闲 | `scrape_Enable=TRUE` |
| 10 | `A00_initialization_初始化` | `Camera_scraper_initialization_OK=TRUE` |
| 15 | `A10_Material_camera_拍照硅胶板` | `scrape_WaitConfirm=TRUE` 后等 PC Confirm |
| 15 内部 | PC 拍 after.jpg、视觉、下发点位、Confirm | `Photo_preparation_completed_OK=TRUE` |
| 20 | CNC 刮取：`A20_Scraper_collection_刮板收集` | `Scraper_collection_completed=TRUE`；若 `g_pass_count=0` 跳过 |
| 30 | `A30_Robot_material_retrieval_机器人取粉末收集器` | `Robot_completes_material_retrieval=TRUE`，然后 Done |
| 90 | 故障锁存 | 等 `scrape_Reset` |

客户视角：

```text
机器人把展开后的板放到拍照/刮取位
-> PLC 定位并遮光
-> 上位机拍照和视觉识别
-> 上位机把刮取路径传给 PLC
-> PLC 执行 CNC 刮取
-> 机器人把粉末收集器送往收集工位
```

### 6.3 前提条件

- scrape FSM 空闲。
- 展缸排液/取板已完成，且 RecipeTask 已拿到 `_scrape_lock`。
- 机器人可从展缸取板并放到拍照刮板位：`展开工位允许取硅胶板 AND scrape_Step=0`。
- 粉末收集器暂存 A 已准备好，机器人可按 `scrape_Consume_Slot` 放到刮取位。
- PC 必须在 Confirm 前写好 CNC 数组；`g_pass_count=0` 是明确的“跳过刮取”安全占位。

### 6.4 错误处理

- CNC 点位生成失败或视觉失败继续：PC 下发安全占位数组，PLC 看到 `g_pass_count=0` 跳过刮取。
- 视觉失败且用户中止：上位机写 `scrape_Enable=FALSE` 并等待 FSM 归零。
- PLC 急停：停轴、关真空/电机、Error 锁存。
- Reset：清内部 `初始化step/拍照step/刮板收集step/机器人取物料step`。

### 6.5 可拆原子动作

- 拍照刮板初始化。
- 机器人从展缸取板到拍照刮取位。
- 拍照轴定位、遮光气缸动作、WaitConfirm 门控。
- CNC 刮扫路径执行。
- 粉末收集器夹持/退出。
- 末次刮取后的硅胶板废弃动作。

## 7. 收集工位 collect

### 7.1 入口参数

- `collect_forward_instructions`：收集注射泵指令。
- `collect_count`：重复打液次数。
- 耗材参数：`collect_Fetch_Rack_Plate`、`collect_Old_Plate_Slot`、`collect_Consume_Slot`。
- `collect_Powder_Return_Slot`：粉末收集器归还暂存 A 的原孔位。

### 7.2 PLC 动作流程

| Step | 动作 | 完成条件 |
|---:|---|---|
| 0 | 空闲 | `collect_Enable=TRUE` |
| 5 | `A00_initialization_初始化` | 各气缸原点 + 泵初始化完成 |
| 10 | `A10_preparation_准备` | `collect_prepare_OK=TRUE` |
| 20 | `A20_collect_收集` | `collect_OK=TRUE` |
| 30 | `A30_transport_物料搬运` | `收集工位放收集器完成=TRUE` 后 Done |
| 90 | 故障锁存 | 等 `collect_Reset` |

`A20_collect_收集` 内部逻辑：

1. 如果 `collect_forward_instructions` 非空，启动收集进液。
2. 发送泵转发指令。
3. 查询泵状态 `/3Q\r`。
4. 泵空闲后切换排液/正压排液。
5. 计数达到 `collect_count` 后置 `collect_OK=TRUE`。

客户视角：

```text
收集平台初始化 -> 放入收集瓶和粉末收集器
-> 注射泵按配方加液/洗脱
-> 机器人把粉末收集器/收集瓶转运回暂存或仓库
```

### 7.3 前提条件

- collect FSM 空闲。
- 收集平台各气缸在原点。
- 玻璃瓶暂存 B 和粉末收集器交接状态与 PC 耗材账本一致。
- 机器人可按 `collect_Consume_Slot` 取暂存瓶到收集工位。
- `collect_Powder_Return_Slot>0` 时，机器人可把粉末收集器归还到暂存 A 对应孔位。

### 7.4 错误处理

- 急停：停止泵，收集工位 Error 锁存。
- Reset：清 Step/Error/Busy/Done，并复位内部动作 step。
- 泵超时、气缸不到位、机器人不到位目前仍需在原子化时补明确错误码和超时分支。

### 7.5 可拆原子动作

- 收集平台初始化。
- 放入收集瓶。
- 放入粉末收集器。
- 注射泵进液。
- 正压排液/洗脱。
- 粉末收集器归还暂存 A。
- 收集瓶归还暂存 B 或仓库。

### 7.6 原子化探索目标（首选 collect）

后续 PLC 工位动作原子化建议先从 collect 开始，因为它比点样、展开、拍照刮板更简单：没有视觉介入，没有 CNC 路径生成，伺服参与主要体现在机器人地轨 11Y 的工位定位，核心动作集中在收集平台气缸、收集泵/阀、机器人交接和耗材账本。

本轮探索目标不是立即把 collect 拆成外部可直接调用的所有 IO，而是先在 PLC 侧建立清晰的动作结构：

```text
执行器原子层 -> 工位动作层 -> collect 业务编排层
```

可用于后续 goal 指令的简短推进提示：

```text
从第一性原理出发推进 collect 工位动作拆解：PLC 负责原始传感器、I/O 闭环、安全互锁、动作执行和可重试性判断；上位机只表达动作意图并消费动作状态、结果、错误码、诊断摘要和 retryable/safe_state。不要把所有传感器直接上移给上位机，也不要让上位机盲目重试非幂等物理动作。先在不破坏现有 collect_Enable 完整流程的前提下，梳理 Collect_Init、Collect_LoadPowderCollector、Collect_LoadBottle、Collect_Elute、Collect_UnloadBottle、Collect_UnloadPowderCollector 六个工位动作，明确每个动作的入口条件、完成条件、失败条件、执行器依赖、物理状态变化、错误码、恢复方式和是否可自动重试。
```

建议的 collect 工位动作层：

| 工位动作 | 内部依赖 | 目标状态 / 完成条件 |
|---|---|---|
| `Collect_Init` | 收集下压/夹持/升降/伸缩气缸，收集泵，收集相关允许位 | 气缸回安全初始态，泵初始化完成，内部 step 与完成位清零 |
| `Collect_LoadPowderCollector` | 机器人流程 110/130 相关交接，收集夹持气缸 | 粉末收集器到收集位，夹持完成，机器人退出安全位置 |
| `Collect_LoadBottle` | 机器人流程 120，收集伸缩/升降/下压气缸，瓶有无传感器 | 收集瓶到位，平台升降和下压到洗脱姿态 |
| `Collect_Elute` | 收集泵、进液阀、排液阀、正压排液阀 | 按 `collect_forward_instructions` 和 `collect_count` 完成洗脱/排液循环 |
| `Collect_UnloadBottle` | 收集下压/升降/伸缩气缸，机器人流程 140 | 收集瓶回暂存 B 或后续指定位置 |
| `Collect_UnloadPowderCollector` | 收集夹持气缸，机器人流程 130，`collect_Powder_Return_Slot` | 粉末收集器回暂存 A 原孔位，collect Done |

执行器原子层建议这样划分：

- 气缸原子：收集下压、夹持、升降、伸缩；每个动作必须有目标态、原点/动点反馈、超时、错误码和 Reset 语义。当前 `PLC_Cyinder_气缸动作` 已经通过 `FB_cylinder` 复用底层气缸逻辑，后续重点是把它包装为可编排、可诊断的动作单元。
- 伺服原子：至少包括 `AxisHome`、`AxisMoveAbs`、`AxisMoveRel`、`AxisStop`、`AxisResetError`、`AxisWaitInPosition`。collect 本体不直接大量使用伺服，但机器人搬收集瓶/收集器前依赖地轨 `地轨轴11YDATE` 到收集/暂存/仓库点位，因此 collect 样例中应把“地轨到站”作为机器人动作的前置运动模板，而不是忽略伺服。
- 机器人原子：取/放收集器、取/放收集瓶、取/放收集器组回仓库。机器人动作不应脱离地轨伺服和工位允许位单独理解。
- 流体原子：收集泵初始化、收集进液、泵状态查询、排液、正压排液。
- 状态/协议原子：等待 collect 空闲、等待机器人完成位、等待气缸到位、等待泵空闲、Reset pulse、错误锁存和错误码上报。

对外开放策略建议分阶段：

1. 第一阶段只整理 PLC 内部动作结构和状态反馈，外部仍调用完整 `collect_Enable` 流程。
2. 第二阶段开放只读状态，例如各气缸到位、瓶有无、暂存位、collect 当前内部动作。
3. 第三阶段开放受限工位动作，例如 `Collect_LoadBottle` / `Collect_Elute`，仍由 PLC 做互锁。
4. 最后才考虑开放裸执行器动作，例如单轴 `MoveAbs` 或单气缸动作；这些只适合维护/调试模式，不建议直接进入生产编排。

预期产物与验收要求：

- collect 动作分解表：每个工位动作必须写清入口条件、执行器依赖、完成条件、失败条件、是否改变物理状态、是否可自动重试。
- collect 执行器资产表：PLC 内部必须核对气缸、阀、泵、关键传感器、地轨伺服、机器人交接动作；该表主要服务 PLC 侧闭环与诊断，不代表全部传感器都要暴露给上位机。
- 统一动作结果：每个动作至少能给出 `status`、`step`、`error_code`、`message`、`retryable`、`safe_state`。上位机不需要读取全部原始传感器，但必须能判断动作是否完成、失败位置大类、是否允许自动重试、是否需要人工恢复。
- 错误与恢复策略：泵查询/等待类错误可考虑自动重试；机器人搬运、气缸夹持、收集瓶/收集器交接等会改变物理世界的动作默认不可盲重试，只有 PLC 明确标记 `retryable=true` 且 `safe_state` 允许时，上位机才可重发。
- 兼容性：现有完整 collect stage 仍通过 `collect_Enable` 跑通；内部原子化不得破坏当前上位机契约。
- 可诊断性：失败不能只表现为 `collect_Error=TRUE`，至少要能定位到泵/阀、气缸、机器人、地轨伺服、耗材/传感器、工位互锁中的一类。

传感器信息边界：

```text
PLC 掌握原始传感器、互锁条件和硬件闭环。
上位机掌握动作意图、动作生命周期、诊断摘要、错误码、可重试性和恢复建议。
```

因此，上位机不应为了编排 collect 而直接订阅所有收集平台传感器。原始传感器可以在维护/诊断接口中只读查看，但生产编排应消费 PLC 汇总后的动作状态。这样既避免把安全逻辑上移，也避免上位机根据单个传感器误判并重复触发非幂等动作。

需要在原子化前核对的 collect I/O 表：

| 对象 | 输出/命令 | 反馈 | 备注 |
|---|---|---|---|
| 收集下压气缸 | `收集下压气缸自动` | `收集平台下压气缸原点`、疑似动点反馈待核对 | 当前气缸 FB 中 `xPosRetract` 接控制信号，需确认是否应接真实动点 |
| 收集夹持气缸 | `收集夹持气缸自动` | `收集平台夹持气缸原点/动点` | 夹持粉末收集器 |
| 收集升降气缸 | `收集升降气缸自动` | `收集平台升降气缸原点/动点` | 瓶到位后升降 |
| 收集伸缩气缸 | `收集伸缩气缸自动` | `收集平台推出气缸原点/动点` | 取放瓶交接 |
| 收集泵/阀 | `收集进液自动`、`收集排液自动`、`收集正压排液自动` | 泵空闲、计数、气泡/瓶有无传感器 | 需补 timeout/error 分支 |
| 地轨 11Y | `地轨轴11YDATE.fAbsTarget/xMoveAbs` | `地轨轴11YDATE.bAbMoveDone` | 机器人动作前置伺服移动 |

## 8. 机器人调度流程

当前机器人侧是一个全局 `机器人流程` 调度器，按优先级扫描触发条件。核心流程如下：

| 机器人流程 | 触发条件 | 动作 |
|---:|---|---|
| 10 | `上样点样允许放硅胶板` | 取升降机硅胶板放点样机构 |
| 20 | `上样点样允许取硅胶板 AND scrape_Step=0` | 取点样硅胶板放拍照机构 |
| 30 | `拍照工位允许取硅胶板去展开 AND Expand_Step=0` | 取拍照硅胶板放展缸 |
| 40 | `展开工位允许取硅胶板 AND scrape_Step=0` | 取展缸硅胶板到拍照刮取机构 |
| 50 | `拍照工位允许取硅胶板放废料区` | 取拍照刮取硅胶板放废料区 |
| 60 | `collect_Fetch_Rack_Plate>0 AND NOT 收集平台暂存工位传感器` | 取收集瓶组到暂存 B |
| 70 | `scrape_Fetch_Rack_Plate>0 AND NOT 刮板拍照暂存工位传感器` | 取粉末收集器组到暂存 A |
| 80 | `collect_Old_Plate_Slot>0 ...` | 旧收集瓶组回仓库 |
| 90 | `scrape_Old_Plate_Slot>0 ...` | 旧收集器组回仓库 |
| 100 | `拍照工位允许放收集器 AND scrape_Consume_Slot>0` | 取暂存收集器到刮取位 |
| 110 | `拍照工位允许取收集器 AND collect_Step=0` | 取刮板收集器放到收集工位 |
| 120 | `收集工位允许放收集瓶 AND collect_Consume_Slot>0` | 取暂存收集瓶到收集工位 |
| 130 | `收集工位允许取收集器 AND collect_Powder_Return_Slot>0` | 取收集器到暂存工位 |
| 140 | `收集工位允许机器人取收集瓶放暂存工位` | 取收集瓶到暂存工位 |

机器人调度是后续原子化的关键：很多“工位 Step 完成条件”实际上由机器人流程中的完成位回写，例如 `取点样硅胶板完成`、`取拍照硅胶板完成`、`收集工位放收集器完成`。

## 9. 耗材动作嵌入点

耗材不是独立工位，而是通过 PC 决策参数触发机器人动作：

- scrape 侧：
  - `scrape_Fetch_Rack_Plate`：从仓库取粉末收集器组到暂存 A。
  - `scrape_Old_Plate_Slot`：旧粉末收集器组回仓库。
  - `scrape_Consume_Slot`：从暂存 A 取当前孔位的粉末收集器到刮取位。
- collect 侧：
  - `collect_Fetch_Rack_Plate`：从仓库取收集瓶组到暂存 B。
  - `collect_Old_Plate_Slot`：旧收集瓶组回仓库。
  - `collect_Consume_Slot`：从暂存 B 取收集瓶到收集位。
  - `collect_Powder_Return_Slot`：粉末收集器从收集位回暂存 A 原孔。

原子化时建议把“架板交换”“暂存到工位”“工位到暂存”“暂存到仓库”拆成独立机器人原子动作，PC 只负责决策参数，不让 PLC 推理账本。

## 10. L2 迁移时需要保持的当前事实

- 最新 XML 已包含 `scrape_PhotoMode=2` 和 `scrape_IsLast` 的当前生产路径；它们在旧 Stage 运行期间继续保留，PhotoScrape L2 验收后随旧路径删除。
- 当前 PLC 有 Step 5、15、16、60 等内部子步。L2 拆分应复用其设备动作，但不要求沿用旧 Step 编号。
- HMI 手动变量、MODE/E-Stop、气缸 FB、轴控制和现有恢复功能必须保留。
- 当前工作流已经跑通。L2 改造关注的是重新划分职责、减少跨工位自治和增加结构化结果，而不是因为遗留 TODO 推断现有动作不可用。
- 新动作通道、机器人直连和 PLC Mock 必须同步更新，避免实机与本地调试出现两套节点树。
- 现有完整流程是迁移回归基线；对应工位通过 L2 回归后，再删除旧 Stage、旧路由变量和冗余判断。

本文不再维护目标 ActionCode、Confirm 或锁设计，避免与目标文档重复。相关设计统一见：

- `PLC_L2_Workstation_Action_Decomposition.md`
- `L2分层架构迁移代码分析.md`
