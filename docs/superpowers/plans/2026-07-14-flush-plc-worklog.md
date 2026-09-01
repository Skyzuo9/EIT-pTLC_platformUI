# flush PLC 命名对照表 (SP-B Task 1 发现产物, 2026-07-14)

真源: eit_ptlc/plc/20260702.project (codesys-mcp 直读)。以下为轻清洗 mode=1 分支落笔的唯一命名真源。

## 六项对照

1. **POU 与动作码 20 定位**
   - 父调度: `Application/50_action/Sampling_L2`(PROGRAM);IDLE 接受 Start 上升沿 → RUNNING 每周期 `CASE Sampling_L2_ActiveCode OF ... 20: A20_clean_清洗();`
   - 清洗原子: `Application/50_action/Sampling_L2/A20_clean_清洗`(无独立 decl,变量在父 POU VAR 区);步变量 `清洗step: INT`(父 decl),IDLE 接受时清零。
   - **mode 分支完全收在 A20 内,父 POU 零改动**(分发/锁存均通用)。

2. **泵指令 idiom(非 FB,邮箱模式)**
   - 占泵总线: `IF %MW1300=0 AND NOT 泵站位符 THEN 泵站位符:=TRUE; 转发转存:=<指令>; %MW1300:=LEN(STR:=转发转存); ...`
   - Q 确认空闲: `IF %MW1300=0 AND TON[n].Q THEN 转发转存:='/4Q$R'; %MW1300:=LEN(...); END_IF` + `R_TRIG[m](CLK:=%MX2005.5)` 上升沿(泵空闲应答位)→ `泵站位符:=FALSE` 并推进。TON PT=T#0.5S(重发节拍)。
   - 释放/再占先例: A20 现行在段间释放再占(step20 释→step24 占);flush 沿用。

3. **三通阀 DO**: `上样点样三通电池阀自动: BOOL`
   - **TRUE = 点样头流路;FALSE = 上样针流路**。证据: A62/A60 向点样头供液全程 TRUE;A10_init 复位 FALSE;A20 现行第一遍 instructions[1] 阀 TRUE(冲点样头侧)、第二遍 FALSE(冲上样针侧)。

4. **切阀延时**: 全工程无阀行程 TON 先例(A62 step12、A60 step5 均为置阀与发泵指令同周期)→ flush 不加延时,与既有一致。

5. **DONE 锁存 idiom**: 原子内 `Sampling_Cleaning_OK:=TRUE; 清洗step:=0; bActionDone:=TRUE;` → 父层 `IF bActionDone THEN CompletedSeq:=AcceptedSeq; State:=20`;终态 `IF (NOT Sampling_L2_Start) OR Reset THEN State:=0`。错误: 原子置 `Sampling_L2_ErrorCode` + `bActionError:=TRUE`。

6. **count 循环结构(mode=1 必须绕开)**: step7 按 `Sampling_clean_count>0` 进 10..50 循环(50 处 清洗计数++ 对比 count 回跳 10);**分支点选在 step7 轴到位判据内**: `mode=1 → 清洗step:=110`(绕开 10..60 全部),mode≠1 走原判据(原文不动)。

## 计划假设的修正(发现驱动)

- **GVL pragma**: Host_Computer 同组通道变量(Sampling_clean_count 等)**均无** `{attribute 'symbol'...}`(仅 Rail_ActPos/Rail_Homed 有)——OPC UA 可见性由符号配置整组导出保证。新变量跟随兄弟风格: **不加 pragma**,加 GrpComment 双格式注释。锚点: `Sampling_clean_count: INT;` 之后。
- **物理前置条件升级**: A20 步 0-7 轴前置段(点样6X→position[1] 清洗位 / 上样4X→Sampling_4X_WashTarget / 上样5Z→position[1])为 clean/flush 共用——**"上样针在清洗位、点样头在清洗位"由 PLC 保证,不再依赖编排层**(spec §5 前置条件实际上被 A20 原生满足)。
- **现行 clean 真实语义勘误**: instructions[1] 发两遍(阀 TRUE 冲点样头侧一遍 + 阀 FALSE 冲上样针侧一遍),再 instructions[2] 外壁——host 注释"[内壁,外壁]"是简化说法。mode=0 不动,仅记录。
- **%MW1300:=128 + 空串** 为 clean step50 循环间邮箱清理特例;prep/absorb/spray 完成路径均无 → flush 完成路径不搬(跟随多数 idiom)。

## 资源分配(空闲下标盘点, 全 10 个子原子已核)

- TON[1..11] 已用 {1,2,4,5,6,7,8,10,11} + TON_0/TON_1 → **flush 用 TON[3](step=120), TON[9](step=140)**
- R_TRIG[1..12] 已用 {1,2,3,10,11,12}(注: [10] 有 A50/A60 跨原子复用先例) → **flush 用 R_TRIG[4], R_TRIG[5]**(CLK:=%MX2005.5)
- flush 步号 110/120/130/140,与现行 0/5/6/7/10/20/24/26/30/40/50/60 无碰撞。

## 已知留后项(不在本次范围)

- 父 Reset 路径对 code 20 只释放 泵站位符,不复位三通阀(对 62 才复位)——mode=0 现行同样暴露(step10-20 窗口阀 TRUE 被 Reset 打断即残留)。flush 使暴露窗口变长(entry[2] 全程阀 TRUE),但阀静置无流量、下一动作派发时必显式置阀,风险低;若要闭合应连 mode=0 一起改父 Reset,与"mode=0 零变化"约束冲突,留上机联调时定。
- Reset 不发 /4T 停泵(泵链式指令继续走完)——mode=0 既有行为,同上留后。

## Task 3 落笔硬性要求勾验单(实现后逐条核)

1. 切阀只在 phase 120(Q空闲后)与 140(Q空闲后)  2. mode=1 不进 count 循环  3. 错误路径复用既有(本分支无新增错误码;Q 重发节拍内无超时先例,跟随 A20 现行"无超时"语义)  4. 清洗step 由父 IDLE 接受时归零 + 完成路径归零  5. 原路径 diff 为零(step7 包裹行除外)
