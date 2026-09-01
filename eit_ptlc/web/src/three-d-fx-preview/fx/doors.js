/**
 * 功能: 开关门动画(全机 8 扇合页门) —— 点哪扇开哪扇, 再点关上; 对开门点一扇两扇同开.
 *
 * 铰链边与开向是**几何事实不是口味**, 取值出处见 fxConfig.doors 的注释(CAD 合页件
 * AKQ41-G-Z-6065 定铰链边, 把手 XAD51-A100 永远在对边). 门体要能单独转, 前提是它在
 * material_semantics.yaml 的 part_isolate 里 —— 否则会被并进静态块, 整块只能一起动.
 *
 * 铰链枢轴: 门 mesh 的 origin 在板中心(直接转会绕中线翻), 因此每扇门插一对
 * 双层 Group —— align(位=铰链竖边中点折算父局部系, 姿=父世界旋转的逆 → 局部 Y
 * 轴对齐世界竖直) + hinge(动画只写 hinge.rotation.y), 门节点 attach() 进 hinge
 * 保世界位姿. attach 只重挂父子: mesh 引用不变, nodeIndex/BVH/isolation.traverse/
 * meshToStation 全部无感(已核).
 *
 * 上料门 = 钣金框 + 内嵌亚克力窗两件(nodes 逗号分隔), 同挂一个 hinge 刚性同转.
 * 门属 ST_FRAME(非工位): 点击优先分派在 focus.onPointerUp 里(查 doorOfMesh);
 * 悬停只切 cursor 不出白卡. 聚焦幽灵态下门仍可点(visible 恒真); hide 模式点不到
 * (环境整体剥离, 语义自洽, 不做特例).
 */
import * as THREE from 'three'

const DEG = Math.PI / 180

const _unionBox = new THREE.Box3()
const _nodeBox = new THREE.Box3()
const _hingeWorld = new THREE.Vector3()
const _q = new THREE.Quaternion()

/**
 * 功能: 铰链竖边中点 —— 指定轴取盒极值, 另一水平轴与 y 取盒中心. 纯函数(有单测).
 * @param {{min: {x,y,z}, max: {x,y,z}}} box 门体世界包围盒(THREE.Box3 或同形普通对象)
 * @param {'minX'|'maxX'|'minZ'|'maxZ'} edge 铰链边
 * @returns {{x: number, y: number, z: number}} 铰链点
 */
export function hingePoint(box, edge) {
  const cx = (box.min.x + box.max.x) / 2
  const cy = (box.min.y + box.max.y) / 2
  const cz = (box.min.z + box.max.z) / 2
  if (edge === 'minX') return { x: box.min.x, y: cy, z: cz }
  if (edge === 'maxX') return { x: box.max.x, y: cy, z: cz }
  if (edge === 'minZ') return { x: cx, y: cy, z: box.min.z }
  if (edge === 'maxZ') return { x: cx, y: cy, z: box.max.z }
  return { x: cx, y: cy, z: cz }
}

/**
 * 功能: 开合插值的缓动(推门的起停感, 开/关对称复用). 纯函数(有单测).
 * @param {number} t 0..1
 * @returns {number} 0..1
 */
export function easeInOutSine(t) {
  return -(Math.cos(Math.PI * Math.min(Math.max(t, 0), 1)) - 1) / 2
}

/**
 * 功能: 创建门模块.
 * @param {object} ctx 沙盒上下文
 * @param {object} [deps] { cards } —— 读 cards.hoveredMesh() 切 cursor
 * @returns {object} 特效实例(另暴露 toggleDoor/setDoor/doorOfMesh/doorStates)
 */
export function createDoors(ctx, deps = {}) {
  const cfg = ctx.config.doors

  /** @type {Map<string, object>} 门名 -> 状态 */
  const doors = new Map()
  /** @type {Map<object, string>} 门体 mesh -> 门名(点击/悬停分派用) */
  const meshToDoor = new Map()

  ctx.machineRoot.updateWorldMatrix(true, true) // 装配期可能尚未渲染过, 先刷世界矩阵

  for (const [name, def] of Object.entries(cfg)) {
    if (!def || typeof def !== 'object') continue // 跳过 animS 等标量
    const paths = String(def.nodes).split(',').map((s) => s.trim()).filter(Boolean)
    const nodes = paths.map((p) => ctx.nodeIndex.get(p) || ctx.nodeIndex.get(p.split('/').pop()))
    if (!nodes.length || nodes.some((n) => !n)) {
      console.warn(`[fx-doors] 门节点解析失败, 该扇门禁用: ${name}`, def.nodes)
      continue
    }

    _unionBox.makeEmpty()
    for (const node of nodes) {
      _nodeBox.setFromObject(node, true)
      _unionBox.union(_nodeBox)
    }
    const hp = hingePoint(_unionBox, def.hinge)

    // 双层枢轴: parent -> align(定位+轴对齐世界) -> hinge(rotation.y 动画) -> 门节点
    const parent = nodes[0].parent
    parent.updateWorldMatrix(true, false)
    const align = new THREE.Group()
    align.name = `DOOR_ALIGN_${name}`
    parent.add(align)
    align.position.copy(parent.worldToLocal(_hingeWorld.set(hp.x, hp.y, hp.z)))
    parent.getWorldQuaternion(_q)
    align.quaternion.copy(_q.invert()) // 父世界旋转的逆 -> align 局部 Y = 世界竖直
    const hinge = new THREE.Group()
    hinge.name = `DOOR_HINGE_${name}`
    align.add(hinge)
    const originalParents = nodes.map((n) => n.parent)
    for (const node of nodes) hinge.attach(node) // 保世界位姿重挂

    const state = { name, def, nodes, originalParents, align, hinge, t: 0, target: 0 }
    doors.set(name, state)
    for (const node of nodes) {
      node.traverse((child) => {
        if (child.isMesh) meshToDoor.set(child, name)
      })
    }
  }

  // 对开门配对: 双向补齐. 只在一侧写 pair 也能成对 —— 否则"点这扇联动、点那扇只开
  // 自己"是个极隐蔽的半错状态, 目检很难发现.
  for (const door of doors.values()) {
    if (!door.def.pair) continue
    const mate = doors.get(door.def.pair)
    if (!mate || mate === door) {
      console.warn(`[fx-doors] pair 指向不存在的门, 该扇按单开处理: ${door.name} -> ${door.def.pair}`)
      continue
    }
    door.mate = mate
    mate.mate = door
  }

  let lastHoverMesh = null

  /**
   * 功能: 写开合目标, 并把对开门的另一扇一起带上 —— 对开门是一个物理整体,
   *       点哪扇都该两扇同开. 只跨一跳(不顺着 mate 再往下走), 故不会递归.
   * @param {string} name 门名(fxConfig.doors 的键)
   * @param {number} value 1=开 0=关
   * @returns {boolean} 是否命中一扇门
   */
  function applyTarget(name, value) {
    const door = doors.get(name)
    if (!door) return false
    door.target = value
    if (door.mate) door.mate.target = value
    return true
  }

  return {
    name: 'doors',

    /**
     * 功能: 开/关切换(对开门连动).
     * @param {string} name 门名(fxConfig.doors 的键)
     * @returns {boolean} 是否命中一扇门
     */
    toggleDoor(name) {
      const door = doors.get(name)
      if (!door) return false
      return applyTarget(name, door.target === 1 ? 0 : 1)
    },

    /**
     * 功能: 指定开合(对开门连动).
     * @param {string} name 门名
     * @param {boolean} open true=开
     * @returns {void}
     */
    setDoor(name, open) {
      applyTarget(name, open ? 1 : 0)
    },

    /**
     * 功能: 该 mesh 属于哪扇门(点击优先分派用).
     * @param {object} mesh 命中网格
     * @returns {string|null} 门名
     */
    doorOfMesh(mesh) {
      return (mesh && meshToDoor.get(mesh)) || null
    },

    /** 功能: 全部门的开合状态(验收断言用). */
    doorStates() {
      const out = {}
      for (const [name, door] of doors) {
        out[name] = { found: true, open: door.target === 1, t: Math.round(door.t * 1000) / 1000 }
      }
      return out
    },

    update(dt) {
      let moved = false
      for (const door of doors.values()) {
        if (door.t !== door.target) {
          const step = dt / Math.max(cfg.animS, 0.05)
          door.t = door.target > door.t
            ? Math.min(door.t + step, door.target)
            : Math.max(door.t - step, door.target)
          door.hinge.rotation.y = door.def.sign * door.def.openDeg * DEG * easeInOutSine(door.t)
          moved = true
        }
      }
      if (moved) ctx.invalidateShadows() // 每帧至多一次

      // 悬停到门体 -> cursor 变手型(门不出白卡, 只给可点暗示)
      const mesh = deps.cards?.hoveredMesh?.() || null
      if (mesh !== lastHoverMesh) {
        lastHoverMesh = mesh
        ctx.canvas.style.cursor = mesh && meshToDoor.has(mesh) ? 'pointer' : ''
      }
    },

    setStationState() {},
    setEnabled() {},
    setParams() {},

    dispose() {
      for (const door of doors.values()) {
        door.nodes.forEach((node, i) => door.originalParents[i]?.attach(node))
        door.align.removeFromParent()
      }
      doors.clear()
      meshToDoor.clear()
      ctx.canvas.style.cursor = ''
    },
  }
}
