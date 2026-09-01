/**
 * 功能: 展缸液面 `liquid` 连续通道 —— 编译、插值、seek 幂等与驱动层写入.
 *
 * 为什么液面做成**连续通道**且值是**毫升**(这几条用例就是钉这两个决定的):
 *   1. 通道值是 t 的纯函数 —— 拖进度条到任意时刻直接算得出, 不依赖"回家重放";
 *   2. 注/排液本来就是连续过程(实时侧画的就是 8~12 秒的指数趋近曲线), 做成离散开关
 *      既不像, 又会在向后 seek 时留下"该空没空"的一整块可见体积;
 *   3. 存毫升而不是 0..1 的液位: 液位要用 cavity 的实测自由截面积/槽深与观感放大系数
 *      换算, 而那三个数每跑一次 03 体素扫描都会变。把它们烘进落盘片段的数字里, 重测一次
 *      全部片段就静默错位, 而 railCalibStatus 只盯轴标定, 没有任何指标会说它假。
 *
 * 最要紧的一条是"驱动层与 TankLiquidModel 逐位一致": 同一条动作在演示页与实况页高低
 * 不一时, 两边都看着挺正常。本仓已经为"同一条公式留两份"付过一次代价
 * (linkageKinematics.js ↔ solve_lid_kinematics), 那是跨语言不得已 —— 这里没有借口。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { compileClip, evaluateChannels } from '../../src/three-d/anim/clipSchema.js'
import { MachineStateDriver } from '../../src/three-d/anim/MachineStateDriver.js'
import { TankLiquidModel, levelFromMl } from '../../src/three-d/twin/bindings/TankLiquidModel.js'
import {
  LIQUID_EMPTY_FACTOR, applyLiquidLevel, captureLiquidBase,
} from '../../src/three-d/twin/bindings/liquidPivot.js'
import { HIDE_OWNER, holdHidden, releaseHidden } from '../../src/three-d/twin/scene/visibilityIntent.js'
import { ViewTools } from '../../src/three-d/twin/scene/ViewTools.js'

/** 2026-08-03 体素实测值(与 device-manifest.tankLiquid.cavity 同源) */
const CAVITY = {
  floorZMm: 114.721,
  rimZMm: 134.995,
  usableDepthMm: 20.274,
  freeAreaMm2: 4939.6,
  capacityMl: 102.48,
  mlPerMm: 4.94,
}

/** 一段"沉降 → 排空"的润洗抽吸片段(与 clip_compiler.emit_tank_liquid 同形)。 */
function drainClip() {
  return {
    schema: 'ptlc.clip/v1',
    name: 'rinse_suction',
    home: { liquid_ml: { tank3: 20 } },
    steps: [
      { label: '3号缸静置沉降 3s', dur: 3, do: { wait: {} } },
      { label: '3号缸排液 20.0 → 0.0 mL', dur: 8, ease: 'out', do: { liquid: { id: 'tank3', to_ml: 0 } } },
    ],
  }
}

/** 造一个带 N 个展缸液面盒的最小 manifest + 场景。 */
function makeRig({ tanks = 2, exaggeration = 2, cavity = CAVITY } = {}) {
  const root = new THREE.Group()
  const nodes = new Map()
  // 共用一份材质: 驱动层不该克隆(它一个颜色都不写), 共用才能验出"有没有偷偷克隆"
  const shared = new THREE.MeshStandardMaterial({ color: '#6fb9d8' })
  const specs = []
  for (let i = 1; i <= tanks; i += 1) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.21, 0.02, 0.04), shared)
    mesh.name = `LIQUID_${i}`
    // 建模位 = 满到槽口, scale 非 1 才能验出"按比例缩放"而不是"直接写绝对值"
    mesh.scale.set(1, 1.5, 1)
    root.add(mesh)
    const path = `ST_DEVELOP/TANK_${i}/LIQUID_${i}`
    nodes.set(path, mesh)
    specs.push({ index: i - 1, id: `tank${i}`, label: `展缸 ${i}`, liquidNode: path })
  }
  const manifest = {
    tanks: specs,
    tankLiquid: { cavity, exaggeration, pipeHoldupMl: 0, tankArg: 'target_tank', actions: {} },
  }
  const rig = new MachineStateDriver({ manifest, resolve: (p) => nodes.get(p) })
  return { rig, nodes, shared, manifest }
}

/** 取某个液面盒当前的相对液位(= scale.y / 建模 scale.y) */
function levelOf(node) {
  return node.scale.y / 1.5
}

/**
 * 功能: 取节点缩放后的世界底面/顶面 y —— 与 liquidPivot.test.js 同一把尺子.
 *
 * 判据必须是"世界底面坐标不动"而不是"position 等于某个数": 后者换个枢轴就红,
 * 前者才是我们真正要的性质. Box3 不看 visible, 所以空缸(已隐藏)也量得到.
 */
function worldBottomY(node) {
  node.updateMatrixWorld(true)
  return new THREE.Box3().setFromObject(node).min.y
}

function worldTopY(node) {
  node.updateMatrixWorld(true)
  return new THREE.Box3().setFromObject(node).max.y
}

/**
 * 功能: 造一个只挂着这几个节点的真 ViewTools —— 验的是"两个写方在同一个节点上并存".
 *
 * 用真的 ViewTools 而不是手搓 holdHidden: 会不会弹回来取决于它**怎么记台账**,
 * 而那正是最容易写错的一处(记 obj.visible 会记下一个会过期的快照).
 */
function makeViewTools(nodes) {
  const machineRoot = new THREE.Group()
  for (const node of nodes) machineRoot.add(node)
  return new ViewTools({ machineRoot })
}

test('liquid 是连续通道: 编译进 channels 而不是 events', () => {
  const clip = compileClip(drainClip())
  assert.equal(clip.events.length, 0, '液面不该产生离散事件')
  assert.ok(clip.channels.has('liquid:tank3'))
})

test('体积按关键帧插值, 且任意 t 都是纯函数(seek 安全)', () => {
  const clip = compileClip(drainClip())
  const at = (t) => evaluateChannels(clip, t).liquids.tank3

  assert.equal(at(0), 20, 't=0 是 home 声明的起始液量')
  assert.equal(at(3), 20, '沉降期间液面不动 —— settle_s 是先静置再抽')
  assert.ok(at(7) < 20 && at(7) > 0, '排液中途在两端之间')
  assert.ok(Math.abs(at(11)) < 1e-9, '排完归零')
  assert.ok(Math.abs(at(99)) < 1e-9, '末帧之后保持终值')

  // 纯函数: 正着走一遍再回头, 同一 t 必须同值
  for (const t of [1, 3.5, 6, 9, 10.5]) {
    assert.equal(at(t), at(t), `t=${t} 求值不稳定`)
  }
})

test('只在 home.liquid_ml 里声明、没有任何步骤的缸也要建通道', () => {
  // 钉 2026-08-05 点样座 7Y 那个 bug 的形状, 而液面这里更严重: 它的"建模位"是满到
  // 槽口, 不建通道就会有一缸溶剂凭空出现在画面里, 且看着完全正常。
  const clip = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'lid_only',
    home: { liquid_ml: { tank5: 30 } },
    steps: [{ label: '开盖', dur: 1, do: { linkage: { id: 'dev_t2_cyl1', to: 0 } } }],
  })
  assert.ok(clip.channels.has('liquid:tank5'), 'home 里声明的缸必须各自成一条通道')
  assert.equal(evaluateChannels(clip, 0).liquids.tank5, 30)
  assert.equal(evaluateChannels(clip, 5).liquids.tank5, 30, '没人驱动就一直保持声明值')
})

test('liquid 缺 id/to_ml 或 to_ml 为负在编译期就报错', () => {
  const build = (body) => () => compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bad',
    steps: [{ label: 'x', dur: 1, do: { liquid: body } }],
  })
  assert.throws(build({ to_ml: 10 }), /缺 id\/to_ml/)
  assert.throws(build({ id: 'tank1' }), /缺 id\/to_ml/)
  assert.throws(build({ id: 'tank1', to_ml: -1 }), /非负毫升数/)
  assert.throws(build({ id: 'tank1', to_ml: 'x' }), /非负毫升数/)
})

test('驱动层 mL→scale.y 与 TankLiquidModel.level 逐位一致(防漂主测)', () => {
  const { rig, nodes } = makeRig()
  const model = new TankLiquidModel({ cavity: CAVITY, exaggeration: 2, pipeHoldupMl: 0 })
  const node = nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')

  for (const ml of [0, 1, 2, 20, 40, 60, 102.48]) {
    rig.setLiquidMl('tank1', ml)
    // 实时模型走同一体积
    model.volumes[0].value = ml
    const expected = levelFromMl(CAVITY, ml, 2)
    assert.equal(model.level(0), expected, `${ml}mL: 实时模型没走共享实现`)
    // 驱动层的 0 缩放有 1e-4 下限(法线退化), 那一档单独验 —— 下限档由"几何版防漂主测"
    // 的 deepEqual 覆盖, 那条连 0mL 也逐位比
    if (expected > LIQUID_EMPTY_FACTOR) {
      assert.ok(Math.abs(levelOf(node) - expected) < 1e-12, `${ml}mL: 离线驱动与实时模型不一致`)
    }
  }
})

test('液面为 0 时整体隐藏, 而不是留一张压扁的顶面(scale 仍留 1e-4 下限)', () => {
  const { rig, nodes } = makeRig()
  const node = nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')

  rig.setLiquidMl('tank1', 0)
  assert.equal(node.scale.y, 1.5 * LIQUID_EMPTY_FACTOR, '空缸留一个下限而不是真的乘 0(法线退化)')
  // 下限只解决法线, 解决不了观感: 液面盒是实心盒, 压扁之后**顶面尺寸不变** ——
  // 展缸那只是 210×40mm 的不透明面, 隔着玻璃缸看就是"排干净了还剩薄薄一层"
  // (2026-08-05 报障的第二个现象). 只能让它不进渲染。
  assert.equal(node.visible, false, '空缸必须真的消失')

  rig.setLiquidMl('tank1', 40)
  assert.equal(node.visible, true, '有液就得画出来')
})

test('别人(隔离/示意体开关)藏着的液面盒, 驱动层不许显示回来', () => {
  const { rig, nodes } = makeRig()
  const node = nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')
  // 复刻动作页的隔离: MotionWorkbench 的 isolate 按钮 -> ViewTools.isolate 按
  // `child.isMesh` 收集, 而 LIQUID_* 是裸网格, 必被藏进去
  holdHidden(node, HIDE_OWNER.VIEW)

  rig.setLiquidMl('tank1', 0)
  rig.setLiquidMl('tank1', 40)
  assert.equal(node.visible, false, '隔离期间播一段注液, 液面盒不该自己弹回画面')

  // 用户取消隔离后才该回来 —— 此时缸里有液, 所以是显示
  releaseHidden(node, HIDE_OWNER.VIEW, true)
  assert.equal(node.visible, true, '取消隔离后, 有液的缸该显示')
})

test('空缸时被隐藏 → 注液 → 取消隐藏: 液面必须回得来(台账快照会过期)', () => {
  const { rig, nodes } = makeRig()
  const node = nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')
  const tools = makeViewTools([node])

  // 缸是空的(液面盒已隐藏), 用户此时点了"隐藏"
  rig.setLiquidMl('tank1', 0)
  assert.equal(node.visible, false)
  tools.hide([node])

  // 播到注液段, 然后取消隐藏
  rig.setLiquidMl('tank1', 40)
  tools.show([node])
  // ViewTools 若把 hide 那一刻的 visible(false, 当时缸是空的)当成还原目标, 这缸就
  // 再也显示不出来了 —— 台账快照会过期, 参与仲裁的对象得让仲裁裁决
  assert.equal(node.visible, true, '注液后取消隐藏, 液面必须回得来')
})

test('ViewTools 的"隐藏示意体"开关关掉后, 播注液不会把液面盒弹回来', () => {
  const { rig, nodes } = makeRig()
  const node = nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')
  const tools = makeViewTools([node])

  tools.setHelpersVisible(false)
  assert.equal(node.visible, false)
  rig.setLiquidMl('tank1', 40)
  assert.equal(node.visible, false, '用户关掉的示意体, 不该在下一次注液时自己弹回来')

  tools.setHelpersVisible(true)
  assert.equal(node.visible, true, '重新打开开关, 有液的缸该显示')
})

test('离线链也是"从底往上涨": 世界底面恒定 —— 与 liquidPivot.test.js 同判据', () => {
  const { rig, nodes } = makeRig()
  const node = nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')
  rig.setLiquidMl('tank1', CAVITY.capacityMl)
  const full = worldBottomY(node)

  let lastTop = Infinity
  for (const ml of [60, 40, 20, 5, 1, 0]) {
    rig.setLiquidMl('tank1', ml)
    assert.ok(Math.abs(worldBottomY(node) - full) < 1e-6,
      `${ml}mL 时底面漂了 ${((worldBottomY(node) - full) * 1000).toFixed(2)}mm —— 又变成往中心收了`)
    const top = worldTopY(node)
    assert.ok(top <= lastTop, `${ml}mL 时顶面没有单调下降`)
    lastTop = top
  }
})

test('同一 mL 下, 离线链与实时链写出的 scale/position 逐位相同(防漂主测·几何版)', () => {
  const { rig, nodes } = makeRig()
  const node = nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')
  // 造一个与实时链 _bindTanks 同形的参照节点, 走 TwinBindings 用的同一条 applyLiquidLevel
  const twin = new THREE.Mesh(new THREE.BoxGeometry(0.21, 0.02, 0.04), new THREE.MeshStandardMaterial())
  twin.scale.set(1, 1.5, 1)
  const base = captureLiquidBase(twin)

  for (const ml of [0, 1, 20, 40, 60, CAVITY.capacityMl]) {
    rig.setLiquidMl('tank1', ml)
    applyLiquidLevel(base, twin, levelFromMl(CAVITY, ml, 2))
    // deepEqual 连空缸那一档也比 —— 上一版的 `expected > 1e-4` 例外正好放过了下限档
    assert.deepEqual(node.scale.toArray(), twin.scale.toArray(), `${ml}mL: scale 漂了`)
    assert.deepEqual(node.position.toArray(), twin.position.toArray(), `${ml}mL: position 漂了`)
  }
})

test('home() 把所有液面清零 —— 否则拖过一次注液段之后缸就再也空不掉了', () => {
  const { rig, nodes } = makeRig()
  rig.setLiquidMl('tank1', 60)
  rig.setLiquidMl('tank2', 30)
  assert.ok(levelOf(nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')) > 0.1)

  rig.home()
  for (const path of nodes.keys()) {
    assert.equal(nodes.get(path).scale.y, 1.5 * LIQUID_EMPTY_FACTOR, `${path} 未在 home() 里归零`)
    assert.equal(nodes.get(path).visible, false, `${path} 归零后没隐藏, 会留一张满尺寸顶面`)
  }
  assert.equal(rig.liquidMl('tank1'), 0)
})

test('驱动层只写 scale, 不碰材质(液面必须保持不透明, 否则会糊在缸外面)', () => {
  const { rig, nodes, shared } = makeRig()
  rig.setLiquidMl('tank1', 40)
  const mesh = nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')
  // 不克隆: 实时侧克隆是为了写相位色, 离线链一个颜色都不写, 克隆一次就泄一份材质
  assert.equal(mesh.material, shared, '离线驱动不该克隆材质')
  // 玻璃缸壁是 BLEND/depthWrite=false, 液体一旦也进透明队列就会按物体中心排序,
  // 被画到缸壁之上 —— 2026-08-03 "液体糊在缸外面"就是这么来的
  assert.equal(mesh.material.transparent, false)
  assert.equal(mesh.material.opacity, 1)
})

test('液面节点不进刚体门禁(它天生就是靠非单位缩放表达体积的)', () => {
  const { rig } = makeRig()
  rig.setLiquidMl('tank1', 50)
  assert.deepEqual(rig.rigidScaleViolations(), [], '液面被误加进刚体门禁, 上线当天就会变红')
})

test('超过槽容的体积夹到 capacityMl(液体不会溢出缸口)', () => {
  const { rig, nodes } = makeRig()
  rig.setLiquidMl('tank1', 999)
  assert.equal(rig.liquidMl('tank1'), CAVITY.capacityMl)
  assert.ok(Math.abs(levelOf(nodes.get('ST_DEVELOP/TANK_1/LIQUID_1')) - 1) < 1e-12, '满槽即封顶')
})

test('未声明的 id / 非有限值静默忽略, 不炸', () => {
  const { rig } = makeRig()
  assert.equal(rig.setLiquidMl('tank9', 10), false)
  assert.equal(rig.setLiquidMl('tank1', Number.NaN), false)
  assert.equal(rig.liquidMl('tank9'), 0)
})

test('管线停用液面盒时(无 cavity / 无 liquidNode)整段静默跳过', () => {
  // rig_map 可以把 tanks.liquid.enabled 关掉; 某个缸的溶液槽没认出来时也只有那一个缺
  const root = new THREE.Group()
  const rig = new MachineStateDriver({
    manifest: { tanks: [{ index: 0, id: 'tank1', liquidNode: null }], tankLiquid: {} },
    resolve: () => undefined,
  })
  assert.equal(rig.liquids.size, 0)
  assert.equal(rig.setLiquidMl('tank1', 10), false)
  // 只看液面相关的缺件: missing 里还有这个最小 manifest 天然没有的 TOOL_MOUNT
  assert.deepEqual(
    rig.missing.filter((path) => String(path).includes('LIQUID')),
    [],
    '声明为 null 的液面不算"解析失败"',
  )
  assert.ok(root)
})

test('dispose() 把液面还原到加载态而不是留在播放态(scale 与 position 必须成对)', () => {
  const { rig, nodes } = makeRig()
  const before = new Map([...nodes].map(([path, node]) => [path, node.position.clone()]))
  rig.setLiquidMl('tank1', 40)
  rig.dispose()
  for (const [path, node] of nodes) {
    assert.equal(node.scale.y, 1.5, 'dispose 后应还原建模尺寸(home() 留下的是空缸)')
    // position 也必须还原: 不还的话, 下一次 _bindLiquids 会把补偿后的位置采成新的
    // basePosition, 于是每改一次参、重建一次 rig 就多偏一截, 越用越歪
    assert.ok(node.position.distanceTo(before.get(path)) < 1e-12, `${path} 的 position 没还原`)
    assert.equal(node.visible, true, 'dispose 后不该留下驱动层登记的隐藏')
  }
})
