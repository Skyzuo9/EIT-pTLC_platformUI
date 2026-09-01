/**
 * 功能: 片段里的虚拟板 —— `plate` 原语的校验、执行, 以及 seek 重放的确定性.
 *
 * 钉死三件最容易悄悄坏掉的事:
 *   1. 落点名写错必须**编译期**报错(运行期的表现只是"板没出现", 无从归因);
 *   2. 向后拖进度条不能越拖越多板(home 清场 + 重放的契约);
 *   3. 持板时翻吸盘, 板必须跟着翻 180°(用户第 5 条要求, 由"挂成子级"构造成立)。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { compileClip } from '../../src/three-d/anim/clipSchema.js'
import { PlateFaceLayer } from '../../src/three-d/twin/scene/plates/PlateFaceLayer.js'
import { PlateStage } from '../../src/three-d/twin/scene/plates/PlateStage.js'

const FLIP_PATH = 'ST_TOOLING/夹具总装-1/TOOL_SUCTION/TOOL_SUCTION_GEOMETRY/ACTUATOR_FLIP_SUCTION'
const MANIFEST = { actuators: [{ id: 'rob_flip_suction', node: FLIP_PATH }] }

function anchorMesh() {
  return new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.003, 0.2), new THREE.MeshBasicMaterial())
}

/** 与真实模型同构的最小场景(缸编号刻意用实测的乱序对应)。 */
function makeScene() {
  const root = new THREE.Group()
  const nodeIndex = new Map()
  const add = (path, node, parent) => {
    parent.add(node)
    nodeIndex.set(path, node)
  }

  const tankPairs = [[1, '玻璃-1.010'], [2, '玻璃-1.009'], [3, '玻璃-1.008'], [4, '玻璃-1.011'],
    [5, '玻璃-1.005'], [6, '玻璃-1.004'], [7, '玻璃-1.003'], [8, '玻璃-1.006']]
  for (const [n, part] of tankPairs) {
    const tank = new THREE.Group()
    tank.name = `TANK_${n}`
    root.add(tank)
    const mesh = anchorMesh()
    mesh.name = part
    mesh.position.set(n * 0.3, 0.5, 0)
    add(`ST_DEVELOP/TANK_${n}/${part}`, mesh, tank)
  }

  const seats = [
    ['玻璃-1', '抽液机构总装-1', 'ST_SAMPLING/抽液机构总装-1/玻璃-1', new THREE.Vector3(0, 1, 0)],
    ['玻璃-1.002', '刮板机构总装-1', 'ST_PHOTOSCRAPE/刮板机构总装-1/玻璃-1.002', new THREE.Vector3(1, 1, 0)],
    ['INV_MAGAZINE_FEED_TEMPLATE', '玻璃上料机构-1', 'ST_FEEDLIFT/玻璃上料机构-1/INV_MAGAZINE_FEED_TEMPLATE', new THREE.Vector3(-1, 0.2, 0)],
    ['INV_MAGAZINE_WASTE_TEMPLATE', '玻璃下料机构-1', 'ST_FEEDLIFT/玻璃下料机构-1/INV_MAGAZINE_WASTE_TEMPLATE', new THREE.Vector3(-1.5, 0.2, 0)],
  ]
  for (const [name, parentName, path, pos] of seats) {
    const holder = new THREE.Group()
    holder.name = parentName
    root.add(holder)
    const mesh = anchorMesh()
    mesh.name = name
    mesh.position.copy(pos)
    add(path, mesh, holder)
  }

  // 吸盘翻转节点
  const flip = new THREE.Group()
  flip.name = 'ACTUATOR_FLIP_SUCTION'
  flip.position.set(0.5, 1.2, 0.2)
  root.add(flip)
  nodeIndex.set(FLIP_PATH, flip)

  root.updateMatrixWorld(true)
  return { root, nodeIndex, flip }
}

function makeStage() {
  const scene = makeScene()
  const layer = new PlateFaceLayer({})
  const stage = new PlateStage({ manifest: MANIFEST, nodeIndex: scene.nodeIndex, layer })
  return { ...scene, layer, stage }
}

/** 只有 plate 原语的最小片段(编译期校验用)。 */
function plateClip(body) {
  return { schema: 'ptlc.clip/v1', name: 't', steps: [{ label: 'p', dur: 0, do: { plate: body } }] }
}

// ── 编译期校验 ─────────────────────────────────────────────────────────────

test('plate 原语进了 PRIMITIVES 且能编译成离散事件', () => {
  const compiled = compileClip(plateClip({ id: 'p1', at: 'spot_seat' }))
  assert.equal(compiled.events.length, 1)
  assert.equal(compiled.events[0].kind, 'plate')
  assert.deepEqual(compiled.events[0].payload, { id: 'p1', at: 'spot_seat' })
})

test('落点名写错在编译期就报错, 不留到运行期变成"板没出现"', () => {
  assert.throws(() => compileClip(plateClip({ id: 'p1', at: 'tank:9' })), /不是已知落点/)
  assert.throws(() => compileClip(plateClip({ id: 'p1', at: 'spot_set' })), /不是已知落点/)
})

test('plate 必须有 id 且动作唯一', () => {
  assert.throws(() => compileClip(plateClip({ at: 'spot_seat' })), /缺 id/)
  assert.throws(() => compileClip(plateClip({ id: 'p1' })), /恰好含一个动作/)
  assert.throws(() => compileClip(plateClip({ id: 'p1', at: 'spot_seat', carry: true })), /恰好含一个动作/)
})

test('持板只有 carry: true 一种写法', () => {
  assert.throws(() => compileClip(plateClip({ id: 'p1', at: 'carried' })), /carry: true/)
  assert.doesNotThrow(() => compileClip(plateClip({ id: 'p1', carry: true })))
})

// ── 舞台执行 ───────────────────────────────────────────────────────────────

test('13 个落点全解析到, 缸号按 parent 名反查(不按实例序号)', () => {
  const { stage } = makeStage()
  assert.deepEqual(stage.missing, [])
  assert.equal(stage.anchors.size, 12)   // 4 固定 + 8 缸
  assert.equal(stage.status().suctionBound, true)
})

test('at: 摆到该落点的 CAD 位姿上', () => {
  const { stage, layer } = makeStage()
  assert.equal(stage.show('p1', 'tank:3'), true)
  const root = layer.get('p1').root
  const world = root.getWorldPosition(new THREE.Vector3())
  // tank:3 的锚点是 玻璃-1.008, 摆在 x = 3*0.3
  assert.ok(Math.abs(world.x - 0.9) < 1e-9, `x=${world.x}`)
  assert.ok(Math.abs(world.y - 0.5) < 1e-9, `y=${world.y}`)
})

test('解析不到的落点一块板都不画, 并记进 unresolved', () => {
  const scene = makeScene()
  scene.nodeIndex.delete('ST_DEVELOP/TANK_5/玻璃-1.005')
  const layer = new PlateFaceLayer({})
  const stage = new PlateStage({ manifest: MANIFEST, nodeIndex: scene.nodeIndex, layer })
  assert.ok(stage.missing.includes('tank:5'))
  assert.equal(stage.apply({ id: 'p1', at: 'tank:5' }), false)
  assert.equal(layer.get('p1'), null)
  assert.deepEqual(stage.status().unresolved, ['tank:5'])
})

test('carry: 保世界位姿换父到翻转节点之下', () => {
  const { stage, layer, flip } = makeStage()
  stage.apply({ id: 'p1', at: 'feedlift' })
  const before = layer.get('p1').root.getWorldPosition(new THREE.Vector3())
  assert.equal(stage.apply({ id: 'p1', carry: true }), true)
  const root = layer.get('p1').root
  assert.equal(root.parent, flip)
  const after = root.getWorldPosition(new THREE.Vector3())
  assert.ok(before.distanceTo(after) < 1e-7, `换父当帧不许跳变: ${before.distanceTo(after)}`)
})

test('持板时翻吸盘, 板跟着翻 180°(用户第 5 条: 由挂成子级构造成立)', () => {
  const { stage, layer, flip, root } = makeStage()
  stage.apply({ id: 'p1', at: 'feedlift' })
  stage.apply({ id: 'p1', carry: true })

  const plateRoot = layer.get('p1').root
  const up = new THREE.Vector3(0, 1, 0)
  const before = up.clone().applyQuaternion(plateRoot.getWorldQuaternion(new THREE.Quaternion()))

  flip.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI)
  root.updateMatrixWorld(true)
  const after = up.clone().applyQuaternion(plateRoot.getWorldQuaternion(new THREE.Quaternion()))

  assert.ok(before.dot(after) < -0.999, `法线应完全反向, dot=${before.dot(after)}`)
})

test('hide 收走板; clear 清全场(向后 seek 的重放契约)', () => {
  const { stage, layer } = makeStage()
  stage.apply({ id: 'p1', at: 'spot_seat' })
  stage.apply({ id: 'p2', at: 'tank:1' })
  assert.equal(layer.plateIds().length, 2)

  stage.apply({ id: 'p1', hide: true })
  assert.equal(layer.plateIds().length, 1)

  stage.clear()
  assert.equal(layer.plateIds().length, 0)
  assert.deepEqual(stage.status().rows, [])
})

test('重复 show 同一块板不会长出第二块(拖进度条不越拖越多)', () => {
  const { stage, layer } = makeStage()
  for (let i = 0; i < 5; i += 1) stage.apply({ id: 'p1', at: 'scrape_table' })
  assert.equal(layer.plateIds().length, 1)
  assert.equal(layer.drawCallEstimate(), 2)
})

test('放板: 从手上落回落点时回到 CAD 位姿, 不留示教残差', () => {
  const { stage, layer, flip, root } = makeStage()
  stage.apply({ id: 'p1', at: 'feedlift' })
  stage.apply({ id: 'p1', carry: true })
  flip.position.set(2, 2, 2)          // 机械臂把板带到别处
  root.updateMatrixWorld(true)

  stage.apply({ id: 'p1', at: 'spot_seat' })
  const world = layer.get('p1').root.getWorldPosition(new THREE.Vector3())
  assert.ok(Math.abs(world.x - 0) < 1e-9 && Math.abs(world.y - 1) < 1e-9, `${world.toArray()}`)
})

test('没有吸盘节点时 carry 不生效, 也不炸', () => {
  const scene = makeScene()
  const layer = new PlateFaceLayer({})
  const stage = new PlateStage({ manifest: { actuators: [] }, nodeIndex: scene.nodeIndex, layer })
  assert.equal(stage.suctionNode, null)
  assert.equal(stage.apply({ id: 'p1', carry: true }), false)
})

// ── 真实产物 ───────────────────────────────────────────────────────────────
// 上面那些用例造的是最小场景; 这一组直接吃 sync_ptlc_robot 生成的片段, 防的是
// "单测全绿、页面上一条都装载不了"这类脱节(gripHold 的 args 就这么静默失效过)。

import fs from 'node:fs'
import path from 'node:path'
import { parseClip } from '../../src/three-d/anim/clipSchema.js'

const CLIP_DIR = path.resolve(import.meta.dirname, '../../../three_d/clips')
const CATALOG = path.resolve(import.meta.dirname, '../../../three_d/generated/robot-points.json')
const hasAssets = fs.existsSync(CLIP_DIR) && fs.existsSync(CATALOG)

test('生成的片段全部能被前端编译(含 plate 原语与 staleJointPoints 豁免)', { skip: !hasAssets }, () => {
  const catalog = JSON.parse(fs.readFileSync(CATALOG, 'utf-8'))
  const names = fs.readdirSync(CLIP_DIR).filter((n) => n.endsWith('.yaml'))
  assert.ok(names.length >= 30, `片段太少, 疑似没生成: ${names.length}`)
  for (const name of names) {
    const doc = parseClip(fs.readFileSync(path.join(CLIP_DIR, name), 'utf-8'))
    assert.doesNotThrow(() => compileClip(doc, { pointCatalog: catalog }), `${name} 编译失败`)
  }
})

test('流程片段里板的行踪完整: 上样-上料 = 料仓 → 手上 → 点样座', { skip: !hasAssets }, () => {
  const catalog = JSON.parse(fs.readFileSync(CATALOG, 'utf-8'))
  const file = path.join(CLIP_DIR, 'plate.flow.sampling_load.yaml')
  if (!fs.existsSync(file)) return
  const clip = compileClip(parseClip(fs.readFileSync(file, 'utf-8')), { pointCatalog: catalog })
  const trail = clip.events.filter((e) => e.kind === 'plate')
    .map((e) => e.payload.at || (e.payload.carry ? 'carried' : 'hidden'))
  assert.deepEqual(trail, ['feedlift', 'carried', 'spot_seat'])
  // 板一出场就在, 不是播到一半才冒出来
  assert.equal(clip.events.find((e) => e.kind === 'plate').t, 0)
})

test('片段里的 plate 落点全部在词表内(编译器与前端词表不许漂移)', { skip: !hasAssets }, () => {
  const catalog = JSON.parse(fs.readFileSync(CATALOG, 'utf-8'))
  for (const name of fs.readdirSync(CLIP_DIR).filter((n) => n.startsWith('plate'))) {
    const clip = compileClip(parseClip(fs.readFileSync(path.join(CLIP_DIR, name), 'utf-8')),
      { pointCatalog: catalog })
    for (const event of clip.events.filter((e) => e.kind === 'plate')) {
      if (!event.payload.at) continue
      assert.ok(makeStage().stage.anchors.has(event.payload.at),
        `${name} 引用了解析不到的落点 ${event.payload.at}`)
    }
  }
})

test('锚点解析时按落点写入硅胶朝向(料仓玻璃面朝上供吸盘贴)', { skip: false }, () => {
  const { stage } = makeStage()
  assert.equal(stage.anchors.get('spot_seat').silicaUp, true)
  assert.equal(stage.anchors.get('scrape_table').silicaUp, true)
  assert.equal(stage.anchors.get('feedlift').silicaUp, false)
  assert.equal(stage.anchors.get('waste').silicaUp, false)
  assert.equal(stage.anchors.get('tank:3').silicaUp, false)
})

test('片段里的板是真板不是线: 摆到落点后世界尺寸 200×3×200mm', () => {
  const { stage, layer, root } = makeStage()
  stage.apply({ id: 'p1', at: 'spot_seat' })
  root.updateMatrixWorld(true)
  const size = new THREE.Box3().setFromObject(layer.get('p1').root, true).getSize(new THREE.Vector3())
  assert.ok(Math.abs(size.x - 0.2) < 1e-5 && Math.abs(size.z - 0.2) < 1e-5, `面内 ${size.toArray()}`)
  assert.ok(Math.abs(size.y - 0.003) < 1e-5, `厚度 ${size.y * 1000}mm`)
})

// ── 刀具常量持板(2026-08-05 起的常态路径) ───────────────────────────────────

/**
 * 与管线实测同形的 plateGrip: 两只 SAB22 沿翻转节点局部 −Y 伸出, 唇口平面 y=−71.57mm。
 * 上面的 MANIFEST 刻意**不带**它 —— 那条是老 manifest 的兼容路径, 两条都要有测。
 */
const GRIP = {
  axisLocal: [0, -1, 0],
  contactLocalM: [0, -0.07157172, -0.16254141],
  spanAxisLocal: [0, 0, -1],
  cupCount: 2,
  cupDiameterM: 0.024,
  cupSpanM: 0.085,
}
const MANIFEST_WITH_GRIP = {
  actuators: [{ id: 'rob_flip_suction', node: FLIP_PATH, plateGrip: GRIP }],
}

/**
 * 位姿比对容差(米)。这里的板厚来自**逐顶点实测**的锚点(float32 顶点 => thickM 实为
 * 0.003000000026…), 所以不能拿纯常数的 1e-12 去比 —— 实测残差约 1e-11, 会假红。
 * 1e-9 m = 1 nm: 比任何真实几何误差小六个数量级, 又稳稳高于浮点噪声。
 * 与 plateGeometry.test.js 的 MEASURED_TOL/EXACT 两档同一条理由。
 */
const POSE_TOL_M = 1e-9

function makeGripStage() {
  const scene = makeScene()
  const layer = new PlateFaceLayer({})
  const stage = new PlateStage({
    manifest: MANIFEST_WITH_GRIP, nodeIndex: scene.nodeIndex, layer,
  })
  return { ...scene, layer, stage }
}

test('有刀具常量时: 持板位姿由吸盘几何定, 与板从哪个落点来无关', () => {
  const locals = []
  for (const slot of ['feedlift', 'tank:3', 'waste']) {
    const { stage, layer } = makeGripStage()
    stage.apply({ id: 'p', at: slot })
    stage.apply({ id: 'p', carry: true, from: slot })
    const root = layer.get('p').root
    assert.equal(root.parent.name, 'ACTUATOR_FLIP_SUCTION')
    locals.push(root.position.clone())
  }
  // 三个落点的世界位姿天差地别, 但挂到吸盘下之后的局部位姿必须逐位相同 ——
  // 这正是"保世界位姿换父"做不到的那件事(它会把每站的示教残差各自冻进来)。
  for (const position of locals.slice(1)) {
    assert.ok(position.distanceTo(locals[0]) < POSE_TOL_M,
      `不同落点取板后持板位姿不一致: ${position.toArray()} vs ${locals[0].toArray()}`)
  }
})

test('有刀具常量时: 被吸的玻璃面正落在唇口平面上', () => {
  const { stage, layer } = makeGripStage()
  stage.apply({ id: 'p', at: 'feedlift' })          // 料仓: 硅胶朝下, 玻璃面朝上
  stage.apply({ id: 'p', carry: true, from: 'feedlift' })

  const root = layer.get('p').root
  const axis = new THREE.Vector3().fromArray(GRIP.axisLocal).normalize()
  const contact = new THREE.Vector3().fromArray(GRIP.contactLocalM)
  // 贴合面 = 板局部 +Y 面(玻璃在上), 换算到翻转节点局部系后应当正落在接触点所在平面
  const face = new THREE.Vector3(0, 0.0015, 0)
    .applyQuaternion(root.quaternion).add(root.position)
  const gap = face.clone().sub(contact).dot(axis)
  assert.ok(Math.abs(gap) < POSE_TOL_M, `玻璃面离唇口平面 ${gap} m —— 吸盘会扎穿板面`)
})

test('from 提示定硅胶朝向: 料仓来的板玻璃面朝吸盘, 点样座来的板反过来', () => {
  const faces = {}
  for (const slot of ['feedlift', 'spot_seat']) {
    const { stage, layer } = makeGripStage()
    stage.apply({ id: 'p', at: slot })
    stage.apply({ id: 'p', carry: true, from: slot })
    const root = layer.get('p').root
    faces[slot] = new THREE.Vector3(0, 1, 0).applyQuaternion(root.quaternion)
  }
  // 两个翻转态贴的是板的两个不同面 => 板面法线相对吸盘正好反向
  assert.ok(Math.abs(faces.feedlift.dot(faces.spot_seat) + 1) < 1e-9,
    '两种落点来的板朝向应当相反(吸盘永远贴玻璃面, 而玻璃在哪一侧由落点定)')
})

test('没有刀具常量时: 退回保世界位姿换父(老 manifest 不能崩)', () => {
  const { stage, layer } = makeStage()   // MANIFEST 不带 plateGrip
  stage.apply({ id: 'p', at: 'tank:3' })
  const before = layer.get('p').root.getWorldPosition(new THREE.Vector3())
  stage.apply({ id: 'p', carry: true, from: 'tank:3' })
  const after = layer.get('p').root.getWorldPosition(new THREE.Vector3())
  assert.equal(layer.get('p').root.parent.name, 'ACTUATOR_FLIP_SUCTION')
  assert.ok(before.distanceTo(after) < 1e-9, '兜底路径应当保住世界位姿')
})

// ── 取板持板修正(2026-08-06 第二轮) ─────────────────────────────────────────
//
// 病征与两次误判, 值得原样记着:
//   用户报"升降上料取板瞬间板与料仓厘米级穿模"。
//   第一轮: 量到面内残差 15.08mm, 改成"板坐在落点里时面内归落点、按**法向间距**释放"。
//           没修好 —— 料仓取板后紧接着降轴 5mm 让位, 落点自己跑开、机械臂同时抬,
//           法向间距 0.15s 内涨过窗口, 而板仍被侧壁围着, 于是横扫 14.6mm 进侧壁。
//           ⇒ 判据必须是"**离落点多远**", 不是"法向间距多大"。
//   第二轮: 平移归零后仍剩 36.35mm —— 病根是**姿态**: 该落点法线转角 1.006°, 200mm 板
//           折算到边缘 ±1.75mm, 而板底离 `玻璃放置板` 顶面只有 1.51mm。⇒ 倾角也得保持。
// 真值判据是 probe_plate_overlap.py(全向三角形相交), 不是这几条单测; 这里锁的是机理。

/**
 * 功能: 把翻转节点摆到"canonical 持板位姿 = 落点位姿 + offset"的位置上, 并取板一次.
 *
 * 夹具里 flip 无旋转, 故 世界 = flip.position + 局部。先取一次 canonical 局部位姿 L,
 * 再令 flip.position = 落点世界 A − L + offset, 于是 canonical 世界 = A + offset ——
 * offset 就是"杯相对板心落偏了多少", 正是实测那 4~21mm 的替身。
 *
 * @returns {{stage, layer, flip, root, anchorWorld, anchorQuat}} 已 at + carry 过的舞台
 */
function pickedStage(slot, offset, tiltRad = 0) {
  const scene = makeScene()
  if (tiltRad) {
    // 给落点一点倾角, 复现"落点法线与刀具法线差 1°"那个真实工况(实测 feedlift 1.006°)
    const anchor = scene.nodeIndex.get('ST_FEEDLIFT/玻璃上料机构-1/INV_MAGAZINE_FEED_TEMPLATE')
    anchor.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), tiltRad)
    scene.root.updateMatrixWorld(true)
  }
  const layer = new PlateFaceLayer({})
  // 带上 root: update() 要有 contact 实例才会走"重摆 + 接触"那条生产路径
  const stage = new PlateStage({
    manifest: MANIFEST_WITH_GRIP, nodeIndex: scene.nodeIndex, layer, root: scene.root,
  })
  return pickInto({ ...scene, layer, stage }, slot, offset)
}

function pickInto(rig, slot, offset) {
  const { stage, layer, flip, root } = rig
  stage.apply({ id: 'p', at: slot })
  const plate = layer.get('p').root
  const anchorWorld = plate.getWorldPosition(new THREE.Vector3())
  const anchorQuat = plate.getWorldQuaternion(new THREE.Quaternion())
  stage.apply({ id: 'p', carry: true, from: slot })      // flip 还在原位, 落点远在天边
  const local = plate.position.clone()                   // = canonical L
  stage.apply({ id: 'p', at: slot })                     // 放回落点再正式取一次
  flip.position.copy(anchorWorld).sub(local).add(offset)
  flip.updateMatrixWorld(true)
  root.updateMatrixWorld(true)
  stage.apply({ id: 'p', carry: true, from: slot })
  /**
   * 之后的每一帧走 `update()`, **不是**再 apply 一次 carry ——
   * 真实片段里 carry 只在吸气那一下触发一次, 捕获也只发生那一次; 后续帧由帧钩子调
   * update()。拿 apply 当"推进一帧"会每帧重新捕获, 测出来的就不是生产行为了。
   */
  const tick = () => {
    flip.updateMatrixWorld(true)
    root.updateMatrixWorld(true)
    stage.update()
  }
  return { ...rig, anchorWorld, anchorQuat, tick }
}

test('取板那一帧: 板的世界位姿逐位不变(位置与姿态都不跳)', () => {
  const { layer, stage, anchorWorld, anchorQuat } = pickedStage(
    'feedlift', new THREE.Vector3(0.012, 0.0017, 0.009), 0.0175,
  )
  const plate = layer.get('p').root
  assert.equal(plate.parent.name, 'ACTUATOR_FLIP_SUCTION', '仍必须挂在翻转节点下')
  const world = plate.getWorldPosition(new THREE.Vector3())
  assert.ok(world.distanceTo(anchorWorld) < POSE_TOL_M,
    `取板跳了 ${world.distanceTo(anchorWorld) * 1000}mm, 应当纹丝不动`)
  // 姿态: 只锁**板面法线**。面内偏航是方板的同构自由度, 刀具那侧刻意钉死, 不该被落点改
  const n0 = new THREE.Vector3(0, 1, 0).applyQuaternion(anchorQuat)
  const n1 = new THREE.Vector3(0, 1, 0).applyQuaternion(
    plate.getWorldQuaternion(new THREE.Quaternion()))
  assert.ok(n0.angleTo(n1) < 1e-6,
    `板面法线差 ${THREE.MathUtils.radToDeg(n0.angleTo(n1))}° —— 1° 就够让板角扎进放置板`)
  assert.equal(stage.status().seatHold.source, 'carry')
})

test('取板后在工位范围内怎么动, 板相对吸盘都**恒定不动**(本轮的核心)', () => {
  const rig = pickedStage('feedlift', new THREE.Vector3(0.012, -0.002, 0.009))
  const { layer, stage, flip, tick } = rig
  const held = layer.get('p').root.position.clone()

  // 模拟"上料1Z降轴5mm让位 + 机械臂上抬": 落点跑开、刀具也动, 但都还在工位范围内。
  // 第一轮按法向间距释放, 正是在这三步里把修正泄光、把板横扫 14.6mm 进侧壁的。
  for (const step of [[0, 0.01, 0], [0, 0.03, 0], [0.02, 0.05, -0.02]]) {
    flip.position.add(new THREE.Vector3(...step))
    tick()
    assert.ok(layer.get('p').root.position.distanceTo(held) < POSE_TOL_M,
      '板还在工位里时, 相对吸盘必须一动不动 —— 一动就是横扫进侧壁')
    assert.equal(stage.status().seatHold.weight, 1)
  }
})

test('走到自由空间后: 修正退场, 回到与落点无关的刀具常量位姿', () => {
  const { layer, stage, flip, tick } = pickedStage('feedlift', new THREE.Vector3(0.012, -0.002, 0.009))
  flip.position.y += 0.40          // 远超 CARRY_RELEASE_M
  tick()

  assert.equal(stage.status().seatHold, null, '自由空间里不该再有任何修正')
  const fresh = makeGripStage()
  fresh.stage.apply({ id: 'p', at: 'feedlift' })
  fresh.stage.apply({ id: 'p', carry: true, from: 'feedlift' })
  assert.ok(layer.get('p').root.position.distanceTo(fresh.layer.get('p').root.position) < POSE_TOL_M,
    '退场后必须回到纯刀具常量位姿, 否则各站残差又被冻进运输段')
})

test('权重按**离落点的距离**单调退场, 与法向间距无关', () => {
  // 关键回归: 法向抬得再高, 只要人还在工位范围内, 权重就必须是 1。
  // 第一轮按法向间距释放, 正是在这里泄掉修正、把板横扫进侧壁的。
  const seen = []
  for (const lift of [0, 0.02, 0.10, 0.16, 0.22, 0.30]) {
    const { stage, flip, tick } = pickedStage('feedlift', new THREE.Vector3(0.012, -0.002, 0.009))
    flip.position.y += lift
    tick()
    seen.push(stage.status().seatHold?.weight ?? 0)
  }
  assert.equal(seen[0], 1, '贴着落点时必须满权重')
  assert.equal(seen[1], 1, '抬起 20mm(远超旧的 10mm 法向窗口)时仍必须满权重')
  assert.equal(seen[2], 1, '离落点 100mm 仍在工位范围内')
  assert.equal(seen[5], 0, '离落点 300mm 已是自由空间')
  for (let i = 1; i < seen.length; i += 1) {
    assert.ok(seen[i] <= seen[i - 1] + 1e-12, `权重必须单调不增, 实测 ${seen.join(' > ')}`)
  }
})

test('法向那一份交给吸盘: 板被抬回落点高度, 杯就得多压同样多', () => {
  // offset 的 y 取**负**: 刀具常量把板摆得比落点**低** 1.7mm(实机 1.66mm 就是这个方向),
  // 于是板要被抬回去 1.7mm —— 朝杯体方向, 所以杯必须多压 1.7mm 才还贴着板面。
  const sink = 0.0017
  const { stage } = pickedStage('feedlift', new THREE.Vector3(0.012, -sink, 0.009))
  const extra = stage.status().seatHold.extraCompressionM
  assert.ok(Math.abs(extra - sink) < 1e-6,
    `杯应当多压 ${sink * 1000}mm 才还贴着板面, 实测 ${extra * 1000}mm —— 不透传杯会悬空`)
})

test('放板落座后捕获立即作废(不许留到下一次取板)', () => {
  const { stage } = pickedStage('feedlift', new THREE.Vector3(0.012, 0.002, 0.009))
  assert.ok(stage.carryHold, '取板后应当有捕获')
  stage.apply({ id: 'p', at: 'spot_seat' })
  assert.equal(stage.carryHold, null)
  assert.equal(stage.status().seatHold, null)
})

test('无记忆: 同一姿态经不同路径到达, 持板位姿逐位相同(seek 可复现)', () => {
  const { layer, flip, tick } = pickedStage('feedlift', new THREE.Vector3(0.012, -0.002, 0.009))
  const direct = layer.get('p').root.position.clone()

  // 绕到自由空间(修正退场)再回来。捕获量本身是常数, 权重只由当帧距离算 ——
  // 所以回到同一姿态必须逐位复原。若哪天改成"按时间衰减", 这条立刻红。
  for (const dy of [0.5, -0.5]) {
    flip.position.y += dy
    tick()
  }
  assert.ok(layer.get('p').root.position.distanceTo(direct) < POSE_TOL_M,
    '同一姿态经不同路径到达后必须逐位相同 —— 否则拖进度条会漂')
})

// ── 刮取(setScrape) ────────────────────────────────────────────────────────
// 舞台层管三件事: 落座门槛(板在具体落点上才建 cm→UV 映射)、映射缓存(条带是板的
// 属性, 板被吸走后不许重投影)、留白纪律(方向解析不到就什么都不画并记 unresolved)。

/** 与 clip_compiler 产物同形的条带声明(板 cm 帧)。 */
const SCRAPE_REGION = {
  frame: 'plate-cm',
  plateSizeCm: [20, 20],
  bandCm: [2, 8, 18, 10],
  loosen: { axis: 'x', dir: 1 },
  clear: { axis: 'x', dir: -1 },
}

/** 记录式画布工厂(node 无 DOM)。 */
function scrapeCanvasFactory() {
  return () => {
    const ops = []
    const ctx = {
      fillStyle: '',
      globalCompositeOperation: '',
      fillRect(x, y, w, h) { ops.push({ op: 'fill', style: this.fillStyle, x, y, w, h }) },
      clearRect(x, y, w, h) { ops.push({ op: 'clear', x, y, w, h }) },
    }
    return { width: 0, height: 0, ops, getContext: () => ctx }
  }
}

/**
 * 在 makeScene 的基础上补两根轴的滑车与 manifest.axes(轴向取与真机同构的语义:
 * 9X 沿世界 +X, 8Y 沿世界 +Z —— 恰好与夹具里 scrape_table 锚点的无旋转姿态正交)。
 */
function makeScrapeStage() {
  const scene = makeScene()
  for (const [leaf, path] of [['CARR9', 'ST_PS/AXIS_9X/CARR9'], ['CARR8', 'ST_PS/AXIS_8Y/CARR8']]) {
    const parent = new THREE.Group()
    const carriage = new THREE.Group()
    carriage.name = leaf
    parent.add(carriage)
    scene.root.add(parent)
    scene.nodeIndex.set(path, carriage)
    scene.nodeIndex.set(leaf, carriage)
  }
  scene.root.updateMatrixWorld(true)
  const manifest = {
    ...MANIFEST,
    axes: [
      { id: 'axis_9x', axis: [1, 0, 0], sign: 1, glbNode: 'ST_PS/AXIS_9X/CARR9' },
      { id: 'axis_8y', axis: [0, 0, 1], sign: 1, glbNode: 'ST_PS/AXIS_8Y/CARR8' },
    ],
  }
  const layer = new PlateFaceLayer({ canvasFactory: scrapeCanvasFactory() })
  const stage = new PlateStage({ manifest, nodeIndex: scene.nodeIndex, layer })
  return { ...scene, layer, stage }
}

test('刮取: 板出场前 setScrape 不生效(通道从 t=0 就在求值)', () => {
  const { stage } = makeScrapeStage()
  assert.equal(stage.setScrape('plate', { loosen: 0.5, clear: 0 }, SCRAPE_REGION), false)
})

test('刮取: 落座后建立映射, 进度>0 时板换克隆材质', () => {
  const { stage, layer } = makeScrapeStage()
  stage.apply({ id: 'plate', at: 'scrape_table' })
  // 零进度: 映射可以建, 但不建资源、不换材质
  stage.setScrape('plate', { loosen: 0, clear: 0 }, SCRAPE_REGION)
  assert.equal(layer.get('plate').silica.material, layer.silicaMaterial)

  assert.equal(stage.setScrape('plate', { loosen: 0.5, clear: 0 }, SCRAPE_REGION), true)
  assert.notEqual(layer.get('plate').silica.material, layer.silicaMaterial)
  const snapshot = stage.status().scrape
  assert.equal(snapshot.plateId, 'plate')
  assert.ok(Math.abs(snapshot.loosen - 0.5) < 1e-9)
  assert.ok(snapshot.uvBand, 'status 要外露 uvBand 供验收脚本反投影')
})

test('刮取: 板被吸走后沿用落座时的映射(条带是板的属性, 不许重投影)', () => {
  const { stage, layer } = makeScrapeStage()
  stage.apply({ id: 'plate', at: 'scrape_table' })
  stage.setScrape('plate', { loosen: 0.5, clear: 0 }, SCRAPE_REGION)
  const uvBefore = JSON.stringify(stage.status().scrape.uvBand)

  stage.apply({ id: 'plate', carry: true, from: 'scrape_table' })
  assert.equal(stage.setScrape('plate', { loosen: 1, clear: 0.5 }, SCRAPE_REGION), true,
    '手上的板要能继续被刮(缓存路径)')
  assert.equal(JSON.stringify(stage.status().scrape.uvBand), uvBefore, '映射不许随姿态重算')
})

test('刮取: 从未落座直接被持的板收到 scrape 只能跳过(没有可信的映射姿态)', () => {
  const { stage } = makeScrapeStage()
  stage.apply({ id: 'plate', carry: true })
  assert.equal(stage.setScrape('plate', { loosen: 0.5, clear: 0 }, SCRAPE_REGION), false)
})

test('刮取: region 缺失静默跳过(片段没有 compiled.scrapeRegions 的形态)', () => {
  const { stage } = makeScrapeStage()
  stage.apply({ id: 'plate', at: 'scrape_table' })
  assert.equal(stage.setScrape('plate', { loosen: 0.5, clear: 0 }, null), false)
})

test('刮取: manifest 没有轴(方向解析不到)时留白并记 unresolved', () => {
  const { stage, layer } = makeStage()   // 原 MANIFEST: 无 axes
  stage.apply({ id: 'plate', at: 'scrape_table' })
  assert.equal(stage.setScrape('plate', { loosen: 0.5, clear: 0 }, SCRAPE_REGION), false)
  assert.ok(stage.status().unresolved.includes('scrape:machine-dirs'))
  assert.equal(layer.get('plate').silica.material, layer.silicaMaterial, '留白 = 材质原样')
})

test('刮取: clear() 清映射缓存与刮痕, 重放按同一落座姿态重建(seek 契约)', () => {
  const { stage, layer } = makeScrapeStage()
  stage.apply({ id: 'plate', at: 'scrape_table' })
  stage.setScrape('plate', { loosen: 1, clear: 0.5 }, SCRAPE_REGION)
  const uvBefore = JSON.stringify(stage.status().scrape.uvBand)

  stage.clear()
  assert.equal(stage.status().scrape, null, '清场后不该残留刮取状态')
  assert.equal(layer.plateIds().length, 0)

  // 重放: 同一落点、同一 region → 映射逐位相同, 板从干净态重新刮起
  stage.apply({ id: 'plate', at: 'scrape_table' })
  assert.equal(layer.get('plate').silica.material, layer.silicaMaterial, '重放出场的板必须干净')
  stage.setScrape('plate', { loosen: 1, clear: 0.5 }, SCRAPE_REGION)
  assert.equal(JSON.stringify(stage.status().scrape.uvBand), uvBefore,
    '重放后的映射必须逐位相同 —— 否则拖进度条条带会跳')
})

