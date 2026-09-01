/**
 * 功能: 控制面板(纯 DOM, 无 Vue) —— 风格/特效开关/流程播放/场景模拟/显示设置/参数/工具.
 *
 * 滑杆按 fxConfig 的 PARAM_DEFS / DISPLAY_DEFS 声明自动生成: min/max/step/默认值只在
 * 那一处声明, 面板与配置永不漂移. 面板任何改动经 main 的 syncUrl 回写地址栏.
 * 显示设置段照正式页 DisplayPanel 的行范式: 标签 | 控件 | 数值 | 单项还原.
 */
import { PARAM_DEFS, DISPLAY_DEFS, FX_DEFAULTS, getPath } from './fxConfig.js'
import { HEALTH_LABEL } from './fx/cards.js'

/** DOM 建造小工具 */
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

/** mm:ss.s 时间格式 */
function fmtTime(seconds) {
  const s = Math.max(0, Number(seconds) || 0)
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
}

/**
 * 功能: 构建控制面板.
 * @param {object} options 参数对象
 * @param {HTMLElement} options.host 面板宿主元素
 * @param {object} options.state 页面状态(urlState 解析结果, 面板只读初值)
 * @param {object} options.config 运行配置
 * @param {object[]} options.stationList 工位清单
 * @param {object} options.events 事件总线(订阅 tour 状态)
 * @param {object} options.actions main 提供的动作回调集
 * @returns {{setStats, toggle, setClipFlows, setClipStatus}}
 */
export function createPanel({ host, state, config, stationList, events, actions }) {
  host.innerHTML = ''

  // 卡片头: 标题 + 最小化按钮; 最小化后整卡收成"效果预览"小胶囊(用户要的"缩放卡片")
  const minBtn = el('button', {
    class: 'fxp-min', type: 'button', text: '—', title: '最小化为胶囊',
    onclick: () => host.classList.add('is-min'),
  })
  const pill = el('button', {
    class: 'fxp-pill', type: 'button', text: '效果预览', title: '展开效果预览面板',
    onclick: () => host.classList.remove('is-min'),
  })
  host.append(el('div', { class: 'fxp-head' }, el('h1', { text: '效果预览' }), minBtn), pill)

  // ---- 主题 ----------------------------------------------------------------
  const themeGroup = el('div', { class: 'fxp-group' })
  for (const [key, label] of [['dark', '深色(展示)'], ['light', '浅色(兼容)']]) {
    themeGroup.append(el('button', {
      class: `fxp-btn${state.theme === key ? ' is-active' : ''}`,
      text: label,
      onclick: () => actions.setTheme(key), // 切主题走整页 reload
    }))
  }
  host.append(el('details', { open: '' }, el('summary', { text: '主题' }), themeGroup))

  // ---- 特效开关 ---------------------------------------------------------------
  const persistent = [
    ['cards', '悬浮信息卡'], ['focus', '点击聚焦'],
  ]
  const checkGroup = el('div', { class: 'fxp-group' })
  for (const [key, label] of persistent) {
    const input = el('input', { type: 'checkbox' })
    input.checked = state.fx.has(key)
    input.addEventListener('change', () => actions.toggleFx(key, input.checked))
    checkGroup.append(el('label', { class: 'fxp-check' }, input, el('span', { text: label })))
  }
  const tourButton = el('button', { class: 'fxp-btn', text: '▶ 巡检模式', onclick: () => actions.toggleTour() })
  events.on('tour', (on) => {
    tourButton.textContent = on ? '⏹ 停止巡检' : '▶ 巡检模式'
    tourButton.classList.toggle('is-active', on)
  })
  const isolateSelect = el('select', {},
    ...[['ghost', '幽灵半透明'], ['hide', '隐藏周围'], ['off', '不处理']]
      .map(([v, t]) => el('option', { value: v, text: t })))
  isolateSelect.value = config.focus.isolation
  isolateSelect.addEventListener('change', () => actions.setIsolation(isolateSelect.value))
  host.append(el('details', { open: '' },
    el('summary', { text: '特效' }),
    checkGroup,
    el('div', { class: 'fxp-group' },
      el('button', { class: 'fxp-btn', text: '▶ 开场动画', onclick: () => actions.intro() }),
      tourButton),
    el('div', { class: 'fxp-row' }, el('label', { text: '聚焦隔离' }), isolateSelect),
  ))

  // ---- 流程播放(精编译片段) -----------------------------------------------------
  const flowSelect = el('select', {}, el('option', { value: '', text: '加载清单中…' }))
  flowSelect.addEventListener('change', () => {
    if (flowSelect.value) actions.loadClip(flowSelect.value)
  })
  const clipPlayBtn = el('button', { class: 'fxp-btn', text: '▶', onclick: () => actions.clipToggle() })
  const clipExitBtn = el('button', { class: 'fxp-btn', text: '⏹ 退出', onclick: () => actions.clipExit() })
  const clipRange = el('input', { type: 'range', min: '0', max: '1', step: '0.05', value: '0' })
  clipRange.addEventListener('input', () => actions.clipSeek(Number(clipRange.value)))
  const clipTime = el('output', { text: '0:00.0' })
  const clipSpeed = el('select', {},
    ...['0.5', '1', '2', '4'].map((v) => el('option', { value: v, text: `${v}x` })))
  clipSpeed.value = '1'
  clipSpeed.addEventListener('change', () => actions.clipSpeed(Number(clipSpeed.value)))
  const clipLoop = el('input', { type: 'checkbox' })
  clipLoop.addEventListener('change', () => actions.clipLoop(clipLoop.checked))
  const clipStep = el('div', { class: 'fxp-hint', text: '未载入片段(选择流程后机器按精编译动画运动)' })
  host.append(el('details', { open: '' },
    el('summary', { text: '流程播放' }),
    el('div', { class: 'fxp-row' }, el('label', { text: '流程' }), flowSelect),
    el('div', { class: 'fxp-row' }, el('label', { text: '播放' }), clipPlayBtn, clipRange, clipTime),
    el('div', { class: 'fxp-row' },
      el('label', { text: '倍速' }), clipSpeed,
      el('label', { class: 'fxp-check' }, clipLoop, el('span', { text: '循环' })), clipExitBtn),
    clipStep,
  ))

  // ---- 场景模拟 ---------------------------------------------------------------
  const scenarioSelect = el('select', {},
    ...[['running', '循环任务'], ['idle', '全线空闲'], ['error', '定点故障'], ['showcase', '五态摆拍']]
      .map(([v, t]) => el('option', { value: v, text: t })))
  scenarioSelect.value = state.scenario
  scenarioSelect.addEventListener('change', () => actions.setScenario(scenarioSelect.value))

  const speedOut = el('output', { text: `${state.speed}x` })
  const speedInput = el('input', { type: 'range', min: '0.25', max: '4', step: '0.25', value: String(state.speed) })
  speedInput.addEventListener('input', () => {
    speedOut.textContent = `${speedInput.value}x`
    actions.setSpeed(Number(speedInput.value))
  })

  const stationSelect = el('select', {}, ...stationList.map((s) => el('option', { value: s.id, text: s.label })))
  const healthSelect = el('select', {},
    el('option', { value: '', text: '按剧本' }),
    ...Object.entries(HEALTH_LABEL).map(([v, t]) => el('option', { value: v, text: t })))
  healthSelect.addEventListener('change', () => {
    actions.setStationHealth(stationSelect.value, healthSelect.value || null)
  })
  stationSelect.addEventListener('change', () => { healthSelect.value = '' })

  host.append(el('details', {},
    el('summary', { text: '场景模拟' }),
    el('div', { class: 'fxp-row' }, el('label', { text: '剧本' }), scenarioSelect),
    el('div', { class: 'fxp-row' }, el('label', { text: '倍速' }), speedInput, speedOut),
    el('div', { class: 'fxp-row' }, el('label', { text: '手动置态' }), stationSelect, healthSelect),
    el('div', { class: 'fxp-group' },
      el('button', { class: 'fxp-btn', text: '注入故障(10s 自愈)', onclick: () => actions.injectError() }),
      el('button', { class: 'fxp-btn', text: '清除覆写', onclick: () => actions.clearOverrides() })),
  ))

  // ---- 显示设置(照正式页 DisplayPanel 行范式: 标签|滑杆|数值|↺) -------------------
  const displayRows = DISPLAY_DEFS.map((def) => {
    const defaultValue = getPath(FX_DEFAULTS, def.path)
    const out = el('output', { text: String(getPath(config, def.path)) })
    const input = el('input', {
      type: 'range', min: String(def.min), max: String(def.max), step: String(def.step),
      value: String(getPath(config, def.path)),
    })
    input.addEventListener('input', () => {
      const v = Number(input.value)
      out.textContent = String(v)
      actions.setDisplay(def.path, v)
    })
    const reset = el('button', {
      class: 'fxp-reset', text: '↺', title: '还原默认',
      onclick: () => {
        input.value = String(defaultValue)
        out.textContent = String(defaultValue)
        actions.setDisplay(def.path, defaultValue)
      },
    })
    const label = el('label', { text: def.label + (def.sandboxOnly ? '*' : '') })
    if (def.sandboxOnly) label.title = '沙盒专用旋钮, 正式页显示设置里没有此项'
    return { row: el('div', { class: 'fxp-row' }, label, input, out, reset), def, input, out }
  })
  host.append(el('details', { open: '' },
    el('summary', { text: '显示设置' }),
    ...displayRows.map((r) => r.row),
    el('div', { class: 'fxp-group' }, el('button', {
      class: 'fxp-btn', text: '恢复默认',
      onclick: () => {
        for (const { def, input, out } of displayRows) {
          const v = getPath(FX_DEFAULTS, def.path)
          input.value = String(v)
          out.textContent = String(v)
          actions.setDisplay(def.path, v)
        }
      },
    })),
    el('div', { class: 'fxp-hint', text: '* 曝光为沙盒专用; 其余数值与正式页显示设置一比一对应' }),
  ))

  // ---- 参数微调(特效参数) --------------------------------------------------------
  const paramRows = PARAM_DEFS.map((def) => {
    const value = getPath(config, def.path)
    const out = el('output', { text: String(value) })
    const input = el('input', {
      type: 'range', min: String(def.min), max: String(def.max), step: String(def.step), value: String(value),
    })
    input.addEventListener('input', () => {
      const v = Number(input.value)
      out.textContent = String(v)
      actions.setParam(def.path, v)
    })
    return el('div', { class: 'fxp-row' }, el('label', { text: def.label }), input, out)
  })
  host.append(el('details', {}, el('summary', { text: '参数微调' }), ...paramRows))

  // ---- 机位与工具 ----------------------------------------------------------------
  const presetGroup = el('div', { class: 'fxp-group' },
    ...['iso', 'front', 'left', 'right', 'top'].map((name) =>
      el('button', { class: 'fxp-btn', text: name, onclick: () => actions.preset(name) })))

  const rotateInput = el('input', { type: 'checkbox' })
  rotateInput.checked = state.autorotate
  rotateInput.addEventListener('change', () => actions.setAutorotate(rotateInput.checked))
  const followInput = el('input', { type: 'checkbox' })
  followInput.checked = true
  followInput.addEventListener('change', () => actions.setCarriageFollow(followInput.checked))

  const stats = el('div', { class: 'fxp-stats', text: '…' })
  // 定制视角调参回路: 聚焦后手调机位 -> 一键固化(写 config + cfg.* URL, 复制地址即可交付)
  const captureBtn = el('button', {
    class: 'fxp-btn', text: '固化机位为该工位视角', title: '先点击聚焦一个工位, 手调好机位后按此固化',
    onclick: () => {
      const captured = actions.captureStationView()
      captureBtn.textContent = captured ? `✓ 已固化 ${captured.id}` : '先聚焦一个工位'
      setTimeout(() => { captureBtn.textContent = '固化机位为该工位视角' }, 1600)
    },
  })
  host.append(el('details', { open: '' },
    el('summary', { text: '机位与工具' }),
    presetGroup,
    el('div', { class: 'fxp-group' },
      el('label', { class: 'fxp-check' }, rotateInput, el('span', { text: '自动环绕' })),
      el('label', { class: 'fxp-check' }, followInput, el('span', { text: '搬运滑座跟随' }))),
    el('div', { class: 'fxp-group' },
      captureBtn,
      el('button', { class: 'fxp-btn', text: '复制当前 URL', onclick: () => actions.copyUrl() })),
    stats,
    el('div', { class: 'fxp-hint', text: '悬停看信息 · 点击聚焦 · 点门开关门 · Esc 退出\n快捷键: H 面板 · T 巡检 · 1-9 选工位(左→右)' }),
  ))

  return {
    setStats(text) {
      stats.textContent = text
    },
    toggle() {
      host.hidden = !host.hidden
    },
    /** 功能: 恢复面板默认布局(顶栏"恢复默认布局"钮): 展开胶囊 + 取消隐藏. */
    resetLayout() {
      host.classList.remove('is-min')
      host.hidden = false
    },

    /**
     * 功能: 填充流程下拉(main 拉到 flow-index 后调).
     * @param {Array<{clipName: string, label: string, group: string}>} flows 可播清单
     * @param {string} [currentClipName] 已载入的片段(URL 直达时回显选中项)
     * @returns {void}
     */
    setClipFlows(flows, currentClipName = '') {
      flowSelect.innerHTML = ''
      flowSelect.append(el('option', { value: '', text: `— 选择流程(${flows.length} 条可播) —` }))
      const groups = new Map()
      for (const flow of flows) {
        if (!groups.has(flow.group)) {
          const og = el('optgroup', { label: flow.group || '其他' })
          groups.set(flow.group, og)
          flowSelect.append(og)
        }
        groups.get(flow.group).append(el('option', { value: flow.clipName, text: flow.label }))
      }
      if (currentClipName) flowSelect.value = currentClipName
    },

    /**
     * 功能: 刷新播放状态(clipMode.onStatus 10Hz 驱动).
     * @param {object} s clipMode.status
     * @returns {void}
     */
    setClipStatus(s) {
      clipPlayBtn.textContent = s.playing ? '⏸' : '▶'
      clipRange.max = String(Math.max(s.duration, 0.1))
      if (document.activeElement !== clipRange) clipRange.value = String(s.time)
      clipTime.textContent = fmtTime(s.time)
      if (s.error) clipStep.textContent = `✗ ${s.error}`
      else if (!s.active) clipStep.textContent = '未载入片段(选择流程后机器按精编译动画运动)'
      else {
        const missing = s.missing ? ` · ${s.missing} 个节点未解析` : ''
        clipStep.textContent = `${s.label} · 第${s.stepIndex + 1}步 ${s.stepLabel || ''}${missing}`
      }
    },
  }
}
