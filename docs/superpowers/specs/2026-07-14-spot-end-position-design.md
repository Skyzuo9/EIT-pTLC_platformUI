# 点样活塞终点位置可配置(上样流路死体积补偿)设计 spec

日期:2026-07-14
状态:**已实施**(同日):host 侧 Task 1/2 落地(离线全套 595 passed;提交 2ce85c8+b5be5ec);
PLC 侧并入 band-edge E+B 单一 A62 改动集(判终 `pos<=N+5` 在新 step 38;compile 0 errors
已 save,worklog 见 `plans/2026-07-14-band-edge-eb-worklog.md`)。
待上机 3 项:符号 XML 重导出(与 clean_mode 同批)、固件下装(⚠️ 未下装前 host 禁发 N>5,
旧固件空转 60 程报 462)、标定流程(knob 从 0 上探定值,定值写 config.pump)。
2026-07-15 补:feat/pump-defaults-config 已合回(9d7ce9c),`spot_end_position_ml` 的
config 层已注册(668a3bf:_parse_pump float mL 键 0..5 + app.yaml 播种 0.0 + hint 同源),
三层链 knob > config.pump > 0.0 全部生效,全套件 623 passed。

## 1. 背景与目的

`sampling.spot_band_layer`(PLC L2 动作 62)当前把活塞打到绝对 0 位作为点样结束条件:
host 侧 `build_spot_band_run_cmd()` 生成写死的 `A0R` 供液指令;PLC A62 步链(真代码
2026-07-14 已核)每程后 step 24 发 `/4T` 停泵、step 26 发 `/4?` + TON[10] 200ms 沉降后
扫字节解析真活塞位,**判终条件是 `spot_band_pos <= 5`(现成 5 步容差)**,否则吹干、
回起点再来一程;单带 60 程保险(超报 ErrorCode 462),查询无效重试 5 次(超报 465)。

问题:上样吸液流路存在死体积——当全部样品已被驱动清洗液推出点样头后,泵腔里剩余的
驱动液继续打出的只是纯清洗液,点到板上稀释/展宽条带。补偿方法:让活塞停在一个
**用户标定的绝对终点位置 N**(N ≈ prep 保留驱动液体积 − 流路死体积),而不是 0。

## 2. 参数语义与层级(已确认)

- 新参数 `spot_end_position_ml`:**点样结束时活塞停在的绝对位置**,单位 mL
  (host 经 `_ml_to_steps` 换算,25mL/6000 步,1 步 ≈ 4.17µL)。
- 缺省 0.0 = 现行为逐字不变。
- 三层链:**knob(action 参数,标定期逐次试值)> config.pump 标定值 > 缺省 0.0**。
  与 pump-defaults-config 机制同构。
- ⚠️ 依赖注记:config.pump 三层链实现在 worktree 分支 `feat/pump-defaults-config`
  (a945fe0..90d0103,终审 Ready-to-merge,因主树 app.yaml/bootstrap.py 他会话 WIP
  尚未合回)。本 spec 的 knob 层与 PLC 层**不依赖**该分支,可先行落地
  (knob > 常量 0.0);config 层在该分支合回后补一行注册即可(spec 记 hook 点)。

## 3. 改动面(Consumes / Produces)

### 3.1 Host — translator(`tools/pump/sample_translator.py` + `sample_translator_v2.py`)

- `build_dispense_all_cmd()` 增加可选参数 `end_steps: int = 0`,指令
  `A0` → `A{end_steps}`。缺省 0 → 现有全部调用方(A20 清洗 entry[2]、A60 旧点样、
  轻清洗数组)**零 diff**。
- `build_spot_band_run_cmd()` 增加 `end_position_ml: float = 0.0`,内部换算
  `end_steps = _ml_to_steps(end_position_ml)` 后透传。换算只做一次,
  返回值同时供指令串与 PLC 节点(见 3.2),保证两处 N 一致(单一真源)。
- 校验:`0 <= end_position_ml <= 5.0`(与 3.3 的 min/max 闭区间一致,超出抛 ValueError;5mL 上限
  留足 prep 缺省 3mL 驱动液 + 余量,防误配大值导致一程不点)。

### 3.2 Host — profiles builder(`tools/pump/profiles.py`)

`_build_sampling_spot_band_layer()` 消费 `values.get("spot_end_position_ml")`
(None → 0.0,合回 config.pump 分支后此处改为 config 回退 hook 点),返回节点新增:

```python
"Sampling_band_end_position": end_steps,   # Int16, 与 run_instruction 的 A{N} 同源
```

### 3.3 Host — action 声明(`config/actions/01_sampling/plc_sampling.yaml`)

`sampling.spot_band_layer.params` 新增:

```yaml
- {name: spot_end_position_ml, type: float, required: false, min: 0.0, max: 5.0,
   label: 点样活塞终点位置 (mL, 死体积补偿, 缺省=0)}
```

### 3.4 Host — PLC 节点注册(`config/plc_nodes.yaml`)

```yaml
Sampling_band_end_position: {type: Int16, comment: "单条带点样: 活塞终点目标步数(死体积补偿); 0=打到底(旧行为)"}
```

### 3.5 PLC — GVL + A62 步链(CODESYS 工程 20260702.project)

- GVL 新增 `Sampling_band_end_position: INT`(兄弟风格无 pragma,整组符号导出)。
- A62 step 26 判终条件:`spot_band_pos <= 5` →
  `spot_band_pos <= Sampling_band_end_position + 5`(保留现有 5 步容差;泵按 A{N}R
  自空闲在 N,容差覆盖解析/步进舍入)。host 写 0 时逐字等价现行为。
- 60 程保险(462)与查询重试(465)语义不变。
- 退化安全:若起始位已 ≤ N+5,首程 Q 判位直接走收尾路径(step 70 去清洗位关气),
  不再循环。

## 4. 不变量核对(设计时已核)

- prep 是**绝对**回抽,活塞基线每循环自恢复,N>0 残留不跨循环累积。
- A20 清洗 entry[2] 打到 A0,把残留驱动液排掉;"清洗后活塞必在 0"不变量不受影响。
- aspirate 的 `当前位置 + n <= 6000` PLC 行程闸不受影响。
- 与条带边缘缺陷 spec(2026-07-14-band-edge-artifacts)正交:B 方案只改扫描方向编排,
  不碰终点判据。

## 5. 测试与验收

- 离线:translator 指令串测试(`A{N}R` 且 N=0 时与旧串逐字相等)、profiles 节点测试
  (`Sampling_band_end_position` 与指令串 N 同源)、knob 透传链测试、越界 ValueError。
- PLC:codesys MCP compile 0 errors;mode 判据 N=0 回归(逐字零变化预期)。
- 上机(pending):符号 XML 重导出**与 `Sampling_clean_mode` 同批**、固件下装;
  标定流程:knob 逐次试 N(从 0 上探),观察条带末端稀释消失且样品量不缺,定值写入
  config.pump。

## 6. 上机前置与风险

- ⚠️ 未下装本版固件前,host 侧若先发 N>5:PLC 旧判据等 `pos <= 5`,泵停在 N 收不了
  尾 → 空转程循环直到 **60 程保险报 ErrorCode 462**(每程含扫线+吹干,持续数分钟且
  白白吹扫条带)。落地顺序:PLC 固件先行或 host/PLC 同批上机;knob 缺省 0 保证未标定
  时行为不变。
