/**
 * 功能: 在途载荷绑定层的端到端测试(最小 three 场景, 不起渲染器).
 *
 * 覆盖用户报的那条链: 流程取整板 → 托盘挂上机械臂并跟着走 → 放到中转位坐正。
 * 以及三条纪律: 认不出身份就不动画面、断流冻结不回零、在途期间由本层独占显隐。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { TrayBinding } from '../../src/three-d/twin/bindings/TrayBinding.js'
import { TwinFeed } from '../../src/three-d/twin/bindings/TwinFeed.js'

const RACK_1 = 'ST_RACK/上料架-1/INV_RACK_COLLECTOR_1'
const STAGING_A = 'ST_COLLECT/收集瓶支架总装-1/INV_STAGING_A'
const TOOL_MOUNT = 'TOOL_MOUNT'

/**
 * 实测的夹持位姿(载荷相对 TOOL_MOUNT), 形状与 manifest 的
 * `attachments[].payload.mountLocal` 一致。数值取自真机产物 payload-grips.json 的
 * INV_RACK_COLLECTOR_1, 保持量级真实 —— INV_* 节点原点是任意的, 所以看着离法兰很远
 * 属于正常, 别照"应该在爪子附近"去改小它。
 */
const GRIP_COLLECTOR_1 = {
  position: [0.154919869, 0.003172477, -0.902362996],
  quaternion: [0.708661942, -0.006782388, -0.002905179, 0.705509611],
}

const MANIFEST = {
  robot: { toolMount: TOOL_MOUNT },
  attachments: [
    { id: 'INV_RACK_COLLECTOR_1', node: RACK_1, payload: { mountLocal: GRIP_COLLECTOR_1 } },
  ],
  inventory: {
    rack: [
      {
        kind: 'collector',
        plate: 1,
        node: RACK_1,
        items: [`${RACK_1}/INV_RACK_COLLECTOR_1_ITEM_1`, `${RACK_1}/INV_RACK_COLLECTOR_1_ITEM_2`],
      },
      { kind: 'collector', plate: 2, node: 'ST_RACK/上料架-1/INV_RACK_COLLECTOR_2', items: [] },
    ],
    staging: [
      {
        area: 'staging-a',
        kind: 'collector',
        node: STAGING_A,
        items: [`${STAGING_A}/INV_STAGING_A_ITEM_1`, `${STAGING_A}/INV_STAGING_A_ITEM_2`],
      },
    ],
  },
}

/** 造一个最小场景: 两处托盘座 + 一个会动的快换安装座。 */
function makeScene() {
  const root = new THREE.Group()
  const nodeIndex = new Map()
  const add = (path, node, parent) => {
    parent.add(node)
    nodeIndex.set(path, node)
    return node
  }

  const tray = (path, parentName, pos, items) => {
    const holder = new THREE.Group()
    holder.name = parentName
    root.add(holder)
    const node = new THREE.Group()
    node.name = path.split('/').pop()
    node.position.copy(pos)
    add(path, node, holder)
    for (const itemPath of items) {
      const item = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.05, 0.02))
      item.name = itemPath.split('/').pop()
      add(itemPath, item, node)
    }
    return node
  }

  tray(RACK_1, '上料架-1', new THREE.Vector3(-1, 0.8, 0),
    [`${RACK_1}/INV_RACK_COLLECTOR_1_ITEM_1`, `${RACK_1}/INV_RACK_COLLECTOR_1_ITEM_2`])
  tray('ST_RACK/上料架-1/INV_RACK_COLLECTOR_2', '上料架-1b', new THREE.Vector3(-1, 0.6, 0), [])
  tray(STAGING_A, '收集瓶支架总装-1', new THREE.Vector3(0.4, 0.5, 0.2),
    [`${STAGING_A}/INV_STAGING_A_ITEM_1`, `${STAGING_A}/INV_STAGING_A_ITEM_2`])

  const mount = new THREE.Group()
  mount.name = TOOL_MOUNT
  mount.position.set(0, 1.4, 0)
  add(TOOL_MOUNT, mount, root)

  root.updateMatrixWorld(true)
  return { root, nodeIndex, mount }
}

/**
 * 造一条完整的 material_state 事件。
 *
 * ⚠ 这里刻意造**事件**而不是造投影后的 snapshot: 本文件早先直接手搓 snapshot 喂给
 * TrayBinding, 于是绕开了 MaterialStateStore 的归一化 —— 而 2026-08-05 那次"托盘不跟手"
 * 恰恰就丢在那一层(normalizeSnapshot 是显式白名单, 没列 transit)。测下游时把上游一起
 * 串上, 这类"中间层吃掉字段"才拦得住。
 */
let seq = 0
function materialEvent({ transit = {}, stagingPlate = null } = {}) {
  seq += 1
  const cells = []
  for (const kind of ['collector', 'bottle']) {
    for (let plate = 1; plate <= 6; plate += 1) {
      for (let hole = 1; hole <= 6; hole += 1) {
        cells.push({ kind, plate, hole, state: 'FRESH', sample_id: '' })
      }
    }
  }
  return {
    type: 'material_state', seq, ts: 1_700_000_000 + seq,
    cells,
    staging: {
      'staging-a': { area: 'staging-a', kind: 'collector', plate: stagingPlate },
      'staging-b': { area: 'staging-b', kind: 'bottle', plate: null },
    },
    transit,
    summary: {}, presence: [], presence_mismatches: 0,
    magazines: [], bottles: [], topology: null,
  }
}

function makeBinding() {
  const { root, nodeIndex, mount } = makeScene()
  const feed = new TwinFeed({ axes: [], stations: [], realtime: { mechanisms: [] } })
  feed.setTransportState(true)
  const binding = new TrayBinding({
    manifest: MANIFEST,
    resolve: (path) => nodeIndex.get(path) || nodeIndex.get(String(path).split('/').pop()),
    feed,
  })
  // 与 useTwinScene 的接线一致: 节点事件由 TwinFeed 配对好入参后投递给本层。
  // 测试里必须一并接上, 否则 L2 的合爪/松爪信号根本到不了 —— 那正是"只测下游"的老毛病。
  feed.addNodeSink((event, args) => binding.handleEvent(event, args))
  return {
    binding,
    root,
    mount,
    nodeIndex,
    feed,
    /** 走真实事件流: 投一帧 material_state 再推进一帧。 */
    push(event, delta = 0) {
      feed.handleEvent(event)
      return binding.update(delta)
    },
  }
}

const TRAY_ON_GRIP = {
  gripper_plate96: {
    carrier: 'gripper_plate96', payload: 'tray', kind: 'collector', plate: 1,
    hole: null, from_loc: 'rack', to_loc: '', since_at: 1, run_id: 'r1',
  },
}

/** 断言托盘此刻在法兰系下的局部位姿等于实测夹持位姿。 */
function assertPinned(tray, message) {
  const wantP = new THREE.Vector3().fromArray(GRIP_COLLECTOR_1.position)
  const wantQ = new THREE.Quaternion().fromArray(GRIP_COLLECTOR_1.quaternion).normalize()
  assert.ok(tray.position.distanceTo(wantP) < 1e-6,
    `${message}: 位置 ${tray.position.toArray()} 应为 ${wantP.toArray()}`)
  assert.ok(1 - Math.abs(tray.quaternion.dot(wantQ)) < 1e-6, `${message}: 姿态不符`)
}

test('取整板: 托盘挂上 TOOL_MOUNT, 并钉到实测夹持位姿(不是保世界位姿)', () => {
  const { binding, mount, nodeIndex, push } = makeBinding()
  const tray = nodeIndex.get(RACK_1)
  tray.visible = false                       // TwinBindings 初始把它藏起来了

  assert.equal(push(materialEvent({ transit: TRAY_ON_GRIP })), true, '应报告动过场景')
  assert.equal(tray.parent, mount, '托盘应挂到快换安装座下')
  assertPinned(tray, '挂上后')
  assert.equal(tray.visible, true, '在途托盘必须可见 —— 账本此刻两处都说没有它')
  assert.ok(binding.owned.has(RACK_1), '显隐控制权应移交本层')
  assert.deepEqual(binding.status().carried, { gripper_plate96: 'rack.collector.1' })
})

test('换父时机械臂**不在取料点**, 位姿依然正确 —— 这条就是"虚空旋转"的回归', () => {
  // 真实时序: 在途行是 robot_group_rack_pick DONE 时才落账, 而那个脚本以
  // P7 -> P1 -> require_anchor(P1) 收尾 —— 换父时臂早已退回 home、离取料点一米开外。
  // 保世界位姿在这种时刻会把托盘冻在货架的世界位置却挂在 home 的法兰下(差约一米),
  // 随臂刚性转动 = 用户看到的"托盘在虚空里跟着转"。
  const { mount, nodeIndex, push } = makeBinding()
  mount.position.set(3.0, 2.0, -1.5)         // 把法兰挪到与货架毫不相干的地方
  mount.rotateY(1.1)
  mount.updateMatrixWorld(true)

  push(materialEvent({ transit: TRAY_ON_GRIP }))
  const tray = nodeIndex.get(RACK_1)
  assert.equal(tray.parent, mount)
  assertPinned(tray, '臂不在取料点时挂载')

  // 而且它必须真的跟在爪子边上, 不是挂在一米开外
  const gap = tray.getWorldPosition(new THREE.Vector3())
    .distanceTo(mount.getWorldPosition(new THREE.Vector3()))
  const nominal = new THREE.Vector3().fromArray(GRIP_COLLECTOR_1.position).length()
  assert.ok(Math.abs(gap - nominal) < 1e-6, `托盘到法兰的距离应恒为 ${nominal}, 实际 ${gap}`)
})

test('缺 mountLocal 时退回保世界位姿, 并喊出来', () => {
  const { nodeIndex } = makeScene()
  const feed = new TwinFeed({ axes: [], stations: [], realtime: { mechanisms: [] } })
  feed.setTransportState(true)
  const warnings = []
  const original = console.warn
  console.warn = (msg) => warnings.push(String(msg))
  try {
    const binding = new TrayBinding({
      manifest: { ...MANIFEST, attachments: [] },   // 老 manifest: 没量过夹持位姿
      resolve: (path) => nodeIndex.get(path) || nodeIndex.get(String(path).split('/').pop()),
      feed,
    })
    const tray = nodeIndex.get(RACK_1)
    const before = tray.getWorldPosition(new THREE.Vector3())
    feed.handleEvent(materialEvent({ transit: TRAY_ON_GRIP }))
    binding.update(0.016)
    assert.ok(tray.getWorldPosition(new THREE.Vector3()).distanceTo(before) < 1e-9,
      '兜底路径仍是保世界位姿')
    assert.ok(warnings.some((w) => w.includes('mountLocal')), '必须告警, 不能静默降级')
  } finally {
    console.warn = original
  }
})

test('托盘跟着机械臂刚性走 (6 个耗材件作为子级免费跟随)', () => {
  const { mount, nodeIndex, push } = makeBinding()
  push(materialEvent({ transit: TRAY_ON_GRIP }))
  const tray = nodeIndex.get(RACK_1)
  const item = nodeIndex.get(`${RACK_1}/INV_RACK_COLLECTOR_1_ITEM_1`)

  const before = tray.getWorldPosition(new THREE.Vector3())
  const itemBefore = item.getWorldPosition(new THREE.Vector3())
  mount.position.x += 0.5
  mount.updateMatrixWorld(true)

  assert.ok(Math.abs(tray.getWorldPosition(new THREE.Vector3()).x - before.x - 0.5) < 1e-9)
  assert.ok(Math.abs(item.getWorldPosition(new THREE.Vector3()).x - itemBefore.x - 0.5) < 1e-9)
})

test('钉位姿会让托盘跳一下 —— 那是纠错, 不是 bug', () => {
  // 与 PlateStage.carry 第 2 级同理: 跳掉的正是"换父那一刻的示教残差/错位"。
  // 刻意断言它**会**变, 免得将来有人以为"世界位姿保持"是本层的契约又改回去。
  const { nodeIndex, push } = makeBinding()
  const tray = nodeIndex.get(RACK_1)
  const before = tray.getWorldPosition(new THREE.Vector3())
  push(materialEvent({ transit: TRAY_ON_GRIP }))
  assert.ok(tray.getWorldPosition(new THREE.Vector3()).distanceTo(before) > 1e-6,
    '钉到夹持位姿必然改变世界位姿(本场景的法兰不在取料点)')
  assertPinned(tray, '钉位姿后')
})

test('放下: 换回原父级, 补间走完坐正回 CAD 位姿, 显隐控制权交还', () => {
  const { binding, nodeIndex, push } = makeBinding()
  const tray = nodeIndex.get(RACK_1)
  const home = tray.position.clone()
  const holder = tray.parent

  push(materialEvent({ transit: TRAY_ON_GRIP }))
  assert.notEqual(tray.parent, holder)

  // 落位: 在途行消失, 中转位记上板号。本场景行程 > MAX_SETTLE_TRAVEL_M, 走瞬间就位
  // 路径 ⇒ 交权也是立即的
  push(materialEvent({ stagingPlate: 1 }))
  assert.equal(tray.parent, holder, '应换回原父级')
  assert.equal(binding.owned.has(RACK_1), false, '显隐控制权应交还 TwinBindings')

  for (let i = 0; i < 40; i += 1) binding.update(0.05)
  assert.ok(tray.position.distanceTo(home) < 1e-6, '补间走完必须坐正回设计位, 不留换父残差')
})

test('短行程落位: 补间期间接管权保持, 补间走完才交还 (2026-08-15 倒扣桶的前置)', () => {
  const { binding, nodeIndex, push } = makeBinding()
  const tray = nodeIndex.get(RACK_1)
  const home = tray.position.clone()
  const holder = tray.parent

  push(materialEvent({ transit: TRAY_ON_GRIP }))
  // 把托盘挪到"目的座正上方"(行程远小于 MAX_SETTLE_TRAVEL_M) —— 逼出补间路径。
  // 早交权的话, TwinBindings 当帧写的姿态(如已用粉桶倒扣)会被补间每帧抹回。
  const homeWorld = holder.localToWorld(home.clone().add(new THREE.Vector3(0, 0.01, 0)))
  tray.position.copy(tray.parent.worldToLocal(homeWorld))
  tray.updateMatrixWorld(true)

  push(materialEvent({ stagingPlate: 1 }))
  assert.equal(tray.parent, holder, '应换回原父级')
  assert.equal(binding.owned.has(RACK_1), true, '补间期间接管权必须保持(否则两写者互抹)')

  binding.update(0.05)
  assert.equal(binding.owned.has(RACK_1), true, '补间中途仍不交权')

  for (let i = 0; i < 40; i += 1) binding.update(0.05)
  assert.equal(binding.owned.has(RACK_1), false, '补间走完交还显隐控制权')
  assert.equal(binding.consumeOwnedDirty(), true, '交权要举 ownedDirty 旗, 宿主才会强制重算')
  assert.ok(tray.position.distanceTo(home) < 1e-6, '坐正回设计位')
})

test('单件在途: 只飞那一个耗材件, 托盘本体不动', () => {
  const { binding, mount, nodeIndex, push } = makeBinding()
  push(materialEvent({
    stagingPlate: 1,
    transit: {
      gripper_vial: {
        carrier: 'gripper_vial', payload: 'item', kind: 'collector', plate: 1,
        hole: 2, from_loc: 'staging', to_loc: '', since_at: 1, run_id: 'r1',
      },
    },
  }))
  const item = nodeIndex.get(`${STAGING_A}/INV_STAGING_A_ITEM_2`)
  assert.equal(item.parent, mount)
  assert.notEqual(nodeIndex.get(STAGING_A).parent, mount, '托盘本体应留在原座上')
  assert.ok(binding.owned.has(`${STAGING_A}/INV_STAGING_A_ITEM_2`))
  assert.equal(binding.owned.has(STAGING_A), false, '托盘本体不该被接管')
})

test('两把爪可同时各拿一件, 互不干扰', () => {
  const { binding, push } = makeBinding()
  push(materialEvent({
    stagingPlate: 2,
    transit: {
      ...TRAY_ON_GRIP,
      gripper_vial: {
        carrier: 'gripper_vial', payload: 'item', kind: 'collector', plate: 2,
        hole: 1, from_loc: 'staging', to_loc: '', since_at: 1, run_id: 'r1',
      },
    },
  }))
  assert.deepEqual(binding.status().carried, {
    gripper_plate96: 'rack.collector.1',
    gripper_vial: 'staging-a#1',
  })
})

test('身份认不出就不动画面 —— 绝不挂一块编出来的托盘', () => {
  const { binding, nodeIndex, push } = makeBinding()
  const tray = nodeIndex.get(RACK_1)
  const holder = tray.parent
  // 板号 6 在本场景的 manifest 里没有对应节点
  push(materialEvent({
    transit: {
      gripper_plate96: {
        carrier: 'gripper_plate96', payload: 'tray', kind: 'collector', plate: 6,
        hole: null, from_loc: 'rack', to_loc: '', since_at: 1, run_id: 'r1',
      },
    },
  }))
  assert.equal(tray.parent, holder)
  assert.deepEqual(binding.status().carried, {})
})

test('断流冻结: 托盘留在爪上, 绝不自己掉回货架', () => {
  const { binding, mount, nodeIndex, push } = makeBinding()
  push(materialEvent({ transit: TRAY_ON_GRIP }))
  binding.markDisconnected()
  binding.update(0.05)
  assert.equal(nodeIndex.get(RACK_1).parent, mount)
})

test('快照对象没换就不重算归属 (0.5s 一帧的账本不该逐帧翻场景图)', () => {
  const { push } = makeBinding()
  // 同一份事件重投: MaterialStateStore 会按 ts+seq 判重拒收, 快照对象不换,
  // TrayBinding 也就不该再翻一遍场景图
  const frame = materialEvent({ transit: TRAY_ON_GRIP })
  assert.equal(push(frame), true)
  assert.equal(push(frame), false, '同一帧重复投递不应再动场景')
})

// ── L2: 合爪即挂 / 松爪即放 ─────────────────────────────────────────────────
// 这一组钉的是**时刻**。在途行要等 robot_group_rack_pick DONE 才落账, 而那个脚本以
// P7 → P1 收尾 —— 只靠 L1, 机械臂会拎着托盘走十几秒而爪子是空的(用户实测报的第一条)。

/** 造一条 run_script 的 vm_node_enter。 */
const enterScript = (script, args, runId = 'r1') => ({
  type: 'vm_node_enter', run_id: runId, script: 'demo', aid: 'b1',
  op: 'run_script', action: script, args,
})
/** 造一条夹爪动作完成的 vm_node_done(script = 它所在的脚本帧)。 */
const gripDone = (script, action, runId = 'r1') => ({
  type: 'vm_node_done', run_id: runId, script, aid: 'g1',
  op: 'call', action: 'robot.tool_action', status: 'DONE', args: { action },
})

test('L2: 合爪那一帧就挂上, 不等在途行落账', () => {
  const { binding, mount, nodeIndex, feed } = makeBinding()
  const tray = nodeIndex.get(RACK_1)

  feed.handleEvent(enterScript('robot_group_rack_pick', { rack_id: 'collector', slot_id: 1 }))
  feed.handleEvent(gripDone('robot_group_rack_pick', 'gripper-close'))
  assert.equal(tray.parent, mount, '合爪即挂')
  assertPinned(tray, 'L2 抢跑挂载')
  assert.deepEqual(binding.status().carried, { gripper_plate96: 'rack.collector.1' })
})

test('L2 抢跑后, 账本还没落账那几帧不得被当成"已放下"', () => {
  const { binding, mount, nodeIndex, feed, push } = makeBinding()
  feed.handleEvent(enterScript('robot_group_rack_pick', { rack_id: 'collector', slot_id: 1 }))
  feed.handleEvent(gripDone('robot_group_rack_pick', 'gripper-close'))

  // 账本此刻仍是空的(在途行要等脚本 DONE) —— 推几帧空快照
  push(materialEvent({}))
  push(materialEvent({}))
  assert.equal(nodeIndex.get(RACK_1).parent, mount, '不能因为账本没跟上就把托盘丢回货架')
  assert.deepEqual(binding.status().carried, { gripper_plate96: 'rack.collector.1' })

  // 账本到货 -> L1 接管, 位姿不变
  push(materialEvent({ transit: TRAY_ON_GRIP }))
  assert.equal(nodeIndex.get(RACK_1).parent, mount)
  assertPinned(nodeIndex.get(RACK_1), 'L1 接管后')
})

test('L2: 松爪即放, 不等放料脚本跑完', () => {
  const { binding, nodeIndex, feed } = makeBinding()
  const tray = nodeIndex.get(RACK_1)
  const holder = tray.parent
  feed.handleEvent(enterScript('robot_group_rack_pick', { rack_id: 'collector', slot_id: 1 }))
  feed.handleEvent(gripDone('robot_group_rack_pick', 'gripper-close'))
  assert.notEqual(tray.parent, holder)

  feed.handleEvent(gripDone('robot_group_staging_put', 'gripper-open'))
  assert.equal(tray.parent, holder, '松爪即放')
  assert.deepEqual(binding.status().carried, {})
})

test('L1 已认领之后, 松爪照样立刻放 —— 这条就是"松爪了还夹着"的回归', () => {
  // 病根: 第一版用一个 Set 记"L2 抢跑挂上的爪", 松爪时只放这个集合里的;
  // 而 L1 在搬运途中必然追上并撤掉标记, 于是正常流程下松爪那一支永远不执行,
  // 只能等放料脚本 DONE(那时臂已退刀) —— 用户看到的就是"松开夹爪后托盘还夹着,
  // 整个动作跑完才闪回落点"。
  const { binding, nodeIndex, feed, push } = makeBinding()
  const tray = nodeIndex.get(RACK_1)
  const holder = tray.parent

  feed.handleEvent(enterScript('robot_group_rack_pick', { rack_id: 'collector', slot_id: 1 }))
  feed.handleEvent(gripDone('robot_group_rack_pick', 'gripper-close'))
  push(materialEvent({ transit: TRAY_ON_GRIP }))          // L1 追上, 认领这把爪
  assert.deepEqual(binding.status().carried, { gripper_plate96: 'rack.collector.1' })

  feed.handleEvent(gripDone('robot_group_staging_put', 'gripper-open'))
  assert.equal(tray.parent, holder, 'L1 认领过也必须能松爪即放')
  assert.deepEqual(binding.status().carried, {})
})

test('松爪后账本还说在途, 不得把托盘再抓回爪上', () => {
  // 在途行要等放料脚本 DONE 才清。这中间账本描述的是过去, L1 不能推翻 L2 的松爪。
  const { binding, mount, nodeIndex, feed, push } = makeBinding()
  const tray = nodeIndex.get(RACK_1)
  const holder = tray.parent

  feed.handleEvent(enterScript('robot_group_rack_pick', { rack_id: 'collector', slot_id: 1 }))
  feed.handleEvent(gripDone('robot_group_rack_pick', 'gripper-close'))
  push(materialEvent({ transit: TRAY_ON_GRIP }))
  feed.handleEvent(gripDone('robot_group_staging_put', 'gripper-open'))
  assert.equal(tray.parent, holder)

  // 账本仍是旧的在途行 —— 推几帧
  push(materialEvent({ transit: TRAY_ON_GRIP }))
  push(materialEvent({ transit: TRAY_ON_GRIP }))
  assert.equal(tray.parent, holder, '账本落后不该把已放下的托盘抓回去')
  assert.notEqual(tray.parent, mount)
  assert.deepEqual(binding.status().carried, {})

  // 账本清掉在途行 -> 两边一致, 交还 L1, 仍然在座上
  push(materialEvent({ stagingPlate: 1 }))
  assert.equal(tray.parent, holder)
  assert.deepEqual(binding.status().carried, {})
})

test('松爪的是哪把爪按放料脚本名定, 不误放另一把', () => {
  const { binding, feed, push } = makeBinding()
  // 大爪拿整板(L1), 小爪拿单件(L1)
  push(materialEvent({
    stagingPlate: 2,
    transit: {
      ...TRAY_ON_GRIP,
      gripper_vial: {
        carrier: 'gripper_vial', payload: 'item', kind: 'collector', plate: 2,
        hole: 1, from_loc: 'staging', to_loc: '', since_at: 1, run_id: 'r1',
      },
    },
  }))
  assert.equal(Object.keys(binding.status().carried).length, 2)

  // 小爪的放料脚本松爪 -> 只放小爪那件
  feed.handleEvent(gripDone('robot_individual_put', 'gripper-open'))
  assert.deepEqual(binding.status().carried, { gripper_plate96: 'rack.collector.1' })
})

test('L2: 放料脚本开头的空爪合拢不得误挂', () => {
  const { binding, nodeIndex, feed } = makeBinding()
  const holder = nodeIndex.get(RACK_1).parent
  // 没有取料脚本上下文, 且 script 名不以 _pick 结尾
  feed.handleEvent(gripDone('robot_group_staging_put', 'gripper-close'))
  assert.equal(nodeIndex.get(RACK_1).parent, holder)
  assert.deepEqual(binding.status().carried, {})
})

test('L2: 认不出身份就什么都不做 —— 绝不挂一件猜出来的载荷', () => {
  const { binding, nodeIndex, feed } = makeBinding()
  const holder = nodeIndex.get(RACK_1).parent
  // 库位 6 在本场景的 manifest 里没有对应节点
  feed.handleEvent(enterScript('robot_group_rack_pick', { rack_id: 'collector', slot_id: 6 }))
  feed.handleEvent(gripDone('robot_group_rack_pick', 'gripper-close'))
  assert.equal(nodeIndex.get(RACK_1).parent, holder)
  assert.deepEqual(binding.status().carried, {})
})

test('L2: 断流丢弃在途取料上下文, 重连后不拿过期身份去挂', () => {
  const { binding, nodeIndex, feed } = makeBinding()
  const holder = nodeIndex.get(RACK_1).parent
  feed.handleEvent(enterScript('robot_group_rack_pick', { rack_id: 'collector', slot_id: 1 }))
  binding.markDisconnected()
  feed.handleEvent(gripDone('robot_group_rack_pick', 'gripper-close'))
  assert.equal(nodeIndex.get(RACK_1).parent, holder)
  assert.deepEqual(binding.status().carried, {})
})

test('缺 TOOL_MOUNT 时如实上报, 不静默把托盘挂到别处', () => {
  const { nodeIndex } = makeScene()
  const feed = new TwinFeed({ axes: [], stations: [], realtime: { mechanisms: [] } })
  feed.setTransportState(true)
  feed.handleEvent(materialEvent({ transit: TRAY_ON_GRIP }))
  const binding = new TrayBinding({
    manifest: { ...MANIFEST, robot: { toolMount: 'NO_SUCH_MOUNT' } },
    resolve: (path) => nodeIndex.get(path),
    feed,
  })
  assert.ok(binding.missing.includes('NO_SUCH_MOUNT'))
  assert.equal(binding.status().toolMountBound, false)
  binding.update(0.05)
  assert.deepEqual(binding.status().carried, {}, '挂不上就不挂, 不找替身')
})
