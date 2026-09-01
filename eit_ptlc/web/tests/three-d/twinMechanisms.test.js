/**
 * 功能: TwinBindings._updateMechanisms 的两态缓动语义测试.
 *
 * 机构信号是布尔两态(mechanism_state 的 effective), 但几何要以 transitionS 声明的
 * 时长平滑推到端点 —— 这里锁四条行为: 首见直跳(页面加载不播历史动画)、指数缓动在
 * ~3×transitionS 内到位 95%、断流重连(resynced)直跳末态、"rigged 却无绑定"只告警
 * 一次而不是静默不动.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import { TwinBindings } from '../../src/three-d/twin/bindings/TwinBindings.js'

/** 构造最小可运行的 TwinBindings: 只喂执行器/联动组, 其余段全空 */
function makeBindings() {
  const root = new THREE.Object3D()
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'
  const flip = new THREE.Object3D(); flip.name = 'ACTUATOR_FLIP'
  const left = new THREE.Object3D(); left.name = 'ACT_L'
  const right = new THREE.Object3D(); right.name = 'ACT_R'
  root.add(mount, flip, left, right)
  const nodeIndex = new Map([...root.children].map((child) => [child.name, child]))

  const manifest = {
    stations: [],
    tanks: [],
    axes: [],
    tools: [],
    robot: { joints: [], toolMount: 'TOOL_MOUNT' },
    inventory: {},
    nodes: [],
    attachments: [],
    states: [],
    sockets: [],
    actuators: [{
      id: 'rob_flip_suction', node: 'ACTUATOR_FLIP', motion: 'rotate', axis: [0, 0, 1],
      sign: 1, inputRange: [0, 1], outputRange: [0, 180], transitionS: 0.6,
    }],
    linkages: [{
      id: 'rob_grip_plate96', inputRange: [0, 1], transitionS: 0.15,
      members: [
        // 与真 manifest 同构: 夹爪 outputRange 反向 [行程, 0] —— 信号 1=张开(GLB 基准位), 0=闭合
        { node: 'ACT_L', motion: 'translate', axis: [1, 0, 0], sign: 1, inputRange: [0, 1], outputRange: [5, 0], unitScale: 0.001 },
        { node: 'ACT_R', motion: 'translate', axis: [1, 0, 0], sign: -1, inputRange: [0, 1], outputRange: [5, 0], unitScale: 0.001 },
      ],
    }],
    realtime: {
      mechanisms: [
        { id: 'rob_flip_suction', rigged: true },
        { id: 'rob_grip_plate96', rigged: true },
        { id: 'rob_ghost', rigged: true },
      ],
    },
  }

  let states = {}
  const feed = { sampleMechanismStates: () => states }
  const bindings = new TwinBindings(manifest, nodeIndex, feed)
  return {
    bindings,
    flip,
    left,
    right,
    setStates: (next) => { states = next },
  }
}

/** 以 60 fps 推进指定秒数 */
function run(bindings, seconds) {
  const dt = 1 / 60
  for (let t = 0; t < seconds; t += dt) bindings._updateMechanisms(dt)
}

/** 节点当前旋转角(度, 绕任意轴的总角) */
function angleDeg(node) {
  return THREE.MathUtils.radToDeg(2 * Math.acos(Math.min(1, Math.abs(node.quaternion.w))))
}

test('首见状态直接就位, 不从基准位播历史动画', () => {
  const { bindings, left, right, setStates } = makeBindings()
  setStates({ rob_grip_plate96: { effective: false } })
  bindings._updateMechanisms(1 / 60)
  assert.ok(Math.abs(left.position.x - 0.005) < 1e-9, '首见闭合态(信号 0)应直接站到 +5mm')
  assert.ok(Math.abs(right.position.x + 0.005) < 1e-9, '对侧应对称到 -5mm')
})

test('两态翻转按 transitionS 缓动, ~3×transitionS 内到位 95%', () => {
  const { bindings, left, right, setStates } = makeBindings()
  setStates({ rob_grip_plate96: { effective: true } })
  bindings._updateMechanisms(1 / 60)
  assert.equal(left.position.x, 0, '张开态(信号 1)=GLB 基准位')

  setStates({ rob_grip_plate96: { effective: false } })
  bindings._updateMechanisms(1 / 60)
  const early = left.position.x
  assert.ok(early > 0 && early < 0.005, '第一帧应在闭合途中而不是瞬移')

  let previous = early
  run(bindings, 0.45)   // 3 × transitionS(0.15)
  assert.ok(left.position.x >= 0.005 * 0.95, `0.45s 后应到位 95%: ${left.position.x}`)
  assert.ok(left.position.x >= previous, '位移必须单调趋近')
  assert.ok(Math.abs(left.position.x + right.position.x) < 1e-9, '双指必须对称')

  // 收敛后继续走帧不得再动
  run(bindings, 0.3)
  const settled = left.position.x
  run(bindings, 0.3)
  assert.equal(left.position.x, settled, '收敛后不得漂移')
})

test('旋转执行器走同一缓动: 0.6s 档在 1.8s 内转到 180° 的 95%', () => {
  const { bindings, flip, setStates } = makeBindings()
  setStates({ rob_flip_suction: { effective: false } })
  bindings._updateMechanisms(1 / 60)
  assert.ok(angleDeg(flip) < 1e-6)

  setStates({ rob_flip_suction: { effective: true } })
  run(bindings, 0.3)
  const mid = angleDeg(flip)
  assert.ok(mid > 10 && mid < 175, `0.3s 时应在途中: ${mid}`)
  run(bindings, 1.5)
  assert.ok(angleDeg(flip) >= 180 * 0.95, `1.8s 后应到 171°+: ${angleDeg(flip)}`)
})

test('在途(moving)时保持在终点前, 收到到位信号才合上最后一段', () => {
  const { bindings, flip, setStates } = makeBindings()
  setStates({ rob_flip_suction: { effective: false } })
  bindings._updateMechanisms(1 / 60)

  // 发令即起步: 与实物同时开始转, 而不是等整段行程走完
  setStates({ rob_flip_suction: { effective: true, moving: true } })
  bindings._updateMechanisms(1 / 60)
  assert.ok(angleDeg(flip) > 0, '第一帧就该动起来')

  // 保持在 180° 的 85% = 153° 附近(MECHANISM_APPROACH_GAP=0.15), 且久了也不会自己
  // 走完 —— 翻转实际行程 0.6~10.8s 不定(di_or_dwell), 靠"保持 + 放行"而不是靠猜时长对齐
  run(bindings, 3.0)
  const held = angleDeg(flip)
  assert.ok(Math.abs(held - 153) < 0.5, `在途应保持在 153° 附近: ${held}`)
  run(bindings, 3.0)
  assert.ok(Math.abs(angleDeg(flip) - held) < 1e-6, '在途保持期间不得继续爬向终点')

  // 到位信号到达 -> 走完最后一段
  setStates({ rob_flip_suction: { effective: true, moving: false } })
  run(bindings, 1.2)
  assert.ok(angleDeg(flip) >= 180 - 0.5, `到位后必须合上: ${angleDeg(flip)}`)
})

test('首见就在途: 必须从对面端起步, 不得把整段行程直跳吃掉', () => {
  // 2026-08-05 用户报"上翻瞬移、下翻正常"的病根。这只缸在收到第一条命令之前根本不在
  // mechanism_state 里, 于是第一条 rotary-up 那一帧才建通道 —— 而 push() 的首见是直跳,
  // 整段 180° 被一步吃掉。开机后第一条命令通常正是上翻(CAD 基准态是下翻位),
  // 所以看起来像"按方向分叉", 其实是"首见那一程被吃掉"。
  const { bindings, flip, setStates } = makeBindings()

  // 通道尚未建立 + 第一帧就在途: 该帧必须**还在起点附近**, 而不是已经到 153°/180°
  setStates({ rob_flip_suction: { effective: true, moving: true, expectedS: 5 } })
  bindings._updateMechanisms(1 / 60)
  assert.ok(angleDeg(flip) < 5, `首见在途的第一帧应仍在起点附近: ${angleDeg(flip)}`)

  // 随后按匀速推进(180/5 = 36°/s), 并停在保持点 153°
  run(bindings, 1.0)
  assert.ok(Math.abs(angleDeg(flip) - 36) < 3, `应匀速推进: ${angleDeg(flip)}`)
  run(bindings, 5.0)
  assert.ok(Math.abs(angleDeg(flip) - 153) < 0.5, `应停在保持点: ${angleDeg(flip)}`)
})

test('首见是静态态时仍直跳: 页面加载不补播历史动画', () => {
  // 与上一条互为对照 —— 修首见在途时不能把这条既有语义一起改掉。
  const { bindings, flip, setStates } = makeBindings()
  setStates({ rob_flip_suction: { effective: true } })   // 无 moving = 静态既有姿态
  bindings._updateMechanisms(1 / 60)
  assert.ok(angleDeg(flip) >= 180 - 0.5, `静态首见必须直达末态: ${angleDeg(flip)}`)
})

test('在途段是匀速: 等长时间窗内的角度增量近似相等(不是指数递减)', () => {
  // 本次修复的核心判据。旧的指数曲线在头段冲得极快、随后越走越慢 —— 用户说的
  // "第一下翻转太快、跟实物对不上"就是它。气缸是恒速推进直到撞硬限位, 必须匀速。
  const { bindings, flip, setStates } = makeBindings()
  setStates({ rob_flip_suction: { effective: false } })
  bindings._updateMechanisms(1 / 60)

  // expectedS=5 (上位机实测的一程耗时), 行程 180° -> 36°/s
  setStates({ rob_flip_suction: { effective: true, moving: true, expectedS: 5 } })
  const windows = []
  for (let i = 0; i < 3; i += 1) {
    const before = angleDeg(flip)
    run(bindings, 1.0)
    windows.push(angleDeg(flip) - before)
  }
  for (const delta of windows) {
    assert.ok(Math.abs(delta - 36) < 2, `每秒应走约 36°(=180/5): ${windows.join(', ')}`)
  }
  // 指数曲线下第三个窗口会衰减到第一个的零头; 匀速则三窗基本相等
  assert.ok(Math.abs(windows[2] - windows[0]) < 2, `匀速: 首尾窗口应相当: ${windows.join(', ')}`)
})

test('假的极小 expectedS 不得退化成瞬移(前端最后一道兜底)', () => {
  // 2026-08-05 上翻瞬移的直接成因: 防御性复令让驱动量到 ~0.01s 并当成标定下发,
  // speed=span/0.01 一帧就走完全程。后端已挡两道, 这里锁前端自己也兜得住:
  // 就算又冒出坏值, 最多偏快, 不得一帧到位。
  const { bindings, flip, setStates } = makeBindings()
  setStates({ rob_flip_suction: { effective: false } })
  bindings._updateMechanisms(1 / 60)

  setStates({ rob_flip_suction: { effective: true, moving: true, expectedS: 0.01 } })
  bindings._updateMechanisms(1 / 60)
  assert.ok(angleDeg(flip) < 20, `第一帧不得吃掉整段行程: ${angleDeg(flip)}`)
  // 兜底速度 = 标称 0.6s 的一半 = 0.3s 走完 180°, 故 0.1s 时远未到保持点
  bindings._updateMechanisms(1 / 60)
  assert.ok(angleDeg(flip) < 153, '仍应是逐帧推进而不是已经贴在保持点')
})

test('无 expectedS 样本时按 spec.transitionS 配速', () => {
  // 首程/仿真/老后端没有实测样本, 回退 rig_map 标称值。夹具里 transitionS=0.6,
  // 行程 180° -> 300°/s, 0.3s 就该顶到保持点 153°。
  const { bindings, flip, setStates } = makeBindings()
  setStates({ rob_flip_suction: { effective: false } })
  bindings._updateMechanisms(1 / 60)

  setStates({ rob_flip_suction: { effective: true, moving: true } })
  run(bindings, 0.6)
  assert.ok(Math.abs(angleDeg(flip) - 153) < 0.5, `应回退标称值配速并顶到保持点: ${angleDeg(flip)}`)
})

test('已在目标态时收到同向命令: 一帧都不动(空翻抑制的前端侧)', () => {
  // 流程把 rotary 当状态确认重下(robot_suction_pick 同一次运行发两次 rotary-up),
  // 实物不动。后端已由 _twin_already_confirmed_at 拦掉在途公告, 这里锁前端不自己抖:
  // 收敛在终点后, 再来一帧同向的非在途状态不得产生任何位移。
  const { bindings, flip, setStates } = makeBindings()
  setStates({ rob_flip_suction: { effective: true, moving: true, expectedS: 1 } })
  run(bindings, 2.0)
  setStates({ rob_flip_suction: { effective: true, moving: false } })
  run(bindings, 2.0)
  const settled = angleDeg(flip)
  assert.ok(Math.abs(settled - 180) < 0.5, `先到位: ${settled}`)

  // 复令: 后端不公告在途, 前端看到的还是同一个已到位状态
  setStates({ rob_flip_suction: { effective: true, moving: false } })
  run(bindings, 1.0)
  assert.equal(angleDeg(flip), settled, '同向复令不得产生任何位移')
})

test('没有 moving 字段的机构走原路: 一次缓动直达终点', () => {
  const { bindings, flip, setStates } = makeBindings()
  setStates({ rob_flip_suction: { effective: false } })
  bindings._updateMechanisms(1 / 60)
  // 老后端/PLC 机构的条目里根本没有这个键, 不得因此被卡在终点前
  setStates({ rob_flip_suction: { effective: true } })
  run(bindings, 1.8)
  assert.ok(angleDeg(flip) >= 180 * 0.95, `缺省应视同已就位: ${angleDeg(flip)}`)
})

test('断流重连(resynced)直跳末态, 不沿虚构路径补间', () => {
  const { bindings, left, setStates } = makeBindings()
  setStates({ rob_grip_plate96: { effective: true } })
  bindings._updateMechanisms(1 / 60)
  setStates({ rob_grip_plate96: { effective: false } })
  bindings._updateMechanisms(1 / 60)
  assert.ok(left.position.x < 0.005 * 0.9, '此刻应仍在闭合途中')

  setStates({ rob_grip_plate96: { effective: false, resynced: true } })
  bindings._updateMechanisms(1 / 60)
  assert.ok(Math.abs(left.position.x - 0.005) < 1e-9, 'resynced 帧必须直达闭合末态')
})

test('rigged 却无执行器绑定的机构: 告警一次, 不静默也不重复刷屏', () => {
  const { bindings, setStates } = makeBindings()
  const warnings = []
  const original = console.warn
  console.warn = (...args) => { warnings.push(args.join(' ')) }
  try {
    setStates({ rob_ghost: { effective: true } })
    run(bindings, 0.1)
  } finally {
    console.warn = original
  }
  const hits = warnings.filter((line) => line.includes('rob_ghost'))
  assert.equal(hits.length, 1, `应恰好告警一次: ${JSON.stringify(warnings)}`)
})
