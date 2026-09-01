# 液位检测二次改造: log 域干湿分离 + 板上干区冻结守卫 + 多帧参考 (极简 SDD)

2026-07-15 与用户两轮收敛定案 (讨论充分, 本文只钉契约; 背景见 memory
`ptlc-waterlevel-dryzone-log-redesign` 与 `docs/superpowers/plans/2026-07-14-waterlevel-drift-compensation.md`)。

## 问题 (真机整定台暴露)

1. **阴影带结构性漏检的模型根因**: 相机灰度 I = L(x)·R(x), 湿润是反射率 R 的乘性下降,
   差分信号 diff = L·ΔR **正比局部照度** —— 展缸盖阴影带 L 低, 真湿信号被压到绝对阈值
   (wet_pixel_threshold) 以下。加性差分套在乘性信号上是模型错误, 参考帧含阴影也救不了。
2. **板外金属面板干区两个根缺陷**: 材质不同源 (高反光金属 vs 哑光硅胶, drift 不等价);
   且下游末端 (前沿最后到达处) 恒被盖阴影覆盖, 真机上画不出"永不湿"的合理干区。

## 决策

| # | 决策 | 要点 |
|---|------|------|
| D1 | separate_wet 换 **log 域乘性模型** | corrected = log(ref+ε) − log(now+ε) + log(gain); wet ⇔ corrected > −log(1−k); gain = median((dry_now+ε)/(dry_ref+ε)); ε=1 兜黑电平。照度逐像素约掉 → 阴影带湿信号与亮区等强 |
| D2 | 双模式过渡 | `separation_mode`: "log"(默认) / "abs"(旧口径, deprecated, 留作整定台 A/B); 上层 percent/front/gap 对换域透明, 零改 |
| D3 | 参数换域 | k=`wet_rel_threshold` 默认 0.05 (真机 wet_thr 8.6 @ ~180 灰度 ≈ 4.8% 自洽); `diff_threshold_log` 默认 0.013 (no_signal 门, 2.0 灰度@~150 换算) |
| D4 | 干区语义放宽 **"运行窗口内不湿"** | 可画在硅胶板上 (同材质同受光); 标注准则: 完全避开阴影带的前提下尽量靠下游 (√t: 30min/90% 时前沿到 50% 仅 ~9min, 到 75% 需 ~21min) |
| D5 | **冻结守卫** (干区会被打湿, 必要机制) | ① front 逼近: front_max ≥ 干区起点pct − 10 → 冻结 (单调不解冻); ② 干区自卫: 干区内湿像素占比 > 0.15 或 gain 单步 \|Δlog\| > 0.05 → 立即冻结回滚上一可信值。防 gain 中毒 (干区被打湿→gain≪1→已湿像素被补回干→percent 崩塌)。冻结后保持最后可信 gain; 守卫常量硬编码非旋钮 |
| D6 | **参考多帧化** | request_reference 从单帧改为窗口 N 帧 (服务默认 15 帧 ≈ 30s@2s) 逐像素 median → plate_gray/dry_gray; 整定台保持单帧 (迭代速度优先) |
| D7 | 守卫归属 | 检测核心保持纯函数; 微型时序守卫 DryGainGuard 放 detector 模块 (服务与整定台共用同一口径), 是"无状态约定"的唯一显式例外 |

## 契约 (Consumes / Produces)

- `waterlevel_detector.py`:
  - `WaterLevelDetectParams` += `separation_mode:str="log"`, `wet_rel_threshold:float=0.05`, `diff_threshold_log:float=0.013`
  - `separate_wet(gray, ref, dry_now, params, gain_override=None) -> (wet_mask, drift, corrected, gain)` (abs: drift 加性/gain=1; log: drift=0/gain 乘性)
  - `detect_level(..., gain_override=None)`; `LevelResult` += `gain:float=1.0`
  - 新纯函数 `measure_dry_gain(frame,calib,ref,params) -> (gain, dry_wet_frac)|None`、`dry_zone_front_percent(calib,params) -> pct|None` (crop 修正后的流向坐标; 仅 roi_frac+dry_ref_frac 可算)
  - `DryGainGuard.filter(measure, front_percent, zone_percent) -> gain` (冻结常量: MARGIN=10pct, WET_FRAC=0.15, GAIN_STEP=0.05)
- `waterlevel_service.py`: ctor += `ref_frames=15`; 参考窗口累积+median; log 模式每帧 measure→guard→gain_override; snapshot += `gain`/`gain_frozen`; get/update_params += 3 新字段 (separation_mode 白名单 abs|log); 标定变更/重抓参考 → 重置 guard 与 front_max
- `waterlevel_store.py`: 3 新字段序列化往返; `waterlevel_config_tiers.py`: GLOBAL_JUDGMENT_FIELDS += 3
- `wl_replay_tune.py`: 滑块 += sep_mode / wet_rel(‰) / diff_log(×1e-3); HUD 显示 sep/gain; 'c' 整段回放走与服务同款 guard 时序; separate_wet 4 元组适配
- 网页参数面板暂不加新旋钮 (get/update_params 透传已通, 留后)

## 验证

- 离线套件全绿 (`python -m pytest eit_ptlc/tests -q`, 基线 623 passed)
- 新增用例: 阴影带 abs 漏检/log 检出、乘性漂移 gain 补偿、measure_dry_gain、干区几何 pct、守卫四态 (更新/front 冻结/自卫回滚/步限冻结)
- e2e 回放 A/B: ch3_20260708 (问题录像) + ch5_20260714 (关盖新录像), 对比阴影带 wet mask / front 连续性 / percent 单调性
- 上机 pending: ①8 通道干区重标 (板上, 贴阴影带边界往上游) ②k/diff_log 真机核 ③auto-drain T2 复核
