/**
 * 功能: 工艺灯 `light` 连续通道 —— 编译、插值、seek 幂等与驱动层写入.
 *
 * 为什么灯做成**连续通道**而不是离散事件(这两条用例就是钉这个决定的):
 *   1. 通道值是 t 的纯函数 —— 拖进度条到任意时刻直接算得出, 不依赖"回家重放";
 *   2. 补光本来就是"渐亮 → 稳态 → 熄灭"的连续过程(真机 light_settle_ms 有 1s 稳定期),
 *      做成离散开关既不像, 又会在向后 seek 时留下"该灭没灭"的残留。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { compileClip, evaluateChannels } from '../../src/three-d/anim/clipSchema.js'
import { MachineStateDriver } from '../../src/three-d/anim/MachineStateDriver.js'

/** 一段"渐亮 → 稳态 → 曝光 → 熄灭"的补光片段(与 clip_compiler.emit_vision_capture 同形)。 */
function flashClip() {
  return {
    schema: 'ptlc.clip/v1',
    name: 'flash',
    home: { lights: { vision_fill: 0 } },
    steps: [
      { label: '开灯', dur: 0.25, ease: 'out', do: { light: { id: 'vision_fill', to: 0.82 } } },
      { label: '稳定', dur: 1.0, ease: 'linear', do: { light: { id: 'vision_fill', to: 0.82 } } },
      { label: '曝光', dur: 0.3, ease: 'out', do: { light: { id: 'vision_fill', to: 1.0 } } },
      { label: '熄灭', dur: 0.35, ease: 'inout', do: { light: { id: 'vision_fill', to: 0 } } },
    ],
  }
}

/**
 * 造一个带一盏灯的最小 manifest + 场景。
 *
 * `litPeak` 非 null 时再挂一个**受照节点**(对应真机里补光灯上方那扇会跟着亮的盖板玻璃)。
 */
function makeRig({ defaultLevel = 0, peak = 4, litPeak = null } = {}) {
  const root = new THREE.Group()
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(0.1, 0.1, 0.01),
    new THREE.MeshStandardMaterial({ emissive: new THREE.Color('#000000') }),
  )
  mesh.name = 'STATIC_MAT_VISION_FILL'
  root.add(mesh)
  const shared = mesh.material

  const glass = new THREE.Mesh(
    new THREE.BoxGeometry(0.14, 0.14, 0.003),
    new THREE.MeshStandardMaterial({ emissive: new THREE.Color('#000000') }),
  )
  glass.name = '下相机盖板玻璃'
  root.add(glass)
  const glassShared = glass.material

  const spec = {
    id: 'vision_fill', glbNode: 'STATIC_MAT_VISION_FILL',
    color: '#ffffff', peakIntensity: peak, defaultLevel, bloom: true,
  }
  if (litPeak !== null) {
    spec.illuminatesNodes = [{ glbNode: glass.name, peakIntensity: litPeak }]
  }
  const resolve = (p) => (p === mesh.name ? mesh : (p === glass.name ? glass : undefined))
  const rig = new MachineStateDriver({ manifest: { lights: [spec] }, resolve })
  return { rig, mesh, shared, glass, glassShared }
}

test('light 是连续通道: 编译进 channels 而不是 events', () => {
  const clip = compileClip(flashClip())
  assert.equal(clip.events.length, 0, '灯不该产生离散事件')
  assert.ok(clip.channels.has('light:vision_fill'))
})

test('亮度按关键帧插值, 且任意 t 都是纯函数(seek 安全)', () => {
  const clip = compileClip(flashClip())
  const at = (t) => evaluateChannels(clip, t).lights.vision_fill

  assert.equal(at(0), 0, 't=0 全灭')
  assert.ok(at(0.25) > 0.8, '渐亮结束应到稳态')
  assert.ok(Math.abs(at(0.8) - 0.82) < 1e-9, '稳定期保持不变')
  assert.ok(Math.abs(at(1.55) - 1.0) < 1e-9, '曝光顶到峰值')
  assert.ok(at(1.9) < 0.01, '末尾熄灭')

  // 纯函数: 正着走一遍再回头, 同一 t 必须同值
  for (const t of [0.1, 0.7, 1.3, 1.6, 1.85]) {
    assert.equal(at(t), at(t), `t=${t} 求值不稳定`)
  }
})

test('light.to 越界或缺 id 在编译期就报错', () => {
  const bad = (body) => () => compileClip({
    schema: 'ptlc.clip/v1', name: 't', steps: [{ dur: 0.1, do: { light: body } }],
  })
  assert.throws(bad({ id: 'vision_fill' }), /缺 id\/to/)
  assert.throws(bad({ to: 0.5 }), /缺 id\/to/)
  assert.throws(bad({ id: 'vision_fill', to: 1.5 }), /0\.\.1/)
  assert.throws(bad({ id: 'vision_fill', to: -0.1 }), /0\.\.1/)
})

test('驱动层: 克隆材质独占, 不污染共用同材质的别的零件', () => {
  const { rig, mesh, shared } = makeRig()
  assert.notEqual(mesh.material, shared, '必须克隆一份')
  rig.setLight('vision_fill', 1)
  assert.equal(shared.emissiveIntensity, 1, '原材质不该被改动')
  assert.equal(mesh.material.emissiveIntensity, 4, '克隆件按 peakIntensity 放大')
})

test('驱动层: 亮度 = 系数 × peakIntensity, 并夹到 0..1', () => {
  const { rig, mesh } = makeRig({ peak: 2.5 })
  rig.setLight('vision_fill', 0.4)
  assert.ok(Math.abs(mesh.material.emissiveIntensity - 1.0) < 1e-9)
  rig.setLight('vision_fill', 5)
  assert.ok(Math.abs(mesh.material.emissiveIntensity - 2.5) < 1e-9, '越界夹到 1')
  rig.setLight('vision_fill', -1)
  assert.equal(mesh.material.emissiveIntensity, 0)
})

test('home() 把灯还原到 default_level —— 否则拖过补光段之后灯再也不灭', () => {
  const { rig, mesh } = makeRig({ defaultLevel: 0, peak: 4 })
  rig.setLight('vision_fill', 1)
  assert.equal(mesh.material.emissiveIntensity, 4)
  rig.home()
  assert.equal(mesh.material.emissiveIntensity, 0, 'home 后必须回默认亮度')
})

test('常亮灯(紫外面光源)默认就亮, home 后仍亮', () => {
  const { rig, mesh } = makeRig({ defaultLevel: 1, peak: 2.5 })
  assert.ok(Math.abs(mesh.material.emissiveIntensity - 2.5) < 1e-9, '默认即常亮')
  rig.setLight('vision_fill', 0)
  rig.home()
  assert.ok(Math.abs(mesh.material.emissiveIntensity - 2.5) < 1e-9)
})

test('只有亮着的灯进辉光选集(灭灯进选集是白跑一次全屏 pass)', () => {
  const { rig, mesh } = makeRig({ defaultLevel: 0 })
  assert.deepEqual(rig.bloomLights(), [], '灭着时不进')
  rig.setLight('vision_fill', 0.5)
  assert.deepEqual(rig.bloomLights(), [mesh])
  rig.setLight('vision_fill', 0)
  assert.deepEqual(rig.bloomLights(), [])
})

test('未声明的灯 id 静默忽略, 不炸(宿主没挂灯装置时片段照播)', () => {
  const { rig } = makeRig()
  assert.equal(rig.setLight('nope', 1), false)
})

// ── 受照节点(illuminatesNodes) ──────────────────────────────────────────────
//
// 这个接缝此前一条测试都没有, 而它正是 2026-08-05 "实时页闪光灯不闪" 的形状:
// 通道在跑、setLight 也在写, 但灯本体埋在盖板玻璃下 37mm 根本看不见 —— 可见形态
// 全靠受照节点承担。它坏掉时画面完全正常, 没有任何指标会报警。

test('受照节点随灯同步提亮, 各按自己的峰值', () => {
  const { rig, mesh, glass } = makeRig({ defaultLevel: 0, peak: 4, litPeak: 1.8 })
  rig.setLight('vision_fill', 0.5)
  assert.ok(Math.abs(mesh.material.emissiveIntensity - 2.0) < 1e-9, '灯本体 0.5×4')
  assert.ok(Math.abs(glass.material.emissiveIntensity - 0.9) < 1e-9, '受照节点 0.5×1.8')
})

test('受照节点克隆材质独占, 不污染共用同材质的别的零件', () => {
  const { rig, glass, glassShared } = makeRig({ litPeak: 1.8 })
  assert.notEqual(glass.material, glassShared, '必须克隆一份')
  rig.setLight('vision_fill', 1)
  assert.equal(glassShared.emissiveIntensity, 1, '原材质不该被改动')
})

test('home() 把受照节点一并还原 —— 否则拖过补光段之后那扇窗再也不灭', () => {
  const { rig, glass } = makeRig({ defaultLevel: 0, litPeak: 1.8 })
  rig.setLight('vision_fill', 1)
  assert.ok(Math.abs(glass.material.emissiveIntensity - 1.8) < 1e-9)
  rig.home()
  assert.equal(glass.material.emissiveIntensity, 0, 'home 后受照节点必须回默认亮度')
})

test('辉光选集含受照节点 —— 只放灯本体等于这盏灯没有辉光(它看不见)', () => {
  const { rig, mesh, glass } = makeRig({ defaultLevel: 0, litPeak: 1.8 })
  assert.deepEqual(rig.bloomLights(), [], '灭着时两个都不进')
  rig.setLight('vision_fill', 0.5)
  assert.deepEqual(rig.bloomLights(), [mesh, glass])
  rig.setLight('vision_fill', 0)
  assert.deepEqual(rig.bloomLights(), [])
})

test('受照节点解析不到时记进 missing, 而不是静默变成一盏不亮的灯', () => {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(0.1, 0.1, 0.01),
    new THREE.MeshStandardMaterial({ emissive: new THREE.Color('#000000') }),
  )
  mesh.name = 'STATIC_MAT_VISION_FILL'
  const manifest = {
    lights: [{
      id: 'vision_fill', glbNode: mesh.name, color: '#ffffff',
      peakIntensity: 4, defaultLevel: 0, bloom: true,
      illuminatesNodes: [{ glbNode: '这个零件改名了' }],
    }],
  }
  const rig = new MachineStateDriver({ manifest, resolve: (p) => (p === mesh.name ? mesh : undefined) })
  assert.ok(rig.missing.includes('这个零件改名了'), 'missing 必须报出来')
  // 灯本身照常工作, 不因为受照对象缺失而整盏失效
  rig.setLight('vision_fill', 1)
  assert.equal(mesh.material.emissiveIntensity, 4)
})
