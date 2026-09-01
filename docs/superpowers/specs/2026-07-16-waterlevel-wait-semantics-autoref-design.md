# 液位 wait_level 降级语义修正 + 参考图自动采集 — 设计

日期: 2026-07-16
状态: 待用户评审 (4 个决策点采用推荐值, 已标注, 评审时可改)
前置诊断: 2026-07-16 会话 (ch6 0715 录像回放实证); 修订对象: `docs/superpowers/specs/2026-07-13-waterlevel-auto-drain-design.md` 的 degraded 语义

## 1. 问题 (回放实证)

ch6 0715 录像 (37min/21937 帧, 帧源零断档、亮度稳定) 按检测服务真实管线回放:

1. **前沿到 ROI 需 ~26min**, 期间 `detect_level` 恒返 `valid=False, reason=no_signal` (物理正常等待态)。`wait_level` 把它按坏帧累计, 30s (`staleness_s`) 即 `degraded`→HITL ⇒ **auto_drain 模式几乎必在开始 ~30s 误升 HITL**。
2. **参考图无自动采集**: `request_reference` 仅调试页手动按钮触发, 且只存内存。无参考时 `detect_level` **静默 Otsu 回退**, `valid=True` 但 percent 无意义 ⇒ "百分比不可靠"。参考是板专属基线, **每 run 换板即作废**, 必须每 run 重拍。
3. front_percent 56→100 单拍跳变 (`front_gap_frac` 桥接), T1/T2 同拍命中, T1 提前量失效。
4. 结构性隐患 (本次录像未现, wl.log 证实相机断流重开真实存在): 相机重开曝光爬坡的**暗帧**在 log 模式下算出 `valid=True, percent≈100` (log_ref−log(ε) 巨大→全板判湿), 且永久污染 `front_max` (单调) 冻结增益守卫。

## 2. 目标 / 非目标

**目标**: auto_drain 模式下, 干板等待期不误升 HITL; 无参考不产出可信假象; 参考图每 run 自动采集; 单帧尖峰/暗帧不假触发排液。
**非目标**: 前沿定位算法本身 (跳变根因 front_gap_frac 桥接口径) 不动 — 由去抖兜; 香橙派载荷不动; UI 大改不做 (仅文案)。

## 3. 设计

### 3.1 `wait_level` 坏帧三分类 (waterlevel_trigger.py)

现状: 所有非 reached 情形一律按坏帧累计, ≥staleness_s → degraded。改为按 reason 分类:

| 类 | reason | 行为 |
|---|---|---|
| **正常等待** | `invalid:no_signal`、`front_none`、valid 未达阈 | 不降级, 一直等 (hard_cap 兜底); 不计 bad_since |
| **传输降级** | `unreachable`、`stale:*`、`channel_missing`、`invalid:frame_dark` | 持续 ≥ staleness_s → `degraded` (现状语义) |
| **配置错误** | `no_roi`/`empty_roi`、`has_ref=False` | **立即** `degraded`, reason 前缀 `config:` |

- `has_ref` 从 snapshot 通道字段读 (已有); has_ref=False 时**不采信任何 percent/front** (堵死 Otsu 回退假信号)。
- 返回契约不变 (三态 status + reason/front_percent/threshold/elapsed_s), 流程 if 分支零改动兼容。
- 日志: 进入等待态首拍 INFO 一条 "前沿未出现, 正常等待中"; 传输降级仍按现状 WARNING。

### 3.2 reached 去抖 【决策: N=2, 待确认】

连续 `confirm_n` 拍 (默认 2, min 1=现状) `front_percent >= threshold` 才返回 `reached`; 中断即清零重计。+~4s 延迟, 展开尺度可忽略。action YAML 增参 `confirm_n`。

### 3.3 新 action `develop.capture_reference` (kind: host)

- host 方法 (bootstrap `vision_methods` 注册, 与 `wait_level` 同模式): `ensure_active(ch)` → `detect.request_reference(ch)` → 轮询 snapshot `has_ref` 直到 True 或超时 (`timeout_s` 默认 90; 窗口本体 = ref_frames×interval ≈ 30s)。
- 返回 `{ok, has_ref, elapsed_s}`; 超时/不可达 → `ok=False` (DONE, 流程分支消费, 不 raise)。
- 挂点: `develop_execute.yaml` body 开头、`auto_drain` if 之前 (人工门模式同样受益 — 排液前快照 waterlevel_observation 依赖参考)。物理正当性: load 段 `plate_extend` 后板已就位、前沿离 ROI 数十分钟, 30s 窗口安全。
- **失败语义 【决策: 升 HITL 确认继续, 待确认】**: `ok=False` → `op: human confirm` "参考图采集失败, 本次液位检测不可用, 确认继续? (auto_drain 本次退化为人工门+硬上限)"; 确认后跳过 wait_level 直接走人工门分支。
- 每 run 无条件重拍 (覆盖旧参考; `request_reference` 已有重开窗口语义)。

### 3.4 暗帧守卫 (waterlevel_service._process) 【决策: 加, 待确认】

有参考即查 (log/abs 同罹此病, 与分离口径无关), 检测前比较 ROI 均亮度: `mean(gray) < DARK_FRAME_RATIO × mean(ref.plate_gray)` (常量 0.35) → 记 `LevelResult(valid=False, reason="frame_dark")`, **不喂 front_max、不喂增益守卫**。wait_level 按传输降级类累计 (爬坡数秒不触发, 持续黑才 HITL)。

### 3.5 无前沿超时 【决策: 不加 (YAGNI), 待确认】

检测健康但前沿久不出现 → 依赖 hard_cap (3600s) 兜底直排 (宁欠展开不过展开, 既有契约); 相机定格由香橙派 60 帧指纹看门狗自愈。不新增参数。

### 3.6 UI 文案

网格/单路状态: `no_signal` → "等待前沿" (现显示 reason 原文/"无信号" 误导); `frame_dark` → "画面过暗"; has_ref=False → "未采参考"。仅 WaterLevelGrid/Channel 的 status 映射, 不动布局。

### 3.7 develop_execute.yaml 接线 (伪)

```yaml
- call develop.capture_reference {target_tank: tank} → assign ref_result
- if !ref_result.ok → human confirm "参考图采集失败…" → 走人工门分支 (跳过 wait_level)
- if auto_drain → (原 T1/T2 wait_level 链, 不变) …
```

## 4. 切面契约 (Consumes / Produces)

- `wait_level(detect, *, target_tank, stage, staleness_s=30, hard_cap_s=3600, poll_s=2, confirm_n=2, …)` → dict 三态 (形状不变, reason 新增取值 `config:*`/`frame_dark`)。
- `capture_reference(target_tank: int, timeout_s: float = 90) -> {ok: bool, has_ref: bool, elapsed_s: float}`。
- snapshot 通道字段不变 (has_ref/reachable/reason 均已存在); LevelResult.reason 新增 `frame_dark`。

## 5. 测试

1. `test_waterlevel_trigger_offline` 扩展: no_signal 持续 >staleness_s 不降级、直到假时钟 hard_cap; unreachable 30s 仍降级; has_ref=False 立即 config-degraded; confirm_n=2 单拍尖峰不触发、两拍触发。
2. service 暗帧用例: 全黑帧 → reason=frame_dark 且 front_max 不变。
3. capture_reference action 离线用例 (fake detect: 正常完成 / 超时)。
4. e2e 对照: ch6 0715 录像回放脚本跑修正后语义 → 0 次误降级, T2 命中时刻不变 (±1 拍去抖延迟)。

## 6. 上机验证清单 (实施后)

1. 真机跑一次 auto_drain=true 全程: 无 30s 误 HITL; 参考图自动就位 (日志 "[WL] CHx 参考已捕获")。
2. 拔一路相机 USB ≥ staleness_s: degraded→HITL 仍触发 (传输降级保留)。
3. 手动清参考后直接跑 execute: capture_reference 自动补齐。
4. 观察 T2 触发排液时刻与人工判断偏差。

## 7. 决策点汇总 (评审焦点)

| # | 决策 | 采用 (推荐) | 备选 |
|---|---|---|---|
| D1 | 参考采集失败 | 升 HITL 确认继续 | raise 中止 / 仅告警 |
| D2 | 无前沿超时档 | 不加 (hard_cap 兜底) | 加 no_front_timeout_s |
| D3 | reached 去抖 | N=2 (+4s) | N=3 / 不加 |
| D4 | 暗帧守卫 | 加 (ratio 0.35) | 不加 |
