/**
 * 功能: 离线驱动栈的挂与拆 —— rig / 板舞台 / 语义 / 着色 / 拖拽 / 播放器 / 观察工具.
 *
 * 这一栈是"离线"的: 状态由片段播放器或人手写入, 不接实时链。运动模式子页、原子动作
 * 演示子页、流程演示页都用它; 标定子页用的是实时链(useLiveBindings), 两者互斥 ——
 * 同一条轴被 feed 和播放器同时写会互相覆盖。
 *
 * ⚠ 拆序不可改(每一步的理由见各行注释): 播放器先停时钟 → 拖拽控制器释放 canvas
 * 监听/指针捕获/cursor → 着色还原材质指针(必须趁模型还活着) → 板层(实例网格挂在
 * 模型子树上, 须早于换模) → rig → tools; 最后清描边与选中态。
 */
import { shallowRef } from 'vue'

import { ClipPlayer } from '../anim/ClipPlayer.js'
import { MachineRig } from '../anim/MachineRig.js'
import { PlateFaceLayer } from '../twin/scene/plates/PlateFaceLayer.js'
import { PlateStage } from '../twin/scene/plates/PlateStage.js'
import { ViewTools } from '../twin/scene/ViewTools.js'
import { AxisDragController } from './AxisDragController.js'
import { MotionPaint } from './MotionPaint.js'
import { classifySemantics, markAxisResolveFailures } from './motionSemantics.js'

/**
 * 功能: 建立可挂拆的离线驱动栈.
 *
 * @param {object} options 参数对象
 * @param {import('vue').ShallowRef} options.manager SceneManager 的 shallowRef
 * @param {(text: string) => void} options.notify 面向用户的提示回调
 * @param {() => void} options.onValueChange 驱动层值变化回调(宿主的重算扳机)
 * @param {(state: object|null) => void} [options.onDrag] 拖拽 HUD 回调
 * @param {(state: object) => void} [options.onTransport] 传输条状态回调
 * @returns {object} 栈引用与 attach/detach
 */
export function useMotionStack({ manager, notify, onValueChange, onDrag, onTransport }) {
  const rig = shallowRef(/** @type {MachineRig|null} */ (null))
  const player = shallowRef(/** @type {ClipPlayer|null} */ (null))
  const paint = shallowRef(/** @type {MotionPaint|null} */ (null))
  const dragger = shallowRef(/** @type {AxisDragController|null} */ (null))
  const tools = shallowRef(/** @type {ViewTools|null} */ (null))
  /** 运动语义条目(manifest 加载后固定) */
  const semantics = shallowRef(/** @type {Array} */ ([]))

  /** 非响应式引用: three 对象图 */
  let plateLayer = null
  let plateStage = null
  let unhookFrame = null
  /** 从显示面板的板设置里注销(切页/换模时必须调, 否则面板会写进已 dispose 的层) */
  let unregisterPlates = null

  /**
   * 功能: 建薄层板舞台并交给 rig.
   *
   * 板锚点解析不到时**不静默**: 缸/座位少一处, 该处的板就不会出现, 而画面照样"看着
   * 很真" —— 必须让人看见少了哪个落点。
   * @param {object} manifest device-manifest
   * @returns {void}
   */
  function setupPlateStage(manifest) {
    const instance = manager.value
    let glassSource = null
    for (const node of instance.nodeIndex.values()) {
      const name = node?.userData?.origName || node?.name || ''
      if (name.startsWith('玻璃-') && node.isMesh && node.material) {
        glassSource = node.material
        break
      }
    }
    plateLayer = new PlateFaceLayer({ glassSource })
    plateStage = new PlateStage({
      manifest,
      nodeIndex: instance.nodeIndex,
      layer: plateLayer,
      root: instance.machineRoot,                   // 接触判据的可碰几何来源
    })
    rig.value?.setPlateStage(plateStage)
    // 登记进显示面板的板设置(硅胶厚度 / 吸盘柔性开关) —— 面板只有一个, 两条链共用
    unregisterPlates?.()
    unregisterPlates = instance.registerPlateConsumer?.({ layer: plateLayer, stage: plateStage })
    if (plateStage.missing.length) {
      notify(`板落点未解析: ${plateStage.missing.slice(0, 4).join(', ')}(这些位置不会出现板)`)
    }
  }

  /**
   * 功能: 建立离线驱动栈的全部配套件.
   * @param {object} manifest device-manifest
   * @returns {Map<string, string>} 各轴已固化运动方向的快照(判 dirty 基准)
   */
  function attach(manifest) {
    const instance = manager.value
    rig.value = new MachineRig({ manager: instance, manifest })
    if (rig.value.missing.length) {
      notify(`部分可动件未解析: ${rig.value.missing.slice(0, 4).join(', ')}`)
    }

    // 薄层板舞台: 流程片段里的 `plate` 原语落到这里, 让虚拟板在合适的位置出现并跟手。
    setupPlateStage(manifest)

    // 已固化运动方向快照: 每次 rig 重建都按当下 manifest 重置
    const axisDirSaved = new Map()
    for (const [axisId, entry] of rig.value.axes) {
      axisDirSaved.set(
        axisId,
        JSON.stringify({ axis: entry.spec.axis || [1, 0, 0], sign: Number(entry.spec.sign ?? 1) }),
      )
    }

    // 语义分类 + 解析失败防回归标记(manifest 说 rigged 但驱动层没解析到 → 亮红徽章)
    semantics.value = markAxisResolveFailures(
      classifySemantics(manifest),
      new Set(rig.value.axes.keys()),
    )
    paint.value = new MotionPaint({
      manager: instance,
      resolve: (path) => rig.value?._resolve(path),
    })
    dragger.value = new AxisDragController({
      manager: instance,
      rig: rig.value,
      onDrag: (dragState) => {
        onDrag?.(dragState)
        onValueChange()
      },
    })

    player.value = new ClipPlayer({
      rig: rig.value,
      cameraRig: instance.cameraRig,
      manifest,
      onChange: (transportState) => onTransport?.(transportState),
    })

    let lastClipTime = -1
    let lastBloomKey = ''
    unhookFrame = instance.addFrameHook((delta) => {
      const active = player.value
      active?.tick(delta)
      // ⚠ 必须排在 tick 之后: 接触判据要读这一帧刚写好的 transform。
      // 放在同一个钩子体里而不是另注册一个, 是因为 addFrameHook 没有优先级 ——
      // 靠注册顺序保证"排在后面"太脆(measureShadows 会在运行期往数组尾部插钩子)。
      plateStage?.update()
      // 播放或拖动进度都会改 time -> 机构在动, 阴影逐帧重渲; 停住后回到零开销
      const time = active ? active.time : -1
      if (active && (active.playing || time !== lastClipTime)) instance.invalidateShadows()
      lastClipTime = time

      // 亮着的工艺灯才进辉光选集。只在"哪几盏亮着"这个集合变化时才重设 ——
      // Selection.set 每帧调一次是白费, 而且灭着的灯进选集只是多跑一次全屏 pass。
      const lit = rig.value?.bloomLights?.() || []
      const key = lit.map((mesh) => mesh.uuid).join('|')
      if (key !== lastBloomKey) {
        lastBloomKey = key
        instance.effects?.setBloomTargets(lit)
      }
    })
    tools.value = new ViewTools(instance)
    return axisDirSaved
  }

  /**
   * 功能: 拆掉离线驱动栈(幂等; 换模前必须调).
   * @returns {void}
   */
  function detach() {
    unhookFrame?.()
    unhookFrame = null
    unregisterPlates?.()
    unregisterPlates = null
    player.value?.dispose()
    player.value = null
    plateStage?.dispose()
    plateStage = null
    plateLayer?.dispose()
    plateLayer = null
    rig.value?.setPlateStage(null)
    dragger.value?.dispose()
    dragger.value = null
    paint.value?.dispose()
    paint.value = null
    rig.value?.dispose?.()
    rig.value = null
    tools.value?.dispose()
    tools.value = null
    manager.value?.effects?.setSelected([])
    manager.value?.effects?.setHover([])
    semantics.value = []
  }

  return {
    rig,
    player,
    paint,
    dragger,
    tools,
    semantics,
    attach,
    detach,
    /** 板舞台状态(验收钩子用) */
    plateStatus: () => plateStage?.status() || null,
    /** 单独跑一次接触判据 —— 只给验收脚本量每帧开销用, 正常路径由帧钩子调。 */
    plateContactTick: () => plateStage?.update() || null,
    // 当帧手上那块板与整机静止几何的全向相交(见 PlateContact.overlap)。
    // 与 plateStatus().contact 不是一回事: 那个只沿吸盘轴看, 面内/斜向相交它看不见。
    plateOverlap: () => plateStage?.overlap() || null,
    /**
     * 某块板在场景图上的**局部**位姿与父节点名(验收用, 见 devHooks.plateLocal)。
     *
     * 为什么不能靠 nodesWorldMatching / nodeWorld 顶替: 板是 PlateFaceLayer 运行期造出来
     * 的, 不在 loadModel 建的节点索引里, `_resolve` 找不到它。而持板判据恰恰要看局部
     * 位姿 —— 那里 plateGrip 是刀具常量, 与机械臂姿态无关, 世界坐标比不了。
     */
    plateLocal: (plateId) => {
      const root = plateLayer?.get(plateId)?.root
      if (!root) return null
      return {
        parent: root.parent?.name || null,
        position: root.position.toArray(),
        quaternion: root.quaternion.toArray(),
      }
    },
    plateLayerRef: () => plateLayer,
  }
}
