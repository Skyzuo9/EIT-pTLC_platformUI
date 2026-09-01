# operation 四段式重构审阅与实现计划 (2026-07-01)

更新时间: 2026-07-02

本文只保留后续实现还需要看的内容。历史审计细表见
`docs/operation四段式审计表_20260701.md`；已完成的逐项过程不再在本文展开。

## 1. 核心修正

本轮计划需要修正一个关键口径: **四段式不是只在一个站级 cycle 里用注释标出
prepare/load/execute/unload，而是每个工位任务都要有四个可单独运行的站级单步
operation**。这些单步 operation 本身可以包含 PLC L2、机器人、地轨、泵、相机、
vision 等原子动作和子流程。

后续统一使用以下层级:

| 层级 | 目标 | 示例/约束 |
|---|---|---|
| atomic action | 不可再分的设备动作 | `plc_l2`、`robot.move_to_point`、`camera/vision/pump` 等 |
| robot/helper operation | 可复用点位或转运子流程 | `06_robot/*`、`rail_move_safe`、`transfer_*`; 可隐藏在主列表外, 但供 step 调用 |
| station step operation | 工位四段单步入口 | `{station}_prepare/load/execute/unload`; 可被 UI/调试器单独点跑 |
| station task operation | 工位完整任务入口 | `{station}_cycle`; 只顺序 `run_script` 四个 step |
| recipe | 跨站编排 | 只负责站间顺序、资源和物料交接, 不补齐站内 step 的机器人动作 |

中文阶段名统一为:

```text
prepare: 准备 - 工位复位、资源/目标参数准备、让位到可接收状态
load:    上料 - 样品/耗材进入本站并完成夹紧、定位或交接
execute: 执行 - 本站工艺动作
unload:  下料 - 松开、取出、让位、恢复安全态
```

旧文档和现有 label 中出现的“放料/放板”先按 `load/上料` 兼容理解；新建或改名时优先使用
`load/上料`。

因此，当前四段式架构是合理的，但合理性边界必须说清: 四段式是**站内生命周期语言**，
用于把一个工位任务拆成可审计、可单独点跑、可现场验收的 step；它不是跨站并发调度器。
后一个工位的 `load` 与前一个工位的 `unload` 在物理动作上可能重叠，但这种重叠只能由
中控以跨站 handoff 事务编排，不能靠某个站内 step 自行判断。

## 2. 当前结论

当前可以收口的是 **静态配置与 PLC 工程候选验证**，不能收口的是
**下载后的真实设备闭环**。同时，现有 operation 还没有完全达到“每站 1 个 task + 4 个
可单独点跑 step”的目标。

| 工位/模块 | 当前形态 | 与目标的差距 | 迁移口径 |
|---|---|---|---|
| Collect | `collect_cycle -> collect_prepare/load/execute/unload` 已成型 | 四个 step 仍被标为 hidden/helper | 作为最小试点, 先提升为正式 station step, 不改动作顺序 |
| Sampling | `sampling_cycle -> sampling_prepare/load/execute/unload` 已成型; 旧 `sampling_place_plate/spot/full` 保留兼容 | 静态结构已闭合; 真机单 step 与跨站 handoff 未闭环 | 作为 sampling 试点保留现有动作参数与主入口, 后续只做现场验收和 handoff 编排 |
| Develop | `develop_cycle -> develop_prepare/load/execute/unload` 已成型 | 准备段已承载清洗/润洗/板前预置上液; 执行段收窄为展开等待门 + 排液闭环; 真机单 step 未验收 | 后续只做现场单 action/step/task 验收与跨站 handoff 编排 |
| PhotoScrape | `photoscrape_cycle -> photoscrape_prepare/load/process/unload` 已成型; `photoscrape_before_photo_cycle` 补齐 before 实拍路径 | `photoscrape_load` 已纳入“暂存A接粉收集器 -> 刮板夹具”; before-photo 与 after-develop 回刮板复用 `photoscrape_plate_load`, 不碰接粉收集器 | 不把“仓库 -> 暂存A”补货算作本站动作; 后续再迁移 collect handoff |
| FeedLift/Rail | `feedlift_load_cycle`、`feedlift_unload_cycle` 已有阶段注释; FeedLift 光电兜底已进上位机与候选 PLC; rail 多为 helper | FeedLift 真机下载/单 action 验收未完成, 且仍有两个业务任务 | 分别验收上料取板/废料下料 task; Rail 默认保持 helper |
| `06_robot` | 点位 operation 可复用, 但当前容易被当主入口 | 不应成为站级 task 的外部附录, 也不应淹没主入口 | 作为 station step 内部 `run_script` 子流程库 |

必须继续分清三层验证:

- `validate_script` / 配置自检通过，只证明名称、结构和参数表面合法。
- `.project` 编译 0 errors，只证明工程能编译，不证明已经下载或在线版本一致。
- 真机闭环必须按单 action -> 单 station step -> 单 station task -> 跨站 recipe 逐层验收。

## 3. 命名与 UI 元数据契约

脚本名仍保持全局唯一，四个 step 必须带工位或任务前缀，不使用裸 `prepare.yaml` 之类名称。

目标命名:

```text
{station}_cycle
{station}_prepare
{station}_load
{station}_execute
{station}_unload
```

FeedLift 这类一个物理模块承载两个业务任务的场景，优先使用任务前缀:

```text
feedlift_feed_prepare/load/execute/unload
feedlift_waste_prepare/load/execute/unload
```

建议元数据:

```yaml
ui:
  role: station_task
  station: sampling
  primary: true
  order: 10
```

```yaml
ui:
  role: station_phase
  station: sampling
  phase: load
  primary: true
  order: 12
```

helper/robot/legacy 入口仍保留，但与 station step 区分:

```yaml
ui:
  role: robot_route   # 或 helper / legacy
  hidden: true        # 主流程列表默认隐藏, 编辑器和 run_script 仍可引用
```

UI 层后续应支持按 `station_task / station_phase / helper / robot_route / legacy`
分组或过滤。真正的四段 step 不应再被当普通 helper 隐藏；否则无法满足“可单独点跑”的目标。

## 4. 已实现内容的重新判定

### 4.1 action 层

以下 action 层结论仍有效，后续 step 拆分时继续复用，不因为 operation 重构而删除:

- PhotoScrape 已使用生产 L2 目标态 action 承载双态执行件:
  - `photoscrape.locate_cylinder(clamped)` code 32。
  - `photoscrape.press_cylinder(pressed)` code 33。
  - `photoscrape.powder_collector_locator(located)` code 36。
- Collect 四段已移除 `collect.bottle_locator(located)`；code 24 保留为暂存B瓶板锁动作，待独立补货/回库链承载。
- Develop 已补 `develop.drain` code 50 与 `develop.release_tank` code 51，排液不再依赖 HITL 或 raw output；展开完成判定仍是 HITL/后续 vision 门，板进入前的预置上液属于 `prepare`。
- Sampling 已把 `sampling.aspirate` 调用迁移到 `plate_spec/plate_no/well` 孔位契约，并补入 `sampling.place_release`。

### 4.2 operation 层

原“按四段注释整理”只能算过渡状态，不能算最终完成:

- `collect_cycle` 是当前最接近目标的样板: task wrapper 顺序调用四个 step。
  `collect_execute` 已收拢为 `collect.lift_press -> collect.collect -> collect.transport_extend`,
  即执行段负责进入洗脱姿态、按设定次数洗脱、再退出到取瓶姿态；`collect.bottle_locator`
  仍不属于 Collect 工位四段，留给仓库到暂存的耗材板链路。
- `sampling_cycle` 已改为 `sampling_prepare -> sampling_load -> sampling_execute -> sampling_unload`
  四段 wrapper；`sampling_place_plate`、`sampling_spot`、`sampling_full` 先保留为 hidden/legacy 兼容入口。
- `develop_cycle` 已改成 station task wrapper，顺序调用 `develop_prepare -> develop_load ->
  develop_execute -> develop_unload`；`develop_prepare` 包含初始化、放板缸让位、清洗/润洗和板前预置上液，
  `develop_execute` 仅保留展开完成门与 `develop.drain` 排液闭环；`robot_tank_put/pick` 继续作为子流程复用。
- `photoscrape_cycle` 已改成 station task wrapper，顺序调用
  `photoscrape_prepare -> photoscrape_load -> photoscrape_process -> photoscrape_unload`。
  `photoscrape_load` 包含板放入定位和“暂存A接粉收集器 -> 刮板夹具”; 仓库到暂存A补货不属于本站 step。
  `photoscrape_process` 和 `photoscrape_unload` 均为可见四段 operation，直接由 action / human / robot 子流程组成；
  旧 `photoscrape_place/execute/pick` 保留为 hidden helper，其中 `pick` 只委托正式 `photoscrape_unload`。
- `photoscrape_before_photo_cycle` 是展开前 before-photo 可见路径，顺序为
  `photoscrape_prepare -> photoscrape_plate_load -> photoscrape_before_photo_capture -> photoscrape_unload`。
  其中 capture step 显式调用 `cam_photopos -> capture(filename=before.jpg) -> cam_photohome`,
  并把 `before_path` 输出给后续 `photoscrape_process`。
- `feedlift_load_cycle`、`feedlift_unload_cycle` 先作为两个候选 station task 处理；
  是否各自四段化，要结合真实业务入口和现场调试习惯决定。
- `06_robot/*.yaml` 是点位子流程库。站级 step 内应通过 `run_script` 调用它们，
  不要把机器人点位串重新手写进站级 step。

## 5. 仍未完成的必要内容

### 5.1 PLC 真源与快照关系

提交前必须避免形成两套 PLC 真源:

- 仓库历史主线原本跟踪 `eit_ptlc/plc/20260622.project` 与 `20260622.Device.Application.xml`。
- 本地工作树出现了 `20260702.project` / `20260702.Device.Application.xml`，且 `.mcp.json` 曾指向该候选工程。
- 若要正式切换到 `20260702.project`，需要作为单独决策同步更新 `AGENTS.md`、`.mcp.json`、可检索 XML 与相关文档。
- 若本次不切换，本文和提交说明只能说“PLC 工程候选/本地 MCP 复核”，不能把未跟踪快照写成团队基线。

### 5.2 station step 完整性

每个纳入重构的工位任务必须满足:

- 有 1 个 station task operation 和 4 个 station step operation。
- station task 除 comment 外，只按 `prepare -> load -> execute -> unload` 顺序
  `run_script` 四个 step。
- 四个 step 都可单独 `validate_script`、单独从调试器启动，并声明完整 `resources`。
- 上料/下料 step 必须包含完成该工位交接所需的机器人动作或 helper 子流程；
  不能要求 recipe 额外补动作才算完成工位任务。
- `run_script` 引用必须存在；后续应补 repo 级校验，检查子脚本存在和 inputs/outputs 契约。
- 含机器人动作的 step 必须声明 `robot` 或相应资源，失败时停在可恢复状态。

### 5.3 真机单 action 与单 step 验收

下载 PLC 后优先验收:

| 工位 | action / step | 验收点 |
|---|---|---|
| Sampling | `sampling.place_release` code 33 | 定位气缸真实松开；DONE 时序正确；当前无独立到位反馈，需现场确认风险 |
| Sampling | `sampling.spot_band_layer` code 62 | 到终点发 `T` 停泵；三通阀保持点样头流路；吹气往复干燥；清洗位关气 |
| Develop | `develop.drain` code 50 | 触发目标缸排液，最终到 `Tank_State=99` 或排液完成反馈 |
| Develop | `develop.release_tank` code 51 | 只能在 `robot_tank_pick` 后释放 `Tank_State=0` |
| PhotoScrape | code 32/33/36 true/false | 定位、下压、接粉夹具目标态两侧动作与反馈/延时语义正确 |
| Collect | `collect.bottle_locator` code 24 true/false | 不属于 Collect 工位四段；后续应串在“仓库↔暂存B”独立补货/回库链 |
| Rail/FeedLift | Rail code 10；FeedLift code 11/12/21/22/91 | 真机派发器、伺服动作和机器人交接顺序一致；FeedLift 光电兜底已静态闭合, 现场验收见 5.4 |

新增或改写的 station step 也必须按 `prepare/load/execute/unload` 单独点跑验收，再跑完整
station task。

### 5.4 FeedLift 光电兜底设计合同

本节记录 2026-07-03 讨论形成并实施到静态层的 FeedLift 设计合同。当前状态:

- 上位机已实现 `preload_targets` 解析、执行前块写回读确认、FeedLift 搜索边界点位配置和离线测试。
- 候选 PLC 工程 `eit_ptlc/plc/20260702.project` 已经通过 MCP 保存:
  `Host_Computer` 增加 FeedLift flat target/ActPos/debug 参数, `PLC_MainPRG` 增加 1Z/2Z ActPos
  无条件镜像, `FeedLift_L2/A11/A21/A22` 改为有界 jog + 稳定确认, code 91 增加 DEBUG-only
  光电稳定状态确认。
- CODESYS 编译结果: 0 errors, 32 warnings。warnings 为既有 INT->WORD 隐式转换类告警。
- 尚未完成 PLC 下载、在线版本一致性确认、单 action/单 station task 现场验收。
- 2026-07-03 首次现场联调补充: `feedlift.feed_raise` 已能被 PLC 接受并返回 FeedLift 专用
  `303`。该错误按合同表示搜索 target 非法 (`low >= high`), 与当前
  `eit_ptlc/config/points/plc/feedlift.yaml` 中 1Z/2Z 搜索边界仍为初始 `0.0/0.0`
  一致。下一步先做现场点位种子与上位机 fail-fast, 暂不改 PLC ST。执行计划见
  `docs/FeedLift光电兜底现场联调实施计划_20260703.md`。

问题背景:

- 上下料工位执行成功率受光电不稳定影响。已观察到废料下料时 2Z 因光电漏检继续走向零位，
  人工触发光电后才停止。
- 当前 `FeedLift_L2` 中 `A11_feed_raise`、`A21_unload_ready`、`A22_unload_bury`
  均依赖光电/传感器状态；`A12_feed_lower` 只是 1Z 相对下降 5 mm 并等待
  `bReMoveDone`，不属于本轮光电扫边兜底范围。

边界决策:

- 兜底闭环放在 PLC `FeedLift_L2` 内部；上位机 operation 不拆 1Z/2Z 连续运动细节。
- 生产动作接入范围为 `feedlift.feed_raise` code 11、`feedlift.unload_ready` code 21、
  `feedlift.unload_bury` code 22。`feedlift.feed_lower` code 12 不接入光电扫边，但后续可独立
  增加相对运动完成超时。
- 搜索过程使用有界 jog；绝对点位只作为搜索窗口边界和越界停止条件，不替代光电作为成功判据。
- 成功判据为最终光电状态稳定；边沿存在用于二次确认和诊断。`A11` 最终应稳定为
  `玻璃升降光电开关1 = TRUE`；`A21/A22` 最终应稳定为 `玻璃升降光电开关2 = FALSE`。
- PLC/硬件限位是最终保护；上位机点位只是可调安全余量。PLC 动作开始前仍必须校验 target
  是否落在硬边界内，非法则拒绝进入运动。
- 生产动作搜索/确认失败不允许上位机自动重试；DEBUG 诊断动作可重跑。

点位与下发合同:

- FeedLift 搜索边界是纯上位机管理的 PLC target 点位，不需要 HMI 管理，不做地轨那种
  `sync` 邮箱握手。
- 已新增 `config/points/plc/feedlift.yaml`，以 `plc_servo_target` 管理 4 个点位:
  `feedlift_1z_search_low`、`feedlift_1z_search_high`、`feedlift_2z_search_low`、
  `feedlift_2z_search_high`。
- 已新增 PLC flat 节点/配置声明:
  `FeedLift_1Z_ActPos`、`FeedLift_2Z_ActPos`、`FeedLift_1Z_SearchLowTarget`、
  `FeedLift_1Z_SearchHighTarget`、`FeedLift_2Z_SearchLowTarget`、
  `FeedLift_2Z_SearchHighTarget`、`FeedLift_DebugAxis`、`FeedLift_DebugExpectedFinal`。
- 上位机 action schema 已增加声明式 `preload_targets` 字段。执行器在触发 L2 前自动下发并回读确认
  固定点位，operation 不新增显式 push 步骤。
- 已绑定 action:
  - `feedlift.feed_raise`: preload `feedlift_1z_search_low/high`。
  - `feedlift.unload_ready`: preload `feedlift_2z_search_low/high`。
  - `feedlift.unload_bury`: preload `feedlift_2z_search_low/high`。
  - `feedlift.debug_check_photoelectric_edge`: DEBUG-only, preload 1Z/2Z 全部搜索边界。

PLC 内部动作合同:

- `A11_feed_raise`: 在 1Z 搜索窗口内有界 jog 捕获光电1；200 ms 稳定确认后光电1 TRUE 才 `DONE`。
  到窗口上/下边界仍未确认则 `ERROR`。
- `A21_unload_ready`: 在 2Z 搜索窗口内完成当前“先找光电2、再退出到光电2消失”的接料位逻辑；
  200 ms 稳定确认后光电2 FALSE 才 `DONE`。
- `A22_unload_bury`: 先朝 `feedlift_2z_search_low` 方向 jog，直到光电2消失；到 low 仍未消失则
  朝 `feedlift_2z_search_high` 反向 jog。200 ms 稳定确认后光电2 FALSE 才 `DONE`。
- code 91 / `feedlift.debug_check_photoelectric_edge` 为 DEBUG-only 稳定状态确认:
  参数 `axis` 选择 1Z/2Z, `expected_final` 选择期望光电最终态；该诊断分支不 jog, 不作为生产 operation 步骤。
  若后续需要“诊断动作也主动扫边”, 应作为单独 PLC 小改动扩展, 不混入生产验收结论。

错误码合同:

- 保留 `301` 表示上料前置无玻璃/传感器未就绪。
- 保留 `302` 表示下料前置无玻璃/传感器未就绪。
- 新增 `303` 表示 FeedLift 搜索 target 配置非法 (`low >= high`)。
- 新增 `304` 表示 1Z 搜索窗口内未找到/未稳定确认光电1。
- 新增 `305` 表示 2Z 搜索窗口内未找到/未稳定确认光电2。
- 新增 `306` 表示 DEBUG 诊断参数非法。

实施顺序建议:

1. [已完成] 上位机实现 `preload_targets` 解析、执行前下发、点位配置和离线测试。
2. [已完成] PLC 新增 flat target/ActPos 节点，并改写 `A11/A21/A22` 为有界 jog + 稳定确认。
3. [已完成] 增加 DEBUG-only 诊断 action / code 91 稳定状态确认。
4. [已完成] 配置自检 -> 上位机离线测试 -> CODESYS 编译。
5. [待现场] 下载 PLC 后按单 action 真机验收 ->
   `feedlift_load_cycle` / `feedlift_unload_cycle` 单任务验收。

### 5.5 单站与跨站事件序列

实机或 sim/mock 需要验证的最小序列:

- 单 step: 每个试点站四个 step 分别启动，确认动作顺序、资源声明、失败停点。
- 单 station task: `collect_cycle`、`sampling_cycle`、`develop_cycle`、`photoscrape_cycle`。
- before-photo: `ptlc_full_v2` 已接入 `photoscrape_before_photo_cycle`, 不再 place/pick 空过;
  该 cycle 跳过接粉收集器步骤, 输出 `before_path` 给 after-scrape 视觉分析。
- after-scrape: `photoscrape_load` 负责把暂存A接粉收集器放入刮板夹具；
  `photoscrape_process -> collect_load -> collect_execute -> collect_unload`
  仍要重点确认接粉收集器从刮板到收集站的 handoff。
- FeedLift: 上料取板与废料下料若被定义为 station task，也要分别跑四个 step 和完整 task。

重点看 action 顺序、失败时是否停在可恢复状态，以及 `collect_load` 与
`photoscrape_process` 的跨站资源前提是否被调度层保证。

### 5.6 跨站 handoff 与机器人持板态

跨站自动运行时，中控不应在某个 `execute` 完成后临时决定“先跑源站 `unload` 还是目标站
`load`”。正确边界是先决定交接事务，再让机器人介入:

```text
A.execute 完成
  -> 中控检查并预约 B 的 load 能力
  -> 若 B 不可预约: 板继续留在 A，机器人不介入
  -> 若 B 可预约: 开启 handoff(A -> B)
       reserve(B)
       acquire(robot / rail / 必要夹具 / 物料所有权)
       A.unload
       B.load
       release(robot / rail)
       material_state = at_B
```

`robot_holding(sample_id, from=A, to=B)` 可以作为 handoff 内部过渡态，但不能作为普通
operation 完成态，也不能把机器人释放给其他样品。机器人拿着板停在 home 时，目标站预约和
物料所有权都必须仍被该 handoff 持有；否则其他样品竞争机器人资源时会形成锁死或难恢复的
半交接状态。

因此:

- 单站调试时可以单独点跑 `unload` 或 `load`，但操作者要确认物料前提。
- 跨站 recipe 不应裸调用 `A.unload` 后再等待调度下一步；应由 scheduler/controller 包一层
  `handoff(A -> B)`。
- 本轮 sampling 四段试点只做站内 step 拆分，不实现 handoff 调度器；但文档和测试口径必须
  保留这个约束，避免把“机器人持板 home”误判为安全空闲态。

### 5.7 顶层 recipe 与历史入口

- `09_full/ptlc_full_v2.yaml` 本轮不改。只有单 action、单 station step 和单 station task
  现场通过，并明确跨站 handoff 事务边界后，才进入顶层 recipe 简化。
- 旧 full/demo/兼容脚本先隐藏或标 legacy，不删除。删除前需确认无 `run_script` 引用、
  无测试入口、无 UI 入口、无现场回滚价值。
- 后续若增加机器可校验 `phase` 字段，应优先用 repo 级校验和 UI 元数据完成；
  不在第一轮扩 VM 指令或脚本 schema。

## 6. 后续执行顺序

1. 先确认本文的目标口径: 每个工位任务 = 1 个 station task + 4 个可单独点跑 station step。
2. 再决定 PLC 真源是否正式切到 `20260702.project`；不要让 `.mcp.json` 指向未跟踪工程。
3. Collect 作为最小试点: 只把四个 step 从 hidden/helper 提升为正式 station step，
   并补 UI 元数据/测试断言，不重排动作。
4. Sampling 第二站: 结构性试点已完成；后续只做单 step 现场验收、跨站 handoff 编排与必要 UI 分组。
5. Develop 与 PhotoScrape 已拆出四个 step。Develop 的 `prepare` 边界已定为:
   初始化 + 放板缸让位 + 清洗/润洗 + 板进入前预置上液；`execute` 只做展开完成门与排液闭环。
   PhotoScrape 的 `load` 边界已定为: 板放入 + 暂存A接粉收集器放入刮板夹具；仓库补货到暂存A不算本站动作。
6. FeedLift/Rail 最后定性: FeedLift 光电兜底已静态闭合, 但仍可能是两个 station task；Rail 多数保持 helper。
7. 已跑配置自检、目标离线测试与 CODESYS 编译，确认静态契约闭合。
8. 下载 PLC 后做单 action -> 单 step -> 单 station task -> 跨站 handoff 序列验收。
9. 现场通过后再进入 `ptlc_full_v2` 顶层 recipe 简化和 demo/legacy 清理。

## 7. 推荐验证命令

```powershell
E:\Anaconda\envs\platformupper\python.exe -m eit_ptlc.config.loader --check
E:\Anaconda\envs\platformupper\python.exe -m pytest `
  eit_ptlc/tests/test_sampling_four_stage_offline.py `
  eit_ptlc/tests/test_photoscrape_four_stage_offline.py `
  eit_ptlc/tests/test_collect_four_stage_offline.py `
  eit_ptlc/tests/test_develop_four_stage_offline.py `
  eit_ptlc/tests/test_feedlift_rail_four_stage_offline.py -q
E:\Anaconda\envs\platformupper\python.exe -m pytest eit_ptlc/tests/test_pump_contract_offline.py -q
```

后续新增/改写测试时，应把断言从“有四段注释/marker”升级为:

- 每个试点站恰有 1 个 station task + 4 个 visible station step。
- station task 只按 `prepare/load/execute/unload` 顺序调用四个 step。
- 四个 step 均可独立校验、独立启动，并拥有必要资源声明。
- `06_robot`、transfer、rail helper 被 step 调用，而不是要求 recipe 在外部补齐站内动作。

上述命令仍然只是配置和离线护栏，不替代 PLC 下载与现场动作验收。
