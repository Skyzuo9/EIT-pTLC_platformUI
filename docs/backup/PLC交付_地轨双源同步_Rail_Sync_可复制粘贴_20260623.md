# PLC 交付（复制粘贴版）— 地轨 11Y 双源同步收编 `Rail_Sync`

> 日期：2026-06-23 ｜ 面向：PLC 工程师（汇川 InoProShop / CODESYS）｜ 当前 PLC 事实源：MCP 直读 `eit_ptlc/plc/20260622.project`
>
> **落地状态（2026-07-01 MCP 复核）**：本文全部 PLC 代码已在当前 `.project` 中确认 —— `Rail_Sync` POU、5 同步变量（`Rail_Pos_Target`/`Rail_Pos_HMI`/`Rail_Sync_Req/Ack/Src`）、派发器改读 `Rail_Pos_Target[Rail_Target_Position]`、步骤 5 防御兜底（`fTgt` 校验 + `ErrorCode:=102`），以及 `PLC_MainPRG` 中 `Rail_Sync()` 无条件调用 / `Rail_L2()` 运行态调用。MCP 编译结果 `0 errors`、32 个既有 `INT -> WORD` warning。现场仍需核对运行 PLC 与当前工程一致，并按验收清单跑单动作。HMI 按钮 + 首次种子值见 [HMI交付_显示改读Target与地轨双源同步按钮_20260624](HMI交付_显示改读Target与地轨双源同步按钮_可复制粘贴_20260624.md)。
> ⚠️ 事实源基准：当前实现状态以 MCP 直读 `.project` 为准；本文保留的 `Now.xml` 行号只作历史定位线索。如下文与工程不符，**按 POU 名 + 符号搜索为准**（`Rail_L2`/`Rail_Sync`/`Host_Computer` GVL）。
>
> **增量进度（2026-06-24 下午）**：发现「PLC 重启后 `Rail_Pos_Target` 归 0 → 派发器把 0 当目标移到底端」的隐患（无自动 push 时）。**PC 侧已根治**：`rail.move` 下发前即时 `ensure_target_confirmed`（写 `Rail_Pos_Target[]` + **回读确认**，复用 `write_block_confirmed` 与 `plc_write` 同原语），确认失败即拒绝/报错不下发——免 retain / 启动 push / 重连钩子（见 `points_service.ensure_target_confirmed` + `executor._exec_plc_l2`，rail_sync 离线测试 8 绿）。`push_sync` 也改走回读确认；`mirror_synced` 判据由 `Req==IDLE` 纠正为 `Ack==DONE`（避免 POU 未就绪时误报「已同步」）。**PLC 侧 [步骤 5](#步骤-5--派发器加目标有效性保护防御加固) 防御加固已由 2026-07-01 MCP 复核确认仍在当前工程内**（旧行号 `Rail_L2` @4760-4769：`fTgt<=0 或 >3000 → ErrorCode:=102` @4763，绝不移到 0 端）。同步变量**确认保持易失**（握手量上电须归 0/IDLE，勿 retain）。
> 用法：**本文每个代码块照抄即可编译**。原理与决策见 [点位双源同步设计_模式分工与地轨收编_20260623.md](点位双源同步设计_模式分工与地轨收编_20260623.md)（D-A〜D-E 已拍板）。配套上位机改动（`rail.yaml` 加 value、PC 侧 diff/push/pull）见同一轮 PC 提交，与本文同契约。
>
> 承接前作 [PLC交付_伺服B方案_可复制粘贴_20260623.md](PLC交付_伺服B方案_可复制粘贴_20260623.md)（连续轴 B 方案 + `Rail_L2` 派发器已落地）。本文只增量收编**地轨坐标真源**，**不重复** B 方案那 5 步。

---

## 0. 这次到底改什么（一句话）

把地轨自动派发器**唯一读坐标的那一行**从读 HMI 示教槽 `HMI_地轨轴11Y.position[]` 改成读 **PC 拥有的 flat 数组** `Rail_Pos_Target[]`；再建一个**专用同步 POU `Rail_Sync`** 当 PC↔HMI 的对账桥（OPC 只暴露 flat 数组，PLC 内部替 PC 碰 struct）。2026-07-01 MCP 复核已确认当前工程采用该形态。

> **为什么这样**：地轨真值原本归 HMI、自动直接读它 → HMI 在自动控制环里（用户最在意要根治的耦合）。经 MCP 直读当前工程复核，自动**只有这一处**读坐标，故收编 = 一行改 + 一个桥，成本远小于旧「最后批次」叙事。索引召回语义（位2=拍照…）**完全保留**——仍按 `Rail_Target_Position` 索引数组。

---

## 1. 单写者 / 守恒不变式（设计红线，违反即代差复发）

| 量 | 唯一写者 | 说明 |
|---|---|---|
| `Rail_Pos_Target[1..6]` | **仅 PC** | 自动运行真源（派发器读）；PUSH 的源。PLC **绝不**回写它（写了就多出第二写者，单写者破）。 |
| `HMI_地轨轴11Y.position[1..6]` | HMI 面板 / `Rail_Sync` 的 PUSH 段 | 手动示教**工作副本**（retain）。PUSH 覆盖它是**安全**的（只覆盖副本）。自动链路**永不读它**。 |
| `Rail_Pos_HMI[1..6]` | **仅 PLC**（`Rail_Sync` 每扫描镜像） | HMI 教值的**只读 flat 镜像**，供 PC 做 diff/pull（PC 经 OPC 碰不了 struct）。 |

**PUSH**（`Target→position[]`）= 纯 PLC 内存拷贝，POU 独立完成，**任一侧（PC/HMI）触发都行**。
**PULL**（收现场教值成真源）= 要写 `points.yaml` **且** 重算 `Rail_Pos_Target` → **只有 PC 能做**。`Rail_Sync` 对 PULL 只当**邮箱**把请求亮给 PC，**绝不**自己写 `Rail_Pos_Target`。

---

## 2. 总览：4 步收编 + 1 步防御（全部在真机工程内手加）

| 步 | 动作 | 位置 | 性质 |
|---|---|---|---|
| 1 | GVL `Host_Computer` 新增 5 个变量（2 数组 + 3 邮箱 INT） | `Host_Computer` GVL | 粘贴声明 |
| 2 | 派发器改 1 行：读 `Rail_Pos_Target[]` 取代 `position[]` | `Rail_L2` POU [:4760](../eit_ptlc/plc/Now.xml#L4760) | 改 1 行（+注释） |
| 3 | 新建 `Rail_Sync` POU（镜像 + 同步邮箱） | `50_action` 文件夹 | 新建 POU |
| 4 | 主程序**无条件段**挂 `Rail_Sync()`（每扫描，**非**运行态） | `PLC_MainPRG` 无条件段 | 加 1 行调用 |
| 5 | 派发器加目标有效性保护（`fTgt<=0` 拒绝, `ErrorCode:=102`） | `Rail_L2` POU `action_code=10` 段 | 防御加固（2026-06-24 增补） |

> 步骤 1–4 是 0623 收编主体，步骤 5 是 0624 增补的防御加固——**全部已由 MCP 直读确认在当前 `.project` 内**。是否已下载到现场运行 PLC、动作是否闭环，仍需现场验收。详见 [步骤 5](#步骤-5--派发器加目标有效性保护防御加固)。

> ⚠️ 与 `Rail_L2()` 不同：`Rail_L2()` 只在「运行」态调度；`Rail_Sync()` 须**每扫描无条件**执行（手动示教、PC 在非运行态做 diff/push 都要它跑）——与 B 方案的 ActPos 5 行镜像放同一处（`CASE MODE_State OF` 之前）。

---

## 步骤 1 — GVL `Host_Computer` 新增 5 个变量

在 `Host_Computer`（与现有 `Pump_L2_*` / `Rail_L2_*` 同处）末尾粘贴。类型与上位机 [plc_nodes.yaml](../eit_ptlc/config/plc_nodes.yaml) 一一对应（LREAL=Double、INT=Int16）。

```iecst
	// ===== 地轨 11Y 双源同步 (Rail_Sync POU; struct 离散位 PC<->HMI 对账) =====
	Rail_Pos_Target : ARRAY[1..6] OF LREAL;  // 仅 PC 写: 6 站点真源运行值 (派发器读 + PUSH 源); PLC 绝不回写
	Rail_Pos_HMI    : ARRAY[1..6] OF LREAL;  // 仅 PLC 写: 每扫描镜像 HMI position[] (PC 做 diff/pull 读, 不碰 struct)
	Rail_Sync_Req   : INT;   // PC 或 HMI 写: 0=空闲 1=PUSH 2=PULL
	Rail_Sync_Ack   : INT;   // PLC 写 (PULL 完成段由 PC 写): 0=空闲 1=完成 2=待PC提交 3=拒绝(限位)
	Rail_Sync_Src   : INT;   // 请求方写: 1=PC 2=HMI (审计 + 防误触)
```

> **OPC 暴露**：5 个变量须像 `Pump_L2_*` / `Rail_L2_*` 一样进「标签通讯 / 符号配置」并下载。两个数组按 `ARRAY[1..6] OF LREAL` 整体导出符号（上位机 OPC 客户端把它当 6 元 LREAL 数组整体读/写，已在 `Tank_State[8]` 等数组节点验证可行）。建完用 OPC 客户端 browse 核对 5 个全部出现、数组维度=6。

---

## 步骤 2 — 派发器改 1 行（[Now.xml:4760](../eit_ptlc/plc/Now.xml#L4760)）

在 `Rail_L2` POU 的 `0:(* IDLE *)` 分支内，**搜索锚点** `地轨轴11YDATE.fAbsTarget`。

改前：
```iecst
				地轨轴11YDATE.fAbsTarget := HMI_地轨轴11Y.position[Rail_Target_Position];
```
改后（**仍按位码索引数组，索引召回 / 「位2=拍照」语义不变**）：
```iecst
				地轨轴11YDATE.fAbsTarget := Rail_Pos_Target[Rail_Target_Position];
```

顺手把 `Rail_L2` POU 顶部注释里的过时句更正（不影响编译，纯文档自洽）：

改前：
```iecst
   按位置码移地轨: Rail_L2_ActionCode=10 -> 移到 HMI_地轨轴11Y.position[Rail_Target_Position] (1..6).
   地轨真值仍在 HMI 槽 (legacy 召回不变); 本派发器仅加上位机独立触发通道.
```
改后：
```iecst
   按位置码移地轨: Rail_L2_ActionCode=10 -> 移到 Rail_Pos_Target[Rail_Target_Position] (1..6, PC 真源).
   地轨坐标真源已收编为 PC 写的 Rail_Pos_Target[]; HMI position[] 降为手动示教工作副本, 自动不再读它.
```

> 仅此一行是「自动运行值」的来源切换。除此之外 `Rail_L2` 派发器时序（Start 上升沿→RUNNING→bAbMoveDone→DONE）**一字不动**。

---

## 步骤 3 — 新建 `Rail_Sync` 同步 POU

### 3.1 新建 POU
工程树 `Application/50_action` 文件夹下，新建 **Program** 类型 POU，命名 `Rail_Sync`（与 `Rail_L2` / `Pump_L2` 同级）。

### 3.2 声明区（粘贴到 `Rail_Sync` 的 VAR 段）
```iecst
PROGRAM Rail_Sync
VAR
	i : INT;
END_VAR
```

### 3.3 程序体（粘贴到 `Rail_Sync` 的 ST 编辑区）
```iecst
(* 地轨 11Y 双源同步桥 (非动作派发器, 是 PC<->HMI 点位对账工具).
   原理: HMI_地轨轴11Y.position[] 是单 ExtensionObject struct, OPC 逐成员读写不可行
         -> 让 PLC 当桥, OPC 只暴露 flat 数组 (复用 *_ActPos 镜像同套路).
   每扫描无条件执行 (挂 PLC_MainPRG 无条件段, 与 ActPos 镜像同处; 勿放运行态 CASE).
   守恒: PUSH 纯 PLC 内存拷贝, 任一侧可触发; PULL 写真源恒为 PC, HMI 触发=请 PC 提交. *)

// (1) 常开镜像: HMI 教值 -> flat 只读镜像 (PC 经此读做 diff/pull, 不直访 struct)
FOR i := 1 TO 6 DO
	Rail_Pos_HMI[i] := HMI_地轨轴11Y.position[i];
END_FOR

// (2) 同步邮箱
CASE Rail_Sync_Req OF
	1:  (* PUSH: PC 真源 Rail_Pos_Target[] -> HMI 工作副本 position[] (PLC 写自己 struct, 无 OPC 限制) *)
		FOR i := 1 TO 6 DO
			HMI_地轨轴11Y.position[i] := Rail_Pos_Target[i];
		END_FOR
		Rail_Sync_Ack := 1;     (* 完成 *)
		Rail_Sync_Req := 0;     (* 清请求 *)

	2:  (* PULL: 收现场教值回真源. PLC 写不了 yaml, 更不可碰 Rail_Pos_Target (单写者=PC).
	          -> 仅亮邮箱待 PC 提交. PC 轮询见 Req=2 -> 读 Rail_Pos_HMI[] -> 限位校验/diff/确认
	             -> 写 points.yaml + 重算并写 Rail_Pos_Target[] -> 由 PC 置 Req:=0,Ack:=1 (失败 Ack:=3). *)
		Rail_Sync_Ack := 2;     (* 待 PC 提交 (PC 接手后由 PC 改写 Ack/Req) *)
END_CASE
```

> `Rail_Sync_Src` 由请求方写、供审计/防误触，POU 不分支于它（仅记录谁发起）。
> PULL 分支 PLC 只置 `Ack:=2` 后**不再动** `Req`/`Ack`——交还 PC，避免 PLC 与 PC 在 PULL 段抢写（握手单向移交）。

---

## 步骤 4 — 主程序无条件段挂 `Rail_Sync()`

与 B 方案 ActPos 5 行镜像同处：[PLC_MainPRG](../eit_ptlc/plc/Now.xml#L10049) 的 `PLC_Pump_泵管理();` 之后、`CASE MODE_State OF` 之前的**无条件周期段**，在 ActPos 5 行镜像后加一行：
```iecst
Rail_Sync();   // 地轨双源同步: 每扫描镜像 position[]->Rail_Pos_HMI[] + 处理 PUSH/PULL 邮箱
```

> **不要**放进 `EN_功能块状态.运行:` 块（那是 `Rail_L2()` 的位置）。同步要在手动示教 / 非运行态也跑。

---

## 步骤 5 — 派发器加目标有效性保护（防御加固）

> **2026-06-24 增补，2026-07-01 MCP 复核确认仍在当前工程内**（旧行号 `Rail_L2` @[4760-4769](../eit_ptlc/plc/Now.xml#L4760)，下方代码留作改动记录）。PC 侧已做「移动前即时写-回读确认」根治隐患；本步是 **PLC 侧 defense-in-depth**——PC 离线 / 旧版兜不到时，PLC 自己也**绝不把 0（未初始化默认 / 重启归零）当目标移到底端**。与步骤 2 同处（`Rail_L2` 的 `0:(* IDLE *)` 分支 `action_code=10` 段）。

### 5.1 局部变量加 1 行（`Rail_L2` 的 VAR 段）
```iecst
	fTgt : LREAL;   (* 取出的目标坐标, 移动前校验用 *)
```

### 5.2 把 `IF Rail_L2_ActionCode = 10 ... END_IF` 整块替换为
```iecst
IF Rail_L2_ActionCode = 10
   AND Rail_Target_Position >= 1 AND Rail_Target_Position <= 6 THEN
	fTgt := Rail_Pos_Target[Rail_Target_Position];     (* PC 真源坐标 *)
	IF fTgt <= 0.0 OR fTgt > 3000.0 THEN
		(* 兜底: PC 未 push / 重启后 Rail_Pos_Target 归 0 / 越限 → 拒绝, 绝不移到 0 端 *)
		Rail_L2_ErrorCode    := 102;   (* 目标未初始化或越限 *)
		Rail_L2_Retryable    := TRUE;
		Rail_L2_CompletedSeq := Rail_L2_AcceptedSeq;
		Rail_L2_State        := 30;    (* REJECTED *)
	ELSE
		Rail_L2_SafeState        := 0;
		地轨轴11YDATE.fAbsTarget := fTgt;
		地轨轴11YDATE.xMoveAbs   := TRUE;
		Rail_L2_State            := 10; (* RUNNING *)
	END_IF
ELSE
	Rail_L2_ErrorCode    := 101;   (* 未知动作码 / 非法位置码 *)
	Rail_L2_Retryable    := TRUE;
	Rail_L2_CompletedSeq := Rail_L2_AcceptedSeq;
	Rail_L2_State        := 30;    (* REJECTED *)
END_IF
```

> **错误码**：新增 **102 = 目标未初始化或越限**（101 仍是动作码/位置码非法）。上位机据此区分「PLC 没拿到坐标」与「位置码错」。
> **哨兵边界**：用 `fTgt <= 0.0` 当「未初始化」。地轨 min 限位=0.0，故 **若将来有工位真示教在 0（home 端）会被误拒**；现役 6 站点均 168/350/500/600，无 0，安全。要支持「0 也合法」则改用 `Rail_Pos_Valid : BOOL`（PC push 确认后置位、PLC 校验它）取代 `<=0` 判定。
> 上限 `3000.0` 与 `rail.yaml` 各点 `limits.max` 一致；若限位改动，此处同步。

---

## PC ↔ PLC 同步时序契约（PC 侧如何驱动，无新 PLC 逻辑）

恒定权威方向：**PC = 真源；`position[]` = 工作副本**。三操作经 `Rail_Sync_Req/Ack` 邮箱轮询完成：

| 操作 | PC 动作 | PLC（`Rail_Sync`）动作 | 安全性 |
|---|---|---|---|
| **diff** | 读 `Rail_Pos_HMI[]` ↔ `rail.yaml.value` 逐点算偏差 | 只是每扫描刷新 `Rail_Pos_HMI[]` | 只读，安全 |
| **PUSH** | 写 `Rail_Pos_Target[]` ← `rail.yaml.value` → 置 `Src`=1、`Req`=1 → 轮询 `Ack`=1 | 拷 `Target→position[]`，置 `Ack:=1,Req:=0` | 安全（只覆盖副本） |
| **PULL** | 置 `Src`=1、`Req`=2 → 见 `Ack`=2 → 读 `Rail_Pos_HMI[]` → 限位校验（失败置 `Ack:=3`）→ diff+二次确认 → 写 `rail.yaml` + 写 `Rail_Pos_Target[]` → 置 `Req:=0,Ack:=1` | 置 `Ack:=2` 后交还 PC | **危险**：写真源，须 diff+确认+限位前置 |

> HMI 按钮（现场触发 PUSH=`Req:=1,Src:=2`；PULL=`Req:=2,Src:=2`）**照同协议后续接线**，本轮先锁变量 + POU + PC 侧。HMI 发起 PUSH 时 PLC 自完成；HMI 发起 PULL 时同样亮 `Ack:=2` 等 PC 提交。

---

## 真机验收清单

- [ ] **步骤1**：`Host_Computer` 5 个新变量建成，OPC browse 全可见；`Rail_Pos_Target`/`Rail_Pos_HMI` 数组维度=6
- [ ] **步骤2**：[4760](../eit_ptlc/plc/Now.xml#L4760) 已改读 `Rail_Pos_Target[Rail_Target_Position]`；`Rail_L2` 派发时序未动；顶部注释已更正
- [ ] **步骤3**：`Rail_Sync` POU 编译通过；镜像段 + PUSH/PULL CASE 完整
- [ ] **步骤4**：`PLC_MainPRG` 无条件段已挂 `Rail_Sync();`（**不在**运行态块）
- [ ] **步骤5**：`Rail_L2` `action_code=10` 段已加 `fTgt` 校验；`fTgt<=0`/越限走 `ErrorCode:=102` REJECTED；合法值仍 RUNNING；编译通过
- [ ] **镜像活性**：HMI 手轮教任一站点 → 上位机读 `Rail_Pos_HMI[该位]` 实时跟随
- [ ] **PUSH**：上位机写 `Rail_Pos_Target[]` + 置 `Req=1` → HMI 面板 `position[]` 显示变为 PC 真值，`Ack` 回 1、`Req` 回 0
- [ ] **自动取数**：上位机 `rail.move(1..6)` → 派发器读 `Rail_Pos_Target[位码]` 移动到位（确认自动**不再**依赖 `position[]`）
- [ ] **重启兜底**（步骤5）：手动把 PLC `Rail_Pos_Target` 清 0（或重启 PLC 不 push）→ `rail.move` 应被拒绝（`ErrorCode=102`），**不**移到底端；PC 侧因移动前即时 `ensure_target_confirmed`，正常 `rail.move` 仍直接成功
- [ ] **PULL**（PC 侧 UI 就绪后）：现场教 → 置 `Req=2` → `Ack=2` → PC 校验/确认 → 写真源 + 回 `Ack=1`；越限路径回 `Ack=3` 拒绝
- [ ] **单写者核对**：确认全工程无任何 POU 回写 `Rail_Pos_Target[]`（除 PC）；`Rail_Sync` 的 PULL 段未碰 `Rail_Pos_Target`/`Req`/`Ack`（仅置 `Ack:=2`）

---

## 附：改动文件 / POU 索引

| POU / 位置 | 改动 |
|---|---|
| `Host_Computer` GVL | +5 变量（`Rail_Pos_Target[6]` / `Rail_Pos_HMI[6]` / `Rail_Sync_Req/Ack/Src`）（步骤1） |
| `Rail_L2` POU [:4760](../eit_ptlc/plc/Now.xml#L4760) | 1 行改读 `Rail_Pos_Target[]` + 顶部注释更正（步骤2） |
| `Rail_Sync`（新建）`50_action/` | 新 POU：每扫描镜像 + PUSH/PULL 邮箱（步骤3） |
| `PLC_MainPRG` 无条件段 | +`Rail_Sync();` 调用（步骤4） |
| `Rail_L2` POU `action_code=10` 段 | +`fTgt` 目标有效性校验（`<=0`/越限→`ErrorCode:=102` REJECTED）（步骤5，0624 增补） |

> 上位机侧配套（同契约，见 PC 提交）：`plc_nodes.yaml` 声明 5 节点、`rail.yaml` 6 站点加 `value`、`points_service` 实现 rail diff/push/pull + 路由 + 离线测试。
> **0624 增量（PC 侧）**：`points_service.ensure_target_confirmed`（写 `Rail_Pos_Target[]` + 回读确认，不碰邮箱）+ `executor._exec_plc_l2` 移动前即时调用（PLC 重启兜底）；`push_sync` 改走回读确认、`mirror_synced` 判据纠为 `Ack==DONE`；新增 `test_ensure_target_confirmed_writes_only_target`，rail_sync 离线 8 绿。
