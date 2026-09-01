/**
 * 功能: 流程片段播放模式 —— 把正式演示页(/3d/demo)那批离线精编译片段接进沙盒:
 * 真机构动画 + AR 状态卡片联动("现在哪个工位在动"实时高亮).
 *
 * 接线要点(全部来自对 anim/* 栈的摸底):
 *   - 绕开 MachineRig(它只是 SceneManager 的一层皮), 直接用 MachineStateDriver
 *     ({manifest, resolve} 纯注入) —— 沙盒零 SceneManager 依赖不破;
 *   - ClipPlayer 不传 cameraRig/manifest => 片段里的 camera 事件整条旁路(不抢相机);
 *   - 三个资产 fetch 必须带 ?t= 时间戳(后端不发 Cache-Control, 重编译后会吃旧片段);
 *   - v2/v3 片段必须配 robot-points.json, hash 不符 compileClip 硬抛 —— 抓住并显示;
 *   - **compileClip 丢掉 do 载荷**: "哪个工位在动"要留着 parseClip 的原始 doc,
 *     经 clipStation.js 纯函数反查; 卡片动作行直接用步骤中文 label;
 *   - 与沙盒滑座跟随(carriageFollow)写同一个 CARRIAGE 节点: 进片段模式必须停它,
 *     地轨交给 rig.setAxisMm; 退出再还给它;
 *   - 向后 seek = rig.home() 后重放, 播完/退出 rig.home() 收场(液面清空是播放态语义).
 */
import { ClipPlayer } from '../three-d/anim/ClipPlayer.js'
import { MachineStateDriver } from '../three-d/anim/MachineStateDriver.js'
import { parseClip, compileClip } from '../three-d/anim/clipSchema.js'

import { buildStationLookup, stationOfStep, STATION_ALIAS } from './clipStation.js'

/**
 * 功能: 创建片段播放模式.
 * @param {object} ctx 沙盒上下文
 * @param {object} deps 依赖
 * @param {object} deps.simFeed 模拟剧本(片段模式期间冻结)
 * @param {object} deps.follow 滑座跟随(片段模式期间停用)
 * @param {(id: string, state: object) => void} deps.pushState 状态分发(喂 cards/rings)
 * @param {(status: object) => void} [deps.onStatus] 播放状态回调(面板/api 消费, 10Hz 节流)
 * @param {() => void} [deps.onExit] 退出片段模式后的回调(main 用它恢复剧本状态)
 * @returns {object} clipMode 实例
 */
export function createClipMode(ctx, { simFeed, follow, pushState, onStatus, onExit }) {
  const lookup = buildStationLookup(ctx.manifest)
  const cardStations = ctx.stationList

  /** @type {MachineStateDriver|null} */
  let rig = null
  /** @type {ClipPlayer|null} */
  let player = null
  /** @type {object|null} parseClip 的原始文档(工位推导要用 do 载荷) */
  let doc = null
  let active = false
  /** @type {Promise<object>|null} 点表缓存(v2/v3 片段共用) */
  let pointsPromise = null
  /** @type {Record<string, {health: string, action: string, progress: number}>} 上次已推送的状态 */
  let pushed = {}
  /** @type {THREE.Object3D[]} 当前进辉光选集的工艺灯 */
  let litObjects = []
  let litKey = ''
  let lastStatusAt = 0

  const status = {
    active: false,
    clipName: '',
    label: '',
    time: 0,
    duration: 0,
    playing: false,
    speed: 1,
    stepIndex: 0,
    stepLabel: '',
    station: null,
    missing: 0,
    error: '',
  }

  async function fetchText(url) {
    const response = await fetch(`${url}?t=${Date.now()}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`)
    return response.text()
  }

  function getPoints() {
    if (!pointsPromise) {
      pointsPromise = fetchText('/api/3d/assets/generated/robot-points.json').then((t) => JSON.parse(t))
    }
    return pointsPromise
  }

  function ensureRig() {
    if (rig) return
    const resolve = (path) => ctx.nodeIndex.get(path) || ctx.nodeIndex.get(String(path).split('/').pop())
    rig = new MachineStateDriver({ manifest: ctx.manifest, resolve })
    status.missing = rig.missing?.length || 0
    player = new ClipPlayer({ rig, onChange: handleTransport }) // 刻意不传 cameraRig/manifest: 旁路镜头事件
  }

  /** 把"第 stepIndex 步在 station 忙"翻译成整批工位状态并按需分发 */
  function distributeStates(stepIndex, time) {
    const step = player?.clip?.steps?.[stepIndex]
    const raw = doc ? stationOfStep(doc, stepIndex, lookup) : null
    const station = raw ? (STATION_ALIAS[raw] || raw) : null // 地轨动作归入机械臂组显示
    status.stepIndex = stepIndex
    status.stepLabel = step?.label || ''
    status.station = station

    for (const entry of cardStations) {
      const desired = entry.id === station
        ? {
          health: 'busy',
          action: step?.label || '执行中',
          progress: step && step.dur > 0 ? Math.min(Math.max((time - step.at) / step.dur, 0), 1) : 0,
        }
        : { health: entry.hasTelemetry ? 'ok' : 'unknown', action: '', progress: 0 }
      const prev = pushed[entry.id]
      if (!prev || prev.health !== desired.health || prev.action !== desired.action
        || Math.abs(prev.progress - desired.progress) >= 0.02) {
        pushed[entry.id] = desired
        pushState(entry.id, desired)
      }
    }
  }

  /** ClipPlayer 的 onChange(播放时每帧触发): 状态分发全速, 面板回调 10Hz 节流 */
  function handleTransport(transport) {
    status.time = transport.time
    status.duration = transport.duration
    status.playing = transport.playing
    status.speed = transport.speed
    distributeStates(transport.stepIndex, transport.time)
    const now = performance.now()
    if (now - lastStatusAt > 100 || !transport.playing) {
      lastStatusAt = now
      onStatus?.(status)
    }
  }

  function enter() {
    if (active) return
    active = true
    status.active = true
    simFeed.freeze(true)
    follow.setEnabled(false) // 滑座交还给 rig.setAxisMm, 两个写方不打架
    pushed = {}
  }

  return {
    name: 'clipMode',
    status,
    isActive: () => active,

    /**
     * 功能: 取可播放流程清单(flow-index 里 status==='ok' 的).
     * @returns {Promise<Array<{clipName: string, label: string, group: string}>>}
     */
    async loadFlowList() {
      const index = JSON.parse(await fetchText('/api/3d/assets/clips/flow-index.json'))
      const flows = []
      for (const flow of index.flows || []) {
        if (flow.status !== 'ok') continue
        for (const clip of flow.clips || []) {
          flows.push({ clipName: clip.clipName, label: clip.label || clip.clipName, group: flow.group || '' })
        }
      }
      return flows
    },

    /**
     * 功能: 载入并进入片段模式(不自动播放; 面板/api 再 toggle).
     * @param {string} clipName 片段名(如 flow.sampling_execute)
     * @returns {Promise<void>}
     */
    async loadClip(clipName) {
      ensureRig()
      enter()
      status.error = ''
      try {
        const text = await fetchText(`/api/3d/assets/clips/${clipName}.yaml`)
        doc = parseClip(text)
        const pointCatalog = doc.schema === 'ptlc.clip/v1' ? null : await getPoints()
        const compiled = compileClip(doc, { pointCatalog })
        player.load(compiled)
        status.clipName = clipName
        status.label = doc.label || clipName
        ctx.invalidateShadows()
      } catch (error) {
        status.error = String(error?.message || error)
        onStatus?.(status)
        throw error
      }
      onStatus?.(status)
    },

    /** 功能: 退出片段模式, 机器回 home, 恢复模拟剧本与滑座跟随. */
    exit() {
      if (!active) return
      player?.dispose() // 停播 + rig.home() + clip=null
      doc = null
      active = false
      status.active = false
      status.clipName = ''
      status.playing = false
      status.error = ''
      for (const object of litObjects) ctx.bloom.remove(object)
      litObjects = []
      litKey = ''
      follow.setEnabled(true)
      simFeed.freeze(false)
      ctx.invalidateShadows()
      onStatus?.(status)
      onExit?.()
    },

    toggle() {
      if (player?.clip) player.toggle()
    },
    seek(t) {
      if (player?.clip && Number.isFinite(t)) player.seek(t)
    },
    setSpeed(v) {
      player?.setSpeed(v)
    },
    setLoop(on) {
      if (player) player.loop = !!on
    },

    /** 每帧(main 帧钩子调, 在特效 update 之前 —— 特效要读这帧刚写好的 transform) */
    update(delta) {
      if (!active || !player) return
      player.tick(delta)
      if (player.playing) ctx.invalidateShadows()
      // 工艺灯辉光: 集合变化才重设(照 useMotionStack 的节流写法)
      const lit = rig?.bloomLights?.() || []
      const key = lit.map((o) => o.uuid).join('|')
      if (key !== litKey) {
        for (const object of litObjects) ctx.bloom.remove(object)
        for (const object of lit) ctx.bloom.add(object)
        litObjects = lit
        litKey = key
      }
    },

    dispose() {
      this.exit()
      rig?.dispose?.()
      rig = null
      player = null
    },
  }
}
