import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

import { MOTION_TABS, THREE_D_CHILD_ROUTES } from '../../src/three-d/routes.js'

test('宿主只注册六个三维工作台且 /3d 默认进入实时页', () => {
  assert.equal(THREE_D_CHILD_ROUTES[0].redirect, '/3d/live')
  const paths = THREE_D_CHILD_ROUTES.slice(1).map((route) => route.path)
  assert.deepEqual(paths, [
    'workbench',
    'materials',
    'motion',
    'motion/:tab(mode|calib|action)/:target?',
    'demo/:flow?',
    'live',
    'sim',
    // 旧地址兼容, 不是第七个工作台
    'calib',
    'motion/:legacy(.*)',
  ])
})

test('动作工作台只有运动模式/标定/演示三个子页', () => {
  assert.deepEqual(MOTION_TABS, ['mode', 'calib', 'action'])
  const motion = THREE_D_CHILD_ROUTES.find((route) => route.name === 'three-d-motion')
  for (const tab of MOTION_TABS) {
    assert.ok(motion.path.includes(tab), `子页 ${tab} 不在路由正则里`)
  }
})

test('旧地址仍可达: /3d/calib 落到标定子页, 片段深链落到演示页', () => {
  const calib = THREE_D_CHILD_ROUTES.find((route) => route.path === 'calib')
  assert.equal(calib.redirect, '/3d/motion/calib')

  // 片段名含点号, 不匹配 :tab 正则, 由兜底重定向接到演示页
  const legacy = THREE_D_CHILD_ROUTES.find((route) => route.path === 'motion/:legacy(.*)')
  assert.equal(legacy.redirect({ params: { legacy: 'plate.tank1_put' } }), '/3d/demo/plate.tank1_put')

  const bare = THREE_D_CHILD_ROUTES.find((route) => route.path === 'motion')
  assert.equal(bare.redirect, '/3d/motion/mode')
})

test('主导航把 3D 固定放在设备和动作之间', () => {
  const railSource = fs.readFileSync(
    new URL('../../src/components/RailNav.vue', import.meta.url),
    'utf-8',
  )
  const devices = railSource.indexOf("key: 'nodes'")
  const threeD = railSource.indexOf("key: 'three_d'")
  const actions = railSource.indexOf("key: 'action'")
  assert.ok(devices >= 0 && devices < threeD && threeD < actions)
  assert.match(railSource, /key: 'three_d',[\s\S]*?base: '\/3d\/live',[\s\S]*?label: '3D'/)
})

test('主题适配器读取并监听宿主 data-theme', async () => {
  const previousDocument = globalThis.document
  const previousObserver = globalThis.MutationObserver
  let observer = null
  globalThis.document = { documentElement: { dataset: { theme: 'light' } } }
  globalThis.MutationObserver = class {
    constructor(callback) {
      this.callback = callback
      this.disconnected = false
      observer = this
    }

    observe(target, options) {
      this.target = target
      this.options = options
    }

    disconnect() {
      this.disconnected = true
    }
  }

  try {
    const theme = await import(`../../src/three-d/theme.js?test=${Date.now()}`)
    assert.equal(theme.getTheme(), 'light')
    const seen = []
    const off = theme.onThemeChange((value) => seen.push(value))
    document.documentElement.dataset.theme = 'dark'
    observer.callback()
    assert.deepEqual(seen, ['dark'])
    assert.deepEqual(observer.options.attributeFilter, ['data-theme'])
    off()
    assert.equal(observer.disconnected, true)
  } finally {
    globalThis.document = previousDocument
    globalThis.MutationObserver = previousObserver
  }
})
