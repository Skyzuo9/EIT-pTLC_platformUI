/**
 * 功能: 动作工作台的场景生命周期 —— 建 SceneManager, 取 manifest, 载模型, 卸载彻底释放.
 *
 * 为什么单独一层: 运动模式/标定/演示三个子页共用同一份模型与 manifest, 只有驱动栈
 * 不同。场景建在外壳上、只加载一次, 切子页就只是挂拆驱动栈(毫秒级); 三个子页各建
 * 一个 SceneManager 的话每次切页都要重新解析 14 MB GLB。
 *
 * 两条纪律从 MotionView 原样继承, 都有事故背景:
 *   1. 先取 manifest(小文件, 每次强刷), 再用它的 generatedAt 做 GLB 的 cache-buster ——
 *      只在真出新构建时才失效大文件缓存。曾因模型 URL 无 buster 出现"旧模型配新清单",
 *      快换对接在浏览器里看着仍错位, 排查很久。
 *   2. 每个 await 之后都要 `if (state.disposed) return`。异步续段跑在已释放的
 *      SceneManager 上不会报错, 只会静默写进一棵被丢弃的对象图。
 */
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'

import { SceneManager } from '../twin/scene/SceneManager.js'

/**
 * 功能: 在组件挂载时建立三维场景并加载整机模型, 卸载时释放.
 *
 * @param {object} options 参数对象
 * @param {import('vue').Ref<HTMLElement|null>} options.containerRef 画布容器模板引用
 * @param {string} options.modelUrl 整机 GLB 地址
 * @param {string} options.manifestUrl device-manifest 地址
 * @param {string} [options.quality='high'] 初始画质档位
 * @param {(manifest: object) => void|Promise<void>} [options.onReady] 模型就绪回调
 * @returns {object} { manager, manifest, loading, progress, error, stats, state, swapModel, reloadManifest }
 */
export function useMotionScene({
  containerRef,
  modelUrl,
  manifestUrl,
  quality = 'high',
  onReady,
}) {
  // shallowRef: 内部是庞大的 three 对象图, 绝不能被 Vue 深度代理
  const manager = shallowRef(/** @type {SceneManager|null} */ (null))
  const manifest = shallowRef(/** @type {object|null} */ (null))

  const loading = ref(true)
  const progress = ref(0)
  const error = ref('')
  const stats = ref({})

  /** 卸载标志; 用对象包一层, 让子 composable 也能读到同一个引用 */
  const state = { disposed: false }

  /**
   * 功能: 取最新 manifest(强刷, 绕开缓存).
   * @returns {Promise<object>} manifest 文档
   */
  async function reloadManifest() {
    const response = await fetch(`${manifestUrl}?t=${Date.now()}`)
    if (!response.ok) throw new Error(`加载绑定契约失败: HTTP ${response.status}`)
    return await response.json()
  }

  /**
   * 功能: 换装另一份模型(指认模式进出用), 并同步 manifest.
   *
   * @param {string} url 目标 GLB 地址
   * @param {object} [options] 选项
   * @param {boolean} [options.freshManifest=false] 是否重取 manifest(重跑后必须)
   * @param {boolean} [options.bust=false] 是否强制绕开缓存(raw.glb 无构建戳可用)
   * @returns {Promise<object|null>} 当前 manifest; 已卸载时返回 null
   */
  async function swapModel(url, { freshManifest = false, bust = false } = {}) {
    const instance = manager.value
    if (!instance) return null
    let doc = manifest.value
    if (freshManifest === true) {
      doc = await reloadManifest()
      if (state.disposed === true) return null
      manifest.value = doc
    }
    const buster = bust === true ? `t=${Date.now()}` : `v=${doc?.generatedAt ?? Date.now()}`
    await instance.loadMachineModel(`${url}?${buster}`, (fraction) => {
      progress.value = fraction
    })
    return state.disposed === true ? null : doc
  }

  onMounted(async () => {
    if (!containerRef.value) {
      error.value = '画布容器未就绪'
      loading.value = false
      return
    }
    try {
      const instance = new SceneManager(containerRef.value, {
        quality,
        onStats: (next) => {
          stats.value = next
        },
      })
      manager.value = instance

      const doc = await reloadManifest()
      if (state.disposed === true) return
      manifest.value = doc

      await instance.loadMachineModel(`${modelUrl}?v=${doc.generatedAt ?? Date.now()}`, (fraction) => {
        progress.value = fraction
      })
      if (state.disposed === true) return

      await onReady?.(doc)
    } catch (err) {
      if (state.disposed === true) return
      error.value = err?.message || String(err)
      console.error('[motion] 场景初始化失败', err)
    } finally {
      if (state.disposed === false) loading.value = false
    }
  })

  onBeforeUnmount(() => {
    state.disposed = true
    manager.value?.dispose()
    manager.value = null
  })

  // 开发期热更新: Vite 替换模块前先释放, 否则会累积出多个 WebGL 上下文
  if (import.meta.hot) {
    import.meta.hot.dispose(() => {
      state.disposed = true
      manager.value?.dispose()
      manager.value = null
    })
  }

  return { manager, manifest, loading, progress, error, stats, state, swapModel, reloadManifest }
}
