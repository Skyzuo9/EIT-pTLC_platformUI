# 透传 knob · 第二步 —— 粒度 reach + 点样几何覆盖 (执行计划, 2026-07-06)

状态: **计划 (grill 达成共识, 未动手)**。上游第一步 (标量旋钮核心) 见
`docs/透传knob_action参数运行前覆盖_奥卡姆计划_20260705.md`。

本步解决第一步遗留的**真痛点**: 循环体 operation (如 `sampling_execute`) 用作「多条带」循环单元时,
每根要变的参数 (吸样孔位 `well`、点样起终点几何) **够不着** —— `well` 是裸入参 (无 `ui:`),
点样几何根本不在 operation 树里 (在点表 `points/plc/spotting.yaml` 的组合点位 `spot_pose`)。

> 注: 原第一步文末「待办 = LIST-批次 UI」被本次 grill **重排**: LIST-批次 (声明式批档 B) 降为第三步;
> 本步 (交互档 A 的粒度 reach) 才是先决,因为 A/B 共享同一份参数接口,接口有洞则两档都残。

---

## 0. 锁定的设计口径 (grill 结论, 实现须守)

| # | 口径 |
|---|---|
| 1 | **循环体模型**: operation 作被重复单元。A 人肉交互 (跑前面板逐次填, 本步主交付) + B 声明批次 (LIST 一次 N 行, 第三步)。**A/B 共享同一份参数接口**,只差前端。 |
| 2 | **参数哲学: 乙 (完整接口)**。每轮会变的参数显式声明为带 `ui:` 的具名旋钮; 内部实现参数保持封装。裸 `{lit}` 提升 = 编辑态两行 (`{lit}`→`{var}`+`ui:`),不在跑前面板改代码。 |
| 3 | **覆盖身份: 按名**。语义具名旋钮; 层级树 (op → action →〔点位 → 成员〕→ 旋钮) 只做**导航壳**, 不做位置 (AID) 锚定。要「各调各的」→ 起不同名。 |
| 4 | **点样几何**: 三成员 `x_start / x_end / y_height` 各自独立、按**绝对值**填,跑前面板预填**实时示教基准值**; 临时覆盖走 push 缝, 点表不动。 |
| 5 | **临时覆盖 vs 持久化**: 点表 = 示教基准持久化唯一真源 (teach-verify 单写); 运行意图 = 临时覆盖, **永不回写点表**。「改点表 value 后循环」(旧 C 模型) 废弃。 |
| 6 | **实现时清误导信号**: 把被新模型取代的旧注释一并改掉,别让库里同时讲三套自相矛盾的故事。 |

**一个前提** (来自 grill, 需现场确认后收尾): 几何按机器绝对坐标, 仅在「点样工位板位可重复夹定」时成立;
若点样要跟每次板放置/视觉校正走, 几何须锚在校正后基准上 (偏置), 届时把「绝对值」改为「基准+偏置」即可,
push 缝与旋钮机制不变。

---

## 1. 核心机制决策: 几何为何走「动作参数 → VM 旋钮」而非独立通道

几何值 (x_start…) 现在在点表, 有两条路让它可覆盖:

- **(X) 并入现有旋钮通道**: 给动作 `sampling.spot_band_layer` 加**可选**成员覆盖参数 → operation 声明为
  `in` 旋钮 → 走**已有的** VM 旋钮机器 (collect/inject/validate/面板)。
- **(Y) 新开一条「点表成员覆盖」通道**: 收集器扫 `point_ref` 自动浮现成员, 覆盖 map 旁路直达 push 缝。

**选 X。决定性理由 = 口径 1 (A/B 共享一份接口)**: B 档 (`for` 循环) 是把一张表**按列名喂进循环体的
`in` 变量**。几何若是 VM 变量 (X),循环天然能逐行喂;几何若在旁路通道 (Y),`for` 循环够不着它 →
B 档无法逐带给几何 → A/B 裂成两套。故几何**必须是 VM 旋钮 (动作参数)**。

**push 缝 = 现成的** (`executor.py:252-268` → `points_service.push_composite`): 触发 L2 前据 `ref_spot`
把组合点位成员从 catalog 读出、写 `*_Target`。覆盖只需在**写那一刻**用覆盖值替 `m.value`, catalog 的
`m.value` (示教基准) **纹丝不动** —— teach 路 `set_composite_member_value` 仍是点表唯一写者。

**「未覆盖 → 走示教基准」= base by read (点表单一真源, 零重复)**: 旋钮不覆盖 → 面板不进 map →
VM 传该 arg 为 `None` → `_validate` (改后) 视 `None` 为「未提供」跳过 → 不入 coerced → 执行器成员环
找不到它 → `push_composite` 用 catalog 里的 `m.value`。**只有点表这一处存基准, 无副本、无漂移。**

---

## 2. 改动清单 (依赖序, 精确到文件/函数)

### ① 执行器: `None` ≡ 未提供 (可选参数) —— 使能 base-by-read
`eit_ptlc/action/executor.py` · `_validate` (行 495-503):
```python
# 现: if p.name in params:
if p.name in params and params[p.name] is not None:   # None ≡ 未提供 → 可选走默认/跳过, 必填仍拒
    raw = params[p.name]
```
- 语义: 显式 `None` 的可选参数当作没给 (走 default / `continue`); 必填给 `None` → 仍落 `elif p.required`
  报「缺少必填」。
- 爆炸半径: 改前 `None` 必落 `_coerce_param` 抛「类型错误」被拒 —— 无任何动作能靠收到可用 `None` 工作,
  故此改只把「必错」变「按未给处理」, 不破坏现有路径。加一条离线用例锁死。

### ② 执行器: point_ref 块收集同名成员覆盖 → 透传 push
`eit_ptlc/action/executor.py` · point_ref 块 (行 252-268), 把 `push_point_ref(str(key))` 改为:
```python
comp = self._points.composite_entry(str(key))
member_overrides = {}
if comp is not None:
    for m in comp.members:
        if m.key in coerced:                 # 声明的几何覆盖参数; None 已被 ① 挡在 coerced 外
            member_overrides[m.key] = coerced.pop(m.key)
await self._points.push_point_ref(str(key), member_overrides=member_overrides or None)
```
- 成员键 ↔ 动作参数名**按名对齐** (约定: 覆盖参数名 == 组合成员 key)。这些参数被本块 `pop`, 不下传 PLC 通道
  (与既有 `ref_spot` / `PLATE_WELL_PARAMS` 的「pop 后特殊消费」同构)。

### ③ 点位服务: push 时覆盖成员值 (只写不改真源)
`eit_ptlc/controller/points_service.py`:
- `push_composite(key, member_overrides=None)` (行 1590): 每成员 `v = (member_overrides or {}).get(m.key, m.value)`;
  `within_limits(v)` 对**生效值**校验 (越限整体不下发); `write_variable(m.node, v)`; **不触碰 `m.value`**。
  返回 `written` 每项加 `overridden: bool`。未知覆盖键 → `PointsCatalogError` (防喂错成员)。
- `push_point_ref(key, member_overrides=None)` (行 1610): 透传给 `push_composite`; 普通目标点 (无成员) 若带
  overrides → 报错 (点样才有成员)。

### ④ 动作层: 给 `spot_band_layer` 加可选成员覆盖参数
`eit_ptlc/config/actions/01_sampling/plc_sampling.yaml` · `sampling.spot_band_layer.params` 追加:
```yaml
- {name: x_start,  type: float, required: false, min: -500.0, max: 500.0, label: 点样X起点覆盖 (缺省=示教基准)}
- {name: x_end,    type: float, required: false, min: -500.0, max: 500.0, label: 点样X终点覆盖 (缺省=示教基准)}
- {name: y_height, type: float, required: false, min: -500.0, max: 500.0, label: 点样Y高度覆盖 (缺省=示教基准)}
```
- 名字 == `spotting.yaml` 组合点位 `spot_pose` 成员 key。min/max 对齐成员 limits (现 ±500; 收尾可收窄到安全点样窗)。
- `required: false` + 缺省不传 → ① 保证走基准。**动作层 `_validate` 仍对给了的值强制 min/max** = 真安全闸。

### ⑤ operation: 补齐 `sampling_execute` 的每轮接口
`eit_ptlc/config/operation/01_sampling/sampling_execute.yaml`:
- 新增 3 个几何旋钮 (`in` FLOAT, **无 default** → 不覆盖即 `None` → 走基准):
  ```yaml
  - {name: spot_x_start, scope: local, type: FLOAT, io: in,
     ui: {label: 点样X起点, group: 点样几何, min: -500.0, max: 500.0, live_from: "spot_pose.x_start"}}
  # spot_x_end / spot_y_height 同型, live_from 指向对应成员
  ```
  `body` 里 `sampling.spot_band_layer` 的 `args` 追加 `x_start: {var: spot_x_start}` 等三行。
- 提升 `well` / `plate_spec` / `plate_no` 为旋钮: 给这三个已有 `in` var 补 `ui:`
  (`well` → label 吸样孔位, group 吸样孔位; 规格/盘位号同组), 使其在下钻树归到 `sampling.aspirate` 名下。
- `sample_volume_ml` 等 (现 `{lit}`) 是**候选**旋钮, 机制已通, 是否暴露交作者按 乙 curate, 本步不强做。

### ⑥ 旋钮收集: 附「消费该旋钮的 action」关联 (供下钻树)
`eit_ptlc/operation/vm/knobs.py` · `collect_knobs`:
- 走 body 时同时记 `call` 节点: 若某 `call.args` 的某项是 `{var: <旋钮名>}`, 给该旋钮记 `action` /
  `action_label` (动作 schema 的 label)。一个旋钮被多 action 引 → 记多个 (下钻树各挂一份, 身份仍是名)。
- `live_from` 旋钮 (⑤): 若给了 `PointsService`, 解析 `spot_pose.x_start` → 附 `live: <当前示教值>` 供面板预填。
  (收集器新增可选 `points` 依赖; 缺省不解析, 离线可测。)

### ⑦ API: knobs 端点带 action 关联
`eit_ptlc/api/app.py` · `GET /api/scripts/{name}/debug/knobs`: 返回结构每项带 `action`/`live` (⑥ 的产物)。
`validate_overrides` **无需改** —— 几何是普通标量 FLOAT 旋钮, 按 `ui.min/max` 走既有校验。

### ⑧ Web: DebugDock 扁平组 → operation → action 下钻树
`eit_ptlc/web/src/components/editor/DebugDock.vue`:
- `knobGroups` (行 43): 分组键从 `ui.group` 改为 **`script → action`** 两级 (无 action 的散旋钮归「其它」);
  渲染成可展开的「operation → action 列表 → 参数」树。`ui.group` 降为 action 内的子标签。
- 几何旋钮 (`live` 非空): number 输入的 `placeholder` = `live` (实时示教值); 「改动即进 map」逻辑
  (`collectOverrides` 行 93) 不变 —— 未动 → 不进 map → 后端走基准。
- 身份仍是**旋钮名**: 同名旋钮挂多个 action 节点是展示, `collectOverrides` 仍按名收一份。

### ⑨ 清理误导信号 (口径 6)
- `config/actions/01_sampling/plc_sampling.yaml:62` 「多带由编排改点表 value 后循环」→ **删/改**为
  「多带由 operation 逐带调用本动作, 每带经 x_start/x_end/y_height 运行前覆盖 (临时, 不改点表)」。
- `config/points/plc/spotting.yaml:9` 「值为 PC 侧真值 (按带/按板, 点表维护…)」→ **改**为
  「点表存**单一示教基准**; 按带差异由运行前临时覆盖 (push 时叠加, 不回写本文件)」。
- `plc_sampling.yaml:80` 「多个条带/多层由 operation 多次调用本动作」→ **保留** (A/B 下依然为真)。
- `config/operation/01_sampling/sampling_spot.yaml` (helper, hidden): 与 `sampling_execute` 口径对齐或标注废弃,
  避免两个「点样」样板讲不同故事。

### ⑩ 测试 (离线)
`eit_ptlc/tests/`:
- `test_action_executor_offline` / 新用例: ① `None` 可选参数被跳过 (不报类型错); 必填 `None` 仍报缺失。
- point_ref + member_overrides: 给 `x_start` → `push_composite` 写覆盖值且 `m.value` 不变; 不给 → 写基准;
  越限 → reject (within_limits on 生效值)。
- `test_knob_override_offline` 扩: `collect_knobs` 正确把 `spot_x_start` 关联到 `spot_band_layer`;
  `well` 提升后归 `sampling.aspirate`。
- (第三步预埋) `for lane in lanes` 逐带喂 `spot_x_start` → 每轮 `push_composite` 收到该行几何 (证 A/B 同接口)。

---

## 3. 不做 / 留到第三步
- **B 声明式批次**: LIST 网格 UI + 批次 op。**已被本步解锁** (几何现在是 VM 旋钮, `for` 循环可逐行喂),
  只差: 批次 op 领域语义 (一次 `prepare` 服务几根? 板物理布局?) + LIST 网格列 schema。
- **偏置模式**: 若现场确认点样须跟视觉校正 (§0 前提), 把几何绝对值换成「基准+偏置」; push 缝/旋钮不变。
- **A 档小 UX**: 人肉循环里面板记住上次值 (倾向) vs 每次归零 —— 收尾定。

## 4. 验收 (本步 = A 交互档打通)
跑 `sampling_execute`: 面板下钻树里 `sampling.aspirate` 见 `well` 可改、`spot_band_layer` 见
`点样X起点/终点/Y高度` 预填示教值可改; 改几根不同的 well+起终点各跑一次 = 手动点多条带,
**全程零逐层 inputs、点表不被改写**。
