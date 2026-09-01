# HMI 执行说明（汇川 Inovance）— 路径 T：显示/召回改读 `*_Target`（消代差）

> 日期：2026-06-23 ｜ 适用：汇川 Inovance HMI（InoProShop 工程内 CODESYS 可视化，或独立触摸屏 IT 系列经变量/通讯表）
> 关联：[伺服地轨控制_架构与实施计划 §6.A](伺服地轨控制_架构与实施计划_20260622.md) ｜ [PLC交付_伺服B方案_可复制粘贴_20260623.md](PLC交付_伺服B方案_可复制粘贴_20260623.md)
> 状态：待 HMI 工程师执行（与 PLC 次轮"24 变量符号导出 + 5Z 建节点"同步）
>
> ⚠️ 本文是**契约/规格级**说明（HMI 工程源文件不在本仓库，给不了逐行照抄）。它给出：改哪些轴、从读什么改成读什么、单写者铁律、验收口径。

---

## 0. 一句话目标

上位机点位页示教写 `*_Target`；**HMI 面板对这些轴的显示/召回也改读 `*_Target`（实际位读 `*_ActPos`），不再读各轴 `HMI_*.position[槽]`**。这样 PC 示教后 HMI 立刻显示同值 —— **零代差**。

---

## 1. 为什么改（背景，30 秒）

- B 方案让连续伺服目标由 PC 写专用扁平节点 `*_Target`（`Host_Computer` GVL），PLC 自动序列已改读它（PLC 交付步骤 2 已落地）。
- 但 HMI 仍读旧的 `HMI_*.position[槽]`（`HMI_Date` GVL）→ 同一个"被示教的值"存了两份，PC 改了 HMI 不知道 = **代差**。
- 消代差最干净：HMI 改读 PC 写的那一份（`*_Target`），`position[]` 对这些轴退役。
- （**已否决的"不改 HMI"替代**：让 PLC 每扫描把 `*_Target` 抄回 `position[]`——会让 PLC 变 `position[]` 写者、与 HMI 示教双写、HMI 示教被静默覆盖，更脏。故采用本文的 HMI 改读。）

---

## 2. 单写者铁律（务必遵守，否则代差复发）

| 变量 | 唯一写者 | HMI 对迁移轴的角色 |
|---|---|---|
| `*_Target`（`Host_Computer`） | **只有上位机 PC** | **只读显示**；HMI **绝不写** `*_Target` |
| `*_ActPos`（`Host_Computer`） | 只有 PLC（镜像 fActPos） | 只读显示（实际位） |
| `HMI_*.position[]`（`HMI_Date`） | （迁移轴上）不再读、不再写 | FB_Teach 对这些轴停用 |

> 含义：**这些轴的"示教"整体迁到上位机点位页**，HMI 面板对它们退为显示/召回，不再承担示教。若保留 HMI 示教按钮且让它写 `*_Target`，会变成 PC+HMI 双写者 → 代差回来，**禁止**。

---

## 3. 改动映射表（逐轴：从读 position[] 改为读 flat 节点）

| 轴 | HMI 旧读（`HMI_Date`） | 新读·目标值（`Host_Computer`） | 新读·实际位（`Host_Computer`） | 备注 |
|---|---|---|---|---|
| 上样 4X | `HMI_上样轴4X轴.position[列号]` | `Sampling_4X_Target` | `Sampling_4X_ActPos` | 仿射轴：逐孔目标 PC 实时算，HMI 仅显示当前值，不逐孔示教 |
| 上样 Y（打样3Y） | `HMI_打样瓶上料轴3Y.position[行号]` | `Sampling_3Y_Target` | `Sampling_3Y_ActPos` | 同上（HMI 物理轴标签仍是"打样瓶上料轴3Y"，功能即上样Y） |
| 点样 6X 起 | `HMI_点样轴6X.position[2]` | `Spot_6X_StartTarget` | `Spot_6X_ActPos` | 点表维护，可逐点示教（点位页） |
| 点样 6X 止 | `HMI_点样轴6X.position[3]` | `Spot_6X_EndTarget` | `Spot_6X_ActPos` | 同上 |
| 点样 7Y | `HMI_点样轴7Y.position[2]` | `Spot_7Y_Target` | `Spot_7Y_ActPos` | 同上 |
| 拍照 8Y | （原硬编码 420 / 无槽） | `Photo_8Y_Target` | `Photo_8Y_ActPos` | 同上 |
| 上样 5Z | `HMI_上样轴5Z轴.position[1/2]` | `Sampling_5Z_Target` ⏳ | `Sampling_5Z_ActPos` ⏳ | **本轮不动**：PLC 节点待建（pending），等 PLC 5Z 批次完成后再切本轴 |

---

## 4. 怎么改（按 HMI 形态二选一）

### 情况 A — HMI 是 InoProShop 内 CODESYS 可视化（最可能）
> 判据：`HMI_Date` 与 `Host_Computer` 同属一个 Application 的 GVL（见 PLC 工程 `…/Application/GlobalVars/`），说明可视化直接绑定 PLC 变量。

1. 打开对应**可视化界面（Visualization）**，定位显示这些轴位置的**文本/数值显示元件**。
2. 把元件的**变量绑定**从 `HMI_Date.HMI_点样轴6X.position[2]` 改为 `Host_Computer.Spot_6X_StartTarget`（目标）或 `Host_Computer.Spot_6X_ActPos`（实际位）。逐轴按 §3 表。
3. **召回/"移到示教位"按钮**：若其逻辑读 `position[]`，改读对应 `*_Target`。
4. **示教按钮**（调 `FB_Teach` 写 `position[]`）：对这些轴**删除/禁用**，或改为提示"请在上位机点位页示教"。

### 情况 B — HMI 是独立触摸屏（IT 系列，InoTouchPad，经变量/通讯表）
1. 打开工程的**变量表 / 通讯标签表**，找到映射到各轴 `position[槽]` 的标签。
2. 把这些标签的 **PLC 源地址/符号**改成对应的 `*_Target` / `*_ActPos`（前提：这两组 flat 节点已在 PLC「标签通讯/符号配置」导出——见 PLC 交付步骤 1 核对）。
3. 画面元件绑定不动（仍绑同名标签），只改"标签 → PLC"的映射。
4. 触发 `FB_Teach` 的示教按钮：对这些轴禁用。

---

## 5. 不要动（保留 `position[]` + HMI 现状）

- 清洗位 `6X.position[1]`、取板位 `7Y.position[1]`、地轨 `11Y.position[1..6]`、各轴 home/归零 —— **本轮不迁**，HMI 照旧读 `position[]`（见架构 §4.A 后续/最后批次）。
- 上样 5Z —— PLC 节点 `Sampling_5Z_Target/ActPos` **待建**（pending）；**等 PLC 5Z 批次完成后再切本轴**，本轮 5Z 维持读 `position[1/2]`。

---

## 6. 验收（自检，3 条）

1. 上位机点位页对某轴（如点样 7Y）"存值"并"下发" → HMI 面板该轴显示值**立即变为同值**（零代差）。
2. 手动 jog 该轴 → HMI 实际位（读 `*_ActPos`）实时跟随。
3. HMI 上对这些轴**没有**可写示教入口（或点击后提示去点位页）。

---

## 7. 依赖（PLC 次轮，必须先就绪）

1. **24 个 flat 变量**（6 `*_Target` + 5 `*_ActPos` + 13 `Rail_L2_*`）进 PLC「标签通讯/符号配置」并下载 —— HMI 才 browse/映射得到（[PLC交付 步骤1核对](PLC交付_伺服B方案_可复制粘贴_20260623.md)）。
2. **5Z**：`Sampling_5Z_Target/ActPos` 建节点 + step 改读 + fActPos 镜像后，本轴 HMI 再按 §3 切换。
