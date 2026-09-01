/**
 * 功能: 夹爪三态的**全语料**产物门禁 —— 遍历 clips/ 整个目录, 不按族展开.
 *
 * 为什么必须按目录走而不是按族走: clipFamilies.test.js 的 holdValue 检查只看**一个**样本
 * 片段 (transfer.tray.collector.to_staging.slot3), 而 200 多个 flow.* 片段没有任何族会
 * 展开到。2026-08-05 实测: 270 个片段共 103 个"夹爪夹持"步骤, 其中 **79 个发的是 0.0
 * (= 张开态)** —— 小夹爪 46 个合爪步骤无一会动。全程零报错、零日志, 时间轴上那一步还
 * 照样占 0.4 秒, 用户看到的就是"小夹爪没有闭合动画"。
 *
 * 病根在 clip_compiler 的 _hold_value: 它只从转移路线取值, 而 flow.* 片段没有路线可取,
 * 于是恒返回 0.0。这类缺陷的特征是**产物自洽、指标全绿、只有肉眼能发现**, 唯一拦得住
 * 它的就是一条"把全部产物都过一遍"的断言。
 *
 * 三态真源: three_d/pipeline/rig_map.yaml 的 linkages[] (经 device-manifest 透出),
 * 与 clip_compiler.ClipBuilder._gripper_target、前端 gripSemantics.js 逐字同义。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

import { parseClip } from '../../src/three-d/anim/clipSchema.js'

const WORKSPACE_ROOT = process.env.PTLC_THREE_D_WORKSPACE || 'E:/eit_lab/pTLC_platformUI/eit_ptlc/three_d'
const CLIPS_DIR = path.join(WORKSPACE_ROOT, 'clips')
const MANIFEST_PATH = path.join(WORKSPACE_ROOT, 'models', 'device-manifest.official-cr5.json')
const FLOW_INDEX_PATH = path.join(CLIPS_DIR, 'flow-index.json')

/** 已知欠账的站侧座位条数。修好一条就必须改这个数字 —— 否则欠账会静静地长期存在。
 *  2026-08-06 清零: not-under-col_extend / empty-node-no-geometry 分别由
 *  rig_map station_seats 的 adopt_into 过继与 join 免合并保护修复。 */
const EXPECTED_KNOWN_DEBTS = 0

/** 读 JSON 产物; 不存在返回 null(产物门禁的通用形态: 不在就跳过) */
function readJson(file) {
  if (!fs.existsSync(file)) return null
  return JSON.parse(fs.readFileSync(file, 'utf-8'))
}

/** 每把夹爪的取值域 {id: {open, hold, closed, payloadCloses:Set}}; manifest 缺失时返回 null。
 *  payloadCloses = 逐件闭合值(fit_item_grips 经 payload.closeValue 下发: 瓶颈销贴颈
 *  0.2543 / 粉桶摇篮同心 0.8172, 2026-08-07 定案); holdValue 只剩托盘/实时链兜底。 */
function allowedTargets(manifest) {
  const out = new Map()
  for (const linkage of manifest?.linkages || []) {
    const id = String(linkage.id || '')
    if (!id.startsWith('rob_grip_')) continue
    const hold = Number(linkage.holdValue)
    const closed = Number(linkage.inputRange?.[1])
    assert.ok(Number.isFinite(hold) && hold > 0, `${id} 缺 holdValue —— 夹住载荷的开度不能猜`)
    assert.ok(Number.isFinite(closed), `${id} 缺 inputRange —— 空爪紧闭的开度不能猜`)
    out.set(id, { open: 0, hold, closed, payloadCloses: new Set() })
  }
  for (const att of manifest?.attachments || []) {
    const close = Number(att?.payload?.closeValue)
    const spec = att?.payload && out.get(String(att.payload.grip))
    if (spec && Number.isFinite(close) && close > 0) spec.payloadCloses.add(close)
  }
  return out.size ? out : null
}

/** attach 目标 id -> 逐件闭合值; 无逐件值的载荷(整板托盘)由调用方回落 spec.hold */
function closeValueByPayload(manifest) {
  const out = new Map()
  for (const att of manifest?.attachments || []) {
    const close = Number(att?.payload?.closeValue)
    if (Number.isFinite(close) && close > 0) out.set(String(att.id), close)
  }
  return out
}

/** 遍历全部片段文档 */
function eachClip(visit) {
  for (const file of fs.readdirSync(CLIPS_DIR)) {
    if (!file.endsWith('.yaml')) continue
    const raw = fs.readFileSync(path.join(CLIPS_DIR, file), 'utf-8')
    visit(file, parseClip(raw))
  }
}

test('全语料: 夹爪开度只能取三态之一, 且"夹爪夹持"绝不发张开值', () => {
  const manifest = readJson(MANIFEST_PATH)
  const allowed = allowedTargets(manifest)
  if (!allowed || !fs.existsSync(CLIPS_DIR)) return // 还没跑过管线

  let closes = 0
  let opens = 0
  const seenCloses = new Map([...allowed.keys()].map((id) => [id, new Set()]))
  eachClip((file, doc) => {
    for (const step of doc.steps || []) {
      const linkage = step.do?.linkage
      if (!linkage) continue
      const spec = allowed.get(String(linkage.id))
      if (!spec) continue
      const to = Number(linkage.to)
      const targets = [spec.open, spec.hold, spec.closed, ...spec.payloadCloses]
      assert.ok(
        targets.some((v) => Math.abs(v - to) < 5e-7),
        `${file} 步骤「${step.label}」把 ${linkage.id} 驱到 ${to}, `
        + `不在取值域 {0, ${spec.hold}, ${spec.closed}, 逐件 ${[...spec.payloadCloses].join('/')}} 内`,
      )
      for (const close of spec.payloadCloses) {
        if (Math.abs(close - to) < 5e-7) seenCloses.get(String(linkage.id)).add(close)
      }
      if (step.label === '夹爪夹持') {
        closes += 1
        assert.notEqual(to, spec.open,
          `${file}「夹爪夹持」发了张开值 0 —— 爪子一动不动, 这正是 2026-08 那个静默缺陷`)
      }
      if (step.label === '夹爪张开') {
        opens += 1
        assert.equal(to, spec.open, `${file}「夹爪张开」没回到 GLB 基准态, 实为 ${to}`)
      }
    }
  })
  assert.ok(closes > 0, '一个"夹爪夹持"都没扫到 —— 语料或标签变了, 这条门禁已失效')
  assert.ok(opens > 0, '一个"夹爪张开"都没扫到 —— 语料或标签变了, 这条门禁已失效')
  // 逐件闭合必须真的进语料: 瓶颈 0.2543 与粉桶 0.8172 各至少出现一次 —— 锁住
  // "closeValue 通道断了片段静默退 holdValue"这类回归(manifest 白名单漏收即如此)
  for (const [id, spec] of allowed) {
    for (const close of spec.payloadCloses) {
      assert.ok(seenCloses.get(id).has(close),
        `${id} 的逐件闭合值 ${close} 在整个语料里一次都没出现 —— closeValue 通道断了?`)
    }
  }
})

test('全语料: 两把夹爪都真的用上了三态里的"夹持", 不是只有一把', () => {
  const manifest = readJson(MANIFEST_PATH)
  const allowed = allowedTargets(manifest)
  if (!allowed || !fs.existsSync(CLIPS_DIR)) return

  // 缺陷期的分布正是"只有 rob_grip_plate96 出现过 0.288, rob_grip_vial 一次都没有" ——
  // 单看"有没有非零值"会被大夹爪那 24 个片段蒙混过去, 必须逐爪点名。
  const held = new Set()
  eachClip((_file, doc) => {
    for (const step of doc.steps || []) {
      const linkage = step.do?.linkage
      const spec = linkage && allowed.get(String(linkage.id))
      if (!spec) continue
      const to = Number(linkage.to)
      // "夹持" = holdValue 或任一逐件闭合值(小夹爪的取件已全部逐件化, 0.101 只剩兜底)
      if ([spec.hold, ...spec.payloadCloses].some((v) => Math.abs(v - to) < 5e-7)) {
        held.add(String(linkage.id))
      }
    }
  })
  for (const id of allowed.keys()) {
    assert.ok(held.has(id), `${id} 在整个语料里一次都没用过夹持开度 —— 它夹住东西时不会动`)
  }
})

test('全语料: 空爪紧闭只准出现在换刀段里 —— 真取件被判成空爪会把物料捏穿', () => {
  const manifest = readJson(MANIFEST_PATH)
  const allowed = allowedTargets(manifest)
  if (!allowed || !fs.existsSync(CLIPS_DIR)) return

  // 三态门禁本身拦不住这一类: hold 与 closed 都在合法取值域里, 混用它俩不违反闭集。
  // 2026-08-05 实测正是如此 —— 22 处空爪紧闭里有 18 处是**真取件被误判**
  // (从刮板夹具取收集器、从收集工位取瓶), 全语料闭集检查全绿, 只有人工看上下文才发现。
  //
  // 判据取**结构**而不是标签文字: 空爪紧闭只发生在 robot_tool_put 里 —— 走到刀库、
  // 收拢爪子、快换释放。所以它后面几步内必然出现 tool 原语。真取件后面是一串点位运动,
  // 直到 gripper-open 都不会碰快换。
  const WINDOW = 8
  const offenders = []
  eachClip((file, doc) => {
    const steps = doc.steps || []
    for (let i = 0; i < steps.length; i += 1) {
      const linkage = steps[i].do?.linkage
      const spec = linkage && allowed.get(String(linkage.id))
      if (!spec || Math.abs(Number(linkage.to) - spec.closed) > 1e-9) continue
      const near = steps.slice(i + 1, i + 1 + WINDOW).some((s) => s.do?.tool)
      if (!near) offenders.push(`${file} 步${i}「${steps[i].label}」${linkage.id}`)
    }
  })
  assert.deepEqual(offenders, [],
    `这些空爪紧闭后面 ${WINDOW} 步内没有快换动作, 多半是真取件被判成了空爪 —— `
    + '查 clip_compiler.SEAT_TEMPLATES 是不是漏了那个取放脚本')
})

test('全语料: 每个 attach 事件之前最近的那次合爪必须是"夹持"而不是空爪紧闭', () => {
  const manifest = readJson(MANIFEST_PATH)
  const allowed = allowedTargets(manifest)
  if (!allowed || !fs.existsSync(CLIPS_DIR)) return

  // 把"夹爪值"与"载荷交接"绑死: 载荷跟手的那一刻爪子必须处在**这件载荷**的夹持开度上
  // (逐件: 瓶颈 0.2543 / 粉桶 0.8172 / 无逐件值的整板回落 holdValue)。
  // 任何一边单独漂了, 另一边就会把它顶出来。
  const closeByPayload = closeValueByPayload(manifest)
  let checked = 0
  eachClip((file, doc) => {
    let lastClose = null
    for (const step of doc.steps || []) {
      const linkage = step.do?.linkage
      const spec = linkage && allowed.get(String(linkage.id))
      if (spec && Number(linkage.to) !== spec.open) lastClose = { spec, to: Number(linkage.to) }
      if (!step.do?.attach) continue
      assert.ok(lastClose, `${file}: attach 之前没有任何合爪 —— 载荷凭空跟手`)
      const expected = closeByPayload.get(String(step.do.attach.id)) ?? lastClose.spec.hold
      assert.ok(Math.abs(lastClose.to - expected) < 5e-7,
        `${file}: attach ${step.do.attach.id} 时夹爪停在 ${lastClose.to}, `
        + `应为该载荷的夹持开度 ${expected}`)
      checked += 1
    }
  })
  assert.ok(checked > 0, '一个 attach 都没扫到 —— 转移片段没编出来, 这条门禁已失效')
})

test('全语料: attach/detach 必须成对, 片段结束时手上不得还挂着载荷', () => {
  if (!fs.existsSync(CLIPS_DIR)) return

  // 既有的 clipFamilies.test.js 只覆盖 index.families 展开的那几十个片段, 200 个 flow.*
  // 一个都不查 —— 而"取了不放"正是复合流程被改坏时最先出现的形状。
  let pairs = 0
  eachClip((file, doc) => {
    let carried = null
    for (const step of doc.steps || []) {
      const attach = step.do?.attach
      const detach = step.do?.detach
      if (attach) {
        assert.equal(carried, null,
          `${file}: 爪里已经有 ${carried} 却又 attach ${attach.id} —— 取放不成对`)
        carried = String(attach.id)
      }
      if (detach) {
        if (detach.snap === true && String(detach.parent) === 'TOOL_MOUNT') {
          // 「起手·持件在爪」(编译器 preload_payload): snap-dock 到腕上是"本段开场时
          // 件已在爪中"的**声明**, 语义上等于取件, 不是释放 —— 放件半程片段(put 族)
          // 都以它开场, 按老规则会被误判成"无中生有的 detach"。
          assert.equal(carried, null,
            `${file}: 爪里已经有 ${carried} 却又声明起手持件 ${detach.id} —— 取放不成对`)
          carried = String(detach.id)
        } else if (detach.snap === true) {
          // 「目的实例就位」(编译器 instance-swap): snap-dock 到目的父级是把目的实例
          // 摆进场景的声明, 载荷不经过爪 —— 爪内状态不变, 也不计入取放对。真实放件
          // 从不带 snap (全语料仅这两种声明用它), 落到下面严格分支的仍是真 detach。
        } else {
          assert.equal(carried, String(detach.id),
            `${file}: detach ${detach.id} 但爪里是 ${carried} —— 取放不成对`)
          carried = null
          pairs += 1
        }
      }
    }
    // 取件半程(operation 名带 pick 的 SEAT_TEMPLATES 族)按设计**持件收尾**: 放件在
    // 下一段流程, 那段以「起手·持件在爪」开场(见上面的 snap-dock 分支)。半程之外的
    // 流程仍然必须空爪收尾 —— "取了不放"正是复合流程被改坏时最先出现的形状。
    const isPickHalf = String(doc.operation?.name || doc.name || '').includes('pick')
    if (!isPickHalf) {
      assert.equal(carried, null, `${file}: 片段结束时载荷 ${carried} 仍在爪里`)
    }
  })
  assert.ok(pairs > 0, '一对 attach/detach 都没扫到 —— 语料没生成, 这条门禁已失效')
})

test('演示页「转移」分组: 每个片段都必须有真实的载荷交接', () => {
  const index = readJson(FLOW_INDEX_PATH)
  const manifest = readJson(MANIFEST_PATH)
  if (!index || !manifest || !fs.existsSync(CLIPS_DIR)) return

  // 这条就是 2026-08-06 那个缺陷的直接反面: 编译器对所有 flow 片段传 transfer=None,
  // 于是「转移」分组 9 条流程 44 个片段 attach 全为 0 —— 机械臂走位、夹爪开合都对,
  // 爪子里什么都没有。用户逐条看演示时报的"虚空转运"就是它。
  const group = (index.flows || []).filter((flow) => flow.group === '05_transfer'
    && flow.status === 'ok')
  assert.ok(group.length >= 9,
    `「转移」分组只有 ${group.length} 条 ok 流程(期望 ≥9) —— 台账或分组名变了`)

  let checked = 0
  for (const flow of group) {
    for (const clip of flow.clips || []) {
      const file = path.join(CLIPS_DIR, `${clip.clipName}.yaml`)
      if (!fs.existsSync(file)) continue
      const doc = parseClip(fs.readFileSync(file, 'utf-8'))
      const attach = (doc.steps || []).filter((step) => step.do?.attach).length
      assert.ok(attach >= 1,
        `${clip.clipName} 一次 attach 都没有 —— 这就是"虚空转运": 机械臂走位、夹爪开合`
        + '都对, 但爪子里什么都没有。查 clip_compiler.emit_tool_action 的载荷交接闸门')
      checked += 1
    }
  }
  assert.ok(checked >= 40,
    `只查到 ${checked} 个「转移」片段(期望 ≥40) —— 语料没编全, 这条门禁已失效`)
})

test('全语料: 机构 id 必须在 manifest 里, 或在该片段的 dataOnlyMechanisms 里点名', () => {
  const manifest = readJson(MANIFEST_PATH)
  if (!manifest || !fs.existsSync(CLIPS_DIR)) return

  // "没几何"与"打错 id"今天长得一模一样(前端 setActuator 查不到条目都是静默返回 false)。
  // 分开之后, 前者是一份看得见的清单, 后者编译期就报红。
  const rigged = new Set([
    ...(manifest.actuators || []).map((item) => String(item.id)),
    ...(manifest.linkages || []).map((item) => String(item.id)),
  ])
  let checked = 0
  eachClip((file, doc) => {
    const dataOnly = new Set((doc.compiled?.dataOnlyMechanisms || []).map(String))
    for (const step of doc.steps || []) {
      for (const kind of ['actuator', 'linkage']) {
        const body = step.do?.[kind]
        if (!body) continue
        const id = String(body.id)
        assert.ok(rigged.has(id) || dataOnly.has(id),
          `${file} 步骤「${step.label}」驱动 ${id}, 它既不在 manifest 的 actuators/linkages `
          + '里, 也没被该片段的 compiled.dataOnlyMechanisms 点名 —— 多半是打错了 id')
        checked += 1
      }
    }
  })
  assert.ok(checked > 0, '一个机构步都没扫到 —— 语料没生成, 这条门禁已失效')
})

test('全语料: 片段的 home 机构键集必须恰好等于 manifest 的机构集', () => {
  const manifest = readJson(MANIFEST_PATH)
  if (!manifest || !fs.existsSync(CLIPS_DIR)) return

  // 漏一个机构的表现是它在所有片段里都停在 CAD 基位, 而画面看着完全正常 ——
  // 2026-08-06 之前 col_lift(264/270 段停在落位)与 col_clamp(263/270 段停在紧闭)就是这样。
  // 多一个(比如把 rigged:false 的 data-only 机构塞进来)同样要拦: 那会建一条永远写不进
  // 几何的空通道。
  const want = {
    actuators: new Set((manifest.actuators || []).map((item) => String(item.id))),
    linkages: new Set((manifest.linkages || []).map((item) => String(item.id))),
  }
  let checked = 0
  eachClip((file, doc) => {
    // 手写片段不归编译器管(develop.lid_cycle 只声明它自己要用的 8 个缸盖)
    if (!doc.compiled) return
    for (const key of ['actuators', 'linkages']) {
      const got = new Set(Object.keys(doc.home?.[key] || {}))
      assert.deepEqual([...got].sort(), [...want[key]].sort(),
        `${file} 的 home.${key} 与 manifest 的机构集对不上 —— 漏的那些会停在 CAD 基位`)
    }
    checked += 1
  })
  assert.ok(checked > 0, '一个编译产物都没扫到 —— 语料没生成, 这条门禁已失效')
})

test('全语料: state 目标必须在 manifest.states 里声明过', () => {
  const manifest = readJson(MANIFEST_PATH)
  if (!manifest || !fs.existsSync(CLIPS_DIR)) return

  // 拦 INV_STAGING_B_ITEM_3_ITEM_1 这类"按托盘规则给单件拼孔件"拼出来的假 id ——
  // 发出去之后前端 setState 查不到 stateSpecs 只会静默 no-op。
  const declared = new Set((manifest.states || []).map((item) => String(item.id)))
  let checked = 0
  eachClip((file, doc) => {
    for (const step of doc.steps || []) {
      const body = step.do?.state
      if (!body) continue
      assert.ok(declared.has(String(body.id)),
        `${file} 步骤「${step.label}」把 ${body.id} 置显隐, 但 manifest.states 里没有它`)
      checked += 1
    }
  })
  assert.ok(checked > 0, '一个 state 步都没扫到 —— 语料没生成, 这条门禁已失效')
})

test('站侧座位: 每条都要有配套的 state; 已知欠账条数被锁死', () => {
  const manifest = readJson(MANIFEST_PATH)
  if (!manifest) return

  // 站侧座位(seat 是定值座名, 不含冒号)引用的是 GLB 里的 CAD 原生零件。
  // 少了 state 条目它们就**永远可见** —— 同一只瓶子会在收集工位和中转 B 同时出现。
  const stateIds = new Set((manifest.states || []).map((item) => String(item.id)))
  const stationSeats = (manifest.attachments || []).filter(
    (item) => item.payload?.seat && !String(item.payload.seat).includes(':'))
  assert.ok(stationSeats.length >= 3,
    `站侧座位只有 ${stationSeats.length} 条(期望 ≥3) —— rig_map.station_seats 少了`)
  for (const item of stationSeats) {
    assert.ok(stateIds.has(String(item.id)),
      `站侧座位 ${item.id} 没有配套的 manifest.states 条目 —— 它会永远可见`)
  }
  const debts = stationSeats.filter((item) => item.payload?.knownDebt)
  assert.equal(debts.length, EXPECTED_KNOWN_DEBTS,
    `站侧座位的已知欠账有 ${debts.length} 条, 期望 ${EXPECTED_KNOWN_DEBTS} 条`
    + `(${debts.map((item) => `${item.id}:${item.payload.knownDebt}`).join(', ')}) —— `
    + '修好一条就把 EXPECTED_KNOWN_DEBTS 减一, 新增欠账要先在 rig_map 的白名单里点名')
})
