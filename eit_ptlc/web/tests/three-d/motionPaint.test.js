/**
 * 功能: 语义着色控制器(MotionPaint)的单测.
 *
 * 要害是**认领优先级**: 程序化板网格自带 __ptlcSemantic 标签, 必须压过"按条目子树
 * 认领"(板骑在滑车/吸盘上不该跟着变蓝)与"transmission>0 透明兜底"(玻璃层不该被
 * 涂成半透明静止). 这正是"语义着色下玻璃板显示透明"那个 bug 的回归钉.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { MotionPaint } from '../../src/three-d/motion/MotionPaint.js'
import { SEMANTIC_COLORS } from '../../src/three-d/motion/motionSemantics.js'

const UNIT_BOX = new THREE.BoxGeometry(1, 1, 1)

/** 与生产同形态的程序化玻璃层材质(transmission>0 且半透明, 正中透明兜底的判据)。 */
function makeGlassLikeMaterial() {
  return new THREE.MeshPhysicalMaterial({ transmission: 0.86, transparent: true, opacity: 1 })
}

/** 打了耗材标签的程序化板网格(写方是 PlateFaceLayer, 这里手搓同构夹具)。 */
function makeTaggedPlate() {
  const mesh = new THREE.Mesh(UNIT_BOX, makeGlassLikeMaterial())
  mesh.userData.__ptlcSemantic = 'consumable'
  return mesh
}

/**
 * 场景夹具: root 下挂
 *   plain    普通不透明静止件
 *   housing  未打标签的透射罩壳(应走透明兜底)
 *   carriage 可动条目的 glbNode 子树, 内含滑车本体 body 与骑在上面的标签板 ridingPlate
 *   stack    打标签的 InstancedMesh(料仓板堆形态)
 */
function makeScene() {
  const root = new THREE.Group()
  const plain = new THREE.Mesh(UNIT_BOX, new THREE.MeshStandardMaterial())
  const housing = new THREE.Mesh(UNIT_BOX, makeGlassLikeMaterial())
  const carriage = new THREE.Group()
  carriage.name = 'CARRIAGE'
  const body = new THREE.Mesh(UNIT_BOX, new THREE.MeshStandardMaterial())
  const ridingPlate = makeTaggedPlate()
  carriage.add(body, ridingPlate)
  const stack = new THREE.InstancedMesh(UNIT_BOX, makeGlassLikeMaterial(), 8)
  stack.userData.__ptlcSemantic = 'consumable'
  root.add(plain, housing, carriage, stack)

  const paint = new MotionPaint({
    manager: { machineRoot: root },
    resolve: (path) => (path === 'CARRIAGE' ? carriage : undefined),
  })
  const entries = [{ id: 'axis:test', category: 'movable', glbNodes: ['CARRIAGE'] }]
  return { root, plain, housing, carriage, body, ridingPlate, stack, paint, entries }
}

test('标签认领: 程序化板刷耗材橙, 压过所在的 movable 子树', () => {
  const { paint, entries, body, ridingPlate, stack } = makeScene()
  const counts = paint.apply(entries)

  assert.equal(ridingPlate.material, stack.material, '标签网格共享同一个耗材材质实例')
  const expected = new THREE.Color(SEMANTIC_COLORS.consumable).getHexString()
  assert.equal(ridingPlate.material.color.getHexString(), expected, '刷的就是耗材橙')
  assert.equal(ridingPlate.material.transparent, false, '耗材色是不透明的(不是玻璃兜底)')
  assert.equal(counts.consumable, 2, '单板 + InstancedMesh 板堆都计入耗材')
  assert.equal(counts.movable, 1, '滑车本体仍按子树认领为可动')
  assert.equal(paint.meshEntry.get(body), 'axis:test')
  assert.equal(paint.meshEntry.has(ridingPlate), false, '标签认领不冒充条目归属')
  paint.dispose()
})

test('透明兜底不回归: 未打标签的透射罩壳仍保持半透明静止', () => {
  const { paint, entries, plain, housing } = makeScene()
  const counts = paint.apply(entries)

  assert.equal(housing.material.transparent, true)
  assert.ok(housing.material.opacity < 0.5, '罩壳走半透明兜底, 不挡柜内可动件')
  assert.notEqual(housing.material, plain.material, '罩壳与普通静止件不共用材质')
  assert.equal(counts.static, 2, '普通件 + 罩壳都计入静止')
  paint.dispose()
})

test('还原: 原材质指针逐一换回, 台账清空(含着色期间被摘出场景的板)', () => {
  const { paint, entries, root, plain, housing, ridingPlate, stack } = makeScene()
  const originals = new Map(
    [plain, housing, ridingPlate, stack].map((mesh) => [mesh, mesh.material]),
  )
  paint.apply(entries)
  ridingPlate.removeFromParent()   // 模拟板归池(release 摘出场景)

  paint.restore()
  for (const [mesh, material] of originals) {
    assert.equal(mesh.material, material, `${mesh.type} 应还原原材质`)
  }
  assert.equal(paint._original.size, 0)
  assert.equal(paint.meshEntry.size, 0)
  assert.equal(paint.active, false)
  root.updateMatrixWorld(true)
  paint.dispose()
})

test('快照语义: 着色开启后新建的标签板不上色, 重开一次即全量重涂', () => {
  const { paint, entries, root } = makeScene()
  paint.apply(entries)

  const late = makeTaggedPlate()
  const lateOriginal = late.material
  root.add(late)
  assert.equal(late.material, lateOriginal, 'apply 是一次性快照, 事后新建的板不变色')

  const counts = paint.apply(entries)   // 幂等: 先还原再重涂
  assert.equal(late.material.color.getHexString(),
    new THREE.Color(SEMANTIC_COLORS.consumable).getHexString())
  assert.equal(counts.consumable, 3, '重涂后新板计入耗材')
  paint.restore()
  assert.equal(late.material, lateOriginal)
  paint.dispose()
})

test('CAD 残留板按命名认领: 裸 玻璃-N 刷耗材橙, 带前缀的部件与石英玻璃不误伤', () => {
  const { paint, entries, root } = makeScene()
  // 上料抽屉里的遗留板(实机 bug 现场: 唯一可见的 CAD 薄层板, 不在任何 manifest 节点里)
  const drawerPlate = new THREE.Mesh(UNIT_BOX, makeGlassLikeMaterial())
  drawerPlate.name = '玻璃-2'
  // 三侧点号被剥的落点板命名形态(玻璃-1.006 -> 玻璃-1006)
  const anchorPlate = new THREE.Mesh(UNIT_BOX, makeGlassLikeMaterial())
  anchorPlate.name = '玻璃-1006'
  // 误伤防护: 名字含"玻璃"的钢件与石英玻璃缸盖都带部件前缀
  const steelBracket = new THREE.Mesh(UNIT_BOX, new THREE.MeshStandardMaterial())
  steelBracket.name = 'PTLC-06-004_刮板玻璃放置平台-1'
  const quartzLid = new THREE.Mesh(UNIT_BOX, makeGlassLikeMaterial())
  quartzLid.name = 'PTLC-02-019_石英玻璃-1004'
  root.add(drawerPlate, anchorPlate, steelBracket, quartzLid)

  const counts = paint.apply(entries)
  const orange = new THREE.Color(SEMANTIC_COLORS.consumable).getHexString()
  assert.equal(drawerPlate.material.color.getHexString(), orange, '抽屉遗留板刷耗材橙')
  assert.equal(drawerPlate.material.transparent, false)
  assert.equal(anchorPlate.material.color.getHexString(), orange, '落点板命名同样认领')
  assert.equal(steelBracket.material, paint._materials.static, '钢件走静止')
  assert.ok(quartzLid.material.transparent && quartzLid.material.opacity < 0.5,
    '石英玻璃缸盖保持透明兜底')
  assert.equal(counts.consumable, 4, '标签 2 + 命名认领 2')
  paint.dispose()
})

test('脏标签值不接: 未知分类走原有认领/兜底逻辑', () => {
  const { paint, entries, root } = makeScene()
  const weird = new THREE.Mesh(UNIT_BOX, new THREE.MeshStandardMaterial())
  weird.userData.__ptlcSemantic = 'no-such-category'
  root.add(weird)

  const counts = paint.apply(entries)
  assert.equal(weird.material, paint._materials.static, '未知标签按普通静止件处理')
  assert.equal(counts.static, 3)
  paint.dispose()
})
