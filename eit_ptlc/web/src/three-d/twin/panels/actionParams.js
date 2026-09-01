/**
 * 功能: 原子动作参数表单的纯逻辑 —— 默认值、类型归一、必填检查.
 *
 * 抽出来是因为有两个消费方且规则必须一致: 动作执行表单(ActionQuickForm, 真下发硬件)
 * 与演示子页(ActionDemoPane, 只算模拟)。规则漂了会出现"演示里填得进、执行时被拒"。
 *
 * 纯函数, 零 Vue/three 依赖, 可 node --test.
 *
 * 注意 DTO 的字段名: 后端 ActionParamDTO 用的是 `minimum` / `maximum`(pydantic 字段名),
 * 不是 `min` / `max`。两个都认是为了容忍历史调用方。
 */

/**
 * 功能: 取参数下限(兼容 minimum/min 两种写法).
 * @param {object} param 参数定义
 * @returns {number|null} 下限, 未声明返回 null
 */
export function minOf(param) {
  const value = param?.minimum ?? param?.min
  return value === undefined || value === null ? null : Number(value)
}

/**
 * 功能: 取参数上限(兼容 maximum/max 两种写法).
 * @param {object} param 参数定义
 * @returns {number|null} 上限, 未声明返回 null
 */
export function maxOf(param) {
  const value = param?.maximum ?? param?.max
  return value === undefined || value === null ? null : Number(value)
}

/**
 * 功能: 按参数 schema 生成初始值.
 *
 * 无 default 的参数一律给空串而不是 0: 空串在 coerceParams 里被跳过, 后端因此取
 * 自己的默认(泵档常量/示教基准)。填 0 会把"没填"变成"显式要求 0", 是两回事。
 * @param {Array} params 参数定义数组
 * @returns {object} 参数名 -> 初值
 */
export function defaultValuesOf(params) {
  const next = {}
  for (const param of params || []) {
    if (param.default !== undefined && param.default !== null) next[param.name] = param.default
    else if (param.type === 'bool') next[param.name] = false
    else next[param.name] = ''
  }
  return next
}

/**
 * 功能: 把表单值转换成后端期望的类型(空值跳过).
 * @param {Array} params 参数定义数组
 * @param {object} values 表单值
 * @returns {object} 可直接发给 /api/actions/{name}/run 的参数字典
 */
export function coerceParams(params, values) {
  const payload = {}
  for (const param of params || []) {
    const raw = values?.[param.name]
    if (raw === '' || raw === undefined || raw === null) continue
    if (param.type === 'int') payload[param.name] = Number.parseInt(raw, 10)
    else if (param.type === 'float') payload[param.name] = Number.parseFloat(raw)
    else if (param.type === 'bool') payload[param.name] = Boolean(raw)
    else payload[param.name] = raw
  }
  return payload
}

/**
 * 功能: 列出未填的必填参数(显示名).
 * @param {Array} params 参数定义数组
 * @param {object} values 表单值
 * @returns {string[]} 未填项的显示名
 */
export function missingRequiredOf(params, values) {
  return (params || [])
    .filter((param) => param.required)
    .filter((param) => {
      const value = values?.[param.name]
      return value === undefined || value === null || value === ''
    })
    .map((param) => param.label || param.name)
}

/**
 * 功能: 判断动作在当前控制模式下是否允许执行.
 * @param {object} action 动作定义
 * @param {string} controlMode 当前模式(RUN/DEBUG)
 * @returns {boolean} 是否允许
 */
export function modeAllows(action, controlMode) {
  const modes = action?.modes
  if (!Array.isArray(modes) || modes.length === 0) return true
  if (!controlMode) return true
  return modes.some((mode) => String(mode).toUpperCase() === String(controlMode).toUpperCase())
}
