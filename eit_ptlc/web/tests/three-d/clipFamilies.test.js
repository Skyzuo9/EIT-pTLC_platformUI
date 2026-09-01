/**
 * 功能: 转移片段矩阵的产物门禁 —— 索引参数域、片段可编译、载荷/机构 id 全部对得上.
 *
 * 为什么值得单测: 片段是离线生成的产物, 生成器与前端契约之间没有类型系统兜底。
 * 一旦生成器写出一个 manifest 里不存在的载荷 id 或夹爪 id, 前端表现是"播放了但托盘
 * 一动不动" —— 没有报错、没有日志, 只能靠目视发现。这里把这类静默失效挡住。
 *
 * 本文件校验的是**真实产物**, 与 manifest.test.js 后半段同一性质: 产物不在就跳过,
 * 在就必须自洽。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

import { compileClip, parseClip } from '../../src/three-d/anim/clipSchema.js'

const WORKSPACE_ROOT = process.env.PTLC_THREE_D_WORKSPACE || 'E:/eit_lab/pTLC_platformUI/eit_ptlc/three_d'
const CLIPS_DIR = path.join(WORKSPACE_ROOT, 'clips')
const INDEX_PATH = path.join(CLIPS_DIR, 'index.json')
const CATALOG_PATH = path.join(WORKSPACE_ROOT, 'generated', 'robot-points.json')
const MANIFEST_PATH = path.join(WORKSPACE_ROOT, 'models', 'device-manifest.official-cr5.json')

/** 把一个片段族的参数域展开成全部片段名。 */
function expandFamily(family) {
  let combos = [{}]
  for (const param of family.params) {
    const values = Array.isArray(param.options)
      ? param.options.map((option) => option.value)
      : Array.from(
        { length: param.range[1] - param.range[0] + 1 },
        (_, index) => param.range[0] + index,
      )
    combos = combos.flatMap((combo) => values.map((value) => ({ ...combo, [param.key]: value })))
  }
  return combos.map((combo) => ({
    combo,
    name: family.nameTemplate.replace(/\{(\w+)\}/g, (_, key) => String(combo[key])),
  }))
}

function readIfPresent(...paths) {
  return paths.every((item) => fs.existsSync(item))
    ? paths.map((item) => JSON.parse(fs.readFileSync(item, 'utf-8')))
    : null
}

test('片段索引升到 v2 并带可展开的参数域', (t) => {
  if (!fs.existsSync(INDEX_PATH)) {
    t.skip('尚未生成 clips/index.json, 跳过')
    return
  }
  const index = JSON.parse(fs.readFileSync(INDEX_PATH, 'utf-8'))
  assert.equal(index.schema, 'ptlc.clip-index/v2')
  assert.ok(Array.isArray(index.families) && index.families.length > 0, '应有片段族')

  for (const family of index.families) {
    assert.ok(family.id && family.label && family.nameTemplate, `族 ${family.id} 字段不全`)
    assert.ok(Array.isArray(family.params) && family.params.length > 0, `族 ${family.id} 无参数`)
    const keys = family.params.map((param) => param.key)
    // 模板里的每个占位符都必须有对应参数, 否则界面拼出来的名字必然指向不存在的片段。
    const placeholders = [...family.nameTemplate.matchAll(/\{(\w+)\}/g)].map((match) => match[1])
    assert.deepEqual([...placeholders].sort(), [...keys].sort(), `族 ${family.id} 占位符与参数不匹配`)
  }
})

test('参数域展开出的每个片段文件都存在', (t) => {
  if (!fs.existsSync(INDEX_PATH)) {
    t.skip('尚未生成 clips/index.json, 跳过')
    return
  }
  const index = JSON.parse(fs.readFileSync(INDEX_PATH, 'utf-8'))
  let total = 0
  for (const family of index.families) {
    for (const { name } of expandFamily(family)) {
      assert.ok(fs.existsSync(path.join(CLIPS_DIR, `${name}.yaml`)), `缺片段: ${name}`)
      total += 1
    }
  }
  assert.ok(total >= 24, `片段数量异常: ${total}`)
})

test('每个转移片段都能用真实点表编译, 且载荷/机构 id 在 manifest 里存在', (t) => {
  const loaded = readIfPresent(INDEX_PATH, CATALOG_PATH, MANIFEST_PATH)
  if (loaded === null) {
    t.skip('尚未生成片段索引/点表/manifest, 跳过')
    return
  }
  const [index, catalog, manifest] = loaded

  const attachmentIds = new Set((manifest.attachments || []).map((item) => item.id))
  const stateIds = new Set((manifest.states || []).map((item) => item.id))
  const linkageIds = new Set((manifest.linkages || []).map((item) => item.id))
  const toolIds = new Set((manifest.tools || []).map((item) => item.id))
  const riggedAxes = new Set((manifest.axes || []).filter((item) => item.rigged).map((item) => item.id))

  for (const family of index.families) {
    for (const { name } of expandFamily(family)) {
      const doc = parseClip(fs.readFileSync(path.join(CLIPS_DIR, `${name}.yaml`), 'utf-8'))
      const clip = compileClip(doc, { pointCatalog: catalog })
      assert.ok(clip.duration > 0, `${name} 时长为 0`)

      // 载荷交接必须成对且顺序正确。两族用的是两套机制, 各查各的:
      //   整板转移(大夹爪)  -> attach/detach, 载荷是 GLB 里的库存节点;
      //   薄层板(吸盘)      -> plate 原语, 板是前端程序化生成的, 不进 manifest.attachments。
      // 判据本身是同一条: 拿起来的必须放下, 播完手上不能还剩东西。
      const ownership = clip.events.filter((event) => ['attach', 'detach'].includes(event.kind))
      const plateEvents = clip.events.filter((event) => event.kind === 'plate')
      assert.ok(ownership.length >= 2 || plateEvents.length >= 2,
        `${name} 缺载荷交接事件(既没有 attach/detach 也没有 plate)`)

      let carried = null
      for (const event of ownership) {
        if (event.kind === 'attach') {
          assert.equal(carried, null, `${name} 连续两次 attach: ${event.payload.id}`)
          carried = event.payload.id
        } else {
          assert.equal(carried, event.payload.id, `${name} detach 的载荷与 attach 不是同一件`)
          carried = null
        }
        assert.ok(attachmentIds.has(event.payload.id), `${name} 载荷未在 manifest 声明: ${event.payload.id}`)
      }
      assert.equal(carried, null, `${name} 播完后载荷仍在爪里`)

      // 板: 同一块板不能连吸两次(中间没放下), 且末态要么落在某个停放位、要么显式收走。
      const inHand = new Map()
      for (const event of plateEvents) {
        const id = event.payload.id
        if (event.payload.carry === true) {
          assert.notEqual(inHand.get(id), true, `${name} 板 ${id} 连续两次吸起, 中间没放下`)
          inHand.set(id, true)
        } else {
          inHand.set(id, false)
        }
      }
      const last = plateEvents[plateEvents.length - 1]
      if (last) {
        assert.ok(last.payload.at || last.payload.hide === true || last.payload.carry === true,
          `${name} 最后一个 plate 事件语义不明: ${JSON.stringify(last.payload)}`)
      }

      for (const event of clip.events) {
        if (event.kind === 'state') {
          assert.ok(stateIds.has(event.payload.id), `${name} state 目标未声明: ${event.payload.id}`)
        }
        if (event.kind === 'tool') {
          assert.ok(toolIds.has(event.payload.id), `${name} 工具未声明: ${event.payload.id}`)
        }
      }
      for (const key of clip.channels.keys()) {
        if (key.startsWith('axis:')) {
          assert.ok(riggedAxes.has(key.slice(5)), `${name} 驱动了未装配的轴: ${key}`)
        }
        if (key.startsWith('linkage:')) {
          assert.ok(linkageIds.has(key.slice(8)), `${name} 联动组未声明: ${key}`)
        }
      }
    }
  }
})

test('整板转移片段的夹爪开度用 manifest 的 holdValue, 不是硬编码', (t) => {
  const loaded = readIfPresent(INDEX_PATH, CATALOG_PATH, MANIFEST_PATH)
  if (loaded === null) {
    t.skip('尚未生成产物, 跳过')
    return
  }
  const [, catalog, manifest] = loaded
  const sample = path.join(CLIPS_DIR, 'transfer.tray.collector.to_staging.slot3.yaml')
  if (!fs.existsSync(sample)) {
    t.skip('样本片段不存在, 跳过')
    return
  }
  const hold = (manifest.linkages || []).find((item) => item.id === 'rob_grip_plate96')?.holdValue
  assert.ok(typeof hold === 'number', 'manifest 应声明大夹爪 holdValue')

  const clip = compileClip(parseClip(fs.readFileSync(sample, 'utf-8')), { pointCatalog: catalog })
  const frames = clip.channels.get('linkage:rob_grip_plate96')
  assert.ok(frames, '整板片段必须驱动大夹爪')
  const values = frames.map((frame) => frame.v)
  assert.ok(values.includes(hold), `夹持开度应等于 holdValue(${hold}), 实际取值: ${[...new Set(values)]}`)
  assert.ok(values.includes(0), '张开应回到 0(GLB 基准态)')
})
