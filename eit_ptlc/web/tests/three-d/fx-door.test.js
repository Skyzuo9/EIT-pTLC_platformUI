/**
 * 功能: 开关门的铰链点/缓动纯函数单测 —— 铰链竖边取盒极值、另一水平轴取中,
 * 这是"门绕板中心翻"病根的解药, 数值错了门就绕错轴.
 * 另钉死 fxConfig.doors 的铰链边/开向表: 那张表被按推测填错过两轮(feed 挂在把手边、
 * back 往柜内开), 而错了页面照样跑、不报任何错, 只能靠断言兜.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { hingePoint, easeInOutSine } from '../../src/three-d-fx-preview/fx/doors.js'
import { FX_DEFAULTS } from '../../src/three-d-fx-preview/fxConfig.js'

/** 造一个世界盒(与 THREE.Box3 同形的普通对象即可, hingePoint 只读 min/max) */
function box(x0, y0, z0, x1, y1, z1) {
  return { min: { x: x0, y: y0, z: z0 }, max: { x: x1, y: y1, z: z1 } }
}

test('YZ 面门(±X 端侧门): 铰链取 z 极值, x 取板厚中心, y 取中', () => {
  // 侧门-1 的真实量级: 厚 16mm 沿 X, 面 0.718x0.667 在 YZ
  const door = box(-1.293, 0.2, -0.007, -1.277, 0.918, 0.66)
  const hinge = hingePoint(door, 'maxZ')
  assert.ok(Math.abs(hinge.z - 0.66) < 1e-9, '铰链贴 z=maxZ 竖边')
  assert.ok(Math.abs(hinge.x - -1.285) < 1e-9, 'x 取板厚中心')
  assert.ok(Math.abs(hinge.y - 0.559) < 1e-9, 'y 取盒中心')
  const other = hingePoint(door, 'minZ')
  assert.ok(Math.abs(other.z - -0.007) < 1e-9, '对开另一扇取 minZ')
})

test('XY 面门(±Z 面前后门): 铰链取 x 极值, z 取板厚中心', () => {
  // 上料门板的量级: 878x718 面在 XY, 厚 21.5mm 沿 Z
  const door = box(0.348, 0.2, 0.72, 1.226, 0.918, 0.741)
  const left = hingePoint(door, 'minX')
  assert.ok(Math.abs(left.x - 0.348) < 1e-9)
  assert.ok(Math.abs(left.z - 0.7305) < 1e-9)
  const right = hingePoint(door, 'maxX')
  assert.ok(Math.abs(right.x - 1.226) < 1e-9)
})

test('前面左半对开门: 铰链在外沿, 自由边在中缝相接', () => {
  // 固定门板-5 / -6 的真实量级(世界系, 单位 m): 面 0.738x0.718 在 XY, 厚 16mm 沿 Z
  const l1 = box(-0.472, 0.2, 0.725, 0.266, 0.918, 0.741)   // 靠 feed 那侧
  const l2 = box(-1.212, 0.2, 0.725, -0.474, 0.918, 0.741)  // 靠左端那侧
  assert.ok(Math.abs(hingePoint(l1, 'maxX').x - 0.266) < 1e-9, 'L1 铰链贴外沿 +0.27 合页立柱')
  assert.ok(Math.abs(hingePoint(l2, 'minX').x - -1.212) < 1e-9, 'L2 铰链贴外沿 -1.21 合页立柱')
  // 两扇的自由边(=把手边)在中缝相接, 这正是"对开门"的判据
  assert.ok(Math.abs(l1.min.x - l2.max.x) < 3e-3, '自由边在 X≈-0.473 对接')
})

test('门表钉死: 铰链边/开向/配对逐扇比对(填错过两轮, 靠这条兜)', () => {
  // 出处: CAD 合页件 AKQ41-G-Z-6065 定铰链边; sign 由"自由边朝机外走"解出.
  // 前面朝 +Z 开, 后面朝 -Z 开, 左端面朝 -X 开.
  const want = {
    sideL1: { hinge: 'maxZ', sign: 1, pair: 'sideL2', handle: 'XAD51-A100-6' },
    sideL2: { hinge: 'minZ', sign: -1, pair: 'sideL1', handle: 'XAD51-A100-7' },
    feed: { hinge: 'maxX', sign: 1, pair: undefined, handle: 'XAD51-A100-1' },
    back: { hinge: 'maxX', sign: -1, pair: undefined, handle: 'XAD51-A100-8' },
    frontL1: { hinge: 'maxX', sign: 1, pair: 'frontL2', handle: 'XAD51-A100-3' },
    frontL2: { hinge: 'minX', sign: -1, pair: 'frontL1', handle: 'XAD51-A100-2' },
    backL1: { hinge: 'maxX', sign: -1, pair: 'backL2', handle: 'XAD51-A100-5' },
    backL2: { hinge: 'minX', sign: 1, pair: 'backL1', handle: 'XAD51-A100-4' },
  }
  const doors = FX_DEFAULTS.doors
  const names = Object.keys(doors).filter((k) => doors[k] && typeof doors[k] === 'object')
  assert.deepEqual(names.sort(), Object.keys(want).sort(), '八扇门一个不少一个不多')
  for (const [name, spec] of Object.entries(want)) {
    const got = doors[name]
    assert.equal(got.hinge, spec.hinge, `${name} 铰链边`)
    assert.equal(got.sign, spec.sign, `${name} 开向`)
    assert.equal(got.pair, spec.pair, `${name} 配对`)
    assert.ok(got.nodes && got.nodes.length > 0, `${name} 有节点路径`)
  }
  // 配对必须互指: 只写一侧会变成"点这扇联动、点那扇只开自己"的半错状态
  for (const [name, spec] of Object.entries(want)) {
    if (!spec.pair) continue
    assert.equal(doors[spec.pair].pair, name, `${name} 与 ${spec.pair} 互指`)
  }
})

test('门表钉死: 骑在门上的五金必须挂进 nodes(漏了就悬在原地)', () => {
  // 2026-08-09 的 bug: nodes 只列门板, 开门时把手明晃晃留在关门位置.
  // 全机普查过 —— 每扇门骑着且仅骑着 1 只把手 + 1 组合页门叶, 无第三类.
  const handleOf = {
    sideL1: 'XAD51-A100-6', sideL2: 'XAD51-A100-7',
    feed: 'XAD51-A100-1', back: 'XAD51-A100-8',
    frontL1: 'XAD51-A100-3', frontL2: 'XAD51-A100-2',
    backL1: 'XAD51-A100-5', backL2: 'XAD51-A100-4',
  }
  const doors = FX_DEFAULTS.doors
  for (const [name, handle] of Object.entries(handleOf)) {
    const paths = String(doors[name].nodes).split(',').map((s) => s.trim()).filter(Boolean)
    const handles = paths.filter((p) => p.includes('XAD51-A100-'))
    const hinges = paths.filter((p) => p.includes('DOOR_HINGE_'))
    assert.equal(handles.length, 1, `${name} 应挂且只挂 1 只把手, 实得 ${handles.length}`)
    assert.ok(handles[0].endsWith(`/${handle}`), `${name} 的把手应是 ${handle}, 实得 ${handles[0]}`)
    assert.equal(hinges.length, 1, `${name} 应挂且只挂 1 组合页门叶, 实得 ${hinges.length}`)
    // 合页组节点名由管线按门键造(见 blender_clean.rename_door_hinge_leaves), 键必须对上
    assert.ok(hinges[0].endsWith(`_DOOR_HINGE_${name}`),
      `${name} 的合页组应以 _DOOR_HINGE_${name} 结尾, 实得 ${hinges[0]}`)
    // 门板必须在首位: doors.js 拿 nodes[0].parent 当 align 枢轴宿主
    assert.ok(!paths[0].includes('XAD51-A100-') && !paths[0].includes('DOOR_HINGE_'),
      `${name} 的 nodes 首位必须是门板, 实得 ${paths[0]}`)
  }
})

test('对开门开度不得撞上 feed 的扫掠圆盘', () => {
  // feed 铰链(1.226,0.730) 半径 0.878; frontL1 铰链(0.266,0.730) 叶长 0.738.
  // 两扇同开时 L1 的门板线段若进了 feed 的圆盘就会穿模 —— 110° 只剩 24mm, 不够.
  const A = { x: 0.266, z: 0.730 }
  const P = { x: 1.226, z: 0.730 }
  const R = 0.878
  const leaf = 0.738
  const clearanceMm = (deg) => {
    const t = (deg * Math.PI) / 180
    const B = { x: A.x - leaf * Math.cos(t), z: A.z + leaf * Math.sin(t) }
    const ab = { x: B.x - A.x, z: B.z - A.z }
    const ap = { x: P.x - A.x, z: P.z - A.z }
    const s = Math.max(0, Math.min(1, (ap.x * ab.x + ap.z * ab.z) / (ab.x ** 2 + ab.z ** 2)))
    const C = { x: A.x + s * ab.x, z: A.z + s * ab.z }
    return (Math.hypot(P.x - C.x, P.z - C.z) - R) * 1000
  }
  assert.ok(clearanceMm(110) < 30, '110° 余量不足 30mm —— 这就是不许抄左端那对开度的原因')
  const openDeg = FX_DEFAULTS.doors.frontL1.openDeg
  assert.ok(clearanceMm(openDeg) > 50, `实际开度 ${openDeg}° 余量应 >50mm, 实得 ${clearanceMm(openDeg).toFixed(1)}mm`)
})

test('未知铰链边回退盒中心(不炸)', () => {
  const hinge = hingePoint(box(0, 0, 0, 2, 4, 6), 'oops')
  assert.deepEqual(hinge, { x: 1, y: 2, z: 3 })
})

test('开合缓动: 端点闭合、中点过半程、单调、越界钳住', () => {
  assert.ok(Math.abs(easeInOutSine(0)) < 1e-12) // -(cos0-1)/2 是 -0, 按数值比
  assert.ok(Math.abs(easeInOutSine(1) - 1) < 1e-12)
  assert.ok(Math.abs(easeInOutSine(0.5) - 0.5) < 1e-12)
  let prev = -1
  for (let i = 0; i <= 20; i += 1) {
    const v = easeInOutSine(i / 20)
    assert.ok(v >= prev, '单调不回摆')
    prev = v
  }
  assert.ok(Math.abs(easeInOutSine(-0.5)) < 1e-12)
  assert.ok(Math.abs(easeInOutSine(1.5) - 1) < 1e-12)
})
