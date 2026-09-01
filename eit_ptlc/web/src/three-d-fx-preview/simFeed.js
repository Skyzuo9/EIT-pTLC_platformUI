/**
 * 功能: 模拟状态驱动器 —— 用确定性剧本产出各工位的 {health, action, progress}.
 *
 * 纯逻辑零依赖(不碰 three/DOM/定时器), 时间由宿主 tick() 注入, 因此:
 *   - node --test 可以直接喂时间断言状态;
 *   - 截图脚本能 jumpToStep()+freeze() 定格到剧本任意时刻, 永远复现同一画面.
 * 零随机是硬要求: 截图矩阵的可复现性建立在"同一 URL 同一画面"上.
 *
 * 健康度语义与正式页对齐(device-manifest healthStyles / node_registry.derive_health):
 *   ok=正常/空闲  busy=运行中  error=故障  offline=离线  unknown=无遥测
 * 状态形状 { health, action, progress, manual } 即特效模块 setStationState 的入参.
 */

/**
 * 循环任务剧本: 一块板在产线上流转. dur 单位秒.
 * transfer 步 = 机械臂搬运: RAIL/ROBOT 置忙, 并对外发 transfer 事件(流光带/滑座跟随消费).
 * action 名沿用真实动作命名习惯(<工位前缀>.<动作>), 与 manifest.stations[].actions 同风格.
 */
export const RUN_SCRIPT = [
  { kind: 'work', station: 'FEEDLIFT', action: 'feedlift.feed_upper', dur: 4 },
  { kind: 'transfer', from: 'FEEDLIFT', to: 'SAMPLING', dur: 3 },
  { kind: 'work', station: 'SAMPLING', action: 'sampling.aspirate', dur: 8 },
  { kind: 'transfer', from: 'SAMPLING', to: 'DEVELOP', dur: 3 },
  { kind: 'work', station: 'DEVELOP', action: 'develop.fill', dur: 10 },
  { kind: 'transfer', from: 'DEVELOP', to: 'PHOTOSCRAPE', dur: 3 },
  { kind: 'work', station: 'PHOTOSCRAPE', action: 'photoscrape.scrape_run', dur: 6 },
  { kind: 'transfer', from: 'PHOTOSCRAPE', to: 'COLLECT', dur: 3 },
  { kind: 'work', station: 'COLLECT', action: 'collect.collect', dur: 4 },
  { kind: 'transfer', from: 'COLLECT', to: 'FEEDLIFT', dur: 3 },
]

/** 剧本总时长(秒) */
export const SCRIPT_TOTAL = RUN_SCRIPT.reduce((sum, step) => sum + step.dur, 0)

/** 各步的起始时刻(秒) */
export const STEP_STARTS = (() => {
  const starts = []
  let t = 0
  for (const step of RUN_SCRIPT) {
    starts.push(t)
    t += step.dur
  }
  return starts
})()

/** error 剧本的定点故障时刻: DEVELOP 工作步开始后 4 秒 */
export const ERROR_AT = STEP_STARTS[RUN_SCRIPT.findIndex((s) => s.station === 'DEVELOP')] + 4

/** showcase 摆拍: 一帧五态全齐(静态, 不随时间变化) */
const SHOWCASE = {
  SAMPLING: { health: 'busy', action: 'sampling.aspirate', progress: 0.6 },
  ROBOT: { health: 'busy', action: 'robot.dwell', progress: 0.35 },
  DEVELOP: { health: 'error', action: 'develop.fill', progress: 0.42 },
  PUMP: { health: 'offline', action: '', progress: 0 },
}

/**
 * 功能: 创建模拟状态驱动器.
 * @param {object} options 参数对象
 * @param {string[]} options.stationIds 参与模拟的全部工位 id
 * @param {string[]} options.telemetryIds 其中有遥测节点的工位 id(其余恒 unknown)
 * @param {string} [options.scenario='running'] 剧本名 idle|running|error|showcase
 * @param {number} [options.speed=1] 剧本倍速
 * @param {number} [options.errorRecoverS=10] injectError 的自愈秒数
 * @returns {object} 驱动器实例
 */
export function createSimFeed({ stationIds, telemetryIds, scenario = 'running', speed = 1, errorRecoverS = 10 }) {
  const telemetry = new Set(telemetryIds)
  /** @type {Map<string, {health?: string, action?: string, progress?: number, expireAt?: number}>} */
  const overrides = new Map()
  const changeCbs = new Set()
  const transferCbs = new Set()

  let time = 0
  let frozen = false
  /** @type {Record<string, {health: string, action: string, progress: number, manual: boolean}>} */
  let states = {}
  let lastStepIndex = -1

  /** 剧本时刻 -> 步序号与步内进度 */
  function stepAt(t) {
    const wrapped = ((t % SCRIPT_TOTAL) + SCRIPT_TOTAL) % SCRIPT_TOTAL
    for (let i = RUN_SCRIPT.length - 1; i >= 0; i -= 1) {
      if (wrapped >= STEP_STARTS[i]) {
        return { index: i, progress: (wrapped - STEP_STARTS[i]) / RUN_SCRIPT[i].dur }
      }
    }
    return { index: 0, progress: 0 }
  }

  /** 纯函数: 剧本时刻 -> 全工位状态(不含手动覆写) */
  function scriptStates(t) {
    /** @type {Record<string, {health: string, action: string, progress: number}>} */
    const out = {}
    for (const id of stationIds) {
      out[id] = { health: telemetry.has(id) ? 'ok' : 'unknown', action: '', progress: 0 }
    }

    if (scenario === 'idle') {
      if (out.PUMP) out.PUMP.health = 'offline'
      return out
    }
    if (scenario === 'showcase') {
      for (const [id, patch] of Object.entries(SHOWCASE)) {
        if (out[id]) Object.assign(out[id], patch)
      }
      return out
    }

    // running 与 error 共用剧本; error 在定点时刻后冻结为"DEVELOP 故障, 其余待机"
    if (scenario === 'error' && t >= ERROR_AT) {
      if (out.DEVELOP) out.DEVELOP = { health: 'error', action: 'develop.fill', progress: 0.4 }
      return out
    }

    const { index, progress } = stepAt(t)
    const step = RUN_SCRIPT[index]
    if (step.kind === 'work') {
      if (out[step.station]) out[step.station] = { health: 'busy', action: step.action, progress }
    } else {
      if (out.RAIL) out.RAIL = { health: 'busy', action: 'rail.move', progress }
      if (out.ROBOT) out.ROBOT = { health: 'busy', action: 'robot.move_named', progress }
    }
    return out
  }

  /** 叠加手动覆写并处理过期 */
  function applyOverrides(base) {
    for (const [id, patch] of overrides.entries()) {
      if (patch.expireAt !== undefined && time >= patch.expireAt) {
        overrides.delete(id)
        continue
      }
      if (!base[id]) continue
      if (patch.health !== undefined) base[id].health = patch.health
      if (patch.action !== undefined) base[id].action = patch.action
      if (patch.progress !== undefined) base[id].progress = patch.progress
    }
    for (const id of Object.keys(base)) base[id].manual = overrides.has(id)
    return base
  }

  /** 重算状态, 对变化的工位发 onChange */
  function recompute() {
    const next = applyOverrides(scriptStates(time))
    const changes = []
    for (const id of stationIds) {
      const prev = states[id]
      const cur = next[id]
      if (!prev || prev.health !== cur.health || prev.action !== cur.action
        || Math.abs((prev.progress ?? 0) - cur.progress) >= 0.01 || prev.manual !== cur.manual) {
        changes.push({ id, state: cur })
      }
    }
    states = next
    if (changes.length) for (const cb of changeCbs) cb(changes)
  }

  recompute()
  lastStepIndex = stepAt(time).index

  return {
    /**
     * 功能: 推进模拟时间并发布状态变化/搬运事件.
     * @param {number} dtSeconds 帧间隔(秒, 未乘倍速)
     * @returns {void}
     */
    tick(dtSeconds) {
      if (frozen || !(dtSeconds > 0)) return
      time += dtSeconds * speed
      recompute()
      if (scenario === 'running' || (scenario === 'error' && time < ERROR_AT)) {
        const { index } = stepAt(time)
        if (index !== lastStepIndex) {
          const step = RUN_SCRIPT[index]
          if (step.kind === 'transfer') {
            for (const cb of transferCbs) cb({ from: step.from, to: step.to })
          }
          lastStepIndex = index
        }
      }
    },

    getTime: () => time,
    getAll: () => states,
    get: (id) => states[id],

    /**
     * 功能: 当前剧本步(滑座跟随/面板显示用).
     * @returns {{index: number, kind: string, station?: string, from?: string, to?: string, progress: number}|null}
     */
    getCurrentStep() {
      if (scenario === 'idle' || scenario === 'showcase') return null
      if (scenario === 'error' && time >= ERROR_AT) return null
      const { index, progress } = stepAt(time)
      return { index, progress, ...RUN_SCRIPT[index] }
    },

    setScenario(name) {
      scenario = name
      time = 0
      lastStepIndex = stepAt(0).index
      recompute()
    },
    setSpeed(v) {
      if (Number.isFinite(v) && v > 0) speed = v
    },

    /**
     * 功能: 手动覆写某工位状态(面板"手动置态"用). 覆写永久生效直到 clearOverride.
     * @param {string} id 工位 id
     * @param {object} patch { health?, action?, progress? }
     * @returns {void}
     */
    set(id, patch) {
      overrides.set(id, { ...overrides.get(id), ...patch, expireAt: undefined })
      recompute()
    },
    clearOverride(id) {
      if (id) overrides.delete(id)
      else overrides.clear()
      recompute()
    },

    /**
     * 功能: 注入一次会自愈的故障(演示 error 特效用).
     * @param {string} [id='DEVELOP'] 工位 id
     * @returns {void}
     */
    injectError(id = 'DEVELOP') {
      overrides.set(id, { health: 'error', expireAt: time + errorRecoverS })
      recompute()
    },

    /**
     * 功能: 跳到剧本第 N 步(步内 0.4s 处, 保证进度条非零可见). 截图定格用.
     * @param {number} stepIndex 步序号
     * @returns {void}
     */
    jumpToStep(stepIndex) {
      const i = Math.max(0, Math.min(RUN_SCRIPT.length - 1, Math.floor(stepIndex)))
      time = STEP_STARTS[i] + Math.min(0.4, RUN_SCRIPT[i].dur / 2)
      lastStepIndex = i
      recompute()
    },

    freeze(on) {
      frozen = on !== false
    },
    isFrozen: () => frozen,

    onChange(cb) {
      changeCbs.add(cb)
      cb(stationIds.map((id) => ({ id, state: states[id] })))
      return () => changeCbs.delete(cb)
    },
    onTransfer(cb) {
      transferCbs.add(cb)
      return () => transferCbs.delete(cb)
    },
  }
}
