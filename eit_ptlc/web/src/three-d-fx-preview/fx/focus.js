/**
 * 功能: 聚焦编排 —— 点机身/快捷键选工位后的联动: 相机飞到该工位的**定制视角**
 * (cameraDirector.applyStationView, 第四轮换掉"保持方位角推近"的旧口径) +
 * 周围结构幽灵化/隐藏(isolation) + 选中工位**保持实体**并加描边(postfx
 * OutlineEffect) + 锚点上方钉白色详情卡. Esc/点空白退出.
 *
 * 点击分派优先序(第四轮): 门体(doors.doorOfMesh 命中 -> 开关门, 不聚焦不 blur)
 * > 工位(聚焦/再点退出) > 空白(blur). 直插而不走事件总线 —— 分派必须有确定的
 * 消费语义, emit 无返回值会让"开门"与"blur"双发.
 */
import * as THREE from 'three'

const _ndc = new THREE.Vector2()

/**
 * 功能: 创建聚焦编排器.
 * @param {object} ctx 沙盒上下文
 * @param {object} deps 参与联动的模块 { cards, isolation, director, doors }
 * @returns {object} 特效实例(另暴露 focus/blur/current)
 */
export function createFocus(ctx, deps) {
  const { cards, isolation, director, doors } = deps
  const raycaster = new THREE.Raycaster()
  raycaster.firstHitOnly = true

  let enabled = true
  let current = null
  let downX = 0
  let downY = 0
  let downAt = 0

  /**
   * 功能: 聚焦某工位.
   * @param {string} id 工位 id
   * @param {{instant?: boolean}} [options] instant=true 无过渡(截图/巡检定格用)
   * @returns {void}
   */
  function focus(id, options = {}) {
    if (!enabled || !ctx.stations.has(id)) return
    current = id
    cards?.setSelected(id)
    isolation?.setStation(id) // 先幽灵化周围再飞入: 相机贴近不穿模、视线不被机架挡
    ctx.post.setOutline(ctx.stations.get(id).meshes)
    director.applyStationView(id, { instant: options.instant })
    ctx.events.emit('focus', id)
  }

  /** 功能: 退出聚焦, 恢复全场. */
  function blur() {
    if (current === null) return
    current = null
    cards?.setSelected(null)
    isolation?.setStation(null)
    ctx.post.setOutline([])
    ctx.events.emit('focus', null)
  }

  function onPointerDown(event) {
    downX = event.clientX
    downY = event.clientY
    downAt = performance.now()
  }

  function onPointerUp(event) {
    if (!enabled) return
    const moved = Math.hypot(event.clientX - downX, event.clientY - downY)
    if (moved > 5 || performance.now() - downAt > 400) return // 是拖拽不是点选
    if (!ctx.occluder.ready) return
    const rect = ctx.canvas.getBoundingClientRect()
    _ndc.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    )
    raycaster.setFromCamera(_ndc, ctx.camera)
    raycaster.far = Infinity
    const hits = raycaster.intersectObjects(ctx.occluder.meshes, false)
    const hit = hits.find((entry) => entry.object.visible) || null
    // 门优先: 点到门体 = 开关那扇门, 不进入聚焦也不退出聚焦
    const doorName = doors?.doorOfMesh?.(hit?.object)
    if (doorName) {
      doors.toggleDoor(doorName)
      return
    }
    const stationId = hit ? ctx.meshToStation.get(hit.object) : null
    if (stationId) {
      if (stationId === current) blur()
      else focus(stationId)
    } else {
      blur() // 点空白退出聚焦
    }
  }

  ctx.canvas.addEventListener('pointerdown', onPointerDown)
  ctx.canvas.addEventListener('pointerup', onPointerUp)

  const offClick = ctx.events.on('station-click', (id) => {
    if (id === current) blur()
    else focus(id)
  })

  return {
    name: 'focus',
    focus,
    blur,
    current: () => current,

    update() {},
    setStationState() {},
    setEnabled(on) {
      enabled = !!on
      if (!enabled) blur()
    },
    setParams() {},

    dispose() {
      blur()
      offClick()
      ctx.canvas.removeEventListener('pointerdown', onPointerDown)
      ctx.canvas.removeEventListener('pointerup', onPointerUp)
    },
  }
}
