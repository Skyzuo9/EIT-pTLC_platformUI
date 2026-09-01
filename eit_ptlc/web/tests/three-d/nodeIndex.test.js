/**
 * 功能: buildNodeIndex 双写索引(three 名 + glTF 原名)的单测.
 *
 * 值得单测的理由: 这是 manifest glbNode 解析的唯一依据. three 加载器剥掉节点名里的
 * 点号(CARRIAGE.001→CARRIAGE001)曾让 manifest 带点原名解析失败, axis_3y/axis_5z
 * 静默变成死轴 —— 索引契约必须用测试锁死, 别再靠实机发现.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import { buildNodeIndex } from '../../src/three-d/twin/scene/loadModel.js'

/**
 * 功能: 造一个模拟 GLTFLoader 加载结果的节点(three 名已消毒, 原名进 userData).
 * @param {string} threeName three 消毒后的名字
 * @param {string} [origName] glTF 原名(与 three 名相同时不写 userData)
 * @returns {THREE.Group} 节点
 */
function node(threeName, origName) {
  const group = new THREE.Group()
  group.name = threeName
  if (origName && origName !== threeName) group.userData.origName = origName
  return group
}

/** 复刻实机层级: ST_RAIL/AXIS_AXIS_11Y/CARRIAGE(无后缀) + ST_SAMPLING 下带 .001/.002 的叠轴 */
function buildScene() {
  const scene = new THREE.Group()
  scene.name = 'scene'

  const rail = node('ST_RAIL')
  const axis11 = node('AXIS_AXIS_11Y')
  const carriage11 = node('CARRIAGE')
  rail.add(axis11)
  axis11.add(carriage11)

  const sampling = node('ST_SAMPLING')
  const axis3 = node('AXIS_AXIS_3Y')
  const carriage3 = node('CARRIAGE001', 'CARRIAGE.001')
  const axis5 = node('AXIS_AXIS_5Z')
  const carriage5 = node('CARRIAGE002', 'CARRIAGE.002')
  sampling.add(axis3)
  axis3.add(carriage3)
  carriage3.add(axis5)
  axis5.add(carriage5)

  // 空格消毒的常规情况: three 名下划线, 原名带空格
  const frame = node('ST_FRAME')
  const panel = node('PTLC-01-001_面板-1', 'PTLC-01-001 面板-1')
  frame.add(panel)

  scene.add(rail)
  scene.add(sampling)
  scene.add(frame)
  return { scene, carriage11, carriage3, carriage5, panel }
}

test('three 名路径与裸名解析保持原语义', () => {
  const { scene, carriage11, carriage3 } = buildScene()
  const index = buildNodeIndex(scene)
  assert.equal(index.get('ST_RAIL/AXIS_AXIS_11Y/CARRIAGE'), carriage11)
  assert.equal(index.get('ST_SAMPLING/AXIS_AXIS_3Y/CARRIAGE001'), carriage3)
  // 裸名首个命中优先: 'CARRIAGE' 归 ST_RAIL 那个(遍历序先到)
  assert.equal(index.get('CARRIAGE'), carriage11)
})

test('manifest 带点原名路径能命中(死轴修复的核心)', () => {
  const { scene, carriage3, carriage5 } = buildScene()
  const index = buildNodeIndex(scene)
  // 这两条正是实机 manifest 里 axis_3y / axis_5z 的 glbNode
  assert.equal(index.get('ST_SAMPLING/AXIS_AXIS_3Y/CARRIAGE.001'), carriage3)
  assert.equal(
    index.get('ST_SAMPLING/AXIS_AXIS_3Y/CARRIAGE.001/AXIS_AXIS_5Z/CARRIAGE.002'),
    carriage5,
  )
  // 原名裸末段也可用(TwinBindings._resolve 的末段兜底路径)
  assert.equal(index.get('CARRIAGE.001'), carriage3)
  assert.equal(index.get('CARRIAGE.002'), carriage5)
})

test('空格消毒的原名同样双写', () => {
  const { scene, panel } = buildScene()
  const index = buildNodeIndex(scene)
  assert.equal(index.get('ST_FRAME/PTLC-01-001_面板-1'), panel)
  assert.equal(index.get('ST_FRAME/PTLC-01-001 面板-1'), panel)
  assert.equal(index.get('PTLC-01-001 面板-1'), panel)
})

test('原名与 three 名相同的节点不产生冗余键', () => {
  const { scene } = buildScene()
  const index = buildNodeIndex(scene)
  // ST_RAIL 一支全部同名: 键数 = 路径键 + 裸名键, 无原名平行键
  const railKeys = [...index.keys()].filter((k) => k.includes('ST_RAIL') || k === 'ST_RAIL')
  assert.deepEqual(railKeys.sort(), [
    'ST_RAIL',
    'ST_RAIL/AXIS_AXIS_11Y',
    'ST_RAIL/AXIS_AXIS_11Y/CARRIAGE',
  ])
})

test('原名键守卫: 不覆盖已存在的 three 名键', () => {
  const scene = new THREE.Group()
  const a = node('X')
  const b = node('Y', 'X') // b 的原名与 a 的 three 名撞车
  scene.add(a)
  scene.add(b)
  const index = buildNodeIndex(scene)
  // 'X' 键保住 a(three 名先写), b 只占 'Y'
  assert.equal(index.get('X'), a)
  assert.equal(index.get('Y'), b)
})
