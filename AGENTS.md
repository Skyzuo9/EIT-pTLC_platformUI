# AGENTS.md

本文件为在本仓库工作的智能体 (Qoder / Codex / Claude 等) 提供指引。

## ⚠️ 首要方位 (Orientation)

- **`UI-Upper/` 是过时存档** (旧 NiceGUI 单体)，仅作历史参照，**不再开发**，勿当活动代码读改。
- **全部新开发集中在 `eit_ptlc/`**。
- **总目标**：以**原子级动作 (atomic actions)** 重构 上位机-PLC-机器人 三方协作，实现**柔性生产** —— 任意工艺由"原子动作 + 流程脚本"自由编排，而非硬编码 stage 流水线。

## Common Commands

```bash
# 后端 Python: conda env platformupper (E:\Anaconda\envs\platformupper\python.exe, 3.11)
cd eit_ptlc/web && npm install          # 前端依赖 (首次)
cd eit_ptlc/web && npm run build        # 前端产物 (首次 + 每次改前端源码; dist/ 已 gitignore)

# 一键起整套 UI (推荐): MQTT:1883 + Bridge:18888 + 后端 uvicorn:18080, 分控台 + 交互菜单
# 前端默认由后端同源托管 web/dist, 不再单独占窗口 → 浏览器开 http://localhost:18080/
# 后端监听 app.yaml api.host (默认 0.0.0.0): 同网段设备开 http://<本机IP>:18080/ (就绪日志
# 会打印该地址; 打不开先放行防火墙 TCP 18080. ⚠ API 无鉴权, 收紧改 api.host: 127.0.0.1)
python eit_ptlc/main.py                 # 默认 sim (进程内 Mock PLC + 内存机器人仿真)
python eit_ptlc/main.py --real          # 真机 PLC(OPC UA) + Dobot(TCP)；--no-browser 不开浏览器
python eit_ptlc/main.py --dev-frontend  # 改前端源码时: 另起 vite:15173 (HMR), 浏览器改开 15173

python -m eit_ptlc.config.loader --check  # 配置自检 (fail-fast 校验 app.yaml 及引用)
python -m pytest eit_ptlc/tests -q        # 离线测试 (全 *_offline.py, 无需硬件)
python -m eit_ptlc.tools.gen_robot_point_operations  # 重生成 06_robot/*.yaml 点位 operation

# CODESYS/InoProShop 文件 IPC + MCP 自测 (会启动带 UI 的 InoProShop)
cd eit_ptlc/tools/codesys-mcp
npm install
node test_worker.mjs
node test_mcp.mjs
```

`main.py` 是开发编排器：启动前按端口 (1883/18888/18887/18080/48490，`--dev-frontend` 时另加 15173) 清理残留进程。

## Architecture Overview

### 系统拓扑

```
        OPC UA (统一 L2 动作通道)            Dobot TCP-IP-V4 (29999/30004/30003)
PLC ◄─────────────────────────► 上位机后端 (FastAPI/asyncio :18080) ◄──────────► 机器人 (Dobot)
(汇川/CODESYS)                    │  config/    声明式动作 + 流程脚本仓库 (单一事实源)
工位 L2 FSM + 伺服/地轨/泵        │  action/    ActionExecutor 统一入口 → ActionResult
                                 │  operation/ mini-VM 解释器 + 调试器 + HITL + 调度
                                 │  controller/ PLC / Robot / Points / Vision / Calibration / PLC Program
                                 │  driver/    OpcUa / Dobot / Sim / 相机 / 香橙派液位 / CODESYS IPC
                                 │  runtime/   bootstrap(sim|real) + 事件总线 + 遥测 + RunStore
                                 └─ HTTP + WS(/api/ws/events) ─► 前端 Vue3/Vite SPA (:15173)

真机模式另有 PLC 工程维护链:

前端 PLC 页 → `/api/plc/*` → `PlcProgramService` → `CodesysIpcClient`
→ 文件 IPC 常驻 worker → InoProShop SP11 (带 UI) → `eit_ptlc/plc/20260702.project`
```

### 核心理念: 原子动作 → 流程编排

```
原子动作 (config/actions/)  不可再分最小指令; kind=robot | plc_l2 | (device/camera/vision 预留)
   ↓ 被引用
流程脚本 (config/operation/) ptlc.script/v1 节点树; if/for/while/try/parallel/human + 变量/资源
   ↓ 解释执行
mini-VM (operation/vm/)     递归 async 解释器, 逐节点过调试门, 叶子复用 ActionExecutor
   ↓ 下发
ActionExecutor (action/)    校验 + 模式门控 + 泵参翻译; 机器人(run_in_executor)/PLC L2(async) 归一
   ↓
Controllers → Drivers → 硬件
```

"柔性"= 改流程只需增删 `config/actions` 原子动作与 `config/operation` 流程脚本 (UI 可视化编辑)，**无需改流水线代码**。

### 目录地图 (`eit_ptlc/`)

| 目录 | 职责 |
|------|------|
| `action/` | `models.py`(ActionResult/状态机/拒绝码)、`registry.py`(动作目录)、`executor.py`(统一执行器) |
| `operation/` | `vm/`(mini-VM)、`scheduler.py`(样品级并发)、`recipe.py`、`resources.py`/`*_manager.py`(资源门)、`robot_routes/`(离线工具, **非运行期**) |
| `controller/` | 设备语义层: plc / robot / points / vision / camera / calibration / config / actions_service / plc_program+version |
| `driver/` | 传输层: opcua / dobot_tcp / robot_sim / robot_transport / camera+daheng / orangepi / codesys_ipc |
| `runtime/` | `bootstrap.py`(sim/real 装配)、`events.py`(EventBus)、`node_registry.py`(遥测)、`run_store.py`(SQLite 历史) |
| `api/` | FastAPI: `app.py` + actions / VM / points / calibration / PLC program / water level / vision 路由 |
| `config/` | **单一事实源** (见下) |
| `plc/` | 现役 PLC 真源: `20260702.project`; `20260702.Device.Application.xml` 为可检索导出 |
| `mock/` | `plc_server.py` 同构 Mock OPC UA + L2 FSM (sim 用) |
| `web/` | Vue3 + Vite + Pinia SPA (运维/编辑/调试控制台) |
| `tools/` | 点位 operation 生成 / PLC L2 验收 / checklist / pump DT 翻译 / `codesys-mcp` |
| `tests/` | 全离线测试; `var/` 运行期产物 (runs.db / operation_history) |

## 原子动作模型 (`action/`)

**kind**:
- `robot`: 调 `RobotController.<method>`。
- `plc_l2`: 调 `PlcController.execute(station, action_code, params)`。
- `servo_target`: 将点位真源值写入 PLC `*_Target` flat 节点。
- `plc_write`: 声明式节点块写 + 回读确认，用于 CNC 路径等数组/标量下发。
- `camera` / `vision`: 已接入执行器；`device` 仍为预留类别。(液位检测走 REST 控制台 + MQTT 服务, 不作原子动作 kind。)

**声明** (`config/actions/<NN_设备>/*.yaml`): 顶层子目录名即 UI 分组；`ActionRegistry.load()` 递归加载。参数类型 `int/float/bool/string/enum/point_ref`，支持 `min/max/options/default/required`、`modes`(模式门控)。`point_ref` 由调用方显式选择 `plc_servo_target` 或组合点位，执行器在触发 L2 前先下发目标值。Web 可整文件编辑动作 YAML；保存前全量校验，成功后热重载 registry/executor/VM 校验器。

```yaml
robot.move_to_point:
  kind: robot
  method: move_to_point
  modes: []                # 空=不限; [DEBUG]=仅调试
  params:
    - {name: point_id_or_robot_name, type: string, required: true}
    - {name: motion, type: enum, options: [move_j, move_l]}
    - {name: acc, type: int, min: 1, max: 100}   # acc+vel 齐备才合成 MotionProfile
```

**ActionResult 生命周期**: `SUBMITTED→ACCEPTED→RUNNING→DONE|ERROR|CANCELLED|TIMEOUT`；接受前门控失败为 `REJECTED`。
- 拒绝码 `RejectCode`: BUSY/ESTOP_ACTIVE/UNSAFE/INVALID_PARAM/OUT_OF_RANGE/WORKSTATION_OCCUPIED/MODE_NOT_ALLOWED/RESOURCE_CONFLICT/PLC_NOT_READY。
- `execute()` **始终返回 ActionResult 不抛异常**；机器人被显式中止 (Stop/EStop)→`CANCELLED`(非故障)；PLC 结果不明确 (停滞超时)→`TIMEOUT` 且 `retryable=False` (**非幂等物理动作绝不自动重发**)。

## 流程编排: mini-VM (`operation/vm/`)

**脚本 schema** (`ptlc.script/v1`): 顶层 `schema/kind/name/vars/resources/body`，`body` 为语句节点列表。op: `call`(调原子动作+args+assign)、`run_script`(子流程, 深度≤64)、`assign`、`if/for/while/repeat`、`try`(catch+finally)、`parallel`(并发分支)、`human`(HITL 挂起)、`comment`。表达式为 dict: `{lit}/{var}/{binop}/{unop}/{call}/{index}/{field}`；变量有类型/作用域(local/global)/IO(in/out/var/const)。

**调试**: AID = 按树位置推导的指令指针 (如 `b/3/then/0`)，断点/复位按位置寻址。`VmThread`(thread.py) 递归 async 解释器，叶子执行前过 `_checkpoint` 调试门 (STEP/RUN/PAUSE/断点)。`VmController`(controller.py) 按 run_id 管理线程，暴露 `start/step/run/pause/stop/reset/human_reply/state/vars/set_breakpoints`，并提供 `run_sample()` 接 `Scheduler` 做样品级编排。运行状态全在进程内存；事件经 `emit` 外发 (`vm_*`/`operation_*`)，落 RunStore 经 WS 推前端。

**ScriptRepo** (`vm/repo.py`): `config/operation/` 本身即仓库 (顶层子文件夹=分组)，UI 直读直写；保存经 `validate_script` 校验 (节点合法 / 变量可解析 / call 动作名存在)，版本历史落 `var/operation_history/`。

当前调试体验还支持“从选中行起跑”；单动作直发会旁路发出与 VM 同形的实时 operation/step 事件，点亮当前运行面板，但不写入 RunStore 历史。

**运行前旋钮覆盖** (`vm/knobs.py` + `schema.is_knob_var`)：旋钮 = 带 `ui:` 元数据块的 `in` 变量 (opt-in 白名单)。`start(overrides=…)` 在**每次建帧** `_make_frame` 于 inputs 之后按名注入命中的旋钮 → 深埋子脚本的叶子 `{lit}` 参数可在运行前一步覆盖，**零逐层 `inputs:` 透传**。范围/枚举校验在运行前提交端 (`validate_overrides`) + 动作层 `_validate` 双闸，建帧注入只做类型 coerce。

## PLC L2 统一动作通道 (`controller/plc_controller.py`)

每工位一套 `{prefix}_L2_*` 变量取代旧"每 stage 一套触点"：**PC→PLC** 写 ActionCode/RequestSeq/Start/Reset + 具名工艺参数；**PLC→PC** 回 State/ActiveCode/AcceptedSeq/CompletedSeq/Step/ErrorCode/SafeState/Retryable。

- **State 枚举**: IDLE(0)/RUNNING(10)/DONE(20)/REJECTED(30)/ERROR(40)/INTERRUPTED(50)。
- **启动时序 (下降沿确认)**: `Start=FALSE → 等 State=IDLE → 写参数/ActionCode/RequestSeq → 写回校验 → Start=TRUE`。
- **等终态 = OPC UA 订阅事件 + 看门狗**: 只要任一 L2 字段在推进就一直等 (慢动作如注射泵不误报)；`action_timeout`(600s 绝对上限) + `action_stall_timeout`(60s 无推进判"结果不明确")。断线在 `reconnect_wait_timeout` 内等重连，**不重发不确定物理动作**。
- **工位前缀** (`STATION_PREFIX`): sampling/spotting→Sampling、collect→Collect、develop/expand→Develop、photoscrape/scrape→PhotoScrape、feedlift→FeedLift、pump→Pump、rail→Rail、staging_a→StagingA。

## PLC 工程编辑、编译与部署

- **PLC 真源**: `eit_ptlc/plc/20260702.project`(前代 `20260622.project` 留在 `plc/` 仅供回滚，勿在其上开发)。顶层 `PLCsoftware/` 与旧 XML 均为历史资料，不在其上继续开发。
- **装配边界**: 仅 `real` 模式且 `codesys.enabled=true` 时装配 `PlcProgramService`；sim 对 `/api/plc/*` 返回 503。
- **能力**: POU/设备树浏览，声明与 ST 实现读写，Application 编译，OPC `{attribute 'symbol'}` pragma 管理，整份 `.project` 快照/下载/还原，以及真机全下载。
- **安全门**: 部署还需 `codesys.allow_deploy=true`，worker 先编译，错误数非 0 不登录 PLC。当前 worker 的真实行为是强制全下载后自动启动程序；历史快照与部署台账落 `var/plc-history/`。
- **SP11 约束**: InoProShop V1.9.1.6 必须带 UI；首次请求冷启动较慢。worker 由文件 IPC 多客户端共享，空闲超时后退出释放工程锁；不要同时用另一个交互式 InoProShop 打开同一工程。

## 机器人原子动作与点位系统

- **机器人点位真源**: `config/points/robot/robot_points.json`(86 点) + `robot_points_meta.json`(派生点并入 meta.supplement) → `PointRegistry.load()`。运行期**不再叠加** `robot_flows_v2.yaml` (仅供离线生成工具)。
- **PLC 点位真源**: `config/points/stations.yaml` + `config/points/plc/<workstation>.yaml`。`PointsService` 聚合 robot / plc_servo / plc_servo_target / plc_servo_composite，并负责 flat 节点下发、回读与工位级 PC↔HMI 双源对账。
- **取放流程 = 点位 operation** (`config/operation/06_robot/*.yaml`, 由模板 + `gen_robot_point_operations.py` 离线生成)。典型: `require_anchor` → 多级 `move_to_point` → `tool_action` → 原路退回 → home → `require_anchor`。
- **工具态与视觉纠偏**: 末端挂载工具四态持久化到 `robot_tool_state.json`；放板视觉纠偏走顶层 `pallas_vision` TCP action (`vision.capture_plate_offset` → Bridge)，读回 `Δx/Δy/Δθ` 叠加到目标点。(旧机器人 Modbus 寄存器纠偏路径已删除。)

### 机器人末端 IO 映射 (关键, 易踩坑)

经 Modbus/Lua ToolAction 白名单协议控制。关键 DO：

| DO | 功能 | 物理语义 |
|----|------|----------|
| DO1 | 快换电磁阀 | **DO1=0 锁紧**(工具固定), **DO1=1 松开**(工具可脱离) |
| DO2 | 夹爪 | 1 夹 / 0 松 |
| DO3 | 吸盘 | 1 吸 / 0 放 |
| DO6 | 快换辅助气缸 | 1 开 / 0 关 |

**关键原则**: **取工具=锁紧 (`quick-change-lock`, DO1=0)，放工具=松开 (`quick-change-release`, DO1=1)**。⚠️ 旧 v0.11 Lua `Kh_vac` 命名与物理效果相反，**只能按 DO 电平映射，不按旧汉字名**。取/放相反时先查 `robot_flows_v2.yaml` 映射，再查 Lua 端 DO 极性。枚举见 `driver/robot_transport.py`。

## 配置系统 (`config/`)

- `app.yaml`: 顶层含 control_mode / plc / robot / pallas_vision / vision / camera / water_level / api / gcode / codesys / vision_debug；子配置路径相对 `config/`，数据输出路径相对 cwd。改后跑 `--check`。
- `config/actions/<NN_设备>/`: 原子动作声明。`config/operation/<组>/`: 01_sampling / 02_develop / 03_photoscrape / 04_collect / 05_transfer / 06_robot / 07_feedlift / 08_rail / 09_full / 10_demo。
- `plc_nodes.yaml`: OPC UA 节点表。`config/points/`: 机器人 JSON + PLC 分工位 YAML。`plates.yaml` + `calibration.yaml`: 孔板类型 + 3 点仿射标定，支持按 `(plate_spec, plate_no, well)` 寻址后逐孔下发。

## API 表面 (`api/`)

`/api/health`、`/api/mode`、`/api/actions[/{name}][/run|/raw]`、`/api/robot/*`、`/api/scripts/*` + `/api/debug/{run_id}/*`、`/api/points/*`、`/api/calibration/*`、`/api/config/{section}`、`/api/nodes`、`/api/runs`、`/api/water-level/*`、`/api/vision/*`、`/api/photoscrape/*`(拍照刮板路径来源: 手绘/预览/提交/门内重识别)、`WS /api/ws/events`。`/api/scripts/{name}/debug/knobs` 收集运行前旋钮 (带 `ui:` 的 in var), `debug/run` 接 `overrides` 按名注入 (见下)。

PLC 工程表面集中在 `/api/plc/*`: status / pous / tree / pou / compile / symbols / online_status / deploy / versions，以及 `/api/plc/stations/{station}/reset`。前端对应 PLC 程序页、动作 YAML 编辑、点位/标定、流程编辑调试、设备节点与常驻运行监视器。

## 运行模式与控制模式

- **运行模式** (EIT_MODE / `--real`): `sim` = 进程内 Mock OPC UA + L2 FSM + 内存机器人仿真；`real` = 真机 PLC + Dobot 直连，并按配置可选装配液位与 CODESYS 工程服务。共享执行/VM/点位/遥测装配仍在 `_build_shared_state`。
- **控制模式** (control_mode, 两态): `DEBUG` 可执行全部；`RUN` 禁调试功能 (机器人 jog/step/home/工具/清警/使能、点位编辑)。由 `ActionExecutor` 按动作 `modes` 门控。
- **全部 L2 工位**: Sampling / Collect / Develop / PhotoScrape / FeedLift / Pump / Rail / StagingA。StagingA (中转A) 一站统管中转A/B 两个定位气缸 (`staging_a.locator_a` code 24 / `staging_a.locator_b` code 25，后者别名 `collect.bottle_locator`)；上位机侧已接入 (STATION_PREFIX / plc_nodes / 动作组 11_staging_a)，`bootstrap._ALL_L2_STATIONS` 已含 `StagingA` (sim FSM + 真机遥测均覆盖)。气缸开关由 `05_transfer/transfer_*` 各自自守卫 (放板前松、放毕夹、取板前松、取单件前夹)，顶层编排 (`ptlc_full_v2` / `single_sample_demo`) 保留同名调用作幂等段级兜底；写为直接赋值、同扫描周期 DONE，无到位反馈。StagingB 曾拟作独立 L2 工位系错误设计，已删除 (其定位气缸并入 StagingA_L2)；中转B 仅作为被动物料区保留 (资源令牌 `staging-b` + 机器人瓶转运流程 `05_transfer/transfer_bottle_*_staging_b*`)，非 PLC 工位。

## 开发约定

- **第一性原理 + 奥卡姆**: 每个变量都要能答"它不存在会怎样?"。质疑过度设计，给替代方案而非照单全收。**中文交流，动手前先讨论设计**。
- **与 PLC 最小耦合**: 缺失变量 WARN 而非崩溃。**Mock 同构**: Mock 节点树须与真机完全一致。**Debug = 生产路径**: 调试走与编排相同代码路径。**单一写者**: 每个 PLC BOOL 恰一个 ST 写者; 写经 asyncio.Lock 串行化。
- **Worktree 归属**: `EIT_Project`(parallel) = 冻结集成/回滚基线，不在此开发新架构；`EIT_Project-Next`(codex/ui-upper-next) = 新架构**唯一活动 worktree**。经 Git merge/cherry-pick 同步，**绝不手工维护两份活动副本**。
- **流程**: git commit 前问是否记实验日志 (目标/改动/结果/已知问题/下一步)；架构级改动 (协议/依赖/接口) 先析影响再动；需求含糊先澄清再写码。

## 已知坑 (要点)

- **OPC UA/PLC**: asyncua 须显式 VariantType (REAL 用 `Float` 非 `Double`)；汇川 NodeId 为数字, 用 BrowseName 匹配 (无动态发现)；`BadNotWritable`=STRING(N) 溢出 (非 AccessLevel)；写串行化 (asyncio.Lock)，心跳 KeyError≠重连 (仅网络错误触发)；DT 协议用 ASCII `\r` 非 `$R`。**异常日志一律经 `_exc_text()`**：asyncua 超时抛的 `TimeoutError` 其 `str()` 为空串，直接 `%s` 会打出空白 (曾导致断网故障只显示 `重连失败 (#48): `)。日志里的 `close_secure_channel was called but connection is closed` 是 asyncua 对已死连接调 `disconnect()` 的噪音，非故障本身。`_link_hint()` 只报裸 TCP 这一层，**不可当链路真值**：本机开着 TUN/代理时端口关闭也表现为超时而非拒绝 (实测连回环亦然)。
- **PLC 工程**: `.project` 是二进制，Git/文本工具不能合并；在线编辑须走 `PlcProgramService`/`codesys-mcp`。部署是非幂等真机操作，必须先看编译结果、在线状态和版本快照。
- **项目级 MCP**: 根 `.mcp.json` 以绝对路径注册 `codesys` server，当前已指向本 checkout (`EIT_Project-Next`)，含 `--project=...plc/20260702.project` 与 `--ipc=...var/codesys-ipc-20260702`。换到其它 checkout 前必须整体改为该 checkout 的绝对路径，且 `--ipc` 须与 `app.yaml` 的 `codesys.ipc_dir` 指向同一目录，否则 `codesys` server 找不到脚本/工程或与后端争抢工程锁。
- **Python/asyncio**: `CancelledError` 不被 `except Exception` 捕获 (须先显式处理)；机器人控制器同步 (经 run_in_executor)，PLC 控制器 async 直接 await；离线脚本须自带超时 (终态等待靠看门狗不抛 TimeoutError)。
- **前端**: 默认后端同源托管 `web/dist` (`api/app.py::_mount_spa`，catch-all 必须最后注册，且对未匹配的 `/api/*` 显式 404 而非回落 index.html)；`dist/` 已 gitignore，改前端后须 `npm run build` 否则页面还是旧产物 (`main.py` 会 WARN)。仅 `--dev-frontend` 才起 vite :15173 经 `/api` 代理到 :18080，此时二者须同时在线；`vite.config.js` 的 `server.port`(strictPort) 与 `main.py` 的 `FRONTEND_PORT` 强绑定，勿单改一侧。
