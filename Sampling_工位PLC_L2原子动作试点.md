# Sampling 工位 PLC L2 原子动作试点

## 总结

- 首站选择 Sampling，不再先做 Collect。
- 交付终点为完整内部主线：PLC L2、上位机通信、调试/验收工具、两条机器人路线和 RecipeTask；暂不开放 FastAPI。
- 旧 `Sampling_Enable` 仅在迁移期保留，L2 真机验收后删除。
- 保留现有 HMI 手动、示教、回零、复位和急停；L2 运行时拒绝切入手动。
- 上样位没有板传感器，因此装卸结果明确标记为“命令级确认”，不宣称物理到位验证。

## PLC 动作与协议

统一动作通道：

```text
PC→PLC:
Sampling_L2_ActionCode : INT
Sampling_L2_RequestSeq : DINT
Sampling_L2_Start      : BOOL
Sampling_L2_Reset      : BOOL
现有具名工艺参数

PLC→PC:
Sampling_L2_State        : INT
Sampling_L2_ActiveCode   : INT
Sampling_L2_AcceptedSeq  : DINT
Sampling_L2_CompletedSeq : DINT
Sampling_L2_Step         : INT
Sampling_L2_ErrorCode    : INT
Sampling_L2_SafeState    : INT
Sampling_L2_Retryable    : BOOL
```

状态采用 `IDLE → RUNNING → DONE|REJECTED|ERROR|INTERRUPTED`；终态保持到 `Start=FALSE`。不增加通用 Confirm、Owner 或万能参数数组。

| Code | PLC L2 动作 | 复用/拆分来源 |
|---:|---|---|
| 10 | `Sampling_Init` | A00，保持现有回零和泵初始化顺序 |
| 20 | `Sampling_Clean` | A10，继续使用现有指令数组和 count，不新增 mode |
| 30 | `Sampling_PrepareFluid` | A30，空气隔离段和排废准备 |
| 40 | `Sampling_PreparePlateReceive` | 从 A20 拆出轴让位和夹持释放 |
| 50 | `Sampling_ClampPlate` | 机器人放板后锁存夹持命令；板存在状态未知 |
| 60 | `Sampling_AspirateSample` | A40，保留当前轴序列和泵时序 |
| 70 | `Sampling_DispenseSample` | A50 点样主体，结束时泵、阀和吹气关闭 |
| 80 | `Sampling_PreparePlateRelease` | 从 A50 尾段拆出轴归位和夹持释放 |
| 90 | `Sampling_FinishPlateRelease` | 机器人取板成功后清本地状态；板移除仍属弱确认 |

- `SafeState` 固定为 `UNKNOWN / READY / PLATE_HELD_UNVERIFIED / RELEASE_READY_UNVERIFIED / RECOVERY_REQUIRED`。
- 1xx 错误用于启动拒绝，2xx 轴错误，3xx 泵/DT，4xx 急停或模式问题，5xx 状态不一致/结果不确定。
- 只有动作接受前的 `BUSY` 等拒绝可标记 retryable；已接受的物理动作默认不可自动重发。
- 迁移期增加 `Sampling_ControlMode=LEGACY|L2`，默认 LEGACY，切换仅允许两侧均空闲。L2 运行时保持自动模式并报告手动切换被阻止；急停仍具有最高优先级。
- 同一 Sampling POU 内互斥调用旧 FSM 与 L2 执行器，继续复用底层轴、泵和气缸变量，保证物理输出单写者。

## 上位机与机器人主线

- 新增通用 `PLCActionClient.execute(station, action, params) -> PLCActionResult`；每次连接维护单调序号，断线后查询原序号状态，绝不自动重发结果不明确的动作。
- Mock PLC 增加完全同构的 L2 节点、动作轨迹、拒绝和故障注入；硬编码节点类型同步更新。
- 扩展机器人主机动作绑定，使 `plc_action` 可调用 L2 动作，而非直接写旧握手 BOOL：
  - `plate.feed-to-spotting`：PrepareReceive → 机器人放板 → ClampPlate。
  - `plate.spotting-to-scrape`：PrepareRelease → 机器人取板 → FinishPlateRelease。
- 启动时构建一个共享 RobotRuntime/路线资源账本，经 Scheduler → RecipeTask → SpottingStage 显式注入，不使用全局单例。
- SpottingStage 保留参数翻译、日志和整段工位锁，但内部改为九个 L2 动作及两条现有机器人路线；完整点样期间不允许其他样品占用 Sampling。
- 增加独立 Sampling L2 验收 CLI，并在上位机 Debug 页提供本地动作、状态、Reset 和完整试点序列；调试入口与 RecipeTask 使用同一客户端。
- 暂不实现 FastAPI、SystemResourceView、通用 ActionListExecutor或其他工位协议。

## PLC 交付、迁移与文档

1. 交付可复制粘贴/导入的 ST：GVL 声明、Sampling POU 改造、动作实现和模式互锁，并附 InoProShop 操作清单；先尝试 XML 导入，失败时按分块复制粘贴。
2. 现场工程师导入、编译并回传新 XML；再核对变量类型、单写者和导出差异。
3. 以 LEGACY 跑同配方基线，再切 L2 分阶段验收。
4. L2 整段通过后删除旧 `Sampling_Enable/Step/Done/Error/Busy` 入口、Sampling 的旧机器人流程 10/20 及相关握手变量；保留现有具名工艺参数和 HMI 底层变量。
5. 更新“当前事实、目标动作、实施设计”三类活跃文档；清理仍宣称 collect 首站或永久保留双路径的根目录 `.work.md`，历史内容留在 `Backup/`。
6. 不覆盖当前工作树已有文档修改；提交前按仓库约定询问是否记录实验日志。

## 测试与验收

- 离线：保留当前已通过的 7 项主机绑定和 8 项 RouteExecutor 测试，并新增协议序号、旧结果隔离、模式互斥、参数校验、故障分类、断线不重发、取消/E-Stop、九动作顺序和 RecipeTask 全链路测试。
- PLC 编译门：无未定义变量、无重复写者、ST 类型与 OPC UA Variant 一致、旧 LEGACY 路径仍可运行。
- 真机依次验收：Init/Clean/PrepareFluid → 放板路线 → Aspirate/Dispense → 取板路线 → 单样完整流程 → 连续两样。
- 必测异常：运行中请求手动被拒绝、动作结束后 HMI 手动恢复、急停、Reset、泵忙、轴不到位、OPC UA 断线和机器人路线失败。
- 因无板传感器，装卸验收必须记录人工观察；日志和文档不得把机器人完成或夹持输出等同于板物理到位。
- 只有完整 L2 流程、HMI 回归和恢复测试全部通过后，才删除 LEGACY 路径并扩展到下一工位。
