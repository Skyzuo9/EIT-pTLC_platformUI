# operation 四段式审计表 (2026-07-01)

本表原对应 `operation四段式重构审阅与实现计划_20260701.md` 的阶段 1 审计；现追加记录阶段 2 的 action 基建补齐结果。

审计范围:

- `eit_ptlc/config/operation/01_sampling` 到 `10_demo`
- `eit_ptlc/config/actions/**/*.yaml`
- `eit_ptlc/config/plc_nodes.yaml`
- InoProShop/CODESYS MCP 直读 `eit_ptlc/plc/20260622.project` 的 POU、GVL、PLC_MainPRG 调用；导出 XML 仅作辅助检索
- Python 执行链只用于确认边界: `ActionExecutor._exec_plc_l2 -> PlcController.execute`

边界说明:

- 本轮已进入阶段 2 的 action 基建补齐；允许为参数化 action 做最小 operation 接线，但不做阶段 3 的站内大规模四段式重排。
- PLC 实现级核实优先走 MCP 直读 `.project`。本轮已修改并保存 `eit_ptlc/plc/20260622.project`，CODESYS 编译 0 errors；`20260622.Device.Application.xml` 尚未重新导出，不能当作本轮 PLC 修改的最新证据。
- 静态合法不等于物理闭环。阶段 2 结论是“生产 L2 承载已补齐并通过编译”，真机下载、单 action 验收、联动流程验证仍属于后续门槛。

## 1. 静态底稿

| 检查项 | 结果 |
|---|---|
| `python -m eit_ptlc.config.loader --check` | 通过: app.yaml、197 个 PLC 节点、86 个机器人点加载成功 |
| 全量 action 数 | 74 |
| 全量 operation script 数 | 66 |
| 全量 `op: call` 数 | 1317 |
| 全量 `op: run_script` 数 | 94 |
| 缺失 action 引用 | 0 |
| 缺失 run_script 引用 | 0 |

## 2. 站级生命周期表

| 工位/子系统 | 准备 | 放料 | 执行 | 下料 | 缺口 | 冗余/历史项 |
|---|---|---|---|---|---|---|
| sampling | `sampling_cycle`: `sampling.init`, `pump.vacuum_on`, `sampling.clean`, `sampling.place_axis`; `sampling_prepare` 到 `sampling.place_axis` | `sampling_cycle`: `robot_suction_put(spotting)`, `sampling.place_locate`; `sampling_place_plate`: `robot_startup_check`, `robot_tool_ensure`, `rail_move_safe`, `feedlift_load_cycle`, `robot_suction_put`, `sampling.place_locate` | `sampling.prep`, `sampling.aspirate`, `pump.vacuum_off`, `sampling.spot_band_layer`; `sampling_spot` 覆盖同类执行段 | `sampling_cycle` 下料释放/取板顺序由采样 agent 复核 | 采样站不属于本轮展开收口范围；当前工作树已不再检出 `source_x/source_y` 残留 | `sampling_full` 是旧式纯设备串联入口，演示可用，但不应作为生产主线 |
| develop | `develop.init`, `develop.plate_retract`; `tank_prep`/`develop_prep_tank1` 为准备型子流程 | `robot_tank_put`, `develop.plate_extend` | `develop.clean_line`, `develop.rinse_fill`, `develop.rinse_suction`, `develop.fill`, `pump.vacuum_on/off`, `human confirm(显影到位)`, `develop.drain` | `develop.plate_retract`, `robot_tank_pick`, `develop.release_tank` | 排液已产品化为 PLC L2 action 并完成配置/编译验证；显影完成判定仍为 HITL/后续 vision 门；待下载/真机验收 | `tank_prep` 不可误认为完整站 cycle |
| photoscrape | `photoscrape_place`: `photoscrape.init`, `photoscrape.cam_x335` | 板: `robot_suction_put(scrape)`, `photoscrape.locate_cylinder(clamped=true)`; 接粉收集器: `transfer_collector_staging_a_to_scrape` 调 `photoscrape.powder_collector_locator(located=true)` | `photoscrape_process`: `photoscrape.press_cylinder(pressed=true)`, `photoscrape.cam_photopos`, `photoscrape.capture`, `photoscrape.cam_photohome`, `photoscrape.analyze`, `photoscrape.cnc_path`, `photoscrape.write_cnc_path`, `photoscrape.write_pass_z`, `photoscrape.scrape`, `photoscrape.scrape_finish` | 板: `photoscrape_pick`: `photoscrape.locate_cylinder(clamped=false)`, `robot_suction_pick(scrape)`, `photoscrape.retr_stoprot`; 接粉收集器: `collect_load` 调 `press_cylinder(false)` + `powder_collector_locator(false)` | G1/G4 已由参数化生产 L2 承载补齐，待下载/真机验收 | `photoscrape_full` 仍名为 full，但 R2 边界已拆为 place/process/pick，生产主线不应回退到旧 full |
| collect | `collect_prepare`: `collect.init` | `collect_load`: `robot_scrape_holder_pick_enter`, `photoscrape.press_cylinder(false)`, `photoscrape.powder_collector_locator(false)`, `robot_scrape_holder_pick_exit`, `robot_collect_holder_put_enter`, `collect.clamp`, `robot_collect_holder_put_exit`, `collect.extend`, `transfer_bottle_staging_b_to_collect` | `collect_execute`: `collect.lift_press`, `collect.collect`, `collect.transport_extend` | `collect_unload`: `transfer_bottle_collect_to_staging_b`, `collect.retract`, `robot_collect_holder_pick_enter`, `collect.release_clamp`, `robot_collect_holder_pick_exit`, `robot_collector_return_put` | 本站已完成静态四段式组织；`execute` 承载进入洗脱姿态、设定次数洗脱循环、退出到取瓶姿态；`collect.bottle_locator` 已移出工位四段，待独立暂存B补货/回库链承载 | `collect_full` 标注弃用，缺机器人放瓶/取瓶交错 |
| transfer | 非站级，负责 `rail.move` + 机器人取放 | 非站级 | 不应含工艺执行 | 非站级 | C: 多个 transfer 直接 `rail.move`，未复用已有 `rail_move_safe`; `transfer_collector_staging_a_to_scrape` 现含 `powder_collector_locator(true)`，这是目标站放料夹具接线 | transfer 文件应保持跨站交接，不扩展为工艺执行 |
| robot | 非站级点位片段库 | pick/put 片段含 approach/target/retreat | 末端动作通过 `robot.tool_action` | 多数片段回 P1 或局部安全锚点 | C 风险: 底层片段通常不自带 `robot_tool_ensure`，依赖上层 recipe 组合 | `robot_home_check`/jog/step/set_do/clear_error/enable/disable 为 DEBUG/维护类，不应混入 RUN |
| feedlift | `feedlift_load_cycle`: `rail_move_safe(1)`, `feedlift.feed_raise`; `feedlift_unload_cycle`: `rail_move_safe(1)`, `feedlift.unload_ready` | load: 升降机顶料; unload: `robot_suction_put(waste)` 放废板 | load: `robot_feed_lift_pick_enter`, `feedlift.feed_lower`; unload: `feedlift.unload_bury` | load: `robot_feed_lift_pick_exit` 持板回 P1; unload: 废板埋料完成 | 未见 A/B 缺口; 前提是工具态和持板状态由调用方保证 | 辅助上下料 cycle，不是工艺站 |
| rail | `rail_move_safe`: `robot.require_anchor(P1)` | 不适用 | `rail.move(target)` | 不适用 | B 风险已降级: MCP 已确认 `Rail_L2` / `Rail_Sync` / `PLC_MainPRG` 调用；仍需现场单动作验收。C: transfer 多处未用 `rail_move_safe` | `rail.move` 可保留为底层 action |
| ptlc_full_v2 | `robot_startup_check`, HITL, `robot.set_mounted_tool` | 串联 `feedlift_load_cycle`, `sampling_cycle`, `photoscrape_place`, `develop_cycle`, 耗材 transfer, `collect_cycle` | 顶层调用 `photoscrape_process` 和站 cycle，不直接裸调站内气缸 | `photoscrape_pick`, `feedlift_unload_cycle` | 顶层边界基本干净; 缺口应回填站内 cycle，不应补在顶层 | 仍固定 demo tank/slot，生产调度需后续参数化 |
| demo | 各 demo 均有 startup/tool/HITL | 复用 station/transfer 子流程 | 单站或 round-trip 演示 | 按 demo 边界结束 | 继承 production 缺口; `sampling_demo` 引用 `sampling_full` | 需继续显式标注 `[单站DEMO]` / DEBUG / manual-only |

## 3. 执行件状态表

| 执行件 | 夹紧/伸出/开 action | 松开/缩回/关 action | 反馈/节点证据 | operation 引用 | 结论 |
|---|---|---|---|---|---|
| 拍照刮板定位气缸 | `photoscrape.locate_cylinder(clamped=true)` code 32 | `photoscrape.locate_cylinder(clamped=false)` code 32 | `PhotoScrape_CamLocate_Target`; MCP 直读 `A32_cam_定位` 已读取目标态参数；A41 已不再隐式释放定位；当前未见独立定位到位反馈 | `photoscrape_place.yaml`, `photoscrape_pick.yaml` | 已修复为生产 L2 目标态 action，CODESYS 编译 0 errors；待真机下载/单动作验收 |
| 拍照刮板下压气缸 | `photoscrape.press_cylinder(pressed=true)` code 33 | `photoscrape.press_cylinder(pressed=false)` code 33 | `PhotoScrape_CamPress_Target`; MCP 直读 `A33_cam_下压` 已读取目标态参数，false 分支等待 `刮板拍照下压气缸上位` | `photoscrape_process.yaml`, `collect_load.yaml` | 已修复为生产 L2 目标态 action；旧 `retr_release(51)` 不再作为上位机 action 暴露；pressed=true 是否需下位反馈待现场确认 |
| 拍照刮板接粉夹具定位 | `photoscrape.powder_collector_locator(located=true)` code 36 | `photoscrape.powder_collector_locator(located=false)` code 36 | `PhotoScrape_PowderCollectorLocate_Target`; MCP 直读 `PhotoScrape_L2` code 36 inline 写 `粉末收集器定位自动`；当前未见独立到位反馈 | `transfer_collector_staging_a_to_scrape.yaml`, `collect_load.yaml` | 已修复为生产 L2 目标态 action，CODESYS 编译 0 errors；待真机验收 |
| 拍照刮板旋转气缸 | 隐含在刮取/翻料流程，未见独立“旋转开” action | `photoscrape.retr_stoprot` code 52 | PLC 工程有旋转气缸输出与原/动点反馈 | `photoscrape_pick.yaml` | 取料复位 action 有；不纳入本轮目标态合并 |
| 拍照遮光气缸 + 8Y | `photoscrape.cam_photopos` code 34, `ref_8y` | `photoscrape.cam_photohome` code 35 | `Photo_8Y_Target`, 遮光上/下位, 8Y 目标点位 | `photoscrape_process.yaml` | 闭环较完整；不纳入本轮目标态合并 |
| CNC 刮取路径 | `photoscrape.write_cnc_path` + `photoscrape.scrape` code 40 | `photoscrape.scrape_finish` code 41 | `g_sx/g_sy/g_cx/g_cy/g_pass_z/g_scrape_feed`, `CNC完成`; MCP 已将 A41 改为只关真空/无刷电机并启动旋转翻料，不再释放定位气缸 | `photoscrape_process.yaml` | 路径写入 + L2 执行闭环存在；A41 不再替代单气缸目标态释放 |
| 上样定位气缸 | `sampling.place_locate` code 32 | `sampling.place_release` code 33 | PLC 工程有 `上样定位气缸` 输出与反馈 | `sampling_cycle.yaml` | 采样站接线由对应 agent 复核；本轮不展开 |
| 上样点样/泵 | `sampling.prep`, `sampling.aspirate`, `sampling.spot_band_layer` | `pump.vacuum_off` | `Sampling_*instructions`, `Sampling_4X/3Y_Target`, `Spot_6X/7Y_Target` | `sampling_cycle.yaml`, `sampling_spot.yaml` | 执行链存在；`sampling.spot` code 60 未引用，当前用 code 62 |
| 展开放板缸 | `develop.plate_extend` code 32 | `develop.plate_retract` code 31 | `Expand_Target_Tank`, Develop L2 节点 | `develop_cycle.yaml` | 闭环存在 |
| 展缸排液/液位 | `develop.drain` code 50 | `develop.release_tank` code 51 | `Tank_Drain_Enable/Done`, `Tank_State`; `Develop_L2` 统一通道 | `develop_cycle.yaml` | 排液原语已补为生产 L2 action；未下载 PLC，未做现场排液闭环 |
| 收集夹持气缸 | `collect.clamp` code 21 | `collect.release_clamp` code 43 | PLC 工程有夹持动点/原点、夹持输出 | `collect_cycle.yaml` | 闭环存在 |
| 暂存B瓶板锁 | 待独立补货/回库链串联 `collect.bottle_locator(located=true)` code 24 | 待独立补货/回库链串联 `collect.bottle_locator(located=false)` code 24 | `Collect_BottleLocate_Target`; MCP 已在 `Collect_L2` 增加 code 24；CODESYS 编译 0 errors | 不属于 `collect_cycle.yaml` | 已从 Collect 工位四段移除；后续补货/回库链设计时再承载 |
| 收集伸缩/升降/下压 | `collect.extend`; `collect_execute` 内 `collect.lift_press -> collect.collect -> collect.transport_extend` | `collect.retract` | `A23` 负责缩回/验瓶/升降/下压，`A41` 负责复位下压/升降并伸出 | `collect_cycle.yaml` | 复合动作存在；洗脱姿态进入/退出归入执行段；瓶定位不再误写为这些复合动作覆盖 |
| FeedLift 上料升降 | `feedlift.feed_raise` code 11 | `feedlift.feed_lower` code 12 | `FeedLift_L2_*` | `feedlift_load_cycle.yaml` | 闭环存在 |
| FeedLift 下料埋料 | `feedlift.unload_ready` code 21 | `feedlift.unload_bury` code 22 | `FeedLift_L2_*` | `feedlift_unload_cycle.yaml` | 闭环存在 |
| Rail 地轨 | `rail.move` code 10 | 同一目标位参数化 | `Rail_Target_Position`, `Rail_ActPos`, `Rail_Homed`, `Rail_L2_*` | `rail_move_safe.yaml`, 多处 recipe 调用 | 上位 action/operation 有；真机单动作仍需验收 |
| 机器人快换/吸盘/夹爪 | `robot.tool_action` 参数化 | 同左 | 工具动作白名单和机器人驱动映射 | `robot_*` scripts | 语义动作与工具态门控存在；裸 `robot.set_do` 仅 DEBUG，未进生产 |

## 4. 缺口清单

| ID | 缺口 | 分类 | 证据 | 处理建议 |
|---|---|---|---|---|
| G1 | 拍照刮板 before-photo 定位释放承载 | 已处理，待真机验收 | `photoscrape.locate_cylinder(clamped)` code 32 + `PhotoScrape_CamLocate_Target`; PLC `A32_cam_定位` 已改目标态；`photoscrape_pick` 已调用 false；A41 已不再隐式释放定位 | 下载 PLC 后做 code 32 true/false 单动作验收，再跑 before-photo place->pick |
| G2 | 上样定位松开/取板顺序 | 由采样 agent 复核 | `plc_sampling.yaml` 有 `sampling.place_release`; 当前工作树 `sampling_cycle.yaml` 已出现引用 | 用采样站目标测试确认 `sampling.place_release` 与 `robot_suction_pick(spotting)` 的最终顺序 |
| G3 | 展缸自动排液/显影完成门未动作化 | 排液原语已处理；显影完成门保留 HITL/后续 vision | `develop.drain` code 50 等待 `Tank_Drain_Done/Tank_State=99`; `develop.release_tank` code 51 在取板后清 `Tank_State=0`; CODESYS 编译 0 errors/32 warnings | 下载 PLC 后单独验收 code 50/51，再验 `develop_cycle` 现场排液；不能把配置/编译通过说成真机闭环 |
| G4 | 刮板接粉夹具定位承载 | 已处理，待真机验收 | `photoscrape.powder_collector_locator(located)` code 36 + `PhotoScrape_PowderCollectorLocate_Target`; PLC `PhotoScrape_L2` 已接受 code 36 并 inline 写目标态 | 下载 PLC 后做 code 36 true/false 单动作验收，再验耗材 transfer/collect handoff；若现场要求到位反馈，需补 PLC 反馈输入后再改等待逻辑 |
| G5 | transfer 直接 `rail.move`，未复用 `rail_move_safe` | C | `05_transfer/*.yaml` 多处直接 `rail.move`; `08_rail/rail_move_safe.yaml` 已存在安全封装 | 后续重排时统一纳入 `rail_move_safe` 或给出机器可查证前置 |
| G6 | 暂存B瓶板锁被误放进 Collect 工位四段 | 已从 `collect_load` / `collect_unload` 移除，待独立补货/回库链承载 | `collect.bottle_locator(located)` code 24 + `Collect_BottleLocate_Target`; PLC `Collect_L2` 已接受 code 24，但 operation 中不再由 `collect_cycle` 调用 | 后续在“仓库↔暂存B”链路里明确锁/松顺序，再做 code 24 true/false 单动作验收 |
| G7 | `sampling_full` / `collect_full` / `photoscrape_full` / `ptlc_full.yaml` 入口可能被误用为生产主线 | 已标注，仍是历史/演示风险 | `sampling_full` 已 legacy hidden；`collect_full`、`photoscrape_full`、`ptlc_full.yaml` 已补 legacy/deprecated hidden；demo 入口仍可能引用历史脚本 | 保留用于测试/手工对照，不作为阶段 3/4 生产样板；后续若迁移 demo，可再考虑删除或收窄入口 |
| G8 | Rail 工程实现已核，现场单动作仍需验收 | B 风险降为验收风险 | MCP 已确认 `Rail_L2` 改读 `Rail_Pos_Target[]`、`Rail_Sync`、`PLC_MainPRG` 调用；`plc_nodes.yaml` 有 Rail_L2 节点 | 阶段 2/3 前跑 acceptance 单动作验证，确认运行 PLC 与当前工程一致 |

## 5. 本轮没有继续扩大的原因

本轮修正 action 目录表达和必要接线，重点是把成对气缸动作改为“生产 L2 action + BOOL 目标态参数”，不再新增 DEBUG/raw-output。已经确认并落地的参数化范围是拍照刮板定位、下压、接粉夹具定位，以及暂存B瓶板锁目标态。其余项暂不合并，原因如下:

1. `sampling.place_locate/place_release` 已有生产 action，本轮不强行改为参数化；阶段 3 会先补 operation 下料引用。
2. `develop` 排液涉及数组元素和 Tank 状态，已按两个 L2 动作处理为“排液到 `Tank_State=99`”与“取板后释放 `Tank_State=0`”，不是单 BOOL 目标态动作。
3. `cam_photopos/cam_photohome`、`scrape/scrape_finish`、`rail.move` 不是简单双态气缸。
4. 机器人工具 action 已参数化，且有工具态门控，不属于 PLC L2 双态气缸合并范围。

## 6. 验证记录

- 已做: `python -m eit_ptlc.config.loader --check` 通过，当前 197 个 PLC 节点。
- 已做: action/operation 静态引用检查通过，74 个 action、66 个 operation script、1317 个 `op: call`、94 个 `op: run_script`。
- 已做: 目标静态契约测试 `python -m pytest eit_ptlc/tests/test_pump_contract_offline.py -q` 通过，4 passed / 169 subtests passed。
- 已做: 收集站四段式静态测试 `python -m pytest eit_ptlc/tests/test_collect_four_stage_offline.py -q` 通过，6 passed / 6 subtests passed。
- 已做: CODESYS MCP 修改并保存 `eit_ptlc/plc/20260622.project`，拍照刮板 `A41_scrape_收尾` 已去掉隐式定位释放，编译 0 errors；仍有 32 个既有 `INT` 到 `WORD` 隐式转换 warnings。
- 未做: PLC 下载到真机、真机单 action 验证、mock/sim station cycle 事件序列验证。

以上未做项不阻塞阶段 2 的 action 基建结论，但会阻塞阶段 3/4 的“operation 行为已完成真机闭环”结论。
