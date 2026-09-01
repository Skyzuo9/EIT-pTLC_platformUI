# 上样轻清洗充液 SP-A (host 侧) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `sampling.flush` 轻清洗充液动作——translator 生成 2 条 DT 指令复用 `Sampling_clean_instructions ARRAY[1..2]` 通道,配合唯一新变量 `Sampling_clean_mode` 派发到 PLC(mode=1),离线全绿。

**Architecture:** 语义参数唯一真源 = 动作 YAML params;`profiles.py` 只持 builder(语义 dict → PLC 通道 dict);指令文本由 `sample_translator_v2.build_flush_array` 生成。flush 与 clean 共用 action_code 20 与 clean 通道,靠 `Sampling_clean_mode` 区分(clean=0/flush=1,**两个 builder 每次派发都显式写,防陈旧**)。

**Tech Stack:** Python 3(`E:/Anaconda/envs/platformupper/python.exe`),unittest/pytest,asyncua mock OPC UA。

## Global Constraints(逐字来自 spec `docs/superpowers/specs/2026-07-14-sampling-light-flush-design.md`)

- entry[1](链式三合一,全程三通=上样位):`/{addr}V{asp}I1A{total_steps}M{delay}V{flush_spd}I3A{p1}M{delay}V{flush_spd}I2A{p2}M{delay}R`,其中 `total_steps = steps(v1)+steps(v2)+steps(v3)`(逐段取整后相加,守恒),`p1 = total_steps − steps(v1)`,`p2 = p1 − steps(v2)`。
- entry[2]:`/{addr}V{spot_spd}I3A0M{delay}R`(终态不变量:活塞必回 A0,体积恒等于 v3)。
- 默认参数:v1/v2/v3 = 17/5/3 mL,asp_speed 250,充液打速 300,点样头打速 100,delay = STEP_DELAY(1500 ms);校验三段体积各 > 0 且总步数 ≤ 6000,打速 ≤ 500。
- `Sampling_clean_mode : INT`(0=重清洗现行,1=轻清洗充液);host 每次派发显式写,不依赖 PLC 复位。
- `Sampling_clean_count`:flush 恒写 1。
- mode=0(重清洗)行为逐位不变。
- 速度/延时可选覆写参数不在 YAML 里复制数值默认(缺省=translator 模块常量兜底,与既有 asp_speed 模式一致)。
- 提交信息结尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`;不推送。
- **范围外(刻意不做)**:operation 编排换血(每次点样前 clean→flush)延后到上机验证 flush 后单独做——它依赖物理前置条件(上样针在废液/清洗位、点样头在清洗位)的编排设计,spec §5 记录了意图。

---

### Task 1: translator `build_flush_array`(2 条指令,步数守恒 + A0 不变量)

**Files:**
- Modify: `eit_ptlc/tools/pump/sample_translator_v2.py`(常量区 ~line 86 之后;函数加在 `build_clean_array` 之后)
- Test: `eit_ptlc/tests/test_pump_contract_offline.py`(`PumpTranslationTests` 类内追加)

**Interfaces:**
- Consumes: `sample_translator.py` 既有 `_ml_to_steps / SYRINGE_STEPS / SYRINGE_ML / ASP_SPEED / STEP_DELAY / WASH_PORT / WASTE_PORT / OUTPUT_PORT / DEFAULT_PUMP_ADDR`(v2 已导入)。
- Produces: `build_flush_array(flush_volume_ml=17.0, outer_wash_volume_ml=5.0, spot_head_volume_ml=3.0, *, pump_addr, asp_speed, flush_disp_speed, spot_head_disp_speed, step_delay, wash_port, waste_port, output_port) -> list[str]`(恒 2 元素,均非空);模块常量 `DEFAULT_FLUSH_ML=17.0, DEFAULT_OUTER_WASH_ML=5.0, DEFAULT_SPOT_HEAD_ML=3.0, FLUSH_DISP_SPEED=300, FLUSH_SPOT_HEAD_DISP_SPEED=100`(Task 2 的 hints 引用)。

- [ ] **Step 1: 写失败测试**(`PumpTranslationTests` 内追加,风格对齐既有精确字符串断言)

```python
    # ---- 轻清洗充液 build_flush_array (spec 2026-07-14-sampling-light-flush §3.2) ----
    def test_flush_array_defaults_matches_spec(self) -> None:
        commands = s2.build_flush_array(17.0, 5.0, 3.0)
        self.assertEqual(commands, [
            "/4V250I1A6000M1500V300I3A1920M1500V300I2A720M1500R\r",
            "/4V100I3A0M1500R\r",
        ])

    def test_flush_array_step_conservation_and_a0_invariant(self) -> None:
        # s1=2400 s2=480 s3=360 -> total=3240, p1=840, p2=360; entry2 恒打到 A0
        commands = s2.build_flush_array(
            10.0, 2.0, 1.5,
            asp_speed=200, flush_disp_speed=400, spot_head_disp_speed=80, step_delay=500,
        )
        self.assertEqual(commands, [
            "/4V200I1A3240M500V400I3A840M500V400I2A360M500R\r",
            "/4V80I3A0M500R\r",
        ])

    def test_flush_array_rejects_over_capacity(self) -> None:
        with self.assertRaises(ValueError):
            s2.build_flush_array(18.0, 5.0, 3.0)   # 26 mL > 25 mL

    def test_flush_array_rejects_nonpositive_stage(self) -> None:
        with self.assertRaises(ValueError):
            s2.build_flush_array(17.0, 0.0, 3.0)

    def test_flush_array_rejects_disp_speed_over_500(self) -> None:
        with self.assertRaises(ValueError):
            s2.build_flush_array(17.0, 5.0, 3.0, flush_disp_speed=501)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_pump_contract_offline.py::PumpTranslationTests -v`
Expected: 5 个新用例 FAIL/ERROR(`AttributeError: ... has no attribute 'build_flush_array'`),既有用例 PASS。

- [ ] **Step 3: 实现**(`sample_translator_v2.py`)

常量区(`DEFAULT_DISPENSE_DISP_SPEED = 50` 行之后)追加:

```python
DEFAULT_FLUSH_ML = 17.0            # 轻清洗: 上样流路充液体积 (泵→三通15.7 + 针流路1.125 ≈ 16.8mL 的 1.01×)
DEFAULT_OUTER_WASH_ML = 5.0        # 轻清洗: 针外壁清洗体积 (外壁流路 2-4mL)
DEFAULT_SPOT_HEAD_ML = 3.0         # 轻清洗: 点样头清洗体积
FLUSH_DISP_SPEED = 300             # 轻清洗充液/外壁打速 (偏高冲刷贴壁气泡; 守卫上限 500)
FLUSH_SPOT_HEAD_DISP_SPEED = 100   # 轻清洗点样头打速
```

`build_clean_array` 之后追加:

```python
def build_flush_array(
    flush_volume_ml: float = DEFAULT_FLUSH_ML,
    outer_wash_volume_ml: float = DEFAULT_OUTER_WASH_ML,
    spot_head_volume_ml: float = DEFAULT_SPOT_HEAD_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    flush_disp_speed: int = FLUSH_DISP_SPEED,
    spot_head_disp_speed: int = FLUSH_SPOT_HEAD_DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    waste_port: int = WASTE_PORT,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """轻清洗充液数组 [吸满+充上样流路+冲外壁(链式), 冲点样头至A0](clean mode=1 消费)。

    [1] 链式三合一: 自清洗口吸满(=三段之和) → 充液上样流路(高速冲刷贴壁气泡)
        → 冲针外壁(废液口)。三步间无外部阀动作, 全程三通=上样位, 原子执行。
    [2] 冲点样头: 打到 A0。派发本条前 PLC 须已切三通→点样位(Q 确认空闲后)。
    终态不变量: 活塞必回 A0; entry[2] 体积恒等于 spot_head_volume_ml(逐段取整守恒)。
    契约: docs/superpowers/specs/2026-07-14-sampling-light-flush-design.md §3.2
    """
    for label, v in (("上样流路充液", flush_volume_ml),
                     ("针外壁清洗", outer_wash_volume_ml),
                     ("点样头清洗", spot_head_volume_ml)):
        if v <= 0:
            raise ValueError(f"{label}体积必须 > 0，收到 {v} mL")
    for label, v in (("充液/外壁打液速度", flush_disp_speed),
                     ("点样头打液速度", spot_head_disp_speed)):
        if v > 500:
            raise ValueError(f"{label}不能超过 500，收到 {v}")

    n_flush = _ml_to_steps(flush_volume_ml)
    n_outer = _ml_to_steps(outer_wash_volume_ml)
    n_spot = _ml_to_steps(spot_head_volume_ml)
    total = n_flush + n_outer + n_spot
    if total > SYRINGE_STEPS:
        raise ValueError(
            f"三段体积之和 {flush_volume_ml + outer_wash_volume_ml + spot_head_volume_ml:.1f} mL"
            f" 超出注射泵量程 {SYRINGE_ML} mL"
        )
    p1 = total - n_flush
    p2 = p1 - n_outer
    chained = (
        f"/{pump_addr}V{asp_speed}I{wash_port}A{total}M{step_delay}"
        f"V{flush_disp_speed}I{output_port}A{p1}M{step_delay}"
        f"V{flush_disp_speed}I{waste_port}A{p2}M{step_delay}"
        f"R\r"
    )
    spot_head = f"/{pump_addr}V{spot_head_disp_speed}I{output_port}A0M{step_delay}R\r"
    return [chained, spot_head]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_pump_contract_offline.py::PumpTranslationTests -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/tools/pump/sample_translator_v2.py eit_ptlc/tests/test_pump_contract_offline.py
git commit -m "feat(pump): 轻清洗充液 build_flush_array — 吸满+充上样流路+冲外壁链式 / 点样头A0 两条指令

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: 通道声明 + 动作 YAML + profiles builder(mode 防陈旧契约)

**Files:**
- Modify: `eit_ptlc/config/plc_nodes.yaml:63-64`(clean 通道块)
- Modify: `eit_ptlc/config/actions/01_sampling/plc_sampling.yaml`(`sampling.clean` 块之后插入)
- Modify: `eit_ptlc/tools/pump/profiles.py`(`_build_sampling_clean` 加 mode;新增 `_build_sampling_flush`;`PUMP_PROFILES` 与 `PUMP_DEFAULT_HINTS` 登记)
- Test: `eit_ptlc/tests/test_pump_contract_offline.py`(`PumpTranslationTests` 追加 mode 契约用例;`PumpContractTests` 既有记账自动覆盖 flush)

**Interfaces:**
- Consumes: Task 1 的 `s2.build_flush_array` 与常量 `FLUSH_DISP_SPEED / FLUSH_SPOT_HEAD_DISP_SPEED`。
- Produces: `PUMP_PROFILES["sampling.flush"]`(build(语义dict) → `{"Sampling_clean_instructions": list[str]×2, "Sampling_clean_count": 1, "Sampling_clean_mode": 1}`);`PUMP_PROFILES["sampling.clean"]` 输出新增 `"Sampling_clean_mode": 0`;节点 `Sampling_clean_mode: Int16`(Task 3 的 mock 服务器据此建变量)。

- [ ] **Step 1: 写失败测试**(`PumpTranslationTests` 内追加)

```python
    def test_clean_and_flush_write_mode_every_dispatch(self) -> None:
        """防陈旧契约: clean/flush 每次派发都显式写 Sampling_clean_mode (spec §3.1)。"""
        from eit_ptlc.tools.pump.profiles import PUMP_PROFILES
        clean = PUMP_PROFILES["sampling.clean"].build(
            {"wash_volume_ml": 25.0, "cleaning_count": 3})
        self.assertEqual(clean["Sampling_clean_mode"], 0)
        flush = PUMP_PROFILES["sampling.flush"].build(
            {"flush_volume_ml": 17.0, "outer_wash_volume_ml": 5.0, "spot_head_volume_ml": 3.0})
        self.assertEqual(flush["Sampling_clean_mode"], 1)
        self.assertEqual(flush["Sampling_clean_count"], 1)
        self.assertEqual(flush["Sampling_clean_instructions"],
                         s2.build_flush_array(17.0, 5.0, 3.0))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_pump_contract_offline.py -v`
Expected: 新用例 FAIL(`KeyError: 'sampling.flush'`);同时注意 `PumpContractTests` 此刻仍 PASS(flush 尚未进 YAML)。

- [ ] **Step 3: 实现**

3a. `plc_nodes.yaml`:把 line 63 的 clean 注释更新并在 `Sampling_clean_count` 后加 mode(数组语义随 mode 多态,注释写明):

```yaml
  Sampling_clean_instructions: {type: String, array_len: 2, comment: "清洗 mode=0:[内壁,外壁]×count / mode=1:[吸+充上样流路+冲外壁链式, 冲点样头A0] (Step 10)"}
  Sampling_clean_count: {type: Int16}
  Sampling_clean_mode: {type: Int16, comment: "清洗模式: 0=重清洗(现行) 1=轻清洗充液(PLC在entry边界Q空闲后切三通→点样, 结束复位→上样)"}
```

3b. `plc_sampling.yaml`:`sampling.clean` 块之后插入(action_code 与 clean 同为 20,靠 mode 区分):

```yaml
# 轻清洗充液: 与 sampling.clean 共用动作码20与 clean 通道, 由 Sampling_clean_mode=1 区分。
# 一次吸满(=三段之和): entry1 链式[吸+充上样流路+冲外壁], entry2 单独[冲点样头至A0];
# PLC 在 entry 边界(Q确认泵空闲后)切三通→点样, 结束复位→上样。
# 物理前置(编排层保证): 上样针在废液/清洗位(17mL从针尖排出), 点样头在其清洗位(3mL从点样头排出)。
sampling.flush:
  kind: plc_l2
  station: sampling
  action_code: 20
  label: 上样-轻清洗充液
  desc: 一次抽液分段清洗——充液上样流路+冲针外壁+冲点样头, 消除管内空气顺应性(点样后驱动空气占管的治本清洗)
  modes: []
  params:
    - {name: flush_volume_ml, type: float, required: false, default: 17.0, min: 0.1, max: 25.0, label: 上样流路充液体积 (mL)}
    - {name: outer_wash_volume_ml, type: float, required: false, default: 5.0, min: 0.1, max: 25.0, label: 针外壁清洗体积 (mL)}
    - {name: spot_head_volume_ml, type: float, required: false, default: 3.0, min: 0.1, max: 25.0, label: 点样头清洗体积 (mL)}
    - {name: asp_speed, type: int, required: false, min: 1, max: 500, label: 吸液速度 V (DT, 缺省=泵档)}
    - {name: flush_disp_speed, type: int, required: false, min: 1, max: 500, label: 充液/外壁打速 V (DT, 缺省=300)}
    - {name: spot_head_disp_speed, type: int, required: false, min: 1, max: 500, label: 点样头打速 V (DT, 缺省=100)}
    - {name: step_delay, type: int, required: false, min: 0, max: 10000, label: 步间延时 M (ms, 缺省=泵档)}
```

3c. `profiles.py`:

`_build_sampling_clean` 的返回 dict 追加一行(其余不动):

```python
        "Sampling_clean_count": int(values["cleaning_count"]),
        "Sampling_clean_mode": 0,  # 防陈旧: 与 flush 共用通道, 每次派发显式写 (spec §3.1)
```

`_build_sampling_clean` 之后新增(映射表与 builder):

```python
# 轻清洗充液的 V/M 覆写映射 (充液/外壁与点样头两档打速独立)
_FLUSH_SPEED_KWARGS = {
    "asp_speed": "asp_speed",
    "flush_disp_speed": "flush_disp_speed",
    "spot_head_disp_speed": "spot_head_disp_speed",
    "step_delay": "step_delay",
}


def _build_sampling_flush(values: dict) -> dict:
    """轻清洗充液: 复用 clean 通道 (action_code 20), mode=1 + count=1。

    entry1 链式[吸满+充上样流路+冲外壁] / entry2 [冲点样头至A0];
    PLC 在 entry 边界切三通。契约: specs/2026-07-14-sampling-light-flush §3。
    """
    return {
        "Sampling_clean_instructions": s2.build_flush_array(
            float(values["flush_volume_ml"]),
            float(values["outer_wash_volume_ml"]),
            float(values["spot_head_volume_ml"]),
            **_speed_kwargs(values, _FLUSH_SPEED_KWARGS),
        ),
        "Sampling_clean_count": 1,
        "Sampling_clean_mode": 1,
    }
```

`PUMP_PROFILES` 表 `"sampling.clean"` 行后登记:

```python
    "sampling.flush": PumpProfile(_build_sampling_flush),
```

`PUMP_DEFAULT_HINTS["sampling"]` 追加两键(引用常量不键入数字):

```python
    "sampling": {"asp_speed": s2.ASP_SPEED, "disp_speed": s2.DISP_SPEED,
                 "spot_disp_speed": s2.DEFAULT_DISPENSE_DISP_SPEED, "step_delay": s2.STEP_DELAY,
                 "flush_disp_speed": s2.FLUSH_DISP_SPEED,
                 "spot_head_disp_speed": s2.FLUSH_SPOT_HEAD_DISP_SPEED},
```

- [ ] **Step 4: 跑测试确认通过(含契约记账)**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_pump_contract_offline.py -v`
Expected: 全部 PASS。重点看 `PumpContractTests::test_declared_params_equal_builder_consumed` 的 `sampling.flush` subTest——YAML 7 参数与 builder 消费集必须相等(它同时验证 registry 接受与 clean 同码的第二个动作;若 registry 对 action_code 有唯一性断言在此暴露,处理方式=报告用户,勿自行绕过)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/config/plc_nodes.yaml eit_ptlc/config/actions/01_sampling/plc_sampling.yaml eit_ptlc/tools/pump/profiles.py eit_ptlc/tests/test_pump_contract_offline.py
git commit -m "feat(sampling): sampling.flush 轻清洗充液动作 — 复用clean通道+Sampling_clean_mode防陈旧契约

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 离线验收(mock OPC UA 全链路 + mode 防陈旧行为验证)

**Files:**
- Modify: `eit_ptlc/tests/test_plc_l2_acceptance_offline.py`(上样清洗块之后插入,~line 79)

**Interfaces:**
- Consumes: Task 2 的 `PUMP_PROFILES["sampling.flush"]` 与节点 `Sampling_clean_mode`(mock 服务器按 plc_nodes.yaml 自动建变量);既有 `ctrl.execute / mock_read / _is_nonempty_str_array / check`。
- Produces: 无(终端验收)。

- [ ] **Step 1: 写验收块**(插在 `sampling_clean_count` 那组 check 之后、prep 块之前)

```python
            # ── 上样轻清洗充液 (动作码 20, mode=1): 复用 clean 通道 ──
            flush = PUMP_PROFILES["sampling.flush"].build(
                {"flush_volume_ml": 17.0, "outer_wash_volume_ml": 5.0,
                 "spot_head_volume_ml": 3.0},
            )
            r = await ctrl.execute("sampling", 20, flush)
            check("sampling_flush_done", r.state is PLCActionState.DONE, str(r))
            check(
                "sampling_flush_instructions",
                _is_nonempty_str_array(await mock_read(server, "Sampling_clean_instructions"), 2),
                str(await mock_read(server, "Sampling_clean_instructions")),
            )
            check(
                "sampling_flush_count",
                int(await mock_read(server, "Sampling_clean_count")) == 1,
                str(await mock_read(server, "Sampling_clean_count")),
            )
            check(
                "sampling_flush_mode",
                int(await mock_read(server, "Sampling_clean_mode")) == 1,
                str(await mock_read(server, "Sampling_clean_mode")),
            )
            # 防陈旧: 重清洗再派发, mode 必须被显式打回 0
            clean_again = PUMP_PROFILES["sampling.clean"].build(
                {"wash_volume_ml": 25.0, "cleaning_count": 3},
            )
            r = await ctrl.execute("sampling", 20, clean_again)
            check("sampling_clean_again_done", r.state is PLCActionState.DONE, str(r))
            check(
                "sampling_clean_mode_reset",
                int(await mock_read(server, "Sampling_clean_mode")) == 0,
                str(await mock_read(server, "Sampling_clean_mode")),
            )
```

- [ ] **Step 2: 跑验收确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_plc_l2_acceptance_offline`
Expected: 输出含 `PASS sampling_flush_done / PASS sampling_flush_instructions / PASS sampling_flush_count / PASS sampling_flush_mode / PASS sampling_clean_mode_reset`,退出码 0,无 FAIL。

- [ ] **Step 3: Commit**

```bash
git add eit_ptlc/tests/test_plc_l2_acceptance_offline.py
git commit -m "test(sampling): flush 离线验收 — 通道写入/count=1/mode=1 + 重清洗回派 mode 打回 0

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 全量离线回归

**Files:** 无新改动(纯验证;若回归失败,修复属于对应 Task 的返工)。

- [ ] **Step 1: 跑全量离线套件**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests -q`
Expected: 全绿(基线约 446+,新增用例后总数只增不减);特别确认 `test_sampling_four_stage_offline.py`(prep/aspirate/spot 链路)与 `test_photoscrape_gate_flow_offline.py` 未受 plc_nodes/actions YAML 变更影响。

- [ ] **Step 2: 跑既有 acceptance 模块入口(双入口都要绿)**

Run: `E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.tests.test_plc_l2_acceptance_offline`
Expected: 退出码 0。

- [ ] **Step 3: 汇报**

向用户汇报:SP-A 离线全绿;`sampling.flush` 可在 UI 调试坞单发(上机验证入口);operation 编排换血与上机联调依赖 SP-B(PLC)落地。
