# 泵档默认值持久化配置 (config.pump) 设计

日期: 2026-07-14
状态: 设计定稿, 待实施
前置讨论: 本次会话 brainstorming, 6 项拟定答案 + 方案 A 已获用户认可

## 1. 背景与目标

注射泵动作的速度/延时档 (V/M) 目前默认值真源是 translator 模块常量
(`sample_translator.py:49-51` 250/100/1500 · `collect_translator.py:25-27` 500/500/1000 ·
`develop_translator.py:45-47` 100/100/500, 外加 sampling 的 `DEFAULT_DISPENSE_DISP_SPEED=50` /
`FLUSH_DISP_SPEED=300` / `FLUSH_SPOT_HEAD_DISP_SPEED=100`, 后三者定义在
`sample_translator_v2.py:86-92`)。改默认值须改代码, 现场不可调。

目标: 把这批默认值收编为 **app.yaml 的 `pump:` 持久配置段**, 上位机 UI 可编辑、即改即生效,
同时**完全保留**现有的 operation 运行前参数覆盖 (knob) 机制。

## 2. 需求定案 (6 项, 已确认)

1. **收编范围 = 只收速度/延时档**: 即 `PUMP_DEFAULT_HINTS` 现有全部键 ——
   sampling 6 个 (`asp_speed` / `disp_speed` / `spot_disp_speed` / `step_delay` /
   `flush_disp_speed` / `spot_head_disp_speed`)、collect 3 个、develop 3 个。
   其他工艺常量 (体积系数/气垫量等) 无对应 knob, 属配方语义, 不收。
   develop 排液时长已走 PLC L2 通道化, 不属本次范围。
   台架 CLI 工具 (`mvp_staged_clean.py` 等) 是独立脚本, 不接配置, 不改。
2. **粒度 = 按工位** (sampling / collect / develop), 与现常量结构一一对应;
   工位内动作差异已由不同键名表达 (点样打速 / 充液打速), 不引入每动作维度。
3. **生效时机 = live-read**: 派发动作时实时读 config.pump (与 vision 段同款模式),
   不进 AppConfig 启动快照, 改完对下一次派发即生效, 无需重启上位机。
4. **优先级链**: 运行前 knob 传值 > config.pump 持久值 > translator 常量 (最后兜底)。
   现有覆盖机制零改动。
5. **UI 入口**: `DeviceParamsPanel.vue` 段列表加 "泵档默认" 一项, 复用通用扁平编辑器;
   动作页参数占位提示 (`default_hint`) 因 live-read 自动跟随持久值。
6. **校验**: 速度 1..500 (PLC 守卫上限), `step_delay` 0..60000 ms;
   **未知键拒绝** (防拼写错误静默回退常量); 非法值整段拒写 (沿用 ConfigService
   "校验不过不写盘")。允许缺键 (缺键回退常量)。

## 3. 方案选型 (已确认: 方案 A)

- **A (选定) — profiles.py 内置 provider, live-read**: bootstrap 注入
  `lambda: cfg_svc.read_section("pump")`, 缺省回退逻辑集中在 profiles.py 一个缝;
  dto / executor / knob 透传链全部不动。模块级可变状态与 vision live-read 先例一致。
- B (弃) — executor 派发前预填 values: 泵档知识泄漏到 executor, UI 提示还要另接线。
- C (弃) — 进 AppConfig 启动快照: 需重启生效, 违背"运行时可调"初衷。

## 4. 设计

### 4.1 配置段 (app.yaml)

新增 `pump:` 段, **初值抄现常量** (播种全部键, 否则 DeviceParamsPanel 的扁平编辑器
无字段可编辑), 注释写清单位与上限:

```yaml
# 泵档默认 (V/M 速度/延时): 优先级 = 运行前参数覆盖 > 本段 > translator 常量兜底
# 速度单位: 半步/s, 守卫上限 500; step_delay 单位 ms (0..60000)。改后对下一次派发即生效。
pump:
  sampling:
    asp_speed: 250            # 吸液速度
    disp_speed: 100           # 打液速度
    spot_disp_speed: 50       # 点样打液速度 (精度优先)
    step_delay: 1500          # 步骤间延迟 ms
    flush_disp_speed: 300     # 轻清洗充液/外壁打速 (偏高冲刷贴壁气泡)
    spot_head_disp_speed: 100 # 轻清洗点样头打速
  collect:
    asp_speed: 500
    disp_speed: 500
    step_delay: 1000
  develop:
    asp_speed: 100
    disp_speed: 100
    step_delay: 500
```

**真源语义变化**: 播种后 config.pump 成为运行默认的实际真源; translator 常量降级为
"config 缺键 / 读盘失败时的兜底安全值"。二者初值相同, 之后允许分叉 (用户改 config)。

### 4.2 校验器 (config/loader.py)

新增 `_parse_pump(d: dict)`, 照 `_parse_vision` 模式:

- 顶层键只允许 `sampling` / `collect` / `develop`, 各值须为映射; 未知键 → ValueError。
- 每工位键只允许该工位的合法参数名集合 (sampling 6 键 / collect 3 键 / develop 3 键);
  未知键 → ValueError (防拼写错误静默回退常量)。
- 值须可转 int: 速度类 1..500, `step_delay` 0..60000; 越界 → ValueError。
- 允许缺键/缺工位 (回退常量), 空段合法。
- 不定义新 dataclass, 返回规范化后的纯 dict (`{station: {key: int}}`) —— pump 不进
  AppConfig, 校验器只服务 ConfigService 写前校验与 profiles 读后清洗。

### 4.3 ConfigService (controller/config_service.py)

- `SECTIONS = ("camera", "gcode", "vision", "pump")`
- `_validate` 加 `elif section == "pump": _parse_pump(merged)` 分支。
- 读写路径复用现有 ruamel round-trip, 注释保留, 无 operation 编辑器那个剥注释坑。

### 4.4 provider 缝 + 回退改造 (tools/pump/profiles.py) —— 核心改动

```python
# 模块级 provider (bootstrap 注入; 未注入/读失败 → 回退 translator 常量)
_pump_defaults_provider: Callable[[], dict] | None = None

def set_pump_defaults_provider(provider: Callable[[], dict] | None) -> None: ...

def _config_default(station: str, key: str) -> int | None:
    """读 config.pump 某键; provider 未注入/抛异常/缺键 → None。
    provider 抛异常时 log.warning 并回退, 不得阻断派发。"""
```

**层间依赖约束**: profiles.py 不 import config.loader —— 清洗职责放进 bootstrap 注入的
provider 闭包 (`_parse_pump(read_section("pump"))`), provider 返回**已清洗**的
`{station: {key: int}}`; profiles 侧只做 dict 查找 + 对 provider 调用整体 try/except。

三处回退点全部接上 (回退次序: knob 传值 → `_config_default` → 常量):

1. `_speed_kwargs(values, mapping)` → 加 `station` 参数: `values.get(yaml_name)` 为 None 时
   查 `_config_default(station, yaml_name)`, 命中则纳入 kwargs; 仍无 → 不传 kwarg
   (由 translator 函数签名常量兜底)。各 builder 调用点补 station 实参。
   保持对每个声明键都经 `values.get` 访问 —— `test_pump_contract_offline` 的记账契约不破。
2. `_build_sampling_spot` 手写回退 (现 profiles.py:141): `spot_disp_speed` 缺省 →
   `_config_default("sampling", "spot_disp_speed")` → `s2.DEFAULT_DISPENSE_DISP_SPEED`。
3. `_build_sampling_spot_band_layer` 手写回退 (现 profiles.py:160-161): `spot_disp_speed`
   与 `step_delay` 同上接三层链。

**UI 提示同源**: `PUMP_DEFAULT_HINTS` 静态 dict 保留、改名为常量兜底层
(如 `_PUMP_CONSTANT_HINTS`); `pump_default_hint(station, param)` 改为
`_config_default(station, param)` 命中则返回之, 否则查常量兜底表。
`api/dto.py` 与前端占位显示零改动, hint 自动跟随持久值。

### 4.5 bootstrap 注入 (runtime/bootstrap.py)

`app.state.config_svc = ConfigService(config_path)` (现 bootstrap.py:374) 之后一行:

```python
set_pump_defaults_provider(lambda: _parse_pump(app.state.config_svc.read_section("pump")))
```

`read_section` 每次调用读盘 → live-read。泵动作派发频率低, 开销可忽略。

### 4.6 前端 (web/src/components/DeviceParamsPanel.vue)

`SECTIONS` 列表加 `{ key: 'pump', label: '泵档默认 (吸/打速度/步延时)' }`。
面板是通用扁平化编辑器 + 整段 PUT, 零新代码。保存成功提示文案保持现状不动
("部分参数需重启上位机生效" 对 pump 段属保守表述, 不误导操作、不值得为此加按段分支)。

### 4.7 数据流小结

```
UI 编辑 pump 段 → PUT /api/config/pump → ConfigService.save_section
  → _parse_pump 校验 (不过 400 不写盘) → ruamel 写回 app.yaml (保注释)

动作派发 → executor 按 YAML params 校验强转 → PUMP_PROFILES[action].build(values)
  → 回退链: values 传值 → _config_default (live-read app.yaml) → translator 常量
  → 通道字典 → PlcController.execute

动作页打开 → dto 建参数列表 → pump_default_hint → 同一 _config_default → 占位提示
```

## 5. 错误处理

- 保存: 校验失败 → ValueError → HTTP 400, 不写盘 (现有机制)。
- 派发时读盘失败 (yaml 损坏/文件锁): `_config_default` 捕获异常, log.warning,
  返回 None → 回退常量, **不阻断派发**。
- config 值越界但已在盘上 (绕过 UI 手改 yaml): `_config_default` 读后经 `_parse_pump`
  同一套清洗; 清洗失败按读盘失败处理 (回退常量 + warning), 避免非法速度直达 PLC。
- provider 未注入 (离线测试/脚本直调 profiles): 一律回退常量, 行为与现状完全一致。

## 6. 测试

- **config/loader**: `_parse_pump` 用例 —— 合法段 / 空段 / 缺键 / 未知工位键拒绝 /
  未知参数键拒绝 / 速度越界 (0, 501) 拒绝 / step_delay 越界拒绝。
- **config_service** (`test_config_service_offline.py` 扩): pump 段读写往返 /
  非法值整段拒写不落盘 / 注释保留。
- **新增 `test_pump_defaults_config_offline.py`**: 三层优先级 —— knob 传值压过 config;
  config 压过常量; 缺键回退常量; provider 抛异常回退常量且不抛出;
  三处回退点 (_speed_kwargs / spot / spot_band_layer) 逐一覆盖;
  `pump_default_hint` 跟随 config live-read。
- **`test_action_dto_offline.py` 改写**: 断言从"hint == translator 常量"改为两层语义
  (provider 有值时显示 config 值, 无 provider 时回退常量)。
- **`test_pump_contract_offline.py` 不改须绿**: 声明↔消费记账路径 (`values.get` 访问)
  在 `_speed_kwargs` 改造后保持不变。
- 全离线套件回归绿。

## 7. 影响面与不改清单

改动 7 文件: `config/app.yaml` · `config/loader.py` · `controller/config_service.py` ·
`tools/pump/profiles.py` · `runtime/bootstrap.py` · `web/src/components/DeviceParamsPanel.vue` ·
测试若干。

**明确不改**: 动作 YAML 的 params 声明 (knob 声明集不变) · executor · `api/dto.py` ·
translator 模块 (常量与函数签名原样保留) · knob 透传链 · PLC 侧。

## 8. 上机验证项 (实施后)

1. UI 改 sampling `asp_speed` → 不重启, 派发 sampling.clean, 抓 PLC 写帧确认新速度生效。
2. 运行前 knob 覆盖同参数 → 覆盖值压过 config 值。
3. 动作页占位提示显示 config 当前值 (非常量、非 0)。
