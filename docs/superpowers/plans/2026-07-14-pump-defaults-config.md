# 泵档默认值持久化配置 (config.pump) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把注射泵速度/延时档默认值从 translator 模块常量收编为 app.yaml `pump:` 持久段, UI 可编辑、live-read 即改即生效, 运行前 knob 覆盖机制零改动。

**Architecture:** ConfigService 加 `pump` 段 (loader 新增 `_parse_pump` 校验器); profiles.py 加模块级 provider 缝, bootstrap 注入 `_parse_pump(read_section("pump"))` 闭包; 三处缺省回退点改为三层链: knob 传值 > config.pump > translator 常量。spec: `docs/superpowers/specs/2026-07-14-pump-defaults-config-design.md`。

**Tech Stack:** Python (FastAPI 上位机) / ruamel.yaml round-trip / Vue3 前端 / pytest 离线套件。

## Global Constraints

- 优先级链固定: 运行前 knob 传值 > config.pump 持久值 > translator 常量 (最后兜底)。
- 速度类键校验范围 1..500 (PLC 守卫上限); `step_delay` 范围 0..60000 (ms)。
- pump 段**未知键必须拒绝** (防拼写错误静默回退常量); 缺键/缺工位/空段合法 (回退常量)。
- `profiles.py` **不得 import** `eit_ptlc.config.loader` (清洗职责在 bootstrap 注入的 provider 闭包里)。
- provider 未注入 / 读盘失败 / 清洗失败 → 回退 translator 常量并 log.warning, **不得阻断派发**。
- `test_pump_contract_offline.py` **一行不改且必须保持绿** (声明↔消费记账契约)。
- translator 模块 (sample_translator*.py / collect_translator.py / develop_translator.py) 常量与函数签名**原样保留**。
- ConfigService 写盘走现有 ruamel round-trip, YAML 注释必须保留。
- 测试解释器: `E:/Anaconda/envs/platformupper/python.exe` (bash 里直接以该路径调用)。
- 注释/文案风格: 中文为主体、技术术语保留英文, 与各文件现有风格一致。
- 每个 Task 完成即 commit; commit message 末尾带 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `eit_ptlc/config/loader.py` | Modify | 新增 `_parse_pump` 校验器 + `PUMP_STATION_KEYS` 常量 (校验/清洗唯一实现) |
| `eit_ptlc/tests/test_pump_defaults_config_offline.py` | Create | `_parse_pump` 用例 + profiles provider 三层回退用例 |
| `eit_ptlc/controller/config_service.py` | Modify | `SECTIONS` 加 `"pump"` + `_validate` 分支 |
| `eit_ptlc/tests/test_config_service_offline.py` | Modify | fixture 加 pump 段 + 读写/拒写/注释保留用例 |
| `eit_ptlc/tools/pump/profiles.py` | Modify | provider 缝 + `_speed_kwargs` 加 station 三层回退 + 两处手写回退接链 + hint 改 provider-backed |
| `eit_ptlc/tests/test_action_dto_offline.py` | Modify | 补 "hint 跟随 config" 用例 + 语义说明更新 |
| `eit_ptlc/config/app.yaml` | Modify | 文件末尾追加 `pump:` 段 (初值抄现常量, 播种全部键) |
| `eit_ptlc/runtime/bootstrap.py` | Modify | `ConfigService(config_path)` 之后注入 provider |
| `eit_ptlc/web/src/components/DeviceParamsPanel.vue` | Modify | `SECTIONS` 列表加 pump 一项 |

---

### Task 1: `_parse_pump` 校验器 (config/loader.py)

**Files:**
- Modify: `eit_ptlc/config/loader.py` (在 `_parse_vision` 定义之后、`_parse_pallas_vision` 之前插入)
- Test: `eit_ptlc/tests/test_pump_defaults_config_offline.py` (新建)

**Interfaces:**
- Consumes: 无 (纯函数, 不依赖其他 Task)
- Produces: `_parse_pump(d: dict | None) -> dict` — 输入 app.yaml pump 段原始 dict, 返回已清洗的 `{station: {key: int}}`; 非法输入抛 `ValueError`。模块常量 `PUMP_STATION_KEYS: dict[str, tuple[str, ...]]`、`PUMP_SPEED_MAX = 500`、`PUMP_STEP_DELAY_MAX = 60000`。Task 2 的 `_validate` 与 Task 4 的 bootstrap 闭包都调用 `_parse_pump`。

- [ ] **Step 1: 写失败测试** — 新建 `eit_ptlc/tests/test_pump_defaults_config_offline.py`:

```python
#!/usr/bin/env python3
"""泵档持久化配置 (config.pump) 离线测试
========================================
两道守护 (spec 2026-07-14-pump-defaults-config-design):
    ParsePumpTests           — _parse_pump 校验器: 未知键拒绝 / 范围守卫 / 缺键合法。
    PumpDefaultsProviderTests — profiles provider 三层回退链:
        knob 传值 > config.pump 持久值 > translator 常量; provider 抛异常回退不阻断。

运行:
    & E:/Anaconda/envs/platformupper/python.exe -m pytest \
      eit_ptlc/tests/test_pump_defaults_config_offline.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import _parse_pump  # noqa: E402


class ParsePumpTests(unittest.TestCase):
    def test_valid_full_section(self):
        out = _parse_pump({
            "sampling": {"asp_speed": 250, "disp_speed": 100, "spot_disp_speed": 50,
                         "step_delay": 1500, "flush_disp_speed": 300,
                         "spot_head_disp_speed": 100},
            "collect": {"asp_speed": 500, "disp_speed": 500, "step_delay": 1000},
            "develop": {"asp_speed": 100, "disp_speed": 100, "step_delay": 500},
        })
        self.assertEqual(out["sampling"]["asp_speed"], 250)
        self.assertEqual(out["collect"]["step_delay"], 1000)
        self.assertEqual(out["develop"]["disp_speed"], 100)

    def test_empty_missing_and_none_ok(self):
        # 空段 / None / 缺工位 / 键值为 null 均合法 (回退常量)
        self.assertEqual(_parse_pump({}), {})
        self.assertEqual(_parse_pump(None), {})
        self.assertEqual(_parse_pump({"collect": {}}), {})
        self.assertEqual(_parse_pump({"sampling": {"asp_speed": None}}), {})

    def test_unknown_station_rejected(self):
        with self.assertRaises(ValueError):
            _parse_pump({"smapling": {"asp_speed": 250}})   # 工位名拼写错误

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            _parse_pump({"collect": {"asp_sped": 500}})      # 参数名拼写错误
        with self.assertRaises(ValueError):
            # flush 键只属 sampling, 出现在 develop 是错误
            _parse_pump({"develop": {"flush_disp_speed": 300}})

    def test_speed_bounds(self):
        with self.assertRaises(ValueError):
            _parse_pump({"sampling": {"asp_speed": 0}})      # 下限 1
        with self.assertRaises(ValueError):
            _parse_pump({"sampling": {"disp_speed": 501}})   # PLC 守卫上限 500
        self.assertEqual(_parse_pump({"sampling": {"asp_speed": 1}})["sampling"]["asp_speed"], 1)
        self.assertEqual(_parse_pump({"sampling": {"asp_speed": 500}})["sampling"]["asp_speed"], 500)

    def test_step_delay_bounds(self):
        self.assertEqual(_parse_pump({"develop": {"step_delay": 0}})["develop"]["step_delay"], 0)
        with self.assertRaises(ValueError):
            _parse_pump({"develop": {"step_delay": -1}})
        with self.assertRaises(ValueError):
            _parse_pump({"develop": {"step_delay": 60001}})

    def test_non_integer_rejected(self):
        with self.assertRaises(ValueError):
            _parse_pump({"collect": {"asp_speed": "fast"}})
        with self.assertRaises(ValueError):
            _parse_pump({"collect": {"asp_speed": 250.5}})   # 非整浮点拒绝 (防静默截断)
        # 整值浮点可接受 (前端 number 输入可能送 250.0)
        self.assertEqual(_parse_pump({"collect": {"asp_speed": 250.0}})["collect"]["asp_speed"], 250)

    def test_non_mapping_rejected(self):
        with self.assertRaises(ValueError):
            _parse_pump({"sampling": [250]})
        with self.assertRaises(ValueError):
            _parse_pump("pump")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_pump_defaults_config_offline.py -q`
Expected: FAIL — `ImportError: cannot import name '_parse_pump'`

- [ ] **Step 3: 实现 `_parse_pump`** — 在 `eit_ptlc/config/loader.py` 的 `_parse_vision` 函数结束后 (现 262 行附近, `_parse_pallas_vision` 之前) 插入:

```python
# ----------------------------------------------------------------------
# 泵档持久默认 (config.pump): 工位 -> {参数名: int}
# ----------------------------------------------------------------------
# 不进 AppConfig (live-read 段, 见 spec 2026-07-14-pump-defaults-config-design §4.2):
# 本校验器服务 ConfigService 写前校验 + bootstrap provider 闭包读后清洗。
# 速度类 1..500 (PLC 守卫上限, 与 translator 一致); step_delay 0..60000 ms。
PUMP_SPEED_MAX = 500
PUMP_STEP_DELAY_MAX = 60000
PUMP_STATION_KEYS: dict[str, tuple[str, ...]] = {
    "sampling": ("asp_speed", "disp_speed", "spot_disp_speed", "step_delay",
                 "flush_disp_speed", "spot_head_disp_speed"),
    "collect": ("asp_speed", "disp_speed", "step_delay"),
    "develop": ("asp_speed", "disp_speed", "step_delay"),
}


def _parse_pump(d) -> dict:
    """校验并规范化 pump 段 -> {工位: {参数名: int}}.

    功能:
        缺键/缺工位/空段/null 值合法 (调用方回退 translator 常量); 未知工位/未知参数键
        一律拒绝 —— 缺键语义是"静默回退常量", 拼写错误若不拒绝会伪装成缺键。
    参数:
        d: app.yaml pump 段原始值 (dict / None)
    返回:
        {station: {key: int}} 仅含显式给值的键
    """
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ValueError("pump 必须是映射")
    unknown_stations = set(d) - set(PUMP_STATION_KEYS)
    if unknown_stations:
        raise ValueError(
            f"pump 未知工位: {sorted(unknown_stations)} (合法 {tuple(PUMP_STATION_KEYS)})")
    out: dict = {}
    for station, keys in PUMP_STATION_KEYS.items():
        sub = d.get(station)
        if sub is None:
            continue
        if not isinstance(sub, dict):
            raise ValueError(f"pump.{station} 必须是映射")
        unknown = set(sub) - set(keys)
        if unknown:
            raise ValueError(f"pump.{station} 未知键: {sorted(unknown)} (合法 {keys})")
        cleaned: dict = {}
        for key, raw in sub.items():
            if raw is None:
                continue
            if isinstance(raw, float) and not raw.is_integer():
                raise ValueError(f"pump.{station}.{key} 必须是整数, 得到: {raw!r}")
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"pump.{station}.{key} 必须是整数, 得到: {raw!r}")
            if key == "step_delay":
                if not 0 <= value <= PUMP_STEP_DELAY_MAX:
                    raise ValueError(
                        f"pump.{station}.step_delay 须在 0..{PUMP_STEP_DELAY_MAX}, 得到: {value}")
            elif not 1 <= value <= PUMP_SPEED_MAX:
                raise ValueError(
                    f"pump.{station}.{key} 须在 1..{PUMP_SPEED_MAX}, 得到: {value}")
            cleaned[key] = value
        if cleaned:
            out[station] = cleaned
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_pump_defaults_config_offline.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/config/loader.py eit_ptlc/tests/test_pump_defaults_config_offline.py
git commit -m "feat(config): _parse_pump 校验器 — pump 段未知键拒绝+速度1..500/延时0..60000守卫

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: ConfigService 开放 pump 段读写

**Files:**
- Modify: `eit_ptlc/controller/config_service.py` (import 行 / `SECTIONS` / `_validate`)
- Test: `eit_ptlc/tests/test_config_service_offline.py` (扩)

**Interfaces:**
- Consumes: Task 1 的 `_parse_pump` (from `eit_ptlc.config.loader`)。
- Produces: `ConfigService.read_section("pump") -> dict` 与 `save_section("pump", values) -> dict` 可用; `GET/PUT /api/config/pump` 经现有 `config_routes.py` 自动生效 (路由按 SECTIONS 白名单转发, 无需改动)。

- [ ] **Step 1: 写失败测试** — 修改 `eit_ptlc/tests/test_config_service_offline.py`:

模块 docstring 首行段落 "camera/gcode/vision 段" 改为 "camera/gcode/vision/pump 段"。`_APP_YAML` 常量的 `vision:` 段之后追加 (保持现有内容不动, 在字符串末尾续):

```python
_APP_YAML = """# 顶部注释 (应保留)
control_mode: DEBUG
camera:
  mock: true
  daheng:
    exposure_time: 500000.0  # 曝光注释
    gain: 1.0
gcode:
  plate_surface_z_mm: 5.0
  boustrophedon_columns: 20  # 列数注释
  path_strategy: contour
vision:
  mock: true
  image_plate_orientation: rot0
pump:
  sampling:
    asp_speed: 250  # 泵档注释
    step_delay: 1500
  collect:
    disp_speed: 500
"""
```

类 `ConfigServiceTests` 末尾 (在 `test_unknown_section_rejected` 之后) 加三个用例:

```python
    def test_pump_read_and_save_roundtrip_keeps_comments(self):
        self.assertEqual(self.svc.read_section("pump")["sampling"]["asp_speed"], 250)
        self.svc.save_section("pump", {"sampling": {"asp_speed": 300}})
        pump = self.svc.read_section("pump")
        self.assertEqual(pump["sampling"]["asp_speed"], 300)
        self.assertEqual(pump["sampling"]["step_delay"], 1500)   # 兄弟字段保留
        self.assertIn("泵档注释", self.tmp.read_text(encoding="utf-8"))  # 注释保留

    def test_pump_save_invalid_rejected_not_written(self):
        with self.assertRaises(ValueError):
            self.svc.save_section("pump", {"sampling": {"asp_speed": 501}})  # 越上限
        self.assertEqual(self.svc.read_section("pump")["sampling"]["asp_speed"], 250)  # 未改

    def test_pump_save_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.save_section("pump", {"sampling": {"asp_sped": 300}})  # 拼写错误
        with self.assertRaises(ValueError):
            self.svc.save_section("pump", {"smapling": {"asp_speed": 300}})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_config_service_offline.py -q`
Expected: FAIL — 3 个新用例报 `ValueError: 不可编辑配置段: pump`

- [ ] **Step 3: 实现** — `eit_ptlc/controller/config_service.py` 三处:

import 行 (现 20 行):

```python
from eit_ptlc.config.loader import _parse_camera, _parse_gcode, _parse_pump, _parse_vision
```

`SECTIONS` (现 50 行):

```python
    SECTIONS = ("camera", "gcode", "vision", "pump")
```

`_validate` (现 60-66 行) 加分支:

```python
    @staticmethod
    def _validate(section: str, merged: dict) -> None:
        if section == "camera":
            _parse_camera(merged)
        elif section == "gcode":
            _parse_gcode(merged)
        elif section == "vision":
            _parse_vision(merged)
        elif section == "pump":
            _parse_pump(merged)
```

同时把模块 docstring 与类 docstring 里的 "(camera / gcode / vision)" 更新为 "(camera / gcode / vision / pump)" (共两处, 现 5 行与 48 行)。

- [ ] **Step 4: 跑测试确认通过**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_config_service_offline.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/controller/config_service.py eit_ptlc/tests/test_config_service_offline.py
git commit -m "feat(config): ConfigService 开放 pump 段 — GET/PUT /api/config/pump 经现有路由生效

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: profiles.py provider 缝 + 三层回退链 + hint 同源

**Files:**
- Modify: `eit_ptlc/tools/pump/profiles.py`
- Test: `eit_ptlc/tests/test_pump_defaults_config_offline.py` (扩)、`eit_ptlc/tests/test_action_dto_offline.py` (扩)
- 回归 (不改): `eit_ptlc/tests/test_pump_contract_offline.py`

**Interfaces:**
- Consumes: 无代码依赖 (provider 由 Task 4 注入; 本 Task 内测试用 lambda 模拟)。
- Produces: `set_pump_defaults_provider(provider: Callable[[], dict] | None) -> None` (Task 4 的 bootstrap 调用; 传 None 撤销, 供测试复位)。`_config_default(station: str, key: str) -> int | None` (模块内部)。`_speed_kwargs(values, mapping, station)` 新签名 (第三个位置参数)。`pump_default_hint(station, param_name)` 签名不变、语义变为 config 优先。

- [ ] **Step 1: 写失败测试** — `eit_ptlc/tests/test_pump_defaults_config_offline.py` 追加 import 与测试类:

import 区补:

```python
from eit_ptlc.tools.pump import collect_translator as ct  # noqa: E402
from eit_ptlc.tools.pump import develop_translator as dt  # noqa: E402
from eit_ptlc.tools.pump import profiles  # noqa: E402
```

文件末尾 (`if __name__ ...` 之前) 加:

```python
class PumpDefaultsProviderTests(unittest.TestCase):
    """三层回退链: knob 传值 > config.pump (provider) > translator 常量。

    provider 是 profiles 模块级状态 —— 每个用例 tearDown 必须复位, 防跨用例污染。
    """

    def tearDown(self):
        profiles.set_pump_defaults_provider(None)

    def test_knob_value_beats_config(self):
        profiles.set_pump_defaults_provider(lambda: {"sampling": {"asp_speed": 111}})
        out = profiles._speed_kwargs({"asp_speed": 222}, {"asp_speed": "asp_speed"}, "sampling")
        self.assertEqual(out, {"asp_speed": 222})

    def test_config_beats_constant(self):
        profiles.set_pump_defaults_provider(lambda: {"sampling": {"asp_speed": 111}})
        out = profiles._speed_kwargs({"asp_speed": None}, {"asp_speed": "asp_speed"}, "sampling")
        self.assertEqual(out, {"asp_speed": 111})

    def test_missing_key_falls_back_to_constant(self):
        # config 缺键 → 不传 kwarg → translator 函数签名常量兜底 (行为与历史一致)
        profiles.set_pump_defaults_provider(lambda: {"sampling": {}})
        out = profiles._speed_kwargs({"asp_speed": None}, {"asp_speed": "asp_speed"}, "sampling")
        self.assertEqual(out, {})

    def test_no_provider_falls_back_to_constant(self):
        out = profiles._speed_kwargs({"asp_speed": None}, {"asp_speed": "asp_speed"}, "collect")
        self.assertEqual(out, {})

    def test_provider_error_falls_back_not_raises(self):
        def boom():
            raise RuntimeError("yaml 损坏")
        profiles.set_pump_defaults_provider(boom)
        out = profiles._speed_kwargs({"asp_speed": None}, {"asp_speed": "asp_speed"}, "sampling")
        self.assertEqual(out, {})   # 回退常量, 不抛出、不阻断派发

    def test_spot_handwritten_fallback_uses_config(self):
        # sampling.spot 的 spot_disp_speed 绕过 _speed_kwargs 的手写回退, 须同样接 config
        profiles.set_pump_defaults_provider(lambda: {"sampling": {"spot_disp_speed": 77}})
        channels = profiles.PUMP_PROFILES["sampling.spot"].build({"sample_volume_ml": 1.0})
        self.assertTrue(
            any("V77" in cmd for cmd in channels["Sampling_dispense_instructions"]),
            f"点样指令未用 config 打速 77: {channels['Sampling_dispense_instructions']}")

    def test_spot_band_layer_handwritten_fallback_uses_config(self):
        profiles.set_pump_defaults_provider(
            lambda: {"sampling": {"spot_disp_speed": 66, "step_delay": 123}})
        channels = profiles.PUMP_PROFILES["sampling.spot_band_layer"].build(
            {"spot_speed_mm_s": 1.0, "dry_speed_mm_s": 2.0, "dry_cycles": 1})
        cmd = channels["Sampling_band_run_instruction"]
        self.assertIn("V66", cmd)
        self.assertIn("M123", cmd)

    def test_hint_follows_config_live(self):
        profiles.set_pump_defaults_provider(lambda: {"develop": {"asp_speed": 123}})
        self.assertEqual(profiles.pump_default_hint("develop", "asp_speed"), 123)
        # config 缺键 → 常量兜底
        self.assertEqual(profiles.pump_default_hint("develop", "disp_speed"), dt.DISP_SPEED)
        # 撤销 provider → 全部回常量
        profiles.set_pump_defaults_provider(None)
        self.assertEqual(profiles.pump_default_hint("develop", "asp_speed"), dt.ASP_SPEED)
        # 非泵工位/非泵参数仍返回 None
        self.assertIsNone(profiles.pump_default_hint("robot", "asp_speed"))
        self.assertIsNone(profiles.pump_default_hint("collect", "wash_volume_ml"))
```

同时 `eit_ptlc/tests/test_action_dto_offline.py` 追加一个用例 (类 `ActionDtoHintTests` 末尾), 并在模块 docstring 的 "断言值直接引用 translator 常量" 句后补一句 "config.pump provider 注入时 hint 跟随持久值 (三层链见 test_pump_defaults_config_offline)":

```python
    def test_hint_follows_pump_config_when_provider_injected(self) -> None:
        # config.pump 有值时 default_hint 透出持久值而非常量 (live-read 同源)
        from eit_ptlc.tools.pump import profiles
        profiles.set_pump_defaults_provider(lambda: {"collect": {"asp_speed": 333}})
        try:
            h = self._hints("collect.collect")
            self.assertEqual(h["asp_speed"], 333)
            self.assertEqual(h["disp_speed"], ct.DISP_SPEED)  # 缺键回退常量
        finally:
            profiles.set_pump_defaults_provider(None)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_pump_defaults_config_offline.py eit_ptlc/tests/test_action_dto_offline.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'set_pump_defaults_provider'` 等

- [ ] **Step 3: 实现** — `eit_ptlc/tools/pump/profiles.py` 逐处修改:

**(a)** import 区 (现 22-29 行) 加 `logging` 与 log 对象:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from eit_ptlc.tools.pump import collect_translator as ct
from eit_ptlc.tools.pump import develop_translator as dt
from eit_ptlc.tools.pump import sample_translator_v2 as s2

log = logging.getLogger(__name__)
```

**(b)** `PumpProfile` 类定义之后、`_speed_kwargs` 之前插入 provider 缝:

```python
# ----------------------------------------------------------------------
# 持久化泵档 provider (config.pump live-read, spec 2026-07-14-pump-defaults)
# ----------------------------------------------------------------------
# bootstrap 注入 lambda: _parse_pump(cfg_svc.read_section("pump")) —— 返回已清洗的
# {工位: {参数名: int}}。本模块不 import config.loader (清洗职责在闭包里, 保持层间解耦)。
# 未注入 (离线测试/脚本直调) / 读失败 → 回退 translator 常量, 行为与历史完全一致。
_pump_defaults_provider: Callable[[], dict] | None = None


def set_pump_defaults_provider(provider: Callable[[], dict] | None) -> None:
    """注入 config.pump live-read provider (None 撤销, 供测试复位)。"""
    global _pump_defaults_provider
    _pump_defaults_provider = provider


def _config_default(station: str, key: str) -> int | None:
    """查 config.pump 持久默认; 未注入/读失败/缺键 → None (调用方回退常量)。

    读失败只 warning 不抛出 —— 泵档缺省绝不能阻断派发。
    """
    if _pump_defaults_provider is None:
        return None
    try:
        section = _pump_defaults_provider() or {}
    except Exception as exc:
        log.warning("config.pump 读取失败, 回退 translator 常量: %s", exc)
        return None
    value = section.get(station, {}).get(key)
    return int(value) if value is not None else None
```

**(c)** `_speed_kwargs` 改签名与回退链 (docstring 同步):

```python
def _speed_kwargs(values: dict, mapping: dict, station: str) -> dict:
    """从语义 dict 抽取已提供的 V/M 覆写 -> translator kwargs.

    mapping: {YAML参数名: translator_kwarg名}; station: 泵工位 (sampling/collect/develop)。
    回退链: values 传值 > config.pump 持久值 (_config_default) > 不传 kwarg
    (由 translator 模块常量兜底)。
    对每个键都经 values.get 访问, 供 test_pump_contract_offline 记账 (声明即须被消费)。
    """
    out: dict = {}
    for yaml_name, kw in mapping.items():
        v = values.get(yaml_name)
        if v is None:
            v = _config_default(station, yaml_name)
        if v is not None:
            out[kw] = int(v)
    return out
```

**(d)** 全部 9 个调用点补 station 实参 (逐处列出, 只改调用行):

| 函数 | 改后调用 |
|---|---|
| `_build_sampling_clean` | `_speed_kwargs(values, _ASP_DISP_DELAY, "sampling")` |
| `_build_sampling_flush` | `_speed_kwargs(values, _FLUSH_SPEED_KWARGS, "sampling")` |
| `_build_sampling_prep` | `_speed_kwargs(values, {"asp_speed": "asp_speed", "step_delay": "step_delay"}, "sampling")` |
| `_build_sampling_aspirate` | `_speed_kwargs(values, {"asp_speed": "asp_speed", "step_delay": "step_delay"}, "sampling")` |
| `_build_sampling_spot` | `_speed_kwargs(values, {"asp_speed": "asp_speed", "step_delay": "step_delay"}, "sampling")` |
| `_build_collect_collect` | `_speed_kwargs(values, _ASP_DISP_DELAY, "collect")` |
| `_build_develop_rinse` | `_speed_kwargs(values, _ASP_DISP_DELAY, "develop")` |
| `_build_develop_fill` | `_speed_kwargs(values, _ASP_DISP_DELAY, "develop")` |

**(e)** `_build_sampling_spot` 手写回退接链 (docstring 的 "缺省回退" 句改为三层链表述):

```python
def _build_sampling_spot(values: dict) -> dict:
    """点样: 抽取驱动空气 + 打气点样(含回抽释压)指令数组.

    点样打液速度 spot_disp_speed (DT V) 回退链: 传值 > config.pump >
    DEFAULT_DISPENSE_DISP_SPEED (=50, 精度优先), 而非 translator 的 0->跟随 disp_speed。
    """
    spot = values.get("spot_disp_speed")
    if spot is None:
        spot = _config_default("sampling", "spot_disp_speed")
    kwargs = _speed_kwargs(values, {"asp_speed": "asp_speed", "step_delay": "step_delay"}, "sampling")
    kwargs["dispense_disp_speed"] = int(spot) if spot is not None else s2.DEFAULT_DISPENSE_DISP_SPEED
    return {
        "Sampling_dispense_instructions": s2.build_dispense_array(
            float(values["sample_volume_ml"]), **kwargs,
        ),
    }
```

**(f)** `_build_sampling_spot_band_layer` 手写回退接链 (仅改 spot/delay 两行取值, 其余原样):

```python
    spot = values.get("spot_disp_speed")
    if spot is None:
        spot = _config_default("sampling", "spot_disp_speed")
    delay = values.get("step_delay")
    if delay is None:
        delay = _config_default("sampling", "step_delay")
```

**(g)** hint 表更名 + 函数改 provider-backed (替换现 249-278 行整块):

```python
# ----------------------------------------------------------------------
# 泵档默认 (V/M) 的 UI 提示 (派发单 A2 显示侧)
# ----------------------------------------------------------------------
# 常量兜底层: 数字只引用 translator 常量 (s2/ct/dt), 不重新键入 -> 与执行兜底同源。
# pump_default_hint 先查 config.pump (live-read, 与执行回退链同一 _config_default),
# 缺键才落本表 —— UI 占位与实际执行值恒同源, 用户改 config 即时跟随。
_PUMP_CONSTANT_HINTS: dict[str, dict[str, int]] = {
    "sampling": {"asp_speed": s2.ASP_SPEED, "disp_speed": s2.DISP_SPEED,
                 "spot_disp_speed": s2.DEFAULT_DISPENSE_DISP_SPEED, "step_delay": s2.STEP_DELAY,
                 "flush_disp_speed": s2.FLUSH_DISP_SPEED,
                 "spot_head_disp_speed": s2.FLUSH_SPOT_HEAD_DISP_SPEED},
    "collect":  {"asp_speed": ct.ASP_SPEED, "disp_speed": ct.DISP_SPEED, "step_delay": ct.STEP_DELAY},
    "develop":  {"asp_speed": dt.ASP_SPEED, "disp_speed": dt.DISP_SPEED, "step_delay": dt.STEP_DELAY},
}


def pump_default_hint(station: str, param_name: str) -> int | None:
    """返回某工位某泵参数"未覆写时实际执行值" (无则 None).

    功能:
        供 UI 占位展示; 与执行回退链同源 —— 先查 config.pump 持久值 (_config_default),
        缺键回退 translator 常量兜底表。非泵参数 / 非泵工位返回 None。
    参数:
        station: 动作工位名 (sampling/collect/develop)
        param_name: 参数名 (asp_speed/disp_speed/spot_disp_speed/step_delay/...)
    返回:
        int 泵档默认值, 无对应项返回 None
    """
    hints = _PUMP_CONSTANT_HINTS.get(station, {})
    if param_name not in hints:
        return None   # 非泵参数/工位: 不查 config, 保持 None 语义
    cfg = _config_default(station, param_name)
    return cfg if cfg is not None else hints[param_name]
```

**(h)** 模块 docstring 的 "V/M 显式传参 (派发单 A2)" 段落, 把 "由 translator 模块常量兜底 ... 故默认值唯一真源仍是 translator 常量" 改为:

```
V/M 显式传参 (派发单 A2 + config.pump 持久化):
    各泵动作可选暴露 asp_speed/disp_speed/(spot_disp_speed)/step_delay (DT 指令 V/M);
    缺省 (未在 YAML 传入) 时回退链 = config.pump 持久值 (live-read, bootstrap 注入
    provider) > translator 模块常量 (各站常量: sampling 250/100/1500 · collect
    500/500/1000 · develop 100/100/500)。运行默认的实际真源是 config.pump (app.yaml
    播种初值 = 常量), 常量降级为缺键/读失败兜底; YAML 仅声明"可覆写"而不复制数值默认.
```

- [ ] **Step 4: 跑测试确认通过 (含契约回归)**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_pump_defaults_config_offline.py eit_ptlc/tests/test_action_dto_offline.py eit_ptlc/tests/test_pump_contract_offline.py -q`
Expected: PASS 全绿; 其中 `test_pump_contract_offline.py` 零改动通过 (契约测试给全部声明参数造了非 None 值, config 回退路径不触发, 记账集不变)

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/tools/pump/profiles.py eit_ptlc/tests/test_pump_defaults_config_offline.py eit_ptlc/tests/test_action_dto_offline.py
git commit -m "feat(pump): profiles 三层回退链 — knob传值 > config.pump(provider live-read) > translator常量; hint 同源跟随

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 接线 — app.yaml 播种 + bootstrap 注入 + 前端段入口 + 全量回归

**Files:**
- Modify: `eit_ptlc/config/app.yaml` (文件末尾追加段)
- Modify: `eit_ptlc/runtime/bootstrap.py` (import + 注入一行)
- Modify: `eit_ptlc/web/src/components/DeviceParamsPanel.vue` (SECTIONS 加一项)

**Interfaces:**
- Consumes: Task 1 `_parse_pump` + Task 3 `set_pump_defaults_provider`。
- Produces: 运行系统全链贯通 (UI 编辑 → 写盘 → 派发 live-read)。无后续 Task。

- [ ] **Step 1: app.yaml 播种 pump 段** — 文件末尾 (`vision_debug` 段之后, 现 217 行后) 追加:

```yaml

# 泵档默认 (V/M 速度/延时): 优先级 = 运行前参数覆盖 > 本段 > translator 常量兜底
# 速度单位: 半步/s, 守卫上限 500; step_delay 单位 ms (0..60000)。改后对下一次派发即生效
# (live-read, 无需重启)。删除某键 = 回退代码常量。spec: 2026-07-14-pump-defaults-config-design
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

播种值必须与 translator 常量当前值一致 (上面即是); 播种全部键否则 DeviceParamsPanel 扁平编辑器无字段可编辑。

- [ ] **Step 2: 校验 app.yaml 仍可加载**

Run: `E:/Anaconda/envs/platformupper/python.exe -m eit_ptlc.config.loader --check`
Expected: 退出码 0, 无错误输出 (pump 段不进 AppConfig, loader --check 忽略之但 YAML 语法错误会炸)

- [ ] **Step 3: bootstrap 注入 provider** — `eit_ptlc/runtime/bootstrap.py` 两处:

import 行 (现 31 行) 扩:

```python
from eit_ptlc.config.loader import _parse_gcode, _parse_pump, _parse_vision
```

import 区 (现 34 行 `from eit_ptlc.controller.config_service import ConfigService` 附近) 加:

```python
from eit_ptlc.tools.pump.profiles import set_pump_defaults_provider
```

`app.state.config_svc = ConfigService(config_path)` (现 374 行) 之后加:

```python
    # 泵档持久默认 live-read: knob 传值 > config.pump > translator 常量 (清洗在闭包, profiles 不依赖 loader)
    _cfg_svc = app.state.config_svc
    set_pump_defaults_provider(lambda: _parse_pump(_cfg_svc.read_section("pump")))
```

- [ ] **Step 4: 前端段入口** — `eit_ptlc/web/src/components/DeviceParamsPanel.vue` 的 `SECTIONS` (现 7-11 行) 加一项, 顶部注释同步:

```javascript
// 设备参数面板: app.yaml 的 camera/gcode/vision/pump 段结构化编辑 (扁平化为点号路径字段)
// 嵌入动作/流程页, 复用参数表单范式; 保存经后端 loader 校验 (不通过 400 不写盘)
const SECTIONS = [
  { key: 'camera', label: '相机 (曝光/增益/UV光/图像尺寸)' },
  { key: 'gcode', label: 'CNC (板原点/Z高度/进给/刀具)' },
  { key: 'vision', label: '视觉' },
  { key: 'pump', label: '泵档默认 (吸/打速度/步延时)' },
]
```

- [ ] **Step 5: 全量离线回归**

Run: `E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests -q`
Expected: 全绿 (基线 446+ 用例 + 本次新增; 零 fail)。若有既有用例因 pump 段新增而挂 (如快照类断言), 逐个查明修复后重跑。

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/config/app.yaml eit_ptlc/runtime/bootstrap.py eit_ptlc/web/src/components/DeviceParamsPanel.vue
git commit -m "feat(pump): 接线 config.pump — app.yaml 播种泵档段 + bootstrap 注入 live-read provider + 设备参数面板入口

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## 上机验证项 (实施完成后, 不在本 plan 自动化范围)

1. UI 改 sampling `asp_speed` → 不重启, 派发 sampling.clean, 抓 PLC 写帧确认新速度生效。
2. 运行前 knob 覆盖同参数 → 覆盖值压过 config 值。
3. 动作页占位提示显示 config 当前值 (非常量、非 0)。
