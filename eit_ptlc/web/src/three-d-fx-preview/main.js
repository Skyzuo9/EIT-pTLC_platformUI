/**
 * 功能: 效果预览沙盒入口 —— 装配 stage/postfx/工位模型/模拟剧本/流程片段/特效/面板.
 *
 * 第三轮形态(用户定夺): 悬停白卡(realvirtual 风格) + 聚焦"周围幽灵化、对象实体+描边"
 * (不压暗) + 环绕点亮开场; 流光带/地面光环/扫描波/全息壳已退役.
 * 数据流: simFeed(剧本) 或 clipMode(精编译片段) --低频 pushState--> cards(圆点/白卡)
 * 结构化结果挂 window.__fx 供 Playwright 验收(照 spike 的 __spike 约定).
 *
 * 前提: 需 18080 后端在线(模型与 manifest 走 vite 的 /api 代理), 否则页面明示.
 */
import * as THREE from 'three'
import { computeBoundsTree, disposeBoundsTree, acceleratedRaycast } from 'three-mesh-bvh'

import '../style.css'
import '../three-d/styles.css'
import './styles.css'

import { loadMachine, computeBounds } from '../three-d/twin/scene/loadModel.js'
import { makeConfig, setPath } from './fxConfig.js'
import { parseUrlState, serializeUrlState } from './urlState.js'
import { createStage } from './stage.js'
import { createPostFx } from './postfx.js'
import { buildStationIndex, probeCarriage, createCarriageFollow } from './stationIndex.js'
import { createSimFeed } from './simFeed.js'
import { createCameraDirector, VIEW_PRESETS } from './cameraDirector.js'
import { createCards } from './fx/cards.js'
import { createIsolation } from './fx/isolation.js'
import { createDoors } from './fx/doors.js'
import { createFocus } from './fx/focus.js'
import { createTour } from './fx/tour.js'
import { createIntro } from './fx/intro.js'
import { createClipMode } from './clipMode.js'
import { createPanel } from './panel.js'
import { createShell } from './shell.js'

// three-mesh-bvh: 加速射线(悬停/点选拾取共用一棵树)
THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree
THREE.Mesh.prototype.raycast = acceleratedRaycast

const MODEL_URL = '/api/3d/assets/models/machine.official-cr5.glb'
const MANIFEST_URL = '/api/3d/assets/models/device-manifest.official-cr5.json'

/** manifest 缺失时的健康度样式兜底(值与现役 manifest 一致) */
const FALLBACK_HEALTH_STYLES = {
  ok: { color: '#39d98a', intensity: 3, pulse: 0 },
  busy: { color: '#f4b740', intensity: 4.5, pulse: 1.1 },
  error: { color: '#ff5c5c', intensity: 6, pulse: 3 },
  offline: { color: '#5a6472', intensity: 0.3, pulse: 0 },
  unknown: { color: '#7b8aa5', intensity: 1, pulse: 0 },
}

/** 结构化结果, 供 Playwright 读 */
const result = {
  ready: false,
  errors: [],
  scenario: null,
  fx: [],
  stats: null,
  api: null,
}
window.__fx = result
window.addEventListener('error', (e) => result.errors.push(String(e.message)))
window.addEventListener('unhandledrejection', (e) => result.errors.push(String(e.reason)))

const msgHost = document.getElementById('fx-msg')
/** 全屏提示(空串隐藏) */
function msg(text) {
  msgHost.hidden = !text
  msgHost.textContent = text || ''
}

/** 微型事件总线 */
function createEmitter() {
  const map = new Map()
  return {
    on(type, cb) {
      if (!map.has(type)) map.set(type, new Set())
      map.get(type).add(cb)
      return () => map.get(type)?.delete(cb)
    },
    emit(type, payload) {
      map.get(type)?.forEach((cb) => cb(payload))
    },
  }
}

async function main() {
  const urlState = parseUrlState(location.search)
  const config = makeConfig(new URLSearchParams(location.search))
  if (urlState.isolate) config.focus.isolation = urlState.isolate
  result.scenario = urlState.scenario
  result.fx = [...urlState.fx]

  const panelHost = document.getElementById('fx-panel')
  panelHost.hidden = !urlState.panel

  /** 主题切换 = 整页 reload(面板按钮与顶栏按钮共用) */
  function gotoTheme(theme) {
    urlState.theme = theme
    const qs = serializeUrlState(urlState, location.search)
    location.href = location.pathname + (qs ? `?${qs}` : '')
  }

  /** @type {ReturnType<typeof createPanel>|null} */
  let panelApi = null
  // 仿正式应用外壳(侧栏/顶栏/页签): 模型加载前就位, chrome 不等资产
  const shell = createShell({
    theme: urlState.theme,
    onToggleTheme: () => gotoTheme(urlState.theme === 'dark' ? 'light' : 'dark'),
    onResetLayout: () => panelApi?.resetLayout(),
  })
  shell.setScenario(urlState.scenario)

  const stage = createStage({
    container: document.getElementById('fx-app'),
    theme: urlState.theme,
    dpr: urlState.dpr,
    display: config.display,
  })

  // -- 资产 -------------------------------------------------------------------
  msg('正在加载整机模型…\n(需要 18080 后端在线, 15173 经 vite 代理取 /api/3d/assets)')
  let manifest
  try {
    const response = await fetch(MANIFEST_URL)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    manifest = await response.json()
  } catch (error) {
    throw new Error(`取不到 device-manifest: ${error.message}\n请确认 18080 后端在线后刷新本页`)
  }
  const load = await loadMachine({
    url: `${MODEL_URL}?v=${encodeURIComponent(manifest.generatedAt || '')}`,
    onProgress: (f) => msg(`正在加载整机模型… ${Math.round(f * 100)}%`),
  })
  stage.scene.add(load.root)

  /** @type {THREE.Mesh[]} 整机全部网格(阴影/悬停/拾取共用) */
  const machineMeshes = []
  load.root.traverse((node) => {
    if (!node.isMesh) return
    node.castShadow = true
    node.receiveShadow = true
    machineMeshes.push(node)
  })
  stage.invalidateShadows()

  const machineBounds = computeBounds(load.root)
  stage.fitWorld(machineBounds) // 雾距/主光摆位/影子相机按整机尺度定

  // -- 工位模型 / 后期 / 运镜 -----------------------------------------------------
  const { stations, list: stationList, meshToStation } = buildStationIndex({
    manifest, nodeIndex: load.nodeIndex, config,
  })
  if (!stationList.length) throw new Error('manifest.stations 与模型节点对不上, 一个工位都没解析出来')

  // 空间左→右序(manifest 声明序≠空间序): 巡检路线与 1-9 快捷键都用它
  const _sortBox = new THREE.Box3()
  const centerX = (station) => {
    station.getWorldBounds(_sortBox)
    return (_sortBox.min.x + _sortBox.max.x) / 2
  }
  const stationListByX = [...stationList].sort((a, b) => centerX(a) - centerX(b))

  const post = createPostFx({
    renderer: stage.renderer,
    scene: stage.scene,
    camera: stage.camera,
    quality: urlState.quality,
    aa: urlState.aa,
    config,
    theme: urlState.theme,
  })
  stage.setComposer(post.composer ? post : null)

  const director = createCameraDirector({
    controls: stage.controls,
    camera: stage.camera,
    machineBounds,
    stations,
    config,
  })
  if (urlState.cam.startsWith('station:')) director.applyStationView(urlState.cam.slice(8), { instant: true })
  else director.applyPreset(VIEW_PRESETS[urlState.cam] ? urlState.cam : 'iso', false)
  stage.setAutorotate(urlState.autorotate)

  // -- 上下文 -------------------------------------------------------------------
  const healthStyles = { ...FALLBACK_HEALTH_STYLES, ...(manifest.healthStyles || {}) }
  const occluder = { ready: false, meshes: machineMeshes }
  const events = createEmitter()
  const _proj = new THREE.Vector3()

  /**
   * 画布视口缓存(每帧主钩子第一行刷新). 坐标契约:
   *   - 内部(screenOf 输出/卡片 transform)一律**画布局部像素**;
   *   - 对外验收 API(hoverProbe 入参 / debugAnchors 出参)一律**页面像素**, 折算在 API 内做.
   * 满屏形态下两坐标系恒等; 套外壳(画布非满屏)后自动带偏移, shot/verify 脚本零改动.
   */
  const _vp = { left: 0, top: 0, width: 1, height: 1 }
  function refreshViewport() {
    const rect = stage.canvas.getBoundingClientRect()
    _vp.left = rect.left
    _vp.top = rect.top
    _vp.width = rect.width || 1
    _vp.height = rect.height || 1
  }
  refreshViewport()

  const ctx = {
    scene: stage.scene,
    camera: stage.camera,
    renderer: stage.renderer,
    canvas: stage.canvas,
    controls: stage.controls,
    lights: stage.lights,
    machineRoot: load.root,
    machineBounds,
    nodeIndex: load.nodeIndex,
    invalidateShadows: stage.invalidateShadows,
    unitScale: load.unit.scale || 1,
    stations,
    stationList,
    stationListByX,
    meshToStation,
    manifest,
    styles: healthStyles,
    occluder,
    events,
    config,
    post,
    bloom: post.bloom,
    quality: urlState.quality,
    theme: urlState.theme,
    debug: urlState.debug,
    dom: {
      cardHost: document.getElementById('fx-cards'),
      panelHost,
    },
    addFrameHook: stage.addFrameHook,
    /** 功能: 画布视口缓存只读访问({left, top, width, height}, 页面坐标系). */
    viewport: () => _vp,
    /**
     * 功能: 世界点 -> **画布局部像素**(配方照 motion/devHooks.screenOf).
     * 输出是画布(=#fx-cards 宿主)局部坐标; 页面像素请自行加 viewport().left/top.
     * @param {THREE.Vector3} world 世界点
     * @param {object} out 复用的输出对象
     * @returns {{x: number, y: number, depth: number, dist: number, visible: boolean}}
     */
    screenOf(world, out) {
      _proj.copy(world).project(stage.camera)
      out.x = ((_proj.x + 1) / 2) * _vp.width
      out.y = ((1 - _proj.y) / 2) * _vp.height
      out.depth = _proj.z
      out.dist = stage.camera.position.distanceTo(world)
      out.visible = _proj.z < 1 && Math.abs(_proj.x) < 1.15 && Math.abs(_proj.y) < 1.15
      return out
    },
  }

  // -- 模拟剧本 -------------------------------------------------------------------
  const simFeed = createSimFeed({
    stationIds: stationList.map((s) => s.id),
    telemetryIds: stationList.filter((s) => s.hasTelemetry).map((s) => s.id),
    scenario: urlState.scenario,
    speed: urlState.speed,
    errorRecoverS: config.sim.errorRecoverS,
  })

  // -- 特效装配 -------------------------------------------------------------------
  const cards = createCards(ctx)
  const isolation = createIsolation(ctx)
  const doors = createDoors(ctx, { cards })
  const focusApi = createFocus(ctx, { cards, isolation, director, doors })
  const tour = createTour(ctx, { focusApi })
  const intro = createIntro(ctx, { director })

  const registry = [isolation, tour, intro, doors, cards]

  cards.setEnabled(urlState.fx.has('cards'))
  focusApi.setEnabled(urlState.fx.has('focus'))

  // 开场 x 聚焦互斥(L1) + 输入门控: 扫场期间聚焦/悬停停用, Esc 可中止
  isolation.setIntroInterlock(() => intro.abort())
  let introActive = false
  events.on('intro', (on) => {
    introActive = on
    focusApi.setEnabled(on ? false : urlState.fx.has('focus'))
  })
  /** 开场统一入口: 先撤巡检与聚焦(清空 isolation 台账)再快照 —— 幽灵永不入台账 */
  function playIntroClean() {
    tour.stop()
    focusApi.blur()
    intro.play()
  }

  shell.setTelemetryIds(stationList.filter((s) => s.hasTelemetry).map((s) => s.id))

  /** 状态分发单点: 剧本与片段模式都走这里喂卡片层与顶栏计数 */
  function pushState(id, state) {
    cards.setStationState(id, state)
    shell.setStationState(id, state)
  }
  simFeed.onChange((changes) => {
    for (const { id, state } of changes) pushState(id, state)
  })

  const carriage = probeCarriage(load.nodeIndex) // 必须早于任何 rig 写入(采 home 基准)
  const follow = createCarriageFollow({
    carriage, stations, simFeed, invalidateShadows: stage.invalidateShadows,
  })

  // -- 流程片段播放模式 ------------------------------------------------------------
  const clipMode = createClipMode(ctx, {
    simFeed,
    follow,
    pushState,
    onStatus: (s) => {
      panelApi?.setClipStatus(s)
      shell.setClipStatus(s)
    },
    onExit: () => {
      // 回到剧本模式: 把剧本当前状态整批重推(片段状态别残留在卡片上)
      const all = simFeed.getAll()
      for (const id of Object.keys(all)) pushState(id, all[id])
    },
  })
  const flowListPromise = clipMode.loadFlowList().catch((error) => {
    console.warn('[fx-preview] flow-index 加载失败', error)
    return []
  })

  // BVH 渐进构建: 每帧 4ms 预算, 不卡首屏; 建完悬停与点选拾取才启用
  const geometries = [...new Set(machineMeshes.map((mesh) => mesh.geometry))]
  let bvhCursor = 0

  stage.addFrameHook((delta, elapsed) => {
    refreshViewport() // 必须第一行: 本帧所有屏幕坐标换算(卡片/悬停/探针)读同一份视口
    simFeed.tick(delta)
    clipMode.update(delta) // 片段驱动机构在前, 卡片锚点读这帧刚写好的 transform
    follow.update()
    for (const fx of registry) fx.update(delta, elapsed)
    if (bvhCursor < geometries.length) {
      const t0 = performance.now()
      while (bvhCursor < geometries.length && performance.now() - t0 < 4) {
        const geometry = geometries[bvhCursor]
        bvhCursor += 1
        if (!geometry.boundsTree) geometry.computeBoundsTree()
      }
      if (bvhCursor >= geometries.length) occluder.ready = true
    }
  })

  // -- 定格(截图矩阵的核心入口) ----------------------------------------------------
  /**
   * 功能: 把画面钉在动画时刻 t: 先用合成时间把过渡类视觉快进到稳态, 再冻结时钟.
   * @param {number} t 目标动画时刻(秒)
   */
  function freezeAt(t) {
    simFeed.freeze(true)
    // 3.2s 快进窗口与 fxConfig.intro 的开场总时长绑定(durS+tailS=3.2) —— 改长要同步!
    const from = Math.max(t - 3.2, 0)
    for (let e = from; e < t - 1e-9; e += 0.08) {
      for (const fx of registry) fx.update(0.08, e + 0.08)
    }
    stage.clock.freezeTime(t)
  }

  // -- URL 初始动作 ----------------------------------------------------------------
  if (urlState.step !== null) simFeed.jumpToStep(urlState.step)
  if (urlState.clip) {
    try {
      await clipMode.loadClip(urlState.clip)
      if (urlState.clipt !== null) clipMode.seek(urlState.clipt)
    } catch (error) {
      result.errors.push(`片段载入失败: ${error?.message || error}`)
    }
  }
  const wantFreeze = urlState.freeze || urlState.freezetime !== null
  if (urlState.focus) focusApi.focus(urlState.focus, { instant: wantFreeze })
  if (wantFreeze) freezeAt(urlState.freezetime ?? 2.0)
  else if (urlState.fx.has('intro') && urlState.intro && !urlState.focus && !urlState.clip) playIntroClean()

  // -- 面板 -----------------------------------------------------------------------
  /** 面板滑杆改过的 cfg.* 覆写(回写 URL 用, 复制地址即可复现调参结果) */
  const cfgOverrides = new Map()

  /** 面板/快捷键改动后把状态回写地址栏(URL 即完整场景) */
  function syncUrl() {
    const search = new URLSearchParams(location.search)
    for (const [key, value] of cfgOverrides) search.set(key, value)
    const qs = serializeUrlState(urlState, `?${search.toString()}`)
    history.replaceState(null, '', location.pathname + (qs ? `?${qs}` : ''))
  }

  /** 特效参数落值(不回写 URL 的内核; setParam 与 captureStationView 共用) */
  function applyParam(path, value) {
    setPath(config, path, value)
    if (path === 'postfx.bloomIntensity') post.setBloomIntensity(value)
    cfgOverrides.set(`cfg.${path}`, String(value))
  }

  const persistentFx = { cards, focus: focusApi }
  const panel = createPanel({
    host: panelHost,
    state: urlState,
    config,
    stationList,
    events,
    actions: {
      setTheme: gotoTheme, // 主题热切不做, 整页 reload
      toggleFx(key, on) {
        persistentFx[key]?.setEnabled(on)
        if (on) urlState.fx.add(key)
        else urlState.fx.delete(key)
        result.fx = [...urlState.fx]
        syncUrl()
      },
      intro: () => playIntroClean(),
      toggleTour: () => tour.toggle(),
      setScenario(name) {
        simFeed.setScenario(name)
        urlState.scenario = name
        result.scenario = name
        shell.setScenario(name)
        syncUrl()
      },
      setSpeed(v) {
        simFeed.setSpeed(v)
        urlState.speed = v
        syncUrl()
      },
      injectError: () => simFeed.injectError('DEVELOP'),
      setStationHealth(id, health) {
        if (health) simFeed.set(id, { health })
        else simFeed.clearOverride(id)
      },
      clearOverrides: () => simFeed.clearOverride(),
      setParam(path, value) {
        applyParam(path, value)
        syncUrl()
      },
      /** 把当前手调好的机位固化为选中工位的定制视角(写 config + cfg.* URL) */
      captureStationView() {
        const id = focusApi.current()
        if (!id) return null
        const view = director.captureStationView(id)
        if (!view) return null
        applyParam(`stationViews.${id}.azDeg`, view.azDeg)
        applyParam(`stationViews.${id}.elDeg`, view.elDeg)
        applyParam(`stationViews.${id}.fill`, view.fill)
        syncUrl()
        return { id, ...view }
      },
      setDisplay(path, value) {
        setPath(config, path, value)
        stage.applyDisplay()
        cfgOverrides.set(`cfg.${path}`, String(value))
        syncUrl()
      },
      setIsolation(mode) {
        isolation.setMode(mode)
        urlState.isolate = mode
        syncUrl()
      },
      loadClip(name) {
        urlState.clip = name
        syncUrl()
        clipMode.loadClip(name).catch(() => {})
      },
      clipToggle: () => clipMode.toggle(),
      clipSeek: (t) => clipMode.seek(t),
      clipSpeed: (v) => clipMode.setSpeed(v),
      clipLoop: (on) => clipMode.setLoop(on),
      clipExit() {
        clipMode.exit()
        urlState.clip = ''
        urlState.clipt = null
        syncUrl()
      },
      preset: (name) => director.applyPreset(name),
      setAutorotate(on) {
        stage.setAutorotate(on)
        urlState.autorotate = on
        syncUrl()
      },
      setCarriageFollow: (on) => follow.setEnabled(on),
      copyUrl: () => navigator.clipboard?.writeText(location.href),
    },
  })
  panelApi = panel
  flowListPromise.then((flows) => {
    panel.setClipFlows(flows, clipMode.status.clipName)
    if (clipMode.isActive()) panel.setClipStatus(clipMode.status) // URL 直达片段时补一次面板回显
  })
  setInterval(() => {
    const s = stage.stats
    panel.setStats(`${s.fps} fps · ${s.drawCalls} calls · ${(s.triangles / 1000).toFixed(0)}k tri`
      + `${occluder.ready ? '' : ' · BVH 构建中'}`)
  }, 500)

  // -- 快捷键 ---------------------------------------------------------------------
  window.addEventListener('keydown', (event) => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return
    if (introActive) {
      if (event.key === 'Escape') intro.abort({ snapCamera: true }) // 扫场期间只认 Esc 中止
      return
    }
    if (event.key === 'h' || event.key === 'H') panel.toggle()
    else if (event.key === 'Escape') focusApi.blur()
    else if (event.key === 't' || event.key === 'T') tour.toggle()
    else if (/^[1-9]$/.test(event.key)) {
      const station = stationListByX[Number(event.key) - 1] // 与巡检同为空间左→右序
      if (station) focusApi.focus(station.id)
    }
  })

  // -- 启动与对外 API ----------------------------------------------------------------
  msg('')
  stage.start()

  const _dbgV = new THREE.Vector3()
  const _dbgS = { x: 0, y: 0, depth: 0, dist: 0, visible: false }
  const _dbgBox = new THREE.Box3()
  const _dbgMeshBox = new THREE.Box3()

  /** 把一个世界盒的 8 角投到屏幕, 累进包络 */
  function projectBoxInto(box, envelope) {
    for (const cx of [box.min.x, box.max.x]) {
      for (const cy of [box.min.y, box.max.y]) {
        for (const cz of [box.min.z, box.max.z]) {
          _dbgV.set(cx, cy, cz)
          ctx.screenOf(_dbgV, _dbgS)
          envelope.x1 = Math.min(envelope.x1, _dbgS.x)
          envelope.x2 = Math.max(envelope.x2, _dbgS.x)
          envelope.y1 = Math.min(envelope.y1, _dbgS.y)
          envelope.y2 = Math.max(envelope.y2, _dbgS.y)
        }
      }
    }
  }

  result.api = {
    focus: (id) => focusApi.focus(id, { instant: true }),
    blur: () => focusApi.blur(),
    tourStep: (i) => tour.tourStep(i),
    playIntro: () => playIntroClean(),
    abortIntro: () => intro.abort({ snapCamera: true }),
    introRunning: () => intro.isRunning(),
    toggleDoor: (name) => doors.toggleDoor(name),
    setDoor: (name, open) => doors.setDoor(name, open),
    doorStates: () => doors.doorStates(),
    captureStationView: (id) => director.captureStationView(id || focusApi.current()),
    freezeTime: (t) => freezeAt(t),
    unfreeze: () => {
      simFeed.freeze(false)
      stage.clock.unfreeze()
    },
    setScenario: (name) => simFeed.setScenario(name),
    jumpToStep: (i) => simFeed.jumpToStep(i),
    setStation: (id, health) => (health ? simFeed.set(id, { health }) : simFeed.clearOverride(id)),
    stats: () => ({ ...stage.stats, bvhReady: occluder.ready }),
    hoveredStation: () => cards.hoveredStation(),
    /**
     * 功能: 验收探针 —— 屏幕点 (x,y) 处的悬停射线会打中哪个工位(不动鼠标).
     * @param {number} x **页面**像素 x(与 page.mouse.move 同系; 画布偏移在此折算)
     * @param {number} y **页面**像素 y
     * @returns {string|null} 工位 id
     */
    hoverProbe(x, y) {
      if (!occluder.ready) return null
      refreshViewport()
      const ray = new THREE.Raycaster()
      ray.firstHitOnly = true
      ray.setFromCamera(new THREE.Vector2(
        ((x - _vp.left) / _vp.width) * 2 - 1,
        -((y - _vp.top) / _vp.height) * 2 + 1,
      ), stage.camera)
      const hits = ray.intersectObjects(machineMeshes, false)
      const hit = hits.find((entry) => entry.object.visible)
      return hit ? meshToStation.get(hit.object) || null : null
    },

    loadClip: (name) => clipMode.loadClip(name),
    clipSeek: (t) => clipMode.seek(t),
    clipToggle: () => clipMode.toggle(),
    clipExit: () => clipMode.exit(),
    clipStatus: () => ({ ...clipMode.status }),
    setIsolation: (mode) => isolation.setMode(mode),
    setDisplay(patch) {
      for (const [key, value] of Object.entries(patch || {})) setPath(config, `display.${key}`, value)
      stage.applyDisplay()
    },

    /**
     * 功能: 锚点准度自检数据 —— 每工位: 锚点屏幕位 + "顶部带"网格的屏幕包络 +
     * 整工位屏幕包络. 断言口径: 锚点 x 应落在顶部带包络的水平范围内.
     * 出参一律**页面像素**(可直接喂 hoverProbe / page.mouse.move).
     * @returns {Record<string, object>}
     */
    debugAnchors() {
      const out = {}
      refreshViewport()
      /** screenOf 出的是画布局部像素, 报告前折回页面像素 */
      const toPage = (env) => {
        env.x1 += _vp.left
        env.x2 += _vp.left
        env.y1 += _vp.top
        env.y2 += _vp.top
        return env
      }
      for (const station of stationList) {
        station.getAnchor(_dbgV, config.cards.anchorLift)
        ctx.screenOf(_dbgV, _dbgS)
        const anchor = { x: _dbgS.x + _vp.left, y: _dbgS.y + _vp.top, visible: _dbgS.visible }

        station.getWorldBounds(_dbgBox)
        const cut = _dbgBox.max.y - Math.max((_dbgBox.max.y - _dbgBox.min.y) * config.cards.anchorBand, 0.02)
        const top = { x1: Infinity, x2: -Infinity, y1: Infinity, y2: -Infinity }
        // 动态工位(机械臂·地轨)锚点只认动件子树, 顶部带包络同口径
        const anchorMeshes = station.isDynamic
          ? station.meshes.filter((mesh) => {
            let node = mesh
            while (node) {
              if (node === station.object) return true
              node = node.parent
            }
            return false
          })
          : station.meshes
        for (const mesh of anchorMeshes) {
          _dbgMeshBox.setFromObject(mesh, true)
          if (_dbgMeshBox.isEmpty() || _dbgMeshBox.max.y < cut) continue
          projectBoxInto(_dbgMeshBox, top)
        }
        const whole = { x1: Infinity, x2: -Infinity, y1: Infinity, y2: -Infinity }
        projectBoxInto(_dbgBox, whole)
        out[station.id] = { anchor, top: toPage(top), whole: toPage(whole), label: station.label }
      }
      return out
    },

    /**
     * 功能: 隔离/聚焦实体化自检 —— 可见数/幽灵台账/选中工位材质是否保持原引用.
     * @returns {object}
     */
    debugVisibility() {
      let visible = 0
      for (const mesh of machineMeshes) {
        if (mesh.visible) visible += 1
      }
      const selected = isolation.current()
      const station = selected ? stations.get(selected) : null
      // 聚焦实体化判据: 选中工位网格的材质没有一个是幽灵材质(transparent 低透明度)
      let selectedSolid = true
      if (station) {
        for (const mesh of station.meshes) {
          const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
          for (const material of materials) {
            if (material?.transparent && material.opacity <= ctx.config.focus.ghostOpacity + 0.01) {
              selectedSolid = false
            }
          }
        }
      }
      return {
        total: machineMeshes.length,
        visible,
        selected,
        selectedMeshes: station?.meshes.length ?? 0,
        selectedSolid,
        ...isolation.counts(),
      }
    },
  }

  // 出过若干帧再举 ready(保证截图脚本等到的是已渲染画面)
  let readyFrames = 0
  const unhookReady = stage.addFrameHook(() => {
    readyFrames += 1
    if (readyFrames >= 5) {
      result.ready = true
      unhookReady()
    }
  })
}

main().catch((error) => {
  console.error('[fx-preview] 启动失败', error)
  result.errors.push(String(error?.message || error))
  result.ready = true // fail fast: 让截图脚本读到 errors 而不是傻等
  msg(`效果预览启动失败\n\n${error?.message || error}`)
})
