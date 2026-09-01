/**
 * 功能: 演示页入参比对的单元测试(demo/flowInputs.js).
 *
 * 这三个坑都会让"按这组入参编这一条"按钮在错误的时刻出现或消失, 而画面完全正常、
 * 控制台一行错都没有 —— 正是本仓最难查的那一类。逐条钉死:
 *   1. 面板值全是 String() 化的, 片段里是真类型;
 *   2. 空串是"取默认"而不是空值;
 *   3. 片段的 operation.inputs 键比面板多(io:var/out 也被烘了进去)。
 *
 * 第 3 条用**真实的 flow.sampling_execute** 做样本: 它片段侧 22 键、面板侧 17 键,
 * 多出 5 个。拿真样本而不是手捏的, 是因为"多出几个键"这件事本身就是从真产物里发现的。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { inputsDiffer, matchVariantIndex } from '../../src/three-d/demo/flowInputs.js'

const CLIPS_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'three_d', 'clips',
)

/** collect_execute 的面板变量(照 config/operation/04_collect/collect_execute.yaml 的 io:in) */
const COLLECT_VARS = [
  { name: 'solvent_volume_ml', default: 0.1, type: 'FLOAT' },
  { name: 'liquid_repeat_count', default: 1, type: 'INT' },
]

test('坑1: 面板的字符串与片段的真类型必须判相同', () => {
  const clip = { solvent_volume_ml: 0.1, liquid_repeat_count: 1 }
  assert.equal(inputsDiffer(clip, { solvent_volume_ml: '0.1', liquid_repeat_count: '1' },
    COLLECT_VARS), false)
  // 尾随零、多余空白同样要判相同
  assert.equal(inputsDiffer(clip, { solvent_volume_ml: '0.10', liquid_repeat_count: ' 1 ' },
    COLLECT_VARS), false)
  // 真的改了才判不同
  assert.equal(inputsDiffer(clip, { solvent_volume_ml: '5', liquid_repeat_count: '1' },
    COLLECT_VARS), true)
})

test('坑2: 空串是"取默认", 要拿 default 去比而不是拿空串去比', () => {
  const clip = { solvent_volume_ml: 0.1, liquid_repeat_count: 1 }
  assert.equal(inputsDiffer(clip, { solvent_volume_ml: '', liquid_repeat_count: '' },
    COLLECT_VARS), false, '全部取默认 = 与默认编出来的片段相同')
  // 片段不是按默认编的时候, "取默认"就该判不同
  assert.equal(inputsDiffer({ solvent_volume_ml: 5, liquid_repeat_count: 3 },
    { solvent_volume_ml: '', liquid_repeat_count: '' }, COLLECT_VARS), true)
})

test('坑3: 片段里多出来的 io:var/out 键一律忽略 —— 否则按钮永久常亮', () => {
  // 手捏一份"片段键比面板多"的样本(形状照 default_bindings 的产物)
  const clip = {
    solvent_volume_ml: 0.1,
    liquid_repeat_count: 1,
    // 下面这些是 io:var / io:out, 面板上根本不显示
    aspirate_round_ml: 0.4, aspirate_total_ml: 0, band_end_ml: 0, round_idx: 0,
  }
  assert.equal(inputsDiffer(clip, { solvent_volume_ml: '0.1', liquid_repeat_count: '1' },
    COLLECT_VARS), false, '多出来的键不参与比较')
})

test('坑3(真样本): flow.sampling_execute 的片段键确实比面板多, 且不该判为已改', (t) => {
  const clipPath = path.join(CLIPS_DIR, 'flow.sampling_execute.yaml')
  if (!fs.existsSync(clipPath)) {
    t.skip('片段产物不在盘上(未跑过 --flows), 跳过真样本校验')
    return
  }
  const text = fs.readFileSync(clipPath, 'utf-8')
  // 只取 operation.inputs 那一段, 不引 YAML 依赖
  const block = text.split(/^operation:$/m)[1]?.split(/^\w/m)[0] || ''
  const inputs = {}
  let inInputs = false
  for (const line of block.split(/\r?\n/)) {
    if (/^\s{2}inputs:\s*$/.test(line)) { inInputs = true; continue }
    if (inInputs) {
      const hit = /^\s{4}([A-Za-z_][A-Za-z0-9_]*):\s*(.+)$/.exec(line)
      if (!hit) break
      inputs[hit[1]] = hit[2].trim()
    }
  }
  assert.ok(Object.keys(inputs).length > 0, '没解析出 operation.inputs')

  // 面板只声明其中一部分(这里取两个真实存在的 io:in 变量做代表)
  const panelVars = [
    { name: 'solvent_volume_ml', default: inputs.solvent_volume_ml },
    { name: 'sample_id', default: inputs.sample_id },
  ].filter((item) => item.default !== undefined)
  if (panelVars.length === 0) { t.skip('该片段没有这两个入参, 跳过'); return }

  // 面板照默认值填(String 化) -> 必须判"未改", 尽管片段里还有一堆别的键
  const panel = Object.fromEntries(panelVars.map((item) => [item.name, String(item.default)]))
  assert.equal(inputsDiffer(inputs, panel, panelVars), false,
    '片段多出来的 io:var/out 键让按钮永久常亮')
})

test('缺片段入参时不判已改(装载中/老片段), 不让按钮闪', () => {
  assert.equal(inputsDiffer(null, { solvent_volume_ml: '5' }, COLLECT_VARS), false)
  assert.equal(inputsDiffer({ solvent_volume_ml: 0.1 }, {}, []), false, '没有声明变量就无从比较')
})

// ---------------------------------------------------------------------------
// matchVariantIndex: 参数改回某个已编好的变体就秒切, 不必重编
// ---------------------------------------------------------------------------

const TANK_VARS = [{ name: 'tank', default: 1, type: 'INT' }]

test('matchVariantIndex: 命中已有变体返回下标', () => {
  const entry = {
    clips: [
      { clipName: 'flow.develop_execute.tank1', variant: [{ key: 'tank', value: 1 }] },
      { clipName: 'flow.develop_execute.tank2', variant: [{ key: 'tank', value: 2 }] },
      { clipName: 'flow.develop_execute.tank3', variant: [{ key: 'tank', value: 3 }] },
    ],
  }
  assert.equal(matchVariantIndex(entry, { tank: '2' }, TANK_VARS), 1)
  assert.equal(matchVariantIndex(entry, { tank: 3 }, TANK_VARS), 2)
  assert.equal(matchVariantIndex(entry, { tank: '9' }, TANK_VARS), -1, '没编过的取值应落空')
})

test('matchVariantIndex: 无变体的单条片段, 只有面板全取默认才算命中', () => {
  const entry = { clips: [{ clipName: 'flow.collect_execute', variant: [] }] }
  assert.equal(matchVariantIndex(entry, { solvent_volume_ml: '0.1', liquid_repeat_count: '1' },
    COLLECT_VARS), 0)
  assert.equal(matchVariantIndex(entry, { solvent_volume_ml: '', liquid_repeat_count: '' },
    COLLECT_VARS), 0, '空串取默认同样命中')
  assert.equal(matchVariantIndex(entry, { solvent_volume_ml: '5', liquid_repeat_count: '1' },
    COLLECT_VARS), -1, '改了参数就不该命中那条按默认编的片段')
})

test('matchVariantIndex: 临时片段(--inputs 编出来的)与扇出变体同形, 一样能命中', () => {
  const entry = {
    clips: [
      { clipName: 'flow.collect_execute', variant: [] },
      {
        clipName: 'flow.collect_execute.solvent_volume_ml5.liquid_repeat_count3',
        adhoc: true,
        variant: [
          { key: 'solvent_volume_ml', value: 5, adhoc: true },
          { key: 'liquid_repeat_count', value: 3, adhoc: true },
        ],
      },
    ],
  }
  assert.equal(matchVariantIndex(entry, { solvent_volume_ml: '5', liquid_repeat_count: '3' },
    COLLECT_VARS), 1, '编过一次之后再改回这组参数应当秒切, 不再重编')
  assert.equal(matchVariantIndex(entry, { solvent_volume_ml: '5', liquid_repeat_count: '1' },
    COLLECT_VARS), -1, '只对上一半不算命中')
})

test('matchVariantIndex: 空/缺参不炸', () => {
  assert.equal(matchVariantIndex(null, {}, COLLECT_VARS), -1)
  assert.equal(matchVariantIndex({ clips: [] }, {}, COLLECT_VARS), -1)
})
