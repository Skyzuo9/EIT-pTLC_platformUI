// 运行前设置的输入校验 + 上次输入记忆 (localStorage)
// 校验规则镜像后端 operation/vm/expr.py coerce_value — 前端提前拦只是体验加速, 后端仍是最终把关。

// 显式 .js 后缀: 本模块要能被 node --test 直接加载 (Vite 两种写法都认, Node ESM 只认带后缀的)
import { loadJson, saveJson } from './storage.js'

export const STRUCT_TYPES = ['LIST', 'DICT', 'POSE']

// 后端 BOOL 仅认 true/1/yes/on 为真, 其余字符串静默变 False; 白名单拦住"拼错静默变假"的坑
const BOOL_WORDS = ['true', 'false', '1', '0', 'yes', 'no', 'on', 'off']

function rangeError(n, ui) {
  if (ui && ui.min != null && n < ui.min) return `低于下限 ${ui.min}`
  if (ui && ui.max != null && n > ui.max) return `高于上限 ${ui.max}`
  return ''
}

// 有限取值域 -> 下拉选项 [{value, label}]; 无取值域返回 []。三个渲染点 (运行前设置 /
// 调度接线 / 三维演示) 共用这一个读取口, 保证"什么算有限取值"只有一处定义。
//
// value 一律 String(): draft / <option :value> / v-model 全程是字符串, 在这里收口,
// 免得 INT 域的 1 与 '1' 在 v-model 比较处静默不相等 (下拉渲成空白)。
// 兼容期同时认顶层 enum 与旧的 ui.enum; ui.enum 迁移完成后删掉后半段。
export function enumOf(v) {
  const raw = (v && v.enum) || (v && v.ui && v.ui.enum) || null
  if (!Array.isArray(raw) || !raw.length) return []
  return raw.map((o) => (o != null && typeof o === 'object'
    ? { value: String(o.value), label: String(o.label == null ? o.value : o.label) }
    : { value: String(o), label: String(o) }))
}

// ---- 变量定义编辑器用: 取值域 <-> 文本 (每行一项, `值 | 标签`; 标签可省) ----

// 取值域 -> 可编辑文本 (与 parseEnumText 互逆)
export function enumToText(raw) {
  if (!Array.isArray(raw)) return ''
  return raw.map((o) => (o != null && typeof o === 'object'
    ? (o.label == null || String(o.label) === String(o.value) ? String(o.value) : `${o.value} | ${o.label}`)
    : String(o))).join('\n')
}

// 文本 -> 取值域; 空文本返回 [] (调用方据此删掉 enum 字段 —— 后端不接受空 enum)。
// INT/FLOAT 变量的值转成数字: 后端 schema 要求 INT 域必须是 YAML 整数, 存成字符串会被拒。
export function parseEnumText(text, type) {
  const out = []
  for (const line of String(text == null ? '' : text).split('\n')) {
    const s = line.trim()
    if (!s) continue
    const i = s.indexOf('|')
    let value = (i < 0 ? s : s.slice(0, i).trim())
    const label = i < 0 ? '' : s.slice(i + 1).trim()
    if (type === 'INT' || type === 'FLOAT') {
      const n = Number(value)
      if (Number.isFinite(n)) value = type === 'INT' ? Math.trunc(n) : n
    }
    out.push(label && label !== String(value) ? { value, label } : value)
  }
  return out
}

// 校验一个输入框的原始字符串; 返回错误文案, 合法返回空串。留空恒合法 (取默认/零值/示教基准)。
// options (enumOf 的输出) 非空时先做成员判定 —— 陈旧的枚举值 (如已删掉的分支名) 在 STRING
// 上过得了类型检查, 只有成员判定能说清问题; 放最前才能给出准确文案而非"须为整数"之类。
export function validateValue(type, raw, ui, options) {
  if (raw == null || String(raw).trim() === '') return ''
  const s = String(raw).trim()
  if (options && options.length && !options.some((o) => o.value === s)) {
    return '不在可选值内'
  }
  if (type === 'INT') {
    if (!/^[+-]?\d+$/.test(s)) return '须为整数'
    return rangeError(Number(s), ui)
  }
  if (type === 'FLOAT') {
    const n = Number(s)
    if (!Number.isFinite(n)) return '须为数字'
    return rangeError(n, ui)
  }
  if (type === 'BOOL') {
    return BOOL_WORDS.includes(s.toLowerCase()) ? '' : '须为 true/false'
  }
  if (STRUCT_TYPES.includes(type)) {
    let v
    try { v = JSON.parse(s) } catch { return 'JSON 解析失败' }
    if (type === 'LIST' && !Array.isArray(v)) return '须为 JSON 数组'
    if (type === 'DICT' && (typeof v !== 'object' || v === null || Array.isArray(v))) return '须为 JSON 对象'
    if (type === 'POSE' && !(Array.isArray(v) && v.length === 6 && v.every((x) => Number.isFinite(x))))
      return '须为 6 数字数组'
    return ''
  }
  return ''  // STRING 及未知类型不设限
}

// ---- 数值"显示缩放"皮肤: 底层存原值 (如泵速整数 V), 界面按 scale 显示成物理单位 (如 mL/min) ----
// 显示值 = 原值 × scale; 反向 = round(显示值 / scale) 再 clamp 到 [min,max] (min/max 是原值域, 如 V 的 1..500)。
// 单一真源: 旋钮面与动作参数面共用同一 round/clamp 规则。留空恒透传 (=取默认/示教基准, 不写 0)。

// 去浮点尾噪 (0.25 步进恒精确, 此处为通用 scale 兜底)
function _clean(x) {
  return Math.round(x * 1e6) / 1e6
}

// 原值 (字符串/数字) -> 显示字符串; 空/非法/无 scale 时原样返回
export function toDisplay(raw, scale) {
  if (raw == null || String(raw).trim() === '') return ''
  const n = Number(raw)
  if (!Number.isFinite(n) || !scale) return String(raw)
  return String(_clean(n * scale))
}

// 显示字符串 -> 原值字符串 (round 到最近档并 clamp 到 [min,max]); 空/非法/无 scale 时原样返回
export function toRaw(display, scale, min, max) {
  if (display == null || String(display).trim() === '') return ''
  const n = Number(display)
  if (!Number.isFinite(n) || !scale) return String(display)
  let raw = Math.round(n / scale)
  if (min != null && raw < min) raw = min
  if (max != null && raw > max) raw = max
  return String(raw)
}

// ---- 上次输入记忆: 按流程名一档, 存原始字符串 draft (与面板同型) ----

const lastKey = (name) => `ptlc.lastRunInputs.${name}`

export function loadLastInputs(name) {
  const v = loadJson(lastKey(name), null)
  return v && typeof v === 'object' ? v : null
}

export function saveLastInputs(name, record) {
  saveJson(lastKey(name), record)
}

// 回填清洗: 丢掉"上次输入"里已不在取值域内的值 (分支被改名/删掉后, localStorage 里
// 还留着旧值), 返回 {values, dropped} —— dropped 是被丢弃的变量名, 供横幅点名。
//
// 与旋钮侧 (保留 + 标红 + 禁启动, 见 DebugDock 的 knobErrors) **刻意分叉**:
// 旋钮的陈旧值往往是个仍有意义的数 (只是超了新上限), 值得让人看见再自行改;
// 选择子的陈旧值就是个已不存在的分支名, 保留它只会让人在禁用态下困惑, 不如直接
// 退回默认并说明。改这里前请先想清楚这个区别, 不要图"统一"把两者并成一种行为。
export function sanitizeRestored(vars, values) {
  const out = {}
  const dropped = []
  for (const [k, v] of Object.entries(values || {})) {
    const vd = (vars || []).find((x) => x && x.name === k)
    const opts = enumOf(vd)
    if (opts.length && v != null && String(v) !== '' && !opts.some((o) => o.value === String(v))) {
      dropped.push(k)
      continue
    }
    out[k] = v
  }
  return { values: out, dropped }
}
