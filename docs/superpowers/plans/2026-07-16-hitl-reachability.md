# HITL 可达性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 挂起的 HITL 请求可从服务端随时重建(新端点 `GET /api/debug/active`),弹窗全局化到任何页面,并支持「稍后处理」最小化为 StatusBar 徽标随时重新唤起。

**Architecture:** 后端在 `VmThread._op_human` 保留发出的请求 payload(与 `vm_human_request` 事件字段一致),经 `VmController._state()/active()` 与新 REST 端点暴露;前端 debug store 新增 `seedActive()`(App 挂载 + WS 重连沿拉取,**只填充不清除**)与 `hitlMinimized` 状态;`HitlModal` 从 EditorView 提升到 App.vue 全局层。

**Tech Stack:** FastAPI + asyncio(后端,纯 stdlib,无新依赖);Vue3 + pinia(前端);离线测试为脚本式 `python -m` 套件(非 pytest 收集)。

**Spec:** `docs/superpowers/specs/2026-07-16-hitl-reachability-design.md`(设计决策 D1-D4、契约 §4、测试 §5 以 spec 为准)。

## Global Constraints

- 本机解释器: `E:/Anaconda/python.exe`(非 miniforge;测试文件头部的 miniforge 路径是历史注释)。
- 注释/文案中文为主、技术术语英文,匹配周边代码风格。
- `pending_human` 字段集合与 `vm_human_request` 事件**严格一致**(去 type/run_id/ts):`req_id, kind, prompt, fields, image, options, context, aid`。
- `active()` 返回的 `operation` 必须与 `operation_start` 事件同源 = 根 doc 的 `name` 字段(`thread.py` `run()` 里 `self._root.get("name", "")`;controller 侧从 `self._docs[run_id]` 取,同一对象)。
- `seedActive` 只填充不清除(spec D3):绝不因服务端快照无 pending 而清本地 `hitl`。
- 不改 `runs.js`、`eventStream.js`、回复接口与 req_id 竞态守卫(`stores/debug.js` `replyHuman`)。
- 前端无测试设施:每个前端任务以 `npm run build`(vite,在 `eit_ptlc/web/` 下)作静态验证;行为验证走 spec §5 手动清单(上机 pending)。
- **工作区有大量无关 WIP 未提交**(0716 wait_level/vision 工作,含 `eit_ptlc/operation/vm/thread.py`)。每次提交只 stage 本任务文件;Task 0 preflight 处理 thread.py 的 WIP 重叠。
- 离线回归基线:改动 `_state()` 形状(新增 key)后,`test_vm_debug_offline` / `test_vm_thread_offline` / `test_vm_api_offline` / `test_vm_human_offline` 必须全绿。

---

### Task 0: Preflight — 确认待改文件无未提交 WIP 重叠

**Files:** 无修改;只读检查。

- [ ] **Step 1: 检查本计划要改的文件是否已有未提交改动**

```bash
cd "E:\PHD\PKU\MoGroup\pTLC_platform\EIT_Project-Next"
git status --porcelain -- eit_ptlc/operation/vm/thread.py eit_ptlc/operation/vm/controller.py \
  eit_ptlc/api/vm_routes.py eit_ptlc/tests/test_vm_human_offline.py eit_ptlc/tests/test_vm_api_offline.py \
  eit_ptlc/web/src/api.js eit_ptlc/web/src/stores/debug.js eit_ptlc/web/src/App.vue \
  eit_ptlc/web/src/views/EditorView.vue eit_ptlc/web/src/components/HitlModal.vue \
  eit_ptlc/web/src/components/StatusBar.vue
```

Expected: 计划撰写时 `eit_ptlc/operation/vm/thread.py` 显示 ` M`(0716 wait_level WIP)。

- [ ] **Step 2: 如有重叠,停下问用户**

若上述任何文件已有未提交改动:**停止执行,向用户报告哪些文件重叠,请用户先把 WIP 单独提交(或明确同意混入)**。不得擅自 stash 或把无关 WIP 卷进本计划的提交。若全部干净,直接进 Task 1。

---

### Task 1: 后端 — VmThread 保留 pending human payload + `_state()` 暴露

**Files:**
- Modify: `eit_ptlc/operation/vm/thread.py`(init 的 HITL 块 ~L76-78;`_op_human` ~L446-466;`snapshot_vars` 附近加 property)
- Modify: `eit_ptlc/operation/vm/controller.py`(`_state()` ~L262-265)
- Test: `eit_ptlc/tests/test_vm_human_offline.py`(新 case 4,3 个 check)

**Interfaces:**
- Consumes: 现有 `_op_human` 局部变量 `req_id/prompt/image/context` 与 `node` 字段;`aid_of(path)`。
- Produces: `VmThread.pending_human_request -> Optional[dict]`(property,无门挂起时 None,字段见 Global Constraints);`VmController._state()` 新 key `"pending_human": dict|None`。Task 2/3 依赖二者。

- [ ] **Step 1: 写失败测试** — 在 `test_vm_human_offline.py` 的 case 3 之后、`print(f"\n共 ...")` 之前插入:

```python
    # 4) pending_human 可重建: 门挂起时 state 携带与事件一致的请求全文; 连门 req_id 更新; 终态清空
    ex4 = FakeExecutor()
    ev4: list[dict] = []
    doc4 = script("hp", [{"name": "note", "scope": "local", "type": "STRING", "io": "var", "default": ""}],
                  [{"op": "human", "kind": "input", "prompt": {"lit": "第一道门"},
                    "fields": [{"var": "note"}]},
                   {"op": "human", "kind": "confirm", "prompt": {"lit": "第二道门"}}])
    c4 = VmController(executor=ex4, res_gate=ResourceGate(), event_sink=ev4.append)
    s = await c4.start(doc4, mode_run="run")
    rid4 = s["run_id"]
    await wait_status(c4, rid4, "WAITING_HUMAN")
    st = c4.state(rid4)
    evreq = next(e for e in ev4 if e["type"] == "vm_human_request")
    expect = {k: evreq[k] for k in ("req_id", "kind", "prompt", "fields", "image", "options", "context", "aid")}
    check("pending_human_matches_event", st.get("pending_human") == expect,
          f"state={st.get('pending_human')} event={expect}")
    await c4.human_reply(rid4, evreq["req_id"], {"values": {"note": "ok"}})
    ok = await wait_status(c4, rid4, "WAITING_HUMAN")
    st2 = c4.state(rid4)
    check("pending_human_second_gate",
          ok and bool(st2.get("pending_human")) and st2["pending_human"]["req_id"] != evreq["req_id"]
          and st2["pending_human"]["prompt"] == "第二道门", str(st2.get("pending_human")))
    await c4.human_reply(rid4, st2["pending_human"]["req_id"], {"choice": "ok"})
    ok = await wait_status(c4, rid4, "DONE")
    check("pending_human_cleared_after_done", ok and c4.state(rid4).get("pending_human") is None,
          str(c4.state(rid4)))
```

同时把末行计数改为实际 check 数:`print(f"\n共 10 用例, 失败 {len(failures)}")`(原 7 个 check + 新 3 个;原文件印的 8 是历史误计,顺手勘正)。

- [ ] **Step 2: 跑测试确认失败**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_human_offline
```

Expected: `FAIL pending_human_matches_event`(state 里无 pending_human key,`None != {...}`),其余原有 case PASS。

- [ ] **Step 3: 实现** — `thread.py` 三处:

(a) init 的 HITL 块(现为两行)追加一行:

```python
        # HITL
        self._human_reply: Optional[asyncio.Future] = None
        self._pending_human: Optional[str] = None
        # 挂起的人工请求 payload (字段与 vm_human_request 事件一致, 去 type/run_id/ts);
        # 供 GET /api/debug/active 重建前端弹窗 (刷新/断线找回), 回复后清空
        self._pending_human_payload: Optional[dict] = None
```

(b) `_op_human` 中,把现有的 `self._emit({"type": "vm_human_request", ...})` 调用改为先构 payload 再复用(emit 字段值不变):

```python
        payload = {"req_id": req_id, "kind": node.get("kind"), "prompt": prompt,
                   "fields": node.get("fields", []), "image": image,
                   "options": node.get("options", []), "context": context, "aid": aid_of(path)}
        self._pending_human_payload = payload
        self._emit({"type": "vm_human_request", "run_id": self.run_id, **payload, "ts": self._time()})
```

并在其下的 `finally:` 块(现清 `_pending_human`/`_human_reply` 两行)追加:

```python
            self._pending_human_payload = None
```

(c) 在 `snapshot_vars` 方法旁(公开访问器区)加 property:

```python
    @property
    def pending_human_request(self) -> Optional[dict]:
        """挂起的人工请求 payload (无门挂起时 None); 字段与 vm_human_request 事件一致 (供 API 重建弹窗)."""
        return dict(self._pending_human_payload) if self._pending_human_payload else None
```

`controller.py` 的 `_state()` 加一个 key:

```python
    def _state(self, thread: VmThread) -> dict:
        return {"run_id": thread.run_id, "status": thread.status.value,
                "current_aid": thread.current_aid, "script": thread.current_script(),
                "stack_depth": len(thread.stack), "hold": self._hold.get(thread.run_id, "none"),
                "pending_human": thread.pending_human_request}
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_human_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_thread_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_debug_offline
```

Expected: 三个套件末行均 `失败 0`(`_state` 新增 key 不得破坏 debug 套件)。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/operation/vm/thread.py eit_ptlc/operation/vm/controller.py eit_ptlc/tests/test_vm_human_offline.py
git commit -m "feat(hitl): VmThread 保留挂起 human 请求 payload + state 暴露 pending_human — 弹窗可重建的数据源 (spec 0716 §4.1)"
```

---

### Task 2: 后端 — `VmController.active()` 非终态运行列表

**Files:**
- Modify: `eit_ptlc/operation/vm/controller.py`(查询区,`state()`/`vars()` 之后)
- Test: `eit_ptlc/tests/test_vm_human_offline.py`(新 case 5,3 个 check)

**Interfaces:**
- Consumes: Task 1 的 `_state()`(含 `pending_human`);现有 `_FINAL` 集合、`self._threads`、`self._docs`。
- Produces: `VmController.active() -> dict`,形状 `{"runs": [ {run_id, status, current_aid, script, stack_depth, hold, pending_human, operation} ]}`。Task 3 的路由直接返回它。

- [ ] **Step 1: 写失败测试** — 在 Task 1 的 case 4 之后插入:

```python
    # 5) active(): 门挂起时列出非终态 run (含 operation 与 pending_human); 终态后出列
    ex5 = FakeExecutor()
    doc5 = script("ha", [], [{"op": "human", "kind": "confirm", "prompt": {"lit": "在吗"}}])
    c5 = VmController(executor=ex5, res_gate=ResourceGate())
    check("active_empty_initially", c5.active() == {"runs": []}, str(c5.active()))
    s = await c5.start(doc5, mode_run="run")
    rid5 = s["run_id"]
    await wait_status(c5, rid5, "WAITING_HUMAN")
    act = c5.active()["runs"]
    check("active_lists_waiting_run",
          len(act) == 1 and act[0]["run_id"] == rid5 and act[0]["operation"] == "ha"
          and act[0]["status"] == "WAITING_HUMAN" and act[0]["pending_human"]["prompt"] == "在吗",
          str(act))
    await c5.human_reply(rid5, act[0]["pending_human"]["req_id"], {"choice": "ok"})
    await wait_status(c5, rid5, "DONE")
    check("active_excludes_final", c5.active() == {"runs": []}, str(c5.active()))
```

计数行改为 `共 13 用例`。

- [ ] **Step 2: 跑测试确认失败**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_human_offline
```

Expected: `AttributeError: 'VmController' object has no attribute 'active'`(脚本式套件直接抛错退出即失败)。

- [ ] **Step 3: 实现** — `controller.py` 查询区(`vars()` 之后、`_state()` 之前)加:

```python
    def active(self) -> dict:
        """非终态运行列表, 供前端刷新/断线重连后重建 HITL 弹窗与调试状态 (rehydrate).

        返回:
            {"runs": [_state + {"operation": 根脚本名}]}; operation 与 operation_start
            事件同源 (根 doc 的 name), 供前端 DebugDock 归属判定 (isRunActiveElsewhere)。
            终态 (DONE/ERROR/KILLED) 即使仍驻留 _threads (未被 _purge 淘汰) 也不出现。
        """
        runs = []
        for run_id, thread in self._threads.items():
            if thread.status in _FINAL:
                continue
            runs.append({**self._state(thread),
                         "operation": self._docs.get(run_id, {}).get("name", "")})
        return {"runs": runs}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_human_offline
```

Expected: 末行 `共 13 用例, 失败 0`。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/operation/vm/controller.py eit_ptlc/tests/test_vm_human_offline.py
git commit -m "feat(hitl): VmController.active() 非终态运行列表 — rehydrate 数据面 (spec 0716 §4.1)"
```

---

### Task 3: 后端 — 路由 `GET /api/debug/active`

**Files:**
- Modify: `eit_ptlc/api/vm_routes.py`(`debug_state` 路由之前加新路由;文件头端点清单加一行)
- Test: `eit_ptlc/tests/test_vm_api_offline.py`(HITL 段扩 3 个 check)

**Interfaces:**
- Consumes: Task 2 的 `vm.active()`。
- Produces: `GET /api/debug/active → {"runs": [...]}`(形状同 Task 2)。前端 Task 4 的 `api.debugActive()` 消费。

- [ ] **Step 1: 写失败测试** — `test_vm_api_offline.py` 中:

(a) `check("hitl_waiting", ...)` 之后插入:

```python
        act = client.get("/api/debug/active").json()["runs"]
        mine = next((r for r in act if r["run_id"] == hid), None)
        check("active_has_pending_human",
              mine is not None and mine["operation"] == "t_human"
              and mine["pending_human"]["kind"] == "input" and mine["pending_human"]["req_id"],
              str(act))
        check("state_has_pending_human",
              client.get(f"/api/debug/{hid}/state").json().get("pending_human", {}).get("prompt") == "请输入备注",
              str(client.get(f"/api/debug/{hid}/state").json()))
```

(b) `check("hitl_done_bound", ...)` 之后插入(其它 run 可能仍驻留,按 run_id 过滤):

```python
        act = client.get("/api/debug/active").json()["runs"]
        check("active_clears_after_done", all(r["run_id"] != hid for r in act), str(act))
```

末行计数 `共 18 用例` 改为 `共 22 用例`(实际现有 check 数是 19, printed 18 是历史误计, 顺手勘正; 19+3=22)。

- [ ] **Step 2: 跑测试确认失败**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_api_offline
```

Expected: `FAIL active_has_pending_human`(路由不存在,`.json()` 是 404 detail dict,取 `["runs"]` 抛 KeyError 即失败)。注:sim app 首次启动较慢属正常。

- [ ] **Step 3: 实现** — `vm_routes.py`:

(a) 文件头 docstring 端点清单的 `GET /debug/{run_id}/{state|vars}` 行后加:

```
    GET    /debug/active                                           非终态运行列表 (rehydrate: 含挂起 human 请求)
```

(b) `debug_state` 路由定义之前加(3 段路径与 4 段的 `{run_id}/state` 无冲突,置前仅为可读性):

```python
    @app.get("/api/debug/active")
    async def debug_active(request: Request):
        """非终态运行列表 (含挂起的 human 请求全文): 前端刷新/WS 断线重连后重建弹窗与调试状态."""
        return _vm(request).active()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_api_offline
```

Expected: 末行 `共 22 用例, 失败 0`。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/api/vm_routes.py eit_ptlc/tests/test_vm_api_offline.py
git commit -m "feat(hitl): GET /api/debug/active — 挂起 human 请求经 REST 可重建 (spec 0716 §4.2)"
```

---

### Task 4: 前端 — `api.debugActive` + debug store `seedActive()`/`hitlMinimized`

**Files:**
- Modify: `eit_ptlc/web/src/api.js`(`hitlReply` 行后)
- Modify: `eit_ptlc/web/src/stores/debug.js`

**Interfaces:**
- Consumes: Task 3 端点。
- Produces: store 新导出 `hitlMinimized`(ref bool)与 `seedActive()`(async)。Task 5 在 App.vue 调 `seedActive`;Task 6 的 HitlModal/StatusBar 读写 `hitlMinimized`。

- [ ] **Step 1: 实现 api.js** — `hitlReply` 行后加:

```js
  debugActive: () => http.get('/api/debug/active').then((r) => r.data),
```

- [ ] **Step 2: 实现 debug.js** — 四处:

(a) `hold` ref 声明行后加:

```js
  const hitlMinimized = ref(false)    // HITL「稍后处理」最小化标记; 新门到达/hitl 清空时复位
```

(b) `replyHuman` 之后加 `seedActive`:

```js
  // 从服务端重建活跃运行 + 挂起 HITL 门 (App 挂载与 WS 重连沿调用)。
  // 只填充不清除 (spec D3): REST 快照可能老于在途 WS 事件, 据快照清 hitl 会重新引入丢门竞态。
  // 断线期间他屏已答的陈旧弹窗: 用户点击后回复落空 (accepted=false), 本地照既有路径关闭, 无害。
  async function seedActive() {
    let runs
    try { runs = (await api.debugActive()).runs || [] } catch (e) { return }  // 拉取失败静默; 下个重连沿再试
    if (!runs.length) return
    const target = runs.find((r) => r.pending_human) || runs[runs.length - 1]
    const localIdle = !runId.value || isIdle(status.value)
    if (!localIdle && target.run_id !== runId.value) return  // 不抢占本地调试会话 (与 operation_start latch 同型守卫)
    runId.value = target.run_id
    operation.value = target.operation || operation.value
    operationAtomic.value = false                            // active 只含 VM 流程 (单动作不经 VmController)
    _apply(target)
    const p = target.pending_human
    if (p && (!hitl.value || hitl.value.req_id !== p.req_id)) {
      hitl.value = { req_id: p.req_id, kind: p.kind, prompt: p.prompt, fields: p.fields || [],
                     image: p.image, options: p.options || [], context: p.context, aid: p.aid }
      hitlMinimized.value = false
    }
  }
```

(c) `hitlMinimized` 复位点与 `hitl.value = null` 一一同步(共 5 处):
- `start()` 里 `hitl.value = null` 后加 `hitlMinimized.value = false`
- `endSession()` 里 `hitl.value = null` 后加 `hitlMinimized.value = false`
- `replyHuman()` 里 `if (hitl.value?.req_id === rid) hitl.value = null` 改为:

```js
    if (hitl.value?.req_id === rid) { hitl.value = null; hitlMinimized.value = false }
```

- `ingest` 的 `vm_human_request` 分支,置 `hitl.value = {...}` 后加 `hitlMinimized.value = false`(新门强制弹出)
- `ingest` 的 `vm_human_reply` 分支改为 `{ hitl.value = null; hitlMinimized.value = false }`

(d) return 导出对象追加 `hitlMinimized` 与 `seedActive`(放在 `hitl,` 与 `replyHuman,` 旁)。

- [ ] **Step 3: 构建验证**

```bash
cd "E:\PHD\PKU\MoGroup\pTLC_platform\EIT_Project-Next\eit_ptlc\web" && npm run build
```

Expected: vite build 成功,无 import/语法错误。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/web/src/api.js eit_ptlc/web/src/stores/debug.js
git commit -m "feat(hitl): debug store seedActive 只填充式 rehydrate + hitlMinimized 稍后处理状态 (spec 0716 §4.3)"
```

---

### Task 5: 前端 — HitlModal 提升到 App.vue 全局层 + 挂载/重连沿 seed

**Files:**
- Modify: `eit_ptlc/web/src/App.vue`
- Modify: `eit_ptlc/web/src/views/EditorView.vue`(移除 HitlModal)

**Interfaces:**
- Consumes: Task 4 的 `debug.seedActive()`;现有 `HitlModal.vue`(自带 `Teleport to body`,z-index 契约不变: AlarmBanner 3000 > modal 1000)。
- Produces: HitlModal 全局单实例(Task 6 只需改组件内部,无需关心挂载点)。

- [ ] **Step 1: App.vue** — script 的 import 区加:

```js
import HitlModal from './components/HitlModal.vue'
```

`onMounted` 内把最后一行 `startEventStream(...)` 段改为(挂载 seed 一次 + 断开→连上边沿再 seed;首次连接也会触发边沿,与挂载那次幂等重复无害):

```js
  debug.seedActive()   // 首屏 rehydrate: 刷新丢门找回 (seedActive 内部吞错, 不阻断)
  let wasConnected = false
  startEventStream((connected) => {
    sys.setStreamConnected(connected)
    if (connected && !wasConnected) debug.seedActive()   // 断线→重连沿: 补拉断线期间可能丢的门
    wasConnected = connected
  })
```

template 改为:

```html
<template>
  <AlarmBanner />
  <ConsoleShell />
  <HitlModal />
</template>
```

- [ ] **Step 2: EditorView.vue** — 删两处:import 行 `import HitlModal from '../components/HitlModal.vue'` 与 template 里 `<HitlModal />`(避免双实例双弹)。同步把文件头注释 `// 编排 IDE 中区: 工具栏 / (节点表 + 右栏) / 调试坞 + HITL 弹窗` 改为 `// 编排 IDE 中区: 工具栏 / (节点表 + 右栏) / 调试坞 (HITL 弹窗已全局化, 挂 App.vue)`。

- [ ] **Step 3: 构建验证**

```bash
cd "E:\PHD\PKU\MoGroup\pTLC_platform\EIT_Project-Next\eit_ptlc\web" && npm run build
```

Expected: build 成功。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/web/src/App.vue eit_ptlc/web/src/views/EditorView.vue
git commit -m "feat(hitl): HitlModal 全局化到 App.vue + 挂载/WS 重连沿 seedActive — 跨页面弹出与丢门找回 (spec 0716 §4.4)"
```

---

### Task 6: 前端 — 「稍后处理」最小化 + StatusBar「等待人工」徽标

**Files:**
- Modify: `eit_ptlc/web/src/components/HitlModal.vue`
- Modify: `eit_ptlc/web/src/components/StatusBar.vue`

**Interfaces:**
- Consumes: Task 4 的 `debug.hitlMinimized` / `debug.seedActive()`;`style.css` 既有 `.badge.WAITING_HUMAN` 样式族。
- Produces: 完整交互闭环(弹出→稍后处理→徽标→重新唤起)。

- [ ] **Step 1: HitlModal.vue 显示条件** — template 外层 `<div v-if="debug.hitl" class="modal-backdrop">` 改为(v-if 保门存在性、v-show 只隐藏不卸载——保住手绘门画布已点角点/多边形;门切换复位仍由既有 `watch(() => debug.hitl)` 负责):

```html
    <div v-if="debug.hitl" v-show="!debug.hitlMinimized" class="modal-backdrop">
```

- [ ] **Step 2: 三个门类动作区各加「稍后处理」按钮**

(a) 手绘门 `modal-actions`(`cancelSketch` 的「取消」按钮前):

```html
            <button class="run ghost" @click="debug.hitlMinimized = true">稍后处理</button>
```

(b) 重识别门 `modal-actions`(`cancelReanalyze` 的「取消」按钮前):同一行代码。

(c) 通用门 `modal-actions`(choose/input/confirm 共用块,两个 `<template>` 之后、`</div>` 之前):同一行代码。

- [ ] **Step 3: StatusBar.vue 徽标** — script 加:

```js
import { useDebugStore } from '../stores/debug'
```

```js
const debug = useDebugStore()
// 等待人工徽标: 常规 = hitl 已就位 (弹着或已稍后处理); 兜底 = 状态卡 WAITING_HUMAN 却无 hitl
// (事件丢失的残余失效模式) → 点击先 seedActive 手动找回再展开
const hitlWaiting = computed(() => !!debug.hitl || debug.status === 'WAITING_HUMAN')
async function openHitl() {
  if (!debug.hitl) await debug.seedActive()
  debug.hitlMinimized = false
}
```

template 在 run-ind div 之后加:

```html
    <div class="sb-item hitl-ind clickable" v-if="hitlWaiting" @click="openHitl" title="有流程在等待人工处理, 点击打开">
      <span class="badge WAITING_HUMAN">等待人工</span>
    </div>
```

scoped style 加:

```css
.hitl-ind.clickable { cursor: pointer; }
.hitl-ind .badge { animation: hitl-pulse 1.2s ease-in-out infinite; }
@keyframes hitl-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
```

- [ ] **Step 4: 构建验证**

```bash
cd "E:\PHD\PKU\MoGroup\pTLC_platform\EIT_Project-Next\eit_ptlc\web" && npm run build
```

Expected: build 成功。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/web/src/components/HitlModal.vue eit_ptlc/web/src/components/StatusBar.vue
git commit -m "feat(hitl): 稍后处理最小化 (v-show 保画布态) + StatusBar 等待人工徽标可重新唤起 (spec 0716 §4.4, D1/D4)"
```

---

### Task 7: 收口 — 全量离线回归 + 手动验证清单交接

**Files:** 无新改动(除非回归暴露问题)。

- [ ] **Step 1: 四套件离线回归**

```bash
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_thread_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_debug_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_human_offline
E:/Anaconda/python.exe -m eit_ptlc.tests.test_vm_api_offline
```

Expected: 四套件末行均 `失败 0`(human=13、api=22)。

- [ ] **Step 2: 前端最终构建**

```bash
cd "E:\PHD\PKU\MoGroup\pTLC_platform\EIT_Project-Next\eit_ptlc\web" && npm run build
```

Expected: build 成功。

- [ ] **Step 3: 手动验证清单交接** — 向用户报告 spec §5 的 7 条前端手动清单为 pending(需起 sim/真机 + 浏览器):跨页弹出 / 刷新找回(含 DebugDock 状态同步=缺陷 C)/ 稍后处理→徽标唤起 / 断线重连找回 / 双屏一答一关 / 最小化时新门强制弹出 / 编辑器页无回归。不自行宣称"已验证"。
