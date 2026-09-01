# pTLC 当前程序组织与样品生命周期说明

> 本文用于双方会前对齐当前 pTLC 项目的程序组织、样品流程控制方式和现有控制颗粒度。本文只描述当前系统现状，不作为最终中控接入方案。

## 1. 文档目的

当前 pTLC 系统已经具备本地上位机、PLC、机器人、视觉分析、耗材管理、样品队列和历史记录等能力。为了便于后续讨论中控系统接入、原子动作拆分和资源账本边界，需要先对齐当前程序是如何组织的，以及一个样品从入队到完成的过程中由哪些程序控制。

本文中的“中控系统”指后续与 pTLC 对接、负责上层实验流程编排的外部系统。

本文重点回答三个问题：

- 当前上位机、PLC、机器人分别承担什么职责。
- 一个样品完整生命周期中，各阶段由哪些程序推进。
- 当前阶段切换、PLC 握手和资源互斥是在哪里完成的。

## 2. 当前系统运行边界

当前系统的运行链路可以简化为：

```text
本地 UI / 操作员
    -> Python 上位机
        -> OPC UA
            -> PLC
                -> 机器人 / 泵 / 阀 / 气缸 / CNC
        -> 相机 / 视觉分析 / G-code 生成
        -> 样品数据 / 日志 / 历史记录
```

当前职责边界如下：

| 部分 | 当前职责 |
|---|---|
| 上位机 | 样品队列、配方解析、流程编排、资源账本、视觉分析、路径生成、日志记录、PLC 通信、本地 UI |
| PLC | 工位 FSM、安全互锁、硬件动作时序、泵阀气缸/CNC/机器人调度、完成与错误反馈 |
| 机器人 | 根据 PLC 授权后的指令执行取放或运动动作 |
| 相机/视觉 | 获取 TLC 图片，识别色带，输出刮取区域 |
| 本地 UI | 样品操作、队列查看、视觉调试、耗材状态、历史结果和异常恢复 |

一个核心边界是：**上位机负责决定样品流程进入哪个阶段，PLC 负责执行单个阶段内部动作并反馈结果。**

## 3. 一个样品的生命周期

一个样品进入系统后，主要由 `Scheduler` 和 `RecipeTask` 推进。

```text
样品入队
  -> Scheduler 创建异步任务
  -> RecipeTask 按配方推进各 stage
  -> StageExecutor 写入参数并启动 PLC FSM
  -> PLC 返回 Step / Done / Error / WaitConfirm
  -> 当前 stage 完成后，RecipeTask 切换到下一 stage
  -> 保存结果、日志和历史记录
```

当前完整样品流程为：

```text
SPOTTING
  -> BEFORE_PHOTO 与 DEVELOP 可并行
      -> SCRAPE
          -> COLLECT
              -> DONE
```

其中，阶段切换不是由 PLC 自动跳到下一阶段，而是由上位机 `RecipeTask` 根据配方、阶段结果和资源状态决定。每个阶段内部的动作顺序和安全检查主要由 PLC FSM 执行。

## 4. 上位机程序组织：按样品阶段说明

| 样品阶段 | 主要上位机程序 | PLC 侧对象 | 当前控制内容 |
|---|---|---|---|
| 样品入队 | `ui/`、`core/scheduler.py` | - | 创建样品任务，进入异步队列 |
| 流程编排 | `core/task.py` | - | 按 recipe 决定 stage 顺序、是否启用、是否并行 |
| 点样 | `core/stages/spotting.py` | `Sampling` FSM | 写入点样参数，启动点样阶段，等待完成 |
| 拍照前照片 | `core/stages/before_photo.py` | `scrape` FSM | 通过 `PhotoMode=1` 复用 scrape 拍照流程 |
| 展开 | `core/stages/develop.py`、`core/resource_manager.py` | `Expand` FSM、Tank FSM | 分配展缸，执行展开、排液和释放 |
| 刮取 | `core/stages/scrape.py`、`core/vision_service.py`、`core/gcode_generator.py` | `scrape` FSM | 拍照、视觉分析、生成刮取路径、启动刮取 |
| 收集 | `core/stages/collect.py`、`core/consumable_manager.py` | `collect` FSM | 准备耗材，写入收集参数，启动收集 |
| 结果保存 | `core/sample_store.py`、`core/database.py`、`core/log_persistence.py` | - | 保存图片、元数据、分析结果、日志和历史索引 |

当前上位机不是简单界面程序，而是承担了流程编排、资源账本、PLC 通信、视觉/G-code 处理和结果记录等职责。

## 5. 阶段切换方式

阶段切换主要在 `core/task.py` 的 `RecipeTask` 中完成。

当前切换逻辑可以概括为：

1. `RecipeTask` 读取 recipe 中每个 stage 的 `enabled` 配置和参数。
2. 如果阶段启用，则创建对应 `StageExecutor`。
3. `StageExecutor` 获取必要资源锁后，调用 `PLCClient` 写参数并启动 PLC FSM。
4. 当前 stage 返回完成、取消或错误结果后，`RecipeTask` 决定是否进入下一阶段。
5. 所有阶段完成后，样品进入 `DONE`，结果写入样品目录和历史记录。

当前有两类特殊流程：

- `before_photo` 和 `develop prep` 可以并行启动，因为两者占用的硬件资源不同。
- 多色带样品会在 `scrape` 与 `collect` 之间执行多轮循环，保证每条色带单独刮取、单独收集，避免混粉。

## 6. PLC 握手在哪里实现

上位机和 PLC 的通用通信与握手主要集中在 `core/plc_client.py`，各 stage executor 通过它启动阶段并等待结果。

典型阶段启动流程如下：

```text
上位机写入阶段参数
  -> 拉起 <Stage>_Enable
  -> PLC FSM 进入运行状态
  -> 上位机轮询 <Stage>_Step / <Stage>_Done / <Stage>_Error
  -> 必要步骤通过 <Stage>_WaitConfirm / <Stage>_Confirm 握手
  -> PLC Done 后，上位机完成收尾并进入下一阶段
```

其中：

- `Step` 表示 PLC 当前子步骤。
- `Done` 表示 PLC 当前阶段完成。
- `Error` 表示 PLC 当前阶段故障。
- `WaitConfirm` 表示 PLC 等待上位机确认。
- `Confirm` 由上位机写入，用于通知 PLC 可以继续。

例如拍照或视觉处理相关步骤中，PLC 可以先运行到等待点，上位机完成拍照、分析或路径生成后，再通过 `Confirm` 让 PLC 继续执行后续动作。

## 7. 当前资源与并发颗粒度

当前系统已经有本地资源账本和并发保护逻辑，主要包括：

| 资源类型 | 管理程序 | 当前颗粒度 |
|---|---|---|
| 样品队列 | `core/scheduler.py` | 样品级任务 |
| 单个样品流程 | `core/task.py` | stage 级编排 |
| 展开缸 | `core/resource_manager.py` | 8 个 tank 独立分配和释放 |
| 点样工位 | `SpottingStage` 内部锁 | 单工位互斥 |
| 拍照/刮取工位 | `ScrapeStage` 共享锁 | 拍照和刮取互斥，多色带期间保持一致性 |
| 收集工位 | `CollectStage` 内部锁 | 单工位互斥 |
| 耗材槽位 | `core/consumable_manager.py` | 硅胶板、粉末收集器、收集瓶和槽位账本 |
| 样品结果 | `core/sample_store.py` | 样品目录、图片、元数据、分析结果 |

这些资源模型保证了当前本地自动流程可以安全并发运行。后续如果中控系统希望直接下发更细粒度动作，需要讨论这些资源状态仍由 pTLC 维护，还是需要与中控系统同步。

## 8. 当前控制颗粒度总结

当前系统实际存在四层颗粒度：

| 颗粒度 | 当前状态 | 示例 |
|---|---|---|
| 完整样品流程 | 已实现 | 一个样品从点样到收集完成 |
| Stage 阶段 | 已实现 | spotting、before_photo、develop、scrape、collect |
| PLC FSM 子步骤 | 已实现但主要由 PLC 内部控制 | Step、WaitConfirm、Done、Error |
| 更细执行器动作 | 部分存在于 PLC 内部，尚未作为外部 API 系统开放 | 气缸、泵阀、伺服、机器人移动、相机触发 |

因此，当前 pTLC 的主控制颗粒度是“样品流程 + stage 阶段”。PLC 内部已经有更细的动作步骤，但这些步骤目前主要服务于本地自动流程，并未作为外部中控系统可直接编排的动作接口。

## 9. 后续讨论引出

基于当前程序组织，后续中控系统接入需要重点讨论：

- 中控系统是调用完整样品流程、单个 stage，还是更细的业务动作。
- 如果开放更细粒度动作，阶段切换是否仍由 `RecipeTask` 负责。
- 资源账本由 pTLC 维护、中控系统维护，还是双方同步。
- PLC 的 `Step / Done / Error / WaitConfirm / Confirm` 机制是否继续作为底层动作反馈基础。
- 本地 UI、自动流程和外部中控动作之间如何做模式互斥。

建议后续会议先基于本文确认当前颗粒度，再进一步讨论哪些逻辑需要保留在 pTLC，哪些逻辑可以开放给中控系统。
