/**
 * 功能: 演示页"面板入参"与"精编译片段里烘死的那组入参"的比对 —— 纯函数, 可单测.
 *
 * 为什么单独成模块而不是留在 DemoView.vue 里: 下面三个坑一个比一个隐蔽, 而 DemoView.vue
 * 今天没有任何测试。本仓的惯例是把这类判据抽成纯 .js 再挂单测(motionMap / flowSim /
 * actionSim 都是这么做的) —— 留在 .vue 里等于这三个坑没有守门人。
 *
 * 三个坑(每一个都会让按钮在错误的时刻出现或消失, 而画面完全正常):
 *
 *   1. **面板值全是字符串。** DemoView 装载时把入参一律 `String()` 化(为了让 <select> 的
 *      option 值匹配得上), 而片段里的 `operation.inputs` 是真类型(0.1 / 1)。直接 !== 比,
 *      每条流程都会永远显示"参数已改"。
 *
 *   2. **空串是"取默认", 不是空值。** 下拉里有一项 `<option value="">— 取默认 —</option>`,
 *      选中它意味着"用脚本自己的 default", 该拿 default 去比而不是拿 '' 去比。
 *
 *   3. **片段里的键比面板多。** clip_compiler.default_bindings 会把带 default 的
 *      `io: var` / `io: out` 也一并烘进 operation.inputs。实测 flow.sampling_execute
 *      片段侧 22 个键、面板侧(io:in)只有 17 个, 多出 aspirate_round_ml / aspirate_total_ml /
 *      band_end_ml / round_idx / spray_margin_ml 五个 —— 天真的 deepEqual 会让那条流程的
 *      "重编这一条"按钮**永久常亮**。
 *      ⇒ **比较必须以面板的 inputVars 为准遍历, 片段里多出来的键一律忽略。**
 */

/**
 * 功能: 把一个取值归一成可比较的形式.
 *
 * 数值一律按数比(于是 "0.10" 与 0.1 判相同); 其余按去空白的字符串比。
 * 布尔转成 'true'/'false' 与面板的字符串形态对齐。
 *
 * @param {*} value 取值
 * @returns {number|string} 归一结果
 */
function normalize(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  const text = String(value).trim()
  if (text === '') return ''
  const number = Number(text)
  return Number.isFinite(number) ? number : text
}

/**
 * 功能: 取面板上某个入参的**有效值** —— 空串回落到该变量的 default(坑 2).
 *
 * @param {object} panelInputs 面板入参 {名: 值}
 * @param {object} varItem 该变量的声明(需含 name, 可含 default)
 * @returns {number|string} 归一后的有效值
 */
function effective(panelInputs, varItem) {
  const raw = panelInputs?.[varItem.name]
  const picked = (raw === undefined || raw === null || String(raw).trim() === '')
    ? varItem.default
    : raw
  return normalize(picked)
}

/**
 * 功能: 面板入参与片段烘死的那组入参是否不同 —— 决定"按这组入参编这一条"按钮出不出.
 *
 * 只遍历面板声明的 io:in 变量(坑 3); 片段里没有的键按该变量的 default 比 ——
 * 片段总是带全的, 真缺了说明这条片段是老版本编的, 那时按"不同"处理更保守。
 *
 * @param {object|null} clipInputs 片段的 operation.inputs
 * @param {object} panelInputs 面板入参
 * @param {Array<{name: string, default?: *}>} inputVars 面板声明的 io:in 变量
 * @returns {boolean} 不同则 true
 */
export function inputsDiffer(clipInputs, panelInputs, inputVars) {
  if (!clipInputs || !Array.isArray(inputVars) || inputVars.length === 0) return false
  for (const item of inputVars) {
    if (!item?.name) continue
    const want = effective(panelInputs, item)
    const has = Object.prototype.hasOwnProperty.call(clipInputs, item.name)
      ? normalize(clipInputs[item.name])
      : normalize(item.default)
    if (want !== has) return true
  }
  return false
}

/**
 * 功能: 面板这组入参能不能在该流程**已编好的变体**里找到 —— 找到就秒切下标, 不必重编.
 *
 * 变体(flow_params.yaml 扇出的那些)与临时片段(--inputs 编的)在 flow-index 里是同一种形状,
 * 所以这一个函数同时服务两者: 用户把参数改回某个已有变体的取值, 立刻切回去, 零等待。
 *
 * @param {object|null} entry flow-index 的一条 {clips: [{variant: [{key, value}]}]}
 * @param {object} panelInputs 面板入参
 * @param {Array<{name: string, default?: *}>} inputVars 面板声明的 io:in 变量
 * @returns {number} 命中的 clips 下标; 没命中返回 -1
 */
export function matchVariantIndex(entry, panelInputs, inputVars) {
  const clips = entry?.clips
  if (!Array.isArray(clips) || clips.length === 0) return -1
  const byName = new Map((inputVars || []).filter((item) => item?.name)
    .map((item) => [item.name, item]))

  for (let index = 0; index < clips.length; index += 1) {
    const variant = clips[index]?.variant
    if (!Array.isArray(variant)) continue
    // 变体只声明"与默认不同的那几维"。所以两头都要查:
    //   ① 变体点名的每一维, 面板值必须与它相同;
    //   ② 变体没点名的每一维, 面板值必须等于默认(否则这条变体表达不了当前这组参数)。
    const named = new Set(variant.map((item) => item?.key).filter(Boolean))
    let hit = true
    for (const item of variant) {
      const decl = byName.get(item?.key)
      if (!decl) { hit = false; break }          // 变体维不在面板声明里 —— 不认
      if (effective(panelInputs, decl) !== normalize(item.value)) { hit = false; break }
    }
    if (!hit) continue
    for (const decl of byName.values()) {
      if (named.has(decl.name)) continue
      if (effective(panelInputs, decl) !== normalize(decl.default)) { hit = false; break }
    }
    if (hit) return index
  }
  return -1
}
