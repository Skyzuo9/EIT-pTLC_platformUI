# PLC多通道展开ST代码改造草稿

> 基于架构决策确认（2026-05-13），针对 `plc_develop.txt` 的改造设计  
> Phase 1: 全局单序列器 + Tank_State跟踪 + Per-tank排液

---

## 1. 改造概述

### 1.1 改造目标

将展开工位从"单资源自治状态机"升级为"全局准备序列器 + Per-tank状态寄存器 + 独立排液程序"，
支持多缸交替准备、并行展开、独立排液。

### 1.2 核心变更清单

| # | 变更项 | 类型 | 说明 |
|---|--------|------|------|
| 1 | 新增 `Tank_State[1..8]` | 新增变量 | 每缸状态跟踪（0/10/40/50/99/90） |
| 2 | 新增 `Expand_Target_Tank` | 新增变量 | PC指定目标缸号(1-8) |
| 3 | 新增 `Tank_Drain_Enable/Done[1..8]` | 新增变量 | Per-tank排液触发/完成 |
| 4 | 修改 Step=0 触发逻辑 | 改造 | Enable触发时读取Target_Tank，推导Group/Number |
| 5 | 修改 Step 10/20 操作目标 | 改造 | 所有prep操作针对target缸 |
| 6 | **重大变更**: Step 40 逻辑 | 改造 | 不再等待展开完成；设Tank_State=40后立即Done |
| 7 | 新增排液子程序 `FB_TankDrain` | 新增程序块 | 独立于主序列器的per-tank排液控制 |
| 8 | 废弃 `Expand_Group_clean` | 清理 | 已由Expand_Mode_Flag替代 |
| 9 | 废弃 `Expand_forward_instructions_clean/UP` | 清理 | 已合并为单一变量 |
| 10 | 废弃 Expand_Confirm 及 Step 35 | 清理 | 展开完成→排液的握手已由 Tank_Drain_Enable 替代 |

### 1.3 Expand_Done语义变更

```
旧语义: prep + develop + drain 整流程完成
新语义: 当前prep指令执行完毕，目标缸已进入展开阶段（Tank_State[target]=40）
```

---

## 2. 新增全局变量声明

```st
VAR_GLOBAL
    // ══════════════════════════════════════════════════════════════
    // 展开工位六件套（协议 v1.2 / Phase B1）—— 保持不变
    // ══════════════════════════════════════════════════════════════
    Expand_Enable       : BOOL;         // PC→PLC: TRUE 启动状态机
    Expand_Step         : INT;          // PLC→PC: 子步号 {0,10,20,30,40,90}
    Expand_Done         : BOOL;         // PLC→PC: 完成锁存（语义变更：prep完成）
    Expand_Error        : BOOL;         // PLC→PC: 故障锁存
    Expand_Reset        : BOOL;         // PC→PLC: TRUE 清错误
    Expand_Busy         : BOOL;         // PLC→PC: 派生信号

    // ── 业务参数（保持不变）──
    Expand_Mode_Flag    : INT;          // 0=缸模式润洗 / 1=管路模式润洗
    Expand_Group        : INT;          // 展开组号（1 或 2），由PLC自动推导
    Expand_Number       : INT;          // 缸号在组内序号（1-4），由PLC自动推导
    Expand_forward_instructions : STRING(128);  // 注射泵DT协议指令（合并后的单一变量）

    // ══════════════════════════════════════════════════════════════
    // 【新增】展缸状态跟踪
    // ══════════════════════════════════════════════════════════════
    Tank_State          : ARRAY[1..8] OF INT;
        // PLC→PC: 每缸状态
        //   0  = Idle（空闲，可分配）
        //   10 = Prepping（准备中：润洗/上液/放板）
        //   40 = Developing（展开中，等待视觉/延时触发排液）
        //   50 = Draining（排液中）
        //   99 = Done（排液完成，等待PC释放）
        //   90 = Error（故障）

    Tank_SampleID       : ARRAY[1..8] OF DINT;
        // PC→PLC: 绑定样品ID（调试/溯源用，PLC不使用此值做逻辑判断）

    // ══════════════════════════════════════════════════════════════
    // 【新增】Prep目标参数
    // ══════════════════════════════════════════════════════════════
    Expand_Target_Tank  : INT;
        // PC→PLC: 目标缸号(1-8)，Enable触发前写入
        // PLC读取后自动推导：
        //   Expand_Group  = (Target_Tank - 1) DIV 4 + 1
        //   Expand_Number = (Target_Tank - 1) MOD 4 + 1

    // ══════════════════════════════════════════════════════════════
    // 【新增】Per-tank排液控制
    // ══════════════════════════════════════════════════════════════
    Tank_Drain_Enable   : ARRAY[1..8] OF BOOL;
        // PC→PLC: 触发第i缸排液（前置条件：Tank_State[i]=40）

    Tank_Drain_Done     : ARRAY[1..8] OF BOOL;
        // PLC→PC: 第i缸排液完成锁存
        // PC确认后写Tank_Drain_Enable[i]=FALSE进行复位

    // ══════════════════════════════════════════════════════════════
    // 【新增】排液子程序内部变量
    // ══════════════════════════════════════════════════════════════
    DrainTimer          : ARRAY[1..8] OF TON;
        // 每缸排液定时器（后续可替换为传感器判断）

    DrainDuration       : TIME := T#120S;
        // 排液持续时间（全局默认值，后续可改为per-tank配置）

    // ══════════════════════════════════════════════════════════════
    // 【废弃变量 —— 应从代码中移除】
    // ══════════════════════════════════════════════════════════════
    // Expand_Confirm                  : BOOL;   -- 已废弃，展开完成→排液的握手已由Tank_Drain_Enable[i]替代
    // Expand_Group_clean              : INT;    -- 已废弃，由Expand_Mode_Flag替代
    // Expand_forward_instructions_clean : STRING(128); -- 已废弃，合并入Expand_forward_instructions
    // Expand_Group_UP                 : INT;    -- 已废弃，Target_Tank可推导
    // Expand_Number_UP                : INT;    -- 已废弃，Target_Tank可推导
    // Expand_forward_instructions_UP  : STRING(128); -- 已废弃，合并入Expand_forward_instructions
END_VAR
```

### 2.1 变量语义速查表

| 变量 | 方向 | 类型 | 语义 |
|------|------|------|------|
| `Tank_State[i]` | PLC→PC | INT | 缸状态机 {0,10,40,50,99,90} |
| `Tank_SampleID[i]` | PC→PLC | DINT | 样品绑定ID（仅调试用） |
| `Expand_Target_Tank` | PC→PLC | INT | 当前prep目标缸(1-8) |
| `Tank_Drain_Enable[i]` | PC→PLC | BOOL | 触发第i缸排液 |
| `Tank_Drain_Done[i]` | PLC→PC | BOOL | 第i缸排液完成锁存 |
| `DrainTimer[i]` | 内部 | TON | 排液定时器 |
| `DrainDuration` | 配置 | TIME | 排液持续时间 |

---

## 3. 现有代码改动点标注

以下对照 `plc_develop.txt` 原始行号，标注需要修改的位置：

### 3.1 VAR_GLOBAL 块（行 11-30）

| 行号 | 原内容 | 操作 | 原因 |
|------|--------|------|------|
| 23 | `Expand_Group: INT; // 润洗展开组号（>0 走缸模式）` | **修改注释** | Group不再做逻辑判断，改为由PLC自动推导 |
| 24 | `Expand_Group_clean: INT;` | **删除** | 已废弃 |
| 25 | `Expand_Number: INT; // 润洗号/展缸号` | **修改注释** | 改为由PLC自动推导 |
| 26 | `Expand_forward_instructions_clean: STRING(128);` | **删除** | 已合并 |
| 27 | `Expand_Group_UP: INT;` | **删除** | Target_Tank可推导 |
| 28 | `Expand_Number_UP: INT;` | **删除** | Target_Tank可推导 |
| 29 | `Expand_forward_instructions_UP: STRING(128);` | **删除** | 已合并 |
| - | (新增多个变量) | **新增** | 见第2节 |

### 3.2 Step 0 触发逻辑（行 65-68）

| 行号 | 原内容 | 操作 | 原因 |
|------|--------|------|------|
| 66-68 | 直接 `Expand_Step := 10` | **改造** | 新增：读取Target_Tank、校验合法性、自动推导Group/Number、设Tank_State[target]:=10 |

### 3.3 Step 10 润洗逻辑（行 70-80）

| 行号 | 原内容 | 操作 | 原因 |
|------|--------|------|------|
| 71 | `IF Expand_Mode_Flag = 0 AND Expand_Group > 0 THEN` | **简化条件** | Group由PLC自动推导，必>0；只需检查Mode_Flag |
| 73 | `ELSIF Expand_Mode_Flag = 1 AND Expand_Group_clean > 0 THEN` | **修改** | 删除Expand_Group_clean条件，改用Mode_Flag=1 |

### 3.4 Step 20 上液逻辑（行 82-90）

| 行号 | 原内容 | 操作 | 原因 |
|------|--------|------|------|
| 83 | `IF Expand_Group_UP > 0 AND Expand_Number_UP > 0 THEN` | **删除判断** | UP变量废弃，统一使用target缸的Group/Number |

### 3.5 Step 35 乒乓握手（行 95-101）—— **删除**

| 行号 | 原内容 | 操作 | 原因 |
|------|--------|------|------|
| 95-101 | Step 35 等待Expand_Confirm | **整段删除** | 展开完成→排液触发已由Tank_Drain_Enable替代，放板由机械臂+传感器自治完成 |

### 3.6 Step 40 展开+排液逻辑（行 107-114）—— **最关键改动**

| 行号 | 原内容 | 操作 | 原因 |
|------|--------|------|------|
| 107-114 | 展开排液等待完成后Done | **彻底重写** | 不再等待展开完成；设Tank_State[target]=40后立即Done释放序列器 |

---

## 4. 改造后的完整状态机代码

### 4.1 准备序列器（主状态机 —— 改造后完整代码）

```st
// ══════════════════════════════════════════════════════════════
// 展开工位准备序列器（协议 v1.2+ / Phase MultiTank）
// ══════════════════════════════════════════════════════════════
// 职责：执行prep流程（润洗→上液→放板→交付至展开态）
// 语义变更：Expand_Done = prep完成（非整流程完成）
// 序列器释放后可立即接受下一个prep请求
// ══════════════════════════════════════════════════════════════

VAR
    stepTimer   : TON;       // 步骤内通用定时器
    targetTank  : INT;       // 本轮prep的目标缸号（锁存值）
    targetGroup : INT;       // 推导的组号（1或2）
    targetNum   : INT;       // 推导的组内序号（1-4）
END_VAR

// ── 1. 急停联锁（最高优先级）──
IF PLC_EStop THEN
    Expand_Step  := 0;
    Expand_Done  := FALSE;
    Expand_Error := TRUE;
    Expand_Busy  := FALSE;
    // 急停时将所有Prepping状态的缸标记为Error
    FOR i := 1 TO 8 DO
        IF Tank_State[i] = 10 THEN
            Tank_State[i] := 90;
        END_IF
    END_FOR
    stepTimer(IN := FALSE, PT := T#0S);
    RETURN;
END_IF

// ── 2. 复位脉冲（用于错误恢复 / 强制清状态）──
IF Expand_Reset THEN
    Expand_Step  := 0;
    Expand_Done  := FALSE;
    Expand_Error := FALSE;
    Expand_Busy  := FALSE;
    stepTimer(IN := FALSE, PT := T#0S);
    // 注意：Tank_State不在此处清理，由PC决定是否单独复位某缸
    RETURN;
END_IF

// ── 3. Enable=FALSE 时清 Done（次周期复位握手）──
IF NOT Expand_Enable THEN
    Expand_Done := FALSE;
END_IF

// ── 4. 派生 Expand_Busy ──
Expand_Busy := (Expand_Step >= 10)
              AND (Expand_Step <= 80)
              AND (NOT Expand_Done);

// ── 5. 主状态机（准备序列器）──
CASE Expand_Step OF

    0:  // ═══ 空闲：等待 Enable 上升 ═══
        IF Expand_Enable AND (NOT Expand_Done) THEN
            // 【新增】读取目标缸号并校验
            targetTank := Expand_Target_Tank;

            // 校验：目标缸号必须在1-8范围内
            IF targetTank < 1 OR targetTank > 8 THEN
                Expand_Error := TRUE;
                Expand_Step := 90;
            // 校验：目标缸必须处于Idle状态（防止重复prep）
            ELSIF Tank_State[targetTank] <> 0 THEN
                Expand_Error := TRUE;
                Expand_Step := 90;
            ELSE
                // 【新增】自动推导 Group 和 Number
                targetGroup := (targetTank - 1) / 4 + 1;   // 1-4→Group1, 5-8→Group2
                targetNum   := (targetTank - 1) MOD 4 + 1; // 组内序号1-4

                // 写入协议变量（供FB调用使用）
                Expand_Group  := targetGroup;
                Expand_Number := targetNum;

                // 【新增】标记目标缸进入Prepping状态
                Tank_State[targetTank] := 10;

                // 推进到Step 10
                Expand_Step := 10;
                stepTimer(IN := FALSE, PT := T#0S);  // 复位定时器
            END_IF
        END_IF

    10: // ═══ 润洗/清洗（Expand_Mode_Flag=0→缸模式；=1→管路模式）═══
        // 润洗/清洗操作针对 targetTank 对应的泵组
        IF Expand_Mode_Flag = 0 THEN
            // 缸模式润洗：使用 targetGroup 对应的泵执行润洗
            clean_expand_润洗展缸();     // FB内部使用Expand_Group/Number
        ELSIF Expand_Mode_Flag = 1 THEN
            // 管路模式清洗
            pipeline_cleaning_清洗管路(); // FB内部使用Expand_Group/Number
        END_IF
        // TODO【实机集成点】替换为真实FB调用，按完成信号推进
        stepTimer(IN := NOT stepTimer.Q, PT := T#5S);
        IF stepTimer.Q THEN
            stepTimer(IN := FALSE, PT := T#0S);
            Expand_Step := 20;
        END_IF

    20: // ═══ 上液（展开剂加入目标展缸）═══
        // 使用Expand_forward_instructions中的DT协议指令驱动注射泵
        // 目标缸由targetGroup/targetNum确定
        up_liquid_上液();    // FB内部使用Expand_Group/Number和forward_instructions
        // TODO【实机集成点】替换为真实FB调用
        stepTimer(IN := NOT stepTimer.Q, PT := T#5S);
        IF stepTimer.Q THEN
            stepTimer(IN := FALSE, PT := T#0S);
            Expand_Step := 30;
        END_IF

    30: // ═══ 放硅胶板（机械臂+传感器自治）═══
        // 放板由机械臂执行，传感器确认到位后PLC自动推进
        // 不再需要PC握手确认（旧Step 35已废弃）
        silica_gel_plate_放硅胶板();
        // TODO【实机集成点】替换为真实FB调用，以传感器到位信号作为完成条件
        stepTimer(IN := NOT stepTimer.Q, PT := T#5S);
        IF stepTimer.Q THEN
            stepTimer(IN := FALSE, PT := T#0S);
            Expand_Step := 40;  // 直接进入交付释放
        END_IF

    40: // ═══ 【关键变更】交付至展开态 —— 立即释放序列器 ═══
        // 旧逻辑：在此等待展开+排液完成后才Done
        // 新逻辑：设Tank_State=40后立即Done，释放序列器给下一个prep

        // 将目标缸状态从 Prepping(10) 推进到 Developing(40)
        Tank_State[targetTank] := 40;

        // 标记prep完成，释放序列器
        Expand_Done := TRUE;
        Expand_Busy := FALSE;
        Expand_Step := 0;

        // 序列器已归零，可接受下一个prep请求
        // 实际展开由缸自身"静置"完成，排液由独立子程序处理

    90: // ═══ 故障态：等待外部 Expand_Reset 脉冲 ═══
        Expand_Error := TRUE;   // 故障态本身不动作，仅等待顶部复位逻辑

END_CASE
```

### 4.2 排液子程序（新增独立程序块）

```st
// ══════════════════════════════════════════════════════════════
// 排液控制程序（独立于准备序列器，每扫描周期调用）
// ══════════════════════════════════════════════════════════════
// 职责：监控 Tank_Drain_Enable[1..8]，触发对应缸的排液流程
// 触发条件：Tank_Drain_Enable[i]=TRUE 且 Tank_State[i]=40
// 完成标志：Tank_Drain_Done[i]=TRUE, Tank_State[i]=99
// 复位方式：PC写 Tank_Drain_Enable[i]=FALSE
// ══════════════════════════════════════════════════════════════
// 硬件映射：
//   - 每缸入口有独立三通阀（通/废液切换）
//   - 排液使用真空泵系统（与注射泵无竞争）
//   - 支持多缸同时排液
// ══════════════════════════════════════════════════════════════

PROGRAM PRG_TankDrain
VAR
    i : INT;  // 循环索引
END_VAR

FOR i := 1 TO 8 DO

    // ── 场景1：PC撤销Drain_Enable → 复位Done标志（握手完成）──
    IF NOT Tank_Drain_Enable[i] THEN
        Tank_Drain_Done[i] := FALSE;
        DrainTimer[i](IN := FALSE, PT := T#0S);  // 复位定时器
        // 注意：不主动修改Tank_State，由PC决定是否释放(设为0)
    END_IF

    // ── 场景2：Drain_Enable=TRUE，缸处于Developing(40)，启动排液 ──
    IF Tank_Drain_Enable[i] AND Tank_State[i] = 40 THEN
        // 切换三通阀到废液方向
        SET_ThreeWayValve(tankIndex := i, direction := DRAIN);  // TODO：替换为实际IO映射

        // 开启真空泵
        SET_VacuumPump(enable := TRUE);  // TODO：替换为实际IO映射

        // 推进状态至 Draining
        Tank_State[i] := 50;
    END_IF

    // ── 场景3：缸处于Draining(50)，等待排液定时完成 ──
    IF Tank_State[i] = 50 THEN
        DrainTimer[i](IN := TRUE, PT := DrainDuration);

        IF DrainTimer[i].Q THEN
            // 排液完成
            // 关闭该缸三通阀（恢复常态）
            SET_ThreeWayValve(tankIndex := i, direction := CLOSED);  // TODO：替换为实际IO映射

            // 标记排液完成
            Tank_Drain_Done[i] := TRUE;
            Tank_State[i] := 99;

            // 复位定时器
            DrainTimer[i](IN := FALSE, PT := T#0S);
        END_IF
    END_IF

END_FOR

// ── 真空泵全局控制：当无任何缸在排液时关闭真空泵 ──
VAR
    anyDraining : BOOL := FALSE;
END_VAR
FOR i := 1 TO 8 DO
    IF Tank_State[i] = 50 THEN
        anyDraining := TRUE;
        EXIT;
    END_IF
END_FOR
IF NOT anyDraining THEN
    SET_VacuumPump(enable := FALSE);  // 全部完成，关闭真空泵
END_IF

END_PROGRAM
```

### 4.3 Tank状态复位辅助逻辑（可选，集成到主扫描或独立POU）

```st
// ══════════════════════════════════════════════════════════════
// Tank状态复位（由PC通过写Tank_State[i]=0触发）
// ══════════════════════════════════════════════════════════════
// 说明：当PC侧ResourceManager.release(tank_id)执行后，
//       PC直接将Tank_State[i]写为0，缸回归Idle池。
//       PLC侧不需要额外逻辑，只需确保Tank_State为PC可写。
//
// OPC UA节点权限配置：
//   Tank_State[1..8] —— PLC写(状态推进) + PC写(复位为0)
//   需在OPC UA服务端配置双向读写权限
// ══════════════════════════════════════════════════════════════
```

---

## 5. 关键设计决策说明

### 5.1 Expand_Done语义变更

```
┌─────────────────────────────────────────────────────┐
│  旧流程（单缸阻塞）                                   │
│  Enable → prep → 展开等待(30-60min) → 排液 → Done   │
│  序列器全程被占用，无法接新请求                         │
├─────────────────────────────────────────────────────┤
│  新流程（多缸交替）                                   │
│  Enable → prep(5-10min) → Tank_State=40 → Done      │
│  序列器立即释放，可接下一个prep                        │
│  展开完成由视觉/延时触发Drain，与序列器无关            │
└─────────────────────────────────────────────────────┘
```

**兼容性保证**：
- 上位机侧 `DevelopStage` 仍使用 `await Expand_Done` 判断prep完成
- 但Done现在意味着"该缸已进入展开"，不再意味着"该缸展开排液全部完成"
- 实际完成由 `Tank_State[i]=99` 或 `Tank_Drain_Done[i]=TRUE` 判定

### 5.2 Tank_State状态转换规则

```
                  ┌──────────────────────────────────────────┐
                  │          Tank_State 状态机                │
                  └──────────────────────────────────────────┘

    ┌─────┐  prep触发  ┌──────┐  Step40交付  ┌────────────┐
    │  0  │──────────→│  10  │────────────→│     40     │
    │Idle │           │Prep- │             │Developing  │
    │     │           │ ping │             │(展开静置)   │
    └─────┘           └──────┘             └────────────┘
       ↑                  │                      │
       │                  │ Error                 │ Drain触发
       │                  ↓                      ↓
       │              ┌──────┐             ┌──────────┐
       │              │  90  │             │    50    │
       │              │Error │             │Draining  │
       │              └──────┘             └──────────┘
       │                  ↑                      │
       │                  │ Error                 │ 排液完成
       │                  │                      ↓
       │                  │                ┌──────────┐
       │                  └────────────────│    99    │
       │         PC释放(写0)               │  Done    │
       └───────────────────────────────────└──────────┘

    转换触发者：
    - 0→10  : PLC（prep序列器Step 0触发）
    - 10→40 : PLC（prep序列器Step 40交付）
    - 40→50 : PLC（排液子程序，Drain_Enable触发）
    - 50→99 : PLC（排液子程序，定时/传感器完成）
    - 99→0  : PC（ResourceManager.release()写入）
    - *→90  : PLC（急停/异常）
    - 90→0  : PC（手动复位）
```

### 5.3 Expand_Confirm废弃说明

旧架构中 Expand_Confirm 的真正用途：
- Step 35: PLC等待PC通知"展开完成，可以开始排液"
- PC接收视觉模块的"展开完成"信号后写 Expand_Confirm=TRUE
- PLC读到后进入排液流程

新架构中的替代机制：
- 展开完成→排液触发 已由独立的 Tank_Drain_Enable[i] 信号承担
- Prep序列器在Step 40交付后立即释放，不等待展开完成
- 视觉检测到展开完成 → PC写 Tank_Drain_Enable[i]=TRUE → 排液子程序独立处理
- 因此 Expand_Confirm 和 Step 35 在展开流程中完全废弃

### 5.4 准备序列器的Reset逻辑

```
Reset触发场景：
1. PC检测到prep超时/异常 → 写Expand_Reset=TRUE
2. PLC清除序列器状态（Step=0, Done=FALSE, Error=FALSE, Busy=FALSE）
3. 注意：Tank_State[target]不自动清理
   - 如果prep中途出错，Tank_State仍保持在10(Prepping)
   - PC需要额外写Tank_State[target]=0或90来处理该缸

设计理由：
- Reset只负责序列器自身恢复，不干预缸状态
- 缸状态由PC全权管理（Resource Manager职责）
- 避免Reset时误清其他正在展开的缸
```

### 5.5 Expand_Group与Target_Tank的自动映射

```st
// 映射规则（在Step 0中自动执行）：
targetGroup := (Expand_Target_Tank - 1) / 4 + 1;
targetNum   := (Expand_Target_Tank - 1) MOD 4 + 1;

// 对照表：
// Target_Tank | Group | Number | 物理含义
// ------------|-------|--------|------------------
//     1       |   1   |   1    | 泵1，第1路三通阀
//     2       |   1   |   2    | 泵1，第2路三通阀
//     3       |   1   |   3    | 泵1，第3路三通阀
//     4       |   1   |   4    | 泵1，第4路三通阀
//     5       |   2   |   1    | 泵2，第1路三通阀
//     6       |   2   |   2    | 泵2，第2路三通阀
//     7       |   2   |   3    | 泵2，第3路三通阀
//     8       |   2   |   4    | 泵2，第4路三通阀
```

**PC侧简化**：PC只需写 `Expand_Target_Tank=3`，不再需要分别计算和写入Group/Number/Group_UP/Number_UP。

### 5.6 多缸排液并行安全性

```
资源竞争分析：
- 三通阀：每缸独立 → 无竞争 ✓
- 真空泵：全局共享 → 不竞争（多缸可同时抽真空）✓
- 注射泵：排液不使用注射泵 → 无竞争 ✓

因此：多缸同时排液完全安全，排液子程序可并行处理所有Enable=TRUE的缸。
```

---

## 6. 程序调用结构

```
主任务周期扫描（MAIN Task）
├── PRG_ExpandPrep()     ←── 准备序列器（本文4.1节）
├── PRG_TankDrain()      ←── 排液子程序（本文4.2节）
└── (其他工位状态机...)
```

**扫描周期要求**：
- PRG_ExpandPrep 和 PRG_TankDrain 必须在同一任务周期中调用
- 推荐放在同一MAIN任务中，确保Tank_State读写一致性
- 排液定时器精度取决于任务周期（建议≤20ms）

---

## 7. OPC UA节点注册清单（新增）

以下变量需在OPC UA服务端注册为可读写节点：

| 节点名 | 数据类型 | 数组 | 读写 | 备注 |
|--------|----------|------|------|------|
| `Tank_State` | Int16[] | [1..8] | R/W | PLC写状态推进，PC写复位 |
| `Tank_SampleID` | Int32[] | [1..8] | R/W | PC写绑定ID |
| `Expand_Target_Tank` | Int16 | - | R/W | PC写目标缸 |
| `Tank_Drain_Enable` | Boolean[] | [1..8] | R/W | PC写触发排液 |
| `Tank_Drain_Done` | Boolean[] | [1..8] | R | PLC写完成标志 |

> 注：现有六件套（Enable/Step/Done/Error/Reset/Busy）及Mode_Flag等保持原有节点配置不变。Expand_Confirm已废弃，可从节点注册中移除。

---

## 8. 与上位机的交互时序（完整）

```
═══ Prep缸3 ═══
PC:   写 Expand_Target_Tank = 3
PC:   写 Expand_Mode_Flag = 0 (缸模式)
PC:   写 Expand_forward_instructions = "/1I1P480R;/1I3P960R"
PC:   写 Expand_Enable = TRUE

PLC:  读Target=3, 校验Tank_State[3]=0 ✓
PLC:  推导 Group=1, Number=3
PLC:  Tank_State[3] := 10
PLC:  Expand_Step=10, Expand_Busy=TRUE
PLC:  [执行润洗] → Step=20
PLC:  [执行上液] → Step=30
PLC:  [放硅胶板+传感器确认到位] → Step=40
PLC:  Tank_State[3] := 40   ← 关键：进入展开态
PLC:  Expand_Done := TRUE    ← 关键：prep完成信号
PLC:  Expand_Step := 0       ← 序列器归零

PC:   检测到Done=TRUE → prep流程结束
PC:   写 Expand_Enable = FALSE → Done被清零
PC:   序列器空闲，可立即发起下一个prep

═══ 30-60分钟后，视觉检测展开完成 ═══

PC:   写 Tank_Drain_Enable[3] = TRUE

PLC:  检测到 Drain_Enable[3]=TRUE 且 Tank_State[3]=40
PLC:  切换缸3三通阀→废液方向
PLC:  开启真空泵
PLC:  Tank_State[3] := 50 (Draining)
PLC:  [等待定时完成]
PLC:  Tank_State[3] := 99 (Done)
PLC:  Tank_Drain_Done[3] := TRUE

PC:   检测到 Drain_Done[3]=TRUE → 排液完成
PC:   写 Tank_Drain_Enable[3] = FALSE → Done被清零
PC:   ResourceManager.release(3) → 写Tank_State[3]=0
PC:   缸3回归Idle池
```

---

## 9. 迁移检查清单

- [ ] 删除废弃变量：`Expand_Group_clean`, `Expand_forward_instructions_clean`, `Expand_Group_UP`, `Expand_Number_UP`, `Expand_forward_instructions_UP`
- [ ] 新增全局变量并注册OPC UA节点
- [ ] 改造主状态机Step 0（增加Target_Tank读取和校验）
- [ ] 改造主状态机Step 10（移除Group_clean条件）
- [ ] 改造主状态机Step 20（移除UP变量条件）
- [ ] **关键改造**：Step 40 从"展开等待"变为"交付释放"
- [ ] 新增 PRG_TankDrain 排液程序
- [ ] 配置 MAIN 任务调用顺序
- [ ] 上位机 mock_server 注册新变量
- [ ] 上位机 plc_client 新增节点定义
- [ ] 废弃 Expand_Confirm 变量（展开流程中不再使用）
- [ ] 移除主状态机中的 Step 35 分支
- [ ] 联调验证：单缸prep→Done→Drain→Done全流程
- [ ] 联调验证：双缸交替prep（确认序列器释放正确）
