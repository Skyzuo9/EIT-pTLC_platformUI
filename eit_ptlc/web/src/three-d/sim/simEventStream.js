/**
 * 功能: 组装仿真页的 EventStream —— 独立 WS 通道 + 沙盒快照播种.
 *
 * 复用 twin/bindings/eventStream.js 的多订阅者适配层 (transport/seeder 注入口),
 * TwinFeed/TwinBindings 渲染链因此一行不动; dispose 时顺带停掉沙盒 WS 通道
 * (宿主单例常驻, 沙盒通道必须随页面走)。
 */
import { EventStream } from '../twin/bindings/eventStream.js'
import { createSimChannel } from './simChannel.js'
import { simApi as defaultApi, simEventsWsUrl } from './simApi.js'

/**
 * 功能: 建一条沙盒事件流.
 * @param {object} [options]
 * @param {object} [options.channel] 注入通道替身 (离线单测)
 * @param {object} [options.api] 注入沙盒 API 替身
 * @returns {EventStream} 带 dispose 收口的事件流
 */
export function createSimEventStream({ channel = null, api = defaultApi } = {}) {
  const simChannel = channel || createSimChannel({ url: simEventsWsUrl() })

  const stream = new EventStream({
    transport: simChannel,
    // 连接沿播种: WS 自身会发 ready+物料快照, 这里补拉一次全量状态供诊断;
    // axis_pose/mechanism_state 由沙盒 20Hz 反馈循环持续供给, 无需快照播种。
    seeder: async ({ reportError }) => {
      try {
        await api.sessionStatus()
      } catch (error) {
        reportError(`沙盒状态读取失败: ${error?.message || error}`)
      }
    },
  })

  const dispose = stream.dispose.bind(stream)
  stream.dispose = () => {
    dispose()
    simChannel.stop()
  }
  simChannel.start()
  return stream
}
