# 拍照刮板对位检查(Plan B: PLC + Host + 编排)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 刮前机床侧唯一探针 —— 刀头走位到板原点角/路径起点,配 jog 微调 + 轴位置回显 + Δ 建议(只显示不回写),编排成可复用内环 + 独立对刀业务 + 门环选项三层。

**Architecture:** PLC PhotoScrape_L2 新增专用 ActionCode 42/43/44(守卫全在动作内);host 侧零新执行器分支 —— plc_l2 动作纯 YAML,回显/Δ/建议全部下沉到一个 `host` kind 动作 `photoscrape.align_readout`(闭包 live-read gcode 配置 + 读 PLC ActPos,返回预格式化中文 `text`,VM 零算术);编排 D1 内环子 operation ← `op: run_script` ← D2 独立对刀业务 / D3 门环选项。

**Tech Stack:** CODESYS ST(经 codesys-mcp)、OPCUA 符号节点、ptlc VM YAML operation、FastAPI、pytest 离线(伪执行器,PLC 不在场全绿)。

**Spec:** docs/superpowers/specs/2026-07-16-photoscrape-align-check-design.md §2 决策表 Q1-Q7 逐字遵守

## Global Constraints(逐字来自 spec)

- **专动作专用, 收窄影响面**:新动作不碰 `g_sx/g_sy/g_cx/g_cy`、收集器轴、气缸/真空/翻料 —— 与 scrape(40) 零共享状态。
- **Z 正方向向下;Z=0 在上=安全位**。**一切 XY 移动只在 10Z 零位发生**(2026-07-16 B1 核查修正:原"检查高度下 ≤2mm 微调"与既有互锁 `刮板轴10ZDATE.fActPos<6` 冲突已废除;jog = 升Z→步进→人工再缓降复查循环;PLC 42 动作内强制,不靠调用方)。
- **Align Target 与 g_sx/g_sy 同帧**(机床 mm);若单轴 MC 需帧变换在 PLC 内完成(B1 C2:host plate_origin 与 8Y 轴坐标疑似不同帧,上机首项核查);板区软限位窗数值上机以 ActPos 轴坐标实测。
- 检查高度 = `plate_surface_z_mm − align_clearance_mm`(新配置,默认 2.5mm),**不立第二刀长源**;换刀只改 `plate_surface_z_mm`。
- **单写者**:PLC 写只经 VM run 内动作;UI 只读轮询(读不算写者)。
- **Δ 只显示不回写**:plate_origin_x/y 唯一修正家,run 上下文无权改标定。
- D1 内环**不碰气缸**(门环调用时板压紧且还要刮);任何失败/中止路径先回零(ActionCode 43 自带"Z 不在 0 先升 Z"),刀头绝不悬在板上方退出。
- 老路/既有行为零回归:photoscrape_process 既有分支逐字节不动,只增 align 选项。
- 动作码 42/43/44 空闲已核(现用 10/31/32/33/34/35/40/41/52)。
- ⚠️ YAML 注释会被 web 编辑器回写剥光:设计知识写进 docs/ 与 `op: comment` 节点。
- ⚠️ PLC 未下装 42/43/44 前,真机**禁发** align 系动作(离线测试用伪执行器不受限)。
- 本机测试解释器 = `E:/Anaconda/python.exe`。

## File Structure & 任务 DAG

| 文件 | 职责 | 任务 |
|---|---|---|
| `docs/superpowers/plans/2026-07-16-align-plc-worklog.md`(建) | CODESYS 核查记录(轴实例/回零块/软限位/40 起点假设) | T1 |
| `eit_ptlc/config/models.py` + `config/loader.py` + `config/app.yaml`(改) | `align_clearance_mm` 配置 | T2 |
| `eit_ptlc/controller/plc_controller.py`(改) | `read_scrape_axes()` | T3 |
| `eit_ptlc/runtime/bootstrap.py`(改) | `_align_readout` 闭包 + vision_methods 注册 | T4 |
| `eit_ptlc/config/actions/04_photoscrape/align_host.yaml`(建) | `photoscrape.align_readout`(kind: host) | T4 |
| `eit_ptlc/config/actions/04_photoscrape/plc_photoscrape.yaml`(改) | `align_move/align_home/align_z`(kind: plc_l2, 42/43/44) | T5 |
| `eit_ptlc/api/photoscrape_routes.py`(改) | `GET /api/photoscrape/axes` 只读轮询 | T6 |
| `eit_ptlc/controller/cnc_path.py`(改) | 结果增 `start_x_mm/start_y_mm`(路径首点) | T7 |
| `eit_ptlc/config/operation/03_photoscrape/photoscrape_align_loop.yaml`(建) | D1 内环子 operation | T8 |
| `eit_ptlc/config/operation/03_photoscrape/photoscrape_tool_align.yaml`(建) | D2 独立对刀业务 | T9 |
| `eit_ptlc/config/operation/03_photoscrape/photoscrape_process.yaml`(改) | D3 门环 align 选项 | T10 |
| PLC 20260702.project(经 codesys-mcp) | ActionCode 42/43/44 + 5 节点 | T11(依赖 T1) |
| `docs/photoscrape-tool-align-manual.md`(建) | 对刀业务操作手册 | T12 |

依赖:T1 独立可先行;T2→T4;T3→T4/T6;T4/T5→T8;T7→T10;T8→T9/T10;T11 依赖 T1(且是真机启用前提);T12 收尾。离线测试全程不需要 PLC 在场。

---

### Task 1: CODESYS 核查(实施验证项落 worklog)

**Files:**
- Create: `docs/superpowers/plans/2026-07-16-align-plc-worklog.md`

**Interfaces:**
- Produces: worklog 文档,T11 逐条消费(轴 FB 实例名、回零块名、软限位来源、速度常量基准)。

- [ ] **Step 1:** 起 CODESYS 会话(`mcp__codesys__codesys_status` 确认;⚠️ 换手前杀旧版 codesys-mcp Node 进程,见 memory[ptlc-plc-session-takeover-bugs])。
- [ ] **Step 2:** `codesys_read_pou` 读 `PhotoScrape_L2`(50_action 家族)与其调用的运动块,逐条记录进 worklog:
  1. scrape(40) 用哪些轴 FB 实例(9X/8Y/10Z 的 AXIS_REF 名);与 42/43/44 拟用轴有无隐藏共享状态(使能/插补器 B1/B2/CNC启动线);
  2. 8Y 相机/刮头同轴时序:cam_photohome(35) 终态 8Y 是否在零;
  3. 回零复用哪个既有块(MC_Home?一键回原点链?),42/43 能否直接调用;
  4. scrape(40) 对起始 XY 有无"从零位出发"假设(首点是否有进近段);
  5. 既有软限位/行程常量在哪(轴配置 or GVL),42 的板区窗数值从哪取;
  6. 既有 MC_MoveAbsolute 的速度典型值(42/44 保守速度取其 1/2 作基准);
  7. GVL 符号配置(Symbol Configuration)当前导出方式,确认新增 5 节点的挂载点(Host_Computer 组)。
- [ ] **Step 3:** worklog 末尾给出 T11 的最终 ST 集成点清单(CASE 分支插入行号/兄弟动作码样例)。
- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-07-16-align-plc-worklog.md
git commit -m "docs(align): PLC 核查 worklog — PhotoScrape_L2 轴实例/回零/软限位/40起点假设 (spec 0716 §7)"
```

---

### Task 2: 配置 `align_clearance_mm`

**Files:**
- Modify: `eit_ptlc/config/models.py:307`(GCodeCfg,`plate_surface_z_mm` 下一行)
- Modify: `eit_ptlc/config/loader.py`(`_parse_gcode`,452 起;仿 `plate_surface_z_mm` 的解析行)
- Modify: `eit_ptlc/config/app.yaml:174` 附近(gcode 段)
- Test: `eit_ptlc/tests/test_align_check_offline.py`(新建,本 plan 后续任务共用此文件)

**Interfaces:**
- Produces: `GCodeCfg.align_clearance_mm: float = 2.5`;T4 闭包消费 `plate_surface_z_mm − align_clearance_mm`。

- [ ] **Step 1: 失败测试(新建 test_align_check_offline.py)**

```python
"""对位检查 — 配置/回显/端点/编排离线测试 (spec 2026-07-16-photoscrape-align-check)。"""

from __future__ import annotations

from eit_ptlc.config.loader import _parse_gcode


def test_align_clearance_default_and_parse():
    assert _parse_gcode({}).align_clearance_mm == 2.5
    assert _parse_gcode({"align_clearance_mm": 4.0}).align_clearance_mm == 4.0
```

- [ ] **Step 2:** Run `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_align_check_offline.py -v` → FAIL(TypeError/AttributeError)。
- [ ] **Step 3: 实现**

models.py(`plate_surface_z_mm: float = 7.0` 下一行):

```python
    align_clearance_mm: float = 2.5     # 对位检查高度余量(mm): 检查Z = plate_surface_z_mm − 此值; 不立第二刀长源
```

loader.py `_parse_gcode` 返回构造中,与 `plate_surface_z_mm=...` 相邻处加:

```python
        align_clearance_mm=float(d.get("align_clearance_mm", GCodeCfg.align_clearance_mm)),
```

app.yaml gcode 段 `plate_surface_z_mm: 20.5` 下一行加:

```yaml
  align_clearance_mm: 2.5             # 对位检查高度余量(mm): 检查Z=plate_surface_z_mm−此值(当前刀≈18); 换刀只改 plate_surface_z_mm
```

- [ ] **Step 4:** 重跑 Step 2 → PASS;`E:/Anaconda/python.exe -m pytest eit_ptlc/tests -q -k gcode` 零回归。
- [ ] **Step 5: Commit** `git commit -m "feat(config): gcode.align_clearance_mm — 对位检查高度锚定 plate_surface_z_mm (spec 0716 Q5)"`

---

### Task 3: `plc_controller.read_scrape_axes()`

**Files:**
- Modify: `eit_ptlc/controller/plc_controller.py`(`read_rail_pose` :200-208 之后,同节)
- Test: `eit_ptlc/tests/test_align_check_offline.py`(追加)

**Interfaces:**
- Consumes: driver `read_variable(name)`(与 `read_rail_pose` 同)。
- Produces: `async read_scrape_axes(self) -> tuple[float, float, float]`(x,y,z 机床 mm);T4 闭包与 T6 端点消费。节点名:`PhotoScrape_9X_ActPos` / `PhotoScrape_8Y_ActPos` / `PhotoScrape_10Z_ActPos`。

- [ ] **Step 1: 失败测试(追加;PlcController 构造方式照 `eit_ptlc/tests/test_plc_l2_missed_done_offline.py` 的既有 fixture 逐字复用 —— 先读该文件确认构造参数,再落测试)**

```python
import asyncio


def test_read_scrape_axes_reads_three_actpos_nodes():
    # FakeDriver 与 PlcController 构造: 复用 test_plc_l2_missed_done_offline.py 的 fixture 形态,
    # 给 read_variable 喂 {"PhotoScrape_9X_ActPos": 91.24, "PhotoScrape_8Y_ActPos": -75.2,
    #                      "PhotoScrape_10Z_ActPos": 0.0}
    plc = _make_plc_with_values({
        "PhotoScrape_9X_ActPos": 91.24,
        "PhotoScrape_8Y_ActPos": -75.2,
        "PhotoScrape_10Z_ActPos": 0.0,
    })
    x, y, z = asyncio.run(plc.read_scrape_axes())
    assert (x, y, z) == (91.24, -75.2, 0.0)
```

`_make_plc_with_values` 为本文件内 helper:内嵌最小 FakeDriver(`async def read_variable(self, name): return self._vals[name]`),PlcController 构造参数以 test_plc_l2_missed_done_offline.py 为准。

- [ ] **Step 2:** 跑 → FAIL(no attribute)。
- [ ] **Step 3: 实现(read_rail_pose 之后)**

```python
    async def read_scrape_axes(self) -> tuple[float, float, float]:
        """读刮板 CNC 三轴实际位置 (mm, Z 正方向向下): 9X/8Y/10Z — 对位检查回显。

        节点未下装到真机时 driver 抛 KeyError, 由调用方兜底 (端点 503 / 动作 ERROR)。
        """
        x = float(await self._driver.read_variable("PhotoScrape_9X_ActPos"))
        y = float(await self._driver.read_variable("PhotoScrape_8Y_ActPos"))
        z = float(await self._driver.read_variable("PhotoScrape_10Z_ActPos"))
        return x, y, z
```

- [ ] **Step 4:** 跑 → PASS。**Step 5: Commit** `feat(plc): read_scrape_axes — 刮板三轴 ActPos 只读回显`

---

### Task 4: host 动作 `photoscrape.align_readout`(回显/Δ/建议单点产地)

**Files:**
- Modify: `eit_ptlc/runtime/bootstrap.py:339-346`(vision_methods)与其上方闭包区
- Create: `eit_ptlc/config/actions/04_photoscrape/align_host.yaml`
- Test: `eit_ptlc/tests/test_align_check_offline.py`(追加)

**Interfaces:**
- Consumes: T2 配置、T3 `plc.read_scrape_axes()`、`app.state.config_svc.read_section("gcode")`(live-read,与 cnc_path 同源)。
- Produces: 动作 `photoscrape.align_readout`(kind: host, method: align_readout, 无参),result:
  `{x_mm, y_mm, z_mm, origin_x_mm, origin_y_mm, inspect_z_mm, dx_vs_origin_mm, dy_vs_origin_mm, text}`。
  语义:**jog 对准原点角后,建议 plate_origin 新值 = 当前实读 (x_mm, y_mm) 直接照抄**(plate_origin 定义即"板 cm(0,0) 角的机床坐标",flip 不进公式)。D1(T8)每轮门前调用,prompt 直接拼 `text`。

- [ ] **Step 1: 失败测试(纯函数抽出便于离线测:格式化拆成 `controller/align_check.py` 亦可,MVP 直接测 bootstrap 闭包不划算 —— 落一个纯函数 `build_align_readout(axes, gcode_cfg) -> dict` 在新文件 `eit_ptlc/controller/align_check.py`,bootstrap 闭包只做 IO 再调它)**

```python
from eit_ptlc.config.loader import _parse_gcode
from eit_ptlc.controller.align_check import build_align_readout


def test_align_readout_delta_and_text():
    g = _parse_gcode({"plate_origin_x": 91.24, "plate_origin_y": -75.2,
                      "plate_surface_z_mm": 20.5, "align_clearance_mm": 2.5})
    ro = build_align_readout((92.34, -75.9, 0.0), g)
    assert ro["origin_x_mm"] == 91.24 and ro["origin_y_mm"] == -75.2
    assert ro["inspect_z_mm"] == 18.0
    assert round(ro["dx_vs_origin_mm"], 3) == 1.1
    assert round(ro["dy_vs_origin_mm"], 3) == -0.7
    assert "X=92.34" in ro["text"] and "plate_origin" in ro["text"]
```

- [ ] **Step 2:** 跑 → FAIL。
- [ ] **Step 3: 实现 `eit_ptlc/controller/align_check.py`(新建)**

```python
"""对位检查回显 — Δ 与建议值单点产地 (spec 2026-07-16 §5)。

Δ = ActPos 实读 − plate_origin 指令原点; jog 对准物理板角(标注图金色双圈角)后,
建议 plate_origin 新值 = 当前实读直接照抄 (plate_origin 定义即该角机床坐标, flip 不进公式)。
只显示不回写: 修正家唯一 = 配置页 plate_origin_x/y。
"""

from __future__ import annotations

from eit_ptlc.config.models import GCodeCfg


def build_align_readout(axes: tuple[float, float, float], g: GCodeCfg) -> dict:
    x, y, z = (round(float(v), 3) for v in axes)
    inspect_z = round(max(0.0, g.plate_surface_z_mm - g.align_clearance_mm), 3)
    dx = round(x - g.plate_origin_x, 3)
    dy = round(y - g.plate_origin_y, 3)
    text = (
        f"当前 X={x} Y={y} Z={z} (mm, Z向下) | "
        f"原点角=({g.plate_origin_x}, {g.plate_origin_y}) Δ=({dx}, {dy}) | "
        f"检查高度 Z={inspect_z} | "
        f"jog 对准原点角后建议 plate_origin: x→{x} y→{y} (只显示不回写, 到配置页人工修改)"
    )
    return {
        "x_mm": x, "y_mm": y, "z_mm": z,
        "origin_x_mm": g.plate_origin_x, "origin_y_mm": g.plate_origin_y,
        "inspect_z_mm": inspect_z,
        "dx_vs_origin_mm": dx, "dy_vs_origin_mm": dy,
        "text": text,
    }
```

- [ ] **Step 4: bootstrap 闭包(`_wl_capture_reference` 之后)+ 注册**

```python
    async def _align_readout(**kwargs):
        """VM photoscrape.align_readout 入口: 读三轴 ActPos + live-read gcode → 回显/Δ/建议。"""
        from eit_ptlc.config.loader import _parse_gcode
        from eit_ptlc.controller.align_check import build_align_readout
        cfg_svc = getattr(app.state, "config_svc", None)
        if cfg_svc is None:
            raise ValueError("配置服务未就绪, align_readout 不可用")
        g = _parse_gcode(cfg_svc.read_section("gcode"))
        axes = await plc.read_scrape_axes()
        return build_align_readout(axes, g)
```

vision_methods 增 `"align_readout": _align_readout,`。
(注:若 bootstrap 中 `app.state.config_svc` 赋值晚于此闭包定义,闭包内 getattr 是惰性读,无顺序问题 —— 与 `_wl_capture_reference` 同型。)

- [ ] **Step 5: 动作 YAML `config/actions/04_photoscrape/align_host.yaml`(新建)**

```yaml
# 对位检查回显 (host kind, 上位机纯读, 不进 PLC L2 FSM; spec 2026-07-16 §5):
# 读 9X/8Y/10Z ActPos + live-read gcode → 位置/Δ/建议 plate_origin(只显示不回写) + 预格式化 text。
# D1 内环每轮门前调用, prompt 直接拼 result.text (VM 零算术)。
photoscrape.align_readout:
  kind: host
  method: align_readout
  label: 对位-回显
  desc: 三轴实读 + Δ(实读−原点角) + 建议 plate_origin 新值; 节点未下装时动作 ERROR。
  modes: []
  params: []
```

- [ ] **Step 6:** 跑 Step 1 测试 → PASS;全量 `pytest eit_ptlc/tests -q` 零回归(动作注册表加载会扫到新 YAML)。
- [ ] **Step 7: Commit** `feat(align): photoscrape.align_readout host 动作 — 回显/Δ/建议单点产地, VM 零算术`

---

### Task 5: plc_l2 动作 YAML(42/43/44)

**Files:**
- Modify: `eit_ptlc/config/actions/04_photoscrape/plc_photoscrape.yaml`(末尾追加)
- Test: `eit_ptlc/tests/test_align_check_offline.py`(追加)

**Interfaces:**
- Produces: `photoscrape.align_move(x_mm, y_mm)` / `photoscrape.align_home()` / `photoscrape.align_z(z_mm)`;channel 节点 `PhotoScrape_Align_TargetX/TargetY/TargetZ`。T8 编排消费;T11 PLC 侧对齐同名节点与动作码。

- [ ] **Step 1: 失败测试(注册表加载断言;ActionRegistry 构造方式:先 grep `ActionRegistry(` 在 tests/ 的既有用法并逐字复用其加载 fixture)**

```python
def test_align_actions_registered():
    reg = _load_registry()   # 复用既有测试的 registry 加载 helper
    mv = reg.get("photoscrape.align_move")
    assert mv.kind == "plc_l2" and mv.action_code == 42
    assert {p.name: p.channel for p in mv.params} == {
        "x_mm": "PhotoScrape_Align_TargetX", "y_mm": "PhotoScrape_Align_TargetY"}
    assert reg.get("photoscrape.align_home").action_code == 43
    az = reg.get("photoscrape.align_z")
    assert az.action_code == 44
    assert [p.channel for p in az.params] == ["PhotoScrape_Align_TargetZ"]
    assert reg.get("photoscrape.align_readout").kind == "host"
```

- [ ] **Step 2:** 跑 → FAIL。
- [ ] **Step 3: 实现(plc_photoscrape.yaml 末尾;动作码表文件保持单一)**

```yaml
# ── 对位检查 (spec 2026-07-16-photoscrape-align-check §4; 专动作专用, 不碰 g_数组/收集器轴/气缸) ──
# 守卫全在 PLC 动作内: 42 Z门(一切XY移动只在10Z零位, 与既有互锁 fActPos<6 同哲学) + 板区软限位窗;
# 44 只在 XY 位于板区窗内才许降; 43 若 Z 不在 0 先升 Z 再 9X/8Y 回零。Target 与 g_sx/g_sy 同帧(帧变换在PLC内)。
# ⚠️ PLC 未下装 42/43/44 前真机禁发 (worklog: 2026-07-16-align-plc-worklog.md)。
photoscrape.align_move:
  kind: plc_l2
  station: photoscrape
  action_code: 42
  label: 对位-移动XY
  desc: 刀头 XY 到机床mm目标并停在原地 (Done 不回零); Z门/软限位拒动=ErrorCode
  modes: []
  params:
    - {name: x_mm, type: float, required: true, channel: PhotoScrape_Align_TargetX, label: 目标X(mm)}
    - {name: y_mm, type: float, required: true, channel: PhotoScrape_Align_TargetY, label: 目标Y(mm)}
photoscrape.align_home: {kind: plc_l2, station: photoscrape, action_code: 43, label: 对位-结束回零, desc: Z不在0先升Z, 再9X/8Y回零, modes: []}
photoscrape.align_z:
  kind: plc_l2
  station: photoscrape
  action_code: 44
  label: 对位-Z两档
  desc: host 只发 {0, 检查高度} 两档; XY 在板区窗内才许降, 慢速
  modes: []
  params:
    - {name: z_mm, type: float, required: true, channel: PhotoScrape_Align_TargetZ, label: 目标Z(mm)}
```

- [ ] **Step 4:** 跑 → PASS。**Step 5: Commit** `feat(align): plc_l2 动作 42/43/44 — align_move/home/z (真机待 PLC 下装)`

---

### Task 6: 只读轮询端点 `GET /api/photoscrape/axes`

**Files:**
- Modify: `eit_ptlc/api/photoscrape_routes.py`(`sketch_context` 后)
- Test: `eit_ptlc/tests/test_align_check_offline.py`(追加;client 构造照 test_sketch_rectify_offline.py `_client`,额外挂 `app.state.plc` stub)

**Interfaces:**
- Consumes: T3 `plc.read_scrape_axes()`(经 `request.app.state.plc`)。
- Produces: `{"x_mm","y_mm","z_mm"}`;未来 align 前端面板轮询用(本期 MVP 仅联调工具消费),读不算写者。

- [ ] **Step 1: 失败测试**

```python
def test_axes_endpoint_reads_plc(tmp_path):
    client, app = _client_with_plc(tmp_path, values=(91.24, -75.2, 0.0))
    r = client.get("/api/photoscrape/axes")
    assert r.status_code == 200
    assert r.json() == {"x_mm": 91.24, "y_mm": -75.2, "z_mm": 0.0}


def test_axes_endpoint_503_when_plc_absent(tmp_path):
    client, app = _client_with_plc(tmp_path, values=None)   # app.state.plc = None
    assert client.get("/api/photoscrape/axes").status_code == 503
```

`_client_with_plc`:FastAPI + register_photoscrape_routes;plc stub = `class _P: async def read_scrape_axes(self): return values`。

- [ ] **Step 2:** FAIL(404)。
- [ ] **Step 3: 实现**

```python
    @app.get("/api/photoscrape/axes")
    async def read_axes(request: Request):
        """刮板三轴 ActPos 只读回显 (UI 轮询; 读不算写者, 单写者纪律不破)。"""
        plc = getattr(request.app.state, "plc", None)
        if plc is None:
            raise HTTPException(503, "PLC 控制器未就绪")
        try:
            x, y, z = await plc.read_scrape_axes()
        except Exception as exc:  # noqa: BLE001 — 节点未下装(KeyError)/通讯异常统一 503
            raise HTTPException(503, f"读取刮板轴位置失败: {exc}") from exc
        return {"x_mm": x, "y_mm": y, "z_mm": z}
```

- [ ] **Step 4:** PASS。**Step 5: Commit** `feat(align): GET /api/photoscrape/axes 只读轮询端点`

---

### Task 7: cnc_path 结果增 `start_x_mm/start_y_mm`

**Files:**
- Modify: `eit_ptlc/controller/cnc_path.py`(结果 dataclass ~:129 与 to-dict ~:153,生成处 ~:1029-1044,placeholder ~:1075-1082)
- Test: 既有 cnc_path 测试文件追加(grep `pass_z_list` 定位主测试文件)

**Interfaces:**
- Produces: cnc_path 动作 result 新增键 `start_x_mm`/`start_y_mm` = `g_sx[0]`/`g_sy[0]`(路径首点机床 mm;placeholder 时 0.0)。T10 D3 传给 D1,规避 VM 数组下标。纯增量,既有键零变。

- [ ] **Step 1: 失败测试(追加到既有 cnc_path 测试文件;取该文件一个已生成非空路径的用例,断言)**

```python
    assert res.start_x_mm == res.g_sx[0]
    assert res.start_y_mm == res.g_sy[0]
```

另在该文件对 result **dict 导出**已有断言的用例里(grep `pass_z_list` 定位),同步断言导出含
`d["start_x_mm"] == res.g_sx[0]` 与 `d["start_y_mm"] == res.g_sy[0]` 两键(键名与 dataclass 字段同名)。

- [ ] **Step 2:** FAIL。
- [ ] **Step 3:** dataclass 加两个 `float` 字段(default 0.0);生成路径处赋 `g_sx[0]/g_sy[0]`;dict 导出处补两键;placeholder 构造保持 0.0。
- [ ] **Step 4:** 本文件全量 PASS(黄金值零回归)。**Step 5: Commit** `feat(cnc_path): 结果携带路径首点 start_x/y_mm — 供对位检查走起点`

---

### Task 8: D1 内环子 operation `photoscrape_align_loop`

**Files:**
- Create: `eit_ptlc/config/operation/03_photoscrape/photoscrape_align_loop.yaml`
- Test: `eit_ptlc/tests/test_align_loop_flow_offline.py`(新建;harness 逐字仿 test_photoscrape_gate_flow_offline.py 的 `_drive`,加 `resolve_script`)

**Interfaces:**
- Consumes: T4 `photoscrape.align_readout`(result.text 等)、T5 三动作。
- Produces: 子脚本 `photoscrape_align_loop`,in vars `start_x_mm/start_y_mm(FLOAT)`、`start_valid(BOOL)`;正常返回=已回零;失败 raise `ALIGN_FAILED`(回零后)。T9/T10 以 `op: run_script` 调用。

- [ ] **Step 1: 写 YAML(完整;`op: comment` 承载设计知识 —— web 回写会剥注释)**

```yaml
schema: ptlc.script/v1
kind: operation
name: photoscrape_align_loop
label: 刮板-对位内环 (通用件)
ui:
  role: helper
  hidden: true
vars:
  - {name: start_x_mm, scope: local, type: FLOAT, io: in, default: 0.0, comment: 路径起点X(机床mm)}
  - {name: start_y_mm, scope: local, type: FLOAT, io: in, default: 0.0, comment: 路径起点Y(机床mm)}
  - {name: start_valid, scope: local, type: BOOL, io: in, default: false, comment: 路径起点可用(cand_valid)}
  - {name: ro,    scope: local, type: DICT,   comment: align_readout 回显(x/y/z/原点/Δ/inspect_z/text)}
  - {name: done,  scope: local, type: BOOL,   default: false}
  - {name: gate,  scope: local, type: STRING, default: ""}
  - {name: dx_mm, scope: local, type: FLOAT,  default: 0.0, comment: 微调步进X(mm, 可负; 先升Z再步进)}
  - {name: dy_mm, scope: local, type: FLOAT,  default: 0.0, comment: 微调步进Y}
body:
  - {op: comment, text: "对位内环 (spec 0716 §6 D1): 纯对位不碰气缸; 大行程前先 align_z(0); 检查高度只发≤2mm微调(PLC硬守卫); 任何失败先回零再抛"}
  - op: try
    body:
      - op: while
        cond: {unop: not, operand: {var: done}}
        max_iter: 500
        body:
          - {op: call, action: photoscrape.align_readout, mode: RUN, assign: {var: ro}}
          - {op: assign, target: {var: gate}, value: {lit: ""}}
          - op: human
            kind: choose
            prompt: {binop: +, left: {lit: "对位检查 — "}, right: {field: {var: ro}, name: text}}
            assign_choice: {var: gate}
            options:
              - {value: go_origin, label: 走原点角}
              - {value: go_start,  label: 走路径起点}
              - {value: z_down,    label: 缓降检查高度}
              - {value: z_up,      label: 升回安全高}
              - {value: jog,       label: 微调(Δx/Δy)}
              - {value: finish,    label: 结束对位}
          - op: if
            cond: {binop: ==, left: {var: gate}, right: {lit: go_origin}}
            then:
              - op: try
                body:
                  - {op: comment, text: "大行程: 先升Z=0(安全位)再走XY; PLC 42 对 Z 非零大目标拒动是兜底"}
                  - {op: call, action: photoscrape.align_z, mode: RUN, args: {z_mm: {lit: 0.0}}}
                  - {op: call, action: photoscrape.align_move, mode: RUN,
                     args: {x_mm: {field: {var: ro}, name: origin_x_mm}, y_mm: {field: {var: ro}, name: origin_y_mm}}}
                catch:
                  - error: "*"
                    body:
                      - {op: comment, text: "走位失败(软限位/PLC拒动): 不退环, 回门重选"}
            elifs:
              - cond: {binop: ==, left: {var: gate}, right: {lit: go_start}}
                body:
                  - op: if
                    cond: {var: start_valid}
                    then:
                      - op: try
                        body:
                          - {op: call, action: photoscrape.align_z, mode: RUN, args: {z_mm: {lit: 0.0}}}
                          - {op: call, action: photoscrape.align_move, mode: RUN,
                             args: {x_mm: {var: start_x_mm}, y_mm: {var: start_y_mm}}}
                        catch:
                          - error: "*"
                            body:
                              - {op: comment, text: "走位失败: 回门"}
                    else:
                      - {op: comment, text: "无可用路径起点(cand_valid=false): 空转回门, 门文案已提示"}
              - cond: {binop: ==, left: {var: gate}, right: {lit: z_down}}
                body:
                  - op: try
                    body:
                      - {op: call, action: photoscrape.align_z, mode: RUN,
                         args: {z_mm: {field: {var: ro}, name: inspect_z_mm}}}
                    catch:
                      - error: "*"
                        body:
                          - {op: comment, text: "缓降被拒(XY不在板区窗): 回门"}
              - cond: {binop: ==, left: {var: gate}, right: {lit: z_up}}
                body:
                  - {op: call, action: photoscrape.align_z, mode: RUN, args: {z_mm: {lit: 0.0}}}
              - cond: {binop: ==, left: {var: gate}, right: {lit: jog}}
                body:
                  - {op: assign, target: {var: dx_mm}, value: {lit: 0.0}}
                  - {op: assign, target: {var: dy_mm}, value: {lit: 0.0}}
                  - op: human
                    kind: input
                    prompt: {lit: "微调步进(mm, 可负; 将先升Z到安全位再步进, 步进后需再「缓降」复查): 留空=0"}
                    fields:
                      - {var: dx_mm, label: ΔX(mm)}
                      - {var: dy_mm, label: ΔY(mm)}
                  - op: try
                    body:
                      - {op: comment, text: "B1修正: 一切XY移动只在Z=0 — 先升Z再步进(低位观察→升Z盲步进→再缓降复查, 迭代收敛)"}
                      - {op: call, action: photoscrape.align_z, mode: RUN, args: {z_mm: {lit: 0.0}}}
                      - {op: call, action: photoscrape.align_move, mode: RUN,
                         args: {x_mm: {binop: +, left: {field: {var: ro}, name: x_mm}, right: {var: dx_mm}},
                                y_mm: {binop: +, left: {field: {var: ro}, name: y_mm}, right: {var: dy_mm}}}}
                    catch:
                      - error: "*"
                        body:
                          - {op: comment, text: "微调被拒(出窗/PLC拒动): 回门"}
              - cond: {binop: ==, left: {var: gate}, right: {lit: finish}}
                body:
                  - {op: assign, target: {var: done}, value: {lit: true}}
            else:
              - {op: comment, text: "空/未知选择: 回门"}
      - {op: comment, text: "正常收尾: 43 自带Z不在0先升Z, 无需先 align_z(0)"}
      - {op: call, action: photoscrape.align_home, mode: RUN}
    catch:
      - error: "*"
        body:
          - {op: comment, text: "对位内环失败: 先回零(刀头绝不悬板上方)再抛给调用方"}
          - {op: call, action: photoscrape.align_home, mode: RUN}
          - {op: raise, error: ALIGN_FAILED, message: {lit: "对位检查失败, 已回零; 详见上一动作错误"}}
```

- [ ] **Step 2: 失败测试(新建 test_align_loop_flow_offline.py;fake executor 对 align_readout 返回固定 readout,记录调用)**

```python
"""对位内环 — VM 端到端离线 (真 photoscrape_align_loop.yaml + 伪执行器)。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.tests.test_vm_debug_offline import wait_status

_LOOP = Path("eit_ptlc/config/operation/03_photoscrape/photoscrape_align_loop.yaml")
READOUT = {"x_mm": 91.0, "y_mm": -75.0, "z_mm": 0.0, "origin_x_mm": 91.24, "origin_y_mm": -75.2,
           "inspect_z_mm": 18.0, "dx_vs_origin_mm": -0.24, "dy_vs_origin_mm": 0.2, "text": "T"}


class AlignExecutor:
    def __init__(self, fail_move=False):
        self.calls, self._fail = [], fail_move

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        self.calls.append((name, dict(params or {})))
        if name == "photoscrape.align_move" and self._fail:
            return ActionResult(action=name, request_id="x", status=ActionStatus.REJECTED,
                                accepted=False, message="软限位拒动(测试注入)", result={})
        res = READOUT if name == "photoscrape.align_readout" else {}
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, message="ok", result=res)


def _drive(replies, terminal, executor=None, start_vars=None):
    async def run():
        ex = executor or AlignExecutor()
        events = []
        c = VmController(executor=ex, res_gate=ResourceGate(), event_sink=events.append)
        s = await c.start(yaml.safe_load(_LOOP.read_text(encoding="utf-8")),
                          start_vars or {}, mode_run="run")
        rid, replied = s["run_id"], set()
        for payload in replies:
            assert await wait_status(c, rid, "WAITING_HUMAN")
            req = [e for e in events if e["type"] == "vm_human_request" and e["req_id"] not in replied][-1]
            replied.add(req["req_id"])
            await c.human_reply(rid, req["req_id"], payload)
        assert await wait_status(c, rid, terminal), c.state(rid)
        return ex
    return asyncio.run(run())


def _names(ex):
    return [c[0] for c in ex.calls]


def test_finish_immediately_homes():
    ex = _drive([{"choice": "finish", "values": {}}], "DONE")
    assert _names(ex) == ["photoscrape.align_readout", "photoscrape.align_home"]


def test_go_origin_lifts_z_then_moves_then_loop():
    ex = _drive([{"choice": "go_origin", "values": {}}, {"choice": "finish", "values": {}}], "DONE")
    n = _names(ex)
    assert n[:3] == ["photoscrape.align_readout", "photoscrape.align_z", "photoscrape.align_move"]
    mv = [c for c in ex.calls if c[0] == "photoscrape.align_move"][0][1]
    assert mv == {"x_mm": 91.24, "y_mm": -75.2}
    assert n[-1] == "photoscrape.align_home"


def test_jog_lifts_z_then_adds_delta_to_actpos():
    ex = _drive([{"choice": "jog", "values": {}},
                 {"choice": "ok", "values": {"dx_mm": "0.5", "dy_mm": "-0.3"}},
                 {"choice": "finish", "values": {}}], "DONE")
    n = _names(ex)
    # B1修正: jog 先 align_z(0) 再 align_move
    assert n.index("photoscrape.align_z") < n.index("photoscrape.align_move")
    z = [c for c in ex.calls if c[0] == "photoscrape.align_z"][0][1]
    assert z == {"z_mm": 0.0}
    mv = [c for c in ex.calls if c[0] == "photoscrape.align_move"][0][1]
    assert round(mv["x_mm"], 3) == 91.5 and round(mv["y_mm"], 3) == -75.3


def test_rejected_move_returns_to_gate_not_fault():
    ex = _drive([{"choice": "go_origin", "values": {}}, {"choice": "finish", "values": {}}],
                "DONE", executor=AlignExecutor(fail_move=True))
    assert _names(ex)[-1] == "photoscrape.align_home"   # 拒动被分支 catch 吞掉, 环存活到 finish


def test_go_start_without_valid_start_stays_in_loop():
    ex = _drive([{"choice": "go_start", "values": {}}, {"choice": "finish", "values": {}}], "DONE")
    assert "photoscrape.align_move" not in _names(ex)
```

- [ ] **Step 3:** 跑 `E:/Anaconda/python.exe -m pytest eit_ptlc/tests/test_align_loop_flow_offline.py -v` → 全 PASS(YAML 先行,测试驱动修 YAML 细节;human input FLOAT 字段 "0.5" 由 `coerce_value` 强转,若断言失败按实际强转行为修 fixture 而非产品)。
- [ ] **Step 4: Commit** `feat(align): D1 对位内环子operation + VM离线全绿 — 走位/缓降/jog/失败回零`

---

### Task 9: D2 独立对刀业务 `photoscrape_tool_align`

**Files:**
- Create: `eit_ptlc/config/operation/03_photoscrape/photoscrape_tool_align.yaml`
- Test: `eit_ptlc/tests/test_align_loop_flow_offline.py`(追加;resolve_script 注入 D1 真 YAML)

**Interfaces:**
- Consumes: D1 子脚本、`photoscrape.locate_cylinder/press_cylinder`(既有 32/33)。
- Produces: 独立可跑 operation(UI role station_task, station photo_scrape);resources `[station:photo_scrape]` 与生产 run 互斥。

- [ ] **Step 1: 写 YAML**

```yaml
schema: ptlc.script/v1
kind: operation
name: photoscrape_tool_align
label: 刮板-对刀(对位检查)
ui:
  role: station_task
  station: photo_scrape
  order: 38
vars:
  - {name: ack, scope: local, type: STRING, default: "", comment: 首门确认选择}
resources: [station:photo_scrape]
body:
  - {op: comment, text: "对刀业务 (spec 0716 §6 D2): 换刀后专跑。首门=唯一防撞板防线; 气缸配对释放, catch 兜底"}
  - op: human
    kind: confirm
    prompt: {lit: "换刀后对刀确认: ① plate_surface_z_mm 已按当前刀更新(未更新则缓降检查高度会撞板!) ② 刮板夹具已人工放入一块板(任意板, 角位置由定位夹具保证)。确认继续?"}
    assign_choice: {var: ack}
  - op: if
    cond: {binop: "!=", left: {var: ack}, right: {lit: ok}}
    then:
      - {op: raise, error: TOOL_ALIGN_CANCELLED, message: {lit: "用户取消对刀; 板未夹持, 无需释放"}}
  - {op: call, action: photoscrape.locate_cylinder, mode: RUN, args: {clamped: {lit: true}}}
  - {op: call, action: photoscrape.press_cylinder,  mode: RUN, args: {pressed: {lit: true}}}
  - op: try
    body:
      - {op: comment, text: "维护场景无路径: start_valid=false, 门内「走路径起点」空转; 自由目标用 微调 累加"}
      - {op: run_script, script: photoscrape_align_loop, inputs: {start_valid: {lit: false}}, outputs: {}}
    catch:
      - error: "*"
        body:
          - {op: comment, text: "对位失败(内环已回零): 释放气缸放板后抛干净中止"}
          - {op: call, action: photoscrape.press_cylinder,  mode: RUN, args: {pressed: {lit: false}}}
          - {op: call, action: photoscrape.locate_cylinder, mode: RUN, args: {clamped: {lit: false}}}
          - {op: raise, error: TOOL_ALIGN_ABORTED, message: {lit: "对刀中止; 已回零并放板"}}
  - {op: call, action: photoscrape.press_cylinder,  mode: RUN, args: {pressed: {lit: false}}}
  - {op: call, action: photoscrape.locate_cylinder, mode: RUN, args: {clamped: {lit: false}}}
```

- [ ] **Step 2: 失败测试(追加;`resolve_script=lambda n: yaml.safe_load(Path(f"eit_ptlc/config/operation/03_photoscrape/{n}.yaml").read_text(encoding="utf-8"))` 传入 VmController)**

```python
def test_tool_align_full_flow_pairs_cylinders():
    ex = _drive_tool([{"choice": "ok", "values": {}},        # 首门确认
                      {"choice": "finish", "values": {}}],   # 内环直接结束
                     "DONE")
    n = _names(ex)
    assert n.count("photoscrape.press_cylinder") == 2 and n.count("photoscrape.locate_cylinder") == 2
    press_args = [c[1]["pressed"] for c in ex.calls if c[0] == "photoscrape.press_cylinder"]
    assert press_args == [True, False]
    assert "photoscrape.align_home" in n


def test_tool_align_cancel_at_confirm_releases_nothing():
    ex = _drive_tool([{"choice": "cancel", "values": {}}], "FAILED")
    assert "photoscrape.locate_cylinder" not in _names(ex)


def test_tool_align_inner_failure_releases_and_aborts():
    # align_home 也失败 → 内环 catch 内的 home 抛 → D2 catch 释放气缸 → FAILED
    ex = _drive_tool([{"choice": "ok", "values": {}}, {"choice": "go_origin", "values": {}}],
                     "FAILED", executor=AlignExecutor(fail_move=True, fail_home=True))
    press_args = [c[1]["pressed"] for c in ex.calls if c[0] == "photoscrape.press_cylinder"]
    assert press_args == [True, False]
```

(`AlignExecutor` 增 `fail_home` 开关:`align_home` 返回 REJECTED;`fail_move=True, fail_home=True` 时 go_origin 分支 catch 吞掉 move 失败回门 —— 故该用例第二门后直接注入 align_z 失败更直接:实现时按"内环真实抛出路径"调整注入点,断言只锁死两条:D2 catch 必释放气缸、终态 FAILED。)

- [ ] **Step 3:** 跑 → 全 PASS(FAILED 终态名以 `wait_status` 既有取值为准,test_vm_debug_offline 中已有失败终态先例,照抄其字符串)。
- [ ] **Step 4: Commit** `feat(align): D2 独立对刀业务 operation — 首门防撞板确认+气缸配对+兜底释放`

---

### Task 10: D3 门环选项 `align`

**Files:**
- Modify: `eit_ptlc/config/operation/03_photoscrape/photoscrape_process.yaml`(options :158-163;elif 链 :168-238)
- Test: `eit_ptlc/tests/test_photoscrape_gate_flow_offline.py`(追加;`_drive` 增 resolve_script 参数)

**Interfaces:**
- Consumes: D1 子脚本、T7 `cnc.start_x_mm/start_y_mm`。
- Produces: 门 options 增 `{value: align, label: 对位检查}`;选后进 D1(气缸不动),返回/失败均回门。既有分支逐字节不动。

- [ ] **Step 1: YAML 改动**

options 列表 `- {value: dispatch, ...}` 之后插:

```yaml
          - {value: align,     label: 对位检查}
```

elif 链中 `reanalyze` 分支之后、`skip` 之前插:

```yaml
          - cond: {binop: ==, left: {var: gate_choice}, right: {lit: align}}
            body:
              - {op: comment, text: "对位检查 (spec 0716 §6 D3): 刀头走位核对刀; 气缸保持压紧; 内环失败已自回零, 此处吞错回门"}
              - op: try
                body:
                  - op: if
                    cond: {var: cand_valid}
                    then:
                      - op: run_script
                        script: photoscrape_align_loop
                        inputs:
                          start_valid: {lit: true}
                          start_x_mm: {field: {var: cnc}, name: start_x_mm}
                          start_y_mm: {field: {var: cnc}, name: start_y_mm}
                        outputs: {}
                    else:
                      - {op: run_script, script: photoscrape_align_loop, inputs: {start_valid: {lit: false}}, outputs: {}}
                catch:
                  - error: "*"
                    body:
                      - {op: comment, text: "对位检查失败(已回零): 回门, 不阻断下发/手绘/中止选择"}
```

- [ ] **Step 2: 测试(harness 微改 + 两用例)**

`_drive` 签名增 `resolve_script=None` 透传 VmController(默认 None 不影响既有用例);新用例:

```python
def _resolve_ps(n):
    import yaml as _y
    return _y.safe_load(Path(f"eit_ptlc/config/operation/03_photoscrape/{n}.yaml").read_text(encoding="utf-8"))


def test_gate_align_option_runs_loop_and_returns_to_gate():
    # manual + 视觉OK: 门1=align → 内环readout门=finish → 回外门 → 门2=dispatch → DONE
    ex, events = _run(_drive("manual", [
        {"choice": "band_01", "values": {"band_id": "band_01"}},   # 选带 input 门(照本文件既有 manual 用例的回复形态)
        {"choice": "align", "values": {}},
        {"choice": "finish", "values": {}},
        {"choice": "dispatch", "values": {}},
    ], "DONE", resolve_script=_resolve_ps))
    n = _names(ex)
    assert "photoscrape.align_readout" in n and "photoscrape.align_home" in n
    assert "photoscrape.press_cylinder" in n                        # 只有段首 true; align 分支不新增气缸调用
    assert [c[1] for c in ex.calls if c[0] == "photoscrape.press_cylinder"] == [{"pressed": True}]
    assert "photoscrape.write_cnc_path" in n                        # 检查完仍正常下发


def test_gate_align_failure_swallowed_back_to_gate():
    # align_z 拒动注入 → 内环catch回零后 raise → D3 catch 吞 → 外门仍可 skip 收尾
    ex, events = _run(_drive("manual", [
        {"choice": "band_01", "values": {"band_id": "band_01"}},
        {"choice": "align", "values": {}},
        {"choice": "z_down", "values": {}},
        {"choice": "skip", "values": {}},
    ], "DONE", executor=AlignRejectingPhotoExecutor(), resolve_script=_resolve_ps))
    assert "photoscrape.scrape_finish" in _names(ex)
```

(`AlignRejectingPhotoExecutor` = PhotoExecutor 子类:`align_z` REJECTED、`align_home` DONE、`align_readout` 返回 READOUT 常量。注意 z_down 分支自带 catch 回门 —— 为让内环真抛,注入点改为 `align_readout` 第二次调用 REJECTED 更简单;实现时以"外门在 align 失败后仍能 skip 收尾"为唯一硬断言。)

- [ ] **Step 3:** 本文件全量 PASS(既有门用例零回归 —— 无 align 回复的用例不进新分支)。
- [ ] **Step 4:** 全套件 `E:/Anaconda/python.exe -m pytest eit_ptlc/tests -q` 全绿。
- [ ] **Step 5: Commit** `feat(align): D3 下发门「对位检查」选项 — run_script 内环, 失败吞错回门, 既有分支零变`

---

### Task 11: PLC 实装(ActionCode 42/43/44 + 5 节点;依赖 T1 worklog)

**Files:** PLC 工程 `eit_ptlc/plc/20260702.project`(经 codesys-mcp 写 POU/GVL/符号配置;改后 XML 重导出同批)

**Interfaces:**
- Consumes: T1 worklog 全部事实;T5 的节点名/动作码契约(**逐字对齐**:`PhotoScrape_Align_TargetX/TargetY/TargetZ`、`PhotoScrape_9X_ActPos/8Y_ActPos/10Z_ActPos`、码 42/43/44)。
- Produces: compile 0 错;真机下装后 align 系动作解禁。

- [ ] **Step 1:** GVL(Host_Computer 组)加 5 变量并挂符号配置(ReadWrite×3 Target, Read 即可但沿组惯例 ReadWrite×3 ActPos;LREAL/REAL 按 T1 记录的组内同类型惯例):

```text
PhotoScrape_Align_TargetX : REAL;   // 对位目标X(mm); host 写, 42 消费
PhotoScrape_Align_TargetY : REAL;
PhotoScrape_Align_TargetZ : REAL;   // 对位目标Z(mm, 正向下); host 只发 {0, 检查高度} 两档, 44 消费
PhotoScrape_9X_ActPos  : LREAL;     // 每扫描回写 fActPosition — 对位回显
PhotoScrape_8Y_ActPos  : LREAL;
PhotoScrape_10Z_ActPos : LREAL;
```

- [ ] **Step 2:** PhotoScrape_L2 动作码 CASE 增三分支(ST 骨架;轴实例名/回零块/软限位常量按 worklog 替换,标 `<worklog>` 处):

```text
42: // align_move — 专动作专用: 不碰 g_数组/收集器轴/气缸/真空
    // Z门(B1修正): 一切XY移动只在10Z零位 — 复用既有互锁哲学(刮板轴10ZDATE.fActPos<6)
    // 前置: 既有互锁"刮板拍照遮光气缸上位"须满足(8Y绝对运动的既有前置, worklog记录)
    IF NOT (刮板轴10ZDATE.fActPos < 6.0) THEN
        ErrorCode := <按站内既有错误码段分配>; (* Z非零禁XY移动 *)
    ELSIF PhotoScrape_Align_TargetX < <worklog:板区Xmin实测> OR PhotoScrape_Align_TargetX > <worklog:板区Xmax实测> OR
          PhotoScrape_Align_TargetY < <worklog:板区Ymin实测> OR PhotoScrape_Align_TargetY > <worklog:板区Ymax实测> THEN
        ErrorCode := <...>; (* 软限位窗外; 数值上机以 ActPos 轴坐标实测, 勿照抄 config *)
    ELSE
        (* Target 与 g_sx/g_sy 同帧(机床mm); 若单轴MC需帧变换在此完成(B1 C2 上机首核) *)
        (* MC_MoveAbsolute 9X/8Y 到 Target, fVelocity=显式保守常量(B1 C4: 无既有ST典型值, 须显式设); 双轴 Done → 终态锁存, 停在原地 *)
    END_IF
43: // align_home — 若 10Z 不在 0 先 MoveAbsolute Z→0, Done 后 9X/8Y 回零(复用 <worklog:回零块>); 终态锁存
44: // align_z — 仅当 9X/8Y 均在板区窗内才许 Target>0(降); MoveAbsolute 10Z→Target, Velocity=<worklog慢速>; 终态锁存
```

终态一律沿 8 站 `IF (NOT Start)` 锁存契约(memory[ptlc-l2-missed-done-freeze])。

- [ ] **Step 3:** 每扫描回写三个 ActPos(PLC_MainPRG 或站 POU 尾部,与 T1 记录的 Rail_ActPos 同型写法)。
- [ ] **Step 4:** `codesys_compile` 0 错;`codesys_save`;XML(`20260702.Device.Application.xml`)重导出同批提交。
- [ ] **Step 5: Commit** `feat(plc): PhotoScrape_L2 对位动作 42/43/44 + Align Target/ActPos 6节点 — Z门/软限位守卫在动作内`

---

### Task 12: 对刀操作手册 + 收尾

**Files:**
- Create: `docs/photoscrape-tool-align-manual.md`
- Modify: spec §10 上机清单核对;memory 由主会话收尾同步

- [ ] **Step 1:** 手册内容(自然语言,中文):业务全流程 = 换刀 → **先改 `plate_surface_z_mm`**(安全前提,首门会再确认)→ UI 跑「刮板-对刀」→ 走原点角 → 缓降 → jog 对准物理板角(= Plan A 标注图金色双圈那个角,点样边)→ 读门顶 Δ 与建议值 → 配置页改 `plate_origin_x/y` → 复跑对位 Δ≈0 验收 → 结束(自动回零放板)。附:检查高度物理含义(板面上方 `align_clearance_mm`)、微调 2mm 限、与包1(受力刮痕/刮宽校验)和对账照片(长期哨兵)的互补关系(spec §9)。
- [ ] **Step 2:** 全套件回归 `E:/Anaconda/python.exe -m pytest eit_ptlc/tests -q` + `cd eit_ptlc/web && npm run build`(若 Plan A 已合入)。
- [ ] **Step 3: Commit** `docs(align): 对刀业务操作手册 — 换刀→标定→验收全流程`

## 上机 pending(合并 + T11 下装后;spec §8)

1. 原点角走位 + 回显对读(门顶 text vs 物理位置);
2. 缓降 + jog 对准物理板角 → Δ 读数与包1 卡尺法交叉验证一次;
3. 路径起点走位 vs 手绘带目测;
4. 修 plate_origin 后复跑 Δ≈0;
5. 故意超窗 / 低位大步长 → 两级拒动(PLC ErrorCode → 门内可见, 回门不 fault);
6. 压头/收集器与检查高度物理干涉核查(spec §7-4)。
