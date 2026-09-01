/**
 * 功能: 板面痕迹的几何换算与画布绘制 —— `scrape`/`spot`/`wet` 原语与实时页
 *       "实际刀路"共用的视觉数学层, 全部幂等.
 *
 * 分工(与 liquid 的"换算留写入层"同一条纪律):
 *   上游只给**板 cm 帧**的几何(compiled.scrapeRegions/spotRegions/wetRegions 或后端
 *   /api/3d/plate-traces, 原点=板左下角, 与 controller/plate_coords.py 同帧) ——
 *   那是有真源的帧; 本模块负责把它换算到硅胶面的 UV 上, 并按各自进度画遮罩.
 *
 * 帧链: 板 cm 帧 → 板局部帧(measurePlateAnchor 的标准正交盒: +Y=法线, +X/+Z 面内)
 *       → 硅胶盒 UV(BoxGeometry +Y 面). 每一跳都不猜:
 *   cm→局部: 两种锚定, 按板当下的处境选 ——
 *     machine: 机床方向(manifest.axes 实读)与板局部轴做点积, 定轴定向. 只在板正对
 *              机床摆着的工位成立(刮板台 9X/8Y, 点样座 6X/7Y);
 *     gravity: 展缸里的板与刮台机床轴不对齐(近竖直), machine 锚定的对齐门槛会拒画.
 *              但缸里有更硬的物理事实 —— 板下沿(cm y=0, 点样线那条边)朝下浸在溶液槽里,
 *              所以 +y_cm = 世界上方向在板面内的投影. 见 gravityDirsWorld.
 *   局部→UV: three BoxGeometry buildPlane 的 py 面固定映射(u 沿 +x 增, v 沿 +z 减;
 *            该映射自 r125 起未变, 若升级 three 后条带转了 90°, 先查这里).
 *
 * ⚠ 板禁用世界空间投影纹理(plateMaterials.js 头注释: 语义非均匀 scale 会放大成鳄鱼皮),
 *   所以这里全部走板自身 UV, 与那条硬约束不冲突.
 */
import * as THREE from 'three'

/**
 * 遮罩画布边长(px)。512px 下 200mm 板面 1px≈0.4mm —— 实际刮取刀路要按刀宽(2mm)描边,
 * 256px 时一刀只有 2.5px, 锯齿读得出来; 512px 给到 5px。矩形前沿类痕迹 256 已够,
 * 跟着涨到 512 的代价只在重画帧(纹理上传 1MB), 而重画只在进度真的变了时发生。
 */
export const SCRAPE_CANVAS_SIZE = 512

/**
 * 刮松未收粉区域的填充色。观感值, 不是物理量: 被刮刀犁过的粉层比未动的粉略暗略毛,
 * 取一个能在 #f1f3f5 基色上看出差别、又不至于读成"脏板"的暖灰。
 */
export const SCRAPE_LOOSEN_FILL = '#d6d0c8'

/**
 * 点样色带的填充色。取上位机既有的"谱带橙"(cnc_preview.py contour_orange,
 * OpenCV BGR (54,132,255) = RGB #FF8436) —— 系统里凡是"样品带"就是这个橙, 不另造色。
 */
export const SPOT_BAND_FILL = '#ff8436'

/**
 * 溶剂润湿区的罩色(半透明灰绿, 叠在白底/色带上整体压暗)。alpha 只是画布合成系数,
 * 落到不透明白底上后像素 alpha 仍是 1 —— 不会误触发硅胶材质的 alphaTest discard
 * (alpha 通道的"挖穿"语义独属刮取, 见 drawTrace 的绘制次序注释)。
 */
export const WET_FILL = 'rgba(96, 112, 108, 0.30)'

/** 溶剂前沿线的颜色。干燥后前沿在真板上也留一条可见的界线, 所以进度=1 时照画。 */
export const WET_FRONT_LINE = 'rgba(84, 98, 94, 0.55)'

/** cm 轴与板局部轴的最小对齐度(cos 30°)。低于它 = 板没有正对机床摆, 宁可不画。 */
const AXIS_ALIGN_MIN = 0.87

const _quat = new THREE.Quaternion()

/**
 * 功能: 从 manifest 实读机床 X/Y 在**世界系**里的方向(板 cm 帧的两根轴).
 *
 * spec.axis 表达在滑车**父级**的局部系 —— MachineStateDriver.setAxisMm 写的是
 * `node.position = base + normalize(spec.axis) * sign * offset`, 而 position 是父空间量.
 * 转世界必须乘父级的世界姿态, 不是节点自己的(节点带着自身旋转时会差一截).
 *
 * 机床 Y 取反是全链唯一一处符号推理, 依据是**板动刀不动**: Y 轴(8Y 板托台 / 7Y 点样座)
 * 载的是**板**, 毫米增大时板沿 +方向走, 刀/喷头在板面上的接触点相对板往 −方向挪;
 * 而板 cm 帧的 y 是"刀落在板上哪一行"(plate_origin_y 的定义, app.yaml gcode 段),
 * 所以 +y_cm 的世界方向 = 托台运动方向取反. X 轴(9X 刀 / 6X 喷射头)是刀自己走、
 * 板不动, 不取反. 两个工位共用这条推理, 差别只在轴 id 与标定方向:
 *   刮板台(缺省): axis_9x / axis_8y, 方向由 app.yaml gcode.origin_corner 定, 恒 +1;
 *   点样座:       axis_6x / axis_7y + SPOT_BAND_CALIB 的 x_dir/y_dir(编译器与
 *                 motion-map 的 spotBandCalib 同源, 是那张标定表的一部分).
 *
 * @param {object} manifest device-manifest(要 axes[].axis/sign/glbNode)
 * @param {(name: string) => import('three').Object3D|undefined} resolveNode 节点解析
 *        (先按 glbNode 全路径, 再退叶名 —— 与 nodeIndex 的双索引约定一致)
 * @param {{xAxis?: string, yAxis?: string, xDir?: number, yDir?: number}} [opts]
 *        轴 id 与标定方向(缺省=刮板台)
 * @returns {{xCm: THREE.Vector3, yCm: THREE.Vector3}|null} 解析不全时 null(留白不画)
 */
export function machineDirsWorld(manifest, resolveNode, opts = {}) {
  const { xAxis = 'axis_9x', yAxis = 'axis_8y', xDir = 1, yDir = 1 } = opts
  const dirOf = (axisId) => {
    const spec = (manifest?.axes || []).find((axis) => axis.id === axisId)
    if (!spec || !Array.isArray(spec.axis) || spec.axis.length !== 3) return null
    const path = String(spec.glbNode || '')
    const node = resolveNode?.(path) || resolveNode?.(path.split('/').pop() || '')
    if (!node?.parent) return null
    node.parent.updateWorldMatrix(true, false)
    return new THREE.Vector3(...spec.axis)
      .normalize()
      .multiplyScalar(Number(spec.sign ?? 1) >= 0 ? 1 : -1)
      .applyQuaternion(node.parent.getWorldQuaternion(_quat))
      .normalize()
  }
  const xCm = dirOf(xAxis)
  const yCarrier = dirOf(yAxis)
  if (!xCm || !yCarrier) return null
  return {
    xCm: xCm.multiplyScalar(Number(xDir) < 0 ? -1 : 1),
    yCm: yCarrier.negate().multiplyScalar(Number(yDir) < 0 ? -1 : 1),
  }
}

/**
 * 功能: 展缸里的板的 cm 轴世界方向 —— 重力锚定(machine 锚定在缸里必然拒画的替代).
 *
 * 物理依据: 缸里的板近竖直, 下沿(cm y=0, 点样线那条边)浸在溶液槽里 —— TLC 展开的
 * 定义本身. 所以 +y_cm = 世界上方向在板面内的投影; +x_cm 由右手系补全
 * (看着粉面时 x 向右: x̂ = ŷ × n̂, n̂ 是**粉面**的外法线 —— 硅胶朝下挂的板要取局部 −Y,
 * 板池复用时朝向由落点的 geom.silicaUp 声明, 与 PlateFaceLayer._applyResidual 同源).
 *
 * 板太接近水平(法线近铅垂)时重力投影退化, 返回 null 留白 —— 与 machine 锚定的
 * 对齐门槛(AXIS_ALIGN_MIN)同一条"宁可不画"纪律.
 *
 * ⚠ x 的镜像取向对"满宽"的润湿区没有影响; 对点样色带只在带不居中时有零点几厘米的
 * 可辨差 —— 但这不是猜: 右手系 + 粉面外法线把符号唯一钉死了.
 *
 * @param {THREE.Quaternion} plateQuatWorld 板根的世界姿态
 * @param {boolean} [silicaUp] 粉面是否朝板局部 +Y(落点 geom.silicaUp; 缸位是 false)
 * @returns {{xCm: THREE.Vector3, yCm: THREE.Vector3}|null} 板近水平时 null(留白不画)
 */
export function gravityDirsWorld(plateQuatWorld, silicaUp = true) {
  if (!plateQuatWorld) return null
  const normal = new THREE.Vector3(0, silicaUp ? 1 : -1, 0).applyQuaternion(plateQuatWorld)
  const yCm = new THREE.Vector3(0, 1, 0).addScaledVector(normal, -normal.y)
  // sin²(30°)=0.25: 板面与铅垂线夹角小于 30°(近水平躺平)时, 投影短到方向不可信
  if (yCm.lengthSq() < 0.25) return null
  yCm.normalize()
  const xCm = new THREE.Vector3().crossVectors(yCm, normal).normalize()
  return { xCm, yCm }
}

/**
 * 功能: 卧式展开的板的 cm 轴世界方向 —— 槽向锚定(gravity 在平躺的板上必然退化).
 *
 * 本机的展缸是**卧式**: 板在缸里平躺(实测缸位锚点姿态法线朝上), 溶剂积在缸一端的
 * 溶液槽里(manifest.tanks[].liquidNode 的液面盒), 经滤芯引到板沿后沿水平方向爬升。
 * 物理事实是: 点样线那条边(cm y=0)贴着槽端, 前沿**背离槽**推进 ——
 * 所以 +y_cm = (板心 − 槽心) 在板面内的投影; +x_cm 由右手系补全(与 gravityDirsWorld
 * 同一条"粉面外法线"约定)。
 *
 * @param {THREE.Quaternion} plateQuatWorld 板根的世界姿态
 * @param {THREE.Vector3|number[]} plateWorldPos 板心世界坐标
 * @param {THREE.Vector3|number[]} troughWorldPos 溶液槽(液面盒)世界坐标
 * @param {boolean} [silicaUp] 粉面是否朝板局部 +Y(缸位是 false)
 * @returns {{xCm: THREE.Vector3, yCm: THREE.Vector3}|null} 槽心与板心几乎重合时 null
 */
export function troughDirsWorld(plateQuatWorld, plateWorldPos, troughWorldPos, silicaUp = false) {
  if (!plateQuatWorld || !plateWorldPos || !troughWorldPos) return null
  const toVec = (value) => (Array.isArray(value) ? new THREE.Vector3(...value) : value.clone())
  const normal = new THREE.Vector3(0, silicaUp ? 1 : -1, 0).applyQuaternion(plateQuatWorld)
  const away = toVec(plateWorldPos).sub(toVec(troughWorldPos))
  const yCm = away.addScaledVector(normal, -away.dot(normal))
  // 槽在板沿之外 ~10cm 量级; 投影短于 5mm 说明数据不对, 宁可留白
  if (yCm.lengthSq() < 0.005 * 0.005) return null
  yCm.normalize()
  const xCm = new THREE.Vector3().crossVectors(yCm, normal).normalize()
  return { xCm, yCm }
}

/**
 * 功能: 把板 cm 帧的条带矩形换算成硅胶面 UV 矩形 + 前沿推进方向.
 *
 * 纯函数: 只吃姿态与声明, 不碰场景. 板局部 +X/+Z 的世界向量与机床方向点积,
 * |dot| 最大者定轴、符号定向; 两根 cm 轴必须落在**不同**的板局部轴上, 且对齐度
 * ≥ cos 30°, 否则返回 null —— 摆到一个猜的方向比不画更坏(与 PlateStage.show 的
 * 留白纪律同源).
 *
 * @param {object} region compiled.scrapeRegions 的一项
 *        {plateSizeCm:[2], bandCm:[x0,y0,x1,y1], loosen:{axis,dir}, clear:{axis,dir}}
 * @param {THREE.Quaternion} plateQuatWorld 板根的世界姿态
 * @param {{xCm: THREE.Vector3, yCm: THREE.Vector3}} dirs machineDirsWorld 的结果
 * @returns {{u0:number, v0:number, u1:number, v1:number,
 *            loosen:{coord:'u'|'v', dir:1|-1}, clear:{coord:'u'|'v', dir:1|-1}}|null}
 */
export function bandToUv(region, plateQuatWorld, dirs) {
  const size = region?.plateSizeCm
  const band = region?.bandCm
  if (!Array.isArray(size) || size.length !== 2 || !Array.isArray(band) || band.length !== 4) {
    return null
  }
  if (!plateQuatWorld || !dirs?.xCm || !dirs?.yCm) return null
  if (!(Number(size[0]) > 0) || !(Number(size[1]) > 0)) return null

  const axes = cmAxesUv(plateQuatWorld, dirs)
  if (!axes) return null
  const { ux, uy } = axes

  const range = { u: [0, 1], v: [0, 1] }
  const put = (m, f0, f1) => {
    const p0 = m.a * f0 + m.b
    const p1 = m.a * f1 + m.b
    range[m.coord] = [Math.min(p0, p1), Math.max(p0, p1)]
  }
  put(ux, Number(band[0]) / Number(size[0]), Number(band[2]) / Number(size[0]))
  put(uy, Number(band[1]) / Number(size[1]), Number(band[3]) / Number(size[1]))

  // 前沿: region 声明它沿 cm 的哪根轴、朝哪个方向推进; 换到 UV 后方向要乘映射的符号
  const frontOf = (spec) => {
    const m = spec?.axis === 'y' ? uy : ux
    return { coord: m.coord, dir: (Number(spec?.dir) < 0 ? -1 : 1) * (m.a > 0 ? 1 : -1) }
  }
  const out = {
    u0: range.u[0],
    v0: range.v[0],
    u1: range.u[1],
    v1: range.v[1],
    loosen: frontOf(region?.loosen),
    clear: frontOf(region?.clear),
  }
  // spot/wet 的渐进方向走同一条换算; 没声明就不带出 —— scrape 的调用方不受影响
  if (region?.fill) out.fill = frontOf(region.fill)
  return out
}

/**
 * 功能: cm 轴 → 硅胶面 UV 的仿射(bandToUv 与 pathToUv 共用的那一跳).
 *
 * 板局部 +X/+Z 的世界向量与 cm 轴方向点积, |dot| 最大者定轴、符号定向; 两根 cm 轴
 * 必须落在**不同**的板局部轴上, 且对齐度 ≥ cos 30°, 否则返回 null —— 摆到一个猜的
 * 方向比不画更坏(与 PlateStage.show 的留白纪律同源).
 *
 * @param {THREE.Quaternion} plateQuatWorld 板根的世界姿态
 * @param {{xCm: THREE.Vector3, yCm: THREE.Vector3}} dirs cm 轴的世界方向
 * @returns {{ux: {coord: 'u'|'v', a: number, b: number},
 *            uy: {coord: 'u'|'v', a: number, b: number}}|null}
 *          uv = a·f + b(f 是 cm 坐标的板上归一分数, 自 cm 原点边起)
 */
function cmAxesUv(plateQuatWorld, dirs) {
  if (!plateQuatWorld || !dirs?.xCm || !dirs?.yCm) return null
  const localX = new THREE.Vector3(1, 0, 0).applyQuaternion(plateQuatWorld)
  const localZ = new THREE.Vector3(0, 0, 1).applyQuaternion(plateQuatWorld)

  const match = (dirWorld) => {
    const dx = dirWorld.dot(localX)
    const dz = dirWorld.dot(localZ)
    const pick = Math.abs(dx) >= Math.abs(dz) ? { local: 'x', dot: dx } : { local: 'z', dot: dz }
    if (Math.abs(pick.dot) < AXIS_ALIGN_MIN) return null
    return { local: pick.local, positive: pick.dot > 0 }
  }
  const mx = match(dirs.xCm)
  const my = match(dirs.yCm)
  if (!mx || !my || mx.local === my.local) return null

  // 局部轴 → UV 的仿射:
  //   cm 轴 ↔ +x: u=f;  ↔ −x: u=1−f;  ↔ +z: v=1−f;  ↔ −z: v=f
  // (BoxGeometry py 面: u 随 +x 增, v 随 +z 减)
  const toUv = (m) => {
    if (m.local === 'x') return m.positive ? { coord: 'u', a: 1, b: 0 } : { coord: 'u', a: -1, b: 1 }
    return m.positive ? { coord: 'v', a: -1, b: 1 } : { coord: 'v', a: 1, b: 0 }
  }
  return { ux: toUv(mx), uy: toUv(my) }
}

/**
 * 功能: 把板 cm 帧的折线(实际刮取刀路)换算成硅胶面 UV 折线.
 *
 * 与 bandToUv 走同一个 cmAxesUv 仿射, 所以两者的对齐门槛、镜像符号严格一致 ——
 * 各推一遍迟早漂, 漂了只表现为"刀痕与色带错位", 没有指标会报.
 *
 * @param {number[][]} pointsCm 折线点列 [[x_cm, y_cm], ...]
 * @param {number[]} plateSizeCm 板尺寸 [宽, 高](cm)
 * @param {THREE.Quaternion} plateQuatWorld 板根的世界姿态
 * @param {{xCm: THREE.Vector3, yCm: THREE.Vector3}} dirs machineDirsWorld/gravityDirsWorld 的结果
 * @returns {{points: Array<{u: number, v: number}>}|null} 对不齐/入参非法时 null(留白)
 */
export function pathToUv(pointsCm, plateSizeCm, plateQuatWorld, dirs) {
  if (!Array.isArray(pointsCm) || pointsCm.length < 2) return null
  const size = plateSizeCm
  if (!Array.isArray(size) || !(Number(size[0]) > 0) || !(Number(size[1]) > 0)) return null
  const axes = cmAxesUv(plateQuatWorld, dirs)
  if (!axes) return null
  const points = []
  for (const point of pointsCm) {
    const fx = Number(point?.[0]) / Number(size[0])
    const fy = Number(point?.[1]) / Number(size[1])
    if (!Number.isFinite(fx) || !Number.isFinite(fy)) return null
    const mapped = {}
    mapped[axes.ux.coord] = axes.ux.a * fx + axes.ux.b
    mapped[axes.uy.coord] = axes.uy.a * fy + axes.uy.b
    points.push(mapped)
  }
  return { points }
}

/**
 * 功能: 由两个前沿进度算出当前该画的两个 UV 子矩形(幂等纯函数).
 *
 * dir=+1 的前沿从矩形低端(u0/v0)起步, dir=−1 从高端(u1/v1)起步 —— 收集回扫
 * 就是靠后者表达"桶从条带末端往回吃"的.
 *
 * @param {object} uvBand bandToUv 的结果
 * @param {number} loosen 刮松进度 0..1
 * @param {number} clear 收粉进度 0..1
 * @returns {{loosen: object|null, clear: object|null}} 为 null 表示该层什么都不画
 */
export function scrapeRects(uvBand, loosen, clear) {
  return {
    loosen: progressRect(uvBand, uvBand?.loosen, loosen),
    clear: progressRect(uvBand, uvBand?.clear, clear),
  }
}

/**
 * 功能: 按前沿进度裁一个 UV 矩形(scrape 前沿 / spot 渐现 / wet 上行共用的纯函数).
 *
 * dir=+1 的前沿从矩形低端(u0/v0)起步, dir=−1 从高端(u1/v1)起步.
 *
 * @param {object} rect 全量 UV 矩形 {u0,v0,u1,v1}
 * @param {{coord: 'u'|'v', dir: 1|-1}|null} front 前沿描述(缺省沿 u、+向)
 * @param {number} progress 进度 0..1
 * @returns {object|null} 裁出的子矩形; 进度 0 时 null(什么都不画)
 */
export function progressRect(rect, front, progress) {
  const value = Math.min(1, Math.max(0, Number(progress) || 0))
  if (!rect || !(value > 0)) return null
  const full = { u0: rect.u0, v0: rect.v0, u1: rect.u1, v1: rect.v1 }
  if (value >= 1) return full
  const along = front?.coord === 'v' ? 'v' : 'u'
  const lo = along === 'u' ? full.u0 : full.v0
  const hi = along === 'u' ? full.u1 : full.v1
  const out = { ...full }
  if ((front?.dir ?? 1) >= 0) {
    const edge = lo + (hi - lo) * value
    if (along === 'u') out.u1 = edge
    else out.v1 = edge
  } else {
    const edge = hi - (hi - lo) * value
    if (along === 'u') out.u0 = edge
    else out.v0 = edge
  }
  return out
}

/**
 * 功能: 按前沿进度算出"一个圆点滑过留下的轨迹"(点样色带专用的纯函数).
 *
 * 与 progressRect 的差别只在形状: 那边是矩形的一条边被推着走(方头), 这里是一个
 * 直径=带厚的圆点从起点滑到当前进度处, 轨迹是两端带圆帽的胶囊 —— 喷头在板上划过
 * 就是这个形状。返回值刻意与 drawTrace 的 layers.path 同形({points, widthUv}),
 * 直接喂同一段描边代码, 不另造绘制概念。
 *
 * 圆点中心走的是 [lo+r, hi−r](r=半厚)而不是 [lo, hi]: 圆帽外沿于是恰好贴住 rect
 * 两端, 全程轨迹**恒是原 rect 的子集** —— 与 progressRect"永远画不出带外"这条
 * 不变量对齐, 于是上游声明的 bandCm 仍然等于实际绘出的包络。
 *
 * @param {object} rect 全量 UV 矩形 {u0,v0,u1,v1}
 * @param {{coord: 'u'|'v', dir: 1|-1}|null} front 前沿描述(缺省沿 u、+向, 与 progressRect 同)
 * @param {number} progress 进度 0..1
 * @returns {{points: Array<{u: number, v: number}>, widthUv: number}|null}
 *          进度 0 或入参脏时 null(什么都不画)
 */
export function progressStroke(rect, front, progress) {
  const value = Math.min(1, Math.max(0, Number(progress) || 0))
  if (!rect || !(value > 0)) return null
  const along = front?.coord === 'v' ? 'v' : 'u'
  // 端点次序归一: 跨度本就与次序无关, 反序的 rect 不该算出负线宽(bandToUv 已归一, 这是安全网)
  const u = [Math.min(rect.u0, rect.u1), Math.max(rect.u0, rect.u1)]
  const v = [Math.min(rect.v0, rect.v1), Math.max(rect.v0, rect.v1)]
  const line = along === 'u' ? u : v
  const cross = along === 'u' ? v : u
  const alongSpan = line[1] - line[0]
  const crossSpan = cross[1] - cross[0]
  if (!(alongSpan > 0) || !(crossSpan > 0)) return null
  // 带长比带厚还短时厚度收到带长 —— 否则圆点直径超过带长, 会画到声明的带外去
  const thickness = Math.min(crossSpan, alongSpan)
  const radius = thickness / 2
  const mid = (cross[0] + cross[1]) / 2
  const forward = (front?.dir ?? 1) >= 0
  const from = forward ? line[0] + radius : line[1] - radius
  const to = from + (forward ? 1 : -1) * (alongSpan - thickness) * value
  const at = (pos) => (along === 'u' ? { u: pos, v: mid } : { u: mid, v: pos })
  return { points: [at(from), at(to)], widthUv: thickness }
}

/**
 * 功能: 求条带内"本刀还没扫到"的那一块(= 条带 − 已收矩形), 仍是一个矩形.
 *
 * 成立的前提: scrapeRects 的 sub() 只裁**一条边**(前沿沿单轴推进), 所以补集必然
 * 也是矩形。分层刮取要同时画两级深度(前沿之后=第 k 层, 之前=第 k−1 层), 这块就是后者。
 *
 * @param {object} uvBand bandToUv 的结果
 * @param {object|null} cut scrapeRects(...).clear —— 本刀已收的子矩形
 * @returns {object|null} 未收子矩形; 已全收或没开收时按情况返回 null / 整条带
 */
export function bandComplement(uvBand, cut) {
  if (!uvBand) return null
  const full = { u0: uvBand.u0, v0: uvBand.v0, u1: uvBand.u1, v1: uvBand.v1 }
  if (!cut) return full
  const eps = 1e-6
  const rest = { ...full }
  // 逐边比对: 哪条边被裁了, 补集就顶着那条边的另一侧
  if (cut.u1 < full.u1 - eps) rest.u0 = cut.u1
  else if (cut.u0 > full.u0 + eps) rest.u1 = cut.u0
  else if (cut.v1 < full.v1 - eps) rest.v0 = cut.v1
  else if (cut.v0 > full.v0 + eps) rest.v1 = cut.v0
  else return null // 已收满整条带
  if (rest.u1 - rest.u0 < eps || rest.v1 - rest.v0 < eps) return null
  return rest
}

/**
 * 功能: 由 pass 相位算出两块残余硅胶的**剩余厚度比**(0..1, 1=原厚).
 *
 * 分层刮取: 真机 num_passes 刀、每刀吃 total_depth/N。第 k 刀收粉扫过之后那一段落到
 * 第 k 层(剩 (N−k)/N), 还没扫到的仍停在第 k−1 层(剩 (N−k+1)/N)。只有 k == N 才见玻璃。
 *
 * `pass` 缺省(老片段没有这条通道)时按 **N** 算 —— 那些片段是分层之前编的, 语义就是
 * "clear 到底即露玻璃", 按 N 处理与旧行为逐帧一致。给它补 0 会让老片段永远刮不透。
 *
 * @param {{pass?: number}} phases 相位集
 * @param {number} passes 总刀数(compiled.scrapeRegions[id].passes, 缺省 1)
 * @returns {{pass:number, passes:number, cut:number, prior:number}} 两级剩余厚度比
 */
export function residualLevels(phases, passes) {
  const total = Math.max(1, Math.round(Number(passes) || 1))
  const raw = Number(phases?.pass)
  const pass = Number.isFinite(raw) ? Math.min(total, Math.max(0, Math.round(raw))) : total
  return {
    pass,
    passes: total,
    cut: (total - pass) / total,
    prior: (total - Math.max(0, pass - 1)) / total,
  }
}

/**
 * 功能: 把一个 UV 子矩形换算回**板局部系**的中心与边长(供残余硅胶薄板定位).
 *
 * 映射由 three BoxGeometry 的 +Y 面实测钉死(r180 实跑: 顶面四顶点
 * (x−,z−)→uv(0,1) / (x+,z−)→(1,1) / (x−,z+)→(0,0) / (x+,z+)→(1,0)):
 *   **u 随 +x 增, v 随 +z 减** ⇒ x = (u−0.5)·宽, z = (0.5−v)·长。
 * 这与遮罩用的是同一张 UV, 所以薄板与被 discard 掉的洞天然对齐 —— 两处各推一遍
 * 迟早漂, 且漂了只表现为"薄板与凹坑错位", 没有任何指标会报。
 *
 * @param {object} rect UV 子矩形 {u0,v0,u1,v1}
 * @param {number} widthM 硅胶盒 x 向边长(米)
 * @param {number} lengthM 硅胶盒 z 向边长(米)
 * @returns {{x:number, z:number, width:number, length:number}|null} 板局部系(相对盒中心)
 */
export function uvRectToLocal(rect, widthM, lengthM) {
  if (!rect) return null
  const w = Number(widthM) || 0
  const l = Number(lengthM) || 0
  const width = (rect.u1 - rect.u0) * w
  const length = (rect.v1 - rect.v0) * l
  if (!(width > 0) || !(length > 0)) return null
  return {
    x: ((rect.u0 + rect.u1) / 2 - 0.5) * w,
    z: (0.5 - (rect.v0 + rect.v1) / 2) * l,
    width,
    length,
  }
}

/**
 * 功能: 把一块板的全部痕迹画上遮罩画布(整幅重画, 幂等) —— 痕迹层唯一的合成器.
 *
 * 绘制次序即工艺次序, 后画的压前面的:
 *   1. 白底不透明 = 净板(map 乘 1 不改硅胶基色);
 *   2. 点样色带(橙, 不透明) —— 只动 RGB。扫线带走圆帽描边(一个圆点滑过的轨迹),
 *      视觉实测谱带走矩形(真实斑点 bbox 近似方形, 描边会把它压成胶囊或溢出带外);
 *   3. 润湿区(半透明灰绿罩 + 前沿线) —— 叠在白底/色带上整体压暗, 像素 alpha 仍是 1;
 *   4. 刮松区涂不透明暖灰(alpha 仍 1 不触发 discard);
 *   5. 收粉区 clearRect / 实际刀路 destination-out 描边(alpha=0 → 材质既有的
 *      alphaTest 0.5 discard → 露出下层玻璃盒顶面)。
 * ⚠ alpha 通道的"挖穿"语义**独属刮取**(第 5 层): 色带/润湿若动 alpha 会把板挖穿。
 *
 * UV→画布像素: CanvasTexture 默认 flipY=true, v=1 对应画布**顶行**, 这里统一换算.
 *
 * ⚠ "圆帽画出来是正圆"依赖两个正方: 画布 512×512(_createTrace 的构造保证)与板
 *   plateSizeCm 为正方(当前唯一规格)。cm→uv 是逐轴归一的, 板一旦非方, cm→px 两个
 *   缩放不等, 圆帽落到板上就成椭圆 —— 而 lineWidth 是标量, **没有任何取值能修好**
 *   (同一个坑现已存在于刀路层)。真出非方板时正确的修法是把移动端头改成 ctx.ellipse
 *   单画, 不是调 lineWidth。
 *
 * @param {HTMLCanvasElement} canvas 遮罩画布
 * @param {object} layers 各痕迹层(均可缺省)
 * @param {object[]} [layers.spotStrokes] 点样色带轨迹(progressStroke 的结果, 圆帽描边)
 * @param {object[]} [layers.spotRects] 视觉实测谱带 UV 矩形们(真实斑点 bbox, 仍走矩形)
 * @param {object|null} [layers.wetRect] 润湿区 UV 子矩形(已按 front 进度裁好)
 * @param {{coord: 'u'|'v', at: number}|null} [layers.wetFront] 溶剂前沿线(UV 坐标)
 * @param {object|null} [layers.loosen] 刮松 UV 子矩形(scrapeRects 的结果)
 * @param {object|null} [layers.clear] 收粉 UV 子矩形
 * @param {{points: Array<{u,v}>, widthUv: number}|null} [layers.path] 实际刀路折线
 * @returns {void}
 */
export function drawTrace(canvas, layers = {}) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const width = canvas.width
  const height = canvas.height
  ctx.globalCompositeOperation = 'source-over'
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)
  const toPx = (rect) => ({
    x: rect.u0 * width,
    y: (1 - rect.v1) * height,
    w: (rect.u1 - rect.u0) * width,
    h: (rect.v1 - rect.v0) * height,
  })
  for (const rect of layers.spotRects || []) {
    if (!rect) continue
    const px = toPx(rect)
    ctx.fillStyle = SPOT_BAND_FILL
    ctx.fillRect(px.x, px.y, px.w, px.h)
  }
  for (const seg of layers.spotStrokes || []) {
    if (!seg) continue
    strokePath(ctx, seg, width, height, SPOT_BAND_FILL, 'source-over')
  }
  if (layers.wetRect) {
    const px = toPx(layers.wetRect)
    ctx.fillStyle = WET_FILL
    ctx.fillRect(px.x, px.y, px.w, px.h)
    const front = layers.wetFront
    if (front) {
      // 前沿线画在推进沿上, 2px 细线; 干燥后前沿在真板上也留界线, 进度=1 照画
      ctx.fillStyle = WET_FRONT_LINE
      if (front.coord === 'v') ctx.fillRect(px.x, (1 - front.at) * height - 1, px.w, 2)
      else ctx.fillRect(front.at * width - 1, px.y, 2, px.h)
    }
  }
  if (layers.loosen) {
    const px = toPx(layers.loosen)
    ctx.fillStyle = SCRAPE_LOOSEN_FILL
    ctx.fillRect(px.x, px.y, px.w, px.h)
  }
  if (layers.clear) {
    const px = toPx(layers.clear)
    ctx.clearRect(px.x, px.y, px.w, px.h)
  }
  // 实际刀路: 沿折线以刀宽描边擦除 alpha —— 蛇形列彼此搭接(overlap_ratio),
  // 合起来就是真机刮出的那块露玻璃区; 圆帽/圆角与铣刀的圆截面一致。
  if (layers.path) strokePath(ctx, layers.path, width, height, '#000000', 'destination-out')
}

/**
 * 功能: UV 折线按线宽圆帽描边(点样色带与实际刀路共用的那一段画布代码).
 *
 * 两家的差别只有颜色与合成模式: 色带 source-over 只动 RGB, 刀路 destination-out
 * 挖 alpha。合成模式用完即复位, 免得漏给后面的层。
 *
 * @param {CanvasRenderingContext2D} ctx 画布上下文
 * @param {{points: Array<{u: number, v: number}>, widthUv: number}} spec UV 折线 + 线宽
 * @param {number} width 画布宽(px)
 * @param {number} height 画布高(px)
 * @param {string} style 描边色
 * @param {string} composite globalCompositeOperation
 * @returns {void}
 */
function strokePath(ctx, spec, width, height, style, composite) {
  const points = spec?.points
  if (!Array.isArray(points) || points.length < 2) return
  ctx.globalCompositeOperation = composite
  ctx.strokeStyle = style
  ctx.lineWidth = Math.max(1, (Number(spec.widthUv) || 0) * width)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.beginPath()
  ctx.moveTo(points[0].u * width, (1 - points[0].v) * height)
  for (let i = 1; i < points.length; i += 1) {
    ctx.lineTo(points[i].u * width, (1 - points[i].v) * height)
  }
  ctx.stroke()
  ctx.globalCompositeOperation = 'source-over'
}

/**
 * 功能: 兼容入口 —— 只画刮取两层(老调用面/老测试), 等价于 drawTrace 的第 4/5 层.
 * @param {HTMLCanvasElement} canvas 遮罩画布
 * @param {{loosen: object|null, clear: object|null}} rects scrapeRects 的结果
 * @returns {void}
 */
export function drawScrape(canvas, rects) {
  drawTrace(canvas, { loosen: rects?.loosen || null, clear: rects?.clear || null })
}

/**
 * 功能: 画润湿粗糙度遮罩(roughnessMap 的 G 通道) —— 湿区更光泽的那一半"湿感".
 *
 * 白底 G=1(粗糙度不变); 润湿区涂中灰(G≈0.56 → 粗糙度 0.92→0.52, 湿粉的微弱镜面)。
 * 单独一张画布而不复用颜色遮罩: roughnessMap 采样的是同一张纹理的 G 通道, 复用会让
 * 橙色带(G=0.52)也跟着变光 —— 干燥的样品带不该发亮。
 *
 * @param {HTMLCanvasElement} canvas 粗糙度画布
 * @param {object|null} wetRect 润湿区 UV 子矩形(null = 全干)
 * @returns {void}
 */
export function drawWetRoughness(canvas, wetRect) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.globalCompositeOperation = 'source-over'
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  if (!wetRect) return
  ctx.fillStyle = '#8f8f8f'
  ctx.fillRect(
    wetRect.u0 * canvas.width,
    (1 - wetRect.v1) * canvas.height,
    (wetRect.u1 - wetRect.u0) * canvas.width,
    (wetRect.v1 - wetRect.v0) * canvas.height,
  )
}
