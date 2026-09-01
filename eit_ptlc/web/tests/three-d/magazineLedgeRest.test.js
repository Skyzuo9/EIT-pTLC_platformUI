/**
 * 功能: 料仓托边停靠(MachineStateDriver.magazineRests)的回归测试.
 *
 * 真机里板不被滑车顶着时坐在料仓口的固定托边上: 滑车下行穿过托边平面, 板留在托边,
 * 滑车继续降。三维里板堆模板被 rig_map 并进滑车, 修法是在滑车与模板之间插 identity 的
 * REST 节点, setAxisMm 同步 REST.position = localPerMm × max(0, ledgeAxisMm − 轴mm)。
 *
 * 锁住五条:
 *   1. 交接值之上随滑车、之下停在交接高度, 交接点处连续无跳变;
 *   2. 滑车带旋转+非 1 缩放时补偿仍逐位精确 —— localPerMm 必须过滑车局部基的 3×3 逆,
 *      transformDirection 会把 scale 归一化抹掉(GLB 反量化 scale 教训同款);
 *   3. manifest 没有 ledgeAxisMm/axisId/inventory 时不建 REST, 行为与旧 manifest 逐位相同;
 *   4. dispose+重建 driver 幂等(同名 REST 复用不叠套); 加载态与 home() 都按 CAD 停靠
 *      轴值(zeroOffsetMm)先托 —— 自驱轴片段 t=0 前没有轴写入, 不先托就是开场埋板;
 *   5. 补偿是当帧轴值的纯函数(无记忆), 任意 seek 序列后位姿只由当前值决定。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { MachineStateDriver } from '../../src/three-d/anim/MachineStateDriver.js'
import { PlateFaceLayer } from '../../src/three-d/twin/scene/plates/PlateFaceLayer.js'
import { measurePlateAnchor } from '../../src/three-d/twin/scene/plates/plateGeometry.js'
import { makeQuantizedAnchor } from './plateFixtures.js'

const LEDGE_MM = 11.058
const ZERO_MM = -22

/**
 * 造一套"轴父级 → 滑车 → 量化板堆模板"的场景 + driver。
 * 模板用与生产同形态的量化锚点(SHORT + scale 0.1 + 薄轴 Z→Y 置换)。
 */
function makeRig({
  ledgeAxisMm = LEDGE_MM, includeLedge = true, includeAxisId = true, includeInventory = true,
  carriageRotation = null, carriageScale = 1,
} = {}) {
  const world = new THREE.Group()
  const carriage = new THREE.Group()
  carriage.name = 'CARRIAGE_TEST'
  if (carriageRotation) carriage.quaternion.copy(carriageRotation)
  if (carriageScale !== 1) carriage.scale.setScalar(carriageScale)
  world.add(carriage)

  const { mesh: template } = makeQuantizedAnchor({ offset: new THREE.Vector3(0.1, 0.2, 0.05) })
  template.name = 'INV_MAGAZINE_FEED_TEMPLATE'
  carriage.add(template)
  world.updateMatrixWorld(true)

  const magazine = {
    id: 'feed', node: 'TEMPLATE_PATH', stackAxis: [0, 1, 0], stackSign: 1, spacingM: 0.003,
  }
  if (includeAxisId) magazine.axisId = 'axis_1z'
  if (includeLedge) magazine.ledgeAxisMm = ledgeAxisMm
  const manifest = {
    axes: [{
      id: 'axis_1z', glbNode: 'CARRIAGE_TEST', rigged: true, axis: [0, 1, 0], sign: 1,
      mmToUnit: 0.001, zeroOffsetMm: ZERO_MM, rangeMm: [-50, 550], geometryMinMm: -32,
    }],
  }
  if (includeInventory) manifest.inventory = { magazines: [magazine] }

  const resolve = (path) => ({ CARRIAGE_TEST: carriage, TEMPLATE_PATH: template }[path])
  const rig = new MachineStateDriver({ manifest, resolve })
  return { rig, world, carriage, template, manifest, resolve }
}

/** 一个节点当刻的世界位置(先强制刷新整棵树)。 */
function worldPos(world, node) {
  world.updateMatrixWorld(true)
  return node.getWorldPosition(new THREE.Vector3())
}

test('交接值之上随滑车, 之下停在交接高度, 交接点连续', () => {
  const { rig, world, template, carriage } = makeRig()

  rig.setAxisMm('axis_1z', 512)
  const atPick = worldPos(world, template)
  rig.setAxisMm('axis_1z', 300)
  const atMid = worldPos(world, template)
  assert.ok(Math.abs((atPick.y - atMid.y) - (512 - 300) / 1000) < 1e-12, '交接值之上 1:1 随滑车')

  rig.setAxisMm('axis_1z', LEDGE_MM)
  const atLedge = worldPos(world, template)
  for (const mm of [LEDGE_MM - 1e-6, 5, 0, -32]) {
    rig.setAxisMm('axis_1z', mm)
    const held = worldPos(world, template)
    assert.ok(held.distanceTo(atLedge) < 1e-12, `轴 ${mm}mm 时板必须停在交接高度`)
  }
  // 滑车自己继续走: 板停住的同时滑车按轴值下行
  rig.setAxisMm('axis_1z', 0)
  const carriageLow = worldPos(world, carriage)
  rig.setAxisMm('axis_1z', LEDGE_MM)
  const carriageLedge = worldPos(world, carriage)
  assert.ok(Math.abs((carriageLedge.y - carriageLow.y) - LEDGE_MM / 1000) < 1e-12,
    '板停在托边期间滑车仍随轴值移动')
})

test('滑车带旋转+非 1 缩放时补偿仍精确(3×3 逆, 不许 transformDirection)', () => {
  const rotation = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.3, 0.7, -0.2))
  const { rig, world, template } = makeRig({ carriageRotation: rotation, carriageScale: 0.5 })

  rig.setAxisMm('axis_1z', LEDGE_MM)
  const atLedge = worldPos(world, template)
  rig.setAxisMm('axis_1z', -32)
  const held = worldPos(world, template)
  assert.ok(held.distanceTo(atLedge) < 1e-12,
    '旋转+缩放滑车下, 板世界位姿仍钉在交接高度 —— localPerMm 的基变换错了这里就飘')

  rig.setAxisMm('axis_1z', LEDGE_MM + 100)
  const above = worldPos(world, template)
  assert.ok(Math.abs((above.y - atLedge.y) - 0.1) < 1e-12, '交接值之上仍沿父空间轴向 1:1')
})

test('兜底: 缺 ledgeAxisMm / 缺 axisId / 无 inventory 时不建 REST, 行为与现行逐位相同', () => {
  for (const opts of [
    { includeLedge: false },
    { ledgeAxisMm: null },
    { includeAxisId: false },
    { includeInventory: false },
  ]) {
    const { rig, world, template, carriage } = makeRig(opts)
    assert.equal(rig.magazineRests.size, 0, `${JSON.stringify(opts)} 不该建 REST`)
    assert.equal(template.parent, carriage, '模板仍直接挂滑车')
    rig.setAxisMm('axis_1z', 512)
    const top = worldPos(world, template)
    rig.setAxisMm('axis_1z', 0)
    const low = worldPos(world, template)
    assert.ok(Math.abs((top.y - low.y) - 0.512) < 1e-12, '老 manifest 下板仍刚性随滑车(现行为)')
  }
})

test('幂等: dispose 后重建 driver 只有一个 REST, 模板局部变换逐位不变', () => {
  const { rig, carriage, template, manifest, resolve } = makeRig()
  const localBefore = {
    position: template.position.clone(),
    quaternion: template.quaternion.clone(),
    scale: template.scale.clone(),
  }
  rig.setAxisMm('axis_1z', 0)
  rig.dispose()
  const second = new MachineStateDriver({ manifest, resolve })

  const rests = carriage.children.filter((child) => child.name.startsWith('REST_'))
  assert.equal(rests.length, 1, '重建 driver 不许叠套 REST')
  assert.equal(template.parent, rests[0])
  assert.equal(second.magazineRests.get('axis_1z')?.[0]?.rest, rests[0], '第二个 driver 复用同一 REST')
  assert.ok(template.position.equals(localBefore.position), '模板局部位置逐位不变')
  assert.ok(template.quaternion.equals(localBefore.quaternion), '模板局部姿态逐位不变')
  assert.ok(template.scale.equals(localBefore.scale), '模板局部缩放逐位不变')
})

test('加载态与 home() 都已托在交接高度(CAD 埋板不复现)', () => {
  const { rig, world, template } = makeRig()
  // CAD 停靠轴值 −22 在交接值之下: 绑定一完成板就该被托住, 不等第一次写轴 ——
  // 自驱轴的片段 home 里没有轴值, t=0 到首个轴步之间没有任何 setAxisMm
  const loaded = worldPos(world, template)
  rig.setAxisMm('axis_1z', LEDGE_MM)
  assert.ok(worldPos(world, template).distanceTo(loaded) < 1e-12,
    '加载态位姿 = 交接高度(绑定时已按 zeroOffsetMm 托过)')

  rig.setAxisMm('axis_1z', 512)
  assert.ok(worldPos(world, template).distanceTo(loaded) > 1e-6, '先确认真的动过')
  rig.home()
  assert.ok(worldPos(world, template).distanceTo(loaded) < 1e-12, 'home 后回到托位(加载态)')
})

test('无记忆: 任意 seek 序列后位姿只由当前轴值决定', () => {
  const { rig, world, template } = makeRig()
  rig.setAxisMm('axis_1z', 512)
  rig.setAxisMm('axis_1z', 0)
  rig.setAxisMm('axis_1z', 512)
  const roundTrip = worldPos(world, template)

  const fresh = makeRig()
  fresh.rig.setAxisMm('axis_1z', 512)
  const direct = worldPos(fresh.world, fresh.template)
  assert.ok(roundTrip.distanceTo(direct) < 1e-12, '512→0→512 与直接写 512 逐位一致')
})

test('集成: 单板与料仓堆的父级都是 REST, 低轴时一起被托住', () => {
  const { rig, world, template } = makeRig()
  const layer = new PlateFaceLayer()
  const geom = measurePlateAnchor(template)
  geom.silicaUp = false

  assert.equal(layer.place('plate', geom), true)
  const plate = layer.get('plate')
  assert.equal(plate.root.parent.name, 'REST_INV_MAGAZINE_FEED_TEMPLATE', '单板骑 REST')

  layer.setMagazine('feed', { geom, parent: geom.parent, count: 3, pitchM: 0.003 })
  const stack = layer._magazines.get('feed')
  assert.equal(stack.glass.parent.name, 'REST_INV_MAGAZINE_FEED_TEMPLATE', '板堆骑 REST')

  rig.setAxisMm('axis_1z', LEDGE_MM)
  const plateAtLedge = worldPos(world, plate.root)
  const stackAtLedge = worldPos(world, stack.glass)
  rig.setAxisMm('axis_1z', 0)
  assert.ok(worldPos(world, plate.root).distanceTo(plateAtLedge) < 1e-12, '低轴时单板停在托边')
  assert.ok(worldPos(world, stack.glass).distanceTo(stackAtLedge) < 1e-12, '低轴时板堆停在托边')
  layer.dispose()
})
