# band-edge E+B + 死体积补偿 PLC 合并改动集 — 实施 worklog(2026-07-14)

状态:**已实施,compile 0 errors,已 codesys_save**。三处 POU 回读逐字核对通过。

## 落点(与计划的差异以本文为准)

1. **GVL 实际位置**:`Application/20_变量Date/Host_Computer`(非泛称"GVL" POU)——
   `Sampling_band_end_position: INT;` 插在 `Sampling_band_dry_cycles` 后,带 GrpComment。
2. **A62**(`Application/50_action/Sampling_L2/A62_单条带点样`):按计划重写
   (蛇形 `spot_band_dir` / 并行查询块 / step 38 判终 `pos <= Sampling_band_end_position + 5` /
   step 40/42 删除 / step 99 惰性错误保持)。
3. **父派发器**(`Application/50_action/Sampling_L2`,计划未覆盖、实施中发现):
   VAR 区新增 `spot_band_dir / spot_band_query_active / spot_band_query_done`;
   IDLE-accept 与 Reset(code62)路径各补清 `query_active/query_done`——否则重派发首周期
   并行块会以残留 active 发一条无主 `/4?`。

## Opus 4.8 对抗性评审(写入前)采纳的修正

- **[blocker] 465 同周期穿透**:并行块在 CASE 之前执行,465 路径若直设 `spot_band_step := 0`,
  同周期 CASE 即命中 step 0,把刚做的急停(停轴/关气关阀)当周期撤销并反向命令回 Start。
  修法:465 跳**惰性保持步 99**(空语句,不发运动),等父派发器下周期以 `bActionError`
  接管终态。462 在 CASE 内(step 12),`step:=0` 下一拍才生效且父已接管——保持基线写法勿改。
- **[major/上机项] 收尾几何**:蛇形下末程可停在 Start 侧,step 70 的 6X→清洗位由基线恒
  从 End 出发变为 Start/End 皆可。代码推演:新路径 X 包络 ⊆ 基线已扫包络
  (Start ∈ [带区 ∪ End→清洗位]),Y 不变,无新增碰撞面;仍列上机首跑观察项。
- **[minor 加固] step 0 防御性 `泵站位符 := FALSE`**:根治"上次运行非常规中断残留占位 →
  step 12 静默死锁"的既有隐患。
- **[minor] 465 路径恢复 `fVelocity`**(基线不恢复;新版顺手恢复,防错误后轴速残留吹干速)。

## 上机验证清单(叠加两 spec 的清单)

1. 固件下装(与 `Sampling_clean_mode` 同批);⚠️ 未下装前 host 禁发 `spot_end_position_ml > 0`
   (旧固件空转 60 程报 462)。
2. 符号 XML 重导出同批(新增符号 `Sampling_band_end_position`)。
3. **465 用例专项**(评审最不放心点):真机构造查询超时(拔泵 RS485),确认报 465 后轴
   确实静止在 step 99、不回程;Reset 后可正常重派发。
4. 蛇形首跑观察:末程停 Start 侧时的收尾路径;两端边缘对称性对比照片(40mm/s 同参数)。
5. 死体积标定:knob `spot_end_position_ml` 从 0 上探。

## 警告基线

compile 40 warnings,全部为 `INT→WORD 隐含转换`(`%MW1300 := LEN(...)` 邮箱 idiom 既有类别);
新版此类写点 3 处与基线等数,无新增。
