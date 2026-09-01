/**
 * 功能: 开发期验收钩子 —— 把 rig/播放器/场景的内部真值暴露到 window, 供浏览器验收脚本读.
 *
 * 消费方是 three_d/tools/visual_validation/ 下的 Playwright 脚本(verify_studio.py 等):
 * 它们要读的是"工具锁紧后到底挂在谁身上""某节点此刻的世界位姿"这类**内部真值**, 截图看
 * 不出来, DOM 里也没有。
 *
 * 与原 MotionView 里那一大坨内联钩子的区别只是搬了家: 动作工作台与演示页都播片段, 两边
 * 各写一份必然漂, 所以收成一个模块两处装。
 *
 * 仍然锁在 `import.meta.env.DEV` 后面(与搬家前一致): 生产构建里不存在这些钩子, 也就没有
 * 从控制台直接驱动机构的入口。
 */
import * as THREE from 'three'

/**
 * 功能: 安装 window.__anim.
 *
 * @param {object} options 参数对象
 * @param {import('vue').ShallowRef} options.manager SceneManager
 * @param {object} options.stack useMotionStack 返回值
 * @param {import('vue').Ref} options.transport 传输条状态
 * @param {() => string} options.currentName 当前片段名
 * @param {object} [options.extra] 追加的钩子(各页自己的东西)
 * @returns {() => void} 卸载函数
 */
export function installAnimHooks({ manager, stack, transport, currentName, extra = {} }) {
  if (!import.meta.env.DEV) return () => {}

  /** 取一个 three 向量类的构造器(避免在本模块里 import three) */
  const vectorOf = (node) => Object.getPrototypeOf(node.position).constructor
  const resolve = (name) => stack.rig.value?._resolve(name) || null

  window.__anim = {
    state: () => ({ ...transport.value, clip: currentName() }),
    seek: (t) => stack.player.value?.seek(Number(t)),
    play: () => {
      if (!transport.value.playing) stack.player.value?.toggle()
    },
    pause: () => {
      if (transport.value.playing) stack.player.value?.toggle()
    },
    setSpeed: (speed) => stack.player.value?.setSpeed(speed),
    setJoints: (values) => stack.rig.value?.setJointsDeg(values),
    setAxis: (id, mm) => stack.rig.value?.setAxisMm(id, mm),
    axisValue: (id) => stack.rig.value?.axes.get(id)?.valueMm ?? null,
    home: () => stack.rig.value?.home(),

    toolParent: (id) => stack.rig.value?.toolParentName(id),
    toolWorld: (id) => stack.rig.value?.toolWorldPosition(id),

    // 驱动本体 —— attach/dock 的**决策路径**只能从内部读: 磁吸没生效时, 外部钩子只看得到
    // "件的位置没动", 分不清是提前 return(mount 身份不符/载荷缺 mountLocal)、补间没登记,
    // 还是补间跑了但目标本身算错。载荷锚点这类几何契约出过多次"数字看着对、屏幕上是错的",
    // 验收脚本必须能读到 mount 身份、载荷 spec 与补间表本身。
    driver: () => stack.rig.value || null,

    nodeWorld: (name) => {
      const node = resolve(name)
      if (!node) return null
      const point = new (vectorOf(node))()
      node.getWorldPosition(point)
      return [point.x, point.y, point.z]
    },
    // 子树的**世界系**包围盒 —— 验收探针量"某零件的实占空间"用(如点样喷嘴尖的轴线:
    // 节点原点常在装配原点上, 与几何差几十毫米, 只有 bbox 说得准)。
    // 与 plateGeometry 禁用 setFromObject 的那条纪律不冲突: 那里要的是锚点**局部**
    // 标准正交盒(setFromObject 给的世界 AABB 会把斜摆的盒撑大), 这里要的恰是世界 AABB。
    // Box3 没有现成实例可借构造器, 破例直接引 three —— 本模块 DEV-only 且 three 本就
    // 在包里, 无新增重量。
    worldBox: (name) => {
      const node = resolve(name)
      if (!node) return null
      const box = new THREE.Box3().setFromObject(node)
      if (box.isEmpty()) return null
      return { min: box.min.toArray(), max: box.max.toArray() }
    },
    nodeWorldPose: (name) => {
      const node = resolve(name)
      if (!node) return null
      const Vector = vectorOf(node)
      const Quaternion = Object.getPrototypeOf(node.quaternion).constructor
      const position = new Vector()
      const quaternion = new Quaternion()
      node.getWorldPosition(position)
      node.getWorldQuaternion(quaternion)
      return { position: position.toArray(), quaternion: quaternion.toArray() }
    },
    nodeLocal: (name) => {
      const node = resolve(name)
      if (!node) return null
      return {
        parent: node.parent?.name || null,
        position: node.position.toArray(),
        quaternion: node.quaternion.toArray(),
        scale: node.scale.toArray(),
        // 空缸必须**真的隐藏**而不是压扁(压扁的液面盒仍有一张满尺寸不透明顶面) ——
        // verify_tank_liquid.py 靠这个字段验那一条
        visible: node.visible,
      }
    },
    nodesWorldMatching: (pattern) => {
      const matches = []
      const needle = String(pattern || '').toLowerCase()
      stack.rig.value?.root?.traverse((node) => {
        if (!needle || !String(node.name || '').toLowerCase().includes(needle)) return
        const point = new (vectorOf(node))()
        node.getWorldPosition(point)
        matches.push({ name: node.name, world: [point.x, point.y, point.z] })
      })
      return matches
    },

    // 把镜头怼到指定节点上 —— 默认取景是整机全貌, 缸内的液面与板全被机罩挡着,
    // "液体有没有糊到缸外""板有没有穿进缸壁"这类只能靠眼睛的判据在全貌里根本看不见。
    frame: (names, padding = 0.4) => {
      const wanted = (Array.isArray(names) ? names : [names]).map(resolve).filter(Boolean)
      return stack.tools.value?.frameObjects(wanted, padding) ?? false
    },

    // 板舞台: 验收"虚拟板出现在合适的位置"用
    plates: () => stack.plateStatus(),
    // 板是运行期造的, 不在节点索引里 —— nodeLocal/nodesWorldMatching 都找不到它
    plateLocal: (plateId) => stack.plateLocal?.(plateId) ?? null,
    // 板根的**世界**位姿: 刮取验收要把 uvBand 反投影成条带端点的世界坐标
    // (再经 screenOf 落到像素上采色), 局部位姿 + 父级链在脚本侧复合既繁琐又易漂。
    plateWorld: (plateId) => {
      const root = stack.plateLayerRef?.()?.get(plateId)?.root
      if (!root) return null
      const Vector = vectorOf(root)
      const Quaternion = Object.getPrototypeOf(root.quaternion).constructor
      const position = new Vector()
      const quaternion = new Quaternion()
      root.updateWorldMatrix(true, false)
      root.getWorldPosition(position)
      root.getWorldQuaternion(quaternion)
      return { position: position.toArray(), quaternion: quaternion.toArray() }
    },
    // 单独跑一次接触判据(量它自己每帧多少开销用; 正常路径由帧钩子调)
    plateContactTick: () => stack.plateContactTick?.(),
    // 手上那块板当帧**全向**相交了哪些静止件、多深(mm)。
    // ⚠ 与 plates().contact 分工不同: 那个只沿吸盘轴打射线, 面内横扫进侧壁它恒返回 0
    //   —— 2026-08-06 就是因为只信它, 把"面内偏移已归零"当成了"不穿模"。
    plateOverlap: () => stack.plateOverlap?.(),

    // 工艺灯当前亮度(0..1 系数)与实际写进材质的 emissiveIntensity
    lightLevels: () => {
      const out = {}
      for (const [id, entry] of stack.rig.value?.lights || []) {
        out[id] = {
          level: Number.isFinite(entry.value) ? +entry.value.toFixed(4) : null,
          emissive: +(entry.material.emissiveIntensity ?? 0).toFixed(4),
        }
      }
      return out
    },

    // 世界点 -> 画布客户端像素(合成拖拽用)
    screenOf: (world) => {
      const instance = manager.value
      if (!instance || !Array.isArray(world)) return null
      const Vector = Object.getPrototypeOf(instance.camera.position).constructor
      const projected = new Vector(...world).project(instance.camera)
      const rect = instance.canvas.getBoundingClientRect()
      return [
        rect.left + ((projected.x + 1) / 2) * rect.width,
        rect.top + ((1 - projected.y) / 2) * rect.height,
      ]
    },
    // 该轴某个可拖网格的表面点(中间顶点, 世界坐标) —— 合成拖拽的按下位置
    dragAnchor: (axisId) => {
      const controller = stack.dragger.value
      if (!controller) return null
      for (const [mesh, id] of controller.meshAxis.entries()) {
        if (id !== axisId || !mesh.visible) continue
        const positions = mesh.geometry?.attributes?.position
        if (!positions || !positions.count) continue
        const point = new (vectorOf(mesh))().fromBufferAttribute(
          positions, Math.floor(positions.count / 2),
        )
        mesh.updateWorldMatrix(true, false)
        mesh.localToWorld(point)
        return [point.x, point.y, point.z]
      }
      return null
    },

    ...extra,
  }

  return () => {
    delete window.__anim
  }
}
