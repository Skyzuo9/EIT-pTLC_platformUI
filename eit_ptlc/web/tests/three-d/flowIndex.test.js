/**
 * 功能: 流程动画台账与动作映射表的产物门禁.
 *
 * 与 clipFamilies.test.js 同一性质 —— 校验的是**真实产物**, 不在就跳过, 在就必须自洽。
 *
 * 要拦住的三类静默失效:
 *   1. 台账说某流程 status:ok, 但片段文件不在 / 编译不过 —— 演示栏点下去只会得到
 *      "装载失败", 而徽章还绿着;
 *   2. 台账漏了流程界面里看得见的流程 —— 两份清单对不上, 而没人会去逐条核对;
 *   3. 映射表的字段名与前端 motionMap.js 的读法漂移 —— 表在、读不到, 于是全部流程
 *      静默退化成"每个动作都是占位步", 画面一动不动却不报错。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

import { compileClip, parseClip } from '../../src/three-d/anim/clipSchema.js'
import { isIgnored, lookupAction, tankLidLinkage } from '../../src/three-d/demo/motionMap.js'

const WORKSPACE_ROOT = process.env.PTLC_THREE_D_WORKSPACE || 'E:/eit_lab/pTLC_platformUI/eit_ptlc/three_d'
const CONTROL_ROOT = process.env.PTLC_CONTROL_ROOT || 'E:/eit_lab/pTLC_platformUI/eit_ptlc'
const CLIPS_DIR = path.join(WORKSPACE_ROOT, 'clips')
const FLOW_INDEX_PATH = path.join(CLIPS_DIR, 'flow-index.json')
const MOTION_MAP_PATH = path.join(WORKSPACE_ROOT, 'generated', 'action-motion-map.json')
const CATALOG_PATH = path.join(WORKSPACE_ROOT, 'generated', 'robot-points.json')
const OPERATION_DIR = path.join(CONTROL_ROOT, 'config', 'operation')

/** 读 JSON 产物; 不存在返回 null(产物门禁的通用形态: 不在就跳过) */
function readJson(file) {
  if (!fs.existsSync(file)) return null
  return JSON.parse(fs.readFileSync(file, 'utf-8'))
}

test('flow-index: 每条 status:ok 的片段都真的在盘上且能编译', () => {
  const index = readJson(FLOW_INDEX_PATH)
  if (!index) return // 还没跑过 sync_ptlc_robot.py --flows

  assert.equal(index.schema, 'ptlc.flow-index/v1')
  const catalog = readJson(CATALOG_PATH)

  let checked = 0
  for (const flow of index.flows) {
    if (flow.status !== 'ok') continue
    assert.ok(flow.clips?.length, `${flow.name} 标了 ok 却没有任何片段`)
    for (const clip of flow.clips) {
      const file = path.join(CLIPS_DIR, `${clip.clipName}.yaml`)
      assert.ok(fs.existsSync(file), `${flow.name} 的片段不在盘上: ${clip.clipName}`)
      const doc = parseClip(fs.readFileSync(file, 'utf-8'))
      assert.doesNotThrow(
        () => compileClip(doc, { pointCatalog: catalog }),
        `${clip.clipName} 编译不过 —— 演示栏点下去会得到"装载失败"而徽章还绿着`,
      )
      checked += 1
    }
  }
  assert.ok(checked > 0, 'flow-index 里一条可播片段都没有, 台账形同虚设')
})

test('flow-index: 失败与无机械动作都必须给出可读原因', () => {
  const index = readJson(FLOW_INDEX_PATH)
  if (!index) return

  for (const flow of index.flows) {
    if (flow.status === 'failed' || flow.status === 'no-motion') {
      assert.ok(
        typeof flow.reason === 'string' && flow.reason.length > 0,
        `${flow.name} 是 ${flow.status} 却没写原因 —— 演示栏只能显示一句"不行", 用户无从下手`,
      )
    }
  }
})

test('flow-index: 覆盖流程界面里看得见的全部流程', () => {
  const index = readJson(FLOW_INDEX_PATH)
  if (!index || !fs.existsSync(OPERATION_DIR)) return

  // 流程界面(/library/operation)的规则: 全部 operation 脚本, 只滤掉 ui.hidden
  const onDisk = new Set()
  const visit = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory() && !entry.name.startsWith('.')) visit(full)
      else if (entry.isFile() && entry.name.endsWith('.yaml')) {
        onDisk.add(path.basename(entry.name, '.yaml'))
      }
    }
  }
  visit(OPERATION_DIR)

  const indexed = new Set(index.flows.map((flow) => flow.name))
  const missing = [...onDisk].filter((name) => !indexed.has(name))
  assert.deepEqual(
    missing, [],
    `台账漏了这些流程, 演示栏与流程界面会对不上: ${missing.slice(0, 8).join(', ')}`,
  )
})

test('action-motion-map: schema 与前端读法一致, 查表函数真能查到东西', () => {
  const map = readJson(MOTION_MAP_PATH)
  if (!map) return

  assert.equal(map.schema, 'ptlc.action-motion-map/v1')

  // 前端 motionMap.js 的查表函数必须在真实产物上工作 —— 字段名漂了这里就该红
  const axisEntry = lookupAction(map, 'feedlift.feed_raise')
  assert.equal(axisEntry?.kind, 'axis')
  assert.equal(typeof axisEntry.axis, 'string')
  assert.equal(Number.isFinite(axisEntry.toMm), true)

  const fixedEntry = lookupAction(map, 'collect.clamp')
  assert.equal(fixedEntry?.kind, 'actuator')
  assert.equal(Number.isFinite(fixedEntry.value), true)

  const argEntry = lookupAction(map, 'photoscrape.press_cylinder')
  assert.equal(argEntry?.kind, 'actuator')
  assert.equal(typeof argEntry.arg, 'string')

  const lidEntry = lookupAction(map, 'develop.plate_extend')
  assert.equal(lidEntry?.kind, 'tank-lid')

  assert.equal(isIgnored(map, 'robot.query'), true)
  assert.equal(isIgnored(map, 'feedlift.feed_raise'), false)

  // 缸号 1-4 = 架1, 5-8 = 架2(配对真源是 rig_map.tanks.first_rack)
  assert.equal(tankLidLinkage(map, 1), 'dev_t1_cyl1')
  assert.equal(tankLidLinkage(map, 5), 'dev_t2_cyl1')
  assert.equal(tankLidLinkage(map, 8), 'dev_t2_cyl4')
})

test('action-motion-map: 映射到的机构/轴都是 manifest 里**声明过**的 id', () => {
  const map = readJson(MOTION_MAP_PATH)
  const manifest = readJson(path.join(WORKSPACE_ROOT, 'models', 'device-manifest.official-cr5.json'))
  if (!map || !manifest) return

  const axisIds = new Set((manifest.axes || []).map((axis) => axis.id))
  for (const [action, entry] of Object.entries(map.stationAxisActions || {})) {
    assert.ok(axisIds.has(entry.axis), `${action} 映射到 manifest 里不存在的轴: ${entry.axis}`)
  }

  // 判据是"声明过"而不是"已绑定几何"。多数气缸目前 rigged:false —— 只在
  // realtime.mechanisms 里有声明, 不进 manifest.actuators; 片段照播、气缸不动,
  // 这是既有的"data-only 不驱动几何"纪律, 不是缺陷。
  // 但**打错的 id 两处都不会有**, 那才是本用例要拦的东西。
  const declared = new Set([
    ...(manifest.actuators || []).map((item) => item.id),
    ...((manifest.realtime || {}).mechanisms || []).map((item) => item.id),
  ])
  for (const table of ['cylinderActions', 'cylinderActionsFixed']) {
    for (const [action, entry] of Object.entries(map[table] || {})) {
      assert.ok(
        declared.has(entry.id),
        `${action} 映射到一个 manifest 从未声明的机构 id: ${entry.id}(多半是打错了)`,
      )
    }
  }

  const linkageIds = new Set([
    ...(manifest.linkages || []).map((item) => item.id),
    ...((manifest.realtime || {}).mechanisms || []).map((item) => item.id),
  ])
  for (const [tank, linkageId] of Object.entries(map.tankLidLinkage || {})) {
    assert.ok(linkageIds.has(linkageId), `${tank} 号缸的缸盖联动组未声明: ${linkageId}`)
  }
})
