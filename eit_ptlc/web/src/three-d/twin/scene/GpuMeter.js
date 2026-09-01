/**
 * 功能: 渲染耗时计量 —— 面板"GPU 负载条"与"逐项开销增量实测"的数据源.
 *
 * 两条计量通道:
 *   - CPU 提交耗时(frameMs): render 调用前后 performance.now() 差分. rAF 循环每帧
 *     无条件全渲, 所以静止时它也真实反映渲染管线的每帧成本, 且不被 vsync 的 16.7ms
 *     节拍锁死(那是整帧间隔, 不是 render 调用本身).
 *   - GPU 真实耗时(gpuMs): WebGL2 的 EXT_disjoint_timer_query_webgl2. three 的经典
 *     WebGLRenderer 没有任何封装, 这里自封(写法范本: three 仓库 webgl-fallback 的
 *     WebGLTimestampQueryPool). 约束: 同一时刻只能有一个 TIME_ELAPSED 查询在飞,
 *     结果异步到达(晚几帧), GPU_DISJOINT_EXT 置位时所有在飞样本作废.
 *     Windows Chrome(ANGLE)/iOS Safari 普遍不支持 —— frameMs 是主指标, gpuMs 是增强.
 *
 * 本文件同时提供纯逻辑件(median/RollingStat/DeltaProbe), 供 node --test 直接单测.
 */

/**
 * 功能: 数组中位数.
 * @param {number[]} values 样本
 * @returns {number|null} 中位数(空数组为 null)
 */
export function median(values) {
  if (!values || !values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = sorted.length >> 1
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/** 滚动样本窗口(默认 120 帧 ≈ 2 秒) */
export class RollingStat {
  /**
   * @param {number} [limit=120] 窗口容量
   */
  constructor(limit = 120) {
    this.limit = limit
    this.values = []
  }

  /**
   * 功能: 压入一个样本(非有限值忽略), 超容量淘汰最旧.
   * @param {number} value 样本
   * @returns {void}
   */
  push(value) {
    if (!Number.isFinite(value)) return
    this.values.push(value)
    if (this.values.length > this.limit) this.values.shift()
  }

  /**
   * 功能: 当前窗口中位数.
   * @returns {number|null} 中位数
   */
  median() {
    return median(this.values)
  }

  /**
   * 功能: 清空窗口.
   * @returns {void}
   */
  reset() {
    this.values.length = 0
  }

  /** 样本数 */
  get size() {
    return this.values.length
  }
}

/**
 * 增量测量状态机: settle 相丢样(吃掉 shader 重编译尖峰与管线暖机) -> sampling 相
 * 收样 -> done 给出 after 中位数与相对 before 的差值. 纯时序逻辑, now 可注入以便单测.
 */
export class DeltaProbe {
  /**
   * @param {object} [options] 选项
   * @param {number} [options.settleMs=300] 稳定期时长
   * @param {number} [options.sampleMs=700] 采样期时长
   * @param {() => number} [options.now] 时钟(默认 performance.now)
   */
  constructor({ settleMs = 300, sampleMs = 700, now = () => performance.now() } = {}) {
    this.settleMs = settleMs
    this.sampleMs = sampleMs
    this.now = now
    this.phase = 'idle'
    this.before = null
    this.samples = []
    this._t0 = null
  }

  /**
   * 功能: 启动测量.
   * @param {number} before 切换前的基线中位数
   * @returns {void}
   */
  start(before) {
    this.before = before
    this.samples = []
    this._t0 = this.now()
    this.phase = 'settle'
  }

  /**
   * 功能: 每帧喂一个样本推进状态机(样本可为 null, 只推进时间不入样).
   * @param {number|null} sample 本帧耗时样本
   * @returns {{phase: string, deltaMs?: number|null, afterMedian?: number|null}} 进度
   */
  tick(sample) {
    if (this.phase !== 'settle' && this.phase !== 'sampling') return { phase: this.phase }
    const elapsed = this.now() - this._t0
    if (elapsed < this.settleMs) {
      this.phase = 'settle'
      return { phase: 'settle' }
    }
    if (elapsed < this.settleMs + this.sampleMs) {
      this.phase = 'sampling'
      if (Number.isFinite(sample)) this.samples.push(sample)
      return { phase: 'sampling' }
    }
    this.phase = 'done'
    const after = median(this.samples)
    return {
      phase: 'done',
      afterMedian: after,
      deltaMs: after === null || !Number.isFinite(this.before) ? null : after - this.before,
    }
  }

  /**
   * 功能: 中止测量(档位/主题切换、页面隐藏时调用, 样本作废).
   * @returns {void}
   */
  abort() {
    this.phase = 'aborted'
  }
}

export class GpuMeter {
  /**
   * 功能: 绑定一个 WebGL2 上下文; 拿不到计时扩展时自动退化为纯 CPU 通道.
   * @param {WebGL2RenderingContext|null} gl 渲染上下文
   */
  constructor(gl) {
    this.gl = gl || null
    this.ext = this.gl && typeof this.gl.getExtension === 'function'
      ? this.gl.getExtension('EXT_disjoint_timer_query_webgl2')
      : null
    this.gpuAvailable = Boolean(this.ext && this.gl && typeof this.gl.createQuery === 'function')

    this._cpuStat = new RollingStat()
    this._gpuStat = new RollingStat()
    /** @type {WebGLQuery[]} 已 endQuery、等待结果的查询(FIFO) */
    this._pending = []
    /** @type {WebGLQuery|null} 本帧在飞的查询 */
    this._active = null
    this._t0 = null

    /** 最近一帧的 CPU 提交耗时(毫秒) */
    this.lastCpuMs = null
    /** 最近一次解析出的 GPU 耗时(毫秒); 没有新结果的帧为 null */
    this.lastGpuMs = null
  }

  /**
   * 功能: 帧首调用 —— 回收已就绪的 GPU 查询、起新查询、记 CPU 起点.
   * @returns {void}
   */
  beginFrame() {
    this.lastGpuMs = null
    if (this.gpuAvailable) {
      this._resolvePending()
      if (!this._active && this._pending.length < 8) {
        this._active = this.gl.createQuery()
        this.gl.beginQuery(this.ext.TIME_ELAPSED_EXT, this._active)
      }
    }
    this._t0 = performance.now()
  }

  /**
   * 功能: 帧尾调用 —— 收 CPU 样本、结束在飞查询.
   * @returns {void}
   */
  endFrame() {
    if (this._t0 !== null) {
      this.lastCpuMs = performance.now() - this._t0
      this._cpuStat.push(this.lastCpuMs)
      this._t0 = null
    }
    if (this._active) {
      this.gl.endQuery(this.ext.TIME_ELAPSED_EXT)
      this._pending.push(this._active)
      this._active = null
    }
  }

  /**
   * 功能: 回收就绪查询. DISJOINT 置位(GPU 计时不可靠, 如变频/上下文切换)时
   *       丢弃全部在飞样本 —— 读该参数本身会清标志位.
   * @returns {void}
   */
  _resolvePending() {
    if (!this._pending.length) return
    const { gl, ext } = this
    if (gl.getParameter(ext.GPU_DISJOINT_EXT)) {
      for (const query of this._pending) gl.deleteQuery(query)
      this._pending.length = 0
      return
    }
    while (this._pending.length) {
      const query = this._pending[0]
      if (!gl.getQueryParameter(query, gl.QUERY_RESULT_AVAILABLE)) break
      const ns = gl.getQueryParameter(query, gl.QUERY_RESULT)
      gl.deleteQuery(query)
      this._pending.shift()
      const ms = ns / 1e6
      this._gpuStat.push(ms)
      this.lastGpuMs = ms
    }
  }

  /**
   * 功能: 当前窗口的汇总(供负载条与增量测量的基线).
   * @returns {{frameMs: number|null, gpuMs: number|null, gpuAvailable: boolean, samples: number}} 汇总
   */
  snapshot() {
    return {
      frameMs: this._cpuStat.median(),
      gpuMs: this.gpuAvailable ? this._gpuStat.median() : null,
      gpuAvailable: this.gpuAvailable,
      samples: this._cpuStat.size,
    }
  }

  /**
   * 功能: 清空窗口与在飞查询(增量测量切换点、档位/主题变化时调用).
   * @returns {void}
   */
  reset() {
    this._cpuStat.reset()
    this._gpuStat.reset()
    this.lastCpuMs = null
    this.lastGpuMs = null
    if (this.gl) {
      if (this._active) {
        this.gl.endQuery(this.ext.TIME_ELAPSED_EXT)
        this.gl.deleteQuery(this._active)
        this._active = null
      }
      for (const query of this._pending) this.gl.deleteQuery(query)
    }
    this._pending.length = 0
    this._t0 = null
  }

  /**
   * 功能: 释放全部查询对象.
   * @returns {void}
   */
  dispose() {
    this.reset()
  }
}
