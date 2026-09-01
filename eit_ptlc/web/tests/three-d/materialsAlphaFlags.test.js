/**
 * 功能: 材质台透明三元组(transparent/opacity/depthWrite)联动 —— 类/零件克隆/组克隆三条路径.
 *
 * 为什么盯这三个标志必须一起动(这组用例钉的就是这个决定):
 *   GLTFLoader 对 alphaMode=BLEND 的材质会同时置 transparent=true 与 depthWrite=false
 *   (three#17706 的官方配对). 材质台若只切 transparent —— 把不透明度拖回 1.0 时网格
 *   进了不透明队列却仍不写深度, 后画的内部隔板直接盖穿外壁, 表现为"不透明度 100%
 *   仍穿模"(2026-08-07 用户在 MAT_LABWARE_PP 样品板上实报). 反向把不透明材质拖成
 *   半透明时 depthWrite 停在 true, 半透明件之间又互相硬遮挡. 所以三个标志只能从
 *   alpha/transmission 一起推导, 任何一条写入路径(类 apply / 件克隆 _writeMerged /
 *   组克隆 _writeGroupMerged)都不许漏.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { MaterialsScene, syncAlphaFlags } from '../../src/three-d/materials/MaterialsScene.js'

/** 读一个材质的透明三元组, 断言时整组比对(单看一个标志正是本 bug 的成因). */
function flags(material) {
  return {
    transparent: material.transparent,
    opacity: material.opacity,
    depthWrite: material.depthWrite,
  }
}

/**
 * 造一个最小场景: 三种典型加载态各挂一个网格, 外加一个共享 PP 材质的第二网格
 * (验证类材质共享/克隆隔离). manager 只需 machineRoot; canvas=null 时拾取绑定自动跳过.
 */
function makeRig() {
  const root = new THREE.Group()

  // 仿 GLTFLoader 加载 alphaMode=BLEND 的产物(MAT_LABWARE_PP, alpha 0.92)
  const pp = new THREE.MeshStandardMaterial({
    name: 'MAT_LABWARE_PP', transparent: true, opacity: 0.92, depthWrite: false,
  })
  // 仿加载 OPAQUE 的产物
  const steel = new THREE.MeshStandardMaterial({
    name: 'MAT_STEEL_TEST', transparent: false, opacity: 1, depthWrite: true,
  })
  // 仿加载 BLEND + KHR_materials_transmission 的玻璃
  const glass = new THREE.MeshPhysicalMaterial({
    name: 'MAT_GLASS_TEST', transparent: true, opacity: 0.42, depthWrite: false,
    transmission: 0.72,
  })

  const meshes = {}
  for (const [key, material] of [
    ['plate1', pp], ['plate2', pp], ['frame', steel], ['pane', glass],
  ]) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 0.1), material)
    mesh.name = key
    root.add(mesh)
    meshes[key] = mesh
  }

  const scene = new MaterialsScene({ manager: { machineRoot: root, canvas: null, effects: null } })
  return { scene, meshes, pp, steel, glass }
}

test('syncAlphaFlags: alpha/transmission 推导三元组', () => {
  const material = new THREE.MeshStandardMaterial({ transparent: true, opacity: 0.92, depthWrite: false })
  syncAlphaFlags(material, { alpha: 1 })
  assert.deepEqual(flags(material), { transparent: false, opacity: 1, depthWrite: true })
  syncAlphaFlags(material, { alpha: 0.5 })
  assert.deepEqual(flags(material), { transparent: true, opacity: 0.5, depthWrite: false })
  // 透射>0 时即使 alpha=1 也维持 BLEND 语义
  syncAlphaFlags(material, { alpha: 1, transmission: 0.7 })
  assert.deepEqual(flags(material), { transparent: true, opacity: 1, depthWrite: false })
})

test('类材质: BLEND 加载态拖到 alpha=1 → 完全不透明并恢复写深度(用户实报的穿模)', () => {
  const { scene, pp } = makeRig()
  assert.deepEqual(flags(pp), { transparent: true, opacity: 0.92, depthWrite: false })

  scene.apply('MAT_LABWARE_PP', { alpha: 1 })
  assert.deepEqual(flags(pp), { transparent: false, opacity: 1, depthWrite: true })

  // 空补丁 = 恢复原值: 回到与 GLTFLoader 加载态逐位一致的三元组
  scene.apply('MAT_LABWARE_PP', {})
  assert.deepEqual(flags(pp), { transparent: true, opacity: 0.92, depthWrite: false })
})

test('类材质: 不透明材质拖成半透明 → 关写深度; 清补丁还原', () => {
  const { scene, steel } = makeRig()
  scene.apply('MAT_STEEL_TEST', { alpha: 0.5 })
  assert.deepEqual(flags(steel), { transparent: true, opacity: 0.5, depthWrite: false })
  scene.apply('MAT_STEEL_TEST', {})
  assert.deepEqual(flags(steel), { transparent: false, opacity: 1, depthWrite: true })
})

test('类材质: 透射玻璃 alpha 拖到 1 仍保持 BLEND 语义(transmission 屏蔽)', () => {
  const { scene, glass } = makeRig()
  scene.apply('MAT_GLASS_TEST', { alpha: 1 })
  assert.deepEqual(flags(glass), { transparent: true, opacity: 1, depthWrite: false })
})

test('零件克隆: 克隆继承的 depthWrite=false 被合成值修正, 类本体不动', () => {
  const { scene, meshes, pp } = makeRig()

  scene.applyPart([meshes.plate1], { alpha: 1 })
  const clone = meshes.plate1.material
  assert.equal(clone.name, 'MAT_LABWARE_PP@part')
  assert.deepEqual(flags(clone), { transparent: false, opacity: 1, depthWrite: true })
  // 同类其余零件与类材质本体保持加载态
  assert.equal(meshes.plate2.material, pp)
  assert.deepEqual(flags(pp), { transparent: true, opacity: 0.92, depthWrite: false })

  // 清空补丁: 还原类材质并回收克隆
  scene.applyPart([meshes.plate1], {})
  assert.equal(meshes.plate1.material, pp)
})

test('组克隆: 组合成值同样联动三元组', () => {
  const { scene, meshes, steel } = makeRig()

  scene.applyGroup('测试组', [meshes.frame], { alpha: 0.5 }, 'MAT_STEEL_TEST')
  const clone = meshes.frame.material
  assert.equal(clone.name, 'GROUP_测试组@part')
  assert.deepEqual(flags(clone), { transparent: true, opacity: 0.5, depthWrite: false })
  assert.deepEqual(flags(steel), { transparent: false, opacity: 1, depthWrite: true })

  // 组参数拖回 1.0: 组克隆退出半透明并恢复写深度
  scene.applyGroup('测试组', [meshes.frame], { alpha: 1 }, 'MAT_STEEL_TEST')
  assert.deepEqual(flags(clone), { transparent: false, opacity: 1, depthWrite: true })

  scene.dissolveGroup('测试组')
  assert.equal(meshes.frame.material, steel)
})
