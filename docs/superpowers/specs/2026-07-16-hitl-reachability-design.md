# HITL 可达性修复 — 设计 spec

日期: 2026-07-16
状态: 设计已获用户批准 (打扰模式=全局弹出+可最小化)
范围: 单一垂直切片, 一份 plan, 不拆 sub-project

## 1. 问题

HITL(人工介入门)现状有两个结构性缺陷, 均已在真实代码链路核实:

**缺陷 A — 一次性事件, 丢了无法找回。** VM 执行到 `human` 节点时只在进门瞬间 `_emit` 一条
`vm_human_request`(`operation/vm/thread.py` `_op_human`), 然后无超时地 `await self._human_reply`。
WS 端点(`api/app.py` `/api/ws/events`)是纯实时订阅、无历史重放; 前端
`composables/eventStream.js` 断线重连后不补拉; `GET /api/debug/{run_id}/state`
(`operation/vm/controller.py` `_state`)只返回 `{run_id, status, current_aid, script,
stack_depth, hold}`, 不含挂起的 human 请求。req_id 只存在于那条事件里, 事件一丢
(页面刷新 / WS 断线期间进门 / 浏览器未开), 弹窗永远无法重建, 用户连手动回复的可能都没有
(回复接口要 req_id), VM 永远卡 `WAITING_HUMAN`, 只能终止运行。

**缺陷 B — 弹窗不跨页面。** WS 事件经 `App.vue` 全局分发进 pinia debug store,
`debug.hitl` 在任何页面都会被置上; 但 `HitlModal` 只挂载在 `EditorView.vue`
(流程编辑器页且选中了流程)。用户在监控 / 视觉调试 / 水位等页面时弹窗不出现,
且几乎无提示: `WAITING_HUMAN` 徽标只在编辑器页 DebugDock 显示; 全局底部 MonitorDock 的
`runs.live.status` 只消费 `operation_*/step_*/vm_node_*` 事件、不消费 `vm_state`,
别的页面只能看到 RUNNING。

**次生缺陷 C — 刷新后 debug store 卡 idle。** `vm_state` 只在状态迁移时发,
页面刷新后 debug store 回到 idle, 要等下一次迁移才能重新对齐, DebugDock 期间显示错误状态。
本方案的 rehydrate 机制顺带修复。

## 2. 目标 / 非目标

**目标:**
1. 挂起的 human 请求可随时从服务端重建 (刷新 / 断线重连 / 迟到的浏览器都能找回弹窗)。
2. 弹窗全局化: 任何页面立即弹出。
3. 弹窗可「稍后处理」最小化为全局常驻徽标, 点徽标随时重新唤起 (= 重新唤起机制)。

**非目标:**
- 不改 `runs.js` 的事件消费语义 (resetLive / live.status 现状不动)。
- 不改水位 `wait_level` 的降级/HITL 判定语义 (0716 诊断的另一张票)。
- 不做 HITL 门超时 / 自动升级 / 声音通知。
- 不做 WS 事件重放 (见 §3 否决方案)。
- 不动回复接口与 req_id 竞态守卫 (`stores/debug.js` replyHuman 现状保留)。

## 3. 关键决策

**D1 打扰模式 = 全局弹出 + 可最小化 (用户已确认)。**
任何页面立即弹窗; 弹窗新增「稍后处理」按钮, 收成 StatusBar 常驻「等待人工」徽标,
点徽标重新展开。新 `vm_human_request` 到达时强制重新弹出 (清最小化标记)。
否决"强弹必须处理"(遮挡示教/调参等精细操作)与"仅徽标"(易错过, 流程停等时间拉长)。

**D2 找回机制 = REST 端点, 否决 WS 接入重放。**
新增 `GET /api/debug/active`。前端在两个时机拉取: App 挂载 (修刷新)、WS 断开→连上边沿
(修断线)。否决 WS 重放的理由: 重放的 `operation_start` 会触发 `runs.js` `resetLive`
清掉已累计步进度, 四个 store 都要加重放感知守卫, 触点多且污染事件语义;
REST 拉取幂等、离线可测。

**D3 seedActive 只填充不清除。**
拉取结果只在本地空闲(或同 run)时接管, 且 hitl 只在"本地为空或 req_id 不同"时回填;
绝不因服务端快照无 pending 而清掉本地 hitl —— REST 快照可能老于在途 WS 事件,
清除会重新引入丢门竞态。代价是一个无害边缘: 断线期间他屏已答门, 重连后本屏可能短暂残留
陈旧弹窗, 用户点击后回复落空 (req_id 失配按现状为无害 no-op), 本地照常清弹窗。

**D4 徽标兜底双条件。**
StatusBar 徽标显示条件: `debug.hitl` 存在 (常规), 或 `status === 'WAITING_HUMAN'` 且
`hitl` 为空 (异常兜底, 理论上修复后不该出现)。点击: 前者清最小化标记展开;
后者先 `seedActive()` 再展开 —— 这给了任何残余失效模式一条手动找回路径。

## 4. 契约

### 4.1 后端: pending human 请求的保留与暴露

`VmThread._op_human` 在 `_emit` 的同时把请求 payload 存为实例字段, `finally` 清空:

```python
self._pending_human_payload = {
    "req_id": req_id, "kind": node.get("kind"), "prompt": prompt,
    "fields": node.get("fields", []), "image": image,
    "options": node.get("options", []), "context": context, "aid": aid_of(path),
}
```

字段集合与 `vm_human_request` 事件严格一致 (去掉 type/run_id/ts)。
门附图 image 是 API 静态文件 URL (run case 目录落盘), 跨刷新仍可加载, 无需特殊处理。

`VmController._state()` 增加一个字段:

```python
"pending_human": thread.pending_human_request   # dict | None
```

`VmController.active()` 新增: 遍历 `self._threads`, 过滤 `thread.status not in _FINAL`
(即 NEW/RUNNING/PAUSED/WAITING_HUMAN/STOPPED; 复用现有 `_FINAL` 集合,
与 `_purge` 的"未终结绝不淘汰"语义同源), 每项返回 `_state()` 加 `operation` 字段。
**operation 必须与 `operation_start` 事件的 operation 字段同值** (前端 DebugDock 归属判定
`isRunActiveElsewhere` 依赖二者一致; 实现时从事件发射处同一来源取, plan 阶段核对)。

### 4.2 后端: 新端点

```
GET /api/debug/active
→ {"runs": [{run_id, operation, status, current_aid, script, stack_depth, hold,
             pending_human: {...}|null}, ...]}
```

- 无活跃运行: `{"runs": []}`。
- 已终结但仍驻留在 `_threads` 里的运行 (被 `_purge` 淘汰前) 不出现在列表。
- 路由与 `/api/debug/{run_id}/state` 无路径冲突 (段数不同)。
- 单动作运行 (`runAction` 路径) 不经 VmController, 天然不在列表 —— 单动作无 HITL 门, 正确。

### 4.3 前端: debug store

新增状态与动作 (`stores/debug.js`):

```js
const hitlMinimized = ref(false)   // 「稍后处理」标记; 新门到达/清 hitl 时复位 false

async function seedActive() {
  // 拉取失败静默返回 (下一个重连沿再试); 空列表直接返回
  // 目标 run: 优先带 pending_human 的, 否则最新的非终态 run
  // 接管守卫与 ingest 的 operation_start 同型: 本地空闲或同 run 才接管, 不抢占本地调试会话
  // 接管时回灌 runId/operation/status/current_aid/script/hold
  // pending_human 存在且 (本地 hitl 为空 或 req_id 不同) → 回填 hitl, hitlMinimized=false
  // 本地 hitl 存在而服务端无 pending → 不清除 (D3)
}
```

`hitlMinimized` 复位点: `start()` / `endSession()` / ingest `vm_human_request`(置 false 强制弹出)
/ ingest `vm_human_reply` / `replyHuman` 清 hitl 时 —— 与 `hitl.value = null` 的既有清理点一一同步。

### 4.4 前端: 组件挂载与徽标

- `App.vue`: `<HitlModal />` 挂到根 (AlarmBanner 旁); `onMounted` 里 `debug.seedActive()`;
  WS 状态回调记录前值, false→true 边沿再调 `debug.seedActive()`。
- `EditorView.vue`: 移除 `HitlModal` 导入与标签 (避免双实例双弹)。
- `HitlModal.vue`: 外层保持 `v-if="debug.hitl"` (门存在性), 内层加 `v-show="!debug.hitlMinimized"`
  (最小化只隐藏不卸载 —— 保住手绘门画布/已点角点等组件内状态; 门切换时的状态复位仍由既有
  `watch(() => debug.hitl)` 负责)。所有门类 (confirm/input/choose/sketch/reanalyze) 的按钮区
  新增「稍后处理」→ `debug.hitlMinimized = true`。
- `StatusBar.vue`: 新增「等待人工」徽标 (warn 色, 建议脉冲动画), 显示/点击语义见 D4。
  与既有 `.badge.WAITING_HUMAN` 样式族复用。

z-index 契约不变: AlarmBanner 3000 仍压过弹窗 1000。

### 4.5 多客户端 / 多 run

- 双屏: A 屏回复后 `vm_human_reply` 事件广播, B 屏弹窗自动关 —— 现有语义, 不动。
- 多 run: `active()` 返回列表; 前端单 run 假设下按 §4.3 规则挑一个, 不做多门排队 UI。

## 5. 测试

**后端 pytest (离线, 扩展 test_vm_api_offline.py / test_vm_human_offline.py):**
1. 门挂起时: `GET /api/debug/{run_id}/state` 的 `pending_human` 含全字段且与
   `vm_human_request` 事件一致; `GET /api/debug/active` 列出该 run。
2. 回复后: `pending_human` 为 null; 运行继续 (RUNNING 非终态) 仍在 active 列表。
3. 终态 run (驻留未淘汰) 不在 active 列表; 无运行时 `{"runs": []}`。
4. 连续两道门: 第二道门的 pending_human 是新 req_id (finally 清空 + 重新赋值链路)。

**前端 (无测试设施, 手动清单):**
1. 监控页等门开 → 弹窗跨页出现。
2. 门挂起时刷新页面 → 弹窗回来; DebugDock 状态同步为 WAITING_HUMAN (缺陷 C 一并验证)。
3. 「稍后处理」→ 徽标出现 → 点徽标弹回。
4. 后端重启/断网期间门开 → 重连后弹窗出现。
5. 双屏一答一关。
6. 上一门最小化时新门到达 → 强制弹出。
7. 编辑器页无回归 (弹窗、DebugDock 徽标、req_id 竞态守卫)。

## 6. 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `eit_ptlc/operation/vm/thread.py` | `_op_human` 保留/清空 `_pending_human_payload` + 只读暴露 |
| `eit_ptlc/operation/vm/controller.py` | `_state()` 加 `pending_human`; 新增 `active()` |
| `eit_ptlc/api/vm_routes.py` | `GET /api/debug/active` |
| `eit_ptlc/web/src/stores/debug.js` | `seedActive()` + `hitlMinimized` + 复位点同步 |
| `eit_ptlc/web/src/App.vue` | 挂 HitlModal; mount + 重连沿 seedActive |
| `eit_ptlc/web/src/views/EditorView.vue` | 移除 HitlModal |
| `eit_ptlc/web/src/components/HitlModal.vue` | 显示条件 + 「稍后处理」按钮 |
| `eit_ptlc/web/src/components/StatusBar.vue` | 「等待人工」徽标 |
| `eit_ptlc/tests/test_vm_api_offline.py` 等 | §5 用例 |
