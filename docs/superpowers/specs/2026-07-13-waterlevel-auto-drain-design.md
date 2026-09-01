# 液位双阈值自动触发排液 · 设计 spec

日期: 2026-07-13
分支: codex/ui-upper-next
相关: docs/液位检测_触发线定前沿_QR标定_单ch录制_实施计划_20260706.md · docs/Rf测量_真机测试与落地_数据采集清单_20260709.md

## 1. 背景与问题

展开工位当前的排液触发是纯人工: `develop_execute.yaml` 里一道 HITL confirm 门
("展开完成? 确认开始 PLC L2 排液") → `develop.drain` (PLC L2 code 50)。
液位检测服务 (`WaterLevelDetectService`) 已在上位机以 2s 周期产出前沿位置快照,
但快照只被 UI 和 `WaterLevelObservationCollector` (诊断存档) 消费, **与排液触发之间没有接线**。

人工触发的问题:
- 操作员必须盯屏, 点击时机方差大 → 过展开 / 欠展开不可控;
- 触发一致性差直接威胁 Rf 测量的 D_f-常量假设 (0709 清单假设②: percent 阈值 → 前沿位置可重复);
- 排液序列 (真空抽液 → 正压吹扫 → 开盖等机器人取板) 期间**砂芯仍有残液**,
  板与砂芯接触, 前沿在排液触发后还会继续推进一段 — 这段净推进量目前完全未量化
  (PLC code 50 对上位机是黑盒, 只等 `Tank_State=99`)。

## 2. 目标 / 非目标

**目标**
1. auto 模式下, 液位前沿到 T2 阈值自动触发 `develop.drain`, 不需人工盯屏;
2. T1 (预告阈值) 命中时流程内物理就位: 地轨到展开区 + 机器人到待命位,
   压缩排液完成开盖后板在蒸气/干燥环境中的滞留;
3. 两层看门狗: 检测降级 → 回落 HITL; 展开时长硬上限 → 直排兜底;
4. P0 上机实验量化砂芯残液期的前沿净推进, 反哺 T2 提前量。

**非目标 (YAGNI, 明确不做)**
- 多缸并行的机器人资源预约/调度 (res_gate 目前只有拿住/等待两态, 预约、优先级、
  抢占是下期资源模型专题; 本期 T1 语义已为它留位, 不动 ResourceManager);
- "直接拔板" 应急路径 T3 (牵涉湿板滴液、开夹取浸液板的机械可行性, 等 P0 数据后再议);
- `percent` (湿润面积) 作为触发信号的兜底混用 (量纲语义不同, 见 §4-1);
- PLC 侧闭环 (检测算法与相机都在上位机, 不成立)。

## 3. 关键事实 (设计依据, 已核实)

1. **`front_percent` 是面积法衍生的, 不是脆弱的直接找边**: `detect_level` 先差分
   (无参考图退 Otsu) 分割湿像素掩码 (与 `percent` 同源), 沿流动方向压成逐列/逐行
   湿润比例 profile, 从流入侧扫描首次跌破 `front_ratio_level` 处即前沿位置。
   鲁棒性继承自面积分割, 且是与 "触发线 → D_f 常量" 物理对应的量。
2. **VM 是 asyncio 协程, 不是 OS 线程**: `VmThread` = 一个 async 协程驱动的 mini-VM。
   阻塞等待动作实现为 async 轮询, 8 缸并行也只是 8 个休眠协程, VM 执行架构不构成
   并行瓶颈; 未来瓶颈在资源模型 (见非目标)。
3. **当前资源持有形态**: `develop_cycle` / `ptlc_full_v2` 整程持有 `robot`,
   单样本串行下机器人排队问题不存在; T1 的现实价值 = 物理就位省时 + 为多缸并行留语义位。
4. **`develop.drain` (code 50)** 自带 `stall_timeout: 180s / action_timeout: 900s`;
   PLC 侧排液序列对上位机是黑盒整段。
5. **砂芯残液**: 水平展缸内有砂芯借毛细吸液, 板与砂芯接触; 抽液后砂芯仍含残液,
   "泵启动 ≠ 断液", 真正断液时刻未知 → P0 实验是唯一量化手段。

## 4. 架构决策

**总架构 = 方案 A: VM 内阻塞等待动作 `develop.wait_level`**
(仿 `photoscrape.analyze` 的 host 动作先例, executor 注入 detect service)。
流程保持声明式, 看门狗/硬上限是动作参数, 离线测试只需 fake detect service,
与运行所有权/恢复向导零冲突。已否决: 上位机常驻监视服务代派发 (双写者抢 run 状态,
违反 "浏览不得干扰运行" invariant 的同类雷区)、PLC 侧闭环 (不成立)。

**决策点 (均已与用户确认):**

1. **触发信号 = `front_percent` 单变量**。不用 `percent` 兜底;
   `front_percent` 连续无效走看门狗路径, 不换信号顶替。
2. **阈值归属 = `ChannelConfig.params` (每通道, 标定层)**: 新增
   `trigger_percent_t2` 与 `t1_offset` (T1 = T2 − offset)。同通道每次同阈值是
   D_f-常量方案的前提; 阈值是标定量, 不是每 run 旋钮。
3. **HITL 保留为模式开关**: run 级 knob `auto_drain` (走既有 knob 透传机制),
   默认 manual (现状 HITL 门原样), 上机验证后再翻默认。
4. **触发优先级: 检测算法 > HITL > 硬上限**。
   - 检测健康: T2 命中即自动排液;
   - 检测降级 (数据陈旧 / 掉流 / front_percent 连续无效): 报警事件 + 升级 HITL 确认门,
     **人一旦介入, 硬上限不再自动开火** (人的决定权高于超时);
   - 硬上限只在 "自动等待中、无人介入、检测始终未到 T2" 一条路上兜底直排
     (宁可欠展开, 不可过展开)。
5. **P0 实验先软件后上机**: 软件全部离线可测, 先实现; 上机用 auto 模式 + 保守低阈值,
   VM 事件时间戳 × 录制曲线对齐, 得触发后前沿净推进量 (含砂芯残液段);
   色素滴注作交叉验证 (已知高度滴色素, 到位即触发排液, 直接可视化后续行走距离,
   不依赖检测算法)。与 Rf 假设② (M≥10 块板前沿可重复) 同批上机, 一次两用。

## 5. 组件设计

### 5.1 新动作 `develop.wait_level`

- kind: host 类 (仿 vision 动作接线方式), `ActionExecutor` 注入 `WaterLevelDetectService`;
- 参数: `target_tank` (1-8, 通道即缸号), `stage` (`t1`/`t2`, 查该通道
  `ChannelConfig.params` 取阈值), `staleness_s` (陈旧判据), `hard_cap_s` (展开时长硬上限,
  从进入等待起计, t1/t2 两段共享同一预算 — 具体分账在 plan 定);
- 行为: async 轮询 detect service 快照 (不自己拉帧, 周期与检测服务同阶 2s);
- 返回: `{status: reached | degraded | hard_cap, front_percent, elapsed_s}`;
- 事件: 命中/降级/硬上限各发 VM 事件 (进日志与 UI), 时间戳供 P0 实验对齐。

降级判据 (任一命中即返回 `degraded`):
- `observed_at` 距今超 `staleness_s`;
- `reachable=false` 持续超 `staleness_s`;
- `valid=false` 或 `front_percent=None` 连续 N 个周期 (N 在 plan 定, 建议 ≥5)。

### 5.2 流程改造 `develop_execute.yaml`

```yaml
- if auto_drain:                        # run 级 knob, 默认 false
    - call develop.wait_level (stage=t1) → wl_status
    - if wl_status == reached:
        - run_script develop_standby    # T1 物理就位
        - call develop.wait_level (stage=t2) → wl_status   # 覆写同一变量
    - if wl_status == degraded:         # 任一段检测降级 → 人兜底
        - human confirm("液位检测异常, 确认排液?")
    # wl_status == hard_cap → 不设门, 直落 drain (兜底直排 + 报警事件已发)
    - call develop.drain
  else:                                 # 现状原样
    - human confirm("展开完成? 确认开始 PLC L2 排液")
    - call develop.drain
```

(伪码示意; if/嵌套的确切 YAML 形态按 VM schema 现有 `if`/`human` 口径在 plan 落定。
T1 段降级时跳过物理就位直接进 HITL — 人确认后排液, standby 由人补位。)

### 5.3 新流程脚本 `develop_standby`

地轨到展开区 (位5, 复用 `rail.move`) + 机器人到展缸待命位。
遵守既有不变量: 原子动作不嵌地轨、编排段首拥有一次 rail (本脚本即编排段)。
点位选取在 plan 定 (倾向复用 robot_tank_pick 的进近前置位)。

### 5.4 阈值配置 `ChannelConfig.params`

新增字段 (随既有 params 同文件持久化, 走 `waterlevel_store`):
- `trigger_percent_t2: float` — T2 触发阈值 (front_percent, 0~100);
- `t1_offset: float` — T1 = T2 − offset (默认值在 P0 实验后定, 先给保守占位)。

前端: 液位标定/参数面板补两个输入 (复用 `update_params` 通道)。

### 5.5 观测联动 (零改动)

`WaterLevelObservationCollector` 在 `develop.drain` 派发前冻结快照的机制不动 —
auto 模式下该快照即 "自动触发时刻的液位", Rf 假设②的数据顺带成型。

## 6. 错误处理汇总

| 情形 | 行为 |
|---|---|
| 检测健康, front_percent ≥ T2 | 自动 `develop.drain` |
| 数据陈旧 / 掉流 / 连续无效 | 报警事件 + 回落 HITL 确认门 (人决定, 硬上限不再自动开火) |
| 自动等待超 `hard_cap_s` (无人介入) | 直接 `develop.drain` + 报警标注 (欠展开优于过展开) |
| `develop.drain` 自身卡死 | 既有 stall 180s / action 900s 看门狗, 不变 |
| `wait_level` 内部异常 | VM 既有 raise → 恢复向导路径 |

## 7. 测试

**离线 (全部可在无硬件跑):**
- fake detect service 按脚本吐快照序列, 覆盖四路径: 正常到 T2 / 陈旧降级 / 掉流降级 / 硬上限直排;
- `develop_execute` auto/manual 两模式流程离线跑通 (含 T1→standby→T2 序列与降级跳 standby);
- 阈值字段在 `ChannelConfig.params` 的读写/持久化/前端 API 往返;
- 人介入后硬上限不开火的优先级语义。

**上机 (P0 实验, 软件落地后):**
- auto 模式 + 保守低阈值, 录制 (`waterlevel_recorder`) 全程 front_percent(t),
  与 wait_level 触发事件时间戳对齐 → 触发后净推进量 (含砂芯残液段);
- 色素滴注交叉验证 (不依赖检测算法);
- 同批采集 Rf 假设②数据 (M≥10 板, 触发即排液 → scrape 拍照);
- 依据结果定 `trigger_percent_t2` 提前量与 `t1_offset`, 再翻 `auto_drain` 默认值。

## 8. 后续留位 (本期不做, 语义已兼容)

- 多缸并行: `wait_level` 是协程等待, 天然可 8 缸并挂; 届时只需资源模型升级
  (预约/优先级/抢占), T1 从 "物理就位" 扩为 "资源预约 + 物理就位", 流程形态不变。
- T3 直接拔板应急路径: 若 P0 显示砂芯残推量不可接受再议。
