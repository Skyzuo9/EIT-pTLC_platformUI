/**
 * 功能: 程序化冰蓝虚拟实验室背景 —— 一体旋转成型的封闭罩.
 *
 * 只承载空间本身, 不复制设备、不创建额外动态光源. 设备仍由 SceneManager 管理,
 * 环境光照、实时阴影、接触影和倒影继续走 Environment 链路.
 *
 * 为什么是"封闭罩"而不是四面墙或开口圆筒: 旧实现用 openEnded 的圆筒 + 有限方板地面,
 * 无顶无底且半透明不写深度, 相机一旦退到半径外就直接看穿 —— 而相机上限
 * (modelRadius * 12)本来就比房间半径大好几倍, 于是"缩到最小必穿帮". 现在剖面沿 Y 轴
 * 旋转 360°(地面→地墙圆角→直墙→穹顶收到轴心), 一体无接缝、无开口、不透明, 并由
 * laboratorySafeDistance() 从这个剖面反推相机轨道上限, 把"出不去"变成几何事实而非调参.
 */
import * as THREE from 'three'

export const LABORATORY_MIN_SIZE = Object.freeze({ width: 14, depth: 10, height: 4.2 })
export const LABORATORY_MARGIN = Object.freeze({ width: 8, depth: 7, height: 2.4 })
export const LABORATORY_MIN_RADIUS = 7.5
export const LABORATORY_RADIUS_CLEARANCE = 0.5

/** 罩体半径至少是整机外接球半径的这个倍数: 决定相机能退多远(见 laboratorySafeDistance) */
export const LABORATORY_RADIUS_MODEL_FACTOR = 6
/** 直墙高度相对罩体半径的比例下限: 半径大了墙还是 4.2 m 会显得像个盘子 */
export const LABORATORY_WALL_HEIGHT_RATIO = 0.38
/** 地墙圆角半径相对罩体半径的比例: 影棚无缝背景纸的"圆角过渡" */
export const LABORATORY_FILLET_RATIO = 0.16
/** 穹顶在直墙之上的升起高度相对罩体半径的比例 */
export const LABORATORY_DOME_RATIO = 0.6
/** 相机与罩体内表面之间保留的安全余量(米) */
export const LABORATORY_CAMERA_MARGIN = 0.5
/**
 * 罩体地面相对整机底面再往下让的量(米).
 * 舞台的三层贴地物在 y<0 处: 接触阴影 -0.001 / 倒影 -0.0015. 罩体地面若正好在 0,
 * 这两层会被埋在它下面 —— 现象是整机彻底没有落地感, 像浮在空中(已退役的方板地面
 * 当年写死 -0.006 就是这个原因, 一体罩必须继承).
 */
export const LABORATORY_FLOOR_DROP = 0.006

/** 剖面上圆角段与穹顶段各自的细分数(同时决定 Lathe 的经向精度) */
const FILLET_SEGMENTS = 14
const DOME_SEGMENTS = 20
/** 旋转细分数 */
const LATHE_SEGMENTS = 96
/** laboratorySafeDistance 在每段剖面上的加密采样数(只在模型加载时算一次, 可以给足) */
const SAFE_SAMPLES_PER_SEGMENT = 24

/**
 * 壳体渐变三段色: 地面亮 → 直墙中调 → 穹顶沉. 旋转对称, 所以各方位角观感一致.
 *
 * 亮色侧为什么不是一片近白: 这台设备通体白钣金, 罩子也near白的话整机只剩一团糊
 * (与 STAGES.light 里记着的"背景太亮看不清设备"是同一条教训, 那次把默认舞台的
 * 背景压过一档). 这里直墙压到中蓝灰, 白色机身才有剪影可立; 地面保持亮, 影子才读得出来.
 */
const LAB_PALETTES = {
  light: {
    floor: 0xc8d9ec,
    shellFloor: 0xccdbeb,
    shellWall: 0x9db2c9,
    shellDome: 0x6f8499,
    panel: 0xd9e8f8,
    light: 0xffffff,
    accent: 0xa8cae7,
  },
  dark: {
    floor: 0x101a28,
    shellFloor: 0x16242f,
    shellWall: 0x18283a,
    shellDome: 0x0a1420,
    panel: 0x23384e,
    light: 0xb4dcff,
    accent: 0x78add5,
  },
}

/**
 * 功能: 从 Three.Box3 或同形 {min,max} 计算虚拟大厅布局.
 *       纯计算导出供单测, 不依赖渲染器.
 * @param {{min:{x:number,y:number,z:number},max:{x:number,y:number,z:number}}|null} box 整机包围盒
 * @returns {{centerX:number,centerZ:number,floorY:number,shellBaseY:number,width:number,depth:number,
 *            height:number,radius:number,filletRadius:number,domeRise:number,
 *            apexY:number,modelRadius:number}} 罩体布局(radius/height 即直墙半径与直墙高度)
 */
export function computeLaboratoryLayout(box) {
  const valid = box
    && Number.isFinite(box.min?.x) && Number.isFinite(box.min?.y) && Number.isFinite(box.min?.z)
    && Number.isFinite(box.max?.x) && Number.isFinite(box.max?.y) && Number.isFinite(box.max?.z)
    && box.max.x >= box.min.x && box.max.y >= box.min.y && box.max.z >= box.min.z

  const min = valid ? box.min : { x: -1.4, y: 0, z: -1.1 }
  const max = valid ? box.max : { x: 1.4, y: 1.6, z: 1.1 }
  const size = {
    x: Math.max(max.x - min.x, 0.001),
    y: Math.max(max.y - min.y, 0.001),
    z: Math.max(max.z - min.z, 0.001),
  }
  const width = Math.max(LABORATORY_MIN_SIZE.width, size.x + LABORATORY_MARGIN.width)
  const depth = Math.max(LABORATORY_MIN_SIZE.depth, size.z + LABORATORY_MARGIN.depth)
  // 与 CameraRig.frameObject 同一口径: 外接球半径 = 包围盒对角线的一半
  const modelRadius = Math.max(Math.hypot(size.x, size.y, size.z) * 0.5, 0.001)

  // 罩体半径三者取大: 最小空旷感 / 包住加了余量的房间轮廓 / 给相机留出退让空间
  const radius = Math.max(
    LABORATORY_MIN_RADIUS,
    Math.hypot(width, depth) * 0.5 + LABORATORY_RADIUS_CLEARANCE,
    modelRadius * LABORATORY_RADIUS_MODEL_FACTOR,
  )
  const height = Math.max(
    LABORATORY_MIN_SIZE.height,
    size.y + LABORATORY_MARGIN.height,
    radius * LABORATORY_WALL_HEIGHT_RATIO,
  )
  const floorY = min.y
  const shellBaseY = floorY - LABORATORY_FLOOR_DROP
  const domeRise = radius * LABORATORY_DOME_RATIO

  return {
    centerX: (min.x + max.x) * 0.5,
    centerZ: (min.z + max.z) * 0.5,
    floorY,
    // 罩体自身的世界基准高度: 剖面局部 y=0 落在这里. 一切"剖面 → 世界"的换算都用它,
    // 不用 floorY, 否则判据算的是一个比实物高 6 mm 的假罩子
    shellBaseY,
    width,
    depth,
    height,
    radius,
    filletRadius: radius * LABORATORY_FILLET_RATIO,
    domeRise,
    apexY: shellBaseY + height + domeRise,
    modelRadius,
  }
}

/**
 * 功能: 生成罩体剖面折线(局部坐标, y 自 shellBaseY 起算, 沿 Y 轴旋转即得罩体).
 *       导出供 laboratorySafeDistance 与单测复用, 保证"判据与几何同源".
 * @param {object} layout computeLaboratoryLayout 的产物
 * @returns {Array<{r:number,y:number}>} 自轴心到穹顶顶点的剖面点列
 */
export function laboratoryProfile(layout) {
  const { radius, height, filletRadius, domeRise } = layout
  const fillet = Math.min(filletRadius, radius * 0.45, height * 0.9)
  const points = [{ r: 0, y: 0 }, { r: radius - fillet, y: 0 }]

  // 地墙圆角: 四分之一圆弧, 从水平地面平滑转成竖直墙面.
  // 末点直接写死 (radius, fillet): Math.cos(π/2) 不是精确 0, 留下的 1e-16 残差会让
  // 墙面半径与 layout.radius 对不上, 判据与几何就此分家.
  for (let index = 1; index < FILLET_SEGMENTS; index += 1) {
    const angle = (index / FILLET_SEGMENTS) * Math.PI * 0.5
    points.push({
      r: radius - fillet + Math.sin(angle) * fillet,
      y: fillet - Math.cos(angle) * fillet,
    })
  }
  points.push({ r: radius, y: fillet })

  // 直墙: 分舱面板与拱肋贴在这一段上
  points.push({ r: radius, y: height })

  // 穹顶: 四分之一椭圆收到轴心, 封死顶部
  for (let index = 1; index < DOME_SEGMENTS; index += 1) {
    const angle = (index / DOME_SEGMENTS) * Math.PI * 0.5
    points.push({
      r: Math.cos(angle) * radius,
      y: height + Math.sin(angle) * domeRise,
    })
  }
  // 顶点必须**精确**落在轴上: LatheGeometry 只在 x===0 时才走极点法线分支,
  // 否则顶上留一圈退化面片, 光照会在穹顶正中拧出一个亮斑
  points.push({ r: 0, y: height + domeRise })

  return points
}

/**
 * 功能: 由罩体剖面反推相机轨道距离上限 —— 超过它相机就会捅出罩外.
 *
 * 判据: CameraRig 的 maxPolarAngle < 90°, 所以相机始终**高于**轨道中心;
 *       相机可达集是"以轨道中心为心、半径 d 的上半球". 只要该半球不碰到罩体内表面
 *       (即 y >= 轨道中心高度的那部分剖面), 相机就出不去. 地面因此不参与约束.
 *       轨道中心会被 flyToStation/focusObjects 移到设备各处, 最大离轴 targetDrift.
 *
 * @param {object} layout computeLaboratoryLayout 的产物
 * @param {number} targetY 轨道中心的世界高度(整机包围盒中心高度)
 * @param {number} targetDrift 轨道中心可能偏离罩体轴心的最大水平距离(整机外接球半径)
 * @returns {number} 允许的 controls.maxDistance(米), 恒为正
 */
export function laboratorySafeDistance(layout, targetY, targetDrift) {
  const profile = laboratoryProfile(layout)
  const drift = Number.isFinite(targetDrift) ? Math.max(targetDrift, 0) : 0
  // 轨道中心必须严格高于地面, 否则"地面不参与约束"的前提不成立
  const centerY = Math.max(
    Number.isFinite(targetY) ? targetY : layout.shellBaseY,
    layout.shellBaseY + 1e-3,
  )

  let nearest = Infinity
  for (let index = 0; index < profile.length - 1; index += 1) {
    const from = profile[index]
    const to = profile[index + 1]
    for (let step = 0; step <= SAFE_SAMPLES_PER_SEGMENT; step += 1) {
      const t = step / SAFE_SAMPLES_PER_SEGMENT
      const r = from.r + (to.r - from.r) * t
      const worldY = layout.shellBaseY + from.y + (to.y - from.y) * t
      if (worldY < centerY) continue
      nearest = Math.min(nearest, Math.hypot(r - drift, worldY - centerY))
    }
  }
  // 剖面在轨道中心高度上可能一个采样点都没落到(极扁的罩子), 退到墙面水平余量
  const horizontal = layout.radius - drift
  const bound = Math.min(Number.isFinite(nearest) ? nearest : horizontal, horizontal)
  return Math.max(bound - LABORATORY_CAMERA_MARGIN, 0.1)
}

function disposeGroupGeometry(group) {
  group.traverse((node) => node.geometry?.dispose?.())
  group.clear()
}

/**
 * 功能: 创建可热切主题/显隐、可按设备包围盒重排的虚拟实验室.
 * @returns {{root:THREE.Group,setVisible:Function,setTheme:Function,setIntensity:Function,
 *           fitToModel:Function,dispose:Function,getLayout:Function}}
 */
export function createLaboratoryBackground() {
  const root = new THREE.Group()
  root.name = 'LABORATORY_BACKGROUND'
  root.visible = false

  const hall = new THREE.Group()
  hall.name = 'LABORATORY_HALL'
  root.add(hall)

  // fitToModel 重建几何; 主题切换重写壳体顶点色, 亮度切换只动共享材质.
  const materials = {
    // 壳体不透明且写深度: 相机既然出不去, 就没有"从外面看进来"这回事,
    // 半透明只会让远侧内壁与网格互相透穿. 色彩全部走顶点色, material.color 只承载亮度.
    // 粗糙度压到 0.62 是为了让地面吃到 HDRI 的柔和映影 —— 产品渲染图里"贵"的最大单一线索;
    // 壳体只有一份材质(一体成型没法逐段给粗糙度), 所以这个值同时是墙面的, 再低墙上会起高光条
    shell: new THREE.MeshStandardMaterial({
      roughness: 0.62,
      metalness: 0.0,
      side: THREE.BackSide,
      vertexColors: true,
    }),
    panel: new THREE.MeshStandardMaterial({
      transparent: true,
      opacity: 0.12,
      roughness: 0.5,
      metalness: 0.02,
      depthWrite: false,
      side: THREE.FrontSide,
    }),
    light: new THREE.MeshBasicMaterial({
      transparent: true,
      opacity: 0.82,
      depthWrite: false,
      side: THREE.FrontSide,
      toneMapped: false,
    }),
    accent: new THREE.MeshBasicMaterial({
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
      side: THREE.FrontSide,
      toneMapped: false,
    }),
  }

  let theme = 'light'
  let intensity = 1
  let layout = computeLaboratoryLayout(null)
  /** @type {THREE.Mesh|null} 一体罩, 顶点色随主题重写 */
  let shell = null

  /**
   * 功能: 按剖面高度给壳体逐顶点上色(地面亮 → 直墙中性 → 穹顶略沉).
   *       壳体是旋转对称的, 所以颜色只与高度有关, 各方位角观感一致.
   * @returns {void}
   */
  function applyShellColors() {
    if (!shell) return
    const palette = LAB_PALETTES[theme] || LAB_PALETTES.light
    const position = shell.geometry.getAttribute('position')
    const colors = new Float32Array(position.count * 3)
    const floorColor = new THREE.Color(palette.shellFloor)
    const wallColor = new THREE.Color(palette.shellWall)
    const domeColor = new THREE.Color(palette.shellDome)
    const mixed = new THREE.Color()

    // 分两段插值: 地面→直墙顶用圆角高度当过渡尺度, 直墙顶→穹顶顶点走剩下的高度
    const wallTop = layout.height
    const apex = layout.height + layout.domeRise
    for (let index = 0; index < position.count; index += 1) {
      const y = position.getY(index)
      if (y <= wallTop) {
        mixed.copy(floorColor).lerp(wallColor, THREE.MathUtils.clamp(y / Math.max(wallTop, 1e-6), 0, 1))
      } else {
        const t = THREE.MathUtils.clamp((y - wallTop) / Math.max(apex - wallTop, 1e-6), 0, 1)
        mixed.copy(wallColor).lerp(domeColor, t)
      }
      colors[index * 3] = mixed.r
      colors[index * 3 + 1] = mixed.g
      colors[index * 3 + 2] = mixed.b
    }
    shell.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  }

  function applyPalette() {
    const palette = LAB_PALETTES[theme] || LAB_PALETTES.light
    const factor = THREE.MathUtils.clamp(intensity, 0.4, 1.3)
    const luminousFactor = Math.min(factor, 1.08)

    // 壳体色在顶点里, material.color 只当亮度旋钮
    materials.shell.color.setScalar(1).multiplyScalar(factor)
    materials.panel.color.setHex(palette.panel).multiplyScalar(factor)
    materials.light.color.setHex(palette.light).multiplyScalar(luminousFactor)
    materials.accent.color.setHex(palette.accent).multiplyScalar(luminousFactor)

    const dark = theme === 'dark'
    materials.panel.opacity = (dark ? 0.16 : 0.12) * Math.min(factor, 1)
    materials.light.opacity = THREE.MathUtils.clamp((dark ? 0.62 : 0.82) * factor, 0.25, 0.94)
    materials.accent.opacity = THREE.MathUtils.clamp((dark ? 0.3 : 0.22) * factor, 0.08, 0.42)
  }

  function rebuild(nextLayout) {
    disposeGroupGeometry(hall)
    shell = null
    layout = nextLayout

    const { centerX, centerZ, shellBaseY, height, radius, filletRadius, domeRise } = layout

    // 一体罩: 剖面绕 Y 轴旋转, 地面/圆角/直墙/穹顶一次成型, 没有接缝也没有开口.
    const profile = laboratoryProfile(layout)
    shell = new THREE.Mesh(
      new THREE.LatheGeometry(
        profile.map((point) => new THREE.Vector2(point.r, point.y)),
        LATHE_SEGMENTS,
      ),
      materials.shell,
    )
    shell.position.set(centerX, shellBaseY, centerZ)
    shell.receiveShadow = true
    shell.renderOrder = -10
    shell.name = 'LAB_SHELL'
    hall.add(shell)
    applyShellColors()

    // 低透明度分舱面板提供空间尺度, 贴在圆角以上的直墙段, 不使用真实门窗或墙板纹理.
    const wallBottom = shellBaseY + filletRadius
    const wallSpan = Math.max(height - filletRadius, 0.2)
    const bayCount = THREE.MathUtils.clamp(Math.round(radius * 1.7), 12, 20)
    const bayRadius = radius - 0.045
    const bayWidth = (Math.PI * 2 * bayRadius / bayCount) * 0.78
    const bayGeometry = new THREE.PlaneGeometry(bayWidth, wallSpan * 0.8)
    const bays = new THREE.InstancedMesh(bayGeometry, materials.panel, bayCount)
    bays.name = 'LAB_VIRTUAL_PANELS'
    bays.renderOrder = -8

    const ribGeometry = new THREE.PlaneGeometry(0.032, wallSpan * 0.86)
    const ribs = new THREE.InstancedMesh(ribGeometry, materials.accent, bayCount)
    ribs.name = 'LAB_ARCH_RIBS'
    ribs.renderOrder = -7

    const transform = new THREE.Object3D()
    for (let index = 0; index < bayCount; index += 1) {
      const angle = index / bayCount * Math.PI * 2
      const x = centerX + Math.sin(angle) * bayRadius
      const z = centerZ + Math.cos(angle) * bayRadius
      transform.position.set(x, wallBottom + wallSpan * 0.5, z)
      transform.rotation.set(0, angle + Math.PI, 0)
      transform.updateMatrix()
      bays.setMatrixAt(index, transform.matrix)
      ribs.setMatrixAt(index, transform.matrix)
    }
    bays.instanceMatrix.needsUpdate = true
    ribs.instanceMatrix.needsUpdate = true
    hall.add(bays, ribs)

    // 三道宽光环贴在穹顶内表面上(按椭圆剖面求高度), 形成效果图里的轻盈穹顶.
    const ringScales = [0.42, 0.65, 0.88]
    for (let index = 0; index < ringScales.length; index += 1) {
      const scale = ringScales[index]
      const ringRadius = radius * scale
      const ringWidth = 0.075 + index * 0.025
      // 穹顶剖面 r = R·cos(t), y = H + rise·sin(t) ⇒ 给定 r 求 y
      const ringY = shellBaseY + height + domeRise * Math.sqrt(Math.max(1 - scale * scale, 0))
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(ringRadius - ringWidth, ringRadius + ringWidth, 96),
        materials.light,
      )
      ring.rotation.x = Math.PI / 2
      ring.position.set(centerX, ringY - 0.02, centerZ)
      ring.renderOrder = -5
      ring.name = `LAB_CEILING_LIGHT_${index}`
      hall.add(ring)
    }

    // 远端柔和水平光带只负责拉开地平线, 绝不围合设备包围盒.
    const horizon = new THREE.Mesh(
      new THREE.TorusGeometry(radius - 0.065, 0.018, 6, 96),
      materials.accent,
    )
    horizon.rotation.x = Math.PI / 2
    horizon.position.set(centerX, shellBaseY + height * 0.2, centerZ)
    horizon.renderOrder = -5
    horizon.name = 'LAB_HORIZON_GLOW'
    hall.add(horizon)
  }

  function setVisible(visible) {
    root.visible = Boolean(visible)
  }

  function setTheme(name) {
    theme = name === 'dark' ? 'dark' : 'light'
    applyPalette()
    applyShellColors()
  }

  function setIntensity(value) {
    const next = Number(value)
    intensity = Number.isFinite(next) ? next : 1
    applyPalette()
  }

  function fitToModel(box) {
    rebuild(computeLaboratoryLayout(box))
  }

  function dispose() {
    root.parent?.remove(root)
    disposeGroupGeometry(hall)
    shell = null
    for (const material of Object.values(materials)) material.dispose()
  }

  applyPalette()
  rebuild(layout)

  return {
    root,
    setVisible,
    setTheme,
    setIntensity,
    fitToModel,
    dispose,
    getLayout: () => ({ ...layout }),
  }
}
