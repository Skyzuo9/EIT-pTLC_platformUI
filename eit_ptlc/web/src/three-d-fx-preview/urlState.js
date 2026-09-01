/**
 * 功能: URL 参数 <-> 页面状态. URL 即完整场景描述 —— 面板任何改动回写地址栏,
 * 把地址复制给别人(或截图脚本)就能复现同一画面.
 *
 * 第三轮清理: style(双风格已退役, 白卡统一)/rings/scan/flow 相关键全部移除;
 * 新增 debug(悬停卡显示零件名, 指认错归零件用).
 */

/** 全部特效名(cards = 状态圆点+悬浮卡) */
export const FX_KEYS = ['cards', 'focus', 'tour', 'intro']

const DEFAULT_FX = ['cards', 'focus']

/**
 * 功能: 解析 URL 查询参数为页面状态(带全部默认值).
 * @param {string} search location.search
 * @returns {object} 页面状态
 */
export function parseUrlState(search) {
  const q = new URLSearchParams(search)
  const fxRaw = q.get('fx')
  let fx
  if (fxRaw === 'all') fx = new Set(FX_KEYS)
  else if (fxRaw) fx = new Set(fxRaw.split(',').map((s) => s.trim()).filter((s) => FX_KEYS.includes(s)))
  else fx = new Set(DEFAULT_FX)

  const num = (key, fallback) => {
    const v = Number(q.get(key))
    return Number.isFinite(v) && q.get(key) !== null && q.get(key) !== '' ? v : fallback
  }

  return {
    theme: q.get('theme') === 'light' ? 'light' : 'dark',
    fx,
    scenario: ['idle', 'running', 'error', 'showcase'].includes(q.get('scenario')) ? q.get('scenario') : 'running',
    quality: q.get('quality') === 'low' ? 'low' : 'high',
    speed: num('speed', 1),
    focus: q.get('focus') || '',
    cam: q.get('cam') || 'iso',
    step: q.has('step') ? num('step', 0) : null,
    freeze: q.get('freeze') === '1',
    freezetime: q.has('freezetime') ? num('freezetime', 0) : null,
    // intro 缺省: fx 含 intro 时自动播一次; intro=0 显式抑制(截图矩阵默认抑制)
    intro: q.get('intro') !== '0',
    panel: q.get('panel') !== '0',
    clip: q.get('clip') || '',
    clipt: q.has('clipt') ? num('clipt', 0) : null,
    isolate: ['ghost', 'hide', 'off'].includes(q.get('isolate')) ? q.get('isolate') : '',
    debug: q.get('debug') === '1',
    aa: q.get('aa') !== '0',
    dpr: q.has('dpr') ? num('dpr', 0) : null,
    autorotate: q.get('autorotate') === '1',
  }
}

/**
 * 功能: 把页面状态序列化回查询串(只写非默认项, 保持地址干净; cfg.* 覆写原样保留).
 * @param {object} state 页面状态
 * @param {string} currentSearch 当前 location.search(为了带上 cfg.* 覆写)
 * @returns {string} 查询串(不带 '?', 可能为空)
 */
export function serializeUrlState(state, currentSearch = '') {
  const q = new URLSearchParams()
  if (state.theme !== 'dark') q.set('theme', state.theme)
  const fxList = FX_KEYS.filter((k) => state.fx.has(k))
  if (fxList.length === FX_KEYS.length) q.set('fx', 'all')
  else if (fxList.join(',') !== DEFAULT_FX.join(',')) q.set('fx', fxList.join(','))
  if (state.scenario !== 'running') q.set('scenario', state.scenario)
  if (state.quality !== 'high') q.set('quality', state.quality)
  if (state.speed !== 1) q.set('speed', String(state.speed))
  if (state.focus) q.set('focus', state.focus)
  if (state.cam !== 'iso') q.set('cam', state.cam)
  if (state.step !== null && state.step !== undefined) q.set('step', String(state.step))
  if (state.freeze) q.set('freeze', '1')
  if (state.freezetime !== null && state.freezetime !== undefined) q.set('freezetime', String(state.freezetime))
  if (!state.intro) q.set('intro', '0')
  if (!state.panel) q.set('panel', '0')
  if (state.clip) q.set('clip', state.clip)
  if (state.clipt !== null && state.clipt !== undefined) q.set('clipt', String(state.clipt))
  if (state.isolate) q.set('isolate', state.isolate)
  if (state.debug) q.set('debug', '1')
  if (!state.aa) q.set('aa', '0')
  if (state.dpr) q.set('dpr', String(state.dpr))
  if (state.autorotate) q.set('autorotate', '1')
  for (const [key, value] of new URLSearchParams(currentSearch).entries()) {
    if (key.startsWith('cfg.')) q.set(key, value)
  }
  return q.toString()
}
