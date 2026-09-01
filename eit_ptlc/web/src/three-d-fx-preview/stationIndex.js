/**
 * 功能: manifest.stations x 节点索引 -> 工位运行时模型(StationEntry).
 *
 * 这是悬浮卡/聚焦/隔离共同的唯一数据源. 坐标约定: manifest 的 bounds/camera 是
 * 管线生成时的模型系数值, 与运行时世界系有平移差 —— 一律对实际场景图现算.
 *
 * 第三轮定夺:
 *   - **地轨并入机械臂**: RAIL 不再单独成组, ROBOT 条目吃下 ST_RAIL 整棵网格
 *     (ST_ROBOT 本就嵌在 ST_RAIL/AXIS_AXIS_11Y/CARRIAGE 下), 但锚点仍取 ROBOT
 *     子树的动态顶部带 —— 机械臂沿地轨移动时卡片锚点跟着走; 聚焦包围盒 =
 *     地轨静态盒 ∪ 机械臂动态盒.
 *   - 管线重跑后新增的 VISION(视觉定位)工位自动进清单(无遥测, 悬停可发现).
 * 锚点算法: "顶部带加权中心"(anchorMath.js), 病根与订正见其头注释.
 */
import * as THREE from 'three'

import { topBandAnchor } from './fx/anchorMath.js'

const _box = new THREE.Box3()
const _tmpBox = new THREE.Box3()
const _inverse = new THREE.Matrix4()
const _probe = new THREE.Vector3()
const _probe2 = new THREE.Vector3()

/** 不参与卡片/聚焦的工位(整机外罩会把所有特效"罩"在里面) */
const EXCLUDED = new Set(['FRAME'])

/**
 * 功能: 收集一棵子树的全部网格.
 * @param {THREE.Object3D} root 根
 * @returns {THREE.Mesh[]} 网格数组
 */
function collectMeshes(root) {
  const meshes = []
  root.traverse((node) => {
    if (node.isMesh) meshes.push(node)
  })
  return meshes
}

/**
 * 功能: 在给定参照系里算一批网格的"顶部带锚点"(局部系).
 * @param {THREE.Mesh[]} meshes 网格
 * @param {THREE.Object3D} frame 参照对象(其局部系)
 * @param {number} band 顶部带比例
 * @returns {THREE.Vector3|null} 局部系锚点
 */
function localAnchorOf(meshes, frame, band) {
  _inverse.copy(frame.matrixWorld).invert()
  const boxes = []
  for (const mesh of meshes) {
    const b = new THREE.Box3().setFromObject(mesh, true)
    if (b.isEmpty()) continue
    b.applyMatrix4(_inverse)
    boxes.push({ min: [b.min.x, b.min.y, b.min.z], max: [b.max.x, b.max.y, b.max.z] })
  }
  const top = topBandAnchor(boxes, band)
  return top ? new THREE.Vector3(top.x, top.topY, top.z) : null
}

/**
 * 功能: 构建工位运行时模型.
 * @param {object} options 参数对象
 * @param {object} options.manifest device-manifest JSON
 * @param {Map<string, THREE.Object3D>} options.nodeIndex loadMachine 的节点索引
 * @param {object} [options.config] 运行配置(读 cards.anchorBand / cards.anchorNudge)
 * @returns {{stations: Map<string, object>, list: object[], meshToStation: Map<THREE.Mesh, string>}}
 */
export function buildStationIndex({ manifest, nodeIndex, config }) {
  /** @type {Map<string, object>} */
  const stations = new Map()
  /** @type {Map<THREE.Mesh, string>} 拾取/悬停用: 网格 -> 工位 id */
  const meshToStation = new Map()
  const band = config?.cards?.anchorBand ?? 0.28

  let order = 0
  for (const spec of manifest.stations || []) {
    if (EXCLUDED.has(spec.id) || !spec.glbNode) continue
    if (spec.id === 'RAIL') continue // 地轨并入机械臂组(用户定夺), 不单独成组

    const merged = spec.id === 'ROBOT' // 机械臂·地轨合并条目
    const object = nodeIndex.get(spec.glbNode) || nodeIndex.get(spec.glbNode.split('/').pop())
    if (!object) continue
    const meshRoot = merged ? (nodeIndex.get('ST_RAIL') || object) : object

    const meshes = collectMeshes(meshRoot)
    if (!meshes.length) continue
    for (const mesh of meshes) meshToStation.set(mesh, spec.id)

    // ROBOT(或任何骑在滑座下的节点)按动态处理; 其余工位静态求一次世界盒
    const isDynamic = spec.glbNode.includes('/CARRIAGE/')
    meshRoot.updateMatrixWorld(true)
    const staticBox = new THREE.Box3().setFromObject(meshRoot, true) // precise: 量化几何必须

    /** @type {THREE.Box3|null} 动态部分: 世界盒折回局部系(滑座纯平移, 往返无损) */
    let dynamicLocalBox = null
    if (isDynamic) {
      _inverse.copy(object.matrixWorld).invert()
      dynamicLocalBox = new THREE.Box3().setFromObject(object, true).applyMatrix4(_inverse)
    }

    // 锚点: 动态工位(机械臂)只用自己子树的网格在**自己局部系**算 —— 跟滑座走;
    // 静态工位用全部网格在工位根局部系算
    const anchorMeshes = isDynamic ? collectMeshes(object) : meshes
    const anchorFrame = object
    const anchorLocal = localAnchorOf(anchorMeshes, anchorFrame, band)
      || staticBox.getCenter(new THREE.Vector3()).setY(staticBox.max.y)
        .applyMatrix4(_inverse.copy(anchorFrame.matrixWorld).invert())

    const entry = {
      id: spec.id,
      label: merged ? '机械臂·地轨' : (spec.label || spec.id),
      nodeId: spec.nodeId || null,
      /** 合并组的第二遥测节点(阶段B接真实数据用) */
      secondaryNodeId: merged ? 'plc.rail' : null,
      hasTelemetry: !!spec.nodeId,
      glbNode: spec.glbNode,
      object,
      meshes,
      isDynamic,
      order,

      /**
       * 功能: 当前世界包围盒. 静态=缓存盒; 动态=静态盒(地轨等) ∪ 动件盒(机械臂随滑座).
       * @param {THREE.Box3} out 输出盒
       * @returns {THREE.Box3} out
       */
      getWorldBounds(out) {
        out.copy(staticBox)
        if (isDynamic && dynamicLocalBox) {
          _tmpBox.copy(dynamicLocalBox).applyMatrix4(object.matrixWorld)
          out.union(_tmpBox)
        }
        return out
      },

      /**
       * 功能: 卡片 3D 锚点 = 顶部带加权中心 + 抬高. 局部系锚点 x 当前 matrixWorld ——
       * 静态工位矩阵恒定, 动态工位(机械臂)自动跟滑座.
       * @param {THREE.Vector3} out 输出向量
       * @param {number} [lift=0.05] 抬高量(米)
       * @returns {THREE.Vector3} out
       */
      getAnchor(out, lift = 0.05) {
        out.copy(anchorLocal).applyMatrix4(object.matrixWorld)
        out.y += lift
        const nudge = config?.cards?.anchorNudge?.[spec.id]
        if (nudge) {
          out.x += nudge[0] || 0
          out.y += nudge[1] || 0
          out.z += nudge[2] || 0
        }
        return out
      },

      /**
       * 功能: 工位底面中心(滑座跟随取 x 用).
       * @param {THREE.Vector3} out 输出向量
       * @returns {THREE.Vector3} out
       */
      getGroundCenter(out) {
        this.getWorldBounds(_box).getCenter(out)
        out.y = _box.min.y
        return out
      },
    }
    stations.set(spec.id, entry)
    order += 1
  }

  return { stations, list: [...stations.values()], meshToStation }
}

/**
 * 功能: 探测地轨滑座的移动轴 —— 逐局部轴试探 100 局部单位(模型是毫米制, 即 0.1m),
 * 量 ROBOT 世界位移最大的那根轴. 不写死轴向: glTF 局部轴与世界轴的映射经了
 * Blender 重组, 猜错会让"搬运跟随"整个反向或不动, 试探一次一劳永逸.
 *
 * @param {Map<string, THREE.Object3D>} nodeIndex 节点索引
 * @returns {{node: THREE.Object3D, axis: 'x'|'y'|'z', worldDir: THREE.Vector3,
 *            worldPerUnit: number, home: number}|null} 探测结果(拿不到滑座返回 null)
 */
export function probeCarriage(nodeIndex) {
  const carriage = nodeIndex.get('ST_RAIL/AXIS_AXIS_11Y/CARRIAGE')
  const robot = nodeIndex.get('ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT')
  if (!carriage || !robot) return null

  const PROBE = 100 // 局部单位(mm), 折世界 0.1m
  let best = null
  robot.updateMatrixWorld(true)

  for (const axis of ['x', 'y', 'z']) {
    const original = carriage.position[axis]
    robot.getWorldPosition(_probe)
    carriage.position[axis] = original + PROBE
    carriage.updateMatrixWorld(true)
    robot.getWorldPosition(_probe2)
    carriage.position[axis] = original
    carriage.updateMatrixWorld(true)

    _probe2.sub(_probe)
    const len = _probe2.length()
    if (!best || len > best.worldPerUnit * PROBE) {
      best = {
        node: carriage,
        axis,
        worldDir: _probe2.clone().divideScalar(Math.max(len, 1e-9)),
        worldPerUnit: len / PROBE,
        home: original,
      }
    }
  }
  // 位移小于 1mm/单位说明这不是平移滑座, 跟随功能不可用
  if (!best || best.worldPerUnit <= 1e-5) return null
  // 顺带记下机械臂 home 位的世界 X: 搬运跟随的偏移基准.
  // (不能用工位包围盒中心 —— 地轨并入机械臂组后, 盒中心是整条地轨的中点)
  robot.getWorldPosition(_probe)
  best.robotHomeWorldX = _probe.x
  return best
}

/**
 * 功能: 搬运跟随 —— simFeed 处于 transfer 步时, 驱动滑座让机械臂沿 X 在起终点
 * 工位之间平滑移动. 既是画面生动性的来源, 也是"ROBOT 动态锚点"能被截图证明的前提.
 *
 * @param {object} options 参数对象
 * @param {object|null} options.carriage probeCarriage 的结果
 * @param {Map<string, object>} options.stations 工位表
 * @param {object} options.simFeed 模拟驱动器
 * @param {() => void} options.invalidateShadows 几何动了要重渲阴影
 * @returns {{update: () => void, setEnabled: (on: boolean) => void, reset: () => void}}
 */
export function createCarriageFollow({ carriage, stations, simFeed, invalidateShadows }) {
  let enabled = true
  const from = new THREE.Vector3()
  const to = new THREE.Vector3()

  // 世界 X 每局部单位的带符号增益(滑座沿机器长轴 X 走; |增益| 过小则禁用)
  const gainX = carriage ? carriage.worldDir.x * carriage.worldPerUnit : 0
  const usable = !!carriage && Math.abs(gainX) > 1e-5
  // 机械臂 home 位世界 X(probeCarriage 记录), 作为偏移基准
  const homeWorldX = carriage?.robotHomeWorldX ?? 0

  /** 缓入缓出 */
  const ease = (t) => t * t * (3 - 2 * t)

  return {
    update() {
      if (!usable || !enabled) return
      const step = simFeed.getCurrentStep?.()
      if (!step || step.kind !== 'transfer') return
      const a = stations.get(step.from)
      const b = stations.get(step.to)
      if (!a || !b) return
      a.getGroundCenter(from)
      b.getGroundCenter(to)
      const targetX = from.x + (to.x - from.x) * ease(Math.min(Math.max(step.progress, 0), 1))
      carriage.node.position[carriage.axis] = carriage.home + (targetX - homeWorldX) / gainX
      carriage.node.updateMatrixWorld(true)
      invalidateShadows()
    },
    setEnabled(on) {
      enabled = !!on
      if (!on) this.reset()
    },
    reset() {
      if (!usable) return
      carriage.node.position[carriage.axis] = carriage.home
      carriage.node.updateMatrixWorld(true)
      invalidateShadows()
    },
  }
}
