/**
 * 功能: 薄层色谱板(TLC 板)的分层几何 —— 尺寸实测、层变换代数、共享单位盒.
 *
 * 为什么是程序化而不是 CAD 几何: CAD 里的 `玻璃-*` 就是一个 200×3×200 mm 的 12 面
 * 长方体, 既没有分层也没有正反面之分。真实的板是 **2mm 玻璃 + 一层不透明硅胶**,
 * 而硅胶层厚度是随板规格变的(制备型 0.5~2mm, 分析型 0.2~0.25mm), 必须运行时可调 ——
 * 烘进 GLB 就调不动了。长宽与位姿仍然**全部从 CAD 锚点实测**, 不猜一个数。
 *
 * 坐标约定: `measurePlateAnchor` 产出的是**父空间里的标准正交盒** —— 板面法线 +Y、
 * 面内两轴 +X/+Z、单位 scale。12 个落点实测在父空间一律 200 × 3 × 200 mm 且轴对齐。
 * 板的"硅胶朝上/朝下"由落点声明(见 PlateSlots.isSilicaUp), 被吸起后跟着吸盘刚性翻转,
 * 不需要任何朝向状态位。
 *
 * ⚠ **锚点自己的局部空间不是米制。** 04 步的 KHR_mesh_quantization 把顶点存成
 * `SHORT + normalized:true`, 反量化 scale 落在**节点的 scale 上**(实测锚点 scale≈0.1,
 * 而祖先链全是单位)。所以逐顶点读到的是量化坐标, **必须逐分量乘回 anchor.scale 才是米**;
 * 而且那个空间里的薄轴是 **Z** 不是 Y。
 * 2026-08-03 正因为漏了这一步, 板被画成一条 200×0.2×3mm 的线 —— 而单测用的是
 * 未量化的 BoxGeometry 夹具(scale=1、薄轴在 Y), 恰好是代码假设的那种锚点, 测不出来。
 */
import * as THREE from 'three'

/**
 * 全场唯一的单位盒(24 顶点 / 12 三角形)。所有板、所有层、料仓实例共用这一个,
 * 尺寸完全靠 mesh.scale 表达 —— renderer.info.memory.geometries 只 +1。
 */
export const UNIT_BOX = new THREE.BoxGeometry(1, 1, 1)

/** 玻璃基板厚度(mm)。用户拍板的标准板规格, 固定值。 */
export const GLASS_MM = 2.0

/**
 * 硅胶层厚度(mm)的可调范围与默认值。
 * 默认 1.0 → 总厚 3.0mm, 与 CAD 实测的 200×3×200 完全吻合, 不改变任何既有位姿。
 */
export const SILICA_MM = Object.freeze({ min: 0.1, max: 2.0, default: 1.0 })

/** 毫米 → 场景米(整机 1:1 米制)。 */
const MM = 0.001

/** 夹取硅胶厚度到合法区间; 非有限值回落默认。 */
export function clampSilicaMm(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return SILICA_MM.default
  return Math.min(SILICA_MM.max, Math.max(SILICA_MM.min, num))
}

/** 一块板的总厚(米) = 玻璃 + 硅胶。料仓节距未标定时的回退值就是它。 */
export function plateTotalM(silicaMm = SILICA_MM.default) {
  return (GLASS_MM + clampSilicaMm(silicaMm)) * MM
}

/** CAD 名义板长宽(米)。12 个落点实测一致, 只作为"还没量到锚点"时的兜底。 */
export const PLATE_NOMINAL_M = 0.2

/**
 * 功能: 标准板的兜底 geom —— 给"还没落到任何锚点上"的板一个正确尺寸.
 *
 * 不是猜数: 长宽用 CAD 名义 200mm(12 个落点实测全一致), 厚度用用户拍板的标准板总厚。
 * 位姿留在原点, 由调用方负责摆 —— 这里只保证板不会以单位盒的原始尺寸(1 米见方)出场。
 * @param {number} [silicaMm] 硅胶层厚度(mm)
 * @returns {object} 与 measurePlateAnchor 同形状的 geom
 */
export function standardPlateGeom(silicaMm = SILICA_MM.default) {
  return {
    widthM: PLATE_NOMINAL_M,
    lengthM: PLATE_NOMINAL_M,
    thickM: plateTotalM(silicaMm),
    center: new THREE.Vector3(),
    parent: null,
    position: new THREE.Vector3(),
    quaternion: new THREE.Quaternion(),
    scale: new THREE.Vector3(1, 1, 1),
    silicaUp: true,
  }
}

const _v = new THREE.Vector3()
const _m = new THREE.Matrix4()

/** 板面两个方向至少要比厚度大这么多倍, 否则这个锚点根本不是一块板。 */
const PLATE_ASPECT_MIN = 10

/**
 * 功能: 实测一个 CAD 板锚点, 产出**父空间里的标准正交盒**(板面法线 +Y, 单位 scale).
 *
 * 三个坑都绕开了:
 *   1. 不用 `geometry.boundingBox` —— KHR_mesh_quantization 会把每个图元的缓存局部
 *      AABB 变成量化立方体(见 three_d/docs/CLAUDE.md 第 6 条), 读它必然偏大。逐顶点算。
 *   2. 不用 `Box3.setFromObject(obj, true)` —— 它算的是**世界轴对齐**包围盒, 板一旦带
 *      面内旋转就会膨胀(第 11 条同款教训)。这里先把顶点变换回锚点自身坐标系再拟合,
 *      于是对任意摆放都成立 —— 这条**旋转免疫**是仍在局部量而不是直接在父空间量的理由。
 *   3. 锚点局部空间**不是米制**, 薄轴也**不在 Y** —— 见模块头注释。所以量完之后要:
 *      逐分量乘回 `anchor.scale` 换算成米, 再检出薄轴、把它转成父空间的标准正交帧。
 *
 * 产出的语义(下游全部按这个来, 于是 layerTransforms 那套"薄轴在 Y"的简单代数才成立):
 *   position   父空间里的**盒心**位置
 *   quaternion 标准帧: +Y = 板面法线(取世界朝上那一侧), +X/+Z = 面内两轴
 *   scale      恒为 (1,1,1) —— 反量化 scale 已经烘进尺寸里了
 *   center     恒为 (0,0,0) —— 盒心偏移已经折进 position
 *
 * @param {THREE.Object3D} anchor CAD 玻璃盒节点(可以是 Mesh, 也可以是带网格子级的组)
 * @returns {{widthM:number, lengthM:number, thickM:number, center:THREE.Vector3,
 *            parent:THREE.Object3D|null, position:THREE.Vector3,
 *            quaternion:THREE.Quaternion, scale:THREE.Vector3} | null}
 *          不是一块板(三轴没有明显薄轴)时返回 null —— 让调用方走"解析不到就不画"的
 *          留白路径, 而不是摆一块尺寸可疑的板。
 */
export function measurePlateAnchor(anchor) {
  if (!anchor) return null
  anchor.updateWorldMatrix(true, true)
  const toLocal = _m.copy(anchor.matrixWorld).invert()
  const box = new THREE.Box3()
  let vertices = 0

  anchor.traverse((child) => {
    const position = child.isMesh ? child.geometry?.attributes?.position : null
    if (!position) return
    // 子网格顶点 → 世界 → 锚点局部; 锚点自身就是 Mesh 时该复合矩阵退化为单位阵
    const toAnchor = new THREE.Matrix4().multiplyMatrices(toLocal, child.matrixWorld)
    for (let i = 0; i < position.count; i += 1) {
      _v.fromBufferAttribute(position, i).applyMatrix4(toAnchor)
      box.expandByPoint(_v)
      vertices += 1
    }
  })

  if (!vertices || box.isEmpty()) return null

  // 局部尺寸 × 节点 scale = 真米制。scale 承载的是反量化因子, 不是造型意图。
  const localSize = box.getSize(new THREE.Vector3())
  const localCenter = box.getCenter(new THREE.Vector3())
  const size = [
    localSize.x * Math.abs(anchor.scale.x),
    localSize.y * Math.abs(anchor.scale.y),
    localSize.z * Math.abs(anchor.scale.z),
  ]

  // 薄轴 = 三轴最小者。绝不假定是哪一根: 真实锚点是 Z, 单测夹具历史上是 Y。
  const thin = size.indexOf(Math.min(...size))
  const plane = [0, 1, 2].filter((axis) => axis !== thin)
  if (size[plane[0]] < size[thin] * PLATE_ASPECT_MIN
    || size[plane[1]] < size[thin] * PLATE_ASPECT_MIN) {
    return null
  }

  // 局部三轴 → 父空间方向(带上锚点自己的旋转与 scale; scale 为正只影响长度不影响方向)
  const axisDir = (index) => {
    const local = new THREE.Vector3(index === 0 ? 1 : 0, index === 1 ? 1 : 0, index === 2 ? 1 : 0)
    return local.multiply(anchor.scale).applyQuaternion(anchor.quaternion).normalize()
  }
  const normal = axisDir(thin)
  const inPlane = axisDir(plane[0])

  // 法线取"在世界里朝上"那一侧: 下游把 +Y 当板面上方, 两层的上下顺序由落点语义决定,
  // 而不是由 CAD 盒恰好朝哪边建模决定(对称长方体本来也没有正反之分)。
  const parent = anchor.parent || null
  if (parent) {
    parent.updateWorldMatrix(true, false)
    const worldNormal = normal.clone().applyQuaternion(
      parent.getWorldQuaternion(new THREE.Quaternion()),
    )
    if (worldNormal.y < 0) normal.negate()
  }
  // 右手系: Z = X × Y
  const third = new THREE.Vector3().crossVectors(inPlane, normal)
  const basis = new THREE.Matrix4().makeBasis(inPlane, normal, third)

  return {
    widthM: size[plane[0]],
    lengthM: size[plane[1]],
    thickM: size[thin],
    center: new THREE.Vector3(),
    parent,
    // 盒心在父空间: 锚点原点 + 锚点旋转/缩放作用后的局部盒心
    position: localCenter.clone().multiply(anchor.scale)
      .applyQuaternion(anchor.quaternion).add(anchor.position),
    quaternion: new THREE.Quaternion().setFromRotationMatrix(basis),
    scale: new THREE.Vector3(1, 1, 1),
  }
}

/**
 * 功能: 由硅胶厚度算两层的 scale 与 y 偏移(板 Group 局部空间).
 *
 * 基准取 **CAD 盒的底面**而不是中心: 板是坐在缸底/托盘/料仓上的, 底面才是接触面。
 * 厚度变化一律向 +Y 生长, 于是调厚度不会让板陷进承托面, 也不会悬空。
 *
 * 两层的上下顺序由 `geom.silicaUp` 决定(落点语义, 见 PlateSlots.isSilicaUp) ——
 * 料仓/展缸/废料仓是硅胶朝下(玻璃面朝上给吸盘贴), 点样座/刮板台是硅胶朝上。
 *
 * @param {object} geom measurePlateAnchor 的结果(可带 silicaUp)
 * @param {number} silicaMm 硅胶层厚度(mm)
 * @returns {{glass:{scale:number[], y:number}, silica:{scale:number[], y:number},
 *            x:number, z:number, totalM:number}}
 */
export function layerTransforms(geom, silicaMm = SILICA_MM.default) {
  const t = clampSilicaMm(silicaMm)
  const glassM = GLASS_MM * MM
  const silicaM = t * MM
  const width = geom?.widthM || 0.2
  const length = geom?.lengthM || 0.2
  const center = geom?.center || new THREE.Vector3()
  const bottomY = center.y - (geom?.thickM ?? glassM + silicaM) / 2
  const silicaUp = geom?.silicaUp !== false     // 缺省朝上(点样/刮板是最常被看的两处)

  const lower = silicaUp ? glassM : silicaM
  const upper = silicaUp ? silicaM : glassM
  const lowerY = bottomY + lower / 2
  const upperY = bottomY + lower + upper / 2

  return {
    x: center.x,
    z: center.z,
    totalM: glassM + silicaM,
    glass: { scale: [width, glassM, length], y: silicaUp ? lowerY : upperY },
    silica: { scale: [width, silicaM, length], y: silicaUp ? upperY : lowerY },
  }
}

/**
 * 功能: 板的两个面在**板局部系**里的 y —— 贴吸盘那一面与背离吸盘那一面.
 *
 * 单独抽出来是因为两处要用同一套代数, 而层的上下顺序只由 `silicaUp` 决定:
 *   suctionMountLocal 要 `contactY`(把它钉到吸盘唇口上);
 *   plateContact 要 `farY`(从那一面往外打射线找硬表面)。
 * 两处各推一遍迟早漂, 且漂了不报错 —— 表现只是板贴得不对, 看不出来。
 *
 * **吸盘永远贴玻璃面**, 从不贴硅胶(那是要被点样/刮取的粉末面), 所以 contactY 恒取玻璃层
 * 的外侧面。板体总在接触面的 +axis 一侧, 于是 farY 比 contactY 更靠 +axis 一整个板厚。
 *
 * @param {object} geom measurePlateAnchor 的结果(要 silicaUp)
 * @param {number} [silicaMm] 硅胶层厚度(mm)
 * @returns {{contactY: number, farY: number, totalM: number}} 板局部系的 y 与总厚(米)
 */
export function plateFaceLocalY(geom, silicaMm = SILICA_MM.default) {
  const silicaUp = geom?.silicaUp !== false
  const layers = layerTransforms(geom, silicaMm)
  const glassHalf = (GLASS_MM * MM) / 2
  const contactY = silicaUp ? layers.glass.y - glassHalf : layers.glass.y + glassHalf
  return {
    contactY,
    farY: contactY + layers.totalM * (silicaUp ? 1 : -1),
    totalM: layers.totalM,
  }
}

const _axis = new THREE.Vector3()
const _contact = new THREE.Vector3()
const _spanX = new THREE.Vector3()
const _plateY = new THREE.Vector3()
const _plateZ = new THREE.Vector3()
const _basis = new THREE.Matrix4()

/**
 * 功能: 由**吸盘自己的几何**算出板挂在翻转节点下时的局部位姿.
 *
 * 为什么不再走"保世界位姿换父": 那等于把取板那一刻的示教残差原样冻进去, 于是板与吸盘
 * 的相对关系每站一个样。2026-08-05 用 verify_plate_seats 实测: rotary-up 两站在法兰系下
 * 差 134.0mm(= 点样 7Y 99 + 刮板 8Y 35, 两根没被片段驱动的工位轴), 料仓两站差 530mm
 * (1Z/2Z 顶升没被驱动)。而吸盘对板的关系本该是**纯刀具几何** —— 同一把刀、任何站、
 * 任何机械臂朝向下都一样。常量由管线实测后随 manifest 下发(见 gen_twin_manifest
 * .resolve_plate_grip), 这里只做代数, 不猜任何数。
 *
 * **吸盘永远贴玻璃面**, 从不贴硅胶(那是要被点样/刮取的粉末面) —— 所以被吸的是哪一面
 * 由 `geom.silicaUp` 唯一决定, 不需要任何新的朝向状态位:
 *   料仓/展缸(silicaUp=false) 玻璃在上, 吸盘从上方贴 → 板的 +Y 面贴住接触面;
 *   点样座/刮板台(silicaUp=true) 玻璃在下, 吸盘从下方托 → 板的 −Y 面贴住接触面。
 *
 * @param {object} grip manifest 的 actuators[rob_flip_suction].plateGrip
 * @param {object} geom measurePlateAnchor 的结果(要 thickM 与 silicaUp)
 * @param {number} [silicaMm] 当前硅胶层厚度(mm) —— 改厚度后贴合面要跟着走
 * @returns {{position: THREE.Vector3, quaternion: THREE.Quaternion} | null}
 *          grip 缺失或不成形时返回 null, 让调用方退回旧的"保世界位姿"路径
 */
export function suctionMountLocal(grip, geom, silicaMm = SILICA_MM.default) {
  const axis = grip?.axisLocal
  const contact = grip?.contactLocalM
  const span = grip?.spanAxisLocal
  if (!Array.isArray(axis) || axis.length !== 3) return null
  if (!Array.isArray(contact) || contact.length !== 3) return null
  if (!Array.isArray(span) || span.length !== 3) return null

  _axis.fromArray(axis)
  if (_axis.lengthSq() < 1e-12) return null
  _axis.normalize()

  const silicaUp = geom?.silicaUp !== false
  // 板面法线(标准帧 +Y)在翻转节点局部系里的朝向: 板体总在接触面的 +axis 一侧,
  // 所以贴住的那一面朝向 −axis, 而哪一面贴住由 silicaUp 决定。
  _plateY.copy(_axis).multiplyScalar(silicaUp ? 1 : -1)

  // 面内 +X 取吸盘连线, 并对 +Y 正交化 —— 方板本身没有取向, 钉死它是为了让转载前后
  // 的朝向可复现(ClipPlayer 向后 seek 会重放事件, 朝向若随机, 画面就会跳)。
  _spanX.fromArray(span)
  _spanX.addScaledVector(_plateY, -_spanX.dot(_plateY))
  if (_spanX.lengthSq() < 1e-12) return null
  _spanX.normalize()
  // 右手系, 与 measurePlateAnchor 的 makeBasis(inPlane, normal, inPlane×normal) 同构
  _plateZ.crossVectors(_spanX, _plateY)

  // 贴合面在板局部系里的 y —— 与 plateContact 共用同一套代数, 见 plateFaceLocalY
  const { contactY: faceY } = plateFaceLocalY(geom, silicaMm)

  // 真正的贴合面不是**自由长度**的唇口, 而是被吸住后**压缩到位**的唇口。
  //
  // CAD 里这只波纹杯是自由态(逐顶点实测正好 35.0mm, contactLocalM 也正落在唇口上 ——
  // 量法没错), 但真机是抽着真空夹板的, 波纹早压瘪了。少扣这一段, 板就被画在自由唇口上,
  // 放板时整块板扎进座面 —— 2026-08-05 用户报的穿模就是它, 实测 17.82mm。
  // 常量缺席(老 manifest)时为 0, 退回原来的"贴自由唇口"行为, 不会崩也不会突然挪位。
  const carry = Number(grip?.carryCompressionM) || 0
  const workingContact = _contact.fromArray(contact).addScaledVector(_axis, -carry)

  // 板上局部点 (0, faceY, 0) 必须落在接触点上 => root = contact − faceY * plateY
  const position = workingContact.clone().addScaledVector(_plateY, -faceY)
  _basis.makeBasis(_spanX, _plateY, _plateZ)
  return { position, quaternion: new THREE.Quaternion().setFromRotationMatrix(_basis) }
}
