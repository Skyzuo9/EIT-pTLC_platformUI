# PLC 工位 L2 动作划分

> 状态：当前目标动作目录
> 修订日期：2026-06-20
> 现状依据：最新 `PLCsoftware/OPCUAtest/*.xml` 与已跑通工作流
> 迁移实施：见 `L2分层架构迁移代码分析.md`

## 1. 文档边界

本文只定义 L2 动作名称、职责和稳定结束状态，不重复描述代码迁移、锁实现和通讯字段。

PLC 现状以最新 XML 为准；TXT 文件属于旧版参考。XML 中遗留 TODO 不用于判断动作是否已实现，具体行为以现有工作流和最新程序为准。

L2 不是单个 IO，也不是完整样品 Stage：

```text
L1：气缸、阀、泵、轴和传感器
L2：具有工艺语义、可独立结束、由 PLC 本地闭环的工位动作
上位机业务动作：PLC L2 + 机器人命名动作 + 相机/视觉 + 资源更新
RecipeTask：样品级流程和并发编排
```

当前阶段不新增通用 ActionListExecutor；由 RecipeTask 顺序调用 L2 动作，并在既有明确并发点使用 `asyncio.create_task/await`。

## 2. 跨设备交接

上位机同时管理 PLC 和机器人，不再使用通用 Confirm 或 `robot_req_*` 请求标志。

统一交接形式：

```text
PLC Prepare：工位进入稳定接收/释放姿态
→ Robot NamedAction：机器人执行取放
→ PLC Closeout：夹持、释放、传感器校验和本地状态收尾
```

Closeout 是普通 PLC 动作。机器人 Done 不能替代 PLC 对物料存在、气缸到位和工位安全状态的本地判断。

## 3. Sampling 上样点样工位

| 上位机业务动作 | PLC 本地动作/机器人动作 | 稳定结束状态 |
|---|---|---|
| `Sampling_Init` | PLC 回安全位、泵初始化 | 工位 Ready |
| `Sampling_Clean` | PLC 清洗；参数 `mode/count` | 流路可继续上样 |
| `Sampling_PrepareFluid` | PLC 空气隔离段和排废准备 | 流路准备完成 |
| `Sampling_LoadPlate` | PreparePlateReceive → Robot_LoadBlankPlateToSampling → SecureAndVerifyPlate | 板到点样位并定位 |
| `Sampling_AspirateSample` | PLC 定位、吸样和规定排废 | 样品吸取完成 |
| `Sampling_DispenseSample` | PLC 点样运动、打液和回位 | 点样完成，板可释放 |
| `Sampling_UnloadPlate` | PreparePlateRelease → Robot_TransferSamplingToPhoto → VerifyPlateRemoved | 点样位空闲 |

设计决定：

- `Sampling_Init` 与 `Sampling_ResetFault` 分开；Reset 不产生回零运动。
- `Sampling_Clean` 首版保留一个动作，不为内壁/外壁建立两套协议。
- 复用当前 A00/A10/A20/A30/A40/A50 内部设备逻辑，删除迁移后不再需要的机器人隐式调度。

## 4. PhotoScrape 拍照/刮板工位

| 上位机业务动作 | PLC 本地动作/上位机动作 | 稳定结束状态 |
|---|---|---|
| `PhotoScrape_Init` | PLC 轴、气缸、真空初始化 | 工位 Ready |
| `PhotoScrape_LoadPlate` | PreparePlateReceive → Robot 放板 → SecureAndVerifyPlate | 板定位在拍照/刮取位 |
| `PhotoScrape_LoadCollector` | PrepareCollectorReceive → Robot 放收集器 → SecureAndVerifyCollector | 收集器夹持完成 |
| `PhotoScrape_CaptureImage` | PrepareImaging → Camera_Capture → FinishImaging | 图像保存，遮光和拍照轴归位 |
| `Scrape_ExecutePath` | PLC 旋转/真空/CNC 刮取 | 指定路径执行完成 |
| `PhotoScrape_UnloadCollector` | PrepareCollectorRelease → Robot 取走 → VerifyCollectorRemoved | 收集器离开工位 |
| `PhotoScrape_UnloadPlate` | PreparePlateRelease → Robot 去展缸或废料区 → VerifyPlateRemoved | 工位空闲 |

新路径不使用 `scrape_PhotoMode`、`scrape_IsLast` 或 `scrape_Confirm` 表达业务流程：

- 是否拍照由 RecipeTask 是否调用 `CaptureImage` 决定。
- 是否废板由选择的机器人命名动作决定。
- 多条带重刮直接执行 LoadCollector → ExecutePath → UnloadCollector，板继续占用工位。

这些旧变量在 PhotoScrape L2 验收后与旧 Stage 一并删除。

## 5. Develop 展开工位

展开分为一个共享 prep 通道和 8 个独立 tank 通道。

| 上位机业务动作 | PLC 本地动作/机器人动作 | 稳定结束状态 |
|---|---|---|
| `Develop_InitFluidSystem` | 共享泵/流路初始化 | prep Ready |
| `Develop_CleanLine` | 指定组管路清洗 | 流路清洗完成 |
| `Develop_RinseTank` | 指定缸润洗 | 展缸润洗完成 |
| `Develop_FillTank` | 指定缸上液 | 展开液准备完成 |
| `Develop_LoadPlate` | PrepareTankReceive → Robot_TransferPhotoToDevelop → SecureAndVerifyTankPlate | 板进入目标缸 |
| `Develop_Start` | PLC 接收 `duration_s` 并启动单缸 TON | Tank=DEVELOPING |
| `Develop_DrainAndDry` | 排液、吹气、气缸复位 | 缸等待取板 |
| `Develop_UnloadPlate` | PrepareTankRelease → Robot_TransferDevelopToPhoto → VerifyTankEmpty | 板离开展缸 |

TON 作为上位机触发排液失效时的保险：

- 上位机可正常或提前触发排液。
- 到期未收到上位机触发时，PLC 自动进入同一个 DrainAndDry 状态转换。
- 排液只能启动一次。
- PLC 返回 `DrainTriggerReason=HOST|TON_FAILSAFE`。
- TON 不决定机器人取板顺序。

## 6. Collect 收集工位

对外保留六个清晰业务动作：

| 上位机业务动作 | PLC 本地动作/机器人动作 | 稳定结束状态 |
|---|---|---|
| `Collect_Init` | PLC 气缸和泵初始化 | 工位 Ready |
| `Collect_LoadPowderCollector` | PrepareCollectorReceive → Robot_TransferCollectorPhotoToCollect → SecureAndVerifyCollector | 收集器夹持完成 |
| `Collect_LoadBottle` | PrepareBottleReceive → Robot_LoadBottleToCollect → SecureAndVerifyBottle | 瓶进入洗脱姿态 |
| `Collect_Elute` | PLC 加液、查询、排液/正压排液循环 | 洗脱完成 |
| `Collect_UnloadBottle` | PrepareBottleRelease → Robot_ReturnBottle → VerifyBottleRemoved | 瓶离开工位 |
| `Collect_UnloadPowderCollector` | PrepareCollectorRelease → Robot_ReturnCollector → VerifyCollectorRemoved | 收集器离开，工位空闲 |

`Collect_Elute` 不拆成裸泵、阀生产接口。裸执行器仅供 HMI 手动维护。

当前 A10/A30 中机器人握手和气缸动作需要按 Prepare/Closeout 边界拆开；拆分后删除旧机器人允许位和重复循环判断。

## 7. 辅助机构和机器人动作

上下料升降继续由 PLC 本地控制：

- `PlateFeeder_PresentNextPlate`
- `WasteElevator_AcceptPlate`

机器人生产动作使用已有 schema v2/RouteExecutor，不重新建立第二套机器人动作目录。典型业务路线包括：

- 空白板到 Sampling。
- Sampling 到 PhotoScrape。
- PhotoScrape 到指定展缸。
- 指定展缸到 PhotoScrape。
- PhotoScrape 废板。
- 收集器和瓶在仓库、暂存、PhotoScrape、Collect 之间转运。

机器人路线负责点位、工具和运动；PLC Closeout 负责工位本地物理校验。

## 8. 状态与资源边界

`StageStateRegistry` 只描述业务阶段和 UI 进度，不作为工位物理占用的唯一事实源。

权威边界：

- PLC Action State/传感器摘要：工位是否运行、是否存在物料、执行器是否到位。
- `ResourceManager`：展缸归属和恢复状态。
- `ConsumableManager`：耗材架、暂存 A/B 和槽位。
- RobotActionService：机器人 Busy、工具和运动状态。
- 样品状态：板属于哪个 sample、当前业务阶段。

新增只读 `SystemResourceView` 聚合这些信息，供 Scheduler、UI 和 FastAPI 查询；不创建第二份可写总账本。只补当前缺失的板位置记录。

## 9. 调度锁

采用“单层调度锁 + PLC 最终拒绝”：

- RecipeTask 调用一个动作资源门，原子获取当前动作完整资源集合。
- PLC 再次检查本地模式、State 和传感器条件，必要时返回 REJECTED。
- `ResourceManager`、`ConsumableManager` 的内部锁只保护自身数据。
- RouteExecutor 只持有短时机器人事务资源。
- 展缸静置等长期占用记录在领域账本，不长期持有 asyncio.Lock。

首版资源：

```text
station:sampling
station:photo_scrape
station:collect
develop_prep
tank_action:1..8
robot
pump_command_bus
```

Camera/CNC 由 photo_scrape 工位覆盖；tool 是机器人状态，不单独加锁。

## 10. HMI 与目标代码

优先级：

```text
E-Stop > HMI_MANUAL > L2_EXTERNAL
```

ManualRequest 到来时：

1. 立即停止接受新外部动作。
2. 当前动作执行安全停止/中断。
3. PLC 返回 `INTERRUPTED + ErrorCode + SafeState`。
4. 到达允许手动控制的状态后开放 HMI 输出。
5. 恢复自动前执行 Reset/Init 和资源一致性检查。

迁移期以 `AutoControlMode=LEGACY|L2` 互斥当前 Stage 与新路径。对应工位验收后删除 LEGACY 入口和无意义的旧判断；最终只保留 L2 自动路径和 HMI 手动路径。

## 11. 实施顺序

1. 用 `Collect_Init` 或 `Collect_Elute` 验证统一动作通道和 HMI 中断。
2. 迁移 Sampling。
3. 迁移 Develop prep、TankAction 和 TON 保险。
4. 拆 Collect 的机器人交接。
5. 最后迁移 PhotoScrape。
6. 全部机器人交接改由上位机 RouteExecutor 后，删除 PLC 机器人 14 路优先级树。
7. 每完成一个工位，同步删除对应旧 Stage、变量、Mock 分支和上位机兼容判断。
