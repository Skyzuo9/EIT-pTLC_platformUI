# 上样轻清洗充液 SP-B (PLC 侧) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 CODESYS 工程(真源 `eit_ptlc/plc/20260702.project`)的 Sampling 站动作码 20(清洗)步骤内加 `Sampling_clean_mode=1` 轻清洗分支:entry[1] → Q 空闲 → 切三通→点样 → entry[2] → Q 空闲 → 三通复位→上样 → DONE 锁存;mode=0 路径逐位不变。

**Architecture:** 不加新步骤、不扩数组:复用 `Sampling_clean_instructions[1..2]` 与既有 pumpCmd FB(发送+Q 确认空闲)、既有终态 `IF NOT Start` 锁存契约;唯一新 GVL 变量 `Sampling_clean_mode : INT`(带 symbol 导出 pragma)。三通阀复用点样步骤(动作码 60/62)已在驱动的同一个 DO。

**Tech Stack:** CODESYS ST,经 codesys-mcp 工具(`codesys_status / codesys_list_pous / codesys_read_pou / codesys_write_pou / codesys_compile / codesys_save`)。

## Global Constraints(逐字来自 spec `docs/superpowers/specs/2026-07-14-sampling-light-flush-design.md`)

- FSM 时序(mode=1):`三通→上样位(确保) → 派发 entry[1] → pumpCmd FB Q 确认空闲 → 切三通→点样位 → 派发 entry[2] → Q 确认空闲 → 三通复位→上样位 → 终态锁存 DONE(沿用 IF NOT Start 锁存契约)`。
- mode=0:与现行路径逐位一致,零行为变化(回归风险隔离在分支判断一处)。
- 切阀时机恒在 entry 边界、泵确认空闲之后,不做泵运动中的时序耦合。
- 泵错误(Q 返回错误码)沿既有 clean 错误路径上报,不新增错误通道。
- `Sampling_clean_mode : INT`,0=重清洗(现行),1=轻清洗充液;由 host 每次派发显式写入,PLC 只读不复位。
- ⚠️ 环境前置(memory ptlc-plc-session-takeover-bugs):动工前先杀旧版 codesys-mcp Node 进程,避免混版本锁窗口;确认会话由本机 keeper 持有后再写。
- PLC 工程二进制(`eit_ptlc/plc/20260702.project`)每个 Task 编译零错误后即提交;提交信息结尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`;不推送。

---

### Task 1: 发现与基线锚定(只读,产出命名对照表)

**Files:**
- Read(经 codesys-mcp): Sampling 站 L2 POU(预期名形如 `Sampling_L2`,以 `codesys_list_pous` 实际为准)、Host_Computer GVL、点样步骤(动作码 60/62)所在 POU。
- Create: `docs/superpowers/plans/2026-07-14-flush-plc-worklog.md`(命名对照表,后续 Task 的唯一命名真源)

**Interfaces:**
- Produces: 对照表,必须钉死以下 6 项的**逐字**现名——
  1. Sampling 站 L2 POU 名与动作码 20 分支的定位(CASE 结构/步变量名);
  2. pumpCmd FB 实例名与调用 idiom(如何发送指令字符串、如何判"Q 确认空闲"、错误码如何冒泡);
  3. 三通阀 DO 变量名(点样步骤里"保持三通阀在点样头流路"用的那个;plc_nodes 侧 HMI 名为"上样点样三通电池阀手动/自动",ST 内部另有其名);
  4. 既有点样步骤切阀后是否带 TON 阀行程延时及其时长(轻清洗切阀沿用同款);
  5. 终态 DONE 锁存的逐字 idiom(`IF NOT ..._L2_Start THEN` 锁存块);
  6. 现行 clean(mode=0)如何按 `Sampling_clean_count` 循环消费 `[1]/[2]`(轻清洗分支必须绕开此循环)。

- [ ] **Step 1: 环境检查**

先在任务管理器/`tasklist` 确认无旧版 codesys-mcp Node 进程残留;然后 `codesys_status` 确认工程 = `20260702.project`、会话空闲可接管。
Expected: status 正常,无第二个 CODESYS/MCP 实例。

- [ ] **Step 2: 读 POU 并落对照表**

`codesys_list_pous` → `codesys_read_pou`(Sampling L2 POU / Host_Computer GVL / 点样步骤 POU),把上述 6 项逐字抄进 worklog 文件。
Expected: worklog 六项齐全,无"待定"。若动作码 20 的现行实现与 host 侧注释(内壁/外壁 ×count)对不上,停下向用户报告,不得臆测。

- [ ] **Step 3: Commit(worklog)**

```bash
git add docs/superpowers/plans/2026-07-14-flush-plc-worklog.md
git commit -m "docs(plc): flush PLC 命名对照表 — Sampling L2 clean 步/pumpCmd/三通DO/锁存 idiom 锚定

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: GVL 变量 `Sampling_clean_mode`(带 symbol 导出)

**Files:**
- Modify(经 codesys-mcp): Host_Computer GVL(`Sampling_clean_count` 声明行之后)

**Interfaces:**
- Consumes: Task 1 对照表(GVL 名、pragma idiom——若既有导出变量用 `{attribute 'symbol' := 'readwrite'}` 即同款)。
- Produces: `Sampling_clean_mode : INT;`(OPC UA 可读写,host SP-A 写 0/1)。

- [ ] **Step 1: 写声明**(`codesys_write_pou`,紧邻 `Sampling_clean_count` 之后,pragma 与邻近导出变量逐字同款)

```iecst
	// 清洗模式: 0=重清洗(内/外壁×count, 现行) 1=轻清洗充液(host每次派发显式写, PLC只读不复位)
	{attribute 'symbol' := 'readwrite'}
	Sampling_clean_mode : INT;
```

- [ ] **Step 2: 编译**

`codesys_compile`
Expected: 0 errors, 0 new warnings。

- [ ] **Step 3: Commit**

```bash
git add eit_ptlc/plc/20260702.project
git commit -m "feat(plc): GVL 新增 Sampling_clean_mode — 轻清洗充液模式开关(host显式写, 唯一新增变量)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 动作码 20 步骤内的 mode=1 分支

**Files:**
- Modify(经 codesys-mcp): Sampling L2 POU 动作码 20 分支(Task 1 定位处)

**Interfaces:**
- Consumes: Task 1 对照表全部 6 项;`Sampling_clean_instructions[1..2]`(SP-A 已按 spec §3.2 填充:entry[1]=吸满+充上样流路+冲外壁链式,entry[2]=冲点样头至 A0)。
- Produces: mode=1 时的完整轻清洗时序;mode≠1 时走原路径(原代码一字不动,仅被包进 ELSE 或以 `IF Sampling_clean_mode = 1 THEN ... ELSE 原体 END_IF` 包裹——选改动最小的包裹方式)。

- [ ] **Step 1: 写分支 ST**(以下为**结构模板**,所有 `<占位>` 必须替换为 Task 1 对照表的逐字现名/现 idiom;新增局部相变量 `iFlushPhase : INT;` 声明进该 POU 的 VAR 区)

```iecst
(* 动作码20 清洗: mode=1 轻清洗充液 (spec 2026-07-14-sampling-light-flush §3.3);
   mode<>1 走下方原重清洗路径, 逐位不变 *)
IF Sampling_clean_mode = 1 THEN
	CASE iFlushPhase OF
		0:  (* 确保三通=上样位 (吸液/充液/外壁全程保持) *)
			<三通DO> := <上样位电平>;
			iFlushPhase := 10;
		10: (* 派发 entry[1]: 吸满+充上样流路+冲外壁 (链式原子, 无阀动作) *)
			<pumpCmd实例>(<发送:=Sampling_clean_instructions[1], 按对照表idiom>);
			IF <pumpCmd Q确认空闲/Done> THEN iFlushPhase := 20; END_IF
			IF <pumpCmd 错误> THEN <沿既有clean错误路径置Error>; END_IF
		20: (* 泵空闲后切三通→点样位; 若点样步有TON阀行程延时, 同款同时长 *)
			<三通DO> := <点样位电平>;
			<TON同款延时, 到时> iFlushPhase := 30;
		30: (* 派发 entry[2]: 冲点样头至 A0 *)
			<pumpCmd实例>(<发送:=Sampling_clean_instructions[2], 同idiom>);
			IF <pumpCmd Q确认空闲/Done> THEN iFlushPhase := 40; END_IF
			IF <pumpCmd 错误> THEN <沿既有clean错误路径置Error>; END_IF
		40: (* 三通复位→上样位, 进终态 *)
			<三通DO> := <上样位电平>;
			<按既有 IF NOT Sampling_L2_Start 锁存契约写 DONE/CompletedSeq>;
			iFlushPhase := 0;
	END_CASE
ELSE
	(* ===== 原重清洗路径, 原文一字不动 ===== *)
END_IF
```

硬性要求(缺一即返工):
1. 切阀只发生在 phase 20 与 40,且都在 pumpCmd 确认空闲之后(Global Constraints 第 3 条);
2. mode=1 分支**不进入** `Sampling_clean_count` 循环(count 由 host 恒写 1,但分支逻辑不得依赖它);
3. 错误路径复用既有 clean 的 Error 置位与恢复语义,不新增错误变量;
4. `iFlushPhase` 在进入动作与终态复位两处都归 0(防上次中断残留);
5. 原路径的 diff 必须为零(包裹行除外)。

- [ ] **Step 2: 编译**

`codesys_compile`
Expected: 0 errors, 0 new warnings。

- [ ] **Step 3: 自查 diff**

`codesys_read_pou` 回读,与 Task 1 worklog 里抄录的原文对比:确认 ELSE 侧原文逐字未变、上述 5 条硬性要求逐条勾验,并把勾验结果追记进 worklog。
Expected: 5/5 勾验通过。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/plc/20260702.project docs/superpowers/plans/2026-07-14-flush-plc-worklog.md
git commit -m "feat(plc): Sampling clean 步 mode=1 轻清洗分支 — entry边界Q空闲后切三通, mode=0 原路径零变化

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 保存工程 + 符号导出同步

**Files:**
- Modify: `eit_ptlc/plc/20260702.project`(codesys_save)
- Modify(上机/CODESYS GUI): `eit_ptlc/plc/20260702.Device.Application.xml`(符号导出重出;若 codesys-mcp 无导出能力,此步标记为上机项并告知用户)

**Interfaces:**
- Consumes: Task 2/3 的已编译工程。
- Produces: 含 `Sampling_clean_mode` 的符号导出(真机 OPC UA 服务器暴露该变量的前提)。

- [ ] **Step 1: 保存**

`codesys_save`;确认 `git status` 显示 `.project` 已变更并已在 Task 2/3 提交覆盖(若 save 产生新 diff,补提交)。

- [ ] **Step 2: 符号导出**

在 CODESYS 内确认符号配置包含 `Sampling_clean_mode`(readwrite),重出 `20260702.Device.Application.xml` 到 `eit_ptlc/plc/`。无法脚本化则记为上机项。
Expected: 新 XML 内 `grep Sampling_clean_mode` 命中一行 `<Node name="Sampling_clean_mode" type="T_INT" access="ReadWrite" />`(type 以实际导出为准)。

- [ ] **Step 3: 离线侧确认(host 仓库)**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_plc_symbol_pragma_offline.py -q`
Expected: PASS(纯函数测试,不读工程;此步只是确认符号工具链未被本次改动波及)。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/plc/20260702.project eit_ptlc/plc/20260702.Device.Application.xml
git commit -m "chore(plc): 保存工程并重出符号 XML — Sampling_clean_mode 进符号面

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: 上机联调清单(人工,非代码)

**Files:** 无(结果追记进 worklog 与 memory)。

- [ ] **Step 1: MVP 手动预演**(若用户尚未做):`mvp_staged_clean.py` 方式一分段发送、手动切三通,确认 17/5/3 数字合适;不合适先调 SP-A 默认常量再上全链路。
- [ ] **Step 2: mode=0 回归**:UI 调试坞单发 `sampling.clean`,与改前行为逐项对照(内/外壁×count、DONE 上报、错误路径)。
- [ ] **Step 3: mode=1 全链路**:确认上样针在废液/清洗位、点样头在清洗位(物理前置,PLC 不校验)→ UI 单发 `sampling.flush` → 观察:entry[1] 期间三通不动、entry[1] 完成后才切点样、entry[2] 后复位上样、DONE 正常锁存。
- [ ] **Step 4: 根因闭环验证**:flush 后立即 `sampling.prep + sampling.aspirate`,确认停泵回落/针尖滴液消失(整个项目的成立判据)。
- [ ] **Step 5: 结果记录**:结论(含调整后的体积/速度终值)写回 worklog,并请主会话更新 memory(ptlc-sampling-light-flush)。
