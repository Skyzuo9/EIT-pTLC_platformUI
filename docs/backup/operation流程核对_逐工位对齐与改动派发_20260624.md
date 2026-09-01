# operation 流程核对 — 逐工位对齐与改动派发单 (2026-06-24)
> **2026-07-01 当前状态修订**：本文件保留为 2026-06-24 的历史派发单，不可直接当作最新执行指令。当前活动目录已是 `03_photoscrape` / `04_collect` / `05_transfer` / `06_robot` / `07_feedlift` / `09_full`；若本文仍出现旧编号路径，按当前目录映射理解。另，上一轮新增的 `*_debug` 裸写 action 已撤回；本轮已通过 MCP 将拍照刮板定位/下压/接粉夹具定位与收集瓶定位改为生产 L2 目标态参数 action，PLC 工程已保存并编译 0 errors，待下载与真机验收。

## 0. 用途与读法 (执行 agent 必读)

这份文档是 **逐工位 grilling 的结论账本 + YAML 改动派发单**。核对目标两条轴线：
1. **流程是否还原** —— 新上位机 operation 对旧机器人 lua (`机器人程序v0.11/HHWS_tjcx2/global.lua` + `src0.lua`) 与旧 PLC (`plc/old_UI-Upper.xml`) 的逐点/握手复刻。
2. **变量/参数如何传入** —— 地轨位、子流程选择、站动作码、样品级变量的绑定方式。

**执行 agent 操作规程**：
- 按改动项 ID 找目标文件，按"改法"精确编辑；**不要**重新推导设计（设计已在本单裁定）。
- 改完把该项状态从 ⬜ 改为 🟦，跑 §1 离线验收命令，全绿后改 ✅(离线)；标 🟨 的留待真机。
- 遵守 §1 全局约定，尤其 **真源 / 冻结生成器** 一条——违反会被下次重生成静默回滚。

---

## 1. 全局约定 (conventions)

- **机器人 operation 真源 = 直接编辑** `eit_ptlc/config/operation/06_robot/*.yaml`。这些文件虽由生成器产出，但生成是"一次性迁移"，产物即现行手改真源。
- **冻结生成器与模板（承重墙）**：**不得重新运行** `eit_ptlc/tools/gen_robot_point_operations.py`。其自校验 (`_branch_body`) **只比对 move 点序列、不校验 `tool_action`**，重生成会**静默抹掉**本单插入的 `rotary-*` 等 tool_action 步骤。模板 `eit_ptlc/config/backup/robot_flows_v2.yaml` 视为冻结存档。见改动项 **G-1**。
- **地轨位参数**：保留**裸整数** `{lit: N}` + 调用点中文注释。位号→工位映射真源 = `eit_ptlc/config/points/plc/rail.yaml`：`1=上样/升降上料(168.0)`、`2=拍照(168.0)`、`3=收集(350.0)`、`4=工具(500.0)`、`5=展开(600.0)`、`6=仓库(600.0)`。**当前 1≡2**（值均 168.0）。不引具名常量（避免多一层 UI↔存储映射）。
- **rotary tool_action 写法**（与现有 `robot_suction_put` 一致）：
  ```yaml
  - op: call
    action: robot.tool_action
    args:
      action: {lit: rotary-down}   # 或 rotary-up
      timeout_ms: {lit: 3000}
    mode: RUN
  ```
  挂吸盘工具时 DO2/DO6 = 翻转气缸：`rotary-up`=DO2:1/DO6:0 等 DI(1)，`rotary-down`=DO6:1/DO2:0 等 DI(2)。**DI 翻到位反馈是驱动层缺口**（rotary 版当前仅超时、无 DI 确认），**不在本单 YAML 范围**，单列驱动跟踪 (见 §3 跨站缺口)。
- **离线验收命令**（每个改动项至少跑一次，应保持全绿）：
  ```powershell
  & E:/Anaconda/envs/platformupper/python.exe -m pytest `
    eit_ptlc/tests/test_robot_point_ops_offline.py `
    eit_ptlc/tests/test_stations_l2_offline.py -q
  ```
  （另：全量 operation 解析 + run_script 引用零缺失，由上述离线套件覆盖。）
- **状态图例**：⬜ 待执行 ｜ 🟦 已执行待验 ｜ ✅ 已验(离线) ｜ 🟨 待真机 T ｜ ⛔ 阻塞。

---

## 2. 架构裁决（GOVERNING — 2026-06-24 grilling 裁定，反向约束下方所有工位项）

operation 分层职责严格切分（裁决 **A + R2**）：

| 层 | 职责 | 约束 |
|---|---|---|
| `06_robot/*` | 纯机器人点位 op（pick/put/feed/tool） | 已纯；是各站的"机器人接口 op" |
| 站 `*_cycle`（`sampling_cycle` / `develop_cycle` / `collect_cycle` / `photoscrape_cycle` / feedlift 上料+下料 cycle） | 拥有本站工艺 + 本站握手 + 在握手点调"接口本站的机器人 op" | **(R2) 每个 cycle 只碰自己站的动作，零跨站动作泄漏** |
| `05_transfer/*` 跨站单体脚本 | **退役（R2）** | 跨站move = 源站 cycle 末 [release + 机器人取板→持板] · 目标站 cycle 首 [retract + 机器人放板 + extend] |
| `09_full/ptlc_full_v2`（顶层 recipe） | 串各 cycle + 地轨move + 持板跨站 | = 业务调度层雏形；样品/缸/并行后续真调度器 |

- **判据**：「同站握手」（板在本站原地放/取，如 sampling place→put→locate）→ 进本站 cycle ✓；「跨站move」（板从 A 站搬到 B 站）→ 纯机器人 op 由两端 cycle 各调一半 + recipe 串。
- **地轨 `rail.move`**＝机器人 transport（非站设备动作）：**默认归 recipe 跨站握手点**（transport=调度层），cycle 假定地轨已到位。（真机可改为 cycle 首步 `rail→本站`；此为我的默认假设，可推翻）
- **新 cycle 文件落位**（遵守「程序洁癖」，已定）：feedlift 两 cycle → 当前落位 `config/operation/07_feedlift/`（`feedlift_load_cycle.yaml` + `feedlift_unload_cycle.yaml`）；其余 cycle 落各自既有站组目录。

**反向影响（下方改动项按此重订；细化随逐站 re-walk）**：
- **LU-1 自然修正**：feedlift 上料 cycle 内序＝`feed_raise → 机器人吸板 → feed_lower → 机器人退`，恰为契约序，LU-1 的时序疑虑随 cycle 化消解。
- **LU-3 → 重订**：`feedlift.unload_ready/unload_bury` 不进 transfer，归新 **feedlift 下料 cycle**（受废板→`unload_ready`→机器人放废料→`unload_bury`）；`transfer_scrape_to_waste` 退役（刮板取板归 photoscrape，废料放板归 feedlift 下料 cycle）。废料 rotary-down 仍随机器人 put op。
- **SP-1 → 重订**：`transfer_feed_to_spotting` 退役；其 `feedlift.feed_raise/lower` 归新 **feedlift 上料 cycle**；spotting 放板归 `sampling_cycle`（单站，**不变**）。
- **LU-2 不变**（rotary-down 仍在 `robot_feed_lift_pick_enter` 内）。
- **问题10 三重 `develop.init` 自然解决**：transfer 退役后那两处 init 消失，`develop_cycle` 内 init 一次。

> 注：§3 上下料已按 R2 重写为最终形（feedlift 两 cycle + transfer 退役）。§4 的 SP-1 仍带 **[R2-REVISE]** 旗标（sampling_cycle 本体不变、transfer 退役部分以 §2 为准）。

---

## 3. 工位：上下料（升降上料 + 废料埋料）

**参考**：旧机器人 `global.lua` → `PL4_Path()`(FID1 升降取料 / global.lua:398)、`PL4_2_Path_Put()`(FID8 放废料 / global.lua:430)；派发表 `src0.lua:15-22`；动作契约 `eit_ptlc/config/actions/05_feedlift/plc_feedlift.yaml`。

**R2 结构**：feedlift 站新增**两个 cycle**（`config/operation/07_feedlift/`）：`feedlift_load_cycle`(上料) + `feedlift_unload_cycle`(下料)；`transfer_feed_to_spotting`/`transfer_scrape_to_waste` 退役。机器人点位 op（`robot_feed_lift_pick_enter/exit`、`robot_suction_put` waste 分支）留 `06_robot`。

**复刻已核对吻合（无需改）**：P5→P21 接近三段速 a100/a30/a10、退出回 P1、feed pick 航点与旧 PL4 逐一一致。

### G-1 ⬜ 冻结生成器与模板
- **目标文件**：`eit_ptlc/tools/gen_robot_point_operations.py`（顶部 docstring）、`eit_ptlc/config/backup/robot_flows_v2.yaml`（文件首行）。
- **改法**：各加醒目注释：
  > 【冻结·勿运行】生成的 `config/operation/06_robot/*.yaml` 现为**手改真源**。重运行本生成器会**静默抹掉**手插的 `tool_action`（rotary 等，自校验只比 move 点）。如确需重生成：须先把全部手改并回模板、并扩展生成器支持 tool_action 插入，再运行。
- **验收**：注释存在即可（不影响离线套件）。
- **状态**：⬜

### LU-1 ⬜ 新建 feedlift_load_cycle（上料；契约时序内建）
- **新建文件**：`eit_ptlc/config/operation/07_feedlift/feedlift_load_cycle.yaml`，`resources: [station:feedlift, robot]`。
- **本体序**（自然契约序，消解原"raise/吸/lower/退先后"疑虑）：`feedlift.feed_raise` → `run_script robot_feed_lift_pick_enter`（rotary-down→降 P21→suction-on）→ `feedlift.feed_lower`（5mm 让位）→ `run_script robot_feed_lift_pick_exit`（退回 P1，机器人持板）。
- **依据**：契约 `feed_raise→[吸]→feed_lower→[退]`（plc_feedlift.yaml:3）；旧 PL4 `WaitValue(==1)`(presented)→吸→`WaitValue(==2)`(raise/退)（global.lua:398）。
- **地轨**：`rail→位1` 由 recipe 调用前置（默认 transport 归 recipe）。
- **验收**：离线 pytest 绿；真机确认 raise 后取料高度对、feed_lower 让位足够。
- **状态**：⬜

### LU-2 ⬜ 取料入口补 rotary-down
- **目标文件**：`eit_ptlc/config/operation/06_robot/robot_feed_lift_pick_enter.yaml`
- **改法**：在 `then:` 块内、入口 `require_anchor P1` **之后**、`move_to_point P5` **之前**，插入一个 `tool_action {action: rotary-down, timeout_ms: 3000}`（写法见 §1）。
- **依据**：旧 `PL4_Path` 取料前首步 `DO(6,1);Wait(200);DO(2,0)` 等 `DI(2)` = 把吸盘翻下再去 P21 吸料（global.lua:402）。新流程缺此朝向复位，首循环/异常恢复后可能以错误朝向撞 P21。
- **用户确认**：需保证吸盘翻下才能吸取硅胶板。
- **验收**：离线 pytest 绿；真机确认翻下到位后再吸。
- **状态**：⬜

### LU-3 ⬜ 新建 feedlift_unload_cycle（下料）+ 废料 rotary-down
- **新建文件**：`eit_ptlc/config/operation/07_feedlift/feedlift_unload_cycle.yaml`，`resources: [station:feedlift, robot]`。前提：机器人已持废板（recipe 从 photoscrape 取板交来）。
- **本体序**：`feedlift.unload_ready`（升轴到放废料位）→ `run_script robot_suction_put(waste)`（rotary-down→降 P22→suction-off→退）→ `feedlift.unload_bury`（埋料至光电消失）。
- **目标文件 2**：`eit_ptlc/config/operation/06_robot/robot_suction_put.yaml`（**waste 分支**）：入口 `require_anchor P1` **之后**、`move_to_point P5` **之前**，插 `tool_action {action: rotary-down, timeout_ms: 3000}`。
- **依据**：旧 `PL4_2_Path_Put`（global.lua:430）落板前 `DO(6,1);DO(2,0)` 等 `DI(2)`、`Xp_vac(0)` 放料；契约下料 `unload_ready(21 到放废料位)→[放]→unload_bury(22 埋料至光电消失)`（plc_feedlift.yaml:5,9）。
- **地轨**：`rail→位1` 由 recipe 前置（位1≡位2，物理可达）。
- **验收**：离线 pytest 绿；真机确认升轴到位接料 + 埋料至光电消失。
- **状态**：⬜

### LU-4 ⬜ 退役 transfers + 改 recipe（ptlc_full_v2）
- **退役**：`transfer_feed_to_spotting.yaml`、`transfer_scrape_to_waste.yaml`（标弃用，保留 git 历史）。
- **改 recipe** `eit_ptlc/config/operation/09_full/ptlc_full_v2.yaml`：
  - 上料段：`transfer_feed_to_spotting` + `sampling_full` → `rail.move(1)` + `feedlift_load_cycle` + `sampling_cycle`。
  - 下料段：`transfer_scrape_to_waste` → photoscrape 侧取废板（见 §6 `photoscrape_cycle`）→ `rail.move(1)` + `feedlift_unload_cycle`。
- **验收**：离线 pytest 绿（无悬空 run_script 引用、`transfer_*` 不再被顶层引用）。
- **状态**：⬜

### LU-5 ✅ 地轨位参数化（已决，无改动）
- **裁决**：裸整数 `{lit: N}` + 调用点注释保留；不引具名常量。位号→工位见 rail.yaml（1=上样/升降上料、2=拍照…）。
- **状态**：✅

---

## 4. 工位：上样（sampling）

**参考**：旧机器人 `global.lua` → `PL2_Path()`(FID2 点样放板 / global.lua:321)；动作契约 `eit_ptlc/config/actions/01_sampling/plc_sampling.yaml`。

**根因**：`sampling_full` 被写成自洽单段（含放板定位），但顶层又用 `transfer_feed_to_spotting` 单独放了一次板 → `place_axis`/`place_locate` 各跑两遍、机器人放板没插进唯一一段上样序列（与收集站缺口 A5 同型）。

### SP-1 ⬜ 新建 sampling_cycle（交错放板）+ 退化 transfer + 弃用 sampling_full
> **[R2-REVISE]** `sampling_cycle` 本体不变（单站合规）。但「保留 transfer_feed_to_spotting 做取料-only」被 §2 推翻：该 transfer 退役，其 `feedlift.feed_raise/lower` 归 **feedlift 上料 cycle**，机器人持板经 recipe 交给 `sampling_cycle`。
- **新建文件**：`eit_ptlc/config/operation/03_sampling/sampling_cycle.yaml`
  - `resources: [station:sampling, robot]`（现在内含机器人放板调用）。
  - body 按契约序交错（尊重既有 sampling_full 顺序，仅把机器人 put 插进 `place_axis`↔`place_locate` 缝）：
    `sampling.init` → `pump.vacuum_on` → `sampling.clean` → `sampling.place_axis` → **`run_script robot_suction_put(spotting)`**（其内含缺口B占位，见 SP-3）→ `sampling.place_locate` → `sampling.prep` → `sampling.aspirate {source_x:1, source_y:1}` → `pump.vacuum_off` → `sampling.push_spot_targets` → `sampling.spot`。
  - 顶部注释标注"单带退化；多带由上层带循环包裹本 cycle（按带改 source_x/y + spot_*_target 后 push+spot），见 SP-2"。
- **编辑** `eit_ptlc/config/operation/05_transfer/transfer_feed_to_spotting.yaml`
  - **删除**末段放板（现行第 18–21 行：注释「上样备料…」+ `sampling.place_axis` + `robot_suction_put(spotting)` + `sampling.place_locate`）。保留升降取料段（`rail.move(1)` → `pick_enter` → `feed_raise` → `pick_exit` → `feed_lower`）与第 17 行「相机标定占位」（属取料后标定占位，非缺口B，留原处）。退化后语义=把板从升降取来、机器人持板停 P1。
- **编辑** `eit_ptlc/config/operation/09_full/ptlc_full_v2.yaml`
  - 第 13 行 `run_script sampling_full` → `run_script sampling_cycle`（第 12 行 `transfer_feed_to_spotting` 保留，现为取料-only）。
- **弃用** `eit_ptlc/config/operation/03_sampling/sampling_full.yaml`
  - label/注释标「已弃用，保留给 test_stations_l2」（与 `collect_full` 同处理），不从顶层引用。
- **依据**：契约单段时序 `init→clean→place_axis→[放板]→place_locate→prep→aspirate→spot→[取板]`（plc_sampling.yaml:3）。
- **验收**：离线 pytest 绿（run_script 引用 `sampling_cycle` 可解析、`sampling_full` 不再被顶层引用）。
- **状态**：⬜

### SP-2 ✅ 多带循环（本轮不补，已决）
- **裁决**：`sampling_cycle` 本轮**单带退化**（`source_x/y=1`、单组 spot target 字面量）。多带=按样品/配方维度展开，属**上层调度/配方层**：由 wrapping 循环按带改 `source_x/y` + `spot_6x_start/end`/`spot_7y` value 后逐次调 `push_spot_targets`+`spot`（二者本就是原子，天然作循环体）。本轮只把 cycle 写成"可被带循环包裹"形态 + 注释标注。
- **状态**：✅（决议；落地随 SP-1 的注释）

### SP-3 ⬜ 上样放板 2D 相机纠偏占位（缺口 B，钉死注入点）
- **目标文件**：`eit_ptlc/config/operation/06_robot/robot_suction_put.yaml`（**spotting 分支**）
- **改法**：在 spotting 分支 `approach_near` 之后、最终落 `P19` 之前，加一行占位注释：
  `# TODO 缺口B: 2D相机纠偏, 最终落点=P19+视觉偏移[Δx,Δy] 而非定点P19; err==111重试 (复刻PL2 SetReadReg_F32/ReadReg_err)`。
  本轮**不接真实视觉动作**，落点仍为定点 P19。
- **依据**：旧 `PL2_Path` rotary-up(等DI1) → `SetReadReg_F32`(读Xt1a/Yt2b) → `ReadReg_err`(err==111 Pause重拍) → `Path_XP_x_z2D(P4,P19,...,Xt1a,Yt2b)` 带偏移落点 → rotary-down(等DI2)（global.lua:321）。
- **关联**：将来实现复用 `photoscrape` 已落地的 `vision/camera` kind（见跨站缺口）。DI(1)/DI(2) 翻到位确认仍归驱动层缺口。
- **状态**：⬜

---

## 5. 工位：展开（develop）

**参考**：旧机器人 `global.lua` → `PL1_Path(a)`（FID4 放/FID5 取 展缸板 / global.lua:285）；动作契约 `eit_ptlc/config/actions/02_develop/plc_develop.yaml`；PLC 节点 `Tank_State`/`Tank_Drain_Enable`/`Tank_Drain_Done`（plc_nodes.yaml:51-54）。

**复刻已核对吻合（无需改）**：`robot_tank_put`/`robot_tank_pick` 8 缸分支均已含 `rotary-down` + 取=`suction-on`/放=`suction-off`；y/z 偏移（267/-287、330/151/60/20）与旧 PL1 `Path_XP_y` 逐一一致。

### DV-1 ⬜ 新建 develop_cycle（缸接收→显影→排液→出板）+ transfer 退役（R2）
- **新建** `develop_cycle`（04_develop，文件名/资源待定）：拥有展缸全过程 + 缸握手 + 调展缸接口机器人 op（`robot_tank_put/pick`）。本体序：
  受板（机器人已持板，recipe 从 photoscrape 交来）→ `develop.init(tank)` → `develop.plate_retract(tank)` → `robot_tank_put(tank)` → `develop.plate_extend(tank)` → `pump.vacuum_on`/`develop.clean_line(tank)`/`vacuum_off` → `rinse_fill`/`vacuum_on`/`rinse_suction`/`vacuum_off` → `develop.fill(tank)` → **[DV-2 HITL 门 + 排液]** → `develop.plate_retract(tank)` → `robot_tank_pick(tank)` →（持板交回 recipe→photoscrape）。
- **退役** `transfer_scrape_to_tank` / `transfer_tank_to_scrape`：刮板侧取放归 `photoscrape_cycle`，`develop.*` 全部归 `develop_cycle`，地轨move归 recipe。
- **init 去三重**：周期内 `develop.init` 一次（cycle 开头），transfer 退役后另两处 init 消失（解决问题10）。
- **状态**：⬜

### DV-2 ⬜ 显影完成门 + 排液（安全门；双重定位=占位 + 长期需求）
- `develop.fill` 后插 `human` HITL 门：操作员确认「显影到位 + 已排液」后放行，**不静默放行**（防止从满缸抽板毁板）。此门是**长期功能需求＝人工/外部触发排液**，非纯脚手架；将来与自动门并存为两模式。
- 门旁注释钉死自动化：显影门＝vision 液位前沿 + 定时保底；排液＝新建 `develop.drain` poll 原语（执行层：写 `Tank_Drain_Enable[tank]` + 轮询 `Tank_Drain_Done[tank]` + 写 `Tank_State[tank]=0` 释放）。**超出 YAML 范围，单列执行层实现项**（现有 kind 无 poll 原语）。
- **状态**：⬜（HITL 门本轮落地；drain poll 原语 + vision 门后续）

---

## 6. 工位：拍照刮取（photoscrape）

**参考**：旧 `PL5_Path`（子模式）；契约 `plc_photoscrape.yaml:6-9`；`photoscrape_full.yaml`。

**根因**：`photoscrape_full` 只是「光照+刮取工艺」，缺定位/下压/接粉夹具目标态与全部机器人交错（放板/放收集器/取板，散在 dying transfer）。板在刮板 **ping-pong**（展开前 before / 展开后 photo+scrape）；**收集器须在 `locate_cylinder(true)` 与 `press_cylinder(true)` 之间插入**（collect 链 + 换夹爪工具）→ 单体 cycle 在 R2 下被收集器交错劈开。

**裁决（R2）**：photoscrape **不做单体 cycle**，拆成 **3 个站 op**（每个只碰 photoscrape 动作 + 刮板侧机器人 op），由 recipe 与 collect 链交错。

### PS-1 🟦 photoscrape_place（受板）
- **当前文件** `eit_ptlc/config/operation/03_photoscrape/photoscrape_place.yaml`：`cam_x335` → `run_script robot_suction_put(scrape)` → `locate_cylinder(clamped=true)`。
- **用途**：展开前（spotting→scrape）与展开后（tank→scrape）两次到访共用；替代 `transfer_spotting_to_scrape` / `transfer_tank_to_scrape` 的刮板侧。
- **状态**：🟦 已落地；code 32 已改为 `locate_cylinder(clamped)` 目标态，before-photo 释放定位待下载/真机验收

### PS-2 🟦 photoscrape_pick（交板）
- **当前文件** `eit_ptlc/config/operation/03_photoscrape/photoscrape_pick.yaml`：`locate_cylinder(clamped=false)` → `press_cylinder(pressed=false)` → `run_script robot_suction_pick(scrape)` → `retr_stoprot`。`retr_release(51)` 不再作为上位机 action 暴露。
- **用途**：取板去缸（→develop）与取板去废料（→feedlift 下料）共用；替代 `transfer_scrape_to_tank` / `transfer_scrape_to_waste` 的刮板侧。
- **状态**：🟦 已落地，待真机下载/单 action 验收

### PS-3 🟦 photoscrape_process（光照+刮取工艺，折入 photoscrape_full）
- **当前文件** `eit_ptlc/config/operation/03_photoscrape/photoscrape_process.yaml`：`press_cylinder(pressed=true)`（下压夹紧；收集器由 recipe 的 collect 链在 PS-1 之后、本步之前已放入）→ `cam_photopos` → `capture` → `cam_photohome` → `analyze` → 选带(human) → `cnc_path` → 确认(human) → `write_cnc_path` → `{write_pass_z + scrape}×N` → `scrape_finish`。`scrape_finish(41)` 仍是完整刮取收尾复合 action。
- `photoscrape_full` 工艺内容整体折入；6 变量契约 / pass 循环 / 视觉 / human 门保留不变。**`photoscrape_full` 标弃用**（留现有测试）。
- **状态**：🟦 已落地，待真机验证

### PS-4 ⬜ 展开前拍照占位（before 图）
- **现状**：`before_path` 为预置测试图，展开前到访仅 place+pick 过板。
- **本轮**：留占位（注释），before 实拍后续；`analyze` 仍用预置 `before_path`。
- **状态**：⬜

### PS-5 ⬜ recipe 交错（ptlc_full_v2）
- **展开前**：(sampling 交板) → PS-1 place → [before 占位] → PS-2 pick → develop。
- **展开后**：(develop 交板) → PS-1 place → [collect 链放收集器(换夹爪)] → PS-3 process → PS-2 pick → feedlift 下料。
- **退役**：`transfer_spotting_to_scrape` / `transfer_scrape_to_tank` / `transfer_tank_to_scrape` / `transfer_scrape_to_waste`（刮板侧并入 PS-1/PS-2；与 LU-4 / DV-1 协同）。
- **状态**：⬜

---

## 7. 工位：收集（collect）

**参考**：旧 `PL8_Path`(收集子模式 / global.lua:704)、`PL9_Path`(收集瓶 / global.lua:686)；契约 `plc_collect.yaml`；`collect_cycle.yaml`（0624 已建）；设计稿 `docs/收集阶段编排_原子交错与收集瓶链_20260624.md`。

**复刻已核对吻合（无需改）**：`collect_cycle` 的气缸原子交错 `init→[放收集器]→extend→[放瓶]→lift_press→collect→transport_extend→[取瓶]→retract→[取收集器]` 复刻旧 Collection_process「气缸步进↔机器人放瓶/取瓶(FID15/13)」内部同步 ✓（单站，合 R2）。

### CL-1 🟦 collect.clamp/release_clamp 移出 transfer 入 collect_cycle（R2）
- **现状**：`transfer_collector_scrape_to_collect` 内嵌 `collect.clamp`（line 17）、`transfer_collector_collect_to_staging_a` 内嵌 `collect.release_clamp` —— 站动作在 transfer 里，**违反 R2**。
- **改**：`clamp`/`release_clamp` 移入 `collect_cycle`（收集器到 P73 夹具后夹紧 / 取收集器前松夹）；两 collector transfer 降为**纯机器人**（`robot_collect_holder_put/pick` + `robot_scrape_holder_pick` + 地轨）。`collect_cycle` 顶注「勿重复调 clamp（已内嵌 transfer）」失效，改为 cycle 内显式调。
- **状态**：🟦 已执行（clamp/release_clamp 入 `collect_cycle`，两 transfer 退役为纯机器人，待真机 T）

### CL-2 🟦 收集器跨站（刮板接粉夹具→collect P73）按 R2 拆
- 收集器在**刮板接粉夹具**（`scrape-holder`，photoscrape 子夹具）→ 收集 P73 夹具（collect）。跨 photoscrape→collect。接粉夹具已改为 `photoscrape.powder_collector_locator(located)` code 36 生产 L2 目标态；放入刮板夹具后定位，取出前松开。
- **R2**：取收集器自 `scrape-holder` ＝ photoscrape 侧 handoff（`press_cylinder(false)` + `powder_collector_locator(false)` + 机器人）；放 P73 + `clamp` ＝ collect 侧（`collect_cycle`，见 CL-1）。recipe 串。气缸交错 ✓ 不变。
- **状态**：🟦 已接线，待真机验收

### CL-3 ⬜ bottle 链核对（已大体并入）
- `collect_cycle` 已含放瓶/取瓶（`transfer_bottle_staging_b_to_collect` / `collect_to_staging_b`，纯机器人，collect 气缸在 cycle 内括）✓；放瓶后 `collect.bottle_locator(true)`，取瓶前 `collect.bottle_locator(false)`；bottle 预备（rack→staging_b）在 recipe ✓。
- **核对**：成品瓶取走（`staging_b→rack`，`transfer_bottle_staging_b_to_rack`）是否在 recipe 收尾段；`collect_full` 已弃用 ✓。
- **状态**：⬜

---

## 8. 工位：工具快换（tool）

**参考**：旧 `ToolGet_Put()`（global.lua:857）；`robot_tool_put/pick.yaml`；工具态设计稿 `docs/机器人工具态维护_快换防呆与启动对账_20260624.md`。

### TL-1 ✅ tool put/pick 纯机器人（R2-clean，无 YAML 改动）
- `robot_tool_put/pick` ＝ `tool-change-aux-on/off` + `quick-change-release` + `set_mounted_tool`，**纯机器人** ✓。换刀由 recipe 在工具边界插（`ptlc_full_v2` 现 #23-24 卸吸盘挂夹爪 / #34-35 卸夹爪挂吸盘 已在）。
- **状态**：✅

### TL-2 ⬜ 缺口C 工具态维护 ＝ 驱动/执行层收口（R2 定调）
- **现状**：`set_mounted_tool` 原语已存在（put→0 / pick→tool_id）；但无「挂载工具↔tool_action 匹配」强制——错发（吸盘语义发给夹爪、rotary 误当夹爪）无拦截（隐患见记忆）。
- **R2 定调**：operation 层保持声明式，工具态**权威 + 不匹配拦截归驱动/执行层**（非 operation、非 transfer）。实现：驱动持 `mounted_tool`，`tool_action` 校验工具匹配否则报错 + **启动对账**（开机核对实际挂载）。**超出 YAML，执行层实现项**。
- **状态**：⬜（执行层）

### TL-3 ⬜ 流程启动自检 + 工具对账/按需取用（recipe 起手式）
- **背景**：现 `ptlc_full_v2` 顶注**被动假定**「入口须已挂吸盘(slot1)并声明(启动对账)」，无主动自检。旧 `Init()`（src0.lua:40）起手 `MovJ(P1)` + 复位 IO/工具在位标志；`robot_home_check.yaml` 已有但 **DEBUG 模式**（robot.home + robot.query），未进生产 recipe。
- **改（recipe 起手段，加在 `ptlc_full_v2` 最前）**：
  1. **自检**：RUN 模式 `robot.home → robot.query → require_anchor(home/P1)`，确认在原点、无故障（把 `robot_home_check` 升 RUN 或新建 `robot_startup_check`）。
  2. **工具对账**：读**实际**挂载工具（驱动权威，依赖 TL-2 的 get-mounted-tool 原语）。
  3. **按需取用**：首阶段(板处理)需吸盘 slot1；对账 ≠ slot1 → `robot_tool_put(当前) → robot_tool_pick(1)`，已是则跳过。
- **TL-2 依赖**：步 2-3 全自动条件取用依赖 TL-2 挂载工具查询。**本轮 scaffold**：RUN 自检 + HITL 对账门（"确认当前挂载=slot1 吸盘？否则换刀"）；TL-2 落地后转全自动。这也使现顶注的"被动前提"升级为"主动起手式"，与防呆/柔性一致。
- **关键约束（实现时发现）**：`robot.home` 是 `modes:[DEBUG]`，**不能在 RUN 生产 recipe 跑**；且未知态下命令运动不安全。故 RUN 自检=**校验**已在原点（`robot.query` + `require_anchor P1`，**P1 ≡ robot-main.home**），不**命令** home；不在原点则 anchor 失败停流程→维护模式手动 home。`robot.set_mounted_tool` 是 `modes:[]`（RUN 允许），作启动对账声明。
- **[🟦 已落地 scaffold]**：新建 `06_robot/robot_startup_check.yaml`（query + require_anchor P1）；`ptlc_full_v2` 最前插起手段 `robot_startup_check → human confirm(对账门, on_cancel raise) → robot.set_mounted_tool(1)`。离线验收绿。
- **状态**：🟦 已执行（scaffold，待真机 T）；按需全自动随 TL-2

---

## 9. 跨站缺口与执行层项（汇总）
- 缺口A 翻面（rotary）：逐站补 rotary-up/down（LU-2 起步；tank put/pick 已含）；**驱动层补 DI(1)/DI(2) 翻到位反馈**（独立于 YAML）。
- 缺口B 上样 2D 纠偏：占位（SP-3），后实现，复用 vision/camera kind。
- 缺口C 快换工具态维护：v2 顶层至少 2 次快换无人维护工具态；实现层=驱动/执行层收口（R2 下不进 transfer）。
- 显影完成门 + 排液：见 DV-2（HITL 门本轮落地 + `develop.drain` poll 原语后续）。

---

## 10. 执行记录（2026-06-24 workflow `wf_87181aaf-158`）

按工位 fan-out workflow（10 agent）执行：Author 7/7 → Integrate → Validate → Review。**全部 YAML 改动项已落地**。

**已落地（🟦 已执行，待真机 T）**：
- G-1 冻结注释（gen 工具 + 模板）。
- LU-1 `07_feedlift/feedlift_load_cycle.yaml`、LU-3 `feedlift_unload_cycle.yaml`（新建）。
- LU-2 `robot_feed_lift_pick_enter` rotary-down；LU-3 `robot_suction_put` waste rotary-down；SP-3 spotting 缺口B占位注释。
- SP-1 `sampling_cycle.yaml`（新建）。
- DV-1+DV-2 `develop_cycle.yaml`（新建，含 HITL 门，三重 init 消解）。
- PS-1/2/3/4 `photoscrape_place/pick/process.yaml`（新建）。
- CL-1 `collect_cycle.yaml` 解交错（clamp/release_clamp 入 cycle）。
- LU-4/SP-1/DV-1/PS-5 `ptlc_full_v2.yaml` recipe 重写 + 5 个 dying transfer 标 `[已退役 R2]`。
- **TL-3 起手式 scaffold（0624 追加）**：新建 `06_robot/robot_startup_check.yaml`（query + require_anchor P1）+ `ptlc_full_v2` 最前插 `robot_startup_check → HITL 对账门 → set_mounted_tool(1)`。发现 `robot.home`=DEBUG 门控→RUN 自检改为"校验在原点"而非命令 home。

**离线验收**：`pytest test_robot_point_ops_offline` 4 passed；`python -m eit_ptlc.tests.test_stations_l2_offline` 8/8 pass（含 `ptlc_full` 跨工位端到端终态 DONE）。**注**：`test_stations_l2_offline.py` 非 pytest 用例（脚本式，pytest 收集 0），须用 `python -m` 跑——§1 验收命令应据此修正。

**评审（对抗式）findings 处置**：
- ~~MED `photoscrape.init` 拆站后成孤儿~~ → **已修**：`init` 加为 `photoscrape_place` 首步（每访 init，真机验收是否双访去重）。
- ~~LOW 退役 collector transfer 残留 clamp 无注释~~ → **已修**：两文件加 `[已退役 R2]` 注释。
- LOW recipe `photoscrape_process` inputs:{} → sample_id/save_dir/before_path 空（demo 限制，样品维度归后续真调度器，非阻塞，记账）。
- LOW `collect_cycle` 的 bottle transfer 调用树内含 `rail.move`（耗材取瓶须离收集位去仓库，物理必需自带地轨；接受为豁免，记账）。
- LOW DV-2 HITL 门未表达 `Tank_State[tank]=0` 释放（归执行层 `develop.drain` 原语，记账）。

**仍待执行层（非 YAML）**：`develop.drain` poll 原语 + `Tank_State` 释放、工具态拦截+启动对账(TL-2)、rotary DI 反馈(缺口A)、2D 纠偏 vision(SP-3)、展开前 before 实拍(PS-4)。
