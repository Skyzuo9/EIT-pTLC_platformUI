/**
 * 功能: manifest 查询辅助与实际产出文件的一致性测试.
 *
 * 后半部分直接校验 three_d/models/device-manifest.json 这份真实产物 —— 它是三维模型
 * 与上位机数据之间的契约, 结构一旦跑偏(例如工位丢了 nodeId、展缸下标错位),
 * 界面上的表现是"某个工位永远离线"或"液面对错缸", 排查代价很高, 不如在这里挡住.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

import {
  axesOfStation,
  groupRowsByStation,
  manifestSummary,
  stationByNodeId,
  stationById,
  stationForAction,
} from '../../src/three-d/twin/manifest.js'
import { isCameraOutsideFootprint } from '../../src/three-d/twin/stationViewRules.js'

const WORKSPACE_ROOT = process.env.PTLC_THREE_D_WORKSPACE || 'E:/eit_lab/pTLC_platformUI/eit_ptlc/three_d'
const MANIFEST_PATH = path.join(WORKSPACE_ROOT, 'models', 'device-manifest.json')
const OFFICIAL_MANIFEST_PATH = path.join(
  WORKSPACE_ROOT,
  'models',
  'device-manifest.official-cr5.json',
)
const STRUCTURE_PATH = path.join(WORKSPACE_ROOT, 'work', 'structure.json')

/** 构造一份最小 manifest 用于纯函数测试 */
const FIXTURE = {
  stations: [
    { id: 'DEVELOP', nodeId: 'plc.develop', label: '展开工位', actionPrefixes: ['develop.'] },
    { id: 'RAIL', nodeId: 'plc.rail', label: '地轨', actionPrefixes: ['rail.'] },
    { id: 'FRAME', nodeId: null, label: '机架', actionPrefixes: [] },
  ],
  axes: [
    { id: 'axis_11y', station: 'RAIL', rigged: true },
    { id: 'axis_4x', station: 'SAMPLING', rigged: false },
  ],
  tanks: [{ index: 0, id: 'tank1' }],
}

test('按工位 id 查找', () => {
  assert.equal(stationById(FIXTURE, 'DEVELOP').label, '展开工位')
  assert.equal(stationById(FIXTURE, '不存在'), undefined)
})

test('按上位机节点 id 反查工位', () => {
  assert.equal(stationByNodeId(FIXTURE, 'plc.rail').id, 'RAIL')
  assert.equal(stationByNodeId(FIXTURE, 'plc.unknown'), undefined)
})

test('按动作名反查工位', () => {
  assert.equal(stationForAction(FIXTURE, 'develop.drain').id, 'DEVELOP')
  assert.equal(stationForAction(FIXTURE, 'rail.move').id, 'RAIL')
  assert.equal(stationForAction(FIXTURE, 'robot.home'), undefined)
})

test('取工位下的运动轴', () => {
  assert.equal(axesOfStation(FIXTURE, 'RAIL').length, 1)
  assert.equal(axesOfStation(FIXTURE, 'DEVELOP').length, 0)
})

test('实时条目按工位分组(手动控制面板)', () => {
  const rows = [
    { id: 'axis_11y', station: 'rail' },
    { id: 'axis_4x', station: 'sampling' },
    { id: 'develop_valve', station: 'DEVELOP' },
    { id: 'no_station' },
  ]
  const groups = groupRowsByStation(FIXTURE, rows)
  // 组序跟随 stations 数组(DEVELOP → RAIL), 大小写不敏感;
  // FIXTURE 没有 SAMPLING 工位与缺 station 的条目落"其他"垫底; 空组(FRAME)剔除
  assert.deepEqual(groups.map((group) => group.id), ['DEVELOP', 'RAIL', 'OTHER'])
  assert.deepEqual(groups.map((group) => group.label), ['展开工位', '地轨', '其他'])
  assert.deepEqual(groups[0].items.map((row) => row.id), ['develop_valve'])
  assert.deepEqual(groups[1].items.map((row) => row.id), ['axis_11y'])
  assert.deepEqual(groups[2].items.map((row) => row.id), ['axis_4x', 'no_station'])
})

test('分组的边界情况', () => {
  assert.deepEqual(groupRowsByStation(FIXTURE, []), [])
  assert.deepEqual(groupRowsByStation(FIXTURE, null), [])
  // 无 stations 的 manifest → 全部落"其他", 面板仍可用(退化为平铺)
  const fallback = groupRowsByStation(null, [{ id: 'axis_1z', station: 'feedlift' }])
  assert.equal(fallback.length, 1)
  assert.equal(fallback[0].id, 'OTHER')
  assert.equal(fallback[0].items.length, 1)
})

test('装配完成度摘要', () => {
  const summary = manifestSummary(FIXTURE)
  assert.equal(summary.stations, 3)
  assert.equal(summary.axes, 2)
  assert.equal(summary.axesRigged, 1)
})

// -- 真实产物校验 -----------------------------------------------------------

test('实际产出的 device-manifest 结构自洽', (t) => {
  if (!fs.existsSync(MANIFEST_PATH)) {
    t.skip('尚未生成 device-manifest.json, 跳过')
    return
  }
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'))

  assert.equal(manifest.version, 2, '统一驱动 manifest 必须为 v2')
  assert.equal(manifest.generatedFrom?.rigMapSchema, 'ptlc.rigmap/v2')
  assert.ok(Array.isArray(manifest.stations) && manifest.stations.length > 0, '应有工位')
  assert.ok(Array.isArray(manifest.axes), '应有轴列表')
  assert.ok(Array.isArray(manifest.tanks), '应有展缸列表')
  for (const field of ['nodes', 'actuators', 'linkages', 'attachments', 'states', 'sockets']) {
    assert.ok(Array.isArray(manifest[field]), `统一驱动字段 ${field} 必须为数组`)
  }

  // 展缸下标必须是 0..7 且连续 —— 它直接用作上位机 Tank_State 数组的下标
  const indices = manifest.tanks.map((tank) => tank.index).sort((a, b) => a - b)
  assert.deepEqual(indices, [0, 1, 2, 3, 4, 5, 6, 7], '展缸下标应为 0~7')
  for (const tank of manifest.tanks) {
    // 液面盒/状态灯是可停用的示意体(rig_map enabled: false), 契约允许为 null,
    // 前端绑定层对 null 直接跳过; 但字段本身必须存在, 缺字段说明生成器坏了.
    assert.ok('liquidNode' in tank, `展缸 ${tank.id} 应有 liquidNode 字段(可为 null)`)
    assert.equal(tank.stateFrom.node, 'plc.develop')
    assert.equal(tank.stateFrom.key, 'Tank_State')
  }

  // 每个带遥测节点的工位都应有相机机位, 否则界面上会缺表现
  for (const station of manifest.stations) {
    if (!station.nodeId || !station.hasGeometry) continue
    assert.ok('statusLight' in station, `工位 ${station.id} 应有 statusLight 字段(可为 null)`)
    assert.ok(station.camera?.pos?.length === 3, `工位 ${station.id} 应有相机机位`)
    assert.ok(station.camera?.target?.length === 3, `工位 ${station.id} 应有相机目标`)
  }

  // 注射泵契约自洽: 动作表引用的每个泵 id 都必须能在 pumps[] 里找到, 否则改 id 时
  // 动作会静默不接管(柱塞不动、面板不涨, 却一条报错也没有)
  if (manifest.pumpSyringe) {
    const pumpIds = new Set(manifest.pumpSyringe.pumps.map((pump) => pump.id))
    assert.ok(pumpIds.size > 0, '注射泵列表不应为空')
    for (const [action, spec] of Object.entries(manifest.pumpSyringe.actions || {})) {
      if (spec.pump?.from === 'fixed') {
        assert.ok(pumpIds.has(spec.pump.id), `动作 ${action} 指向不存在的泵 ${spec.pump.id}`)
      }
      assert.ok(Array.isArray(spec.phases) && spec.phases.length > 0,
        `动作 ${action} 必须是相位脚本 —— 单目标模型下往复运动会整个消失`)
    }
    // tankGroup 路由的动作要有泵认领这些缸号, 否则展开动作全程不接管
    const covered = new Set(manifest.pumpSyringe.pumps.flatMap((pump) => pump.tankGroup || []))
    for (const tank of manifest.tanks) {
      assert.ok(covered.has(tank.index + 1), `缸 ${tank.index + 1} 没有任何泵认领`)
    }
    for (const pump of manifest.pumpSyringe.pumps) {
      assert.ok('plungerNode' in pump, `泵 ${pump.id} 应有 plungerNode 字段(可为 null)`)
      assert.ok('liquidNode' in pump, `泵 ${pump.id} 应有 liquidNode 字段(可为 null)`)
      if (pump.rigged) {
        assert.ok(pump.plungerNode && pump.liquidNode, `已装配的泵 ${pump.id} 两个节点都要有`)
        assert.ok(pump.travelM > 0, `已装配的泵 ${pump.id} 行程应为正`)
      }
    }
  }

  // 已装配的轴必须有节点路径与遥测键, 否则绑定层会静默失效
  for (const axis of manifest.axes) {
    assert.ok(axis.telemetry?.node && axis.telemetry?.key, `轴 ${axis.id} 应声明遥测来源`)
    if (axis.rigged) {
      assert.ok(axis.glbNode, `已装配的轴 ${axis.id} 应有 glbNode`)
      assert.ok(axis.mmToUnit > 0, `轴 ${axis.id} 的 mmToUnit 应为正`)
    }
  }

  assert.equal(manifest.robot?.joints?.length, 6, 'CR5 必须有完整六轴声明')
  assert.ok(manifest.robot?.toolMount, 'CR5 必须声明 TOOL_MOUNT')
  assert.deepEqual(
    manifest.tools.map((tool) => tool.controllerTool).sort((a, b) => a - b),
    [1, 2, 3],
    '三把 CAD 工具必须与上位机 MountedTool 的 SLOT1 吸盘/SLOT2 大爪/SLOT3 小爪一一对应',
  )
  // 缺 mountQuaternion 时 syncMountedTool 会退回单位四元数, 实时挂上去绕安装轴错转约 90°。
  // 大夹爪与小夹爪先后栽在这上面, 所以三把刀一起锁死。
  for (const tool of manifest.tools) {
    assert.equal(tool.mountPosition?.length, 3, `工具 ${tool.id} 缺 mountPosition`)
    assert.equal(tool.mountQuaternion?.length, 4, `工具 ${tool.id} 缺 mountQuaternion`)
  }

  // 健康度配色必须覆盖后端 derive_health 的全部取值
  for (const health of ['ok', 'busy', 'error', 'offline']) {
    assert.ok(manifest.healthStyles?.[health], `缺少 ${health} 的状态灯配色`)
  }

  // 整机三色塔灯契约: 指向唯一灯罩节点(绝不能是外壳), 配色覆盖全部灯态.
  // 缺契约的表现是 live 页塔灯永远停在烘焙静态绿, 与 PLC 实际输出脱节.
  const signalLight = manifest.signalLight
  assert.ok(signalLight?.glbNode, 'manifest 应声明 signalLight(rig_map.signal_light 已启用)')
  assert.match(signalLight.glbNode, /RYG/, '塔灯节点应是 ZHD24 RYG 灯罩')
  assert.ok(!signalLight.glbNode.endsWith('_HOUSING'), '不得把塔灯外壳声明为发光灯罩')
  assert.equal(signalLight.event, 'signal_light')
  assert.ok(signalLight.staleMs > 0, 'staleMs 应为正(断流转灰的时钟)')
  for (const key of ['red', 'yellow', 'green', 'off', 'stale']) {
    assert.ok(signalLight.styles?.[key], `signalLight 缺少 ${key} 配色`)
  }
})

test('CR5 末端执行器绑定契约(夹爪开合 + 吸盘翻转)', (t) => {
  if (!fs.existsSync(MANIFEST_PATH)) {
    t.skip('尚未生成 device-manifest.json, 跳过')
    return
  }
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'))

  // id 是全链契约(上位机 robot_controller._MECH_BY_TOOL / rig_map / 前端按 id 直配),
  // 错一个字的症状是机构"永远不动"且零报错 —— 三处各硬编码一份互为绊线.
  const EXPECTED = ['rob_flip_suction', 'rob_grip_plate96', 'rob_grip_vial']
  const runtimeIds = [
    ...manifest.actuators.map((item) => item.id),
    ...manifest.linkages.map((item) => item.id),
  ]
  for (const id of EXPECTED) {
    assert.equal(runtimeIds.filter((item) => item === id).length, 1, `${id} 必须有且只有一份几何绑定`)
  }

  const robotActuators = manifest.actuators.filter((item) => EXPECTED.includes(item.id))
  const robotLinkages = manifest.linkages.filter((item) => EXPECTED.includes(item.id))

  const byId = new Map(manifest.realtime.mechanisms.map((item) => [item.id, item]))
  for (const id of EXPECTED) {
    assert.equal(byId.get(id)?.rigged, true, `${id} 必须进实时目录且 rigged(否则事件被 knownIds 过滤)`)
    assert.equal(byId.get(id)?.station, 'robot')
  }

  // 节点路径必须是"已解析的完整路径"(strict 解析的证据), 叶名必须是短 ASCII 的
  // ACTUATOR_* 空对象 —— 一次绕开 47 字符截断与 three.js 名字消毒两个坑.
  const nodePaths = [
    ...robotActuators.map((item) => item.node),
    ...robotLinkages.flatMap((item) => item.members.map((member) => member.node)),
  ]
  assert.equal(nodePaths.length, 5, '1 个翻转节点 + 两副夹爪各 2 个组节点')
  for (const nodePath of nodePaths) {
    assert.ok(nodePath.includes('/'), `节点必须是完整路径而非叶名回退: ${nodePath}`)
    assert.match(nodePath.split('/').pop(), /^ACTUATOR_[A-Z0-9_]+$/, `叶名必须是 ACTUATOR_* 空对象: ${nodePath}`)
  }

  // 行程与方向: 信号 0=张开(GLB 基准位, 位移 0) / 1=闭合, inputRange 保持升序 [0,1].
  // 每指行程采用当前气爪标称行程: plate96 5.2 mm, vial 12.5 mm. 翻转 180°.
  for (const linkage of robotLinkages) {
    assert.equal(linkage.members.length, 2, `${linkage.id} 应为双指对开`)
    const [a, b] = linkage.members
    assert.equal(a.sign + b.sign, 0, `${linkage.id} 双指 sign 必须互反`)
    const stroke = linkage.id === 'rob_grip_plate96' ? 5.2 : 12.5
    for (const member of linkage.members) {
      assert.deepEqual(member.outputRange, [0, stroke], `${linkage.id} 应为正向行程 [0, ${stroke}](1=闭合)`)
      assert.deepEqual(member.inputRange, [0, 1], `${linkage.id} inputRange 必须保持升序 [0,1](clamp 约束)`)
      assert.equal(member.unitScale, 0.001, `${linkage.id} 行程单位应为毫米(unitScale=0.001)`)
      assert.equal(member.motion, 'translate')
    }
    assert.ok(linkage.transitionS > 0, `${linkage.id} 应声明缓动时长`)
  }
  const flip = robotActuators.find((item) => item.id === 'rob_flip_suction')
  assert.equal(flip.motion, 'rotate')
  assert.deepEqual(flip.outputRange, [0, 180], '吸盘翻转应为 180°(用户拍板)')
  assert.ok(flip.transitionS > 0)

  // build/catalog 是管线内部块, 不得泄漏进浏览器产物
  for (const item of [...manifest.actuators, ...manifest.linkages]) {
    assert.equal('build' in item, false, `${item.id} 的 build 块应被剥除`)
    assert.equal('catalog' in item, false, `${item.id} 的 catalog 块应被剥除`)
  }
})

test('同款同图纸的两只定位缸必须成对 rig(上样 / 刮板拍照)', (t) => {
  if (!fs.existsSync(MANIFEST_PATH)) {
    t.skip('尚未生成 device-manifest.json, 跳过')
    return
  }
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'))

  // 2026-08-05 修的病: smp_locator 的 PLC 点/动作映射/片段步/manifest 目录条目全都在,
  // 唯独 rig_map 少一条 actuators 条目 —— 于是片段照发 setActuator, applyMotion 查不到
  // 条目返回 false, **缸一动不动且全程零报错**(manifest 标 rigged:false, 连告警都不触发).
  // 这两只是同款同图纸(TCM6x5S + PTLC-05-023 推板), 只 rig 一半没有任何合法理由,
  // 故在此成对锁住 —— 靠人眼去 manifest 里翻 rigged 字段是发现不了的.
  const PAIR = [
    { id: 'smp_locator', station: 'sampling' },
    { id: 'ps_locator', station: 'photoscrape' },
  ]
  const byId = new Map(manifest.realtime.mechanisms.map((item) => [item.id, item]))

  for (const { id, station } of PAIR) {
    const matches = manifest.actuators.filter((item) => item.id === id)
    assert.equal(matches.length, 1, `${id} 必须有且只有一份几何绑定`)
    const spec = matches[0]

    assert.equal(byId.get(id)?.rigged, true, `${id} 必须 rigged(否则片段照播而缸不动, 零报错)`)
    assert.equal(byId.get(id)?.station, station)

    // 节点必须是 strict 解析出的完整路径, 叶名是 ACTUATOR_* 空对象(叶名回退 = 没解析到真节点)
    assert.ok(spec.node.includes('/'), `${id} 节点必须是完整路径而非叶名回退: ${spec.node}`)
    assert.match(spec.node.split('/').pop(), /^ACTUATOR_[A-Z0-9_]+$/, `${id} 叶名必须是 ACTUATOR_*`)

    // 运动学: 两只缸都沿 glTF X 推, 夹紧 = −X, 毫米单位
    assert.equal(spec.motion, 'translate', `${id} 是直线缸`)
    assert.deepEqual(spec.axis, [1, 0, 0], `${id} 应沿 glTF X`)
    assert.equal(spec.sign, -1, `${id} 夹紧 = 推板往 −X 顶玻璃`)
    assert.equal(spec.unitScale, 0.001, `${id} 行程单位应为毫米`)
    assert.deepEqual(spec.inputRange, [0, 1], `${id} inputRange 必须保持升序 [0,1]`)
    assert.ok(spec.transitionS > 0, `${id} 应声明缓动时长`)

    // 基准态 = 松开 ⇒ outputRange 必须**递增**且起点为 0(值0=零位移=CAD 位姿).
    // 与 col_clamp 那种"CAD 基准即紧闭"的递减 outputRange 相反, 写反的症状是缸动反.
    assert.equal(spec.outputRange[0], 0, `${id} 基准态=松开, outputRange 起点必须是 0`)
    assert.ok(spec.outputRange[1] > 0, `${id} outputRange 必须递增(夹紧为正行程)`)
  }

  // 行程各按各自实测净空, 不互相照抄: 上样 3.5(台面 +X 端到玻璃 6.0mm 落位),
  // 刮板拍照 2.5(同处 5.0mm). 差 1mm 来自玻璃在沉台里的落位而非气缸差别.
  const strokeOf = (id) => manifest.actuators.find((item) => item.id === id).outputRange[1]
  assert.equal(strokeOf('smp_locator'), 3.5, '上样定位缸行程 = 玻璃 +X 边到推板的实测净空')
  assert.equal(strokeOf('ps_locator'), 2.5, '刮板拍照定位缸行程 = 同口径实测净空')
})

test('相机机位落在整机之外', (t) => {
  if (!fs.existsSync(MANIFEST_PATH)) {
    t.skip('尚未生成 device-manifest.json, 跳过')
    return
  }
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'))
  const bounds = manifest.machine?.bounds
  if (!bounds) {
    t.skip('manifest 未记录整机包围盒, 跳过')
    return
  }

  for (const station of manifest.stations) {
    const pos = station.camera?.pos
    if (!pos) continue
    // 判据与「显示 → 模块视角设定」保存前的校验**同一份实现**(twin/stationViewRules.js) ——
    // 那边存进来的机位要过的就是这一关, 两处不能各写一遍
    assert.ok(
      isCameraOutsideFootprint(pos, bounds),
      `工位 ${station.id} 的相机机位 (${pos}) 落在整机轮廓内部`,
    )
  }
})

test('official CR5 产物包含完整实时目录、真源哈希与装配状态', (t) => {
  if (!fs.existsSync(OFFICIAL_MANIFEST_PATH)) {
    t.skip('尚未生成 official CR5 manifest, 跳过')
    return
  }
  const source = fs.readFileSync(OFFICIAL_MANIFEST_PATH, 'utf-8')
  const manifest = JSON.parse(source)
  const realtime = manifest.realtime

  assert.equal(realtime?.protocol, 'ptlc.realtime/v1')
  assert.equal(realtime.renderDelayMs, 100)
  assert.equal(realtime.staleMs, 500)
  assert.deepEqual(
    realtime.events,
    // scrape_state: 刮取前沿实时事件(gen_twin_manifest realtime.events 声明), 2026-08-07
    // 全量重建后进入产物, 镜像随生成器契约走
    ['robot_pose', 'axis_pose', 'mechanism_state', 'material_state', 'signal_light', 'scrape_state'],
  )
  assert.equal(realtime.materialHeartbeatMs, 5000)
  assert.equal(realtime.materialStaleMs, 12000)
  assert.equal(realtime.axes?.length, 11, '实时目录必须覆盖 11 根 PLC 轴')
  // 51 个 PLC 机构 + 3 个有几何的机器人末端执行器(rob_grip_plate96/rob_grip_vial/
  // rob_flip_suction) + 1 个纯状态机构(rob_suction 吸盘真空, 无几何), 均由 rig_map
  // 的 catalog 块派生, 不进上位机 manual_points.yaml
  assert.equal(realtime.mechanisms?.length, 55, '实时目录必须覆盖 51 PLC + 3 末端执行器 + 1 吸盘真空')
  assert.equal(new Set(realtime.axes.map((item) => item.id)).size, 11, '轴 id 不得重复')
  assert.equal(new Set(realtime.mechanisms.map((item) => item.id)).size, 55, '机构 id 不得重复')
  // 吸盘真空是 data-only 的纯状态机构: 它没有(也不需要)几何, 必须 rigged:false ——
  // 若被误放进 rig_map 的 actuators 段就会变成 rigged:true 的幽灵条目, 表现是
  // MachineStateDriver 把它计入 missing、TwinBindings 每帧告警而画面永远不动。
  const suction = realtime.mechanisms.find((item) => item.id === 'rob_suction')
  assert.ok(suction, 'rob_suction 必须进实时目录(否则事件被 knownIds 静默过滤)')
  assert.equal(suction.rigged, false, 'rob_suction 无几何, 必须是 data-only')
  assert.equal(suction.kind, 'vacuum')
  assert.equal(suction.station, 'robot')
  assert.equal(suction.controllerTool, 1, '按挂载工具反查时要能定位到 1 号刀吸盘')
  assert.equal(suction.feedbackAvailable, false, '吸盘没有真空 DI, 不得声称有反馈')
  assert.equal(suction.fallbackSource, 'commanded')
  assert.equal(
    realtime.axes.find((item) => item.id === 'axis_11y')?.rigged,
    true,
    '已装配的地轨轴必须在实时目录中保持 rigged',
  )
  const railAxis = manifest.axes.find((item) => item.id === 'axis_11y')
  assert.equal(railAxis?.zeroOffsetMm, 500, '4 号工具位必须保持虚拟地轨零点')
  assert.equal(railAxis?.sign, -1, 'CAD +X 与实机地轨正方向相反，禁止再次镜像 1/6 工位')
  const toSceneX = (mm) => (mm - railAxis.zeroOffsetMm) * railAxis.sign * railAxis.mmToUnit
  assert.ok(toSceneX(168) > 0, '1 号位必须位于工具位的场景 +X 侧')
  assert.ok(toSceneX(600) < 0, '6 号位必须位于工具位的场景 -X 侧')
  const largeGripper = manifest.tools.find((item) => item.controllerTool === 2)
  assert.equal(largeGripper?.id, 'TOOL_PLATE96')
  assert.equal(largeGripper.mountPosition?.length, 3, '大夹爪必须声明锁紧后的局部位置')
  assert.equal(largeGripper.mountQuaternion?.length, 4, '大夹爪必须声明锁紧后的局部朝向')
  assert.ok(
    Math.abs(largeGripper.mountQuaternion[0]) > 0.7,
    '大夹爪挂载朝向不能退回单位四元数',
  )
  assert.match(largeGripper.mountCalibration || '', /robot\.tool_pickup/)
  assert.match(manifest.generatedFrom?.manualPointsHash || '', /^[a-f0-9]{64}$/)
  assert.equal(manifest.inventory?.rack?.length, 12, '货架必须保留 12 张可独立显隐的 CAD 托盘')
  assert.equal(manifest.inventory?.staging?.length, 2, '中转 A/B 必须各有独立物料刚体')
  assert.equal(manifest.inventory?.magazines?.length, 2, '上/下料仓必须各有正式玻璃板模板')
  assert.deepEqual(manifest.inventory?.visibleStates, ['FRESH'])
  assert.equal(manifest.inventory?.visibleWhenSampleId, true)
  assert.ok(
    [...manifest.inventory.rack, ...manifest.inventory.staging]
      .every((tray) => tray.items?.length === 6 && new Set(tray.items).size === 6),
    '12 张货架托盘与两个中转托盘都必须有 6 个可独立显隐的耗材刚体',
  )
  assert.ok(manifest.inventory.magazines.every((item) => item.spacingM > 0))
  for (const item of manifest.inventory.magazines) {
    // 托边交接值: 轴低于它时前端把板托在托边高度(板停、滑车继续走), 缺了板堆会随
    // 滑车穿过料仓口固定托边。数据由 blender_plate_clearance.ledge_probe 实测。
    const axis = (manifest.axes || []).find((spec) => spec.id === item.axisId)
    assert.ok(axis?.rigged, `料仓 ${item.id} 的 axisId(${item.axisId}) 必须指向已装配的轴`)
    assert.ok(Number.isFinite(item.ledgeAxisMm), `料仓 ${item.id} 缺托边交接值 ledgeAxisMm`)
    assert.ok(
      item.ledgeAxisMm > Number(axis.geometryMinMm ?? axis.rangeMm?.[0] ?? -Infinity),
      `料仓 ${item.id} 托边交接值应高于轴的几何下界(否则永远托不住)`,
    )
    assert.ok(Math.abs(item.ledgeAxisMm) < 20, `料仓 ${item.id} 托边交接值量级异常: ${item.ledgeAxisMm}`)
  }
  assert.equal(source.includes('E:\\eit_lab'), false, '浏览器产物不得携带开发机绝对路径')
  assert.ok(manifest.signalLight?.glbNode, 'official 份同样必须声明 signalLight(漏一份的症状是两页灯行为不一致)')
})

test('中转站固定机构与可搬运托盘分层', (t) => {
  if (!fs.existsSync(STRUCTURE_PATH)) {
    t.skip('尚未生成 work/structure.json, 跳过')
    return
  }
  const nodes = JSON.parse(fs.readFileSync(STRUCTURE_PATH, 'utf-8')).nodes || []
  const stagingA = nodes.find((node) => node.name === 'INV_STAGING_A')
  assert.ok(stagingA?.path, '收集瓶中转托盘必须有独立 INV_STAGING_A 节点')
  assert.match(
    stagingA.path,
    /\/收集瓶支架总装-1\/INV_STAGING_A$/,
    '固定中转装配必须保留，禁止把整棵装配直接改名为可显隐托盘',
  )

  // PTLC-07 固定件会在产出阶段按材质并入 ST_COLLECT/STATIC_*，因此这里锁定
  // INV_STAGING_A 的直属子节点白名单：只能有孔板托盘、四根托盘支柱和六个耗材。
  // 定位气缸、安装板或传感器一旦被误绑进来，这条门禁会立即失败。
  const prefix = `${stagingA.path}/`
  const directChildren = nodes.filter((node) => (
    node.path.startsWith(prefix)
    && !node.path.slice(prefix.length).includes('/')
  ))
  assert.equal(directChildren.length, 12, '中转 A 可搬运载荷应为 6 个托盘件和 6 个耗材')
  assert.ok(directChildren.every((node) => (
    node.name.startsWith('INV_STAGING_A_ITEM_')
    || node.name.startsWith('PTLC-01-008')
    || node.name.startsWith('PTLC-01-009')
    || node.name.startsWith('瓶子料架支撑柱-')
  )), 'INV_STAGING_A 中混入了固定中转站机构')
  assert.ok(
    nodes.some((node) => node.path.startsWith('ST_COLLECT/STATIC_')),
    '中转站固定机构不得随托盘一起从 ST_COLLECT 中消失',
  )
})
