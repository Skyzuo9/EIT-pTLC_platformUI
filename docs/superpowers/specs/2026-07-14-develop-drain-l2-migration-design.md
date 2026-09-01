# 展缸排液 L2 化迁移 + 原位干燥 · 设计 spec

日期: 2026-07-14
状态: 已实施 (plan 2026-07-14-develop-drain-l2-migration, 主机+PLC 全落地, 离线守卫 8/9 绿 — 唯一失败为他人在途 ptlc_full.yaml 的既有问题与本迁移无关; 上机验证项见 §7 待跑)
分支: codex/ui-upper-next
相关: docs/superpowers/specs/2026-07-13-waterlevel-auto-drain-design.md · docs/液位自动排液_P0实验手册_20260713.md

## 1. 背景与问题

液位双阈值自动排液 (spec 2026-07-13) 已把"何时排液"闭环到检测算法; 本 spec 处理它的下游:
排液序列本身与取板物流的关系。旧排液程序 (`40_Man/Develop_TankDrain`) 把两类性质不同的事
捆在一个 code 50 黑盒里:

- **化学关键、时间关键**: 断液 (真空抽液 + 吹净砂芯残液)。决定前沿最终停位, 直接决定 Rf 一致性;
  只依赖 PLC 自己的阀/泵, 不依赖机器人。
- **纯物流、时间不定**: 开盖、等机器人取板。多缸并发下, 排液完成到机器人到手的间隔是
  无界随机变量 (取决于邻缸刮板进度)。

现状 `Done(99) ≡ 盖已开`, 即"排液完成"被定义成"板暴露在机箱环境里等机器人"。单样本串行下无害;
多缸并发下, 板的等待环境 (暴露时长、邻缸排液蒸气串扰) 与干湿状态成为不受控变量:
前沿位置虽被排液冻结, **湿板上的斑点在等待期持续横向扩散**, 等待时长方差直接转化为斑点质量方差。
另外今天板从出缸到拍照没有任何干燥环节, 纯靠转运/等待自然晾干 —— 送到拍照工位的板干湿程度
本来就是不受控变量, 也是 PALLAS 视觉输入的隐藏噪声源。

## 2. 现状盘点 (已核实到 PLC 代码级)

### 2.1 旧排液程序 `40_Man/Develop_TankDrain/A50_Expand_liquid_discharge_排液`

每缸独立 FSM, 支持 8 缸并行:

1. **Phase A — Draining (Tank_State=50)**: 开本缸排液电磁阀 + 拿大真空泵票
   (泵全局共享, 引用计数 `大真空泵站位[i]`)。完成判据 = `DrainTimer` 被**废液检测传感器门控**:
   传感器持续为真累计满 `DrainDuration` 才进下一阶段。
2. **Phase B — BlowAir (55)**: 开吹气阀, 排液阀保持开 (气路经废液线贯通排出, 不憋压);
   **真空票在此刻撤销** (`大真空泵站位[i]:=FALSE`) —— 吹气是被动排出。固定 30s
   (`BlowDuration` 硬编码在 POU 变量区)。
3. **Phase B 结束**: 关排液阀+吹气阀, 同时 `展缸i气缸j自动:=FALSE` (盖气缸退回 = 开盖)。
4. **Phase C (60)**: 等气缸原点 (盖开到位) → `Tank_Drain_Done=TRUE`, `Tank_State=99`。

即: **旧程序已是关盖吹气**, 盖在吹完才开; 吹气段无主动抽气。
急停联锁与中途撤销 Enable 的安全归位 (关阀+撤泵票+回 Tank_State=0) 已存在。

### 2.2 物理气路 (用户口述, 2026-07-14)

水平展缸, 2 进 1 出, 3 个独立电磁阀: 进液 (展开剂) / 正压吹气 (压缩空气) / 排液 (真空泵抽)。
吹气时真空可以同开。缸内砂芯借毛细吸液, 板与砂芯接触; 抽液后砂芯仍含残液
("泵启动 ≠ 断液", 净推进量待 P0 实验量化)。

### 2.3 废液检测传感器

**真 = 废液管已走空 (只剩气)**; 按组共享 (缸 1-4 一个, 缸 5-8 一个), 共享是传感器数量的
硬件约束, 不可加装。故 Phase A 完成判据本质是"组废液线持续走空满 X 秒"的断液确认。
串扰方向分析: 邻缸的液体只会把"已走空"压回"有液", **只会延迟确认、永远不会伪造确认**
—— 误差方向天然保守 (与主机侧"宁欠展开不过展开"同哲学: 宁多抽, 不误判)。

### 2.4 双派发器真相 (plan 阶段核实, 修正 spec 初稿)

develop 存在**两个派发器** (PhotoScrape 双派发器同款坑):

- **`50_action/Develop_L2` = 活的那个**: `PLC_MainPRG` 运行态每扫描无条件调用
  (与 `Develop_TankDrain()` 并列)。动作码表 10/20/21/22/26/31/32/50/51 与主机
  `plc_develop.yaml` 完全对齐; code 50 已无 40 前置 (任意态置 Enable + 幂等 99 直通),
  code 51 已收 99/0, 31/32 已分派 A31/A32。缺口只剩: 终态换 98、51 收 98、
  50 对非法态 (10/90) 缺 REJECT。
- **`40_Man/Expand_process/Develop_L2_Dispatch` = 死代码带隐患**: 仅
  `Develop_ControlMode=1` 时被调用; 码表还是旧的 (30=润洗/40=上液, 与主机不符),
  code 50 卡 `Tank_State=40` 前置。一旦有人把 ControlMode 翻到 1, 它与活派发器
  **双写 `Develop_L2_*` 通道**。处置 = 拆除该调用分支 (legacy CASE 保留,
  ControlMode=1 分支改为空操作+注释)。

**Tank_State=40 语义裁决**: 40 只由 legacy 流程 (`Expand_process` step 40) 写入;
L2 派发路径全程不写 Tank_State, 展开期间缸一直是 0。排液 FSM 启动条件统一为
**`Tank_State ∈ {0, 40}`** (0=L2 路径, 40=legacy 路径, 两模式同治)。

### 2.5 展缸盖的既有实现 (关键修正: L2 开/关盖 action 已存在)

**⚠️ plan 阶段核实推翻了 spec 初稿的一角: "放板缸" 与 "盖" 是同一执行器。**
`50_action/Develop_L2/A31_放板缸回原点` / `A32_放板缸到动点` (host action
`develop.plate_retract` / `develop.plate_extend`, codes 31/32, plc_develop.yaml 已声明)
驱动的正是 `展缸i气缸j自动` + 等 `原点`/`动点` 反馈 —— 即开盖/关盖的 L2 原子已经写好,
**不需要新 code 52**。unload 取板前直接调 `develop.plate_retract`。
但派发器 accept 列表目前只有 10/20/30/40/50, **31/32/51 均未接通** (固件 pending 的一部分),
且 31/32 依赖的 Expand_Group/Number 派生目前只对 10/20/30/40 做 —— 迁移时一并补。

其余既有实现 (三处分散):

- **legacy `Expand_process/A30_放硅胶板`**: 放板前 `展缸i气缸j自动:=FALSE` 等 `原点` (开盖,
  允许机器人进), 放板完成后 `:=TRUE` 等 `动点` (关盖)。完整开/关盖编排先例, 但内嵌 legacy
  step 链、与机器人握手信号 (`展开工位机器人到达准备点` 等) 耦合, 不是独立 action。
- **旧排液程序结尾** (§2.1 Phase B/C): "排液附带开盖"。这是取板路径今天**唯一的开盖者**
  —— 机器人流程 `A30_取展缸硅胶板` 只做地轨+机器人调用, 不碰盖子, 依赖排液已把盖打开。
  反向确认: 新设计 98 态之后必须有显式 lid_open, 不存在其他隐藏开盖者。
- **`PLC_Cyinder_气缸动作` cylinder_0..7**: 8 缸盖气缸 FB_cylinder 实例, 手动/自动双命令位、
  原点/动点反馈、5s 超时报警 (`cyinderAlarm.0-7`)。新 lid_open action 直接复用这套命令位
  与反馈, FB 超时报警既有兜底。

主机侧 config 无任何展缸盖 action (仅收集/暂存/拍照气缸)。

盖气缸方向语义 (以 A30 实测为准): `自动:=FALSE` + 等 `原点` = 开盖; `自动:=TRUE` + 等 `动点` = 关盖。

## 3. 目标 / 非目标

**目标**

1. 排液链路从旧程序桥接收编为干净的 L2 形态: 断液与开盖物流拆开, 排液不再依赖/等待机器人;
2. 排液后板的等待环境受控: 关盖等待 + just-in-time 开盖; 可选原位干燥把板干湿状态变成受控终态;
3. 时长参数 (`DrainDuration`/`BlowDuration`/`DryDuration`) 全部上位机可写, 策略留给上机实验;
4. 拆除 40_Man 死派发器 (双写隐患) + 活派发器 (`50_action/Develop_L2`) 按新终态修缮;
   mock PLC 补 develop 排液语义 + 离线测试 (本来就 pending)。

**非目标 (YAGNI, 明确不做)**

- 多缸机器人调度 (预约/优先级/抢占): 下期资源模型专题;
- 派发通道 trigger/wait 拆分 (见 §8): 串行下阻塞派发行为正确且零改动, 本轮不做;
- load 路径 (放板/关盖) 的 L2 化: legacy `A30_放硅胶板` 不动, 关盖仍由它负责;
- 湿度/干燥传感器闭环: 无传感器, `DryDuration` 纯定时, 上机标定;
- 氮气气源改造: 现状压缩空气, 氧暴露方向与自然晾干同质。

## 4. 架构决策 (均已与用户确认, 2026-07-14)

1. **等待期策略 = 方案 C, 参数化选择开**: 排液 → 吹扫 → 原位干燥 (`DryDuration`, 设 0 即跳过,
   退化为关盖静置) → 关阀静置 (盖关) → 机器人到位后 just-in-time 开盖。
   第一性原理: 板一旦到达"干"终态, 后续等待不再劣化 —— 无界的机器人等待方差被转化为有界工艺常量。
   附带红利: 拍照工位收到的板干湿状态恒定, 视觉分析输入一致性受益; 干燥发生在 8 缸并行域,
   不占机器人/下游工位, 节拍免费。已否决: A (吹完即开盖, 等待环境不受控) 与 B (关盖静置,
   湿板斑点持续扩散) 作为独立方案 —— 二者收敛为 C 的参数组合, 不是三份代码。
2. **策略归属分层**: PLC 只提供原子 (drain-to-98 / lid_open), "什么时候开盖"完全由主机 YAML
   编排决定。今天串行流程在 unload 段首紧跟着调 lid_open (行为≈现状); 将来多缸把 lid_open
   挪到拿到机器人之后, PLC 零返工。
3. **吹气段真空票保持不撤** (改旧程序一行): 主动贯通负压气流, 吹透砂芯压差更大, 溶剂蒸气被拉进
   废液线而非滞留腔内。代价仅多占共享泵票 (引用计数, 多缸无冲突)。P0 实验可直接对比吹气段
   前沿净推进量。
4. **Phase A 判据保留传感器门控 + 新增每缸硬上限**: 传感器断液确认是 Rf 一致性叙事的物理底座,
   不降级为纯定时; 每缸硬上限看门狗把同组并发下"被邻缸挟持"变成有界延迟 (超时带警告事件强制
   进吹扫; 上限放宽松, 单缸运行永不触碰)。同组并发时判据自然退化为"全组走空", 方向保守, 可接受。
5. **干燥气源 = 压缩空气**: 对易挥发/氧敏感样品, 强制气流放大暴露 —— 故 `DryDuration` 做成
   run 级 knob 按样品类型选择开, UI 说明暴露语义。

## 5. 组件设计

### 5.1 Tank_State 语义 (扩展)

```
0   Idle          (L2 路径下展开期间也是 0 — L2 prep 不写 Tank_State)
10  Prepping      (legacy prep 中)
40  Developing    (仅 legacy 路径写入)
50  Draining      (Phase A: 真空+排液阀, 传感器判据+硬上限)
55  BlowAir       (Phase B: 吹气+排液阀+真空保持)
56  Drying        (Phase B': 同 55 气路, 时长 DryDuration; =0 跳过)   [新]
98  DrainedIdle   (阀全关、盖关、板在缸内待取; code 50 终态)          [新]
99  (legacy 遗留值: 旧 FSM "排液完成+盖已开"; 新 FSM 不再产生)
90  Error
```

**盖子位置不进 Tank_State** (单一职责: Tank_State 跟踪缸生命周期, 执行器位置由
气缸原点/动点反馈直接可观测)。`develop.release_tank` (code 51) 收
`Tank_State ∈ {98, 99}` → 写 0 (99 仅为旧值兼容)。
plc_nodes.yaml 与 Host_Computer 的 `Tank_State`/`Tank_Drain_Enable` comment 同步更新
(后者仍写着"前置条件 Tank_State[i]=40", 过期)。

### 5.2 code 50 `develop.drain` (重写)

- Phase A: 启动时拿泵票+开排液阀 → 组传感器持续走空满 `DrainDuration` 或每缸硬上限
  `DrainCapDuration` 超时 (带警告事件/标志) → Phase B;
- Phase B: 开吹气阀, 排液阀+真空票保持, 满 `BlowDuration` → Phase B' (DryDuration>0)
  或收尾 (=0);
- Phase B' (56): 气路不变继续吹+抽, 满 `DryDuration` → 收尾;
- 收尾: 关吹气阀+排液阀, 撤泵票, **盖不动 (保持关)**, `Tank_Drain_Done:=TRUE`,
  `Tank_State:=98`;
- 急停/撤销 Enable 的安全归位逻辑扩展覆盖 56/98 (98 为静止终态, 归位只需清 Done 语义,
  阀已全关)。
- FSM 位置: 仍为独立每缸并行程序 (桥接形态保留 —— 派发器单通道, FSM 必须独立于派发器
  per-tank 推进, 这是多缸并行的结构前提)。

### 5.3 开盖/关盖 = 复用既有 code 31/32 (spec 初稿的 code 52 作废)

`develop.plate_retract` (code 31) 即开盖原子 (`展缸i气缸j自动:=FALSE` 等 `原点`),
`develop.plate_extend` (code 32) 即关盖, PLC 侧 A31/A32 与主机侧 action 声明均已存在。
本次只需:

- 派发器 accept 列表补 31/32 (含 Expand_Group/Number 派生) + RUNNING CASE 分派 A31/A32
  (bActionDone 消费模式与其他 A 动作一致);
- 31/32 不设 Tank_State 前置 (纯气缸原子, load 期在 0/10 态用、unload 期在 98 态用);
- 主机 label/desc 更新为双语义 ("放板缸/展缸盖为同一执行器: 回原点=开盖, 到动点=关盖"),
  防止后来者再次误判为两个执行器;
- 复用 FB_cylinder 既有命令位/反馈/5s 超时报警, 动作秒级, 阻塞派发无压力。

### 5.4 派发器修缮 (对象 = 活派发器 `50_action/Develop_L2`)

- code 50 接受: `Tank_State ∈ {10, 90}` → REJECT 501 (retryable); 其余接受
  (∈{0,40} 置 Enable 新起排液; ∈{50,55,56} 置 Enable 无害、等同重挂在途排液,
  供恢复向导 reattach; ∈{98,99} 幂等直通)。RUNNING 完成判据
  `Tank_State ∈ {98, 99} OR Tank_Drain_Done`; 90 → 既有 502 error;
- code 51 前置 {99, 0} → **{98, 99, 0}** (accept 与 RUNNING 两处), 行为不变
  (写 Tank_State:=0 + 清 Enable/Done), 非法态 REJECT 既有 511;
- 31/32 已接通, 不动;
- **拆除 40_Man 死派发器**: `Expand_process` 的 `Develop_ControlMode=1` 分支不再调用
  `Develop_L2_Dispatch()` (防双写, 见 §2.4); legacy CASE (ControlMode=0) 原样保留。

### 5.5 参数化 (上位机可写 DT 通道)

| 参数 | 现状 | 迁移后 (Host_Computer LREAL 全局 + plc_nodes Double 节点) |
|---|---|---|
| 抽液判据时长 | `DrainDuration: TIME := T#5s` (Host_Computer 全局) | `Tank_Drain_S` (LREAL 秒, 初值 5.0); 旧 TIME 变量删除 |
| 抽液硬上限 | 无 (新增) | `Tank_Drain_Cap_S` (初值 120.0, 宽松); 超时强制进吹扫 + 锁存 `Tank_Drain_CapHit[i]` (Boolean 数组, PLC→PC, 下次排液启动时清) |
| 吹扫时长 | `BlowDuration: TIME := T#30s` (POU 变量区硬编码) | `Tank_Blow_S` (初值 30.0); 旧变量删除 |
| 原位干燥时长 | 无 (新增) | `Tank_Dry_S` (初值 0.0); 主机侧 run 级 knob `dry_duration_s`, 默认 0 (上机标定后翻) |

主机 `develop.drain` 以可选参数 (YAML 默认值与 PLC 初值一致) 经 `param.channel`
声明式别名直透以上节点, 派发前 `write_many` 写入 —— 与 `target_tank→Expand_Target_Tank`
同口径。CapHit 本轮只暴露节点 (上机复盘直读), 主机事件联动留给监控台专题。

### 5.6 主机侧改动 (薄)

- `config/actions/02_develop/plc_develop.yaml`: `develop.drain` 补 4 个时长参数
  (channel 别名) + desc 更新 (终态 98/盖保持关); `develop.release_tank` desc 更新
  (收 98/99); `develop.plate_retract/extend` label/desc 补开盖/关盖双语义;
- `config/plc_nodes.yaml`: `Tank_State` comment 更新 (+56/98, 99=legacy) + 新增
  4 个 Double 时长节点 + `Tank_Drain_CapHit` Boolean 数组;
- `config/operation/02_develop/develop_unload.yaml`: **已在取板前调
  `develop.plate_retract`, 结构零改动**, 仅注释更新 (99→98);
- `config/operation/02_develop/develop_execute.yaml`: 新增 run 级 knob
  `dry_duration_s` (REAL, 默认 0.0, ui 组"展开控制"), 传入 auto/manual 两分支的
  `develop.drain` args;
- `WaterLevelObservationCollector` 排液前冻结快照机制零改动。

### 5.7 离线测试 (mock PLC 补 develop 排液语义)

现状 `mock/plc_server.py` 的 `run_l2_fsm` 是通用 FSM (任意码直接 DONE), 不模拟
Tank_Drain 桥接与 Tank_State 推进。本次补:

- 新协程 `run_tank_drain_fsm`: 按 Enable/状态门/时长通道模拟 50→55→(56)→98+Done,
  时长直读 `Tank_*_S` 节点 (测试写小值, 无需时间缩放); 传感器挟持经测试注入的
  "湿组"集合模拟 → 走 Cap 路径锁存 CapHit;
- `run_l2_fsm` 增加 develop 语义开关: code 50 桥接 Enable/Done (含 10/90 REJECT 501
  与 98/99 幂等), code 51 门 {98,99,0} (非法 REJECT 511);
- 验收测试 (test_plc_l2_acceptance_offline) 补排液全相位/Cap 挟持/dry=0 跳过/
  release 98→0/非法态拒绝;
- VM 级 (test_develop_auto_drain_flow_offline) 补 `dry_duration_s` knob 透传到
  `develop.drain` args 的断言; 结构级 (test_develop_four_stage_offline) 守卫
  unload 序 plate_retract→robot_tank_pick→release_tank。

## 6. 错误处理汇总

| 情形 | 行为 |
|---|---|
| Phase A 传感器判据满足 | 正常进吹扫 |
| Phase A 被同组邻缸液体延迟 | 有界延迟 (最慢邻缸), 方向保守, 不报警 |
| Phase A 超 `DrainCapDuration` | 强制进吹扫 + 警告事件 (可能砂芯残液偏多, 上机复盘) |
| code 50 派发时缸态 ∈ {10, 90} | REJECT 501 (retryable) |
| code 51 派发时缸态非 {98, 99, 0} | REJECT 511 (既有错误码) |
| 盖气缸开盖超时 | FB_cylinder 5s 报警 → L2 error 路径 |
| 急停 / 中途撤销 Enable | 既有安全归位扩展覆盖 56/98 |
| drain 整体卡死 | 主机既有 stall 180s / action 900s 看门狗不变 |

## 7. 上机验证项 (软件落地后)

1. 吹气段真空保持 vs 撤销的前沿净推进对比 (并入 P0 实验批次);
2. `DryDuration` 标定: 不同溶剂体系下板到干态的时长; 定 knob 默认值;
3. 多缸同组并发排液的 Phase A 延迟实测 (传感器挟持幅度);
4. 开盖 just-in-time 后取板全链 dry-run (develop_unload 新序)。

## 8. 后续留位 (本期不做, 语义已兼容)

- **多缸调度**: 资源模型专题; lid_open 届时挪到机器人资源获取之后, 编排层改动, PLC 零返工;
- **派发通道 trigger/wait 拆分**: 今天 code 50 阻塞占住 Develop_L2 单通道直到排液完成,
  多缸并发时两缸同时排液会被派发通道串行化。届时改法 = 派发在 FSM 启动即 DONE, 主机另起
  host 动作轮询 `Tank_State=98` (wait_level 同款形态) —— 只改派发器与主机;
  per-tank FSM 与状态语义本轮已按并发形态浇筑;
  ⚠ 届时 4 个时长通道 (共享标量) 须一并升级为每缸数组或 PLC 启动时锁存, 否则后派发会
  改写在途缸的 TON PT (终审 Important; 警示已钉进 plc_nodes 与 A50 头注释);
- **load 路径 L2 化**: 关盖 (`lid_close`) 届时从 legacy A30 收编, 命令位/反馈同 §2.5;
- **T3 直接拔板应急路径**: 沿 2026-07-13 spec 口径, 等 P0 数据后再议。
