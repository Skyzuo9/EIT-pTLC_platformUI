/**
 * 功能: 注射泵 `pump`/`pump_valve` 连续通道 —— 编译、插值、驱动层写入与清场.
 *
 * 两条通道两种单位, 都是刻意的(与 liquidChannel.test.js 钉 liquid 的方式同构):
 *   1. `pump:<id>` 存**毫升**: 柱塞位移/液柱高度/丝杆转角是同一个自由度(阀头在下,
 *      柱塞上行即吸液), 换算所需的 travelM/leadTurnsPerStroke/syringeMl 都是 03 构建
 *      产物, 烘进片段就是陈旧隐患 —— 全部留到写入层(setPumpMl)按 manifest 现算;
 *   2. `pumpPort:<id>` 存**端口号**(1 基): 各口的指针角度(valvePortAngles)同样每跑
 *      一次 03 就变, 片段只说"去 2 号口", 角度留到写入层查表.
 *
 * 防漂主测: 驱动层写出的柱塞/液柱/丝杆几何必须与实时链(TwinBindings._updatePumps)
 * 逐位一致 —— 两条链高低不一时, 各自看着都挺正常.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { compileClip, evaluateChannels } from '../../src/three-d/anim/clipSchema.js'
import { MachineStateDriver } from '../../src/three-d/anim/MachineStateDriver.js'
import {
  applyLiquidLevel, captureLiquidBase,
} from '../../src/three-d/twin/bindings/liquidPivot.js'

/** 与 device-manifest.pumpSyringe 同形的最小配置(角度取自 T-06 阀头的真实下半弧) */
const PORT_ANGLES = [335, 309, 283, 257, 231, 205]

/** 一段"换阀→吸液→换阀→打空"的最小片段 */
function fillClip() {
  return {
    schema: 'ptlc.clip/v1',
    name: 'pump_fill',
    home: { pump_ml: { DEV1: 0 }, pump_port: { DEV1: 1 } },
    steps: [
      { label: '展开泵1·阀→2号口', dur: 0.4, do: { pump_valve: { id: 'DEV1', port: 2 } } },
      { label: '展开泵1·吸液 0.0 → 20.0 mL', dur: 20, ease: 'out', do: { pump: { id: 'DEV1', to_ml: 20 } } },
      { label: '展开泵1·阀→6号口', dur: 0.4, do: { pump_valve: { id: 'DEV1', port: 6 } } },
      { label: '展开泵1·排液 20.0 → 0.0 mL', dur: 20, ease: 'out', do: { pump: { id: 'DEV1', to_ml: 0 } } },
    ],
  }
}

/**
 * 造一台泵的可动组 + 最小 manifest.
 *
 * 液柱建模位 scale.y=1.5(满行程), 与展缸夹具同款 —— 非 1 的基准才能验出
 * "按比例缩放"而不是"直接写绝对值"; 材质共用一份, 验驱动层没有偷偷克隆.
 */
function makePumpRig({ withValve = true, withAngles = true } = {}) {
  const root = new THREE.Group()
  const nodes = new Map()
  const shared = new THREE.MeshStandardMaterial({ color: '#bfd8e8' })

  const put = (name, mesh) => {
    mesh.name = name
    root.add(mesh)
    nodes.set(`ST_PUMP/展缸注射泵总装-2/${name}`, mesh)
    return `ST_PUMP/展缸注射泵总装-2/${name}`
  }
  const plungerPath = put('ACTUATOR_PUMP_PLUNGER_DEV1', new THREE.Mesh(new THREE.CylinderGeometry(0.011, 0.011, 0.06), shared))
  const liquid = new THREE.Mesh(new THREE.CylinderGeometry(0.011, 0.011, 0.06), shared)
  liquid.scale.set(1, 1.5, 1)
  const liquidPath = put('LIQUID_PUMP_DEV1', liquid)
  const valvePath = withValve
    ? put('ACTUATOR_PUMP_VALVE_DEV1', new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.015), shared))
    : null
  const leadPath = put('ACTUATOR_PUMP_LEAD_DEV1', new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 0.08), shared))

  const manifest = {
    pumpSyringe: {
      syringeMl: 25,
      strokeMm: 60,
      stepsPerStroke: 6000,
      pumps: [
        {
          id: 'DEV1',
          label: '展开泵 1(缸 1-4)',
          rigged: true,
          plungerNode: plungerPath,
          liquidNode: liquidPath,
          travelAxis: [0, 1, 0],
          travelM: 0.06,
          valveNode: valvePath,
          valveAxis: [0, 0, -1],
          valvePorts: 6,
          valvePortAngles: withAngles ? [...PORT_ANGLES] : undefined,
          leadNode: leadPath,
          leadAxis: [0, 1, 0],
          leadTurnsPerStroke: 10,
        },
        // 收集泵: CAD 无泵体的降级形态 —— 数据仍走模型, 三维不动
        { id: 'COL', label: '收集泵', rigged: false, plungerNode: null, liquidNode: null },
      ],
    },
  }
  const rig = new MachineStateDriver({ manifest, resolve: (p) => nodes.get(p) })
  return { rig, nodes, shared, manifest }
}

function nodeOf(nodes, name) {
  return nodes.get(`ST_PUMP/展缸注射泵总装-2/${name}`)
}

/** 阀/丝杆期望姿态: base × axisAngle —— 与 TwinBindings._updatePumps 同一公式 */
function expectedQuat(base, axis, rad) {
  return base.clone().multiply(new THREE.Quaternion().setFromAxisAngle(axis, rad))
}

test('pump/pump_valve 是连续通道: 编译进 channels 而不是 events', () => {
  const clip = compileClip(fillClip())
  assert.equal(clip.events.length, 0, '泵不该产生离散事件')
  assert.ok(clip.channels.has('pump:DEV1'))
  assert.ok(clip.channels.has('pumpPort:DEV1'))
})

test('体积/阀位按关键帧插值, 任意 t 都是纯函数(seek 安全)', () => {
  const clip = compileClip(fillClip())
  const at = (t) => evaluateChannels(clip, t)

  assert.equal(at(0).pumps.DEV1, 0, 't=0 是 home 声明的起始体积')
  assert.equal(at(0).pumpPorts.DEV1, 1, 't=0 是 home 声明的 1 号口')
  assert.equal(at(0.4).pumpPorts.DEV1, 2, '换阀步结束停在 2 号口')
  const mid = at(10).pumps.DEV1
  assert.ok(mid > 0 && mid < 20, '吸液中途在两端之间')
  assert.equal(at(20.4).pumps.DEV1, 20, '吸满 20mL')
  assert.ok(Math.abs(at(99).pumps.DEV1) < 1e-9, '打空后保持终值')
  for (const t of [0.2, 5, 10.3, 20.6, 30]) {
    assert.equal(at(t).pumps.DEV1, at(t).pumps.DEV1, `t=${t} 求值不稳定`)
  }
})

test('只在 home.pump_ml 里声明、没有任何步骤的泵也要建通道(起手气隙不许被清场吃掉)', () => {
  // 钉 rig.home() 清零 + "只应用有通道的量"那条链: sampling.prep 停在 0.2mL 气隙,
  // 下一条片段若只声明不驱动, 不建通道就会开局回 0 —— 与 7Y 点样座/满缸液面同一形状.
  const clip = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'hold_gap',
    home: { pump_ml: { SMP: 0.2 } },
    steps: [{ label: '等待', dur: 2, do: { wait: {} } }],
  })
  assert.ok(clip.channels.has('pump:SMP'), 'home 里声明的泵必须各自成一条通道')
  assert.equal(evaluateChannels(clip, 0).pumps.SMP, 0.2)
  assert.equal(evaluateChannels(clip, 2).pumps.SMP, 0.2, '没人驱动就一直保持声明值')
})

test('pump/pump_valve 参数非法在编译期就报错', () => {
  const build = (kind, body) => () => compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bad',
    steps: [{ label: 'x', dur: 1, do: { [kind]: body } }],
  })
  assert.throws(build('pump', { to_ml: 10 }), /缺 id\/to_ml/)
  assert.throws(build('pump', { id: 'DEV1' }), /缺 id\/to_ml/)
  assert.throws(build('pump', { id: 'DEV1', to_ml: -1 }), /非负毫升数/)
  assert.throws(build('pump_valve', { id: 'DEV1' }), /缺 id\/port/)
  assert.throws(build('pump_valve', { id: 'DEV1', port: 0 }), /≥1 的整数端口号/)
  assert.throws(build('pump_valve', { id: 'DEV1', port: 2.5 }), /≥1 的整数端口号/)
})

test('柱塞平移 = base + travelAxis×travelM×level —— 与实时链同一公式(防漂主测)', () => {
  const { rig, nodes } = makePumpRig()
  const plunger = nodeOf(nodes, 'ACTUATOR_PUMP_PLUNGER_DEV1')
  const base = plunger.position.clone()

  for (const ml of [0, 1, 12.5, 25]) {
    rig.setPumpMl('DEV1', ml)
    const expected = base.clone().add(new THREE.Vector3(0, 1, 0).multiplyScalar(0.06 * (ml / 25)))
    assert.ok(plunger.position.distanceTo(expected) < 1e-12, `${ml}mL: 柱塞位置漂了`)
  }
  // 1 mL ≡ 2.4 mm: 针筒是标定过的量具, 这个数与上位机离线单测同源
  rig.setPumpMl('DEV1', 1)
  assert.ok(Math.abs(plunger.position.y - base.y - 0.0024) < 1e-12, '1mL 不等于 2.4mm 行程')
})

test('液柱与柱塞同相涨落, 且与实时链的 applyLiquidLevel 逐位相同(几何版防漂)', () => {
  const { rig, nodes } = makePumpRig()
  const liquid = nodeOf(nodes, 'LIQUID_PUMP_DEV1')
  // 参照节点走实时链同一条 applyLiquidLevel(TwinBindings._updatePumps 的写法)
  const twin = new THREE.Mesh(new THREE.CylinderGeometry(0.011, 0.011, 0.06), new THREE.MeshStandardMaterial())
  twin.scale.set(1, 1.5, 1)
  const base = captureLiquidBase(twin)

  for (const ml of [0, 1, 12.5, 25]) {
    rig.setPumpMl('DEV1', ml)
    applyLiquidLevel(base, twin, ml / 25)
    assert.deepEqual(liquid.scale.toArray(), twin.scale.toArray(), `${ml}mL: 液柱 scale 漂了`)
    assert.deepEqual(liquid.position.toArray(), twin.position.toArray(), `${ml}mL: 液柱 position 漂了`)
  }
  rig.setPumpMl('DEV1', 0)
  assert.equal(liquid.visible, false, '空筒必须整体隐藏, 不留压扁的顶面')
  rig.setPumpMl('DEV1', 5)
  assert.equal(liquid.visible, true, '有液就得画出来')
})

test('丝杆转角 = level × leadTurnsPerStroke × 2π, 与柱塞刚性同相', () => {
  const { rig, nodes } = makePumpRig()
  const lead = nodeOf(nodes, 'ACTUATOR_PUMP_LEAD_DEV1')
  const leadBase = lead.quaternion.clone()
  const axis = new THREE.Vector3(0, 1, 0)

  for (const ml of [0, 5, 12.5, 25]) {
    rig.setPumpMl('DEV1', ml)
    const expected = expectedQuat(leadBase, axis, (ml / 25) * 10 * Math.PI * 2)
    assert.ok(Math.abs(lead.quaternion.dot(expected)) > 1 - 1e-9, `${ml}mL: 丝杆角度漂了`)
  }
})

test('阀指针按 valvePortAngles 查表(下半弧), 小数口号分段插值, 缺表退均布', () => {
  const { rig, nodes } = makePumpRig()
  const valve = nodeOf(nodes, 'ACTUATOR_PUMP_VALVE_DEV1')
  const valveBase = valve.quaternion.clone()
  const axis = new THREE.Vector3(0, 0, -1)

  for (let port = 1; port <= 6; port += 1) {
    rig.setPumpValvePort('DEV1', port)
    const expected = expectedQuat(valveBase, axis, (PORT_ANGLES[port - 1] / 360) * Math.PI * 2)
    assert.ok(Math.abs(valve.quaternion.dot(expected)) > 1 - 1e-9, `${port}号口角度不对`)
  }
  // 通道在两口之间插值时口号是小数: 角度按相邻两口分段线性
  rig.setPumpValvePort('DEV1', 2.5)
  const midDeg = (PORT_ANGLES[1] + PORT_ANGLES[2]) / 2
  const expectedMid = expectedQuat(valveBase, axis, (midDeg / 360) * Math.PI * 2)
  assert.ok(Math.abs(valve.quaternion.dot(expectedMid)) > 1 - 1e-9, '2.5 口没有落在 2/3 号口正中')

  // 缺角度表(旧 manifest)退回均布, 保持老行为不回归
  const uniform = makePumpRig({ withAngles: false })
  const uValve = nodeOf(uniform.nodes, 'ACTUATOR_PUMP_VALVE_DEV1')
  const uBase = uValve.quaternion.clone()
  uniform.rig.setPumpValvePort('DEV1', 4)
  const expectedU = expectedQuat(uBase, axis, ((4 - 1) / 6) * Math.PI * 2)
  assert.ok(Math.abs(uValve.quaternion.dot(expectedU)) > 1 - 1e-9, '缺表时没有退回均布')
})

test('超量程夹到 syringeMl; 未绑定 id / rigged:false / NaN 一律静默不动', () => {
  const { rig } = makePumpRig()
  rig.setPumpMl('DEV1', 999)
  assert.equal(rig.pumpMl('DEV1'), 25, '超过针筒量程按量程夹')
  assert.equal(rig.setPumpMl('COL', 10), false, 'rigged:false 的收集泵不绑定、不动')
  assert.equal(rig.setPumpMl('SMP', 10), false)
  assert.equal(rig.setPumpMl('DEV1', Number.NaN), false)
  assert.equal(rig.setPumpValvePort('DEV1', Number.NaN), false)
  assert.equal(rig.pumpMl('COL'), 0)
})

test('home() 把泵清到 0mL/1号口 —— 0mL 是机器静止态(每个 *.init 都是 Z 归零)', () => {
  const { rig, nodes } = makePumpRig()
  const plunger = nodeOf(nodes, 'ACTUATOR_PUMP_PLUNGER_DEV1')
  const valve = nodeOf(nodes, 'ACTUATOR_PUMP_VALVE_DEV1')
  const base = plunger.position.clone()
  const valveBase = valve.quaternion.clone()

  rig.setPumpMl('DEV1', 20)
  rig.setPumpValvePort('DEV1', 6)
  rig.home()
  assert.ok(plunger.position.distanceTo(base) < 1e-12, 'home 后柱塞未回零位')
  assert.equal(rig.pumpMl('DEV1'), 0)
  assert.equal(nodeOf(nodes, 'LIQUID_PUMP_DEV1').visible, false, 'home 后液柱未隐藏')
  const port1 = expectedQuat(valveBase, new THREE.Vector3(0, 0, -1), (PORT_ANGLES[0] / 360) * Math.PI * 2)
  assert.ok(Math.abs(valve.quaternion.dot(port1)) > 1 - 1e-9, 'home 后阀没有回 1 号口')
})

test('柱塞/阀/丝杆进刚体门禁, 液柱与展缸液面同理故意不进', () => {
  const { rig, nodes } = makePumpRig()
  rig.setPumpMl('DEV1', 12)
  assert.deepEqual(rig.rigidScaleViolations(), [], '液柱被误加进刚体门禁, 有液当天就会变红')
  // 反向验证: 柱塞若真被缩放, 门禁必须抓到
  nodeOf(nodes, 'ACTUATOR_PUMP_PLUNGER_DEV1').scale.setScalar(1.01)
  assert.deepEqual(rig.rigidScaleViolations(), ['ACTUATOR_PUMP_PLUNGER_DEV1'])
})

test('驱动层不克隆材质(离线链一个颜色都不写, 克隆一次就泄一份)', () => {
  const { rig, nodes, shared } = makePumpRig()
  rig.setPumpMl('DEV1', 10)
  assert.equal(nodeOf(nodes, 'LIQUID_PUMP_DEV1').material, shared)
  assert.equal(nodeOf(nodes, 'ACTUATOR_PUMP_PLUNGER_DEV1').material, shared)
})

test('dispose() 把泵还原到加载态: 液柱成对还原, 柱塞/阀/丝杆回捕获基位', () => {
  const { rig, nodes } = makePumpRig()
  const plunger = nodeOf(nodes, 'ACTUATOR_PUMP_PLUNGER_DEV1')
  const liquid = nodeOf(nodes, 'LIQUID_PUMP_DEV1')
  const valve = nodeOf(nodes, 'ACTUATOR_PUMP_VALVE_DEV1')
  const lead = nodeOf(nodes, 'ACTUATOR_PUMP_LEAD_DEV1')
  const snapshot = {
    plunger: plunger.position.clone(),
    liquidScale: liquid.scale.clone(),
    liquidPos: liquid.position.clone(),
    valve: valve.quaternion.clone(),
    lead: lead.quaternion.clone(),
  }
  rig.setPumpMl('DEV1', 18)
  rig.setPumpValvePort('DEV1', 5)
  rig.dispose()
  assert.ok(plunger.position.distanceTo(snapshot.plunger) < 1e-12, '柱塞没回建模位')
  assert.deepEqual(liquid.scale.toArray(), snapshot.liquidScale.toArray(), '液柱 scale 没还原')
  assert.deepEqual(liquid.position.toArray(), snapshot.liquidPos.toArray(), '液柱 position 没还原(下次 bind 会采错基准)')
  assert.equal(liquid.visible, true, 'dispose 后不该留下驱动层登记的隐藏')
  assert.ok(Math.abs(valve.quaternion.dot(snapshot.valve)) > 1 - 1e-9, '阀没回建模朝向')
  assert.ok(Math.abs(lead.quaternion.dot(snapshot.lead)) > 1 - 1e-9, '丝杆没回建模朝向')
  assert.equal(rig.pumps.size, 0)
})

test('骑在运动轴上的泵(上样泵形态): basePosition 是局部系, 父节点动它跟着走', () => {
  // SMP 挂在 6X 轴的 CARRIAGE 下 —— 记世界坐标会在轴一动就错, 这条钉"局部基准"约定
  const root = new THREE.Group()
  const carriage = new THREE.Group()
  carriage.name = 'CARRIAGE.006'
  root.add(carriage)
  const plunger = new THREE.Mesh(new THREE.CylinderGeometry(0.011, 0.011, 0.06), new THREE.MeshStandardMaterial())
  plunger.name = 'ACTUATOR_PUMP_PLUNGER_SMP'
  plunger.position.set(0.1, 0.2, 0.3)
  carriage.add(plunger)
  const liquid = new THREE.Mesh(new THREE.CylinderGeometry(0.011, 0.011, 0.06), plunger.material)
  liquid.name = 'LIQUID_PUMP_SMP'
  carriage.add(liquid)
  const nodes = new Map([
    ['ST_SAMPLING/AXIS_AXIS_6X/CARRIAGE.006/ACTUATOR_PUMP_PLUNGER_SMP', plunger],
    ['ST_SAMPLING/AXIS_AXIS_6X/CARRIAGE.006/LIQUID_PUMP_SMP', liquid],
  ])
  const rig = new MachineStateDriver({
    manifest: {
      pumpSyringe: {
        syringeMl: 25,
        strokeMm: 60,
        stepsPerStroke: 6000,
        pumps: [{
          id: 'SMP',
          rigged: true,
          plungerNode: 'ST_SAMPLING/AXIS_AXIS_6X/CARRIAGE.006/ACTUATOR_PUMP_PLUNGER_SMP',
          liquidNode: 'ST_SAMPLING/AXIS_AXIS_6X/CARRIAGE.006/LIQUID_PUMP_SMP',
          travelAxis: [0, 1, 0],
          travelM: 0.06,
        }],
      },
    },
    resolve: (p) => nodes.get(p),
  })

  rig.setPumpMl('SMP', 25)
  carriage.position.set(1, 0, 0) // 轴走位
  plunger.updateMatrixWorld(true)
  const world = plunger.getWorldPosition(new THREE.Vector3())
  assert.ok(Math.abs(world.x - 1.1) < 1e-12, '柱塞没有跟着滑车走 —— base 被记成世界系了')
  assert.ok(Math.abs(world.y - 0.26) < 1e-12, '柱塞行程没有叠加在局部基准上')
})
