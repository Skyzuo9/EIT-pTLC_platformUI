# 条带点样 E+B(蛇形+端点去驻留)+ 死体积补偿判终 PLC 合并改动集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A62 单条带点样步链重构:液体程蛇形双向 + 到位即停泵起吹干(查询/沉降/解析并行化),判终阈值同批改为 `pos <= Sampling_band_end_position + 5`,消除起点空白/终点富集并支持死体积补偿。

**Architecture:** 纯 PLC(CODESYS ST,经 codesys MCP);host 零改动。方向 `spot_band_dir` 为 PLC 内部状态;`/4?` 查询从 step 26 搬出为标志驱动并行块;step 40/42 回程删除。与 spot-end-position 计划共用 GVL 变量 `Sampling_band_end_position`(该计划 Task 3 被本计划吸收)。

**Tech Stack:** CODESYS ST + codesys MCP(list_pous / read_pou / write_pou / compile / save)。

## Global Constraints

- Spec 真源:`docs/superpowers/specs/2026-07-14-band-edge-artifacts-design.md`(v3 §3)+ `2026-07-14-spot-end-position-design.md`(§3.5)。
- 前置:CODESYS 打开 20260702.project、codesys MCP 可用(`codesys_status` 先行;上机换手前先杀旧版 codesys-mcp Node 进程)。
- **host 写 `Sampling_band_end_position`=0 时判终语义与旧 `pos <= 5` 等价**;E+B 重构不改变阀极性(TRUE=点样头)、泵站位符持有/释放契约、462/465 错误码语义。
- 兄弟风格:GVL 无 pragma;新局部变量加在父 POU VAR 区既有 `spot_band_*` 组;注释中文。
- compile 0 errors;警告不高于基线。
- 本计划只做 PLC;host 侧(spot-end-position Task 1/2)先行完成并已离线绿。
- ⚠️ 本改动集未下装前,真机不得以新 host 发 N>5(旧固件空转 60 程报 462);符号 XML 重导出与 `Sampling_clean_mode` 同批。
- 提交信息结尾:`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

---

### Task 1: A62 步链重构(单一改动集)

**Files:**
- Modify(CODESYS 经 MCP):`Sampling_band_*` 所在 GVL;A62 单条带点样 POU(`Application/50_action/Sampling_L2` 下,特征:`spot_band_step` CASE + 注释"A62 单条带点样 — 模型B ②")。
- Modify: 本计划与 `2026-07-14-spot-end-position.md`(勾选其 Task 3)。

**Interfaces:**
- Consumes: host 每次派发写入的 `Sampling_band_run_instruction`(`A{N}R`)与 `Sampling_band_end_position`(INT 步数,builder 无条件重写,无陈旧)。
- Produces: A62 新步链(0/10/12/15/20/24/30/32/34/36/38/70/80/90);GVL 新增 `Sampling_band_end_position: INT`。

- [ ] **Step 1: 基线读取与定位**

`codesys_status` 确认工程;`codesys_list_pous` 定位 GVL 与 A62 POU;`codesys_read_pou` 读 A62 全文,与 spec §2 时序逐字核对(step 26 判终 `spot_band_pos <= 5`、step 40/42 回程、TON[10] 200ms)。同时读一个兄弟错误路径(如 A20)确认"错误时停轴"的既有 idiom(xMoveAbs := FALSE 写法)。若基线与预期不符,停下报告差异,不要继续。

- [ ] **Step 2: GVL 新增变量**

在 `Sampling_band_dry_cycles` 声明后追加(无 pragma):

```iecst
Sampling_band_end_position: INT;   (* 单条带点样: 活塞终点目标步数(死体积补偿); 0=打到底; 判终 pos<=N+5 *)
```

- [ ] **Step 3: 父 POU VAR 区新增局部变量**

在既有 `spot_band_*` 变量组后追加:

```iecst
spot_band_dir: BOOL;            (* 蛇形方向: TRUE=正向 start->end; 每程翻转; step0 置 TRUE *)
spot_band_query_active: BOOL;   (* /4? 并行查询在途 (发T起 至 有效响应/超限) *)
spot_band_query_done: BOOL;     (* 本程查询已解析有效, spot_band_pos 可用; step38 消费 *)
```

- [ ] **Step 4: A62 主体重写**

头注释与整段 CASE 按下文替换(收尾 70/80/90 逐字保留;解析 WHILE 逻辑逐字搬入并行块):

```iecst
(* A62 单条带点样 — 模型B ③(E+B): 蛇形双向液体程 + 到位即停泵起吹干(去驻留), /4? 查询并行化
   spec: 2026-07-14-band-edge-artifacts v3 §3 + 2026-07-14-spot-end-position §3.5
   每程: A{N}R 供液 -> 按 dir 扫线到位 -> 发T即起吹干leg1(反向离开停点), /4?+沉降200ms+解析并行
   -> dry_cycles 周期(每周期2 leg, 终点=本程停点) -> step38 判终: pos<=Sampling_band_end_position+5
   收尾, 否则 dir 取反从当前端直发下一程 (回程 step40/42 已删)。
   死锁纪律不变: xMoveAbs 置位步与 done 原子消费步一一配对; 泵站位符 发T起持有至 /4? 有效响应。
   保险: 单带最多60程(462); 查询无效重试5次(465, 新增停轴)。 *)
TON[10](IN := spot_band_q_sent, PT := T#200MS);
Sampling_L2_Step := spot_band_step;

(* —— /4? 并行查询块: 与轴运动同周期跑; 泵站位符 在此释放 —— *)
IF spot_band_query_active THEN
    IF %MW1300 = 0 AND NOT spot_band_q_sent THEN
        接收字符 := '';
        转发转存 := '/4?$R';
        %MW1300 := LEN(STR:=转发转存);
        spot_band_q_sent := TRUE;
    END_IF
    IF TON[10].Q THEN
        spot_band_q_sent := FALSE;
        spot_band_pB := ADR(接收字符);
        spot_band_pos := 0;
        spot_band_pos_valid := FALSE;
        spot_band_k := 0;
        WHILE spot_band_k <= 60 DO
            IF (spot_band_pB[spot_band_k] = 16#2F) AND (spot_band_pB[spot_band_k + 1] = 16#30) THEN
                EXIT;
            END_IF
            spot_band_k := spot_band_k + 1;
        END_WHILE
        IF spot_band_k <= 60 THEN
            spot_band_k := spot_band_k + 3;
            WHILE (spot_band_pB[spot_band_k] >= 16#30) AND (spot_band_pB[spot_band_k] <= 16#39) DO
                spot_band_pos := spot_band_pos * 10 + (BYTE_TO_INT(spot_band_pB[spot_band_k]) - 48);
                spot_band_pos_valid := TRUE;
                spot_band_k := spot_band_k + 1;
            END_WHILE
        END_IF
        IF spot_band_pos_valid THEN
            (* /4? 有效响应已完整归属本事务，此时才允许释放共享泵总线。 *)
            泵站位符 := FALSE;
            spot_band_query_retry := 0;
            spot_band_query_active := FALSE;
            spot_band_query_done := TRUE;
        ELSE
            (* 无效/未完整响应不能当作"未到目标"；保持占位并重查。 *)
            spot_band_query_retry := spot_band_query_retry + 1;
            IF spot_band_query_retry > 5 THEN
                泵站位符 := FALSE;
                spot_band_query_active := FALSE;
                点样轴6XDATE.xMoveAbs := FALSE;   (* 查询失败时轴可能在吹干 leg 中: 停轴 *)
                上样吹气自动 := FALSE;
                上样点样三通电池阀自动 := FALSE;
                Sampling_L2_ErrorCode := 465;
                spot_band_step := 0;
                bActionError := TRUE;
            END_IF
        END_IF
    END_IF
END_IF

CASE spot_band_step OF
    0:
        IF NOT spot_band_velocity_saved THEN
            spot_band_old_6x_velocity := 点样轴6XDATE.fVelocity;
            spot_band_velocity_saved := TRUE;
        END_IF
        IF Sampling_band_dry_cycles < 1 THEN
            Sampling_band_dry_cycles := 1;
        END_IF
        点样轴6XDATE.xMoveAbs := FALSE;
        点样轴7YDATE.xMoveAbs := FALSE;
        上样点样三通电池阀自动 := FALSE;
        上样吹气自动 := FALSE;
        spot_band_q_sent := FALSE;
        spot_band_pass_count := 0;
        spot_band_query_retry := 0;
        spot_band_dir := TRUE;
        spot_band_query_active := FALSE;
        spot_band_query_done := FALSE;
        IF Sampling_band_spot_speed > 0.0 THEN
            点样轴6XDATE.fVelocity := Sampling_band_spot_speed;
        END_IF
        点样轴6XDATE.fAbsTarget := Spot_6X_StartTarget;
        点样轴7YDATE.fAbsTarget := Spot_7Y_Target;
        点样轴6XDATE.xMoveAbs := TRUE;
        点样轴7YDATE.xMoveAbs := TRUE;
        spot_band_step := 10;
    10: (* 到起点(原子消费两轴 done); 第1程恒正向 *)
        IF 点样轴6XDATE.bAbMoveDone AND 点样轴7YDATE.bAbMoveDone THEN
            点样轴6XDATE.xMoveAbs := FALSE;
            点样轴7YDATE.xMoveAbs := FALSE;
            spot_band_step := 12;
        END_IF
    12: (* 发一程供液 A{N}R (泵朝目标N), 阀->点样头, 气ON; 程数保险; 蛇形下头已在本程起点 *)
        IF %MW1300 = 0 AND NOT 泵站位符 THEN
            spot_band_pass_count := spot_band_pass_count + 1;
            IF spot_band_pass_count > 60 THEN
                Sampling_L2_ErrorCode := 462;
                bActionError := TRUE;
                spot_band_step := 0;
            ELSE
                上样点样三通电池阀自动 := TRUE;
                上样吹气自动 := TRUE;
                泵站位符 := TRUE;
                spot_band_query_done := FALSE;
                转发转存 := Sampling_band_run_instruction;
                %MW1300 := LEN(STR:=转发转存);
                spot_band_step := 15;
            END_IF
        END_IF
    15: (* A{N}R 已送出 -> 按 dir 起本程扫线 (点样速) *)
        IF %MW1300 = 0 THEN
            IF Sampling_band_spot_speed > 0.0 THEN
                点样轴6XDATE.fVelocity := Sampling_band_spot_speed;
            END_IF
            IF spot_band_dir THEN
                点样轴6XDATE.fAbsTarget := Spot_6X_EndTarget;
            ELSE
                点样轴6XDATE.fAbsTarget := Spot_6X_StartTarget;
            END_IF
            点样轴6XDATE.xMoveAbs := TRUE;
            spot_band_step := 20;
        END_IF
    20: (* 扫线到位 【唯一写者/唯一消费】 *)
        上样点样三通电池阀自动 := TRUE;
        上样吹气自动 := TRUE;
        IF 点样轴6XDATE.bAbMoveDone THEN
            点样轴6XDATE.xMoveAbs := FALSE;
            spot_band_q_sent := FALSE;
            spot_band_query_retry := 0;
            spot_band_step := 24;
        END_IF
    24: (* E核心: 停泵 /4T -> 启动并行查询, 立即转吹干(不在停点驻留) *)
        上样点样三通电池阀自动 := TRUE;
        上样吹气自动 := TRUE;
        IF %MW1300 = 0 THEN
            转发转存 := '/4T$R';
            %MW1300 := LEN(STR:=转发转存);
            spot_band_query_active := TRUE;
            spot_band_dry_count := 0;
            spot_band_step := 30;
        END_IF
    30: (* 吹干 leg1: 反向离开本程停点 (吹干速); T送达前后余液被运动摊开 *)
        上样点样三通电池阀自动 := TRUE;
        上样吹气自动 := TRUE;
        IF Sampling_band_dry_speed > 0.0 THEN
            点样轴6XDATE.fVelocity := Sampling_band_dry_speed;
        END_IF
        IF spot_band_dir THEN
            点样轴6XDATE.fAbsTarget := Spot_6X_StartTarget;
        ELSE
            点样轴6XDATE.fAbsTarget := Spot_6X_EndTarget;
        END_IF
        点样轴6XDATE.xMoveAbs := TRUE;
        spot_band_step := 32;
    32:
        IF 点样轴6XDATE.bAbMoveDone THEN
            点样轴6XDATE.xMoveAbs := FALSE;
            spot_band_step := 34;
        END_IF
    34: (* 吹干 leg2: 回本程停点 (= 蛇形下一程起点) *)
        上样点样三通电池阀自动 := TRUE;
        上样吹气自动 := TRUE;
        IF Sampling_band_dry_speed > 0.0 THEN
            点样轴6XDATE.fVelocity := Sampling_band_dry_speed;
        END_IF
        IF spot_band_dir THEN
            点样轴6XDATE.fAbsTarget := Spot_6X_EndTarget;
        ELSE
            点样轴6XDATE.fAbsTarget := Spot_6X_StartTarget;
        END_IF
        点样轴6XDATE.xMoveAbs := TRUE;
        spot_band_step := 36;
    36:
        IF 点样轴6XDATE.bAbMoveDone THEN
            点样轴6XDATE.xMoveAbs := FALSE;
            spot_band_dry_count := spot_band_dry_count + 1;
            IF spot_band_dry_count >= Sampling_band_dry_cycles THEN
                spot_band_step := 38;
            ELSE
                spot_band_step := 30;
            END_IF
        END_IF
    38: (* 判终等待: 头已停回本程停点, 等并行查询解析 (正常吹干时长>>查询, 不驻留) *)
        上样点样三通电池阀自动 := TRUE;
        上样吹气自动 := TRUE;
        IF spot_band_query_done THEN
            spot_band_query_done := FALSE;
            IF spot_band_pos <= Sampling_band_end_position + 5 THEN
                spot_band_step := 70;
            ELSE
                spot_band_dir := NOT spot_band_dir;
                spot_band_step := 12;
            END_IF
        END_IF
    70: (* 收尾: 带气到清洗位 -> 关气 -> 复位 *)
        上样点样三通电池阀自动 := TRUE;
        上样吹气自动 := TRUE;
        点样轴6XDATE.fAbsTarget := HMI_点样轴6X.position[1];
        点样轴6XDATE.xMoveAbs := TRUE;
        spot_band_step := 80;
    80:
        IF 点样轴6XDATE.bAbMoveDone THEN
            点样轴6XDATE.xMoveAbs := FALSE;
            点样轴7YDATE.fAbsTarget := HMI_点样轴7Y.position[1];
            点样轴7YDATE.xMoveAbs := TRUE;
            spot_band_step := 90;
        END_IF
    90:
        IF 点样轴7YDATE.bAbMoveDone THEN
            点样轴7YDATE.xMoveAbs := FALSE;
            上样吹气自动 := FALSE;
            上样点样三通电池阀自动 := FALSE;
            IF spot_band_velocity_saved THEN
                点样轴6XDATE.fVelocity := spot_band_old_6x_velocity;
                spot_band_velocity_saved := FALSE;
            END_IF
            Sampling_Spray_sample_OK := TRUE;
            spot_band_step := 0;
            bActionDone := TRUE;
        END_IF
END_CASE
```

实施对照注意(写入前逐项核对基线,以基线为准):变量/信号名以 read_pou 读出的为准
(如 `点样轴6XDATE`、`泵站位符`、`接收字符`、`HMI_点样轴6X.position[1]` 等,勿凭本计划
拼写盲写);若基线错误路径 idiom 与 Step 1 所读兄弟 POU 不同(如停轴需先减速或有专用
abort 位),错误路径按兄弟 idiom 改写并在 worklog 记录差异。

- [ ] **Step 5: 不变量自检(写入后 read_pou 重读 diff)**

逐项核对 spec v3 §6:
1. `泵站位符`:step 12 置 TRUE → 并行块有效响应/465 超限才置 FALSE;中途无其它写者。
2. N=0 时判终 `pos <= 0 + 5` 与旧 `pos <= 5` 等价。
3. 462:step 12 程数保险逐字保留;465:重试超限含停轴+关气关阀。
4. dry_cycles 语义:每周期 2 leg,终点 = 本程停点;`< 1` 钳到 1 保留。
5. step 0 复位集含 `spot_band_dir`/`spot_band_query_active`/`spot_band_query_done`。
6. xMoveAbs 置位步与 done 消费步一一配对(0/10, 15/20, 30/32, 34/36, 70/80, 80/90),无双写者。
7. step 40/42 已不存在;除 A62 与 GVL 外无其它 POU 变化。

- [ ] **Step 6: 编译保存**

`codesys_compile` → Expected: 0 errors,警告不高于基线;`codesys_save`。

- [ ] **Step 7: 勾选两计划复选框并提交仓内痕迹**

勾选本计划 Task 1 与 `2026-07-14-spot-end-position.md` Task 3(被吸收):

```bash
git add docs/superpowers/plans/2026-07-14-band-edge-eb.md docs/superpowers/plans/2026-07-14-spot-end-position.md
git commit -m "feat(plc): A62 蛇形+去驻留重构 — 液体程双向/回程删除/查询并行化, 判终 pos<=Sampling_band_end_position+5 (compile 0 errors)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: 收尾 — spec 状态戳与上机清单

**Files:**
- Modify: `docs/superpowers/specs/2026-07-14-band-edge-artifacts-design.md`(状态戳)

- [ ] **Step 1: spec 落状态戳**

状态行更新为已实施 + 提交号 + 上机 pending:
1. 固件下装(与 spot-end-position、`Sampling_clean_mode` 同批;⚠️ 未下装前禁发 N>5);
2. 符号 XML 重导出同批;
3. 板面对比验证(40mm/s 同参数前后照片,§4 判据);
4. 第 1 程起点残余评估 → 必要时 S 补丁(§3.3)。

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-07-14-band-edge-artifacts-design.md
git commit -m "docs(sampling): band-edge E+B spec 落实施状态戳 + 上机4项清单

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
