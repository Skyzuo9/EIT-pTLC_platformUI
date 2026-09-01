# HMI 交付（执行说明）— 显示/召回改读 `*_Target` ＋ 地轨双源同步按钮 `Rail_Sync`

> 日期：2026-06-24 ｜ 面向：HMI 工程师（汇川 Inovance；InoProShop 工程内 CODESYS 可视化，或独立触摸屏 IT 系列经变量/通讯表）
> PLC 当前事实源：通过 InoProShop/CODESYS MCP 直读 `eit_ptlc/plc/20260622.project`；`Now.xml` / `20260622.Device.Application.xml` 仅作辅助检索或历史行号参考，不再作为当前 PLC 程序权威。
> 原理与决策：[点位双源同步设计_模式分工与地轨收编_20260623.md](点位双源同步设计_模式分工与地轨收编_20260623.md) ｜ [伺服地轨控制_架构与实施计划_20260622.md §6.A](伺服地轨控制_架构与实施计划_20260622.md)
> 配套 PLC 交付：[PLC交付_伺服B方案_可复制粘贴_20260623.md](PLC交付_伺服B方案_可复制粘贴_20260623.md)、[PLC交付_地轨双源同步_Rail_Sync_可复制粘贴_20260623.md](PLC交付_地轨双源同步_Rail_Sync_可复制粘贴_20260623.md)
>
> **本文取代** [backup/HMI交付_路径T_显示召回改读Target_20260623.md](backup/HMI交付_路径T_显示召回改读Target_20260623.md)（旧版只覆盖连续轴改读，本文合并连续轴改读 **＋** 地轨双源同步按钮，是 HMI 侧唯一现行交付）。
>
> ⚠️ 本文是**契约/规格级**说明：HMI 工程源文件不在本仓库，给不了逐行照抄，但每处都点明「改哪个元件、绑到哪个 PLC 变量、谁是唯一写者、怎么验收」。

---

## 0. 上手前先核对（PLC 侧已就绪到什么程度）

2026-07-01 通过 InoProShop/CODESYS MCP 直读当前 `.project` 复核：本文涉及的地轨、拍照 8Y、点样 6X/7Y、上样 4X/3Y、4X 清洗位变量和 POU 已在工程内；工程编译 `0 errors`，仍有既有的 `INT -> WORD` warning。HMI 能 browse / 映射到这些变量的前提仍是**符号已导出并下载到目标**，独立触摸屏场景尤其要核对。

| HMI 要用的 PLC 量 | 容器/POU | MCP/POU 核对位置 | 状态 |
|---|---|---|---|
| `*_Target` / `*_ActPos`（连续轴，§2 用；5Z 除外） | `Host_Computer` GVL | MCP 读 `Host_Computer` + 各 L2 POU | ✅ 工程内已在；独立 HMI 仍需符号 browse 核对 |
| `Rail_Pos_Target[1..6]`（地轨真源，PUSH 源/diff 用） | `Host_Computer` GVL | MCP 读 `Host_Computer` / `Rail_L2` | ✅ |
| `HMI_地轨轴11Y.position[1..6]`（地轨工作副本，§3 教 + 显示） | `HMI_Date` GVL（存量） | 一直在 | ✅ |
| `Rail_Sync_Req / Ack / Src`（同步邮箱，§3 按钮驱动） | `Host_Computer` GVL | MCP 读 `Host_Computer` | ✅ |
| `Rail_Sync` POU（每扫描镜像 + PUSH 拷贝 + PULL 邮箱） | `50_action/Rail_Sync` | MCP 读 POU + `PLC_MainPRG` 调用 | ✅ |
| 地轨派发器改读 `Rail_Pos_Target[位码]` | `Rail_L2` | MCP 读 `Rail_L2` | ✅ |
| `Sampling_4X_WashTarget`（4X 清洗位） | `Host_Computer` GVL + `Sampling_L2` 清洗 step | MCP 读 `Host_Computer` / `Sampling_L2` | ✅ PLC 节点和改读已在；运行期仍需在 `sampling.clean` 前补 PC 下发接线 |
| `Sampling_5Z_Target / ActPos` | `Host_Computer` GVL | MCP 搜索未命中 | ⏳ 仍 pending，HMI 暂维持旧 5Z 读法 |

> **符号导出核对（HMI/PLC 第一项）**：连续轴 24 个新 flat 变量 + 地轨 5 个同步变量（`Rail_Pos_Target/HMI`、`Rail_Sync_Req/Ack/Src`）须像 `Pump_L2_*` 一样进 PLC「标签通讯/符号配置」并下载，HMI 才 browse 得到。若 HMI 是同一 Application 内 CODESYS 可视化（情况 A），多数变量可直接绑 GVL，无需通讯表；若是独立触摸屏（情况 B），必须先在符号表导出。
> **`Rail_Sync()` 调用核对**：`Rail_Sync` 是 program POU，须在 `PLC_MainPRG` **无条件段**（与 `*_ActPos` 镜像同处，**勿放运行态 CASE**）被调用 `Rail_Sync();`。2026-07-01 MCP 直读已确认当前工程内存在该调用；后续只需在下载/真机验收时确认运行工程与当前 `.project` 一致。

---

## 1. 单写者铁律（违反即代差/失控复发，务必遵守）

| 变量 | 唯一写者 | HMI 角色 |
|---|---|---|
| `*_Target`（`Host_Computer`，连续轴） | **只有上位机 PC** | **只读显示/召回**；HMI **绝不写** |
| `*_ActPos`（`Host_Computer`，连续轴） | 只有 PLC（镜像 fActPos） | 只读显示（实际位） |
| `Rail_Pos_Target[1..6]`（`Host_Computer`，地轨真源） | **只有上位机 PC** | **只读显示/diff 比对**；HMI **绝不写** |
| `Rail_Pos_HMI[1..6]`（`Host_Computer`，地轨教值镜像） | 只有 PLC（`Rail_Sync` 每扫描镜像） | （HMI 一般不用；diff 给 PC 用） |
| `HMI_地轨轴11Y.position[1..6]`（`HMI_Date`，地轨工作副本） | HMI 示教链 ＋ `Rail_Sync` 的 PUSH 段 | **唯一主场**：现场手轮/按钮教（retain，断电不丢） |
| `Rail_Sync_Req / Ack / Src`（`Host_Computer`，同步邮箱） | PC 或 HMI 写 Req/Src；PLC 与 PC 写 Ack | 按 §3 协议写（PUSH/PULL 触发） |
| 各连续轴 `HMI_*.position[]`（迁移轴） | （迁移轴上）不再读写 | 显示/召回退役，改读 `*_Target` |

> 两条红线：
> ① **连续轴的"示教"整体迁到上位机点位页**，HMI 对它们退为显示/召回，**不再承担示教**；若保留 HMI 示教按钮且让它写 `*_Target` → PC+HMI 双写 → 代差回来，**禁止**。
> ② **地轨真源 `Rail_Pos_Target[]` 只 PC 写**；HMI 教只改 `position[]`（工作副本），靠 §3 的 PULL 经 PC 复核才回真源。HMI **绝不**直写 `Rail_Pos_Target[]`。

---

# 第一部分 · 连续轴：显示/召回改读 `*_Target`（消代差）

## 2. 改动映射表（逐轴：从读 `position[]` 改为读 flat 节点）

上位机点位页示教写 `*_Target`；HMI 面板对这些轴的**显示/召回也改读 `*_Target`**（实际位读 `*_ActPos`），不再读各轴 `HMI_*.position[槽]`。PC 示教后 HMI 立刻显示同值 → **零代差**。

> **⚠️ 先分清两类轴（否则"操作手册给 1 个值，HMI 却有 8 列示教格"读不通）**：
> - **仿射轴（上样 4X / 上样 Y）**：PC **不存逐列点位**，只存「孔板类型 ＋ 3 个标定点」(`calibration.yaml`)，执行时**按孔实时算**目标写 `*_Target`（一个**随孔切换的当前活目标值**）。所以 `Sampling_4X_Target` **不是右侧 8 列示教格的替代**，它在概念上属于左侧"当前位置/移动位置"那一族**实时单值**显示。→ HMI 4X/3Y 页**右侧 8 列示教格（写入/执行）整体退役**（禁用或隐藏），逐孔示教改走上位机孔板标定页；HMI 只显示当前 `*_Target`（目标）＋ `*_ActPos`（实际）。
> - **离散点轴（点样 6X 起/止、7Y、拍照 8Y、以及 4X 清洗位）**：PC **逐点存**真值，**每个槽位 1:1 对应一个 flat 节点**，可在点位页逐点示教。此类才是"1 槽 ⇄ 1 flat 节点"的直读替换。
> - 左侧 4 框（当前位置/当前速度/移动位置/速度设置 ＋ JOG/回原点）是**手动命令**，归 HMI（mode 门控），本表不动；其中"当前位置"可继续读伺服 struct 或改读 `*_ActPos`（同值）。

| 轴 | HMI 旧读（`HMI_Date`） | 新读·目标值（`Host_Computer`） | 新读·实际位（`Host_Computer`） | 备注 |
|---|---|---|---|---|
| 上样 4X | `HMI_上样轴4X轴.position[列号]` | `Sampling_4X_Target` | `Sampling_4X_ActPos` | **仿射轴**（见上方说明）：右侧 8 列示教格退役；HMI 仅显示当前目标/实际位，不逐列示教。固定工位清洗位另起一行↓ |
| 上样 4X 清洗位 | `HMI_上样轴4X轴.position[9]` | `Sampling_4X_WashTarget` | `Sampling_4X_ActPos` | **离散点**：4X 轴固定工位（非孔，仿射算不出），独立 flat 节点；可逐点示教（点位页）。PLC 节点与清洗 step 改读已落地；还需在 `sampling.clean` 前补 PC 下发接线。 |
| 上样 Y（HMI 标签：打样瓶上料轴3Y） | `HMI_打样瓶上料轴3Y.position[行号]` | `Sampling_3Y_Target` | `Sampling_3Y_ActPos` | **仿射轴**（同 4X）：右侧示教格退役；物理轴名仍是"打样瓶上料轴3Y"，功能即上样 Y |
| 点样 6X 起 | `HMI_点样轴6X.position[2]` | `Spot_6X_StartTarget` | `Spot_6X_ActPos` | 点表维护，可逐点示教（点位页） |
| 点样 6X 止 | `HMI_点样轴6X.position[3]` | `Spot_6X_EndTarget` | `Spot_6X_ActPos` | 同上 |
| 点样 7Y | `HMI_点样轴7Y.position[2]` | `Spot_7Y_Target` | `Spot_7Y_ActPos` | 同上 |
| 拍照 8Y | （原硬编码 420 / 无槽） | `Photo_8Y_Target` | `Photo_8Y_ActPos` | 同上 |
| 上样 5Z | `HMI_上样轴5Z轴.position[1/2]` | `Sampling_5Z_Target` ⏳ | `Sampling_5Z_ActPos` ⏳ | **本轮不动**：PLC 节点待建（pending），等 5Z 批次完成后再切 |

> 这些右值已通过 MCP 直读当前 PLC 工程确认：`Sampling_L2` 读 `Sampling_4X/3Y_Target`、`Spot_6X_*Target`、`Spot_7Y_Target`，`PhotoScrape_L2/A34_cam_相机位` 读 `Photo_8Y_Target`，4X 清洗 step 读 `Sampling_4X_WashTarget`。HMI 这步只是让面板与 PLC 读同一份。

## 2.1 怎么改（按 HMI 形态二选一）

### 情况 A — HMI 是 InoProShop 内 CODESYS 可视化（最可能）
判据：`HMI_Date` 与 `Host_Computer` 同属一个 Application 的 GVL → 可视化直接绑 PLC 变量。
1. 打开显示这些轴位置的**可视化界面**，定位**文本/数值显示元件**。
2. 把变量绑定从 `HMI_Date.HMI_点样轴6X.position[2]` 改为 `Host_Computer.Spot_6X_StartTarget`（目标）或 `Host_Computer.Spot_6X_ActPos`（实际位）。逐轴照 §2 表。
3. **召回/"移到示教位"按钮**：若逻辑读 `position[]`，改读对应 `*_Target`。
4. **示教按钮**（调 `FB_Teach` 写 `position[]`）：对这些轴**删除/禁用**，或改成提示"请在上位机点位页示教"。

### 情况 B — 独立触摸屏（IT 系列，InoTouchPad，经变量/通讯表）
1. 打开**变量表/通讯标签表**，找到映射到各轴 `position[槽]` 的标签。
2. 把标签的 **PLC 源地址/符号**改成对应 `*_Target` / `*_ActPos`（前提：§0 符号已导出）。
3. 画面元件绑定不动（仍绑同名标签），只改"标签→PLC"映射。
4. 触发 `FB_Teach` 的示教按钮：对这些轴禁用。

## 2.2 连续轴不要动（保留 `position[]` 现状）
- 点样 6X `position[1]`（清洗位）、点样 7Y `position[1]`（取板位）、各轴 home/归零 —— 本轮不迁，HMI 照旧读 `position[]`（PLC 派发器亦仍读；若需定位，优先用 MCP 按 POU 名 + `点样轴6X.position[1]` / `点样轴7Y.position[1]` 符号搜索）。
- **例外（本轮迁移，勿与上一条混）**：上样 4X 清洗位 `position[9]` **不在保留之列**——它已迁为独立离散节点 `Sampling_4X_WashTarget`（见上表 ＋ [PLC交付 §步骤6](PLC交付_伺服B方案_可复制粘贴_20260623.md)），HMI 改读该节点、`position[9]` 退役。（保留的是 6X 的清洗位 `position[1]`，与 4X 的 `position[9]` 是两个不同工位。）

> ⚠️ 事实源基准（2026-07-01 修订）：当前 PLC 实现以 MCP 直读 `20260622.project` 为准。本文保留的 `Now.xml` 行号只作旧交付定位线索；若与工程不符，**按 MCP 读 POU 名 + 符号搜索为准**。
- 上样 5Z —— `Sampling_5Z_Target/ActPos` **待建**（pending）；等 PLC 5Z 批次完成后再切，本轮维持读 `position[1/2]`。

---

# 第二部分 · 地轨 11Y：双源同步面板（push / pull / diff 按钮）

> 地轨与连续轴**不同**：它**保留** HMI `position[1..6]` 作手动示教**工作副本**（现场手轮教），但**自动派发器不再读它**——MCP 已确认当前 `Rail_L2` 改读 PC 真源 `Rail_Pos_Target[]`。HMI 与 PC 之间靠 `Rail_Sync` 邮箱做 push/pull/diff 对账。**HMI 这部分是新增面板，不是改读**。

## 3. 邮箱协议（HMI 按钮怎么写）

`Rail_Sync` POU 每扫描做两件事：① 常开把 `position[1..6]` 镜像进 `Rail_Pos_HMI[1..6]`；② 按 `Rail_Sync_Req` 执行 PUSH / 亮 PULL 邮箱。当前工程内的 POU 与 `PLC_MainPRG` 调用已由 MCP 直读确认。

| `Rail_Sync_Req` | 含义 | 谁写 |
|---|---|---|
| 0 | 空闲 | PLC（PUSH 完成自清）/ PC |
| 1 | PUSH（`Rail_Pos_Target[] → position[]`） | PC 或 HMI |
| 2 | PULL（请 PC 把现场教值收成真源） | PC 或 HMI |

| `Rail_Sync_Ack` | 含义 |
|---|---|
| 0 | 空闲 |
| 1 | 完成 |
| 2 | 待 PC 提交（PULL 已亮邮箱，等 PC 接手） |
| 3 | 拒绝（限位越界） |

`Rail_Sync_Src`：1=PC 触发 / 2=HMI 触发（审计 + 防误触）。

### 3.1 HMI「下发(PUSH)」按钮 —— 把 PC 真源刷进面板工作副本（安全）
> 用途：现场想"从 PC 当前真值起教"，或自动跑前让面板显示与自动实际一致。只覆盖工作副本，安全。
```
按下 PUSH 按钮：
    Rail_Sync_Src := 2;        (* HMI 触发 *)
    Rail_Sync_Req := 1;        (* 请求 PUSH *)
(* PLC Rail_Sync 下一扫描即把 Rail_Pos_Target[1..6] 拷进 position[1..6]，
   完成后置 Ack:=1、Req:=0。HMI 可监视 Ack=1 弹"已下发"，再自行清 Src。 *)
```
> 完成后 `position[1..6]` = PC 真值，面板（仍显示 `position[i]`）即同步显示。

### 3.2 HMI「diff(偏差检查)」显示 —— 只读对照，不写任何变量
> HMI 是工程内可视化，可直接引用 `Rail_Pos_Target[i]` 与 `HMI_地轨轴11Y.position[i]`，在可视化表达式里算差并回显（**无 OPC、不写变量**）。
- 每个工位显示一行：`position[i]`（现场教值）、`Rail_Pos_Target[i]`（PC 真源）、`差 = position[i] - Rail_Pos_Target[i]`。
- `|差| ≥ 0.1 mm` 的工位高亮"需确认"。**阈值 0.1 mm 暂在 HMI 硬编码并注释"真源以 `rail.yaml` 的 `sync.diff_threshold_mm` 为准"**（HMI 读不了 yaml，此处轻微重复；3000 mm 行程的 ~0.003%，刻意取紧）。
- 这是"是否提请确认"的**软注意阈值**，与 PULL 的**硬限位拒绝**（0..3000 越界 → Ack=3）是两回事。

### 3.3 HMI「回收(PULL)」按钮 —— 请 PC 把现场教值收成真源（危险，PC 复核才落盘）
> 守恒不变式：PULL 要写 `points.yaml` ＋ 重算 `Rail_Pos_Target` → **只有 PC 能做**。HMI 按 PULL = **"请 PC 提交"**，POU 只亮邮箱，**绝不**自己写 `Rail_Pos_Target`。
```
按下 PULL 按钮（建议先弹二次确认，UI 上比 PUSH 更"沉"）：
    Rail_Sync_Src := 2;        (* HMI 触发 *)
    Rail_Sync_Req := 2;        (* 请求 PULL *)
(* PLC 置 Ack:=2(待 PC 提交)。PC 轮询见 Req=2 → 读 Rail_Pos_HMI[] → 限位校验
   (越界 Ack:=3) → diff + 确认 → 写 rail.yaml + 重算并写 Rail_Pos_Target[]
   → 由 PC 置 Req:=0、Ack:=1。 *)
HMI 监视 Ack：
    =2 → 显示"已提请上位机，请在点位页复核确认";
    =1 → "已收编为真源";
    =3 → "越限被拒，请检查教值".
```
> **二次确认形态 = 按工位**：diff 逐点展示，但确认是整工位（地轨 6 位码一并）一次提交。**真正"写真源 + 复核"恒落 PC 点位页**（PC 屏也能独立发起同一 PULL，不依赖 HMI）。

## 3.4 地轨 HMI 不要动
- `position[1..6]` 的**示教/手轮链路保持原样**（这是工作副本的唯一写入口，retain）。
- 不要新增任何写 `Rail_Pos_Target[]` 的入口。

---

## 4. 验收（自检）

**连续轴（第一部分）**：
1. 上位机点位页对某轴（如点样 7Y）"存值 + 下发" → HMI 面板该轴显示值**立即变同值**（零代差）。
2. 手动 jog 该轴 → HMI 实际位（读 `*_ActPos`）实时跟随。
3. HMI 对这些轴**没有**可写示教入口（或点击提示去点位页）。

**地轨（第二部分）**：
4. 上位机点位页对地轨某工位改真源 → HMI 按 **PUSH** → 面板 `position[该位]` 变为 PC 真值。
5. 现场手轮教某工位 `position[i]` → HMI **diff** 行显示非零差并高亮；上位机点位页 diff 也看到同一差。
6. HMI 按 **PULL** → `Ack=2` 提示"待 PC 提交" → 上位机点位页确认 → `Ack=1`、`rail.yaml` 该工位 `value` 变为教值。
7. 教一个越限值（>3000）→ PULL → `Ack=3` 拒绝，真源不变。

---

## 5. 依赖与遗留

| 项 | 谁 | 状态 |
|---|---|---|
| 24 连续轴 flat 变量 + 5 地轨同步变量进「标签通讯/符号配置」并下载 | 现场/PLC | ⬜ 上真机第一步（§0） |
| 确认 `Rail_Sync()` 已挂 `PLC_MainPRG` 无条件段 | PLC | ✅ MCP 已确认；现场仅需下载一致性/运行验收 |
| 连续轴显示/召回改读 `*_Target`（§2） | HMI | ⬜ 本文 |
| 地轨 push/pull/diff 面板（§3） | HMI | ⬜ 本文 |
| 上样 5Z 节点建好后切 HMI 读 `Sampling_5Z_Target/ActPos` | HMI（待 PLC 5Z 批次） | ⏳ pending |
| 上样 4X 清洗位 HMI 改读 `Sampling_4X_WashTarget`（`position[9]` 退役） | HMI | ⬜ 节点已建；按本文接线与现场验收 |

> ⚠️ **首次种子值（跑自动前必做，非 HMI 但相关）**：当前 `rail.yaml` 6 工位 `value` 全为 `0.0` 占位，真值仍只在 HMI `position[1..6]`。PC 连接后 PUSH/自动会把 `Rail_Pos_Target[]` 写成 0 → 地轨全去原点。**第一次须在上位机点位页对地轨做一次 `diff → pull`**（PLC `Rail_Sync` 已每扫描镜像 `position[]→Rail_Pos_HMI[]`，PC 独立可完成，不依赖 HMI 按钮），把现场教值收成真源；点样 6X/7Y 同理需手动种子（无镜像，照 HMI 屏读值填点位页，或 jog 读 ActPos 存值）。详见 [点位双源同步设计 §5.5](点位双源同步设计_模式分工与地轨收编_20260623.md)。
