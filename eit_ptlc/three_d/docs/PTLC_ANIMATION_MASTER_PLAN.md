# PTLC 三维模块全量动画与实时孪生主计划

> 文档版本：1.5  
> 建立日期：2026-08-01  
> 当前阶段：阶段 2 `READY_FOR_REVIEW`  
> 实施范围：三维功能、资源与运行时统一归入 `eit_ptlc`；原始 CAD 明确排除在仓库外  
> 状态流：`NOT_STARTED → IN_PROGRESS → READY_FOR_REVIEW → ACCEPTED`  
> 阶段门：未经用户明确验收，不进入下一阶段

## 1. 当前结论

阶段 0 的真源清点已完成，数量与计划完全一致：

| 项目 | 数量 | 核验结果 |
|---|---:|---|
| 上位机原子动作 | 93 | PASS |
| 操作流程 | 101 | PASS |
| 被流程直接引用的动作 | 73 | PASS |
| 未被流程引用但仍需覆盖的动作 | 20 | PASS |
| PLC 手动轴 | 11 | PASS |
| 手动气缸/阀/泵 | 51 | PASS |
| 原始机器人 joint+pose 点 | 74 | PASS |
| 六轴全零占位点 | 4 | PASS，排除 |
| 可用于关节标定的原始点 | 70 | PASS |
| 未知动作引用 | 0 | PASS |
| 未知子流程引用 | 0 | PASS |

阶段 1 的统一运行时、刚体约束和静态合并保护已经完成；针对页面验收发现的底座/托盘横向错位及托盘气动附件遗漏，现已将真实 `PTLC-07-025` 支撑板、`4V21008B-1`、`WEF50-N-KL-1`、`PTLC-07-027 压力表安装板-1` 在内的 11 个托盘刚体根纳入 `axis_11y/CARRIAGE`，并按 slot 4 安装基准整体平移后重新进入 `/3d/motion` 视觉验收。整机仍不能直接进入“批量做动画”：只有地轨 `axis_11y` 和 CR5 六轴具备已核验的独立刚体链；另外 10 根 PLC 轴、绝大多数气缸、连杆和载荷必须在对应业务阶段从正式 CAD 分离后才能加入，不能先填近似节点。

## 2. 真源与版本指纹

本目录不是 Git 工作树，因此用稳定 SHA-256 追踪输入。动作树哈希同时包含相对路径和文件内容，改名也会触发变化。

| 真源/资产 | SHA-256 |
|---|---|
| `config/actions/**/*.yaml` | `4236902019256f16e701c3ad915bd3d424d1d52be1dd5acf95f63bd98d2aae30` |
| `config/operation/**/*.yaml` | `b23400478c531d84c1b5575783f16693d6f18928a5c72a799600eae415ad9e67` |
| `config/manual_points.yaml` | `3e40d3e1ec77c12b8d17d19964c41f5361f9ef6b6ac7811439a7cdd300864000` |
| `config/points/robot/robot_points.json` | `4b62a7049b8df0c5e0e8d34920f8cb64695f6dafe73eb04960c3301f9991c673` |
| `pipeline/rig_map.yaml` | `0e840961089c4d1c3f9d6d98e9cd446706dae923c85c908b555991e01a0d14c7` |
| `pipeline/calibration/cr5_ptlc_v1.yaml` | `6b568919276fc2d56b5030e40a0b8f9cb676d6f1b4eaf7a8b562f5fe9fc12288` |
| `models/machine.glb` | `cea7484bf2eed5d179e958e675ad2be931cd26568754f95786ace89a240d04c9` |
| `models/device-manifest.json` | `45fa4e7d54efc8e97712b63356bc809ae3a4f8a91b13f48742913dc96d81e847` |
| `models/machine.official-cr5.glb` | `518d36b482ed1d0de6843ee7a471f0430ebf311fddf8a7189d2699247a88b29` |
| `models/device-manifest.official-cr5.json` | `3df82bc007dfff9cb41c9743687c5aee1e7e1f4be5ad8e5389234c4470aef446` |

CR5 运动学真源固定为 Dobot 官方仓库提交 `37730d08b08c74061ae10d4fa5565b4c4c914885`。当前 manifest 已记录该提交和机器人点表 SHA。

审计命令：

```powershell
python pipeline/audit_ptlc_sources.py `
  --control-root $env:PTLC_CONTROL_ROOT `
  --check --summary
```

该命令只读，不修改上位机配置；输出仅包含相对源路径。

## 3. 原子动作台账（93/93）

说明：`机构` 表示真实刚体/轴/连杆运动，`状态` 表示灯、液位、相机、视觉结果或控制器状态。所有条目当前均为 `NOT_STARTED`，只有清点工作完成。

### 3.1 Sampling（12）

| 动作 | kind | 规划表现 | 主要机构/载荷 | 流程引用 |
|---|---|---|---|---|
| `sampling.init` | plc_l2 | 机构+状态 | 3Y/4X/5Z/6X/7Y、阀 | 已引用 |
| `sampling.clean` | plc_l2 | 机构+流体状态 | 4X/5Z/6X、泵、三通 | 已引用 |
| `sampling.flush` | plc_l2 | 机构+流体状态 | 4X/5Z/6X、泵、三通 | 已引用 |
| `sampling.place_axis` | plc_l2 | 机构 | 4X/5Z 放板位 | 已引用 |
| `sampling.place_locate` | plc_l2 | 机构+约束 | 定位缸、板件工位插槽 | 已引用 |
| `sampling.place_release` | plc_l2 | 机构+约束 | 定位缸、板件释放 | 已引用 |
| `sampling.prep` | plc_l2 | 流体状态 | 泵、三通、驱动液 | 已引用 |
| `sampling.aspirate` | plc_l2 | 机构+流体状态 | 3Y/4X/5Z、孔板 | 已引用 |
| `sampling.rinse_mix` | plc_l2 | 机构+流体状态 | 孔板、泵、三通 | 已引用 |
| `sampling.spot` | plc_l2 | 机构+流体状态 | 6X/7Y、板件 | 未引用 |
| `sampling.spray_axis` | plc_l2 | 机构 | 5Z/6X/7Y | 未引用 |
| `sampling.spot_band_layer` | plc_l2 | 机构+流体状态 | 6X/7Y、板件、吹气 | 已引用 |

### 3.2 Develop（11）

| 动作 | kind | 规划表现 | 主要机构/载荷 | 流程引用 |
|---|---|---|---|---|
| `develop.init` | plc_l2 | 机构+状态 | 8 缸、阀、液位 | 已引用 |
| `develop.clean_line` | plc_l2 | 流体状态 | 进/排/吹阀、管路 | 未引用 |
| `develop.rinse_fill` | plc_l2 | 流体状态 | 进液阀、液位 | 已引用 |
| `develop.rinse_suction` | plc_l2 | 流体状态 | 排液/吹气阀、液位 | 已引用 |
| `develop.fill` | plc_l2 | 流体状态 | 进液阀、液位 | 已引用 |
| `develop.drain` | plc_l2 | 流体状态 | 排液/吹气阀、液位 | 已引用 |
| `develop.release_tank` | plc_l2 | 状态 | 缸资源/占用标识 | 已引用 |
| `develop.plate_retract` | plc_l2 | 连杆+约束 | 开盖、板件插槽 | 已引用 |
| `develop.plate_extend` | plc_l2 | 连杆+约束 | 关盖、板件插槽 | 已引用 |
| `develop.wait_level` | host | 状态 | 液位确认、等待进度 | 已引用 |
| `develop.capture_reference` | host | 相机/状态 | 展缸参考图 | 已引用 |

### 3.3 Collect（9）

| 动作 | kind | 规划表现 | 主要机构/载荷 | 流程引用 |
|---|---|---|---|---|
| `collect.init` | plc_l2 | 机构+状态 | 夹持/升降/伸缩/下压 | 已引用 |
| `collect.clamp` | plc_l2 | 机构+约束 | 夹持缸、收集器 | 已引用 |
| `collect.extend` | plc_l2 | 机构 | 伸缩平台 | 已引用 |
| `collect.lift_press` | plc_l2 | 机构 | 升降、下压 | 已引用 |
| `collect.bottle_locator` | plc_l2 | 机构+约束 | 中转B瓶板定位 | 未引用 |
| `collect.collect` | plc_l2 | 机构+流体状态 | 收集器、瓶、阀、泵 | 已引用 |
| `collect.transport_extend` | plc_l2 | 机构 | 升降/下压复位、伸出 | 已引用 |
| `collect.retract` | plc_l2 | 机构 | 伸缩平台 | 已引用 |
| `collect.release_clamp` | plc_l2 | 机构+约束 | 夹持缸、收集器释放 | 已引用 |

### 3.4 PhotoScrape（20）

| 动作 | kind | 规划表现 | 主要机构/载荷 | 流程引用 |
|---|---|---|---|---|
| `photoscrape.align_readout` | host | 结果覆盖 | 对位数值 | 已引用 |
| `photoscrape.capture` | camera | 相机状态 | 相机、闪光、图像结果 | 已引用 |
| `photoscrape.cnc_path` | vision | 路径覆盖 | 刮取路径 | 已引用 |
| `photoscrape.init` | plc_l2 | 机构+状态 | 8Y/9X/10Z、气缸 | 已引用 |
| `photoscrape.cam_x335` | plc_l2 | 机构 | 9X **刀头停放位**(让位 + 翻料互锁 >330) | 已引用 |
| `photoscrape.locate_cylinder` | plc_l2 | 机构+约束 | 定位缸、玻璃板 | 已引用 |
| `photoscrape.press_cylinder` | plc_l2 | 机构 | 下压缸 | 已引用 |
| `photoscrape.cam_photopos` | plc_l2 | 机构 | 8Y、遮光机构 | 已引用 |
| `photoscrape.cam_photohome` | plc_l2 | 机构 | 8Y、遮光机构 | 已引用 |
| `photoscrape.scrape` | plc_l2 | 机构+路径 | 8Y(板走 X)/9X(刀走 Y)/10Z(切深)三轴插补、刮板、收集器 | 已引用 |
| `photoscrape.scrape_finish` | plc_l2 | 机构+载荷 | 翻料机构、收集器 | 已引用 |
| `photoscrape.retr_stoprot` | plc_l2 | 机构 | 旋转缸复位 | 已引用 |
| `photoscrape.align_move` | plc_l2 | 机构 | 8Y/9X | 已引用 |
| `photoscrape.align_home` | plc_l2 | 机构 | 8Y/9X/10Z | 已引用 |
| `photoscrape.align_z` | plc_l2 | 机构 | 10Z | 已引用 |
| `photoscrape.write_cnc_path` | plc_write | 状态 | PLC 路径写入 | 已引用 |
| `photoscrape.write_pass_z` | plc_write | 状态 | pass 切深写入 | 已引用 |
| `photoscrape.wait_rot` | host | 状态 | 旋转缸到位等待 | 已引用 |
| `photoscrape.scraped_overlay` | vision | 结果覆盖 | 刮前/刮后对账 | 已引用 |
| `photoscrape.analyze` | vision | 结果覆盖 | 板件、条带分析 | 已引用 |

### 3.5 FeedLift（11）

| 动作 | kind | 规划表现 | 主要机构/载荷 | 流程引用 |
|---|---|---|---|---|
| `feedlift.probe_stack` | host | 机构+测量状态 | 1Z/2Z、板堆 | 已引用 |
| `feedlift.preflight` | host | 状态 | 光电/轴前置检查 | 已引用 |
| `feedlift.read_pos` | host | 状态 | 1Z/2Z 读数 | 已引用 |
| `feedlift.calib_record` | host | 状态 | 标定样本 | 已引用 |
| `feedlift.init` | plc_l2 | 机构+状态 | 1Z/2Z | 已引用 |
| `feedlift.feed_raise` | plc_l2 | 机构+载荷 | 1Z、板堆 | 已引用 |
| `feedlift.feed_clear` | plc_l2 | 机构+载荷 | 1Z、板堆 | 已引用 |
| `feedlift.feed_lower` | plc_l2 | 机构+载荷 | 1Z、板堆 | 已引用 |
| `feedlift.unload_ready` | plc_l2 | 机构+载荷 | 2Z、废板堆 | 已引用 |
| `feedlift.unload_bury` | plc_l2 | 机构+载荷 | 2Z、废板堆 | 已引用 |
| `feedlift.debug_check_photoelectric_edge` | plc_l2 | 机构+诊断状态 | 1Z/2Z、光电 | 未引用 |

### 3.6 Rail（2）

| 动作 | kind | 规划表现 | 主要机构/载荷 | 流程引用 |
|---|---|---|---|---|
| `rail.move` | plc_l2 | 机构 | 11Y→托盘→机器人→工具→载荷 | 已引用 |
| `rail.ensure` | rail_ensure | 机构+状态 | 11Y 站位确认 | 已引用 |

### 3.7 Robot（21）

| 动作 | kind | 规划表现 | 主要机构/载荷 | 流程引用 |
|---|---|---|---|---|
| `robot.query` | robot | 状态 | 模式、关节、位姿、工具 | 已引用 |
| `robot.home` | robot | 关节运动 | CR5→工具→载荷 | 已引用 |
| `robot.jog_start` | robot | 实时关节/笛卡尔运动 | CR5→工具→载荷 | 未引用 |
| `robot.jog_stop` | robot | 实时状态 | 冻结于实际停点 | 未引用 |
| `robot.set_speed_factor` | robot | 状态 | 速度倍率 | 未引用 |
| `robot.step` | robot | 实时关节/笛卡尔运动 | CR5→工具→载荷 | 未引用 |
| `robot.move_to_point` | robot | 关节/FK | CR5→工具→载荷 | 已引用 |
| `robot.require_anchor` | robot | 状态 | 锚点误差覆盖 | 已引用 |
| `robot.home_ensure` | robot | 关节/FK+状态 | CR5→工具→载荷 | 已引用 |
| `robot.dwell` | robot | 状态 | 等待进度 | 已引用 |
| `robot.tool_action` | robot | 工具机构+约束 | 快换/吸盘/夹爪/载荷 | 已引用 |
| `robot.set_mounted_tool` | robot | attach/detach | TOOL_MOUNT、工具 | 已引用 |
| `robot.set_do` | robot | 状态 | DO/工具指示 | 未引用 |
| `robot.stop` | robot | 状态 | 实际停点 | 未引用 |
| `robot.pause` | robot | 状态 | 暂停并冻结实际反馈 | 未引用 |
| `robot.resume` | robot | 状态 | 继续实际反馈 | 未引用 |
| `robot.emergency_stop` | robot | 状态 | 急停/报警覆盖 | 未引用 |
| `robot.clear_error` | robot | 状态 | 报警清除 | 未引用 |
| `robot.enable` | robot | 状态 | 使能 | 未引用 |
| `robot.disable` | robot | 状态 | 下使能 | 未引用 |
| `robot.connect` | robot | 状态 | 连接/重连 | 未引用 |

### 3.8 其他（7）

| 动作 | kind | 规划表现 | 主要机构/载荷 | 流程引用 |
|---|---|---|---|---|
| `pump.vacuum_on` | plc_l2 | 状态 | 真空泵/管路 | 未引用 |
| `pump.vacuum_off` | plc_l2 | 状态 | 真空泵/管路 | 未引用 |
| `vision.capture_plate_offset` | vision | 结果覆盖 | 玻璃板纠偏 | 已引用 |
| `staging_a.locator_a` | plc_l2 | 机构+约束 | 粉末收集器定位 | 已引用 |
| `staging_a.locator_b` | plc_l2 | 机构+约束 | 收集瓶定位 | 已引用 |
| `material.check_availability` | host | 状态 | 耗材余量 | 已引用 |
| `material.plan_staging` | host | 状态 | 中转/料架决策 | 已引用 |

20 个未引用动作仍属于正式交付范围，不能因生产流程暂未调用而跳过。

## 4. 流程台账（101/101）

全部流程 YAML 已成功解析，当前不存在未知动作或未知子流程引用。动画编译状态均为 `NOT_STARTED`。

### System（1）

- [ ] `system_init_all`

### Sampling（12）

- [ ] `sampling_cycle`
- [ ] `sampling_execute`
- [ ] `sampling_full`
- [ ] `sampling_load`
- [ ] `sampling_multi_cycle`
- [ ] `sampling_multi_execute`
- [ ] `sampling_place_plate`
- [ ] `sampling_prepare`
- [ ] `sampling_prepare_legacy`
- [ ] `sampling_spot`
- [ ] `sampling_unload`
- [ ] `sampling_volume_model`

### Develop（8）

- [ ] `develop_cycle`
- [ ] `develop_execute`
- [ ] `develop_load`
- [ ] `develop_prep_tank1`
- [ ] `develop_prepare`
- [ ] `develop_standby`
- [ ] `develop_unload`
- [ ] `tank_prep`

### PhotoScrape（15）

- [ ] `photoscrape_align_loop`
- [ ] `photoscrape_before_photo_capture`
- [ ] `photoscrape_before_photo_cycle`
- [ ] `photoscrape_cycle`
- [ ] `photoscrape_execute`
- [ ] `photoscrape_full`
- [ ] `photoscrape_load`
- [ ] `photoscrape_pick`
- [ ] `photoscrape_place`
- [ ] `photoscrape_plate_load`
- [ ] `photoscrape_prepare`
- [ ] `photoscrape_process`
- [ ] `photoscrape_scrape_calib`
- [ ] `photoscrape_tool_align`
- [ ] `photoscrape_unload`

### Collect（6）

- [ ] `collect_cycle`
- [ ] `collect_execute`
- [ ] `collect_full`
- [ ] `collect_load`
- [ ] `collect_prepare`
- [ ] `collect_unload`

### Transfer（9）

- [ ] `ensure_bottle_staged`
- [ ] `ensure_collector_staged`
- [ ] `transfer_bottle_collect_to_staging_b`
- [ ] `transfer_bottle_rack_to_staging_b`
- [ ] `transfer_bottle_staging_b_to_collect`
- [ ] `transfer_bottle_staging_b_to_rack`
- [ ] `transfer_collector_rack_to_staging_a`
- [ ] `transfer_collector_staging_a_to_rack`
- [ ] `transfer_collector_staging_a_to_scrape`

### Robot（28）

- [ ] `robot_collect_bottle_pick`
- [ ] `robot_collect_bottle_put`
- [ ] `robot_collect_holder_pick_enter`
- [ ] `robot_collect_holder_pick_exit`
- [ ] `robot_collect_holder_put_enter`
- [ ] `robot_collect_holder_put_exit`
- [ ] `robot_collector_return_put`
- [ ] `robot_feed_lift_pick_enter`
- [ ] `robot_feed_lift_pick_exit`
- [ ] `robot_group_rack_pick`
- [ ] `robot_group_rack_put`
- [ ] `robot_group_staging_pick`
- [ ] `robot_group_staging_put`
- [ ] `robot_home_check`
- [ ] `robot_individual_pick`
- [ ] `robot_individual_put`
- [ ] `robot_scrape_holder_pick_enter`
- [ ] `robot_scrape_holder_pick_exit`
- [ ] `robot_scrape_holder_put_enter`
- [ ] `robot_scrape_holder_put_exit`
- [ ] `robot_startup_check`
- [ ] `robot_suction_pick`
- [ ] `robot_suction_put`
- [ ] `robot_tank_pick`
- [ ] `robot_tank_put`
- [ ] `robot_tool_ensure`
- [ ] `robot_tool_pick`
- [ ] `robot_tool_put`

### FeedLift（4）

- [ ] `feedlift_calib_sample`
- [ ] `feedlift_load_cycle`
- [ ] `feedlift_measure_count`
- [ ] `feedlift_unload_cycle`

### Rail（1）

- [ ] `rail_move_safe`

### Full（2）

- [ ] `ptlc_full`
- [ ] `ptlc_full_v2`

### Parallel（15）

- [ ] `pf_af0_batch_startup`
- [ ] `pf_s1_load`
- [ ] `pf_s2_spot`
- [ ] `pf_s3_tank_prep`
- [ ] `pf_s4_photo_before`
- [ ] `pf_s5_to_tank`
- [ ] `pf_s6_develop_wait`
- [ ] `pf_s7_consumables`
- [ ] `pf_s8_to_scrape`
- [ ] `pf_s9_scrape`
- [ ] `pf_s10_collect`
- [ ] `pf_s11_unload`
- [ ] `pf_smoke_a`
- [ ] `pf_smoke_b`
- [ ] `pf_smoke_c`

## 5. 实时手动控制台账

### 5.1 机械臂

- 连续点动：`J1±…J6±`、`X±/Y±/Z±/Rx±/Ry±/Rz±`，共 24 个方向。
- 步进：`J1…J6` 与 `X/Y/Z/Rx/Ry/Rz`，共 12 轴。
- 其他实时状态：到点运动、速度倍率、暂停、继续、停止、急停、使能、报警和工具状态。
- 当前缺口：`jog_start` 返回后 30004 没有后台唯一读者；现有 20 Hz `robot_pose` 只在驱动主动读取帧时更新，连续点动期间可能回落到 1 Hz 遥测。

### 5.2 PLC 轴（11）

十一根轴现已全部 `rigged: true`。`stroke_mm` 与 `range_mm` 于 2026-08-04 按所骑模组的
**物理行程**重定(见下方订正记)。

| 工位 | 轴 | 当前 GLB 驱动节点 | 模组 → 行程 | `range_mm` | 当前状态 |
|---|---|---|---|---|---|
| feedlift | `axis_1z` | `ST_FEEDLIFT/AXIS_AXIS_1Z/CARRIAGE.001` | CFG12-L5-600 → 600 | [−50, 550] | READY_FOR_STAGE1_VERIFY(待现场标零) |
| feedlift | `axis_2z` | `ST_FEEDLIFT/AXIS_AXIS_2Z/CARRIAGE.002` | CFG12-L5-600 → 600 | [−50, 550] | READY_FOR_STAGE1_VERIFY(待现场标零) |
| sampling | `axis_3y` | `ST_SAMPLING/AXIS_AXIS_3Y/CARRIAGE.***` | CFC30B-S300 → 300 | [−37.5, 262.5] | READY_FOR_STAGE1_VERIFY(**2026-08-05 身份订正**: 3Y=载**物料盘**的 CFC30B; 余量仅 17.5/端) |
| sampling | `axis_4x` | `ST_SAMPLING/AXIS_AXIS_4X/CARRIAGE.***` | `_LRM9RLX350` → 319 | [−107, 212] | READY_FOR_STAGE1_VERIFY(**2026-08-05 身份订正**: 4X=载**上样针**的同步带轴, 5Z 骑其上) |
| sampling | `axis_5z` | `…/AXIS_AXIS_4X/CARRIAGE.***/AXIS_AXIS_5Z/CARRIAGE.***` | `_LRM9RLX180` → 149 | [−22.5, 126.5] | READY_FOR_STAGE1_VERIFY(叠轴改挂 **4X** 下; 几何窗口整段包住控制侧限位) |
| sampling | `axis_6x` | `ST_SAMPLING/AXIS_AXIS_6X/CARRIAGE.006` | CFG4-L5-300 → 300 | [0, 300] | READY_FOR_STAGE1_VERIFY(**sign 由 +1 几何反证订正为 −1**, 待现场复核) |
| sampling | `axis_7y` | `ST_SAMPLING/AXIS_AXIS_7Y/CARRIAGE.007` | CFG4-L10-100 → 100 | [−100, 0] | READY_FOR_STAGE1_VERIFY(旧 range 是行程的 4 倍且不含唯一示教点) |
| photoscrape | `axis_8y` | `ST_PHOTOSCRAPE/AXIS_AXIS_8Y/CARRIAGE.008` | CFG5-L10-550 → 550 | [−80, 440] | READY_FOR_STAGE1_VERIFY(2026-08-04 归属订正: **载板**的 CFG5-L10-550; 本轮唯一无需改 range 的一根) |
| photoscrape | `axis_9x` | `ST_PHOTOSCRAPE/AXIS_AXIS_9X/CARRIAGE.009` | CFC30B-S400 → 400 | [−48.67, 351.33] | READY_FOR_STAGE1_VERIFY(2026-08-04 归属订正: **载刀**的 CFC30B-S400; 窗口按几何平移 11.3mm 到位) |
| photoscrape | `axis_10z` | `…/AXIS_AXIS_9X/CARRIAGE.009/AXIS_AXIS_10Z/CARRIAGE.010` | CFG4-L5-50 → 50 | [−14, 36] | READY_FOR_STAGE1_VERIFY(叠轴挂 9X 下; 旧 [0,50] 不含 CAD 位 −14) |
| rail | `axis_11y` | `ST_RAIL/AXIS_AXIS_11Y/CARRIAGE` | CFF10-L10-900 → 900 | [−54.9, 845.1] | DONE(零点已标定: 4 号工具位 500mm) |

> **2026-08-05 SAMPLING 身份互换**: `axis_3y` 与 `axis_4x` **认反了** —— 带上样针的自制同步带轴
> 原标成 3Y、带物料盘的 CFC30B-S300 原标成 4X, 连带 `axis_5z` 挂错了父轴。几何未动, 只换 id。
> 三条证据(方向惯例 / A20 清洗时序 / 清洗池几何)与遗留问题见
> [AXIS_ZERO_CALIBRATION.md](AXIS_ZERO_CALIBRATION.md) 的 2026-08-05 订正记。
> 同批按逐顶点审计补绑 6 件此前浮在原地的零件(4X×3: 5Z 驱动带轮 / 5Z 光电限位 / 扶针器;
> 5Z×2: 导轨滑块 / 皮带压板; 6X×1: 注液电磁阀), 复现图 `work/previews/audit_mod_{base,jog}_iso.png`。
> 另: 由动作页拖拽定出的 sign(3Y/5Z 那两条 2026-08-02 记录)因拖拽会随缩放翻向而作废, 退回占位。

> **2026-08-04 运动范围按轨道行程重定**: 此前十根轴的 `range_mm` 是"控制侧 limits + 拍脑袋
> 余量", 与所骑模组行程脱节 —— 地轨 [0,3000] 是 900 行程的 3.3 倍、7Y [0,400] 是 100 行程
> 的 4 倍。病根有物证: `rig_map.yaml` 的 RAIL / FEEDLIFT 工位 patterns 注释把模组**本体长**
> (1.17 m / 0.88 m)写成了"行程"(已订正)。新增 `stroke_mm` 字段固化物理行程,
> `gen_twin_manifest.check_axis_limits` 随之改为双向校验(跨度超行程报警 + 名义软界降级),
> 校验从 13 条真警告降到 **0**。定法与逐轴依据见 `AXIS_ZERO_CALIBRATION.md` §5/§5.1。

> **2026-08-04 PHOTOSCRAPE 归属订正**: 8Y 与 9X 此前认反了(把载板的模组标成 9X、载刀的标成 8Y)。
> 判据与复核数据见 `AXIS_ZERO_CALIBRATION.md` §5 的订正记; 逐项复核图在
> `work/previews/chk_ptlc_axes_{iso,top}.png` / `chk_scrape_{front,iso}.png` /
> `chk_rot_{0_before,1_after}.png`。同批把 `ps_rotate`(翻料 HRQ7, 转轴沿 Blender X、
> 枢轴由摆台**中心导向孔**圆柱面实测 R=11.82mm 残差 0.089mm)、`ps_locator`、`ps_shade`
> 三个气缸建成几何, 并把 `ps_press` 的驱动件从静止侧的 `06-013 压紧安装块` 订正为
> 杆端真正推动的吸嘴组(`06-014 接头安装块` + `03-035 导向块` + `06-028 穿板鲁尔接头`)。
> 上述四个气缸与 10Z 的层级为 `CARRIAGE.010/ACTUATOR_PS_ROTATE/ACTUATOR_PS_PRESS`,
> 由 rig_map 新增的 `build.parent_axis` / `build.parent_node` 声明(缺省仍挂工位根)。

零点标定规程与逐轴工作表见 [AXIS_ZERO_CALIBRATION.md](AXIS_ZERO_CALIBRATION.md)（2026-08-01 建立）。
配套工具：`/3d/calib` 打开 AxisDebugPanel（离线 jog 核对 carriage 归属；live 下微调
`zero_offset_mm`/`sign` 秒级生效并导出 rig_map 回填片段）；`gen_twin_manifest.py` 新增控制侧
`points/plc/*.yaml` 限位一致性校验（当前 10 根未绑轴共 13 条警告——绑定时须同步扩 `range_mm`，
否则实机负位置会被 clamp 静默冻住）。

### 5.3 气缸、阀和泵（51）

反馈类别：`both` 为开/关两端真实反馈，`partial` 为单端反馈，`commanded` 为无到位反馈、只能显示命令/估计态。

| 工位 | 数量 | both | partial | commanded | 完整 ID |
|---|---:|---:|---:|---:|---|
| develop | 32 | 8 | 0 | 24 | `dev_t1_cyl1`、`dev_t1_cyl2`、`dev_t1_cyl3`、`dev_t1_cyl4`、`dev_t2_cyl1`、`dev_t2_cyl2`、`dev_t2_cyl3`、`dev_t2_cyl4`、`dev_t1_fill1`、`dev_t1_fill2`、`dev_t1_fill3`、`dev_t1_fill4`、`dev_t1_drain1`、`dev_t1_drain2`、`dev_t1_drain3`、`dev_t1_drain4`、`dev_t1_blow1`、`dev_t1_blow2`、`dev_t1_blow3`、`dev_t1_blow4`、`dev_t2_fill1`、`dev_t2_fill2`、`dev_t2_fill3`、`dev_t2_fill4`、`dev_t2_drain1`、`dev_t2_drain2`、`dev_t2_drain3`、`dev_t2_drain4`、`dev_t2_blow1`、`dev_t2_blow2`、`dev_t2_blow3`、`dev_t2_blow4` |
| collect | 7 | 3 | 1 | 3 | `col_press`、`col_clamp`、`col_lift`、`col_extend`、`col_fill`、`col_drain`、`col_pdrain` |
| photoscrape | 6 | 2 | 1 | 3 | `ps_shade`、`ps_rotate`、`ps_press`、`ps_vacuum`、`ps_motor`、`ps_locator` |
| sampling | 3 | 0 | 0 | 3 | `smp_locator`、`smp_3way`、`smp_blow` |
| staginga | 2 | 0 | 0 | 2 | `sta_powder_locator`、`col_bottle_locator` |
| pump | 1 | 0 | 0 | 1 | `pump_vacuum` |

状态真实性规则：存在反馈时禁止用命令态覆盖实际反馈；没有反馈时必须在 3D HUD 标明 `estimated`。

### 5.4 注射泵柱塞与筒内液柱（2026-08-05 入驻）

三台润泽 SY-03B（展开 ×2 / 上样 ×1，另有收集泵 DT 3 实机在但 CAD 未建模）。外形照官方
「产品尺寸mm」图重建（总高 253.3 / 主体进深 114.5 / 前面板 55 / T-04·T-06 阀头 Ø28×35），
**并非近似节点**：占位件本身就是照该图建的，两者 253.3 / 114.5 逐位吻合。

- 几何：`blender_clean.build_pump_visuals`（仅 full 阶段建可动件）。可动节点
  `ACTUATOR_PUMP_PLUNGER_<ID>`（平移）与 `LIQUID_PUMP_<ID>`（缩放，原点在筒底）——
  两个前缀本就在 `join_static_per_station` 的保护清单里，未新增保护项。
- 契约：`rig_map.pumps` 给语义（DT 地址 / 阀头 / 缸组），`manifest.pumpSyringe` 由
  `gen_twin_manifest.resolve_pump_syringe` 生成，节点真名从 03 报告读、不字面拼路径。
- 驱动：`PumpSyringeModel`（动作事件的**相位脚本**包络）。规格是厂家额定值而非实测
  ——针筒是光管，内腔无可测特征，体素扫描给不出腔体，这与展缸溶液槽刻意不同。
- **`estimated` 恒真**：`config/plc_nodes.yaml` 里没有任何柱塞位置回读通道，这不是
  「暂时没收到反馈」而是「这条链路上不存在反馈」。HUD 那一列永远不给 `ok`。

## 6. 可动几何与阶段 0 代码审计

当前 `machine.glb`：658 个节点、184 个网格、63 个材质。节点命名 84.8% 具备语义，仍有约 15.2% 供应商自动名。

| 对象 | 当前证据 | 判定 | 阶段 1 动作 |
|---|---|---|---|
| 地轨→托盘→机器人父子链 | `CARRIAGE` 下同时存在 `ROBOT_CARRIAGE_SUPPORT`、`SOCKET_ROBOT_BASE`、11 个托盘刚体根和 `ST_ROBOT`；气动阀组与过滤减压阀仍保留各自子树 | 自动门禁通过，待视觉验收 | 500 mm 零偏与 1:1 位移统一驱动托盘、气动附件、机械臂和末端 |
| CR5 六轴 | 21 个 `CR5_*` 节点，完整 ORIGIN→ROTOR→LINK 链 | 自动门禁通过，待视觉验收 | J1–J6 ±10° 刚体回归通过 |
| 机器人底座接触/居中 | 具名 `PTLC-07-025` 支撑板和显式 `SOCKET_ROBOT_BASE`，不再扫描任意钢板 | 几何门禁通过，待用户目测 | 接触间隙、底座/托盘中心、底座/插槽、托盘/标定基准误差均 `0.0 mm` |
| Link6/快换 | `CR5_LINK6`、`CR5_LINK6_HW`、空节点 `TOOL_MOUNT` 存在 | 几何与约束门禁通过，待目测 | Link6→适配器 `0.0393 mm`；适配器→快换 `0.0495 mm` |
| 工具 | GLB 有 `TOOL_PLATE96`、`TOOL_VIAL`、`TOOL_SUCTION` 三棵独立子树 | 已补齐（2026-08-01） | 1 号吸盘在 CAD 里没包子装配，改用 rig_map `members` 聚合散件；三把刀共用快换耦合位姿，门禁实测 `0.0396°` / `0.0 mm` |
| Tool 0 标定 | manifest 为 `uncalibrated-no-valid-joint-samples` | BLOCKED_CALIBRATION | 找到正式样本前不得用于生产 FK |
| 其余 10 根 PLC 轴 | manifest 全部 `rigged:false` 且无 `AXIS_*` 节点 | BLOCKED_GEOMETRY | 从 CAD 子树分离运动件并建立 CARRIAGE |
| 展缸盖 | 8 个盖语义节点中 1 个已无网格，7 个仍有独立网格 | 不一致 | 全部重建一致的盖/连杆刚体，不靠幸存网格碰运气 |
| 上下料板仓 | 语义装配节点存在但没有后代网格 | 已被静态合并 | 从原始 CAD 重新分离 1Z/2Z 运动件与板堆 |
| 收集器/硅胶件 | 多个语义节点存在但网格为空 | 已被静态合并 | 建立独立载荷实例和插槽 |
| 样品瓶 | 收集工位和中转位存在独立瓶网格 | 部分可用 | 建立瓶/瓶组载荷语义和唯一所有权 |
| PhotoScrape | 遮光板/罩、玻璃板存在网格，8Y/9X/10Z 不独立 | BLOCKED_GEOMETRY | 按轴和气缸拆分移动组件 |
| 液位 | rig map 中 liquid 明确 `enabled:false` | NOT_STARTED | 阶段 5 使用正式液位几何/材质恢复 |

阶段 1 后静态合并保护以下前缀：

```text
TANK_ LIQUID LIGHT_STATUS AXIS_ CARRIAGE TOOL_ JOINT_ CR5_
ACTUATOR_ LINKAGE_ PAYLOAD_ SOCKET_
```

新前缀已经进入 `blender_clean.py` 门禁；后续从 CAD 分离出的气缸、连杆、载荷和插槽不会再被并入 `STATIC_*`。现有尚未分离的十根 PLC 轴与机构仍保持阻塞，必须在对应业务阶段从真 CAD 建立边界。

阶段 0 识别的运行时代码缺口及阶段 1 结果：

- `rig_map.yaml` 已升级为 `ptlc.rigmap/v2`；通用节点、执行器、连杆、附件、状态和插槽声明已进入 manifest v2。
- 正式 clip 只有 `robot.tool_pickup.yaml` 和 `robot.tool_return.yaml` 两个。
- 新增 `MachineStateDriver`，统一 axis/joint/node/actuator/linkage/attach/detach/state；`MachineRig` 仅保留 Studio 适配。
- `ClipPlayer` 已实际写入 node/actuator/linkage，并处理 attach/detach/state；`ptlc.clip/v3` 编译与 seek 回放测试通过。
- `TwinBindings` 与 Studio 已共用 `MachineStateDriver` 和 `RobotJointDriver`，不再各自计算轴/关节变换。
- Twin 已有 `RobotPoseBuffer`，但没有 `axis_pose`、`mechanism_state` 和全机构 stale 管理。

## 7. 阶段 1 实施结果与验收清单

交付摘要：

- 轴、CR5 六轴、通用节点、执行器和连杆均采用“加载态 + 绝对值”写入，重复 seek 不累积漂移。
- CR5 保持官方 ORIGIN→ROTOR 层级，控制器角度经过 `sign/zeroOffsetDeg` 后沿局部轴后乘；跨 ±180° 连续展开。
- 工具和载荷使用保持世界矩阵的重挂；锁紧后成为 `TOOL_MOUNT` 子级，释放当帧只转移父级、不吸附跳向。
- `home()` 是倒放/seek 的唯一强制复位入口，工具、载荷、轴、关节、执行器、连杆和状态均可确定恢复。
- 当前真实 manifest 的 actuator/linkage/attachment 扩展数组为空是有意门禁：尚未获得正式 CAD 归属和枢轴的机构不以近似配置冒充；对应实体在阶段 4–7 逐项加入。

阶段 1 关键产物指纹：

| 产物 | SHA-256 |
|---|---|
| `web/src/three-d/anim/MachineStateDriver.js` | `a2284a0f4920dced0ce2bca5d01827f4a92f5ecba6b4ef22bdcf0bb29ccafbb6` |
| `web/src/three-d/anim/RobotJointDriver.js` | `92a1320f75fbf438dbe0675df65738c418649e905bac969932828b3abf3edb7d` |
| `web/src/three-d/anim/clipSchema.js` | `3fb5aec2a6a48351b5a0bcd91eeddadba4df75caa8c66d43f6ee5e89065559a9` |
| `web/src/three-d/twin/bindings/TwinBindings.js` | `9a1d39d509044e5ea1efaae3369feba05100aec6cd5c17b3e42afb348c18a2ae` |
| `pipeline/blender_clean.py` | `7f850a525fce544ac9807e26c452aa71b979e9ac2caf183e8a32d8f55ee34109` |
| `pipeline/verify_robot_geometry.py` | `483e877fa3bd7dcaffdf55de73c49f72f6c6e1e13729660f40a7bd3972fcd399` |
| `pipeline/03_clean_model.py` | `c5abed6ac66f71f1039b3160401fa07b10a11072786a6813a06ecb59d80abcc2` |
| `models/device-manifest.official-cr5.json` | `4f166984bdfad9a7d59118e2f06066f04157eee426128518cb2b84cb9d5bdd70` |
| `models/machine.official-cr5.glb` | `5d16ae8f5005277c5560579b52308def84b20d6d9dc4565e51cc255912727884` |

自动验证：

- [x] 前端测试 `103/103` 通过。
- [x] Vite 生产构建通过（231 modules）。
- [x] J1–J6 各自 ±10°：上游不动、下游刚体距离不变、局部缩放为 1。
- [x] node/actuator/linkage 绝对写、重复写不漂移、home 确定恢复。
- [x] attach 当帧世界位置/方向不变，重挂后随新父级刚性运动。
- [x] 机器人底座到具名 `PTLC-07-025` 支撑面间隙 `0.0 mm`。
- [x] 底座中心→支撑板中心、底座→安装插槽、支撑板→安装插槽、支撑板→slot 4 标定基准均为 `0.0 mm`。
- [x] 支撑板、托盘滑块和 `ST_ROBOT` 全部属于同一个 `axis_11y/CARRIAGE` 刚体子树。
- [x] 用户标蓝的 `4V21008B-1`、`WEF50-N-KL-1`、`PTLC-07-027 压力表安装板-1` 全部属于同一个 `axis_11y/CARRIAGE`；前两项的子零件保持在各自装配根下。
- [x] 将 `CARRIAGE` 沿地轨方向测试平移 `100 mm`：CR5 基座及上述三个节点的世界位移均为 `100 mm`（浮点误差小于 `0.00001 mm`），其余两轴位移为 `0 mm`。
- [x] Link6→适配器最近点 `0.0393 mm`；适配器→快换最近点 `0.0495 mm`。
- [x] 2 个正式机器人片段、10 段 move_l：直线偏差 `0.0 mm`，终点误差 `0.0 mm`，最大相邻关节跳变 `4.2277°`。
- [x] 真源复核仍为 93 动作、101 流程、11 轴、51 机构、74 点（4 个全零排除）。

用户页面验收（必须在 `/3d/motion` 完成）：

- [ ] 地轨在机械臂正下方，底座与托盘接触，无悬空或穿透。
- [ ] J1–J6 调试滑杆分别做 ±10°，上游不动、下游整体刚性运动、无拉伸。
- [ ] Link6、法兰、快换之间视觉连续，无明显间隙。
- [ ] 播放 `robot.tool_pickup`：锁紧瞬间夹爪位置与方向不跳变；随后随 J6 旋转。
- [ ] 播放、暂停、回拖、跳步、倒回锁紧前后，工具父级和姿态每次一致。
- [ ] 地轨移动时完整带动机器人、快换和已挂工具。
- [ ] 地轨移动时同步带动 `4V21008B-1`、`WEF50-N-KL-1` 与 `PTLC-07-027 压力表安装板-1`，三项之间不拆散、不滞留。

## 7.1 阶段 2：实时点动与全机构状态同步

三维只读消费端与上位机只读生产端已完成：

- [x] `robot_pose`：100 ms 缓冲、连续角展开、乱序重排、重复丢弃、500 ms stale 冻结。
- [x] `axis_pose`：逐轴插值、速度保留、高频优先、1 Hz telemetry 逐轴回退。
- [x] `mechanism_state`：`confirmed` 与 `commanded` 分账，反馈优先，回退强制标 `estimated`。
- [x] `material_state`：直接镜像上位机 `MaterialStore.grid()` 完整快照，覆盖两个中转位、12 个货架托盘/72 个耗材位和 feed/waste 板仓；三维模块不维护第二套账本。
- [x] WebSocket 显式断连会标记运动/机构/物料缓冲；运动首帧直达真实状态，物料冻结最后一帧、不清空。
- [x] WebSocket 建连后在 `ready` 后立即补发 `initial: true` 的 `material_state`，无需等待下一次物料变化。
- [x] 三维模块只读轮询 `/api/materials`（2 s）补种物料快照；新鲜 WebSocket 快照始终拥有更高优先级，不新增写接口。
- [x] 实时工具号接入唯一 `MachineStateDriver`；重连时工具直接恢复到 `TOOL_MOUNT`，裸腕时恢复版本化停靠位。
- [x] 大夹爪实时挂载复用 `robot.tool_pickup` 锁紧后的局部刚体变换，不再以单位四元数错误归零；锁紧后保持为 `TOOL_MOUNT` 子节点并随 J6 刚性旋转。
- [x] 1 Hz `telemetry` 保持兼容，不会覆盖仍新鲜的高频数据。
- [x] 顶部新增可见“实时”入口，固定导航到 `/3d/live` 并复用宿主事件流。
- [x] ShowView 改为响应路由 query，并在脱机/实时模式切换时重建 TwinView，避免同路径导航复用组件而保持 `live=false`。
- [x] HUD 增加折叠的“只读实时诊断”，显示 11 轴和 51 机构的值、stale、estimated/confirmed 与 rigged/data-only。
- [x] HUD 增加“物料”入口和只读面板，显示中转 A/B、收集器/样品瓶各 6 张托盘的可用耗材数，以及上下料板仓 `count/capacity`。
- [x] 从正式 CAD 严格分离 12 个货架托盘、2 个中转载荷和 2 个玻璃板模板；上两层固定为 6 个收集器/粉桶托盘，下两层固定为 6 个样品瓶托盘；按各孔板自身朝向求解 `47.5 mm × 45 mm` 网格，生成 `14 托盘 × 6 = 84` 个逐孔耗材刚体；板仓按 CAD 实测 `3 mm` 节距生成堆叠。
- [x] 中转 A 的可搬运托盘已从固定缓存工位中独立抽出：账本为空只隐藏 PTLC-01 孔板、底板、四根支柱及耗材，PTLC-07 定位/安装结构永久留在 `ST_COLLECT`；结构门禁禁止固定机构再次落入 `INV_STAGING_A`。
- [x] 逐孔几何遵守账本语义：`FRESH` 显示；`USED` 且无 `sample_id` 视为空孔；`USED` 且有 `sample_id` 表示已装填件，仍显示。
- [x] 货架传感器映射尚未验证时只显示账本身份和一致性提示，不允许未验证 DI 覆盖物料账本；中转 A/B 已验证传感器只作一致性确认。
- [x] official manifest 写入 `ptlc.realtime/v1`、11 轴、51 机构、点表 SHA，浏览器产物不含开发机绝对路径。
- [x] 自动测试 `120/120`、Vite 生产构建、真源审计、机器人资产门禁和几何门禁全部通过。
- [x] Dobot 30004 改为单一后台反馈读取者；命令等待、DI 等待和查询改为等待条件变量中的新帧，不再并发读取反馈 socket。
- [x] `robot_pose` 由反馈观察器最高约 20 Hz 发布，包含 joint/pose/tool/mode/ts/seq；持续 jog 无需等待命令结束即可更新。
- [x] PLC 一次批读 11 轴位置/速度和 51 机构命令/传感器状态；分别以 20 Hz/10 Hz 发布 `axis_pose`/`mechanism_state`，慢周期不积压。
- [x] 地轨以实机 4 号工具位 `500 mm` 为零点，CAD +X 与伺服正方向相反，`axis_11y.sign=-1`；1 号位映射 `+0.332 m`、4 号位 `0 m`、6 号位 `-0.100 m`。
- [x] 实时快照不调用手动会话 `_touch`，不会因三维页面观察延长点动 TTL；上位机没有新增任何三维模块→设备写接口。
- [x] 上位机物料发布器每 `0.5 s` 只读 SQLite，变化立即发布、无变化每 `5 s` 心跳；独立于 PLC/机器人在线状态，慢读取不堆积。
- [x] `confirmed: null` 会立即清除旧到位态，表示机构位于两端传感器之间或反馈冲突；三维模块回退到 `commanded + estimated`，不会继续显示旧确认态。
- [x] 上位机扩大回归 `92 passed, 79 subtests passed`；物料/实时定向套件 `95 passed`，覆盖 30004 单读者、11/51 清单、无 TTL 副作用、无读取任务堆积、物料变更/心跳以及 WebSocket 首帧补种；Python 编译检查通过。

阶段 2 关键产物 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `web/src/three-d/twin/bindings/RobotPoseBuffer.js` | `8b9d8fde40864c1aa17a2a6345cc68e2a7e1b5e1ae4fa89ad4f42d7265cea20f` |
| `web/src/three-d/twin/bindings/AxisPoseBuffer.js` | `6bc66b6df3bf2d6281089ff8130f41b95b5ee8e1bf4c0bdbfccbf7622ba03a3a` |
| `web/src/three-d/twin/bindings/MechanismStateStore.js` | `93417d801786566c98db9dd17a54a60bd9e6a1bed6bb21697084e5e0e94b28c7` |
| `web/src/three-d/twin/bindings/TwinFeed.js` | `1e6cd73326b78f6193efa97a68fc83df850f60b7b18f034c26e1e44b46b53fdf` |
| `web/src/three-d/twin/bindings/MaterialStateStore.js` | `0b83399db52dabc9d10aa49fb6159a8146e5903082fcb5f51657ebade86f17f5` |
| `web/src/three-d/twin/bindings/TwinBindings.js` | `bebaf86dbd1d8195339c8bb12cdf7a156410f5830721b4b863daec82ae060687` |
| `web/src/three-d/twin/bindings/eventStream.js` | `957cf19cb433e5f1705ecae482c555bed3790de95d4ba90a77bdae026aa34029` |
| `web/src/three-d/twin/panels/MaterialPanel.vue` | `8838481cfa1b0aefb739a93ecf8e2cdf1b4da7ec23673952b296d59665e0d240` |
| `web/src/three-d/anim/MachineStateDriver.js` | `d359816388e09aa0fe43b312971e3eedde5b9c6945bcecfb93a5bd41b865a277` |
| `models/machine.official-cr5.glb` | `b75f19fa78c79698b24cc06f0f1da7adf8e87a3733fbd293c56adcda7e47b44a` |
| `models/device-manifest.official-cr5.json` | `5dc17e2500e1363e7b01bcf28f181788fb176e1830cb8f43feef59521127fd8f` |
| `pipeline/rig_map.yaml` | `8f60805f79964ba2313b8863ad3408168f9046a317aa6e00a879e2a1ce3807ec` |
| `pipeline/blender_clean.py` | `681d36d2b20b1ddc2d9be77dc70a658efe4e62d0894b7cd9e9e3752ba8b34e21` |
| `pipeline/gen_twin_manifest.py` | `84077a585f5cc78e2c975880e41babde64e8021f6f5df71f00709d99443ba479` |
| `eit_ptlc/driver/dobot_tcp_driver.py` | `716cd6916ffafe267475dadd52fad00c071dec9d25d140ad2dd148c25a9dc2c5` |
| `eit_ptlc/controller/manual_service.py` | `65f08ea2bc2fe74f5210711e87009bd50502098b7c8fcc35dc79a59fb3049377` |
| `eit_ptlc/runtime/realtime_feedback.py` | `76bdb5a68523966b61685ee51cf6eb829395230c4b6ea2a7dd9375c090d016b4` |
| `eit_ptlc/runtime/material_feedback.py` | `331df51e9d0a6b5098653e0c31cfda81796bca9b8609baec750ab285e0431931` |
| `eit_ptlc/runtime/bootstrap.py` | `e35951d3851740932f691363c23392c020f47ea377b9a863e922c1145b365e6c` |
| `eit_ptlc/runtime/events.py` | `f6534ef131eb23712e5084bd771e6727f84170cf42547864d25edf5f822fbcbb` |
| `eit_ptlc/api/app.py` | `031c575fce4656bf4fae73f4576fd55af5e66017e93044515f1eefd0e6df553f` |
| `web/src/three-d/App.vue` | `c956018c577fe7d6b972567c3dff80326ea21f1e369f2b05ac48c64702a0f69b` |
| `web/src/three-d/live/LiveView.vue` | `a34f04ac62e49fb56bc27bcfa8999361d12e7781b6ef530d4a7bfcb76bd1b77f` |

现场验收边界与后续几何边界：

- `eit_ptlc` 已实现唯一 30004 反馈泵以及 `robot_pose`、`axis_pose`、`mechanism_state`、`material_state` 四类只读生产者；既有 1 Hz telemetry 保留兼容。
- 当前环境没有连接现场 Dobot、PLC 和浏览器会话，因此方向、实际延迟、传感器极性、断网重连与急停后的真实表现仍必须由用户按下列清单核验。
- official 模型当前仅 `axis_11y` 已 rig；其余十轴与 51 机构保持 `data-only`，等待对应业务阶段按真实 CAD 分离，不猜几何。
- `data-only` 不代表实时数据缺失：11 轴与 51 机构均已发布并显示在诊断表；未完成真实 CAD 刚体分离的机构暂不驱动几何。

阶段 2 页面/现场核验（顶部“实时”，对应 `/3d/live`）：

- [ ] 机械臂 J1–J6 与笛卡尔 12 个正反方向点动时，模型方向和停止位置与实机一致。
- [ ] 持续 jog 超过 2 秒仍连续更新；正常链路视觉延迟不超过 200 ms。
- [ ] 地轨正反移动时 `axis_11y` 比例为 `1 mm = 0.001 m`，完整机器人、工具和载荷一起移动。
- [ ] 断开事件流超过 500 ms：模型冻结，HUD 显示 stale，不回零。
- [ ] 重连后：HUD 短暂显示“重新同步”，模型直接恢复真实位置，不穿模补间。
- [ ] 打开“只读实时诊断”，11 个轴 id 与 51 个机构 id 数量完整；未装配项明确显示 `data-only`。
- [ ] 有传感器机构显示 `confirmed`；无反馈机构只显示 `estimated`，命令态不能覆盖仍新鲜的反馈。
- [ ] 打开 HUD“物料”：中转 A/B 的托盘号与上位机物料设置一致；空位不显示托盘，断线后保留最后状态并标“已冻结”。
- [ ] 中转 A 账本为空时只隐藏托盘与耗材，固定中转站、定位机构和支腿仍完整显示；中转 B 同理。
- [ ] 修改收集器或样品瓶托盘的耗材状态后，对应货架卡片的 `可用 x/6` 与上位机一致。
- [ ] 同一修改会逐孔改变 3D 耗材：可用件和带 `sample_id` 的已装填件显示，真正空孔隐藏；每盘最多 6 个且孔位不漂移。
- [ ] 将托盘从货架记到账到中转位后，3D 对应货架托盘隐藏、中转位托盘出现；移回后确定性恢复，不能同时出现在两个位置。
- [ ] 修改上料仓/下料仓板数后，面板 `count/capacity` 与 3D 玻璃板堆叠数量一致，板间距保持 `3 mm`。

详细协议与生产端能力矩阵见 `docs/PTLC_REALTIME_PROTOCOL.md`。

## 8. 阶段与进度

| 阶段 | 内容 | 状态 | 验收人 | 验收日期 |
|---:|---|---|---|---|
| 0 | 真源清单、哈希、几何与代码审计 | ACCEPTED | 用户 | 2026-08-01 |
| 1 | 统一驱动、坐标、基础约束与当前几何问题修复 | ACCEPTED | 2026-08-01 | 用户确认继续下一阶段 |
| 2 | 实时点动与全机构状态同步 | READY_FOR_REVIEW | — | — |
| 3 | Robot、Rail、工具和载荷物流 | IN_PROGRESS | — | — |
| 4 | FeedLift、Sampling 与 16 个流程 | NOT_STARTED | — | — |
| 5 | Develop 与 8 个流程 | NOT_STARTED | — | — |
| 6 | PhotoScrape、Vision 与 15 个流程 | NOT_STARTED | — | — |
| 7 | Collect、Staging、Pump、Material 与 15 个流程 | IN_PROGRESS（注射泵柱塞/液柱已入驻，见 §5.4） | — | — |
| 8 | 剩余流程、全流程和并行流程 | NOT_STARTED | — | — |
| 9 | 发布与现场验收 | NOT_STARTED | — | — |

## 9. 阶段 0 验收清单

- [x] CodeGraph 索引健康：2684 文件、77617 节点、228387 边。
- [x] 93 个动作全部列入台账。
- [x] 101 个流程全部列入台账。
- [x] 11 根手动轴全部列入台账。
- [x] 51 个气缸/阀/泵全部列入台账并区分反馈可信度。
- [x] 74 个机器人原始点只读核验，4 个全零点明确排除。
- [x] 动作引用和子流程引用闭合，无未知引用。
- [x] 识别现有静态合并对可动件和载荷的破坏风险。
- [x] 识别第三工具缺失、Tool 0 未标定、10 根轴未 rig 等阻塞项。
      （更正：2026-08-01 查证「第三工具缺失」是误判 —— 零件一直在模型里，只是 CAD 未包子装配、
      安装板被静态合并吃掉；已按 `members` 聚合登记为 `TOOL_SUCTION`。）
- [x] 建立可重复执行的只读审计命令。
- [x] 用户确认动作/流程/实时控制清单没有漏项。
- [x] 用户允许阶段 1 开始修改 rig、运行时代码和模型。

## 10. 证据与限制

- 视觉证据：用户在本任务中提供的机械臂悬空、法兰/快换分离、工具方向突变截图。
- 当前环境没有可用的内置浏览器会话，因此阶段 1 没有伪造页面截图；自动几何门禁已通过，六项 `/3d/motion` 视觉检查等待用户核验。
- 由于本目录不是 Git 工作树，阶段 0 无法提供 `git diff`；后续继续用文件 SHA 和本文件进度记录追踪。
- 未取得正式 CAD 支点/尺寸的连杆机构保持阻塞，不以包围盒或截图猜轴。

## 11. 验收记录

| 日期 | 阶段 | 决定 | 说明 |
|---|---|---|---|
| 2026-08-05 | 3 | DONE | **三维模块整改: 动作/标定合并 + 新增演示栏(流程动画自动关联)**(用户提出)。**① 页签重排**: 顶栏由 `装配/材质/动作/标定/实时` 改为 `装配/材质/动作/演示/实时`; 「动作」内含 **运动模式 / 标定 / 原子动作演示** 三个子页(原「运动语义」改名为运动模式), 「演示」是与动作平级的新顶级页。**② 一个场景三个子页**: 原动作页与标定页各建一个 `SceneManager` 并各自加载 14MB GLB, 现由 `MotionWorkbench` 外壳持有唯一场景, 子页只挂拆驱动栈 —— 离线栈 `useMotionStack`(MachineRig + 板舞台 + 着色 + 拖拽 + 播放器)与实时链 `useLiveBindings`(TwinFeed + 绑定 + 事件流)**互斥**, 同一条轴被 feed 与播放器同时写会互相覆盖。为此给 `SceneManager` 补了 `detachBindings()`(把 `unloadMachineModel` 的绑定拆解那半段提出来, 两条路径拆序完全一致)。实测切子页 **零 GLB 请求**。**③ rig_map 三个写入方收编**: 运动模式的方向/参数、指认模式的 `carriage_members`、标定的零点三元组现在统一走 `motion/rigWriter.js` 的"读盘→打补丁→写"并做第三方改动检测(冲突时拒写并提示重试, 而不是闷头覆盖) —— 对应 CLAUDE.md §36 记的那次实际撞车。`rigPatch.js` 六个 patch 函数保持纯函数不动。**④ 流程动画两级生成**(用户选定口径): 一级是后端精编译 —— `flow_discovery.py` 扫 `config/operation/**` 自动发现流程(取代硬编码的 `PLATE_FLOW_ROUTES` 四条), 入参展开域由新增的 `pipeline/flow_params.yaml` **显式声明而非推断**(猜域会静默产出错误的片段矩阵), `sync_ptlc_robot.py --flows` 逐条编译并写 `clips/flow-index.json`。二级是前端即时近似 —— 新增纯函数 `demo/flowSim.js` 按脚本展开成 `ptlc.clip/v1 + debug:true` 文档, 喂给**既有** `compileClip`/`ClipPlayer`, 不新造播放器; 近似产物**只活在内存里, 不落盘**(落盘会让它在别处被当成正式片段)。**⑤ 映射表单向导出**: `clip_compiler.motion_map_document()` 把 `STATION_AXIS_ACTIONS`/`CYLINDER_ACTIONS`/`TANK_LID_ACTIONS`/`IGNORED_ACTIONS` 等序列化成 `generated/action-motion-map.json`, 前端只读不抄 —— 本仓已为"两边各留一份公式"付过一次代价(`linkageKinematics.js` ↔ `gen_twin_manifest.solve_lid_kinematics`), 映射表比那条公式大两个数量级。**⑥ 对"编译期一律 raise"纪律的受控放宽**: 只放宽在**发现器驱动层** —— 单个片段的编译器仍然 raise, 驱动层 catch 后逐条记录原因。理由可证伪: 101 个流程里大多含 `assign/human/while/for/try`, 整体退出等于产出为零。**实测覆盖率(如实记录)**: 101 条流程中 18 条 `ui.hidden`(流程界面同样不显示), 可见 83 条里 **14 条精编译 / 69 条近似**, 精编译短期上不去的原因即上述编译器限制, 外加 `clip_compiler.py:1616` + `SEAT_TEMPLATES` 缺三个单件座位那条**已知硬阻塞**(本次未修)。**验收**: 前端单测 **600/600**(更新 `hostIntegration`, 新增 `flowSim.test.js` 14 项 + `flowIndex.test.js` 5 项产物门禁); pytest **1344 passed / 1 failed**(failed 是 skip-worktree 的现场标定文件, 与本次无关的既有基线); 生产构建通过; 浏览器端到端 22 项全绿 —— 顶栏五页签、子页签三个、切页零 GLB、93 个原子动作全中文分组、`rail.move` 未填必填项时如实判"无法模拟"、填槽号 4 后翻"可模拟"并能播、**演示栏 83 行与流程界面 83 行逐条对齐**、`/3d/calib` 与 `/3d/motion/<片段名>` 两条旧链接均正确重定向、控制台零报错。**新增流程验收**(建两条探针流程后删除): 演示栏自动由 83 变 85 行、新目录自动成组、有机械动作的探针播出「1号缸关盖」、无机械动作的探针显示「该流程无机械动作」。**待办**: 精编译覆盖率的提升要么补 `clip_compiler` 对 `assign/for/while` 的支持, 要么解 `SEAT_TEMPLATES` 那条硬阻塞 —— 两者都不在本次范围 |
| 2026-08-01 | 0 | ACCEPTED | 用户明确确认“阶段 0 通过”；最新补充截图不纳入问题记录；允许进入阶段 1 |
| 2026-08-01 | 1 | READY_FOR_REVIEW | 统一驱动、rigmap/v2、clip/v3、刚体附件约束及自动门禁完成；停止进入阶段 2，等待用户页面验收 |
| 2026-08-01 | 1 | REOPENED | 用户页面验收发现圆形机器人底座未落在地轨方形移动托盘中心；原自动门禁误把相邻静态钢板当作承托面，阶段 1 重新进入修复 |
| 2026-08-01 | 1 | READY_FOR_REVIEW | 保留 P8/P9/P10 的 slot 4 基座注册，将真实 PTLC-07-025 支撑板及托盘滑块整体平移 `+339.1499 mm` 到基座下方；新门禁强制具名支撑板、安装插槽、CR5 同属 CARRIAGE，接触和中心误差均为 `0.0 mm`；停止进入阶段 2，等待用户复核 |
| 2026-08-01 | 1 | REOPENED | 用户确认地轨位置正确，但指出托盘侧的 `4V21008B-1`、`WEF50-N-KL-1` 与 `PTLC-07-027 压力表安装板-1` 未随地轨移动 |
| 2026-08-01 | 1 | READY_FOR_REVIEW | 三个用户标蓝节点已按装配根归入 `axis_11y/CARRIAGE`，`200M3F` 及 WEF50 两个子件保持组内层级；几何门禁、103/103 前端测试、轨迹验收和生产构建通过，停止进入阶段 2，等待用户复核 |
| 2026-08-01 | 1 | ACCEPTED | 用户回复“OK，继续下一个阶段的任务”；阶段 1 验收通过，允许进入阶段 2 |
| 2026-08-01 | 2 | IN_PROGRESS | 开始审计并实施实时机器人、PLC 轴、机构状态、stale/重连及只读点动镜像链路 |
| 2026-08-01 | 2 | IN_PROGRESS | 三维消费端、三类缓冲、统一驱动、只读诊断、official manifest 与 110 项测试完成；实机 20 Hz jog、axis_pose、mechanism_state 生产端因上位机目录只读而阻塞，等待用户决定是否授权修改 `eit_ptlc` |
| 2026-08-01 | 2 | IN_PROGRESS | 用户回复“继续任务”，授权在 `eit_ptlc` 范围内继续只读反馈生产端；未增加浏览器控制或设备写命令 |
| 2026-08-01 | 2 | READY_FOR_REVIEW | 唯一 30004 后台读取者、最高约 20 Hz robot_pose、20 Hz axis_pose、10 Hz mechanism_state、传感器可信度、无 TTL 副作用和三维实时消费链已完成；三维单测 110/110、上位机扩大回归 92 passed + 79 subtests、两端构建/编译通过；停止进入阶段 3，等待用户现场核验 |
| 2026-08-01 | 2 | REOPENED | 用户现场页面显示“离线”、机器人反馈为空、轴 0/11、机构 0/51；本机检查确认 18080 与 WebSocket 均正常，随后统一为 `/3d/live` 实时入口 |
| 2026-08-01 | 2 | READY_FOR_REVIEW | 顶部新增可见“实时验收”标签；实测事件流收到 ready、robot_pose、axis_pose、mechanism_state，三维单测 110/110 与生产构建再次通过；等待用户刷新后复核 |
| 2026-08-01 | 2 | REOPENED | 用户现场确认工具位正确，但 1/6 号地轨方向镜像；核对发现 500 mm 零点正确、虚拟 `axis_11y.sign` 错为 `+1`，实机六点真源不修改 |
| 2026-08-01 | 2 | READY_FOR_REVIEW | 虚拟地轨方向改为 `sign=-1` 并同步四份 manifest；新增 1/4/6 映射回归，三维单测 110/110、资产门禁、几何门禁和生产构建通过；等待用户强制刷新后复核两端方向 |
| 2026-08-01 | 2 | REOPENED | 用户现场确认实时挂载的大夹爪朝向错误，但离线取工具动画锁紧后的朝向正确且能随 J6；定位为实时恢复缺少 mountQuaternion，错误退回单位四元数 |
| 2026-08-01 | 2 | READY_FOR_REVIEW | 从正式 GLB 与 `robot.tool_pickup` 2 号目标锁紧瞬间提取 TOOL_MOUNT→TOOL_PLATE96 变换并写入 rig/manifest；实时与动画挂载位置误差约 `0.00000024 mm`、姿态差约 `0.0014°`，工具保持 J6 子级；三维单测 111/111、资产/几何门禁和生产构建通过，等待用户刷新复核 |
| 2026-08-01 | 2 | READY_FOR_REVIEW | 上位机 `MaterialStore` 已作为唯一物料真源接入 `material_state`；三维模块已同步两个中转位、12 个货架托盘/72 个账本耗材位及 feed/waste 板仓，并用正式 CAD 生成 84 个逐孔耗材刚体与玻璃板堆叠。三维单测 115/115、上位机物料/实时套件 95 passed、生产构建通过；停止进入阶段 3，等待用户重启后端并现场核验 |
| 2026-08-01 | 2 | READY_FOR_REVIEW | 修正货架分层与孔位朝向：上两层 6 个收集器/粉桶托盘、下两层 6 个样品瓶托盘；中转 B 按自身旋转后的孔板轴排布。增加 `/api/materials` 只读补种，账本变化约 2 s 内进入三维模块 |
| 2026-08-01 | 2 | READY_FOR_REVIEW | 用户发现空中转 A 时固定工位随托盘消失；已将整套 `收集瓶支架总装-1` 拆为永久固定工位与独立 `INV_STAGING_A` 载荷，显隐只作用于托盘/耗材。新增结构门禁，三维单测 120/120、几何/资产门禁及生产构建通过；继续停在阶段 2 等待页面核验 |
| 2026-08-01 | 2 | REOPENED | 用户现场确认实时验收里放刀正常、取刀（上位机 `mounted_tool=1` 吸盘）后法兰上什么都没有。定位：manifest 只声明 2/3 号刀，`syncMountedTool` 对 1 号返回 `missing` 且既无日志也无 UI；连带发现 3 号小夹爪缺 `mount_transform`（会退回单位四元数错转约 90°，与大夹爪当年同因） |
| 2026-08-03 | 3 | FIX | **推翻上一条并重做: 抓取基准取错了地方, 而工位被抬离了台面**(用户连提四条目检结论, 四条全部证实)。(1) **"中转盘位悬空了"** —— 属实: CAD 名义态三个工位的安装底板底面**全部 Y=10.00**, 正好坐在 `PTLC-08-009 大面板`(顶面 10.00)上、间隙 0.00, 它们是拧在台面上的; 上一条给的 8.5~12.1 mm 竖直平移把三个工位集体抬离了台面。(2) **"中转站被放到了机械臂地轨的底板上"** —— 属实且更糟: 中转B 被 −76.9 mm 的 Z 平移从 Z[131,321] 推到 Z[54,245], 压进 `PTLC-07-022 机器人模组固定板`(顶面 19.97) **1.5 mm** —— 物理上不可能的摆位, 而当时的门禁 48/48 全绿, 因为它只判夹爪与孔板、从不问工位脚下是什么。(3) **"如果在平面上应该正好卡在凹槽里"** —— 属实且精度惊人: 把工位放回 CAD 原位后, 中转B 的孔板中心距凹槽中心仅 **0.46 mm**(槽的竖直余量 ±0.81 mm), 中转A 2.71、货架 4.57 mm。(4) **"夹爪是夹在托盘中间位置的, 不是完全包裹"** —— 属实, 单这一条就砍掉 42 mm 误差。**我错在哪(五条, 同一个病根: 拿包围盒/单一区间代替真实特征, 本项目第三、四、五次)**: ① 抓取基准取**钳口板包围盒中心**(mount Z=−135.05)而非**凹槽中心**(−142.21), 差 7.16 mm; ② 槽深量成 1.02 mm —— 那是**倒角**, 0.25 mm 分辨率逐三角面重扫得槽底回退 **3.00 mm**、槽高 9.75 mm; ③ 由②推出"槽太松夹不住, 改判齐平唇口摩擦夹持" —— 反了, 闭合态**唇口内隙 85.46 < 板宽 85.50**(板沿被上下唇口勾住)、槽内隙 91.52 > 85.50(3 mm/侧 是插入余量), 是**榫槽卡合**; ④ 长度基准取钳口板中心(69.52), 而槽只存在于远端 **50.67 mm**(长度 86.3~137.0)、中心 **111.67**, 差 42.15 mm; ⑤ 门禁从不校验工位脚下有没有支承面。**修法**: `fit_station_alignment.py` 重写 —— `_inner_profile()` 逐三角面投影出内面剖面(0.25 mm 分辨率)、`_bands()` 按回退量聚类切出齐平唇口带与凹槽带(不再"取某个区间的顶点", 那样会把倒角当槽面), 抓取基准改为**槽心(高度) + 槽长度中心(长度) + 唇面中点(闭合)**; 判据分**硬**(板沿在槽内、唇口勾住、不顶槽底, 容差 0.15 mm —— 槽名义余量 ±0.81 但托盘与钳口有约 0.5° 姿态差, 实剩 ~0.28)与**软**(槽全落在孔板边沿上、偏心 ≤20 mm —— 用户明确说过是"大概中心, 也不是 100%", 故长度轴不做逐库位拟合); 新增**支承面门禁**(在未合并的 `machine.raw.glb` 上解析地施加声明平移, 判安装底板是否仍贴支承面 |Δ|≤0.05 mm、且无**新增**体积交叠 —— 修前它准确报出"孔板缓存安装板-1.001 捅进了机器人模组固定板-1", 修后 3/3 通过); `rig_map` 拆成两段: `station_alignment` **只吃水平、竖直恒为 0**(货架 [38.7,0,12.1] / 中转A [−22.7,0,−4.1] / 中转B [8.0,0,−34.8], 水平量较上一条从 65~82 砍到 23~41 mm), 新增 `shelf_alignment` 承担竖直(货架 4 层 4.45/5.22/4.22/5.07, 中转 2.83/0.90 mm; 中转组**必须含 `样品架支撑轴`** 否则台面浮在轴顶上, 货架组**必须含 `样品放置板`** 且其实例与层号不对应、按实测高度归层); `blender_clean.apply_station_alignment` 支持节点组, 世界向量**换算到父级局部系**(`上料架-1` 自带 180° 绕 Y 旋转, 子级直接加世界向量会 X/Z 反号), 自校从"只校位移模长"改为**校位移向量**(旋转不改模长, 老自校抓不住方向错), 并新增**缩放不变断言**(用户定的"只改位置不改尺寸"原则: 尺寸是本项目唯一独立于示教点的校验手段, 上面(1)(3)两条结论全靠它们没被动过)。**效果(48 个取放点逐一实测, 全链重跑后)**: 板心偏离槽心 **≤0.50 mm**(预算 0.81); 夹持偏心 40~47 → **≤5.3 mm**(要求 ≤20); 板沿离槽底 1.0~3.3 mm(预算 3.01/侧); 支承面门禁 3/3、设计校核 3/3、48/48 硬软全过, 退出码 0。片段的示教↔CAD 平移残差 ≤6.4 mm(`PAYLOAD_DOCK_MAX_TRAVEL_M=10 mm` 仍成立)。前端 535/535 + 生产构建通过。**判据两次订正, 理由同源**: 逐位姿曾判"唇口是否勾住"与"板沿包围盒是否在槽内", 前者名义预算只有 **0.02 mm/侧**(唇口内隙 85.46 vs 板宽 85.50)、后者判的是被 0.5° 姿态差撑到 9.06 的跨度而非真板厚 8.00 —— 两条的名义余量都小于任何可达对齐精度, 与早先那条"钳口容差 1.0 mm"是同一个毛病。现改为判**板心对槽心**(预算按真板厚算)+ **板沿别顶到槽底**(预算 3.01 mm/侧), 姿态差(≤1.96 mm)单列为观测量 —— 它是托盘与钳口的角度差, 纯平移消不掉。**另加一道防呆**: `--check` 先比 `machine.full.glb` 与 `rig_map.yaml` 的 mtime, 模型更旧即拒跑 —— 本轮真踩了: `03_clean_model.py --stage full` 的 `--output` **默认是 `machine.clean.glb` 而非 `machine.full.glb`**, 不显式给就不会覆盖下游要读的那个文件, 于是门禁照跑照报数、数字却是上一版模型的。**仍未解释**: 水平 23~41 mm 的成因; 已逐条排除地轨 slot→mm 表(中转A/B 同为 slot 3 却需不同沿轨分量)、机器人基座刚体变换(最好情况残差仍 5.0 mm)、TCP 口径(标定里 tool 1 = 160.6 mm 偏置且已正确套用: 不套用 FK 误差 161.9 mm、套用后 3.47 mm)、工具挂载变换(自校 0.0001 mm, 且换刀点与刀库 CAD 只差 ~7 mm)。留给现场一把卷尺定案。**未做**: 取料侧吸附(`attach` 支持 `dock`)—— `clipSchema.js`/`ClipPlayer.js` 正被 `plate` 原语并行修改(片段已从 22 涨到 43 条), 避让 |
| 2026-08-03 | 3 | SUPERSEDED | **盘位对齐: 货架/中转的 CAD 摆位与实机示教系不符, 夹爪没有居中夹住托盘**(用户目视发现)。**⚠ 本条结论已被上一行推翻 —— 抓取基准取错(钳口板包围盒中心而非凹槽中心), 且竖直平移把工位抬离了台面。数值与"钳口容差 1.0 mm"的理由均已作废, 保留仅为留档。**诊断三步走且中间更正过一次结论: (a) 先按"夹具板中点 vs 孔板中心"量出 65~87 mm, 但把这描述成"夹爪根本没夹到"是**错的** —— 起因是拿 TOOL_MOUNT 系的 X 当成了钳口闭合轴(实际是 Y, 内隙实测 88.4 mm, 与 rig_map 记的 88.49 吻合); (b) 改用**包含判定**(把夹具板与孔板换算到同一坐标系, 不依赖任何基准取法)得到准确观感: 夹爪**确实咬住了**孔板(135 mm 爪子有 46 mm 压在板上, 所以目测像夹住了), 但偏心 86 mm 夹在板的一端、且孔板插进单侧爪约 11 mm; (c) 逐点解出所需平移, 发现是**三个工位各自一个纯平移**(残差 0.3~5.4 mm, 故不需拟合旋转), 且方向互不相同, 一个全局变换不可能同时对齐。修法: 新增 `fit_station_alignment.py`(`--fit` 从示教点解平移 / `--check` 逐位姿包含判定门禁)与 `rig_map.station_alignment` 段, 由 `blender_clean.apply_station_alignment` 执行(含 glTF→Blender 轴系换算与位移自校)。实测平移: 货架 `上料架-1` 82.5 mm、中转A `收集瓶支架总装-1` 65.8 mm、中转B `样品瓶支架总装-1` 77.8 mm。**效果(48 个取放点逐一实测)**: 长度重叠 46~56 → **126~128 mm**(要求 ≥110); 钳口余量 −12.3~−6.7 → **−0.8~+2.9 mm**; 高度余量 −2.3 → **+9.3~+11 mm**; 片段的示教↔CAD 平移残差 6~23 → **≤7.9 mm**, `PAYLOAD_DOCK_MAX_TRAVEL_M` 随之从 30 收到 10 mm。钳口容差定 1.0 mm 而非 0: 内隙 88.4/板宽 87.2 ⇒ 居中时每侧仅 0.6 mm 名义间隙, 而逐库位示教散布约 1 mm, 刚体工位不可能让 12 个库位同时 ≥0(真机是气动柔性闭合, 亚毫米过盈属正常, 由运行期落位吸附消化)。全链重跑 + 前端 516/516 + 生产构建通过。**未决**: 工位挪了 65~83 mm, 与相邻机架/管线是否出现可见错位, 包围盒粗检未见**新增**交叠但该判据太粗, 需用户目检拍板 |
| 2026-08-03 | 3 | FIX | **修复: 货架的金属搁板被当成托盘的一部分搬走**(用户现场发现)。根因是两种建组方式不对称: `staging` 条目是"新建空节点 + 只把 members 搬进去", 固定工位天然留在原地; 而 `rack` 条目是"把整棵 CAD 装配改名成 `INV_*`", 装配里混着的货架件一并被当成托盘。实证 `PTLC-01-005 样品放置板` 在原始模型有 **12 个实例**(正好对应 12 个库位)、且**两个中转托盘装配里都没有它** —— 它是库位搁板, 不属于可搬运托盘。修法: `rig_map.inventory` 新增 `rackExclude` 段, `blender_clean.build_inventory_nodes` 在改名后把命中件挪回货架侧父级(保世界变换), 并对"命中数 ≠ 规则数 × 托盘数"硬失败(防止零件改名后静默失效, 同 CLAUDE.md 第 27 条)。另在 `export_payload_poses.py` 加一条结构门禁: **同种耗材的货架托盘与中转托盘零件数必须一致** —— 修复前实测 38 vs 37(collector)、14 vs 13(bottle), 修复后 37=37、13=13, 12 个货架托盘逐一相符。全链重跑(03 full → 几何门禁 → manifest ×2 → 04 ×2 → 载荷帧 → 24 片段), 三角形数 2,548,391 不变(搁板是**挪走**不是删掉, 已并入 `ST_RACK` 静态块), 预算门禁全过, 前端 503/503。浏览器复核托盘搬运位移 872 mm / 落位 1847 mm, 搁板不再随动 |
| 2026-08-03 | 3 | IN_PROGRESS | **落位几何闭环**。新增 `scene_kinematics.py`(编译期复算浏览器场景任意节点世界位姿, 逐字镜像 RobotJointDriver 的"局部轴后乘"与 setAxisMm; 以 manifest 已标定的 `TOOL_PLATE96` 快换变换自校, 残差 `0.0001 mm / 0.0000°`)与 `export_payload_poses.py`(逐顶点求载荷子树几何 AABB 中心, 折算回节点局部)。**关键更正**: `INV_*` 是 blender_clean 造的空节点, **原点位置任意** —— 实测 `INV_STAGING_A` 原点落在世界原点、离自身几何 655 mm, `INV_RACK_COLLECTOR_3` 离 769 mm; 早先按"节点原点距离"量出的 840 mm 落位误差是伪量, 落位门禁必须用几何。改用几何口径后实测**示教↔CAD 平移残差: 瓶组 5.8~7.9 mm、收集器组 15.9~23.2 mm**(24 条逐条留档在片段的 `compiled.dockResiduals`)。片段 `dock` 按该残差做**平移校正**(姿态保持示教点给出的物理朝向, 不动), 校正后几何落位残差 **0.0000 mm(24/24)**, 生成器对 >0.5 mm 硬失败。`PAYLOAD_DOCK_MAX_TRAVEL_M` 据实测改为 30 mm(原 5 mm 是拍的, 会把每条转移都判成坏数据)。浏览器复核: 落位后托盘挂到 `收集瓶支架总装-1`、无超阈告警; 浏览器世界坐标与编译期相差一个恒定量 `(-0.0131, 0.9919, 0.0089)`, 系 `loadMachine({center:true})` 的整体居中/落地平移 —— `dock` 是局部位姿, 对此免疫。前端 503/503、生产构建通过。**气缸装配尚未开工**, 侦察结论见下一行 |
| 2026-08-05 | 3 | IN_PROGRESS | **刮板翻料缸 + 收集站三缸装配落地**, 机构建组 8 → 11 (`ps_rotate` 由用户直接写就, 一次构建通过: HRQ7 摆台是**方**的、端面半径直方图一片平坦没有环带可拟合, 改走 `pivot.surface: bore` 取中心导向孔孔壁, R=11.817mm 残差 0.089mm、圆心与摆台包围盒中心偏差 0.000mm; `parent_axis: axis_10z` —— 整个夹持总成骑在刮板模组 Z 轴滑车上; 整只 HLH 下压缸随转子转, `ps_press` 再以 `parent_node: ACTUATOR_PS_ROTATE` 在其上平移, 两级嵌套)。**收集站三缸归属双证判定**(不照名字猜): ① PLC `plc_collect.yaml` 的 A22("推出原点 且 瓶传感器=FALSE"才允许伸出 → 空瓶座出去等机器人放瓶)、A23(缩回→升降→下压)、A41(下压复位→升降复位→伸缩伸出)三段的先后与联锁区分三个缸; ② 三条运动链逐顶点实测各自闭合, 零件名自证 —— `PTLC-03-032 推杆气缸安装板`贴在 PB10x80SU 上、`PTLC-03-019 顶升气缸滑轨安装板`贴在 MA16x70SU 上、`PTLC-03-024 注液气缸接头连接板`贴在 ACE20X90S 上。定案: `col_extend`=PB10x80SU(Blender **+Y** 80, 推杆连接块→治具安装板→定位治具, 骑 LRM9 滑块); `col_lift`=MA16x70SU(**+Z** 70, WHD51 联轴→粉末瓶定位板→夹爪安装板→HFD16X15, 骑 GVB72 轴承走两根 d12 粉末瓶下压导向轴, 轴顶由 03-016 导向连接板对拉); `col_press`=ACE20X90S(**−Z** 90, WHC01→接头连接块→接头连接板→压块连接板→注液打压塞→鲁尔接头→导向块, 骑 LRM12 竖直滑轨)。**PLC 目录里 `col_extend`/`col_lift`/`col_press` 三个 id 都在, 原方案写的"两条(± col_press)"是低估。** `col_clamp` 补 `parent_node: ACTUATOR_COL_LIFT` —— 两爪连同夹持缸整体骑在升降台上, 不声明父级会被本步抢回 `ST_COLLECT`。**基准态逐缸各判, 不套模板**: 升降的基准态是**推断**的(判据是另一个态几何上不成立 —— 若基准在上位, 落下 70 会让收集器插进瓶身 95mm), 故 CAD=落位态、写成递减 `outputRange: [70, 0]`(值1=落位=零位移), 与 `col_clamp` 同向、与 `ps_press`(基准=抬起)相反。**三次翻车全部由断言拦下, 没有一处靠眼睛发现**: ① 三条一开始写成 `build.members` —— 那是**旋转缸**路径会去做圆拟合, 报 `pivot.mesh 命中 0 个`; **直线缸必须走 `build.groups`**(对照: ps_press/col_clamp 是 groups, ps_rotate/rob_flip_suction 才是 members+pivot)。② 成员里写 `硅胶收集-1` 命中 2 个 —— `_plain_match` 的 `equals` **比对前剥掉 `.NNN` 副本后缀**, 于是同时命中中转A托盘上的 `硅胶收集-1.007`; **耗材类名字(样品瓶-*/硅胶收集-*)天然多实例, 不能用来定位机构件**。③ 由 ② 顺带纠正一处设计判断: 耗材随缸走属于**载荷托管**(P4)的职责, 不是建组的职责, 已从三条的成员里移除并写进注释。三条 `gap_check` 因此改用唯一的机构件: `col_extend` 断言缸体螺母到推杆连接块 37.0±1.0mm(伸出态会变 117)、`col_lift` 断言升降台底到导轨安装板顶 143.0±1.5mm(抬起态会变 213)、`col_press` 断言打压塞底到升降台顶 167.5±1.5mm。**行程取缸型名义值**(80/70/90), CAD 里量不到; 旁证: 下压 90 与"打压塞底距收集器口实测 91.1mm"只差 1.1mm, 自洽。**验收**: 03 建组 11/11 + 三条 gap_check 通过; **整板不退化** —— 落位对齐门禁仍 48/48, 板心最大偏离槽心 0.50mm(预算 0.81+容差 0.15)、最大偏心 5.3mm。**未完成**: 04 优化 ×2 → manifest ×2 → payload-poses → clips 重生成尚未跑(`rigged` 预计 13 → 19 待复核); `official-cr5` 那一路 `04_optimize.mjs` 与 `gen_twin_manifest.py` 都没有对应开关, 正确调用方式待查, 未用猜测参数动产物。**P3 有硬阻塞(不是工作量问题)**: `clip_compiler.py:1616` 规定编译结束载荷仍在爪里即硬失败, 而 `SEAT_TEMPLATES` 里单件的三个目的地(刮板夹具/收集夹具/收集瓶座)**没有座位**, 故 M1/M4 那类"中转→工位"片段**编译不出来**, 原方案的"FK-only 落位"绕不过这一条。**但 P2 恰好使其可解**: 三个落点现在都是真节点(`硅胶收集-1.008`在 `ACTUATOR_PS_ROTATE` 下、`硅胶收集-1`在 `ACTUATOR_COL_LIFT` 下、`样品瓶-2`在 `ACTUATOR_COL_EXTEND` 下), 登记成座位后落位能**自动随缸走**, 比 FK-only 更好 —— 代价是要动 `rig_map.inventory` 的分类结构(现只有 rack/staging/magazines/consumables 四类, 需加"工位夹具")+ `gen_twin_manifest` 的展开 + `SEAT_TEMPLATES` 三处, 属设计决定, 下一轮开工前先定。**待目检**: `/3d/live` 驱三个缸 0↔1 看行程量与方向(尤其升降的基准态是推断的), 不对只改 rig_map 里那一个数 |
| 2026-08-05 | 3 | DONE | **上样工位 3Y↔4X 身份互换 + 动作页拖拽翻向修复 + 上样五轴漏绑审计**(用户报 5 个缺陷)。**① 拖拽翻向(根因)**: `AxisDragController` 用两条异面直线最近点的闭式解, 两处硬伤 —— 跟的是**轴线**不是抓取点, 增益正比于"相机↔轴线距离"(同一次 20mm 拖拽: 22.2m 得 20.1 / minDistance 0.222m 得 **29.3** / 枢轴偏离 1m 时 **98.9**, 5 倍); 解含 `1/(1−(d·rd)²)` 近平行时发散, 旧码硬切到"沿轴**1 米探针** + NDC 位移"的第二套估计器, 推近时探针落到眼平面之后, `project()` 除以负 w 把 NDC 整体镜像 ⇒ **方向翻 180°**(俯视 12° 实测: 22.2/4.23/1.0/0.5m 给 +20mm, **0.3/0.222m 变 −27.1/−26.1mm**, 与用户"缩小正常放大变反"逐字吻合); 另有 `s0` 播种坑(退化分支读还是 `null` 的 `drag.s0` 按 0 播种), 正视轴线时把轴甩到 **4233mm** = 相机距离的毫米数。改为**拖拽平面投影**(three.js TransformControls 同法), 近平行姿态明确拒动并回报 `blocked` 给 HUD。回归测 `web/tests/three-d/axisDrag.test.js`(三档相机距离 × 三轴向 × 俯视角, 判据"从 `screenOf(抓取点)` 拖到 `screenOf(抓取点+轴向·Δ)` 应恰好走 Δ", 与透视无关): 修前 8 红, 修后 24/24。同类排查: `PickController`/`MaterialsScene`/`WorkbenchScene` 只做拾取不做屏幕↔世界距离换算, 全仓 `src` 只剩 1 处 `.project()`(Playwright 钩子), 无第二处。**② 3Y↔4X 认反**(用户指出"XY 运动方向全工位一致"), 三条独立证据: 方向惯例(X 族恒 glTF Z / Y 族恒 glTF X, 十一根轴只这两根违例且互为对方)、动作时序(A20 `sampling.clean` 只动 4X+5Z 把针送清洗池、A10 明写"只把3Y目标写为0并未命令3Y移动")、几何(针管清洗池距针 156.85mm 正落在该轴 +Y 窗口内)。几何未动只换 id, `axis_5z.parent_axis` 3Y→**4X**; `zero_offset` 重解 4X=**79.85**(range [−107,212]) / 3Y=**41.1**(range [−37.5,262.5])。**③ 漏绑 6 件**(用户报"4X 至少少绑 4 个"): 逐顶点审计 + 用户指认 —— 4X 补 `EBF41` 5Z 驱动带轮 / `ZJF45-…-5` 5Z 光电限位 / `PTLC-05-015 扶针器`(**推翻 2026-08-01 记在注释里却从未写成规则的"扶针器归 5Z"**: 它顶面与注液模组安装板底面贴合 **0.00mm**, 离每个 5Z 成员都有 22.5~53.5mm), 5Z 补 `_LRM9BK` 导轨滑块(与 05-011 贴合 0.00mm) / `ECY51-…-2` 皮带压板, 6X 补 `V14T24` 注液电磁阀。**注意**: 用户目测的"4 个"里有一部分其实是 `螺钉-3-*`(被 `luo_ding` 规则删)与 `ZJF45-…-1..4`(在 `explicit_delete` 里), 已删的件不能写规则否则 `expect_count` 硬失败。**验收**: 03 建组 **11/11**; `check_axis_limits` **零警告**("控制侧示教点全部落在 range_mm 内"); `verify_axis_travel` 全部在轨, **`axis_4x` 出轨 0.00mm 且窗口两端正好贴住导轨两端**(zero_offset 的独立自证), 最大出轨 3.36/容差 5.0; 05 预算五项全过(13.96MB/408 图元/2.43M 三角/命名 88.1%/执行器存活 0); web 单测 571/571; 复现与复验图 `work/previews/audit_mod_{base,jog}_iso.png` → `fixed_mod_jog_iso.png`(补绑件由浮在原地变为整体随行)。**顺带关闭上一行的两个未完成项**: 规范调用参数在 `runtime/three_d_authoring.py::_rebuild_steps`(official-cr5 靠 **`--no-join`** 区分, 输入同为 `machine.full.glb`; 03 少写 `--output ../work/machine.full.glb` 会写成 `machine.clean.glb` 且不报错), 全链跑通; **`rigged` 16 → 19 已复核**(新增 col_extend/col_lift/col_press)。**待现场**: 4X/3Y/5Z 的 `sign` 全部退回占位(旧值由会翻向的拖拽判出, 已作废), 按七步法第 2 步实机 jog 定; 另遗留"清洗池距针 156.85mm 而控制侧 4X limits 跨度只有 115mm"未解释, 按 §5.1 第 3 条只写注释未动 zero_offset |
| 2026-08-04 | 3 | IN_PROGRESS | **两个约束缸装配落地**(`ps_press` / `col_clamp`), 机构 rigged 计数 11 → 13。`col_clamp` 是 linkage(双指 `ACTUATOR_COL_CLAMP_L/R`, 成员 = `_HFD16X15(CL)_t-2/t-3` + `PTLC-03-029/028` 两只夹爪), **`outputRange` 取递减 `[7.5, 0]`** —— CAD 基准态是空爪紧闭(两爪内面沿全高逐层实测 0.10 mm), 故值1=夹紧=零位移、值0=张开; `MachineStateDriver.mapRange` 是 `from+(to-from)*normalized` 的直白线性映射, 支持递减。`ps_press` 是直线 actuator(`ACTUATOR_PS_PRESS`, 成员 = `_HLH6X20-S(0)_rod` + `PTLC-06-013 压紧安装块`), 基准态是抬起, 压下 = 走 **−Y**(用户目检定"下压离粉桶更近的方向"; 几何佐证: 粉桶中心 Y=318.2 在杆 375.8/缸体 348 之下, 而 +Y 是上)。**两个缸的基准态约定相反, 不能套同一模板。****方向已在产物上复核**(不是靠父节点推断): 三个新空对象 `ACTUATOR_COL_CLAMP_L`(X=183.6) / `_R`(X=211.2) / `ACTUATOR_PS_PRESS`(Y=339.7) 在 GLB 里全部 `rotation=None, scale=None`, 父级 `ST_COLLECT`/`ST_PHOTOSCRAPE` 亦是无旋转无缩放根节点 ⇒ 局部轴 = 世界轴, `sign`(L=−1 / R=+1 / press=−1)成立。**两条可失败断言**: `col_clamp` 的 `gap_check` 断言**闭合态**两爪内面 0.1±0.5 mm(与 `rob_grip_plate96` 断言"GLB=张开态"正好互补, 已实测通过); `ps_press` 的 `gap_check` 断言杆底与块顶贴合(−3.0±1.0 mm) —— 后者是补加的, 因为建组只校 `contains` 名字命中、不校选的是不是同一条运动链上的件, 没有它则被动件挑错(如误选 `PTLC-06-011 硅胶收集器安装板`)无人能挡。配套: `blender_clean.build_end_effector_actuators` 已泛化(作用域 `tool`/`station` 二选一; 直线缸与双指夹爪共用建组路径, 原分支硬要求的环带圆拟合是旋转缸专用)。**行程量未经实测**: 7.5 mm/指 与 20 mm 取自缸的名义规格(HFD16X15 / HLH6X20), 张开态与压下态 CAD 都没画、量不到, 观感不对时改这两个数即可。**收尾被三道机器判据各拦一次, 三次都拦对了, 没有一处是靠眼睛发现的**: ① `ps_press` 的 `gap_check` 实测 −35.0 ≠ 期望 −3.0 —— **`gap_check.axis` 用的是 Blender 轴系(Z 向上), 而同一文件的 `translate_mm` 用 glTF 轴系(Y 向上)**; −35.0 与"Blender y = glTF −z 上的间距"手算逐位吻合, 故是轴写错而非被动件挑错, 改 `axis: z` 后通过。**一个文件里并存两套轴系, 改 gap_check 前先确认用哪套。** ② `gen_twin_manifest` 报 "rig_map actuators 的机构 id 与 PLC 目录冲突: ps_press" —— `catalog:` 段是给**不在 PLC 机构目录里**的机构(机器人侧那三个夹爪)用的, 这两个本就在目录里, 重复声明会造出"永远驱动不了的幽灵条目"; 删掉 `catalog:`、条目留在 `actuators`/`linkages` 里即可把既有 PLC 机构标成 rigged。③ 我自己的重跑脚本写成 `03 ... | grep ... || true`, 管道把 03 的退出码换成了 grep 的, 于是 03 断言失败后 04 仍拿旧模型编了一遍 —— 改为先落日志再 grep 并 `set -euo pipefail`。另: 改 rig_map 后 `--check` 被本轮新加的 mtime 防呆拦下(模型比配置旧), 按提示重建后放行, 防呆按设计工作。**验收**: 落位门禁 48/48 + 支承面 3/3 + 设计校核 3/3; `rigged` 11 → 13; 预算门禁全过; 前端 535/535 + 生产构建通过。**未完成**: 25 条单件片段一条没有; `ps_rotate` 未装配 —— 而用户目检定案"先反转后取"意味着不做它 M2 会**没翻转就被取走**, 动作次序在视觉上是错的, 故已从 P4 提到与本批同级。**待目检**: 两个缸的**行程量**(7.5 mm/指 与 20 mm)取自缸的名义规格, 张开态/压下态 CAD 都没画、量不到, 只能在 `/3d/live` 手动驱 0↔1 看观感, 不对就改这两个数 |
| 2026-08-03 | 3 | NOTE | **约束缸侦察 + 用户目检定案两条**。用户裁定: 中转 A/B 两个定位缸(`sta_powder_locator`/`col_bottle_locator`)**不做动画**, 改做约束缸(`ps_press`/`col_clamp`)+ 单件片段。侦察结论: 两个缸都**几何可分、不必拆网格** —— `col_clamp` = `HFD16X15_CL_-1`(`_b-1` 缸体 + `_t-2`@X=183.6 / `_t-3`@X=211.2 双指, 与 `PTLC-03-029/028` 两只夹爪的 X 逐位对上; 与已装配的 `rob_grip_plate96` 是 HFD 同族), `ps_press` = `HLH6X20S_0_+_DMSH-2_-1`(`_rod-1`@Y=375.8 + `_body-1`@Y=348, 轴=Y, 行程 20), 被动件 `PTLC-06-013 压紧安装块-1`。**`col_clamp` 夹的是粉桶不是瓶**(manifest 标签「收集夹持气缸」与 CAD 零件名「收集**瓶**左/右夹爪」矛盾, 后者的"收集瓶"是**工位名**): 双证据 —— `collect_load` 时序是 `放粉桶 → collect.clamp → 退出 → extend → 这才放瓶`, 动作码 A21 原文写"**收集器**必须正确落座""本动作不驱动伸缩、升降或瓶定位气缸"; 几何上夹爪在 Y=391 落在粉桶(Y 309.9~429.4)高度带内, 瓶(Y 214.7~309.7)整个在其下方。**两个缸的基准态约定相反, 不能套同一模板**: `col_clamp` 的 CAD 基准是**空爪紧闭**(两爪内面逐层实测 0.10 mm, 粉桶 Ø27.99 是画上去示意的、与闭合爪穿模), 故值1=夹紧=零位移、值0=张开, 需递减 `outputRange: [7.5, 0]`(`MachineStateDriver.mapRange` 是直白线性映射, 支持递减); `ps_press` 的 CAD 基准是**抬起**, 压下 = 杆走 **−Y**(用户目检定: "下压离粉桶更近的方向"; 几何佐证: 粉桶中心 Y=318.2 在杆 375.8 与缸体 348 之下, 而 +Y 是上)。**另一条用户目检定案: 刮板站粉桶必须"先反转后取"** —— 与 `collect_load` 编排逐字吻合(`scrape_finish` A41 翻料倒粉 → `press_cylinder(false)` → `robot_scrape_holder_pick_exit` → `retr_stoprot` A52 复位, 注释原文"接粉收集器**已由机器人取走并退出后**才允许旋转复位")。**含义: `ps_rotate` 不是可有可无的观感件** —— 不做它, M2(粉桶 刮板→收集)播出来就是没翻转就被取走, 动作次序在视觉上是错的; 原先把它排在 P4 最低优先级的判断作废。配套代码改动: `blender_clean.build_end_effector_actuators` 泛化 —— 作用域从"只认刀具侧 `build.tool` + `{tool}_GEOMETRY`"改为 `tool`/`station` 二选一(工位侧解析到 `ST_<id>`), 且直线缸(actuator + `build.groups`)与双指夹爪共用建组路径(原 actuator 分支硬要求环带圆拟合, 是旋转缸 `rob_flip_suction` 专用)。已跑 03 回归: 三个既有机构照建、工位对齐 9 条照施、落位门禁仍 48/48 + 支承面 3/3, 退出码 0。**未落 rig_map**: `col_clamp` 的张开 `sign` 还取决于 `ACTUATOR_COL_CLAMP_L/R` 在 `ST_COLLECT` 下的局部系是否翻转 X(本项目栽过多次的同类坑), 要先建出来读世界矩阵再回填 |
| 2026-08-03 | 3 | NOTE | 转移路径气缸侦察: 中转 A/B 定位机构 = `PTLC-07-031 料架定位气缸安装板` + 2 个 `MP16X5B3M5X6`(缸径16/**行程仅 5 mm**) + `PTLC-07-032/033 对角定位机构/轴承安装板` + 2 个 `PTLC-07-034 料架定位边`。两点阻碍: (a) 按几何位置, 两条"定位边"在托盘的低 X/低 Z 侧、气缸在高 X/高 Z 侧, 更像**固定基准边**而非运动件, 真正动的是缸杆 —— 而 `MP16X5B3M5X6` 是缸体+缸杆同一个单体网格, 要动就得先做区域拆分(同 CLAUDE.md 第 28 条); (b) 行程只有 5 mm, 整机尺度下几乎看不见。**结论: 这两个缸性价比最低, 不应先做。**性价比最高的是收集站的 `col_extend`(伸缩到放瓶位)与 `col_lift`(抬瓶), 它们行程大且**真的带着样品瓶移动**, 属于"气缸完成的转移" |
| 2026-08-03 | 3 | IN_PROGRESS | 托盘转移(整板)第一段落地: rig_map 新增 `payloads` 段 → manifest 26 个 attachments(可携带) + 98 个 states(可显隐, 两者刻意不同批); `clip_compiler.py` 泛化了 operation→clip 编译器(表达式/分支求值、`run_script` 递归内联、气缸→actuator、夹爪→linkage+attach/detach); `sync_ptlc_robot.py --transfers` 生成 4 条路线 × 6 库位 = 24 个片段, `clips/index.json` 升 `ptlc.clip-index/v2` 带参数域; `/3d/motion` 新增参数化转移面板(种类/方向/库位三个下拉)。`detach` 原语新增 `dock` 字段与 `MachineStateDriver.dockPayload()`(独立阈值 `PAYLOAD_DOCK_MAX_TRAVEL_M=0.005`, 比工具吸附严 —— 粉桶要坐进凹槽)。前端 425/425、生产构建通过; 浏览器实测片段可装载可播放、控制台零错误; seek 确定性以受控 A/B(单调前进 vs 回家重放)在 4 个时刻实测 **0.0 mm**, 并与既有 `robot.tool_pickup` 对照一致。**未完成**: 落位位姿(`dock`)尚未计算, 托盘目前落在 FK 推算处而非 CAD 中转位, 视觉误差**未测量**; 8 个转移路径气缸仍 `rigged:false`(片段照发 actuator 步, 几何不动)。下一步是 `blender_clean` 补 `matrix_world` 导出 → `payload-poses.json` → dock 推算 + CAD 复核门禁 |
| 2026-08-01 | 2 | READY_FOR_REVIEW | 更正「1 号吸盘缺少 CAD」的历史误判：零件一直在模型里，只是 CAD 未包子装配、安装板被静态合并吃掉。`build_tools` 新增 `members` 散件聚合（只收未被前序工具认领的对象），登记 `TOOL_SUCTION` 16 件网格，快换点 `[-0.546055, 0.256974, -0.421546]` 与标定 slot-1 逐位一致；3 号刀补齐 `mount_transform`。新增工具侧快换同朝向/共线门禁（实测 `0.0396°` / `0.0 mm`）与「工具声明未命中即硬失败」；HUD 只读诊断新增「末端工具」行，控制器报了模型未声明的刀号时显式告警。三维单测 119/119、预算 219/500 图元、几何/资产门禁与生产构建通过，三工位配色渲染目检三把刀齐全、料架未被带走；等待用户在 `/3d/live` 复核 |
| 2026-08-05 | 3 | FIX | **工位摆位偏差溯源: 23~41 mm 里有 18~28 mm 是记错账的**(用户提出"实机中转A/B 与 SolidWorks 总装图差得不多, 反而与三维数模差得很远")。**① 定位**: 把 `need` 转进**夹爪法兰系**后, 三站主项全部落在**同一根轴、同一方向**(长度轴 −38.62 / −22.75 / −34.79 mm), 世界系里"三个方向互不相同"只是三站进刀偏航角不同造成的投影假象 —— 此前反复排查找不到"共同成因", 病根是一直在世界系里比。(`verify_plate_seats` 早就总结过"跨站比较必须转法兰系", 当时只用在吸盘那条链上。)**② 成因假设对照**(新增只读诊断 `pipeline/diagnose_station_offset.py`, 以 CAD 原位下 48 个 `need` 为观测量): 无修正 rms 35.95 → 地轨零点(1 自由度) 32.35 / 整机统一平移(3) 31.97 / 机器人基座刚体(6) 29.13 —— 三个"全局"假设几乎无解释力(基座刚体还会让 P8/P9/P10 换刀位注册劣化 11.3~12.0 mm, 故**不要动**); 而**仅法兰系长度轴常量(1 自由度)就把 rms 砍到 12.53**, 三轴刀具常量砍到 7.86。但"改刀具常量"物理上不成立: 长度轴要 +33.7 mm 会把抓取基准推到局部 +145.36, 而夹具板只到 +137.03。**③ A/B 实测**: 把 9 个平移量归零重建整机, 在同一套订正后的抓取基准下重测 —— CAD 原位 48/48 **全不合格**(夹持偏心 21.7~42.2 mm、板沿顶到槽底最大 10.81 mm), 现役 48/48 全过; 且在 CAD 原位从零独立重解, 解出的数与现值**逐位相同** ⇒ 现值是可复现的测量, 不是累积漂移。**④ 现场复核定案**(把内部坐标换算成用尺子能量的量: 夹具板最前端离托盘中心还有多远): CAD 原位预测 货架 13.3 / 中转A −2.6 / 中转B 9.4 mm(**够不到中心, 只咬靠机械臂那一半**), 现役预测三站一律 **越过中心 25.4 mm**。用户现场答复"夹爪下齿咬合托盘靠近机械臂那一半, 最前端离托盘中心还有两厘米左右" —— 与 CAD 原位同向同量级, 与现役**方向相反**。**⇒ CAD 摆位是对的。** **⑤ 病根是判据**: `MAX_GRIP_OFFCENTER_MM = 20` 源自 2026-08-03 把用户"夹爪是夹在托盘中间位置的, 不是完全包裹"读成了"要求夹在中段"(原话说的是**包裹范围**不是**定位要求**), 写成软判后**反向驱动**了工位摆位: 为了让偏心达标, 三站各被多挪了 18~28 mm, 而门禁照样 48/48 全绿 —— 逐站 3 个自由度足以吸收任何来源的误差, 绿只证明"托盘被挪到了机器人以为的地方"。用户原话: "我本来也没有让夹持就要夹持在中间…你凭什么假定它一定要加到中心上"。**⑥ 修法**: `report_fit` 改为**只按硬约束轴解算**(闭合轴的榫槽卡合 0.13 mm/侧 + 高度轴的槽高余量 0.81 mm), 长度轴放开; 解算前先把 `need` 加回"该载荷已施加的总平移"还原成**相对 CAD 原位的总偏差** —— 硬轴约束必须加在总量上, 加在增量上等于默认现值的长度轴分量是对的(已用现役/CAD 原位两版构建互验同值)。⚠ 该最小二乘**秩亏**(每个位姿只约束 2 个方向, 长度方向落在零空间), 必须 `rcond=1e-3` 取最小范数解 —— 默认 `rcond=None` 实测解出 **+153614 mm** 的伪平移却报"残差 0.00"。夹持偏心降为**纯观测量不再判失败**(它由示教点决定、几何不约束, 当判据就会反向驱动人去挪工位); `槽被覆盖`保留为判据, 那是真的物理有效性。**⑦ 回填**: `station_alignment` 货架 `[38.7,0,12.1]`→**`[2.8,0,12.4]`**(40.5→**12.7 mm**)、中转A `[-22.7,0,-4.1]`→**`[0.0,0,-4.1]`**(23.1→**4.1 mm**)、中转B `[8.0,0,-34.8]`→**`[8.1,0,0.0]`**(35.7→**8.1 mm**); **`shelf_alignment` 六个值不动** —— 新口径重解出 4.45/5.22/4.22/5.07/2.83/0.90 与现值逐位相同(长度轴基本是水平的, 去掉它对竖直几乎无影响)。硬轴残差从现役全轴拟合的 5.41 降到 **1.36 mm**: 少挪了 18~28 mm, 拟合反而更紧。**⑧ 另外 4 站一并量出**(从未对齐, 全在 CAD 原位): `verify_plate_seats` 退出 0, 上样 5.4 / 刮板台 5.4 / 上料仓 7.0 / 废板仓 6.5 / 展缸1-4 2.5~5.9 mm 彼此吻合到 5~7 mm ⇒ 吸盘那条链上没有 23~41 mm 量级的站间散布; 唯一例外是**展缸架2(缸5-8)整体差 24.9~29.3 mm**(另一件事)。⚠ 口径差异: `verify_plate_seats` 判**站间一致性**(相对中位数, 对"所有站共同的偏移"免疫), `fit_station_alignment` 判**绝对偏差**, 两者绝对值不能直接比。**验收**: 全链重建 6 步全 0; 落位门禁 **48/48 退出 0**(板心最大偏离槽心 0.55 mm/预算 0.81+0.15), 支承面 3/3(三站底面仍 Y=10.00 贴大面板, 间隙 +0.00), 设计校核 3/3; 观测量·夹持偏心最大 41.1 mm(如实报出不判)。**并发事故(已恢复)**: A/B 期间另一会话/前端在 07:11 触发了全链重建, 读到我临时归零的 `rig_map`, 于是 `models/` 六个产物在 07:15~07:17 被以归零配置部署; 已恢复并重建。教训: 这类 A/B **应当用独立输出文件名 + 独立 rig_map 副本**(`--model` / `--rig-map` 都支持), 不要动共享的 `machine.full.glb` 与 `rig_map.yaml`。全文见 `docs/工位摆位偏差溯源_20260805.md` |
