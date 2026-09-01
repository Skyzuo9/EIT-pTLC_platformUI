# 点样活塞终点位置可配置(死体积补偿)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sampling.spot_band_layer` 的点样结束条件从"活塞到 0(容差 5 步)"改为"到用户指定终点 N(容差保留)",用于标定补偿上样吸液流路死体积。

**Architecture:** host 三层:translator 生成 `A{N}R` 指令 + 换算助手(单一真源);profiles builder 消费新 knob `spot_end_position_ml` 并同源产出新节点 `Sampling_band_end_position`;PLC A62 判终 `pos <= 5` → `pos <= Sampling_band_end_position + 5`。knob 缺省 0 = 全链路逐字旧行为。

**Tech Stack:** Python 3(pytest/unittest 离线套件)、CODESYS ST(经 codesys MCP)、OPC UA 节点表 YAML。

## Global Constraints

- Spec 真源:`docs/superpowers/specs/2026-07-14-spot-end-position-design.md`。
- 本机测试解释器:`E:/Anaconda/envs/platformupper/python.exe`(测试文件 docstring 一致)。
- `spot_end_position_ml` 合法域 `0.0 <= x <= 5.0`(mL),越界抛 ValueError / YAML min-max 拒绝;换算 25mL = 6000 步(`_ml_to_steps`)。
- **缺省 0 时全链路(指令串/节点值/PLC 分支)必须与现行为逐字等价**。
- `build_dispense_all_cmd` 的既有调用方(A20 清洗、A60 旧点样、轻清洗数组)零 diff——新参数必须 keyword-only 且缺省 0。
- 契约测试 `test_pump_contract_offline.py` 要求 *YAML 声明参数集 == builder 消费集*:YAML 参数、builder 消费、节点注册必须同一提交。
- PLC 侧遵循兄弟风格:GVL 无 pragma、整组符号导出;不动 A62 其它步;compile 0 errors。
- ⚠️ 上机顺序:PLC 固件先行或与 host 同批;旧固件下 host 发 N>5 会空转到 60 程保险报 462。
- config.pump 三层链的 config 层依赖未合回的 `feat/pump-defaults-config` 分支:本计划只落 knob > 常量 0.0,在 builder 留一行 hook 注释。
- 提交信息结尾:`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

---

### Task 1: translator — 换算助手 + `A{N}` 指令支持

**Files:**
- Modify: `eit_ptlc/tools/pump/sample_translator.py:123-131`(`build_dispense_all_cmd`)
- Modify: `eit_ptlc/tools/pump/sample_translator_v2.py:509-527`(`build_spot_band_run_cmd`,新增 `spot_band_end_steps`)
- Test: `eit_ptlc/tests/test_spot_end_position_offline.py`(新建)

**Interfaces:**
- Consumes: `sample_translator._ml_to_steps(volume_ml, syringe_ml=25.0) -> int`(现有)。
- Produces:
  - `sample_translator.build_dispense_all_cmd(pump_addr="1", disp_speed=DISP_SPEED, step_delay=STEP_DELAY, output_port=OUTPUT_PORT, *, end_steps: int = 0) -> str`
  - `sample_translator_v2.spot_band_end_steps(end_position_ml: float) -> int`(校验 0..5.0 mL,越界 ValueError)
  - `sample_translator_v2.build_spot_band_run_cmd(*, pump_addr=..., disp_speed=..., step_delay=..., output_port=..., end_position_ml: float = 0.0) -> str`

- [ ] **Step 1: 写失败测试**

新建 `eit_ptlc/tests/test_spot_end_position_offline.py`:

```python
#!/usr/bin/env python3
"""点样活塞终点位置(死体积补偿)离线测试
=============================================
守护 spec 2026-07-14-spot-end-position:
    - 换算助手 spot_band_end_steps: mL->步 (25mL=6000步), 0..5mL 闭区间越界 ValueError;
    - build_dispense_all_cmd 新增 keyword-only end_steps, 缺省 0 时指令串与旧版逐字相等;
    - build_spot_band_run_cmd 新增 end_position_ml, 指令 A{N} 与 spot_band_end_steps 同源。

运行:
    & E:/Anaconda/envs/platformupper/python.exe -m pytest \
      eit_ptlc/tests/test_spot_end_position_offline.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eit_ptlc.tools.pump import sample_translator as s1
from eit_ptlc.tools.pump import sample_translator_v2 as s2


class TranslatorEndPositionTests(unittest.TestCase):
    def test_end_steps_conversion(self):
        self.assertEqual(s2.spot_band_end_steps(0.0), 0)
        self.assertEqual(s2.spot_band_end_steps(1.0), 240)   # 1mL × 6000/25
        self.assertEqual(s2.spot_band_end_steps(5.0), 1200)

    def test_end_steps_out_of_range(self):
        for bad in (-0.1, 5.01):
            with self.assertRaises(ValueError):
                s2.spot_band_end_steps(bad)

    def test_dispense_all_default_verbatim_unchanged(self):
        old = f"/4V50I{s1.OUTPUT_PORT}A0M{s1.STEP_DELAY}R\r"
        self.assertEqual(s1.build_dispense_all_cmd("4", 50), old)
        self.assertEqual(s1.build_dispense_all_cmd("4", 50, end_steps=0), old)

    def test_dispense_all_end_steps(self):
        cmd = s1.build_dispense_all_cmd("4", 50, end_steps=240)
        self.assertIn("A240M", cmd)
        self.assertNotIn("A0M", cmd)

    def test_spot_band_run_cmd_default_verbatim_unchanged(self):
        self.assertEqual(s2.build_spot_band_run_cmd(),
                         s2.build_spot_band_run_cmd(end_position_ml=0.0))
        self.assertIn("A0M", s2.build_spot_band_run_cmd())

    def test_spot_band_run_cmd_end_position(self):
        cmd = s2.build_spot_band_run_cmd(end_position_ml=1.0)
        self.assertIn(f"A{s2.spot_band_end_steps(1.0)}M", cmd)

    def test_spot_band_run_cmd_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            s2.build_spot_band_run_cmd(end_position_ml=5.5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_spot_end_position_offline.py -q`
Expected: FAIL/ERROR — `AttributeError: ... has no attribute 'spot_band_end_steps'` 及 `unexpected keyword argument 'end_steps'`。

- [ ] **Step 3: 实现 translator 改动**

`sample_translator.py` — `build_dispense_all_cmd` 改为:

```python
def build_dispense_all_cmd(
    pump_addr: str = "1",
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
    *,
    end_steps: int = 0,
) -> str:
    """构建全打液指令（打到绝对位 end_steps, 缺省 0=归零）。用于 Phase 4 点样。

    end_steps > 0 用于点样死体积补偿: 活塞停在 N 保留纯驱动液不点到板上
    (spec 2026-07-14-spot-end-position)。
    """
    return f"/{pump_addr}V{disp_speed}I{output_port}A{end_steps}M{step_delay}R\r"
```

`sample_translator_v2.py` — 在 `build_spot_band_run_cmd` 前新增助手,并给它加 `end_position_ml`:

```python
SPOT_END_POSITION_MAX_ML = 5.0  # 死体积补偿终点上限 (留足 prep 缺省 3mL 驱动液 + 余量)


def spot_band_end_steps(end_position_ml: float) -> int:
    """点样活塞终点 mL -> 步数(单一换算真源: 指令 A{N} 与 PLC 节点共用)。

    合法域 [0, SPOT_END_POSITION_MAX_ML] mL; 越界 ValueError (防误配大值一程不点)。
    """
    if not (0.0 <= end_position_ml <= SPOT_END_POSITION_MAX_ML):
        raise ValueError(
            f"点样活塞终点必须在 [0, {SPOT_END_POSITION_MAX_ML}] mL, 收到 {end_position_ml} mL")
    return _ml_to_steps(end_position_ml)


def build_spot_band_run_cmd(
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    disp_speed: int = DEFAULT_DISPENSE_DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
    end_position_ml: float = 0.0,
) -> str:
    """单条带点样供液指令: 从当前位置绝对打出到 A{N}(缺省 N=0)。

    该指令用于 PLC 条带级动作: PLC 发送有限 A{N}R 后, 以 Q 查询确认
    注射泵空闲, 再进入只吹气干燥段。%MW1300 只表示转发邮箱可用,
    不能表示 A{N} 物理动作完成。N>0 = 死体积补偿, PLC 判终同步用
    Sampling_band_end_position (spec 2026-07-14-spot-end-position)。
    """
    return build_dispense_all_cmd(
        pump_addr=pump_addr,
        disp_speed=disp_speed,
        step_delay=step_delay,
        output_port=output_port,
        end_steps=spot_band_end_steps(end_position_ml),
    )
```

(注意 `_ml_to_steps` 已在 v2 顶部 import,无需新增;`SPOT_END_POSITION_MAX_ML` 放常量区。)

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_spot_end_position_offline.py -q`
Expected: 7 passed。

- [ ] **Step 5: 回归既有调用方**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_pump_contract_offline.py eit_ptlc/tests/test_single_sample_demo_offline.py -q`
Expected: 全 pass(A20/A60/轻清洗指令串零变化)。

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/tools/pump/sample_translator.py eit_ptlc/tools/pump/sample_translator_v2.py eit_ptlc/tests/test_spot_end_position_offline.py
git commit -m "feat(pump): 点样终点 A{N} 指令支持 — spot_band_end_steps 换算真源 + build_dispense_all_cmd keyword-only end_steps (缺省0零diff)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: host 接线 — knob 声明 + builder 消费 + 节点注册(须同一提交,契约测试锁死)

**Files:**
- Modify: `eit_ptlc/config/actions/01_sampling/plc_sampling.yaml:111-122`(spot_band_layer params)
- Modify: `eit_ptlc/tools/pump/profiles.py:149-166`(`_build_sampling_spot_band_layer`)
- Modify: `eit_ptlc/config/plc_nodes.yaml:82` 后插一行
- Test: `eit_ptlc/tests/test_spot_end_position_offline.py`(追加测试类)

**Interfaces:**
- Consumes: Task 1 的 `s2.spot_band_end_steps(ml)` 与 `s2.build_spot_band_run_cmd(..., end_position_ml=...)`。
- Produces: builder 输出通道字典新增键 `"Sampling_band_end_position": int`(与指令串 A{N} 同源);action YAML 新 knob `spot_end_position_ml`(float, required:false, min 0.0, max 5.0)。

- [ ] **Step 1: 追加失败测试**

在 `test_spot_end_position_offline.py` 追加:

```python
from eit_ptlc.tools.pump.profiles import PUMP_PROFILES


class BandLayerBuilderTests(unittest.TestCase):
    _BASE = {"ref_spot": "spot_pose", "spot_disp_speed": None, "step_delay": None,
             "spot_speed_mm_s": 5.0, "dry_speed_mm_s": 20.0, "dry_cycles": 1}

    def _build(self, **extra):
        values = dict(self._BASE)
        values.update(extra)
        return PUMP_PROFILES["sampling.spot_band_layer"].build(values)

    def test_default_end_position_zero(self):
        ch = self._build(spot_end_position_ml=None)
        self.assertEqual(ch["Sampling_band_end_position"], 0)
        self.assertIn("A0M", ch["Sampling_band_run_instruction"])

    def test_end_position_same_source(self):
        ch = self._build(spot_end_position_ml=1.0)
        self.assertEqual(ch["Sampling_band_end_position"], 240)
        self.assertIn("A240M", ch["Sampling_band_run_instruction"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_spot_end_position_offline.py -q`
Expected: 新增 2 用例 FAIL(`KeyError: 'Sampling_band_end_position'`),旧 7 用例 PASS。

- [ ] **Step 3: 三处同批实现**

`profiles.py` `_build_sampling_spot_band_layer` 改为:

```python
def _build_sampling_spot_band_layer(values: dict) -> dict:
    """单条带点样+连续吹干: 生成泵供液指令与轴/吹扫参数。

    PLC 侧负责强同步: 先发有限 A{N}R, 6X 一程到位后在同一泵总线占位内
    发 T 停泵并以 ? 查询真活塞位；有效位置仍大于 N 才释放总线进入吹干，
    回起点后继续下一程，直到位置回到 N(+5 步容差)，再移动到清洗位关气。
    N = spot_end_position_ml (死体积补偿, 缺省 0 = 旧行为)。
    """
    spot = values.get("spot_disp_speed")
    delay = values.get("step_delay")
    end_raw = values.get("spot_end_position_ml")
    # hook: feat/pump-defaults-config 合回后, 此处 None 回退改接 config.pump 三层链
    end_ml = float(end_raw) if end_raw is not None else 0.0
    return {
        "Sampling_band_run_instruction": s2.build_spot_band_run_cmd(
            disp_speed=int(spot) if spot is not None else s2.DEFAULT_DISPENSE_DISP_SPEED,
            step_delay=int(delay) if delay is not None else s2.STEP_DELAY,
            end_position_ml=end_ml,
        ),
        "Sampling_band_end_position": s2.spot_band_end_steps(end_ml),
        "Sampling_band_spot_speed": float(values["spot_speed_mm_s"]),
        "Sampling_band_dry_speed": float(values["dry_speed_mm_s"]),
        "Sampling_band_dry_cycles": int(values["dry_cycles"]),
    }
```

`plc_sampling.yaml` 在 `step_delay` 参数行(第 122 行)后追加:

```yaml
    - {name: spot_end_position_ml, type: float, required: false, min: 0.0, max: 5.0, label: 点样活塞终点位置 (mL, 死体积补偿, 缺省=0)}
```

`plc_nodes.yaml` 在 `Sampling_band_dry_cycles` 行(第 82 行)后追加:

```yaml
  Sampling_band_end_position: {type: Int16, comment: "单条带点样: 活塞终点目标步数(死体积补偿); 0=打到底(旧行为); 判终 pos<=N+5"}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_spot_end_position_offline.py eit_ptlc/tests/test_pump_contract_offline.py -q`
Expected: 全 pass(契约测试确认 YAML 声明集 == builder 消费集)。

- [ ] **Step 5: 全离线套件回归**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests -q`
Expected: 全绿(含 test_action_executor_offline / test_sampling_four_stage_offline;新节点经 load_plc_nodes 自动进 mock server,不需要改 mock)。

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/tools/pump/profiles.py eit_ptlc/config/actions/01_sampling/plc_sampling.yaml eit_ptlc/config/plc_nodes.yaml eit_ptlc/tests/test_spot_end_position_offline.py
git commit -m "feat(sampling): spot_end_position_ml knob 全链接线 — builder同源产出 A{N}指令+Sampling_band_end_position 节点 (缺省0零diff)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: PLC 侧 — GVL 变量 + A62 判终改判(codesys MCP)

> **⚠️ 已被吸收(2026-07-14)**:本任务并入 `docs/superpowers/plans/2026-07-14-band-edge-eb.md`
> 的单一 A62 改动集(E+B 蛇形重构后 step 26 不复存在,阈值 `N+5` 写进新判终等待步 38;
> GVL 变量新增仍按本任务 Step 2 执行)。执行该计划时勾选本任务;不要按下方旧步骤单独改 step 26。

**Files:**
- Modify(CODESYS 工程 20260702.project,经 codesys MCP):GVL(含 `Sampling_band_*` 组的全局变量列表)、A62 单条带点样 POU(`Application/50_action/Sampling_L2` 下)。

**Interfaces:**
- Consumes: host 写入的 `Sampling_band_end_position`(INT 步数,每次派发 builder 无条件重写,无陈旧风险)。
- Produces: A62 判终 `spot_band_pos <= Sampling_band_end_position + 5`;符号面新增 `Sampling_band_end_position`(待上机重导出符号 XML,与 `Sampling_clean_mode` 同批)。

前置:CODESYS 打开 20260702.project 且 codesys MCP 可用(先 `codesys_status` 确认;上机换手前先杀旧版 codesys-mcp Node 进程)。

- [ ] **Step 1: 定位 POU 与 GVL**

用 `codesys_list_pous` 找到:(a) 声明 `Sampling_band_run_instruction` 等的 GVL;(b) A62 单条带点样步链 POU(特征:`spot_band_step` CASE、注释含"A62 单条带点样 — 模型B ②")。`codesys_read_pou` 读出全文确认基线与 spec §1 一致(判终 `spot_band_pos <= 5` 在 step 26)。

- [ ] **Step 2: GVL 增加变量**

在 `Sampling_band_dry_cycles` 声明行后(兄弟风格,无 pragma)追加:

```iecst
Sampling_band_end_position: INT;   (* 单条带点样: 活塞终点目标步数(死体积补偿); 0=打到底; 判终 pos<=N+5 *)
```

- [ ] **Step 3: A62 step 26 判终改判**

唯一改动行——把:

```iecst
IF spot_band_pos <= 5 THEN
```

改为:

```iecst
IF spot_band_pos <= Sampling_band_end_position + 5 THEN
```

其余(465 重试、462 保险、泵站位符释放时机)逐字不动。

- [ ] **Step 4: 编译并保存**

`codesys_compile` → Expected: 0 errors(警告基线不新增);`codesys_save`。

- [ ] **Step 5: diff 自检**

`codesys_read_pou` 重读 A62,确认与基线 diff 仅上述一行 + GVL 一行;host 写 0 时 `pos <= 0 + 5` 与旧 `pos <= 5` 逐字等价。

- [ ] **Step 6: 记录工作日志并提交仓内痕迹**

在 `docs/superpowers/plans/2026-07-14-spot-end-position.md` 勾选本任务,并:

```bash
git add docs/superpowers/plans/2026-07-14-spot-end-position.md
git commit -m "feat(plc): A62 判终 pos<=Sampling_band_end_position+5 — GVL新增变量, host写0逐字等价旧判据 (compile 0 errors)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 收尾验证与上机清单

**Files:**
- Modify: `docs/superpowers/specs/2026-07-14-spot-end-position-design.md`(状态戳)

- [ ] **Step 1: 全套件终验**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests -q`
Expected: 全绿。

- [ ] **Step 2: spec 落状态戳**

spec 头部状态行更新为已实施 + 提交号区间 + 上机 pending 清单:
1. 符号 XML 重导出(与 `Sampling_clean_mode` 同批);
2. 固件下装(⚠️ 未下装前 host 禁发 N>5,否则 60 程保险 462);
3. 标定流程:knob `spot_end_position_ml` 从 0 上探,板面确认末端稀释消失且样品量不缺,定值(后续进 config.pump)。

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-07-14-spot-end-position-design.md
git commit -m "docs(sampling): spot-end-position spec 落实施状态戳 + 上机3项清单

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
