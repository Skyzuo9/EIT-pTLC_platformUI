/**
 * 功能: 实时链的挂与拆 —— TwinFeed + 绑定层 + 事件流, 挂在**已加载模型**的场景上.
 *
 * 与 twin/useTwinScene.js 的分工: 那个是"建场景 + 载模型 + 接实时"的一体化胶水, 供
 * 实时页整页使用; 这里只要实时那一半, 因为动作工作台的场景由外壳持有, 标定子页只是
 * 在它上面临时接一条实时链, 切走就拆掉。
 *
 * 分工原则(整个三维模块的性能关键)照旧:
 *   - 高频数据(轴位置/关节角/状态灯)走 TwinFeed + 帧回调, 全程普通对象, 不碰响应式;
 *   - 低频 UI 状态(连接状态/健康度)才用 ref, 并以 500 ms 固定节奏同步一次快照。
 */
import { onBeforeUnmount, ref, shallowRef } from 'vue'

import { EventStream } from '../twin/bindings/eventStream.js'
import { TwinFeed } from '../twin/bindings/TwinFeed.js'

/** 面板数据从 TwinFeed 同步到 Vue 的间隔(毫秒). 遥测本身 1 Hz, 无需更快 */
const UI_SYNC_INTERVAL_MS = 500

/**
 * 功能: 提供可挂拆的实时链.
 *
 * @param {object} options 参数对象
 * @param {import('vue').ShallowRef} options.manager SceneManager 的 shallowRef
 * @returns {object} { feed, connection, realtime, warnings, attached, attach, detach }
 */
export function useLiveBindings({ manager }) {
  const feed = shallowRef(/** @type {TwinFeed|null} */ (null))
  const attached = ref(false)
  const warnings = ref(/** @type {string[]} */ ([]))
  const connection = ref({ connected: false, lastError: '' })
  /** 高频实时源健康度; 独立于 WebSocket 是否连通, 避免"连着但数据已陈旧" */
  const realtime = ref({
    robot: { available: false, stale: true, resynced: false },
    axes: { known: 0, total: 0, stale: 0, resynced: [] },
    mechanisms: { known: 0, total: 0, stale: 0, estimated: 0, resynced: [] },
    materials: { available: false, stale: true, snapshot: null },
  })

  let stream = null
  let unsubscribeEvents = null
  let unsubscribeStatus = null
  let syncTimer = 0

  /**
   * 功能: 把 TwinFeed 的低频信息同步到 Vue 响应式状态.
   * @returns {void}
   */
  function syncUi() {
    const current = feed.value
    if (!current) return
    realtime.value = current.realtimeStatus()
  }

  /**
   * 功能: 在既有场景上接一条实时链(幂等).
   * @param {object} manifest device-manifest
   * @returns {void}
   */
  function attach(manifest) {
    const instance = manager.value
    if (!instance || !manifest || attached.value === true) return

    const twinFeed = new TwinFeed(manifest)
    feed.value = twinFeed

    // picking:false —— 标定不需要工位悬停/点选, 省掉 BVH 拾取与误触的外壳透视
    const bindResult = instance.attachBindings(manifest, twinFeed, {}, { picking: false })
    warnings.value = bindResult.missing.length
      ? [`模型中缺少 ${bindResult.missing.length} 个 manifest 声明的节点: ${bindResult.missing.slice(0, 5).join(', ')}`]
      : []

    stream = new EventStream()
    unsubscribeEvents = stream.onEvent((event) => twinFeed.handleEvent(event))
    unsubscribeStatus = stream.onStatus((state) => {
      twinFeed.setTransportState(state.connected)
      connection.value = { ...state }
      syncUi()
    })

    syncTimer = window.setInterval(syncUi, UI_SYNC_INTERVAL_MS)
    syncUi()
    attached.value = true
  }

  /**
   * 功能: 拆掉实时链, 保留模型(幂等).
   *
   * 必须先 clearHolds: 接管中的轴若带着 hold 离场, 下次接回来 feed 仍写不进去,
   * 表现是"三维不跟实机动"却毫无报错。
   * @returns {void}
   */
  function detach() {
    if (attached.value === false) return
    manager.value?.bindings?.clearHolds?.()
    clearInterval(syncTimer)
    syncTimer = 0
    unsubscribeEvents?.()
    unsubscribeEvents = null
    unsubscribeStatus?.()
    unsubscribeStatus = null
    stream?.dispose()
    stream = null
    manager.value?.detachBindings()
    feed.value = null
    connection.value = { connected: false, lastError: '' }
    warnings.value = []
    attached.value = false
  }

  onBeforeUnmount(detach)

  return { feed, connection, realtime, warnings, attached, attach, detach }
}
