/**
 * 功能: 回放播放头 —— 墙钟前进量 × 倍速 = 录像时间前进量.
 *
 * 做成纯对象(不碰 DOM/three/网络)是刻意的: 倍速、seek、边界钳位这些最容易出错、也
 * 最难在浏览器里复现的语义, 全部可以离线单测。
 *
 * 单位约定(硬约束): 播放头是**绝对纪元秒**, 与录像和线上事件一致; nowMs() 出的是
 * 绝对纪元**毫秒**, 直接喂给 TwinFeed.now。各 store 的 stampMs 把 < 1e12 判为秒并
 * 乘 1000, 用 0 基时间会让采样器永远钳在第一帧, 画面卡住却不报错。
 */
export class ReplayClock {
  /**
   * @param {object} [options]
   * @param {number} [options.t0] 录像可用区间起点(纪元秒)
   * @param {number} [options.t1] 录像可用区间终点(纪元秒)
   * @param {number} [options.speed] 初始倍速
   */
  constructor({ t0 = 0, t1 = 0, speed = 1 } = {}) {
    this.t0 = t0
    this.t1 = t1
    this.playhead = t0
    this.speed = speed
    this.playing = false
    /** 每次不连续跳转自增 —— 消费者据此判断"必须清场并重播关键帧"。 */
    this.epoch = 0
  }

  /** 可拖动区间; 录像还在增长时由调用方持续更新。 */
  setRange(t0, t1) {
    this.t0 = t0
    this.t1 = t1
    this.playhead = Math.min(Math.max(this.playhead, t0), t1)
  }

  setSpeed(speed) {
    const value = Number(speed)
    if (Number.isFinite(value) && value > 0) this.speed = value
  }

  play() { this.playing = true }
  pause() { this.playing = false }

  /**
   * 功能: 跳到某时刻; 一律视为不连续跳转并自增 epoch.
   *
   * 向前跳同样要自增: 跨过的那段事件没有被喂进去, 各 buffer 里留着的是跳转前的
   * 轨迹, 不清场的话会沿一条并不存在的补间路径插值过去(甚至穿模)。
   */
  seek(t) {
    const target = Math.min(Math.max(Number(t) || 0, this.t0), this.t1)
    this.playhead = target
    this.epoch += 1
    return target
  }

  /**
   * 功能: 只移动播放头, **不**自增 epoch —— 拖动向前掠过用.
   *
   * 必须与 seek() 分开: seek 自增 epoch 就会触发宿主清场, 而"向前掠过"恰恰是那条
   * 不需要清场的路径(数据已在手, 等同快进)。复用 seek 会把这条免费路径变成最贵的。
   *
   * @param {number} t 目标时刻(纪元秒)
   * @returns {number} 钳位后的播放头
   */
  scrub(t) {
    this.playhead = Math.min(Math.max(Number(t) || 0, this.t0), this.t1)
    return this.playhead
  }

  /**
   * 功能: 按墙钟前进量推进播放头.
   * @param {number} realDeltaS 墙钟前进秒数
   * @returns {number} 新的播放头(纪元秒)
   */
  advance(realDeltaS) {
    if (!this.playing) return this.playhead
    const delta = Number(realDeltaS)
    if (!Number.isFinite(delta) || delta <= 0) return this.playhead
    const next = this.playhead + delta * this.speed
    if (next >= this.t1) {
      // 撞到录像末尾: 停在末尾而不是绕回, 且不自增 epoch(是连续到达, 不是跳转)
      this.playhead = this.t1
      this.playing = false
    } else {
      this.playhead = next
    }
    return this.playhead
  }

  /** 喂给 TwinFeed.now 的绝对纪元毫秒。 */
  nowMs() {
    return this.playhead * 1000
  }

  /** 已播比例 [0,1], 供进度条使用。 */
  get progress() {
    const span = this.t1 - this.t0
    return span > 0 ? (this.playhead - this.t0) / span : 0
  }

  snapshot() {
    return {
      t0: this.t0,
      t1: this.t1,
      playhead: this.playhead,
      speed: this.speed,
      playing: this.playing,
      epoch: this.epoch,
      progress: this.progress,
    }
  }
}
