# 运行前设置 (启动变量输入) 体验优化 — 设计

日期: 2026-07-11
范围: `eit_ptlc/web`(纯前端, 无后端改动)
背景: 流程页 DebugDock「运行前设置」浮层三项体验缺陷 (用户选定 B2/B3/B4; B1 类型化控件本轮不做)。

## 后端事实 (校验规则的镜像依据)

`operation/vm/expr.py::coerce_value`:

- INT=`int(value)` (整数字面量), FLOAT=`float(value)`, POSE=6 数字分量, LIST/DICT=可转列表/字典。
- **BOOL 静默坑**: 字符串仅 `true/1/yes/on` 为真, 其余任何字符串 (含拼错的 `ture`、中文) **静默变 False 不报错** — 前端白名单拦截价值最大。
- **无必填概念**: 无 default 的裸入参留空 → `coerce_value(None)` 落类型零值 (0/""/false/零POSE/空列表) 静默跑; 无 default 的旋钮留空 → None → 走示教基准 (有意设计, 不动)。
- 旋钮 min/max/enum 由 `knobs.py::validate_overrides` 服务端把关 (4xx); 前端提前拦只是体验加速, 后端仍是最终防线。

## B2 启动前校验

- 新 util `web/src/utils/runInputs.js::validateValue(type, raw, ui)` → 错误文案或空串。规则:
  - 留空恒合法 (默认/零值/基准)。
  - INT: `/^[+-]?\d+$/`; FLOAT: `Number()` 有限; BOOL: 白名单 `true/false/1/0/yes/no/on/off` (小写比对);
    LIST/DICT/POSE: JSON.parse 成功且形状正确 (数组/纯对象/6 数字数组)。
  - INT/FLOAT 带 `ui.min/max` 时查范围 (旋钮)。enum 旋钮只查成员资格 (select 常态合法,
    但 B3 回填的陈旧值可能已不在枚举里, 此时 select 显示空白且提交会被服务端 4xx — 前端提前标红)。
- UI: 出错输入框红框, 注释列文案替换为红色错误; 底部「N 项有误」+ 启动按钮禁用; Enter 启动同受 `errorCount` 拦截。
- 无默认值且留空的裸入参: 注释列黄色提示「留空将以零值运行」, **不拦截** (决策: 尊重后端语义, 提示不禁止)。

## B3 记住上次输入

- 存储: `localStorage["ptlc.lastRunInputs.<流程名>"]` = `{inputs: 裸入参draft, knobs: 旋钮draft, ts}`, 原始字符串形 (与面板 draft 同型)。启动成功 (校验通过, `debug.start` 前) 写入。换浏览器即丢, 上位机单机可接受。
- 回填: 打开面板先铺默认值, 再叠加上次记录 (**只回填当前仍存在的变量/旋钮名**, 改名/删除自动失效); 标题下横幅「已回填上次输入 (MM-DD HH:mm)」+「恢复默认」按钮 (决策: 自动回填, 适配反复实验场景)。
- 旋钮 changed 高亮与默认值比对逻辑不变, 回填后自然显示哪些偏离默认。

## B4 旋钮树折叠 + 只看已改动

- operation/action 两级头部点击折叠 (▸/▾), 折叠态会话级 reactive map (不持久化)。
- 旋钮区标题加「只看已改动 (N)」checkbox: 开启后按 `knobChanged` 过滤, 空 action/operation 组隐藏; N=0 且开启时显示「无改动项」提示。
- operation 组头显示本组改动数徽标 (`M 改动`), 折叠时也可见。

## 改动面

- 新增 `web/src/utils/runInputs.js` (校验 + localStorage 读写, STRUCT_TYPES 常量迁入)。
- 修改 `web/src/components/editor/DebugDock.vue` (校验绑定/回填横幅/折叠与过滤视图 knobView)。
- 修改 `web/src/style.css` (`.err/.cell-err/.cell-warn/.restored/.fold/.caret/.chg-badge` 等)。
- 后端零改动; `collectInputs/collectOverrides` 容错分支保留 (后端仍兜底)。

## 验证

- `npm run build` 通过; `node --input-type=module` 快速跑 validateValue 边界用例 (无 vitest 设施, 不新引框架)。
- 手工: 敲坏 JSON/超范围/BOOL 拼错 → 红框禁启动; 启动后重开面板 → 回填+横幅; 折叠/筛选行为。
