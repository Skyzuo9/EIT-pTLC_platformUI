/**
 * 功能: 仿真运行面板的入参/参数行构造与收集 (纯函数, node 可测).
 *
 * 提交契约 (与 DebugDock.collectInputs 逐条对齐, 教训 2026-08-09):
 *   · 取值域经 utils/runInputs.enumOf 归一 —— 曾把 YAML 的 {value,label} 对象整个
 *     绑成 option value, 选中后 parseInt 出 NaN, JSON 序列化成 null, 后端精确报"留空";
 *   · 空串/null = "取脚本默认", **整键不提交** (validate_inputs 的唯一取默认途径);
 *   · 流程入参一律原样字符串提交, 类型交后端 coerce_value (check_enum 两侧同 coerce,
 *     "1" 匹配 INT 声明 1) —— 前端不做数字强转, 就没有 NaN 可漏;
 *   · 单动作参数走 executor 校验 (吃类型值), 保留数字化但 NaN 一律丢弃不提交。
 */
import { enumOf } from '../../utils/runInputs.js'

/**
 * 功能: 流程脚本的 in 变量 -> 表单行.
 * @param {object[]} vars 脚本文档 vars 段
 * @returns {object[]} [{name, label, type, enum|null, default, value}]
 */
export function rowsFromVars(vars) {
  return (vars || [])
    .filter((item) => item?.io === 'in')
    .map((item) => {
      const options = enumOf(item)              // 归一成 [{value:String,label:String}]
      return {
        name: item.name,
        label: item.ui?.label || item.comment || item.name,
        type: String(item.type || '').toUpperCase(),
        enum: options.length ? options : null,
        default: item.default,
        // 初值与 option 的字符串 value 同型, 否则 v-model 匹配不上渲成空白下拉
        value: item.default == null ? '' : String(item.default),
      }
    })
}

/**
 * 功能: 流程入参收集 —— 空值整键不提交(=取默认), 其余原样字符串.
 * @param {object[]} rows rowsFromVars 的产物
 * @returns {object} inputs
 */
export function collectFlowInputs(rows) {
  const out = {}
  for (const row of rows || []) {
    const raw = row.value
    if (raw == null || String(raw).trim() === '') continue
    out[row.name] = String(raw)
  }
  return out
}

/**
 * 功能: 动作参数声明 -> 表单行 (options 摊平成字符串).
 * @param {object[]} params /api/actions/{name} 的 params
 * @returns {object[]}
 */
export function rowsFromParams(params) {
  return (params || []).map((param) => ({
    name: param.name,
    label: param.label || param.name,
    type: String(param.type || '').toUpperCase(),
    enum: (param.options || []).map((opt) => String(opt?.value ?? opt)),
    // 与 option 的字符串同型 (enum 下拉才能选中); coerceParam 会转回声明类型
    value: param.default == null ? '' : String(param.default),
  }))
}

/**
 * 功能: 单动作参数按声明类型转值; 空值/NaN 返回 undefined (= 不提交).
 * @param {object} row rowsFromParams 的一行
 * @returns {*} 类型化的值或 undefined
 */
export function coerceParam(row) {
  if (row.value === '' || row.value === null || row.value === undefined) return undefined
  if (row.type.includes('INT')) {
    const value = Number.parseInt(row.value, 10)
    return Number.isFinite(value) ? value : undefined
  }
  if (row.type.includes('FLOAT') || row.type.includes('REAL')) {
    const value = Number(row.value)
    return Number.isFinite(value) ? value : undefined
  }
  if (row.type.includes('BOOL')) return row.value === true || row.value === 'true'
  return row.value
}

/**
 * 功能: 单动作参数收集 (undefined 键不提交).
 * @param {object[]} rows rowsFromParams 的产物
 * @returns {object} params
 */
export function collectParams(rows) {
  const out = {}
  for (const row of rows || []) {
    const value = coerceParam(row)
    if (value !== undefined) out[row.name] = value
  }
  return out
}
