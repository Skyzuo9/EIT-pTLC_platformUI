/**
 * 功能: 板实体层(建板/板池/料仓堆叠/厚度改写)的测试.
 *
 * 两条要害:
 *   1. **料仓里硅胶必须朝下** —— 玻璃面朝上才能给 rotary-down 的吸盘贴。反了的话
 *      吸盘会"吸在硅胶面上", 画面看不出异样, 但语义整条链都错。
 *   2. **料仓节距优先用现场实测值** —— 三维堆高必须与真机 probe_stack 的板数换算同源;
 *      未标定(出厂 pitch_mm=0)时才回退单板总厚。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { PlateFaceLayer } from '../../src/three-d/twin/scene/plates/PlateFaceLayer.js'
import { measurePlateAnchor } from '../../src/three-d/twin/scene/plates/plateGeometry.js'
import { makeQuantizedAnchor, worldSize } from './plateFixtures.js'

/**
 * 造一个**与生产同形态**(量化 SHORT + 节点 scale 0.1 + 薄轴在 Z)的锚点并实测。
 * `silicaUp` 照 plateAnchors 的做法显式带上 —— 料仓是硅胶朝下。
 */
function makeGeom({ y = 0, silicaUp = false } = {}) {
  const { parent, mesh } = makeQuantizedAnchor({ offset: new THREE.Vector3(0, y, 0) })
  const geom = measurePlateAnchor(mesh)
  geom.silicaUp = silicaUp
  return { parent, mesh, geom }
}

/** 读一个 InstancedMesh 实例的 y 与 scale.y。 */
function instanceY(mesh, index) {
  const m = new THREE.Matrix4()
  const pos = new THREE.Vector3()
  const quat = new THREE.Quaternion()
  const scale = new THREE.Vector3()
  mesh.getMatrixAt(index, m)
  m.decompose(pos, quat, scale)
  return { y: pos.y, thick: scale.y }
}

test('建板: 一个 Group 两层, 不透明的硅胶层投影、透射的玻璃层豁免', () => {
  const layer = new PlateFaceLayer()
  const plate = layer.acquire('sample:S-01')
  assert.equal(plate.root.children.length, 2)
  // 决定投影的是板的**投影面积**(整块 200×200mm), 不是 1mm 的层厚。曾按"1mm 层的投影
  // 贡献为零"把两层一起关掉, 表现是板悬在半空没有任何影子, 像一张贴在画面上的白色剪贴画。
  assert.equal(plate.silica.castShadow, true, '硅胶层不透明, 必须投影')
  assert.equal(plate.glass.castShadow, false, '玻璃层 transmission 0.86, 按幽灵件规则豁免')
  assert.equal(plate.glass.receiveShadow, true)
  assert.equal(plate.silica.receiveShadow, true)
  layer.dispose()
})

test('板池: 归还后复用同一批网格, 不反复 new', () => {
  const layer = new PlateFaceLayer()
  const first = layer.acquire('sample:S-01')
  layer.release('sample:S-01')
  const second = layer.acquire('sample:S-02')
  assert.equal(second, first, '应从池里取回同一个实体')
  assert.equal(second.root.name, 'PLATE_sample:S-02')
  assert.equal(layer.plateIds().length, 1)
  layer.dispose()
})

/** 一块板的底面(取两层里更低的那一层的下沿) —— 与硅胶朝上朝下无关。 */
function plateBottom(plate) {
  return Math.min(
    plate.glass.position.y - plate.glass.scale.y / 2,
    plate.silica.position.y - plate.silica.scale.y / 2,
  )
}

test('摆板: 换父到锚点父级并对齐锚点位姿, 两层按实测尺寸铺开', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom({ y: 1.5, silicaUp: true })   // 点样座/刮板台这类落点
  assert.equal(layer.place('sample:S-01', geom), true)

  const plate = layer.get('sample:S-01')
  assert.equal(plate.root.parent, parent)
  assert.ok(Math.abs(plate.root.position.y - 1.5) < 1e-9)
  assert.ok(Math.abs(plate.glass.scale.x - 0.2) < 1e-6)
  assert.ok(Math.abs(plate.glass.scale.y - 0.002) < 1e-12, '玻璃层固定 2mm')
  assert.ok(Math.abs(plate.silica.scale.y - 0.001) < 1e-12, '默认硅胶 1mm')
  assert.ok(plate.silica.position.y > plate.glass.position.y, 'silicaUp 落点上硅胶在玻璃之上')
  layer.dispose()
})

test('改厚度: 只动 scale/position, 且板底面不动(两种朝向都是)', () => {
  for (const silicaUp of [true, false]) {
    const layer = new PlateFaceLayer()
    const { geom } = makeGeom({ silicaUp })
    layer.place('sample:S-01', geom)
    const plate = layer.get('sample:S-01')
    const bottomBefore = plateBottom(plate)

    assert.equal(layer.setSilicaThickness(2.0), true)
    assert.ok(Math.abs(plate.silica.scale.y - 0.002) < 1e-12)
    assert.ok(Math.abs(plateBottom(plate) - bottomBefore) < 1e-12,
      `silicaUp=${silicaUp} 时板底面必须钉住不动`)

    assert.equal(layer.setSilicaThickness(2.0), false, '同值不该触发重写')
    layer.dispose()
  }
})

test('改厚度: 越界被夹取, 总厚随之变', () => {
  const layer = new PlateFaceLayer()
  layer.setSilicaThickness(99)
  assert.equal(layer.silicaMm, 2.0)
  assert.ok(Math.abs(layer.plateThicknessM() - 0.004) < 1e-12)
  layer.setSilicaThickness(0)
  assert.equal(layer.silicaMm, 0.1)
  layer.dispose()
})

test('料仓: 每仓每层一个 InstancedMesh, 满仓也只有 2 个绘制调用', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom()
  layer.setMagazine('feed', { geom, parent, count: 30, pitchM: 0.00285 })
  assert.equal(layer.magazineCount('feed'), 30)
  assert.equal(layer.drawCallEstimate(), 2, '30 张板只吃 2 个绘制调用')

  layer.acquire('sample:S-01')
  assert.equal(layer.drawCallEstimate(), 4, '再加一块活动板(两层)')
  layer.dispose()
})

test('料仓: 硅胶朝下 —— 每张板的硅胶实例都在玻璃实例之下', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom()
  layer.setMagazine('feed', { geom, parent, count: 3, pitchM: 0.00285 })
  const entry = layer._magazines.get('feed')

  for (let i = 0; i < 3; i += 1) {
    const glass = instanceY(entry.glass, i)
    const silica = instanceY(entry.silica, i)
    assert.ok(silica.y < glass.y, `第 ${i} 张: 硅胶必须在玻璃下面(供吸盘从上方贴玻璃)`)
    assert.ok(Math.abs(glass.thick - 0.002) < 1e-9)
    assert.ok(Math.abs(silica.thick - 0.001) < 1e-9)
  }
  layer.dispose()
})

test('料仓: 用现场实测节距堆叠(不是单板名义厚)', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom()
  layer.setMagazine('feed', { geom, parent, count: 3, pitchM: 0.00285 })
  const entry = layer._magazines.get('feed')
  const y0 = instanceY(entry.silica, 0).y
  const y1 = instanceY(entry.silica, 1).y
  assert.ok(Math.abs((y1 - y0) - 0.00285) < 1e-9, '相邻两张的间距应为实测 2.85mm')
  layer.dispose()
})

test('料仓: 未标定(pitch<=0)时回退单板总厚, 不静默用 0 把板叠成一片', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom()
  layer.setMagazine('waste', { geom, parent, count: 2, pitchM: 0 })
  const entry = layer._magazines.get('waste')
  const gap = instanceY(entry.silica, 1).y - instanceY(entry.silica, 0).y
  assert.ok(Math.abs(gap - 0.003) < 1e-9, '出厂 pitch_mm=0 时应退回 2+1=3mm')
  layer.dispose()
})

test('料仓: 张数变化即时反映, 归零后不再画', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom()
  layer.setMagazine('feed', { geom, parent, count: 6, pitchM: 0.00285 })
  assert.equal(layer._magazines.get('feed').glass.count, 6)
  layer.setMagazine('feed', { geom, parent, count: 0, pitchM: 0.00285 })
  assert.equal(layer._magazines.get('feed').glass.count, 0)
  assert.equal(layer.drawCallEstimate(), 0)
  layer.dispose()
})

test('料仓: 张数被夹在合理上限内, 不会因账本异常撑爆实例缓冲', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom()
  layer.setMagazine('feed', { geom, parent, count: 9999, pitchM: 0.00285 })
  assert.ok(layer.magazineCount('feed') <= 40)
  layer.dispose()
})

test('改厚度会同步重写料仓堆叠', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom()
  layer.setMagazine('feed', { geom, parent, count: 2, pitchM: 0 })
  const entry = layer._magazines.get('feed')
  const before = instanceY(entry.silica, 1).y - instanceY(entry.silica, 0).y
  layer.setSilicaThickness(2.0)
  const after = instanceY(entry.silica, 1).y - instanceY(entry.silica, 0).y
  assert.ok(Math.abs(before - 0.003) < 1e-9)
  assert.ok(Math.abs(after - 0.004) < 1e-9, '回退节距应随厚度走')
  layer.dispose()
})

test('dispose: 板归池、实例网格摘除, 共享几何不被销毁', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom()
  layer.place('sample:S-01', geom)
  layer.setMagazine('feed', { geom, parent, count: 3 })
  const stack = layer._magazines.get('feed').glass
  layer.dispose()
  assert.equal(layer.plateIds().length, 0)
  assert.equal(stack.parent, null)
  assert.ok(layer.glassMaterial)   // 材质对象仍在, 只是已 dispose GPU 资源
})

// ── 尺寸: 直接钉死"板被画成一条线"那个 bug ─────────────────────────────────
// 判据用**世界包围盒**而不是内部字段: 量纲错在哪一环都逃不掉这一条。

test('落位后板的世界尺寸就是 200 × 3 × 200 mm(不是一条线)', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom({ silicaUp: true })
  layer.place('p1', geom)
  parent.updateMatrixWorld(true)

  const size = worldSize(layer.get('p1').root)
  assert.ok(Math.abs(size.x - 0.2) < 1e-5, `宽 ${size.x * 1000}mm`)
  assert.ok(Math.abs(size.z - 0.2) < 1e-5, `长 ${size.z * 1000}mm`)
  assert.ok(Math.abs(size.y - 0.003) < 1e-5, `厚 ${size.y * 1000}mm`)
  layer.dispose()
})

test('落位后两层各自的世界厚度 = 2mm 玻璃 + 1mm 硅胶', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom({ silicaUp: true })
  layer.place('p1', geom)
  parent.updateMatrixWorld(true)

  const glass = worldSize(layer.get('p1').glass)
  const silica = worldSize(layer.get('p1').silica)
  assert.ok(Math.abs(glass.y - 0.002) < 1e-6, `玻璃层 ${glass.y * 1000}mm`)
  assert.ok(Math.abs(silica.y - 0.001) < 1e-6, `硅胶层 ${silica.y * 1000}mm`)
  // 面内尺寸两层一致, 不许一层缩水
  assert.ok(Math.abs(glass.x - silica.x) < 1e-9 && Math.abs(glass.z - silica.z) < 1e-9)
  layer.dispose()
})

test('板中心落在锚点盒心上(不因盒心偏移而侧移)', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom({ y: 1.5 })
  layer.place('p1', geom)
  parent.updateMatrixWorld(true)
  const center = layer.get('p1').root.getWorldPosition(new THREE.Vector3())
  assert.ok(center.distanceTo(new THREE.Vector3(0, 1.5, 0)) < 1e-6, `${center.toArray()}`)
  layer.dispose()
})

test('从未 place 过的板也是标准板尺寸, 不是一米见方的单位盒', () => {
  const layer = new PlateFaceLayer()
  const plate = layer.acquire('sample:S-01')
  const holder = new THREE.Group()
  holder.add(plate.root)
  holder.updateMatrixWorld(true)
  const size = worldSize(plate.root)
  assert.ok(size.x < 0.3 && size.z < 0.3, `兜底尺寸不该是米级: ${size.toArray()}`)
  assert.ok(Math.abs(size.x - 0.2) < 1e-9 && Math.abs(size.y - 0.003) < 1e-9)
  layer.dispose()
})

test('料仓堆叠: 每张都是 200×200 的方板, 不是长条', () => {
  const layer = new PlateFaceLayer()
  const { parent, geom } = makeGeom()
  layer.setMagazine('feed', { geom, parent, count: 5, pitchM: 0.00285 })
  parent.updateMatrixWorld(true)
  const entry = layer._magazines.get('feed')

  const m = new THREE.Matrix4()
  const pos = new THREE.Vector3()
  const quat = new THREE.Quaternion()
  const scale = new THREE.Vector3()
  entry.glass.getMatrixAt(0, m)
  m.decompose(pos, quat, scale)
  assert.ok(Math.abs(scale.x - 0.2) < 1e-5, `单张宽 ${scale.x * 1000}mm`)
  assert.ok(Math.abs(scale.z - 0.2) < 1e-5, `单张长 ${scale.z * 1000}mm`)
  assert.ok(Math.abs(scale.y - 0.002) < 1e-9, '玻璃层 2mm')

  // 整堆的世界高度 ≈ (count-1)*pitch + 单板总厚
  const stack = worldSize(entry.glass)
  assert.ok(Math.abs(stack.x - 0.2) < 1e-5, `堆叠面内宽 ${stack.x * 1000}mm`)
  layer.dispose()
})

test('料仓堆叠: 锚点带旋转时整堆跟着转, 不飞到别处', () => {
  const layer = new PlateFaceLayer()
  const { parent, mesh } = makeQuantizedAnchor({ offset: new THREE.Vector3(0.4, 0.8, -0.2) })
  // 让标准帧不再是单位阵: 父级整体转 90°
  parent.rotateY(Math.PI / 2)
  parent.updateMatrixWorld(true)
  const geom = measurePlateAnchor(mesh)
  geom.silicaUp = false

  layer.setMagazine('feed', { geom, parent, count: 2, pitchM: 0.003 })
  parent.updateMatrixWorld(true)
  const entry = layer._magazines.get('feed')

  const m = new THREE.Matrix4()
  const pos = new THREE.Vector3()
  entry.glass.getMatrixAt(0, m)
  pos.setFromMatrixPosition(m).applyMatrix4(entry.glass.matrixWorld)
  const anchorWorld = mesh.getWorldPosition(new THREE.Vector3())
  assert.ok(pos.distanceTo(anchorWorld) < 0.01,
    `第一张应落在锚点附近(相距 ${(pos.distanceTo(anchorWorld) * 1000).toFixed(1)}mm)`)
  layer.dispose()
})

// ── 补光打在板上 ───────────────────────────────────────────────────────────
// 那盏补光灯在机台盖板玻璃下方 44.5mm, 灯本体从任何正常机位都被台面挡着(实测开/关
// 两态画面几乎无差)。所以"闪光"看得见的形态是**板面提亮** —— 这几条钉住它。

test('补光: 硅胶面按 0..1 提亮, 玻璃层不动', () => {
  const layer = new PlateFaceLayer()
  const glassBefore = layer.glassMaterial.emissiveIntensity

  assert.equal(layer.setFlash(1), true)
  assert.ok(layer.silicaMaterial.emissiveIntensity > 0, '硅胶面应发亮')
  assert.equal(layer.glassMaterial.emissiveIntensity, glassBefore, '玻璃层不该跟着亮(透射层提亮只会发灰)')

  assert.equal(layer.setFlash(0), true)
  assert.equal(layer.silicaMaterial.emissiveIntensity, 0)
  layer.dispose()
})

test('补光: 越界夹到 0..1, 同值不重复写', () => {
  const layer = new PlateFaceLayer()
  layer.setFlash(5)
  const peak = layer.silicaMaterial.emissiveIntensity
  assert.ok(peak > 0 && peak < 1, `峰值应克制(避免顶到色调映射削波), 实际 ${peak}`)
  assert.equal(layer.setFlash(5), false, '同值不该触发重写')
  layer.setFlash(-1)
  assert.equal(layer.silicaMaterial.emissiveIntensity, 0)
  layer.dispose()
})

test('补光强度与亮度成正比(供片段做渐亮/熄灭)', () => {
  const layer = new PlateFaceLayer()
  layer.setFlash(1)
  const full = layer.silicaMaterial.emissiveIntensity
  layer.setFlash(0.5)
  assert.ok(Math.abs(layer.silicaMaterial.emissiveIntensity - full / 2) < 1e-9)
  layer.dispose()
})

// ── 刮取遮罩(applyScrape) ──────────────────────────────────────────────────
// 两条纪律的落点: ①共享硅胶材质不许被碰(three_d/docs/CLAUDE.md 第 12 条), 被刮那块
// 板必须换克隆; ②资源走池, release 还原 —— 向后 seek 每次都经 release→重放, 逐次
// 销毁会 GC 抖动, 留着不还原则"下一块板带着上一块的刮痕出场"。

/** 记录式画布工厂(node 无 DOM; 生产画布行为由 verify_scrape_band.py 兜)。 */
function stubCanvasFactory() {
  return () => {
    const ops = []
    const ctx = {
      fillStyle: '',
      strokeStyle: '',
      lineWidth: 0,
      lineCap: '',
      lineJoin: '',
      globalCompositeOperation: '',
      fillRect(x, y, w, h) { ops.push({ op: 'fill', style: this.fillStyle, x, y, w, h }) },
      clearRect(x, y, w, h) { ops.push({ op: 'clear', x, y, w, h }) },
      beginPath() { ops.push({ op: 'begin' }) },
      moveTo(x, y) { ops.push({ op: 'move', x, y }) },
      lineTo(x, y) { ops.push({ op: 'line', x, y }) },
      stroke() {
        ops.push({
          op: 'stroke',
          mode: this.globalCompositeOperation,
          width: this.lineWidth,
          style: this.strokeStyle,
          cap: this.lineCap,
        })
      },
    }
    return { width: 0, height: 0, ops, getContext: () => ctx }
  }
}

/** 手搓一个已换算好的 uvBand(几何换算的正确性由 scrapeOverlay.test.js 钉)。 */
const UV_BAND = {
  u0: 0.1, v0: 0.4, u1: 0.9, v1: 0.5,
  loosen: { coord: 'u', dir: 1 },
  clear: { coord: 'u', dir: -1 },
}

function scrapeLayer() {
  return new PlateFaceLayer({ canvasFactory: stubCanvasFactory() })
}

test('刮取: 零进度不建资源, 板仍用共享硅胶材质', () => {
  const layer = scrapeLayer()
  const plate = layer.acquire('p1')
  assert.equal(layer.applyScrape('p1', { loosen: 0, clear: 0 }, UV_BAND), false)
  assert.equal(plate.silica.material, layer.silicaMaterial)
  layer.dispose()
})

test('刮取: 首次进度>0 才克隆材质挂遮罩, 共享材质与其他板不受牵连', () => {
  const layer = scrapeLayer()
  const scraped = layer.acquire('p1')
  const bystander = layer.acquire('p2')

  assert.equal(layer.applyScrape('p1', { loosen: 0.5, clear: 0 }, UV_BAND), true)
  const cloned = scraped.silica.material
  assert.notEqual(cloned, layer.silicaMaterial, '被刮的板必须换克隆材质')
  assert.equal(cloned.name, 'MAT_TLC_SILICA_TRACE')
  assert.ok(cloned.map, '克隆材质挂了遮罩贴图')
  assert.equal(cloned.alphaTest, layer.silicaMaterial.alphaTest, 'discard 阈值随克隆保留')
  assert.equal(layer.silicaMaterial.map, null, '共享材质不许被挂上遮罩')
  assert.equal(bystander.silica.material, layer.silicaMaterial, '旁板不受牵连')
  layer.dispose()
})

test('刮取: 同值跳过重画, 值变了才碰画布(每帧调用的幂等门)', () => {
  const layer = scrapeLayer()
  layer.acquire('p1')
  layer.applyScrape('p1', { loosen: 0.5, clear: 0 }, UV_BAND)
  const canvas = layer.get('p1').trace.canvas
  const painted = canvas.ops.length
  assert.equal(layer.applyScrape('p1', { loosen: 0.5, clear: 0 }, UV_BAND), true)
  assert.equal(canvas.ops.length, painted, '同值不许重画')
  layer.applyScrape('p1', { loosen: 0.6, clear: 0 }, UV_BAND)
  assert.ok(canvas.ops.length > painted, '值变了要重画')
  layer.dispose()
})

test('刮取: release 还原共享材质并把资源归池, 复用不新建', () => {
  const layer = scrapeLayer()
  const plate = layer.acquire('p1')
  layer.applyScrape('p1', { loosen: 1, clear: 0.5 }, UV_BAND)
  const cloned = plate.silica.material

  layer.release('p1')
  assert.equal(plate.silica.material, layer.silicaMaterial, '归还后板回到共享材质')
  assert.equal(plate.trace, null)
  assert.equal(layer._tracePool.length, 1, '资源应归池而不是销毁')

  // 池里的板 + 池里的遮罩一起复用: 新板不带旧刮痕(last 已清, 首次写会整幅重画)
  const again = layer.acquire('p2')
  assert.equal(again, plate, '板池复用同一实体')
  assert.equal(again.silica.material, layer.silicaMaterial, '复用的板出场时是干净的')
  layer.applyScrape('p2', { loosen: 0.2, clear: 0 }, UV_BAND)
  assert.equal(again.silica.material, cloned, '遮罩资源从池里复用, 不再克隆')
  assert.equal(layer._tracePool.length, 0)
  layer.dispose()
})

test('刮取: 补光要同时写到克隆材质(闪光不许漏掉被刮的板)', () => {
  const layer = scrapeLayer()
  layer.acquire('p1')
  layer.applyScrape('p1', { loosen: 0.5, clear: 0 }, UV_BAND)
  const cloned = layer.get('p1').trace.material

  layer.setFlash(1)
  assert.ok(cloned.emissiveIntensity > 0, '补光要落在克隆材质上')
  assert.equal(cloned.emissiveIntensity, layer.silicaMaterial.emissiveIntensity)
  layer.setFlash(0)
  assert.equal(cloned.emissiveIntensity, 0)

  // 反向时序: 先有补光、后开刮 —— 克隆在取用时要接住当下亮度
  layer.setFlash(0.8)
  layer.acquire('p2')
  layer.applyScrape('p2', { loosen: 0.3, clear: 0 }, UV_BAND)
  const late = layer.get('p2').trace.material
  assert.equal(late.emissiveIntensity, layer.silicaMaterial.emissiveIntensity,
    '开刮晚于补光时, 克隆材质要接住当下亮度')
  layer.dispose()
})

test('刮取: dispose 连池里的遮罩资源一起销毁', () => {
  const layer = scrapeLayer()
  layer.acquire('p1')
  layer.applyScrape('p1', { loosen: 1, clear: 1 }, UV_BAND)
  layer.dispose()
  assert.equal(layer._tracePool.length, 0, 'dispose 后池必须清空')
})

// ── 痕迹层扩展: 点样色带 / 溶剂润湿 / 实际刀路 ─────────────────────────────
// 与刮取共用同一份克隆材质与画布(_recompose 整幅合成), 所以资源纪律逐条同上:
// 零进度不建资源、幂等门、release 归池复位。

const SPOT_UV = { u0: 0.08, v0: 0.1, u1: 0.93, v1: 0.145, fill: { coord: 'u', dir: 1 } }
const WET_UV = { u0: 0, v0: 0, u1: 1, v1: 0.735, fill: { coord: 'v', dir: 1 } }

test('点样: 零进度不建资源; 渐现后画布出现色带橙, 同值跳过重画', () => {
  const layer = scrapeLayer()
  layer.acquire('p1')
  assert.equal(layer.applySpot('p1', [{ uv: SPOT_UV, fill: 0 }]), false, '全零不建')
  assert.equal(layer.get('p1').trace, null)

  assert.equal(layer.applySpot('p1', [{ uv: SPOT_UV, fill: 0.5 }]), true)
  const entry = layer.get('p1').trace
  assert.ok(entry, '首个非零进度建资源')
  // 扫线带是"一个圆点滑过"的圆帽描边, 不是矩形 —— 厚度取垂直于前沿的 v 跨度
  const bandStrokes = entry.canvas.ops.filter((op) => op.op === 'stroke' && op.style === '#ff8436')
  assert.equal(bandStrokes.length, 1, '画布上应有一笔色带橙描边')
  assert.equal(bandStrokes[0].cap, 'round', '圆帽')
  assert.ok(Math.abs(bandStrokes[0].width - (0.145 - 0.1) * entry.canvas.width) < 1e-6,
    '线宽 = 带厚 × 画布')
  // 圆点中心从 u0+r 滑到半程: r=0.0225, 行程 = (0.93−0.08)−0.045
  const move = entry.canvas.ops.find((op) => op.op === 'move')
  const line = entry.canvas.ops.find((op) => op.op === 'line')
  assert.ok(Math.abs(move.x - 0.1025 * entry.canvas.width) < 1e-6, '起点内缩半个厚度')
  assert.ok(Math.abs(line.x - (0.1025 + 0.805 * 0.5) * entry.canvas.width) < 1e-6,
    '半程渐现只滑一半行程')
  assert.ok(Math.abs(move.y - line.y) < 1e-9, '中心线沿 u, v 恒为带中心')

  const opsBefore = entry.canvas.ops.length
  assert.equal(layer.applySpot('p1', [{ uv: SPOT_UV, fill: 0.5 }]), true)
  assert.equal(entry.canvas.ops.length, opsBefore, '同值跳过重画(幂等门)')
  layer.dispose()
})

test('点样: shape=rect 的条带仍走矩形(视觉实测谱带 bbox 不能被压成胶囊)', () => {
  const layer = scrapeLayer()
  layer.acquire('p1')
  // 真实斑点 bbox 近似方形, 且没有 fill 前沿声明 —— 这一路由 PlateBinding 显式点名
  const factBand = { u0: 0.3, v0: 0.3, u1: 0.4, v1: 0.42 }
  assert.equal(layer.applySpot('p1', [{ uv: factBand, fill: 1, shape: 'rect' }]), true)
  const entry = layer.get('p1').trace
  const fills = entry.canvas.ops.filter((op) => op.op === 'fill' && op.style === '#ff8436')
  assert.equal(fills.length, 1, '应有一笔矩形色带橙')
  assert.equal(entry.canvas.ops.filter((op) => op.op === 'stroke').length, 0, '不该走描边')
  assert.ok(Math.abs(fills[0].w - 0.1 * entry.canvas.width) < 1e-6, '整块 bbox 铺满')
  assert.ok(Math.abs(fills[0].h - 0.12 * entry.canvas.height) < 1e-6)
  // shape 变了必须重画: 幂等门要把它算进比较, 否则分流永远停在第一次的形状上
  const opsBefore = entry.canvas.ops.length
  assert.equal(layer.applySpot('p1', [{ uv: factBand, fill: 1 }]), true)
  assert.ok(entry.canvas.ops.length > opsBefore, 'shape 改变要触发重画')
  assert.equal(entry.canvas.ops.filter((op) => op.op === 'stroke').length, 1, '改回默认走描边')
  layer.dispose()
})

test('润湿: 首次润湿挂 roughnessMap(线性, 不设 SRGB), 归池白化不摘图', () => {
  const layer = scrapeLayer()
  layer.acquire('p1')
  assert.equal(layer.applyWet('p1', 0, WET_UV), false, '干板不建资源')
  assert.equal(layer.applyWet('p1', 0.6, WET_UV), true)
  const entry = layer.get('p1').trace
  assert.ok(entry.wetTexture, '润湿建第二张画布')
  assert.equal(entry.material.roughnessMap, entry.wetTexture, '克隆材质挂 roughnessMap')
  assert.notEqual(entry.wetTexture.colorSpace, THREE.SRGBColorSpace, '粗糙度是线性数据')
  const wetOps = entry.wetCanvas.ops.filter((op) => op.op === 'fill' && op.style === '#8f8f8f')
  assert.equal(wetOps.length, 1, '粗糙度画布上有湿区中灰')

  // 归池再取: 粗糙度画布白化(全干), roughnessMap 不摘(避免材质程序重编译抖动)
  layer.release('p1')
  layer.acquire('p2')
  assert.equal(layer.applySpot('p2', [{ uv: SPOT_UV, fill: 1 }]), true)
  const reused = layer.get('p2').trace
  assert.equal(reused, entry, '资源应复用')
  assert.equal(reused.material.roughnessMap, reused.wetTexture, 'roughnessMap 保持在位')
  const lastWet = reused.wetCanvas.ops[reused.wetCanvas.ops.length - 1]
  assert.equal(lastWet.style, '#ffffff', '归池后湿区粗糙度已白化')
  layer.dispose()
})

test('实际刀路: 沿折线以刀宽擦除(destination-out), 与色带同画布合成', () => {
  const layer = scrapeLayer()
  layer.acquire('p1')
  layer.applySpot('p1', [{ uv: SPOT_UV, fill: 1 }])
  const path = { points: [{ u: 0.1, v: 0.45 }, { u: 0.9, v: 0.45 }], widthUv: 0.01 }
  assert.equal(layer.applyScrapePath('p1', path), true)
  const entry = layer.get('p1').trace
  const stroke = entry.canvas.ops.filter((op) => op.op === 'stroke').pop()
  assert.ok(stroke, '刀路应描边')
  assert.equal(stroke.mode, 'destination-out', '描边即擦除(露玻璃)')
  const lastBand = entry.canvas.ops.filter((op) => op.op === 'stroke' && op.style === '#ff8436').pop()
  assert.ok(lastBand, '重画合成后色带仍在(刀路擦掉的只是折线覆盖处)')
  assert.equal(lastBand.mode, 'source-over', '色带只动 RGB —— 挖 alpha 的语义独属刮取')

  assert.equal(layer.applyScrapePath('p1', path), true)
  const cuts = entry.canvas.ops.filter((op) => op.op === 'stroke' && op.mode === 'destination-out')
  assert.equal(cuts.length, 1, '同一份路径对象不重画(幂等门)')
  layer.dispose()
})

test('release 复位全部痕迹: 下一块板不携带色带/湿区/刀路出场', () => {
  const layer = scrapeLayer()
  layer.acquire('p1')
  layer.applySpot('p1', [{ uv: SPOT_UV, fill: 1 }])
  layer.applyWet('p1', 1, WET_UV)
  layer.applyScrapePath('p1', { points: [{ u: 0.1, v: 0.4 }, { u: 0.9, v: 0.4 }], widthUv: 0.01 })
  layer.release('p1')

  layer.acquire('p2')
  const plate = layer.get('p2')
  assert.equal(plate.trace, null, '新板出场无痕迹资源')
  // 从池里复取的资源, 状态槽必须已清空
  layer.applyScrape('p2', { loosen: 0.3, clear: 0 }, UV_BAND)
  const entry = plate.trace
  assert.equal(entry.spot, null)
  assert.equal(entry.wet, null)
  assert.equal(entry.path, null)
  layer.dispose()
})

// ── 语义标签 ───────────────────────────────────────────────────────────────
// 动作页语义着色(motion/MotionPaint.js)靠 __ptlcSemantic 标签认领程序化板:
// 板不在 manifest 的 glbNodes 子树里(锚点模板被隐藏成纯位姿源), 标签丢了就会
// 复现"玻璃板显示透明而非耗材橙"那个 bug. 这里钉住写方.

test('语义标签: 单板两层 + 料仓堆叠 + 残余硅胶全部带耗材标签', () => {
  const layer = scrapeLayer()
  const plate = layer.acquire('p1')
  assert.equal(plate.glass.userData.__ptlcSemantic, 'consumable')
  assert.equal(plate.silica.userData.__ptlcSemantic, 'consumable')

  const { parent, geom } = makeGeom()
  layer.setMagazine('feed', { geom, parent, count: 3, pitchM: 0.00285 })
  const stack = layer._magazines.get('feed')
  assert.equal(stack.glass.userData.__ptlcSemantic, 'consumable', '堆叠玻璃层(InstancedMesh)')
  assert.equal(stack.silica.userData.__ptlcSemantic, 'consumable', '堆叠硅胶层(InstancedMesh)')

  // 分层刮取(passes>=2)懒建的残余硅胶薄板也是板体的一部分
  layer.applyScrape('p1', { loosen: 1, clear: 0.5, pass: 1 }, UV_BAND, { passes: 2 })
  assert.ok(plate.residual, '两刀制中途应建残余薄板')
  assert.equal(plate.residual.cut.userData.__ptlcSemantic, 'consumable')
  assert.equal(plate.residual.prior.userData.__ptlcSemantic, 'consumable')
  layer.dispose()
})

// ── 阴影标志位 ─────────────────────────────────────────────────────────────
// 三处建板(单板/料仓堆叠/刮取残余)共用 applyShadowFlags 那一条规则: 不透明层投影,
// 透射的玻璃层豁免. 单板那处钉在上面的"建板"用例里, 这里钉另外两处 —— 漏掉任何一处的
// 表现都只是"板悬空没有影子", 不会让别的断言变红, 所以必须显式钉住.

test('阴影标志位: 料仓堆叠与残余硅胶同样是硅胶层投影、玻璃层豁免', () => {
  const layer = scrapeLayer()
  const plate = layer.acquire('p1')

  const { parent, geom } = makeGeom()
  layer.setMagazine('feed', { geom, parent, count: 3, pitchM: 0.00285 })
  const stack = layer._magazines.get('feed')
  assert.equal(stack.silica.castShadow, true, '堆叠硅胶层(InstancedMesh)应投影')
  assert.equal(stack.glass.castShadow, false, '堆叠玻璃层按幽灵件规则豁免')
  assert.equal(stack.silica.receiveShadow, true)

  // 残余薄板与硅胶同物性(cutSilicaMaterial 不透明), 一样投影
  layer.applyScrape('p1', { loosen: 1, clear: 0.5, pass: 1 }, UV_BAND, { passes: 2 })
  assert.equal(plate.residual.cut.castShadow, true)
  assert.equal(plate.residual.prior.castShadow, true)
  layer.dispose()
})
