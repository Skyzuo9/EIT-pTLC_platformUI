# 透传 knob —— action 参数运行前覆盖 (奥卡姆计划, 2026-07-05)

状态: **标量核心已实现并离线验证 (2026-07-05)**; LIST-批次 UI 为紧随其后的第二步 (引擎已天然支持
LIST 旋钮, 见文末)。本文是与用户逐支 grill 后达成的共识; §1–§5 为原始设计, 文末「执行记录」记落地
实况与一处奥卡姆偏离。

## 0. 底层需求

operation 执行(尤其全流程 demo)时, 常需临时改某个 action 的参数(如上样清洗的
液体体积 / 吸液打液速度 / 清洗次数, 点样的起终点 / 抽取体积)。这些参数当前是**深埋 2–3
层嵌套的叶子 `{lit}` 字面量**(例: `ptlc_full_v2 → sampling_cycle → sampling_prepare →
sampling.clean` 的 `cleaning_count: {lit: 1}`)。要让它可调, 今天得在**每个 `run_script`
接缝**声明 `in` 并写 `inputs:` 逐层透传 —— 即 prop-drilling, 不便且易漏。

目标: 让白名单参数在**运行前一步**被用户按需覆盖, 零逐层接线, 且不破坏 VM 安全模型。

## 1. 已决口径 (逐支 grill 结论)

| 分支 | 决定 |
|---|---|
| 核心场景 | 少数已知实验旋钮为主(curated), 机制可退化 |
| 寻址模型 | **语义具名旋钮 + 自动下传**; 非 AID 位置寻址 |
| 多实例(同 sub-op 跑 N 次各不同) | **LIST-of-DICT 表 + `for` 循环**(数据批, 如多-lane 板); 循环使实例相异, 覆盖通道只送一张表 |
| 基线来源 | 暴露的叶子 `{lit}` → `{var}`; 转换本身即 opt-in 白名单 |
| knob 来源 | **纯 curated 白名单**(不做全参发现) |
| 时间点 | **仅运行前预检面板 (v1)**; mid-run 交现有 `reanalyze` HITL 门 |

核心洞察: **knob 不是新概念, 就是带 `ui:` 元数据的 `in` 变量**; 唯一新机器是「运行前
把一张覆盖 map 在**建帧时按名注入**」。类型系统已够(`VAR_TYPES` 含 `LIST`/`DICT`,
见 `vm/expr.py:25`), 注入点已现成(`vm/thread.py:232 _make_frame` 在应用 `inputs`
之后叠加即可)。不碰控制流、不碰 `mode: RUN` 门。

## 2. 核心契约 (最小)

- **knob = `in` var + 可选 `ui:` 块**(`label / group / min / max / enum`)。有 `ui:` 才
  进面板 → 天然白名单。**不新增顶层 `knobs:` 概念**, 复用现有 var 机器。
- **覆盖 map 按 var 名寻址**, `start(overrides=…)` 带入; VM 在**每一次建帧**时于
  `inputs` 之后叠加(override 胜)。同名 = 同一 knob(正是「语义具名」语义)。
- **多实例差异**交给 `LIST` knob + `for` 循环(循环每轮重读 LIST → 「改还没跑到的行」
  天然成立), 不引位置寻址。
- **安全**: knob 只改*数值*, 不改跑哪些 action、不注入控制流 → 天然不越 `mode` 门;
  值由 `coerce_value` + `min/max/enum` **双重校验**(提交时 + 注入时)兜底。作者为
  安全关键量(速度 / Z 切深)设合理 range 是唯一人为责任。
- **硬语义**: 注入发生在**该帧被构造那一刻**; 归属帧已跑过再改无效。v1 只运行前, 不触此边界。

## 3. 改动清单 (依赖序)

### ① 引擎 (无 UI, 可离线测)
- `vm/schema.py`: var 校验放行可选 `ui:` 元数据(非破坏性)。
- `vm/thread.py`: `VmThread.__init__` 存 `self._overrides`; `_make_frame` 末尾对**已声明
  的 `in` var**做 `if 名 in overrides: var.value = coerce(...)`; `run()` 签名加 `overrides`。
- `vm/controller.py`: `start(...)` 透传 `overrides` 到 `_drive → run`; `reset` 沿用同一份
  (复位重跑参数不丢, 存入 `self._inputs` 旁的 `self._overrides`)。
- 新增 `collect_knobs(entry_doc, resolve_script)`: 静态遍历 run_script 树收集所有带 `ui:`
  的 `in` var → `[{path, name, type, default, ui}]`(带 `max_depth` 防环)。

### ② 样板 (证明打通)
- `config/operation/01_sampling/sampling_prepare.yaml`: `sampling.clean` 的 5 个 `{lit}`
  → `{var}`, 加对应 `in` + `ui` 声明(min/max 可 `from: sampling.clean.<param>` 继承
  action 参数 schema, 避免两处重复)。
- 新增 `sampling_batch`(或改造 `sampling_cycle`): 声明 `lanes: LIST` knob, body
  `for lane in lanes → run_script sampling_execute, inputs: {well: {field:{var:lane},name:well},
  sample_volume_ml: {field:{var:lane},name:vol}, …}`。

### ③ UI (运行前一步)
- `api/app.py`: `GET /operations/{name}/knobs` → `collect_knobs`; run-start 接受 `overrides`。
- Web: 预检面板组件 —— 按 `group`/子 op 成卡片; 标量 = 带 min/max 字段, `LIST` = 可增删
  行网格; 未动显灰「默认」, 只有动过的进 map; 接入 runs store 的 run-start。

### ④ 测试
- 离线: override 名达到深 3 层帧(`cleaning_count=3` 生效); 越界被拒; lane 表驱动循环轮数正确。

## 4. 明确不做 (v1 razor)
- mid-run 改参(交现有 `reanalyze` 门)
- 实验预设 sidecar JSON、「存为默认」写回 YAML `default`
- 路径限定身份(冲突时再升级: map key 由 `name` 改 `path::name` 即可)
- 位置 / AID 节点覆盖

## 5. 端到端样例 (可验)

场景: 一块板 3 lane, 清洗次数全局调 3, 每 lane 不同 well / 体积。

1. `sampling_prepare` 声明 `cleaning_count` 等为 `in`+`ui`, `sampling.clean` 读 `{var: cleaning_count}`。
2. 批次 op 声明 `lanes: LIST`, `for lane in lanes` 跑 `sampling_execute`。
3. 预检面板遍历树 → 两组:「清洗(cleaning_count=1)」标量 +「lane 表」网格。用户改
   `cleaning_count=3`, 网格填 3 行。
4. `start(overrides={"cleaning_count": 3, "lanes": [...]})`。
5. VM 建 `sampling_prepare` 帧时叠加 → `cleaning_count=3`; 建批次帧时注入 `lanes` → 循环
   3 次, 每次 `sampling_execute` 拿到该行参数。**全程零逐层 `inputs:` wiring**。

## 6. 执行记录 (2026-07-05 落地)

### 已落地 (标量核心, 端到端离线验证通过)
- **引擎**: `vm/schema.py::is_knob_var` (旋钮唯一判定 = `io:in` 且带 `ui:`, 供建帧注入与静态收集
  同源); `vm/thread.py` `__init__` 存 `self._overrides`、`_make_frame` 在 inputs 后按名注入命中
  旋钮 (仅类型 coerce); `vm/controller.py` `start/reset/_new_thread` 透传 `overrides` (复位重跑
  不丢); 新 `vm/knobs.py::collect_knobs`(树内递归收集, visited 拦环 + `MAX_KNOB_DEPTH`) 与
  `validate_overrides`(运行前范围/枚举/未知键校验)。
- **样板**: `config/operation/01_sampling/sampling_prepare.yaml` 的 5 个 `sampling.clean` `{lit}`
  → `{var}` + `in`+`ui` 旋钮; `default` 保原值 → 不覆盖时逐字等价旧行为; `ui.min/max` 对齐动作
  schema。跑 `sampling_cycle` 时经 `collect_knobs` 在 `sampling_cycle → sampling_prepare` 深度自动
  浮现这 5 个旋钮, **零逐层 `inputs:`**。
- **API**: `GET /api/scripts/{name}/debug/knobs` (collect_knobs); `VmStartBody.overrides` +
  `debug/run` 运行前 `validate_overrides` (越界/未知 → 400) 后透传 `vm.start(overrides=…)`。
- **Web**: `api.js` 加 `getKnobs` 并把 `overrides` 织入 `debugRun`; `stores/debug.js::start` 加参
  透传; `DebugDock.vue` 运行前面板扩为「裸入参 + 旋钮」两段 (带 `ui` 的 in var 归旋钮、按
  `group/子op` 成组、改动即高亮进 map、未动取默认), `style.css` 配套。
- **测试**: `tests/test_knob_override_offline.py` (深帧注入命中 / 非旋钮·常量不被误伤 / `"3"`→3
  coerce / LIST 旋钮驱动 `for` 逐行差异 / collect 去重 / validate 越界·未知·枚举); 扩
  `tests/test_vm_api_offline.py` (HTTP: 收集深层旋钮 + 覆盖注入到帧 + 越界/未知 400)。全绿。

### 一处奥卡姆偏离 (相对 §2「双重校验(提交时+注入时)」)
落地为**单点校验**: 只在**提交时** (`api` 的 `validate_overrides`) 按 `ui.min/max/enum` 拒越界
——因为**动作层 `executor._validate` 已在每次动作调用时强制 min/max/enum/required, 越界即
`REJECTED → VmActionError` fail-fast 且不触硬件**(见 `action/executor.py`)。故 VM 注入时**不再重复
范围校验**, 仅做类型 `coerce_value`; 提交校验负责「未跑先拒」的好 UX, 动作层是真正的安全闸。避免
在建帧热路径叠冗余逻辑。

### 待办 (第二步: LIST-批次多实例 UI)
引擎已支持 LIST 旋钮 (`for lane in lanes` + `field` 提取已离线验证通过, 见测试第 5 例), **只差 UI 与
一个批次 op**:
- 批次 op 的工作流语义待定 (一次 prepare 是否服务 N lane / 板物理布局) —— 属领域决策, 需与用户确认。
- LIST 旋钮网格的**列 schema 来源**待定 (建议 `ui.columns: [{name,type,min,max,label}]` 显式声明,
  或从 `default` 首行推断); 现 `DebugDock` 对 LIST 旋钮回退为 JSON 文本框 (可用但非网格)。
- `validate_overrides` 对 LIST/DICT 现仅校验可强转, 逐行范围校验随网格一并补。
