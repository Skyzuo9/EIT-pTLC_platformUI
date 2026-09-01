# PTLC 三维模块只读实时协议

> 协议：`ptlc.realtime/v1`  
> 通道：既有 `/api/ws/events`  
> 方向：上位机 → 三维模块；三维模块不新增机器人、PLC 或物料控制接口

## 1. 通用规则

- `ts` 为 Unix 时间。接收端兼容秒和毫秒，小于 `1e12` 的值按秒换算。
- `seq` 在同一连接、同一消息类型内单调递增；重连后允许从 0 或 1 重新开始。
- 重复 `seq` 不刷新新鲜度；乱序运动帧按 `ts` 重排。
- 机器人与轴使用约 100 ms 时间缓冲。超过 500 ms 无有效运动帧时冻结末态并标记 `stale`，绝不回零。
- 物料是低频持久化快照，不做插值。断线后保留最后一帧；超过 12 s 或显式断连时标记“已冻结”。
- WebSocket 连接成功后先发送 `ready`，紧接着发送一帧 `initial: true` 的完整 `material_state`，客户端不必等待下一次盘点。
- 若 6.5 s 内没有收到 WebSocket `material_state`，三维模块每 2 s 只读请求 `/api/materials`；一旦收到新鲜 WebSocket 快照即停止以 REST 覆盖。
- 高频实时事件优先于既有 1 Hz `telemetry`；高频源陈旧后才允许按字段回退。
- 有传感器的机构由 `confirmed` 决定；无反馈时可以使用 `commanded`，但必须显示 `estimated`。

## 2. `robot_pose`

```json
{
  "type": "robot_pose",
  "joint": [0, 0, 0, 0, 0, 0],
  "pose": [0, 0, 0, 0, 0, 0],
  "tool": 2,
  "mode": 7,
  "ts": 0,
  "seq": 0
}
```

- `joint`：必填，6 个有限数，单位为度。
- `pose`：可选，`x/y/z/rx/ry/rz`，沿用 Dobot 反馈单位。
- `tool`：上位机 `mounted_tool`；`0` 表示裸腕。
- `mode`：Dobot 机器人模式码。
- 目标发布频率不超过 20 Hz。

关节角在时间序列中连续展开，跨 `±180°` 不产生整周跳转。工具号变化通过统一驱动层改变刚体所有权；工具锁紧后属于 `TOOL_MOUNT` 并随 J6 刚性旋转。

## 3. `axis_pose`

```json
{
  "type": "axis_pose",
  "positions": {"axis_1z": 0, "axis_11y": 500},
  "velocities": {"axis_1z": 0, "axis_11y": 20},
  "ts": 0,
  "seq": 0
}
```

- `positions`：至少一根轴，单位 mm；推荐每帧包含全部 11 轴。
- `velocities`：可选，单位 mm/s。
- 目录固定来自 `config/manual_points.yaml`，只允许 11 个已登记轴 id。
- 目标频率 10–20 Hz，慢周期直接跳过，不排队补发旧帧。

当前 official 模型只正式装配 `axis_11y`。其余十轴会出现在只读诊断表中，但在对应 CAD 刚体完成分离和枢轴标定前保持 `data-only`。

## 4. `mechanism_state`

```json
{
  "type": "mechanism_state",
  "states": {
    "ps_shade": {
      "commanded": true,
      "confirmed": true,
      "source": "feedback"
    }
  },
  "ts": 0,
  "seq": 0
}
```

- `states` 可包含 51 个目录机构中的任意子集。
- `commanded` 表示写入目标；`confirmed` 表示传感器实际到位。
- `source` 使用 `feedback`、`commanded` 或 `estimated`。
- `available: false` 表示本周期无法读取。
- `confirmed: null` 表示机构位于两端传感器之间或反馈冲突；客户端必须清除旧到位态并显示 `estimated`。
- `manual.cylinder.<id>` 的 `step_done.result={id,on}` 只写入 `commanded`，不能冒充 `confirmed`。
- `moving: true` 表示**命令已下发但行程未结束**。字段可选，缺省视同 `false`；当前唯一的
  发布方是 `rob_flip_suction`（`robot_controller._TWIN_INFLIGHT_ACTIONS`）。它与
  `commanded` / `confirmed` 正交，**只说阶段不说位置**，任何情况下都不得用来冒充到位。
  客户端据此让动画与实物同时起步、保持在终点前一小段，收到 `moving: false` 再合上最后一段。
  - 为什么需要它：`robot.tool_action` 的旋转是 `di_or_dwell`（`app.yaml` 的 `tool_confirm`），
    等 DI 上限 `tool_di_timeout` 10 s、等不到才回退 600 ms dwell，**单次行程 0.6~10.8 s 不定**，
    任何"按固定时长播一段"的客户端动画都对不齐。
  - 为什么不复用 `confirmed`：dwell 兜底那一路永远不给 `confirmed`（如实表达，不伪造），
    只认它会让动画永久停在终点前。`moving` 无论 DI 通不通都必然落到 `false`。

## 5. `material_state`

```json
{
  "type": "material_state",
  "initial": false,
  "seq": 12,
  "ts": 0,
  "cells": [
    {"kind": "collector", "plate": 1, "hole": 1, "state": "FRESH", "sample_id": ""}
  ],
  "staging": {
    "staging-a": {"area": "staging-a", "kind": "collector", "plate": 1},
    "staging-b": {"area": "staging-b", "kind": "bottle", "plate": null}
  },
  "transit": {
    "gripper_plate96": {
      "carrier": "gripper_plate96", "payload": "tray", "kind": "collector",
      "plate": 3, "hole": null, "from_loc": "rack", "to_loc": "",
      "since_at": 0, "run_id": "", "script": "robot_group_rack_pick"
    }
  },
  "summary": {},
  "presence": [],
  "presence_mismatches": 0,
  "magazines": [
    {"magazine": "feed", "count": 6, "capacity": 30},
    {"magazine": "waste", "count": 8, "capacity": 30}
  ],
  "bottles": [],
  "topology": {}
}
```

语义和映射：

- `MaterialStore.grid()` 是唯一事实源，三维模块不维护第二套库存账本；人工盘点**写入**经
  上位机既有端点提交（见 §5.1），提交后仍以推流快照回读，前端不保留第二份状态。
- `cells` 固定覆盖 `collector` 和 `bottle` 两类，各 6 张托盘、每盘 6 个耗材位，共 72 格。
- `staging-a` 对应收集器中转托盘，`staging-b` 对应样品瓶中转托盘。**落位后**，3D 隐藏对应货架托盘并显示中转位托盘。
- `transit` 是取放过程中的中间态：载荷此刻挂在哪把夹爪上。按 `carrier` 索引，两把爪都空手时是空对象。
  - `carrier`：`gripper_plate96`（2 号大夹爪，整板）/ `gripper_vial`（3 号小夹爪，单件）。
    名字与 `rig_map` / `device-manifest` 的机构 id 同源，3D 据此把载荷换父挂到 `robot.toolMount`。
  - **1 号吸盘刀（薄层玻璃板）刻意不在此列**：它的位置权威是 `experiments.db` 的 `samples.position`，
    经 `GET /api/scheduler/snapshot` 下发（见 §5 之外的板层链路）。收进来就成了第二套板账本。
  - `payload=tray` 时 `hole` 为 null，身份是 `(kind, plate)`；`payload=item` 时身份是 `(kind, plate, hole)`。
  - 在途期间该载荷**既不在货架也不在中转位**：货架侧 `rack[].present=0`，中转侧 `staging[].plate=null`。
    因此 3D 必须由在途层独占它的显隐（否则按账本判必然判成隐藏，与换父层每帧互顶就是闪烁）。
  - 3D **只做投影，不做推断**：合爪到画面跟手最坏差半秒（生产端 0.5 s 轮询），
    而取放脚本在夹爪开合前后跑的是 vel 5~10 的慢速逼近段，这半秒里机械臂只走几毫米。
    刻意不引入薄层板那套 L2 事件包络，以免出现第二套身份推断。
  - 流程正常跑完在途行会自己消失；中途取消/断电才会滞留，此时物料页显示滞留提示并提供
    `POST /api/materials/transit` 人工清账（`land_at` 为 `""`/`rack`/`staging`）。这正是它相对旧账本的全部价值 ——
    旧账本在那段窗口里静默失同步且不留任何痕迹。
- 每个货架/中转托盘都有 6 个独立耗材刚体，共 `14 × 6 = 84` 个。孔阵列由中转 A 正式 CAD 的 1/2/3 号实物求得，孔距为 `47.5 mm × 45 mm`，不使用包围盒或截图猜测。
- `FRESH` 表示未用耗材并显示；`USED` 且 `sample_id` 为空表示空孔并隐藏；`USED` 且带 `sample_id` 表示已装填件，仍保持显示。
- `magazines.feed` 和 `magazines.waste` 分别驱动上料仓、下料/废板仓。3D 使用正式 CAD 玻璃板模板和由 CAD 得出的 `3 mm` 节距，显示数量严格夹在 `0..capacity`。
- `presence` 用于账本/传感器一致性提示。当前货架传感器映射在上位机拓扑中标记为 `verified: false`，不得覆盖账本中的托盘身份；中转 A/B 的已验证传感器只用于一致性确认。
- 生产端每 0.5 s 读取一次本地 SQLite；快照变化时立即发布，无变化时每 5 s 发布心跳。慢读取不堆积，也不触碰任何物料写接口。
- `material_state` 是完整快照且属于可丢旧事件；消费者只需保留最新一帧。
- REST 回退只读取既有 `/api/materials`，不提供物料写入能力（人工盘点写入不走回退通道，
  见 §5.1）；回退事件标记 `source: "rest_fallback"`，与正式 WebSocket 快照使用同一 `MaterialStateStore`。

### 5.1 三维发起的物料写入边界

三维实时页（`/3d/live`）与仿真页（`/3d/sim`）支持右键物料实体做人工盘点（`twin/panels/
MaterialInteraction.vue` + `twin/materialWriteApi.js`）。这不改变 §5 的投影纪律，边界如下：

1. **写入 = 上位机既有的人工盘点 REST**（`/api/materials/` 下 `mark | cell_amount | staging |
   rack | magazine | bottle | seat | transit | payload_seat`）。三维**不新增任何私有写端点**，
   校验、确认级与流水留痕与二维物料页完全同源。
2. **写后不做乐观渲染**：画面变化只来自下一帧 `material_state` 推流（最坏约 1 s）。
   前端身份是值对象，快照整帧替换后自动重算 —— 单向闭环，不存在第二份状态。
3. **仿真页写 `/api/sim/materials/*`**（镜像契约，前端 `base` 可注入）。沙盒端点未就绪时
   请求 404，按"记账失败"显式播报，不静默。
4. **在途载荷只允许"清在途"**，不允许改其格账（件在爪上是唯一能确认的事实，见 §5 的
   `transit` 语义）。
5. 标题的"只读"指**事件流方向**与渲染纪律不变：事件流仍是单向下行，渲染仍只从推流投影；
   §10.4 的安全边界不因写入放宽（物料盘点端点不驱动任何硬件）。

## 6. `signal_light`

```json
{
  "type": "signal_light",
  "red": false,
  "yellow": false,
  "green": true,
  "flash": false,
  "buzzer": false,
  "mode": 1,
  "ts": 0,
  "seq": 0
}
```

- 颜色由 **`GVL/MODE_State` 状态机推导**（上位机 `manual_service._SIGNAL_BY_MODE`，
  随 10 Hz 机构批读采集）：0 停止=黄、1 运行=绿、2 故障=红闪、3 急停=红、
  4 初始化=黄闪、未知码=全灭。映射依据 PLC `FB_Mode` 源码（故障
  `bRed := bFlashFlag`，`tFlashTimer` T#500MS 翻转 = 1 Hz）与活值取证。
- **为什么不读原始输出位**：2026-08-02 取证发现运行版 `FB_Mode` 在运行态误置
  `三色灯红` 恒 TRUE（实体红灯并不亮），原始色位（`%QX0.0-0.2`）与实体灯脱钩。
  三个色位仍保留在 `/api/manual/state` 供诊断；待 PLC 侧修正 FB 后如需可切回。
- `flash: true` 表示该态实体灯是闪烁的；上位机发布的是稳态布尔，1 Hz 闪烁动画
  由前端本地渲染（不产生高频事件）。`mode` 为 MODE_State 原始码，供 HUD 诊断。
- `buzzer` 仍读原始输出位 `%QX0.3`（未见污染），三维模块当前不消费（留扩展）。
- 发布策略：**变化即发 + 1 s 心跳**（dedup 键含 flash/mode）。心跳兼作新连接的
  初始播种（首帧 ≤1 s）与消费端 staleness 时钟。可丢旧快照，只保留最新帧。
- 采集降级：`mode_state` 读不到时快照省略 signals、事件停发，不影响轴/机构流；
  前端表现为塔灯停留在烘焙静态色。
- 渲染语义（`manifest.signalLight` 契约，styles 五态）：灯罩整罩单色，优先级
  **红 > 黄 > 绿**；全灭为熄灯态（自发光归零）；超过 `staleMs`（3 s = 3 个心跳）无帧
  或显式断连转灰色未知态（常亮不闪）并保留末态布尔；live 首帧前保持管线烘焙的
  静态绿，材质不被接管。

## 7. `process_light`

```json
{
  "type": "process_light",
  "id": "vision_fill",
  "on": true,
  "channel": 7,
  "ts": 0
}
```

- **工艺灯**（拍照补光/面光源）与 `signal_light`（整机三色塔灯）是两回事：那个报的是
  机器状态，这个是**工艺动作的一部分**（拍照要打光）。`id` 与
  `three_d/pipeline/rig_map.yaml` 的 `lights[].id` 逐字一致，前端按 id 查
  `manifest.lights`；对不上就是一盏永远不亮的灯。
- 目前只有 `vision_fill` 一个发布者：视觉纠偏补光，走机器人 **DO7**
  （`app.yaml: pallas_vision.light_do_channel`）。发布点在
  `runtime/bootstrap.py::pallas_light_setter` —— 那是全仓**唯一**写 DO7 的地方
  （`controller/pallas_vision_client._run_with_light` 经 `light_setter` 调进来），
  所以事件与真机 DO 逐次同步，**不需要 DO 回读或轮询**。机器人 DO 也没有便宜的回读通道。
- 事件**排在 `set_output` 成功之后**：写失败会抛出去（关灯失败还会被上游升级成
  `PallasVisionError`），那种情况下不发事件 —— 只报已经写成功的 DO 状态。
- 发布策略：**变化即发，无心跳**。补光每块板才开关两三次，不该进 10 Hz 快照流；
  也因此**没有 seq/心跳兜底**，消费端不要拿它做 staleness 时钟。
- ⚠ **不是可丢事件**（刻意不进 `runtime/events.py` 的 `_DROPPABLE_TYPES`）。
  `signal_light` 能丢是因为 1 s 心跳会把状态重新播种；本事件没有心跳，背压下丢掉一帧
  「关灯」就意味着画面里那盏灯**永远亮着**，再没有第二次机会纠正。这与"补光是瞬态量"
  是同一件事的两面：正因为它稀疏，每一帧都是不可替代的。
- `uv_scrape`（刮板台紫外面光源）**不在本事件里**：暗箱里一直开着，PC 侧根本没有它的
  开关信号 —— 不编造一个不存在的 DO，它按 `rig_map.lights[].default_level` 常亮。
- 渲染语义（`manifest.lights` 契约）：`on` 是稳态布尔，0↔1 的**斜坡由前端本地渲染**
  （真机是 1 s 量级的稳态过程 —— `light_settle_ms`，硬切既不像也看不清）。
  灯本体埋在盖板玻璃下 37 mm，整机机位看不出开关差异，所以真正的可见形态由
  `lights[].illuminatesNodes` 声明的**受照对象**承担（下相机盖板玻璃发光）；
  离线片段侧另有 `illuminates: plate` 让板面提亮。
  live 首帧前**不接管**，保持管线烘焙的静态观感；断流时回落 `defaultLevel`
  （补光是瞬态量，丢帧后停在"亮着"是错的 —— 与塔灯"转灰保留末态"刻意不同）。

## 7b. `scrape_state`（2026-08-06 新增）

```json
{
  "type": "scrape_state",
  "phase": "armed",
  "band_cm": [2.1, 7.8, 17.6, 9.9],
  "pass_count": 2,
  "pass_z_list": [21.0, 21.5],
  "plate_surface_z_mm": 20.5,
  "total_depth_mm": 1.0
}
```

- 由 `controller/cnc_path.py::CncPathController._emit_scrape_armed` 在算完本次路径时发一条。
  **全链只有那里知道谱带在板上的哪一块** —— 下发 PLC 的是机床 mm 数组（`g_sx/g_sy`），
  反算不回板 cm 帧。`band_cm` 是未内缩的原始带 bbox（刀补只挪刀心，被刮掉的仍是整条带）。
- `pass_count: 0` = 本轮跳过刮板（`placeholder`），消费端据此**清掉上一轮的刮痕**。
- **不在可丢事件集里**（`runtime/events.py::_DROPPABLE_TYPES`）：它是增量语义，丢一条
  就永远画不出刮痕，与 `axis_pose` 那种"最新快照即全部语义"的高频流不同。
- 层进度不在本事件里：消费端按 `photoscrape.write_pass_z` 的 `vm_node_enter` 入参 `z`
  在 `pass_z_list` 里定位层号，按 `photoscrape.scrape` 的 enter/done 定本刀的起止。
- 渲染语义（`PlateBinding._handleScrapeEvent` / `PlateFaceLayer.applyScrape`）：条带被
  discard 出一个洞，洞底垫一块**残余硅胶薄板**，厚度 = `(pass_count − 已完成刀数)
  / pass_count × 硅胶层厚` —— 只有最后一刀才真正露玻璃。
  **刀内前沿不插值**：A40 是一条静默的 CNC 插补，中途没有任何进度反馈，唯一能观测的
  `axis_pose` 在刮取段与收集段含义不同（收集时桶比刀偏 90 mm）。按刀出离散三态
  （未刮 → 整条刮松 → 整条收尽落一层），不画猜出来的前沿。

## 7c. `pump_state`（2026-08-08 新增, **仅仿真沙盒通道**）

```json
{
  "type": "pump_state",
  "id": "SMP",
  "plunger_ml": 12.5,
  "valve_port": 3,
  "busy": true,
  "ts": 1754620000.0,
  "seq": 42
}
```

- 只出现在 `/api/sim/ws/events`（仿真沙盒, `mock/behavior/pump.py::run_pump_watcher`）:
  虚拟泵按执行器写入的**真实 DT 指令串**（`tools/pump/dt_codec.parse`）逐段积分柱塞与
  阀位, busy 期约 10Hz + 终态一帧。**主通道 `/api/ws/events` 不发** —— 真机注射泵全程
  无位置回读, 诚实缺席; 实时页的泵动画仍走 manifest 相位表的动作包络。
- `id` 对齐 `manifest.pumpSyringe.pumps[].id`（SMP/COL/DEV1/DEV2）; `plunger_ml` 为
  柱塞绝对体积（25 mL 量程）; `valve_port` 1 起数, null = 未知（未初始化）。
- 最新快照即全部语义, 在可丢事件集里（`runtime/events.py::_DROPPABLE_TYPES`）。
- 消费端: `TwinFeed.handleEvent` 的 `pump_state` 分支 →
  `PumpSyringeModel.pushFeedback` —— **有反馈优先**（直设通道目标, 包络推算退位）,
  断流/缺席时回落包络行为, live 页因此零影响。

## 7d. `tank_liquid`（2026-08-13 新增, **仅仿真沙盒通道**）

```json
{
  "type": "tank_liquid",
  "tank": 3,
  "volume_ml": 41.2,
  "level": 0.402,
  "capacity_ml": 102.48,
  "ts": 1754620000.0,
  "seq": 17
}
```

- 只出现在 `/api/sim/ws/events`（`mock/behavior/tank_liquid.py::run_tank_liquid_loop`）:
  后端按**泵的累计排出量 × 该缸进液阀开合**积分注入, 按排液阀开合排出, 变化超过
  0.05 mL 才发。**主通道 `/api/ws/events` 不发** —— 真机展缸无流量计, 上位机拿不到
  任何注排进度, 实时页的液面仍走动作包络 + `Tank_State` 相位锚点两路合成。
- `tank` 是 **1 基**缸号（1..8）; `volume_ml` 为槽内体积; `level` = 体积/容量, 已在
  后端算好（前端 `levelFromMl` 另做观感放大, 两者互不覆盖）。
- 容量与排液速率的真源都是 `manifest.tankLiquid`（cavity 由 03 管线实测,
  `actions['develop.drain'].rampS` 借作排液速率 —— 这是该模型**唯一的显式近似**,
  真机排液既无流量计也无时长通道）。
- 消费端: `TwinFeed.handleEvent` 的 `tank_liquid` 分支 →
  `TankLiquidModel.onTankVolume` —— **收到即置 `authoritative`**, 动作包络与相位锚点
  两路合成一并让位（有真值就不该再编）; 真机从不发本事件, live 页因此零影响。

## 8. 优先级与模式切换

```text
新鲜 confirmed
  > 新鲜 robot_pose / axis_pose
  > 1 Hz telemetry 回退
  > commanded（标 estimated）
  > 冻结末态（标 stale）
```

- Live 模式真实反馈优先；Studio 保持离线，不连接事件流。
- 顶部“实时”进入 `/3d/live`, 并始终复用上位机事件流。
- HUD 的“只读实时诊断”显示 11 轴和 51 机构；“物料”面板显示两个中转位、12 个货架托盘及耗材、上下料板仓。

## 9. 当前生产端实现与现场边界

`E:\eit_lab\pTLC_platformUI\eit_ptlc` 已增加只读实时生产端：

- Dobot 30004 由唯一后台线程持续读取，命令等待、DI 等待、模式等待和查询只等待条件变量中的最新/下一帧。
- `realtime_feedback_loop` 一次 PLC 批读生成 11 轴和 51 机构快照；轴目标 20 Hz，机构目标 10 Hz。
- `material_feedback_loop` 独立于 PLC/机器人连接运行，直接读取上位机的 `MaterialStore`，因此即使设备离线也能显示已保存的物料设置。
- `telemetry`、`robot_pose`、`axis_pose`、`mechanism_state`、`material_state`、`signal_light` 都是可丢旧快照；操作、步骤、报警等生命周期事件保持不可丢。
- 工艺灯 `process_light` 不进 `realtime_feedback_loop`（它只做 PLC 批读）：唯一发布点是
  `bootstrap.pallas_light_setter`，与写 DO7 同一次调用，因此不增加任何采集负担。
  它**与生命周期事件同级不可丢**（无心跳，丢一帧即永久错态，理由见 §7）。
- 三色灯位声明在 `config/manual_points.yaml` 的 `globals:` 段（`signal_red/yellow/green/buzzer`），
  采集在 `manual_service.realtime_snapshot`，发布在 `realtime_feedback_loop`。
- 没有增加三维模块→机器人、三维模块→PLC 或三维模块→物料账本的写接口。
- 2026-08-05：账本新增在途表（`payload_transit`）与叶子层绑定（`robot_group_*` / `robot_individual_*`），
  于是"取放托盘"这段过程在 `/3d/live` 上可见，而不是终点一次瞬变；二维物料页（`views/MaterialView.vue`）
  也改为订阅 `material_state`，此前它只有 `onMounted` 与手动刷新，同一份账本两页两种时效。
  两者仍都是只读投影，写入口只有既有的人工盘点 REST（2026-08-10 起三维实时/仿真页
  经右键点选也成为该盘点入口之一，边界见 §5.1）。
- 2026-08-05：`RobotController.tool_action` 改为**分两拍**写孪生缓存 —— 发令前先公告
  `moving: true`，动作返回后再补 `confirmed` 并清 `moving`。此前只在 `transport.tool_action`
  返回之后写一次，而那一次调用阻塞整段物理行程，于是 `/3d/live` 上的吸盘 180° 翻转
  表现为"实物转完之后画面才一瞬间转过去"。只有旋转动作进这个名单（夹爪 0.4 s 行程
  没有这个观感问题），仍然没有新增任何三维模块→机器人的写接口。

部署后必须重启上位机后端进程，新的 `material_feedback_loop` 和 WebSocket 首帧补种才会生效；随后强制刷新 `/3d/live` 页面。

## 10. 2026-08-05 真机实时性能基线

本节记录当前实现的数据刷新能力和工程可感知延迟，用于后续调参、回归比较与现场验收。这些数字描述的是只读可视化链路，不是 PLC 或机器人控制回路的实时指标。

### 10.1 测试条件

| 项目 | 记录 |
|---|---|
| 测试日期 | 2026-08-05 |
| 运行对象 | 当前在线的真机服务，机器人反馈链路已连接 |
| 采样入口 | `ws://127.0.0.1:18080/api/ws/events` |
| 采样时长 | 12.007 s |
| 客户端 | 同机回环 WebSocket 客户端，单订阅者 |
| 代码基线 | 分支 `codex/ui-upper-next-v2`，基准提交 `7161e05` |

> 测试时工作区含未提交的三维模块改动，因此 `7161e05` 只是可追溯的基准提交，不代表完整工作区快照。本次字节数按 UTF-8 JSON 消息体统计，不含 WebSocket/TCP 帧头，且包含建连时的完整 `material_state` 补种。

### 10.2 WebSocket 实测结果

| 事件类型 | 12.007 s 内条数 | 实测速率 | 中位间隔 | P95 间隔 | 平均消息体 |
|---|---:|---:|---:|---:|---:|
| `robot_pose` | 241 | **20.07 Hz** | 49.2 ms | 53.2 ms | 317 B |
| `axis_pose` | 186 | **15.49 Hz** | 62.9 ms | 74.9 ms | 609 B |
| `mechanism_state` | 94 | **7.83 Hz** | 125.3 ms | 138.8 ms | 4,192 B |
| `telemetry` | 108 | 8.99 条/s（聚合） | — | — | 297 B |
| `signal_light` | 12 | 1.00 Hz | 1,014.8 ms | 1,020.7 ms | 136 B |
| `material_state` | 3 | 0.25 条/s | — | — | 16,811 B |
| `ready` | 1 | 建连确认 | — | — | 16 B |

- 总计 645 条消息，平均 **53.72 条/s**。
- 原始 JSON 消息体平均 **55,629 B/s**，即约 **55.6 KB/s（0.45 Mbit/s）/ 客户端**。WebSocket 会按订阅者复制事件，多客户端时带宽和序列化开销近似按连接数增长。
- 高频事件从后端写入 `ts` 到同机 WebSocket 客户端收到的中位延迟约 **1 ms**，P95 约 **2 ms**。因此当前主要限制不在 WebSocket 传输。
- `telemetry` 按节点分别发送；表中 8.99 条/s 是 9 个节点每节点约 1 Hz 的聚合速率，不表示单节点有 9 Hz。
- `material_state` 为变化即发加心跳，本次 0.25 条/s 只反映采样窗口内的实际发送，不是其变化检查上限；生产端仍每 0.5 s 检查一次。

### 10.3 数据刷新率、渲染帧率与画面延迟

数据刷新率不等于画面帧率。Three.js 由 `requestAnimationFrame` 驱动，在常见 60 Hz 显示器上目标是约 60 FPS；机器人和 PLC 轴的新物理样本仍分别只有约 20 Hz 和当前实测 15.5 Hz。前端对两者都保留 100 ms 时间缓冲，每个渲染帧在相邻样本间插值，因此视觉运动可以连续，但会有有意保留的显示滞后。

| 对象 | 当前工程结论 | 主要构成 |
|---|---|---|
| 机器人位姿 | 约 **100–120 ms** 跟随延迟 | 100 ms 插值缓冲 + 下一次渲染/显示机会 |
| PLC 伺服轴 | 约 **120–150 ms** 跟随延迟 | OPC UA 批量读取耗时 + 100 ms 插值缓冲 + 渲染 |
| 气缸、阀和机构 | 变化通常在约 **130 ms 量级**内被下一帧状态发现；本次间隔 P95 为 138.8 ms | 10 Hz 目标检查 + PLC 批量读取；收到状态后再按 `transitionS` 表现物理行程 |
| 物料和托盘账本 | 变化发现最坏约 **500 ms** | 0.5 s 本地账本检查，变化即发，不插值 |

PLC 轴的代码目标周期为 50 ms，但每轮会先完成一次 OPC UA 批量读取，下一个周期又从读取完成时开始计时，因此现场实际速率低于理想 20 Hz。机构状态同理由 10 Hz 目标降到本次实测约 7.8 Hz。

### 10.4 适用边界与测量限制

- 当前水平属于约 **0.1–0.15 s 级近实时数字孪生**，适合运行监视、动作跟随、调试和演示。
- 三维页只是只读投影，不用于碰撞保护、安全联锁、急停判定、精密轨迹跟踪或任何闭环控制；这些职责仍必须留在 PLC 和机器人控制器内。
- WebSocket 事件到达时间和消息体带宽为本次实测；机器人/PLC 轴最终屏幕延迟是结合实测样本间隔、100 ms 前端缓冲与渲染周期得到的工程估算。
- 本次没有用高帧率摄像机同时拍摄实物与显示器，未纳入显示器扫描、像素响应、远端局域网往返及现场 GPU 负载。若要得到可用于验收的端到端数字，需再做实物与屏幕的同画面对拍。
