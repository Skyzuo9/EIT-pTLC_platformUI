/**
 * 功能: 一维数值的时间插值 —— 把 1 Hz 的遥测采样变成 60 fps 的连续运动.
 *
 * 为什么需要: 上位机的遥测循环是 1 Hz, 直接把采样值写进场景, 轴会以每秒一次的频率
 * "跳"过去, 观感很差. 这里在两次采样之间做时间驱动的追赶: 当前值以"在一个采样周期
 * 略多一点的时间内到达目标"的速度趋近目标, 从而既连续又不会滞后太多.
 *
 * 为什么不用简单的 lerp(a, b, 0.1): 那种写法的收敛速度取决于帧率, 高刷屏和 30 fps 屏
 * 上表现不一致; 这里用与帧间隔无关的指数衰减公式, 任何帧率下的观感都相同.
 */

/** 追赶时长相对采样周期的倍数: 略大于 1 可以让运动更平滑, 代价是多约半拍延迟 */
export const ARRIVE_FACTOR = 1.25

/** 采样周期未知时的默认值(秒), 对应上位机 1 Hz 遥测 */
export const DEFAULT_SAMPLE_PERIOD = 1.0

/**
 * 功能: 创建一个插值通道.
 * @param {number} [initial=0] 初始值
 * @returns {{value: number, target: number, period: number, lastStamp: number, initialized: boolean}}
 *          通道状态对象(纯对象, 不带任何响应式代理)
 */
export function createChannel(initial = 0) {
  return {
    value: initial,
    target: initial,
    period: DEFAULT_SAMPLE_PERIOD,
    lastStamp: 0,
    initialized: false,
  }
}

/**
 * 功能: 写入一个新采样值.
 *
 * 同时按两次采样的实际间隔自适应更新采样周期 —— 后端若从 1 Hz 改成 5 Hz,
 * 插值速度会自动跟上, 无需改前端常量.
 *
 * @param {object} channel 通道状态
 * @param {number} sample 新采样值
 * @param {number} [stampMs] 采样时刻(毫秒); 缺省用当前时间
 * @returns {void}
 */
export function push(channel, sample, stampMs) {
  if (!Number.isFinite(sample)) return
  const now = Number.isFinite(stampMs) ? stampMs : performance.now()

  if (channel.lastStamp > 0) {
    const gap = (now - channel.lastStamp) / 1000
    // 只接受合理区间内的间隔, 避免页面切后台再回来时的超长间隔污染周期估计
    if (gap > 0.02 && gap < 10) {
      channel.period = channel.period * 0.7 + gap * 0.3
    }
  }
  channel.lastStamp = now

  channel.target = sample
  if (!channel.initialized) {
    // 首帧直接就位, 不要从 0 慢慢爬到实际位置
    channel.value = sample
    channel.initialized = true
  }
}

/**
 * 功能: 按帧推进通道当前值.
 * @param {object} channel 通道状态
 * @param {number} delta 帧间隔(秒)
 * @param {number} [snapThreshold=0] 差值超过该阈值时直接跳过去(用于回零/急停等瞬移)
 * @returns {number} 推进后的当前值
 */
export function step(channel, delta, snapThreshold = 0) {
  if (!channel.initialized) return channel.value

  const diff = channel.target - channel.value
  if (diff === 0) return channel.value

  if (snapThreshold > 0 && Math.abs(diff) > snapThreshold) {
    channel.value = channel.target
    return channel.value
  }

  // 指数衰减: 经过 tau 秒后剩余误差衰减到 1/e. 取 tau = 采样周期 × 系数,
  // 保证"下一个采样到来时基本已经到位", 且与帧率无关.
  const tau = Math.max(channel.period * ARRIVE_FACTOR, 0.05)
  const alpha = 1 - Math.exp(-delta / tau)
  channel.value += diff * alpha

  // 收敛到足够近时直接吸附, 避免浮点尾数导致的无休止微小更新
  if (Math.abs(channel.target - channel.value) < 1e-6) channel.value = channel.target
  return channel.value
}

/**
 * 功能: 把一个值按线性映射钳制到区间内.
 * @param {number} value 输入值
 * @param {number} min 下限
 * @param {number} max 上限
 * @returns {number} 钳制结果
 */
export function clamp(value, min, max) {
  return value < min ? min : value > max ? max : value
}
