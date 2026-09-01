# 上样轻清洗(一次抽液·分段清洗/管路充液)设计 spec

日期:2026-07-14
状态:**SP-A(host)与 SP-B(PLC)均已实施并过终审**(SP-A 提交 31f961a..98d34a8 离线全绿;SP-B 提交 56cffa8+f821602,compile 0 errors、+4 警告为邮箱 idiom 同款预期、mode=0 逐字零变化、阀极性经 A60/A62/A10 三源证实)。**待上机**:§5.1 部署前置(下装本版固件 + 确认 Sampling_clean_mode 符号面可读写,符号 XML 重导出同批)+ §6 三条验证 + mode=0 回归。发现修正:A20 步 0-7 轴前置段使"针/点样头在清洗位"由 PLC 原生保证(§5 前置条件实际不依赖编排层);Reset 中断 mode=1 残留阀 TRUE 为低危留后项(worklog 有记)。
分支基线:codex/ui-upper-next

## 1. 背景与动机(根因链)

- 上样抽液停泵后液柱回落/针尖滴液,台架实验证实根因是**管内空气体积带来的顺应性**(气体弹簧),而非抽吸速度本身:空气体积越大,停泵时弹簧回缩越多;速度只改变弹簧被拉伸的程度。
- 按现行空气驱动点样策略,每次点样后**驱动空气占满上样流路前段**,下一循环抽液时管内必然有 mL 级空气 → 大顺应性不可避免。
- 治本解法:**每次点样前把管路重新充满液体**(消除空气段)。充液后抽液不再需要低速,时间反而省回来。
- 现行重清洗(`sampling.clean`,内壁+外壁各满行程 × 循环次数)太重:≥100 mL 溶剂、数分钟;不适合每次点样前执行。

## 2. 方案定型(用户已确认的物理事实)

一次吸满,分三段打向不同流路:

| 段 | 体积(默认) | 泵端口 | 三通位 | 目的 |
|---|---|---|---|---|
| 吸 | 25 mL(=三段之和) | 口1 清洗液 | 任意 | 满行程一次吸 |
| 打1 | 17 mL | 口3 输出 | 上样 | 充液上样流路(泵→三通 15.7 mL + 针流路 1.125 mL ≈ 16.8 mL,1.01×管路体积),顺带排出残液 |
| 打2 | 5 mL | 口2 废液 | (无关) | 冲上样针外壁(外壁流路体积 2–4 mL) |
| 打3 | 3 mL | 口3 输出 | 点样 | 冲点样头 |

流路拓扑(用户确认):外壁流路走泵口 2;上样流路与点样头共用泵口 3,由外部三通阀切换;三通阀是 PLC DO(plc_nodes:"上样点样三通电池阀手动/自动")。

物理要点:充液段(打1)用**偏高打速**(默认 300,守卫上限 500)冲刷贴壁气泡;点样头段低速(默认 100)。

## 3. 切面契约(钉死,SP-A / SP-B 共同真源)

### 3.1 PLC 通道(全部复用现有 clean 通道,新增仅一个 mode 变量)

- 复用:`Sampling_clean_instructions : ARRAY[1..2] OF STRING`、`Sampling_clean_count`(轻清洗恒写 1)、clean 步骤的 action_code 与终态锁存契约。
- **唯一新增变量**:`Sampling_clean_mode : INT`(0 = 重清洗/现行行为,1 = 轻清洗充液)。
- **防陈旧契约**:host 侧 `sampling.clean` 与 `sampling.flush` 两个动作**每次派发都显式写入 mode**(clean 写 0,flush 写 1),不依赖 PLC 复位,不允许缺省。

### 3.2 指令数组内容(由 host translator 生成)

- `entry[1]`(链式三合一,全程三通=上样位,无外部阀动作):
  `/{addr}V{asp}I1A{total_steps}M{delay}V{flush_spd}I3A{p1}M{delay}V{flush_spd}I2A{p2}M{delay}R`
  其中 `total_steps = steps(v1+v2+v3)`,`p1 = total_steps − steps(v1)`,`p2 = p1 − steps(v2)`。
- `entry[2]`:`/{addr}V{spot_spd}I3A0M{delay}R`(打到 A0,体积恒等于 v3,不变量:轻清洗结束活塞必在 0 位)。
- 默认参数:v1/v2/v3 = 17/5/3 mL,asp_speed 250,flush 打速 300,点样头打速 100,delay = STEP_DELAY(1500 ms);校验 v1+v2+v3 ≤ 25 mL 且各段 > 0,打速 ≤ 500。
- 链式指令长度默认约 51 字符(缓冲区上限 255,余量充足)。

### 3.3 FSM 时序(mode=1 分支,插在现有 clean 步骤内)

```
三通→上样位(确保) → 派发 entry[1] → pumpCmd FB Q 确认空闲
→ 切三通→点样位 → 派发 entry[2] → Q 确认空闲
→ 三通复位→上样位 → 终态锁存 DONE(沿用 IF NOT Start 锁存契约)
```

- mode=0:与现行路径逐位一致,零行为变化(回归风险隔离在分支判断一处)。
- 切阀时机恒在 entry 边界、泵确认空闲之后,不做泵运动中的时序耦合。
- 泵错误(Q 返回错误码)沿既有 clean 错误路径上报,不新增错误通道。

## 4. Sub-project 拆分(可并行,联调需上机)

- **SP-A host**:`sample_translator_v2.build_flush_array()`(2 条指令,§3.2 契约)+ `sampling.flush` 动作 YAML(新 action 文件,复用 clean 的 station/action_code,params:三段体积 + asp_speed + flush_disp_speed + spot_disp_speed + step_delay,knob 透传沿现行模式)+ `profiles.py` builder(同时给 clean/flush 补 mode 显式写入)+ `PUMP_DEFAULT_HINTS` + 离线测试(步数守恒/A0 不变量/和 ≤25 校验/契约记账)。
- **SP-B PLC**:`Sampling_clean_mode` 变量 + clean 步骤 FSM mode=1 分支(§3.3)+ 三通 DO 驱动 + 离线仿真 FSM 同步该分支,喂 L2 离线验收套件。
- 依赖:契约(§3)已钉死,SP-A/SP-B 可并行;真机联调是唯一汇合点。

## 5. 编排与前置条件

- **前置条件(编排层保证,PLC 不校验)**:执行 flush 时上样针在废液/清洗位(打1 的 17 mL 从针尖排出)、点样头在其清洗位(打3 的 3 mL 从点样头排出)。
- 编排变更:每次点样前的清洗由重清洗换成 `sampling.flush`;重清洗保留在换样/初始化路径(深度去污需多倍体积置换,轻清洗对整条主管路只有 ~1× 置换,但对被样品污染的前段 ~1.1 mL 是 ~15× 置换)。
- 收益账:溶剂 25 mL/次(现行 ≥100 mL),全程约 1 分钟(吸 26 s + 三段打 ~30 s)。

## 5.1 部署顺序前置条件(终审 Important,真机暴露 flush 前必须满足)

- **SP-B 未落地前,不得在真机派发 `sampling.flush`**(调试坞人工单发也不行)。原因:`opcua_driver.write_many` 对 PLC 符号面不存在的节点只记 WARNING 并静默跳过——若 PLC 固件尚无 `Sampling_clean_mode` 变量,host 自认为发了 mode=1,PLC 实际按 mode=0 的现行 clean FSM 消费 flush 的指令数组:泵行程安全(A 值单调、终态回 A0),但**不会在 entry 边界切三通**,17 mL 会从三通当前指向的流路排出,可能喷错位置。
- 换手清单加一条:真机启用 flush 前,确认 PLC 工程 ≥ SP-B 落地版本且 `Sampling_clean_mode` 在符号面可读写。
- 可选加固(未实施,留为 SP-B 联调时决策):executor 派发前校验 `Sampling_clean_mode` 节点存在,缺失则显式拒绝,把静默降级变成硬错误。

## 6. 上机验证清单(MVP 先行,mvp_staged_clean.py 方式一)

1. 分段手动执行(段间手动切三通),确认 17 mL 充液后管路无可见气段、3 mL 够冲点样头。
2. 轻清洗后立即做一次抽液,确认停泵回落/滴液消失(根因验证闭环)。
3. 体积/速度若需调整,均为参数,不影响本 spec 骨架。

## 7. 刻意不做

- 不做通用"泵指令+阀动作混合序列"机制(第二个同类需求出现前不抽象)。
- 不扩 `Sampling_clean_instructions` 数组长度,不新增 PLC 步骤。
- 不切细分模式 N1/N2(缓议:待 µL 级直接计量需求出现,作为"翻译器单位制 + PLC 行程闸/查询语义 + 初始化显式设模式并 ?28 校验"打包项目)。
