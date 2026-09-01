/**
 * 功能: 把命令式的三维场景接入 Vue 组件生命周期的胶水层.
 *
 * 分工原则(整个三维模块的性能关键):
 *   - 高频数据(轴位置、关节角、状态灯)走 TwinFeed + SceneManager 的帧回调,
 *     全程是普通对象, 不碰 Vue 响应式;
 *   - 低频 UI 状态(加载进度、选中工位、面板字段、连接状态)才用 ref 暴露给模板,
 *     并以固定节奏(每 500 ms)从 TwinFeed 同步一次快照, 而不是每帧同步.
 * 若把每帧变化的数据塞进 ref, Vue 的依赖追踪会在 60 fps 下产生大量无谓开销.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'

import { EventStream } from './bindings/eventStream.js'
import { TwinFeed } from './bindings/TwinFeed.js'
import { loadManifest, manifestSummary, stationById } from './manifest.js'
import { createIntroReveal } from './scene/IntroReveal.js'
import { SceneManager } from './scene/SceneManager.js'

/** 面板数据从 TwinFeed 同步到 Vue 的间隔(毫秒). 遥测本身 1 Hz, 无需更快 */
const UI_SYNC_INTERVAL_MS = 500
/** 板位置账本的轮询周期(ms)。位置是低频持久化数据(段完成才变), 不需要更快。 */
const PLATE_LEDGER_INTERVAL_MS = 3000
/**
 * 回放播放头单帧最大推进量(秒)。
 *
 * 渲染慢(软件渲染/切后台标签页)时墙钟差可能有好几秒, 不钳住的话播放头一步跨到
 * 录像末尾, 表现成"点了播放却什么都没发生"; 同时泵/液位这些按 delta 积分的模型
 * 也会越过事件流。宁可播得比实时慢, 不能让时间乱跳。
 */
const MAX_REPLAY_STEP_S = 0.25
/** 开场动画"每浏览器会话只自动播第一次"的 sessionStorage 门槛键 */
const INTRO_SEEN_KEY = 'ptlc.twin.introPlayed.v1'

/**
 * 功能: 在组件挂载时创建三维场景、加载模型与 manifest、接入实时事件流, 卸载时彻底释放.
 *
 * @param {object} options 参数对象
 * @param {import('vue').Ref<HTMLElement|null>} options.containerRef 画布容器的模板引用
 * @param {string} options.modelUrl 整机 GLB 地址
 * @param {string} [options.manifestUrl] device-manifest 地址
 * @param {string} [options.quality='high'] 初始画质档位
 * @param {boolean} [options.live=true] 是否接入实时事件流
 * @param {Function} [options.streamFactory] () => EventStream 兼容对象; 缺省 = 宿主单例
 *   事件流。仿真页传 simEventStream 工厂以换独立数据源, 渲染链一行不动。
 * @param {string} [options.plateLedgerUrl] 板位置账本轮询端点; 仿真页必须换成沙盒端点,
 *   否则仿真页板层会被**真机**调度账本驱动。
 * @returns {object} 供模板使用的响应式状态与操作函数
 */
export function useTwinScene({
  containerRef,
  modelUrl,
  manifestUrl = '/api/3d/assets/models/device-manifest.json',
  quality = 'high',
  live = true,
  stationPicking = true,
  plates = false,
  streamFactory = null,
  plateLedgerUrl = '/api/scheduler/snapshot',
  // 下面两个的缺省值就是从前写死的那两条 URL —— live 逐字零变化。
  // 传 null 表示"这条链在本页不存在", 整条不装而不是装了再降级。
  feedliftCalibUrl = '/api/feedlift/calib',
  plateTraceBase = '/api/3d/plate-traces',
  // 回放: 传入 DVR 传输层即进入录像回放模式。两个参数必须成对给 —— feedClock 决定
  // 下游全部 staleness/插值判定的"现在", replayChannel 负责按播放头投喂与清场。
  feedClock = null,
  replayChannel = null,
}) {
  // shallowRef: 这些对象内部有庞大的 three 对象图, 绝不能被 Vue 深度代理
  const manager = shallowRef(/** @type {SceneManager|null} */ (null))
  const feed = shallowRef(/** @type {TwinFeed|null} */ (null))
  const manifest = shallowRef(/** @type {object|null} */ (null))
  /** 事件流实例; 时间线组件需要直接订阅它以获取步骤事件 */
  const eventStream = shallowRef(/** @type {EventStream|null} */ (null))

  const loading = ref(true)
  const progress = ref(0)
  const error = ref('')
  const warnings = ref(/** @type {string[]} */ ([]))
  const stats = ref({ fps: 0, quality, drawCalls: 0, triangles: 0 })
  const modelInfo = ref(/** @type {object|null} */ (null))
  const summary = ref(/** @type {object|null} */ (null))

  const connection = ref({ connected: false, lastError: '' })
  /** 高频实时源健康度；独立于 WebSocket 是否连通，避免“连着但数据已陈旧”。 */
  const realtime = ref({
    robot: { available: false, stale: true, resynced: false },
    axes: { known: 0, total: 0, stale: 0, resynced: [] },
    mechanisms: { known: 0, total: 0, stale: 0, estimated: 0, resynced: [] },
    materials: { available: false, stale: true, snapshot: null },
  })
  /** 上位机 MaterialStore.grid 的只读投影。 */
  const materials = ref(/** @type {object|null} */ (null))
  const hoveredStation = ref(/** @type {string|null} */ (null))
  const selectedStation = ref(/** @type {string|null} */ (null))
  /**
   * 能"特写"(相机飞入)的工位 id 集合 —— 判据是 glbNode **真的**解进了
   * bindings.stationRoots, 而不是 manifest 里的 hasGeometry(两份产物里 13 个工位
   * 全是 true, 判不出任何东西)。manifest 与 GLB 对不上时那个工位会落进
   * bindResult.missing, 这里就不会出现, UI 于是不去提供一个点了没反应的按钮。
   */
  const focusableStations = ref(/** @type {Set<string>} */ (new Set()))
  /** 工位健康度快照; 每 500 ms 从 TwinFeed 同步一次 */
  const stationHealth = ref(/** @type {Record<string, string>} */ ({}))
  /** 展缸状态码快照 */
  const tankStates = ref(/** @type {number[]} */ ([]))
  /** 展缸液体体积快照(mL, 真实值不含观感放大); 与 tankStates 同走 500 ms 低频桥 */
  const tankVolumesMl = ref(/** @type {number[]} */ ([]))
  /** 溶液槽容积等换算参数, 供面板画液位条(manifest.tankLiquid.cavity) */
  const tankCapacityMl = ref(0)
  /** 注射泵柱塞快照(mL / mm / 可信度); 与 tankVolumesMl 同走 500 ms 低频桥 */
  const pumpSyringes = ref(/** @type {object[]} */ ([]))
  /** 自动环绕开关状态(HUD 按钮高亮; 用户一动相机 SceneManager 会自停并回调同步) */
  const autoRotate = ref(false)
  /** 选中工位的遥测字段快照 */
  const selectedSnapshot = ref(/** @type {object|null} */ (null))

  let stream = null
  let unsubscribeEvents = null
  let unsubscribeStatus = null
  let syncTimer = 0
  let disposed = false
  let unsubscribePlateNodes = null
  let plateLedgerTimer = 0
  let unhookReplay = null
  let unsubscribeReplay = null

  /**
   * 功能: 拉调度器快照喂给板层的 L1 权威位置, 并取一次现场实测的料仓堆叠节距.
   *
   * 为什么走轮询而不是等 scheduler_update 事件: 三维页不一定挂载调度视图, 不能依赖
   * 那边的 store; 而板位置是低频持久化数据(段完成才变), 3 s 一拉完全够用, 也与
   * stores/scheduler.js 既有的兜底轮询同节奏。两个接口都是**只读**的。
   * @param {object} instance SceneManager
   * @returns {void}
   */
  /**
   * 功能: 让渲染循环驱动录像回放 —— 推进播放头、按需清场、把倍速交给场景.
   *
   * 清场顺序是本函数唯一的要害, 反了就静默出错:
   *   1. feed.resetForSeek()  丢弃机构的逐 id 时间戳闸门与位姿缓冲的到达时刻锁存,
   *      否则紧随其后的关键帧会被逐 id 悄悄跳过, 气缸/阀停在未来的状态上;
   *   2. machine.home()       它的源码注释原文就写着"是向后 seek 的唯一清场入口" ——
   *      顺带把关节解缠参考 controllerDeg 复位, 免得跨过 ±180° 的关节凭空转一整圈;
   *   3. plates._applied 清空 关键帧改了板位却不重绘, 就是它在短路;
   *   4. 最后才应用标量快照(没有任何事件能置位的那些锁存)。
   *
   * 清场与播种落在同一帧是**结构保证**而不是巧合: replayChannel 直到快照到手才自增
   * resetToken, 所以本钩子看到新 token 时 pendingSeed 必然已就绪。
   *
   * @param {SceneManager} instance 场景
   * @param {TwinFeed} twinFeed 数据通道
   */
  function startReplayDriving(instance, twinFeed) {
    let appliedToken = -1
    let lastWallMs = 0
    unhookReplay = instance.addFrameHook(() => {
      if (appliedToken !== replayChannel.resetToken) {
        appliedToken = replayChannel.resetToken
        // seek 期间的加载耗时不算进播放时间, 否则跳完就往前窜一大截
        lastWallMs = 0
        twinFeed.resetForSeek()
        instance.bindings?.machine?.home?.()
        // 插值通道标回未初始化 —— interp 只在首帧直接就位, 之后一律缓动, 而清场路径
        // 从没解除过 initialized。不做这一步, 每次跳转姿态要 ~1.25 s 才收敛: 单击时
        // 读作"平滑落位", 拖动时就是永远追不上手指。
        instance.bindings?.snapInterp?.()
        // 板与托盘的持握/归属是**事件历史算出来的派生态**, 关键帧里没有。擦洗预览
        // 刻意不重建它(那要多打一个 /history), 所以预览时也绝不能拆 —— 拆了就没人
        // 装回去, 表现是每拖一下板全部退回料仓再由账本摆回去, 一秒十几次的频闪。
        // 不拆也不会说谎: 关键帧带的 material_state 照样把板位重新投一遍。
        if (!replayChannel.previewing) {
          instance.plates?.resetForSeek?.()
          instance.trays?.resetForSeek?.()
        }
        if (instance.bindings?.signalLight) instance.bindings.signalLight.lastKey = null
      }
      // 种子必须与本次清场配对, 且落在**同一帧**里 —— 见 replayChannel.seek 的注释:
      // 让 seek 自己 _emit 的话, 顺序取决于"网络比一帧快还是慢", 是掷硬币。
      const seed = replayChannel.pendingSeed
      if (seed && seed.token === appliedToken) {
        for (const event of seed.events) twinFeed.handleEvent(event)
        if (seed.scalars) twinFeed.applySnapshot(seed.scalars)
        replayChannel.pendingSeed = null
      }
      // 播放头按**墙钟**推进, 不用帧回调给的 delta。
      //
      // 两条理由, 都是实测踩出来的:
      // 1) 帧回调的 delta 已被 SceneManager 乘过 timeScale, 反除回去会累积误差;
      // 2) 更要命的是它与帧率绑死。软件渲染(无 GPU 的验收环境)下整机场景可能跌到
      //    1 fps 以下, 单帧 delta 能有好几秒 —— 播放头会一步跨到录像末尾然后停住,
      //    表现成"点了播放却什么都没发生"。切后台标签页回来是同一个病。
      // 因此这里自己量墙钟, 并把单步钳住: 渲染慢就少画几帧, 而不是让时间乱跳。
      const nowMs = performance.now()
      const wall = lastWallMs ? Math.min((nowMs - lastWallMs) / 1000, MAX_REPLAY_STEP_S) : 0
      const beforeHead = replayChannel.clock.playhead
      lastWallMs = nowMs
      replayChannel.tick(wall)
      // 擦洗时 timeScale 既不能是 1(泵/液位这些按 delta 积分的模型会与事件流脱节,
      // 就是 SceneManager 注释警告的撕裂)也不能是 0(interp 停摆, 姿态永远收敛不到
      // 播种值)。effectiveRate 把这个夹逼关进纯函数并有单测钉着。
      instance.timeScale = replayChannel.effectiveRate(
        replayChannel.clock.playhead - beforeHead, wall)
    })
  }

  function startPlateLedgerPolling(instance) {
    const pullLedger = async () => {
      // 回放中绝不拉实时账本: 它会用**当下**的板位覆盖历史板位
      if (replayChannel?.active) return
      try {
        const res = await fetch(plateLedgerUrl)
        if (!res.ok) return
        const payload = await res.json()
        instance.plates?.pushLedger(payload)
        // 沙盒的板位投影顺带带出板堆节距(它读的是**同一份** feedlift_calib.json,
        // 不是第二个数) —— 于是仿真页不必再去打真机的标定端点
        for (const row of payload?.magazines || []) {
          const pitch = Number(row?.pitch_mm) || 0
          if (row?.magazine) instance.setPlateStackPitch(String(row.magazine), pitch / 1000)
        }
      } catch {
        /* 拉不到就保持末态 —— 板绝不回零, 与断流冻结同义 */
      }
    }
    const pullPitch = async () => {
      if (!feedliftCalibUrl) return
      try {
        const res = await fetch(feedliftCalibUrl)
        if (!res.ok) return
        const calib = await res.json()
        for (const id of ['feed', 'waste']) {
          // 出厂是 0(未标定), 此时板层自己回退到"玻璃 + 硅胶"总厚
          instance.setPlateStackPitch(id, (Number(calib?.[id]?.pitch_mm) || 0) / 1000)
        }
      } catch {
        /* 标定读不到就用名义厚度, 不影响搬运 */
      }
    }
    // 板面痕迹的标定与取数: 映射来自 motion-map(编译器导出, 与演示片段同源),
    // 端点毫米与实际刀路走后端只读路由。任一路取不到 → 对应痕迹留白, 不影响位置投影。
    const pullTraceConfig = async () => {
      if (!plateTraceBase) return
      try {
        const [mapRes, cfgRes] = await Promise.all([
          fetch('/api/3d/assets/generated/action-motion-map.json'),
          fetch(`${plateTraceBase}/config`),
        ])
        if (!mapRes.ok || !cfgRes.ok) return
        const motionMap = await mapRes.json()
        const config = await cfgRes.json()
        const pose = config?.spotPose
        instance.plates?.setTraceConfig({
          calib: motionMap?.spotBandCalib || null,
          pose: pose
            ? {
              xStartMm: Number(pose.x_start),
              xEndMm: Number(pose.x_end),
              yHeightMm: Number(pose.y_height),
            }
            : null,
          wetFrontTargetCm: Number(motionMap?.wetFrontTargetCm) || 0,
        })
      } catch {
        /* 配置读不到就留白 —— 板位置照常, 只是没有痕迹外观 */
      }
    }
    // 痕迹取数按样品号打后端。仿真页传 plateTraceBase=null 整条不装:
    // 那里的 sample_id 是投影按位置合成的, 打过去必然 404; 且 spotPose 来自真机点表,
    // 画出来的痕迹既无数据也无意义 —— 不装是减法, 不是降级。
    if (plateTraceBase) {
      instance.plates?.setTraceProvider(async (sampleId) => {
        const res = await fetch(`${plateTraceBase}/${encodeURIComponent(sampleId)}`)
        if (!res.ok) return null
        return res.json()
      })
    }
    pullPitch()
    pullTraceConfig()
    pullLedger()
    plateLedgerTimer = window.setInterval(pullLedger, PLATE_LEDGER_INTERVAL_MS)
  }

  /**
   * 功能: 把 TwinFeed 的低频信息同步到 Vue 响应式状态.
   * @returns {void}
   */
  function syncUi() {
    const currentFeed = feed.value
    const currentManifest = manifest.value
    if (!currentFeed || !currentManifest) return

    const health = {}
    for (const station of currentManifest.stations || []) {
      health[station.id] = currentFeed.healthOf(station)
    }
    stationHealth.value = health
    tankStates.value = [...currentFeed.tankStates]
    tankVolumesMl.value = currentFeed.tankLiquid.snapshotMl()
    tankCapacityMl.value = currentFeed.tankLiquid.capacityMl
    pumpSyringes.value = currentFeed.pumpSyringe.snapshot()
    realtime.value = currentFeed.realtimeStatus()
    materials.value = realtime.value.materials

    const station = selectedStation.value
      ? stationById(currentManifest, selectedStation.value)
      : null
    selectedSnapshot.value =
      station?.nodeId ? currentFeed.snapshots[station.nodeId] || null : null
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
        autoDegrade: true,
        onStats: (next) => {
          stats.value = next
        },
      })
      manager.value = instance

      // 先取 manifest(小文件, 每次强刷), 再用其构建戳做模型 URL 的 cache-buster:
      // 只在真出新构建时失效大 GLB 的缓存. 曾因模型 URL 无 buster 出现"旧模型配
      // 新清单"(快换对接看着仍错位). 串行多等的一轮往返是本地几毫秒, 换正确性.
      const loadedManifest = await loadManifest(`${manifestUrl}?t=${Date.now()}`)
      if (disposed === true) return
      const result = await instance.loadMachineModel(
        `${modelUrl}?v=${loadedManifest.generatedAt ?? Date.now()}`,
        (fraction) => {
          progress.value = fraction
        },
      )
      if (disposed === true) return

      manifest.value = loadedManifest
      summary.value = manifestSummary(loadedManifest)
      modelInfo.value = {
        loadMs: result.loadMs,
        unit: result.unit,
        stats: result.stats,
        sizeM: result.box
          ? {
              radius: Number(result.box.radius.toFixed(2)),
              size: result.box.size
                ? [
                    Number(result.box.size.x.toFixed(2)),
                    Number(result.box.size.y.toFixed(2)),
                    Number(result.box.size.z.toFixed(2)),
                  ]
                : null,
            }
          : null,
      }

      const twinFeed = new TwinFeed(loadedManifest, { now: feedClock })
      feed.value = twinFeed
      if (import.meta.env.DEV) {
        // 开发期调试口: 控制台直接注入事件做纯前端冒烟, 如
        // __ptlcTwin.feed.handleEvent({type:'signal_light', red:true, yellow:false,
        //   green:false, ts: Date.now()/1000, seq: 1})
        // manager 供验收脚本读绑定层真值(如塔灯材质当前 emissive)
        window.__ptlcTwin = { feed: twinFeed, manager: instance }
      }

      const bindResult = instance.attachBindings(
        loadedManifest,
        twinFeed,
        {
          onHover: (id) => {
            hoveredStation.value = id
          },
          onSelect: (id) => {
            selectedStation.value = id
            syncUi()
          },
        },
        { picking: stationPicking, plates },
      )
      if (bindResult.missing.length) {
        warnings.value = [
          `模型中缺少 ${bindResult.missing.length} 个 manifest 声明的节点: ` +
            bindResult.missing.slice(0, 5).join(', '),
        ]
      }

      // 一次性低频快照(装配后工位根节点不再增减), 不进每帧通道
      focusableStations.value = new Set(instance.bindings?.stationRoots?.keys?.() || [])

      // 薄层板与在途托盘的搬运推断都吃**已配对好入参**的节点事件 —— vm_node_done 本身
      // 不带 args, 配对只在 TwinFeed 里做一次, 这里挂消费者取用, 不重建第二份 pending 表。
      // 托盘那一路只用来把挂载时刻提前到合爪那一帧(身份仍与 material_state 同源),
      // 因为在途行要等取料脚本 DONE 才落账, 而那时机械臂已经拎着托盘退回 home 了。
      if (instance.plates || instance.trays) unsubscribePlateNodes = twinFeed.addNodeSink(
        (event, args) => {
          instance.plates?.handleEvent(event, args)
          instance.trays?.handleEvent(event, args)
        },
      )

      if (replayChannel) {
        // 回放事件与实时事件走同一个 handleEvent —— 这正是"回放 1:1"的由来:
        // 下游 145 KB 绑定逻辑对数据来自哪里毫不知情。
        unsubscribeReplay = replayChannel.onEvent((event) => twinFeed.handleEvent(event))
      }

      if (live) {
        stream = streamFactory ? streamFactory() : new EventStream()
        eventStream.value = stream
        unsubscribeEvents = stream.onEvent((event) => {
          // 回放期间屏蔽实时事件: 否则今天的轴位会盖在历史画面上, 是"回放在说谎"
          // 里最难察觉的一种 —— 画面看着在动, 只是动的不是当时那台机器。
          if (replayChannel?.active) return
          twinFeed.handleEvent(event)
        })
        unsubscribeStatus = stream.onStatus((state) => {
          if (replayChannel?.active) return
          twinFeed.setTransportState(state.connected)
          if (!state.connected) {
            instance.plates?.markDisconnected()
            instance.trays?.markDisconnected()
          }
          connection.value = { ...state }
          syncUi()
        })
        if (instance.plates) startPlateLedgerPolling(instance)
      }

      if (replayChannel) startReplayDriving(instance, twinFeed)

      syncTimer = window.setInterval(syncUi, UI_SYNC_INTERVAL_MS)
      syncUi()

      // 开场动画: 必须在 attachBindings 之后装配(它快照的材质要是绑定层克隆后的
      // 最终材质); 每浏览器会话只自动播第一次, HUD「开场」钮可随时重播
      instance.intro = createIntroReveal(instance)
      instance.onAutoRotateChange = (on) => {
        autoRotate.value = on
      }
      if (!window.sessionStorage.getItem(INTRO_SEEN_KEY)) {
        window.sessionStorage.setItem(INTRO_SEEN_KEY, '1')
        instance.intro.play()
      }
    } catch (err) {
      if (disposed === true) return
      error.value = err?.message || String(err)
      console.error('[twin] 场景初始化失败', err)
    } finally {
      if (disposed === false) loading.value = false
    }
  })

  onBeforeUnmount(() => {
    disposed = true
    clearInterval(syncTimer)
    clearInterval(plateLedgerTimer)
    unhookReplay?.()
    unsubscribeReplay?.()
    unsubscribePlateNodes?.()
    unsubscribeEvents?.()
    unsubscribeStatus?.()
    stream?.dispose()
    manager.value?.intro?.dispose() // dispose 链里的 detachBindings 也会兜底, 这里显式对称
    manager.value?.dispose()
    manager.value = null
    feed.value = null
  })

  // 开发期热更新: Vite 替换模块时先释放旧上下文, 否则会累积出多个 WebGL 上下文
  if (import.meta.hot) {
    import.meta.hot.dispose(() => {
      clearInterval(syncTimer)
      stream?.dispose()
      manager.value?.dispose()
      manager.value = null
    })
  }

  /**
   * 功能: 切换画质档位.
   * @param {string} next 档位名(high/medium/low)
   * @returns {void}
   */
  function setQuality(next) {
    manager.value?.setQuality(next)
    stats.value = { ...stats.value, quality: next }
  }

  /**
   * 功能: 应用标准视角预设.
   * @param {string} name 预设名(iso/front/back/left/right/top)
   * @returns {void}
   */
  function applyPreset(name) {
    manager.value?.cameraRig.applyPreset(name, true)
  }

  /**
   * 功能: 选中某个工位(仅详情面板与柜内工位的外壳透视, 不移动相机; 想凑近看用双击飞入).
   * @param {string|null} stationId 工位 id
   * @returns {void}
   */
  function selectStation(stationId) {
    manager.value?.picker?.setSelected(stationId)
  }

  /**
   * 功能: 开关自动环绕(HUD「环绕」钮; 用户一动相机会被 SceneManager 自停并回调同步).
   * @returns {void}
   */
  function toggleAutoRotate() {
    const next = !autoRotate.value
    autoRotate.value = next
    manager.value?.setAutoRotate(next)
  }

  /** 功能: 重播开场动画(HUD「开场」钮; 无视会话门槛). */
  function replayIntro() {
    manager.value?.intro?.play()
  }

  return {
    manager,
    manifest,
    feed,
    eventStream,
    loading,
    progress,
    error,
    warnings,
    stats,
    modelInfo,
    summary,
    connection,
    realtime,
    materials,
    hoveredStation,
    selectedStation,
    focusableStations,
    stationHealth,
    tankStates,
    tankVolumesMl,
    tankCapacityMl,
    pumpSyringes,
    selectedSnapshot,
    autoRotate,
    setQuality,
    applyPreset,
    selectStation,
    toggleAutoRotate,
    replayIntro,
  }
}
