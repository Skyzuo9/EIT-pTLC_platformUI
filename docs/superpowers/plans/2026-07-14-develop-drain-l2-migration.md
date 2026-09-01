# 展缸排液 L2 化迁移 + 原位干燥 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把展缸排液从旧黑盒 (排液完隐式开盖) 迁移为 L2 化形态: 断液 (抽液→吹扫→原位干燥) 与开盖物流拆开, 终态 `Tank_State=98` (盖关待取板), 时长全部上位机可写, 干燥为 run 级 knob。

**Architecture:** PLC 侧重写 `Develop_TankDrain` per-tank FSM (相位 50→55→56→98) 并修缮活派发器 `50_action/Develop_L2` (98 终态/51 收 98/50 非法态拒绝), 拆除 40_Man 死派发器; 主机侧只动契约 YAML + knob 透传; mock PLC 补 develop 排液语义供离线测试。设计真源: `docs/superpowers/specs/2026-07-14-develop-drain-l2-migration-design.md`。

**Tech Stack:** CODESYS ST (经 codesys MCP: `codesys_read_pou`/`codesys_write_pou`/`codesys_compile`/`codesys_save`) · Python 3.13 (asyncua mock, unittest/脚本式离线测试) · ptlc.script/v1 YAML。

## Global Constraints

- PLC 真源工程 = `eit_ptlc/plc/20260702.project`; 所有 PLC 改动经 codesys MCP 完成: read_pou → 按本 plan 的 old/new 片段改文本 → write_pou → `codesys_compile` 必须 **0 errors** → `codesys_save` → 提交 .project 二进制。
- Python 解释器 = `E:/Anaconda/python.exe` (miniforge 不存在, 测试文件 docstring 里的旧路径勿信); 测试从仓库根以 `-m eit_ptlc.tests.<module>` 方式运行。
- **盖子位置不进 `Tank_State`**; 排液 FSM 不触碰盖气缸 (`展缸i气缸j*`); 开盖 = 既有 L2 code 31 (`develop.plate_retract`)。
- 排液 FSM 启动条件 = `Tank_Drain_Enable[i] AND Tank_State[i] ∈ {0, 40}`; 与 `Develop_L2` 派发器 code 50 接受门 (10/90 → REJECT 501) 为**同一契约, 改一处必改另一处** (两处都写交叉注释)。
- Phase B 吹扫段**真空票保持不撤** (`大真空泵站位[i]` 引用计数); Phase A 判据保留废液传感器门控 (真=已走空, 按组共享), 新增每缸硬上限 `Tank_Drain_Cap_S` + `Tank_Drain_CapHit[i]` 锁存。
- 时长通道 4 个 (Host_Computer LREAL 秒 / plc_nodes Double): `Tank_Drain_S`(初值5.0) `Tank_Drain_Cap_S`(120.0) `Tank_Blow_S`(30.0) `Tank_Dry_S`(0.0); 主机 `develop.drain` 可选参数 YAML 默认值与 PLC 初值一致。
- 明确不做 (YAGNI): 多缸机器人调度 / 派发通道 trigger-wait 拆分 / load 路径 L2 化 (`lid_close` 收编) / 湿度传感器闭环 / 氮气气源 / CapHit 的主机事件联动 (只暴露节点)。
- YAML 文件直接用编辑器改 (保留注释); 绝不经 web UI 回写 (会剥光注释)。
- 每个 Task 一次 commit, 提交信息中文 (repo 惯例 `feat(develop): ...` 式), **不 push**。

## 契约总表 (所有 Task 共享)

`Tank_State` 语义 (Int16, ARRAY[1..8]):

```
0  Idle (L2 路径展开期间也是 0)   10 Prepping (legacy)   40 Developing (仅 legacy 写)
50 Draining (Phase A)            55 BlowAir (Phase B)   56 Drying (Phase B', 新)
98 DrainedIdle (阀关/盖关/待取板, code 50 终态, 新)      99 legacy 遗留 (新 FSM 不再产生)
90 Error
```

L2 语义: code 50 = drain→98 (Done 锁存); code 51 = release, 收 {98,99,0} → 写 0; code 31/32 = 开盖/关盖 (纯气缸原子, 无 Tank_State 门); 错误码 102=缸号非法, 501=缸态不可排液, 511=缸态不可释放, 502=排液 FSM Error(90)。

---

### Task 1: 契约层 — plc_nodes.yaml + plc_develop.yaml + develop_unload 注释

**Files:**
- Modify: `eit_ptlc/config/plc_nodes.yaml` (Tank 数组段, 约 :50-54)
- Modify: `eit_ptlc/config/actions/02_develop/plc_develop.yaml` (develop.drain :95-105, release_tank :107-115, plate_retract/extend :117-135)
- Modify: `eit_ptlc/config/operation/02_develop/develop_unload.yaml` (仅注释)

**Interfaces:**
- Produces: PLC 节点名 `Tank_Drain_S / Tank_Drain_Cap_S / Tank_Blow_S / Tank_Dry_S` (Double) 与 `Tank_Drain_CapHit` (Boolean×8) — Task 2 sim 与 Task 4 PLC 声明按此命名; `develop.drain` 参数名 `drain_duration_s / drain_cap_s / blow_s / dry_duration_s` — Task 3 knob 按名对接 `dry_duration_s`。

- [ ] **Step 1: 更新 plc_nodes.yaml 的 Tank 数组段**

把:

```yaml
Tank_State: {type: Int16, array_len: 8, comment: "0=Idle,10=Prepping,40=Developing,50=Draining,99=Done,90=Error"}
```

改为 (并在 `Tank_Drain_Done` 行后追加 5 行新节点):

```yaml
Tank_State: {type: Int16, array_len: 8, comment: "0=Idle,10=Prepping,40=Developing(legacy),50=Draining,55=BlowAir,56=Drying,98=DrainedIdle(盖关待取板),99=legacy遗留,90=Error"}
```

`Tank_Drain_Done` 行后新增:

```yaml
  Tank_Drain_CapHit: {type: Boolean, array_len: 8, comment: "PLC 锁存: Phase A 走硬上限强制进吹扫 (上机复盘直读; 下次排液启动清)"}
  Tank_Drain_S: {type: Double, comment: "排液 Phase A 判据时长 s (组废液线持续走空满此值)"}
  Tank_Drain_Cap_S: {type: Double, comment: "排液 Phase A 每缸硬上限 s (同组并发被邻缸挟持时兜底)"}
  Tank_Blow_S: {type: Double, comment: "排液 Phase B 吹扫时长 s (真空票保持)"}
  Tank_Dry_S: {type: Double, comment: "排液 Phase B' 原位干燥时长 s (0=跳过; 对应 run 级 knob dry_duration_s)"}
```

(缩进与同段其他节点一致, 两空格。)

- [ ] **Step 2: 更新 plc_develop.yaml 三个 action**

`develop.drain` 整块替换为:

```yaml
develop.drain:
  kind: plc_l2
  station: develop
  action_code: 50
  label: 展缸-排液闭环
  desc: 断液序列 抽液(传感器判据+Cap硬上限)→吹扫(真空保持)→原位干燥(dry_duration_s>0), 终态 Tank_State=98 (阀全关/盖保持关/板在缸内待取); 开盖由 code 31 just-in-time 下发, 不释放缸资源。时长参数经通道直透 PLC, 缺省与 PLC 初值一致。
  modes: []
  stall_timeout: 180.0
  action_timeout: 900.0
  params:
    - {name: target_tank, type: int, required: true, label: 目标缸号, min: 1, max: 8, channel: Expand_Target_Tank}
    - {name: drain_duration_s, type: float, required: false, default: 5.0, min: 0.0, max: 600.0, label: 抽液判据时长s, channel: Tank_Drain_S}
    - {name: drain_cap_s, type: float, required: false, default: 120.0, min: 1.0, max: 1800.0, label: 抽液硬上限s, channel: Tank_Drain_Cap_S}
    - {name: blow_s, type: float, required: false, default: 30.0, min: 0.0, max: 600.0, label: 吹扫时长s, channel: Tank_Blow_S}
    - {name: dry_duration_s, type: float, required: false, default: 0.0, min: 0.0, max: 1800.0, label: 原位干燥时长s, channel: Tank_Dry_S}
```

`develop.release_tank` 的 `desc` 改为:

```yaml
  desc: 机器人取板离缸后释放缸资源; PLC 侧收 Tank_State ∈ {98,99,0} → 写 0 (99 仅旧值兼容); 不触发排液硬件。
```

`develop.plate_retract` 的 label/desc 改为:

```yaml
  label: 展缸-开盖(放板缸回原点)
  desc: 放板缸与展缸盖为同一执行器(展缸i气缸j); 回原点=开盖/让位, 放板前与取板前(Tank_State=98)都用它; 纯气缸原子, 无 Tank_State 前置。
```

`develop.plate_extend` 的 label/desc 改为:

```yaml
  label: 展缸-关盖(放板缸到动点)
  desc: 放板缸与展缸盖为同一执行器(展缸i气缸j); 到动点=关盖/夹持到位, 机器人放板后闭合展开腔。
```

- [ ] **Step 3: develop_unload.yaml 注释更新 (结构零改动)**

```yaml
- op: comment
  text: "unload: 开盖 (放板缸/展缸盖同一执行器回原点), 允许机器人取板出缸; 排液终态 Tank_State=98 盖保持关, 此处 just-in-time 开盖"
```

(替换原 "unload: 放板缸回原点 (让位), 允许机器人取板出缸"。)

```yaml
- op: comment
  text: "unload: 机器人取板出缸; Tank_State=98 表示已断液待取板 (板仍在缸内)"
```

(替换原 "unload: 机器人取板出缸; Tank_State=99 表示排液完成但板仍在缸内"。)

- [ ] **Step 4: 跑既有守卫套件确认契约层不破坏**

```bash
cd E:/PHD/PKU/MoGroup/pTLC_platform/EIT_Project-Next
E:/Anaconda/python.exe -m eit_ptlc.tests.test_node_registry_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_pump_contract_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_develop_four_stage_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_plc_l2_acceptance_offline
```

Expected: 全部 0 失败 (acceptance 此时仍是旧用例集, 新节点只增不改不会破坏)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/config/plc_nodes.yaml eit_ptlc/config/actions/02_develop/plc_develop.yaml eit_ptlc/config/operation/02_develop/develop_unload.yaml
git commit -m "feat(develop): 排液契约层 — Tank_State 98/56 语义 + 4时长Double节点 + CapHit数组, drain参数化/开关盖双语义 (spec 2026-07-14)"
```

---

### Task 2: mock PLC develop 排液语义 + 验收测试

**Files:**
- Modify: `eit_ptlc/mock/plc_server.py`
- Test: `eit_ptlc/tests/test_plc_l2_acceptance_offline.py`

**Interfaces:**
- Consumes: Task 1 的节点名 (`Tank_Drain_S` 等 4 通道 + `Tank_Drain_CapHit`)。
- Produces: `run_tank_drain_fsm(server, stop_event, *, tick=0.02)` 协程; `run_l2_fsm(..., develop_tank_semantics: bool = False)` 新 kwarg; 测试注入点 `server._eit_drain_wet_groups: set[int]` (组号 1/2, 模拟废液线持续有液)。Task 4 的 PLC FSM 行为以此 sim 为镜像契约。

- [ ] **Step 1: 先写失败的验收用例 (TDD)**

`test_plc_l2_acceptance_offline.py` 改动三处。

(a) 导入行 (`:20-23` 附近) 增加:

```python
from eit_ptlc.controller.plc_controller import PLCActionError, PLCActionState, PlcController
from eit_ptlc.mock.plc_server import build_mock_server, mock_read, mock_write, run_l2_fsm, run_tank_drain_fsm
```

(替换原有两行同名导入; 注意新增 `PLCActionError` / `mock_write` / `run_tank_drain_fsm`。)

(b) FSM 启动段 (原 `:56-59`) 替换为:

```python
        fsms = [
            asyncio.create_task(run_l2_fsm(server, prefix, stop))
            for prefix in ("Sampling", "Collect")
        ]
        fsms.append(asyncio.create_task(
            run_l2_fsm(server, "Develop", stop, develop_tank_semantics=True)))
        fsms.append(asyncio.create_task(run_tank_drain_fsm(server, stop)))
```

(c) 在 `develop_rinse_mode_flag` 用例之后、`finally` 之前追加新段:

```python
            # ── 展缸排液 v2 (动作码 50): 全相位 50→55→56→98 + 时长通道写入 (spec 2026-07-14) ──
            drain_channels = {
                "Expand_Target_Tank": 3,
                "Tank_Drain_S": 0.05, "Tank_Drain_Cap_S": 1.0,
                "Tank_Blow_S": 0.05, "Tank_Dry_S": 0.05,
            }
            r = await ctrl.execute("develop", 50, drain_channels)
            check("develop_drain_done", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_drain_duration_channels",
                abs(float(await mock_read(server, "Tank_Drain_S")) - 0.05) < 1e-9
                and abs(float(await mock_read(server, "Tank_Dry_S")) - 0.05) < 1e-9,
                f"Drain_S={await mock_read(server, 'Tank_Drain_S')} Dry_S={await mock_read(server, 'Tank_Dry_S')}",
            )
            tanks = await mock_read(server, "Tank_State")
            check("develop_drain_state_98", int(tanks[2]) == 98, str(tanks))
            check(
                "develop_drain_caphit_false",
                not bool((await mock_read(server, "Tank_Drain_CapHit"))[2]),
                str(await mock_read(server, "Tank_Drain_CapHit")),
            )

            # ── 排液释放 (动作码 51): 98 → 0 ──
            r = await ctrl.execute("develop", 51, {"Expand_Target_Tank": 3})
            check("develop_release_done", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_release_state_0",
                int((await mock_read(server, "Tank_State"))[2]) == 0,
                str(await mock_read(server, "Tank_State")),
            )

            # ── Cap 挟持: 组1 废液线持续有液 → Phase A 走硬上限 + CapHit 锁存 ──
            server._eit_drain_wet_groups = {1}
            drain_cap = dict(drain_channels)
            drain_cap["Expand_Target_Tank"] = 2
            drain_cap["Tank_Drain_Cap_S"] = 0.2
            r = await ctrl.execute("develop", 50, drain_cap)
            check("develop_drain_cap_done", r.state is PLCActionState.DONE, str(r))
            check(
                "develop_drain_cap_hit",
                bool((await mock_read(server, "Tank_Drain_CapHit"))[1])
                and int((await mock_read(server, "Tank_State"))[1]) == 98,
                f"CapHit={await mock_read(server, 'Tank_Drain_CapHit')} State={await mock_read(server, 'Tank_State')}",
            )
            server._eit_drain_wet_groups = set()
            r = await ctrl.execute("develop", 51, {"Expand_Target_Tank": 2})
            check("develop_release_after_cap", r.state is PLCActionState.DONE, str(r))

            # ── 非法态拒绝: 缸4 置 10 (Prepping) → 50 REJECT 501 / 51 REJECT 511 ──
            tanks = list(await mock_read(server, "Tank_State"))
            tanks[3] = 10
            await mock_write(server, "Tank_State", tanks)
            try:
                await ctrl.execute("develop", 50, {"Expand_Target_Tank": 4})
                check("develop_drain_reject_501", False, "缸态 10 未被拒绝")
            except PLCActionError as e:
                check(
                    "develop_drain_reject_501",
                    e.result.state is PLCActionState.REJECTED and e.result.error_code == 501,
                    str(e.result),
                )
            try:
                await ctrl.execute("develop", 51, {"Expand_Target_Tank": 4})
                check("develop_release_reject_511", False, "缸态 10 未被拒绝")
            except PLCActionError as e:
                check(
                    "develop_release_reject_511",
                    e.result.state is PLCActionState.REJECTED and e.result.error_code == 511,
                    str(e.result),
                )
            tanks[3] = 0
            await mock_write(server, "Tank_State", tanks)
```

同时把文件头 docstring 的运行行改为 `E:/Anaconda/python.exe -m eit_ptlc.tests.test_plc_l2_acceptance_offline`, 功能描述追加一行 "展缸排液 v2 全相位/Cap挟持/非法态拒绝 (develop 排液语义桥)"。

- [ ] **Step 2: 跑测试确认失败**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_plc_l2_acceptance_offline
```

Expected: FAIL — `ImportError: cannot import name 'run_tank_drain_fsm'`。

- [ ] **Step 3: 实现 mock 侧 develop 排液语义**

`eit_ptlc/mock/plc_server.py` 三处改动。

(a) `run_l2_fsm` 签名增加 kwarg (在 `mirror_on_done` 参数后):

```python
    mirror_on_done: tuple[tuple[str, str], ...] = (),
    develop_tank_semantics: bool = False,
```

docstring 参数段补一行:

```
        develop_tank_semantics: True 时 code 50/51 走 develop 排液语义桥 (_develop_drain_bridge),
                    与真 PLC Develop_L2 派发器同契约 (spec 2026-07-14); 其余码不受影响.
```

(b) `run_l2_fsm` 主体在写完 `_L2_RUNNING` 之后、`if code in hang_codes:` 之前插入:

```python
                if develop_tank_semantics and code in (50, 51):
                    await _develop_drain_bridge(server, prefix, seq, code, stop_event, tick)
                    prev_start = start
                    await asyncio.sleep(tick)
                    continue
```

(c) 文件末尾追加两个新协程 (完整代码):

```python
# ── develop 排液语义 (spec 2026-07-14-develop-drain-l2-migration) ──
_TANK_DRAIN_START_STATES = (0, 40)   # 0=L2路径, 40=legacy路径; 与真 PLC FSM 同契约


async def _develop_drain_bridge(server, prefix: str, seq: int, code: int,
                                stop_event, tick: float) -> None:
    """develop L2 桥: code 50 桥接 Tank_Drain 数组等排液 FSM, code 51 释放缸.

    契约 (与真 PLC Develop_L2 派发器一致):
        50: Tank_State ∈ {10,90} → REJECTED 501; ∈ {98,99} → 幂等 DONE;
            其余置 Tank_Drain_Enable 并等 run_tank_drain_fsm 推到 98/Done (90 → ERROR 502)。
        51: Tank_State ∈ {98,99,0} → 清 Enable/Done + 写 0 → DONE; 否则 REJECTED 511。
    真 PLC 在 Start 落沿清 Enable; sim 在终态前顺手清, 时序差异离线无影响。
    """
    import asyncio
    tank = int(await mock_read(server, "Expand_Target_Tank"))
    idx = tank - 1
    term, err, safe = _L2_DONE, 0, 10
    if not (1 <= tank <= 8):
        term, err, safe = _L2_REJECTED, 102, 0
    elif code == 50:
        st = int((await mock_read(server, "Tank_State"))[idx])
        if st in (10, 90):
            term, err, safe = _L2_REJECTED, 501, 0
        elif st in (98, 99):
            term, err, safe = _L2_DONE, 0, 10   # 幂等直通
        else:
            enables = list(await mock_read(server, "Tank_Drain_Enable"))
            enables[idx] = True
            await mock_write(server, "Tank_Drain_Enable", enables)
            while not stop_event.is_set():
                st = int((await mock_read(server, "Tank_State"))[idx])
                await mock_write(server, f"{prefix}_L2_Step", st)
                done = bool((await mock_read(server, "Tank_Drain_Done"))[idx])
                if st == 90:
                    term, err, safe = _L2_ERROR, 502, 90
                    break
                if st in (98, 99) or done:
                    term, err, safe = _L2_DONE, 0, 10
                    break
                await asyncio.sleep(tick)
            enables = list(await mock_read(server, "Tank_Drain_Enable"))
            enables[idx] = False
            await mock_write(server, "Tank_Drain_Enable", enables)
    else:  # code == 51
        states = list(await mock_read(server, "Tank_State"))
        if int(states[idx]) in (98, 99, 0):
            enables = list(await mock_read(server, "Tank_Drain_Enable"))
            dones = list(await mock_read(server, "Tank_Drain_Done"))
            enables[idx] = False
            dones[idx] = False
            states[idx] = 0
            await mock_write(server, "Tank_Drain_Enable", enables)
            await mock_write(server, "Tank_Drain_Done", dones)
            await mock_write(server, "Tank_State", states)
        else:
            term, err, safe = _L2_REJECTED, 511, 0
    await mock_write(server, f"{prefix}_L2_ErrorCode", err)
    await mock_write(server, f"{prefix}_L2_SafeState", safe)
    await mock_write(server, f"{prefix}_L2_Retryable", term == _L2_REJECTED)
    await mock_write(server, f"{prefix}_L2_CompletedSeq", seq)
    await mock_write(server, f"{prefix}_L2_State", term)


async def run_tank_drain_fsm(server, stop_event, *, tick: float = 0.02) -> None:
    """模拟 Develop_TankDrain per-tank 排液 FSM (spec 2026-07-14).

    相位: Enable ∧ State∈{0,40} → 50 → (判据 Tank_Drain_S / 挟持走 Tank_Drain_Cap_S
    并锁存 CapHit) → 55 → (Tank_Blow_S) → 56 → (Tank_Dry_S; 0=一拍直通) → 98 + Done。
    Enable 撤销: 清 Done; 50/55/56/90 安全归位到 0 (98 为静止终态不动)。
    时长直读 Tank_*_S 节点 (测试写小值, 无需时间缩放)。
    传感器挟持注入: server._eit_drain_wet_groups = {1} 表示组1 (缸1-4) 废液线持续
    "有液", 该组缸 Phase A 无法经判据完成, 只能走硬上限。
    """
    import asyncio
    import time
    phase_t0 = [0.0] * 9   # 下标 1..8
    while not stop_event.is_set():
        try:
            enables = list(await mock_read(server, "Tank_Drain_Enable"))
            states = list(await mock_read(server, "Tank_State"))
            dones = list(await mock_read(server, "Tank_Drain_Done"))
            caphits = list(await mock_read(server, "Tank_Drain_CapHit"))
            drain_s = float(await mock_read(server, "Tank_Drain_S"))
            cap_s = float(await mock_read(server, "Tank_Drain_Cap_S"))
            blow_s = float(await mock_read(server, "Tank_Blow_S"))
            dry_s = float(await mock_read(server, "Tank_Dry_S"))
            wet_groups = getattr(server, "_eit_drain_wet_groups", set())
            changed = False
            for i in range(1, 9):
                idx = i - 1
                st = int(states[idx])
                if not enables[idx]:
                    if dones[idx]:
                        dones[idx] = False
                        changed = True
                    if st in (50, 55, 56, 90):
                        states[idx] = 0
                        changed = True
                    continue
                if st in _TANK_DRAIN_START_STATES:
                    states[idx] = 50
                    caphits[idx] = False
                    phase_t0[i] = time.monotonic()
                    changed = True
                elif st == 50:
                    elapsed = time.monotonic() - phase_t0[i]
                    group = 1 if i <= 4 else 2
                    if group in wet_groups:
                        if elapsed >= cap_s:          # 挟持 → 硬上限兜底
                            caphits[idx] = True
                            states[idx] = 55
                            phase_t0[i] = time.monotonic()
                            changed = True
                    elif elapsed >= drain_s:          # 判据: 持续走空满时长
                        states[idx] = 55
                        phase_t0[i] = time.monotonic()
                        changed = True
                elif st == 55:
                    if time.monotonic() - phase_t0[i] >= blow_s:
                        states[idx] = 56
                        phase_t0[i] = time.monotonic()
                        changed = True
                elif st == 56:
                    if time.monotonic() - phase_t0[i] >= dry_s:
                        states[idx] = 98
                        dones[idx] = True
                        changed = True
            if changed:
                await mock_write(server, "Tank_State", [int(x) for x in states])
                await mock_write(server, "Tank_Drain_Done", [bool(x) for x in dones])
                await mock_write(server, "Tank_Drain_CapHit", [bool(x) for x in caphits])
        except Exception:
            log.debug("[MockPLC] TankDrain FSM tick 异常", exc_info=True)
        await asyncio.sleep(tick)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_plc_l2_acceptance_offline
```

Expected: 输出末尾 `失败 0` (新增约 10 个 PASS 用例)。

- [ ] **Step 5: 回归 mock 消费者**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_plc_controller_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_stations_l2_offline
```

Expected: 全绿 (新 kwarg 有默认值, 既有调用零影响)。

- [ ] **Step 6: Commit**

```bash
git add eit_ptlc/mock/plc_server.py eit_ptlc/tests/test_plc_l2_acceptance_offline.py
git commit -m "test(develop): mock PLC 补排液 per-tank FSM + L2 语义桥 — 全相位50/55/56→98, Cap挟持锁存, 501/511拒绝 (spec 2026-07-14)"
```

---

### Task 3: run 级 knob `dry_duration_s` + VM/结构级测试

**Files:**
- Modify: `eit_ptlc/config/operation/02_develop/develop_execute.yaml`
- Test: `eit_ptlc/tests/test_develop_auto_drain_flow_offline.py`

**Interfaces:**
- Consumes: Task 1 的 `develop.drain` 参数 `dry_duration_s` (float, default 0.0)。
- Produces: develop_execute 的 knob 变量 `dry_duration_s` (REAL, ui 组"展开控制") — 运行前面板与 override 注入按此名。

- [ ] **Step 1: 先写失败的测试 (TDD)**

`test_develop_auto_drain_flow_offline.py` 的 `AutoDrainFlowTests` 类内追加两个方法 (文件已有 `_load` / `SeqExecutor` / `VmThread` 基建, 见既有 `_run_execute`):

```python
    def test_dry_duration_knob_passthrough(self) -> None:
        """knob dry_duration_s 经 override 注入后必须透传到 develop.drain args."""
        docs = {n: _load(n) for n in ("develop_execute", "develop_standby", "rail_move_safe")}
        ex = SeqExecutor([
            {"status": "reached", "front_percent": 66.0, "threshold": 65.0,
             "stage": "t1", "elapsed_s": 100.0, "reason": ""},
            {"status": "reached", "front_percent": 81.0, "threshold": 80.0,
             "stage": "t2", "elapsed_s": 40.0, "reason": ""},
        ])
        thread = VmThread(docs["develop_execute"], executor=ex, res_gate=ResourceGate(),
                          resolve_script=lambda n: docs[n],
                          overrides={"auto_drain": True, "dry_duration_s": 45.0})
        status = asyncio.run(thread.run())
        self.assertIs(status, VmStatus.DONE)
        name, args = ex.calls[-1]
        self.assertEqual(name, "develop.drain")
        self.assertEqual(dict(args).get("dry_duration_s"), 45.0)

    def test_drain_calls_and_unload_order_structural(self) -> None:
        """结构级: 两分支 drain 都带 dry_duration_s 变量引用; unload 序 = 开盖→取板→释放."""
        def walk(nodes):
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                if n.get("op") == "call" and n.get("action") == "develop.drain":
                    yield n
                for key in ("then", "else", "body"):
                    if isinstance(n.get(key), list):
                        yield from walk(n[key])
        execute = _load("develop_execute")
        drains = list(walk(execute["body"]))
        self.assertEqual(len(drains), 2, "develop_execute 应有 auto/manual 两处 drain")
        for node in drains:
            self.assertEqual(node["args"].get("dry_duration_s"), {"var": "dry_duration_s"})
        knobs = [v for v in execute["vars"] if v["name"] == "dry_duration_s"]
        self.assertEqual(len(knobs), 1)
        self.assertTrue(isinstance(knobs[0].get("ui"), dict), "dry_duration_s 必须是 knob (带 ui)")
        unload = _load("develop_unload")
        names = [n.get("action") or n.get("script")
                 for n in unload["body"] if n.get("op") in ("call", "run_script")]
        self.assertEqual(names, ["develop.plate_retract", "robot_tank_pick", "develop.release_tank"])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_develop_auto_drain_flow_offline
```

Expected: 2 个新用例 FAIL (drain args 缺 dry_duration_s / vars 无该 knob), 既有 3 用例 PASS。

- [ ] **Step 3: develop_execute.yaml 加 knob 并透传**

`vars:` 段 `wl_result` 之前插入:

```yaml
- name: dry_duration_s
  scope: local
  type: FLOAT   # 勘误: VM var 类型系统无 REAL (见 vm/expr.py VAR_TYPES); 初稿误写 REAL

  io: in
  default: 0.0
  comment: 排液后原位干燥时长秒 (0=跳过; 直透 PLC Tank_Dry_S; 气源=压缩空气, 挥发/氧敏感样品慎开)
  ui:
    label: 原位干燥时长(s)
    group: 展开控制
    min: 0.0
    max: 1800.0
```

(若 Step 4 的测试/加载因 schema 拒绝 `ui.min/max` 报错, 降级为仅 label/group —
范围校验由 action 参数层的 min/max 兜底, 语义不丢。)

auto 分支与 manual (else) 分支的两处 `develop.drain` 调用 args 都改为:

```yaml
    args:
      target_tank:
        var: tank
      dry_duration_s:
        var: dry_duration_s
```

段首总注释 (`op: comment` 第一条) 末尾追加一句: `排液终态 Tank_State=98 (盖关待取板), 开盖在 unload 段 just-in-time。`

- [ ] **Step 4: 跑测试确认通过 + knob 面板回归**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_develop_auto_drain_flow_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_knob_override_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_develop_four_stage_offline
```

Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/config/operation/02_develop/develop_execute.yaml eit_ptlc/tests/test_develop_auto_drain_flow_offline.py
git commit -m "feat(develop): dry_duration_s run级knob — 原位干燥时长透传至 develop.drain (默认0=跳过, 按样品类型选择开)"
```

---

### Task 4: PLC — Host_Computer 声明 + Develop_TankDrain FSM v2 重写

**Files:**
- Modify (经 codesys MCP): `Application/20_变量Date/Host_Computer` (declaration)
- Modify (经 codesys MCP): `Application/40_Man/Develop_TankDrain` (declaration) 与其子 POU `A50_Expand_liquid_discharge_排液` (implementation)
- 载体: `eit_ptlc/plc/20260702.project` (codesys_save 后提交)

**Interfaces:**
- Consumes: Task 1 的通道命名 (Host_Computer 变量名必须与 plc_nodes.yaml 完全一致)。
- Produces: FSM 行为契约 = Task 2 sim 的镜像 (相位/门/CapHit); Task 5 派发器依赖终态 98 与启动条件 {0,40}。

流程: 每处先 `codesys_read_pou` 取当前文本 → 按下述 old/new 片段改 → `codesys_write_pou` 写回 → 最后统一 `codesys_compile`。

- [ ] **Step 1: Host_Computer 声明更新 (4 处)**

(a) 删除旧时长变量 — 把这两行 (含其上方的 GrpComment 注释块"每缸排液定时器(后续可替换为传感器判断)"保留在 DrainTimer 上):

```
	DrainDuration: TIME := TIME#5s0ms;
```

替换为 (新时长组 + CapHit; LREAL 秒, 与 plc_nodes.yaml Double 对应):

```
	// ══ 排液时长参数 v2 (LREAL 秒; 上位机派发 code 50 前经同名通道写入; spec 2026-07-14) ══
	Tank_Drain_S: LREAL := 5.0;        // Phase A 判据: 组废液线持续走空满此时长
	Tank_Drain_Cap_S: LREAL := 120.0;  // Phase A 每缸硬上限 (同组并发被邻缸挟持时兜底)
	Tank_Blow_S: LREAL := 30.0;        // Phase B 吹扫时长 (真空票保持)
	Tank_Dry_S: LREAL := 0.0;          // Phase B' 原位干燥时长 (0=一扫描直通; run级knob dry_duration_s)
	// PLC→PC: Phase A 走硬上限强制进吹扫的锁存 (下次排液启动清; 上位机复盘直读)
	Tank_Drain_CapHit: ARRAY[1..8] OF BOOL;
```

(b) `Tank_State` 的注释块 (GrpComment 与 // 两份都改) 状态清单改为:

```
	//   0  = Idle（空闲，可分配; L2 路径展开期间也是 0）
	//   10 = Prepping（准备中，legacy）
	//   40 = Developing（展开中，仅 legacy 路径写入）
	//   50 = Draining（抽液 Phase A）
	//   55 = BlowAir（吹扫 Phase B，真空保持）
	//   56 = Drying（原位干燥 Phase B'）
	//   98 = DrainedIdle（已断液，阀全关/盖关/板在缸内待取；code 50 终态）
	//   99 = legacy 遗留（旧 FSM"排液完成+盖开"；新 FSM 不再产生）
	//   90 = Error（故障）
```

(c) `Tank_Drain_Enable` 的注释 "前置条件：Tank_State[i]=40" 改为 "前置条件：Tank_State[i] ∈ {0, 40} (0=L2 路径, 40=legacy 路径)"。

(d) 其余变量一律不动。

- [ ] **Step 2: Develop_TankDrain 声明重写**

整个 VAR 块替换为 (删除死变量 anyDraining/展开step/TON_3/TON_4/BlowDuration; DrainTimer 仍在 Host_Computer 全局):

```
PROGRAM Develop_TankDrain
VAR
	i: INT;                          // 循环索引
	BlowTimer: ARRAY[1..8] OF TON;   // Phase B 吹扫定时
	CapTimer: ARRAY[1..8] OF TON;    // Phase A 硬上限看门狗
	DryTimer: ARRAY[1..8] OF TON;    // Phase B' 原位干燥定时
END_VAR
```

(implementation 仍为一行 `A50_Expand_liquid_discharge_排液();`, 不动。)

- [ ] **Step 3: A50_Expand_liquid_discharge_排液 实现整体重写**

implementation 全文替换为:

```
// ══════════════════════════════════════════════════════════════
// 排液控制程序 v2 (per-tank 并行 FSM, 每扫描调用) — spec 2026-07-14 L2化迁移+原位干燥
// ══════════════════════════════════════════════════════════════
// 相位: 50 抽液 → 55 吹扫 → 56 原位干燥 → 98 DrainedIdle (阀全关/盖保持关/Done锁存)
// 时长 (LREAL 秒, Host_Computer 全局, 上位机派发 code 50 前写):
//   Tank_Drain_S     Phase A 判据: 组废液线持续走空满此时长
//   Tank_Drain_Cap_S Phase A 每缸硬上限: 同组并发被邻缸挟持时兜底, 锁存 Tank_Drain_CapHit[i]
//   Tank_Blow_S      Phase B 吹扫时长 (真空票保持不撤 — 主动贯通气流, v2 变更)
//   Tank_Dry_S       Phase B' 原位干燥时长 (0 = 一个扫描周期直通)
// 启动: Tank_Drain_Enable[i] AND Tank_State[i] ∈ {0, 40} (0=L2路径, 40=legacy路径)
//   ⚠ 与 50_action/Develop_L2 派发器 code 50 接受门 (10/90=REJECT 501) 为同一契约, 改一处必改另一处
// 盖(展缸i气缸j)本程序不再触碰: 开盖 = L2 code 31 (A31_放板缸回原点), 由主机 just-in-time 编排
// 传感器: 溶剂废液检测传感器 TRUE=废液管已走空; 按组共享 (缸1-4/5-8); 邻缸有液只会延迟判据不会伪造
// ══════════════════════════════════════════════════════════════

// ══ 急停联锁 ══
IF NOT 急停 THEN
    FOR i := 1 TO 8 DO
        IF (Tank_State[i] = 50) OR (Tank_State[i] = 55) OR (Tank_State[i] = 56) THEN
            Tank_State[i] := 90;
        END_IF
        DrainTimer[i](IN := FALSE, PT := T#0S);
        CapTimer[i](IN := FALSE, PT := T#0S);
        BlowTimer[i](IN := FALSE, PT := T#0S);
        DryTimer[i](IN := FALSE, PT := T#0S);
        大真空泵站位[i] := FALSE;
        CASE i OF
            1: 展缸1排液电池阀1自动 := FALSE; 展缸1吹气电池阀1自动 := FALSE;
            2: 展缸1排液电池阀2自动 := FALSE; 展缸1吹气电池阀2自动 := FALSE;
            3: 展缸1排液电池阀3自动 := FALSE; 展缸1吹气电池阀3自动 := FALSE;
            4: 展缸1排液电池阀4自动 := FALSE; 展缸1吹气电池阀4自动 := FALSE;
            5: 展缸2排液电池阀1自动 := FALSE; 展缸2吹气电池阀1自动 := FALSE;
            6: 展缸2排液电池阀2自动 := FALSE; 展缸2吹气电池阀2自动 := FALSE;
            7: 展缸2排液电池阀3自动 := FALSE; 展缸2吹气电池阀3自动 := FALSE;
            8: 展缸2排液电池阀4自动 := FALSE; 展缸2吹气电池阀4自动 := FALSE;
        END_CASE
    END_FOR
    大真空泵站位[0] := FALSE;
    RETURN;
END_IF

// ══ 主循环: 逐缸并行 FSM ══
FOR i := 1 TO 8 DO
    // 定时器每扫描调用 (TON 语义: IN 断开即复位, 天然实现"持续满足"判据)
    DrainTimer[i](IN := (Tank_State[i] = 50) AND (((i > 4) AND 展缸2溶剂废液检测传感器) OR ((i < 5) AND 展缸1溶剂废液检测传感器)),
                  PT := LREAL_TO_TIME(Tank_Drain_S * 1000.0));
    CapTimer[i](IN := (Tank_State[i] = 50), PT := LREAL_TO_TIME(Tank_Drain_Cap_S * 1000.0));
    BlowTimer[i](IN := (Tank_State[i] = 55), PT := LREAL_TO_TIME(Tank_Blow_S * 1000.0));
    DryTimer[i](IN := (Tank_State[i] = 56), PT := LREAL_TO_TIME(Tank_Dry_S * 1000.0));

    IF NOT Tank_Drain_Enable[i] THEN
        // ── 场景 1: PC 撤销 Enable → 复位 Done (握手) + 中止安全归位 (98 为静止终态不动) ──
        Tank_Drain_Done[i] := FALSE;
        IF (Tank_State[i] = 50) OR (Tank_State[i] = 55) OR (Tank_State[i] = 56) OR (Tank_State[i] = 90) THEN
            大真空泵站位[i] := FALSE;
            CASE i OF
                1: 展缸1排液电池阀1自动 := FALSE; 展缸1吹气电池阀1自动 := FALSE;
                2: 展缸1排液电池阀2自动 := FALSE; 展缸1吹气电池阀2自动 := FALSE;
                3: 展缸1排液电池阀3自动 := FALSE; 展缸1吹气电池阀3自动 := FALSE;
                4: 展缸1排液电池阀4自动 := FALSE; 展缸1吹气电池阀4自动 := FALSE;
                5: 展缸2排液电池阀1自动 := FALSE; 展缸2吹气电池阀1自动 := FALSE;
                6: 展缸2排液电池阀2自动 := FALSE; 展缸2吹气电池阀2自动 := FALSE;
                7: 展缸2排液电池阀3自动 := FALSE; 展缸2吹气电池阀3自动 := FALSE;
                8: 展缸2排液电池阀4自动 := FALSE; 展缸2吹气电池阀4自动 := FALSE;
            END_CASE
            Tank_State[i] := 0;
        END_IF
    ELSIF (Tank_State[i] = 0) OR (Tank_State[i] = 40) THEN
        // ── 场景 2: 启动 Phase A — 拿泵票 + 开排液阀 (⚠ 启动门与派发器同契约) ──
        大真空泵站位[i] := TRUE;
        Tank_Drain_CapHit[i] := FALSE;
        CASE i OF
            1: 展缸1排液电池阀1自动 := TRUE;
            2: 展缸1排液电池阀2自动 := TRUE;
            3: 展缸1排液电池阀3自动 := TRUE;
            4: 展缸1排液电池阀4自动 := TRUE;
            5: 展缸2排液电池阀1自动 := TRUE;
            6: 展缸2排液电池阀2自动 := TRUE;
            7: 展缸2排液电池阀3自动 := TRUE;
            8: 展缸2排液电池阀4自动 := TRUE;
        END_CASE
        Tank_State[i] := 50;
    ELSIF Tank_State[i] = 50 THEN
        // ── 场景 3: Phase A 完成 — 判据满足或硬上限兜底 → 开吹气阀 (排液阀保持, 真空票保持) ──
        IF DrainTimer[i].Q OR CapTimer[i].Q THEN
            IF CapTimer[i].Q AND (NOT DrainTimer[i].Q) THEN
                Tank_Drain_CapHit[i] := TRUE;   // 判据未满足被迫进吹扫 (同组挟持/砂芯残液偏多), 上位机复盘
            END_IF
            CASE i OF
                1: 展缸1吹气电池阀1自动 := TRUE;
                2: 展缸1吹气电池阀2自动 := TRUE;
                3: 展缸1吹气电池阀3自动 := TRUE;
                4: 展缸1吹气电池阀4自动 := TRUE;
                5: 展缸2吹气电池阀1自动 := TRUE;
                6: 展缸2吹气电池阀2自动 := TRUE;
                7: 展缸2吹气电池阀3自动 := TRUE;
                8: 展缸2吹气电池阀4自动 := TRUE;
            END_CASE
            Tank_State[i] := 55;
        END_IF
    ELSIF Tank_State[i] = 55 THEN
        // ── 场景 4: Phase B 吹扫 — 气路贯通 (吹入→废液线), 真空票保持 (v2: 不再撤票) ──
        IF BlowTimer[i].Q THEN
            Tank_State[i] := 56;   // 干燥段气路与吹扫相同; Tank_Dry_S=0 时 DryTimer PT=0 下扫描即 Q
        END_IF
    ELSIF Tank_State[i] = 56 THEN
        // ── 场景 5: Phase B' 原位干燥完成 → 收尾: 关阀撤票, 盖不动, 终态 98 ──
        IF DryTimer[i].Q THEN
            大真空泵站位[i] := FALSE;
            CASE i OF
                1: 展缸1排液电池阀1自动 := FALSE; 展缸1吹气电池阀1自动 := FALSE;
                2: 展缸1排液电池阀2自动 := FALSE; 展缸1吹气电池阀2自动 := FALSE;
                3: 展缸1排液电池阀3自动 := FALSE; 展缸1吹气电池阀3自动 := FALSE;
                4: 展缸1排液电池阀4自动 := FALSE; 展缸1吹气电池阀4自动 := FALSE;
                5: 展缸2排液电池阀1自动 := FALSE; 展缸2吹气电池阀1自动 := FALSE;
                6: 展缸2排液电池阀2自动 := FALSE; 展缸2吹气电池阀2自动 := FALSE;
                7: 展缸2排液电池阀3自动 := FALSE; 展缸2吹气电池阀3自动 := FALSE;
                8: 展缸2排液电池阀4自动 := FALSE; 展缸2吹气电池阀4自动 := FALSE;
            END_CASE
            Tank_Drain_Done[i] := TRUE;
            Tank_State[i] := 98;
        END_IF
    END_IF
END_FOR
```

- [ ] **Step 4: 编译验证**

```
codesys_compile
```

Expected: 0 errors。若报 `LREAL_TO_TIME` 未定义, 改用 `DINT_TO_TIME(LREAL_TO_DINT(Tank_Drain_S * 1000.0))` 重试 (InoProShop 转换函数命名差异)。

- [ ] **Step 5: 保存工程 + 提交**

```
codesys_save
```

```bash
git add eit_ptlc/plc/20260702.project
git commit -m "feat(plc): Develop_TankDrain v2 — 相位50/55/56→98盖关终态, 吹扫真空保持, 传感器判据+Cap硬上限锁存, 时长LREAL通道化 (spec 2026-07-14)"
```

---

### Task 5: PLC — Develop_L2 派发器修缮 + 拆除 40_Man 死派发器

**Files:**
- Modify (经 codesys MCP): `Application/50_action/Develop_L2` (implementation, 4 个片段)
- Modify (经 codesys MCP): `Application/40_Man/Expand_process_展开流程` (implementation, 1 个片段)
- 载体: `eit_ptlc/plc/20260702.project`

**Interfaces:**
- Consumes: Task 4 的终态 98 与启动门 {0,40}; 契约总表错误码 501/511。
- Produces: 派发器行为与 Task 2 sim `_develop_drain_bridge` 完全一致 (host 侧离线测试即其守卫)。

- [ ] **Step 1: Develop_L2 implementation 片段 A — accept CASE 50**

read_pou 后, 把:

```
					50:
						IF Tank_State[DrainTank] = 99 THEN
							Develop_L2_SafeState := 10;
							Develop_L2_State     := 10;   (* RUNNING; 幂等: 缸已排空(99) 直接完成 *)
						ELSE
							Tank_Drain_Enable[DrainTank] := TRUE;  (* 排液按请求执行, 移除 Tank_State=40 前置 *)
							Develop_L2_SafeState := 0;
							Develop_L2_State     := 10;   (* RUNNING *)
						END_IF
```

改为:

```
					50:
						(* 接受门与 Develop_TankDrain 启动条件 {0,40} 为同一契约, 改一处必改另一处:
						   10/90 拒绝; 98/99 幂等直通; 0/40 新起排液; 50/55/56 置 Enable 无害=重挂在途 (恢复向导 reattach) *)
						IF (Tank_State[DrainTank] = 10) OR (Tank_State[DrainTank] = 90) THEN
							Develop_L2_ErrorCode    := 501;  (* 缸态不可排液 (Prepping/Error) *)
							Develop_L2_Retryable    := TRUE;
							Develop_L2_CompletedSeq := Develop_L2_AcceptedSeq;
							Develop_L2_State        := 30;   (* REJECTED *)
						ELSIF (Tank_State[DrainTank] = 98) OR (Tank_State[DrainTank] = 99) THEN
							Develop_L2_SafeState := 10;
							Develop_L2_State     := 10;   (* RUNNING; 幂等: 缸已排空 直接完成 *)
						ELSE
							Tank_Drain_Enable[DrainTank] := TRUE;
							Develop_L2_SafeState := 0;
							Develop_L2_State     := 10;   (* RUNNING *)
						END_IF
```

- [ ] **Step 2: 片段 B — accept CASE 51 收 98**

```
					51:
						IF (Tank_State[DrainTank] = 99) OR (Tank_State[DrainTank] = 0) THEN
```

改为:

```
					51:
						IF (Tank_State[DrainTank] = 98) OR (Tank_State[DrainTank] = 99) OR (Tank_State[DrainTank] = 0) THEN
```

- [ ] **Step 3: 片段 C — RUNNING 50 完成判据收 98**

```
				ELSIF (Tank_State[DrainTank] = 99) OR Tank_Drain_Done[DrainTank] THEN
```

改为:

```
				ELSIF (Tank_State[DrainTank] = 98) OR (Tank_State[DrainTank] = 99) OR Tank_Drain_Done[DrainTank] THEN
```

- [ ] **Step 4: 片段 D — RUNNING 51 收 98**

RUNNING 分支 `51:` 段内的:

```
				IF (Tank_State[DrainTank] = 99) OR (Tank_State[DrainTank] = 0) THEN
```

改为:

```
				IF (Tank_State[DrainTank] = 98) OR (Tank_State[DrainTank] = 99) OR (Tank_State[DrainTank] = 0) THEN
```

write_pou 写回完整 implementation。

- [ ] **Step 5: Expand_process 拆除死派发器调用**

read_pou `Application/40_Man/Expand_process_展开流程`, 把文件末尾的:

```
	ELSE
		Develop_L2_Dispatch();
	END_IF
END_IF
```

改为:

```
	ELSE
		(* L2 派发已由 PLC_MainPRG 每扫描调用的 50_action/Develop_L2 承担;
		   旧 Develop_L2_Dispatch 码表过期 (30/40) 且 code50 卡 Tank_State=40 前置,
		   若在此启用会与活派发器双写 Develop_L2_* 通道, 故拆除.
		   spec: docs/superpowers/specs/2026-07-14-develop-drain-l2-migration-design.md *)
	END_IF
END_IF
```

write_pou 写回。(POU `Develop_L2_Dispatch` 本体保留不删 — 无调用者即无害, 删除对象操作留给日后清理。)

- [ ] **Step 6: 编译 + 保存 + 提交**

```
codesys_compile
```

Expected: 0 errors (可能出现 Develop_L2_Dispatch 未调用的 warning, 可接受)。

```
codesys_save
```

```bash
git add eit_ptlc/plc/20260702.project
git commit -m "feat(plc): Develop_L2 派发器按98终态修缮 (50门501/51收98/幂等) + 拆除40_Man死派发器双写隐患 (spec 2026-07-14)"
```

---

### Task 6: 全量离线守卫 + 文档收尾

**Files:**
- Modify: `docs/superpowers/specs/2026-07-14-develop-drain-l2-migration-design.md` (状态戳)

- [ ] **Step 1: 全量跑本次涉及的离线套件**

```bash
cd E:/PHD/PKU/MoGroup/pTLC_platform/EIT_Project-Next
E:/Anaconda/python.exe -m eit_ptlc.tests.test_plc_l2_acceptance_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_develop_auto_drain_flow_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_develop_four_stage_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_plc_controller_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_stations_l2_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_node_registry_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_pump_contract_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_knob_override_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_waterlevel_autodrain_params_offline
```

Expected: 全部 0 失败。任一失败 → 按 superpowers:systematic-debugging 处理后重跑。

- [ ] **Step 2: spec 状态戳**

spec 文件头部 `日期:` 行后加一行:

```
状态: 已实施 (plan 2026-07-14-develop-drain-l2-migration, 离线全绿; 上机验证项见 §7 待跑)
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-07-14-develop-drain-l2-migration-design.md
git commit -m "docs(develop): 排液L2迁移 spec 落状态戳 — 软件已实施离线全绿, 上机4项待验证"
```

---

## 上机验证项 (plan 之外, 硬件到位后; 复制自 spec §7)

1. 吹气段真空保持 vs 撤销的前沿净推进对比 (并入 P0 实验批次);
2. `DryDuration` (`dry_duration_s`) 标定: 不同溶剂体系下板到干态的时长, 定 knob 默认值;
3. 多缸同组并发排液的 Phase A 延迟实测 (传感器挟持幅度, 读 `Tank_Drain_CapHit`);
4. 开盖 just-in-time 后取板全链 dry-run (develop_unload: plate_retract → robot_tank_pick → release_tank)。
