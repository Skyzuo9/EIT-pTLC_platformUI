# PLC 统一工位协议（电平驱动自治状态机）v1.7

> 版本：v1.7（E-Stop Phase 0 体系落地）日期：2026-05-18
> 状态：collect + develop + spotting + scrape 工位生效 + E-Stop 安全停车体系启用
>
> v1.7 变更要点：
> 1. **E-Stop 安全停车体系**：新增§9，明确 PLC 侧各工位最小停车动作、Tank_State 急停标记规则、响应时延要求、Recovery 流程。
> 2. **PC 侧 EstopBroadcaster + Recovery UI**：`core/estop.py` 提供 `broadcast_estop` / `reset_estop` / `is_estop_active`；Recovery Tab 急停自动弹出；`ResourceManager` 新增 `NEEDS_DRAIN=91` 状态与 `manual_release()` 接口。
> 3. **`StageState` 新增 `estop`**：区分 ESTOP / CANCELLED / ERROR 三种终止状态，供 UI 和日志分析。
> 4. **WaitConfirm 显式握手变量**：新增 `scrape_WaitConfirm : BOOL`，PLC 在进入 confirm 轮询前置 TRUE、消费 Confirm 后清零；PC 侧 `await_stage_step` 返回条件升级为 `Step==target AND WaitConfirm==TRUE`，`confirm_stage` 写 Confirm 前防御性校验 WaitConfirm。消除 PLC 写 `_Step` 与进入 confirm 轮询之间的扫描周期窗口。
>
> v1.6 变更要点：
> 1. **PhotoMode 路由机制**：新增 `scrape_PhotoMode`(INT) 变量，控制 Step 10 初始化后的路径选择。0=完整刮板模式(默认, Step 10→20→30→40)，1=仅before-photo模式(Step 10→15→归位Done)。
> 2. **Step 15 before-photo 乒乓等待**：新增 Step 15 子步，PLC 将硅胶板送至拍照位后停在 Step 15，等待 PC 侧拍照+Confirm 后归位+Done。用于点样后拍照场景（BeforePhotoStage）。
> 3. **Phase A 完成门控**：Step 15/20 的 Confirm 上升沿检测增加 `phaseA_done` 门控，确保送板完成前 Confirm 信号不提前触发路径切换。
> 4. **消费型变量归零位置修正**：`scrape_PhotoMode` 不再在 Step 0 无条件归零（否则 PC 写入 PhotoMode=1 会被每周期覆盖），改为 Step 10 路由决策完成后消费归零。
>
> v1.5 变更要点：
> 1. **scrape（拍照刮板）工位平移**：PLC 变量前缀 `scrape`（与上位机 stage name 同名），单 FSM + 乒乓握手。
> 2. **乒乓握手机制（v1.5）**：Step=20（拍照完成）为等待确认子步，PLC 在此轮询 `scrape_Confirm` 信号；上位机先 `await_stage_step(20)` 再执行视觉分析 → 下发 G-code → 写 `scrape_Confirm=TRUE`，再 `await_stage_done`。
> 3. **新增 `PLCClient.confirm_stage` API**：写 `<stage>_Confirm=TRUE`，让 PLC 从乒乓等待步继续推进。PLC 侧消费 Confirm 后自动清零。
> 4. **新增 `scrape_gcode_instructions` 业务参数**：STRING(128)，G-code 动态生成指令（替代旧的 gcode_name 预置方式），由 PC 侧视觉分析后写入。
> 5. **删除 Vision_Done / Vision_Result_X / Vision_Result_Y**：scrape 电平范式替代旧 Vision 乒乓通道，视觉分析内嵌于 ScrapeStage 流程。
>
> v1.4 变更要点：
> 1. **spotting（上样点样）工位平移**：PLC 变量前缀 `Sampling`（实机 GVL 命名），上位机 stage name 为 `spotting`。
> 2. **STRING 数组参数**：`Sampling_bubble_instructions` 为 `ARRAY[1..16] OF STRING(128)`，配合 `Sampling_bubble_count` 管理变长气泡序列指令。上位机新增 `PLCClient.write_string_array()` 方法整体写入。
> 3. **清洗参数可配**：`Sampling_clean_instructions`(STRING) + `Sampling_clean_count`(INT) 支持可配清洗次数和指令。
> 4. **PC侧翻译**：清洗/气泡/吸液/点样指令均由 PC 侧翻译后写入 PLC 变量（复用 pump_translator / sample_pump_translator）。
>
> v1.4a spotting 4 数组重构（2026-06-01）：
> 1. **泵指令统一为 4 个 1×2 数组**：删除 `Sampling_bubble_instructions`(ARRAY[1..4]) + `Sampling_aspirate_instructions`(STRING) + 旧 `Sampling_dispense_instructions`(STRING)；新增 `Sampling_prep_instructions` / `Sampling_sample_instructions` / `Sampling_dispense_instructions`（均 ARRAY[1..2]）。
> 2. **`Sampling_clean_instructions` 从标量改为 ARRAY[1..2]**：[1]=内壁清洗（吸清洗液→输出口打出），[2]=外壁清洗（吸清洗液→废液口打出，新增功能）。
> 3. **每步消费一个数组**：Step 10→clean_array，Step 20→prep_array，Step 40→sample_array，Step 50→dispense_array。PLC 顺序执行数组内 2 条指令。
>
> v1.3 变更要点：
> 1. **Expand_Done 语义变更**：从“整流程完成”变为“prep 完成”——Step 40 交付时立即 Done=TRUE、Step 回 0、序列器释放，支持多缸交替 prep。
> 2. **删除乒乓握手**：Step 35 / Expand_Confirm 废弃，排液由独立 per-tank 变量 Tank_Drain_Enable[i] / Tank_Drain_Done[i] 替代。
> 3. **新增 Expand_Target_Tank**：PC 写入目标缸号(1-8)，PLC 自动推导 Expand_Group / Expand_Number；上位机不再写入 Group/Number。
> 4. **新增数组节点**：Tank_State[1..8] / Tank_SampleID[1..8] / Tank_Drain_Enable[1..8] / Tank_Drain_Done[1..8]，采用 OPC UA 真数组节点。
> 5. **DevelopStage 四阶段流程**：allocate + prep → sleep(develop) → drain → release。
> 6. **新增 ResourceManager**：展缸分配/释放/状态同步/绑定管理。
>
> v1.2 变更要点：
> 1. **develop（展开）工位平移**：PLC 变量前缀为 `Expand`（实机 GVL 命名），上位机 stage name 为 `develop`。
> 2. **乒乓握手机制**：develop 工位 Step=35 为等待确认子步，PLC 在此轮询 `Expand_Confirm` 信号；上位机先 `await_stage_step(35)` 再写 `Expand_Confirm=TRUE`，再 `await_stage_done`。——**v1.3 已废弃**
> 3. **新增 `PLCClient.await_stage_step` API**：轮询 `<stage>_Step` 直到到达目标子步号后返回，不做任何写入。
> 4. develop 工位业务参数：`Expand_Mode_Flag / Expand_Group / Expand_Group_clean / Expand_Number / Expand_forward_instructions_clean / Expand_Group_UP / Expand_Number_UP / Expand_forward_instructions_UP`。——**v1.3 精简**
>
> v1.1 变更要点：
> 1. **删除 Recipe_Param_A..F / I1..I4 / Recipe_Gcode_Name / Recipe_Mode_Flag 通用通道抽象**——所有工位的参数变量按业务命名直接挂在 GVL 下；上位机 `send_recipe_params(dict)` 中 dict 的 key 直接是 PLC 变量名，零二次赋值。
> 2. **每工位新增 `<Stage>_Busy`（PLC→PC, BOOL）**，由各工位 ST 自身派生。全局 `PLC_Busy` 改由独立的 BusyAggregator PRG 单写：`PLC_Busy := collect_Busy OR Expand_Busy OR ...`，避免多 PRG 写同一 BOOL 冲突。
> 3. collect 工位参数：`Recipe_Gcode_Name` → `collect_forward_instructions`（STRING(128), 注射泵转发指令，非 G 代码）；`Recipe_Param_I1` → `collect_count`（DINT, 重复打液次数）。

---

## 1. 设计原则

- **第一性原理**：协议只解决三件事——启动、观察、交参数；其它由 PLC 自治。
- **奥卡姆剃刀**：每个变量都必须回答"不存在会怎样"；不能回答的立即删掉。
- **Mock 与实机同构**：Mock 节点树、变量名、子步编号与实机一致，上位机代码零分支。
- **Debug 与正式路径同源**：UI Debug Tab 的"启动 collect"按钮走与 Scheduler 完全相同的 `start_stage` 路径。

---

## 2. 每工位 6 变量（唯一范式）

| 变量 | 类型 | 方向 | 语义 |
|------|------|------|------|
| `<Stage>_Enable` | Bool | PC→PLC | TRUE 启动状态机；FALSE 让 PLC 清 `_Done` 并回 idle |
| `<Stage>_Step` | Int32 | PLC→PC | 当前子步号（从 SUB_STEPS 集合取值） |
| `<Stage>_Done` | Bool | PLC→PC | 完成锁存，直到 `_Enable=FALSE` 清零 |
| `<Stage>_Error` | Bool | PLC→PC | 故障锁存（`_Step=90`），`<Stage>_Reset=TRUE` 清零 |
| `<Stage>_Reset` | Bool | PC→PLC | TRUE 清 `_Error` 与 `_Step=90`，回到 idle |
| `<Stage>_Busy` | Bool | PLC→PC | 由各工位 ST 自身派生：`(_Step ∈ [10,80]) AND NOT _Done`；供 BusyAggregator 与上位机互锁查询 |

### 全局变量

| 变量 | 类型 | 方向 | 语义 |
|------|------|------|------|
| `PLC_EStop` | Bool | PLC→PC | TRUE 代表 PLC 侧急停，强制所有 `_Enable=FALSE`；上升沿触发上位机 on_estop 回调 |
| `PLC_Busy` | Bool | PLC→PC | **由 BusyAggregator PRG 单写**：`PLC_Busy := collect_Busy OR develop_Busy OR spotting_Busy OR scrape_Busy`。供 UI 点动互锁 |

> **写者唯一原则**：每个 PLC BOOL 变量必须只有一个 ST 程序写它，避免周期性互相覆盖。`<Stage>_Busy` 只能由对应工位 ST 写；`PLC_Busy` 只能由 BusyAggregator PRG 写。

### 参数通道（v1.1 业务命名）

本协议**不再维护通用 `Recipe_Param_*` 集合**。每个工位需要的参数直接以业务名挂在 GVL 下，例如：

- collect：`collect_forward_instructions`（STRING(128)，注射泵转发指令）、`collect_count`（DINT，重复打液次数）
- develop / spotting / scrape：在 Phase B1/B2/B3 平移时各自声明业务变量，命名规范 `<stage>_<purpose>[_<unit>]`

上位机 `PLCClient.send_recipe_params(params: dict)` 中 dict 的 key 即 PLC 变量名，类型由上位机 NODE_TYPES 与 PLC 端 GVL 一致。

---

## 3. 时序约定

```
           PC 写参数                                        PC 清 _Enable
           ┆ (A/B/I1/I2/...) ≥50ms                          ┆
           ▼                   ▼                            ▼
_Enable  ──┬─────────────────────────────────────────────────┬──
           │                                                 │
_Step   0 ─┤    10    20    30                              ┌─ 0
           │                                                 │
_Done   ───┴─────────────────────────────────┌───────────────┴──
                                             │（锁存至 _Enable=FALSE）
```

- **参数先写，再置 `_Enable=TRUE`**：上位机在 `_Enable` 写入前必须确保所有配方静态参数已写入对应通道，并留 ≥ 50 ms 余量。
- **`_Done` 锁存**：PLC 置位后保持，直到上位机写 `_Enable:=FALSE`。避免"短脉冲被轮询漏检"。
- **`_Error` 锁存**：PLC 置位后保持，直到上位机写 `<Stage>_Reset:=TRUE`；随后 PLC 清 `_Error` 与 `_Step`，回 idle。
- **急停**：`PLC_EStop=TRUE` 时 PLC 端强制所有 `_Enable:=FALSE`；上位机心跳检测到上升沿触发 on_estop。

---

## 4. collect 工位（v1.0 实例）

### 4.1 子步定义

| 子步号 | 键 | 中文标签 | 说明 |
|--------|-----|---------|------|
| 0 | `idle` | 空闲 | 未启动或已完成后的回归状态 |
| 10 | `prepare` | 收集准备 | 气路/注射泵初始化 |
| 20 | `collecting` | 收集中 | 按 `liquid_repeat_count` 重复调用 `syringe_forward_cmd` 打液 |
| 30 | `transfer` | 物料转运 | 完成打液后转运并收尾，完成后 PLC 置位 `_Done` 并回 0 |
| 90 | `error` | 故障 | 锁存故障态，等待 `_Reset` 清零 |

> 注：原 "60 finish" 已并入 30 transfer。最终轨迹 `0 → 10 → 20 → 30 → 0(+Done)`。

### 4.2 节点命名（沿用现有 GVL 命名空间）

OPC UA 树：`Objects/DeviceSet/Inovance-ARM-Linux/Resources/Application/GlobalVars/GVL/<name>`。

| 变量 | 类型 | 方向 |
|------|------|------|
| `collect_Enable` | Boolean | PC→PLC |
| `collect_Step` | Int32 | PLC→PC |
| `collect_Done` | Boolean | PLC→PC |
| `collect_Error` | Boolean | PLC→PC |
| `collect_Reset` | Boolean | PC→PLC |
| `collect_Busy` | Boolean | PLC→PC |
| `collect_forward_instructions` | STRING(128) | PC→PLC |
| `collect_count` | DINT | PC→PLC |

### 4.3 参数通道（v1.1：业务直名，仅 2 个）

| YAML 字段 | 类型 | PLC 变量 | 消费子步 |
|-----------|------|----------|----------|
| `syringe_forward_cmd` | str | `collect_forward_instructions` | 20 collecting |
| `liquid_repeat_count` | int | `collect_count` | 20 collecting |

上位机 `Stage.PARAM_CHANNEL_MAP` 中 channel value 直接是 PLC 变量名，PLC ST 在子步 20 直接消费同名变量，无二次赋值。

### 4.4 上位机调用模板

```python
# 启动
await plc.write_variable("collect_forward_instructions", params["syringe_forward_cmd"])
await plc.write_variable("collect_count",                params["liquid_repeat_count"])
await asyncio.sleep(0.05)                         # 50 ms 余量
await plc.write_variable("collect_Enable", True)

# 观察（由 PLCClient.await_stage_done 封装）
while True:
    step = await plc.read_variable("collect_Step")
    if await plc.read_variable("collect_Done"):
        break
    if await plc.read_variable("collect_Error") or step == 90:
        raise RuntimeError("collect stage error")
    await asyncio.sleep(0.15)

# 收尾
await plc.write_variable("collect_Enable", False) # 让 PLC 清 _Done
```

### 4.5 故障恢复

```python
await plc.write_variable("collect_Reset", True)   # PLC 清 _Error 与 _Step
await asyncio.sleep(0.1)
await plc.write_variable("collect_Reset", False)  # 复位信号回落
```

---

## 5. Phase A 与 Phase B 的边界

- Phase A 只实现 collect 工位；`PLCClient` 新增 `start_stage / await_stage_done` 两个公共方法，与旧 `send_action / wait_done / send_vision_result` 并存（spotting/scrape 继续走旧路径）。
- Phase B1 完成 develop 工位平移；`PLCClient` 新增 `await_stage_step` 公共方法，支持乒乓握手。
- Phase B2 完成 spotting 工位平移；`PLCClient` 新增 `write_string_array` 公共方法，支持 STRING 数组整体写入。
- Phase B3 完成 scrape 工位平移；`PLCClient` 新增 `confirm_stage` 公共方法，支持乒乓确认信号。
- Phase C 统一清理 `NODE_TYPES` 中的废弃键（`Action_ID / PC_Trigger / PLC_Busy / PLC_Done / PLC_Error / collection_step`）与旧 API（`send_action / wait_done / send_vision_result`）。

---

## 6. spotting 工位（v1.4 上样点样 / v1.4a 4 数组重构）

### 6.1 子步定义

| 子步号 | 键 | 中文标签 | 说明 |
|--------|-----|---------|------|
| 0 | `idle` | 空闲 | 未启动或已完成后的回归状态 |
| 10 | `clean` | 清洗 | 消费 `Sampling_clean_instructions[1..2]`(清洗数组) + `Sampling_clean_count`(循环次数) |
| 20 | `prepare` | 上样准备 | 消费 `Sampling_prep_instructions[1..2]`(上样准备数组) |
| 30 | `silica_plate` | 放硅胶板 | PLC 自治（机器人动作），无需参数 |
| 40 | `sample` | 上样(吸液) | 消费 `Sampling_X/Y_coordinate` + `Sampling_sample_instructions[1..2]`(上样数组) |
| 50 | `spot` | 点样 | 消费 `Sampling_dispense_instructions[1..2]`(点样数组)，完成后 Done=TRUE 回 0 |
| 90 | `error` | 故障 | 锁存故障态，等待 `_Reset` 清零 |

> 子步编号与 PLC 侧 `上样点样流程` 状态机对齐（10 间距）。
> 每个泵指令子步消费一个 1×2 STRING 数组，PLC 按顺序执行数组内 2 条指令。
> 清洗步（Step 10）循环执行 `Sampling_clean_count` 次（每次执行数组内全部 2 条指令）。

### 6.2 节点命名

PLC 变量前缀为 `Sampling`（实机 GVL 命名），上位机 stage name 为 `spotting`。

| 变量 | 类型 | 方向 | 说明 |
|------|------|------|------|
| `Sampling_Enable` | Boolean | PC→PLC | 启动上样点样状态机 |
| `Sampling_Step` | Int | PLC→PC | 当前子步号 |
| `Sampling_Done` | Boolean | PLC→PC | 完成锁存 |
| `Sampling_Error` | Boolean | PLC→PC | 故障锁存 |
| `Sampling_Reset` | Boolean | PC→PLC | 清 Error + Step |
| `Sampling_Busy` | Boolean | PLC→PC | 状态机忙 |
| `Sampling_clean_instructions` | ARRAY[1..2] OF STRING(128) | PC→PLC | 清洗数组 [内壁清洗, 外壁清洗]（Step 10 消费） |
| `Sampling_clean_count` | INT | PC→PLC | 清洗循环次数 |
| `Sampling_prep_instructions` | ARRAY[1..2] OF STRING(128) | PC→PLC | 上样准备数组 [吸取空气, 废液打出]（Step 20 消费） |
| `Sampling_X_coordinate` | INT | PC→PLC | 上样 X 坐标 |
| `Sampling_Y_coordinate` | INT | PC→PLC | 上样 Y 坐标 |
| `Sampling_sample_instructions` | ARRAY[1..2] OF STRING(128) | PC→PLC | 上样数组 [回抽样品, 废液排废]（Step 40 消费） |
| `Sampling_dispense_instructions` | ARRAY[1..2] OF STRING(128) | PC→PLC | 点样数组 [抽取空气, 打气点样]（Step 50 消费） |

> **设计决策（v1.4a）**：废弃旧 v1.4 的混合方案（1 标量 + 1 数组[1..4] + 2 标量），
> 统一为 4 个 1×2 STRING 数组，每个子步消费一个数组。优势：
> - PLC 侧处理逻辑统一：每个子步均为“读数组→顺序执行 2 条指令”
> - 上位机翻译语义清晰：4 个数组对应 4 个子步，命名即语义
> - 新增外壁清洗功能：clean_instructions[2] = 吸清洗液→废液口打出
>
> 已删除变量：`Sampling_bubble_instructions`(ARRAY[1..4])、`Sampling_aspirate_instructions`(STRING)、旧 `Sampling_dispense_instructions`(STRING)。

### 6.3 参数通道（v1.4a）

| YAML 字段 | PLC 变量 | 消费子步 |
|-----------|----------|----------|
| (隐含) | `Sampling_clean_instructions[1..2]` (PC 翻译) | 10 clean |
| `cleaning_count` | `Sampling_clean_count` | 10 clean |
| `sample_volume_ml` + `margin_volume_ml` | `Sampling_prep_instructions[1..2]` (PC 翻译) | 20 prepare |
| `source_x` | `Sampling_X_coordinate` | 40 sample |
| `source_y` | `Sampling_Y_coordinate` | 40 sample |
| `sample_volume_ml` | `Sampling_sample_instructions[1..2]` (PC 翻译) | 40 sample |
| `sample_volume_ml` | `Sampling_dispense_instructions[1..2]` (PC 翻译) | 50 spot |

### 6.4 上位机调用模板（v1.4a）

```python
# 翻译参数（4 个 1×2 数组 + 标量全部在 channels dict 内）
channels = spotting.translate_params(params)
# channels 包含：
#   Sampling_clean_instructions: [内壁清洗, 外壁清洗]  (ARRAY[1..2])
#   Sampling_clean_count: 3
#   Sampling_prep_instructions: [吸取空气, 废液打出]   (ARRAY[1..2])
#   Sampling_X_coordinate: 1, Sampling_Y_coordinate: 1
#   Sampling_sample_instructions: [回抽样品, 废液排废]  (ARRAY[1..2])
#   Sampling_dispense_instructions: [抽取空气, 打气点样] (ARRAY[1..2])

# 启动（write_variable 自动检测 NODE_ARRAYS 声明，数组变量走 _write_array 路径）
await plc.start_stage("Sampling", channels)

# 等待完成
await plc.await_stage_done("Sampling", on_step_change=..., timeout=...)

# 收尾（await_stage_done 内部已写 Enable=FALSE）
```

### 6.5 故障恢复

```python
await plc.write_variable("Sampling_Reset", True)
await asyncio.sleep(0.1)
await plc.write_variable("Sampling_Reset", False)
```

---

## 7. develop 工位（v1.3 多通道展开）

### 7.1 子步定义（v1.3：删除 Step 35，Step 40 语义变更）

| 子步号 | 键 | 中文标签 | 说明 |
|--------|-----|---------|------|
| 0 | `idle` | 空闲 | 未启动或已完成后的回归状态 |
| 10 | `rinse` | 润洗/清洗 | 互斥：`Expand_Mode_Flag=0` 走缸模式，`=1` 走管路模式 |
| 20 | `up_liquid` | 上液 | 展开剂加入展缸 |
| 30 | `silica_plate` | 放硅胶板 | 放硅胶板执行 |
| 40 | `deliver` | 交付至展开态 | **v1.3 关键变更**：prep 完成，立即 Done=TRUE + Step 回 0 + 序列器释放，支持下一缸 prep |
| 90 | `error` | 故障 | 锁存故障态，等待 `_Reset` 清零 |

> **v1.2→v1.3 变更**：删除 Step 35（乒乓握手），Step 40 语义从"展开及排液"变为"交付至展开态"。排液由独立 per-tank 变量 Tank_Drain_Enable[i] 触发。

### 7.2 节点命名

PLC 变量前缀为 `Expand`（实机 GVL 命名规范），上位机 stage name 为 `develop`。

| 变量 | 类型 | 方向 | 说明 |
|------|------|------|------|
| `Expand_Enable` | Boolean | PC→PLC | 启动准备序列器 |
| `Expand_Step` | Int | PLC→PC | 当前子步号 |
| `Expand_Done` | Boolean | PLC→PC | **v1.3**：prep 完成（非整流程完成） |
| `Expand_Error` | Boolean | PLC→PC | 故障锁存 |
| `Expand_Reset` | Boolean | PC→PLC | 清 Error + Step |
| `Expand_Busy` | Boolean | PLC→PC | 序列器忙 |
| `Expand_Target_Tank` | Int | PC→PLC | **v1.3 新增**：目标缸号(1-8) |
| `Expand_Mode_Flag` | Int | PC→PLC | 0=缸模式润洗 / 1=管路模式润洗 |
| `Expand_forward_instructions` | STRING(128) | PC→PLC | 注射泵转发指令 |
| `Expand_Group` | Int | PLC→PC | PLC 从 Target_Tank 自动推导，上位机不再写入 |
| `Expand_Number` | Int | PLC→PC | PLC 从 Target_Tank 自动推导，上位机不再写入 |
| ~~`Expand_Confirm`~~ | ~~Boolean~~ | ~~PC→PLC~~ | **v1.3 废弃**，排液由 Tank_Drain_Enable[i] 替代 |

### 7.3 多通道展开变量（v1.3 新增）

| 变量 | 类型 | 方向 | 说明 |
|------|------|------|------|
| `Tank_State` | ARRAY[1..8] OF INT | PLC→PC | 每缸状态：0=Idle, 10=Prepping, 40=Developing, 50=Draining, 55=BlowAir, 60=CylinderRetract, 65=RobotPickup, 99=Done, 90=Error |
| `Tank_SampleID` | ARRAY[1..8] OF DINT | PLC→PC | 调试用：每缸绑定的样品 ID |
| `Tank_Drain_Enable` | ARRAY[1..8] OF BOOL | PC→PLC | per-tank 排液触发（8 缸可全部并行，无需组级互斥） |
| `Tank_Drain_Done` | ARRAY[1..8] OF BOOL | PLC→PC | per-tank 排液完成锁存 |

> **OPC UA 实现决策**：数组变量采用真数组节点（非 8 个独立标量），与 PLC ST `ARRAY[1..8]` 语义一致。
> 上位机通过 PLCClient.read_tank_array / write_tank_element 封装数组索引访问。
>
> **排液并发语义**：8 缸排液 per-tank 独立，可同时进入排液流程——PLC 侧**不**实现任何组级互斥逻辑。排液为 4 阶段硬件序列：`50 (Draining)` → `55 (BlowAir)` → `60 (CylinderRetract)` → `65 (RobotPickup)` → `99 (Done)`，其中 55/60/65 为 PLC 内部自动转换子状态，PC 只关心 `Tank_Drain_Done[i]=TRUE`（state 99）。机器人取板为串行资源（`RobotRequested` 共享锁），多缸同时到达 65 时按 `FOR i=1 TO 8` 扫描顺序排队。硬件依据：每缸有独立排液电磁阀、吹气电磁阀、气缸；真空泵全局共享（anyDraining 引用计数控制）；真空废液瓶缓冲容器供稳态负压，多缸同时排液不会互抢负压。上位机 `DevelopStage` 的 `_group_locks[group]` 仅作用于 prep 阶段（同组共享注射泵），排液阶段不持锁。

### 7.4 参数通道（v1.3）

| YAML 字段 | PLC 变量 | 消费子步 |
|-----------|----------|----------|
| `rinse_mode` | `Expand_Mode_Flag`（0=缸/1=管路） | 10 rinse |
| `target_tank` | `Expand_Target_Tank` | 0 idle（PLC 自动推导 Group/Number） |
| `solvent_volume_ml` + `solvent_ratio_1~5` | `Expand_forward_instructions`（翻译后） | 20 up_liquid |
| `develop_duration_min` | 上位机本地定时 | 展开等待阶段 |

### 7.5 上位机调用模板（v1.3 四阶段流程）

```python
# Phase 1: 分配展缸 + 启动 prep
if resource_manager:
    target_tank = await resource_manager.allocate(sample_id)
await plc.start_stage("Expand", channels)  # channels 含 Expand_Target_Tank
await plc.await_stage_done("Expand", ...)  # prep 完成，Expand_Done=TRUE

# Phase 2: 等待展开时间
await asyncio.sleep(develop_duration_min * 60)

# Phase 3: 触发排液 + 等待完成
await plc.trigger_drain(target_tank)
await plc.await_drain_done(target_tank, timeout=300)

# Phase 4: 释放展缸
if resource_manager:
    await resource_manager.release(target_tank)
else:
    await plc.release_tank(target_tank)
```

### 7.6 Expand_Done 语义变更对比

| 版本 | Expand_Done=TRUE 含义 | 序列器行为 |
|------|----------------------|-----------|
| v1.2 | 整流程完成（含展开+排液） | 序列器占用至 Done |
| v1.3 | prep 完成（目标缸进入 Developing 态） | 序列器立即释放，可接受下一缸 prep |

### 7.7 时序图（v1.3）

```
             PC 写参数                                 PC trigger_drain      PC release_tank
             ┆ (Target_Tank, ...)                       ┆                    ┆
             ▼                                          ▼                    ▼
Enable  ──┬────────────────────────────────────────────────────────────────────────┬──
           │              Done=TRUE             sleep               Drain_Done[i]=TRUE
Step   0 ─┤   10   20   30   40 → 0                                                              │
           │                                  ↑ Tank_State[i]=40                     Tank_State[i]=0
Tank[i]  ────────────────── 10 ───────────── 40 ─────── 50 ──── 99 ──────────────── 0
           Prepping                     Developing  Draining  Done
```

---

## 8. scrape 工位（v1.6 拍照刮板 + PhotoMode 路由）

### 8.1 子步定义

| 子步号 | 键 | 中文标签 | 说明 |
|--------|-----|---------|------|
| 0 | `idle` | 空闲 | 未启动或已完成后的回归状态 |
| 10 | `init` | 初始化 | 气路/机器人复位；完成后按 `scrape_PhotoMode` 路由：0→Step 20（完整刮板），1→Step 15（仅before-photo） |
| 15 | `before_photo` | 点样后拍照(乒乓) | **v1.6 新增**：PLC 将硅胶板送至拍照位后停在此步，置 `scrape_WaitConfirm=TRUE`，轮询 `scrape_Confirm` 等待 PC 侧拍照+确认；Confirm 后归位+Done，`WaitConfirm` 清零 |
| 20 | `photo` | 展开后拍照(乒乓) | **乒乓等待步**：PLC 将硅胶板送至拍照位后停在此步，置 `scrape_WaitConfirm=TRUE`，轮询 `scrape_Confirm` 等待 PC 侧拍照+视觉分析+G-code下发+确认；Confirm 后 `WaitConfirm` 清零，继续 Step 30 |
| 30 | `scrape` | 刮取 | 消费 `scrape_gcode_instructions`(G-code 指令)，执行刮板运动 |
| 40 | `collect` | 机器人取粉末 | 机器人夹取粉末收集器，完成后 Done=TRUE 回 0 |
| 90 | `error` | 故障 | 锁存故障态，等待 `_Reset` 清零 |

> **设计决策**：scrape 采用单 FSM + 乒乓握手方案（非双 FSM 拆分）。原因：拍照和刮板在硬件层面是不可分割的串行流程（同一台机器人 + 同一块硅胶板），拆分为 vision/motion 两个 FSM 没有硬件解耦收益，反而增加协调复杂度。Step 20 乒乓握手机制允许 PC 侧在拍照完成后插入视觉分析+G-code 生成逻辑，PLC 侧等待确认后继续自治执行。

> **v1.5.1 拍照触发权修订**：Step 15/20 到达 = 板已到位信号。拍照触发由 PC 侧 CameraService 负责（PLC 仅执行送板动作），不再由 PLC 触发相机。PC 侧在 Step 15/20 后触发拍照 → 视觉分析 → band 选择 → G-code 生成 → 下发 → Confirm。
>
> **v1.6 PhotoMode 路由**：Step 10 初始化完成后，根据 `scrape_PhotoMode` 选择后续路径。PhotoMode=0（默认）走完整刮板流程（Step 20→30→40），PhotoMode=1 走仅拍照流程（Step 15→归位+Done）。PhotoMode 在 Step 10 路由决策完成后消费归零（不在 Step 0 归零）。
>
> **v1.6 Phase A 门控**：Step 15/20 的 Confirm 上升沿检测增加 `phaseA_done` 门控标志，确保 PLC 完成送板后（Phase A）才检测 Confirm 信号，防止 PC 提前写 Confirm 导致板未到位就推进。

> **乒乓握手与 develop v1.2 的对比**：develop v1.2 的 Step 35 乒乓（`Expand_Confirm`）已在 v1.3 中废弃，改为 per-tank 排液；scrape v1.5 的 Step 20 乒乓（`scrape_Confirm`）是永久机制——PLC 无法自行完成视觉分析，必须等 PC 侧介入。

### 8.2 节点命名

PLC 变量前缀为 `scrape`（与上位机 stage name 同名，无需映射）。

| 变量 | 类型 | 方向 | 说明 |
|------|------|------|------|
| `scrape_Enable` | Boolean | PC→PLC | 启动拍照刮板状态机 |
| `scrape_Step` | Int | PLC→PC | 当前子步号 |
| `scrape_Done` | Boolean | PLC→PC | 完成锁存 |
| `scrape_Error` | Boolean | PLC→PC | 故障锁存 |
| `scrape_Reset` | Boolean | PC→PLC | 清 Error + Step |
| `scrape_Busy` | Boolean | PLC→PC | 状态机忙 |
| `scrape_Confirm` | Boolean | PC→PLC | **v1.5 乒乓确认信号**：Step 15/20 时 PLC 轮询此变量；PC 写 TRUE 后 PLC 继续（Step 15→归位Done / Step 20→Step 30）；PLC 消费后自动清零 |
| `scrape_WaitConfirm` | Boolean | PLC→PC | **v1.7 显式就绪信号**：PLC 进入 confirm 轮询前置 TRUE，消费 Confirm 后清零；PC 侧 `await_stage_step` 返回条件为 `Step==target AND WaitConfirm==TRUE`；Reset/Enable下降沿同步清零 |
| `scrape_gcode_instructions` | STRING(128) | PC→PLC | G-code 动态生成指令（Step 30 消费） |
| `scrape_PhotoMode` | Int | PC→PLC | **v1.6 拍照模式选择**：0=完整刮板模式(默认, Step 10→20→30→40)，1=仅before-photo模式(Step 10→15→归位Done) |

> **`scrape_Confirm` 生命周期**：PC 在 Confirm=TRUE 后 PLC 检测到上升沿、消费后自动清零。与 develop v1.2 的 `Expand_Confirm` 行为一致。

### 8.3 参数通道（v1.5）

| 来源 | PLC 变量 | 消费子步 |
|------|----------|----------|
| VisionService 分析结果 + 用户 band 选择 → GCodeGenerator.generate() | `scrape_gcode_instructions`（动态生成） | 30 scrape |

> **v1.5 关键变更**：废弃旧的 `gcode_name` 预置方式。G-code 由 PC 侧视觉分析后动态生成并写入 `scrape_gcode_instructions`，不再依赖 PLC 侧的文件名查找机制。

### 8.4 上位机调用模板（v1.6）

```python
# ── 路径 A：完整刮板模式（PhotoMode=0，默认） ──

# Phase 1: 启动 scrape FSM（PhotoMode=0 默认，无需显式写入）
await plc.start_stage("scrape")

# Phase 2: 等待 Step 到达 photo（板已到位，乒乓等待点）
await plc.await_stage_step("scrape", STEP["photo"], on_step_change=..., timeout=600)

# Phase 2.5: PC 侧触发拍照
image_path = await camera.capture(sample_id, save_dir)

# Phase 3: PC 侧视觉分析 + 分支决策
ar = await vision.analyze_full(sample_id, before_path, after_path)
if ar is None:
    # 未配视觉 → 写入安全占位 G-code 后 Confirm
    await plc.send_recipe_params({"scrape_gcode_instructions": "G0 Z10.0\nM2\n"})
    await plc.confirm_stage("scrape")
elif ar.ok:
    # 视觉成功 → 等待 Vision Tab band 选择 → 生成 G-code → 下发 + Confirm
    gcode_text = await wait_for_band_selection_and_generate_gcode()
    if gcode_text:
        await plc.send_recipe_params({"scrape_gcode_instructions": gcode_text})
    await plc.confirm_stage("scrape")
else:
    # 视觉失败 → 人工确认 → 写安全占位 G-code + Confirm 或中止
    should_continue = await confirm_or_abort()
    if should_continue:
        await plc.send_recipe_params({"scrape_gcode_instructions": "G0 Z10.0\nM2\n"})
        await plc.confirm_stage("scrape")
    else:
        await plc.write_variable("scrape_Enable", False)
        raise RuntimeError("视觉失败且人工选择终止")

# Phase 4: 等待整个流程完成（Step 30 scrape → Step 40 collect → Done）
await plc.await_stage_done("scrape", on_step_change=..., timeout=600)

# ── 路径 B：仅 before-photo 模式（PhotoMode=1） ──

# Phase 1: 写入 PhotoMode=1 后启动 scrape FSM
await plc.start_stage("scrape", {"scrape_PhotoMode": 1})

# Phase 2: 等待 Step 到达 before_photo（板已到位，乒乓等待点）
await plc.await_stage_step("scrape", STEP["before_photo"], on_step_change=..., timeout=600)

# Phase 3: PC 侧触发拍照 + Confirm
image_path = await camera.capture(sample_id, save_dir, filename="before.jpg")
await plc.confirm_stage("scrape")

# Phase 4: 等待完成（Step 15 归位 → Done）
await plc.await_stage_done("scrape", on_step_change=..., timeout=600)
```

### 8.5 时序图（v1.6）

**路径 A：完整刮板模式（PhotoMode=0）**

```
             PC start_stage          PC camera.capture          PC confirm_stage                     PC (Done→Enable=FALSE)
             ┆                         ┆                         ┆                                    ┆
             ▼                         ▼                         ▼                                    ▼
Enable  ──┬──────────────────────────────────────────────────────────────────────────────────────────┬──
           │                                                                      │
Step   0 ─┤   10   20(等待Confirm)   30   40                                    ┌─ 0
           │       ↑                  │    │                                      │
Confirm ──────────────────────────────┬──────┘                                     │
                                       TRUE                                        │
Done   ───────────────────────────────────────────────────┌─────────────────────────┴──
                                                           │（锁存至 _Enable=FALSE）
```

**路径 B：仅 before-photo 模式（PhotoMode=1）**

```
             PC start_stage(PhotoMode=1)   PC camera.capture   PC confirm_stage      PC (Done→Enable=FALSE)
             ┆                              ┆                   ┆                      ┆
             ▼                              ▼                   ▼                      ▼
Enable  ──┬────────────────────────────────────────────────────────────────────────────────┬──
           │                                                                │
Step   0 ─┤   10   15(等待Confirm)   0+Done                              ┌─ 0
           │       ↑                    │                                  │
Confirm ───────────────────────────────┬──────────────────────────────────┘
                                       TRUE
Done   ───────────────────────────────────────────────┌─────────────────────┴──
                                                       │（锁存至 _Enable=FALSE）
```

> Step 15/20 期间 PLC 轮询 `scrape_Confirm`（带 Phase A 门控：仅送板完成后检测）；PC 侧在 Step 15/20 到达后触发相机拍照（CameraService），完成视觉分析+G-code 下发后写 `scrape_Confirm=TRUE`，PLC 检测到上升沿后继续后续步骤。PhotoMode=1 时 Step 15 Confirm 后直接归位+Done；PhotoMode=0 时 Step 20 Confirm 后继续 Step 30。

### 8.5 双帧视觉集成说明（v1.6）

TLC 视觉分析采用**双帧模式**：通过比较点样后（before）和展开后（after）两帧图像的差分映射检测 band。

#### 数据流

```
BeforePhotoStage(PhotoMode=1)            ScrapeStage(PhotoMode=0)
  Step 10→15(乒乓)                         Step 10→20(乒乓)
      │                                         │
      ▼                                         ▼
  CameraService.capture(                    CameraService.capture(
      filename="before.jpg")                     filename="after.jpg")
      │                                         │
      ▼                                         ▼
  SampleStore.set_before_path()              _resolve_image_paths()
                                               ├─ after_path ← 拍照结果
                                               └─ before_path ← SampleStore.get_before_path()
                                                    (BeforePhotoStage 写入)
                                                    │
                                                    ▼
                                             VisionService.analyze_full(
                                                 before_path, after_path)
                                                    │
                                                    ▼
                                             差分映射 → BandInfo[] → G-code
```

#### before_path 传递链

| 阶段 | 写入者 | 读取者 | 传递路径 |
|------|--------|--------|----------|
| BeforePhotoStage | `SampleStore.set_before_path()` | ScrapeStage | SampleStore → `_resolve_image_paths()` |
| ScrapeStage | `CameraService.capture()` → after_path | VisionService | 直接参数传递 |

#### 异常降级

| 场景 | 行为 |
|------|------|
| before_photo 阶段 disabled | `_resolve_image_paths()` 找不到 before.jpg → `before_path=None` |
| BeforePhotoStage 拍照失败 | `SampleStore` 无 before_path → `before_path=None` |
| `before_path=None` | `VisionService.analyze_full()` 返回 `ok=False` → ScrapeStage 走视觉失败分支（人工确认 → 安全占位 G-code + Confirm 或中止） |

> **设计决策**：双帧模式为唯一分析模式，不提供单帧回退。原因：TLC 差分映射依赖 before/after 图像对，`process_pair()` 内部做 `score = after_score - before_score`。缺失 before 图像时差分无法计算，强制走视觉失败分支是更安全的降级策略。

### 8.6 before_photo 工位说明（v1.6，复用 scrape FSM）

`before_photo` 不是独立的 PLC FSM，而是**复用 scrape FSM 的 PhotoMode=1 路径**。上位机 `BeforePhotoStage` 通过写入 `scrape_PhotoMode=1` 后启动 scrape 状态机，PLC 在 Step 10 初始化后路由到 Step 15（before-photo 乒乓等待），PC 侧拍照后 Confirm，PLC 归位+Done。

#### 工位映射关系

| 上位机 Stage 名称 | PLC 变量前缀 | FSM | 路由条件 |
|------------------|-------------|-----|----------|
| `scrape` | `scrape` | scrape FSM | `scrape_PhotoMode=0`（默认）→ Step 20 |
| `before_photo` | `scrape` | 同一 scrape FSM | `scrape_PhotoMode=1` → Step 15 |

> **设计决策**：before_photo 不独立创建 FSM，原因：
> 1. 硬件层面，点样后拍照和展开后拍照使用同一台机器人+同一拍照位，无硬件解耦收益
> 2. 共享 FSM 通过 PhotoMode 路由，避免双 FSM 的状态协调复杂度
> 3. 共享 `_scrape_lock` 确保两阶段对拍照刮板工位硬件的串行化访问

#### before_photo 子步轨迹

```
Step 0 (idle) → Step 10 (init) → Step 15 (before-photo 乒乓) → Step 0 + Done=TRUE
```

| 子步 | 说明 | PC 侧介入 |
|------|------|----------|
| 0 | idle：等待 Enable | 无 |
| 10 | 初始化：PhotoMode 路由到 Step 15 | 无 |
| 15 | before-photo 乒乓等待：板已到位，等 PC Confirm | await_stage_step(15) → 拍照 → Confirm |
| 0+Done | 归位完成 | 写 Enable=FALSE 清 Done |

#### 上位机调用模板

```python
# BeforePhotoStage(PhotoMode=1) 调用序列

# Phase 1: 写 PhotoMode=1 + 启动 scrape FSM
await plc.send_recipe_params({"scrape_PhotoMode": 1})
await plc.start_stage("scrape")

# Phase 2: 等待 Step 15（板已到位，乒乓等待点）
await plc.await_stage_step("scrape", 15, on_step_change=..., timeout=120)

# Phase 3: PC 侧拍照（保存为 before.jpg）+ Confirm
image_path = await camera.capture(sample_id, save_dir, filename="before.jpg")
sample_store.set_before_path(sample_id, image_path)  # 供后续 ScrapeStage 读取
await plc.confirm_stage("scrape")

# Phase 4: 等待完成（Step 15 归位 → Done）
await plc.await_stage_done("scrape", on_step_change=..., timeout=120)
```

#### 资源互斥

`BeforePhotoStage` 与 `ScrapeStage` 共享 `_scrape_lock`（类级 `asyncio.Lock` 同一实例），确保两个阶段对拍照刮板工位硬件的访问串行化。锁绑定在 `stages/__init__.py`：

```python
BeforePhotoStage._scrape_lock = ScrapeStage._scrape_lock
```

#### before_path 传递链

```
BeforePhotoStage              ScrapeStage
  ↓ 拍照                        ↓ 拍照
  before.jpg                    after.jpg
  ↓ 存储                         ↓ 读取
  SampleStore.set_before_path()  SampleStore.get_before_path()
                                 ↓ 传入
                                 VisionService.analyze_full(before_path, after_path)
```

#### 异常降级

| 场景 | 行为 |
|------|------|
| before_photo 阶段 disabled | ScrapeStage `_resolve_image_paths()` 找不到 before.jpg → `before_path=None` |
| BeforePhotoStage 拍照失败 | 异常 re-raise → PLC 清理（条件化 Enable=False） → 样品终止 |
| `before_path=None` | `VisionService.analyze_full()` 返回 `ok=False` → ScrapeStage 走视觉失败分支 |

---

## 9. E-Stop 安全停车规约（v1.7）

### 9.1 触发链路

```
PLC_EStop 上升沿
  → PLC 侧：各工位 ST 检测 IF PLC_EStop THEN → 紧急停车分支
  → PC  侧：心跳检测上升沿 → plc._on_estop() → broadcast_estop(scheduler)
       → scheduler.estop_activate() → 全部 active task.cancel()
       → StageExecutor.execute() CancelledError → STAGE_DONE(status=ESTOP)
```

### 9.2 PLC 侧各工位最小停车动作清单

| 工位 | PLC 侧必须执行的动作 | 说明 |
|------|------------------------------|------|
| spotting (Sampling) | `pumpCmd_execute := FALSE`；三通阀回安全位 | 停注射泵、防泄漏 |
| scrape | `axisCmd_stop := TRUE`；相机触发关闭 | 停 CNC 轴运动、关相机 |
| develop (Expand) | `IF Tank_State[i] IN (10,40,50,55,60,65) THEN Tank_State[i] := 90`；关闭所有排液阀/吹气阀；关真空泵；清除机器人取板请求 | prep/develop/排液/取板中的缸全部标记 Error |
| collect | `pumpCmd_execute := FALSE` | 停注射泵 |

> 全工位公共动作：`<Stage>_Enable := FALSE`；`<Stage>_Step := 0`；`<Stage>_Busy := FALSE`；`<Stage>_Done := FALSE`。

### 9.3 Tank_State 急停标记规则

| 急停前 Tank_State[i] | 急停后 PLC 侧标记 | PC 侧 ResourceManager |
|---------------------------|--------------------|---------------------|
| 10 (Prepping) | 90 (Error) | NEEDS_DRAIN (91) |
| 40 (Developing) | 90 (Error) | NEEDS_DRAIN (91) |
| 50 (Draining) | 90 (Error) | NEEDS_DRAIN (91) |
| 55 (BlowAir) | 90 (Error) | NEEDS_DRAIN (91) |
| 60 (CylinderRetract) | 90 (Error) | NEEDS_DRAIN (91) |
| 65 (RobotPickup) | 90 (Error) | NEEDS_DRAIN (91) |
| 0 (Idle) / 99 (Done) | 保持不变 | 保持不变 |

> PC 侧 `ResourceManager` 在 E-Stop 路径下通过 `release(mark_needs_drain=True)` 将占用缸标记为
> `NEEDS_DRAIN=91`，不写 PLC `Tank_State`（PLC 侧已标记 90）。Recovery 向导中用户强制排液后，
> `manual_release()` 读 PLC `Tank_State[i]==0`（确认已排完）后方可释放。

### 9.4 响应时延要求

- PLC ST 急停分支必须在 **≤ 1 个 PLC 扫描周期** 内完成全部停车动作
- PC 侧心跳检测周期：100 ms（PLCClient heartbeat_interval）
- 从 PLC_EStop 上升沿到 PC 侧全部 task cancel：≤ 200 ms（心跳 100ms + 广播延迟）

### 9.5 Recovery 流程

```
1. PC 侧 broadcast_estop → 所有 Task CancelledError → NEEDS_DRAIN 标记
2. Recovery UI 自动弹出：
   a) 展缸强制排液（NEEDS_DRAIN 缸→ PLC trigger_drain → await_drain_done → manual_release）
   b) 工位 Reset 脉冲（清除 PLC Error 锁存）
   c) 现场安全确认（人工勾选）
3. 解除急停：reset_estop(scheduler) → estop_active=False → 队列恢复调度
```

---

## 10. 版本历史

- v1.7（2026-05-18）：E-Stop Phase 0 体系落地。
  - 新增§9 E-Stop 安全停车规约：触发链路、PLC 侧各工位最小停车动作、Tank_State 急停标记、响应时延、Recovery 流程。
  - PC 侧 `core/estop.py` + `broadcast_estop` + `is_estop_active` 公共 API。
  - `ResourceManager` 新增 `TankStatus.NEEDS_DRAIN=91` + `release(mark_needs_drain=True)` + `manual_release(tank_id)` + `needs_drain_tanks()`。
  - `StageStateRegistry` 新增 `state="estop"`，区分 ESTOP/CANCELLED/ERROR 三种终止状态。
  - `develop.py` finally 块集成 `is_estop_active()` 路径，急停路径下调用 `release(mark_needs_drain=True)`。
  - Recovery UI（`ui/sections/recovery.py`）极简向导：展缸强制排液 + 工位 Reset 脉冲 + 现场安全确认。
  - app.py 急停自动切换 Recovery Tab；Mock Server 新增 `mark_tank <N> needs_drain` 控制台命令。
- v1.6（2026-05-16）：scrape 工位 PhotoMode 路由 + Step 15 before-photo + 双帧视觉集成。
  - 新增 `scrape_PhotoMode`(INT) 变量：0=完整刮板模式(默认)，1=仅before-photo模式。
  - 新增 Step 15 before-photo 乒乓等待子步：PLC 送板后停在 Step 15，等待 PC 侧拍照+Confirm 后归位+Done。
  - Step 10 初始化后按 PhotoMode 路由：0→Step 20，1→Step 15。
  - 双帧视觉集成：VisionService.analyze_full() 接受 Optional[Path] before_path，
    before_path=None 时返回 ok=False，ScrapeStage 走视觉失败分支。
    BeforePhotoStage 通过 SampleStore.set_before_path() 写入 before 图像路径，
    ScrapeStage 通过 _resolve_image_paths() 从 SampleStore 动态获取。
  - Phase A 完成门控：Step 15/20 的 Confirm 上升沿检测增加 `phaseA_done` 标志，确保送板完成后才检测 Confirm。
  - 消费型变量归零位置修正：`scrape_PhotoMode` 不在 Step 0 无条件归零（否则 PC 写入值被每周期覆盖），改为 Step 10 路由决策完成后消费归零。
  - 上位机 `ScrapeStage` 视觉跳过分支补写安全占位 G-code（`G0 Z10.0\nM2\n`），避免 PLC Step 30 空指令故障。
  - 上位机 `SCRAPE_SUB_STEPS` 新增 Step 15 + 引入 `STEP` 常量。
  - 上位机 `NODE_TYPES` + Mock Server 注册 `scrape_PhotoMode` 变量。
  - 上位机 Mock Server `_run_sequence` 改为按索引迭代，支持 step_hook 动态修改 trace。
- v1.5.1（2026-05-16）：拍照触发权修订。
  - Step 20 语义从"PLC 完成拍照后停在此步"改为"PLC 将硅胶板送至拍照位后停在此步"。拍照触发由 PC 侧 CameraService 负责。
  - 新增 `core/camera_service.py`：CameraService 抽象层（MockCameraService / DahengCameraService）。
  - ScrapeStage 新增 Phase 2.5（`_capture_photo()`）：Step 20 到达后触发拍照，动态更新 after_path。
  - `core/config.py` 新增 CameraCfg 配置（mock / test_image）。
  - `core/sample_store.py` 新增 save_capture / get_debug_dir 方法，list_samples() 排除 debug 目录。
  - camera 参数通过 main.py → Scheduler → RecipeTask/SampleTask → ScrapeStage 全链路注入。
- v1.5（2026-05-15）：scrape 工位平移 Phase B3。
  - scrape（拍照刮板）工位平移至电平范式，PLC 变量前缀 `scrape`（与上位机 stage name 同名）。
  - 单 FSM + 乒乓握手方案：Step 20（拍照完成）为等待确认子步，PLC 轮询 `scrape_Confirm`；PC 侧完成视觉分析+G-code 下发后写 Confirm=TRUE。
  - 新增 `PLCClient.confirm_stage(stage)` 公共方法，写 `<stage>_Confirm=TRUE`。
  - 新增业务参数 `scrape_gcode_instructions`（STRING(128)，G-code 动态生成指令）。
  - 删除 `Vision_Done / Vision_Result_X / Vision_Result_Y` 变量（scrape 电平范式替代旧 Vision 乒乓通道）。
  - 废弃 `PLCClient.send_vision_result()` 方法（改为抛 RuntimeError，Phase C 删除）。
  - 删除 scrape 相关 ActionID（1003 刮取 / 4001 系统复位 / 4002 初始化 / 1030 送版入拍照位 / 4010 异常回复）。
  - 子步编号与 PLC 侧状态机对齐：`{0, 10, 20, 30, 40, 90}`。
- v1.4（2026-05-15）：spotting 工位平移 Phase B2。
  - spotting（上样点样）工位平移至电平范式，PLC 变量前缀 `Sampling`。
  - STRING 数组参数：`Sampling_bubble_instructions` 为 `ARRAY[1..16] OF STRING(128)`，配合 `Sampling_bubble_count` 管理变长气泡序列指令。
  - 新增 `PLCClient.write_string_array(name, values)` 公共方法，整体写入 STRING 数组。
  - 清洗参数可配：`Sampling_clean_instructions`(STRING) + `Sampling_clean_count`(INT)。
  - PC 侧翻译策略：清洗/气泡/吸液/点样指令均由 pump_translator / sample_pump_translator 翻译后写入 PLC 变量。
  - 子步编号与 PLC 侧 `上样点样流程` 状态机对齐：`{0, 10, 20, 30, 40, 50, 90}`。
- v1.3（2026-05-13）：多通道展开架构改造 Phase 1。
  - Expand_Done 语义变更：从"整流程完成"变为"prep 完成"，序列器在 Step 40 交付后立即释放。
  - 删除 Step 35 乒乓握手：Expand_Confirm 废弃，排液由 per-tank Tank_Drain_Enable[i] / Tank_Drain_Done[i] 替代。
  - 新增 Expand_Target_Tank：PC 写入目标缸号(1-8)，PLC 自动推导 Group/Number。
  - 新增数组节点：Tank_State / Tank_SampleID / Tank_Drain_Enable / Tank_Drain_Done（真数组）。
  - DevelopStage 四阶段流程：allocate + prep → sleep(develop) → drain → release。
  - 新增 ResourceManager：展缸分配/释放/状态同步/绑定管理。
  - 参数精简：删除 expand_group / expand_number，新增 target_tank / develop_duration_min。
- v1.2（2026-05-12）：Phase B1 修订。
  - develop（展开）工位平移至电平范式，PLC 变量前缀 `Expand`。
  - 乒乓握手机制：Step=35 等待 `Expand_Confirm` 信号，上位机通过 `await_stage_step` + 写 Confirm 实现。
  - 新增 `PLCClient.await_stage_step(stage, target_step)` 公共方法。
  - develop 业务参数：`Expand_Mode_Flag / Expand_Group / Expand_Group_clean / Expand_Number / Expand_forward_instructions_clean / Expand_Group_UP / Expand_Number_UP / Expand_forward_instructions_UP`。
- v1.1（2026-05-11）：Phase A.1 修订。
  - 删除 `Recipe_Param_A..F / I1..I4 / Recipe_Gcode_Name / Recipe_Mode_Flag` 通用通道抽象，参数变量改业务直名（collect 用 `collect_forward_instructions / collect_count`），消除 PLC 侧二次赋值。
  - 每工位新增 `<Stage>_Busy`，由各工位 ST 自派生；全局 `PLC_Busy` 改由独立 BusyAggregator PRG 聚合写入，落实"写者唯一原则"，杜绝多 PRG 互相覆盖。
  - 修正历史命名错误：`Gcode_Name` 实为注射泵转发指令（非 G 代码），STRING(128)。
- v1.0（2026-05-10）：collect 范围冻结。4 读写 + 1 复位 + 全局急停；子步 `{0,10,20,30,90}`；参数仅 `syringe_forward_cmd / liquid_repeat_count`。
