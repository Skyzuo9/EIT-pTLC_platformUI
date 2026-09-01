/**
 * 功能: 注射泵 pump/pump_valve 步的**全语料**产物门禁 —— 遍历 clips/ 整个目录.
 *
 * 与 gripperCorpus 同一条立足点: 这类缺陷产物自洽、指标全绿、只有肉眼能发现.
 * 泵这里的具体坑形状:
 *   1. home 漏声明 —— 机构 home 门禁(mechanism_home_of)只覆盖 actuators/linkages,
 *      泵住在 manifest.pumpSyringe.pumps[] 里, **现有 missing 门禁抓不到它**. 漏了的
 *      表现是 rig.home() 清零后"只声明不驱动"的泵开局回 0(气隙凭空消失), 画面正常无报错;
 *   2. id 打错 —— setter 查不到 entry 静默不动, 与 collect.clamp→col_clamp 那次
 *      8 步静默丢失同款;
 *   3. 口号越界 —— 转到一个不存在的口比不转更糟.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

import { parseClip } from '../../src/three-d/anim/clipSchema.js'

const WORKSPACE_ROOT = process.env.PTLC_THREE_D_WORKSPACE || 'E:/eit_lab/pTLC_platformUI/eit_ptlc/three_d'
const CLIPS_DIR = path.join(WORKSPACE_ROOT, 'clips')
const MANIFEST_PATH = path.join(WORKSPACE_ROOT, 'models', 'device-manifest.official-cr5.json')

function readJson(file) {
  if (!fs.existsSync(file)) return null
  return JSON.parse(fs.readFileSync(file, 'utf-8'))
}

function eachClip(visit) {
  for (const file of fs.readdirSync(CLIPS_DIR)) {
    if (!file.endsWith('.yaml')) continue
    const raw = fs.readFileSync(path.join(CLIPS_DIR, file), 'utf-8')
    visit(file, parseClip(raw))
  }
}

/** manifest 里可动泵(rigged 且有柱塞节点)的 {id: valvePorts} 表; 没有泵契约时 null */
function riggedPumps(manifest) {
  const out = new Map()
  for (const pump of manifest?.pumpSyringe?.pumps || []) {
    if (pump.rigged && pump.plungerNode) out.set(String(pump.id), Number(pump.valvePorts) || 0)
  }
  return out.size ? out : null
}

test('全语料: pump/pump_valve 步只准指向可动泵, home 必须覆盖被驱的泵, 口号不越界', () => {
  const manifest = readJson(MANIFEST_PATH)
  const pumps = riggedPumps(manifest)
  if (!pumps || !fs.existsSync(CLIPS_DIR)) return // 还没跑过管线

  let pumpSteps = 0
  eachClip((file, doc) => {
    const homeMl = doc.home?.pump_ml || {}
    const homePort = doc.home?.pump_port || {}
    for (const step of doc.steps || []) {
      const pump = step.do?.pump
      const valve = step.do?.pump_valve
      if (pump) {
        pumpSteps += 1
        const id = String(pump.id)
        assert.ok(pumps.has(id),
          `${file} 步骤「${step.label}」驱了 manifest 里不存在/未装配的泵 ${id} —— `
          + 'setter 会静默不动, 与 col_clamp 那次 8 步丢失同款')
        assert.ok(id in homeMl,
          `${file} 驱了 ${id} 却没在 home.pump_ml 里声明起手体积 —— `
          + 'rig.home() 清零后"只声明不驱动"的续接片段会把气隙抹掉')
      }
      if (valve) {
        const id = String(valve.id)
        assert.ok(pumps.has(id), `${file} 换阀步指向不存在/未装配的泵 ${id}`)
        assert.ok(id in homePort,
          `${file} 换了 ${id} 的阀却没在 home.pump_port 里声明起手口`)
        const total = pumps.get(id)
        assert.ok(Number.isInteger(valve.port) && valve.port >= 1 && (!total || valve.port <= total),
          `${file} 把 ${id} 的阀转到 ${valve.port} 号口, 超出 1..${total}`)
      }
    }
    // 反向: home 里声明的泵必须真实存在(防打错 id 后"声明了却永远不动")
    for (const id of [...Object.keys(homeMl), ...Object.keys(homePort)]) {
      assert.ok(pumps.has(String(id)),
        `${file} 的 home.pump_* 声明了 manifest 里不存在/未装配的泵 ${id}`)
    }
  })
  assert.ok(pumpSteps > 0,
    '整个语料一个 pump 步都没有 —— 要么泵支持坏了, 要么片段没重编, 这条门禁已失效')
})
