/**
 * 功能: 把「显示 → 模块视角设定」存下的机位写回 manifest 的 stations[].camera.
 *
 * ⚠ **必须写"当前页正在用的那一份" manifest。** /3d/live 与演示页加载的是
 *   device-manifest.official-cr5.json, 装配台默认页才是 device-manifest.json ——
 *   2026-08-15 之前这里写死基础版键, 实时页保存的视角落进了没人读的文件,
 *   刷新即"丢失"。调用方用 manifestKeyForUrl(manifestUrl) 推导键并逐调用传入。
 *
 * 为什么写这个字段而不是新开一份配置: manifest 里**本来就有** stations[].camera{pos,target},
 * 管线 gen_twin_manifest.merge_preserving 认字段内的 manual: true 为人工标记, 重跑不覆盖。
 * 一个工位只该有一个"官方机位"。副作用是演示页 ClipPlayer 的 camera 事件读的也是它 ——
 * 存完演示动画飞向该工位的镜头会跟着变, 这一条在 UI 上如实写着。
 *
 * ⚠ **绝不整体 JSON.stringify 回写。** 实测过: 把这份文件在 JS 里 parse 再 stringify,
 *   441 行会变 —— Python 的 json.dump 把浮点 3.0 写成 "3.0", JS 写成 "3"; 加上文件是
 *   CRLF 而 JS 输出 LF, 于是"改一个机位"的 diff 会变成整个文件。所以这里做**定点文本替换**:
 *   只重排那一个 camera 块, 其余字节原样不动, 数字也照 Python 风格补小数点。
 *
 * 并发: manifest 现在有了第二个写入方(过去只有管线)。照 motion/rigWriter.js 同款做
 *   读-改-写 + 基线比对, 中途被别人改过就报冲突让人决定, 不闷头覆盖。后端 write_file
 *   还会留一份 .bak 兜底。
 */
import * as api from '../workbench/authoringApi.js'

/** 后端 _writable_files() 里两份 manifest 的键名(基础版 / official-cr5 变体) */
const MANIFEST_KEYS = new Set(['device_manifest', 'device_manifest_cr5'])

/** 上一次经本模块读到/写出的原文(按 manifest 键分开记); 用于识别第三方改动 */
const lastSeen = new Map()

/**
 * 功能: 从页面的 manifestUrl 推导后端写盘键.
 * @param {string} url manifest 资产地址
 * @returns {string} 'device_manifest_cr5' 或 'device_manifest'
 */
export function manifestKeyForUrl(url) {
  return String(url || '').includes('official-cr5') ? 'device_manifest_cr5' : 'device_manifest'
}

/**
 * 功能: 拦下拼错/漏传的 manifest 键 —— 写错文件是静默数据丢失, 必须炸在门口.
 * @param {string} manifestKey 写盘键
 * @returns {void}
 */
function assertManifestKey(manifestKey) {
  if (!MANIFEST_KEYS.has(manifestKey)) {
    throw new Error(`未知的 manifest 写盘键: ${manifestKey}`)
  }
}

/**
 * 功能: 按 Python json.dump 的浮点风格格式化数字(整数值也带小数点).
 *
 * 文件其余部分是 Python 写的, 里面写着 "intensity": 3.0。这里若写成 3, 下次管线重跑
 * 读回来是 int 再写出去还是 3 —— 风格分叉从此固定下来。补个 .0 就没这事。
 * @param {number} value 数值
 * @returns {string} 字面量
 */
function formatNumber(value) {
  return Number.isInteger(value) ? `${value}.0` : String(value)
}

/**
 * 功能: 从 open 位置起做括号配对(跳过字符串字面量与转义).
 * @param {string} text 原文
 * @param {number} open 起始括号下标
 * @returns {number} 匹配的闭括号下标; 找不到为 -1
 */
function matchBracket(text, open) {
  const pairs = { '{': '}', '[': ']' }
  const close = pairs[text[open]]
  if (!close) return -1
  let depth = 0
  let inString = false
  for (let i = open; i < text.length; i += 1) {
    const ch = text[i]
    if (inString) {
      if (ch === '\\') i += 1
      else if (ch === '"') inString = false
      continue
    }
    if (ch === '"') inString = true
    else if (ch === text[open]) depth += 1
    else if (ch === close) {
      depth -= 1
      if (depth === 0) return i
    }
  }
  return -1
}

/**
 * 功能: 定位某个工位的 camera 块在原文里的区间.
 * @param {string} text manifest 原文
 * @param {string} stationId 工位 id
 * @returns {{start: number, end: number, indent: string}|null} 区间与缩进
 */
function locateCameraBlock(text, stationId) {
  // 先把搜索范围收进 stations 数组 —— axes/actuators 里也有 "id", 不收范围会串台
  const stationsKey = text.indexOf('"stations"')
  if (stationsKey < 0) return null
  const arrayOpen = text.indexOf('[', stationsKey)
  if (arrayOpen < 0) return null
  const arrayClose = matchBracket(text, arrayOpen)
  if (arrayClose < 0) return null

  const scope = text.slice(arrayOpen, arrayClose)
  const idPattern = new RegExp(`"id"\\s*:\\s*"${stationId}"`)
  const idHit = idPattern.exec(scope)
  if (!idHit) return null

  // 只在"本工位到下一个工位的 id"之间找 camera, 免得越界改到下一个工位
  const afterId = idHit.index + idHit[0].length
  const nextId = /"id"\s*:\s*"/.exec(scope.slice(afterId))
  const limit = nextId ? afterId + nextId.index : scope.length
  const cameraHit = /"camera"\s*:\s*\{/.exec(scope.slice(afterId, limit))
  if (!cameraHit) return null

  const braceInScope = afterId + cameraHit.index + cameraHit[0].length - 1
  const braceEnd = matchBracket(scope, braceInScope)
  if (braceEnd < 0) return null

  // 取 "camera" 这一行的缩进, 用来排新块(不硬编码 6 空格)
  const keyStart = afterId + cameraHit.index
  const lineStart = scope.lastIndexOf('\n', keyStart) + 1
  const indent = scope.slice(lineStart, keyStart)

  return { start: arrayOpen + braceInScope, end: arrayOpen + braceEnd, indent }
}

/**
 * 功能: 把一个 camera 对象排成与文件其余部分同款的多行 JSON 文本.
 * @param {object} camera 机位对象
 * @param {string} indent "camera" 键那一行的缩进
 * @param {string} eol 换行符(跟随原文, 别把 CRLF 文件写成 LF)
 * @returns {string} 从 { 到 } 的文本
 */
function formatCameraBlock(camera, indent, eol) {
  /**
   * 递归排一个值(只需支持数字数组、布尔与嵌套对象 —— camera 里没有别的形状).
   * @param {*} value 值
   * @param {string} pad 该值所在层的缩进
   * @returns {string} 文本
   */
  const emit = (value, pad) => {
    if (Array.isArray(value)) {
      const inner = `${pad}  `
      return `[${eol}${value.map((v) => `${inner}${formatNumber(v)}`).join(`,${eol}`)}${eol}${pad}]`
    }
    if (value && typeof value === 'object') {
      const inner = `${pad}  `
      const body = Object.entries(value)
        .map(([key, val]) => `${inner}"${key}": ${emit(val, inner)}`)
        .join(`,${eol}`)
      return `{${eol}${body}${eol}${pad}}`
    }
    if (typeof value === 'boolean') return String(value)
    return formatNumber(value)
  }

  // 键序固定 pos → target → manual → auto, 与生成器一致, 免得每次保存 diff 里键在跳
  const ordered = {}
  ordered.pos = camera.pos
  ordered.target = camera.target
  if (camera.manual) ordered.manual = true
  if (camera.auto) ordered.auto = { pos: camera.auto.pos, target: camera.auto.target }
  return emit(ordered, indent)
}

/**
 * 功能: 定点替换某工位的 camera 块(纯函数, 可单测).
 * @param {string} text manifest 原文
 * @param {string} stationId 工位 id
 * @param {object} camera 新的 camera 对象 {pos, target, manual?, auto?}
 * @returns {string} 新原文
 * @throws {Error} 找不到该工位或它的 camera 块
 */
export function patchStationCamera(text, stationId, camera) {
  const found = locateCameraBlock(text, stationId)
  if (!found) throw new Error(`manifest 里找不到工位 ${stationId} 的 camera 字段`)
  // 换行符跟随原文: 这份文件在 Windows 上是 CRLF, 写成 LF 会让 diff 变成整个文件
  const eol = text.includes('\r\n') ? '\r\n' : '\n'
  const block = formatCameraBlock(camera, found.indent, eol)
  return text.slice(0, found.start) + block + text.slice(found.end + 1)
}

/**
 * 功能: 读一次 manifest 原文并记录基线.
 * @param {string} manifestKey 写盘键(manifestKeyForUrl 推导)
 * @returns {Promise<string>} JSON 原文
 */
export async function readManifestText(manifestKey) {
  assertManifestKey(manifestKey)
  const text = await api.readFile(manifestKey)
  lastSeen.set(manifestKey, text)
  return text
}

/**
 * 功能: 读-改-写一次 manifest.
 * @param {string} manifestKey 写盘键(manifestKeyForUrl 推导)
 * @param {(text: string) => string} patch 纯补丁函数
 * @param {object} [options] 选项
 * @param {boolean} [options.force=false] 检测到第三方改动时仍然写入
 * @returns {Promise<{ok: boolean, conflict?: boolean, path?: string}>} 结果
 */
export async function patchManifest(manifestKey, patch, { force = false } = {}) {
  assertManifestKey(manifestKey)
  const current = await api.readFile(manifestKey)
  const seen = lastSeen.get(manifestKey)
  if (force === false && seen !== undefined && current !== seen) {
    // 不覆盖: 基线更新到盘上现状, 调用方重试一次即可打在最新文本上
    lastSeen.set(manifestKey, current)
    return { ok: false, conflict: true }
  }
  const next = patch(current)
  const result = await api.writeFile(manifestKey, next)
  lastSeen.set(manifestKey, next)
  return { ok: true, path: result?.path || '' }
}

/**
 * 功能: 把当前机位存成某工位的跳转视角.
 *
 * 首次人工设定时把管线自动烘的那份塞进 camera.auto —— 「清除」要能真的还原回去,
 * 否则清完留下的还是用户自己那份, 只是不再被 flyToStation 采用, 而演示页仍在用它。
 * @param {string} manifestKey 写盘键(manifestKeyForUrl 推导, 必须是页面在用的那份)
 * @param {string} stationId 工位 id
 * @param {object} camera 新机位 {pos, target}
 * @param {object|null} previous 该工位当前的 camera(取 auto 用)
 * @param {object} [options] 选项
 * @returns {Promise<object>} 结果
 */
export function saveStationCamera(manifestKey, stationId, camera, previous, options = {}) {
  const auto = previous?.auto
    || (previous?.pos && previous?.target ? { pos: previous.pos, target: previous.target } : null)
  const next = { pos: camera.pos, target: camera.target, manual: true }
  if (auto) next.auto = auto
  return patchManifest(manifestKey, (text) => patchStationCamera(text, stationId, next), options)
}

/**
 * 功能: 清除人工机位, 还原成管线自动烘的那份(没有存过 auto 就只摘掉 manual 标记).
 * @param {string} manifestKey 写盘键(manifestKeyForUrl 推导)
 * @param {string} stationId 工位 id
 * @param {object|null} previous 该工位当前的 camera
 * @param {object} [options] 选项
 * @returns {Promise<object>} 结果
 */
export function clearStationCamera(manifestKey, stationId, previous, options = {}) {
  const auto = previous?.auto
  const next = auto
    ? { pos: auto.pos, target: auto.target }
    : { pos: previous?.pos || [0, 0, 0], target: previous?.target || [0, 0, 0] }
  return patchManifest(manifestKey, (text) => patchStationCamera(text, stationId, next), options)
}

/**
 * 功能: 丢弃基线(换页后调, 避免拿过期基线误判冲突).
 * @returns {void}
 */
export function resetManifestBaseline() {
  lastSeen.clear()
}
