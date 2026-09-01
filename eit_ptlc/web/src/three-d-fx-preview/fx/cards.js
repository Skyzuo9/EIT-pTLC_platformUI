/**
 * 功能: 悬浮信息卡层(realvirtual 风格) —— 鼠标悬停到工位上时, 光标旁浮现**白色信息卡**;
 * 点击聚焦后, 工位锚点上方钉一张**白色固定详情卡**. 第四轮起状态圆点(fxdot)整个退役
 * (用户定夺), 工位状态改由外壳顶栏计数与悬停卡承载.
 *
 * 结构: 悬浮卡 1 张 + 固定详情卡 1 张(共用 .fxwcard).
 * 悬停检测复用聚焦拾取同一批 BVH 网格(pointermove 节流射线), 冻结定格时用
 * performance.now 计时 —— 截图脚本 mouse.move 也能hover出卡.
 * `?debug=1` 时卡片追加"零件"行(射中的网格名/合并块名), 供用户指认错归零件.
 *
 * 铁律不变: 位置更新只写 style.transform(画布局部像素, 与 ctx.screenOf 同系);
 * 状态字段低频推入(setStationState). 悬停命中 mesh 经 hoveredMesh() 暴露(门模块切 cursor 用).
 */
import * as THREE from 'three'

/** 健康度中文(与 StationPanel.vue 同表) */
export const HEALTH_LABEL = { ok: '正常', busy: '运行中', error: '故障', offline: '离线', unknown: '未知' }

/** 非运行态的动作行文案 */
const ACTION_FALLBACK = { ok: '待机', offline: '连接断开', unknown: '无遥测节点' }

const _ndc = new THREE.Vector2()
const _anchor = new THREE.Vector3()

/** 造一张白卡 DOM */
function buildCard(mode, debug) {
  const el = document.createElement('div')
  el.className = 'fxwcard'
  el.dataset.mode = mode
  el.dataset.health = 'unknown'
  el.innerHTML = `
    <i class="fxwcard__bar"></i>
    <div class="fxwcard__head">
      <span class="fxwcard__name"></span>
      <span class="fxwcard__chip"></span>
    </div>
    <div class="fxwcard__action"></div>
    <div class="fxwcard__rows">
      <div class="fxwcard__row"><span>遥测节点</span><b data-ref="node"></b></div>
      <div class="fxwcard__row"><span>动作进度</span><b data-ref="pct"></b></div>
      ${debug ? '<div class="fxwcard__row"><span>零件</span><b data-ref="part"></b></div>' : ''}
    </div>`
  return {
    el,
    name: el.querySelector('.fxwcard__name'),
    chip: el.querySelector('.fxwcard__chip'),
    action: el.querySelector('.fxwcard__action'),
    node: el.querySelector('[data-ref="node"]'),
    pct: el.querySelector('[data-ref="pct"]'),
    part: el.querySelector('[data-ref="part"]'),
  }
}

/**
 * 功能: 创建悬浮卡层.
 * @param {object} ctx 沙盒上下文
 * @returns {object} 特效实例(另暴露 setSelected/hoveredStation/hoveredMesh)
 */
export function createCards(ctx) {
  const cfg = ctx.config.cards
  const hoverCfg = ctx.config.hover
  const host = ctx.dom.cardHost

  /** @type {Map<string, {health: string, action: string, progress: number}>} 全部工位状态 */
  const states = new Map()
  for (const station of ctx.stationList) {
    states.set(station.id, {
      health: station.hasTelemetry ? 'ok' : 'unknown', action: '', progress: 0,
    })
  }

  const hover = buildCard('hover', ctx.debug)
  const pinned = buildCard('pinned', ctx.debug)
  host.append(hover.el, pinned.el)

  const raycaster = new THREE.Raycaster()
  raycaster.firstHitOnly = true

  let enabled = true
  let selectedId = null
  let hoverId = null
  /** @type {THREE.Mesh|null} 最近一次悬停射线命中的 mesh(门模块的 cursor 判定读它) */
  let hoverMesh = null
  let hoverPartName = ''
  let mouseX = 0
  let mouseY = 0
  let mouseIn = false
  let lastPick = 0

  function onPointerMove(event) {
    mouseX = event.clientX
    mouseY = event.clientY
    mouseIn = true
  }
  function onPointerLeave() {
    mouseIn = false
  }
  ctx.canvas.addEventListener('pointermove', onPointerMove)
  ctx.canvas.addEventListener('pointerleave', onPointerLeave)

  /** 光标下的工位(悬停射线, 只认可见网格 —— 幽灵/隐藏的不挡) */
  function pick() {
    if (!ctx.occluder.ready) return null
    const vp = ctx.viewport()
    _ndc.set(
      ((mouseX - vp.left) / vp.width) * 2 - 1,
      -((mouseY - vp.top) / vp.height) * 2 + 1,
    )
    raycaster.setFromCamera(_ndc, ctx.camera)
    const hits = raycaster.intersectObjects(ctx.occluder.meshes, false)
    const hit = hits.find((entry) => entry.object.visible) || null
    return hit
  }

  /** 把某工位的当前状态写进一张卡 */
  function fill(card, id) {
    const station = ctx.stations.get(id)
    const state = states.get(id) || { health: 'unknown', action: '', progress: 0 }
    card.el.dataset.health = state.health
    card.name.textContent = station?.label || id
    card.chip.textContent = HEALTH_LABEL[state.health] || state.health
    if (state.health === 'busy') card.action.textContent = state.action || '执行中'
    else if (state.health === 'error') card.action.textContent = state.action ? `${state.action} · 中断` : '故障'
    else card.action.textContent = ACTION_FALLBACK[state.health] || '待机'
    card.node.textContent = station?.nodeId || '—'
    card.pct.textContent = (state.health === 'busy' || state.health === 'error') && state.progress > 0
      ? `${Math.round(state.progress * 100)}%` : '—'
    if (card.part) card.part.textContent = hoverPartName || '—'
  }

  return {
    name: 'cards',
    hoveredStation: () => hoverId,
    hoveredMesh: () => hoverMesh,

    update() {
      if (!enabled) return
      const vp = ctx.viewport()

      // 悬停射线(真实时间节流, 冻结定格时照样可用)
      const now = performance.now()
      if (mouseIn && now - lastPick > hoverCfg.throttleMs) {
        lastPick = now
        const hit = pick()
        hoverMesh = hit?.object || null
        const id = hit ? ctx.meshToStation.get(hit.object) || null : null
        hoverPartName = hit?.object?.name || ''
        if (id !== hoverId) {
          hoverId = id
          if (id) fill(hover, id)
        } else if (id && ctx.debug) {
          if (hover.part) hover.part.textContent = hoverPartName || '—'
        }
      }
      if (!mouseIn) {
        hoverId = null
        hoverMesh = null
      }

      // 悬浮卡贴光标(偏移 + 视口夹取, 画布局部坐标); 悬停对象即聚焦对象时不重复出卡
      const showHover = !!hoverId && hoverId !== selectedId
      hover.el.dataset.visible = showHover ? '1' : ''
      if (showHover) {
        const rect = hover.el.getBoundingClientRect()
        const x = Math.min(mouseX - vp.left + hoverCfg.offsetX, vp.width - rect.width - 8)
        const y = Math.min(mouseY - vp.top + hoverCfg.offsetY, vp.height - rect.height - 8)
        hover.el.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0)`
      }

      // 固定详情卡钉在选中工位锚点上方(带视口夹取: 锚点贴视口顶时卡别被裁掉)
      pinned.el.dataset.visible = selectedId ? '1' : ''
      if (selectedId) {
        const station = ctx.stations.get(selectedId)
        station.getAnchor(_anchor, cfg.anchorLift)
        const s = ctx.screenOf(_anchor, pinned.screen || (pinned.screen = { x: 0, y: 0, depth: 0, dist: 0, visible: false }))
        const rect = pinned.el.getBoundingClientRect()
        const halfW = Math.max(rect.width / 2, 100)
        const x = Math.min(Math.max(s.x, halfW + 8), vp.width - halfW - 8)
        const y = Math.min(Math.max(s.y - cfg.pinnedRisePx, rect.height + 8), vp.height - 8)
        pinned.el.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0)`
      }
    },

    /**
     * 功能: 低频状态推入.
     * @param {string} id 工位 id
     * @param {{health: string, action: string, progress: number}} state 状态
     * @returns {void}
     */
    setStationState(id, state) {
      states.set(id, state)
      if (id === hoverId) fill(hover, id)
      if (id === selectedId) fill(pinned, id)
    },

    setSelected(id) {
      selectedId = id || null
      if (selectedId) fill(pinned, selectedId)
    },

    setEnabled(on) {
      enabled = !!on
      host.style.display = enabled ? '' : 'none'
    },

    setParams() {},

    dispose() {
      ctx.canvas.removeEventListener('pointermove', onPointerMove)
      ctx.canvas.removeEventListener('pointerleave', onPointerLeave)
      hover.el.remove()
      pinned.el.remove()
    },
  }
}
