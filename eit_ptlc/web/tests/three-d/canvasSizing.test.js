/**
 * 功能: 锁死画布尺寸的职责边界 —— CSS 盒子归布局, 绘图缓冲归 ResizeObserver.
 *
 * 这条边界一旦被破坏(有人往 canvas.style 写了像素值), 表现是: 改窗口大小后画面被非等比
 * 拉伸, 且只有刷新页面才能恢复 —— 因为只有重新挂载才会重新钉一次那个固定像素。
 * 历史缺陷正是 Effects.resize 漏传 setSize 的第三个参数, 让 postprocessing 把 undefined
 * 透传给 renderer.setSize, 触发 three 那边 updateStyle = true 的默认值.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { Effects } from '../../src/three-d/twin/scene/Effects.js'
import { SceneManager } from '../../src/three-d/twin/scene/SceneManager.js'

test('后期链改尺寸时不许碰画布 CSS 盒(否则缩窗后画面被永久拉伸)', () => {
  const calls = []
  // 不构造真实后期链(要 WebGL 上下文), 只把真实的 resize 方法挂到假 composer 上跑
  const effects = Object.create(Effects.prototype)
  effects.composer = { setSize: (...args) => calls.push(args) }

  effects.resize(1280, 720)

  assert.deepEqual(calls, [[1280, 720, false]], 'composer.setSize 必须显式传 updateStyle=false')
})

test('渲染器改尺寸时同样不许碰画布 CSS 盒', () => {
  const previousWindow = globalThis.window
  globalThis.window = { devicePixelRatio: 2 }
  try {
    const calls = []
    const manager = Object.create(SceneManager.prototype)
    manager.disposed = false
    manager.quality = 'high'
    manager.container = { clientWidth: 1280, clientHeight: 720 }
    manager.renderer = {
      setPixelRatio: () => {},
      setSize: (...args) => calls.push(args),
    }
    manager.cameraRig = { resize: () => {} }
    manager.effects = null

    manager.resize()

    assert.deepEqual(calls, [[1280, 720, false]], 'renderer.setSize 必须显式传 updateStyle=false')
  } finally {
    globalThis.window = previousWindow
  }
})
