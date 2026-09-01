# 待办 — 在 InoProShop 里给 SMC_Interpolator.bAbort 接线 (CFC 图形, 工具改不了)

日期: 2026-07-26
执行方式: **人工 / computer-use 代理操作 InoProShop GUI**
工程: `eit_ptlc/plc/20260702.project`
目标 POU: `Application/30_Ethercat任务/PLC_CNC` (语言 = **CFC**, 非 ST)

> 为什么不能用工具做: `codesys_write_pou` 只能读写 **ST 文本**。`PLC_CNC` 是 CFC 图形程序
> (`codesys_list_pous` 里它的 `has_impl=false` 就是这个意思), 连线必须在 IDE 画布上操作。

---

## 1. 背景 — 这根线要解决什么

2026-07-26 真机跑刮痕标定时: 操作员点了「终止流程」, 上位机 VM 停了、刮刀不动了, **但 8Y 轴
还在不停移动**, 一直跑到 CNC 程序自己走完才归位。

根因: `A40_scrape_刮取` 在 step0 锁存 `CNC启动:=TRUE`, 而 `PLC_CNC` 是**独立 PROGRAM** 每扫描
都在插补。`PhotoScrape_L2` 的 RESET 分支只把 State 置 0 并 RETURN, 清不掉 `CNC启动`。

### 已经做完的部分 (2026-07-26 已改并编译通过, 见本目录同日改动)

| 位置 | 改动 |
|---|---|
| `GVL` | 新增 `CNC_AbortLatch: BOOL;` |
| `PLC_MainPRG` 镜像块尾 | `IF PhotoScrape_L2_Reset THEN CNC_AbortLatch:=TRUE; END_IF` + 闩锁驱动 `CNC停止:=TRUE; CNC启动:=FALSE;` |
| `PhotoScrape_L2` IDLE 受理 | `CNC_AbortLatch := FALSE;` (新动作解除刹车) |

这套已经能停住运动: `CNC停止` → `SMC_Interpolator.bSlow_Stop` 减速停, 且 `CNC启动:=FALSE`
撤掉 `SMC_NCDecoder.bExecute`。

### 那 `bAbort` 还有什么用 —— 请先读完再决定做不做

**这是健壮性增强, 不是必需修复。** `bSlow_Stop` 只是"减速暂停", 插补器内部**保留剩余轨迹**;
`bAbort` 才是"丢弃队列并复位 FB"。

实际影响有限, 因为下一次刮取会以新的 G-code 重新 `bExecute` 上升沿, 译码器重新解码, 旧段
自然被冲掉。所以 **不接 `bAbort` 大概率也不会出问题**。

值得接的场景: 你不放心"中止后插补器里还留着半条旧轨迹"这件事, 想要一个确定性的清空。

⚠️ **风险**: `bAbort` 是**立即中止, 没有减速斜坡**。若在高速插补中直接置 TRUE, 机械冲击比
`bSlow_Stop` 大。所以**不要**简单地把它和 `bSlow_Stop` 接同一个信号 —— 见下面的方案选择。

---

## 2. 两个方案 — 推荐 B

### 方案 A (省事但有冲击风险): `bAbort` 直接接现有的 `CNC停止`

画布上从已有的 `CNC停止` 输入框再拉一根线到 `bAbort` 引脚即可, **不需要任何 ST 改动**。

代价: 中止瞬间 `bSlow_Stop` 和 `bAbort` 同时为 TRUE, FB 内部大概率 `bAbort` 优先 → 立即停,
减速斜坡失效。低速时无所谓, 高速刮取时有冲击。

### 方案 B (推荐): 新增独立信号 `CNC中止`, 由 ST 在**停稳之后**再脉冲

先减速停, 确认轴速≈0, 再清队列 —— 既有确定性又无冲击。

需要配套三处 ST 改动 (这些我能用工具做, 等你决定后说一声):

```pascal
(* GVL 新增 *)
CNC中止: BOOL;          // -> SMC_Interpolator.bAbort; 仅在减速停稳后脉冲, 清插补队列

(* PLC_MainPRG 闸门块, 替换现有闩锁驱动段 *)
IF PhotoScrape_L2_Reset THEN
    CNC_AbortLatch := TRUE;
END_IF
IF CNC_AbortLatch THEN
    CNC停止 := TRUE;
    CNC启动 := FALSE;
    // 三轴都停稳后再清队列 (先减速, 后中止; 避免 bAbort 的无斜坡冲击)
    CNC中止 := (ABS(刮板轴9XDATE.fActVel) < 0.5)
           AND (ABS(拍照轴8YDATE.fActVel) < 0.5)
           AND (ABS(刮板轴10ZDATE.fActVel) < 0.5);
ELSE
    CNC停止 := FALSE;
    CNC中止 := FALSE;
END_IF
```

> 阈值 0.5 mm/s 是占位, 上机看 `fActVel` 停稳时的残留噪声再定。

**本文档剩余部分按方案 B 写。选方案 A 的话跳过 §4, §3 里把变量名换成 `CNC停止` 即可。**

---

## 3. GUI 操作步骤 (InoProShop)

程序路径: `D:/InoProShop/CODESYS/Common/InoProShop.exe`

> ⚠️ **开工前**: 确认没有别的进程正占用共享实例 (后端的 codesys MCP 会话)。
> 上位机侧查 `GET /api/plc/session`, 或直接看 InoProShop 是否已被自动化打开。

### Step 0 — 备份

复制 `eit_ptlc/plc/20260702.project` 到 `20260702.project.bak-cfc-abort`。改 CFC 无法用
文本 diff 复核, 备份是唯一回退手段。

### Step 1 — 打开工程与目标 POU

1. 启动 InoProShop, 打开 `eit_ptlc/plc/20260702.project`
2. 左侧**设备树**依次展开: `Device` → `PLC 逻辑` → `Application` → `30_Ethercat任务`
3. 双击 **`PLC_CNC`**
4. **确认**: 右侧打开的是**图形画布**(方框 + 连线), 不是文本编辑器。若是文本, 说明打开错了 POU

### Step 2 — 定位 SMC_Interpolator 块

画布上找实例名 **`SMC_Interpolator`** 的功能块 (类型名也是 `SMC_Interpolator`)。

它在流水线中段, 上游是 `SMC_SmoothPath`, 下游是 `SMC_TRAFO_Gantry3`。整条链是:

```
SMC_NCDecoder_0 → SMC_CheckVelocities → SMC_SmoothPath → SMC_Interpolator
                → SMC_TRAFO_Gantry3 → SMC_ControlAxisByPos1/2/3 (9X/8Y/10Z)
```

**确认落点正确的标志**: 该块左侧输入引脚**自上而下**依次是

| # | 引脚 | 当前接线 |
|---|---|---|
| 1 | `bExecute` | 已接 (来自 `CNC启动`) |
| 2 | `poqDataIn` | 已接 (上游数据) |
| 3 | **`bSlow_Stop`** | **已接 → 输入框 `CNC停止`** ← 用它当参照物 |
| 4 | `bEmergency_Stop` | 空 |
| 5 | `bWaitAtNextStop` | 空 |
| 6 | `dOverride` | 空 |
| 7 | `iVelMode` | 空 |
| 8 | `dwIpoTime` | 已接 (常数 4000) |
| 9 | `dLastWayPos` | 空 |
| 10 | **`bAbort`** | **空 ← 本次目标** |
| 11 | `bSingleStep` | 空 |
| 12 | `bAcknM` | 已接 |
| 13 | `bQuick_Stop` | 空 |

**`bAbort` = 从 `bSlow_Stop` 往下数第 7 个引脚。** 三个已接的引脚 (`bSlow_Stop` / `dwIpoTime`
/ `bAcknM`) 是可靠的视觉锚点 —— 数不清时按它们校准。

### Step 3 — 放置输入变量框

最省事的做法是**复制现有的 `CNC停止` 框再改名**:

1. 单击选中画布上标着 `CNC停止` 的输入框 (它连着 `bSlow_Stop`)
2. `Ctrl+C` → `Ctrl+V`
3. 把粘贴出来的新框拖到 `bAbort` 引脚左侧的空白处
4. 双击新框的文字, 改成 **`CNC中止`** (方案 A 则保持 `CNC停止` 不改)

若复制粘贴不便, 用菜单插入: 画布空白处右键 → **插入** → **输入** (或工具箱拖 "输入" 元素),
然后双击填变量名。

### Step 4 — 连线

1. 鼠标移到新输入框**右侧的输出小方块**, 光标变成连线状
2. 按住左键拖到 `SMC_Interpolator` 的 **`bAbort`** 引脚, 松开
3. **确认**: 出现一根实线; `bAbort` 引脚左边不再是空的

⚠️ 最容易犯的错: 接到相邻的 `dLastWayPos`(上一个) 或 `bSingleStep`(下一个)。松手后**放大画布
逐字核对引脚名**, 不要只看位置。

### Step 5 — 编译

菜单 **编译** → **生成代码** (或 `F11`)。

**期望**: `0 个错误`。警告数应与改动前一致 (本工程基线约 53 条: `INT→WORD` 隐式转换 + 表达式
复杂, 都是既存的)。

若报 `未知标识符 CNC中止` → §4 的 GVL 声明还没加, 先做 §4 再编译。

### Step 6 — 保存, **不要下装**

`Ctrl+S` 保存工程。**下装由你确认后单独执行**, 本任务到编译通过为止。

---

## 4. 配套 ST 改动 (方案 B 必需)

这三处**可以用 codesys MCP 工具做**, 不必手工:

1. `Application/20_变量Date/GVL` — 在 `CNC_AbortLatch` 旁加 `CNC中止: BOOL;`
2. `Application/40_Man/PLC_MainPRG` — 闸门块按 §2 方案 B 的片段替换
3. 无需改 `PhotoScrape_L2`

顺序建议: **先做 §4 (ST), 再做 §3 (CFC)** —— 否则 CFC 里填的 `CNC中止` 编译时会报未知标识符。

---

## 5. 验证 (下装后, 真机)

分两步, 别一次跑满。

**第一步 — 只验中止, 不刮**
1. 起一个刮痕标定 run, 进到刮取阶段
2. 立刻点「终止流程」
3. **期望**: 8Y **减速停住** (不是跑完剩余 G-code); 停稳后 `CNC中止` 短暂为 TRUE
4. 再启动一次, 确认能正常刮 (说明 `CNC_AbortLatch` 已被新动作解除)

**第二步 — 观察冲击**
中止瞬间听/看有无明显机械冲击。若有, 说明 `bAbort` 早于停稳就触发了 → 调大 §2 里的速度阈值。

**监视手段**: 上位机 `GET /api/photoscrape/axes` 连续轮询看三轴位置是否还在变。

---

## 6. 回退

改坏了直接用 Step 0 的备份覆盖 `20260702.project`。

CFC 改动**没有文本 diff 可查**, 所以备份是唯一手段 —— 别跳过 Step 0。

---

## 7. 相关

- 本次已完成的 ST 侧改动: `A40` 补吸粉电机行 + 中止闩锁三处 (2026-07-26)
- `SMC_Interpolator` 其余悬空输入: `bEmergency_Stop` / `bQuick_Stop` / `bWaitAtNextStop`
  也都没接。本任务只接 `bAbort`, 其余保持现状
- 相关缺陷记录: `plc_photoscrape.yaml:5` 那句「CNC启动/完成 不经 OPCUA」是错的 ——
  符号表里三者都是 `T_BOOL access="ReadWrite"`, 已另行订正
