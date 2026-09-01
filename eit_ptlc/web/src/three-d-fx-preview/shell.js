/**
 * 功能: 仿正式应用外壳(chrome 层, 非特效) —— 左侧图标竖栏 + 顶部态势条 + 3D 页签条.
 * 让沙盒"看起来像未来实际使用的界面"(用户第四轮定夺).
 *
 * 结构与样式来源(逐字照抄正式页, 全局类零成本复用 —— main.js 已 import ../style.css):
 *   - 侧栏 13 项与 SVG path 数据: components/RailNav.vue:12-42(Feather 风描边);
 *   - 顶栏 11 元素: components/StatusBar.vue:125-183(模式 select/实时在线/运行指示/
 *     四健康计数/站点/末端/主题钮/底栏钮/恢复布局/急停);
 *   - 页签条: three-d/App.vue:14-20(装配/材质/动作/演示/实时, 本页标"实时"态).
 *
 * 活数据(比静态贴图"更真"的关键): 四健康计数吃 pushState 同源工位状态; ▶ 运行指示
 * 绑流程片段播放(无片段时显示当前模拟剧本). 侧栏/页签是惰性链接(preventDefault),
 * 急停/模式/底栏钮仿外观不接功能 —— 沙盒不碰真机.
 */

/** 侧栏 13 项(key/label/d 逐字照 RailNav.vue; three_d 是本页高亮项) */
const RAIL_TABS = [
  { key: 'plc', label: 'PLC', d: ['M7 4h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3Z', 'M9.5 9.5h5v5h-5Z', 'M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2'] },
  { key: 'nodes', label: '设备', d: ['M4.5 4h15A1.5 1.5 0 0 1 21 5.5v3A1.5 1.5 0 0 1 19.5 10h-15A1.5 1.5 0 0 1 3 8.5v-3A1.5 1.5 0 0 1 4.5 4Z', 'M4.5 14h15a1.5 1.5 0 0 1 1.5 1.5v3a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5v-3A1.5 1.5 0 0 1 4.5 14Z', 'M6.5 7h.01M6.5 17h.01'] },
  { key: 'three_d', label: '3D', d: ['M12 2.8 20 7.2v9.6L12 21.2 4 16.8V7.2L12 2.8Z', 'M4.3 7.4 12 11.7l7.7-4.3', 'M12 11.7v9.2'] },
  { key: 'action', label: '动作', d: ['M13 2 3 14h9l-1 8 10-12h-9l1-8Z'] },
  { key: 'operation', label: '流程', d: ['M4 4h6v6H4Z', 'M14 14h6v6h-6Z', 'M10 7h4a3 3 0 0 1 3 3v4'] },
  { key: 'schedule', label: '调度', d: ['M9.5 2.5h5v4h-5Z', 'M3 10h5v4H3Z', 'M16 10h5v4h-5Z', 'M9.5 17.5h5v4h-5Z', 'M12 6.5v1.2a1.3 1.3 0 0 1-1.3 1.3H5.5', 'M12 6.5v1.2a1.3 1.3 0 0 0 1.3 1.3h5.2', 'M5.5 14v1.2a1.3 1.3 0 0 0 1.3 1.3H12', 'M18.5 14v1.2a1.3 1.3 0 0 1-1.3 1.3H12'] },
  { key: 'points', label: '点位', d: ['M12 5.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Z', 'M12 2v3.5M12 18.5V22M2 12h3.5M18.5 12H22', 'M12 12h.01'] },
  { key: 'vision', label: '视觉', d: ['M9.5 4h5l2 3H20a1.5 1.5 0 0 1 1.5 1.5V18a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 18V8.5A1.5 1.5 0 0 1 4 7h3.5l2-3Z', 'M12 9.5a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z'] },
  { key: 'water_level', label: '液位', d: ['M12 3.5c3.6 4.1 5.5 6.9 5.5 9.5a5.5 5.5 0 0 1-11 0c0-2.6 1.9-5.4 5.5-9.5Z', 'M9 14.5h6'] },
  { key: 'planner', label: '排程', d: ['M5 5.5h14A1.5 1.5 0 0 1 20.5 7v12a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V7A1.5 1.5 0 0 1 5 5.5Z', 'M8 3v4M16 3v4M3.5 10.5h17', 'M7 14h6M11 17h6'] },
  { key: 'scheduler', label: '实验', d: ['M4 6h7M4 12h7M4 18h7', 'M15 5.5 21 9l-6 3.5v-7Z', 'M15 14.5h6M15 18h6'] },
  { key: 'materials', label: '物料', d: ['M12 2.5 20.5 7v10L12 21.5 3.5 17V7L12 2.5Z', 'M3.7 7.2 12 11.7l8.3-4.5', 'M12 11.7v9.6'] },
  { key: 'runs', label: '执行记录', d: ['M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8', 'M3 3v5h5', 'M12 7v5l4 2'] },
]

/** 页签清单(label/hint 照 three-d/App.vue; 本页 = "实时"工作台的增强显示预览) */
const WORK_TABS = [
  { key: 'workbench', label: '装配', hint: '白模删减预览 · 点选授权' },
  { key: 'materials', label: '材质', hint: '材质类 + 单零件 · 实时生效' },
  { key: 'motion', label: '动作', hint: '运动模式 · 标定 · 原子动作演示' },
  { key: 'demo', label: '演示', hint: '实机全部流程 · 自动生成动画' },
  { key: 'live', label: '实时', hint: '增强显示效果预览 · 沙盒(不写入真机)', active: true },
]

/** 模拟剧本的中文名(运行指示无片段时显示) */
const SCENARIO_LABEL = { running: '循环任务', idle: '全线空闲', error: '定点故障', showcase: '五态摆拍' }

const SVG_NS = 'http://www.w3.org/2000/svg'

/** DOM 建造小工具(与 panel.js 同款) */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag)
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'class') node.className = value
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value)
    else if (key === 'text') node.textContent = value
    else node.setAttribute(key, value)
  }
  node.append(...children)
  return node
}

/** Feather 风描边 SVG(渲染规则吃全局 .rail-ic / .mon-ic) */
function svgIcon(className, paths) {
  const svg = document.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('class', className)
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('aria-hidden', 'true')
  for (const d of paths) {
    const path = document.createElementNS(SVG_NS, 'path')
    path.setAttribute('d', d)
    svg.append(path)
  }
  return svg
}

/**
 * 功能: 构建外壳并绑定活数据.
 * @param {object} options 参数对象
 * @param {string} options.theme 当前主题
 * @param {() => void} options.onToggleTheme 主题切换(整页 reload, main 提供)
 * @param {() => void} options.onResetLayout "恢复默认布局"(复位面板折叠态)
 * @returns {{setTelemetryIds, setStationState, setClipStatus, setScenario}}
 */
export function createShell({ theme, onToggleTheme, onResetLayout }) {
  // ---- 侧栏 -----------------------------------------------------------------
  const rail = document.getElementById('fxsh-rail')
  for (const tab of RAIL_TABS) {
    const link = el('a', {
      class: `rail-tab${tab.key === 'three_d' ? ' active' : ''}`,
      href: '#',
      title: `${tab.label}(沙盒演示, 不跳转)`,
      onclick: (e) => e.preventDefault(), // 惰性链接: 别把用户从沙盒带走
    }, svgIcon('rail-ic', tab.d), el('span', { text: tab.label }))
    if (tab.key === 'three_d') link.setAttribute('aria-current', 'page')
    rail.append(link)
  }

  // ---- 顶栏 -----------------------------------------------------------------
  const status = document.getElementById('fxsh-status')
  const modeSelect = el('select', { 'aria-label': '控制模式', onchange: (e) => { e.target.value = 'DEBUG' } },
    el('option', { value: 'RUN', text: '运行' }),
    el('option', { value: 'DEBUG', text: '调试' }))
  modeSelect.value = 'DEBUG' // 沙盒钉在调试态(与截图里的正式页一致), 改动即回弹

  const runLabel = el('span', { text: '▶ 演示剧本 · 五态摆拍' })
  const runSub = el('span', { class: 'muted num', text: '' })
  const runInd = el('button', { type: 'button', class: 'btn-bare sb-item run-ind', title: '当前动画源(沙盒)' }, runLabel, runSub)

  const counts = { ok: 0, busy: 0, error: 0, offline: 0 }
  const countEls = {}
  const summary = el('div', { class: 'sb-summary', title: '设备健康汇总: 正常 / 忙碌 / 错误 / 离线' })
  for (const [key, label] of [['ok', '正常'], ['busy', '忙碌'], ['error', '错误'], ['offline', '离线']]) {
    countEls[key] = el('span', { class: 'num', text: '0' })
    summary.append(el('span', { class: 'chip' },
      el('span', { class: `health-dot ${key}`, 'aria-hidden': 'true' }),
      el('span', { class: 'chip-lbl', text: label }),
      countEls[key]))
  }

  status.append(
    el('h1', { text: 'pTLC 上位机' }),
    el('div', { class: 'sb-item' }, el('span', { class: 'lbl', text: '模式' }), modeSelect),
    el('span', { class: 'health-dot ok', 'aria-hidden': 'true' }),
    el('span', { class: 'lbl', text: '实时在线', role: 'status' }),
    runInd,
    summary,
    el('div', { class: 'sb-item' }, el('span', { class: 'lbl', text: '站点' }), el('strong', { class: 'sb-val', text: '工具' })),
    el('div', { class: 'sb-item' }, el('span', { class: 'lbl', text: '末端' }), el('strong', { class: 'sb-val', text: '吸盘' })),
    el('button', {
      class: 'btn-theme', type: 'button',
      title: theme === 'dark' ? '切换浅色主题' : '切换深色主题',
      onclick: () => onToggleTheme(),
    }, el('span', { 'aria-hidden': 'true', text: theme === 'dark' ? '☀' : '☾' })),
    el('button', { class: 'btn-monitor', type: 'button', title: '底部监视栏(沙盒无此栏)', 'aria-pressed': 'false' },
      svgIcon('mon-ic', ['M5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13A1.5 1.5 0 0 1 5.5 4Z', 'M4 14.5h16'])),
    el('button', { class: 'btn-reset-layout', type: 'button', title: '恢复面板默认布局', onclick: () => onResetLayout() }, document.createTextNode('恢复默认布局')),
    el('button', { class: 'estop', type: 'button', title: '沙盒演示: 不下发真机', onclick: (e) => e.preventDefault() }, document.createTextNode('急停')),
  )

  // ---- 页签条 ----------------------------------------------------------------
  const tabs = document.getElementById('fxsh-tabs')
  tabs.append(el('span', { class: 'app__brand', text: '3D' }))
  for (const tab of WORK_TABS) {
    tabs.append(el('a', {
      class: `app__tab${tab.active ? ' app__tab--active' : ''}`,
      href: '#',
      title: tab.hint,
      text: tab.label,
      onclick: (e) => e.preventDefault(),
    }))
  }
  const hint = el('span', { class: 'app__hint', text: WORK_TABS.find((t) => t.active)?.hint || '' })
  tabs.append(hint)

  // ---- 活数据 ----------------------------------------------------------------
  /** @type {Set<string>} 计入健康汇总的工位(有遥测的) */
  let telemetryIds = new Set()
  /** @type {Map<string, string>} 工位 -> health */
  const health = new Map()
  let scenario = 'showcase'
  let clipActive = false

  function renderCounts() {
    counts.ok = 0
    counts.busy = 0
    counts.error = 0
    counts.offline = 0
    for (const id of telemetryIds) {
      const h = health.get(id) || 'ok'
      if (counts[h] !== undefined) counts[h] += 1
    }
    for (const key of Object.keys(countEls)) countEls[key].textContent = String(counts[key])
  }

  function renderRun() {
    if (clipActive) return // 片段模式由 setClipStatus 直接写
    runLabel.textContent = `▶ 演示剧本 · ${SCENARIO_LABEL[scenario] || scenario}`
    runSub.textContent = ''
  }

  return {
    /** 功能: 声明计入健康汇总的工位集合(main 在工位索引建好后调一次). */
    setTelemetryIds(ids) {
      telemetryIds = new Set(ids)
      renderCounts()
    },

    /** 功能: 工位状态推入(与 cards.setStationState 同源同频). */
    setStationState(id, state) {
      health.set(id, state?.health || 'ok')
      renderCounts()
    },

    /** 功能: 流程片段播放状态 -> 顶栏运行指示(clipMode.onStatus 驱动). */
    setClipStatus(s) {
      clipActive = !!s?.active
      if (!clipActive) {
        renderRun()
        return
      }
      const pct = s.duration > 0 ? Math.round((s.time / s.duration) * 100) : 0
      runLabel.textContent = `▶ ${s.label || s.clipName || '流程片段'}`
      runSub.textContent = `(${pct}%)`
    },

    /** 功能: 模拟剧本切换 -> 运行指示兜底文案. */
    setScenario(name) {
      scenario = name
      renderRun()
    },
  }
}
